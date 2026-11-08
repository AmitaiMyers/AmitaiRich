// Python <-> JS parity: the browser engine must reproduce the Python engine exactly.
// Fixture: python -m tests.make_js_fixtures      Run: node --test pwa/tests/

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { decodeBars } from '../js/data.js';
import { buyAndHold, metrics, pyFloorDiv, runEngine } from '../js/engine/engine.js';
import { rollingMean } from '../js/engine/indicators.js';
import { buildStrategy, STRATEGIES } from '../js/engine/strategies.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/parity.json', import.meta.url)));
const bars = Object.fromEntries(Object.entries(fixture.bars).map(([t, e]) => [t, decodeBars(e)]));
const indices = (flags) => [...flags].flatMap((v, i) => (v ? [i] : []));
const nullable = (arr) => Array.from(arr, (x) => (Number.isNaN(x) ? null : x));

test('every fixture strategy exists in the JS registry', () => {
  for (const s of fixture.signals) assert.ok(s.strategy in STRATEGIES, s.strategy);
});

for (const expected of fixture.signals) {
  test(`signals: ${expected.strategy} ${JSON.stringify(expected.config)}`, () => {
    const signals = buildStrategy(expected.strategy, expected.config).signals(bars[expected.ticker]);
    assert.deepEqual(indices(signals.entry), expected.entry, 'entry bars');
    assert.deepEqual(indices(signals.exit), expected.exit, 'exit bars');
    assert.deepEqual(nullable(signals.score), expected.score, 'score');
    assert.deepEqual(signals.stopLevels.map(nullable), expected.stopLevels, 'stop levels');
  });
}

for (const [n, run] of fixture.runs.entries()) {
  const label = `${run.strategy} ${JSON.stringify(run.config)} ${run.options.fillMode} x${run.tickers.length}`;
  test(`backtest #${n}: ${label}`, () => {
    const strategy = buildStrategy(run.strategy, run.config);
    const frames = Object.fromEntries(run.tickers.map((t) => [t, bars[t]]));
    const result = runEngine(frames, strategy, strategy, run.options);
    const trades = result.trades.map((t) => ({
      ticker: t.ticker, entryDay: t.entryDay, entryPrice: t.entryPrice, stopPrice: t.stopPrice,
      shares: t.shares, exitDay: t.exitDay, exitPrice: t.exitPrice, exitReason: t.exitReason,
      barsHeld: t.barsHeld,
    }));
    assert.deepEqual(trades, run.trades);
    for (const [day, value] of Object.entries(run.equitySample)) {
      assert.equal(result.equity[Number(day)], value, `equity on calendar day #${day}`);
    }
    assert.equal(result.nEntrySignals, run.nEntrySignals);
  });
}

test('rolling mean handles constant runs and warmup like pandas', () => {
  const out = rollingMean([1, 2, 2, 2, 5], 3);
  assert.ok(Number.isNaN(out[0]) && Number.isNaN(out[1]));
  assert.deepEqual(Array.from(out.slice(2)), [5 / 3, 2, 3]);
});

test('python floor division semantics', () => {
  assert.equal(pyFloorDiv(7, 2), 3);
  assert.equal(pyFloorDiv(0.3, 0.1), 2);
  assert.equal(pyFloorDiv(1e6, 3.7), 270270);
});

test('buy & hold keeps a sleeve in cash until the stock lists', () => {
  const a = { dates: Int32Array.from([0, 1, 2]), close: Float64Array.from([10, 11, 12]) };
  const b = { dates: Int32Array.from([1, 2]), close: Float64Array.from([20, 10]) };
  const equity = buyAndHold({ A: a, B: b }, Int32Array.from([0, 1, 2]), 100);
  assert.deepEqual(Array.from(equity), [100, 105, 90]);
});

test('metrics on a simple curve', () => {
  const m = metrics([100, 120, 90, 135]);
  assert.equal(m.maxDD, 90 / 120 - 1);
  assert.ok(Math.abs(m.totalReturn - 0.35) < 1e-12);
});

test('unknown config keys fail fast', () => {
  assert.throws(() => buildStrategy('Momentum Rider (ROC + MA exit)', { nope: 1 }), /Unknown config keys/);
});
