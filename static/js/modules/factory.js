// Fabrika (fabrika dijital ikizi) modülü — 2D çok katlı kat planı editörü + personel/kamera yerleşimi +
// yüz tanıma görülmelerinden otomatik personel hareketi çizimi.
//
// İki mod (toolbar ile geçiş):
//   "Düzen"   → SVG tuval üzerinde kat / oda (serbest poligon) / kamera (+ görüş yönü) / merdiven tasarımı.
//   "Hareket" → bir kişi + tarih aralığı seçilir; /movement ile yolu çizilir (numaralı oda-oda iz + oklar +
//               zaman damgaları, çok katlı geçişler), bir oynatma (timeline) ile hareketli nokta canlandırılır;
//               ayrıca "Şu an" canlı görünümü (/now her 10 sn) odalardaki kişileri vurgular.
//
// Yeniden kullanım: NVR kameraları /api/factory/available-cameras (mevcut kamera yolu), yüz görülmeleri
// /api/factory/movement ve /api/factory/now (mevcut events/recent yolu) üzerinden gelir; kişi seçici
// /api/faces/people (mevcut yüz atama seçicisi) ile doldurulur.
import { api, fileUrl } from '../api.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, h, modal, moduleToolbar, onLeave, pageHead,
  segmented, toast, toastError,
} from '../ui.js';

const NS = 'http://www.w3.org/2000/svg';
// SVG düğümü üretici (ui.js'nin h()'i HTML createElement kullanır; SVG için ayrı NS gerekir).
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ROOM_COLORS = ['#60a5fa', '#34d399', '#f59e0b', '#f472b6', '#a78bfa', '#f87171', '#22d3ee', '#a3e635'];
// Poligon ağırlık merkezi (etiket + iz konumu). Dejenere poligonlarda ortalama noktaya düşer.
function centroid(points) {
  if (!points || !points.length) return { x: 0, y: 0 };
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i], [x2, y2] = points[(i + 1) % points.length];
    const f = x1 * y2 - x2 * y1;
    a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f;
  }
  if (Math.abs(a) < 1e-6) {   // alanı sıfır → köşe ortalaması
    const sx = points.reduce((t, p) => t + p[0], 0), sy = points.reduce((t, p) => t + p[1], 0);
    return { x: sx / points.length, y: sy / points.length };
  }
  a *= 0.5;
  return { x: cx / (6 * a), y: cy / (6 * a) };
}
// Nokta poligon içinde mi (ışın atma) — kamerayı bulunduğu odaya otomatik bağlamak için.
function pointInPoly(px, py, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if (((yi > py) !== (yj > py)) && (px < ((xj - xi) * (py - yi)) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
}
const fmtT = iso => (iso ? fmtDateTime(iso) : '—');

export async function render(view, params, ctx) {
  // -------------------------------------------------------------------- durum
  const st = {
    mode: 'edit',                 // 'edit' | 'move'
    tool: 'select',               // edit altı: 'select' | 'room' | 'camera' | 'stair'
    floors: [], floorId: null,
    rooms: [], cams: [], stairs: [], markers: [], avail: [],
    sel: null,                    // {type:'room'|'cam'|'stair', id}
    draft: null,                  // çizilmekte olan oda köşeleri [[x,y],...]
    cam: { scale: 1, panX: 60, panY: 60 },   // tuval görünümü (pan/zoom)
    // hareket modu
    people: null, subject: null,  // subject: {type,id,name}
    move: null,                   // /movement yanıtı
    live: false, liveTimer: null, liveData: null,
    play: { t: 0, playing: false, raf: null },
  };

  // -------------------------------------------------------------------- iskelet DOM
  const svg = s('svg', { class: 'fab-svg', xmlns: NS });
  const world = s('g', { class: 'fab-world' });
  const gGrid = s('g'), gStatic = s('g'), gOverlay = s('g');
  world.append(gGrid, gStatic, gOverlay);
  svg.append(world);
  const stage = h('div', { class: 'fab-stage' }, svg);
  const side = h('div', { class: 'fab-side' });   // sağ panel (araç/özellik/hareket)
  const floorBar = h('div', { class: 'fab-floors' });
  const hint = h('div', { class: 'fab-hint' });
  const wrap = h('div', { class: 'fab-wrap' }, h('div', { class: 'fab-main' }, floorBar, stage, hint), side);

  injectStyle();

  // -------------------------------------------------------------------- tuval dönüşümü
  const applyCam = () => world.setAttribute('transform', `translate(${st.cam.panX} ${st.cam.panY}) scale(${st.cam.scale})`);
  const toWorld = (clientX, clientY) => {
    const r = svg.getBoundingClientRect();
    return { x: (clientX - r.left - st.cam.panX) / st.cam.scale, y: (clientY - r.top - st.cam.panY) / st.cam.scale };
  };

  // -------------------------------------------------------------------- veri yükleme
  const loadFloors = async () => {
    st.floors = await api.get('/api/factory/floors');
    if (!st.floors.length) { st.floorId = null; return; }
    if (!st.floors.some(f => f.id === st.floorId)) st.floorId = st.floors[0].id;
  };
  const loadFloorData = async () => {
    if (!st.floorId) { st.rooms = []; st.cams = []; st.stairs = []; st.markers = []; return; }
    const [rooms, cams, stairs, markers] = await Promise.all([
      api.get(`/api/factory/rooms?floor=${st.floorId}`),
      api.get(`/api/factory/cameras?floor=${st.floorId}`),
      api.get(`/api/factory/stairs?floor=${st.floorId}`),
      api.get(`/api/factory/markers?floor=${st.floorId}`),
    ]);
    st.rooms = rooms; st.cams = cams; st.stairs = stairs; st.markers = markers;
  };
  const loadAvail = async () => { st.avail = await api.get('/api/factory/available-cameras').catch(() => []); };

  const reload = async () => { await loadFloors(); await loadFloorData(); drawFloorBar(); drawCanvas(); drawSide(); };

  // ==================================================================== ÇİZİM: kat sekmeleri
  function drawFloorBar() {
    const tabs = st.floors.map(f => h('button', {
      class: `fab-floor ${f.id === st.floorId ? 'on' : ''}`, type: 'button',
      onclick: async () => { st.floorId = f.id; st.sel = null; st.draft = null; await loadFloorData(); drawCanvas(); drawSide(); drawFloorBar(); },
      ondblclick: () => renameFloor(f),
    }, f.name));
    const add = h('button', { class: 'fab-floor add', type: 'button', title: 'Kat ekle', onclick: addFloor }, '+ Kat');
    clear(floorBar, h('span', { class: 'fab-floors-lbl' }, 'Katlar:'), tabs, add,
      st.floors.length ? h('button', { class: 'btn ghost sm', type: 'button', onclick: reorderFloors }, 'Sırala') : null,
      st.floorId ? h('button', { class: 'btn ghost sm danger', type: 'button', onclick: () => delFloor(st.floorId) }, 'Katı Sil') : null);
  }
  async function addFloor() {
    const name = h('input', { class: 'input', value: `Kat ${st.floors.length + 1}` });
    modal({
      title: 'Yeni kat', body: field('Kat adı', name),
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
        const f = await api.post('/api/factory/floors', { name: name.value.trim() || 'Kat' });
        st.floorId = f.id; await reload(); toast('Kat eklendi');
      } }],
    });
  }
  function renameFloor(f) {
    const name = h('input', { class: 'input', value: f.name });
    modal({ title: 'Katı yeniden adlandır', body: field('Kat adı', name),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        await api.patch(`/api/factory/floors/${f.id}`, { name: name.value.trim() || f.name }); await reload();
      } }] });
  }
  async function delFloor(id) {
    if (!await confirmDialog('Katı sil', 'Bu kattaki tüm odalar, yerleştirilmiş kameralar ve merdivenler silinecek. Emin misiniz?', { danger: true, okLabel: 'Sil' })) return;
    await api.del(`/api/factory/floors/${id}`); st.floorId = null; await reload(); toast('Kat silindi');
  }
  function reorderFloors() {
    // Basit sıralama: her kat için yukarı/aşağı okları
    const list = h('div', { class: 'fab-reorder' });
    const order = st.floors.map(f => ({ ...f }));
    const redraw = () => clear(list, order.map((f, i) => h('div', { class: 'fab-reorder-row' },
      h('span', null, f.name),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', type: 'button', disabled: i === 0, onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; redraw(); } }, '↑'),
      h('button', { class: 'btn sm', type: 'button', disabled: i === order.length - 1, onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; redraw(); } }, '↓'))));
    redraw();
    modal({ title: 'Katları sırala (alt → üst)', body: list,
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        await api.post('/api/factory/floors/reorder', { ids: order.map(f => f.id) }); await reload();
      } }] });
  }

  // ==================================================================== ÇİZİM: tuval
  function drawCanvas() {
    // ızgara
    clear(gGrid);
    const G = 40, N = 60;
    for (let i = -N; i <= N; i++) {
      gGrid.append(s('line', { x1: i * G, y1: -N * G, x2: i * G, y2: N * G, class: 'fab-grid' }));
      gGrid.append(s('line', { x1: -N * G, y1: i * G, x2: N * G, y2: i * G, class: 'fab-grid' }));
    }
    gGrid.append(s('line', { x1: -N * G, y1: 0, x2: N * G, y2: 0, class: 'fab-axis' }));
    gGrid.append(s('line', { x1: 0, y1: -N * G, x2: 0, y2: N * G, class: 'fab-axis' }));
    applyCam();

    clear(gStatic);
    if (!st.floorId) { clear(gOverlay); drawEmptyHint(); return; }

    // odalar (dolu yarı saydam poligon + merkez etiket)
    st.rooms.forEach((r, idx) => {
      const pts = r.points || [];
      const color = r.color || ROOM_COLORS[idx % ROOM_COLORS.length];
      if (pts.length >= 2) {
        const poly = s('polygon', {
          points: pts.map(p => p.join(',')).join(' '),
          class: `fab-room ${st.sel && st.sel.type === 'room' && st.sel.id === r.id ? 'sel' : ''}`,
          fill: color, stroke: color,
          onclick: e => { if (st.mode === 'edit' && st.tool === 'select') { e.stopPropagation(); selectRoom(r); } },
        });
        gStatic.append(poly);
      }
      const c = centroid(pts);
      gStatic.append(s('text', { x: c.x, y: c.y, class: 'fab-room-lbl', 'text-anchor': 'middle' }, r.name || 'Oda'));
    });

    // merdivenler
    st.stairs.forEach(m => {
      const onThis = m.from_floor_id === st.floorId;
      const x = onThis ? m.x : (m.to_x ?? m.x), y = onThis ? m.y : (m.to_y ?? m.y);
      const g = s('g', { class: `fab-stair ${st.sel && st.sel.type === 'stair' && st.sel.id === m.id ? 'sel' : ''}`, transform: `translate(${x} ${y})`,
        onclick: e => { if (st.mode === 'edit' && st.tool === 'select') { e.stopPropagation(); selectStair(m); } },
        onmousedown: e => startDragStair(e, m) });
      g.append(s('rect', { x: -14, y: -14, width: 28, height: 28, rx: 4, class: 'fab-stair-box' }));
      for (let i = 0; i < 4; i++) g.append(s('line', { x1: -11, y1: -8 + i * 6, x2: 11, y2: -8 + i * 6, class: 'fab-stair-step' }));
      const other = st.floors.find(f => f.id === (onThis ? m.to_floor_id : m.from_floor_id));
      g.append(s('text', { x: 0, y: 26, class: 'fab-stair-lbl', 'text-anchor': 'middle' }, `${m.name} → ${other ? other.name : '?'}`));
      gStatic.append(g);
    });

    // kameralar (ikon + görüş konisi)
    st.cams.forEach(c => {
      const g = s('g', { class: `fab-cam ${st.sel && st.sel.type === 'cam' && st.sel.id === c.id ? 'sel' : ''}`, transform: `translate(${c.x} ${c.y})`,
        onclick: e => { if (st.mode === 'edit' && st.tool === 'select') { e.stopPropagation(); selectCam(c); } },
        onmousedown: e => startDragCam(e, c) });
      // görüş konisi (yön = derece)
      const rad = (c.direction || 0) * Math.PI / 180, spread = 0.55, len = 46;
      const p1 = [Math.cos(rad - spread) * len, Math.sin(rad - spread) * len];
      const p2 = [Math.cos(rad + spread) * len, Math.sin(rad + spread) * len];
      g.append(s('path', { d: `M0 0 L${p1[0]} ${p1[1]} L${p2[0]} ${p2[1]} Z`, class: 'fab-cone' }));
      g.append(s('rect', { x: -9, y: -7, width: 18, height: 13, rx: 2.5, class: 'fab-cam-body' }));
      g.append(s('circle', { cx: 0, cy: 0, r: 3.4, class: 'fab-cam-lens' }));
      g.append(s('text', { x: 0, y: -12, class: 'fab-cam-lbl', 'text-anchor': 'middle' }, c.camera_name || `#${c.camera_id}`));
      gStatic.append(g);
      // seçili kamera: yön döndürme kolu
      if (st.sel && st.sel.type === 'cam' && st.sel.id === c.id) {
        const hx = Math.cos(rad) * 60, hy = Math.sin(rad) * 60;
        const handle = s('circle', { cx: hx, cy: hy, r: 6, class: 'fab-rot', transform: `translate(${c.x} ${c.y})`,
          onmousedown: e => startRotateCam(e, c) });
        gStatic.append(s('line', { x1: c.x, y1: c.y, x2: c.x + hx, y2: c.y + hy, class: 'fab-rot-line' }));
        gStatic.append(handle);
      }
    });

    // statik işaretçiler
    st.markers.forEach(m => {
      const g = s('g', { class: 'fab-marker', transform: `translate(${m.x} ${m.y})`, onmousedown: e => startDragMarker(e, m) });
      g.append(s('circle', { cx: 0, cy: 0, r: 4, class: 'fab-marker-dot' }));
      g.append(s('text', { x: 8, y: 4, class: 'fab-marker-lbl' }, m.label || ''));
      gStatic.append(g);
    });

    drawOverlay();
  }

  function drawEmptyHint() {
    gStatic.append(s('text', { x: 0, y: 0, class: 'fab-empty', 'text-anchor': 'middle' }, 'Başlamak için bir kat ekleyin'));
  }

  // seçili odanın köşe tutamakları + çizim taslağı + hareket izi overlay'de
  function drawOverlay() {
    clear(gOverlay);
    // çizilmekte olan oda taslağı
    if (st.draft && st.draft.length) {
      gOverlay.append(s('polyline', { points: st.draft.map(p => p.join(',')).join(' '), class: 'fab-draft' }));
      st.draft.forEach(p => gOverlay.append(s('circle', { cx: p[0], cy: p[1], r: 4, class: 'fab-draft-dot' })));
    }
    // seçili oda köşe tutamakları (sürükle → düzenle)
    if (st.mode === 'edit' && st.sel && st.sel.type === 'room') {
      const r = st.rooms.find(x => x.id === st.sel.id);
      if (r) r.points.forEach((p, i) => gOverlay.append(s('circle', {
        cx: p[0], cy: p[1], r: 5, class: 'fab-vertex', onmousedown: e => startDragVertex(e, r, i) })));
    }
    // hareket modu izleri
    if (st.mode === 'move') drawMovementOverlay();
    if (st.mode === 'move' && st.live) drawLiveOverlay();
  }

  // ==================================================================== seçim yardımcıları
  const selectRoom = r => { st.sel = { type: 'room', id: r.id }; drawCanvas(); drawSide(); };
  const selectCam = c => { st.sel = { type: 'cam', id: c.id }; drawCanvas(); drawSide(); };
  const selectStair = m => { st.sel = { type: 'stair', id: m.id }; drawCanvas(); drawSide(); };

  // ==================================================================== sürükleme (autosave)
  function drag(onMove, onUp) {
    const mm = e => onMove(toWorld(e.clientX, e.clientY), e);
    const mu = async e => {
      window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu);
      if (onUp) await onUp(toWorld(e.clientX, e.clientY), e);
    };
    window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
  }
  function startDragCam(e, c) {
    if (st.mode !== 'edit' || st.tool !== 'select') return;
    e.stopPropagation();
    drag(w => { c.x = Math.round(w.x); c.y = Math.round(w.y); drawCanvas(); },
      async () => { autoBindRoom(c); await api.patch(`/api/factory/cameras/${c.id}`, { x: c.x, y: c.y, room_id: c.room_id }); });
  }
  function startRotateCam(e, c) {
    e.stopPropagation();
    drag(w => { c.direction = Math.round(Math.atan2(w.y - c.y, w.x - c.x) * 180 / Math.PI); drawCanvas(); },
      async () => { await api.patch(`/api/factory/cameras/${c.id}`, { direction: c.direction }); });
  }
  function startDragStair(e, m) {
    if (st.mode !== 'edit' || st.tool !== 'select') return;
    e.stopPropagation();
    const onThis = m.from_floor_id === st.floorId;
    drag(w => { if (onThis) { m.x = Math.round(w.x); m.y = Math.round(w.y); } else { m.to_x = Math.round(w.x); m.to_y = Math.round(w.y); } drawCanvas(); },
      async () => { await api.patch(`/api/factory/stairs/${m.id}`, onThis ? { x: m.x, y: m.y } : { to_x: m.to_x, to_y: m.to_y }); });
  }
  function startDragMarker(e, m) {
    if (st.mode !== 'edit' || st.tool !== 'select') return;
    e.stopPropagation();
    drag(w => { m.x = Math.round(w.x); m.y = Math.round(w.y); drawCanvas(); },
      async () => { await api.patch(`/api/factory/markers/${m.id}`, { x: m.x, y: m.y }); });
  }
  function startDragVertex(e, r, i) {
    e.stopPropagation();
    drag(w => { r.points[i] = [Math.round(w.x), Math.round(w.y)]; drawCanvas(); },
      async () => { await api.patch(`/api/factory/rooms/${r.id}`, { points: r.points }); });
  }
  // kamerayı içinde bulunduğu odaya otomatik bağla (nokta-poligon)
  function autoBindRoom(c) {
    const hit = st.rooms.find(r => r.points.length >= 3 && pointInPoly(c.x, c.y, r.points));
    c.room_id = hit ? hit.id : null;
  }

  // ==================================================================== tuval olayları (pan / zoom / araçlar)
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const ns = Math.max(0.2, Math.min(5, st.cam.scale * f));
    // imleç altındaki nokta sabit kalsın
    st.cam.panX = mx - (mx - st.cam.panX) * (ns / st.cam.scale);
    st.cam.panY = my - (my - st.cam.panY) * (ns / st.cam.scale);
    st.cam.scale = ns; applyCam();
  }, { passive: false });

  svg.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    const w = toWorld(e.clientX, e.clientY);
    if (st.mode === 'edit' && st.tool === 'room') { addDraftVertex(w); return; }
    if (st.mode === 'edit' && (st.tool === 'camera' || st.tool === 'stair')) { return; }   // kamera/merdiven: yerleştirme click ile (aşağıda), pan başlatma
    // boş alana tıklama: pan + seçim temizle
    if (st.mode === 'edit' && st.tool === 'select') { st.sel = null; drawSide(); drawOverlay(); }
    const sx = e.clientX, sy = e.clientY, px = st.cam.panX, py = st.cam.panY;
    const mm = ev => { st.cam.panX = px + (ev.clientX - sx); st.cam.panY = py + (ev.clientY - sy); applyCam(); };
    const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
    window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
  });
  // oda çizimini bitir: çift tık ya da Enter
  svg.addEventListener('dblclick', e => { e.preventDefault(); if (st.tool === 'room') finishRoom(); });
  const onKey = e => {
    if (st.mode !== 'edit') return;
    if (e.key === 'Enter' && st.tool === 'room') finishRoom();
    else if (e.key === 'Escape') { st.draft = null; drawOverlay(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && st.sel) deleteSelected();
  };
  window.addEventListener('keydown', onKey);
  onLeave(() => window.removeEventListener('keydown', onKey));

  // kamera aracı: tuvale tıklanınca seçili NVR kamerası oraya yerleşir
  svg.addEventListener('click', e => {
    if (st.mode === 'edit' && st.tool === 'camera' && pendingCam) {
      const w = toWorld(e.clientX, e.clientY);
      placeCameraAt(pendingCam, Math.round(w.x), Math.round(w.y));
    }
    if (st.mode === 'edit' && st.tool === 'stair') {
      const w = toWorld(e.clientX, e.clientY);
      newStairAt(Math.round(w.x), Math.round(w.y));
    }
  });

  // -------------------------------------------------------------------- oda çizimi
  function addDraftVertex(w) {
    if (!st.draft) st.draft = [];
    st.draft.push([Math.round(w.x), Math.round(w.y)]);
    drawOverlay();
  }
  async function finishRoom() {
    if (!st.draft || st.draft.length < 3) { st.draft = null; drawOverlay(); return toast('Oda için en az 3 köşe gerekli', 'err'); }
    const pts = st.draft.slice(); st.draft = null;
    const name = h('input', { class: 'input', value: `Oda ${st.rooms.length + 1}` });
    const colorRow = h('div', { class: 'fab-colors' });
    let chosen = ROOM_COLORS[st.rooms.length % ROOM_COLORS.length];
    const paint = () => clear(colorRow, ROOM_COLORS.map(col => h('button', {
      class: `fab-swatch ${col === chosen ? 'on' : ''}`, type: 'button', style: { background: col },
      onclick: () => { chosen = col; paint(); } })));
    paint();
    modal({
      title: 'Oda adı ve rengi', body: h('div', null, field('Oda adı', name), field('Renk', colorRow)),
      onClose: () => { drawOverlay(); },
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        await api.post('/api/factory/rooms', { floor_id: st.floorId, name: name.value.trim(), points: pts, color: chosen });
        st.tool = 'select'; await loadFloorData(); drawCanvas(); drawSide();
        toast('Oda eklendi');
      } }],
    });
  }

  // -------------------------------------------------------------------- kamera yerleştirme
  let pendingCam = null;   // kamera aracı aktifken yerleştirilecek NVR kamerası
  function pickCamera() {
    if (!st.avail.length) return toast('Yerleştirilecek boş NVR kamerası yok (hepsi yerleştirilmiş ya da NVR erişilemez)', 'err');
    const listEl = h('div', { class: 'fab-cam-pick' }, st.avail.map(c => h('button', {
      class: 'fab-cam-opt', type: 'button', onclick: () => { pendingCam = c; st.tool = 'camera'; m.close(); drawSide(); hintText('Kamerayı yerleştirmek için plana tıklayın'); },
    }, h('b', null, c.name || `Kamera #${c.id}`), c.location ? h('span', { class: 'muted' }, ` · ${c.location}`) : null)));
    const m = modal({ title: 'NVR kamerası seç', body: listEl, actions: [{ label: 'Kapat' }] });
  }
  async function placeCameraAt(cam, x, y) {
    // içinde bulunduğu odayı otomatik bul
    const hit = st.rooms.find(r => r.points.length >= 3 && pointInPoly(x, y, r.points));
    await api.post('/api/factory/cameras', { camera_id: cam.id, floor_id: st.floorId, x, y, direction: 0, room_id: hit ? hit.id : null });
    pendingCam = null; st.tool = 'select';
    await loadAvail(); await loadFloorData(); drawCanvas(); drawSide();
    toast('Kamera yerleştirildi');
  }

  // -------------------------------------------------------------------- merdiven
  function newStairAt(x, y) {
    if (st.floors.length < 2) { st.tool = 'select'; return toast('Merdiven için en az 2 kat gerekli', 'err'); }
    const name = h('input', { class: 'input', value: 'Merdiven' });
    const target = h('select', { class: 'input' }, st.floors.filter(f => f.id !== st.floorId).map(f => h('option', { value: f.id }, f.name)));
    modal({ title: 'Merdiven: hedef kat', body: h('div', null, field('Ad', name), field('Çıktığı kat', target)),
      onClose: () => { st.tool = 'select'; },
      actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: async () => {
        await api.post('/api/factory/stairs', { name: name.value.trim() || 'Merdiven', from_floor_id: st.floorId, to_floor_id: Number(target.value), x, y });
        st.tool = 'select'; await loadFloorData(); drawCanvas(); drawSide(); toast('Merdiven eklendi');
      } }] });
  }

  // -------------------------------------------------------------------- seçili öğeyi sil
  async function deleteSelected() {
    const sel = st.sel; if (!sel) return;
    const map = { room: ['rooms', 'Oda'], cam: ['cameras', 'Kamera'], stair: ['stairs', 'Merdiven'] };
    const [path, label] = map[sel.type];
    if (!await confirmDialog(`${label} sil`, `${label} silinsin mi?`, { danger: true, okLabel: 'Sil' })) return;
    await api.del(`/api/factory/${path}/${sel.id}`);
    st.sel = null; if (sel.type === 'cam') await loadAvail();
    await loadFloorData(); drawCanvas(); drawSide(); toast(`${label} silindi`);
  }

  // ==================================================================== SAĞ PANEL
  function drawSide() {
    if (st.mode === 'move') return drawMoveSide();
    // DÜZEN paneli: araçlar + seçili öğe özellikleri
    const toolBtn = (key, label) => h('button', { class: `fab-tool ${st.tool === key ? 'on' : ''}`, type: 'button',
      onclick: () => { st.tool = key; st.draft = null; if (key === 'camera') pickCamera(); else if (key === 'stair') hintText('Merdiven koymak için plana tıklayın'); else hintText(''); drawSide(); drawOverlay(); } },
      label);
    const tools = h('div', { class: 'fab-tools' },
      toolBtn('select', 'Seç / Taşı'),
      toolBtn('room', 'Oda Çiz'),
      toolBtn('camera', 'Kamera Koy'),
      toolBtn('stair', 'Merdiven Koy'));
    clear(side,
      h('h3', { class: 'fab-side-h' }, 'Araçlar'),
      tools,
      st.tool === 'room' ? h('div', { class: 'fab-note' }, 'Köşe eklemek için tıklayın; bitirmek için çift tık ya da Enter. Vazgeç: Esc.') : null,
      selProps());
    drawFloorBar();
  }
  function selProps() {
    if (!st.sel) return h('div', { class: 'fab-note muted' }, 'Bir öğe seçin (özellikleri burada görünür).');
    if (st.sel.type === 'room') {
      const r = st.rooms.find(x => x.id === st.sel.id); if (!r) return null;
      const name = h('input', { class: 'input', value: r.name || '' });
      name.addEventListener('change', async () => { await api.patch(`/api/factory/rooms/${r.id}`, { name: name.value.trim() }); r.name = name.value.trim(); drawCanvas(); });
      return h('div', { class: 'fab-props' }, h('h4', null, 'Oda'), field('Ad', name),
        h('button', { class: 'btn danger sm', type: 'button', onclick: deleteSelected }, 'Odayı Sil'));
    }
    if (st.sel.type === 'cam') {
      const c = st.cams.find(x => x.id === st.sel.id); if (!c) return null;
      const dir = h('input', { class: 'input', type: 'number', value: Math.round(c.direction || 0) });
      dir.addEventListener('change', async () => { c.direction = Number(dir.value) || 0; await api.patch(`/api/factory/cameras/${c.id}`, { direction: c.direction }); drawCanvas(); });
      const roomSel = h('select', { class: 'input' },
        h('option', { value: '' }, '(oda yok)'),
        st.rooms.map(r => h('option', { value: r.id, selected: r.id === c.room_id }, r.name || `Oda #${r.id}`)));
      roomSel.addEventListener('change', async () => { c.room_id = roomSel.value ? Number(roomSel.value) : null; await api.patch(`/api/factory/cameras/${c.id}`, { room_id: c.room_id }); });
      return h('div', { class: 'fab-props' }, h('h4', null, c.camera_name || `Kamera #${c.camera_id}`),
        field('Görüş yönü (derece)', dir), field('Bağlı oda', roomSel),
        h('div', { class: 'fab-note muted' }, 'İpucu: yönü tuval üzerindeki daireyi döndürerek de ayarlayabilirsiniz.'),
        h('button', { class: 'btn danger sm', type: 'button', onclick: deleteSelected }, 'Kamerayı Kaldır'));
    }
    if (st.sel.type === 'stair') {
      const m = st.stairs.find(x => x.id === st.sel.id); if (!m) return null;
      return h('div', { class: 'fab-props' }, h('h4', null, m.name),
        h('div', { class: 'fab-note' }, `${st.floors.find(f => f.id === m.from_floor_id)?.name || '?'} ↔ ${st.floors.find(f => f.id === m.to_floor_id)?.name || '?'}`),
        h('button', { class: 'btn danger sm', type: 'button', onclick: deleteSelected }, 'Merdiveni Sil'));
    }
    return null;
  }
  const hintText = txt => { hint.textContent = txt || ''; hint.hidden = !txt; };

  // ==================================================================== HAREKET MODU
  async function drawMoveSide() {
    if (!st.people) st.people = await api.get('/api/faces/people').catch(() => ({ users: [], people: [], family: [], visitors: [] }));
    // özne seçici (optgroup: Kullanıcılar / Kişiler / Aile / Ziyaretçiler)
    const sub = h('select', { class: 'input' }, h('option', { value: '' }, 'Kişi seçin…'),
      optg('Kullanıcılar', st.people.users, 'user', p => p.full_name),
      optg('Firma Kişileri', st.people.people, 'person', p => `${p.full_name}${p.company_name ? ` · ${p.company_name}` : ''}`),
      optg('Personel Aileleri', st.people.family, 'family', p => `${p.full_name}${p.employee_name ? ` · ${p.employee_name}` : ''}`),
      optg('Ziyaretçiler', st.people.visitors, 'visitor', p => p.full_name));
    const today = new Date().toISOString().slice(0, 10);
    const from = h('input', { class: 'input', type: 'date', value: today });
    const to = h('input', { class: 'input', type: 'date', value: today });
    const go = h('button', { class: 'btn primary', type: 'button' }, 'Yolu Göster');
    go.addEventListener('click', async () => {
      if (!sub.value) return toast('Önce bir kişi seçin', 'err');
      const [type, id] = sub.value.split(':');
      st.subject = { type, id: Number(id), name: sub.selectedOptions[0].textContent };
      try {
        st.move = await api.get(`/api/factory/movement?subject_type=${type}&subject_id=${id}&date_from=${from.value}&date_to=${to.value}`);
        st.play.t = 0; st.play.playing = false;
        if (st.move.segments.length) { const f = st.move.segments[0].floor_id; if (f) { st.floorId = f; await loadFloorData(); drawCanvas(); drawFloorBar(); } }
        drawMoveSide(); drawOverlay();
        if (!st.move.segments.length) toast('Bu aralıkta eşlenmiş hareket bulunamadı');
      } catch (err) { toastError(err); }
    });

    const liveBtn = h('button', { class: `btn ${st.live ? 'success' : ''}`, type: 'button', onclick: toggleLive }, st.live ? 'Canlı: Açık' : 'Şu An (canlı)');

    clear(side,
      h('h3', { class: 'fab-side-h' }, 'Hareket'),
      field('Kişi', sub),
      h('div', { class: 'fab-row' }, field('Başlangıç', from), field('Bitiş', to)),
      go,
      moveResultPanel(),
      h('hr', { class: 'fab-hr' }),
      h('h3', { class: 'fab-side-h' }, 'Canlı Durum'),
      liveBtn,
      livePanel());
    drawFloorBar();
  }
  function optg(label, arr, type, fmt) {
    if (!arr || !arr.length) return null;
    return h('optgroup', { label }, arr.map(p => h('option', { value: `${type}:${p.id}` }, fmt(p))));
  }

  function moveResultPanel() {
    if (!st.move) return null;
    const segs = st.move.segments || [];
    if (!segs.length) return h('div', { class: 'fab-note muted' }, st.subject ? 'Eşlenmiş hareket yok. (Kameralar odalara bağlı olmalı.)' : '');
    // zaman çizelgesi oynatıcı
    const scrub = h('input', { class: 'fab-scrub', type: 'range', min: 0, max: 1000, value: Math.round(st.play.t * 1000) });
    scrub.addEventListener('input', () => { st.play.t = Number(scrub.value) / 1000; st.play.playing = false; applyPlayhead(); });
    const playBtn = h('button', { class: 'btn sm', type: 'button' }, st.play.playing ? '⏸ Duraklat' : '▶ Oynat');
    playBtn.addEventListener('click', () => { st.play.playing = !st.play.playing; if (st.play.playing) runPlay(scrub, playBtn); else cancelAnimationFrame(st.play.raf); playBtn.textContent = st.play.playing ? '⏸ Duraklat' : '▶ Oynat'; });

    const list = h('ol', { class: 'fab-seglist' }, segs.map((sg, i) => {
      const fl = st.floors.find(f => f.id === sg.floor_id);
      return h('li', { class: sg.floor_id === st.floorId ? 'on' : '' },
        h('button', { class: 'fab-seg', type: 'button', onclick: async () => {
          if (sg.floor_id && sg.floor_id !== st.floorId) { st.floorId = sg.floor_id; await loadFloorData(); drawCanvas(); drawFloorBar(); }
          drawOverlay();
        } },
          h('b', null, `${i + 1}. ${sg.room_name || sg.camera_name || 'Bilinmeyen'}`),
          h('span', { class: 'muted' }, fl ? ` (${fl.name})` : ''),
          h('div', { class: 'fab-seg-t muted' }, `${fmtT(sg.enter)} → ${fmtT(sg.leave)}${sg.count > 1 ? ` · ${sg.count} görülme` : ''}`)));
    }));
    return h('div', { class: 'fab-move-res' },
      h('div', { class: 'fab-note' }, h('b', null, st.move.subject_name || st.subject?.name || ''), ` · ${segs.length} durak`),
      h('div', { class: 'fab-play' }, playBtn, scrub),
      list);
  }

  // oynatma: başlangıç→bitiş zamanını 0..1'e ölçekler; aktif segmenti bulur, katı değiştirir, noktayı konumlar
  function playTimeline() {
    const segs = st.move?.segments || [];
    const times = segs.flatMap(s2 => [s2.enter, s2.leave]).filter(Boolean).sort();
    return { t0: times[0], t1: times[times.length - 1], segs };
  }
  function segPos(sg) {
    // segmentin konumu: odası varsa merkez; yoksa yerleştirilmiş kamerası
    if (sg.room_id) { const r = st.rooms.find(x => x.id === sg.room_id); if (r) return centroid(r.points); }
    if (sg.camera_id) { const c = st.cams.find(x => x.camera_id === sg.camera_id); if (c) return { x: c.x, y: c.y }; }
    return null;
  }
  function applyPlayhead() {
    const { t0, t1, segs } = playTimeline();
    if (!t0) return;
    const ms0 = new Date(t0).getTime(), ms1 = new Date(t1).getTime();
    const cur = ms0 + (ms1 - ms0) * st.play.t;
    // aktif segment: enter<=cur<=leave (ya da en yakın)
    let active = segs[0];
    for (const sg of segs) { if (new Date(sg.enter).getTime() <= cur) active = sg; }
    if (active && active.floor_id && active.floor_id !== st.floorId) {
      st.floorId = active.floor_id; loadFloorData().then(() => { drawCanvas(); drawFloorBar(); drawOverlay(); placeDot(active); });
      return;
    }
    drawOverlay(); placeDot(active);
  }
  function placeDot(sg) {
    const p = sg && segPos(sg); if (!p) return;
    gOverlay.append(s('circle', { cx: p.x, cy: p.y, r: 9, class: 'fab-playdot' }));
  }
  function runPlay(scrub, playBtn) {
    const step = () => {
      st.play.t += 0.004;
      if (st.play.t >= 1) { st.play.t = 1; st.play.playing = false; playBtn.textContent = '▶ Oynat'; }
      scrub.value = Math.round(st.play.t * 1000);
      applyPlayhead();
      if (st.play.playing) st.play.raf = requestAnimationFrame(step);
    };
    st.play.raf = requestAnimationFrame(step);
  }

  // hareket izi (mevcut kata ait segmentler: numaralı oklar + duraklar)
  function drawMovementOverlay() {
    const segs = (st.move?.segments || []).filter(sg => sg.floor_id === st.floorId);
    const pts = [];
    segs.forEach((sg, i) => { const p = segPos(sg); if (p) pts.push({ ...p, i: (st.move.segments.indexOf(sg)) + 1, sg }); });
    // bağlantı okları
    for (let i = 0; i < pts.length - 1; i++) {
      gOverlay.append(s('line', { x1: pts[i].x, y1: pts[i].y, x2: pts[i + 1].x, y2: pts[i + 1].y, class: 'fab-trail', 'marker-end': 'url(#fab-arrow)' }));
    }
    pts.forEach(p => {
      gOverlay.append(s('circle', { cx: p.x, cy: p.y, r: 12, class: 'fab-trail-node' }));
      gOverlay.append(s('text', { x: p.x, y: p.y + 4, class: 'fab-trail-num', 'text-anchor': 'middle' }, String(p.i)));
      gOverlay.append(s('text', { x: p.x, y: p.y - 16, class: 'fab-trail-t', 'text-anchor': 'middle' }, fmtDateTime(p.sg.enter)));
    });
    ensureArrowMarker();
  }
  function ensureArrowMarker() {
    if (svg.querySelector('#fab-arrow')) return;
    const defs = s('defs', null, s('marker', { id: 'fab-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
      s('path', { d: 'M0 0 L10 5 L0 10 z', class: 'fab-arrow-head' })));
    svg.insertBefore(defs, svg.firstChild);
  }

  // ------------------------------------------------- canlı "şu an kim nerede"
  async function toggleLive() {
    st.live = !st.live;
    if (st.live) { await refreshLive(); st.liveTimer = every(10000, () => refreshLive().catch(() => {})); }
    else if (st.liveTimer) { clearInterval(st.liveTimer); st.liveTimer = null; }
    drawMoveSide(); drawOverlay();
  }
  async function refreshLive() {
    st.liveData = await api.get('/api/factory/now?minutes=10');
    drawMoveSide(); drawOverlay();
  }
  function livePanel() {
    if (!st.live) return h('div', { class: 'fab-note muted' }, 'Son 10 dakikada görülen kişileri odalara göre gösterir.');
    const ppl = st.liveData?.people || [];
    if (!ppl.length) return h('div', { class: 'fab-note muted' }, 'Son 10 dakikada tanınan kişi yok.');
    // kata göre grupla
    const byFloor = new Map();
    ppl.forEach(p => { const k = p.floor_id || 0; if (!byFloor.has(k)) byFloor.set(k, []); byFloor.get(k).push(p); });
    return h('div', { class: 'fab-live' }, [...byFloor.entries()].map(([fid, arr]) => {
      const fl = st.floors.find(f => f.id === fid);
      return h('div', { class: 'fab-live-floor' }, h('h4', null, fl ? fl.name : 'Bilinmeyen kat'),
        arr.map(p => h('div', { class: 'fab-live-row' },
          p.crop ? h('img', { class: 'fab-live-img', src: fileUrl(p.crop, 64), alt: '' }) : h('span', { class: 'fab-live-img ph' }),
          h('span', null, h('b', null, p.subject_name || '—'), h('br'), h('span', { class: 'muted' }, `${p.room_name || p.camera_name || '—'} · ${fmtDateTime(p.at)}`)))));
    }));
  }
  function drawLiveOverlay() {
    // canlı: kişisi olan odaları vurgula + sayac
    const ppl = (st.liveData?.people || []).filter(p => p.floor_id === st.floorId && p.room_id);
    const counts = new Map();
    ppl.forEach(p => counts.set(p.room_id, (counts.get(p.room_id) || 0) + 1));
    counts.forEach((n, rid) => {
      const r = st.rooms.find(x => x.id === rid); if (!r) return;
      const c = centroid(r.points);
      gOverlay.append(s('circle', { cx: c.x, cy: c.y, r: 16, class: 'fab-live-dot' }));
      gOverlay.append(s('text', { x: c.x, y: c.y + 5, class: 'fab-live-cnt', 'text-anchor': 'middle' }, String(n)));
    });
  }

  // ==================================================================== mod geçişi + ilk çizim
  function setMode(mode) {
    st.mode = mode; st.sel = null; st.draft = null; st.tool = 'select';
    if (mode !== 'move' && st.live && st.liveTimer) { clearInterval(st.liveTimer); st.liveTimer = null; st.live = false; }
    hintText('');
    drawCanvas(); drawSide();
  }
  onLeave(() => { if (st.liveTimer) clearInterval(st.liveTimer); if (st.play.raf) cancelAnimationFrame(st.play.raf); });

  const toolbar = moduleToolbar(segmented([['edit', 'Düzen'], ['move', 'Hareket']], st.mode, setMode, { tabs: true }));
  clear(view, pageHead('Fabrika', { back: '#/', sub: 'Kat planı · kamera/personel yerleşimi · hareket izi' }), toolbar, wrap);

  try {
    await reload();
    await loadAvail();
    drawSide();
    if (!st.floors.length) hintText('Henüz kat yok. Sağ üstteki "+ Kat" ile başlayın.');
  } catch (err) { toastError(err); }
}

// ---------------------------------------------------------------------------- stiller (bir kez enjekte)
function injectStyle() {
  if (document.getElementById('fab-style')) return;
  const css = `
  .fab-wrap{display:flex;gap:12px;align-items:stretch;height:calc(100vh - 190px);min-height:460px}
  .fab-main{flex:1;display:flex;flex-direction:column;min-width:0}
  .fab-side{width:290px;flex:0 0 290px;overflow:auto;background:var(--card,#fff);border:1px solid var(--line,#e5e7eb);border-radius:10px;padding:12px}
  .fab-side-h{margin:4px 0 8px;font-size:15px}
  .fab-floors{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px}
  .fab-floors-lbl{font-size:12px;color:var(--muted,#6b7280)}
  .fab-floor{padding:4px 12px;border:1px solid var(--line,#e5e7eb);background:var(--card,#fff);border-radius:16px;cursor:pointer;font-size:13px}
  .fab-floor.on{background:var(--pri,#2563eb);color:#fff;border-color:var(--pri,#2563eb)}
  .fab-floor.add{border-style:dashed;color:var(--muted,#6b7280)}
  .fab-stage{flex:1;position:relative;border:1px solid var(--line,#e5e7eb);border-radius:10px;overflow:hidden;background:var(--bg2,#f8fafc)}
  .fab-svg{width:100%;height:100%;display:block;cursor:grab;touch-action:none}
  .fab-svg:active{cursor:grabbing}
  .fab-grid{stroke:#e2e8f0;stroke-width:1;vector-effect:non-scaling-stroke}
  .fab-axis{stroke:#cbd5e1;stroke-width:1.5;vector-effect:non-scaling-stroke}
  .fab-room{fill-opacity:.22;stroke-width:2;cursor:pointer;vector-effect:non-scaling-stroke}
  .fab-room.sel{fill-opacity:.38;stroke-width:3}
  .fab-room-lbl{font:600 13px system-ui;fill:#1e293b;pointer-events:none}
  .fab-empty{font:600 16px system-ui;fill:#94a3b8}
  .fab-cone{fill:#f59e0b;fill-opacity:.25;stroke:none;pointer-events:none}
  .fab-cam{cursor:move}
  .fab-cam-body{fill:#1e293b;stroke:#fff;stroke-width:1.2}
  .fab-cam.sel .fab-cam-body{stroke:#2563eb;stroke-width:2}
  .fab-cam-lens{fill:#60a5fa}
  .fab-cam-lbl{font:600 10px system-ui;fill:#334155;pointer-events:none}
  .fab-rot{fill:#2563eb;cursor:crosshair}
  .fab-rot-line{stroke:#2563eb;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}
  .fab-stair{cursor:move}
  .fab-stair-box{fill:#e2e8f0;stroke:#64748b;stroke-width:1.5}
  .fab-stair.sel .fab-stair-box{stroke:#2563eb;stroke-width:2.5}
  .fab-stair-step{stroke:#64748b;stroke-width:1.2}
  .fab-stair-lbl{font:600 10px system-ui;fill:#475569;pointer-events:none}
  .fab-marker-dot{fill:#64748b}
  .fab-marker-lbl{font:600 11px system-ui;fill:#475569}
  .fab-draft{fill:none;stroke:#2563eb;stroke-width:2;stroke-dasharray:5 4;vector-effect:non-scaling-stroke}
  .fab-draft-dot{fill:#2563eb}
  .fab-vertex{fill:#fff;stroke:#2563eb;stroke-width:2;cursor:move}
  .fab-trail{stroke:#dc2626;stroke-width:2.5;vector-effect:non-scaling-stroke;opacity:.85}
  .fab-arrow-head{fill:#dc2626}
  .fab-trail-node{fill:#dc2626;fill-opacity:.9}
  .fab-trail-num{font:700 12px system-ui;fill:#fff;pointer-events:none}
  .fab-trail-t{font:600 10px system-ui;fill:#991b1b;pointer-events:none}
  .fab-playdot{fill:#16a34a;stroke:#fff;stroke-width:2}
  .fab-live-dot{fill:#16a34a;fill-opacity:.35;stroke:#16a34a;stroke-width:2}
  .fab-live-cnt{font:700 13px system-ui;fill:#065f46;pointer-events:none}
  .fab-tools{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
  .fab-tool{padding:8px 10px;border:1px solid var(--line,#e5e7eb);border-radius:8px;background:var(--card,#fff);cursor:pointer;text-align:left;font-size:13px}
  .fab-tool.on{background:var(--pri,#2563eb);color:#fff;border-color:var(--pri,#2563eb)}
  .fab-note{font-size:12px;color:var(--muted,#6b7280);margin:6px 0;line-height:1.5}
  .fab-note.muted{opacity:.85}
  .fab-props h4{margin:10px 0 6px}
  .fab-colors,.fab-cam-pick{display:flex;flex-wrap:wrap;gap:6px}
  .fab-swatch{width:26px;height:26px;border-radius:50%;border:2px solid transparent;cursor:pointer}
  .fab-swatch.on{border-color:#1e293b}
  .fab-cam-pick{flex-direction:column}
  .fab-cam-opt{text-align:left;padding:8px 10px;border:1px solid var(--line,#e5e7eb);border-radius:8px;background:var(--card,#fff);cursor:pointer}
  .fab-cam-opt:hover{background:var(--bg2,#f1f5f9)}
  .fab-hint{position:static;margin-top:6px;font-size:12px;color:var(--pri,#2563eb);min-height:16px}
  .fab-row{display:flex;gap:8px}
  .fab-row>*{flex:1}
  .fab-hr{border:none;border-top:1px solid var(--line,#e5e7eb);margin:12px 0}
  .fab-play{display:flex;align-items:center;gap:8px;margin:8px 0}
  .fab-scrub{flex:1}
  .fab-seglist{margin:8px 0 0;padding-left:20px;font-size:13px;max-height:260px;overflow:auto}
  .fab-seglist li{margin-bottom:6px}
  .fab-seglist li.on .fab-seg b{color:var(--pri,#2563eb)}
  .fab-seg{display:block;text-align:left;background:none;border:none;cursor:pointer;padding:2px 0;width:100%}
  .fab-seg-t{font-size:11px}
  .fab-reorder-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--line,#eee)}
  .fab-live-floor h4{margin:8px 0 4px}
  .fab-live-row{display:flex;gap:8px;align-items:center;padding:4px 0;font-size:12px}
  .fab-live-img{width:34px;height:34px;border-radius:6px;object-fit:cover;background:#e2e8f0;flex:0 0 34px}
  `;
  const styleEl = document.createElement('style');
  styleEl.id = 'fab-style';
  styleEl.textContent = css;
  document.head.append(styleEl);
}
