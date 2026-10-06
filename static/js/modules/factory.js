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

// ---------------------------------------------------------------------------- ALTYAPI palet / katman tanımları
// İŞARETÇİ PALETİ: backend MARKER_KINDS allowlist ile AYNI anahtarlar; her türe ayrı ikon (emoji) + renk.
// (NVR'a bağlı gerçek kameralar factory_cameras'ta kalır; cam_indoor/cam_outdoor burada PLANLANAN/bağsız konumlardır.)
const MARKER_PALETTE = {
  ups:          { label: 'UPS / Güç kaynağı',         icon: '🔋', color: '#16a34a' },
  power_outlet: { label: 'Priz / Elektrik',           icon: '⚡', color: '#f59e0b' },
  wifi:         { label: 'WiFi erişim noktası',       icon: '📶', color: '#2563eb' },
  internet:     { label: 'Internet / Ethernet prizi', icon: '🌐', color: '#0891b2' },
  intranet:     { label: 'Intranet noktası',          icon: '🔗', color: '#7c3aed' },
  switch:       { label: 'Ağ switch’i',               icon: '🔀', color: '#0ea5e9' },
  cam_indoor:   { label: 'İç kamera (planlanan)',     icon: '📷', color: '#334155' },
  cam_outdoor:  { label: 'Dış kamera (planlanan)',    icon: '📹', color: '#475569' },
  note:         { label: 'Not / etiket',              icon: '📝', color: '#64748b' },
};
const MARKER_ORDER = ['ups', 'power_outlet', 'wifi', 'internet', 'intranet', 'switch', 'cam_indoor', 'cam_outdoor', 'note'];
const markerMeta = k => MARKER_PALETTE[k] || { label: k || 'İşaretçi', icon: '📍', color: '#64748b' };

// HAT (kablo güzergâhı) türleri: [anahtar, etiket, öntanımlı renk] — network mavi (kesikli), power kırmızı (düz).
const LINE_KINDS = [['network', 'Network hattı', '#2563eb'], ['power', 'Elektrik hattı', '#dc2626'], ['other', 'Diğer', '#6b7280']];
const LINE_DEFAULT = { network: '#2563eb', power: '#dc2626', other: '#6b7280' };
const lineColor = ln => ln.color || LINE_DEFAULT[ln.kind] || '#6b7280';
const lineDash = ln => (ln.kind === 'network' ? '7 5' : null);

// KATMAN (layer) görünürlük anahtarları: her kategori bağımsız açılıp kapanır (pptx'teki ayrı planlar gibi).
const LAYER_DEFS = [
  ['bg', 'Arka plan'], ['rooms', 'Odalar'], ['cams', 'NVR Kameralar'], ['markers', 'İşaretçiler'],
  ['network', 'Network hatları'], ['power', 'Elektrik hatları'], ['stairs', 'Merdivenler'],
];
const LAYER_KEY = 'fab.layers';
function loadLayers() {   // cihaz başına (localStorage) saklanır; hepsi öntanımlı açık
  const d = {}; LAYER_DEFS.forEach(([k]) => { d[k] = true; });
  try { Object.assign(d, JSON.parse(localStorage.getItem(LAYER_KEY) || '{}')); } catch { /* yoksa öntanımlı */ }
  return d;
}
function saveLayers(l) { try { localStorage.setItem(LAYER_KEY, JSON.stringify(l)); } catch { /* sessiz */ } }

// Photoshop tarzı yüzen ikon araç çubuğu konumu (sürüklenince cihaz başına localStorage'da saklanır)
const TB_KEY = 'fab.toolbar.pos';
// Yüzen "Seçenekler" paneli (özellik/katman/hareket) açık mı? (cihaz başına localStorage)
const PANEL_KEY = 'fab.panel.open';
// Araç ikonları (24x24 SVG). fill="none" olan şekiller CSS ile stroke'lanır; diğerleri dolu. currentColor ile renklenir.
const TOOL_ICON = {
  select: () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M5 3 L5 19 L9 15 L12 21 L14.5 20 L11.5 14 L17 14 Z' })),
  room:   () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('polygon', { points: '4,7 13,3 20,9 18,20 7,18', fill: 'none' })),
  camera: () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M3 7 h3 l2-2 h6 l2 2 h3 v12 H3 Z', fill: 'none' }), s('circle', { cx: 12, cy: 13, r: 3.2, fill: 'none' })),
  marker: () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M12 2 C8 2 5 5 5 9 c0 5 7 13 7 13 s7-8 7-13 c0-4-3-7-7-7 Z' }), s('circle', { cx: 12, cy: 9, r: 2.4, fill: '#fff', stroke: 'none' })),
  net:    () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('polyline', { points: '4,18 10,10 15,14 20,5', fill: 'none' }), s('circle', { cx: 4, cy: 18, r: 2.1, stroke: 'none' }), s('circle', { cx: 20, cy: 5, r: 2.1, stroke: 'none' })),
  power:  () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M13 2 L4 14 h6 l-1 8 L20 9 h-6 Z' })),
  stair:  () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M4 20 V16 H9 V12 H14 V8 H19 V4', fill: 'none' })),
  bg:     () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('rect', { x: 3, y: 5, width: 18, height: 14, rx: 2, fill: 'none' }), s('circle', { cx: 8, cy: 10, r: 1.7, stroke: 'none' }), s('path', { d: 'M4 18 L10 12 L13 15 L16.5 11 L20 16', fill: 'none' })),
  grip:   () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, [[9, 6], [15, 6], [9, 12], [15, 12], [9, 18], [15, 18]].map(([cx, cy]) => s('circle', { cx, cy, r: 1.5, stroke: 'none' }))),
  // Seçenekler paneli (sürgü/slider ikonu): özellikler + katmanlar menüsünü açar
  panel:  () => s('svg', { viewBox: '0 0 24 24', class: 'fab-ti' }, s('path', { d: 'M4 7 H20 M4 12 H20 M4 17 H20', fill: 'none' }), [[9, 7], [15, 12], [7, 17]].map(([cx, cy]) => s('circle', { cx, cy, r: 2.3, stroke: 'none' }))),
};
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
    tool: 'select',               // edit altı: 'select' | 'room' | 'camera' | 'stair' | 'marker' | 'line'
    floors: [], floorId: null,
    rooms: [], cams: [], stairs: [], markers: [], lines: [], avail: [],
    sel: null,                    // {type:'room'|'cam'|'stair'|'marker'|'line', id}
    draft: null,                  // çizilmekte olan oda köşeleri [[x,y],...]
    lineDraft: null,              // çizilmekte olan hat köşeleri [[x,y],...]
    lineKind: 'network',          // "Hat Çiz" aktifken çizilecek hat türü
    layers: loadLayers(),         // katman görünürlükleri (localStorage)
    panelOpen: (() => { try { return localStorage.getItem(PANEL_KEY) === '1'; } catch { return false; } })(),  // yüzen seçenekler paneli açık mı
    bgEdit: false,                // arka plan "Hizala" modu (resmi sürükle)
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
  const gBg = s('g', { class: 'fab-bg' }), gGrid = s('g'), gStatic = s('g'), gOverlay = s('g');
  world.append(gBg, gGrid, gStatic, gOverlay);   // gBg: kat planı arka plan resmi (en altta, üzerine çizilir)
  svg.append(world);
  const stage = h('div', { class: 'fab-stage' }, svg);
  // Photoshop tarzı YÜZEN ikon araç çubuğu: tuval üzerinde, ince dikey, yalnız ikon (hover'da başlık), sürüklenebilir.
  const toolbarEl = h('div', { class: 'fab-toolbar', role: 'toolbar', 'aria-label': 'Tasarım araçları' });
  toolbarEl.hidden = true;
  const tbBgInp = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif,image/svg+xml,.svg', style: { display: 'none' } });
  tbBgInp.addEventListener('change', async () => {
    if (!st.floorId) { toast('Önce bir kat seçin', 'err'); tbBgInp.value = ''; return; }
    if (!tbBgInp.files || !tbBgInp.files[0]) { return; }
    const fd = new FormData(); fd.append('file', tbBgInp.files[0]);
    try { await api.post(`/api/factory/floors/${st.floorId}/background`, fd); await reload(); toast('Kat planı (arka plan) yüklendi'); }
    catch (err) { toastError(err); }
    tbBgInp.value = '';
  });
  // Yüzen "Seçenekler" paneli: eski sağ panel yerine tuval üzerinde, araç çubuğu düğmesiyle açılır popover.
  const sideBody = h('div', { class: 'fab-side-body' });
  const side = h('div', { class: 'fab-side fab-pop' },
    h('div', { class: 'fab-pop-hdr' },
      h('span', { class: 'fab-pop-ttl' }, 'Seçenekler'),
      h('button', { class: 'fab-pop-x', type: 'button', title: 'Kapat', 'aria-label': 'Kapat', onclick: () => setPanel(false) }, '✕')),
    sideBody);
  side.hidden = true;
  stage.append(toolbarEl, tbBgInp, side);
  const floorBar = h('div', { class: 'fab-floors' });
  const hint = h('div', { class: 'fab-hint' });
  const wrap = h('div', { class: 'fab-wrap' }, h('div', { class: 'fab-main' }, floorBar, stage, hint));

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
    if (!st.floorId) { st.rooms = []; st.cams = []; st.stairs = []; st.markers = []; st.lines = []; return; }
    const [rooms, cams, stairs, markers, lines] = await Promise.all([
      api.get(`/api/factory/rooms?floor=${st.floorId}`),
      api.get(`/api/factory/cameras?floor=${st.floorId}`),
      api.get(`/api/factory/stairs?floor=${st.floorId}`),
      api.get(`/api/factory/markers?floor=${st.floorId}`),
      api.get(`/api/factory/lines?floor=${st.floorId}`),
    ]);
    st.rooms = rooms; st.cams = cams; st.stairs = stairs; st.markers = markers; st.lines = lines;
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
    // ALTYAPI: kat arka plan planı yükleme + opaklık/ölçek + hizalama (yalnız Düzen modunda)
    if (st.floorId && st.mode === 'edit') floorBar.append(bgControls());
  }

  // ---- Kat arka plan planı (gerçek plan resmi) araçları: yükle / opaklık / ölçek / hizala / kaldır
  function bgControls() {
    const f = st.floors.find(x => x.id === st.floorId);
    const fileInp = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif,image/svg+xml,.svg', style: { display: 'none' } });
    fileInp.addEventListener('change', async () => {
      if (!fileInp.files || !fileInp.files[0]) return;
      const fd = new FormData(); fd.append('file', fileInp.files[0]);
      try { await api.post(`/api/factory/floors/${st.floorId}/background`, fd); await reload(); toast('Kat planı (arka plan) yüklendi'); }
      catch (err) { toastError(err); }
      fileInp.value = '';
    });
    const upBtn = h('button', { class: 'btn ghost sm', type: 'button', title: 'Gerçek kat planı resmini altlık olarak yükle (üzerine çizersiniz)', onclick: () => fileInp.click() },
      f && f.bg_image ? 'Arka planı Değiştir' : 'Arka plan');
    const kids = [h('span', { class: 'fab-bg-sep' }), fileInp, upBtn];
    if (f && f.bg_image) {
      const opa = h('input', { type: 'range', min: 0, max: 1, step: 0.05, value: f.bg_opacity != null ? f.bg_opacity : 0.6, class: 'fab-bg-rng', title: 'Opaklık' });
      opa.addEventListener('input', () => { f.bg_opacity = Number(opa.value); drawCanvas(); });
      opa.addEventListener('change', async () => { await api.patch(`/api/factory/floors/${f.id}`, { bg_opacity: f.bg_opacity }); });
      const scl = h('input', { type: 'range', min: 0.1, max: 4, step: 0.05, value: f.bg_scale || 1, class: 'fab-bg-rng', title: 'Ölçek' });
      scl.addEventListener('input', () => { f.bg_scale = Number(scl.value); drawCanvas(); });
      scl.addEventListener('change', async () => { await api.patch(`/api/factory/floors/${f.id}`, { bg_scale: f.bg_scale }); });
      const align = h('button', { class: `btn ghost sm ${st.bgEdit ? 'on' : ''}`, type: 'button', title: 'Arka planı sürükleyerek hizala',
        onclick: () => { st.bgEdit = !st.bgEdit; drawFloorBar(); drawCanvas(); } }, st.bgEdit ? 'Hizala: Açık' : 'Hizala');
      const rm = h('button', { class: 'btn ghost sm danger', type: 'button',
        onclick: async () => { if (!await confirmDialog('Arka planı kaldır', 'Kat planı arka planı kaldırılsın mı?', { danger: true, okLabel: 'Kaldır' })) return; await api.del(`/api/factory/floors/${st.floorId}/background`); st.bgEdit = false; await reload(); toast('Arka plan kaldırıldı'); } }, 'Kaldır');
      kids.push(h('span', { class: 'fab-bg-field' }, 'Opaklık', opa), h('span', { class: 'fab-bg-field' }, 'Ölçek', scl), align, rm);
    }
    return h('span', { class: 'fab-bgctl' }, kids);
  }

  // Arka plan resmini sürükleyerek konumla (yalnız "Hizala" modunda; autosave bg_x/bg_y)
  function startDragBg(e, f) {
    e.stopPropagation();
    const sx = f.bg_x || 0, sy = f.bg_y || 0, start = toWorld(e.clientX, e.clientY);
    drag(w => { f.bg_x = Math.round(sx + (w.x - start.x)); f.bg_y = Math.round(sy + (w.y - start.y)); drawCanvas(); },
      async () => { await api.patch(`/api/factory/floors/${f.id}`, { bg_x: f.bg_x, bg_y: f.bg_y }); });
  }

  // Arka plan resmini gBg grubuna çiz (doğal boyutu bir kez öğrenip önbelleğe alır; transform ile konum/ölçek)
  const bgNat = {};
  function drawBackground() {
    const f = st.floors.find(x => x.id === st.floorId);
    if (!f || !f.bg_image || st.layers.bg === false) return;
    const href = fileUrl(f.bg_image);
    const nat = bgNat[href];
    const img = s('image', {
      href, 'xlink:href': href,
      width: nat ? nat.w : null, height: nat ? nat.h : null,
      transform: `translate(${f.bg_x || 0} ${f.bg_y || 0}) scale(${f.bg_scale || 1})`,
      opacity: f.bg_opacity != null ? f.bg_opacity : 0.6,
      preserveAspectRatio: 'none',
      class: `fab-bg-img ${st.bgEdit ? 'edit' : ''}`,
      onmousedown: e => { if (st.bgEdit) startDragBg(e, f); },
    });
    if (!nat) {   // doğal boyut bilinmiyor: yükle, önbelleğe al, yeniden çiz
      const probe = new Image();
      probe.onload = () => { bgNat[href] = { w: probe.naturalWidth || 800, h: probe.naturalHeight || 600 }; drawCanvas(); };
      probe.onerror = () => { bgNat[href] = { w: 800, h: 600 }; };
      probe.src = href;
    }
    gBg.append(img);
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

    clear(gStatic); clear(gBg);
    if (!st.floorId) { clear(gOverlay); drawEmptyHint(); return; }
    drawBackground();   // ALTYAPI: gerçek kat planı altlığı (varsa)

    // odalar (dolu yarı saydam poligon + merkez etiket) — "Odalar" katmanı
    if (st.layers.rooms) st.rooms.forEach((r, idx) => {
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

    // merdivenler — "Merdivenler" katmanı
    if (st.layers.stairs) st.stairs.forEach(m => {
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

    // kameralar (ikon + görüş konisi) — "NVR Kameralar" katmanı
    if (st.layers.cams) st.cams.forEach(c => {
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

    // ALTYAPI hatları (network/power kablo güzergâhları) — poli-çizgi; her tür kendi katmanında
    st.lines.forEach(ln => {
      if (!lineVisible(ln)) return;
      const pts = ln.points || [];
      if (pts.length < 2) return;
      const col = lineColor(ln);
      const sel = st.sel && st.sel.type === 'line' && st.sel.id === ln.id;
      gStatic.append(s('polyline', {
        points: pts.map(p => p.join(',')).join(' '),
        class: `fab-line ${sel ? 'sel' : ''}`, fill: 'none', stroke: col,
        'stroke-width': ln.width || 2.5, 'stroke-dasharray': lineDash(ln),
        onclick: e => { if (st.mode === 'edit' && st.tool === 'select') { e.stopPropagation(); selectLine(ln); } },
      }));
      if (ln.label) {
        const mid = pts[Math.floor(pts.length / 2)];
        gStatic.append(s('text', { x: mid[0], y: mid[1] - 6, class: 'fab-line-lbl', 'text-anchor': 'middle', fill: col }, ln.label));
      }
    });

    // ALTYAPI işaretçileri (UPS, priz, WiFi, internet/intranet, switch, planlanan kamera, not) — paletten ikon + renk
    if (st.layers.markers) st.markers.forEach(m => {
      const meta = markerMeta(m.kind);
      const sel = st.sel && st.sel.type === 'marker' && st.sel.id === m.id;
      const g = s('g', { class: `fab-marker ${sel ? 'sel' : ''}`, transform: `translate(${m.x} ${m.y})`,
        onclick: e => { if (st.mode === 'edit' && st.tool === 'select') { e.stopPropagation(); selectMarker(m); } },
        onmousedown: e => startDragMarker(e, m) });
      g.append(s('circle', { cx: 0, cy: 0, r: 11, class: 'fab-marker-badge', fill: meta.color }));
      g.append(s('text', { x: 0, y: 5, class: 'fab-marker-icon', 'text-anchor': 'middle' }, meta.icon));
      if (m.label) g.append(s('text', { x: 15, y: 4, class: 'fab-marker-lbl' }, m.label));
      gStatic.append(g);
    });

    drawOverlay();
  }
  // Bir hattın mevcut katman görünürlüğü (network/power ayrı; other her zaman görünür)
  const lineVisible = ln => (ln.kind === 'power' ? st.layers.power !== false : ln.kind === 'network' ? st.layers.network !== false : true);

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
    // çizilmekte olan hat taslağı
    if (st.lineDraft && st.lineDraft.length) {
      const col = (LINE_KINDS.find(k => k[0] === st.lineKind) || [])[2] || '#2563eb';
      gOverlay.append(s('polyline', { points: st.lineDraft.map(p => p.join(',')).join(' '), class: 'fab-line-draft',
        stroke: col, 'stroke-dasharray': st.lineKind === 'network' ? '7 5' : null }));
      st.lineDraft.forEach(p => gOverlay.append(s('circle', { cx: p[0], cy: p[1], r: 4, class: 'fab-draft-dot' })));
    }
    // seçili hat köşe tutamakları (sürükle → düzenle)
    if (st.mode === 'edit' && st.sel && st.sel.type === 'line') {
      const ln = st.lines.find(x => x.id === st.sel.id);
      if (ln) (ln.points || []).forEach((p, i) => gOverlay.append(s('circle', {
        cx: p[0], cy: p[1], r: 5, class: 'fab-vertex', onmousedown: e => startDragLineVertex(e, ln, i) })));
    }
    // hareket modu izleri
    if (st.mode === 'move') drawMovementOverlay();
    if (st.mode === 'move' && st.live) drawLiveOverlay();
  }

  // ==================================================================== seçim yardımcıları
  const selectRoom = r => { st.sel = { type: 'room', id: r.id }; st.panelOpen = true; drawCanvas(); drawSide(); };
  const selectCam = c => { st.sel = { type: 'cam', id: c.id }; st.panelOpen = true; drawCanvas(); drawSide(); };
  const selectStair = m => { st.sel = { type: 'stair', id: m.id }; st.panelOpen = true; drawCanvas(); drawSide(); };
  const selectMarker = m => { st.sel = { type: 'marker', id: m.id }; st.panelOpen = true; drawCanvas(); drawSide(); };
  const selectLine = ln => { st.sel = { type: 'line', id: ln.id }; st.panelOpen = true; drawCanvas(); drawSide(); };

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
  function startDragLineVertex(e, ln, i) {
    e.stopPropagation();
    drag(w => { ln.points[i] = [Math.round(w.x), Math.round(w.y)]; drawCanvas(); },
      async () => { await api.patch(`/api/factory/lines/${ln.id}`, { points: ln.points }); });
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
    if (st.mode === 'edit' && st.tool === 'line') { addLineVertex(w); return; }
    if (st.mode === 'edit' && (st.tool === 'camera' || st.tool === 'stair' || st.tool === 'marker')) { return; }   // kamera/merdiven/işaretçi: yerleştirme click ile (aşağıda), pan başlatma
    // boş alana tıklama: pan + seçim temizle
    if (st.mode === 'edit' && st.tool === 'select') { st.sel = null; drawSide(); drawOverlay(); }
    const sx = e.clientX, sy = e.clientY, px = st.cam.panX, py = st.cam.panY;
    const mm = ev => { st.cam.panX = px + (ev.clientX - sx); st.cam.panY = py + (ev.clientY - sy); applyCam(); };
    const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
    window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
  });
  // DOKUNMATİK: tek parmak kaydırma (pan) + iki parmak yakınlaştırma (pinch zoom). Tap (yerleştirme/seçim) korunur.
  let touchPan = null, pinch = null;
  const tDist = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  svg.addEventListener('touchstart', e => {
    if (e.touches.length === 1) {
      const t = e.touches[0];
      touchPan = { sx: t.clientX, sy: t.clientY, px: st.cam.panX, py: st.cam.panY, moved: false };
      pinch = null;
    } else if (e.touches.length === 2) {
      e.preventDefault();
      const r = svg.getBoundingClientRect(), m = { x: (e.touches[0].clientX + e.touches[1].clientX) / 2, y: (e.touches[0].clientY + e.touches[1].clientY) / 2 };
      pinch = { d: tDist(e.touches[0], e.touches[1]) || 1, scale: st.cam.scale, panX: st.cam.panX, panY: st.cam.panY, mx: m.x - r.left, my: m.y - r.top };
      touchPan = null;
    }
  }, { passive: false });
  svg.addEventListener('touchmove', e => {
    if (pinch && e.touches.length === 2) {
      e.preventDefault();
      const ns = Math.max(0.2, Math.min(5, pinch.scale * (tDist(e.touches[0], e.touches[1]) / pinch.d)));
      st.cam.panX = pinch.mx - (pinch.mx - pinch.panX) * (ns / pinch.scale);   // iki parmağın ortası sabit kalsın
      st.cam.panY = pinch.my - (pinch.my - pinch.panY) * (ns / pinch.scale);
      st.cam.scale = ns; applyCam();
    } else if (touchPan && e.touches.length === 1) {
      const t = e.touches[0], dx = t.clientX - touchPan.sx, dy = t.clientY - touchPan.sy;
      if (!touchPan.moved && Math.hypot(dx, dy) < 6) return;   // küçük hareket = tap (pan değil) → yerleştirme/seçim bozulmasın
      touchPan.moved = true; e.preventDefault();
      st.cam.panX = touchPan.px + dx; st.cam.panY = touchPan.py + dy; applyCam();
    }
  }, { passive: false });
  svg.addEventListener('touchend', e => { if (e.touches.length < 2) pinch = null; if (e.touches.length === 0) touchPan = null; });

  // oda / hat çizimini bitir: çift tık ya da Enter
  svg.addEventListener('dblclick', e => { e.preventDefault(); if (st.tool === 'room') finishRoom(); else if (st.tool === 'line') finishLine(); });
  const onKey = e => {
    if (st.mode !== 'edit') return;
    if (e.key === 'Enter' && st.tool === 'room') finishRoom();
    else if (e.key === 'Enter' && st.tool === 'line') finishLine();
    else if (e.key === 'Escape') { st.draft = null; st.lineDraft = null; drawOverlay(); }
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
    if (st.mode === 'edit' && st.tool === 'marker' && pendingMarkerKind) {
      const w = toWorld(e.clientX, e.clientY);
      placeMarkerAt(pendingMarkerKind, Math.round(w.x), Math.round(w.y));
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

  // -------------------------------------------------------------------- ALTYAPI işaretçisi (palet) yerleştirme
  let pendingMarkerKind = null;   // "İşaretçi Koy" aktifken plana konacak işaretçi türü
  function pickMarkerKind() {
    const grid = h('div', { class: 'fab-mk-pick' }, MARKER_ORDER.map(k => {
      const meta = MARKER_PALETTE[k];
      return h('button', { class: 'fab-mk-opt', type: 'button',
        onclick: () => { pendingMarkerKind = k; st.tool = 'marker'; m.close(); drawSide(); hintText(`${meta.label}: yerleştirmek için plana tıklayın`); } },
        h('span', { class: 'fab-mk-ic', style: { background: meta.color } }, meta.icon), h('span', null, meta.label));
    }));
    const m = modal({ title: 'İşaretçi türü seç', body: grid, actions: [{ label: 'Kapat' }] });
  }
  async function placeMarkerAt(kind, x, y) {
    await api.post('/api/factory/markers', { floor_id: st.floorId, kind, label: '', x, y });
    pendingMarkerKind = null; st.tool = 'select';
    await loadFloorData(); drawCanvas(); drawSide();
    toast(`${markerMeta(kind).label} eklendi`);
  }

  // -------------------------------------------------------------------- ALTYAPI hattı (network/power) çizimi
  function addLineVertex(w) {
    if (!st.lineDraft) st.lineDraft = [];
    st.lineDraft.push([Math.round(w.x), Math.round(w.y)]);
    drawOverlay();
  }
  async function finishLine() {
    if (!st.lineDraft || st.lineDraft.length < 2) { st.lineDraft = null; drawOverlay(); return toast('Hat için en az 2 nokta gerekli', 'err'); }
    const pts = st.lineDraft.slice(); st.lineDraft = null;
    const kind = st.lineKind || 'network';
    await api.post('/api/factory/lines', { floor_id: st.floorId, kind, points: pts });
    st.tool = 'select'; await loadFloorData(); drawCanvas(); drawSide();
    toast(kind === 'power' ? 'Elektrik hattı eklendi' : kind === 'network' ? 'Network hattı eklendi' : 'Hat eklendi');
  }

  // -------------------------------------------------------------------- seçili öğeyi sil
  async function deleteSelected() {
    const sel = st.sel; if (!sel) return;
    const map = { room: ['rooms', 'Oda'], cam: ['cameras', 'Kamera'], stair: ['stairs', 'Merdiven'],
      marker: ['markers', 'İşaretçi'], line: ['lines', 'Hat'] };
    const [path, label] = map[sel.type];
    if (!await confirmDialog(`${label} sil`, `${label} silinsin mi?`, { danger: true, okLabel: 'Sil' })) return;
    await api.del(`/api/factory/${path}/${sel.id}`);
    st.sel = null; if (sel.type === 'cam') await loadAvail();
    await loadFloorData(); drawCanvas(); drawSide(); toast(`${label} silindi`);
  }

  // ==================================================================== SAĞ PANEL
  // ---- Araç seçimi (hem yüzen araç çubuğu hem kısayollar buradan geçer)
  function setTool(key, opts = {}) {
    st.tool = key; st.draft = null; st.lineDraft = null;
    if (key === 'line' && opts.lineKind) st.lineKind = opts.lineKind;
    if (key === 'camera') pickCamera();
    else if (key === 'marker') pickMarkerKind();
    else if (key === 'stair') hintText('Merdiven koymak için plana tıklayın');
    else if (key === 'line') hintText(`${st.lineKind === 'power' ? 'Elektrik' : st.lineKind === 'network' ? 'Network' : 'Hat'} hattı: noktaları tıklayın; bitirmek için çift tık ya da Enter.`);
    else hintText('');
    drawSide(); drawOverlay();
  }

  // ---- Yüzen araç çubuğunu sürükle (konumu localStorage'da sakla); pan/zoom'u etkilemez (ayrı DOM katmanı)
  function toolbarDrag(e) {
    e.preventDefault(); e.stopPropagation();
    const pt = (e.touches && e.touches[0]) || e;
    const stageR = stage.getBoundingClientRect(), tbR = toolbarEl.getBoundingClientRect();
    const offX = pt.clientX - tbR.left, offY = pt.clientY - tbR.top;
    const move = (cx, cy) => {
      let x = cx - stageR.left - offX, y = cy - stageR.top - offY;
      x = Math.max(0, Math.min(x, stageR.width - tbR.width));
      y = Math.max(0, Math.min(y, stageR.height - tbR.height));
      toolbarEl.style.left = `${x}px`; toolbarEl.style.top = `${y}px`; toolbarEl.style.right = 'auto';
      if (!side.hidden) positionPanel();
    };
    const mm = ev => move(ev.clientX, ev.clientY);
    const tm = ev => { if (ev.touches[0]) { ev.preventDefault(); move(ev.touches[0].clientX, ev.touches[0].clientY); } };
    const up = () => {
      window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', up);
      window.removeEventListener('touchmove', tm); window.removeEventListener('touchend', up);
      const r = toolbarEl.getBoundingClientRect(), sr = stage.getBoundingClientRect();
      try { localStorage.setItem(TB_KEY, JSON.stringify({ x: r.left - sr.left, y: r.top - sr.top })); } catch { /* sessiz */ }
    };
    window.addEventListener('mousemove', mm); window.addEventListener('mouseup', up);
    window.addEventListener('touchmove', tm, { passive: false }); window.addEventListener('touchend', up);
  }
  function applyToolbarPos() {
    let p = null; try { p = JSON.parse(localStorage.getItem(TB_KEY) || 'null'); } catch { /* yoksa öntanımlı */ }
    if (p && typeof p.x === 'number') { toolbarEl.style.left = `${p.x}px`; toolbarEl.style.top = `${p.y}px`; toolbarEl.style.right = 'auto'; }
  }

  // ---- Yüzen "Seçenekler" paneli: araç çubuğundaki düğmeyle açılır; konumu araç çubuğuna göre hizalanır
  let panelBtnEl = null;
  function setPanel(open) {
    st.panelOpen = !!open;
    try { localStorage.setItem(PANEL_KEY, st.panelOpen ? '1' : '0'); } catch { /* sessiz */ }
    applyPanel();
  }
  function applyPanel() {
    side.hidden = !st.panelOpen;
    if (panelBtnEl) { panelBtnEl.classList.toggle('on', st.panelOpen); panelBtnEl.setAttribute('aria-pressed', st.panelOpen ? 'true' : 'false'); }
    if (st.panelOpen) positionPanel();
  }
  function positionPanel() {
    if (side.hidden) return;
    const sr = stage.getBoundingClientRect(), tr = toolbarEl.getBoundingClientRect();
    const pw = side.offsetWidth || 290, ph = side.offsetHeight || 300;
    let left = (tr.right - sr.left) + 8;                 // öntanımlı: araç çubuğunun sağına
    if (left + pw > sr.width - 8) left = (tr.left - sr.left) - pw - 8;   // sığmazsa soluna
    left = Math.max(8, Math.min(left, sr.width - pw - 8));
    let top = Math.max(8, Math.min(tr.top - sr.top, sr.height - ph - 8));
    side.style.left = `${left}px`; side.style.top = `${top}px`;
  }
  // ---- Yüzen ikon araç çubuğunu kur (aktif araç vurgulanır). Her buton: net ikon + Türkçe title/aria-label.
  function buildToolbar() {
    const grip = h('div', { class: 'fab-tb-grip', title: 'Araç çubuğunu taşı (sürükleyin)', onmousedown: toolbarDrag, ontouchstart: toolbarDrag });
    grip.append(TOOL_ICON.grip());
    const btn = (title, iconKey, onClick, active) => {
      const b = h('button', { class: `fab-tb-btn ${active ? 'on' : ''}`, type: 'button', title, 'aria-label': title, 'aria-pressed': active ? 'true' : 'false', onclick: onClick });
      b.append(TOOL_ICON[iconKey]());
      return b;
    };
    // Seçenekler panelini açıp kapatan düğme (her iki modda): basınca sağ paneldeki seçenekler menü olarak gelir.
    panelBtnEl = btn(st.mode === 'move' ? 'Seçenekler: Hareket & Canlı Durum' : 'Seçenekler: Özellikler & Katmanlar',
      'panel', () => setPanel(!st.panelOpen), st.panelOpen);
    if (st.mode === 'move') { clear(toolbarEl, grip, panelBtnEl); return; }
    clear(toolbarEl, grip,
      btn('Seç / Taşı', 'select', () => setTool('select'), st.tool === 'select'),
      btn('Oda Çiz', 'room', () => setTool('room'), st.tool === 'room'),
      btn('Kamera Koy (NVR)', 'camera', () => setTool('camera'), st.tool === 'camera'),
      btn('İşaretçi Koy (UPS / priz / WiFi / internet / switch / kamera / not)', 'marker', () => setTool('marker'), st.tool === 'marker'),
      h('div', { class: 'fab-tb-sep' }),
      btn('Network Hattı Çiz', 'net', () => setTool('line', { lineKind: 'network' }), st.tool === 'line' && st.lineKind === 'network'),
      btn('Elektrik Hattı Çiz', 'power', () => setTool('line', { lineKind: 'power' }), st.tool === 'line' && st.lineKind === 'power'),
      h('div', { class: 'fab-tb-sep' }),
      btn('Merdiven Koy', 'stair', () => setTool('stair'), st.tool === 'stair'),
      btn('Arka Plan Planı Yükle', 'bg', () => { if (!st.floorId) return toast('Önce bir kat seçin', 'err'); tbBgInp.click(); }, false),
      h('div', { class: 'fab-tb-sep' }),
      panelBtnEl);
  }

  function drawSide() {
    buildToolbar(); toolbarEl.hidden = false;
    if (st.mode === 'move') { drawMoveSide(); return; }   // hareket içeriğini doldurur, sonunda applyPanel çağırır
    // DÜZEN: araçlar yüzen ikon çubuğunda; seçenekler paneli = aktif araç notu + seçili öğe özellikleri + katmanlar
    const note = st.tool === 'room' ? 'Köşe eklemek için tıklayın; bitirmek için çift tık ya da Enter. Vazgeç: Esc.'
      : st.tool === 'line' ? 'Hat için noktaları tıklayın; bitirmek için çift tık ya da Enter. Vazgeç: Esc.'
        : st.tool === 'marker' ? 'İşaretçiyi yerleştirmek için plana tıklayın.'
          : st.tool === 'stair' ? 'Merdiven koymak için plana tıklayın.' : null;
    clear(sideBody,
      h('h3', { class: 'fab-side-h' }, 'Özellikler'),
      note ? h('div', { class: 'fab-note' }, note) : h('div', { class: 'fab-note muted' }, 'Araçlar tuval üzerindeki yüzen ikon çubuğundadır.'),
      selProps(),
      layersPanel());
    drawFloorBar();
    applyPanel();
  }

  // Katmanlar paneli: her kategori bağımsız gösterilir/gizlenir (cihaz başına localStorage'da saklanır)
  function layersPanel() {
    const rows = LAYER_DEFS.map(([k, lbl]) => {
      const cb = h('input', { type: 'checkbox', checked: st.layers[k] !== false });
      cb.addEventListener('change', () => { st.layers[k] = cb.checked; saveLayers(st.layers); drawCanvas(); });
      return h('label', { class: 'fab-layer' }, cb, h('span', null, lbl));
    });
    return h('div', { class: 'fab-layers' }, h('h3', { class: 'fab-side-h' }, 'Katmanlar'), rows);
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
    if (st.sel.type === 'marker') {
      const m = st.markers.find(x => x.id === st.sel.id); if (!m) return null;
      const kindSel = h('select', { class: 'input' }, MARKER_ORDER.map(k =>
        h('option', { value: k, selected: k === m.kind }, `${MARKER_PALETTE[k].icon} ${MARKER_PALETTE[k].label}`)));
      kindSel.addEventListener('change', async () => { m.kind = kindSel.value; await api.patch(`/api/factory/markers/${m.id}`, { kind: m.kind }); drawCanvas(); drawSide(); });
      const lbl = h('input', { class: 'input', value: m.label || '' });
      lbl.addEventListener('change', async () => { m.label = lbl.value.trim(); await api.patch(`/api/factory/markers/${m.id}`, { label: m.label }); drawCanvas(); });
      return h('div', { class: 'fab-props' }, h('h4', null, `${markerMeta(m.kind).icon} ${markerMeta(m.kind).label}`),
        field('Tür', kindSel), field('Etiket (ör. ad / adet)', lbl),
        h('button', { class: 'btn danger sm', type: 'button', onclick: deleteSelected }, 'İşaretçiyi Sil'));
    }
    if (st.sel.type === 'line') {
      const ln = st.lines.find(x => x.id === st.sel.id); if (!ln) return null;
      const kindSel = h('select', { class: 'input' }, LINE_KINDS.map(([k, l]) => h('option', { value: k, selected: k === ln.kind }, l)));
      kindSel.addEventListener('change', async () => { ln.kind = kindSel.value; await api.patch(`/api/factory/lines/${ln.id}`, { kind: ln.kind }); drawCanvas(); });
      const colr = h('input', { class: 'input', type: 'color', value: lineColor(ln) });
      colr.addEventListener('change', async () => { ln.color = colr.value; await api.patch(`/api/factory/lines/${ln.id}`, { color: ln.color }); drawCanvas(); });
      const lbl = h('input', { class: 'input', value: ln.label || '' });
      lbl.addEventListener('change', async () => { ln.label = lbl.value.trim(); await api.patch(`/api/factory/lines/${ln.id}`, { label: ln.label }); drawCanvas(); });
      const wdt = h('input', { class: 'input', type: 'number', min: 1, max: 12, step: 0.5, value: ln.width || 2.5 });
      wdt.addEventListener('change', async () => { ln.width = Number(wdt.value) || 2.5; await api.patch(`/api/factory/lines/${ln.id}`, { width: ln.width }); drawCanvas(); });
      return h('div', { class: 'fab-props' }, h('h4', null, 'Hat'),
        field('Tür', kindSel), field('Renk', colr), field('Etiket', lbl), field('Kalınlık', wdt),
        h('div', { class: 'fab-note muted' }, 'Köşeleri tuval üzerindeki tutamakları sürükleyerek düzenleyebilirsiniz.'),
        h('button', { class: 'btn danger sm', type: 'button', onclick: deleteSelected }, 'Hattı Sil'));
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

    clear(sideBody,
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
    applyPanel();
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
    applyToolbarPos();   // yüzen araç çubuğunun kayıtlı konumunu uygula (varsa)
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
  /* Seçenekler paneli artık tuval üzerinde YÜZEN popover (araç çubuğu düğmesiyle açılır) */
  .fab-side.fab-pop{position:absolute;left:58px;top:12px;z-index:6;width:290px;max-height:calc(100% - 24px);overflow:auto;touch-action:pan-y;
    background:var(--card,#fff);border:1px solid var(--line,#e5e7eb);border-radius:10px;padding:12px;
    box-shadow:0 12px 34px rgba(15,23,42,.22)}
  .fab-side[hidden]{display:none}
  .fab-pop-hdr{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:-12px -12px 10px;padding:8px 12px;
    border-bottom:1px solid var(--line,#e5e7eb);position:sticky;top:-12px;background:var(--card,#fff);border-radius:10px 10px 0 0;z-index:1}
  .fab-pop-ttl{font-weight:600;font-size:13px;color:var(--muted,#64748b);letter-spacing:.02em}
  .fab-pop-x{border:none;background:transparent;cursor:pointer;font-size:14px;line-height:1;color:#94a3b8;padding:3px 7px;border-radius:6px}
  .fab-pop-x:hover{background:var(--bg2,#f1f5f9);color:#1e293b}
  .fab-side-h{margin:4px 0 8px;font-size:15px}
  .fab-floors{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px}
  .fab-floors-lbl{font-size:12px;color:var(--muted,#6b7280)}
  .fab-floor{padding:4px 12px;border:1px solid var(--line,#e5e7eb);background:var(--card,#fff);border-radius:16px;cursor:pointer;font-size:13px}
  .fab-floor.on{background:var(--pri,#2563eb);color:#fff;border-color:var(--pri,#2563eb)}
  .fab-floor.add{border-style:dashed;color:var(--muted,#6b7280)}
  .fab-stage{flex:1;position:relative;border:1px solid var(--line,#e5e7eb);border-radius:10px;overflow:hidden;background:var(--bg2,#f8fafc);touch-action:none}
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

  /* ALTYAPI: arka plan planı resmi (altlık) */
  .fab-bg-img{pointer-events:none}
  .fab-bg-img.edit{pointer-events:auto;cursor:move;outline:2px dashed #2563eb;outline-offset:2px}
  /* ALTYAPI: hatlar (network/power kablo güzergâhları) */
  .fab-line{vector-effect:non-scaling-stroke;cursor:pointer;opacity:.9}
  .fab-line.sel{opacity:1;filter:drop-shadow(0 0 3px rgba(37,99,235,.7))}
  .fab-line-lbl{font:600 10px system-ui;pointer-events:none}
  .fab-line-draft{fill:none;stroke-width:2.5;vector-effect:non-scaling-stroke;opacity:.8}
  /* ALTYAPI: paletli işaretçiler */
  .fab-marker{cursor:move}
  .fab-marker-badge{fill-opacity:.92;stroke:#fff;stroke-width:1.4}
  .fab-marker.sel .fab-marker-badge{stroke:#2563eb;stroke-width:2.4}
  .fab-marker-icon{font-size:12px;pointer-events:none;dominant-baseline:middle}
  .fab-marker-lbl{font:600 11px system-ui;fill:#334155;pointer-events:none}
  /* İşaretçi palet seçici (modal) */
  .fab-mk-pick{display:grid;grid-template-columns:1fr 1fr;gap:6px}
  .fab-mk-opt{display:flex;align-items:center;gap:8px;text-align:left;padding:8px 10px;border:1px solid var(--line,#e5e7eb);border-radius:8px;background:var(--card,#fff);cursor:pointer;font-size:13px}
  .fab-mk-opt:hover{background:var(--bg2,#f1f5f9)}
  .fab-mk-ic{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;color:#fff;font-size:14px;flex:0 0 24px}
  /* Katmanlar paneli */
  .fab-layers{margin-top:12px;border-top:1px solid var(--line,#e5e7eb);padding-top:8px}
  .fab-layer{display:flex;align-items:center;gap:8px;padding:3px 0;font-size:13px;cursor:pointer}
  .fab-layer input{width:15px;height:15px}
  /* Kat çubuğundaki arka plan kontrolleri */
  .fab-bgctl{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap}
  .fab-bg-sep{width:1px;height:18px;background:var(--line,#e5e7eb);margin:0 2px}
  .fab-bg-field{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--muted,#6b7280)}
  .fab-bg-rng{width:80px}
  .btn.ghost.sm.on{background:var(--pri,#2563eb);color:#fff;border-color:var(--pri,#2563eb)}

  /* Photoshop tarzı YÜZEN ikon araç çubuğu */
  .fab-toolbar{position:absolute;left:12px;top:12px;z-index:5;display:flex;flex-direction:column;align-items:center;gap:4px;
    padding:5px;background:var(--card,#fff);border:1px solid var(--line,#e5e7eb);border-radius:12px;
    box-shadow:0 6px 20px rgba(15,23,42,.18);user-select:none}
  .fab-tb-grip{display:flex;align-items:center;justify-content:center;width:34px;height:18px;cursor:grab;color:#94a3b8;border-radius:6px;touch-action:none}
  .fab-tb-grip:active{cursor:grabbing}
  .fab-tb-sep{width:22px;height:1px;background:var(--line,#e5e7eb);margin:2px 0}
  .fab-tb-btn{display:flex;align-items:center;justify-content:center;width:34px;height:34px;padding:0;border:1px solid transparent;border-radius:8px;background:transparent;cursor:pointer;color:#475569}
  .fab-tb-btn:hover{background:var(--bg2,#f1f5f9);color:#1e293b}
  .fab-tb-btn.on{background:var(--pri,#2563eb);color:#fff}
  .fab-ti{width:20px;height:20px;display:block;fill:currentColor;stroke:none}
  .fab-ti [fill="none"]{fill:none;stroke:currentColor;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
  `;
  const styleEl = document.createElement('style');
  styleEl.id = 'fab-style';
  styleEl.textContent = css;
  document.head.append(styleEl);
}
