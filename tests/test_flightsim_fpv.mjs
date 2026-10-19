// Uçuş Simülatörü — FPV (pilot gözü) kipi (§22) tarayıcısız birim testi: OSD yardımcı hesapları (eve vektör/ok açısı, ufuk çizgisi, pil yüzdesi,
// uyarılar, analog parazit), kamera kipi sırası/etiketleri/döngüsü (flightsim3d.js CAMERA_MODES), tercihler (localStorage fs.fpv.* / fs.cam),
// ses: 'pilot' kipinde motor daha yakın/yüksek + rüzgâr (flightsim_audio.js fpvParams + sahte Web Audio grafiği).
// Çalıştırma: node tests/test_flightsim_fpv.mjs
import assert from 'node:assert/strict';
import { homeVector, relBearing, horizonLine, battPct, cellCount, osdWarnings, analogNoise, fmtClock, homeArrow, createFpvPrefs, wrap180, LS, LOW_BATT_PCT, LOW_ALT_M } from '../static/js/modules/flightsim_fpv_osd.js';
import { CAMERA_MODES, PILOT_FOV, PIP_SIZE, PIP_FPS, nextCameraMode } from '../static/js/modules/flightsim3d.js';
import { fpvParams, PILOT_BOOST, createEngineAudio } from '../static/js/modules/flightsim_audio.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);
const DEG = Math.PI / 180;
const memStorage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), map: m }; };

console.log('Kamera kipleri');
test('sıra: Takip · FPV · Gimbal kamerası · Serbest · Yer; kod adları follow/pilot/fpv/free/ground (eski fpv kodu değişmedi)', () => {
  assert.deepEqual(CAMERA_MODES.map(([k]) => k), ['follow', 'pilot', 'fpv', 'free', 'ground']);
  assert.deepEqual(CAMERA_MODES.map(([, l]) => l), ['Takip', 'FPV', 'Gimbal kamerası', 'Serbest', 'Yer']);
  assert.equal(CAMERA_MODES.length, 5);
});
test('C döngüsü: follow → pilot → fpv → free → ground → follow; bilinmeyen → follow', () => {
  assert.equal(nextCameraMode('follow'), 'pilot'); assert.equal(nextCameraMode('pilot'), 'fpv'); assert.equal(nextCameraMode('fpv'), 'free');
  assert.equal(nextCameraMode('free'), 'ground'); assert.equal(nextCameraMode('ground'), 'follow'); assert.equal(nextCameraMode('yok'), 'follow');
});
test('FPV görüş açısı 120° (90–150, adım 5); PiP 240×135 @ 20 fps', () => {
  assert.deepEqual(PILOT_FOV, { def: 120, min: 90, max: 150, step: 5 });
  assert.equal(PIP_SIZE.w, 240); assert.equal(PIP_SIZE.h, 135); assert.equal(PIP_FPS, 20);
});

console.log('OSD yardımcıları');
test('eve vektör: 1 km kuzeyde ev → mesafe ≈ 1000 m, kerteriz 0°; doğuda → 90°; veri yoksa null', () => {
  const home = { lat: 39.925, lon: 32.837 };
  const n1 = homeVector(39.925 - 1000 / 110574, 32.837, home);
  close(n1.dist, 1000, 0.5); close(n1.bearing, 0, 1e-6);
  const e1 = homeVector(39.925, 32.837 - 1000 / (111320 * Math.cos(39.925 * DEG)), home);
  close(e1.dist, 1000, 0.5); close(e1.bearing, 90, 1e-3);
  const s1 = homeVector(39.925 + 500 / 110574, 32.837, home); close(s1.bearing, 180, 1e-6); close(s1.dist, 500, 0.5);
  assert.equal(homeVector(null, 32, home), null); assert.equal(homeVector(39, 32, null), null); assert.equal(homeVector(39, 32, { lat: null }), null);
  close(homeVector(39.925, 32.837, home).dist, 0);
});
test('eve ok açısı: kerteriz − yön, −180…180 (ev tam arkada ±180, sağda +90)', () => {
  close(relBearing(90, 0), 90); close(relBearing(0, 90), -90); close(relBearing(180, 0), -180); close(relBearing(10, 350), 20); close(relBearing(350, 10), -20);
  close(wrap180(540), -180); close(wrap180(-190), 170); close(wrap180(0), 0);
  const pts = homeArrow(100, 100, 10, 0);
  assert.equal(pts.length, 4); close(pts[0][0], 100); close(pts[0][1], 90, 1e-9);        // ok ucu yukarıda
  const r90 = homeArrow(100, 100, 10, 90); close(r90[0][0], 110, 1e-9); close(r90[0][1], 100, 1e-9);   // sağa dönük
});
test('ufuk çizgisi: düz uçuşta merkezde yatay; burun yukarı → ufuk aşağı kayar; sağa yatış → sağ uç yukarı; odak f = (H/2)/tan(fov/2)', () => {
  const W = 1200, H = 800;
  const flat = horizonLine(W, H, 0, 0, 120, 200);
  close(flat.mx, 600); close(flat.my, 400); close(flat.y1, 400); close(flat.y2, 400); close(flat.x1, 400); close(flat.x2, 800);
  close(flat.f, 400 / Math.tan(60 * DEG));
  const up = horizonLine(W, H, 0, 10 * DEG, 120, 200);
  assert.ok(up.my > 400, 'burun yukarı → ufuk aşağı'); close(up.my - 400, flat.f * Math.tan(10 * DEG), 1e-9); close(up.y1, up.y2);
  const down = horizonLine(W, H, 0, -10 * DEG, 120, 200); assert.ok(down.my < 400);
  const bank = horizonLine(W, H, 20 * DEG, 0, 120, 200);
  assert.ok(bank.y2 < bank.y1, 'sağa yatışta ufkun sağ ucu yukarı'); close(bank.y1 - bank.y2, 2 * 200 * Math.sin(20 * DEG), 1e-9);
  close(Math.hypot(bank.x2 - bank.x1, bank.y2 - bank.y1), 400, 1e-9);   // uzunluk korunur
  const both = horizonLine(W, H, 20 * DEG, 10 * DEG, 120, 200);   // kayma ufka dik yönde (dönmüş): merkez x de kayar
  assert.ok(both.mx > 600 && both.my > 400);
  const narrow = horizonLine(W, H, 0, 10 * DEG, 60, 200); assert.ok(narrow.my - 400 > up.my - 400, 'dar FOV → aynı pitch daha çok piksel');
  const ext = horizonLine(W, H, 0, 89 * DEG, 120, 200); assert.ok(Number.isFinite(ext.my), 'kırpma: 85° sınır');
});
test('pil yüzdesi: telemetri yüzdesi öncelikli (0–100 kırpılır); yoksa gerilimden hücre kestirimi (3,5 → 0 %, 4,2 → 100 %); yoksa null', () => {
  close(battPct(16.8, 73), 73); close(battPct(0, 120), 100); close(battPct(null, -5), 0);
  assert.equal(cellCount(16.8), 4); assert.equal(cellCount(22.2), 6); assert.equal(cellCount(11.1), 3); assert.equal(cellCount(0), null); assert.equal(cellCount(null), null);
  close(battPct(16.8, null), 100); close(battPct(14.0, null), 0); close(battPct(15.4, null), 50, 1e-9); close(battPct(3.85, undefined), 50, 1e-9);
  assert.equal(battPct(null, null), null); assert.equal(battPct(0, null), null);
});
test('uyarılar: düşük pil < %25, alçak (armed, AGL < 10 m, hız > 3), çarpışma, RSSI < 30; yerde/disarm alçak uyarısı yok', () => {
  assert.equal(LOW_BATT_PCT, 25); assert.equal(LOW_ALT_M, 10);
  assert.deepEqual(osdWarnings({ armed: true, agl: 50, gs: 20, batt: 80 }), []);
  assert.deepEqual(osdWarnings({ armed: true, agl: 50, gs: 20, batt: 20 }), ['lowbatt']);
  assert.deepEqual(osdWarnings({ armed: true, agl: 5, gs: 10, batt: 80 }), ['lowalt']);
  assert.deepEqual(osdWarnings({ armed: false, agl: 0, gs: 0, batt: 80 }), [], 'yerde alçak yok');
  assert.deepEqual(osdWarnings({ armed: true, agl: 5, gs: 1, batt: 80 }), [], 'yavaşken (iniş/askı) alçak yok');
  assert.deepEqual(osdWarnings({ armed: true, agl: 5, gs: 10, batt: 10, collision: true, rssi: 20 }), ['crash', 'lowbatt', 'lowalt', 'rssi']);
  assert.deepEqual(osdWarnings({ armed: true, agl: null, gs: 10, batt: null, rssi: null }), []);
});
test('analog parazit: RSSI varsa %60 altında doğrusal artar (0 → 1); yoksa eve uzaklıkla (3 km → 0,6, sınırlı)', () => {
  close(analogNoise(100, 0), 0); close(analogNoise(60, 0), 0); close(analogNoise(30, 0), 0.5); close(analogNoise(0, 5000), 1);
  close(analogNoise(null, 0), 0); close(analogNoise(null, 1500), 0.3); close(analogNoise(null, 3000), 0.6); close(analogNoise(null, 9000), 0.6);
  assert.equal(fmtClock(0), '00:00'); assert.equal(fmtClock(65.9), '01:05'); assert.equal(fmtClock(-3), '00:00'); assert.equal(fmtClock(3600), '60:00');
});
test('tercihler: varsayılan analog kapalı, PiP açık, burun açık, FOV 120, OSD açık, kamera follow; localStorage anahtarları; özel kipte sessiz', () => {
  const st = memStorage(); const p = createFpvPrefs(st);
  assert.equal(p.analog, false); assert.equal(p.pip, true); assert.equal(p.nose, true); assert.equal(p.fov, 120); assert.equal(p.osd, true); assert.equal(p.cam, 'follow');
  p.setAnalog(true); assert.equal(st.getItem(LS.analog), '1'); p.setPip(false); assert.equal(st.getItem('fs.fpv.pip'), '0');
  assert.equal(p.setFov(200), 150); assert.equal(p.setFov(10), 90); assert.equal(p.setFov(117.6), 118); assert.equal(st.getItem('fs.fpv.fov'), '118');
  p.setCam('pilot'); assert.equal(st.getItem('fs.cam'), 'pilot'); p.setOsd(false); assert.equal(st.getItem('fs.osd.on'), '0');
  const p2 = createFpvPrefs(st); assert.equal(p2.analog, true); assert.equal(p2.pip, false); assert.equal(p2.fov, 118); assert.equal(p2.cam, 'pilot'); assert.equal(p2.osd, false);
  const p3 = createFpvPrefs({ getItem() { throw new Error('private'); }, setItem() { throw new Error('private'); } });
  assert.equal(p3.fov, 120); p3.setFov(100); assert.equal(p3.fov, 100);
});

console.log('Ses (pilot kipi)');
test("fpvParams: 'fpv' lowpass 900 + rüzgâr 0,5 (eski davranış); 'pilot' süzgeç açık, boost 1,3, rüzgâr 35 m/s'de 0,8; diğer kip boost 1", () => {
  const g = fpvParams(20), p = fpvParams(20, 'pilot'), f = fpvParams(0, 'follow');
  assert.equal(g.lowpass, 900); close(g.wind, 0.25); assert.equal(g.boost, 1);
  assert.equal(p.lowpass, 20000); close(p.boost, PILOT_BOOST); assert.ok(p.boost > 1); assert.ok(p.wind > g.wind, 'pilot rüzgârı daha güçlü'); close(fpvParams(35, 'pilot').wind, 0.8); close(fpvParams(100, 'pilot').wind, 0.8);
  assert.ok(fpvParams(30, 'pilot').windFreq > fpvParams(5, 'pilot').windFreq, 'rüzgâr frekansı hızla yükselir');
  assert.equal(f.boost, 1);
});
test("grafik: 'pilot' kipinde kaynak dinleyicide, master ×1,3, rüzgâr > 0, süzgeç açık; 'follow'a dönüşte eski değerler", () => {
  class FakeParam { constructor(v = 0) { this.value = v; } setTargetAtTime(v) { this.value = v; } setValueAtTime(v) { this.value = v; } linearRampToValueAtTime() {} cancelScheduledValues() {} }
  class FakeNode { constructor(ctx) { this.ctx = ctx; ctx.nodes.push(this); } connect(d) { return d; } disconnect() {} start() {} stop() {} }
  class FakeAC {
    constructor() { this.nodes = []; this.currentTime = 0; this.sampleRate = 48000; this.state = 'suspended'; this.destination = {}; this.listener = Object.fromEntries(['positionX', 'positionY', 'positionZ', 'forwardX', 'forwardY', 'forwardZ', 'upX', 'upY', 'upZ'].map(k => [k, new FakeParam()])); }
    createGain() { const g = new FakeNode(this); g.gain = new FakeParam(1); return g; }
    createOscillator() { const o = new FakeNode(this); o.frequency = new FakeParam(440); o.type = 'sine'; return o; }
    createBiquadFilter() { const f = new FakeNode(this); f.frequency = new FakeParam(350); f.Q = new FakeParam(1); return f; }
    createBufferSource() { const s = new FakeNode(this); return s; }
    createBuffer(ch, len, sr) { const d = new Float32Array(len); return { getChannelData: () => d }; }
    createPanner() { const p = new FakeNode(this); p.positionX = new FakeParam(); p.positionY = new FakeParam(); p.positionZ = new FakeParam(); return p; }
    async resume() { this.state = 'running'; this.onstatechange?.(); } async close() {}
  }
  const sim = { cam: 'follow', getCamera() { return this.cam; }, position: () => ({ x: 100, y: 50, z: 30 }), cameraPose: () => ({ x: 0, y: -20, z: 5, fx: 0, fy: 1, fz: 0, ux: 0, uy: 0, uz: 1 }), launchPhase: null };
  let clock = 0; const st = memStorage(); st.setItem('fs.audio.vol', '100');
  const a = createEngineAudio(null, { type: 'multirotor', doc: null, AudioContextClass: FakeAC, storage: st, now: () => clock, getSim: () => sim });
  a.unlock();
  const tick = () => { clock += 50; a.update({ armed: true, throttle: 50, airspeed: 20 }); };
  for (let i = 0; i < 10; i++) tick();
  close(a.graph.master.gain.value, 1); close(a.graph.pan.positionX.value, 100); assert.equal(a.graph.fpv.frequency.value, 20000); assert.equal(a.graph.wind.g.gain.value, 0);
  sim.cam = 'pilot';
  for (let i = 0; i < 10; i++) tick();
  close(a.graph.master.gain.value, PILOT_BOOST); close(a.graph.pan.positionX.value, 0); close(a.graph.pan.positionY.value, -20);   // kokpit: kaynak dinleyicide
  assert.equal(a.graph.fpv.frequency.value, 20000, 'pilot: süzgeç açık (boğuk değil)'); close(a.graph.wind.g.gain.value, 20 / 35 * 0.8);
  sim.cam = 'fpv';
  for (let i = 0; i < 10; i++) tick();
  close(a.graph.master.gain.value, 1); assert.equal(a.graph.fpv.frequency.value, 900); close(a.graph.wind.g.gain.value, 0.25);
  sim.cam = 'follow';
  for (let i = 0; i < 10; i++) tick();
  close(a.graph.master.gain.value, 1); close(a.graph.pan.positionX.value, 100); assert.equal(a.graph.wind.g.gain.value, 0);
  a.dispose();
});
console.log(`\n${n} test geçti`);
