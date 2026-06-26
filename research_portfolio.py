"""Portfolio research harness — find the best BUY+SELL strategy as a realistic system.

Unlike research.py (which scores each stock independently), this evaluates every
strategy as ONE shared-capital account (see portfolio.py): finite capital, max
concurrent positions, risk-based sizing on live equity, transaction costs,
long-only, optional market-regime filter. The benchmark to beat is equal-weight
Buy & Hold of the same universe.

Validation design (per the owner): a STOCK split, not a time split. 300 training
stocks are used to choose strategies/parameters; the chosen finalists are then
reported out-of-sample on 100 DIFFERENT, never-tuned stocks — over each stock's
full available history (2004-2026).

Heavy step = generating each stock's round-trip trades for a strategy config. That
is done once per (strategy, config, stop_mode, universe), parallelised across
processes and cached to disk; the portfolio overlay (sweeping max_positions /
risk / market filter / ranking) is then near-instant on the cached trades.

Phases:
  python research_portfolio.py split        # build + show the 300/100 split
  python research_portfolio.py smoke         # tiny end-to-end sanity run
  python research_portfolio.py train         # full grid on the 300 train stocks
  python research_portfolio.py validate      # finalists out-of-sample on 100 test stocks
"""

import hashlib
import json
import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

import analytics
from algorithms import build_algorithm
from data_engine import fetch_data
from errors import SimulatorError
from portfolio import (PortfolioConfig, simulate_ticker_trades, run_portfolio,
                       buy_and_hold_portfolio)

# Canonical data range — MUST match the bulk fetch (cache-key stability).
FETCH_START, FETCH_END = "2004-01-01", "2026-06-27"
INTERVAL = "1d"
MARKET_TICKER = "SPY"

SEED = 20260626
N_TRAIN, N_TEST = 300, 100
MIN_BARS = 1500           # ~6y minimum history to be eligible for selection
N_WORKERS = 10

SCRATCH = r"C:\Users\AMITAI~1\AppData\Local\Temp\claude\C--axioma-code-ntp\202db557-a354-4c66-8cac-c70edaf325e2\scratchpad"
SPLIT_JSON = os.path.join(SCRATCH, "train_test_split.json")
TRADE_CACHE = os.path.join(SCRATCH, "trade_cache")
RESULTS_DIR = os.path.join(SCRATCH, "results")
UNIVERSE_DIR = r"C:\axioma\code\ntp\universe_cache"
LISTS = ["sp500.csv", "nasdaq100.csv", "watchlist.csv", "magic_formula.csv"]

os.makedirs(TRADE_CACHE, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Universe assembly + 300/100 split
# ---------------------------------------------------------------------------

def _read_symbol_list(path):
    df = pd.read_csv(path)
    if "symbol" in df.columns:
        return df["symbol"].astype(str).tolist()
    return pd.read_csv(path, header=None).iloc[:, 0].astype(str).tolist()


def _all_symbols():
    seen, out = set(), []
    for name in LISTS:
        path = os.path.join(UNIVERSE_DIR, name)
        if not os.path.exists(path):
            continue
        for raw in _read_symbol_list(path):
            sym = raw.strip().upper().replace(".", "-")
            if sym and sym != "NAN" and sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def _bar_count(ticker):
    """Cached-history bar count for a ticker; 0 if unavailable."""
    try:
        return len(fetch_data(ticker, FETCH_START, FETCH_END, interval=INTERVAL, use_cache=True))
    except SimulatorError:
        return 0


def build_split(force=False):
    """Build (and cache) a seeded, disjoint 300-train / 100-test split.

    Eligible = at least MIN_BARS of cached history. Shuffled with a fixed seed so
    the split is reproducible; train and test never overlap.
    """
    if os.path.exists(SPLIT_JSON) and not force:
        with open(SPLIT_JSON) as fh:
            data = json.load(fh)
        return data["train"], data["test"]

    import random
    symbols = _all_symbols()
    eligible = [s for s in symbols if _bar_count(s) >= MIN_BARS]
    rng = random.Random(SEED)
    rng.shuffle(eligible)
    if len(eligible) < N_TRAIN + N_TEST:
        raise SimulatorError(f"Only {len(eligible)} eligible symbols; need {N_TRAIN + N_TEST}.")
    train = sorted(eligible[:N_TRAIN])
    test = sorted(eligible[N_TRAIN:N_TRAIN + N_TEST])
    with open(SPLIT_JSON, "w") as fh:
        json.dump({"seed": SEED, "min_bars": MIN_BARS, "n_eligible": len(eligible),
                   "train": train, "test": test}, fh, indent=2)
    return train, test


# ---------------------------------------------------------------------------
# Data loading + parallel, cached trade generation
# ---------------------------------------------------------------------------

def load_closes(tickers):
    """ticker -> daily close Series (for mark-to-market + Buy&Hold)."""
    closes = {}
    for ticker in tickers:
        try:
            closes[ticker] = fetch_data(ticker, FETCH_START, FETCH_END,
                                        interval=INTERVAL, use_cache=True)["Close"]
        except SimulatorError:
            continue
    return closes


def load_market_close():
    return fetch_data(MARKET_TICKER, FETCH_START, FETCH_END, interval=INTERVAL, use_cache=True)["Close"]


def _config_key(strategy, config, stop_mode, universe_tag):
    blob = json.dumps({"s": strategy, "c": config, "m": stop_mode, "u": universe_tag},
                      sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()[:16]


def _gen_one(args):
    """Worker: generate one ticker's round-trip trades for a strategy config."""
    ticker, strategy, config, stop_mode = args
    try:
        df = fetch_data(ticker, FETCH_START, FETCH_END, interval=INTERVAL, use_cache=True)
    except SimulatorError:
        return ticker, []
    buy = build_algorithm(strategy, config)
    sell = build_algorithm(strategy, config)
    return ticker, simulate_ticker_trades(ticker, df, buy, sell, stop_mode)


def gen_trades(strategy, config, tickers, stop_mode, universe_tag, n_workers=N_WORKERS):
    """All tickers' trades for one config (disk-cached, parallelised)."""
    key = _config_key(strategy, config, stop_mode, universe_tag)
    cache_path = os.path.join(TRADE_CACHE, f"{key}.pkl")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            return pickle.load(fh)

    work = [(t, strategy, config, stop_mode) for t in tickers]
    trades_by_ticker = {}
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for ticker, trades in pool.map(_gen_one, work, chunksize=4):
            trades_by_ticker[ticker] = trades
    with open(cache_path, "wb") as fh:
        pickle.dump(trades_by_ticker, fh)
    return trades_by_ticker


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def benchmark_metrics(closes, pcfg, periods_per_year=252):
    """Equal-weight Buy & Hold metrics over the universe (the bar to beat)."""
    equity = buy_and_hold_portfolio(closes, pcfg)
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        "cagr": analytics.cagr(equity), "max_dd": analytics.max_drawdown(equity),
        "sharpe": analytics.sharpe(equity),
        "calmar": float(analytics.cagr(equity) / abs(analytics.max_drawdown(equity)))
        if analytics.max_drawdown(equity) < 0 else 0.0,
    }


def eval_config(label, strategy, config, tickers, closes, market_close, pcfg,
                stop_mode, universe_tag, n_workers=N_WORKERS):
    """Run one strategy config through the portfolio; return a metrics row."""
    trades = gen_trades(strategy, config, tickers, stop_mode, universe_tag, n_workers)
    result = run_portfolio(trades, closes, pcfg, market_close=market_close)
    m = result.metrics
    return {
        "strategy": label, "algo": strategy, "stop": stop_mode,
        "cagr": round(m["cagr"] * 100, 1), "sharpe": round(m["sharpe"], 2),
        "maxDD": round(m["max_dd"] * 100, 1), "calmar": round(m["calmar"], 2),
        "totRet": round(m["total_return"] * 100, 0),
        "finalEq": round(m["final_equity"], 0),
        "nTaken": m["n_taken"], "nSig": m["n_signals"],
        "avgHoldDays": round(m["avg_hold_days"], 0), "winRate": round(m["win_rate"] * 100, 0),
        "config": config, "mkt": pcfg.market_filter, "maxPos": pcfg.max_positions,
    }


def _print_rows(rows, bench, sort_key="sharpe"):
    df = pd.DataFrame(rows).sort_values(sort_key, ascending=False)
    show = ["strategy", "stop", "maxPos", "mkt", "cagr", "sharpe", "maxDD", "calmar",
            "totRet", "nTaken", "avgHoldDays", "winRate", "finalEq"]
    print(df[show].to_string(index=False))
    print(f"\n  BENCHMARK Buy&Hold: cagr={bench['cagr']*100:.1f}% sharpe={bench['sharpe']:.2f} "
          f"maxDD={bench['max_dd']*100:.1f}% calmar={bench['calmar']:.2f}")
    return df


if __name__ == "__main__":
    import research_grids  # dispatch lives in a sibling so the grid is editable alone
    research_grids.main(sys.argv[1:] if len(sys.argv) > 1 else ["smoke"])
