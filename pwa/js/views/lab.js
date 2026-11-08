// Lab: run your own backtests in the browser — one stock or a whole-list portfolio —
// with the same engine as the Python research (identical results, see pwa/tests).

import { lineChart } from '../chart.js';
import { dayToIso, isoToDay } from '../data.js';
import { STRATEGIES } from '../engine/strategies.js';
import { downloadText, h, kpi, money, num, pctOf, signClass, store, table } from '../ui.js';

const KEY = 'roof.lab.v1';
const CUSTOM = 'Custom list';
const SAME_EXIT = 'Same as buy strategy';

function defaults(manifest) {
  const production = manifest.production;
  return {
    mode: 'portfolio', ticker: 'AAPL', universe: Object.keys(manifest.lists)[1] || Object.keys(manifest.lists)[0],
    custom: 'AAPL, MSFT, NVDA, AMZN, GOOGL, META', buy: production.strategy,
    params: { ...STRATEGIES[production.strategy].DEFAULTS, ...production.config }, sell: SAME_EXIT,
    from: '2008-01-01', to: manifest.data_date, capital: 100000, maxPositions: production.target_positions,
    sizingMode: 'risk_based', riskPct: 1, costBps: 10, fillMode: 'next_open', stopMode: production.stop_mode,
  };
}

const field = (label, input) => h('label', { class: 'field' }, label, input);

export function renderLab(context) {
  const { manifest } = context;
  const saved = store.read(KEY, null);
  const form = saved && saved.buy in STRATEGIES ? { ...defaults(manifest), ...saved } : defaults(manifest);
  const results = h('div', { class: 'section' });
  const progress = h('div', { class: 'progress', hidden: true }, h('div'));
  const status = h('p', { class: 'small muted', role: 'status' });
  const paramsHost = h('div', { class: 'form-grid' });
  let worker = null;

  const input = (key, attrs = {}) => h('input', { value: form[key], ...attrs,
    oninput: (event) => { form[key] = attrs.type === 'number' ? Number(event.target.value) : event.target.value; } });
  const select = (key, options, onchange = null) => h('select', {
    onchange: (event) => { form[key] = event.target.value; if (onchange) onchange(); } },
  options.map(([value, label]) => h('option', { value, selected: value === form[key], text: label })));

  function drawParams() {
    const spec = STRATEGIES[form.buy];
    form.params = Object.fromEntries(Object.keys(spec.DEFAULTS).map((k) => [k, k in form.params ? form.params[k] : spec.DEFAULTS[k]]));
    paramsHost.replaceChildren(...Object.keys(spec.DEFAULTS).map((k) => field(k, h('input', {
      type: 'number', step: 'any', value: form.params[k],
      oninput: (event) => { form.params[k] = Number(event.target.value); } }))));
    if (!Object.keys(spec.DEFAULTS).length) paramsHost.append(h('p', { class: 'muted small', text: 'No parameters.' }));
  }

  const strategyOptions = Object.values(STRATEGIES).map((s) => [s.name, s.short]);
  const universeOptions = [...Object.entries(manifest.lists).map(([name, list]) => [name, `${name} (${list.length})`]), [CUSTOM, CUSTOM]];
  const singleOnly = h('div', { class: 'form-grid' }, field('Ticker', input('ticker', { list: 'ticker-list', autocapitalize: 'characters' })));
  const portfolioOnly = h('div', {},
    h('div', { class: 'form-grid' },
      field('Universe', select('universe', universeOptions)),
      field('Max positions', input('maxPositions', { type: 'number', min: 1, step: 1 }))),
    field('Custom list (comma-separated, used when Universe = Custom list)', h('textarea', {
      text: form.custom, oninput: (event) => { form.custom = event.target.value; } })));
  const showMode = () => { singleOnly.hidden = form.mode !== 'single'; portfolioOnly.hidden = form.mode !== 'portfolio'; };
  const modeButtons = ['portfolio', 'single'].map((mode) => h('button', { type: 'button',
    class: form.mode === mode ? 'active' : null, text: mode === 'single' ? 'Single stock' : 'Portfolio',
    onclick: (event) => {
      form.mode = mode;
      for (const b of event.target.parentElement.children) b.classList.toggle('active', b === event.target);
      showMode();
    } }));
  showMode();
  drawParams();

  function tickers() {
    if (form.mode === 'single') return [form.ticker.trim().toUpperCase().replace(/\./g, '-')];
    if (form.universe !== CUSTOM) return manifest.lists[form.universe];
    return [...new Set(form.custom.split(/[\s,]+/).map((t) => t.trim().toUpperCase().replace(/\./g, '-')).filter(Boolean))];
  }

  function run() {
    const symbols = tickers();
    const unknown = symbols.filter((t) => !context.tickers.has(t));
    if (!symbols.length || unknown.length) {
      status.className = 'small down';
      status.textContent = symbols.length ? `Not in the published universe: ${unknown.join(', ')}` : 'Choose at least one ticker.';
      return;
    }
    if (STRATEGIES[form.buy].DEFAULTS.atr_mult === undefined && form.sizingMode === 'risk_based') {
      status.className = 'small down';
      status.textContent = 'This strategy has no stop, so risk-based sizing is impossible — choose all-in or fixed-fraction.';
      return;
    }
    store.write(KEY, form);
    const request = {
      tickers: symbols,
      buy: { name: form.buy, config: form.params },
      sell: form.sell === SAME_EXIT ? null : { name: form.sell, config: {} },
      fromDay: isoToDay(form.from), toDay: isoToDay(form.to),
      options: { startingCapital: form.capital, maxPositions: form.mode === 'single' ? 1 : form.maxPositions,
                 sizingMode: form.sizingMode, riskPct: form.riskPct / 100, costBps: form.costBps,
                 fillMode: form.fillMode, stopMode: form.stopMode, skipUnprotectable: form.mode === 'portfolio' },
    };
    if (worker) worker.terminate();
    worker = new Worker(new URL('../lab-worker.js', import.meta.url), { type: 'module' });
    runButton.disabled = true;
    progress.hidden = false;
    status.className = 'small muted';
    status.textContent = `Loading ${symbols.length} price histories…`;
    worker.onerror = (event) => {
      runButton.disabled = false;
      progress.hidden = true;
      status.className = 'small down';
      status.textContent = `The backtest worker failed: ${event.message || 'could not start (see console)'}`;
    };
    worker.onmessage = ({ data }) => {
      if (data.type === 'progress') {
        progress.firstChild.style.width = `${(data.done / data.total) * 100}%`;
        status.textContent = `Loaded ${data.done}/${data.total} · then backtesting…`;
        return;
      }
      runButton.disabled = false;
      progress.hidden = true;
      worker.terminate();
      worker = null;
      if (data.type === 'error') {
        status.className = 'small down';
        status.textContent = data.message;
        return;
      }
      status.textContent = data.failed.length ? `Skipped (no data): ${data.failed.join(', ')}` : '';
      results.replaceChildren(renderResults(data, form));
    };
    worker.postMessage({ request });
  }

  const runButton = h('button', { class: 'primary', type: 'button', text: 'Run backtest', onclick: run });
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', { text: 'Backtest lab' }),
        h('div', { class: 'muted small', text: 'Runs in your browser with the same engine as the Python research.' })),
      h('div', { class: 'segmented' }, modeButtons)),
    h('div', { class: 'card' },
      singleOnly, portfolioOnly,
      h('div', { class: 'form-grid section' },
        field('Buy strategy', select('buy', strategyOptions, drawParams)),
        field('Exit strategy', select('sell', [[SAME_EXIT, SAME_EXIT], ...strategyOptions])),
        field('From', input('from', { type: 'date' })), field('To', input('to', { type: 'date', max: manifest.data_date })),
        field('Capital', input('capital', { type: 'number', min: 1000, step: 1000 })),
        field('Sizing', select('sizingMode', [['risk_based', 'Risk-based'], ['all_in', 'All-in'], ['fixed_fraction', 'Fixed fraction']])),
        field('Risk per trade %', input('riskPct', { type: 'number', min: 0.1, step: 0.1 })),
        field('Cost (bps/side)', input('costBps', { type: 'number', min: 0, step: 1 })),
        field('Fill', select('fillMode', [['next_open', 'Next open (realistic)'], ['close', 'Signal close']])),
        field('Stop', select('stopMode', [['widest', 'Widest'], ['tightest', 'Tightest']]))),
      h('details', { class: 'section' }, h('summary', { text: 'Strategy parameters' }), h('div', { class: 'section' }, paramsHost)),
      h('div', { class: 'row section' }, runButton,
        h('button', { type: 'button', text: 'Reset to production', onclick: () => {
          store.write(KEY, null);
          document.getElementById('view').replaceChildren(renderLab(context));
        } }),
        h('span', { class: 'spacer' })),
      progress, status),
    results);
}

function renderResults(data, form) {
  const { strategy, equalWeight, spy } = data.stats;
  const row = (name, s) => ({ name, ...s });
  const comparison = [row('Strategy', strategy), row('Equal-weight buy & hold', equalWeight), row('SPY buy & hold', spy)];
  const trades = [...data.trades].reverse();
  const tradeCsv = () => ['ticker,entry_date,entry_price,exit_date,exit_price,reason,shares,return',
    ...data.trades.map((t) => [t.ticker, dayToIso(t.entryDay), t.entryPrice, dayToIso(t.exitDay), t.exitPrice,
      t.exitReason, t.shares, t.ret.toFixed(6)].join(','))].join('\n');

  return h('div', {},
    h('div', { class: 'grid kpis' },
      kpi('CAGR', pctOf(strategy.cagr), `SPY ${pctOf(spy.cagr)}`, signClass(strategy.cagr)),
      kpi('Max drawdown', pctOf(strategy.maxDD), `SPY ${pctOf(spy.maxDD)}`, 'down'),
      kpi('Sharpe', num(strategy.sharpe), `Calmar ${num(strategy.calmar)}`),
      kpi('Final equity', money(strategy.finalEquity), `from ${money(form.capital)}`),
      kpi('Trades', String(strategy.trades), `win ${Math.round(strategy.winRate * 100)}% · avg ${Math.round(strategy.avgHold)} bars`)),
    h('div', { class: 'card section' }, h('h2', { text: `Equity (log scale) · ${data.nTickers} stocks` }),
      lineChart({
        series: [
          { name: 'Strategy', days: data.calendar, values: data.equity, color: '--series-1', width: 2 },
          { name: 'Equal-weight B&H', days: data.calendar, values: data.equalWeight, color: '--series-2' },
          { name: 'SPY B&H', days: data.calendar, values: data.spy, color: '--series-3' },
        ],
        log: true, format: (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : `${Math.round(v / 1000)}k`), tall: true,
      })),
    h('div', { class: 'section' }, table([
      { label: '', value: (r) => h('strong', { text: r.name }) },
      { label: 'CAGR', value: (r) => pctOf(r.cagr), num: true, cls: (r) => signClass(r.cagr) },
      { label: 'Max DD', value: (r) => pctOf(r.maxDD), num: true },
      { label: 'Sharpe', value: (r) => num(r.sharpe), num: true },
      { label: 'Calmar', value: (r) => num(r.calmar), num: true },
      { label: 'Total return', value: (r) => pctOf(r.totalReturn, 0), num: true },
    ], comparison)),
    trades.length ? h('div', { class: 'section' },
      h('div', { class: 'row' }, h('h2', { text: `Trades (${trades.length})` }), h('span', { class: 'spacer' }),
        h('button', { type: 'button', text: 'Download CSV', onclick: () => downloadText('lab-trades.csv', tradeCsv()) })),
      table([
        { label: 'Ticker', value: (t) => h('a', { href: `#/t/${t.ticker}`, text: t.ticker }) },
        { label: 'Entry', value: (t) => dayToIso(t.entryDay) },
        { label: 'Exit', value: (t) => dayToIso(t.exitDay) },
        { label: 'Reason', value: (t) => t.exitReason },
        { label: 'Return', value: (t) => pctOf(t.ret), num: true, cls: (t) => signClass(t.ret) },
        { label: 'P&L', value: (t) => money(t.pnl), num: true, cls: (t) => signClass(t.pnl) },
        { label: 'Bars', value: (t) => t.barsHeld, num: true },
      ], trades.slice(0, 300))) : h('div', { class: 'card empty', text: 'No trades in this window.' }),
  );
}
