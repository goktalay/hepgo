#!/usr/bin/env node
// RAR arşivini saf JS/WASM ile çıkarır (sistemde unrar yok): node-unrar-js.
// Kullanım:  NODE_PATH=/tmp/icept-node/node_modules node tools/unrar_extract.mjs arsiv.rar hedef_dizin
// Bağımlılık geçici dizine kurulur (depoya node_modules girmez):  cd /tmp/icept-node && npm i node-unrar-js
// Güvenlik: arşiv içeriği güvenilmeyen veridir — yalnız dosyaya yazılır, hiçbir şey çalıştırılmaz; '..'/mutlak yollar reddedilir.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(path.join(process.env.NODE_PATH || process.cwd(), 'x.js'));
const { createExtractorFromData } = require('node-unrar-js');

const [arsiv, hedef] = process.argv.slice(2);
if (!arsiv || !hedef) { console.error('kullanım: unrar_extract.mjs arsiv.rar hedef_dizin'); process.exit(2); }
const kok = path.resolve(hedef);
fs.mkdirSync(kok, { recursive: true });
const data = fs.readFileSync(arsiv);
const ex = await createExtractorFromData({ data: data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) });
const { files } = ex.extract();
for (const f of files) {
  const ad = f.fileHeader.name.replace(/\\/g, '/');
  const yol = path.resolve(kok, ad);
  if (!yol.startsWith(kok + path.sep)) { console.error('reddedildi (dizin dışı):', ad); continue; }
  if (f.fileHeader.flags.directory) { fs.mkdirSync(yol, { recursive: true }); continue; }
  fs.mkdirSync(path.dirname(yol), { recursive: true });
  fs.writeFileSync(yol, f.extraction);
  console.log(ad, f.extraction.length);
}
