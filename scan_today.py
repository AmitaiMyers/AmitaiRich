"""Daily 'scan today' — the production use of the simulator.

Two questions a trader asks each day:
  1. Across the whole market, which stocks fire a BUY on the most recent bar?
     -> scan_for_buys(): the strategy's entry signal on each ticker's latest bar,
        ranked strongest first.
  2. For a stock I already hold, should I sell today?
     -> check_holding(): reconstructs the position and runs the stop + sell logic.

`daily_report` combines both into one structured result that the CLI prints and
publish.py serialises for the PWA, so the two can never disagree.

Per-ticker data failures (late listings, bad symbols) are collected and returned,
not raised — same boundary policy as batch.py. A ConfigurationError (a setup
mistake) is NOT caught.

CLI:  python scan_today.py   (the full daily routine: a single BUY list across the
S&P 500, Nasdaq-100 and watchlist, de-duplicated and ranked best-to-least, then a
HOLD/SELL check on every open position in positions.csv — BUYs first, then SELLs)
"""

import json
import os
from datetime import date

import pandas as pd

import indicators
import universe
from algorithms import build_algorithm, exit_hit, stop_price_at
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data, normalize_ticker, prefetch
from errors import ConfigurationError, EmptyDataError, InsufficientDataError

# The strategy chosen by the GROWTH research (see research_26062026.md): the
# "Growth Momentum Rider" — buy the biggest healthy growers (raw 6-month momentum
# ROC(126) >= 25% AND price above its 200-day SMA); HOLD until price closes back
# below the 200-day SMA, with a wide ATR catastrophe stop underneath. Optimized for
# maximum CAGR under a ~40% drawdown cap, holding ~20 positions.
DEFAULT_BUY = "Momentum Rider (ROC + MA exit)"
DEFAULT_CONFIG = {"mom_lookback": 126, "mom_threshold": 0.25, "atr_period": 20}
# The research sized risk off this 'widest' (most room) catastrophe stop; every SELL
# check uses the same mode to match the backtested system.
DEFAULT_STOP_MODE = "widest"
# The daily BUY list shows the top-N candidates by growth potential (raw momentum).
TOP_N = 30
# How many positions the backtested system holds at once (the research's ~20 wide).
TARGET_POSITIONS = 20

# Open positions to run the daily HOLD/SELL check against (ticker, entry_date,
# entry_price). Edit this file as you enter/exit trades.
POSITIONS_CSV = "positions.csv"
POSITION_COLUMNS = ("ticker", "entry_date", "entry_price")

# Remembers each day's full BUY ranking so the next scan can show how far each
# candidate moved up/down the list (a stock climbing the ranks = strengthening).
STATE_FILE = "scan_state.json"
STATE_DAYS = 10

# Short tags marking which source list a candidate belongs to.
SCOPE_TAGS = {"sp500": "SPX", "nasdaq100": "NDX", "watchlist": "WL"}


def production_algorithm():
    return build_algorithm(DEFAULT_BUY, DEFAULT_CONFIG)


def _window(as_of, lookback_days):
    """Return (start_str, end_str) for a recent window ending the bar after as_of.

    yfinance's `end` is exclusive, so we add a day to make sure the as_of bar is
    included once it exists.
    """
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = end - pd.Timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d"), (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def scan_for_buys(tickers, algorithm, as_of=None, lookback_days=600,
                  interval="1d", use_cache=True, frames=None):
    """Return (hits, errors) DataFrames: stocks whose latest bar is a BUY, strongest first.

    `hits` has ticker, date, close, score (the strategy's ranking strength) plus the
    algorithm's `describe` facts. `errors` lists tickers with no usable data.
    `frames` ({ticker: frame}, optional) supplies already-loaded histories — a ticker
    missing from it is reported as an error; nothing is downloaded.
    """
    if frames is not None:
        return _rank_hits(algorithm, frames, list(dict.fromkeys(normalize_ticker(t) for t in tickers)))
    start_str, end_str = _window(as_of, lookback_days)
    errors = []

    # De-duplicate (some universe CSVs list a symbol more than once) so each name
    # is scanned and reported once, and we don't waste a fetch on repeats.
    tickers = list(dict.fromkeys(normalize_ticker(t) for t in tickers))
    if use_cache:
        prefetch(tickers, start_str, end_str, interval=interval)
    loaded = {}
    for ticker in tickers:
        try:
            loaded[ticker] = fetch_data(ticker, start_str, end_str, interval=interval, use_cache=use_cache)
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})
    hits_df, missing = _rank_hits(algorithm, loaded, list(loaded))
    return hits_df, pd.concat([pd.DataFrame(errors), missing], ignore_index=True)


def _rank_hits(algorithm, frames, tickers):
    """Latest-bar BUY hits among `tickers` (histories from `frames`), strongest first."""
    needed = algorithm.warmup_bars() + 1
    hits = []
    missing = [{"ticker": t, "error": "NoData"} for t in tickers if t not in frames]
    for ticker in [t for t in tickers if t in frames]:
        df = frames[ticker]
        if len(df) < needed:
            continue
        signals = algorithm.signals(df)
        if not signals.entry[-1]:
            continue
        row = {"ticker": ticker, "date": df.index[-1].strftime("%Y-%m-%d"),
               "close": round(float(df["Close"].iloc[-1]), 2),
               "score": round(float(signals.score[-1]), 4)}
        if hasattr(algorithm, "describe"):
            row.update(algorithm.describe(df))
        hits.append(row)
    hits_df = pd.DataFrame(hits)
    if not hits_df.empty:
        hits_df = hits_df.sort_values("score", ascending=False).reset_index(drop=True)
    return hits_df, pd.DataFrame(missing, columns=["ticker", "error"])


def exit_ma_period(algorithm):
    """The moving average the strategy actually exits on (exit_ma, else trend_ma, else None)."""
    for key in ("exit_ma", "trend_ma"):
        if key in algorithm.config:
            return algorithm.config[key]
    return None


def check_holding(ticker, algorithm, entry_date, entry_price=None, as_of=None,
                  lookback_days=900, stop_mode=DEFAULT_STOP_MODE, interval="1d", use_cache=True):
    """Return today's HOLD/SELL verdict for a position you already hold.

    Reconstructs the position: the stop is what the algorithm would have set at the
    entry bar; bars_held is counted from the entry date. Sells if today's bar hits
    that stop OR the algorithm's discretionary exit fires.
    """
    ticker = normalize_ticker(ticker)
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = (pd.Timestamp(entry_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = fetch_data(ticker, start, end_str, interval=interval, use_cache=use_cache)
    return {"ticker": ticker, **holding_verdict(df, algorithm, entry_date, entry_price, stop_mode, ticker)}


def holding_verdict(df, algorithm, entry_date, entry_price, stop_mode, ticker="?"):
    """The HOLD/SELL verdict for a position on `df`'s latest bar (pure; no I/O).

    pwa/js/holdings.js is a port of this function (checked by the parity fixture).
    """
    entry_index = int(df.index.searchsorted(pd.Timestamp(entry_date)))
    if entry_index >= len(df):
        raise EmptyDataError(f"{ticker}: entry date {entry_date} is after the last bar.")
    if (entry_index + 1) < algorithm.warmup_bars():
        # A recent listing without enough history before entry to compute the
        # strategy's stop / exit indicators — surface it as a per-position data skip.
        raise InsufficientDataError(
            f"{ticker}: only {entry_index + 1} bars before entry {entry_date}; "
            f"need {algorithm.warmup_bars()} for the strategy's warmup.")

    signals = algorithm.signals(df)
    fill_price = float(entry_price) if entry_price is not None else float(df["Close"].iloc[entry_index])
    stop_price = stop_price_at(signals, entry_index, fill_price, stop_mode)
    bars_held = (len(df) - 1) - entry_index

    last_close = float(df["Close"].iloc[-1])
    stop_hit = stop_price is not None and float(df["Low"].iloc[-1]) <= stop_price
    highest_high = float(df["High"].iloc[entry_index:].max())
    sell_signal = exit_hit(signals, len(df) - 1, last_close, highest_high, bars_held,
                           fill_price, stop_price)

    if stop_hit:
        verdict, reason = "SELL", "stop hit"
    elif sell_signal:
        verdict, reason = "SELL", "exit signal"
    else:
        verdict, reason = "HOLD", "trend intact"

    # The rising trend-break exit (the strategy's MA exit) is the real sell line for
    # a winner — far above the fixed catastrophe stop and climbing with the trend.
    # `to_exit_%` is the cushion: how far the close can fall before that exit fires.
    exit_ma = exit_ma_period(algorithm)
    exit_level, to_exit = None, None
    if exit_ma is not None and len(df) >= exit_ma:
        level = float(indicators.sma(df["Close"], exit_ma).iloc[-1])
        exit_level, to_exit = round(level, 2), round((last_close / level - 1) * 100, 1)

    # Recent (1-month) momentum so a fading holding is visible before it sells.
    recent = indicators.roc(df["Close"], 21).iloc[-1]
    mom_1m = None if pd.isna(recent) else round(float(recent) * 100, 1)
    trend = "flat" if mom_1m is None else ("down" if mom_1m < -1 else ("up" if mom_1m > 1 else "flat"))

    return {
        "verdict": verdict, "reason": reason,
        "trend": trend, "mom_1m_%": mom_1m,
        "entry_price": round(fill_price, 2), "last_close": round(last_close, 2),
        "open_pnl_%": round((last_close / fill_price - 1) * 100, 1),
        "exit_level": exit_level, "to_exit_%": to_exit,
        "stop_price": round(stop_price, 2) if stop_price is not None else None,
        "bars_held": bars_held,
    }


def load_positions(path=POSITIONS_CSV):
    """Read and validate an open-positions CSV. Fail fast on setup mistakes."""
    if not os.path.exists(path):
        raise ConfigurationError(f"positions file {path!r} not found. Columns: {POSITION_COLUMNS}.")
    positions = pd.read_csv(path)
    missing = [column for column in POSITION_COLUMNS if column not in positions.columns]
    if missing:
        raise ConfigurationError(f"{path}: missing columns {missing}; got {list(positions.columns)}.")
    return positions


def _entry_price(value):
    """An empty entry_price cell means 'use the entry-bar close'."""
    if pd.isna(value) or str(value).strip() == "":
        return None
    return float(value)


def check_positions(algorithm, positions_path=POSITIONS_CSV, as_of=None,
                    stop_mode=DEFAULT_STOP_MODE, interval="1d", use_cache=True):
    """Run the HOLD/SELL check on every open position in a positions CSV.

    Returns (verdicts, errors) DataFrames with SELLs on top, then the holdings
    closest to their exit line. Per-position data failures are collected, not raised.
    """
    positions = load_positions(positions_path)
    verdicts, errors = [], []
    for row in positions.itertuples(index=False):
        ticker = normalize_ticker(str(row.ticker))
        try:
            verdicts.append(check_holding(
                ticker, algorithm, str(row.entry_date).strip(), entry_price=_entry_price(row.entry_price),
                as_of=as_of, stop_mode=stop_mode, interval=interval, use_cache=use_cache))
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__, "detail": str(exc)})

    verdicts_df = pd.DataFrame(verdicts)
    if not verdicts_df.empty:
        verdicts_df = verdicts_df.sort_values(
            ["verdict", "to_exit_%"], ascending=[False, True], na_position="last"
        ).reset_index(drop=True)
    return verdicts_df, pd.DataFrame(errors)


# ---------------------------------------------------------------------------
# The daily report (shared by the CLI and the PWA publisher)
# ---------------------------------------------------------------------------

def combined_universe():
    """All scan scopes merged into one de-duplicated list, plus a per-ticker source tag."""
    sources, order = {}, []
    for scope, tag in SCOPE_TAGS.items():
        for raw in universe.get_universe(scope):
            ticker = normalize_ticker(raw)
            if ticker not in sources:
                sources[ticker] = []
                order.append(ticker)
            if tag not in sources[ticker]:
                sources[ticker].append(tag)
    return order, {ticker: "/".join(tags) for ticker, tags in sources.items()}


def load_state(path=STATE_FILE):
    """Load the saved {date: {ticker: [rank, score]}} history (empty if none yet)."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def save_state(state, path=STATE_FILE):
    with open(path, "w") as fh:
        json.dump(state, fh, indent=0)


def _previous_snapshot(state, today):
    """The ranking from the most recent day BEFORE today (same-day re-runs compare to yesterday)."""
    prior = [d for d in state if d < today]
    return state[max(prior)] if prior else {}


def _rank_change(ticker, new_rank, prev):
    """'NEW', '+n' (climbed n places), '-n' (fell), or '0' (same)."""
    if ticker not in prev:
        return "NEW"
    delta = prev[ticker][0] - new_rank
    return f"+{delta}" if delta > 0 else (str(delta) if delta < 0 else "0")


def _score_change(ticker, new_score, prev):
    if ticker not in prev:
        return None
    return round(new_score - prev[ticker][1], 4)


def daily_report(algorithm, state, today, held=frozenset(), as_of=None, use_cache=True,
                 frames=None, top_n=TOP_N, scan_universe=None):
    """Scan the combined universe and return (report dict, updated state).

    Rank, score and their day-over-day changes are computed on the FULL ranking
    BEFORE hiding holdings, so they reflect momentum — not which names you own.
    `scan_universe` = (tickers, {ticker: source tag}); default: combined_universe().
    """
    tickers, sources = combined_universe() if scan_universe is None else scan_universe
    hits, errors = scan_for_buys(tickers, algorithm, as_of=as_of, use_cache=use_cache, frames=frames)
    prev = _previous_snapshot(state, today)
    rows = hits.to_dict("records") if not hits.empty else []
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["src"] = sources[row["ticker"]]
        row["chg"] = _rank_change(row["ticker"], rank, prev)
        row["dscore"] = _score_change(row["ticker"], row["score"], prev)
    snapshot = {row["ticker"]: [row["rank"], row["score"]] for row in rows}
    state = {**state, today: snapshot}
    for old in sorted(state)[:-STATE_DAYS]:
        del state[old]

    current = {row["ticker"] for row in rows}
    buyable = [row for row in rows if row["ticker"] not in held]
    report = {
        "date": today,
        "strategy": {"name": algorithm.name, "config": algorithm.config,
                     "stop_mode": DEFAULT_STOP_MODE, "top_n": top_n,
                     "target_positions": TARGET_POSITIONS},
        "universe_size": len(tickers),
        "n_candidates": len(rows),
        "candidates": buyable[:top_n],
        "held_hidden": [row["ticker"] for row in rows if row["ticker"] in held],
        "new_today": [row["ticker"] for row in buyable if row["ticker"] not in prev] if prev else [],
        "dropped": sorted(set(prev) - current),
        "risers": sorted(([row["ticker"], prev[row["ticker"]][0] - row["rank"]]
                          for row in buyable[:top_n]
                          if row["ticker"] in prev and prev[row["ticker"]][0] > row["rank"]),
                         key=lambda pair: -pair[1])[:5],
        "skipped": errors["ticker"].tolist() if not errors.empty else [],
    }
    return report, state


def _fmt_list(names, cap=15):
    names = list(names)
    if len(names) <= cap:
        return ", ".join(names)
    return ", ".join(names[:cap]) + f", (+{len(names) - cap} more)"


def _print_report(report):
    print(f"\nScanned {report['universe_size']} unique stocks with {report['strategy']['name']}")
    if report["risers"]:
        print("Top risers vs last scan: " + ", ".join(f"{t} (+{d})" for t, d in report["risers"]))
    shown = pd.DataFrame(report["candidates"])
    print(f"=== BUY candidates: top {len(shown)} of {report['n_candidates']} "
          f"({len(report['held_hidden'])} held hidden) ===")
    cols = [c for c in ("rank", "chg", "dscore", "ticker", "src", "date", "close",
                        "mom_%", "vol_adj_score", "pct_vs_200ma") if c in shown.columns]
    print(shown[cols].to_string(index=False) if not shown.empty else "  (none today)")
    if report["new_today"]:
        print(f"New today (just qualified): {_fmt_list(report['new_today'])}")
    if report["dropped"]:
        print(f"Dropped off (lost momentum): {_fmt_list(report['dropped'])}")
    if report["held_hidden"]:
        print(f"(held, hidden from BUY list: {', '.join(report['held_hidden'])})")
    print(f"({len(report['skipped'])} tickers skipped for missing data)")


def print_sell_check(algorithm, positions_path=POSITIONS_CSV):
    """Run the HOLD/SELL check on a positions CSV and print verdicts (SELLs first)."""
    verdicts, errors = check_positions(algorithm, positions_path)
    n_sell = int((verdicts["verdict"] == "SELL").sum()) if not verdicts.empty else 0
    print(f"\n=== HOLD/SELL check on {len(verdicts)} positions ({n_sell} SELL) ===")
    if verdicts.empty:
        print("  (no open positions)")
    else:
        cols = [c for c in ("ticker", "verdict", "reason", "trend", "mom_1m_%", "last_close",
                            "open_pnl_%", "exit_level", "to_exit_%", "stop_price", "bars_held")
                if c in verdicts.columns]
        print(verdicts[cols].to_string(index=False))
    if len(errors):
        print(f"({len(errors)} positions skipped for missing data: {', '.join(errors['ticker'])})")


def _held_tickers(positions_path=POSITIONS_CSV):
    """Symbols already held (from positions.csv) — these are hidden from the BUY list."""
    if not os.path.exists(positions_path):
        return frozenset()
    return frozenset(normalize_ticker(str(t)) for t in load_positions(positions_path)["ticker"])


def _cli():
    """Full daily routine: ranked BUY list, then the HOLD/SELL check (BUYs first, then SELLs)."""
    algorithm = production_algorithm()
    today = date.today().strftime("%Y-%m-%d")
    print(today, flush=True)
    report, state = daily_report(algorithm, load_state(), today, held=_held_tickers())
    save_state(state)
    _print_report(report)
    if os.path.exists(POSITIONS_CSV):
        print_sell_check(algorithm)
    else:
        print(f"\n(no {POSITIONS_CSV} found — skipping HOLD/SELL check)")


if __name__ == "__main__":
    _cli()
