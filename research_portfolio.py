"""Portfolio research harness — evaluate strategies as a realistic shared-capital system.

Every candidate is run as ONE account (portfolio.py): finite capital, max concurrent
positions, 1%-risk sizing on live equity, transaction costs, long-only, and
optionally next-day-open fills. Benchmarks: equal-weight Buy & Hold of the same
universe and SPY Buy & Hold.

Validation layers (all used by research_grids.py's `v3` phase):
  * STOCK split   — tune on 300 stocks, report on 100 never-tuned stocks;
  * MULTI-SPLIT   — re-draw the 300/100 split with other seeds to check the result
                    is not an artifact of one lucky draw;
  * WALK-FORWARD  — the same rules over disjoint time windows (regime stability).

Portable by design: paths are relative / env-configurable, data is bulk-downloaded
and cached, candidates run in parallel processes. Environment overrides:
  RESEARCH_END   last data date (default: today)      RESEARCH_OUT  scratch dir
  RESEARCH_WORKERS  process count (default: all CPUs)
"""

import json
import os
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

import universe
from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data, prefetch
from errors import ConfigurationError
from portfolio import (PortfolioConfig, buy_and_hold_portfolio, equity_metrics,
                       run_portfolio, single_asset_benchmark)

FETCH_START = "2004-01-01"
FETCH_END = os.environ.get("RESEARCH_END", date.today().isoformat())
INTERVAL = "1d"
MARKET_TICKER = "SPY"

SEED = 20260626
N_TRAIN, N_TEST = 300, 100
MIN_BARS = 1500           # ~6y minimum history to be eligible for selection
DD_CAP = 40.0             # growth objective: max drawdown must stay within -40%

OUT_DIR = os.environ.get("RESEARCH_OUT", "research_out")      # scratch (gitignored)
RESULTS_DIR = "research_results"                              # published summaries
SPLIT_JSON = os.path.join(OUT_DIR, "split.json")
N_WORKERS = int(os.environ.get("RESEARCH_WORKERS", os.cpu_count() or 1))


@dataclass
class Candidate:
    """One system to evaluate: buy (+ optional different sell) strategy + account rules."""

    label: str
    buy: str
    buy_config: dict
    stop_mode: str = "widest"
    sell: str = None             # None = the buy strategy's own exit
    sell_config: dict = None
    portfolio: dict = field(default_factory=dict)   # PortfolioConfig overrides

    def portfolio_config(self, base):
        return replace(base, stop_mode=self.stop_mode, **self.portfolio)

    def algorithms(self):
        buy = build_algorithm(self.buy, self.buy_config)
        if self.sell is None:
            return buy, buy
        return buy, build_algorithm(self.sell, self.sell_config if self.sell_config is not None else {})


# ---------------------------------------------------------------------------
# Data + splits
# ---------------------------------------------------------------------------

def research_symbols():
    """The research pool: every cached list (S&P 500, Nasdaq-100, watchlist, magic formula)."""
    return universe.get_universe("all")


def ensure_data(tickers):
    """Bulk-download whatever is not cached yet (fast path before per-ticker loads)."""
    newly = prefetch(list(tickers) + [MARKET_TICKER], FETCH_START, FETCH_END, interval=INTERVAL)
    print(f"  data: {len(newly)} tickers downloaded, rest from cache", flush=True)


def load_frames(tickers):
    """{ticker: frame} for every ticker with usable data; failures are reported, not raised."""
    frames, failed = {}, []
    for ticker in tickers:
        try:
            frames[ticker] = fetch_data(ticker, FETCH_START, FETCH_END, interval=INTERVAL)
        except PER_TICKER_ERRORS as exc:
            failed.append(f"{ticker} ({type(exc).__name__})")
    if failed:
        print(f"  data: skipped {len(failed)}: {', '.join(failed[:12])}", flush=True)
    return frames


def load_market_close():
    return fetch_data(MARKET_TICKER, FETCH_START, FETCH_END, interval=INTERVAL)["Close"]


def eligible_symbols():
    """Research-pool symbols with at least MIN_BARS of history, sorted."""
    symbols = research_symbols()
    ensure_data(symbols)
    frames = load_frames(symbols)
    return sorted(t for t, df in frames.items() if len(df) >= MIN_BARS)


def draw_split(eligible, seed):
    """Seeded, disjoint (train, test) draw of N_TRAIN / N_TEST names from `eligible`."""
    if len(eligible) < N_TRAIN + N_TEST:
        raise ConfigurationError(f"Only {len(eligible)} eligible symbols; need {N_TRAIN + N_TEST}.")
    shuffled = list(eligible)
    random.Random(seed).shuffle(shuffled)
    return sorted(shuffled[:N_TRAIN]), sorted(shuffled[N_TRAIN:N_TRAIN + N_TEST])


def build_split(force=False):
    """The canonical split (seed SEED), cached to OUT_DIR so every phase uses the same one."""
    if os.path.exists(SPLIT_JSON) and not force:
        with open(SPLIT_JSON) as fh:
            data = json.load(fh)
        return data["train"], data["test"], data["eligible"]
    eligible = eligible_symbols()
    train, test = draw_split(eligible, SEED)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SPLIT_JSON, "w") as fh:
        json.dump({"seed": SEED, "min_bars": MIN_BARS, "data_end": FETCH_END,
                   "eligible": eligible, "train": train, "test": test}, fh, indent=1)
    return train, test, eligible


# ---------------------------------------------------------------------------
# Parallel evaluation (each worker loads the frames once)
# ---------------------------------------------------------------------------

_WORKER = {}


def _init_worker(tickers):
    _WORKER["frames"] = load_frames(tickers)
    _WORKER["market"] = load_market_close()


def _window(frames, start, end):
    """Frames cut at `end` (inclusive); `start` is applied as trade_from by the caller."""
    if end is None:
        return frames
    cut = {t: df[df.index <= pd.Timestamp(end)] for t, df in frames.items()}
    return {t: df for t, df in cut.items() if len(df) and (start is None or df.index[-1] >= pd.Timestamp(start))}


def _evaluate_task(task):
    candidate, tickers, base, start, end = task
    frames = _window({t: _WORKER["frames"][t] for t in tickers if t in _WORKER["frames"]}, start, end)
    market = _WORKER["market"]
    buy, sell = candidate.algorithms()
    config = candidate.portfolio_config(base)
    result = run_portfolio(frames, buy, sell, config, market_close=market, trade_from=start)
    return metrics_row(candidate.label, result.metrics, config, candidate)


def evaluate(candidates, tickers, base=None, start=None, end=None, pool_tickers=None):
    """Evaluate candidates on `tickers` (optionally a [start, end] window) in parallel.

    `pool_tickers` (default `tickers`) is what each worker loads — pass the whole
    eligible pool when several universes are evaluated with one pool.
    """
    base = PortfolioConfig() if base is None else base
    tasks = [(c, tickers, base, start, end) for c in candidates]
    workers = max(1, min(N_WORKERS, len(tasks)))
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(pool_tickers or tickers,)) as pool:
        rows = []
        for row in pool.map(_evaluate_task, tasks):
            print(f"    {row['strategy']:44s} cagr={row['cagr']:5.1f}% maxDD={row['maxDD']:6.1f}% "
                  f"sharpe={row['sharpe']:.2f} trades={row['trades']}", flush=True)
            rows.append(row)
    return rows


def benchmark_rows(tickers, base=None, start=None, end=None):
    """Equal-weight Buy & Hold of `tickers` and SPY Buy & Hold over the same window."""
    base = PortfolioConfig() if base is None else base
    frames = _window(load_frames(tickers), start, end)
    market = load_market_close()
    if end is not None:
        market = market[market.index <= pd.Timestamp(end)]
    closes = {t: df["Close"] for t, df in frames.items()}
    ew = buy_and_hold_portfolio(closes, base)
    if start is not None:
        ew = ew[ew.index >= pd.Timestamp(start)]
    spy = single_asset_benchmark(market, base, start=start)
    return [metrics_row("BENCH equal-weight Buy&Hold", equity_metrics(ew), base, None),
            metrics_row("BENCH SPY Buy&Hold", equity_metrics(spy), base, None)]


def metrics_row(label, metrics, config, candidate):
    """A flat, rounded result row (the unit of every results table)."""
    row = {
        "strategy": label,
        "cagr": round(metrics["cagr"] * 100, 2),
        "maxDD": round(metrics["max_dd"] * 100, 1),
        "sharpe": round(metrics["sharpe"], 2),
        "calmar": round(metrics["calmar"], 2),
        "totRet": round(metrics["total_return"] * 100, 0),
        "finalEq": round(metrics["final_equity"], 0),
        "ddOK": bool(metrics["max_dd"] * 100 >= -DD_CAP),
    }
    if candidate is not None:
        row.update({
            "trades": metrics["n_trades"], "winRate": round(metrics["win_rate"] * 100, 0),
            "avgHold": round(metrics["avg_hold_bars"], 0),
            "maxPos": config.max_positions, "fill": config.fill_mode, "rank": config.rank_by,
            "buy": candidate.buy, "buyCfg": candidate.buy_config, "stop": candidate.stop_mode,
            "sell": candidate.sell, "sellCfg": candidate.sell_config,
        })
    return row


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

SHOW = ["strategy", "cagr", "maxDD", "sharpe", "calmar", "trades", "avgHold", "winRate", "ddOK"]


def print_table(title, rows, sort_key="cagr"):
    df = pd.DataFrame(rows).sort_values(sort_key, ascending=False)
    print(f"\n=== {title} ===")
    print(df[[c for c in SHOW if c in df.columns]].to_string(index=False))
    return df


def table(title, rows, sort_key="cagr", note=None):
    """A results table for the JSON report (rows sorted best-first)."""
    ordered = sorted(rows, key=lambda r: r[sort_key], reverse=True)
    columns = [c for c in SHOW if any(c in r for r in ordered)]
    return {"title": title, "note": note, "columns": columns,
            "rows": [{c: r[c] for c in columns if c in r} for r in ordered]}


def write_report(phase, tables, verdict=None, extra=None):
    """Write research_results/<phase>.json (published to the PWA) and update the index."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    report = {"phase": phase, "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
              "data": {"start": FETCH_START, "end": FETCH_END},
              "objective": f"max CAGR with max drawdown within -{DD_CAP:.0f}%",
              "tables": tables, "verdict": verdict, **(extra or {})}
    with open(os.path.join(RESULTS_DIR, f"{phase}.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    index_path = os.path.join(RESULTS_DIR, "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path) as fh:
            index = json.load(fh)
    index[phase] = report["generated"]
    with open(index_path, "w") as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    print(f"\nWritten: {os.path.join(RESULTS_DIR, phase + '.json')}")


if __name__ == "__main__":
    import sys

    import research_grids  # phase dispatch lives in the sibling so the grids are editable alone
    research_grids.main(sys.argv[1:])
