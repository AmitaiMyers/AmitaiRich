"""Data coverage report: how complete and point-in-time is the research data, year by year?

    python data_coverage.py           # -> reports/data/coverage.md (+ chart)

Measures, for each year, the average day's historical S&P 500 membership and how much of it the
research can actually see: members with Yahoo prices (the rest are mostly delisted/acquired —
the remaining survivorship bias), and among priced members the share with a known EPS surprise
(Yahoo) and with EDGAR growth data. Coverage is metadata, not outcomes, so it may show recent years.
"""

import os

import matplotlib
import pandas as pd

import factors
import fundamental_factors
import market_data
import universe_history

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT_DIR = os.path.join("reports", "data")


def run():
    members_ever = universe_history.sp500_members_since("2004-01-01")
    frames = market_data.load_prices(members_ever + ["SPY"])
    panel = factors.Panel(frames, start="2004-01-01")
    fundamental = fundamental_factors.build_all(panel)
    snapshots = universe_history.sp500_snapshots()
    rows = snapshots["tickers"].reindex(panel.dates, method="ffill")
    priced = set(panel.tickers)
    member_matrix = universe_history.member_matrix(panel.dates, list(panel.tickers))
    has_price = panel.close.notna() & member_matrix

    yearly = []
    for year in sorted(set(panel.dates.year)):
        days = panel.dates[panel.dates.year == year]
        total = pd.Series([len(rows.loc[d]) for d in days]).mean()
        listed = rows.loc[days].map(lambda members: len(members & priced)).mean()
        with_bars = has_price.loc[days].sum(axis=1).mean()
        surprise = (fundamental["eps_surprise"].loc[days].notna() & has_price.loc[days]).sum(axis=1).mean()
        growth = (fundamental["rev_growth_yoy"].loc[days].notna() & has_price.loc[days]).sum(axis=1).mean()
        yearly.append({"year": year, "members": round(total), "priced": round(with_bars),
                       "priced_%": round(with_bars / total * 100, 1),
                       "eps_surprise_%": round(surprise / with_bars * 100, 1),
                       "edgar_growth_%": round(growth / with_bars * 100, 1),
                       "symbols_known": round(listed)})
    table = pd.DataFrame(yearly)
    missing = sorted(set(members_ever) - priced)
    write(table, missing, len(members_ever))
    return table


def write(table, missing, n_members):
    os.makedirs(OUT_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    for column, color in (("priced_%", "#1f6feb"), ("eps_surprise_%", "#0f8a4a"), ("edgar_growth_%", "#e39b3c")):
        ax.plot(table["year"], table[column], marker="o", ms=3, label=column.replace("_%", " %"), color=color)
    ax.set_ylim(0, 105)
    ax.set_ylabel("% coverage")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "coverage.png"), dpi=130)
    plt.close(fig)

    lines = [
        "# Data coverage — how much of the point-in-time S&P 500 can the research see?", "",
        f"{n_members} different companies were S&P 500 members at some point since 2004; "
        f"{n_members - len(missing)} have Yahoo price history, {len(missing)} do not "
        "(almost all delisted or acquired — the survivorship bias that remains).", "",
        "![coverage](coverage.png)", "",
        "- **priced %** — of the day's index members, how many have price data (the rest are invisible "
        "to the backtest; they were disproportionately the companies that later failed or were bought).",
        "- **eps surprise %** — of priced members, how many have a known consensus-vs-reported EPS surprise "
        "(Yahoo, ~2005+) from the last 200 days.",
        "- **edgar growth %** — of priced members, how many have point-in-time YoY revenue growth from SEC "
        "filings (machine-readable filings start 2009-2011).", "",
        "| Year | Members | Priced | Priced % | EPS surprise % | EDGAR growth % |",
        "|---|---|---|---|---|---|",
    ]
    for row in table.itertuples(index=False):
        lines.append(f"| {row.year} | {row.members} | {row.priced} | {row[3]} | {row[4]} | {row[5]} |")
    lines += ["", "## Implication", "",
              "Results on early years are biased upward (missing members skew toward failures). The "
              "paid fix is Norgate Data (all delisted US stocks + historical index membership, about "
              "US$30–60/month); see GOAL_SPEC.md. Fundamental factors can only be judged where coverage "
              "is high — growth factors effectively from ~2011.", "",
              "Missing symbols (first 120): " + ", ".join(missing[:120])]
    with open(os.path.join(OUT_DIR, "coverage.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Written {os.path.join(OUT_DIR, 'coverage.md')}")


if __name__ == "__main__":
    run()
