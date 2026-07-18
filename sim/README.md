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
