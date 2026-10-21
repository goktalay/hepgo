// Uçuş Simülatörü uçuş arayüzü saf testleri (HEPGO + SIMUMAV ortak):
//  §27.1 kumanda hassasiyeti (flightsim_rcfeel.js) · §27.4 yüzen radar/EO pencere yerleşimi (flightsim_dock.js) ·
//  §27.3 gösterge tasarımı (flightsim_gtheme.js) · §27.2 giriş sekansı (flightsim_intro.js) · SIMUMAV rc.js eğri entegrasyonu.
// Çalıştırma: node tests/test_flightsim_flyui.mjs
import assert from 'node:assert/strict';
import { RCFEEL_DEFAULTS, RCFEEL_LIMITS, RCFEEL_PRESETS, RCFEEL_TEXTS, RC_AXES, curvePoints, loadFeel, makeShaper, normFeel, presetOf, saveFeel, shapeAxis } from '../static/js/modules/flightsim_rcfeel.js';
import { WIN_MIN_W, avoidRects, boundsOf, clampRect, fromFrac, normWin, overlaps, resizeW, sizeFor, snapRect, toFrac, winMaxW } from '../static/js/modules/flightsim_dock.js';
import { GAUGE_THEMES, GAUGE_THEME_DEFAULT, GAUGE_THEME_KEYS, GTHEME_TEXTS, gaugeFrac, gaugeThemePreviewSvg, isGaugeTheme, loadGaugeTheme, makeGThemeT, nextGaugeTheme, normGaugeTheme, saveGaugeTheme } from '../static/js/modules/flightsim_gtheme.js';
import { INTRO, INTRO_TEXTS, beepPlan, countdownState, hepgoSound, introEase, introPose } from '../static/js/modules/flightsim_intro.js';
import { channelsOf } from '../static/simumav/app/fly/rc.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, e = 1e-6, m = '') => assert.ok(Math.abs(a - b) <= e, `${m} ${a} ≈ ${b}`);
const mem = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };

// ---------------------------------------------------------------- §27.1 hassasiyet ----------------------------------------------------------------
test('shapeAxis: tek fonksiyon, işaret korunur, uçlar oran kadar, merkez 0', () => {
  for (const c of [{ rate: 100, expo: 0, dead: 0 }, { rate: 70, expo: 45, dead: 4 }, { rate: 100, expo: 90, dead: 20 }]) {
    near(shapeAxis(0, c), 0); near(shapeAxis(1, c), c.rate / 100); near(shapeAxis(-1, c), -c.rate / 100);
    for (let x = -1; x <= 1; x += 0.05) near(shapeAxis(-x, c), -shapeAxis(x, c), 1e-9, 'tek');
    let prev = -Infinity; for (let x = -1; x <= 1.0001; x += 0.02) { const y = shapeAxis(x, c); assert.ok(y >= prev - 1e-12, 'monoton'); prev = y; }
  }
  near(shapeAxis(0.5, { rate: 100, expo: 0, dead: 0 }), 0.5);       // doğrusal
  near(shapeAxis(0.5, { rate: 100, expo: 100, dead: 0 }), 0.125);   // saf kübik
  near(shapeAxis(0.5, { rate: 100, expo: 50, dead: 0 }), 0.3125);
  near(shapeAxis(0.5, { rate: 60, expo: 0, dead: 0 }), 0.3);
  assert.equal(shapeAxis(0.05, { rate: 100, expo: 0, dead: 10 }), 0);   // ölü bölge
  near(shapeAxis(0.55, { rate: 100, expo: 0, dead: 10 }), 0.5);       // dışarısı yeniden ölçekli
  near(shapeAxis(2, { rate: 100 }), 1); near(shapeAxis('x', {}), 0);  // kırpma / geçersiz
});
test('normFeel: eksik → varsayılan, aralık dışı → sınır, tam sayı; dört eksen', () => {
  const f = normFeel({ roll: { rate: 500, expo: -5, dead: 3.6 }, yaw: 'bozuk' });
  assert.deepEqual(Object.keys(f), RC_AXES);
  assert.deepEqual(f.roll, { rate: RCFEEL_LIMITS.rate[1], expo: 0, dead: 4 });
  assert.deepEqual(f.yaw, RCFEEL_DEFAULTS.yaw); assert.deepEqual(normFeel(null), normFeel(RCFEEL_DEFAULTS));
  for (const p of Object.values(RCFEEL_PRESETS)) assert.deepEqual(normFeel(p), p, 'hazır ayarlar sınırlar içinde');
});
test('makeShaper: uçakta gaz doğrusal (tutmalı), kopterde eğrili; presetOf; curvePoints', () => {
  const sp = makeShaper(RCFEEL_PRESETS.soft, { plane: true }), sc = makeShaper(RCFEEL_PRESETS.soft, { plane: false });
  near(sp('thr', 0.4), 0.4); near(sp('thr', -1), -1); assert.ok(Math.abs(sc('thr', 0.4)) < 0.4);
  assert.ok(Math.abs(sp('roll', 0.3)) < 0.3 * 0.7 + 1e-9, 'yumuşak roll');
  assert.equal(presetOf(RCFEEL_PRESETS.sport), 'sport'); assert.equal(presetOf(null), 'normal');
  assert.equal(presetOf({ ...RCFEEL_PRESETS.normal, yaw: { rate: 55, expo: 20, dead: 4 } }), 'custom');
  const pts = curvePoints({ rate: 80, expo: 30, dead: 5 }, 20); assert.equal(pts.length, 21); assert.deepEqual(pts[10], [0, 0]); near(pts[20][1], 0.8);
});
test('loadFeel/saveFeel: kalıcı tercih (fs.rc.feel), bozuk JSON → varsayılan', () => {
  const st = mem();
  assert.deepEqual(loadFeel(st), normFeel(null));
  saveFeel({ ...RCFEEL_PRESETS.sport, roll: { rate: 33, expo: 12, dead: 1 } }, st);
  assert.deepEqual(loadFeel(st).roll, { rate: 33, expo: 12, dead: 1 });
  st.setItem('fs.rc.feel', '{bozuk'); assert.deepEqual(loadFeel(st), normFeel(null));
  assert.ok(RCFEEL_TEXTS.every(([k, v]) => k.startsWith('rcfeel.') && v));
});
test('SIMUMAV channelsOf: eğri çıkışa uygulanır (çubuk ve klavye aynı yoldan); eğri yoksa eski davranış', () => {
  const ax = { roll: 0.5, pitch: 0.5, thr: 0, yaw: -0.5 };
  assert.deepEqual(channelsOf(ax, 1500), [1750, 1250, 1500, 1250, 1500, 0, 0, 0]);
  const s = makeShaper({ roll: { rate: 100, expo: 90, dead: 0 }, pitch: { rate: 100, expo: 90, dead: 0 }, yaw: { rate: 50, expo: 0, dead: 0 }, thr: { rate: 100, expo: 0, dead: 0 } });
  assert.deepEqual(channelsOf(ax, 2000, s), [1581, 1419, 1500, 1375, 2000, 0, 0, 0]);
});

// ---------------------------------------------------------------- §27.4 pencere yerleşimi ----------------------------------------------------------------
const W = 1600, H = 900, A = 304 / 204, B = boundsOf(W, H, { top: 70, bottom: 70 });
test('boyut: oran korunur, en küçük / en büyük sınır; köşe tutamacı', () => {
  const s = sizeFor(400, A, { W, H, hdr: 24, bounds: B }); assert.equal(s.w, 400); assert.equal(s.h, Math.round(400 / A) + 24);
  assert.equal(sizeFor(50, A, { W, H }).w, WIN_MIN_W);
  assert.ok(sizeFor(5000, A, { W, H, hdr: 24, bounds: B }).w <= winMaxW(W, H, A, B));
  assert.ok(sizeFor(5000, A, { W, H, hdr: 24, bounds: B }).h <= B.bottom - B.top + 1, 'yüksekliğe sığar');
  assert.equal(resizeW(300, 50, 10, A), 350); near(resizeW(300, 5, 40, A), 300 + 40 * A); assert.equal(resizeW(300, 50, 0, A, 'bl'), 250);
});
test('kırpma + kenar/köşe yapışma', () => {
  assert.deepEqual(clampRect({ x: -50, y: 2000, w: 300, h: 200 }, B), { x: B.left, y: B.bottom - 200, w: 300, h: 200 });
  const s = snapRect({ x: B.right - 300 - 20, y: B.bottom - 200 - 10, w: 300, h: 200 }, B);
  assert.equal(s.x, B.right - 300); assert.equal(s.y, B.bottom - 200); assert.equal(s.sx, 'r'); assert.equal(s.sy, 'b');
  const f = snapRect({ x: 600, y: 300, w: 300, h: 200 }, B); assert.equal(f.sx, null); assert.equal(f.sy, null); assert.equal(f.x, 600);
});
test('engellerden kaçınma: çakışma yoksa yerinde; varsa en yakın boş yere; hep sınır içinde', () => {
  const pip = { x: 1200, y: 560, w: 360, h: 220 }, gauges = { x: 620, y: 640, w: 420, h: 190 };
  const r0 = { x: 300, y: 300, w: 300, h: 200 };
  assert.deepEqual(avoidRects(r0, [pip, gauges], B), r0);
  const r1 = avoidRects({ x: 1250, y: 600, w: 300, h: 200 }, [pip, gauges], B);
  assert.ok(![pip, gauges].some(o => overlaps(r1, o, 8)), 'PiP ile çakışmaz');
  assert.ok(r1.x >= B.left && r1.y >= B.top && r1.x + r1.w <= B.right && r1.y + r1.h <= B.bottom);
  assert.ok(Math.hypot(r1.x - 1250, r1.y - 600) < 400, 'en yakın aday');
  const r2 = avoidRects({ x: 700, y: 650, w: 300, h: 200 }, [pip, gauges], B);
  assert.ok(![pip, gauges].some(o => overlaps(r2, o, 8)));
  // kalabalık ekran (harekât kartı + PiP + kadranlar + diğer pencere): çok adımlı arama yakın boş yeri bulur
  const kart = { x: 1030, y: 120, w: 398, h: 670 }, pip2 = { x: 728, y: 452, w: 287, h: 160 }, g2 = { x: 455, y: 625, w: 530, h: 175 }, radar = { x: 45, y: 213, w: 465, h: 337 };
  const B2 = boundsOf(1440, 900, { top: 70, bottom: 110 });
  const r4 = avoidRects({ x: 1040, y: 525, w: 303, h: 229 }, [kart, pip2, g2, radar], B2);
  assert.ok(![kart, pip2, g2, radar].some(o => overlaps(r4, o, 8)), JSON.stringify(r4));
  assert.ok(Math.hypot(r4.x - 1040, r4.y - 525) < 460, `yakın: ${JSON.stringify(r4)}`);
  // maxMove: uzak boş yere ışınlanmaz, bırakılan yerin yakınında (en az çakışan) kalır
  const r5 = avoidRects({ x: 1125, y: 525, w: 303, h: 229 }, [kart, pip2, g2, radar], B2, 8, 4, 200);
  assert.ok(Math.hypot(r5.x - 1125, r5.y - 525) <= 200, JSON.stringify(r5));
  // tamamen dolu ekran: yine sınır içinde bir dikdörtgen döner (çökmez)
  const r3 = avoidRects({ x: 400, y: 300, w: 300, h: 200 }, [{ x: 0, y: 0, w: W, h: H }], B);
  assert.ok(Number.isFinite(r3.x) && Number.isFinite(r3.y));
});
test('oranlı kayıt: ekran boyutu değişince yapışık kenar korunur; bozuk kayıt reddedilir', () => {
  const r = snapRect({ x: B.right - 320, y: B.bottom - 230, w: 320, h: Math.round(320 / A) + 24 }, B);
  const f = toFrac(r, W, H); assert.equal(f.sx, 'r'); assert.equal(f.sy, 'b');
  const W2 = 1100, H2 = 700, B2 = boundsOf(W2, H2, { top: 70, bottom: 70 });
  const r2 = fromFrac(f, W2, H2, A, { hdr: 24, bounds: B2 });
  assert.equal(r2.x + r2.w, B2.right); assert.equal(r2.y + r2.h, B2.bottom); near(r2.w / W2, f.fw, 0.01);
  const mid = fromFrac(toFrac({ x: 500, y: 300, w: 320 }, W, H), W2, H2, A, { hdr: 24, bounds: B2 }); near(mid.x / W2, 500 / W, 0.002);
  assert.equal(fromFrac(null, W, H, A), null); assert.equal(normWin({ fx: 'a' }), null); assert.equal(normWin({ fx: 0.2, fy: 0.3, fw: 3 }), null);
  assert.deepEqual(normWin({ fx: 0.2, fy: 0.3, fw: 0.25, sx: 'x', sy: 'b' }), { fx: 0.2, fy: 0.3, fw: 0.25, sx: null, sy: 'b' });
});

// ---------------------------------------------------------------- §27.3 gösterge tasarımı ----------------------------------------------------------------
test('tema listesi ≥ 4 + doğrulama (enum) + döngü', () => {
  assert.ok(GAUGE_THEMES.length >= 4); assert.equal(GAUGE_THEME_DEFAULT, 'classic');
  assert.deepEqual(GAUGE_THEME_KEYS, ['classic', 'cockpit', 'glass', 'minimal', 'military', 'none']);
  assert.ok(isGaugeTheme('glass') && !isGaugeTheme('neon') && !isGaugeTheme(null));
  assert.equal(normGaugeTheme('<script>'), 'classic'); assert.equal(normGaugeTheme('cockpit'), 'cockpit');
  assert.equal(nextGaugeTheme('military'), 'none'); assert.equal(nextGaugeTheme('none'), 'classic'); assert.equal(nextGaugeTheme('bozuk'), 'cockpit');
  const seen = new Set(); let t = 'classic'; for (let i = 0; i < GAUGE_THEME_KEYS.length; i++) { seen.add(t); t = nextGaugeTheme(t); } assert.equal(seen.size, GAUGE_THEME_KEYS.length);
});
test('kalıcı tercih (fs.gauge.theme) + seviye şeridi doluluğu + önizleme SVG + metinler', () => {
  const st = mem(); assert.equal(loadGaugeTheme(st), 'classic'); saveGaugeTheme('minimal', st); assert.equal(loadGaugeTheme(st), 'minimal');
  saveGaugeTheme('yok', st); assert.equal(loadGaugeTheme(st), 'classic');
  assert.equal(gaugeFrac(-120), 0); assert.equal(gaugeFrac(120), 1); assert.equal(gaugeFrac(0), 0.5); assert.equal(gaugeFrac(500), 1); assert.equal(gaugeFrac(NaN), 0);
  for (const k of GAUGE_THEME_KEYS) for (const dark of [false, true]) { const s = gaugeThemePreviewSvg(k, { dark }); assert.ok(s.startsWith('<svg') && s.endsWith('</svg>') && !s.includes('NaN') && !s.includes('undefined'), k); }
  assert.notEqual(gaugeThemePreviewSvg('classic', { dark: false }), gaugeThemePreviewSvg('classic', { dark: true }), 'gün/gece önizlemesi farklı');
  const keys = new Set(GTHEME_TEXTS.map(([k]) => k)); for (const k of GAUGE_THEME_KEYS) assert.ok(keys.has(`gtheme.${k}`) && keys.has(`gtheme.${k}_desc`));
  assert.equal(makeGThemeT(null)('gtheme.cockpit'), 'Uçak kokpiti'); assert.equal(makeGThemeT(k => (k === 'gtheme.glass' ? 'Glass' : k), true)('gtheme.glass'), 'Glass');
  assert.equal(makeGThemeT(k => k, true)('gtheme.minimal'), 'Minimal / şeffaf', 'anahtar yoksa Türkçeye düşer');
});

// ---------------------------------------------------------------- §27.2 giriş sekansı ----------------------------------------------------------------
test('introPose: 100 m yüksekten başlar, normal kip ofsetinde biter, yükseklik monoton iner', () => {
  const end = { x: -4.8, y: -6.8, z: 2.8 };
  const p0 = introPose(0, { end }), p1 = introPose(1, { end });
  near(p0.z, INTRO.height, 1e-9); near(Math.hypot(p0.x, p0.y), INTRO.radius0, 1e-3);
  near(p1.x, end.x, 1e-3); near(p1.y, end.y, 1e-3); near(p1.z, end.z, 1e-3);
  let prev = Infinity; for (let u = 0; u <= 1.0001; u += 0.02) { const p = introPose(u, { end }); assert.ok(p.z <= prev + 1e-9, 'iniş'); prev = p.z; assert.ok(Number.isFinite(p.x + p.y + p.z)); }
  near(introEase(0), 0); near(introEase(1), 1); near(introEase(0.5), 0.5); assert.ok(introEase(0.05) < 0.01, 'yumuşak başlangıç');
  // spiral: başta bitiş yönünden turnDeg geride
  const a0 = Math.atan2(p0.y, p0.x), aE = Math.atan2(end.y, end.x); let d = (aE - a0) * 180 / Math.PI; while (d < -180) d += 360; while (d > 180) d -= 360; near(d, INTRO.turnDeg, 0.5);
});
test('geri sayım 3-2-1 → BAŞLA → bitti; bip planı dıt dıt dıt + farklı uzun diiit', () => {
  assert.deepEqual([0, 0.5, 1, 1.99, 2.2].map(t => countdownState(t).n), [3, 3, 2, 2, 1]);
  const g = countdownState(3.1); assert.ok(g.go && !g.done && g.n === 0);
  assert.ok(countdownState(3 + INTRO.goS + 0.01).done); assert.equal(countdownState(-5).n, 3); near(countdownState(1.25).frac, 0.25);
  const b = beepPlan(3); assert.equal(b.length, 4); assert.deepEqual(b.map(x => x.t), [0, 1, 2, 3]);
  assert.ok(b.slice(0, 3).every(x => x.f === b[0].f && x.dur < 0.2), 'kısa dıt');
  assert.ok(b[3].f !== b[0].f && b[3].dur > 3 * b[0].dur, 'son ton farklı ve uzun');
});
test('ses tercihi: HEPGO fs.audio.on / fs.audio.vol (kapalı → sessiz)', () => {
  const st = mem(); assert.deepEqual(hepgoSound(st), { on: true, vol: 0.7 });
  st.setItem('fs.audio.on', '0'); st.setItem('fs.audio.vol', '40'); assert.deepEqual(hepgoSound(st), { on: false, vol: 0.4 });
  assert.ok(INTRO_TEXTS.every(([k, v]) => k.startsWith('intro.') && v));
});

console.log(`\n${n} test geçti`);
