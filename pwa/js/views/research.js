// Research: the published reports from research_grids.py (run by the Research workflow).

import { loadResearch, loadResearchIndex } from '../data.js';
import { h, table } from '../ui.js';

const LABELS = {
  v3: 'Improvement study (v3)', baseline: 'Baseline re-check', train: 'Part I grid', refine: 'Part I refine',
  sweep: 'Portfolio sweep', growth: 'Growth grid', refine_growth: 'Growth refine', regime: 'Regime filter',
  squeeze: 'Squeeze combo', validate: 'Out-of-sample validation',
};
const COLUMN_LABELS = { cagr: 'CAGR %', maxDD: 'Max DD %', sharpe: 'Sharpe', calmar: 'Calmar', trades: 'Trades',
  avgHold: 'Avg hold', winRate: 'Win %', ddOK: 'DD ok', meanCagr: 'Mean CAGR %', minCagr: 'Min CAGR %',
  beatsProduction: 'Beats prod.', strategy: 'System' };

function reportTable(spec) {
  return h('div', { class: 'section' }, h('h2', { text: spec.title }),
    spec.note ? h('p', { class: 'muted small', text: spec.note }) : null,
    table(spec.columns.map((c) => ({
      label: COLUMN_LABELS[c] || c, num: c !== 'strategy',
      value: (r) => (c === 'ddOK' ? (r[c] === undefined ? '' : r[c] ? '✓' : '✗') : r[c] ?? ''),
      cls: (r) => (c === 'strategy' && String(r.strategy).startsWith('BENCH') ? 'muted' : ''),
    })), spec.rows));
}

export async function renderResearch(context, [phase]) {
  const index = await loadResearchIndex();
  const phases = Object.keys(index).sort((a, b) => index[b].localeCompare(index[a]));
  if (!phases.length) {
    return h('div', { class: 'card empty' },
      h('p', { text: 'No research reports published yet.' }),
      h('p', { class: 'small', text: 'Run the "Research" workflow in GitHub Actions (e.g. phase v3); its report appears here after the next publish.' }));
  }
  const selected = phase && index[phase] ? phase : phases[0];
  const report = await loadResearch(selected);
  const verdict = report.verdict;
  return h('div', {},
    h('div', { class: 'page-head' },
      h('div', {}, h('h1', { text: LABELS[selected] || selected }),
        h('div', { class: 'muted small', text: `Generated ${report.generated} · data ${report.data.start} → ${report.data.end} · objective: ${report.objective}` })),
      h('div', { class: 'chips' }, phases.map((p) => h('a', { class: 'chip', href: `#/research/${p}`,
        style: p === selected ? 'background:var(--accent-soft);color:var(--accent)' : null, text: LABELS[p] || p })))),
    verdict ? h('div', { class: `card verdict-box ${verdict.promoted.length ? 'good' : ''}` },
      h('h3', { text: 'Verdict' }), h('p', { text: verdict.summary }),
      h('p', { class: 'muted small', text: 'The workflow never changes production by itself: switching scan_today.py is a reviewed code change.' })) : null,
    report.tables.map(reportTable),
    h('p', { class: 'muted small section', text:
      'Caveats: the universe is today\'s index members (survivorship bias inflates every CAGR, the benchmarks\' most); '
      + 'results are hypothetical, before taxes, with 10 bps/side costs.' }),
  );
}
