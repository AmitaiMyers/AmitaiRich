// App shell: loads the published manifest + signals once, routes #/hash views,
// wires the ticker search and registers the service worker (offline + install).

import { loadManifest, loadSignals } from './data.js';
import { h, showBanner } from './ui.js';
import { renderLab } from './views/lab.js';
import { renderPositions } from './views/positions.js';
import { renderResearch } from './views/research.js';
import { renderTicker } from './views/ticker.js';
import { renderToday } from './views/today.js';

const ROUTES = {
  today: renderToday,
  positions: renderPositions,
  lab: renderLab,
  research: renderResearch,
  t: renderTicker,
};

const view = document.getElementById('view');
let context = null;   // {manifest, signals, tickers:Set}
let renderToken = 0;

async function boot() {
  try {
    const [manifest, signals] = await Promise.all([loadManifest(), loadSignals()]);
    context = { manifest, signals, tickers: new Set(manifest.tickers) };
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

document.getElementById('search').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = document.getElementById('search-input');
  const symbol = input.value.trim().toUpperCase().replace(/\./g, '-');
  if (!symbol) return;
  input.value = '';
  input.blur();
  location.hash = `#/t/${encodeURIComponent(symbol)}`;
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
