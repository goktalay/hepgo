// STEP (.step/.stp) 3B önizleme: occt-import-js (OpenCascade WASM) ile STEP → mesh, three.js ile gösterim.
// Ağır kütüphaneler (three + ~7MB CAD çekirdeği) yalnızca bir STEP açılınca tembel yüklenir.
import { loadLibs } from './gcode3d.js';   // [THREE, { OrbitControls }]

const OCCT = '/static/vendor/occt/';
let occtPromise = null;
function loadOcct() {
  if (!occtPromise) occtPromise = import(OCCT + 'occt-import-js.js').then(m => m.default({ locateFile: n => OCCT + n }));
  return occtPromise;
}

// container: boş bir DOM düğümü (ölçüsü olmalı). arrayBuffer: STEP dosyası. → { dispose() }
export async function viewStep(container, arrayBuffer) {
  const [THREE, { OrbitControls }] = await loadLibs();
  const occt = await loadOcct();
  const res = occt.ReadStepFile(new Uint8Array(arrayBuffer), null);
  if (!res || !res.success || !res.meshes || !res.meshes.length) throw new Error('STEP dosyası okunamadı ya da geometri yok.');

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
  for (const mesh of res.meshes) {
    const pos = mesh.attributes?.position?.array;
    if (!pos || !pos.length) continue;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(Float32Array.from(pos), 3));
    if (mesh.attributes.normal?.array?.length) g.setAttribute('normal', new THREE.Float32BufferAttribute(Float32Array.from(mesh.attributes.normal.array), 3));
    if (mesh.index?.array?.length) g.setIndex(Array.from(mesh.index.array));
    if (!mesh.attributes.normal?.array?.length) g.computeVertexNormals();
    const c = mesh.color && mesh.color.length === 3 ? new THREE.Color(mesh.color[0], mesh.color[1], mesh.color[2]) : new THREE.Color(0x9aa8bd);
    group.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: c, metalness: 0.25, roughness: 0.65, side: THREE.DoubleSide })));
  }
  scene.add(group);

  // Kadrajı geometriye göre ortala ve uzaklığı ayarla
  const box = new THREE.Box3().setFromObject(group);
  const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
  group.position.sub(center);
  const radius = Math.max(size.x, size.y, size.z, 1) * 0.5;
  const dist = radius / Math.tan((camera.fov * Math.PI / 180) / 2) * 1.6;
  camera.position.set(dist * 0.8, dist * 0.6, dist);
  camera.near = Math.max(dist / 1000, 0.01); camera.far = dist * 100; camera.updateProjectionMatrix();
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.target.set(0, 0, 0); controls.update();

  let raf = null, alive = true;
  const tick = () => { if (!alive) return; controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(tick); };
  tick();
  const onResize = () => { const w = container.clientWidth || W, hh = container.clientHeight || H; camera.aspect = w / hh; camera.updateProjectionMatrix(); renderer.setSize(w, hh); };
  window.addEventListener('resize', onResize);

  return {
    dispose() {
      alive = false; if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      try { group.traverse(o => { o.geometry?.dispose?.(); o.material?.dispose?.(); }); renderer.dispose(); renderer.domElement.remove(); } catch { /* */ }
    },
  };
}

export const isStep = name => /\.(step|stp)$/i.test(name || '');
