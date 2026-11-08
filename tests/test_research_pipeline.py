"""End-to-end smoke test of the research pipeline on a synthetic on-disk data cache.

Runs the real `v3` phase (train grid -> finalists -> test -> re-drawn splits ->
walk-forward -> verdict JSON) with worker processes, on a tiny fake universe, so a
broken research path fails CI instead of failing hours into a GitHub Action run.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import data_engine
import research_grids
import research_portfolio as rp
from tests.synthetic import make_ohlcv

N_FAKE = 16


def _write_fake_cache(directory):
    tickers = [f"F{k:02d}" for k in range(N_FAKE)]
    for k, ticker in enumerate(tickers + [rp.MARKET_TICKER]):
        frame = make_ohlcv(500 + k, n_bars=1400, start="2010-01-04")
        path = os.path.join(directory, f"{ticker}_{rp.FETCH_START}_{rp.FETCH_END}_{rp.INTERVAL}.csv")
        frame.to_csv(path)
    return tickers


class ResearchPipelineTest(unittest.TestCase):
    def test_v3_phase_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir, out_dir, results_dir = (os.path.join(tmp, d) for d in ("cache", "out", "results"))
            os.makedirs(cache_dir)
            tickers = _write_fake_cache(cache_dir)
            patches = [
                mock.patch.object(data_engine, "CACHE_DIR", cache_dir),
                mock.patch.object(rp, "research_symbols", return_value=tickers),
                mock.patch.object(rp, "ensure_data", return_value=None),
                mock.patch.object(rp, "N_TRAIN", 10), mock.patch.object(rp, "N_TEST", 5),
                mock.patch.object(rp, "MIN_BARS", 1000), mock.patch.object(rp, "N_WORKERS", 2),
                mock.patch.object(rp, "OUT_DIR", out_dir),
                mock.patch.object(rp, "SPLIT_JSON", os.path.join(out_dir, "split.json")),
                mock.patch.object(rp, "RESULTS_DIR", results_dir),
                mock.patch.object(research_grids, "V3_SEEDS", (1, 2, 3)),
                mock.patch.object(research_grids, "V3_WINDOWS", (("2012-01-01", "2013-06-30"),
                                                                 ("2013-07-01", None))),
                mock.patch.object(research_grids, "v3_candidates",
                                  return_value=research_grids.v3_candidates()[:6]),
            ]
            for patch in patches:
                patch.start()
            self.addCleanup(mock.patch.stopall)

            research_grids.main(["v3"])

            with open(os.path.join(results_dir, "v3.json")) as fh:
                report = json.load(fh)
            self.assertEqual(report["phase"], "v3")
            self.assertIn("winner", report["verdict"])
            titles = [t["title"] for t in report["tables"]]
            self.assertEqual(len(titles), 2 + 1 + 2)  # train, test, robustness, 2 windows
            self.assertTrue(all(t["rows"] for t in report["tables"]))
            with open(os.path.join(results_dir, "index.json")) as fh:
                self.assertIn("v3", json.load(fh))


if __name__ == "__main__":
    unittest.main()
