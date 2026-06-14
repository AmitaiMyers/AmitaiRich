"""Research harness — find the best strategy across a 50-stock universe.

Methodology (per the project owner's choices):
- Objective: ROBUST PROFIT — high average per-stock return AND consistency
  (share of stocks profitable), and must beat Buy & Hold. Ranking metric:
  robust_score = portfolio_return * pct_profitable.
- Validation: TRAIN/TEST split. Tune on 2010-2018, then report the honest
  out-of-sample result on 2019-2025 (data the tuning never saw).
- Timeframe: daily candles. Universe: 50 diversified large caps.

"portfolio_return" = mean total_return across the 50 stocks, each traded
independently with the same starting capital (an equal-weight portfolio proxy).
Stocks the strategy never enters contribute 0% (cash), which is the honest
portfolio view. Sizing is all_in so returns reflect fully-deployed capital.

Run phases:  python research.py baseline | tune_trend | tune_sma | tune_bollinger | validate
"""

import sys

import pandas as pd

import analytics
import database
from algorithms import build_algorithm
from batch import run_batch
from data_engine import fetch_data
from errors import SimulatorError

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

RESEARCH_DB = "research.db"
START_CAPITAL = 10_000.0
TRAIN = ("2010-01-01", "2018-12-31")
TEST = ("2019-01-01", "2025-12-31")

# 50 diversified S&P large caps spanning all 11 GICS sectors.
UNIVERSE_50 = [
    # Information Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "CSCO",
    # Communication Services
    "GOOGL", "META", "NFLX", "DIS", "VZ",
    # Consumer Discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX",
    # Consumer Staples
    "PG", "KO", "PEP", "COST", "WMT",
    # Health Care
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO",
    # Financials
    "JPM", "BAC", "GS", "V", "MA", "AXP",
    # Energy
    "XOM", "CVX", "COP",
    # Industrials
    "BA", "CAT", "HON", "GE", "UPS", "LMT",
    # Materials / Utilities / Real Estate
    "LIN", "NEE", "DUK", "AMT",
]


def run_config(strategy_name, config, period, sizing_mode="all_in", stop_mode="tightest",
               sell_name=None, leverage=1.0, db_path=RESEARCH_DB):
    """Run one strategy config across the universe for a period; return batch_id."""
    buy = build_algorithm(strategy_name, config)
    sell = build_algorithm(sell_name or strategy_name, config)
    start, end = period
    return run_batch(
        UNIVERSE_50, start, end, START_CAPITAL, buy, sell,
        stop_mode=stop_mode, sizing_mode=sizing_mode, fill_mode="close",
        interval="1d", leverage=leverage, use_cache=True, db_path=db_path,
    )


def portfolio_equity(batch_id, db_path=RESEARCH_DB):
    """Reconstruct the equal-weight portfolio equity curve (sum of all per-stock runs).

    Each stock starts with the same capital; before a stock's run produces equity
    (warmup / late listing) its capital is idle cash (START_CAPITAL). Curves are
    aligned on the union of dates, forward-filled, and summed.
    """
    conn = database.get_connection(db_path)
    results = database.get_batch_results(conn, batch_id)
    ok = results[results["status"] == "ok"]
    series = []
    for run_id in ok["run_id"].dropna():
        equity = database.get_equity_curve(conn, int(run_id))
        if len(equity):
            s = equity.set_index(pd.to_datetime(equity["date"]))["total_equity"]
            series.append(s[~s.index.duplicated(keep="last")])
    conn.close()
    if not series:
        return pd.Series(dtype=float)
    frame = pd.concat(series, axis=1).sort_index().ffill().fillna(START_CAPITAL)
    return frame.sum(axis=1)


def portfolio_metrics(equity, periods_per_year=252):
    """Total return, CAGR, max drawdown, Sharpe, and Calmar of a portfolio curve."""
    if len(equity) < 2:
        return {"total_return": 0.0, "cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0, "calmar": 0.0}
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = analytics.cagr(equity, periods_per_year)
    max_dd = analytics.max_drawdown(equity)
    sharpe = analytics.sharpe(equity, periods_per_year)
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {"total_return": total_return, "cagr": cagr, "max_dd": max_dd,
            "sharpe": sharpe, "calmar": calmar}


def load_price_matrix(period):
    """Daily close prices for the universe as a (dates x tickers) DataFrame."""
    start, end = period
    closes = {}
    for ticker in UNIVERSE_50:
        try:
            closes[ticker] = fetch_data(ticker, start, end, interval="1d", use_cache=True)["Close"]
        except SimulatorError:
            continue
    return pd.DataFrame(closes).sort_index()


def momentum_rotation(period, lookback_months=6, top_k=10, market_filter=False):
    """Cross-sectional momentum: monthly, hold the top-K by trailing return.

    A TRUE shared-capital portfolio (unlike the per-stock batch): each month-end,
    rank the universe by `lookback_months` return and hold the top K equal-weight
    for the next month. With `market_filter`, a name is only held while its monthly
    close is above its 10-month (~200-day) average, else that sleeve sits in cash.
    Weights are shifted one month so only past data drives each month's return
    (no lookahead). Returns the growth-of-1 equity curve.
    """
    monthly = load_price_matrix(period).resample("ME").last()
    monthly_return = monthly.pct_change()
    momentum = monthly.pct_change(lookback_months)

    holdings = momentum.rank(axis=1, ascending=False) <= top_k
    if market_filter:
        holdings = holdings & (monthly > monthly.rolling(10).mean())
        weights = holdings.astype(float) / top_k          # cash if fewer than K qualify
    else:
        weights = holdings.astype(float).div(holdings.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0.0)

    portfolio_return = (monthly_return * weights.shift(1)).sum(axis=1).dropna()
    equity = (1.0 + portfolio_return).cumprod()
    base = pd.Series([1.0], index=[portfolio_return.index[0] - pd.Timedelta(days=1)])
    return pd.concat([base, equity])


def analyze(batch_id, db_path=RESEARCH_DB, periods_per_year=252):
    """Aggregate a batch into the robust-profit metric set."""
    conn = database.get_connection(db_path)
    results = database.get_batch_results(conn, batch_id)
    ok = results[results["status"] == "ok"].copy()

    drawdowns = []
    for run_id in ok["run_id"].dropna():
        equity = database.get_equity_curve(conn, int(run_id))
        if len(equity):
            drawdowns.append(analytics.max_drawdown(equity["total_equity"]))
    conn.close()

    traded = ok[ok["num_trades"] > 0]
    port_return = float(ok["total_return"].mean()) if len(ok) else 0.0
    pct_profitable = float((ok["total_return"] > 0).mean()) if len(ok) else 0.0
    return {
        "port_return": port_return,
        "median_return": float(ok["total_return"].median()) if len(ok) else 0.0,
        "pct_profitable": pct_profitable,
        "avg_win_rate": float(traded["win_rate"].mean()) if len(traded) else 0.0,
        "avg_trades": float(traded["num_trades"].mean()) if len(traded) else 0.0,
        "avg_max_dd": float(pd.Series(drawdowns).mean()) if drawdowns else 0.0,
        "n_traded": len(traded),
        "n_failed": int((results["status"] == "error").sum()),
        "robust_score": port_return * pct_profitable,
    }


def _print_table(rows, sort_key="robust_score"):
    df = pd.DataFrame(rows).sort_values(sort_key, ascending=False)
    for col in ["port_return", "median_return", "pct_profitable", "avg_win_rate", "avg_max_dd", "robust_score"]:
        if col in df:
            df[col] = (df[col] * 100).round(1)
    print(df.to_string(index=False))
    return df


def baseline():
    """Default-param run of every candidate strategy on TRAIN."""
    candidates = [
        ("Buy & Hold (benchmark)", {}),
        ("SMA Crossover", {}),
        ("Trend Follower (Donchian)", {}),
        ("Bollinger Squeeze + Volume Breakout", {}),
        ("Bollinger Bounce (mean reversion)", {}),
    ]
    rows = []
    for name, cfg in candidates:
        bid = run_config(name, cfg, TRAIN)
        m = analyze(bid)
        m["strategy"] = name
        rows.append(m)
        print(f"  done: {name}  port_return={m['port_return']*100:.1f}%  robust={m['robust_score']*100:.1f}")
    print("\n=== BASELINE on TRAIN (2010-2018), sizing=all_in ===")
    _print_table(rows)


def tune_trend():
    """Grid search the Donchian Trend Follower on TRAIN."""
    rows = []
    for entry in (20, 50, 100):
        for ex in (10, 20, 50):
            if ex >= entry:
                continue
            for filt in (0, 1):
                cfg = {"entry_lookback": entry, "exit_lookback": ex, "use_trend_filter": filt}
                bid = run_config("Trend Follower (Donchian)", cfg, TRAIN)
                m = analyze(bid)
                m["cfg"] = f"entry={entry} exit={ex} filt={filt}"
                rows.append(m)
                print(f"  {m['cfg']}: port={m['port_return']*100:.1f}% prof={m['pct_profitable']*100:.0f}% robust={m['robust_score']*100:.1f}")
    print("\n=== TREND FOLLOWER tuning on TRAIN ===")
    _print_table(rows)


def tune_sma():
    """Grid search SMA Crossover on TRAIN (fast=1 => price vs slow SMA)."""
    rows = []
    for fast in (1, 10, 20, 50):
        for slow in (50, 100, 150, 200):
            if fast >= slow:
                continue
            cfg = {"fast_period": fast, "slow_period": slow}
            bid = run_config("SMA Crossover", cfg, TRAIN)
            m = analyze(bid)
            m["cfg"] = f"fast={fast} slow={slow}"
            rows.append(m)
            print(f"  {m['cfg']}: port={m['port_return']*100:.1f}% prof={m['pct_profitable']*100:.0f}% robust={m['robust_score']*100:.1f}")
    print("\n=== SMA CROSSOVER tuning on TRAIN ===")
    _print_table(rows)


def tune_bollinger():
    """Grid search the Bollinger squeeze breakout on TRAIN (relax selectivity)."""
    rows = []
    for bw in (0.10, 0.15, 0.25):
        for sq in (3, 5):
            for vm in (1.2, 1.5):
                cfg = {"bandwidth_threshold": bw, "min_squeeze_candles": sq, "vol_breakout_mult": vm}
                bid = run_config("Bollinger Squeeze + Volume Breakout", cfg, TRAIN)
                m = analyze(bid)
                m["cfg"] = f"bw={bw} sq={sq} vm={vm}"
                rows.append(m)
                print(f"  {m['cfg']}: port={m['port_return']*100:.1f}% prof={m['pct_profitable']*100:.0f}% trades={m['avg_trades']:.1f} robust={m['robust_score']*100:.1f}")
    print("\n=== BOLLINGER tuning on TRAIN ===")
    _print_table(rows)


DISPATCH = {
    "baseline": baseline,
    "tune_trend": tune_trend,
    "tune_sma": tune_sma,
    "tune_bollinger": tune_bollinger,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in DISPATCH:
        print("usage: python research.py", "|".join(DISPATCH))
        sys.exit(1)
    DISPATCH[sys.argv[1]]()
