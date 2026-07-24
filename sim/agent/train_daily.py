"""Train the (bigger, dueling/noisy) DQN on the daily indicator dataset.

Each episode replays one random training ticker's daily history through
`DailyTradingEnv`. Every `--val-every` episodes the greedy policy is scored on the
held-out split; the best model is saved immediately and a final model at the end.
A per-episode CSV log is written so you can plot the learning curve later.

You can restrict which INDICATORS the agent sees with --indicators (any subset of
prices / volume / bollinger / adx / obv); the dataset is not rebuilt.

Usage (from the repo root, in an env with torch):
    python -m sim.agent.dataset                                  # build the dataset once
    python -m sim.agent.train_daily --arch gru --window 30
    python -m sim.agent.train_daily --indicators prices bollinger adx
"""

import argparse
import csv
import os
import random
import sys
import time
from collections import deque

from sim.agent.dataset import load_dataset, select_indicators, select_features_by_name, DATASET_PATH
from sim.agent.daily_env import DailyTradingEnv, START_CASH
from sim.agent.dqn_agent import DQNAgent
from sim.agent.checkpoint import save_checkpoint, load_agent
from sim.agent.validate import evaluate
from sim.agent.features import ALL_GROUPS
from sim.agent import viz

FINAL_NAME = "dqn_daily.pth"
BEST_NAME = "dqn_daily_best.pth"
LOG_NAME = "train_log.csv"


def train(episodes=2000, batch_size=128, dataset_path=DATASET_PATH, val_every=100,
          target_update_every=10, arch="mlp", window=1, d_model=128, seq_layers=2,
          indicators=None, out_dir="models", log_csv=True, resume=None):
    data = load_dataset(dataset_path)

    if resume:
        # Warm-start from an existing checkpoint: architecture, window and feature
        # set are read FROM the checkpoint (so the weights fit), not from CLI flags.
        agent, ckpt = load_agent(resume)
        feature_names = ckpt["feature_names"]
        window, arch = ckpt["window"], ckpt["arch"]
        data = select_features_by_name(data, feature_names)
        agent.update_target_network()   # load_agent leaves target un-synced; fix for training
        agent.policy_net.train()         # load_agent left it in eval()
        print(f"Resuming from {resume} | arch={arch} window={window} "
              f"features={len(feature_names)} ({', '.join(feature_names)})")
    else:
        if indicators:
            data = select_indicators(data, indicators)
        feature_names = data["feature_names"]
        feature_dim = len(feature_names)
        if arch != "mlp" and window < 2:
            window = 30   # sequence encoders need a real look-back window
        agent = DQNAgent(state_dim=window * feature_dim + 2, action_dim=3, arch=arch,
                         feature_dim=feature_dim, window=window, d_model=d_model, seq_layers=seq_layers)

    train_set, val_set = data["train"], data["val"]
    assert train_set, "Empty training set — rebuild the dataset."
    train_set = [s for s in train_set if len(s[2]) > window + 1]
    val_set = [s for s in val_set if len(s[2]) > window + 1]
    assert train_set, "No training series long enough for the chosen window."
    state_dim = agent.state_dim

    os.makedirs(out_dir, exist_ok=True)
    final_path = os.path.join(out_dir, FINAL_NAME)
    best_path = os.path.join(out_dir, BEST_NAME)
    log_path = os.path.join(out_dir, LOG_NAME)
    log_file = writer = None
    if log_csv:
        log_file = open(log_path, "w", newline="", encoding="utf-8")
        writer = csv.writer(log_file)
        writer.writerow(["episode", "epsilon", "episode_return", "avg_loss",
                         "val_mean_return", "val_pct_profitable", "val_excess_vs_bh"])

    print(f"Training daily DQN | arch={arch} window={window} | {episodes} episodes | "
          f"{len(train_set)} train / {len(val_set)} val tickers")
    print(f"  features={len(feature_names)} | state_dim={state_dim} | noisy={agent.noisy}"
          + ("  (resumed)" if resume else "") + "\n")

    best_metric = float("-inf")
    train_hist = deque(maxlen=50)
    val_hist = []
    width = len(str(episodes))
    t0 = time.time()

    for ep in range(1, episodes + 1):
        ticker, feats, closes, _dates = random.choice(train_set)
        env = DailyTradingEnv(ticker, feats, closes, window=window)
        state, done, equity = env.reset(), False, START_CASH
        losses = []
        while not done:
            action = agent.select_action(state)
            next_state, reward, done, equity = env.step(action)
            if next_state is not None:
                agent.memory.push(state, action, reward, next_state, done)
            loss = agent.train_step(batch_size)
            if loss is not None:
                losses.append(loss)
            state = next_state
        ep_return = equity / START_CASH - 1.0
        avg_loss = sum(losses) / len(losses) if losses else None
        train_hist.append(ep_return)

        if ep % target_update_every == 0:
            agent.update_target_network()
        agent.decay_epsilon()

        # live progress bar
        speed = ep / (time.time() - t0 + 1e-9)
        viz.live(f"Ep {ep:>{width}}/{episodes} [{viz.bar(ep / episodes, 22)}] {ep / episodes * 100:3.0f}% "
                 f"| eps {agent.epsilon:.3f} | train {viz.pct_color(sum(train_hist) / len(train_hist))} "
                 f"| {speed:4.1f} ep/s")

        # periodic validation
        val_row = ["", "", ""]
        if ep % val_every == 0 or ep == episodes:
            agent.policy_net.eval()
            saved_eps, agent.epsilon = agent.epsilon, 0.0
            m = evaluate(agent, val_set, window=window)
            agent.epsilon = saved_eps
            agent.policy_net.train()
            val_hist.append(m["mean_return"])
            improved = m["mean_return"] > best_metric
            if improved:
                best_metric = m["mean_return"]
                save_checkpoint(agent, best_path, feature_names, extra={"val_mean_return": best_metric})
            viz.clear_line()
            star = viz.color(" ★ best", viz.YELLOW) if improved else ""
            print(f"Ep {ep:>{width}}/{episodes} | val {viz.pct_color(m['mean_return'])} "
                  f"| %prof {m['pct_profitable'] * 100:3.0f}% | vs b&h {viz.pct_color(m['excess_vs_buyhold'])} "
                  f"| {viz.sparkline(val_hist)}{star}")
            val_row = [round(m["mean_return"], 6), round(m["pct_profitable"], 4), round(m["excess_vs_buyhold"], 6)]

        if writer:
            writer.writerow([ep, round(agent.epsilon, 4), round(ep_return, 6),
                             (round(avg_loss, 6) if avg_loss is not None else ""), *val_row])
            log_file.flush()

    viz.clear_line()
    save_checkpoint(agent, final_path, feature_names)
    if log_file:
        log_file.close()
    print(f"Done. Best -> {best_path} | Final -> {final_path}" + (f" | Log -> {log_path}" if log_csv else ""))
    return {
        "best_path": best_path, "final_path": final_path, "log_path": log_path if log_csv else None,
        "feature_names": feature_names, "window": window, "arch": arch,
        "indicators": indicators or ALL_GROUPS, "val_hist": val_hist, "best_metric": best_metric,
        "episodes": episodes,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Train the daily indicator DQN.")
    p.add_argument("--arch", choices=["mlp", "gru", "transformer"], default="mlp",
                   help="mlp = per-day features; gru/transformer = sequence encoder over a window.")
    p.add_argument("--window", type=int, default=1, help="Look-back days (sequence archs; default 30 if unset).")
    p.add_argument("--indicators", nargs="+", choices=ALL_GROUPS, default=None,
                   help=f"Subset of indicator groups to train on (default all: {ALL_GROUPS}).")
    p.add_argument("--d-model", type=int, default=128, help="Sequence encoder hidden width.")
    p.add_argument("--seq-layers", type=int, default=2, help="GRU/Transformer layers.")
    p.add_argument("--episodes", type=int, default=2000)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--val-every", type=int, default=100)
    p.add_argument("--target-update-every", type=int, default=10)
    p.add_argument("--out-dir", default="models")
    p.add_argument("--no-log", action="store_true", help="Disable the per-episode CSV log.")
    p.add_argument("--resume", default=None,
                   help="Continue training from a saved .pth checkpoint (arch/window/indicators "
                        "are taken from the checkpoint; --arch/--window/--indicators are ignored).")
    args = p.parse_args(argv)
    train(episodes=args.episodes, batch_size=args.batch_size, dataset_path=args.dataset,
          val_every=args.val_every, target_update_every=args.target_update_every,
          arch=args.arch, window=args.window, d_model=args.d_model, seq_layers=args.seq_layers,
          indicators=args.indicators, out_dir=args.out_dir, log_csv=not args.no_log, resume=args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
