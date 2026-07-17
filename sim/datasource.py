"""Modular data-ingestion pipeline for the day-trading simulator.

`DataSource` is the pluggable interface — `load_session(ticker, date) -> Session`.
Two implementations are provided:

- `YahooFinanceSource` (default): downloads REAL 1-minute OHLCV bars from Yahoo
  Finance and deterministically interpolates each bar down to 60 per-second ticks.
  The interpolation is anchored on the bar's real Open/High/Low/Close, so every
  real price the market printed at minute resolution is faithfully represented;
  only the sub-minute path between those anchors is reconstructed (Yahoo does not
  sell tick data). Volume is split across the 60 seconds so each minute's total
  matches the real reported volume.
- `SyntheticSource`: fully offline deterministic generator (no network), useful
  for demos / testing when Yahoo is unavailable.

Swap in another provider by implementing `DataSource.load_session` and returning
it from `create_data_source()`.

A `Session` is a plain dict:
    { "ticker", "name", "date" (YYYY-MM-DD), "prevClose",
      "prices": [23400 floats], "vols": [23400 ints] }
covering the 390-minute regular session 09:30:00–15:59:59 ET (one tick/second).

Fail-fast: an empty download raises `EmptyDataError`; a missing OHLCV column
raises `MissingColumnError`. Interior missing minutes (halts) are explicitly
flat-filled from the last known price with zero volume — a documented DISPLAY
gap-fill for the simulator, distinct from the strict backtest engine.
"""

import math
import random
from datetime import date as date_cls, timedelta

import pandas as pd
import yfinance as yf

from errors import EmptyDataError, MissingColumnError, ConfigurationError

# 390 regular-session minutes (09:30–15:59 ET) × 60 seconds.
SESSION_MINUTES = 390
SESSION_SECONDS = SESSION_MINUTES * 60  # 23400
_OPEN_MINUTE_OF_DAY = 9 * 60 + 30       # 09:30 as minutes-since-midnight

REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# The five stocks the simulator ships with. Names are static (matches the design)
# so we never depend on Yahoo's flaky `.info` endpoint just for a label.
TICKERS = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    "SPY": "SPDR S&P 500 ETF",
}


def _seed(ticker, date_str, salt):
    """Deterministic integer seed from ticker + date + a salt string.

    Same (ticker, date, minute) always produces the same interpolated path, so a
    saved session is perfectly reproducible.
    """
    return hash((ticker, date_str, salt)) & 0xFFFFFFFF


def _distribute_volume(total, rng):
    """Split an integer minute volume across 60 seconds, summing EXACTLY to total.

    Uses seeded random weights with occasional volume bursts (large single-second
    prints), then hands out any rounding remainder to the seconds with the largest
    fractional shares so the per-minute total is preserved exactly.
    """
    if total <= 0:
        return [0] * 60
    weights = []
    for _ in range(60):
        w = rng.random() + 0.15  # floor so no second is ever bone-dry
        if rng.random() < 0.04:
            w *= 4 + rng.random() * 8  # burst
        weights.append(w)
    wsum = sum(weights)
    shares = [total * w / wsum for w in weights]
    floors = [int(math.floor(s)) for s in shares]
    remainder = total - sum(floors)
    # give the remaining units to the largest fractional parts
    order = sorted(range(60), key=lambda i: shares[i] - floors[i], reverse=True)
    for i in range(remainder):
        floors[order[i]] += 1
    return floors


def _interpolate_minute(o, h, l, c, volume, rng):
    """Reconstruct 60 per-second prices + volumes for one real 1-minute bar.

    Guarantees the second-path starts at the real Open, ends at the real Close,
    and touches the real High and Low — so min/max/first/last of the 60 ticks
    equal the bar's actual O/H/L/C. The interior path is a piecewise walk through
    those four anchors plus seeded noise, clamped to [Low, High].
    """
    o, h, l, c = float(o), float(h), float(l), float(c)
    vols = _distribute_volume(int(volume), rng)

    if h <= l:  # perfectly flat minute
        return [round(o, 2)] * 60, vols

    # Place the High and Low at interior seconds. Bias: an up minute tends to dip
    # (low) before it peaks (high); a down minute peaks before it bottoms.
    a, b = rng.randint(1, 58), rng.randint(1, 58)
    while a == b:
        b = rng.randint(1, 58)
    if c >= o:
        t_low, t_high = min(a, b), max(a, b)
    else:
        t_high, t_low = min(a, b), max(a, b)

    anchors = sorted([(0, o), (t_low, l), (t_high, h), (59, c)])
    span = h - l
    prices = [0.0] * 60
    ai = 0
    for s in range(60):
        # advance to the segment [anchors[ai], anchors[ai+1]] that contains s
        while ai + 1 < len(anchors) and s > anchors[ai + 1][0]:
            ai += 1
        (s0, p0), (s1, p1) = anchors[ai], anchors[min(ai + 1, len(anchors) - 1)]
        base = p0 if s1 == s0 else p0 + (p1 - p0) * (s - s0) / (s1 - s0)
        noise = rng.gauss(0.0, span * 0.08)
        prices[s] = min(h, max(l, base + noise))

    # Pin the anchors exactly (after rounding) so real O/H/L/C are exact.
    for s, p in [(0, o), (t_low, l), (t_high, h), (59, c)]:
        prices[s] = p
    return [round(p, 2) for p in prices], vols


class DataSource:
    """Pluggable session provider. Implement `load_session` to add a source."""

    def load_session(self, ticker, date_str):
        raise NotImplementedError


class YahooFinanceSource(DataSource):
    """Real Yahoo Finance 1-minute bars, interpolated to per-second ticks."""

    def load_session(self, ticker, date_str):
        _require_known_ticker(ticker)
        session_date = date_cls.fromisoformat(date_str)
        intraday = self._fetch_intraday(ticker, session_date)
        prev_close = self._fetch_prev_close(ticker, session_date, intraday)
        prices, vols = self._build_ticks(ticker, date_str, intraday, prev_close)
        return {
            "ticker": ticker,
            "name": TICKERS[ticker],
            "date": date_str,
            "prevClose": round(float(prev_close), 2),
            "prices": prices,
            "vols": vols,
        }

    def _fetch_intraday(self, ticker, session_date):
        """Download the single trading day's real 1-minute bars, NY-time indexed."""
        start = session_date
        end = session_date + timedelta(days=1)
        raw = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1m",
            auto_adjust=False,   # day-traders see raw traded prices; no intraday corp-actions
            prepost=False,
            progress=False,
        )
        if raw is None or raw.empty:
            raise EmptyDataError(
                f"yfinance returned no 1-minute data for {ticker!r} on {session_date}. "
                f"Yahoo only serves 1m bars for ~the last 30 days, and only for trading "
                f"days — pick a recent weekday the market was open."
            )
        df = _flatten_columns(raw, ticker)
        _validate_columns(df, ticker)
        df = df[REQUIRED_COLUMNS].copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("America/New_York")
        # keep only bars actually on the requested calendar day (ET)
        df = df[[d.date() == session_date for d in df.index]]
        if df.empty:
            raise EmptyDataError(
                f"No 1-minute bars fell on {session_date} for {ticker!r} (market holiday?)."
            )
        return df

    def _fetch_prev_close(self, ticker, session_date, intraday):
        """Prior trading day's real daily close (the % change / dashed-line ref)."""
        start = session_date - timedelta(days=10)
        daily = yf.download(
            ticker,
            start=start.isoformat(),
            end=session_date.isoformat(),  # end is exclusive -> excludes session day
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if daily is not None and not daily.empty:
            daily = _flatten_columns(daily, ticker)
            if "Close" in daily.columns and len(daily):
                return float(daily["Close"].iloc[-1])
        # Fallback: first real intraday open (no prior daily bar available).
        return float(intraday["Open"].iloc[0])

    def _build_ticks(self, ticker, date_str, intraday, prev_close):
        """Interpolate every minute to seconds across the full 390-minute grid."""
        by_minute = {}
        for ts, row in intraday.iterrows():
            minute_idx = (ts.hour * 60 + ts.minute) - _OPEN_MINUTE_OF_DAY
            if 0 <= minute_idx < SESSION_MINUTES:
                by_minute[minute_idx] = row

        prices = [0.0] * SESSION_SECONDS
        vols = [0] * SESSION_SECONDS
        carry = float(prev_close)  # last known price, for flat gap-fills
        for m in range(SESSION_MINUTES):
            base = m * 60
            if m in by_minute:
                row = by_minute[m]
                rng = random.Random(_seed(ticker, date_str, f"m{m}"))
                sec_p, sec_v = _interpolate_minute(
                    row["Open"], row["High"], row["Low"], row["Close"], row["Volume"], rng
                )
                carry = float(row["Close"])
            else:
                # Documented DISPLAY gap-fill: a halted/missing minute holds flat at
                # the last price with zero volume (never invents trades).
                sec_p = [round(carry, 2)] * 60
                sec_v = [0] * 60
            prices[base:base + 60] = sec_p
            vols[base:base + 60] = sec_v
        return prices, vols


class SyntheticSource(DataSource):
    """Offline deterministic generator — a fallback when Yahoo is unreachable."""

    _SPECS = {
        "AAPL": (233.4, 0.014, 58e6), "MSFT": (498.8, 0.012, 22e6),
        "NVDA": (172.4, 0.024, 210e6), "TSLA": (316.9, 0.032, 95e6),
        "SPY": (627.6, 0.008, 48e6),
    }

    def load_session(self, ticker, date_str):
        _require_known_ticker(ticker)
        base, vol, adv = self._SPECS[ticker]
        rng = random.Random(_seed(ticker, date_str, "synthetic"))
        prev_close = base * (1 + (rng.random() - 0.5) * 0.06)
        min_sigma = vol / math.sqrt(SESSION_MINUTES)
        drift = (rng.random() - 0.5) * 2 * vol / SESSION_MINUTES
        minutes = [prev_close * (1 + rng.gauss(0, 1) * vol * 0.35)]
        mom = 0.0
        for _ in range(SESSION_MINUTES):
            mom = mom * 0.92 + rng.gauss(0, 1) * 0.08
            r = drift + (rng.gauss(0, 1) + mom * 2.2) * min_sigma
            minutes.append(minutes[-1] * (1 + r))
        prices, vols = [0.0] * SESSION_SECONDS, [0] * SESSION_SECONDS
        sec_sigma = min_sigma / math.sqrt(60) * 1.15
        for m in range(SESSION_MINUTES):
            p0, p1 = minutes[m], minutes[m + 1]
            minute_vol = (adv / SESSION_MINUTES) * math.exp(rng.gauss(0, 1) * 0.55)
            p = p0
            for s in range(60):
                i = m * 60 + s
                remain = 60 - s
                p = p + (p1 - p) / remain + rng.gauss(0, 1) * sec_sigma * p
                prices[i] = round(p, 2)
                burst = 4 + rng.random() * 10 if rng.random() < 0.04 else 1
                vols[i] = max(0, round((minute_vol / 60) * burst * (0.25 + rng.random() * 1.5)))
            prices[m * 60 + 59] = round(p1, 2)
        return {
            "ticker": ticker, "name": TICKERS[ticker], "date": date_str,
            "prevClose": round(prev_close, 2), "prices": prices, "vols": vols,
        }


def _require_known_ticker(ticker):
    if ticker not in TICKERS:
        raise ConfigurationError(f"Unknown ticker {ticker!r}; expected one of {list(TICKERS)}")


def _flatten_columns(df, ticker):
    """Single-ticker yfinance still returns MultiIndex columns — collapse to OHLCV."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    for level in range(df.columns.nlevels):
        if "Close" in set(df.columns.get_level_values(level)):
            flat = df.copy()
            flat.columns = df.columns.get_level_values(level)
            return flat
    raise MissingColumnError(
        f"{ticker}: could not locate OHLCV fields in columns {list(df.columns)}"
    )


def _validate_columns(df, ticker):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise MissingColumnError(f"{ticker}: missing required columns {missing}")


def create_data_source(kind="yahoo"):
    """Factory — swap the live provider here without touching the server/UI."""
    if kind == "yahoo":
        return YahooFinanceSource()
    if kind == "synthetic":
        return SyntheticSource()
    raise ConfigurationError(f"Unknown data source kind {kind!r}")
