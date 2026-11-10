// Today: what is new on the v0 and v7 lists, both lists, the paper scoreboard and notifications.
// Source: data/daily.json (the Paper trading job's signal-log record). Before that job has run,
// v0 falls back to signals.json (published by every build) and v7 says it is not available yet.

import { heldTickers } from '../positions.js';
import { notificationsCard } from '../push.js';
import { h, kpi, money, num, pct, signClass, store, table } from '../ui.js';

const V0_COUNTS = [20, 40, 'all'];   // 'all' = every stock that passes v0's rules
const countLabel = (n) => (n === 'all' ? 'All' : `Top ${n}`);
const rowsShown = (n, list) => (n === 'all' ? list.length : Math.min(n, list.length));
const V0_COUNT_KEY = 'roof.v0count.v1';
const NEW_CHIPS_SHOWN = 24;

const tickerLink = (ticker) => h('a', { class: 'chip', href: `#/t/${encodeURIComponent(ticker)}`, text: ticker });
const heldBadge = (held) => (r) => (held.has(r.ticker) ? h('span', { class: 'badge', text: 'HELD' }) : '');
const openTicker = (r) => { location.hash = `#/t/${encodeURIComponent(r.ticker)}`; };

/** v0 rows + new names, from daily.json when available, else from this build's signals.json. */
function v0Source(daily, signals) {
  if (daily.available) return { date: daily.date, list: daily.v0.list, new: daily.v0.new };
  const list = signals.candidates.map((r) => ({ rank: r.rank, ticker: r.ticker, close: r.close,
                                                mom_pct: r['mom_%'], vs_ma200_pct: r.pct_vs_200ma }));
  return { date: signals.date, list, new: signals.new_today };
}

function chipRow(names) {
  return h('div', { class: 'chips', style: 'margin-top:6px' }, names.slice(0, NEW_CHIPS_SHOWN).map(tickerLink),
    names.length > NEW_CHIPS_SHOWN ? h('span', { class: 'chip muted', text: `+${names.length - NEW_CHIPS_SHOWN} more` }) : null);
}

/** Names that left a list since the previous logged day, each with its reason (older logs have none). */
function droppedBlock(entry) {
  if (!('dropped' in entry) || !entry.dropped.length) return null;
  return h('details', { style: 'margin-top:6px' }, h('summary', { text: `${entry.dropped.length} left the list` }),
    h('ul', { class: 'small' }, entry.dropped.map((d) => h('li', {}, h('strong', { text: d.ticker }), ` — ${d.reason}`))));
}

function newTodayCard(v0, daily) {
  const line = (label, entry) => h('div', { class: 'section' }, h('strong', { text: `${label} · ${entry.new.length} new` }),
    entry.new.length ? chipRow(entry.new) : h('div', { class: 'muted small', text: 'No new names today.' }),
    droppedBlock(entry));
  return h('div', { class: 'card' }, h('h2', { text: 'New today' }),
    line('v0 momentum', daily.available ? daily.v0 : v0),
    daily.available ? line('v7 earnings', daily.v7) : h('div', { class: 'section muted small', text: `v7: ${daily.reason}.` }));
}

function v0Rows(v0, held, count) {
  return table([
    { label: '#', value: (r) => r.rank, num: true },
    { label: 'Ticker', value: (r) => h('strong', { text: r.ticker }) },
    { label: 'Close', value: (r) => num(r.close), num: true },
    { label: '6-mo momentum', value: (r) => pct(r.mom_pct), num: true, cls: (r) => signClass(r.mom_pct) },
    { label: 'vs 200-MA', value: (r) => pct(r.vs_ma200_pct), num: true },
    { label: '', value: heldBadge(held) },
  ], v0.list.slice(0, rowsShown(count, v0.list)), { onRow: openTicker, rowClass: (r) => (held.has(r.ticker) ? 'held' : '') });
}

function v0Table(v0, held) {
  let count = store.read(V0_COUNT_KEY, V0_COUNTS[0]);
  const title = h('h2');
  const host = h('div');
  const draw = () => {
    title.textContent = rowsShown(count, v0.list) === v0.list.length
      ? `v0 — momentum rider (production) · all ${v0.list.length} that pass`
      : `v0 — momentum rider (production) · top ${count} of ${v0.list.length}`;
    host.replaceChildren(v0Rows(v0, held, count));
  };
  const picker = h('div', { class: 'segmented', role: 'group', 'aria-label': 'How many v0 stocks to show' },
    V0_COUNTS.map((n) => h('button', {
      type: 'button', class: n === count ? 'active' : null, text: countLabel(n),
      onclick: (event) => {
        count = n;
        store.write(V0_COUNT_KEY, n);
        for (const b of event.target.parentElement.children) b.classList.toggle('active', b === event.target);
        draw();
      },
    })));
  draw();
  return h('div', { class: 'section' },
    h('div', { class: 'row' }, title, h('span', { class: 'spacer' }), picker),
    h('p', { class: 'muted small', text: 'Strong 6-month momentum and price above the 200-day MA; '
      + 'sell on a close below the MA or the stop. Strongest first.' }),
    host);
}

function v7Table(daily, held) {
  if (!daily.available) return null;
  return h('div', { class: 'section' },
    h('h2', { text: `v7 — earnings-led · ${daily.v7.list.length} names` }),
    h('p', { class: 'muted small', text: 'Ranked on beat streak, earnings surprise (SUE) and revenue acceleration; '
      + 'rebalanced weekly. Research only: it beat SPY before 2023 but lagged it on the 2023+ holdout.' }),
    table([
      { label: '#', value: (r) => r.rank, num: true },
      { label: 'Ticker', value: (r) => h('strong', { text: r.ticker }) },
      { label: 'Close', value: (r) => num(r.close), num: true },
      { label: 'Beat streak', value: (r) => num(r.beat_streak, 0), num: true },
      { label: 'EPS surprise', value: (r) => pct(r.eps_surprise), num: true, cls: (r) => signClass(r.eps_surprise) },
      { label: 'Buyable', value: (r) => (r.buyable_today ? 'yes' : 'no') },
      { label: '', value: heldBadge(held) },
    ], daily.v7.list, { onRow: openTicker, rowClass: (r) => (held.has(r.ticker) ? 'held' : '') }));
}

function paperCard(daily) {
  if (!daily.available) return null;
  const { accounts, orders, status } = daily.paper;
  const ordersLine = Object.entries(orders).map(([name, list]) =>
    h('div', { class: 'small' }, h('strong', { text: `${name} next open: ` }), list.length ? list.join(', ') : 'none'));
  return h('details', { class: 'card section' }, h('summary', { text: 'Paper-trading scoreboard (v0, v0m, v7 vs SPY)' }),
    h('p', { class: 'muted small', text: status }),
    accounts.length ? table([
      { label: 'Account', value: (r) => r.strategy },
      { label: 'Value', value: (r) => money(r.value), num: true },
      { label: 'Return', value: (r) => pct(r.return, 2), num: true, cls: (r) => signClass(r.return) },
      { label: 'Max DD', value: (r) => pct(-r.maxDD), num: true },
      { label: 'Trades', value: (r) => r.trades, num: true },
    ], accounts) : null,
    ordersLine);
}

export function renderToday({ signals, daily }) {
  const held = heldTickers();
  const m = signals.market;
  const v0 = v0Source(daily, signals);
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', { text: `Signals for ${v0.date}` }),
        h('div', { class: 'muted', text: 'Act at the next open. Tap a ticker for its chart.' })),
      h('a', { href: '#/positions', class: 'chip', text: `${held.size} held → HOLD/SELL status` })),
    h('div', { class: 'grid kpis' },
      kpi('Market (SPY)', m.risk_on ? 'Risk-on' : 'Risk-off', `${pct(m['spy_vs_ma200_%'])} vs 200-day MA`, m.risk_on ? 'up' : 'down'),
      kpi('Breadth', m['breadth_above_ma200_%'] === null ? '—' : `${m['breadth_above_ma200_%']}%`,
        `of ${m.breadth_universe} stocks above their 200-MA`)),
    h('div', { class: 'section' }, newTodayCard(v0, daily)),
    v0Table(v0, held),
    v7Table(daily, held),
    paperCard(daily),
    notificationsCard(),
  );
}
