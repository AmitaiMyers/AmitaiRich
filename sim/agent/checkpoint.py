"""Model checkpointing for the daily DQN.

A checkpoint stores the weights AND the architecture/feature config, so a saved
model always reloads into a matching network (no silent dimension mismatches).
"""

import os

import torch

from sim.agent.dqn_agent import DQNAgent


def save_checkpoint(agent, path, feature_names, extra=None):
    """Persist policy-net weights + config to `path` (creating the dir)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ckpt = {
        "model_state": agent.policy_net.state_dict(),
        "state_dim": agent.state_dim,
        "action_dim": agent.action_dim,
        "hidden": list(agent.hidden),
        "dropout": agent.dropout,
        "noisy": agent.noisy,
        "arch": agent.arch,
        "feature_dim": agent.feature_dim,
        "window": agent.window,
        "d_model": agent.d_model,
        "seq_layers": agent.seq_layers,
        "nhead": agent.nhead,
        "feature_names": list(feature_names),
    }
    if extra:
        ckpt.update(extra)
    torch.save(ckpt, path)
    return path


def load_agent(path):
    """Rebuild a greedy (epsilon=0) DQNAgent from a checkpoint. Returns (agent, ckpt)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Checkpoint not found at {path}. Train first (python -m sim.agent.train_daily).")
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    agent = DQNAgent(
        state_dim=ckpt["state_dim"], action_dim=ckpt["action_dim"],
        hidden=tuple(ckpt["hidden"]), dropout=ckpt["dropout"], noisy=ckpt["noisy"],
        arch=ckpt["arch"], feature_dim=ckpt["feature_dim"], window=ckpt["window"],
        d_model=ckpt["d_model"], seq_layers=ckpt["seq_layers"], nhead=ckpt["nhead"],
        epsilon_start=0.0, epsilon_min=0.0,
    )
    agent.policy_net.load_state_dict(ckpt["model_state"])
    agent.policy_net.eval()
    return agent, ckpt
