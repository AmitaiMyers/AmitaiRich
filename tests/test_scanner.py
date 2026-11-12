"""Production scanner: BUY scan, HOLD/SELL agreement with the backtest, score_stock, report."""

import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

import scan_today
import score_stock
from engine import EngineConfig, run_engine
from tests.synthetic import make_ohlcv

FRAMES = {f"S{k}": make_ohlcv(40 + k, n_bars=900) for k in range(6)}


def _fake_fetch(as_of=None):
    """fetch_data stand-in returning synthetic history up to `as_of` (inclusive)."""
    def fetch(ticker, start, end, interval="1d", use_cache=True):
        df = FRAMES[ticker]
        return df if as_of is None else df[df.index <= pd.Timestamp(as_of)]
    return fetch


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.algorithm = scan_today.production_algorithm()
        for target in (mock.patch.object(scan_today, "prefetch", return_value=[]),
                       mock.patch.object(scan_today, "fetch_data", side_effect=_fake_fetch()),
                       mock.patch.object(score_stock, "fetch_data", side_effect=_fake_fetch())):
            target.start()
        self.addCleanup(mock.patch.stopall)

    def test_scan_lists_exactly_the_latest_bar_entries_ranked_by_score(self):
        hits, errors = scan_today.scan_for_buys(list(FRAMES), self.algorithm)
        self.assertTrue(errors.empty)
        expected = {t for t, df in FRAMES.items() if self.algorithm.signals(df).entry[-1]}
        self.assertEqual(set(hits["ticker"]) if not hits.empty else set(), expected)
        if len(hits) > 1:
            self.assertTrue(hits["score"].is_monotonic_decreasing)

    def test_hold_sell_verdicts_agree_with_the_backtest(self):
        checked = 0
        for ticker, df in FRAMES.items():
            config = EngineConfig(sizing_mode="all_in", stop_mode=scan_today.DEFAULT_STOP_MODE)
            trades = run_engine({ticker: df}, self.algorithm, self.algorithm, config).trades
            for trade in trades:
                if trade.exit_reason not in ("signal", "stop"):
                    continue
                exit_bar = df.index.get_loc(trade.exit_date)
                for as_of, expected in ((df.index[exit_bar - 1], "HOLD"), (trade.exit_date, "SELL")):
                    if as_of <= trade.entry_date:
                        continue
                    with mock.patch.object(scan_today, "fetch_data", side_effect=_fake_fetch(as_of)):
                        verdict = scan_today.check_holding(
                            ticker, self.algorithm, trade.entry_date.strftime("%Y-%m-%d"),
                            entry_price=trade.entry_price, as_of=as_of)
                    self.assertEqual(verdict["verdict"], expected, f"{ticker} {as_of.date()}")
                    checked += 1
        self.assertGreater(checked, 5)

    def test_score_stock_explains_every_verdict(self):
        results, errors = score_stock.score_stocks(list(FRAMES) + ["s0"], self.algorithm)
        self.assertTrue(errors.empty)
        self.assertEqual(len(results), len(FRAMES))  # 's0' normalizes to the duplicate 'S0'
        for row in results.to_dict("records"):
            self.assertTrue(row["reason"])
            self.assertEqual(row["BUY"] == "YES", row["reason"] == "entry conditions met")

    def test_daily_report_tracks_rank_changes_and_hides_holdings(self):
        universe_patch = mock.patch.object(
            scan_today, "combined_universe",
            return_value=(list(FRAMES), {t: "SPX" for t in FRAMES}))
        with universe_patch:
            hits, _ = scan_today.scan_for_buys(list(FRAMES), self.algorithm)
            if hits.empty:
                self.skipTest("no candidates on the synthetic last bar")
            first = hits["ticker"].iloc[0]
            state = {"2000-01-01": {first: [5, 0.0]}}
            report, new_state = scan_today.daily_report(self.algorithm, state, "2000-01-02",
                                                        held=frozenset({first}))
        self.assertIn(first, report["held_hidden"])
        self.assertNotIn(first, [row["ticker"] for row in report["candidates"]])
        self.assertIn("2000-01-02", new_state)
        self.assertEqual(new_state["2000-01-02"][first][0], 1)

    def test_positions_csv_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "positions.csv")
            pd.DataFrame({"ticker": ["S0"], "entry": ["2017-01-03"]}).to_csv(path, index=False)
            with self.assertRaises(scan_today.ConfigurationError):
                scan_today.load_positions(path)




class CleanBulkFrameTest(unittest.TestCase):
    """A newest bar with a blank field is dropped; a blank in the middle rejects the ticker."""

    @staticmethod
    def _frame(volumes):
        import pandas as pd
        index = pd.date_range("2026-11-02", periods=len(volumes), freq="B")
        return pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": volumes}, index=index)

    def test_incomplete_trailing_bar_is_dropped(self):
        from data_engine import clean_bulk_frame
        cleaned = clean_bulk_frame(self._frame([10.0, 11.0, 12.0, float("nan")]))
        self.assertEqual(len(cleaned), 3)
        self.assertFalse(cleaned.isna().any().any())

    def test_gap_in_the_middle_rejects_the_ticker(self):
        from data_engine import clean_bulk_frame
        self.assertIsNone(clean_bulk_frame(self._frame([10.0, float("nan"), 12.0, 13.0])))

    def test_complete_frame_is_unchanged(self):
        from data_engine import clean_bulk_frame
        self.assertEqual(len(clean_bulk_frame(self._frame([10.0, 11.0, 12.0]))), 3)


if __name__ == "__main__":
    unittest.main()
