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
import shutil
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

# Model-capacity presets. `--size` sets them all at once; any explicit flag wins.
# Scale up when you have GPU headroom — bigger d_model/layers/heads for the sequence
# encoders, wider trunk + bigger replay buffer for all archs.
SIZE_PRESETS = {
    "small":  {"hidden": (128, 128),           "d_model": 96,  "seq_layers": 2, "nhead": 4, "ff_mult": 2, "buffer": 50_000,  "batch": 128},
    "medium": {"hidden": (256, 256, 128),      "d_model": 128, "seq_layers": 2, "nhead": 4, "ff_mult": 2, "buffer": 50_000,  "batch": 128},
    "large":  {"hidden": (512, 512, 256),      "d_model": 256, "seq_layers": 4, "nhead": 8, "ff_mult": 4, "buffer": 150_000, "batch": 256},
    "xl":     {"hidden": (1024, 1024, 512, 256), "d_model": 384, "seq_layers": 6, "nhead": 8, "ff_mult": 4, "buffer": 300_000, "batch": 512},
}


def _mirror(mirror_dir, paths):
    """Copy artifacts to a second location (e.g. Google Drive), never fatally.

    Train to LOCAL disk and mirror out: a FUSE mount that stalls or drops must not
    be able to abort a long GPU run, so failures warn and training carries on.
    """
    if not mirror_dir:
        return
    try:
        os.makedirs(mirror_dir, exist_ok=True)
        for p in paths:
            if p and os.path.exists(p):
                shutil.copy2(p, os.path.join(mirror_dir, os.path.basename(p)))
    except OSError as exc:
        viz.clear_line()
        print(viz.color(f"WARNING: mirror to {mirror_dir} failed ({exc}); "
                        f"artifacts remain in the local out-dir.", viz.YELLOW))


def train(episodes=2000, batch_size=None, dataset_path=DATASET_PATH, val_every=100,
          target_update_every=10, arch="mlp", window=1, d_model=None, seq_layers=None,
          nhead=None, ff_mult=None, hidden=None, buffer_size=None, lr=None,
          size="medium", indicators=None, out_dir="models", log_csv=True, resume=None,
          train_every=1, mirror_dir=None):
    preset = SIZE_PRESETS[size]
    # explicit args win over the preset
    d_model = d_model if d_model is not None else preset["d_model"]
    seq_layers = seq_layers if seq_layers is not None else preset["seq_layers"]
    nhead = nhead if nhead is not None else preset["nhead"]
    ff_mult = ff_mult if ff_mult is not None else preset["ff_mult"]
    hidden = tuple(hidden) if hidden else preset["hidden"]
    buffer_size = buffer_size if buffer_size is not None else preset["buffer"]
    batch_size = batch_size if batch_size is not None else preset["batch"]

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
        kwargs = {"lr": lr} if lr is not None else {}
        agent = DQNAgent(state_dim=window * feature_dim + 2, action_dim=3, arch=arch,
                         feature_dim=feature_dim, window=window, d_model=d_model,
                         seq_layers=seq_layers, nhead=nhead, ff_mult=ff_mult,
                         hidden=hidden, buffer_size=buffer_size, **kwargs)

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
    n_params = sum(p.numel() for p in agent.policy_net.parameters())
    print(f"  features={len(feature_names)} | state_dim={state_dim} | noisy={agent.noisy}"
          + ("  (resumed)" if resume else "") )
    print(f"  size={size} | params={n_params:,} | batch={batch_size} | buffer={agent.memory.buffer.maxlen:,}"
          + (f" | d_model={agent.d_model} layers={agent.seq_layers} heads={agent.nhead}" if arch != "mlp"
             else f" | hidden={agent.hidden}")
          + f" | device={agent.device}\n")

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
        step_i = 0
        while not done:
            action = agent.select_action(state)
            next_state, reward, done, equity = env.step(action)
            if next_state is not None:
                agent.memory.push(state, action, reward, next_state, done)
            # Gradient step every `train_every` env steps (DQN's standard
            # train-frequency; >1 trades a little sample-efficiency for a big
            # speedup, since the env steps serially on CPU).
            step_i += 1
            if step_i % train_every == 0:
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
                # copy the new best out to durable storage (e.g. Drive), if asked
                _mirror(mirror_dir, [best_path, log_path if log_csv else None])
            viz.clear_line()
            star = viz.color(" ★ best", viz.YELLOW) if improved else ""
            print(f"Ep {ep:>{width}}/{episodes} | val {viz.pct_color(m['mean_return'])} "
                  f"| %prof {m['pct_profitable'] * 100:3.0f}% | vs b&h {viz.pct_color(m['excess_vs_buyhold'])} "
                  f"| {viz.sparkline(val_hist)}{star}")
            val_row = [round(m["mean_return"], 6), round(m["pct_profitable"], 4), round(m["excess_vs_buyhold"], 6)]

        if writer:
            # Logging must NEVER kill a training run. A flaky filesystem (e.g. a
            # Google Drive FUSE mount dropping with Errno 107) would otherwise
            # abort hours of GPU work, so an I/O failure disables the log loudly
            # and training continues.
            try:
                writer.writerow([ep, round(agent.epsilon, 4), round(ep_return, 6),
                                 (round(avg_loss, 6) if avg_loss is not None else ""), *val_row])
                log_file.flush()
            except OSError as exc:
                viz.clear_line()
                print(viz.color(f"WARNING: episode log disabled (write failed: {exc}). "
                                f"Training continues.", viz.YELLOW))
                writer = None
                log_file = None

    viz.clear_line()
    save_checkpoint(agent, final_path, feature_names)
    if log_file:
        log_file.close()
    _mirror(mirror_dir, [best_path, final_path, log_path if log_csv else None])
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
    p.add_argument("--size", choices=list(SIZE_PRESETS), default="medium",
                   help="Model-capacity preset (sets d_model/layers/heads/hidden/buffer/batch). "
                        "Use 'large' or 'xl' on a strong GPU. Individual flags override it.")
    p.add_argument("--d-model", type=int, default=None, help="Sequence encoder hidden width.")
    p.add_argument("--seq-layers", type=int, default=None, help="GRU/Transformer layers.")
    p.add_argument("--nhead", type=int, default=None, help="Transformer attention heads (must divide d_model).")
    p.add_argument("--ff-mult", type=int, default=None, help="Transformer feed-forward width = d_model * ff_mult.")
    p.add_argument("--hidden", type=int, nargs="+", default=None, help="MLP trunk widths, e.g. --hidden 512 512 256.")
    p.add_argument("--buffer-size", type=int, default=None, help="Replay buffer capacity.")
    p.add_argument("--lr", type=float, default=None, help="Adam learning rate (default 5e-4).")
    p.add_argument("--episodes", type=int, default=2000)
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--dataset", default=DATASET_PATH)
    p.add_argument("--val-every", type=int, default=100)
    p.add_argument("--target-update-every", type=int, default=10)
    p.add_argument("--out-dir", default="models")
    p.add_argument("--mirror-dir", default=None,
                   help="Also copy the best/final model + log here after each improvement "
                        "(e.g. a Google Drive path). Train to LOCAL --out-dir and mirror out: "
                        "a Drive hiccup then warns instead of killing the run.")
    p.add_argument("--train-every", type=int, default=1,
                   help="Gradient step every N env steps (default 1). Try 4 for a ~3-4x speedup.")
    p.add_argument("--no-log", action="store_true", help="Disable the per-episode CSV log.")
    p.add_argument("--resume", default=None,
                   help="Continue training from a saved .pth checkpoint (arch/window/indicators "
                        "are taken from the checkpoint; --arch/--window/--indicators are ignored).")
    args = p.parse_args(argv)
    train(episodes=args.episodes, batch_size=args.batch_size, dataset_path=args.dataset,
          val_every=args.val_every, target_update_every=args.target_update_every,
          arch=args.arch, window=args.window, d_model=args.d_model, seq_layers=args.seq_layers,
          nhead=args.nhead, ff_mult=args.ff_mult, hidden=args.hidden, buffer_size=args.buffer_size,
          lr=args.lr, size=args.size, indicators=args.indicators, out_dir=args.out_dir,
          log_csv=not args.no_log, resume=args.resume,
          train_every=args.train_every, mirror_dir=args.mirror_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
