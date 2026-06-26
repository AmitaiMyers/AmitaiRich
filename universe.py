"""Constituent lists for the daily scan: S&P 500 and Nasdaq-100.

Fetched from Wikipedia (the conventional free source) and cached to CSV so repeat
runs are offline and fast. Two gotchas handled explicitly:
  - Wikipedia 403s the default urllib user-agent, so we fetch via requests with a
    browser User-Agent and hand the HTML to pandas.
  - Yahoo uses a dash, not a dot, for share classes (BRK.B -> BRK-B), so symbols
    are normalized on the way out (matches data_engine's expectation).

Fail fast: if the network fails AND there is no cache, raise rather than returning
a silently-empty list.
"""

import io
import os

import pandas as pd
import requests

from errors import ConfigurationError, EmptyDataError

CACHE_DIR = "universe_cache"
HEADERS = {"User-Agent": "Mozilla/5.0 (capital-market-roof-simulator)"}
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

VALID_SCOPES = ("sp500", "nasdaq100", "sp500_ndx", "watchlist")


def _normalize(symbol):
    """Upper-case, strip, and convert share-class dots to Yahoo's dash form."""
    return symbol.strip().upper().replace(".", "-")


def _cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.csv")


def _load_cache(name):
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)["symbol"].astype(str).tolist()


def _save_cache(name, symbols):
    os.makedirs(CACHE_DIR, exist_ok=True)
    pd.DataFrame({"symbol": symbols}).to_csv(_cache_path(name), index=False)


def _fetch_symbols(url, symbol_columns):
    """Download a Wikipedia page and return the first table's symbol column."""
    html = requests.get(url, headers=HEADERS, timeout=30).text
    for table in pd.read_html(io.StringIO(html)):
        for column in table.columns:
            if str(column).strip().lower() in symbol_columns:
                symbols = [_normalize(s) for s in table[column].astype(str).tolist()]
                return [s for s in symbols if s and s != "NAN"]
    raise EmptyDataError(f"Could not find a symbol column in any table at {url}")


def _get(name, url, symbol_columns, use_cache, refresh):
    if use_cache and not refresh:
        cached = _load_cache(name)
        if cached:
            return cached
    symbols = _fetch_symbols(url, symbol_columns)
    _save_cache(name, symbols)
    return symbols


def get_sp500(use_cache=True, refresh=False):
    """The ~503 S&P 500 symbols (Yahoo-normalized)."""
    return _get("sp500", SP500_URL, {"symbol"}, use_cache, refresh)


def get_nasdaq100(use_cache=True, refresh=False):
    """The ~101 Nasdaq-100 symbols (Yahoo-normalized)."""
    return _get("nasdaq100", NDX_URL, {"ticker", "symbol"}, use_cache, refresh)

# def get_magic_formula(use_cache=True, refresh=False):
#     """The ~1000 Magic Formula symbols (Yahoo-normalized)."""
#     return _get("magic_formula",  , {"ticker", "symbol"}, use_cache, refresh)


def get_watchlist():
    """A hand-curated list of symbols not in the index CSVs.

    Unlike the index scopes there is no Wikipedia source to scrape, so this is
    cache-only: edit universe_cache/watchlist.csv to change it. Fail fast if the
    file is missing rather than scanning a silently-empty universe.
    """
    symbols = _load_cache("watchlist")
    if not symbols:
        raise ConfigurationError(
            f"watchlist is empty or missing — expected symbols in {_cache_path('watchlist')}")
    return [_normalize(s) for s in symbols]


def get_universe(scope="sp500_ndx", use_cache=True, refresh=False):
    """Return the symbol list for a scope.

    scope: 'sp500' | 'nasdaq100' | 'sp500_ndx' (de-duplicated union, order
    preserved) | 'watchlist' (the hand-curated universe_cache/watchlist.csv).
    """
    if scope not in VALID_SCOPES:
        raise ConfigurationError(f"scope must be one of {VALID_SCOPES}, got {scope!r}")
    if scope == "sp500":
        return get_sp500(use_cache, refresh)
    if scope == "nasdaq100":
        return get_nasdaq100(use_cache, refresh)
    if scope == "watchlist":
        return get_watchlist()
    # if scope == "magic_formula":
    #     return get_magic_formula(use_cache, refresh)
    union = get_sp500(use_cache, refresh) + get_nasdaq100(use_cache, refresh)
    return list(dict.fromkeys(union))
