// Uçuş Simülatörü — kayıttan oynatmada kalkış aşamalarının logdan türetilmesi (static/js/modules/flightsim_launch.js, §8/§13) tarayıcısız birim testi.
// Çalıştırma: node tests/test_flightsim_launch.mjs
import assert from 'node:assert/strict';
import { replayLaunchTimeline, replayLaunchPhaseAt, REPLAY_RAMP_RELEASE, LAUNCH_DEFAULTS, launchLabel, surfaceLock, surfaceFit, isFineSample, RIG_LOCK_DELTA, RIG_FINE_ERR } from '../static/js/modules/flightsim_launch.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const FIELDS = ['t', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'vn', 've', 'vd', 'gs', 'as', 'hdg', 'thr', 'mode', 'armed', 'batt_v', 'batt_pct', 'sats', 'fix', 'rc', 'servo'];
const FI = Object.fromEntries(FIELDS.map((k, i) => [k, i]));
const fr = (t, armed, gs, agl) => { const f = new Array(FIELDS.length).fill(null); f[FI.t] = t; f[FI.armed] = armed; f[FI.gs] = gs; f[FI.alt_rel] = agl; return f; };
// Senaryo (25 Hz yerine 1 Hz yeter): 0–9 yerde disarm · 10 ARM (kalibrasyon) · 14 DISARM · 20 ARM · 24 ilk hareket (gs 3) · 26 gs 10 (rampa bırakma) · 30 AGL 20 · 60 DISARM
const frames = [];
for (let t = 0; t <= 70; t++) {
  const armed = (t >= 10 && t < 14) || (t >= 20 && t < 60) ? 1 : 0;
  const gs = t < 24 ? 0 : t < 26 ? 3 : t < 28 ? 10 : t < 60 ? 22 : 0;
  const agl = t < 27 ? 0 : t < 30 ? (t - 26) * 1.2 : t < 60 ? 20 : 0;
  frames.push(fr(t, armed, gs, agl));
}
test('zaman çizelgesi: iki ARM segmenti; kalibrasyon segmenti hareketsiz (launch/release null), kalkış segmenti arm/launch/release/disarm', () => {
  const segs = replayLaunchTimeline(frames, FI, { method: 'ramp', angle_deg: 15 });
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[0], { arm: 10, launch: null, release: null, disarm: 14 });
  assert.equal(segs[1].arm, 20); assert.equal(segs[1].launch, 24, 'ilk hareket gs > 2'); assert.equal(segs[1].release, 26, `rampa: gs ≥ ${REPLAY_RAMP_RELEASE}`); assert.equal(segs[1].disarm, 60);
});
test('aşama(t): idle → armed → (kalibrasyon DISARM) idle → armed → launch → released; uçuş sonu DISARM\'da released kalır', () => {
  const segs = replayLaunchTimeline(frames, FI, { method: 'ramp' });
  assert.equal(replayLaunchPhaseAt(segs, 0), 'idle'); assert.equal(replayLaunchPhaseAt(segs, 9.9), 'idle');
  assert.equal(replayLaunchPhaseAt(segs, 10), 'armed'); assert.equal(replayLaunchPhaseAt(segs, 13.5), 'armed');
  assert.equal(replayLaunchPhaseAt(segs, 14), 'idle', 'hareketsiz segmentin DISARM\'ı → düzenek başa');
  assert.equal(replayLaunchPhaseAt(segs, 20), 'armed'); assert.equal(replayLaunchPhaseAt(segs, 23.9), 'armed');
  assert.equal(replayLaunchPhaseAt(segs, 24), 'launch'); assert.equal(replayLaunchPhaseAt(segs, 25.5), 'launch');
  assert.equal(replayLaunchPhaseAt(segs, 26), 'released'); assert.equal(replayLaunchPhaseAt(segs, 45), 'released');
  assert.equal(replayLaunchPhaseAt(segs, 60), 'released'); assert.equal(replayLaunchPhaseAt(segs, 70), 'released');
  assert.equal(replayLaunchPhaseAt([], 5), 'idle'); assert.equal(replayLaunchPhaseAt(null, 5), 'idle');
});
test('yönteme göre bırakma eşiği: araç %95 bırakma hızı (72 km/h → 19 m/s → gs 22\'de), tekerlekli AGL > 1 m; AGL artışı da bırakır (rampa > 3 m)', () => {
  const veh = replayLaunchTimeline(frames, FI, { method: 'vehicle', release_kmh: 72 });
  assert.equal(veh[1].launch, 24); assert.equal(veh[1].release, 28, 'gs 22 ≥ 19 m/s');
  const wh = replayLaunchTimeline(frames, FI, { method: 'wheels' });
  assert.equal(wh[1].release, 27, 'AGL 1,2 > 1 m (gs eşiği yok)');
  const slow = []; for (let t = 0; t <= 20; t++) slow.push(fr(t, t >= 2 ? 1 : 0, t >= 5 ? 4 : 0, t >= 8 ? (t - 7) * 1.5 : 0));   // yavaş uçak: gs 4 sabit, irtifa artıyor
  const r = replayLaunchTimeline(slow, FI, { method: 'ramp' });
  assert.equal(r[0].launch, 5); assert.equal(r[0].release, 10, 'AGL 4,5 > 3 m ile bırakma'); assert.equal(r[0].disarm, null);
  assert.equal(replayLaunchPhaseAt(r, 20), 'released');
});
test('AGL referansı ARM anı (baro kayması): ARM anında AGL 5 m olan kayıtta hareket AGL artışıyla ölçülür', () => {
  const fs = []; for (let t = 0; t <= 10; t++) fs.push(fr(t, t >= 2 ? 1 : 0, 0, 5 + (t >= 6 ? (t - 5) * 2 : 0)));
  const segs = replayLaunchTimeline(fs, FI, { method: 'ramp' });
  assert.equal(segs[0].launch, 6, 'AGL 5 → 7: artış 2 > 0,5'); assert.equal(segs[0].release, 7, 'artış 4 > 3');
  assert.equal(replayLaunchPhaseAt(segs, 4), 'armed');
});
test('yardımcılar: varsayılanlar ve etiket', () => {
  assert.deepEqual(LAUNCH_DEFAULTS, { method: 'wheels', angle_deg: 15, release_kmh: 70 });
  assert.equal(launchLabel({ method: 'ramp', angle_deg: 20 }), 'Rampa 20°'); assert.equal(launchLabel({ method: 'vehicle', release_kmh: 72 }), 'Araç 72 km/h'); assert.equal(launchLabel(null), 'Tekerlekli');
});
// ---------- §13 yüzey kilidi (surfaceLock / surfaceFit): Google 3B karo niteliğiyle kabul ----------
const F = (z, err = 0.5) => ({ z, fine: true, err, dem: 0 });     // ince karo örneği
const C = (z, err = 60) => ({ z, fine: false, err, dem: 0 });     // kaba/kök karo örneği
test('ilk örnekler kaba (kök karo −280 m): değer KULLANILMAZ → DEM yedeği (0), kilit yok; 8 m eşiği yok (ince 12 m kabul edilir)', () => {
  let L = surfaceLock(null, [C(-280), C(-281), C(-279), C(-280)]);
  assert.deepEqual(L.hs, [0, 0, 0, 0]); assert.equal(L.locked, false); assert.equal(L.event, 'init');
  L = surfaceLock(L, [F(12.1), F(12.3), F(11.9), F(12.0)]);   // eğimli/dağlık merkez: ince karoda |h| > 8 m gerçek değerdir
  assert.deepEqual(L.hs, [12.1, 12.3, 11.9, 12.0]); assert.equal(L.locked, true); assert.equal(L.event, 'lock'); assert.equal(L.err, 0.5);
});
test('kısmen ince: önceki kabul edilmiş değer korunur (hold); hiç değer yokken ince olanlar alınır, kaba olanlar DEM ile dolar', () => {
  let L = surfaceLock(null, [F(1.0), C(-50), F(1.2), { z: 1.1, fine: false, err: 30, dem: 0.9 }]);
  assert.deepEqual(L.hs, [1.0, 0, 1.2, 0.9]); assert.equal(L.locked, false); assert.equal(L.event, 'init');
  const L2 = surfaceLock(L, [C(-100), C(-100), C(-100), C(-100)]);
  assert.deepEqual(L2.hs, L.hs); assert.equal(L2.event, 'hold'); assert.equal(L2.locked, false);
});
test('kilitliyken küçük düzeltme (|Δ| ≤ 0,35) uygulanır, büyük sıçrama (LOD kabalaşması / başka karo) yok sayılır; ince bayrağı düşerse eski değer kalır', () => {
  let L = surfaceLock(null, [F(2.0), F(2.1), F(2.2), F(2.3)]);
  L = surfaceLock(L, [F(2.2), F(2.1), F(5.0), F(2.3)]);          // 3. nokta +2,8 m: yok say
  assert.deepEqual(L.hs, [2.2, 2.1, 2.2, 2.3]); assert.equal(L.event, 'ignore'); assert.equal(L.ignored, 1); assert.equal(L.locked, true);
  L = surfaceLock(L, [F(2.2), F(2.1), C(40), F(2.3)]);           // kaba karo geri geldi: tut
  assert.deepEqual(L.hs, [2.2, 2.1, 2.2, 2.3]); assert.equal(L.event, 'hold'); assert.equal(L.locked, true);
  L = surfaceLock(L, [F(2.25), F(2.0), F(2.25), F(2.3)]);
  assert.deepEqual(L.hs, [2.25, 2.0, 2.25, 2.3]); assert.equal(L.event, 'adjust');
  assert.equal(RIG_LOCK_DELTA, 0.35); assert.equal(RIG_FINE_ERR, 2);
});
test('daha ince karo gelince (geometricError küçüldü) yeniden kilitlenir: büyük fark da kabul edilir', () => {
  let L = surfaceLock(null, [F(2.0, 1.8), F(2.0, 1.8), F(2.0, 1.8), F(2.0, 1.8)]);
  assert.equal(L.err, 1.8);
  L = surfaceLock(L, [F(3.5, 0.6), F(3.4, 0.6), F(3.6, 0.6), F(3.5, 0.6)]);
  assert.deepEqual(L.hs, [3.5, 3.4, 3.6, 3.5]); assert.equal(L.event, 'relock'); assert.equal(L.err, 0.6);
  L = surfaceLock(L, [F(1.0, 1.8), F(1.0, 1.8), F(1.0, 1.8), F(1.0, 1.8)]);   // kabalaştı: sıçrama yok sayılır
  assert.deepEqual(L.hs, [3.5, 3.4, 3.6, 3.5]); assert.equal(L.event, 'ignore'); assert.equal(L.ignored, 4);
});
test('Google yer ofseti değişince (karolar toptan kaydı) saklı değerler aynı miktarda kayar; yaprak karo da ince sayılır (isFineSample yalnız bayrağa bakar)', () => {
  let L = surfaceLock(null, [F(1.0), F(1.0), F(1.0), F(1.0)], -30);
  L = surfaceLock(L, [C(0), C(0), C(0), C(0)], -32.5);   // ofset −30 → −32,5: yüzey 2,5 m aşağı kaydı
  assert.deepEqual(L.hs.map(v => +v.toFixed(3)), [-1.5, -1.5, -1.5, -1.5]); assert.equal(L.event, 'hold'); assert.equal(L.offset, -32.5);
  L = surfaceLock(L, [F(-1.4), F(-1.5), F(-1.6), F(-1.5)], -32.5);   // ince karolarla küçük düzeltme (kayma sonrası sıçrama olmaz)
  assert.equal(L.event, 'adjust');
  assert.equal(isFineSample({ z: 1, fine: true, err: 5 }), true); assert.equal(isFineSample({ z: 1, fine: false, err: 0 }), false); assert.equal(isFineSample(null), false);
});
test('surfaceFit: ortalama z, ileri yükseliş → +pitch, sağ yükseliş → −roll, ±20° sınırı', () => {
  let f = surfaceFit([0, 0, 1, 1], 1.9, 2.6);
  assert.equal(+f.z.toFixed(3), 0.5); assert.equal(+(f.p * 180 / Math.PI).toFixed(1), 20.0, 'atan2(1, 2,6) = 21° → 20° sınırı'); assert.equal(Math.abs(f.r), 0);
  f = surfaceFit([0, 0.2, 0, 0.2], 1.9, 2.6);
  assert.equal(Math.abs(f.p), 0); assert.ok(f.r < 0, 'sağ yüksek → roll negatif'); assert.equal(+(f.r * 180 / Math.PI).toFixed(1), -6.0);
  f = surfaceFit([0, 0, 0.3, 0.3], 1.9, 2.6);
  assert.equal(+(f.p * 180 / Math.PI).toFixed(1), 6.6);
});
console.log(`\n${n} test geçti`);
