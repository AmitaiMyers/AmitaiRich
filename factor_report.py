"""Factor report (the 'edge finder', capability 10): which factors predict next-month returns?

    python factor_report.py            # -> reports/factors/factor_report.md (+ charts, JSON)

Method (no look-ahead, holdout locked):
  * universe each month-end = point-in-time S&P 500 members with a price > $5 and 20-day
    average dollar volume > $5M (stocks the strategy could really trade);
  * forward return = next open -> open 21 trading days later (decide at the close, buy the next open);
  * Rank IC = Spearman correlation between the factor and the forward return across stocks,
    per month; reported as the mean, t-stat (mean / std * sqrt(months)) and hit rate;
  * top-quintile edge = average forward return of the best 20% minus the universe average,
    annualized (what a long-only buyer of that factor would gain);
  * development (2005-2018) and validation (2019-2022) side by side; the holdout is never read.
"""

import json
import os

import matplotlib
import numpy as np
import pandas as pd

import factors
import fundamental_factors
import market_data
import periods
import universe_history

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

OUT_DIR = os.path.join("reports", "factors")
PANEL_START = "2003-01-01"
FORWARD_BARS = 21
HORIZONS = (21, 63)   # 1-month and 3-month forward returns
MIN_STOCKS = 50
MIN_PRICE, MIN_DOLLAR_VOLUME = 5.0, 5e6


def core_frames():
    """Prices for every historical S&P 500 member since 2004 that has history, plus SPY."""
    tickers = universe_history.sp500_members_since() + ["SPY"]
    return market_data.load_prices(tickers)


def eligibility(panel):
    """Point-in-time member AND liquid AND priced — the stocks that could be traded that day."""
    members = universe_history.member_matrix(panel.dates, list(panel.tickers))
    dollar_volume = (panel.close * panel.volume).rolling(20, min_periods=20).mean()
    liquid = (panel.close > MIN_PRICE) & (dollar_volume > MIN_DOLLAR_VOLUME)
    return members & liquid & panel.close.notna()


def month_ends(dates, start, end):
    in_window = dates[(dates >= start) & (dates <= end)]
    series = pd.Series(in_window, index=in_window)
    return pd.DatetimeIndex(series.groupby([in_window.year, in_window.month]).max().to_numpy())


def forward_returns(panel, bars=FORWARD_BARS):
    """Return from the NEXT open to the open `bars` later (aligned to the decision date)."""
    entry = panel.open.shift(-1)
    exit_ = panel.open.shift(-(bars + 1))
    return exit_ / entry - 1.0


def _rank_ic(scores, returns, eligible):
    """Per-date Spearman IC over eligible stocks with both a score and a return."""
    ics = {}
    for date in scores.index:
        mask = eligible.loc[date] & scores.loc[date].notna() & returns.loc[date].notna()
        if mask.sum() < MIN_STOCKS:
            continue
        s = scores.loc[date][mask].rank()
        r = returns.loc[date][mask].rank()
        ics[date] = float(np.corrcoef(s, r)[0, 1])
    return pd.Series(ics, dtype=float)


def _top_edge(scores, returns, eligible, quantile):
    """Average forward return of stocks scoring above `quantile` minus the universe average."""
    edges = {}
    for date in scores.index:
        mask = eligible.loc[date] & scores.loc[date].notna() & returns.loc[date].notna()
        if mask.sum() < MIN_STOCKS:
            continue
        s, r = scores.loc[date][mask], returns.loc[date][mask]
        top = r[s >= s.quantile(quantile)]
        edges[date] = float(top.mean() - r.mean())
    return pd.Series(edges, dtype=float)


def summarize(ics, quintile, decile, ics_3m, decile_3m, coverage):
    months = len(ics)
    if months < 12:
        raise ValueError(f"Only {months} months with >= {MIN_STOCKS} scored stocks; too few to judge a factor.")
    t_stat = ics.mean() / ics.std() * np.sqrt(months)
    # 3-month forward windows overlap month to month, so the 3-month t-stat is deflated by sqrt(3).
    t_3m = ics_3m.mean() / ics_3m.std() * np.sqrt(len(ics_3m) / 3)
    return {"months": months, "mean_ic": round(float(ics.mean()), 4), "t_stat": round(float(t_stat), 2),
            "hit_rate": round(float((ics > 0).mean()) * 100, 1),
            "top_q_edge_ann": round(float(quintile.mean()) * 12 * 100, 2),
            "top_d_edge_ann": round(float(decile.mean()) * 12 * 100, 2),
            "ic_3m": round(float(ics_3m.mean()), 4), "t_3m": round(float(t_3m), 2),
            "top_d_edge_3m_ann": round(float(decile_3m.mean()) * 4 * 100, 2),
            "coverage": round(coverage * 100, 1)}


def evaluate_factor(scores, returns_by_horizon, eligible, dates):
    sampled = scores.reindex(dates)
    elig = eligible.reindex(dates)
    r1, r3 = (returns_by_horizon[h].reindex(dates) for h in HORIZONS)
    summary = summarize(_rank_ic(sampled, r1, elig), _top_edge(sampled, r1, elig, 0.8),
                        _top_edge(sampled, r1, elig, 0.9), _rank_ic(sampled, r3, elig),
                        _top_edge(sampled, r3, elig, 0.9),
                        float((sampled.notna() & elig).sum().sum() / max(elig.sum().sum(), 1)))
    return summary, sampled


def correlation_matrix(sampled_by_factor, eligible, dates):
    """Average cross-sectional rank correlation between factors (redundancy check)."""
    names = list(sampled_by_factor)
    matrix = pd.DataFrame(np.nan, index=names, columns=names)
    ranks = {n: f.where(eligible.reindex(dates)).rank(axis=1, pct=True) for n, f in sampled_by_factor.items()}
    for a in names:
        for b in names:
            per_date = ranks[a].corrwith(ranks[b], axis=1)
            matrix.loc[a, b] = per_date.mean()
    return matrix.round(2)


def run(with_fundamentals=True):
    frames = core_frames()
    panel = factors.Panel(frames, start=PANEL_START)
    if with_fundamentals:
        fundamental_factors.build_all(panel)
    eligible = eligibility(panel)
    returns = {h: forward_returns(panel, h) for h in HORIZONS}
    windows = {name: periods.research_window(name) for name in ("development", "validation")}
    dates = {}
    for name, (start, end) in windows.items():
        sample = month_ends(panel.dates, start, end)
        # Keep only decisions whose whole forward window (exit = FORWARD_BARS + 1 bars later)
        # ends inside the same period: development never peeks at validation, and validation
        # never reaches the locked holdout.
        exit_pos = panel.dates.searchsorted(sample) + max(HORIZONS) + 1
        inside = exit_pos < len(panel.dates)
        sample = sample[inside]
        exits = panel.dates[exit_pos[inside]]
        sample = sample[exits <= end]
        periods.assert_before_holdout(panel.dates[panel.dates.searchsorted(sample[-1]) + max(HORIZONS) + 1])
        dates[name] = sample

    rows, sampled_dev = [], {}
    for factor in factors.FACTORS.values():
        scores = factor.compute(panel)
        row = {"factor": factor.name, "group": factor.group, "meaning": factor.meaning, "formula": factor.formula}
        for name, sample in dates.items():
            summary, sampled = evaluate_factor(scores, returns, eligible, sample)
            row[name] = summary
            if name == "development":
                sampled_dev[factor.name] = sampled
        rows.append(row)
        d, v = row["development"], row["validation"]
        print(f"  {factor.name:16s} dev IC1m {d['mean_ic']:+.4f} t {d['t_stat']:+.2f} | IC3m {d['ic_3m']:+.4f} "
              f"t {d['t_3m']:+.2f} topD3m {d['top_d_edge_3m_ann']:+.1f}%/y | val IC1m {v['mean_ic']:+.4f} "
              f"IC3m {v['ic_3m']:+.4f} topD3m {v['top_d_edge_3m_ann']:+.1f}%/y", flush=True)
    corr = correlation_matrix(sampled_dev, eligible, dates["development"])
    write_report(rows, corr, eligible, dates)
    return rows, corr


def _verdict(dev, val):
    """EDGE: significant in development (1- or 3-month) AND the same sign in validation."""
    for ic, t, val_ic in (("mean_ic", "t_stat", "mean_ic"), ("ic_3m", "t_3m", "ic_3m")):
        if dev[ic] > 0.01 and dev[t] > 2:
            return "EDGE (holds out-of-sample)" if val[val_ic] > 0 else "fragile (dev only)"
    for ic, t in (("mean_ic", "t_stat"), ("ic_3m", "t_3m")):
        if dev[ic] < -0.01 and dev[t] < -2:
            return "inverse (high score = worse)"
    return "noise"


def write_report(rows, corr, eligible, dates):
    os.makedirs(OUT_DIR, exist_ok=True)
    for row in rows:
        row["verdict"] = _verdict(row["development"], row["validation"])
    ordered = sorted(rows, key=lambda r: r["development"]["ic_3m"], reverse=True)

    names = [r["factor"] for r in ordered]
    dev_ic = [r["development"]["ic_3m"] for r in ordered]
    val_ic = [r["validation"]["ic_3m"] for r in ordered]
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(8, max(4, len(names) * 0.32)))
    ax.barh(y + 0.2, dev_ic, height=0.4, label="development 2005-18", color="#1f6feb")
    ax.barh(y - 0.2, val_ic, height=0.4, label="validation 2019-22", color="#e39b3c")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.axvline(0, color="#888", lw=0.8)
    ax.set_xlabel("mean rank IC vs 3-month forward return (higher = better predictor)")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "factor_ic.png"), dpi=130)
    plt.close(fig)

    lines = [
        "# Factor report — which signals predict next-month returns?", "",
        f"Universe: point-in-time S&P 500 members, price > ${MIN_PRICE:.0f}, 20-day dollar volume > "
        f"${MIN_DOLLAR_VOLUME / 1e6:.0f}M (median {int(eligible.reindex(dates['development']).sum(axis=1).median())} "
        f"stocks per month). Forward return: next open → open {FORWARD_BARS} bars later. Holdout (2023+) not used.",
        "", "![factor IC](factor_ic.png)", "",
        "**How to read:** *IC* = how well the factor's ranking predicts the ranking of forward returns "
        "(0 = no skill; 0.02–0.05 is a useful real-world edge). *t* > 2 = unlikely to be luck "
        "(3-month t is corrected for overlapping windows). *Top-10% edge* = yearly return of the best "
        "10% by the factor minus the average stock — what a ~20-stock buyer of that factor would gain. "
        "*EDGE* = significant in development AND the same direction in validation.", "",
        "| Factor | Group | Dev IC 1m (t) | Dev IC 3m (t) | Dev top-10% edge %/yr (3m) | Val IC 1m | Val IC 3m | "
        "Val top-10% edge %/yr (3m) | Coverage % | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in ordered:
        d, v = r["development"], r["validation"]
        lines.append(f"| {r['factor']} | {r['group']} | {d['mean_ic']:+.4f} ({d['t_stat']:+.1f}) | "
                     f"{d['ic_3m']:+.4f} ({d['t_3m']:+.1f}) | {d['top_d_edge_3m_ann']:+.1f} | "
                     f"{v['mean_ic']:+.4f} | {v['ic_3m']:+.4f} | {v['top_d_edge_3m_ann']:+.1f} | "
                     f"{d['coverage']} | {r['verdict']} |")
    lines += ["", "## What each factor measures", ""]
    for r in ordered:
        lines.append(f"- **{r['factor']}** — {r['meaning']} `{r['formula']}`")
    lines += ["", "## Redundancy: average rank correlation between factors (development)", "",
              "Pairs above ~0.7 measure nearly the same thing; combining them adds little.", "",
              "| | " + " | ".join(corr.columns) + " |", "|---|" + "---|" * len(corr.columns)]
    for name, row in corr.iterrows():
        lines.append(f"| {name} | " + " | ".join(f"{x:.2f}" for x in row) + " |")
    with open(os.path.join(OUT_DIR, "factor_report.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(OUT_DIR, "factor_report.json"), "w") as fh:
        json.dump({"rows": ordered, "correlation": corr.to_dict()}, fh, indent=1, default=str)
    print(f"Written {os.path.join(OUT_DIR, 'factor_report.md')}")


if __name__ == "__main__":
    run()
