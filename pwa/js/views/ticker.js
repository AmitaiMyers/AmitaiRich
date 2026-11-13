// Ticker page: today's v0 verdict (score_stock) and a candlestick chart with the 200-day MA
// (the v0 trend line: above it = can buy, a close below it = sell).

import { lineChart } from '../chart.js';
import { dayToIso, loadBars, sliceBars } from '../data.js';
import { sma } from '../engine/indicators.js';
import { buildStrategy } from '../engine/strategies.js';
import { exitMaPeriod, scoreStock } from '../holdings.js';
import { addPosition, heldTickers, makePosition } from '../positions.js';
import { h, kpi, num, pct, signClass } from '../ui.js';
import { valuationCard } from '../valuation.js';
import { companySection } from '../company.js';

const RANGES = { '3M': 92, '6M': 183, '1Y': 365, '3Y': 3 * 365, All: null };
const DEFAULT_RANGE = '6M';

export async function renderTicker(context, [symbol]) {
  const { manifest } = context;
  if (!symbol || !context.tickers.has(symbol)) {
    return h('div', { class: 'card empty' },
      h('p', { text: `${symbol || 'That ticker'} is not in the published universe.` }),
      h('p', { class: 'small', text: 'The app covers the S&P 500, Nasdaq-100, the watchlist and the Magic Formula list.' }));
  }
  const production = manifest.production;
  const strategy = buildStrategy(production.strategy, production.config);
  const bars = await loadBars(symbol);
  let verdict;
  try {
    verdict = scoreStock(bars, strategy);
  } catch (error) {
    return h('div', { class: 'card empty', text: `${symbol}: ${error.message}` });
  }

  const maPeriod = exitMaPeriod(strategy);
  const average = sma(bars.close, maPeriod);
  const held = heldTickers().has(symbol);

  const chartHost = h('div');
  const rangeButtons = Object.keys(RANGES).map((name) => h('button', { type: 'button', text: name,
    onclick: (event) => {
      for (const b of event.target.parentElement.children) b.classList.toggle('active', b === event.target);
      drawChart(name);
    } }));
  function drawChart(rangeName) {
    const lastDay = bars.dates[bars.dates.length - 1];
    const fromDay = RANGES[rangeName] === null ? null : lastDay - RANGES[rangeName];
    const view = sliceBars(bars, fromDay, null);
    const offset = bars.close.length - view.close.length;
    chartHost.replaceChildren(lineChart({
      candles: { name: symbol, days: view.dates, open: view.open, high: view.high, low: view.low, close: view.close },
      series: [
        { name: `${maPeriod}-day MA (trend line)`, days: view.dates, values: average.slice(offset), color: '--series-3', dash: [5, 4], width: 1.3 },
      ],
      log: rangeName === 'All', tall: true,
    }));
  }
  rangeButtons[Object.keys(RANGES).indexOf(DEFAULT_RANGE)].classList.add('active');
  drawChart(DEFAULT_RANGE);

  const addButton = h('button', { type: 'button', class: 'primary', text: held ? 'Already in positions' : `Add ${symbol} at ${num(verdict.close)}`,
    disabled: held, onclick: (event) => {
      addPosition(makePosition({ ticker: symbol, entryDate: dayToIso(verdict.date), entryPrice: verdict.close }, context.tickers));
      event.target.textContent = 'Added — see Positions';
      event.target.disabled = true;
    } });

  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', {}, `${symbol} `, h('span', { class: `badge ${verdict.isBuy ? 'buy' : ''}`, text: verdict.isBuy ? 'BUY' : 'NO BUY' })),
        h('div', { class: 'muted', text: `Close ${num(verdict.close)} on ${dayToIso(verdict.date)} · ${verdict.reason}` })),
      h('div', { class: 'row' }, addButton,
        h('a', { class: 'chip', href: `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}`, target: '_blank',
                 rel: 'noopener', text: 'Open in Yahoo Finance ↗' }))),
    h('div', { class: 'grid kpis' },
      kpi('6-month momentum', pct(verdict.momentum), `threshold ${Math.round(strategy.config.mom_threshold * 100)}%`, signClass(verdict.momentum)),
      kpi(`vs ${production.config.trend_ma ?? 200}-day MA`, pct(verdict.vsMa), verdict.vsMa > 0 ? 'uptrend' : 'below trend', signClass(verdict.vsMa))),
    h('div', { class: 'card section' },
      h('div', { class: 'row' }, h('h2', { text: 'Price and 200-day trend line' }), h('span', { class: 'spacer' }),
        h('div', { class: 'segmented' }, rangeButtons)),
      chartHost,
      h('p', { class: 'muted small', text: 'v0 buys while the price is above the dashed 200-day MA (with 6-month momentum above '
        + `${Math.round(strategy.config.mom_threshold * 100)}%) and sells on a close below it. Long ranges merge candles into weeks/months.` })),
    valuationCard(context.daily, symbol),
    await companySection(manifest, symbol),
  );
}
