"""RankedStrategy: buys only on rebalance days, top-N, eligible, filtered; exits wired into the engine."""

import unittest

import numpy as np
import pandas as pd

import factors
import strategy_lab
from algo_versions import Version
from engine import EngineConfig, run_engine
from tests.synthetic import make_universe


class FakeLabData:
    """The slice of LabData that RankedStrategy reads, built from synthetic prices."""

    def __init__(self):
        frames = make_universe(12, seed=21, n_bars=800)
        frames["SPY"] = frames.pop("T00")
        self.frames = frames
        self.panel = factors.Panel(frames)
        self.eligible = self.panel.close.notna().copy()
        self.eligible["SPY"] = False
        self.eligible.loc[:, "T05"] = False                      # never a member
        self.market_up = factors.market_uptrend(self.panel)
        self.stock_frames = {t: f for t, f in frames.items() if t != "SPY"}

    def factor(self, name):
        return factors.FACTORS[name].compute(self.panel)


VERSION = Version("t", "test", weights={"mom_6m": 1.0, "trend_200": 1.0}, filters={"stock_above_ma": 200},
                  exits={"ma_break": 200, "rank_drop": True}, rebalance="monthly", max_positions=3)


class RankedStrategyTest(unittest.TestCase):
    def setUp(self):
        self.data = FakeLabData()
        self.strategy = strategy_lab.RankedStrategy(VERSION, self.data)

    def test_entries_only_on_month_ends_top_n_eligible_and_filtered(self):
        entry = self.strategy.entry
        rebalance = strategy_lab.rebalance_days(self.data.panel.dates, "monthly")
        self.assertFalse(entry.loc[~rebalance.to_numpy()].any().any())
        self.assertTrue((entry.sum(axis=1) <= 3).all())
        self.assertGreater(int(entry.sum().sum()), 10)
        self.assertFalse(entry["T05"].any())
        above = self.data.panel.close > factors.sma(self.data.panel.close, 200)
        self.assertFalse((entry & ~above).any().any())

    def test_month_end_days_are_the_last_trading_day_of_each_month(self):
        dates = pd.bdate_range("2021-01-01", "2021-03-31")
        days = strategy_lab.rebalance_days(dates, "monthly")
        self.assertEqual(list(dates[days.to_numpy()]), [pd.Timestamp("2021-01-29"), pd.Timestamp("2021-02-26"),
                                                       pd.Timestamp("2021-03-31")])

    def test_engine_never_holds_more_than_max_positions_and_honours_exits(self):
        result = run_engine(self.data.stock_frames, self.strategy, self.strategy,
                            EngineConfig(starting_capital=32_000, max_positions=3, sizing_mode="equal_weight",
                                         fill_mode="next_open", stop_mode="widest", skip_unprotectable=True))
        self.assertGreater(len(result.trades), 5)
        calendar = result.equity.index
        open_count = pd.Series(0, index=calendar)
        for trade in result.trades:
            open_count[(calendar >= trade.entry_date) & (calendar < trade.exit_date)] += 1
        self.assertLessEqual(int(open_count.max()), 3)
        self.assertTrue(all(t.ticker != "T05" for t in result.trades))
        self.assertTrue({t.exit_reason for t in result.trades} <= {"signal", "stop", "final"})

    def test_composite_renormalizes_over_available_factors(self):
        composite = self.strategy.composite.dropna(how="all")
        values = composite.to_numpy()
        finite = values[np.isfinite(values)]
        self.assertTrue(((finite > 0) & (finite <= 1)).all())


if __name__ == "__main__":
    unittest.main()
