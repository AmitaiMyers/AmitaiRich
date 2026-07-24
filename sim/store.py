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
        if not name.endswith(".json") or name.startswith("crypto_"):
            continue
        ticker, _, rest = name[:-5].partition("_")
        if ticker in TICKERS and rest:
            per_date.setdefault(rest, set()).add(ticker)
    complete = [d for d, tk in per_date.items() if tk >= set(TICKERS)]
    return sorted(complete)


# ── crypto recordings: files named crypto_{SYMBOL}_{recid}.json ────────────────

def crypto_cache_path(symbol, recid):
    return os.path.join(CACHE_DIR, f"crypto_{symbol}_{recid}.json")


def save_crypto_session(session, recid):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = crypto_cache_path(session["symbol"], recid)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(session, fh, separators=(",", ":"))
    return path


def load_crypto_session(symbol, recid):
    with open(crypto_cache_path(symbol, recid), "r", encoding="utf-8") as fh:
        return json.load(fh)


def crypto_recordings():
    """List recorded crypto sessions grouped by recording id, newest first.

    Returns [{recid, symbols:[...], length, start}] — one entry per recording run.
    """
    if not os.path.isdir(CACHE_DIR):
        return []
    per_rec = {}
    for name in os.listdir(CACHE_DIR):
        if not name.startswith("crypto_") or not name.endswith(".json"):
            continue
        # crypto_{SYMBOL}_{recid}.json  (recid itself may contain no underscores)
        core = name[len("crypto_"):-len(".json")]
        symbol, _, recid = core.partition("_")
        if not recid:
            continue
        entry = per_rec.setdefault(recid, {"recid": recid, "symbols": []})
        entry["symbols"].append(symbol)
    out = sorted(per_rec.values(), key=lambda e: e["recid"], reverse=True)
    for entry in out:
        entry["symbols"].sort()
    return out
