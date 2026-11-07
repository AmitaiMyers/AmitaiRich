"""Training-job manager for the Agent Lab GUI (torch-free).

The GUI server uses this to launch experiments as SUBPROCESSES and to read their
artifacts for live progress + the report. Training itself needs torch, but this
module only spawns processes and reads files, so it runs fine in the server's
process (which the user starts from the `ntp` env, so the child inherits torch).

Progress is read from the run's `train_log.csv` (one row per finished episode,
written incrementally) — robust and independent of terminal output. The child's
console (stdout+stderr) is captured to `console.log` for errors.
"""

import json
import os
import re
import subprocess
import sys

from sim.agent.features import ALL_GROUPS

RUNS_DIR = os.path.join("models", "runs")
DATASET_LOG = os.path.join("models", "dataset_build.log")
# Python used for child processes. Defaults to the server's interpreter (run the
# server from the `ntp` env so this has torch); override with SIM_AGENT_PYTHON.
PYTHON = os.environ.get("SIM_AGENT_PYTHON", sys.executable)

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REGISTRY = {}   # name -> Popen (this session's launched jobs)
_DATASET_PROC = [None]


def _valid_name(name):
    if not _NAME_RE.match(name or ""):
        raise ValueError("Run name must be 1-64 chars of letters, digits, '_' or '-'.")
    return name


def run_dir(name):
    return os.path.join(RUNS_DIR, name)


# ── launching ─────────────────────────────────────────────────────────────────

def launch_experiment(params):
    """Spawn `sim.agent.experiment` with the given params. Returns the run name."""
    name = _valid_name(params["name"])
    rd = run_dir(name)
    if name in _REGISTRY and _REGISTRY[name].poll() is None:
        raise ValueError(f"A run named {name!r} is already training.")
    os.makedirs(rd, exist_ok=True)

    cmd = [PYTHON, "-u", "-m", "sim.agent.experiment", "--name", name,
           "--arch", params["arch"], "--window", str(params["window"]),
           "--episodes", str(params["episodes"]), "--batch-size", str(params["batch_size"]),
           "--d-model", str(params["d_model"]), "--seq-layers", str(params["seq_layers"]),
           "--val-every", str(params.get("val_every", 100))]
    indicators = params.get("indicators")
    if indicators:
        for g in indicators:
            if g not in ALL_GROUPS:
                raise ValueError(f"Unknown indicator group {g!r}")
        cmd += ["--indicators", *indicators]

    # persist launch params so progress % + config survive a server restart
    launch = {"params": params, "cmd": cmd, "total_episodes": params["episodes"]}
    with open(os.path.join(rd, "launch.json"), "w", encoding="utf-8") as fh:
        json.dump(launch, fh, indent=2)

    console = open(os.path.join(rd, "console.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=console, stderr=subprocess.STDOUT, cwd=os.getcwd())
    _REGISTRY[name] = proc
    return name


def launch_dataset(scope="nasdaq100", start="2015-01-01", limit=None):
    """Spawn the (torch-free) dataset build. Returns True if started."""
    if _DATASET_PROC[0] is not None and _DATASET_PROC[0].poll() is None:
        raise ValueError("Dataset build already running.")
    os.makedirs("models", exist_ok=True)
    cmd = [PYTHON, "-u", "-m", "sim.agent.dataset", "--scope", scope, "--start", start]
    if limit:
        cmd += ["--limit", str(limit)]
    log = open(DATASET_LOG, "w", encoding="utf-8")
    _DATASET_PROC[0] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=os.getcwd())
    return True


def stop(name):
    proc = _REGISTRY[name] if name in _REGISTRY else None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        return True
    return False


# ── reading artifacts ─────────────────────────────────────────────────────────

def _status(name):
    report = os.path.join(run_dir(name), "report.md")
    if name in _REGISTRY:
        if _REGISTRY[name].poll() is None:
            return "running"
        return "done" if os.path.exists(report) else "failed"
    if os.path.exists(report):
        return "done"
    return "unknown"


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_text(path, tail_lines=None):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if tail_lines:
        return "\n".join(text.splitlines()[-tail_lines:])
    return text


def _parse_csv(path):
    if not os.path.exists(path):
        return None
    import csv
    with open(path, "r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _total_episodes(name):
    launch = _read_json(os.path.join(run_dir(name), "launch.json"))
    if launch and "total_episodes" in launch:
        return int(launch["total_episodes"])
    cfg = _read_json(os.path.join(run_dir(name), "config.json"))
    return int(cfg["episodes"]) if cfg and "episodes" in cfg else None


def summary(name):
    """Lightweight status for the runs list."""
    rd = run_dir(name)
    log = _parse_csv(os.path.join(rd, "train_log.csv")) or []
    total = _total_episodes(name)
    cfg = _read_json(os.path.join(rd, "config.json")) or _read_json(os.path.join(rd, "launch.json")) or {}
    params = cfg.get("params", cfg)
    return {
        "name": name,
        "status": _status(name),
        "episode": len(log),
        "total_episodes": total,
        "progress": (len(log) / total) if total else 0.0,
        "arch": params.get("arch"),
        "indicators": params.get("indicators") or ALL_GROUPS,
        "best_metric": cfg.get("best_metric"),
    }


def list_runs():
    if not os.path.isdir(RUNS_DIR):
        return []
    names = [n for n in os.listdir(RUNS_DIR) if os.path.isdir(run_dir(n))]
    out = [summary(n) for n in names]
    out.sort(key=lambda r: (r["status"] != "running", r["name"]))
    return out


def read_run(name):
    """Full detail for the report view."""
    _valid_name(name)
    rd = run_dir(name)
    if not os.path.isdir(rd):
        return None
    train_log = _parse_csv(os.path.join(rd, "train_log.csv")) or []
    total = _total_episodes(name)
    tape = None
    for fn in os.listdir(rd):
        if fn.startswith("tape_") and fn.endswith(".csv"):
            tape = _parse_csv(os.path.join(rd, fn))
            break
    return {
        "name": name,
        "status": _status(name),
        "episode": len(train_log),
        "total_episodes": total,
        "progress": (len(train_log) / total) if total else 0.0,
        "config": _read_json(os.path.join(rd, "config.json")),
        "launch": _read_json(os.path.join(rd, "launch.json")),
        "report_md": _read_text(os.path.join(rd, "report.md")),
        "console_tail": _read_text(os.path.join(rd, "console.log"), tail_lines=40),
        "train_log": train_log,
        "tape": tape,
    }


def dataset_status():
    from sim.agent.dataset import DATASET_PATH
    exists = os.path.exists(DATASET_PATH)
    building = _DATASET_PROC[0] is not None and _DATASET_PROC[0].poll() is None
    meta = None
    if exists:
        import numpy as np
        d = np.load(DATASET_PATH, allow_pickle=True)
        meta = d["meta"].item()
        meta["n_features"] = len(d["feature_names"])
        meta["n_train_tickers"] = len(d["train_tickers"])
    return {"exists": exists, "building": building, "meta": meta,
            "log_tail": _read_text(DATASET_LOG, tail_lines=15)}
