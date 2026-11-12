"""Magic Formula: exclusions, the two ratios, the combined rank, and missing-data handling."""

import unittest

import pandas as pd

import magic_formula as MF
from errors import ConfigurationError


def stock(ticker, **overrides):
    """A rankable U.S. industrial: EBIT 100, capital 400 (ROC 25%), EV 1000 (EY 10%)."""
    row = {"ticker": ticker, "sector": "Industrials", "country": "United States", "market_cap": 900.0e6,
           "ebit": 100.0e6, "current_assets": 400.0e6, "current_liabilities": 200.0e6,
           "net_fixed_assets": 300.0e6, "total_debt": 200.0e6, "cash": 100.0e6,
           "excess_cash": 150.0e6, "short_term_debt": 50.0e6}
    row.update(overrides)
    return row


class RatiosTest(unittest.TestCase):
    def test_roc_and_earnings_yield_follow_the_formulas(self):
        ranked, excluded = MF.magic_formula_pool([stock("AAA")])
        row = ranked.iloc[0]
        self.assertAlmostEqual(row["capital"], 400.0e6)             # (400 - 150) - (200 - 50) + 300
        self.assertAlmostEqual(row["enterprise_value"], 1000.0e6)   # 900 + 200 - 100
        self.assertAlmostEqual(row["roc"], 0.25)
        self.assertAlmostEqual(row["earnings_yield"], 0.10)
        self.assertTrue(excluded.empty)


class RankingTest(unittest.TestCase):
    def setUp(self):
        self.stocks = [
            stock("BEST", ebit=300.0e6),                       # ROC 75%, EY 30%   -> ranks 1 + 1
            stock("CHEAP", ebit=150.0e6, market_cap=400.0e6),  # ROC 37.5%, EY 30% -> ranks 3 + 1 (tie on EY)
            stock("GOOD", ebit=200.0e6, market_cap=1900.0e6),  # ROC 50%, EY 10%   -> ranks 2 + 3
            stock("POOR", ebit=10.0e6),                        # ROC 2.5%, EY 1%
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

    def test_zero_denominators_are_dropped(self):
        self.assertIn("capital", self.reason(current_liabilities=900.0e6, net_fixed_assets=0.0))  # capital = 0
        self.assertIn("enterprise value", self.reason(cash=1100.0e6))                             # EV = 0

    def test_negative_working_capital_counts_as_zero(self):
        ranked, excluded = MF.magic_formula_pool([stock("NEG", current_liabilities=900.0e6)])
        self.assertTrue(excluded.empty)
        self.assertAlmostEqual(ranked.iloc[0]["capital"], 300.0e6)        # only the net fixed assets
        self.assertAlmostEqual(ranked.iloc[0]["roc"], 100.0 / 300.0)

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


class FetcherHelpersTest(unittest.TestCase):
    """The statement readers behind fetch_fundamentals (no network)."""

    @staticmethod
    def statement(rows):
        columns = pd.to_datetime(["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
        return pd.DataFrame(rows, index=columns).T

    def test_operating_income_is_the_sum_of_the_last_four_quarters(self):
        quarterly = self.statement({MF.EARNINGS_ROW: [10.0, 20.0, 30.0, 40.0, 999.0]})
        self.assertEqual(MF._trailing_operating_income(quarterly, None), 100.0)

    def test_falls_back_to_the_latest_fiscal_year_when_a_quarter_is_missing(self):
        quarterly = self.statement({MF.EARNINGS_ROW: [10.0, float("nan"), 30.0, 40.0, 50.0]})
        annual = self.statement({MF.EARNINGS_ROW: [123.0, 100.0, 90.0, 80.0, 70.0]})
        self.assertEqual(MF._trailing_operating_income(quarterly, annual), 123.0)

    def test_absent_debt_line_is_zero_only_when_the_balance_sheet_exists(self):
        balance = self.statement({"Current Assets": [5.0, 4.0, 3.0, 2.0, 1.0]})
        self.assertEqual(MF._debt(balance, "Total Debt"), 0.0)
        self.assertIsNone(MF._debt(pd.DataFrame(), "Total Debt"))
        self.assertIsNone(MF._debt(None, "Total Debt"))
        with_debt = self.statement({"Total Debt": [7.0, 6.0, 5.0, 4.0, 3.0]})
        self.assertEqual(MF._debt(with_debt, "Total Debt"), 7.0)


class DailySectionTest(unittest.TestCase):
    """The block written into the daily record, built from a fresh cache (so no network is used)."""

    def test_top_list_and_rank_of_every_ranked_ticker(self):
        import json
        import os
        import tempfile
        from datetime import date

        rows = [stock("BEST", ebit=300.0e6), stock("POOR", ebit=10.0e6), stock("FIN", sector="Financial Services")]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "magic.json")
            with open(path, "w") as fh:
                json.dump({r["ticker"]: {"fetched": date.today().isoformat(), "row": r} for r in rows}, fh)
            section = MF.daily_section(["BEST", "POOR", "FIN"], top_n=1, cache_path=path)
        self.assertEqual(section["status"], "up to date")
        self.assertEqual([r["ticker"] for r in section["top"]], ["BEST"])
        self.assertEqual(section["ranks"], {"BEST": 1, "POOR": 2})
        self.assertEqual((section["n_scanned"], section["n_ranked"], section["n_excluded"]), (3, 2, 1))
        self.assertEqual(section["as_of"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
