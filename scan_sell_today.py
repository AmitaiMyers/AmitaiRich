"""Daily 'should I sell?' scan for the stocks you currently hold.

Counterpart to scan_today.py's BUY scan. Reads your open positions from a CSV
(ticker, entry_date, entry_price) and, for each, runs scan_today.check_holding to
get today's verdict: SELL if today's bar hits the stop set at entry OR the
strategy's discretionary exit (the trailing chandelier) fires; otherwise HOLD.

Per-position data failures (bad symbol, an entry date after the last bar) are
collected and reported, not raised — same boundary policy as batch.py. A
ConfigurationError (missing file / columns — a setup mistake) is NOT caught.

CLI:  python scan_sell_today.py [positions.csv]
"""

import os
import sys

import pandas as pd

from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from errors import ConfigurationError
from scan_today import DEFAULT_BUY, DEFAULT_CONFIG, check_holding

POSITIONS_FILE = "positions.csv"
REQUIRED_COLUMNS = ("ticker", "entry_date", "entry_price")

# The same Roof strategy as the BUY scan supplies the stop; its trailing
# (chandelier) exit is the discretionary sell signal. exit_mode "trailing" is the
# strategy default, named here so the sell rule is explicit.
SELL_CONFIG = {**DEFAULT_CONFIG, "exit_mode": "trailing"}
STOP_MODE = "tightest"


def load_positions(path):
    """Read and validate the open-positions CSV. Fail fast on setup mistakes."""
    if not os.path.exists(path):
        raise ConfigurationError(
            f"positions file {path!r} not found. Create it with columns {REQUIRED_COLUMNS}."
        )
    positions = pd.read_csv(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in positions.columns]
    if missing:
        raise ConfigurationError(
            f"{path}: missing required columns {missing}; got {list(positions.columns)}."
        )
    if positions.empty:
        raise ConfigurationError(f"{path}: no positions listed.")
    return positions


def _entry_price(value):
    """An empty entry_price cell means 'use the entry-bar close' (check_holding default)."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def scan_holdings(positions, algorithm, as_of=None, stop_mode=STOP_MODE,
                  interval="1d", use_cache=True):
    """Return (verdicts, errors) DataFrames: today's HOLD/SELL call per position."""
    verdicts, errors = [], []

    for row in positions.itertuples(index=False):
        ticker = str(row.ticker).strip().upper()
        try:
            verdict = check_holding(
                ticker, algorithm,
                entry_date=str(row.entry_date).strip(),
                entry_price=_entry_price(row.entry_price),
                as_of=as_of, stop_mode=stop_mode, interval=interval, use_cache=use_cache,
            )
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__, "detail": str(exc)})
            continue
        verdicts.append(verdict)

    verdicts_df = pd.DataFrame(verdicts)
    if not verdicts_df.empty:
        # SELLs first, then by largest open loss, so the most urgent sit on top.
        verdicts_df = verdicts_df.sort_values(
            ["verdict", "open_pnl_%"], ascending=[False, True]
        ).reset_index(drop=True)
    return verdicts_df, pd.DataFrame(errors)


def _cli():
    path = sys.argv[1] if len(sys.argv) > 1 else POSITIONS_FILE
    positions = load_positions(path)
    algorithm = build_algorithm(DEFAULT_BUY, SELL_CONFIG)
    print(f"Checking {len(positions)} holding(s) from {path} "
          f"with {DEFAULT_BUY} (trailing exit, {STOP_MODE} stop)...", flush=True)
    verdicts, errors = scan_holdings(positions, algorithm)

    sells = verdicts[verdicts["verdict"] == "SELL"] if not verdicts.empty else verdicts
    print(f"\n=== SELL/HOLD verdicts ({len(verdicts)} positions, {len(sells)} SELL) ===")
    if verdicts.empty:
        print("  (no verdicts)")
    else:
        print(verdicts.to_string(index=False))

    if not errors.empty:
        print(f"\n({len(errors)} position(s) skipped for missing data)")
        print(errors.to_string(index=False))


if __name__ == "__main__":
    _cli()
