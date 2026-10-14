// 3B CFD sonuç görselleştirme (OpenFOAM çıktıları): gövde yüzeyi (Cp / kayma gerilmesi / y+), kesit düzlemleri (|U|/U∞, Cp),
// akım çizgileri (hıza göre renk). Veri: /api/design/cfd/<id>/file?name=… ikili paketleri — [u32 n][json başlık][f32 xyz…][f32 alan…].
import { loadLibs } from './gcode3d.js';

export function heat(t) {   // mavi → cyan → yeşil → sarı → kırmızı
  t = Math.max(0, Math.min(1, t));
  const s = [[0.12, 0.2, 0.6], [0.0, 0.6, 0.9], [0.15, 0.8, 0.35], [0.95, 0.85, 0.15], [0.85, 0.15, 0.1]];
  const p = t * 4, i = Math.min(3, Math.floor(p)), k = p - i;
  return [s[i][0] + (s[i + 1][0] - s[i][0]) * k, s[i][1] + (s[i + 1][1] - s[i][1]) * k, s[i][2] + (s[i + 1][2] - s[i][2]) * k];
}

export async function fetchBundle(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (!r.ok) throw new Error('Sonuç dosyası alınamadı');
  const buf = await r.arrayBuffer();
  const dv = new DataView(buf), hl = dv.getUint32(0, true);
  const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
  let off = 4 + hl;
  const pos = new Float32Array(buf.slice(off, off + head.n * 12)); off += head.n * 12;
  const fields = {};
  for (const f of head.fields) { fields[f] = new Float32Array(buf.slice(off, off + head.n * 4)); off += head.n * 4; }
  return { head, pos, fields };
}

// Renk aralığı: yüzdelik (uç değerleri kırp) → [lo, hi]
function range(arr, lo = 0.02, hi = 0.98) {
  if (!arr || !arr.length) return [0, 1];
  const a = Float32Array.from(arr).sort();
  return [a[Math.floor(lo * (a.length - 1))], a[Math.floor(hi * (a.length - 1))]];
}

export async function createCfdViz(container, { legend } = {}) {
  const [THREE, { OrbitControls }] = await loadLibs();
  const W = container.clientWidth || 600, H = container.clientHeight || 420;
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0xf3f6fb);
  const camera = new THREE.PerspectiveCamera(40, W / H, 0.001, 1000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(W, H);
  container.replaceChildren(renderer.domElement);
  scene.add(new THREE.AmbientLight(0xffffff, 0.85));
  const dl = new THREE.DirectionalLight(0xffffff, 0.7); dl.position.set(1, 1, 2); scene.add(dl);
  const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
  const group = new THREE.Group(); scene.add(group);
  const layers = {};   // name → Object3D
  let raf = null, alive = true;
  const tick = () => { if (!alive) return; controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
  tick();
  const onResize = () => { const w = container.clientWidth || W, h = container.clientHeight || H; camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h); };
  window.addEventListener('resize', onResize);

  const colorize = (geom, values, [lo, hi]) => {
    const col = new Float32Array(values.length * 3);
    for (let i = 0; i < values.length; i++) { const c = heat((values[i] - lo) / ((hi - lo) || 1)); col[i * 3] = c[0]; col[i * 3 + 1] = c[1]; col[i * 3 + 2] = c[2]; }
    geom.setAttribute('color', new THREE.BufferAttribute(col, 3));
  };
  const drawLegend = (title, [lo, hi], unit = '') => {
    if (!legend) return;
    const c = legend; c.width = 260; c.height = 44; const g = c.getContext('2d');
    g.clearRect(0, 0, c.width, c.height);
    for (let x = 0; x < 200; x++) { const k = heat(x / 199); g.fillStyle = `rgb(${k[0] * 255 | 0},${k[1] * 255 | 0},${k[2] * 255 | 0})`; g.fillRect(30 + x, 6, 1, 12); }
    g.fillStyle = '#334155'; g.font = '11px system-ui, sans-serif';
    g.fillText(`${lo.toFixed(2)}${unit}`, 0, 32); g.textAlign = 'right'; g.fillText(`${hi.toFixed(2)}${unit}`, 232, 32); g.textAlign = 'center'; g.fillText(title, 130, 42);
  };

  const fit = () => {
    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const rad = Math.max(size.x, size.y, size.z) * 0.5, d = rad / Math.tan((camera.fov * Math.PI / 180) / 2) * 1.3;
    camera.position.set(center.x - d * 0.55, center.y - d * 0.75, center.z + d * 0.45); controls.target.copy(center);
    camera.near = d / 500; camera.far = d * 50; camera.updateProjectionMatrix(); controls.update();
  };
  const bodyBox = () => layers.body ? new THREE.Box3().setFromObject(layers.body) : null;
  const fitBody = () => {
    const box = bodyBox(); if (!box) return fit();
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const rad = Math.max(size.x, size.y, size.z) * 0.5, d = rad / Math.tan((camera.fov * Math.PI / 180) / 2) * 1.6;
    camera.position.set(center.x - d * 0.6, center.y - d * 0.7, center.z + d * 0.45); controls.target.copy(center);
    camera.near = d / 500; camera.far = d * 80; camera.updateProjectionMatrix(); controls.update();
  };

  const state = { bundles: {}, field: { body: 'Cp', slice: 'Umag' } };
  const clearLayer = name => { const o = layers[name]; if (o) { group.remove(o); o.traverse(x => { x.geometry?.dispose?.(); x.material?.dispose?.(); }); delete layers[name]; } };
  const addSurface = (name, b, field, opacity = 1) => {
    clearLayer(name);
    const geom = new THREE.BufferGeometry(); geom.setAttribute('position', new THREE.BufferAttribute(b.pos, 3)); geom.computeVertexNormals();
    const vals = b.fields[field] || new Float32Array(b.head.n);
    const rg = range(vals); colorize(geom, vals, rg);
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, metalness: 0.05, roughness: 0.8, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 });
    const mesh = new THREE.Mesh(geom, mat); mesh.name = name; group.add(mesh); layers[name] = mesh;
    return rg;
  };
  const addLines = (name, b, field) => {
    clearLayer(name);
    const geom = new THREE.BufferGeometry(); geom.setAttribute('position', new THREE.BufferAttribute(b.pos, 3));
    const vals = b.fields[field] || new Float32Array(b.head.n); colorize(geom, vals, range(vals, 0.01, 0.99));
    const lines = new THREE.LineSegments(geom, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 }));
    lines.name = name; group.add(lines); layers[name] = lines;
  };

  return {
    async load(base, meta) {
      const files = meta.files || {};
      state.bundles = {};
      for (const key of ['body', 'slice_side', 'slice_top', 'lines']) {
        if (!files[key]) continue;
        try { state.bundles[key] = await fetchBundle(`${base}&name=${files[key]}`); } catch { /* eksik dosya */ }
      }
      this.rebuild(); fitBody();
      return Object.keys(state.bundles);
    },
    rebuild() {
      const b = state.bundles;
      let bodyRange = null;
      if (b.body) bodyRange = addSurface('body', b.body, state.field.body);
      if (b.slice_side) addSurface('slice_side', b.slice_side, state.field.slice, 0.85);
      if (b.slice_top) addSurface('slice_top', b.slice_top, state.field.slice, 0.85);
      if (b.lines) addLines('lines', b.lines, 'Umag');
      if (bodyRange) drawLegend({ Cp: 'Gövde: basınç katsayısı Cp', wallShearStress: 'Gövde: duvar kayma gerilmesi (Pa)', yPlus: 'Gövde: y+' }[state.field.body] || state.field.body, bodyRange);
    },
    setField(kind, name) { state.field[kind] = name; this.rebuild(); },
    show(name, on) { if (layers[name]) layers[name].visible = on; },
    has(name) { return !!state.bundles[name]; },
    fit, fitBody, resize: onResize,
    dispose() { alive = false; if (raf) cancelAnimationFrame(raf); window.removeEventListener('resize', onResize); Object.keys(layers).forEach(clearLayer); renderer.dispose(); renderer.domElement.remove(); },
  };
}
