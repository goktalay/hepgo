// Uçuş Simülatörü §31 — hava durumu / rüzgâr / rampa saf kuralları (static/js/modules/flightsim_weather.js) ve rüzgâr göstergesi metinleri
// (flightsim_windui.js componentText / windWarn / makeWfxT). Tarayıcısız. Çalıştırma: node tests/test_flightsim_worldfx.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CROSSWIND_MAX, RAMP_LIMITS, SIMUMAV_WEATHER, TAILWIND_MAX, WEATHER, WEATHER_LABELS, WEATHER_PRESETS, WIND_LIMITS, compassName, fogRange, gustFactor, gustSpeed,
  intoWindHeading, normRampAim, normWeather, precipParams, rampChange, rampEditable, rampHeading, sockState, streakParams, sunPosition, takeoffAdvice, weatherFromTrack,
  weatherPreset, windComponents, windVector } from '../static/js/modules/flightsim_weather.js';
import { WFX_TEXTS, componentText, makeWfxT, windWarn } from '../static/js/modules/flightsim_windui.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) <= e, `${a} ≈ ${b}`);

test('hava ön ayarları: 6 tür, her birinde tüm alanlar; bilinmeyen → açık; SIMUMAV parkuru birebir', () => {
  assert.deepEqual(WEATHER, ['clear', 'cloudy', 'rain', 'snow', 'fog', 'storm']);
  for (const k of WEATHER) { const p = WEATHER_PRESETS[k]; for (const f of ['cloud', 'rain', 'snow', 'wet', 'snowCover', 'light', 'vis', 'haze']) assert.ok(p[f] >= 0 && p[f] <= 1, `${k}.${f}`); assert.ok(WEATHER_LABELS[k]); }
  assert.equal(normWeather('hail'), 'clear'); assert.equal(weatherPreset(undefined).key, 'clear');
  assert.ok(WEATHER_PRESETS.storm.lightning && !WEATHER_PRESETS.rain.lightning);
  assert.ok(WEATHER_PRESETS.rain.wet === 1 && WEATHER_PRESETS.snow.snowCover === 1 && WEATHER_PRESETS.clear.wet === 0);
  for (const w of SIMUMAV_WEATHER) assert.equal(weatherFromTrack(w), w);
  assert.equal(weatherFromTrack('storm'), 'clear');   // SIMUMAV parkurunda fırtına yok (bridge.WEATHER)
  // sunucu WEATHER ile aynı liste
  const py = readFileSync(new URL('../app/flightsim.py', import.meta.url), 'utf8');
  assert.match(py, /WEATHER = \('clear', 'cloudy', 'rain', 'snow', 'fog', 'storm'\)/);
  assert.match(readFileSync(new URL('../app/simumav/bridge.py', import.meta.url), 'utf8'), /WEATHER = \('clear', 'cloudy', 'rain', 'fog', 'snow'\)/);
});

test('görüş: açık havada eski formülle aynı (prosedürel ve ufuk), sis ≤ 900 m, yağmur/kar kısar, fog 0 + açık → sis yok', () => {
  for (const fog of [0.1, 0.2, 0.6, 1]) {
    near(fogRange(fog, 'clear', { size: 4000 }).far, 4000 * (1.6 - 1.25 * fog));
    near(fogRange(fog, 'clear', { horizon: 24000 }).far, 24000 * (1.25 - fog));
    near(fogRange(fog, 'clear', { horizon: 24000 }).near, 24000 * (1.25 - fog) * 0.12);
  }
  assert.equal(fogRange(0, 'clear', { size: 4000 }).on, false);
  assert.equal(fogRange(0, 'rain', { size: 4000 }).on, true);
  assert.ok(fogRange(0.2, 'fog', { horizon: 24000 }).far <= 900);
  assert.ok(fogRange(0.2, 'rain', { horizon: 24000 }).far < fogRange(0.2, 'cloudy', { horizon: 24000 }).far);
  assert.ok(fogRange(0.2, 'snow', { horizon: 24000 }).far < fogRange(0.2, 'clear', { horizon: 24000 }).far);
  assert.ok(fogRange(1, 'fog', { size: 1000 }).far >= 180);
});

test('yağış: yağmur çizgi / kar tanesi, kaliteyle ölçeklenir; açık/bulutlu/sis yağışsız', () => {
  const r = precipParams('rain'), s = precipParams('snow'), st = precipParams('storm');
  assert.equal(r.kind, 'rain'); assert.equal(s.kind, 'snow'); assert.equal(st.kind, 'rain');
  assert.ok(st.count > r.count && r.fall > s.fall && s.len === 0);
  assert.ok(precipParams('rain', { quality: 0.25 }).count < r.count / 3);
  for (const w of ['clear', 'cloudy', 'fog']) assert.equal(precipParams(w), null);
});

test('güneş konumu: gündüz yüksek, akşam ufukta (batıya yakın), gece ay; birim vektör', () => {
  const d = sunPosition('day'), k = sunPosition('dusk'), g = sunPosition('night');
  assert.ok(d.elev > 40 && k.elev < 10 && g.moon && !d.moon);
  assert.ok(k.az > 225 && k.az < 290);
  for (const p of [d, k, g]) near(Math.hypot(p.x, p.y, p.z), 1, 1e-9);
});

test('rüzgâr vektörü (SIM_WIND_DIR: geldiği yön) ve baş/yan/kuyruk bileşenleri', () => {
  const v = windVector(10, 270);   // batıdan esen → doğuya akar
  near(v.x, 10); near(v.y, 0); near(windVector(5, 0).y, -5);
  let c = windComponents(10, 0, 0);   // burun kuzey, rüzgâr kuzeyden → tam baş rüzgârı
  near(c.head, 10); near(c.cross, 0); assert.equal(c.kind, 'head');
  c = windComponents(10, 180, 0); near(c.head, -10); assert.equal(c.kind, 'tail');
  c = windComponents(10, 90, 0); near(c.cross, 10); assert.equal(c.side, 'R'); assert.equal(c.kind, 'cross');   // doğudan (sağdan)
  c = windComponents(10, 270, 0); near(c.cross, -10); assert.equal(c.side, 'L');
  c = windComponents(8, 300, 20); near(c.rel, -80); near(c.head, 8 * Math.cos(-80 * Math.PI / 180), 0.01);
  assert.equal(windComponents(0.1, 0, 0).kind, 'calm');
  assert.equal(windComponents(5, 350, 10).rel, -20);   // sarma
});

test('rüzgâra karşı kalkış önerisi: yön = geldiği yön (5°), kuyruk > 1 / yan > 6 m/s uygun değil', () => {
  assert.equal(intoWindHeading(272), 270); assert.equal(intoWindHeading(358), 0); assert.equal(intoWindHeading(-10), 350);
  let a = takeoffAdvice(6, 270, 270); assert.ok(a.ok && !a.worth && a.off === 0);
  a = takeoffAdvice(6, 270, 90); assert.ok(!a.ok && a.worth && a.suggest === 270 && a.head < -TAILWIND_MAX);
  a = takeoffAdvice(10, 0, 90); assert.ok(!a.ok && Math.abs(a.cross) > CROSSWIND_MAX);
  a = takeoffAdvice(0, 0, 90); assert.ok(a.ok && !a.worth);
});

test('esinti çarpanı: [0,1], sunucu esinti_carpani ile aynı tablo, anlık hız = taban + gust·g', () => {
  for (const [t, g] of [[0, 0.25], [3.2, 0.3184], [7.7, 0.0256], [12.5, 0.2581]]) near(gustFactor(t), g, 1e-4);
  const gs = Array.from({ length: 400 }, (_, i) => gustFactor(i * 0.25));
  assert.ok(Math.min(...gs) >= 0 && Math.max(...gs) <= 1 && Math.max(...gs) > 0.8 && Math.min(...gs) < 0.05);
  near(gustSpeed(5, 4, 3.2), +(5 + 4 * 0.3184).toFixed(2), 1e-9);
  assert.equal(gustSpeed(5, 0, 3.2), 5);
  // Python formülü aynı katsayılarla (11.3 / 4.7 / 1.9; 0.55 / 0.3 / 0.15; tohum 0.7311)
  const py = readFileSync(new URL('../app/flightsim.py', import.meta.url), 'utf8');
  assert.match(py, /0\.55 \* math\.sin\(2 \* math\.pi \* t \/ 11\.3 \+ s\)/); assert.match(py, /0\.15 \* math\.sin\(2 \* math\.pi \* t \/ 1\.9 \+ 3\.3 \* s\)/);
});

test('rüzgâr tulumu (15 kt = 7,7 m/s tam açık) ve akış çizgileri (rüzgârla sayı/uzunluk/saydamlık)', () => {
  assert.equal(sockState(0).inflation, 0.12); assert.equal(sockState(7.7).inflation, 1); assert.equal(sockState(20).inflation, 1);
  assert.ok(sockState(0).droop > 60 && sockState(10).droop === 0);
  assert.ok(sockState(3).inflation > sockState(1).inflation && sockState(12).flutter > sockState(2).flutter);
  assert.equal(streakParams(0.2).on, false);
  const a = streakParams(3), b = streakParams(12);
  assert.ok(a.on && b.count > a.count && b.len > a.len && b.alpha > a.alpha && b.count <= 420 && b.alpha <= 0.55);
});

test('rampa yön/açı: sınırlar (10–30°, 0–359°), varsayılan yön pist, yön değişince yeniden konuşlandırma, yalnız ARM öncesi', () => {
  assert.deepEqual(RAMP_LIMITS, { angle: [10, 30], azimuth: [0, 359] });
  assert.deepEqual(normRampAim({ azimuth_deg: 365, angle_deg: 40 }), { azimuth_deg: 5, angle_deg: 30 });
  assert.deepEqual(normRampAim({ angle_deg: 3 }, 120), { azimuth_deg: 120, angle_deg: 10 });
  assert.deepEqual(normRampAim({ azimuth_deg: -90, angle_deg: 17.3 }), { azimuth_deg: 270, angle_deg: 17.5 });
  assert.equal(rampHeading({ method: 'ramp' }, 40), 40); assert.equal(rampHeading({ method: 'ramp', azimuth_deg: 200 }, 40), 200);
  let c = rampChange({ angle_deg: 15 }, { azimuth_deg: 40, angle_deg: 20 }, 40);
  assert.ok(!c.redeploy && c.angleChanged && !c.azimuthChanged);
  c = rampChange({ angle_deg: 15, azimuth_deg: 40 }, { azimuth_deg: 220 }, 0);
  assert.ok(c.redeploy && c.azimuthChanged && !c.angleChanged && c.azimuth_deg === 220);
  assert.equal(rampChange({ azimuth_deg: 359 }, { azimuth_deg: 359 }).redeploy, false);
  assert.ok(rampEditable({ armed: false, altRel: 0, phase: null }) && rampEditable({ phase: 'idle' }));
  assert.ok(!rampEditable({ armed: true }) && !rampEditable({ altRel: 3 }) && !rampEditable({ phase: 'launch' }));
  // sunucu sınırlarıyla aynı (launch_dogrula / rampa_aim_dogrula)
  const py = readFileSync(new URL('../app/flightsim.py', import.meta.url), 'utf8');
  assert.match(py, /\('azimuth_deg', 0, 359\.99\), \('angle_deg', 10, 30\)/);
  assert.deepEqual(WIND_LIMITS, { ms: [0, 30], dir: [0, 359.99], gust: [0, 20], turb: [0, 10] });
  assert.match(py, /'wind_gust': \(float, 0, 20\), 'wind_turb': \(float, 0, 10\)/);
});

test('gösterge metinleri: bileşen metni, uyarı düzeyi, pusula adı, SIMUMAV anahtarları (wfx.*) 7 dilde', () => {
  const T = makeWfxT(null);
  assert.equal(componentText(windComponents(6, 0, 0), T), 'Baş 6.0 · Yan 0.0');
  assert.equal(componentText(windComponents(6, 180, 0), T), 'Kuyruk 6.0 · Yan 0.0');
  assert.equal(componentText(windComponents(8, 300, 270), T), 'Baş 6.9 · Yan 4.0 sağdan');
  assert.equal(componentText(windComponents(8, 240, 270), T), 'Baş 6.9 · Yan 4.0 soldan');
  assert.equal(componentText(windComponents(0, 0, 0), T), 'Sakin');
  assert.equal(windWarn(windComponents(6, 180, 0)), 'tail'); assert.equal(windWarn(windComponents(8, 90, 0)), 'cross'); assert.equal(windWarn(windComponents(4, 20, 0)), '');
  assert.equal(compassName(0), 'K'); assert.equal(compassName(270), 'B'); assert.equal(compassName(135), 'GD'); assert.equal(compassName(-90), 'B');
  const keyed = makeWfxT(k => (k === 'wfx.head' ? 'Head' : k), true);
  assert.equal(keyed('wfx.head'), 'Head'); assert.equal(keyed('wfx.tail'), 'Kuyruk');   // anahtar yoksa Türkçe
  for (const l of ['tr', 'en', 'de', 'fr', 'es', 'ru', 'ar']) {
    const d = JSON.parse(readFileSync(new URL(`../static/simumav/app/i18n/${l}.json`, import.meta.url), 'utf8'));
    for (const [k] of WFX_TEXTS) assert.ok(d[k], `${l}.json ${k}`);
  }
});

console.log(`\n${n} test geçti (flightsim_weather + flightsim_windui).`);
