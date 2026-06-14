"""Explicit custom exceptions for the simulator.

Fail-fast principle: every invalid assumption raises a named, descriptive error
instead of being silently swallowed or worked around. Catch these only at the
outermost layer (e.g. the Streamlit UI) to show the user a clear message.
"""


class SimulatorError(Exception):
    """Base class for every error raised by this project."""


class EmptyDataError(SimulatorError):
    """yfinance returned no rows for the requested ticker / date range."""


class MissingColumnError(SimulatorError):
    """A required OHLCV column is absent from the downloaded data."""


class DataIntegrityError(SimulatorError):
    """Downloaded data contains NaN values in critical columns."""


class InsufficientDataError(SimulatorError):
    """Not enough bars to satisfy an algorithm's warmup requirement."""


class InsufficientCashError(SimulatorError):
    """A buy was attempted without enough cash to cover the order."""


class InvalidTradeTypeError(SimulatorError):
    """A trade was recorded with a type other than 'BUY' or 'SELL'."""


class ConfigurationError(SimulatorError):
    """An algorithm or simulation was configured with invalid parameters."""


class EarningsDataUnavailableError(SimulatorError):
    """The earnings-avoidance filter is enabled but earnings dates could not be fetched."""
