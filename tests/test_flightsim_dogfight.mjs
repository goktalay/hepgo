// Uçuş Simülatörü §41 — İT DALAŞI ön yüz saf katmanı (flightsim_dogfight.js) tarayıcısız birim testi:
//   • sınırlar / varsayılanlar çekirdekle (app/flightsim_match_core.py) aynı, istemci doğrulaması, özet metni
//   • rol / rakip / kalan süre / koni durumu, sonuç satırları (kazanan önce), rakip işaretçisi (ekranda kutu, arkada kenar oku)
//   • kurallar şeması (SVG), metinler: HEPGO 6 dil (Türkçe anahtar) + SIMUMAV 7 dil (df.*; yer tutucular), bağlama (HEPGO + SIMUMAV)
// Çalıştırma: node tests/test_flightsim_dogfight.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DF_LIMITS, DF_TEXTS, coneState, dfDefaults, dfError, dfResultRows, dfSummary, dfSvg, fmtMMSS, makeDfT, opponentMarker, opponentOf, remainS, roleOf } from '../static/js/modules/flightsim_dogfight.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const core = readFileSync(join(ROOT, 'app/flightsim_match_core.py'), 'utf8');
const pyPair = name => { const m = core.match(new RegExp(`^${name} = \\(([\\d.]+), ([\\d.]+)\\)`, 'm')); return m ? [Number(m[1]), Number(m[2])] : null; };

console.log('saf katman');
test('sınırlar ve varsayılanlar çekirdekle aynı', () => {
  for (const [js, py] of [['distance_m', 'IT_MESAFE'], ['alt_m', 'IT_IRTIFA'], ['time_limit_min', 'IT_SURE_DK'], ['range_m', 'IT_MENZIL'], ['cone_deg', 'IT_KONI'], ['hold_s', 'IT_TUTMA'], ['area_radius_m', 'IT_ALAN']]) {
    assert.deepEqual(DF_LIMITS[js], pyPair(py), js);
  }
  assert.ok(core.includes("IT_ROLLER = ('random', 'host_chaser', 'host_evader')") && core.includes('KORUMA_S = 60.0'));
  assert.equal(dfDefaults('multirotor').range_m, 120); assert.equal(dfDefaults('sabit_kanat').distance_m, 1000); assert.equal(dfDefaults('vtol').cone_deg, 30);
  assert.ok(core.includes("'dikey': {'distance_m': 400.0, 'alt_m': 40.0, 'time_limit_min': 5, 'range_m': 120.0, 'cone_deg': 30.0, 'hold_s': 3.0, 'area_radius_m': 800.0}"));
});
test('istemci doğrulaması: sınır dışı, tam sayı süre, alan ≥ mesafe/2 + 150, rol', () => {
  assert.equal(dfError(dfDefaults('multirotor')), null);
  for (const bad of [{ distance_m: 200 }, { cone_deg: 50 }, { hold_s: 1 }, { time_limit_min: 2.5 }, { roles: 'x' }, { distance_m: 1400, area_radius_m: 800 }]) assert.ok(dfError({ ...dfDefaults('multirotor'), ...bad }), JSON.stringify(bad));
  assert.ok(dfError(null));
  assert.match(dfSummary(dfDefaults('multirotor')), /400 m · 40 m · 5 dk · 120 m \/ ±30° \/ 3\.0 s · R 800 m · Rastgele/);
});
test('rol / rakip / kalan süre / koni durumu', () => {
  const M = { start_at: 1000, rings_cfg: { time_limit_min: 5, range_m: 150, cone_deg: 25, hold_s: 3 }, players: [{ id: 1, name: 'A', role: 'chaser', status: 'hazir' }, { id: 2, name: 'B', role: 'evader', status: 'hazir' }] };
  assert.equal(roleOf(M, 1), 'chaser'); assert.equal(roleOf(M, 2), 'evader'); assert.equal(opponentOf(M, 1).id, 2);
  assert.equal(roleOf({ result: { dogfight: { roles: { 7: 'evader' } } } }, 7), 'evader');
  assert.equal(remainS(M, 1060), 240); assert.equal(remainS(M, 9999), 0); assert.equal(fmtMMSS(239.2), '4:00'); assert.equal(fmtMMSS(null), '—');
  assert.equal(coneState({ dist: 100, in_cone: true }, M.rings_cfg), 'in');
  assert.equal(coneState({ dist: 200, in_cone: false }, M.rings_cfg), 'range');
  assert.equal(coneState({ dist: 100, in_cone: false, off_deg: 40 }, M.rings_cfg), 'cone');
  assert.equal(coneState({ dist: 100, guard: true }, M.rings_cfg), 'guard'); assert.equal(coneState(null, M.rings_cfg), null);
});
test('sonuç satırları: kazanan, rol (sonuçtan), azami hız', () => {
  const M = { result: { winner: 2, reason: 'sure', standings: [{ id: 2, name: 'B', max_speed_ms: 22.4, crashes: 0 }, { id: 1, name: 'A', max_speed_ms: 18, crashes: 1 }], dogfight: { roles: { 1: 'chaser', 2: 'evader' } } } };
  const r = dfResultRows(M);
  assert.deepEqual(r.map(x => [x.id, x.role, x.won]), [[2, 'evader', true], [1, 'chaser', false]]);
});
test('rakip işaretçisi: önde → ekranda kutu; arkada → kenar oku (aşağı yarım küre doğru tarafta)', () => {
  const view = { pos: [0, 0, 0], fwd: [0, 1, 0], right: [1, 0, 0], up: [0, 0, 1], tanV: Math.tan(Math.PI / 6), aspect: 16 / 9 };
  const a = opponentMarker(view, { x: 0, y: 300, z: 0 }, 1600, 900);
  assert.ok(a.on && Math.abs(a.x - 800) < 1e-6 && Math.abs(a.y - 450) < 1e-6 && a.arrow === null);
  const b = opponentMarker(view, { x: 100, y: -300, z: 0 }, 1600, 900);
  assert.ok(!b.on && b.arrow && b.arrow.x > 800, 'arkada sağdaki rakip: sağ kenarda ok');
  assert.equal(opponentMarker(null, { x: 0, y: 1, z: 0 }, 10, 10), null);
});
test('kurallar şeması (SVG): alan dairesi, koni kaması, iki başlangıç, mesafe; gerçek başlangıçlarla', () => {
  const s = dfSvg(dfDefaults('multirotor'));
  assert.ok(s.startsWith('<svg') && s.includes('R 800 m') && s.includes('400 m') && (s.match(/<circle/g) || []).length >= 3 && s.includes('<path'));
  const s2 = dfSvg(dfDefaults('multirotor'), { starts: [{ role: 'chaser', x: -200, y: 0, yaw_deg: 90 }, { role: 'evader', x: 200, y: 0, yaw_deg: 90 }] });
  assert.ok(s2.includes('<svg') && s2 !== s);
});

console.log('metinler + bağlama');
test('HEPGO 6 dil: DF metinleri (Türkçe anahtar) + "Tür ve kurallar"', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const want = [...DF_TEXTS.filter(([k]) => !k.endsWith('_s')).map(([, v]) => v), 'Tür ve kurallar'];
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = want.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: df.* anahtarları, yer tutucular korunur; makeDfT keyed', () => {
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = DF_TEXTS.map(([k]) => k).filter(k => !(k in d));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
    for (const [k, v] of DF_TEXTS) for (const ph of v.match(/\{\w+\}/g) || []) assert.ok(d[k].includes(ph), `${l} ${k} ${ph}`);
    assert.ok(d['match.step_rings'], 'adım başlığı');
  }
  assert.equal(makeDfT(k => (k === 'df.chaser' ? 'CHASER' : k), true)('df.chaser'), 'CHASER');
  assert.equal(makeDfT(null)('df.out_range', { d: 220, r: 150 }), 'MENZİL DIŞI 220 / 150 m');
});
test('bağlama: HEPGO sihirbaz/salon/oturum + SIMUMAV sihirbaz/salon/yarış it dalaşını kullanır', () => {
  const ui = readFileSync(join(ROOT, 'static/js/modules/flightsim_match_ui.js'), 'utf8');
  assert.ok(/createDogfightHud\(stage/.test(ui) && /kind: \(\) => kind/.test(ui) && /rematch: id =>/.test(ui) && /dfResultsBody/.test(ui));
  const fs = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(/kind: ringsSec\.kind\(\), dogfight:/.test(fs) && /inviteSec\?\.setMax\(k === 'dogfight' \? 1 : null\)/.test(fs));
  const hud = readFileSync(join(ROOT, 'static/simumav/app/fly/match_hud.js'), 'utf8');
  assert.ok(/createDogfightHud\(stage/.test(hud) && /dfResultTable/.test(hud));
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/match.js'), 'utf8');
  assert.ok(/kind: 'dogfight', dogfight: dfBodyOf\(D\)/.test(sm) && /W\.state\.kind === 'dogfight' \? \[2\]/.test(sm));
  const wz = readFileSync(join(ROOT, 'static/simumav/app/fly/wizard.js'), 'utf8');
  assert.ok(/max_players: df \? 2 : S\.max_players/.test(wz));
});
console.log(`\n${n} test geçti`);
