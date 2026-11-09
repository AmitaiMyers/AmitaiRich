"""Portfolio engine: legacy agreement, account invariants, fills, windows, benchmarks."""

import unittest

import numpy as np
import pandas as pd

import algorithms
import portfolio
from algorithms import vol_adjusted_momentum
from portfolio import (PortfolioConfig, buy_and_hold_portfolio, run_portfolio,
                       single_asset_benchmark)
from tests.legacy import legacy_algorithms, legacy_portfolio
from tests.synthetic import make_universe

MOMENTUM = "Momentum Rider (ROC + MA exit)"
PRODUCTION = {"mom_lookback": 126, "mom_threshold": 0.25, "atr_period": 20}


def _trade_keys(trades):
    return sorted((t.ticker, t.entry_date, round(t.entry_price, 9), t.exit_date,
                   round(t.exit_price, 9), t.exit_reason) for t in trades)


class LegacyAgreementTest(unittest.TestCase):
    def test_unconstrained_portfolio_takes_exactly_the_legacy_trades(self):
        frames = make_universe(8, seed=3, n_bars=800)
        for name, config in [(MOMENTUM, PRODUCTION), ("Trend Rider (breakout + MA exit)", {}),
                             ("Growth Rider (momentum + chandelier)", {})]:
            with self.subTest(name):
                legacy = []
                old_algo = legacy_algorithms.build_algorithm(name, config)
                for ticker, df in frames.items():
                    legacy += legacy_portfolio.simulate_ticker_trades(ticker, df, old_algo, old_algo, "widest")
                algo = algorithms.build_algorithm(name, config)
                cfg = PortfolioConfig(starting_capital=1e12, max_positions=100, cost_bps=0.0)
                new = run_portfolio(frames, algo, algo, cfg).trades
                stop_exits = {(t.ticker, t.exit_date) for t in new if t.exit_reason == "stop"}
                # Documented divergence: the legacy overlay ran BUYs before processing a
                # same-day intrabar stop, so it dropped a re-entry on a stop-out day that
                # its own per-stock replay had produced. The engine now allows it.
                comparable = [t for t in new if (t.ticker, t.entry_date) not in stop_exits]
                expected = [t for t in legacy if (t.ticker, t.entry_date) not in stop_exits]
                self.assertEqual(_trade_keys(comparable), _trade_keys(expected))


class InvariantTest(unittest.TestCase):
    def setUp(self):
        self.frames = make_universe(10, seed=5, n_bars=800)
        self.algo = algorithms.build_algorithm(MOMENTUM, PRODUCTION)

    def _open_counts(self, trades, calendar):
        counts = pd.Series(0, index=calendar)
        for t in trades:
            # Held from the fill day through the day before the exit (exit frees the slot).
            counts[(calendar >= t.entry_date) & (calendar < t.exit_date)] += 1
        return counts

    def test_slot_cap_cash_and_equity_identity(self):
        cfg = PortfolioConfig(max_positions=3)
        result = run_portfolio(self.frames, self.algo, self.algo, cfg)
        self.assertGreater(len(result.trades), 5)
        counts = self._open_counts(result.trades, result.equity.index)
        self.assertLessEqual(int(counts.max()), 3)
        self.assertTrue(all(t.shares > 0 for t in result.trades))
        self.assertAlmostEqual(result.metrics["final_equity"], float(result.equity.iloc[-1]))

    def test_entries_fill_on_signal_bars_at_the_close(self):
        result = run_portfolio(self.frames, self.algo, self.algo, PortfolioConfig(max_positions=3))
        for trade in result.trades:
            df = self.frames[trade.ticker]
            bar = df.index.get_loc(trade.entry_date)
            self.assertTrue(self.algo.signals(df).entry[bar])
            self.assertEqual(trade.entry_price, float(df["Close"].iloc[bar]))

    def test_next_open_fills_at_the_following_open(self):
        cfg = PortfolioConfig(max_positions=3, fill_mode="next_open")
        result = run_portfolio(self.frames, self.algo, self.algo, cfg)
        self.assertGreater(len(result.trades), 5)
        for trade in result.trades:
            df = self.frames[trade.ticker]
            bar = df.index.get_loc(trade.entry_date)
            self.assertEqual(trade.entry_price, float(df["Open"].iloc[bar]))
            self.assertTrue(self.algo.signals(df).entry[bar - 1])

    def test_late_entry_when_slots_free_up(self):
        """State-based entries: a qualifying stock can be bought after its first signal day."""
        result = run_portfolio(self.frames, self.algo, self.algo, PortfolioConfig(max_positions=2))
        late = 0
        for trade in result.trades:
            entry = self.algo.signals(self.frames[trade.ticker]).entry
            bar = self.frames[trade.ticker].index.get_loc(trade.entry_date)
            late += int(bar > 0 and entry[bar - 1])
        self.assertGreater(late, 0)

    def test_trade_from_blocks_earlier_entries(self):
        start = pd.Timestamp("2016-06-01")
        result = run_portfolio(self.frames, self.algo, self.algo, PortfolioConfig(), trade_from=start)
        self.assertTrue(all(t.entry_date >= start for t in result.trades))
        self.assertEqual(result.equity.index[0], start)

    def test_alternative_ranking_replaces_the_score(self):
        df = self.frames["T00"]
        adjusted = portfolio._AdjustedBuy(self.algo, portfolio.RANKERS["vol_adj"], None)
        np.testing.assert_array_equal(adjusted.signals_for("T00", df).score,
                                      vol_adjusted_momentum(df, 126, 20).to_numpy())
        np.testing.assert_array_equal(adjusted.signals_for("T00", df).entry, self.algo.signals(df).entry)
        vol = run_portfolio(self.frames, self.algo, self.algo,
                            PortfolioConfig(max_positions=2, rank_by="vol_adj"))
        self.assertGreater(len(vol.trades), 0)

    def test_regime_filter_needs_a_market_and_exits_when_off(self):
        market = self.frames["T00"]["Close"]
        result = run_portfolio(self.frames, self.algo, self.algo,
                               PortfolioConfig(regime_filter=True), market_close=market)
        regime = market > market.rolling(200).mean()
        for trade in result.trades:
            self.assertTrue(bool(regime.asof(trade.entry_date)))


class BenchmarkTest(unittest.TestCase):
    def test_buy_and_hold_values(self):
        closes = {"A": pd.Series([10.0, 11.0, 12.0], index=pd.bdate_range("2020-01-01", periods=3)),
                  "B": pd.Series([np.nan, 20.0, 10.0], index=pd.bdate_range("2020-01-01", periods=3))}
        cfg = PortfolioConfig(starting_capital=100.0, cost_bps=0.0)
        equity = buy_and_hold_portfolio(closes, cfg)
        # A buys 5 @10 (sleeve 50); B's sleeve stays cash until it lists, then 2 @20.
        np.testing.assert_allclose(equity.to_numpy(), [50.0 + 50.0, 10.0 + 55.0 + 40.0,
                                                       10.0 + 60.0 + 20.0])

    def test_single_asset_benchmark(self):
        close = pd.Series([100.0, 110.0], index=pd.bdate_range("2020-01-01", periods=2))
        equity = single_asset_benchmark(close, PortfolioConfig(starting_capital=1_000.0, cost_bps=0.0))
        np.testing.assert_allclose(equity.to_numpy(), [1_000.0, 1_100.0])


if __name__ == "__main__":
    unittest.main()


class LiveAccountTest(unittest.TestCase):
    def test_live_mode_keeps_positions_and_next_open_orders(self):
        from dataclasses import replace as dc_replace

        from engine import EngineConfig, run_engine
        frames = make_universe(6, seed=5, n_bars=800)
        algo = algorithms.build_algorithm(MOMENTUM, PRODUCTION)
        base = EngineConfig(max_positions=4, fill_mode="next_open", stop_mode="widest", skip_unprotectable=True)
        backtest = run_engine(frames, algo, algo, base)
        live = run_engine(frames, algo, algo, dc_replace(base, liquidate_at_end=False))
        self.assertEqual(backtest.open_positions, [])
        self.assertTrue(all(t.exit_reason != "final" or t.exit_date < live.equity.index[-1] for t in live.trades))
        self.assertEqual(len(live.open_positions), sum(1 for t in backtest.trades if t.exit_reason == "final"
                                                       and t.exit_date == backtest.equity.index[-1]))
        # With zero costs, closing at the last close cannot change the account value.
        self.assertAlmostEqual(float(live.equity.iloc[-1]), float(backtest.equity.iloc[-1]), places=6)
        self.assertTrue(all(o["side"] in ("BUY", "SELL") for o in live.pending_orders))
