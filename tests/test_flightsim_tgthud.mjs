// Uçuş Simülatörü §24.4–24.5 — hedef sembolojisi + sihirbaz önizleme saf modül testleri (tarayıcısız):
//   static/js/modules/flightsim_tgthud.js (izdüşüm, balıkgözü tersi, ekran dışı yön — arka yarım küre dahil, kenar elipsi, prizma en küçük boyutu,
//   kapanma hızı, TLL kutu girişi, hedef seçimi/kilidi, symbology bütünü, çizim duman testi) · flightsim_tgtview.js (ölçek çubuğu, boyut metni)
// Çalıştırma: node tests/test_flightsim_tgthud.mjs
import assert from 'node:assert/strict';
import { camSpace, projectView, barrelScreen, screenDir, dirAngle, offAngle, edgePoint, fitMin, closureRate, rectEntry, selectTarget, lockedIndex, symbology, drawSymbology,
  boxCorners, BOX_EDGES, TD_MIN_PX, fmtRange } from '../static/js/modules/flightsim_tgthud.js';
import { niceScale, fmtSize, fmtLen } from '../static/js/modules/flightsim_tgtview.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, eps = 1e-6, msg) => assert.ok(Math.abs(a - b) <= eps, msg || `${a} ≈ ${b}`);

// Kamera: orijinde, kuzeye (+y) bakıyor; sağ = doğu (+x), yukarı = +z; dikey FOV 60°, 16:9
const V = { pos: [0, 0, 0], fwd: [0, 1, 0], right: [1, 0, 0], up: [0, 0, 1], tanV: Math.tan(30 * Math.PI / 180), aspect: 16 / 9, k: 0, scale: 1 };

console.log('flightsim_tgthud.js');
test('projectView: eksen üstü nokta merkezde; sağ/yukarı ofset ndc formülüyle; arkadaki nokta front=false', () => {
  const p = projectView(V, [0, 100, 0]); near(p.sx, 0.5); near(p.sy, 0.5); assert.equal(p.front, true);
  const q = projectView(V, [10, 100, 5]);
  near(q.sx, 0.5 + 10 / (100 * V.tanV * V.aspect) / 2); near(q.sy, 0.5 - 5 / (100 * V.tanV) / 2);
  assert.ok(q.sx > 0.5 && q.sy < 0.5, 'sağ-yukarı → ekranda sağ-üst');
  assert.equal(projectView(V, [0, -50, 0]).front, false);
  // görüş alanının üst kenarı: yc/zf = tanV → sy = 0
  near(projectView(V, [0, 100, 100 * V.tanV]).sy, 0, 1e-9);
});
test('barrelScreen: CAM_FRAG ileri formülünün tersi (q = d·(1 + k·|d|²)·scale); k = 0 → yalnız ölçek', () => {
  const k = 0.12, sc = 1 / (1 + k * 0.5);
  for (const [qx, qy] of [[0.3, -0.2], [-0.45, 0.4], [0.01, 0.02], [0.5, 0.5]]) {
    const [dx, dy] = barrelScreen(qx, qy, k, sc), f = (1 + k * (dx * dx + dy * dy)) * sc;
    near(dx * f, qx, 1e-7); near(dy * f, qy, 1e-7);
  }
  assert.deepEqual(barrelScreen(0.2, 0.1, 0, 1), [0.2, 0.1]);
  // köşeler (balıkgözü) ekranda dışa itilir: |d| > |q|/scale değil — k>0 kenarları içe sıkıştırır → görünen ofset < q/scale
  const [dx] = barrelScreen(0.4, 0, k, sc); assert.ok(dx < 0.4 / sc);
});
test('screenDir/dirAngle: önde sağ → 90°, sol-üst → 315°; ARKA yarım küre: arka-sağ hâlâ sağ (90°), arka-sol-üst sol-üst; tam arka aşağı (180°)', () => {
  near(dirAngle(screenDir(V, [50, 100, 0])), 90);
  near(dirAngle(screenDir(V, [-50, 100, 50])), 315);
  near(dirAngle(screenDir(V, [50, -100, 0])), 90, 1e-9, 'arka-sağ → sağ ok');
  near(dirAngle(screenDir(V, [-50, -100, 50])), 315, 1e-9, 'arka-sol-üst → sol-üst ok');
  near(dirAngle(screenDir(V, [0, -100, 0])), 180, 1e-9, 'tam arka → aşağı');
  // ndc bölmesi arka yarım kürede yönü çevirirdi (karşı örnek): xc/zf < 0 iken gerçek yön sağ
  const [xc, , zf] = camSpace(V, [50, -100, 0]); assert.ok(xc / zf < 0, 'bölünmüş (ndc) izdüşüm arkada ters tarafa düşer — bu yüzden screenDir bölmez');
});
test('offAngle: eksen 0°, 90° yan, 180° arka', () => {
  near(offAngle(V, [0, 10, 0]), 0); near(offAngle(V, [10, 0, 0]), 90); near(offAngle(V, [0, -10, 0]), 180); near(offAngle(V, [10, 10, 0]), 45, 1e-9);
});
test('edgePoint: elips denklemini sağlar ve yönü korur', () => {
  for (const a of [0, 33, 90, 145, 200, 300]) {
    const r = a * Math.PI / 180, d = [Math.sin(r), -Math.cos(r)];
    const [x, y] = edgePoint(d, 400, 300, 350, 220);
    near(((x - 400) / 350) ** 2 + ((y - 300) / 220) ** 2, 1, 1e-9);
    near(dirAngle([x - 400, y - 300]), a, 1e-6);
  }
});
test('fitMin: küçük prizma en küçük boyuta merkez etrafında büyür (biçim korunur); büyük olana dokunulmaz; tek nokta → kare kutu', () => {
  const pts = [[100, 100], [104, 101], [102, 103]];
  const f = fitMin(pts, 22);
  assert.equal(f.scaled, true); near(Math.max(f.bb.x1 - f.bb.x0, f.bb.y1 - f.bb.y0), 22, 1e-9);
  near((f.bb.x0 + f.bb.x1) / 2, 102, 1e-9); near((f.bb.y0 + f.bb.y1) / 2, 101.5, 1e-9);
  near((f.pts[1][0] - f.pts[0][0]) / (f.pts[2][0] - f.pts[0][0]), 2, 1e-9, 'oranlar korunur');
  const big = [[0, 0], [50, 30]]; assert.equal(fitMin(big, 22).scaled, false); assert.equal(fitMin(big, 22).pts, big);
  const one = fitMin([[10, 10], [10, 10]], 20); near(one.bb.x1 - one.bb.x0, 20); assert.deepEqual(one.pts[0], [10, 10]);
});
test('closureRate: kafa kafaya yaklaşma +, uzaklaşma −, yanal 0', () => {
  near(closureRate([0, 100, 0], [0, -20, 0], [0, 30, 0]), 50);
  near(closureRate([0, 100, 0], [0, 10, 0], [0, 0, 0]), -10);
  near(closureRate([0, 100, 0], [15, 0, 0], [0, 0, 0]), 0);
  assert.equal(closureRate([0, 0, 0], [1, 1, 1], [0, 0, 0]), 0);
});
test('rectEntry: boresight → TD kutusuna giriş noktası; boresight kutu içinde → null', () => {
  const bb = { x0: 300, y0: 100, x1: 340, y1: 140 };
  assert.deepEqual(rectEntry(100, 120, 320, 120, bb), [300, 120]);
  const e = rectEntry(320, 400, 320, 120, bb); assert.deepEqual(e, [320, 140]);
  assert.equal(rectEntry(310, 110, 320, 120, bb), null);
});
test('boxCorners/BOX_EDGES: 8 köşe bit sırası, 12 kenar her köşede 3 kenar', () => {
  const c = boxCorners([0, 0, 0], [1, 2, 3]);
  assert.deepEqual(c[0], [0, 0, 0]); assert.deepEqual(c[7], [1, 2, 3]); assert.deepEqual(c[5], [1, 0, 3]);
  assert.equal(BOX_EDGES.length, 12);
  for (let k = 0; k < 8; k++) assert.equal(BOX_EDGES.filter(e => e.includes(k)).length, 3);
  for (const [a, b] of BOX_EDGES) assert.equal([1, 2, 4].includes(a ^ b), true, 'kenar tek eksende');
});
test('selectTarget/lockedIndex: oto = en yakın; Tab en yakından sonrakine (i sırası, döngü); Shift+Tab geri; kilitli düşerse oto', () => {
  const L = [{ i: 0, dist: 900 }, { i: 1, dist: 300 }, { i: 2, dist: 1500 }];
  let s = { i: null, auto: true };
  assert.equal(lockedIndex(L, s), 1);
  s = selectTarget(L, s, 1); assert.deepEqual(s, { i: 2, auto: false });
  s = selectTarget(L, s, 1); assert.deepEqual(s, { i: 0, auto: false });
  s = selectTarget(L, s, -1); assert.deepEqual(s, { i: 2, auto: false });
  assert.equal(lockedIndex(L, s), 2, 'elle kilit en yakın olmasa da korunur');
  assert.deepEqual(selectTarget(L.slice(0, 2), s, 0), { i: null, auto: true });
  assert.equal(lockedIndex([], s), null); assert.deepEqual(selectTarget([], s, 1), { i: null, auto: true });
});
const item = (i, c, half = 2) => ({ i, name: `T${i}`, center: c, corners: boxCorners(c.map(v => v - half), c.map(v => v + half)), vel: [0, -20, 0], dist: Math.hypot(...c), dz: c[2], inside: false, flash: false });
test('symbology: öndeki kilitli hedef → prizma (8 nokta, en küçük boyut), TD kutusu, TLL boresight\'tan kutu kenarına; arkadaki → kenar oku 180° (aşağı)', () => {
  const W = 1280, H = 720;
  const d = { view: V, radius: 25, sel: { i: null, auto: true }, player: { pos: [0, 0, 0], vel: [0, 30, 0] }, items: [item(0, [80, 1500, 40]), item(1, [0, -400, -20])] };
  const s = symbology(d, W, H, { S: 1 });
  const [a, b] = s.items;
  assert.equal(a.on, true); assert.equal(a.pts.length, 8); assert.ok(a.bb.x1 - a.bb.x0 >= TD_MIN_PX - 1e-9 || a.bb.y1 - a.bb.y0 >= TD_MIN_PX - 1e-9);
  assert.equal(b.on, false); near(b.arrow.ang, 180, 1e-6);
  assert.equal(s.locked.i, 1, 'oto kilit en yakın (arkadaki 400 m)');
  assert.ok(s.tll && Math.abs(s.tll.y2 - s.tll.y1) > 50, 'ekran dışı kilit: TLL kenardaki oka');
  near(b.vc, closureRate([0, -400, -20], [0, -20, 0], [0, 30, 0]), 1e-9);
  // Tab ile öndekine kilit: TLL TD kutusunun kenarında biter
  const s2 = symbology({ ...d, sel: { i: 0, auto: false } }, W, H, { S: 1 });
  assert.equal(s2.locked.i, 0); assert.ok(s2.locked.td);
  const { x0, x1, y0, y1 } = s2.locked.td, e = 1e-6;
  assert.ok((Math.abs(s2.tll.x2 - x0) < e || Math.abs(s2.tll.x2 - x1) < e || Math.abs(s2.tll.y2 - y0) < e || Math.abs(s2.tll.y2 - y1) < e), 'TLL kutu kenarında');
  assert.ok(x1 - x0 >= 34 - 1e-9, 'TD kutusu en küçük kenar');
  // görüş alanı dışında ama önde (sağda 80°) → ok sağ yarıda
  const s3 = symbology({ ...d, items: [item(0, [1000, 170, 0])] }, W, H, { S: 1 });
  assert.equal(s3.items[0].on, false); near(s3.items[0].arrow.ang, 90, 1e-6); assert.ok(s3.items[0].arrow.x > W / 2);
  // veri yok → boş
  assert.deepEqual(symbology(null, W, H).items, []);
});
test('symbology FPV balıkgözü: ekrandaki nokta CAM_FRAG ile örneklendiğinde sahnedeki (düz) izdüşüme düşer', () => {
  const W = 1280, H = 720, k = 0.12, sc = 1 / 1.06;
  for (const c of [[300, 1000, 0], [-120, 400, 90], [10, 2000, -30]]) {
    const flat = symbology({ view: V, sel: null, items: [item(0, c)] }, W, H).items[0];
    const fish = symbology({ view: { ...V, k, scale: sc }, sel: null, items: [item(0, c)] }, W, H).items[0];
    const dx = fish.x / W - 0.5, dy = fish.y / H - 0.5, f = (1 + k * (dx * dx + dy * dy)) * sc;
    near(0.5 + dx * f, flat.x / W, 1e-7); near(0.5 + dy * f, flat.y / H, 1e-7);
  }
});
test('drawSymbology: sahte 2B bağlamda hatasız çizer (prizma kenarları + ok + ÖNLEME yanıp sönme)', () => {
  const calls = [];
  const g = new Proxy({}, { get: (o, k) => (k in o ? o[k] : (...a) => calls.push([k, ...a])), set: (o, k, v) => { o[k] = v; return true; } });
  const it0 = { ...item(0, [0, 300, 0]), inside: true };
  const sym = symbology({ view: V, sel: { i: 0, auto: false }, player: { pos: [0, 0, 0], vel: [0, 0, 0] }, items: [it0, item(1, [0, -300, 0])] }, 1280, 720);
  drawSymbology(g, sym, { color: '#9cff6a', S: 1, tr: s => (s === 'ÖNLEME' ? 'SHOOT' : s), now: 0, W: 1280 });
  assert.ok(calls.filter(c => c[0] === 'moveTo').length >= 12, 'prizma kenarları');
  assert.ok(calls.some(c => c[0] === 'fillText' && c[1] === 'SHOOT'), 'önleme ibaresi');
  assert.ok(calls.some(c => c[0] === 'fillText' && /^T1 /.test(c[1])), 'veri bloğu');
  drawSymbology(g, { items: [] });   // boş: sessiz
});
test('fmtRange: m / km', () => { assert.equal(fmtRange(850.4), '850m'); assert.equal(fmtRange(1240), '1.24km'); assert.equal(fmtRange(12400), '12km'); });

console.log('flightsim_tgtview.js');
test('niceScale: 40–110 px aralığına sığan adım; aralık dışıysa en yakın', () => {
  assert.deepEqual(niceScale(100), { m: 0.5, px: 50 });
  assert.deepEqual(niceScale(30), { m: 2, px: 60 });
  assert.equal(niceScale(0), null);
  const s = niceScale(5000); assert.equal(s.m, 0.05);
});
test('fmtSize / fmtLen', () => {
  assert.equal(fmtSize([1.654, 0.5, 0.25]), '1.65 × 0.50 × 0.25 m'); assert.equal(fmtSize(null), '—');
  assert.equal(fmtLen(0.25), '25 cm'); assert.equal(fmtLen(2), '2 m');
});
console.log(`${n} test geçti`);
