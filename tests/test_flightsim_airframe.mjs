// Uçuş Simülatörü — kontrol düzeni saf katmanı (static/js/modules/flightsim_airframe.js, §13.1) tarayıcısız birim testi.
// Çalıştırma: node tests/test_flightsim_airframe.mjs
import assert from 'node:assert/strict';
import { LAYOUTS, LAYOUT_KEYS, LAYOUT_PARAMS, LAYOUT_SITL_MODEL, CTRL_RE, FN, layoutForModel, logicalOutputs, controlInputs, surfaceTarget, easeSurface, layoutLabel, layoutShort, nrm } from '../static/js/modules/flightsim_airframe.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, eps = 1e-9, msg) => assert.ok(Math.abs(a - b) <= eps, msg || `${a} ≈ ${b}`);
const pwm = x => 1500 + 400 * x;   // ±1 → µs

test('düzen listesi ve etiketler: classic / elevon / vtail; SITL modelleri; parametre setleri ArduPilot autotest ile aynı', () => {
  assert.deepEqual(LAYOUT_KEYS, ['classic', 'elevon', 'vtail']); assert.equal(LAYOUTS.length, 3);
  assert.equal(LAYOUT_SITL_MODEL.vtail, 'plane-vtail'); assert.equal(LAYOUT_SITL_MODEL.elevon, 'plane-elevon'); assert.equal(LAYOUT_SITL_MODEL.classic, 'plane');
  assert.deepEqual([LAYOUT_PARAMS.vtail.SERVO2_FUNCTION, LAYOUT_PARAMS.vtail.SERVO4_FUNCTION, LAYOUT_PARAMS.vtail.SERVO2_REVERSED], [80, 79, 1], 'plane-vtail.parm');
  assert.deepEqual([LAYOUT_PARAMS.elevon.SERVO1_FUNCTION, LAYOUT_PARAMS.elevon.SERVO2_FUNCTION, LAYOUT_PARAMS.elevon.SERVO1_REVERSED, LAYOUT_PARAMS.elevon.SERVO2_REVERSED], [78, 77, 1, 1], 'plane-elevons.parm');
  assert.deepEqual([LAYOUT_PARAMS.classic.SERVO1_FUNCTION, LAYOUT_PARAMS.classic.SERVO2_FUNCTION, LAYOUT_PARAMS.classic.SERVO4_FUNCTION], [4, 19, 21]);
  assert.equal(layoutLabel('vtail'), 'V-kuyruk (ruddervator)'); assert.equal(layoutShort('elevon'), 'Elevon'); assert.equal(layoutLabel(null), '—');
  assert.equal(layoutLabel('vtail', s => `[${s}]`), '[V-kuyruk (ruddervator)]');
});
test('CTRL_RE: ruddervator_l/r tanınır (yan: l/r/left/right), aileron/elevon/flap/elevator/rudder korunur', () => {
  for (const [name, surf, side] of [['ruddervator_l', 'ruddervator', 'l'], ['ruddervator_right', 'ruddervator', 'right'], ['aileron_r', 'aileron', 'r'], ['elevon_l', 'elevon', 'l'], ['elevator', 'elevator', undefined], ['rudder', 'rudder', undefined], ['Flap_L', 'Flap', 'L']]) {
    const m = CTRL_RE.exec(name); assert.ok(m, name); assert.equal(m[1], surf); assert.equal(m[2], side);
  }
  assert.equal(CTRL_RE.exec('propeller'), null); assert.equal(CTRL_RE.exec('base_link'), null); assert.equal(CTRL_RE.exec('ruddervator_l_v0'), null, 'alt mesh düğümü eşleşmez');
});
test('layoutForModel: model.layout önce; yoksa yüzey düğüm adlarından (ruddervator → vtail, elevon → elevon, aileron/elevator → classic); bilinmiyor → null', () => {
  assert.equal(layoutForModel({ id: 'builtin:talon', layout: 'vtail' }), 'vtail');
  assert.equal(layoutForModel({ id: 'builtin:caymaz', layout: 'elevon' }, [{ surface: 'ruddervator' }]), 'elevon', 'model.layout yüzey adlarını ezer');
  assert.equal(layoutForModel({ id: '12' }, [{ surface: 'aileron', side: 'l' }, { surface: 'ruddervator', side: 'r' }]), 'vtail');
  assert.equal(layoutForModel({ id: '12' }, [{ surface: 'elevon' }, { surface: 'flap' }]), 'elevon');
  assert.equal(layoutForModel({ id: '12' }, [{ surface: 'aileron' }, { surface: 'elevator' }, { surface: 'rudder' }]), 'classic');
  assert.equal(layoutForModel({ id: '12' }, [{ surface: 'flap' }]), null); assert.equal(layoutForModel(null), null); assert.equal(layoutForModel({ id: 'x' }, []), null);
});
test('logicalOutputs: ±400 µs → ±1, geçersiz (0 µs) → 0; REVERSED kanal işareti geri çevrilir', () => {
  assert.deepEqual(logicalOutputs([1900, 1100, 0, 1500]), [1, -1, 0, 0]);
  assert.deepEqual(logicalOutputs([1900, 1100, 1700, 1500], [1, 0, 1, 1]), [-1, -1, -0.5, -0]);
  assert.equal(logicalOutputs(null), null); near(nrm(1700), 0.5); near(nrm(2500), 0);
});
test('controlInputs klasik (4/19/21): sağa yatış + burun yukarı + sağa rudder; disarm → nötr; servo yoksa rc', () => {
  const fn = [4, 19, 70, 21, 3, 3, 0, 0];
  const o = controlInputs({ armed: true, servo: [pwm(0.5), pwm(0.25), 1500, pwm(-0.5), 1100, 1100, 0, 0], fn, rev: [0, 0, 0, 0, 0, 0, 0, 0], mode: 'FBWA' });
  assert.equal(o.source, 'servo'); near(o.ail, 0.5); near(o.ele, 0.25); near(o.rud, -0.5); near(o.flap, 0); assert.equal(o.elevonL, null); assert.equal(o.vtailL, null);
  assert.equal(controlInputs({ armed: false, servo: [1900, 1900, 1900, 1900] }).ail, 0, 'disarm nötr');
  const r = controlInputs({ armed: true, servo: null, rc: [pwm(-1), pwm(1), 1500, pwm(0.5)], mode: 'TAKEOFF' });
  assert.equal(r.source, 'rc'); near(r.ail, -1); near(r.ele, 1); near(r.rud, 0.5); near(r.flap, 0.5, 1e-9, 'TAKEOFF %50 flap öykünmesi');
  // montaj: SERVO1_REVERSED 1 (CAYMAZ) → PWM ters, mantıksal aileron komut yönünde
  const m = controlInputs({ armed: true, servo: [pwm(-0.5), pwm(0), 1500, pwm(0), 1100, 1100, 0, 0], fn, rev: [1, 0, 0, 0, 0, 0, 0, 0], mode: 'FBWA' });
  near(m.ail, 0.5, 1e-9, 'REVERSED=1: PWM −0,5 → mantıksal +0,5');
});
test('controlInputs elevon (SERVO1 78 R, SERVO2 77 L, REVERSED 1/1): ArduPlane L = e − a, R = e + a → eksenler geri çözülür', () => {
  const fn = [78, 77, 70, 0, 3, 3, 0, 0], rev = [1, 1, 0, 0, 0, 0, 0, 0];
  const e = 0.4, a = 0.2, L = e - a, R = e + a;   // mantıksal çıkışlar; PWM = −mantıksal (REVERSED)
  const o = controlInputs({ armed: true, servo: [pwm(-R), pwm(-L), 1500, 0, 1100, 1100, 0, 0], fn, rev, mode: 'FBWA' });
  near(o.elevonL, L); near(o.elevonR, R); near(o.ele, e); near(o.ail, a); assert.equal(o.vtailL, null);
  // yüzeyler: elevon L/R doğrudan; ayrı aileron/elevator düğümleri olan modelde eksenlerden
  near(surfaceTarget('elevon', 'l', o), -L * 25); near(surfaceTarget('elevon', 'r', o), -R * 25);
  near(surfaceTarget('aileron', 'l', o), a * 25); near(surfaceTarget('aileron', 'r', o), -a * 25); near(surfaceTarget('elevator', '', o), -e * 25);
});
test('controlInputs V-kuyruk (SERVO1 4, SERVO2 80 R REVERSED, SERVO4 79 L): L = e + r, R = e − r; sağa sapmada sol yukarı sağ aşağı, burun yukarıda ikisi yukarı', () => {
  const fn = [4, 80, 70, 79, 3, 3, 0, 0], rev = [0, 1, 0, 0, 0, 0, 0, 0];
  const run = (e, r, a = 0) => controlInputs({ armed: true, servo: [pwm(a), pwm(-(e - r)), 1500, pwm(e + r), 1100, 1100, 0, 0], fn, rev, mode: 'FBWA' });
  let o = run(0, 0.6);   // sağa sapma
  near(o.vtailL, 0.6); near(o.vtailR, -0.6); near(o.rud, 0.6); near(o.ele, 0);
  assert.ok(surfaceTarget('ruddervator', 'l', o) < 0, 'sol ruddervator arka kenar YUKARI (° aşağı + → negatif)'); assert.ok(surfaceTarget('ruddervator', 'r', o) > 0, 'sağ ruddervator arka kenar AŞAĞI');
  near(surfaceTarget('rudder', '', o), 0.6 * 25, 1e-9, 'rudder düğümlü modelde + = sağa');
  o = run(0.5, 0);      // burun yukarı
  near(o.ele, 0.5); near(o.rud, 0); near(surfaceTarget('ruddervator', 'l', o), -12.5); near(surfaceTarget('ruddervator', 'r', o), -12.5); near(surfaceTarget('elevator', '', o), -12.5);
  o = run(0.5, 0.5, 0.3);   // birleşik: L = 1 (doyma), R = 0; aileron ayrı kanal
  near(o.vtailL, 1); near(o.vtailR, 0); near(o.ail, 0.3); near(surfaceTarget('aileron', 'r', o), -7.5);
  // servo_fn bilinmeden (eski kayıt) ruddervator düğümleri eksenlerden: L = e + r
  const k = controlInputs({ armed: true, servo: null, rc: [1500, pwm(0.2), 1500, pwm(0.4)], mode: 'FBWA' });
  near(surfaceTarget('ruddervator', 'l', k), -(0.2 + 0.4) * 25); near(surfaceTarget('ruddervator', 'r', k), -(0.2 - 0.4) * 25);
});
test('flap: işlevli kanal ortalaması 1100…1900 → 0…1; +35°; işlev bilinmiyor ve dinlenmede → LAND %100', () => {
  const o = controlInputs({ armed: true, servo: [1500, 1500, 1500, 1500, 1500, 1900], fn: [4, 19, 70, 21, 3, 3], mode: 'FBWA' });
  near(o.flap, 0.75); near(surfaceTarget('flap', 'l', o), 0.75 * 35);
  const l = controlInputs({ armed: true, servo: [1500, 1500, 1500, 1500, 1100, 1100], fn: null, mode: 'LAND' }); near(l.flap, 1);
});
test('easeSurface: τ gecikme + 400°/s hız sınırı; hedefe yaklaşır, aşmaz', () => {
  let d = 0; for (let i = 0; i < 100; i++) d = easeSurface(d, 25, 1 / 60); near(d, 25, 1e-6);
  near(easeSurface(0, 25, 0.01), 4, 1e-9, 'hız sınırı 400°/s · 0,01 s = 4°'); near(easeSurface(0, 1, 1), 1); assert.ok(easeSurface(0, -25, 0.02) >= -8 - 1e-9);
  assert.equal(FN.VTAIL_L, 79); assert.equal(FN.ELEVON_R, 78);
});
console.log(`\n${n} test geçti`);
