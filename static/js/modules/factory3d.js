// HEPGO Fabrika — Canlı İzleme 3B sahnesi (Three.js, yerel kopya).
// 2B kat planını (oda poligonları = duvarlar) 3B'ye yükseltir: zemin plakaları + cam duvarlar,
// kameralar koni+görüş konisi, canlı personel yüz fotoğraflı dik kartlar (billboard) + durum rengi.
// vantra-facility-os esinli: orbit kamera, cam yüzeyler, yumuşak ışık, açık/koyu uyumlu.
// Veri factory.js'teki aynı uçlardan gelir; bu modül yalnız görselleştirir.

const LIB = '/static/vendor/three/';
let _libs = null;
const loadLibs = () => (_libs ??= Promise.all(
  ['three.module.min.js', 'OrbitControls.js'].map(f => import(LIB + f))
).then(([T, O]) => ({ T, OrbitControls: O.OrbitControls })).catch(e => { _libs = null; throw e; }));

const WALL_H = 2.3;          // duvar yüksekliği (birim)
const SPAN = 26;             // sahnenin hedef genişliği (birim)

// görülme yaşına göre renk (factory.js liveAgeColor ile aynı)
const ageColor = at => {
  const ms = at ? Date.now() - new Date(at).getTime() : Infinity;
  return ms <= 5 * 60000 ? 0x16a34a : ms <= 60 * 60000 ? 0xf59e0b : 0xdc2626;
};

export async function createFactory3D(mountEl, opts = {}) {
  const { T, OrbitControls } = await loadLibs();
  _Tref = T;
  const fileUrl = opts.fileUrl || (p => p);
  let dark = !!opts.dark;
  let floorName = opts.floorName || '';

  // ---------- cam (glass) HUD paneli (vantra tarzı) ----------
  ensureHudStyle();
  const hud = document.createElement('div'); hud.className = 'f3d-hud';
  hud.style.cssText = 'position:absolute;left:16px;top:16px;z-index:5;pointer-events:none';   // konum CSP-muaf (görsel detay class'tan)
  hud.innerHTML = `<div class="f3d-hud-card">
    <div class="f3d-hud-top"><span class="f3d-dot live"></span><b>Canlı İzleme · 3B</b></div>
    <div class="f3d-hud-floor"></div>
    <div class="f3d-hud-cnt"><span class="n">0</span> kişi şu an sahada</div>
    <div class="f3d-hud-leg"><span><i class="g"></i>çok yeni</span><span><i class="y"></i>1 saat içinde</span><span><i class="r"></i>daha eski</span></div>
  </div>`;
  mountEl.appendChild(hud); if (dark) hud.classList.add('f3d-dark');
  const hudFloor = hud.querySelector('.f3d-hud-floor');
  const hudCnt = hud.querySelector('.f3d-hud-cnt .n');
  const setHud = (name, n) => { if (name != null) floorName = name; hudFloor.textContent = floorName || 'Tüm kat'; hudCnt.textContent = n; };

  // ---------- renderer / sahne / kamera ----------
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
  if ('outputColorSpace' in renderer) renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.domElement.style.cssText = 'width:100%;height:100%;display:block;touch-action:none';
  mountEl.appendChild(renderer.domElement);

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(46, 1, 0.1, 400);
  camera.position.set(0, 26, 30);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.48; controls.minDistance = 6; controls.maxDistance = 90;
  controls.target.set(0, 0, 0);

  // ---------- ışık ----------
  const hemi = new T.HemisphereLight(0xffffff, 0x8794a8, 0.95); scene.add(hemi);
  const key = new T.DirectionalLight(0xffffff, 1.25); key.position.set(14, 26, 12);
  key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.near = 1; key.shadow.camera.far = 120;
  key.shadow.camera.left = -40; key.shadow.camera.right = 40; key.shadow.camera.top = 40; key.shadow.camera.bottom = -40;
  scene.add(key);
  scene.add(new T.DirectionalLight(0x9db4ff, 0.4).translateX(-18).translateY(10).translateZ(-14));

  // ---------- kalıcı gruplar ----------
  const gWorld = new T.Group(); scene.add(gWorld);        // kat planı (statik) — tek seferde kurulur
  const gLive = new T.Group(); scene.add(gLive);          // canlı personel — her güncellemede yenilenir
  let grid, ground;

  // ---------- koordinat dönüşümü (plan → sahne) ----------
  let X = { cx: 0, cy: 0, s: 1 };
  const computeTransform = (rooms, cams, markers) => {
    const pts = [];
    (rooms || []).forEach(r => (r.points || []).forEach(p => pts.push(p)));
    (cams || []).forEach(c => pts.push([c.x, c.y]));
    (markers || []).forEach(m => pts.push([m.x, m.y]));
    if (!pts.length) { X = { cx: 0, cy: 0, s: 0.05 }; return; }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    pts.forEach(([x, y]) => { if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; });
    const w = Math.max(1, maxX - minX), h = Math.max(1, maxY - minY);
    X = { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, s: SPAN / Math.max(w, h) };
  };
  const px = x => (x - X.cx) * X.s;           // plan x → sahne X
  const pz = y => (y - X.cy) * X.s;           // plan y → sahne Z

  const mats = {};
  const makeMats = () => {
    mats.ground = new T.MeshStandardMaterial({ color: dark ? 0x0e1626 : 0xeef1f7, roughness: 0.95, metalness: 0 });
    mats.floor = new T.MeshStandardMaterial({ color: dark ? 0x1b2740 : 0xdfe6f2, roughness: 0.8, metalness: 0.05, transparent: true, opacity: 0.55 });
    mats.wall = new T.MeshStandardMaterial({ color: dark ? 0x3b82f6 : 0x2f6fed, roughness: 0.3, metalness: 0.1, transparent: true, opacity: 0.22, side: T.DoubleSide });
    mats.wallEdge = new T.LineBasicMaterial({ color: dark ? 0x7aa2ff : 0x2f6fed, transparent: true, opacity: 0.8 });
    mats.cam = new T.MeshStandardMaterial({ color: 0x334155, roughness: 0.4, metalness: 0.3 });
    mats.cone = new T.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.14, side: T.DoubleSide, depthWrite: false });
  };

  const disposeGroup = g => { g.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.map?.dispose?.() || m.dispose?.()); } }); g.clear(); };

  // ---------- zemin + ızgara ----------
  const buildBase = () => {
    if (ground) { scene.remove(ground); ground.geometry.dispose(); }
    if (grid) scene.remove(grid);
    ground = new T.Mesh(new T.PlaneGeometry(240, 240), mats.ground);
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.02; ground.receiveShadow = true; scene.add(ground);
    grid = new T.GridHelper(240, 120, dark ? 0x23324e : 0xc6d0e4, dark ? 0x1a2740 : 0xd8e0ef);
    grid.material.transparent = true; grid.material.opacity = dark ? 0.5 : 0.7; scene.add(grid);
  };

  // ---------- kat planı: oda zeminleri + cam duvarlar ----------
  const buildWorld = (rooms, cams, markers, stairs) => {
    disposeGroup(gWorld);
    (rooms || []).forEach(r => {
      const pts = (r.points || []).filter(p => p && p.length >= 2);
      if (pts.length < 3) return;
      const shape = new T.Shape();
      pts.forEach(([x, y], i) => { const sx = px(x), sz = pz(y); i ? shape.lineTo(sx, sz) : shape.moveTo(sx, sz); });
      shape.closePath();
      // zemin plakası (yatay)
      const floorGeo = new T.ShapeGeometry(shape); floorGeo.rotateX(Math.PI / 2);
      const col = r.color ? new T.Color(r.color) : null;
      const fm = col ? mats.floor.clone() : mats.floor; if (col) fm.color = col.lerp(new T.Color(dark ? 0x1b2740 : 0xdfe6f2), 0.45);
      const floor = new T.Mesh(floorGeo, fm); floor.position.y = 0.01; floor.receiveShadow = true; gWorld.add(floor);
      // duvarlar: her kenar için dikey cam yüzey + üst kenar çizgisi
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i], b = pts[(i + 1) % pts.length];
        const ax = px(a[0]), az = pz(a[1]), bx = px(b[0]), bz = pz(b[1]);
        const len = Math.hypot(bx - ax, bz - az); if (len < 0.01) continue;
        const wall = new T.Mesh(new T.PlaneGeometry(len, WALL_H), mats.wall);
        wall.position.set((ax + bx) / 2, WALL_H / 2, (az + bz) / 2);
        wall.rotation.y = -Math.atan2(bz - az, bx - ax);
        wall.castShadow = true; gWorld.add(wall);
      }
      // oda kontürü üst kenar (parlak çizgi, duvar hissi)
      const edgePts = pts.map(([x, y]) => new T.Vector3(px(x), WALL_H, pz(y)));
      edgePts.push(edgePts[0].clone());
      gWorld.add(new T.Line(new T.BufferGeometry().setFromPoints(edgePts), mats.wallEdge));
      // taban kontür
      const basePts = pts.map(([x, y]) => new T.Vector3(px(x), 0.02, pz(y))); basePts.push(basePts[0].clone());
      gWorld.add(new T.Line(new T.BufferGeometry().setFromPoints(basePts), mats.wallEdge));
      // oda adı etiketi (3B sprite)
      if (r.name) { const c = centroid(pts); const lbl = makeTextSprite(r.name, dark); lbl.position.set(px(c[0]), WALL_H + 0.6, pz(c[1])); gWorld.add(lbl); }
    });
    // kameralar
    (cams || []).forEach(c => {
      if (c.x == null || c.y == null) return;
      const body = new T.Mesh(new T.ConeGeometry(0.28, 0.7, 4), mats.cam);
      body.position.set(px(c.x), WALL_H + 0.1, pz(c.y)); body.rotation.x = Math.PI / 2;
      body.castShadow = true; gWorld.add(body);
      const dir = (c.direction || 0) * Math.PI / 180;
      const cone = new T.Mesh(new T.ConeGeometry(2.4, 5, 24, 1, true), mats.cone);
      cone.position.set(px(c.x) + Math.cos(dir) * 2.4, WALL_H - 0.3, pz(c.y) + Math.sin(dir) * 2.4);
      cone.rotation.z = Math.PI / 2; cone.rotation.y = -dir; gWorld.add(cone);
    });
    // merdivenler (basit blok)
    (stairs || []).forEach(sObj => {
      if (sObj.x == null || sObj.y == null) return;
      const m = new T.Mesh(new T.BoxGeometry(1.4, 0.5, 1.4), new T.MeshStandardMaterial({ color: 0x94a3b8, roughness: 0.9 }));
      m.position.set(px(sObj.x), 0.25, pz(sObj.y)); m.castShadow = true; gWorld.add(m);
    });
  };

  // ---------- canlı personel ----------
  const texLoader = new T.TextureLoader();
  const updateLive = (people) => {
    disposeGroup(gLive);
    const ppl = (people || []).filter(p => p.x != null && p.y != null);
    // aynı noktadakileri hafif daire içine yay
    const spots = new Map();
    ppl.forEach(p => { const k = `${Math.round(p.x)},${Math.round(p.y)}`; if (!spots.has(k)) spots.set(k, []); spots.get(k).push(p); });
    spots.forEach(list => list.forEach((p, i) => {
      const n = list.length, off = n > 1 ? 0.9 : 0, ang = (i / n) * Math.PI * 2;
      const sx = px(p.x) + Math.cos(ang) * off, sz = pz(p.y) + Math.sin(ang) * off;
      const col = ageColor(p.at);
      // durum tabanı (disk + ışık sütunu)
      const disk = new T.Mesh(new T.CircleGeometry(0.6, 24), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.85 }));
      disk.rotation.x = -Math.PI / 2; disk.position.set(sx, 0.05, sz); gLive.add(disk);
      const beam = new T.Mesh(new T.CylinderGeometry(0.1, 0.1, 2.4, 8), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.35 }));
      beam.position.set(sx, 1.2, sz); gLive.add(beam);
      // yüz kartı (billboard sprite)
      const makeFace = (map) => {
        const mat = new T.SpriteMaterial({ map, transparent: true });
        const sp = new T.Sprite(mat); sp.scale.set(1.5, 1.5, 1); sp.position.set(sx, 2.7, sz); sp.userData.bill = true; gLive.add(sp);
        // renkli halka (durum)
        const ring = new T.Mesh(new T.RingGeometry(0.78, 0.92, 32), new T.MeshBasicMaterial({ color: col, side: T.DoubleSide }));
        ring.position.set(sx, 2.7, sz); ring.userData.bill = true; gLive.add(ring);
      };
      if (p.crop) {
        texLoader.load(fileUrl(p.crop, 128), tex => { if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; makeFace(roundTex(tex, T)); }, undefined, () => makeFace(initialTex(p.subject_name, col, T)));
      } else makeFace(initialTex(p.subject_name, col, T));
      // isim etiketi
      const tag = makeTextSprite((p.subject_name || '—').slice(0, 16), dark, col);
      tag.position.set(sx, 3.8, sz); gLive.add(tag);
    }));
    setHud(null, ppl.length);
  };

  // ---------- render döngüsü (görünür değilken durur) ----------
  let raf = 0, running = false, visible = true;
  const tick = () => {
    if (!running) return;
    raf = requestAnimationFrame(tick);
    controls.update();
    gLive.children.forEach(o => { if (o.userData.bill) o.quaternion.copy(camera.quaternion); });
    renderer.render(scene, camera);
  };
  const start = () => { if (!running && visible) { running = true; tick(); } };
  const stop = () => { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; };

  const resize = () => {
    const w = mountEl.clientWidth || 800, h = mountEl.clientHeight || 500;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(mountEl);
  const onVis = () => { if (document.hidden) stop(); else start(); };
  document.addEventListener('visibilitychange', onVis);

  // ---------- fit kamera ----------
  const fit = () => { controls.target.set(0, WALL_H / 2, 0); camera.position.set(SPAN * 0.5, SPAN * 0.9, SPAN * 1.05); controls.update(); };

  makeMats(); buildBase(); resize(); fit(); start();

  return {
    setFloor(_data) { /* rezerv */ },
    build({ rooms, cams, markers, stairs, floorName }) {
      if (floorName != null) setHud(floorName, hudCnt.textContent || 0);
      computeTransform(rooms, cams, markers); buildWorld(rooms, cams, markers, stairs); fit();
    },
    updateLive,
    setDark(d) { dark = !!d; makeMats(); buildBase(); hud.classList.toggle('f3d-dark', dark); },
    resize,
    dispose() {
      stop(); ro.disconnect(); document.removeEventListener('visibilitychange', onVis);
      disposeGroup(gWorld); disposeGroup(gLive);
      renderer.dispose(); renderer.domElement.remove(); hud.remove();
    },
  };
}

// ---------- yardımcılar ----------
function centroid(pts) { let x = 0, y = 0; pts.forEach(p => { x += p[0]; y += p[1]; }); return [x / pts.length, y / pts.length]; }

function roundTex(tex, T) {
  // kare foto → yuvarlak maskeli texture
  const img = tex.image; if (!img) return tex;
  const S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
  ctx.beginPath(); ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2); ctx.closePath(); ctx.clip();
  ctx.drawImage(img, 0, 0, S, S);
  const t = new T.CanvasTexture(cv); if ('colorSpace' in t) t.colorSpace = T.SRGBColorSpace; return t;
}
function initialTex(name, col, T) {
  const S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
  ctx.beginPath(); ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2); ctx.fillStyle = '#' + col.toString(16).padStart(6, '0'); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.font = 'bold 64px system-ui,sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText((name || '?').slice(0, 1).toLocaleUpperCase('tr'), S / 2, S / 2 + 4);
  const t = new T.CanvasTexture(cv); if ('colorSpace' in t) t.colorSpace = T.SRGBColorSpace; return t;
}
function makeTextSprite(text, dark, accent) {
  const pad = 16, fs = 42, cv = document.createElement('canvas'), ctx = cv.getContext('2d');
  ctx.font = `600 ${fs}px system-ui,sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2, hh = fs + pad;
  cv.width = w; cv.height = hh; ctx.font = `600 ${fs}px system-ui,sans-serif`;
  ctx.fillStyle = dark ? 'rgba(15,22,38,.82)' : 'rgba(255,255,255,.9)';
  roundRect(ctx, 0, 0, w, hh, 12); ctx.fill();
  if (accent != null) { ctx.strokeStyle = '#' + accent.toString(16).padStart(6, '0'); ctx.lineWidth = 3; roundRect(ctx, 1.5, 1.5, w - 3, hh - 3, 11); ctx.stroke(); }
  ctx.fillStyle = dark ? '#e7edf7' : '#0b1322'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, w / 2, hh / 2 + 2);
  return buildSprite(cv);
}
// sprite'ı modülün three örneğiyle kur (createFactory3D içinde _Tref = T atanır)
let _Tref = null;
function buildSprite(cv) {
  const T = _Tref; if (!T) return new Object3DStub();
  const tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace;
  const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  sp.scale.set(cv.width / cv.height * 0.9, 0.9, 1); sp.userData.bill = false; return sp;
}
function Object3DStub() { return { position: { set() {} }, scale: { set() {} }, userData: {} }; }
function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

function ensureHudStyle() {
  if (document.getElementById('f3d-hud-style')) return;
  const st = document.createElement('style'); st.id = 'f3d-hud-style';
  st.textContent = `
  .f3d-hud{position:absolute;left:16px;top:16px;z-index:5;pointer-events:none}
  .f3d-hud-card{background:rgba(255,255,255,.52);backdrop-filter:blur(16px) saturate(1.4);-webkit-backdrop-filter:blur(16px) saturate(1.4);border:1px solid rgba(255,255,255,.6);border-radius:16px;padding:14px 18px;box-shadow:0 10px 36px rgba(16,24,48,.14);min-width:196px;font-family:system-ui,-apple-system,sans-serif}
  .f3d-hud-top{display:flex;align-items:center;gap:8px;font-size:13px;color:#0b1322}
  .f3d-hud-top b{font-weight:700}
  .f3d-dot.live{width:8px;height:8px;border-radius:50%;background:#16a34a;animation:f3dpulse 1.8s infinite}
  @keyframes f3dpulse{0%{box-shadow:0 0 0 0 rgba(22,163,74,.5)}70%{box-shadow:0 0 0 7px rgba(22,163,74,0)}100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}
  .f3d-hud-floor{margin-top:10px;font-size:19px;font-weight:800;color:#0b1322;letter-spacing:-.02em}
  .f3d-hud-cnt{margin-top:2px;font-size:12.5px;color:#5b6170}
  .f3d-hud-cnt .n{font-weight:800;color:#2f6fed;font-size:15px}
  .f3d-hud-leg{margin-top:11px;display:flex;flex-direction:column;gap:3px;font-size:11px;color:#5b6170}
  .f3d-hud-leg span{display:flex;align-items:center;gap:6px}
  .f3d-hud-leg i{width:9px;height:9px;border-radius:50%;display:inline-block}
  .f3d-hud-leg i.g{background:#16a34a}.f3d-hud-leg i.y{background:#f59e0b}.f3d-hud-leg i.r{background:#dc2626}
  .f3d-dark .f3d-hud-card{background:rgba(15,22,38,.55);border-color:rgba(120,150,210,.35)}
  .f3d-dark .f3d-hud-top,.f3d-dark .f3d-hud-floor{color:#e7edf7}
  .f3d-dark .f3d-hud-cnt,.f3d-dark .f3d-hud-leg{color:#9aa6bd}
  `;
  document.head.appendChild(st);
}
