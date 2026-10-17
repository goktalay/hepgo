// Uçuş Simülatörü — 3B dünya (three.js r170, yerel kopya static/vendor/three). Sözleşme: docs/ucus-simulatoru.md §5.
// • Koordinat: ENU, merkez referanslı, Z YUKARI (camera.up = +Z). x = doğu, y = kuzey, z = alt_rel (pist seviyesi 0).
// • Arazi: tohumlu 2B simplex gürültü (kendi uygulamamız, bağımlılık yok), 3 oktav; merkez çevresinde 300 m düzleştirme; su seviyesi
//   `water` oranına göre; renkler yüksekliğe göre (kum → çim → kaya → kar). 256×256 ızgara, LOD yok.
// • Nesneler: ağaçlar (InstancedMesh ≤ 20.000, su/pist/bina üzerinde değil), binalar (kutular, 6–40 m), pist (asfalt + çizgiler,
//   runway_heading), gökyüzü/ışık (day/dusk/night; gece pist ve bina ışıkları), sis.
// • Dron: sabit kanat/VTOL gövdesi (airframe) 'caymaz' → static/models/caymaz-sim.glb (CAYMAZ V3 STEP'inden; yüklenemezse delta) ya da
//   'delta' → prosedürel delta uçan kanat; multikopter (60 cm) / hexa (90 cm) / helikopter (1.5 m) gerçekçi prosedürel geometri.
//   Pervaneler gaz ile döner (yüksek devirde bulanık disk), elevonlar RC ile, seyir ışıkları (sol kırmızı / sağ yeşil / kuyruk beyaz strobe),
//   yalnız dron gölge düşürür. Yönelim: ArduPilot roll/pitch/yaw (NED) → ENU quaternion (Euler 'ZXY': pitch, roll, −yaw).
// • Kameralar (1–4): Takip (OrbitControls, hedef dron) · Dron kamerası (FPV, burun; gimbal ↑↓) · Serbest (WASD/QE + fare sürükle) · Yer.
// • Telemetri enterpolasyonu (20 Hz → kare): hız ile öngörü + üstel yumuşatma. Çarpışma: z < h(x,y)+0.3 ya da bina kutusu, hız > 1 m/s.
// Dışa: createFlightSim3D(mountEl, world, opts) → { setTelemetry, setCamera, getCamera, setGimbal, resetCamera, terrainHeight,
//        toLocal, setWorld, setType(type, airframe), clearCollision, resize, dispose }. opts: { type, airframe, preview, origin, … }

const LIB = '/static/vendor/three/';
let _libs = null;
const loadLibs = () => (_libs ??= Promise.all(
  ['three.module.min.js', 'OrbitControls.js', 'GLTFLoader.js'].map(f => import(LIB + f)),
).then(([T, O, G]) => ({ T, OrbitControls: O.OrbitControls, GLTFLoader: G.GLTFLoader })).catch(e => { _libs = null; throw e; }));

export const CAMERA_MODES = [['follow', 'Takip'], ['fpv', 'Dron kamerası'], ['free', 'Serbest'], ['ground', 'Yer']];
export const WORLD_DEFAULTS = {
  seed: 12345, size_m: 4000, tree_density: 0.3, mountain_height: 300, mountain_count: 4, building_count: 40,
  runway: true, runway_heading: 0, water: 0.1, time: 'day', wind_ms: 3, wind_dir: 270, fog: 0.2,
};
const FLAT_R = 300, FLAT_R2 = 600;        // merkez çevresi düzleştirme (pist / kalkış alanı)
const RUNWAY_L = 1200, RUNWAY_W = 40;     // pist boyutları (m)
const GRID = 256;                         // arazi ızgarası
const MAX_TREES = 20000;
const MODEL_SCALE = 2.5;                  // dron modelleri (görünürlük için büyütülür; kamera mesafeleri yarıçapa bağlı)
const DEG = Math.PI / 180;

// ---------- Tohumlu rastgele sayı (mulberry32) ----------
function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ---------- 2B simplex gürültü (Gustavson), tohumlu permütasyon; çıktı ≈ [-1, 1] ----------
function simplex2D(seed) {
  const G = [[1, 1], [-1, 1], [1, -1], [-1, -1], [1, 0], [-1, 0], [0, 1], [0, -1]];
  const r = rng(seed), p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) { const j = Math.floor(r() * (i + 1)); const t = p[i]; p[i] = p[j]; p[j] = t; }
  const perm = new Uint8Array(512);
  for (let i = 0; i < 512; i++) perm[i] = p[i & 255];
  const F2 = 0.5 * (Math.sqrt(3) - 1), G2 = (3 - Math.sqrt(3)) / 6;
  return (xin, yin) => {
    const s = (xin + yin) * F2, i = Math.floor(xin + s), j = Math.floor(yin + s), t = (i + j) * G2;
    const x0 = xin - (i - t), y0 = yin - (j - t);
    const i1 = x0 > y0 ? 1 : 0, j1 = x0 > y0 ? 0 : 1;
    const x1 = x0 - i1 + G2, y1 = y0 - j1 + G2, x2 = x0 - 1 + 2 * G2, y2 = y0 - 1 + 2 * G2;
    const ii = i & 255, jj = j & 255;
    let n = 0;
    let tt = 0.5 - x0 * x0 - y0 * y0;
    if (tt > 0) { const g = G[perm[ii + perm[jj]] & 7]; tt *= tt; n += tt * tt * (g[0] * x0 + g[1] * y0); }
    tt = 0.5 - x1 * x1 - y1 * y1;
    if (tt > 0) { const g = G[perm[ii + i1 + perm[jj + j1]] & 7]; tt *= tt; n += tt * tt * (g[0] * x1 + g[1] * y1); }
    tt = 0.5 - x2 * x2 - y2 * y2;
    if (tt > 0) { const g = G[perm[ii + 1 + perm[jj + 1]] & 7]; tt *= tt; n += tt * tt * (g[0] * x2 + g[1] * y2); }
    return 70 * n;
  };
}

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const num = (v, d) => (v == null || Number.isNaN(Number(v)) ? d : Number(v));

// Dünya tanımından deterministik arazi fonksiyonu: h(x, y) metre (pist seviyesi 0), su seviyesi ve yardımcılar
export function makeTerrain(world) {
  const W = { ...WORLD_DEFAULTS, ...(world || {}) };
  const size = clamp(num(W.size_m, 4000), 1000, 20000);
  const H = clamp(num(W.mountain_height, 300), 0, 3000);
  const cnt = clamp(num(W.mountain_count, 4), 1, 12);
  const noise = simplex2D(num(W.seed, 12345));
  const f = cnt / size;   // yaklaşık `mountain_count` tepe genişlik boyunca
  const fbm = (x, y) => (noise(x * f, y * f) + 0.5 * noise(x * f * 2 + 31.7, y * f * 2 - 17.3) + 0.25 * noise(x * f * 4 - 5.1, y * f * 4 + 9.9)) / 1.75;
  const raw = (x, y) => { const n = clamp((fbm(x, y) + 1) / 2, 0, 1); return H * Math.pow(n, 1.7) - H * 0.12; };
  const h0 = raw(0, 0);
  const height = (x, y) => { const r = Math.hypot(x, y); return (raw(x, y) - h0) * smooth(FLAT_R, FLAT_R2, r); };
  // Su seviyesi: ızgara yüksekliklerinin `water` oranı altta kalacak şekilde (pist seviyesinin en az 1.5 m altında)
  let waterZ = -Infinity;
  const water = clamp(num(W.water, 0), 0, 0.9);
  if (water > 0 && H > 0) {
    const hs = [];
    for (let j = 0; j < 64; j++) for (let i = 0; i < 64; i++) hs.push(height((i / 63 - 0.5) * size, (j / 63 - 0.5) * size));
    hs.sort((a, b) => a - b);
    waterZ = Math.min(hs[Math.floor(water * (hs.length - 1))], -1.5);
  }
  return { W, size, H, height, waterZ, rand: rng(num(W.seed, 12345) ^ 0x9E3779B9) };
}

// Pist dikdörtgeni içinde mi (yerel x, y; heading saat yönü kuzeyden)
function inRunway(x, y, headingDeg, margin = 0) {
  const a = -headingDeg * DEG, c = Math.cos(a), s = Math.sin(a);
  const u = c * x + s * y, v = -s * x + c * y;   // u: pist boyu ekseni (+y döndürülmüş), v: pist genişliği
  return Math.abs(v) <= RUNWAY_L / 2 + margin && Math.abs(u) <= RUNWAY_W / 2 + margin;
}

// ArduPilot roll/pitch/yaw (rad, NED) → ENU gövde quaternionu. Gövde: burun +Y, sağ kanat +X, üst +Z.
// yaw 0 = kuzey (+Y), doğu = +X; saat yönü yaw → +Z etrafında negatif dönüş. Sıra: yaw → pitch (gövde X) → roll (gövde Y).
function attitudeQuat(T, roll, pitch, yaw, out) {
  const e = new T.Euler(pitch || 0, roll || 0, -(yaw || 0), 'ZXY');
  return (out || new T.Quaternion()).setFromEuler(e);
}

export async function createFlightSim3D(mountEl, world, opts = {}) {
  const { T, OrbitControls, GLTFLoader } = await loadLibs();
  const preview = !!opts.preview;
  let onCollision = opts.onCollision || null;
  const origin = { lat: num(opts.origin?.lat, 0), lon: num(opts.origin?.lon, 0) };
  const toLocal = (lat, lon) => ({ x: (lon - origin.lon) * 111320 * Math.cos(origin.lat * DEG), y: (lat - origin.lat) * 110574 });

  // ---------- çizici / sahne / kamera ----------
  const renderer = new T.WebGLRenderer({ antialias: !preview, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, preview ? 1 : 2));
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.shadowMap.enabled = !preview;   // yalnız dron gölge düşürür (castShadow); arazi/pist alır
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.className = 'fs3d-canvas';
  canvas.style.cssText = 'display:block;width:100%;height:100%;outline:none;touch-action:none';
  canvas.tabIndex = -1;
  mountEl.appendChild(canvas);
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(60, 1, 0.5, 60000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.12; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 3; controls.maxDistance = 20000;

  // ---------- dünya ----------
  let terrain = null, gWorld = new T.Group(), buildingsAABB = [], W = { ...WORLD_DEFAULTS };
  scene.add(gWorld);
  let lights = { sun: new T.DirectionalLight(0xffffff, 2), hemi: new T.HemisphereLight(0xbfd8ff, 0x3a4a2a, 0.9), amb: new T.AmbientLight(0xffffff, 0.15) };
  scene.add(lights.sun, lights.hemi, lights.amb, lights.sun.target);
  // Gölge kamerası dronu izler (küçük, keskin): her karede sun.position = dron + güneş yönü × 120 m, target = dron
  const sunDir = new T.Vector3(0.6, -0.5, 0.9).normalize();
  if (!preview) {
    lights.sun.castShadow = true;
    const sc = lights.sun.shadow.camera;
    sc.left = sc.bottom = -25; sc.right = sc.top = 25; sc.near = 20; sc.far = 400;
    lights.sun.shadow.mapSize.set(1024, 1024);
    lights.sun.shadow.bias = -0.0008;
  }

  const disposeGroup = g => {
    g.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      const ms = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      ms.forEach(m => { for (const k of ['map', 'emissiveMap']) m[k]?.dispose?.(); m.dispose?.(); });
    });
    while (g.children.length) g.remove(g.children[0]);
  };

  function buildWorld(world) {
    disposeGroup(gWorld);
    buildingsAABB = [];
    terrain = makeTerrain(world);
    W = terrain.W;
    const { size, H, height, waterZ, rand } = terrain;
    const night = W.time === 'night', dusk = W.time === 'dusk';

    // --- gökyüzü, ışık, sis ---
    const sky = night ? 0x0a1328 : dusk ? 0xe0956a : 0x8fbdea;
    renderer.setClearColor(sky, 1);
    scene.background = new T.Color(sky);
    lights.sun.color.set(night ? 0x6f7fb0 : dusk ? 0xffb070 : 0xfff2dc);
    lights.sun.intensity = night ? 0.45 : dusk ? 1.3 : 2.4;
    sunDir.set(night ? -0.3 : dusk ? -0.9 : 0.6, dusk ? -0.2 : -0.5, night ? 0.5 : dusk ? 0.25 : 0.9).normalize();
    lights.sun.position.copy(sunDir).multiplyScalar(preview ? size : 120);
    lights.sun.shadow.intensity = night ? 0.35 : dusk ? 0.7 : 1;
    lights.hemi.color.set(night ? 0x1b2a55 : dusk ? 0xf0b088 : 0xbfd8ff);
    lights.hemi.groundColor.set(night ? 0x060a12 : 0x3a4a2a);
    lights.hemi.intensity = night ? 0.5 : dusk ? 0.8 : 0.9;
    lights.amb.intensity = night ? 0.3 : 0.15;
    const fog = clamp(num(W.fog, 0), 0, 1);
    scene.fog = fog > 0 ? new T.Fog(sky, size * 0.12, size * (1.6 - 1.25 * fog)) : null;

    // --- arazi (256×256 ızgara, yükseklik renkleri) ---
    const geo = new T.PlaneGeometry(size, size, GRID - 1, GRID - 1);
    const pos = geo.attributes.position, col = new Float32Array(pos.count * 3);
    const c = new T.Color(), sand = new T.Color(0xc2b280), grass1 = new T.Color(0x4f8a3a), grass2 = new T.Color(0x7a9a46),
      rock = new T.Color(0x7d7569), snow = new T.Color(0xeef2f5);
    const relH = Math.max(H, 1);
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = height(x, y);
      pos.setZ(i, z);
      if (z < waterZ + 1.5) c.copy(sand);
      else if (z < relH * 0.35) c.lerpColors(grass1, grass2, clamp(z / (relH * 0.35), 0, 1));
      else if (z < relH * 0.7) c.lerpColors(grass2, rock, (z - relH * 0.35) / (relH * 0.35));
      else c.lerpColors(rock, snow, clamp((z - relH * 0.7) / (relH * 0.25), 0, 1));
      if (night) c.multiplyScalar(0.55);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    geo.setAttribute('color', new T.BufferAttribute(col, 3));
    geo.computeVertexNormals();
    const ground = new T.Mesh(geo, new T.MeshLambertMaterial({ vertexColors: true }));
    ground.name = 'arazi';
    ground.receiveShadow = true;
    gWorld.add(ground);

    // --- su ---
    if (waterZ > -Infinity) {
      const water = new T.Mesh(new T.PlaneGeometry(size * 1.02, size * 1.02), new T.MeshPhongMaterial({
        color: night ? 0x0b1d3a : dusk ? 0x3b5f8a : 0x2f6fa8, transparent: true, opacity: 0.86, shininess: 90, specular: 0x88aadd }));
      water.position.z = waterZ;
      gWorld.add(water);
    }

    // --- pist (asfalt, orta çizgiler, eşik çizgileri; heading) ---
    const hdg = num(W.runway_heading, 0);
    if (W.runway !== false) {
      const rw = new T.Group();
      rw.rotation.z = -hdg * DEG;
      rw.position.z = 0.05;
      const asphalt = new T.Mesh(new T.PlaneGeometry(RUNWAY_W, RUNWAY_L), new T.MeshLambertMaterial({ color: night ? 0x1c1f24 : 0x3a3d42 }));
      asphalt.receiveShadow = true;
      rw.add(asphalt);
      const white = new T.MeshBasicMaterial({ color: night ? 0x9aa3ad : 0xf5f5f5 });
      for (let y = -RUNWAY_L / 2 + 60; y < RUNWAY_L / 2 - 60; y += 60) { const d = new T.Mesh(new T.PlaneGeometry(1.2, 30), white); d.position.set(0, y, 0.02); rw.add(d); }
      for (const sgn of [-1, 1]) for (let k = -3; k <= 3; k++) { if (!k) continue; const s = new T.Mesh(new T.PlaneGeometry(2.4, 30), white); s.position.set(k * 4.8, sgn * (RUNWAY_L / 2 - 22), 0.02); rw.add(s); }
      // Pist kenar çizgileri
      for (const sgn of [-1, 1]) { const e = new T.Mesh(new T.PlaneGeometry(0.9, RUNWAY_L), white); e.position.set(sgn * (RUNWAY_W / 2 - 0.6), 0, 0.02); rw.add(e); }
      // Gece: pist kenar ışıkları (nokta bulutu) — beyaz kenar, yeşil/kırmızı eşik
      if (night || dusk) {
        const pts = [], cols = [];
        for (let y = -RUNWAY_L / 2; y <= RUNWAY_L / 2; y += 60) for (const sgn of [-1, 1]) { pts.push(sgn * (RUNWAY_W / 2 + 1.5), y, 0.6); cols.push(1, 0.95, 0.8); }
        for (let x = -RUNWAY_W / 2; x <= RUNWAY_W / 2; x += 5) { pts.push(x, -RUNWAY_L / 2 - 2, 0.6, x, RUNWAY_L / 2 + 2, 0.6); cols.push(0.2, 1, 0.3, 1, 0.25, 0.2); }
        const pg = new T.BufferGeometry();
        pg.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
        pg.setAttribute('color', new T.Float32BufferAttribute(cols, 3));
        rw.add(new T.Points(pg, new T.PointsMaterial({ size: 0.8, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: 0.95 })));
      }
      gWorld.add(rw);
    }

    // --- binalar (kutular, 6–40 m; pistten uzak, su dışında) ---
    const nb = clamp(Math.round(num(W.building_count, 0)), 0, 400);
    if (nb > 0) {
      const bgeo = new T.BoxGeometry(1, 1, 1); bgeo.translate(0, 0, 0.5);
      const bmat = new T.MeshLambertMaterial({ color: 0xffffff, emissive: night ? 0x3a3418 : 0x000000 });
      const inst = new T.InstancedMesh(bgeo, bmat, nb);
      const m4 = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), p = new T.Vector3(), bc = new T.Color();
      let placed = 0;
      for (let tries = 0; placed < nb && tries < nb * 40; tries++) {
        const ang = rand() * Math.PI * 2, r = 380 + rand() * (size * 0.42 - 380);
        const x = Math.cos(ang) * r, y = Math.sin(ang) * r, z = height(x, y);
        if (z < waterZ + 2 || z > relH * 0.6 || inRunway(x, y, hdg, 120)) continue;
        const w = 8 + rand() * 18, d = 8 + rand() * 18, hgt = 6 + rand() * 34;
        if (buildingsAABB.some(b => x + w / 2 > b.x1 - 6 && x - w / 2 < b.x2 + 6 && y + d / 2 > b.y1 - 6 && y - d / 2 < b.y2 + 6)) continue;
        p.set(x, y, z - 1); sc.set(w, d, hgt + 1);
        inst.setMatrixAt(placed, m4.compose(p, q, sc));
        bc.setHSL(0.08 + rand() * 0.05, 0.08 + rand() * 0.15, night ? 0.25 : 0.55 + rand() * 0.3);
        inst.setColorAt(placed, bc);
        buildingsAABB.push({ x1: x - w / 2, x2: x + w / 2, y1: y - d / 2, y2: y + d / 2, z2: z + hgt });
        placed++;
      }
      inst.count = placed;
      inst.instanceMatrix.needsUpdate = true;
      if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
      gWorld.add(inst);
    }

    // --- ağaçlar (gövde + taç; InstancedMesh ≤ 20.000; su/pist/bina/kar üzerinde değil) ---
    const density = clamp(num(W.tree_density, 0), 0, 1);
    const nt = Math.min(preview ? 3000 : MAX_TREES, Math.round(density * MAX_TREES));
    if (nt > 0) {
      const crownG = new T.ConeGeometry(1, 1, 6); crownG.rotateX(Math.PI / 2); crownG.translate(0, 0, 0.5);
      const trunkG = new T.CylinderGeometry(0.12, 0.18, 1, 5); trunkG.rotateX(Math.PI / 2); trunkG.translate(0, 0, 0.5);
      const crown = new T.InstancedMesh(crownG, new T.MeshLambertMaterial({ color: 0xffffff }), nt);
      const trunk = new T.InstancedMesh(trunkG, new T.MeshLambertMaterial({ color: night ? 0x2a2017 : 0x5a3f27 }), nt);
      const m4 = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), p = new T.Vector3(), cc = new T.Color();
      let placed = 0;
      for (let tries = 0; placed < nt && tries < nt * 4; tries++) {
        const x = (rand() - 0.5) * size * 0.98, y = (rand() - 0.5) * size * 0.98, r = Math.hypot(x, y);
        if (r < 330) continue;
        const z = height(x, y);
        if (z < waterZ + 2 || z > relH * 0.72 || (W.runway !== false && inRunway(x, y, hdg, 60))) continue;
        if (buildingsAABB.some(b => x > b.x1 - 3 && x < b.x2 + 3 && y > b.y1 - 3 && y < b.y2 + 3)) continue;
        const hh = 6 + rand() * 9, rr = 1.8 + rand() * 2.2;
        p.set(x, y, z - 0.3); sc.set(1, 1, hh * 0.35 + 0.3);
        trunk.setMatrixAt(placed, m4.compose(p, q, sc));
        p.set(x, y, z + hh * 0.3); sc.set(rr, rr, hh * 0.7);
        crown.setMatrixAt(placed, m4.compose(p, q, sc));
        cc.setHSL(0.27 + rand() * 0.08, 0.45 + rand() * 0.2, (night ? 0.12 : 0.22) + rand() * 0.12);
        crown.setColorAt(placed, cc);
        placed++;
      }
      crown.count = trunk.count = placed;
      crown.instanceMatrix.needsUpdate = trunk.instanceMatrix.needsUpdate = true;
      if (crown.instanceColor) crown.instanceColor.needsUpdate = true;
      gWorld.add(trunk, crown);
    }

    // Merkez işareti (ev konumu): küçük turuncu disk
    const home = new T.Mesh(new T.CircleGeometry(3, 24), new T.MeshBasicMaterial({ color: 0xf59e0b }));
    home.position.z = 0.12;
    gWorld.add(home);
  }

  // ---------- dron modelleri ----------
  // Gövde çerçevesi: burun +Y, sağ kanat +X, üst +Z; birimler metre (gerçek boyut), görünürlük için ×MODEL_SCALE.
  // Sabit kanat / VTOL gövdesi (airframe): 'caymaz' → static/models/caymaz-sim.glb (CAYMAZ V3 STEP'inden; glTF: Y yukarı, burun +Z,
  // sol kanat +X → Rx+90°, Rz180°), 'delta' → prosedürel delta uçan kanat. Pervane düğümleri `props` (yerel Z etrafında döner,
  // userData.dir ±1; userData.disc/blades: yüksek devirde palalar gizlenir, saydam disk belirir). Kontrol yüzeyleri `ctrl`.
  let drone = { group: new T.Group(), props: [], ctrl: [], lights: [], radius: 3, nose: 2, type: null, airframe: null };
  scene.add(drone.group);
  const MAT = () => ({
    carbon: new T.MeshStandardMaterial({ color: 0x1f2428, roughness: 0.55, metalness: 0.35 }),
    dark: new T.MeshStandardMaterial({ color: 0x2b3340, roughness: 0.6, metalness: 0.2 }),
    body: new T.MeshStandardMaterial({ color: 0x33496f, roughness: 0.5, metalness: 0.15 }),
    white: new T.MeshStandardMaterial({ color: 0xe9ecf1, roughness: 0.5, metalness: 0.1 }),
    grey: new T.MeshStandardMaterial({ color: 0x8a939e, roughness: 0.5, metalness: 0.5 }),
    red: new T.MeshStandardMaterial({ color: 0xd93a2b, roughness: 0.55 }),
    orange: new T.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.55 }),
    glass: new T.MeshStandardMaterial({ color: 0x0b1420, roughness: 0.15, metalness: 0.6 }),
    disc: new T.MeshBasicMaterial({ color: 0x8a939e, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false }),
    blade: new T.MeshStandardMaterial({ color: 0x15181c, roughness: 0.6, side: T.DoubleSide }),
  });
  const mesh = (geo, mat, x = 0, y = 0, z = 0) => { const m = new T.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; return m; };
  // Pervane: hub + n pala (hafif hatve açısı) + bulanıklık diski; dönüş ekseni yerel Z
  const propeller = (r, dir, M, blades = 2, hub = r * 0.12) => {
    const g = new T.Group();
    g.userData.dir = dir;
    const disc = new T.Mesh(new T.RingGeometry(hub, r, 24, 1), M.disc.clone()); g.add(disc); g.userData.disc = disc;
    g.add(mesh(new T.CylinderGeometry(hub, hub, hub * 1.2, 10).rotateX(Math.PI / 2), M.dark));
    const bl = [];
    for (let k = 0; k < blades; k++) {
      const b = mesh(new T.BoxGeometry(r - hub * 0.8, r * 0.15, Math.max(0.004, r * 0.012)), M.blade, 0, 0, 0);
      b.geometry.translate((r + hub * 0.8) / 2, 0, 0);
      b.rotation.set(0.28 * dir, 0, k * 2 * Math.PI / blades);   // hatve açısı
      b.rotation.order = 'ZXY';
      g.add(b); bl.push(b);
    }
    g.userData.blades = bl;
    return g;
  };
  // Çokrotor (quad/hexa): gövde (üst/alt plaka), kollar, motorlar, iniş takımı, kamera gimbali, CW/CCW pervaneler
  const buildMulti = (n, span, M) => {
    const grp = new T.Group(), props = [];
    const R = span / 2, bodyW = span * 0.3, bodyH = span * 0.08;
    grp.add(mesh(new T.CylinderGeometry(bodyW / 2, bodyW / 2, bodyH, 8).rotateX(Math.PI / 2), M.carbon, 0, 0, 0));
    grp.add(mesh(new T.BoxGeometry(bodyW * 0.7, bodyW * 0.9, bodyH * 1.3), M.body, 0, 0, bodyH * 0.9));   // batarya/üst kapak
    grp.add(mesh(new T.BoxGeometry(bodyW * 0.3, bodyW * 0.3, bodyH * 0.4), M.orange, 0, bodyW * 0.42, bodyH * 1.6));   // burun işareti (ileri +Y)
    grp.add(mesh(new T.CylinderGeometry(bodyW * 0.12, bodyW * 0.12, 0.03, 10).rotateX(Math.PI / 2), M.white, 0, -bodyW * 0.1, bodyH * 1.7));   // GPS
    for (let k = 0; k < n; k++) {
      const a = Math.PI / n + k * (2 * Math.PI / n), c = Math.cos(a), s = Math.sin(a);
      const arm = mesh(new T.CylinderGeometry(span * 0.018, span * 0.022, R - bodyW * 0.3, 8), M.carbon, c * (R + bodyW * 0.3) / 2, s * (R + bodyW * 0.3) / 2, 0);
      arm.rotation.z = a - Math.PI / 2; grp.add(arm);
      grp.add(mesh(new T.CylinderGeometry(span * 0.045, span * 0.05, span * 0.05, 12).rotateX(Math.PI / 2), M.grey, c * R, s * R, span * 0.03));   // motor
      const pr = propeller(span * 0.19, k % 2 ? 1 : -1, M); pr.position.set(c * R, s * R, span * 0.062); grp.add(pr); props.push(pr);
    }
    for (const sx of [-1, 1]) {   // iniş takımı: iki dikey ayak + kızak çubuğu (her yanda)
      for (const y of [-span * 0.18, span * 0.18]) grp.add(mesh(new T.CylinderGeometry(span * 0.01, span * 0.01, span * 0.2, 6).rotateX(Math.PI / 2), M.carbon, sx * span * 0.2, y, -span * 0.1));
      grp.add(mesh(new T.CylinderGeometry(span * 0.01, span * 0.01, span * 0.52, 6), M.carbon, sx * span * 0.2, 0, -span * 0.2));
    }
    // Kamera gimbali (alt ön)
    const gim = new T.Group(); gim.position.set(0, bodyW * 0.35, -bodyH * 1.3);
    gim.add(mesh(new T.CylinderGeometry(span * 0.03, span * 0.03, span * 0.04, 10).rotateX(Math.PI / 2), M.dark));
    gim.add(mesh(new T.SphereGeometry(span * 0.045, 12, 10), M.dark, 0, 0, -span * 0.05));
    gim.add(mesh(new T.CylinderGeometry(span * 0.02, span * 0.025, span * 0.03, 10), M.glass, 0, span * 0.045, -span * 0.05));   // lens ileri (+Y)
    grp.add(gim);
    return { grp, props, ctrl: [], tips: { left: [-R * 0.72, R * 0.72, 0.03], right: [R * 0.72, R * 0.72, 0.03], tail: [0, -R * 0.8, 0.08] } };   // ön kollar kırmızı/yeşil, arka beyaz
  };
  // Helikopter (1.5 m): gövde + kabin camı, kuyruk bomu, dikey/yatay stabilizatör, ana rotor (3 pala) + kuyruk rotoru, kızaklar
  const buildHeli = M => {
    const grp = new T.Group(), props = [];
    const fus = mesh(new T.SphereGeometry(0.22, 16, 12), M.body); fus.scale.set(0.9, 2.0, 0.85); grp.add(fus);
    const cab = mesh(new T.SphereGeometry(0.19, 16, 12), M.glass, 0, 0.22, 0.03); cab.scale.set(0.85, 1.1, 0.8); grp.add(cab);
    grp.add(mesh(new T.BoxGeometry(0.2, 0.3, 0.12), M.dark, 0, -0.05, 0.2));   // motor kaportası
    const boom = mesh(new T.CylinderGeometry(0.03, 0.05, 1.0, 10), M.white, 0, -0.9, 0.08); grp.add(boom);   // kuyruk bomu −Y boyunca (ince uç arkada)
    grp.add(mesh(new T.BoxGeometry(0.02, 0.22, 0.3), M.red, 0, -1.38, 0.2));      // dikey stabilizatör
    grp.add(mesh(new T.BoxGeometry(0.4, 0.12, 0.015), M.white, 0, -1.1, 0.12));   // yatay stabilizatör
    grp.add(mesh(new T.CylinderGeometry(0.02, 0.02, 0.22, 8).rotateX(Math.PI / 2), M.dark, 0, 0, 0.3));   // mast
    const main = propeller(0.85, 1, M, 3, 0.07); main.position.z = 0.42; grp.add(main); props.push(main);
    const tail = propeller(0.17, -1, M, 2, 0.025); tail.rotation.y = Math.PI / 2; tail.position.set(0.06, -1.38, 0.2); grp.add(tail); props.push(tail);
    for (const s of [-1, 1]) {
      grp.add(mesh(new T.CylinderGeometry(0.015, 0.015, 0.9, 8), M.grey, s * 0.22, 0.05, -0.3));   // kızak (Y boyunca)
      for (const y of [-0.2, 0.3]) { const st = mesh(new T.CylinderGeometry(0.012, 0.012, 0.22, 6).rotateX(Math.PI / 2), M.grey, s * 0.16, y, -0.2); st.rotation.y = s * 0.5; grp.add(st); }   // dikey destekler
    }
    return { grp, props, ctrl: [], tips: { left: [-0.2, 0.1, -0.05], right: [0.2, 0.1, -0.05], tail: [0, -1.4, 0.36] } };
  };
  // Delta uçan kanat (açıklık 2.2 m, uzunluk ~3.1 m): yuvarlak burunlu gövde, delta kanat, kanat ucu dikey yüzeyler,
  // arkadan itişli pervane, elevonlar (RC ile hareket). ExtrudeGeometry ile kanat planformu (XY düzlemi, kalınlık Z).
  const buildDelta = M => {
    const grp = new T.Group(), props = [], ctrl = [];
    const span = 2.2, L = 3.1, half = span / 2;
    const shape = new T.Shape();   // planform (sağ yarı + sol yarı simetrik), burun +Y
    shape.moveTo(0, 1.35); shape.lineTo(0.22, 1.0); shape.lineTo(half, -1.25); shape.lineTo(half, -1.45); shape.lineTo(0.3, -1.45);
    shape.lineTo(0, -1.5); shape.lineTo(-0.3, -1.45); shape.lineTo(-half, -1.45); shape.lineTo(-half, -1.25); shape.lineTo(-0.22, 1.0); shape.closePath();
    const wing = mesh(new T.ExtrudeGeometry(shape, { depth: 0.06, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 2 }), M.white, 0, 0, -0.04);
    grp.add(wing);
    // CylinderGeometry Y ekseni boyunca = gövde burun ekseni (+Y); burun geniş, kuyruk dar
    const fus = mesh(new T.CylinderGeometry(0.17, 0.11, L * 0.72, 16), M.white, 0, -0.1, 0.03); grp.add(fus);
    const nose = mesh(new T.SphereGeometry(0.17, 16, 12), M.white, 0, L * 0.72 / 2 - 0.1, 0.03); nose.scale.set(1, 1.6, 1); grp.add(nose);
    grp.add(mesh(new T.CylinderGeometry(0.11, 0.06, 0.25, 12), M.dark, 0, -L * 0.72 / 2 - 0.1 - 0.12, 0.03));   // motor kaportası
    for (const s of [-1, 1]) {   // kanat ucu dikey yüzeyler (yukarı/aşağı)
      const fin = mesh(new T.BoxGeometry(0.03, 0.5, 0.34), M.red, s * (half - 0.015), -1.2, 0.1); fin.geometry.translate(0, 0, 0); grp.add(fin);
      const el = mesh(new T.BoxGeometry(0.72, 0.16, 0.025), M.grey, s * 0.72, -1.52, 0); el.geometry.translate(0, -0.08, 0);   // elevon (menteşe ön kenarda)
      el.userData.ctrl = { roll: s, pitch: 1 }; grp.add(el); ctrl.push(el);
    }
    const pr = propeller(0.33, 1, M, 2); pr.rotation.x = -Math.PI / 2; pr.position.set(0, -L * 0.72 / 2 - 0.1 - 0.28, 0.03); grp.add(pr); props.push(pr);
    return { grp, props, ctrl, tips: { left: [-half, -1.3, 0.28], right: [half, -1.3, 0.28], tail: [0, -1.5, 0.08] } };
  };
  // CAYMAZ V3 (STEP → GLB): kanat açıklığı 3.03 m, uzunluk 3.1 m, arkadan itişli; prop düğümü GLB içinde (glTF Z ekseni = burun ekseni)
  let glbCache = null;
  const loadCaymaz = () => (glbCache ??= fetch('/static/models/caymaz-sim.glb', { credentials: 'same-origin' })
    .then(r => { if (!r.ok) throw new Error(`glb ${r.status}`); return r.arrayBuffer(); })
    .then(ab => new Promise((resolve, reject) => new GLTFLoader().parse(ab, '/static/models/', g => resolve(g.scene), reject)))
    .catch(e => { glbCache = null; throw e; }));
  const buildCaymaz = async M => {
    const sc = (await loadCaymaz()).clone(true);
    sc.traverse(o => { if (o.isMesh) { o.castShadow = true; o.material = o.material.clone(); } });
    const inner = new T.Group();
    inner.rotation.order = 'ZYX';
    inner.rotation.set(Math.PI / 2, 0, Math.PI);   // glTF (Y yukarı, burun +Z, sol +X) → gövde (burun +Y, sağ +X, üst +Z)
    inner.add(sc);
    const grp = new T.Group(); grp.add(inner);
    const props = [];
    const prop = sc.getObjectByName('prop');
    if (prop) {   // GLB pervanesi (Ø 0.81 m) + bulanıklık diski (glTF yerel XY düzlemi = pervane düzlemi)
      const disc = new T.Mesh(new T.RingGeometry(0.05, 0.405, 24, 1), M.disc.clone()); prop.add(disc);
      prop.userData.dir = 1; prop.userData.disc = disc; props.push(prop);
    }
    return { grp, props, ctrl: [], tips: { left: [-1.5, -0.95, 0.3], right: [1.5, -0.95, 0.3], tail: [0, -1.15, 0.02] } };
  };
  // VTOL: uçak gövdesi + kanat altı iki bum + 4 dikey motor/pervane (ileri/geri)
  const addVtolMotors = (built, M) => {
    const bb = new T.Box3().setFromObject(built.grp);
    const sx = (bb.max.x - bb.min.x) * 0.27, L = 1.5;
    for (const x of [-sx, sx]) {
      built.grp.add(mesh(new T.CylinderGeometry(0.03, 0.03, L, 8), M.carbon, x, -0.05, -0.02));   // bum Y boyunca (ileri-geri)
      for (const y of [-L / 2 + 0.05, L / 2 - 0.05]) {
        built.grp.add(mesh(new T.CylinderGeometry(0.04, 0.045, 0.06, 10).rotateX(Math.PI / 2), M.grey, x, y, 0.02));
        const pr = propeller(0.28, x * y > 0 ? 1 : -1, M); pr.position.set(x, y, 0.06); built.grp.add(pr); built.props.push(pr);
      }
    }
    return built;
  };
  // Seyir ışıkları: sol kırmızı, sağ yeşil (sabit + senkron flaş), kuyruk beyaz strobe; gece/akşam halo (additif sprite)
  let haloTex = null;
  const haloTexture = () => {
    if (haloTex) return haloTex;
    const cv = document.createElement('canvas'); cv.width = cv.height = 64;
    const g = cv.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.25, 'rgba(255,255,255,0.55)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    haloTex = new T.CanvasTexture(cv);
    return haloTex;
  };
  const addNavLights = (built, tips) => {
    const lights = [];
    for (const [key, color, kind] of [['left', 0xff2a1a, 'nav'], ['right', 0x22ff55, 'nav'], ['tail', 0xffffff, 'strobe']]) {
      const p = tips[key]; if (!p) continue;
      const g = new T.Group(); g.position.set(p[0], p[1], p[2]);
      const bulb = new T.Mesh(new T.SphereGeometry(0.035, 8, 6), new T.MeshBasicMaterial({ color, toneMapped: false }));
      const halo = new T.Sprite(new T.SpriteMaterial({ map: haloTexture(), color, transparent: true, opacity: 0.8, blending: T.AdditiveBlending, depthWrite: false, toneMapped: false }));
      halo.scale.setScalar(0.5);
      g.add(bulb, halo); g.userData = { kind, bulb, halo };
      built.grp.add(g); lights.push(g);
    }
    built.lights = lights;
  };
  const SIZES = { multirotor: 0.6, hexarotor: 0.9 };
  async function setType(type, airframe) {
    type = type || 'multirotor';
    airframe = (type === 'sabit_kanat' || type === 'vtol') ? (airframe === 'delta' ? 'delta' : 'caymaz') : null;
    disposeGroup(drone.group);
    const M = MAT();
    let built = null;
    if (airframe === 'caymaz') { try { built = await buildCaymaz(M); } catch { built = null; } }   // GLB yüklenemedi → delta kanat
    if (!built && airframe) built = buildDelta(M);
    if (!built) built = type === 'helikopter' ? buildHeli(M) : buildMulti(type === 'hexarotor' ? 6 : 4, SIZES[type] || 0.6, M);
    if (type === 'vtol') addVtolMotors(built, M);
    addNavLights(built, built.tips || {});
    built.grp.traverse(o => { if (o.isMesh && !o.isSprite) o.castShadow = true; });
    // Yarıçap ve burun konumu modelin sınırlayıcı kutusundan (kamera mesafeleri ve FPV için); sonra görünürlük ölçeği
    const bb = new T.Box3().setFromObject(built.grp);
    drone.radius = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y, 1) / 2 * MODEL_SCALE;
    drone.nose = (bb.max.y + 0.15) * MODEL_SCALE;
    drone.ground = -bb.min.z * MODEL_SCALE;   // park yüksekliği (iniş takımı yere değer)
    built.grp.scale.setScalar(MODEL_SCALE);   // 4 km'lik dünyada görünürlük: gerçek boyutun 2.5 katı
    drone.group.add(built.grp);
    drone.props = built.props; drone.ctrl = built.ctrl || []; drone.lights = built.lights || []; drone.type = type; drone.airframe = airframe;
    if (!tele.has) drone.group.position.set(0, 0, drone.ground + 0.02);   // park: pist merkezinde
  }

  // ---------- telemetri ve enterpolasyon ----------
  const tele = { has: false, target: new T.Vector3(0, 0, 0.6), vel: new T.Vector3(), q: new T.Quaternion(), at: 0, throttle: 0, armed: false, speed: 0, last: null };
  const cur = { pos: new T.Vector3(0, 0, 0.6), q: new T.Quaternion() };
  function setTelemetry(t) {
    if (!t) return;
    const p = (t.lat != null && t.lon != null) ? toLocal(t.lat, t.lon) : { x: num(t.x, 0), y: num(t.y, 0) };
    tele.target.set(p.x, p.y, num(t.alt_rel, 0));
    tele.vel.set(num(t.ve, 0), num(t.vn, 0), -num(t.vd, 0));
    attitudeQuat(T, num(t.roll, 0), num(t.pitch, 0), num(t.yaw, 0), tele.q);
    tele.at = performance.now();
    tele.throttle = num(t.throttle, 0); tele.armed = !!t.armed;
    tele.rc = Array.isArray(t.rc) ? t.rc : null;   // RC kanalları 1000…2000 (1: roll, 2: pitch) → kontrol yüzeyleri
    tele.speed = Math.hypot(tele.vel.x, tele.vel.y, tele.vel.z);
    tele.last = t;
    if (!tele.has) { tele.has = true; cur.pos.copy(tele.target); cur.q.copy(tele.q); }
  }

  // ---------- kameralar ----------
  let camMode = 'follow', gimbal = -10;   // derece; 0 = burun hizası, eksi = aşağı
  const free = { yaw: 0, pitch: -10, keys: new Set(), drag: null };
  const followOff = new T.Vector3(-2.4, -3.4, 1.4);   // × yarıçap (resetCamera)
  const tmpV = new T.Vector3(), tmpV2 = new T.Vector3(), tmpQ = new T.Quaternion(), tmpE = new T.Euler();
  const onCamChange = opts.onCameraChange || null;
  function setCamera(mode) {
    if (typeof mode === 'number') mode = CAMERA_MODES[mode - 1]?.[0];
    if (!CAMERA_MODES.some(([k]) => k === mode)) return;
    const prev = camMode;
    camMode = mode;
    controls.enabled = mode === 'follow';
    camera.fov = mode === 'fpv' ? 78 : 60;
    camera.updateProjectionMatrix();
    if (mode === 'follow') resetCamera();
    if (mode === 'free' && prev !== 'free') {
      // Serbest kamera: bulunduğu yerden devam; yön açılarını mevcut bakıştan türet
      camera.getWorldDirection(tmpV);
      free.yaw = Math.atan2(-tmpV.x, tmpV.y) / DEG;
      free.pitch = Math.asin(clamp(tmpV.z, -1, 1)) / DEG;
    }
    if (mode === 'ground') camera.position.set(RUNWAY_W / 2 + 25, -70, terrainHeight(RUNWAY_W / 2 + 25, -70) + 3);
    onCamChange?.(mode);
  }
  function resetCamera() {
    camera.position.copy(cur.pos).add(tmpV.copy(followOff).multiplyScalar(Math.max(2, drone.radius)));
    controls.target.copy(cur.pos);
    controls.update();
  }
  const setGimbal = delta => { gimbal = clamp(gimbal + delta, -90, 30); return gimbal; };

  // Klavye: 1–4 kamera, ↑↓ gimbal (FPV), WASD/QE serbest hareket (Shift hızlı). Form alanlarında devre dışı.
  const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const onKeyDown = e => {
    if (preview || editable(document.activeElement) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key >= '1' && e.key <= '4') { setCamera(Number(e.key)); e.preventDefault(); return; }
    if (camMode === 'fpv' && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { setGimbal(e.key === 'ArrowUp' ? 5 : -5); e.preventDefault(); return; }
    if (camMode === 'free') { const k = e.key.toLowerCase(); if ('wasdqe'.includes(k) || e.key === 'Shift') { free.keys.add(k === 'shift' ? 'shift' : k); e.preventDefault(); } }
  };
  const onKeyUp = e => { free.keys.delete(e.key.toLowerCase()); if (e.key === 'Shift') free.keys.delete('shift'); };
  const onPointerDown = e => { if (camMode !== 'free' || e.button !== 0) return; free.drag = { x: e.clientX, y: e.clientY }; canvas.setPointerCapture(e.pointerId); };
  const onPointerMove = e => {
    if (!free.drag) return;
    free.yaw -= (e.clientX - free.drag.x) * 0.25; free.pitch = clamp(free.pitch - (e.clientY - free.drag.y) * 0.2, -89, 89);
    free.drag = { x: e.clientX, y: e.clientY };
  };
  const onPointerUp = () => { free.drag = null; };
  const onWheel = e => { if (camMode === 'fpv') { setGimbal(e.deltaY > 0 ? -3 : 3); e.preventDefault(); } };
  if (!preview) {
    window.addEventListener('keydown', onKeyDown); window.addEventListener('keyup', onKeyUp);
    canvas.addEventListener('pointerdown', onPointerDown); canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp); canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
  }

  // ---------- çarpışma ----------
  let collided = false;
  const terrainHeight = (x, y) => (terrain ? terrain.height(x, y) : 0);
  function checkCollision() {
    if (collided || !tele.has || !tele.armed || tele.speed <= 1) return;
    const p = cur.pos;
    let hit = null;
    const hz = terrainHeight(p.x, p.y);
    const onRunway = Math.hypot(p.x, p.y) <= 25 || (W.runway !== false && inRunway(p.x, p.y, num(W.runway_heading, 0), 4));   // pist/kalkış alanında yer teması (koşu, iniş) çarpışma değil
    if (p.z < hz + 0.3 && !onRunway) hit = { kind: 'terrain', z: hz };
    else if (terrain && p.z < terrain.waterZ + 0.3) hit = { kind: 'water', z: terrain.waterZ };
    else {
      const b = buildingsAABB.find(b => p.x > b.x1 && p.x < b.x2 && p.y > b.y1 && p.y < b.y2 && p.z < b.z2 + 0.3);
      if (b) hit = { kind: 'building', z: b.z2 };
    }
    if (hit) { collided = true; onCollision?.({ ...hit, x: p.x, y: p.y, alt: p.z, speed: tele.speed }); }
  }
  const clearCollision = () => { collided = false; };

  // ---------- boyut ----------
  function resize() {
    const w = Math.max(1, mountEl.clientWidth), hgt = Math.max(1, mountEl.clientHeight);
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(mountEl);

  // ---------- kare döngüsü ----------
  let raf = 0, lastT = performance.now(), disposed = false, previewAngle = 0.6;
  const propAngle = { v: 0 };
  function frame(now) {
    if (disposed) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - lastT) / 1000); lastT = now;
    // Telemetri: hızla öngörü (en çok 0.3 sn) + üstel yumuşatma; yönelim slerp
    if (tele.has) {
      const age = Math.min(0.3, (now - tele.at) / 1000);
      tmpV.copy(tele.target).addScaledVector(tele.vel, age);
      const k = 1 - Math.exp(-dt * 10);
      const before = tmpV2.copy(cur.pos);
      cur.pos.lerp(tmpV, k);
      cur.q.slerp(tele.q, 1 - Math.exp(-dt * 12));
      drone.group.position.copy(cur.pos);
      drone.group.position.z += drone.ground || 0;   // alt_rel gövde orijini değil tekerlek/kızak yüksekliği: yerde model piste gömülmesin
      drone.group.quaternion.copy(cur.q);
      if (camMode === 'follow') { camera.position.add(tmpV.copy(cur.pos).sub(before)); controls.target.copy(cur.pos); }
      checkCollision();
    }
    // Pervaneler: arm'lıysa en az rölanti, gaz ile hızlanır; yüksek devirde palalar gizlenir, bulanıklık diski belirir
    const rate = tele.armed ? 12 + tele.throttle * 0.9 : 0;   // rad/s
    propAngle.v += rate * dt;
    const blur = clamp((rate - 20) / 40, 0, 1);
    for (const p of drone.props) {
      p.rotation.z += rate * dt * (p.userData.dir || 1);
      if (p.userData.disc) p.userData.disc.material.opacity = 0.45 * blur;
      if (p.userData.blades) for (const b of p.userData.blades) b.visible = blur < 0.85;
    }
    // Kontrol yüzeyleri (elevon): RC roll (ch1) / pitch (ch2) → ±20°
    if (drone.ctrl.length) {
      const rc = tele.rc || [], rN = rc[0] ? clamp((rc[0] - 1500) / 500, -1, 1) : 0, pN = rc[1] ? clamp((rc[1] - 1500) / 500, -1, 1) : 0;
      for (const c of drone.ctrl) c.rotation.x = (pN * c.userData.ctrl.pitch - rN * c.userData.ctrl.roll) * 0.35;
    }
    // Seyir ışıkları: kırmızı/yeşil 1 Hz çift flaş üzerine sabit; kuyruk beyaz strobe 1 Hz (gece halo büyür)
    const tt = now / 1000, ph = tt % 1, navOn = ph < 0.08 || (ph > 0.16 && ph < 0.24), strobeOn = ph > 0.5 && ph < 0.58;
    const night = W.time === 'night', dusk = W.time === 'dusk', haloBase = night ? 0.55 : dusk ? 0.4 : 0.22;   // sprite ölçeği model ölçeğiyle çarpılır
    for (const l of drone.lights) {
      const on = l.userData.kind === 'strobe' ? strobeOn : navOn;
      l.userData.halo.scale.setScalar(haloBase * (on ? 1.8 : l.userData.kind === 'strobe' ? 0 : 0.7));
      l.userData.halo.visible = l.userData.kind !== 'strobe' || on;
      l.userData.bulb.visible = l.userData.kind !== 'strobe' || on || !night;
    }
    // Gölge: güneş dronu izler
    if (!preview) { lights.sun.target.position.copy(cur.pos); lights.sun.position.copy(cur.pos).addScaledVector(sunDir, 120); }
    // Kamera kipleri
    if (preview) {
      previewAngle += dt * 0.12;
      const R = Math.max(900, terrain ? terrain.size * 0.32 : 1200);
      camera.position.set(Math.cos(previewAngle) * R, Math.sin(previewAngle) * R, Math.max(260, terrain ? terrain.H * 0.9 + 160 : 300));
      camera.lookAt(0, 0, 40);
    } else if (camMode === 'follow') {
      controls.update();
    } else if (camMode === 'fpv') {
      // Burun konumu: gövde +Y yönünde model yarıçapı kadar ileri, biraz yukarı; bakış: gövde yönelimi × (90° + gimbal) X dönüşü
      tmpV.set(0, drone.nose, 0.12 * MODEL_SCALE).applyQuaternion(cur.q);
      camera.position.copy(cur.pos).add(tmpV);
      tmpQ.setFromAxisAngle(tmpV2.set(1, 0, 0), (90 + gimbal) * DEG);
      camera.quaternion.copy(cur.q).multiply(tmpQ);
    } else if (camMode === 'free') {
      const sp = (free.keys.has('shift') ? 120 : 30) * dt;
      tmpE.set((90 + free.pitch) * DEG, 0, free.yaw * DEG, 'ZXY');
      camera.quaternion.setFromEuler(tmpE);
      camera.getWorldDirection(tmpV);
      tmpV2.set(1, 0, 0).applyQuaternion(camera.quaternion);
      if (free.keys.has('w')) camera.position.addScaledVector(tmpV, sp);
      if (free.keys.has('s')) camera.position.addScaledVector(tmpV, -sp);
      if (free.keys.has('d')) camera.position.addScaledVector(tmpV2, sp);
      if (free.keys.has('a')) camera.position.addScaledVector(tmpV2, -sp);
      if (free.keys.has('e')) camera.position.z += sp;
      if (free.keys.has('q')) camera.position.z -= sp;
      camera.position.z = Math.max(camera.position.z, terrainHeight(camera.position.x, camera.position.y) + 1.5);
    } else if (camMode === 'ground') {
      camera.lookAt(cur.pos);
      const dist = camera.position.distanceTo(cur.pos);
      camera.fov = clamp(60 * 35 / Math.max(dist, 1), 5, 60);   // uzaklaştıkça yakınlaştır (teleobjektif)
      camera.updateProjectionMatrix();
    }
    renderer.render(scene, camera);
  }

  // ---------- kurulum ----------
  buildWorld(world);
  await setType(opts.type, opts.airframe);
  resize();
  if (!preview) { setCamera('follow'); } else { controls.enabled = false; }
  raf = requestAnimationFrame(frame);

  function setWorld(nw) { buildWorld(nw); if (!tele.has) drone.group.position.set(0, 0, (drone.ground || 0.2) + 0.02); if (!preview && camMode === 'follow') resetCamera(); }

  function dispose() {
    disposed = true;
    cancelAnimationFrame(raf);
    ro.disconnect();
    window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', onKeyUp);
    canvas.removeEventListener('pointerdown', onPointerDown); canvas.removeEventListener('pointermove', onPointerMove);
    canvas.removeEventListener('pointerup', onPointerUp); canvas.removeEventListener('pointercancel', onPointerUp);
    canvas.removeEventListener('wheel', onWheel);
    controls.dispose();
    disposeGroup(gWorld); disposeGroup(drone.group);
    renderer.dispose();
    renderer.forceContextLoss?.();
    canvas.remove();
  }

  return {
    setTelemetry, setCamera, getCamera: () => camMode, setGimbal, getGimbal: () => gimbal, resetCamera, terrainHeight, toLocal,
    setWorld, setType, clearCollision, resize, dispose,
    get collided() { return collided; }, get world() { return W; }, get waterZ() { return terrain ? terrain.waterZ : -Infinity; },
    set onCollision(fn) { onCollision = fn; },
    position: () => ({ x: cur.pos.x, y: cur.pos.y, z: cur.pos.z }),
    canvas,
  };
}
