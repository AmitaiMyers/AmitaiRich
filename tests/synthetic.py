"""Deterministic synthetic OHLCV data for offline tests (no network, no yfinance).

Prices follow a regime-switching geometric random walk: trending, choppy, and
low-volatility "squeeze" stretches alternate, so every strategy in the registry
(breakouts, squeezes, momentum riders, mean reversion) actually fires. Same seed ->
identical frame, so test failures are reproducible.
"""

import numpy as np
import pandas as pd

# (daily drift, daily volatility) per regime.
_REGIMES = (
    (0.0015, 0.012),   # steady uptrend
    (-0.0012, 0.018),  # downtrend
    (0.0, 0.020),      # choppy
    (0.0002, 0.004),   # quiet squeeze
    (0.0030, 0.025),   # strong, volatile rally
)


def make_ohlcv(seed, n_bars=900, start="2015-01-02", start_price=50.0):
    """Return a business-day OHLCV DataFrame (index named 'Date') for one fake stock."""
    rng = np.random.default_rng(seed)
    regime_ids = _regime_path(rng, n_bars)
    drift = np.array([_REGIMES[r][0] for r in regime_ids])
    vol = np.array([_REGIMES[r][1] for r in regime_ids])

    log_returns = drift + vol * rng.standard_normal(n_bars)
    close = start_price * np.exp(np.cumsum(log_returns))
    prev_close = np.concatenate([[start_price], close[:-1]])
    open_ = prev_close * np.exp(vol * 0.5 * rng.standard_normal(n_bars))
    spread_up = np.abs(vol * rng.standard_normal(n_bars))
    spread_down = np.abs(vol * rng.standard_normal(n_bars))
    high = np.maximum(open_, close) * np.exp(spread_up)
    low = np.minimum(open_, close) * np.exp(-spread_down)
    base_volume = 1_000_000 * (1.0 + 20.0 * vol)
    volume = np.round(base_volume * np.exp(0.5 * rng.standard_normal(n_bars)))

    index = pd.bdate_range(start=start, periods=n_bars, name="Date")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


def _regime_path(rng, n_bars):
    """Piecewise-constant regime ids with stretches of 20-120 bars."""
    ids = []
    while len(ids) < n_bars:
        regime = int(rng.integers(len(_REGIMES)))
        ids.extend([regime] * int(rng.integers(20, 121)))
    return ids[:n_bars]


def make_universe(n_tickers, seed=7, n_bars=900, start="2015-01-02"):
    """{ticker: frame} for a small fake universe with staggered listing dates."""
    frames = {}
    for k in range(n_tickers):
        offset = (k % 4) * 15  # some tickers list later, exercising calendar alignment
        listing_day = pd.Timestamp(start) + pd.offsets.BDay(offset)
        frames[f"T{k:02d}"] = make_ohlcv(seed * 1000 + k, n_bars=n_bars - offset,
                                         start=listing_day)
    return frames
