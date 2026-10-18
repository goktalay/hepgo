// CAYMAZ web uygulaması service worker'ı: uygulamanın kurulabilmesi ve bağlantı yokken
// anlamlı bir sayfa gösterilmesi için. Veriler (API) önbelleğe alınmaz; arayüz her zaman güncel sunucudan gelir.
// Tek istisna: Şirketten Haberler MEDYASI (/api/files/feed/…) — TikTok gibi bir kez iner, Cache Storage'da kalır (aşağıda).
const CACHE = 'caymaz-shell-v2';
const OFFLINE = '/static/offline.html';

// ---------- Şirketten Haberler medya önbelleği
// Dosya adları rastgele/değişmez (sunucu da 1 yıl immutable verir) → içerik hiç eskimez; yalnız yer sınırı var.
// MEDIA_LIMIT aşılınca en uzun süredir ERİŞİLMEYEN silinir (LRU; erişim zamanları META deposunda tek JSON olarak tutulur).
// Video için tarayıcının Range (bytes=a-b) istekleri de önbellekteki tam dosyadan dilimlenerek (206) yanıtlanır.
// Oturum kapatılınca (POST /api/auth/logout) depo boşaltılır: medya giriş gerektirir, cihazda oturumsuz kalmasın.
const MEDIA_CACHE = 'feed-media-v1';
const META_CACHE = 'feed-media-meta-v1';
const MEDIA_LIMIT = 300 * 1024 * 1024;
const MEDIA_PATH = /^\/api\/files\/feed\//;
let metaQ = Promise.resolve();   // META okuma-yazma sırayla (yarış olmasın)
const withMeta = fn => (metaQ = metaQ.then(async () => {
  const c = await caches.open(META_CACHE);
  let meta = {};
  try { const r = await c.match('/__meta'); if (r) meta = await r.json(); } catch { meta = {}; }
  const out = await fn(meta);
  await c.put('/__meta', new Response(JSON.stringify(meta), { headers: { 'Content-Type': 'application/json' } }));
  return out;
}, () => {}));
const mediaKey = url => { const u = new URL(url, self.location.origin); u.hash = ''; return u.href; };

async function mediaStore(key, res) {
  const size = +(res.headers.get('Content-Length') || 0) || (await res.clone().arrayBuffer()).byteLength;
  if (size > MEDIA_LIMIT / 2) return;   // tek dosya deponun yarısından büyükse saklanmaz (ağdan oynar)
  const cache = await caches.open(MEDIA_CACHE);
  await cache.put(key, res);
  await withMeta(async meta => {
    meta[key] = { s: size, t: Date.now() };
    let total = Object.values(meta).reduce((a, x) => a + (x.s || 0), 0);
    if (total > MEDIA_LIMIT) {
      const old = Object.entries(meta).sort((a, b) => a[1].t - b[1].t);
      for (const [k, v] of old) { if (total <= MEDIA_LIMIT) break; await cache.delete(k); delete meta[k]; total -= v.s || 0; }
    }
  });
}
const touch = key => withMeta(meta => { if (meta[key]) meta[key].t = Date.now(); });

const inflight = new Map();   // aynı dosya için eşzamanlı istekler tek indirme paylaşır
function mediaFetchFull(key) {
  if (inflight.has(key)) return inflight.get(key).then(r => r.clone());
  const p = (async () => {
    const res = await fetch(key, { credentials: 'same-origin' });   // Range'siz: tam dosya (önbelleğe tam girer)
    if (res.ok && res.status === 200) { await mediaStore(key, res.clone()); }
    return res;
  })();
  inflight.set(key, p);
  p.finally(() => inflight.delete(key)).catch(() => {});
  return p.then(r => r.clone());
}
// Önbellekteki tam yanıttan Range dilimi (206); bozuk aralıkta tam yanıt döner
async function sliced(res, range) {
  const m = /^bytes=(\d*)-(\d*)$/.exec(range || '');
  if (!m) return res;
  const buf = await res.arrayBuffer();
  const len = buf.byteLength;
  let start = m[1] === '' ? Math.max(0, len - (+m[2] || 0)) : +m[1];
  let end = m[1] !== '' && m[2] !== '' ? Math.min(+m[2], len - 1) : len - 1;
  if (!(start <= end && start < len)) return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${len}` } });
  const h = new Headers(res.headers);
  h.set('Content-Range', `bytes ${start}-${end}/${len}`);
  h.set('Content-Length', String(end - start + 1));
  h.set('Accept-Ranges', 'bytes');
  return new Response(buf.slice(start, end + 1), { status: 206, statusText: 'Partial Content', headers: h });
}
async function mediaRespond(e, req) {
  const key = mediaKey(req.url);
  const range = req.headers.get('Range');
  const cache = await caches.open(MEDIA_CACHE);
  const hit = await cache.match(key);
  if (hit) { touch(key); return range ? sliced(hit, range) : hit; }
  if (range) {
    // İlk oynatma beklemesin: Range isteği doğrudan ağdan akar, tam dosya ARKA PLANDA indirilip depoya konur (sonraki açılış depodan)
    e.waitUntil(mediaFetchFull(key).catch(() => {}));
    return fetch(req);
  }
  try { return await mediaFetchFull(key); } catch { return new Response('', { status: 504, statusText: 'offline' }); }
}
async function prefetch(urls) {
  const cache = await caches.open(MEDIA_CACHE);
  for (const u of urls || []) {
    const key = mediaKey(u);
    if (!MEDIA_PATH.test(new URL(key).pathname)) continue;
    if (await cache.match(key)) { touch(key); continue; }
    try { await mediaFetchFull(key); } catch { /* bağlantı yok: sonraki ön yüklemede */ }
  }
}
self.addEventListener('message', e => {
  const d = e.data || {};
  if (d.t === 'feed-prefetch') e.waitUntil(prefetch(d.urls));
  if (d.t === 'feed-media-clear') e.waitUntil(Promise.all([caches.delete(MEDIA_CACHE), caches.delete(META_CACHE)]));
});

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll([OFFLINE, '/static/icons/icon-192.png'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  // Kabuk önbelleği sürüm değişince silinir; medya deposu KORUNUR (tekrar indirmemek bu depoyu yaşatmaya bağlı)
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== MEDIA_CACHE && k !== META_CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method === 'POST' && url.pathname === '/api/auth/logout') {
    e.waitUntil(Promise.all([caches.delete(MEDIA_CACHE), caches.delete(META_CACHE)]));
    return;
  }
  if (req.method === 'GET' && MEDIA_PATH.test(url.pathname) && !url.searchParams.get('dl')) {
    e.respondWith(mediaRespond(e, req));
  }
});

// ---------- Arka plan bildirimleri (Web Push): uygulama kapalı / ekran kilitliyken arama, mesaj, telsiz, bildirim
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { title: 'Bildirim', body: e.data && e.data.text() }; }
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Uygulama ön planda ve görünürse kendi zil / arama ekranını zaten gösterir
    // (Safari / iOS sessiz push'ta aboneliği iptal edebildiği için orada her zaman gösterilir)
    const safari = /Safari/.test(navigator.userAgent) && !/Chrome|Chromium|Android/.test(navigator.userAgent);
    if (!safari && wins.some(w => w.visibilityState === 'visible' && w.focused)) return;
    const call = d.type === 'call';
    await self.registration.showNotification(d.title || 'Bildirim', {
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
