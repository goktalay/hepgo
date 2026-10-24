// Karşılaşma parkuru İÇİNDEN GÖRÜNTÜ (yol haritası "Parkur › Karşılaşma Parkurları": yalnız gösterim): sunucunun parkur tanımından
// (GET /api/fpv/courses/{id}: zemin, engeller, dekor, kapılar, yarış hattı) hafif three.js sahnesi; kamera yarış hattı boyunca süzülür.
// Paylaşılan tek WebGL çizici (core/three.js makeStage) — kart başına bağlam açılmaz. Koordinat: parkur x doğu, y kuzey, z yukarı → three (x, z, −y).
import { loadThree, makeStage } from '../core/three.js';

const GROUND = { forest: 0x2f4a24, meadow: 0x4c7a33, dirt: 0x6b5236, asphalt: 0x2b2f36, concrete: 0x77797c, turf: 0x2f7d3a, industrial: 0x444a50, rock: 0x6d6258 };
const MAT = { frame: 0xff6a00, pole: 0xd1d5db, log: 0x6b4423, bush: 0x2f6b2a, rock: 0x7c7268, concrete: 0x9ca3af, steel: 0x94a3b8, wood: 0x9a6b3d, net: 0xe5e7eb,
  tree: 0x285d22, leaf: 0x2e7d32, crate: 0xa16207, tire: 0x1f2937, container: 0x2563eb, pipe: 0x9ca3af, flag: 0xef4444, light: 0xfef08a };
const SKY = { day: 0x9cc6ef, dusk: 0xf0a36a, night: 0x0b1530 };

/** Yarış hattı → düz nokta dizisi (saf; test edilir). */
export function flatLine(line) { const out = []; for (const seg of line || []) for (const p of seg || []) { const l = out[out.length - 1]; if (!l || Math.hypot(l[0] - p[0], l[1] - p[1], l[2] - p[2]) > 0.05) out.push(p); } return out; }
/** Kümülatif uzunlukta konum (saf). */
export function pointAt(pts, s) {
  if (!pts.length) return [0, 0, 2];
  let acc = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], d = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    if (acc + d >= s) { const k = d ? (s - acc) / d : 0; return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k]; }
    acc += d;
  }
  return pts[pts.length - 1];
}
export const lineLength = pts => pts.reduce((s, p, i) => (i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1], p[2] - pts[i - 1][2]) : 0), 0);

export async function courseFlythrough(host, course, { speed = 9 } = {}) {
  const lib = await loadThree();
  const { THREE } = lib;
  const pts = flatLine(course.line);
  const L = Math.max(1, lineLength(pts));
  let s = Math.random() * L;
  const v3 = p => new THREE.Vector3(p[0], p[2], -p[1]);
  const stage = makeStage(lib, host, { fov: 70, near: 0.1, far: 1500, env: false, pixelRatioMax: 1.25, onFrame: dt => {
    s = (s + dt * speed) % L;
    const p = pointAt(pts, s), q = pointAt(pts, (s + 7) % L);
    stage.camera.position.copy(v3([p[0], p[1], p[2] + 1.2]));
    stage.camera.lookAt(v3([q[0], q[1], q[2] + 0.8]));
    for (const g of glows) g.material.opacity = 0.55 + 0.35 * Math.sin(performance.now() / 300 + g.userData.k);
  } });
  const env = course.env || {};
  const sc = stage.scene;
  sc.background = new THREE.Color(SKY[env.time] || SKY.day);
  sc.fog = new THREE.Fog(sc.background, 25, 120 + (1 - (env.fog || 0.2)) * 160);
  sc.add(new THREE.HemisphereLight(0xffffff, 0x334155, env.time === 'night' ? 0.5 : 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, env.time === 'night' ? 0.3 : 1.1); sun.position.set(40, 80, 30); sc.add(sun);
  const [gw, gd] = env.size || [200, 200];
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(gw * 1.6, gd * 1.6), new THREE.MeshStandardMaterial({ color: GROUND[env.ground] || 0x4c7a33, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; sc.add(ground);
  const mats = new Map();
  const mat = k => { if (!mats.has(k)) mats.set(k, new THREE.MeshStandardMaterial({ color: MAT[k] ?? 0x9ca3af, roughness: 0.8, metalness: k === 'steel' || k === 'pipe' ? 0.5 : 0 })); return mats.get(k); };
  const add = o => {
    let m = null;
    if (o.t === 'box') { m = new THREE.Mesh(new THREE.BoxGeometry(o.w, o.h, o.d), mat(o.mat)); m.position.copy(v3([o.x, o.y, (o.z || 0) + o.h / 2])); m.rotation.y = -(o.yaw || 0) * Math.PI / 180; }
    else if (o.t === 'cyl') { m = new THREE.Mesh(new THREE.CylinderGeometry(o.r, o.r, o.h, 10), mat(o.mat)); m.position.copy(v3([o.x, o.y, (o.z || 0) + o.h / 2])); }
    else if (o.t === 'sph') { m = new THREE.Mesh(new THREE.SphereGeometry(o.r, 10, 8), mat(o.mat)); m.position.copy(v3([o.x, o.y, o.z || 0])); }
    else if (o.t === 'torus') { m = new THREE.Mesh(new THREE.TorusGeometry(o.R, o.tube, 8, 32), mat(o.mat || 'frame')); m.position.copy(v3([o.x, o.y, o.z])); m.rotation.y = -(o.yaw || 0) * Math.PI / 180; }
    else if (o.t === 'pipe') {
      const a = v3(o.a), b = v3(o.b), len = a.distanceTo(b);
      m = new THREE.Mesh(new THREE.CylinderGeometry(o.r, o.r, len, 10), mat(o.mat)); m.position.copy(a.clone().add(b).multiplyScalar(0.5));
      m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    }
    if (m) sc.add(m);
  };
  (course.obstacles || []).forEach(add);
  (course.decor || []).slice(0, 600).forEach(add);
  const glows = [];
  (course.gates || []).forEach((g, k) => {   // neon kapı ağzı
    const geo = g.kind === 'circle' ? new THREE.TorusGeometry((g.r ?? g.w / 2) || 1.5, 0.06, 6, 40) : new THREE.EdgesGeometry(new THREE.PlaneGeometry(g.w, g.h));
    const mm = new THREE.MeshBasicMaterial({ color: g.kind === 'start' ? 0x22d3ee : 0xff8a1f, transparent: true, opacity: 0.8 });
    const o = g.kind === 'circle' ? new THREE.Mesh(geo, mm) : new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: mm.color, transparent: true, opacity: 0.85 }));
    o.position.copy(v3([g.x, g.y, g.z])); o.rotation.y = -((g.yaw || 0) + 90) * Math.PI / 180; o.userData.k = k;
    glows.push(o); sc.add(o);
  });
  stage.start();
  return { dispose: () => stage.dispose(), stage };
}
