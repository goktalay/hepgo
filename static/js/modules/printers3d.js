// Yazıcı Yönetimi → 3B görünüm: yazıcı odası. Ortada koridor, sağda ve solda iki katlı raflarda Creality K2 Plus'lar.
// Yazıcının yeri (taraf / kat / sıra) sunucuda tutulur (printers.rack_*); tıklanan yazıcının ayrıntısı pencerede açılır,
// "Yerini değiştir" ile başka rafa taşınır (dolu rafta yer değiştirilir). Durum her yenilemede renk ve etiketle güncellenir.
// Three.js yerel kopyadan (static/vendor/three) yalnızca bu görünüm açılınca yüklenir.
import { api } from '../api.js';
import { loadPath, partObject } from '../gcode3d.js';
import { PRINTER_STATES, badge } from '../status.js';
import { clear, field, fmtDateTime, h, modal, onLeave, segmented, t, toast } from '../ui.js';

const LIB = '/static/vendor/three/';
let libs;
const LIB_FILES = ['three.module.min.js', 'OrbitControls.js', 'CSS2DRenderer.js', 'RoomEnvironment.js'];
const loadLibs = () => (libs ??= Promise.all(LIB_FILES.map(f => import(LIB + f))).catch(err => { libs = null; throw err; }));

// Ölçüler (metre). K2 Plus gövdesi yaklaşık 0,50 × 0,52 × 0,69; üstünde CFS filament kutusu.
const P = { w: 0.5, d: 0.52, h: 0.69, cfsH: 0.2 };
const PITCH = 0.64;                       // raftaki yazıcı aralığı
const SHELF = [0.12, 1.18];               // alt / üst kat raf yüzeyi yüksekliği
const RACK_H = 2.15, RACK_D = 0.68;
const AISLE = 2.2;                        // koridor genişliği
const RACK_X = AISLE / 2 + RACK_D / 2;    // raf merkezinin koridor ortasına uzaklığı
// Girişten (−z) içeri (+z) bakana göre: sol raf +x, sağ raf −x tarafında
const sideX = side => (side === 'L' ? RACK_X : -RACK_X);
export const STATE_COLORS = {
  YAZDIRIYOR: 0x3b82f6, HAZIR: 0x22c55e, TAMAMLANDI: 0xa855f7, DURAKLADI: 0xf59e0b, HATA: 0xef4444, CEVRIMDISI: 0x4b5563,
};
const SIDE_TEXT = { L: 'Sol raf', R: 'Sağ raf' };
const LEVEL_TEXT = { 1: 'Alt kat', 2: 'Üst kat' };
// Basılan parça: sistemdeki sipariş parçası; yoksa yazıcıdaki dosya adından tanınan parça (sunucu: file_part)
export const partOf = p => p.current_part || p.file_part || null;
export const placeText = p => (p.rack_side ? t('{side} · {level} · {slot}. sıra', { side: SIDE_TEXT[p.rack_side], level: LEVEL_TEXT[p.rack_level], slot: p.rack_slot }) : 'Yeri yok');

/**
 * @returns {{ el, update(printers), destroy() }}
 * opts: canEdit (yerleşim değiştirebilir mi), canOpen (üretim siparişine bağlantı), reload()
 */
export function printerRoom(opts) {
  const stage = h('div', { class: 'pr3d-stage' }, h('div', { class: 'pr3d-loading' }, '3B oda hazırlanıyor…'));
  const legend = h('div', { class: 'pr3d-legend' }, Object.entries(PRINTER_STATES).map(([k, s]) =>
    h('span', null, h('i', { style: { background: `#${STATE_COLORS[k].toString(16).padStart(6, '0')}` } }), s.label)));
  const views = segmented([['entry', 'Giriş'], ['L', 'Sol raf'], ['R', 'Sağ raf'], ['top', 'Genel']], 'entry', v => room?.view(v));
  // Tam ekran: oda sabit katman olarak tüm ekranı kaplar ve tarayıcı tam ekrana geçer (açılan pencereler görünür kalsın diye
  // odanın kendisi değil sayfa tam ekrana alınır)
  const fullBtn = h('button', { class: 'btn', type: 'button', onclick: () => setFull(!el.classList.contains('pr3d-full')) });
  const el = h('div', { class: 'pr3d' },
    h('div', { class: 'pr3d-bar' }, views, h('span', { class: 'spacer' }), legend,
      h('a', { class: 'btn', href: '/app#/tv/printers', target: '_blank', rel: 'noopener', title: 'Ofis monitörleri için: tam ekran, kendiliğinden dolaşan canlı görünüm' }, 'TV Ekranı ↗'), fullBtn),
    stage);
  const drawFullBtn = () => { fullBtn.textContent = el.classList.contains('pr3d-full') ? 'Tam ekrandan çık' : 'Tam ekran'; };
  function setFull(on) {
    el.classList.toggle('pr3d-full', on);
    document.body.classList.toggle('pr3d-lock', on);
    drawFullBtn();
    if (on && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  const onFsChange = () => { if (!document.fullscreenElement && el.classList.contains('pr3d-full')) setFull(false); };
  document.addEventListener('fullscreenchange', onFsChange);
  drawFullBtn();
  let room = null, printers = [], selected = null, dead = false, info = null;

  // Yazıcı bilgisi: tıklanınca açılan pencere; açıkken yenilenen durumla güncellenir
  const infoBody = p => {
    const st = p.live_state || 'CEVRIMDISI';
    return h('div', null,
      h('div', { class: 'pr3d-title' }, badge(PRINTER_STATES, st)),
      st === 'YAZDIRIYOR' || st === 'DURAKLADI' ? h('div', { class: 'print-progress', style: { margin: '6px 0 12px', maxWidth: 'none' } },
        h('div', { class: 'track' }, h('i', { class: st === 'DURAKLADI' ? 'paused' : '', style: { width: `${p.live_progress || 0}%` } })),
        h('span', null, `%${Math.floor(p.live_progress || 0)}`)) : null,
      h('dl', { class: 'kv' },
        h('dt', null, 'Yeri'), h('dd', null, placeText(p)),
        h('dt', null, 'IP'), h('dd', { class: 'mono' }, p.ip),
        h('dt', null, 'Model'), h('dd', null, p.model || '—'),
        h('dt', null, 'Dosya'), h('dd', { class: 'mono small' }, p.live_file || '—'),
        h('dt', null, 'Sistemde'), h('dd', null, p.current_part
          ? (opts.canOpen ? h('a', { href: `#/production/${p.current_order_id}` }, `${p.current_order} / ${p.current_part}`) : `${p.current_order} / ${p.current_part}`)
          : p.file_part ? t('{part} (dosya adından; sistemde siparişi yok)', { part: p.file_part }) : 'İş yok'),
        h('dt', null, 'Son görülme'), h('dd', null, fmtDateTime(p.last_seen))));
  };
  function openInfo(id) {
    const p = printers.find(x => x.id === id);
    if (!p) return;
    info?.close();
    selected = id;
    room?.select(id);
    const box = h('div', { class: 'pr3d-info' }, infoBody(p));
    const view3d = h('div', { class: 'pr3d-solo' });
    const soloView = room?.solo(view3d, p);
    const m = modal({
      title: p.name, wide: true,
      body: h('div', { class: 'pr3d-pop' }, view3d, box),
      onClose: () => { soloView?.destroy(); if (info?.id === id) { info = null; selected = null; room?.select(null); } },
      actions: [
        opts.canEdit ? { label: 'Yerini Değiştir', onClick: () => { moveDialog(p); } } : null,
        { label: 'Kapat', class: 'primary' },
      ].filter(Boolean),
    });
    info = { id, box, close: m.close, solo: soloView };
  }

  // Yer değiştirme: hedef raf doluysa iki yazıcı yer değiştirir
  function moveDialog(p) {
    const perRow = Math.max(15, ...printers.map(x => x.rack_slot || 0));
    const side = h('select', { class: 'input' }, Object.entries(SIDE_TEXT).map(([k, t]) => h('option', { value: k, selected: k === p.rack_side }, t)));
    const level = h('select', { class: 'input' }, Object.entries(LEVEL_TEXT).map(([k, t]) => h('option', { value: k, selected: Number(k) === p.rack_level }, t)));
    const slot = h('select', { class: 'input' });
    const info = h('div', { class: 'small muted', style: { marginTop: '-4px' } });
    const fill = () => {
      const cur = slot.value || p.rack_slot;
      clear(slot, Array.from({ length: perRow + 1 }, (_, i) => i + 1).map(n => {
        const o = printers.find(x => x.id !== p.id && x.rack_side === side.value && x.rack_level === Number(level.value) && x.rack_slot === n);
        return h('option', { value: n, selected: n === Number(cur) }, t('{n}. sıra{extra}', { n, extra: o ? ` — ${o.name}` : t(' — boş') }));
      }));
      const o = occupant();
      info.textContent = o ? t('Bu rafta {name} var; iki yazıcının yeri değiştirilecek.', { name: o.name }) : 'Boş raf.';
    };
    const occupant = () => printers.find(x => x.id !== p.id && x.rack_side === side.value && x.rack_level === Number(level.value) && x.rack_slot === Number(slot.value));
    side.addEventListener('change', fill);
    level.addEventListener('change', fill);
    slot.addEventListener('change', fill);
    fill();
    modal({
      title: t('{name} — Yerini değiştir', { name: p.name }),
      body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, t('Şu an: {place}', { place: placeText(p) })),
        h('div', { class: 'row' }, field('Taraf', side), field('Kat', level)), field('Sıra (1 = girişe en yakın)', slot), info),
      actions: [
        { label: 'Vazgeç' },
        {
          label: 'Kaydet', class: 'primary', onClick: async () => {
            const o = occupant();
            const items = [{ id: p.id, side: side.value, level: Number(level.value), slot: Number(slot.value) }];
            if (o) items.push({ id: o.id, side: p.rack_side, level: p.rack_level, slot: p.rack_slot });
            await api.put('/api/printers/layout', { items });
            toast(o ? t('{a} ile {b} yer değiştirdi', { a: p.name, b: o.name }) : t('{name} taşındı', { name: p.name }));
            opts.reload();
          },
        },
      ],
    });
  }

  loadLibs().then(mods => {
    if (dead) return;
    room = buildRoom(stage, mods, openInfo);
    room.set(printers);
  }).catch(err => clear(stage, h('div', { class: 'alert err', style: { margin: '16px' } }, t('3B görünüm yüklenemedi: {msg}', { msg: err.message }))));

  const api3d = {
    el,
    tour: on => { const go = () => room ? room.tour(on) : setTimeout(go, 300); go(); },
    update(list) {
      printers = list;
      room?.set(list);
      const p = info && printers.find(x => x.id === info.id);
      if (p) { clear(info.box, infoBody(p)); info.solo?.update(p); }
    },
    destroy() {
      dead = true;
      if (el.classList.contains('pr3d-full')) setFull(false);
      document.removeEventListener('fullscreenchange', onFsChange);
      room?.dispose();
    },
  };
  onLeave(() => api3d.destroy());
  return api3d;
}

// ---------- Sahne ----------
function buildRoom(stage, [THREE, { OrbitControls }, { CSS2DRenderer, CSS2DObject }, { RoomEnvironment }], onPick) {
  clear(stage);
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const css = new CSS2DRenderer();
  css.domElement.className = 'pr3d-labels';
  stage.append(renderer.domElement, css.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xdfe4ea);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI * 0.495;
  controls.minDistance = 0.8;
  controls.maxDistance = 30;

  // Işık: tavan panelleri + yumuşak dolgu; tek gölge veren yönlü ışık
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  scene.add(sun, sun.target);

  const mat = {
    body: new THREE.MeshStandardMaterial({ color: 0x1b1d21, roughness: 0.55, metalness: 0.35 }),
    trim: new THREE.MeshStandardMaterial({ color: 0x2b2f36, roughness: 0.4, metalness: 0.6 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0xaec3d6, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.22, depthWrite: false }),
    bed: new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.85, metalness: 0.2 }),
    bedTop: new THREE.MeshStandardMaterial({ color: 0x3b3b3b, roughness: 0.6, metalness: 0.5 }),
    rail: new THREE.MeshStandardMaterial({ color: 0x9aa1ab, roughness: 0.3, metalness: 0.9 }),
    head: new THREE.MeshStandardMaterial({ color: 0xe9ebee, roughness: 0.45, metalness: 0.1 }),
    cfs: new THREE.MeshStandardMaterial({ color: 0x2a2d33, roughness: 0.5, metalness: 0.3 }),
    cfsLid: new THREE.MeshPhysicalMaterial({ color: 0x9fb2c4, roughness: 0.1, transparent: true, opacity: 0.35, depthWrite: false }),
    screen: new THREE.MeshStandardMaterial({ color: 0x0b1220, emissive: 0x1e3a8a, emissiveIntensity: 0.9, roughness: 0.3 }),
    logo: new THREE.MeshStandardMaterial({ color: 0xd1d5db, roughness: 0.4, metalness: 0.7 }),
    post: new THREE.MeshStandardMaterial({ color: 0x2f3a4a, roughness: 0.5, metalness: 0.7 }),
    beam: new THREE.MeshStandardMaterial({ color: 0xe56b1f, roughness: 0.5, metalness: 0.4 }),
    deck: new THREE.MeshStandardMaterial({ color: 0xb9bec6, roughness: 0.7, metalness: 0.5 }),
    wall: new THREE.MeshStandardMaterial({ color: 0xeef1f4, roughness: 0.95 }),
    lamp: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 1.2 }),
    select: new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.25, depthWrite: false }),
  };
  const spools = [0xe11d48, 0x2563eb, 0xf5f5f5, 0x111827].map(c => new THREE.MeshStandardMaterial({ color: c, roughness: 0.6 }));
  const partMat = new THREE.MeshStandardMaterial({ color: 0xf97316, roughness: 0.7 });
  // Gövde: koyu gri, durum rengine doğru kısık (≈%10) boyanır
  const bodyMats = Object.fromEntries(Object.entries(STATE_COLORS).map(([k, c]) =>
    [k, new THREE.MeshStandardMaterial({ color: new THREE.Color(0x1b1d21).lerp(new THREE.Color(c), k === 'CEVRIMDISI' ? 0.04 : 0.1),
      roughness: 0.55, metalness: 0.35 })]));
  const stateMats = Object.fromEntries(Object.entries(STATE_COLORS).map(([k, c]) =>
    [k, new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: k === 'CEVRIMDISI' ? 0.1 : 1.6 })]));
  const box = (w, hh, d) => new THREE.BoxGeometry(w, hh, d);
  const geo = {
    side: box(0.025, P.h, P.d), back: box(P.w, P.h, 0.025), base: box(P.w, 0.11, P.d), topFrame: box(P.w, 0.03, P.d),
    door: box(P.w - 0.05, P.h - 0.16, 0.01), lid: box(P.w - 0.05, 0.01, P.d - 0.05), pillar: box(0.03, P.h - 0.14, 0.03),
    bed: box(0.36, 0.02, 0.36), bedTop: box(0.35, 0.004, 0.35), railX: box(0.42, 0.02, 0.02), railZ: box(0.02, 0.02, 0.4),
    head: box(0.07, 0.08, 0.07), nozzle: new THREE.ConeGeometry(0.012, 0.025, 12), part: box(0.14, 1, 0.1),
    screen: box(0.12, 0.07, 0.005), logo: box(0.1, 0.012, 0.004), light: box(P.w - 0.06, 0.012, 0.012),
    cfs: box(P.w - 0.02, P.cfsH, 0.34), cfsLid: box(P.w - 0.06, 0.01, 0.3), spool: new THREE.CylinderGeometry(0.075, 0.075, 0.07, 28),
    hit: box(P.w, P.h + P.cfsH, P.d),
  };
  geo.spool.rotateZ(Math.PI / 2);
  const mesh = (g, m, x = 0, y = 0, z = 0, shadow = true) => {
    const o = new THREE.Mesh(g, m);
    o.position.set(x, y, z);
    o.castShadow = shadow;
    o.receiveShadow = true;
    return o;
  };

  // Yerel eksen: yazıcının önü +z; tabanı y = 0
  function makePrinter() {
    const g = new THREE.Group();
    const H = P.h, W = P.w, D = P.d;
    const shell = [mesh(geo.base, mat.body, 0, 0.055, 0), mesh(geo.back, mat.body, 0, H / 2, -D / 2 + 0.0125),
      mesh(geo.side, mat.body, -W / 2 + 0.0125, H / 2, 0), mesh(geo.side, mat.body, W / 2 - 0.0125, H / 2, 0)];
    g.add(...shell,
      mesh(geo.topFrame, mat.trim, 0, H - 0.015, 0),
      mesh(geo.pillar, mat.trim, -W / 2 + 0.03, 0.11 + (H - 0.14) / 2, D / 2 - 0.02), mesh(geo.pillar, mat.trim, W / 2 - 0.03, 0.11 + (H - 0.14) / 2, D / 2 - 0.02));
    g.add(mesh(geo.door, mat.glass, 0, 0.11 + (H - 0.16) / 2 + 0.01, D / 2 - 0.01, false), mesh(geo.lid, mat.glass, 0, H + 0.002, 0, false));
    // Ön alt panel: dokunmatik ekran ve logo; durum ışığı ön üst kenarda
    g.add(mesh(geo.screen, mat.screen, -0.14, 0.058, D / 2 + 0.003, false), mesh(geo.logo, mat.logo, 0.13, 0.06, D / 2 + 0.003, false));
    const light = mesh(geo.light, stateMats.CEVRIMDISI, 0, H - 0.04, D / 2 - 0.005, false);
    g.add(light);
    // İç: tabla, raylar, kafa
    const bed = new THREE.Group();
    bed.add(mesh(geo.bed, mat.bed, 0, 0, 0), mesh(geo.bedTop, mat.bedTop, 0, 0.012, 0));
    bed.position.set(0, 0.2, 0.01);
    const part = mesh(geo.part, partMat, 0, 0, 0);
    part.visible = false;
    bed.add(part);
    g.add(bed);
    const gantry = new THREE.Group();
    gantry.position.y = H - 0.1;
    const railA = mesh(geo.railZ, mat.rail, -0.2, 0, 0.01), railB = mesh(geo.railZ, mat.rail, 0.2, 0, 0.01);
    const cross = mesh(geo.railX, mat.rail, 0, 0, 0);
    const head = new THREE.Group();
    head.add(mesh(geo.head, mat.head, 0, -0.03, 0), mesh(geo.nozzle, mat.rail, 0, -0.08, 0));
    cross.add(head);
    gantry.add(railA, railB, cross);
    g.add(gantry);
    // CFS: üstte filament kutusu, şeffaf kapağın altında dört makara
    const cfs = new THREE.Group();
    cfs.position.set(0, H + P.cfsH / 2 + 0.005, -0.05);
    cfs.add(mesh(geo.cfs, mat.cfs, 0, 0, 0), mesh(geo.cfsLid, mat.cfsLid, 0, P.cfsH / 2 + 0.004, 0, false));
    spools.forEach((m, i) => cfs.add(mesh(geo.spool, m, -0.165 + i * 0.11, P.cfsH / 2 - 0.07, 0, false)));
    g.add(cfs);
    const hit = new THREE.Mesh(geo.hit, new THREE.MeshBasicMaterial({ visible: false }));
    hit.position.y = (P.h + P.cfsH) / 2;
    g.add(hit);
    const sel = new THREE.Mesh(box(P.w + 0.06, P.h + P.cfsH + 0.06, P.d + 0.06), mat.select);
    sel.position.y = (P.h + P.cfsH) / 2;
    sel.visible = false;
    g.add(sel);
    return { g, shell, light, part, cross, head, hit, sel, bedY: 0.012 };
  }

  const world = new THREE.Group();
  scene.add(world);
  // Basılan parçanın G-code'dan 3B yolu (gerçek ölçüde: 1 mm = 0,001): yüzdesi kadarı dolu, üstü şeffaf
  let previews = null;
  const previewsReady = api.get('/api/products/previews').then(m => { previews = m; }).catch(() => { previews = {}; });
  function showPart(u, p, prog, done) {
    const path = previews?.[partOf(p)]?.preview || null;
    if (u.gpath !== path) {
      u.gpath = path;
      if (u.gobj) { u.gobj.parent?.remove(u.gobj); u.gobj.geometry.dispose(); u.gobj.material.dispose(); u.gobj = null; }
      if (path) {
        loadPath(path).then(data => {
          if (u.gpath !== path) return;
          const obj = partObject(THREE, data, { faint: 0.16 });
          obj.scale.setScalar(0.001);
          obj.position.set(0, u.bedY + 0.002, 0);
          u.part.parent.add(obj);
          u.gobj = obj;
          obj.setCut(u.cut ?? 1);
          u.part.visible = false;
        }).catch(() => {});
      }
    }
    u.cut = done ? 1 : prog / 100;
    if (u.gobj) { u.gobj.setCut(u.cut); u.gobj.visible = true; }
  }
  let built = '', units = new Map(), len = 10, lamps = null, lastView = 'entry';

  function buildStatic(perRow) {
    world.clear();
    len = perRow * PITCH + 1.2;
    const z0 = -0.6;
    // Zemin (epoksi, koridor çizgileri), duvarlar, tavan lambaları
    const floorTex = floorTexture(THREE);
    floorTex.repeat.set((AISLE + 2 * RACK_D + 3) / 2, len / 2);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(AISLE + 2 * RACK_D + 3, len + 3),
      new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.35, metalness: 0.05 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0, z0 + len / 2);
    floor.receiveShadow = true;
    world.add(floor);
    const roomW = AISLE + 2 * RACK_D + 3;
    for (const x of [-roomW / 2, roomW / 2]) {
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(len + 3, 3.2), mat.wall);
      wall.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2;
      wall.position.set(x, 1.6, z0 + len / 2);
      wall.receiveShadow = true;
      world.add(wall);
    }
    const back = new THREE.Mesh(new THREE.PlaneGeometry(roomW, 3.2), mat.wall);
    back.position.set(0, 1.6, z0 + len + 1.5);
    back.rotation.y = Math.PI;   // girişe bakar
    back.receiveShadow = true;
    world.add(back);
    // Karşı duvarda firma logosu (tenant'ın logosu); en-boy oranı resimden
    new THREE.TextureLoader().load('/static/img/logo.png', tex => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 8;
      const w = Math.min(roomW * 0.55, 3), hh = w * tex.image.height / tex.image.width;
      const logo = new THREE.Mesh(new THREE.PlaneGeometry(w, hh), new THREE.MeshStandardMaterial({ map: tex, transparent: true, roughness: 0.8 }));
      logo.position.set(0, Math.min(2.9 - hh / 2, 1.7 + hh / 2), z0 + len + 1.49);
      logo.rotation.y = Math.PI;
      world.add(logo);
    });
    lamps = new THREE.Group();
    for (let z = z0 + 1; z < z0 + len; z += 2.2) lamps.add(mesh(box(0.35, 0.03, 1.2), mat.lamp, 0, 3.05, z, false));
    world.add(lamps);
    // Raflar: iki katlı endüstriyel raf; dikmeler 3 yazıcıda bir, turuncu kirişler, metal tablalar
    for (const side of ['L', 'R']) {
      const x = sideX(side);
      const rackLen = perRow * PITCH + 0.1;
      const zc = z0 + 0.6 + rackLen / 2 - 0.05;
      for (let i = 0; i <= perRow; i += 3) {
        const z = z0 + 0.6 + Math.min(i, perRow) * PITCH - 0.05 + (i === 0 ? 0 : 0);
        for (const dx of [-RACK_D / 2 + 0.03, RACK_D / 2 - 0.03]) world.add(mesh(box(0.05, RACK_H, 0.05), mat.post, x + dx, RACK_H / 2, z));
      }
      const endZ = z0 + 0.6 + perRow * PITCH - 0.05;
      for (const dx of [-RACK_D / 2 + 0.03, RACK_D / 2 - 0.03]) world.add(mesh(box(0.05, RACK_H, 0.05), mat.post, x + dx, RACK_H / 2, endZ));
      for (const y of [...SHELF, RACK_H - 0.05]) {   // iki kat tabla; en üstte yalnızca kiriş (raf üstü açık)
        if (y < RACK_H - 0.1) world.add(mesh(box(RACK_D, 0.025, rackLen), mat.deck, x, y - 0.0125, zc));
        for (const dx of [-RACK_D / 2 + 0.03, RACK_D / 2 - 0.03]) world.add(mesh(box(0.06, 0.09, rackLen), mat.beam, x + dx, y - 0.06, zc));
      }
      // Raf başında taraf etiketi
      const tag = document.createElement('div');
      tag.className = 'pr3d-side';
      tag.textContent = side === 'L' ? 'SOL RAF' : 'SAĞ RAF';
      const tagObj = new CSS2DObject(tag);
      tagObj.position.set(x, RACK_H + 0.2, z0 + 0.3);
      world.add(tagObj);
    }
    sun.position.set(3, 7, z0 - 2);
    sun.target.position.set(0, 0, z0 + len / 2);
    Object.assign(sun.shadow.camera, { left: -4, right: 4, top: len / 2 + 2, bottom: -len / 2 - 2, near: 1, far: 30 });
    sun.shadow.camera.updateProjectionMatrix();
  }

  function place(u, p) {
    const x = sideX(p.rack_side);
    const z = -0.6 + 0.6 + ((p._pos || p.rack_slot) - 1) * PITCH + PITCH / 2 - 0.05;   // katında bitişik sıra (boş numara boşluk bırakmaz)
    u.g.position.set(x, SHELF[(p.rack_level || 1) - 1], z);
    u.g.rotation.y = x > 0 ? -Math.PI / 2 : Math.PI / 2;   // ön yüz koridora bakar
  }

  let lastList = null;
  previewsReady.then(() => { if (lastList) set(lastList); });   // parça 3B yolları gelince hemen çiz
  function set(list) {
    lastList = list;
    const withPlace = list.filter(p => p.rack_side);
    // Gerçekte rafta boşluk yok: her taraf / katta yazıcılar sıra numarasına göre bitişik dizilir; raf boyu en kalabalık kata göre
    const rows = {};
    for (const p of [...withPlace].sort((a, b) => a.rack_slot - b.rack_slot)) {
      const k = `${p.rack_side}${p.rack_level}`;
      p._pos = (rows[k] = (rows[k] || 0) + 1);
    }
    const perRow = Math.max(1, ...Object.values(rows));
    const sig = `${perRow}|${withPlace.map(p => `${p.id}:${p.rack_side}${p.rack_level}${p._pos}`).join(',')}`;
    if (sig !== built) {
      const first = !built;
      buildStatic(perRow);
      units = new Map();
      for (const p of withPlace) {
        const u = makePrinter();
        u.hit.userData.pid = p.id;
        // İsim plakası: yazıcının üstündeki kirişte (alt katta üst tablanın, üst katta rafın en üst kirişi);
        // rafın hem önünde (koridor) hem arkasında
        u.plate = namePlate(THREE);
        const beamY = (p.rack_level === 2 ? RACK_H - 0.05 : SHELF[1]) - 0.06 - SHELF[(p.rack_level || 1) - 1];
        const back = new THREE.Mesh(u.plate.mesh.geometry, u.plate.mesh.material);
        u.plate.mesh.position.set(0, beamY, RACK_D / 2 + 0.004);
        back.position.set(0, beamY, -RACK_D / 2 - 0.004);
        back.rotation.y = Math.PI;
        u.plates = [u.plate.mesh, back];
        for (const m of u.plates) { m.userData.pid = p.id; u.g.add(m); }
        place(u, p);
        world.add(u.g);
        units.set(p.id, u);
      }
      built = sig;
      if (first) view('entry');   // yeniden kurulumda (yer değişince) kamera açısı korunur
      if (selectedId) select(selectedId);
    }
    for (const p of withPlace) {
      const u = units.get(p.id);
      const st = p.live_state || 'CEVRIMDISI';
      u.state = st;
      u.light.material = stateMats[st] || stateMats.CEVRIMDISI;
      for (const m of u.shell) m.material = bodyMats[st] || bodyMats.CEVRIMDISI;
      const prog = Math.max(0, Math.min(100, p.live_progress || 0));
      const building = (st === 'YAZDIRIYOR' || st === 'DURAKLADI') && prog > 0;
      const done = st === 'TAMAMLANDI';
      const showing = building || done;
      if (showing && partOf(p) && previews?.[partOf(p)]) {   // gerçek parça (G-code) — yüzdeye kadar dolu
        showPart(u, p, prog, done);
      } else {
        if (u.gobj) u.gobj.visible = false;
        u.part.visible = showing;   // G-code'u olmayan (sistem dışı) baskı: büyüyen kutu
        const hgt = Math.max(0.004, 0.12 * (done ? 1 : prog / 100));
        u.part.scale.y = hgt;
        u.part.position.y = u.bedY + hgt / 2;
      }
      u.plate.draw(p.name, st, p.id === selectedId);
    }
  }

  let selectedId = null;
  function select(id) {
    selectedId = id;
    for (const [pid, u] of units) {
      u.sel.visible = pid === id;
      u.plate.draw(u.plate.name, u.plate.state, pid === id);
    }
  }

  function view(v) {
    lastView = v;
    const mid = -0.6 + len / 2;
    if (v === 'entry') { camera.position.set(0, 1.75, -2.6); controls.target.set(0, 1.0, mid - 1); }
    else if (v === 'top') { camera.position.set(-3.2, 3.6, -3.4); controls.target.set(0, 0.7, mid); }   // köşeden, yukarıdan genel bakış
    else {
      const x = sideX(v);
      camera.position.set(-x * 0.35, 1.5, -1.2);
      controls.target.set(x, 0.9, mid - 1.5);
    }
    controls.update();
  }

  // Tıklama: sürükleme değilse yazıcı seçilir
  const ray = new THREE.Raycaster();
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.intersectObjects([...units.values()].flatMap(u => [u.hit, ...u.plates]))[0];
    if (hit) onPick(hit.object.userData.pid);
  });

  const resize = () => {
    const w = stage.clientWidth, hh = stage.clientHeight;
    if (!w || !hh) return;
    renderer.setSize(w, hh);
    css.setSize(w, hh);
    camera.aspect = w / hh;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(stage);
  resize();

  // Basan yazıcılarda kafa ve köprü hareket eder
  let raf = 0;
  const clock = new THREE.Clock();
  const loop = () => {
    raf = requestAnimationFrame(loop);
    const t = clock.getElapsedTime();
    for (const u of units.values()) {
      if (u.state !== 'YAZDIRIYOR') continue;
      const k = u.g.id * 0.37;
      u.cross.position.z = Math.sin(t * 1.3 + k) * 0.15;
      u.head.position.x = Math.sin(t * 2.1 + k * 1.7) * 0.16;
    }
    if (tourFn) tourFn(t); else controls.update();
    renderer.render(scene, camera);
    css.render(scene, camera);
  };
  let tourFn = null;
  loop();

  // Kiosk turu (TV ekranı): girişte etrafa bakar → koridorda yürür, raflara döner → sonda geri döner ve yükselir →
  // odayı üstten dolaşır → köşeden genel bakış → başa döner. Odanın boyuna göre rota çıkarılır; yumuşak eğri (Catmull-Rom).
  function tour(on, period = 96) {
    if (!on) { tourFn = null; controls.enabled = true; return; }
    const z0 = -0.6, zEnd = z0 + len - 0.9, mid = z0 + len / 2, eye = 1.62, look = 1.3;
    const K = [];   // [saniye, konum, hedef]
    const key = (dt, p, t) => K.push([dt, new THREE.Vector3(...p), new THREE.Vector3(...t)]);
    key(5, [0, eye, -2.6], [0, 1.2, 2]);
    key(4, [0.1, eye, -2.45], [look, 1.05, 0.2]);         // sola bak
    key(4, [-0.1, eye, -2.3], [-look, 1.05, 0.2]);        // sağa bak
    let side = 1;
    for (let z = -1.5; z < zEnd - 1; z += 1.9) {           // koridorda yürü, başı raflara dönsün
      key(3.6, [side * 0.12, eye + Math.sin(z) * 0.03, z], [side * look, side > 0 ? 1.3 : 0.75, z + 1.7]);
      side = -side;
    }
    key(4, [0, eye + 0.2, zEnd], [0, 1.1, zEnd + 2]);       // koridor sonu
    key(5, [0.3, 2.5, zEnd - 0.3], [0, 0.9, zEnd - 5]);     // dönüp geriye bak, yüksel
    key(7, [0.8, 4.2 + len * 0.45, mid + len * 0.12], [0, 0.4, mid]);    // üstten (tüm oda kadrajda)
    key(7, [-0.8, 4.4 + len * 0.45, mid - len * 0.12], [0, 0.4, mid]);   // üstten yavaşça dolaş
    key(6, [-3.2, 3.6, -3.4], [0, 0.7, mid]);               // köşeden genel bakış
    const total = K.reduce((a, k) => a + k[0], 0);
    const pc = new THREE.CatmullRomCurve3(K.map(k => k[1]), true, 'centripetal');
    const tc = new THREE.CatmullRomCurve3(K.map(k => k[2]), true, 'centripetal');
    const starts = [];
    K.reduce((a, k) => { starts.push(a); return a + k[0]; }, 0);
    const scale = total / period;   // istenen döngü süresine yay
    const p = new THREE.Vector3(), tg = new THREE.Vector3();
    const t0 = clock.getElapsedTime();
    controls.enabled = false;
    tourFn = t => {
      const s = ((t - t0) * scale) % total;
      let i = starts.length - 1;
      while (i > 0 && starts[i] > s) i--;
      const f = (s - starts[i]) / K[i][0];
      const u = (i + f) / K.length;   // eğri zaten yumuşak; sabit hızla akar (yürüyüşte durup kalkmasın)
      pc.getPoint(u, p); tc.getPoint(u, tg);
      camera.position.copy(p);
      camera.lookAt(tg);
    };
  }

  // Tek yazıcı görünümü (bilgi penceresi): aynı model, içindeki parça (G-code 3B yolu, yüzdesi kadar dolu); döndürülebilir
  function solo(box, p) {
    const r2 = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    r2.setPixelRatio(Math.min(devicePixelRatio, 2));
    r2.toneMapping = THREE.ACESFilmicToneMapping;
    box.replaceChildren(r2.domElement);
    const sc = new THREE.Scene();
    sc.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.3));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1.2, 2, 1.5);
    sc.add(key);
    const cam = new THREE.PerspectiveCamera(38, 1, 0.02, 20);
    const ctl = new OrbitControls(cam, r2.domElement);
    ctl.enableDamping = true;
    ctl.target.set(0, 0.46, 0);
    cam.position.set(1.15, 1.0, 1.45);
    ctl.autoRotate = true;
    ctl.autoRotateSpeed = 0.8;
    r2.domElement.addEventListener('pointerdown', () => { ctl.autoRotate = false; });
    const u = makePrinter();
    for (const m of u.hit ? [u.hit] : []) m.visible = false;
    sc.add(u.g);
    const upd = pp => {
      const st = pp.live_state || 'CEVRIMDISI';
      u.state = st;
      u.light.material = stateMats[st] || stateMats.CEVRIMDISI;
      for (const m of u.shell) m.material = bodyMats[st] || bodyMats.CEVRIMDISI;
      const prog = Math.max(0, Math.min(100, pp.live_progress || 0));
      const done = st === 'TAMAMLANDI';
      const showing = ((st === 'YAZDIRIYOR' || st === 'DURAKLADI') && prog > 0) || done;
      if (showing && partOf(pp) && previews?.[partOf(pp)]) showPart(u, pp, prog, done);
      else {
        if (u.gobj) u.gobj.visible = false;
        u.part.visible = showing;
        const hgt = Math.max(0.004, 0.12 * (done ? 1 : prog / 100));
        u.part.scale.y = hgt;
        u.part.position.y = u.bedY + hgt / 2;
      }
    };
    upd(p);
    previewsReady.then(() => upd(p));
    const fit = () => {
      const w = box.clientWidth || 360, hh = box.clientHeight || 320;
      r2.setSize(w, hh);
      cam.aspect = w / hh;
      cam.updateProjectionMatrix();
    };
    const ro2 = new ResizeObserver(fit);
    ro2.observe(box);
    fit();
    const clk = new THREE.Clock();
    let raf2 = 0;
    const tick = () => {
      raf2 = requestAnimationFrame(tick);
      if (u.state === 'YAZDIRIYOR') {
        const t = clk.getElapsedTime();
        u.cross.position.z = Math.sin(t * 1.3) * 0.15;
        u.head.position.x = Math.sin(t * 2.1) * 0.16;
      }
      ctl.update();
      r2.render(sc, cam);
    };
    tick();
    return {
      update: upd,
      destroy() { cancelAnimationFrame(raf2); ro2.disconnect(); ctl.dispose(); r2.dispose(); r2.domElement.remove(); },
    };
  }

  return {
    el, update: set, set, select, view, solo, tour,
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      pmrem.dispose();
    },
  };
}

// Raf kirişindeki isim plakası: beyaz etiket, solda durum renginde şerit, yazıcının adı; seçiliyse mavi çerçeve
function namePlate(THREE) {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 128;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(0.36, 0.09), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6 }));
  const plate = { mesh, name: '', state: '', on: null };
  plate.draw = (name, state, on) => {
    if (name === plate.name && state === plate.state && on === plate.on) return;
    Object.assign(plate, { name, state, on });
    const g = c.getContext('2d');
    g.fillStyle = on ? '#dbeafe' : '#f8fafc';
    g.fillRect(0, 0, 512, 128);
    g.fillStyle = `#${(STATE_COLORS[state] ?? STATE_COLORS.CEVRIMDISI).toString(16).padStart(6, '0')}`;
    g.fillRect(0, 0, 34, 128);
    g.lineWidth = on ? 12 : 4;
    g.strokeStyle = on ? '#1d4ed8' : '#94a3b8';
    g.strokeRect(g.lineWidth / 2, g.lineWidth / 2, 512 - g.lineWidth, 128 - g.lineWidth);
    g.fillStyle = '#0f172a';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    let size = 76;
    do { g.font = `800 ${size}px system-ui, sans-serif`; size -= 4; } while (g.measureText(name).width > 440 && size > 30);
    g.fillText(name, 273, 68);
    tex.needsUpdate = true;
  };
  return plate;
}

// Epoksi zemin: açık gri, hafif benekli, 1 m'lik derz çizgileri
function floorTexture(THREE) {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = '#b8bec6';
  g.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 1400; i++) {
    g.fillStyle = `rgba(${Math.random() < 0.5 ? '255,255,255' : '60,70,80'},${Math.random() * 0.08})`;
    g.fillRect(Math.random() * 256, Math.random() * 256, 2, 2);
  }
  g.strokeStyle = 'rgba(80,90,100,.35)';
  g.lineWidth = 2;
  g.strokeRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}
