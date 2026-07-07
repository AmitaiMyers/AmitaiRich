"""Grid definitions + phase dispatch for the portfolio research (edit me freely).

Kept separate from research_portfolio.py so the (frequently-tweaked) search space
can change without touching the validated engine/harness. Run:

    python research_grids.py split | smoke | train | sweep | validate
"""

import sys

import pandas as pd

import research_portfolio as rp
from portfolio import PortfolioConfig

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 30)


# ---------------------------------------------------------------------------
# Search space — strategy x parameter configs. (label, algo_name, config, stop_mode)
# ---------------------------------------------------------------------------

# The EXACT production strategy in scan_today.py today — the baseline every
# candidate must beat (Roof 52-week-high breakout + 1.5x volume; class-default
# trailing chandelier exit; check_holding's default 'tightest' stop).
CURRENT_DEFAULT = ("CURRENT DEFAULT (Roof252 vol1.5)", "Roof: 52-Week-High Breakout",
                   {"roof_lookback": 252, "vol_surge_mult": 1.5}, "tightest")


def train_configs():
    """The full strategy/parameter grid evaluated on the 300 training stocks."""
    cfgs = [CURRENT_DEFAULT]

    # --- New hold-winner riders (the focus): breakout vs momentum entry, MA exit ---
    for bl in (50, 100, 150):
        for exit_ma in (100, 200):
            for am in (3.0, 4.0):
                cfgs.append((f"TrendRider bl={bl} xMA={exit_ma} atr={am}",
                             "Trend Rider (breakout + MA exit)",
                             {"breakout_lookback": bl, "exit_ma": exit_ma, "trend_ma": 200,
                              "atr_mult": am}, "widest"))
    for ml in (126, 189, 252):
        for tm in (150, 200):
            cfgs.append((f"MomRider mom={ml} trendMA={tm}",
                         "Momentum Rider (ROC + MA exit)",
                         {"mom_lookback": ml, "trend_ma": tm, "atr_mult": 4.0}, "widest"))

    # --- Panel-designed riders: vol-adjusted momentum (lever = score_threshold) ---
    for ml in (126, 252):
        for thr in (5.0, 8.0, 12.0):
            cfgs.append((f"VolAdjMom mom={ml} thr={thr}", "Vol-Adjusted Momentum Rider",
                         {"mom_lookback": ml, "score_threshold": thr}, "widest"))
    # --- Dual-confirm trend hold (lever = exit_lookback) ---
    for xl in (60, 100, 120):
        cfgs.append((f"DualConfirm xl={xl}", "Dual-Confirm Trend Hold",
                     {"exit_lookback": xl}, "widest"))
    # --- Efficiency-ratio trend rider (lever = er_threshold) ---
    for er in (0.30, 0.40, 0.50):
        cfgs.append((f"EffRider er={er}", "Efficiency-Ratio Trend Rider",
                     {"er_threshold": er}, "widest"))
    # --- Two-speed Donchian (lever = exit_lookback; the low-overfit baseline) ---
    for el, xl in ((40, 100), (40, 120), (40, 160), (60, 160)):
        cfgs.append((f"TwoSpeed e={el} x={xl}", "Two-Speed Donchian",
                     {"entry_lookback": el, "exit_lookback": xl}, "widest"))

    # --- Donchian trend follower (channel breakout entry, channel-low exit) ---
    for entry in (50, 100, 200):
        for ex in (50, 100):
            if ex >= entry:
                continue
            for filt in (0, 1):
                cfgs.append((f"Donchian e={entry} x={ex} filt={filt}",
                             "Trend Follower (Donchian)",
                             {"entry_lookback": entry, "exit_lookback": ex,
                              "use_trend_filter": filt, "atr_mult": 3.0}, "widest"))

    # --- Absolute (time-series) momentum ---
    for ml in (126, 252):
        cfgs.append((f"TSMom mom={ml}", "Time-Series Momentum (absolute)",
                     {"mom_lookback": ml, "ma_period": 200, "atr_mult": 3.0}, "widest"))

    # --- 52-week-high proximity momentum ---
    for prox in (0.90, 0.95):
        for drop in (0.75, 0.85):
            cfgs.append((f"52wHi prox={prox} drop={drop}", "52-Week High Momentum",
                         {"proximity": prox, "exit_drop": drop, "atr_mult": 3.0}, "widest"))

    # --- 52-week-high breakout (roof) + volume, trailing vs structural exit ---
    for lb in (126, 252):
        for xm in ("trailing", "structural"):
            for vm in (0.0, 1.5):
                cfgs.append((f"RoofHi lb={lb} {xm} vol={vm}", "Roof: 52-Week-High Breakout",
                             {"roof_lookback": lb, "exit_mode": xm, "vol_surge_mult": vm,
                              "trail_atr_mult": 3.0, "struct_ma_period": 100}, "widest"))

    # --- Volatility-squeeze breakout ---
    for xm in ("trailing", "structural"):
        cfgs.append((f"Squeeze {xm}", "Roof: Volatility-Squeeze Breakout",
                     {"exit_mode": xm, "struct_ma_period": 100}, "widest"))

    # --- SMA crossover (classic) ---
    for fast, slow in ((20, 100), (50, 200)):
        cfgs.append((f"SMAx {fast}/{slow}", "SMA Crossover",
                     {"fast_period": fast, "slow_period": slow, "atr_mult": 3.0}, "widest"))

    # --- Mean-reversion / short-horizon contrast (expected higher churn) ---
    cfgs.append(("BollBounce", "Bollinger Bounce (mean reversion)", {"atr_mult": 3.0}, "tightest"))
    cfgs.append(("RSIpullback", "Pullback Reversal (RSI in uptrend)", {"atr_mult": 3.0}, "widest"))

    return cfgs


# Finalists carried to out-of-sample validation (updated after reading train results).
# CURRENT_DEFAULT is always included so the OOS test compares winner vs production vs B&H.
FINALISTS = [
    CURRENT_DEFAULT,
    ("WINNER VolAdjMom mom=126 thr=12", "Vol-Adjusted Momentum Rider",
     {"mom_lookback": 126, "score_threshold": 12.0}, "widest"),
    ("VolAdjMom mom=126 thr=10", "Vol-Adjusted Momentum Rider",
     {"mom_lookback": 126, "score_threshold": 10.0}, "widest"),
    ("TrendRider bl=50 xMA=200 atr=3", "Trend Rider (breakout + MA exit)",
     {"breakout_lookback": 50, "exit_ma": 200, "trend_ma": 200, "atr_mult": 3.0}, "widest"),
    ("Donchian e=200 x=100 filt=0", "Trend Follower (Donchian)",
     {"entry_lookback": 200, "exit_lookback": 100, "use_trend_filter": 0, "atr_mult": 3.0}, "widest"),
]


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def split():
    train, test = rp.build_split()
    print(f"TRAIN {len(train)} stocks: {', '.join(train[:15])} ...")
    print(f"TEST  {len(test)} stocks: {', '.join(test[:15])} ...")
    print(f"Split cached at {rp.SPLIT_JSON}")


def smoke():
    """Tiny end-to-end run: ~25 train stocks, two riders + B&H. Validates the pipeline."""
    train, _ = rp.build_split()
    universe = train[:25]
    tag = "smoke25"
    closes = rp.load_closes(universe)
    market = rp.load_market_close()
    pcfg = PortfolioConfig()
    rows = []
    for label, algo, cfg, stop in [
        ("TrendRider default", "Trend Rider (breakout + MA exit)", {}, "widest"),
        ("MomRider default", "Momentum Rider (ROC + MA exit)", {}, "widest"),
    ]:
        rows.append(rp.eval_config(label, algo, cfg, universe, closes, market, pcfg, stop, tag,
                                   n_workers=6))
    bench = rp.benchmark_metrics(closes, pcfg)
    print("\n=== SMOKE (25 train stocks) ===")
    rp._print_rows(rows, bench)


def train():
    """Full grid on the 300 training stocks (default realistic portfolio)."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    pcfg = PortfolioConfig()
    cfgs = train_configs()
    print(f"=== TRAIN GRID: {len(cfgs)} configs x {len(train_stocks)} stocks ===", flush=True)
    rows = []
    for i, (label, algo, cfg, stop) in enumerate(cfgs):
        row = rp.eval_config(label, algo, cfg, train_stocks, closes, market, pcfg, stop, "train")
        rows.append(row)
        print(f"  [{i+1}/{len(cfgs)}] {label:34s} cagr={row['cagr']:5.1f}% sharpe={row['sharpe']:.2f} "
              f"maxDD={row['maxDD']:6.1f}% calmar={row['calmar']:.2f} nTaken={row['nTaken']} "
              f"hold={row['avgHoldDays']:.0f}d", flush=True)
    bench = rp.benchmark_metrics(closes, pcfg)
    print("\n=== TRAIN RESULTS (ranked by Sharpe) ===")
    df = rp._print_rows(rows, bench)
    out = f"{rp.RESULTS_DIR}\\train_results.csv"
    df.to_csv(out, index=False)
    print(f"\nWritten: {out}")


def refine_configs():
    """Zoom in on the train leaders: Vol-Adjusted Momentum Rider + the explicit default."""
    cfgs = [CURRENT_DEFAULT]
    # Vol-adjusted momentum: push selectivity higher + shorter lookbacks (the lever).
    for ml in (63, 100, 126):
        for thr in (10.0, 12.0, 16.0, 20.0, 25.0):
            cfgs.append((f"VolAdjMom mom={ml} thr={thr}", "Vol-Adjusted Momentum Rider",
                         {"mom_lookback": ml, "score_threshold": thr}, "widest"))
    # Exit-speed + stop variants around the leading 126/16 region.
    for xma in (150, 250):
        cfgs.append((f"VolAdjMom mom=126 thr=16 xMA={xma}", "Vol-Adjusted Momentum Rider",
                     {"mom_lookback": 126, "score_threshold": 16.0, "exit_ma": xma}, "widest"))
    for stop in ("tightest", "widest"):
        for am in (3.0, 6.0):
            cfgs.append((f"VolAdjMom mom=126 thr=16 atr={am} {stop}", "Vol-Adjusted Momentum Rider",
                         {"mom_lookback": 126, "score_threshold": 16.0, "atr_mult": am}, stop))
    # Best TrendRider for confirmation.
    cfgs.append(("TrendRider bl=50 xMA=200 atr=3", "Trend Rider (breakout + MA exit)",
                 {"breakout_lookback": 50, "exit_ma": 200, "trend_ma": 200, "atr_mult": 3.0}, "widest"))
    return cfgs


def refine():
    """Refinement grid on the training stocks (zoom into the leaders)."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    pcfg = PortfolioConfig()
    cfgs = refine_configs()
    print(f"=== REFINE GRID: {len(cfgs)} configs x {len(train_stocks)} stocks ===", flush=True)
    rows = []
    for i, (label, algo, cfg, stop) in enumerate(cfgs):
        row = rp.eval_config(label, algo, cfg, train_stocks, closes, market, pcfg, stop, "train")
        rows.append(row)
        print(f"  [{i+1}/{len(cfgs)}] {label:38s} cagr={row['cagr']:5.1f}% sharpe={row['sharpe']:.2f} "
              f"maxDD={row['maxDD']:6.1f}% calmar={row['calmar']:.2f} nTaken={row['nTaken']} "
              f"hold={row['avgHoldDays']:.0f}d", flush=True)
    bench = rp.benchmark_metrics(closes, pcfg)
    print("\n=== REFINE RESULTS (ranked by Sharpe) ===")
    df = rp._print_rows(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\refine_results.csv", index=False)


def sweep():
    """Portfolio-parameter sweep on the FINALISTS (max_positions, market filter, risk)."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    rows = []
    variants = [
        ("base maxPos=15", dict(max_positions=15, market_filter=False)),
        ("maxPos=10", dict(max_positions=10, market_filter=False)),
        ("maxPos=25", dict(max_positions=25, market_filter=False)),
        ("maxPos=15 +mktFilter", dict(max_positions=15, market_filter=True)),
        ("maxPos=25 +mktFilter", dict(max_positions=25, market_filter=True)),
        ("maxPos=15 risk=2%", dict(max_positions=15, market_filter=False, risk_pct=0.02)),
    ]
    for label, algo, cfg, stop in FINALISTS:
        for vlabel, kw in variants:
            pcfg = PortfolioConfig(**kw)
            row = rp.eval_config(f"{label} | {vlabel}", algo, cfg, train_stocks, closes,
                                 market, pcfg, stop, "train")
            rows.append(row)
            print(f"  {label:30s} {vlabel:22s} cagr={row['cagr']:5.1f}% sharpe={row['sharpe']:.2f} "
                  f"maxDD={row['maxDD']:6.1f}% calmar={row['calmar']:.2f}", flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== PORTFOLIO SWEEP (train, ranked by Sharpe) ===")
    df = rp._print_rows(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\sweep_results.csv", index=False)


# Growth finalists carried to out-of-sample validation. Tuple:
# (label, buy, cfg, stop, sell, sellcfg, maxPos, regime). The regime challengers use
# the SPY-200MA market filter; the current winner (no regime) is the baseline to beat.
MR = "Momentum Rider (ROC + MA exit)"


def _mr(thr):
    return {"mom_lookback": 126, "mom_threshold": thr, "atr_period": 20, "trend_ma": 200}


FINALISTS_GROWTH = [
    ("CURRENT winner MomRider thr=0.30", MR, _mr(0.30), "widest", None, None, 15, False),
    ("MomRider thr=0.25 +regime mp=20", MR, _mr(0.25), "widest", None, None, 20, True),
    ("MomRider thr=0.25 +regime mp=15", MR, _mr(0.25), "widest", None, None, 15, True),
    ("MomRider thr=0.20 +regime mp=20", MR, _mr(0.20), "widest", None, None, 20, True),
    ("MomRider thr=0.30 +regime mp=20", MR, _mr(0.30), "widest", None, None, 20, True),
    ("MomRider thr=0.30 +regime mp=15", MR, _mr(0.30), "widest", None, None, 15, True),
]


def validate():
    """Growth finalists out-of-sample on the 100 unseen TEST stocks vs Buy & Hold."""
    _, test_stocks = rp.build_split()
    closes = rp.load_closes(test_stocks)
    market = rp.load_market_close()
    rows = []
    print(f"=== OOS VALIDATION: {len(FINALISTS_GROWTH)} finalists x {len(test_stocks)} test stocks ===",
          flush=True)
    for label, buy, cfg, stop, sell, sellcfg, mp, regime in FINALISTS_GROWTH:
        pcfg = PortfolioConfig(max_positions=mp)
        row = rp.eval_config(label, buy, cfg, test_stocks, closes, market, pcfg, stop, "test",
                             sell_strategy=sell, sell_config=sellcfg, regime=regime)
        rows.append(row)
        print(f"  {label:36s} cagr={row['cagr']:5.1f}% maxDD={row['maxDD']:6.1f}% "
              f"calmar={row['calmar']:.2f} sharpe={row['sharpe']:.2f}", flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== OOS TEST RESULTS (ranked by CAGR) ===")
    df = _print_growth(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\test_regime_results.csv", index=False)


# ---------------------------------------------------------------------------
# Growth objective: maximize CAGR subject to a max-drawdown ceiling.
# ---------------------------------------------------------------------------

DD_CAP = 40.0   # only configs with maxDD >= -DD_CAP% qualify as "growth winners"


def growth_configs():
    """Growth grid. Each tuple: (label, buy_algo, buy_cfg, stop[, sell_algo, sell_cfg]).

    Includes the champion family (to beat), raw-momentum growth riders, accelerating
    momentum, the trend/breakout riders that showed high OOS CAGR last time, and
    MIXED buy/sell combos (two algorithms in one strategy).
    """
    C = []
    for thr in (8.0, 10.0, 12.0):
        C.append((f"VolAdjMom thr={thr}", "Vol-Adjusted Momentum Rider",
                  {"mom_lookback": 126, "score_threshold": thr}, "widest"))
    for mt in (0.20, 0.30, 0.40):
        for tm in (5.0, 8.0):
            C.append((f"GrowthRider mt={mt} trail={tm}", "Growth Rider (momentum + chandelier)",
                      {"mom_threshold": mt, "trail_atr_mult": tm}, "widest"))
    C.append(("AccelMom 63/252 x150", "Accelerating Momentum Rider",
              {"fast": 63, "slow": 252, "exit_ma": 150}, "widest"))
    C.append(("AccelMom 63/252 x200", "Accelerating Momentum Rider",
              {"fast": 63, "slow": 252, "exit_ma": 200}, "widest"))
    C.append(("MomRider mom=126", "Momentum Rider (ROC + MA exit)",
              {"mom_lookback": 126, "trend_ma": 200}, "widest"))
    C.append(("TrendRider bl=50 xMA=200", "Trend Rider (breakout + MA exit)",
              {"breakout_lookback": 50, "exit_ma": 200, "trend_ma": 200, "atr_mult": 3.0}, "widest"))
    C.append(("Donchian e=200 x=100", "Trend Follower (Donchian)",
              {"entry_lookback": 200, "exit_lookback": 100, "use_trend_filter": 0, "atr_mult": 3.0}, "widest"))
    C.append(("TwoSpeed e=40 x=120", "Two-Speed Donchian",
              {"entry_lookback": 40, "exit_lookback": 120}, "widest"))
    C.append(("TSMom mom=252", "Time-Series Momentum (absolute)",
              {"mom_lookback": 252, "ma_period": 200, "atr_mult": 3.0}, "widest"))
    # Mixed buy/sell — two algorithms in one strategy (entry from one, exit from another).
    C.append(("MIX VolAdj-entry + Chandelier-exit", "Vol-Adjusted Momentum Rider",
              {"mom_lookback": 126, "score_threshold": 10.0}, "widest",
              "Growth Rider (momentum + chandelier)", {"trail_atr_mult": 6.0}))
    C.append(("MIX Growth-entry + 200MA-exit", "Growth Rider (momentum + chandelier)",
              {"mom_threshold": 0.30}, "widest",
              "Momentum Rider (ROC + MA exit)", {"trend_ma": 200}))
    C.append(("MIX Breakout-entry + Chandelier-exit", "Trend Rider (breakout + MA exit)",
              {"breakout_lookback": 50, "trend_ma": 200}, "widest",
              "Growth Rider (momentum + chandelier)", {"trail_atr_mult": 6.0}))
    return C


def _print_growth(rows, bench):
    """Rank by CAGR, flag which meet the drawdown cap, and name the growth winner."""
    df = pd.DataFrame(rows)
    df["ddOK"] = df["maxDD"] >= -DD_CAP            # maxDD is negative; within cap if >= -40
    df = df.sort_values("cagr", ascending=False).reset_index(drop=True)
    show = ["strategy", "maxPos", "cagr", "maxDD", "calmar", "sharpe", "totRet",
            "nTaken", "avgHoldDays", "ddOK"]
    print(df[show].to_string(index=False))
    print(f"\n  BENCHMARK Buy&Hold: cagr={bench['cagr']*100:.1f}% maxDD={bench['max_dd']*100:.1f}% "
          f"sharpe={bench['sharpe']:.2f} calmar={bench['calmar']:.2f}")
    capped = df[df["ddOK"]]
    if not capped.empty:
        w = capped.iloc[0]
        print(f"\n>>> GROWTH WINNER (max CAGR within maxDD<= {DD_CAP}%): {w['strategy']}")
        print(f"    CAGR={w['cagr']}%  maxDD={w['maxDD']}%  Calmar={w['calmar']}  Sharpe={w['sharpe']}  "
              f"trades={w['nTaken']}  avgHold={w['avgHoldDays']}d")
    return df


def growth():
    """Growth grid on the 300 train stocks, ranked by CAGR under the drawdown cap."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    cfgs = growth_configs()
    print(f"=== GROWTH GRID: {len(cfgs)} configs x (maxPos 15,20) x {len(train_stocks)} stocks ===",
          flush=True)
    rows = []
    for i, tup in enumerate(cfgs):
        label, buy, cfg, stop = tup[0], tup[1], tup[2], tup[3]
        sell = tup[4] if len(tup) > 4 else None
        sellcfg = tup[5] if len(tup) > 5 else None
        for mp in (15, 20):
            pcfg = PortfolioConfig(max_positions=mp)
            r = rp.eval_config(f"{label} | mp={mp}", buy, cfg, train_stocks, closes, market,
                               pcfg, stop, "train", sell_strategy=sell, sell_config=sellcfg)
            rows.append(r)
            print(f"  [{i+1}/{len(cfgs)}] {label:34s} mp={mp} cagr={r['cagr']:5.1f}% "
                  f"maxDD={r['maxDD']:6.1f}% calmar={r['calmar']:.2f} hold={r['avgHoldDays']:.0f}d",
                  flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== GROWTH RESULTS (ranked by CAGR) ===")
    df = _print_growth(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\growth_results.csv", index=False)


def refine_growth_configs():
    """Zoom into the growth leader: VolAdj-momentum ENTRY + chandelier EXIT, tuning
    the chandelier width (the main drawdown lever) to pull maxDD under the cap while
    keeping the high CAGR. Tuple: (label, buy, cfg, stop[, sell, sellcfg])."""
    C = []
    for thr in (10.0, 12.0):
        for trail in (3.0, 4.0, 5.0, 6.0):
            C.append((f"MIX VolAdj{int(thr)}+Chand{trail}", "Vol-Adjusted Momentum Rider",
                      {"mom_lookback": 126, "score_threshold": thr}, "widest",
                      "Growth Rider (momentum + chandelier)",
                      {"trail_atr_mult": trail, "trail_atr_period": 22}))
    for trail in (4.0, 5.0):        # tighter catastrophe stop variant
        C.append((f"MIX VolAdj10+Chand{trail} tight", "Vol-Adjusted Momentum Rider",
                  {"mom_lookback": 126, "score_threshold": 10.0}, "tightest",
                  "Growth Rider (momentum + chandelier)", {"trail_atr_mult": trail}))
    C.append(("MIX Growth+200MA", "Growth Rider (momentum + chandelier)",
              {"mom_threshold": 0.30}, "widest",
              "Momentum Rider (ROC + MA exit)", {"trend_ma": 200}))
    return C


def refine_growth():
    """Refine the growth leader (mixed VolAdj-entry + chandelier-exit) on train stocks."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    cfgs = refine_growth_configs()
    print(f"=== REFINE-GROWTH: {len(cfgs)} configs x (maxPos 12,15,20) x {len(train_stocks)} ===",
          flush=True)
    rows = []
    for i, tup in enumerate(cfgs):
        label, buy, cfg, stop = tup[0], tup[1], tup[2], tup[3]
        sell = tup[4] if len(tup) > 4 else None
        sellcfg = tup[5] if len(tup) > 5 else None
        for mp in (12, 15, 20):
            pcfg = PortfolioConfig(max_positions=mp)
            r = rp.eval_config(f"{label} | mp={mp}", buy, cfg, train_stocks, closes, market,
                               pcfg, stop, "train", sell_strategy=sell, sell_config=sellcfg)
            rows.append(r)
            print(f"  [{i+1}/{len(cfgs)}] {label:28s} mp={mp} cagr={r['cagr']:5.1f}% "
                  f"maxDD={r['maxDD']:6.1f}% calmar={r['calmar']:.2f} sharpe={r['sharpe']:.2f}", flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== REFINE-GROWTH RESULTS (ranked by CAGR) ===")
    df = _print_growth(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\refine_growth_results.csv", index=False)


def regime_grid():
    """Beat the current winner: sweep entry aggressiveness (lower momentum threshold /
    more positions) WITH and WITHOUT the SPY-200MA regime filter (go to cash in bear
    markets). The regime filter should cut drawdowns, letting a more aggressive entry
    lift CAGR while staying under the ~40% drawdown cap."""
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    thresholds = (0.15, 0.20, 0.25, 0.30, 0.40)
    combos = [(thr, rg) for thr in thresholds for rg in (False, True)]
    print(f"=== REGIME GRID: {len(combos)} (thr,regime) x mp(15,20) x {len(train_stocks)} stocks ===",
          flush=True)
    rows = []
    for thr, regime in combos:
        cfg = {"mom_lookback": 126, "mom_threshold": thr, "atr_period": 20, "trend_ma": 200}
        tag = f"MomRider thr={thr}{' +regime' if regime else ''}"
        for mp in (15, 20):
            pcfg = PortfolioConfig(max_positions=mp)
            r = rp.eval_config(f"{tag} | mp={mp}", "Momentum Rider (ROC + MA exit)", cfg,
                               train_stocks, closes, market, pcfg, "widest", "train", regime=regime)
            rows.append(r)
            print(f"  {tag:28s} mp={mp} cagr={r['cagr']:5.1f}% maxDD={r['maxDD']:6.1f}% "
                  f"calmar={r['calmar']:.2f} sharpe={r['sharpe']:.2f}", flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== REGIME GRID RESULTS (ranked by CAGR) ===")
    df = _print_growth(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\regime_results.csv", index=False)


def squeeze_grid():
    """The owner's combined BUY idea: squeeze breakout + momentum + anti-overextension.

    Grid: bandwidth (0.15, 0.20) x mom_threshold (0.10, 0.15, 0.25) x max_ext
    (0.40, 0.60, off) at maxPos=20, vs the current production winner as baseline.
    ext=9.99 disables the cap so the cap's own effect is measurable. Ranked by CAGR
    under the <=40% drawdown cap.
    """
    train_stocks, _ = rp.build_split()
    closes = rp.load_closes(train_stocks)
    market = rp.load_market_close()
    rows = []
    baseline_cfg = {"mom_lookback": 126, "mom_threshold": 0.25, "atr_period": 20, "trend_ma": 200}
    pcfg20 = PortfolioConfig(max_positions=20)
    r = rp.eval_config("BASELINE MomRider thr=0.25 mp=20", "Momentum Rider (ROC + MA exit)",
                       baseline_cfg, train_stocks, closes, market, pcfg20, "widest", "train")
    rows.append(r)
    print(f"  BASELINE cagr={r['cagr']:5.1f}% maxDD={r['maxDD']:6.1f}% calmar={r['calmar']:.2f}",
          flush=True)

    grid = [(bw, mt, ext)
            for bw in (0.15, 0.20)
            for mt in (0.10, 0.15, 0.25)
            for ext in (0.40, 0.60, 9.99)]
    print(f"=== SQUEEZE GRID: {len(grid)} configs x maxPos=20 x {len(train_stocks)} stocks ===",
          flush=True)
    for i, (bw, mt, ext) in enumerate(grid):
        cfg = {"bandwidth_threshold": bw, "mom_threshold": mt, "max_ext": ext}
        label = f"SqzMom bw={bw} mom={mt} ext={'off' if ext > 9 else ext}"
        r = rp.eval_config(label, "Squeeze Momentum Breakout", cfg, train_stocks, closes,
                           market, pcfg20, "widest", "train")
        rows.append(r)
        print(f"  [{i+1}/{len(grid)}] {label:34s} cagr={r['cagr']:5.1f}% maxDD={r['maxDD']:6.1f}% "
              f"calmar={r['calmar']:.2f} sharpe={r['sharpe']:.2f} nTaken={r['nTaken']} "
              f"hold={r['avgHoldDays']:.0f}d", flush=True)
    bench = rp.benchmark_metrics(closes, PortfolioConfig())
    print("\n=== SQUEEZE GRID RESULTS (ranked by CAGR) ===")
    df = _print_growth(rows, bench)
    df.to_csv(f"{rp.RESULTS_DIR}\\squeeze_results.csv", index=False)


DISPATCH = {"split": split, "smoke": smoke, "train": train, "refine": refine,
            "sweep": sweep, "validate": validate, "growth": growth,
            "refine_growth": refine_growth, "regime": regime_grid,
            "squeeze": squeeze_grid}


def main(argv):
    phase = argv[0] if argv else "smoke"
    if phase not in DISPATCH:
        print("usage: python research_grids.py", "|".join(DISPATCH))
        sys.exit(1)
    DISPATCH[phase]()


if __name__ == "__main__":
    main(sys.argv[1:])
