// HEPGO Fabrika — Canlı İzleme 3B sahnesi (Three.js, yerel kopya) — vantra-facility-os esinli.
// • Kat planı ARKA PLAN RESMİNDEKİ duvar çizgileri otomatik tespit edilir ve 3B beyaz duvar olarak yükseltilir
//   (koyu piksel taraması → yatay/dikey segmentler → InstancedMesh). Polygon oda çizmek gerekmez.
// • Polygon odalar (varsa) cam duvar + eşik olarak çizilir.
// • Kat: kalın beyaz plaka; altyapı işaretçileri (UPS/WiFi/priz...) pin + emoji; canlı personel yüz kartı + durum rengi.
// • Sol cam panel: kat seçici, sayaçlar, canlı kişi listesi. Orbit kamera. Açık/koyu tema.

const LIB = '/static/vendor/three/';
let _libs = null;
const loadLibs = () => (_libs ??= Promise.all(
  ['three.module.min.js', 'OrbitControls.js'].map(f => import(LIB + f))
).then(([T, O]) => ({ T, OrbitControls: O.OrbitControls })).catch(e => { _libs = null; throw e; }));

const WALL_H = 1.4, IMG_WALL_H = 1.1, TH = 0.06, SILL_H = 0.34, SPAN = 26, SLAB_T = 0.9;   // alçak, ince cam duvarlar
let _Tref = null;

const PAL = {
  light: { grid1: 0xd3d9e6, grid2: 0xe3e8f1, slab: 0xffffff, slabSide: 0xeef1f8, deck: 0xf3f5fa, wall: 0xf7f8fc, sill: 0xe6eaf3, steel: 0xb7c2d6, label: '#1c2233', labelBg: 'rgba(255,255,255,.92)', accent: 0x7c6cf0 },
  dark: { grid1: 0x263252, grid2: 0x1b2540, slab: 0x1f2a44, slabSide: 0x182238, deck: 0x25304d, wall: 0x3a4664, sill: 0x2b3650, steel: 0x55617f, label: '#e8edf8', labelBg: 'rgba(18,24,40,.86)', accent: 0x9d8cff },
};
// İki kademe: yakın zamanda görüldü (≤10 dk) → yeşil; daha eski → gri "son görüldüğü yer"
const RECENT_MS = 10 * 60000;
const isRecent = at => !!at && (Date.now() - new Date(at).getTime()) <= RECENT_MS;
const ageColor = at => (isRecent(at) ? 0x16a34a : 0x98a2b3);
const ageText = at => { if (!at) return '—'; const m = Math.round((Date.now() - new Date(at).getTime()) / 60000); return m < 1 ? 'şimdi' : m < 60 ? `${m} dk` : `${Math.round(m / 60)} sa`; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export async function createFactory3D(mountEl, opts = {}) {
  const { T, OrbitControls } = await loadLibs();
  _Tref = T;
  const fileUrl = opts.fileUrl || (p => p);
  let dark = !!opts.dark, floorName = opts.floorName || '', palette = opts.palette || {};
  let floors = opts.floors || [], floorId = opts.floorId ?? null; const onFloor = opts.onFloor || null;
  const onPrinter = opts.onPrinter || null;   // yazıcıya tıklandı → factory.js bilgi penceresi açar
  let P = dark ? PAL.dark : PAL.light;

  // ---------- cam panel (HUD) ----------
  ensureHudStyle();
  const hud = document.createElement('div'); hud.className = 'f3d-hud';
  hud.style.cssText = 'position:absolute;left:14px;top:14px;bottom:14px;z-index:5;pointer-events:none;display:flex;flex-direction:column;gap:10px;max-width:290px';
  // kart = header (ikon + başlık, altında ince çizgi) · gövde · footer (hafif koyu zemin). Çift tık → ikona küçülür / geri açılır.
  hud.innerHTML = `
    <div class="f3d-card f3d-main" data-icon="📡">
      <div class="f3d-hd"><span class="f3d-ic">📡</span><span class="f3d-dot live"></span><b class="f3d-ttl">Canlı İzleme · 3B</b><span class="f3d-chip">RTLS</span></div>
      <div class="f3d-bd">
        <div class="f3d-floor"></div>
        <div class="f3d-stats">
          <div class="f3d-stat v"><b class="n-people">0</b><span>Sahada</span></div>
          <div class="f3d-stat c"><b class="n-cams">0</b><span>Kamera</span></div>
          <div class="f3d-stat m"><b class="n-markers">0</b><span>İşaretçi</span></div>
        </div>
      </div>
      <div class="f3d-ft">Konumlar 10 sn'de bir yenilenir · çift tık: küçült</div>
    </div>
    <div class="f3d-card f3d-people" data-icon="👥">
      <div class="f3d-hd"><span class="f3d-ic">👥</span><b class="f3d-ttl">Sahadaki Kişiler</b><span class="f3d-chip n-people2">0</span></div>
      <div class="f3d-bd f3d-list"></div>
      <div class="f3d-ft f3d-leg"><span><i class="g"></i>yakın zamanda görüldü</span><span><i class="x"></i>son görüldüğü yer</span></div>
    </div>`;
  mountEl.appendChild(hud); if (dark) hud.classList.add('f3d-dark');
  // kat seçici: üstte ortada, HEPGO modüllerindeki silindirik segment buton (.seg) tarzı
  const hudF = document.createElement('div'); hudF.className = 'seg f3d-floors';
  hudF.style.cssText = 'position:absolute;left:50%;top:14px;transform:translateX(-50%);z-index:6;pointer-events:auto';
  mountEl.appendChild(hudF);
  // çift tık: kartı ikona küçült / ikondan geri aç (tüm cam paneller)
  mountEl.addEventListener('dblclick', e => {
    const card = e.target.closest && e.target.closest('.f3d-card'); if (!card) return;
    e.preventDefault(); card.classList.toggle('f3d-min');
  });
  const q = s => hud.querySelector(s);
  const el = { floor: q('.f3d-floor'), nPeople: q('.n-people'), nCams: q('.n-cams'), nMarkers: q('.n-markers'), list: q('.f3d-list'), floors: hudF };
  // sağ cam panel: bölgeler + kameralar (vantra "Ward cameras" tarzı)
  const hudR = document.createElement('div'); hudR.className = 'f3d-hud f3d-right';
  hudR.style.cssText = 'position:absolute;right:14px;top:14px;z-index:5;pointer-events:none;display:flex;flex-direction:column;gap:10px;width:236px;height:calc(100% - 28px)';
  hudR.innerHTML = `
    <div class="f3d-card f3d-zonecard" data-icon="🗂️">
      <div class="f3d-hd"><span class="f3d-ic">🗂️</span><b class="f3d-ttl">Bölümler</b><span class="f3d-chip n-zones">0</span></div>
      <div class="f3d-bd f3d-zones"><div class="f3d-empty">Plan yüklenince bölümler çıkarılır</div></div>
      <div class="f3d-ft">Etiketler Düzen › "Bölüm Etiketi Koy" ile · kişi sayısı: yakın görülenler</div>
    </div>
    <div class="f3d-card f3d-camcard" data-icon="📷">
      <div class="f3d-hd"><span class="f3d-ic">📷</span><b class="f3d-ttl">Kameralar</b><span class="f3d-chip n-camlist">0</span></div>
      <div class="f3d-bd f3d-cams"><div class="f3d-empty">Kamera yok</div></div>
      <div class="f3d-ft">Satıra tıkla → kameranın yerinde canlı önizleme</div>
    </div>`;
  mountEl.appendChild(hudR); if (dark) hudR.classList.add('f3d-dark');
  el.zones = hudR.querySelector('.f3d-zones'); el.cams = hudR.querySelector('.f3d-cams'); el.nCamList = hudR.querySelector('.n-camlist');
  const renderFloors = () => {
    el.floors.innerHTML = '';
    if (!floors.length) return;
    floors.forEach(f => {
      const b = document.createElement('button'); b.type = 'button'; b.className = f.id === floorId ? 'on' : ''; b.textContent = f.name;
      b.onclick = () => { if (onFloor) onFloor(f.id); }; el.floors.appendChild(b);
    });
  };
  const renderPeople = (ppl) => {
    ppl = [...(ppl || [])].sort((a, b) => (isRecent(b.at) - isRecent(a.at)) || (new Date(b.at || 0) - new Date(a.at || 0)));
    el.nPeople.textContent = ppl.filter(p => isRecent(p.at)).length;
    const c2 = hud.querySelector('.n-people2'); if (c2) c2.textContent = ppl.length;
    if (!ppl.length) { el.list.innerHTML = '<div class="f3d-empty">Henüz tanınan kişi yok</div>'; return; }
    el.list.innerHTML = ppl.slice(0, 8).map(p => {
      const col = '#' + ageColor(p.at).toString(16).padStart(6, '0');
      const av = p.crop ? `<img src="${esc(fileUrl(p.crop, 64))}" alt="">` : `<i style="background:${col}">${esc((p.subject_name || '?').slice(0, 1).toLocaleUpperCase('tr'))}</i>`;
      return `<div class="f3d-row"><span class="f3d-av" style="border-color:${col}">${av}</span><span class="f3d-nm"><b>${esc(p.subject_name || '—')}</b><small>${esc(p.room_name || p.camera_name || '—')}</small></span><span class="f3d-age" style="color:${col}">${ageText(p.at)}</span></div>`;
    }).join('') + (ppl.length > 8 ? `<div class="f3d-more">+${ppl.length - 8} kişi daha</div>` : '');
  };
  const setFloorName = n => { if (n != null) floorName = n; el.floor.textContent = floorName || 'Tüm kat'; };
  setFloorName(floorName); renderFloors(); renderPeople([]);

  // ---------- renderer / sahne / kamera ----------
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  if ('outputColorSpace' in renderer) renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.domElement.style.cssText = 'width:100%;height:100%;display:block;touch-action:none;cursor:grab';
  mountEl.appendChild(renderer.domElement);

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(36, 1, 0.3, 500);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 6; controls.maxDistance = 120;
  // ---------- fare modları: Orbit (sol: döndür) · Gez (sol: kaydır) · Döndür (otomatik dönüş) — alt-orta segment ----------
  const hudM = document.createElement('div'); hudM.className = 'seg f3d-modes';
  hudM.style.cssText = 'position:absolute;left:50%;bottom:14px;transform:translateX(-50%);z-index:6;pointer-events:auto';
  const MODES = [['orbit', '🧭 Orbit'], ['pan', '✋ Gez'], ['rotate', '🔄 Döndür']];
  let mouseMode = 'orbit';
  const setMouseMode = m => {
    mouseMode = m;
    controls.autoRotate = m === 'rotate'; controls.autoRotateSpeed = 0.9;
    controls.mouseButtons = m === 'pan' ? { LEFT: T.MOUSE.PAN, MIDDLE: T.MOUSE.DOLLY, RIGHT: T.MOUSE.ROTATE } : { LEFT: T.MOUSE.ROTATE, MIDDLE: T.MOUSE.DOLLY, RIGHT: T.MOUSE.PAN };
    controls.touches = m === 'pan' ? { ONE: T.TOUCH.PAN, TWO: T.TOUCH.DOLLY_ROTATE } : { ONE: T.TOUCH.ROTATE, TWO: T.TOUCH.DOLLY_PAN };
    renderer.domElement.style.cursor = m === 'pan' ? 'move' : 'grab';
    hudM.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.m === m));
  };
  MODES.forEach(([k, lbl]) => { const b = document.createElement('button'); b.type = 'button'; b.dataset.m = k; b.textContent = lbl; b.onclick = () => setMouseMode(k); hudM.appendChild(b); });
  mountEl.appendChild(hudM); setMouseMode('orbit');

  const hemi = new T.HemisphereLight(0xffffff, 0x9aa6bd, 1.0); scene.add(hemi);
  const key = new T.DirectionalLight(0xffffff, 1.45);
  key.position.set(18, 36, 20); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -34; key.shadow.camera.right = 34; key.shadow.camera.top = 34; key.shadow.camera.bottom = -34;
  key.shadow.camera.near = 1; key.shadow.camera.far = 120; key.shadow.bias = -0.0005; key.shadow.radius = 4;
  scene.add(key);
  const rim = new T.DirectionalLight(0xb9c6ff, 0.55); rim.position.set(-22, 14, -20); scene.add(rim);

  const gWorld = new T.Group(); scene.add(gWorld);
  const gBg = new T.Group(); scene.add(gBg);
  const gZones = new T.Group(); scene.add(gZones);
  const gPrinters = new T.Group(); scene.add(gPrinters);   // Yazıcı Odası rafı + yazıcılar
  const gLive = new T.Group(); scene.add(gLive);
  let grid, M = {}, zones = [], zoneGrid = null, camNames = [], labels = [], freeLabels = [], camMeshes = [], printers = [], printerMeshes = [];
  const ZONE_COLORS = [0xc7c2ff, 0xbfe3ff, 0xc3f1dc, 0xffe1c4, 0xffd1dc, 0xd9f0b8, 0xfff0b3, 0xd4e6ff];
  // yazıcı durum ışığı (printers3d ile aynı renkler)
  const PR_STATE = { YAZDIRIYOR: 0x3b82f6, HAZIR: 0x22c55e, TAMAMLANDI: 0xa855f7, DURAKLADI: 0xf59e0b, HATA: 0xef4444, CEVRIMDISI: 0x4b5563, BAKIM: 0xf97316, ARGE: 0x14b8a6 };
  const PR_TEXT = { YAZDIRIYOR: 'Yazdırıyor', HAZIR: 'Hazır', TAMAMLANDI: 'Tamamlandı', DURAKLADI: 'Duraklandı', HATA: 'Hata', CEVRIMDISI: 'Çevrimdışı', BAKIM: 'Bakım', ARGE: 'Ar-Ge' };
  // yazıcı durumu (printers3d ile aynı kural: bakım > arge > canlı durum)
  const prState = p => p.maint_since ? 'BAKIM' : (p.arge_since ? (p.live_state && p.live_state !== 'HATA' && p.live_state !== 'CEVRIMDISI' ? p.live_state : 'ARGE') : String(p.live_state || p.state || 'CEVRIMDISI').toUpperCase());

  const makeMats = () => {
    M.slab = new T.MeshStandardMaterial({ color: P.slab, roughness: 0.55, metalness: 0.05 });
    M.slabSide = new T.MeshStandardMaterial({ color: P.slabSide, roughness: 0.7, metalness: 0.05 });
    M.deck = new T.MeshStandardMaterial({ color: P.deck, roughness: 0.6, metalness: 0.1 });
    M.wall = new T.MeshStandardMaterial({ color: P.wall, roughness: 0.62, metalness: 0.04 });
    M.sill = new T.MeshStandardMaterial({ color: P.sill, roughness: 0.75, metalness: 0.05 });
    M.glass = new T.MeshPhysicalMaterial({ color: 0xa9cfdd, transmission: 0.9, thickness: 0.5, roughness: 0.14, metalness: 0, ior: 1.35, transparent: true, opacity: 0.4, side: T.DoubleSide });
    // plandan çıkan duvarlar için hafif cam (binlerce segment → transmission yerine şeffaf+clearcoat, tek draw call)
    M.imgGlass = new T.MeshPhysicalMaterial({ color: 0xcfe6f4, transparent: true, opacity: 0.42, roughness: 0.06, metalness: 0, clearcoat: 0.6, clearcoatRoughness: 0.15, side: T.DoubleSide, depthWrite: false });
    M.zone = new T.MeshBasicMaterial({ transparent: true, opacity: 0.5, depthWrite: false });
    M.frame = new T.MeshStandardMaterial({ color: P.steel, roughness: 0.5, metalness: 0.4 });
    M.cam = new T.MeshStandardMaterial({ color: 0x2a3340, roughness: 0.45, metalness: 0.3 });
    M.cone = new T.MeshBasicMaterial({ color: P.accent, transparent: true, opacity: 0.07, side: T.DoubleSide, depthWrite: false });
  };
  const buildBase = () => {
    if (grid) scene.remove(grid);
    grid = new T.GridHelper(300, 150, P.grid1, P.grid2);
    grid.material.transparent = true; grid.material.opacity = dark ? 0.35 : 0.45; grid.position.y = -SLAB_T - 0.02; scene.add(grid);
  };

  // ---------- koordinat dönüşümü ----------
  let X = { cx: 0, cy: 0, s: 1 };
  const computeTransform = (rooms, cams, markers, bgBox) => {
    const pts = [];
    (rooms || []).forEach(r => (r.points || []).forEach(p => pts.push(p)));
    (cams || []).forEach(c => (c.x != null) && pts.push([c.x, c.y]));
    (markers || []).forEach(m => (m.x != null) && pts.push([m.x, m.y]));
    if (bgBox) pts.push([bgBox.x0, bgBox.y0], [bgBox.x1, bgBox.y1]);
    if (!pts.length) { X = { cx: 0, cy: 0, s: 0.05 }; return; }
    let a = Infinity, b = -Infinity, c = Infinity, d = -Infinity;
    pts.forEach(([x, y]) => { if (x < a) a = x; if (x > b) b = x; if (y < c) c = y; if (y > d) d = y; });
    X = { cx: (a + b) / 2, cy: (c + d) / 2, s: SPAN / Math.max(b - a || 1, d - c || 1) };
  };
  const px = x => (x - X.cx) * X.s, pz = y => (y - X.cy) * X.s;
  const disposeGroup = g => { g.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => { m.map?.dispose?.(); m.dispose?.(); }); }); g.clear(); };

  // ---------- polygon odalar + kameralar + işaretçiler ----------
  const buildWorld = (rooms, cams, markers, stairs) => {
    disposeGroup(gWorld); camMeshes = [];
    (rooms || []).forEach(r => {
      const pts = (r.points || []).filter(p => p && p.length >= 2); if (pts.length < 3) return;
      const shape = new T.Shape(); pts.forEach(([x, y], i) => { const sx = px(x), sz = pz(y); i ? shape.lineTo(sx, sz) : shape.moveTo(sx, sz); }); shape.closePath();
      const slabGeo = new T.ExtrudeGeometry(shape, { depth: 0.14, bevelEnabled: false }); slabGeo.rotateX(Math.PI / 2);
      const slab = new T.Mesh(slabGeo, M.deck); slab.position.y = 0.14; slab.receiveShadow = true; slab.castShadow = true; gWorld.add(slab);
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i], b = pts[(i + 1) % pts.length];
        const ax = px(a[0]), az = pz(a[1]), bx = px(b[0]), bz = pz(b[1]);
        const len = Math.hypot(bx - ax, bz - az); if (len < 0.05) continue;
        const mx = (ax + bx) / 2, mz = (az + bz) / 2, ry = -Math.atan2(bz - az, bx - ax);
        const sill = new T.Mesh(new T.BoxGeometry(len, SILL_H, TH), M.sill); sill.position.set(mx, SILL_H / 2 + 0.14, mz); sill.rotation.y = ry; sill.castShadow = true; sill.receiveShadow = true; gWorld.add(sill);
        const glassH = WALL_H - SILL_H - 0.14;
        const glass = new T.Mesh(new T.BoxGeometry(len, glassH, 0.05), M.glass); glass.position.set(mx, SILL_H + 0.14 + glassH / 2, mz); glass.rotation.y = ry; gWorld.add(glass);
        const top = new T.Mesh(new T.BoxGeometry(len, 0.14, TH), M.wall); top.position.set(mx, WALL_H + 0.07, mz); top.rotation.y = ry; top.castShadow = true; gWorld.add(top);
        const n = Math.max(1, Math.round(len / 2.4));
        for (let k = 1; k < n; k++) { const t = k / n, fx = ax + (bx - ax) * t, fz = az + (bz - az) * t; const fr = new T.Mesh(new T.BoxGeometry(0.06, glassH, TH * 0.9), M.frame); fr.position.set(fx, SILL_H + 0.14 + glassH / 2, fz); fr.rotation.y = ry; gWorld.add(fr); }
      }
      if (r.name) { const c = centroid(pts); const lbl = makeTextSprite(r.name, P); lbl.position.set(px(c[0]), WALL_H + 0.7, pz(c[1])); gWorld.add(lbl); }
    });
    (cams || []).forEach(c => {
      if (c.x == null || c.y == null) return;
      const cx = px(c.x), cz = pz(c.y), dir = (c.direction || 0) * Math.PI / 180, camH = IMG_WALL_H + 0.1;
      // gövde: mercek (+Z) 2B yönüyle aynı tarafa baksın (0° = doğu/+x, saat yönü) → rotation.y = π/2 − dir
      const g = new T.Group(); g.position.set(cx, camH, cz); g.rotation.y = Math.PI / 2 - dir; gWorld.add(g);
      const body = new T.Mesh(new T.BoxGeometry(0.26, 0.2, 0.36), M.cam); body.castShadow = true; g.add(body);
      const lens = new T.Mesh(new T.SphereGeometry(0.08, 14, 12), new T.MeshStandardMaterial({ color: 0x11161f, roughness: 0.15, metalness: 0.9 })); lens.position.set(0, -0.02, 0.2); g.add(lens);
      body.userData.cam = { id: c.camera_id, name: c.camera_name || c.name || `Kamera #${c.camera_id}`, live: true }; camMeshes.push(body);
      // kapsama: kameradan zemine eğimli görüş hunisi (tepe mercekte, geniş kenar yerde); 2B ile aynı yön/açı, 70×1.5 birim, amber
      gWorld.add(viewCone(cx, cz, camH, dir, 70 * 1.5 * X.s, 0xf59e0b));
    });
    (stairs || []).forEach(sObj => { if (sObj.x == null || sObj.y == null) return; const m = new T.Mesh(new T.BoxGeometry(1.4, 0.5, 1.4), M.sill); m.position.set(px(sObj.x), 0.25, pz(sObj.y)); m.castShadow = true; gWorld.add(m); });
    // altyapı işaretçileri: planlanan kameralar duvar üstünde küçük gövde+lens (vantra), diğerleri zeminde küçük renkli nokta + minik rozet
    let camCount = (cams || []).length;
    const lensMat = new T.MeshStandardMaterial({ color: 0x11161f, roughness: 0.15, metalness: 0.9 });
    (markers || []).forEach(m => {
      if (m.x == null || m.y == null) return;
      const meta = palette[m.kind] || { color: '#64748b', icon: '' };
      const col = new T.Color(meta.color), x = px(m.x), z = pz(m.y);
      if (/^cam/.test(m.kind || '')) {
        if (!m.camera_id) return;   // NVR bağlı olmayan kamera işaretçileri 3B'de hiç çizilmez (listede de yok)
        camCount++;
        const g = new T.Group(); g.position.set(x, IMG_WALL_H + 0.1, z); gWorld.add(g);
        const mast = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 0.22, 6), M.cam); mast.position.y = -0.1; g.add(mast);
        const body = new T.Mesh(new T.BoxGeometry(0.2, 0.16, 0.3), M.cam); body.position.y = 0.06; body.castShadow = true; g.add(body);
        const lens = new T.Mesh(new T.SphereGeometry(0.06, 12, 10), lensMat); lens.position.set(0, 0.04, 0.17); g.add(lens);
        const led = new T.Mesh(new T.SphereGeometry(0.022, 8, 8), new T.MeshBasicMaterial({ color: 0xf43f5e })); led.position.set(0.07, 0.12, 0.1); g.add(led);
        const dir = (m.direction || 0) * Math.PI / 180; g.rotation.y = Math.PI / 2 - dir;   // mercek (+Z) 2B yönüne baksın
        body.userData.cam = { id: m.camera_id || null, name: m.label || m.camera_name || m.name || `${meta.label || 'Kamera'} ${camMeshes.length + 1}`, live: !!m.camera_id }; camMeshes.push(body);
        gWorld.add(viewCone(x, z, IMG_WALL_H + 0.1, dir, (m.kind === 'cam_outdoor' ? 95 : 72) * 1.5 * X.s, 0x38bdf8));   // 2B ile aynı yön/açı, mavi
        return;
      }
      const dot = new T.Mesh(new T.SphereGeometry(0.085, 12, 10), new T.MeshStandardMaterial({ color: col, roughness: 0.35, metalness: 0.2 }));
      dot.position.set(x, 0.09, z); dot.castShadow = true; gWorld.add(dot);
      const halo = new T.Mesh(new T.RingGeometry(0.12, 0.2, 24), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.35, side: T.DoubleSide }));
      halo.rotation.x = -Math.PI / 2; halo.position.set(x, 0.02, z); gWorld.add(halo);
      if (meta.icon) { const em = emojiSprite(meta.icon); em.scale.set(0.34, 0.34, 1); em.position.set(x, 0.42, z); gWorld.add(em); }
    });
    el.nCams.textContent = camCount; el.nMarkers.textContent = (markers || []).length;
    // panel listesi: ad (etiket › NVR adı › tür N) + sahnedeki gövde (tıklayınca yerinde önizleme)
    camNames = camMeshes.map(mh => mh.userData.cam.name);
    renderCamPanel();
  };

  // ---------- arka plan kat planı: beyaz kat plakası + soluk resim + RESİMDEN 3B DUVARLAR ----------
  // ---------- bölge tespiti: duvar segmentlerinden kapalı alanlar (grid + dilate + flood-fill) ----------
  function detectRooms(segs, bb) {
    const W = bb.x1 - bb.x0, H = bb.z1 - bb.z0; if (!(W > 0 && H > 0) || !segs.length) return [];
    const GX = 220, GZ = Math.max(24, Math.round(GX * H / W)), cw = W / GX, ch = H / GZ, N = GX * GZ;
    const wall = new Uint8Array(N);
    const mark = (x, z) => { const gx = Math.floor((x - bb.x0) / cw), gz = Math.floor((z - bb.z0) / ch); if (gx >= 0 && gz >= 0 && gx < GX && gz < GZ) wall[gz * GX + gx] = 1; };
    segs.forEach(s => { const n = Math.max(1, Math.ceil(s.len / (Math.min(cw, ch) * 0.5))); for (let i = 0; i <= n; i++) { const t = i / n; mark(s.ax + (s.bx - s.ax) * t, s.az + (s.bz - s.az) * t); } });
    const r = Math.max(2, Math.round(GX * 0.028)), dil = new Uint8Array(N);   // kapı boşluklarını kapat (geniş kapılar dâhil)
    for (let z = 0; z < GZ; z++) for (let x = 0; x < GX; x++) if (wall[z * GX + x]) for (let dz = -r; dz <= r; dz++) for (let dx = -r; dx <= r; dx++) { if (dx * dx + dz * dz > r * r) continue; const xx = x + dx, zz = z + dz; if (xx >= 0 && zz >= 0 && xx < GX && zz < GZ) dil[zz * GX + xx] = 1; }
    const lab = new Int32Array(N), stack = [];
    const nb4 = i => { const x = i % GX, z = (i - x) / GX; return [x > 0 ? i - 1 : -1, x < GX - 1 ? i + 1 : -1, z > 0 ? i - GX : -1, z < GZ - 1 ? i + GX : -1]; };
    const seed = i => { if (i >= 0 && !dil[i] && lab[i] === 0) { lab[i] = -1; stack.push(i); } };
    for (let x = 0; x < GX; x++) { seed(x); seed((GZ - 1) * GX + x); } for (let z = 0; z < GZ; z++) { seed(z * GX); seed(z * GX + GX - 1); }
    while (stack.length) nb4(stack.pop()).forEach(seed);                      // dış alan = -1
    const comps = []; let next = 1;
    for (let i0 = 0; i0 < N; i0++) {
      if (dil[i0] || lab[i0] !== 0) continue;
      const id = next++; let cnt = 0; lab[i0] = id; stack.push(i0);
      while (stack.length) { const i = stack.pop(); cnt++; for (const j of nb4(i)) if (j >= 0 && !dil[j] && lab[j] === 0) { lab[j] = id; stack.push(j); } }
      comps.push({ id, cnt });
    }
    const minArea = N * 0.0015, keepC = comps.filter(c => c.cnt >= minArea).sort((a, b) => b.cnt - a.cnt).slice(0, 60);   // küçük odalar (tuvalet, sunucu) da bölge olsun
    const keepIds = new Set(keepC.map(c => c.id)); for (let i = 0; i < N; i++) if (lab[i] > 0 && !keepIds.has(lab[i])) lab[i] = 0;
    let fr = []; for (let i = 0; i < N; i++) if (lab[i] > 0) fr.push(i);     // dilate kalınlığını geri ver (duvara kadar büyüt)
    for (let it = 0; it <= r && fr.length; it++) { const nx = []; for (const i of fr) for (const j of nb4(i)) if (j >= 0 && !wall[j] && lab[j] === 0) { lab[j] = lab[i]; nx.push(j); } fr = nx; }
    zoneGrid = { lab, GX, GZ, cw, ch, x0: bb.x0, z0: bb.z0 };
    const out = []; let n = 1;
    keepC.forEach(c => { const cells = []; let sx = 0, sz = 0; for (let i = 0; i < N; i++) if (lab[i] === c.id) { cells.push(i); const x = i % GX; sx += x; sz += (i - x) / GX; } if (!cells.length) return; out.push({ id: c.id, name: `Bölge ${n++}`, cells, cx: bb.x0 + (sx / cells.length + 0.5) * cw, cz: bb.z0 + (sz / cells.length + 0.5) * ch, people: 0 }); });
    return out;
  }
  function zoneAt(x, z) {
    if (!zoneGrid) return null; const { lab, GX, GZ, cw, ch, x0, z0 } = zoneGrid;
    const gx = Math.floor((x - x0) / cw), gz = Math.floor((z - z0) / ch); if (gx < 0 || gz < 0 || gx >= GX || gz >= GZ) return null;
    const id = lab[gz * GX + gx]; return id > 0 ? (zones.find(zn => zn.id === id) || null) : null;
  }
  // Yazıcı Odası: /api/printers kayıtları, önceki 3B raf düzeniyle (sol/sağ raf, 2 kat, slot sırası) odanın içine ölçeklenerek yerleştirilir
  function buildPrinters() {
    disposeGroup(gPrinters);
    if (!printers.length || !zoneGrid) return;
    const zn = zones.find(z => /yaz[ıi]c[ıi]|printer/i.test(z.name || '')); if (!zn) return;
    const { GX, cw, ch, x0, z0 } = zoneGrid;
    let gx0 = Infinity, gx1 = -Infinity, gz0 = Infinity, gz1 = -Infinity;
    zn.cells.forEach(i => { const gx = i % GX, gz = (i - gx) / GX; if (gx < gx0) gx0 = gx; if (gx > gx1) gx1 = gx; if (gz < gz0) gz0 = gz; if (gz > gz1) gz1 = gz; });
    const bx0 = x0 + gx0 * cw, bx1 = x0 + (gx1 + 1) * cw, bz0 = z0 + gz0 * ch, bz1 = z0 + (gz1 + 1) * ch;
    const W = bx1 - bx0, D = bz1 - bz0; if (W < 0.5 || D < 0.5) return;
    const along = W >= D, long = Math.max(W, D), short = Math.min(W, D);         // raflar odanın uzun kenarına paralel
    const slots = Math.max(1, Math.ceil(printers.length / 4), ...printers.map(p => +p.rack_slot || 1));
    // yazıcı ölçeği: hedef 3× (0.64×3 aralık), oda dar/kısaysa sığacak kadar küçülür; yükseklik duvarı aşmasın diye ayrıca sınırlı
    const PITCH = Math.min(0.64 * 3, (long * 0.8) / slots), k = PITCH / 0.64, ky = Math.min(k, 1.4);
    const RW = 0.5 * k, RD = 0.52 * k, PH = 0.55 * ky, SHELF = [0.08 * ky, 0.78 * ky], RH = SHELF[1] + PH + 0.15;
    const AISLE = Math.max(0.4 * k, Math.min(2.2 * k, short - 2 * RD - 0.3)), len = slots * PITCH;
    const g = new T.Group(); g.position.set((bx0 + bx1) / 2, 0, (bz0 + bz1) / 2); if (!along) g.rotation.y = Math.PI / 2; gPrinters.add(g);
    const rackMat = new T.MeshStandardMaterial({ color: 0x8a94a6, roughness: 0.6, metalness: 0.5 });
    const shelfMat = new T.MeshStandardMaterial({ color: 0xd7dce6, roughness: 0.7 });
    [-1, 1].forEach(side => {
      const zc = side * (AISLE / 2 + RD / 2);
      SHELF.forEach(y => { const sh = new T.Mesh(new T.BoxGeometry(len, 0.03 * ky, RD), shelfMat); sh.position.set(0, y, zc); sh.receiveShadow = true; g.add(sh); });
      [-len / 2, len / 2].forEach(x => [zc - RD / 2, zc + RD / 2].forEach(z => { const post = new T.Mesh(new T.BoxGeometry(0.03 * k, RH, 0.03 * k), rackMat); post.position.set(x, RH / 2, z); g.add(post); }));
    });
    const bodyMat = new T.MeshStandardMaterial({ color: 0x1f2430, roughness: 0.5, metalness: 0.3 });
    const glassMat = new T.MeshPhysicalMaterial({ color: 0x9ec5ff, transparent: true, opacity: 0.38, roughness: 0.1, metalness: 0, clearcoat: 1, side: T.DoubleSide });
    printerMeshes = [];
    printers.forEach((p, i) => {
      const side = String(p.rack_side || (i % 2 ? 'R' : 'L')).toUpperCase().startsWith('R') ? 1 : -1;
      const level = Math.min(2, Math.max(1, +p.rack_level || 1)), slot = Math.max(1, +p.rack_slot || Math.floor(i / 4) + 1);
      const pg = new T.Group(); pg.position.set(-len / 2 + (slot - 0.5) * PITCH, SHELF[level - 1] + 0.015 * ky, side * (AISLE / 2 + RD / 2));
      pg.rotation.y = side > 0 ? Math.PI : 0;                                            // cam kapı koridora baksın
      const body = new T.Mesh(new T.BoxGeometry(RW, PH, RD * 0.9), bodyMat); body.position.y = PH / 2; body.castShadow = true; pg.add(body);
      body.userData.printer = p.id; printerMeshes.push(body);
      const door = new T.Mesh(new T.PlaneGeometry(RW * 0.8, PH * 0.62), glassMat); door.position.set(0, PH * 0.5, RD * 0.45 + 0.004); pg.add(door);
      const stt = prState(p), col = PR_STATE[stt] || PR_STATE.CEVRIMDISI;
      const led = new T.Mesh(new T.SphereGeometry(0.03 * k, 8, 8), new T.MeshBasicMaterial({ color: col })); led.position.set(RW * 0.36, PH * 0.9, RD * 0.46); pg.add(led);
      // canlı veri: üstte etiket YOK (kullanıcı isteği) — durum LED rengi + yazdırırken kapı altında ilerleme çubuğu; ayrıntı tıklayınca
      const prog = Math.max(0, Math.min(100, +p.live_progress || 0));
      if (stt === 'YAZDIRIYOR' || stt === 'DURAKLADI') {
        const bw = RW * 0.8, bar = new T.Mesh(new T.PlaneGeometry(bw, 0.04 * ky), new T.MeshBasicMaterial({ color: 0x2b3240 })); bar.position.set(0, PH * 0.12, RD * 0.45 + 0.006); pg.add(bar);
        const fill = new T.Mesh(new T.PlaneGeometry(Math.max(0.001, bw * prog / 100), 0.04 * ky), new T.MeshBasicMaterial({ color: col })); fill.position.set(-bw / 2 + bw * prog / 200, PH * 0.12, RD * 0.45 + 0.008); pg.add(fill);
      }
      g.add(pg);
    });
  }
  function renderZones() {
    disposeGroup(gZones);
    if (!zoneGrid || !zones.length) return;
    const { GX, cw, ch, x0, z0 } = zoneGrid, total = zones.reduce((a, zn) => a + zn.cells.length, 0);
    const inst = new T.InstancedMesh(new T.PlaneGeometry(cw * 1.03, ch * 1.03), M.zone, total);
    const m4 = new T.Matrix4(), q = new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), -Math.PI / 2), pos = new T.Vector3(), scl = new T.Vector3(1, 1, 1), col = new T.Color();
    let k = 0;
    zones.forEach((zn, zi) => { col.set(ZONE_COLORS[zi % ZONE_COLORS.length]); zn.cells.forEach(i => { const x = i % GX, z = (i - x) / GX; pos.set(x0 + (x + 0.5) * cw, 0.02, z0 + (z + 0.5) * ch); m4.compose(pos, q, scl); inst.setMatrixAt(k, m4); inst.setColorAt(k, col); k++; }); });
    inst.instanceMatrix.needsUpdate = true; if (inst.instanceColor) inst.instanceColor.needsUpdate = true; inst.renderOrder = 1; gZones.add(inst);
    // zarif küçük etiketler: bölge adları (duvar üstünün biraz altında) + serbest alan etiketleri
    zones.forEach(zn => { const lbl = makeLabelSprite(zn.name, P, !!zn.named); lbl.position.set(zn.cx, IMG_WALL_H - 0.35, zn.cz); gZones.add(lbl); });
    freeLabels.forEach(fl => { const lbl = makeLabelSprite(fl.name, P, true); lbl.position.set(fl.x, 0.75, fl.z); gZones.add(lbl); });
  }
  // kayıtlı etiketleri bölgelere eşle: etiket noktası bir bölgenin içindeyse o bölgenin adı olur, değilse serbest etiket
  function applyLabels() {
    freeLabels = [];
    zones.forEach((zn, i) => { zn.name = `Bölge ${i + 1}`; zn.named = false; zn.labelIdx = -1; });
    (labels || []).forEach((l, idx) => {
      if (!l || l.x == null || l.y == null || !l.name) return;
      const wx = px(l.x), wz = pz(l.y), zn = zoneAt(wx, wz);
      if (zn) { zn.name = l.name; zn.named = true; zn.labelIdx = idx; }
      else freeLabels.push({ x: wx, z: wz, name: l.name, idx });
    });
  }
  function renderZonePanel() {
    if (!el.zones) return;
    const nz = hud.parentElement && hudR.querySelector('.n-zones'); if (nz) nz.textContent = zones.length + freeLabels.length;
    if (!zones.length && !freeLabels.length) { el.zones.innerHTML = '<div class="f3d-empty">Bu katta bölüm bulunamadı</div>'; return; }
    // adlandırılmış bölümler önce; tanınmayan alan etiketleri (Montaj Hattı, Pilot…) de bölüm olarak listelenir (kişi: etiket yakınında)
    const named = zones.map((zn, i) => ({ name: zn.name, people: zn.people, color: ZONE_COLORS[i % ZONE_COLORS.length], named: zn.named }));
    const frees = freeLabels.map(fl => ({ name: fl.name, people: fl.people || 0, color: 0xcfd6e4, named: true }));
    const rows = [...named.filter(r => r.named), ...frees, ...named.filter(r => !r.named)];
    el.zones.innerHTML = rows.map(r => `<div class="f3d-row"><i class="f3d-sw" style="background:#${r.color.toString(16).padStart(6, '0')}"></i><span class="f3d-nm"><b>${esc(r.name)}</b></span><span class="f3d-cnt${r.people ? ' on' : ''}">${r.people} kişi</span></div>`).join('');
  }
  function renderCamPanel() {
    if (!el.cams) return;
    el.nCamList.textContent = camNames.length;
    el.cams.innerHTML = camNames.length
      ? camNames.map((nm, i) => `<div class="f3d-row f3d-camrow" data-i="${i}" title="Kameranın yerinde önizleme"><span class="f3d-rec"><i></i>${camMeshes[i] && camMeshes[i].userData.cam.live ? 'REC' : 'PLAN'}</span><span class="f3d-nm"><b>${esc(nm)}</b></span></div>`).join('')
      : '<div class="f3d-empty">Kamera yok</div>';
    // satıra tıkla → o kameranın sahnedeki yerinde sabit önizleme (ekran koordinatına izdüşüm)
    el.cams.querySelectorAll('.f3d-camrow').forEach(row => row.onclick = () => {
      const mh = camMeshes[+row.dataset.i]; if (!mh) return;
      const r = renderer.domElement.getBoundingClientRect(), v = new T.Vector3(); mh.getWorldPosition(v); v.project(camera);
      showCam(mh.userData.cam, r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height, true);
    });
  }

  // Kamera görüş hunisi: tepe noktası kamera yüksekliğinde (mercek), geniş kenarı zemine iner; yön 2B ile aynı (0°=+x, saat yönü)
  function viewCone(cx, cz, h, dir, len, color) {
    const L = Math.hypot(len, h), tilt = Math.atan2(h, len);
    const sg = new T.Group(); sg.position.set(cx, h, cz); sg.rotation.y = -dir;      // grup +X → dünya (cos dir, sin dir)
    const sec = makeSectorPlane(L, 1.2, color);
    sec.rotation.set(-Math.PI / 2, 0, -tilt, 'ZYX');                                  // önce yatır, sonra +X'i aşağı eğ
    sec.position.set(L / 2 * Math.cos(tilt), -L / 2 * Math.sin(tilt), 0);             // tepe (apex) tam kamerada
    sg.add(sec); return sg;
  }

  let bgReq = 0, lastWalls = null, wallErr = null;
  function buildBg(bg, after) {
    disposeGroup(gBg); disposeGroup(gZones); disposeGroup(gPrinters); zones = []; zoneGrid = null; renderZonePanel();
    if (!bg || !bg.url) { after && after(null); return; }
    const req = ++bgReq;
    const img = new Image(); img.crossOrigin = 'anonymous';
    img.onload = () => {
      if (req !== bgReq) return;
      const nw = img.naturalWidth || 800, nh = img.naturalHeight || 600, sc = bg.scale || 1;
      const box = { x0: bg.x || 0, y0: bg.y || 0, x1: (bg.x || 0) + nw * sc, y1: (bg.y || 0) + nh * sc };
      after && after(box);                       // dönüşüm bu kutuyu da kapsasın
      const W = nw * sc * X.s, H = nh * sc * X.s, cx = px(box.x0 + nw * sc / 2), cz = pz(box.y0 + nh * sc / 2);
      // kalın beyaz kat plakası (üst yüzey y=0)
      const slab = new T.Mesh(new T.BoxGeometry(W + 0.6, SLAB_T, H + 0.6), [M.slabSide, M.slabSide, M.slab, M.slabSide, M.slabSide, M.slabSide]);
      slab.position.set(cx, -SLAB_T / 2, cz); slab.receiveShadow = true; slab.castShadow = true; gBg.add(slab);
      // soluk plan resmi (zemin dokusu)
      const tex = new T.Texture(img); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; tex.needsUpdate = true;
      const plane = new T.Mesh(new T.PlaneGeometry(W, H), new T.MeshBasicMaterial({ map: tex, transparent: true, opacity: dark ? 0.18 : 0.28, depthWrite: false }));
      plane.rotation.x = -Math.PI / 2; plane.position.set(cx, 0.012, cz); plane.receiveShadow = true; gBg.add(plane);
      // plandaki duvar çizgilerini 3B duvara çevir: SVG ise vektörden (hassas), raster ise piksel taramasından
      const geo = { x: box.x0, y: box.y0, scale: sc };
      const place = segs => {
        if (req !== bgReq) return;
        const keep = [], dropped = [];
        for (const s of segs) {
          const ax = px(s.ax), az = pz(s.az), bx = px(s.bx), bz = pz(s.bz);
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.22) { if (dropped.length < 4) dropped.push({ raw: [s.ax, s.az, s.bx, s.bz].map(v => +v.toFixed(1)), len: +len.toFixed(3) }); continue; }
          keep.push({ ax, az, bx, bz, len, th: s.th != null ? Math.min(Math.max(s.th * X.s, 0.05), 0.09) : 0.06 });   // ince duvar
          if (keep.length >= 24000) break;
        }
        lastWalls = { total: segs.length, kept: keep.length, X: { ...X }, dropped, keptSample: keep.slice(0, 3).map(k => ({ ax: +k.ax.toFixed(2), az: +k.az.toFixed(2), bx: +k.bx.toFixed(2), bz: +k.bz.toFixed(2), len: +k.len.toFixed(2) })) };
        if (!keep.length) return;
        // vantra pencere duvarı: opak alt eşik + şeffaf cam + ince üst kiriş (her biri tek InstancedMesh)
        const SILL = 0.26, RAIL = 0.05, GH = IMG_WALL_H - SILL - RAIL;
        const layer = (mat, y, h, thMul, shadow) => {
          const inst = new T.InstancedMesh(new T.BoxGeometry(1, 1, 1), mat, keep.length);
          const m4 = new T.Matrix4(), q = new T.Quaternion(), up = new T.Vector3(0, 1, 0), pos = new T.Vector3(), scl = new T.Vector3();
          keep.forEach((s, i) => {
            pos.set((s.ax + s.bx) / 2, y + h / 2, (s.az + s.bz) / 2);
            q.setFromAxisAngle(up, -Math.atan2(s.bz - s.az, s.bx - s.ax));
            scl.set(s.len + s.th * 0.6, h, s.th * thMul);   // köşeler kapansın diye hafif uzat
            m4.compose(pos, q, scl); inst.setMatrixAt(i, m4);
          });
          inst.instanceMatrix.needsUpdate = true; inst.castShadow = shadow; inst.receiveShadow = shadow; gBg.add(inst); return inst;
        };
        layer(M.sill, 0, SILL, 1, true);
        const gl = layer(M.imgGlass, SILL, GH, 0.5, false); gl.renderOrder = 2;
        layer(M.wall, SILL + GH, RAIL, 1.1, true);
        // kapalı alanları bölge olarak tanı → zemin tonu + etiket + kişi sayımı
        try { zones = detectRooms(keep, { x0: px(box.x0), z0: pz(box.y0), x1: px(box.x1), z1: pz(box.y1) }); } catch { zones = []; }
        applyLabels(); renderZones(); buildPrinters(); if (last && last.people) updateLive(last.people); else renderZonePanel();
      };
      const isSvg = /\.svg(\?|#|$)/i.test(bg.url) || /^data:image\/svg/i.test(bg.url);
      wallErr = null;
      if (isSvg) svgWalls(bg.url, nw, nh, geo).then(place).catch(e => { wallErr = String(e && e.message || e); place(extractWalls(img, geo)); });
      else place(extractWalls(img, geo));
    };
    img.onerror = () => { after && after(null); };
    img.src = bg.url;
  }

  // ---------- canlı personel ----------
  const texLoader = new T.TextureLoader();
  const updateLive = (people) => {
    disposeGroup(gLive);
    const ppl = (people || []).filter(p => p.x != null && p.y != null);
    const spots = new Map();
    ppl.forEach(p => { const k = `${Math.round(p.x)},${Math.round(p.y)}`; if (!spots.has(k)) spots.set(k, []); spots.get(k).push(p); });
    spots.forEach(list => list.forEach((p, i) => {
      const n = list.length, off = n > 1 ? 0.95 : 0, ang = (i / n) * Math.PI * 2;
      const sx = px(p.x) + Math.cos(ang) * off, sz = pz(p.y) + Math.sin(ang) * off;
      // Kişi: üstte daire içinde fotoğraf (çevrimiçi yeşil / çevrimdışı gri çerçeve), altında çok ince çubuk; isim yazılmaz
      const recent = isRecent(p.at), col = new T.Color(ageColor(p.at));
      const stem = new T.Mesh(new T.CylinderGeometry(0.012, 0.012, 2.2, 6), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: recent ? 0.7 : 0.4 }));
      stem.position.set(sx, 1.1, sz); gLive.add(stem);
      const foot = new T.Mesh(new T.CircleGeometry(0.07, 16), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: recent ? 0.9 : 0.5 }));
      foot.rotation.x = -Math.PI / 2; foot.position.set(sx, 0.025, sz); gLive.add(foot);
      const grp = new T.Group(); grp.position.set(sx, 2.75, sz); grp.userData.bill = true; gLive.add(grp);
      const border = new T.Mesh(new T.CircleGeometry(0.6, 40), new T.MeshBasicMaterial({ color: col, depthTest: false, toneMapped: false, transparent: true, opacity: recent ? 1 : 0.85 })); border.renderOrder = 10; grp.add(border);
      const face = new T.Mesh(new T.CircleGeometry(0.52, 40), new T.MeshBasicMaterial({ map: initialTex(p.subject_name, col), depthTest: false, toneMapped: false, transparent: true, opacity: recent ? 1 : 0.8 })); face.position.z = 0.01; face.renderOrder = 11; grp.add(face);
      if (p.crop) texLoader.load(fileUrl(p.crop, 128), tex => { if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; face.material.map = roundTex(tex); face.material.needsUpdate = true; }, undefined, () => {});
    }));
    zones.forEach(zn => { zn.people = 0; });
    ppl.filter(p => isRecent(p.at)).forEach(p => { const zn = zoneAt(px(p.x), pz(p.y)); if (zn) zn.people++; });   // yalnız yakın görülenler "sahada"
    renderZonePanel();
    renderPeople((people || []));
  };

  // ---------- render döngüsü ----------
  let raf = 0, running = false;
  const tick = () => { if (!running) return; raf = requestAnimationFrame(tick); controls.update(); gLive.children.forEach(o => { if (o.userData.bill) o.quaternion.copy(camera.quaternion); }); renderer.render(scene, camera); };
  const start = () => { if (!running) { running = true; tick(); } };
  const stop = () => { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; };
  const resize = () => { const w = mountEl.clientWidth, h = mountEl.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  const ro = new ResizeObserver(resize); ro.observe(mountEl);
  // ---------- kamera üzerine gel / dokun → bağlı NVR kamerasının canlı görüntüsü (anlık kare, 1.5 sn'de bir yenilenir) ----------
  const camBox = document.createElement('div'); camBox.className = 'f3d-cam'; camBox.hidden = true; mountEl.appendChild(camBox);
  let camCur = null, camTimer = 0, camPinned = false;
  const camRay = new T.Raycaster(), camNdc = new T.Vector2();
  const frameUrl = id => `/api/cameras/${id}/frame?t=${Date.now()}`;
  const hideCam = () => { camBox.hidden = true; camCur = null; camPinned = false; if (camTimer) { clearInterval(camTimer); camTimer = 0; } };
  const showCam = (cam, clientX, clientY, pinned) => {
    const rect = mountEl.getBoundingClientRect();
    const lx = Math.min(rect.width - 246, Math.max(0, clientX - rect.left)), ly = Math.max(150, clientY - rect.top);
    camBox.style.left = lx + 'px'; camBox.style.top = ly + 'px';
    camBox.classList.toggle('touch', !!pinned);
    if (camCur !== cam.id || camBox.hidden || camPinned !== !!pinned) {
      camCur = cam.id;
      camBox.innerHTML = `<div class="f3d-cam-hd">📷 ${esc(cam.name)}${cam.live ? '<span class="f3d-rec"><i></i>CANLI</span>' : ''}${pinned ? '<button class="f3d-cam-x" type="button" aria-label="Kapat">✕</button>' : ''}</div>`
        + (cam.live ? `<img alt="" src="${frameUrl(cam.id)}">` : '') + `<div class="f3d-cam-ft">${cam.live ? 'NVR anlık görüntü · sürekli yenilenir' : 'Planlanan kamera — NVR bağlı değil'}</div>`;
      const x = camBox.querySelector('.f3d-cam-x'); if (x) x.onclick = hideCam;
      const im = camBox.querySelector('img'); if (im) im.onerror = () => { const ft = camBox.querySelector('.f3d-cam-ft'); if (ft) ft.textContent = 'Görüntü alınamadı — kamera çevrimdışı olabilir'; };
      if (camTimer) clearInterval(camTimer);
      if (cam.live) { const img = camBox.querySelector('img'); camTimer = setInterval(() => { if (!camBox.hidden && img) img.src = frameUrl(cam.id); }, 1500); }
    }
    camBox.hidden = false; camPinned = !!pinned;
  };
  const camAt = (clientX, clientY) => {
    if (!camMeshes.length) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    camNdc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    camRay.setFromCamera(camNdc, camera);
    const hit = camRay.intersectObjects(camMeshes, false)[0];
    return hit ? hit.object.userData.cam : null;
  };
  // yazıcı gövdesi altında mı? (ekran koordinatı → yazıcı id)
  const printerAt = (cx, cy) => {
    if (!printerMeshes.length) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    camNdc.set(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    camRay.setFromCamera(camNdc, camera);
    const hit = camRay.intersectObjects(printerMeshes, false)[0];
    return hit ? hit.object.userData.printer : null;
  };
  renderer.domElement.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || camPinned) return;
    const cam = camAt(e.clientX, e.clientY);
    if (cam) { renderer.domElement.style.cursor = 'pointer'; showCam(cam, e.clientX, e.clientY, false); }
    else { renderer.domElement.style.cursor = (onPrinter && printerAt(e.clientX, e.clientY) != null) ? 'pointer' : 'grab'; if (!camBox.hidden) hideCam(); }
  });
  renderer.domElement.addEventListener('pointerleave', () => { if (!camPinned) hideCam(); });
  // dokunmatik / tıklama: kameraya dokununca sabitlenmiş önizleme (tekrar dokununca ya da ✕ ile kapanır); yazıcıya dokununca bilgi penceresi
  let prDown = null;
  renderer.domElement.addEventListener('pointerdown', e => { prDown = { x: e.clientX, y: e.clientY, t: Date.now() }; }, true);
  renderer.domElement.addEventListener('pointerup', e => {
    const d = prDown; prDown = null;
    if (onPrinter && d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6 && Date.now() - d.t < 500) {
      const pid = printerAt(e.clientX, e.clientY); if (pid != null) { if (camPinned) hideCam(); onPrinter(pid); return; }
    }
    const cam = camAt(e.clientX, e.clientY);
    if (cam) { if (camPinned && camCur === cam.id) hideCam(); else showCam(cam, e.clientX, e.clientY, true); }
    else if (camPinned) hideCam();
  }, true);
  const onVis = () => { if (document.hidden) stop(); else start(); };
  document.addEventListener('visibilitychange', onVis);
  const fit = () => { controls.target.set(0, 0.6, 0); camera.position.set(SPAN * 0.55, SPAN * 0.82, SPAN * 1.02); controls.update(); };

  makeMats(); buildBase(); resize(); fit(); start();

  let last = null;
  return {
    build({ rooms, cams, markers, stairs, floorName: fn, bg, palette: pal, floors: fl, floorId: fid, labels: lb, printers: pr }) {
      if (pal) palette = pal;
      if (lb) labels = lb;
      if (pr) printers = Array.isArray(pr) ? pr : [];
      if (fl) { floors = fl; } if (fid !== undefined) { floorId = fid; } renderFloors();
      if (fn != null) setFloorName(fn);
      last = { rooms, cams, markers, stairs };
      computeTransform(rooms, cams, markers, null); buildWorld(rooms, cams, markers, stairs); fit();
      // arka plan resmi yüklenince dönüşümü resmi kapsayacak şekilde yenile ve dünyayı yeniden kur
      buildBg(bg, box => { if (!box) return; computeTransform(rooms, cams, markers, box); buildWorld(rooms, cams, markers, stairs); if (last.people) updateLive(last.people); fit(); });
    },
    // canlı yazıcı verisi (durum / % / dosya) yenilenince rafı yeniden kur
    updatePrinters(list) { printers = Array.isArray(list) ? list : []; try { buildPrinters(); } catch (e) { console.warn('[factory3d] yazıcılar', e); } },
    updateLive(people) { if (last) last.people = people; updateLive(people); },
    stats() { return { walls: lastWalls, wallErr, scale: X.s }; },
    camScreenPos() {   // test/teşhis: kamera gövdelerinin ekran (client) koordinatları
      const r = renderer.domElement.getBoundingClientRect(), v = new T.Vector3();
      return camMeshes.map(m => { m.getWorldPosition(v); v.project(camera); return { name: m.userData.cam.name, x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height }; });
    },
    printerScreenPos() {   // test/teşhis: yazıcı gövdelerinin ekran koordinatları
      const r = renderer.domElement.getBoundingClientRect(), v = new T.Vector3();
      return printerMeshes.map(m => { m.getWorldPosition(v); v.project(camera); return { id: m.userData.printer, x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height }; });
    },
    setDark(d) { dark = !!d; P = dark ? PAL.dark : PAL.light; makeMats(); buildBase(); hud.classList.toggle('f3d-dark', dark); },
    resize,
    dispose() { stop(); ro.disconnect(); document.removeEventListener('visibilitychange', onVis); disposeGroup(gWorld); disposeGroup(gBg); disposeGroup(gZones); disposeGroup(gPrinters); disposeGroup(gLive); renderer.dispose(); renderer.domElement.remove(); hud.remove(); hudR.remove(); },
  };
}

// ---------- resimden duvar çıkarma ----------
// Koyu pikselleri (duvar çizgileri) tarar; yatay ve dikey ardışık koyu dizileri segment yapar.
// Kısa diziler (metin, gürültü) elenir. Plan koordinatına (bg.x/y + ölçek) çevrilir.
function extractWalls(img, bg) {
  const nw = img.naturalWidth || 800, nh = img.naturalHeight || 600, sc = bg.scale || 1;
  const cw = Math.min(nw, 560), ch = Math.max(1, Math.round(nh * cw / nw));
  const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
  const ctx = cv.getContext('2d', { willReadFrequently: true }); ctx.drawImage(img, 0, 0, cw, ch);
  let d; try { d = ctx.getImageData(0, 0, cw, ch).data; } catch { return []; }   // CORS ile boyanmış canvas → vazgeç
  // eşik: resmin parlaklık dağılımına göre (beyaz zemin + koyu çizgi varsayımı)
  let sum = 0, cnt = 0; for (let i = 0; i < cw * ch; i += 7) { if (d[i * 4 + 3] > 90) { sum += 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]; cnt++; } }
  const mean = cnt ? sum / cnt : 200, thr = Math.min(120, mean * 0.55);
  const dark = new Uint8Array(cw * ch);
  for (let i = 0; i < cw * ch; i++) { if (d[i * 4 + 3] < 90) continue; const l = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]; if (l < thr) dark[i] = 1; }
  const MIN = Math.max(4, Math.round(cw / 110)), segs = [];
  for (let y = 0; y < ch; y++) { let run = 0; for (let x = 0; x <= cw; x++) { const on = x < cw && dark[y * cw + x]; if (on) run++; else { if (run >= MIN) segs.push({ h: 1, x0: x - run, x1: x, y }); run = 0; } } }
  for (let x = 0; x < cw; x++) { let run = 0; for (let y = 0; y <= ch; y++) { const on = y < ch && dark[y * cw + x]; if (on) run++; else { if (run >= MIN) segs.push({ h: 0, y0: y - run, y1: y, x }); run = 0; } } }
  const ux = nw * sc / cw, uy = nh * sc / ch;
  return segs.map(s => s.h
    ? { ax: bg.x + s.x0 * ux, az: bg.y + (s.y + 0.5) * uy, bx: bg.x + s.x1 * ux, bz: bg.y + (s.y + 0.5) * uy, th: uy * 1.3 }
    : { ax: bg.x + (s.x + 0.5) * ux, az: bg.y + s.y0 * uy, bx: bg.x + (s.x + 0.5) * ux, bz: bg.y + s.y1 * uy, th: ux * 1.3 });
}

// ---------- SVG kat planından duvar çıkarma (vektör; line/polyline/polygon/rect/path) ----------
// Elemanlar geçici bir gizli <svg> içine alınır; getCTM ile iç transform'lar user-space'e çözülür.
// user-space (viewBox) → plan koordinatı: bg.x + (x - vbX) * (naturalW / vbW) * bg.scale
async function svgWalls(url, nw, nh, bg) {
  let txt;
  const dm = /^data:image\/svg\+xml(;[^,]*)?,(.*)$/is.exec(url);
  if (dm) {                                   // data: URL — CSP connect-src'den bağımsız, fetch'siz çöz
    const meta = dm[1] || '', body = dm[2];
    txt = /;base64/i.test(meta) ? decodeURIComponent(escape(atob(body))) : decodeURIComponent(body);
  } else {
    txt = await (await fetch(url, { credentials: 'same-origin' })).text();
  }
  const doc = new DOMParser().parseFromString(txt, 'image/svg+xml');
  const root = doc.documentElement;
  if (!root || root.nodeName.toLowerCase() !== 'svg') return [];
  const vb = (root.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
  const [vx, vy, vw, vh] = (vb.length === 4 && vb[2] > 0 && vb[3] > 0) ? vb : [0, 0, nw, nh];
  const sc = bg.scale || 1, kx = nw / vw * sc, ky = nh / vh * sc, th = Math.max(vw, vh) * 0.004 * kx;   // duvar kalınlığı (plan birimi)
  const host = document.createElement('div');
  host.style.cssText = 'position:absolute;left:-99999px;top:-99999px;width:10px;height:10px;overflow:hidden;visibility:hidden';
  const live = document.importNode(root, true); host.appendChild(live); document.body.appendChild(host);
  const segs = [];
  try {
    const pt = live.createSVGPoint();
    // İç transform yoksa koordinatlar zaten viewBox (user) uzayındadır — CTM'ye hiç dokunma (en sağlam yol).
    // Transform varsa: el.getCTM() kök svg'nin viewBox→viewport (px) dönüşümünü de içerir; kökün tersiyle sadeleştir.
    const needCTM = !!live.querySelector('[transform]');
    let rootInv = null; try { const rm = live.getCTM(); rootInv = rm ? rm.inverse() : null; } catch { rootInv = null; }
    const toUser = (el, x, y) => {
      if (!needCTM) return [x, y];
      try { let m = el.getCTM(); if (!m) return [x, y]; if (rootInv) m = rootInv.multiply(m); pt.x = x; pt.y = y; const p = pt.matrixTransform(m); return [p.x, p.y]; } catch { return [x, y]; }
    };
    const push = (el, x1, y1, x2, y2) => {
      const [ax, ay] = toUser(el, x1, y1), [bx, by] = toUser(el, x2, y2);
      if (!isFinite(ax + ay + bx + by)) return;
      segs.push({ ax: bg.x + (ax - vx) * kx, az: bg.y + (ay - vy) * ky, bx: bg.x + (bx - vx) * kx, bz: bg.y + (by - vy) * ky, th });
    };
    const num = v => parseFloat(v) || 0;
    const pts = s => (s || '').trim().split(/[\s,]+/).map(Number).filter(n => isFinite(n));
    live.querySelectorAll('line,polyline,polygon,rect,path').forEach(el => {
      if (segs.length > 40000) return;
      const tag = el.tagName.toLowerCase();
      const style = (el.getAttribute('style') || '') + ';';
      const stroke = el.getAttribute('stroke') || (style.match(/stroke:\s*([^;]+)/) || [])[1] || '';
      const fill = el.getAttribute('fill') || (style.match(/fill:\s*([^;]+)/) || [])[1] || '';
      if (stroke === 'none' && (fill === 'none' || !fill)) return;         // görünmez
      if (tag === 'line') push(el, num(el.getAttribute('x1')), num(el.getAttribute('y1')), num(el.getAttribute('x2')), num(el.getAttribute('y2')));
      else if (tag === 'polyline' || tag === 'polygon') { const p = pts(el.getAttribute('points')); for (let i = 2; i < p.length; i += 2) push(el, p[i - 2], p[i - 1], p[i], p[i + 1]); if (tag === 'polygon' && p.length >= 4) push(el, p[p.length - 2], p[p.length - 1], p[0], p[1]); }
      else if (tag === 'rect') { const x = num(el.getAttribute('x')), y = num(el.getAttribute('y')), w = num(el.getAttribute('width')), h = num(el.getAttribute('height')); if (w > 0 && h > 0) { push(el, x, y, x + w, y); push(el, x + w, y, x + w, y + h); push(el, x + w, y + h, x, y + h); push(el, x, y + h, x, y); } }
      else if (tag === 'path') {
        let L = 0; try { L = el.getTotalLength(); } catch { L = 0; }
        if (!(L > 0)) return;
        const n = Math.min(400, Math.max(2, Math.ceil(L / (Math.max(vw, vh) * 0.01))));
        let prev = null;
        for (let i = 0; i <= n; i++) { let p; try { p = el.getPointAtLength(L * i / n); } catch { break; } if (prev && (Math.abs(p.x - prev.x) + Math.abs(p.y - prev.y)) > 0.01) push(el, prev.x, prev.y, p.x, p.y); prev = p; }
      }
    });
  } finally { host.remove(); }
  return segs;
}

// ---------- yardımcılar ----------
function centroid(pts) { let x = 0, y = 0; pts.forEach(p => { x += p[0]; y += p[1]; }); return [x / pts.length, y / pts.length]; }
function roundTex(tex) {
  const T = _Tref, img = tex.image; if (!img) return tex;
  const S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S; const ctx = cv.getContext('2d');
  ctx.save(); ctx.beginPath(); ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2); ctx.clip(); ctx.drawImage(img, 0, 0, S, S); ctx.restore();
  const t = new T.CanvasTexture(cv); if ('colorSpace' in t) t.colorSpace = T.SRGBColorSpace; return t;
}
function initialTex(name, col) {
  const T = _Tref, S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S; const ctx = cv.getContext('2d');
  ctx.fillStyle = '#' + col.getHexString(); ctx.beginPath(); ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.font = 'bold 60px system-ui,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText((name || '?').slice(0, 1).toLocaleUpperCase('tr'), S / 2, S / 2 + 4);
  const t = new T.CanvasTexture(cv); if ('colorSpace' in t) t.colorSpace = T.SRGBColorSpace; return t;
}
function makeTextSprite(text, P, accentHex) {
  const T = _Tref, fs = 42, pad = 16, cv = document.createElement('canvas'), ctx = cv.getContext('2d');
  ctx.font = `600 ${fs}px system-ui,sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2, hh = fs + pad;
  cv.width = w; cv.height = hh; ctx.font = `600 ${fs}px system-ui,sans-serif`;
  ctx.fillStyle = P.labelBg; roundRect(ctx, 0, 0, w, hh, 12); ctx.fill();
  if (accentHex != null) { ctx.strokeStyle = '#' + accentHex.toString(16).padStart(6, '0'); ctx.lineWidth = 3; roundRect(ctx, 1.5, 1.5, w - 3, hh - 3, 11); ctx.stroke(); }
  ctx.fillStyle = P.label; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, w / 2, hh / 2 + 2);
  const tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace;
  const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, toneMapped: false }));
  sp.renderOrder = 12; sp.scale.set(cv.width / cv.height * 0.95, 0.95, 1); return sp;
}
// Zarif küçük alan etiketi (photoshop'taki gibi: ince yazı, beyaz hafif saydam kutu, ince kenar)
function makeLabelSprite(text, P, named) {
  const T = _Tref, fs = 30, pad = 14, cv = document.createElement('canvas'), ctx = cv.getContext('2d');
  const font = `${named ? 500 : 400} ${fs}px system-ui,-apple-system,"Segoe UI",sans-serif`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2, hh = fs + pad;
  cv.width = w; cv.height = hh; ctx.font = font;
  ctx.fillStyle = P.labelBg; roundRect(ctx, 0.5, 0.5, w - 1, hh - 1, 9); ctx.fill();
  ctx.strokeStyle = 'rgba(28,34,51,.14)'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.fillStyle = named ? P.label : 'rgba(28,34,51,.55)'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, w / 2, hh / 2 + 1);
  const tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace;
  const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, toneMapped: false }));
  sp.renderOrder = 8; const sc = 0.52; sp.scale.set(cv.width / cv.height * sc, sc, 1); return sp;
}
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
// Kamera kapsama alanı: zeminde yumuşak gradyanlı sektör (2B'deki üçgen/koni gibi). Doku önbelleklenir (fov+renk).
const _secCache = new Map();
function makeSectorPlane(lenWorld, fovRad, colorHex) {
  const T = _Tref, key = `${Math.round(fovRad * 100)}:${colorHex}`;
  let tex = _secCache.get(key);
  if (!tex) {
    const S = 256, cv = document.createElement('canvas'); cv.width = cv.height = S; const ctx = cv.getContext('2d');
    const c = '#' + colorHex.toString(16).padStart(6, '0');
    const g = ctx.createRadialGradient(4, S / 2, 0, 4, S / 2, S - 6);
    g.addColorStop(0, c + 'a6'); g.addColorStop(0.55, c + '55'); g.addColorStop(1, c + '00');
    ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(4, S / 2); ctx.arc(4, S / 2, S - 6, -fovRad / 2, fovRad / 2); ctx.closePath(); ctx.fill();
    tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; _secCache.set(key, tex);
  }
  const m = new T.Mesh(new T.PlaneGeometry(lenWorld, lenWorld), new T.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false, side: T.DoubleSide }));
  m.rotation.x = -Math.PI / 2; m.renderOrder = 3; return m;   // tepe noktası sol kenarda: konumlanırken yön boyunca len/2 kaydır
}
function emojiSprite(ch) {
  const T = _Tref, S = 96, cv = document.createElement('canvas'); cv.width = cv.height = S; const ctx = cv.getContext('2d');
  ctx.font = '60px system-ui,"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(ch, S / 2, S / 2 + 4);
  const tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace;
  const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, toneMapped: false }));
  sp.renderOrder = 9; sp.scale.set(0.5, 0.5, 1); return sp;
}

function ensureHudStyle() {
  if (document.getElementById('f3d-hud-style')) return;
  const st = document.createElement('style'); st.id = 'f3d-hud-style';
  st.textContent = `
  .f3d-hud{font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
  .f3d-card{background:rgba(255,255,255,.66);backdrop-filter:blur(18px) saturate(1.5);-webkit-backdrop-filter:blur(18px) saturate(1.5);border:1px solid rgba(255,255,255,.75);border-radius:18px;padding:14px 16px;box-shadow:0 2px 6px rgba(24,32,64,.05),0 14px 34px -10px rgba(24,32,64,.16);pointer-events:auto}
  .f3d-top{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#1c2233}
  .f3d-top b{font-weight:700}
  .f3d-chip{margin-left:auto;font-size:10px;letter-spacing:.08em;color:#7c6cf0;background:rgba(124,108,240,.12);border-radius:999px;padding:3px 8px;font-weight:700}
  .f3d-dot.live{width:8px;height:8px;border-radius:50%;background:#16a34a;animation:f3dpulse 1.8s infinite;flex:none}
  @keyframes f3dpulse{0%{box-shadow:0 0 0 0 rgba(22,163,74,.5)}70%{box-shadow:0 0 0 7px rgba(22,163,74,0)}100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}
  .f3d-floor{margin-top:8px;font-size:20px;font-weight:800;color:#1c2233;letter-spacing:-.02em}
  .f3d-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}
  .f3d-stat{border-radius:12px;padding:8px 6px;text-align:center}
  .f3d-stat b{display:block;font-size:18px;font-weight:800;line-height:1.1}
  .f3d-stat span{font-size:10.5px;color:#5b6170}
  .f3d-stat.v{background:rgba(124,108,240,.14)}.f3d-stat.v b{color:#6a58e8}
  .f3d-stat.c{background:rgba(14,165,233,.14)}.f3d-stat.c b{color:#0284c7}
  .f3d-stat.m{background:rgba(22,163,74,.13)}.f3d-stat.m b{color:#15803d}
  .f3d-people{flex:1;min-height:0;display:flex;flex-direction:column}
  .f3d-sub{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#7a8296;font-weight:700;margin-bottom:8px}
  .f3d-list{overflow:auto;min-height:0;flex:1;display:flex;flex-direction:column;gap:6px}
  .f3d-row{display:flex;align-items:center;gap:9px;padding:6px 8px;border-radius:12px;background:rgba(255,255,255,.55)}
  .f3d-av{width:30px;height:30px;border-radius:50%;border:2px solid #16a34a;overflow:hidden;flex:none;display:flex;align-items:center;justify-content:center}
  .f3d-av img{width:100%;height:100%;object-fit:cover}
  .f3d-av i{font-style:normal;color:#fff;font-weight:700;font-size:13px;width:100%;height:100%;display:flex;align-items:center;justify-content:center}
  .f3d-nm{flex:1;min-width:0;line-height:1.15}
  .f3d-nm b{display:block;font-size:12.5px;color:#1c2233;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .f3d-nm small{font-size:10.5px;color:#7a8296}
  .f3d-age{font-size:11px;font-weight:700}
  .f3d-empty,.f3d-more{font-size:11.5px;color:#7a8296;padding:6px 2px}
  .f3d-leg{margin-top:8px;display:flex;gap:10px;font-size:10.5px;color:#5b6170;flex-wrap:wrap}
  .f3d-leg span{display:flex;align-items:center;gap:5px}
  .f3d-leg i{width:8px;height:8px;border-radius:50%;display:inline-block}
  .f3d-leg i.g{background:#16a34a}.f3d-leg i.y{background:#f59e0b}.f3d-leg i.r{background:#dc2626}.f3d-leg i.x{background:#98a2b3}
  .f3d-floors.seg{box-shadow:0 2px 6px rgba(24,32,64,.06),0 10px 24px -8px rgba(24,32,64,.14);backdrop-filter:blur(12px)}
  .f3d-cam{position:absolute;z-index:7;pointer-events:none;width:232px;border-radius:14px;overflow:hidden;background:rgba(255,255,255,.72);backdrop-filter:blur(16px) saturate(1.4);-webkit-backdrop-filter:blur(16px) saturate(1.4);border:1px solid rgba(255,255,255,.75);box-shadow:0 4px 12px rgba(24,32,64,.08),0 24px 56px -12px rgba(24,32,64,.22);transform:translate(14px,-100%);font-family:system-ui,-apple-system,sans-serif}
  .f3d-cam .f3d-cam-hd{display:flex;align-items:center;gap:6px;padding:7px 10px;font-size:11.5px;font-weight:700;color:#1c2233}
  .f3d-cam .f3d-cam-hd .f3d-rec{margin-left:auto}
  .f3d-cam img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:#111823}
  .f3d-cam .f3d-cam-ft{padding:5px 10px 7px;font-size:10.5px;color:#7a8296}
  .f3d-cam.touch{pointer-events:auto}
  .f3d-cam .f3d-cam-x{margin-left:6px;border:0;background:transparent;color:#7a8296;font-size:14px;cursor:pointer;pointer-events:auto}
  .f3d-dark .f3d-cam{background:rgba(18,24,40,.72);border-color:rgba(130,150,210,.3)}.f3d-dark .f3d-cam .f3d-cam-hd{color:#e8edf8}
  .f3d-floors{display:flex;gap:6px;flex-wrap:wrap;pointer-events:auto}
  .f3d-fl{border:1px solid rgba(255,255,255,.75);background:rgba(255,255,255,.66);backdrop-filter:blur(14px);border-radius:999px;padding:6px 12px;font-size:12px;font-weight:700;color:#3b4252;cursor:pointer}
  .f3d-fl.on{background:#7c6cf0;color:#fff;border-color:#7c6cf0}
  .f3d-scroll{overflow:auto;min-height:0}
  /* kart iskeleti: header (ince çizgi) · gövde · footer (hafif koyu zemin) */
  .f3d-card{padding:0;display:flex;flex-direction:column;min-height:0}
  .f3d-hd{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid rgba(28,34,51,.08);font-size:12.5px;color:#1c2233;flex:none;cursor:default;user-select:none}
  .f3d-hd .f3d-ttl{font-weight:700;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .f3d-hd .f3d-chip{margin-left:0}
  .f3d-ic{font-size:14px;line-height:1;flex:none}
  .f3d-bd{padding:12px 14px;min-height:0;overflow:auto;flex:1 1 auto}
  .f3d-ft{padding:7px 14px;border-top:1px solid rgba(28,34,51,.08);background:rgba(28,34,51,.045);font-size:10.5px;color:#6b7386;flex:none;border-radius:0 0 18px 18px}
  .f3d-ft.f3d-leg{margin-top:0;display:flex;gap:10px;flex-wrap:wrap}
  .f3d-main .f3d-bd{padding-top:10px}
  .f3d-people{flex:1 1 0}
  .f3d-right{height:calc(100% - 28px)}
  .f3d-right .f3d-card{flex:1 1 0;max-height:none}
  .f3d-right .f3d-zones,.f3d-right .f3d-cams{padding-right:10px}
  .f3d-camrow{cursor:pointer;pointer-events:auto}.f3d-camrow:hover{background:rgba(124,108,240,.12)}
  /* küçültülmüş kart: yalnız ikon */
  .f3d-card.f3d-min{flex:0 0 auto;width:46px;height:46px;border-radius:14px;align-items:center;justify-content:center;cursor:pointer}
  .f3d-card.f3d-min .f3d-bd,.f3d-card.f3d-min .f3d-ft,.f3d-card.f3d-min .f3d-hd>*:not(.f3d-ic){display:none}
  .f3d-card.f3d-min .f3d-hd{border:0;padding:0}
  .f3d-card.f3d-min .f3d-ic{font-size:20px}
  .f3d-dark .f3d-hd{color:#e8edf8;border-color:rgba(130,150,210,.2)}.f3d-dark .f3d-ft{border-color:rgba(130,150,210,.2);background:rgba(255,255,255,.05);color:#9aa6bd}
  /* ince, yumuşak kaydırma çubuğu (bölgeler / kameralar / kişiler) */
  .f3d-scroll,.f3d-list,.f3d-zones,.f3d-cams{scrollbar-width:thin;scrollbar-color:rgba(100,110,140,.28) transparent}
  .f3d-scroll::-webkit-scrollbar,.f3d-list::-webkit-scrollbar,.f3d-zones::-webkit-scrollbar,.f3d-cams::-webkit-scrollbar{width:5px}
  .f3d-scroll::-webkit-scrollbar-thumb,.f3d-list::-webkit-scrollbar-thumb,.f3d-zones::-webkit-scrollbar-thumb,.f3d-cams::-webkit-scrollbar-thumb{background:rgba(100,110,140,.28);border-radius:99px}
  .f3d-scroll::-webkit-scrollbar-thumb:hover,.f3d-zones::-webkit-scrollbar-thumb:hover,.f3d-cams::-webkit-scrollbar-thumb:hover{background:rgba(100,110,140,.45)}
  .f3d-scroll::-webkit-scrollbar-track,.f3d-list::-webkit-scrollbar-track,.f3d-zones::-webkit-scrollbar-track,.f3d-cams::-webkit-scrollbar-track{background:transparent}
  .f3d-zones,.f3d-cams{display:flex;flex-direction:column;gap:6px}
  .f3d-sw{width:11px;height:11px;border-radius:4px;flex:none;border:1px solid rgba(0,0,0,.08)}
  .f3d-cnt{font-size:11px;color:#7a8296;font-weight:700;white-space:nowrap}
  .f3d-cnt.on{color:#6a58e8}
  .f3d-rec{font-size:9.5px;letter-spacing:.08em;color:#e11d48;font-weight:800;display:flex;align-items:center;gap:4px;flex:none}
  .f3d-rec i{width:6px;height:6px;border-radius:50%;background:#e11d48;animation:f3dpulse 1.6s infinite}
  .f3d-dark .f3d-cnt{color:#aab4c8}.f3d-dark .f3d-cnt.on{color:#b6a8ff}
  .f3d-dark .f3d-card,.f3d-dark .f3d-fl{background:rgba(18,24,40,.62);border-color:rgba(130,150,210,.3)}
  .f3d-dark .f3d-top,.f3d-dark .f3d-floor,.f3d-dark .f3d-nm b{color:#e8edf8}
  .f3d-dark .f3d-row{background:rgba(255,255,255,.06)}
  .f3d-dark .f3d-stat span,.f3d-dark .f3d-sub,.f3d-dark .f3d-leg,.f3d-dark .f3d-nm small,.f3d-dark .f3d-empty,.f3d-dark .f3d-fl{color:#aab4c8}
  `;
  document.head.appendChild(st);
}
