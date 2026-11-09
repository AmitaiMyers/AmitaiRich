"""Shared-capital portfolio backtester (the realistic single-account model).

`batch.py` runs each ticker INDEPENDENTLY (an algorithm-evaluation scan). This
module models how the strategy is actually traded: ONE account holding many
positions at once, walking the market day by day under real constraints — finite
capital, a cap on concurrent positions, risk-based sizing on live equity,
transaction costs, long-only, and (optionally) next-day-open fills.

It is a thin layer over engine.py (the same loop the single-stock simulation runs),
so every fill/stop/sizing rule is shared. Buy priority = the buy strategy's own
score (raw momentum for the Momentum Rider — the same ranking the daily scan shows)
unless `rank_by` overrides it.

Entries are state-based, exactly like the daily scan: a stock whose entry condition
holds but finds no free slot today stays a candidate on later days. (The previous
overlay engine could only enter on a trade's first signal day, which understated
how the production list is actually used.)
"""

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

import analytics
import indicators
from algorithms import vol_adjusted_momentum
from engine import EngineConfig, run_engine
from errors import ConfigurationError


@dataclass
class PortfolioConfig:
    """Realistic single-account assumptions (defaults = the research 'realistic' profile)."""

    starting_capital: float = 100_000.0
    max_positions: int = 15
    risk_pct: float = 0.01          # 1% of live equity risked per trade (entry->stop)
    cost_bps: float = 10.0          # per-side cost in basis points (10 = 0.10%)
    fill_mode: str = "close"        # "close" | "next_open" (scan after the close, buy next open)
    stop_mode: str = "widest"
    sizing_mode: str = "risk_based"  # or "equal_weight"
    rank_by: str = "signal"         # "signal" (strategy score) | "momentum" | "vol_adj"
    regime_filter: bool = False     # SPY below its MA -> no new buys, exit holdings
    market_ma: int = 200

    def engine_config(self):
        return EngineConfig(
            starting_capital=self.starting_capital, max_positions=self.max_positions,
            sizing_mode=self.sizing_mode, risk_pct=self.risk_pct, cost_bps=self.cost_bps,
            fill_mode=self.fill_mode, stop_mode=self.stop_mode, skip_unprotectable=True,
            regime_filter=self.regime_filter,
        )


# Alternative buy-priority scores (the strategy's own score is the default).
RANKERS = {
    "momentum": lambda df: indicators.roc(df["Close"], 126).to_numpy(dtype=float),
    "vol_adj": lambda df: vol_adjusted_momentum(df, 126, 20).to_numpy(dtype=float),
}


@dataclass
class PortfolioResult:
    """Everything needed to score and explain one portfolio run."""

    equity: pd.Series
    trades: list
    n_signals: int
    holdings: pd.Series = None      # market value of open positions per day
    metrics: dict = field(default_factory=dict)


class _AdjustedBuy:
    """A buy algorithm with an optional alternative ranking score and/or entry start date."""

    def __init__(self, algorithm, ranker, trade_from):
        self._algorithm, self._ranker, self._trade_from = algorithm, ranker, trade_from
        self.name = algorithm.name

    def warmup_bars(self):
        return self._algorithm.warmup_bars()

    def signals_for(self, ticker, history):
        built = self._algorithm.signals_for(ticker, history)
        if self._ranker is not None:
            built = replace(built, score=self._ranker(history))
        if self._trade_from is not None:
            built = replace(built, entry=built.entry & (history.index >= self._trade_from))
        return built


def run_portfolio(frames, buy_algo, sell_algo, config, market_close=None, trade_from=None):
    """Backtest one shared account over `frames` ({ticker: OHLCV DataFrame}).

    `trade_from` (optional date) blocks entries before it and measures performance
    from it — used for walk-forward windows (indicators still warm up on earlier data).
    """
    if config.rank_by != "signal" and config.rank_by not in RANKERS:
        raise ConfigurationError(f"rank_by must be 'signal' or one of {sorted(RANKERS)}")
    if config.regime_filter and market_close is None:
        raise ConfigurationError("regime_filter=True requires market_close.")
    regime_ok = market_regime(market_close, config.market_ma) if config.regime_filter else None

    start = None if trade_from is None else pd.Timestamp(trade_from)
    ranker = None if config.rank_by == "signal" else RANKERS[config.rank_by]
    same_algorithm = sell_algo is buy_algo
    if ranker is not None or start is not None:
        buy_algo = _AdjustedBuy(buy_algo, ranker, start)
        sell_algo = buy_algo if same_algorithm else sell_algo
    if start is not None:
        frames = {t: df for t, df in frames.items() if df.index[-1] >= start}

    result = run_engine(frames, buy_algo, sell_algo, config.engine_config(), regime_ok=regime_ok)
    keep = result.equity.index >= start if start is not None else slice(None)
    out = PortfolioResult(equity=result.equity[keep], trades=result.trades,
                          n_signals=result.n_entry_signals, holdings=result.holdings[keep])
    out.metrics = portfolio_metrics(out)
    return out


def market_regime(market_close, ma_period):
    """Boolean per date: is the market above its `ma_period` SMA? (NaN MA -> False)."""
    return market_close > indicators.sma(market_close, ma_period)


# ---------------------------------------------------------------------------
# Benchmarks + metrics
# ---------------------------------------------------------------------------

def buy_and_hold_portfolio(close_by_ticker, config):
    """Equal-weight buy-and-hold of the whole universe (the benchmark to beat).

    Splits starting capital equally across all stocks and buys each at its FIRST
    available close (whole shares, with entry cost), holding to the end. A stock that
    lists later keeps its sleeve in cash until it lists. (The previous version spent
    every sleeve on day one, so later listings made the curve start artificially low
    and jump on listing — inflating the benchmark's CAGR.)
    """
    matrix = pd.DataFrame(close_by_ticker).sort_index().ffill()
    per_stock = config.starting_capital / len(close_by_ticker)
    cost = config.cost_bps / 10_000.0
    listed = [t for t, s in close_by_ticker.items() if s.notna().any()]
    first_price = np.array([close_by_ticker[t].dropna().iloc[0] for t in listed])
    first_day = np.array([close_by_ticker[t].dropna().index[0] for t in listed])
    shares = np.floor((per_stock / (1.0 + cost)) / first_price)
    spent = shares * first_price * (1.0 + cost)
    is_listed = matrix.index.to_numpy()[:, None] >= first_day[None, :]
    prices = matrix[listed].to_numpy()
    holdings = np.where(is_listed, prices * shares, 0.0).sum(axis=1)
    cash = config.starting_capital - np.where(is_listed, spent, 0.0).sum(axis=1)
    return pd.Series(cash + holdings, index=matrix.index)


def single_asset_benchmark(close, config, start=None):
    """Buy-and-hold of one instrument (e.g. SPY) with the same capital and entry cost."""
    series = close if start is None else close[close.index >= pd.Timestamp(start)]
    cost = config.cost_bps / 10_000.0
    shares = float(int((config.starting_capital / (1.0 + cost)) // float(series.iloc[0])))
    cash = config.starting_capital - shares * float(series.iloc[0]) * (1.0 + cost)
    return cash + shares * series


def equity_metrics(equity, periods_per_year=252):
    """CAGR / max drawdown / Sharpe / Calmar / total return of an equity curve."""
    if len(equity) < 2:
        raise ConfigurationError("An equity curve needs at least 2 points to score.")
    cagr = analytics.cagr(equity, periods_per_year)
    max_dd = analytics.max_drawdown(equity)
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "cagr": cagr,
        "max_dd": max_dd,
        "max_underwater_days": analytics.longest_underwater_days(equity),
        "sharpe": analytics.sharpe(equity, periods_per_year),
        "calmar": float(cagr / abs(max_dd)) if max_dd < 0 else 0.0,
        "final_equity": float(equity.iloc[-1]),
    }


def portfolio_metrics(result, periods_per_year=252):
    """Risk/return + activity metrics for ranking a portfolio run."""
    metrics = equity_metrics(result.equity, periods_per_year)
    trades = result.trades
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    metrics.update({
        "n_trades": len(trades),
        "n_signals": result.n_signals,
        "win_rate": float(np.mean([t.pnl > 0 for t in trades])) if trades else 0.0,
        "avg_hold_bars": float(np.mean([t.bars_held for t in trades])) if trades else 0.0,
        "costs": float(sum(t.costs for t in trades)),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "longest_losing_streak": longest_losing_streak(trades),
        "exposure": float((result.holdings / result.equity).mean()) if result.holdings is not None else None,
    })
    return metrics


def longest_losing_streak(trades):
    """Most consecutive losing round trips, in exit order."""
    longest = current = 0
    for trade in sorted(trades, key=lambda t: t.exit_date):
        current = current + 1 if trade.pnl < 0 else 0
        longest = max(longest, current)
    return longest
