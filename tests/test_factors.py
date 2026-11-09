"""Factor library: causality (no look-ahead) and the point-in-time rules for fundamentals."""

import unittest

import numpy as np
import pandas as pd

import earnings_pit
import factors
import fundamental_factors
import fundamentals_pit
from tests.synthetic import make_universe


def _frames():
    frames = make_universe(6, seed=12, n_bars=700)
    frames["SPY"] = frames.pop("T00")
    return frames


class FactorCausalityTest(unittest.TestCase):
    def test_every_technical_factor_is_unchanged_by_truncating_the_future(self):
        frames = _frames()
        full = factors.Panel(frames)
        cut_date = full.dates[450]
        truncated = factors.Panel({t: f[f.index <= cut_date] for t, f in frames.items()})
        for factor in list(factors.FACTORS.values()):
            if factor.group in ("earnings", "growth"):
                continue
            with self.subTest(factor.name):
                a = factor.compute(full).loc[:cut_date]
                b = factor.compute(truncated)
                pd.testing.assert_frame_equal(a, b.reindex(a.index), check_freq=False, rtol=1e-5)

    def test_relative_strength_ranks_exactly_like_six_month_momentum(self):
        panel = factors.Panel(_frames())
        rs = factors.relative_strength(panel).iloc[300:]
        mom = factors.roc(panel.close, 126).iloc[300:]
        pd.testing.assert_frame_equal(rs.rank(axis=1), mom.rank(axis=1))


class EarningsAvailabilityTest(unittest.TestCase):
    def test_after_close_reports_are_usable_the_next_business_day(self):
        ny = "America/New_York"
        self.assertEqual(earnings_pit.availability(pd.Timestamp("2024-05-22 16:20", tz=ny)), pd.Timestamp("2024-05-23"))
        self.assertEqual(earnings_pit.availability(pd.Timestamp("2024-05-22 07:00", tz=ny)), pd.Timestamp("2024-05-22"))
        self.assertEqual(earnings_pit.availability(pd.Timestamp("2024-05-24 16:00", tz=ny)), pd.Timestamp("2024-05-27"))
        self.assertEqual(earnings_pit.availability(pd.Timestamp("2024-05-22 10:00", tz=ny)), pd.Timestamp("2024-05-23"))


def _fact(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "filed": filed, "accn": "x", "fy": 0, "fp": "Q", "form": "10-Q"}


class EdgarPointInTimeTest(unittest.TestCase):
    def _raw(self, facts):
        return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": facts}}}}}

    def test_original_filing_wins_over_a_later_restatement(self):
        raw = self._raw([_fact("2020-01-01", "2020-03-31", 100.0, "2020-05-01"),
                         _fact("2020-01-01", "2020-03-31", 120.0, "2021-05-01")])
        series = fundamentals_pit.quarterly_series(raw, "revenue")
        self.assertEqual(series["value"].tolist(), [100.0])
        self.assertEqual(series["available"].tolist(), [pd.Timestamp("2020-05-01")])

    def test_q4_is_derived_from_the_annual_report_and_known_on_its_filing_date(self):
        raw = self._raw([_fact("2020-01-01", "2020-09-30", 300.0, "2020-11-01"),
                         _fact("2020-01-01", "2020-12-31", 450.0, "2021-02-20")])
        series = fundamentals_pit.quarterly_series(raw, "revenue")
        q4 = series[series["period_end"] == pd.Timestamp("2020-12-31")]
        self.assertEqual(float(q4["value"].iloc[0]), 150.0)
        self.assertTrue(bool(q4["derived"].iloc[0]))
        self.assertEqual(q4["available"].iloc[0], pd.Timestamp("2021-02-20"))


class DailyPanelTest(unittest.TestCase):
    def test_values_enter_on_the_first_bar_on_or_after_availability_and_go_stale(self):
        calendar = pd.bdate_range("2021-01-04", periods=300)
        events = pd.DataFrame({"ticker": ["A", "A"], "available": [pd.Timestamp("2021-01-09"), pd.Timestamp("2021-03-01")],
                               "value": [1.0, 2.0]})
        panel = fundamental_factors._daily(events, calendar, pd.Index(["A", "B"]), max_age_days=100)
        self.assertTrue(np.isnan(panel.loc["2021-01-08", "A"]))      # Friday: not yet public
        self.assertEqual(panel.loc["2021-01-11", "A"], 1.0)          # Saturday release -> Monday
        self.assertEqual(panel.loc["2021-03-01", "A"], 2.0)
        self.assertEqual(panel.loc["2021-06-08", "A"], 2.0)          # 99 days old: still fresh
        self.assertTrue(np.isnan(panel.loc["2021-06-10", "A"]))      # > 100 days: stale -> unknown
        self.assertTrue(panel["B"].isna().all())


if __name__ == "__main__":
    unittest.main()
