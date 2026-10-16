// Parçalı uçak haritası bileşeni. Geometri, ürünün sunucudaki şemasından (/api/products/{id}/plane) gelir.
import { closeTipPreview, tipPreview } from './gcode3d.js';
import { api, fileUrl } from './api.js';
import { fmtMinutes, h, pref, segmented, setPref } from './ui.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const planeCache = new Map();

export function loadPlane(productId) {
  const url = productId ? `/api/products/${productId}/plane` : '/api/plane';
  if (!planeCache.has(url)) planeCache.set(url, api.get(url).catch(err => { planeCache.delete(url); throw err; }));
  return planeCache.get(url);
}

const svgEl = (tag, attrs) => {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

const centroid = pts => pts.reduce((a, p) => [a[0] + p[0] / pts.length, a[1] + p[1] / pts.length], [0, 0]);

function inPoly([x, y], pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const edges = pts => pts.map((p, i) => [p, pts[(i + 1) % pts.length]]);

function segDist([px, py], [[x1, y1], [x2, y2]]) {
  const dx = x2 - x1, dy = y2 - y1;
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(px - x1 - t * dx, py - y1 - t * dy);
}

// Noktadan yatay (axis=0) veya dikey (axis=1) doğrultuda kenarlara kadar olan boş uzunluk.
function freeSpan(pt, segs, axis) {
  const o = 1 - axis;
  let lo = -Infinity, hi = Infinity;
  for (const [a, b] of segs) {
    if ((a[o] > pt[o]) === (b[o] > pt[o])) continue;
    const v = a[axis] + (pt[o] - a[o]) * (b[axis] - a[axis]) / (b[o] - a[o]);
    if (v <= pt[axis]) lo = Math.max(lo, v); else hi = Math.min(hi, v);
  }
  return hi - lo;
}

// Etiket konumu: parçanın içinde, kenarlardan ve üstüne binen parçalardan (kapak, elevon)
// yeterince uzak, merkeze en yakın nokta. Dar ve uzun boş alanlarda etiket dikey yazılır.
const CLEARANCE = 45;
function labelPlacement(part, overlays) {
  const pts = part.shapes[0].pts;
  if (part.label_at) return { pos: part.label_at, rotate: false };   // şema etiket yerini belirlemiş (yedek parça)
  if (part.group === 'cover' || part.group === 'spare') return { pos: centroid(pts), rotate: false };
  const blockers = overlays.filter(o => o.id !== part.id).flatMap(o => o.shapes.map(s => s.pts))
    .filter(cp => cp.some(p => inPoly(p, pts)));
  const segs = [...edges(pts), ...blockers.flatMap(edges)];
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const step = Math.max(3, Math.min(x1 - x0, y1 - y0) / 24);
  const [cx, cy] = centroid(pts);
  let best = [cx, cy], bestScore = -Infinity;
  for (let x = x0 + step / 2; x < x1; x += step) {
    for (let y = y0 + step / 2; y < y1; y += step) {
      if (!inPoly([x, y], pts) || blockers.some(b => inPoly([x, y], b))) continue;
      const d = Math.min(...segs.map(s => segDist([x, y], s)));
      const score = Math.min(d, CLEARANCE) * 1000 - Math.hypot(x - cx, y - cy);
      if (score > bestScore) { bestScore = score; best = [x, y]; }
    }
  }
  const w = freeSpan(best, segs, 0), hgt = freeSpan(best, segs, 1);
  return { pos: best, rotate: blockers.length > 0 && w < 90 && hgt > w * 1.5 };
}

let tipEl;
function tip() {
  tipEl ??= document.body.appendChild(h('div', { class: 'tip' }));
  return tipEl;
}
function moveTip(ev) {
  const t = tip(), pad = 14;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + t.offsetWidth > innerWidth) x = ev.clientX - t.offsetWidth - pad;
  if (y + t.offsetHeight > innerHeight) y = ev.clientY - t.offsetHeight - pad;
  t.style.left = `${x}px`;
  t.style.top = `${y}px`;
}
export function hideTip() {
  if (tipEl) tipEl.style.display = 'none';
  closeTipPreview();
}

/**
 * @param plane  /api/plane yanıtı
 * @param opts   fill(part), label(part) → metin|null, labelClass(part), tooltip(part) → satırlar, onClick(part)
 *               sections: true → sol kanat, sağ kanat ve orta gövde birbirinden ayrık çizilir;
 *               sectionState(bölüm) → 'ready' (montaja hazır) | 'done' (montajı bitti) | null: hazır / biten bölümün
 *               parçaları silik, etrafında çizgi; sectionLabel(bölüm) → satırlar (bölümün üstüne yazılır)
 */
export function renderPlane(plane, opts = {}) {
  const [x, y, w, hgt] = plane.viewBox;
  const explode = !!(opts.sections && plane.sections && Object.keys(plane.sections).length);
  const pad = explode ? 80 : 0;
  const svg = svgEl('svg', { viewBox: `${x - pad} ${y} ${w + 2 * pad} ${hgt}`, role: 'img', 'aria-label': 'CAYMAZ parça haritası' });
  const overlays = plane.parts.filter(p => p.group === 'cover' || p.group === 'elevon');
  const labels = svgEl('g', {});
  const items = new Map();
  // Bölüm grupları: her bölüm kendi kaydırmasıyla; önce kalın dış çizgi ve düz zemin, üstüne parçalar
  const secs = new Map();
  if (explode) {
    for (const key of [...Object.keys(plane.sections), '_']) {
      const list = plane.parts.filter(p => (p.section || '_') === key);
      if (!list.length) continue;
      const g = svgEl('g', { class: 'plane-sec', transform: `translate(${EXPLODE[key] || 0} 0)` });
      const box = { g, labels: svgEl('g', {}), text: null };
      if (key !== '_') {
        const shapes = list.filter(p => p.group !== 'cover').flatMap(p => p.shapes.map(sh => sh.pts.map(pt => pt.join(',')).join(' ')));
        shapes.forEach(pts => g.append(svgEl('polygon', { points: pts, class: 'sec-edge' })));
        shapes.forEach(pts => g.append(svgEl('polygon', { points: pts, class: 'sec-base' })));
        let ax = 0, ay = 0, at = 0;
        for (const p of list.filter(q => q.group !== 'cover')) for (const sh of p.shapes) {
          const [cx, cy] = centroid(sh.pts);
          const a = p.area / p.shapes.length;
          ax += cx * a; ay += cy * a; at += a;
        }
        const all = list.flatMap(p => p.shapes.flatMap(sh => sh.pts));
        const bw = Math.max(...all.map(q => q[0])) - Math.min(...all.map(q => q[0]));
        const bh = Math.max(...all.map(q => q[1])) - Math.min(...all.map(q => q[1]));
        box.text = svgEl('text', { x: ax / at, y: ay / at, class: 'sec-label' });
        if (bw < bh * 0.35) box.text.setAttribute('transform', `rotate(-90 ${ax / at} ${ay / at})`);
      }
      svg.append(g);
      secs.set(key, box);
    }
  }
  const holder = part => (explode ? secs.get(part.section || '_') : { g: svg, labels });

  for (const part of plane.parts) {
    const polys = [];
    const into = holder(part);
    if (part.image) {   // basılı ürün (Ürün Yönetimi): zeminde 2B üstten görünüm resmi; durum rengi üstte yarı saydam
      const xs = part.shapes[0].pts.map(q => q[0]), ys = part.shapes[0].pts.map(q => q[1]);
      const [x0, y0] = [Math.min(...xs), Math.min(...ys)];
      into.g.append(svgEl('image', { href: fileUrl(part.image, 900), x: x0, y: y0, width: Math.max(...xs) - x0, height: Math.max(...ys) - y0,
        preserveAspectRatio: 'xMidYMid meet', class: 'plane-img' }));
    }
    for (const shape of part.shapes) {
      const poly = svgEl('polygon', {
        points: shape.pts.map(p => p.join(',')).join(' '),
        class: `plane-part ${part.group === 'cover' ? 'cover' : ''} ${part.image ? 'has-img' : ''} layer-${part.layer || 'body'}`,
      });
      poly.dataset.id = part.id;
      into.g.append(poly);
      polys.push(poly);
      for (const [hx, hy, r] of shape.holes) into.g.append(svgEl('circle', { cx: hx, cy: hy, r, class: `plane-hole layer-${part.layer || 'body'}` }));
      for (const line of shape.inner || []) {   // çift çizgili kapaklarda iç hat
        into.g.append(svgEl('polygon', { points: line.map(q => q.join(',')).join(' '), class: `plane-inner layer-${part.layer || 'body'}` }));
      }
      for (const [sx, sy, sw, sh] of shape.slots) {
        into.g.append(svgEl('rect', { x: sx, y: sy, width: sw, height: sh, rx: Math.min(sw, sh) / 2, class: `plane-slot layer-${part.layer || 'body'}` }));
      }
    }
    const { pos: [lx, ly], rotate } = labelPlacement(part, overlays);
    const text = svgEl('text', { x: lx, y: ly, class: 'plane-label' });
    if (rotate) text.setAttribute('transform', `rotate(-90 ${lx} ${ly})`);
    into.labels.append(text);
    items.set(part.id, { part, polys, text });
  }
  if (explode) {
    for (const box of secs.values()) box.g.append(box.labels, ...(box.text ? [box.text] : []));
  } else {
    svg.append(labels);
  }

  const lines = (text, list, first, step) => text.replaceChildren(...list.map((line, i) => {
    const t = svgEl('tspan', { x: text.getAttribute('x'), dy: i ? step : `${-(list.length - 1) * first}em` });
    if (typeof line === 'object') { t.textContent = line.text; t.setAttribute('class', line.class || ''); } else t.textContent = line;
    return t;
  }));

  function update() {
    for (const { part, polys, text } of items.values()) {
      const fill = opts.fill ? opts.fill(part) : 'var(--part-fill)';
      polys.forEach(p => { p.style.fill = fill; });
      const small = part.area / part.shapes.length < 6000 || part.group === 'strake';
      const active = svg.dataset.layer === part.layer;   // kapak adları yalnızca kendi katmanı seçiliyken yazılır
      const label = opts.label ? opts.label(part)
        : part.group === 'cover' ? (active ? part.id.split('-') : null)
          : part.group === 'spare' ? (part.label_at ? part.id : null)   // çoklu baskı tablası: etiket yok
          : small ? null : part.name ? part.name.split(' ') : part.id;
      if (Array.isArray(label)) {
        // Çok satırlı etiket: satırlar merkez etrafında dikey ortalanır
        text.replaceChildren(...label.map((line, i) => {
          const t = svgEl('tspan', { x: text.getAttribute('x'), dy: i ? '1.1em' : `${-(label.length - 1) * 0.55}em` });
          if (typeof line === 'object') { t.textContent = line.text; t.setAttribute('class', line.class || ''); } else t.textContent = line;
          return t;
        }));
      } else {
        text.textContent = label ?? '';
      }
      text.setAttribute('class', `plane-label ${part.group === 'cover' ? 'cover-label' : ''} layer-${part.layer || 'body'} ${small ? 'small' : ''} ${opts.labelClass?.(part) || ''}`);
    }
    for (const [key, box] of secs) {
      if (key === '_') continue;
      const state = opts.sectionState?.(key) || '';
      box.g.setAttribute('class', `plane-sec ${state}`);
      lines(box.text, state && opts.sectionLabel ? opts.sectionLabel(key) : [], 0.62, '1.25em');
    }
  }
  update();

  const setHot = (id, on) => items.get(id)?.polys.forEach(p => p.classList.toggle('hot', on));
  svg.addEventListener('mouseover', ev => {
    const id = ev.target.dataset?.id;
    if (!id) return;
    setHot(id, true);
    if (opts.tooltip) {
      const t = tip();
      const part = items.get(id).part;
      t.replaceChildren(h('b', null, id), ...opts.tooltip(part).filter(Boolean).map(l => h('div', null, l)));
      t.style.display = 'block';
      if (part.gcode_preview && opts.preview3d !== false) tipPreview(t, part.gcode_preview);   // G-code'dan 3B parça
      moveTip(ev);
    }
  });
  svg.addEventListener('mousemove', ev => { if (tipEl?.style.display === 'block') moveTip(ev); });
  svg.addEventListener('mouseout', ev => {
    const id = ev.target.dataset?.id;
    if (!id) return;
    setHot(id, false);
    hideTip();
  });
  svg.addEventListener('click', ev => {
    const id = ev.target.dataset?.id;
    if (id && opts.onClick) {
      hideTip();
      opts.onClick(items.get(id).part);
    }
  });

  // Katman: 'body' (yalnızca gövde; kapak ve elektronik gizli) | 'cover' (kapaklar etkin) |
  // 'electronics' (elektronik kat ve K04 etkin) | null (hepsi). Seçilmeyen katmanlar silik ve tıklanamaz.
  const setLayer = layer => {
    if (layer) svg.dataset.layer = layer; else delete svg.dataset.layer;
    update();
  };
  // Şemada o an görünen dolgu renkleri (3B Montaj aynı renklerle çizer)
  const fills = () => {
    const m = new Map();
    for (const [id, { polys }] of items) {
      const p = polys[0];
      m.set(id, p ? (p.isConnected ? getComputedStyle(p).fill : p.style.fill) : null);
    }
    return m;
  };
  return { svg, update, setLayer, fills, plane };
}

// GÖVDE / KAPAK / ELEKTRONİK geçiş düğmeleri: seçilen katman kullanıcı tercihinde saklanır
const LAYERS = [['body', 'GÖVDE'], ['cover', 'KAPAK'], ['electronics', 'ELEKTRONİK']];
export function layerToggle(pl, key = 'plane.layer', plane = null) {
  if (plane && !plane.parts.some(p => p.layer && p.layer !== 'body')) { pl.setLayer(null); return null; }   // tek katmanlı şema
  const saved = pref(key, 'body');
  const start = LAYERS.some(l => l[0] === saved) ? saved : 'body';
  pl.setLayer(start);
  const asm = h('button', { class: 'btn asm3d-btn', type: 'button', title: 'Parçaları şemaya göre birleştirip uçağı 3B görün; patlatma ile ayırın',
    onclick: () => import('./assembly3d.js').then(m => m.openAssembly(plane || pl.plane, pl.fills())) },
  h('span', { class: 'asm3d-ico', 'aria-hidden': 'true' }, '◆'), '3B Montaj');
  return h('div', { class: 'layer-toggle' },
    segmented(LAYERS, start, v => { pl.setLayer(v); setPref(key, v); }), h('span', { class: 'spacer' }), asm);
}

export const SIDE_TEXT = { L: 'Sol', R: 'Sağ', M: 'Merkez', LR: 'Sol + Sağ' };

export function partInfoLines(part, groups) {
  return [
    `Grup: ${groups[part.group]}`,
    `Taraf: ${SIDE_TEXT[part.side]}`,
    part.parent ? `Ana parça: ${part.parent} – Part ${part.sub} (ayrı yazıcı)` : null,
    part.shapes.length > 1 ? `Adet: ${part.shapes.length} (tek yazıcıda tek baskı)` : null,
    part.hosts?.length ? `Bulunduğu parça: ${part.hosts.join(', ')}` : null,
    part.print_minutes ? `Baskı süresi: ${fmtMinutes(part.print_minutes)}` : null,
    part.print_file ? `Dosya: ${part.print_file}` : null,
  ];
}

/**
 * Montaj görünümü: parçalar görünmez; uçak montaj bölümleri (sol kanat, sağ kanat, orta gövde) ya da
 * tek bütün olarak çizilir. Bölümün çerçevesi durumuna göre sarı (bekliyor) ya da yeşildir (tamamlandı).
 * Kapaklar montajda uçağın içindedir, çizilmez.
 * @param opts  whole: true → tek parça uçak; items: {anahtar: {state: 'todo'|'done', label: [satırlar]}}
 *              (whole için anahtar 'ALL'), onClick(anahtar)
 */
const EXPLODE = { SOL_KANAT: -60, SAG_KANAT: 60, GOVDE: 0 };
export function renderAssembly(plane, opts) {
  const [x, y, w, hgt] = plane.viewBox;
  const pad = opts.whole ? 20 : 80;
  const svg = svgEl('svg', { viewBox: `${x - pad} ${y - 20} ${w + 2 * pad} ${hgt + 40}`, role: 'img', 'aria-label': 'Montaj görünümü' });
  const parts = plane.parts.filter(p => p.group !== 'cover' && p.layer !== 'electronics');
  const groups = opts.whole ? { ALL: parts } : Object.fromEntries(Object.keys(plane.sections).map(k => [k, parts.filter(p => p.section === k)]));
  const labels = [];
  for (const [key, list] of Object.entries(groups)) {
    const g = svgEl('g', { class: 'asm-sec', transform: `translate(${opts.whole ? 0 : EXPLODE[key] || 0} 0)` });
    g.dataset.sec = key;
    const shapes = list.flatMap(p => p.shapes.map(s => s.pts.map(pt => pt.join(',')).join(' ')));
    // Önce kalın kenar (dış çerçeve), üstüne dolgu: iç parça sınırları dolgunun altında kalır
    shapes.forEach(pts => g.append(svgEl('polygon', { points: pts, class: 'asm-edge' })));
    shapes.forEach(pts => g.append(svgEl('polygon', { points: pts, class: 'asm-fill' })));
    let ax = 0, ay = 0, at = 0;
    for (const p of list) for (const s of p.shapes) {
      const [cx, cy] = centroid(s.pts);
      const a = p.area / p.shapes.length;
      ax += cx * a; ay += cy * a; at += a;
    }
    const text = svgEl('text', { x: ax / at, y: ay / at, class: 'asm-label' });
    const all = list.flatMap(p => p.shapes.flatMap(s => s.pts));
    const bw = Math.max(...all.map(q => q[0])) - Math.min(...all.map(q => q[0]));
    const bh = Math.max(...all.map(q => q[1])) - Math.min(...all.map(q => q[1]));
    if (bw < bh * 0.35) text.setAttribute('transform', `rotate(-90 ${ax / at} ${ay / at})`);   // dar gövde: dikey yazı
    g.append(text);
    labels.push([key, g, text]);
    g.addEventListener('click', () => opts.onClick?.(key));
    svg.append(g);
  }
  // Elektronik yarı mamulü (elektronik kat + K04 kapağı): montaj bölümlerinde uçağın yanında ayrı, çerçeveli
  // dördüncü yapı olarak çizilir; parçalar alt alta dizilir. Tek parça uçakta (whole) çizilmez.
  // En büyük parça (elektronik kat) yerinde kalır, diğerleri (K04) onun altına dizilir
  const elecParts = opts.extra ? plane.parts.filter(p => p.layer === 'electronics').sort((a, b) => b.area - a.area) : [];
  const bbox = pts => [Math.min(...pts.map(q => q[0])), Math.min(...pts.map(q => q[1])), Math.max(...pts.map(q => q[0])), Math.max(...pts.map(q => q[1]))];
  const shift = new Map();
  if (!opts.whole && elecParts.length) {
    const boxes = elecParts.map(p => bbox(p.shapes.flatMap(sh => sh.pts)));
    const [ax0, ay0, ax1, ay1] = boxes[0];
    const cx = (ax0 + ax1) / 2;
    let top = ay1 + 40;
    boxes.forEach((b, i) => {
      if (!i) { shift.set(elecParts[i].id, [0, 0]); return; }
      shift.set(elecParts[i].id, [cx - (b[0] + b[2]) / 2, top - b[1]]);
      top += b[3] - b[1] + 40;
    });
    const moved = boxes.map((b, i) => { const [dx, dy] = shift.get(elecParts[i].id); return [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]; });
    const pad = 30;
    const fx0 = Math.min(...moved.map(b => b[0])) - pad, fy0 = Math.min(...moved.map(b => b[1])) - pad;
    const fx1 = Math.max(...moved.map(b => b[2])) + pad, fy1 = Math.max(...moved.map(b => b[3])) + pad;
    const frame = `${fx0},${fy0} ${fx1},${fy0} ${fx1},${fy1} ${fx0},${fy1}`;
    const g = svgEl('g', { class: 'asm-sec asm-elec' });
    g.append(svgEl('polygon', { points: frame, class: 'asm-edge' }), svgEl('polygon', { points: frame, class: 'asm-fill' }));
    const text = svgEl('text', { x: (fx0 + fx1) / 2, y: fy1 + 110, class: 'asm-label' });
    g.append(text);
    labels.push(['ELEKTRONIK', g, text]);
    if (opts.onElecClick) g.addEventListener('click', () => opts.onElecClick());
    svg.append(g);
  }
  // Uçağın dışında ayrı çizilen parçalar (elektronik kat): kendi üretim durumu rengiyle, tıklanabilir
  const extras = elecParts.map(part => {
    const [dx, dy] = shift.get(part.id) || [0, 0];
    const g = svgEl('g', { class: 'asm-extra', transform: `translate(${dx} ${dy})` });
    const polys = part.shapes.map(sh => svgEl('polygon', { points: sh.pts.map(q => q.join(',')).join(' '), class: 'plane-part' }));
    const [cx, cy] = centroid(part.shapes[0].pts);
    const text = svgEl('text', { x: cx, y: cy, class: 'asm-label extra' });
    g.append(...polys, text);
    g.addEventListener('click', () => opts.extra.onClick?.(part));
    svg.append(g);
    return { part, polys, text, g };
  });
  function update(items) {
    opts.items = items || opts.items;
    for (const { part, polys, text, g } of extras) {
      polys.forEach(p => { p.style.fill = opts.extra.fill(part); });
      g.classList.toggle('clickable', !!opts.extra.clickable?.(part));
      const lines = opts.extra.label(part);
      text.replaceChildren(...lines.map((line, i) => {
        const t = svgEl('tspan', { x: text.getAttribute('x'), dy: i ? '1.2em' : `${-(lines.length - 1) * 0.6}em` });
        t.textContent = typeof line === 'object' ? line.text : line;
        if (typeof line === 'object') t.setAttribute('class', line.class || '');
        return t;
      }));
    }
    for (const [key, g, text] of labels) {
      const it = opts.items[key] || {};
      const elec = key === 'ELEKTRONIK';   // çerçeve; tıklama içindeki parçalarda
      g.setAttribute('class', `asm-sec ${elec ? 'asm-elec' : ''} ${it.state || 'todo'} ${(elec ? opts.onElecClick : opts.onClick) && it.clickable !== false ? 'clickable' : ''}`);
      const lines = it.label || [];
      text.replaceChildren(...lines.map((line, i) => {
        const t = svgEl('tspan', { x: text.getAttribute('x'), dy: i ? '1.25em' : `${-(lines.length - 1) * 0.62}em` });
        t.textContent = typeof line === 'object' ? line.text : line;
        if (typeof line === 'object') t.setAttribute('class', line.class || '');
        return t;
      }));
    }
  }
  update();
  return { svg, update };
}
