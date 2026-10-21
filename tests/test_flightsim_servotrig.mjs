// Uçuş Simülatörü — §34 SERVO TETİK tarayıcısız birim testi (HEPGO + SIMUMAV ortak flightsim_servotrig.js):
//   • saf katman: işlev adları (sunucu flightsim_servotrig.SERVO_ISLEVLERI ile aynı kodlar), kanal etiketi ("9 · RCIN9 / Yük"), koşul metni,
//     ayar kırpma (sunucu sınırları), başlangıç ayarı önceliği (dron başına > sunucu önerisi > genel tercih > varsayılan), anlık PWM (servo16 / servo),
//     rapor metni satırları, harita işaretleri, kayıt rozeti.
//   • metinler: HEPGO Türkçe anahtar / SIMUMAV `srv.*` anahtarı; HEPGO 6 dil + SIMUMAV 7 dil sözlüklerinde karşılık.
// Çalıştırma: node tests/test_flightsim_servotrig.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_CFG, LIMITS, SRV_TEXTS, chanLabel, condText, fnName, isPayloadFn, makeSrvT, normalizeCfg, pickInitial, pwmFor, servoMapPoints, servoReportLines, servoRunBadge, srvActKey, srvBtnKey } from '../static/js/modules/flightsim_servotrig.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

console.log('saf katman');
test('işlev adları sunucuyla aynı (RCIN, Motor, Script, yük işaretleri)', () => {
  assert.equal(fnName(59), 'RCIN9'); assert.equal(fnName(66), 'RCIN16'); assert.equal(fnName(33), 'Motor1'); assert.equal(fnName(85), 'Motor12');
  assert.equal(fnName(94), 'Script1'); assert.equal(fnName(4), 'Aileron'); assert.equal(fnName(999), 'F999'); assert.equal(fnName(null), null);
  assert.ok(isPayloadFn(59) && isPayloadFn(28) && isPayloadFn(27) && !isPayloadFn(4) && !isPayloadFn(33) && !isPayloadFn(null));
  const py = readFileSync(join(ROOT, 'app/flightsim_servotrig.py'), 'utf8');
  for (const [k, v] of [[4, 'Aileron'], [28, 'Gripper'], [27, 'Parachute'], [70, 'Throttle'], [88, 'Winch'], [10, 'CameraTrigger']]) assert.ok(py.includes(`${k}: '${v}'`), `${k} ${v}`);
});
test('kanal etiketi: "9 · RCIN9 / Yük"; işlevsiz yalnız numara', () => {
  assert.equal(chanLabel(9, 59), '9 · RCIN9 / Yük');
  assert.equal(chanLabel(1, 4), '1 · Aileron');
  assert.equal(chanLabel(5, 1), '5 · RCPassThru');
  assert.equal(chanLabel(12, null), '12');
  assert.equal(chanLabel(9, 59, k => (k === 'srv.payload' ? 'Payload' : k)), '9 · RCIN9 / Payload');
});
test('koşul metni ve ayar kırpma (sunucu sınırları)', () => {
  assert.equal(condText({ cmp: 'ge', pwm: 1900 }), '≥ 1900 µs'); assert.equal(condText({ cmp: 'le', pwm: 1100 }), '≤ 1100 µs');
  assert.equal(condText({ cmp: 'eq', pwm: 1500, tol: 30 }), '= 1500 ±30 µs');
  assert.deepEqual(normalizeCfg({ ch: 20, pwm: 5000, cmp: 'x', tol: 0, delay_ms: -5 }), { ch: 16, pwm: 2200, cmp: 'ge', tol: 1, delay_ms: 0 });
  assert.deepEqual(normalizeCfg({ ch: '9', pwm: '1900.4', cmp: 'eq', tol: 'abc', delay_ms: 70000 }), { ch: 9, pwm: 1900, cmp: 'eq', tol: DEFAULT_CFG.tol, delay_ms: 60000 });
  assert.deepEqual(LIMITS, { pwm: [800, 2200], delay_ms: [0, 60000], tol: [1, 500] });
});
test('başlangıç ayarı: dron başına > sunucu önerisi > genel > varsayılan', () => {
  const g = { ch: 3, pwm: 1200, cmp: 'le', tol: 50, delay_ms: 0 }, s = { ch: 10, pwm: 2000, cmp: 'ge', tol: 50, delay_ms: 2500 }, d = { ch: 11, pwm: 1800, cmp: 'eq', tol: 40, delay_ms: 100 };
  assert.deepEqual(pickInitial({ stored: g, suggest: s, byDrone: { 7: d }, droneId: 7 }), d);
  assert.deepEqual(pickInitial({ stored: g, suggest: s, byDrone: { 7: d }, droneId: 8 }), s);
  assert.deepEqual(pickInitial({ stored: g }), g);
  assert.deepEqual(pickInitial(), DEFAULT_CFG);
});
test('anlık PWM: servo16 (9–16) → servo (1–8) yedeği; 0/65535 yok', () => {
  assert.equal(pwmFor({ servo16: [1500, 0, 0, 0, 0, 0, 0, 0, 1900] }, 9), 1900);
  assert.equal(pwmFor({ servo: [1100, 1200] }, 2), 1200);
  assert.equal(pwmFor({ servo: [1100] }, 9), null);
  assert.equal(pwmFor({ servo16: Array(16).fill(65535) }, 4), null);
  assert.equal(pwmFor(null, 1), null);
});
const SUM = { servo_trigger: { ch: 9, fn_name: 'RCIN9', pwm: 1900, cmp: 'ge', tol: 50, delay_ms: 1500, seen_pwm: 1900,
  trigger: { lat: 39.926, lon: 32.837, agl: 80, alt_msl: 980, dist_home_m: 111.2 }, hit: { lat: 39.927, lon: 32.837, agl: 62.5, alt_msl: 975, dist_home_m: 222.3, delay_sim_ms: 1500 } } };
test('rapor metni, harita işaretleri, kayıt rozeti', () => {
  const L = servoReportLines(SUM);
  assert.equal(L[0], 'Servo tetik: S9 (RCIN9) ≥ 1900 µs · gecikme 1500 ms');
  assert.ok(L[1].startsWith('Tetik anı: AGL 80.0 m · MSL 980.0 m · evden 111 m') && L[2].startsWith('Çarpma anı: AGL 62.5 m'), L);
  assert.deepEqual(servoReportLines({}), []);
  assert.deepEqual(servoReportLines({ servo_trigger: { ...SUM.servo_trigger, trigger: null, hit: null } }).slice(1), ['Tetik gelmedi (dinleme sürdü)']);
  assert.deepEqual(servoMapPoints(SUM), [{ lat: 39.926, lon: 32.837, kind: 'trigger' }, { lat: 39.927, lon: 32.837, kind: 'hit' }]);
  assert.deepEqual(servoMapPoints({ servo_trigger: { trigger: { lat: null } } }), []);
  const b = servoRunBadge({ servo_trig: { ch: 9, trig_agl: 80.4, trig_dist_m: 111.2, delay_ms: 1500 } });
  assert.equal(b.text, '⚡ S9 · 80 m'); assert.ok(b.title.includes('80.4') && b.title.includes('111') && b.title.includes('1500'));
  assert.equal(servoRunBadge({}), null);
});

console.log('metinler ve sözlükler');
test('HEPGO Türkçe anahtar, SIMUMAV srv.* (yoksa Türkçe)', () => {
  const tx = Object.fromEntries(SRV_TEXTS);
  assert.equal(makeSrvT(null)('srv.ev_on', { c: 'S9' }), 'Servo tetik dinleniyor: S9');
  assert.equal(makeSrvT(s => `<${s}>`)('srv.listen'), `<${tx['srv.listen']}>`);
  assert.equal(makeSrvT(k => (k === 'srv.listen' ? 'Listen' : k), true)('srv.listen'), 'Listen');
  assert.equal(makeSrvT(k => k, true)('srv.stop'), tx['srv.stop']);
});
const REPORT = ['Servo tetik', 'gecikme', 'Tetik anı', 'evden', 'Çarpma anı', 'Tetik gelmedi (dinleme sürdü)', 'İrtifa (AGL)', 'İrtifa (MSL)', 'Evden yatay mesafe',
  'Tetik irtifası (AGL)', 'Çarpma irtifası (AGL)', 'Tetik anı (komutun geldiği an)', 'Koşul / görülen PWM', '{k} · {v} m/s · simülasyon bitiriliyor, özet raporu açılacak',
  'Servo tetik çarpması — simülasyon bitti', 'Servo tetik S{ch} · tetik AGL {a} m · evden {d} m · gecikme {ms} ms'];
test('HEPGO 6 dil: servo tetik metinleri', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const need = [...SRV_TEXTS.map(([, v]) => v), ...REPORT];
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = need.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: srv.* anahtarları + rapor metinleri', () => {
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = [...SRV_TEXTS.map(([k]) => k), ...REPORT, 'Servo tetik çarpması — uçuş bitti'].filter(k => !(k in d));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
    if (l !== 'tr') assert.notEqual(d['srv.listen'], 'Dinle', l);
  }
});

test('alt bant: tek düğme metni aşamaya göre (Dinle → Dinleniyor → Tetiklendi → ÇARPMA); panel eylemi başla / durdur', () => {
  const tx = Object.fromEntries(SRV_TEXTS);
  assert.equal(tx[srvBtnKey('idle')], 'Dinle'); assert.equal(tx[srvBtnKey('listening')], 'Dinleniyor');
  assert.equal(tx[srvBtnKey('pending')], 'Tetiklendi'); assert.equal(tx[srvBtnKey('fired')], 'ÇARPMA');
  assert.equal(tx[srvActKey('idle')], 'Dinlemeye başla'); assert.equal(tx[srvActKey('listening')], 'Dinlemeyi durdur'); assert.equal(tx[srvActKey('pending')], 'Dinlemeyi durdur');
  const src = readFileSync(join(ROOT, 'static/js/modules/flightsim_servotrig.js'), 'utf8');
  assert.ok(/fs-srv-pop/.test(src) && /if \(on\) setOpen\(false\)/.test(src), 'dinleme başlayınca panel kapanır');
  assert.ok(/key === 'Escape' && !pop\.hidden/.test(src) && /root\.contains\(e\.target\)/.test(src), 'Esc / dışarı tıklama kapatır');
});

console.log(`\n${n} test geçti`);
