"""Annual-profitability data for the earnings filter (yfinance fundamentals).

yfinance exposes only ~4 recent fiscal years of annual income statements, so this
data supports (a) the LIVE daily scan ("is the company profitable on its latest
annual report?") and (b) an incremental backtest measure on the recent window —
NOT a full-history backtest. See research_26062026.md Part IV for the honest scope.

Point-in-time discipline: an annual report is only usable AFTER it was published.
We approximate availability as fiscal-year-end + `REPORT_LAG_DAYS` (90); as-of any
date, the filter looks at the most recent fiscal year whose report was available.

Cache: one JSON file mapping ticker -> {fiscal_end_iso: net_income_or_null}.
A ticker with no retrievable statement caches as an empty dict (fetched, unknown).
Unknown profitability is treated as PASS (we only eliminate names we positively
know were unprofitable) — the filter's job is to drop known money-losers, not to
punish missing data.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

CACHE_PATH = os.path.join("fundamentals_cache", "annual_net_income.json")
REPORT_LAG_DAYS = 90
MAX_WORKERS = 8


def _fetch_one(ticker):
    """Return {fiscal_end_iso: net_income_float_or_None} for one ticker ({} if none)."""
    try:
        stmt = yf.Ticker(ticker).income_stmt
    except Exception:
        return ticker, {}
    if stmt is None or stmt.empty or "Net Income" not in stmt.index:
        return ticker, {}
    row = stmt.loc["Net Income"]
    out = {}
    for fiscal_end, value in row.items():
        key = pd.Timestamp(fiscal_end).strftime("%Y-%m-%d")
        out[key] = None if pd.isna(value) else float(value)
    return ticker, out


def load_cache(cache_path=CACHE_PATH):
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path) as fh:
        return json.load(fh)


def fetch_net_income(tickers, cache_path=CACHE_PATH, refresh=False, pause=0.05):
    """Fetch (or load cached) annual net income for `tickers`; returns the full map.

    Only missing tickers are fetched unless `refresh`. Writes the cache after each
    batch so an interrupted run keeps its progress.
    """
    cache = {} if refresh else load_cache(cache_path)
    todo = [t for t in tickers if t not in cache]
    if not todo:
        return cache

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in todo}
        for fut in as_completed(futures):
            ticker, data = fut.result()
            cache[ticker] = data
            done += 1
            if done % 50 == 0 or done == len(todo):
                with open(cache_path, "w") as fh:
                    json.dump(cache, fh)
                print(f"  fundamentals: {done}/{len(todo)} fetched", flush=True)
            time.sleep(pause)
    with open(cache_path, "w") as fh:
        json.dump(cache, fh)
    return cache


def profitable_as_of(net_income_by_year, as_of, lag_days=REPORT_LAG_DAYS):
    """True/False if the most recent AVAILABLE annual report shows net income > 0.

    Returns None when no report was available on `as_of` (unknown). Availability =
    fiscal year end + `lag_days`.
    """
    as_of = pd.Timestamp(as_of)
    best_end, best_value = None, None
    for fiscal_end_iso, value in net_income_by_year.items():
        fiscal_end = pd.Timestamp(fiscal_end_iso)
        if fiscal_end + pd.Timedelta(days=lag_days) <= as_of:
            if best_end is None or fiscal_end > best_end:
                best_end, best_value = fiscal_end, value
    if best_end is None or best_value is None:
        return None
    return bool(best_value > 0)


def latest_profitability(net_income_by_year):
    """(fiscal_end_iso, net_income) of the most recent annual report, or (None, None)."""
    if not net_income_by_year:
        return None, None
    best = max(net_income_by_year, key=lambda k: pd.Timestamp(k))
    return best, net_income_by_year[best]
