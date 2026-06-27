"""score_stock.py — score one or many stocks with the production BUY strategy.

Ask about any ticker(s) and get, for EACH one, the current strategy score and a
clear BUY / no verdict WITH the reason — using the exact same strategy and config
that scan_today.py runs (the Vol-Adjusted Momentum Rider), so the answer here always
matches the daily scan. Unlike the daily scan (which only lists names that fire a
BUY), this reports the score even when the answer is "no".

A BUY needs BOTH:
  1. price above its 200-day SMA (an established uptrend), and
  2. the vol-adjusted momentum score  ROC(126) / (ATR(20)/price)  >= the threshold.

Usage:
    python score_stock.py NVDA                      # single stock
    python score_stock.py AAPL MSFT NVDA            # batch (space-separated)
    python score_stock.py AAPL,MSFT,NVDA            # batch (comma-separated)
    python score_stock.py --file mylist.txt         # batch from a file
        (one symbol per line, or a CSV with a 'symbol' column / first column)

Per-ticker data problems (bad symbol, too little history) are reported as skips,
not crashes — the same boundary policy as scan_today.py / batch.py.
"""

import argparse
import os
import sys

import pandas as pd

from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data
from errors import InsufficientDataError
from scan_today import DEFAULT_BUY, DEFAULT_CONFIG, _window


def _normalize(symbol):
    """Upper-case, strip, and convert share-class dots to Yahoo's dash form."""
    return symbol.strip().upper().replace(".", "-")


def score_stock(ticker, algorithm, as_of=None, lookback_days=600,
                interval="1d", use_cache=True):
    """Return one ticker's score + BUY verdict (with reason) as a dict.

    Raises a PER_TICKER_ERROR (e.g. EmptyDataError / InsufficientDataError) on a
    bad symbol or too little history — callers catch these at the batch boundary.
    """
    start_str, end_str = _window(as_of, lookback_days)
    df = fetch_data(ticker, start_str, end_str, interval=interval, use_cache=use_cache)
    needed = algorithm.warmup_bars() + 1
    if len(df) < needed:
        raise InsufficientDataError(
            f"{ticker}: only {len(df)} bars; need {needed} for the strategy's warmup.")

    facts = algorithm.describe(df)
    is_buy = algorithm.scan_and_buy(df)
    threshold = algorithm.config["score_threshold"]

    if is_buy:
        reason = "strong, smooth uptrend"
    elif facts["pct_vs_200ma"] <= 0:
        reason = "below 200-day MA (no uptrend)"
    elif facts["vol_adj_score"] < threshold:
        reason = f"score {facts['vol_adj_score']} < threshold {threshold}"
    else:
        reason = "entry conditions not met"

    return {
        "ticker": ticker,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "score": facts["vol_adj_score"],
        "threshold": threshold,
        "mom_%": facts["mom_%"],
        "vs_200ma_%": facts["pct_vs_200ma"],
        "BUY": "YES" if is_buy else "no",
        "reason": reason,
    }


def score_stocks(tickers, algorithm, **kwargs):
    """Score a list of tickers; return (results, errors) DataFrames.

    `results` is sorted by score (best first). Tickers that fail to load are
    collected in `errors` rather than aborting the batch.
    """
    seen, rows, errors = set(), [], []
    for raw in tickers:
        ticker = _normalize(raw)
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        try:
            rows.append(score_stock(ticker, algorithm, **kwargs))
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})

    results = pd.DataFrame(rows)
    if not results.empty:
        results = results.sort_values("score", ascending=False).reset_index(drop=True)
    return results, pd.DataFrame(errors)


def _read_symbol_file(path):
    """Read tickers from a .txt (one per line) or .csv ('symbol' col / first col)."""
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path)
        column = "symbol" if "symbol" in df.columns else df.columns[0]
        return df[column].astype(str).tolist()
    with open(path) as fh:
        return [line.strip() for line in fh if line.strip()]


def _collect_tickers(args):
    """Build the ticker list from --file and/or positional args (comma-aware)."""
    tickers = []
    if args.file:
        if not os.path.exists(args.file):
            raise FileNotFoundError(f"--file not found: {args.file}")
        tickers.extend(_read_symbol_file(args.file))
    for token in args.tickers:
        tickers.extend(part for part in token.split(",") if part.strip())
    return tickers


def _print_single(row):
    """Readable verdict for a single stock (ASCII only — Windows console is cp1252)."""
    verdict = "BUY" if row["BUY"] == "YES" else "NOT a buy"
    trend = "uptrend" if row["vs_200ma_%"] > 0 else "below 200-day MA"
    print(f"\n{row['ticker']}  |  {row['date']}  |  close {row['close']}")
    print(f"  vol-adjusted score : {row['score']:<8} (buy threshold: {row['threshold']})")
    print(f"  6-month momentum   : {row['mom_%']:+.1f}%")
    print(f"  vs 200-day MA      : {row['vs_200ma_%']:+.1f}%  ({trend})")
    print(f"  VERDICT: {verdict}   ({row['reason']})\n")


def _print_table(results, errors):
    """Table for a batch, BUYs implied by the 'BUY' column; best score first."""
    cols = ["ticker", "date", "close", "score", "threshold", "mom_%", "vs_200ma_%", "BUY", "reason"]
    if results.empty:
        print("  (no scorable tickers)")
    else:
        print(results[cols].to_string(index=False))
        n_buy = int((results["BUY"] == "YES").sum())
        print(f"\n{n_buy} BUY of {len(results)} scored.")
    if len(errors):
        print(f"({len(errors)} skipped for missing data: {', '.join(errors['ticker'])})")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Score stock(s) with the production strategy and say whether to BUY.")
    parser.add_argument("tickers", nargs="*", help="one or more symbols (space- or comma-separated)")
    parser.add_argument("--file", help="path to a .txt/.csv list of symbols")
    parser.add_argument("--no-cache", action="store_true", help="force a fresh download")
    args = parser.parse_args(argv)

    tickers = _collect_tickers(args)
    if not tickers:
        parser.error("give at least one ticker, or --file <path>")

    algorithm = build_algorithm(DEFAULT_BUY, DEFAULT_CONFIG)
    print(f"Scoring {len(tickers)} symbol(s) with {DEFAULT_BUY} "
          f"(buy threshold {DEFAULT_CONFIG['score_threshold']})...", flush=True)
    results, errors = score_stocks(tickers, algorithm, use_cache=not args.no_cache)

    if len(results) == 1 and errors.empty:
        _print_single(results.iloc[0])
    else:
        _print_table(results, errors)


if __name__ == "__main__":
    main()
