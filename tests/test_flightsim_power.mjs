// Uçuş Simülatörü — §23 güç ve yakıt tarayıcısız birim testi: saf model (yakıt L/dk, batarya Wh, servo J, ölçülen km/L, ortalama W),
// kayıttan oynatma istemci modeli (createPowerSim adım/bitiş/rebuild), gösterge metinleri, OSD/HUD alanları (osdBattery, osdFuelText, osdWarnings
// yakıt/elektronik uyarıları), simülasyon hızı kapsülü (sahte h ile). Çalıştırma: node tests/test_flightsim_power.mjs
import assert from 'node:assert/strict';
import { fuelLpm, batteryWh, servoJoule, measuredKmPerL, avgW, elecVolts, createPowerSim, powerWarnings, fuelText, elecText, rangeText, minText, defaultsFor, isPlaneType,
  createSpeedPill, SPEEDUPS, CAYMAZ_DEFAULTS, LIMITS, POWER_FIELDS,
  gaugeLevel, gaugeColor, gaugeArc, fuelGauge, elecGauge, gaugeModels, createPowerAcc, powerDetailRows, GAUGE_LOW_PCT, GAUGE_CRIT_PCT, GAUGE_COLORS,
  needleAngle, niceScaleMax, scaleTicks, zoneArc, arcPath, easeNeedle, speedGauge, engineGauge, dashModels, GAUGE_SWEEP, ENGINE_RED_PCT, NEEDLE_SNAP } from '../static/js/modules/flightsim_power.js';
import { osdWarnings, osdBattery, osdFuelText, osdPowerRows, LOW_FUEL_PCT } from '../static/js/modules/flightsim_fpv_osd.js';
import { hudPowerBars } from '../static/js/modules/flightsim_hud.js';

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

console.log('Güç paneli kadranları (§23.6)');
test('seviye eşikleri: ≥ 30 yeşil, < 30 sarı, < 15 kırmızı, ≤ 0 / empty bitti; renkler; 270° yay uzunluğu (pathLength 100 → 75)', () => {
  assert.equal(GAUGE_LOW_PCT, 30); assert.equal(GAUGE_CRIT_PCT, 15);
  assert.equal(gaugeLevel(96), 'ok'); assert.equal(gaugeLevel(30), 'ok'); assert.equal(gaugeLevel(29.9), 'low'); assert.equal(gaugeLevel(15), 'low'); assert.equal(gaugeLevel(14.9), 'crit');
  assert.equal(gaugeLevel(0), 'empty'); assert.equal(gaugeLevel(50, true), 'empty'); assert.equal(gaugeLevel(null), 'empty');
  assert.equal(gaugeColor(96), GAUGE_COLORS.ok); assert.equal(gaugeColor(20), '#fbbf24'); assert.equal(gaugeColor(5), '#ef4444');
  assert.equal(gaugeArc(100), 75); assert.equal(gaugeArc(50), 37.5); assert.equal(gaugeArc(0), 0); assert.equal(gaugeArc(140), 75); assert.equal(gaugeArc(-3), 0);
});
test('yakıt kadranı: ana "4.82 L", ikincil "≈ 113 km", anlık "0.41 L/sa", rozet yok; bitince rozet YAKIT BİTTİ + 0 km', () => {
  const m = fuelGauge({ l: 4.8213, pct: 96.4, lpm: 0.00683, range_km: 113.2 });
  assert.equal(m.kind, 'fuel'); assert.equal(m.main, '4.82 L'); assert.equal(m.pctText, '%96'); assert.equal(m.sub, '≈ 113 km'); assert.equal(m.rate, '0.41 L/sa'); assert.equal(m.level, 'ok'); assert.equal(m.badge, null); assert.equal(m.arc, 72.3);
  const e = fuelGauge({ l: 0, pct: 0, lpm: 0, range_km: 0, empty: true });
  assert.equal(e.level, 'empty'); assert.equal(e.badge, 'YAKIT BİTTİ'); assert.equal(e.sub, '0 km'); assert.equal(e.arc, 0); assert.ok(e.empty);
  assert.equal(fuelGauge({ l: 0.6, pct: 12 }).level, 'crit'); assert.equal(fuelGauge(null), null);
});
test('batarya kadranı: elektronik ("%99", "16.8 V · ≈ 5 sa 14 dk", "31 W · 4S"); bitince BATARYA BİTTİ; SITL pili yedeği (sitl: true, "SITL pili")', () => {
  const m = elecGauge({ pct: 99.2, v: 16.78, min_left: 314, w: 31.4, cells: 4, wh: 146 });
  assert.equal(m.main, '%99'); assert.equal(m.sub, '16.8 V · ≈ 5 sa 14 dk'); assert.equal(m.rate, '31 W · 4S'); assert.equal(m.pctText, '16.8 V'); assert.equal(m.sitl, false); assert.equal(m.badge, null);
  const e = elecGauge({ pct: 0, v: 14, min_left: null, w: 30, cells: 4, wh: 0, empty: true });
  assert.equal(e.level, 'empty'); assert.equal(e.badge, 'BATARYA BİTTİ'); assert.equal(e.sub, '14.0 V');
  const s = elecGauge(null, { batt_v: 15.4, batt_pct: 61 });
  assert.ok(s.sitl); assert.equal(s.main, '%61'); assert.equal(s.rate, 'SITL pili'); assert.equal(s.sub, '15.4 V'); assert.equal(s.badge, null);
  const g = elecGauge(null, { batt_v: 15.4, batt_pct: null });   // yüzde yok → gerilimden kaba kestirim (4S, 3,85 V/hücre ≈ %50)
  assert.ok(g.pct > 40 && g.pct < 60, String(g.pct));
  assert.equal(elecGauge(null, { batt_v: 0, batt_pct: null }), null); assert.equal(elecGauge(null, null), null);
});
test('gaugeModels: yakıt 0 L (elektrikli) → yalnız batarya; batarya tanımsız → yalnız yakıt; hiçbiri yok → ikisi de null', () => {
  const a = gaugeModels({ fuel: null, elec: { pct: 80, v: 16, wh: 100, w: 30, cells: 4 } }); assert.equal(a.fuel, null); assert.ok(a.elec);
  const b = gaugeModels({ fuel: { l: 3, pct: 60, range_km: 75, lpm: 0.01 }, elec: null, batt_v: 0 }); assert.ok(b.fuel); assert.equal(b.elec, null);
  const c = gaugeModels({}); assert.equal(c.fuel, null); assert.equal(c.elec, null); assert.deepEqual(gaugeModels(null), { fuel: null, elec: null });
});
test('mesafe/süre toplayıcısı: kayıt t (sn) / SITL tbm (ms) / ts (ms); yalnız armed mesafe; > 5 sn boşluk ve geri zaman atlanır; reset', () => {
  const a = createPowerAcc();
  a.step({ t: 0, armed: true, groundspeed: 20 }); a.step({ t: 1, armed: true, groundspeed: 20 }); a.step({ t: 2, armed: false, groundspeed: 20 });
  close(a.dist_m, 20); close(a.time_s, 2); close(a.armed_s, 1);
  a.step({ t: 10, armed: true, groundspeed: 20 }); close(a.dist_m, 20);   // 8 sn boşluk: atlanır
  a.step({ t: 5, armed: true, groundspeed: 20 }); close(a.dist_m, 20);    // geri: atlanır
  a.reset(); assert.equal(a.dist_m, 0);
  const b = createPowerAcc(); b.step({ tbm: 1000, armed: true, gs: 10 }); b.step({ tbm: 3000, armed: true, gs: 10 }); close(b.dist_m, 20);
  const c = createPowerAcc(); c.step({ ts: 5000, armed: true, groundspeed: 5 }); c.step({ ts: 6000, armed: true, groundspeed: 5 }); close(c.dist_m, 5);
  const d = createPowerAcc(); d.step({ armed: true, groundspeed: 5 }); d.step(null); assert.equal(d.dist_m, 0);   // zaman alanı yok
});
test('ayrıntı satırları: başlangıç / tüketim ayarı / harcanan / anlık / ölçülen / mesafe — kayıt özetinden ya da canlı toplayıcıdan; kaynak yoksa "—"', () => {
  const S = { fuel_l: 5, fuel_km_per_l: 25, elec_cells: 4, elec_mah: 10000, elec_w: 30 };
  const t = { fuel: { l: 4.5, pct: 90, lpm: 0.04, range_km: 112.5 }, elec: { pct: 90, v: 16.5, wh: 133.2, w: 31, cells: 4 } };
  const r = powerDetailRows(t, S, { dist_m: 12000, time_s: 600, fuel: { used_l: 0.5, km_per_l: 24 }, elec: { wh_used: 14.8, w_avg: 29.6 } });
  assert.equal(r.length, 6);
  assert.deepEqual(r[0], ['Başlangıç', '5.00 L', '148 Wh · 4S 10000 mAh']); assert.deepEqual(r[1], ['Tüketim ayarı', '25 km/L', '30 W']);
  assert.deepEqual(r[2], ['Harcanan', '0.50 L', '14.8 Wh']); assert.deepEqual(r[3], ['Anlık', '2.40 L/sa', '31 W']);
  assert.deepEqual(r[4], ['Ölçülen', '24 km/L', 'ort. 29.6 W']); assert.deepEqual(r[5], ['Mesafe', '12 km · 10 dk', '']);
  const live = powerDetailRows(t, S, { dist_m: 12000, time_s: 600 });   // canlı: harcanan = başlangıç − kalan; ölçülen hesaplanır
  assert.equal(live[2][1], '0.50 L'); assert.equal(live[4][1], '24 km/L'); assert.equal(live[2][2], '14.8 Wh'); assert.equal(live[4][2], 'ort. 88.8 W');
  const none = powerDetailRows({ fuel: null, elec: t.elec }, S, { dist_m: 100, time_s: 10 });
  assert.equal(none[0][1], '—'); assert.equal(none[4][2], 'henüz yok'); assert.equal(none[5][1], '100 m · 0 dk');
  assert.equal(powerDetailRows(t, S, null, s => `[${s}]`)[0][0], '[Başlangıç]');
});
test('FPV OSD güç satırları: BAT (elektronik: V % S min) üstte, FUEL (L % km) altta; seviye kadranlarla aynı; SITL pili; hiçbiri yoksa []', () => {
  const r = osdPowerRows({ elec: { v: 16.2, pct: 61.4, cells: 4, min_left: 120.4, empty: false }, fuel: { l: 4.1432, pct: 82.86, range_km: 103.58 } });
  assert.deepEqual(r.map(x => [x.key, x.label, x.level, x.value]), [['bat', 'BAT', 'ok', '16.2V 61% 4S 120min'], ['fuel', 'FUEL', 'ok', '4.14L 83% 104km']]);
  const s = osdPowerRows({ batt_v: 15.4, batt_pct: 22 }); assert.equal(s.length, 1); assert.equal(s[0].level, 'low'); assert.equal(s[0].value, '15.4V 22% 4S');
  const e = osdPowerRows({ fuel: { l: 0, pct: 0, range_km: 0, empty: true } }); assert.equal(e[0].level, 'empty'); assert.equal(e[0].pct, 0);
  assert.deepEqual(osdPowerRows({}), []); assert.equal(osdPowerRows({ fuel: { l: 0.3, pct: 6, range_km: 7.5 } })[0].level, 'crit');
});
test('gimbal HUD dikey barlar: BAT (V · kalan dk) + FUEL (L · menzil); düşük < 25 / < 20 kırmızı; bitti; SITL pili yüzdesi', () => {
  const b = hudPowerBars({ elec: { pct: 99, v: 16.8, min_left: 312, empty: false }, fuel: { l: 4.71, pct: 94, range_km: 111 } });
  assert.deepEqual(b, [{ label: 'BAT', pct: 99, low: false, empty: false, l1: '16.8V', l2: '312min' }, { label: 'FUEL', pct: 94, low: false, empty: false, l1: '4.71L', l2: '111km' }]);
  const l = hudPowerBars({ elec: { pct: 20, v: 14.5, min_left: 3 }, fuel: { l: 0.5, pct: 10, range_km: 2.5 } }); assert.ok(l[0].low && l[1].low); assert.equal(l[1].l2, '2.5km');
  const e = hudPowerBars({ elec: { pct: 0, v: 14, wh: 0, empty: true }, fuel: { l: 0, pct: 0, empty: true } }); assert.ok(e[0].empty && e[1].empty && e[0].low);
  const s = hudPowerBars({ batt_v: 15.4, batt_pct: 61 }); assert.equal(s.length, 1); assert.equal(s[0].l1, '15.4V'); assert.equal(s[0].l2, '');
  assert.deepEqual(hudPowerBars({}), []); assert.deepEqual(hudPowerBars(null), []);
});

console.log('Analog kadranlar (§23.6 yeniden tasarım: 240° süpürme, ölçek, bölgeler, ibre)');
test('ibre açısı: min → −120°, orta → 0°, max → +120°; aralık dışı kırpılır; geçersiz aralık/değer → min', () => {
  assert.equal(GAUGE_SWEEP, 240);
  assert.equal(needleAngle(0, 0, 100), -120); assert.equal(needleAngle(50, 0, 100), 0); assert.equal(needleAngle(100, 0, 100), 120); assert.equal(needleAngle(25, 0, 100), -60);
  assert.equal(needleAngle(140, 0, 100), 120); assert.equal(needleAngle(-5, 0, 100), -120); assert.equal(needleAngle(0.75, 0, 1), 60);
  assert.equal(needleAngle(null, 0, 100), -120); assert.equal(needleAngle(5, 10, 10), -120); assert.equal(needleAngle(50, 0, 100, 270), 0);
});
test('ölçek üst sınırı: azami × 1,2 güzel adıma yuvarlanır (162 km/h → 200/50; 45 → 60/10; 400 → 500/100); ana bölme 4–6', () => {
  assert.deepEqual(niceScaleMax(162), { max: 200, step: 50 }); assert.deepEqual(niceScaleMax(45), { max: 60, step: 10 }); assert.deepEqual(niceScaleMax(400), { max: 500, step: 100 });
  assert.deepEqual(niceScaleMax(8, 1), { max: 8, step: 2 }); assert.deepEqual(niceScaleMax(100 / 1.2), { max: 100, step: 20 });
  for (const v of [12, 33, 77, 162, 250, 540, 1000]) { const s = niceScaleMax(v); assert.ok(s.max >= v * 1.2 - 1e-9 && s.max / s.step >= 4 && s.max / s.step <= 6, `${v} → ${JSON.stringify(s)}`); }
});
test('çentikler: ana + ara (0…100 adım 20, ara 2 → 11 çentik, 6 ana); yakıt 0…1 adım ¼; açılar −120…120; geçersiz → []', () => {
  const t = scaleTicks(100, 20, 2);
  assert.equal(t.length, 11); assert.equal(t.filter(x => x.major).length, 6); assert.equal(t[0].a, -120); assert.equal(t[10].a, 120); assert.equal(t[1].v, 10); assert.ok(!t[1].major);
  const f = scaleTicks(1, 0.25, 2); assert.equal(f.length, 9); assert.deepEqual(f.filter(x => x.major).map(x => x.v), [0, 0.25, 0.5, 0.75, 1]);
  assert.deepEqual(scaleTicks(100, 0), []); assert.deepEqual(scaleTicks(0, 10), []);
});
test('bölge yayı: azami 162 → ölçek 200 kırmızı [162, 200] = 74,4° … 120°; batarya kırmızı [0, 15], mavi [90, 100]; boş aralık null; SVG yay yolu', () => {
  const r = zoneArc(162, 200, 0, 200); close(r.a0, 74.4, 0.01); assert.equal(r.a1, 120);
  assert.deepEqual(zoneArc(0, 15, 0, 100), { a0: -120, a1: -84 }); assert.deepEqual(zoneArc(90, 100, 0, 100), { a0: 96, a1: 120 });
  assert.equal(zoneArc(100, 100, 0, 100), null); assert.equal(zoneArc(null, 5, 0, 100), null); assert.equal(zoneArc(5, 10, 10, 10), null);
  const d = arcPath(-120, 120, 46); assert.ok(d.startsWith('M ') && d.includes(' A 46 46 0 1 1 '), d);   // 240° → büyük yay bayrağı
  assert.ok(arcPath(0, 90, 10).includes(' A 10 10 0 0 1 ')); assert.equal(arcPath(0, 0, 10, 50, 50), 'M 50.00 40.00 A 10 10 0 0 1 50.00 40.00');
});
test('ibre yumuşatma: üstel yaklaşım (tau), NEEDLE_SNAP altında hedefe oturur, dt yoksa hedef; birikerek yakınsar', () => {
  const a = easeNeedle(0, 100, 0.22); close(a, 100 * (1 - Math.exp(-1)), 1e-9);
  assert.equal(easeNeedle(99.99, 100, 0.016), 100); assert.equal(easeNeedle(0, 100, 0), 100); assert.equal(easeNeedle(null, 42, 0.016), 42);
  let c = -120; for (let i = 0; i < 200; i++) c = easeNeedle(c, 60, 0.016); assert.equal(c, 60);
  assert.ok(easeNeedle(0, 100, 0.016) < easeNeedle(0, 100, 0.05)); assert.ok(NEEDLE_SNAP > 0 && NEEDLE_SNAP < 1);
});
test('hız / motor kadranı ve dashModels: yer hızı km/h, ölçek azami × 1,2, kırmızı bölge, IAS, uyarı üçgeni (çarpışma / aşırı hız / stall); gaz % ya da ×1000 RPM; yakıtsız dron', () => {
  const S = { max_speed_ms: 45 }, t = { groundspeed: 37.2, airspeed: 33.3, throttle: 72, armed: true, alt_rel: 120, fuel: { l: 4.9, pct: 98, range_km: 116, lpm: 0.01 }, elec: { pct: 99, v: 16.8, wh: 146, w: 30, cells: 4, min_left: 314 } };
  const sp = speedGauge(t, S, { plane: true });
  assert.equal(sp.max, 200); assert.equal(sp.step, 50); assert.equal(sp.main, '134'); assert.equal(sp.unit, 'KM/H'); assert.equal(sp.sub, 'IAS 120'); assert.ok(!sp.warn); assert.equal(sp.level, 'ok');
  close(sp.red.a0, 74.4, 0.01); close(sp.angle, needleAngle(133.92, 0, 200), 0.01);
  assert.ok(speedGauge(t, S, { plane: true, collision: true }).warn && speedGauge(t, S, { plane: true, collision: true }).warnKind === 'crash');
  const ov = speedGauge({ ...t, groundspeed: 50 }, S, { plane: true }); assert.ok(ov.warn && ov.warnKind === 'over' && ov.angle === 96);   // 180 km/h, ölçek 200
  const st = speedGauge({ ...t, airspeed: 8, groundspeed: 8 }, S, { plane: true }); assert.ok(st.warn && st.warnKind === 'stall');
  assert.ok(!speedGauge({ ...t, airspeed: 8, groundspeed: 8, alt_rel: 2 }, S, { plane: true }).warn);   // yerde stall yok
  const cp = speedGauge({ groundspeed: 10 }, { max_speed_ms: null }, { plane: false }); assert.equal(cp.max, 100); assert.equal(cp.red, null); assert.equal(cp.sub, '');
  const en = engineGauge(t); assert.equal(en.main, '72'); assert.equal(en.unit, '% GAZ'); assert.equal(en.max, 100); assert.deepEqual(en.red, { a0: needleAngle(ENGINE_RED_PCT, 0, 100), a1: 120 }); assert.equal(en.level, 'ok');
  assert.equal(engineGauge({ throttle: 95 }).level, 'low');
  const rpm = engineGauge({ throttle: 80, rpm: 6400 }); assert.equal(rpm.main, '6.4'); assert.equal(rpm.unit, '×1000 RPM'); assert.equal(rpm.max, 8); assert.equal(rpm.sub, '80 %');
  const d = dashModels(t, S, { plane: true }); assert.ok(d.fuel && d.speed && d.engine && d.elec); assert.equal(d.fuel.main, '4.90 L'); assert.equal(d.fuel.angle, needleAngle(0.98, 0, 1)); assert.equal(d.elec.angle, needleAngle(99, 0, 100));
  const nf = dashModels({ ...t, fuel: null }, S); assert.equal(nf.fuel, null); assert.ok(nf.speed && nf.elec);
  assert.deepEqual(dashModels({ groundspeed: 5 }, S), { fuel: null, speed: null, engine: null, elec: null });   // güç kaynağı yok → hepsi gizli
  assert.equal(speedGauge(null, S), null); assert.equal(engineGauge(null), null);
});

console.log(`\n${n} test geçti`);
