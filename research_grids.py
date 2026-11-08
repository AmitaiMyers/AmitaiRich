"""Search spaces + phases for the portfolio research (edit the grids freely).

Each phase is just (which stocks, which candidates); `run_grid` does the rest
(parallel evaluation, printed table, JSON report for the PWA). Run:

    python research_grids.py <phase>

Phases:
  split            build + show the canonical 300/100 stock split
  smoke            tiny end-to-end check (25 train stocks)
  baseline         re-baseline production + past champions on train AND test,
                   close vs next-open fills, vs equal-weight and SPY Buy & Hold
  v3               the automated improvement study (see `v3` below)
  train | refine | sweep | growth | refine_growth | regime | squeeze | validate
                   the historical grids from research_26062026.md (re-runnable on
                   the new engine; results will differ — see the doc's Part V)
"""

import sys
from dataclasses import replace

import research_portfolio as rp
from portfolio import PortfolioConfig
from research_portfolio import Candidate

MR = "Momentum Rider (ROC + MA exit)"
VA = "Vol-Adjusted Momentum Rider"
TR = "Trend Rider (breakout + MA exit)"
GR = "Growth Rider (momentum + chandelier)"
DONCHIAN = "Trend Follower (Donchian)"
ROOF = "Roof: 52-Week-High Breakout"


def _mr(threshold, **extra):
    return {"mom_lookback": 126, "mom_threshold": threshold, "atr_period": 20, "trend_ma": 200, **extra}


# The production system in scan_today.py (Growth Momentum Rider v2, ~20 positions).
PRODUCTION = Candidate("PRODUCTION MomRider thr=0.25 mp=20", MR, _mr(0.25), portfolio={"max_positions": 20})

PAST_CHAMPIONS = [
    Candidate("Part II MomRider thr=0.30 mp=15", MR, _mr(0.30)),
    Candidate("Part I VolAdj thr=12 mp=15", VA, {"mom_lookback": 126, "score_threshold": 12.0}),
    Candidate("Original Roof252 vol1.5 (tightest)", ROOF,
              {"roof_lookback": 252, "vol_surge_mult": 1.5}, stop_mode="tightest"),
]


# ---------------------------------------------------------------------------
# v3 — the automated improvement study
# ---------------------------------------------------------------------------
# Realistic by default: the scan runs after the close, so orders fill at the NEXT
# open; 10 bps/side; 1% risk. Levers tested around the production core:
#   * entry selectivity (mom_threshold) and breadth (max_positions)
#   * exit confirmation (exit_confirm: closes below the 200-MA before selling)
#   * buy priority: raw momentum vs volatility-adjusted momentum
#   * the strongest structural alternatives from earlier rounds

V3_BASE = PortfolioConfig(fill_mode="next_open")
V3_FINALISTS = 4
V3_SEEDS = (101, 202, 303, 404, 505)
V3_WINDOWS = (("2006-01-01", "2015-12-31"), ("2016-01-01", None))


def v3_candidates():
    grid = []
    for threshold in (0.20, 0.25, 0.30, 0.40):
        for max_positions in (20, 25):
            for exit_confirm in (1, 3):
                for rank_by in ("signal", "vol_adj"):
                    grid.append(Candidate(
                        f"MomRider thr={threshold} mp={max_positions} xc={exit_confirm} rank={rank_by}",
                        MR, _mr(threshold, exit_confirm=exit_confirm),
                        portfolio={"max_positions": max_positions, "rank_by": rank_by}))
    grid += [
        Candidate("VolAdj thr=10 mp=20", VA, {"mom_lookback": 126, "score_threshold": 10.0},
                  portfolio={"max_positions": 20}),
        Candidate("TrendRider bl=50 xMA=200 mp=20", TR,
                  {"breakout_lookback": 50, "exit_ma": 200, "trend_ma": 200, "atr_mult": 3.0},
                  portfolio={"max_positions": 20}),
        Candidate("Donchian e=200 x=100 mp=20", DONCHIAN,
                  {"entry_lookback": 200, "exit_lookback": 100, "use_trend_filter": 0, "atr_mult": 3.0},
                  portfolio={"max_positions": 20}),
        Candidate("MIX MomRider-entry + DualConfirm-exit mp=20", MR, _mr(0.25),
                  sell="Dual-Confirm Trend Hold", sell_config={}, portfolio={"max_positions": 20}),
    ]
    return grid


def _beats(row, baseline_row):
    return row["cagr"] > baseline_row["cagr"]


def v3():
    """Train grid -> finalists -> test -> multi-split robustness -> walk-forward -> verdict.

    A finalist is PROMOTED only if, versus production under identical rules, it:
      1. has higher CAGR on the 100 never-tuned test stocks, within the DD cap;
      2. has higher CAGR on a majority of re-drawn random splits (test halves);
      3. has higher CAGR in every walk-forward time window.
    The report never edits production — switching scan_today.py stays a human call.
    """
    train, test, eligible = rp.build_split()
    tables = []

    print(f"[1/4] TRAIN grid on {len(train)} stocks", flush=True)
    grid = v3_candidates()
    train_rows = rp.evaluate([PRODUCTION] + grid, train, V3_BASE, pool_tickers=eligible)
    tables.append(rp.table("Train grid (300 stocks, next-open fills)",
                           train_rows + rp.benchmark_rows(train, V3_BASE)))
    production_label = PRODUCTION.label
    qualified = [r for r in train_rows if r["ddOK"] and r["strategy"] != production_label]
    qualified.sort(key=lambda r: r["cagr"], reverse=True)
    finalist_labels = [r["strategy"] for r in qualified[:V3_FINALISTS]]
    by_label = {c.label: c for c in grid}
    finalists = [PRODUCTION] + [by_label[label] for label in finalist_labels]

    print(f"[2/4] TEST: {len(finalists)} systems on {len(test)} unseen stocks", flush=True)
    test_rows = rp.evaluate(finalists, test, V3_BASE, pool_tickers=eligible)
    tables.append(rp.table("Out-of-sample: 100 never-tuned stocks",
                           test_rows + rp.benchmark_rows(test, V3_BASE)))

    print(f"[3/4] ROBUSTNESS: {len(V3_SEEDS)} re-drawn splits", flush=True)
    split_wins = {label: 0 for label in finalist_labels}
    split_cagrs = {c.label: [] for c in finalists}
    for seed in V3_SEEDS:
        _, seed_test = rp.draw_split(eligible, seed)
        rows = {r["strategy"]: r for r in rp.evaluate(finalists, seed_test, V3_BASE, pool_tickers=eligible)}
        for label in split_cagrs:
            split_cagrs[label].append(rows[label]["cagr"])
        for label in finalist_labels:
            split_wins[label] += int(_beats(rows[label], rows[production_label]))
    tables.append({
        "title": f"Robustness: OOS CAGR on {len(V3_SEEDS)} re-drawn 100-stock test sets",
        "note": None, "columns": ["strategy", "meanCagr", "minCagr", "beatsProduction"],
        "rows": [{"strategy": label, "meanCagr": round(sum(v) / len(v), 2), "minCagr": min(v),
                  "beatsProduction": "-" if label == production_label
                  else f"{split_wins[label]}/{len(V3_SEEDS)}"}
                 for label, v in split_cagrs.items()]})

    print(f"[4/4] WALK-FORWARD: {len(V3_WINDOWS)} time windows on all {len(eligible)} stocks", flush=True)
    window_wins = {label: 0 for label in finalist_labels}
    for start, end in V3_WINDOWS:
        rows = rp.evaluate(finalists, eligible, V3_BASE, start=start, end=end)
        by = {r["strategy"]: r for r in rows}
        for label in finalist_labels:
            window_wins[label] += int(_beats(by[label], by[production_label]))
        tables.append(rp.table(f"Walk-forward window {start} .. {end or 'today'} (all eligible stocks)",
                               rows + rp.benchmark_rows(eligible, V3_BASE, start=start, end=end)))

    verdict = _v3_verdict(test_rows, split_wins, window_wins, finalist_labels, production_label)
    print(f"\nVERDICT: {verdict['summary']}")
    rp.write_report("v3", tables, verdict=verdict,
                    extra={"finalists": finalist_labels, "fill_mode": V3_BASE.fill_mode})


def _v3_verdict(test_rows, split_wins, window_wins, finalist_labels, production_label):
    by = {r["strategy"]: r for r in test_rows}
    production = by[production_label]
    promoted = [label for label in finalist_labels
                if _beats(by[label], production) and by[label]["ddOK"]
                and split_wins[label] > len(V3_SEEDS) // 2
                and window_wins[label] == len(V3_WINDOWS)]
    if not promoted:
        return {"winner": production_label, "promoted": [],
                "summary": "No candidate beat production on every check — keep production."}
    winner = max(promoted, key=lambda label: by[label]["cagr"])
    return {"winner": winner, "promoted": promoted,
            "summary": (f"{winner} beat production out-of-sample ({by[winner]['cagr']}% vs "
                        f"{production['cagr']}% CAGR), on {split_wins[winner]}/{len(V3_SEEDS)} "
                        f"re-drawn splits and in every walk-forward window.")}


# ---------------------------------------------------------------------------
# Baseline + historical grids
# ---------------------------------------------------------------------------

def baseline():
    """Production + past champions, train and test, close vs next-open, + benchmarks."""
    train, test, eligible = rp.build_split()
    systems = [PRODUCTION] + PAST_CHAMPIONS
    tables = []
    for name, stocks in (("Train (300)", train), ("Test (100)", test)):
        for fill in ("close", "next_open"):
            base = PortfolioConfig(fill_mode=fill)
            rows = rp.evaluate(systems, stocks, base, pool_tickers=eligible)
            tables.append(rp.table(f"{name}, {fill} fills", rows + rp.benchmark_rows(stocks, base)))
    rp.write_report("baseline", tables)


def smoke():
    """Tiny end-to-end run on 25 train stocks."""
    train, _test, _eligible = rp.build_split()
    stocks = train[:25]
    rows = rp.evaluate([PRODUCTION, Candidate("TrendRider default", TR, {})], stocks)
    rp.print_table("SMOKE (25 train stocks)", rows + rp.benchmark_rows(stocks))


def split():
    train, test, eligible = rp.build_split(force=True)
    print(f"{len(eligible)} eligible; TRAIN {len(train)}: {', '.join(train[:12])} ...")
    print(f"TEST {len(test)}: {', '.join(test[:12])} ...  (cached at {rp.SPLIT_JSON})")


def run_grid(phase, candidates, universe="train", sort_key="cagr"):
    """Evaluate a candidate list on the train or test stocks and write the report."""
    train, test, eligible = rp.build_split()
    stocks = train if universe == "train" else test
    print(f"=== {phase}: {len(candidates)} systems x {len(stocks)} {universe} stocks ===", flush=True)
    rows = rp.evaluate(candidates, stocks, pool_tickers=eligible)
    rows += rp.benchmark_rows(stocks)
    rp.print_table(f"{phase} ({universe})", rows, sort_key)
    rp.write_report(phase, [rp.table(f"{phase} ({universe} stocks)", rows, sort_key)])


def train_configs():
    """The Part I grid (risk-adjusted study)."""
    c = list(PAST_CHAMPIONS[2:])
    for bl in (50, 100, 150):
        for exit_ma in (100, 200):
            for am in (3.0, 4.0):
                c.append(Candidate(f"TrendRider bl={bl} xMA={exit_ma} atr={am}", TR,
                                   {"breakout_lookback": bl, "exit_ma": exit_ma, "trend_ma": 200,
                                    "atr_mult": am}))
    for ml in (126, 189, 252):
        for tm in (150, 200):
            c.append(Candidate(f"MomRider mom={ml} trendMA={tm}", MR,
                               {"mom_lookback": ml, "trend_ma": tm, "atr_mult": 4.0}))
    for ml in (126, 252):
        for thr in (5.0, 8.0, 12.0):
            c.append(Candidate(f"VolAdjMom mom={ml} thr={thr}", VA,
                               {"mom_lookback": ml, "score_threshold": thr}))
    for xl in (60, 100, 120):
        c.append(Candidate(f"DualConfirm xl={xl}", "Dual-Confirm Trend Hold", {"exit_lookback": xl}))
    for er in (0.30, 0.40, 0.50):
        c.append(Candidate(f"EffRider er={er}", "Efficiency-Ratio Trend Rider", {"er_threshold": er}))
    for el, xl in ((40, 100), (40, 120), (40, 160), (60, 160)):
        c.append(Candidate(f"TwoSpeed e={el} x={xl}", "Two-Speed Donchian",
                           {"entry_lookback": el, "exit_lookback": xl}))
    for entry in (50, 100, 200):
        for ex in (50, 100):
            if ex >= entry:
                continue
            for filt in (0, 1):
                c.append(Candidate(f"Donchian e={entry} x={ex} filt={filt}", DONCHIAN,
                                   {"entry_lookback": entry, "exit_lookback": ex,
                                    "use_trend_filter": filt, "atr_mult": 3.0}))
    for ml in (126, 252):
        c.append(Candidate(f"TSMom mom={ml}", "Time-Series Momentum (absolute)",
                           {"mom_lookback": ml, "ma_period": 200, "atr_mult": 3.0}))
    for prox in (0.90, 0.95):
        for drop in (0.75, 0.85):
            c.append(Candidate(f"52wHi prox={prox} drop={drop}", "52-Week High Momentum",
                               {"proximity": prox, "exit_drop": drop, "atr_mult": 3.0}))
    for lb in (126, 252):
        for xm in ("trailing", "structural"):
            for vm in (0.0, 1.5):
                c.append(Candidate(f"RoofHi lb={lb} {xm} vol={vm}", ROOF,
                                   {"roof_lookback": lb, "exit_mode": xm, "vol_surge_mult": vm,
                                    "trail_atr_mult": 3.0, "struct_ma_period": 100}))
    for xm in ("trailing", "structural"):
        c.append(Candidate(f"Squeeze {xm}", "Roof: Volatility-Squeeze Breakout",
                           {"exit_mode": xm, "struct_ma_period": 100}))
    for fast, slow in ((20, 100), (50, 200)):
        c.append(Candidate(f"SMAx {fast}/{slow}", "SMA Crossover",
                           {"fast_period": fast, "slow_period": slow, "atr_mult": 3.0}))
    c.append(Candidate("BollBounce", "Bollinger Bounce (mean reversion)", {"atr_mult": 3.0},
                       stop_mode="tightest"))
    c.append(Candidate("RSIpullback", "Pullback Reversal (RSI in uptrend)", {"atr_mult": 3.0}))
    return c


def refine_configs():
    c = []
    for ml in (63, 100, 126):
        for thr in (10.0, 12.0, 16.0, 20.0, 25.0):
            c.append(Candidate(f"VolAdjMom mom={ml} thr={thr}", VA,
                               {"mom_lookback": ml, "score_threshold": thr}))
    for xma in (150, 250):
        c.append(Candidate(f"VolAdjMom thr=16 xMA={xma}", VA,
                           {"mom_lookback": 126, "score_threshold": 16.0, "exit_ma": xma}))
    for stop in ("tightest", "widest"):
        for am in (3.0, 6.0):
            c.append(Candidate(f"VolAdjMom thr=16 atr={am} {stop}", VA,
                               {"mom_lookback": 126, "score_threshold": 16.0, "atr_mult": am},
                               stop_mode=stop))
    return c


def sweep_configs():
    """Portfolio-parameter sweep (positions, regime filter, risk) on two finalists."""
    variants = [("mp=15", {}), ("mp=10", {"max_positions": 10}), ("mp=25", {"max_positions": 25}),
                ("mp=15 +regime", {"regime_filter": True}),
                ("mp=25 +regime", {"max_positions": 25, "regime_filter": True}),
                ("mp=15 risk=2%", {"risk_pct": 0.02})]
    systems = [PRODUCTION, PAST_CHAMPIONS[1]]
    return [replace(s, label=f"{s.label} | {v}", portfolio={**s.portfolio, **kw})
            for s in systems for v, kw in variants]


def growth_configs():
    c = []
    for thr in (8.0, 10.0, 12.0):
        c.append(Candidate(f"VolAdjMom thr={thr}", VA, {"mom_lookback": 126, "score_threshold": thr}))
    for mt in (0.20, 0.30, 0.40):
        for tm in (5.0, 8.0):
            c.append(Candidate(f"GrowthRider mt={mt} trail={tm}", GR,
                               {"mom_threshold": mt, "trail_atr_mult": tm}))
    for exit_ma in (150, 200):
        c.append(Candidate(f"AccelMom 63/252 x{exit_ma}", "Accelerating Momentum Rider",
                           {"fast": 63, "slow": 252, "exit_ma": exit_ma}))
    c.append(Candidate("MIX VolAdj-entry + Chandelier-exit", VA,
                       {"mom_lookback": 126, "score_threshold": 10.0},
                       sell=GR, sell_config={"trail_atr_mult": 6.0}))
    c.append(Candidate("MIX Growth-entry + 200MA-exit", GR, {"mom_threshold": 0.30},
                       sell=MR, sell_config={"trend_ma": 200}))
    with_positions = []
    for candidate in c:
        for mp in (15, 20):
            with_positions.append(replace(candidate, label=f"{candidate.label} | mp={mp}",
                                          portfolio={"max_positions": mp}))
    return with_positions


def refine_growth_configs():
    c = []
    for thr in (10.0, 12.0):
        for trail in (3.0, 4.0, 5.0, 6.0):
            c.append(Candidate(f"MIX VolAdj{int(thr)}+Chand{trail}", VA,
                               {"mom_lookback": 126, "score_threshold": thr},
                               sell=GR, sell_config={"trail_atr_mult": trail, "trail_atr_period": 22}))
    return c


def regime_configs():
    return [Candidate(f"MomRider thr={thr}{' +regime' if regime else ''} | mp={mp}", MR, _mr(thr),
                      portfolio={"max_positions": mp, "regime_filter": regime})
            for thr in (0.15, 0.20, 0.25, 0.30, 0.40) for regime in (False, True) for mp in (15, 20)]


def squeeze_configs():
    c = [PRODUCTION]
    for bw in (0.15, 0.20):
        for mt in (0.10, 0.15, 0.25):
            for ext in (0.40, 0.60, 9.99):
                c.append(Candidate(f"SqzMom bw={bw} mom={mt} ext={'off' if ext > 9 else ext}",
                                   "Squeeze Momentum Breakout",
                                   {"bandwidth_threshold": bw, "mom_threshold": mt, "max_ext": ext},
                                   portfolio={"max_positions": 20}))
    return c


def validate_configs():
    return [PRODUCTION] + PAST_CHAMPIONS


GRIDS = {
    "train": (train_configs, "train"),
    "refine": (refine_configs, "train"),
    "sweep": (sweep_configs, "train"),
    "growth": (growth_configs, "train"),
    "refine_growth": (refine_growth_configs, "train"),
    "regime": (regime_configs, "train"),
    "squeeze": (squeeze_configs, "train"),
    "validate": (validate_configs, "test"),
}

PHASES = {"split": split, "smoke": smoke, "baseline": baseline, "v3": v3}


def main(argv):
    phase = argv[0] if argv else "smoke"
    if phase in PHASES:
        PHASES[phase]()
    elif phase in GRIDS:
        configs, universe = GRIDS[phase]
        run_grid(phase, configs(), universe)
    else:
        print("usage: python research_grids.py", "|".join(list(PHASES) + list(GRIDS)))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
