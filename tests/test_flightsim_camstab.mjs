// Uçuş Simülatörü — araç kamerası titreme düzeltmesi (flightsim_camera.js stabStep / CAM_STAB_TAU) tarayıcısız birim testi.
// Kök neden: gerçek ArduCopter SITL askıda gövde yönelimi ~16 Hz'de ±1,5–2° salınır (tests/data/sitl_copter_hover_att.json: ALT_HOLD askı, 20 ms
// ATTITUDE kareleri); gövdeye sabit gimbal kamerası bu salınımı tüm görüntüye taşıyordu. Burada kayıt flightsim_interp.js zaman çizgisinden 60 / 30 fps
// "render" edilir; kameranın ardışık kareler arası açı değişimi (asılı dronda gerçek hareket ≈ 0) ham ve süzülmüş yönelimle ölçülür.
// Çalıştırma: node tests/test_flightsim_camstab.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as T from '../static/vendor/three/three.module.min.js';
import { createTimeline } from '../static/js/modules/flightsim_interp.js';
import { CAM_STAB_TAU, stabStep } from '../static/js/modules/flightsim_camera.js';

const DEG = Math.PI / 180;
const F = JSON.parse(fs.readFileSync(new URL('./data/sitl_copter_hover_att.json', import.meta.url), 'utf8')).f;
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

// Gimbal kamerası yönelimi: gövde · Rx(90° + gimbal) (flightsim3d.js poseGimbal ile aynı)
const gimbalQ = (q, gimbalDeg = -49) => q.clone().multiply(new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), (90 + gimbalDeg) * DEG));

function render(fps, tau) {
  const tl = createTimeline(T);
  const t0 = F[0][0], dtMs = 1000 / fps, stab = new T.Quaternion();
  let k = 0, has = false, prev = null;
  const steps = [];
  for (let now = 0; now < F[F.length - 1][0] - t0 - 200; now += dtMs) {
    while (k < F.length && F[k][0] - t0 <= now) {   // kare tbm anında (+ sabit ağ gecikmesi) gelir
      const [tbm, roll, pitch, yaw, rs, ps, ys] = F[k++];
      tl.push({ x: 0, y: 0, alt_rel: 40, roll, pitch, yaw, rs, ps, ys, tbm, tbm_pos: tbm }, now);
    }
    tl.advance(dtMs);
    if (!has) { stab.copy(tl.cur.q); has = true; } else if (tau > 0) stabStep(stab, tl.cur.q, dtMs / 1000, tau); else stab.copy(tl.cur.q);
    const cam = gimbalQ(stab);
    if (prev && now > 1000) steps.push(cam.angleTo(prev) / DEG);   // ilk 1 sn: tampon oturması
    prev = cam;
  }
  steps.sort((a, b) => a - b);
  return { mean: steps.reduce((a, b) => a + b, 0) / steps.length, p95: steps[Math.floor(steps.length * 0.95)], n: steps.length };
}

console.log('Kayıt (gerçek SITL askı)');
test('kayıtta yüksek frekanslı salınım var (kök neden: ardışık 20 ms karede roll/pitch işaret değiştirir, ±1,5° üstü)', () => {
  let flips = 0, amp = 0;
  for (let i = 2; i < F.length; i++) { if ((F[i][1] - F[i - 1][1]) * (F[i - 1][1] - F[i - 2][1]) < 0) flips++; amp = Math.max(amp, Math.abs(F[i][1]) / DEG); }
  assert.ok(flips / (F.length - 2) > 0.4, `işaret dönüşü ${flips}`);
  assert.ok(amp > 1.5, `genlik ${amp}`);
});

console.log('Gimbal kamerası titremesi (kare → kare açı değişimi, °)');
for (const fps of [60, 30]) {
  test(`${fps} fps: ham (süzgeçsiz) gövde kamerası titrer, stabilize gimbal ≥ 8× sakin ve ortalama < 0,12° / (1/60 sn)`, () => {
    const raw = render(fps, 0), st = render(fps, CAM_STAB_TAU.gimbal);
    console.log(`      ham ort ${raw.mean.toFixed(3)}° p95 ${raw.p95.toFixed(3)}° · stabilize ort ${st.mean.toFixed(3)}° p95 ${st.p95.toFixed(3)}° (${st.n} kare)`);
    assert.ok(raw.mean > 0.4, `ham titreme beklenenden küçük: ${raw.mean}`);
    const per = 60 / fps;   // eşik 1/60 sn başına (30 fps'te kare süresi iki kat)
    assert.ok(st.mean < 0.12 * per && st.p95 < 0.2 * per, `stabilize: ${JSON.stringify(st)}`);
    assert.ok(raw.mean / st.mean >= 8, `sönüm ${raw.mean / st.mean}`);
  });
}
test('FPV (τ pilot) en az 3× sönüm', () => {
  const raw = render(60, 0), st = render(60, CAM_STAB_TAU.pilot);
  assert.ok(raw.mean / st.mean >= 3, `FPV sönüm ${raw.mean / st.mean}`);
});

console.log('stabStep davranışı');
test('kasıtlı dönüş (45°/s yaw) gecikmesi küçük: kararlı durumda ≈ ω·τ', () => {
  const q = new T.Quaternion(), tgt = new T.Quaternion(), ax = new T.Vector3(0, 0, 1);
  let yaw = 0;
  for (let i = 0; i < 120; i++) { yaw += 45 * DEG / 60; tgt.setFromAxisAngle(ax, yaw); stabStep(q, tgt, 1 / 60, CAM_STAB_TAU.gimbal); }
  const lag = q.angleTo(tgt) / DEG;
  assert.ok(lag < 45 * CAM_STAB_TAU.gimbal * 1.15 + 0.2, `gecikme ${lag}°`);
});
test('büyük sıçrama (reset / ışınlanma) doğrudan alınır; dt 0 → değişmez; τ 0 → doğrudan', () => {
  const q = new T.Quaternion(), tgt = new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 0, 1), 120 * DEG);
  stabStep(q, tgt, 1 / 60, 0.12);
  assert.ok(q.angleTo(tgt) < 1e-6);
  const a = new T.Quaternion(), b = new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), 5 * DEG);
  stabStep(a, b, 0, 0.12); assert.ok(a.angleTo(new T.Quaternion()) < 1e-9);
  stabStep(a, b, 1 / 60, 0); assert.ok(a.angleTo(b) < 1e-6);
});
test('kare hızından bağımsız: 60 fps ve 30 fps aynı süre sonunda aynı yönelime yakınsar', () => {
  const tgt = new T.Quaternion().setFromAxisAngle(new T.Vector3(1, 0, 0), 10 * DEG);
  const a = new T.Quaternion(), b = new T.Quaternion();
  for (let i = 0; i < 12; i++) stabStep(a, tgt, 1 / 60, 0.2);
  for (let i = 0; i < 6; i++) stabStep(b, tgt, 1 / 30, 0.2);
  assert.ok(Math.abs(a.angleTo(tgt) - b.angleTo(tgt)) / DEG < 0.05);
});
console.log(`\n${n} test geçti`);
