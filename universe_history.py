"""Point-in-time universe: historical S&P 500 membership + the extended (current) lists.

Two tiers (see GOAL_SPEC.md):
  * CORE — historical S&P 500 members on each date (fja05680/sp500, 1996 →). A stock is
    eligible only while it was actually in the index, which removes most survivorship bias.
  * EXTENDED — today's S&P 400 (mid caps), S&P 600 (small caps), Nasdaq-100, watchlist and
    Magic Formula lists. These are CURRENT lists, so they are survivor-biased; they are used
    for the live scan and as a clearly-labelled secondary research universe.

Residual bias: Yahoo has no prices for most delisted companies, and some old tickers were
later reused by different companies. `member_matrix` therefore only marks a historical member
as eligible on dates where its Yahoo history actually exists (a reused ticker's history starts
long after the old membership, so the old membership simply never becomes eligible).
"""

import io
import os
import time

import pandas as pd
import requests

import universe
from data_engine import normalize_ticker
from errors import EmptyDataError

DATA_DIR = os.environ.get("MARKET_DATA_DIR", "market_data")
SP500_HISTORY_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
                     "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")
WIKI_LISTS = {
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (AmitaiRich research)"}
RESEARCH_START = "2004-01-01"


def _history_path():
    return os.path.join(DATA_DIR, "sp500_history.csv")


HISTORY_MAX_AGE_DAYS = 7


def sp500_snapshots(refresh=False):
    """DataFrame indexed by date with a `tickers` column (frozenset, Yahoo-normalized).

    The history file is maintained by hand upstream and lags by weeks to months, so a row
    dated today holding the CURRENT constituents (Wikipedia, via universe.get_sp500) is appended
    when today is later than its last snapshot — live scans and paper trading then use today's
    index. Research periods (<= 2022) are unaffected.
    """
    path = _history_path()
    stale = os.path.exists(path) and time.time() - os.path.getmtime(path) > HISTORY_MAX_AGE_DAYS * 86400
    if refresh or stale or not os.path.exists(path):
        os.makedirs(DATA_DIR, exist_ok=True)
        response = requests.get(SP500_HISTORY_URL, timeout=60)
        response.raise_for_status()
        with open(path, "w") as fh:
            fh.write(response.text)
    raw = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    if raw.empty:
        raise EmptyDataError(f"{path} has no membership rows")
    tickers = raw["tickers"].map(lambda s: frozenset(normalize_ticker(t) for t in s.split(",")))
    snapshots = pd.DataFrame({"tickers": tickers.to_numpy()}, index=pd.DatetimeIndex(raw["date"], name="date"))
    today = pd.Timestamp.today().normalize()
    if today > snapshots.index[-1]:
        snapshots.loc[today] = [frozenset(current_sp500(refresh=stale or refresh))]
    return snapshots


def current_sp500(refresh=False):
    """Today's S&P 500 constituents straight from Wikipedia (cached in the data store).

    Deliberately NOT universe_cache/sp500.csv: that repo list has been hand-extended and holds
    more than the index's ~503 members."""
    path = os.path.join(DATA_DIR, "sp500_current.csv")
    if refresh or not os.path.exists(path):
        os.makedirs(DATA_DIR, exist_ok=True)
        pd.DataFrame({"symbol": _wiki_symbols(universe.SP500_URL)}).to_csv(path, index=False)
    return pd.read_csv(path)["symbol"].astype(str).tolist()


def sp500_members_since(start=RESEARCH_START):
    """Every symbol that was an S&P 500 member at any time since `start` (sorted)."""
    snapshots = sp500_snapshots()
    before = snapshots[snapshots.index <= pd.Timestamp(start)]
    from_row = before.index[-1] if len(before) else snapshots.index[0]
    union = set()
    for members in snapshots.loc[from_row:, "tickers"]:
        union |= members
    return sorted(union)


def member_matrix(calendar, tickers):
    """Boolean dates x tickers: was each ticker an S&P 500 member on each calendar date?"""
    snapshots = sp500_snapshots()
    rows = snapshots["tickers"].reindex(calendar, method="ffill")
    known = rows.notna().to_numpy()
    data = {t: [bool(k) and t in members for k, members in zip(known, rows.to_numpy())] for t in tickers}
    return pd.DataFrame(data, index=calendar)


def _wiki_symbols(url):
    html = requests.get(url, headers=HEADERS, timeout=30).text
    for table in pd.read_html(io.StringIO(html)):
        for column in table.columns:
            if str(column).strip().lower() in ("symbol", "ticker", "ticker symbol"):
                symbols = [normalize_ticker(s) for s in table[column].astype(str)]
                return [s for s in symbols if s and s != "NAN"]
    raise EmptyDataError(f"no symbol column found at {url}")


def extended_lists(refresh=False):
    """{list name: [tickers]} for the current (survivor-biased) extended universe."""
    lists = {}
    for name, url in WIKI_LISTS.items():
        path = os.path.join(DATA_DIR, f"{name}.csv")
        if refresh or not os.path.exists(path):
            os.makedirs(DATA_DIR, exist_ok=True)
            pd.DataFrame({"symbol": _wiki_symbols(url)}).to_csv(path, index=False)
        lists[name] = pd.read_csv(path)["symbol"].astype(str).tolist()
    for scope in ("nasdaq100", "watchlist", "magic_formula"):
        lists[scope] = universe.get_universe(scope)
    return lists


def research_universe():
    """Core (historical S&P 500 since 2004) + extended lists, de-duplicated."""
    tickers = sp500_members_since()
    for names in extended_lists().values():
        tickers += names
    return list(dict.fromkeys(tickers))
