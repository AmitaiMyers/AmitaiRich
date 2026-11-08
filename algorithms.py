"""Module 3 — Algorithm interface and strategies.

Every strategy declares its rules ONCE, vectorized over a whole price history, as a
`Signals` bundle (see `_build_signals`):

    entry        bool[N]   BUY at bar i's close?
    exit         bool[N]   path-independent discretionary SELL at bar i's close?
    score        float[N]  ranking strength (for scans / portfolio priority)
    stop_levels  fixed candidate stop prices per bar (e.g. lower band, swing low)
    stop_atr     ATR per bar for the `entry - atr_mult * ATR` stop candidate
    trail_atr / target_mult / max_hold   path-dependent exits needing the position

From that bundle the base class derives the classic per-bar interface used by the
scanners and the GUI, so callers are unchanged:

    warmup_bars()                           -> int
    scan_and_buy(history_slice)             -> bool
    compute_stop(entry, history, stop_mode) -> float | None
    calculate_sell(position, history)       -> bool

No lookahead: every indicator here is causal (rolling / shifted / EWM windows that
only look backwards), so the value at bar i computed on the full history is
identical to the value computed on `history.iloc[:i+1]`. The engine relies on this
to compute signals once per stock (O(N)) instead of once per bar (O(N^2)); the test
suite (tests/test_parity.py) enforces it by comparing both forms bar by bar and by
replaying the pre-refactor per-slice implementation trade for trade.

Strategies are registered in ALGORITHMS so the dashboard can list them.
"""

import math
from dataclasses import dataclass, replace

import numpy as np

import indicators
from errors import ConfigurationError

# Default ranking signal for strategies without a natural strength measure.
DEFAULT_SCORE_LOOKBACK = 126


@dataclass(frozen=True)
class Signals:
    """Per-bar decision arrays for one stock (all aligned to the price history)."""

    entry: np.ndarray
    exit: np.ndarray
    score: np.ndarray
    stop_levels: tuple = ()
    stop_atr: np.ndarray = None
    stop_atr_mult: float = 0.0
    trail_atr: np.ndarray = None
    trail_mult: float = 0.0
    target_mult: float = None
    max_hold: int = None

    @property
    def has_stop(self):
        return bool(self.stop_levels) or self.stop_atr is not None


def _merge_config(defaults, overrides):
    """Validate overrides against defaults (fail fast on unknown keys) and merge."""
    unknown = set(overrides) - set(defaults)
    if unknown:
        raise ConfigurationError(
            f"Unknown config keys {sorted(unknown)}; valid keys are {sorted(defaults)}"
        )
    merged = dict(defaults)
    merged.update(overrides)
    return merged


def select_stop(candidates, entry_price, stop_mode):
    """Pick a stop price from candidate levels, considering only levels below entry.

    A long position's stop must sit below the entry price. Among the valid
    (below-entry) candidates:
        "tightest" -> highest price  = smallest loss per trade (default)
        "widest"   -> lowest price   = most room to avoid whipsaw
    """
    below_entry = [level for level in candidates if level < entry_price]
    if not below_entry:
        raise ConfigurationError(
            f"No stop candidate is below the entry price {entry_price:.4f}; "
            f"candidates were {candidates}. Check indicator periods / ATR multiple."
        )
    if stop_mode == "tightest":
        return max(below_entry)
    if stop_mode == "widest":
        return min(below_entry)
    raise ConfigurationError(f"stop_mode must be 'tightest' or 'widest', got {stop_mode!r}")


def stop_price_at(signals, i, entry_price, stop_mode):
    """The initial stop for an entry filled at `entry_price`, decided on bar i (None if no stop)."""
    if not signals.has_stop:
        return None
    candidates = [float(level[i]) for level in signals.stop_levels]
    if signals.stop_atr is not None:
        candidates.append(float(entry_price - signals.stop_atr_mult * signals.stop_atr[i]))
    return select_stop(candidates, entry_price, stop_mode)


def exit_hit(signals, i, close_today, highest_high, bars_held, entry_price, stop_price):
    """Discretionary SELL at bar i's close for an open position?

    `highest_high` is the highest high from the fill bar through bar i and
    `bars_held` counts bars since the fill bar (0 on the fill bar itself).
    """
    if signals.exit[i]:
        return True
    if signals.trail_atr is not None:
        # Chandelier: close falls trail_mult ATRs below the run-up high since entry.
        if close_today < highest_high - signals.trail_mult * signals.trail_atr[i]:
            return True
    if signals.target_mult is not None and _target_hit(signals.target_mult, close_today,
                                                       entry_price, stop_price):
        return True
    if signals.max_hold is not None and bars_held >= signals.max_hold:
        return True
    return False


def _target_hit(target_mult, close_today, entry_price, stop_price):
    """Profit target at `target_mult` x initial risk (entry -> stop distance)."""
    if stop_price is None:
        raise ConfigurationError(
            "target exit needs an initial stop to define risk, but the position has none.")
    initial_risk = entry_price - stop_price
    if initial_risk <= 0:
        raise ConfigurationError(
            f"Non-positive initial risk ({initial_risk:.4f}); stop must be below entry.")
    return close_today >= entry_price + target_mult * initial_risk


def _bool(series):
    """pandas boolean Series -> numpy bool array (comparisons against NaN are False)."""
    return series.to_numpy(dtype=bool)


def _float(series):
    return series.to_numpy(dtype=float)


def _default_score(close):
    return _float(indicators.roc(close, DEFAULT_SCORE_LOOKBACK))


def _atr_swing_stop(config, history):
    """The shared catastrophe stop: {recent swing low, entry - atr_mult * ATR}."""
    close, high, low = history["Close"], history["High"], history["Low"]
    return {
        "stop_levels": (_float(indicators.recent_swing_low(low, config["swing_lookback"])),),
        "stop_atr": _float(indicators.atr(high, low, close, config["atr_period"])),
        "stop_atr_mult": float(config["atr_mult"]),
    }


def _band_swing_atr_stop(config, history, lower_band):
    """Bollinger strategies' stop: {lower band, recent swing low, entry - atr_mult * ATR}."""
    stop = _atr_swing_stop(config, history)
    stop["stop_levels"] = (_float(lower_band),) + stop["stop_levels"]
    return stop


def _ma_break(close, period):
    """Structural exit: close below its `period` SMA."""
    return close < indicators.sma(close, period)


class Algorithm:
    """Base interface. Subclasses set `name`, `DEFAULTS`, `warmup_bars`, `_build_signals`."""

    name = "base"
    DEFAULTS = {}

    def __init__(self, **overrides):
        self.config = _merge_config(self.DEFAULTS, overrides)
        self._validate_config()

    def _validate_config(self):
        """Hook for subclasses to fail fast on invalid parameter values."""

    def warmup_bars(self):
        raise NotImplementedError

    def _build_signals(self, history):
        raise NotImplementedError

    def signals(self, history):
        """All per-bar decision arrays for `history` (entries masked during warmup).

        An entry needs at least `warmup_bars()` bars of history, i.e. bar index
        i >= warmup_bars() - 1.
        """
        built = self._build_signals(history)
        entry = built.entry.copy()
        entry[: max(self.warmup_bars() - 1, 0)] = False
        return replace(built, entry=entry)

    # --- the classic per-bar interface, derived from the signals -------------

    def scan_and_buy(self, history_slice):
        return bool(self.signals(history_slice).entry[-1])

    def compute_stop(self, entry_price, history_slice, stop_mode):
        return stop_price_at(self.signals(history_slice), len(history_slice) - 1,
                             entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        since_entry = history_slice["High"].iloc[-(position.bars_held + 1):]
        return exit_hit(self.signals(history_slice), len(history_slice) - 1,
                        float(history_slice["Close"].iloc[-1]), float(since_entry.max()),
                        position.bars_held, position.entry_price, position.stop_price)

    def score_today(self, history_slice):
        """The ranking strength on the latest bar (NaN when undefined)."""
        return float(self.signals(history_slice).score[-1])


class DummyAlgorithm(Algorithm):
    """Baseline pipeline test: buy if today's close > yesterday's; sell after N bars."""

    name = "Dummy (close > prev; exit after N bars)"
    DEFAULTS = {"hold_bars": 5}

    def warmup_bars(self):
        return 2

    def _build_signals(self, history):
        close = history["Close"]
        return Signals(entry=_bool(close > close.shift(1)),
                       exit=np.zeros(len(close), dtype=bool),
                       score=_default_score(close),
                       max_hold=self.config["hold_bars"])  # the dummy carries no stop


def _squeeze_breakout(history, config, bb):
    """The flagship squeeze-then-breakout test (setup window ends yesterday).

    SETUP over the `min_squeeze_candles` bars ending YESTERDAY: bandwidth below
    threshold, closes inside the bands, volume contracting vs its average. Today a
    bullish candle closes above the upper band. (Volume surge is checked by callers.)
    """
    close, open_, volume = history["Close"], history["Open"], history["Volume"]
    middle, upper, lower = bb
    band_width = indicators.bandwidth(upper, lower, middle)
    volume_avg = indicators.sma(volume, config["vol_avg_period"])
    n = config["min_squeeze_candles"]

    squeezed = indicators.held_for_prior_bars(band_width < config["bandwidth_threshold"], n)
    inside = indicators.held_for_prior_bars((close <= upper) & (close >= lower), n)
    contracting = volume.rolling(window=n).mean().shift(1) < volume_avg.shift(1)
    breakout = (close > upper) & (close > open_)
    return squeezed & inside & contracting & breakout, volume_avg


class BollingerSqueezeBreakout(Algorithm):
    """Flagship: Bollinger squeeze + volume-bandwidth breakout.

    SETUP (squeeze, measured on the bars BEFORE today's breakout candle):
        1. Bandwidth < threshold for `min_squeeze_candles` consecutive bars.
        2. Price stayed compressed inside the bands during that window.
        3. Volume was contracting (window mean below its `vol_avg_period` average).

    ENTRY (today's candle):
        1. Close above the upper band (the breakout).
        2. Volume > `vol_breakout_mult` x average volume.
        3. Bullish candle (close > open).

    STOP: smallest-loss / widest of {lower band, recent swing low, entry - mult*ATR}
          (selection via `stop_mode`).

    EXIT (discretionary): close back below the middle band.
    """

    name = "Bollinger Squeeze + Volume Breakout"
    DEFAULTS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "bandwidth_threshold": 0.10,
        "min_squeeze_candles": 5,
        "vol_avg_period": 20,
        "vol_breakout_mult": 1.5,
        "atr_period": 14,
        "atr_mult": 2.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        longest = max(c["bb_period"], c["vol_avg_period"], c["atr_period"], c["swing_lookback"])
        # +min_squeeze_candles so the full squeeze window has valid indicator values.
        return longest + c["min_squeeze_candles"] + 1

    def _build_signals(self, history):
        c = self.config
        close, volume = history["Close"], history["Volume"]
        bb = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        setup_and_breakout, volume_avg = _squeeze_breakout(history, c, bb)
        surge = volume > c["vol_breakout_mult"] * volume_avg
        middle, _upper, lower = bb
        return Signals(entry=_bool(setup_and_breakout & surge),
                       exit=_bool(close < middle),
                       score=_default_score(close),
                       **_band_swing_atr_stop(c, history, lower))


class SMACrossover(Algorithm):
    """Optional: classic fast/slow SMA crossover (golden/death cross)."""

    name = "SMA Crossover"
    DEFAULTS = {
        "fast_period": 20,
        "slow_period": 50,
        "atr_period": 14,
        "atr_mult": 2.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["slow_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        fast = indicators.sma(close, c["fast_period"])
        slow = indicators.sma(close, c["slow_period"])
        crossed_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        crossed_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        return Signals(entry=_bool(crossed_up), exit=_bool(crossed_down),
                       score=_default_score(close), **_atr_swing_stop(c, history))


class BollingerBounce(Algorithm):
    """Optional: mean-reversion bounce off the lower band, exit at the middle band."""

    name = "Bollinger Bounce (mean reversion)"
    DEFAULTS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "atr_mult": 2.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["bb_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, low = history["Close"], history["Low"]
        middle, _upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        # Dipped to/under the lower band intrabar but closed back above it.
        bounced = (low <= lower) & (close > lower)
        return Signals(entry=_bool(bounced), exit=_bool(close >= middle),
                       score=_default_score(close),
                       **_band_swing_atr_stop(c, history, lower))


class TrendFollower(Algorithm):
    """Donchian-channel trend following (Turtle-style) with an optional trend filter.

    ENTRY: today's close breaks above the highest high of the prior `entry_lookback`
    bars, and (optional) price is above its long `trend_sma` (only trade with the
    long-term trend). A catastrophe ATR stop is set at entry.

    EXIT: today's close breaks below the lowest low of the prior `exit_lookback`
    bars. Because the exit channel rides up with price, this acts as a trailing
    exit without needing per-bar stop mutation in the simulation.
    """

    name = "Trend Follower (Donchian)"
    DEFAULTS = {
        "entry_lookback": 50,
        "exit_lookback": 20,
        "trend_sma": 200,
        "use_trend_filter": 1,   # 1 = require close > trend SMA, 0 = ignore
        "atr_period": 14,
        "atr_mult": 3.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["entry_lookback"], c["trend_sma"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        entry = close > indicators.prior_max(high, c["entry_lookback"])
        if c["use_trend_filter"]:
            entry = entry & (close > indicators.sma(close, c["trend_sma"]))
        exit_ = close < indicators.prior_min(low, c["exit_lookback"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_default_score(close),
                       **_atr_swing_stop(c, history))


class BuyAndHold(Algorithm):
    """Benchmark: buy on the first eligible bar and hold until the end of the run."""

    name = "Buy & Hold (benchmark)"
    DEFAULTS = {}

    def warmup_bars(self):
        return 1

    def _build_signals(self, history):
        n = len(history)
        # Always "buy" while flat -> buys once; never exits (liquidated at the end).
        return Signals(entry=np.ones(n, dtype=bool), exit=np.zeros(n, dtype=bool),
                       score=_default_score(history["Close"]))


class TimeSeriesMomentum(Algorithm):
    """Absolute (time-series) momentum — the per-stock production analog of rotation.

    Research (Moskowitz/Ooi/Pedersen; AQR): an asset's own trailing 3-12 month
    return predicts its next return. Hold while intermediate momentum is positive
    and price is in an uptrend; exit when momentum turns negative or the trend breaks.
    """

    name = "Time-Series Momentum (absolute)"
    DEFAULTS = {
        "mom_lookback": 126,     # ~6 months of daily bars
        "ma_period": 200,
        "use_ma_filter": 1,
        "atr_period": 14,
        "atr_mult": 3.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["mom_lookback"], c["ma_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        momentum = indicators.roc(close, c["mom_lookback"])
        entry = momentum > 0
        exit_ = momentum < 0
        if c["use_ma_filter"]:
            above = close > indicators.sma(close, c["ma_period"])
            entry = entry & above
            exit_ = exit_ | _ma_break(close, c["ma_period"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_float(momentum),
                       **_atr_swing_stop(c, history))


class FiftyTwoWeekHighMomentum(Algorithm):
    """Proximity-to-52-week-high momentum (George & Hwang).

    Stocks trading near their 52-week high tend to keep outperforming. Buy when
    price is within `proximity` of its rolling 52-week high and above its long MA;
    exit when it falls a meaningful distance below that high or loses the trend.
    """

    name = "52-Week High Momentum"
    DEFAULTS = {
        "high_lookback": 252,
        "proximity": 0.95,       # within 5% of the 52-week high
        "exit_drop": 0.85,       # exit if it falls >15% below the high
        "ma_period": 200,
        "atr_period": 14,
        "atr_mult": 3.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["high_lookback"], c["ma_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high = history["Close"], history["High"]
        high_52w = indicators.recent_swing_high(high, c["high_lookback"])
        in_trend = close > indicators.sma(close, c["ma_period"])
        entry = (close >= c["proximity"] * high_52w) & in_trend
        exit_ = (close < c["exit_drop"] * high_52w) | _ma_break(close, c["ma_period"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_default_score(close),
                       **_atr_swing_stop(c, history))


class ShortTermMomentum(Algorithm):
    """Short-term (≈1-week) momentum with a trend filter and a max holding period.

    Tests the owner's last-day/last-week idea. Buy when the trailing `st_lookback`
    return clears `threshold` and the stock is above its long MA; exit when that
    short burst fades (negative short return) or after `hold_bars`.
    """

    name = "Short-Term Momentum (1-week)"
    DEFAULTS = {
        "st_lookback": 5,
        "threshold": 0.0,
        "ma_period": 200,
        "use_ma_filter": 1,
        "hold_bars": 10,
        "atr_period": 14,
        "atr_mult": 3.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["st_lookback"], c["ma_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        short_return = indicators.roc(close, c["st_lookback"])
        entry = short_return > c["threshold"]
        if c["use_ma_filter"]:
            entry = entry & (close > indicators.sma(close, c["ma_period"]))
        return Signals(entry=_bool(entry), exit=_bool(short_return < 0),
                       score=_float(short_return), max_hold=c["hold_bars"],
                       **_atr_swing_stop(c, history))


class PullbackReversal(Algorithm):
    """Buy oversold pullbacks within an uptrend (short-term reversal, trend-aligned).

    Research: short-horizon returns mean-revert. Buy when price is above its long
    MA (uptrend intact) but RSI is oversold (a dip); sell when RSI recovers or the
    uptrend breaks.
    """

    name = "Pullback Reversal (RSI in uptrend)"
    DEFAULTS = {
        "rsi_period": 14,
        "rsi_buy": 30.0,
        "rsi_sell": 55.0,
        "ma_period": 200,
        "atr_period": 14,
        "atr_mult": 3.0,
        "swing_lookback": 10,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["rsi_period"], c["ma_period"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        rsi = indicators.rsi(close, c["rsi_period"])
        entry = (close > indicators.sma(close, c["ma_period"])) & (rsi < c["rsi_buy"])
        exit_ = (rsi > c["rsi_sell"]) | _ma_break(close, c["ma_period"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_default_score(close),
                       **_atr_swing_stop(c, history))


# ---------------------------------------------------------------------------
# Roof-breakout scanners
#
# The project thesis ("Capital Market Roof"): a stock builds a base under a price
# ceiling (the "roof"), then breaks through it on strong volume and runs. These
# three strategies share everything EXCEPT how the roof is defined, so the shared
# machinery (volume / higher-timeframe confirmation, the catastrophe stop, and the
# swappable exit) lives once in BreakoutScanner and each subclass only answers
# "did price break its roof today?". Exits are config-driven so the same roof can
# be tested with a trailing stop, a structural (MA) exit, or a profit target.
# ---------------------------------------------------------------------------

# Defaults shared by every roof scanner (merged into each subclass's DEFAULTS).
BREAKOUT_COMMON = {
    # Breakout-day confirmation.
    "vol_avg_period": 20,
    "vol_surge_mult": 1.5,    # breakout volume must exceed this x average; 0 disables
    "use_htf": 0,             # 1 = also require the weekly trend to agree
    "htf_ma_weeks": 30,       # weekly close must be above its 30-week average
    # Catastrophe stop set at entry (enforced intrabar by the simulation).
    "atr_period": 14,
    "atr_mult": 3.0,
    "swing_lookback": 10,
    # Discretionary exit.
    "exit_mode": "trailing",  # "trailing" | "structural" | "target"
    "trail_atr_period": 22,
    "trail_atr_mult": 3.0,
    "struct_ma_period": 50,
    "target_mult": 3.0,
}

VALID_EXIT_MODES = ("trailing", "structural", "target")


def weekly_close_above_ma(close, weeks):
    """Higher-timeframe confirmation per bar: weekly close above its `weeks`-week SMA.

    As of each daily bar, the current (still-forming) week's close is today's close
    and the previous weeks are their completed closes — exactly what resampling the
    history up to that bar to weekly candles gives. Needs `weeks + 1` weeks of data.
    """
    week = close.index.to_period("W-SUN")
    weekly_last = close.groupby(week).last()
    week_pos = weekly_last.index.get_indexer(week)
    completed = weekly_last.to_numpy(dtype=float)
    cumulative = np.concatenate([[0.0], np.cumsum(completed)])
    first = np.clip(week_pos - weeks + 1, 0, None)
    prior_sum = cumulative[week_pos] - cumulative[first]   # completed weeks first..pos-1
    today = close.to_numpy(dtype=float)
    weekly_ma = (prior_sum + today) / weeks
    enough_weeks = (week_pos + 1) >= weeks + 1
    return enough_weeks & (today > weekly_ma)


class BreakoutScanner(Algorithm):
    """Base for roof-breakout strategies. Subclasses implement the roof; the rest is shared.

    Subclass contract:
        _roof_warmup()              -> int
        _roof_breakout(history)     -> bool Series (did price break its roof that bar?)
    """

    def _validate_config(self):
        if self.config["exit_mode"] not in VALID_EXIT_MODES:
            raise ConfigurationError(
                f"exit_mode must be one of {VALID_EXIT_MODES}, got {self.config['exit_mode']!r}")

    def warmup_bars(self):
        c = self.config
        htf_bars = c["htf_ma_weeks"] * 5 if c["use_htf"] else 0
        return max(
            self._roof_warmup(), c["vol_avg_period"], c["atr_period"], c["swing_lookback"],
            c["trail_atr_period"], c["struct_ma_period"], htf_bars,
        ) + 2

    def _roof_warmup(self):
        raise NotImplementedError

    def _roof_breakout(self, history):
        raise NotImplementedError

    def _confirmed(self, history):
        """Volume surge (and optionally weekly-trend agreement) on the breakout bar."""
        c = self.config
        confirmed = np.ones(len(history), dtype=bool)
        if c["vol_surge_mult"] > 0:
            volume = history["Volume"]
            volume_avg = indicators.sma(volume, c["vol_avg_period"])
            confirmed &= _bool(volume > c["vol_surge_mult"] * volume_avg)
        if c["use_htf"]:
            confirmed &= weekly_close_above_ma(history["Close"], c["htf_ma_weeks"])
        return confirmed

    def _exit_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        no_exit = np.zeros(len(history), dtype=bool)
        if c["exit_mode"] == "trailing":
            trail = _float(indicators.atr(high, low, close, c["trail_atr_period"]))
            return {"exit": no_exit, "trail_atr": trail, "trail_mult": float(c["trail_atr_mult"])}
        if c["exit_mode"] == "structural":
            return {"exit": _bool(_ma_break(close, c["struct_ma_period"]))}
        return {"exit": no_exit, "target_mult": float(c["target_mult"])}

    def _build_signals(self, history):
        entry = _bool(self._roof_breakout(history)) & self._confirmed(history)
        return Signals(entry=entry, score=_default_score(history["Close"]),
                       **self._exit_signals(history), **_atr_swing_stop(self.config, history))

    def describe(self, history_slice):
        """Display facts for a fired signal: the 52-week roof and the volume surge."""
        c = self.config
        close = history_slice["Close"]
        high = history_slice["High"]
        volume = history_slice["Volume"]
        prior_high = high.iloc[-253:-1].max() if len(high) > 253 else high.iloc[:-1].max()
        volume_avg = indicators.sma(volume, c["vol_avg_period"]).iloc[-1]
        return {
            "roof_52w": round(float(prior_high), 2),
            "pct_vs_52w_high": round((float(close.iloc[-1]) / float(prior_high) - 1) * 100, 1),
            "vol_x_avg": round(float(volume.iloc[-1]) / float(volume_avg), 1),
        }


class HighBreakout(BreakoutScanner):
    """Roof = the highest high of the prior `roof_lookback` bars (a 52-week-high breakout).

    Buy when today's close prints a fresh N-bar high. Optionally require the run-up
    to it to be a tight base (range over `min_base_bars` within `base_max_range`),
    so we buy bases breaking out rather than parabolic extensions.
    """

    name = "Roof: 52-Week-High Breakout"
    DEFAULTS = {
        **BREAKOUT_COMMON,
        "roof_lookback": 252,
        "min_base_bars": 0,      # 0 disables the base-tightness filter
        "base_max_range": 0.0,   # e.g. 0.25 = base high/low within 25%
    }

    def _roof_warmup(self):
        return max(self.config["roof_lookback"], self.config["min_base_bars"]) + 1

    def _roof_breakout(self, history):
        c = self.config
        close, high = history["Close"], history["High"]
        breakout = close > indicators.prior_max(high, c["roof_lookback"])
        if c["min_base_bars"] > 0 and c["base_max_range"] > 0:
            base_high = indicators.prior_max(close, c["min_base_bars"])
            base_low = indicators.prior_min(close, c["min_base_bars"])
            breakout = breakout & ((base_high - base_low) / base_low <= c["base_max_range"])
        return breakout


class SqueezeBreakout(BreakoutScanner):
    """Roof = the upper Bollinger band after a volatility squeeze (the project flagship idea).

    Setup (window ending yesterday): bandwidth below threshold for
    `min_squeeze_candles` bars, price compressed inside the bands, volume
    contracting. Breakout (today): a bullish candle closes above the upper band.
    Breakout-volume confirmation is applied by the shared `_confirmed`.
    """

    name = "Roof: Volatility-Squeeze Breakout"
    DEFAULTS = {
        **BREAKOUT_COMMON,
        "bb_period": 20,
        "bb_std": 2.0,
        "bandwidth_threshold": 0.10,
        "min_squeeze_candles": 5,
    }

    def _roof_warmup(self):
        return self.config["bb_period"] + self.config["min_squeeze_candles"] + 1

    def _roof_breakout(self, history):
        c = self.config
        bb = indicators.bollinger_bands(history["Close"], c["bb_period"], c["bb_std"])
        setup_and_breakout, _volume_avg = _squeeze_breakout(history, c, bb)
        return setup_and_breakout


class PivotBreakout(BreakoutScanner):
    """Roof = a horizontal resistance the stock based under, then broke (the DELL picture).

    The roof is the highest high over the lookback EXCLUDING the most recent
    `base_bars` (the established ceiling). We require the recent `base_bars` to have
    closed below that ceiling (a base beneath resistance), then fire on the bar
    whose close first crosses above it.
    """

    name = "Roof: Pivot-Resistance Breakout"
    DEFAULTS = {
        **BREAKOUT_COMMON,
        "roof_lookback": 120,
        "base_bars": 20,
    }

    def _roof_warmup(self):
        return self.config["roof_lookback"] + 1

    def _roof_breakout(self, history):
        c = self.config
        close, high = history["Close"], history["High"]
        roof_bars = c["roof_lookback"] - c["base_bars"]
        if roof_bars <= 0:
            return close != close  # an empty roof window never breaks (all False)
        # Highest high over bars [i - roof_lookback, i - base_bars - 1].
        roof = high.shift(c["base_bars"] + 1).rolling(window=roof_bars).max()
        based_below = indicators.prior_max(close, c["base_bars"]) < roof
        fresh_cross = (close > roof) & (close.shift(1) <= roof)
        return based_below & fresh_cross


# ---------------------------------------------------------------------------
# Hold-winner riders
#
# Low-turnover trend strategies built for the explicit goal of riding winners
# for long stretches with the FEWEST possible buy/sell actions: each has a SINGLE
# structural exit (a slow moving-average breakdown) so ordinary pullbacks are
# tolerated, plus a WIDE ATR catastrophe stop that only fires on a real collapse.
# ---------------------------------------------------------------------------

class TrendRider(Algorithm):
    """Buy a confirmed breakout in an uptrend; exit only on a structural trend break.

    ENTRY: today's close is a fresh `breakout_lookback`-bar high AND above the long
           `trend_ma` SMA (buy strength that is already trending up).
    STOP:  widest/tightest of {recent swing low, entry - atr_mult*ATR} (wide by default).
    EXIT:  close falls back below the `exit_ma` SMA — the trend is treated as over.
    """

    name = "Trend Rider (breakout + MA exit)"
    DEFAULTS = {
        "breakout_lookback": 100,
        "trend_ma": 200,
        "exit_ma": 100,
        "atr_period": 14,
        "atr_mult": 4.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["breakout_lookback"], c["trend_ma"], c["exit_ma"],
                   c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high = history["Close"], history["High"]
        breakout = close > indicators.prior_max(high, c["breakout_lookback"])
        in_trend = close > indicators.sma(close, c["trend_ma"])
        return Signals(entry=_bool(breakout & in_trend), exit=_bool(_ma_break(close, c["exit_ma"])),
                       score=_default_score(close), **_atr_swing_stop(c, history))


def _trend_facts(close, momentum, trend_ma):
    """Shared display facts: momentum % and distance above the long MA."""
    last = float(close.iloc[-1])
    sma_long = float(indicators.sma(close, trend_ma).iloc[-1])
    return {"mom_%": round(float(momentum) * 100, 1),
            "pct_vs_200ma": round((last / sma_long - 1) * 100, 1)}


class MomentumRider(Algorithm):
    """Buy strong absolute momentum in an uptrend; hold until the long trend breaks.

    Like TimeSeriesMomentum but deliberately lower-turnover: it does NOT sell when
    momentum merely dips negative (that whipsaws) — it exits ONLY when price closes
    below the long `trend_ma`, so a winner is ridden as long as its primary uptrend
    holds.

    ENTRY: trailing `mom_lookback` return > `mom_threshold` AND close > `trend_ma` SMA
           (AND not more than `max_ext` above it; 9.99 = cap off).
    STOP:  widest/tightest of {recent swing low, entry - atr_mult*ATR}.
    EXIT:  close < `trend_ma` SMA on `exit_confirm` consecutive closes (1 = the
           classic single-close exit; 2-3 filters one-day whipsaws).
    """

    name = "Momentum Rider (ROC + MA exit)"
    DEFAULTS = {
        "mom_lookback": 126,
        "mom_threshold": 0.0,
        "trend_ma": 200,
        "max_ext": 9.99,   # skip buys more than this fraction above trend_ma; 9.99 = off
        "exit_confirm": 1,
        "atr_period": 14,
        "atr_mult": 4.0,
        "swing_lookback": 20,
    }

    def _validate_config(self):
        if self.config["exit_confirm"] < 1:
            raise ConfigurationError(
                f"exit_confirm must be >= 1, got {self.config['exit_confirm']!r}")

    def warmup_bars(self):
        c = self.config
        return max(c["mom_lookback"], c["trend_ma"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        momentum = indicators.roc(close, c["mom_lookback"])
        sma_long = indicators.sma(close, c["trend_ma"])
        # The danger-zone cap: skip names already stretched far above their trend.
        entry = (momentum > c["mom_threshold"]) & (close > sma_long) \
            & (close <= (1.0 + c["max_ext"]) * sma_long)
        exit_ = indicators.held_for_bars(close < sma_long, c["exit_confirm"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_float(momentum),
                       **_atr_swing_stop(c, history))

    def describe(self, history_slice):
        """Display facts for a fired BUY: raw 6-month momentum + distance above the 200-MA."""
        c = self.config
        close = history_slice["Close"]
        return _trend_facts(close, indicators.roc(close, c["mom_lookback"]).iloc[-1], c["trend_ma"])


def vol_adjusted_momentum(history, mom_lookback, atr_period):
    """ROC(mom_lookback) / (ATR(atr_period) / close): return per unit of volatility.

    NaN where undefined (warmup, or a non-positive ATR/price) so it never ranks or fires.
    """
    close, high, low = history["Close"], history["High"], history["Low"]
    momentum = indicators.roc(close, mom_lookback)
    average_true_range = indicators.atr(high, low, close, atr_period)
    score = momentum / (average_true_range / close)
    defined = (average_true_range > 0) & (close > 0)
    return score.where(defined)


class VolAdjustedMomentumRider(Algorithm):
    """Buy risk-adjusted momentum in an uptrend; hold until the long MA breaks.

    Ranks trend strength as ROC normalised by volatility (ATR as a % of price), so
    it favours strong AND smooth advancers rather than the most volatile names —
    directly aimed at risk-adjusted (Sharpe) return.

    ENTRY: close > `trend_ma` SMA AND  ROC(`mom_lookback`) / (ATR(`atr_period`)/close)
           >= `score_threshold`.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  close < `exit_ma` SMA (single structural exit).
    """

    name = "Vol-Adjusted Momentum Rider"
    DEFAULTS = {
        "mom_lookback": 126,
        "atr_period": 20,
        "trend_ma": 200,
        "exit_ma": 200,
        "score_threshold": 8.0,
        "atr_mult": 4.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["mom_lookback"], c["trend_ma"], c["exit_ma"],
                   c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        score = vol_adjusted_momentum(history, c["mom_lookback"], c["atr_period"])
        entry = (close > indicators.sma(close, c["trend_ma"])) & (score >= c["score_threshold"])
        return Signals(entry=_bool(entry), exit=_bool(_ma_break(close, c["exit_ma"])),
                       score=_float(score), **_atr_swing_stop(c, history))

    def describe(self, history_slice):
        """Display facts for a fired BUY: the volatility-adjusted momentum score + trend."""
        c = self.config
        close = history_slice["Close"]
        facts = _trend_facts(close, indicators.roc(close, c["mom_lookback"]).iloc[-1], c["trend_ma"])
        score = float(vol_adjusted_momentum(history_slice, c["mom_lookback"], c["atr_period"]).iloc[-1])
        facts["vol_adj_score"] = round(score, 1)
        return facts


class DualConfirmTrendHold(Algorithm):
    """52-week-high breakout in an uptrend; exit only when TWO slow signals agree.

    ENTRY: close is a fresh `entry_lookback`-bar high AND close > `trend_ma` SMA.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  close < the prior `exit_lookback`-bar low  AND  close < `exit_ma` SMA.
    """

    name = "Dual-Confirm Trend Hold"
    DEFAULTS = {
        "entry_lookback": 252,
        "trend_ma": 200,
        "exit_lookback": 100,
        "exit_ma": 200,
        "atr_period": 20,
        "atr_mult": 3.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["entry_lookback"], c["trend_ma"], c["exit_lookback"],
                   c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        entry = (close > indicators.prior_max(high, c["entry_lookback"])) \
            & (close > indicators.sma(close, c["trend_ma"]))
        exit_ = (close < indicators.prior_min(low, c["exit_lookback"])) \
            & _ma_break(close, c["exit_ma"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_default_score(close),
                       **_atr_swing_stop(c, history))


class EfficiencyTrendRider(Algorithm):
    """Buy near-52-week-high uptrends ONLY when the path is efficient (not choppy).

    ENTRY: close > `trend_ma` SMA AND close >= `proximity` x 52-week high AND
           EfficiencyRatio(`er_period`) >= `er_threshold`.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  chandelier trailing stop (`trail_atr_mult` x ATR below highest-high-since-entry).
    """

    name = "Efficiency-Ratio Trend Rider"
    DEFAULTS = {
        "high_lookback": 252,
        "proximity": 0.92,
        "trend_ma": 200,
        "er_period": 30,
        "er_threshold": 0.40,
        "atr_period": 22,
        "atr_mult": 3.0,
        "swing_lookback": 22,
        "trail_atr_period": 22,
        "trail_atr_mult": 5.0,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["high_lookback"], c["trend_ma"], c["er_period"], c["atr_period"],
                   c["swing_lookback"], c["trail_atr_period"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        high_52w = indicators.recent_swing_high(high, c["high_lookback"])
        entry = (close > indicators.sma(close, c["trend_ma"])) \
            & (close >= c["proximity"] * high_52w) \
            & (indicators.efficiency_ratio(close, c["er_period"]) >= c["er_threshold"])
        return Signals(entry=_bool(entry), exit=np.zeros(len(close), dtype=bool),
                       score=_default_score(close),
                       trail_atr=_float(indicators.atr(high, low, close, c["trail_atr_period"])),
                       trail_mult=float(c["trail_atr_mult"]),
                       **_atr_swing_stop(c, history))


class TwoSpeedDonchian(Algorithm):
    """Asymmetric Donchian: fast breakout entry, slow self-trailing channel exit.

    ENTRY: close > prior `entry_lookback`-bar high AND close > `trend_ma` SMA.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  close < the prior `exit_lookback`-bar low (exit_lookback >> entry_lookback).
    """

    name = "Two-Speed Donchian"
    DEFAULTS = {
        "entry_lookback": 40,
        "exit_lookback": 120,
        "trend_ma": 200,
        "atr_period": 20,
        "atr_mult": 3.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["entry_lookback"], c["exit_lookback"], c["trend_ma"],
                   c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        entry = (close > indicators.prior_max(high, c["entry_lookback"])) \
            & (close > indicators.sma(close, c["trend_ma"]))
        exit_ = close < indicators.prior_min(low, c["exit_lookback"])
        return Signals(entry=_bool(entry), exit=_bool(exit_), score=_default_score(close),
                       **_atr_swing_stop(c, history))


# ---------------------------------------------------------------------------
# Growth-maximizing riders
# ---------------------------------------------------------------------------

class GrowthRider(Algorithm):
    """Buy strong raw-momentum names in an uptrend; ride with a chandelier trailing stop.

    ENTRY: close > SMA(trend_ma) AND ROC(mom_lookback) >= mom_threshold.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  chandelier — close falls trail_atr_mult*ATR below the highest high since entry.
    """

    name = "Growth Rider (momentum + chandelier)"
    DEFAULTS = {
        "mom_lookback": 126,
        "mom_threshold": 0.30,
        "trend_ma": 200,
        "atr_period": 20,
        "atr_mult": 4.0,
        "swing_lookback": 20,
        "trail_atr_period": 22,
        "trail_atr_mult": 6.0,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["mom_lookback"], c["trend_ma"], c["atr_period"],
                   c["swing_lookback"], c["trail_atr_period"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, high, low = history["Close"], history["High"], history["Low"]
        momentum = indicators.roc(close, c["mom_lookback"])
        entry = (close > indicators.sma(close, c["trend_ma"])) & (momentum >= c["mom_threshold"])
        return Signals(entry=_bool(entry), exit=np.zeros(len(close), dtype=bool),
                       score=_float(momentum),
                       trail_atr=_float(indicators.atr(high, low, close, c["trail_atr_period"])),
                       trail_mult=float(c["trail_atr_mult"]),
                       **_atr_swing_stop(c, history))

    def describe(self, history_slice):
        c = self.config
        close = history_slice["Close"]
        return _trend_facts(close, indicators.roc(close, c["mom_lookback"]).iloc[-1], c["trend_ma"])


class AcceleratingMomentumRider(Algorithm):
    """Buy momentum that is ACCELERATING (recent faster than older), in an uptrend.

    ENTRY: close > SMA(trend_ma) AND ROC(fast) > ROC(slow) AND ROC(fast) > 0.
    STOP:  widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT:  close < SMA(exit_ma).
    """

    name = "Accelerating Momentum Rider"
    DEFAULTS = {
        "fast": 63,
        "slow": 252,
        "trend_ma": 200,
        "exit_ma": 150,
        "atr_period": 20,
        "atr_mult": 4.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["fast"], c["slow"], c["trend_ma"], c["exit_ma"],
                   c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close = history["Close"]
        fast = indicators.roc(close, c["fast"])
        slow = indicators.roc(close, c["slow"])
        entry = (close > indicators.sma(close, c["trend_ma"])) & (fast > slow) & (fast > 0.0)
        return Signals(entry=_bool(entry), exit=_bool(_ma_break(close, c["exit_ma"])),
                       score=_float(fast), **_atr_swing_stop(c, history))

    def describe(self, history_slice):
        c = self.config
        close = history_slice["Close"]
        return _trend_facts(close, indicators.roc(close, c["fast"]).iloc[-1], c["trend_ma"])


class SqueezeMomentumBuy(Algorithm):
    """Squeeze breakout + momentum confirmation + anti-overextension (owner's combo).

    1. SQUEEZE BREAKOUT on > `vol_breakout_mult` x average volume.
    2. UP MOMENTUM: ROC(`mom_lookback`) >= `mom_threshold` AND close > `trend_ma` SMA.
    3. NOT OVEREXTENDED: close no more than `max_ext` above the `trend_ma` SMA.

    STOP: widest/tightest of {swing low, entry - atr_mult*ATR}.
    EXIT: close < `trend_ma` SMA (the proven ride-the-trend exit).
    """

    name = "Squeeze Momentum Breakout"
    DEFAULTS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "bandwidth_threshold": 0.15,
        "min_squeeze_candles": 5,
        "vol_avg_period": 20,
        "vol_breakout_mult": 1.5,
        "mom_lookback": 126,
        "mom_threshold": 0.15,
        "trend_ma": 200,
        "max_ext": 0.60,
        "atr_period": 20,
        "atr_mult": 4.0,
        "swing_lookback": 20,
    }

    def warmup_bars(self):
        c = self.config
        return max(c["bb_period"] + c["min_squeeze_candles"], c["vol_avg_period"],
                   c["mom_lookback"], c["trend_ma"], c["atr_period"], c["swing_lookback"]) + 2

    def _build_signals(self, history):
        c = self.config
        close, volume = history["Close"], history["Volume"]
        momentum = indicators.roc(close, c["mom_lookback"])
        sma_long = indicators.sma(close, c["trend_ma"])
        bb = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        setup_and_breakout, volume_avg = _squeeze_breakout(history, c, bb)
        surge = volume > c["vol_breakout_mult"] * volume_avg
        entry = (momentum >= c["mom_threshold"]) & (close > sma_long) \
            & ~(close > (1.0 + c["max_ext"]) * sma_long) & setup_and_breakout & surge
        return Signals(entry=_bool(entry), exit=_bool(_ma_break(close, c["trend_ma"])),
                       score=_float(momentum), **_atr_swing_stop(c, history))

    def describe(self, history_slice):
        c = self.config
        close = history_slice["Close"]
        facts = _trend_facts(close, indicators.roc(close, c["mom_lookback"]).iloc[-1], c["trend_ma"])
        middle, upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        facts["squeeze_bw"] = round(float(indicators.bandwidth(upper, lower, middle).iloc[-2]), 3)
        return facts


# Registry consumed by the simulation and the dashboard dropdowns.
ALGORITHMS = {
    algorithm.name: algorithm
    for algorithm in (
        BollingerSqueezeBreakout, BollingerBounce, SMACrossover, TrendFollower,
        TimeSeriesMomentum, FiftyTwoWeekHighMomentum, ShortTermMomentum, PullbackReversal,
        HighBreakout, SqueezeBreakout, PivotBreakout, TrendRider, MomentumRider,
        VolAdjustedMomentumRider, DualConfirmTrendHold, EfficiencyTrendRider,
        TwoSpeedDonchian, GrowthRider, AcceleratingMomentumRider, SqueezeMomentumBuy,
        BuyAndHold, DummyAlgorithm,
    )
}


def build_algorithm(name, ui_config):
    """Instantiate a registered algorithm, passing only the config keys it accepts.

    The dashboard gathers a superset of parameters; we filter to each class's
    DEFAULTS so unrelated keys don't trip the fail-fast unknown-key check.
    """
    if name not in ALGORITHMS:
        raise ConfigurationError(f"Unknown algorithm {name!r}; valid: {sorted(ALGORITHMS)}")
    algorithm_class = ALGORITHMS[name]
    relevant = {key: value for key, value in ui_config.items() if key in algorithm_class.DEFAULTS}
    return algorithm_class(**relevant)
