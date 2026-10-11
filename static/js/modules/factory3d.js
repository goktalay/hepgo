// HEPGO Fabrika — Canlı İzleme 3B sahnesi (Three.js, yerel kopya).
// vantra-facility-os (horizonx) esinli: gerçek cam duvarlar (MeshPhysical transmission),
// opak alt eşik + cam pencere, kalın zemin plakaları, ACESFilmic ışık + yumuşak gölge,
// canlı personel her zaman görünür kart (depthTest:false) + durum rengi halka + sütun, orbit kamera.
// 2B kat planını (oda poligonları) 3B'ye yükseltir; veri factory.js'teki uçlardan gelir.

const LIB = '/static/vendor/three/';
let _libs = null;
const loadLibs = () => (_libs ??= Promise.all(
  ['three.module.min.js', 'OrbitControls.js'].map(f => import(LIB + f))
).then(([T, O]) => ({ T, OrbitControls: O.OrbitControls })).catch(e => { _libs = null; throw e; }));

const WALL_H = 2.2, TH = 0.12, SILL_H = 0.5, SPAN = 26;
let _Tref = null;

const PAL = {
  light: { ground: 0xeef1f7, g1: 0xc6d0e4, g2: 0xd8e0ef, slab: 0xe3e8f1, deck: 0xdde5f1, wall: 0xeef1f8, sill: 0xd4dcea, steel: 0x9fb0c8, label: '#0b1322', labelBg: 'rgba(255,255,255,.9)' },
  dark: { ground: 0x0d1424, g1: 0x22324e, g2: 0x182438, slab: 0x172338, deck: 0x1d2b48, wall: 0x2a3446, sill: 0x1b2740, steel: 0x45506a, label: '#e7edf7', labelBg: 'rgba(15,22,38,.82)' },
};
const ageColor = at => { const ms = at ? Date.now() - new Date(at).getTime() : Infinity; return ms <= 3e5 ? 0x16a34a : ms <= 36e5 ? 0xf59e0b : 0xdc2626; };

export async function createFactory3D(mountEl, opts = {}) {
  const { T, OrbitControls } = await loadLibs();
  _Tref = T;
  const fileUrl = opts.fileUrl || (p => p);
  let dark = !!opts.dark, floorName = opts.floorName || '', palette = opts.palette || {};
  let P = dark ? PAL.dark : PAL.light;

  // ---------- glass HUD ----------
  ensureHudStyle();
  const hud = document.createElement('div'); hud.className = 'f3d-hud';
  hud.style.cssText = 'position:absolute;left:16px;top:16px;z-index:5;pointer-events:none';
  hud.innerHTML = `<div class="f3d-hud-card">
    <div class="f3d-hud-top"><span class="f3d-dot live"></span><b>Canlı İzleme · 3B</b></div>
    <div class="f3d-hud-floor"></div>
    <div class="f3d-hud-cnt"><span class="n">0</span> kişi şu an sahada</div>
    <div class="f3d-hud-leg"><span><i class="g"></i>çok yeni</span><span><i class="y"></i>1 saat içinde</span><span><i class="r"></i>daha eski</span></div>
  </div>`;
  mountEl.appendChild(hud); if (dark) hud.classList.add('f3d-dark');
  const hudFloor = hud.querySelector('.f3d-hud-floor'), hudCntEl = hud.querySelector('.f3d-hud-cnt .n');
  const setHud = (name, n) => { if (name != null) floorName = name; hudFloor.textContent = floorName || 'Tüm kat'; if (n != null) hudCntEl.textContent = n; };

  // ---------- renderer / sahne / kamera ----------
  const renderer = new T.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.outputColorSpace = 'outputColorSpace' in renderer ? T.SRGBColorSpace : renderer.outputColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.06;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.domElement.style.cssText = 'width:100%;height:100%;display:block;touch-action:none;cursor:grab';
  mountEl.appendChild(renderer.domElement);

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(40, 1, 0.3, 400);
  camera.position.set(SPAN * 0.5, SPAN * 0.78, SPAN * 1.0);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 6; controls.maxDistance = 95;

  // ---------- ışık ----------
  const hemi = new T.HemisphereLight(0xffffff, 0x8491a6, 0.9); scene.add(hemi);
  const key = new T.DirectionalLight(0xffffff, 1.35);
  key.position.set(16, 34, 18); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -30; key.shadow.camera.right = 30; key.shadow.camera.top = 30; key.shadow.camera.bottom = -30;
  key.shadow.camera.near = 1; key.shadow.camera.far = 110; key.shadow.bias = -0.0006; key.shadow.radius = 3;
  scene.add(key);
  const rim = new T.DirectionalLight(0x9db4ff, 0.5); rim.position.set(-20, 12, -18); scene.add(rim);

  const gWorld = new T.Group(); scene.add(gWorld);
  const gLive = new T.Group(); scene.add(gLive);
  let grid, ground, gBgMesh = null, M = {};

  const makeMats = () => {
    M.ground = new T.MeshStandardMaterial({ color: P.ground, roughness: 0.96, metalness: 0 });
    M.slab = new T.MeshStandardMaterial({ color: P.slab, roughness: 0.85, metalness: 0.08 });
    M.deck = new T.MeshStandardMaterial({ color: P.deck, roughness: 0.6, metalness: 0.12 });
    M.wall = new T.MeshStandardMaterial({ color: P.wall, roughness: 0.7, metalness: 0.06 });
    M.sill = new T.MeshStandardMaterial({ color: P.sill, roughness: 0.8, metalness: 0.05 });
    M.glass = new T.MeshPhysicalMaterial({ color: 0xa9cfdd, transmission: 0.9, thickness: 0.5, roughness: 0.14, metalness: 0, ior: 1.35, transparent: true, opacity: 0.4, side: T.DoubleSide });
    M.frame = new T.MeshStandardMaterial({ color: P.steel, roughness: 0.5, metalness: 0.4 });
    M.cam = new T.MeshStandardMaterial({ color: 0x2a3340, roughness: 0.45, metalness: 0.3 });
    M.cone = new T.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.08, side: T.DoubleSide, depthWrite: false });
    M.edge = new T.LineBasicMaterial({ color: P.steel, transparent: true, opacity: 0.55 });
  };

  const buildBase = () => {
    if (ground) { scene.remove(ground); ground.geometry.dispose(); }
    if (grid) scene.remove(grid);
    ground = new T.Mesh(new T.PlaneGeometry(260, 260), M.ground);
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.04; ground.receiveShadow = true; scene.add(ground);
    grid = new T.GridHelper(260, 130, P.g1, P.g2);
    grid.material.transparent = true; grid.material.opacity = dark ? 0.45 : 0.7; grid.position.y = -0.02; scene.add(grid);
  };

  // ---------- koordinat dönüşümü ----------
  let X = { cx: 0, cy: 0, s: 1 };
  const computeTransform = (rooms, cams, markers) => {
    const pts = [];
    (rooms || []).forEach(r => (r.points || []).forEach(p => pts.push(p)));
    (cams || []).forEach(c => (c.x != null) && pts.push([c.x, c.y]));
    (markers || []).forEach(m => (m.x != null) && pts.push([m.x, m.y]));
    if (!pts.length) { X = { cx: 0, cy: 0, s: 0.05 }; return; }
    let a = Infinity, b = -Infinity, c = Infinity, d = -Infinity;
    pts.forEach(([x, y]) => { if (x < a) a = x; if (x > b) b = x; if (y < c) c = y; if (y > d) d = y; });
    X = { cx: (a + b) / 2, cy: (c + d) / 2, s: SPAN / Math.max(b - a || 1, d - c || 1) };
  };
  const px = x => (x - X.cx) * X.s, pz = y => (y - X.cy) * X.s;

  const disposeGroup = g => { g.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => { m.map?.dispose?.(); m.dispose?.(); }); }); g.clear(); };

  // ---------- kat planı: zemin plakaları + cam duvarlar ----------
  const buildWorld = (rooms, cams, markers, stairs) => {
    disposeGroup(gWorld);
    (rooms || []).forEach(r => {
      const pts = (r.points || []).filter(p => p && p.length >= 2);
      if (pts.length < 3) return;
      const shape = new T.Shape();
      pts.forEach(([x, y], i) => { const sx = px(x), sz = pz(y); i ? shape.lineTo(sx, sz) : shape.moveTo(sx, sz); });
      shape.closePath();
      // kalın zemin plakası (extrude, hafif yükselti)
      const slabGeo = new T.ExtrudeGeometry(shape, { depth: 0.14, bevelEnabled: false });
      slabGeo.rotateX(Math.PI / 2);
      const col = r.color ? new T.Color(r.color).lerp(new T.Color(P.deck), 0.55) : null;
      const sm = col ? M.deck.clone() : M.deck; if (col) sm.color = col;
      const slab = new T.Mesh(slabGeo, sm); slab.position.y = 0.14; slab.receiveShadow = true; slab.castShadow = true; slab.userData.room = r; gWorld.add(slab);
      // duvarlar: her kenar → opak alt eşik + cam pencere + ince üst kiriş
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i], b = pts[(i + 1) % pts.length];
        const ax = px(a[0]), az = pz(a[1]), bx = px(b[0]), bz = pz(b[1]);
        const len = Math.hypot(bx - ax, bz - az); if (len < 0.05) continue;
        const mx = (ax + bx) / 2, mz = (az + bz) / 2, ry = -Math.atan2(bz - az, bx - ax);
        const sill = new T.Mesh(new T.BoxGeometry(len, SILL_H, TH), M.sill);
        sill.position.set(mx, SILL_H / 2 + 0.14, mz); sill.rotation.y = ry; sill.castShadow = true; sill.receiveShadow = true; gWorld.add(sill);
        const glassH = WALL_H - SILL_H - 0.14;
        const glass = new T.Mesh(new T.BoxGeometry(len, glassH, 0.05), M.glass);
        glass.position.set(mx, SILL_H + 0.14 + glassH / 2, mz); glass.rotation.y = ry; gWorld.add(glass);
        const top = new T.Mesh(new T.BoxGeometry(len, 0.14, TH), M.wall);
        top.position.set(mx, WALL_H + 0.07, mz); top.rotation.y = ry; top.castShadow = true; gWorld.add(top);
        // dikey cam çerçeveleri
        const n = Math.max(1, Math.round(len / 2.4));
        for (let k = 1; k < n; k++) {
          const t = k / n, fx = ax + (bx - ax) * t, fz = az + (bz - az) * t;
          const fr = new T.Mesh(new T.BoxGeometry(0.06, glassH, TH * 0.9), M.frame);
          fr.position.set(fx, SILL_H + 0.14 + glassH / 2, fz); fr.rotation.y = ry; gWorld.add(fr);
        }
      }
      if (r.name) { const c = centroid(pts); const lbl = makeTextSprite(r.name, P); lbl.position.set(px(c[0]), WALL_H + 0.7, pz(c[1])); gWorld.add(lbl); }
    });
    // kameralar (gövde + lens + görüş konisi)
    (cams || []).forEach(c => {
      if (c.x == null || c.y == null) return;
      const g = new T.Group(); g.position.set(px(c.x), WALL_H + 0.05, pz(c.y)); gWorld.add(g);
      const dir = (c.direction || 0) * Math.PI / 180; g.rotation.y = -dir;
      const body = new T.Mesh(new T.BoxGeometry(0.26, 0.26, 0.4), M.cam); body.rotation.x = 0.4; body.castShadow = true; g.add(body);
      const lens = new T.Mesh(new T.SphereGeometry(0.1, 14, 12), new T.MeshStandardMaterial({ color: 0x11161f, roughness: 0.15, metalness: 0.9 }));
      lens.position.set(0, -0.06, 0.24); g.add(lens);
      const cone = new T.Mesh(new T.ConeGeometry(1.7, 4, 24, 1, true), M.cone);
      cone.position.set(0, -0.3, 2); cone.rotation.x = -Math.PI / 2; g.add(cone);
    });
    (stairs || []).forEach(sObj => {
      if (sObj.x == null || sObj.y == null) return;
      const m = new T.Mesh(new T.BoxGeometry(1.4, 0.5, 1.4), M.slab);
      m.position.set(px(sObj.x), 0.25, pz(sObj.y)); m.castShadow = true; gWorld.add(m);
    });
    // altyapı işaretçileri (UPS / WiFi / priz / switch ...) — renkli pin + emoji rozet
    (markers || []).forEach(m => {
      if (m.x == null || m.y == null) return;
      const meta = palette[m.kind] || { color: '#64748b', icon: '•' };
      const col = new T.Color(meta.color);
      const pin = new T.Mesh(new T.CylinderGeometry(0.045, 0.045, 0.9, 6), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55 }));
      pin.position.set(px(m.x), 0.45, pz(m.y)); gWorld.add(pin);
      const head = new T.Mesh(new T.SphereGeometry(0.17, 16, 12), new T.MeshStandardMaterial({ color: col, roughness: 0.4, metalness: 0.2 }));
      head.position.set(px(m.x), 1.0, pz(m.y)); head.castShadow = true; gWorld.add(head);
      if (meta.icon) { const em = emojiSprite(meta.icon); em.position.set(px(m.x), 1.0, pz(m.y)); em.userData.bill = false; gWorld.add(em); }
    });
  };

  // ---------- arka plan kat planı resmi (zemin dokusu) ----------
  function buildBg(bg) {
    if (gBgMesh) { gWorld.remove(gBgMesh); gBgMesh.geometry.dispose(); gBgMesh.material.map?.dispose?.(); gBgMesh.material.dispose(); gBgMesh = null; }
    if (!bg || !bg.url) return;
    const img = new Image(); img.crossOrigin = 'anonymous';
    img.onload = () => {
      const nw = img.naturalWidth || 800, nh = img.naturalHeight || 600, sc = bg.scale || 1;
      const W = nw * sc * X.s, H = nh * sc * X.s;       // dünya birimi
      const tex = new T.Texture(img); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; tex.needsUpdate = true;
      const geo = new T.PlaneGeometry(W, H); geo.rotateX(-Math.PI / 2);
      const mat = new T.MeshBasicMaterial({ map: tex, transparent: true, opacity: bg.opacity != null ? Math.max(0.6, bg.opacity) : 0.92 });
      gBgMesh = new T.Mesh(geo, mat);
      gBgMesh.position.set(px((bg.x || 0) + nw * sc / 2), 0.04, pz((bg.y || 0) + nh * sc / 2));
      gWorld.add(gBgMesh);
    };
    img.onerror = () => {};
    img.src = bg.url;
  }

  // ---------- canlı personel (her zaman görünür kart + halka + sütun) ----------
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
      // zemin halkası + ışık sütunu
      const ring = new T.Mesh(new T.RingGeometry(0.42, 0.56, 40), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.75, side: T.DoubleSide }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(sx, 0.18, sz); gLive.add(ring);
      const stem = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 2.3, 8), new T.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.45 }));
      stem.position.set(sx, 1.3, sz); gLive.add(stem);
      // kart grubu (her zaman görünür: depthTest:false, billboard)
      const grp = new T.Group(); grp.position.set(sx, 2.95, sz); grp.userData.bill = true; gLive.add(grp);
      const back = new T.Mesh(new T.CircleGeometry(0.62, 40), new T.MeshBasicMaterial({ color: col, depthTest: false, toneMapped: false }));
      back.renderOrder = 10; grp.add(back);
      const face = new T.Mesh(new T.CircleGeometry(0.54, 40), new T.MeshBasicMaterial({ map: initialTex(p.subject_name, col), depthTest: false, toneMapped: false }));
      face.position.z = 0.01; face.renderOrder = 11; grp.add(face);
      if (p.crop) texLoader.load(fileUrl(p.crop, 128), tex => { if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace; face.material.map = roundTex(tex); face.material.needsUpdate = true; }, undefined, () => {});
      const tag = makeTextSprite((p.subject_name || '—').slice(0, 16), P, col.getHex()); tag.position.set(sx, 4.0, sz); gLive.add(tag);
    }));
    setHud(null, ppl.length);
  };

  // ---------- render döngüsü ----------
  let raf = 0, running = false;
  const tick = () => {
    if (!running) return;
    raf = requestAnimationFrame(tick);
    controls.update();
    gLive.children.forEach(o => { if (o.userData.bill) o.quaternion.copy(camera.quaternion); });
    renderer.render(scene, camera);
  };
  const start = () => { if (!running) { running = true; tick(); } };
  const stop = () => { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; };

  const resize = () => {
    const w = mountEl.clientWidth, h = mountEl.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(mountEl);
  const onVis = () => { if (document.hidden) stop(); else start(); };
  document.addEventListener('visibilitychange', onVis);

  const fit = () => { controls.target.set(0, WALL_H / 2, 0); camera.position.set(SPAN * 0.5, SPAN * 0.78, SPAN * 1.0); controls.update(); };

  makeMats(); buildBase(); resize(); fit(); start();

  return {
    build({ rooms, cams, markers, stairs, floorName, bg, palette: pal }) {
      if (pal) palette = pal;
      if (floorName != null) setHud(floorName, null);
      computeTransform(rooms, cams, markers); buildWorld(rooms, cams, markers, stairs); buildBg(bg); fit();
    },
    updateLive,
    setDark(d) { dark = !!d; P = dark ? PAL.dark : PAL.light; makeMats(); buildBase(); hud.classList.toggle('f3d-dark', dark); },
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
function roundTex(tex) {
  const T = _Tref, img = tex.image; if (!img) return tex;
  const S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
  ctx.save(); ctx.beginPath(); ctx.arc(S / 2, S / 2, S / 2, 0, Math.PI * 2); ctx.clip();
  ctx.drawImage(img, 0, 0, S, S); ctx.restore();
  const t = new T.CanvasTexture(cv); if ('colorSpace' in t) t.colorSpace = T.SRGBColorSpace; return t;
}
function initialTex(name, col) {
  const T = _Tref, S = 128, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
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
  const T = _Tref, S = 96, cv = document.createElement('canvas'); cv.width = cv.height = S;
  const ctx = cv.getContext('2d');
  ctx.font = '64px system-ui,"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(ch, S / 2, S / 2 + 4);
  const tex = new T.CanvasTexture(cv); if ('colorSpace' in tex) tex.colorSpace = T.SRGBColorSpace;
  const sp = new T.Sprite(new T.SpriteMaterial({ map: tex, transparent: true, depthTest: false, toneMapped: false }));
  sp.renderOrder = 9; sp.scale.set(0.62, 0.62, 1); return sp;
}

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
