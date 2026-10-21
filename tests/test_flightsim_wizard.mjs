// Uçuş Simülatörü — adım adım sihirbaz mantığı (static/js/modules/flightsim_wizard.js) ve görsel sayı girişi yardımcıları
// (static/js/modules/fs_inputs.js) tarayıcısız birim testi. Çalıştırma: node tests/test_flightsim_wizard.mjs
import assert from 'node:assert/strict';
import { STEP_DEFS, LAUNCH_OPTIONS, LAUNCH_PARAM_DEFS, launchOptionsFor, normLaunchMethod, wizardSteps, canGoto, firstInvalid, reconcileStep, createStepper,
  isSimLog, simLogsOnly, simulateParam, wizardStartStep, simulateHref } from '../static/js/modules/flightsim_wizard.js';
import { LAUNCH_METHODS, LAUNCH_DEFAULTS } from '../static/js/modules/flightsim_launch.js';
import { parseNum, clampNum, decimalsOf, snapStep, niceRound, makeScale, fmtNum, valueFromPos, commitValue } from '../static/js/modules/fs_inputs.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

test('adım sırası (canlı): kopterde kalkış adımı yok; sabit kanatta Dünya ile Güç arasında', () => {
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'multirotor' }), ['vehicle', 'world', 'power', 'camera', 'targets', 'site', 'summary']);
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'sabit_kanat' }), ['vehicle', 'world', 'launch', 'power', 'camera', 'targets', 'site', 'summary']);
  for (const t of ['hexarotor', 'helikopter', 'vtol']) assert.ok(!wizardSteps({ mode: 'sitl', type: t }).includes('launch'), t);
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'interceptor' }), ['vehicle', 'world', 'launch', 'power', 'camera', 'targets', 'site', 'summary']);   // §27 fırlatıcılar
});
test('adım sırası (kayıttan oynat): log → (kalkış) → dünya → kamera → özet; güç/hedef/yer kontrol yok', () => {
  assert.deepEqual(wizardSteps({ mode: 'replay', type: 'multirotor' }), ['log', 'world', 'camera', 'summary']);
  assert.deepEqual(wizardSteps({ mode: 'replay', type: 'sabit_kanat' }), ['log', 'world', 'launch', 'camera', 'summary']);
});
test('kalkış seçenekleri veriden: LAUNCH_METHODS ile birebir; yeni seçenek eklenince adım o tipte açılır', () => {
  assert.deepEqual(LAUNCH_OPTIONS.map(o => o.key), LAUNCH_METHODS.map(([k]) => k));
  assert.ok(LAUNCH_OPTIONS.every(o => o.name && o.desc && o.params.every(p => LAUNCH_PARAM_DEFS[p])));
  assert.deepEqual(launchOptionsFor('interceptor').map(o => o.key), ['pod4', 'pod8', 'tube', 'handheld']);   // §27 kullanıcının sırası
  assert.equal(launchOptionsFor('vtol').length, 0);
  const ext = [...LAUNCH_OPTIONS, { key: 'rack4', types: ['vtol'], name: '4\'lü raf', desc: 'x', params: [] }];
  assert.deepEqual(launchOptionsFor('vtol', ext).map(o => o.key), ['rack4']);
  assert.ok(wizardSteps({ mode: 'sitl', type: 'vtol', options: ext }).includes('launch'));
  assert.equal(normLaunchMethod('wheels', 'vtol', ext), 'rack4');
  assert.equal(normLaunchMethod('wheels', 'interceptor'), 'pod4');
  assert.equal(normLaunchMethod('handheld', 'interceptor'), 'handheld');
  assert.equal(normLaunchMethod('handheld', 'sabit_kanat'), 'wheels');
  assert.equal(normLaunchMethod('ramp', 'sabit_kanat'), 'ramp');
  assert.equal(normLaunchMethod('wheels', 'multirotor'), 'wheels');   // seçenek yok: dokunulmaz (gövde aynı kalır)
  assert.equal(LAUNCH_DEFAULTS.angle_deg >= LAUNCH_PARAM_DEFS.angle_deg.min && LAUNCH_DEFAULTS.angle_deg <= LAUNCH_PARAM_DEFS.angle_deg.max, true);
});
test('her adımın başlığı/açıklaması var; isteğe bağlı adımlar işaretli', () => {
  assert.ok(STEP_DEFS.every(s => s.title && s.desc && s.modes.length));
  assert.deepEqual(STEP_DEFS.filter(s => s.optional).map(s => s.key), ['targets', 'site']);
});
test('canGoto: geri serbest; ileri ancak aradaki adımlar geçerliyse', () => {
  const steps = ['vehicle', 'world', 'power', 'summary'];
  const bad = new Set(['world']);
  const valid = k => (bad.has(k) ? 'eksik' : null);
  assert.equal(canGoto(steps, valid, 'power', 'vehicle'), true);
  assert.equal(canGoto(steps, valid, 'vehicle', 'world'), true);   // hedefin kendisi geçersiz olabilir
  assert.equal(canGoto(steps, valid, 'vehicle', 'power'), false);
  assert.equal(canGoto(steps, valid, 'vehicle', 'yok'), false);
  assert.equal(firstInvalid(steps, valid), 'world');
  bad.clear();
  assert.equal(canGoto(steps, valid, 'vehicle', 'summary'), true);
  assert.equal(firstInvalid(steps, valid), null);
});
test('reconcileStep: tip değişince kaybolan adım → önceki en yakın görünür adım', () => {
  const a = wizardSteps({ type: 'sabit_kanat' }), b = wizardSteps({ type: 'multirotor' });
  assert.equal(reconcileStep(a, b, 'launch'), 'world');
  assert.equal(reconcileStep(a, b, 'power'), 'power');
  assert.equal(reconcileStep(['vehicle'], ['log', 'world'], 'vehicle'), 'log');
});
test('createStepper: İleri doğrulamaya bağlı, Geri/İleri, tip değişiminde adım uzlaşması, şerit durumları', () => {
  let type = 'sabit_kanat', center = null;
  const W = createStepper({ getSteps: () => wizardSteps({ mode: 'sitl', type }), valid: k => (k === 'world' && center == null ? 'Bir merkez seçin' : null) });
  assert.equal(W.step, 'vehicle'); assert.ok(W.isFirst());
  assert.ok(W.next()); assert.equal(W.step, 'world');
  assert.equal(W.canNext(), false); assert.equal(W.error(), 'Bir merkez seçin'); assert.equal(W.next(), false);
  assert.equal(W.goto('summary'), false);
  center = 1;
  assert.ok(W.next()); assert.equal(W.step, 'launch');
  type = 'multirotor';
  assert.equal(W.step, 'launch');   // getter kendisi uzlaştırmaz…
  assert.deepEqual(W.steps, wizardSteps({ type: 'multirotor' }));   // …liste okununca uzlaşır
  assert.equal(W.step, 'world');
  assert.ok(W.goto('summary')); assert.ok(W.isLast()); assert.equal(W.canNext(), false);
  const st = W.states();
  assert.equal(st.find(s => s.on).key, 'summary');
  assert.ok(st.filter(s => s.key !== 'summary').every(s => s.done && !s.err && s.reach));
  center = null;
  const st2 = W.states();
  assert.ok(st2.find(s => s.key === 'world').err);
  assert.ok(W.back()); assert.equal(W.step, 'site');
  assert.ok(W.goto('vehicle')); assert.equal(W.back(), false);
  assert.ok(W.goto('summary', { force: true }));
});

// ---------- fs_inputs ----------
test('parseNum: virgül, boşluk, geçersiz', () => {
  assert.equal(parseNum('1,5'), 1.5); assert.equal(parseNum(' 10 000 '), 10000); assert.equal(parseNum('-3'), -3); assert.equal(parseNum('.5'), 0.5);
  assert.equal(parseNum(''), null); assert.equal(parseNum('abc'), null); assert.equal(parseNum('1.2.3'), null); assert.equal(parseNum(NaN), null); assert.equal(parseNum(7), 7);
});
test('decimalsOf / snapStep / clampNum', () => {
  assert.equal(decimalsOf(1), 0); assert.equal(decimalsOf(0.05), 2); assert.equal(decimalsOf(0.5), 1); assert.equal(decimalsOf(1e-7), 7);
  assert.equal(snapStep(0.3333, 0.05), 0.35); assert.equal(snapStep(17, 5, 40), 15); assert.equal(snapStep(43, 5, 40), 45); assert.equal(snapStep(0.1 + 0.2, 0.1), 0.3);
  assert.equal(clampNum(5, 10, 30), 10); assert.equal(clampNum(50, 10, 30), 30);
});
test('niceRound: iki anlamlı basamak', () => {
  assert.equal(niceRound(10347), 10000); assert.equal(niceRound(4472), 4500); assert.equal(niceRound(7.83), 7.8); assert.equal(niceRound(0.0123), 0.012); assert.equal(niceRound(0), 0);
});
test('makeScale: doğrusal ve logaritmik (0 içeren aralık dahil) gidiş-dönüş, uçlar', () => {
  const lin = makeScale({ min: 10, max: 30 });
  assert.equal(lin.toPos(20), 0.5); assert.equal(lin.fromPos(0.25), 15); assert.equal(lin.toPos(99), 1);
  const lg = makeScale({ min: 100, max: 200000, scale: 'log' });
  assert.ok(lg.log); assert.equal(lg.toPos(100), 0); assert.ok(Math.abs(lg.toPos(200000) - 1) < 1e-12);
  for (const v of [150, 1000, 10000, 123456]) assert.ok(Math.abs(lg.fromPos(lg.toPos(v)) - v) / v < 1e-9, String(v));
  assert.ok(lg.toPos(10000) > 0.55 && lg.toPos(10000) < 0.65);   // 10 Ah ortalarda (doğrusalda %5'te kalırdı)
  const z = makeScale({ min: 0, max: 500, scale: 'log' });
  assert.equal(z.toPos(0), 0); assert.ok(Math.abs(z.fromPos(1) - 500) < 1e-9); assert.ok(z.fromPos(0) >= 0 && z.fromPos(0) < 1e-9);
  assert.ok(z.toPos(5) > 0.25 && z.toPos(5) < 0.5);   // 5 L kaydırıcının ilk yarısında, ama dibe yapışmaz
});
test('valueFromPos / commitValue: sınır + adım (eski <input type=number> doğrulamasıyla aynı sınırlar)', () => {
  assert.equal(valueFromPos(0, { min: 100, max: 200000, step: 100, scale: 'log' }), 100);
  assert.equal(valueFromPos(1, { min: 100, max: 200000, step: 100, scale: 'log' }), 200000);
  const mid = valueFromPos(0.6, { min: 100, max: 200000, step: 100, scale: 'log' });
  assert.equal(mid % 100, 0); assert.ok(mid > 5000 && mid < 20000);
  assert.equal(valueFromPos(0.5, { min: 40, max: 110, step: 5 }), 75);
  assert.equal(valueFromPos(0.123, { min: 0, max: 500, step: 0.1, scale: 'log' }) >= 0, true);
  assert.equal(commitValue('2,5', { min: 0, max: 500, step: 0.1 }), 2.5);
  assert.equal(commitValue('9999', { min: 0, max: 500, step: 0.1 }), 500);
  assert.equal(commitValue('-5', { min: 1, max: 16, step: 1, integer: true }), 1);
  assert.equal(commitValue('4.6', { min: 1, max: 16, step: 1, integer: true }), 5);
  assert.equal(commitValue('x', { min: 1, max: 16 }), null);
  assert.equal(commitValue('12.345', { min: 0, max: 100, step: 1 }), 12.35);   // serbest yazım: 2 basamağa kadar korunur (eski kutu adım zorlamıyordu)
});
test('fmtNum', () => {
  assert.equal(fmtNum(12.5, 0.5), '12.5'); assert.equal(fmtNum(12, 0.5), '12'); assert.equal(fmtNum(0.30000000000000004, 0.05), '0.3'); assert.equal(fmtNum(null), ''); assert.equal(fmtNum(1500, 25), '1500');
});

test('§8.5 simülatör log listesi: yalnız simülatör kayıtları — saha görevi/uçuşu logları ve bağımsız gerçek loglar dışarıda', () => {
  const L = [
    { id: 1, origin: 'SIM', file_name: 'SIM-3-20261021-1000.bin' },
    { id: 2, origin: 'REAL', file_name: '00000012.BIN' },                        // Araçlar'dan bağımsız gerçek log
    { id: 3, origin: 'REAL', task_id: 7, task_code: 'SG-1', file_name: 'a.bin' },  // saha görevi
    { id: 4, origin: 'SIM', task_id: 7, flight_id: 9, file_name: 'b.bin' },        // saha uçuşuna bağlı (kaynak SIM olsa da)
    { id: 5, origin: null, aircraft: 'Simülatör · Multikopter', file_name: 'x.bin' },   // eski satır: ad çıkarımı
    { id: 6, origin: null, file_name: 'SIM-12-20261001-0930.bin' },
    { id: 7, origin: null, file_name: 'y.bin', aircraft: 'CZ-07' },
    { id: 8, sim: true, origin: 'REAL', file_name: 'z.bin' },                       // sunucu bayrağı önceliklidir (.bin'i bir simülasyon kaydının)
    { id: 9, sim: false, origin: 'SIM', file_name: 'w.bin' },
  ];
  assert.deepEqual(simLogsOnly(L).map(l => l.id), [1, 5, 6, 8]);
  assert.equal(isSimLog(null), false);
  assert.deepEqual(simLogsOnly(null), []);
});
test('§8.5 "Simüle et" girişi: ?simulate=<log> ayrıştırma, bağlantı, başlangıç adımı (Dünya)', () => {
  assert.equal(simulateParam('42'), 42); assert.equal(simulateParam(7), 7);
  for (const v of [null, undefined, '', '0', '-3', '1.5', 'abc']) assert.equal(simulateParam(v), null, String(v));
  assert.equal(simulateHref(42), '#/drone/sim?simulate=42');
  assert.equal(wizardStartStep({ mode: 'replay', pinned: true }), 'world');
  assert.equal(wizardStartStep({ mode: 'replay', pinned: false }), null);
  assert.equal(wizardStartStep({ mode: 'sitl', pinned: true }), null);
  assert.ok(wizardSteps({ mode: 'replay', type: 'sabit_kanat' }).includes(wizardStartStep({ mode: 'replay', pinned: true })));   // atmosfer → rampa → kamera → özet sorulur
  assert.deepEqual(wizardSteps({ mode: 'replay', type: 'sabit_kanat' }).slice(1), ['world', 'launch', 'camera', 'summary']);
});

console.log(`\n${n} test geçti`);
