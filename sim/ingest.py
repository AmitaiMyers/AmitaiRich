"""Ingestion CLI — pre-fetch and cache real sessions for the five tickers.

Usage (from the repo root, with the env that has yfinance):
    python -m sim.ingest                 # last 5 trading days, all 5 tickers
    python -m sim.ingest --days 10       # last 10 trading days
    python -m sim.ingest --dates 2026-07-15 2026-07-16
    python -m sim.ingest --source synthetic   # offline demo data, no network

Yahoo serves 1-minute bars only for ~the last 30 days, so --days is capped there.
Already-cached (ticker, date) pairs are skipped unless --force is given.
"""

import argparse
import sys

import pandas as pd
import yfinance as yf

from errors import SimulatorError
from sim.datasource import TICKERS, create_data_source
from sim import store


def recent_trading_days(count):
    """Return the last `count` real NYSE trading dates (YYYY-MM-DD), oldest first.

    Derived from SPY's own daily bars, so holidays/weekends are handled by the
    exchange calendar itself rather than a hand-maintained list.
    """
    daily = yf.download(
        "SPY", period="2mo", interval="1d", auto_adjust=False, progress=False
    )
    if daily is None or daily.empty:
        raise SimulatorError("Could not fetch a trading calendar from Yahoo (SPY daily).")
    dates = [pd.Timestamp(d).date().isoformat() for d in daily.index]
    return dates[-count:]


def ingest(dates, source_kind="yahoo", force=False):
    source = create_data_source(source_kind)
    total = len(dates) * len(TICKERS)
    done = 0
    failures = []
    for date_str in dates:
        for ticker in TICKERS:
            done += 1
            tag = f"[{done}/{total}] {ticker} {date_str}"
            if not force and store.is_cached(ticker, date_str):
                print(f"{tag}  cached, skip")
                continue
            try:
                session = source.load_session(ticker, date_str)
                path = store.save_session(session)
                closes = session["prices"]
                print(f"{tag}  saved -> {path}  (prevClose {session['prevClose']}, "
                      f"open {closes[0]}, close {closes[-1]})")
            except SimulatorError as exc:
                # Per-(ticker,date) failures are recorded and reported at the end so
                # one bad symbol/holiday never aborts the whole ingest.
                print(f"{tag}  ERROR: {exc}")
                failures.append((ticker, date_str, str(exc)))
    print(f"\nDone. {total - len(failures)}/{total} sessions cached.")
    if failures:
        print(f"{len(failures)} failed:")
        for ticker, date_str, msg in failures:
            print(f"  - {ticker} {date_str}: {msg}")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pre-fetch simulator sessions.")
    parser.add_argument("--days", type=int, default=5,
                        help="Number of most-recent trading days to fetch (default 5).")
    parser.add_argument("--dates", nargs="+", metavar="YYYY-MM-DD",
                        help="Explicit session dates (overrides --days).")
    parser.add_argument("--source", choices=["yahoo", "synthetic"], default="yahoo")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch even if a session is already cached.")
    args = parser.parse_args(argv)

    if args.source == "synthetic" and not args.dates:
        # synthetic has no real calendar; fabricate sequential weekday-ish labels
        dates = args.dates or recent_trading_days(args.days)
    else:
        dates = args.dates if args.dates else recent_trading_days(args.days)

    print(f"Ingesting {len(dates)} session(s) x {len(TICKERS)} tickers "
          f"from '{args.source}': {', '.join(dates)}\n")
    failures = ingest(dates, source_kind=args.source, force=args.force)
    return 1 if failures and len(failures) == len(dates) * len(TICKERS) else 0


if __name__ == "__main__":
    sys.exit(main())
