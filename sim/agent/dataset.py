"""Build the daily training dataset for the DQN agent.

For a universe of tickers, downloads **daily** OHLCV candles over a long history,
computes every indicator (see `features.py`), and saves a train/validation split
to `models/daily_dataset.npz`. The split is **temporal per ticker** (train = the
earlier part of each ticker's history, validation = the most recent slice) so the
agent is validated on data that comes strictly after what it trained on — no
lookahead across the split.

Usage (from the repo root):
    python -m sim.agent.dataset                          # nasdaq100, 2015->today
    python -m sim.agent.dataset --scope sp500_ndx --limit 120
    python -m sim.agent.dataset --start 2016-01-01 --val-frac 0.2 --limit 40

Per-ticker download/validation failures are caught and reported (a few bad symbols
never abort the whole build), mirroring batch.py's error policy.
"""

import argparse
import os
import sys
from datetime import date

import numpy as np

from errors import SimulatorError
from data_engine import fetch_data
from universe import get_universe
from sim.agent.features import build_features, FEATURE_NAMES, group_columns

DATASET_PATH = os.path.join("models", "daily_dataset.npz")
MIN_ROWS = 120  # a ticker needs at least this many post-warmup daily bars to be useful


def build_dataset(scope="nasdaq100", limit=None, start="2015-01-01", end=None,
                  val_frac=0.2, out_path=DATASET_PATH):
    end = end or date.today().isoformat()
    symbols = get_universe(scope)
    if limit:
        symbols = symbols[:limit]

    print(f"Building daily dataset: {len(symbols)} symbols, {start}..{end}, "
          f"val_frac={val_frac}, {len(FEATURE_NAMES)} features.\n")

    tr_feats, tr_close, tr_syms, tr_dates = [], [], [], []
    va_feats, va_close, va_syms, va_dates = [], [], [], []
    failures = []

    for i, sym in enumerate(symbols, 1):
        try:
            df = fetch_data(sym, start, end, interval="1d")
            feats, close = build_features(df)
            if len(feats) < MIN_ROWS:
                failures.append((sym, f"only {len(feats)} usable rows"))
                continue
            split = int(len(feats) * (1.0 - val_frac))
            fmat = feats.to_numpy(dtype=np.float32)
            cvec = close.to_numpy(dtype=np.float32)
            dvec = np.array([str(ts.date()) for ts in feats.index])   # real calendar dates
            tr_feats.append(fmat[:split]); tr_close.append(cvec[:split]); tr_syms.append(sym); tr_dates.append(dvec[:split])
            va_feats.append(fmat[split:]); va_close.append(cvec[split:]); va_syms.append(sym); va_dates.append(dvec[split:])
            print(f"[{i}/{len(symbols)}] {sym}: {len(feats)} rows -> train {split}, val {len(feats)-split}")
        except SimulatorError as exc:
            failures.append((sym, str(exc)[:90]))
            print(f"[{i}/{len(symbols)}] {sym}: SKIP ({str(exc)[:60]})")

    if not tr_feats:
        raise SimulatorError("No usable tickers — dataset is empty. Check network / universe cache.")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    meta = {"scope": scope, "start": start, "end": end, "val_frac": val_frac,
            "n_symbols": len(tr_syms), "features": FEATURE_NAMES}
    np.savez_compressed(
        out_path,
        feature_names=np.array(FEATURE_NAMES),
        train_features=np.array(tr_feats, dtype=object),
        train_closes=np.array(tr_close, dtype=object),
        train_tickers=np.array(tr_syms),
        train_dates=np.array(tr_dates, dtype=object),
        val_features=np.array(va_feats, dtype=object),
        val_closes=np.array(va_close, dtype=object),
        val_tickers=np.array(va_syms),
        val_dates=np.array(va_dates, dtype=object),
        meta=np.array(meta, dtype=object),
    )
    tr_rows = sum(len(f) for f in tr_feats)
    va_rows = sum(len(f) for f in va_feats)
    print(f"\nSaved {out_path}")
    print(f"  {len(tr_syms)} tickers | train rows {tr_rows:,} | val rows {va_rows:,} | features {len(FEATURE_NAMES)}")
    if failures:
        print(f"  {len(failures)} symbols skipped:")
        for sym, why in failures[:15]:
            print(f"    - {sym}: {why}")
    return out_path


def load_dataset(path=DATASET_PATH):
    """Load the saved dataset. Returns a dict of lists/arrays."""
    if not os.path.exists(path):
        raise SimulatorError(f"Dataset not found at {path}. Run 'python -m sim.agent.dataset' first.")
    d = np.load(path, allow_pickle=True)
    has_dates = "train_dates" in d.files
    tr_dates = list(d["train_dates"]) if has_dates else [None] * len(d["train_tickers"])
    va_dates = list(d["val_dates"]) if has_dates else [None] * len(d["val_tickers"])
    return {
        "feature_names": list(d["feature_names"]),
        # 4-tuples: (ticker, features[T,F], closes[T], dates[T] or None)
        "train": list(zip(d["train_tickers"], d["train_features"], d["train_closes"], tr_dates)),
        "val": list(zip(d["val_tickers"], d["val_features"], d["val_closes"], va_dates)),
        "meta": d["meta"].item(),
    }


def select_indicators(data, groups):
    """Return a copy of a loaded dataset keeping only the chosen indicator groups.

    Columns are sliced from the full feature matrices — the dataset never needs
    rebuilding to change the indicator mix.
    """
    idx, names = group_columns(data["feature_names"], groups)
    cols = np.array(idx)

    def slice_rows(rows):
        return [(ticker, feats[:, cols], closes, dates) for ticker, feats, closes, dates in rows]

    return {
        "feature_names": names,
        "train": slice_rows(data["train"]),
        "val": slice_rows(data["val"]),
        "meta": data["meta"],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Build the daily DQN training dataset.")
    p.add_argument("--scope", default="nasdaq100", help="Universe scope (sp500 / nasdaq100 / sp500_ndx / watchlist).")
    p.add_argument("--limit", type=int, default=None, help="Cap the number of tickers (for a quicker build).")
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=None, help="Default: today.")
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--out", default=DATASET_PATH)
    args = p.parse_args(argv)
    build_dataset(scope=args.scope, limit=args.limit, start=args.start, end=args.end,
                  val_frac=args.val_frac, out_path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
