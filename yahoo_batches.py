"""Fetch per-ticker data from Yahoo in small batches, stopping cleanly when Yahoo throttles us.

Shared by magic_formula.py (weekly fundamentals + company profile) and company_news.py (daily
headlines). Yahoo throttles bulk requests with a rate-limit reply or by letting requests time
out. That is the ONE failure handled here, at the orchestration boundary: the data refreshes
on a schedule, so the daily job must not fail (or lose its other outputs) over it, and retrying
immediately only prolongs the block. Every finished batch is handed to `save_batch` first, so
an interrupted run keeps its progress and the next run resumes from where it stopped.
"""

from concurrent.futures import ThreadPoolExecutor

BATCH_SIZE = 40
MAX_WORKERS = 4


def fetch_in_batches(tickers, fetch_one, save_batch, batch_size=BATCH_SIZE):
    """Run fetch_one(ticker) for every ticker; save_batch(results) after each batch.

    Returns a status line: 'up to date' (nothing to fetch), 'refreshed', or 'interrupted ...'.
    """
    from curl_cffi.requests.exceptions import RequestException
    from yfinance.exceptions import YFRateLimitError

    status = "up to date"
    for first in range(0, len(tickers), batch_size):
        batch = tickers[first:first + batch_size]
        try:
            with ThreadPoolExecutor(MAX_WORKERS) as pool:
                results = list(pool.map(fetch_one, batch))
        except (YFRateLimitError, RequestException) as error:
            return (f"interrupted by Yahoo ({type(error).__name__}) after {first} of {len(tickers)} tickers; "
                    "the rest keep their older data")
        save_batch(results)
        status = "refreshed"
    return status
