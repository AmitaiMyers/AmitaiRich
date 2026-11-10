"""signal_log: new / dropped names between logged days, list-exit CSV, paper trade ledger."""

import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

import signal_log
from engine import EngineResult, Trade


def _rows(*tickers):
    return [{"rank": k + 1, "ticker": t, "close": 10.0, "score": 1.0} for k, t in enumerate(tickers)]


def _account(trades, open_positions):
    empty = pd.Series(dtype=float)
    result = EngineResult(equity=empty, cash=empty, holdings=empty, trades=trades, n_entry_signals=0,
                          open_positions=open_positions, pending_orders=[{"ticker": "CCC", "side": "SELL"}])
    return {"result": result, "trades": trades}


REASONS = {"v0": lambda t: f"v0 reason {t}", "v7": lambda t: f"v7 reason {t}"}


class SignalLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        log_dir = os.path.join(self.tmp.name, "signal_log")
        patches = {"LOG_DIR": log_dir, "HISTORY": os.path.join(log_dir, "history.csv"),
                   "EXITS": os.path.join(log_dir, "list_exits.csv"), "TRADES": os.path.join(log_dir, "paper_trades.csv")}
        for name, value in patches.items():
            patcher = mock.patch.object(signal_log, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _record(self, date, v0, v7, accounts=None):
        return signal_log.record(pd.Timestamp(date), _rows(*v0), _rows(*v7), [], accounts or {}, "ok", REASONS)

    def test_first_day_has_no_exits_and_later_days_report_them_with_reasons(self):
        first = self._record("2026-11-10", ["AAA", "BBB"], ["XXX"])
        self.assertEqual(first["v0"]["dropped"], [])
        second = self._record("2026-11-11", ["BBB", "CCC"], ["YYY"])
        self.assertEqual(second["v0"]["new"], ["CCC"])
        self.assertEqual(second["v0"]["dropped"], [{"ticker": "AAA", "reason": "v0 reason AAA"}])
        self.assertEqual(second["v7"]["dropped"], [{"ticker": "XXX", "reason": "v7 reason XXX"}])
        exits = pd.read_csv(signal_log.EXITS)
        self.assertEqual(list(exits["ticker"]), ["AAA", "XXX"])

    def test_rerunning_a_day_replaces_its_rows(self):
        self._record("2026-11-10", ["AAA", "BBB"], ["XXX"])
        self._record("2026-11-11", ["BBB"], ["XXX"])
        self._record("2026-11-11", ["BBB"], ["XXX"])
        self.assertEqual(len(pd.read_csv(signal_log.EXITS)), 1)
        self.assertEqual(len(pd.read_csv(signal_log.HISTORY)), 5)   # 3 rows day 1 + 2 rows day 2

    def test_paper_trade_ledger_lists_closed_then_open_trades(self):
        closed = Trade(ticker="AAA", entry_date=pd.Timestamp("2026-11-11"), entry_price=100.0, stop_price=90.0,
                       shares=10.0, exit_date=pd.Timestamp("2026-11-20"), exit_price=110.0, exit_reason="signal",
                       bars_held=7, costs=2.0)
        still_open = {"ticker": "BBB", "entry_date": pd.Timestamp("2026-11-12"), "entry_price": 50.0, "shares": 4.0,
                      "stop": 45.0, "last_close": 55.0, "bars_held": 6}
        self._record("2026-11-20", ["AAA"], ["XXX"], {"v0": _account([closed], [still_open])})
        ledger = pd.read_csv(signal_log.TRADES)
        self.assertEqual(list(ledger["status"]), ["closed", "open"])
        self.assertEqual(ledger.loc[0, "exit_reason"], "sell signal")
        self.assertAlmostEqual(ledger.loc[0, "return_pct"], 10.0)
        self.assertAlmostEqual(ledger.loc[0, "pnl"], 98.0)
        self.assertAlmostEqual(ledger.loc[1, "pnl"], 20.0)


if __name__ == "__main__":
    unittest.main()
