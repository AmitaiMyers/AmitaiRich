"""Daily signal log — every day's v0 and v7 lists, kept in the repo for later diagnosis.

    signal_log/2026-11-10.json   full record of one trading day (both lists, paper accounts, orders)
    signal_log/history.csv       one row per (date, strategy, ticker): the easy-to-analyse version
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


def _paper_section(rows, accounts):
    return {
        "accounts": rows,
        "orders": {name: [f"{o['side']} {o['ticker']}" for o in account["result"].pending_orders]
                   for name, account in accounts.items()},
        "holdings": {name: [p["ticker"] for p in account["result"].open_positions]
                     for name, account in accounts.items()},
    }


def record(last_date, v0_rows, v7_rows, paper_rows, accounts, status):
    """Write today's record, refresh latest.json and the history CSV. Returns the record."""
    date = last_date.strftime("%Y-%m-%d")
    previous = _previous_record(date)
    entry = {
        "date": date,
        "previous_date": None if previous is None else previous["date"],
        "v0": {"name": "v0 — momentum rider (production)", "list": v0_rows,
               "new": _new_names(v0_rows, previous, "v0")},
        "v7": {"name": "v7 — earnings-led (beat streak + SUE + revenue acceleration)", "list": v7_rows,
               "new": _new_names(v7_rows, previous, "v7")},
        "paper": {**_paper_section(paper_rows, accounts), "status": status},
    }
    os.makedirs(LOG_DIR, exist_ok=True)
    for name in (f"{date}.json", "latest.json"):
        with open(os.path.join(LOG_DIR, name), "w") as fh:
            json.dump(entry, fh, indent=1, default=str)
    _append_history(entry)
    print(f"signal log {date}: v0 {len(v0_rows)} names ({len(entry['v0']['new'])} new), "
          f"v7 {len(v7_rows)} names ({len(entry['v7']['new'])} new)")
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
    today = pd.DataFrame(rows, columns=HISTORY_COLUMNS)
    if os.path.exists(HISTORY):
        history = pd.read_csv(HISTORY)
        history = history[history["date"] != entry["date"]]
        today = pd.concat([history, today], ignore_index=True)
    today.to_csv(HISTORY, index=False)
