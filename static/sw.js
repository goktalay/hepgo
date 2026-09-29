// CAYMAZ web uygulaması service worker'ı: uygulamanın kurulabilmesi ve bağlantı yokken
// anlamlı bir sayfa gösterilmesi için. Veriler (API) önbelleğe alınmaz; arayüz her zaman güncel sunucudan gelir.
const CACHE = 'caymaz-shell-v1';
const OFFLINE = '/static/offline.html';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([OFFLINE, '/static/icons/icon-192.png'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
  }
});
