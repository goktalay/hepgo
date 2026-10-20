// Uçuş Simülatörü §24 hedefler — saf modül testleri (tarayıcısız): static/js/modules/flightsim_targets.js
// • targetState: sunucu app/flightsim_targets.durum ile AYNI sayılar (vektörler Python'dan üretildi; cw/ccw, faz, ofset, yatış)
// • createInterceptTracker/scoreOf: sunucu HedefIzleyici/puan eşleniği (ARM şartı, histerezis, ilk önleme süresi, rozetler)
// • validateTargets sınırları, newTarget varsayılanı, targetsRelative (kerteriz/göreli yön), drawRadar menzil seçimi
// Çalıştırma: node tests/test_flightsim_targets.mjs
import assert from 'node:assert/strict';
import { targetState, targetsRelative, createInterceptTracker, scoreOf, validateTargets, newTarget, drawRadar, TARGET_MAX, RADIUS_DEFAULT } from '../static/js/modules/flightsim_targets.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, eps = 1e-5, msg) => assert.ok(Math.abs(a - b) <= eps, msg || `${a} ≈ ${b}`);

const H = [{ diameter_m: 600, speed_ms: 30, dir: 'cw', phase_deg: 0, east_m: 100, north_m: -50, alt_m: 150 },
  { diameter_m: 250, speed_ms: 12.5, dir: 'ccw', phase_deg: 137.5, east_m: -300, north_m: 40, alt_m: 60 }];
// [t, x, y, heading, roll] — app.flightsim_targets.durum çıktısı
const PY = [[0, 400.0, -50.0, 180.0, 0.296874402], [7.3, 323.552321, -250.060891, 221.825919, 0.296874402], [123.4, 392.34622, 17.332666, 167.029919, 0.296874402],
  [1000.25, 362.41217, 95.395505, 151.010346, 0.296874402], [0, -392.159667, 124.448776, 222.5, -0.126780865], [7.3, -424.991349, 41.470583, 180.674081, -0.126780865],
  [123.4, -370.854564, 142.978788, 235.470081, -0.126780865], [1000.25, -339.684486, 158.533293, 251.489654, -0.126780865]];

console.log('flightsim_targets.js');
test('targetState sunucu durum() ile aynı (8 vektör: cw/ccw, faz, ofset, uzun süre)', () => {
  PY.forEach(([t, x, y, hd, roll], k) => {
    const s = targetState(H[k < 4 ? 0 : 1], t);
    near(s.x, x, 1e-5, `x ${k}`); near(s.y, y, 1e-5, `y ${k}`); near(s.heading, hd, 1e-5, `hdg ${k}`); near(s.roll, roll, 1e-8, `roll ${k}`);
    assert.equal(s.z, H[k < 4 ? 0 : 1].alt_m);
  });
});
test('yörünge: yarıçap sabit, hız vektörü teğet ve büyüklüğü v; yön hız vektöründen', () => {
  for (const t of [0, 3, 55.5]) {
    const s = targetState(H[0], t);
    near(Math.hypot(s.x - 100, s.y + 50), 300, 1e-9); near(Math.hypot(s.vx, s.vy), 30, 1e-9);
    near((s.x - 100) * s.vx + (s.y + 50) * s.vy, 0, 1e-6, 'teğet');
  }
});
test('önleme izleyicisi = sunucu HedefIzleyici (ARM t=10, t=30 5 m → ilk önleme 20 sn; histerezis; disarm sayılmaz; skor 1050)', () => {
  const cfg = { radius_m: 20, items: [{ i: 0, name: 'Switchblade 300 #1', model: 'tgt:sw300', alt_m: 100, diameter_m: 400, speed_ms: 20, dir: 'cw', east_m: 0, north_m: 0, phase_deg: 0 }] };
  const tr = createInterceptTracker(cfg), h = cfg.items[0];
  assert.deepEqual(tr.step(10, 0, 0, 0, true), []);
  let s = targetState(h, 30);
  assert.deepEqual(tr.step(30, s.x + 5, s.y, s.z, true), [{ i: 0, name: 'Switchblade 300 #1', model: 'tgt:sw300', dist_m: 5, n: 1, first: true, after_s: 20 }]);
  s = targetState(h, 31); assert.deepEqual(tr.step(31, s.x + 25, s.y, s.z, true), [], 'histerezis içinde');
  s = targetState(h, 32); assert.deepEqual(tr.step(32, s.x + 40, s.y, s.z, true), []);
  s = targetState(h, 33); assert.equal(tr.step(33, s.x, s.y, s.z + 3, true)[0].n, 2);
  s = targetState(h, 40); tr.step(39, 0, 0, 0, true); assert.deepEqual(tr.step(40, s.x, s.y, s.z, false), [], 'disarm');
  const o = tr.summary();
  assert.equal(o.total, 2); assert.equal(o.items[0].first_s, 20); assert.equal(o.items[0].min_dist_m, 0); assert.equal(o.score, 1000 - 100 + 100 + 150);
  assert.deepEqual(o.badges, ['first', 'quick', 'close']);
});
test('scoreOf = sunucu puan() (ace/hunter, taban 200)', () => {
  assert.deepEqual(scoreOf({ items: [{ intercepts: 1, first_s: 300, min_dist_m: 9 }, { intercepts: 3, first_s: 10, min_dist_m: 2 }], all_hit: true, count: 2, total: 5 }),
    { score: 200 + 950 + 200 + 150, badges: ['first', 'quick', 'ace', 'close', 'hunter'] });
  assert.deepEqual(scoreOf({ items: [{ intercepts: 0, first_s: null, min_dist_m: 50 }], all_hit: false, count: 1, total: 0 }), { score: 0, badges: [] });
});
test('validateTargets: sınırlar (≤ 8, çap 50–5000, irtifa 10–3000, hız ≤ model azami, ofset ±20 km)', () => {
  const cat = [{ key: 'tgt:lancet', max_ms: 83.33, cruise_ms: 30.56 }];
  const ok = { model: 'tgt:lancet', alt_m: 100, diameter_m: 300, speed_ms: 30, east_m: 0, north_m: 0 };
  assert.equal(validateTargets([ok], cat), null);
  for (const bad of [{ model: 'yok' }, { alt_m: 9 }, { alt_m: 3001 }, { diameter_m: 49 }, { diameter_m: 5001 }, { speed_ms: 84 }, { speed_ms: 0 }, { east_m: 20001 }])
    assert.ok(validateTargets([{ ...ok, ...bad }], cat), JSON.stringify(bad));
  assert.ok(validateTargets(Array(TARGET_MAX + 1).fill(ok), cat)); assert.ok(validateTargets('x', cat));
});
test('newTarget: modelin seyir hızı, sırayla cw/ccw, faz dağıtımı; RADIUS_DEFAULT 25', () => {
  const t = newTarget({ key: 'tgt:octopus', cruise_ms: 55.56 }, 1);
  assert.deepEqual(t, { model: 'tgt:octopus', alt_m: 120, diameter_m: 800, speed_ms: 55.56, dir: 'ccw', east_m: 0, north_m: 0, phase_deg: 138 });
  assert.equal(RADIUS_DEFAULT, 25);
});
test('targetsRelative: kerteriz ve burna göre yön (+ sağ), yarıçap içi', () => {
  const h = { i: 0, name: 'A', diameter_m: 200, speed_ms: 10, dir: 'cw', phase_deg: 90, east_m: 0, north_m: 0, alt_m: 50 };   // t=0: (0, 100)
  const [r] = targetsRelative([h], 0, 0, 0, 50, 90, 25);
  near(r.bearing, 0, 1e-9); near(r.rel, -90, 1e-9); near(r.dist, 100, 1e-9); assert.equal(r.inside, false);
  const [r2] = targetsRelative([h], 0, 0, 90, 45, 0, 25); assert.equal(r2.inside, true);
});
test('drawRadar: en uzak hedefe göre menzil basamağı (sahte 2B bağlam)', () => {
  const calls = [];
  const ctx = new Proxy({}, { get: (o, k) => (k in o ? o[k] : (...a) => calls.push([k, ...a])), set: (o, k, v) => { o[k] = v; return true; } });
  assert.equal(drawRadar(ctx, 280, 280, [{ i: 0, rel: 10, horiz: 1800, inside: false }]), 2000);
  assert.equal(drawRadar(ctx, 280, 280, [{ i: 0, rel: 10, horiz: 120, inside: true }]), 250);
  assert.ok(calls.some(c => c[0] === 'arc'));
});
console.log(`${n} test geçti`);
