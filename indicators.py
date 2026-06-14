"""Vectorized technical indicators (DRY helpers shared by every algorithm).

Each function takes a pandas Series/DataFrame slice and returns a Series aligned
to the same index. Callers pass only the history available up to the current
simulation day, so these functions never introduce lookahead bias on their own.

Warmup note: rolling windows produce NaN until enough bars exist. Algorithms are
responsible for requiring enough history (see `warmup_bars`) before trusting the
latest value.
"""

import pandas as pd


def sma(series, period):
    """Simple moving average over `period` bars."""
    return series.rolling(window=period).mean()


def bollinger_bands(close, period=20, num_std=2.0):
    """Return (middle, upper, lower) Bollinger Bands.

    Uses population standard deviation (ddof=0), the conventional choice for
    Bollinger Bands. pandas defaults to ddof=1, so we set it explicitly.
    """
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return middle, upper, lower


def bandwidth(upper, lower, middle):
    """Bollinger Bandwidth = (upper - lower) / middle.

    A normalized measure of band width; small values indicate a squeeze.
    """
    return (upper - lower) / middle


def percent_b(close, upper, lower):
    """%B = (close - lower) / (upper - lower). Normalized position within the bands."""
    return (close - lower) / (upper - lower)


def true_range(high, low, close):
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    prev_close = close.shift(1)
    range_hl = high - low
    range_hc = (high - prev_close).abs()
    range_lc = (low - prev_close).abs()
    return pd.concat([range_hl, range_hc, range_lc], axis=1).max(axis=1)


def atr(high, low, close, period=14):
    """Average True Range = simple moving average of True Range over `period` bars."""
    return true_range(high, low, close).rolling(window=period).mean()


def recent_swing_low(low, lookback):
    """Lowest low over the trailing `lookback` bars."""
    return low.rolling(window=lookback).min()


def recent_swing_high(high, lookback):
    """Highest high over the trailing `lookback` bars."""
    return high.rolling(window=lookback).max()
