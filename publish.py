"""Build the static PWA site (GitHub Pages): the app shell + freshly published data.

    python publish.py --out site                 # real data (needs network: Yahoo)
    python publish.py --out site --demo          # synthetic data, fully offline preview

Writes:
    site/                     the PWA (copied from pwa/, tests excluded)
    site/data/manifest.json   universe lists, production strategy, data date, build id
    site/data/signals.json    today's ranked BUY list + market regime + breadth
    site/data/prices/<T>.json full daily history per ticker (compact format, pwa_format.py)
    site/data/research/       research_results/*.json (the published research reports)

Your positions are NOT here: the PWA keeps them on your device and computes
HOLD/SELL locally from these price files.
"""

import argparse
import json
import os
import shutil
from datetime import date, timedelta

import pandas as pd

import indicators
import universe
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data, prefetch
from pwa_format import encode_bars
from research_portfolio import RESULTS_DIR
from scan_today import (DEFAULT_STOP_MODE, STATE_FILE, TARGET_POSITIONS, daily_report,
                        load_state, production_algorithm, save_state)

HISTORY_START = "2004-01-01"
BENCHMARKS = ("SPY", "QQQ")
LISTS = {"S&P 500": "sp500", "Nasdaq-100": "nasdaq100", "Watchlist": "watchlist",
         "Magic Formula": "magic_formula"}
PUBLISHED_CANDIDATES = 100   # the PWA hides your holdings itself, so publish a deep list
PWA_DIR = "pwa"


def load_universe_frames(end):
    """Every list's tickers + benchmarks, full history; per-ticker failures reported, not raised."""
    tickers = list(dict.fromkeys(universe.get_universe("all") + list(BENCHMARKS)))
    prefetch(tickers, HISTORY_START, end)
    frames, failed = {}, []
    for ticker in tickers:
        try:
            frames[ticker] = fetch_data(ticker, HISTORY_START, end)
        except PER_TICKER_ERRORS as exc:
            failed.append({"ticker": ticker, "error": type(exc).__name__})
    lists = {name: [t for t in universe.get_universe(scope) if t in frames] for name, scope in LISTS.items()}
    return frames, lists, failed


def demo_frames():
    """Synthetic universe for an offline preview (clearly labelled DEMO in the app)."""
    from tests.synthetic import make_ohlcv

    names = [f"DEMO{k:02d}" for k in range(40)]
    frames = {t: make_ohlcv(1000 + k, n_bars=2600, start="2016-01-04") for k, t in enumerate(names)}
    for k, benchmark in enumerate(BENCHMARKS):
        frames[benchmark] = make_ohlcv(77 + k, n_bars=2600, start="2016-01-04")
    lists = {"Demo A": names[:20], "Demo B": names[20:]}
    return frames, lists, []


def market_summary(frames, scan_tickers):
    """SPY regime vs its 200-day MA + breadth (% of the scan universe above its own 200-MA)."""
    spy = frames["SPY"]["Close"]
    spy_ma = indicators.sma(spy, 200)
    above, total = 0, 0
    for ticker in scan_tickers:
        close = frames[ticker]["Close"]
        if len(close) < 200:
            continue
        total += 1
        above += int(close.iloc[-1] > indicators.sma(close, 200).iloc[-1])
    return {
        "spy_close": round(float(spy.iloc[-1]), 2),
        "spy_ma200": round(float(spy_ma.iloc[-1]), 2),
        "spy_vs_ma200_%": round((float(spy.iloc[-1]) / float(spy_ma.iloc[-1]) - 1) * 100, 1),
        "risk_on": bool(spy.iloc[-1] > spy_ma.iloc[-1]),
        "breadth_above_ma200_%": round(above / total * 100, 1) if total else None,
        "breadth_universe": total,
    }


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"), default=str)


def copy_app_shell(out_dir, build_id):
    """Copy pwa/ (minus tests) and stamp the service worker's cache version."""
    shutil.copytree(PWA_DIR, out_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests"))
    sw_path = os.path.join(out_dir, "sw.js")
    with open(sw_path) as fh:
        sw = fh.read()
    if "__BUILD_ID__" not in sw:
        raise ValueError("sw.js is missing the __BUILD_ID__ placeholder")
    with open(sw_path, "w") as fh:
        fh.write(sw.replace("__BUILD_ID__", build_id))


def publish(out_dir, demo, state_path):
    end = (date.today() + timedelta(days=1)).isoformat()   # yfinance's end is exclusive
    frames, lists, failed = demo_frames() if demo else load_universe_frames(end)
    data_date = frames["SPY"].index[-1].strftime("%Y-%m-%d")
    build_id = f"{data_date}-{pd.Timestamp.now(tz='UTC').strftime('%H%M%S')}"
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    copy_app_shell(out_dir, build_id)
    data_dir = os.path.join(out_dir, "data")

    algorithm = production_algorithm()
    scan_tickers = sorted(set(t for names in lists.values() for t in names) - set(BENCHMARKS))
    scan_frames = {t: frames[t] for t in scan_tickers}
    sources = {t: "/".join(n for n, names in lists.items() if t in names) for t in scan_tickers}
    report, state = daily_report(algorithm, load_state(state_path), data_date, frames=scan_frames,
                                 top_n=PUBLISHED_CANDIDATES, scan_universe=(scan_tickers, sources))
    save_state(state, state_path)
    report["market"] = market_summary(frames, scan_tickers)
    report["demo"] = demo
    _write_json(os.path.join(data_dir, "signals.json"), report)

    for ticker, df in frames.items():
        _write_json(os.path.join(data_dir, "prices", f"{ticker}.json"), encode_bars(ticker, df))

    _write_json(os.path.join(data_dir, "manifest.json"), {
        "build": build_id, "data_date": data_date, "demo": demo,
        "tickers": sorted(frames), "lists": lists, "benchmarks": list(BENCHMARKS),
        "failed": failed,
        "production": {"strategy": algorithm.name, "config": algorithm.config,
                       "stop_mode": DEFAULT_STOP_MODE, "target_positions": TARGET_POSITIONS},
    })

    research_out = os.path.join(data_dir, "research")
    os.makedirs(research_out, exist_ok=True)
    if os.path.isdir(RESULTS_DIR):
        for name in os.listdir(RESULTS_DIR):
            if name.endswith(".json"):
                shutil.copy(os.path.join(RESULTS_DIR, name), research_out)
    if not os.path.exists(os.path.join(research_out, "index.json")):
        _write_json(os.path.join(research_out, "index.json"), {})
    print(f"Published {len(frames)} tickers ({len(failed)} failed), {report['n_candidates']} BUY "
          f"candidates, data as of {data_date} -> {out_dir}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the PWA site with fresh data.")
    parser.add_argument("--out", default="site")
    parser.add_argument("--demo", action="store_true", help="synthetic offline data (preview only)")
    parser.add_argument("--state", default=STATE_FILE, help="rank-history file (kept between runs)")
    args = parser.parse_args(argv)
    publish(args.out, args.demo, args.state)


if __name__ == "__main__":
    main()
