// Uçuş Simülatörü — §48 / §49 KARIŞTIRMA tarayıcısız birim testi (static/js/modules/flightsim_jam.js):
//   • saf katman: ayar kırpma (sunucu sınırları: app/flightsim_jam.py), etkinlik, komut gövdesi, kısa ayar metni, düğme metni, sahne bandı,
//     telemetri birleştirme, rapor metni satırı.
//   • §49: kumanda / telemetri bağlantısı, karıştırıcı bölgesi (bekleme bandı, konum yardımcıları), konum kaybı tepkisi, sahne modeli (bölge + hayalet),
//     küçük harita ölçeği / izdüşümü, telemetri kesikken gösterge dondurma.
//   • metinler: HEPGO Türkçe anahtar / `jam.*` anahtarı; HEPGO 6 dil sözlüklerinde karşılık.
//   • bağlanış: oturum ekranı (yalnız session.jam.supported), WS `jam` çerçevesi, rapor bölümü; SIMUMAV'da komut kapalı.
// Çalıştırma: node tests/test_flightsim_jam.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_CFG, FS_MODES, GHOST_MIN_M, GPS_LEVELS, JAM_TEXTS, LIMITS, bannerText, cfgText, cmdBody, distM, fmtDist, headingOf, isActive, jamBtnKey, jamReportLines, makeJamT,
  mapProject, mapScale, mapUnproject, mergeTele, moveM, normalizeCfg, offsetM, parseLatLon, sceneModel, tlmLost, zoneAhead } from '../static/js/modules/flightsim_jam.js';
import { GHOST_COLOR, ZONE_COLORS, createJamLayer } from '../static/js/modules/flightsim_jam3d.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const oku = p => readFileSync(join(ROOT, p), 'utf8');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const yakin = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg || ''} ${a} ≉ ${b}`);
const ZONE0 = { on: false, lat: null, lon: null, r_m: 300 }, LINK0 = { rc: false, tlm: false, zone: ZONE0 };

console.log('saf katman');
test('sınırlar ve seviyeler sunucuyla aynı', () => {
  const py = oku('app/flightsim_jam.py');
  assert.deepEqual(GPS_LEVELS, ['off', 'light', 'heavy', 'full']);
  assert.ok(/GPS_SEVIYELERI = \('off', 'light', 'heavy', 'full'\)/.test(py), 'GPS_SEVIYELERI');
  assert.deepEqual(LIMITS, { dir: [0, 360], speed: [0, 50], max_m: [1, 5000], dur_s: [0, 3600], r_m: [10, 20000] });
  assert.ok(/BOLGE_R_MIN, BOLGE_R_MAX, BOLGE_R_VARSAYILAN = 10\.0, 20000\.0, 300\.0/.test(py), 'bölge yarıçapı sınırları');
  assert.deepEqual(FS_MODES, ['althold', 'land', 'none']);
  assert.ok(/FS_SECENEKLERI = \('althold', 'land', 'none'\)/.test(py) && /FS_DEGER = \{'none': 0\.0, 'land': 1\.0, 'althold': 2\.0\}/.test(py) && /FS_VARSAYILAN = 'althold'/.test(py), 'konum kaybı tepkisi (FS_EKF_ACTION)');
  assert.ok(/HIZ_MAX = 50\.0/.test(py) && /SAPMA_MIN, SAPMA_MAX = 1\.0, 5000\.0/.test(py) && /SURE_MAX = 3600/.test(py), 'sunucu sınırları');
  assert.ok(/SPOOF_VARSAYILAN = \{'dir': 90\.0, 'speed': 2\.0, 'max_m': 200\.0\}/.test(py), 'varsayılan aldatma');
  assert.deepEqual(DEFAULT_CFG, { gps: 'off', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 0, ...LINK0 });
});
test('ayar kırpma', () => {
  assert.deepEqual(normalizeCfg(), DEFAULT_CFG);
  assert.deepEqual(normalizeCfg({ gps: 'x', spoof: { on: 1, dir: 400, speed: 99, max_m: 0 }, dur_s: 99999 }),
    { gps: 'off', spoof: { on: true, dir: 0, speed: 50, max_m: 1 }, dur_s: 3600, ...LINK0 });
  assert.deepEqual(normalizeCfg({ gps: 'heavy', spoof: { on: false, dir: '270', speed: '2.26', max_m: 'abc' }, dur_s: '' }),
    { gps: 'heavy', spoof: { on: false, dir: 270, speed: 2.3, max_m: 200 }, dur_s: 0, ...LINK0 });
  assert.equal(normalizeCfg({ spoof: { dir: 360 } }).spoof.dir, 0);
  assert.equal(normalizeCfg({ spoof: { speed: 0 } }).spoof.speed, 0, '0 = anında sıçrama korunur');
  // sunucunun durum sözlüğü de ayar olarak okunur (sayfa yenileme / ikinci izleyici)
  assert.deepEqual(normalizeCfg({ supported: true, on: true, gps: 'light', spoof: { on: true, dir: 45.0, speed: 1.5, max_m: 80.0 }, dur_s: 30, left_s: 12 }),
    { gps: 'light', spoof: { on: true, dir: 45, speed: 1.5, max_m: 80 }, dur_s: 30, ...LINK0 });
  // §49 bağlantı + bölge: merkez 7 haneye yuvarlanır, yarıçap kırpılır; merkezsiz / geçersiz merkezli bölge açılmaz
  assert.deepEqual(normalizeCfg({ rc: 1, tlm: 0, zone: { on: true, lat: 39.9251234567, lon: 32.8371234567, r_m: 5 } }),
    { ...DEFAULT_CFG, rc: true, zone: { on: true, lat: 39.9251235, lon: 32.8371235, r_m: 10 } });
  assert.deepEqual(normalizeCfg({ zone: { on: true, r_m: 99999 } }).zone, { on: false, lat: null, lon: null, r_m: 20000 });
  assert.deepEqual(normalizeCfg({ zone: { on: true, lat: 95, lon: 10 } }).zone, ZONE0);
  // sunucu durumundaki bölge alanları (inside / dist_m) ayara taşınmaz
  assert.deepEqual(normalizeCfg({ on: true, rc: true, zone: { on: true, lat: 39.9, lon: 32.8, r_m: 250, inside: false, dist_m: 400 } }).zone, { on: true, lat: 39.9, lon: 32.8, r_m: 250 });
});
test('etkinlik ve komut gövdesi', () => {
  assert.equal(isActive(DEFAULT_CFG), false); assert.equal(isActive(null), false);
  assert.equal(isActive({ gps: 'light', spoof: { on: false } }), true); assert.equal(isActive({ gps: 'off', spoof: { on: true } }), true);
  assert.equal(cmdBody(DEFAULT_CFG), null, 'etkin olmayan ayar gönderilmez');
  assert.deepEqual(cmdBody({ gps: 'full', dur_s: 20 }), { gps: 'full', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 20, ...LINK0 });
  assert.deepEqual(cmdBody({ spoof: { on: true, dir: 180, speed: 0, max_m: 50 } }), { gps: 'off', spoof: { on: true, dir: 180, speed: 0, max_m: 50 }, dur_s: 0, ...LINK0 });
  // §49: kumanda / telemetri tek başına etkin; bölge tek başına etki değildir; konum kaybı tepkisi yalnız geçerliyse gönderilir
  assert.equal(isActive({ rc: true }), true); assert.equal(isActive({ tlm: true }), true);
  const Z = { on: true, lat: 39.9, lon: 32.8, r_m: 300 };
  assert.equal(isActive({ zone: Z }), false); assert.equal(cmdBody({ zone: Z }), null, 'etkisiz bölge gönderilmez');
  assert.deepEqual(cmdBody({ rc: true, zone: Z }), { ...DEFAULT_CFG, rc: true, zone: Z });
  assert.equal(cmdBody({ gps: 'full' }, 'land').fs, 'land'); assert.equal(cmdBody({ gps: 'full' }, 'althold').fs, 'althold');
  assert.ok(!('fs' in cmdBody({ gps: 'full' }, 'x')) && !('fs' in cmdBody({ gps: 'full' })), 'kopter dışı: fs alanı yok');
});
test('kısa ayar metni ve düğme metni', () => {
  assert.equal(cfgText(DEFAULT_CFG), 'Kapalı');
  assert.equal(cfgText({ gps: 'heavy', dur_s: 30 }), 'GPS karıştırma: Ağır · 30 sn');
  assert.equal(cfgText({ gps: 'light', spoof: { on: true, dir: 90, speed: 2, max_m: 200 } }), 'GPS karıştırma: Hafif · GPS aldatma 90° · 2 m/s · 200 m');
  assert.equal(cfgText({ rc: true, tlm: true, zone: { on: true, lat: 39.9, lon: 32.8, r_m: 300 }, dur_s: 30 }), 'kumanda kesik · telemetri kesik · bölge 300 m · 30 sn');
  assert.equal(cfgText({ zone: { on: true, lat: 39.9, lon: 32.8, r_m: 300 } }), 'Kapalı', 'etkisiz bölge');
  const tx = Object.fromEntries(JAM_TEXTS);
  assert.equal(tx[jamBtnKey({ on: false, real: false })], 'Karıştırma');
  assert.equal(tx[jamBtnKey({ on: true, real: true })], 'Karıştırılıyor');
  assert.equal(tx[jamBtnKey({ on: false, real: true })], 'Toparlanıyor');
});
test('sahne bandı: seviye · aldatma · sapma · seyrüsefer hatası · kalan; toparlanma; sahte kip', () => {
  assert.equal(bannerText({ supported: true, on: false, real: false }), null);
  assert.equal(bannerText({ supported: false, on: true }), null);
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'heavy', spoof: { on: false }, nav_err: 12.34, left_s: 9.2, sim: 'sitl' }),
    { main: 'KARIŞTIRMA · GPS KESİNTİLİ', sub: 'seyrüsefer hatası 12.3 m · kalan 10 sn', recover: false, wait: false });
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'off', spoof: { on: true }, off_m: 60, nav_err: 58.7, left_s: null, sim: 'sitl' }),
    { main: 'KARIŞTIRMA · GPS ALDATMA', sub: 'sahte konum sapması 60.0 m · seyrüsefer hatası 58.7 m', recover: false, wait: false });
  assert.deepEqual(bannerText({ supported: true, on: true, gps: 'full', spoof: { on: false }, sim: 'fake' }),
    { main: 'KARIŞTIRMA · GPS YOK', sub: 'yalnız göstergeler', recover: false, wait: false });
  assert.deepEqual(bannerText({ supported: true, on: false, real: true, nav_err: 4 }), { main: 'GPS TOPARLANIYOR', sub: 'seyrüsefer hatası 4.0 m', recover: true, wait: false });
  assert.equal(bannerText({ supported: true, on: true, gps: 'light', spoof: { on: false } }, k => k).main, 'jam.banner · jam.b_light');
});
test('telemetri birleştirme: tele.jam + tele.nav_err', () => {
  const st = { supported: true, on: true, real: true, sim: 'sitl', off_m: 0, left_s: null, nav_err: null };
  assert.deepEqual(mergeTele(st, { jam: { gps: 'off', spoof: true, off_m: 12.5, left_s: 18.2 }, nav_err: 11.9 }), { ...st, off_m: 12.5, left_s: 18.2, nav_err: 11.9 });
  // §49: bölge açıkken tele.jam etkinliği ve merkeze mesafeyi de taşır
  const zs = { ...st, zone: { on: true, lat: 1, lon: 2, r_m: 300 } };
  assert.deepEqual(mergeTele(zs, { jam: { gps: 'full', spoof: false, off_m: 0, left_s: null, rc: true, tlm: false, active: false, inside: false, dist_m: 420.5 }, nav_err: 1 }),
    { ...zs, active: false, nav_err: 1, zone: { on: true, lat: 1, lon: 2, r_m: 300, inside: false, dist_m: 420.5 } });
  assert.equal(mergeTele({ ...st, on: false }, { nav_err: 2.5 }).nav_err, 2.5, 'toparlanırken hata izlenir');
  assert.equal(mergeTele({ ...st, on: false, real: false, nav_err: 3 }, { nav_err: 9 }).nav_err, 3, 'kapalıyken dokunulmaz');
  const off = { supported: false };
  assert.equal(mergeTele(off, { jam: { off_m: 5 } }), off);
});
const SUM = { jam: { count: 3, gps_s: { light: 30.2, heavy: 24 }, spoof_s: 45.4, max_off_m: 60, max_nav_err: 60.12, sim: 'sitl' } };
test('rapor metni satırı', () => {
  assert.deepEqual(jamReportLines(SUM), ['Karıştırma: 3 kez · GPS karıştırma hafif 30 sn, ağır 24 sn · GPS aldatma 45 sn (en büyük sapma 60.0 m) · en büyük seyrüsefer hatası 60.1 m']);
  assert.deepEqual(jamReportLines({ jam: { count: 1, gps_s: { full: 12 }, spoof_s: 0, max_off_m: 0, max_nav_err: 0, sim: 'fake' } }), ['Karıştırma: 1 kez · GPS karıştırma tam 12 sn · yalnız göstergeler']);
  // §49: kumanda / telemetri kesinti süreleri ve bölge (giriş sayısı)
  assert.deepEqual(jamReportLines({ jam: { count: 2, gps_s: { full: 12 }, spoof_s: 0, rc_s: 20.4, tlm_s: 8, max_off_m: 0, max_nav_err: 30, sim: 'sitl', zone: { lat: 39.93, lon: 32.84, r_m: 300, entries: 2 } } }),
    ['Karıştırma: 2 kez · GPS karıştırma tam 12 sn · kumanda bağlantısı 20 sn · telemetri bağlantısı 8 sn · bölge 300 m (2 giriş) · en büyük seyrüsefer hatası 30.0 m']);
  assert.deepEqual(jamReportLines({}), []); assert.deepEqual(jamReportLines({ jam: null }), []); assert.deepEqual(jamReportLines({ jam: { count: 0 } }), []);
});

test('§49 sahne bandı: kumanda / telemetri; gaz ortada; bölge dışında bekleme', () => {
  const B = { supported: true, on: true, active: true, gps: 'off', spoof: { on: false }, sim: 'sitl' };
  assert.deepEqual(bannerText({ ...B, rc: true, tlm: true, thr_mid: true, left_s: null }),
    { main: 'KARIŞTIRMA · KUMANDA YOK · TELEMETRİ YOK', sub: 'gaz ortada (irtifa korunur) · göstergeler son alınan değerde', recover: false, wait: false });
  assert.deepEqual(bannerText({ ...B, gps: 'full', thr_mid: true, nav_err: 3 }),
    { main: 'KARIŞTIRMA · GPS YOK', sub: 'seyrüsefer hatası 3.0 m · gaz ortada (irtifa korunur)', recover: false, wait: false });
  // bölge açık, araç dışarıda: etkiler uygulanmaz → bekleme bandı (sınıra mesafe = merkeze mesafe − yarıçap)
  const W = { ...B, active: false, gps: 'full', rc: true, zone: { on: true, lat: 39.9, lon: 32.8, r_m: 300, inside: false, dist_m: 450.4 }, real: false, left_s: 40 };
  assert.deepEqual(bannerText(W), { main: 'KARIŞTIRICI BÖLGESİ DIŞINDA', sub: 'bölge sınırına 150 m · kalan 40 sn', recover: false, wait: true });
  assert.equal(bannerText({ ...W, real: true, nav_err: 7 }).sub, 'bölge sınırına 150 m · seyrüsefer hatası 7.0 m · kalan 40 sn', 'bölgeden çıkınca toparlanma izlenir');
  assert.equal(bannerText({ ...W, active: true, zone: { ...W.zone, inside: true, dist_m: 120 } }).main, 'KARIŞTIRMA · GPS YOK · KUMANDA YOK');
});
test('§49 telemetri kesik: yalnız etkinken göstergeler donar', () => {
  assert.equal(tlmLost({ jam: { tlm: true, active: true } }), true);
  assert.equal(tlmLost({ jam: { tlm: true, active: false } }), false, 'bölge dışında bağlantı sürer');
  assert.equal(tlmLost({ jam: { tlm: false, active: true } }), false); assert.equal(tlmLost({}), false); assert.equal(tlmLost(null), false);
});
const A = { lat: 39.925, lon: 32.837 };
test('§49 konum yardımcıları: enlem-boylam okuma, metre kaydırma, mesafe, baş açısı, "aracın önüne"', () => {
  assert.deepEqual(parseLatLon('39.92500, 32.83700'), A); assert.deepEqual(parseLatLon(' 39.925 ; 32.837 '), A);
  assert.deepEqual(parseLatLon('-33.5,-70.6'), { lat: -33.5, lon: -70.6 });
  for (const bad of ['95, 10', '10, 190', 'abc', '39.9', '', null]) assert.equal(parseLatLon(bad), null, String(bad));
  const b = moveM(A, 300, -400), o = offsetM(A, b);
  yakin(o.e, 300, 0.05, 'doğu'); yakin(o.n, -400, 0.05, 'kuzey'); yakin(distM(A, b), 500, 0.05, 'mesafe');
  assert.deepEqual(moveM(A, 0, 0), A);
  assert.equal(headingOf({ heading: 135 }), 135); assert.equal(headingOf({ yaw: Math.PI / 2 }), 90); assert.equal(headingOf({ yaw: -Math.PI / 2 }), 270);
  assert.equal(headingOf({}), 0); assert.equal(headingOf(null), 0);
  // merkez = araç + (yarıçap + 150 m) burun yönünde → araç bölgenin DIŞINDA başlar (içine uçulur)
  const z = zoneAhead({ ...A, hdg: 90 }, 300), zo = offsetM(A, z);
  yakin(zo.e, 450, 0.05, 'doğuya'); yakin(zo.n, 0, 0.05, 'kuzey 0'); assert.ok(distM(A, z) > 300);
  const z2 = offsetM(A, zoneAhead({ ...A, hdg: 0 }, 100, 50)); yakin(z2.n, 150, 0.05, 'kuzeye'); yakin(z2.e, 0, 0.05);
});
test('§49 sahne modeli: bölge (içeride / dışarıda / taslak) + hayalet (otopilotun sandığı konum)', () => {
  const st = { supported: true, on: true, active: true, real: true, sim: 'sitl', gps: 'off', spoof: { on: true }, zone: { on: true, lat: 39.93, lon: 32.84, r_m: 300, inside: true, dist_m: 100 } };
  const cfg = normalizeCfg(st), t = { ...A, heading: 45, nav_lat: 39.9255, nav_lon: 32.837, nav_err: 55.6 };
  assert.deepEqual(sceneModel(st, cfg, t, { home: A }), { zone: { lat: 39.93, lon: 32.84, r_m: 300, state: 'in' }, ghost: { lat: 39.9255, lon: 32.837, err: 55.6 },
    veh: { ...A, hdg: 45 }, home: A, live: true });
  assert.equal(sceneModel({ ...st, active: false, zone: { ...st.zone, inside: false } }, cfg, t).zone.state, 'out');
  // panel açık + ayar sunucudakinden farklı → taslak; panel kapalıyken sunucudaki bölge
  const moved = { ...cfg, zone: { ...cfg.zone, r_m: 500 } };
  assert.deepEqual(sceneModel(st, moved, t, { panelOpen: true }).zone, { lat: 39.93, lon: 32.84, r_m: 500, state: 'draft' });
  assert.equal(sceneModel(st, moved, t, { panelOpen: false }).zone.state, 'in');
  assert.equal(sceneModel(st, cfg, t, { panelOpen: true }).zone.state, 'in', 'değişmemiş ayar taslak değildir');
  // boşta: yalnız panel açıkken taslak bölge; hayalet yok
  const idle = { supported: true, on: false, real: false };
  const d = sceneModel(idle, normalizeCfg({ zone: { on: true, lat: 39.93, lon: 32.84, r_m: 200 } }), t, { panelOpen: true });
  assert.deepEqual([d.zone.state, d.ghost, d.live], ['draft', null, false]);
  assert.deepEqual(sceneModel(idle, DEFAULT_CFG, t), { zone: null, ghost: null, veh: { ...A, hdg: 45 }, home: null, live: false });
  // hayalet: seyrüsefer hatası eşiğin altındayken çizilmez (araçla üst üste); toparlanırken (on değil, real) sürer
  assert.equal(GHOST_MIN_M, 2);
  assert.equal(sceneModel(st, cfg, { ...t, nav_err: 1.2 }).ghost, null);
  assert.deepEqual(sceneModel({ ...st, on: false, zone: { ...st.zone, on: false } }, DEFAULT_CFG, t).ghost, { lat: 39.9255, lon: 32.837, err: 55.6 });
  assert.equal(sceneModel(st, cfg, { ...A, heading: 45 }).ghost, null, 'sahte kinematik: otopilot konumu yok');
  assert.equal(sceneModel(st, cfg, null).veh, null);
});
test('§49 küçük harita: 1-2-5 ölçek, izdüşümü ve tersi', () => {
  assert.equal(mapScale({}), 100);
  assert.equal(mapScale({ veh: A, ghost: moveM(A, 0, 90) }), 200); assert.equal(mapScale({ veh: A, ghost: moveM(A, 0, 180) }), 500);
  const zin = { ...moveM(A, 400, 0), r_m: 300, state: 'in' };
  assert.equal(mapScale({ veh: A, zone: zin }), 1000, 'bölgenin tamamı sığar (400 + 300)');
  assert.equal(mapScale({ veh: A, zone: { ...A, r_m: 20000 } }), 50000);
  assert.ok(mapScale({ veh: A, ghost: moveM(A, 0, 90) }, 1.2) >= mapScale({ veh: A, ghost: moveM(A, 0, 90) }), 'küçülme eşiği büyütmez değil, küçültmez');
  // kuzey yukarı: doğu +x, kuzey −y; merkez tuvalin ortası
  assert.deepEqual(mapProject(A, 500, 200, A), { x: 100, y: 100 });
  const p = mapProject(A, 500, 200, moveM(A, 250, 250)); yakin(p.x, 150, 0.05); yakin(p.y, 50, 0.05);
  const u = offsetM(A, mapUnproject(A, 500, 200, 150, 50)); yakin(u.e, 250, 0.05); yakin(u.n, 250, 0.05);
  assert.deepEqual([fmtDist(80), fmtDist(500), fmtDist(1000), fmtDist(2500), fmtDist(20000)], ['80 m', '500 m', '1 km', '2.5 km', '20 km']);
});
test('§49 3B katman: three import etmez; uygun olmayan sahnede null', () => {
  const src = oku('static/js/modules/flightsim_jam3d.js');
  assert.ok(!/^import /m.test(src), 'jam3d bağımsız (sahnenin three nesnesini kullanır)');
  assert.equal(createJamLayer(null), null); assert.equal(createJamLayer({}), null); assert.equal(createJamLayer({ three: {}, scene: {} }), null);
  assert.deepEqual(Object.keys(ZONE_COLORS), ['in', 'out', 'draft']); assert.equal(typeof GHOST_COLOR, 'number');
  assert.ok(/sim\.addFrameHook/.test(src) && /unhook\?\.\(\)/.test(src) && /sim\.scene\.remove\(root\)/.test(src), 'kare kancası ve temizlik');
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
  for (const v of FS_MODES) assert.ok(keys.includes(`jam.fs_${v}`) && keys.includes(`jam.fs_${v}_t`), v);
});
const REPORT = ['{n} kez', 'hafif', 'ağır', 'tam', 'en büyük sapma', 'en büyük seyrüsefer hatası', 'Karıştırma sayısı', 'GPS karıştırma süresi', 'GPS aldatma süresi',
  'En büyük sahte konum sapması', 'En büyük seyrüsefer hatası', 'Seviye başına süre', "Bu oturum SITL'siz çalıştı: karıştırma yalnız göstergeleri etkiledi",
  'Seyrüsefer hatası: otopilotun sandığı konum ile aracın gerçek konumu arasındaki yatay mesafe',
  'kumanda bağlantısı', 'telemetri bağlantısı', 'bölge', '{n} giriş', 'Kumanda kesintisi süresi', 'Telemetri kesintisi süresi', 'Karıştırıcı bölgesi'];
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
  // §49: bağlantı / bölge / konum kaybı tepkisi denetimleri; küçük harita panelin parçası (merkez seçimi paneli kapatmaz)
  for (const c of ['fs-jam-rc', 'fs-jam-tlm', 'fs-jam-zone', 'fs-jam-zr', 'fs-jam-zc', 'fs-jam-zhere', 'fs-jam-zahead', 'fs-jam-fs', 'fs-jam-map', 'fs-jam-tlmb']) assert.ok(src.includes(c), c);
  assert.ok(/!mapEl\.contains\(e\.target\)/.test(src), 'haritaya tıklama paneli kapatmaz');
  assert.ok(/cmdBody\(cfg, st\.fs != null \? fsSel : undefined\)/.test(src), 'konum kaybı tepkisi yalnız kopterde gönderilir');
  assert.ok(/zone: \{ on: false, lat: null, lon: null, r_m: n\.zone\.r_m \}/.test(src), 'bölge merkezi tercih olarak saklanmaz');
  assert.ok(/classList\?\.toggle\('fs-tlm-lost', lost\)/.test(src) && /\.fs-stage\.fs-tlm-lost \.fs-hud/.test(src), 'telemetri kesikken panel soluklaşır');
});
test('oturum ekranı ve rapor: yalnız desteklenen oturumda; WS jam çerçevesi; SIMUMAV komutu kapalı', () => {
  const fs = oku('static/js/modules/flightsim.js');
  assert.ok(/const jam = canWrite && !replay && session\.jam\?\.supported \? createJam\(/.test(fs), 'createJam koşulu');
  assert.ok(/jam\?\.attachSim\(sim\)/.test(fs) && /hud\.prepend\(jam\.tlmBadge\)/.test(fs), '§49 3B katman + telemetri rozeti');
  assert.ok(/const tlmCut = !!jam && tlmLost\(t\)/.test(fs) && /if \(!tlmCut\) \{ milHud\?\.update\(t\); ops\?\.update\(t\); gauges\.update\(t\); \}/.test(fs) && /if \(tlmCut\) \{[^\n]*return; \}/.test(fs), '§49 telemetri kesikken göstergeler donar');
  assert.ok(/jam \? jam\.el : null/.test(fs) && /jam\?\.update\(t\)/.test(fs) && /m\.t === 'jam'\) \{ jam\?\.onFrame\(m\)/.test(fs) && /jam\?\.dispose\(\)/.test(fs), 'bant / tele / çerçeve / dispose');
  const rp = oku('static/js/modules/flightsim_report.js');
  assert.ok(/jamReportLines\(sum, tr\)/.test(rp) && /jamSection\(sum, tr, h\)/.test(rp), 'rapor');
  assert.ok(/SIM_KOMUT = set\(flightsim\.KOMUTLAR\) - \{'jam'\}/.test(oku('app/simumav/routers/fly.py')), 'SIMUMAV komut kümesi');
  const ex = oku('tools/simumav_export.py');
  assert.ok(ex.includes("'app/flightsim_jam.py'") && ex.includes("'static/js/modules/flightsim*.js'"), 'dışa aktarım çekirdeği (jam3d dahil)');
});

console.log(`\n${n} test geçti`);
