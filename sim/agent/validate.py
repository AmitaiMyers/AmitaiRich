"""Validate a trained daily DQN on the held-out split.

Two views:
  • aggregate metrics over every validation ticker (return, hit-rate, vs buy&hold);
  • a day-by-day BUY/SELL "tape" for one ticker — the model stepping through unseen
    days one at a time, exactly like live trading — with an equity curve.

Usage:
    python -m sim.agent.validate                          # metrics + tape for one ticker
    python -m sim.agent.validate --ticker NVDA --daily    # print EVERY day's decision
    python -m sim.agent.validate --model models/dqn_daily.pth --verbose
"""

import argparse
import csv
import os
import sys

import numpy as np

from sim.agent.dataset import load_dataset, DATASET_PATH
from sim.agent.daily_env import DailyTradingEnv, START_CASH
from sim.agent import viz
# load_agent (torch) is imported lazily inside main() so the tape/metrics helpers
# here can be imported and tested without torch installed.


def _run_greedy(agent, env):
    state, done, equity = env.reset(), False, START_CASH
    actions = {0: 0, 1: 0, 2: 0}
    while not done:
        action = agent.select_action(state)   # agent epsilon is 0 -> pure greedy
        actions[action] += 1
        state, _, done, equity = env.step(action)
    return equity, actions


def evaluate(agent, val_set, window=1, verbose=False):
    """Aggregate metrics over the validation ticker set."""
    rets, buyhold = [], []
    for ticker, feats, closes, _dates in val_set:
        if len(closes) <= window + 1:
            continue
        env = DailyTradingEnv(ticker, feats, closes, window=window)
        equity, acts = _run_greedy(agent, env)
        r = equity / START_CASH - 1.0
        bh = float(closes[-1] / closes[window - 1] - 1.0)
        rets.append(r); buyhold.append(bh)
        if verbose:
            print(f"  {ticker:6s} agent {viz.pct_color(r)}  buy&hold {viz.pct_color(bh)}  "
                  f"H/B/S {acts[0]}/{acts[1]}/{acts[2]}")
    rets, buyhold = np.array(rets), np.array(buyhold)
    return {
        "n": int(len(rets)),
        "mean_return": float(rets.mean()) if len(rets) else 0.0,
        "median_return": float(np.median(rets)) if len(rets) else 0.0,
        "pct_profitable": float((rets > 0).mean()) if len(rets) else 0.0,
        "mean_buyhold": float(buyhold.mean()) if len(buyhold) else 0.0,
        "excess_vs_buyhold": float(rets.mean() - buyhold.mean()) if len(rets) else 0.0,
        "sharpe_like": float(rets.mean() / (rets.std() + 1e-9)) if len(rets) else 0.0,
    }


def run_signals(agent, feats, closes, dates, window):
    """Step through one ticker day by day; record each day's decision + realized trade.

    The model outputs an action every day; a BUY only fills from flat and a SELL only
    from long (the realized events), just like a real account. Returns (days, trades).
    """
    env = DailyTradingEnv("", feats, closes, window=window)
    state, done = env.reset(), False
    days, trades, entry = [], [], None
    while not done:
        t = env.t
        prev_shares = env.shares
        action = agent.select_action(state)
        state, _, done, equity = env.step(action)
        event = "BUY" if prev_shares == 0 and env.shares > 0 else \
                "SELL" if prev_shares > 0 and env.shares == 0 else None
        price = float(closes[t])
        date = dates[t] if dates is not None else f"day {t}"
        if event == "BUY":
            entry = price
        elif event == "SELL" and entry is not None:
            trades.append((date, entry, price, price / entry - 1.0))
            entry = None
        days.append({"date": date, "price": price, "action": action,
                     "event": event, "long": env.shares > 0, "equity": float(equity)})
    return days, trades


def print_tape(ticker, days, trades, window, daily=False):
    print(viz.color(f"\n═══ Day-by-day validation tape — {ticker} "
                    f"({days[0]['date']} → {days[-1]['date']}, {len(days)} sessions) ═══", viz.BOLD))
    print(viz.color("  DATE         PRICE     SIGNAL   POSITION      EQUITY", viz.DIM))
    shown = days if daily else [d for d in days if d["event"]]
    for d in shown:
        pos = viz.color("● LONG", viz.GREEN) if d["long"] else viz.color("· flat", viz.GREY)
        print(f"  {d['date']}  {d['price']:>9.2f}   {viz.action_label(d['action'])}   "
              f"{pos:<14}  {d['equity']:>12,.0f}")
    if not daily:
        print(viz.color(f"  ({len(shown)} BUY/SELL events; use --daily to print all "
                        f"{len(days)} sessions)", viz.DIM))

    # equity curve
    print(viz.color("\n  Equity curve (validation period):", viz.BOLD))
    print(viz.ascii_chart([d["equity"] for d in days], height=10, width=70, baseline=START_CASH))

    # trade summary
    final_ret = days[-1]["equity"] / START_CASH - 1.0
    wins = sum(1 for *_, r in trades if r > 0)
    bh = days[-1]["price"] / days[0]["price"] - 1.0
    print(viz.color("\n  Summary:", viz.BOLD))
    print(f"    final return : {viz.pct_color(final_ret)}   (buy & hold {viz.pct_color(bh)})")
    print(f"    trades       : {len(trades)}  |  winners {wins}"
          + (f"  ({wins / len(trades) * 100:.0f}% win rate)" if trades else ""))


def write_tape_csv(path, ticker, days):
    """Export the day-by-day decisions to CSV (date, price, action, event, position, equity)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    names = {0: "HOLD", 1: "BUY", 2: "SELL"}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "date", "price", "action", "event", "position", "equity"])
        for d in days:
            w.writerow([ticker, d["date"], f"{d['price']:.4f}", names[d["action"]],
                        d["event"] or "", "LONG" if d["long"] else "FLAT", f"{d['equity']:.2f}"])
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate a trained daily DQN model.")
    p.add_argument("--model", default="models/dqn_daily_best.pth")
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--ticker", default=None, help="Ticker for the day-by-day tape (default: first val ticker).")
    p.add_argument("--daily", action="store_true", help="Print every session, not just BUY/SELL events.")
    p.add_argument("--verbose", action="store_true", help="Per-ticker aggregate results.")
    p.add_argument("--csv", nargs="?", const="auto", default=None,
                   help="Export the day-by-day tape to CSV (optional path; default models/tape_<ticker>.csv).")
    args = p.parse_args(argv)

    from sim.agent.checkpoint import load_agent   # lazy: pulls in torch only when actually running

    data = load_dataset(args.dataset)
    agent, ckpt = load_agent(args.model)
    window = ckpt["window"]
    expected = window * len(data["feature_names"]) + 2
    assert ckpt["state_dim"] == expected, (
        f"Model expects state_dim {ckpt['state_dim']} but dataset+window give {expected}. Retrain/rebuild.")

    print(f"Model: {args.model}  (arch={ckpt['arch']}, window={window})")

    # day-by-day tape for one ticker
    val = data["val"]
    pick = next((row for row in val if row[0] == args.ticker), None) if args.ticker else val[0]
    if pick is None:
        raise SystemExit(f"Ticker {args.ticker!r} not in the validation set.")
    ticker, feats, closes, dates = pick
    days, trades = run_signals(agent, feats, closes, dates, window)
    print_tape(ticker, days, trades, window, daily=args.daily)
    if args.csv:
        csv_path = os.path.join("models", f"tape_{ticker}.csv") if args.csv == "auto" else args.csv
        write_tape_csv(csv_path, ticker, days)
        print(viz.color(f"  tape exported -> {csv_path}", viz.DIM))

    # aggregate over the whole validation split
    print(viz.color(f"\n═══ Aggregate over {len(val)} validation tickers ═══", viz.BOLD))
    m = evaluate(agent, val, window=window, verbose=args.verbose)
    print(f"  mean return {viz.pct_color(m['mean_return'])} | median {viz.pct_color(m['median_return'])} "
          f"| % profitable {m['pct_profitable'] * 100:.0f}%")
    print(f"  buy & hold {viz.pct_color(m['mean_buyhold'])} | excess {viz.pct_color(m['excess_vs_buyhold'])} "
          f"| return/vol {m['sharpe_like']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
