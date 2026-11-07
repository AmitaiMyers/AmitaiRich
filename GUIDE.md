# ROOF·SIM — Project Guide (what you can do & how to run it)

Everything runs from the repo root in the **`ntp` conda env** (has Python 3.13,
yfinance, torch, fastapi, …). Activate it first:

```bash
conda activate ntp
```

There are two things in this repo:
1. **The day-trading simulator + DQN agent** (`sim/`) — the focus of this guide.
2. **The original Bollinger-squeeze backtester** (Streamlit `app.py`) — see the bottom.

---

## 1. Run the day-trading simulator (web app)

```bash
python -m sim.server                 # -> http://127.0.0.1:8000
```

A real-time, second-by-second paper-trading app ($100k fake cash). Two data modes
(toggle in the header):

- **STOCKS** — real Yahoo 1-minute bars interpolated to per-second; the order book /
  bid-ask / liquidity walls are synthesized (no free L2 for stocks).
- **CRYPTO** — real Binance recordings where **everything is real** (candles, volume,
  bid/ask, full Level-2 order book, walls). Needs a recording first (see §2).

In the app: Japanese candlesticks, order book, time & sales, positions/fills,
**bracket / stop-loss (OCO) orders**, indicator overlays (**BB · VOL · ADX · OBV**),
trend-line drawing, and full playback (jump/step/scrub, 1×–60×).
Keyboard: `Space` play/pause · `←`/`→` step · `Del` delete selected trend line.

> Start the server **from the `ntp` env** — it also powers the Agent Lab (§4), which
> launches training with the same interpreter.

---

## 2. Get real market data

**Stock sessions** (real Yahoo 1m → per-second, cached to `sim_cache/`):
```bash
python -m sim.ingest --days 5                       # last 5 trading days, 5 tickers
python -m sim.ingest --dates 2026-07-16 2026-07-15  # specific days
```
(You can also just pick a date in the app; uncached days are fetched on demand.)

**Crypto sessions** (real Binance order book, no API key — recording is REAL-TIME):
```bash
python -m sim.crypto_record --minutes 20                           # BTC+ETH+SOL, 20 min
python -m sim.crypto_record --minutes 10 --symbols BTCUSDT ETHUSDT
```
Recorded sessions appear in the app's CRYPTO dropdown.

---

## 3. Build the agent's training dataset (daily candles + indicators)

```bash
python -m sim.agent.dataset                     # nasdaq100, 2015->today  (already built)
python -m sim.agent.dataset --scope sp500_ndx   # bigger universe
python -m sim.agent.dataset --limit 40          # quicker build
```
Writes `models/daily_dataset.npz`: daily OHLCV for the universe with all 5 indicator
groups, split train/validation temporally per ticker. Torch-free (only yfinance).

---

## 4. Train / validate the DQN agent

The agent is a **Dueling Double-DQN with NoisyNet** and an optional **GRU/Transformer**
sequence encoder. State = chosen indicators on **1-day candles**. Indicator groups:
`prices` · `volume` · `bollinger` · `adx` · `obv` (pick any subset).

> ### ⚠️ Build the dataset BEFORE training
> Training reads `models/daily_dataset.npz`, which is **gitignored and NOT in the
> repo**. On a fresh clone (or a new machine) you must build it once first:
> ```bash
> python -m sim.agent.dataset            # downloads daily bars, ~a few minutes
> ```
> Then train. (In the Agent Lab GUI, the dataset panel shows "not built" and offers a
> one-click **Build dataset** button.) Training aborts with a clear message if the
> dataset is missing.

### Easiest: the Agent Lab GUI
```bash
python -m sim.server        # from the ntp env, then open:
```
**http://127.0.0.1:8000/agent.html** (or click 🧪 AGENT LAB in the simulator).
Build the dataset, configure a run (indicators, arch, window, episodes, …), press
**Start**, watch **live** charts, and browse each run's **report** (metrics, training
curves, day-by-day BUY/SELL tape, equity curve). Artifacts land in `models/runs/<name>/`.

### One command (CLI): train + validate + report
```bash
python -m sim.agent.experiment --name bb_adx --indicators bollinger adx
python -m sim.agent.experiment --name gru_all --arch gru --window 30 --episodes 3000
```

### Or the steps individually
```bash
python -m sim.agent.train_daily --arch gru --window 30 --indicators prices bollinger adx
python -m sim.agent.validate                        # day-by-day tape + equity + metrics
python -m sim.agent.validate --ticker NVDA --daily  # every session's decision
python -m sim.agent.validate --csv                  # export the tape to CSV
```
Training saves `dqn_daily_best.pth` (best on validation) + `dqn_daily.pth` (final) +
`train_log.csv` (per-episode return & loss). Live terminal progress bar + validation
sparkline included.

Common knobs: `--arch mlp|gru|transformer` · `--window N` · `--episodes` ·
`--batch-size` · `--d-model` · `--seq-layers` · `--indicators ...`

*(Older intraday agent, trains per-second on sim sessions:*
`python -m sim.agent.train --source stock|crypto`*.)*

---

## Quick reference

| Task | Command |
|---|---|
| Run simulator + Agent Lab | `python -m sim.server` → http://127.0.0.1:8000 |
| Ingest real stock sessions | `python -m sim.ingest --days 5` |
| Record real crypto order book | `python -m sim.crypto_record --minutes 20` |
| Build training dataset | `python -m sim.agent.dataset` |
| Full experiment (train+val+report) | `python -m sim.agent.experiment --name X --indicators ...` |
| Train only | `python -m sim.agent.train_daily --arch gru --window 30` |
| Validate a model | `python -m sim.agent.validate --ticker NVDA` |
| Agent Lab GUI | open http://127.0.0.1:8000/agent.html |

## Where things are saved
- `sim_cache/` — stock sessions + crypto recordings (JSON)
- `data_cache/` — raw Yahoo daily/intraday CSV cache
- `models/daily_dataset.npz` — the agent training dataset
- `models/runs/<name>/` — per-run: models, `train_log.csv`, `report.md`,
  `config.json`, `tape_<ticker>.csv`, `console.log`

## Prerequisites & order
- Simulator CRYPTO mode → needs a recording (§2) first.
- Agent training → **needs the dataset built first** (§3): `python -m sim.agent.dataset`.
  The dataset is **gitignored (not in the repo)**, so on a fresh clone you must build
  it before `train_daily` / `experiment` / the GUI.
- GUI training → start the server **from the `ntp` env** (torch), or set
  `SIM_AGENT_PYTHON=<ntp python path>`.

## Running on another machine (fresh clone)

The **code** comes via git; the **data does not** (`models/`, `sim_cache/` are
gitignored). So regenerate what you need:

```bash
git clone https://github.com/AmitaiMyers/AmitaiRich.git && cd AmitaiRich   # (repo dir)
conda env create -f environment.yml      # installs deps incl. torch  (or: pip install -r requirements.txt)
conda activate ntp

python -m sim.agent.dataset              # 1) rebuild the training dataset (required, needs internet)
python -m sim.agent.experiment --name run1 --indicators bollinger adx --arch gru --window 30   # 2) train+validate
# or the GUI:  python -m sim.server   then open http://127.0.0.1:8000/agent.html
```

> **Train on a free GPU / keep it running when your laptop is off** → see
> **[COLAB.md](COLAB.md)** for a step-by-step Google Colab recipe.

Not carried by git (regenerate on the new machine): the dataset
(`python -m sim.agent.dataset`), stock sessions (`python -m sim.ingest`), crypto
recordings (`python -m sim.crypto_record`), and trained models (retrain, or copy the
`models/runs/<name>/` folder over manually).

---

## The original backtester (Streamlit)

The pre-existing Bollinger-squeeze backtesting dashboard (separate from the sim):
```bash
streamlit run app.py
```
See `README.md` / `CLAUDE.md` for its strategy registry, batch mode, and KPIs.
