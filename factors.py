"""Cross-sectional factor library: every candidate signal, causal, on a dates x stocks panel.

Each factor is a `Factor(name, group, meaning, formula, compute)`. `compute(panel)` returns a
dates x tickers DataFrame where HIGHER = more attractive, using only data up to each date's
close (rolling / shifted windows only — tests/test_factors.py checks causality by truncation).
Fundamental factors live in fundamental_factors.py and register into the same FACTORS dict.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

import market_data


@dataclass(frozen=True)
class Factor:
    name: str
    group: str          # momentum | trend | volume | volatility | earnings | growth
    meaning: str        # plain language
    formula: str        # explicit formula
    compute: object     # panel -> DataFrame


class Panel:
    """Aligned float32 OHLCV panels (dates x tickers) + the SPY close, built once and shared."""

    def __init__(self, frames, start=None):
        if "SPY" not in frames:
            raise ValueError("The panel needs SPY (market benchmark) among the frames.")
        stocks = {t: f for t, f in frames.items() if not t.startswith("^")}
        self.open, self.high, self.low, self.close, self.volume = (
            market_data.panel(stocks, field).astype("float32") for field in ("Open", "High", "Low", "Close", "Volume"))
        if start is not None:
            keep = self.close.index >= pd.Timestamp(start)
            for name in ("open", "high", "low", "close", "volume"):
                setattr(self, name, getattr(self, name).loc[keep])
        self.spy = self.close["SPY"]
        self._cache = {}

    @property
    def dates(self):
        return self.close.index

    @property
    def tickers(self):
        return self.close.columns

    def cached(self, key, build):
        """Memoize shared intermediates (e.g. ATR) across factors."""
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]


# --- shared building blocks ----------------------------------------------------

def sma(frame, n):
    return frame.rolling(n, min_periods=n).mean()


def roc(frame, n):
    return frame / frame.shift(n) - 1.0


def true_range(p):
    prev = p.close.shift(1)
    return np.fmax(p.high - p.low, np.fmax((p.high - prev).abs(), (p.low - prev).abs()))


def atr(p, n=20):
    return p.cached(("atr", n), lambda: sma(true_range(p), n))


def adx_parts(p, n=14):
    def build():
        up, down = p.high.diff(), -p.low.diff()
        plus_dm = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        smoothed_tr = true_range(p).ewm(alpha=1 / n, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / smoothed_tr
        minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / smoothed_tr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        return dx.ewm(alpha=1 / n, adjust=False).mean(), plus_di, minus_di
    return p.cached(("adx", n), build)


def obv(p):
    def build():
        direction = np.sign(p.close.diff())
        return (direction * p.volume).cumsum()
    return p.cached("obv", build)


# --- the factors ------------------------------------------------------------------

def _mom_12_1(p):
    return p.close.shift(21) / p.close.shift(252) - 1.0


def _vol_adj_mom(p):
    return roc(p.close, 126) / (atr(p, 20) / p.close)


def relative_strength(p):
    """6-month return minus SPY's. Not a ranking factor (subtracting the same SPY return from
    every stock cannot change their order — it ranks exactly like mom_6m); used as an absolute
    'beating the market' filter instead."""
    return roc(p.close, 126).sub(roc(p.spy, 126), axis=0)


def _adx_trend(p):
    adx, plus_di, minus_di = adx_parts(p)
    return adx.where(plus_di > minus_di, -adx)


def _obv_trend(p):
    flow = obv(p) - obv(p).shift(50)
    return flow / (sma(p.volume, 50) * 50)


def _bb_pct_b(p):
    middle = sma(p.close, 20)
    std = p.close.rolling(20, min_periods=20).std(ddof=0)
    return (p.close - (middle - 2 * std)) / (4 * std)


def _bb_squeeze(p):
    middle = sma(p.close, 20)
    std = p.close.rolling(20, min_periods=20).std(ddof=0)
    return -(4 * std / middle)


TECHNICAL = [
    Factor("mom_12_1", "momentum", "12-month return excluding the last month (classic momentum).",
           "close[t-21] / close[t-252] - 1", _mom_12_1),
    Factor("mom_6m", "momentum", "6-month return (what production uses).",
           "close / close[t-126] - 1", lambda p: roc(p.close, 126)),
    Factor("vol_adj_mom", "momentum", "6-month return per unit of volatility: strong AND smooth.",
           "ROC(126) / (ATR(20) / close)", _vol_adj_mom),
    Factor("high_52w", "momentum", "Closeness to the 52-week high (1.0 = at the high).",
           "close / max(high, 252 bars)", lambda p: p.close / p.high.rolling(252, min_periods=252).max()),
    Factor("short_reversal", "momentum", "Last week's loss (short-term dips tend to bounce).",
           "-(close / close[t-5] - 1)", lambda p: -roc(p.close, 5)),
    Factor("trend_200", "trend", "Distance above the 200-day average.",
           "close / SMA(200) - 1", lambda p: p.close / sma(p.close, 200) - 1.0),
    Factor("trend_50_200", "trend", "50-day average vs 200-day average (golden-cross strength).",
           "SMA(50) / SMA(200) - 1", lambda p: sma(p.close, 50) / sma(p.close, 200) - 1.0),
    Factor("adx_trend", "trend", "Trend strength (ADX 0-100), negative when the trend points down.",
           "ADX(14) if +DI > -DI else -ADX(14)", _adx_trend),
    Factor("volume_surge", "volume", "Recent volume vs its average ('vol undr' rising): buying interest.",
           "SMA(volume, 5) / SMA(volume, 50)", lambda p: sma(p.volume, 5) / sma(p.volume, 50)),
    Factor("volume_quiet", "volume", "Quiet volume (a calm base before a move): the opposite of a surge.",
           "-(SMA(volume, 10) / SMA(volume, 50))", lambda p: -(sma(p.volume, 10) / sma(p.volume, 50))),
    Factor("obv_trend", "volume", "On-Balance Volume change over 50 days, scaled by average volume: "
           "is volume flowing in on up days?", "(OBV - OBV[t-50]) / (50 * SMA(volume, 50))", _obv_trend),
    Factor("bb_pct_b", "volatility", "Position inside the Bollinger Bands (1 = at the upper band).",
           "(close - lower) / (upper - lower), bands = SMA(20) +/- 2 std", _bb_pct_b),
    Factor("bb_squeeze", "volatility", "Narrow Bollinger Bands (a volatility squeeze).",
           "-(upper - lower) / SMA(20)", _bb_squeeze),
    Factor("size", "size", "Company size proxy: average daily dollar volume (bigger = higher). What tilts "
           "a portfolio toward the giants that drive SPY.", "log(SMA(close * volume, 60))",
           lambda p: np.log(sma(p.close * p.volume, 60).where(lambda dv: dv > 0))),
    Factor("low_vol", "volatility", "Calmer stocks (lower 3-month daily volatility).",
           "-std(daily returns, 63)", lambda p: -p.close.pct_change(fill_method=None).rolling(63, min_periods=63).std()),
]

FACTORS = {f.name: f for f in TECHNICAL}


def market_uptrend(p):
    """Per-date: SPY above its 200-day average (the 'no buying against the market' filter)."""
    return p.spy > sma(p.spy.to_frame(), 200).iloc[:, 0]
