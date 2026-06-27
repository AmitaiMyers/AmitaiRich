"""Daily 'scan today' — the production use of the simulator.

Two questions a trader asks each day:
  1. Across the whole market, which stocks fire a BUY on the most recent bar?
     -> scan_for_buys(): runs the algorithm's scan_and_buy on each ticker's latest
        candle and returns the candidates (possibly none).
  2. For a stock I already hold, should I sell today?
     -> check_holding(): reconstructs the position and runs the stop + sell logic.

Only the latest bar's decision matters, but the algorithm still needs warmup
history, so we fetch a recent window up to `as_of`. Per-ticker data failures (late
listings, bad symbols) are collected and returned, not raised — same boundary
policy as batch.py. A ConfigurationError (a setup mistake) is NOT caught.

CLI:  python scan_today.py   (the full daily routine: a single BUY list across the
S&P 500, Nasdaq-100 and watchlist, de-duplicated and ranked best-to-least, then a
HOLD/SELL check on every open position in positions.csv — BUYs first, then SELLs)
"""

import os
from datetime import date

import pandas as pd

from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data
from errors import InsufficientDataError
from simulation import Position
import universe

# The strategy chosen by the 300-train / 100-test portfolio research (see
# research_26062026.md): the Vol-Adjusted Momentum Rider. BUY when price is above
# its 200-day SMA and its volatility-adjusted 6-month momentum
# (ROC(126) / (ATR(20)/price)) clears a high bar; HOLD until price closes back
# below the 200-day SMA (with a wide ATR catastrophe stop underneath). It beat the
# old Roof-breakout default decisively out-of-sample (Sharpe 0.91 vs 0.54) by
# holding winners ~200 days instead of churning, which also makes it cost-robust.
DEFAULT_BUY = "Vol-Adjusted Momentum Rider"
DEFAULT_CONFIG = {"mom_lookback": 126, "score_threshold": 12.0}
# The research sized risk off this 'widest' (most room) catastrophe stop; the SELL
# check (check_holding) should use the same mode to match the backtested system.
DEFAULT_STOP_MODE = "widest"

# Open positions to run the daily HOLD/SELL check against (ticker, entry_date,
# entry_price). Edit this file as you enter/exit trades.
POSITIONS_CSV = "positions.csv"


def _window(as_of, lookback_days):
    """Return (start_str, end_str) for a recent window ending the bar after as_of.

    yfinance's `end` is exclusive, so we add a day to make sure the as_of bar is
    included once it exists.
    """
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = end - pd.Timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d"), (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def scan_for_buys(tickers, algorithm, as_of=None, lookback_days=600,
                  interval="1d", use_cache=True):
    """Return (hits, errors) DataFrames: stocks whose latest bar is a BUY.

    `hits` has ticker, date, close, plus the algorithm's `describe` facts (the roof
    it broke and the volume surge). `errors` lists tickers with no usable data.
    """
    start_str, end_str = _window(as_of, lookback_days)
    needed = algorithm.warmup_bars() + 1
    hits, errors = [], []

    # De-duplicate (some universe CSVs list a symbol more than once) so each name
    # is scanned and reported once, and we don't waste a fetch on repeats.
    tickers = list(dict.fromkeys(t.strip().upper() for t in tickers))
    for ticker in tickers:
        try:
            df = fetch_data(ticker, start_str, end_str, interval=interval, use_cache=use_cache)
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})
            continue
        if len(df) < needed:
            continue
        if algorithm.scan_and_buy(df):
            row = {"ticker": ticker,
                   "date": df.index[-1].strftime("%Y-%m-%d"),
                   "close": round(float(df["Close"].iloc[-1]), 2)}
            if hasattr(algorithm, "describe"):
                row.update(algorithm.describe(df))
            hits.append(row)

    hits_df = pd.DataFrame(hits)
    # Rank the strongest candidate first by whichever strength fact the algorithm
    # reports: the vol-adjusted momentum score (current default) or volume surge.
    for strength_col in ("vol_adj_score", "vol_x_avg"):
        if not hits_df.empty and strength_col in hits_df.columns:
            hits_df = hits_df.sort_values(strength_col, ascending=False).reset_index(drop=True)
            break
    return hits_df, pd.DataFrame(errors)


def check_holding(ticker, algorithm, entry_date, entry_price=None, as_of=None,
                  lookback_days=900, stop_mode=DEFAULT_STOP_MODE, interval="1d", use_cache=True):
    """Return today's HOLD/SELL verdict for a position you already hold.

    Reconstructs the position: the stop is what the algorithm would have set at the
    entry bar; bars_held is counted from the entry date. Sells if today's bar hits
    that stop OR the algorithm's discretionary exit fires.
    """
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = (pd.Timestamp(entry_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = fetch_data(ticker, start, end_str, interval=interval, use_cache=use_cache)

    entry_index = int(df.index.searchsorted(pd.Timestamp(entry_date)))
    if entry_index >= len(df):
        raise PER_TICKER_ERRORS[0](f"{ticker}: entry date {entry_date} is after the last bar.")
    if (entry_index + 1) < algorithm.warmup_bars():
        # A recent listing without enough history before entry to compute the
        # strategy's stop / exit indicators — surface it as a per-position data
        # skip rather than letting an indicator NaN crash the whole check.
        raise InsufficientDataError(
            f"{ticker}: only {entry_index + 1} bars before entry {entry_date}; "
            f"need {algorithm.warmup_bars()} for the strategy's warmup.")

    entry_slice = df.iloc[: entry_index + 1]
    fill_price = float(entry_price) if entry_price else float(df["Close"].iloc[entry_index])
    stop_price = algorithm.compute_stop(fill_price, entry_slice, stop_mode)
    bars_held = (len(df) - 1) - entry_index

    position = Position(entry_date=str(pd.Timestamp(entry_date).date()), entry_price=fill_price,
                        shares=1.0, stop_price=stop_price, bars_held=bars_held)

    last_close = float(df["Close"].iloc[-1])
    last_low = float(df["Low"].iloc[-1])
    stop_hit = stop_price is not None and last_low <= stop_price
    sell_signal = algorithm.calculate_sell(position, df)

    if stop_hit:
        verdict, reason = "SELL", "stop hit"
    elif sell_signal:
        verdict, reason = "SELL", "exit signal"
    else:
        verdict, reason = "HOLD", "trend intact"

    return {
        "ticker": ticker, "verdict": verdict, "reason": reason,
        "entry_price": round(fill_price, 2), "last_close": round(last_close, 2),
        "open_pnl_%": round((last_close / fill_price - 1) * 100, 1),
        "stop_price": round(stop_price, 2) if stop_price is not None else None,
        "bars_held": bars_held,
    }


def check_positions(algorithm, positions_path=POSITIONS_CSV, as_of=None,
                    interval="1d", use_cache=True):
    """Run the HOLD/SELL check on every open position in a positions CSV.

    The CSV has columns `ticker, entry_date, entry_price`. Each row is reconstructed
    and run through the same stop + sell logic as check_holding. Per-position data
    failures are collected and returned, not raised (same boundary policy as the BUY
    scan). Returns (verdicts, errors) DataFrames with SELLs sorted to the top.
    """
    positions = pd.read_csv(positions_path)
    verdicts, errors = [], []
    for _, row in positions.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        try:
            verdicts.append(check_holding(
                ticker, algorithm, row["entry_date"], entry_price=row["entry_price"],
                as_of=as_of, interval=interval, use_cache=use_cache))
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})

    verdicts_df = pd.DataFrame(verdicts)
    if not verdicts_df.empty:
        # SELLs first (action items at the top), then HOLDs.
        verdicts_df = verdicts_df.sort_values("verdict", ascending=False).reset_index(drop=True)
    return verdicts_df, pd.DataFrame(errors)


# Short tags marking which source list a candidate belongs to (a name can be in
# more than one, e.g. an S&P 500 stock that is also in the Nasdaq-100).
SCOPE_TAGS = {"sp500": "SPX", "nasdaq100": "NDX", "watchlist": "WL"}


def _combined_universe():
    """All scopes merged into one de-duplicated list, plus a per-ticker source tag.

    Returns (tickers, sources): `tickers` is every unique symbol across the scopes
    (order preserved); `sources[ticker]` is a tag like 'SPX/NDX' showing the lists
    it appears in.
    """
    sources, order = {}, []
    for scope, tag in SCOPE_TAGS.items():
        for raw in universe.get_universe(scope):
            ticker = raw.strip().upper()
            if ticker not in sources:
                sources[ticker] = []
                order.append(ticker)
            if tag not in sources[ticker]:
                sources[ticker].append(tag)
    return order, {ticker: "/".join(tags) for ticker, tags in sources.items()}


def _scan_all(algorithm):
    """Scan every scope as ONE universe and print a single best-to-least ranked list."""
    tickers, sources = _combined_universe()
    print(f"\nScanning {len(tickers)} unique stocks with {DEFAULT_BUY}...", flush=True)
    hits, errors = scan_for_buys(tickers, algorithm)
    print(f"=== BUY candidates, ranked best to least ({len(hits)}) ===")
    if hits.empty:
        print("  (none today)")
    else:
        hits = hits.copy()
        hits.insert(0, "rank", range(1, len(hits) + 1))
        hits.insert(2, "src", hits["ticker"].map(sources))
        print(hits.to_string(index=False))
    print(f"({len(errors)} tickers skipped for missing data)")


def _sell_check(algorithm):
    """Run the HOLD/SELL check on positions.csv and print verdicts (SELLs first)."""
    if not os.path.exists(POSITIONS_CSV):
        print(f"\n(no {POSITIONS_CSV} found — skipping HOLD/SELL check)")
        return
    verdicts, errors = check_positions(algorithm)
    n_sell = int((verdicts["verdict"] == "SELL").sum()) if not verdicts.empty else 0
    print(f"\n=== HOLD/SELL check on {len(verdicts)} positions ({n_sell} SELL) ===")
    if verdicts.empty:
        print("  (no open positions)")
    else:
        print(verdicts.to_string(index=False))
    if len(errors):
        print(f"({len(errors)} positions skipped for missing data: {', '.join(errors['ticker'])})")


def _cli():
    """Full daily routine: a single best-to-least ranked BUY list across the S&P 500,
    Nasdaq-100 and watchlist, then the HOLD/SELL check on positions.csv — BUYs first,
    then SELLs, in that order."""
    algorithm = build_algorithm(DEFAULT_BUY, DEFAULT_CONFIG)
    print(date.today().strftime("%Y-%m-%d"), flush=True)
    _scan_all(algorithm)
    _sell_check(algorithm)


if __name__ == "__main__":
    _cli()
