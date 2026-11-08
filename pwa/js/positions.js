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
