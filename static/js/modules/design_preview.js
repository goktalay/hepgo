// Endüstriyel Tasarım — STEP sürümünün 3B önizlemesi (docs/endustriyel-tasarim-onizleme.md).
// Sunucuda node/occt yok; dönüşüm TARAYICIDA: STEP → occt wasm işçisi (step-worker.js; kademeli lineer sapma, üçgen ≤ ~150k) →
// three mesh'ler (renge göre birleştirilmiş) → (1) ikili STL (birleşik tek gövde, mm, renk yok) · (2) GLB (renkli, mm → m) ·
// (3) 3/4 açıdan 480×360 şeffaf PNG → PUT /api/design/versions/{id}/preview?kind=stl|glb|thumb. Aynı anda tek üretim (kuyruk);
// ilerleme kartta ("Önizleme hazırlanıyor %"). Gösterim: GLB'yi GLTFLoader ile hızlı görüntüleyici (kartta dönen canlı 3B, pencerede OrbitControls).
import { h, modal, t } from '../ui.js';
import { parseStep, stepWorkerBusy } from '../step3d.js';
import { putBinary } from './flightsim_models.js';

const LIB = '/static/vendor/three/';
export const MAX_TRIS = 150000;
const FIRST_DEFLECTION = 2;     // mm — ilk deneme; üçgen sayısı sınırı aşarsa oranla kabalaştırılır (en çok 4 deneme)
const MAX_TRIES = 4;

let libsP = null;
const loadThree = () => (libsP ??= Promise.all(['three.module.min.js', 'GLTFLoader.js', 'GLTFExporter.js', 'OrbitControls.js', 'BufferGeometryUtils.js'].map(f => import(LIB + f)))
  .then(([T, G, E, O, B]) => ({ T, GLTFLoader: G.GLTFLoader, GLTFExporter: E.GLTFExporter, OrbitControls: O.OrbitControls, mergeGeometries: B.mergeGeometries }))
  .catch(e => { libsP = null; throw e; }));

const fmtKB = b => b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`;

// STEP dosyasını ilerlemeyle indir (sürüm kimliği)
export async function fetchStep(vid, onProgress) {
  const resp = await fetch(`/api/design/file?v=${vid}`, { credentials: 'same-origin' });
  if (!resp.ok) throw new Error(t('Dosya alınamadı'));
  const total = +resp.headers.get('content-length') || 0;
  if (!resp.body || !resp.body.getReader) return resp.arrayBuffer();
  const reader = resp.body.getReader(), parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value); got += value.length;
    onProgress?.(total ? got / total : null, got, total);
  }
  const out = new Uint8Array(got); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out.buffer;
}

// STEP → three.Group (mm; renge göre birleştirilmiş MeshStandardMaterial gövdeler). Kademeli sapma: üçgen sayısı MAX_TRIS'i aşarsa
// bir sonraki sapma orantıyla seçilir (üçgen ≈ 1/sapma) → çoğu dosyada 1–2 çözümleme yeter.
async function meshStep(buf, T, mergeGeometries, onProgress) {
  let d = FIRST_DEFLECTION, res = null, tris = 0;
  for (let i = 0; i < MAX_TRIES; i++) {
    onProgress?.(stepWorkerBusy() ? t('CAD çekirdeği başka bir modeli çözümlüyor, sıra bekleniyor…') : t('CAD çözümleniyor (sapma {d} mm)…', { d }));
    res = await parseStep(buf, { params: { linearUnit: 'millimeter', linearDeflectionType: 'absolute_value', linearDeflection: d, angularDeflection: 0.6 } });
    tris = (res.meshes || []).reduce((n, m) => n + (m.index ? m.index.length / 3 : (m.position ? m.position.length / 9 : 0)), 0);
    onProgress?.(t('{n} üçgen', { n: Math.round(tris).toLocaleString('tr') }));
    if (tris <= MAX_TRIS) break;
    d = Math.min(64, Math.ceil(d * (tris / MAX_TRIS) * 1.25 * 2) / 2);   // 0,5 mm adımlarla yuvarla
  }
  if (!res || !res.meshes || !res.meshes.length) throw new Error(t('STEP dosyasında geometri yok'));
  const byColor = new Map();
  for (const m of res.meshes) {
    if (!m.position || !m.position.length) continue;
    const g = new T.BufferGeometry();
    g.setAttribute('position', new T.BufferAttribute(m.position, 3));
    if (m.index && m.index.length) g.setIndex(new T.BufferAttribute(m.index, 1));
    else g.setIndex(Array.from({ length: m.position.length / 3 }, (_, k) => k));
    if (m.normal && m.normal.length === m.position.length) g.setAttribute('normal', new T.BufferAttribute(m.normal, 3)); else g.computeVertexNormals();
    const c = m.color && m.color.length === 3 ? m.color.map(v => Math.round(Math.max(0, Math.min(1, v)) * 255) / 255) : [0.6, 0.66, 0.74];
    const key = c.join(',');
    if (!byColor.has(key)) byColor.set(key, { color: c, geos: [] });
    byColor.get(key).geos.push(g);
  }
  const root = new T.Group(); root.name = 'model';
  let i = 0;
  for (const { color, geos } of byColor.values()) {
    const merged = geos.length === 1 ? geos[0] : mergeGeometries(geos, false);
    if (!merged) continue;
    const mat = new T.MeshStandardMaterial({ color: new T.Color(color[0], color[1], color[2]), metalness: 0.2, roughness: 0.6, side: T.DoubleSide });
    const mesh = new T.Mesh(merged, mat); mesh.name = `govde_${++i}`;
    root.add(mesh);
  }
  return { root, tris: Math.round(tris), deflection: d, bodies: res.meshes.length, ms: res.ms || 0 };
}

// Gruptaki tüm gövdeler → ikili STL (mm; dünya dönüşümü uygulanır; yüz normali üçgenden hesaplanır; renk/öznitelik yok)
export function groupToStl(T, root) {
  root.updateMatrixWorld(true);
  const meshes = []; root.traverse(o => { if (o.isMesh && o.geometry?.attributes?.position) meshes.push(o); });
  let count = 0; for (const m of meshes) count += m.geometry.index ? m.geometry.index.count / 3 : m.geometry.attributes.position.count / 3;
  const buf = new ArrayBuffer(84 + count * 50), dv = new DataView(buf);
  new Uint8Array(buf, 0, 80).set(new TextEncoder().encode('HEPGO design preview STEP->STL mm').subarray(0, 80));
  dv.setUint32(80, count, true);
  let off = 84; const a = new T.Vector3(), b = new T.Vector3(), c = new T.Vector3(), nn = new T.Vector3();
  for (const m of meshes) {
    const pos = m.geometry.attributes.position.array, idx = m.geometry.index ? m.geometry.index.array : null, tri = idx ? idx.length / 3 : pos.length / 9, M = m.matrixWorld;
    for (let k = 0; k < tri; k++) {
      const i0 = (idx ? idx[k * 3] : k * 3) * 3, i1 = (idx ? idx[k * 3 + 1] : k * 3 + 1) * 3, i2 = (idx ? idx[k * 3 + 2] : k * 3 + 2) * 3;
      a.set(pos[i0], pos[i0 + 1], pos[i0 + 2]).applyMatrix4(M); b.set(pos[i1], pos[i1 + 1], pos[i1 + 2]).applyMatrix4(M); c.set(pos[i2], pos[i2 + 1], pos[i2 + 2]).applyMatrix4(M);
      nn.copy(b).sub(a).cross(c.clone().sub(a)).normalize();
      dv.setFloat32(off, nn.x, true); dv.setFloat32(off + 4, nn.y, true); dv.setFloat32(off + 8, nn.z, true); off += 12;
      for (const v of [a, b, c]) { dv.setFloat32(off, v.x, true); dv.setFloat32(off + 4, v.y, true); dv.setFloat32(off + 8, v.z, true); off += 12; }
      dv.setUint16(off, 0, true); off += 2;
    }
  }
  return { buffer: buf, triangles: count };
}

// Yukarı ekseni tahmini: CAD modelinde en kısa boyut yukarıdır (dron: kanat X, boy Y, yükseklik Z) → three Y-yukarı sahneye döndür
function orientUp(T, obj) {
  const box = new T.Box3().setFromObject(obj), size = box.getSize(new T.Vector3());
  const wrap = new T.Group(); wrap.add(obj);
  if (size.z < size.y && size.z < size.x) wrap.rotation.x = -Math.PI / 2;        // Z yukarı → Y
  else if (size.x < size.y && size.x < size.z) wrap.rotation.z = Math.PI / 2;    // X yukarı → Y
  return wrap;
}

// Sahne kur (ışıklar, kadraj): obj → { scene, camera, pivot, radius, dist }
function stage(T, obj, { fov = 38, aspect = 4 / 3, bg = null } = {}) {
  const scene = new T.Scene();
  if (bg != null) scene.background = new T.Color(bg);
  scene.add(new T.AmbientLight(0xffffff, 0.7));
  const d1 = new T.DirectionalLight(0xffffff, 0.9); d1.position.set(1, 1.2, 0.8); scene.add(d1);
  const d2 = new T.DirectionalLight(0xffffff, 0.35); d2.position.set(-1, -0.4, -1); scene.add(d2);
  const pivot = orientUp(T, obj);
  pivot.updateMatrixWorld(true);
  const box = new T.Box3().setFromObject(pivot), size = box.getSize(new T.Vector3()), center = box.getCenter(new T.Vector3());
  const inner = new T.Group(); inner.add(pivot); pivot.position.sub(center);   // merkez (0,0,0)
  scene.add(inner);
  const radius = Math.max(size.x, size.y, size.z, 1e-6) * 0.5;
  const dist = radius / Math.tan((fov * Math.PI / 180) / 2) * 1.15;
  const camera = new T.PerspectiveCamera(fov, aspect, Math.max(dist / 1000, 1e-4), dist * 100);
  camera.position.set(dist * 0.72, dist * 0.5, dist * 0.72); camera.lookAt(0, 0, 0);   // 3/4 açı
  return { scene, camera, pivot: inner, radius, dist };
}

// 3/4 açıdan şeffaf PNG (480×360)
async function snapshotPng(T, root, w = 480, hh = 360) {
  const r = new T.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  r.setPixelRatio(1); r.setSize(w, hh); r.setClearColor(0x000000, 0);
  const { scene, camera } = stage(T, root, { aspect: w / hh });
  r.render(scene, camera);
  const blob = await new Promise(res => r.domElement.toBlob(res, 'image/png'));
  scene.remove(...scene.children); r.dispose(); r.forceContextLoss?.();
  if (!blob) throw new Error(t('Küçük resim çekilemedi'));
  return blob;
}

// ---- Üretim: STEP sürümü → STL + GLB + PNG → sunucu. onProgress({ pct, text }). Döner { preview, tris, stl, glb, ms }
async function produce(vid, onProgress) {
  const t0 = performance.now();
  const P = (pct, text) => onProgress?.({ pct: Math.round(pct), text });
  P(2, t('STEP indiriliyor…'));
  const buf = await fetchStep(vid, (r, got, total) => { if (r != null) P(2 + r * 14, t('STEP indiriliyor… {a}{b}', { a: fmtKB(got), b: total ? ` / ${fmtKB(total)}` : '' })); });
  const { T, GLTFExporter, mergeGeometries } = await loadThree();
  P(18, t('CAD çekirdeği yükleniyor…'));
  const { root, tris, deflection, bodies } = await meshStep(buf, T, mergeGeometries, txt => P(30, txt));
  P(62, t('STL yazılıyor…'));
  const stl = groupToStl(T, root);
  P(68, t('GLB yazılıyor…'));
  const glbRoot = root.clone(); glbRoot.scale.setScalar(0.001);   // GLB: metre (glTF standardı); STL mm kalır
  const glb = await new GLTFExporter().parseAsync(glbRoot, { binary: true, onlyVisible: true });
  if (!(glb instanceof ArrayBuffer)) throw new Error(t('GLB üretilemedi'));
  P(76, t('Küçük resim çekiliyor…'));
  const png = await snapshotPng(T, root);
  root.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); });
  const url = k => `/api/design/versions/${vid}/preview?kind=${k}`;
  P(80, t('Sunucuya yükleniyor…'));
  await putBinary(url('stl'), stl.buffer, 'application/octet-stream', p => P(80 + p * 0.1, t('Sunucuya yükleniyor… STL %{p}', { p })));
  await putBinary(url('glb'), glb, 'application/octet-stream', p => P(90 + p * 0.08, t('Sunucuya yükleniyor… GLB %{p}', { p })));
  const r = await putBinary(url('thumb'), png, 'image/png');
  P(100, t('Önizleme hazır'));
  return { preview: r.preview, tris, deflection, bodies, stl: stl.buffer.byteLength, glb: glb.byteLength, ms: Math.round(performance.now() - t0) };
}

// Kuyruk: aynı sürüm için tek iş (dinleyiciler eklenir), farklı sürümler sırayla (bellek: tek CAD çözümlemesi)
const jobs = new Map();   // vid → { p, listeners }
let chain = Promise.resolve();
export function ensurePreview(vid, onProgress) {
  const j = jobs.get(vid);
  if (j) { if (onProgress) j.listeners.push(onProgress); return j.p; }
  const listeners = onProgress ? [onProgress] : [];
  const notify = s => listeners.forEach(fn => { try { fn(s); } catch { /* */ } });
  const p = chain.then(() => produce(vid, notify));
  chain = p.catch(() => {});
  jobs.set(vid, { p, listeners });
  p.catch(() => {}).finally(() => jobs.delete(vid));
  return p;
}
export const previewBusy = vid => jobs.has(vid);

// ---- Hızlı GLB görüntüleyici: el (ölçülü kutu), url. autoRotate: kendi etrafında döner; interactive: OrbitControls. → { dispose, resize, fit }
// fps: kart canlı görünümünde kare sınırı (CPU tasarrufu; sekme gizliyken durur); pencerede sınırsız.
export async function glbView(el, url, { autoRotate = true, interactive = false, bg = null, speed = 0.6, fps = 0 } = {}) {
  const { T, GLTFLoader, OrbitControls } = await loadThree();
  const gltf = await new Promise((res, rej) => new GLTFLoader().load(url, res, undefined, rej));
  const W = el.clientWidth || 320, H = el.clientHeight || 240;
  const r = new T.WebGLRenderer({ antialias: true, alpha: bg == null });
  r.setPixelRatio(Math.min(devicePixelRatio || 1, interactive ? 2 : 1.5)); r.setSize(W, H);
  if (bg == null) r.setClearColor(0x000000, 0);
  el.replaceChildren(r.domElement);
  const { scene, camera, pivot, dist } = stage(T, gltf.scene, { aspect: W / H, bg });
  let controls = null;
  if (interactive) { controls = new OrbitControls(camera, r.domElement); controls.enableDamping = true; controls.autoRotate = autoRotate; controls.autoRotateSpeed = speed * 3; }
  let alive = true, raf = null, last = performance.now(), lastDraw = 0;
  const minGap = fps > 0 ? 1000 / fps : 0;
  const tick = now => {
    if (!alive) return;
    raf = requestAnimationFrame(tick);
    if (document.hidden || (minGap && now - lastDraw < minGap)) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now; lastDraw = now;
    if (controls) controls.update(); else if (autoRotate) pivot.rotation.y += speed * dt;
    r.render(scene, camera);
  };
  raf = requestAnimationFrame(tick);
  const resize = () => { const w = el.clientWidth || W, hh = el.clientHeight || H; camera.aspect = w / hh; camera.updateProjectionMatrix(); r.setSize(w, hh); };
  window.addEventListener('resize', resize);
  return {
    resize,
    fit() { camera.position.set(dist * 0.72, dist * 0.5, dist * 0.72); camera.lookAt(0, 0, 0); controls?.target.set(0, 0, 0); controls?.update(); },
    dispose() { alive = false; if (raf) cancelAnimationFrame(raf); window.removeEventListener('resize', resize); controls?.dispose(); scene.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); }); r.dispose(); r.domElement.remove(); },
  };
}

// Pencerede büyük görüntüleyici (OrbitControls, kadraj düğmesi, STL indirme)
export function openGlbModal({ name, glbUrl, stlUrl = null, stlName = 'model.stl', canDownload = false }) {
  const box = h('div', { class: 'dz-glb-stage' }, h('div', { class: 'small muted dz-glb-wait' }, t('3B model yükleniyor…')));
  const hint = h('div', { class: 'small muted' }, t('Sürükle: döndür · tekerlek: yaklaştır · sağ tuş: kaydır'));
  let v = null;
  const fitBtn = h('button', { class: 'btn sm ghost', type: 'button', onclick: () => v?.fit() }, '⌖ ' + t('Kadraj'));
  const dl = canDownload && stlUrl ? h('a', { class: 'btn sm', href: `${stlUrl}&dl=1`, download: stlName }, '⬇ ' + t('STL indir')) : null;
  const dlg = modal({ title: t('{name} · Hızlı 3B önizleme', { name }), wide: true, body: h('div', { class: 'dz-glb-modal' }, box, h('div', { class: 'dz-glb-bar' }, hint, h('span', { class: 'spacer' }), dl, fitBtn)),
    actions: [{ label: t('Kapat') }], onClose: () => v?.dispose() });
  glbView(box, glbUrl, { autoRotate: true, interactive: true, bg: 0xeef3fb }).then(x => { v = x; }).catch(err => box.replaceChildren(h('div', { class: 'card empty' }, t('3B model yüklenemedi') + ': ' + (err?.message || err))));
  return dlg;
}

// Kart üstü canlı 3B: fare gelince dönen GLB, çıkınca kaldır (dokunmatikte "3B görüntüle" düğmesi pencereyi açar)
export function liveOnHover(thumbEl, getGlbUrl) {
  let v = null, layer = null, enterT = null;
  const stop = () => { clearTimeout(enterT); enterT = null; v?.dispose(); v = null; layer?.remove(); layer = null; };
  thumbEl.addEventListener('mouseenter', () => {
    const url = getGlbUrl(); if (!url || v || layer) return;
    enterT = setTimeout(async () => {
      layer = h('div', { class: 'dz-live' }); thumbEl.append(layer);
      try { const x = await glbView(layer, url, { autoRotate: true, interactive: false, fps: 30 }); if (!layer) { x.dispose(); return; } v = x; layer.classList.add('on'); }
      catch { layer?.remove(); layer = null; }
    }, 180);
  });
  thumbEl.addEventListener('mouseleave', stop);
  return stop;
}
