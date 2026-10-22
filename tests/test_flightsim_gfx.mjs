// Uçuş Simülatörü §43 — GRAFİK KALİTE AYARLARI tarayıcısız birim testi (flightsim_gfx.js saf katmanı):
//   • ön ayar → parametreler (Düşük/Orta/Yüksek/Ultra; Yüksek = §43 öncesi sabitler + son işlem; GFX_LEGACY), Özel ince ayar normalleştirme, yetenek kırpması
//   • piksel oranı (ölçek, tavan, bütçe, ekran kaydı tabanı), kare sınırı kapısı (30/60/sınırsız, arka plan 20 fps)
//   • otomatik kademe kuralları (yazılım WebGL, zayıf tümleşik, ayrık, üst sınıf, mobil, yüksek dpr)
//   • uyarlamalı kademe histerezisi (önce ölçek, sonra kademe; bekleme; dönüş kilidi iki katına) + dinamik çözünürlük
//   • kalıcı tercih (fs.gfx / sm.gfx), metinler HEPGO 6 dil + SIMUMAV 7 dil (gfx.*), oturum/sihirbaz/3B bağlama
// Çalıştırma: node tests/test_flightsim_gfx.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ATLAS_MAX, GFX_CHOICES, GFX_KEY, GFX_KEY_SM, GFX_LEGACY, GFX_LEVELS, GFX_PRESETS, GFX_TEXTS, TERRAIN_LOD, autoLevel, createAdaptive, createDynRes, frameGate, levelLabel,
  loadGfxPref, makeGfxT, mobileWarn, normCustom, normGfxPref, pixelRatioFor, recordFloor, resolveGfx, saveGfxPref } from '../static/js/modules/flightsim_gfx.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);
const memStorage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };

console.log('ön ayarlar');
test('dört kademe tam alan kümesi; kademeler monoton (ölçek tavanı, gölge, sis, ağaç, aniso, Google eşiği)', () => {
  const keys = Object.keys(GFX_PRESETS.high).sort();
  for (const l of GFX_LEVELS) assert.deepEqual(Object.keys(GFX_PRESETS[l]).sort(), keys, l);
  const P = GFX_LEVELS.map(l => GFX_PRESETS[l]);
  for (let i = 1; i < P.length; i++) {
    assert.ok(P[i].prCap >= P[i - 1].prCap && P[i].budget > P[i - 1].budget && P[i].shadow > P[i - 1].shadow && P[i].fog > P[i - 1].fog);
    assert.ok(P[i].trees > P[i - 1].trees && P[i].treeLod > P[i - 1].treeLod && P[i].aniso > P[i - 1].aniso && P[i].g3dError < P[i - 1].g3dError && P[i].terrain > P[i - 1].terrain);
  }
  assert.equal(GFX_PRESETS.low.post, false); assert.equal(GFX_PRESETS.medium.post, false); assert.equal(GFX_PRESETS.high.post, true); assert.equal(GFX_PRESETS.ultra.post, true);
  assert.ok(GFX_PRESETS.high.ao > 0 && GFX_PRESETS.ultra.ao === 2 && GFX_PRESETS.ultra.bloom > 0 && GFX_PRESETS.ultra.cascade && GFX_PRESETS.ultra.terrainCast);
});
test('resolveGfx: Düşük kapalı AA/gölge, 30 fps; Ultra MSAA 8× (destek 4 ise 4), 4096 gölge, süper örnekleme 1,5×', () => {
  const lo = resolveGfx({ preset: 'low' });
  assert.equal(lo.level, 'low'); assert.equal(lo.samples, 0); assert.equal(lo.shadow, 0); assert.equal(lo.fpsCap, 30); assert.equal(lo.post, false); assert.equal(lo.fxaa, false);
  const u = resolveGfx({ preset: 'ultra' }, { maxSamples: 8, maxAniso: 16, maxTex: 16384 });
  assert.equal(u.samples, 8); assert.equal(u.shadow, 4096); assert.equal(u.scale, 1.5); assert.equal(u.aniso, 16); assert.equal(u.atlasMax, 8192); assert.equal(u.fpsCap, 0);
  const u4 = resolveGfx({ preset: 'ultra' }, { maxSamples: 4, maxAniso: 8, maxTex: 4096 });
  assert.equal(u4.samples, 4); assert.equal(u4.aniso, 8); assert.equal(u4.atlasMax, 4096, 'MAX_TEXTURE_SIZE < 8192 → 4096 atlas');
  assert.deepEqual(resolveGfx({ preset: 'medium' }).terrainLod, TERRAIN_LOD[1]);
  assert.deepEqual(ATLAS_MAX, [2048, 4096, 8192]);
});
test('Yüksek = §43 öncesi sabitler (MSAA 4, gölge 2048 ±90, sis 1, ızgara 320/256, ağaç 1, LOD 520, aniso 8, PiP 1, karo 14) + son işlem; GFX_LEGACY son işlemsiz', () => {
  const h = resolveGfx({ preset: 'high' });
  assert.equal(h.samples, 4); assert.equal(h.shadow, 2048); assert.equal(h.shadowDist, 90); assert.equal(h.fog, 1); assert.equal(h.terrainLod.grid, 320); assert.equal(h.terrainLod.real, 256);
  assert.equal(h.terrainLod.ring, 128); assert.equal(h.terrainLod.far, 192); assert.equal(h.trees, 1); assert.equal(h.treeLod, 520); assert.equal(h.aniso, 8); assert.equal(h.pipScale, 1); assert.equal(h.post, true);
  assert.equal(GFX_LEGACY.post, false); assert.equal(GFX_LEGACY.ao, 0); assert.equal(GFX_LEGACY.samples, 4); assert.equal(GFX_LEGACY.shadow, 2048); assert.equal(GFX_LEGACY.prCap, 2);
  assert.ok(Object.isFrozen(GFX_LEGACY));
});
test('Otomatik: kademe pref.autoLevel > caps.autoLevel > orta; kare sınırı 60; Özel: taban + ince ayar', () => {
  assert.equal(resolveGfx({ preset: 'auto' }).level, 'medium');
  assert.equal(resolveGfx({ preset: 'auto' }, { autoLevel: 'high' }).level, 'high');
  assert.equal(resolveGfx({ preset: 'auto', autoLevel: 'low' }, { autoLevel: 'high' }).level, 'low');
  assert.equal(resolveGfx({ preset: 'auto', autoLevel: 'low' }).fpsCap, 60, 'otomatikte Düşük de 60 (uyarlamalı kip yukarı çıkabilsin)');
  assert.equal(resolveGfx({ preset: 'auto' }, {}, { level: 'ultra', scaleMul: 0.7 }).level, 'ultra');
  close(resolveGfx({ preset: 'auto' }, {}, { level: 'ultra', scaleMul: 0.7 }).scale, 1.05);
  const c = resolveGfx({ preset: 'custom', base: 'medium', custom: { shadow: 4096, fog: 1.4, post: true, aa: 'fxaa', bloom: 2, junk: 5 } });
  assert.equal(c.level, 'medium'); assert.equal(c.shadow, 4096); assert.equal(c.fog, 1.4); assert.equal(c.post, true); assert.equal(c.fxaa, true); assert.equal(c.samples, 0); assert.equal(c.bloom, 1, 'sınıra kırpılır');
  assert.equal(c.trees, GFX_PRESETS.medium.trees, 'verilmeyen alan tabandan');
  assert.equal(resolveGfx({ preset: 'high', fpsCap: 0 }).fpsCap, 0, 'kullanıcı kare sınırı ön ayarı ezer');
});
test('normCustom / normGfxPref: bilinmeyen/bozuk alan atılır, sayısal kırpma, enum denetimi', () => {
  assert.deepEqual(normCustom({ shadow: 999, aa: 'ssaa', aniso: 3, scale: 9, post: 'evet', terrain: 2, ao: 1 }), { scale: 1.5, terrain: 2, ao: 1 });
  assert.deepEqual(normCustom(null), {});
  const p = normGfxPref({ preset: 'nope', base: 'x', fpsCap: 45, dynRes: 1, bgThrottle: false, autoLevel: 'ultra' });
  assert.equal(p.preset, 'auto'); assert.equal(p.base, 'high'); assert.equal(p.fpsCap, null); assert.equal(p.dynRes, true); assert.equal(p.bgThrottle, false); assert.equal(p.autoLevel, 'ultra');
  assert.equal(normGfxPref({ fpsCap: 0 }).fpsCap, 0); assert.equal(normGfxPref({}).bgThrottle, true);
});
test('kalıcı tercih: fs.gfx / sm.gfx ayrı anahtar; bozuk JSON → varsayılan', () => {
  assert.equal(GFX_KEY, 'fs.gfx'); assert.equal(GFX_KEY_SM, 'sm.gfx');
  const st = memStorage();
  saveGfxPref({ preset: 'ultra', fpsCounter: true }, st);
  saveGfxPref({ preset: 'low' }, st, GFX_KEY_SM);
  assert.equal(loadGfxPref(st).preset, 'ultra'); assert.equal(loadGfxPref(st).fpsCounter, true); assert.equal(loadGfxPref(st, GFX_KEY_SM).preset, 'low');
  st.setItem('fs.gfx', '{bozuk'); assert.equal(loadGfxPref(st).preset, 'auto');
  assert.equal(loadGfxPref(null).preset, 'auto');
});

console.log('piksel oranı + kare sınırı');
test('pixelRatioFor: dpr × ölçek, tavan, bütçe, en az 0,5; kayıt tabanı bütçeyi ezer', () => {
  const lo = resolveGfx({ preset: 'low' }), md = resolveGfx({ preset: 'medium' }), hi = resolveGfx({ preset: 'high' }), ul = resolveGfx({ preset: 'ultra' });
  assert.equal(pixelRatioFor(lo, { dpr: 1, cssW: 1280, cssH: 720 }), 0.75);
  assert.equal(pixelRatioFor(lo, { dpr: 2, cssW: 1280, cssH: 720 }), 1, 'tavan 1');
  assert.equal(pixelRatioFor(md, { dpr: 2, cssW: 1280, cssH: 720 }), 1.5);
  assert.equal(pixelRatioFor(hi, { dpr: 1, cssW: 1920, cssH: 1080 }), 1, '§43 öncesi: min(dpr, 2)');
  assert.equal(pixelRatioFor(hi, { dpr: 2, cssW: 1280, cssH: 720 }), 2);
  assert.equal(pixelRatioFor(ul, { dpr: 1, cssW: 1280, cssH: 720 }), 1.5, 'Ultra süper örnekleme 1,5×');
  const big = pixelRatioFor(ul, { dpr: 2, cssW: 3840, cssH: 2160 });
  assert.ok(3840 * 2160 * big * big <= 8.3e6 && big < 1.01, `bütçe: ${big}`);
  const qhd = pixelRatioFor(ul, { dpr: 2, cssW: 2560, cssH: 1440 });
  assert.ok(2560 * 1440 * qhd * qhd <= 8.3e6 && qhd <= 1.5, `bütçe: ${qhd}`);
  assert.equal(pixelRatioFor({ ...lo, scale: 0.3 }, { dpr: 1, cssW: 800, cssH: 600 }), 0.5, 'taban 0,5');
  const rf = recordFloor(1280, 720, 1);
  assert.equal(rf, 1); assert.equal(pixelRatioFor(lo, { dpr: 1, cssW: 1280, cssH: 720, floor: rf }), 1, 'kayıtta Düşük de tam çözünürlük');
  assert.equal(recordFloor(960, 540, 2), 2 * 0 + Math.min(2, 1280 / 960)); assert.equal(recordFloor(640, 360, 1), 1, 'dpr aşılmaz');
});
test('frameGate: 30 fps sınırında yarı kare atlanır; sınırsız her kare; arka planda 20 fps; uzun duraklama sonrası hizalanır', () => {
  let next = 0, drawn = 0;
  for (let i = 0, t = 0; i < 60; i++, t = i * 1000 / 60) { const g = frameGate(t, next, 30); if (g.draw) { drawn++; next = g.next; } }
  assert.ok(drawn >= 29 && drawn <= 31, `30 fps: ${drawn}`);
  next = 0; drawn = 0;
  for (let i = 0, t = 0; i < 60; i++, t = i * 1000 / 60) { const g = frameGate(t, next, 0); if (g.draw) { drawn++; next = g.next; } }
  assert.equal(drawn, 60);
  next = 0; drawn = 0;
  for (let i = 0, t = 0; i < 60; i++, t = i * 1000 / 60) { const g = frameGate(t, next, 60, { background: true }); if (g.draw) { drawn++; next = g.next; } }
  assert.ok(drawn >= 19 && drawn <= 21, `arka plan: ${drawn}`);
  assert.equal(frameGate(0, 0, 60, { background: true, bgThrottle: false }).draw, true);
  const g = frameGate(5000, 100, 30); assert.ok(g.draw && Math.abs(g.next - (5000 + 1000 / 30)) < 1e-9, 'duraklama sonrası şimdiden say');
});

console.log('otomatik kademe');
test('autoLevel: yazılım WebGL → Düşük (en çok Düşük); zayıf tümleşik → Düşük; Iris/Radeon Graphics → Orta; GTX/RX → Yüksek; RTX 4080 + 8 çekirdek → Ultra', () => {
  const sw = autoLevel({ gpu: 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)', cores: 16, mem: 8 });
  assert.equal(sw.level, 'low'); assert.equal(sw.tier, 'soft'); assert.equal(sw.max, 'low');
  assert.equal(autoLevel({ gpu: 'llvmpipe (LLVM 15.0.7, 256 bits)', cores: 8, mem: 8 }).level, 'low');
  assert.equal(autoLevel({ gpu: 'ANGLE (Intel, Intel(R) HD Graphics 520 Direct3D11 vs_5_0 ps_5_0)', cores: 4, mem: 8 }).level, 'low');
  const iris = autoLevel({ gpu: 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)', cores: 8, mem: 8, dpr: 1.25 });
  assert.equal(iris.level, 'medium'); assert.equal(iris.max, 'high');
  assert.equal(autoLevel({ gpu: 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11)', cores: 6, mem: 8 }).level, 'high');
  assert.equal(autoLevel({ gpu: 'AMD Radeon RX 580', cores: 4, mem: 8 }).level, 'high');
  const rtx = autoLevel({ gpu: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11)', cores: 16, mem: 8 });
  assert.equal(rtx.level, 'ultra'); assert.equal(rtx.max, 'ultra');
  assert.equal(autoLevel({ gpu: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3070)', cores: 4, mem: 8 }).level, 'high', 'az çekirdek → Yüksek');
  assert.equal(autoLevel({ gpu: 'Apple M2 Pro', cores: 10, mem: 8 }).level, 'ultra');
  assert.equal(autoLevel({ gpu: '', cores: 2, mem: 2 }).level, 'low'); assert.equal(autoLevel({}).level, 'medium');
});
test('autoLevel: mobil (Adreno 7xx → Orta, en çok Yüksek; Mali-G52 → Düşük); 4K tümleşik ekran bir kademe aşağı', () => {
  const m = autoLevel({ gpu: 'Adreno (TM) 740', mobile: true, cores: 8, mem: 8 }); assert.equal(m.level, 'medium'); assert.equal(m.max, 'high');
  assert.equal(autoLevel({ gpu: 'Mali-G52 MC2', mobile: true, cores: 8, mem: 4 }).level, 'low');
  assert.equal(autoLevel({ gpu: 'Apple GPU', mobile: true, cores: 6, mem: 4 }).level, 'medium');
  assert.equal(autoLevel({ gpu: 'Intel Iris Xe', cores: 8, mem: 8, dpr: 3 }).level, 'low');
  assert.equal(autoLevel({ gpu: 'NVIDIA GeForce RTX 3080', cores: 8, mem: 8, dpr: 3 }).level, 'ultra', 'ayrık GPU yüksek dpr\'de düşmez');
  assert.equal(mobileWarn('ultra', true), true); assert.equal(mobileWarn('high', false), false); assert.equal(mobileWarn('medium', true), false);
  assert.equal(mobileWarn('custom', true, 'ultra'), true); assert.equal(mobileWarn('auto', true), false);
});

console.log('uyarlamalı kademe (histerezis)');
const run = (a, fps, from, to, step = 500) => { const out = []; for (let t = from; t <= to; t += step) { const r = a.push(typeof fps === 'function' ? fps(t) : fps, t); if (r) out.push({ t, ...r }); } return out; };
test('sürekli düşük FPS: önce ölçek 0,85 → 0,7 (5 sn + bekleme), sonra kademe; en altta durur', () => {
  const a = createAdaptive({ level: 'high', max: 'ultra' });
  const ch = run(a, 25, 0, 120000);
  assert.deepEqual(ch.map(c => [c.reason, c.level, c.scaleMul]).slice(0, 5), [['scale', 'high', 0.85], ['scale', 'high', 0.7], ['level', 'medium', 1], ['scale', 'medium', 0.85], ['scale', 'medium', 0.7]]);
  assert.ok(ch[0].t >= 5000 && ch[1].t - ch[0].t >= 6000, 'downMs 5 sn + bekleme 6 sn');
  assert.equal(a.level, 'low'); const n0 = a.changes;
  assert.equal(ch.length, 8, 'yüksek→orta→düşük, her kademede iki ölçek adımı'); assert.equal(a.scaleMul, 0.7);
  run(a, 25, 120500, 160000); assert.equal(a.level, 'low'); assert.equal(a.scaleMul, 0.7); assert.equal(a.changes, n0, 'Düşük 0,7\'de daha inmez');
});
test('kısa düşüş (< 5 sn) değişiklik yapmaz; dalgalanan FPS titreme üretmez', () => {
  const a = createAdaptive({ level: 'medium' });
  assert.deepEqual(run(a, t => (t % 8000 < 4000 ? 30 : 60), 0, 40000), [], 'her 4 sn düşük/yüksek: ne iner ne çıkar (yukarı 12 sn ister)');
});
test('sürekli yüksek FPS: ölçek geri, sonra kademe yukarı (12 sn); en çok `max`', () => {
  const a = createAdaptive({ level: 'medium', max: 'high' });
  run(a, 25, 0, 6000);   // ölçek 0,85
  assert.equal(a.scaleMul, 0.85);
  const up = run(a, 60, 6500, 80000);
  assert.deepEqual(up.map(c => [c.reason, c.level]), [['scale', 'medium'], ['level', 'high']]);
  assert.equal(a.level, 'high'); assert.equal(a.scaleMul, 1);
});
test('dönüş kilidi: bir kademeden inince geri dönüş 30 sn kilitli; ikinci inişte kilit 60 sn (titreme yok)', () => {
  const a = createAdaptive({ level: 'high', max: 'ultra', scaleSteps: [1] });
  const d1 = run(a, 25, 0, 6000); assert.equal(d1.length, 1); assert.equal(a.level, 'medium');
  const tDown = d1[0].t; assert.equal(a.lockedUntil('high'), tDown + 30000);
  const u1 = run(a, 60, tDown + 500, tDown + 29000); assert.equal(u1.length, 0, 'kilit sürerken çıkmaz');
  const u2 = run(a, 60, tDown + 29500, tDown + 45000); assert.equal(u2.length, 1); assert.equal(a.level, 'high');
  const d2 = run(a, 25, u2[0].t + 500, u2[0].t + 12000); assert.equal(d2.length, 1);
  assert.equal(a.lockedUntil('high') - d2[0].t, 60000, 'ikinci inişte kilit iki katı');
});
test('kare sınırı 30: hedef ve yukarı eşiği sınıra göre (30 fps "düşük" sayılmaz, yukarı çıkılabilir)', () => {
  const a = createAdaptive({ level: 'low', max: 'medium', cap: 30 });
  assert.deepEqual(run(a, 30, 0, 20000).map(c => [c.reason, c.level]), [['level', 'medium']]);
  const b = createAdaptive({ level: 'medium', cap: 30 }); assert.deepEqual(run(b, 26, 0, 20000), [], '26 ≥ 0,8 × 30');
});
test('dinamik çözünürlük açıkken uyarlamalı kip ölçeği atlar; createDynRes 0,05 adımlarla 0,5…1', () => {
  const a = createAdaptive({ level: 'high', dynRes: true });
  assert.deepEqual(run(a, 20, 0, 6000).map(c => c.reason), ['level']);
  const d = createDynRes({ target: 50, cap: 60 });
  assert.equal(d.scale, 1);
  assert.equal(d.push(44), 0.95); assert.equal(d.push(20), 0.85, 'çok düşükte çift adım');
  for (let i = 0; i < 30; i++) d.push(10);
  assert.equal(d.scale, 0.5);
  assert.equal(d.push(48), null, 'ölü bölge');
  assert.equal(d.push(58), 0.55); assert.equal(d.push(Number.NaN), null);
});

console.log('metinler + bağlama');
test('GFX_TEXTS: gfx.* anahtarları, Türkçe değer; makeGfxT keyed / Türkçe yedek; levelLabel', () => {
  assert.ok(GFX_TEXTS.every(([k, v]) => k.startsWith('gfx.') && v));
  assert.equal(new Set(GFX_TEXTS.map(([k]) => k)).size, GFX_TEXTS.length, 'yinelenen anahtar yok');
  for (const c of GFX_CHOICES) assert.ok(GFX_TEXTS.some(([k]) => k === `gfx.${c}`), c);
  assert.equal(makeGfxT(null)('gfx.auto_now', { l: 'Orta' }), 'Otomatik: şu an Orta');
  assert.equal(makeGfxT(k => (k === 'gfx.btn' ? 'Graphics' : k), true)('gfx.btn'), 'Graphics');
  assert.equal(makeGfxT(k => k, true)('gfx.low'), 'Düşük', 'anahtar yoksa Türkçe');
  assert.equal(makeGfxT(s => `[${s}]`)('gfx.high'), '[Yüksek]', 'HEPGO: Türkçe metin sözlük anahtarı');
  assert.equal(levelLabel(makeGfxT(null), 'ultra'), 'Ultra');
});
test('HEPGO 6 dil: gfx metinleri', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = GFX_TEXTS.map(([, v]) => v).filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
  }
});
test('SIMUMAV 7 dil: gfx.* anahtarları', () => {
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(join(ROOT, 'static/simumav/app/i18n', `${l}.json`), 'utf8'));
    const missing = GFX_TEXTS.map(([k]) => k).filter(k => !(k in d));
    assert.deepEqual(missing, [], `${l}: eksik ${missing.join(' | ')}`);
  }
});
test('bağlama: HEPGO + SIMUMAV oturumu (Grafik kapsülü, opts.gfx, attach, dispose), sihirbaz son adımı, 3B setGraphics/gfxStats, kayıt tabanı', () => {
  const hp = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(/createGfxCtl\(\{ tr, getSim: \(\) => sim, stage/.test(hp) && /opsSnd\.append\(gfxCtl\.el\)/.test(hp) && /gfx: gfxCtl\.initial\(\)/.test(hp) && /gfxCtl\.attach\(sim\)/.test(hp) && /gfxCtl\.dispose\(\)/.test(hp));
  assert.ok(/createGfxPicker\(/.test(hp) && /summaryBox, gfxPick\.el/.test(hp), 'HEPGO sihirbaz özet adımı');
  const sm = readFileSync(join(ROOT, 'static/simumav/app/fly/session.js'), 'utf8');
  assert.ok(/'flightsim_gfx_ui\.js'/.test(sm) && /MGfx\.createGfxCtl\(\{ tr, keyed: true, storageKey: 'sm\.gfx'/.test(sm) && /gfx: gfxCtl\.initial\(\)/.test(sm) && /gfxCtl\.attach\(sim\)/.test(sm));
  assert.equal((sm.match(/gfxCtl\.dispose\(\)/g) || []).length, 2, 'iki dispose zinciri');
  const ix = readFileSync(join(ROOT, 'static/simumav/app/fly/index.js'), 'utf8');
  assert.ok(/flightsim_gfx_ui\.js'\)\.then\(M => .*createGfxPicker\(\{ tr, keyed: true, storageKey: 'sm\.gfx' \}\)/.test(ix), 'SIMUMAV sihirbaz son adımı');
  const f3 = readFileSync(join(ROOT, 'static/js/modules/flightsim3d.js'), 'utf8');
  assert.ok(/setGraphics, getGraphics, gfxStats, setRecordFloor/.test(f3) && /gpipe\.render\(scene, camera\)/.test(f3) && /frameGate\(now, gfxSt\.nextAt, gfx\.fpsCap/.test(f3));
  assert.ok(/new T\.WebGLRenderer\(/.test(f3) && (f3.match(/new T\.WebGLRenderer\(/g) || []).length === 1, 'tek renderer');
  assert.ok(/renderer\.info\.autoReset = false/.test(f3) && /renderer\.info\.reset\(\)/.test(f3), 'karenin toplam çizim çağrısı');
  const g3 = readFileSync(join(ROOT, 'static/js/modules/flightsim_g3d.js'), 'utf8');
  assert.ok(/setQuality/.test(g3) && /errorTarget: gfx\.g3dError/.test(f3), 'Google karo eşiği kaliteye bağlı');
  const rec = readFileSync(join(ROOT, 'static/js/modules/flightsim_record.js'), 'utf8');
  assert.ok(/setRecordFloor\?\.\(on\)/.test(rec), 'kayıt sürerken piksel oranı tabanı');
  const gx = readFileSync(join(ROOT, 'static/js/modules/flightsim_gfx3d.js'), 'utf8');
  assert.ok(!/new T\.WebGLRenderer|getContext\(/.test(gx), 'son işlem hattı ikinci bağlam açmaz');
});

console.log(`test_flightsim_gfx: ${n} test TAMAM`);
