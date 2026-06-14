"""Module 1 — SQLite persistence layer.

Stores run metadata, the trade ledger, and the daily equity curve in a local
`simulation.db` file. Schema creation is idempotent.

Transaction policy (explicit and predictable):
- `init_db` and `create_run` commit immediately (DDL / durable run id).
- `record_trade` / `record_equity` do NOT commit — the caller (the simulation
  loop) commits once at the end so a whole run is written as one fast batch.
"""

import sqlite3
from datetime import datetime

import pandas as pd

from errors import InvalidTradeTypeError

DB_PATH = "simulation.db"
VALID_TRADE_TYPES = ("BUY", "SELL")


def get_connection(db_path=DB_PATH):
    """Open a SQLite connection with row access by column name."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    """Create all tables if they do not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker           TEXT    NOT NULL,
            buy_algorithm    TEXT    NOT NULL,
            sell_algorithm   TEXT    NOT NULL,
            starting_capital REAL    NOT NULL,
            start_date       TEXT    NOT NULL,
            end_date         TEXT    NOT NULL,
            created_at       TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER NOT NULL,
            ticker         TEXT    NOT NULL,
            trade_type     TEXT    NOT NULL CHECK (trade_type IN ('BUY', 'SELL')),
            date           TEXT    NOT NULL,
            price          REAL    NOT NULL,
            shares         REAL    NOT NULL,
            algorithm_name TEXT    NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_equity (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER NOT NULL,
            date           TEXT    NOT NULL,
            cash           REAL    NOT NULL,
            position_value REAL    NOT NULL,
            total_equity   REAL    NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
        """
    )
    # A batch = one strategy run independently across many tickers.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS batches (
            batch_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at       TEXT    NOT NULL,
            buy_algorithm    TEXT    NOT NULL,
            sell_algorithm   TEXT    NOT NULL,
            interval         TEXT    NOT NULL,
            start_date       TEXT    NOT NULL,
            end_date         TEXT    NOT NULL,
            starting_capital REAL    NOT NULL,
            ticker_count     INTEGER NOT NULL
        )
        """
    )
    # One row per ticker in a batch (success or failure), with its headline KPIs.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS batch_results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id      INTEGER NOT NULL,
            ticker        TEXT    NOT NULL,
            run_id        INTEGER,
            status        TEXT    NOT NULL CHECK (status IN ('ok', 'error')),
            total_return  REAL,
            num_trades    INTEGER,
            win_rate      REAL,
            final_equity  REAL,
            error_message TEXT,
            FOREIGN KEY (batch_id) REFERENCES batches (batch_id),
            FOREIGN KEY (run_id) REFERENCES runs (run_id)
        )
        """
    )
    conn.commit()


def create_run(conn, ticker, buy_algorithm, sell_algorithm, starting_capital, start_date, end_date):
    """Insert a run row and return its generated run_id."""
    created_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO runs
            (ticker, buy_algorithm, sell_algorithm, starting_capital, start_date, end_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (ticker, buy_algorithm, sell_algorithm, starting_capital, start_date, end_date, created_at),
    )
    conn.commit()
    return cursor.lastrowid


def record_trade(conn, run_id, ticker, trade_type, date, price, shares, algorithm_name):
    """Append one BUY/SELL to the ledger. Validates trade_type explicitly (fail fast)."""
    if trade_type not in VALID_TRADE_TYPES:
        raise InvalidTradeTypeError(
            f"trade_type must be one of {VALID_TRADE_TYPES}, got {trade_type!r}"
        )
    conn.execute(
        """
        INSERT INTO trades (run_id, ticker, trade_type, date, price, shares, algorithm_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, ticker, trade_type, date, price, shares, algorithm_name),
    )


def record_equity(conn, run_id, date, cash, position_value, total_equity):
    """Append one day's mark-to-market portfolio value."""
    conn.execute(
        """
        INSERT INTO daily_equity (run_id, date, cash, position_value, total_equity)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, date, cash, position_value, total_equity),
    )


def get_run(conn, run_id):
    """Return the single run row (sqlite3.Row) for `run_id`, or raise if absent."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"No run found with run_id={run_id}")
    return row


def get_trades(conn, run_id):
    """Return the trade ledger for a run as a DataFrame, ordered chronologically."""
    return pd.read_sql_query(
        "SELECT * FROM trades WHERE run_id = ? ORDER BY date, id", conn, params=(run_id,)
    )


def get_equity_curve(conn, run_id):
    """Return the daily equity curve for a run as a DataFrame, ordered chronologically."""
    return pd.read_sql_query(
        "SELECT * FROM daily_equity WHERE run_id = ? ORDER BY date, id", conn, params=(run_id,)
    )


def list_runs(conn):
    """Return all runs as a DataFrame, newest first."""
    return pd.read_sql_query(
        "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC", conn
    )


def create_batch(conn, buy_algorithm, sell_algorithm, interval, start_date, end_date,
                 starting_capital, ticker_count):
    """Insert a batch row and return its generated batch_id."""
    created_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO batches
            (created_at, buy_algorithm, sell_algorithm, interval, start_date, end_date,
             starting_capital, ticker_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (created_at, buy_algorithm, sell_algorithm, interval, start_date, end_date,
         starting_capital, ticker_count),
    )
    conn.commit()
    return cursor.lastrowid


def record_batch_result(conn, batch_id, ticker, run_id, status, total_return, num_trades,
                        win_rate, final_equity, error_message):
    """Append one ticker's outcome (ok or error) within a batch."""
    if status not in ("ok", "error"):
        raise ValueError(f"status must be 'ok' or 'error', got {status!r}")
    conn.execute(
        """
        INSERT INTO batch_results
            (batch_id, ticker, run_id, status, total_return, num_trades, win_rate,
             final_equity, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (batch_id, ticker, run_id, status, total_return, num_trades, win_rate,
         final_equity, error_message),
    )
    conn.commit()


def get_batch(conn, batch_id):
    """Return the single batch row (sqlite3.Row) for `batch_id`, or raise if absent."""
    row = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if row is None:
        raise ValueError(f"No batch found with batch_id={batch_id}")
    return row


def get_batch_results(conn, batch_id):
    """Return all per-ticker results for a batch as a DataFrame, ticker order."""
    return pd.read_sql_query(
        "SELECT * FROM batch_results WHERE batch_id = ? ORDER BY ticker", conn, params=(batch_id,)
    )


def list_batches(conn):
    """Return all batches as a DataFrame, newest first."""
    return pd.read_sql_query(
        "SELECT * FROM batches ORDER BY created_at DESC, batch_id DESC", conn
    )
