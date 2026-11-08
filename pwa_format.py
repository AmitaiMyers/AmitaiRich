"""The compact price-history format shared by the publisher and the PWA.

    {"ticker": "AAPL", "start": <first date as days since 1970-01-01>,
     "dd": [0, 1, 1, 3, ...],          # day-number deltas (first is 0)
     "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}

Prices keep 6 significant digits (relative precision 1e-6, ample for daily
signals) and volumes are integers, which keeps a 22-year history around 150 KB
before gzip. The JS decoder lives in pwa/js/data.js. Both engines run on the SAME
decoded numbers, which is what makes the Python<->JS parity test exact.
"""

import pandas as pd

EPOCH = pd.Timestamp("1970-01-01")
PRICE_FIELDS = (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"))


def _round6(value):
    return float(f"{value:.6g}")


def encode_bars(ticker, df):
    """OHLCV DataFrame -> compact JSON-able dict."""
    days = ((df.index.normalize() - EPOCH).days).to_numpy()
    encoded = {"ticker": ticker, "start": int(days[0]),
               "dd": [0] + [int(d) for d in (days[1:] - days[:-1])]}
    for key, column in PRICE_FIELDS:
        encoded[key] = [_round6(x) for x in df[column].to_numpy(dtype=float)]
    encoded["v"] = [int(round(x)) for x in df["Volume"].to_numpy(dtype=float)]
    return encoded


def decode_bars(encoded):
    """Compact dict -> OHLCV DataFrame (DatetimeIndex named 'Date')."""
    day = encoded["start"]
    days = []
    for delta in encoded["dd"]:
        day += delta
        days.append(day)
    index = pd.DatetimeIndex(EPOCH + pd.to_timedelta(days, unit="D"), name="Date")
    frame = {column: encoded[key] for key, column in PRICE_FIELDS}
    frame["Volume"] = [float(v) for v in encoded["v"]]
    return pd.DataFrame(frame, index=index)


def day_number(timestamp):
    """A date as days since 1970-01-01 (the PWA's date unit)."""
    return int((pd.Timestamp(timestamp).normalize() - EPOCH).days)
