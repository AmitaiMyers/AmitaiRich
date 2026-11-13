// App shell: loads the published manifest + signals once, routes #/hash views,
// wires the ticker search and registers the service worker (offline + install).

import { loadDaily, loadManifest, loadSignals } from './data.js';
import { h, showBanner } from './ui.js';
import { renderPositions } from './views/positions.js';
import { renderTicker } from './views/ticker.js';
import { renderToday } from './views/today.js';

const ROUTES = {
  today: renderToday,
  positions: renderPositions,
  t: renderTicker,
};

const view = document.getElementById('view');
let context = null;   // {manifest, signals, tickers:Set}
let renderToken = 0;

async function boot() {
  try {
    const [manifest, signals, daily] = await Promise.all([loadManifest(), loadSignals(), loadDaily()]);
    context = { manifest, signals, daily, tickers: new Set(manifest.tickers) };
  } catch (error) {
    showBanner(`Could not load published data (${error.message}). If you are offline, open the app once online first.`, 'error');
    view.replaceChildren(h('div', { class: 'empty', text: 'No data available yet.' }));
    return;
  }
  const { manifest } = context;
  document.getElementById('data-stamp').textContent =
    `Data as of ${manifest.data_date} · build ${manifest.build}${manifest.demo ? ' · DEMO DATA' : ''}`;
  if (manifest.demo) showBanner('Demo build: synthetic prices, not real market data.');
  document.getElementById('ticker-list').replaceChildren(...manifest.tickers.map((t) => h('option', { value: t })));
  window.addEventListener('hashchange', route);
  route();
}

async function route() {
  const [name, ...args] = (location.hash.replace(/^#\/?/, '') || 'today').split('/');
  const render = ROUTES[name] || renderToday;
  for (const link of document.querySelectorAll('[data-tab]')) {
    link.classList.toggle('active', link.dataset.tab === (name === 't' ? '' : name));
  }
  const token = ++renderToken;
  view.replaceChildren(h('div', { class: 'skeleton', text: 'Loading…' }));
  const page = await render(context, args.map(decodeURIComponent));
  if (token === renderToken) {   // ignore a slow render the user already navigated away from
    view.replaceChildren(page);
    view.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

const searchInput = document.getElementById('search-input');
const normalizeSymbol = (text) => text.trim().toUpperCase().replace(/\./g, '-');

function openSymbol(symbol) {
  searchInput.value = '';
  searchInput.blur();
  location.hash = `#/t/${encodeURIComponent(symbol)}`;
}

document.getElementById('search').addEventListener('submit', (event) => {
  event.preventDefault();
  const symbol = normalizeSymbol(searchInput.value);
  if (symbol) openSymbol(symbol);
});

// Picking a ticker from the suggestion list opens it at once (phones show no Enter for that).
// A pick arrives as an input event that is not plain typing: no inputType (Safari) or
// 'insertReplacementText' (Chrome). Typing "A" on the way to "AAPL" must not jump to A.
searchInput.addEventListener('input', (event) => {
  const picked = !event.inputType || event.inputType === 'insertReplacementText';
  const symbol = normalizeSymbol(searchInput.value);
  if (picked && context !== null && context.tickers.has(symbol)) openSymbol(symbol);
});

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const registration = await navigator.serviceWorker.register('sw.js');
  if (!registration) return;   // registration can be disabled (e.g. some embedded/test browsers)
  registration.addEventListener('updatefound', () => {
    const worker = registration.installing;
    worker.addEventListener('statechange', () => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) {
        showBanner('New data is available — reopen the app to refresh.');
      }
    });
  });
}

registerServiceWorker();
boot();
