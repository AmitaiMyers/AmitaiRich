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
# Out-of-sample window extended to the present so recent base-breakouts (e.g. DELL's
# 2026 move above its multi-year roof) fall inside the scanner's test range.
OOS = ("2019-01-01", "2026-06-20")

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

# Another ~50 liquid large/mid caps (all listed before 2014 so train data is clean).
UNIVERSE_EXTRA = [
    "QCOM", "TXN", "AMD", "INTC", "IBM", "ACN", "INTU", "AMAT", "MU", "ADI",
    "T", "TMUS", "CMCSA", "CHTR", "LOW", "TJX", "BKNG", "GM", "MAR", "ORLY",
    "MDLZ", "CL", "MO", "PM", "GIS", "ABT", "DHR", "BMY", "AMGN", "GILD",
    "CVS", "ISRG", "MDT", "VRTX", "REGN", "MS", "C", "WFC", "SCHW", "BLK",
    "SPGI", "RTX", "DE", "MMM", "GD", "EMR", "CSX", "NSC", "SLB", "EOG",
    # DELL: re-listed Dec 2018 (skipped on TRAIN for lack of history) — the owner's
    # worked example of a multi-year roof broken in 2026.
    "DELL",
]

# Full ~100-name universe used by the production-model research.
UNIVERSE = UNIVERSE_50 + UNIVERSE_EXTRA

# A fast subset for grid screening (broad sector coverage in ~40 names). Finalists
# are then re-validated on the full universe out-of-sample.
SCREEN_UNIVERSE = UNIVERSE_50[:40]


def run_config(strategy_name, config, period, sizing_mode="all_in", stop_mode="tightest",
               sell_name=None, leverage=1.0, db_path=RESEARCH_DB, universe=None):
    """Run one strategy config across a universe for a period; return batch_id."""
    buy = build_algorithm(strategy_name, config)
    sell = build_algorithm(sell_name or strategy_name, config)
    start, end = period
    return run_batch(
        universe if universe is not None else UNIVERSE,
        start, end, START_CAPITAL, buy, sell,
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


def evaluate(strategies, period, db_path, periods_per_year=252):
    """Run per-stock daily strategies and return portfolio-level metrics, ranked by Sharpe.

    `strategies` is a list of (label, algorithm_name, config). Each is run across the
    universe with the production daily-scan engine; the equal-weight portfolio curve
    is scored on total return / CAGR / max drawdown / Sharpe / Calmar.
    """
    rows = []
    for label, name, cfg in strategies:
        batch_id = run_config(name, cfg, period, db_path=db_path)
        metrics = portfolio_metrics(portfolio_equity(batch_id, db_path), periods_per_year)
        metrics["strategy"] = label
        rows.append(metrics)
        print(f"  done: {label:38s} ret={metrics['total_return']*100:7.1f}%  "
              f"dd={metrics['max_dd']*100:6.1f}%  sharpe={metrics['sharpe']:.2f}  calmar={metrics['calmar']:.2f}")
    df = pd.DataFrame(rows)[["strategy", "total_return", "cagr", "max_dd", "sharpe", "calmar"]]
    return df.sort_values("sharpe", ascending=False)


# ---------------------------------------------------------------------------
# Scanner evaluation
#
# A breakout scanner is a stock-PICKER, not an equal-weight basket: it flags a few
# names to buy and you hold each while it works. The right unit of analysis is the
# individual signal (a round-trip trade), pooled across every stock and date. These
# functions answer: when the scanner says BUY, what happens?
# ---------------------------------------------------------------------------

def scanner_trades(batch_id, db_path=RESEARCH_DB):
    """Every round-trip trade across all stocks in a batch, with per-trade return.

    Only one position is open per stock at a time, so BUY/SELL rows strictly
    alternate; we pair them in order. Return = sell_price / buy_price - 1.
    """
    conn = database.get_connection(db_path)
    results = database.get_batch_results(conn, batch_id)
    ok = results[results["status"] == "ok"]
    rows = []
    for _, result in ok.iterrows():
        run_id = result["run_id"]
        if pd.isna(run_id):
            continue
        trades = database.get_trades(conn, int(run_id))
        buys = trades[trades["trade_type"] == "BUY"].reset_index(drop=True)
        sells = trades[trades["trade_type"] == "SELL"].reset_index(drop=True)
        for k in range(min(len(buys), len(sells))):
            entry_price = float(buys.loc[k, "price"])
            exit_price = float(sells.loc[k, "price"])
            rows.append({
                "ticker": result["ticker"],
                "entry_date": buys.loc[k, "date"],
                "exit_date": sells.loc[k, "date"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "ret": exit_price / entry_price - 1.0,
            })
    conn.close()
    return pd.DataFrame(rows)


def scanner_stats(batch_id, db_path=RESEARCH_DB):
    """Pooled per-signal statistics for a batch — how good are the scanner's picks?

    Key fields:
      n_signals     : how many BUY signals fired (across all stocks)
      win_rate      : share of signals that closed profitable
      avg_ret       : mean per-trade return = expectancy per signal
      total_edge    : sum of per-trade returns (aggregate edge if you took every
                      signal with equal stake; ignores capital/overlap constraints)
      pct_gt_50/100 : share of signals that gained >50% / >100% (big-mover capture)
      max_ret       : best single signal (did it catch a DELL-type move?)
    """
    trades = scanner_trades(batch_id, db_path)
    if trades.empty:
        return {"n_signals": 0, "win_rate": 0.0, "avg_ret": 0.0, "median_ret": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "total_edge": 0.0,
                "pct_gt_50": 0.0, "pct_gt_100": 0.0, "max_ret": 0.0}
    ret = trades["ret"]
    wins = ret[ret > 0]
    losses = ret[ret <= 0]
    return {
        "n_signals": int(len(ret)),
        "win_rate": float((ret > 0).mean()),
        "avg_ret": float(ret.mean()),
        "median_ret": float(ret.median()),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "total_edge": float(ret.sum()),
        "pct_gt_50": float((ret > 0.5).mean()),
        "pct_gt_100": float((ret > 1.0).mean()),
        "max_ret": float(ret.max()),
    }


def evaluate_scanner(strategies, period, db_path=RESEARCH_DB, sort_key="total_edge", universe=None):
    """Run breakout-scanner configs and rank them by pooled per-signal profitability.

    `strategies` is a list of (label, algorithm_name, config). Ranked by `total_edge`
    (aggregate harvested return) by default — the closest single number to "most
    profitable across all the picks it made".
    """
    rows = []
    for label, name, cfg in strategies:
        batch_id = run_config(name, cfg, period, db_path=db_path, universe=universe)
        stats = scanner_stats(batch_id, db_path)
        stats["strategy"] = label
        rows.append(stats)
        print(f"  done: {label:32s} n={stats['n_signals']:4d} win={stats['win_rate']*100:3.0f}% "
              f"avg={stats['avg_ret']*100:5.1f}% edge={stats['total_edge']:6.1f} "
              f">50%={stats['pct_gt_50']*100:3.0f}% max={stats['max_ret']*100:5.0f}%")
    cols = ["strategy", "n_signals", "win_rate", "avg_ret", "median_ret",
            "total_edge", "pct_gt_50", "pct_gt_100", "max_ret"]
    return pd.DataFrame(rows)[cols].sort_values(sort_key, ascending=False)


def scanner_grid():
    """Phase A — grid each roof type x exit mode on TRAIN, ranked by aggregate edge."""
    configs = []
    for lookback in (126, 252, 504):
        for exit_mode in ("trailing", "structural", "target"):
            configs.append((f"High lb={lookback} {exit_mode}", "Roof: 52-Week-High Breakout",
                            {"roof_lookback": lookback, "exit_mode": exit_mode}))
    for bandwidth in (0.10, 0.15):
        for exit_mode in ("trailing", "structural", "target"):
            configs.append((f"Squeeze bw={bandwidth} {exit_mode}", "Roof: Volatility-Squeeze Breakout",
                            {"bandwidth_threshold": bandwidth, "exit_mode": exit_mode}))
    for lookback in (120, 250):
        for base in (20, 40):
            for exit_mode in ("trailing", "structural", "target"):
                configs.append((f"Pivot lb={lookback} base={base} {exit_mode}",
                                "Roof: Pivot-Resistance Breakout",
                                {"roof_lookback": lookback, "base_bars": base, "exit_mode": exit_mode}))
    print(f"=== SCANNER GRID on TRAIN {TRAIN}, {len(SCREEN_UNIVERSE)} screen stocks, "
          f"{len(configs)} configs ===", flush=True)
    df = evaluate_scanner(configs, TRAIN, universe=SCREEN_UNIVERSE)
    print("\n--- TRAIN ranked by aggregate edge ---")
    print(df.to_string(index=False))


def validate_oos(strategies, period=OOS, db_path="oos.db"):
    """Validate finalist scanner configs out-of-sample on the FULL universe.

    Reports two complementary views per strategy:
      - SCANNER quality: per-signal hit-rate, expectancy, big-mover capture.
      - SYSTEM performance: the equal-weight per-stock portfolio's return / CAGR /
        max drawdown / Sharpe (so it is comparable to Buy & Hold as a tradeable system).
    Returns a DataFrame; also prints a DELL trade log for each strategy as an
    illustration of whether it caught the owner's worked example.
    """
    rows = []
    for label, name, cfg in strategies:
        batch_id = run_config(name, cfg, period, db_path=db_path, universe=UNIVERSE)
        stats = scanner_stats(batch_id, db_path)
        port = portfolio_metrics(portfolio_equity(batch_id, db_path))
        rows.append({
            "strategy": label,
            "n_sig": stats["n_signals"], "win%": round(stats["win_rate"] * 100, 0),
            "avg%": round(stats["avg_ret"] * 100, 1), "edge": round(stats["total_edge"], 1),
            ">100%": round(stats["pct_gt_100"] * 100, 1), "max%": round(stats["max_ret"] * 100, 0),
            "port_ret%": round(port["total_return"] * 100, 0), "cagr%": round(port["cagr"] * 100, 1),
            "maxDD%": round(port["max_dd"] * 100, 1), "sharpe": round(port["sharpe"], 2),
        })
        dell = scanner_trades(batch_id, db_path)
        dell = dell[dell["ticker"] == "DELL"] if not dell.empty else dell
        print(f"  done: {label}", flush=True)
        if not dell.empty:
            for _, t in dell.iterrows():
                print(f"      DELL {t['entry_date'][:10]} @ {t['entry_price']:.0f} -> "
                      f"{t['exit_date'][:10]} @ {t['exit_price']:.0f}  {t['ret']*100:+.0f}%", flush=True)
    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    print("\n--- OOS VALIDATION (full universe) ---")
    print(df.to_string(index=False))
    return df


def load_price_matrix(period):
    """Daily close prices for the universe as a (dates x tickers) DataFrame."""
    start, end = period
    closes = {}
    for ticker in UNIVERSE:
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
    "scanner_grid": scanner_grid,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in DISPATCH:
        print("usage: python research.py", "|".join(DISPATCH))
        sys.exit(1)
    DISPATCH[sys.argv[1]]()
