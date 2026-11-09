"""Systematic strategy search (the owner's "try as many ideas as needed").

    python search.py            # -> reports/search/search.md + search.csv

Honesty rules (GOAL_SPEC.md):
  * every configuration is scored on the DEVELOPMENT period (2005-2018) only;
  * selection = best development objective (CAGR, only for configs with max DD within -35%
    and >= 100 trades); the top configurations are then CHECKED on validation (2019-2022),
    never chosen by it;
  * the report states how many configurations were tried — the more tried, the more the
    best development number overstates the future (selection bias).
"""

import itertools
import multiprocessing
import os
from dataclasses import replace

import pandas as pd

import strategy_lab as L
from algo_versions import Version

OUT_DIR = os.path.join("reports", "search")
WORKERS = int(os.environ.get("SEARCH_WORKERS", os.cpu_count() or 1))
TOP_FOR_VALIDATION = 15
MAX_DD = -0.35
MIN_TRADES = 100

WEIGHT_SETS = {
    "earn3": {"beat_streak": 1.0, "sue": 1.0, "rev_accel": 0.5},
    "beat": {"beat_streak": 1.0},
    "earn+growth": {"beat_streak": 1.0, "sue": 1.0, "rev_accel": 1.0, "rev_growth_yoy": 1.0, "eps_growth_yoy": 0.5},
    "earn+trend": {"beat_streak": 1.0, "sue": 1.0, "rev_accel": 0.5, "trend_200": 0.5, "vol_adj_mom": 0.5},
    "quality": {"rev_consistency": 1.0, "eps_consistency": 1.0, "beat_streak": 1.0},
    "earn+reversal": {"beat_streak": 1.0, "sue": 1.0, "rev_accel": 0.5, "short_reversal": 1.0},
    "earn+lowvol": {"beat_streak": 1.0, "sue": 1.0, "rev_accel": 0.5, "low_vol": 1.0},
    "pead": {"surprise_fresh": 2.0, "beat_streak": 1.0},
    "momentum": {"mom_12_1": 1.0, "vol_adj_mom": 1.0},
    "everything": None,   # every factor, equal weight (filled in at run time)
}
FILTER_SETS = {
    "none": {},
    "above200": {"stock_above_ma": 200},
    "above200+beat": {"stock_above_ma": 200, "beat_last": True},
    "above100": {"stock_above_ma": 100},
}
EXIT_SETS = {
    "rankdrop": {"rank_drop": True},
    "rankdrop+ma200x3": {"rank_drop": True, "ma_break": 200, "ma_confirm": 3},
    "rankdrop+1y": {"rank_drop": True, "time_stop": 252},
}


def ranked_grid():
    everything = {name: 1.0 for name, f in L.factors.FACTORS.items() if f.group not in ("control",)}
    for (wname, weights), (fname, filters), (ename, exits), positions, rebalance in itertools.product(
            WEIGHT_SETS.items(), FILTER_SETS.items(), EXIT_SETS.items(), (10, 20, 30), ("weekly", "monthly")):
        label = f"ranked {wname} | {fname} | {ename} | {positions}pos | {rebalance}"
        yield label, Version(label, label, weights=weights or everything, filters=filters, exits=exits,
                             max_positions=positions, rebalance=rebalance, atr_mult=8.0)


def rider_grid():
    mr = "Momentum Rider (ROC + MA exit)"
    for threshold, trend, confirm, positions in itertools.product((0.0, 0.1, 0.25, 0.4), (100, 200), (1, 3), (10, 20)):
        label = f"rider momentum thr={threshold} ma={trend} confirm={confirm} | {positions}pos"
        yield label, Version(label, label, base_algorithm=mr, max_positions=positions, sizing="risk_based",
                             base_config={"mom_lookback": 126, "mom_threshold": threshold, "trend_ma": trend,
                                          "exit_confirm": confirm, "atr_period": 20})
    for threshold, positions in itertools.product((4.0, 8.0, 12.0), (10, 20)):
        label = f"rider vol-adj thr={threshold} | {positions}pos"
        yield label, Version(label, label, base_algorithm="Vol-Adjusted Momentum Rider", max_positions=positions,
                             sizing="risk_based", base_config={"score_threshold": threshold})
    for lookback, exit_ma in itertools.product((50, 100, 200), (100, 200)):
        label = f"rider trend breakout bl={lookback} exit={exit_ma} | 20pos"
        yield label, Version(label, label, base_algorithm="Trend Rider (breakout + MA exit)", sizing="risk_based",
                             base_config={"breakout_lookback": lookback, "exit_ma": exit_ma, "atr_mult": 4.0})
    for entry, exit_ in ((40, 120), (100, 50), (200, 100)):
        label = f"rider donchian {entry}/{exit_} | 20pos"
        yield label, Version(label, label, base_algorithm="Trend Follower (Donchian)", sizing="risk_based",
                             base_config={"entry_lookback": entry, "exit_lookback": exit_, "use_trend_filter": 1})


def _metrics_row(label, window, metrics):
    return {f"{window}_cagr": metrics["cagr"], f"{window}_dd": metrics["max_dd"],
            f"{window}_sharpe": metrics["sharpe"], f"{window}_trades": metrics["n_trades"],
            f"{window}_exposure": metrics["exposure"]}


def _evaluate_dev(item):
    label, version = item
    start, end = L.periods.research_window("development")
    result = L.run_window(version, start, end)
    return {"label": label, **_metrics_row(label, "dev", result.metrics)}


def _evaluate_val(item):
    label, version = item
    start, end = L.periods.research_window("validation")
    result = L.run_window(version, start, end)
    return {"label": label, **_metrics_row(label, "val", result.metrics)}


def objective(row):
    """Development CAGR if the config respects the drawdown cap and trade minimum, else -inf."""
    if row["dev_dd"] < MAX_DD or row["dev_trades"] < MIN_TRADES:
        return float("-inf")
    return row["dev_cagr"]


def run():
    data = L.lab_data("core")
    for name in {n for w in WEIGHT_SETS.values() if w for n in w} | set(L.factors.FACTORS):
        if L.factors.FACTORS[name].group != "control":
            data.factor(name)            # compute once in the parent; forked workers share it
    grid = list(ranked_grid()) + list(rider_grid())
    by_label = dict(grid)
    print(f"searching {len(grid)} configurations on development with {WORKERS} workers ...", flush=True)
    context = multiprocessing.get_context("fork")
    with context.Pool(WORKERS) as pool:
        rows = []
        for k, row in enumerate(pool.imap_unordered(_evaluate_dev, grid, chunksize=4), start=1):
            rows.append(row)
            if k % 50 == 0:
                print(f"  {k}/{len(grid)}", flush=True)
        table = pd.DataFrame(rows)
        table["objective"] = table.apply(objective, axis=1)
        table = table.sort_values("objective", ascending=False).reset_index(drop=True)
        finalists = table.head(TOP_FOR_VALIDATION)["label"].tolist()
        val_rows = pool.map(_evaluate_val, [(label, by_label[label]) for label in finalists])
    table = table.merge(pd.DataFrame(val_rows), on="label", how="left")
    write(table, len(grid))
    return table


def _benchmarks():
    rows = {}
    for window in ("development", "validation"):
        start, end = L.periods.research_window(window)
        for name, curve in L.benchmark_curves(start, end).items():
            m = L.equity_metrics(curve)
            rows[(window, name)] = m
    return rows


def write(table, n_tried):
    os.makedirs(OUT_DIR, exist_ok=True)
    table.to_csv(os.path.join(OUT_DIR, "search.csv"), index=False)
    bench = _benchmarks()
    spy_dev, spy_val = bench[("development", "SPY")], bench[("validation", "SPY")]
    qualified = table[table["objective"] > float("-inf")]
    pct = lambda x: "" if pd.isna(x) else f"{x * 100:+.1f}%"
    lines = [f"# Strategy search — {n_tried} configurations", "",
             f"Scored on development (2005-2018) only; {len(qualified)} met max DD >= {MAX_DD * 100:.0f}% and "
             f">= {MIN_TRADES} trades. The top {TOP_FOR_VALIDATION} by development CAGR were then checked on "
             "validation (2019-2022). With this many tries, the best development CAGR is optimistic by "
             "construction — the validation column is the honest one.", "",
             f"Benchmarks — SPY: dev {pct(spy_dev['cagr'])} (DD {spy_dev['max_dd'] * 100:.0f}%), "
             f"val {pct(spy_val['cagr'])} (DD {spy_val['max_dd'] * 100:.0f}%). "
             f"RSP: dev {pct(bench[('development', 'RSP')]['cagr'])}, val {pct(bench[('validation', 'RSP')]['cagr'])}.", "",
             "| # | Configuration | Dev CAGR | Dev DD | Dev Sharpe | Trades | Invested | Val CAGR | Val DD | Val Sharpe |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, row in table.head(TOP_FOR_VALIDATION).iterrows():
        lines.append(f"| {i + 1} | {row['label']} | {pct(row['dev_cagr'])} | {row['dev_dd'] * 100:.0f}% | "
                     f"{row['dev_sharpe']:.2f} | {int(row['dev_trades'])} | {row['dev_exposure'] * 100:.0f}% | "
                     f"{pct(row['val_cagr'])} | {row['val_dd'] * 100:.0f}% | {row['val_sharpe']:.2f} |")
    beat_both = table[(table["dev_cagr"] > spy_dev["cagr"]) & (table["val_cagr"] > spy_val["cagr"])]
    lines += ["", f"Configurations beating SPY's CAGR in BOTH periods (among those checked): {len(beat_both)}.", "",
              "## Development CAGR by family (all configurations)", "",
              "| Family | Configs | Best dev CAGR | Median dev CAGR | Median dev DD |", "|---|---|---|---|---|"]
    table["family"] = table["label"].str.split(" \\| ").str[0].str.split(" ").str[:2].str.join(" ")
    for family, group in table.groupby("family"):
        lines.append(f"| {family} | {len(group)} | {pct(group['dev_cagr'].max())} | {pct(group['dev_cagr'].median())} | "
                     f"{group['dev_dd'].median() * 100:.0f}% |")
    with open(os.path.join(OUT_DIR, "search.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Written {os.path.join(OUT_DIR, 'search.md')}")


if __name__ == "__main__":
    run()
