"""Forward paper trading: v0 (production), v0m (v0 + run-up cap) and v7 (earnings-led), on NEW data only.

    python paper_trading.py      # -> reports/paper/paper.md, research_results/paper.json

Both strategies start with $32,000 on PAPER_START with their rules frozen as committed. Every
run replays the identical engine from that date on the data available today. The rules are
causal, so this equals live paper trading — nothing after PAPER_START was ever used to choose
or tune them, which makes this the only truly out-of-sample test left (the 2023-2026 holdout
has been opened three times).

Reported each day: account value vs SPY and RSP from the same start, open positions, and the
orders decided at the last close for the next open (the list the owner would act on).
"""

import json
import os
from dataclasses import replace

import pandas as pd

import indicators
import magic_formula
import scan_today
import signal_log
import strategy_lab as L
from algo_versions import VERSIONS
from engine import run_engine
from errors import EmptyDataError
from portfolio import _AdjustedBuy, equity_metrics, longest_losing_streak, single_asset_benchmark

PAPER_START = pd.Timestamp("2026-11-10")
STRATEGIES = ("v0", "v0m", "v7")
OUT_DIR = os.path.join("reports", "paper")


def run_account(version, data):
    """One paper account: the engine from PAPER_START, positions and orders kept open."""
    strategy = _AdjustedBuy(L.build_strategy(version, data), None, PAPER_START)
    config = replace(L.portfolio_config(version).engine_config(), liquidate_at_end=False)
    frames = {t: f for t, f in data.stock_frames.items() if len(f) > 2 and f.index[-1] >= PAPER_START}
    result = run_engine(frames, strategy, strategy, config)
    return result, result.equity[result.equity.index >= PAPER_START]


def _pct(x):
    return f"{x * 100:+.2f}%"


def account_summary(name, equity, trades):
    if len(equity) < 2:
        return {"strategy": name, "days": len(equity), "value": round(float(equity.iloc[-1]), 0) if len(equity) else L.CAPITAL,
                "return": 0.0, "maxDD": 0.0, "trades": len(trades)}
    m = equity_metrics(equity)
    return {"strategy": name, "days": len(equity), "value": round(m["final_equity"], 0),
            "return": round(m["total_return"] * 100, 2), "maxDD": round(m["max_dd"] * 100, 1),
            "trades": len(trades)}


def run():
    data = L.lab_data("core")
    last_date = data.panel.dates[-1]
    rows, accounts = [], {}
    if last_date < PAPER_START:
        status = f"Paper trading starts {PAPER_START.date()}; latest data is {last_date.date()}."
    else:
        for name in STRATEGIES:
            result, equity = run_account(VERSIONS[name], data)
            live_trades = [t for t in result.trades if t.entry_date >= PAPER_START]
            accounts[name] = {"result": result, "trades": live_trades}
            rows.append(account_summary(name, equity, live_trades))
        for bench, close in data.benchmarks.items():
            if close.index[-1] < last_date:
                raise EmptyDataError(f"Benchmark {bench} ends {close.index[-1].date()} but the stock data reaches "
                                     f"{last_date.date()} — its price refresh failed; rerun market_data.py update.")
            curve = single_asset_benchmark(close[close.index >= PAPER_START], L.portfolio_config(VERSIONS["v7"]))
            rows.append(account_summary(f"BENCH {bench}", curve, []))
        status = f"Day {rows[0]['days']} of paper trading (data to {last_date.date()})."
    write(status, rows, accounts, last_date)
    v0_rows, v0_reason = v0_list()
    v7_rows, v7_reason = v7_list(data)
    scan_tickers, _sources = scan_today.combined_universe()
    signal_log.record(last_date, v0_rows, v7_rows, rows, accounts, status, {"v0": v0_reason, "v7": v7_reason},
                      magic_formula.daily_section(scan_tickers))


# ---------------------------------------------------------------------------
# The two daily lists (what the app shows and the signal log keeps)
# ---------------------------------------------------------------------------

V7_FACTORS = ("beat_streak", "sue", "rev_accel", "eps_surprise")


def v0_list():
    """Production v0 scan, exactly as scan_today / the PWA run it -> (full ranked list, why-dropped fn)."""
    import market_data
    import scan_today

    tickers, sources = scan_today.combined_universe()
    frames = market_data.load_prices(tickers)
    algorithm = scan_today.production_algorithm()
    report, _state = scan_today.daily_report(algorithm, {}, "log", frames=frames,
                                             top_n=1000, scan_universe=(tickers, sources))
    rows = [{"rank": c["rank"], "ticker": c["ticker"], "close": c["close"], "score": c["score"],
             "mom_pct": c["mom_%"], "vs_ma200_pct": c["pct_vs_200ma"]} for c in report["candidates"]]
    return rows, v0_drop_reason(frames, algorithm.config)


def v0_drop_reason(frames, config):
    """Why a name is no longer on the v0 list: the rule it now fails, with today's numbers."""
    trend, lookback, threshold = config["trend_ma"], config["mom_lookback"], config["mom_threshold"]

    def reason(ticker):
        if ticker not in frames:
            return "left the scanned universe (no price data)"
        close = frames[ticker]["Close"]
        last = float(close.iloc[-1])
        average = float(indicators.sma(close, trend).iloc[-1])
        momentum = float(indicators.roc(close, lookback).iloc[-1])
        if last < average:
            return f"SELL signal: closed {(last / average - 1) * 100:+.1f}% below its {trend}-day MA"
        if momentum <= threshold:
            return f"6-month momentum fell to {momentum * 100:+.0f}% (needs > {threshold * 100:.0f}%)"
        return "skipped by the scan (stale or missing data)"

    return reason


def v7_list(data):
    """v7's current top-10 list (set at the last weekly rebalance) -> (rows with factors, why-dropped fn)."""
    strategy = L.RankedStrategy(VERSIONS["v7"], data)
    today = data.panel.dates[-1]
    listed = strategy.on_list.loc[today]
    tickers = list(listed[listed].index)
    rows = []
    for ticker in tickers:
        row = {"ticker": ticker, "close": round(float(data.panel.close.at[today, ticker]), 2),
               "score": round(float(strategy.composite.at[today, ticker]), 4),
               "buyable_today": bool(strategy.entry.at[today, ticker])}
        for factor in V7_FACTORS:
            value = float(data.factor(factor).at[today, ticker])
            row[factor] = None if value != value else round(value, 3)
        rows.append(row)
    rows.sort(key=lambda r: -r["score"])
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows, v7_drop_reason(strategy, today)


def v7_drop_reason(strategy, today):
    """Why a name is no longer on the v7 top-10: it fails a buy filter, or its rank at the last rebalance."""
    rebalance_day = strategy.rank.loc[:today].dropna(how="all").index[-1]
    ranks = strategy.rank.loc[rebalance_day]
    top = VERSIONS["v7"].max_positions

    def reason(ticker):
        if ticker not in ranks.index:
            return "no longer in the data (left the S&P 500 history)"
        if not bool(strategy.candidates.at[today, ticker]):
            return "fails a buy filter today (not eligible, below its 200-day MA, or missed last quarter)"
        if ranks[ticker] != ranks[ticker]:
            return f"failed a buy filter at the {rebalance_day.date()} rebalance"
        return f"ranked {int(ranks[ticker])} at the {rebalance_day.date()} rebalance (list = top {top})"

    return reason




def write(status, rows, accounts, last_date):
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = ["# Paper trading — v0, v0m, v7 (forward, out-of-sample)", "",
             f"Start {PAPER_START.date()} with ${L.CAPITAL:,.0f} each; rules frozen; next-open fills; "
             f"{L.COST_BPS:.0f} bps/side. {status}", ""]
    tables = []
    if rows:
        lines += ["| Account | Days | Value | Return | Max DD | Trades |", "|---|---|---|---|---|---|"]
        lines += [f"| {r['strategy']} | {r['days']} | ${r['value']:,.0f} | {r['return']:+.2f}% | {r['maxDD']}% | {r['trades']} |"
                  for r in rows]
        tables.append({"title": f"Paper accounts since {PAPER_START.date()} (data to {last_date.date()})", "note": None,
                       "columns": ["strategy", "days", "value", "return", "maxDD", "trades"], "rows": rows})
    for name, account in accounts.items():
        result = account["result"]
        held = [{"strategy": p["ticker"], "entry": str(p["entry_date"].date()), "shares": int(p["shares"]),
                 "entry_price": round(p["entry_price"], 2), "last": round(p["last_close"], 2),
                 "pnl_pct": round((p["last_close"] / p["entry_price"] - 1) * 100, 1)}
                for p in result.open_positions]
        orders = [f"{o['side']} {o['ticker']}" for o in result.pending_orders]
        lines += ["", f"## {name} — {VERSIONS[name].description}", "",
                  f"**Orders for the next open:** {', '.join(orders) if orders else 'none'}", "",
                  "| Holding | Entry | Shares | Entry price | Last | P&L |", "|---|---|---|---|---|---|"]
        lines += [f"| {h['strategy']} | {h['entry']} | {h['shares']} | {h['entry_price']} | {h['last']} | {h['pnl_pct']:+.1f}% |"
                  for h in held] or ["| (no holdings) | | | | | |"]
        lines.append(f"\nClosed trades: {len(account['trades'])}, longest losing streak "
                     f"{longest_losing_streak(account['trades'])}.")
        tables.append({"title": f"{name} holdings — next-open orders: {', '.join(orders) if orders else 'none'}",
                       "note": VERSIONS[name].description,
                       "columns": ["strategy", "entry", "shares", "entry_price", "last", "pnl_pct"], "rows": held})
    with open(os.path.join(OUT_DIR, "paper.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    import research_portfolio

    research_portfolio.write_report("paper", tables, verdict={
        "winner": "-", "promoted": [],
        "summary": f"Forward paper trading of v0, v0m and v7 from {PAPER_START.date()}. {status} Judge after "
                   "at least 6-12 months; short windows are mostly noise."})
    print(f"Written {os.path.join(OUT_DIR, 'paper.md')}")


if __name__ == "__main__":
    run()
