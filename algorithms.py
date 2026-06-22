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

import exits
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

    def _trend_ok(self, close):
        c = self.config
        if not c["use_ma_filter"]:
            return True
        return bool(close.iloc[-1] > indicators.sma(close, c["ma_period"]).iloc[-1])

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        momentum = indicators.roc(close, c["mom_lookback"]).iloc[-1]
        return bool(momentum > 0) and self._trend_ok(close)

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close, high, low = history_slice["Close"], history_slice["High"], history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [float(swing_low.iloc[-1]),
                      float(entry_price - c["atr_mult"] * average_true_range.iloc[-1])]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        momentum = indicators.roc(close, c["mom_lookback"]).iloc[-1]
        if momentum < 0:
            return True
        return c["use_ma_filter"] and bool(close.iloc[-1] < indicators.sma(close, c["ma_period"]).iloc[-1])


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close, high = history_slice["Close"], history_slice["High"]
        high_52w = indicators.recent_swing_high(high, c["high_lookback"]).iloc[-1]
        near_high = bool(close.iloc[-1] >= c["proximity"] * high_52w)
        in_trend = bool(close.iloc[-1] > indicators.sma(close, c["ma_period"]).iloc[-1])
        return near_high and in_trend

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close, high, low = history_slice["Close"], history_slice["High"], history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [float(swing_low.iloc[-1]),
                      float(entry_price - c["atr_mult"] * average_true_range.iloc[-1])]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close, high = history_slice["Close"], history_slice["High"]
        high_52w = indicators.recent_swing_high(high, c["high_lookback"]).iloc[-1]
        below_high = bool(close.iloc[-1] < c["exit_drop"] * high_52w)
        lost_trend = bool(close.iloc[-1] < indicators.sma(close, c["ma_period"]).iloc[-1])
        return below_high or lost_trend


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        short_return = indicators.roc(close, c["st_lookback"]).iloc[-1]
        if not (short_return > c["threshold"]):
            return False
        if c["use_ma_filter"]:
            return bool(close.iloc[-1] > indicators.sma(close, c["ma_period"]).iloc[-1])
        return True

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close, high, low = history_slice["Close"], history_slice["High"], history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [float(swing_low.iloc[-1]),
                      float(entry_price - c["atr_mult"] * average_true_range.iloc[-1])]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        short_return = indicators.roc(close, c["st_lookback"]).iloc[-1]
        return bool(short_return < 0) or position.bars_held >= c["hold_bars"]


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

    def scan_and_buy(self, history_slice):
        c = self.config
        if len(history_slice) < self.warmup_bars():
            return False
        close = history_slice["Close"]
        in_trend = bool(close.iloc[-1] > indicators.sma(close, c["ma_period"]).iloc[-1])
        oversold = bool(indicators.rsi(close, c["rsi_period"]).iloc[-1] < c["rsi_buy"])
        return in_trend and oversold

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close, high, low = history_slice["Close"], history_slice["High"], history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [float(swing_low.iloc[-1]),
                      float(entry_price - c["atr_mult"] * average_true_range.iloc[-1])]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        close = history_slice["Close"]
        recovered = bool(indicators.rsi(close, c["rsi_period"]).iloc[-1] > c["rsi_sell"])
        lost_trend = bool(close.iloc[-1] < indicators.sma(close, c["ma_period"]).iloc[-1])
        return recovered or lost_trend


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
    # Discretionary exit (see exits.py).
    "exit_mode": "trailing",  # "trailing" | "structural" | "target"
    "trail_atr_period": 22,
    "trail_atr_mult": 3.0,
    "struct_ma_period": 50,
    "target_mult": 3.0,
}

VALID_EXIT_MODES = ("trailing", "structural", "target")


class BreakoutScanner(Algorithm):
    """Base for roof-breakout strategies. Subclasses implement the roof; the rest is shared.

    Subclass contract:
        _roof_warmup()              -> int   (bars the roof definition needs)
        _breakout_signal(history)   -> bool  (did price break its roof today?)
    """

    def warmup_bars(self):
        c = self.config
        htf_bars = c["htf_ma_weeks"] * 5 if c["use_htf"] else 0
        return max(
            self._roof_warmup(), c["vol_avg_period"], c["atr_period"], c["swing_lookback"],
            c["trail_atr_period"], c["struct_ma_period"], htf_bars,
        ) + 2

    def _roof_warmup(self):
        raise NotImplementedError

    def _breakout_signal(self, history_slice):
        raise NotImplementedError

    def _confirmation_ok(self, history_slice):
        """Volume surge (and optionally weekly-trend agreement) on the breakout bar."""
        c = self.config
        if c["vol_surge_mult"] > 0:
            volume = history_slice["Volume"]
            volume_avg = indicators.sma(volume, c["vol_avg_period"]).iloc[-1]
            if not (volume.iloc[-1] > c["vol_surge_mult"] * float(volume_avg)):
                return False
        if c["use_htf"]:
            weekly_close = history_slice["Close"].resample("W").last().dropna()
            if len(weekly_close) < c["htf_ma_weeks"] + 1:
                return False
            weekly_ma = weekly_close.rolling(c["htf_ma_weeks"]).mean().iloc[-1]
            if not (weekly_close.iloc[-1] > float(weekly_ma)):
                return False
        return True

    def scan_and_buy(self, history_slice):
        if len(history_slice) < self.warmup_bars():
            return False
        if not self._breakout_signal(history_slice):
            return False
        return self._confirmation_ok(history_slice)

    def compute_stop(self, entry_price, history_slice, stop_mode):
        c = self.config
        close, high, low = history_slice["Close"], history_slice["High"], history_slice["Low"]
        average_true_range = indicators.atr(high, low, close, c["atr_period"])
        swing_low = indicators.recent_swing_low(low, c["swing_lookback"])
        candidates = [float(swing_low.iloc[-1]),
                      float(entry_price - c["atr_mult"] * average_true_range.iloc[-1])]
        return select_stop(candidates, entry_price, stop_mode)

    def calculate_sell(self, position, history_slice):
        c = self.config
        mode = c["exit_mode"]
        if mode == "trailing":
            return exits.chandelier_hit(position, history_slice,
                                        c["trail_atr_period"], c["trail_atr_mult"])
        if mode == "structural":
            return exits.ma_breakdown_hit(history_slice, c["struct_ma_period"])
        if mode == "target":
            return exits.target_hit(position, history_slice, c["target_mult"])
        raise ConfigurationError(
            f"exit_mode must be one of {VALID_EXIT_MODES}, got {mode!r}"
        )


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

    def _breakout_signal(self, history_slice):
        c = self.config
        close, high = history_slice["Close"], history_slice["High"]
        roof = high.iloc[-(c["roof_lookback"] + 1):-1].max()  # prior highs, excluding today
        if not (close.iloc[-1] > float(roof)):
            return False
        if c["min_base_bars"] > 0 and c["base_max_range"] > 0:
            base = close.iloc[-(c["min_base_bars"] + 1):-1]
            base_range = (base.max() - base.min()) / base.min()
            if not (base_range <= c["base_max_range"]):
                return False
        return True


class SqueezeBreakout(BreakoutScanner):
    """Roof = the upper Bollinger band after a volatility squeeze (the project flagship idea).

    Setup (window ending yesterday): bandwidth below threshold for
    `min_squeeze_candles` bars, price compressed inside the bands, volume
    contracting. Breakout (today): a bullish candle closes above the upper band.
    Breakout-volume confirmation is applied by the shared `_confirmation_ok`.
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

    def _breakout_signal(self, history_slice):
        c = self.config
        close = history_slice["Close"]
        open_ = history_slice["Open"]
        volume = history_slice["Volume"]

        middle, upper, lower = indicators.bollinger_bands(close, c["bb_period"], c["bb_std"])
        band_width = indicators.bandwidth(upper, lower, middle)
        volume_avg = indicators.sma(volume, c["vol_avg_period"])

        n = c["min_squeeze_candles"]
        window = slice(-(n + 1), -1)  # the squeeze window = N bars ending yesterday

        window_bandwidth = band_width.iloc[window]
        if window_bandwidth.isna().any():
            return False
        if not bool((window_bandwidth < c["bandwidth_threshold"]).all()):
            return False

        window_close = close.iloc[window]
        if not bool(((window_close <= upper.iloc[window]) & (window_close >= lower.iloc[window])).all()):
            return False
        if not bool(volume.iloc[window].mean() < volume_avg.iloc[-2]):
            return False

        breakout = bool(close.iloc[-1] > upper.iloc[-1])
        bullish = bool(close.iloc[-1] > open_.iloc[-1])
        return breakout and bullish


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

    def _breakout_signal(self, history_slice):
        c = self.config
        close, high = history_slice["Close"], history_slice["High"]
        roof_window = high.iloc[-(c["roof_lookback"] + 1):-(c["base_bars"] + 1)]
        if len(roof_window) == 0:
            return False
        roof = float(roof_window.max())
        base = close.iloc[-(c["base_bars"] + 1):-1]
        based_below = bool((base < roof).all())
        fresh_cross = bool(close.iloc[-1] > roof and close.iloc[-2] <= roof)
        return based_below and fresh_cross


# Registry consumed by the simulation and the dashboard dropdowns.
ALGORITHMS = {
    BollingerSqueezeBreakout.name: BollingerSqueezeBreakout,
    BollingerBounce.name: BollingerBounce,
    SMACrossover.name: SMACrossover,
    TrendFollower.name: TrendFollower,
    TimeSeriesMomentum.name: TimeSeriesMomentum,
    FiftyTwoWeekHighMomentum.name: FiftyTwoWeekHighMomentum,
    ShortTermMomentum.name: ShortTermMomentum,
    PullbackReversal.name: PullbackReversal,
    HighBreakout.name: HighBreakout,
    SqueezeBreakout.name: SqueezeBreakout,
    PivotBreakout.name: PivotBreakout,
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
