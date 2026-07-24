"""One-command experiment runner: train -> visualize -> validate -> save + report.

Runs a full DQN experiment with any parameters and any subset of indicators, on
1-day candles, then automatically validates the best model and writes everything
to its own run folder: models, per-episode log, day-by-day tape CSV, a config, and
a human-readable report.

Examples:
    python -m sim.agent.experiment --name bb_adx --indicators bollinger adx
    python -m sim.agent.experiment --name gru_all --arch gru --window 30 --episodes 3000
    python -m sim.agent.experiment --name prices_only --indicators prices --arch mlp

Everything lands in  models/runs/<name>/  (report.md, config.json, models, CSVs).
"""

import argparse
import json
import os
import sys
import time

from sim.agent.dataset import load_dataset, select_indicators, DATASET_PATH
from sim.agent.features import ALL_GROUPS
from sim.agent import viz


def _write_report(run_dir, cfg, results, agg, tape):
    """Assemble a markdown report from the training + validation outputs."""
    lines = []
    a = lines.append
    a(f"# Experiment: {cfg['name']}")
    a("")
    a("## Configuration")
    a(f"- indicators: **{', '.join(cfg['indicators'])}**  ({len(results['feature_names'])} features: "
      f"{', '.join(results['feature_names'])})")
    a(f"- architecture: **{cfg['arch']}**  |  window: {results['window']}  |  "
      f"d_model: {cfg['d_model']}  |  seq_layers: {cfg['seq_layers']}")
    a(f"- episodes: {cfg['episodes']}  |  batch: {cfg['batch_size']}  |  candles: **1-day**")
    a(f"- dataset: {cfg['dataset_meta'].get('scope')} {cfg['dataset_meta'].get('start')}"
      f"..{cfg['dataset_meta'].get('end')}")
    a("")
    a("## Training")
    a(f"- best validation mean return: **{viz.pct(results['best_metric'])}**")
    a(f"- validation curve: `{viz.sparkline(results['val_hist'])}`  ({len(results['val_hist'])} checkpoints)")
    a("")
    a(f"## Validation — held-out split ({agg['n']} tickers)")
    a(f"- mean return: **{viz.pct(agg['mean_return'])}**  |  median: {viz.pct(agg['median_return'])}")
    a(f"- % profitable: {agg['pct_profitable'] * 100:.0f}%")
    a(f"- buy & hold: {viz.pct(agg['mean_buyhold'])}  |  excess vs buy & hold: **{viz.pct(agg['excess_vs_buyhold'])}**")
    a(f"- return/vol (sharpe-like): {agg['sharpe_like']:.3f}")
    a("")
    a(f"## Day-by-day sample — {tape['ticker']} ({tape['start']} -> {tape['end']}, {tape['sessions']} sessions)")
    a(f"- final return: **{viz.pct(tape['final_return'])}**  (buy & hold {viz.pct(tape['buyhold'])})")
    a(f"- trades: {tape['n_trades']}  |  win rate: {tape['win_rate'] * 100:.0f}%")
    a("")
    a("```")
    a(viz.strip_ansi(tape["equity_chart"]))
    a("```")
    a("")
    a("## Files")
    a(f"- best model: `{os.path.relpath(results['best_path'])}`")
    a(f"- final model: `{os.path.relpath(results['final_path'])}`")
    if results["log_path"]:
        a(f"- training log: `{os.path.relpath(results['log_path'])}`")
    a(f"- validation tape: `{os.path.relpath(tape['csv_path'])}`")
    a(f"- config: `{os.path.relpath(os.path.join(run_dir, 'config.json'))}`")
    report_path = os.path.join(run_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return report_path


def run(name, indicators=None, arch="mlp", window=1, d_model=128, seq_layers=2,
        episodes=2000, batch_size=128, dataset_path=DATASET_PATH, ticker=None, val_every=100):
    # Lazy torch imports (only needed to actually run an experiment).
    from sim.agent.train_daily import train
    from sim.agent.checkpoint import load_agent
    from sim.agent.validate import evaluate, run_signals, write_tape_csv

    indicators = indicators or ALL_GROUPS
    run_dir = os.path.join("models", "runs", name)
    os.makedirs(run_dir, exist_ok=True)
    print(viz.color(f"\n=== Experiment '{name}' -> {run_dir} ===", viz.BOLD))
    print(f"indicators={indicators} arch={arch} window={window} episodes={episodes}\n")

    # 1) TRAIN (live visualization happens inside train)
    results = train(episodes=episodes, batch_size=batch_size, dataset_path=dataset_path,
                    val_every=val_every, arch=arch, window=window, d_model=d_model,
                    seq_layers=seq_layers, indicators=indicators, out_dir=run_dir)

    # 2) VALIDATE the best model on the same indicator subset
    print(viz.color("\nValidating best model...", viz.BOLD))
    agent, ckpt = load_agent(results["best_path"])
    win = ckpt["window"]
    data = select_indicators(load_dataset(dataset_path), indicators)
    agg = evaluate(agent, data["val"], window=win)

    # 3) Day-by-day tape for one ticker (+ CSV export)
    val = [r for r in data["val"] if len(r[2]) > win + 1]
    pick = next((r for r in val if r[0] == ticker), None) if ticker else val[0]
    sym, feats, closes, dates = pick
    days, trades = run_signals(agent, feats, closes, dates, win)
    csv_path = write_tape_csv(os.path.join(run_dir, f"tape_{sym}.csv"), sym, days)
    wins = sum(1 for *_, r in trades if r > 0)
    tape = {
        "ticker": sym, "start": days[0]["date"], "end": days[-1]["date"], "sessions": len(days),
        "final_return": days[-1]["equity"] / 100000.0 - 1.0,
        "buyhold": days[-1]["price"] / days[0]["price"] - 1.0,
        "n_trades": len(trades), "win_rate": (wins / len(trades)) if trades else 0.0,
        "equity_chart": viz.ascii_chart([d["equity"] for d in days], height=10, width=70, baseline=100000.0),
        "csv_path": csv_path,
    }

    # 4) Save config + report
    cfg = {
        "name": name, "indicators": list(indicators), "arch": arch, "window": results["window"],
        "d_model": d_model, "seq_layers": seq_layers, "episodes": episodes, "batch_size": batch_size,
        "feature_names": results["feature_names"], "best_metric": results["best_metric"],
        "dataset_meta": data["meta"],
    }
    with open(os.path.join(run_dir, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    report_path = _write_report(run_dir, cfg, results, agg, tape)

    print(viz.color(f"\n=== Done. Report -> {report_path} ===", viz.BOLD))
    print(f"  best model  : {results['best_path']}")
    print(f"  val mean {viz.pct_color(agg['mean_return'])} | excess vs b&h {viz.pct_color(agg['excess_vs_buyhold'])} "
          f"| {sym} sample {viz.pct_color(tape['final_return'])}")
    return run_dir


def main(argv=None):
    p = argparse.ArgumentParser(description="Run a full DQN experiment (train + validate + report).")
    p.add_argument("--name", required=True, help="Run name -> models/runs/<name>/")
    p.add_argument("--indicators", nargs="+", choices=ALL_GROUPS, default=None,
                   help=f"Indicator groups (default all: {ALL_GROUPS}).")
    p.add_argument("--arch", choices=["mlp", "gru", "transformer"], default="mlp")
    p.add_argument("--window", type=int, default=1)
    p.add_argument("--d-model", type=int, default=128)
    p.add_argument("--seq-layers", type=int, default=2)
    p.add_argument("--episodes", type=int, default=2000)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--val-every", type=int, default=100)
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--ticker", default=None, help="Ticker for the day-by-day sample (default: first val ticker).")
    args = p.parse_args(argv)
    run(name=args.name, indicators=args.indicators, arch=args.arch, window=args.window,
        d_model=args.d_model, seq_layers=args.seq_layers, episodes=args.episodes,
        batch_size=args.batch_size, dataset_path=args.dataset, ticker=args.ticker, val_every=args.val_every)
    return 0


if __name__ == "__main__":
    sys.exit(main())
