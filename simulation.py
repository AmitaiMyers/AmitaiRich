"""Module 4 — Single-stock simulation (the engine + SQLite persistence).

Backtests ONE stock through the shared engine (engine.py: one account holding at
most one position) and writes every trade and every bar's equity to SQLite so the
dashboard can chart it. The fills / stops / sizing logic lives only in the engine.

Runtime switches (exposed in the GUI for testing):

    stop_mode    : "tightest" (default) | "widest"          -> see algorithms.select_stop
    sizing_mode  : "risk_based" (default) | "all_in" | "fixed_fraction"
    fill_mode    : "close" (default) | "next_open"

`fill_mode="next_open"` models deciding at a day's close and filling at the next
day's open. An order decided on the final bar (no next day) is dropped — surfaced as
a missing trade rather than silently back-filled.
"""

from dataclasses import dataclass

import pandas as pd

import database
from data_engine import fetch_data
from engine import VALID_FILL, VALID_SIZING, EngineConfig, run_engine
from errors import ConfigurationError, InsufficientDataError


@dataclass
class Position:
    """A single open long position (the view `calculate_sell` reads)."""

    entry_date: str
    entry_price: float
    shares: float
    stop_price: float  # may be None when the buy algorithm carries no stop
    bars_held: int = 0


def run_simulation(
    ticker,
    start_date,
    end_date,
    starting_capital,
    buy_algo,
    sell_algo,
    stop_mode="tightest",
    sizing_mode="risk_based",
    risk_pct=0.01,
    fixed_fraction=0.95,
    fill_mode="close",
    interval="1d",
    leverage=1.0,
    use_cache=True,
    db_path=database.DB_PATH,
):
    """Run a backtest end to end and return the new run_id.

    `interval` is the candle size ('1h' / '1d' / '1wk' / '1mo'); algorithm logic
    is timeframe-agnostic (all periods are measured in bars).
    """
    _validate_modes(sizing_mode, fill_mode)

    df = fetch_data(ticker, start_date, end_date, interval=interval, use_cache=use_cache)
    warmup = max(buy_algo.warmup_bars(), sell_algo.warmup_bars())
    if len(df) <= warmup + 1:
        raise InsufficientDataError(
            f"{ticker}: need more than {warmup + 1} bars for warmup, got {len(df)}. "
            f"Widen the date range or reduce indicator periods."
        )

    config = EngineConfig(
        starting_capital=float(starting_capital), max_positions=1, sizing_mode=sizing_mode,
        risk_pct=risk_pct, fixed_fraction=fixed_fraction, leverage=leverage,
        fill_mode=fill_mode, stop_mode=stop_mode,
    )
    result = run_engine({ticker: df}, buy_algo, sell_algo, config)

    conn = database.get_connection(db_path)
    database.init_db(conn)
    run_id = database.create_run(
        conn, ticker, buy_algo.name, sell_algo.name, starting_capital, str(start_date), str(end_date)
    )
    for trade in result.trades:
        database.record_trade(conn, run_id, ticker, "BUY", _date_str(trade.entry_date),
                              trade.entry_price, trade.shares, buy_algo.name)
        database.record_trade(conn, run_id, ticker, "SELL", _date_str(trade.exit_date),
                              trade.exit_price, trade.shares, sell_algo.name)
    # Equity is recorded from the first tradable bar (the warmup bar) onwards.
    for date in df.index[warmup:]:
        cash, holdings = float(result.cash[date]), float(result.holdings[date])
        database.record_equity(conn, run_id, _date_str(date), cash, holdings, cash + holdings)
    conn.commit()
    conn.close()
    return run_id


def compute_kpis(conn, run_id):
    """Compute headline KPIs for a finished run from the persisted ledger.

    Round trips are BUY/SELL pairs in chronological order (only one position is
    ever open, so trades strictly alternate). A round trip wins when its sell
    price exceeds its buy price.
    """
    run = database.get_run(conn, run_id)
    starting_capital = float(run["starting_capital"])

    equity = database.get_equity_curve(conn, run_id)
    final_equity = float(equity["total_equity"].iloc[-1]) if len(equity) else starting_capital
    total_return = (final_equity - starting_capital) / starting_capital

    trades = database.get_trades(conn, run_id)
    buys = trades[trades["trade_type"] == "BUY"].reset_index(drop=True)
    sells = trades[trades["trade_type"] == "SELL"].reset_index(drop=True)
    round_trips = min(len(buys), len(sells))
    wins = int((sells["price"].iloc[:round_trips] > buys["price"].iloc[:round_trips]).sum())
    win_rate = wins / round_trips if round_trips else 0.0

    return {
        "starting_capital": starting_capital,
        "final_equity": final_equity,
        "total_return": total_return,
        "num_trades": round_trips,
        "wins": wins,
        "win_rate": win_rate,
    }


def _validate_modes(sizing_mode, fill_mode):
    """Fail fast on invalid runtime switches."""
    if sizing_mode not in VALID_SIZING:
        raise ConfigurationError(f"sizing_mode must be one of {VALID_SIZING}, got {sizing_mode!r}")
    if fill_mode not in VALID_FILL:
        raise ConfigurationError(f"fill_mode must be one of {VALID_FILL}, got {fill_mode!r}")


def _date_str(timestamp):
    """Normalize an index timestamp to a sortable string for the database.

    Includes the time component so intraday ('1h') bars stay distinct; for daily
    and coarser candles the time is simply 00:00:00.
    """
    return pd.Timestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
