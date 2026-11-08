"""Module 4 — Simulation sandbox (the core backtest loop).

Steps through historical data one day at a time, in chronological order, and
hands each algorithm only the history available up to that day (no lookahead).
A single long position is held at a time. Every trade and every day's equity is
written to SQLite.

Three behaviours are runtime switches (exposed in the GUI for testing):

    stop_mode    : "tightest" (default) | "widest"          -> see algorithms.select_stop
    sizing_mode  : "risk_based" (default) | "all_in" | "fixed_fraction"
    fill_mode    : "close" (default) | "next_open"

`fill_mode="next_open"` models deciding at a day's close and filling at the next
day's open via a pending-order queue. An order decided on the final bar (no next
day) is dropped — surfaced as a missing trade rather than silently back-filled.
"""

from dataclasses import dataclass

import pandas as pd

import database
from data_engine import fetch_data
from errors import ConfigurationError, InsufficientCashError, InsufficientDataError

VALID_SIZING = ("risk_based", "all_in", "fixed_fraction")
VALID_FILL = ("close", "next_open")


@dataclass
class Position:
    """A single open long position."""

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

    conn = database.get_connection(db_path)
    database.init_db(conn)
    run_id = database.create_run(
        conn, ticker, buy_algo.name, sell_algo.name, starting_capital, str(start_date), str(end_date)
    )

    cash = float(starting_capital)
    position = None
    pending = None  # {"side": "BUY"|"SELL", "decision_index": int} — next_open mode only

    dates = df.index
    total_bars = len(df)

    for i in range(warmup, total_bars):
        row = df.iloc[i]
        today_open = float(row["Open"])
        today_low = float(row["Low"])
        today_close = float(row["Close"])
        date_str = _date_str(dates[i])
        slice_today = df.iloc[: i + 1]

        # (A) Execute orders queued yesterday at today's open (next_open mode).
        if pending is not None:
            if pending["side"] == "BUY" and position is None:
                decision_slice = df.iloc[: pending["decision_index"] + 1]
                cash, position = _execute_buy(
                    conn, run_id, ticker, buy_algo, cash, today_open, date_str,
                    decision_slice, stop_mode, sizing_mode, risk_pct, fixed_fraction, leverage,
                )
            elif pending["side"] == "SELL" and position is not None:
                cash = _execute_sell(
                    conn, run_id, ticker, sell_algo.name, cash, position, today_open, date_str
                )
                position = None
            pending = None

        # (B) Intrabar stop check (applies in both fill modes). A gap-down below
        #     the stop fills at the (worse) open price, not the stop level.
        if position is not None and position.stop_price is not None and today_low <= position.stop_price:
            stop_fill_price = min(position.stop_price, today_open)
            cash = _execute_sell(
                conn, run_id, ticker, sell_algo.name, cash, position, stop_fill_price, date_str
            )
            position = None

        # (C) Signal generation at today's close.
        if position is None and pending is None:
            if buy_algo.scan_and_buy(slice_today):
                if fill_mode == "close":
                    cash, position = _execute_buy(
                        conn, run_id, ticker, buy_algo, cash, today_close, date_str,
                        slice_today, stop_mode, sizing_mode, risk_pct, fixed_fraction, leverage,
                    )
                else:
                    pending = {"side": "BUY", "decision_index": i}
        elif position is not None and pending is None:
            if sell_algo.calculate_sell(position, slice_today):
                if fill_mode == "close":
                    cash = _execute_sell(
                        conn, run_id, ticker, sell_algo.name, cash, position, today_close, date_str
                    )
                    position = None
                else:
                    pending = {"side": "SELL", "decision_index": i}

        # (D) Mark to market on today's close and record the equity point.
        position_value = position.shares * today_close if position is not None else 0.0
        database.record_equity(conn, run_id, date_str, cash, position_value, cash + position_value)

        # (E) Age an open position by one bar (entry day ends at bars_held = 0).
        if position is not None:
            position.bars_held += 1

    # Liquidate any still-open position at the final close so KPIs reflect closed equity.
    if position is not None:
        final_close = float(df.iloc[-1]["Close"])
        cash = _execute_sell(
            conn, run_id, ticker, sell_algo.name, cash, position, final_close, _date_str(dates[-1])
        )
        position = None

    conn.commit()
    conn.close()
    return run_id


def _execute_buy(
    conn, run_id, ticker, buy_algo, cash, fill_price, fill_date,
    decision_slice, stop_mode, sizing_mode, risk_pct, fixed_fraction, leverage=1.0,
):
    """Size, validate cash, open the position, and record the BUY.

    Returns (new_cash, position). If the position cannot be sized to at least one
    whole share, no trade is made and the original cash/position(None) is returned.
    With leverage > 1 the order may cost more than cash (the balance goes negative,
    modelling a margin loan); the cap is cash * leverage.
    """
    stop_price = buy_algo.compute_stop(fill_price, decision_slice, stop_mode)
    shares = _size_position(sizing_mode, cash, fill_price, stop_price, risk_pct, fixed_fraction, leverage)
    if shares <= 0:
        return cash, None

    cost = shares * fill_price
    if cost > cash * leverage + 1e-9:  # tiny epsilon for float rounding
        raise InsufficientCashError(
            f"Buy needs ${cost:,.2f} but buying power is ${cash * leverage:,.2f} "
            f"(cash ${cash:,.2f} x leverage {leverage})."
        )

    cash -= cost
    position = Position(
        entry_date=fill_date, entry_price=fill_price, shares=shares, stop_price=stop_price
    )
    database.record_trade(conn, run_id, ticker, "BUY", fill_date, fill_price, shares, buy_algo.name)
    return cash, position


def _execute_sell(conn, run_id, ticker, sell_algo_name, cash, position, fill_price, fill_date):
    """Close the position, add proceeds to cash, and record the SELL."""
    proceeds = position.shares * fill_price
    database.record_trade(
        conn, run_id, ticker, "SELL", fill_date, fill_price, position.shares, sell_algo_name
    )
    return cash + proceeds


def _size_position(sizing_mode, cash, fill_price, stop_price, risk_pct, fixed_fraction, leverage=1.0):
    """Return the (whole) number of shares to buy under the chosen sizing mode.

    `leverage` scales buying power (cash * leverage). At entry the position is flat,
    so cash == equity and leverage is applied to equity.
    """
    buying_power = cash * leverage
    if sizing_mode == "all_in":
        return float(int(buying_power // fill_price))

    if sizing_mode == "fixed_fraction":
        budget = buying_power * fixed_fraction
        return float(int(budget // fill_price))

    if sizing_mode == "risk_based":
        if stop_price is None:
            raise ConfigurationError(
                "risk_based sizing requires a stop loss, but the chosen buy algorithm "
                "provides none. Use all_in / fixed_fraction, or a strategy with a stop."
            )
        risk_per_share = fill_price - stop_price
        if risk_per_share <= 0:
            raise ConfigurationError(
                f"Non-positive risk per share ({risk_per_share:.4f}); stop must be below entry."
            )
        risk_budget = cash * risk_pct
        target_shares = risk_budget / risk_per_share
        max_affordable = buying_power // fill_price
        return float(int(min(target_shares, max_affordable)))

    raise ConfigurationError(f"Unknown sizing_mode {sizing_mode!r}; valid: {VALID_SIZING}")


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

    wins = 0
    for k in range(round_trips):
        if sells.loc[k, "price"] > buys.loc[k, "price"]:
            wins += 1
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
