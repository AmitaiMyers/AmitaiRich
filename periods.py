"""The validation protocol's periods, and the lock on the holdout (see GOAL_SPEC.md).

Development: every idea is tried and tuned here. Validation: checked every round, side by side.
Holdout: LOCKED — only `open_holdout()` may evaluate it, and every opening is appended to
ALGO_LOG.md. Anything else that touches holdout dates raises HoldoutLockedError.
"""

from datetime import date

import pandas as pd

from errors import SimulatorError

DEVELOPMENT = (pd.Timestamp("2005-01-01"), pd.Timestamp("2018-12-31"))
VALIDATION = (pd.Timestamp("2019-01-01"), pd.Timestamp("2022-12-31"))
HOLDOUT_START = pd.Timestamp("2023-01-01")
ALGO_LOG = "ALGO_LOG.md"


class HoldoutLockedError(SimulatorError):
    """Research code tried to use data from the locked holdout period."""


def research_window(name):
    """(start, end) for 'development' or 'validation' (never the holdout)."""
    windows = {"development": DEVELOPMENT, "validation": VALIDATION}
    if name not in windows:
        raise HoldoutLockedError(f"Unknown or locked window {name!r}; use development/validation.")
    return windows[name]


def assert_before_holdout(last_date):
    """Fail fast if an evaluation would use any outcome dated in the holdout."""
    if pd.Timestamp(last_date) >= HOLDOUT_START:
        raise HoldoutLockedError(
            f"Evaluation reaches {pd.Timestamp(last_date).date()} — the holdout starts "
            f"{HOLDOUT_START.date()} and is locked. Use periods.open_holdout() for a final candidate.")


def open_holdout(version, reason):
    """Unlock the holdout for one evaluation of `version`, recording it in ALGO_LOG.md."""
    with open(ALGO_LOG, "a") as fh:
        fh.write(f"- {date.today().isoformat()}: holdout opened for **{version}** — {reason}\n")
    return HOLDOUT_START, pd.Timestamp(date.today())
