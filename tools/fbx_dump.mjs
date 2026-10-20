#!/usr/bin/env node
// FBX → JSON ağ dökümü (three.js FBXLoader, node'da; DOM yok — doku yükleme taklit edilir, yalnız dosya adı kaydedilir).
// Kullanım:  NODE_PATH=/tmp/icept-node/node_modules node tools/fbx_dump.mjs girdi.fbx cikti.json
// Bağımlılık geçici dizinde:  cd /tmp/icept-node && npm i three@0.170.0   (depoya node_modules girmez)
// Çıktı: {meshes:[{name, path:[ata adları], matrixWorld[16], position[], normal[], uv[], index[]|null, groups:[{start,count,materialIndex}],
//          materials:[{name, color:[r,g,b], map, emissive, opacity}]}]} — koordinatlar FBX (three) dünya çerçevesinde, birim FBX'in kendi birimi.
// Python tarafı (tools/icept_models_build.py) GLB'yi kurar. Güvenlik: FBX güvenilmeyen veri; yalnız ayrıştırılır, hiçbir şey çalıştırılmaz.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const nm = process.env.NODE_PATH || '/tmp/icept-node/node_modules';
const THREE = await import(pathToFileURL(path.join(nm, 'three/build/three.module.js')).href);
const { FBXLoader } = await import(pathToFileURL(path.join(nm, 'three/examples/jsm/loaders/FBXLoader.js')).href);

THREE.TextureLoader.prototype.load = function (url) { const t = new THREE.Texture(); t.userData.url = String(url); return t; };   // DOM'suz doku

const [girdi, cikti] = process.argv.slice(2);
if (!girdi || !cikti) { console.error('kullanım: fbx_dump.mjs girdi.fbx cikti.json'); process.exit(2); }
const buf = fs.readFileSync(girdi);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const root = new FBXLoader().parse(ab, path.dirname(path.resolve(girdi)) + '/');
root.updateMatrixWorld(true);
const arr = a => (a ? Array.from(a.array) : null);
const meshes = [];
root.traverse(o => {
  if (!o.isMesh) return;
  const g = o.geometry, yol = [];
  for (let p = o.parent; p && p !== root; p = p.parent) yol.unshift(p.name);
  const mats = (Array.isArray(o.material) ? o.material : [o.material]).map(m => ({
    name: m.name, color: m.color ? [m.color.r, m.color.g, m.color.b] : null, map: m.map?.userData?.url || null,
    emissive: m.emissive ? [m.emissive.r, m.emissive.g, m.emissive.b] : null, opacity: m.opacity, transparent: m.transparent,
  }));
  meshes.push({ name: o.name, path: yol, matrixWorld: o.matrixWorld.elements.slice(), position: arr(g.attributes.position), normal: arr(g.attributes.normal),
    uv: arr(g.attributes.uv), index: arr(g.index), groups: g.groups, materials: mats });
});
fs.writeFileSync(cikti, JSON.stringify({ meshes }));
console.log(`${meshes.length} mesh → ${cikti}`);
for (const m of meshes) console.log(m.name, '|', m.path.join('/'), '| köşe', m.position.length / 3, '| mat', m.materials.map(x => `${x.name}:${x.map || ''}`).join(','));
