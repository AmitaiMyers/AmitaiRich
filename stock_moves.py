"""'Why is it moving?' — the facts behind a stock's recent price move, for its page in the app.

For every stock: its return over 1 week / 1 month / 3 months next to the market's (SPY) and its
industry's (median of the other stocks in the app with the same Yahoo industry; the sector when
fewer than MIN_PEERS share the industry), how far it is below its 52-week high, and its last
earnings reports (surprise vs the consensus and how the price reacted). The app turns these
numbers into sentences; nothing here is a forecast.

Pure functions on price Series, so they are tested without the network. publish.py calls
`moves_for(...)` with the frames it already has and writes the result into data/company/<T>.json.
"""

import numpy as np
import pandas as pd

HORIZONS = {"1w": 5, "1m": 21, "3m": 63}
YEAR_BARS = 252
MIN_PEERS = 3
REPORTS_SHOWN = 3
REACTION_BARS = 2          # close before the report -> close 2 bars after it becomes known


def _pct(value):
    return None if value is None or not np.isfinite(value) else round(float(value) * 100, 1)


def trailing_return(close, bars):
    """Return over the last `bars` bars, or None when the history is too short."""
    if len(close) <= bars:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - bars] - 1.0)


def returns(close):
    return {name: trailing_return(close, bars) for name, bars in HORIZONS.items()}


def peer_groups(profiles):
    """{ticker: (group name, [peer tickers incl. itself])}: industry peers, else sector peers, else none."""
    by_industry, by_sector = {}, {}
    for ticker, profile in profiles.items():
        if profile["industry"]:
            by_industry.setdefault(profile["industry"], []).append(ticker)
        if profile["sector"]:
            by_sector.setdefault(profile["sector"], []).append(ticker)
    groups = {}
    for ticker, profile in profiles.items():
        industry, sector = profile["industry"], profile["sector"]
        if industry and len(by_industry[industry]) >= MIN_PEERS:
            groups[ticker] = (industry, by_industry[industry])
        elif sector and len(by_sector[sector]) >= MIN_PEERS:
            groups[ticker] = (sector, by_sector[sector])
    return groups


def group_returns(members, stock_returns):
    """Median return per horizon over the members that have one (None when nobody has)."""
    out = {}
    for name in HORIZONS:
        values = [stock_returns[t][name] for t in members if t in stock_returns and stock_returns[t][name] is not None]
        out[name] = float(np.median(values)) if values else None
    return out


def earnings_reactions(close, spy_close, reports):
    """The last REPORTS_SHOWN reports: date, surprise %, and the stock's move vs SPY around it.

    `reports`: DataFrame rows with `available` (first close that reflects the report) and
    `surprise_pct`. Reaction = stock return minus SPY return from the close BEFORE that bar to
    REACTION_BARS bars after it (None when the window is not complete yet)."""
    rows = []
    recent = reports.sort_values("available").tail(REPORTS_SHOWN)
    for _, report in recent.iloc[::-1].iterrows():
        day = close.index.searchsorted(pd.Timestamp(report["available"]))
        reaction = None
        if 1 <= day and day + REACTION_BARS < len(close):
            stock = close.iloc[day + REACTION_BARS] / close.iloc[day - 1] - 1.0
            spy = spy_close.reindex(close.index)
            market = spy.iloc[day + REACTION_BARS] / spy.iloc[day - 1] - 1.0
            reaction = stock - market
        rows.append({"date": pd.Timestamp(report["available"]).strftime("%Y-%m-%d"),
                     "surprise_pct": None if pd.isna(report["surprise_pct"]) else round(float(report["surprise_pct"]), 1),
                     "reaction_pct": _pct(reaction)})
    return rows


def moves_for(closes, spy_close, profiles, earnings):
    """{ticker: move facts} for every ticker in `closes` (a dict of Close Series).

    profiles: magic_formula.company_profiles(...) (for the industry / sector peer groups);
    earnings: earnings_pit.load_earnings() (columns ticker, available, surprise_pct)."""
    stock_returns = {t: returns(c) for t, c in closes.items()}
    groups = peer_groups({t: p for t, p in profiles.items() if t in closes})
    market = returns(spy_close)
    by_ticker = {t: block for t, block in earnings.groupby("ticker")}
    out = {}
    for ticker, close in closes.items():
        year_high = float(close.iloc[-YEAR_BARS:].max())
        group = groups[ticker] if ticker in groups else None
        peers = None if group is None else group_returns([t for t in group[1] if t != ticker], stock_returns)
        out[ticker] = {
            "as_of": close.index[-1].strftime("%Y-%m-%d"),
            "stock": {k: _pct(v) for k, v in stock_returns[ticker].items()},
            "market": {k: _pct(v) for k, v in market.items()},
            "peers": None if peers is None else {k: _pct(v) for k, v in peers.items()},
            "peer_group": None if group is None else group[0],
            "peer_count": None if group is None else len(group[1]) - 1,
            "from_high_pct": _pct(close.iloc[-1] / year_high - 1.0),
            "earnings": earnings_reactions(close, spy_close, by_ticker[ticker]) if ticker in by_ticker else [],
        }
    return out
