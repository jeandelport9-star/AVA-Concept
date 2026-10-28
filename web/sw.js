// Offline shell: the app opens without signal; data needs a connection.
const C = 'ava-v5';
const SHELL = ['/', '/index.html', '/css/app.css', '/js/app.js', '/js/core.js', '/js/public.js', '/js/office.js', '/js/work.js', '/js/market.js', '/js/inspect.js', '/js/shell.js', '/js/pano.js', '/js/agent.js', '/js/trust.js', '/js/compliance.js', '/js/growth.js',
  '/vendor/leaflet/leaflet.js', '/vendor/leaflet/leaflet.css', '/img/mark.png', '/img/icon-192.png', '/manifest.webmanifest'];
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request, { cache: 'no-cache' }).then(r => { if (r.ok && !u.pathname.startsWith('/uploads/')) { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)); } return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match('/index.html'))));
});
