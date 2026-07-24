"""Vectorized technical indicators (DRY helpers shared by every algorithm).

Each function takes a pandas Series/DataFrame slice and returns a Series aligned
to the same index. Callers pass only the history available up to the current
simulation day, so these functions never introduce lookahead bias on their own.

Warmup note: rolling windows produce NaN until enough bars exist. Algorithms are
responsible for requiring enough history (see `warmup_bars`) before trusting the
latest value.
"""

import numpy as np
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


def roc(series, period):
    """Rate of change over `period` bars = trailing return (e.g. 0.10 = +10%)."""
    return series.pct_change(periods=period)


def efficiency_ratio(close, period):
    """Kaufman Efficiency Ratio = |net change| / sum of |bar-to-bar changes|.

    A trend-quality measure in [0, 1]: ~1.0 is a clean straight move, near 0 is
    choppy/noisy. NaN until `period`+1 bars exist, and undefined (NaN via 0/0) on a
    perfectly flat stretch — callers treat NaN as "no signal" rather than filling it.
    """
    net = (close - close.shift(period)).abs()
    gross = close.diff().abs().rolling(window=period).sum()
    return net / gross


def rsi(close, period=14):
    """Relative Strength Index (0-100) using simple rolling averages of gains/losses."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def on_balance_volume(close, volume):
    """On-Balance Volume: running total of volume signed by close-to-close direction.

    The first bar has no prior close, so its direction (and contribution) is 0 —
    a definitional edge, not gap-filling, so no `.fillna` is used.
    """
    delta = close.diff()
    direction = pd.Series(np.where(delta > 0, 1.0, np.where(delta < 0, -1.0, 0.0)), index=close.index)
    return (direction * volume).cumsum()


def adx(high, low, close, period=14):
    """Wilder's Average Directional Index. Returns (adx, plus_di, minus_di) Series.

    Uses Wilder smoothing approximated by an EWM with alpha = 1/period (the standard
    equivalence). Warmup values are NaN until enough bars exist. On a tick series
    (no separate highs/lows) pass close for all three: directional movement then
    derives from close-to-close moves.
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_ = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    return adx_, plus_di, minus_di
