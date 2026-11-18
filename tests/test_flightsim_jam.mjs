// Uçuş Simülatörü — §48 KARIŞTIRMA tarayıcısız birim testi (static/js/modules/flightsim_jam.js):
//   • saf katman: ayar kırpma (sunucu sınırları: app/flightsim_jam.py), etkinlik, komut gövdesi, kısa ayar metni, düğme metni, sahne bandı,
//     telemetri birleştirme, rapor metni satırı.
//   • metinler: HEPGO Türkçe anahtar / `jam.*` anahtarı; HEPGO 6 dil sözlüklerinde karşılık.
//   • bağlanış: oturum ekranı (yalnız session.jam.supported), WS `jam` çerçevesi, rapor bölümü; SIMUMAV'da komut kapalı.
// Çalıştırma: node tests/test_flightsim_jam.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_CFG, GPS_LEVELS, JAM_TEXTS, LIMITS, bannerText, cfgText, cmdBody, isActive, jamBtnKey, jamReportLines, makeJamT, mergeTele, normalizeCfg } from '../static/js/modules/flightsim_jam.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const oku = p => readFileSync(join(ROOT, p), 'utf8');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

console.log('saf katman');
test('sınırlar ve seviyeler sunucuyla aynı', () => {
  const py = oku('app/flightsim_jam.py');
  assert.deepEqual(GPS_LEVELS, ['off', 'light', 'heavy', 'full']);
  assert.ok(/GPS_SEVIYELERI = \('off', 'light', 'heavy', 'full'\)/.test(py), 'GPS_SEVIYELERI');
  assert.deepEqual(LIMITS, { dir: [0, 360], speed: [0, 50], max_m: [1, 5000], dur_s: [0, 3600] });
  assert.ok(/HIZ_MAX = 50\.0/.test(py) && /SAPMA_MIN, SAPMA_MAX = 1\.0, 5000\.0/.test(py) && /SURE_MAX = 3600/.test(py), 'sunucu sınırları');
  assert.ok(/SPOOF_VARSAYILAN = \{'dir': 90\.0, 'speed': 2\.0, 'max_m': 200\.0\}/.test(py), 'varsayılan aldatma');
  assert.deepEqual(DEFAULT_CFG, { gps: 'off', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 0 });
});
test('ayar kırpma', () => {
  assert.deepEqual(normalizeCfg(), DEFAULT_CFG);
  assert.deepEqual(normalizeCfg({ gps: 'x', spoof: { on: 1, dir: 400, speed: 99, max_m: 0 }, dur_s: 99999 }),
    { gps: 'off', spoof: { on: true, dir: 0, speed: 50, max_m: 1 }, dur_s: 3600 });
  assert.deepEqual(normalizeCfg({ gps: 'heavy', spoof: { on: false, dir: '270', speed: '2.26', max_m: 'abc' }, dur_s: '' }),
    { gps: 'heavy', spoof: { on: false, dir: 270, speed: 2.3, max_m: 200 }, dur_s: 0 });
  assert.equal(normalizeCfg({ spoof: { dir: 360 } }).spoof.dir, 0);
  assert.equal(normalizeCfg({ spoof: { speed: 0 } }).spoof.speed, 0, '0 = anında sıçrama korunur');
  // sunucunun durum sözlüğü de ayar olarak okunur (sayfa yenileme / ikinci izleyici)
  assert.deepEqual(normalizeCfg({ supported: true, on: true, gps: 'light', spoof: { on: true, dir: 45.0, speed: 1.5, max_m: 80.0 }, dur_s: 30, left_s: 12 }),
    { gps: 'light', spoof: { on: true, dir: 45, speed: 1.5, max_m: 80 }, dur_s: 30 });
});
test('etkinlik ve komut gövdesi', () => {
  assert.equal(isActive(DEFAULT_CFG), false); assert.equal(isActive(null), false);
  assert.equal(isActive({ gps: 'light', spoof: { on: false } }), true); assert.equal(isActive({ gps: 'off', spoof: { on: true } }), true);
  assert.equal(cmdBody(DEFAULT_CFG), null, 'etkin olmayan ayar gönderilmez');
  assert.deepEqual(cmdBody({ gps: 'full', dur_s: 20 }), { gps: 'full', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 20 });
  assert.deepEqual(cmdBody({ spoof: { on: true, dir: 180, speed: 0, max_m: 50 } }), { gps: 'off', spoof: { on: true, dir: 180, speed: 0, max_m: 50 }, dur_s: 0 });
});
test('kısa ayar metni ve düğme metni', () => {
  assert.equal(cfgText(DEFAULT_CFG), 'Kapalı');
  assert.equal(cfgText({ gps: 'heavy', dur_s: 30 }), 'GPS karıştırma: Ağır · 30 sn');
  assert.equal(cfgText({ gps: 'light', spoof: { on: true, dir: 90, speed: 2, max_m: 200 } }), 'GPS karıştırma: Hafif · GPS aldatma 90° · 2 m/s · 200 m');
  const tx = Object.fromEntries(JAM_TEXTS);
  assert.equal(tx[jamBtnKey({ on: false, real: false })], 'Karıştırma');
  assert.equal(tx[jamBtnKey({ on: true, real: true })], 'Karıştırılıyor');
  assert.equal(tx[jamBtnKey({ on: false, real: true })], 'Toparlanıyor');
});
test('sahne bandı: seviye · aldatma · sapma · seyrüsefer hatası · kalan; toparlanma; sahte kip', () => {
  assert.equal(bannerText({ supported: true, on: false, real: false }), null);
  assert.equal(bannerText({ supported: false, on: true }), null);
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'heavy', spoof: { on: false }, nav_err: 12.34, left_s: 9.2, sim: 'sitl' }),
    { main: 'KARIŞTIRMA · GPS KESİNTİLİ', sub: 'seyrüsefer hatası 12.3 m · kalan 10 sn', recover: false });
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'off', spoof: { on: true }, off_m: 60, nav_err: 58.7, left_s: null, sim: 'sitl' }),
    { main: 'KARIŞTIRMA · GPS ALDATMA', sub: 'sahte konum sapması 60.0 m · seyrüsefer hatası 58.7 m', recover: false });
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'full', spoof: { on: false }, sim: 'fake' }),
    { main: 'KARIŞTIRMA · GPS YOK', sub: 'yalnız göstergeler', recover: false });
  assert.deepEqual(bannerText({ supported: true, on: false, real: true, nav_err: 4 }), { main: 'GPS TOPARLANIYOR', sub: 'seyrüsefer hatası 4.0 m', recover: true });
  assert.equal(bannerText({ supported: true, on: true, gps: 'light', spoof: { on: false } }, k => k).main, 'jam.banner · jam.b_light');
});
test('telemetri birleştirme: tele.jam + tele.nav_err', () => {
  const st = { supported: true, on: true, real: true, sim: 'sitl', off_m: 0, left_s: null, nav_err: null };
  assert.deepEqual(mergeTele(st, { jam: { gps: 'off', spoof: true, off_m: 12.5, left_s: 18.2 }, nav_err: 11.9 }), { ...st, off_m: 12.5, left_s: 18.2, nav_err: 11.9 });
  assert.equal(mergeTele({ ...st, on: false }, { nav_err: 2.5 }).nav_err, 2.5, 'toparlanırken hata izlenir');
  assert.equal(mergeTele({ ...st, on: false, real: false, nav_err: 3 }, { nav_err: 9 }).nav_err, 3, 'kapalıyken dokunulmaz');
  const off = { supported: false };
  assert.equal(mergeTele(off, { jam: { off_m: 5 } }), off);
});
const SUM = { jam: { count: 3, gps_s: { light: 30.2, heavy: 24 }, spoof_s: 45.4, max_off_m: 60, max_nav_err: 60.12, sim: 'sitl' } };
test('rapor metni satırı', () => {
  assert.deepEqual(jamReportLines(SUM), ['Karıştırma: 3 kez · GPS karıştırma hafif 30 sn, ağır 24 sn · GPS aldatma 45 sn (en büyük sapma 60.0 m) · en büyük seyrüsefer hatası 60.1 m']);
  assert.deepEqual(jamReportLines({ jam: { count: 1, gps_s: { full: 12 }, spoof_s: 0, max_off_m: 0, max_nav_err: 0, sim: 'fake' } }), ['Karıştırma: 1 kez · GPS karıştırma tam 12 sn · yalnız göstergeler']);
  assert.deepEqual(jamReportLines({}), []); assert.deepEqual(jamReportLines({ jam: null }), []); assert.deepEqual(jamReportLines({ jam: { count: 0 } }), []);
});

console.log('metinler');
test('makeJamT: HEPGO Türkçe metni anahtar verir; anahtarlı kipte jam.* (yoksa Türkçe)', () => {
  const seen = [];
  const T = makeJamT((s, p) => { seen.push(s); return `«${s}»${p ? JSON.stringify(p) : ''}`; });
  assert.equal(T('jam.start'), '«Başlat»'); assert.equal(T('jam.b_err', { m: '3.0' }), '«seyrüsefer hatası {m} m»{"m":"3.0"}');
  assert.deepEqual(seen, ['Başlat', 'seyrüsefer hatası {m} m']);
  const K = makeJamT((k, p) => (k === 'jam.start' ? 'Start' : k), true);
  assert.equal(K('jam.start'), 'Start'); assert.equal(K('jam.b_left', { s: 5 }), 'kalan 5 sn');
  assert.equal(makeJamT(null)('jam.err', { e: 'x' }), 'Karıştırma: x');
  const keys = JAM_TEXTS.map(([k]) => k);
  assert.equal(new Set(keys).size, keys.length, 'anahtarlar tekil');
  for (const v of GPS_LEVELS) assert.ok(keys.includes(`jam.${v}`) && keys.includes(`jam.${v}_t`), v);
  for (const v of GPS_LEVELS.slice(1)) assert.ok(keys.includes(`jam.b_${v}`), v);
});
const REPORT = ['{n} kez', 'hafif', 'ağır', 'tam', 'en büyük sapma', 'en büyük seyrüsefer hatası', 'Karıştırma sayısı', 'GPS karıştırma süresi', 'GPS aldatma süresi',
  'En büyük sahte konum sapması', 'En büyük seyrüsefer hatası', 'Seviye başına süre', "Bu oturum SITL'siz çalıştı: karıştırma yalnız göstergeleri etkiledi",
  'Seyrüsefer hatası: otopilotun sandığı konum ile aracın gerçek konumu arasındaki yatay mesafe'];
test('HEPGO 6 dil: karıştırma metinleri', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const need = [...JAM_TEXTS.map(([, v]) => v), ...REPORT];
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = need.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
  const src = oku('static/js/modules/flightsim_jam.js');
  for (const m of src.matchAll(/\btr\('((?:[^'\\]|\\.)+)'/g)) assert.ok(need.includes(m[1].replace(/\\'/g, "'")), `rapor metni listede yok: ${m[1]}`);
});

console.log('bağlanış');
test('alt bant: panel Başlat / Uygula sonrası kapanır; Esc / dışarı tıklama kapatır; etkin olmayan ayar gönderilmez', () => {
  const src = oku('static/js/modules/flightsim_jam.js');
  assert.ok(/fs-jam-pop/.test(src) && /if \(on\) setOpen\(false\)/.test(src), 'başlayınca panel kapanır');
  assert.ok(/key === 'Escape' && !pop\.hidden/.test(src) && /root\.contains\(e\.target\)/.test(src), 'Esc / dışarı tıklama kapatır');
  assert.ok(/if \(!body\) \{ onEvent\(T\('jam\.nothing'\), 'warning'\)/.test(src), 'boş ayar uyarısı');
  assert.ok(/cmd\('jam', body\)/.test(src) && /\{ off: true \}/.test(src), 'jam komutu');
  assert.ok(/reason === 'settled'\) onEvent\(T\('jam\.ev_settled'\)/.test(src), 'toparlanma olayı ön yüzde');
  assert.ok(!/toLocaleUpperCase/.test(src), 'dile bağlı büyük harf çevirisi yok');
});
test('oturum ekranı ve rapor: yalnız desteklenen oturumda; WS jam çerçevesi; SIMUMAV komutu kapalı', () => {
  const fs = oku('static/js/modules/flightsim.js');
  assert.ok(/const jam = canWrite && !replay && session\.jam\?\.supported \? createJam\(/.test(fs), 'createJam koşulu');
  assert.ok(/jam \? jam\.el : null/.test(fs) && /jam\?\.update\(t\)/.test(fs) && /m\.t === 'jam'\) \{ jam\?\.onFrame\(m\)/.test(fs) && /jam\?\.dispose\(\)/.test(fs), 'bant / tele / çerçeve / dispose');
  const rp = oku('static/js/modules/flightsim_report.js');
  assert.ok(/jamReportLines\(sum, tr\)/.test(rp) && /jamSection\(sum, tr, h\)/.test(rp), 'rapor');
  assert.ok(/SIM_KOMUT = set\(flightsim\.KOMUTLAR\) - \{'jam'\}/.test(oku('app/simumav/routers/fly.py')), 'SIMUMAV komut kümesi');
  assert.ok(oku('tools/simumav_export.py').includes("'app/flightsim_jam.py'"), 'dışa aktarım çekirdeği');
});

console.log(`\n${n} test geçti`);
