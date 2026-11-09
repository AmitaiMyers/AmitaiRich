"""Point-in-time earnings surprises from Yahoo's earnings calendar (consensus vs reported EPS).

    python earnings_pit.py update

For each report Yahoo gives the consensus EPS estimate going into the announcement, the
reported EPS and the surprise % — free, back to ~2005 for most large companies.

Availability (no look-ahead): a report released before the 09:30 New York open is usable at
that day's close; one released during or after the session (typically 16:00) is usable only
from the NEXT business day's close. Signals are decided at the close and filled the next open.

Output: MARKET_DATA_DIR/fundamentals/earnings.parquet
    ticker, announced (NY time), available (date), estimate, reported, surprise_pct
"""

import os
import sys
import time

import pandas as pd
import requests

DATA_DIR = os.environ.get("MARKET_DATA_DIR", "market_data")
FUND_DIR = os.path.join(DATA_DIR, "fundamentals")
BY_TICKER_DIR = os.path.join(FUND_DIR, "earnings_by_ticker")
MARKET_OPEN = pd.Timedelta(hours=9, minutes=30)
LIMIT = 100           # ~25 years of quarterly reports
PAUSE = 0.3


def availability(announced):
    """First date whose CLOSE comes after the announcement (see module docstring)."""
    local = announced.tz_convert("America/New_York")
    day = local.normalize().tz_localize(None)
    if local - local.normalize() < MARKET_OPEN:
        return day
    return day + pd.offsets.BDay(1)


def fetch_one(ticker):
    """Reported earnings for one ticker (empty frame when Yahoo has none)."""
    import yfinance as yf

    dates = yf.Ticker(ticker).get_earnings_dates(limit=LIMIT)
    columns = ["announced", "available", "estimate", "reported", "surprise_pct"]
    if dates is None or dates.empty:
        return pd.DataFrame(columns=columns)
    reported = dates.dropna(subset=["Reported EPS"])
    return pd.DataFrame({
        "announced": reported.index,
        "available": [availability(ts) for ts in reported.index],
        "estimate": reported["EPS Estimate"].to_numpy(dtype=float),
        "reported": reported["Reported EPS"].to_numpy(dtype=float),
        "surprise_pct": reported["Surprise(%)"].to_numpy(dtype=float),
    })


def _path(ticker):
    return os.path.join(BY_TICKER_DIR, f"{ticker}.parquet")


def update_earnings(tickers, max_age_days=7):
    """Fetch per ticker (cached). Per-ticker network/data failures are reported, not raised."""
    from yfinance.exceptions import YFException

    os.makedirs(BY_TICKER_DIR, exist_ok=True)
    now = time.time()
    todo = [t for t in tickers if not os.path.exists(_path(t))
            or now - os.path.getmtime(_path(t)) > max_age_days * 86400]
    failed = []
    for k, ticker in enumerate(todo, start=1):
        try:
            frame = fetch_one(ticker)
        except (YFException, requests.exceptions.RequestException, KeyError, ValueError) as exc:
            failed.append(f"{ticker} ({type(exc).__name__})")
            continue
        frame.to_parquet(_path(ticker))
        time.sleep(PAUSE)
        if k % 100 == 0 or k == len(todo):
            print(f"  earnings: {k}/{len(todo)}", flush=True)
    return failed


def build_table(tickers):
    frames = [pd.read_parquet(_path(t)).assign(ticker=t) for t in tickers if os.path.exists(_path(t))]
    table = pd.concat([f for f in frames if len(f)], ignore_index=True)
    table.to_parquet(os.path.join(FUND_DIR, "earnings.parquet"))
    return table


def load_earnings():
    return pd.read_parquet(os.path.join(FUND_DIR, "earnings.parquet"))


def _cli(argv):
    import market_data
    import universe_history

    if argv[:1] != ["update"]:
        print("usage: python earnings_pit.py update")
        sys.exit(1)
    priced = [t for t in universe_history.research_universe() if os.path.exists(market_data.price_path(t))]
    failed = update_earnings(priced)
    table = build_table(priced)
    print(f"earnings rows {len(table)}, tickers {table['ticker'].nunique()}, failed {len(failed)}: {failed[:10]}")


if __name__ == "__main__":
    _cli(sys.argv[1:])
