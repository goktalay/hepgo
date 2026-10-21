// Uçuş Simülatörü §40 — Boşluk ile KİLİT + ANGAJMAN tarayıcısız birim testi (flightsim_engage.js saf katmanı + tgthud kilit sembolü):
//   • kilit adayı (HUD TD kutusu ekrandaysa o, değilse boresight'a en yakın görünür; ekranda yoksa null), Boşluk kararı (kumanda açık/kapalı),
//   • görüş dışı sayacı (3 sn → bir kez), burun yönünden açı, ölçüler (mesafe, Vc, ΔH), kayıttan oynatma eşlemesi, rapor satırları,
//   • tgthud: data.eng → kilitli hedefte `engaged` (çift çerçeve + KİLİT), çizim duman testi,
//   • metinler: HEPGO 6 dil + SIMUMAV 7 dil (eng.* + KİLİT); oturumlar modülü bağlar; gamepad 'lock' eylemi.
// Çalıştırma: node tests/test_flightsim_engage.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ENGAGE_LOST_MS, ENGAGE_TEXTS, bearingOff, createLostTimer, engageMetrics, engagementAt, engagementEvents, engagementRows, makeEngT, pickLockCandidate, spaceAction } from '../static/js/modules/flightsim_engage.js';
import { boxCorners, drawSymbology, symbology } from '../static/js/modules/flightsim_tgthud.js';
import { DEFAULT_PAD, PAD_ACTIONS } from '../static/js/modules/flightsim_gamepad.js';
import { scoreOf, ENGAGE_BONUS } from '../static/js/modules/flightsim_targets.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);

// Kamera: orijinde, kuzeye (+y) bakıyor; sağ = doğu (+x), yukarı = +z
const view = { pos: [0, 0, 0], fwd: [0, 1, 0], right: [1, 0, 0], up: [0, 0, 1], tanV: Math.tan(30 * Math.PI / 180), aspect: 16 / 9 };
const item = (i, c, extra = {}) => ({ i, name: `H${i}`, center: c, corners: boxCorners([c[0] - 1, c[1] - 1, c[2] - 0.3], [c[0] + 1, c[1] + 1, c[2] + 0.3]), vel: [0, 0, 0], dist: Math.hypot(...c), dz: c[2], inside: false, flash: false, ...extra });
const W = 1600, H = 900;

console.log('saf katman');
test('aday: HUD kilidi (oto en yakın) ekrandaysa o; değilse boresight’a en yakın görünür; ekranda yoksa null', () => {
  const data = { view, sel: { i: null, auto: true }, player: { pos: [0, 0, 0], vel: [0, 0, 0] }, items: [item(0, [-80, 400, 0]), item(1, [5, 900, 0]), item(2, [0, -300, 0])] };
  // en yakın = 2 (arkada → ekran dışı) → boresight'a en yakın görünür = 1
  let sym = symbology(data, W, H);
  assert.equal(sym.locked.i, 2); assert.equal(sym.locked.on, false);
  assert.equal(pickLockCandidate(sym, W / 2, H / 2), 1);
  // Tab ile 0 seçilmiş ve ekranda → 0
  sym = symbology({ ...data, sel: { i: 0, auto: false } }, W, H);
  assert.equal(pickLockCandidate(sym, W / 2, H / 2), 0);
  // hepsi arkada → null
  sym = symbology({ ...data, items: [item(0, [0, -100, 0]), item(1, [50, -500, 10])] }, W, H);
  assert.equal(pickLockCandidate(sym, W / 2, H / 2), null);
  assert.equal(pickLockCandidate(null, 0, 0), null);
});
test('Boşluk kararı: kilitliyse bırak; aday varsa kilit; yoksa kumanda kapalı → ipucu, açık → eski davranış; hedefsiz → eski', () => {
  assert.equal(spaceAction({ hasTargets: true, engaged: 1, candidate: null, rcOn: true }), 'release');
  assert.equal(spaceAction({ hasTargets: true, engaged: null, candidate: 2, rcOn: true }), 'lock');
  assert.equal(spaceAction({ hasTargets: true, engaged: null, candidate: null, rcOn: false }), 'hint');
  assert.equal(spaceAction({ hasTargets: true, engaged: null, candidate: null, rcOn: true }), null);
  assert.equal(spaceAction({ hasTargets: false, engaged: null, candidate: 1, rcOn: false }), null);
  assert.equal(spaceAction({ hasTargets: true, engaged: 0, candidate: null, rcOn: false }), 'release', 'i = 0 da kilit sayılır');
});
test('görüş dışı sayacı: 3 sn’yi aşınca bir kez; görünürse sıfırlanır', () => {
  assert.equal(ENGAGE_LOST_MS, 3000);
  const L = createLostTimer();
  assert.equal(L.see(0, false), false); assert.equal(L.see(2999, false), false); close(L.left(2000), 1000);
  assert.equal(L.see(3001, false), true); assert.equal(L.see(4000, false), false, 'bir kez');
  assert.equal(L.see(4100, true), false); assert.equal(L.left(4100), null);
  assert.equal(L.see(5000, false), false); assert.equal(L.see(8100, false), true);
});
test('burun yönünden açı (sağ +) ve ölçüler: mesafe, Vc (yaklaşma +), ΔH', () => {
  close(bearingOff(0, [100, 100, 0]), 45); close(bearingOff(90, [0, 100, 0]), -90); close(bearingOff(350, [0, 100, 0]), 10); close(bearingOff(0, [0, -1, 0]), -180);
  const data = { view, player: { pos: [0, 0, 0], vel: [0, 20, 0], hdg: 0 }, items: [item(3, [0, 500, 30], { vel: [0, -10, 0], dist: 500.9, dz: 30 })] };
  const m = engageMetrics(data, 3);
  close(m.vc, 30 * 500 / Math.hypot(500, 30), 1e-6); close(m.ang, 0); assert.equal(m.dz, 30); assert.equal(m.dist, 500.9);
  assert.equal(engageMetrics(data, 9), null);
});
test('kayıttan oynatma: etkin angajman ve aralık olayları (başlangıç / başarı / kesilme)', () => {
  const list = [{ i: 0, name: 'A', t0: 10, dur_s: 5, result: 'success' }, { i: 1, name: 'B', t0: 20, dur_s: 2, result: 'cut', reason: 'lost' }, { i: 0, name: 'A', t0: 30, dur_s: 1, result: 'active' }];
  assert.equal(engagementAt(list, 9.9), null); assert.equal(engagementAt(list, 12).name, 'A'); assert.equal(engagementAt(list, 21).i, 1); assert.equal(engagementAt(list, 23), null);
  assert.deepEqual(engagementEvents(list, 9, 16).map(e => e.kind), ['start', 'success']);
  assert.deepEqual(engagementEvents(list, 16, 25).map(e => `${e.kind}:${e.a.name}`), ['start:B', 'cut:B']);
  assert.deepEqual(engagementEvents(list, 25, 40).map(e => e.kind), ['start'], 'sürmekte olan (active) bitiş olayı üretmez');
  assert.deepEqual(engagementEvents(list, null, 40), [], 'atlamadan sonra ilk kare olay üretmez');
});
test('rapor satırları + puan bonusu (hedef başına bir kez)', () => {
  const T = makeEngT(null);
  const rows = engagementRows([{ i: 0, name: 'Lancet', start_s: 12.34, dur_s: 8.06, result: 'success', min_dist_m: 18.2 }, { i: 1, name: 'SW', start_s: 30, dur_s: 3.1, result: 'cut', reason: 'lost', min_dist_m: null }], T);
  assert.deepEqual(rows[0], { target: 'T1 · Lancet', start: '12.3 s', dur: '8.1 s', result: 'Başarılı', cls: 'green', min: '18 m' });
  assert.equal(rows[1].result, 'Kesildi · hedef görüş dışında'); assert.equal(rows[1].min, '—');
  const base = { items: [{ intercepts: 2, first_s: 20, min_dist_m: 8 }], count: 1, total: 2, all_hit: true };
  const s0 = scoreOf(base).score, s1 = scoreOf({ ...base, items: [{ ...base.items[0], locked_hits: 3 }] }).score;
  assert.equal(s1 - s0, ENGAGE_BONUS); assert.equal(ENGAGE_BONUS, 250);
});

console.log('HUD sembolojisi');
test('tgthud: data.eng → kilitli (TD) hedef engaged; ekran dışı da işaretlenir; çizim KİLİT yazar (duman)', () => {
  const data = { view, sel: { i: 1, auto: false }, eng: { i: 1 }, player: { pos: [0, 0, 0], vel: [0, 0, 0] }, items: [item(0, [-80, 400, 0]), item(1, [5, 900, 0])] };
  const sym = symbology(data, W, H);
  assert.equal(sym.locked.i, 1); assert.equal(sym.locked.engaged, true); assert.equal(sym.items.find(r => r.i === 0).engaged, false);
  const calls = [], g = new Proxy({}, { get: (t, k) => (k in t ? t[k] : typeof k === 'string' && /^(fill|stroke)Text$/.test(k) ? (s => calls.push(s)) : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
  drawSymbology(g, sym, { W, H, tr: s => (s === 'KİLİT' ? 'LOCK' : s), now: 0 });
  assert.ok(calls.includes('LOCK'), 'KİLİT metni');
  const back = symbology({ ...data, items: [item(1, [5, -900, 0])] }, W, H);
  assert.equal(back.locked.on, false); assert.equal(back.locked.engaged, true);
  calls.length = 0; drawSymbology(g, back, { W, H, tr: s => (s === 'KİLİT' ? 'LOCK' : s), now: 0 }); assert.ok(calls.includes('LOCK'), 'ok bloğunda KİLİT');
});

console.log('metinler + bağlama');
test('HEPGO 6 dil: eng metinleri + KİLİT + Boşluk ipuçları + gamepad kilidi', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const want = [...ENGAGE_TEXTS.map(([, v]) => v), 'KİLİT', 'Boşluk: kilit', 'Hedef kilidi (angajman)'];
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = want.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: eng.* + KİLİT + pad.act_lock; yer tutucular korunur; makeEngT keyed', () => {
  const keys = [...ENGAGE_TEXTS.map(([k]) => k), 'KİLİT', 'Boşluk: kilit', 'pad.act_lock'];
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = keys.filter(k => !(k in d));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
    for (const [k, v] of ENGAGE_TEXTS) for (const ph of v.match(/\{\w+\}/g) || []) assert.ok(d[k].includes(ph), `${l} ${k} ${ph}`);
  }
  assert.equal(makeEngT(k => (k === 'eng.lock' ? 'LOCK' : k), true)('eng.lock'), 'LOCK');
  assert.equal(makeEngT(null)('eng.lost_in', { s: '1.5' }), 'GÖRÜŞ DIŞI 1.5 sn');
});
test('gamepad: lock eylemi (standart düğme 0, RC atanmamış); HEPGO + SIMUMAV oturumları modülü bağlar', () => {
  assert.ok(PAD_ACTIONS.includes('lock')); assert.equal(DEFAULT_PAD.standard.buttons.lock, 0); assert.equal(DEFAULT_PAD.rc.buttons.lock, -1);
  const hp = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(/createEngageCtl\(stage/.test(hp) && /m\.t === 'engage'\) return engage\?\.onServer\(m\)/.test(hp) && /a === 'lock'\) engage\?\.toggle\(\)/.test(hp) && /engage\?\.replayFrame\(t\.tt\)/.test(hp));
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/session.js'), 'utf8');
  assert.ok(/'flightsim_engage\.js'/.test(sm) && /MEng\.createEngageCtl\(stage/.test(sm) && /case 'engage':/.test(sm) && /a === 'lock'\) engage\?\.toggle\(\)/.test(sm));
});
console.log(`\n${n} test geçti`);
