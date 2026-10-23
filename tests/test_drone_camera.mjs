// Dron Kameraları — tarayıcısız birim testi (static/js/modules/drone_camera_core.js; DOM yok):
//   • ikili çerçeve ayrıştırma (izleyici WS [tür][fMP4]), canlı uç politikası (ileri atlama / hızlanma), gecikme metni, tampon temizliği.
//   • yüzen pencere yerleşimi: kamera başına oranlı kayıt (localStorage dr.cam.win) yazma/okuma/bozuk kayıt, varsayılan basamaklı yerleşim
//     (sağdan sola sütunlar, çakışmasız), görev başına açık pencere listesi (dr.cam.open), Uçuş Simülatörü dok kurallarıyla (flightsim_dock.js) uyum.
//   • HUD: yön şeridi işaretleri (merkez, sarma, ana yön harfleri), eğim merdiveni, telemetri alan metinleri (batarya / GPS uyarı bayrakları).
//   • metinler: yeni arayüz metinlerinin HEPGO 6 dil sözlüğünde karşılığı; drone.js / drone_cameras.js yapısal denetimleri.
// Çalıştırma: node tests/test_drone_camera.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ASPECT, HDR, OPEN_KEY, T_DELTA, T_INIT, T_KEY, WIN_KEY, FPS_TEXT, fmtCoord, fmtFlight, headingTicks, hudFields, latencyText, liveEdge, loadOpen, loadWins,
  pitchLadder, placeWin, saveOpen, saveWin, splitFrame, trimRange,
} from '../static/js/modules/drone_camera_core.js';
import { boundsOf, overlaps } from '../static/js/modules/flightsim_dock.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const store = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };

console.log('akış');
test('ikili çerçeve: [tür][yük]; geçersiz tür/boş → null', () => {
  const f = splitFrame(new Uint8Array([T_KEY, 9, 8, 7]).buffer);
  assert.equal(f.type, T_KEY); assert.deepEqual([...f.data], [9, 8, 7]);
  assert.equal(splitFrame(new Uint8Array([T_INIT, 1])).type, T_INIT);
  assert.equal(splitFrame(new Uint8Array([T_DELTA, 1])).type, T_DELTA);
  assert.equal(splitFrame(new Uint8Array([4, 1, 2])), null);   // JPEG izleyiciye gitmez
  assert.equal(splitFrame(new Uint8Array([2])), null);
});
test('canlı uç: küçük gecikmede dokunma, orta gecikmede 1,1×, büyük gecikmede uca atla', () => {
  assert.deepEqual(liveEdge(10.3, 10.0), { seek: null, rate: 1, lag: 10.3 - 10.0 });
  assert.equal(liveEdge(11.5, 10.0).rate, 1.1);
  const j = liveEdge(20, 10);
  assert.equal(j.seek, 19.5); assert.equal(j.rate, 1);
  assert.equal(liveEdge(NaN, 1).seek, null);
  assert.equal(liveEdge(5, 6).lag, 0);   // oynatma tamponun önünde (kenar durumu)
});
test('gecikme metni + çevirmen; tampon temizliği yalnız 2×keep aşılınca', () => {
  assert.equal(latencyText(0.43, 1), '0.4 sn');
  assert.equal(latencyText(1.2, 7.4), '1.2 sn · son parça 7 sn önce');
  assert.equal(latencyText(null, null), '—');
  assert.equal(latencyText(2, null, (s, p) => s.replace('{s}', p.s).replace(' sn', ' s')), '2.0 s');
  assert.equal(trimRange(0, 15), null);
  assert.deepEqual(trimRange(0, 25), [0, 15]);
  assert.equal(FPS_TEXT(0), 'Kaynak FPS'); assert.equal(FPS_TEXT(15), '15 FPS');
});

console.log('yüzen pencereler');
test('kamera başına oranlı kayıt: yaz → oku, ekran değişince yapışık kenar korunur, bozuk kayıt atlanır', () => {
  const s = store();
  const W = 1600, H = 900, B = boundsOf(W, H, { top: 56 });
  saveWin(s, 7, { x: B.right - 400, y: 100, w: 400, h: 400 / ASPECT + HDR, sx: 'r', sy: null }, W, H);
  const all = loadWins(s);
  assert.ok(all['7'] && all['7'].sx === 'r' && all['7'].fw === 0.25, JSON.stringify(all));
  const r = placeWin(all['7'], 0, 1280, 720, { bounds: boundsOf(1280, 720, { top: 56 }) });
  assert.equal(r.x + r.w, boundsOf(1280, 720).right, 'sağa yapışık kalır');
  assert.equal(Math.round((r.h - HDR) * ASPECT), r.w, 'en/boy oranı korunur');
  s.setItem(WIN_KEY, JSON.stringify({ 7: all['7'], 8: { fx: 'x' }, 9: { fx: 0.1, fy: 0.1, fw: 3 } }));
  assert.deepEqual(Object.keys(loadWins(s)), ['7']);
  s.setItem(WIN_KEY, '{bozuk');
  assert.deepEqual(loadWins(s), {});
  saveWin(s, 7, null, W, H);   // sıfırla
  assert.deepEqual(loadWins(s), {});
});
test('varsayılan yerleşim: sağ üstten aşağı, sığmayınca sola yeni sütun; pencereler çakışmaz ve sınır içinde', () => {
  const W = 1440, H = 800, B = boundsOf(W, H, { top: 56 });
  const rs = [0, 1, 2, 3, 4].map(i => placeWin(null, i, W, H, { bounds: B }));
  assert.equal(rs[0].x + rs[0].w, B.right); assert.equal(rs[0].y, B.top);
  assert.ok(rs[1].y > rs[0].y && rs[1].x === rs[0].x);
  for (let i = 0; i < rs.length; i++) {
    const r = rs[i];
    assert.ok(r.x >= B.left && r.y >= B.top && r.x + r.w <= B.right && r.y + r.h <= B.bottom, JSON.stringify(r));
    for (let k = 0; k < i; k++) assert.ok(!overlaps(r, rs[k]), `${i}↔${k}`);
  }
  assert.ok(rs.some(r => r.x < rs[0].x), 'ikinci sütun');
});
test('açık pencereler görev başına; tekrar yok; 30 görevden eskisi atılır', () => {
  const s = store();
  assert.equal(loadOpen(s, 5), null);
  saveOpen(s, 5, [3, 3, 4]);
  assert.deepEqual(loadOpen(s, 5), [3, 4]);
  saveOpen(s, 6, []);
  assert.deepEqual(loadOpen(s, 6), []);
  for (let i = 100; i < 140; i++) saveOpen(s, i, [1]);
  assert.ok(Object.keys(JSON.parse(s.getItem(OPEN_KEY))).length <= 31);
});

console.log('HUD');
test('yön şeridi: merkez işaret x=0, 360 sarma, ana yönler N/E/S/W, 30°’de etiket', () => {
  const t = headingTicks(0);
  const c = t.find(k => Math.abs(k.x) < 1e-9);
  assert.equal(c.deg, 0); assert.equal(c.label, 'N');
  assert.ok(t.some(k => k.deg === 315) && t.some(k => k.deg === 45));
  assert.equal(headingTicks(92).find(k => k.deg === 90).label, 'E');
  assert.equal(headingTicks(120).find(k => k.deg === 120).label, '12');
  assert.ok(headingTicks(359).every(k => k.x >= -1 - 1e-9 && k.x <= 1 + 1e-9));
  assert.deepEqual(headingTicks(null), []);
});
test('eğim merdiveni: ufuk (0°) satırı pitch kadar kayar; negatif/pozitif etiketler', () => {
  const l = pitchLadder(10, { pxPerDeg: 5, range: 20 });
  const hz = l.find(r => r.horizon);
  assert.equal(hz.y, 50);   // burun 10° yukarı → ufuk 50 px aşağıda
  assert.ok(l.some(r => r.p === -5 && r.label === '5') && l.some(r => r.p === 20));
  assert.deepEqual(pitchLadder(undefined), []);
});
test('HUD alanları: telemetri → metin; düşük batarya ve zayıf GPS bayrakları; boş durum', () => {
  const f = hudFields({ hdg: 271.4, alt_rel: 52.35, alt: 1012, groundspeed: 14.24, climb: -1.25, batt_pct: 18, volt: 22.2, fix: 3, sats: 14, mode: 'AUTO', armed: true,
    lat: 39.92077, lon: 32.85411, flight_s: 3725, roll: -12.3, pitch: 4 });
  assert.equal(f.hdg, 271.4); assert.equal(f.alt, '52.4 m'); assert.equal(f.altMsl, 'MSL 1012'); assert.equal(f.gs, '14.2 m/s'); assert.equal(f.vs, '-1.3 m/s');
  assert.equal(f.batt, '18% 22.2V'); assert.equal(f.battLow, true); assert.equal(f.gps, '3D 14 UYDU'); assert.equal(f.gpsBad, false);
  assert.equal(f.mode, 'AUTO'); assert.equal(f.armed, true); assert.equal(f.time, '1:02:05'); assert.equal(f.pos, '39.920770°N 32.854110°E');
  assert.equal(f.roll, -12.3);
  const e = hudFields(null);
  assert.equal(e.alt, '— m'); assert.equal(e.hdg, null); assert.equal(e.gpsBad, true); assert.equal(e.time, '00:00'); assert.equal(e.pos, '—');
  assert.equal(hudFields({ fix: 1, sats: 4 }, (s, p) => (s === '{n} UYDU' ? `${p.n} SAT` : s === 'FIX YOK' ? 'NO FIX' : s)).gps, 'NO FIX 4 SAT');
  assert.equal(hudFields({ vz: -2 }).vs, '+2.0 m/s');   // NED vz (aşağı +) → tırmanma +
  assert.equal(fmtCoord(-33.5, -70.25), '33.500000°S 70.250000°W'); assert.equal(fmtFlight(59), '00:59');
});

console.log('metinler ve yapı');
test('HEPGO 6 dil: kamera arayüzü metinleri', () => {
  const need = ['Kameralar · dron kameraları, görüntü köprüsü ve canlı önizleme', 'Yeni Kamera', 'Kaynak FPS', 'Anlık görüntü', 'Görüntü köprüsü', 'Köprü çevrim dışı',
    'Hazır (izleyen yok)', 'HUD aç/kapat', 'HUD: bağlı dron telemetrisi yok', 'YER HIZI', 'CANLI', 'GECİKME', '{n} UYDU', 'son parça {s} sn önce', 'Linux / Jetson (arm64)',
    '⬇ Linux / Jetson için indir', 'Pencerede aç', 'Görevden kaldır', 'Köprü (bu görev için)', 'Bağlı dron (HUD telemetrisi)', 'Ayrı pencerede aç (çift tık)',
    'Kayıtlı — değiştirmek için yazın', 'Tarayıcınız H.265 görüntüyü oynatamıyor; kamerada H.264 seçin ya da köprü ayarında h265 = yeniden_kodla. Şimdilik JPEG anlık görüntü gösteriliyor.',
    "İndirin ve Jetson'a kopyalayın", '{name} · canlı önizleme', 'GPS YOK', 'FIX YOK'];
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = need.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('drone.js: Kameralar sekmesi, Canlı Uçuş kamera katmanı, Linux indirme kartı; kamera sayfası parola göndermez', () => {
  const d = readFileSync(join(ROOT, 'static/js/modules/drone.js'), 'utf8');
  assert.ok(/\['cameras', 'Kameralar'\]/.test(d) && /import\('\.\/drone_cameras\.js'\)/.test(d));
  assert.ok(/liveCameras\(view, task\)/.test(d) && /createCameraWindows\(view/.test(d) && /\/api\/drone\/tasks\/\$\{task\}\/cameras/.test(d));
  assert.ok(/f\.os === 'linux-arm64'/.test(d) && /sudo \.\/install\.sh/.test(d) && /sudo hepgo-kopru eslestir <köprü kodu>/.test(d));
  const c = readFileSync(join(ROOT, 'static/js/modules/drone_cameras.js'), 'utf8');
  assert.ok(/password: pass\.value \|\| null/.test(c), 'boş parola alanı → null (kayıtlı parola korunur)');
  assert.ok(!/c\.password\b/.test(c), 'kamera kaydından parola okunmaz');
  const w = readFileSync(join(ROOT, 'static/js/modules/drone_camera.js'), 'utf8');
  assert.ok(/from '\.\/flightsim_dock\.js'/.test(w) && /sb\.mode = 'sequence'/.test(w) && /ManagedMediaSource/.test(w) && /dblclick/.test(w) && /window\.open/.test(w));
  assert.ok(!/lockTarget|angaj|engage/i.test(w.replace(/^\s*\/\/.*$/gm, '')), 'HUD yalnız gösterge (hedef güdümü yok)');
  const page = readFileSync(join(ROOT, 'static/kamera.html'), 'utf8');
  assert.ok(/kamera_page\.js/.test(page));
});

console.log(`\n${n} test geçti`);
