"""Recent news headlines per stock (Yahoo Finance), refreshed daily for the app's stock pages.

    python company_news.py update        # refresh every scan ticker's headlines (daily job)

Cache: market_data/news.json = {ticker: {"fetched": "YYYY-MM-DD", "items": [...]}}, where each
item is {title, publisher, url, published (ISO UTC), summary}. A ticker is refetched once its
headlines are older than today; the stalest tickers go first, so when Yahoo throttles the run
the remaining ones are simply refreshed next time (see yahoo_batches).

Yahoo items without a title or a link are skipped (nothing to show or open); the count kept is
what Yahoo returned for that ticker, up to NEWS_PER_TICKER.
"""

import json
import os
import sys
from datetime import date

import market_data
import yahoo_batches

CACHE_PATH = os.path.join(market_data.DATA_DIR, "news.json")
NEWS_PER_TICKER = 6
SUMMARY_CHARS = 280


def _url(link):
    return None if link is None else link["url"]


def parse_item(article):
    """One yfinance news article -> {title, publisher, url, published, summary}, or None if unusable."""
    content = article["content"]
    title = content["title"]
    url = _url(content["clickThroughUrl"]) or _url(content["canonicalUrl"])
    if not title or not url:
        return None
    provider = content["provider"]
    summary = content["summary"] or content["description"] or ""
    return {"title": title.strip(), "url": url,
            "publisher": None if provider is None else provider["displayName"],
            "published": content["pubDate"],
            "summary": summary.strip()[:SUMMARY_CHARS]}


def _fetch_one(ticker):
    import yfinance as yf

    articles = yf.Ticker(ticker).get_news(count=NEWS_PER_TICKER)
    items = [item for item in (parse_item(a) for a in articles) if item is not None]
    return ticker, items


def load_cache(cache_path=CACHE_PATH):
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path) as fh:
        return json.load(fh)


def refresh(tickers, cache_path=CACHE_PATH):
    """Refetch every ticker not already refreshed today (stalest first); returns the status line."""
    today = date.today().isoformat()
    cache = load_cache(cache_path)
    stale = [t for t in tickers if t not in cache or cache[t]["fetched"] < today]
    stale.sort(key=lambda t: cache[t]["fetched"] if t in cache else "")

    def save(results):
        for ticker, items in results:
            cache[ticker] = {"fetched": today, "items": items}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump(cache, fh, separators=(",", ":"), sort_keys=True)

    return yahoo_batches.fetch_in_batches(stale, _fetch_one, save)


def news_for(tickers, cache_path=CACHE_PATH):
    """{ticker: {"fetched", "items"}} for the tickers that have cached headlines."""
    cache = load_cache(cache_path)
    return {t: cache[t] for t in tickers if t in cache}


def main(argv):
    import scan_today

    if argv[:1] != ["update"]:
        print("usage: python company_news.py update")
        sys.exit(1)
    tickers, _sources = scan_today.combined_universe()
    print(f"news: {refresh(tickers)}")


if __name__ == "__main__":
    main(sys.argv[1:])
