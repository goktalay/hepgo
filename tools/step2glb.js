// CAYMAZ V3 STEP → static/models/caymaz-sim.glb (uçuş simülatörü). Bağımlılık depoya girmez: geçici dizinde `npm i occt-import-js`, sonra
// NODE_PATH=<o dizin>/node_modules node tools/step2glb.js <CAYMAZ.step> static/models/caymaz-sim.glb [linDefl_mm=2] [angDefl_rad=0.6] [quant=1]
// Eksenler: STEP (X sağ kanat, Y burun, Z yukarı, mm) → glTF (X SOL, Y yukarı, Z burun, m) — flightsim3d.js'teki caymaz dönüşümüyle aynı
// (Rx+90°, Rz180° → gövde: burun +Y, sağ kanat +X, üst +Z). Orijin: kanat ortası (STEP Y=Y0). Renge göre iki mesh'e birleştirilir;
// arkaya prosedürel motor + "prop" düğümü (2 palalı pervane, Ø 0.81 m; glTF Z ekseni etrafında döner).
// KONTROL YÜZEYLERİ (ayrı düğümler, menteşe pivotlu): STEP montajında arka kenar yüzeyleri FL1/FL2 (sol) ve FR1/FR2 (sağ) ayrı parçadır
// (koyu renk, kord ≈ 138 mm, Y 100…240). Dıştakiler (FL1/FR1, X 911…1450) elevon, içtekiler (FL2/FR2, X 370…908) flap. Her biri gövdeyle
// BİRLEŞTİRİLMEZ; kendi düğümüne yazılır: düğüm orijini = menteşe pivotu (yüzeyin gövdeye/kanada bakan ÖN kenarının ortası, Z ortası),
// düğüm yerel X ekseni = menteşe ekseni (ön kenar köşelerinden PCA ile; süpürülü kenarda kanat süpürmesine paralel çıkar), köşeler pivota göre.
// Düğüm `extras`: {surface, side, hinge:'x', te_down: -1} — te_down: yerel X etrafında arka kenarı AŞAĞI indiren dönüş işareti
// (glTF'de Y yukarı, arka kenar −Z'de → rotation.x < 0 arka kenarı aşağı indirir). flightsim3d.js bu düğümleri adıyla bulur
// (elevon_l/elevon_r/flap_l/flap_r; kuyruk/rudder parçası montajda yoktur — uçan kanat). Kuyruk eklenirse CTRL_PARTS'a satır eklenir.
const fs = require('fs');
const occtimportjs = require('occt-import-js');
const [,, STEP, OUT, LD = '2.0', AD = '0.6', QUANT = '1'] = process.argv;
const Y0 = 1200, SCALE = 0.001;
const quant = QUANT !== '0';
// STEP parça adı (düğüm adı, boşluklar sadeleştirilmiş) → kontrol yüzeyi düğümü
const CTRL_PARTS = [
  { re: /^FL1\b/i, name: 'elevon_l', surface: 'elevon', side: 'l' },
  { re: /^FR1\b/i, name: 'elevon_r', surface: 'elevon', side: 'r' },
  { re: /^FL2\b/i, name: 'flap_l', surface: 'flap', side: 'l' },
  { re: /^FR2\b/i, name: 'flap_r', surface: 'flap', side: 'r' },
  { re: /^(RUD|RL|RUDDER)[_ -]?L\b/i, name: 'rudder_l', surface: 'rudder', side: 'l', hingeUp: true },
  { re: /^(RUD|RR|RUDDER)[_ -]?R\b/i, name: 'rudder_r', surface: 'rudder', side: 'r', hingeUp: true },
];
const toGl = (x, y, z) => [-x * SCALE, z * SCALE, (y - Y0) * SCALE];   // STEP mm → glTF m

(async () => {
  const occt = await occtimportjs();
  const buf = new Uint8Array(fs.readFileSync(STEP));
  const res = occt.ReadStepFile(buf, { linearUnit: 'millimeter', linearDeflectionType: 'absolute_value', linearDeflection: Number(LD), angularDeflection: Number(AD) });
  if (!res.success) throw new Error('STEP okunamadı');

  // ---- montaj ağacından mesh → parça adı (mesh.name çoğu parçada boş) ----
  const meshName = new Map();
  const walk = n => { for (const mi of n.meshes || []) if (!meshName.has(mi)) meshName.set(mi, (n.name || '').replace(/\s+/g, ' ').trim()); for (const c of n.children || []) walk(c); };
  walk(res.root);
  // "part 2" alt montajında mesh adları dolu, düğüm adı ortak ("caymaz - v3 part 2") → önce mesh.name, boşsa düğüm adı
  const partName = i => ((res.meshes[i].name || '').replace(/\s+/g, ' ').trim()) || meshName.get(i) || '';
  const ctrlOf = i => CTRL_PARTS.find(c => c.re.test(partName(i))) || null;

  // ---- renge göre birleştirme (kontrol yüzeyleri hariç) ----
  const groups = { white: { pos: [], nor: [], idx: [], color: [0.90, 0.91, 0.94, 1], name: 'govde_beyaz' }, dark: { pos: [], nor: [], idx: [], color: [0.22, 0.24, 0.27, 1], name: 'govde_koyu' } };
  const ctrls = [];   // ayrı düğümler
  let triTotal = 0;
  res.meshes.forEach((m, mi) => {
    const p = m.attributes.position.array, nrm = m.attributes.normal?.array, ix = m.index?.array;
    if (!p || !ix) return;
    const c = ctrlOf(mi);
    let g;
    if (c) {
      g = { pos: [], nor: [], idx: [], color: [0.20, 0.22, 0.25, 1], name: c.name, ctrl: c, raw: p, part: partName(mi) };
      ctrls.push(g);
    } else g = (m.color && m.color[0] > 0.6) ? groups.white : groups.dark;
    const base = g.pos.length / 3;
    for (let k = 0; k < p.length; k += 3) {
      g.pos.push(...toGl(p[k], p[k + 1], p[k + 2]));
      if (nrm) g.nor.push(-nrm[k], nrm[k + 2], nrm[k + 1]); else g.nor.push(0, 1, 0);
    }
    for (let k = 0; k < ix.length; k++) g.idx.push(base + ix[k]);
    triTotal += ix.length / 3;
  });

  // ---- kontrol yüzeyleri: pivot (ön kenar ortası) + menteşe ekseni (ön kenar köşelerinin PCA'sı) → yerel çerçeveye taşı ----
  for (const g of ctrls) {
    const p = g.raw, mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
    for (let k = 0; k < p.length; k += 3) for (let a = 0; a < 3; a++) { if (p[k + a] < mn[a]) mn[a] = p[k + a]; if (p[k + a] > mx[a]) mx[a] = p[k + a]; }
    // Ön kenar: STEP +Y burun → yüzeyin en büyük Y'li köşeleri (kanada bakan kenar). Rudder'da (dikey yüzey) menteşe dikeydir (hingeUp).
    const edge = [];
    const tol = Math.max(3, (mx[1] - mn[1]) * 0.04);
    for (let k = 0; k < p.length; k += 3) if (p[k + 1] >= mx[1] - tol) edge.push([p[k], p[k + 1], p[k + 2]]);
    const cen = [0, 0, 0]; for (const e of edge) for (let a = 0; a < 3; a++) cen[a] += e[a] / edge.length;
    // 2B PCA (menteşe düzlemi: yatay yüzeyde X–Y, dikey yüzeyde Z–Y)
    const ia = g.ctrl.hingeUp ? 2 : 0;
    let sxx = 0, sxy = 0, syy = 0;
    for (const e of edge) { const dx = e[ia] - cen[ia], dy = e[1] - cen[1]; sxx += dx * dx; sxy += dx * dy; syy += dy * dy; }
    const th = 0.5 * Math.atan2(2 * sxy, sxx - syy);   // ana eksen açısı (STEP düzleminde)
    let dir = [0, 0, 0]; dir[ia] = Math.cos(th); dir[1] = Math.sin(th);
    const pivotStep = [cen[0], mx[1], (mn[2] + mx[2]) / 2];
    const pivot = toGl(...pivotStep);
    let d = [-dir[0], dir[2], dir[1]];                 // glTF menteşe yönü (birim)
    if (d[g.ctrl.hingeUp ? 1 : 0] < 0) d = d.map(v => -v);   // glTF +X (sol) / +Y (yukarı) yönünde → düğüm dönüşü ≈ birim, yerel +Z = burun
    // Yerel çerçeve: X = menteşe (d), diğerleri d'ye dik; glTF +Y'yi mümkün olduğunca koru (yatay yüzey) → Z = X × Y_dünya normalize, Y = Z × X
    const up = g.ctrl.hingeUp ? [0, 0, 1] : [0, 1, 0];   // rudder'da menteşe ≈ Y; "yukarı" yerine burun (+Z) korunur
    let Z = [d[1] * up[2] - d[2] * up[1], d[2] * up[0] - d[0] * up[2], d[0] * up[1] - d[1] * up[0]];
    const zl = Math.hypot(...Z) || 1; Z = Z.map(v => v / zl);
    const Yl = [Z[1] * d[2] - Z[2] * d[1], Z[2] * d[0] - Z[0] * d[2], Z[0] * d[1] - Z[1] * d[0]];
    // Dönüş matrisi R sütunları (d, Yl, Z): yerel → dünya; yerel = R^T (v − pivot). glTF node.rotation = quaternion(R)
    const R = [d, Yl, Z];   // sütunlar
    const q = matToQuat(R);
    const loc = (v) => { const r = [v[0] - pivot[0], v[1] - pivot[1], v[2] - pivot[2]]; return [r[0] * R[0][0] + r[1] * R[0][1] + r[2] * R[0][2], r[0] * R[1][0] + r[1] * R[1][1] + r[2] * R[1][2], r[0] * R[2][0] + r[1] * R[2][1] + r[2] * R[2][2]]; };
    const locN = (v) => [v[0] * R[0][0] + v[1] * R[0][1] + v[2] * R[0][2], v[0] * R[1][0] + v[1] * R[1][1] + v[2] * R[1][2], v[0] * R[2][0] + v[1] * R[2][1] + v[2] * R[2][2]];
    for (let k = 0; k < g.pos.length; k += 3) {
      const v = loc([g.pos[k], g.pos[k + 1], g.pos[k + 2]]); g.pos[k] = v[0]; g.pos[k + 1] = v[1]; g.pos[k + 2] = v[2];
      const n = locN([g.nor[k], g.nor[k + 1], g.nor[k + 2]]); g.nor[k] = n[0]; g.nor[k + 1] = n[1]; g.nor[k + 2] = n[2];
    }
    const chord = (mx[1] - mn[1]) * SCALE, span = (g.ctrl.hingeUp ? mx[2] - mn[2] : mx[0] - mn[0]) * SCALE;
    g.node = { translation: pivot.map(v => +v.toFixed(5)), rotation: q.map(v => +v.toFixed(6)),
      extras: { surface: g.ctrl.surface, side: g.ctrl.side, hinge: 'x', te_down: -1, chord_m: +chord.toFixed(3), span_m: +span.toFixed(3), step_part: g.part,
        hinge_dir_body: [+(-d[0]).toFixed(4), +d[2].toFixed(4), +d[1].toFixed(4)] } };   // gövde çerçevesi (sağ +X, burun +Y, üst +Z) menteşe yönü
    console.log(`${g.name.padEnd(10)} ← ${String(g.part).padEnd(10)} pivot glTF [${g.node.translation.join(', ')}] menteşe gövde(x,y,z) [${g.node.extras.hinge_dir_body.join(', ')}] kord ${chord.toFixed(3)} m açıklık ${span.toFixed(3)} m`);
    delete g.raw;
  }
  function matToQuat(C) {   // C: sütun vektörleri [c0,c1,c2] → m[r][c] = C[c][r]
    const m = (r, c) => C[c][r];
    const tr = m(0, 0) + m(1, 1) + m(2, 2);
    let x, y, z, w;
    if (tr > 0) { const s = Math.sqrt(tr + 1) * 2; w = 0.25 * s; x = (m(2, 1) - m(1, 2)) / s; y = (m(0, 2) - m(2, 0)) / s; z = (m(1, 0) - m(0, 1)) / s; }
    else if (m(0, 0) > m(1, 1) && m(0, 0) > m(2, 2)) { const s = Math.sqrt(1 + m(0, 0) - m(1, 1) - m(2, 2)) * 2; w = (m(2, 1) - m(1, 2)) / s; x = 0.25 * s; y = (m(0, 1) + m(1, 0)) / s; z = (m(0, 2) + m(2, 0)) / s; }
    else if (m(1, 1) > m(2, 2)) { const s = Math.sqrt(1 + m(1, 1) - m(0, 0) - m(2, 2)) * 2; w = (m(0, 2) - m(2, 0)) / s; x = (m(0, 1) + m(1, 0)) / s; y = 0.25 * s; z = (m(1, 2) + m(2, 1)) / s; }
    else { const s = Math.sqrt(1 + m(2, 2) - m(0, 0) - m(1, 1)) * 2; w = (m(1, 0) - m(0, 1)) / s; x = (m(0, 2) + m(2, 0)) / s; y = (m(1, 2) + m(2, 1)) / s; z = 0.25 * s; }
    return [x, y, z, w];
  }

  // ---- prosedürel motor (arkadan itişli, gövde arkası STEP Y 100…280) ve pervane ----
  const eng = { pos: [], nor: [], idx: [], color: [0.45, 0.47, 0.50, 1], name: 'motor' };
  const prop = { pos: [], nor: [], idx: [], color: [0.08, 0.08, 0.09, 1], name: 'pervane' };
  const box = (g, cx, cy, cz, sx, sy, sz) => {   // eksen hizalı kutu (glTF m), yüz normalleri
    const h = [sx / 2, sy / 2, sz / 2], faces = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
    for (const n of faces) {
      const a = n[0] ? 1 : 0, b = n[2] ? 1 : 2;   // yüz düzlemindeki iki eksen
      const u = [0, 0, 0], v = [0, 0, 0]; u[a] = 1; v[b] = 1;
      const base = g.pos.length / 3;
      for (const [su, sv] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
        g.pos.push(cx + n[0] * h[0] + su * u[0] * h[0] + sv * v[0] * h[0], cy + n[1] * h[1] + su * u[1] * h[1] + sv * v[1] * h[1], cz + n[2] * h[2] + su * u[2] * h[2] + sv * v[2] * h[2]);
        g.nor.push(...n);
      }
      g.idx.push(base, base + 1, base + 2, base, base + 2, base + 3, base, base + 2, base + 1, base, base + 3, base + 2);
    }
  };
  const cyl = (g, cx, cy, cz, r, len, axis, seg = 12) => {   // eksen boyunca silindir (axis: 0 x, 1 y, 2 z)
    const base = g.pos.length / 3;
    const a1 = (axis + 1) % 3, a2 = (axis + 2) % 3;
    for (let i = 0; i <= seg; i++) {
      const t = i / seg * Math.PI * 2, c = Math.cos(t), s = Math.sin(t);
      for (const e of [-1, 1]) {
        const P = [cx, cy, cz]; P[axis] += e * len / 2; P[a1] += c * r; P[a2] += s * r;
        const N = [0, 0, 0]; N[a1] = c; N[a2] = s;
        g.pos.push(...P); g.nor.push(...N);
      }
    }
    for (let i = 0; i < seg; i++) { const k = base + i * 2; g.idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    for (const e of [-1, 1]) {   // kapaklar
      const c0 = g.pos.length / 3; const P = [cx, cy, cz]; P[axis] += e * len / 2; const N = [0, 0, 0]; N[axis] = e;
      g.pos.push(...P); g.nor.push(...N);
      for (let i = 0; i <= seg; i++) { const t = i / seg * Math.PI * 2; const Q = [...P]; Q[a1] += Math.cos(t) * r; Q[a2] += Math.sin(t) * r; g.pos.push(...Q); g.nor.push(...N); }
      for (let i = 0; i < seg; i++) g.idx.push(c0, c0 + 1 + i + (e > 0 ? 0 : 1), c0 + 1 + i + (e > 0 ? 1 : 0));
    }
  };
  const zEng = (190 - Y0) * SCALE;   // motor merkezi (STEP Y=190)
  box(eng, 0, -0.01, zEng, 0.13, 0.11, 0.17);            // karter
  cyl(eng, 0, 0.0, zEng, 0.055, 0.30, 0, 14);            // iki silindir (yatay, ±X) — 2 pistonlu
  for (const sx of [-1, 1]) cyl(eng, sx * 0.165, 0.0, zEng, 0.062, 0.03, 0, 14);   // silindir kafaları
  cyl(eng, 0, -0.06, zEng - 0.02, 0.028, 0.16, 2, 10);   // susturucu/egzoz alta
  cyl(eng, 0, 0, (85 - Y0) * SCALE, 0.02, 0.07, 2, 10);  // krank mili çıkışı
  const zProp = (50 - Y0) * SCALE;                       // pervane düzlemi (STEP Y=50)
  cyl(prop, 0, 0, 0, 0.045, 0.06, 2, 14);                // hub (prop düğümü orijininde)
  for (const sgn of [-1, 1]) {                            // 2 pala, 32" (0.81 m) — hafif açılı (geometrik yumuşatma yok, hız bulanıklığı sahnede)
    const L = 0.405, w = 0.062, th = 0.012;
    box(prop, sgn * (0.03 + L / 2), 0, 0, L, w, th);
  }
  // Pervane palaları dönük dursun: hub'a göre ±X boyunca kutu yeterli; dönme ekseni Z.

  // ---- GLB yaz ----
  const meshes = [groups.white, groups.dark, ...ctrls, eng, prop].filter(g => g.idx.length);
  const bin = []; let binLen = 0;
  const bufferViews = [], accessors = [];
  const pushView = (arr, target) => {
    const bytes = Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength);
    const pad = (4 - (bytes.length % 4)) % 4;
    bufferViews.push({ buffer: 0, byteOffset: binLen, byteLength: bytes.length, target });
    bin.push(bytes); binLen += bytes.length;
    if (pad) { bin.push(Buffer.alloc(pad)); binLen += pad; }
    return bufferViews.length - 1;
  };
  const minmax = (arr, n) => { const mn = Array(n).fill(Infinity), mx = Array(n).fill(-Infinity); for (let i = 0; i < arr.length; i += n) for (let a = 0; a < n; a++) { if (arr[i + a] < mn[a]) mn[a] = arr[i + a]; if (arr[i + a] > mx[a]) mx[a] = arr[i + a]; } return [mn, mx]; };
  const gmeshes = [], nodes = [], materials = [];
  let vertsTotal = 0;
  for (const g of meshes) {
    const nv = g.pos.length / 3; vertsTotal += nv;
    let posAcc, norAcc, scaleNode = null;
    const posF = Float32Array.from(g.pos);
    const [mn, mx] = minmax(posF, 3);
    if (quant) {
      // KHR_mesh_quantization: konum SHORT (ölçek düğümde), normal BYTE normalized
      const ext = Math.max(...mx.map((v, i) => Math.max(Math.abs(v), Math.abs(mn[i]))), 1e-6);
      const q = 32767 / ext;
      const ps = new Int16Array(nv * 4);   // glTF VEC3 SHORT stride 6 → 8'e hizalama için byteStride 8
      for (let i = 0; i < nv; i++) { ps[i * 4] = Math.round(posF[i * 3] * q); ps[i * 4 + 1] = Math.round(posF[i * 3 + 1] * q); ps[i * 4 + 2] = Math.round(posF[i * 3 + 2] * q); ps[i * 4 + 3] = 0; }
      const bv = pushView(ps, 34962); bufferViews[bv].byteStride = 8;
      const [qmn, qmx] = minmax(ps, 4);
      accessors.push({ bufferView: bv, componentType: 5122, count: nv, type: 'VEC3', min: qmn.slice(0, 3), max: qmx.slice(0, 3) });
      posAcc = accessors.length - 1; scaleNode = 1 / q;
      const ns = new Int8Array(nv * 4);
      for (let i = 0; i < nv; i++) {
        let x = g.nor[i * 3], y = g.nor[i * 3 + 1], z = g.nor[i * 3 + 2]; const l = Math.hypot(x, y, z) || 1; x /= l; y /= l; z /= l;
        ns[i * 4] = Math.round(x * 127); ns[i * 4 + 1] = Math.round(y * 127); ns[i * 4 + 2] = Math.round(z * 127); ns[i * 4 + 3] = 0;
      }
      const bv2 = pushView(ns, 34962); bufferViews[bv2].byteStride = 4;
      accessors.push({ bufferView: bv2, componentType: 5120, normalized: true, count: nv, type: 'VEC3' });
      norAcc = accessors.length - 1;
    } else {
      accessors.push({ bufferView: pushView(posF, 34962), componentType: 5126, count: nv, type: 'VEC3', min: mn, max: mx }); posAcc = accessors.length - 1;
      const norF = Float32Array.from(g.nor); for (let i = 0; i < nv; i++) { const l = Math.hypot(norF[i * 3], norF[i * 3 + 1], norF[i * 3 + 2]) || 1; norF[i * 3] /= l; norF[i * 3 + 1] /= l; norF[i * 3 + 2] /= l; }
      accessors.push({ bufferView: pushView(norF, 34962), componentType: 5126, count: nv, type: 'VEC3' }); norAcc = accessors.length - 1;
    }
    const idxArr = nv > 65535 ? Uint32Array.from(g.idx) : Uint16Array.from(g.idx);
    accessors.push({ bufferView: pushView(idxArr, 34963), componentType: nv > 65535 ? 5125 : 5123, count: idxArr.length, type: 'SCALAR' });
    const idxAcc = accessors.length - 1;
    materials.push({ name: g.name, doubleSided: true, pbrMetallicRoughness: { baseColorFactor: g.color, metallicFactor: g === prop ? 0.3 : 0.15, roughnessFactor: g === prop ? 0.5 : 0.55 } });
    gmeshes.push({ name: g.name, primitives: [{ attributes: { POSITION: posAcc, NORMAL: norAcc }, indices: idxAcc, material: materials.length - 1 }] });
    const node = { name: g === prop ? 'prop' : g.name, mesh: gmeshes.length - 1 };
    if (scaleNode) node.scale = [scaleNode, scaleNode, scaleNode];
    if (g === prop) node.translation = [0, 0, zProp];
    if (g.node) Object.assign(node, g.node);   // kontrol yüzeyi: pivot + menteşe çerçevesi + extras
    nodes.push(node);
    console.log(g.name.padEnd(14), 'vertex', nv, 'üçgen', g.idx.length / 3);
  }
  const rootIdx = nodes.length;
  nodes.push({ name: 'CAYMAZ_V3', children: nodes.map((_, i) => i) });
  const json = {
    asset: { version: '2.0', generator: 'HEPGO step2glb (occt-import-js)' },
    extensionsUsed: quant ? ['KHR_mesh_quantization'] : undefined, extensionsRequired: quant ? ['KHR_mesh_quantization'] : undefined,
    scene: 0, scenes: [{ nodes: [rootIdx] }], nodes, meshes: gmeshes, materials, accessors, bufferViews, buffers: [{ byteLength: binLen }],
  };
  if (!quant) { delete json.extensionsUsed; delete json.extensionsRequired; }
  let jsonBuf = Buffer.from(JSON.stringify(json));
  const jpad = (4 - (jsonBuf.length % 4)) % 4; if (jpad) jsonBuf = Buffer.concat([jsonBuf, Buffer.alloc(jpad, 0x20)]);
  const binBuf = Buffer.concat(bin);
  const total = 12 + 8 + jsonBuf.length + 8 + binBuf.length;
  const head = Buffer.alloc(12); head.writeUInt32LE(0x46546C67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(total, 8);
  const jh = Buffer.alloc(8); jh.writeUInt32LE(jsonBuf.length, 0); jh.writeUInt32LE(0x4E4F534A, 4);
  const bh = Buffer.alloc(8); bh.writeUInt32LE(binBuf.length, 0); bh.writeUInt32LE(0x004E4942, 4);
  fs.writeFileSync(OUT, Buffer.concat([head, jh, jsonBuf, bh, binBuf]));
  console.log('STEP üçgen', triTotal, 'toplam vertex', vertsTotal, 'kontrol yüzeyi', ctrls.length, '→', OUT, (total / 1024).toFixed(0), 'KB', quant ? '(quantized)' : '(float)');
})().catch(e => { console.error(e); process.exit(1); });
