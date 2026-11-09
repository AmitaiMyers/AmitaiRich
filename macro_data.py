"""Macro series from FRED (free, no key), with conservative publication lags (no look-ahead).

    python macro_data.py update

Each series is shifted to the date it was actually PUBLISHED before a backtest may use it:
daily market series are usable the next business day; monthly series (CPI, unemployment)
are released about two weeks into the following month, so they are lagged ~45 days.
Output: MARKET_DATA_DIR/macro.parquet (dates x series, value as known on each date).
"""

import io
import os
import sys

import pandas as pd
import requests

DATA_DIR = os.environ.get("MARKET_DATA_DIR", "market_data")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# series -> publication lag (calendar days after the observation date)
SERIES = {
    "DGS10": 1,        # 10-year Treasury yield (daily)
    "DGS2": 1,         # 2-year Treasury yield (daily)
    "T10Y2Y": 1,       # 10y-2y curve slope (daily)
    "BAMLH0A0HYM2": 1, # high-yield credit spread (daily)
    "CPIAUCSL": 45,    # CPI (monthly)
    "UNRATE": 40,      # unemployment rate (monthly)
}


def fetch_series(series_id):
    response = requests.get(FRED_CSV.format(series=series_id), timeout=60)
    response.raise_for_status()
    raw = pd.read_csv(io.StringIO(response.text))
    dates = pd.to_datetime(raw.iloc[:, 0])
    values = pd.to_numeric(raw.iloc[:, 1], errors="coerce")   # FRED marks missing days with '.'
    return pd.Series(values.to_numpy(), index=dates, name=series_id).dropna()


def update_macro():
    known = {}
    for series_id, lag in SERIES.items():
        series = fetch_series(series_id)
        series.index = series.index + pd.Timedelta(days=lag)   # date it became public
        known[series_id] = series
    table = pd.DataFrame(known).sort_index()
    os.makedirs(DATA_DIR, exist_ok=True)
    table.to_parquet(os.path.join(DATA_DIR, "macro.parquet"))
    return table


def load_macro():
    return pd.read_parquet(os.path.join(DATA_DIR, "macro.parquet"))


if __name__ == "__main__":
    if sys.argv[1:2] != ["update"]:
        print("usage: python macro_data.py update")
        sys.exit(1)
    table = update_macro()
    print(table.tail(3).to_string())
