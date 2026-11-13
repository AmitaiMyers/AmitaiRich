"""Company profile + news: parsing Yahoo articles, batch fetching that stops on throttling,
and the per-stock files the app reads."""

import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import company_news
import magic_formula
import publish
import yahoo_batches
from tests.test_magic_formula import stock


def article(title="Big news", click=None, canonical="https://example.com/a", provider="Reuters",
            summary="Something happened.", description=None, published="2026-11-12T20:00:00Z"):
    """The shape yfinance returns from Ticker.get_news()."""
    return {"id": "x", "content": {
        "title": title, "summary": summary, "description": description, "pubDate": published,
        "provider": None if provider is None else {"displayName": provider, "url": "https://p.example"},
        "clickThroughUrl": None if click is None else {"url": click},
        "canonicalUrl": None if canonical is None else {"url": canonical}}}


class ParseItemTest(unittest.TestCase):
    def test_fields(self):
        item = company_news.parse_item(article())
        self.assertEqual(item, {"title": "Big news", "url": "https://example.com/a", "publisher": "Reuters",
                                "published": "2026-11-12T20:00:00Z", "summary": "Something happened."})

    def test_click_through_link_is_preferred(self):
        self.assertEqual(company_news.parse_item(article(click="https://yahoo.example/b"))["url"],
                         "https://yahoo.example/b")

    def test_items_without_title_or_link_are_skipped(self):
        self.assertIsNone(company_news.parse_item(article(title="")))
        self.assertIsNone(company_news.parse_item(article(canonical=None)))

    def test_missing_summary_and_publisher(self):
        item = company_news.parse_item(article(summary=None, description="From description.", provider=None))
        self.assertEqual((item["summary"], item["publisher"]), ("From description.", None))
        long_item = company_news.parse_item(article(summary="x" * 1000))
        self.assertEqual(len(long_item["summary"]), company_news.SUMMARY_CHARS)


class FetchInBatchesTest(unittest.TestCase):
    def test_stops_on_throttling_and_keeps_finished_batches(self):
        from yfinance.exceptions import YFRateLimitError

        saved = []

        def fetch(ticker):
            if ticker == "T3":
                raise YFRateLimitError()
            return ticker

        status = yahoo_batches.fetch_in_batches(["T0", "T1", "T2", "T3", "T4"], fetch, saved.extend, batch_size=2)
        self.assertEqual(saved, ["T0", "T1"])                 # batch [T2, T3] failed, nothing after it ran
        self.assertIn("interrupted", status)
        self.assertIn("after 2 of 5", status)

    def test_status_when_complete_or_empty(self):
        self.assertEqual(yahoo_batches.fetch_in_batches(["A"], lambda t: t, lambda r: None), "refreshed")
        self.assertEqual(yahoo_batches.fetch_in_batches([], lambda t: t, lambda r: None), "up to date")


class NewsCacheTest(unittest.TestCase):
    def test_only_tickers_not_fetched_today_are_refetched_stalest_first(self):
        today = date.today().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news.json")
            with open(path, "w") as fh:
                json.dump({"NEW": {"fetched": today, "items": []}, "OLD": {"fetched": "2026-01-01", "items": []},
                           "MID": {"fetched": "2026-06-01", "items": []}}, fh)
            calls = []
            with mock.patch.object(company_news, "_fetch_one", lambda t: (calls.append(t), (t, [{"title": t}]))[1]), \
                    mock.patch.object(yahoo_batches, "MAX_WORKERS", 1):
                company_news.refresh(["NEW", "MID", "OLD", "NONE"], path)
            self.assertEqual(calls, ["NONE", "OLD", "MID"])
            news = company_news.news_for(["OLD", "NONE", "UNKNOWN"], path)
            self.assertEqual(sorted(news), ["NONE", "OLD"])
            self.assertEqual(news["OLD"]["fetched"], today)


class CompanyPagesTest(unittest.TestCase):
    def test_one_file_per_ticker_with_a_profile_or_news(self):
        with tempfile.TemporaryDirectory() as tmp:
            fundamentals = os.path.join(tmp, "magic.json")
            with open(fundamentals, "w") as fh:
                json.dump({"AAA": {"fetched": date.today().isoformat(), "row": stock("AAA")}}, fh)
            profiles = magic_formula.company_profiles(["AAA", "BBB", "CCC"], fundamentals)
            news = {"BBB": {"fetched": "2026-11-12", "items": [{"title": "Hi", "url": "u"}]}}
            moves = {"CCC": {"stock": {"1m": -10.0}}}
            written = publish.write_company_pages(tmp, profiles, news, moves)
            self.assertEqual(written, ["AAA", "BBB", "CCC"])
            with open(os.path.join(tmp, "company", "AAA.json")) as fh:
                aaa = json.load(fh)
            self.assertEqual(aaa["profile"]["name"], "AAA Inc.")
            self.assertEqual(aaa["profile"]["sector"], "Industrials")
            self.assertEqual((aaa["news"], aaa["news_as_of"]), ([], None))
            with open(os.path.join(tmp, "company", "BBB.json")) as fh:
                bbb = json.load(fh)
            self.assertIsNone(bbb["profile"])
            self.assertIsNone(bbb["move"])
            self.assertEqual(bbb["news_as_of"], "2026-11-12")


class OlderCacheRowsTest(unittest.TestCase):
    def test_row_without_profile_still_ranks_but_has_no_profile_and_is_refetched(self):
        old_row = {k: v for k, v in stock("OLD").items() if k not in magic_formula.PROFILE_COLUMNS}
        entry = {"fetched": date.today().isoformat(), "row": old_row}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "magic.json")
            with open(path, "w") as fh:
                json.dump({"OLD": entry}, fh)
            frame, _as_of = magic_formula.cached_fundamentals(["OLD"], path)
            self.assertEqual(list(frame["ticker"]), ["OLD"])
            self.assertEqual(magic_formula.company_profiles(["OLD"], path), {})
        self.assertFalse(magic_formula._is_fresh(entry, date.today()))


if __name__ == "__main__":
    unittest.main()
