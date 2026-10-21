// Uçuş Simülatörü — radar altlığı, EO elle kumanda, çarpışma efekti ve alt bant uçuş denetimi saf fonksiyon testleri (node, tarayıcısız).
// Çalıştır: node tests/test_flightsim_simfix.mjs
import assert from 'node:assert/strict';
import { EO_EL, EO_FOV_MAX, EO_FOV_MIN, eoAimMode, eoDragLook, eoPinchFov, eoWheelFov, localToLL, underlayPlan, underlayUV } from '../static/js/modules/flightsim_gcs.js';
import { crashFxParams, flashAt, particleAt, shakeAt } from '../static/js/modules/flightsim_crashfx.js';
import { FLIGHT_MODES, FLT_TEXTS, disarmAction, flightModesFor, isAirborne, makeFltT, modeGroups, modeKind, qMode } from '../static/js/modules/flightsim_fltbar.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);

console.log('EO elle kumanda');
test('tekerlek: üstel, sınırlı; ileri (−) yakınlaştırır, geri (+) uzaklaştırır; aynı adım her FOV\'da aynı oran', () => {
  assert.ok(eoWheelFov(20, -100) < 20 && eoWheelFov(20, 100) > 20);
  close(eoWheelFov(20, -100) / 20, eoWheelFov(2, -100) / 2, 1e-9);
  close(eoWheelFov(EO_FOV_MAX, 5000), EO_FOV_MAX); close(eoWheelFov(EO_FOV_MIN, -5000), EO_FOV_MIN);
  let f = EO_FOV_MAX; for (let i = 0; i < 400; i++) f = eoWheelFov(f, -100); close(f, EO_FOV_MIN);   // tüm ×137 aralığı tekerlekle erişilir
  close(eoWheelFov(NaN, 0), EO_FOV_MAX);
});
test('sıkıştırma: parmaklar açılınca yakınlaşır, sınır içinde', () => {
  close(eoPinchFov(20, 2), 10); close(eoPinchFov(20, 0.5), 40); close(eoPinchFov(1, 100), EO_FOV_MIN); close(eoPinchFov(40, 0.01), EO_FOV_MAX);
});
test('sürükle: zoom\'a göre hassasiyet (1 px = FOV/yükseklik), "tut ve sürükle" yönü, az sarılır, el sınırlı', () => {
  const a = eoDragLook(10, 0, 100, 0, 48, 200); close(a.az, 346); close(a.el, 0);
  const b = eoDragLook(10, 0, 100, 0, 2, 200); close(b.az, 9);           // dar açıda aynı sürükleme 24 kat az döndürür
  close(eoDragLook(5, 0, 100, 0, 48, 200).az, 341);                      // 360'a sarılır
  close(eoDragLook(0, 0, 0, 1e5, 48, 200).el, EO_EL[1]); close(eoDragLook(0, 0, 0, -1e5, 48, 200).el, EO_EL[0]);
  close(eoDragLook(0, 10, 0, -50, 48, 200).el, -2);                      // yukarı sürükleme → aşağı bakar
});
test('nişan kipi: hedef + takip → track; aksi hâlde son yönde sabit (tarama yok)', () => {
  assert.equal(eoAimMode(true, true), 'track'); assert.equal(eoAimMode(true, false), 'hold'); assert.equal(eoAimMode(false, true), 'hold'); assert.equal(eoAimMode(false, false), 'hold');
});

console.log('Radar altlığı');
test('karo planı: kapsamayı örter, eksen başına ≤ 8, olabilecek en ince z', () => {
  for (const [R, lat, lon] of [[20000, 39.93, 32.85], [1000, 39.93, 32.85], [50000, 41.0, 29.0], [8000, -33.9, 151.2]]) {
    const half = R * 1.6, p = underlayPlan(lat, lon, 30, 80, half, 8);
    assert.ok(p.nx <= 8 && p.ny <= 8 && p.nx >= 1 && p.ny >= 1, JSON.stringify(p));
    for (const [x, y] of [[30 - half, 80 - half], [30 + half, 80 + half], [30 - half, 80 + half], [30 + half, 80 - half], [30, 80]]) {
      const [u, v] = underlayUV(p, lat, lon, x, y);
      assert.ok(u >= -1e-9 && u <= 1 + 1e-9 && v >= -1e-9 && v <= 1 + 1e-9, `${R} köşe uv ${u},${v}`);
    }
    const q = underlayPlan(lat, lon, 30, 80, half, 8);
    assert.deepEqual(p, q);
    if (p.z < 15) { const fine = underlayPlan(lat, lon, 30, 80, half, 64); assert.ok(fine.z > p.z, 'daha çok karo izni → daha ince'); }
  }
  assert.equal(underlayPlan(39.93, 32.85, 0, 0, 32000, 8).z, 11);   // Ankara, 20 km kapsama → z 11 (≈ 76 m/piksel)
});
test('UV: kuzey yukarı (v artar), doğu sağa (u artar); localToLL toLocal\'ın tersi', () => {
  const p = underlayPlan(39.93, 32.85, 0, 0, 30000, 8);
  const [u0, v0] = underlayUV(p, 39.93, 32.85, 0, 0), [u1] = underlayUV(p, 39.93, 32.85, 1000, 0), [, v2] = underlayUV(p, 39.93, 32.85, 0, 1000);
  assert.ok(u1 > u0 && v2 > v0);
  const [lat, lon] = localToLL(39.93, 32.85, 1000, 2000);
  close((lon - 32.85) * 111320 * Math.cos(39.93 * Math.PI / 180), 1000, 1e-6); close((lat - 39.93) * 110574, 2000, 1e-6);
});

console.log('Çarpışma efekti');
test('şiddet hızla artar; 42,3 m/s tam şiddet; parametreler sonlu', () => {
  const lo = crashFxParams(3), hi = crashFxParams(42.3);
  assert.ok(lo.i < 0.35 && hi.i === 1);
  for (const k of ['fire', 'fireR', 'dust', 'dustR', 'sparks', 'sparkV', 'shake', 'flash', 'burnS']) assert.ok(hi[k] > lo[k], k);
  for (const v of [null, 0, -5, 1e6]) for (const x of Object.values(crashFxParams(v))) assert.ok(Number.isFinite(x) && x >= 0);
  assert.ok(hi.sparks <= 200 && hi.flash <= 0.95);
  const small = crashFxParams(42.3, 0.5), big = crashFxParams(42.3, 8);   // boyut çarpanı: küçük dronda küçük ateş topu, sınırlı
  close(small.k, 0.4); close(big.k, 2); assert.ok(small.fireR < hi.fireR && big.fireR > hi.fireR && small.fireR <= 5);
});
test('sarsıntı söner ve biter; flaş kısa, tepe başta', () => {
  const p = crashFxParams(30);
  const a = Math.hypot(...Object.values(shakeAt(0.02, p)).slice(0, 3));
  assert.ok(a > 0); assert.equal(shakeAt(p.shakeS + 0.01, p), null); assert.equal(shakeAt(-1, p), null);
  let mx = 0; for (let t = 0.5 * p.shakeS; t < p.shakeS; t += 0.01) { const s = shakeAt(t, p); mx = Math.max(mx, Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)); }
  assert.ok(mx < p.shake * 0.2, 'ikinci yarıda küçük');
  close(flashAt(0.03, p), p.flash); assert.equal(flashAt(p.flashS + 0.01, p), 0); assert.ok(flashAt(0.1, p) < p.flash);
});
test('kıvılcım: balistik, zemine iner, sürüklenmeyle yavaşlar', () => {
  const q0 = particleAt([0, 0, 1], [10, 0, 10], 0); assert.deepEqual(q0, [0, 0, 1]);
  const q1 = particleAt([0, 0, 1], [10, 0, 10], 0.3); assert.ok(q1[0] > 0 && q1[2] > 1);
  close(particleAt([0, 0, 1], [10, 0, 10], 10, 0)[2], 0);
  assert.ok(particleAt([0, 0, 1], [10, 0, 0], 10)[0] < 10 / 0.6 + 1e-9);
});

console.log('Alt bant uçuş denetimi');
test('tip → aile; mod listeleri (Q kipleri VTOL/INTERCEPTOR\'da, kopterde STABILIZE/ALT_HOLD/LOITER/RTL)', () => {
  assert.equal(modeKind('sabit_kanat'), 'plane'); assert.equal(modeKind('vtol'), 'vtol'); assert.equal(modeKind('interceptor'), 'icept'); assert.equal(modeKind('multirotor'), 'copter'); assert.equal(modeKind('helikopter'), 'copter');
  for (const m of ['MANUAL', 'FBWA', 'FBWB', 'CRUISE', 'LOITER', 'RTL', 'AUTO', 'GUIDED', 'TAKEOFF']) assert.ok(FLIGHT_MODES.plane.includes(m), m);
  for (const m of ['STABILIZE', 'ALT_HOLD', 'LOITER', 'RTL', 'LAND']) assert.ok(flightModesFor('copter').includes(m), m);
  for (const m of ['QHOVER', 'QLOITER', 'QLAND', 'QRTL']) assert.ok(FLIGHT_MODES.vtol.includes(m) && FLIGHT_MODES.icept.includes(m), m);
  assert.ok(qMode('QHOVER') && !qMode('GUIDED') && !qMode(null));
  const g = modeGroups('vtol'); assert.equal(g.length, 2); assert.ok(g[1][1].every(qMode) && !g[0][1].some(qMode));
  assert.equal(modeGroups('plane').length, 1);
});
test('DISARM düğmesi: sabit kanat havada motor keser (süzülme), kopter havada onay ister, yerde gerçek disarm', () => {
  const air = { armed: true, alt_rel: 100, airspeed: 22, mode: 'FBWA' }, ground = { armed: true, alt_rel: 0.2, groundspeed: 0 };
  assert.equal(disarmAction('plane', air), 'motor_cut');
  assert.equal(disarmAction('plane', ground), 'disarm');
  assert.equal(disarmAction('copter', { ...air, mode: 'LOITER' }), 'confirm_disarm');
  assert.equal(disarmAction('copter', ground), 'disarm');
  assert.equal(disarmAction('vtol', { ...air, mode: 'QHOVER' }), 'confirm_disarm');
  assert.equal(disarmAction('icept', { ...air, mode: 'CRUISE' }), 'motor_cut');
  assert.equal(disarmAction('plane', { ...air, motor_cut: true }), 'motor_restore');
  assert.equal(disarmAction('plane', { armed: false, motor_cut: true, alt_rel: 80 }), 'motor_restore');
  assert.equal(disarmAction('plane', { armed: false }), 'arm'); assert.equal(disarmAction('copter', null), 'arm');
  assert.ok(isAirborne({ alt_rel: 4 }) && isAirborne({ groundspeed: 8 }) && !isAirborne({ alt_rel: 1, groundspeed: 2 }) && !isAirborne(null));
});
test('metinler: HEPGO Türkçe anahtar, SIMUMAV flt.* anahtarı (yoksa Türkçe)', () => {
  const tx = Object.fromEntries(FLT_TEXTS);
  assert.equal(makeFltT(null)('flt.ev_mode', { m: 'RTL' }), 'Mod isteği: RTL');
  assert.equal(makeFltT(s => `<${s}>`)('flt.cut_banner'), `<${tx['flt.cut_banner']}>`);
  assert.equal(makeFltT(k => (k === 'flt.mode' ? 'Mode' : k), true)('flt.mode'), 'Mode');
  assert.equal(makeFltT(k => k, true)('flt.g_q'), tx['flt.g_q']);
});

console.log(`\n${n} test geçti`);
