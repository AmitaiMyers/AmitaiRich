// Today: the market regime, and the production strategy's ranked BUY list.

import { heldTickers } from '../positions.js';
import { h, kpi, num, pct, signClass, table } from '../ui.js';

const rankChange = (chg) => {
  if (chg === 'NEW') return h('span', { class: 'badge new', text: 'NEW' });
  const n = Number(chg);
  return h('span', { class: signClass(n), text: n > 0 ? `▲${n}` : n < 0 ? `▼${-n}` : '·' });
};

export function renderToday({ manifest, signals }) {
  const held = heldTickers();
  const m = signals.market;
  const strategy = manifest.production;
  const lists = ['All', ...Object.keys(manifest.lists)];
  let filter = 'All';
  const listHost = h('div');

  function drawList() {
    const rows = signals.candidates.filter((r) => filter === 'All' || r.src.split('/').includes(filter));
    listHost.replaceChildren(rows.length ? table([
      { label: '#', value: (r) => r.rank, num: true },
      { label: 'Δ', value: (r) => rankChange(r.chg) },
      { label: 'Ticker', value: (r) => h('strong', { text: r.ticker }) },
      { label: 'Close', value: (r) => num(r.close), num: true },
      { label: '6-mo momentum', value: (r) => pct(r['mom_%']), num: true, cls: (r) => signClass(r['mom_%']) },
      { label: 'vs 200-MA', value: (r) => pct(r.pct_vs_200ma), num: true },
      { label: 'Lists', value: (r) => h('span', { class: 'muted small', text: r.src }) },
      { label: '', value: (r) => (held.has(r.ticker) ? h('span', { class: 'badge', text: 'HELD' }) : '') },
    ], rows, { onRow: (r) => { location.hash = `#/t/${r.ticker}`; },
                rowClass: (r) => (held.has(r.ticker) ? 'held' : '') })
      : h('div', { class: 'card empty', text: 'No BUY signals in this list today.' }));
  }

  const filterBar = h('div', { class: 'segmented', role: 'group', 'aria-label': 'Filter by list' },
    lists.map((name) => h('button', {
      type: 'button', class: name === filter ? 'active' : null, text: name,
      onclick: (event) => {
        filter = name;
        for (const b of event.target.parentElement.children) b.classList.toggle('active', b === event.target);
        drawList();
      },
    })));
  drawList();

  const openSlots = Math.max(0, strategy.target_positions - held.size);
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', { text: `Signals for ${signals.date}` }),
        h('div', { class: 'muted', text: `${strategy.strategy} · ${signals.n_candidates} stocks qualify out of ${signals.universe_size} scanned` })),
      h('a', { href: '#/positions', class: 'chip', text: `${held.size} held · ${openSlots} open slots of ${strategy.target_positions}` })),
    h('div', { class: 'grid kpis' },
      kpi('Market (SPY)', m.risk_on ? 'Risk-on' : 'Risk-off', `${pct(m['spy_vs_ma200_%'])} vs 200-day MA`, m.risk_on ? 'up' : 'down'),
      kpi('Breadth', m['breadth_above_ma200_%'] === null ? '—' : `${m['breadth_above_ma200_%']}%`,
        `of ${m.breadth_universe} stocks above their 200-MA`),
      kpi('New today', String(signals.new_today.length), 'just qualified'),
      kpi('Dropped', String(signals.dropped.length), 'lost momentum or trend')),
    signals.risers.length ? h('div', { class: 'section' }, h('h3', { text: 'Top risers vs last scan' }),
      h('div', { class: 'chips' }, signals.risers.map(([t, d]) => h('a', { class: 'chip', href: `#/t/${t}`, text: `${t} ▲${d}` })))) : null,
    h('div', { class: 'section row' }, h('h2', { text: 'BUY candidates (strongest first)' }), h('span', { class: 'spacer' }), filterBar),
    h('p', { class: 'muted small', text:
      `Rules: buy when ${Math.round(strategy.config.mom_threshold * 100)}%+ 6-month momentum and price above the ${strategy.config.trend_ma}-day MA; `
      + `hold until a close below that MA. The backtested system holds ~${strategy.target_positions} names, 1% risk each, `
      + 'and fills at the next open. Your held names are dimmed.' }),
    listHost,
    signals.dropped.length ? h('details', { class: 'section' }, h('summary', { text: `Dropped off (${signals.dropped.length})` }),
      h('div', { class: 'chips section' }, signals.dropped.map((t) => h('a', { class: 'chip', href: `#/t/${t}`, text: t })))) : null,
  );
}
