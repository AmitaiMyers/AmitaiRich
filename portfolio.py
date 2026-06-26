"""Shared-capital portfolio backtester (the realistic single-account model).

The project's `batch.py` runs each ticker INDEPENDENTLY (an algorithm-evaluation
scan, not a portfolio). This module adds the missing piece: ONE account that holds
many positions at once and walks the market day by day, deciding BUYs then SELLs
each day, under real-world constraints (finite capital, a cap on concurrent
positions, risk-based sizing on live equity, transaction costs, long-only).

Design — a capital-allocation overlay on trusted per-stock signals
----------------------------------------------------------------------
A strategy's exit (stop, sell signal, chandelier, MA-breakdown, target) depends
ONLY on a stock's own price history and its entry bar — never on the portfolio's
state (see simulation.py / exits.py). So a stock's realized round-trip trades are
identical whether or not the portfolio happens to take them. We exploit that:

  1. `simulate_ticker_trades` replays one stock through the strategy exactly as
     `simulation.run_simulation` would (close fills, intrabar catastrophe stop,
     final-bar liquidation) and returns its round-trip trades IN MEMORY. This is a
     lean mirror of run_simulation, validated for equivalence in tests.
  2. `run_portfolio` replays those trades as *intentions* through one account:
     each day it first opens eligible new entries (subject to free slots + cash,
     risk-sized to current equity), THEN processes exits. A winner is held until
     its OWN exit fires — the portfolio never rotates out of a winner to fund a
     new idea, which is exactly the "hold growers, minimise actions" goal.

Because exits are path-independent, an entry the portfolio skips (no slot/cash)
simply means that stock is flat until its strategy next signals — the next
round-trip's entry is a fresh, independent opportunity. Capital contention is the
only thing the overlay adds on top of the per-stock truth.

Fail-fast: invalid sizing / missing market data raise named errors; no silent
fallbacks. Costs and sizing follow simulation.py's conventions.
"""

from dataclasses import dataclass, field

import pandas as pd

import analytics
import indicators
from errors import ConfigurationError

# A round-trip trade produced by replaying one stock through a strategy.
@dataclass
class TickerTrade:
    """One realized round trip for a single stock, generated in isolation."""

    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_date: pd.Timestamp
    exit_price: float
    exit_reason: str   # "stop" | "signal" | "final"


@dataclass
class PortfolioConfig:
    """Realistic single-account assumptions (defaults = the chosen 'realistic' profile)."""

    starting_capital: float = 100_000.0
    max_positions: int = 15
    risk_pct: float = 0.01          # 1% of live equity risked per trade (entry->stop)
    cost_bps: float = 10.0          # round-trip-side cost in basis points (10 = 0.10%)
    rank_lookback: int = 126        # bars of momentum used to prioritise competing buys
    market_filter: bool = False     # block new buys when the market is below its MA
    market_ma: int = 200            # market regime MA (bars)


@dataclass
class PortfolioResult:
    """Everything needed to score and explain one portfolio run."""

    equity: pd.Series
    executed: list                  # list of dicts: taken trades with shares/pnl
    n_signals: int                  # entry opportunities offered (across all stocks)
    n_taken: int                    # entries actually opened (capital permitting)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 1 — per-stock trade generation (lean in-memory mirror of run_simulation)
# ---------------------------------------------------------------------------

def simulate_ticker_trades(ticker, df, buy_algo, sell_algo, stop_mode="tightest"):
    """Replay one stock through the strategy; return its round-trip trades.

    Mirrors simulation.run_simulation with fill_mode='close': enter at today's
    close on a BUY signal (recording the algorithm's stop), exit intrabar if the
    low pierces the stop (gap-downs fill at the worse of stop/open), otherwise exit
    at the close when the sell signal fires; liquidate any open position at the
    final close. Sizing is irrelevant here (1 share) — the portfolio sizes later.
    """
    warmup = max(buy_algo.warmup_bars(), sell_algo.warmup_bars())
    if len(df) <= warmup + 1:
        return []

    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    open_ = df["Open"].to_numpy()
    close = df["Close"].to_numpy()
    dates = df.index

    trades = []
    position = None  # dict: entry_date, entry_price, stop_price, bars_held
    total_bars = len(df)

    for i in range(warmup, total_bars):
        slice_today = df.iloc[: i + 1]

        # (B) Intrabar catastrophe stop — checked before any close-based decision.
        if position is not None and position["stop_price"] is not None \
                and low[i] <= position["stop_price"]:
            fill = min(position["stop_price"], open_[i])
            trades.append(TickerTrade(
                ticker=ticker, entry_date=position["entry_date"],
                entry_price=position["entry_price"], stop_price=position["stop_price"],
                exit_date=dates[i], exit_price=float(fill), exit_reason="stop"))
            position = None

        # (C) Close-based signal generation.
        if position is None:
            if buy_algo.scan_and_buy(slice_today):
                entry_price = float(close[i])
                stop_price = _stop_or_none(buy_algo, entry_price, slice_today, stop_mode)
                # An entry we cannot protect with a stop below entry (a degenerate
                # zero-volatility bar where every stop candidate sits at/above the
                # close) is not taken — you cannot risk-size a trade you cannot
                # protect. This is the portfolio layer's per-entry analog of
                # batch.py's per-ticker error boundary, not a silent data repair.
                if stop_price is not None:
                    position = {"entry_date": dates[i], "entry_price": entry_price,
                                "stop_price": stop_price, "bars_held": 0}
        else:
            if sell_algo.calculate_sell(_as_position(position), slice_today):
                trades.append(TickerTrade(
                    ticker=ticker, entry_date=position["entry_date"],
                    entry_price=position["entry_price"], stop_price=position["stop_price"],
                    exit_date=dates[i], exit_price=float(close[i]), exit_reason="signal"))
                position = None

        # (E) Age the open position by one bar (entry bar ends at bars_held = 0).
        if position is not None:
            position["bars_held"] += 1

    # Liquidate any still-open position at the final close.
    if position is not None:
        trades.append(TickerTrade(
            ticker=ticker, entry_date=position["entry_date"],
            entry_price=position["entry_price"], stop_price=position["stop_price"],
            exit_date=dates[-1], exit_price=float(close[-1]), exit_reason="final"))

    return trades


def _stop_or_none(buy_algo, entry_price, slice_today, stop_mode):
    """Return the algorithm's stop, or None if no valid stop exists for this bar.

    `compute_stop` (via algorithms.select_stop) raises ConfigurationError when no
    candidate level is strictly below the entry — a genuinely unprotectable entry.
    In the portfolio context that means "skip this trade", so we convert only that
    specific signal to None. A real misconfiguration (unknown param key) raises at
    build time, before this point, and is never masked here.
    """
    try:
        return buy_algo.compute_stop(entry_price, slice_today, stop_mode)
    except ConfigurationError:
        return None


def _as_position(state):
    """Adapt the lean dict to the lightweight object `calculate_sell` expects.

    The sell algorithms read `position.bars_held`, `position.entry_price`, and
    `position.stop_price` (see exits.py). A tiny shim avoids importing simulation's
    dataclass and keeps this module independent.
    """
    return _PositionView(state["entry_price"], state["stop_price"], state["bars_held"])


@dataclass
class _PositionView:
    entry_price: float
    stop_price: float
    bars_held: int


# ---------------------------------------------------------------------------
# Stage 2 — the shared-capital overlay
# ---------------------------------------------------------------------------

def _build_close_matrix(close_by_ticker):
    """Align every stock's close onto one calendar (dates x tickers), forward-filled.

    Forward fill carries the last known price across non-trading gaps so a held
    position is always marked to its most recent close. Tickers are only valued on
    dates at/after their first listing (leading NaNs stay NaN -> not yet held).
    """
    matrix = pd.DataFrame(close_by_ticker).sort_index()
    return matrix.ffill()


def _momentum_scores(close_matrix, lookback):
    """Trailing `lookback`-bar return per stock (the buy-priority signal)."""
    return close_matrix.pct_change(lookback)


def _market_ok_series(market_close, ma_period):
    """Boolean per-date: is the market above its `ma_period` SMA (regime filter)?"""
    ma = indicators.sma(market_close, ma_period)
    return (market_close > ma).fillna(False)


def run_portfolio(trades_by_ticker, close_by_ticker, config, market_close=None):
    """Replay per-stock trades through one capital-constrained account.

    Each day, in this order (matching the owner's spec):
      1. BUY: among entries scheduled today for stocks not currently held, take the
         highest-momentum ones while a slot is free and cash allows (risk-sized to
         current equity, long-only, no leverage).
      2. SELL: close any held position whose strategy exit fires today.
      3. Mark to market on the close and record equity.

    Returns a PortfolioResult (equity curve + execution log + counts).
    """
    if config.market_filter and market_close is None:
        raise ConfigurationError("market_filter=True requires a market_close series.")

    close_matrix = _build_close_matrix(close_by_ticker)
    calendar = close_matrix.index
    momentum = _momentum_scores(close_matrix, config.rank_lookback)
    market_ok = _market_ok_series(market_close.reindex(calendar).ffill(), config.market_ma) \
        if config.market_filter else None

    # Index entries by date for O(1) daily lookup. Each entry knows its matched exit.
    entries_by_date = {}
    n_signals = 0
    for ticker, trades in trades_by_ticker.items():
        for trade in trades:
            entry_day = trade.entry_date.normalize()
            entries_by_date.setdefault(entry_day, []).append(trade)
            n_signals += 1

    cost = config.cost_bps / 10_000.0
    cash = float(config.starting_capital)
    open_positions = {}   # ticker -> dict(shares, entry_price, exit_date, exit_price, trade)
    executed = []
    equity_points = []

    for day in calendar:
        # --- (1) BUY: rank today's fresh entries by momentum, fill while able. ---
        candidates = entries_by_date.get(day, [])
        if candidates:
            equity_now = _mark_to_market(cash, open_positions, close_matrix, day)
            ranked = sorted(
                candidates,
                key=lambda t: _entry_rank(momentum, t.ticker, day),
                reverse=True,
            )
            for trade in ranked:
                if len(open_positions) >= config.max_positions:
                    break
                if trade.ticker in open_positions:
                    continue
                shares = _size(equity_now, cash, trade, config.risk_pct, cost)
                if shares <= 0:
                    continue
                notional = shares * trade.entry_price
                cash -= notional + notional * cost
                open_positions[trade.ticker] = {
                    "shares": shares, "entry_price": trade.entry_price,
                    "exit_date": trade.exit_date.normalize(), "exit_price": trade.exit_price,
                    "entry_date": day, "trade": trade,
                }

        # --- (2) SELL: close positions whose strategy exit lands today. ---
        for ticker in [t for t, p in open_positions.items() if p["exit_date"] == day]:
            pos = open_positions.pop(ticker)
            proceeds = pos["shares"] * pos["exit_price"]
            cash += proceeds - proceeds * cost
            executed.append({
                "ticker": ticker, "entry_date": pos["entry_date"], "exit_date": day,
                "entry_price": pos["entry_price"], "exit_price": pos["exit_price"],
                "shares": pos["shares"],
                "pnl": proceeds - pos["shares"] * pos["entry_price"],
                "ret": pos["exit_price"] / pos["entry_price"] - 1.0,
                "bars_held": int((day - pos["entry_date"]).days),
                "reason": pos["trade"].exit_reason,
            })

        # --- (3) Mark to market and record. ---
        equity_points.append((day, _mark_to_market(cash, open_positions, close_matrix, day)))

    equity = pd.Series({d: v for d, v in equity_points}).sort_index()
    result = PortfolioResult(equity=equity, executed=executed,
                             n_signals=n_signals, n_taken=len(executed))
    result.metrics = portfolio_metrics(result, config)
    return result


def _entry_rank(momentum, ticker, day):
    """Momentum score for a stock on a day; missing -> very low priority."""
    if ticker not in momentum.columns:
        return float("-inf")
    value = momentum.at[day, ticker] if day in momentum.index else None
    if value is None or pd.isna(value):
        return float("-inf")
    return float(value)


def _size(equity_now, cash, trade, risk_pct, cost):
    """Whole-share size: risk `risk_pct` of equity over the entry->stop distance.

    Capped by affordable shares given cash net of entry cost (long-only, no margin).
    Mirrors simulation._size_position's risk_based branch but risks live EQUITY
    (cash + open positions), the correct base for a multi-position account.
    """
    if trade.stop_price is None:
        raise ConfigurationError("Portfolio sizing requires a stop; strategy provided none.")
    risk_per_share = trade.entry_price - trade.stop_price
    if risk_per_share <= 0:
        raise ConfigurationError(
            f"Non-positive risk/share for {trade.ticker} at {trade.entry_date.date()}; "
            f"stop {trade.stop_price} must be below entry {trade.entry_price}.")
    target_shares = (equity_now * risk_pct) / risk_per_share
    max_affordable = (cash / (1.0 + cost)) // trade.entry_price
    return float(int(min(target_shares, max_affordable)))


def _mark_to_market(cash, open_positions, close_matrix, day):
    """Account equity = cash + sum(open shares x last close)."""
    value = cash
    for ticker, pos in open_positions.items():
        price = close_matrix.at[day, ticker] if ticker in close_matrix.columns else None
        if price is None or pd.isna(price):
            price = pos["entry_price"]  # not yet priced on calendar -> hold at cost
        value += pos["shares"] * float(price)
    return value


# ---------------------------------------------------------------------------
# Benchmark + metrics
# ---------------------------------------------------------------------------

def buy_and_hold_portfolio(close_by_ticker, config):
    """Equal-weight buy-and-hold of the whole universe (the benchmark to beat).

    Splits starting capital equally across all stocks, buys each at its first
    available close (whole shares, with entry cost), holds to the end. Idle cash
    (rounding + not-yet-listed sleeves) earns nothing. Returns the equity curve.
    """
    close_matrix = _build_close_matrix(close_by_ticker)
    calendar = close_matrix.index
    per_stock = config.starting_capital / len(close_by_ticker)
    cost = config.cost_bps / 10_000.0

    shares = {}
    spent = 0.0
    for ticker, series in close_by_ticker.items():
        first = series.dropna()
        if first.empty:
            continue
        price = float(first.iloc[0])
        n = float(int((per_stock / (1.0 + cost)) // price))
        if n > 0:
            shares[ticker] = (n, first.index[0])
            spent += n * price * (1.0 + cost)

    cash = config.starting_capital - spent
    equity = {}
    for day in calendar:
        value = cash
        for ticker, (n, start_day) in shares.items():
            if day >= start_day:
                price = close_matrix.at[day, ticker]
                if not pd.isna(price):
                    value += n * float(price)
        equity[day] = value
    return pd.Series(equity).sort_index()


def portfolio_metrics(result, config, periods_per_year=252):
    """Risk/return + activity metrics for ranking (risk-adjusted, beats-B&H view)."""
    equity = result.equity
    if len(equity) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0,
                "calmar": 0.0, "n_taken": 0, "n_signals": result.n_signals,
                "avg_hold_days": 0.0, "win_rate": 0.0, "exposure": 0.0,
                "final_equity": float(config.starting_capital)}
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = analytics.cagr(equity, periods_per_year)
    max_dd = analytics.max_drawdown(equity)
    sharpe = analytics.sharpe(equity, periods_per_year)
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0

    rets = [e["ret"] for e in result.executed]
    holds = [e["bars_held"] for e in result.executed]
    win_rate = float(sum(1 for r in rets if r > 0) / len(rets)) if rets else 0.0
    avg_hold = float(sum(holds) / len(holds)) if holds else 0.0
    return {
        "total_return": total_return, "cagr": cagr, "max_dd": max_dd,
        "sharpe": sharpe, "calmar": calmar,
        "n_taken": result.n_taken, "n_signals": result.n_signals,
        "avg_hold_days": avg_hold, "win_rate": win_rate,
        "final_equity": float(equity.iloc[-1]),
    }
