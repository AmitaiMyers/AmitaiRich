// API-backed data source. Same role as the design's SyntheticYahooSource, but it
// pulls REAL, pre-interpolated per-second sessions from the FastAPI backend
// (which downloads real Yahoo 1m bars and interpolates them to seconds). Swap the
// backend implementation without touching the UI — the interface is unchanged:
//   loadAll(date) -> { TICKER: Session }
//   Session = { ticker, name, date, prevClose, prices: Float64Array, vols: Float32Array }

export const SESSION_SECONDS = 23400;

function normalize(s) {
  return {
    ticker: s.ticker,
    name: s.name,
    date: s.date,
    prevClose: s.prevClose,
    prices: Float64Array.from(s.prices),
    vols: Float32Array.from(s.vols),
  };
}

async function readError(res) {
  const body = await res.json().catch(() => null);
  return new Error((body && body.error) || ('HTTP ' + res.status + ' ' + res.statusText));
}

class ApiSource {
  async tickers() {
    if (!this._tickers) {
      const res = await fetch('/api/tickers');
      if (!res.ok) throw await readError(res);
      this._tickers = await res.json();
    }
    return this._tickers;
  }

  async availableDates() {
    const res = await fetch('/api/dates');
    if (!res.ok) throw await readError(res);
    return res.json();
  }

  // Load all five tickers for one session date in a single (gzipped) request.
  async loadAll(dateStr) {
    const res = await fetch('/api/session/' + encodeURIComponent(dateStr));
    if (!res.ok) throw await readError(res);
    const data = await res.json();
    const sessions = {};
    for (const [ticker, session] of Object.entries(data.sessions)) {
      sessions[ticker] = normalize(session);
    }
    return sessions;
  }
}

export function createDataSource() {
  return new ApiSource();
}
