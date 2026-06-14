# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, zero-cost stock backtesting + visualization tool ("Capital Market Roof Simulator").
Python backend (yfinance data, SQLite storage, day-by-day simulation) decoupled from a Streamlit +
Plotly frontend. The flagship strategy is a Bollinger squeeze + volume-bandwidth breakout.

## Commands

Dependencies live in a conda env named `ntp` (Python 3.13). The username path contains a space, which
breaks calling `conda.exe` by full path — **activate the env first**, or invoke conda via
`python -m conda` (not the `.exe` shim).

```powershell
conda activate ntp
streamlit run app.py            # launch the dashboard
```

Recreate / install:
```powershell
conda env create -f environment.yml      # or: pip install -r requirements.txt
```

**There is no automated test suite.** Verify changes by:
- Running a short simulation against live yfinance data through the `ntp` env Python, e.g. import
  `simulation.run_simulation` / `batch.run_batch` and assert on `compute_kpis` output.
- Booting Streamlit headless and checking health:
  `streamlit run app.py --server.headless true --server.port <p>` then GET
  `http://localhost:<p>/_stcore/health` (expects `ok`).

Network is required (yfinance). First fetch per (ticker, range, interval) downloads; subsequent runs
read `data_cache/*.csv`. Runs persist to `simulation.db`.

## Strict coding rules (enforced — deviations are rejected)

- **RIPER**: Readable, Intentional, Predictable, Explicit, Robust. Small focused functions, no clever tricks.
- **Fail fast, no silent failures**: never `.get()` on our own dicts (direct access + explicit validation);
  no `try/except` for control flow; no `.fillna()` (raise on empty/NaN/missing data instead). Invalid
  assumptions should crash with a named exception from `errors.py`.
- **No lookahead bias**: algorithms only ever receive history up to the current bar. The loop enforces
  this by passing `df.iloc[:i+1]` — never index ahead of `i` inside a strategy.
- **DRY**: shared math lives in `indicators.py`; shared stop selection in `algorithms.select_stop`.
- **Surface bugs explicitly**: if you find a logic flaw or risky edge case, call it out and show the fix.

## Architecture (the parts that span files)

Data flow: `app.py` builds strategy instances via `algorithms.build_algorithm` →
`simulation.run_simulation` (one ticker) or `batch.run_batch` (a universe) → `data_engine.fetch_data`
(+ `indicators`, `algorithms`) → `database` (SQLite) → read back for KPIs/charts.

**Strategy interface & registry** (`algorithms.py`): every strategy is a class implementing
`warmup_bars`, `scan_and_buy(history_slice)`, `compute_stop(entry, history, stop_mode)`,
`calculate_sell(position, history)`. They hold only config (no per-ticker state), so the same instance
is safely reused across many tickers in a batch. All are registered in `ALGORITHMS`; the GUI passes a
superset of params and `build_algorithm` filters each class's `DEFAULTS` keys (unknown keys raise).

**Buy/sell are independent roles** (`simulation.py`): the *buy* algorithm supplies the entry signal
**and** the initial stop (`compute_stop`); the *sell* algorithm supplies the discretionary exit
(`calculate_sell`). The simulation enforces the stop loss separately (intrabar, gap-down fills at
open), so an exit = stop hit OR sell signal. This is why the dashboard shows two dropdowns with the
same list — they mix one strategy's entry/stop with another's exit.

**Runtime toggles** (plumbed app → simulation/batch, defaults in bold): `stop_mode`
(**tightest**/widest, see `select_stop`), `sizing_mode` (**risk_based** + `risk_pct` / all_in /
fixed_fraction, in `_size_position`), `fill_mode` (**close**/next_open — next_open uses a pending-order
queue; an order on the last bar is dropped, never back-filled), `interval`
(**1d**/1h/1wk/1mo). Indicator periods are measured in **bars**, so strategies are timeframe-agnostic —
adding/changing a timeframe needs no algorithm changes.

**Batch mode** (`batch.py`): runs the strategy *independently* per ticker with the same starting
capital, so per-stock % returns are comparable. It is an algorithm-evaluation scan, **not** a
shared-capital portfolio. Per-ticker data failures are caught only at this orchestration boundary
(`PER_TICKER_ERRORS`) and recorded as `status='error'` rows — `ConfigurationError` is deliberately NOT
caught so a whole-batch setup mistake aborts loudly. This per-ticker `try/except` is the one sanctioned
exception to the no-try/except rule, and it surfaces errors in the summary rather than hiding them.

**Database** (`database.py`): single-runs use `runs`/`trades`/`daily_equity` (keyed by `run_id`);
batches use `batches`/`batch_results` (keyed by `batch_id`, each result links back to a `run_id`).
`init_db` is idempotent. Write helpers (`record_trade`/`record_equity`) do NOT commit — the simulation
loop commits once at the end as a batch; `create_run`/`create_batch` commit so ids are durable.

## yfinance gotchas baked into `data_engine.py`

- Single-ticker downloads still return **MultiIndex columns** — flattened to OHLCV via the level
  containing `Close`.
- `auto_adjust=True` (split/dividend-adjusted; no `Adj Close`).
- Share classes use a **dash, not a dot** on Yahoo: `BRK.B` → `BRK-B`. Ticker inputs are NOT yet
  auto-normalized — pasting `BRK.B` will raise `EmptyDataError`.
- Intraday `1h` history is limited to ~the last 730 days; older ranges return empty → `EmptyDataError`.
- The cache key includes the interval, so timeframes never collide; `simulation._date_str` stores the
  full datetime so intraday bars stay distinct.
