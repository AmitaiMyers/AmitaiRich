"""The vectorized engine must reproduce the original per-slice engine exactly.

tests/legacy/ holds a frozen copy of the pre-refactor algorithms / simulation (which
recomputed every indicator on `history.iloc[:i+1]` at every bar — lookahead-free by
construction). These tests prove the refactor changed nothing observable:

  * per bar: scan_and_buy / compute_stop / calculate_sell agree with the legacy
    implementation for every strategy and a spread of configs;
  * causality: signals computed once on the full history equal signals computed on
    the history truncated at each bar (no indicator peeks ahead);
  * per run: run_simulation produces the identical trade ledger and equity curve.

Run: python -m unittest discover -s tests -t .
"""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

import algorithms
import database
import simulation
from errors import ConfigurationError
from simulation import Position
from tests.legacy import legacy_algorithms, legacy_simulation
from tests.synthetic import make_ohlcv

# (strategy name, config overrides) — defaults plus variants that reach every branch.
CASES = [(name, {}) for name in algorithms.ALGORITHMS] + [
    ("Roof: 52-Week-High Breakout", {"exit_mode": "structural", "roof_lookback": 60}),
    ("Roof: 52-Week-High Breakout", {"exit_mode": "target", "roof_lookback": 60,
                                     "min_base_bars": 20, "base_max_range": 0.25}),
    ("Roof: 52-Week-High Breakout", {"use_htf": 1, "roof_lookback": 60, "vol_surge_mult": 0}),
    ("Roof: Pivot-Resistance Breakout", {"vol_surge_mult": 0, "roof_lookback": 60, "base_bars": 10}),
    ("Roof: Volatility-Squeeze Breakout", {"bandwidth_threshold": 0.2, "vol_surge_mult": 1.0}),
    ("Bollinger Squeeze + Volume Breakout", {"bandwidth_threshold": 0.2, "vol_breakout_mult": 1.0}),
    ("Squeeze Momentum Breakout", {"bandwidth_threshold": 0.25, "vol_breakout_mult": 1.0,
                                   "mom_threshold": 0.0}),
    ("Trend Follower (Donchian)", {"use_trend_filter": 0}),
    ("Time-Series Momentum (absolute)", {"use_ma_filter": 0}),
    ("Short-Term Momentum (1-week)", {"use_ma_filter": 0, "hold_bars": 3}),
    ("Momentum Rider (ROC + MA exit)", {"mom_threshold": 0.25, "atr_period": 20, "max_ext": 0.4}),
    ("Vol-Adjusted Momentum Rider", {"score_threshold": 2.0}),
    ("Efficiency-Ratio Trend Rider", {"er_threshold": 0.2, "proximity": 0.85}),
]

SEEDS = (3, 11)


def _legacy(name, config):
    return legacy_algorithms.build_algorithm(name, config)


def _new(name, config):
    return algorithms.build_algorithm(name, config)


def _sample_bars(df, new_algo, n_random=25, seed=0):
    """Bars to compare: every entry bar plus a random spread after warmup."""
    warmup = new_algo.warmup_bars()
    entries = np.flatnonzero(new_algo.signals(df).entry)
    rng = np.random.default_rng(seed)
    random_bars = rng.integers(warmup, len(df), size=n_random)
    return sorted(set(entries[:40].tolist()) | set(random_bars.tolist()))


def _stop_or_error(algo, entry, history, mode):
    try:
        return algo.compute_stop(entry, history, mode)
    except ConfigurationError:
        return "unprotectable"


class PerBarParityTest(unittest.TestCase):
    def test_every_strategy_matches_legacy_bar_by_bar(self):
        for name, config in CASES:
            for seed in SEEDS:
                df = make_ohlcv(seed, n_bars=700)
                new_algo, old_algo = _new(name, config), _legacy(name, config)
                for i in _sample_bars(df, new_algo, seed=seed):
                    history = df.iloc[: i + 1]
                    label = f"{name} {config} seed={seed} bar={i}"
                    with self.subTest(label):
                        self.assertEqual(new_algo.scan_and_buy(history),
                                         bool(old_algo.scan_and_buy(history)), "scan_and_buy")
                        entry = float(history["Close"].iloc[-1])
                        for mode in ("tightest", "widest"):
                            self.assertEqual(_stop_or_error(new_algo, entry, history, mode),
                                             _stop_or_error(old_algo, entry, history, mode), mode)
                        self._assert_sell_matches(new_algo, old_algo, df, i)

    def _assert_sell_matches(self, new_algo, old_algo, df, i):
        bars_held = min(30, i - new_algo.warmup_bars())
        if bars_held < 1:
            return
        entry_bar = i - bars_held
        entry_price = float(df["Close"].iloc[entry_bar])
        stop = _stop_or_error(old_algo, entry_price, df.iloc[: entry_bar + 1], "tightest")
        stop = None if stop == "unprotectable" else stop
        position = Position(entry_date="x", entry_price=entry_price, shares=1.0,
                            stop_price=stop, bars_held=bars_held)
        history = df.iloc[: i + 1]
        try:
            expected = bool(old_algo.calculate_sell(position, history))
        except ConfigurationError:
            with self.assertRaises(ConfigurationError):
                new_algo.calculate_sell(position, history)
            return
        self.assertEqual(new_algo.calculate_sell(position, history), expected, "calculate_sell")


class CausalityTest(unittest.TestCase):
    """Signals on the full history must equal signals on the history truncated at bar i."""

    def test_full_history_signals_equal_truncated_signals(self):
        df = make_ohlcv(5, n_bars=600)
        for name, config in CASES:
            algo = _new(name, config)
            full = algo.signals(df)
            for i in range(algo.warmup_bars(), len(df), 37):
                truncated = algo.signals(df.iloc[: i + 1])
                with self.subTest(f"{name} {config} bar={i}"):
                    self.assertEqual(full.entry[i], truncated.entry[-1])
                    self.assertEqual(full.exit[i], truncated.exit[-1])
                    np.testing.assert_array_equal(full.score[i], truncated.score[-1])
                    for full_level, cut_level in zip(full.stop_levels, truncated.stop_levels):
                        np.testing.assert_array_equal(full_level[i], cut_level[-1])


class MomentumCapTest(unittest.TestCase):
    """max_mom (not in the frozen legacy engine): blocks exactly the buys whose momentum exceeds it."""

    def test_cap_removes_only_overextended_entries(self):
        df = make_ohlcv(3, n_bars=900)
        base = _new("Momentum Rider (ROC + MA exit)", {"mom_threshold": 0.1})
        capped = _new("Momentum Rider (ROC + MA exit)", {"mom_threshold": 0.1, "max_mom": 0.5})
        free, cut = base.signals(df), capped.signals(df)
        momentum = free.score
        np.testing.assert_array_equal(cut.entry, free.entry & (momentum <= 0.5))
        np.testing.assert_array_equal(cut.exit, free.exit)
        self.assertTrue((free.entry & ~cut.entry).any(), "test data never exceeds the cap")
        for i in range(capped.warmup_bars(), len(df), 37):
            self.assertEqual(cut.entry[i], capped.signals(df.iloc[: i + 1]).entry[-1])   # causal


def _ledger(module, df, buy, sell, **kwargs):
    """Run a module's run_simulation on `df` (fetch patched) -> (trades rows, equity)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "parity.db")
        with mock.patch.object(module, "fetch_data", return_value=df):
            run_id = module.run_simulation("TEST", "2000-01-01", "2100-01-01", 100_000.0,
                                           buy, sell, db_path=db_path, **kwargs)
        conn = database.get_connection(db_path)
        trades = database.get_trades(conn, run_id)[["trade_type", "date", "price", "shares"]]
        equity = database.get_equity_curve(conn, run_id)[["date", "total_equity"]]
        conn.close()
    return trades, equity


class RunSimulationParityTest(unittest.TestCase):
    def test_trade_ledgers_identical_to_legacy(self):
        df = make_ohlcv(21, n_bars=650)
        for name, config in CASES[: len(algorithms.ALGORITHMS)] + CASES[-6:]:
            has_stop = _new(name, config).signals(df.iloc[:400]).has_stop
            sizing = "risk_based" if has_stop else "all_in"
            for fill_mode in ("close", "next_open"):
                with self.subTest(f"{name} {config} {fill_mode}"):
                    kwargs = {"fill_mode": fill_mode, "sizing_mode": sizing, "stop_mode": "widest"}
                    try:
                        old_trades, old_equity = _ledger(legacy_simulation, df, _legacy(name, config),
                                                         _legacy(name, config), **kwargs)
                    except ConfigurationError:
                        with self.assertRaises(ConfigurationError):
                            _ledger(simulation, df, _new(name, config), _new(name, config), **kwargs)
                        continue
                    new_trades, new_equity = _ledger(simulation, df, _new(name, config),
                                                     _new(name, config), **kwargs)
                    self.assertEqual(old_trades.to_dict("records"), new_trades.to_dict("records"))
                    self.assertEqual(old_equity["date"].tolist(), new_equity["date"].tolist())
                    np.testing.assert_allclose(old_equity["total_equity"], new_equity["total_equity"],
                                               rtol=0, atol=1e-6)

    def test_mixed_buy_and_sell_algorithms(self):
        df = make_ohlcv(8, n_bars=650)
        pairs = [("Vol-Adjusted Momentum Rider", "Growth Rider (momentum + chandelier)"),
                 ("Momentum Rider (ROC + MA exit)", "Trend Follower (Donchian)")]
        for buy_name, sell_name in pairs:
            with self.subTest(f"{buy_name} -> {sell_name}"):
                old = _ledger(legacy_simulation, df, _legacy(buy_name, {}), _legacy(sell_name, {}))
                new = _ledger(simulation, df, _new(buy_name, {}), _new(sell_name, {}))
                self.assertEqual(old[0].to_dict("records"), new[0].to_dict("records"))


if __name__ == "__main__":
    unittest.main()
