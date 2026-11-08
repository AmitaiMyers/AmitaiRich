"""The single backtest engine shared by every caller (one account, many stocks).

`simulation.run_simulation` (one stock, persisted to SQLite), `portfolio.run_portfolio`
(a shared-capital account over a universe) and the research harness all run THIS
loop, so there is exactly one implementation of fills, stops, sizing and costs.

How it stays fast and lookahead-free
------------------------------------
Each stock's `Signals` (entry/exit/stop/score arrays, see algorithms.py) are computed
ONCE from its full history. Every indicator is causal, so the value at bar i equals
what a per-bar loop would compute on `history[:i+1]` — tests/test_parity.py proves
this bar by bar and trade by trade against the original per-slice engine. The loop
below then only ever reads index <= today.

Day order (matches the owner's spec — BUYs are decided before SELLs):
  1. next_open fills: queued SELLs, then queued BUYs, execute at today's open.
  2. Intrabar catastrophe stop: low <= stop exits at min(stop, open) (gap-downs fill
     at the worse open). Positions opened at today's close are not yet exposed.
  3. Market-regime exit (optional): regime off -> exit held names at the close.
  4. BUY decisions at the close: today's entry signals for stocks not held, ranked
     by score, taken while a slot is free and cash allows (close fill), or queued
     for tomorrow's open (next_open fill).
  5. SELL decisions at the close for positions not opened at this close.
  6. A stock's final bar liquidates its open position at the close ("final").
  7. Mark to market on the close.

Entries are STATE-based exactly like the production scan: a momentum stock that
qualifies today but finds no free slot is still a candidate tomorrow while its
condition holds (the old per-trade overlay could only enter on the first day).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from algorithms import exit_hit, stop_price_at
from errors import ConfigurationError, InsufficientCashError

VALID_SIZING = ("risk_based", "all_in", "fixed_fraction")
VALID_FILL = ("close", "next_open")
VALID_STOP_MODES = ("tightest", "widest")


@dataclass
class EngineConfig:
    """Account rules. Defaults reproduce the single-stock simulation."""

    starting_capital: float = 100_000.0
    max_positions: int = 1
    sizing_mode: str = "risk_based"
    risk_pct: float = 0.01           # fraction of live equity risked per trade (risk_based)
    fixed_fraction: float = 0.95     # fraction of buying power per trade (fixed_fraction)
    leverage: float = 1.0            # buying power = cash + equity * (leverage - 1)
    cost_bps: float = 0.0            # per-side transaction cost in basis points
    fill_mode: str = "close"
    stop_mode: str = "tightest"
    # True: an entry whose stop cannot be placed below the fill is skipped (portfolio
    # research). False: it raises ConfigurationError (a single-stock run surfaces it).
    skip_unprotectable: bool = False
    regime_filter: bool = False      # needs a market regime series (no entries / exit when off)

    def validate(self):
        if self.sizing_mode not in VALID_SIZING:
            raise ConfigurationError(f"sizing_mode must be one of {VALID_SIZING}, got {self.sizing_mode!r}")
        if self.fill_mode not in VALID_FILL:
            raise ConfigurationError(f"fill_mode must be one of {VALID_FILL}, got {self.fill_mode!r}")
        if self.stop_mode not in VALID_STOP_MODES:
            raise ConfigurationError(f"stop_mode must be one of {VALID_STOP_MODES}, got {self.stop_mode!r}")
        if self.max_positions < 1:
            raise ConfigurationError(f"max_positions must be >= 1, got {self.max_positions}")
        if self.starting_capital <= 0:
            raise ConfigurationError(f"starting_capital must be > 0, got {self.starting_capital}")
        if self.leverage < 1.0:
            raise ConfigurationError(f"leverage must be >= 1, got {self.leverage}")


@dataclass
class Trade:
    """One completed round trip."""

    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    stop_price: float           # None when the buy algorithm carries no stop
    shares: float
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str            # "stop" | "signal" | "regime" | "final"
    bars_held: int              # stock bars from the fill bar to the exit bar
    costs: float                # entry + exit transaction costs paid

    @property
    def ret(self):
        """Gross price return of the round trip."""
        return self.exit_price / self.entry_price - 1.0

    @property
    def pnl(self):
        """Net profit in currency after costs."""
        return self.shares * (self.exit_price - self.entry_price) - self.costs


@dataclass
class EngineResult:
    equity: pd.Series           # cash + holdings, per calendar day
    cash: pd.Series
    holdings: pd.Series
    trades: list
    n_entry_signals: int        # distinct entry episodes offered (rising edges)
    meta: dict = field(default_factory=dict)


@dataclass
class _Position:
    ticker_index: int
    fill_day: int
    entry_price: float
    stop_price: float
    shares: float
    entry_cost: float
    highest_high: float
    bars_held: int = 0
    opened_at_close_today: bool = False


class _Book:
    """Every stock's prices and signals aligned onto one calendar ([ticker, day] arrays)."""

    def __init__(self, frames, buy_algo, sell_algo):
        if not frames:
            raise ConfigurationError("The engine needs at least one price frame.")
        self.tickers = list(frames)
        self.calendar = pd.DatetimeIndex(sorted(set().union(*(df.index for df in frames.values()))))
        shape = (len(self.tickers), len(self.calendar))
        self.open, self.high, self.low, self.close = (np.full(shape, np.nan) for _ in range(4))
        self.entry = np.zeros(shape, dtype=bool)
        self.score = np.full(shape, -np.inf)
        self.last_day = np.full(len(self.tickers), -1)
        self.buy_signals, self.sell_signals, self.columns = [], [], []

        warmup = max(buy_algo.warmup_bars(), sell_algo.warmup_bars())
        for k, ticker in enumerate(self.tickers):
            df = frames[ticker]
            cols = self.calendar.get_indexer(df.index)
            self.columns.append(cols)
            for name in ("Open", "High", "Low", "Close"):
                getattr(self, name.lower())[k, cols] = df[name].to_numpy(dtype=float)
            self.last_day[k] = cols[-1]
            buy = buy_algo.signals(df)
            self.buy_signals.append(buy)
            self.sell_signals.append(buy if sell_algo is buy_algo else sell_algo.signals(df))
            tradable = buy.entry.copy()
            # Bars before `warmup` never trade; a too-short history never trades at all.
            tradable[:warmup] = False
            if len(df) <= warmup + 1:
                tradable[:] = False
            self.entry[k, cols] = tradable
            self.score[k, cols] = np.where(np.isnan(buy.score), -np.inf, buy.score)
        self.has_bar = ~np.isnan(self.close)
        self.mark = pd.DataFrame(self.close.T).ffill().to_numpy().T  # last known close
        self.bar_of_day = [dict(zip(cols, range(len(cols)))) for cols in self.columns]

    def n_entry_episodes(self):
        """Count entry rising edges (a new opportunity), not every qualifying day."""
        total = 0
        for k, cols in enumerate(self.columns):
            entry = self.entry[k, cols]
            total += int(entry[0]) + int(np.sum(entry[1:] & ~entry[:-1]))
        return total


def run_engine(frames, buy_algo, sell_algo, config, regime_ok=None):
    """Backtest `frames` ({ticker: OHLCV DataFrame}) through one account.

    `regime_ok` (required when config.regime_filter) is a boolean Series indexed by
    date: True = market risk-on. Days before its first value count as risk-off.
    """
    config.validate()
    book = _Book(frames, buy_algo, sell_algo)
    regime = _regime_by_day(book.calendar, regime_ok, config.regime_filter)
    return _Loop(book, buy_algo, sell_algo, config, regime).run()


def _regime_by_day(calendar, regime_ok, enabled):
    if not enabled:
        return np.ones(len(calendar), dtype=bool)
    if regime_ok is None:
        raise ConfigurationError("regime_filter=True requires a regime_ok series.")
    aligned = regime_ok.astype(float).reindex(calendar, method="ffill")
    return (aligned == 1.0).to_numpy()  # before the first market value: risk-off


class _Loop:
    """The day-by-day account state machine (see the module docstring for the order)."""

    def __init__(self, book, buy_algo, sell_algo, config, regime):
        self.book, self.config, self.regime = book, config, regime
        self.buy_name, self.sell_name = buy_algo.name, sell_algo.name
        self.cost = config.cost_bps / 10_000.0
        self.cash = float(config.starting_capital)
        self.held = {}            # ticker_index -> _Position (insertion order = fill order)
        self.pending_buys = {}    # ticker_index -> decision day
        self.pending_sells = set()
        self.trades = []

    def run(self):
        book = self.book
        n_days = len(book.calendar)
        cash_series, holdings_series = np.empty(n_days), np.empty(n_days)
        for day in range(n_days):
            self._age_positions(day)
            if self.config.fill_mode == "next_open":
                self._fill_pending(day)
            self._intrabar_stops(day)
            if not self.regime[day]:
                self._exit_all_with_bar(day, "regime")
            self._decide_buys(day)
            self._decide_sells(day)
            self._final_liquidations(day)
            holdings = sum(p.shares * book.mark[k, day] for k, p in self.held.items())
            cash_series[day], holdings_series[day] = self.cash, holdings
        cash = pd.Series(cash_series, index=book.calendar)
        holdings = pd.Series(holdings_series, index=book.calendar)
        return EngineResult(equity=cash + holdings, cash=cash, holdings=holdings,
                            trades=self.trades, n_entry_signals=book.n_entry_episodes())

    # --- per-day steps -------------------------------------------------------

    def _age_positions(self, day):
        """Advance holding-period bookkeeping for every held stock that trades today."""
        book = self.book
        for k, position in self.held.items():
            position.opened_at_close_today = False
            if book.has_bar[k, day] and day > position.fill_day:
                position.bars_held += 1
                position.highest_high = max(position.highest_high, book.high[k, day])

    def _fill_pending(self, day):
        book = self.book
        for k in [k for k in self.pending_sells if book.has_bar[k, day]]:
            self.pending_sells.discard(k)
            self._close(k, day, book.open[k, day], "signal")
        for k, decision_day in list(self.pending_buys.items()):
            if not book.has_bar[k, day]:
                continue
            del self.pending_buys[k]
            self._open(k, day, decision_day, book.open[k, day], self._equity(day - 1))

    def _intrabar_stops(self, day):
        book = self.book
        for k, position in list(self.held.items()):
            if position.stop_price is None or not book.has_bar[k, day]:
                continue
            if book.low[k, day] <= position.stop_price:
                self.pending_sells.discard(k)
                self._close(k, day, min(position.stop_price, book.open[k, day]), "stop")

    def _exit_all_with_bar(self, day, reason):
        for k in [k for k in self.held if self.book.has_bar[k, day]]:
            self.pending_sells.discard(k)
            self._close(k, day, self.book.close[k, day], reason)

    def _decide_buys(self, day):
        if not self.regime[day]:
            return
        book = self.book
        free_slots = self.config.max_positions - len(self.held) - len(self.pending_buys)
        if free_slots <= 0:
            return
        candidates = [k for k in np.flatnonzero(book.entry[:, day])
                      if k not in self.held and k not in self.pending_buys]
        if not candidates:
            return
        # Highest score first; ties keep universe order (stable sort).
        candidates.sort(key=lambda k: -book.score[k, day])
        equity_now = self._equity(day)
        for k in candidates:
            if free_slots <= 0:
                break
            if self.config.fill_mode == "next_open":
                self.pending_buys[k] = day
                free_slots -= 1
            elif self._open(k, day, day, book.close[k, day], equity_now):
                self.held[k].opened_at_close_today = True
                free_slots -= 1

    def _decide_sells(self, day):
        book = self.book
        for k, position in list(self.held.items()):
            if position.opened_at_close_today or k in self.pending_sells or not book.has_bar[k, day]:
                continue
            bar = book.bar_of_day[k][day]
            if not exit_hit(book.sell_signals[k], bar, book.close[k, day], position.highest_high,
                            position.bars_held, position.entry_price, position.stop_price):
                continue
            if self.config.fill_mode == "close":
                self._close(k, day, book.close[k, day], "signal")
            else:
                self.pending_sells.add(k)

    def _final_liquidations(self, day):
        for k in [k for k in self.held if self.book.last_day[k] == day]:
            self.pending_sells.discard(k)
            self._close(k, day, self.book.close[k, day], "final")
        for k in [k for k in self.pending_buys if self.book.last_day[k] == day]:
            del self.pending_buys[k]  # no next bar to fill on: dropped, never back-filled

    # --- order execution -------------------------------------------------------

    def _open(self, k, day, decision_day, fill_price, equity_now):
        """Size and open a position; return True if a position was opened."""
        book = self.book
        decision_bar = book.bar_of_day[k][decision_day]
        stop = self._initial_stop(book.buy_signals[k], decision_bar, fill_price)
        if stop is _UNPROTECTABLE:
            return False
        shares = self._size(equity_now, fill_price, stop)
        if shares <= 0:
            return False
        notional = shares * fill_price
        entry_cost = notional * self.cost
        buying_power = self._buying_power(equity_now)
        if notional + entry_cost > buying_power + 1e-9:
            raise InsufficientCashError(
                f"Buy needs ${notional + entry_cost:,.2f} but buying power is ${buying_power:,.2f}.")
        self.cash -= notional + entry_cost
        self.held[k] = _Position(ticker_index=k, fill_day=day, entry_price=float(fill_price),
                                 stop_price=stop, shares=shares, entry_cost=entry_cost,
                                 highest_high=float(book.high[k, day]))
        return True

    def _initial_stop(self, signals, decision_bar, fill_price):
        if not self.config.skip_unprotectable:
            return stop_price_at(signals, decision_bar, fill_price, self.config.stop_mode)
        if signals.has_stop and not _has_stop_below(signals, decision_bar, fill_price):
            # An entry we cannot protect (every candidate at/above the fill) is not
            # taken — you cannot risk-size a trade you cannot protect.
            return _UNPROTECTABLE
        return stop_price_at(signals, decision_bar, fill_price, self.config.stop_mode)

    def _close(self, k, day, fill_price, reason):
        position = self.held.pop(k)
        proceeds = position.shares * fill_price
        exit_cost = proceeds * self.cost
        self.cash += proceeds - exit_cost
        self.trades.append(Trade(
            ticker=self.book.tickers[k], entry_date=self.book.calendar[position.fill_day],
            entry_price=position.entry_price, stop_price=position.stop_price,
            shares=position.shares, exit_date=self.book.calendar[day],
            exit_price=float(fill_price), exit_reason=reason, bars_held=position.bars_held,
            costs=position.entry_cost + exit_cost))

    # --- sizing ---------------------------------------------------------------

    def _equity(self, day):
        """Cash + held shares marked at the latest close on/before `day`."""
        if day < 0:
            return self.cash
        return self.cash + sum(p.shares * self.book.mark[k, day] for k, p in self.held.items())

    def _buying_power(self, equity):
        return self.cash + equity * (self.config.leverage - 1.0)

    def _size(self, equity, fill_price, stop_price):
        """Whole shares to buy under the configured sizing mode (0 = skip)."""
        cfg = self.config
        budget = self._buying_power(equity)
        if cfg.sizing_mode == "fixed_fraction":
            budget = budget * cfg.fixed_fraction
        max_affordable = (budget / (1.0 + self.cost)) // fill_price
        if cfg.sizing_mode in ("all_in", "fixed_fraction"):
            return float(int(max_affordable))
        if stop_price is None:
            raise ConfigurationError(
                "risk_based sizing requires a stop loss, but the chosen buy algorithm "
                "provides none. Use all_in / fixed_fraction, or a strategy with a stop.")
        risk_per_share = fill_price - stop_price
        if risk_per_share <= 0:
            raise ConfigurationError(
                f"Non-positive risk per share ({risk_per_share:.4f}); stop must be below entry.")
        target_shares = equity * cfg.risk_pct / risk_per_share
        return float(int(min(target_shares, max_affordable)))


_UNPROTECTABLE = object()


def _has_stop_below(signals, i, fill_price):
    levels = [float(level[i]) for level in signals.stop_levels]
    if signals.stop_atr is not None:
        levels.append(float(fill_price - signals.stop_atr_mult * signals.stop_atr[i]))
    return any(level < fill_price for level in levels)
