"""FastAPI server for the day-trading simulator.

Serves the canvas front-end plus a small JSON API over cached sessions:

    GET /api/tickers                 -> {ticker: company name}
    GET /api/dates                   -> [available session dates]  (fully cached)
    GET /api/session/{date}          -> {date, sessions: {ticker: session}}
    GET /api/session/{date}/{ticker} -> single session

Sessions are read from the JSON cache. If a requested date is not cached, the
server fetches it live via the data source and saves it (so the UI's date picker
can reach any recent trading day, not just the pre-ingested ones).

Run from the repo root:
    python -m sim.server            # http://127.0.0.1:8000
"""

import os

import uvicorn
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from errors import SimulatorError
from sim.datasource import TICKERS, create_data_source
from sim.crypto_source import CRYPTO_SYMBOLS
from sim import store
from sim.agent import jobs                       # torch-free job manager (spawns subprocesses)
from sim.agent.features import ALL_GROUPS

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
_SOURCE_KIND = os.environ.get("SIM_SOURCE", "yahoo")

app = FastAPI(title="ROOF·SIM day-trading simulator")
app.add_middleware(GZipMiddleware, minimum_size=1024)

_source = create_data_source(_SOURCE_KIND)


def _get_or_fetch(ticker, date_str):
    """Return a session from cache, fetching + caching it live on a miss."""
    if store.is_cached(ticker, date_str):
        return store.load_session(ticker, date_str)
    session = _source.load_session(ticker, date_str)  # may raise SimulatorError
    store.save_session(session)
    return session


@app.exception_handler(SimulatorError)
async def _sim_error_handler(_request, exc):
    # Domain errors (bad ticker, no data for that day, …) are client-visible 400s.
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/api/tickers")
def get_tickers():
    return TICKERS


@app.get("/api/dates")
def get_dates():
    return store.available_dates()


@app.get("/api/session/{date_str}/{ticker}")
def get_one(date_str, ticker):
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker!r}")
    return _get_or_fetch(ticker, date_str)


@app.get("/api/session/{date_str}")
def get_all(date_str):
    sessions = {t: _get_or_fetch(t, date_str) for t in TICKERS}
    return {"date": date_str, "sessions": sessions}


# ── crypto (real order-book) recordings ────────────────────────────────────────

@app.get("/api/crypto/symbols")
def crypto_symbols():
    return CRYPTO_SYMBOLS


@app.get("/api/crypto/recordings")
def crypto_recordings():
    """Recordings newest-first, enriched with length/start/names from one file each."""
    out = []
    for rec in store.crypto_recordings():
        meta = {"recid": rec["recid"], "symbols": rec["symbols"],
                "names": {s: CRYPTO_SYMBOLS.get(s, s) for s in rec["symbols"]}}
        if rec["symbols"]:
            head = store.load_crypto_session(rec["symbols"][0], rec["recid"])
            meta["length"] = head["length"]
            meta["start"] = head["start"]
        out.append(meta)
    return out


@app.get("/api/crypto/recording/{recid}")
def crypto_recording(recid):
    recs = {r["recid"]: r for r in store.crypto_recordings()}
    if recid not in recs:
        raise HTTPException(status_code=404, detail=f"Unknown recording {recid!r}")
    sessions = {s: store.load_crypto_session(s, recid) for s in recs[recid]["symbols"]}
    return {"recid": recid, "sessions": sessions}


# ── Agent Lab: train / validate DQN models from the GUI ────────────────────────

@app.get("/api/agent/options")
def agent_options():
    return {"indicator_groups": ALL_GROUPS, "archs": ["mlp", "gru", "transformer"],
            "dataset": jobs.dataset_status()}


@app.get("/api/agent/dataset")
def agent_dataset():
    return jobs.dataset_status()


@app.post("/api/agent/dataset")
def agent_build_dataset(payload: dict = Body(default={})):
    try:
        jobs.launch_dataset(scope=payload.get("scope", "nasdaq100"),
                            start=payload.get("start", "2015-01-01"),
                            limit=payload.get("limit"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"building": True}


@app.get("/api/agent/runs")
def agent_runs():
    return jobs.list_runs()


@app.post("/api/agent/train")
def agent_train(payload: dict = Body(...)):
    params = {
        "name": payload["name"],
        "indicators": payload.get("indicators") or None,
        "arch": payload.get("arch", "mlp"),
        "window": int(payload.get("window", 1)),
        "episodes": int(payload.get("episodes", 2000)),
        "batch_size": int(payload.get("batch_size", 128)),
        "d_model": int(payload.get("d_model", 128)),
        "seq_layers": int(payload.get("seq_layers", 2)),
        "val_every": int(payload.get("val_every", 100)),
    }
    try:
        name = jobs.launch_experiment(params)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": name}


@app.get("/api/agent/run/{name}")
def agent_run(name):
    run = jobs.read_run(name)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {name!r} not found")
    return run


@app.post("/api/agent/run/{name}/stop")
def agent_stop(name):
    return {"stopped": jobs.stop(name)}


# Static front-end last, so the API routes above take precedence.
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


def main():
    host = os.environ.get("SIM_HOST", "127.0.0.1")
    port = int(os.environ.get("SIM_PORT", "8000"))
    print(f"ROOF·SIM serving on http://{host}:{port}  (data source: {_SOURCE_KIND})")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
