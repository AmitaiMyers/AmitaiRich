"""Module 2 — Data engine.

Downloads historical OHLCV data from yfinance at a chosen candle interval
(hourly / daily / weekly / monthly), validates it strictly, and caches it
locally so repeated backtests are fully offline / zero-cost.

Strict validation (fail fast, no silent repair):
- empty result            -> EmptyDataError
- missing OHLCV column     -> MissingColumnError
- NaN in OHLCV columns     -> DataIntegrityError  (we never call .fillna())

Interval note (Yahoo limitation): intraday data ('1h') is only available for
roughly the last 730 days. Requesting '1h' over an older range returns nothing,
which surfaces as EmptyDataError — use a recent date range for hourly candles.
"""

import os

import pandas as pd
import yfinance as yf

from errors import EmptyDataError, MissingColumnError, DataIntegrityError, ConfigurationError

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
CACHE_DIR = "data_cache"

# Candle intervals we expose, mapped to the yfinance interval code.
SUPPORTED_INTERVALS = ("1h", "1d", "1wk", "1mo")


def fetch_data(ticker, start_date, end_date, interval="1d", use_cache=True):
    """Return a validated OHLCV DataFrame indexed by timestamp.

    `interval` selects the candle size (see SUPPORTED_INTERVALS). On a cache hit
    the data is loaded from disk; otherwise it is downloaded and then cached.
    Validation runs for BOTH paths so a corrupt cache still surfaces.
    """
    _validate_interval(interval)
    cache_path = _cache_path(ticker, start_date, end_date, interval)

    if use_cache and os.path.exists(cache_path):
        df = _load_from_cache(cache_path, ticker)
    else:
        df = _download_and_prepare(ticker, start_date, end_date, interval)
        if use_cache:
            _save_to_cache(df, cache_path)

    _validate_no_nan(df, ticker)
    return df


def _validate_interval(interval):
    """Fail fast on an unsupported candle interval."""
    if interval not in SUPPORTED_INTERVALS:
        raise ConfigurationError(
            f"interval must be one of {SUPPORTED_INTERVALS}, got {interval!r}"
        )


def _download_and_prepare(ticker, start_date, end_date, interval):
    """Download from yfinance, flatten columns, validate presence, slice to OHLCV."""
    raw = yf.download(
        ticker,
        start=start_date,
        end=end_date,
        interval=interval,
        auto_adjust=True,   # split/dividend-adjusted OHLC — correct for backtests
        progress=False,
    )

    if raw is None or raw.empty:
        intraday_hint = (
            " For '1h' candles Yahoo only serves ~730 days of history, so an older "
            "date range returns nothing — try a more recent range."
            if interval == "1h"
            else ""
        )
        raise EmptyDataError(
            f"yfinance returned no data for {ticker!r} between {start_date} and {end_date} "
            f"at interval {interval!r}. Check the ticker symbol and date range.{intraday_hint}"
        )

    df = _flatten_columns(raw, ticker)
    _validate_columns(df, ticker)
    df = df[REQUIRED_COLUMNS].copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df


def _flatten_columns(df, ticker):
    """Recent yfinance returns MultiIndex columns even for a single ticker.

    Collapse to the level that holds the OHLCV field names (the level containing
    'Close'). With a single ticker the other level is constant, so each field
    appears exactly once.
    """
    if not isinstance(df.columns, pd.MultiIndex):
        return df

    for level in range(df.columns.nlevels):
        level_values = set(df.columns.get_level_values(level))
        if "Close" in level_values:
            flattened = df.copy()
            flattened.columns = df.columns.get_level_values(level)
            return flattened

    raise MissingColumnError(
        f"{ticker}: could not locate OHLCV fields in MultiIndex columns {list(df.columns)}"
    )


def _validate_columns(df, ticker):
    """Raise if any required OHLCV column is missing."""
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise MissingColumnError(
            f"{ticker}: missing required columns {missing}; got {list(df.columns)}"
        )


def _validate_no_nan(df, ticker):
    """Raise if any OHLCV value is NaN. We never silently fill missing data."""
    nan_counts = df[REQUIRED_COLUMNS].isna().sum()
    offending = nan_counts[nan_counts > 0]
    if not offending.empty:
        raise DataIntegrityError(
            f"{ticker}: NaN values found in OHLCV data -> {offending.to_dict()}. "
            f"Refusing to fill; fix the source data or date range."
        )


def _cache_path(ticker, start_date, end_date, interval):
    """Build a filesystem-safe cache path keyed by ticker + date range + interval."""
    safe_ticker = ticker.replace("/", "_").replace("\\", "_")
    return os.path.join(CACHE_DIR, f"{safe_ticker}_{start_date}_{end_date}_{interval}.csv")


def _load_from_cache(cache_path, ticker):
    """Load a previously cached frame and re-establish OHLCV columns."""
    df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    _validate_columns(df, ticker)
    return df[REQUIRED_COLUMNS].copy()


def _save_to_cache(df, cache_path):
    """Persist a validated frame to the cache directory."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(cache_path)
