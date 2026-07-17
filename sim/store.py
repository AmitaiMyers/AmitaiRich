"""JSON session cache — persists finished sessions so real data is downloaded once.

One file per (ticker, date): `sim_cache/{TICKER}_{YYYY-MM-DD}.json`. The files are
plain JSON (human-readable, trivially inspectable/deletable) and are what the
FastAPI server serves to the front-end.
"""

import json
import os

from sim.datasource import TICKERS

CACHE_DIR = "sim_cache"


def cache_path(ticker, date_str):
    return os.path.join(CACHE_DIR, f"{ticker}_{date_str}.json")


def is_cached(ticker, date_str):
    return os.path.exists(cache_path(ticker, date_str))


def save_session(session):
    """Persist a validated session dict to the cache directory."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = cache_path(session["ticker"], session["date"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(session, fh, separators=(",", ":"))
    return path


def load_session(ticker, date_str):
    """Load a cached session dict. Caller must check `is_cached` first."""
    with open(cache_path(ticker, date_str), "r", encoding="utf-8") as fh:
        return json.load(fh)


def available_dates():
    """Sorted list of session dates that have ALL five tickers cached."""
    if not os.path.isdir(CACHE_DIR):
        return []
    per_date = {}
    for name in os.listdir(CACHE_DIR):
        if not name.endswith(".json"):
            continue
        ticker, _, rest = name[:-5].partition("_")
        if ticker in TICKERS and rest:
            per_date.setdefault(rest, set()).add(ticker)
    complete = [d for d, tk in per_date.items() if tk >= set(TICKERS)]
    return sorted(complete)
