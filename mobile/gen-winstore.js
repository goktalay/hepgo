// Windows Store ekran görüntüleri: landing'deki gerçek uygulama görsellerini 1920x1080 markalı tuvale yerleştirir
// (lacivert gradient arka plan + başlık + ekran görüntüsü gölgeli/yuvarlak köşe). Giriş gerektirmez.
const sharp = require('./node_modules/sharp');
const fs = require('fs');
const path = require('path');

const SRC = path.resolve(__dirname, '../central/veilox_server/static/img/landing/shots');
const LANG = process.argv[2] === 'en' ? 'en' : 'tr';   // node gen-winstore.js en → İngilizce başlık
const OUT = path.resolve(__dirname, LANG === 'en' ? 'deliver/winstore-en' : 'deliver/winstore');
fs.mkdirSync(OUT, { recursive: true });

const W = 1920, H = 1080;
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// [dosya, Türkçe başlık, İngilizce başlık]
const ITEMS = [
  ['dashboard', 'Kişisel Pano', 'Personal Dashboard'],
  ['orders', 'İş Emri Yönetimi', 'Work Orders'],
  ['printers', '3B Yazıcı Odası', '3D Printer Room'],
  ['reports', 'Raporlar (22+)', 'Reports (22+)'],
  ['mrp', 'MRP · Malzeme Planlama', 'MRP · Material Planning'],
  ['design', 'Endüstriyel Tasarım', 'Industrial Design'],
  ['field', 'Saha Yönetimi', 'Field Management'],
  ['hr', 'İnsan Kaynakları', 'Human Resources'],
  ['security', 'Güvenlik', 'Security'],
  ['meet', 'Görüntülü Toplantı', 'Video Meetings'],
  ['belge-list', 'Belge Yönetimi', 'Document Suite'],
  ['belge-excel', 'Uygulama İçi Excel', 'In-app Spreadsheet'],
  ['belge-word', 'Uygulama İçi Word', 'In-app Documents'],
  ['belge-sunum', 'Uygulama İçi Sunum', 'In-app Slides'],
  ['finance-cash', 'Nakit Akışı', 'Cash Flow'],
  ['finance-trial', 'Mizan', 'Trial Balance'],
  ['finance-statements', 'Finansal Tablolar', 'Financial Statements'],
  ['settings', 'Program Ayarları', 'System Settings'],
  ['mascot3d', 'Yapay Zeka Asistanı', 'AI Assistant'],
];

function bgSvg() {
  return Buffer.from(`<svg width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg">
    <defs><radialGradient id="g" cx="12%" cy="0%" r="130%">
      <stop offset="0%" stop-color="#20478f"/><stop offset="52%" stop-color="#0f1d3d"/><stop offset="100%" stop-color="#060b18"/>
    </radialGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/>
    <circle cx="${W - 180}" cy="150" r="320" fill="#2f6fed" opacity="0.10"/>
    <circle cx="140" cy="${H - 120}" r="260" fill="#3b82f6" opacity="0.08"/>
  </svg>`);
}

function titleSvg(tr) {
  return Buffer.from(`<svg width="${W}" height="140" xmlns="http://www.w3.org/2000/svg">
    <style>.b{font-family:'DejaVu Sans',system-ui,sans-serif;font-weight:800;fill:#ffffff}
    .s{font-family:'DejaVu Sans',system-ui,sans-serif;font-weight:600;fill:#9db8ff}</style>
    <text x="80" y="62" class="s" font-size="26" letter-spacing="2">HEPGO ERP</text>
    <text x="80" y="112" class="b" font-size="46">${esc(tr)}</text>
  </svg>`);
}

// yuvarlak köşe maskesi (ekran görüntüsü için)
function roundMask(w, h, r) {
  return Buffer.from(`<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg"><rect width="${w}" height="${h}" rx="${r}" ry="${r}"/></svg>`);
}

async function gen(file, tr, en, idx) {
  const label = LANG === 'en' ? en : tr;
  const src = path.join(SRC, file + '.webp');
  if (!fs.existsSync(src)) { console.log('atlandı (yok):', file); return; }
  // ekran görüntüsünü tuvale sığdır (başlık için üstte yer bırak)
  const boxW = 1640, boxH = 760;
  const shot = await sharp(src).resize({ width: boxW, height: boxH, fit: 'inside', withoutEnlargement: false }).toBuffer();
  const meta = await sharp(shot).metadata();
  const sw = meta.width, sh = meta.height;
  const rounded = await sharp(shot)
    .composite([{ input: roundMask(sw, sh, 18), blend: 'dest-in' }])
    .png().toBuffer();
  const left = Math.round((W - sw) / 2);
  const top = 190 + Math.round((H - 190 - sh) / 2);
  // gölge katmanı
  const shadow = Buffer.from(`<svg width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg">
    <rect x="${left + 10}" y="${top + 16}" width="${sw}" height="${sh}" rx="18" fill="#000000" opacity="0.45"/></svg>`);
  const out = path.join(OUT, `${String(idx + 1).padStart(2, '0')}-${file}.png`);
  await sharp(bgSvg())
    .composite([
      { input: shadow, left: 0, top: 0 },
      { input: await sharp(shadow).blur(22).toBuffer(), left: 0, top: 0 },
      { input: rounded, left, top },
      { input: titleSvg(label), left: 0, top: 36 },
    ])
    .png().toFile(out);
  console.log('üretildi:', path.basename(out), `(${sw}x${sh})`);
}

(async () => {
  let i = 0;
  for (const [f, tr, en] of ITEMS) { await gen(f, tr, en, i); i++; }
  console.log('\nToplam', fs.readdirSync(OUT).filter(x => x.endsWith('.png')).length, 'görüntü →', OUT);
})();
