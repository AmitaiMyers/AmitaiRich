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

CLI:  python scan_today.py   (scans S&P 500 then Nasdaq-100, one after another)
"""

from datetime import date

import pandas as pd

from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data
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


def _scan_scope(scope, algorithm):
    """Run the BUY scan for one universe scope and print its candidates."""
    tickers = universe.get_universe(scope)
    scan_date = date.today().strftime("%Y-%m-%d")
    print(f"\n{scan_date}", flush=True)
    print(f"\nScanning {len(tickers)} {scope} stocks with {DEFAULT_BUY}...", flush=True)
    hits, errors = scan_for_buys(tickers, algorithm)
    print(f"=== BUY candidates as of latest bar ({len(hits)}) - {scope} ===")
    if hits.empty:
        print("  (none today)")
    else:
        print(hits.to_string(index=False))
    print(f"({len(errors)} tickers skipped for missing data)")


def _cli():
    """Scan the S&P 500, the Nasdaq-100, then the custom watchlist, one after another."""
    algorithm = build_algorithm(DEFAULT_BUY, DEFAULT_CONFIG)
    for scope in ("sp500", "nasdaq100", "watchlist"):
        _scan_scope(scope, algorithm)


if __name__ == "__main__":
    _cli()
