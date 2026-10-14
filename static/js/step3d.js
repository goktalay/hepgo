// STEP (.step/.stp) 3B önizleme: occt-import-js (OpenCascade WASM) ile STEP → mesh, three.js ile gösterim.
// Ağır kütüphaneler (three + ~7MB CAD çekirdeği) yalnızca bir STEP açılınca tembel yüklenir.
// Montaj görünümü: STEP içindeki parça ağacı (buildStepTree), parça seçimi/vurgusu (select), patlatma (explode 0–1).
import { loadLibs } from './gcode3d.js';   // [THREE, { OrbitControls }]

const OCCT = '/static/vendor/occt/';
let occtPromise = null;
function loadOcct() {
  if (!occtPromise) occtPromise = import(OCCT + 'occt-import-js.js').then(m => m.default({ locateFile: n => OCCT + n }));
  return occtPromise;
}

// STEP parça anahtarı: ad (sadeleştirilmiş) — sürümler arasında aynı kalır; adsız parçada yol indeksi
export const meshKey = (name, path) => {
  const n = (name || '').trim().replace(/\s+/g, ' ');
  return n ? `n:${n.toLocaleLowerCase('tr')}` : `p:${path}`;
};

// occt sonucu → montaj ağacı. Düğüm: {key, name, path, depth, kind:'group'|'part', meshes:[idx], allMeshes:[idx…], children, parent}
// STEP içindeki alt montajlar (çocuklu düğüm) ve birden çok gövdeli düğümler (ör. "caymaz - v3 part 2": 30 mesh, her birinin adı var)
// grup olur; her gövde (mesh) kendi adıyla ayrı parça olarak gruba girer. Tek gövdeli düğüm doğrudan parçadır.
// Döner: { root, nodes: kök dışındaki tüm düğümler (ağaç sırasında), flat: yalnız yaprak parçalar }
export function buildStepTree(res) {
  const clean = s => (s || '').replace(/[\r\n]+/g, '').replace(/\s+/g, ' ').trim();   // STEP adlarında kaçan satır sonları ("ELEKTRONİK KATMA\rN")
  const meshName = i => clean(res.meshes?.[i]?.name);
  const walk = (node, path) => {
    const meshes = (node.meshes || []).slice();
    const kids = (node.children || []).map((c, i) => walk(c, path ? `${path}/${i}` : String(i)));
    const item = { name: clean(node.name), path, children: kids, meshes: [], allMeshes: [], kind: 'part' };
    if (meshes.length === 1 && !kids.length) item.meshes = meshes;
    else if (meshes.length) {   // çok gövdeli düğüm = alt montaj; gövdeler ayrı parça
      item.kind = 'group';
      meshes.forEach((mi, j) => item.children.push({ name: meshName(mi) || `${item.name || 'Grup'} · gövde ${j + 1}`, path: `${path}/m${j}`, children: [], meshes: [mi], allMeshes: [mi], kind: 'part' }));
    } else if (kids.length) item.kind = 'group';
    item.allMeshes = [...item.meshes, ...item.children.flatMap(k => k.allMeshes)];
    return item;
  };
  let root = walk(res.root || { children: [] }, '');
  root.children = root.children.filter(c => c.allMeshes.length);
  // Boş sarmalayıcı kökler (adsız kök → tek alt montaj) atlanır; en üstteki gerçek montaj kök olur
  while (!root.meshes.length && root.children.length === 1 && root.children[0].kind === 'group') root = root.children[0];
  root.name = root.name || 'Montaj'; root.depth = 0; root.parent = null;
  const nodes = [], flat = [];
  const collect = (n, depth) => {
    n.children = n.children.filter(c => c.allMeshes.length);
    for (const c of n.children) {
      c.depth = depth; c.parent = n; c.key = meshKey(c.name, c.path); if (c.kind === 'group') c.key = 'g' + c.key.slice(1);
      nodes.push(c); if (c.kind === 'part') flat.push(c);
      collect(c, depth + 1);
    }
  };
  collect(root, 1);
  // Aynı adlı parçalar (ör. 4 × "AT"): sıra numarasıyla benzersiz anahtar — sürümler arasında sıra aynı kaldığı sürece eşleşme korunur
  const seen = {};
  for (const p of nodes) {
    const n = (seen[p.key] = (seen[p.key] || 0) + 1);
    if (n > 1) { p.key = `${p.key}#${n}`; p.dupIndex = n; }
  }
  return { root, nodes, flat };
}

// container: boş DOM düğümü (ölçülü). arrayBuffer: STEP. opts.onSelect(node|null). → { root, nodes, parts, select(node), explode(0–1), fit, dispose }
export async function viewStep(container, arrayBuffer, opts = {}) {
  const [THREE, { OrbitControls }] = await loadLibs();
  const occt = await loadOcct();
  const res = occt.ReadStepFile(new Uint8Array(arrayBuffer), null);
  if (!res || !res.success || !res.meshes || !res.meshes.length) throw new Error('STEP dosyası okunamadı ya da geometri yok.');
  const tree = buildStepTree(res);

  const W = container.clientWidth || 560, H = container.clientHeight || 420;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeef3fb);
  const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 1e6);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  container.appendChild(renderer.domElement);
  scene.add(new THREE.AmbientLight(0xffffff, 0.75));
  const d1 = new THREE.DirectionalLight(0xffffff, 0.8); d1.position.set(1, 1, 1); scene.add(d1);
  const d2 = new THREE.DirectionalLight(0xffffff, 0.4); d2.position.set(-1, -0.5, -1); scene.add(d2);

  const group = new THREE.Group();
  const meshObjs = [];   // index = occt mesh index
  res.meshes.forEach((mesh, i) => {
    const pos = mesh.attributes?.position?.array;
    if (!pos || !pos.length) { meshObjs[i] = null; return; }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(Float32Array.from(pos), 3));
    if (mesh.attributes.normal?.array?.length) g.setAttribute('normal', new THREE.Float32BufferAttribute(Float32Array.from(mesh.attributes.normal.array), 3));
    if (mesh.index?.array?.length) g.setIndex(Array.from(mesh.index.array));
    if (!mesh.attributes.normal?.array?.length) g.computeVertexNormals();
    g.computeBoundingBox();
    const c = mesh.color && mesh.color.length === 3 ? new THREE.Color(mesh.color[0], mesh.color[1], mesh.color[2]) : new THREE.Color(0x9aa8bd);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: c, metalness: 0.25, roughness: 0.65, side: THREE.DoubleSide }));
    m.userData = { idx: i, name: mesh.name || '', baseColor: c.clone(), center: g.boundingBox.getCenter(new THREE.Vector3()) };
    group.add(m); meshObjs[i] = m;
  });
  scene.add(group);

  // Kadraj: geometriyi ortala, uzaklığı ayarla
  const box = new THREE.Box3().setFromObject(group);
  const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
  group.position.sub(center);
  const radius = Math.max(size.x, size.y, size.z, 1) * 0.5;
  const dist = radius / Math.tan((camera.fov * Math.PI / 180) / 2) * 1.6;
  const fit = () => { camera.position.set(dist * 0.8, dist * 0.6, dist); controls.target.set(0, 0, 0); controls.update(); };
  camera.near = Math.max(dist / 1000, 0.01); camera.far = dist * 100; camera.updateProjectionMatrix();
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; fit();

  // ---- seçim / vurgu
  let selected = null;
  const HI = new THREE.Color(0xf97316), DIM = 0.35;
  const meshesOf = part => (part ? part.allMeshes : []).map(i => meshObjs[i]).filter(Boolean);
  const paint = () => {
    const sel = new Set(meshesOf(selected).map(m => m.userData.idx));
    meshObjs.forEach(m => {
      if (!m) return;
      const on = sel.has(m.userData.idx);
      m.material.color.copy(on ? HI : m.userData.baseColor);
      m.material.emissive.setHex(on ? 0x7c2d12 : 0x000000);
      m.material.transparent = !!selected && !on; m.material.opacity = selected && !on ? DIM : 1;
      m.material.needsUpdate = true;
    });
  };
  const select = part => { selected = part || null; paint(); opts.onSelect?.(selected); };

  // ---- patlatma (hiyerarşik): alt montaj kendi merkezinden montaj merkezine göre, içindeki parçalar alt montaj merkezine göre açılır.
  // Her parça: Σ (düğüm merkezi − üst düğüm merkezi) · t · 1.5 — uzaklıklar orantılı büyür, montaj yapısı korunur.
  meshObjs.forEach(m => { if (m) m.userData.center.sub(center); });   // grup (0,0,0)'a taşındı → merkezler aynı uzaya
  const nodeCenter = new Map();
  const centerOf = n => {
    if (nodeCenter.has(n)) return nodeCenter.get(n);
    const b = new THREE.Box3();
    n.allMeshes.forEach(i => { if (meshObjs[i]) b.expandByObject(meshObjs[i]); });
    const c = b.isEmpty() ? new THREE.Vector3() : b.getCenter(new THREE.Vector3());
    nodeCenter.set(n, c); return c;
  };
  const leafOf = i => tree.flat.find(p => p.meshes.includes(i)) || null;
  meshObjs.forEach(m => { if (m) m.userData.part = leafOf(m.userData.idx); });
  centerOf(tree.root); tree.nodes.forEach(centerOf);   // başlangıç konumlarıyla (patlatmadan önce) hesapla
  const explode = t => {
    const k = Math.max(0, Math.min(1, t)) * 1.5;
    meshObjs.forEach(m => {
      if (!m) return;
      const off = new THREE.Vector3();
      for (let n = m.userData.part; n && n.parent; n = n.parent) off.add(centerOf(n).clone().sub(centerOf(n.parent)).multiplyScalar(k));
      m.position.copy(off);
    });
  };

  // ---- tıklayarak parça seçme (raycast)
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  let downAt = null;
  renderer.domElement.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(meshObjs.filter(Boolean), false)[0];
    if (!hit) { select(null); return; }
    select(hit.object.userData.part || null);
  });

  let raf = null, alive = true;
  const tick = () => { if (!alive) return; controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
  tick();
  const onResize = () => { const w = container.clientWidth || W, hh = container.clientHeight || H; camera.aspect = w / hh; camera.updateProjectionMatrix(); renderer.setSize(w, hh); };
  window.addEventListener('resize', onResize);

  return {
    tree, root: tree.root, nodes: tree.nodes, parts: tree.flat, select, explode, fit, resize: onResize,
    get selected() { return selected; },
    dispose() {
      alive = false; if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      try { group.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); }); renderer.dispose(); renderer.domElement.remove(); } catch { /* */ }
    },
  };
}

export const isStep = name => /\.(step|stp)$/i.test(name || '');
