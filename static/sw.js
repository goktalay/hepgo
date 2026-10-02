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

// ---------- Arka plan bildirimleri (Web Push): uygulama kapalı / ekran kilitliyken arama, mesaj, telsiz, bildirim
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: 'Fabrika Yönetim Sistemi', body: e.data && e.data.text() }; }
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Uygulama ön planda ve görünürse kendi zil / arama ekranını zaten gösterir
    // (Safari / iOS sessiz push'ta aboneliği iptal edebildiği için orada her zaman gösterilir)
    const safari = /Safari/.test(navigator.userAgent) && !/Chrome|Chromium|Android/.test(navigator.userAgent);
    if (!safari && wins.some(w => w.visibilityState === 'visible' && w.focused)) return;
    const call = d.type === 'call';
    await self.registration.showNotification(d.title || 'Fabrika Yönetim Sistemi', {
      body: d.body || '', tag: d.tag || undefined, renotify: true,
      icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png',
      requireInteraction: call, vibrate: call ? [400, 200, 400, 200, 400, 200, 400] : [150, 80, 150],
      data: { url: d.url || '/app' },
      actions: call ? [{ action: 'open', title: 'Aç ve yanıtla' }] : [],
    });
  })());
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || '/app', self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const w = wins.find(c => new URL(c.url).pathname.startsWith('/app'));
    if (w) {
      await w.focus();
      const hash = new URL(url).hash;
      if (hash) w.postMessage({ t: 'push-open', hash });
      return;
    }
    await self.clients.openWindow(url);
  })());
});
