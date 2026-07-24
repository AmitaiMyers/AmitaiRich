# ROOF·SIM — Day-Trading Simulator

A real-time, second-by-second **paper day-trading practice app** built on real
Yahoo Finance data. You get a fake **$100,000** and a full trading day you can
scrub, rewind and fast-forward while placing simulated buy/sell orders against a
live-updating candlestick chart and order book.

It's a faithful implementation of the design in `Trading Simulator.dc.html` /
`data-pipeline.js`, wired to **real market data** instead of synthetic data.

## What's real vs. reconstructed

Yahoo's finest free granularity is the **1-minute bar** (and only for ~the last
30 days). True tick data isn't available for free, so:

- **Prices** — real Yahoo **1-minute OHLCV** bars, deterministically interpolated
  down to per-second ticks. Every real Open/High/Low/Close is preserved exactly at
  minute resolution; only the sub-minute path between anchors is reconstructed.
- **Volume** — split across each minute's 60 seconds so the per-minute total
  matches the real reported volume.
- **Order book (Level 2) & time-and-sales** — **synthesized** deterministically
  around the real price. No free source provides these; they're stable per
  ticker+date so support/resistance "walls" stay consistent through a session.

## Architecture

```
sim/
  datasource.py   # DataSource interface + YahooFinanceSource (1m→1s) + SyntheticSource
  ingest.py       # CLI: pre-fetch & cache real sessions as JSON
  store.py        # JSON session cache (sim_cache/{TICKER}_{DATE}.json)
  server.py       # FastAPI: serves sessions + the static front-end
  frontend/
    index.html    # layout
    styles.css    # dark terminal theme
    rng.js        # deterministic PRNG (order-book synthesis)
    data-source.js# API-backed session loader
    app.js        # canvas chart, order entry, blotter, playback (ported design)
sim_cache/        # cached sessions (gitignored)
```

Data flow: `ingest`/`server` → `datasource.YahooFinanceSource` (yfinance 1m →
interpolate) → `store` (JSON) → `server` API → `frontend` (canvas render).

## Two data modes

The header has a **STOCKS / CRYPTO** toggle:

- **STOCKS** — real Yahoo 1-minute bars interpolated to seconds. Prices/volume are
  real; the **order book, bid/ask, and liquidity walls are synthesized** (Yahoo has
  no free Level-2 data). Real, cached trading days via the date picker.
- **CRYPTO** — real **Binance** recordings where **every value is real**: candles,
  volume, prev-close, bid/ask, the full Level-2 order-book ladder (evolving
  second-by-second), and the resting-liquidity walls. Instruments are crypto pairs
  (BTC/ETH/SOL/…). Trades use fractional quantities. Pick a recording from the
  dropdown. See "Recording real crypto" below.

Why crypto for full realism: no free source provides real Level-2 depth for US
equities, but crypto exchanges publish their full order book for free. So to
replace **all** synthetic data with real data, the simulator records crypto.

### Recording real crypto sessions

Real Level-2 depth only exists live, so recording is **real-time** (`--minutes 3`
takes 3 minutes). No API key or signup — Binance public REST.

```bash
python -m sim.crypto_record                          # BTC+ETH+SOL, 3 min, depth 100
python -m sim.crypto_record --minutes 5 --symbols BTCUSDT ETHUSDT
python -m sim.crypto_record --seconds 120 --depth 50 --symbols BTCUSDT
```

Each run saves one JSON per symbol (`sim_cache/crypto_{SYMBOL}_{recid}.json`) and
appears in the CRYPTO dropdown. Symbols in a run are recorded concurrently and
share a recording id.

## Technical indicators

Toggle in the chart header (**BB · VOL · ADX · OBV**), computed on the candles at
the selected interval — all from OHLCV, so they work in **both** modes:

- **BB** — Bollinger Bands (14, 2) overlaid on price.
- **VOL** — volume underlay (colored by up/down candle).
- **ADX** — Average Directional Index (14) in its own panel, with a 25 threshold.
- **OBV** — On-Balance Volume in its own panel.

The same indicators feed the **training agent**: `TradingEnv` appends %B, Bollinger
bandwidth, ADX/100, normalized OBV, and relative volume to its state vector (see
`sim/agent/env.py`; math in `indicators.py`, mirrored in `sim/frontend/indicators.js`).

## Training the DQN agent

Two training tracks share the same (bigger, Double-DQN) network:

### A) Daily dataset — the main track (recommended)

A proper ML dataset: **daily candles** across the Nasdaq-100, every indicator in
`indicators.py` as stationary features (returns, SMA gaps, RSI, %B, bandwidth,
ATR%, ADX/±DI, OBV z-score, volume ratio, efficiency ratio, swing gaps), split
**temporally per ticker** (train = older history, validation = most recent slice,
no lookahead).

```bash
# 1) Build the dataset  -> models/daily_dataset.npz
python -m sim.agent.dataset                         # nasdaq100, 2015->today
python -m sim.agent.dataset --scope sp500_ndx       # bigger universe
python -m sim.agent.dataset --limit 40 --start 2018-01-01   # quicker build

# 2) Train              -> saves models/dqn_daily_best.pth (best on validation) + dqn_daily.pth (final)
python -m sim.agent.train_daily                        # MLP over per-day features
python -m sim.agent.train_daily --arch gru --window 30         # GRU over a 30-day window
python -m sim.agent.train_daily --arch transformer --window 40 # Transformer encoder

# 3) Validate the best checkpoint on the held-out split (arch/window auto-detected)
python -m sim.agent.validate                        # day-by-day tape + equity curve + aggregate
python -m sim.agent.validate --ticker NVDA --daily  # print EVERY session's decision
python -m sim.agent.validate --verbose              # per-ticker aggregate table
```

**Live training view** — `train_daily` shows a progress bar that updates every
episode (episode, epsilon, rolling return, ep/s) and, at each validation, logs a
permanent line with a **sparkline** of validation return over time (★ marks a new
best, which is saved immediately).

**Day-by-day validation tape** — `validate` walks the model through unseen days one
at a time, *like live trading*, printing each **BUY/SELL** decision with the real
date, price, position and running equity, then an **equity curve** and a trade
summary (win rate, return vs buy & hold).

### Agent Lab GUI (point-and-click)

A full browser GUI to configure, launch, watch, and review training runs — no CLI:

```bash
conda activate ntp          # IMPORTANT: start the server from the env that has torch,
python -m sim.server        # so GUI-launched training subprocesses can import torch
```

Open **http://127.0.0.1:8000/agent.html** (or click **🧪 AGENT LAB** in the simulator
header). From there you can:
- see **dataset status** and build/rebuild it with one click;
- start a run: name it, tick which **indicators** to use, pick **arch / window /
  episodes / batch / d_model / layers**, press **Start**;
- watch it **live** — progress bar, training-return + loss + validation charts that
  update as episodes complete (polled from `train_log.csv`);
- browse all runs and open any **report**: metric cards, charts, the **day-by-day
  BUY/SELL tape** (colored), the **equity curve**, the rendered `report.md`, and the
  console. Each run's artifacts live in `models/runs/<name>/`.

(The server that serves the GUI is torch-free; it launches each training run as a
subprocess using its own interpreter — hence starting it from the `ntp` env, or set
`SIM_AGENT_PYTHON=<path-to-ntp-python>`.)

### One-command experiments (CLI)

`experiment.py` runs the whole thing — train (with live visuals) → validate → save
model + report — into its own folder, for **any** DQN params and **any** subset of
indicators (all on 1-day candles):

```bash
python -m sim.agent.experiment --name bb_adx  --indicators bollinger adx
python -m sim.agent.experiment --name prices_only --indicators prices --arch mlp
python -m sim.agent.experiment --name gru_all --arch gru --window 30 --episodes 3000
```

Each run writes to `models/runs/<name>/`:
`report.md` (config + training curve + validation metrics + a day-by-day sample with
equity curve), `config.json`, `dqn_daily_best.pth` / `dqn_daily.pth`, `train_log.csv`
(per-episode return + loss), and `tape_<ticker>.csv` (day-by-day BUY/SELL decisions).

**Indicator groups** (`--indicators`, choose any subset; default all): `prices`
(candle OHLC), `volume` (vol underlay), `bollinger`, `adx`, `obv`. The dataset is
built once with all groups; selecting a subset just slices columns — no rebuild.
Same flag works on `train_daily` directly (`--indicators ...`).

**Model architectures** (`--arch`): `mlp` sees one day's features at a time;
`gru` / `transformer` encode a **window** of the last N days (`--window`), so the
agent learns temporal patterns the indicators don't capture. The window is formed
on the fly from the same dataset (no rebuild), flattened into the state, and
reshaped back to `[batch, window, features]` inside the encoder. The checkpoint
records the arch + window, so `validate` reconstructs the right network automatically.

The model **saves twice**: the best-on-validation checkpoint is written the moment
it improves, and a final checkpoint at the end (each stores its architecture +
feature list, so `validate` always reloads a matching network). Validation reports
mean/median return, % profitable, and **excess vs buy & hold**.

**Network** (`dqn_model.py`): a **Dueling** architecture — a residual, LayerNorm'd
`256→256→128` trunk feeding separate **value V(s)** and **advantage A(s,a)** heads
(`Q = V + A − mean A`), with **NoisyNet** heads for learned, state-dependent
exploration. **Agent** (`dqn_agent.py`): **Double DQN** (online net selects the next
action, target net scores it), a 50k replay buffer, and lr 5e-4. With NoisyNet on,
exploration comes from sampled network noise rather than ε-greedy.

### B) Intraday sessions — the original track

Trains per-second on real stock sessions or crypto recordings (indicator features
included via `TradingEnv`):

```bash
python -m sim.agent.train --source stock            # real Yahoo day-sessions
python -m sim.agent.train --source crypto           # real Binance recordings
python -m sim.agent.eval  --source crypto           # evaluate on a crypto session
```

## Run it

From the repo root, with an environment that has the deps
(`pip install -r requirements.txt` — adds `fastapi`, `uvicorn` to the existing
`yfinance`/`pandas`/`numpy`):

```bash
# 1) Pre-fetch the last 5 trading days for the 5 tickers (writes sim_cache/*.json)
python -m sim.ingest --days 5

# 2) Start the server
python -m sim.server            # -> http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and trade. Picking a **date** that isn't cached makes
the server fetch it live from Yahoo and cache it (any recent trading day works).

### Ingest options

```bash
python -m sim.ingest --days 10                 # last 10 trading days
python -m sim.ingest --dates 2026-07-15 2026-07-16
python -m sim.ingest --source synthetic        # offline demo data, no network
python -m sim.ingest --force                   # re-fetch even if cached
```

### Server options (env vars)

```bash
SIM_HOST=0.0.0.0 SIM_PORT=9000 python -m sim.server
SIM_SOURCE=synthetic python -m sim.server      # serve fabricated data offline
```

## Features

- **Japanese candlestick chart** on canvas with selectable intervals
  (5s / 15s / 1m / 5m / 30m / 1h), volume bars, a right-edge volume-profile
  histogram, prev-close & last-price lines, and buy/sell fill markers.
- **Trend-line drawing tool** — click *LINE*, drag on the chart; click a line to
  select, `Del` / *DEL* to remove, *CLEAR* to wipe all.
- **Visual order book** — bid/ask depth ladder with size bars and live spread,
  plus resting-liquidity S/R walls drawn on the chart.
- **Order entry** — quantity + one-click BUY @ ask / SELL @ bid (supports shorts).
- **Bracket / stop-loss orders** — attach an OCO (one-cancels-other) stop and/or
  take-profit to a position. Type levels or leave blank for suggested defaults, then
  *BRACKET*. Levels show as dashed lines on the chart and in a WORKING ORDERS list
  (✕ to cancel). Orders fire **intrabar** as the clock advances — frame-rate
  independent (the whole traversed interval is scanned, so a level crossed between
  ticks at 60× is never skipped), across all tickers, and fill at the level (tagged
  STP/TGT in the blotter). Scrubbing/rewinding never triggers fills; brackets
  auto-cancel/resize when you manually close, flip, or reduce the position.
- **Time & Sales** tape, **Positions** blotter (avg / last / unrealized /
  realized P&L) and a **Fills** log.
- **Playback transport** — jump-to-open/close, step ±1s, play/pause, a full-session
  scrubber, and 1×–60× speed. Keyboard: `Space` play/pause, `←`/`→` step.
- **$100,000** paper cash with live CASH / EQUITY / DAY P&L in the header.
- **Five stocks**: AAPL, MSFT, NVDA, TSLA, SPY.

## Extending

Add a live tick provider (or a different vendor) by implementing
`DataSource.load_session` and returning it from `create_data_source()` in
`sim/datasource.py`. Nothing in the server or front-end needs to change.
