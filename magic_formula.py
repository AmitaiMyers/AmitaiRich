"""Joel Greenblatt's "Magic Formula": a quality + cheapness filter and ranking layer.

    python magic_formula.py                    # top 30 of the app's universe ('all')
    python magic_formula.py --scope sp500 --top 50 --refresh

Two layers, kept apart so the ranking can be tested and reused without the network:

  * `magic_formula_pool(stocks)` / `magic_formula_rank(stocks, top_n=30)` — PURE. Take a
    DataFrame (or list of dicts) with the REQUIRED_COLUMNS and return the ranked stocks.
  * `fetch_fundamentals(tickers)` — the data source (yfinance), cached for a week in
    fundamentals_cache/magic_formula.json. Produces exactly the REQUIRED_COLUMNS.

Rules (in this order):
  1. Exclude financials, utilities, non-U.S. companies (ADRs) and market caps under $50M.
  2. Return on Capital = EBIT / (Net Working Capital + Net Fixed Assets),
     Net Working Capital = Current Assets - Current Liabilities.
     Earnings Yield      = EBIT / Enterprise Value,
     Enterprise Value    = Market Cap + Total Debt - Cash and Cash Equivalents.
  3. Rank by ROC and by EY (highest = rank 1); Magic_Score = ROC rank + EY rank; lowest is best.

Fail-closed on data: a stock is ranked only when every input is known. Missing fields, an
unknown sector/country, non-positive capital or non-positive enterprise value (the ratios are
meaningless there, and capital = 0 would divide by zero) all drop the stock, with the reason
recorded in the `excluded` frame so nothing disappears silently.

LIVE screen only: Yahoo serves current fundamentals (about 4 years of statements), so this
cannot be backtested point-in-time with the project's data.
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from errors import ConfigurationError

REQUIRED_COLUMNS = ("ticker", "sector", "country", "market_cap", "ebit", "current_assets",
                    "current_liabilities", "net_fixed_assets", "total_debt", "cash")
NUMERIC_COLUMNS = REQUIRED_COLUMNS[3:]
EXCLUDED_SECTORS = {"financial services": "financial sector", "financials": "financial sector",
                    "financial": "financial sector", "utilities": "utility sector"}
HOME_COUNTRIES = ("united states", "usa", "us")
MIN_MARKET_CAP = 50e6
DEFAULT_TOP_N = 30
RANKED_COLUMNS = ["ticker", "magic_score", "roc_rank", "ey_rank", "roc", "earnings_yield", "ebit",
                  "capital", "enterprise_value", "market_cap", "sector"]

CACHE_PATH = os.path.join("fundamentals_cache", "magic_formula.json")
CACHE_MAX_AGE_DAYS = 7
MAX_WORKERS = 8
REPORT_PATH = os.path.join("reports", "magic_formula", "latest.csv")


# ---------------------------------------------------------------------------
# Pure ranking
# ---------------------------------------------------------------------------

def _validated_frame(stocks):
    frame = pd.DataFrame(stocks).copy()
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ConfigurationError(f"Magic Formula input is missing columns {missing}; "
                                 f"required: {list(REQUIRED_COLUMNS)}")
    if frame["ticker"].duplicated().any():
        raise ConfigurationError("Magic Formula input has duplicate tickers: "
                                 f"{sorted(frame.loc[frame['ticker'].duplicated(), 'ticker'])}")
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
        frame[column] = frame[column].where(np.isfinite(frame[column]))     # +/-inf counts as missing
    return frame[list(REQUIRED_COLUMNS)].reset_index(drop=True)


def _exclusion_reason(row):
    """Why a stock cannot be ranked (first failing rule), or None when it can."""
    if pd.isna(row["sector"]) or pd.isna(row["country"]):
        return "sector or country unknown"
    sector = str(row["sector"]).strip().lower()
    if sector in EXCLUDED_SECTORS:
        return EXCLUDED_SECTORS[sector]
    if str(row["country"]).strip().lower() not in HOME_COUNTRIES:
        return "non-U.S. company"
    absent = [c for c in NUMERIC_COLUMNS if pd.isna(row[c])]
    if absent:
        return f"missing {', '.join(absent)}"
    if row["market_cap"] < MIN_MARKET_CAP:
        return f"market cap below ${MIN_MARKET_CAP / 1e6:.0f}M"
    if row["capital"] <= 0:
        return "capital (net working capital + net fixed assets) is not positive"
    if row["enterprise_value"] <= 0:
        return "enterprise value is not positive"
    return None


def magic_formula_pool(stocks):
    """(ranked, excluded): every rankable stock, best first, and every dropped stock with its reason."""
    frame = _validated_frame(stocks)
    frame["capital"] = frame["current_assets"] - frame["current_liabilities"] + frame["net_fixed_assets"]
    frame["enterprise_value"] = frame["market_cap"] + frame["total_debt"] - frame["cash"]
    frame["reason"] = frame.apply(_exclusion_reason, axis=1) if len(frame) else pd.Series(dtype=object)
    pool = frame[frame["reason"].isna()].copy()
    excluded = frame.loc[frame["reason"].notna(), ["ticker", "reason"]].reset_index(drop=True)
    pool["roc"] = pool["ebit"] / pool["capital"]
    pool["earnings_yield"] = pool["ebit"] / pool["enterprise_value"]
    pool["roc_rank"] = pool["roc"].rank(ascending=False, method="min").astype(int)
    pool["ey_rank"] = pool["earnings_yield"].rank(ascending=False, method="min").astype(int)
    pool["magic_score"] = pool["roc_rank"] + pool["ey_rank"]
    # Ties on the score: the cheaper stock (higher earnings yield) first, then the ticker — deterministic.
    ranked = pool.sort_values(["magic_score", "earnings_yield", "ticker"], ascending=[True, False, True])
    return ranked[RANKED_COLUMNS].reset_index(drop=True), excluded


def magic_formula_rank(stocks, top_n=DEFAULT_TOP_N):
    """The top `top_n` stocks by Magic_Score (lowest = best) from a DataFrame / list of dicts."""
    if top_n < 1:
        raise ConfigurationError(f"top_n must be >= 1, got {top_n}")
    ranked, _excluded = magic_formula_pool(stocks)
    return ranked.head(top_n)


# ---------------------------------------------------------------------------
# Data source (yfinance) -> REQUIRED_COLUMNS
# ---------------------------------------------------------------------------

def _latest(statement, row):
    """Newest non-null value of a statement row (None when the row or every value is absent)."""
    if statement is None or statement.empty or row not in statement.index:
        return None
    values = statement.loc[row].dropna()
    return None if values.empty else float(values.iloc[0])


def _trailing_ebit(quarterly, annual):
    """EBIT of the last 4 reported quarters; the latest fiscal year when 4 quarters are not available."""
    if quarterly is not None and not quarterly.empty and "EBIT" in quarterly.index:
        last_four = quarterly.loc["EBIT"].iloc[:4]
        if len(last_four) == 4 and last_four.notna().all():
            return float(last_four.sum())
    return _latest(annual, "EBIT")


def _info_value(info, key):
    return info[key] if key in info else None


def _fetch_one(ticker):
    import yfinance as yf

    source = yf.Ticker(ticker)
    info = source.info
    balance = source.quarterly_balance_sheet
    return {
        "ticker": ticker,
        "sector": _info_value(info, "sector"),
        "country": _info_value(info, "country"),
        "market_cap": _info_value(info, "marketCap"),
        "ebit": _trailing_ebit(source.quarterly_income_stmt, source.income_stmt),
        "current_assets": _latest(balance, "Current Assets"),
        "current_liabilities": _latest(balance, "Current Liabilities"),
        "net_fixed_assets": _latest(balance, "Net PPE"),
        "total_debt": _latest(balance, "Total Debt"),
        "cash": _latest(balance, "Cash And Cash Equivalents"),
    }


def _load_cache(cache_path):
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path) as fh:
        return json.load(fh)


def _is_fresh(entry, today):
    return (today - date.fromisoformat(entry["fetched"])).days <= CACHE_MAX_AGE_DAYS


def fetch_fundamentals(tickers, cache_path=CACHE_PATH, refresh=False):
    """DataFrame with REQUIRED_COLUMNS for `tickers` (cached per ticker for CACHE_MAX_AGE_DAYS)."""
    today = date.today()
    cache = _load_cache(cache_path)
    stale = [t for t in tickers if refresh or t not in cache or not _is_fresh(cache[t], today)]
    if stale:
        with ThreadPoolExecutor(MAX_WORKERS) as pool:
            for row in pool.map(_fetch_one, stale):
                cache[row["ticker"]] = {"fetched": today.isoformat(), "row": row}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump(cache, fh, indent=0, sort_keys=True)
    return pd.DataFrame([cache[t]["row"] for t in tickers], columns=list(REQUIRED_COLUMNS))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(scope, top_n, refresh):
    import universe

    tickers = universe.get_universe(scope)
    ranked, excluded = magic_formula_pool(fetch_fundamentals(tickers, refresh=refresh))
    top = ranked.head(top_n)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    ranked.to_csv(REPORT_PATH, index=False)
    excluded.to_csv(REPORT_PATH.replace("latest", "excluded"), index=False)
    shown = top.assign(roc=(top["roc"] * 100).round(1), earnings_yield=(top["earnings_yield"] * 100).round(1),
                       market_cap=(top["market_cap"] / 1e9).round(1))
    print(f"Magic Formula — {len(tickers)} scanned, {len(ranked)} ranked, {len(excluded)} excluded")
    print(shown[["ticker", "magic_score", "roc_rank", "ey_rank", "roc", "earnings_yield", "market_cap", "sector"]]
          .rename(columns={"roc": "ROC %", "earnings_yield": "EY %", "market_cap": "cap $B"}).to_string(index=False))
    print("\nExcluded, by reason:")
    print(excluded["reason"].str.replace(r"^missing .*", "missing data", regex=True).value_counts().to_string())
    return top


def main(argv=None):
    parser = argparse.ArgumentParser(description="Greenblatt Magic Formula ranking.")
    parser.add_argument("--scope", default="all", help="universe scope (see universe.get_universe)")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--refresh", action="store_true", help="ignore the weekly fundamentals cache")
    args = parser.parse_args(argv)
    run(args.scope, args.top, args.refresh)


if __name__ == "__main__":
    main()
