// Yüz ile giriş — ortak arayüz parçaları: Face ID tarzı yuvarlak kamera + 360° segmentli ilerleme halkası, kamera açma /
// kare yakalama, hata metinleri. Eğitim (modules/facesetup.js) ve giriş ekranı (face.js) bu bileşeni kullanır.
// Stil: static/css/face.css (ilk kullanımda <link> ile yüklenir; app.css'e dokunulmaz). Saf matematik: facemath.js.
import { SEGMENTS, segmentAngle, screenPose } from './facemath.js';
import { h, t } from './ui.js';

const TICKS_PER_SEG = 9;   // her yön segmentinde 9 ince çubuk (iPhone Face ID gibi)
const SVG_NS = 'http://www.w3.org/2000/svg';

// SVG öğesi (ui.js h() HTML ad alanında yaratır; SVG için createElementNS şart)
function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}

export function ensureFaceStyle() {
  if (document.getElementById('face-css')) return;
  document.head.append(h('link', { id: 'face-css', rel: 'stylesheet', href: '/static/css/face.css' }));
}

// Halka: {el, video, setSlots, setNext, setLive, setText, setHint, setState, celebrate, fail, destroy}
export function createFaceRing({ size = 280, label = '' } = {}) {
  ensureFaceStyle();
  const R = 136, C = 150;   // viewBox 300×300
  const ticks = [];
  const tickG = s('g', { class: 'fr-ticks' });
  for (let i = 0; i < SEGMENTS.length; i++) {
    for (let k = 0; k < TICKS_PER_SEG; k++) {
      // segment merkezi segmentAngle(i) (0° = sağ, saat yönünün tersi yukarı); SVG y aşağı → açı işareti ters
      const a = segmentAngle(i) - 22.5 + (k + 0.5) * (45 / TICKS_PER_SEG);
      const rad = (-a * Math.PI) / 180;
      const x1 = (C + Math.cos(rad) * (R - 9)).toFixed(2), y1 = (C + Math.sin(rad) * (R - 9)).toFixed(2);
      const x2 = (C + Math.cos(rad) * (R + 9)).toFixed(2), y2 = (C + Math.sin(rad) * (R + 9)).toFixed(2);
      const ln = s('line', { class: 'fr-tick', 'data-seg': SEGMENTS[i], x1, y1, x2, y2 });
      ticks.push(ln); tickG.append(ln);
    }
  }
  const live = s('circle', { class: 'fr-live', cx: C, cy: C, r: 5, opacity: 0 });
  const check = s('path', { class: 'fr-check', d: 'M108 152 l30 30 l56 -64' });
  const cross = s('path', { class: 'fr-cross', d: 'M118 118 l64 64 M182 118 l-64 64' });
  const svg = s('svg', { class: 'fr-ring', viewBox: '0 0 300 300', 'aria-hidden': 'true' },
    s('circle', { class: 'fr-track', cx: C, cy: C, r: R }),
    s('circle', { class: 'fr-glow', cx: C, cy: C, r: R - 18 }),
    tickG, live, check, cross);
  const video = h('video', { autoplay: '', playsinline: '', muted: '', 'aria-hidden': 'true' });
  video.muted = true;
  const cam = h('div', { class: 'fr-cam' }, video, h('div', { class: 'fr-scan' }), h('div', { class: 'fr-noface' }, h('span', { class: 'fr-silhouette' })));
  const stage = h('div', { class: 'fr-stage', style: { width: `${size}px`, height: `${size}px` } }, cam, svg);
  const text = h('div', { class: 'fr-text', role: 'status', 'aria-live': 'polite' }, label);
  const hint = h('div', { class: 'fr-hint', 'aria-live': 'polite' });
  const el = h('div', { class: 'fr-wrap', 'data-state': 'idle' }, stage, text, hint);

  let slots = new Set(), next = null, lastText = '';
  const api = {
    el, video, stage,
    setState(s) { el.dataset.state = s; },
    setSlots(list) {
      slots = new Set(list || []);
      for (const ln of ticks) ln.classList.toggle('done', slots.has(ln.dataset.seg));
      el.classList.toggle('fr-has-center', slots.has('center'));
      stage.style.setProperty('--fr-progress', String(slots.size / 9));
    },
    setNext(seg) {
      next = seg;
      for (const ln of ticks) ln.classList.toggle('next', !!seg && ln.dataset.seg === seg && !slots.has(seg));
      el.dataset.next = seg || '';
    },
    setLive(yaw, pitch) {   // anlık baş pozu (aynalı ekran koordinatı) — halka içinde küçük nokta
      if (yaw == null) { live.setAttribute('opacity', '0'); return; }
      const { sx, sy } = screenPose(yaw, pitch);
      const m = Math.min(1, Math.hypot(sx, sy) / 0.6);
      const ang = Math.atan2(sy, sx);
      live.setAttribute('cx', String(C + Math.cos(ang) * m * (R - 30)));
      live.setAttribute('cy', String(C - Math.sin(ang) * m * (R - 30)));
      live.setAttribute('opacity', '1');
    },
    setText(msg) { if (msg !== lastText) { lastText = msg; text.textContent = msg ? t(msg) : ''; text.classList.remove('fr-pop'); void text.offsetWidth; text.classList.add('fr-pop'); } },
    setHint(msg) { hint.textContent = msg ? t(msg) : ''; },
    noFace(on) { cam.classList.toggle('noface', !!on); },
    celebrate() { api.setState('ok'); api.setLive(null); api.setNext(null); for (const ln of ticks) ln.classList.add('done'); el.classList.add('fr-has-center'); },
    fail() { api.setState('err'); api.setLive(null); api.setNext(null); },
    destroy() { try { video.srcObject = null; } catch { /* */ } el.remove(); },
  };
  return api;
}

// ---------- kamera
export function cameraSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && (window.isSecureContext !== false);
}

export function cameraErrorText(err) {
  if (!cameraSupported()) return window.isSecureContext === false ? 'Kamera yalnızca güvenli (HTTPS) bağlantıda açılır' : 'Bu tarayıcı kamerayı desteklemiyor';
  const n = err && (err.name || '');
  if (n === 'NotAllowedError' || n === 'PermissionDeniedError' || n === 'SecurityError') return 'Kamera izni verilmedi. Tarayıcı adres çubuğundan kamera iznini açın';
  if (n === 'NotFoundError' || n === 'DevicesNotFoundError' || n === 'OverconstrainedError') return 'Bu cihazda kullanılabilir kamera bulunamadı';
  if (n === 'NotReadableError' || n === 'TrackStartError' || n === 'AbortError') return 'Kamera başka bir uygulama tarafından kullanılıyor';
  return (err && err.message) ? t('Kamera açılamadı: {msg}', { msg: err.message }) : 'Kamera açılamadı';
}

export async function openCamera(video) {
  if (!cameraSupported()) throw Object.assign(new Error('unsupported'), { name: 'NotSupportedError' });
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false });
  video.srcObject = stream;
  await video.play().catch(() => {});
  // ilk kare gelsin (videoWidth > 0) — en çok 3 sn bekle
  const t0 = Date.now();
  while (!video.videoWidth && Date.now() - t0 < 3000) await new Promise(r => setTimeout(r, 60));
  return stream;
}

// Kamerayı kapatır (izler durur, kamera ışığı söner, akış bırakılır). Son kare dairede DONUK kalır: kapatmadan önce
// video karesi yanındaki canvas'a çizilir (başarı/hata animasyonu siyah daire üstünde değil yüzün üstünde oynar).
export function closeCamera(video) {
  if (!video) return;
  try {
    const cam = video.parentElement;
    if (video.videoWidth && cam) {
      let cv = cam.querySelector('canvas.fr-freeze');
      if (!cv) { cv = document.createElement('canvas'); cv.className = 'fr-freeze'; cam.insertBefore(cv, video); }
      cv.width = video.videoWidth; cv.height = video.videoHeight;
      cv.getContext('2d').drawImage(video, 0, 0);
      cam.classList.add('frozen');
    }
  } catch { /* çizilemezse siyah kalır */ }
  const s = video.srcObject;
  if (s && s.getTracks) s.getTracks().forEach(tr => { try { tr.stop(); } catch { /* */ } });
  try { video.srcObject = null; } catch { /* */ }
}

// Kareyi küçültüp JPEG base64 (data: öneksiz) döndürür; video hazır değilse null
const grabCanvas = document.createElement('canvas');
export function grabFrame(video, maxW = 480, quality = 0.74) {
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh) return null;
  const scale = Math.min(1, maxW / vw);
  grabCanvas.width = Math.round(vw * scale); grabCanvas.height = Math.round(vh * scale);
  grabCanvas.getContext('2d').drawImage(video, 0, 0, grabCanvas.width, grabCanvas.height);
  return grabCanvas.toDataURL('image/jpeg', quality).split(',')[1];
}

// Periyodik kare döngüsü: her tur `fn(jpg)` (async) — önceki bitmeden yenisi başlamaz. {stop}
export function frameLoop(video, fn, { interval = 380 } = {}) {
  let stopped = false, busy = false, timer = null;
  const tick = async () => {
    if (stopped || busy) return;
    const jpg = grabFrame(video);
    if (!jpg) return;
    busy = true;
    try { await fn(jpg); } catch { /* fn kendi hatasını işler */ } finally { busy = false; }
  };
  timer = setInterval(tick, interval);
  return { stop() { stopped = true; clearInterval(timer); } };
}

// Yüz simgesi (Face ID benzeri, SVG) — düğme ve başlıklarda
export const faceIcon = (cls = '') => (ensureFaceStyle(), s('svg', { class: `fi-ico ${cls}`, width: 20, height: 20, viewBox: '0 0 24 24', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  s('path', { d: 'M3 8V6a3 3 0 0 1 3-3h2M16 3h2a3 3 0 0 1 3 3v2M21 16v2a3 3 0 0 1-3 3h-2M8 21H6a3 3 0 0 1-3-3v-2' }),
  s('path', { d: 'M8.5 9.5v1M15.5 9.5v1M12 9.5v4h-1.2M8.8 15.4a4.6 4.6 0 0 0 6.4 0' })));
