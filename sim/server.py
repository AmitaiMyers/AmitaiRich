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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from errors import SimulatorError
from sim.datasource import TICKERS, create_data_source
from sim import store

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


# Static front-end last, so the API routes above take precedence.
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


def main():
    host = os.environ.get("SIM_HOST", "127.0.0.1")
    port = int(os.environ.get("SIM_PORT", "8000"))
    print(f"ROOF·SIM serving on http://{host}:{port}  (data source: {_SOURCE_KIND})")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
