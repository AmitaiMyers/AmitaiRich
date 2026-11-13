// Stock page: why it is moving (vs the market and its industry, earnings), recent headlines and what
// the company does, from data/company/<T>.json
// (published by publish.py from the daily job's caches; manifest.company lists the tickers that have one).

import { loadCompany } from './data.js';
import { h, num } from './ui.js';

const SUMMARY_PREVIEW = 360;

function ago(iso) {
  const days = Math.floor((Date.now() - Date.parse(iso)) / 86400000);
  if (days < 1) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

// ---------------------------------------------------------------------------
// "Why is it moving?" — sentences built from the move facts (stock_moves.py). Pure, so tested in Node.
// ---------------------------------------------------------------------------

const IN_LINE_POINTS = 3;     // within this many points of its industry = "moved with the industry"
const DEEP_FROM_HIGH = -20;   // at least this far below the 52-week high is worth saying

const signed = (x) => `${x > 0 ? '+' : ''}${x.toFixed(1)}%`;
const verb = (x) => (x >= 0 ? 'rose' : 'fell');

/** The explanation of a stock's last-month move, as a list of plain sentences. */
export function moveSentences(ticker, move) {
  const sentences = [];
  const stock = move.stock['1m'];
  const market = move.market['1m'];
  if (stock === null) return ['Not enough price history yet to explain recent moves.'];
  const peer = move.peers === null ? null : move.peers['1m'];
  sentences.push(`${ticker} ${verb(stock)} ${Math.abs(stock).toFixed(1)}% in the last month, while the S&P 500 `
    + `${market === null ? 'has no data' : `${verb(market)} ${Math.abs(market).toFixed(1)}%`}`
    + (peer === null ? '.' : ` and ${move.peer_group} stocks ${verb(peer)} ${Math.abs(peer).toFixed(1)}% (median of ${move.peer_count}).`));
  if (peer !== null) {
    const own = stock - peer;
    if (Math.abs(own) < IN_LINE_POINTS) {
      sentences.push(`It moved in line with its industry, so the move is mostly industry-wide, not about ${ticker} itself.`);
    } else if (own < 0) {
      sentences.push(`It did ${Math.abs(own).toFixed(0)} points worse than its industry, so most of the fall is specific to `
        + `${ticker}: look for company news or an earnings reaction.`);
    } else {
      sentences.push(`It did ${own.toFixed(0)} points better than its industry, so the strength is specific to ${ticker}.`);
    }
  }
  if (move.from_high_pct !== null && move.from_high_pct <= DEEP_FROM_HIGH) {
    sentences.push(`It is ${Math.abs(move.from_high_pct).toFixed(0)}% below its 52-week high.`);
  }
  if (move.earnings.length) {
    const [last, ...before] = move.earnings;
    if (last.surprise_pct !== null) {
      let text = `Last earnings (${last.date}): ${last.surprise_pct >= 0 ? 'beat' : 'missed'} the analysts' estimate by `
        + `${Math.abs(last.surprise_pct).toFixed(0)}%`;
      const earlier = before.map((r) => r.surprise_pct).filter((x) => x !== null);
      if (last.surprise_pct >= 0 && earlier.length && earlier.every((x) => x > last.surprise_pct)) {
        text += `, a smaller beat than before (${earlier.map((x) => `${x.toFixed(0)}%`).join(', ')}): shrinking beats often weigh on a stock`;
      }
      if (last.reaction_pct !== null) text += `. The stock moved ${signed(last.reaction_pct)} vs the market right after the report`;
      sentences.push(`${text}.`);
    }
  }
  return sentences;
}

function moveTable(move) {
  const row = (label, values) => h('tr', {}, h('td', { text: label }),
    ...['1w', '1m', '3m'].map((k) => h('td', { class: `num ${values === null || values[k] === null ? '' : values[k] >= 0 ? 'up' : 'down'}`,
      text: values === null || values[k] === null ? '—' : signed(values[k]) })));
  return h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, h('th', { text: '' }), h('th', { class: 'num', text: '1 week' }),
      h('th', { class: 'num', text: '1 month' }), h('th', { class: 'num', text: '3 months' }))),
    h('tbody', {}, row('This stock', move.stock), row('S&P 500', move.market),
      move.peers === null ? null : row(move.peer_group, move.peers))));
}

function moveCard(ticker, move) {
  return h('div', { class: 'card section' },
    h('h2', { text: 'Why is it moving?' }),
    h('ul', { class: 'small' }, moveSentences(ticker, move).map((text) => h('li', { text }))),
    moveTable(move),
    h('p', { class: 'muted small', text: `Measured facts as of ${move.as_of}, not a forecast. `
      + 'The headlines below often explain the company-specific part.' }));
}

function aboutCard(profile) {
  const summary = profile.summary || 'No business description available.';
  const long = summary.length > SUMMARY_PREVIEW;
  const text = h('p', { class: 'small', text: long ? `${summary.slice(0, SUMMARY_PREVIEW)}…` : summary });
  const facts = [profile.sector, profile.industry, profile.employees ? `${num(profile.employees, 0)} employees` : null]
    .filter(Boolean).join(' · ');
  return h('div', { class: 'card section' },
    h('h2', { text: profile.name ? `About ${profile.name}` : 'About the company' }),
    facts ? h('div', { class: 'muted small', text: facts }) : null,
    text,
    long ? h('button', { type: 'button', text: 'Read more', onclick: (event) => {
      text.textContent = summary;
      event.target.remove();
    } }) : null,
    profile.website ? h('a', { class: 'chip', href: profile.website, target: '_blank', rel: 'noopener', text: 'Company website ↗' }) : null);
}

function newsCard(items, asOf) {
  return h('div', { class: 'card section' },
    h('h2', { text: 'Recent news' }),
    items.length ? h('ul', { class: 'news' }, items.map((item) => h('li', {},
      h('a', { href: item.url, target: '_blank', rel: 'noopener', text: item.title }),
      h('div', { class: 'muted small', text: [item.publisher, item.published ? ago(item.published) : null].filter(Boolean).join(' · ') }),
      item.summary ? h('div', { class: 'small', text: item.summary }) : null)))
      : h('p', { class: 'muted small', text: 'No recent headlines from Yahoo for this stock.' }),
    asOf ? h('p', { class: 'muted small', text: `Headlines refreshed ${asOf} (daily, from Yahoo Finance).` }) : null);
}

/** The About + Recent news cards for a ticker (or one card saying there is no data yet). */
export async function companySection(manifest, ticker) {
  if (!('company' in manifest) || !manifest.company.includes(ticker)) {
    return h('div', { class: 'card section' }, h('h2', { text: 'About the company' }),
      h('p', { class: 'muted small', text: 'No company profile or news for this stock yet (refreshed by the daily job).' }));
  }
  const company = await loadCompany(ticker);
  return h('div', {}, company.move ? moveCard(ticker, company.move) : null,
    newsCard(company.news, company.news_as_of), company.profile ? aboutCard(company.profile) : null);
}
