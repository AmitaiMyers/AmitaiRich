"""Real crypto market-data recorder (Binance public REST, no auth, no signup).

Unlike equities, crypto exchanges publish their FULL order book for free. This
module records — second by second, live — everything the simulator needs as REAL
data, so nothing has to be synthesized:

  1/2. per-second last trade price + traded volume  (from /api/v3/trades)
  3.   previous close / % change reference          (from /api/v3/ticker/24hr)
  4.   real best bid / best ask                      (top of /api/v3/depth)
  5.   real Level-2 order-book ladder                (/api/v3/depth, N levels)
  6.   real resting liquidity for the chart "walls"  (the same depth ladder)

Because real Level-2 depth only exists live (no free historical L2), recording
is REAL-TIME: capturing `seconds` seconds takes `seconds` seconds of wall-clock.
The result is saved as a JSON session and replayed through the existing UI, so
the whole app (candles, book, tape, blotter, brackets, playback) is unchanged —
only the data underneath is now 100% real.

Endpoints used (all public, unauthenticated):
  GET /api/v3/depth?symbol=&limit=      -> {bids:[[price,qty]..], asks:[..]}
  GET /api/v3/trades?symbol=&limit=1000 -> [{id, price, qty, time, ...}]
  GET /api/v3/ticker/24hr?symbol=       -> {prevClosePrice, lastPrice, ...}
"""

import time
from datetime import datetime, timezone

import requests

from errors import EmptyDataError, ConfigurationError

# Market-data hosts (first that answers wins). `data-api.binance.vision` is
# Binance's auth-free market-data mirror — a good fallback if the main API is
# geo-blocked or rate-limited.
BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]

# Liquid pairs shipped by default. Names are static (like the equity build).
CRYPTO_SYMBOLS = {
    "BTCUSDT": "Bitcoin / USDT",
    "ETHUSDT": "Ethereum / USDT",
    "SOLUSDT": "Solana / USDT",
    "BNBUSDT": "BNB / USDT",
    "XRPUSDT": "XRP / USDT",
}

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "roof-sim/1.0 (market-data recorder)"})


def _get(path, params, retries=4):
    """GET a Binance public endpoint with host fallback + 429 back-off.

    Binance rate-limits by request WEIGHT/min. On 429/418 we honor Retry-After
    and retry rather than aborting, so a long recording survives transient limits.
    """
    last_err = None
    for attempt in range(retries):
        for host in BINANCE_HOSTS:
            try:
                resp = _SESSION.get(host + path, params=params, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 418):
                    wait = int(resp.headers.get("Retry-After", "3"))
                    last_err = f"{host}{path} -> HTTP {resp.status_code} (rate limit)"
                    time.sleep(min(max(wait, 2), 15))
                    continue
                last_err = f"{host}{path} -> HTTP {resp.status_code}: {resp.text[:150]}"
            except requests.RequestException as exc:
                last_err = f"{host}{path} -> {exc}"
        time.sleep(1)
    raise EmptyDataError(f"Binance request failed after {retries} attempts. Last: {last_err}")


def _round_price(p):
    """Round to a precision that suits the price magnitude (keeps JSON compact)."""
    p = float(p)
    if p >= 100:
        return round(p, 2)
    if p >= 1:
        return round(p, 4)
    return round(p, 6)


def _ladder(levels, depth):
    """[[price, qty], ...] as strings -> [[float price, float qty], ...], top `depth`."""
    return [[_round_price(px), round(float(qty), 4)] for px, qty in levels[:depth]]


def record_session(symbol, seconds, depth=100, on_tick=None):
    """Record one symbol live for `seconds` and return a crypto-l2-v1 session dict.

    One snapshot per second: real last price, real volume traded in that second,
    real best bid/ask, and the real top-`depth` order book. `on_tick(i, seconds)`
    is called after each second for progress reporting.
    """
    if symbol not in CRYPTO_SYMBOLS:
        raise ConfigurationError(f"Unknown symbol {symbol!r}; expected one of {list(CRYPTO_SYMBOLS)}")
    if seconds < 1:
        raise ConfigurationError("seconds must be >= 1")

    ticker = _get("/api/v3/ticker/24hr", {"symbol": symbol})
    prev_close = _round_price(ticker["prevClosePrice"])

    prices, vols, bids_top, asks_top, book = [], [], [], [], []
    last_trade_id = None
    last_price = _round_price(ticker["lastPrice"])
    start = datetime.now(timezone.utc)

    for i in range(seconds):
        tick_start = time.time()
        depth_data = _get("/api/v3/depth", {"symbol": symbol, "limit": depth})
        # aggTrades is weight 2 vs 25 for /trades — critical for polling many symbols
        # without exhausting Binance's request-weight budget. Fields: a=id, p, q, T.
        trades = _get("/api/v3/aggTrades", {"symbol": symbol, "limit": 1000})

        # real volume + last price from the trades that are new since last poll
        vol = 0.0
        max_id = last_trade_id
        for tr in trades:
            tid = tr["a"]
            if last_trade_id is None or tid > last_trade_id:
                vol += float(tr["q"])
                if max_id is None or tid > max_id:
                    max_id = tid
                    last_price = _round_price(tr["p"])
        # On the very first poll we have no baseline, so don't count the whole
        # 1000-trade backlog as "one second" — start volume accounting from now.
        if last_trade_id is None:
            vol = 0.0
        last_trade_id = max_id if max_id is not None else last_trade_id

        best_bid = _round_price(depth_data["bids"][0][0]) if depth_data["bids"] else last_price
        best_ask = _round_price(depth_data["asks"][0][0]) if depth_data["asks"] else last_price

        prices.append(last_price)
        vols.append(round(vol, 4))
        bids_top.append(best_bid)
        asks_top.append(best_ask)
        book.append({"b": _ladder(depth_data["bids"], depth), "a": _ladder(depth_data["asks"], depth)})

        if on_tick:
            on_tick(i + 1, seconds)
        # pace to ~1 snapshot/second (account for request latency)
        elapsed = time.time() - tick_start
        if i < seconds - 1 and elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    return {
        "schema": "crypto-l2-v1",
        "symbol": symbol,
        "name": CRYPTO_SYMBOLS[symbol],
        "exchange": "Binance",
        "start": start.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "interval": 1,
        "length": seconds,
        "depth": depth,
        "prevClose": prev_close,
        "prices": prices,
        "vols": vols,
        "bid": bids_top,
        "ask": asks_top,
        "book": book,
    }
