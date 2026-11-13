"""Research data store: full daily price histories cached as parquet (one file per ticker).

    python market_data.py update            # refresh prices for the whole research universe

The store lives in MARKET_DATA_DIR (default `market_data/`, gitignored). Prices are
split/dividend-adjusted daily OHLCV from Yahoo, validated exactly like data_engine
(`clean_bulk_frame`: drop bars that do not exist for a stock, reject partial NaNs).

Adjusted prices change retroactively after every dividend/split, so a stale file is
re-downloaded in full rather than appended to (appending would mix two adjustment bases).
"""

import json
import os
import sys
from datetime import date, timedelta

import pandas as pd

from data_engine import REQUIRED_COLUMNS, clean_bulk_frame, normalize_ticker

DATA_DIR = os.environ.get("MARKET_DATA_DIR", "market_data")
PRICE_DIR = os.path.join(DATA_DIR, "prices")
PRICE_START = "2000-01-01"   # 5 years of warm-up before the 2005 development start
BENCHMARKS = ("SPY", "RSP", "QQQ", "IWM", "MDY", "^VIX")
CHUNK = 100


def price_path(ticker):
    return os.path.join(PRICE_DIR, f"{ticker.replace('^', '_')}.parquet")


def _manifest_path():
    return os.path.join(DATA_DIR, "prices_manifest.json")


def load_manifest():
    if not os.path.exists(_manifest_path()):
        return {"downloaded": {}, "missing": {}, "last_bar": {}}
    with open(_manifest_path()) as fh:
        manifest = json.load(fh)
    if "last_bar" not in manifest:          # manifests written before last-bar tracking
        manifest["last_bar"] = {}
    return manifest


def _save_manifest(manifest):
    with open(_manifest_path(), "w") as fh:
        json.dump(manifest, fh, indent=0, sort_keys=True)


RECENTLY_ACTIVE_DAYS = 10


def _behind(manifest, ticker, wanted):
    """True when a still-trading ticker's history ends before the newest bar of the others.

    A download can succeed yet end a day early (Yahoo had not finalized yesterday's bar), and
    "downloaded today" alone would then keep the short history all day. Long-delisted tickers
    (last bar more than RECENTLY_ACTIVE_DAYS behind) are not refetched for this."""
    if ticker not in manifest["last_bar"]:
        return ticker in manifest["downloaded"]           # unknown end (older manifest): refetch once
    bars = [manifest["last_bar"][t] for t in wanted if t in manifest["last_bar"]]
    newest = date.fromisoformat(max(bars))
    last = date.fromisoformat(manifest["last_bar"][ticker])
    return newest - timedelta(days=RECENTLY_ACTIVE_DAYS) < last < newest


def update_prices(tickers, max_age_days=0):
    """Download (in bulk) every ticker whose cached history is missing or older than max_age_days.

    Returns {"updated": [...], "missing": [...]} — `missing` = Yahoo returned no usable
    history (typically delisted symbols; reported by the coverage report, never filled).
    """
    import yfinance as yf

    os.makedirs(PRICE_DIR, exist_ok=True)
    manifest = load_manifest()
    today = date.today()
    wanted = list(dict.fromkeys(normalize_ticker(t) if not t.startswith("^") else t for t in tickers))
    stale = [t for t in wanted
             if t not in manifest["downloaded"]
             or (today - date.fromisoformat(manifest["downloaded"][t])).days > max_age_days
             or _behind(manifest, t, wanted)]
    end = (today + timedelta(days=1)).isoformat()
    updated = []
    for first in range(0, len(stale), CHUNK):
        chunk = stale[first:first + CHUNK]
        raw = yf.download(chunk, start=PRICE_START, end=end, auto_adjust=True, progress=False,
                          group_by="ticker", threads=True)
        present = set(raw.columns.get_level_values(0)) if raw is not None and not raw.empty else set()
        for ticker in chunk:
            frame = clean_bulk_frame(raw[ticker]) if ticker in present else None
            if frame is None:
                manifest["missing"][ticker] = today.isoformat()
                continue
            frame.to_parquet(price_path(ticker))
            manifest["downloaded"][ticker] = today.isoformat()
            manifest["last_bar"][ticker] = frame.index[-1].strftime("%Y-%m-%d")
            manifest["missing"].pop(ticker, None)
            updated.append(ticker)
        _save_manifest(manifest)
        print(f"  prices: {min(first + CHUNK, len(stale))}/{len(stale)} requested, {len(updated)} saved",
              flush=True)
    return {"updated": updated, "missing": sorted(t for t in wanted if t in manifest["missing"])}


def load_prices(tickers):
    """{ticker: OHLCV frame} for every ticker that has a cached history (others are skipped)."""
    frames = {}
    for ticker in tickers:
        path = price_path(ticker)
        if os.path.exists(path):
            frame = pd.read_parquet(path)
            frame.index.name = "Date"
            frames[ticker] = frame[REQUIRED_COLUMNS]
    return frames


def panel(frames, field):
    """One field (e.g. 'Close') as a dates x tickers DataFrame (NaN where a stock has no bar)."""
    return pd.DataFrame({t: df[field] for t, df in frames.items()}).sort_index()


def _cli(argv):
    import universe_history

    if argv[:1] != ["update"]:
        print("usage: python market_data.py update")
        sys.exit(1)
    tickers = universe_history.research_universe() + list(BENCHMARKS)
    result = update_prices(tickers)
    print(f"updated {len(result['updated'])}, missing {len(result['missing'])}")


if __name__ == "__main__":
    _cli(sys.argv[1:])
