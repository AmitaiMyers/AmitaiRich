// "Why is it moving?" sentences (pwa/js/company.js). Run: node --test pwa/tests/

import assert from 'node:assert/strict';
import test from 'node:test';

import { moveSentences } from '../js/company.js';

const MU = {   // real values for MU on 2026-11-11 (stock_moves.py output)
  as_of: '2026-11-11', stock: { '1w': 2.0, '1m': -14.9, '3m': -14.6 }, market: { '1w': -0.9, '1m': -2.3, '3m': -2.1 },
  peers: { '1w': 5.6, '1m': -4.0, '3m': -18.6 }, peer_group: 'Semiconductors', peer_count: 23, from_high_pct: -33.1,
  earnings: [{ date: '2026-10-01', surprise_pct: 5.0, reaction_pct: -1.7 },
             { date: '2026-06-25', surprise_pct: 21.4, reaction_pct: 8.2 },
             { date: '2026-03-19', surprise_pct: 33.2, reaction_pct: -11.8 }],
};

test('MU: a company-specific fall, far from the high, shrinking earnings beats', () => {
  const s = moveSentences('MU', MU);
  assert.equal(s[0], 'MU fell 14.9% in the last month, while the S&P 500 fell 2.3% and Semiconductors stocks fell 4.0% (median of 23).');
  assert.match(s[1], /^It did 11 points worse than its industry/);
  assert.equal(s[2], 'It is 33% below its 52-week high.');
  assert.match(s[3], /beat the analysts' estimate by 5%, a smaller beat than before \(21%, 33%\)/);
  assert.match(s[3], /moved -1\.7% vs the market right after the report\.$/);
});

test('a move in line with the industry, near the high, no peers or earnings', () => {
  const inLine = { ...MU, stock: { ...MU.stock, '1m': -5.0 }, from_high_pct: -6 };
  assert.match(moveSentences('X', inLine)[1], /in line with its industry/);
  assert.equal(moveSentences('X', inLine).some((t) => t.includes('52-week high')), false);
  const alone = { ...MU, peers: null, peer_group: null, peer_count: null, earnings: [] };
  const s = moveSentences('Y', alone);
  assert.equal(s[0], 'Y fell 14.9% in the last month, while the S&P 500 fell 2.3%.');
  assert.equal(s.length, 2);
});

test('a miss is called a miss; a growing beat gets no "smaller beat" remark', () => {
  const miss = { ...MU, earnings: [{ date: '2026-10-01', surprise_pct: -8, reaction_pct: null }] };
  assert.match(moveSentences('Z', miss).at(-1), /missed the analysts' estimate by 8%\.$/);
  const growing = { ...MU, earnings: [{ date: 'd', surprise_pct: 40, reaction_pct: 3 }, { date: 'e', surprise_pct: 10, reaction_pct: 1 }] };
  assert.equal(moveSentences('Z', growing).at(-1).includes('smaller beat'), false);
});

test('too little history', () => {
  assert.deepEqual(moveSentences('NEW', { ...MU, stock: { '1w': null, '1m': null, '3m': null } }),
    ['Not enough price history yet to explain recent moves.']);
});
