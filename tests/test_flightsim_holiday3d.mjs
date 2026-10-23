// Bayram süsleri — UÇUŞ SAHNESİ (static/js/modules/flightsim_holiday3d.js; docs/bayram-temalari.md › Uçuş sahnesi) tarayıcısız testi:
//   • engel bölgeleri (pist + uç koridoru, ev, düzenek, saha, yer kamerası, alçak hedef yörüngesi, dış bölgeler: FPV kapıları / karşılaşma başlangıcı)
//   • yerleşim kuralları: 20 tema × 4 kalite × 4 pist yönü × gündüz/gece — tampon, yükseklik (≤ 4 m; direk ≤ 8 m ve ≥ 30 m), evden ≤ MAX_R, fişek ufukta
//   • sayı sınırları + kalite kademesi (Düşük az, Ultra çok), ikincil tema yarım/büyük figürsüz, ayar kuralı (genel kapalı → 3B kapalı; ?bayram= önizleme)
//   • gerçek three.js ile kurulum (node; WebGL yok): üçgen bütçesi ≤ 20 000, sınır kutusu yükseklikleri, kare güncellemesi < 2 ms, koyunlar çayırda
//   • bağlantılar: flightsim3d kancası (çarpışma listesine eklenmez), HEPGO/SIMUMAV ayar + i18n, dışa aktarma manifesti deseni
// Çalıştırma: node tests/test_flightsim_holiday3d.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const M = await import(pathToFileURL(join(ROOT, 'static/js/modules/flightsim_holiday3d.js')).href);
const T = await import(pathToFileURL(join(ROOT, 'static/vendor/three/three.module.min.js')).href);
const { THEMES } = await import(pathToFileURL(join(ROOT, 'static/js/modules/holiday_fx.js')).href);
const { DECOR, CAPS, LEVELS, keepoutZones, clearOf, planDecor, decorCaps, holidayDecorEnabled, holidayDecorSpec, createHolidayDecor, runwayFrame } = M;
const read = p => readFileSync(join(ROOT, p), 'utf8');
let n = 0;
const test = async (name, fn) => { await fn(); n++; console.log('  ✓', name); };

const BASE = { runwayL: 1200, runwayW: 40, camSpot: { x: 45, y: -70 } };
const HEADINGS = [0, 37, 90, 215];
const TIMES = ['day', 'night'];
function checkPlan(plan, ctx, label) {
  const zones = keepoutZones(ctx);
  for (const it of plan.items) {
    const tag = `${label} ${it.theme}/${it.kind}`;
    if (it.far) {   // havai fişek: ufukta, yalnız gece/akşam, Düşük'te yok
      assert.equal(it.kind, 'fireworks', tag);
      assert.ok(it.dist >= DECOR.FW_MIN, `${tag} fişek uzaklığı ${it.dist}`);
      assert.ok(ctx.time === 'night' || ctx.time === 'dusk', tag);
      assert.notEqual(plan.level, 'low', tag);
      continue;
    }
    if (it.onRoof) { assert.ok(it.h <= DECOR.ROOF_H, tag); for (const p of it.pts) assert.ok(clearOf(zones, p.x, p.y, 1), `${tag} çatı bayrağı bölgede`); continue; }
    assert.ok(Math.hypot(it.x, it.y) + it.r <= DECOR.MAX_R + 1e-6, `${tag} evden uzak ${Math.hypot(it.x, it.y)}`);
    assert.ok(clearOf(zones, it.x, it.y, it.r), `${tag} engel bölgesine değiyor (${it.x.toFixed(1)}, ${it.y.toFixed(1)}, r ${it.r})`);
    if (it.kind === 'flags') {
      assert.ok(it.h <= DECOR.POLE_H, tag);
      for (const p of it.pts) {
        assert.ok(Math.hypot(p.x, p.y) >= DECOR.POLE_MIN, `${tag} direk evden ≥ 30 m`);
        if (ctx.rig) assert.ok(Math.hypot(p.x - ctx.rig.x, p.y - ctx.rig.y) >= DECOR.POLE_MIN, `${tag} direk düzenekten ≥ 30 m`);
      }
    } else assert.ok(it.h <= DECOR.MAX_H, `${tag} yükseklik ${it.h}`);
    if (!it.anchors) for (const p of it.pts || []) assert.ok(Math.hypot(p.x - it.x, p.y - it.y) <= it.r + 1e-6, `${tag} küme noktası taşıyor`);   // kelebek: ağaç ankrajları (ağaçlar ayrı denetlenir)
    if (it.kind === 'string') for (const [x, y] of [[it.x1, it.y1], [it.x2, it.y2]]) assert.ok(Math.hypot(x - it.x, y - it.y) <= it.r, `${tag} direk dışarıda`);
  }
  // öğeler birbirine binmez (küme merkezleri)
  const base = plan.items.filter(it => !it.far && !it.onRoof && !['gifts', 'snow', 'eggs', 'bunny', 'butterflies'].includes(it.kind));
  for (let i = 0; i < base.length; i++) for (let j = i + 1; j < base.length; j++) {
    const a = base[i], b = base[j];
    assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r, `${label} ${a.kind}/${b.kind} çakışıyor`);
  }
}

console.log('engel bölgeleri');
await test('pist + uç koridoru, ev, düzenek, saha, yer kamerası, alçak hedef yörüngesi (halka), dış bölgeler', () => {
  const z = keepoutZones({ ...BASE, heading: 0, rig: { x: 0, y: -12 }, site: [{ x: 200, y: 50 }], targets: [{ x: -300, y: 0, r: 100, alt: 20 }, { x: 300, y: 300, r: 50, alt: 120 }], extra: [{ x: -80, y: 40, r: 5 }] });
  assert.equal(clearOf(z, 0, 300), false, 'pist üstü');
  assert.equal(clearOf(z, 0, 780), false, 'pist ucu koridoru (600 + 200)');
  assert.equal(clearOf(z, 30, 0), false, 'pist kenarı tamponu (20 + 25)');
  assert.equal(clearOf(z, 70, 100), true, 'pist yanı serbest');
  assert.equal(clearOf(z, 200, 70), false, '§26 saha');
  assert.equal(clearOf(z, 45, -70), false, 'yer kamerası');
  assert.equal(clearOf(z, -300 + 100, 10), false, 'hedef yörüngesi halkası');
  assert.equal(clearOf(z, -300, 20), true, 'halkanın içi (yörünge dışı) serbest');
  assert.equal(clearOf(z, 350, 300), true, 'yüksek hedef (120 m) bölge değil');
  assert.equal(clearOf(z, -80, 40), false, 'dış engel (FPV kapısı)');
  assert.equal(clearOf(z, -80, 40 + 5 + DECOR.ZONE_PAD + 0.5), true, 'dış engel payı');
  const z90 = keepoutZones({ ...BASE, heading: 90 });
  assert.equal(clearOf(z90, 500, 0), false, '90°: pist doğu-batı');
  assert.equal(clearOf(z90, 0, 70), true, '90°: kuzey yanı serbest');
  const f = runwayFrame(37), w = f.toWorld(10, -4), b = f.toFrame(w.x, w.y);
  assert.ok(Math.abs(b.u - 10) < 1e-9 && Math.abs(b.v + 4) < 1e-9, 'pist çerçevesi gidiş-dönüş');
});

console.log('yerleşim kuralları');
await test('20 tema × 4 kalite × 4 pist yönü × gündüz/gece: tampon, yükseklik, uzaklık, çakışma yok', () => {
  let total = 0;
  for (const th of THEMES) for (const level of LEVELS) for (const heading of HEADINGS) for (const time of TIMES) {
    const ctx = { ...BASE, heading, level, time, seed: 7, rig: heading === 37 ? { x: -60, y: 20 } : null, site: heading === 90 ? [{ x: 40, y: 90 }] : [], roofs: [{ x: 400, y: 420, z: 18 }, { x: -500, y: 300, z: 9 }] };
    const plan = planDecor([th], ctx);
    assert.ok(plan.items.length > 0, `${th} ${level} ${heading} boş plan`);
    checkPlan(plan, ctx, `${th} ${level} ${heading}° ${time}`);
    total += plan.items.length;
  }
  assert.ok(total > 600);
});
await test('birleşik tema (ana + ikincil): ikincil yarı sayıda, büyük figürsüz; kurallar korunur', () => {
  const ctx = { ...BASE, heading: 0, level: 'high', time: 'day', seed: 3 };
  const p = planDecor(['kurban', 'cocuk_genclik'], ctx);
  checkPlan(p, ctx, 'kurban+çocuk');
  assert.ok(p.items.some(i => i.kind === 'sheep'));
  assert.ok(!p.items.some(i => i.kind === 'kite_stand'), 'ikincilde uçurtma standı yok');
  const solo = decorCaps(planDecor(['cocuk_genclik'], ctx)).balloons, sec = decorCaps(p).balloons;
  assert.ok(sec < solo, `ikincil balon ${sec} < ${solo}`);
  assert.ok(!planDecor(['noel', 'ramazan'], ctx).items.some(i => i.kind === 'hilal'), 'ikincil ramazanda tabela yok');
  assert.ok(!planDecor(['bagimsizlik', 'noel'], ctx).items.some(i => i.kind === 'xmas_tree'), 'ikincil noelde ağaç yok');
  assert.equal(planDecor(['kurban', 'noel', 'paskalya'], ctx).themes.length, 2, 'en çok iki tema');
  assert.equal(planDecor(['yok-boyle'], ctx).items.length, 0);
});
await test('sayı sınırları + kalite kademesi (koyun Düşük 6 · Orta 8 · Yüksek 10 · Ultra 12)', () => {
  const sheep = LEVELS.map(level => decorCaps(planDecor(['kurban'], { ...BASE, heading: 0, level, seed: 1 })).sheep);
  assert.deepEqual(sheep, [6, 8, 10, 12]);
  for (const th of THEMES) {
    const sizes = LEVELS.map(level => Object.entries(decorCaps(planDecor([th], { ...BASE, heading: 0, level, time: 'night', seed: 5 }))).reduce((s, [k, v]) => s + (k === 'strings' ? 0 : v), 0));
    for (let i = 1; i < sizes.length; i++) assert.ok(sizes[i] >= sizes[i - 1], `${th} kademe ${sizes}`);
    const c = decorCaps(planDecor([th], { ...BASE, heading: 0, level: 'ultra', time: 'night', seed: 5, roofs: Array.from({ length: 9 }, (_, i) => ({ x: 400 + i * 30, y: 400, z: 10 })) }));
    const lim = { sheep: CAPS.sheep, pumpkins: CAPS.pumpkins, eggs: CAPS.eggs, gifts: CAPS.gifts, flags: CAPS.flags, roof_flags: CAPS.roofFlags, diyas: CAPS.diyas, stains: CAPS.stains, balloons: CAPS.balloons * 5, bed: CAPS.beds,
      blossom: CAPS.blossom, strings: CAPS.lanternString, bunny: CAPS.bunny };
    for (const [k, v] of Object.entries(c)) if (lim[k] != null) assert.ok(v <= lim[k], `${th} ${k} ${v} > ${lim[k]}`);
    if (c.string) assert.ok(c.string <= CAPS.lanternString * CAPS.lanterns);
  }
  assert.ok(!planDecor(['yilbasi'], { ...BASE, level: 'low', time: 'night' }).items.some(i => i.kind === 'fireworks'), 'Düşük: fişek yok');
  assert.ok(!planDecor(['yilbasi'], { ...BASE, level: 'high', time: 'day' }).items.some(i => i.kind === 'fireworks'), 'gündüz: fişek yok');
  assert.ok(planDecor(['yilbasi'], { ...BASE, level: 'high', time: 'night', far: 3000 }).items.some(i => i.kind === 'fireworks'), 'gece: fişek ufukta');
  assert.ok(!planDecor(['bahar'], { ...BASE, level: 'low' }).items.some(i => i.kind === 'butterflies'), 'Düşük: kelebek yok');
});
await test('dış engel bölgesi (FPV kapısı / karşılaşma başlangıcı) ve engelli zemin (su/bina) süsü iter; deterministik', () => {
  const ctx = { ...BASE, heading: 0, level: 'high', seed: 11 };
  const a = planDecor(['kurban'], ctx), a2 = planDecor(['kurban'], ctx);
  assert.deepEqual(a.items, a2.items, 'aynı bağlam → aynı yerleşim');
  const p = a.items.find(i => i.kind === 'sheep');
  const b = planDecor(['kurban'], { ...ctx, extra: [{ x: p.x, y: p.y, r: 6 }] });
  const q = b.items.find(i => i.kind === 'sheep');
  assert.ok(q && Math.hypot(q.x - p.x, q.y - p.y) >= q.r + 6, 'çayır kapıdan uzaklaştı');
  const c = planDecor(['kurban'], { ...ctx, blocked: (x, y) => x > 0 });   // doğu yarısı su
  assert.ok(c.items.every(i => i.x + i.r <= 0.001), 'su/bina üstüne konmaz');
  const none = planDecor(['kurban'], { ...ctx, blocked: () => true });
  assert.equal(none.items.length, 0, 'yer yoksa süs yok (zorlama yok)');
});
await test('ayar kuralı: genel bayram teması kapalı → 3B süs de kapalı; ayrı aç/kapa; ?bayram= önizlemesi her zaman', async () => {
  assert.equal(holidayDecorEnabled({}), true, 'varsayılan açık');
  assert.equal(holidayDecorEnabled({ enabled: false, enabled3d: true }), false);
  assert.equal(holidayDecorEnabled({ enabled: true, enabled3d: false }), false);
  assert.equal(holidayDecorEnabled({ enabled: false, enabled3d: false, preview: true }), true);
  const fetchFn = async () => ({ ok: true, json: async () => ({ active: [{ theme: 'kurban', country: 'TR', name: 'Kurban Bayramı' }, { theme: 'cocuk_genclik', country: 'TR' }] }) });
  assert.deepEqual((await holidayDecorSpec({ country: 'TR', fetchFn, search: '' })).themes, ['kurban', 'cocuk_genclik']);
  assert.equal(await holidayDecorSpec({ country: 'TR', fetchFn, search: '', enabled: false }), null);
  assert.equal(await holidayDecorSpec({ country: 'TR', fetchFn, search: '', enabled3d: false }), null);
  const pv = await holidayDecorSpec({ country: 'TR', fetchFn, search: '?bayram=noel', enabled: false, enabled3d: false });
  assert.deepEqual(pv.themes, ['noel']); assert.equal(pv.preview, true);
  const empty = async () => ({ ok: true, json: async () => ({ active: [] }) });
  assert.equal(await holidayDecorSpec({ country: 'TR', fetchFn: empty, search: '' }), null, 'bugün bayram yok');
  let set = null;
  const fakeSim = { setHoliday: s => { set = s; return { ok: 1 }; } };
  assert.deepEqual(await M.applyHolidayDecor(fakeSim, { country: 'DE', fetchFn, search: '?bayram=cadilar' }), { ok: 1 });
  assert.deepEqual(set.themes, ['cadilar']);
});

console.log('three.js kurulumu (node)');
const zMaxOf = obj => { const b = new T.Box3().setFromObject(obj, true); return b.isEmpty() ? null : b.max.z; };
await test('20 tema × Ultra/gece: üçgen ≤ 20 000, yükseklik sınırları, ışık kaynağı yok, kare < 2 ms, dispose', () => {
  for (const th of THEMES) for (const time of ['day', 'night']) {
    const scene = new T.Scene();
    const L = createHolidayDecor(T, scene, { terrainHeight: () => 0 });
    const ctx = { ...BASE, heading: 23, level: 'ultra', time, seed: 9, roofs: [{ x: 400, y: 420, z: 18 }] };
    const info = L.place([th], 'TR', ctx);
    assert.ok(info.tris <= DECOR.TRI_MAX, `${th} üçgen ${info.tris}`);
    assert.ok(info.draws <= 60, `${th} çizim ${info.draws}`);
    let lights = 0;
    scene.traverse(o => { if (o.isLight) lights++; });
    assert.equal(lights, 0, 'süs ışık kaynağı eklemez (malzeme yeniden derlemesi yok)');
    const roofXY = new Set((ctx.roofs || []).map(r => `${r.x},${r.y}`));
    L.root.updateMatrixWorld(true);
    for (const o of L.root.children) {
      if (o.isPoints && o.name === 'havai-fisek') continue;
      const z = zMaxOf(o);
      if (z == null) continue;
      const onRoof = roofXY.has(`${o.position.x},${o.position.y}`) || z > DECOR.POLE_H + 0.5;
      if (onRoof) { assert.ok(z <= 18 + DECOR.ROOF_H + 0.6, `${th} çatı bayrağı ${z}`); continue; }
      const pole = th === 'bagimsizlik' || th === 'genel';
      assert.ok(z <= (pole ? DECOR.POLE_H : DECOR.MAX_H) + 0.35, `${th} ${o.type} ${o.name} tepe ${z.toFixed(2)} m`);
    }
    for (let i = 0; i < 40; i++) L.update(1000 + i * 16, 0.016, { wind: { ms: 6, dir: 200 } });
    const t0 = performance.now();
    for (let i = 0; i < 200; i++) L.update(2000 + i * 16, 0.016, { wind: { ms: 6, dir: 200 } });
    const per = (performance.now() - t0) / 200;
    assert.ok(per < DECOR.MS_MAX, `${th} kare ${per.toFixed(3)} ms`);
    L.dispose();
    assert.equal(scene.children.length, 0, 'dispose kökü kaldırır');
  }
});
await test('koyunlar çayırda kalır, otlar/yürür; eğimli arazide zemine oturur; kalite Düşük → hale yok', () => {
  const scene = new T.Scene(), th = (x, y) => 0.05 * x + 0.02 * y;
  const L = createHolidayDecor(T, scene, { terrainHeight: th });
  L.place(['kurban'], 'TR', { ...BASE, heading: 0, level: 'high', seed: 4 });
  const it = L.plan.items.find(i => i.kind === 'sheep');
  const states = new Set();
  for (let i = 0; i < 3000; i++) { L.update(i * 33, 0.033); if (i % 50 === 0) for (const s of L.sheepState()) { states.add(s.st); assert.ok(Math.hypot(s.x - it.x, s.y - it.y) <= it.r - 2 + 1e-6, 'çayır dışına çıktı'); } }
  assert.ok(states.has('walk') && states.has('graze'), [...states].join(','));
  const body = L.root.children.find(o => o.isInstancedMesh && o.count === it.n);
  const m = new T.Matrix4(), p = new T.Vector3();
  for (let i = 0; i < it.n; i++) { body.getMatrixAt(i, m); p.setFromMatrixPosition(m); const dz = p.z - th(p.x, p.y); assert.ok(dz > 0.4 && dz < 1.1, `gövde zeminden ${dz.toFixed(2)}`); }
  L.place(['ramazan'], 'TR', { ...BASE, heading: 0, level: 'low', time: 'night' });
  assert.ok(!L.root.children.some(o => o.isPoints), 'Düşük: hale noktası yok');
  L.place(['ramazan'], 'TR', { ...BASE, heading: 0, level: 'high', time: 'night' });
  assert.ok(L.root.children.some(o => o.isPoints), 'Yüksek: hale');
  L.place([], null, BASE);
  assert.equal(L.root.children.length, 0, 'boş tema → temiz');
  L.dispose();
});
await test('Google 3B: karolar gelince ankraj yüksekliği değişirse yeniden oturur', () => {
  const scene = new T.Scene(); let h0 = 0;
  const L = createHolidayDecor(T, scene, { terrainHeight: () => h0 });
  L.place(['noel'], 'DE', { ...BASE, heading: 0, level: 'high', google: true });
  const z1 = zMaxOf(L.root);
  h0 = 12;
  L.update(5000, 0.016);
  const z2 = zMaxOf(L.root);
  assert.ok(Math.abs(z2 - z1 - 12) < 0.5, `${z1} → ${z2}`);
  L.dispose();
});

console.log('bağlantılar');
await test('flightsim3d kancası: tembel yükleme, setHoliday/setDecorKeepouts, çarpışma listesine eklenmez, kare + dispose', () => {
  const s = read('static/js/modules/flightsim3d.js');
  assert.ok(/import\('\.\/flightsim_holiday3d\.js'\)/.test(s), 'tembel import');
  assert.ok(!/^import .*flightsim_holiday3d/m.test(s), 'statik import yok');
  for (const k of ['setHoliday,', 'setDecorKeepouts:', 'holidayInfo:', 'hol.layer.update(now, rawDt', 'hol.layer?.dispose()', 'hol.gen++']) assert.ok(s.includes(k), k);
  const blk = s.slice(s.indexOf('// ---------- bayram süsleri'), s.indexOf('async function setHoliday'));
  assert.ok(blk.length > 200 && !/buildingsAABB\.push|coll\.|onCollision/.test(blk), 'süs engel/çarpışma listesine girmez');
  const m = read('static/js/modules/flightsim_holiday3d.js');
  assert.ok(!/buildingsAABB\.push|new T\.(PointLight|SpotLight|DirectionalLight|WebGLRenderer)/.test(m), 'modül çarpışma kutusu/ışık/renderer kurmaz');
});
await test('uygulamalar: HEPGO Kişisel Ayarlar + SIMUMAV Ayarlar aç/kapa, oturumlarda uygulanır, i18n 6 + 7 dil, dışa aktarma deseni', () => {
  const hs = read('static/js/modules/settings.js');
  assert.ok(hs.includes('scene3d: true') && hs.includes("'Uçuş sahnesinde bayram süsleri'"));
  for (const l of ['en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const t = read(`static/js/i18n.${l}.js`);
    for (const k of ['Uçuş sahnesinde bayram süsleri', 'Uçuş sahnesi bayram süsleri açıldı', 'Uçuş sahnesi bayram süsleri kapatıldı']) assert.ok(t.includes(`"${k}"`), `${l}: ${k}`);
  }
  const fs = read('static/js/modules/flightsim.js');
  assert.ok(fs.includes('attachHolidayDecor(sim)') && fs.includes("import('./flightsim_holiday3d.js')"));
  const ss = read('static/simumav/app/fly/session.js');
  assert.ok(ss.includes('flightsim_holiday3d.js') && ss.includes("setDecorKeepouts?.('gates'") && ss.includes('holiday_3d'));
  const st = read('static/simumav/app/settings/index.js');
  assert.ok(st.includes("t('settings.holiday_3d')") && st.includes('holiday_3d: v'));
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const j = JSON.parse(read(`static/simumav/app/i18n/${l}.json`));
    assert.ok(j['settings.holiday_3d'] && j['settings.holiday_3d_sub'], l);
  }
  const ex = read('tools/simumav_export.py');
  assert.ok(ex.includes("'static/js/modules/flightsim*.js'") && ex.includes("'static/js/modules/holiday_*.js'"), 'manifest flightsim*.js + holiday_*.js');
  assert.ok(read('docs/bayram-temalari.md').includes('Uçuş sahnesi'));
});

console.log(`test_flightsim_holiday3d.mjs: ${n} test TAMAM`);
