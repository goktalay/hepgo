// Uçuş Simülatörü — 3B dünya (three.js r170, yerel kopya static/vendor/three). Sözleşme: docs/ucus-simulatoru.md §5.
// • Koordinat: ENU, merkez referanslı, Z YUKARI (camera.up = +Z). x = doğu, y = kuzey, z = alt_rel (pist seviyesi 0).
// • Arazi: tohumlu 2B simplex gürültü (kendi uygulamamız, bağımlılık yok), 3 oktav; merkez çevresinde 300 m düzleştirme; su seviyesi
//   `water` oranına göre; renkler yüksekliğe göre (kum → çim → kaya → kar). 256×256 ızgara, LOD yok.
// • Nesneler: ağaçlar (InstancedMesh ≤ 20.000, su/pist/bina üzerinde değil), binalar (kutular, 6–40 m), pist (asfalt + çizgiler,
//   runway_heading), gökyüzü/ışık (day/dusk/night; gece pist ve bina ışıkları), sis.
// • Dron: sabit kanat static/models/caymaz.gltf (GLTFLoader; yüklenemezse basit uçak geometrisi), multirotor/hexa/heli/vtol basit
//   geometri + dönen pervaneler (gaz ile hız). Yönelim: ArduPilot roll/pitch/yaw (NED) → ENU quaternion (Euler 'ZXY': pitch, roll, −yaw).
// • Kameralar (1–4): Takip (OrbitControls, hedef dron) · Dron kamerası (FPV, burun; gimbal ↑↓) · Serbest (WASD/QE + fare sürükle) · Yer.
// • Telemetri enterpolasyonu (20 Hz → kare): hız ile öngörü + üstel yumuşatma. Çarpışma: z < h(x,y)+0.3 ya da bina kutusu, hız > 1 m/s.
// • Gerçek arazi (world.mode = 'real'; §8): yükseklik AWS Terrain Tiles terrarium PNG (z 12–13, bilineer örnekleme), uydu doku Esri World
//   Imagery karoları canvas atlasında (z+3), OSM (Overpass) binalar (çokgen üçgenleme + duvarlar, tek geometri), orman çokgenlerinde ağaçlar,
//   su çokgenleri, gerçek pistler — hepsi arka uç vekilinden (/api/drone/sim/terrain, /tile, /osm; tarayıcı dışa çıkmaz). Yükseklik alınamazsa
//   prosedürele düşer (onFallback). Prosedürel ayarlar gerçek kipte özelleştirmedir: tree_density orman yoğunluğu ölçeği, building_count ek bina.
// Dışa: createFlightSim3D(mountEl, world, opts) → { setTelemetry, setCamera, getCamera, setGimbal, resetCamera, terrainHeight,
//        toLocal, setWorld (Promise), setOrigin, setType, clearCollision, resize, dispose }.

const LIB = '/static/vendor/three/';
export const ATTRIBUTION = 'Uydu: Esri, Maxar, Earthstar Geographics · Yükseklik: Mapzen / AWS Terrain Tiles · Binalar: © OpenStreetMap';
const TERRAIN_API = '/api/drone/sim';
const TILE_PX = 256;
const MAX_ATLAS = 4096;
const PARALLEL = 6;

// ---------- Web Mercator ----------
function lonlatToTile(lon, lat, z) {
  const n = 2 ** z;
  const x = (lon + 180) / 360 * n;
  const lr = Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180;
  const y = (1 - Math.log(Math.tan(lr) + 1 / Math.cos(lr)) / Math.PI) / 2 * n;
  return [x, y];
}

// Nokta çokgen içinde mi (ışın yöntemi; pts: [[x, y]…])
function pointInPoly(x, y, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

async function pool(items, n, fn) {
  let i = 0;
  const workers = Array.from({ length: Math.min(n, items.length) }, async () => { while (i < items.length) { const k = i++; await fn(items[k], k); } });
  await Promise.all(workers);
}

async function getJSON(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) { let d = ''; try { d = (await r.json()).detail || ''; } catch { /* */ } throw Object.assign(new Error(d || `HTTP ${r.status}`), { status: r.status }); }
  return r.json();
}

async function getBitmap(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) throw Object.assign(new Error(`karo ${r.status}`), { status: r.status });
  const blob = await r.blob();
  if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
  return new Promise((res, rej) => { const im = new Image(); const u = URL.createObjectURL(blob); im.onload = () => { URL.revokeObjectURL(u); res(im); }; im.onerror = () => { URL.revokeObjectURL(u); rej(new Error('karo çözülemedi')); }; im.src = u; });
}

// Gerçek arazi verisini yükler → { sample(x, y) (m, merkez 0), uv(x, y), atlas (canvas), homeElev, hmin, hmax, osm, osmError, meta }
// onProgress({stage: 'plan'|'elev'|'img'|'osm', done, total})
export async function loadRealTerrain(T, origin, size, toLocal, onProgress) {
  const prog = (stage, done, total) => onProgress?.({ stage, done, total });
  prog('plan', 0, 1);
  const meta = await getJSON(`${TERRAIN_API}/terrain?lat=${origin.lat}&lon=${origin.lon}&size_m=${Math.round(size)}`);
  const z = meta.z, tiles = meta.tiles || [], iz = meta.img_z, itiles = meta.img_tiles || [];
  if (!tiles.length) throw new Error('Yükseklik karosu planı boş');
  const ext = ts => { const xs = ts.map(t => t.x), ys = ts.map(t => t.y); return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }; };
  const E = ext(tiles), nx = E.x1 - E.x0 + 1, ny = E.y1 - E.y0 + 1, mw = nx * TILE_PX, mh = ny * TILE_PX;
  const mosaic = new Float32Array(mw * mh);
  const cv = document.createElement('canvas'); cv.width = cv.height = TILE_PX;
  const c2 = cv.getContext('2d', { willReadFrequently: true });
  let done = 0, elevOk = 0;
  // --- yükseklik karoları (terrarium: R·256 + G + B/256 − 32768) ---
  await pool(tiles, PARALLEL, async t => {
    try {
      const bmp = await getBitmap(meta.elev_url_template.replace('{z}', z).replace('{x}', t.x).replace('{y}', t.y));
      c2.clearRect(0, 0, TILE_PX, TILE_PX); c2.drawImage(bmp, 0, 0); bmp.close?.();
      const d = c2.getImageData(0, 0, TILE_PX, TILE_PX).data;
      const ox = (t.x - E.x0) * TILE_PX, oy = (t.y - E.y0) * TILE_PX;
      for (let py = 0; py < TILE_PX; py++) {
        let s = py * TILE_PX * 4;
        const o = (oy + py) * mw + ox;
        for (let px = 0; px < TILE_PX; px++, s += 4) mosaic[o + px] = d[s] * 256 + d[s + 1] + d[s + 2] / 256 - 32768;
      }
      elevOk++;
    } catch (err) { if (err?.status === 503 || err?.status === 502) throw err; }
    prog('elev', ++done, tiles.length);
  });
  if (!elevOk) throw new Error('Yükseklik verisi alınamadı');
  const cosLat = Math.cos(origin.lat * Math.PI / 180);
  const toLL = (x, y) => [origin.lat + y / 110574, origin.lon + x / (111320 * cosLat)];
  const sampleRaw = (x, y) => {
    const [lat, lon] = toLL(x, y);
    const [fx, fy] = lonlatToTile(lon, lat, z);
    const px = Math.min(mw - 1.001, Math.max(0, (fx - E.x0) * TILE_PX - 0.5)), py = Math.min(mh - 1.001, Math.max(0, (fy - E.y0) * TILE_PX - 0.5));
    const ix = Math.floor(px), iy = Math.floor(py), ax = px - ix, ay = py - iy;
    const i0 = iy * mw + ix, i1 = i0 + mw;
    return (mosaic[i0] * (1 - ax) + mosaic[i0 + 1] * ax) * (1 - ay) + (mosaic[i1] * (1 - ax) + mosaic[i1 + 1] * ax) * ay;
  };
  const h0 = sampleRaw(0, 0);
  const homeElev = meta.home_elev != null ? Number(meta.home_elev) : h0;
  let hmin = Infinity, hmax = -Infinity;
  for (let j = 0; j < 64; j++) for (let i = 0; i < 64; i++) { const v = sampleRaw((i / 63 - 0.5) * size, (j / 63 - 0.5) * size) - h0; hmin = Math.min(hmin, v); hmax = Math.max(hmax, v); }
  const sample = (x, y) => sampleRaw(x, y) - h0;
  // --- uydu atlası (karolar canvas'a çizilir; gece/akşam koyulaştırma malzeme renginde — atlas yeniden kullanılabilir) ---
  const I = ext(itiles.length ? itiles : tiles), inx = I.x1 - I.x0 + 1, iny = I.y1 - I.y0 + 1;
  const scale = Math.min(1, MAX_ATLAS / Math.max(inx, iny) / TILE_PX);
  const atlas = document.createElement('canvas');
  atlas.width = Math.round(inx * TILE_PX * scale); atlas.height = Math.round(iny * TILE_PX * scale);
  const ac = atlas.getContext('2d');
  ac.fillStyle = '#3b4a3a'; ac.fillRect(0, 0, atlas.width, atlas.height);
  done = 0;
  const ts = TILE_PX * scale;
  await pool(itiles, PARALLEL, async t => {
    try {
      const bmp = await getBitmap(meta.img_url_template.replace('{z}', iz).replace('{x}', t.x).replace('{y}', t.y));
      ac.drawImage(bmp, (t.x - I.x0) * ts, (t.y - I.y0) * ts, ts, ts); bmp.close?.();
    } catch { /* eksik karo: zemin rengi kalır */ }
    prog('img', ++done, itiles.length);
  });
  const uv = (x, y) => {
    const [lat, lon] = toLL(x, y);
    const [fx, fy] = lonlatToTile(lon, lat, iz);
    return [(fx - I.x0) / inx, 1 - (fy - I.y0) / iny];
  };
  // --- OSM (binalar/orman/su/pist); alınamazsa uyarı ile boş ---
  prog('osm', 0, 1);
  let osm = null, osmError = null;
  try { osm = await getJSON(`${TERRAIN_API}/osm?lat=${origin.lat}&lon=${origin.lon}&size_m=${Math.round(size)}`); } catch (err) { osmError = err?.message || String(err); }
  prog('osm', 1, 1);
  return { sample, uv, atlas, homeElev, hmin, hmax, osm, osmError, meta };
}
let _libs = null;
const loadLibs = () => (_libs ??= Promise.all(
  ['three.module.min.js', 'OrbitControls.js', 'GLTFLoader.js'].map(f => import(LIB + f)),
).then(([T, O, G]) => ({ T, OrbitControls: O.OrbitControls, GLTFLoader: G.GLTFLoader })).catch(e => { _libs = null; throw e; }));

export const CAMERA_MODES = [['follow', 'Takip'], ['fpv', 'Dron kamerası'], ['free', 'Serbest'], ['ground', 'Yer']];
export const WORLD_DEFAULTS = {
  mode: 'procedural', seed: 12345, size_m: 4000, tree_density: 0.3, mountain_height: 300, mountain_count: 4, building_count: 40,
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
  scene.add(lights.sun, lights.hemi, lights.amb);

  const disposeGroup = g => {
    g.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      const ms = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      ms.forEach(m => { for (const k of ['map', 'emissiveMap']) m[k]?.dispose?.(); m.dispose?.(); });
    });
    while (g.children.length) g.remove(g.children[0]);
  };

  // ---------- ortak dünya parçaları (prosedürel + gerçek) ----------
  function skyAndLights(size) {
    const night = W.time === 'night', dusk = W.time === 'dusk';
    const sky = night ? 0x0a1328 : dusk ? 0xe0956a : 0x8fbdea;
    renderer.setClearColor(sky, 1);
    scene.background = new T.Color(sky);
    lights.sun.color.set(night ? 0x6f7fb0 : dusk ? 0xffb070 : 0xfff2dc);
    lights.sun.intensity = night ? 0.45 : dusk ? 1.3 : 2.4;
    lights.sun.position.set(night ? -0.3 : dusk ? -0.9 : 0.6, dusk ? -0.2 : -0.5, night ? 0.5 : dusk ? 0.25 : 0.9).multiplyScalar(size);
    lights.hemi.color.set(night ? 0x1b2a55 : dusk ? 0xf0b088 : 0xbfd8ff);
    lights.hemi.groundColor.set(night ? 0x060a12 : 0x3a4a2a);
    lights.hemi.intensity = night ? 0.5 : dusk ? 0.8 : 0.9;
    lights.amb.intensity = night ? 0.3 : 0.15;
    const fog = clamp(num(W.fog, 0), 0, 1);
    scene.fog = fog > 0 ? new T.Fog(sky, size * 0.12, size * (1.6 - 1.25 * fog)) : null;
    return { night, dusk };
  }

  // Pist (asfalt, orta çizgiler, eşik çizgileri; heading; gece kenar ışıkları). Konum/yükseklik çağıran verir.
  function runwayMesh(hdg, L, Wd, night, dusk) {
    const rw = new T.Group();
    rw.rotation.z = -hdg * DEG;
    rw.add(new T.Mesh(new T.PlaneGeometry(Wd, L), new T.MeshLambertMaterial({ color: night ? 0x1c1f24 : 0x3a3d42 })));
    const white = new T.MeshBasicMaterial({ color: night ? 0x9aa3ad : 0xf5f5f5 });
    for (let y = -L / 2 + 60; y < L / 2 - 60; y += 60) { const d = new T.Mesh(new T.PlaneGeometry(1.2, 30), white); d.position.set(0, y, 0.02); rw.add(d); }
    const kMax = Math.max(1, Math.min(3, Math.floor(Wd / 12)));
    for (const sgn of [-1, 1]) for (let k = -kMax; k <= kMax; k++) { if (!k) continue; const s = new T.Mesh(new T.PlaneGeometry(2.4, 30), white); s.position.set(k * 4.8, sgn * (L / 2 - 22), 0.02); rw.add(s); }
    for (const sgn of [-1, 1]) { const e = new T.Mesh(new T.PlaneGeometry(0.9, L), white); e.position.set(sgn * (Wd / 2 - 0.6), 0, 0.02); rw.add(e); }
    if (night || dusk) {
      const pts = [], cols = [];
      for (let y = -L / 2; y <= L / 2; y += 60) for (const sgn of [-1, 1]) { pts.push(sgn * (Wd / 2 + 1.5), y, 0.6); cols.push(1, 0.95, 0.8); }
      for (let x = -Wd / 2; x <= Wd / 2; x += 5) { pts.push(x, -L / 2 - 2, 0.6, x, L / 2 + 2, 0.6); cols.push(0.2, 1, 0.3, 1, 0.25, 0.2); }
      const pg = new T.BufferGeometry();
      pg.setAttribute('position', new T.Float32BufferAttribute(pts, 3));
      pg.setAttribute('color', new T.Float32BufferAttribute(cols, 3));
      rw.add(new T.Points(pg, new T.PointsMaterial({ size: 0.8, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: 0.95 })));
    }
    return rw;
  }

  // Rastgele kutu binalar (prosedürel; gerçek kipte "ek bina"): pistten uzak, su dışında, mevcut AABB'lerle çakışmaz
  function boxBuildings(nb, size, height, waterZ, relH, hdg, rand, night) {
    const bgeo = new T.BoxGeometry(1, 1, 1); bgeo.translate(0, 0, 0.5);
    const bmat = new T.MeshLambertMaterial({ color: 0xffffff, emissive: night ? 0x3a3418 : 0x000000 });
    const inst = new T.InstancedMesh(bgeo, bmat, nb);
    const m4 = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), p = new T.Vector3(), bc = new T.Color();
    let placed = 0;
    for (let tries = 0; placed < nb && tries < nb * 40; tries++) {
      const ang = rand() * Math.PI * 2, r = 380 + rand() * (size * 0.42 - 380);
      const x = Math.cos(ang) * r, y = Math.sin(ang) * r, z = height(x, y);
      if (z < waterZ + 2 || (!terrain.real && z > relH * 0.6) || inRunway(x, y, hdg, 120) || inWater(x, y, z)) continue;
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

  // Ağaçlar: `pick()` bir aday (x, y) üretir (ya da null); su/pist/bina/kar üzerinde değil
  function trees(nt, pick, height, waterZ, relH, hdg, rand, night) {
    const crownG = new T.ConeGeometry(1, 1, 6); crownG.rotateX(Math.PI / 2); crownG.translate(0, 0, 0.5);
    const trunkG = new T.CylinderGeometry(0.12, 0.18, 1, 5); trunkG.rotateX(Math.PI / 2); trunkG.translate(0, 0, 0.5);
    const crown = new T.InstancedMesh(crownG, new T.MeshLambertMaterial({ color: 0xffffff }), nt);
    const trunk = new T.InstancedMesh(trunkG, new T.MeshLambertMaterial({ color: night ? 0x2a2017 : 0x5a3f27 }), nt);
    const m4 = new T.Matrix4(), q = new T.Quaternion(), sc = new T.Vector3(), p = new T.Vector3(), cc = new T.Color();
    let placed = 0;
    for (let tries = 0; placed < nt && tries < nt * 4; tries++) {
      const c = pick(); if (!c) continue;
      const [x, y] = c, r = Math.hypot(x, y);
      if (r < (W.runway !== false ? 330 : 60)) continue;
      const z = height(x, y);
      if (z < waterZ + 2 || (!terrain.real && z > relH * 0.72) || (W.runway !== false && inRunway(x, y, hdg, 60)) || inWater(x, y, z)) continue;
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
    return placed;
  }

  // Gerçek kip: su çokgenleri (yerel koordinat, bbox + z); nokta içinde mi
  let waterPolys = [];
  const inWater = (x, y, z) => waterPolys.some(w => x >= w.x1 && x <= w.x2 && y >= w.y1 && y <= w.y2 && z < w.z + 1.5 && pointInPoly(x, y, w.pts));

  // ---------- prosedürel dünya ----------
  function buildProcedural(world) {
    terrain = makeTerrain(world);
    W = terrain.W;
    const { size, H, height, waterZ, rand } = terrain;
    const { night, dusk } = skyAndLights(size);
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
    gWorld.add(ground);
    if (waterZ > -Infinity) {
      const water = new T.Mesh(new T.PlaneGeometry(size * 1.02, size * 1.02), new T.MeshPhongMaterial({
        color: night ? 0x0b1d3a : dusk ? 0x3b5f8a : 0x2f6fa8, transparent: true, opacity: 0.86, shininess: 90, specular: 0x88aadd }));
      water.position.z = waterZ;
      gWorld.add(water);
    }
    const hdg = num(W.runway_heading, 0);
    if (W.runway !== false) { const rw = runwayMesh(hdg, RUNWAY_L, RUNWAY_W, night, dusk); rw.position.z = 0.05; gWorld.add(rw); }
    const nb = clamp(Math.round(num(W.building_count, 0)), 0, 400);
    if (nb > 0) boxBuildings(nb, size, height, waterZ, relH, hdg, rand, night);
    const density = clamp(num(W.tree_density, 0), 0, 1);
    const nt = Math.min(preview ? 3000 : MAX_TREES, Math.round(density * MAX_TREES));
    if (nt > 0) trees(nt, () => [(rand() - 0.5) * size * 0.98, (rand() - 0.5) * size * 0.98], height, waterZ, relH, hdg, rand, night);
    addHomeMark();
  }

  // ---------- gerçek dünya (terrarium yükseklik + uydu doku + OSM) ----------
  function buildReal(world, real) {
    const Wn = { ...WORLD_DEFAULTS, ...(world || {}) };
    const size = clamp(num(Wn.size_m, 4000), 1000, 20000);
    const rand = rng(num(Wn.seed, 12345) ^ 0x9E3779B9);
    const flatR = Wn.runway !== false ? FLAT_R : 60, flatR2 = Wn.runway !== false ? FLAT_R2 : 160;
    const height = (x, y) => real.sample(x, y) * smooth(flatR, flatR2, Math.hypot(x, y));
    const H = Math.max(1, real.hmax - real.hmin);
    terrain = { W: Wn, size, H, height, waterZ: -Infinity, rand, real: true, homeElev: real.homeElev, hmin: real.hmin, hmax: real.hmax, osm: real.osm };
    W = Wn;
    const { night, dusk } = skyAndLights(size);
    const osm = real.osm || { buildings: [], forests: [], water: [], runways: [] };
    const half = size / 2;
    const toXY = ll => { const p = toLocal(ll[0], ll[1]); return [p.x, p.y]; };
    const inside = pts => pts.some(([x, y]) => Math.abs(x) <= half && Math.abs(y) <= half);

    // --- arazi: ızgara z = gerçek yükseklik (merkez 0); UV uydu atlasından ---
    const geo = new T.PlaneGeometry(size, size, GRID - 1, GRID - 1);
    const pos = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i);
      pos.setZ(i, height(x, y));
      const t = real.uv(x, y);
      uv.setXY(i, t[0], t[1]);
    }
    geo.computeVertexNormals();
    const tex = new T.CanvasTexture(real.atlas);
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy?.() || 1);
    tex.generateMipmaps = true; tex.minFilter = T.LinearMipmapLinearFilter;
    // Gece/akşam: doku çarpımsal koyulaştırma (atlas ham kalır, yeniden kullanılır)
    const ground = new T.Mesh(geo, new T.MeshLambertMaterial({ map: tex, color: night ? 0x4c5670 : dusk ? 0xe8b898 : 0xffffff }));
    ground.name = 'arazi';
    gWorld.add(ground);

    // --- su çokgenleri (OSM natural=water): düz yüzey, en alçak köşe −0.2 m ---
    waterPolys = [];
    const waterMat = new T.MeshPhongMaterial({ color: night ? 0x0b1d3a : dusk ? 0x3b5f8a : 0x2f6fa8, transparent: true, opacity: 0.86, shininess: 90, specular: 0x88aadd, side: T.DoubleSide });
    for (const poly of osm.water) {
      const pts = poly.map(toXY);
      if (pts.length < 3 || !inside(pts)) continue;
      let zmin = Infinity, x1 = Infinity, x2 = -Infinity, y1 = Infinity, y2 = -Infinity;
      for (const [x, y] of pts) { zmin = Math.min(zmin, height(x, y)); x1 = Math.min(x1, x); x2 = Math.max(x2, x); y1 = Math.min(y1, y); y2 = Math.max(y2, y); }
      const z = zmin - 0.2;
      const shape = new T.Shape(pts.map(([x, y]) => new T.Vector2(x, y)));
      const m = new T.Mesh(new T.ShapeGeometry(shape), waterMat);
      m.position.z = z;
      gWorld.add(m);
      waterPolys.push({ pts, z, x1, x2, y1, y2 });
    }

    // --- binalar (OSM): taban çokgen üçgenleme + duvarlar, tek BufferGeometry; AABB çarpışma için ---
    const hdg0 = num(Wn.runway_heading, 0);
    const bpos = [], bnorm = [], bcol = [];
    const roofC = new T.Color(), wallC = new T.Color();
    let nReal = 0;
    for (const b of osm.buildings) {
      const pts = b.poly.map(toXY);
      if (pts.length >= 4 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) pts.pop();
      if (pts.length < 3 || !inside(pts)) continue;
      let zmin = Infinity, zmax = -Infinity, x1 = Infinity, x2 = -Infinity, y1 = Infinity, y2 = -Infinity;
      for (const [x, y] of pts) { const z = height(x, y); zmin = Math.min(zmin, z); zmax = Math.max(zmax, z); x1 = Math.min(x1, x); x2 = Math.max(x2, x); y1 = Math.min(y1, y); y2 = Math.max(y2, y); }
      if (x2 - x1 > 600 || y2 - y1 > 600) continue;   // bozuk/çok büyük çokgen
      // Kalkış alanı: merkez pisti (açıksa) ve 60 m çevresini kesen binalar atlanır (kent merkezinde pist binaların arasından geçer)
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
      if (Math.hypot(cx, cy) < 60 || (Wn.runway !== false && (inRunway(cx, cy, hdg0, 50) || pts.some(([x, y]) => inRunway(x, y, hdg0, 50))))) continue;
      const zb = zmin - 0.6, zt = zmax + clamp(num(b.h, 8), 2, 400);
      const hue = 0.07 + rand() * 0.06, light = night ? 0.22 : 0.55 + rand() * 0.25;
      roofC.setHSL(hue, 0.1 + rand() * 0.12, light); wallC.setHSL(hue, 0.08 + rand() * 0.1, light * 0.8);
      // Saat yönü denetimi (shoelace) — duvar normalleri dışa baksın
      let area = 0;
      for (let i = 0; i < pts.length; i++) { const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length]; area += ax * by - bx * ay; }
      const ccw = area > 0;
      let tris;
      try { tris = T.ShapeUtils.triangulateShape(pts.map(([x, y]) => new T.Vector2(x, y)), []); } catch { tris = []; }
      for (const [a, b2, c] of tris) {
        const o = ccw ? [a, b2, c] : [a, c, b2];
        for (const k of o) { bpos.push(pts[k][0], pts[k][1], zt); bnorm.push(0, 0, 1); bcol.push(roofC.r, roofC.g, roofC.b); }
      }
      for (let i = 0; i < pts.length; i++) {
        const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length];
        const nx = (by - ay), ny = -(bx - ax), ln = Math.hypot(nx, ny) || 1;
        const s = ccw ? 1 : -1, n = [nx / ln * s, ny / ln * s, 0];
        const quad = ccw ? [[ax, ay, zb], [bx, by, zb], [bx, by, zt], [ax, ay, zb], [bx, by, zt], [ax, ay, zt]]
          : [[ax, ay, zb], [bx, by, zt], [bx, by, zb], [ax, ay, zb], [ax, ay, zt], [bx, by, zt]];
        for (const v of quad) { bpos.push(...v); bnorm.push(...n); bcol.push(wallC.r, wallC.g, wallC.b); }
      }
      buildingsAABB.push({ x1, x2, y1, y2, z2: zt });
      nReal++;
    }
    if (bpos.length) {
      const bg = new T.BufferGeometry();
      bg.setAttribute('position', new T.Float32BufferAttribute(bpos, 3));
      bg.setAttribute('normal', new T.Float32BufferAttribute(bnorm, 3));
      bg.setAttribute('color', new T.Float32BufferAttribute(bcol, 3));
      gWorld.add(new T.Mesh(bg, new T.MeshLambertMaterial({ vertexColors: true, emissive: night ? 0x2a2410 : 0x000000 })));
      if (night || dusk) {   // gece/akşam: bina ışıkları (çatı köşelerinde sıcak noktalar)
        const lp = [], lc = [];
        for (const b of buildingsAABB) {
          for (const [x, y] of [[b.x1 + 1, b.y1 + 1], [b.x2 - 1, b.y2 - 1]]) { lp.push(x, y, b.z2 - 1.2); const warm = 0.75 + rand() * 0.25; lc.push(1, 0.85 * warm, 0.5 * warm); }
        }
        const pg = new T.BufferGeometry();
        pg.setAttribute('position', new T.Float32BufferAttribute(lp, 3));
        pg.setAttribute('color', new T.Float32BufferAttribute(lc, 3));
        gWorld.add(new T.Points(pg, new T.PointsMaterial({ size: night ? 1.6 : 1.1, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: night ? 0.95 : 0.6 })));
      }
    }
    terrain.counts = { buildings: nReal, forests: 0, water: waterPolys.length, runways: 0 };

    // --- pistler: merkez pisti (düzleştirilmiş alan; isteğe bağlı) + OSM pistleri ---
    const hdg = num(Wn.runway_heading, 0);
    if (Wn.runway !== false) { const rw = runwayMesh(hdg, RUNWAY_L, RUNWAY_W, night, dusk); rw.position.z = 0.05; gWorld.add(rw); }
    for (const r of osm.runways) {
      const pts = r.poly.map(toXY);
      if (pts.length < 2 || !inside(pts)) continue;
      const [ax, ay] = pts[0], [bx, by] = pts[pts.length - 1];
      const L = Math.hypot(bx - ax, by - ay);
      if (L < 100) continue;
      const mx = (ax + bx) / 2, my = (ay + by) / 2;
      if (Wn.runway !== false && Math.hypot(mx, my) < RUNWAY_L / 2) continue;   // merkez pistiyle çakışır
      const rw = runwayMesh(num(r.heading, Math.atan2(bx - ax, by - ay) / DEG), L, clamp(num(r.width, 45), 15, 80), night, dusk);
      rw.position.set(mx, my, height(mx, my) + 0.4);
      gWorld.add(rw);
      terrain.counts.runways++;
    }

    // --- ek kutu binalar (building_count; 0 = yalnız gerçek binalar) ---
    const nb = clamp(Math.round(num(Wn.building_count, 0)), 0, 400);
    if (nb > 0) boxBuildings(nb, size, height, -Infinity, H, hdg, rand, night);

    // --- ağaçlar: orman çokgenlerinde (alanla orantılı; tree_density ölçek: 0.3 ≈ 4000 ağaç/km²) ---
    const density = clamp(num(Wn.tree_density, 0), 0, 1);
    const forests = [];
    let totalArea = 0;
    for (const poly of osm.forests) {
      const pts = poly.map(toXY);
      if (pts.length < 3 || !inside(pts)) continue;
      let area = 0, x1 = Infinity, x2 = -Infinity, y1 = Infinity, y2 = -Infinity;
      for (let i = 0; i < pts.length; i++) { const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length]; area += ax * by - bx * ay; x1 = Math.min(x1, ax); x2 = Math.max(x2, ax); y1 = Math.min(y1, ay); y2 = Math.max(y2, ay); }
      area = Math.abs(area) / 2;
      // Dünya sınırına kırp (bbox): dışarıda kalan alan sayılmaz
      const cx1 = Math.max(x1, -half), cx2 = Math.min(x2, half), cy1 = Math.max(y1, -half), cy2 = Math.min(y2, half);
      if (cx2 <= cx1 || cy2 <= cy1) continue;
      forests.push({ pts, area, x1: cx1, x2: cx2, y1: cy1, y2: cy2 });
      totalArea += area;
    }
    terrain.counts.forests = forests.length;
    if (density > 0 && totalArea > 0) {
      const want = Math.min(preview ? 3000 : MAX_TREES, Math.round(totalArea * 0.004 * (density / 0.3)));
      if (want > 0) {
        // Çokgen başına kota (alan oranı); aday: bbox içinde rastgele, çokgen içi denetimi
        const cum = []; let acc = 0;
        for (const f of forests) { acc += f.area / totalArea; cum.push(acc); }
        const pick = () => {
          const r = rand(); let i = cum.findIndex(c => r <= c); if (i < 0) i = forests.length - 1;
          const f = forests[i];
          const x = f.x1 + rand() * (f.x2 - f.x1), y = f.y1 + rand() * (f.y2 - f.y1);
          return pointInPoly(x, y, f.pts) ? [x, y] : null;
        };
        terrain.counts.trees = trees(want, pick, height, -Infinity, H, hdg, rand, night);
      }
    }
    addHomeMark();
  }

  function addHomeMark() {
    const home = new T.Mesh(new T.CircleGeometry(3, 24), new T.MeshBasicMaterial({ color: 0xf59e0b }));
    home.position.z = 0.12;
    gWorld.add(home);
  }

  // Dünya kurucu: prosedürel anında; gerçek kip veri yükler (ilerleme), alınamazsa prosedürele düşer (onFallback). Son çağrı kazanır.
  let buildSeq = 0, realCache = null;
  const onProgress = opts.onProgress || null, onFallback = opts.onFallback || null;
  async function buildWorld(world) {
    const seq = ++buildSeq;
    const Wn = { ...WORLD_DEFAULTS, ...(world || {}) };
    let real = null;
    if (Wn.mode === 'real') {
      const size = clamp(num(Wn.size_m, 4000), 1000, 20000);
      const key = `${origin.lat.toFixed(5)},${origin.lon.toFixed(5)},${size}`;
      try {
        if (!realCache || realCache.key !== key) {
          const r = await loadRealTerrain(T, origin, size, toLocal, p => { if (seq === buildSeq) onProgress?.(p); });
          if (seq !== buildSeq) return;
          realCache = { key, data: r };
        }
        real = realCache.data;
      } catch (err) {
        if (seq !== buildSeq) return;
        realCache = null;
        onFallback?.(err?.message || String(err));
        Wn.mode = 'procedural';
      }
    }
    disposeGroup(gWorld);
    buildingsAABB = []; waterPolys = [];
    if (real) buildReal(Wn, real); else buildProcedural(Wn);
    onProgress?.({ stage: 'done', real: !!real, counts: terrain.counts || null, homeElev: terrain.homeElev ?? null, hmin: terrain.hmin ?? null, hmax: terrain.hmax ?? null });
  }

  // ---------- dron modelleri ----------
  let drone = { group: new T.Group(), props: [], radius: 3, nose: 2, type: null };
  scene.add(drone.group);
  const propDisc = (r, dir, mat, bladeMat) => {
    const g = new T.Group();
    g.userData.dir = dir;
    const disc = new T.Mesh(new T.CircleGeometry(r, 20), mat); g.add(disc);
    for (let k = 0; k < 2; k++) { const b = new T.Mesh(new T.BoxGeometry(r * 2, r * 0.16, 0.02), bladeMat); b.rotation.z = k * Math.PI / 2; g.add(b); }
    return g;
  };
  const buildSimple = type => {
    const grp = new T.Group(), props = [];
    const dark = new T.MeshLambertMaterial({ color: 0x2b3340 }), body = new T.MeshLambertMaterial({ color: 0x2e4066 }),
      red = new T.MeshLambertMaterial({ color: 0xd93a2b }), white = new T.MeshLambertMaterial({ color: 0xeef0f4 }),
      propMat = new T.MeshBasicMaterial({ color: 0x9aa3ad, transparent: true, opacity: 0.25, side: T.DoubleSide }),
      blade = new T.MeshLambertMaterial({ color: 0x111418 });
    const armGeo = n => { const g = new T.CylinderGeometry(0.05, 0.05, n, 6); g.rotateZ(Math.PI / 2); return g; };
    if (type === 'multirotor' || type === 'hexarotor' || type === 'vtol') {
      const n = type === 'hexarotor' ? 6 : 4, L = 1.1;
      if (type !== 'vtol') {
        const hub = new T.Mesh(new T.BoxGeometry(0.5, 0.6, 0.18), body); grp.add(hub);
        const noseMark = new T.Mesh(new T.BoxGeometry(0.2, 0.3, 0.12), red); noseMark.position.set(0, 0.3, 0.1); grp.add(noseMark);   // burun işareti (ileri = +Y)
      }
      for (let k = 0; k < n; k++) {
        const a = (type === 'vtol' ? Math.PI / 4 : Math.PI / n) + k * (2 * Math.PI / n);
        const arm = new T.Mesh(armGeo(L), dark); arm.rotation.z = a; arm.position.set(Math.cos(a) * L / 2, Math.sin(a) * L / 2, 0); grp.add(arm);
        const motor = new T.Mesh(new T.CylinderGeometry(0.07, 0.07, 0.12, 8).rotateX(Math.PI / 2), dark); motor.position.set(Math.cos(a) * L, Math.sin(a) * L, 0.06); grp.add(motor);
        const pr = propDisc(0.32, k % 2 ? 1 : -1, propMat, blade); pr.position.set(Math.cos(a) * L, Math.sin(a) * L, 0.14); grp.add(pr); props.push(pr);
      }
    }
    if (type === 'helikopter') {
      const fus = new T.Mesh(new T.SphereGeometry(0.45, 12, 10).scale(1, 1.6, 0.9), body); grp.add(fus);
      const boom = new T.Mesh(new T.CylinderGeometry(0.06, 0.1, 1.6, 8), dark); boom.position.set(0, -1.3, 0.1); grp.add(boom);
      const fin = new T.Mesh(new T.BoxGeometry(0.04, 0.3, 0.5), red); fin.position.set(0, -2.1, 0.3); grp.add(fin);
      const mast = new T.Mesh(new T.CylinderGeometry(0.04, 0.04, 0.4, 6).rotateX(Math.PI / 2), dark); mast.position.z = 0.55; grp.add(mast);
      const main = propDisc(1.6, 1, propMat, blade); main.position.z = 0.76; grp.add(main); props.push(main);
      const tail = propDisc(0.3, -1, propMat, blade); tail.rotation.y = Math.PI / 2; tail.position.set(0.08, -2.1, 0.3); grp.add(tail); props.push(tail);
      for (const s of [-1, 1]) { const skid = new T.Mesh(new T.CylinderGeometry(0.03, 0.03, 1.4, 6), dark); skid.position.set(s * 0.35, 0, -0.45); grp.add(skid); }
    }
    if (type === 'sabit_kanat' || type === 'vtol') {
      const fus = new T.Mesh(new T.CylinderGeometry(0.12, 0.08, 2.2, 10), body); fus.position.y = 0.1; grp.add(fus);
      const nose = new T.Mesh(new T.SphereGeometry(0.12, 10, 8), body); nose.position.y = 1.2; grp.add(nose);
      const wing = new T.Mesh(new T.BoxGeometry(3.6, 0.42, 0.05), white); wing.position.set(0, 0.25, 0.08); grp.add(wing);
      const tailp = new T.Mesh(new T.BoxGeometry(1.2, 0.3, 0.04), white); tailp.position.set(0, -0.95, 0.05); grp.add(tailp);
      const fin = new T.Mesh(new T.BoxGeometry(0.04, 0.35, 0.45), red); fin.position.set(0, -0.95, 0.25); grp.add(fin);
      if (type === 'sabit_kanat') { const pr = propDisc(0.3, 1, propMat, blade); pr.rotation.x = Math.PI / 2; pr.position.set(0, 1.33, 0); grp.add(pr); props.push(pr); }
    }
    return { grp, props };
  };
  // caymaz.gltf tamponu `data:` URI'dir; CSP connect-src 'self' data: adresine fetch'i engeller → JSON'u kendimiz çekip tamponu
  // çözerek bellekte GLB (JSON + BIN parçası) kurar, GLTFLoader.parse ile yükleriz. Dış tampon (uri dosya) varsa olduğu gibi parse edilir.
  const loadGltfPlane = async () => {
    const res = await fetch('/static/models/caymaz.gltf', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`gltf ${res.status}`);
    const json = await res.json();
    const buf = json.buffers?.[0];
    let payload;
    if (buf && /^data:/.test(buf.uri || '')) {
      const b64 = buf.uri.slice(buf.uri.indexOf(',') + 1), bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      delete buf.uri; buf.byteLength = bytes.length;
      const enc = new TextEncoder(), jsonBytes = enc.encode(JSON.stringify(json));
      const pad4 = n => (4 - (n % 4)) % 4;
      const jl = jsonBytes.length + pad4(jsonBytes.length), bl = bytes.length + pad4(bytes.length);
      const glb = new ArrayBuffer(12 + 8 + jl + 8 + bl), dv = new DataView(glb), u8 = new Uint8Array(glb);
      dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, glb.byteLength, true);
      dv.setUint32(12, jl, true); dv.setUint32(16, 0x4E4F534A, true); u8.set(jsonBytes, 20); u8.fill(0x20, 20 + jsonBytes.length, 20 + jl);
      dv.setUint32(20 + jl, bl, true); dv.setUint32(24 + jl, 0x004E4942, true); u8.set(bytes, 28 + jl);
      payload = glb;
    } else payload = JSON.stringify(json);
    return new Promise((resolve, reject) => new GLTFLoader().parse(payload, '/static/models/', g => resolve(g.scene), reject));
  };
  async function setType(type) {
    type = type || 'multirotor';
    disposeGroup(drone.group);
    let built = null;
    if (type === 'sabit_kanat' || type === 'vtol') {
      try {
        // caymaz.gltf: Y yukarı, burun +Z, kanat ±X → gövde çerçevesi (burun +Y, üst +Z): önce X etrafında +90°, sonra Z etrafında 180°
        const sc = await loadGltfPlane();
        const inner = new T.Group();
        inner.rotation.order = 'ZYX';
        inner.rotation.set(Math.PI / 2, 0, Math.PI);
        inner.scale.setScalar(1.6);   // ×MODEL_SCALE ile ~6 m kanat açıklığı
        inner.add(sc);
        const grp = new T.Group(); grp.add(inner);
        const props = [];
        const propMat = new T.MeshBasicMaterial({ color: 0x9aa3ad, transparent: true, opacity: 0.25, side: T.DoubleSide }), blade = new T.MeshLambertMaterial({ color: 0x111418 });
        if (type === 'vtol') {
          const dark = new T.MeshLambertMaterial({ color: 0x2b3340 });
          for (const [sx, sy] of [[-1.3, 0.9], [1.3, 0.9], [-1.3, -0.9], [1.3, -0.9]]) {
            const boom = new T.Mesh(new T.CylinderGeometry(0.05, 0.05, 2, 6), dark); boom.position.set(sx, 0, 0.1); grp.add(boom);
            const pr = propDisc(0.35, sx * sy > 0 ? 1 : -1, propMat, blade); pr.position.set(sx, sy, 0.2); grp.add(pr); props.push(pr);
          }
        } else { const pr = propDisc(0.3, 1, propMat, blade); pr.rotation.x = Math.PI / 2; pr.position.set(0, 1.05, 0.05); grp.add(pr); props.push(pr); }
        built = { grp, props };
      } catch { built = null; }   // model yüklenemedi → basit uçak geometrisi
    }
    if (!built) built = buildSimple(type);
    // Yarıçap ve burun konumu modelin sınırlayıcı kutusundan (kamera mesafeleri ve FPV için); sonra görünürlük ölçeği
    const bb = new T.Box3().setFromObject(built.grp);
    drone.radius = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y, 1) / 2 * MODEL_SCALE;
    drone.nose = (bb.max.y + 0.15) * MODEL_SCALE;
    built.grp.scale.setScalar(MODEL_SCALE);   // 4 km'lik dünyada görünürlük: gerçek boyutun 2.5 katı
    drone.group.add(built.grp);
    drone.props = built.props; drone.type = type;
    if (!tele.has) drone.group.position.set(0, 0, 0.25 * MODEL_SCALE);   // park: pist merkezinde
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
    else if (terrain?.real && waterPolys.some(w => p.x >= w.x1 && p.x <= w.x2 && p.y >= w.y1 && p.y <= w.y2 && p.z < w.z + 0.3 && pointInPoly(p.x, p.y, w.pts))) hit = { kind: 'water', z: hz };
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
      drone.group.quaternion.copy(cur.q);
      if (camMode === 'follow') { camera.position.add(tmpV.copy(cur.pos).sub(before)); controls.target.copy(cur.pos); }
      checkCollision();
    }
    // Pervaneler: arm'lıysa en az rölanti, gaz ile hızlanır
    const spin = (tele.armed ? 12 + tele.throttle * 0.9 : 0) * dt;
    if (spin) for (const p of drone.props) p.rotation.z += spin * (p.userData.dir || 1);
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
  await buildWorld(world);
  await setType(opts.type);
  resize();
  if (!preview) { setCamera('follow'); } else { controls.enabled = false; }
  raf = requestAnimationFrame(frame);

  async function setWorld(nw) {
    await buildWorld(nw);
    if (disposed) return;
    if (!tele.has) drone.group.position.set(0, 0, 0.6);
    if (!preview && camMode === 'follow') resetCamera();
  }
  // Merkez değişti (sihirbaz): gerçek kipte veriler yeni konumdan yüklenir
  async function setOrigin(lat, lon, nw) {
    origin.lat = num(lat, 0); origin.lon = num(lon, 0);
    realCache = null;
    await setWorld(nw || W);
  }

  function dispose() {
    disposed = true;
    buildSeq++;   // bekleyen gerçek arazi yüklemesi sonuçlarını kullanmaz
    realCache = null;
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
    setWorld, setOrigin, setType, clearCollision, resize, dispose,
    get collided() { return collided; }, get world() { return W; }, get waterZ() { return terrain ? terrain.waterZ : -Infinity; },
    get real() { return !!terrain?.real; },
    get terrainInfo() { return terrain ? { real: !!terrain.real, homeElev: terrain.homeElev ?? null, hmin: terrain.hmin ?? null, hmax: terrain.hmax ?? null, counts: terrain.counts || null, osmError: realCache?.data?.osmError || null } : null; },
    set onCollision(fn) { onCollision = fn; },
    position: () => ({ x: cur.pos.x, y: cur.pos.y, z: cur.pos.z }),
    canvas,
  };
}
