"""score_stock.py — score one or many stocks with the production BUY strategy.

Ask about any ticker(s) and get, for EACH one, the strategy's ranking score and a
clear BUY / no verdict WITH the reason — using the exact strategy and config that
scan_today.py runs, so the answer here always matches the daily scan. Unlike the
daily scan (which only lists names that fire a BUY), this reports the score even
when the answer is "no".

The reason is derived from the strategy's own config, so it stays correct when the
production strategy changes. (It used to hard-code the Vol-Adjusted Rider's
`score_threshold`, and crashed with KeyError once production switched to the
Momentum Rider.)

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

import pandas as pd

from batch import PER_TICKER_ERRORS
from data_engine import fetch_data, normalize_ticker
from errors import InsufficientDataError
from scan_today import _window, production_algorithm


def buy_reason(algorithm, facts, is_buy):
    """Plain-language reason for the verdict, from the strategy's own thresholds."""
    if is_buy:
        return "entry conditions met"
    if facts["pct_vs_200ma"] <= 0:
        return "below its long moving average (no uptrend)"
    config = algorithm.config
    if "mom_threshold" in config and facts["mom_%"] <= config["mom_threshold"] * 100:
        return f"momentum {facts['mom_%']}% <= threshold {config['mom_threshold'] * 100:.0f}%"
    if "score_threshold" in config and facts["vol_adj_score"] < config["score_threshold"]:
        return f"score {facts['vol_adj_score']} < threshold {config['score_threshold']}"
    if "max_ext" in config and facts["pct_vs_200ma"] > config["max_ext"] * 100:
        return f"overextended: {facts['pct_vs_200ma']}% above the MA (cap {config['max_ext'] * 100:.0f}%)"
    return "entry conditions not met"


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

    signals = algorithm.signals(df)
    facts = algorithm.describe(df)
    is_buy = bool(signals.entry[-1])
    return {
        "ticker": ticker,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "score": round(float(signals.score[-1]), 4),
        **facts,
        "BUY": "YES" if is_buy else "no",
        "reason": buy_reason(algorithm, facts, is_buy),
    }


def score_stocks(tickers, algorithm, **kwargs):
    """Score a list of tickers; return (results, errors) DataFrames.

    `results` is sorted by score (best first). Tickers that fail to load are
    collected in `errors` rather than aborting the batch.
    """
    seen, rows, errors = set(), [], []
    for raw in tickers:
        ticker = normalize_ticker(raw)
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
    trend = "uptrend" if row["pct_vs_200ma"] > 0 else "below 200-day MA"
    print(f"\n{row['ticker']}  |  {row['date']}  |  close {row['close']}")
    print(f"  ranking score      : {row['score']}")
    print(f"  6-month momentum   : {row['mom_%']:+.1f}%")
    print(f"  vs 200-day MA      : {row['pct_vs_200ma']:+.1f}%  ({trend})")
    print(f"  VERDICT: {verdict}   ({row['reason']})\n")


def _print_table(results, errors):
    """Table for a batch, BUYs implied by the 'BUY' column; best score first."""
    cols = [c for c in ("ticker", "date", "close", "score", "mom_%", "vol_adj_score",
                        "pct_vs_200ma", "BUY", "reason") if c in results.columns]
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

    algorithm = production_algorithm()
    print(f"Scoring {len(tickers)} symbol(s) with {algorithm.name}...", flush=True)
    results, errors = score_stocks(tickers, algorithm, use_cache=not args.no_cache)

    if len(results) == 1 and errors.empty:
        _print_single(results.iloc[0])
    else:
        _print_table(results, errors)


if __name__ == "__main__":
    main()
