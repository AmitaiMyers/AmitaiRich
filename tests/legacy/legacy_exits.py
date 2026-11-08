"""Shared exit logic for the roof-breakout scanners (DRY).

Each helper answers one question: "given the open position and the history up to
today, should we sell at today's close?" They are pure functions of the slice and
the position, so they introduce no lookahead and can be mixed into any strategy's
`calculate_sell`. The catastrophe stop set at entry (the buy algorithm's
`compute_stop`) is enforced separately by the simulation, so these only cover the
discretionary / profit-taking exit.
"""

import indicators
from errors import ConfigurationError


def _bars_since_entry(position):
    """Number of bars from the entry bar through today, inclusive.

    `bars_held` is incremented at the END of every bar, including the entry bar, so
    on the first day `calculate_sell` runs it is 1 and the entry-to-today window is
    2 bars. Hence the +1.
    """
    return position.bars_held + 1


def chandelier_hit(position, history, atr_period, atr_mult):
    """Trailing-stop exit: sell when close falls `atr_mult` ATRs below the run-up high.

    The reference high is the highest high since entry (a chandelier stop that only
    ratchets up), so this lets winners run and exits on a defined pullback. Checked
    on the close; the intrabar catastrophe stop still guards gap-downs.
    """
    window = history.iloc[-_bars_since_entry(position):]
    highest_high = float(window["High"].max())
    average_true_range = indicators.atr(
        history["High"], history["Low"], history["Close"], atr_period
    ).iloc[-1]
    trail_level = highest_high - atr_mult * float(average_true_range)
    return bool(history["Close"].iloc[-1] < trail_level)


def ma_breakdown_hit(history, ma_period):
    """Structural exit: sell when the close falls back below its `ma_period` SMA.

    Models "the breakout failed / the trend broke" — once price loses the moving
    average the move is treated as over.
    """
    close = history["Close"]
    moving_average = indicators.sma(close, ma_period).iloc[-1]
    return bool(close.iloc[-1] < float(moving_average))


def target_hit(position, history, target_mult):
    """Profit-target exit: sell when gain reaches `target_mult` x initial risk (R).

    Initial risk is the entry-to-stop distance fixed at entry. Requires the buy
    algorithm to have set a stop (fail fast otherwise).
    """
    if position.stop_price is None:
        raise ConfigurationError(
            "target exit needs an initial stop to define risk, but the position has none."
        )
    initial_risk = position.entry_price - position.stop_price
    if initial_risk <= 0:
        raise ConfigurationError(
            f"Non-positive initial risk ({initial_risk:.4f}); stop must be below entry."
        )
    target_price = position.entry_price + target_mult * initial_risk
    return bool(history["Close"].iloc[-1] >= target_price)
