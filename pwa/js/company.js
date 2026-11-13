// Stock page: what the company does (profile) and its recent headlines, from data/company/<T>.json
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
  return h('div', {}, company.profile ? aboutCard(company.profile) : null, newsCard(company.news, company.news_as_of));
}
