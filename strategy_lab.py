"""Strategy lab — run, compare and dissect algorithm versions (capabilities 1-10 of the plan).

    python strategy_lab.py run v1            # development + validation report for one version
    python strategy_lab.py compare v0 v1     # side-by-side table
    python strategy_lab.py sell v1           # SELL-rule tournament (same buys, different exits)
    python strategy_lab.py ablate v1         # which factors/filters actually add return
    python strategy_lab.py regime v1         # behaviour by market regime
    python strategy_lab.py montecarlo v1     # resampled outcomes: stable or fragile?
    python strategy_lab.py controls          # sanity check: random portfolios must track RSP
    python strategy_lab.py holdout v3 "reason"   # the ONE-TIME final test (logged in ALGO_LOG.md)

Every run uses point-in-time S&P 500 membership, point-in-time fundamentals, next-open fills,
10 bps/side, $32,000 starting capital (GOAL_SPEC.md), and is reported as development
(2005-2018) vs validation (2019-2022) side by side against SPY and RSP (equal-weight S&P 500).
The holdout (2023+) is refused unless `holdout` is used.
"""

import json
import os
import sys
from dataclasses import replace

import matplotlib
import numpy as np
import pandas as pd

import factors
import fundamental_factors
import indicators
import market_data
import periods
import universe_history
from algo_versions import VERSIONS
from algorithms import Signals, build_algorithm
from portfolio import PortfolioConfig, equity_metrics, run_portfolio, single_asset_benchmark

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PANEL_START = "2003-01-01"
CAPITAL = 32_000.0
COST_BPS = 10.0
MIN_PRICE, MIN_DOLLAR_VOLUME = 5.0, 5e6
REPORT_DIR = os.path.join("reports", "versions")
WINDOWS = ("development", "validation")
SWING_LOOKBACK, STOP_ATR = 20, 20


# ---------------------------------------------------------------------------
# Data shared by every version (built once per process)
# ---------------------------------------------------------------------------

class LabData:
    def __init__(self, universe="core"):
        tickers = universe_history.sp500_members_since()
        extended = set()
        if universe == "extended":
            for names in universe_history.extended_lists().values():
                extended |= set(names)
            tickers = list(dict.fromkeys(tickers + sorted(extended)))
        frames = market_data.load_prices(tickers + ["SPY"])
        self.frames = {t: f[f.index >= PANEL_START] for t, f in frames.items()}
        self.panel = factors.Panel(self.frames)
        fundamental_factors.build_all(self.panel)
        p = self.panel
        member = universe_history.member_matrix(p.dates, list(p.tickers))
        if extended:
            member = member | pd.DataFrame({t: t in extended for t in p.tickers}, index=p.dates)
        dollar_volume = (p.close * p.volume).rolling(20, min_periods=20).mean()
        self.eligible = member & (p.close > MIN_PRICE) & (dollar_volume > MIN_DOLLAR_VOLUME) & p.close.notna()
        self.eligible["SPY"] = False
        self.market_up = factors.market_uptrend(p)
        self.stock_frames = {t: f for t, f in self.frames.items() if t != "SPY"}
        self.benchmarks = {t: f["Close"] for t, f in market_data.load_prices(["SPY", "RSP"]).items()}
        self._factors = {}

    def factor(self, name):
        if name not in self._factors:
            self._factors[name] = factors.FACTORS[name].compute(self.panel)
        return self._factors[name]

    def ic_history(self, name):
        """Monthly rank IC of a factor vs the next-month return, with the date each IC became KNOWN
        (decision month-end + 22 bars: the forward return must have finished)."""
        key = ("ic", name)
        if key not in self._factors:
            import factor_report

            dates = self.panel.dates
            month_ends = factor_report.month_ends(dates, dates[0], dates[-1])
            returns = factor_report.forward_returns(self.panel, 21)
            ics = factor_report._rank_ic(self.factor(name).reindex(month_ends), returns.reindex(month_ends),
                                         self.eligible.reindex(month_ends))
            position = dates.searchsorted(ics.index) + 22
            valid = position < len(dates)
            self._factors[key] = pd.DataFrame({"ic": ics.to_numpy()[valid],
                                               "known": dates[position[valid]]}, index=ics.index[valid])
        return self._factors[key]

    def adaptive_weights(self, names, rows, months):
        """rows x factors weights: each factor's mean IC over the last `months` months whose
        outcome was already known on that row's date, floored at 0 (a factor that has not been
        working gets no weight). Causal: only completed forward windows are used."""
        weights = np.zeros((len(rows), len(names)))
        for j, name in enumerate(names):
            history = self.ic_history(name)
            for i, date in enumerate(rows):
                usable = history[(history["known"] <= date) & (history.index >= date - pd.DateOffset(months=months))]
                if len(usable) >= 12:
                    weights[i, j] = max(float(usable["ic"].mean()), 0.0)
        return weights


_DATA = {}


def lab_data(universe):
    if universe not in _DATA:
        print(f"loading {universe} universe ...", flush=True)
        _DATA[universe] = LabData(universe)
    return _DATA[universe]


# ---------------------------------------------------------------------------
# Filters and exits (all dates x tickers boolean panels, causal)
# ---------------------------------------------------------------------------

def _broadcast(series, like):
    return pd.DataFrame(np.repeat(series.to_numpy()[:, None], like.shape[1], axis=1),
                        index=like.index, columns=like.columns)


FILTERS = {
    "market_up": lambda d, on: _broadcast(d.market_up, d.panel.close) if on else None,
    "stock_above_ma": lambda d, n: d.panel.close > factors.sma(d.panel.close, n),
    "min_mom_6m": lambda d, x: factors.roc(d.panel.close, 126) > x,
    "beat_last": lambda d, on: d.factor("eps_surprise") >= 0 if on else None,
    "growth_consistent": lambda d, k: d.factor("rev_consistency") >= k,
    "beats_market": lambda d, on: factors.relative_strength(d.panel) > 0 if on else None,
    "adx_min": lambda d, x: factors.adx_parts(d.panel)[0] > x,
}


def _ma_break(d, n, confirm):
    below = (d.panel.close < factors.sma(d.panel.close, n)).astype("float32")
    return below.rolling(confirm, min_periods=confirm).min() == 1.0


def _earnings_miss(d):
    surprise = d.factor("eps_surprise")
    return (surprise < 0) & (surprise != surprise.shift(1))


def _adx_weak(d):
    adx, plus_di, minus_di = factors.adx_parts(d.panel)
    return (adx < 20) & (minus_di > plus_di)


def _obv_weak(d):
    return (d.factor("obv_trend") < 0) & (d.panel.close < factors.sma(d.panel.close, 50))


def rebalance_days(dates, frequency):
    if frequency == "daily":
        return pd.Series(True, index=dates)
    keys = dates.to_period("W-FRI" if frequency == "weekly" else "M")
    last = pd.Series(dates, index=dates).groupby(keys).transform("max")
    return pd.Series(dates == last.to_numpy(), index=dates)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _stop_parts(history, atr_mult):
    close, high, low = history["Close"], history["High"], history["Low"]
    return {"stop_levels": (indicators.recent_swing_low(low, SWING_LOOKBACK).to_numpy(dtype=float),),
            "stop_atr": indicators.atr(high, low, close, STOP_ATR).to_numpy(dtype=float),
            "stop_atr_mult": float(atr_mult)}


def _column(frame, ticker, index, default):
    return frame[ticker].reindex(index, fill_value=default).to_numpy()


class RankedStrategy:
    """Composite-score ranking -> top-N buys on rebalance days -> configured exits."""

    def __init__(self, version, data):
        self.name = version.name
        self.version = version
        d = data
        rebalance = rebalance_days(d.panel.dates, version.rebalance)
        self.composite = self._composite(version, d, rebalance)
        candidates = d.eligible & self.composite.notna()
        for name, param in version.filters.items():
            mask = FILTERS[name](d, param)
            if mask is not None:
                candidates &= mask
        rank = self.composite.where(candidates).rank(axis=1, ascending=False)
        # The list chosen at a rebalance stays valid until the next one: a slot freed by a sell
        # (sells fill the morning after the rebalance, because BUYs are decided before SELLs) is
        # refilled from the current top-N on the following days — exactly how the owner acts on
        # the published list. (Allowing buys ONLY on the rebalance day left freed cash idle for a
        # whole period: v1-v3 were only ~70% invested.) Ranks are known at the rebalance close,
        # so carrying them forward is causal. On the buy day the stock must STILL pass every buy
        # filter and must not be triggering a sell rule — otherwise a stock sold for breaking its
        # MA would be re-bought from the frozen list the next morning (a churn loop).
        on_list = (rank <= version.max_positions).where(_broadcast(rebalance, rank)).ffill()
        self.exit = self._exits(version, d, rebalance)
        self.entry = (on_list == 1.0) & candidates & ~self.exit
        e = version.exits
        self.trail = factors.atr(d.panel, 22) if "trail_atr" in e else None
        self.max_hold = e["time_stop"] if "time_stop" in e else None

    def _composite(self, version, d, rebalance):
        """Weighted average of percentile ranks over the factors each stock HAS on that day.

        A stock missing a fundamental is scored on the rest (weights renormalized); it needs at
        least half of the total weight to be scored at all.
        """
        rows = rebalance[rebalance].index
        eligible = d.eligible.loc[rows]
        names = list(version.weights)
        if version.adaptive:
            row_weights = d.adaptive_weights(names, rows, version.adaptive_months)     # rows x factors
        else:
            row_weights = np.tile([version.weights[n] for n in names], (len(rows), 1)).astype(float)
        pcts = np.stack([d.factor(n).loc[rows].where(eligible).rank(axis=1, pct=True).to_numpy() for n in names])
        known = ~np.isnan(pcts)                                                    # factors x rows x tickers
        w = row_weights.T[:, :, None]                                              # factors x rows x 1
        total = np.sum(np.where(known, pcts, 0.0) * w, axis=0)
        seen = np.sum(known * w, axis=0)
        needed = 0.5 * row_weights.sum(axis=1)[:, None]
        enough = (seen >= needed) & (needed > 0)
        composite = np.where(enough, total / np.where(enough, seen, 1.0), np.nan)
        return pd.DataFrame(composite, index=rows, columns=d.panel.tickers).reindex(d.panel.dates).ffill()

    def _exits(self, version, d, rebalance):
        e = version.exits
        exit_ = pd.DataFrame(False, index=d.panel.dates, columns=d.panel.tickers)
        if "ma_break" in e:
            exit_ |= _ma_break(d, e["ma_break"], e["ma_confirm"] if "ma_confirm" in e else 1)
        if "rank_drop" in e:
            rank_all = self.composite.where(d.eligible).rank(axis=1, ascending=False)
            dropped = (rank_all > version.hold_buffer * version.max_positions) | ~d.eligible
            exit_ |= dropped & _broadcast(rebalance, dropped)
        if "earnings_miss" in e:
            exit_ |= _earnings_miss(d)
        if "adx_weak" in e:
            exit_ |= _adx_weak(d)
        if "obv_weak" in e:
            exit_ |= _obv_weak(d)
        if "market_down" in e:
            exit_ |= _broadcast(~d.market_up, exit_)
        return exit_

    def warmup_bars(self):
        return 1

    def signals_for(self, ticker, history):
        index = history.index
        return Signals(
            entry=_column(self.entry, ticker, index, False).astype(bool),
            exit=_column(self.exit, ticker, index, False).astype(bool),
            score=_column(self.composite, ticker, index, np.nan).astype(float),
            trail_atr=None if self.trail is None else _column(self.trail, ticker, index, np.nan).astype(float),
            trail_mult=float(self.version.exits["trail_atr"]) if self.trail is not None else 0.0,
            max_hold=self.max_hold,
            **_stop_parts(history, self.version.atr_mult))


class EligibleOnly:
    """An algorithms.py strategy that may only BUY point-in-time eligible stocks (for v0)."""

    def __init__(self, algorithm, data, name):
        self.algorithm, self.data, self.name = algorithm, data, name

    def warmup_bars(self):
        return self.algorithm.warmup_bars()

    def signals_for(self, ticker, history):
        built = self.algorithm.signals(history)
        allowed = _column(self.data.eligible, ticker, history.index, False).astype(bool)
        return replace(built, entry=built.entry & allowed)


def build_strategy(version, data):
    if version.base_algorithm is not None:
        return EligibleOnly(build_algorithm(version.base_algorithm, version.base_config), data, version.name)
    return RankedStrategy(version, data)


# ---------------------------------------------------------------------------
# Running a version over a window
# ---------------------------------------------------------------------------

def portfolio_config(version):
    return PortfolioConfig(starting_capital=CAPITAL, max_positions=version.max_positions,
                           risk_pct=version.risk_pct, cost_bps=COST_BPS, fill_mode="next_open",
                           stop_mode="widest", sizing_mode=version.sizing)


def run_window(version, start, end, strategy=None, allow_holdout=False):
    if not allow_holdout:
        periods.assert_before_holdout(end)
    data = lab_data(version.universe)
    strategy = strategy or build_strategy(version, data)
    frames = {t: f[f.index <= end] for t, f in data.stock_frames.items()}
    frames = {t: f for t, f in frames.items() if len(f) > 2}
    result = run_portfolio(frames, strategy, strategy, portfolio_config(version), trade_from=start)
    if version.cash_in == "SPY":
        result = with_spy_fill(result, data.benchmarks["SPY"])
    return result


def with_spy_fill(result, spy_close):
    """Re-price the account as if every uninvested dollar sat in SPY instead of cash.

    Daily: return = stock-book return + (yesterday's cash share) x SPY's return, minus the
    10 bps/side cost of moving money between cash and SPY when the cash share changes.
    """
    from portfolio import PortfolioResult, portfolio_metrics

    equity, holdings = result.equity, result.holdings
    cash_share = ((equity - holdings) / equity).clip(lower=0.0)
    spy_return = spy_close.reindex(equity.index).pct_change(fill_method=None)
    book_return = equity.pct_change(fill_method=None)
    traded = cash_share.diff().abs() * COST_BPS / 10_000.0
    total = (book_return + cash_share.shift(1) * spy_return - traded).iloc[1:]
    filled = pd.concat([equity.iloc[:1], equity.iloc[0] * (1.0 + total).cumprod()])
    # `holdings` keeps meaning "money in the strategy's stock picks" (the rest is in SPY).
    out = PortfolioResult(equity=filled, trades=result.trades, n_signals=result.n_signals,
                          holdings=holdings / equity * filled)
    out.metrics = portfolio_metrics(out)
    return out


def benchmark_curves(start, end, universe="core"):
    data = lab_data(universe)
    cfg = PortfolioConfig(starting_capital=CAPITAL, cost_bps=COST_BPS)
    return {name: single_asset_benchmark(close[(close.index >= start) & (close.index <= end)], cfg)
            for name, close in data.benchmarks.items()}


def evaluate(version, windows=WINDOWS):
    """{window: (PortfolioResult, {benchmark: equity})} for development and validation."""
    data = lab_data(version.universe)
    strategy = build_strategy(version, data)
    out = {}
    for window in windows:
        start, end = periods.research_window(window)
        result = run_window(version, start, end, strategy)
        out[window] = (result, benchmark_curves(start, end, version.universe))
        m = result.metrics
        print(f"  {version.name} {window:11s} CAGR {m['cagr'] * 100:5.1f}%  maxDD {m['max_dd'] * 100:6.1f}%  "
              f"Sharpe {m['sharpe']:.2f}  trades {m['n_trades']}", flush=True)
    return out


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def _pct(x):
    return f"{x * 100:+.1f}%"


def rolling_12m(equity):
    """'Time travel': the 12-month return starting from every month-start in the window."""
    month_starts = equity.groupby([equity.index.year, equity.index.month]).head(1).index
    values = {}
    for start in month_starts:
        end = start + pd.DateOffset(years=1)
        if end > equity.index[-1]:
            break
        values[start] = float(equity.asof(end) / equity.loc[start] - 1.0)
    return pd.Series(values, dtype=float)


def yearly_returns(equity):
    yearly = equity.groupby(equity.index.year).last()
    first = equity.groupby(equity.index.year).first()
    previous = yearly.shift(1)
    previous.iloc[0] = first.iloc[0]
    return yearly / previous - 1.0


def overfit_flags(version, dev, val):
    flags = []
    if dev["cagr"] > 0 and val["cagr"] < dev["cagr"] * (2 / 3):
        flags.append(f"validation CAGR {_pct(val['cagr'])} is more than a third below development {_pct(dev['cagr'])}")
    if dev["n_trades"] < 100:
        flags.append(f"only {dev['n_trades']} development trades (< 100)")
    tuned = len(version.weights) + len(version.filters) + len(version.exits)
    if tuned > 15:
        flags.append(f"{tuned} tuned components (> 15): high risk of fitting noise")
    return flags


def metric_row(name, m):
    return (f"| {name} | {_pct(m['cagr'])} | {m['max_dd'] * 100:.1f}% | {m['sharpe']:.2f} | {m['calmar']:.2f} | "
            f"{m['max_underwater_days']} | "
            + (f"{m['n_trades']} | {m['win_rate'] * 100:.0f}% | {m['profit_factor']:.2f} | "
               f"{m['avg_hold_bars']:.0f} | {m['exposure'] * 100:.0f}% |" if "n_trades" in m else "| | | | |"))


def write_version_report(version, results):
    out_dir = os.path.join(REPORT_DIR, version.name)
    os.makedirs(out_dir, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=False)
    summary = {"version": version.name, "description": version.description, "windows": {}}
    lines = [f"# {version.name} — {version.description}", "",
             f"Capital ${CAPITAL:,.0f} · next-open fills · {COST_BPS:.0f} bps/side · "
             f"{version.max_positions} positions · {version.sizing} sizing · rebalance {version.rebalance} · "
             f"universe {version.universe}", ""]
    if version.base_algorithm is None:
        lines += ["**Score weights:** " + ", ".join(f"{k} {v}" for k, v in version.weights.items()),
                  "**Buy filters:** " + (", ".join(f"{k}={v}" for k, v in version.filters.items()) or "none"),
                  "**Sell rules:** " + ", ".join(f"{k}={v}" for k, v in version.exits.items())
                  + f" + catastrophe stop (widest of 20-day swing low / {version.atr_mult}xATR)", ""]
    for ax, window in zip(axes, WINDOWS):
        result, bench = results[window]
        m = result.metrics
        bench_m = {name: equity_metrics(curve) for name, curve in bench.items()}
        roll = rolling_12m(result.equity)
        roll_spy = rolling_12m(bench["SPY"])
        reasons = pd.Series([t.exit_reason for t in result.trades]).value_counts().to_dict()
        summary["windows"][window] = {"metrics": m, "benchmarks": bench_m, "exit_reasons": reasons}
        lines += [f"## {window.capitalize()} {periods.research_window(window)[0].year}–"
                  f"{periods.research_window(window)[1].year}", "",
                  "| System | CAGR | Max DD | Sharpe | Calmar | Longest underwater (days) | Trades | Win | "
                  "Profit factor | Avg hold (bars) | Invested |",
                  "|---|---|---|---|---|---|---|---|---|---|---|",
                  metric_row(f"**{version.name}**", m)]
        lines += [metric_row(name, bm) for name, bm in bench_m.items()]
        common = roll.index.intersection(roll_spy.index)
        lines += ["", f"**Time travel (12 months from every month-start, {len(roll)} starts):** median "
                      f"{_pct(roll.median())}, positive {(roll > 0).mean() * 100:.0f}% of the time, beat SPY in "
                      f"{(roll.loc[common] > roll_spy.loc[common]).mean() * 100:.0f}% of starts; worst "
                      f"{_pct(roll.min())}, best {_pct(roll.max())}.",
                  f"Exit reasons: {reasons}. Longest losing streak: {m['longest_losing_streak']} trades.", ""]
        years = pd.DataFrame({"strategy": yearly_returns(result.equity), "SPY": yearly_returns(bench["SPY"])})
        lines += ["| Year | " + " | ".join(str(y) for y in years.index) + " |",
                  "|---|" + "---|" * len(years),
                  f"| {version.name} | " + " | ".join(f"{x * 100:+.0f}%" for x in years["strategy"]) + " |",
                  "| SPY | " + " | ".join(f"{x * 100:+.0f}%" for x in years["SPY"]) + " |", ""]
        ax.plot(result.equity.index, result.equity, label=version.name, color="#1f6feb", lw=1.8)
        for name, color in (("SPY", "#e39b3c"), ("RSP", "#8a94a3")):
            ax.plot(bench[name].index, bench[name], label=name, color=color, lw=1.1)
        ax.set_yscale("log")
        ax.set_title(f"{window} — growth of ${CAPITAL:,.0f} (log)")
        ax.legend(loc="upper left")
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "equity.png"), dpi=120)
    plt.close(fig)
    dev, val = summary["windows"]["development"]["metrics"], summary["windows"]["validation"]["metrics"]
    flags = overfit_flags(version, dev, val)
    summary["overfit_flags"] = flags
    first_section = next(i for i, line in enumerate(lines) if line.startswith("## "))
    lines[first_section:first_section] = ["![equity](equity.png)", "",
                                          "**Overfitting flags:** " + ("; ".join(flags) if flags else "none"), ""]
    with open(os.path.join(out_dir, "report.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    update_log(version, dev, val, flags)
    export_for_pwa(version, summary, flags)
    print(f"Written {os.path.join(out_dir, 'report.md')}")


PWA_COLUMNS = ["strategy", "cagr", "maxDD", "sharpe", "calmar", "trades", "avgHold", "winRate"]


def _pwa_row(label, m):
    row = {"strategy": label, "cagr": round(m["cagr"] * 100, 2), "maxDD": round(m["max_dd"] * 100, 1),
           "sharpe": round(m["sharpe"], 2), "calmar": round(m["calmar"], 2)}
    if "n_trades" in m:
        row.update({"trades": m["n_trades"], "avgHold": round(m["avg_hold_bars"]), "winRate": round(m["win_rate"] * 100)})
    return row


def export_for_pwa(version, summary, flags):
    """research_results/lab_<version>.json in the schema the PWA Research page renders."""
    import research_portfolio

    tables = []
    for window in WINDOWS:
        w = summary["windows"][window]
        start, end = periods.research_window(window)
        rows = [_pwa_row(version.name, w["metrics"])] + [_pwa_row(f"BENCH {b}", m) for b, m in w["benchmarks"].items()]
        tables.append({"title": f"{window.capitalize()} {start.year}-{end.year} (point-in-time S&P 500, "
                                f"${CAPITAL:,.0f}, next-open fills, {COST_BPS:.0f} bps)",
                       "note": None, "columns": PWA_COLUMNS, "rows": rows})
    research_portfolio.write_report(f"lab_{version.name}", tables, verdict={
        "winner": version.name, "promoted": [],
        "summary": f"{version.description} Overfitting flags: {'; '.join(flags) if flags else 'none'}."})


def update_log(version, dev, val, flags):
    """Insert/replace this version's row in the ALGO_LOG.md table."""
    with open(periods.ALGO_LOG) as fh:
        lines = fh.read().split("\n")
    row = (f"| {version.name} | {pd.Timestamp.today().date()} | {version.description} | "
           f"{_pct(dev['cagr'])} / {dev['max_dd'] * 100:.0f}% | {_pct(val['cagr'])} / {val['max_dd'] * 100:.0f}% | "
           f"{'FLAGS: ' + '; '.join(flags) if flags else 'see report'} |")
    prefix = f"| {version.name} |"
    existing = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if existing:
        lines[existing[0]] = row
    else:
        last_row = max(i for i, line in enumerate(lines) if line.startswith("| v"))
        lines.insert(last_row + 1, row)
    with open(periods.ALGO_LOG, "w") as fh:
        fh.write("\n".join(lines))


def run_version(name):
    version = VERSIONS[name]
    write_version_report(version, evaluate(version))


# ---------------------------------------------------------------------------
# Analyses: SELL tournament, ablation, regimes, Monte Carlo, comparison
# ---------------------------------------------------------------------------

SELL_VARIANTS = {
    "MA200 break": {"ma_break": 200},
    "MA200 break, 3 closes": {"ma_break": 200, "ma_confirm": 3},
    "MA100 break": {"ma_break": 100},
    "MA50 break": {"ma_break": 50},
    "Rank drop only": {"rank_drop": True},
    "MA200 + rank drop": {"ma_break": 200, "rank_drop": True},
    "Chandelier 4xATR": {"trail_atr": 4.0},
    "Chandelier 6xATR": {"trail_atr": 6.0},
    "MA200 + earnings miss": {"ma_break": 200, "earnings_miss": True},
    "MA200 + ADX weakening": {"ma_break": 200, "adx_weak": True},
    "MA200 + OBV weakening": {"ma_break": 200, "obv_weak": True},
    "MA200 + 1-year time stop": {"ma_break": 200, "time_stop": 252},
    "MA200 + market down": {"ma_break": 200, "market_down": True},
}


def _table(title, rows, columns, note=None):
    lines = [f"## {title}", ""] + ([note, ""] if note else [])
    lines += ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(str(r[c]) for c in columns) + " |" for r in rows]
    return lines + [""]


def _summary_row(label, results):
    dev, val = results["development"][0].metrics, results["validation"][0].metrics
    return {"variant": label, "dev CAGR": _pct(dev["cagr"]), "dev maxDD": f"{dev['max_dd'] * 100:.0f}%",
            "dev Sharpe": f"{dev['sharpe']:.2f}", "val CAGR": _pct(val["cagr"]),
            "val maxDD": f"{val['max_dd'] * 100:.0f}%", "val Sharpe": f"{val['sharpe']:.2f}",
            "trades": dev["n_trades"] + val["n_trades"],
            "avg hold": f"{(dev['avg_hold_bars'] + val['avg_hold_bars']) / 2:.0f}",
            "_dev": dev["cagr"], "_val": val["cagr"]}


def _write_analysis(version, kind, lines):
    out_dir = os.path.join(REPORT_DIR, version.name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{kind}.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Written {path}")


def sell_tournament(name):
    base = VERSIONS[name]
    rows = []
    for label, exits in SELL_VARIANTS.items():
        variant = replace(base, name=f"{name}-sell", exits=exits)
        rows.append(_summary_row(label, evaluate(variant)))
    rows.sort(key=lambda r: r["_val"] + r["_dev"], reverse=True)
    columns = ["variant", "dev CAGR", "dev maxDD", "dev Sharpe", "val CAGR", "val maxDD", "val Sharpe", "trades", "avg hold"]
    _write_analysis(base, "sell_tournament", [f"# SELL-rule tournament — {name} buys, different exits", ""]
                    + _table("Results (sorted by dev + val CAGR)", rows, columns,
                             "Same BUY rules and portfolio; only the sell rule changes. Catastrophe stop always on."))


def ablate(name):
    """Drop one ingredient at a time: how much does each factor / filter / exit really add?"""
    base = VERSIONS[name]
    baseline = _summary_row("FULL VERSION", evaluate(base))
    rows = [baseline]
    for factor in base.weights:
        weights = {k: v for k, v in base.weights.items() if k != factor}
        rows.append(_summary_row(f"without factor {factor}", evaluate(replace(base, weights=weights))))
    for filter_name in base.filters:
        filters = {k: v for k, v in base.filters.items() if k != filter_name}
        rows.append(_summary_row(f"without filter {filter_name}", evaluate(replace(base, filters=filters))))
    for row in rows[1:]:
        row["adds (dev)"] = _pct(baseline["_dev"] - row["_dev"])
        row["adds (val)"] = _pct(baseline["_val"] - row["_val"])
        row["verdict"] = ("HELPS" if baseline["_dev"] > row["_dev"] and baseline["_val"] > row["_val"]
                          else "HURTS" if baseline["_dev"] < row["_dev"] and baseline["_val"] < row["_val"]
                          else "mixed / noise")
    baseline.update({"adds (dev)": "—", "adds (val)": "—", "verdict": "—"})
    columns = ["variant", "dev CAGR", "val CAGR", "adds (dev)", "adds (val)", "verdict", "dev maxDD", "val maxDD"]
    _write_analysis(base, "ablation", [f"# Factor attribution — {name}", ""]
                    + _table("Remove one ingredient at a time", rows, columns,
                             "'adds' = CAGR lost when the ingredient is removed. HELPS = positive in BOTH periods."))


def regimes(name):
    version = VERSIONS[name]
    results = evaluate(version)
    spy_full = lab_data(version.universe).benchmarks["SPY"]
    trend_up = spy_full > spy_full.rolling(200).mean()
    vol = spy_full.pct_change(fill_method=None).rolling(63).std() * np.sqrt(252)
    high_vol = vol > vol[vol.index < periods.VALIDATION[0]].median()
    rows = []
    for window in WINDOWS:
        result, bench = results[window]
        daily = result.equity.pct_change(fill_method=None).dropna()
        spy_daily = bench["SPY"].pct_change(fill_method=None).dropna()
        for trend in (True, False):
            for hv in (False, True):
                days = daily.index[(trend_up.reindex(daily.index) == trend) & (high_vol.reindex(daily.index) == hv)]
                if len(days) < 20:
                    continue
                rows.append({"window": window, "regime": f"{'uptrend' if trend else 'downtrend'} / "
                                                         f"{'high' if hv else 'low'} volatility",
                             "share of days": f"{len(days) / len(daily) * 100:.0f}%",
                             "strategy ann.": _pct(daily.loc[days].mean() * 252),
                             "SPY ann.": _pct(spy_daily.reindex(days).mean() * 252),
                             "strategy vol": f"{daily.loc[days].std() * np.sqrt(252) * 100:.0f}%"})
    _write_analysis(version, "regimes", [f"# Market regimes — {name}", "",
                                         "Regime = SPY above/below its 200-day average × SPY 3-month volatility "
                                         "above/below its development-period median. Returns are simple annualized "
                                         "daily averages (no compounding), for comparison only.", ""]
                    + _table("Behaviour by regime", rows, ["window", "regime", "share of days", "strategy ann.",
                                                            "SPY ann.", "strategy vol"]))


def monte_carlo(name, paths=5000, block=21, horizon_years=(1, 5), seed=7):
    """Block-bootstrap the daily returns: distribution of outcomes, chance of loss, worst cases."""
    version = VERSIONS[name]
    results = evaluate(version)
    daily = pd.concat([results[w][0].equity.pct_change(fill_method=None).dropna() for w in WINDOWS]).to_numpy()
    spy = pd.concat([results[w][1]["SPY"].pct_change(fill_method=None).dropna() for w in WINDOWS]).to_numpy()
    rng = np.random.default_rng(seed)
    rows = []
    for years in horizon_years:
        n = 252 * years
        starts = rng.integers(0, len(daily) - block, size=(paths, n // block + 1))
        idx = (starts[:, :, None] + np.arange(block)).reshape(paths, -1)[:, :n]
        growth, spy_growth = np.prod(1 + daily[idx], axis=1), np.prod(1 + spy[idx], axis=1)
        curves = np.cumprod(1 + daily[idx], axis=1)
        dd = (curves / np.maximum.accumulate(curves, axis=1) - 1).min(axis=1)
        cagr = growth ** (1 / years) - 1
        stats = {"p5": np.percentile(cagr, 5), "beat": (growth > spy_growth).mean()}
        rows.append({"horizon": f"{years} year{'s' if years > 1 else ''}", "_stats": stats,
                     "P(loss)": f"{(growth < 1).mean() * 100:.0f}%",
                     "P(beat SPY)": f"{(growth > spy_growth).mean() * 100:.0f}%",
                     "CAGR 5th pct": _pct(np.percentile(cagr, 5)), "CAGR median": _pct(np.median(cagr)),
                     "CAGR 95th pct": _pct(np.percentile(cagr, 95)),
                     "max DD median": f"{np.median(dd) * 100:.0f}%", "max DD 95th worst": f"{np.percentile(dd, 5) * 100:.0f}%"})
    five = rows[-1].pop("_stats")
    for row in rows[:-1]:
        row.pop("_stats")
    verdict = "STABLE" if five["p5"] > 0 and five["beat"] >= 0.6 else "FRAGILE"
    _write_analysis(version, "monte_carlo", [f"# Monte Carlo — {name}", "",
                                             f"{paths} paths of {block}-day blocks resampled from the development + "
                                             f"validation daily returns (blocks keep streaks and crashes intact).", "",
                                             f"**Verdict: {verdict}** (stable = 5-year 5th-percentile CAGR above 0 "
                                             "and beats SPY in at least 60% of 5-year paths).", ""]
                    + _table("Outcome distribution", rows, list(rows[0].keys())))


def _register_controls(data):
    """Neutral 'factors' for control portfolios: a fixed random number per ticker (buy & hold a
    random 20) and a fresh random draw every month (maximum rotation)."""
    import zlib

    tickers, dates = data.panel.tickers, data.panel.dates
    static = np.tile([zlib.crc32(t.encode()) / 2 ** 32 for t in tickers], (len(dates), 1))
    months = dates.to_period("M")
    draws = pd.DataFrame(np.random.default_rng(3).random((months.nunique(), len(tickers))),
                         index=months.unique(), columns=tickers)
    data._factors["control_static"] = pd.DataFrame(static, index=dates, columns=tickers).astype("float32")
    data._factors["control_monthly"] = draws.reindex(months).set_axis(dates).astype("float32")
    for name in ("control_static", "control_monthly"):
        factors.FACTORS[name] = factors.Factor(name, "control", "random control", "random", lambda p: None)


def controls(universe="core"):
    """Sanity check: random portfolios through the SAME machinery should track RSP (minus costs).

    On the extended (survivor-biased) universe the controls are the fair bar for a strategy:
    survivorship inflates the random picks exactly as it inflates the strategy's.
    """
    from algo_versions import Version

    _register_controls(lab_data(universe))
    variants = [("random 20, held", "control_static", {"rank_drop": True}),
                ("random 20, re-drawn monthly", "control_monthly", {"rank_drop": True}),
                ("random 20 held + MA200 exit", "control_static", {"rank_drop": True, "ma_break": 200})]
    rows = [_summary_row(label, evaluate(Version("control", label, weights={w: 1.0}, exits=exits, atr_mult=8.0,
                                                 universe=universe)))
            for label, w, exits in variants]
    columns = ["variant", "dev CAGR", "dev maxDD", "dev Sharpe", "val CAGR", "val maxDD", "val Sharpe", "trades"]
    lines = ["# Control portfolios — is the machinery neutral?", "",
             "Random selections run through the identical engine, costs and fills. Held random 20 should "
             "track RSP (equal-weight S&P 500); rotation costs only trading costs if the machinery is sound.", ""]
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, f"controls_{universe}.md"), "w") as fh:
        fh.write("\n".join(lines + _table("Controls", rows, columns)) + "\n")
    print("\n".join(_table("Controls", rows, columns)))


def compare(names):
    rows = [_summary_row(name, evaluate(VERSIONS[name])) for name in names]
    columns = ["variant", "dev CAGR", "dev maxDD", "dev Sharpe", "val CAGR", "val maxDD", "val Sharpe", "trades", "avg hold"]
    lines = ["# Version comparison", ""] + _table("Development vs validation", rows, columns)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "comparison.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def holdout(name, reason):
    """The final, one-time test on 2023 -> today (logged)."""
    version = VERSIONS[name]
    start, end = periods.open_holdout(name, reason)
    result = run_window(version, start, end, allow_holdout=True)
    bench = benchmark_curves(start, end, version.universe)
    lines = [f"# HOLDOUT — {name} ({start.date()} → {end.date()})", "", "| System | CAGR | Max DD | Sharpe | Calmar | "
             "Longest underwater (days) | Trades | Win | Profit factor | Avg hold (bars) | Invested |",
             "|---|---|---|---|---|---|---|---|---|---|---|", metric_row(f"**{name}**", result.metrics)]
    lines += [metric_row(b, equity_metrics(curve)) for b, curve in bench.items()]
    _write_analysis(version, "holdout", lines)


COMMANDS = {"run": lambda a: run_version(a[0]), "compare": compare, "sell": lambda a: sell_tournament(a[0]),
            "ablate": lambda a: ablate(a[0]), "regime": lambda a: regimes(a[0]),
            "montecarlo": lambda a: monte_carlo(a[0]), "holdout": lambda a: holdout(a[0], " ".join(a[1:])),
            "controls": lambda a: controls(a[0] if a else "core")}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])
