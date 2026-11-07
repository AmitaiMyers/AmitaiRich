"""Daily feature engineering, organized into selectable INDICATOR GROUPS.

The five groups match the trainable indicators:
    prices     -> candle prices (normalized OHLC returns)
    volume     -> "vol undr" (volume relative to its average)
    bollinger  -> Bollinger Bands (%B + bandwidth)
    adx        -> ADX (+DI / -DI)
    obv        -> On-Balance Volume (normalized)

The dataset is built once with ALL groups; a training run then selects any subset
via `group_columns`, so you never rebuild to change the indicator mix. All features
are stationary (ratios / normalized) so the network generalizes across tickers.
Warmup rows (any NaN) are dropped — never filled (fail-fast / no `.fillna`).
"""

import numpy as np
import pandas as pd

from errors import ConfigurationError
from indicators import (
    sma, bollinger_bands, bandwidth, percent_b, on_balance_volume, adx,
)

# Group -> ordered feature columns. FEATURE_NAMES is the flattened column order.
FEATURE_GROUPS = {
    "prices": ["ret_close", "ret_open", "ret_high", "ret_low"],
    "volume": ["vol_ratio"],
    "bollinger": ["pct_b", "bandwidth"],
    "adx": ["adx", "plus_di", "minus_di"],
    "obv": ["obv_z"],
}
ALL_GROUPS = list(FEATURE_GROUPS)
FEATURE_NAMES = [name for group in FEATURE_GROUPS.values() for name in group]


def group_columns(feature_names, groups):
    """Return (column_indices, selected_names) for the requested indicator groups."""
    selected = []
    for g in groups:
        if g not in FEATURE_GROUPS:
            raise ConfigurationError(f"Unknown indicator group {g!r}; choose from {ALL_GROUPS}")
        selected.extend(FEATURE_GROUPS[g])
    idx = [feature_names.index(n) for n in selected]
    return idx, selected


def build_features(df):
    """Return (features_df[FEATURE_NAMES], close_series) with warmup rows dropped.

    `df` must have Open/High/Low/Close/Volume columns (data_engine output).
    """
    close, open_, high, low, volume = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
    prev_close = close.shift(1)

    middle, upper, lower = bollinger_bands(close, period=14, num_std=2.0)   # Bollinger(14,2)
    adx14, plus_di, minus_di = adx(high, low, close, period=14)             # ADX(14)
    obv = on_balance_volume(close, volume)                                  # OBV
    obv_mean = obv.rolling(window=50).mean()
    obv_std = obv.rolling(window=50).std(ddof=0)

    feats = pd.DataFrame(index=df.index)
    # prices: the candle itself, as returns vs the prior close (stationary)
    feats["ret_close"] = close / prev_close - 1.0
    feats["ret_open"] = open_ / prev_close - 1.0
    feats["ret_high"] = high / prev_close - 1.0
    feats["ret_low"] = low / prev_close - 1.0
    # volume underlay
    feats["vol_ratio"] = volume / sma(volume, 20) - 1.0
    # Bollinger Bands
    feats["pct_b"] = percent_b(close, upper, lower)
    feats["bandwidth"] = bandwidth(upper, lower, middle)
    # ADX
    feats["adx"] = adx14 / 100.0
    feats["plus_di"] = plus_di / 100.0
    feats["minus_di"] = minus_di / 100.0
    # On-Balance Volume (z-scored so it's stationary)
    feats["obv_z"] = (obv - obv_mean) / obv_std

    feats = feats[FEATURE_NAMES].replace([np.inf, -np.inf], np.nan)
    valid = feats.notna().all(axis=1)
    return feats[valid], close[valid]
