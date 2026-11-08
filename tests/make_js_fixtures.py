"""Generate pwa/tests/fixtures/parity.json: Python engine outputs the JS engine must match.

Synthetic bars go through the shared compact format (pwa_format), so both engines
run on bit-identical inputs. For every JS-supported strategy we record the signals
and full backtests (single stock and multi-stock portfolio, both fill modes); the
Node test (pwa/tests/engine.test.mjs) replays them and demands exact equality.

    python -m tests.make_js_fixtures            # rewrite the fixture
tests/test_js_fixtures.py fails if the committed fixture is stale.
"""

import json
import math
import os

from algorithms import build_algorithm
from engine import EngineConfig, run_engine
from pwa_format import day_number, decode_bars, encode_bars
from scan_today import holding_verdict, production_algorithm
from tests.synthetic import make_universe

FIXTURE_PATH = os.path.join("pwa", "tests", "fixtures", "parity.json")

JS_STRATEGIES = {
    "Momentum Rider (ROC + MA exit)": [{}, {"mom_threshold": 0.25, "atr_period": 20, "exit_confirm": 3}],
    "Vol-Adjusted Momentum Rider": [{}, {"score_threshold": 3.0}],
    "Trend Rider (breakout + MA exit)": [{}],
    "Two-Speed Donchian": [{}],
    "Trend Follower (Donchian)": [{}, {"use_trend_filter": 0}],
    "Dual-Confirm Trend Hold": [{"entry_lookback": 120}],
    "Growth Rider (momentum + chandelier)": [{"mom_threshold": 0.15}],
    "Buy & Hold (benchmark)": [{}],
}

ENGINE_KEYS = {  # Python EngineConfig field -> JS option name
    "starting_capital": "startingCapital", "max_positions": "maxPositions",
    "sizing_mode": "sizingMode", "risk_pct": "riskPct", "cost_bps": "costBps",
    "fill_mode": "fillMode", "stop_mode": "stopMode", "skip_unprotectable": "skipUnprotectable",
}


def _num(x):
    return None if math.isnan(x) else float(x)


def _signals_record(signals):
    return {
        "entry": [int(i) for i, v in enumerate(signals.entry) if v],
        "exit": [int(i) for i, v in enumerate(signals.exit) if v],
        "score": [_num(x) for x in signals.score],
        "stopLevels": [[_num(x) for x in level] for level in signals.stop_levels],
    }


def _run_record(frames, name, config, engine_config):
    algorithm = build_algorithm(name, config)
    result = run_engine(frames, algorithm, algorithm, engine_config)
    return {
        "strategy": name, "config": config,
        "options": {js: getattr(engine_config, py) for py, js in ENGINE_KEYS.items()},
        "tickers": list(frames),
        "trades": [{"ticker": t.ticker, "entryDay": day_number(t.entry_date), "entryPrice": t.entry_price,
                    "stopPrice": t.stop_price, "shares": t.shares, "exitDay": day_number(t.exit_date),
                    "exitPrice": t.exit_price, "exitReason": t.exit_reason, "barsHeld": t.bars_held}
                   for t in result.trades],
        # Every 10th day plus the last: an exact check at a fraction of the size.
        "equitySample": {str(i): float(result.equity.iloc[i])
                         for i in list(range(0, len(result.equity), 10)) + [len(result.equity) - 1]},
        "nEntrySignals": result.n_entry_signals,
    }


def build_fixture():
    raw = make_universe(6, seed=9, n_bars=760)
    encoded = {t: encode_bars(t, df) for t, df in raw.items()}
    frames = {t: decode_bars(e) for t, e in encoded.items()}
    single = {"T00": frames["T00"]}

    signals, runs = [], []
    for name, configs in JS_STRATEGIES.items():
        sizing = "all_in" if name.startswith("Buy & Hold") else "risk_based"
        for config in configs:
            algorithm = build_algorithm(name, config)
            signals.append({"strategy": name, "config": config, "ticker": "T01",
                            **_signals_record(algorithm.signals(frames["T01"]))})
            for fill in ("close", "next_open"):
                runs.append(_run_record(single, name, config, EngineConfig(
                    sizing_mode=sizing, fill_mode=fill, stop_mode="widest")))
            if sizing == "risk_based":
                for fill in ("close", "next_open"):
                    runs.append(_run_record(frames, name, config, EngineConfig(
                        max_positions=3, risk_pct=0.02, cost_bps=10.0, fill_mode=fill,
                        stop_mode="tightest", skip_unprotectable=True)))
    holdings = []
    production = production_algorithm()
    for ticker in ("T00", "T02", "T04"):
        df = frames[ticker]
        for entry_bar, as_of_bar, price in ((300, 420, None), (420, 600, 55.0), (500, len(df) - 1, None)):
            history = df.iloc[: as_of_bar + 1]
            entry_date = df.index[entry_bar].strftime("%Y-%m-%d")
            holdings.append({"ticker": ticker, "entryDate": entry_date, "entryPrice": price,
                             "asOfDay": day_number(history.index[-1]), "stopMode": "widest",
                             "expected": holding_verdict(history, production, entry_date, price, "widest")})
    return {"bars": encoded, "signals": signals, "runs": runs, "holdings": holdings,
            "production": {"strategy": production.name, "config": production.config}}


def fixture_json():
    return json.dumps(build_fixture(), separators=(",", ":"))


def main():
    os.makedirs(os.path.dirname(FIXTURE_PATH), exist_ok=True)
    with open(FIXTURE_PATH, "w") as fh:
        fh.write(fixture_json())
    print(f"Written {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
