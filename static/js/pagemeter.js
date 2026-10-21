// Altbilgi sayfa ölçeri: girilen sayfa (hash rotası) için giriş saati, geçen süre, anlık indirme hızı ve girişten beri indirilen miktar.
// Kaynaklar: PerformanceObserver 'resource' girdileri (fetch/XHR/görsel/betik — transferSize; önbellekten gelen 0 bayttır,
// başka kökenden Timing-Allow-Origin'siz gelen boyutu tarayıcı gizler → encodedBodySize, o da 0 ise sayılmaz) + WebSocket ile gelen
// iletiler (WebSocket kurucusu sarmalanır; metin UTF-8 bayt, ikili byteLength). Sayfa = hash yolu (sorgu hariç); yol değişince sayaçlar sıfırlanır.
import { h, t as tr } from './ui.js';

const PATH = () => (location.hash || '#/').split('?')[0] || '#/';
const listeners = new Set();
let wsWrapped = false;

function emit(bytes) {
  if (!(bytes > 0)) return;
  const at = performance.now();
  for (const fn of listeners) fn(bytes, at);
}

function wrapWebSocket() {
  if (wsWrapped || typeof window.WebSocket !== 'function') return;
  wsWrapped = true;
  const Native = window.WebSocket;
  const enc = typeof TextEncoder === 'function' ? new TextEncoder() : null;
  const size = d => (typeof d === 'string' ? (enc ? enc.encode(d).length : d.length) : d instanceof Blob ? d.size : d?.byteLength || 0);
  function Wrapped(...args) {
    const ws = new Native(...args);
    ws.addEventListener('message', e => emit(size(e.data)));
    return ws;
  }
  Wrapped.prototype = Native.prototype;
  for (const k of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) Wrapped[k] = Native[k];
  window.WebSocket = Wrapped;
}

let observing = false;
function observeResources() {
  if (observing || typeof PerformanceObserver !== 'function') return;
  observing = true;
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) emit(e.transferSize || e.encodedBodySize || 0);
    }).observe({ type: 'resource', buffered: false });
  } catch { /* eski tarayıcı */ }
}

export const fmtBytes = b => {
  if (!(b > 0)) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b < 10 && i ? b.toFixed(1) : Math.round(b)} ${u[i]}`;
};
export const fmtElapsed = s => {
  s = Math.max(0, Math.floor(s));
  const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = s % 60;
  const p = n => String(n).padStart(2, '0');
  return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
};
const fmtClock = d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function pageMeter() {
  wrapWebSocket();
  observeResources();
  let path = PATH(), entered = new Date(), total = 0, recent = [];
  const since = h('b', { class: 'pm-v' }), elapsed = h('b', { class: 'pm-v' }), rate = h('b', { class: 'pm-v' }), sum = h('b', { class: 'pm-v' });
  // Simgeler satır içi SVG (emoji yazı tipi olmayan sistemlerde kare görünmesin)
  const icon = d => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'pm-i'); svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = d;
    return svg;
  };
  const ICON = {
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    timer: '<circle cx="12" cy="13" r="8"/><path d="M12 13V9M9 2h6M12 2v3"/>',
    down: '<path d="M12 4v13M6 11l6 6 6-6M5 21h14"/>',
    sum: '<path d="M17 5H7l6 7-6 7h10"/>',
  };
  const item = (ic, el, title) => h('span', { class: 'pm-item', title }, icon(ICON[ic]), el);
  const bar = h('div', { class: 'pagemeter', role: 'status', 'aria-live': 'off' },
    item('clock', since, tr('Bu sayfaya giriş saati')),
    item('timer', elapsed, tr('Bu sayfada geçen süre')),
    item('down', rate, tr('Bu sayfanın anlık indirme hızı (son 2 sn)')),
    item('sum', sum, tr('Bu sayfaya girildiğinden beri indirilen veri')));
  const reset = () => { path = PATH(); entered = new Date(); total = 0; recent = []; draw(); };
  const onBytes = (b, at) => { total += b; recent.push([at, b]); };
  const draw = () => {
    const now = performance.now();
    recent = recent.filter(([at]) => now - at <= 2000);
    const bps = recent.reduce((a, [, b]) => a + b, 0) / 2;
    since.textContent = fmtClock(entered);
    elapsed.textContent = fmtElapsed((Date.now() - entered.getTime()) / 1000);
    rate.textContent = `${fmtBytes(bps)}/s`;
    sum.textContent = fmtBytes(total);
  };
  listeners.add(onBytes);
  const onHash = () => { if (PATH() !== path) reset(); };
  window.addEventListener('hashchange', onHash);
  const timer = setInterval(() => {
    if (!bar.isConnected && document.readyState === 'complete' && bar._mounted) {   // kabuk yeniden çizildi: temizle
      clearInterval(timer); listeners.delete(onBytes); window.removeEventListener('hashchange', onHash); return;
    }
    if (bar.isConnected) bar._mounted = true;
    draw();
  }, 1000);
  draw();
  return bar;
}

// Modül yüklenir yüklenmez (app.js en üstte içe aktarır): sonradan açılan WebSocket'ler ve kaynaklar da sayılsın
wrapWebSocket();
observeResources();
