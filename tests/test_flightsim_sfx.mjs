// Uçuş Simülatörü §44 — KARŞILAŞMA OYUN EFEKTLERİ (flightsim_sfx.js) + YAPAY ZEKÂ PİLOT ön yüz yardımcıları (flightsim_match.js, SIMUMAV match_core.js)
// tarayıcısız birim testi:
//   • olay → nota planı (her olay çalınabilir, süreler kısa), halka perdesi sırayla yükselir (≤ 2 oktav), sıralama değişimi, puan sayacı adımları
//   • tercih (varsayılan açık / 80, kalıcı, bozuk kayıt), kazanç: kapalı → 0, uçuş uyarısı çalarken önemsizler 0, diğerleri kısık
//   • createSfx: sahte Web Audio ile çalma (master yolu = motor sesi alertBus; ses kapalıysa çalmaz), uyarı önceliği, ayar satırı bağlama
//   • bot yardımcıları: ad/rozet (sunucu adlarıyla aynı), rakip doğrulaması (it dalaşında tam 1), canlı sıra, puan, renk; SIMUMAV aiBody + #/fly/ai
//   • seviye/ad/renk sabitleri çekirdekle (app/flightsim_match_core.py) aynı; metinler HEPGO 6 dil + SIMUMAV 7 dil (sfx.*, ai.*; yer tutucular)
// Çalıştırma: node tests/test_flightsim_sfx.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ALERT_DUCK, SFX_EVENTS, SFX_MINOR, SFX_TEXTS, countSteps, createSfx, createSfxPrefs, makeSfxT, planLength, rankChange, ringFreq, sfxGain, sfxPlan } from '../static/js/modules/flightsim_sfx.js';
import { BOT_COLORS, BOT_LEVELS, BOT_LEVEL_TEXT, BOT_NAMES, botBadge, botName, colorFor, isBot, matchScore, myRank, opponentsError } from '../static/js/modules/flightsim_match.js';
import { AI_LEVELS, aiBody, parseFlyParam, resultRows } from '../static/simumav/app/fly/match_core.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const mem = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };

console.log('efekt planları');
test('her olay çalınabilir nota planı üretir; süreler kısa', () => {
  for (const ev of SFX_EVENTS) {
    const p = sfxPlan(ev, { i: 2, n: 5, p: 0.5 });
    assert.ok(p.length > 0, ev);
    for (const x of p) assert.ok(x.f > 20 && x.f < 8000 && x.d > 0 && x.g > 0 && x.g <= 1 && x.t >= 0, `${ev} ${JSON.stringify(x)}`);
    assert.ok(planLength(p) <= 1.6, `${ev} ${planLength(p)}`);
  }
  assert.deepEqual(sfxPlan('yok'), []);
  assert.ok(planLength(sfxPlan('win')) > planLength(sfxPlan('ring')), 'zafer jingle halka dinginden uzun');
  assert.ok(sfxPlan('lose').at(-1).f < sfxPlan('lose')[0].f, 'kaybedince alçalan ton');
  assert.ok(sfxPlan('overtake').some(x => x.noise) && sfxPlan('overtaken').every(x => x.f < 300), 'öne geçme whoosh + ding, geride kalma alçak ton');
});
test('halka "ding" perdesi sırayla yükselir (en çok 2 oktav)', () => {
  const fs = [1, 2, 3, 4, 5, 6, 7, 8].map(i => ringFreq(i, 8));
  for (let i = 1; i < fs.length; i++) assert.ok(fs[i] > fs[i - 1], fs);
  assert.ok(Math.abs(fs[0] - 523.25) < 0.1 && fs.at(-1) <= 523.25 * 4 + 0.1, fs);
  assert.ok(ringFreq(30, 30) <= 523.25 * 4 + 0.1 && ringFreq(0, 5) === ringFreq(1, 5));
  assert.equal(sfxPlan('ring', { i: 3, n: 8 })[0].f, ringFreq(3, 8));
  const l0 = sfxPlan('lock', { p: 0 })[0].f, l1 = sfxPlan('lock', { p: 1 })[0].f;
  assert.ok(l1 > l0 && l0 === 440 && l1 === 1320, 'angajman tonu dolarken yükselir');
});
test('sıralama değişimi ve puan sayacı', () => {
  assert.equal(rankChange(3, 2), 'overtake'); assert.equal(rankChange(1, 2), 'overtaken');
  assert.equal(rankChange(2, 2), null); assert.equal(rankChange(null, 1), null); assert.equal(rankChange(1, undefined), null);
  const st = countSteps(450);
  assert.ok(st.length <= 24 && st.at(-1).v === 450 && st.every((x, i) => !i || (x.v >= st[i - 1].v && x.t >= st[i - 1].t)), JSON.stringify(st));
  assert.deepEqual(countSteps(0), [{ v: 0, t: 0 }]);
  assert.equal(countSteps(7).length, 7);
});

console.log('tercih ve kazanç');
test('tercih: varsayılan açık/80, kalıcı, bozuk kayıt, dinleyici', () => {
  const s = mem();
  const p = createSfxPrefs(s, 'fs.sfx');
  assert.deepEqual(p.get(), { on: true, vol: 80 });
  let seen = null; p.onChange(v => { seen = v; });
  p.set({ vol: 135 });
  assert.deepEqual(seen, { on: true, vol: 100 });
  p.set({ on: false });
  assert.deepEqual(JSON.parse(s.getItem('fs.sfx')), { on: false, vol: 100 });
  assert.deepEqual(createSfxPrefs(s, 'fs.sfx').get(), { on: false, vol: 100 });
  s.setItem('sm.sfx', '{bozuk'); assert.deepEqual(createSfxPrefs(s, 'sm.sfx').get(), { on: true, vol: 80 });
});
test('kazanç: kapalı 0; uyarı çalarken önemsizler 0, diğerleri kısık', () => {
  assert.equal(sfxGain({ on: false, vol: 80 }, 'ring'), 0);
  assert.equal(sfxGain({ on: true, vol: 0 }, 'win'), 0);
  assert.equal(sfxGain({ on: true, vol: 50 }, 'ring'), 0.5);
  for (const ev of SFX_MINOR) assert.equal(sfxGain({ on: true, vol: 100 }, ev, true), 0, ev);
  assert.equal(sfxGain({ on: true, vol: 100 }, 'win', true), ALERT_DUCK);
  assert.ok(SFX_MINOR.has('lock') && !SFX_MINOR.has('ring'));
});

console.log('çalma (sahte Web Audio)');
function fakeAudio(on = true) {
  const log = [];
  const param = () => ({ value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {}, linearRampToValueAtTime() {} });
  const node = kind => ({ kind, gain: param(), frequency: param(), Q: param(), type: '', buffer: null, connect(x) { return x; }, disconnect() {}, start() { log.push(kind); }, stop() {} });
  const ctx = { currentTime: 0, sampleRate: 8000, state: 'running', createGain: () => node('gain'), createOscillator: () => node('osc'), createBiquadFilter: () => node('bq'),
    createBufferSource: () => node('noise'), createBuffer: (c, len) => ({ getChannelData: () => new Float32Array(len) }), destination: node('dest') };
  const master = node('master');
  return { log, ctx, audio: { alertBus: () => (on ? { ctx, bus: master } : null), graph: { master } } };
}
test('motor sesi master yolunda çalar; ses kapalıysa çalmaz; uyarı önceliği', () => {
  const A = fakeAudio(true);
  let alert = false;
  const fx = createSfx({ audio: A.audio, storage: mem(), isAlert: () => alert });
  assert.equal(fx.play('ring', { i: 1, n: 3 }), true);
  assert.equal(A.log.filter(x => x === 'osc').length, 2);
  assert.equal(fx.play('overtake'), true);
  assert.ok(A.log.includes('noise'), 'whoosh gürültüsü');
  assert.equal(fx.last.ev, 'overtake');
  alert = true;
  assert.equal(fx.play('lock', { p: 0.4 }), false, 'uyarı çalarken angajman tonu yok');
  assert.equal(fx.play('win'), true);
  assert.ok(Math.abs(fx.last.gain - 0.8 * ALERT_DUCK) < 1e-9, fx.last);
  fx.prefs.set({ on: false });
  alert = false;
  assert.equal(fx.play('coin'), false);
  const off = createSfx({ audio: fakeAudio(false).audio, storage: mem() });
  assert.equal(off.play('ring'), false, 'genel ses kapalı / etkileşim yok → sessiz');
  assert.ok(off.state().skipped >= 1);
  const none = createSfx({ storage: mem(), fallbackVol: () => 0 });
  assert.equal(none.play('ring'), false, 'yedek bağlam: genel ses 0');
  fx.dispose(); off.dispose(); none.dispose();
});
test('metinler: HEPGO Türkçe anahtar / SIMUMAV sfx.* (keyed, yedek Türkçe)', () => {
  const T = makeSfxT(k => (k === 'Oyun efektleri' ? 'Game effects' : k), false);
  assert.equal(T('sfx.title'), 'Game effects');
  const K = makeSfxT(k => (k === 'sfx.on' ? 'Effects on' : k), true);
  assert.equal(K('sfx.on'), 'Effects on'); assert.equal(K('sfx.off'), 'Efekt kapalı');
  assert.equal(makeSfxT(null)('sfx.vol'), 'Efekt düzeyi');
});

console.log('yapay zekâ pilot yardımcıları');
const core = readFileSync(join(ROOT, 'app/flightsim_match_core.py'), 'utf8');
test('seviyeler, adlar ve renkler çekirdekle aynı', () => {
  const tup = name => JSON.parse(`[${core.match(new RegExp(`^${name} = \\(([^)]*)\\)`, 'm'))[1].replace(/'/g, '"').replace(/,\s*$/, '')}]`);
  assert.deepEqual(BOT_LEVELS, tup('BOT_SEVIYELER'));
  assert.deepEqual(BOT_NAMES, tup('BOT_ADLARI'));
  assert.deepEqual(BOT_COLORS, tup('BOT_RENKLERI'));
  assert.deepEqual(AI_LEVELS, BOT_LEVELS);
  for (const l of BOT_LEVELS) assert.ok(core.includes(`'${l}': '${BOT_LEVEL_TEXT[l]}'`), l);
  for (const [l, h] of [['easy', 0.55], ['normal', 0.75], ['hard', 0.95]]) assert.ok(new RegExp(`'${l}':\\s+\\{'hiz': ${h}`).test(core), `${l} hız ${h}`);
});
test('ad / rozet / renk / rakip doğrulaması', () => {
  assert.equal(botName('hard', 0), 'AI-Şahin (Zor)');
  assert.equal(botName('easy', 8, { withLevel: false }), 'AI-Kartal');
  assert.equal(botName('normal', 1, { T: s => (s === 'Normal' ? 'Medium' : s) }), 'AI-Kartal (Medium)');
  assert.ok(isBot({ id: -1 }) && isBot({ id: 5, is_bot: true }) && !isBot({ id: 5 }) && !isBot(null));
  assert.equal(botBadge({ id: -1, is_bot: true, level: 'hard' }), 'AI · Zor');
  assert.equal(botBadge({ id: -1, is_bot: true }), 'AI');
  assert.equal(botBadge({ id: 3 }), null);
  const P = [{ id: 1 }, { id: -1, color: '#ef4444' }];
  assert.equal(colorFor(P, -1), '#ef4444'); assert.equal(colorFor(P, 1), '#22c55e');
  assert.equal(opponentsError(0, 0, 7), 'En az bir kullanıcı davet edin ya da yapay zekâ pilot ekleyin');
  assert.equal(opponentsError(0, 2, 7), null);
  assert.equal(opponentsError(3, 5, 7), 'Davet sınırı aşıldı');
  assert.match(opponentsError(1, 1, 1), /tam 2 oyuncu/);
  assert.equal(opponentsError(0, 1, 1), null);
});
test('canlı sıra ve puan', () => {
  const players = [{ id: 1, status: 'hazir', rings: 1 }, { id: -1, status: 'hazir', rings: 2, is_bot: true }, { id: 2, status: 'hazir', rings: 0 }];
  assert.equal(myRank(players, {}, 1), 2);
  assert.equal(myRank(players, { 1: { rings: 3 } }, 1), 1);
  assert.equal(myRank([{ id: 1, status: 'hazir' }], {}, 1), null);
  assert.equal(matchScore({ rank: 1, rings: 3, finished: true }), 300 + 250 + 150);
  assert.equal(matchScore({ rank: 3, rings: 2, finished: false }), 200);
  assert.equal(matchScore({ won: true, role: 'chaser' }, 'dogfight', { max_hold_s: 3.2 }), 1320);
  assert.equal(matchScore({ won: false, role: 'evader' }, 'dogfight', { max_hold_s: 3 }), 0);
  assert.equal(matchScore(null), 0);
});
test('SIMUMAV: #/fly/ai, aiBody, sonuç satırında bot', () => {
  assert.deepEqual(parseFlyParam('ai'), { kind: 'ai' });
  const b = aiBody({ drone_id: 1, track_id: 2, kind: 'rings', password: 'x', max_players: 3 }, 'hard', 9, { players: [2, 4] });
  assert.deepEqual(b, { drone_id: 1, track_id: 2, kind: 'rings', level: 'hard', bots: 3 });
  assert.equal(aiBody({ kind: 'dogfight' }, 'easy', 5).bots, 1);
  assert.equal(aiBody({}, 'uzman').level, 'normal');
  const rows = resultRows({ result: { standings: [{ id: -1, name: 'AI-Şahin', is_bot: true, level: 'hard', rank: 1 }, { id: 4, name: 'Ali', rank: 2 }], winner: -1 } });
  assert.ok(rows[0].is_bot && rows[0].level === 'hard' && rows[0].winner && !rows[1].is_bot);
});

console.log('metinler');
test('HEPGO 6 dil: yeni Türkçe anahtarlar', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const want = [...SFX_TEXTS.map(([, v]) => v), 'Yapay zekâ pilot ekle', 'Kolay', 'Zor', 'Puanınız', 'Yapay zekâ pilot', 'Yapay zekâ pilotu kaldır',
    '{n} yapay zekâ pilot · her biri kendi simülatörünü kullanır', 'En çok {n} rakip olabilir (davetli + yapay zekâ)',
    'İt dalaşı tam 2 oyuncuyla oynanır: bir kullanıcı davet edin ya da bir yapay zekâ pilot ekleyin', 'En az bir kullanıcı davet edin ya da yapay zekâ pilot ekleyin'];
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = want.filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: sfx.* + ai.* anahtarları, yer tutucular', () => {
  const tr = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n/tr.json'), 'utf8'));
  const keys = [...SFX_TEXTS.map(([k]) => k), ...Object.keys(tr).filter(k => k.startsWith('ai.'))];
  assert.ok(keys.length >= 30, keys.length);
  for (const [k, v] of SFX_TEXTS) assert.equal(tr[k], v, k);
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = keys.filter(k => !(typeof d[k] === 'string' && d[k].trim()));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
    for (const k of keys) assert.deepEqual((d[k].match(/\{\w+\}/g) || []).sort(), (tr[k].match(/\{\w+\}/g) || []).sort(), `${l} ${k}`);
  }
  // kullanılan her ai.* anahtarı katalogda
  const src = ['match.js', 'match_hud.js', 'index.js', 'wizard.js'].map(f => readFileSync(join(ROOT, 'static/simumav/app/fly', f), 'utf8')).join('\n');
  const used = new Set([...src.matchAll(/'(ai\.[a-z_]+)'/g)].map(m => m[1]));
  for (const l of ['easy', 'normal', 'hard']) { used.add(`ai.level_${l}`); used.add(`ai.level_${l}_d`); }
  const yok = [...used].filter(k => !(k in tr));
  assert.deepEqual(yok, [], yok.join(', '));
});
console.log(`test_flightsim_sfx: ${n} test TAMAM`);
