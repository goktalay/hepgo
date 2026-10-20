// Uçuş Simülatörü — kamera türü (gündüz / termal / gece görüşü) ve kamera PiP'i (§22.3–22.5) tarayıcısız birim testi (flightsim_camera.js saf katmanı):
// tür/palet doğrulama ve döngü, türün uygulandığı kipler, PiP kaynağı ve çift tık yer değiştirmesi, PiP boyutu/yerleşimi/köşeye yapışma, yenileme
// aralığı, gimbal yakınlaştırma → FOV, tercihler (localStorage; eski fs.fpv.pip göçü, dron başına tür), gölgelendirici sözleşmesi, camFxPixel paletleri,
// SIMUMAV camera_pick.js saf kısmı (varsayılan, metin → i18n anahtarı eşlemesi).
// Çalıştırma: node tests/test_flightsim_camera.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  CAMERA_TYPES, CAM_TYPE_KEYS, isCamType, normCamType, nextCamType, THERMAL_PALETTES, normPalette, nextPalette, camTypeIndex, paletteIndex, camFxApplies, nightGain,
  GIMBAL_ZOOM, clampZoom, gimbalZoomFov, pipSourceFor, pipSwapTarget, pipInterval, PIP_SIZES, PIP_DEFAULT, normPipPref, pipSize, pipInsets, pipPlace, pipSnap,
  pipSizeForWidth, nextPipSize, isDoubleTap, createCamPrefs, LS_CAM, CAM_FRAG, camUniforms, camFxPixel,
} from '../static/js/modules/flightsim_camera.js';
import { CAMERA_KEYS, normCamera, cameraDefault, CAM_TEXT_KEYS, camTr } from '../static/simumav/app/fly/camera_pick.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);
const memStorage = (init = {}) => { const m = new Map(Object.entries(init)); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), map: m }; };

console.log('Kamera türü');
test('türler day · thermal · night (sunucu enum ile aynı); doğrulama ve döngü', () => {
  assert.deepEqual(CAM_TYPE_KEYS, ['day', 'thermal', 'night']);
  assert.equal(CAMERA_TYPES.length, 3);
  assert.ok(isCamType('thermal') && !isCamType('ir') && !isCamType(null));
  assert.equal(normCamType('night'), 'night'); assert.equal(normCamType('THERMAL'), 'day'); assert.equal(normCamType(undefined), 'day');
  assert.equal(nextCamType('day'), 'thermal'); assert.equal(nextCamType('thermal'), 'night'); assert.equal(nextCamType('night'), 'day'); assert.equal(nextCamType('x'), 'thermal');
  const py = fs.readFileSync(new URL('../app/flightsim.py', import.meta.url), 'utf8');
  assert.match(py, /KAMERA_TURLERI = \('day', 'thermal', 'night'\)/);
});
test('termal paletleri beyaz-sıcak · siyah-sıcak · ironbow; gölgelendirici dizinleri', () => {
  assert.deepEqual(THERMAL_PALETTES.map(([k]) => k), ['white', 'black', 'iron']);
  assert.equal(normPalette('iron'), 'iron'); assert.equal(normPalette('rainbow'), 'white');
  assert.equal(nextPalette('white'), 'black'); assert.equal(nextPalette('iron'), 'white');
  assert.deepEqual(CAM_TYPE_KEYS.map(camTypeIndex), [0, 1, 2]); assert.equal(camTypeIndex('bozuk'), 0);
  assert.deepEqual(['white', 'black', 'iron'].map(paletteIndex), [0, 1, 2]);
});
test('tür yalnız araç kameralarına (gimbal fpv, FPV pilot); takip/serbest/yer gündüz', () => {
  assert.deepEqual(['follow', 'pilot', 'fpv', 'free', 'ground'].map(camFxApplies), [false, true, true, false, false]);
});
test('gece görüşü kazancı sahne saatine göre (gece > alacakaranlık > gündüz)', () => {
  assert.ok(nightGain('night') > nightGain('dusk') && nightGain('dusk') > nightGain('day'));
  assert.equal(nightGain('bilinmez'), nightGain('day'));
});

console.log('PiP kaynağı ve çift tık');
test('ana kip gimbal değilse PiP gimbal; gimbalse önceki ana kip (takip/FPV; serbest/yer → takip)', () => {
  for (const m of ['follow', 'pilot', 'free', 'ground']) assert.equal(pipSourceFor(m, 'fpv'), 'fpv');
  assert.equal(pipSourceFor('fpv', 'follow'), 'follow'); assert.equal(pipSourceFor('fpv', 'pilot'), 'pilot');
  assert.equal(pipSourceFor('fpv', 'free'), 'follow'); assert.equal(pipSourceFor('fpv', 'ground'), 'follow'); assert.equal(pipSourceFor('fpv', undefined), 'follow');
});
test('çift tık: takip → gimbal (PiP takip gösterir) → takip; FPV ↔ gimbal', () => {
  let main = 'follow', prev = 'follow';
  const swap = () => { const t = pipSwapTarget(main, prev); if (t !== main) { prev = main; main = t; } };
  swap(); assert.equal(main, 'fpv'); assert.equal(pipSourceFor(main, prev), 'follow');
  swap(); assert.equal(main, 'follow'); assert.equal(pipSourceFor(main, prev), 'fpv');
  main = 'pilot'; swap(); assert.equal(main, 'fpv'); assert.equal(pipSourceFor(main, prev), 'pilot');
  swap(); assert.equal(main, 'pilot');
  main = 'free'; swap(); assert.equal(main, 'fpv'); swap(); assert.equal(main, 'follow');   // serbest kamera PiP'te gösterilmez → takip
});
test('yenileme: 30 fps; ortalama kare > 22 ms → yarı hız 15 fps', () => {
  close(pipInterval(16.7), 1000 / 30); close(pipInterval(22), 1000 / 30); close(pipInterval(23), 1000 / 15); close(pipInterval(120), 1000 / 15);
});
test('gimbal yakınlaştırma 1–8×: FOV 78° → 2·atan(tan 39° / z)', () => {
  assert.equal(clampZoom(0.2), 1); assert.equal(clampZoom(20), 8); assert.equal(clampZoom('x'), 1); assert.equal(GIMBAL_ZOOM.step, 1.25);
  close(gimbalZoomFov(78, 1), 78, 1e-9);
  close(Math.tan(gimbalZoomFov(78, 2) * Math.PI / 360), Math.tan(39 * Math.PI / 180) / 2, 1e-9);
  assert.ok(gimbalZoomFov(78, 8) < 12 && gimbalZoomFov(78, 8) > 10);
});

console.log('PiP yerleşimi');
test('boyutlar S/M/L 16:9; dar ekranda genişliğin %46\'sı, en az 140 px', () => {
  for (const k of ['s', 'm', 'l']) close(PIP_SIZES[k].w / PIP_SIZES[k].h, 16 / 9, 0.01);
  assert.deepEqual(pipSize('m', 1600, 900), { w: 288, h: 162 });
  assert.deepEqual(pipSize('l', 1600, 900), { w: 400, h: 225 });
  const mob = pipSize('l', 390, 844); assert.equal(mob.w, Math.round(390 * 0.46)); assert.equal(mob.h, Math.round(mob.w * 9 / 16));
  assert.ok(pipSize('s', 200, 300).w >= 140);
  assert.equal(nextPipSize('s'), 'm'); assert.equal(nextPipSize('l'), 's');
  assert.equal(pipSizeForWidth(200), 's'); assert.equal(pipSizeForWidth(300), 'm'); assert.equal(pipSizeForWidth(520), 'l');
});
test('varsayılan sol alt köşe (sağda veri paneli/kart, ortada kadranlar): alt çubuk + atıf satırı üstünde; sağ köşe kart engelini atlar', () => {
  assert.equal(PIP_DEFAULT.corner, 'bl');
  const ins = pipInsets({ top: 56, bottom: 82 });
  const r = pipPlace(PIP_DEFAULT, 1600, 900, ins);
  assert.deepEqual(r, { x: 12, y: 900 - 82 - 162, w: 288, h: 162, corner: 'bl' });
  const br = pipPlace({ corner: 'br' }, 1600, 900, pipInsets({ right: 424 })); assert.equal(br.x, 1600 - 424 - 288);   // 400 px kartın solunda
  const tl = pipPlace({ corner: 'tl', size: 's' }, 1600, 900, ins); assert.equal(tl.x, 12); assert.equal(tl.y, 56);
});
test('bırakma: köşe yuvasına 56 px içinde → köşe; değilse serbest oran (yeniden yerleşimde aynı konum); taşma kırpılır', () => {
  const W = 1280, H = 720, ins = pipInsets(), w = 288, h = 162;
  assert.equal(pipSnap(30, 70, w, h, W, H, ins).corner, 'tl');
  assert.equal(pipSnap(W - w - 40, H - 80 - h - 30, w, h, W, H, ins).corner, 'br');
  assert.equal(pipSnap(W - w - 12, 60, w, h, W, H, ins).corner, 'tr');
  assert.equal(pipSnap(5000, 5000, w, h, W, H, ins).corner, 'br');   // dışarı bırakılan pencere içeri kırpılır, köşeye yapışır
  const free = pipSnap(500, 300, w, h, W, H, ins);
  assert.equal(free.corner, null);
  const back = pipPlace({ ...free, size: 'm' }, W, H, ins); assert.equal(back.x, 500); assert.equal(back.y, 300);
  const half = pipPlace({ corner: null, fx: 0.5, fy: 0.5, size: 'm' }, W, H, ins); assert.equal(half.x, Math.round(12 + (W - 12 - w - 12) / 2));
});
test('tercih normalleştirme: bozuk boyut/köşe/oran → varsayılan, oran 0…1', () => {
  assert.deepEqual(normPipPref(null), PIP_DEFAULT);
  const p = normPipPref({ size: 'xl', corner: 'mid', fx: 3, fy: -1, on: 0 });
  assert.equal(p.size, 'm'); assert.equal(p.corner, 'bl'); assert.equal(p.fx, 1); assert.equal(p.fy, 0); assert.equal(p.on, true);   // yalnız false kapatır
  assert.equal(normPipPref({ on: false }).on, false);
});
test('çift dokunma: ≤ 320 ms ve ≤ 24 px', () => {
  assert.ok(isDoubleTap({ t: 0, x: 0, y: 0 }, { t: 250, x: 10, y: 5 }));
  assert.ok(!isDoubleTap({ t: 0, x: 0, y: 0 }, { t: 400, x: 0, y: 0 }));
  assert.ok(!isDoubleTap({ t: 0, x: 0, y: 0 }, { t: 100, x: 40, y: 0 }));
  assert.ok(!isDoubleTap(null, { t: 0, x: 0, y: 0 }));
});

console.log('Tercihler');
test('localStorage fs.cam.type / palette / pip (JSON); eski fs.fpv.pip=0 → PiP kapalı başlar; dron başına son tür', () => {
  const st = memStorage({ 'fs.fpv.pip': '0' });
  const p = createCamPrefs(st);
  assert.equal(p.type, 'day'); assert.equal(p.palette, 'white'); assert.equal(p.pip.on, false);
  p.setType('night'); p.setPalette('iron'); p.setPip({ on: true, size: 'l', corner: 'tl' });
  assert.equal(st.getItem(LS_CAM.type), 'night'); assert.equal(st.getItem(LS_CAM.palette), 'iron');
  assert.deepEqual(JSON.parse(st.getItem(LS_CAM.pip)), { on: true, size: 'l', corner: 'tl', fx: 0, fy: 1 });
  p.rememberDrone(7, 'thermal'); p.rememberDrone(8, 'bozuk'); p.rememberDrone(null, 'night');
  const p2 = createCamPrefs(st);
  assert.equal(p2.type, 'night'); assert.equal(p2.palette, 'iron'); assert.equal(p2.pip.size, 'l');
  assert.equal(p2.typeForDrone(7), 'thermal'); assert.equal(p2.typeForDrone(8), null); assert.equal(p2.typeForDrone(null), null);
  const p3 = createCamPrefs(memStorage({ 'fs.cam.type': 'xx', 'fs.cam.pip': '{bozuk' }));
  assert.equal(p3.type, 'day'); assert.equal(p3.pip.on, true);
  assert.equal(createCamPrefs(null).type, 'day');   // depolama yok (node / özel kip)
});

console.log('Gölgelendirici ve önizleme');
test('CAM_FRAG tekdüzeleri camUniforms ile aynı; ironbow/gece/termal dalları var', () => {
  const u = camUniforms({ set() {} });
  for (const k of Object.keys(u)) assert.match(CAM_FRAG, new RegExp(`\\b${k}\\b`), k);
  for (const k of ['iron(', 'camType > 1.5', 'camType > 0.5', 'analog > 0.5', 'gain', 'lowres']) assert.ok(CAM_FRAG.includes(k), k);
  assert.equal(u.camType.value, 0); assert.equal(u.k.value, 0);
});
test('camFxPixel: gündüz değişmez; termal beyaz-sıcak artan, siyah-sıcak ters, ironbow soğuk koyu/sıcak beyaz; gece yeşil', () => {
  assert.equal(camFxPixel(0.5, 'day'), null);
  const w1 = camFxPixel(0.2, 'thermal'), w2 = camFxPixel(0.9, 'thermal');
  assert.ok(w2[0] > w1[0] && w1[0] === w1[1] && w1[1] === w1[2]);
  const b = camFxPixel(0.9, 'thermal', { palette: 'black' }); close(b[0], 1 - w2[0], 1e-9);
  const ic = camFxPixel(0.0, 'thermal', { palette: 'iron' }), ih = camFxPixel(1, 'thermal', { palette: 'iron' });
  assert.ok(ic.every(x => x < 0.05)); assert.ok(ih.every(x => x > 0.95));
  const mid = camFxPixel(0.55, 'thermal', { palette: 'iron' }); assert.ok(mid[0] > mid[2]);   // orta sıcaklık: kırmızı/turuncu
  const g = camFxPixel(0.1, 'night', { gain: 5.5 }); assert.ok(g[1] > g[0] * 2 && g[1] > g[2] * 2);
  const edge = camFxPixel(0.1, 'night', { gain: 5.5, rr: 0.9 }); assert.ok(edge[1] < 0.01);   // tüp vinyeti
  assert.ok(camFxPixel(0.05, 'night', { gain: 5.5, halo: 2 })[1] > camFxPixel(0.05, 'night', { gain: 5.5 })[1]);   // halo parlatır
});

console.log('SIMUMAV camera_pick.js');
test('varsayılan: dron kaydı → dron için yerel → son tercih → gündüz; anahtarlar', () => {
  assert.deepEqual(CAMERA_KEYS, CAM_TYPE_KEYS);
  assert.equal(normCamera('night'), 'night'); assert.equal(normCamera('x'), 'day');
  assert.equal(cameraDefault({ camera: 'thermal' }, 'night', 'day'), 'thermal');
  assert.equal(cameraDefault({}, 'night', 'thermal'), 'night');
  assert.equal(cameraDefault(null, null, 'thermal'), 'thermal');
  assert.equal(cameraDefault(null, 'bozuk', undefined), 'day');
});
test('metin → camera.* anahtarı: paylaşılan modülün tüm tür/palet adları eşlenir; 7 dil sözlüğünde anahtarlar var', () => {
  for (const [, name, desc] of CAMERA_TYPES) { assert.ok(CAM_TEXT_KEYS[name], name); assert.ok(CAM_TEXT_KEYS[desc], desc); }
  for (const [, name] of THERMAL_PALETTES) assert.ok(CAM_TEXT_KEYS[name], name);
  const keys = [...new Set(Object.values(CAM_TEXT_KEYS)), 'camera.hint'];
  for (const lang of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(fs.readFileSync(new URL(`../static/simumav/app/i18n/${lang}.json`, import.meta.url), 'utf8'));
    for (const k of keys) assert.ok(typeof d[k] === 'string' && d[k], `${lang}: ${k}`);
  }
  const dict = { 'camera.thermal': 'Thermal camera' };
  const t = camTr((s, p) => dict[s] ?? s);
  assert.equal(t('Termal kamera'), 'Thermal camera'); assert.equal(t('Gece görüşü'), 'Gece görüşü'); assert.equal(t('başka'), 'başka');
});

console.log(`\n${n} test geçti`);
