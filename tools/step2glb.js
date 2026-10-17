// CAYMAZ V3 STEP → static/models/caymaz-sim.glb (uçuş simülatörü). Bağımlılık depoya girmez: geçici dizinde `npm i occt-import-js`, sonra
// NODE_PATH=<o dizin>/node_modules node tools/step2glb.js <CAYMAZ.step> static/models/caymaz-sim.glb [linDefl_mm=2] [angDefl_rad=0.6] [quant=1]
// Eksenler: STEP (X sağ kanat, Y burun, Z yukarı, mm) → glTF (X SOL, Y yukarı, Z burun, m) — flightsim3d.js'teki caymaz dönüşümüyle aynı
// (Rx+90°, Rz180° → gövde: burun +Y, sağ kanat +X, üst +Z). Orijin: kanat ortası (STEP Y=Y0). Renge göre iki mesh'e birleştirilir;
// arkaya prosedürel motor + "prop" düğümü (2 palalı pervane, Ø 0.81 m; glTF Z ekseni etrafında döner).
const fs = require('fs');
const occtimportjs = require('occt-import-js');
const [,, STEP, OUT, LD = '2.0', AD = '0.6', QUANT = '1'] = process.argv;
const Y0 = 1200, SCALE = 0.001;
const quant = QUANT !== '0';

(async () => {
  const occt = await occtimportjs();
  const buf = new Uint8Array(fs.readFileSync(STEP));
  const res = occt.ReadStepFile(buf, { linearUnit: 'millimeter', linearDeflectionType: 'absolute_value', linearDeflection: Number(LD), angularDeflection: Number(AD) });
  if (!res.success) throw new Error('STEP okunamadı');

  // ---- renge göre birleştirme ----
  const groups = { white: { pos: [], nor: [], idx: [], color: [0.90, 0.91, 0.94, 1], name: 'govde_beyaz' }, dark: { pos: [], nor: [], idx: [], color: [0.22, 0.24, 0.27, 1], name: 'govde_koyu' } };
  let triTotal = 0;
  for (const m of res.meshes) {
    const p = m.attributes.position.array, nrm = m.attributes.normal?.array, ix = m.index?.array;
    if (!p || !ix) continue;
    const g = (m.color && m.color[0] > 0.6) ? groups.white : groups.dark;
    const base = g.pos.length / 3;
    for (let k = 0; k < p.length; k += 3) {
      const x = p[k], y = p[k + 1], z = p[k + 2];
      g.pos.push(-x * SCALE, z * SCALE, (y - Y0) * SCALE);
      if (nrm) g.nor.push(-nrm[k], nrm[k + 2], nrm[k + 1]); else g.nor.push(0, 1, 0);
    }
    for (let k = 0; k < ix.length; k++) g.idx.push(base + ix[k]);
    triTotal += ix.length / 3;
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
  const meshes = [groups.white, groups.dark, eng, prop].filter(g => g.idx.length);
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
      const ps = new Int16Array(nv * 4);   // 4 bileşen? glTF VEC3 SHORT stride 6 → 8'e hizalama için byteStride 8
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
  console.log('STEP üçgen', triTotal, 'toplam vertex', vertsTotal, '→', OUT, (total / 1024).toFixed(0), 'KB', quant ? '(quantized)' : '(float)');
})().catch(e => { console.error(e); process.exit(1); });
