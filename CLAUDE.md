# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local, zero-cost stock backtesting + research tool ("Capital Market Roof Simulator") with a
production daily scanner and a PWA ("Roof Signals") deployed to GitHub Pages.
Python backend (yfinance data, vectorized signals, one shared backtest engine, SQLite storage)
+ a Streamlit/Plotly dashboard + a static PWA whose JavaScript engine reproduces the Python
engine exactly. The production strategy is the Growth Momentum Rider (`scan_today.DEFAULT_*`).

## Commands

Dependencies live in a conda env named `ntp` (Python 3.13). The username path contains a space, which
breaks calling `conda.exe` by full path — **activate the env first**, or invoke conda via
`python -m conda` (not the `.exe` shim).

```powershell
conda activate ntp
streamlit run app.py                         # dashboard
python scan_today.py                         # daily BUY list + HOLD/SELL on positions.csv
python research_grids.py v3                  # research phase (see research_grids.py docstring)
python publish.py --out site --demo          # build the PWA offline (synthetic data)
```

Recreate / install: `conda env create -f environment.yml` or `pip install -r requirements.txt`
(`requirements-core.txt` is the lean set CI uses: no torch/streamlit).

**Tests (run before every commit; CI runs the same):**
```bash
python -m unittest discover -s tests -t .    # Python (~1 min, offline, synthetic data)
node --test pwa/tests/*.test.mjs             # JS engine exact parity with Python
python -m tests.make_js_fixtures             # regenerate the parity fixture after engine changes
```
Live-data checks still need network (yfinance): first fetch per (ticker, range, interval)
downloads; later runs read `data_cache/*.csv`. `data_engine.prefetch` bulk-downloads many tickers.

## Strict coding rules (enforced — deviations are rejected)

- **RIPER**: Readable, Intentional, Predictable, Explicit, Robust. Small focused functions, no clever tricks.
- **Fail fast, no silent failures**: never `.get()` on our own dicts (direct access + explicit validation);
  no `try/except` for control flow; no `.fillna()` (raise on empty/NaN/missing data instead). Invalid
  assumptions should crash with a named exception from `errors.py`.
- **No lookahead bias**: every indicator in a strategy's `_build_signals` must be causal (rolling /
  shifted / EWM windows that only look back). Signals are computed once on the full history, so a
  non-causal indicator WOULD leak the future — `tests/test_parity.py` (CausalityTest + per-bar
  parity with the frozen per-slice legacy engine) is the guard; run it after touching any strategy.
- **DRY**: shared math lives in `indicators.py`; fills/stops/sizing/costs live only in `engine.py`.
- **Python ↔ JS parity**: `pwa/js/engine/*` mirrors `indicators.py`/`algorithms.py`/`engine.py` for
  the production-family strategies. Change one side → regenerate the fixture → both test suites pass.
- **Surface bugs explicitly**: if you find a logic flaw or risky edge case, call it out and show the fix.

## Architecture (the parts that span files)

**Strategies** (`algorithms.py`): each class declares `DEFAULTS`, `warmup_bars()` and
`_build_signals(history) -> Signals` (vectorized arrays: `entry`, `exit`, `score`, stop candidates
`stop_levels` + `stop_atr`, and path-dependent exits `trail_atr` / `target_mult` / `max_hold`).
The base class derives the classic per-bar interface (`scan_and_buy`, `compute_stop`,
`calculate_sell`, `score_today`) from it. Strategies hold only config, so one instance is reused
across tickers. `build_algorithm(name, cfg)` filters to the class's `DEFAULTS` keys.

**Engine** (`engine.py`): the ONE day loop (one account, N stocks): next-open fills (sells then
buys) → intrabar stop (gap-downs fill at the open) → optional regime exit → BUY decisions at the
close ranked by score → SELL decisions → final-bar liquidation → mark to market. Entries are
state-based (a qualifying stock stays a candidate while its condition holds), like the daily scan.
- `simulation.run_simulation` = engine with one stock + SQLite persistence (dashboard).
- `portfolio.run_portfolio` = engine with the realistic account (`PortfolioConfig`: max positions,
  1% risk on live equity, cost bps, fill mode, rank_by, trade_from) + benchmarks
  (equal-weight B&H keeps each sleeve in cash until its stock lists; SPY B&H).
- `batch.run_batch` = independent per-stock runs (algorithm scan, not a portfolio). Per-ticker data
  failures are caught only at orchestration boundaries (`PER_TICKER_ERRORS`) — `ConfigurationError`
  is never caught.

**Buy/sell are independent roles**: the buy algorithm supplies entry + initial stop; the sell
algorithm supplies the discretionary exit. Exit = stop hit OR sell signal.

**Runtime toggles**: `stop_mode` (tightest/**widest** in production), `sizing_mode`
(**risk_based**/all_in/fixed_fraction), `fill_mode` (close/**next_open** = realistic for an
after-the-close scan), `interval` (**1d**/1h/1wk/1mo; periods are in bars).

**Production** (`scan_today.py`): `daily_report` (ranked BUY list + rank history) and
`holding_verdict` (pure HOLD/SELL) are shared by the CLI, `scan_sell_today.py`, `score_stock.py`,
the dashboard and `publish.py`.

**Research** (`research_portfolio.py` + `research_grids.py`): `Candidate` specs evaluated in parallel
on the 300/100 stock split; `v3` = train grid → finalists → OOS → re-drawn splits → walk-forward →
verdict. Reports land in `research_results/*.json` (published to the PWA). Env: `RESEARCH_END`,
`RESEARCH_OUT`, `RESEARCH_WORKERS`.

**PWA** (`pwa/`, built by `publish.py`, deployed by `.github/workflows/publish.yml`): static site;
positions live only in the browser (localStorage); HOLD/SELL runs client-side (`pwa/js/engine`).
Today shows the v0 + v7 lists from `data/daily.json` (= `signal_log/latest.json`, written daily by
`paper_trading.py` via `signal_log.py`; `signal_log/` keeps every day's lists (`history.csv`), names that
left a list with the reason (`list_exits.csv`) and the paper accounts' trades (`paper_trades.csv`)).
The owner's own sold trades are journaled on the device and exported to `my_trades/`.
**Magic Formula** (`magic_formula.py`): Greenblatt filter + rank (pure `magic_formula_rank(stocks, top_n)`), fed by
Yahoo fundamentals cached weekly in `market_data/fundamentals/magic_formula.json` (`--update-only` in the
daily job). Its top 30, every stock's rank and a valuation check (`valuation_check`: cheap / fair / expensive by
earnings yield, plus forward P/E, PEG, price/sales, analyst target) go into the daily record (`magic`), the
Today page and each stock page (`pwa/js/valuation.js`).
Live screen only — it is not a backtested strategy.
**Company pages**: `magic_formula.company_profiles` (name, sector, industry, business summary, website — fetched
with the fundamentals) + `company_news.py` (Yahoo headlines, refreshed daily in the Paper trading job, cached in
`market_data/news.json`); `publish.py` writes `data/company/<T>.json` (the publish job restores the market-data
cache) and the stock page shows them (`pwa/js/company.js`). Yahoo throttling is handled in `yahoo_batches.py`.
Daily phone push: `notify.py` + `webpush.py` (secrets VAPID_PRIVATE_KEY, PUSH_SUBSCRIPTION).
Price files use `pwa_format.py`'s compact format.

**Database** (`database.py`): single runs use `runs`/`trades`/`daily_equity`; batches use
`batches`/`batch_results`. Write helpers don't commit; `create_run`/`create_batch` do.

## yfinance gotchas baked into `data_engine.py`

- Single-ticker downloads still return **MultiIndex columns** — flattened via the level containing `Close`.
- `auto_adjust=True` (split/dividend-adjusted; no `Adj Close`).
- Share classes use a **dash, not a dot** on Yahoo: `fetch_data` normalizes `BRK.B` → `BRK-B`.
- Bulk downloads share one calendar: all-NaN rows (days a stock did not trade) are dropped.
- Intraday `1h` history is limited to ~the last 730 days; older ranges return empty → `EmptyDataError`.
- The cache key includes the interval and date range, so timeframes never collide.
