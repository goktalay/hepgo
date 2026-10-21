// Bağımlılıksız SVG grafikler: zaman serisi çizgi grafiği ve uçuş izi haritası (ekran ve baskı için).
import { h } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, text) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
};

function niceStep(range, target) {
  const raw = range / Math.max(1, target);
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

export const clock = t => {
  t = Math.max(0, Math.round(t || 0));
  const hh = Math.floor(t / 3600), mm = Math.floor(t % 3600 / 60), ss = t % 60;
  const p = n => String(n).padStart(2, '0');
  return hh ? `${hh}:${p(mm)}:${p(ss)}` : `${p(mm)}:${p(ss)}`;
};

/**
 * @param o { title, unit, series: [{label, color, data: [[t, v]], dash}], thresholds: [{value, color, label}],
 *            bands: [[t0, t1]] (uçuş aralıkları gölgesi), height }
 */
export function lineChart(o) {
  const W = 520, H = o.height || 190, L = 44, R = 10, T = 10, B = 24;
  const all = o.series.flatMap(s => s.data).filter(p => p[1] !== null && p[1] !== undefined);
  const wrap = h('figure', { class: 'chart' }, h('figcaption', null, o.title,
    o.unit ? h('span', { class: 'unit' }, ` (${o.unit})`) : null));
  if (!all.length) {
    wrap.append(h('div', { class: 'chart-empty' }, o.empty || 'Logda bu veri yok'));
    return wrap;
  }
  let t0 = Math.min(...all.map(p => p[0])), t1 = Math.max(...all.map(p => p[0]));
  let v0 = Math.min(...all.map(p => p[1])), v1 = Math.max(...all.map(p => p[1]));
  for (const th of o.thresholds || []) { v0 = Math.min(v0, th.value); v1 = Math.max(v1, th.value); }
  if (o.zero !== false) v0 = Math.min(v0, 0);
  if (v1 === v0) { v1 += 1; v0 -= o.zero === false ? 1 : 0; }
  if (t1 === t0) t1 += 1;
  const vs = niceStep(v1 - v0, 4);
  v0 = Math.floor(v0 / vs) * vs;
  v1 = Math.ceil(v1 / vs) * vs;
  const x = t => L + (t - t0) / (t1 - t0) * (W - L - R);
  const y = v => T + (1 - (v - v0) / (v1 - v0)) * (H - T - B);

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img', 'aria-label': o.title });
  for (const [a, b] of o.bands || []) {
    svg.append(el('rect', { x: x(Math.max(a, t0)), y: T, width: Math.max(0, x(Math.min(b, t1)) - x(Math.max(a, t0))),
      height: H - T - B, class: 'chart-band' }));
  }
  for (let v = v0; v <= v1 + vs / 2; v += vs) {
    svg.append(el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'chart-grid' }));
    svg.append(el('text', { x: L - 5, y: y(v) + 3.5, class: 'chart-tick', 'text-anchor': 'end' },
      Math.abs(vs) < 1 ? v.toFixed(1) : Math.round(v)));
  }
  const ts = niceStep(t1 - t0, 6);
  for (let t = Math.ceil(t0 / ts) * ts; t <= t1; t += ts) {
    svg.append(el('line', { x1: x(t), x2: x(t), y1: H - B, y2: H - B + 4, class: 'chart-axis' }));
    svg.append(el('text', { x: x(t), y: H - 7, class: 'chart-tick', 'text-anchor': 'middle' }, clock(t)));
  }
  svg.append(el('line', { x1: L, x2: W - R, y1: H - B, y2: H - B, class: 'chart-axis' }));
  for (const th of o.thresholds || []) {
    svg.append(el('line', { x1: L, x2: W - R, y1: y(th.value), y2: y(th.value), stroke: th.color, class: 'chart-thr' }));
    svg.append(el('text', { x: W - R - 2, y: y(th.value) - 3, fill: th.color, class: 'chart-tick', 'text-anchor': 'end' }, th.label));
  }
  for (const s of o.series) {
    const pts = s.data.filter(p => p[1] !== null && p[1] !== undefined);
    if (!pts.length) continue;
    svg.append(el('polyline', {
      points: pts.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' '),
      fill: 'none', stroke: s.color, 'stroke-width': s.width || 1.4, 'stroke-dasharray': s.dash || '',
      'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke',
    }));
  }
  wrap.append(svg);
  if (o.series.length > 1) {
    wrap.append(h('div', { class: 'chart-legend' }, o.series.map(s =>
      h('span', null, h('i', { style: { background: s.color } }), s.label))));
  }
  return wrap;
}

/** Uçuş izi: yerel metrik izdüşüm, havada/yerde ayrımı, kalkış/bitiş/ev işaretleri, ölçek ve kuzey oku. */
export function trackMap(track, home, { height = 330, empty } = {}) {
  const W = 520, H = height, P = 22;
  const wrap = h('figure', { class: 'chart track' }, h('figcaption', null, 'Uçuş izi'));
  if (!track?.length) {
    wrap.append(h('div', { class: 'chart-empty' }, empty || 'Logda GPS konumu yok'));
    return wrap;
  }
  const lat0 = track[0][0], lng0 = track[0][1];
  const kx = Math.cos(lat0 * Math.PI / 180) * 111320, ky = 110540;
  const pts = track.map(([la, ln, air]) => [(ln - lng0) * kx, (la - lat0) * ky, air]);
  const hm = home ? [(home.lng - lng0) * kx, (home.lat - lat0) * ky] : null;
  const xs = pts.map(p => p[0]).concat(hm ? [hm[0]] : []), ys = pts.map(p => p[1]).concat(hm ? [hm[1]] : []);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(maxX - minX, maxY - minY, 20);
  const sc = Math.min((W - 2 * P) / Math.max(maxX - minX, 1e-6), (H - 2 * P) / Math.max(maxY - minY, 1e-6), (W - 2 * P) / 20);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const X = v => W / 2 + (v - cx) * sc, Y = v => H / 2 - (v - cy) * sc;

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg map-svg', role: 'img', 'aria-label': 'Uçuş izi' });
  svg.append(el('rect', { x: 0, y: 0, width: W, height: H, class: 'map-bg' }));
  const gstep = niceStep(span, 5);
  for (let g = Math.floor(minX / gstep) * gstep; g <= maxX + gstep; g += gstep) {
    svg.append(el('line', { x1: X(g), x2: X(g), y1: 0, y2: H, class: 'map-grid' }));
  }
  for (let g = Math.floor(minY / gstep) * gstep; g <= maxY + gstep; g += gstep) {
    svg.append(el('line', { x1: 0, x2: W, y1: Y(g), y2: Y(g), class: 'map-grid' }));
  }
  // Havada / yerde bölümlerini ayrı çiz
  let seg = [], air = pts[0][2];
  const flush = () => {
    if (seg.length > 1) {
      svg.append(el('polyline', { points: seg.map(p => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' '),
        class: air ? 'map-air' : 'map-ground' }));
    }
  };
  for (const p of pts) {
    if (p[2] !== air) { seg.push(p); flush(); seg = [p]; air = p[2]; } else seg.push(p);
  }
  flush();
  const s = pts[0], e = pts[pts.length - 1];
  if (hm) {
    svg.append(el('circle', { cx: X(hm[0]), cy: Y(hm[1]), r: 7, class: 'map-home' }));
    svg.append(el('text', { x: X(hm[0]), y: Y(hm[1]) + 3.5, class: 'map-home-t', 'text-anchor': 'middle' }, 'H'));
  }
  svg.append(el('circle', { cx: X(s[0]), cy: Y(s[1]), r: 4.5, class: 'map-start' }));
  svg.append(el('rect', { x: X(e[0]) - 4, y: Y(e[1]) - 4, width: 8, height: 8, class: 'map-end' }));
  // Ölçek çubuğu
  const target = (W * 0.22) / sc;
  const bar = niceStep(target, 1);
  svg.append(el('line', { x1: P, x2: P + bar * sc, y1: H - P + 8, y2: H - P + 8, class: 'map-scale' }));
  svg.append(el('text', { x: P, y: H - P + 2, class: 'chart-tick' }, bar >= 1000 ? `${bar / 1000} km` : `${bar} m`));
  // Kuzey oku
  svg.append(el('path', { d: `M${W - 22},${P + 14} l7,-18 l7,18 l-7,-5 z`, class: 'map-north' }));
  svg.append(el('text', { x: W - 15, y: P + 26, class: 'chart-tick', 'text-anchor': 'middle' }, 'K'));
  wrap.append(svg, h('div', { class: 'chart-legend' },
    h('span', null, h('i', { class: 'lg-air' }), 'Havada'),
    h('span', null, h('i', { class: 'lg-ground' }), 'Yerde'),
    h('span', null, h('i', { class: 'lg-start' }), 'Başlangıç'),
    h('span', null, h('i', { class: 'lg-end' }), 'Bitiş'),
    hm ? h('span', null, h('i', { class: 'lg-home' }), 'Ev (kalkış noktası)') : null));
  return wrap;
}
