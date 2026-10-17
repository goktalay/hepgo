// Uçuş Simülatörü — telemetri zaman çizgisi (static/js/modules/flightsim_interp.js, §5) tarayıcısız ölçüm ve kabul testi.
// Sentetik 50 Hz kaynak (sabit kanat, daire: 30 m/s, yaw hızı 0,1 rad/s, hafif roll salınımı; ATTITUDE ve GLOBAL_POSITION_INT farklı
// time_boot_ms) → ağ bozulması (taban gecikme + U(0, 2·jitter) alım jitter'ı, %kayıp, sırası bozulan teslim, SITL saat sapması) →
// sanal rAF (60 / 25 fps) → ardışık render kareleri arası yönelim farkı (°) ve pürüzsüzlük (jerk = ardışık farkların farkı; sabit
// açısal hızda 0), konum jerk (m), DR giriş sayısı/dk. Karşılaştırma: ESKİ algoritma (9e639ef: sabit 80 ms tampon, "min(alım−kaynak)"
// saat ofseti, tek zaman çizgisi, DR'den sert çıkış) bu dosyada aynı arayüzle yeniden uygulanmıştır.
// Çalıştırma: node tests/test_flightsim_interp.mjs   (vendor three.module.min.js tarayıcısız yüklenir)
import * as T from '../static/vendor/three/three.module.min.js';
import { createTimeline, attitudeQuat, DR_MAX } from '../static/js/modules/flightsim_interp.js';

const DEG = Math.PI / 180;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// ---- ESKİ algoritma (flightsim3d.js @9e639ef setTelemetry/sample; ölçüm için aynı motionStats) ----
function createOldTimeline() {
  const RENDER_DELAY = 80, BUF_MAX = 64;
  const buf = [];
  const tele = { has: false, at: 0, src: 0, offset: null };
  const net = { dr: false, drEnters: 0, t0: 0, now: 0 };
  const cur = { pos: new T.Vector3(), q: new T.Quaternion(), vel: new T.Vector3() };
  const tmpQa = new T.Quaternion(), tmpAx = new T.Vector3();
  const mot = { n: 0, ang: 0, angMax: 0, jerk: 0, lastAng: -1, posJerk: 0, lastPos: -1, drFrames: 0, qPrev: new T.Quaternion(), pPrev: new T.Vector3(), has: false };
  function push(t, now) {
    let src = t.tbm;
    if (tele.has && src <= tele.src) src = tele.src + 1;
    const d = now - src;
    tele.offset = tele.offset == null ? d : Math.min(d, tele.offset + (now - tele.at) * 0.002);
    buf.push({ src, pos: new T.Vector3(t.x, t.y, t.alt_rel), q: attitudeQuat(T, t.roll, t.pitch, t.yaw), vel: new T.Vector3(t.ve, t.vn, -t.vd), rx: t.ps, ry: t.rs, rz: -t.ys });
    if (buf.length > BUF_MAX) buf.splice(0, buf.length - BUF_MAX);
    tele.at = now; tele.src = src;
    if (!tele.has) { tele.has = true; net.t0 = now; net.now = now; cur.pos.copy(buf[0].pos); cur.q.copy(buf[0].q); }
  }
  function advance(rawMs) {
    net.now += rawMs;
    const rt = net.now - RENDER_DELAY, n = buf.length;
    if (!n) return;
    const off = tele.offset, last = buf[n - 1], tl = last.src + off;
    let dr = false;
    if (rt >= tl) {
      const dt = Math.min(DR_MAX, rt - tl) / 1000;
      dr = rt - tl > 40;
      cur.pos.copy(last.pos).addScaledVector(last.vel, dt); cur.vel.copy(last.vel);
      tmpAx.set(last.rx * dt, last.ry * dt, last.rz * dt); const ang = tmpAx.length(); cur.q.copy(last.q);
      if (ang > 1e-6) { tmpQa.setFromAxisAngle(tmpAx.multiplyScalar(1 / ang), ang); cur.q.multiply(tmpQa); }
      if (n > 1) buf.splice(0, n - 1);
    } else {
      let i = n - 1;
      while (i > 0 && buf[i - 1].src + off > rt) i--;
      if (i === 0) { cur.pos.copy(buf[0].pos); cur.q.copy(buf[0].q); cur.vel.copy(buf[0].vel); }
      else { const a = buf[i - 1], b = buf[i], span = b.src - a.src, f = span > 0 ? clamp((rt - (a.src + off)) / span, 0, 1) : 1; cur.pos.lerpVectors(a.pos, b.pos, f); cur.q.slerpQuaternions(a.q, b.q, f); cur.vel.lerpVectors(a.vel, b.vel, f); if (i > 1) buf.splice(0, i - 1); }
    }
    if (dr && !net.dr) net.drEnters++;
    net.dr = dr;
    if (mot.has) {
      const ang = 2 * Math.acos(clamp(Math.abs(mot.qPrev.dot(cur.q)), 0, 1)) / DEG, d = mot.pPrev.distanceTo(cur.pos);
      mot.n++; mot.ang += ang; mot.angMax = Math.max(mot.angMax, ang);
      if (mot.lastAng >= 0) { mot.jerk += Math.abs(ang - mot.lastAng); mot.posJerk += Math.abs(d - mot.lastPos); }
      mot.lastAng = ang; mot.lastPos = d; if (dr) mot.drFrames++;
    }
    mot.qPrev.copy(cur.q); mot.pPrev.copy(cur.pos); mot.has = true;
  }
  const motionStats = () => ({ frames: mot.n, angMean: mot.ang / Math.max(1, mot.n), angMax: mot.angMax, angJerk: mot.jerk / Math.max(1, mot.n - 1), posJerk: mot.posJerk / Math.max(1, mot.n - 1), drEnters: net.drEnters, drFrames: mot.drFrames, secs: (net.now - net.t0) / 1000 });
  return { push, advance, cur, motionStats, netStats: () => ({ delay: RENDER_DELAY, drEnters: net.drEnters }) };
}

// ---- sentetik kaynak: daire uçuşu; ATTITUDE (tbm) ve GLOBAL_POSITION_INT (tbm_pos) ayrı damgalar ----
function source(tSrcMs, { posLag = 0 } = {}) {
  const V = 30, R = 300, w = V / R;                       // rad/s (0,1)
  const tt = tSrcMs / 1000, tp = (tSrcMs - posLag) / 1000;   // konum damgası ATTITUDE'dan posLag ms önce alınmış
  const yaw = w * tt, roll = Math.atan(V * V / (R * 9.81)) + 0.05 * Math.sin(tt * 2), pitch = 0.05;
  return { tbm: Math.round(tSrcMs), tbm_pos: Math.round(tSrcMs - posLag), roll, pitch, yaw, rs: 0.1 * Math.cos(tt * 2), ps: 0, ys: w,
    x: R * Math.sin(w * tp), y: R * Math.cos(w * tp), alt_rel: 80, ve: V * Math.cos(w * tp), vn: -V * Math.sin(w * tp), vd: 0 };
}

// ---- koşu: ağ bozulması + sanal rAF ----
// opts: jitter (ms; alım = src/clockRate + base + U(0, 2·jitter)), loss (%), base (ms), fps, secs, clockRate (SITL saati: 1,0 = gerçek zaman;
// 0,97 = kaynak saat %3 yavaş; 0,6 / 1,6 yük altında yavaş / yetişme), posLag (ms; konum damgası farkı; 'rand' → U(0, 20)), seed
function run(make, o) {
  const r = rng(o.seed || 7);
  const tl = make();
  const events = [];                                      // {at, t} alım zamanı (istemci ms)
  const n = Math.ceil(o.secs * 50) + 60;
  for (let k = 0; k < n; k++) {
    const src = k * 20;
    if (r() * 100 < (o.loss || 0)) continue;
    const posLag = o.posLag === 'rand' ? r() * 20 : (o.posLag || 0);
    const at = 1000 + src / (o.clockRate || 1) + (o.base || 40) + r() * 2 * (o.jitter || 0);
    events.push({ at, t: source(src, { posLag }) });
  }
  events.sort((a, b) => a.at - b.at);                     // alım sırası (jitter sırayı bozabilir)
  const step = 1000 / (o.fps || 60);
  let now = 1000, ei = 0, measuring = false, t0 = null;
  const end = 1000 + o.secs * 1000;
  while (now < end) {
    while (ei < events.length && events[ei].at <= now) { tl.push(events[ei].t, events[ei].at); ei++; }
    if (tl.has || tl.cur) {
      if (!t0) t0 = now;
      if (!measuring && now - t0 > 5000) { measuring = true; if (tl.motionStats.length) tl.motionStats(true); }   // ilk 5 sn ısınma (uyarlanır tampon otursun)
      tl.advance(step);
    }
    now += step;
  }
  const m = tl.motionStats(false);
  const ideal = 0.1 * step / 1000 / DEG;                  // sabit yaw hızında ideal kare adımı (°)
  return { angMean: +m.angMean.toFixed(4), ideal: +ideal.toFixed(4), angMax: +m.angMax.toFixed(3), angJerk: +m.angJerk.toFixed(4), posJerk: +m.posJerk.toFixed(4), drEnters: m.drEnters, drPerMin: +(m.drEnters * 60 / Math.max(1, m.secs)).toFixed(1), drFrames: m.drFrames, frames: m.frames, delay: tl.netStats().delay };
}

const yeniMake = () => createTimeline(T);
const eskiMake = () => createOldTimeline();
const senaryolar = [
  ['temiz ağ (jitter 0, kayıp 0), 60 fps', { jitter: 0, loss: 0, fps: 60, secs: 20 }],
  ['jitter 30 ms + %5 kayıp, 60 fps', { jitter: 30, loss: 5, fps: 60, secs: 30 }],
  ['jitter 30 ms + %5 kayıp, 25 fps (Google 3B)', { jitter: 30, loss: 5, fps: 25, secs: 30 }],
  ['jitter 30 + kayıp 5 + konum damgası U(0,20) ms kayık (yarım kare)', { jitter: 30, loss: 5, fps: 60, secs: 30, posLag: 'rand' }],
  ['jitter 10 + SITL saati %3 yavaş (saat sapması)', { jitter: 10, loss: 0, fps: 60, secs: 40, clockRate: 0.97 }],
  ['jitter 60 ms + %10 kayıp (kötü tünel)', { jitter: 60, loss: 10, fps: 60, secs: 30 }],
  ['jitter 20 + SITL saati 0,6× (CPU yükü)', { jitter: 20, loss: 2, fps: 60, secs: 40, clockRate: 0.6 }],
  ['jitter 20 + SITL saati 1,6× (yetişme)', { jitter: 20, loss: 2, fps: 60, secs: 40, clockRate: 1.6 }],
];
let fail = 0;
const ref = { 60: run(eskiMake, { jitter: 0, loss: 0, fps: 60, secs: 20 }).angMean, 25: run(eskiMake, { jitter: 0, loss: 0, fps: 25, secs: 20 }).angMean };   // temiz ağda eski kodun ortalama adımı = referans
const satir = (ad, m) => `${ad.padEnd(5)} adım ${m.angMean}° (ideal ${m.ideal}) · maks ${m.angMax}° · jerk ${m.angJerk}° · konum jerk ${m.posJerk} m · DR ${m.drEnters} (${m.drPerMin}/dk, ${m.drFrames} kare) · tampon ${m.delay} ms`;
for (const [ad, o] of senaryolar) {
  const y = run(yeniMake, o), e = run(eskiMake, o);
  console.log(`\n${ad}\n  ${satir('eski', e)}\n  ${satir('yeni', y)}  (referans adım ${ref[o.fps].toFixed(4)}°)`);
  const kontrol = (k, c) => { if (!c) { fail++; console.log('  BAŞARISIZ:', k); } };
  const cr = o.clockRate || 1;   // kaynak saati gerçek zamandan hızlı/yavaşsa render adımı da o oranda
  kontrol('yeni ortalama adım temiz-ağ referansına yakın (±%6, saat oranıyla ölçekli)', Math.abs(y.angMean - ref[o.fps] * cr) < 0.06 * ref[o.fps] * cr);
  kontrol('yeni jerk ≤ 0,02° (pürüzsüz)', y.angJerk <= 0.02 * Math.max(1, o.clockRate || 1));
  kontrol('yeni maks adım < 4× ideal', y.angMax < 4 * y.ideal * (o.clockRate || 1) + 0.01);
  kontrol('yeni DR ≤ 2/dk', y.drPerMin <= 2);
  if (o.jitter >= 30 || o.clockRate) kontrol('yeni jerk < eski jerk / 2', y.angJerk < e.angJerk / 2 || e.angJerk < 0.01);
  if (o.posLag === 'rand') kontrol('yarım kare: yeni konum jerk < eski / 2', y.posJerk < e.posJerk / 2);
}
// sırası bozuk teslim: aynı kareler karışık sırada → sıralı tamponda sonuç sıralı teslimle aynı
{
  const a = createTimeline(T), b = createTimeline(T);
  const fr = Array.from({ length: 10 }, (_, k) => source(k * 20));
  fr.forEach((t, k) => a.push(t, 1000 + k * 20 + 40));
  [0, 2, 1, 4, 3, 6, 5, 8, 7, 9].forEach((k, i) => b.push(fr[k], 1000 + i * 20 + 40));
  for (let i = 0; i < 20; i++) { a.advance(16.67); b.advance(16.67); }
  const d = 2 * Math.acos(clamp(Math.abs(a.cur.q.dot(b.cur.q)), 0, 1)) / DEG, dp = a.cur.pos.distanceTo(b.cur.pos);
  console.log(`\nsırası bozuk teslim: yönelim farkı ${d.toFixed(4)}°, konum farkı ${dp.toFixed(3)} m`);
  if (d > 0.5 || dp > 1) { fail++; console.log('  BAŞARISIZ: sıralı ekleme'); }
}
// saat geri gitti (SITL yeniden başladı): yeniden senkron, hata yok
{
  const a = createTimeline(T);
  for (let k = 0; k < 100; k++) a.push(source(k * 20), 1000 + k * 20 + 40);
  for (let i = 0; i < 60; i++) a.advance(16.67);
  for (let k = 0; k < 100; k++) a.push(source(k * 20), 4000 + k * 20 + 40);   // tbm 0'dan yeniden
  for (let i = 0; i < 60; i++) a.advance(16.67);
  const s = a.netStats();
  console.log(`\nsaat sıfırlama: snaps ${s.snaps}, DR ${s.deadReckoning}, tampon ${s.delay} ms, oynatma başı ${Math.round(s.play)} ms, son kare ${a.src} ms`);
  // yeniden senkron: oynatma başı yeni (0'dan başlayan) kaynak ekseninde; kareler bir anda geldi → son kare + 1 sn ilerleme (ölü hesap sınırı) civarı
  if (!(s.snaps >= 1) || a.src !== 1980 || !(s.play > 1500 && s.play < 3500)) { fail++; console.log('  BAŞARISIZ: saat sıfırlama'); }
}
if (fail) { console.log(`\n${fail} kontrol BAŞARISIZ`); process.exit(1); }
console.log('\nTelemetri zaman çizgisi testleri geçti.');
