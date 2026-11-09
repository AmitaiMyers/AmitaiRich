"""Point-in-time fundamentals from SEC EDGAR (revenue, diluted EPS, net income).

    SEC_USER_AGENT="Name contact@example.com" python fundamentals_pit.py update

Source: the free XBRL "companyfacts" API (one JSON per company). Every fact carries the date it
was FILED, which is what makes a backtest honest: a value is usable only from its original
filing date. Later restatements of the same period are ignored (the original figure is what
the market knew), so nothing leaks backwards.

Output (MARKET_DATA_DIR/fundamentals/quarterly.parquet), one row per (ticker, metric, quarter):
    ticker, metric, period_end, value, available (= original filing date), derived
Quarters are 3-month facts; a Q4 that is only reported inside the 10-K is derived as
FY minus the 9-month year-to-date figure and becomes available on the 10-K filing date.

SEC requires a contact in the User-Agent (fair-access policy): set SEC_USER_AGENT. It is read
from the environment and never stored in the repository.
"""

import json
import os
import sys
import time

import pandas as pd
import requests

from errors import ConfigurationError

DATA_DIR = os.environ.get("MARKET_DATA_DIR", "market_data")
FUND_DIR = os.path.join(DATA_DIR, "fundamentals")
EXTRACTED_DIR = os.path.join(FUND_DIR, "by_cik")
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
REQUEST_PAUSE = 0.12          # stay under SEC's 10 requests/second

# Metric -> XBRL tags in priority order (companies switch tags over the years; all are merged).
TAGS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet"),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
}
QUARTER_DAYS = (80, 100)
NINE_MONTH_DAYS = (260, 285)
YEAR_DAYS = (350, 380)


def _user_agent():
    if "SEC_USER_AGENT" not in os.environ:
        raise ConfigurationError(
            "Set SEC_USER_AGENT to 'Name contact-email' (SEC requires a contact for API access).")
    return os.environ["SEC_USER_AGENT"]


def _get_json(url):
    response = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=60)
    response.raise_for_status()
    time.sleep(REQUEST_PAUSE)
    return response.json()


def ticker_to_cik(refresh=False):
    """{ticker (Yahoo form): CIK int} for currently-registered SEC filers."""
    path = os.path.join(FUND_DIR, "company_tickers.json")
    if refresh or not os.path.exists(path):
        os.makedirs(FUND_DIR, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(_get_json(TICKER_MAP_URL), fh)
    with open(path) as fh:
        rows = json.load(fh).values()
    return {row["ticker"].upper().replace(".", "-"): int(row["cik_str"]) for row in rows}


def _extracted_path(cik):
    return os.path.join(EXTRACTED_DIR, f"{cik}.parquet")


def download_companyfacts(ciks, max_age_days=7):
    """Fetch each company's facts and keep only the extracted quarterly series.

    The raw JSON (~4 MB per company) is parsed in memory and discarded; only the small
    per-company parquet is cached (re-fetched when older than max_age_days). Returns the CIKs
    SEC has no XBRL financial data for (HTTP 404, e.g. some foreign filers).
    """
    os.makedirs(EXTRACTED_DIR, exist_ok=True)
    now = time.time()
    todo = [c for c in ciks if not os.path.exists(_extracted_path(c))
            or now - os.path.getmtime(_extracted_path(c)) > max_age_days * 86400]
    missing = []
    for k, cik in enumerate(todo, start=1):
        response = requests.get(FACTS_URL.format(cik=cik), headers={"User-Agent": _user_agent()}, timeout=60)
        time.sleep(REQUEST_PAUSE)
        if response.status_code == 404:
            missing.append(cik)
            continue
        response.raise_for_status()
        raw = response.json()
        series = [quarterly_series(raw, metric).assign(metric=metric) for metric in TAGS]
        pd.concat(series, ignore_index=True).to_parquet(_extracted_path(cik))
        if k % 100 == 0 or k == len(todo):
            print(f"  edgar: {k}/{len(todo)} companies", flush=True)
    return missing


def _facts(raw, tags):
    """All USD (or USD/share) facts for the given tags as one DataFrame."""
    gaap = raw["facts"]["us-gaap"] if "us-gaap" in raw["facts"] else {}
    rows = []
    for tag in tags:
        if tag not in gaap:
            continue
        for unit, facts in gaap[tag]["units"].items():
            if not unit.startswith("USD"):
                continue
            for fact in facts:
                if "start" in fact:     # duration facts only (income-statement items)
                    rows.append((pd.Timestamp(fact["start"]), pd.Timestamp(fact["end"]),
                                 float(fact["val"]), pd.Timestamp(fact["filed"])))
    return pd.DataFrame(rows, columns=["start", "end", "val", "filed"])


def _first_filed(facts):
    """Keep each (start, end) period's ORIGINAL value: the earliest filing wins."""
    return facts.sort_values("filed").drop_duplicates(["start", "end"], keep="first")


def _in(days, bounds):
    return (days >= bounds[0]) & (days <= bounds[1])


def quarterly_series(raw, metric):
    """Point-in-time quarterly values of one metric: period_end, value, available, derived."""
    facts = _facts(raw, TAGS[metric])
    if facts.empty:
        return pd.DataFrame(columns=["period_end", "value", "available", "derived"])
    facts = _first_filed(facts)
    days = (facts["end"] - facts["start"]).dt.days
    quarters = facts[_in(days, QUARTER_DAYS)].assign(derived=False)
    nine = facts[_in(days, NINE_MONTH_DAYS)]
    years = facts[_in(days, YEAR_DAYS)]
    # Derive Q4 = FY - 9M YTD for fiscal years whose 4th quarter is not filed as a 3-month fact.
    q4 = years.merge(nine, on="start", suffixes=("_fy", "_9m"))
    q4 = pd.DataFrame({
        "start": q4["end_9m"] + pd.Timedelta(days=1), "end": q4["end_fy"],
        "val": q4["val_fy"] - q4["val_9m"],
        "filed": q4[["filed_fy", "filed_9m"]].max(axis=1), "derived": True,
    })
    combined = pd.concat([quarters, q4], ignore_index=True)
    combined = combined.sort_values(["end", "derived"]).drop_duplicates("end", keep="first")
    return pd.DataFrame({"period_end": combined["end"].to_numpy(), "value": combined["val"].to_numpy(),
                         "available": combined["filed"].to_numpy(),
                         "derived": combined["derived"].to_numpy()}).sort_values("period_end")


def build_quarterly_table(tickers):
    """One long table (ticker, metric, period_end, value, available, derived) for all tickers."""
    cik_of = ticker_to_cik()
    frames = [pd.read_parquet(_extracted_path(cik_of[t])).assign(ticker=t)
              for t in tickers if t in cik_of and os.path.exists(_extracted_path(cik_of[t]))]
    table = pd.concat(frames, ignore_index=True)
    table.to_parquet(os.path.join(FUND_DIR, "quarterly.parquet"))
    return table


def load_quarterly():
    return pd.read_parquet(os.path.join(FUND_DIR, "quarterly.parquet"))


def _cli(argv):
    import universe_history

    if argv[:1] != ["update"]:
        print("usage: SEC_USER_AGENT='Name email' python fundamentals_pit.py update")
        sys.exit(1)
    tickers = universe_history.research_universe()
    cik_of = ticker_to_cik(refresh=True)
    ciks = sorted({cik_of[t] for t in tickers if t in cik_of})
    print(f"{len(ciks)} of {len(tickers)} research tickers are current SEC filers", flush=True)
    missing = download_companyfacts(ciks)
    table = build_quarterly_table(tickers)
    print(f"no XBRL facts for {len(missing)} filers; table rows {len(table)}, "
          f"tickers {table['ticker'].nunique()}")


if __name__ == "__main__":
    _cli(sys.argv[1:])
