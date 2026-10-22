// Uçuş Simülatörü §45 — uçuş yığını seçicisinin saf katmanı (static/js/modules/ucus_yigini.js; YALNIZ HEPGO) + PX4 kiplerinin GPWS / uçuş çubuğu
// uyumu. Çalıştırma: node tests/test_ucus_yigini.mjs
import assert from 'node:assert/strict';
import { stackStatus, stackTypeError, airframesFor, stackBody, stackLabel, readParamsText, PX4_SPEEDS } from '../static/js/modules/ucus_yigini.js';
import { LAUNCH_OPTIONS, launchOptionsFor, wizardSteps } from '../static/js/modules/flightsim_wizard.js';
import { disarmAction, modeGroups } from '../static/js/modules/flightsim_fltbar.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

const STACKS = [
  { key: 'ardupilot', name: 'ArduPilot', status: 'active', available: true, types: ['multirotor', 'hexarotor', 'helikopter', 'sabit_kanat', 'vtol', 'interceptor', 'rover'], params_ext: '.parm' },
  { key: 'px4', name: 'PX4', status: 'active', available: true, types: ['multirotor', 'sabit_kanat', 'vtol'], params_ext: '.params',
    airframes: { multirotor: [{ id: 10040, model: 'sihsim_quadx', name: 'SIH Quadcopter X' }], vtol: [{ id: 10043, name: 'SIH Standart VTOL' }, { id: 10042, name: 'SIH Tailsitter' }] } },
  { key: 'inav', name: 'INAV', status: 'planned', types: [], reason: 'X-Plane köprüsü' },
  { key: 'betaflight', name: 'Betaflight', status: 'unsuitable', types: [], reason: 'GPS seyrüseferi yok' },
];

test('durumlar: etkin / planlandı / uygun değil / kurulu değil', () => {
  assert.equal(stackStatus(STACKS[0]), 'active');
  assert.equal(stackStatus(STACKS[2]), 'planned');
  assert.equal(stackStatus(STACKS[3]), 'unsuitable');
  assert.equal(stackStatus({ ...STACKS[1], available: false }), 'missing');
});

test('tip uyumu: PX4 yalnız kopter / sabit kanat / VTOL; ArduPilot her tip', () => {
  assert.equal(stackTypeError('ardupilot', 'rover', STACKS), null);
  assert.equal(stackTypeError('px4', 'multirotor', STACKS), null);
  assert.match(stackTypeError('px4', 'helikopter', STACKS), /desteklemiyor: Helikopter/);
  assert.match(stackTypeError('px4', 'rover', STACKS), /Kara Aracı/);
  assert.match(stackTypeError('inav', 'multirotor', STACKS), /INAV: X-Plane/);
});

test('airframe listesi tipe göre', () => {
  assert.deepEqual(airframesFor(STACKS, 'vtol').map(a => a.id), [10043, 10042]);
  assert.deepEqual(airframesFor(STACKS, 'rover'), []);
  assert.deepEqual(PX4_SPEEDS, [0.5, 1, 2, 4]);
});

test('gövde: ArduPilot dosyasız → alan yok (eski gövdeyle birebir); PX4 airframe/hız; dosya metni', () => {
  assert.deepEqual(stackBody({ stack: 'ardupilot', params: null }), {});
  assert.deepEqual(stackBody({ stack: 'ardupilot', params: { text: 'A 1', name: 'x.parm' } }), { stack: 'ardupilot', stack_cfg: { params_text: 'A 1', params_name: 'x.parm' } });
  assert.deepEqual(stackBody({ stack: 'px4', airframe: 10040, speed: 1, params: null }), { stack: 'px4', stack_cfg: { airframe: 10040 } });
  assert.deepEqual(stackBody({ stack: 'px4', airframe: 10043, speed: 2, params: { text: 'B 2', name: 'v.params' } }),
    { stack: 'px4', stack_cfg: { params_text: 'B 2', params_name: 'v.params', airframe: 10043, speed: 2 } });
});

test('özet etiketi', () => {
  assert.equal(stackLabel({ stack: 'ardupilot' }, STACKS, 'multirotor'), 'ArduPilot');
  assert.equal(stackLabel({ stack: 'px4', airframe: 10042, speed: 2, params: { text: 'x', name: 'a.params', count: 3 } }, STACKS, 'vtol'),
    'PX4 · SIH Tailsitter (10042) · 2× · parametre dosyası a.params (3 satır)');
});

test('parametre dosyası ön denetimi', () => {
  assert.deepEqual(readParamsText('# c\nA 1\n\nB 2 # x\n'), { count: 2 });
  assert.ok(readParamsText('# yalnız yorum\n').error);
  assert.ok(readParamsText('x'.repeat(600 * 1024)).error);
  assert.ok(readParamsText(null).error);
});

test('PX4 kalkış adımı: sabit kanatta yalnız pist (rampa/araç yok), kopter/VTOL adımsız', () => {
  const px4 = LAUNCH_OPTIONS.filter(o => o.key === 'wheels');
  assert.deepEqual(launchOptionsFor('sabit_kanat', px4).map(o => o.key), ['wheels']);
  assert.ok(wizardSteps({ mode: 'sitl', type: 'sabit_kanat', options: px4 }).includes('launch'));
  assert.ok(!wizardSteps({ mode: 'sitl', type: 'vtol', options: px4 }).includes('launch'));
});

test('PX4 oturumu uçuş çubuğu: copter ailesi → havada DISARM onaylı (motor kesme yok), tek kip grubu', () => {
  const t = { armed: true, alt_rel: 40, groundspeed: 15, mode: 'AUTO.LOITER' };
  assert.equal(disarmAction('copter', t), 'confirm_disarm');
  assert.equal(modeGroups('copter', ['POSCTL', 'AUTO.RTL']).length, 1);
});

const gp = await import('../static/js/modules/flightsim_gpws.js');
test('GPWS: PX4 AUTO.LAND / AUTO.RTL iniş kipi sayılır (iniş evresinde yanlış SINK RATE yok)', () => {
  const g = gp.createGpws({ vehicle: 'multirotor' });
  let act = [];
  for (let i = 0; i < 60; i++) {
    const r = g.step(gp.teleInput({ tbm: i * 100, armed: true, mode: 'AUTO.LAND', alt_rel: Math.max(0, 6 - i * 0.1), vd: 1.2, climb: -1.2, groundspeed: 0.3, roll: 0, pitch: 0, home: { lat: 0, lon: 0 }, lat: 0, lon: 0 }));
    act = act.concat(r.active.map(a => a.code));
  }
  assert.ok(!act.includes('SINK_RATE') && !act.includes('PULL_UP'), act.join(','));
});

console.log(`test_ucus_yigini: ${n} test TAMAM`);
