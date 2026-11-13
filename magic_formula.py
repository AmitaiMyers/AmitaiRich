"""Joel Greenblatt's "Magic Formula": a quality + cheapness filter and ranking layer.

    python magic_formula.py                    # top 30 of the app's universe ('all')
    python magic_formula.py --scope sp500 --top 50 --refresh
    python magic_formula.py --update-only      # refresh the weekly fundamentals cache (daily job)

Two layers, kept apart so the ranking can be tested and reused without the network:

  * `magic_formula_pool(stocks)` / `magic_formula_rank(stocks, top_n=30)` — PURE. Take a
    DataFrame (or list of dicts) with the REQUIRED_COLUMNS and return the ranked stocks.
  * `fetch_fundamentals(tickers)` — the data source (yfinance), cached for a week in
    market_data/fundamentals/magic_formula.json. Produces exactly the REQUIRED_COLUMNS.

Rules (in this order):
  1. Exclude financials, utilities, non-U.S. companies (ADRs) and market caps under $50M.
  2. Return on Capital = EBIT / (Net Working Capital + Net Fixed Assets),
     Net Working Capital = max(0, (Current Assets - Excess Cash) - (Current Liabilities - Short-Term Debt))
                           — Greenblatt's definition: cash is not operating capital and interest-bearing
                           debt is financing, not a working liability; a negative result counts as 0.
     Earnings Yield      = EBIT / Enterprise Value,
     Enterprise Value    = Market Cap + Total Debt - Cash and Cash Equivalents.
     EBIT here is OPERATING income (trailing 4 quarters): Yahoo's "EBIT" line includes one-off
     non-operating gains, which put loss-making companies at the top of the list.
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
from datetime import date

import numpy as np
import pandas as pd

import market_data
import yahoo_batches
from errors import ConfigurationError

REQUIRED_COLUMNS = ("ticker", "sector", "country", "market_cap", "ebit", "current_assets",
                    "current_liabilities", "net_fixed_assets", "total_debt", "cash",
                    "excess_cash", "short_term_debt")
NUMERIC_COLUMNS = REQUIRED_COLUMNS[3:]
# Extra per-stock valuation facts fetched in the same request (for the "is it overpriced?" check).
VALUATION_COLUMNS = ("price", "forward_pe", "trailing_pe", "peg", "price_to_sales", "target_price")
# The company profile, fetched in the same request and published on each stock page.
PROFILE_COLUMNS = ("name", "industry", "summary", "website", "employees")
PROFILE_INFO_KEYS = {"name": "longName", "industry": "industry", "summary": "longBusinessSummary",
                     "website": "website", "employees": "fullTimeEmployees"}
RANKING_COLUMNS = REQUIRED_COLUMNS + VALUATION_COLUMNS
FETCHED_COLUMNS = RANKING_COLUMNS + PROFILE_COLUMNS
VALUATION_INFO_KEYS = {"price": "currentPrice", "forward_pe": "forwardPE", "trailing_pe": "trailingPE",
                       "peg": "trailingPegRatio", "price_to_sales": "priceToSalesTrailing12Months",
                       "target_price": "targetMeanPrice"}
CHEAP, FAIR, EXPENSIVE, NO_PROFITS = "cheap", "fair", "expensive", "no profits"
EXCLUDED_SECTORS = {"financial services": "financial sector", "financials": "financial sector",
                    "financial": "financial sector", "utilities": "utility sector"}
HOME_COUNTRIES = ("united states", "usa", "us")
MIN_MARKET_CAP = 50e6
DEFAULT_TOP_N = 30
RANKED_COLUMNS = ["ticker", "magic_score", "roc_rank", "ey_rank", "roc", "earnings_yield", "ebit",
                  "capital", "enterprise_value", "market_cap", "sector"]

CACHE_PATH = os.path.join(market_data.DATA_DIR, "fundamentals", "magic_formula.json")   # cached by CI with the prices
CACHE_MAX_AGE_DAYS = 7
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
        return "capital (net working capital + net fixed assets) is zero"
    if row["enterprise_value"] <= 0:
        return "enterprise value is not positive"
    return None


def magic_formula_pool(stocks):
    """(ranked, excluded): every rankable stock, best first, and every dropped stock with its reason."""
    frame = _validated_frame(stocks)
    operating_assets = frame["current_assets"] - frame["excess_cash"]
    operating_liabilities = frame["current_liabilities"] - frame["short_term_debt"]
    frame["net_working_capital"] = (operating_assets - operating_liabilities).clip(lower=0.0)
    frame["capital"] = frame["net_working_capital"] + frame["net_fixed_assets"]
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


def _number(value):
    """A finite float rounded for display, or None (JSON has no NaN)."""
    return None if value is None or not np.isfinite(value) else round(float(value), 2)


def valuation_check(stocks):
    """{ticker: valuation facts + a label} — is the stock expensive RIGHT NOW, whatever its momentum?

    The label comes from the earnings yield (operating income / enterprise value: the profit the
    whole business earns per dollar it costs to buy, debt included), compared with the other
    stocks in `stocks`: the highest-yield third is "cheap", the middle "fair", the lowest
    "expensive"; a company with no operating profit is "no profits". Financials are not labelled
    (enterprise value is meaningless for a bank's balance sheet), nor is anything missing data.
    The other numbers (forward P/E, PEG, price/sales, analysts' target) are shown as context.
    """
    frame = pd.DataFrame(stocks).copy()
    missing = [c for c in RANKING_COLUMNS if c not in frame.columns]
    if missing:
        raise ConfigurationError(f"valuation_check input is missing columns {missing}")
    for column in NUMERIC_COLUMNS + VALUATION_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    enterprise_value = frame["market_cap"] + frame["total_debt"] - frame["cash"]
    financial = frame["sector"].astype(str).str.strip().str.lower().map(
        lambda sector: sector in EXCLUDED_SECTORS and EXCLUDED_SECTORS[sector] == "financial sector")
    usable = frame["ebit"].notna() & (enterprise_value > 0) & ~financial
    frame["earnings_yield"] = (frame["ebit"] / enterprise_value).where(usable)
    profitable = frame["earnings_yield"] > 0
    percentile = frame.loc[profitable, "earnings_yield"].rank(pct=True)
    labels = pd.Series([None] * len(frame), index=frame.index, dtype=object)   # None = not labelled
    labels[usable & ~profitable] = NO_PROFITS
    labels[percentile.index] = np.where(percentile > 2 / 3, CHEAP, np.where(percentile > 1 / 3, FAIR, EXPENSIVE))
    frame["label"] = labels
    target_upside = (frame["target_price"] / frame["price"] - 1.0).where(frame["price"] > 0) * 100
    return {row["ticker"]: {"label": labels[index],
                            "ey_pct": _number(row["earnings_yield"] * 100),
                            "forward_pe": _number(row["forward_pe"]), "trailing_pe": _number(row["trailing_pe"]),
                            "peg": _number(row["peg"]), "price_to_sales": _number(row["price_to_sales"]),
                            "target_upside_pct": _number(target_upside[index])}
            for index, row in frame.iterrows()}


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


EARNINGS_ROW = "Operating Income"


def _trailing_operating_income(quarterly, annual):
    """Operating income of the last 4 reported quarters; the latest fiscal year when 4 are not available."""
    if quarterly is not None and not quarterly.empty and EARNINGS_ROW in quarterly.index:
        last_four = quarterly.loc[EARNINGS_ROW].iloc[:4]
        if len(last_four) == 4 and last_four.notna().all():
            return float(last_four.sum())
    return _latest(annual, EARNINGS_ROW)


def _debt(balance, row):
    """A debt line of the balance sheet. A company with no borrowings has NO such line on Yahoo,
    so when the balance sheet itself is present an absent line means 0 (not 'unknown')."""
    if balance is None or balance.empty:
        return None
    value = _latest(balance, row)
    return 0.0 if value is None else value


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
        "ebit": _trailing_operating_income(source.quarterly_income_stmt, source.income_stmt),
        "current_assets": _latest(balance, "Current Assets"),
        "current_liabilities": _latest(balance, "Current Liabilities"),
        "net_fixed_assets": _latest(balance, "Net PPE"),
        "total_debt": _debt(balance, "Total Debt"),
        "cash": _latest(balance, "Cash And Cash Equivalents"),
        "excess_cash": _latest(balance, "Cash Cash Equivalents And Short Term Investments"),
        "short_term_debt": _debt(balance, "Current Debt"),
        **{column: _info_value(info, key) for column, key in VALUATION_INFO_KEYS.items()},
        **{column: _info_value(info, key) for column, key in PROFILE_INFO_KEYS.items()},
    }


def _load_cache(cache_path):
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path) as fh:
        return json.load(fh)


def _has_columns(entry, columns):
    return set(columns) <= set(entry["row"])


def _is_fresh(entry, today):
    """Fetched within the week AND holding every column this version fetches. A row from an older
    version is refetched, but stays usable meanwhile for whatever columns it does have (so adding
    a field never empties the app while Yahoo's throttling spreads the refetch over several days)."""
    return ((today - date.fromisoformat(entry["fetched"])).days <= CACHE_MAX_AGE_DAYS
            and _has_columns(entry, FETCHED_COLUMNS))


def _save_cache(cache, cache_path):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(cache, fh, indent=0, sort_keys=True)


def refresh_cache(tickers, cache_path=CACHE_PATH, refresh=False):
    """Fetch every ticker whose cached row is missing / older than a week (see yahoo_batches);
    returns how the refresh ended ('up to date' / 'refreshed' / 'interrupted ...')."""
    today = date.today()
    cache = _load_cache(cache_path)
    stale = [t for t in tickers if refresh or t not in cache or not _is_fresh(cache[t], today)]

    def save(rows):
        for row in rows:
            cache[row["ticker"]] = {"fetched": today.isoformat(), "row": row}
        _save_cache(cache, cache_path)

    return yahoo_batches.fetch_in_batches(stale, _fetch_one, save)


def company_profiles(tickers, cache_path=CACHE_PATH):
    """{ticker: profile} (name, sector, industry, business summary, website, employees) from the cache."""
    cache = _load_cache(cache_path)
    return {t: {"sector": cache[t]["row"]["sector"], **{c: cache[t]["row"][c] for c in PROFILE_COLUMNS}}
            for t in tickers if t in cache and _has_columns(cache[t], FETCHED_COLUMNS)}


def cached_fundamentals(tickers, cache_path=CACHE_PATH):
    """(DataFrame with RANKING_COLUMNS, as_of) for the tickers whose cached row has them;
    as_of = the OLDEST fetch date among them (how stale the list can be)."""
    cache = _load_cache(cache_path)
    known = [t for t in tickers if t in cache and _has_columns(cache[t], RANKING_COLUMNS)]
    frame = pd.DataFrame([{c: cache[t]["row"][c] for c in RANKING_COLUMNS} for t in known], columns=list(RANKING_COLUMNS))
    as_of = min((cache[t]["fetched"] for t in known), default=None)
    return frame, as_of


def fetch_fundamentals(tickers, cache_path=CACHE_PATH, refresh=False):
    """DataFrame with RANKING_COLUMNS for `tickers` (refreshing rows older than a week)."""
    refresh_cache(tickers, cache_path, refresh)
    return cached_fundamentals(tickers, cache_path)[0]


def daily_section(tickers, top_n=DEFAULT_TOP_N, cache_path=CACHE_PATH):
    """The Magic Formula block of the daily record (signal log / app): the top list and every
    ranked ticker's position, from the weekly-refreshed fundamentals."""
    status = refresh_cache(tickers, cache_path)
    frame, as_of = cached_fundamentals(tickers, cache_path)
    ranked, excluded = magic_formula_pool(frame)
    top = [{"rank": position, "ticker": row["ticker"], "magic_score": int(row["magic_score"]),
            "roc_rank": int(row["roc_rank"]), "ey_rank": int(row["ey_rank"]),
            "roc_pct": round(row["roc"] * 100, 1), "ey_pct": round(row["earnings_yield"] * 100, 1),
            "sector": row["sector"]}
           for position, (_, row) in enumerate(ranked.head(top_n).iterrows(), start=1)]
    return {"as_of": as_of, "status": status, "n_scanned": len(tickers), "n_ranked": len(ranked),
            "n_excluded": len(excluded) + len(tickers) - len(frame), "top": top,
            "ranks": {ticker: position for position, ticker in enumerate(ranked["ticker"], start=1)},
            "valuation": valuation_check(frame) if len(frame) else {}}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(scope, top_n, refresh):
    import universe

    tickers = universe.get_universe(scope)
    print(f"fundamentals: {refresh_cache(tickers, refresh=refresh)}")
    frame, as_of = cached_fundamentals(tickers)
    print(f"{len(frame)} of {len(tickers)} tickers have fundamentals (oldest fetched {as_of})")
    ranked, excluded = magic_formula_pool(frame)
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
    parser.add_argument("--update-only", action="store_true",
                        help="only refresh the fundamentals cache for the daily scan universe (used by CI)")
    args = parser.parse_args(argv)
    if args.update_only:
        import scan_today

        tickers, _sources = scan_today.combined_universe()
        print(f"fundamentals: {refresh_cache(tickers, refresh=args.refresh)}")
        return
    run(args.scope, args.top, args.refresh)


if __name__ == "__main__":
    main()
