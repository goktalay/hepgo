import { simActive } from './simfocus.js';   // simülasyon sahnesinde sistem sesleri susar
// Sistem sesleri: her olay türünün (uyarı, bildirim, kargo, mesaj…) kendi sesi vardır; kullanıcı Ayarlar'dan değiştirir.
// Sesler dosya değil, tarayıcıda Web Audio ile üretilir (lisans / indirme yok, her cihazda aynı). Tarayıcılar ilk dokunuş /
// tıklamadan önce ses çalmaya izin vermez; ilk etkileşimde ses motoru açılır.
let ac = null;
let settings = { on: true, volume: 0.7, map: {} };
let lastPlay = 0;

export const EVENTS = [
  ['alert', 'Uyarı', 'Yazıcı / üretim uyarısı'],
  ['critical', 'Kritik uyarı', 'Kayıtsız baskı yarıda kesildi vb.'],
  ['notification', 'Bildirim', 'Diğer bildirimler (depo onayı, montaj bekleyen…)'],
  ['message', 'Mesaj', 'Yeni sohbet mesajı'],
  ['cargo', 'Kargo', 'Size kargo geldi'],
  ['call', 'Arama', 'Sizi arayan var (Aramalarım)'],
  ['guest', 'Misafir', 'Misafiriniz geldi'],
  ['announcement', 'Duyuru', 'Yeni duyuru'],
  ['signature', 'İmza', 'İmzanızı bekleyen evrak'],
  ['calendar', 'Takvim', 'Randevu / hatırlatma zamanı'],
  ['mail', 'E-posta', 'Gmail gelen kutusuna yeni e-posta'],
  ['meeting', 'Toplantı daveti', 'Bir toplantıya davet edildiniz'],
  ['meeting_soon', 'Toplantı hatırlatması', 'Toplantı zamanı yaklaşıyor'],
  ['online', 'Kullanıcı çevrimiçi oldu', 'Bir kullanıcı sisteme girdi'],
  ['offline', 'Kullanıcı çevrimdışı oldu', 'Bir kullanıcı sistemden çıktı / ayrıldı'],
];
export const DEFAULTS = { alert: 'Dikkat', critical: 'Alarm', notification: 'Nazik', message: 'Mesaj', cargo: 'Kapı Zili', call: 'Telefon',
  guest: 'Üçlü Zil', announcement: 'Çan', signature: 'Kristal', calendar: 'Marimba', mail: 'Damla', meeting: 'Ksilofon', meeting_soon: 'Rüzgâr Çanı', online: 'Arp Yukarı', offline: 'Arp Aşağı' };
// Bildirim anahtarı (app/notifications.py) → ses olayı
const NOTIFY_EVENT = { 'cargo-waiting': 'cargo', 'call-waiting': 'call', 'guest-visit': 'guest', announcements: 'announcement',
  'signature-pending': 'signature', 'calendar-due': 'calendar', 'mail-unread': 'mail',
  'meeting-invite': 'meeting', 'meeting-soon': 'meeting_soon' };
export const eventOfNotification = key => NOTIFY_EVENT[key] || 'notification';

// ---------- ses üretimi
function ctx() {
  if (!ac) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; ac = new C(); }
  if (ac.state === 'suspended') ac.resume().catch(() => {});
  return ac;
}
['pointerdown', 'keydown', 'touchstart'].forEach(ev => addEventListener(ev, () => ctx(), { once: true, passive: true }));

// Tek nota: frekans (ya da [başlangıç, bitiş] kayması), başlangıç, süre, dalga, ses, atak
function note(out, f, t, dur, { type = 'sine', vol = 0.5, attack = 0.005, fm = 0, fmRatio = 2 } = {}) {
  const a = out.context, o = a.createOscillator(), g = a.createGain();
  o.type = type;
  const [f0, f1] = Array.isArray(f) ? f : [f, f];
  o.frequency.setValueAtTime(f0, t);
  if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + dur * 0.9);
  if (fm) {   // FM: çan / gong tınısı
    const m = a.createOscillator(), mg = a.createGain();
    m.frequency.value = f0 * fmRatio;
    mg.gain.setValueAtTime(f0 * fm, t);
    mg.gain.exponentialRampToValueAtTime(1, t + dur);
    m.connect(mg).connect(o.frequency);
    m.start(t); m.stop(t + dur + 0.05);
  }
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(vol, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(out);
  o.start(t); o.stop(t + dur + 0.05);
}
function noise(out, t, dur, vol = 0.3, freq = 3000) {
  const a = out.context, len = Math.floor(a.sampleRate * dur), buf = a.createBuffer(1, len, a.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const s = a.createBufferSource(), f = a.createBiquadFilter(), g = a.createGain();
  s.buffer = buf; f.type = 'bandpass'; f.frequency.value = freq; g.gain.value = vol;
  s.connect(f).connect(g).connect(out); s.start(t);
}
const N = { C5: 523.3, D5: 587.3, E5: 659.3, F5: 698.5, G5: 784, A5: 880, B5: 987.8, C6: 1046.5, D6: 1174.7, E6: 1318.5, G6: 1568, C7: 2093, A4: 440, G4: 392, E4: 329.6, C4: 261.6 };

// Ses kütüphanesi: ad → (çıkış, t) çizimi
export const SOUNDS = {
  'Ding': (o, t) => note(o, N.A5, t, 0.9, { vol: 0.5 }),
  'Ding Dong': (o, t) => { note(o, N.E5, t, 0.7, { vol: 0.5 }); note(o, N.C5, t + 0.35, 1.0, { vol: 0.5 }); },
  'Kapı Zili': (o, t) => { note(o, N.E5, t, 1.1, { vol: 0.45, fm: 0.4, fmRatio: 3.5 }); note(o, N.C5, t + 0.5, 1.4, { vol: 0.45, fm: 0.4, fmRatio: 3.5 }); },
  'Üçlü Zil': (o, t) => [N.C5, N.E5, N.G5].forEach((f, i) => note(o, f, t + i * 0.13, 0.7, { vol: 0.4 })),
  'Kristal': (o, t) => { note(o, N.G6, t, 1.4, { vol: 0.3 }); note(o, N.C7, t + 0.08, 1.6, { vol: 0.22 }); note(o, N.E6, t + 0.16, 1.2, { vol: 0.2 }); },
  'Damla': (o, t) => note(o, [1400, 500], t, 0.25, { vol: 0.5 }),
  'Pop': (o, t) => note(o, [380, 950], t, 0.12, { vol: 0.55 }),
  'Marimba': (o, t) => { note(o, N.G5, t, 0.35, { vol: 0.5, fm: 1.2, fmRatio: 4 }); note(o, N.C6, t + 0.14, 0.45, { vol: 0.5, fm: 1.2, fmRatio: 4 }); },
  'Nazik': (o, t) => { note(o, N.C5, t, 0.5, { type: 'triangle', vol: 0.4, attack: 0.02 }); note(o, N.E5, t + 0.18, 0.7, { type: 'triangle', vol: 0.4, attack: 0.02 }); },
  'Çan': (o, t) => note(o, N.C5, t, 2.2, { vol: 0.45, fm: 2.5, fmRatio: 1.4 }),
  'Gong': (o, t) => note(o, 130, t, 3, { vol: 0.6, fm: 3, fmRatio: 1.48, attack: 0.02 }),
  'Arp Yukarı': (o, t) => [N.C5, N.E5, N.G5, N.C6].forEach((f, i) => note(o, f, t + i * 0.08, 0.4, { vol: 0.35 })),
  'Arp Aşağı': (o, t) => [N.C6, N.G5, N.E5, N.C5].forEach((f, i) => note(o, f, t + i * 0.08, 0.4, { vol: 0.35 })),
  'Bip Bip': (o, t) => { note(o, 1800, t, 0.09, { type: 'square', vol: 0.18 }); note(o, 1800, t + 0.16, 0.09, { type: 'square', vol: 0.18 }); },
  'Radar': (o, t) => [0, 0.35, 0.7].forEach((d, i) => note(o, 1200, t + d, 0.3, { vol: 0.4 - i * 0.1 })),
  'Alarm': (o, t) => [0, 0.25, 0.5, 0.75, 1.0, 1.25].forEach((d, i) => note(o, i % 2 ? 660 : 880, t + d, 0.22, { type: 'square', vol: 0.2, attack: 0.01 })),
  'Siren': (o, t) => { note(o, [600, 1200], t, 0.6, { type: 'sawtooth', vol: 0.15, attack: 0.05 }); note(o, [1200, 600], t + 0.6, 0.6, { type: 'sawtooth', vol: 0.15, attack: 0.02 }); },
  'Kuş': (o, t) => [0, 0.12, 0.3].forEach(d => note(o, [2600, 4200], t + d, 0.09, { vol: 0.25 })),
  'Kabarcık': (o, t) => [0, 0.1, 0.2].forEach((d, i) => note(o, [300 + i * 150, 900 + i * 200], t + d, 0.1, { vol: 0.4 })),
  'Tık': (o, t) => noise(o, t, 0.04, 0.6, 2500),
  'Ksilofon': (o, t) => [N.E6, N.G6, N.C7].forEach((f, i) => note(o, f, t + i * 0.1, 0.3, { vol: 0.3, fm: 0.8, fmRatio: 3 })),
  'Arp': (o, t) => [N.C5, N.D5, N.E5, N.G5, N.A5, N.C6, N.D6, N.E6].forEach((f, i) => note(o, f, t + i * 0.045, 0.8, { type: 'triangle', vol: 0.22 })),
  'Uzay': (o, t) => note(o, [200, 1600], t, 0.8, { vol: 0.3, fm: 1.5, fmRatio: 0.5, attack: 0.05 }),
  'Mesaj': (o, t) => { note(o, N.C6, t, 0.18, { vol: 0.4 }); note(o, N.E6, t + 0.1, 0.35, { vol: 0.4 }); },
  'Telefon': (o, t) => [0, 0.5].forEach(d => { for (let k = 0; k < 8; k++) { note(o, 440, t + d + k * 0.05, 0.05, { vol: 0.15, attack: 0.003 }); note(o, 480, t + d + k * 0.05, 0.05, { vol: 0.15, attack: 0.003 }); } }),
  'Jeton': (o, t) => { note(o, N.B5, t, 0.1, { type: 'square', vol: 0.15 }); note(o, N.E6, t + 0.09, 0.45, { type: 'square', vol: 0.15 }); },
  'Başarı': (o, t) => { [N.C5, N.E5, N.G5].forEach((f, i) => note(o, f, t + i * 0.1, 0.3, { vol: 0.3 })); [N.C5, N.E5, N.G5, N.C6].forEach(f => note(o, f, t + 0.35, 0.9, { vol: 0.18 })); },
  'Dikkat': (o, t) => { note(o, N.A5, t, 0.3, { type: 'triangle', vol: 0.5 }); note(o, 830.6, t + 0.28, 0.5, { type: 'triangle', vol: 0.5 }); },
  'Yumuşak Nabız': (o, t) => [0, 0.3].forEach(d => note(o, 520, t + d, 0.25, { vol: 0.35, attack: 0.06 })),
  'Rüzgâr Çanı': (o, t) => [N.G6, N.E6, N.C7, N.D6, N.G6].forEach((f, i) => note(o, f, t + i * 0.11 + Math.random() * 0.03, 1.2, { vol: 0.14, fm: 0.3, fmRatio: 2.7 })),
  'Düdük': (o, t) => note(o, [1500, 2100], t, 0.35, { vol: 0.25, attack: 0.03 }),
  'Robot': (o, t) => [0, 0.1, 0.2].forEach((d, i) => note(o, [300, 250][i % 2] || 350, t + d, 0.09, { type: 'square', vol: 0.15 })),
  'Sessiz': () => {},
};
export const SOUND_NAMES = Object.keys(SOUNDS);

export function playSound(name, volume = settings.volume) {
  const a = ctx();
  if (!a || !SOUNDS[name] || volume <= 0) return;
  const out = a.createGain();
  out.gain.value = Math.min(1, Math.max(0, volume));
  out.connect(a.destination);
  try { SOUNDS[name](out, a.currentTime + 0.02); } catch { /* yok say */ }
}

// Olay sesi: ayar kapalıysa çalmaz; aynı anda birden çok olay gelirse yalnızca biri çalar (1.5 sn)
const inQuiet = () => {   // sessiz saatler (ör. 22:00–08:00; gece yarısını aşabilir)
  const q = settings.quiet;
  if (!q?.on || !q.from || !q.to) return false;
  const d = new Date(), now = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return q.from <= q.to ? now >= q.from && now < q.to : now >= q.from || now < q.to;
};

export function playEvent(event) {
  if (!settings.on || inQuiet() || simActive()) return;
  const now = Date.now();
  if (now - lastPlay < 1500) return;
  lastPlay = now;
  playSound(settings.map?.[event] || DEFAULTS[event] || DEFAULTS.notification);
}

export const setSoundSettings = s => { settings = { on: true, volume: 0.7, map: {}, ...(s || {}) }; };
export const soundSettings = () => settings;
