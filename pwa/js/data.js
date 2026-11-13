// Data access for the PWA: decode the compact price format (see pwa_format.py) and
// fetch the published JSON files. Pure functions first so Node tests can import them.

const MS_PER_DAY = 86400000;

/** Compact {start, dd, o, h, l, c, v} -> bars {ticker, dates (day numbers), open, high, low, close, volume}. */
export function decodeBars(encoded) {
  const n = encoded.dd.length;
  const dates = new Int32Array(n);
  let day = encoded.start;
  for (let i = 0; i < n; i++) { day += encoded.dd[i]; dates[i] = day; }
  return {
    ticker: encoded.ticker, dates,
    open: Float64Array.from(encoded.o), high: Float64Array.from(encoded.h),
    low: Float64Array.from(encoded.l), close: Float64Array.from(encoded.c),
    volume: Float64Array.from(encoded.v),
  };
}

export const dayToIso = (day) => new Date(day * MS_PER_DAY).toISOString().slice(0, 10);
export const isoToDay = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / MS_PER_DAY);

/** Bars restricted to [fromDay, toDay] (inclusive; either bound may be null). */
export function sliceBars(bars, fromDay, toDay) {
  let a = 0, b = bars.dates.length;
  if (fromDay !== null) while (a < b && bars.dates[a] < fromDay) a++;
  if (toDay !== null) while (b > a && bars.dates[b - 1] > toDay) b--;
  const cut = (arr) => arr.slice(a, b);
  return { ticker: bars.ticker, dates: cut(bars.dates), open: cut(bars.open), high: cut(bars.high),
           low: cut(bars.low), close: cut(bars.close), volume: cut(bars.volume) };
}

// ---------------------------------------------------------------------------
// Network (browser only). Paths are relative so the app works under any Pages subpath.
// ---------------------------------------------------------------------------

const barCache = new Map();

async function getJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

export const loadManifest = () => getJson('data/manifest.json');
export const loadSignals = () => getJson('data/signals.json');
export const loadDaily = () => getJson('data/daily.json');
export const loadCompany = (ticker) => getJson(`data/company/${encodeURIComponent(ticker)}.json`);

/** One ticker's full daily history (memoized for the session; the service worker caches it offline). */
export async function loadBars(ticker) {
  if (!barCache.has(ticker)) {
    barCache.set(ticker, getJson(`data/prices/${encodeURIComponent(ticker)}.json`).then(decodeBars));
  }
  try {
    return await barCache.get(ticker);
  } catch (error) {
    barCache.delete(ticker); // let a later attempt retry (e.g. after reconnecting)
    throw error;
  }
}
