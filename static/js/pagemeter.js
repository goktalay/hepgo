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

// Zaman çizelgesi: saniyelik hız örnekleri → SVG alan grafiği (n > 300 ise en çok 300 noktaya ortalanarak seyreltilir)
export function timelinePoints(samples, w, hgt, maxPts = 300) {
  if (!samples.length) return { pts: [], max: 0 };
  const step = Math.max(1, Math.ceil(samples.length / maxPts));
  const agg = [];
  for (let k = 0; k < samples.length; k += step) {
    const part = samples.slice(k, k + step);
    agg.push(part.reduce((a, b) => a + b, 0) / part.length);
  }
  const max = Math.max(...agg, 1);
  const dx = agg.length > 1 ? w / (agg.length - 1) : 0;
  return { pts: agg.map((v, k) => [k * dx, hgt - 1 - (v / max) * (hgt - 4)]), max };
}

export function pageMeter() {
  wrapWebSocket();
  observeResources();
  const NS = 'http://www.w3.org/2000/svg';
  const hover = window.matchMedia?.('(hover: hover) and (pointer: fine)').matches;
  let path = PATH(), entered = new Date(), total = 0, recent = [], samples = [], secBytes = 0, peak = 0, pop = null, closeTimer = null;
  const icon = d => { const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'pm-i'); svg.setAttribute('aria-hidden', 'true'); svg.innerHTML = d; return svg; };
  const sum = h('b', { class: 'pm-v' });
  // Altbilgide yalnız toplam indirilen; üzerine gelince (dokunmatikte dokununca) yukarı kayan ayrıntı paneli
  const bar = h('button', { type: 'button', class: 'pagemeter sb-hot', 'aria-haspopup': 'dialog', 'aria-label': tr('Bu sayfaya girildiğinden beri indirilen veri') },
    icon('<path d="M12 4v13M6 11l6 6 6-6M5 21h14"/>'), sum);
  const W = 268, HH = 70;
  const chart = document.createElementNS(NS, 'svg');
  chart.setAttribute('viewBox', `0 0 ${W} ${HH}`); chart.setAttribute('class', 'pm-chart'); chart.setAttribute('preserveAspectRatio', 'none');
  const area = document.createElementNS(NS, 'path'), line = document.createElementNS(NS, 'polyline');
  area.setAttribute('class', 'pm-area'); line.setAttribute('class', 'pm-line'); chart.append(area, line);
  const v = () => h('dd');
  const kv = { since: v(), elapsed: v(), rate: v(), avg: v(), peak: v() };
  const big = h('b'), maxLbl = h('span', { class: 'pm-ax' }), t0Lbl = h('span', { class: 'pm-ax' }), t1Lbl = h('span', { class: 'pm-ax' });
  const close = () => { if (!pop) return; pop.remove(); pop = null; bar.classList.remove('open'); };
  const open = pinned => {
    if (pop) { pop.pinned ||= pinned; return; }
    pop = h('div', { class: 'sb-pop pm-pop', role: 'dialog', onclick: e => e.stopPropagation(),
      onmouseenter: () => clearTimeout(closeTimer), onmouseleave: () => { if (hover && !pop?.pinned) closeTimer = setTimeout(close, 300); } },
      h('div', { class: 'sbp-head' }, h('b', null, tr('Sayfa trafiği')), h('button', { type: 'button', class: 'sbp-x', title: tr('Kapat'), onclick: close }, '×')),
      h('div', { class: 'sbp-body' },
        h('div', { class: 'sbp-big' }, big, h('span', null, tr('indirildi'))),
        h('div', { class: 'pm-chartbox' }, maxLbl, chart, h('div', { class: 'pm-axis' }, t0Lbl, t1Lbl)),
        h('dl', { class: 'sbp-kv' },
          h('dt', null, tr('Giriş saati')), kv.since, h('dt', null, tr('Geçen süre')), kv.elapsed,
          h('dt', null, tr('Anlık hız')), kv.rate, h('dt', null, tr('Ortalama hız')), kv.avg, h('dt', null, tr('En yüksek hız')), kv.peak)));
    pop.pinned = pinned;
    document.body.append(pop);
    const r = bar.getBoundingClientRect();
    pop.style.bottom = `${innerHeight - r.top + 8}px`;
    pop.style.right = `${Math.max(8, Math.min(innerWidth - r.right - 10, innerWidth - pop.offsetWidth - 8))}px`;
    bar.classList.add('open');
    draw();
  };
  bar.addEventListener('click', e => { e.stopPropagation(); if (pop?.pinned) close(); else open(true); });
  if (hover) {
    bar.addEventListener('mouseenter', () => { clearTimeout(closeTimer); open(false); });
    bar.addEventListener('mouseleave', () => { if (!pop?.pinned) closeTimer = setTimeout(close, 300); });
  }
  const onDoc = () => close(), onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('click', onDoc);
  document.addEventListener('keydown', onKey);
  const reset = () => { path = PATH(); entered = new Date(); total = 0; recent = []; samples = []; secBytes = 0; peak = 0; draw(); };
  const onBytes = (b, at) => { total += b; secBytes += b; recent.push([at, b]); };
  const draw = () => {
    const now = performance.now();
    recent = recent.filter(([at]) => now - at <= 2000);
    const bps = recent.reduce((a, [, b]) => a + b, 0) / 2;
    const secs = (Date.now() - entered.getTime()) / 1000;
    sum.textContent = fmtBytes(total);
    if (!pop) return;
    big.textContent = fmtBytes(total);
    kv.since.textContent = fmtClock(entered);
    kv.elapsed.textContent = fmtElapsed(secs);
    kv.rate.textContent = `${fmtBytes(bps)}/s`;
    kv.avg.textContent = `${fmtBytes(secs > 0 ? total / secs : 0)}/s`;
    kv.peak.textContent = `${fmtBytes(peak)}/s`;
    const { pts, max } = timelinePoints(samples, W, HH);
    const str = pts.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
    line.setAttribute('points', str);
    area.setAttribute('d', pts.length ? `M${pts[0][0]},${HH} L${str.replaceAll(' ', ' L')} L${pts[pts.length - 1][0]},${HH}Z` : '');
    maxLbl.textContent = `${fmtBytes(max)}/s`;
    t0Lbl.textContent = fmtClock(entered);
    t1Lbl.textContent = fmtClock(new Date());
  };
  listeners.add(onBytes);
  const onHash = () => { close(); if (PATH() !== path) reset(); };
  window.addEventListener('hashchange', onHash);
  const timer = setInterval(() => {
    if (!bar.isConnected && bar._mounted) {   // kabuk yeniden çizildi: temizle
      clearInterval(timer); listeners.delete(onBytes); close();
      window.removeEventListener('hashchange', onHash); document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey); return;
    }
    if (bar.isConnected) bar._mounted = true;
    samples.push(secBytes); peak = Math.max(peak, secBytes); secBytes = 0;   // saniyelik zaman çizelgesi örneği
    if (samples.length > 7200) samples.splice(0, samples.length - 7200);      // en çok 2 saat
    draw();
  }, 1000);
  draw();
  return bar;
}

// Modül yüklenir yüklenmez (app.js en üstte içe aktarır): sonradan açılan WebSocket'ler ve kaynaklar da sayılsın
wrapWebSocket();
observeResources();
