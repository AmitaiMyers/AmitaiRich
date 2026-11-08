// Service worker: offline app shell + offline copies of the data you have viewed.
//   app shell  -> cache-first, versioned per build (publish.py stamps the build id)
//   data/*     -> network-first (always fresh when online), cached copy when offline

const VERSION = '__BUILD_ID__';
const SHELL_CACHE = `shell-${VERSION}`;
const DATA_CACHE = 'data-v1';

const SHELL = [
  './', 'index.html', 'manifest.webmanifest', 'css/app.css',
  'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png',
  'js/app.js', 'js/chart.js', 'js/data.js', 'js/holdings.js', 'js/positions.js', 'js/ui.js', 'js/lab-worker.js',
  'js/engine/engine.js', 'js/engine/indicators.js', 'js/engine/strategies.js',
  'js/views/lab.js', 'js/views/positions.js', 'js/views/research.js', 'js/views/ticker.js', 'js/views/today.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, DATA_CACHE]);
    for (const key of await caches.keys()) if (!keep.has(key)) await caches.delete(key);
    await self.clients.claim();
  })());
});

async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { ignoreSearch: true });
  return cached || fetch(request);
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  const path = url.pathname.slice(new URL(self.registration.scope).pathname.length);
  event.respondWith(path.startsWith('data/') ? networkFirst(event.request) : cacheFirst(event.request));
});
