// Uçuş Simülatörü — §23 güç ve yakıt tarayıcısız birim testi: saf model (yakıt L/dk, batarya Wh, servo J, ölçülen km/L, ortalama W),
// kayıttan oynatma istemci modeli (createPowerSim adım/bitiş/rebuild), gösterge metinleri, OSD/HUD alanları (osdBattery, osdFuelText, osdWarnings
// yakıt/elektronik uyarıları), simülasyon hızı kapsülü (sahte h ile). Çalıştırma: node tests/test_flightsim_power.mjs
import assert from 'node:assert/strict';
import { fuelLpm, batteryWh, servoJoule, measuredKmPerL, avgW, elecVolts, createPowerSim, powerWarnings, fuelText, elecText, rangeText, minText, defaultsFor, isPlaneType,
  createSpeedPill, SPEEDUPS, CAYMAZ_DEFAULTS, LIMITS, POWER_FIELDS } from '../static/js/modules/flightsim_power.js';
import { osdWarnings, osdBattery, osdFuelText, LOW_FUEL_PCT } from '../static/js/modules/flightsim_fpv_osd.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);

console.log('Saf model (sunucu flightsim_power.py ile birebir)');
test('yakıt L/dk: (v km/h ÷ 60) ÷ (km/L) × (0,5 + 0,5·gaz); km/L 0 → 0', () => {
  close(fuelLpm(45, 100, 25), 0.108); close(fuelLpm(45, 0, 25), 0.054); close(fuelLpm(45, 50, 25), 0.081); assert.equal(fuelLpm(45, 50, 0), 0); assert.equal(fuelLpm(-3, 50, 25), 0);
});
test('batarya Wh = mAh/1000 × hücre × 3,7; gerilim kestirimi hücre × (3,5 + 0,7·oran)', () => {
  close(batteryWh(10000, 4), 148); close(batteryWh(100, 1), 0.37); assert.equal(batteryWh(null, 4), 0);
  close(elecVolts(4, 1), 16.8); close(elecVolts(4, 0), 14); close(elecVolts(1, 0.5), 3.85);
});
test('servo aktivitesi: Σ|Δpwm| × 0,0005 J; 0/aralık dışı kanallar sayılmaz', () => {
  close(servoJoule([1600, 1500], [1500, 1500]), 0.05); assert.equal(servoJoule([0, 1500], [1500, 1500]), 0); assert.equal(servoJoule(null, [1]), 0);
});
test('ölçülen km/L (≥ 0,3 km ve ≥ 0,02 L) ve ortalama W (≥ 60 s)', () => {
  assert.equal(measuredKmPerL(300, 0.02), 15); assert.equal(measuredKmPerL(299, 0.02), null); assert.equal(measuredKmPerL(5000, 0.01), null);
  assert.equal(avgW(0.5, 60), 30); assert.equal(avgW(0.5, 59), null);
});
test('varsayılanlar: uçak CAYMAZ (45 m/s · 5 L · 25 km/L · 4S 10000 mAh 30 W), kopter yakıtsız ve azami hızsız; sınırlar ve alan listesi', () => {
  assert.deepEqual(defaultsFor('sabit_kanat'), CAYMAZ_DEFAULTS); assert.deepEqual(defaultsFor('vtol'), CAYMAZ_DEFAULTS);
  assert.equal(defaultsFor('multirotor').fuel_l, 0); assert.equal(defaultsFor('multirotor').max_speed_ms, null);
  assert.ok(isPlaneType('vtol') && !isPlaneType('helikopter'));
  assert.deepEqual(POWER_FIELDS, ['max_speed_ms', 'fuel_l', 'fuel_km_per_l', 'elec_cells', 'elec_mah', 'elec_w']);
  assert.deepEqual(LIMITS.elec_cells, [1, 16]); assert.deepEqual(SPEEDUPS, [1, 2, 4, 8]);
});

console.log('Kayıttan oynatma modeli (createPowerSim)');
test('10 Hz 60 sn, 40 m/s gaz %80: 0,05 L tank 34,7 sn\'de biter → ["fuel"]; mesafe/armed süre; batarya 0,37 Wh bitmez; özet km/L', () => {
  const s = createPowerSim({ max_speed_ms: 45, fuel_l: 0.05, fuel_km_per_l: 25, elec_cells: 1, elec_mah: 100, elec_w: 20 });
  const done = [];
  for (let i = 0; i <= 600; i++) done.push(...s.step({ groundspeed: 40, throttle: 80, armed: i >= 10, servo: [1500 + 100 * (i % 2), 1500] }, i / 10));
  assert.deepEqual(done, ['fuel']);
  const st = s.state(), sm = s.summary();
  assert.ok(st.fuel.empty && st.fuel.l === 0 && st.fuel.pct === 0); close(st.fuel.lpm, 0.0864, 1e-9);
  close(sm.dist_m, 40 * 59.1, 1e-6); close(sm.armed_s, 59.1, 1e-6); close(sm.time_s, 60, 1e-6);   // armed adım 10…600 = 591 × 0,1 sn
  close(sm.fuel.used_l, 0.05, 1e-9); assert.ok(sm.fuel.empty_t > 34 && sm.fuel.empty_t < 36.5, String(sm.fuel.empty_t));
  assert.equal(sm.fuel.km_per_l, Math.round(2.364 / 0.05 * 100) / 100);
  assert.ok(sm.elec.wh_used > 0.33 && sm.elec.wh_used < 0.37 && !st.elec.empty && st.elec.cells === 1 && st.elec.w > 19 && st.elec.w < 24, JSON.stringify(st.elec));
  assert.ok(st.elec.min_left > 0 && st.elec.min_left < 1.5);
  assert.equal(st.speedup, 1);
});
test('zaman geri gittiğinde (yeni SITL saati) adım atlanır; > 5 sn boşluk entegre edilmez; disarm yakıt tüketmez, batarya tüketir', () => {
  const s = createPowerSim(CAYMAZ_DEFAULTS);
  assert.deepEqual(s.step({ groundspeed: 20, throttle: 50, armed: true }, 100), []);
  s.step({ groundspeed: 20, throttle: 50, armed: true }, 101);
  const f1 = s.state().fuel.l; assert.ok(f1 < 5);
  s.step({ groundspeed: 20, throttle: 50, armed: true }, 10);   // geri: sıfırlama, tüketim yok
  assert.equal(s.state().fuel.l, f1);
  s.step({ groundspeed: 20, throttle: 50, armed: true }, 20);   // 10 sn boşluk > 5: atlanır
  assert.equal(s.state().fuel.l, f1);
  const wh0 = s.state().elec.wh;
  s.step({ groundspeed: 0, throttle: 0, armed: false }, 21);
  assert.equal(s.state().fuel.l, f1); assert.ok(s.state().elec.wh < wh0);
});
test('rebuild: kare dizisinden t anına kadar baştan entegre (atlama); ileri atlama sonrası seviye düşük, geri atlama sonrası yeniden dolu', () => {
  const fields = ['t', 'gs', 'thr', 'armed', 'servo'], frames = [];
  for (let i = 0; i <= 1200; i++) frames.push([i / 10, 30, 70, i >= 20 ? 1 : 0, null]);
  const data = { fields, frames };
  const s = createPowerSim({ fuel_l: 2, fuel_km_per_l: 10, elec_cells: 4, elec_mah: 10000, elec_w: 30 });
  s.rebuild(data, 60); const a = s.state().fuel.l; assert.ok(a < 2 && a > 1.8, String(a));
  s.rebuild(data, 120); const b = s.state().fuel.l; assert.ok(b < a);
  s.rebuild(data, 1); assert.equal(s.state().fuel.l, 2);
  s.rebuild({ fields: ['lat'], frames: [[1]] }, 50); assert.equal(s.state().fuel.l, 2);   // zaman alanı yok → dokunulmaz
});
test('yakıt kapalı (0 L) → fuel null, batarya var; batarya kapalı (0 mAh) → elec null', () => {
  const s = createPowerSim({ fuel_l: 0, fuel_km_per_l: 25, elec_cells: 4, elec_mah: 10000, elec_w: 30 });
  assert.equal(s.state().fuel, null); assert.ok(s.state().elec); assert.equal(s.summary().fuel, null);
  const e = createPowerSim({ fuel_l: 5, fuel_km_per_l: 25, elec_cells: 4, elec_mah: 0, elec_w: 30 });
  assert.equal(e.state().elec, null); assert.ok(e.state().fuel);
});

console.log('Göstergeler / uyarılar');
test('uyarılar: düşük yakıt < 20 %, yakıt bitti, düşük batarya < 25 %, batarya bitti; yok → []', () => {
  assert.deepEqual(powerWarnings({ fuel: { l: 1, pct: 19 }, elec: { wh: 10, pct: 24 } }), ['lowfuel', 'lowelec']);
  assert.deepEqual(powerWarnings({ fuel: { l: 0, pct: 0, empty: true }, elec: { wh: 0, pct: 0, empty: true } }), ['fuelempty', 'elecempty']);
  assert.deepEqual(powerWarnings({ fuel: { l: 3, pct: 60 }, elec: { wh: 100, pct: 70 } }), []); assert.deepEqual(powerWarnings({}), []);
});
test('metinler: yakıt "4.14 L · %83", batarya "%97 · 16.71 V · 281 dk", menzil (m/km), süre (dk / sa dk)', () => {
  assert.equal(fuelText({ l: 4.1432, pct: 82.86 }), '4.14 L · %83'); assert.equal(fuelText(null), '—');
  assert.equal(elecText({ pct: 96.6, v: 16.71, min_left: 280.6 }), '%97 · 16.71 V · 281 dk'); assert.equal(elecText({ pct: 50, v: 15, min_left: null }), '%50 · 15.00 V');
  assert.equal(rangeText(103.58), '104 km'); assert.equal(rangeText(2.34), '2.3 km'); assert.equal(rangeText(0.42), '420 m'); assert.equal(rangeText(null), '—');
  assert.equal(minText(45.4), '45 dk'); assert.equal(minText(150), '2 sa 30 dk'); assert.equal(minText(null), '—');
});
test('OSD pil alanı: tele.elec varsa elektronik batarya (V kestirimi, %, hücre, kalan dk); yoksa SITL pili (gerilimden % kestirimi, hücre)', () => {
  const e = osdBattery({ elec: { v: 16.2, pct: 61.4, cells: 4, min_left: 120.4, empty: false }, batt_v: 12.1, batt_pct: 90 });
  assert.deepEqual(e, { v: 16.2, pct: 61.4, cells: 4, min: 120.4, elec: true, empty: false });
  const s = osdBattery({ batt_v: 15.4, batt_pct: null });
  assert.equal(s.elec, false); assert.equal(s.cells, 4); assert.ok(s.pct > 45 && s.pct < 55); assert.equal(s.min, null);
  assert.equal(osdBattery({}).v, null);
});
test('OSD yakıt satırı: "FUEL 4.14L 83% 104km"; < 10 km bir ondalık; yakıt yoksa null', () => {
  assert.equal(osdFuelText({ l: 4.1432, pct: 82.86, range_km: 103.58 }), 'FUEL 4.14L 83% 104km');
  assert.equal(osdFuelText({ l: 0.2, pct: 4, range_km: 5.04 }), 'FUEL 0.20L 4% 5.0km'); assert.equal(osdFuelText(null), null);
});
test('OSD uyarıları: elec varsa lowbatt ondan (SITL pili yok sayılır), elecempty; yakıt lowfuel (< 20) / fuelempty; eski imza korunur', () => {
  assert.equal(LOW_FUEL_PCT, 20);
  assert.deepEqual(osdWarnings({ batt: 10, elec: { pct: 80, wh: 100 } }), []);
  assert.deepEqual(osdWarnings({ batt: 90, elec: { pct: 20, wh: 10 } }), ['lowbatt']);
  assert.deepEqual(osdWarnings({ elec: { pct: 0, wh: 0, empty: true }, fuel: { pct: 0, l: 0, empty: true }, collision: true }), ['crash', 'elecempty', 'fuelempty']);
  assert.deepEqual(osdWarnings({ fuel: { pct: 15, l: 0.7 } }), ['lowfuel']);
  assert.deepEqual(osdWarnings({ armed: true, agl: 5, gs: 10, batt: 10, rssi: 20 }), ['lowbatt', 'lowalt', 'rssi']);
});
test('simülasyon hızı kapsülü: 1×/2×/4×/8× düğmeleri, seçim (set) ve onPick; > 1 iken .fast', () => {
  const mk = (tag, attrs = {}, ...children) => { const el = { tag, attrs, children: children.flat().filter(Boolean), classList: new Set(String(attrs.class || '').split(/\s+/).filter(Boolean)), dataset: { speed: attrs['data-speed'] }, disabled: false };
    el.classList.toggle = (c, v) => { if (v) el.classList.add(c); else el.classList.delete(c); }; el.classList.contains = c => el.classList.has(c); el.click = () => attrs.onclick?.(); return el; };
  const picked = [];
  const pill = createSpeedPill({ h: mk, tr: s => s, onPick: f => picked.push(f) });
  assert.deepEqual(pill.el.children.map(b => b.dataset.speed), [1, 2, 4, 8]);
  assert.ok(pill.el.children[0].classList.has('primary') && !pill.el.children[2].classList.has('primary'));
  pill.el.children[2].click(); assert.deepEqual(picked, [4]);
  pill.set(4); assert.ok(pill.el.children[2].classList.has('primary') && !pill.el.children[0].classList.has('primary') && pill.el.classList.has('fast')); assert.equal(pill.value, 4);
  pill.set(1); assert.ok(!pill.el.classList.has('fast'));
  pill.setEnabled(false); assert.ok(pill.el.children.every(b => b.disabled));
});

console.log(`\n${n} test geçti`);
