// Positions: your holdings (stored only on this device) with today's HOLD/SELL verdict,
// computed locally with the production strategy — the same check as scan_today.py.

import { isoToDay, loadBars } from '../data.js';
import { buildStrategy } from '../engine/strategies.js';
import { holdingVerdict } from '../holdings.js';
import { addPosition, listPositions, makePosition, parseCsv, removePosition, replaceAll, toCsv } from '../positions.js';
import { downloadText, h, kpi, money, num, pct, signClass, table } from '../ui.js';

function cushion(toExit) {
  if (toExit === null) return '—';
  const width = Math.max(4, Math.min(100, Math.abs(toExit) * 4));
  return h('div', { class: 'row', style: 'gap:6px;flex-wrap:nowrap' },
    h('div', { class: 'cushion', title: 'Distance above the exit line' },
      h('div', { style: `width:${width}%;background:var(${toExit > 5 ? '--up' : toExit > 0 ? '--warn' : '--down'})` })),
    h('span', { class: `num ${signClass(toExit)}`, text: pct(toExit) }));
}

async function evaluate(positions, strategy, stopMode) {
  return Promise.all(positions.map(async (p) => {
    try {
      const bars = await loadBars(p.ticker);
      return { ...p, result: holdingVerdict(bars, strategy, isoToDay(p.entryDate), p.entryPrice, stopMode) };
    } catch (error) {
      return { ...p, error: error.message };   // one bad position is shown, not fatal
    }
  }));
}

export async function renderPositions(context) {
  const { manifest } = context;
  const production = manifest.production;
  const strategy = buildStrategy(production.strategy, production.config);
  const positions = listPositions();
  const rows = await evaluate(positions, strategy, production.stop_mode);
  const ok = rows.filter((r) => r.result);
  const sells = ok.filter((r) => r.result.verdict === 'SELL');
  ok.sort((a, b) => (a.result.verdict === b.result.verdict ? (a.result.toExit ?? 1e9) - (b.result.toExit ?? 1e9)
    : a.result.verdict === 'SELL' ? -1 : 1));
  const withShares = ok.filter((r) => r.shares !== null);
  const value = withShares.reduce((sum, r) => sum + r.shares * r.result.lastClose, 0);
  const cost = withShares.reduce((sum, r) => sum + r.shares * r.result.entryPrice, 0);

  const message = h('p', { class: 'small', role: 'status' });
  const rerender = async () => {
    const page = await renderPositions(context);
    document.getElementById('view').replaceChildren(page);
  };

  const form = h('form', { class: 'card form-grid', onsubmit: async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      addPosition(makePosition(data, context.tickers));
      await rerender();
    } catch (error) {
      message.className = 'small down';
      message.textContent = error.message;
    }
  } },
  h('label', { class: 'field' }, 'Ticker', h('input', { name: 'ticker', required: true, list: 'ticker-list', autocapitalize: 'characters' })),
  h('label', { class: 'field' }, 'Entry date', h('input', { name: 'entryDate', type: 'date', required: true, max: manifest.data_date })),
  h('label', { class: 'field' }, 'Entry price (optional)', h('input', { name: 'entryPrice', type: 'number', step: 'any', min: '0', placeholder: 'entry-day close' })),
  h('label', { class: 'field' }, 'Shares (optional)', h('input', { name: 'shares', type: 'number', step: 'any', min: '0' })),
  h('div', { class: 'row', style: 'align-self:end' }, h('button', { class: 'primary', type: 'submit', text: 'Add position' })));

  const fileInput = h('input', { type: 'file', accept: '.csv,text/csv', hidden: true, onchange: async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const imported = parseCsv(await file.text(), context.tickers);
      if (!confirm(`Replace your ${positions.length} positions with ${imported.length} from ${file.name}?`)) return;
      replaceAll(imported);
      await rerender();
    } catch (error) {
      message.className = 'small down';
      message.textContent = error.message;
    }
  } });

  const verdictTable = ok.length ? table([
    { label: 'Ticker', value: (r) => h('a', { href: `#/t/${r.ticker}`, text: r.ticker }) },
    { label: 'Verdict', value: (r) => h('span', { class: `badge ${r.result.verdict.toLowerCase()}`, text: r.result.verdict }) },
    { label: 'Why', value: (r) => r.result.reason },
    { label: 'P&L', value: (r) => pct(r.result.openPnl), num: true, cls: (r) => signClass(r.result.openPnl) },
    { label: 'Last', value: (r) => num(r.result.lastClose), num: true },
    { label: 'Entry', value: (r) => num(r.result.entryPrice), num: true },
    { label: 'Exit line', value: (r) => num(r.result.exitLevel), num: true },
    { label: 'Cushion', value: (r) => cushion(r.result.toExit) },
    { label: 'Stop', value: (r) => num(r.result.stopPrice), num: true },
    { label: '1-mo', value: (r) => pct(r.result.mom1m), num: true, cls: (r) => signClass(r.result.mom1m) },
    { label: 'Held', value: (r) => `${r.result.barsHeld}d`, num: true },
    { label: '', value: (r) => h('button', { class: 'danger', type: 'button', text: 'Remove', 'aria-label': `Remove ${r.ticker}`,
      onclick: async (event) => { event.stopPropagation(); if (confirm(`Remove ${r.ticker} (${r.entryDate})?`)) { removePosition(r.id); await rerender(); } } }) },
  ], ok) : h('div', { class: 'card empty', text: 'No positions yet. Add one below, or import your positions.csv.' });

  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', { text: 'Your positions' }),
        h('div', { class: 'muted small', text: 'Stored only in this browser. Verdicts use the production rules on the latest published close.' })),
      h('div', { class: 'row' },
        h('button', { type: 'button', text: 'Import CSV', onclick: () => fileInput.click() }),
        h('button', { type: 'button', text: 'Export CSV', disabled: !positions.length,
          onclick: () => downloadText(`positions-${manifest.data_date}.csv`, toCsv(positions)) }),
        fileInput)),
    h('div', { class: 'grid kpis' },
      kpi('Positions', String(positions.length), `target ~${production.target_positions}`),
      kpi('SELL today', String(sells.length), sells.map((r) => r.ticker).join(', ') || 'none', sells.length ? 'down' : ''),
      kpi('Open P&L', withShares.length ? money(value - cost) : '—',
        withShares.length ? pct((value / cost - 1) * 100) : 'add share counts to see $', signClass(value - cost)),
      kpi('Market value', withShares.length ? money(value) : '—', `as of ${manifest.data_date}`)),
    h('div', { class: 'section' }, verdictTable),
    rows.filter((r) => r.error).map((r) => h('p', { class: 'small down',
      text: `${r.ticker} (${r.entryDate}): ${r.error}` })),
    h('div', { class: 'section' }, h('h2', { text: 'Add a position' }), form, message),
  );
}
