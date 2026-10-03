// 3D maskot (Three.js, yerel kopya static/vendor/three — yalnızca 3D maskot açıkken yüklenir).
// 6 karakter tamamen koddan üretilir: parlak "vinil oyuncak" malzeme + ortam yansıması (RoomEnvironment).
// Canlılık: nefes, göz kırpma, imleci izleyen gözler/baş, numaralar (el sallama, zıplama, dönme, sallanma, dans,
// kafa şişirme + kıvılcım, eğilip bakma), durumlar (düşünüyor / konuşuyor / mutlu). Görünmezken çizim durur,
// boştayken 30 fps. Ayarlar ve sohbet başlığı için tek bir ekran dışı çizici ile anlık görüntü (PNG) üretilir.
const LIB = '/static/vendor/three/';
let libs = null;
const loadLibs = () => (libs ??= Promise.all([import(`${LIB}three.module.min.js`), import(`${LIB}RoomEnvironment.js`)])
  .then(([T, R]) => ({ T, RoomEnvironment: R.RoomEnvironment }))
  .catch(err => { libs = null; throw err; }));

export function webglOK() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch { return false; }
}

const brand = () => {
  try { return getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || '#2563eb'; } catch { return '#2563eb'; }
};

// ---------- Yapı taşları ----------
function kit(T) {
  const mat = (color, o = {}) => new T.MeshPhysicalMaterial({ color, roughness: 0.42, metalness: 0, clearcoat: 0.65, clearcoatRoughness: 0.22, ...o });
  const glow = (color, k = 1.6) => new T.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: k, roughness: 0.3 });
  const mesh = (geo, m) => new T.Mesh(geo, m);
  const sphere = (r, m, seg = 40) => mesh(new T.SphereGeometry(r, seg, Math.round(seg * 0.75)), m);
  const capsule = (r, len, m) => mesh(new T.CapsuleGeometry(r, len, 8, 20), m);
  // yuvarlatılmış kutu: küre köşeleri kutuya doğru itilir (süper-elipsoit)
  const roundBox = (w, hgt, d, m, p = 0.34) => {
    const g = new T.SphereGeometry(1, 48, 36);
    const pos = g.attributes.position;
    const f = v => Math.sign(v) * Math.abs(v) ** p;
    for (let i = 0; i < pos.count; i++) pos.setXYZ(i, f(pos.getX(i)) * w / 2, f(pos.getY(i)) * hgt / 2, f(pos.getZ(i)) * d / 2);
    g.computeVertexNormals();
    return mesh(g, m);
  };
  const at = (o, x = 0, y = 0, z = 0) => { o.position.set(x, y, z); return o; };
  const sc = (o, x, y = x, z = x) => { o.scale.set(x, y, z); return o; };
  const group = (...kids) => { const g = new T.Group(); kids.filter(Boolean).forEach(k => g.add(k)); return g; };
  // Göz: beyaz + bebek + parıltı; bebek grubu bakış yönüne kayar, göz grubu kırpışta y'de ezilir
  const eye = (r, { pupil = '#1d2433', white = true, pupilScale = 0.62 } = {}) => {
    const glint = at(sphere(r * 0.2, new T.MeshBasicMaterial({ color: '#ffffff' }), 12), r * 0.24, r * 0.28, r * (white ? 0.74 : 0.62));
    const p = sc(sphere(r * (white ? pupilScale : 1), mat(pupil, { roughness: 0.12, clearcoat: 1 }), 28), 1, 1, white ? 0.5 : 0.62);
    if (white) p.position.z = r * 0.42;
    const pg = group(p, glint);
    const g = group(white ? sc(sphere(r, mat('#ffffff', { roughness: 0.18, clearcoat: 1 }), 32), 1, 1, 0.62) : null, pg);
    return { g, pupil: pg, r };
  };
  // Gülümseme (yay) + konuşurken açılan ağız
  const smile = (r, color = '#2a2230', tube = 0.022) => {
    const m = mesh(new T.TorusGeometry(r, tube, 10, 28, Math.PI * 0.8), mat(color, { roughness: 0.5 }));
    m.rotation.z = Math.PI + Math.PI * 0.1;
    return m;
  };
  const mouth = (w, color = '#3a1f2b') => {
    const m = sc(sphere(w, mat(color, { roughness: 0.55, clearcoat: 0.3 }), 24), 1, 0.55, 0.45);
    m.visible = false;
    return m;
  };
  const cheek = r => { const c = sc(sphere(r, new T.MeshStandardMaterial({ color: '#ff8fa3', transparent: true, opacity: 0.45, roughness: 1 }), 16), 1, 0.62, 0.3); return c; };
  return { mat, glow, mesh, sphere, capsule, roundBox, at, sc, group, eye, smile, mouth, cheek };
}

// Kol: omuzda dönen eksen (pivot) + aşağı sarkan kapsül + el
function arm(T, k, side, { x, y, len = 0.42, r = 0.14, color, hand }) {
  const pivot = new T.Group();
  pivot.position.set(side * x, y, 0);
  const a = k.at(k.capsule(r, len, k.mat(color)), 0, -(len / 2 + r * 0.6), 0);
  pivot.add(a);
  if (hand) pivot.add(k.at(k.sphere(r * 1.15, k.mat(hand)), 0, -(len + r * 1.2), 0));
  pivot.rotation.z = side * 0.18;
  pivot.userData.rest = side * 0.18;
  return pivot;
}

// ---------- Karakterler ----------
// Her kurucu: { root, body, head, armL, armR, eyes[], smile, mouth, tail?, glows[], float?, eyeLook }
const BUILD = {
  kubbe(T, k) {
    const shirt = brand(), skin = '#f3c39b', pants = '#2b3445';
    const body = k.group(
      k.sc(k.sphere(0.8, k.mat(shirt)), 1, 0.93, 0.9),
      k.at(k.sc(k.sphere(0.46, k.mat('#ffffff', { transparent: true, opacity: 0.18 })), 1, 0.9, 0.42), 0, -0.08, 0.6),
      k.at(k.sc(k.sphere(0.06, k.mat('#ffffff')), 1, 1, 0.5), 0, 0.22, 0.73),
      k.at(k.sc(k.sphere(0.06, k.mat('#ffffff')), 1, 1, 0.5), 0, 0.0, 0.76));
    body.position.y = 0.92;
    const legs = k.group(
      k.at(k.capsule(0.17, 0.22, k.mat(pants)), -0.3, 0.27, 0), k.at(k.capsule(0.17, 0.22, k.mat(pants)), 0.3, 0.27, 0),
      k.at(k.sc(k.sphere(0.2, k.mat('#1b1f27')), 1.05, 0.6, 1.35), -0.3, 0.08, 0.08), k.at(k.sc(k.sphere(0.2, k.mat('#1b1f27')), 1.05, 0.6, 1.35), 0.3, 0.08, 0.08));
    const eyes = [k.eye(0.12), k.eye(0.12)];
    eyes[0].g.position.set(-0.19, 0.08, 0.44); eyes[1].g.position.set(0.19, 0.08, 0.44);
    const sm = k.at(k.smile(0.14), 0, -0.13, 0.47), mo = k.at(k.mouth(0.11), 0, -0.16, 0.47);
    const hair = new T.Mesh(new T.SphereGeometry(0.545, 40, 24, 0, Math.PI * 2, 0, Math.PI * 0.4), k.mat('#4a3020', { roughness: 0.6, clearcoat: 0.3 }));
    hair.rotation.x = -0.32;
    const head = k.group(
      k.sphere(0.52, k.mat(skin)), hair,
      k.at(k.sphere(0.1, k.mat(skin)), -0.52, 0, 0), k.at(k.sphere(0.1, k.mat(skin)), 0.52, 0, 0),
      k.at(k.sc(k.sphere(0.075, k.mat('#eaa985')), 1, 0.85, 1), 0, -0.04, 0.52),
      eyes[0].g, eyes[1].g, sm, mo, k.at(k.cheek(0.1), -0.32, -0.1, 0.4), k.at(k.cheek(0.1), 0.32, -0.1, 0.4));
    head.position.y = 1.86;
    const armL = arm(T, k, -1, { x: 0.74, y: 1.22, color: shirt, hand: skin }), armR = arm(T, k, 1, { x: 0.74, y: 1.22, color: shirt, hand: skin });
    return { body, head, armL, armR, eyes, smile: sm, mouth: mo, parts: [legs] };
  },

  robo(T, k) {
    const metal = k.mat('#c7d1dd', { metalness: 0.55, roughness: 0.28, clearcoat: 0.8 });
    const dark = k.mat('#1b2230', { roughness: 0.15, clearcoat: 1 });
    const lights = [k.glow('#ff5d6c', 1.4), k.glow('#ffd166', 1.4), k.glow('#4ade80', 1.4)];
    const body = k.group(k.roundBox(1.2, 1.0, 0.86, metal), k.at(k.roundBox(0.62, 0.34, 0.1, dark), 0, 0.06, 0.42),
      ...lights.map((m, i) => k.at(k.sphere(0.05, m, 16), -0.16 + i * 0.16, 0.06, 0.48)));
    body.position.y = 0.86;
    const legs = k.group(k.at(k.capsule(0.13, 0.2, metal), -0.28, 0.26, 0), k.at(k.capsule(0.13, 0.2, metal), 0.28, 0.26, 0),
      k.at(k.roundBox(0.34, 0.16, 0.44, dark), -0.28, 0.08, 0.06), k.at(k.roundBox(0.34, 0.16, 0.44, dark), 0.28, 0.08, 0.06));
    const eyeMat = k.glow('#5ef0ff', 2.2);
    const mkEye = () => { const p = k.group(k.sc(k.sphere(0.085, eyeMat, 20), 1, 1.25, 0.5)); return { g: k.group(p), pupil: p, r: 0.085 }; };
    const eyes = [mkEye(), mkEye()];
    eyes[0].g.position.set(-0.18, 0.05, 0.43); eyes[1].g.position.set(0.18, 0.05, 0.43);
    const mo = k.at(k.sc(k.roundBox(0.22, 0.05, 0.04, k.glow('#5ef0ff', 1.6)), 1, 1, 1), 0, -0.14, 0.44);
    const antBall = k.at(k.sphere(0.07, k.glow('#ff8a3d', 2), 20), 0, 0.64, 0);
    const head = k.group(k.roundBox(0.98, 0.76, 0.8, metal), k.at(k.roundBox(0.8, 0.44, 0.1, dark), 0, 0.0, 0.37),
      eyes[0].g, eyes[1].g, mo, k.at(new T.Mesh(new T.CylinderGeometry(0.02, 0.02, 0.26, 10), metal), 0, 0.5, 0), antBall,
      k.at(k.sc(k.sphere(0.1, metal), 0.5, 1, 1), -0.5, 0, 0), k.at(k.sc(k.sphere(0.1, metal), 0.5, 1, 1), 0.5, 0, 0));
    head.position.y = 1.78;
    const armL = arm(T, k, -1, { x: 0.7, y: 1.2, color: '#aab6c4', hand: '#7d8a99', r: 0.12 }), armR = arm(T, k, 1, { x: 0.7, y: 1.2, color: '#aab6c4', hand: '#7d8a99', r: 0.12 });
    return { body, head, armL, armR, eyes, smile: mo, mouth: null, robotMouth: mo, glows: [antBall, ...body.children.slice(2)], parts: [legs] };
  },

  kedi(T, k) {
    const fur = '#f59e42', cream = '#fde7c8', pink = '#ff9db0';
    const body = k.group(k.sc(k.sphere(0.72, k.mat(fur, { roughness: 0.55, clearcoat: 0.35 })), 1, 0.95, 0.9),
      k.at(k.sc(k.sphere(0.46, k.mat(cream, { roughness: 0.6, clearcoat: 0.3 })), 1, 1.05, 0.5), 0, -0.06, 0.45));
    body.position.y = 0.8;
    const feet = k.group(k.at(k.sc(k.sphere(0.17, k.mat(cream)), 1, 0.7, 1.2), -0.27, 0.1, 0.32), k.at(k.sc(k.sphere(0.17, k.mat(cream)), 1, 0.7, 1.2), 0.27, 0.1, 0.32));
    const curve = new T.CatmullRomCurve3([new T.Vector3(0, 0, 0), new T.Vector3(0.35, 0.1, -0.15), new T.Vector3(0.62, 0.45, -0.2), new T.Vector3(0.55, 0.85, -0.12), new T.Vector3(0.38, 1.0, -0.05)]);
    const tail = k.group(new T.Mesh(new T.TubeGeometry(curve, 48, 0.075, 12, false), k.mat(fur)), k.at(k.sphere(0.09, k.mat(cream)), 0.38, 1.0, -0.05));
    tail.position.set(0.45, 0.45, -0.45);
    const eyes = [k.eye(0.13, { pupil: '#2f7d4a', pupilScale: 0.6 }), k.eye(0.13, { pupil: '#2f7d4a', pupilScale: 0.6 })];
    eyes[0].g.position.set(-0.2, 0.08, 0.46); eyes[1].g.position.set(0.2, 0.08, 0.46);
    const ear = side => {
      const g = k.group(k.mesh(new T.ConeGeometry(0.19, 0.34, 24), k.mat(fur)), k.at(k.mesh(new T.ConeGeometry(0.11, 0.22, 20), k.mat(pink)), 0, -0.02, 0.06));
      g.position.set(side * 0.33, 0.44, 0); g.rotation.z = -side * 0.35;
      return g;
    };
    const whisk = [];
    for (const side of [-1, 1]) for (let i = 0; i < 3; i++) {
      const w = new T.Mesh(new T.CylinderGeometry(0.008, 0.008, 0.34, 6), k.mat('#5b4636'));
      w.rotation.z = Math.PI / 2 + side * (i - 1) * 0.16; w.position.set(side * 0.4, -0.12 + (i - 1) * 0.05, 0.42);
      whisk.push(w);
    }
    const sm = k.at(k.smile(0.08, '#5b3a2e', 0.018), 0, -0.2, 0.52), mo = k.at(k.mouth(0.07), 0, -0.22, 0.5);
    const head = k.group(k.sc(k.sphere(0.56, k.mat(fur, { roughness: 0.55, clearcoat: 0.35 })), 1.08, 0.95, 0.95), ear(-1), ear(1),
      k.at(k.sc(k.sphere(0.13, k.mat(cream)), 1.1, 0.8, 0.8), -0.1, -0.15, 0.46), k.at(k.sc(k.sphere(0.13, k.mat(cream)), 1.1, 0.8, 0.8), 0.1, -0.15, 0.46),
      k.at(k.sc(k.sphere(0.055, k.mat(pink)), 1.2, 0.8, 0.8), 0, -0.07, 0.55),
      eyes[0].g, eyes[1].g, sm, mo, ...whisk, k.at(k.cheek(0.09), -0.36, -0.1, 0.38), k.at(k.cheek(0.09), 0.36, -0.1, 0.38));
    head.position.y = 1.62;
    const armL = arm(T, k, -1, { x: 0.62, y: 1.08, color: fur, hand: cream, len: 0.3, r: 0.12 }), armR = arm(T, k, 1, { x: 0.62, y: 1.08, color: fur, hand: cream, len: 0.3, r: 0.12 });
    return { body, head, armL, armR, eyes, smile: sm, mouth: mo, tail, parts: [feet, tail] };
  },

  hayalet(T, k) {
    const pts = [[0.64, 0.0], [0.68, 0.35], [0.66, 0.75], [0.6, 1.05], [0.48, 1.35], [0.3, 1.56], [0.12, 1.66], [0, 1.68]].map(([x, y]) => new T.Vector2(x, y));
    const geo = new T.LatheGeometry(pts, 64);
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {   // dalgalı etek
      if (pos.getY(i) < 0.01) { const a = Math.atan2(pos.getZ(i), pos.getX(i)); pos.setY(i, Math.sin(a * 7) * 0.07 - 0.02); }
    }
    geo.computeVertexNormals();
    const ghost = k.mat('#ffffff', { roughness: 0.28, clearcoat: 0.9, side: T.DoubleSide, emissive: '#cdd8ff', emissiveIntensity: 0.16 });
    const eyes = [k.eye(0.12, { white: false }), k.eye(0.12, { white: false })];
    eyes.forEach(e => e.pupil.scale.set(0.85, 1.25, 1));
    // Yüz gövdenin parçası; "baş" grubu yalnız yüzü taşır ve dönme noktası yüz hizasında gövde ekseninde —
    // böylece imlece bakarken yüz gövde yüzeyinde kayar, içine gömülmez (yüzey yarıçapı ~0.6)
    eyes[0].g.position.set(-0.2, 0, 0.57); eyes[1].g.position.set(0.2, 0, 0.57);
    const sm = k.at(k.smile(0.08), 0, -0.22, 0.66), mo = k.at(k.mouth(0.08), 0, -0.24, 0.65);
    const body = k.group(new T.Mesh(geo, ghost), k.at(k.cheek(0.09), -0.36, 0.9, 0.52), k.at(k.cheek(0.09), 0.36, 0.9, 0.52));
    body.position.y = 0.3;
    const head = k.group(eyes[0].g, eyes[1].g, sm, mo);
    head.position.y = 1.38;
    const nub = side => { const p = new T.Group(); p.position.set(side * 0.66, 1.0, 0.05); p.add(k.at(k.sc(k.sphere(0.16, ghost), 0.75, 1.1, 0.75), 0, -0.12, 0)); p.rotation.z = side * 0.5; p.userData.rest = side * 0.5; return p; };
    return { body, head, armL: nub(-1), armR: nub(1), eyes, smile: sm, mouth: mo, float: true };
  },

  penguen(T, k) {
    const black = '#1f2733', white = '#f7f8fb', orange = '#ff9f2e';
    const body = k.group(k.sc(k.sphere(0.72, k.mat(black)), 1, 1.18, 0.95), k.at(k.sc(k.sphere(0.6, k.mat(white)), 0.86, 1.1, 0.55), 0, -0.1, 0.36));
    body.position.y = 0.92;
    const feet = k.group(k.at(k.sc(k.sphere(0.17, k.mat(orange)), 1.1, 0.45, 1.5), -0.24, 0.06, 0.26), k.at(k.sc(k.sphere(0.17, k.mat(orange)), 1.1, 0.45, 1.5), 0.24, 0.06, 0.26));
    const eyes = [k.eye(0.1), k.eye(0.1)];
    eyes[0].g.position.set(-0.16, 0.1, 0.42); eyes[1].g.position.set(0.16, 0.1, 0.42);
    const beak = k.mesh(new T.ConeGeometry(0.09, 0.24, 24), k.mat(orange));
    beak.rotation.x = Math.PI / 2; beak.position.set(0, -0.06, 0.52);
    const mo = k.at(k.sc(k.sphere(0.07, k.mat('#c96a12')), 1.2, 0.5, 0.6), 0, -0.13, 0.46); mo.visible = false;
    const head = k.group(k.sphere(0.48, k.mat(black)), k.at(k.sc(k.sphere(0.36, k.mat(white)), 1.15, 0.9, 0.55), 0, 0.02, 0.26),
      eyes[0].g, eyes[1].g, beak, mo, k.at(k.cheek(0.08), -0.28, -0.08, 0.38), k.at(k.cheek(0.08), 0.28, -0.08, 0.38));
    head.position.y = 1.78;
    const flip = side => { const p = new T.Group(); p.position.set(side * 0.66, 1.25, 0); p.add(k.at(k.sc(k.sphere(0.2, k.mat(black)), 0.35, 1.25, 0.7), 0, -0.26, 0)); p.rotation.z = side * 0.25; p.userData.rest = side * 0.25; return p; };
    return { body, head, armL: flip(-1), armR: flip(1), eyes, smile: null, mouth: mo, beak, parts: [feet] };
  },

  uzayli(T, k) {
    const green = '#74e06f', light = '#8ff08a';
    const body = k.group(k.sc(k.sphere(0.48, k.mat(green)), 1, 1.05, 0.95), k.at(k.sc(k.sphere(0.3, k.mat('#c9ffc4', { transparent: true, opacity: 0.6 })), 1, 1, 0.5), 0, -0.05, 0.3));
    body.position.y = 0.72;
    const legs = k.group(k.at(k.capsule(0.09, 0.2, k.mat(green)), -0.17, 0.2, 0), k.at(k.capsule(0.09, 0.2, k.mat(green)), 0.17, 0.2, 0),
      k.at(k.sc(k.sphere(0.12, k.mat('#4fb44b')), 1.1, 0.55, 1.4), -0.17, 0.06, 0.05), k.at(k.sc(k.sphere(0.12, k.mat('#4fb44b')), 1.1, 0.55, 1.4), 0.17, 0.06, 0.05));
    const eyeMat = k.mat('#0d1512', { roughness: 0.08, clearcoat: 1 });
    const mkEye = side => {
      const glint = k.at(k.sphere(0.035, new T.MeshBasicMaterial({ color: '#ffffff' }), 12), 0.04, 0.07, 0.1);
      const p = k.group(k.sc(k.sphere(0.13, eyeMat, 28), 0.85, 1.35, 0.5), glint);
      const g = k.group(p); g.rotation.z = side * 0.32;
      return { g, pupil: glint, r: 0.08 };
    };
    const eyes = [mkEye(1), mkEye(-1)];
    eyes[0].g.position.set(-0.24, 0.05, 0.5); eyes[1].g.position.set(0.24, 0.05, 0.5);
    const sm = k.at(k.smile(0.1, '#245c22'), 0, -0.24, 0.53), mo = k.at(k.mouth(0.08, '#1f3a1d'), 0, -0.26, 0.52);
    const balls = [k.glow('#ff6bd6', 1.8), k.glow('#ff6bd6', 1.8)].map((m, i) => k.at(k.sphere(0.07, m, 18), (i ? 1 : -1) * 0.34, 0.86, 0));
    const ant = side => { const c = new T.Mesh(new T.CylinderGeometry(0.018, 0.018, 0.36, 8), k.mat(green)); c.position.set(side * 0.27, 0.68, 0); c.rotation.z = -side * 0.35; return c; };
    const head = k.group(k.sc(k.sphere(0.62, k.mat(light)), 1.15, 0.95, 0.95), eyes[0].g, eyes[1].g, sm, mo, ant(-1), ant(1), ...balls,
      k.at(k.cheek(0.08), -0.42, -0.16, 0.42), k.at(k.cheek(0.08), 0.42, -0.16, 0.42));
    head.position.y = 1.5;
    const armL = arm(T, k, -1, { x: 0.42, y: 0.92, color: green, hand: light, len: 0.3, r: 0.08 }), armR = arm(T, k, 1, { x: 0.42, y: 0.92, color: green, hand: light, len: 0.3, r: 0.08 });
    return { body, head, armL, armR, eyes, smile: sm, mouth: mo, glows: balls, parts: [legs] };
  },
};

function buildCharacter(T, id) {
  const k = kit(T);
  const c = (BUILD[id] || BUILD.kubbe)(T, k);
  const root = new T.Group();
  [c.body, c.head, c.armL, c.armR, ...(c.parts || [])].forEach(o => o && root.add(o));
  c.root = root;
  c.headY = c.head.position.y;
  return c;
}

function shadowMesh(T) {
  const cv = document.createElement('canvas'); cv.width = cv.height = 64;
  const g = cv.getContext('2d'); const gr = g.createRadialGradient(32, 32, 2, 32, 32, 32);
  gr.addColorStop(0, 'rgba(16,24,40,.42)'); gr.addColorStop(1, 'rgba(16,24,40,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
  const tex = new T.CanvasTexture(cv);
  const m = new T.Mesh(new T.PlaneGeometry(1.9, 1.9), new T.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.y = 0.004;
  return m;
}

function disposeTree(o) {
  o.traverse(n => {
    n.geometry?.dispose?.();
    const ms = Array.isArray(n.material) ? n.material : n.material ? [n.material] : [];
    ms.forEach(m => { m.map?.dispose?.(); m.dispose?.(); });
  });
}

function stage(T, RoomEnvironment, renderer) {
  const scene = new T.Scene();
  const pm = new T.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
  pm.dispose();
  scene.environmentIntensity = 0.8;
  const key = new T.DirectionalLight(0xffffff, 1.5); key.position.set(2.5, 4, 3.5);
  const rim = new T.DirectionalLight(0xbfd4ff, 1.4); rim.position.set(-3, 2.6, -3);
  scene.add(key, rim, new T.HemisphereLight(0xffffff, 0x445566, 0.45));
  return scene;
}

const ease = u => (u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2);
const TRICK_LEN = { wave: 1.7, jump: 1.05, spin: 1.25, wobble: 1.3, dance: 2.0, pop: 1.4, peek: 1.7, hop: 0.45 };

// ---------- Canlı maskot ----------
// container: .mascot-fig; döner: { setCharacter, play, setState, talk, lookAt, poke, destroy }
export async function createMascot3D(container, id) {
  const { T, RoomEnvironment } = await loadLibs();
  const canvas = document.createElement('canvas');
  canvas.className = 'mascot-3d';
  container.append(canvas);
  const renderer = new T.WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = stage(T, RoomEnvironment, renderer);
  const camera = new T.PerspectiveCamera(26, 1, 0.1, 50);
  camera.position.set(0, 1.3, 8.4);
  camera.lookAt(0, 1.12, 0);
  const shadow = shadowMesh(T);
  scene.add(shadow);

  let ch = null, curId = id;
  const setChar = nid => {
    if (ch) { scene.remove(ch.root); disposeTree(ch.root); }
    curId = nid; ch = buildCharacter(T, nid);
    scene.add(ch.root);
    ch.root.scale.setScalar(0.01); popIn = 0;   // yeni karakter "zıplayarak" belirir
  };
  let popIn = 1;
  setChar(id);

  const resize = () => {
    const w = canvas.clientWidth || 1, hh = canvas.clientHeight || 1;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, hh, false);
    camera.aspect = w / hh; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(canvas); resize();

  // durum
  let trick = null, state = 'idle', talkUntil = 0, happy = false;
  const look = { x: 0, y: 0, tx: 0, ty: 0, lastMove: 0 };
  let blinkAt = 1.5, blinkT = -1, poke = -1;
  const sparks = [];
  const clock = new T.Clock();
  let raf = 0, lastDraw = 0, t = 0;

  function burst() {   // kafa şişip patlayınca kıvılcımlar
    const colors = ['#ffd166', '#ff8a5b', '#ff6bd6', '#5ef0ff', '#8ff08a'];
    for (let i = 0; i < 14; i++) {
      const m = new T.Mesh(new T.SphereGeometry(0.045, 10, 8), new T.MeshBasicMaterial({ color: colors[i % colors.length], transparent: true }));
      m.position.set(0, ch.headY + 0.1, 0.3);
      const a = (i / 14) * Math.PI * 2;
      m.userData.v = new T.Vector3(Math.cos(a) * (1.4 + Math.random()), Math.sin(a) * (1.4 + Math.random()) + 0.6, (Math.random() - 0.3) * 0.8);
      m.userData.life = 0;
      scene.add(m); sparks.push(m);
    }
  }

  function animate(dt) {
    t += dt;
    const c = ch;
    // bakış: imleç yoksa ara sıra rastgele bakınır
    if (t - look.lastMove > 4) {
      if (Math.random() < dt * 0.35) { look.tx = (Math.random() - 0.5) * 1.4; look.ty = (Math.random() - 0.4) * 0.8; }
    }
    let tx = look.tx, ty = look.ty;
    if (state === 'thinking') { tx = 0.55; ty = 0.75; }
    look.x += (tx - look.x) * Math.min(1, dt * 5); look.y += (ty - look.y) * Math.min(1, dt * 5);

    // temel poz
    const root = c.root;
    root.position.set(0, c.float ? 0.16 + Math.sin(t * 1.7) * 0.09 : 0, 0);
    root.rotation.set(0, look.x * 0.42, 0);
    let sx = 1, sy = 1;
    const br = Math.sin(t * 2.3);
    c.body.scale.set(1 - br * 0.012, 1 + br * 0.025, 1 - br * 0.012);
    c.head.position.y = c.headY + br * 0.012;
    c.head.rotation.set(-look.y * 0.22, look.x * 0.28, state === 'thinking' ? 0.16 * Math.sin(t * 1.3) + 0.12 : 0);
    c.head.scale.setScalar(1);
    c.armL.rotation.set(0, 0, c.armL.userData.rest + Math.sin(t * 2.3) * 0.03);
    c.armR.rotation.set(0, 0, c.armR.userData.rest - Math.sin(t * 2.3) * 0.03);
    if (state === 'thinking') c.armL.rotation.z = -2.1 + Math.sin(t * 2) * 0.05;   // el çenede
    if (c.tail) c.tail.rotation.z = Math.sin(t * 2.2) * 0.22;
    (c.glows || []).forEach((g, i) => { const s = 1 + Math.sin(t * 4 + i) * 0.12; g.scale.setScalar(s); });
    if (c.float) { c.armL.rotation.z = c.armL.userData.rest + Math.sin(t * 1.7) * 0.15; c.armR.rotation.z = c.armR.userData.rest - Math.sin(t * 1.7 + 0.5) * 0.15; }
    if (happy && !trick) { root.position.y += Math.abs(Math.sin(t * 7)) * 0.06; }

    // numara
    if (trick) {
      const u = Math.min(1, (t - trick.t0) / TRICK_LEN[trick.name]);
      const w = Math.sin(u * Math.PI);
      switch (trick.name) {
        case 'wave':
          c.armR.rotation.z = c.armR.userData.rest + (-2.5 - c.armR.userData.rest) * Math.min(1, w * 1.6) + Math.sin(t * 15) * 0.32 * w;
          c.head.rotation.z = -0.12 * w; break;
        case 'jump': {
          if (u < 0.16) { const q = u / 0.16; sx = 1 + 0.12 * q; sy = 1 - 0.15 * q; }
          else if (u < 0.82) { const q = (u - 0.16) / 0.66; root.position.y += Math.sin(q * Math.PI) * 0.75; sy = 1 + 0.08 * Math.sin(q * Math.PI); sx = 1 - 0.04 * Math.sin(q * Math.PI);
            c.armL.rotation.z = -1.2 * Math.sin(q * Math.PI) + c.armL.userData.rest; c.armR.rotation.z = 1.2 * Math.sin(q * Math.PI) + c.armR.userData.rest; }
          else { const q = (u - 0.82) / 0.18; sx = 1 + 0.1 * Math.sin(q * Math.PI); sy = 1 - 0.12 * Math.sin(q * Math.PI); }
          break; }
        case 'hop': root.position.y += Math.sin(u * Math.PI) * 0.22; break;
        case 'spin': root.rotation.y += ease(u) * Math.PI * 2; root.position.y += w * 0.12; break;
        case 'wobble': root.rotation.z = Math.sin(u * Math.PI * 6) * 0.22 * (1 - u); break;
        case 'dance':
          root.position.x = Math.sin(u * Math.PI * 6) * 0.16; root.rotation.z = Math.sin(u * Math.PI * 6) * 0.12;
          root.position.y += Math.abs(Math.sin(u * Math.PI * 6)) * 0.1;
          c.armL.rotation.z = c.armL.userData.rest - (1.6 + Math.sin(u * Math.PI * 12) * 0.5) * w;
          c.armR.rotation.z = c.armR.userData.rest + (1.6 + Math.cos(u * Math.PI * 12) * 0.5) * w; break;
        case 'pop': {
          const grow = u < 0.62 ? ease(u / 0.62) * 0.42 : 0.42 * (1 - (u - 0.62) / 0.38) * Math.cos((u - 0.62) * 40) ;
          c.head.scale.setScalar(1 + grow);
          if (!trick.burst && u >= 0.62) { trick.burst = true; burst(); }
          break; }
        case 'peek': root.rotation.z = 0.32 * w; root.position.x = -0.22 * w; c.head.rotation.z += 0.2 * w; break;
      }
      if (u >= 1) trick = null;
    }
    // dokunma (tıklama) ezilmesi
    if (poke >= 0) { poke += dt; const q = Math.min(1, poke / 0.35); sx *= 1 + 0.1 * Math.sin(q * Math.PI); sy *= 1 - 0.12 * Math.sin(q * Math.PI); if (q >= 1) poke = -1; }
    // belirme
    if (popIn < 1) { popIn = Math.min(1, popIn + dt * 2.6); const e = popIn; const back = 1 + 2.2 * (e - 1) ** 3 + 1.2 * (e - 1) ** 2; sx *= back; sy *= back; }
    root.scale.set(sx, sy, sx);
    shadow.scale.setScalar(Math.max(0.45, 1 - (root.position.y) * 0.55) * (c.float ? 0.85 : 1));
    shadow.material.opacity = Math.max(0.35, 1 - root.position.y * 0.8);

    // gözler: bakış + kırpma (mutluyken kısık)
    if (blinkT < 0 && t > blinkAt) { blinkT = 0; }
    let lid = 1;
    if (blinkT >= 0) { blinkT += dt; const q = blinkT / 0.15; lid = 1 - Math.sin(Math.min(1, q) * Math.PI) * 0.92; if (q >= 1) { blinkT = -1; blinkAt = t + 1.8 + Math.random() * 3.6; if (Math.random() < 0.2) blinkAt = t + 0.25; } }
    if (happy || trick?.name === 'dance') lid = Math.min(lid, 0.5);
    for (const e of c.eyes) {
      e.g.scale.y = lid;
      e.pupil.position.x = look.x * e.r * 0.32;
      e.pupil.position.y = look.y * e.r * 0.3;
    }
    // ağız: konuşurken açılıp kapanır
    const talking = t < talkUntil;
    if (c.robotMouth) { c.robotMouth.scale.set(1, talking ? 1 + Math.abs(Math.sin(t * 13)) * 2.4 : 1, 1); }
    else {
      if (c.smile) c.smile.visible = !talking;
      if (c.mouth) { c.mouth.visible = talking || trick?.name === 'pop'; c.mouth.scale.y = 0.25 + (talking ? Math.abs(Math.sin(t * 12) * Math.sin(t * 5.3 + 1)) * 0.75 : 0.6); }
    }
    if (talking) c.head.rotation.x += Math.sin(t * 9) * 0.03;

    // kıvılcımlar
    for (let i = sparks.length - 1; i >= 0; i--) {
      const s = sparks[i]; s.userData.life += dt;
      s.userData.v.y -= dt * 3.2;
      s.position.addScaledVector(s.userData.v, dt);
      const k = 1 - s.userData.life / 0.7;
      s.material.opacity = Math.max(0, k); s.scale.setScalar(Math.max(0.01, k));
      if (k <= 0) { scene.remove(s); s.geometry.dispose(); s.material.dispose(); sparks.splice(i, 1); }
    }
  }

  const visible = () => !document.hidden && canvas.isConnected && container.getClientRects().length > 0;
  const loop = now => {
    raf = requestAnimationFrame(loop);
    if (!visible()) { clock.getDelta(); return; }
    const active = trick || state !== 'idle' || t < talkUntil || happy || popIn < 1 || sparks.length || poke >= 0 || blinkT >= 0;
    if (!active && now - lastDraw < 31) return;   // boştayken ~30 fps
    lastDraw = now;
    animate(Math.min(0.05, clock.getDelta()));
    renderer.render(scene, camera);
  };
  raf = requestAnimationFrame(loop);

  return {
    setCharacter: nid => setChar(nid),
    play: name => { if (TRICK_LEN[name] && !trick) trick = { name, t0: t }; },
    setState: s => { state = s || 'idle'; },
    talk: sec => { talkUntil = t + Math.max(0.6, Math.min(sec, 8)); },
    happy: on => { happy = !!on; },
    poke: () => { poke = 0; },
    // ekran koordinatı → bakış hedefi (-1..1)
    lookAt: (x, y) => {
      const r = container.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height * 0.3;
      look.tx = Math.max(-1, Math.min(1, (x - cx) / (window.innerWidth * 0.45)));
      look.ty = Math.max(-1, Math.min(1, -(y - cy) / (window.innerHeight * 0.45)));
      look.lastMove = t;
    },
    get id() { return curId; },
    destroy: () => {
      cancelAnimationFrame(raf); ro.disconnect();
      disposeTree(scene);
      scene.environment?.dispose?.();
      renderer.dispose(); renderer.forceContextLoss?.();
      canvas.remove();
    },
  };
}

// ---------- Anlık görüntü (ayarlar önizlemesi, sohbet başlığı) ----------
let snapR = null;
const snaps = new Map();
export async function mascot3dSnapshot(id, { w = 220, h = 250 } = {}) {
  const key = `${id}|${brand()}|${w}x${h}`;
  if (snaps.has(key)) return snaps.get(key);
  const p = (async () => {
    const { T, RoomEnvironment } = await loadLibs();
    if (!snapR) {
      const c = document.createElement('canvas');
      snapR = { renderer: new T.WebGLRenderer({ canvas: c, alpha: true, antialias: true, preserveDrawingBuffer: true }) };
      const r = snapR.renderer;
      r.setClearColor(0x000000, 0); r.outputColorSpace = T.SRGBColorSpace; r.toneMapping = T.ACESFilmicToneMapping; r.toneMappingExposure = 1.05;
      snapR.scene = stage(T, RoomEnvironment, r);
      snapR.scene.add(shadowMesh(T));
      snapR.camera = new T.PerspectiveCamera(26, 1, 0.1, 50);
    }
    const { renderer, scene, camera } = snapR;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    camera.position.set(0, 1.3, 8.4); camera.lookAt(0, 1.12, 0);
    const c = buildCharacter(T, id);
    c.root.rotation.y = -0.32;
    c.root.position.y = c.float ? 0.16 : 0;
    scene.add(c.root);
    renderer.render(scene, camera);
    const url = renderer.domElement.toDataURL('image/png');
    scene.remove(c.root); disposeTree(c.root);
    return url;
  })().catch(err => { snaps.delete(key); throw err; });
  snaps.set(key, p);
  return p;
}
