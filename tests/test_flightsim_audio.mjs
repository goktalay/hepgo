// Uçuş Simülatörü — motor sesi (static/js/modules/flightsim_audio.js, §16) tarayıcısız birim testi.
// Playwright headless'ta AudioContext sessizdir/çalışmaz → saf model katmanı doğrudan, grafik katmanı SAHTE Web Audio düğümleriyle denenir:
// tip→devir→frekans eşlemeleri, gaz yumuşatma (0,3–0,8 sn takip), mesafe kazancı (1/r, 15 m), aç/kapa + ses düzeyi + localStorage,
// ilk etkileşim (resume) kilidi, sekme gizlenme, oynatma hızı ≥ 2× sessizliği, FPV kokpit, kalkış efektleri, çarpışma, dispose.
// Çalıştırma: node tests/test_flightsim_audio.mjs
import assert from 'node:assert/strict';
import { AUDIO_MODELS, MOTOR_RATIOS, REF_DISTANCE, TAU_UP, TAU_DOWN, audioModel, copterBpf, planeRpm, firingHz, heliBpf, vtolMix, vehicleRpm,
  engineTargets, smoothFollow, distanceGain, fpvParams, dopplerFactor, createAudioPrefs, createEngineAudio } from '../static/js/modules/flightsim_audio.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≈ ${b}`);

// ---------------- sahte Web Audio ----------------
class FakeParam {
  constructor(v = 0) { this.value = v; this.log = []; }
  setTargetAtTime(v, t, tc) { this.target = v; this.log.push(['target', v, t, tc]); this.value = v; }
  setValueAtTime(v, t) { this.value = v; this.log.push(['set', v, t]); }
  linearRampToValueAtTime(v, t) { this.peak = v; this.log.push(['ramp', v, t]); }
  cancelScheduledValues(t) { this.log.push(['cancel', t]); }
}
class FakeNode {
  constructor(ctx, kind) { this.ctx = ctx; this.kind = kind; this.outs = []; ctx.nodes.push(this); }
  connect(d) { this.outs.push(d); return d; }
  disconnect() { this.outs = []; }
  start() { this.started = true; this.ctx.started++; }
  stop() { this.stopped = true; }
}
class FakeAudioContext {
  constructor() { this.nodes = []; this.started = 0; this.currentTime = 0; this.sampleRate = 48000; this.state = 'suspended'; this.destination = { kind: 'dest' }; this.onstatechange = null;
    this.listener = { positionX: new FakeParam(), positionY: new FakeParam(), positionZ: new FakeParam(), forwardX: new FakeParam(), forwardY: new FakeParam(), forwardZ: new FakeParam(), upX: new FakeParam(), upY: new FakeParam(), upZ: new FakeParam() };
    FakeAudioContext.created++; }
  createGain() { const g = new FakeNode(this, 'gain'); g.gain = new FakeParam(1); return g; }
  createOscillator() { const o = new FakeNode(this, 'osc'); o.frequency = new FakeParam(440); o.detune = new FakeParam(0); o.type = 'sine'; return o; }
  createBiquadFilter() { const f = new FakeNode(this, 'filter'); f.frequency = new FakeParam(350); f.Q = new FakeParam(1); f.type = 'lowpass'; return f; }
  createBufferSource() { const s = new FakeNode(this, 'bufsrc'); s.loop = false; return s; }
  createBuffer(ch, len, sr) { const d = new Float32Array(len); return { length: len, sampleRate: sr, numberOfChannels: ch, getChannelData: () => d }; }
  createPanner() { const p = new FakeNode(this, 'panner'); p.positionX = new FakeParam(); p.positionY = new FakeParam(); p.positionZ = new FakeParam(); return p; }
  async resume() { this.state = 'running'; this.onstatechange?.(); }
  async suspend() { this.state = 'suspended'; this.onstatechange?.(); }
  async close() { this.state = 'closed'; this.closed = true; }
}
FakeAudioContext.created = 0;
const memStorage = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), map: m }; };
const fakeSim = (over = {}) => ({ cam: 'follow', pos: { x: 0, y: 0, z: 0 }, camPos: { x: 0, y: -20, z: 5 }, phase: null,
  getCamera() { return this.cam; }, position() { return this.pos; }, cameraPose() { return { ...this.camPos, fx: 0, fy: 1, fz: 0, ux: 0, uy: 0, uz: 1 }; }, get launchPhase() { return this.phase; }, ...over });
let clock = 0;
const mk = (type, extra = {}) => createEngineAudio(null, { type, doc: null, AudioContextClass: FakeAudioContext, storage: extra.storage || memStorage(), now: () => clock, ...extra });
const tick = (a, t, ms = 50) => { clock += ms; a.update(t); };

console.log('Katman 1: saf model');
test('tip → ses modeli; bilinmeyen tip kopter', () => {
  assert.equal(audioModel('multirotor').kind, 'copter'); assert.equal(audioModel('multirotor').motors, 4);
  assert.equal(audioModel('hexarotor').motors, 6); assert.equal(audioModel('helikopter').kind, 'heli');
  assert.equal(audioModel('sabit_kanat').kind, 'plane'); assert.equal(audioModel('vtol').kind, 'vtol');
  assert.equal(audioModel('bilinmeyen').kind, 'copter');
  assert.equal(MOTOR_RATIOS[4].length, 4); assert.equal(MOTOR_RATIOS[6].length, 6);
  assert.ok(new Set(MOTOR_RATIOS[6]).size === 6, 'her motor farklı oran');
});
test('kopter pala geçiş frekansı: gaz 0 → 150 Hz, 100 → 600 Hz; düşük batarya %4 düşürür', () => {
  close(copterBpf(0), 150); close(copterBpf(100), 600); close(copterBpf(50), 375);
  close(copterBpf(100, 0), 600 * 0.96); close(copterBpf(100, 15), 600 * (1 - 0.02)); close(copterBpf(100, 80), 600);
  close(copterBpf(150), 600); close(copterBpf(-5), 150);
});
test('uçak devri: rölanti 1500 → tam gaz 7500; ateşleme f = devir/60 × silindir', () => {
  close(planeRpm(0), 1500); close(planeRpm(100), 7500); close(planeRpm(50), 4500);
  close(firingHz(1500, 1), 25); close(firingHz(7500, 1), 125); close(firingHz(3000, 2), 100);
});
test('helikopter rotor 20–30 Hz; VTOL karışımı 5→20 m/s; araç devri 800–4500', () => {
  close(heliBpf(0), 20); close(heliBpf(100), 30);
  close(vtolMix(0), 0); close(vtolMix(5), 0); close(vtolMix(12.5), 0.5); close(vtolMix(20), 1); close(vtolMix(60), 1);
  close(vehicleRpm(0), 800); close(vehicleRpm(10), 2000); close(vehicleRpm(100), 4500);
});
test('engineTargets: kopter disarm sessiz, armed gazla artar', () => {
  const off = engineTargets('multirotor', { armed: false, throttle: 50 });
  assert.equal(off.copter, 0); assert.equal(off.kind, 'copter');
  const lo = engineTargets('multirotor', { armed: true, throttle: 0 }), hi = engineTargets('multirotor', { armed: true, throttle: 100 });
  assert.ok(lo.copter > 0 && hi.copter > lo.copter); close(lo.bpf, 150); close(hi.bpf, 600);
  assert.equal(engineTargets('hexarotor', { armed: true, throttle: 20 }).kind, 'copter');
});
test('engineTargets: uçak armed + gaz 0 = rölanti (sesli), disarm sessiz; devir ve ateşleme frekansı', () => {
  const idle = engineTargets('sabit_kanat', { armed: true, throttle: 0 });
  assert.ok(idle.plane > 0, 'rölanti sesli'); close(idle.rpm, 1500); close(idle.fire, 25);
  const full = engineTargets('sabit_kanat', { armed: true, throttle: 100 });
  close(full.rpm, 7500); close(full.fire, 125); assert.ok(full.plane > idle.plane);
  const off = engineTargets('sabit_kanat', { armed: false, throttle: 0 });
  assert.equal(off.plane, 0); assert.equal(off.rpm, 0);
});
test('engineTargets: VTOL yerde kopter, ileri uçuşta uçak ağırlıklı', () => {
  const g = engineTargets('vtol', { armed: true, throttle: 60, airspeed: 0 }), f = engineTargets('vtol', { armed: true, throttle: 60, airspeed: 25 });
  assert.equal(g.mix, 0); assert.equal(f.mix, 1);
  assert.ok(g.copter > f.copter, 'kopter sesi ileri uçuşta azalır'); assert.ok(f.plane > g.plane, 'uçak sesi ileri uçuşta artar');
});
test('engineTargets: helikopter; rs/ps/ys → modülasyon 0…1; rüzgâr hızdan', () => {
  const h = engineTargets('helikopter', { armed: true, throttle: 50, rs: 0.5, ps: 0.5, ys: 0 });
  close(h.heliBpf, 25); assert.ok(h.heli > 0); close(h.wobble, Math.hypot(0.5, 0.5) / 2);
  assert.equal(engineTargets('helikopter', { armed: false }).heli, 0);
  close(engineTargets('multirotor', { armed: true, airspeed: 20 }).wind, 0.5);
  close(engineTargets('multirotor', { armed: true, rs: 9, ps: 9 }).wobble, 1);
});
test('engineTargets: araç üstü kalkış — pickup motoru aşamaya ve hıza göre', () => {
  const idle = engineTargets('sabit_kanat', { armed: true, throttle: 0 }, { launchMethod: 'vehicle', launchPhase: 'idle' });
  assert.equal(idle.vehicle, 0);
  const armed = engineTargets('sabit_kanat', { armed: true }, { launchMethod: 'vehicle', launchPhase: 'armed' });
  close(armed.vehicleRpm, 800); assert.ok(armed.vehicle > 0);
  const run = engineTargets('sabit_kanat', { armed: true }, { launchMethod: 'vehicle', launchPhase: 'launch', vehicleSpeed: 15 });
  close(run.vehicleRpm, 2600); assert.ok(run.vehicle > armed.vehicle, 'hızlanırken sesi artar');
  const rel = engineTargets('sabit_kanat', { armed: true }, { launchMethod: 'vehicle', launchPhase: 'released', vehicleSpeed: 15 });
  close(rel.vehicleRpm, 800, 1e-9);
  assert.equal(engineTargets('sabit_kanat', { armed: true }, { launchMethod: 'ramp', launchPhase: 'launch' }).vehicle, 0);
  assert.equal(engineTargets('sabit_kanat', { armed: true }, { launchMethod: 'vehicle', launchPhase: 'free' }).vehicle, 0);
});
test('gaz yumuşatma: yukarı 0,35 sn / aşağı 0,7 sn zaman sabiti; 1 sn sonra yukarı > %94, aşağı ~%76', () => {
  assert.equal(TAU_UP, 0.35); assert.equal(TAU_DOWN, 0.7);
  let v = 0; for (let i = 0; i < 20; i++) v = smoothFollow(v, 100, 0.05);
  close(v, 100 * (1 - Math.exp(-1 / 0.35)), 1e-6); assert.ok(v > 94 && v < 95);
  let d = 100; for (let i = 0; i < 20; i++) d = smoothFollow(d, 0, 0.05);
  close(d, 100 * Math.exp(-1 / 0.7), 1e-6); assert.ok(d > 23 && d < 25, 'aşağı daha yavaş');
  close(smoothFollow(50, 50, 0.05), 50); close(smoothFollow(10, 20, 0), 10); close(smoothFollow(10, 20, -1), 10);
  // 0,3–0,8 sn gecikmeli takip: %63 noktası tau'da
  close(smoothFollow(0, 1, 0.35), 1 - Math.exp(-1));
});
test('mesafe kazancı: 15 m referansa kadar 1, sonra 1/r', () => {
  assert.equal(REF_DISTANCE, 15);
  close(distanceGain(0), 1); close(distanceGain(15), 1); close(distanceGain(30), 0.5); close(distanceGain(150), 0.1); close(distanceGain(300, 30), 0.1);
});
test('FPV kokpit: lowpass 900 Hz, rüzgâr hızla artar (40 m/s → 0,5), Doppler ±%5 sınırlı', () => {
  const s = fpvParams(0), f = fpvParams(40), x = fpvParams(100);
  assert.equal(s.lowpass, 900); close(s.wind, 0); close(f.wind, 0.5); close(x.wind, 0.5); assert.ok(f.windFreq > s.windFreq);
  close(dopplerFactor(0), 1); assert.ok(dopplerFactor(30) < 1 && dopplerFactor(-30) > 1, 'uzaklaşırken alçalır');
  close(dopplerFactor(1000), 0.95); close(dopplerFactor(-1000), 1.05);
});
test('tercihler: varsayılan açık, ses 70; localStorage fs.audio.on / fs.audio.vol; etkili kazanç koşulları', () => {
  const st = memStorage(); const p = createAudioPrefs(st);
  assert.equal(p.enabled, true); assert.equal(p.volume, 70); assert.equal(p.effective(), 0, 'etkileşim yokken sessiz'); assert.equal(p.waiting, true);
  p.setUnlocked(true); assert.equal(p.waiting, false); close(p.effective(), 0.7 ** 1.6);
  p.setVolume(100); assert.equal(st.getItem('fs.audio.vol'), '100'); close(p.effective(), 1);
  p.setVolume(250); assert.equal(p.volume, 100); p.setVolume(-3); assert.equal(p.volume, 0); assert.equal(p.effective(), 0); p.setVolume(50);
  assert.equal(p.toggle(), false); assert.equal(st.getItem('fs.audio.on'), '0'); assert.equal(p.effective(), 0);
  assert.equal(p.toggle(), true); assert.equal(st.getItem('fs.audio.on'), '1'); assert.ok(p.effective() > 0);
  p.setHidden(true); assert.equal(p.effective(), 0); p.setHidden(false);
  assert.equal(p.setPlaybackSpeed(2), true); assert.equal(p.effective(), 0); assert.equal(p.setPlaybackSpeed(1), false); assert.ok(p.effective() > 0);
  assert.equal(p.setPlaybackSpeed(0.5), false); assert.equal(p.setPlaybackSpeed(8), true);
  const st2 = memStorage(); st2.setItem('fs.audio.on', '0'); st2.setItem('fs.audio.vol', '35');
  const p2 = createAudioPrefs(st2); assert.equal(p2.enabled, false); assert.equal(p2.volume, 35);
  const p3 = createAudioPrefs({ getItem() { throw new Error('private'); }, setItem() { throw new Error('private'); } });
  assert.equal(p3.enabled, true); p3.setVolume(10); assert.equal(p3.volume, 10);
});

console.log('Katman 2: Web Audio grafiği (sahte düğümler)');
test('tek AudioContext, düğümler bir kez kurulur; kopter 4 motor + ESC + uğultu', () => {
  FakeAudioContext.created = 0;
  const a = mk('multirotor');
  const sim = fakeSim(); const t = { armed: true, throttle: 40, airspeed: 3 };
  a.update(t);
  assert.equal(FakeAudioContext.created, 0, 'kilit açılmadan bağlam kurulmaz');
  a.unlock(); // ilk etkileşim
  assert.equal(FakeAudioContext.created, 1);
  const g = a.graph; assert.ok(g.copter && !g.plane && !g.heli && !g.vehicle);
  assert.equal(g.copter.motors.length, 4);
  const nodes = a.context.nodes.length, started = a.context.started;
  for (let i = 0; i < 30; i++) tick(a, t);
  assert.equal(FakeAudioContext.created, 1, 'tek bağlam'); assert.equal(a.context.nodes.length, nodes, 'düğüm sayısı sabit'); assert.equal(a.context.started, started, 'yeniden start yok');
  assert.ok(a.stats.updates >= 30 && a.stats.paramSets > 0);
  a.dispose(); assert.ok(a.context === null);
});
test('kopter: gaz 100 → motor frekansları 600 Hz × oranlar (yumuşatma sonrası); disarm → bus 0', () => {
  const a = mk('multirotor'); a.unlock(); const sim = fakeSim(); a.update({ armed: true, throttle: 100 });
  for (let i = 0; i < 100; i++) tick(a, { armed: true, throttle: 100 }, 50);   // 5 sn → yerleşir
  const g = a.graph;
  g.copter.motors.forEach((m, i) => close(m.o.frequency.value, 600 * MOTOR_RATIOS[4][i], 600 * 0.03));   // Doppler/titreme ±%1,5 payı
  assert.ok(g.copter.bus.gain.value > 0.7);
  for (let i = 0; i < 100; i++) tick(a, { armed: false, throttle: 0 }, 50);
  assert.equal(g.copter.bus.gain.value, 0, 'disarm sessiz');
  a.dispose();
});
test('hexarotor 6 motor; helikopter LFO 20–30 Hz; uçak ateşleme 25→125 Hz (rölanti/tam gaz)', () => {
  const h6 = mk('hexarotor'); h6.unlock(); h6.update({ armed: true }); assert.equal(h6.graph.copter.motors.length, 6); h6.dispose();
  const he = mk('helikopter'); he.unlock();
  for (let i = 0; i < 60; i++) tick(he, { armed: true, throttle: 100 });
  close(he.graph.heli.lfo.frequency.value, 30, 0.01); assert.ok(he.graph.heli.bus.gain.value > 0.8);
  for (let i = 0; i < 60; i++) tick(he, { armed: true, throttle: 0 });
  close(he.graph.heli.lfo.frequency.value, 20, 0.01);
  he.dispose();
  const pl = mk('sabit_kanat'); pl.unlock();
  for (let i = 0; i < 120; i++) tick(pl, { armed: true, throttle: 0 });
  close(pl.graph.plane.fire.o.frequency.value, 25, 0.5); assert.ok(pl.graph.plane.bus.gain.value > 0.25, 'rölanti sesli');
  for (let i = 0; i < 120; i++) tick(pl, { armed: true, throttle: 100 });
  close(pl.graph.plane.fire.o.frequency.value, 125, 2.5); close(pl.graph.plane.prop.o.frequency.value, 250, 5);
  for (let i = 0; i < 200; i++) tick(pl, { armed: false, throttle: 0 });
  assert.equal(pl.graph.plane.bus.gain.value, 0, 'disarm → sessiz');
  pl.dispose();
});
test('gaz yumuşatma grafikte: gaz 0→100 sıçramasında frekans 0,2 sn sonra ara değerde', () => {
  const a = mk('multirotor'); a.unlock(); const sim = fakeSim();
  for (let i = 0; i < 60; i++) tick(a, { armed: true, throttle: 0 });
  for (let i = 0; i < 4; i++) tick(a, { armed: true, throttle: 100 });   // 0,2 sn
  const f = a.graph.copter.motors[0].o.frequency.value;
  assert.ok(f > 200 && f < 400, `ara değer bekleniyor, ${f}`);
  a.dispose();
});
test('VTOL: iki grup; hava hızı arttıkça kopter azalır, uçak artar', () => {
  const a = mk('vtol'); a.unlock();
  for (let i = 0; i < 100; i++) tick(a, { armed: true, throttle: 60, airspeed: 0 });
  const c0 = a.graph.copter.bus.gain.value, p0 = a.graph.plane.bus.gain.value;
  for (let i = 0; i < 100; i++) tick(a, { armed: true, throttle: 60, airspeed: 25 });
  assert.ok(a.graph.copter.bus.gain.value < c0 * 0.3 && a.graph.plane.bus.gain.value > p0 * 2);
  a.dispose();
});
test('uzaysal: dinleyici kamerada, kaynak dronda; FPV → kaynak dinleyicide, lowpass 900, rüzgâr', () => {
  const sim = fakeSim(); sim.pos = { x: 100, y: 50, z: 30 };
  const a = mk('multirotor', { getSim: () => sim }); a.unlock();
  for (let i = 0; i < 10; i++) tick(a, { armed: true, throttle: 50, airspeed: 20 });
  const L = a.context.listener, Pn = a.graph.pan;
  close(L.positionX.value, 0); close(L.positionY.value, -20); close(L.positionZ.value, 5); close(L.upZ.value, 1); close(L.forwardY.value, 1);
  close(Pn.positionX.value, 100); close(Pn.positionZ.value, 30);
  assert.equal(a.graph.fpv.frequency.value, 20000); assert.equal(a.graph.wind.g.gain.value, 0);
  assert.equal(Pn.refDistance, REF_DISTANCE); assert.equal(Pn.distanceModel, 'inverse'); assert.equal(Pn.panningModel, 'equalpower');
  sim.cam = 'fpv';
  for (let i = 0; i < 10; i++) tick(a, { armed: true, throttle: 50, airspeed: 20 });
  close(Pn.positionX.value, 0); close(Pn.positionY.value, -20);   // kokpit: kaynak dinleyicide
  assert.equal(a.graph.fpv.frequency.value, 900); close(a.graph.wind.g.gain.value, 0.25);
  a.dispose();
});
test('Doppler: dron kameradan uzaklaşırken frekans alçalır (küçük, ≤ %5)', () => {
  const sim = fakeSim(); sim.pos = { x: 0, y: 0, z: 0 };
  const a = mk('multirotor', { getSim: () => sim }); a.unlock();
  for (let i = 0; i < 100; i++) tick(a, { armed: true, throttle: 50 });
  const f0 = a.graph.copter.motors[0].o.frequency.value;
  sim.pos = { x: 0, y: 3, z: 0 }; tick(a, { armed: true, throttle: 50 }, 50);   // 60 m/s uzaklaşma
  const f1 = a.graph.copter.motors[0].o.frequency.value;
  assert.ok(f1 < f0 && f1 > f0 * 0.93, `${f0} → ${f1}`);
  a.dispose();
});
test('aç/kapa: kapalı → master 0, localStorage 0; açık → kazanç; ses düzeyi kaydırıcısı; oynatma ≥ 2× sessiz', () => {
  const st = memStorage(); let speed = 1;
  const a = mk('multirotor', { storage: st, getSpeed: () => speed }); a.unlock();
  tick(a, { armed: true, throttle: 50 });
  assert.ok(a.graph.master.gain.value > 0); assert.equal(a.enabled, true);
  assert.equal(a.toggle(), false); assert.equal(st.getItem('fs.audio.on'), '0'); assert.equal(a.graph.master.gain.value, 0);
  tick(a, { armed: true, throttle: 50 }); assert.equal(a.graph.master.gain.value, 0);
  assert.equal(a.setEnabled(true), true); tick(a, { armed: true, throttle: 50 }); assert.ok(a.graph.master.gain.value > 0);
  a.setVolume(100); close(a.graph.master.gain.value, 1); a.setVolume(50); close(a.graph.master.gain.value, 0.5 ** 1.6); assert.equal(st.getItem('fs.audio.vol'), '50');
  speed = 2; tick(a, { armed: true, throttle: 50 }); assert.equal(a.graph.master.gain.value, 0, '2× sessiz'); assert.equal(a.prefs.speedMuted, true);
  speed = 1; tick(a, { armed: true, throttle: 50 }); assert.ok(a.graph.master.gain.value > 0);
  a.dispose();
});
test('ilk etkileşim öncesi sessiz (waiting); bağlam resume ile açılır; kapalı tercihle bağlam hiç kurulmaz', () => {
  const a = mk('multirotor');
  for (let i = 0; i < 5; i++) tick(a, { armed: true, throttle: 50 });
  assert.equal(a.prefs.waiting, true); assert.equal(a.context, null, 'etkileşim öncesi bağlam yok');
  a.unlock(); assert.equal(a.prefs.waiting, false); assert.equal(a.context.state, 'running');
  tick(a, { armed: true, throttle: 50 }); assert.ok(a.graph.master.gain.value > 0);
  a.dispose();
  const st = memStorage(); st.setItem('fs.audio.on', '0'); FakeAudioContext.created = 0;
  const b = mk('multirotor', { storage: st });
  for (let i = 0; i < 5; i++) tick(b, { armed: true, throttle: 50 });
  assert.equal(FakeAudioContext.created, 0, 'kapalıyken bağlam kurulmaz'); assert.equal(b.enabled, false);
  b.dispose();
});
test('rampa fırlatma: launch → "pşşt" zarfı; released → kızak çarpması; araç: released → fren; çarpışma → patlama + motor durur, sıfırla → döner', () => {
  const sim = fakeSim(); let crashed = false;
  const a = mk('sabit_kanat', { launch: { method: 'ramp' }, getSim: () => sim, getCrashed: () => crashed }); a.unlock();
  tick(a, { armed: true, throttle: 0 });
  assert.equal(a.graph.fx.g.gain.peak, undefined);
  sim.phase = 'armed'; tick(a, { armed: true }); assert.equal(a.graph.fx.g.gain.peak, undefined);
  sim.phase = 'launch'; tick(a, { armed: true }); close(a.graph.fx.g.gain.peak, 0.7);
  sim.phase = 'released'; tick(a, { armed: true, throttle: 100 }); close(a.graph.thump.g.gain.peak, 0.6);
  crashed = true; tick(a, { armed: false }); close(a.graph.crashN.g.gain.peak, 0.9); assert.equal(a.graph.src.gain.value, 0, 'motor durur');
  crashed = false; tick(a, { armed: false }); assert.equal(a.graph.src.gain.value, 1, 'sıfırla → motor grubu döner');
  a.dispose();
  const v = mk('sabit_kanat', { launch: { method: 'vehicle' }, getSim: () => sim }); v.unlock();
  assert.ok(v.graph.vehicle, 'pickup motoru grubu');
  sim.phase = 'armed'; for (let i = 0; i < 20; i++) tick(v, { armed: true });
  assert.ok(v.graph.vehicle.bus.gain.value > 0.2, 'araçta rölanti');
  sim.phase = 'launch'; for (let i = 0; i < 60; i++) tick(v, { armed: true, groundspeed: 20 });
  assert.ok(v.graph.vehicle.eng.o.frequency.value > 150, `hızlanırken devir artar: ${v.graph.vehicle.eng.o.frequency.value}`);
  sim.phase = 'released'; tick(v, { armed: true, groundspeed: 20 }); close(v.graph.vehicle.brake.g.gain.peak, 0.25);
  sim.phase = 'free'; for (let i = 0; i < 120; i++) tick(v, { armed: true, throttle: 80, groundspeed: 25 });
  assert.ok(v.graph.vehicle.bus.gain.value < 0.02, 'araç susar');
  v.dispose();
  const ramp2 = mk('multirotor', { getSim: () => sim }); ramp2.unlock(); sim.phase = 'launch'; tick(ramp2, { armed: true });
  assert.equal(ramp2.graph.fx.g.gain.peak, undefined, 'kalkış yöntemi yoksa efekt yok'); ramp2.dispose();
});
test('kayıttan oynatma: tele biçimi aynı (thr/armed/airspeed) → kopter sesi çalışır; dispose sonrası update etkisiz', () => {
  const a = mk('multirotor', { replay: true }); a.unlock();
  for (let i = 0; i < 20; i++) tick(a, { armed: true, throttle: 55, airspeed: 4, groundspeed: 4, mode: 'AUTO' });
  assert.ok(a.graph.copter.bus.gain.value > 0.3);
  const u = a.stats.updates; a.dispose(); tick(a, { armed: true, throttle: 55 }); assert.equal(a.stats.updates, u);
});
test('performans: 50 Hz tele → ≤ 25 Hz işleme; parametre yazımı sınırlı', () => {
  const a = mk('multirotor', { getSim: () => fakeSim() }); a.unlock();
  for (let i = 0; i < 100; i++) tick(a, { armed: true, throttle: 50 }, 20);   // 2 sn, 50 Hz
  assert.ok(a.stats.updates <= 51 && a.stats.updates >= 45, `işlenen kare ${a.stats.updates}`);
  assert.ok(a.stats.paramSets / a.stats.updates < 40, 'kare başına < 40 parametre');
  a.dispose();
});
console.log(`\n${n} test geçti`);
