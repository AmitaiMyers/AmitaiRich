// Ticker page: today's verdict + score (score_stock), price chart with the exit MA and
// the production strategy's historical trades on this stock.

import { lineChart } from '../chart.js';
import { dayToIso, loadBars, sliceBars } from '../data.js';
import { runEngine, metrics } from '../engine/engine.js';
import { sma } from '../engine/indicators.js';
import { buildStrategy } from '../engine/strategies.js';
import { exitMaPeriod, scoreStock } from '../holdings.js';
import { addPosition, heldTickers, makePosition } from '../positions.js';
import { h, kpi, num, pct, pctOf, signClass, table } from '../ui.js';

const RANGES = { '1Y': 365, '3Y': 3 * 365, '10Y': 3650, All: null };

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

  const run = runEngine({ [symbol]: bars }, strategy, strategy,
    { sizingMode: 'all_in', stopMode: production.stop_mode, fillMode: 'next_open' });
  const firstTradable = run.calendar[strategy.warmup];
  const startIdx = strategy.warmup;
  const stats = metrics(run.equity.slice(startIdx), run.trades);
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
    const markers = run.trades.flatMap((t) => [
      { day: t.entryDay, value: t.entryPrice, kind: 'buy' }, { day: t.exitDay, value: t.exitPrice, kind: 'sell' },
    ]).filter((m) => fromDay === null || m.day >= fromDay);
    chartHost.replaceChildren(lineChart({
      series: [
        { name: symbol, days: view.dates, values: view.close, color: '--series-1' },
        { name: `${maPeriod}-day MA (exit line)`, days: view.dates, values: average.slice(offset), color: '--series-3', dash: [5, 4], width: 1.3 },
      ],
      markers, log: rangeName === 'All' || rangeName === '10Y', tall: true,
    }));
  }
  rangeButtons[1].classList.add('active');
  drawChart('3Y');

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
      addButton),
    h('div', { class: 'grid kpis' },
      kpi('6-month momentum', pct(verdict.momentum), `threshold ${Math.round(strategy.config.mom_threshold * 100)}%`, signClass(verdict.momentum)),
      kpi(`vs ${production.config.trend_ma ?? 200}-day MA`, pct(verdict.vsMa), verdict.vsMa > 0 ? 'uptrend' : 'below trend', signClass(verdict.vsMa)),
      kpi('Strategy on this stock', pctOf(stats.cagr), `CAGR since ${dayToIso(firstTradable)}`, signClass(stats.cagr)),
      kpi('Trades', String(stats.trades), `win rate ${Math.round(stats.winRate * 100)}% · max DD ${pctOf(stats.maxDD, 0)}`)),
    h('div', { class: 'card section' },
      h('div', { class: 'row' }, h('h2', { text: 'Price, exit line and strategy trades' }), h('span', { class: 'spacer' }),
        h('div', { class: 'segmented' }, rangeButtons)),
      chartHost,
      h('p', { class: 'muted small', text: '▲ buy / ▼ sell: the production rules on this stock alone (all-in, next-open fills).' })),
    run.trades.length ? h('div', { class: 'section' }, h('h2', { text: 'Backtested trades on this stock' }), table([
      { label: 'Entry', value: (t) => dayToIso(t.entryDay) },
      { label: 'Exit', value: (t) => dayToIso(t.exitDay) },
      { label: 'Reason', value: (t) => t.exitReason },
      { label: 'Buy', value: (t) => num(t.entryPrice), num: true },
      { label: 'Sell', value: (t) => num(t.exitPrice), num: true },
      { label: 'Return', value: (t) => pctOf(t.ret), num: true, cls: (t) => signClass(t.ret) },
      { label: 'Bars', value: (t) => t.barsHeld, num: true },
    ], [...run.trades].reverse())) : null,
  );
}
