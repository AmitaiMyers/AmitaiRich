"""Daily signal log — every day's v0 and v7 lists, kept in the repo for later diagnosis.

    signal_log/2026-11-10.json   full record of one trading day (both lists, paper accounts, orders)
    signal_log/history.csv       one row per (date, strategy, ticker): the easy-to-analyse version
    signal_log/list_exits.csv    one row per name that LEFT a list that day, with the reason
    signal_log/paper_trades.csv  every paper-account trade (open and closed), rebuilt each run
    signal_log/latest.json       the newest record (the PWA and the push notification read it)

"New" = on today's list but not on the previous logged day's list. Re-running the same day
replaces that day's entries (no duplicates).
"""

import json
import os

import pandas as pd

LOG_DIR = "signal_log"
HISTORY = os.path.join(LOG_DIR, "history.csv")
HISTORY_COLUMNS = ["date", "strategy", "rank", "ticker", "close", "score", "new", "detail"]
EXITS = os.path.join(LOG_DIR, "list_exits.csv")
EXIT_COLUMNS = ["date", "strategy", "ticker", "reason"]
TRADES = os.path.join(LOG_DIR, "paper_trades.csv")
TRADE_COLUMNS = ["strategy", "status", "ticker", "entry_date", "entry_price", "stop", "shares", "exit_date",
                 "exit_price", "exit_reason", "bars_held", "return_pct", "pnl"]
EXIT_REASONS = {"stop": "stop hit", "signal": "sell signal", "regime": "market regime exit",
                "final": "end of data"}


def _previous_record(date):
    if not os.path.isdir(LOG_DIR):
        return None
    days = sorted(name[:-5] for name in os.listdir(LOG_DIR)
                  if name.endswith(".json") and name[:4].isdigit() and name[:-5] < date)
    if not days:
        return None
    with open(os.path.join(LOG_DIR, f"{days[-1]}.json")) as fh:
        return json.load(fh)


def _new_names(today_rows, previous, strategy):
    previous_names = set() if previous is None else {r["ticker"] for r in previous[strategy]["list"]}
    return [r["ticker"] for r in today_rows if r["ticker"] not in previous_names]


def _dropped(today_rows, previous, strategy, reason_for):
    """Names on the previous logged day's list that are not on today's, each with a reason."""
    if previous is None:
        return []
    today_names = {r["ticker"] for r in today_rows}
    return [{"ticker": r["ticker"], "reason": reason_for(r["ticker"])}
            for r in previous[strategy]["list"] if r["ticker"] not in today_names]


def _paper_section(rows, accounts):
    return {
        "accounts": rows,
        "orders": {name: [f"{o['side']} {o['ticker']}" for o in account["result"].pending_orders]
                   for name, account in accounts.items()},
        "holdings": {name: [p["ticker"] for p in account["result"].open_positions]
                     for name, account in accounts.items()},
    }


def record(last_date, v0_rows, v7_rows, paper_rows, accounts, status, drop_reasons, magic):
    """Write today's record, refresh latest.json and the CSV logs. Returns the record.

    drop_reasons: {"v0": fn(ticker) -> str, "v7": fn(ticker) -> str} explaining why a name left a list.
    magic: magic_formula.daily_section(...) — the Magic Formula top list + every ranked ticker's position."""
    date = last_date.strftime("%Y-%m-%d")
    previous = _previous_record(date)
    entry = {
        "date": date,
        "previous_date": None if previous is None else previous["date"],
        "v0": {"name": "v0 — momentum rider (production)", "list": v0_rows,
               "new": _new_names(v0_rows, previous, "v0"),
               "dropped": _dropped(v0_rows, previous, "v0", drop_reasons["v0"])},
        "v7": {"name": "v7 — earnings-led (beat streak + SUE + revenue acceleration)", "list": v7_rows,
               "new": _new_names(v7_rows, previous, "v7"),
               "dropped": _dropped(v7_rows, previous, "v7", drop_reasons["v7"])},
        "paper": {**_paper_section(paper_rows, accounts), "status": status},
        "magic": magic,
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    for name in (f"{date}.json", "latest.json"):
        with open(os.path.join(LOG_DIR, name), "w") as fh:
            json.dump(entry, fh, indent=1, default=str)
    _append_history(entry)
    _append_exits(entry)
    _write_paper_trades(accounts)
    for strategy in ("v0", "v7"):
        print(f"signal log {date} {strategy}: {len(entry[strategy]['list'])} names, "
              f"{len(entry[strategy]['new'])} new, {len(entry[strategy]['dropped'])} left")
    return entry


def _append_history(entry):
    rows = []
    for strategy in ("v0", "v7"):
        new = set(entry[strategy]["new"])
        for r in entry[strategy]["list"]:
            detail = {k: v for k, v in r.items() if k not in ("rank", "ticker", "close", "score")}
            rows.append({"date": entry["date"], "strategy": strategy, "rank": r["rank"], "ticker": r["ticker"],
                         "close": r["close"], "score": r["score"], "new": r["ticker"] in new,
                         "detail": json.dumps(detail, separators=(",", ":"))})
    _replace_day(HISTORY, HISTORY_COLUMNS, entry["date"], rows)


def _replace_day(path, columns, date, rows):
    """Write `rows` for `date` into the CSV at `path`, replacing that date's earlier rows."""
    today = pd.DataFrame(rows, columns=columns)
    if os.path.exists(path):
        history = pd.read_csv(path)
        today = pd.concat([history[history["date"] != date], today], ignore_index=True)
    today.to_csv(path, index=False)


def _append_exits(entry):
    rows = [{"date": entry["date"], "strategy": strategy, "ticker": d["ticker"], "reason": d["reason"]}
            for strategy in ("v0", "v7") for d in entry[strategy]["dropped"]]
    _replace_day(EXITS, EXIT_COLUMNS, entry["date"], rows)


def _iso(timestamp):
    return timestamp.strftime("%Y-%m-%d")


def _write_paper_trades(accounts):
    """Every paper trade since the start: closed round trips, then the positions still open.

    Rebuilt from scratch each run (the accounts are replayed from PAPER_START), so it is always
    the complete, consistent ledger."""
    rows = []
    for name, account in accounts.items():
        for t in account["trades"]:
            rows.append({"strategy": name, "status": "closed", "ticker": t.ticker, "entry_date": _iso(t.entry_date),
                         "entry_price": round(t.entry_price, 2), "stop": None if t.stop_price is None else round(t.stop_price, 2),
                         "shares": round(t.shares, 4), "exit_date": _iso(t.exit_date), "exit_price": round(t.exit_price, 2),
                         "exit_reason": EXIT_REASONS[t.exit_reason], "bars_held": t.bars_held,
                         "return_pct": round(t.ret * 100, 2), "pnl": round(t.pnl, 2)})
        for p in account["result"].open_positions:
            rows.append({"strategy": name, "status": "open", "ticker": p["ticker"], "entry_date": _iso(p["entry_date"]),
                         "entry_price": round(p["entry_price"], 2), "stop": None if p["stop"] is None else round(p["stop"], 2),
                         "shares": round(p["shares"], 4), "exit_date": None, "exit_price": None, "exit_reason": None,
                         "bars_held": p["bars_held"], "return_pct": round((p["last_close"] / p["entry_price"] - 1) * 100, 2),
                         "pnl": round(p["shares"] * (p["last_close"] - p["entry_price"]), 2)})
    os.makedirs(LOG_DIR, exist_ok=True)
    pd.DataFrame(rows, columns=TRADE_COLUMNS).to_csv(TRADES, index=False)
