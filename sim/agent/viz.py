"""Dependency-free terminal visuals: progress bar, sparkline, ASCII line chart,
ANSI colors. Used to show training progress live and to render the day-by-day
validation tape + equity curve.
"""

import os
import re
import sys

_BLOCKS = "▁▂▃▄▅▆▇█"
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text):
    """Remove ANSI color codes — for writing plain text to report files."""
    return _ANSI_RE.sub("", text)

# ANSI colors (enabled below on Windows). Fall back to no-op if the terminal
# can't do color — the raw codes are harmless in modern terminals.
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
GREY = "\033[90m"


def _enable_ansi():
    if os.name == "nt":
        try:  # turn on Virtual-Terminal processing so ANSI codes render in the console
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    # Ensure UTF-8 output so the block/box-drawing glyphs don't crash on a
    # cp1252 console (common default on Windows).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


_enable_ansi()


def color(text, c):
    return f"{c}{text}{RESET}"


def pct(x, signed=True):
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def pct_color(x):
    """Green for positive, red for negative, grey for ~flat."""
    c = GREEN if x > 1e-9 else RED if x < -1e-9 else GREY
    return color(pct(x), c)


def bar(frac, width=24, fill="█", empty="░"):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return fill * filled + empty * (width - filled)


def sparkline(values):
    """Compact single-line trend using block characters."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BLOCKS[3] * len(values)
    return "".join(_BLOCKS[int((v - lo) / (hi - lo) * (len(_BLOCKS) - 1))] for v in values)


def ascii_chart(series, height=10, width=70, baseline=None):
    """Multi-line ASCII line chart. Optional `baseline` draws a reference row."""
    if not series:
        return ""
    n = len(series)
    if n > width:
        idx = [int(i * (n - 1) / (width - 1)) for i in range(width)]
        pts = [series[i] for i in idx]
    else:
        pts = list(series)
    lo, hi = min(pts), max(pts)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    if hi == lo:
        hi = lo + 1.0
    def row_of(v):
        return int(round((v - lo) / (hi - lo) * (height - 1)))
    grid = [[" "] * len(pts) for _ in range(height)]
    base_row = row_of(baseline) if baseline is not None else None
    if base_row is not None:
        for x in range(len(pts)):
            grid[height - 1 - base_row][x] = color("·", GREY)
    for x, v in enumerate(pts):
        grid[height - 1 - row_of(v)][x] = color("•", CYAN)
    lines = []
    for r, grow in enumerate(grid):
        val = hi - (hi - lo) * r / (height - 1)
        lines.append(f"{val:>10.2f} │ " + "".join(grow))
    lines.append(" " * 10 + " └" + "─" * len(pts))
    return "\n".join(lines)


def clear_line():
    sys.stdout.write("\r" + " " * 100 + "\r")
    sys.stdout.flush()


def live(text):
    """Overwrite the current terminal line (progress bar), no newline."""
    sys.stdout.write("\r" + text)
    sys.stdout.flush()


def action_label(action):
    """0=Hold, 1=Buy, 2=Sell -> colored fixed-width label."""
    if action == 1:
        return color("BUY ", GREEN + BOLD)
    if action == 2:
        return color("SELL", RED + BOLD)
    return color("hold", GREY)
