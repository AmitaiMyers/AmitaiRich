"""Batch runner — evaluate one strategy across many tickers and summarize.

Each ticker is simulated INDEPENDENTLY with the same starting capital and the same
strategy config (via simulation.run_simulation), so per-stock percentage returns
are directly comparable. This is an algorithm-evaluation tool (a scan across a
universe), not a shared-capital portfolio backtest.

Fail-fast note: a per-ticker data problem (no data for the range, too few bars,
NaNs) is an EXPECTED outcome when scanning a universe, not a logic bug. Those are
captured per ticker with status='error' and shown in the summary instead of
aborting the whole scan. The try/except below sits only at this orchestration
boundary and catches a specific, known set of per-ticker data errors — a
ConfigurationError (a whole-batch setup mistake) is deliberately NOT caught, so it
still aborts loudly. The core simulation and algorithms keep their fail-fast rules.
"""

import database
from simulation import run_simulation, compute_kpis
from errors import (
    ConfigurationError,
    EmptyDataError,
    MissingColumnError,
    DataIntegrityError,
    InsufficientDataError,
    InsufficientCashError,
)

# Known, recoverable per-ticker failures during a scan (recorded, not fatal).
PER_TICKER_ERRORS = (
    EmptyDataError,
    MissingColumnError,
    DataIntegrityError,
    InsufficientDataError,
    InsufficientCashError,
)


def run_batch(
    tickers,
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
    """Run the strategy on each ticker, persist a batch, and return its batch_id.

    `buy_algo` / `sell_algo` are reused across tickers — algorithms hold only
    config, no per-ticker state, so this is safe and avoids rebuilding them.
    """
    clean_tickers = _normalize_tickers(tickers)
    if not clean_tickers:
        raise ConfigurationError("No tickers provided for the batch scan.")

    conn = database.get_connection(db_path)
    database.init_db(conn)
    batch_id = database.create_batch(
        conn, buy_algo.name, sell_algo.name, interval,
        str(start_date), str(end_date), starting_capital, len(clean_tickers),
    )

    for ticker in clean_tickers:
        try:
            run_id = run_simulation(
                ticker, start_date, end_date, starting_capital, buy_algo, sell_algo,
                stop_mode=stop_mode, sizing_mode=sizing_mode, risk_pct=risk_pct,
                fixed_fraction=fixed_fraction, fill_mode=fill_mode, interval=interval,
                leverage=leverage, use_cache=use_cache, db_path=db_path,
            )
        except PER_TICKER_ERRORS as exc:
            database.record_batch_result(
                conn, batch_id, ticker, None, "error", None, None, None, None, str(exc)
            )
            continue

        kpis = compute_kpis(conn, run_id)
        database.record_batch_result(
            conn, batch_id, ticker, run_id, "ok",
            kpis["total_return"], kpis["num_trades"], kpis["win_rate"],
            kpis["final_equity"], None,
        )

    conn.close()
    return batch_id


def compute_batch_summary(conn, batch_id):
    """Aggregate a batch's per-ticker results into headline statistics.

    Return-based stats are computed over tickers that actually TRADED (a stock the
    strategy never entered has a 0% return that would otherwise dilute the edge).
    Counts of no-trade and failed tickers are reported separately.
    """
    results = database.get_batch_results(conn, batch_id)
    ok = results[results["status"] == "ok"]
    failed = results[results["status"] == "error"]
    traded = ok[ok["num_trades"] > 0]

    summary = {
        "n_total": len(results),
        "n_ok": len(ok),
        "n_failed": len(failed),
        "n_no_trades": len(ok) - len(traded),
        "n_traded": len(traded),
    }

    if len(traded):
        summary.update({
            "avg_return": float(traded["total_return"].mean()),
            "median_return": float(traded["total_return"].median()),
            "pct_profitable": float((traded["total_return"] > 0).mean()),
            "avg_win_rate": float(traded["win_rate"].mean()),
            "total_trades": int(traded["num_trades"].sum()),
            "avg_trades": float(traded["num_trades"].mean()),
            "best_ticker": str(traded.loc[traded["total_return"].idxmax(), "ticker"]),
            "best_return": float(traded["total_return"].max()),
            "worst_ticker": str(traded.loc[traded["total_return"].idxmin(), "ticker"]),
            "worst_return": float(traded["total_return"].min()),
        })
    else:
        summary.update({
            "avg_return": 0.0, "median_return": 0.0, "pct_profitable": 0.0,
            "avg_win_rate": 0.0, "total_trades": 0, "avg_trades": 0.0,
            "best_ticker": None, "best_return": 0.0,
            "worst_ticker": None, "worst_return": 0.0,
        })
    return summary


def _normalize_tickers(tickers):
    """Upper-case, strip, and de-duplicate a list of ticker symbols (order preserved)."""
    cleaned = []
    for raw in tickers:
        symbol = raw.strip().upper()
        if symbol and symbol not in cleaned:
            cleaned.append(symbol)
    return cleaned
