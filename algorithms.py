"""Module 3 — Algorithm interface and strategies.

Every strategy is a small class implementing the same four methods, so the
simulation and the GUI can treat them uniformly:

    warmup_bars()                          -> int
    scan_and_buy(history_slice)            -> bool   (enter long today?)
    compute_stop(entry, history, stop_mode)-> float | None   (initial stop price)
    calculate_sell(position, history)      -> bool   (discretionary exit today?)

`history_slice` always ends at the current simulation day — algorithms never see
the future (no lookahead bias). The hard stop loss is enforced separately by the
simulation; `calculate_sell` covers the discretionary/target exit.

Strategies are registered in ALGORITHMS so the dashboard can list them.
"""

import indicators
from errors import ConfigurationError


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


class Algorithm:
    """Base interface. Subclasses set `name`, `DEFAULTS`, and implement the methods."""

    name = "base"
    DEFAULTS = {}

    def __init__(self, **overrides):
        self.config = _merge_config(self.DEFAULTS, overrides)

    def warmup_bars(self):
        raise NotImplementedError

    def scan_and_buy(self, history_slice):
        raise NotImplementedError

    def compute_stop(self, entry_price, history_slice, stop_mode):
        raise NotImplementedError

    def calculate_sell(self, position, history_slice):
        raise NotImplementedError


class DummyAlgorithm(Algorithm):
    """Baseline pipeline test: buy if today's close > yesterday's; sell after N bars."""

    name = "Dummy (close > prev; exit after N bars)"
    DEFAULTS = {"hold_bars": 5}

    def warmup_bars(self):
        return 2

    def scan_and_buy(self, history_slice):
        if len(history_slice) < 2:
            return False
        close = history_slice["Close"]
        return bool(close.iloc[-1] > close.iloc[-2])

    def compute_stop(self, entry_price, history_slice, stop_mode):
        return None  # the dummy strategy carries no stop loss

    def calculate_sell(self, position, history_slice):
        return position.bars_held >= self.config["hold_bars"]


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False

        close = history_slice["Close"]
        high = history_slice["High"]
        low = history_slice["Low"]
        open_ = history_slice["Open"]
        volume = history_slice["Volume"]

        middle, upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        band_width = indicators.bandwidth(upper, lower, middle)
        volume_avg = indicators.sma(volume, c["vol_avg_period"])

        # --- SETUP: evaluate the squeeze window = N bars ending YESTERDAY ---
        # Today's breakout candle closes above the band, so it is deliberately
        # excluded from the "compressed inside the bands" test.
        n = c["min_squeeze_candles"]
        window = slice(-(n + 1), -1)

        window_bandwidth = band_width.iloc[window]
        if window_bandwidth.isna().any():
            return False
        is_squeezed = bool((window_bandwidth < c["bandwidth_threshold"]).all())

        window_close = close.iloc[window]
        window_upper = upper.iloc[window]
        window_lower = lower.iloc[window]
        stayed_inside = bool(
            ((window_close <= window_upper) & (window_close >= window_lower)).all()
        )

        window_volume = volume.iloc[window]
        volume_contracting = bool(window_volume.mean() < volume_avg.iloc[-2])

        if not (is_squeezed and stayed_inside and volume_contracting):
            return False

        # --- ENTRY: today's breakout candle ---
        breakout = bool(close.iloc[-1] > upper.iloc[-1])
        volume_surge = bool(volume.iloc[-1] > c["vol_breakout_mult"] * volume_avg.iloc[-1])
        bullish = bool(close.iloc[-1] > open_.iloc[-1])
        return breakout and volume_surge and bullish

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close = history_slice["Close"]
        high = history_slice["High"]
        low = history_slice["Low"]

        middle, upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])

        candidates = [
            float(lower.iloc[-1]),
            float(swing_low.iloc[-1]),
            float(entry_price - c["atr_mult"] * average_true_range.iloc[-1]),
        ]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        middle, _upper, _lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        return bool(close.iloc[-1] < middle.iloc[-1])


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        fast = indicators.sma(close, c["fast_period"])
        slow = indicators.sma(close, c["slow_period"])
        crossed_up = fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]
        return bool(crossed_up)

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close = history_slice["Close"]
        high = history_slice["High"]
        low = history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [
            float(swing_low.iloc[-1]),
            float(entry_price - c["atr_mult"] * average_true_range.iloc[-1]),
        ]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        fast = indicators.sma(close, c["fast_period"])
        slow = indicators.sma(close, c["slow_period"])
        crossed_down = fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]
        return bool(crossed_down)


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        low = history_slice["Low"]
        _middle, _upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        # Dipped to/under the lower band intrabar but closed back above it.
        dipped = bool(low.iloc[-1] <= lower.iloc[-1])
        reclaimed = bool(close.iloc[-1] > lower.iloc[-1])
        return dipped and reclaimed

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close = history_slice["Close"]
        high = history_slice["High"]
        low = history_slice["Low"]
        _middle, _upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [
            float(lower.iloc[-1]),
            float(swing_low.iloc[-1]),
            float(entry_price - c["atr_mult"] * average_true_range.iloc[-1]),
        ]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        middle, _upper, _lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        return bool(close.iloc[-1] >= middle.iloc[-1])


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        high = history_slice["High"]

        prior_high = high.iloc[-(c["entry_lookback"] + 1):-1].max()
        breakout = bool(close.iloc[-1] > prior_high)
        if not breakout:
            return False
        if c["use_trend_filter"]:
            trend_sma = indicators.sma(close, c["trend_sma"]).iloc[-1]
            if not (close.iloc[-1] > trend_sma):
                return False
        return True

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close = history_slice["Close"]
        high = history_slice["High"]
        low = history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [
            float(swing_low.iloc[-1]),
            float(entry_price - c["atr_mult"] * average_true_range.iloc[-1]),
        ]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        low = history_slice["Low"]
        close = history_slice["Close"]
        prior_low = low.iloc[-(c["exit_lookback"] + 1):-1].min()
        return bool(close.iloc[-1] < prior_low)


class BuyAndHold(Algorithm):
    """Benchmark: buy on the first eligible bar and hold until the end of the run."""

    name = "Buy & Hold (benchmark)"
    DEFAULTS = {}

    def warmup_bars(self):
        return 1

    def scan_and_buy(self, history_slice):
        return True  # only called while flat -> buys once, on the first bar

    def compute_stop(self, entry_price, history_slice, stop_mode):
        return None

    def calculate_sell(self, position, history_slice):
        return False  # never exits; the simulation liquidates at the final bar


# Registry consumed by the simulation and the dashboard dropdowns.
ALGORITHMS = {
    BollingerSqueezeBreakout.name: BollingerSqueezeBreakout,
    BollingerBounce.name: BollingerBounce,
    SMACrossover.name: SMACrossover,
    TrendFollower.name: TrendFollower,
    BuyAndHold.name: BuyAndHold,
    DummyAlgorithm.name: DummyAlgorithm,
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
