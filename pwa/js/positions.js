// Your positions — stored ONLY in this browser (localStorage), never uploaded.
// CSV import/export uses the same columns as the repo's positions.csv.

import { store } from './ui.js';

const KEY = 'roof.positions.v1';
export const CSV_COLUMNS = ['ticker', 'entry_date', 'entry_price', 'shares'];

export const normalizeTicker = (s) => s.trim().toUpperCase().replace(/\./g, '-');

export function listPositions() {
  return store.read(KEY, []);
}

function save(positions) {
  store.write(KEY, positions);
}

/** Validate and normalise one position; throws a readable Error on bad input. */
export function makePosition({ ticker, entryDate, entryPrice, shares }, knownTickers) {
  const symbol = normalizeTicker(ticker || '');
  if (!symbol) throw new Error('Ticker is required.');
  if (!knownTickers.has(symbol)) throw new Error(`${symbol} is not in the published universe.`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(entryDate || '')) throw new Error('Entry date must be YYYY-MM-DD.');
  const price = entryPrice === '' || entryPrice === null || entryPrice === undefined ? null : Number(entryPrice);
  if (price !== null && !(price > 0)) throw new Error('Entry price must be a positive number (or empty = entry-day close).');
  const qty = shares === '' || shares === null || shares === undefined ? null : Number(shares);
  if (qty !== null && !(qty > 0)) throw new Error('Shares must be a positive number (or empty).');
  return { id: crypto.randomUUID(), ticker: symbol, entryDate, entryPrice: price, shares: qty };
}

export function addPosition(position) {
  save([...listPositions(), position]);
}

export function removePosition(id) {
  save(listPositions().filter((p) => p.id !== id));
}

export function heldTickers() {
  return new Set(listPositions().map((p) => p.ticker));
}

export function toCsv(positions) {
  const lines = positions.map((p) => [p.ticker, p.entryDate, p.entryPrice ?? '', p.shares ?? ''].join(','));
  return [CSV_COLUMNS.join(','), ...lines].join('\n') + '\n';
}

/** Parse a positions CSV (header required: ticker, entry_date[, entry_price][, shares]). */
export function parseCsv(text, knownTickers) {
  const rows = text.trim().split(/\r?\n/).map((line) => line.split(',').map((cell) => cell.trim()));
  const header = rows.shift().map((h) => h.toLowerCase());
  for (const required of ['ticker', 'entry_date']) {
    if (!header.includes(required)) throw new Error(`CSV is missing the "${required}" column.`);
  }
  const col = (row, name) => (header.includes(name) ? row[header.indexOf(name)] : '');
  return rows.filter((row) => row.some(Boolean)).map((row, k) => {
    try {
      return makePosition({ ticker: col(row, 'ticker'), entryDate: col(row, 'entry_date'),
                            entryPrice: col(row, 'entry_price'), shares: col(row, 'shares') }, knownTickers);
    } catch (error) {
      throw new Error(`CSV line ${k + 2}: ${error.message}`);
    }
  });
}

export function replaceAll(positions) {
  save(positions);
}

// ---------------------------------------------------------------------------
// Trade journal: positions you sold (also only on this device). Export it as CSV and keep the
// file (e.g. upload it to the repo's my_trades/ folder) to compare your trades with the signals.
// ---------------------------------------------------------------------------

const JOURNAL_KEY = 'roof.journal.v1';
export const JOURNAL_COLUMNS = ['status', 'ticker', 'entry_date', 'entry_price', 'shares', 'exit_date', 'exit_price',
  'return_pct', 'app_verdict', 'app_reason'];

export function listClosed() {
  return store.read(JOURNAL_KEY, []);
}

/** Move a position to the journal. `evaluated` = its HOLD/SELL result (entry price resolved, verdict). */
export function closePosition(position, evaluated, exitDate, exitPrice) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(exitDate)) throw new Error('Sell date must be YYYY-MM-DD.');
  if (exitDate < position.entryDate) throw new Error('Sell date is before the entry date.');
  if (!(exitPrice > 0)) throw new Error('Sell price must be a positive number.');
  const closed = { id: position.id, ticker: position.ticker, entryDate: position.entryDate,
                   entryPrice: evaluated.entryPrice, shares: position.shares, exitDate, exitPrice,
                   appVerdict: evaluated.verdict, appReason: evaluated.reason };
  store.write(JOURNAL_KEY, [...listClosed(), closed]);
  removePosition(position.id);
}

export function removeClosed(id) {
  store.write(JOURNAL_KEY, listClosed().filter((t) => t.id !== id));
}

export const closedReturnPct = (t) => (t.exitPrice / t.entryPrice - 1) * 100;

/** Open positions (with their evaluated entry price) + closed trades, one CSV. */
export function journalCsv(openRows, closed) {
  const cell = (x) => (x === null || x === undefined ? '' : String(x).replace(/[,\n]/g, ' '));
  const open = openRows.map((r) => ['open', r.ticker, r.entryDate, r.result.entryPrice, r.shares, '', '',
    ((r.result.lastClose / r.result.entryPrice - 1) * 100).toFixed(2), r.result.verdict, r.result.reason]);
  const done = closed.map((t) => ['closed', t.ticker, t.entryDate, t.entryPrice, t.shares, t.exitDate, t.exitPrice,
    closedReturnPct(t).toFixed(2), t.appVerdict, t.appReason]);
  return [JOURNAL_COLUMNS.join(','), ...[...done, ...open].map((row) => row.map(cell).join(','))].join('\n') + '\n';
}
