// Backtest worker: loads price files and runs the engine off the main thread, so a
// 500-stock portfolio backtest never freezes the UI. Protocol:
//   in:  {request: {tickers, buy:{name,config}, sell:{name,config}|null, options, fromDay, toDay}}
//   out: {type:'progress', done, total} | {type:'result', ...} | {type:'error', message}

import { loadBars, loadManyBars, setDataBase, sliceBars } from './data.js';
import { buyAndHold, metrics, runEngine } from './engine/engine.js';
import { buildStrategy } from './engine/strategies.js';

setDataBase('../');   // this file lives in js/, the data in ../data/

/** A strategy that cannot ENTER before `fromDay` (indicators still warm up on earlier bars). */
function tradingFrom(strategy, fromDay) {
  return {
    ...strategy,
    signals(bars) {
      const built = strategy.signals(bars);
      for (let i = 0; i < bars.dates.length && bars.dates[i] < fromDay; i++) built.entry[i] = 0;
      return built;
    },
  };
}

function firstIndexFrom(calendar, day) {
  let i = 0;
  while (i < calendar.length && calendar[i] < day) i++;
  return i;
}

async function run(request) {
  const { frames: loaded, failed } = await loadManyBars(request.tickers,
    (done, total) => postMessage({ type: 'progress', done, total }));
  const frames = {};
  for (const [ticker, bars] of Object.entries(loaded)) {
    const cut = sliceBars(bars, null, request.toDay);
    if (cut.close.length && cut.dates[cut.dates.length - 1] >= request.fromDay) frames[ticker] = cut;
  }
  if (!Object.keys(frames).length) throw new Error('None of the selected tickers has data in that date range.');

  const buyBase = buildStrategy(request.buy.name, request.buy.config);
  const buy = tradingFrom(buyBase, request.fromDay);
  const sell = request.sell ? buildStrategy(request.sell.name, request.sell.config) : buy;
  const result = runEngine(frames, buy, sell, request.options);

  const start = firstIndexFrom(result.calendar, request.fromDay);
  const calendar = result.calendar.slice(start);
  const equity = result.equity.slice(start);
  const capital = request.options.startingCapital;
  const fromWindow = Object.fromEntries(Object.entries(frames)
    .map(([t, b]) => [t, sliceBars(b, request.fromDay, null)]).filter(([, b]) => b.close.length));
  const equalWeight = buyAndHold(fromWindow, calendar, capital, request.options.costBps);
  const spyBars = sliceBars(await loadBars('SPY'), request.fromDay, request.toDay);
  const spy = buyAndHold({ SPY: spyBars }, calendar, capital, request.options.costBps);

  return {
    type: 'result', calendar, equity, equalWeight, spy, failed,
    nTickers: Object.keys(frames).length,
    trades: result.trades,
    stats: { strategy: metrics(equity, result.trades), equalWeight: metrics(equalWeight), spy: metrics(spy) },
  };
}

self.onmessage = async ({ data }) => {
  try {
    postMessage(await run(data.request));
  } catch (error) {
    postMessage({ type: 'error', message: error.message });
  }
};
