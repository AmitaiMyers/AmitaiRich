"""Daily 'scan today' — the production use of the simulator.

Two questions a trader asks each day:
  1. Across the whole market, which stocks fire a BUY on the most recent bar?
     -> scan_for_buys(): runs the algorithm's scan_and_buy on each ticker's latest
        candle and returns the candidates (possibly none).
  2. For a stock I already hold, should I sell today?
     -> check_holding(): reconstructs the position and runs the stop + sell logic.

Only the latest bar's decision matters, but the algorithm still needs warmup
history, so we fetch a recent window up to `as_of`. Per-ticker data failures (late
listings, bad symbols) are collected and returned, not raised — same boundary
policy as batch.py. A ConfigurationError (a setup mistake) is NOT caught.

CLI:  python scan_today.py   (the full daily routine: a single BUY list across the
S&P 500, Nasdaq-100 and watchlist, de-duplicated and ranked best-to-least, then a
HOLD/SELL check on every open position in positions.csv — BUYs first, then SELLs)
"""

import json
import os
from datetime import date

import pandas as pd

from algorithms import build_algorithm
from batch import PER_TICKER_ERRORS
from data_engine import fetch_data
from errors import InsufficientDataError
from simulation import Position
import indicators
import universe

# The strategy chosen by the GROWTH research (see research_26062026.md): the
# "Growth Momentum Rider" — buy the biggest healthy growers (raw 6-month momentum
# ROC(126) >= 30% AND price above its 200-day SMA); HOLD until price closes back
# below the 200-day SMA, with a wide ATR catastrophe stop underneath. Optimized for
# maximum CAGR under a ~40% drawdown cap, it beat the previous Vol-Adjusted champion
# out-of-sample on growth (CAGR 14.7% vs 13.3%, maxDD -33.5%) by using a higher
# raw-momentum entry bar to catch the strongest movers, while riding winners ~180 days.
DEFAULT_BUY = "Momentum Rider (ROC + MA exit)"
DEFAULT_CONFIG = {"mom_lookback": 126, "mom_threshold": 0.30, "atr_period": 20}
# The research sized risk off this 'widest' (most room) catastrophe stop; the SELL
# check (check_holding) should use the same mode to match the backtested system.
DEFAULT_STOP_MODE = "widest"
# The daily BUY list shows the top-N candidates by growth potential (raw momentum).
TOP_N = 30

# Open positions to run the daily HOLD/SELL check against (ticker, entry_date,
# entry_price). Edit this file as you enter/exit trades.
POSITIONS_CSV = "positions.csv"

# Remembers each day's full BUY ranking so the next scan can show how far each
# candidate moved up/down the list (a stock climbing the ranks = strengthening).
STATE_FILE = "scan_state.json"


def _window(as_of, lookback_days):
    """Return (start_str, end_str) for a recent window ending the bar after as_of.

    yfinance's `end` is exclusive, so we add a day to make sure the as_of bar is
    included once it exists.
    """
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = end - pd.Timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d"), (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def scan_for_buys(tickers, algorithm, as_of=None, lookback_days=600,
                  interval="1d", use_cache=True):
    """Return (hits, errors) DataFrames: stocks whose latest bar is a BUY.

    `hits` has ticker, date, close, plus the algorithm's `describe` facts (the roof
    it broke and the volume surge). `errors` lists tickers with no usable data.
    """
    start_str, end_str = _window(as_of, lookback_days)
    needed = algorithm.warmup_bars() + 1
    hits, errors = [], []

    # De-duplicate (some universe CSVs list a symbol more than once) so each name
    # is scanned and reported once, and we don't waste a fetch on repeats.
    tickers = list(dict.fromkeys(t.strip().upper() for t in tickers))
    for ticker in tickers:
        try:
            df = fetch_data(ticker, start_str, end_str, interval=interval, use_cache=use_cache)
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})
            continue
        if len(df) < needed:
            continue
        if algorithm.scan_and_buy(df):
            row = {"ticker": ticker,
                   "date": df.index[-1].strftime("%Y-%m-%d"),
                   "close": round(float(df["Close"].iloc[-1]), 2)}
            if hasattr(algorithm, "describe"):
                row.update(algorithm.describe(df))
            hits.append(row)

    hits_df = pd.DataFrame(hits)
    # Rank the strongest candidate first by whichever strength fact the algorithm
    # reports: raw momentum (current growth default), the vol-adjusted score, or
    # the volume surge.
    for strength_col in ("mom_%", "vol_adj_score", "vol_x_avg"):
        if not hits_df.empty and strength_col in hits_df.columns:
            hits_df = hits_df.sort_values(strength_col, ascending=False).reset_index(drop=True)
            break
    return hits_df, pd.DataFrame(errors)


def check_holding(ticker, algorithm, entry_date, entry_price=None, as_of=None,
                  lookback_days=900, stop_mode=DEFAULT_STOP_MODE, interval="1d", use_cache=True):
    """Return today's HOLD/SELL verdict for a position you already hold.

    Reconstructs the position: the stop is what the algorithm would have set at the
    entry bar; bars_held is counted from the entry date. Sells if today's bar hits
    that stop OR the algorithm's discretionary exit fires.
    """
    end = pd.Timestamp(as_of) if as_of else pd.Timestamp(date.today())
    start = (pd.Timestamp(entry_date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = fetch_data(ticker, start, end_str, interval=interval, use_cache=use_cache)

    entry_index = int(df.index.searchsorted(pd.Timestamp(entry_date)))
    if entry_index >= len(df):
        raise PER_TICKER_ERRORS[0](f"{ticker}: entry date {entry_date} is after the last bar.")
    if (entry_index + 1) < algorithm.warmup_bars():
        # A recent listing without enough history before entry to compute the
        # strategy's stop / exit indicators — surface it as a per-position data
        # skip rather than letting an indicator NaN crash the whole check.
        raise InsufficientDataError(
            f"{ticker}: only {entry_index + 1} bars before entry {entry_date}; "
            f"need {algorithm.warmup_bars()} for the strategy's warmup.")

    entry_slice = df.iloc[: entry_index + 1]
    fill_price = float(entry_price) if entry_price else float(df["Close"].iloc[entry_index])
    stop_price = algorithm.compute_stop(fill_price, entry_slice, stop_mode)
    bars_held = (len(df) - 1) - entry_index

    position = Position(entry_date=str(pd.Timestamp(entry_date).date()), entry_price=fill_price,
                        shares=1.0, stop_price=stop_price, bars_held=bars_held)

    last_close = float(df["Close"].iloc[-1])
    last_low = float(df["Low"].iloc[-1])
    stop_hit = stop_price is not None and last_low <= stop_price
    sell_signal = algorithm.calculate_sell(position, df)

    if stop_hit:
        verdict, reason = "SELL", "stop hit"
    elif sell_signal:
        verdict, reason = "SELL", "exit signal"
    else:
        verdict, reason = "HOLD", "trend intact"

    # The rising trend-break exit (the strategy's MA exit) is the real sell line for
    # a winner — far above the fixed catastrophe stop and climbing with the trend.
    # `to_exit_%` is the cushion: how far the close can fall before that exit fires.
    # The MA the strategy actually exits on: exit_ma if it has one, else the trend MA
    # (the Momentum Rider sells on a close below its trend_ma).
    if "exit_ma" in algorithm.config:
        exit_ma = algorithm.config["exit_ma"]
    elif "trend_ma" in algorithm.config:
        exit_ma = algorithm.config["trend_ma"]
    else:
        exit_ma = None
    if exit_ma is not None and len(df) >= exit_ma:
        exit_level = float(indicators.sma(df["Close"], exit_ma).iloc[-1])
        to_exit = round((last_close / exit_level - 1) * 100, 1)
        exit_level = round(exit_level, 2)
    else:
        exit_level, to_exit = None, None

    # Recent (1-month) momentum so a fading holding is visible before it sells:
    # 'down' = losing momentum / price falling lately, 'up' = still pushing higher.
    recent = indicators.roc(df["Close"], 21).iloc[-1]
    mom_1m = round(float(recent) * 100, 1) if not pd.isna(recent) else None
    trend = "flat" if mom_1m is None else ("down" if mom_1m < -1 else ("up" if mom_1m > 1 else "flat"))

    return {
        "ticker": ticker, "verdict": verdict, "reason": reason,
        "trend": trend, "mom_1m_%": mom_1m,
        "entry_price": round(fill_price, 2), "last_close": round(last_close, 2),
        "open_pnl_%": round((last_close / fill_price - 1) * 100, 1),
        "exit_level": exit_level, "to_exit_%": to_exit,
        "stop_price": round(stop_price, 2) if stop_price is not None else None,
        "bars_held": bars_held,
    }


def check_positions(algorithm, positions_path=POSITIONS_CSV, as_of=None,
                    interval="1d", use_cache=True):
    """Run the HOLD/SELL check on every open position in a positions CSV.

    The CSV has columns `ticker, entry_date, entry_price`. Each row is reconstructed
    and run through the same stop + sell logic as check_holding. Per-position data
    failures are collected and returned, not raised (same boundary policy as the BUY
    scan). Returns (verdicts, errors) DataFrames with SELLs sorted to the top.
    """
    positions = pd.read_csv(positions_path)
    verdicts, errors = [], []
    for _, row in positions.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        try:
            verdicts.append(check_holding(
                ticker, algorithm, row["entry_date"], entry_price=row["entry_price"],
                as_of=as_of, interval=interval, use_cache=use_cache))
        except PER_TICKER_ERRORS as exc:
            errors.append({"ticker": ticker, "error": type(exc).__name__})

    verdicts_df = pd.DataFrame(verdicts)
    if not verdicts_df.empty:
        # SELLs first (action items); within each group, the smallest cushion to the
        # exit first, so the holdings closest to selling bubble to the top.
        verdicts_df = verdicts_df.sort_values(
            ["verdict", "to_exit_%"], ascending=[False, True], na_position="last"
        ).reset_index(drop=True)
    return verdicts_df, pd.DataFrame(errors)


# Short tags marking which source list a candidate belongs to (a name can be in
# more than one, e.g. an S&P 500 stock that is also in the Nasdaq-100).
SCOPE_TAGS = {"sp500": "SPX", "nasdaq100": "NDX", "watchlist": "WL"}


def _combined_universe():
    """All scopes merged into one de-duplicated list, plus a per-ticker source tag.

    Returns (tickers, sources): `tickers` is every unique symbol across the scopes
    (order preserved); `sources[ticker]` is a tag like 'SPX/NDX' showing the lists
    it appears in.
    """
    sources, order = {}, []
    for scope, tag in SCOPE_TAGS.items():
        for raw in universe.get_universe(scope):
            ticker = raw.strip().upper()
            if ticker not in sources:
                sources[ticker] = []
                order.append(ticker)
            if tag not in sources[ticker]:
                sources[ticker].append(tag)
    return order, {ticker: "/".join(tags) for ticker, tags in sources.items()}


def _held_tickers(positions_path=POSITIONS_CSV):
    """Symbols already held (from positions.csv) — these are hidden from the BUY list."""
    if not os.path.exists(positions_path):
        return set()
    return {str(t).strip().upper() for t in pd.read_csv(positions_path)["ticker"]}


def _load_state(path):
    """Load the saved {date: {ticker: [rank, score]}} history (empty if none yet)."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def _save_state(path, state, today, snapshot, keep=10):
    """Record today's full ranking (rank + score per ticker), keeping last `keep` days."""
    state[today] = snapshot
    for old in sorted(state)[:-keep]:
        del state[old]
    with open(path, "w") as fh:
        json.dump(state, fh, indent=0)


def _prev_snapshot(state, today):
    """The snapshot (ticker -> [rank, score]) from the most recent day BEFORE today,
    so same-day re-runs still compare against yesterday rather than against this run."""
    prior = [d for d in state if d < today]
    return state[max(prior)] if prior else {}


def _rank_change(ticker, new_rank, prev):
    """ASCII rank-move tag: 'NEW', '+n' (climbed n places), '-n' (fell), '0' (same)."""
    if ticker not in prev:
        return "NEW"
    delta = prev[ticker][0] - new_rank          # positive => moved UP the list
    return f"+{delta}" if delta > 0 else (str(delta) if delta < 0 else "0")


def _score_change(ticker, new_score, prev):
    """Signed change in the vol-adjusted score vs the previous scan ('NEW' if absent)."""
    if ticker not in prev:
        return "NEW"
    return f"{new_score - prev[ticker][1]:+.1f}"


def _fmt_list(names, cap=15):
    """Comma-join names, truncating to `cap` with a '(+N more)' tail."""
    names = list(names)
    if len(names) <= cap:
        return ", ".join(names)
    return ", ".join(names[:cap]) + f", (+{len(names) - cap} more)"


def _scan_all(algorithm):
    """Scan every scope as ONE universe; print a single best-to-least ranked BUY list
    with day-over-day rank- and score-change, a 'top risers' line, a new/dropped
    summary, and holdings hidden.

    Rank, score and their changes are computed on the FULL candidate ranking BEFORE
    hiding holdings, so they reflect momentum — not which names you own.
    """
    tickers, sources = _combined_universe()
    print(f"\nScanning {len(tickers)} unique stocks with {DEFAULT_BUY}...", flush=True)
    hits, errors = scan_for_buys(tickers, algorithm)
    if hits.empty:
        print("=== BUY candidates, ranked best to least (0) ===")
        print("  (none today)")
        print(f"({len(errors)} tickers skipped for missing data)")
        return

    hits = hits.copy()
    hits.insert(0, "rank", range(1, len(hits) + 1))
    hits["src"] = hits["ticker"].map(sources)

    today = date.today().strftime("%Y-%m-%d")
    state = _load_state(STATE_FILE)
    prev = _prev_snapshot(state, today)
    hits["chg"] = [_rank_change(t, r, prev) for t, r in zip(hits["ticker"], hits["rank"])]
    # The ranking/score column the strategy's describe() produced — raw momentum for
    # the growth default, the vol-adjusted score for the previous champion.
    score_col = next((c for c in ("mom_%", "vol_adj_score", "vol_x_avg") if c in hits.columns), None)
    if score_col is not None:
        hits["dscore"] = [_score_change(t, s, prev) for t, s in zip(hits["ticker"], hits[score_col])]
        snapshot = {t: [int(r), float(s)] for t, r, s in
                    zip(hits["ticker"], hits["rank"], hits[score_col])}
    else:
        hits["dscore"] = "NEW"
        snapshot = {t: [int(r), 0.0] for t, r in zip(hits["ticker"], hits["rank"])}
    _save_state(STATE_FILE, state, today, snapshot)

    held = _held_tickers()
    hidden = [t for t in hits["ticker"] if t in held]
    buyable = hits[~hits["ticker"].isin(held)]
    shown = buyable.head(TOP_N)   # the daily top-N by growth potential

    # Top risers: biggest rank climbs among the shown top-N (needs a prior scan).
    if prev:
        climbs = [(t, prev[t][0] - r) for t, r in zip(shown["ticker"], shown["rank"])
                  if t in prev and prev[t][0] - r > 0]
        climbs.sort(key=lambda x: -x[1])
        if climbs:
            print("Top risers vs last scan: "
                  + ", ".join(f"{t} (+{d})" for t, d in climbs[:5]))

    print(f"=== BUY candidates: top {len(shown)} of {len(buyable)} buyable "
          f"({len(hidden)} held hidden) ===")
    cols = [c for c in ("rank", "chg", "dscore", "ticker", "src", "date", "close",
                        "mom_%", "vol_adj_score", "pct_vs_200ma") if c in shown.columns]
    print(shown[cols].to_string(index=False) if not shown.empty else "  (all candidates already held)")

    # New entrants / dropped-off vs the previous scan.
    if prev:
        new_names = [t for t in hits["ticker"] if t not in prev and t not in held]
        dropped = sorted(set(prev) - set(hits["ticker"]))
        if new_names:
            print(f"New today (just qualified): {_fmt_list(new_names)}")
        if dropped:
            print(f"Dropped off (lost momentum): {_fmt_list(dropped)}")
    if hidden:
        print(f"(held, hidden from BUY list: {', '.join(hidden)})")
    print(f"({len(errors)} tickers skipped for missing data)")


def _sell_check(algorithm):
    """Run the HOLD/SELL check on positions.csv and print verdicts (SELLs first)."""
    if not os.path.exists(POSITIONS_CSV):
        print(f"\n(no {POSITIONS_CSV} found — skipping HOLD/SELL check)")
        return
    verdicts, errors = check_positions(algorithm)
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


def _cli():
    """Full daily routine: a single best-to-least ranked BUY list across the S&P 500,
    Nasdaq-100 and watchlist, then the HOLD/SELL check on positions.csv — BUYs first,
    then SELLs, in that order."""
    algorithm = build_algorithm(DEFAULT_BUY, DEFAULT_CONFIG)
    print(date.today().strftime("%Y-%m-%d"), flush=True)
    _scan_all(algorithm)
    _sell_check(algorithm)


if __name__ == "__main__":
    _cli()
