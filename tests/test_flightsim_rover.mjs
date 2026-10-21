// Uçuş Simülatörü — §31 KARA ARACI (rover, ArduRover) tarayıcısız birim testi:
//   • flightsim_rover.js saf işlevleri: kipler, sanal kumanda eşlemesi (RC1 direksiyon / RC3 gaz), teker kinematiği, zemine oturma, süspansiyon,
//     gösterge modeli, metinler (HEPGO Türkçe anahtar / SIMUMAV `rover.*`).
//   • flightsim_fltbar.js: rover ailesi, kip listesi, DISARM her zaman yerde.
//   • flightsim_power.js: ROVER_DEFAULTS, flightBudget rover dalı (sunucu flightsim_power.menzil_sure ile BİREBİR — tests/test_flightsim.py aynı sayıları
//     denetler), hız kadranı (72 km/h ölçeği, hava hızı / stall yok).
//   • flightsim_wizard.js (Kalkış adımı yok), flightsim_rcfeel.js (iki eksen), flightsim_audio.js (elektrik motoru sesi).
//   • HEPGO sözlükleri: rover metinlerinin 6 dilde karşılığı.
// Çalıştırma: node tests/test_flightsim_rover.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ROVER_DRIVES, ROVER_LIMITS, ROVER_MODES, ROVER_RC_TEXT, ROVER_TEXTS, ROVER_TYPE, compass8, createSuspension, isRover, makeRoverT, normDrive, roverContacts, roverDash, roverGroundFit, roverKinematics, roverRcChannels } from '../static/js/modules/flightsim_rover.js';
import { FLIGHT_MODES, disarmAction, flightModesFor, isAirborne, modeGroups, modeKind } from '../static/js/modules/flightsim_fltbar.js';
import { ROVER_AZAMI_MS, ROVER_DEFAULTS, ROVER_GAUGE_KMH, ROVER_SEYIR_GAZ, ROVER_SEYIR_MS, createPowerSim, dashModels, defaultsFor, flightBudget, isPlaneType, niceScaleMax, speedGauge } from '../static/js/modules/flightsim_power.js';
import { launchOptionsFor, normLaunchMethod, wizardSteps } from '../static/js/modules/flightsim_wizard.js';
import { ROVER_FEEL_AXES, RCFEEL_TEXTS, makeShaper, shapeAxis } from '../static/js/modules/flightsim_rcfeel.js';
import { AUDIO_MODELS, SPIN_UP, audioModel, engineTargets, roverMotorHz, spinStep } from '../static/js/modules/flightsim_audio.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6, msg = '') => assert.ok(Math.abs(a - b) <= eps, `${msg} ${a} ≉ ${b}`);
const DEG = Math.PI / 180;

console.log('flightsim_rover: sabitler ve sanal kumanda');
test('tip / kipler / sürüş biçimleri', () => {
  assert.equal(ROVER_TYPE, 'rover'); assert.ok(isRover('rover')); assert.ok(isRover({ type: 'rover' })); assert.ok(!isRover('multirotor')); assert.ok(!isRover(null));
  assert.deepEqual(ROVER_MODES, ['MANUAL', 'ACRO', 'STEERING', 'HOLD', 'LOITER', 'FOLLOW', 'SIMPLE', 'AUTO', 'RTL', 'SMART_RTL', 'GUIDED']);
  assert.deepEqual(ROVER_DRIVES, ['ackermann', 'skid']);
  assert.equal(normDrive('skid'), 'skid'); assert.equal(normDrive('ackermann'), 'ackermann'); assert.equal(normDrive(null), 'ackermann'); assert.equal(normDrive('x'), 'ackermann');
  assert.equal(ROVER_LIMITS.ackermann.vmax, 20); assert.equal(ROVER_LIMITS.skid.vmax, 4);
});
test('roverRcChannels: RC1 direksiyon, RC3 gaz (1500 = dur, çift yönlü), RC2/RC4 dokunulmaz (0), ch5 kırpılır', () => {
  assert.deepEqual(roverRcChannels(), [1500, 0, 1500, 0, 1500, 0, 0, 0]);
  assert.deepEqual(roverRcChannels({ steer: 1, thr: 1 }), [2000, 0, 2000, 0, 1500, 0, 0, 0]);
  assert.deepEqual(roverRcChannels({ steer: -1, thr: -1, ch5: 1000 }), [1000, 0, 1000, 0, 1000, 0, 0, 0]);
  assert.deepEqual(roverRcChannels({ steer: 0.5, thr: -0.25, ch5: 2600 }), [1750, 0, 1375, 0, 2000, 0, 0, 0]);
  assert.deepEqual(roverRcChannels({ steer: 3, thr: 'x' }), [2000, 0, 1500, 0, 1500, 0, 0, 0]);   // kırpma + bozuk değer = orta
});
test('ROVER_RC_TEXT: ipucu + çubuk etiketleri', () => {
  assert.equal(ROVER_RC_TEXT.left, 'Gaz / Fren'); assert.equal(ROVER_RC_TEXT.right, 'Direksiyon');
  for (const w of ['W/S', 'A/D', 'Boşluk', 'Q/E']) assert.ok(ROVER_RC_TEXT.hint.includes(w), w);
});

console.log('flightsim_rover: kinematik, zemin, süspansiyon, gösterge');
test('roverKinematics: Ackermann servo çıkışından direksiyon (±35°) ve gaz; vites D / R / N; fren', () => {
  const k = roverKinematics({ servo: [2000, 1500, 1750, 1500], groundspeed: 5, vn: 5, ve: 0, yaw: 0, armed: true });
  close(k.steer, 35 * DEG, 1e-9); assert.equal(k.src, 'servo'); assert.equal(k.gear, 'D'); close(k.throttle, 0.5, 1e-9); assert.equal(k.brake, 0); close(k.v, 5, 1e-9);
  const r = roverKinematics({ servo: [1500, 1500, 1200, 1500], vn: -3, ve: 0, yaw: 0, armed: true });   // geri gidiyor, gaz geri
  assert.equal(r.gear, 'R'); close(r.v, -3, 1e-9);
  const b = roverKinematics({ servo: [1500, 1500, 1000, 1500], vn: 6, ve: 0, yaw: 0, armed: true });   // ileri giderken tam geri gaz = fren
  close(b.brake, 1, 1e-9); assert.equal(b.throttle, 0);
  const z = roverKinematics({ groundspeed: 0, vn: 0, ve: 0, yaw: 0, throttle: 0 });
  assert.equal(z.gear, 'N'); assert.equal(z.src, 'kin');
});
test('roverKinematics: skid — sol/sağ servo; kinematikte yön hızından teker hız farkı', () => {
  const k = roverKinematics({ servo: [2000, 1500, 1000, 1500], vn: 0, ve: 0, yaw: 0, armed: true }, { drive: 'skid' });
  assert.equal(k.src, 'servo'); assert.equal(k.steer, 0);
  const t = roverKinematics({ vn: 2, ve: 0, yaw: 0, ys: 1 }, { drive: 'skid', track: 1 });
  close(t.vL, 2.5, 1e-9); close(t.vR, 1.5, 1e-9);   // sağa dönüş (ys +): sol teker hızlı
  const a = roverKinematics({ vn: 4, ve: 0, yaw: 0, ys: 0.5 }, { drive: 'ackermann', wheelbase: 1.3 });
  assert.ok(a.steer > 0, 'sağa dönüşte direksiyon +'); close(a.steer, Math.atan(1.3 * 0.5 / 4), 1e-9);
});
test('roverContacts / roverGroundFit: 4 temas noktası; eğim ileri yükselince +, yatış sağ yükselince −; ±35° kırpma', () => {
  assert.deepEqual(roverContacts(2, 1), [[-0.5, -1], [0.5, -1], [-0.5, 1], [0.5, 1]]);
  const f = roverGroundFit([0, 0, 1, 1], 2, 1);
  close(f.z, 0.5, 1e-9); close(f.pitch, Math.atan2(1, 2), 1e-9); close(f.roll, 0, 1e-9);
  const r = roverGroundFit([0, 1, 0, 1], 2, 2);
  close(r.roll, -Math.atan2(1, 2), 1e-9);
  const c = roverGroundFit([0, 0, 10, 10], 1, 1);
  close(c.pitch, 35 * DEG, 1e-9);
});
test('createSuspension: ilk adım oturur, yumuşak geçiş, büyük sıçrama doğrudan oturur', () => {
  const s = createSuspension();
  assert.deepEqual(s.step([0, 0, 0, 0], 0.016), [0, 0, 0, 0]);
  let h = null; for (let i = 0; i < 3; i++) h = s.step([0.5, 0.5, 0.5, 0.5], 0.016);
  assert.ok(h[0] > 0 && h[0] < 0.5, `yumuşak: ${h[0]}`); assert.ok(s.comp(0) > 0);
  for (let i = 0; i < 200; i++) h = s.step([0.5, 0.5, 0.5, 0.5], 0.016);
  close(h[0], 0.5, 1e-3);
  assert.deepEqual(s.step([10, 10, 10, 10], 0.016), [10, 10, 10, 10]);   // > 4 m: ışınlanma
});
test('roverDash: km/h, yön, eğim/yatış (3B pozu öncelikli), vites P (disarm), azami km/h; compass8', () => {
  assert.equal(roverDash(null), null);
  const d = roverDash({ groundspeed: 10, heading: 370, pitch: 0.1, roll: -0.05, armed: true, mode: 'MANUAL', servo: [1500, 1500, 1800, 1500], vn: 10, ve: 0, yaw: 0 }, { pose: { pitch: 0.2, roll: 0 } });
  close(d.kmh, 36, 1e-9); close(d.hdg, 10, 1e-9); close(d.pitchDeg, 0.2 / DEG, 1e-9); close(d.rollDeg, 0, 1e-9); assert.equal(d.gear, 'D'); assert.equal(d.mode, 'MANUAL'); close(d.maxKmh, 72, 1e-9);
  close(d.gradePct, Math.tan(0.2) * 100, 1e-9);
  assert.equal(roverDash({ groundspeed: 0, armed: false }).gear, 'P');
  close(roverDash({ groundspeed: 1, armed: true }, { drive: 'skid' }).maxKmh, 14.4, 1e-9);
  assert.equal(compass8(0), 'N'); assert.equal(compass8(90), 'E'); assert.equal(compass8(225), 'SW'); assert.equal(compass8(-45), 'NW');
});
test('ROVER_TEXTS: anahtarlar tekil `rover.*`; makeRoverT HEPGO (Türkçe anahtar) / SIMUMAV (keyed, yoksa Türkçe)', () => {
  const keys = ROVER_TEXTS.map(([k]) => k);
  assert.equal(new Set(keys).size, keys.length); assert.ok(keys.every(k => k.startsWith('rover.')));
  assert.equal(makeRoverT(null)('rover.speed'), 'HIZ');
  assert.equal(makeRoverT(s => `[${s}]`, false)('rover.hdg'), '[YÖN]');   // HEPGO: Türkçe metin anahtar
  assert.equal(makeRoverT(s => (s === 'YÖN' ? 'HDG' : s))('rover.hdg'), 'HDG');   // auto: anahtar karşılıksız → Türkçe metin
  assert.equal(makeRoverT(k => (k === 'rover.thr' ? 'THR' : k), true)('rover.thr'), 'THR');
  assert.equal(makeRoverT(k => k, true)('rover.brake'), 'FREN');
});

console.log('flightsim_fltbar: rover ailesi');
test('modeKind / kip listesi / gruplar', () => {
  assert.equal(modeKind('rover'), 'rover');
  assert.deepEqual(FLIGHT_MODES.rover, ROVER_MODES); assert.deepEqual(flightModesFor('rover'), ROVER_MODES);
  assert.deepEqual(modeGroups('rover'), [['all', ROVER_MODES]]);
});
test('DISARM her zaman yerde (hareket hâlinde de); kara aracı hiç havada değil', () => {
  const t = { armed: true, groundspeed: 15, alt_rel: 0, mode: 'MANUAL' };
  assert.equal(isAirborne(t, 'rover'), false); assert.equal(isAirborne(t), true);   // 15 m/s: uçak ailesinde "havada" sayılırdı
  assert.equal(disarmAction('rover', t), 'disarm');
  assert.equal(disarmAction('rover', { armed: false }), 'arm');
  assert.equal(disarmAction('rover', { armed: true, alt_rel: 50 }), 'disarm');
});

console.log('flightsim_power: rover (sunucuyla birebir)');
test('ROVER_DEFAULTS = sunucu ROVER_VARSAYILAN; defaultsFor; uçak sayılmaz', () => {
  assert.deepEqual(ROVER_DEFAULTS, { max_speed_ms: null, fuel_l: 0, fuel_km_per_l: 12, elec_cells: 4, elec_mah: 16000, elec_w: 60 });
  assert.deepEqual(defaultsFor('rover'), ROVER_DEFAULTS); assert.notEqual(defaultsFor('rover'), ROVER_DEFAULTS);   // kopya
  assert.equal(isPlaneType('rover'), false);
  assert.equal(ROVER_SEYIR_MS, 5); assert.equal(ROVER_AZAMI_MS, 20); assert.equal(ROVER_SEYIR_GAZ, 0.3);
});
test('flightBudget rover: elektrikli varsayılan 236,8 Wh / 60 W → 236,8 dk, 71 km seyir (5 m/s), 284,2 km azami', () => {
  const b = flightBudget({}, 'rover');
  assert.deepEqual(b.speed, { cruise_ms: 5, max_ms: 20, cruise_thr: 0.3 });
  assert.equal(b.fuel, null);
  assert.deepEqual(b.elec, { wh: 236.8, time_min: 236.8, range_km: 71, time_min_max: 236.8, range_km_max: 284.2 });
  assert.equal(b.limit, 'elec'); assert.equal(b.time_min, 236.8); assert.equal(b.range_km, 71);
});
test('flightBudget rover: içten yanmalı 10 L @ 12 km/L → 184,6 km / 615,4 dk (gaz %30); batarya yine sınırlar', () => {
  const b = flightBudget({ fuel_l: 10 }, 'rover');
  assert.deepEqual(b.fuel, { range_km: 184.6, time_min: 615.4, range_km_max: 120, time_min_max: 100 });
  assert.equal(b.limit, 'elec'); assert.equal(b.time_min_max, 100); assert.equal(b.range_km_max, 120);
});
test('speedGauge rover: 0 … niceScaleMax(72 km/h) ölçeği, kırmızı bölge yok, hava hızı / stall yok', () => {
  const sc = niceScaleMax(ROVER_GAUGE_KMH);
  const g = speedGauge({ groundspeed: 10, airspeed: 2, armed: true, alt_rel: 50 }, { max_speed_ms: 45 }, { rover: true, plane: true });
  assert.equal(g.max, sc.max); assert.equal(g.red, null); assert.equal(g.sub, ''); assert.equal(g.warnKind, null); assert.equal(g.main, '36');
  assert.equal(speedGauge({ groundspeed: 1 }, null, { rover: true, collision: true }).warnKind, 'crash');
  const m = dashModels({ groundspeed: 3, throttle: 40, elec: { pct: 80, wh: 100, v: 15.6, w: 60 } }, ROVER_DEFAULTS, { rover: true });
  assert.ok(m.speed && m.engine && m.elec); assert.equal(m.fuel, null);
});
test('createPowerSim rover ayarlarıyla: yalnız batarya, 60 W', () => {
  const p = createPowerSim(ROVER_DEFAULTS);
  assert.equal(p.fuelOn, false); assert.equal(p.elecOn, true);
  for (let t = 0; t <= 60; t++) p.step({ armed: true, groundspeed: 5, throttle: 30 }, t);   // > 5 sn boşluk atlanır → 1 sn adım
  close(p.summary().elec.wh_used, 1, 1e-6);   // 60 W × 60 sn = 1 Wh
});

console.log('sihirbaz / hassasiyet / ses');
test('sihirbaz: kara aracında Kalkış adımı yok (fırlatma seçeneği yok)', () => {
  assert.deepEqual(launchOptionsFor('rover'), []);
  const st = wizardSteps({ mode: 'sitl', type: 'rover' });
  assert.ok(!st.includes('launch')); assert.deepEqual(st, ['vehicle', 'world', 'power', 'camera', 'targets', 'site', 'summary']);
  assert.ok(!wizardSteps({ mode: 'replay', type: 'rover' }).includes('launch'));
  assert.equal(normLaunchMethod('wheels', 'rover'), 'wheels');   // seçenek yok → dokunulmaz
});
test('rcfeel: kara aracı iki eksen (Direksiyon = roll eğrisi, Gaz); gaz eğrisi uygulanır (çift yönlü)', () => {
  assert.deepEqual(ROVER_FEEL_AXES.map(([a]) => a), ['roll', 'thr']);
  assert.ok(RCFEEL_TEXTS.some(([k, v]) => k === 'rcfeel.steer' && v === 'Direksiyon'));
  const feel = { thr: { rate: 80, expo: 0, dead: 0 } };
  const sh = makeShaper(feel, { plane: false });
  close(sh('thr', 1), shapeAxis(1, { rate: 80, expo: 0, dead: 0 }), 1e-9); close(sh('thr', -1), -0.8, 1e-9);
});
test('ses: rover = elektrik motoru (uğultu hızla 90 → 850 Hz), disarm sessiz, lastik gürültüsü hızla', () => {
  assert.equal(audioModel('rover'), AUDIO_MODELS.rover); assert.equal(audioModel('rover').kind, 'rover'); assert.equal(SPIN_UP.rover, 0.4);
  assert.equal(roverMotorHz(0), 90); assert.equal(roverMotorHz(20), 850); assert.equal(roverMotorHz(-20), 850); assert.equal(roverMotorHz(100), roverMotorHz(25));
  const off = engineTargets('rover', { armed: false, groundspeed: 0, throttle: 0 });
  assert.equal(off.rover, 0); assert.equal(off.copter, 0); assert.equal(off.plane, 0);
  const idle = engineTargets('rover', { armed: true, groundspeed: 0, throttle: 0 });
  close(idle.rover, 0.18, 1e-9); assert.equal(idle.tire, 0);
  const fast = engineTargets('rover', { armed: true, groundspeed: 20, throttle: 100 });
  close(fast.rover, 0.5, 1e-9); close(fast.tire, 0.45, 1e-9); assert.equal(fast.roverHz, 850);
  close(spinStep(0, true, 0.2, 'rover'), 0.5, 1e-9);
});

console.log('HEPGO sözlükleri (6 dil)');
test('rover metinleri her sözlükte (en: i18n.en*.js birleşik)', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const need = [...ROVER_TEXTS.map(([, v]) => v), ROVER_RC_TEXT.hint, ROVER_RC_TEXT.left, ROVER_RC_TEXT.right, 'Kara Aracı', 'Keşif 4×4', 'Paletli UGV', 'Teslimat robotu',
    'Ackermann', 'Paletli / diferansiyel', 'Sürüş biçimi', 'Kokpit', 'Kara aracı göstergesi', 'Sürüş', 'Eğim', 'Yatış', 'km/h', 'Dur (HOLD)',
    '0 = elektrikli; içten yanmalı 4×4 için L ve km/L girin.'];
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = need.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});

console.log(`\n${n} test geçti`);
