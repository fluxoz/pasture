// pasture service worker. The build replaces @VERSION@ (a hash of the whole
// bundle) and @PRECACHE@ (every static file), so each build gets a new cache.
// /api, /auth, /ws and /enroll are never cached.

const VERSION = '@VERSION@';
const CACHE = `pasture-${VERSION}`;
const PRECACHE = @PRECACHE@;
const NETWORK_ONLY = ['/api/', '/auth/', '/ws/', '/enroll', '/healthz'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('pasture-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (NETWORK_ONLY.some((p) => url.pathname.startsWith(p))) return;

  if (req.mode === 'navigate') {
    // Network first so a new build shows up; the cached shell when offline.
    event.respondWith(fetch(req).catch(() => caches.match('/', { cacheName: CACHE })));
    return;
  }
  event.respondWith(caches.match(req, { cacheName: CACHE }).then((hit) => hit || fetch(req)));
});
