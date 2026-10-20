// Uçuş Simülatörü §27 — INTERCEPTOR fırlatıcıları saf mantığı (static/js/modules/flightsim_launcher.js): fırlatma yönelimi (nişan vektörü, nişan noktası
// — Python app/flightsim_launcher.aim_noktasi ile birebir vektörler), hücre envanteri (durumlar, görevde kutu sayısı, raf), nişangâh izdüşümü
// (scopeView + flightsim_tgthud.projectView), nişan adımı/sürükleme. Çalıştırma: node tests/test_flightsim_launcher.mjs
import assert from 'node:assert/strict';
import { AIM_LIMITS, ICEPT_METHODS, aimAt, aimDrag, aimStep, aimVector, aimWaypoint, azTicks, bankLayout, cellCount, cellLayout, cellStates, isIceptLauncher,
  launcherCount, launcherInventory, normAim, rackCountFor, scopeFov, scopeView } from '../static/js/modules/flightsim_launcher.js';
import { projectView, symbology } from '../static/js/modules/flightsim_tgthud.js';
import { LAUNCH_METHODS, ICEPT_LAUNCH, launchLabel, launchHud, replayLaunchTimeline, replayLaunchPhaseAt } from '../static/js/modules/flightsim_launch.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, e = 1e-6, m = '') => assert.ok(Math.abs(a - b) <= e, `${m} ${a} ≉ ${b}`);

// Python app/flightsim_launcher.aim_noktasi ile aynı vektörler (tests/test_flightsim.py firlatici_testleri de aynısını doğrular)
export const AIM_VECTORS = [
  [0, 10, { east_m: 0, north_m: 492.4, alt_m: 86.82, horiz_m: 492.4 }],
  [90, 30, { east_m: 433.01, north_m: 0, alt_m: 250, horiz_m: 433.01 }],
  [225, 45, { east_m: -247.49, north_m: -247.49, alt_m: 350, horiz_m: 350 }],
  [300, 80, { east_m: -103.92, north_m: 60, alt_m: 350, horiz_m: 120 }],
];

test('yöntemler: LAUNCH_METHODS ↔ flightsim_launcher ↔ flightsim_launch kopyası', () => {
  assert.deepEqual(ICEPT_METHODS, ['pod4', 'pod8', 'tube', 'handheld']);
  assert.deepEqual(ICEPT_LAUNCH, ICEPT_METHODS);
  for (const m of ICEPT_METHODS) assert.ok(LAUNCH_METHODS.some(([k]) => k === m), m);
  assert.ok(!isIceptLauncher('ramp') && !isIceptLauncher('hand') && isIceptLauncher('handheld'));
  assert.deepEqual(ICEPT_METHODS.map(cellCount), [4, 8, 1, 1]);
});
test('nişan normalize: az sarılır, el [10, 85] kırpılır; geçersiz → varsayılan', () => {
  assert.deepEqual(normAim(370, 5), { az: 10, el: AIM_LIMITS.el[0] });
  assert.deepEqual(normAim(-30, 120), { az: 330, el: 85 });
  assert.deepEqual(normAim('x', null), { az: 0, el: 55 });
});
test('fırlatma yönelimi: nişan vektörü birim ve ENU (az 0 kuzey, 90 doğu)', () => {
  const v = aimVector(90, 0); near(v[0], 1); near(v[1], 0); near(v[2], 0);
  const u = aimVector(0, 45); near(u[1], Math.SQRT1_2); near(u[2], Math.SQRT1_2);
  for (const [az, el] of [[17, 33], [250, 70]]) { const w = aimVector(az, el); near(Math.hypot(...w), 1); }
});
test('nişan noktası: Python vektörleriyle birebir; ışın üzerinde (kırpılmadıkça) ve sınırlar', () => {
  for (const [az, el, exp] of AIM_VECTORS) assert.deepEqual(aimWaypoint(az, el), exp, `${az}/${el}`);
  const w = aimWaypoint(90, 30);   // kırpılmamış: irtifa/yatay = tan(el)
  near(w.alt_m / w.horiz_m, Math.tan(30 * Math.PI / 180), 1e-3);
  for (let el = 10; el <= 85; el += 5) { const p = aimWaypoint(123, el); assert.ok(p.alt_m >= 30 && p.alt_m <= 350 && p.horiz_m >= 120, `${el}`); }
});
test('aimAt: noktadan hedefe az/el/menzil', () => {
  const a = aimAt([0, 0, 2], [100, 100, 2 + Math.hypot(100, 100)]);
  near(a.az, 45, 1e-9); near(a.el, 45, 1e-9); near(a.range, Math.hypot(100, 100) * Math.SQRT2, 1e-6);
  near(aimAt([0, 0, 0], [-10, 0, 0]).az, 270, 1e-9);
});
test('nişan adımı (klavye/sanal kumanda) ve sürükleme', () => {
  const a = aimStep({ az: 350, el: 50 }, { az: 1, el: -1 }, 0.5);
  near(a.az, 15, 1e-9); near(a.el, 32.5, 1e-9);   // 50°/sn, 35°/sn
  const f = aimStep({ az: 0, el: 50 }, { az: 1, el: 0 }, 1, true); near(f.az, 12.5, 1e-9);   // ince ÷4
  assert.deepEqual(aimStep({ az: 0, el: 84 }, { el: 1 }, 1), { az: 0, el: 85 });
  const d = aimDrag({ az: 10, el: 40 }, 100, -50, 200, 40);   // 0,2°/px
  near(d.az, 30, 1e-9); near(d.el, 50, 1e-9);
});
test('hücre yerleşimi: 4\'lü 2×2, 8\'li 4×2 simetrik; ateşleme sırası arka sıra soldan sağa', () => {
  const c4 = cellLayout('pod4'); assert.equal(c4.length, 4);
  near(c4.reduce((s, c) => s + c.x, 0), 0); near(c4.reduce((s, c) => s + c.y, 0), 0);
  assert.ok(c4[0].x < c4[1].x && c4[0].y > c4[2].y);
  assert.equal(cellLayout('pod8').length, 8); assert.deepEqual(cellLayout('tube'), [{ x: 0, y: 0 }]);
});
test('hücre envanteri: boş / dolu / sıradaki / ateşlenmiş', () => {
  const st = cellStates('pod4', { total: 3, used: 1 });
  assert.deepEqual(st.cells, [['active', 'loaded', 'loaded', 'empty']]);
  assert.deepEqual([st.loaded, st.spent, st.empty], [2, 0, 1]); assert.deepEqual(st.active, { l: 0, c: 0 });
  const g = cellStates('pod8', { total: 12, used: 10 });   // görev: 12 interceptor → 2 kutu; 9 ateşlendi
  assert.equal(g.launchers, 2);
  assert.deepEqual(g.cells[1], ['spent', 'active', 'loaded', 'loaded', 'empty', 'empty', 'empty', 'empty']);
  assert.deepEqual([g.spent, g.loaded, g.empty], [9, 2, 4]); assert.deepEqual(g.active, { l: 1, c: 1 });
  assert.deepEqual(cellStates('tube', { total: 10, used: 4 }).cells, [['spent']]);   // tüp: 1 hücre (raf yedekleri ayrı); taşan sıra
  assert.equal(cellStates('ramp', {}).launchers, 0);
});
test('görev envanteri: kutu sayısı ⌈n / hücre⌉, raf yalnız tüp/el; görevsiz loaded', () => {
  assert.equal(launcherCount('pod4', 10), 3); assert.equal(launcherCount('pod8', 8), 1); assert.equal(launcherCount('pod8', 20), 3); assert.equal(launcherCount('tube', 10), 1);
  assert.equal(rackCountFor('pod4', 10), 0); assert.equal(rackCountFor('tube', 10), 10); assert.equal(rackCountFor('handheld', 7), 7); assert.equal(rackCountFor('pod8', 0), 0);
  assert.deepEqual(launcherInventory({ method: 'pod4', loaded: 2 }), { total: 2, used: 1, launchers: 1, defend: false });
  assert.deepEqual(launcherInventory({ method: 'pod8' }), { total: 8, used: 1, launchers: 1, defend: false });
  assert.deepEqual(launcherInventory({ method: 'pod4', loaded: 2 }, { config: { interceptors: 10 }, state: { icept: { used: 5 } } }), { total: 10, used: 5, launchers: 3, defend: true });
  assert.equal(launcherInventory({ method: 'ramp' }), null);
  const b = bankLayout('pod4', 3); near(b[0].x + b[2].x, 0); assert.ok(b[1].x === 0);   // sıra merkezi = ev noktası
});
test('nişangâh izdüşümü: nişan doğrultusundaki hedef merkezde; sağdaki sağda, yukarıdaki yukarıda', () => {
  const pos = [5, -3, 2], v = scopeView(pos, 60, 35, scopeFov(1), 1.5);
  const f = aimVector(60, 35), at = d => [pos[0] + f[0] * d, pos[1] + f[1] * d, pos[2] + f[2] * d];
  const c = projectView(v, at(800)); assert.ok(c.front); near(c.sx, 0.5, 1e-9); near(c.sy, 0.5, 1e-9);
  const r = projectView(v, [at(800)[0] + v.right[0] * 50, at(800)[1] + v.right[1] * 50, at(800)[2]]); assert.ok(r.sx > 0.5);
  const u = projectView(v, [at(800)[0], at(800)[1], at(800)[2] + 50]); assert.ok(u.sy < 0.5);
  near(Math.hypot(...v.up), 1); near(v.up[0] * f[0] + v.up[1] * f[1] + v.up[2] * f[2], 0); assert.ok(v.up[2] > 0);
  const back = projectView(v, [pos[0] - f[0] * 100, pos[1] - f[1] * 100, pos[2] - f[2] * 100]); assert.ok(!back.front);
  assert.equal(scopeFov(4), 10); assert.equal(scopeFov(3), 40);
});
test('nişangâh sembolojisi: göğe bakarken hedef kutusu ekranda, arkadaki hedefe ok', () => {
  const pos = [0, 0, 3], v = scopeView(pos, 30, 40, 40, 1.5), f = aimVector(30, 40);
  const box = c => { const o = []; for (let k = 0; k < 8; k++) o.push([c[0] + (k & 1 ? 2 : -2), c[1] + (k & 2 ? 2 : -2), c[2] + (k & 4 ? 1 : -1)]); return o; };
  const t1 = [f[0] * 600, f[1] * 600, 3 + f[2] * 600], t2 = [-300, -400, 150];
  const data = { view: v, sel: { i: null, auto: true }, player: { pos, vel: [0, 0, 0] }, items: [{ i: 0, name: 'A', center: t1, corners: box(t1), vel: [0, 0, 0], dist: 600, dz: t1[2] - 3 }, { i: 1, name: 'B', center: t2, corners: box(t2), vel: [0, 0, 0], dist: 520, dz: 147 }] };
  const sym = symbology(data, 380, 250, {});
  const a = sym.items.find(x => x.i === 0), b = sym.items.find(x => x.i === 1);
  assert.ok(a.on && a.pts && Math.abs(a.x - 190) < 1 && Math.abs(a.y - 125) < 1);
  assert.ok(!b.on && b.arrow);
});
test('azimut şeridi işaretleri: merkezde nişan azimutu, 0/360 sarması', () => {
  const t = azTicks(355, 40, 1.5, 10);
  assert.ok(t.some(x => x.deg === 0) && t.some(x => x.deg === 350));
  const z = t.find(x => x.deg === 0); assert.ok(z.x > 0.5);
  for (const x of t) assert.ok(x.x >= 0 && x.x <= 1);
});
test('etiketler + kayıtta aşamalar (AGL 1,5 m)', () => {
  assert.equal(launchLabel({ method: 'pod4', loaded: 3 }), "4'lü fırlatıcı · 3/4");
  assert.equal(launchLabel({ method: 'handheld', aim_az_deg: 40, aim_el_deg: 30 }), 'El fırlatıcısı 30°/40°');
  assert.equal(launchHud({ method: 'handheld', aim_az_deg: 7, aim_el_deg: 30 }), 'LAUNCH HAND AZ 007 EL 30');
  assert.equal(launchHud({ method: 'pod8' }), 'LAUNCH CELL x8');
  const FI = { t: 0, armed: 1, gs: 2, alt_rel: 3 };
  const fr = [[0, 0, 0, 0], [1, 1, 0, 0], [2, 1, 0, 0.3], [2.5, 1, 0.1, 0.8], [3, 1, 0.1, 1.2], [3.5, 1, 0.2, 1.7], [10, 1, 0, 40]];
  const seg = replayLaunchTimeline(fr, FI, { method: 'tube' })[0];
  assert.deepEqual([seg.arm, seg.launch, seg.release], [1, 2.5, 3.5]);
  assert.equal(replayLaunchPhaseAt([seg], 3), 'launch'); assert.equal(replayLaunchPhaseAt([seg], 4), 'released');
});

console.log(`\n${n} test geçti`);
