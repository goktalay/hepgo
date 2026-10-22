// Uçuş Simülatörü §42 — UÇUŞ UYARI SİSTEMİ tarayıcısız birim testi (flightsim_gpws.js saf katmanı):
//   • her uyarının tetiklenmesi / temizlenmesi (sentetik kare dizileri), histerezis (açıkken gevşeyen eşik), tetik gecikmesi + en kısa gösterim,
//   • evre bastırma (ARM'sız yok, kalkış, LAND / RTL son yaklaşma, çarpışma), öncelik, araç tipine göre eşik (kopter / uçak / VTOL Q kipi / kara aracı),
//   • onay (MASTER: ses susar, görsel kalır; yeni uyarı yeniden çalar), zaman geri giderse (Sıfırla / atlama) bölümler kapanır,
//   • özet + "uçuş disiplini" puanı (sunucu app/flightsim_gpws.py ile aynı formül), ayar normalleştirme, telemetri dönüşümü, metinler (6 + 7 dil),
//   • oturumlar modülü bağlar (HEPGO flightsim.js, SIMUMAV fly/session.js, rapor), sunucu kod listesi JS ile aynı.
// Çalıştırma: node tests/test_flightsim_gpws.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  GPWS_CODES, GPWS_DEFAULT, GPWS_TEXTS, IMU_MASK, MIN_SHOW, OFF_DELAY, alertEventSev, alertEventText, alertRows, alertSpeech, alertText, codeApplies, createGpws,
  createGpwsPrefs, gpwsThresholds, gradeOf, makeGpwsT, modeKind, normalizeGpwsCfg, penaltyOf, summarizeAlerts, teleInput, vehicleClass,
} from '../static/js/modules/flightsim_gpws.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

// Sentetik uçuş: base kare + her adımda üzerine yazılan alanlar; dt = 0.1 sn
const BASE = { armed: true, mode: 'LOITER', agl: 40, aglAhead: null, vs: 0, gs: 5, as: 5, roll: 0, pitch: 0, rates: { p: 0, q: 0, r: 0 }, battPct: 80, battEmpty: false,
  fuelPct: null, fuelEmpty: false, gpsFix: 3, sats: 12, sensBad: 0, ekf: 0.05, vibe: 5, wind: 3, motorCut: false, phase: null, distHome: 100, linkAge: 100, crashed: false };
function sim(vehicle, cfg = {}, opts = {}) {
  const g = createGpws({ vehicle, cfg, ...opts });
  let t = 0, prev = { roll: 0, pitch: 0 };
  const log = [];
  const run = (secs, over = {}, dt = 0.1) => {
    let r = null;
    for (let k = 0; k < Math.round(secs / dt); k++) {
      t = Math.round((t + dt) * 1000) / 1000;
      const o = typeof over === 'function' ? over(t) : over;
      const f = { ...BASE, ...o, t };
      if (!('rates' in o)) f.rates = { p: ((f.roll ?? 0) - prev.roll) / dt, q: ((f.pitch ?? 0) - prev.pitch) / dt, r: 0 };   // tutarlı jiroskop (açısal hız tutumla uyumlu)
      prev = { roll: f.roll ?? 0, pitch: f.pitch ?? 0 };
      r = g.step(f);
      log.push(r);
    }
    return r;
  };
  return { g, run, get t() { return t; }, log, codes: () => (log.at(-1)?.active || []).map(a => a.code) };
}
// Havalanmış araç (kalkış süresi geçmiş: uçakta 8 sn): 10 sn düz uçuş
const airborne = (vehicle = 'multirotor', cfg = {}, opts = {}, over = {}) => { const s = sim(vehicle, cfg, opts); s.run(10, over); return s; };

console.log('araç tipi ve eşikler');
test('araç sınıfı + kip sınıfı (VTOL/INTERCEPTOR Q kiplerinde kopter eşikleri)', () => {
  assert.equal(vehicleClass('multirotor'), 'copter'); assert.equal(vehicleClass('hexarotor'), 'copter'); assert.equal(vehicleClass('helikopter'), 'heli');
  assert.equal(vehicleClass('sabit_kanat'), 'plane'); assert.equal(vehicleClass('plane'), 'plane'); assert.equal(vehicleClass('vtol'), 'vtol');
  assert.equal(vehicleClass('interceptor'), 'icept'); assert.equal(vehicleClass('rover'), 'rover'); assert.equal(vehicleClass('fpv'), 'copter');
  assert.equal(modeKind('vtol', 'QHOVER'), 'copter'); assert.equal(modeKind('vtol', 'FBWA'), 'plane'); assert.equal(modeKind('icept', 'QLOITER'), 'copter');
  assert.equal(modeKind('plane', 'QHOVER'), 'plane'); assert.equal(modeKind('heli', 'LOITER'), 'copter'); assert.equal(modeKind('rover', 'MANUAL'), 'rover');
});
test('eşikler: kopter yatış 35°, uçak 45°; hassasiyet süreleri ölçekler; güç ayarındaki azami hız Vne olur', () => {
  const c = gpwsThresholds('copter', 'copter', GPWS_DEFAULT), p = gpwsThresholds('plane', 'plane', GPWS_DEFAULT);
  assert.equal(c.bank, 35); assert.equal(p.bank, 45); assert.equal(c.stall, null); assert.equal(p.stall, 9);
  const hi = gpwsThresholds('copter', 'copter', normalizeGpwsCfg({ sens: 'high' })), lo = gpwsThresholds('copter', 'copter', normalizeGpwsCfg({ sens: 'low' }));
  assert.ok(hi.tPull > c.tPull && lo.tPull < c.tPull); assert.ok(hi.sinkHard < c.sinkHard);
  assert.equal(gpwsThresholds('copter', 'copter', GPWS_DEFAULT, { maxSpeed: 20 }).vne, 20 * 1.08);
  assert.equal(gpwsThresholds('icept', 'plane', GPWS_DEFAULT).vne, 70);
  assert.equal(gpwsThresholds('copter', 'copter', normalizeGpwsCfg({ bank_copter: 25 })).bank, 25);
});
test('kod geçerliliği: kara aracında uçuş uyarıları yok; STALL yalnız kanatlı', () => {
  assert.ok(!codeApplies('PULL_UP', 'rover')); assert.ok(!codeApplies('BANK_ANGLE', 'rover')); assert.ok(codeApplies('IMU_FAULT', 'rover')); assert.ok(codeApplies('BATT_CRIT', 'rover'));
  assert.ok(!codeApplies('STALL', 'copter')); assert.ok(codeApplies('STALL', 'plane')); assert.ok(codeApplies('STALL', 'vtol')); assert.ok(!codeApplies('NOPE', 'copter'));
});

console.log('tek tek uyarılar: tetik / temizlenme');
test('BANK ANGLE: kopter 35°’yi aşınca (0,3 sn gecikme) açılır; histerezis 30°; en kısa gösterim 2,5 sn', () => {
  const s = airborne();
  let r = s.run(0.2, { roll: 40 });
  assert.ok(!s.codes().includes('BANK_ANGLE'), 'tetik gecikmesi 0,3 sn');
  r = s.run(0.2, { roll: 40 });
  assert.ok(s.codes().includes('BANK_ANGLE')); assert.equal(r.primary.code, 'BANK_ANGLE'); assert.equal(r.primary.level, 'warning');
  assert.ok(s.log.some(x => x.fresh.includes('BANK_ANGLE')), 'fresh bir kez');
  s.run(1, { roll: 32 });   // 30 < 32 < 35: açıkken sürer (histerezis)
  assert.ok(s.codes().includes('BANK_ANGLE'));
  s.run(0.5, { roll: 5 });
  assert.ok(s.codes().includes('BANK_ANGLE'), 'OFF_DELAY + MIN_SHOW');
  r = s.run(2.5, { roll: 5 });
  assert.ok(!s.codes().includes('BANK_ANGLE'));
  const ep = s.g.episodes().find(e => e.code === 'BANK_ANGLE');
  assert.ok(ep && ep.dur_s >= 1.3 && ep.dur_s <= 2, `süre ${ep?.dur_s}`); assert.equal(ep.level, 'warning');
  assert.ok(OFF_DELAY === 1 && MIN_SHOW === 2.5);
});
test('BANK ANGLE uçakta 45° (40° uyarmaz); ayarla eşik değişir', () => {
  const p = airborne('sabit_kanat', {}, {}, { mode: 'FBWA', as: 20, gs: 20, agl: 120 });
  p.run(1, { mode: 'FBWA', as: 20, gs: 20, agl: 120, roll: 40 });
  assert.ok(!p.codes().includes('BANK_ANGLE'));
  p.run(1, { mode: 'FBWA', as: 20, gs: 20, agl: 120, roll: 50 });
  assert.ok(p.codes().includes('BANK_ANGLE'));
  const c = airborne('multirotor', { bank_copter: 25 });
  c.run(1, { roll: 28 });
  assert.ok(c.codes().includes('BANK_ANGLE'), 'eşik 25°');
});
test('PULL UP: hızlı alçalma + kısa çarpma süresi; TERRAIN ileri bakışta arazi yükselmesi; SINK RATE sert alçalma', () => {
  const s = airborne();
  s.run(0.5, { agl: 20, vs: -8 });   // ttc 2,5 sn < 3,5
  assert.ok(s.codes().includes('PULL_UP')); assert.equal(s.log.at(-1).primary.code, 'PULL_UP', 'en yüksek öncelik');
  assert.ok(s.codes().includes('SINK_RATE'), 'sert alçalma (> 6 m/s)');
  const s2 = airborne('sabit_kanat', {}, {}, { mode: 'CRUISE', as: 22, gs: 22, agl: 150 });
  s2.run(1, { mode: 'CRUISE', as: 22, gs: 22, agl: 100, aglAhead: 20, vs: 0 });   // 8 sn'de 80 m arazi → kapanma 10 m/s, ttc 10 sn → TERRAIN değil (< 10 değil)
  s2.run(1, { mode: 'CRUISE', as: 22, gs: 22, agl: 80, aglAhead: 0, vs: 0 });     // kapanma 10 m/s, ttc 8 sn < 10 → TERRAIN
  assert.ok(s2.codes().includes('TERRAIN')); assert.ok(!s2.codes().includes('SINK_RATE'), 'dron alçalmıyor');
  s2.run(1, { mode: 'CRUISE', as: 22, gs: 22, agl: 40, aglAhead: -40, vs: 0 });  // ttc 4 sn < 5 → PULL UP
  assert.ok(s2.codes().includes('PULL_UP'));
});
test('STALL: sabit kanatta hava hızı < 9 m/s (havada); yüksek pitch + düşük hızda da; kopterde yok', () => {
  const p = airborne('sabit_kanat', {}, {}, { mode: 'FBWA', as: 20, gs: 20, agl: 120 });
  p.run(1, { mode: 'FBWA', as: 7, gs: 7, agl: 120 });
  assert.ok(p.codes().includes('STALL'));
  p.run(4, { mode: 'FBWA', as: 10, gs: 10, agl: 120 });   // 9 × 1,15 = 10,35 > 10 → açıkken sürer (histerezis)
  assert.ok(p.codes().includes('STALL'));
  p.run(4, { mode: 'FBWA', as: 18, gs: 18, agl: 120 });
  assert.ok(!p.codes().includes('STALL'));
  p.run(1, { mode: 'FBWA', as: 11, gs: 11, agl: 120, pitch: 20 });
  assert.ok(p.codes().includes('STALL'), 'yüksek hücum');
  const c = airborne(); c.run(1, { as: 2 }); assert.ok(!c.codes().includes('STALL'));
  const v = airborne('vtol', {}, {}, { mode: 'QHOVER', as: 0, gs: 0 }); v.run(1, { mode: 'QHOVER', as: 0 }); assert.ok(!v.codes().includes('STALL'), 'VTOL Q kipinde stall yok');
});
test('OVERSPEED: kopter 22 m/s (güç ayarı varsa azami × 1,08); PITCH: kopter ±35°', () => {
  const s = airborne(); s.run(1, { gs: 25 }); assert.ok(s.codes().includes('OVERSPEED'));
  const s2 = airborne('multirotor', {}, { maxSpeed: 30 }); s2.run(1, { gs: 25 }); assert.ok(!s2.codes().includes('OVERSPEED'));
  const s3 = airborne(); s3.run(1, { pitch: -40 }); assert.ok(s3.codes().includes('PITCH'));
});
test('ENGINE: havada motor kesik; havadayken DISARM (düşüş) da', () => {
  const p = airborne('sabit_kanat', {}, {}, { mode: 'FBWA', as: 20, agl: 120 }); p.run(1, { mode: 'FBWA', as: 20, agl: 120, motorCut: true }); assert.ok(p.codes().includes('ENGINE'));
  const c = airborne(); c.run(1, { armed: false, agl: 30, vs: -6 }); assert.ok(c.codes().includes('ENGINE'), 'disarm + düşüş');
  const g = airborne(); g.run(1, { armed: false, agl: 0.2, vs: 0 }); assert.ok(!g.codes().includes('ENGINE'), 'yerde disarm normal');
});
test('IMU / GYRO FAULT: SITL sağlık biti, EKF ≥ 0,8, tutum sıçraması, sürekli dönme, aşırı açısal hız; ACRO’da hareket kuralları yok', () => {
  const a = airborne(); a.run(0.1, { sensBad: 0x1 }); assert.ok(a.codes().includes('IMU_FAULT'), 'gyro biti anında'); assert.equal(IMU_MASK & 0x200000, 0, 'AHRS biti SITL’de güvenilmez');
  const a2 = airborne(); a2.run(1, { sensBad: 0x200000 | 0x10000000 }); assert.ok(!a2.codes().includes('IMU_FAULT'), 'AHRS / prearm bitleri uyarı değil');
  const b = airborne(); b.run(1.2, { ekf: 0.9 }); assert.ok(b.codes().includes('IMU_FAULT')); assert.ok(!b.codes().includes('EKF'), '0,8 üstü kırmızı, sarı değil');
  const b2 = airborne(); b2.run(1.2, { ekf: 0.6 }); assert.ok(b2.codes().includes('EKF')); assert.equal(b2.log.at(-1).primary.level, 'caution');
  const c = airborne(); c.run(0.1, { roll: 0 }); c.run(0.1, { roll: 80, rates: { p: 0, q: 0, r: 0 } });   // 0,1 sn'de 80° ama açısal hız 0
  assert.ok(c.codes().includes('IMU_FAULT'), 'tutum sıçraması'); c.run(5, { roll: 0 }); assert.ok(!c.codes().includes('IMU_FAULT'), '3 sn mandal + temizlenme');
  const d = airborne(); d.run(2.5, { rates: { p: 0, q: 0, r: 250 } }); assert.ok(d.codes().includes('IMU_FAULT'), 'sürekli dönme (yaw 250°/s, 2 sn)');
  const e = airborne(); e.run(0.6, { rates: { p: 500, q: 0, r: 0 } }); assert.ok(e.codes().includes('IMU_FAULT'), 'aşırı açısal hız');
  const f = airborne('multirotor', {}, {}, { mode: 'ACRO' }); f.run(3, { mode: 'ACRO', rates: { p: 500, q: 0, r: 300 } }); assert.ok(!f.codes().includes('IMU_FAULT'), 'ACRO takla serbest');
  const g = airborne(); g.run(0.1, { roll: 10 }); g.run(0.1, { roll: 40, rates: { p: 300, q: 0, r: 0 } }); assert.ok(!g.codes().includes('IMU_FAULT'), 'tutarlı hızlı yatış sıçrama değil');
});
test('BATARYA / YAKIT / GPS / GEOFENCE / LINK / VIBRATION / WIND', () => {
  const a = airborne(); a.run(1.5, { battPct: 20 }); assert.ok(a.codes().includes('BATT_LOW')); a.run(1.5, { battPct: 8 }); assert.ok(a.codes().includes('BATT_CRIT')); assert.ok(!a.codes().includes('BATT_LOW') || a.log.at(-1).active.find(x => x.code === 'BATT_LOW').clearing);
  const b = airborne(); b.run(1.5, { battEmpty: true }); assert.ok(b.codes().includes('BATT_CRIT'));
  const f = airborne(); f.run(1.5, { fuelPct: 15 }); assert.ok(f.codes().includes('FUEL_LOW')); f.run(1.5, { fuelPct: 3 }); assert.ok(f.codes().includes('FUEL'));
  const gps = airborne(); gps.run(0.5, { gpsFix: 1 }); assert.ok(!gps.codes().includes('GPS_LOST'), '1 sn gecikme'); gps.run(1, { gpsFix: 1 }); assert.ok(gps.codes().includes('GPS_LOST'));
  const ng = sim('multirotor'); ng.run(8, { gpsFix: 0 }); assert.ok(!ng.codes().includes('GPS_LOST'), 'hiç 3B fix görülmediyse kayıp sayılmaz');
  const fe = airborne('multirotor', {}, { fence: 500 }); fe.run(1, { distHome: 520 }); assert.ok(fe.codes().includes('GEOFENCE'));
  const nf = airborne(); nf.run(1, { distHome: 5000 }); assert.ok(!nf.codes().includes('GEOFENCE'), 'çit yoksa yok');
  const l = airborne(); l.run(0.5, { linkAge: 2000 }); assert.ok(!l.codes().includes('LINK'), '1 sn gecikme'); l.run(0.7, { linkAge: 2000 }); assert.ok(l.codes().includes('LINK')); assert.equal(l.log.at(-1).primary.level, 'caution');
  const v = airborne(); v.run(1.5, { vibe: 45 }); assert.ok(v.codes().includes('VIBRATION'));
  const w = airborne(); w.run(2.5, { wind: 14 }); assert.ok(w.codes().includes('WIND'));
});
test("TOO LOW (iniş dışında alçak + hızlı) ve DON'T SINK (kalkıştan sonra irtifa kaybı)", () => {
  const s = sim('multirotor'); s.run(8, { agl: 30 }); s.run(1, { agl: 3, gs: 10 });
  assert.ok(s.codes().includes('TOO_LOW'));
  const d = sim('multirotor'); d.run(4, { agl: 30, vs: 2 }); d.run(1, { agl: 20, vs: -2 });
  assert.ok(d.codes().includes('DONT_SINK'));
  const p = sim('sabit_kanat'); p.run(10, { mode: 'FBWA', as: 22, agl: 150 }); p.run(1, { mode: 'FBWA', as: 22, gs: 22, agl: 20 });
  assert.ok(p.codes().includes('TOO_LOW'));
});

console.log('evre bastırma, öncelik, onay');
test('ARM’sız uyarı yok; kalkışta (havalanma + 3 sn, rampa aşaması, TAKEOFF) arazi/alçalma/pitch yok', () => {
  const s = sim('multirotor'); s.run(3, { armed: false, roll: 60, agl: 20, vs: -10, battPct: 3 });
  assert.equal(s.codes().length, 0);
  const k = sim('multirotor'); k.run(0.1, { agl: 0.5 }); k.run(1, { agl: 5, vs: -8, pitch: 50 });
  assert.ok(!k.codes().includes('PULL_UP') && !k.codes().includes('PITCH'), 'havalanma süresi içinde');
  const r = sim('sabit_kanat'); r.run(10, { mode: 'TAKEOFF', phase: 'launch', as: 5, gs: 5, pitch: 40, agl: 10 });
  assert.ok(!r.codes().includes('STALL') && !r.codes().includes('PITCH'), 'rampa / TAKEOFF');
});
test('LAND / RTL son yaklaşmasında TERRAIN / TOO LOW / DON’T SINK bastırılır; çarpışmada hepsi susar', () => {
  const s = sim('multirotor'); s.run(8, { agl: 30 }); s.run(1, { mode: 'LAND', agl: 3, gs: 10, vs: -1 });
  assert.ok(!s.codes().includes('TOO_LOW') && !s.codes().includes('DONT_SINK'));
  const r = sim('multirotor'); r.run(8, { agl: 30 }); r.run(1, { mode: 'RTL', agl: 3, gs: 10, distHome: 20 });
  assert.ok(!r.codes().includes('TOO_LOW'));
  const c = airborne(); c.run(1, { roll: 60 }); assert.ok(c.codes().includes('BANK_ANGLE')); c.run(4, { roll: 60, crashed: true }); assert.equal(c.codes().length, 0);
});
test('öncelik: aynı anda birden çok → en yüksek öncelikli birincil; WARNING > CAUTION', () => {
  const s = airborne(); s.run(0.1, { roll: 30, rates: { p: 300, q: 0, r: 0 } });   // tutarlı yatış (sıçrama değil)
  const r = s.run(2, { roll: 60, rates: { p: 300, q: 0, r: 0 }, battPct: 20, agl: 20, vs: -8 });
  assert.ok(!r.active.some(a => a.code === 'IMU_FAULT'));
  assert.deepEqual(r.active.map(a => a.code).slice(0, 3), ['PULL_UP', 'BANK_ANGLE', 'SINK_RATE']);
  assert.equal(r.active.at(-1).code, 'BATT_LOW');
  const prios = GPWS_CODES.map(c => c.prio); assert.deepEqual(prios, [...prios].sort((a, b) => b - a), 'tablo öncelik sırasında');
  assert.ok(GPWS_CODES.filter(c => c.level === 'warning').every(w => GPWS_CODES.filter(c => c.level === 'caution').every(c => w.prio > c.prio)));
});
test('onay: ack → acked (ses susar), görsel kalır; yeni uyarı acked değil; seviye bazlı onay', () => {
  const s = airborne(); s.run(1, { roll: 60 });
  assert.equal(s.g.ack(), 1); assert.equal(s.g.ack(), 0, 'ikinci kez yok');
  let r = s.run(0.5, { roll: 60 }); assert.ok(r.active[0].acked);
  r = s.run(1.5, { roll: 60, battPct: 20 });
  assert.ok(r.active.find(a => a.code === 'BATT_LOW' && !a.acked)); assert.ok(r.active.find(a => a.code === 'BANK_ANGLE').acked);
  assert.equal(s.g.ack('warning'), 0); assert.equal(s.g.ack('caution'), 1);
  // temizlenip yeniden açılınca acked sıfırlanır
  s.run(4, { roll: 0, battPct: 80 }); r = s.run(1, { roll: 60 }); assert.equal(r.active[0].acked, false);
});
test('zaman geri gider (Sıfırla / kayıtta geri atlama) → açık bölümler kapanır, bellek sıfırlanır; kapalı mod → hiç uyarı', () => {
  const g = createGpws({ vehicle: 'multirotor' });
  for (let t = 0; t < 8; t += 0.1) g.step({ ...BASE, t });
  for (let t = 8; t < 9; t += 0.1) g.step({ ...BASE, t, roll: 60 });
  const r = g.step({ ...BASE, t: 1, roll: 60 });
  assert.ok(r.ended.some(e => e.code === 'BANK_ANGLE')); assert.equal(r.active.length, 0, 'kalkış süresi yeniden başlar (bellek sıfır)');
  const off = createGpws({ vehicle: 'multirotor', cfg: { mode: 'off' } });
  for (let t = 0; t < 10; t += 0.1) assert.equal(off.step({ ...BASE, t, roll: 80 }).active.length, 0);
  const one = createGpws({ vehicle: 'multirotor', cfg: { off: ['BANK_ANGLE'] } });
  for (let t = 0; t < 10; t += 0.1) one.step({ ...BASE, t, roll: 80 });
  assert.equal(one.step({ ...BASE, t: 10.1, roll: 80 }).active.length, 0, 'tür kapalı');
  const sw = createGpws({ vehicle: 'multirotor' });
  for (let t = 0; t < 8; t += 0.1) sw.step({ ...BASE, t, roll: Math.min(80, Math.max(0, (t - 6) * 200)), rates: null });   // 20°/kare: sıçrama değil
  sw.setCfg({ off: ['BANK_ANGLE'] }); assert.equal(sw.step({ ...BASE, t: 8.1, roll: 80 }).active.length, 0, 'uçuşta kapatılınca hemen kapanır');
});
test('kara aracı: uçuş uyarıları yok, batarya / IMU var', () => {
  const s = sim('rover'); s.run(8, { mode: 'MANUAL', agl: 0, roll: 50, pitch: 40, gs: 30, vs: -5 });
  assert.equal(s.codes().length, 0);
  s.run(1.5, { mode: 'MANUAL', agl: 0, battPct: 5, sensBad: 2 }); assert.ok(s.codes().includes('BATT_CRIT') && s.codes().includes('IMU_FAULT'));
});

console.log('özet ve puan');
test('özet: tür başına adet / toplam süre / ilk görülme; puan formülü; kapalıyken puan yok', () => {
  const ev = [{ code: 'PULL_UP', level: 'warning', t0: 100, start_s: 30, dur_s: 4 }, { code: 'PULL_UP', level: 'warning', t0: 200, start_s: 130, dur_s: 2 }, { code: 'TOO_LOW', level: 'caution', t0: 150, start_s: 80, dur_s: 10 }];
  const S = summarizeAlerts(ev);
  assert.equal(S.by_code.PULL_UP.n, 2); assert.equal(S.by_code.PULL_UP.total_s, 6); assert.equal(S.by_code.PULL_UP.first_s, 30);
  assert.equal(S.warnings, 2); assert.equal(S.cautions, 1); assert.equal(S.total_s, 16);
  // ceza: (6 + 6) + (6 + 3) + min(8, 2 + 5) = 12 + 9 + 7 = 28 → 72
  assert.equal(penaltyOf({ level: 'warning', dur_s: 4 }), 12); assert.equal(penaltyOf({ level: 'warning', dur_s: 100 }), 20, 'tavan');
  assert.equal(S.score, 72); assert.equal(S.grade, 'C');
  assert.equal(summarizeAlerts([]).score, 100); assert.equal(summarizeAlerts([]).grade, 'A');
  assert.equal(summarizeAlerts(ev, { mode: 'off' }).score, null);
  assert.deepEqual([gradeOf(95), gradeOf(80), gradeOf(61), gradeOf(45), gradeOf(10), gradeOf(null)], ['A', 'B', 'C', 'D', 'F', null]);
  const rows = alertRows(S, makeGpwsT(null));
  assert.deepEqual(rows.map(r => r.code), ['PULL_UP', 'TOO_LOW']); assert.equal(rows[0].text, 'PULL UP'); assert.equal(rows[0].first, '00:30');
  assert.equal(alertRows(S, makeGpwsT(null), 'ui')[0].text, 'YUKARI ÇEK');
});
test('değerlendirici özeti: bölümler start_s (ilk ARM’dan) ve puan', () => {
  const s = airborne(); s.run(1, { roll: 60 }); s.run(4, { roll: 0 });
  const S = s.g.summary();
  assert.equal(S.by_code.BANK_ANGLE.n, 1); assert.ok(S.by_code.BANK_ANGLE.first_s > 9.5 && S.by_code.BANK_ANGLE.first_s < 10.5); assert.ok(S.score < 100 && S.score > 80);
});

console.log('ayarlar, telemetri, metinler');
test('ayar normalleştirme + tercih deposu (varsayılan Görsel + ses AÇIK)', () => {
  assert.deepEqual(normalizeGpwsCfg(null), { ...GPWS_DEFAULT, off: [] }); assert.equal(GPWS_DEFAULT.mode, 'full');
  assert.deepEqual(normalizeGpwsCfg({ mode: 'x', bank_copter: 99, bank_plane: 10, off: ['PULL_UP', 'NOPE', 'PULL_UP'] }), { mode: 'full', lang: 'aviation', sens: 'normal', bank_copter: 60, bank_plane: 30, off: ['PULL_UP'] });
  let stored = null; const P = createGpwsPrefs({ get: () => stored, set: v => { stored = v; } });
  let seen = null; P.onChange(c => { seen = c.mode; });
  P.set({ mode: 'visual' }); assert.equal(stored.mode, 'visual'); assert.equal(seen, 'visual');
  P.toggleCode('STALL', false); assert.deepEqual(stored.off, ['STALL']); P.toggleCode('STALL', true); assert.deepEqual(stored.off, []);
});
test('telemetri dönüşümü: rad → °, rs/ps/ys → °/s, climb/vd, §23 elektrik/yakıt öncelikli, AGL ctx > terrain_agl > alt_rel, zaman tbm / t / ts', () => {
  const I = teleInput({ tbm: 12500, armed: true, mode: 'LOITER', roll: Math.PI / 4, pitch: -0.1, rs: 1, ps: 0, ys: -2, vd: 3, groundspeed: 7, airspeed: 6, batt_pct: 50, elec: { pct: 22, empty: false },
    fuel: { pct: 4 }, gps_fix: 3, sats: 10, sens_bad: 1, ekf: 0.3, vibe: 12, wind_spd: 4, motor_cut: true, alt_rel: 50, terrain_agl: 45 }, { agl: 41, phase: 'released', linkAge: 300 });
  assert.equal(I.t, 12.5); assert.ok(Math.abs(I.roll - 45) < 1e-9); assert.ok(Math.abs(I.rates.r + 114.59) < 0.01); assert.equal(I.vs, -3); assert.equal(I.battPct, 22); assert.equal(I.fuelPct, 4);
  assert.equal(I.agl, 41); assert.equal(I.sensBad, 1); assert.equal(I.motorCut, true); assert.equal(I.linkAge, 300);
  assert.equal(teleInput({ alt_rel: 9, terrain_agl: 7 }).agl, 7); assert.equal(teleInput({ alt_rel: 9 }).agl, 9);
  assert.equal(teleInput({ t: 33.2, climb: 1.5 }).t, 33.2); assert.equal(teleInput({ t: 1, climb: 1.5 }).vs, 1.5);
  assert.equal(teleInput({ ts: 1700000000123 }).t, 1700000000.123); assert.equal(teleInput({}).rates, null);
});
test('metinler: havacılık dili İngilizce, arayüz dili çeviri; olay şeridi "WARNING · PULL UP"; keyed (SIMUMAV) anahtar', () => {
  const T = makeGpwsT(null);
  assert.equal(alertText('PULL_UP', 'aviation', T), 'PULL UP'); assert.equal(alertText('BANK_ANGLE', 'ui', T), 'YATIŞ AÇISI');
  assert.equal(alertSpeech('STALL', 'aviation', T), 'Stall, stall'); assert.equal(alertSpeech('STALL', 'ui', T, 'tr'), 'perdövites');
  assert.equal(alertEventText('PULL_UP', 'aviation', T), 'WARNING · PULL UP'); assert.equal(alertEventText('TOO_LOW', 'aviation', T), 'CAUTION · TOO LOW');
  assert.equal(alertEventSev('PULL_UP'), 'error'); assert.equal(alertEventSev('WIND'), 'warning');
  const keyed = makeGpwsT((k, p) => (k === 'gpws.title' ? 'Flight alerts' : k), true);
  assert.equal(keyed('gpws.title'), 'Flight alerts'); assert.equal(keyed('gpws.mode_off'), 'Kapalı', 'eksik anahtar → Türkçe');
  const plain = makeGpwsT(s => `<${s}>`); assert.equal(plain('gpws.title'), '<Uçuş uyarıları>');
});
test('HEPGO 6 dil: tüm Türkçe metinler kataloglarda; SIMUMAV 7 dil: tüm gpws.* anahtarları', () => {
  const trTexts = GPWS_TEXTS.map(([, tx]) => tx);
  for (const f of ['i18n.en.extra2.js', 'i18n.de.js', 'i18n.fr.js', 'i18n.es.js', 'i18n.ru.js', 'i18n.ar.js']) {
    const src = readFileSync(join(ROOT, 'static/js', f), 'utf8');
    const missing = trTexts.filter(tx => !src.includes(JSON.stringify(tx)));
    assert.deepEqual(missing, [], `${f} eksik`);
  }
  for (const lg of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${lg}.json`), 'utf8'));
    const missing = GPWS_TEXTS.map(([k]) => k).filter(k => !d[k]);
    assert.deepEqual(missing, [], `SIMUMAV ${lg} eksik`);
  }
});
test('bağlama: HEPGO oturumu + rapor + SIMUMAV oturumu + kayıttan oynatma modülü kullanır; sunucu kod listesi aynı', () => {
  const hep = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.match(hep, /createGpwsCtl/); assert.match(hep, /gpws\?\.flush\(\)/); assert.match(hep, /gpws\?\.update\(/);
  const rep = readFileSync(join(ROOT, 'static/js/modules/flightsim_report.js'), 'utf8'); assert.match(rep, /gpwsSection/);
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/session.js'), 'utf8'); assert.match(sm, /flightsim_gpws_ui\.js/); assert.match(sm, /createGpwsCtl/);
  const smr = readFileSync(join(ROOT, 'static/simumav/app/ops/replay.js'), 'utf8'); assert.match(smr, /flightsim_gpws/);
  const py = readFileSync(join(ROOT, 'app/flightsim_gpws.py'), 'utf8');
  for (const c of GPWS_CODES) assert.match(py, new RegExp(`'${c.code}': '${c.level}'`), `sunucuda ${c.code}`);
});

console.log(`\n${n} test geçti`);
