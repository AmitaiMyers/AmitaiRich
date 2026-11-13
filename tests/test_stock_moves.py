"""stock_moves: returns vs the market and peers, peer groups, earnings reactions."""

import unittest

import numpy as np
import pandas as pd

import stock_moves as SM


def series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def profile(industry, sector="Technology"):
    return {"industry": industry, "sector": sector}


class ReturnsTest(unittest.TestCase):
    def test_trailing_return_and_short_history(self):
        close = series(np.arange(1.0, 31.0))                    # 30 bars: 1 .. 30
        self.assertAlmostEqual(SM.trailing_return(close, 5), 30 / 25 - 1)
        self.assertIsNone(SM.trailing_return(close, 63))


class PeerGroupsTest(unittest.TestCase):
    def test_industry_then_sector_then_none(self):
        profiles = {"A": profile("Chips"), "B": profile("Chips"), "C": profile("Chips"),
                    "D": profile("Software"), "E": profile("Cloud"),
                    "F": profile("Oil", sector="Energy")}
        groups = SM.peer_groups(profiles)
        self.assertEqual(groups["A"], ("Chips", ["A", "B", "C"]))
        self.assertEqual(groups["D"][0], "Technology")          # only 1 Software name -> sector peers
        self.assertNotIn("F", groups)                           # alone in its industry and sector


class MovesForTest(unittest.TestCase):
    def test_stock_vs_market_vs_peers_and_earnings_reaction(self):
        n = 300
        spy = series(np.full(n, 100.0))
        flat = series(np.full(n, 50.0))
        falling = series(np.r_[np.full(n - 21, 100.0), np.linspace(99.0, 80.0, 21)])
        closes = {"MU": falling, "P1": flat, "P2": flat, "P3": flat}
        profiles = {t: profile("Chips") for t in closes}
        report_day = falling.index[n - 10]
        earnings = pd.DataFrame({"ticker": ["MU", "MU"], "available": [falling.index[n - 100], report_day],
                                 "surprise_pct": [20.0, 4.0]})
        move = SM.moves_for(closes, spy, profiles, earnings)["MU"]
        self.assertEqual(move["stock"]["1m"], -20.0)
        self.assertEqual(move["market"]["1m"], 0.0)
        self.assertEqual((move["peer_group"], move["peer_count"], move["peers"]["1m"]), ("Chips", 3, 0.0))
        self.assertEqual(move["from_high_pct"], -20.0)
        latest, older = move["earnings"]
        self.assertEqual((latest["date"], latest["surprise_pct"]), (report_day.strftime("%Y-%m-%d"), 4.0))
        expected = falling.iloc[n - 10 + SM.REACTION_BARS] / falling.iloc[n - 11] - 1.0
        self.assertAlmostEqual(latest["reaction_pct"], round(expected * 100, 1))
        self.assertEqual(older["reaction_pct"], 0.0)

    def test_reaction_is_none_until_the_window_completes(self):
        close = series(np.linspace(10.0, 20.0, 100))
        reports = pd.DataFrame({"available": [close.index[-1]], "surprise_pct": [3.0]})
        self.assertIsNone(SM.earnings_reactions(close, close, reports)[0]["reaction_pct"])


if __name__ == "__main__":
    unittest.main()
