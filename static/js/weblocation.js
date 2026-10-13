// Web (tarayıcı) konum paylaşımı: Canlı Konum için mobil uygulama dışındaki kullanıcıların da konumu.
// Kurallar: (1) KVKK açık rıza (sunucudaki /api/location/consent; native ile ortak), (2) tarayıcının konum izni,
// (3) Ayarlar › Gizlilik › "Web'de konumumu paylaş" açık. Yalnız sekme açıkken; değişiklikte ya da en geç 2 dk'da bir
// /api/location/ping (platform 'web', doğruluk ile). Native kabukta (Capacitor) çalışmaz — orada native.js vardır.
import { api } from './api.js';
import { h, modal } from './ui.js';

const MIN_INTERVAL = 60_000, MAX_INTERVAL = 120_000, MIN_MOVE_M = 25;
let watchId = null, timer = null, last = null, lastSent = 0;

const dist = (a, b) => {   // metre (haversine)
  const R = 6371000, toR = x => x * Math.PI / 180, dLat = toR(b.lat - a.lat), dLng = toR(b.lng - a.lng);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toR(a.lat)) * Math.cos(toR(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
};

function consentDialog() {
  return new Promise(resolve => {
    const m = modal({
      title: '📍 Konum takibine izin',
      body: h('div', null,
        h('p', { class: 'small', style: { marginTop: 0, lineHeight: 1.55 } },
          'Çalışma saatlerinde iş süreçleri ve saha/güvenlik yönetimi için konumunuz tarayıcı üzerinden kaydedilebilir (yalnız HEPGO sekmesi açıkken). ',
          'Bu KVKK kapsamında ', h('b', null, 'açık rızanıza'), ' bağlıdır; Ayarlar › Gizlilik\'ten dilediğiniz zaman kapatabilirsiniz. Ayrıntı: Gizlilik Politikası.')),
      actions: [{ label: 'Reddet', onClick: () => { resolve(false); } }, { label: 'Onaylıyorum', class: 'primary', onClick: () => { resolve(true); } }],
      onClose: () => resolve(false),
    });
    void m;
  });
}

async function send(pos, allowed) {
  if (!allowed()) return;
  const { latitude: lat, longitude: lng, accuracy: acc } = pos.coords;
  const now = Date.now();
  const moved = !last || dist(last, { lat, lng }) >= MIN_MOVE_M;
  if (now - lastSent < MIN_INTERVAL && !moved) return;
  if (!moved && now - lastSent < MAX_INTERVAL) return;
  lastSent = now; last = { lat, lng };
  try { await api.post('/api/location/ping', { lat, lng, acc, at: new Date(pos.timestamp || now).toISOString(), platform: 'web' }); } catch { /* sessiz */ }
}

export function stopWebLocation() {
  if (watchId != null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
  clearInterval(timer); watchId = null; timer = null;
}

export async function initWebLocation(ctx, allowed = () => true) {
  try {
    if (window.Capacitor?.isNativePlatform?.()) return;   // native kabuk kendi takibini yapar
    if (!navigator.geolocation || !ctx?.user) return;
    if (!allowed()) return;
    let c = null;
    try { c = (await api.get('/api/location/consent')).consent; } catch { return; }
    if (!c) {
      const ok = await consentDialog();
      try { await api.post('/api/location/consent', { granted: ok }); } catch { /* */ }
      if (!ok) return;
    } else if (!c.granted) return;
    stopWebLocation();
    watchId = navigator.geolocation.watchPosition(pos => send(pos, allowed), () => {}, { enableHighAccuracy: true, maximumAge: 30_000, timeout: 20_000 });
    // hareket yoksa da en geç 2 dk'da bir güncel konum (sekme açıkken)
    timer = setInterval(() => { if (document.hidden || !allowed()) return; navigator.geolocation.getCurrentPosition(pos => send(pos, allowed), () => {}, { enableHighAccuracy: false, maximumAge: 60_000, timeout: 15_000 }); }, MAX_INTERVAL);
  } catch { /* yut */ }
}
