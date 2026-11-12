"""Magic Formula: exclusions, the two ratios, the combined rank, and missing-data handling."""

import unittest

import pandas as pd

import magic_formula as MF
from errors import ConfigurationError


def stock(ticker, **overrides):
    """A rankable U.S. industrial: EBIT 100, capital 500 (ROC 20%), EV 1000 (EY 10%)."""
    row = {"ticker": ticker, "sector": "Industrials", "country": "United States", "market_cap": 900.0e6,
           "ebit": 100.0e6, "current_assets": 400.0e6, "current_liabilities": 200.0e6,
           "net_fixed_assets": 300.0e6, "total_debt": 200.0e6, "cash": 100.0e6}
    row.update(overrides)
    return row


class RatiosTest(unittest.TestCase):
    def test_roc_and_earnings_yield_follow_the_formulas(self):
        ranked, excluded = MF.magic_formula_pool([stock("AAA")])
        row = ranked.iloc[0]
        self.assertAlmostEqual(row["capital"], 500.0e6)             # (400 - 200) + 300
        self.assertAlmostEqual(row["enterprise_value"], 1000.0e6)   # 900 + 200 - 100
        self.assertAlmostEqual(row["roc"], 0.20)
        self.assertAlmostEqual(row["earnings_yield"], 0.10)
        self.assertTrue(excluded.empty)


class RankingTest(unittest.TestCase):
    def setUp(self):
        self.stocks = [
            stock("BEST", ebit=300.0e6),                       # ROC 60%, EY 30%  -> ranks 1 + 1
            stock("CHEAP", ebit=150.0e6, market_cap=400.0e6),  # ROC 30%, EY 30%  -> ranks 2 + 1 (tie on EY)
            stock("GOOD", ebit=200.0e6, market_cap=1900.0e6),  # ROC 40%, EY 10%  -> ranks ... see below
            stock("POOR", ebit=10.0e6),                        # ROC 2%,  EY 1%
            stock("LOSS", ebit=-50.0e6),                       # negative EBIT ranks last, is not dropped
        ]

    def test_score_is_the_sum_of_the_two_ranks_and_lowest_is_first(self):
        ranked, _ = MF.magic_formula_pool(self.stocks)
        self.assertEqual(list(ranked["ticker"]), ["BEST", "CHEAP", "GOOD", "POOR", "LOSS"])
        self.assertTrue((ranked["magic_score"] == ranked["roc_rank"] + ranked["ey_rank"]).all())
        self.assertEqual(ranked.set_index("ticker").loc["BEST", "magic_score"], 2)
        self.assertEqual(list(ranked["magic_score"]), sorted(ranked["magic_score"]))

    def test_top_n(self):
        self.assertEqual(list(MF.magic_formula_rank(self.stocks, top_n=2)["ticker"]), ["BEST", "CHEAP"])
        self.assertEqual(len(MF.magic_formula_rank(self.stocks)), 5)        # default 30 > pool size

    def test_accepts_a_dataframe(self):
        self.assertEqual(MF.magic_formula_rank(pd.DataFrame(self.stocks), top_n=1).iloc[0]["ticker"], "BEST")

    def test_invalid_top_n(self):
        with self.assertRaises(ConfigurationError):
            MF.magic_formula_rank(self.stocks, top_n=0)


class ExclusionTest(unittest.TestCase):
    def reason(self, **overrides):
        ranked, excluded = MF.magic_formula_pool([stock("XXX", **overrides), stock("KEEP")])
        self.assertEqual(list(ranked["ticker"]), ["KEEP"])
        return excluded.set_index("ticker").loc["XXX", "reason"]

    def test_sector_country_and_size_rules(self):
        self.assertEqual(self.reason(sector="Financial Services"), "financial sector")
        self.assertEqual(self.reason(sector="Utilities"), "utility sector")
        self.assertEqual(self.reason(country="Ireland"), "non-U.S. company")
        self.assertEqual(self.reason(market_cap=49.0e6), "market cap below $50M")
        self.assertEqual(self.reason(sector=None), "sector or country unknown")

    def test_missing_inputs_are_dropped_not_filled(self):
        for column in MF.NUMERIC_COLUMNS:
            self.assertIn(column, self.reason(**{column: None}))
        self.assertIn("ebit", self.reason(ebit=float("nan")))
        self.assertIn("cash", self.reason(cash=float("inf")))

    def test_zero_or_negative_denominators_are_dropped(self):
        self.assertIn("capital", self.reason(current_assets=0.0, current_liabilities=300.0e6))   # capital = 0
        self.assertIn("capital", self.reason(current_liabilities=900.0e6))                       # capital < 0
        self.assertIn("enterprise value", self.reason(cash=1100.0e6))                            # EV = 0

    def test_everything_excluded_gives_an_empty_ranking(self):
        ranked, excluded = MF.magic_formula_pool([stock("FIN", sector="Financials")])
        self.assertTrue(ranked.empty)
        self.assertEqual(len(excluded), 1)


class InputValidationTest(unittest.TestCase):
    def test_missing_column_fails_fast(self):
        row = stock("AAA")
        del row["cash"]
        with self.assertRaises(ConfigurationError):
            MF.magic_formula_pool([row])

    def test_duplicate_ticker_fails_fast(self):
        with self.assertRaises(ConfigurationError):
            MF.magic_formula_pool([stock("AAA"), stock("AAA")])


if __name__ == "__main__":
    unittest.main()
