// "Is it overpriced right now?" — the valuation facts published in daily.json (magic.valuation),
// computed by magic_formula.valuation_check. Shared by the Today lists and the stock page.

import { h, kpi, num, pct } from './ui.js';

const LABELS = {
  cheap: { text: 'Cheap', cls: 'buy' },
  fair: { text: 'Fair', cls: '' },
  expensive: { text: 'Expensive', cls: 'sell' },
  'no profits': { text: 'No profits', cls: 'warn' },
};

/** The valuation facts of one ticker, or null (old record, or no fundamentals for it yet). */
export function valuationOf(daily, ticker) {
  if (!daily.available || !('magic' in daily) || !('valuation' in daily.magic)) return null;
  return ticker in daily.magic.valuation ? daily.magic.valuation[ticker] : null;
}

export function valuationBadge(facts) {
  if (facts === null || facts.label === null) return '—';
  const label = LABELS[facts.label];
  return h('span', { class: `badge ${label.cls}`, text: label.text });
}

const shown = (value, format) => (value === null ? '—' : format(value));

/** The stock page card: the label plus the numbers behind it. */
export function valuationCard(daily, ticker) {
  const facts = valuationOf(daily, ticker);
  if (facts === null) {
    return h('div', { class: 'card section' }, h('h2', { text: 'Is it overpriced?' }),
      h('p', { class: 'muted small', text: 'No valuation data for this stock yet (fundamentals refresh weekly).' }));
  }
  return h('div', { class: 'card section' },
    h('div', { class: 'row' }, h('h2', { text: 'Is it overpriced?' }), h('span', { class: 'spacer' }), valuationBadge(facts)),
    h('div', { class: 'grid kpis' },
      kpi('Earnings yield', shown(facts.ey_pct, (v) => `${num(v, 1)}%`), 'operating profit / price of the whole business'),
      kpi('Forward P/E', shown(facts.forward_pe, (v) => num(v, 1)), 'price / next year\'s expected earnings'),
      kpi('PEG', shown(facts.peg, (v) => num(v, 2)), 'P/E divided by growth; under ~1.5 is reasonable'),
      kpi('Price / sales', shown(facts.price_to_sales, (v) => num(v, 1)), 'useful when there are no profits'),
      kpi('Analyst target', shown(facts.target_upside_pct, (v) => pct(v, 0)), 'average target vs today\'s price')),
    h('p', { class: 'muted small', text: 'The label compares this stock\'s earnings yield with the other stocks in the app: '
      + 'the highest third is Cheap, the lowest third Expensive. It is a snapshot from Yahoo, refreshed weekly, '
      + `as of ${daily.magic.as_of}. Not labelled for banks and insurers.` }));
}
