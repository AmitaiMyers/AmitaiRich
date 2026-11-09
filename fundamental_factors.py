"""Earnings + growth factors (the owner's beliefs 1 and 2), point-in-time, as daily panels.

Every value enters the panel on the first trading day on/after the date it became public
(EDGAR filing date / Yahoo availability rule) and is carried forward until the next report.
Values older than MAX_AGE_DAYS (no report for ~2 quarters) are treated as unknown (NaN), so a
company that stopped reporting is never scored on stale numbers.

Registered into factors.FACTORS by `register(panel_builder)` callers via `build_all`.
"""

import numpy as np
import pandas as pd

import earnings_pit
import fundamentals_pit
from factors import FACTORS, Factor

MAX_AGE_DAYS = 200


def _daily(events, calendar, tickers, max_age_days=MAX_AGE_DAYS):
    """events (ticker, available, value) -> dates x tickers panel of the latest known value."""
    events = events[events["ticker"].isin(tickers)].dropna(subset=["value"])
    position = calendar.searchsorted(pd.DatetimeIndex(events["available"]))
    events = events.assign(bar=position)[position < len(calendar)]
    events = events.assign(date=calendar[events["bar"].to_numpy()])
    latest = events.sort_values("available").drop_duplicates(["date", "ticker"], keep="last")
    values = latest.pivot(index="date", columns="ticker", values="value").reindex(calendar).ffill()
    stamped = latest.assign(stamp=latest["date"]).pivot(index="date", columns="ticker", values="stamp")
    age = (pd.Series(calendar, index=calendar).to_numpy()[:, None]
           - stamped.reindex(calendar).ffill().to_numpy())
    fresh = age <= np.timedelta64(max_age_days, "D")
    result = values.where(fresh)
    return result.reindex(columns=tickers).astype("float32")


# --- earnings surprise (Yahoo: consensus vs reported) -------------------------------

def earnings_events(table):
    table = table.sort_values(["ticker", "available"])
    surprise = table["surprise_pct"].clip(-100, 100)
    beat = (table["reported"] >= table["estimate"]).astype(float)
    streak = beat.groupby(table["ticker"]).transform(lambda s: s.rolling(4, min_periods=1).sum())
    return {
        "eps_surprise": table.assign(value=surprise.to_numpy()),
        "beat_streak": table.assign(value=streak.to_numpy()),
    }


# --- growth (EDGAR quarterly revenue / diluted EPS) ---------------------------------

def _year_ago(series):
    """For each quarter, the value of the quarter whose period ended ~1 year earlier (else NaN)."""
    ends = series["period_end"].to_numpy()
    values = series["value"].to_numpy()
    result = np.full(len(series), np.nan)
    for i, end in enumerate(ends):
        gap = (end - ends[:i]).astype("timedelta64[D]").astype(int)
        match = np.flatnonzero((gap >= 350) & (gap <= 380))
        if len(match):
            result[i] = values[match[-1]]
    return result


def growth_events(quarterly):
    """Per ticker-quarter growth metrics, each available at that quarter's filing date."""
    rows = []
    for ticker, block in quarterly.groupby("ticker"):
        rev = block[block["metric"] == "revenue"].sort_values("period_end").reset_index(drop=True)
        eps = block[block["metric"] == "eps_diluted"].sort_values("period_end").reset_index(drop=True)
        if len(rev) >= 5:
            prior = _year_ago(rev)
            growth = rev["value"] / prior - 1.0
            growth = growth.where(prior > 0)
            ttm = rev["value"].rolling(4).sum()
            ttm_up = (ttm > ttm.shift(4)).astype(float).where(ttm.shift(4).notna())
            consistency = ttm_up + ttm_up.shift(4) + ttm_up.shift(8)
            rows.append(pd.DataFrame({"ticker": ticker, "available": rev["available"],
                                      "rev_growth_yoy": growth, "rev_accel": growth - growth.shift(1),
                                      "rev_consistency": consistency}))
        if len(eps) >= 5:
            prior = _year_ago(eps)
            change = eps["value"] - prior
            growth = change / np.maximum(np.abs(prior), 0.05)
            sue = change / change.rolling(8, min_periods=4).std().shift(1)
            ttm = eps["value"].rolling(4).sum()
            ttm_up = (ttm > ttm.shift(4)).astype(float).where(ttm.shift(4).notna())
            rows.append(pd.DataFrame({"ticker": ticker, "available": eps["available"],
                                      "eps_growth_yoy": growth.clip(-5, 5), "sue": sue.clip(-10, 10),
                                      "eps_consistency": ttm_up + ttm_up.shift(4) + ttm_up.shift(8)}))
    return pd.concat(rows, ignore_index=True)


FUNDAMENTAL_SPECS = [
    ("eps_surprise", "earnings", "Last quarter's EPS surprise vs the consensus estimate (beat = positive).",
     "(reported EPS - consensus) / |consensus| in %, clipped to +/-100"),
    ("beat_streak", "earnings", "How many of the last 4 reports matched or beat the consensus (0-4).",
     "count(reported >= estimate) over the last 4 reports"),
    ("sue", "earnings", "Standardized unexpected earnings: EPS growth vs its own usual variability.",
     "(EPS_q - EPS_q-4) / std(previous 8 such changes)"),
    ("eps_growth_yoy", "growth", "Latest quarter's diluted EPS vs the same quarter a year earlier.",
     "(EPS_q - EPS_q-4) / max(|EPS_q-4|, 0.05), clipped to +/-5"),
    ("rev_growth_yoy", "growth", "Latest quarter's revenue vs the same quarter a year earlier.",
     "revenue_q / revenue_q-4 - 1"),
    ("rev_accel", "growth", "Revenue growth speeding up vs the previous quarter.",
     "rev_growth_yoy_q - rev_growth_yoy_q-1"),
    ("rev_consistency", "growth", "In how many of the last 3 years trailing-12-month revenue grew (0-3).",
     "sum over 3 years of [TTM revenue > TTM revenue a year earlier]"),
    ("eps_consistency", "growth", "In how many of the last 3 years trailing-12-month EPS grew (0-3).",
     "sum over 3 years of [TTM EPS > TTM EPS a year earlier]"),
]


def build_all(panel):
    """Compute every fundamental factor panel for `panel` and register them in FACTORS."""
    calendar, tickers = panel.dates, panel.tickers
    surprise = earnings_events(earnings_pit.load_earnings())
    growth = growth_events(fundamentals_pit.load_quarterly())
    sources = {**surprise, **{name: growth[["ticker", "available", name]].rename(columns={name: "value"})
                             for name in ("sue", "eps_growth_yoy", "rev_growth_yoy", "rev_accel",
                                          "rev_consistency", "eps_consistency")}}
    built = {}
    for name, group, meaning, formula in FUNDAMENTAL_SPECS:
        frame = _daily(sources[name], calendar, tickers)
        built[name] = frame
        FACTORS[name] = Factor(name, group, meaning, formula, lambda p, f=frame: f)
    return built
