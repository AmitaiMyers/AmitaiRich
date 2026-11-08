// The production-family strategies — a port of the matching classes in algorithms.py.
//
// Each strategy declares DEFAULTS (same keys/values as Python), warmup(config) and
// build(bars, config) returning the same Signals bundle the Python engine uses.
// Names are identical to the Python registry so configs and reports interoperate.

import { atr, heldForBars, priorMax, priorMin, roc, rollingMin, sma, volAdjustedMomentum } from './indicators.js';

const DEFAULT_SCORE_LOOKBACK = 126;

const boolArray = (n, predicate) => {
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = predicate(i) ? 1 : 0;
  return out;
};

/** The shared catastrophe stop: {recent swing low, entry - atr_mult * ATR}. */
const atrSwingStop = (bars, c) => ({
  stopLevels: [rollingMin(bars.low, c.swing_lookback)],
  stopAtr: atr(bars.high, bars.low, bars.close, c.atr_period),
  stopAtrMult: c.atr_mult,
});

const below = (close, average) => boolArray(close.length, (i) => close[i] < average[i]);

const signals = (fields) => ({
  stopLevels: [], stopAtr: null, stopAtrMult: 0, trailAtr: null, trailMult: 0, maxHold: null,
  ...fields,
});

const MOMENTUM_RIDER = {
  name: 'Momentum Rider (ROC + MA exit)',
  short: 'Momentum Rider',
  description: 'Buy when 6-month momentum clears the threshold and price is above its 200-day MA; sell when it closes back below the MA (production strategy).',
  DEFAULTS: { mom_lookback: 126, mom_threshold: 0.0, trend_ma: 200, max_ext: 9.99, exit_confirm: 1,
              atr_period: 14, atr_mult: 4.0, swing_lookback: 20 },
  warmup: (c) => Math.max(c.mom_lookback, c.trend_ma, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close } = bars;
    const momentum = roc(close, c.mom_lookback);
    const average = sma(close, c.trend_ma);
    return signals({
      entry: boolArray(close.length, (i) => momentum[i] > c.mom_threshold && close[i] > average[i]
        && close[i] <= (1.0 + c.max_ext) * average[i]),
      exit: heldForBars(below(close, average), c.exit_confirm),
      score: momentum,
      ...atrSwingStop(bars, c),
    });
  },
};

const VOL_ADJUSTED = {
  name: 'Vol-Adjusted Momentum Rider',
  short: 'Vol-Adj Momentum',
  description: 'Buy when momentum per unit of volatility (ROC / ATR%) clears the threshold in an uptrend; sell below the exit MA.',
  DEFAULTS: { mom_lookback: 126, atr_period: 20, trend_ma: 200, exit_ma: 200, score_threshold: 8.0,
              atr_mult: 4.0, swing_lookback: 20 },
  warmup: (c) => Math.max(c.mom_lookback, c.trend_ma, c.exit_ma, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close } = bars;
    const score = volAdjustedMomentum(bars, c.mom_lookback, c.atr_period);
    const trend = sma(close, c.trend_ma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > trend[i] && score[i] >= c.score_threshold),
      exit: below(close, sma(close, c.exit_ma)),
      score,
      ...atrSwingStop(bars, c),
    });
  },
};

const TREND_RIDER = {
  name: 'Trend Rider (breakout + MA exit)',
  short: 'Trend Rider',
  description: 'Buy a fresh N-bar-high breakout above the 200-day MA; sell below the exit MA.',
  DEFAULTS: { breakout_lookback: 100, trend_ma: 200, exit_ma: 100, atr_period: 14, atr_mult: 4.0,
              swing_lookback: 20 },
  warmup: (c) => Math.max(c.breakout_lookback, c.trend_ma, c.exit_ma, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close, high } = bars;
    const roof = priorMax(high, c.breakout_lookback);
    const trend = sma(close, c.trend_ma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > roof[i] && close[i] > trend[i]),
      exit: below(close, sma(close, c.exit_ma)),
      score: roc(close, DEFAULT_SCORE_LOOKBACK),
      ...atrSwingStop(bars, c),
    });
  },
};

const TWO_SPEED = {
  name: 'Two-Speed Donchian',
  short: 'Two-Speed Donchian',
  description: 'Fast channel breakout entry above the 200-day MA; slow channel-low exit.',
  DEFAULTS: { entry_lookback: 40, exit_lookback: 120, trend_ma: 200, atr_period: 20, atr_mult: 3.0,
              swing_lookback: 20 },
  warmup: (c) => Math.max(c.entry_lookback, c.exit_lookback, c.trend_ma, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close, high, low } = bars;
    const roof = priorMax(high, c.entry_lookback);
    const floor = priorMin(low, c.exit_lookback);
    const trend = sma(close, c.trend_ma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > roof[i] && close[i] > trend[i]),
      exit: boolArray(close.length, (i) => close[i] < floor[i]),
      score: roc(close, DEFAULT_SCORE_LOOKBACK),
      ...atrSwingStop(bars, c),
    });
  },
};

const DONCHIAN = {
  name: 'Trend Follower (Donchian)',
  short: 'Donchian',
  description: 'Turtle-style channel breakout (optional 200-day trend filter); exit on a channel low.',
  DEFAULTS: { entry_lookback: 50, exit_lookback: 20, trend_sma: 200, use_trend_filter: 1,
              atr_period: 14, atr_mult: 3.0, swing_lookback: 10 },
  warmup: (c) => Math.max(c.entry_lookback, c.trend_sma, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close, high, low } = bars;
    const roof = priorMax(high, c.entry_lookback);
    const floor = priorMin(low, c.exit_lookback);
    const trend = sma(close, c.trend_sma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > roof[i] && (!c.use_trend_filter || close[i] > trend[i])),
      exit: boolArray(close.length, (i) => close[i] < floor[i]),
      score: roc(close, DEFAULT_SCORE_LOOKBACK),
      ...atrSwingStop(bars, c),
    });
  },
};

const DUAL_CONFIRM = {
  name: 'Dual-Confirm Trend Hold',
  short: 'Dual-Confirm',
  description: '52-week-high breakout in an uptrend; exit only when a slow channel low AND the 200-day MA both break.',
  DEFAULTS: { entry_lookback: 252, trend_ma: 200, exit_lookback: 100, exit_ma: 200, atr_period: 20,
              atr_mult: 3.0, swing_lookback: 20 },
  warmup: (c) => Math.max(c.entry_lookback, c.trend_ma, c.exit_lookback, c.atr_period, c.swing_lookback) + 2,
  build(bars, c) {
    const { close, high, low } = bars;
    const roof = priorMax(high, c.entry_lookback);
    const floor = priorMin(low, c.exit_lookback);
    const trend = sma(close, c.trend_ma);
    const exitAverage = sma(close, c.exit_ma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > roof[i] && close[i] > trend[i]),
      exit: boolArray(close.length, (i) => close[i] < floor[i] && close[i] < exitAverage[i]),
      score: roc(close, DEFAULT_SCORE_LOOKBACK),
      ...atrSwingStop(bars, c),
    });
  },
};

const GROWTH_RIDER = {
  name: 'Growth Rider (momentum + chandelier)',
  short: 'Growth Rider',
  description: 'Momentum entry in an uptrend; exit on a chandelier trailing stop below the run-up high.',
  DEFAULTS: { mom_lookback: 126, mom_threshold: 0.30, trend_ma: 200, atr_period: 20, atr_mult: 4.0,
              swing_lookback: 20, trail_atr_period: 22, trail_atr_mult: 6.0 },
  warmup: (c) => Math.max(c.mom_lookback, c.trend_ma, c.atr_period, c.swing_lookback, c.trail_atr_period) + 2,
  build(bars, c) {
    const { close, high, low } = bars;
    const momentum = roc(close, c.mom_lookback);
    const trend = sma(close, c.trend_ma);
    return signals({
      entry: boolArray(close.length, (i) => close[i] > trend[i] && momentum[i] >= c.mom_threshold),
      exit: new Uint8Array(close.length),
      score: momentum,
      trailAtr: atr(high, low, close, c.trail_atr_period),
      trailMult: c.trail_atr_mult,
      ...atrSwingStop(bars, c),
    });
  },
};

const BUY_AND_HOLD = {
  name: 'Buy & Hold (benchmark)',
  short: 'Buy & Hold',
  description: 'Buy on the first bar and hold to the end (benchmark; no stop, so use all-in sizing).',
  DEFAULTS: {},
  warmup: () => 1,
  build: (bars) => signals({
    entry: new Uint8Array(bars.close.length).fill(1),
    exit: new Uint8Array(bars.close.length),
    score: roc(bars.close, DEFAULT_SCORE_LOOKBACK),
  }),
};

export const STRATEGIES = Object.fromEntries(
  [MOMENTUM_RIDER, VOL_ADJUSTED, TREND_RIDER, TWO_SPEED, DONCHIAN, DUAL_CONFIRM, GROWTH_RIDER, BUY_AND_HOLD]
    .map((s) => [s.name, s]),
);

/** A configured strategy instance (fails fast on unknown names / config keys). */
export function buildStrategy(name, overrides = {}) {
  if (!(name in STRATEGIES)) throw new Error(`Unknown strategy ${JSON.stringify(name)}`);
  const spec = STRATEGIES[name];
  const unknown = Object.keys(overrides).filter((k) => !(k in spec.DEFAULTS));
  if (unknown.length) throw new Error(`Unknown config keys ${unknown.join(', ')} for ${name}`);
  const config = { ...spec.DEFAULTS, ...overrides };
  if ('exit_confirm' in config && config.exit_confirm < 1) throw new Error('exit_confirm must be >= 1');
  const warmup = spec.warmup(config);
  return {
    name, config, warmup,
    signals(bars) {
      const built = spec.build(bars, config);
      built.entry.fill(0, 0, Math.max(warmup - 1, 0));
      return built;
    },
  };
}
