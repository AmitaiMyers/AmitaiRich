// On-device position checks — a port of scan_today.holding_verdict + score_stock.
// Positions never leave the browser; verdicts are computed from published prices.

import { exitHit, stopPriceAt } from './engine/engine.js';
import { roc, sma } from './engine/indicators.js';

const round = (x, digits) => Math.round(x * 10 ** digits) / 10 ** digits;
const last = (arr) => arr[arr.length - 1];

/** The moving average the strategy exits on (exit_ma, else trend_ma, else null). */
export function exitMaPeriod(strategy) {
  if ('exit_ma' in strategy.config) return strategy.config.exit_ma;
  if ('trend_ma' in strategy.config) return strategy.config.trend_ma;
  return null;
}

/** First bar on/after `entryDay` (pandas searchsorted). */
function searchSorted(dates, day) {
  let lo = 0, hi = dates.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (dates[mid] < day) lo = mid + 1; else hi = mid; }
  return lo;
}

/**
 * HOLD/SELL for a position on the latest bar of `bars`.
 * entryPrice null = the entry bar's close. Throws (like Python) when the entry date is
 * after the last bar or there is not enough history before entry.
 */
export function holdingVerdict(bars, strategy, entryDay, entryPrice, stopMode) {
  const n = bars.close.length;
  const entryIndex = searchSorted(bars.dates, entryDay);
  if (entryIndex >= n) throw new Error('Entry date is after the last available bar.');
  if (entryIndex + 1 < strategy.warmup) {
    throw new Error(`Only ${entryIndex + 1} bars before entry; the strategy needs ${strategy.warmup}.`);
  }
  const signals = strategy.signals(bars);
  const fill = entryPrice === null ? bars.close[entryIndex] : entryPrice;
  const stop = stopPriceAt(signals, entryIndex, fill, stopMode);
  const barsHeld = n - 1 - entryIndex;
  const lastClose = last(bars.close);
  const stopHit = stop !== null && last(bars.low) <= stop;
  let highestHigh = -Infinity;
  for (let i = entryIndex; i < n; i++) highestHigh = Math.max(highestHigh, bars.high[i]);
  const sellSignal = exitHit(signals, n - 1, lastClose, highestHigh, barsHeld);

  let verdict = 'HOLD', reason = 'trend intact';
  if (stopHit) [verdict, reason] = ['SELL', 'stop hit'];
  else if (sellSignal) [verdict, reason] = ['SELL', 'exit signal'];

  const exitMa = exitMaPeriod(strategy);
  let exitLevel = null, toExit = null;
  if (exitMa !== null && n >= exitMa) {
    const level = last(sma(bars.close, exitMa));
    exitLevel = level;
    toExit = (lastClose / level - 1) * 100;
  }
  const recent = last(roc(bars.close, 21));
  const mom1m = Number.isNaN(recent) ? null : recent * 100;
  const trend = mom1m === null ? 'flat' : mom1m < -1 ? 'down' : mom1m > 1 ? 'up' : 'flat';
  return {
    verdict, reason, trend, mom1m, entryPrice: fill, lastClose,
    openPnl: (lastClose / fill - 1) * 100, exitLevel, toExit, stopPrice: stop, barsHeld,
    entryIndex,
  };
}

/** score_stock: today's BUY verdict, ranking score and reason (from the strategy's thresholds). */
export function scoreStock(bars, strategy) {
  const n = bars.close.length;
  if (n < strategy.warmup + 1) throw new Error(`Only ${n} bars; the strategy needs ${strategy.warmup + 1}.`);
  const signals = strategy.signals(bars);
  const c = strategy.config;
  const momLookback = c.mom_lookback ?? 126;
  const trendMa = c.trend_ma ?? 200;
  const momentum = last(roc(bars.close, momLookback)) * 100;
  const vsMa = (last(bars.close) / last(sma(bars.close, trendMa)) - 1) * 100;
  const isBuy = Boolean(signals.entry[n - 1]);
  let reason = 'entry conditions not met';
  if (isBuy) reason = 'entry conditions met';
  else if (!(vsMa > 0)) reason = 'below its long moving average (no uptrend)';
  else if ('mom_threshold' in c && momentum <= c.mom_threshold * 100) {
    reason = `momentum ${round(momentum, 1)}% ≤ threshold ${round(c.mom_threshold * 100, 0)}%`;
  } else if ('max_ext' in c && vsMa > c.max_ext * 100) reason = 'overextended above its moving average';
  return { isBuy, reason, score: last(signals.score), momentum, vsMa, close: last(bars.close),
           date: last(bars.dates) };
}
