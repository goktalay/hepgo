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

const WALL_H = 2.2, IMG_WALL_H = 1.75, TH = 0.12, SILL_H = 0.5, SPAN = 26, SLAB_T = 0.9;
let _Tref = null;

const PAL = {
  light: { grid1: 0xd3d9e6, grid2: 0xe3e8f1, slab: 0xffffff, slabSide: 0xeef1f8, deck: 0xf3f5fa, wall: 0xf7f8fc, sill: 0xe6eaf3, steel: 0xb7c2d6, label: '#1c2233', labelBg: 'rgba(255,255,255,.92)', accent: 0x7c6cf0 },
  dark: { grid1: 0x263252, grid2: 0x1b2540, slab: 0x1f2a44, slabSide: 0x182238, deck: 0x25304d, wall: 0x3a4664, sill: 0x2b3650, steel: 0x55617f, label: '#e8edf8', labelBg: 'rgba(18,24,40,.86)', accent: 0x9d8cff },
};
const ageColor = at => { const ms = at ? Date.now() - new Date(at).getTime() : Infinity; return ms <= 3e5 ? 0x16a34a : ms <= 36e5 ? 0xf59e0b : 0xdc2626; };
const ageText = at => { if (!at) return '—'; const m = Math.round((Date.now() - new Date(at).getTime()) / 60000); return m < 1 ? 'şimdi' : m < 60 ? `${m} dk` : `${Math.round(m / 60)} sa`; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export async function createFactory3D(mountEl, opts = {}) {
  const { T, OrbitControls } = await loadLibs();
  _Tref = T;
  const fileUrl = opts.fileUrl || (p => p);
  let dark = !!opts.dark, floorName = opts.floorName || '', palette = opts.palette || {};
  let floors = opts.floors || [], floorId = opts.floorId ?? null; const onFloor = opts.onFloor || null;
  let P = dark ? PAL.dark : PAL.light;

  // ---------- cam panel (HUD) ----------
  ensureHudStyle();
  const hud = document.createElement('div'); hud.className = 'f3d-hud';
  hud.style.cssText = 'position:absolute;left:14px;top:14px;bottom:14px;z-index:5;pointer-events:none;display:flex;flex-direction:column;gap:10px;max-width:290px';
  hud.innerHTML = `
    <div class="f3d-card">
      <div class="f3d-top"><span class="f3d-dot live"></span><b>Canlı İzleme · 3B</b><span class="f3d-chip">RTLS</span></div>
      <div class="f3d-floor"></div>
      <div class="f3d-stats">
        <div class="f3d-stat v"><b class="n-people">0</b><span>Kişi</span></div>
        <div class="f3d-stat c"><b class="n-cams">0</b><span>Kamera</span></div>
        <div class="f3d-stat m"><b class="n-markers">0</b><span>İşaretçi</span></div>
      </div>
    </div>
    <div class="f3d-card f3d-people">
      <div class="f3d-sub">Sahadaki kişiler</div>
      <div class="f3d-list"></div>
      <div class="f3d-leg"><span><i class="g"></i>çok yeni</span><span><i class="y"></i>1 saat içinde</span><span><i class="r"></i>daha eski</span></div>
    </div>
    <div class="f3d-floors"></div>`;
  mountEl.appendChild(hud); if (dark) hud.classList.add('f3d-dark');
  const q = s => hud.querySelector(s);
  const el = { floor: q('.f3d-floor'), nPeople: q('.n-people'), nCams: q('.n-cams'), nMarkers: q('.n-markers'), list: q('.f3d-list'), floors: q('.f3d-floors') };
  const renderFloors = () => {
    el.floors.innerHTML = '';
    if (!floors.length) return;
    floors.forEach(f => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'f3d-fl' + (f.id === floorId ? ' on' : ''); b.textContent = f.name;
      b.onclick = () => { if (onFloor) onFloor(f.id); }; el.floors.appendChild(b);
    });
  };
  const renderPeople = (ppl) => {
    el.nPeople.textContent = ppl.length;
    if (!ppl.length) { el.list.innerHTML = '<div class="f3d-empty">Son 10 dakikada tanınan kişi yok</div>'; return; }
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

  const hemi = new T.HemisphereLight(0xffffff, 0x9aa6bd, 1.0); scene.add(hemi);
  const key = new T.DirectionalLight(0xffffff, 1.45);
  key.position.set(18, 36, 20); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -34; key.shadow.camera.right = 34; key.shadow.camera.top = 34; key.shadow.camera.bottom = -34;
  key.shadow.camera.near = 1; key.shadow.camera.far = 120; key.shadow.bias = -0.0005; key.shadow.radius = 4;
  scene.add(key);
  const rim = new T.DirectionalLight(0xb9c6ff, 0.55); rim.position.set(-22, 14, -20); scene.add(rim);

  const gWorld = new T.Group(); scene.add(gWorld);
  const gBg = new T.Group(); scene.add(gBg);
  const gLive = new T.Group(); scene.add(gLive);
  let grid, M = {};

  const makeMats = () => {
    M.slab = new T.MeshStandardMaterial({ color: P.slab, roughness: 0.55, metalness: 0.05 });
    M.slabSide = new T.MeshStandardMaterial({ color: P.slabSide, roughness: 0.7, metalness: 0.05 });
    M.deck = new T.MeshStandardMaterial({ color: P.deck, roughness: 0.6, metalness: 0.1 });
    M.wall = new T.MeshStandardMaterial({ color: P.wall, roughness: 0.62, metalness: 0.04 });
    M.sill = new T.MeshStandardMaterial({ color: P.sill, roughness: 0.75, metalness: 0.05 });
    M.glass = new T.MeshPhysicalMaterial({ color: 0xa9cfdd, transmission: 0.9, thickness: 0.5, roughness: 0.14, metalness: 0, ior: 1.35, transparent: true, opacity: 0.4, side: T.DoubleSide });
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
    disposeGroup(gWorld);
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
      const g = new T.Group(); g.position.set(px(c.x), WALL_H + 0.05, pz(c.y)); gWorld.add(g);
      const dir = (c.direction || 0) * Math.PI / 180; g.rotation.y = -dir;
      const body = new T.Mesh(new T.BoxGeometry(0.26, 0.26, 0.4), M.cam); body.rotation.x = 0.4; body.castShadow = true; g.add(body);
      const lens = new T.Mesh(new T.SphereGeometry(0.1, 14, 12), new T.MeshStandardMaterial({ color: 0x11161f, roughness: 0.15, metalness: 0.9 })); lens.position.set(0, -0.06, 0.24); g.add(lens);
      const cone = new T.Mesh(new T.ConeGeometry(1.7, 4, 24, 1, true), M.cone); cone.position.set(0, -0.3, 2); cone.rotation.x = -Math.PI / 2; g.add(cone);
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
        camCount++;
        const g = new T.Group(); g.position.set(x, IMG_WALL_H + 0.1, z); gWorld.add(g);
        const mast = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 0.22, 6), M.cam); mast.position.y = -0.1; g.add(mast);
        const body = new T.Mesh(new T.BoxGeometry(0.2, 0.16, 0.3), M.cam); body.position.y = 0.06; body.castShadow = true; g.add(body);
        const lens = new T.Mesh(new T.SphereGeometry(0.06, 12, 10), lensMat); lens.position.set(0, 0.04, 0.17); g.add(lens);
        const led = new T.Mesh(new T.SphereGeometry(0.022, 8, 8), new T.MeshBasicMaterial({ color: 0xf43f5e })); led.position.set(0.07, 0.12, 0.1); g.add(led);
        return;
      }
      const dot = new T.Mesh(new T.SphereGeometry(0.085, 12, 10), new T.MeshStandardMaterial({ color: col, roughness: 0.35, metalness: 0.2 }));
      dot.position.set(x, 0.09, z); dot.castShadow = true; gWorld.add(dot);
      const halo = new T.Mesh(new T.RingGeometry(0.12, 0.2, 24), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.35, side: T.DoubleSide }));
      halo.rotation.x = -Math.PI / 2; halo.position.set(x, 0.02, z); gWorld.add(halo);
      if (meta.icon) { const em = emojiSprite(meta.icon); em.scale.set(0.34, 0.34, 1); em.position.set(x, 0.42, z); gWorld.add(em); }
    });
    el.nCams.textContent = camCount; el.nMarkers.textContent = (markers || []).length;
  };

  // ---------- arka plan kat planı: beyaz kat plakası + soluk resim + RESİMDEN 3B DUVARLAR ----------
  let bgReq = 0;
  function buildBg(bg, after) {
    disposeGroup(gBg);
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
        const keep = [];
        for (const s of segs) {
          const ax = px(s.ax), az = pz(s.az), bx = px(s.bx), bz = pz(s.bz);
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.22) continue;                      // kapı sembolü, köşe işareti vb. kısa parçalar
          keep.push({ ax, az, bx, bz, len, th: s.th != null ? Math.max(s.th * X.s, 0.14) : 0.14 });
          if (keep.length >= 24000) break;
        }
        if (!keep.length) return;
        const inst = new T.InstancedMesh(new T.BoxGeometry(1, 1, 1), M.wall, keep.length);
        const m4 = new T.Matrix4(), q = new T.Quaternion(), up = new T.Vector3(0, 1, 0), pos = new T.Vector3(), scl = new T.Vector3();
        keep.forEach((s, i) => {
          pos.set((s.ax + s.bx) / 2, IMG_WALL_H / 2, (s.az + s.bz) / 2);
          q.setFromAxisAngle(up, -Math.atan2(s.bz - s.az, s.bx - s.ax));
          scl.set(s.len + s.th * 0.6, IMG_WALL_H, s.th);  // köşeler kapansın diye hafif uzat
          m4.compose(pos, q, scl); inst.setMatrixAt(i, m4);
        });
        inst.instanceMatrix.needsUpdate = true; inst.castShadow = true; inst.receiveShadow = true; gBg.add(inst);
      };
      const isSvg = /\.svg(\?|#|$)/i.test(bg.url) || /^data:image\/svg/i.test(bg.url);
      if (isSvg) svgWalls(bg.url, nw, nh, geo).then(place).catch(() => place(extractWalls(img, geo)));
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
      const col = new T.Color(ageColor(p.at));
      const ring = new T.Mesh(new T.RingGeometry(0.42, 0.56, 40), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.8, side: T.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(sx, 0.03, sz); gLive.add(ring);
      const stem = new T.Mesh(new T.CylinderGeometry(0.025, 0.025, 2.4, 8), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.45 }));
      stem.position.set(sx, 1.2, sz); gLive.add(stem);
      const grp = new T.Group(); grp.position.set(sx, 2.95, sz); grp.userData.bill = true; gLive.add(grp);
      const back = new T.Mesh(new T.CircleGeometry(0.62, 40), new T.MeshBasicMaterial({ color: col, depthTest: false, toneMapped: false })); back.renderOrder = 10; grp.add(back);
      const face = new T.Mesh(new T.CircleGeometry(0.54, 40), new T.MeshBasicMaterial({ map: initialTex(p.subject_name, col), depthTest: false, toneMapped: false })); face.position.z = 0.01; face.renderOrder = 11; grp.add(face);
      if (p.crop) texLoader.load(fileUrl(p.crop, 128), tex => { if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; face.material.map = roundTex(tex); face.material.needsUpdate = true; }, undefined, () => {});
      const tag = makeTextSprite((p.subject_name || '—').slice(0, 16), P, col.getHex()); tag.position.set(sx, 4.0, sz); gLive.add(tag);
    }));
    renderPeople((people || []));
  };

  // ---------- render döngüsü ----------
  let raf = 0, running = false;
  const tick = () => { if (!running) return; raf = requestAnimationFrame(tick); controls.update(); gLive.children.forEach(o => { if (o.userData.bill) o.quaternion.copy(camera.quaternion); }); renderer.render(scene, camera); };
  const start = () => { if (!running) { running = true; tick(); } };
  const stop = () => { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; };
  const resize = () => { const w = mountEl.clientWidth, h = mountEl.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  const ro = new ResizeObserver(resize); ro.observe(mountEl);
  const onVis = () => { if (document.hidden) stop(); else start(); };
  document.addEventListener('visibilitychange', onVis);
  const fit = () => { controls.target.set(0, 0.6, 0); camera.position.set(SPAN * 0.55, SPAN * 0.82, SPAN * 1.02); controls.update(); };

  makeMats(); buildBase(); resize(); fit(); start();

  let last = null;
  return {
    build({ rooms, cams, markers, stairs, floorName: fn, bg, palette: pal, floors: fl, floorId: fid }) {
      if (pal) palette = pal;
      if (fl) { floors = fl; } if (fid !== undefined) { floorId = fid; } renderFloors();
      if (fn != null) setFloorName(fn);
      last = { rooms, cams, markers, stairs };
      computeTransform(rooms, cams, markers, null); buildWorld(rooms, cams, markers, stairs); fit();
      // arka plan resmi yüklenince dönüşümü resmi kapsayacak şekilde yenile ve dünyayı yeniden kur
      buildBg(bg, box => { if (!box) return; computeTransform(rooms, cams, markers, box); buildWorld(rooms, cams, markers, stairs); if (last.people) updateLive(last.people); fit(); });
    },
    updateLive(people) { if (last) last.people = people; updateLive(people); },
    setDark(d) { dark = !!d; P = dark ? PAL.dark : PAL.light; makeMats(); buildBase(); hud.classList.toggle('f3d-dark', dark); },
    resize,
    dispose() { stop(); ro.disconnect(); document.removeEventListener('visibilitychange', onVis); disposeGroup(gWorld); disposeGroup(gBg); disposeGroup(gLive); renderer.dispose(); renderer.domElement.remove(); hud.remove(); },
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
  const txt = await (await fetch(url, { credentials: 'same-origin' })).text();
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
    const toUser = (el, x, y) => { try { const m = el.getCTM(); if (!m) return [x, y]; pt.x = x; pt.y = y; const p = pt.matrixTransform(m); return [p.x, p.y]; } catch { return [x, y]; } };
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
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
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
  .f3d-leg i.g{background:#16a34a}.f3d-leg i.y{background:#f59e0b}.f3d-leg i.r{background:#dc2626}
  .f3d-floors{display:flex;gap:6px;flex-wrap:wrap;pointer-events:auto}
  .f3d-fl{border:1px solid rgba(255,255,255,.75);background:rgba(255,255,255,.66);backdrop-filter:blur(14px);border-radius:999px;padding:6px 12px;font-size:12px;font-weight:700;color:#3b4252;cursor:pointer}
  .f3d-fl.on{background:#7c6cf0;color:#fff;border-color:#7c6cf0}
  .f3d-dark .f3d-card,.f3d-dark .f3d-fl{background:rgba(18,24,40,.62);border-color:rgba(130,150,210,.3)}
  .f3d-dark .f3d-top,.f3d-dark .f3d-floor,.f3d-dark .f3d-nm b{color:#e8edf8}
  .f3d-dark .f3d-row{background:rgba(255,255,255,.06)}
  .f3d-dark .f3d-stat span,.f3d-dark .f3d-sub,.f3d-dark .f3d-leg,.f3d-dark .f3d-nm small,.f3d-dark .f3d-empty,.f3d-dark .f3d-fl{color:#aab4c8}
  `;
  document.head.appendChild(st);
}
