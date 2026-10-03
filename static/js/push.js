// Arka plan bildirimleri (Web Push): uygulama kapalıyken / ekran kilitliyken arama, mesaj, telsiz ve bildirimler cihaza düşer.
// İzin bir kez verilince bu cihaz sunucuya abone edilir; her açılışta abonelik sessizce tazelenir.
import { api } from './api.js';

const b64 = s => { const p = '='.repeat((4 - (s.length % 4)) % 4); const r = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(r, c => c.charCodeAt(0)); };
const isIOS = () => /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

export function pushSupport() {
  if (!window.isSecureContext || !('serviceWorker' in navigator)) return { ok: false, why: 'Bu bağlantıda (güvenli olmayan adres) desteklenmiyor.' };
  if (!('PushManager' in window) || !('Notification' in window)) {
    if (isIOS() && !standalone()) return { ok: false, why: 'iPhone / iPad\'de önce Paylaş › "Ana Ekrana Ekle" ile uygulamayı yükleyin, sonra uygulamadan açın.' };
    return { ok: false, why: 'Bu tarayıcı arka plan bildirimlerini desteklemiyor.' };
  }
  if (Notification.permission === 'denied') return { ok: false, why: 'Bildirim izni tarayıcı ayarlarından engellenmiş; site ayarlarından izin verin.' };
  return { ok: true };
}

async function reg() { return navigator.serviceWorker.ready; }

export async function pushState() {
  if (!pushSupport().ok) return 'unsupported';
  const sub = await (await reg()).pushManager.getSubscription();
  return sub && Notification.permission === 'granted' ? 'on' : 'off';
}

async function subscribe() {
  const r = await reg();
  let sub = await r.pushManager.getSubscription();
  const { key } = await api.get('/api/push/key');
  if (sub) {   // sunucu anahtarı değiştiyse yeniden abone ol
    const cur = sub.options?.applicationServerKey ? new Uint8Array(sub.options.applicationServerKey) : null;
    const want = b64(key);
    if (cur && (cur.length !== want.length || cur.some((v, i) => v !== want[i]))) { await sub.unsubscribe(); sub = null; }
  }
  sub ??= await r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
  await api.post('/api/push/subscribe', sub.toJSON());
}

export async function enablePush() {
  const s = pushSupport();
  if (!s.ok) throw new Error(s.why);
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('Bildirim izni verilmedi');
  try { await subscribe(); } catch (e) {
    if (e?.status) throw e;   // sunucu hatası: mesajı olduğu gibi
    throw new Error(/permission|denied|NotAllowed/i.test(`${e?.name} ${e?.message}`)
      ? 'Tarayıcı bu cihazda arka plan bildirimine izin vermedi (site ayarlarından bildirim iznini kontrol edin).'
      : 'Bu cihaz bildirim servisine abone olamadı. İnternet bağlantısını kontrol edip tekrar deneyin.');
  }
}

export async function disablePush() {
  const sub = await (await reg()).pushManager.getSubscription();
  if (sub) { await api.post('/api/push/unsubscribe', { endpoint: sub.endpoint, keys: {} }).catch(() => {}); await sub.unsubscribe(); }
}

// Girişte: izin önceden verilmişse aboneliği sessizce tazele (hesap değişmiş olabilir)
export function syncPush() {
  if (!pushSupport().ok || Notification.permission !== 'granted') return;
  subscribe().catch(() => {});
}

// Bildirime tıklanınca açık pencere ilgili sayfaya gider
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('message', e => {
    if (e.data?.t !== 'push-open' || !e.data.hash) return;
    if (location.hash === e.data.hash) window.dispatchEvent(new HashChangeEvent('hashchange'));   // zaten oradaysa yeniden çiz (yeni paylaşım gelsin)
    else location.hash = e.data.hash;
  });
}
