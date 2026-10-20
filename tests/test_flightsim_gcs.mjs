// Uçuş Simülatörü §26 yer kontrol sahası + "Yer kontrolünü koru" — saf modül testleri (tarayıcısız): static/js/modules/flightsim_gcs.js
// • siteLayout / radarCovers / eoLook: sunucu app/flightsim_gcs (yerlesim, radar_kapsar, eo_bakis) ile AYNI sayılar
// • mulberry32 + defendPlan: sunucu savunma_plani ile bit düzeyinde aynı (vektörler Python'dan); tohum determinizmi
// • threatGeometry / threatState: seyir → dalış → çarpma (Python vektörleri), fallState, threatPhase
// • radar tarama: sweepAngle, sweepGlow, radarSteps, autoRadarRange; EO: eoZoom, eoStatus
// • createDefendTracker (sunucu SavunmaGorevi eşleniği): dalga/doğuş, ARM şartlı önleme, sızma, bitiş, yeniden konuşlandırma; scoreDefend/rankOf
// • validateSite / siteBody / validateDefend; nextWave; defendStateAt (kayıt); SITE_TEXTS anahtarları + çevirmen
// Çalıştırma: node tests/test_flightsim_gcs.mjs
import assert from 'node:assert/strict';
import {
  siteLayout, radarCovers, eoLook, eoZoom, eoStatus, sweepAngle, sweepGlow, bearingFrom, radarSteps, autoRadarRange, mulberry32, defendPlan, threatGeometry, threatState,
  fallState, threatPhase, scoreDefend, rankOf, createDefendTracker, validateSite, siteBody, validateDefend, nextWave, defendStateAt, STATION_Z, EO_FOV_MAX, EO_FOV_MIN, FALL_S,
} from '../static/js/modules/flightsim_gcs.js';
import * as M from '../static/js/modules/flightsim_gcs_ui.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, eps = 1e-5, msg) => assert.ok(Math.abs(a - b) <= eps, msg || `${a} ≈ ${b}`);
const ST = { x: 55, y: -40, z: STATION_Z };
console.log('flightsim_gcs.js');

test('yerleşim (sunucu yerlesim): pist yönüne göre istasyon / kule / raf', () => {
  const L0 = siteLayout(0), L90 = siteLayout(90);
  assert.deepEqual(L0.station, { x: 55, y: -40, yaw_deg: 0 }); assert.deepEqual(L0.tower, { x: 85, y: -40, yaw_deg: 0 }); assert.deepEqual(L0.rack, { x: 34, y: -14, yaw_deg: 0 });
  assert.deepEqual(L90.station, { x: -40, y: -55, yaw_deg: 90 });
  assert.equal(L0.station_z, STATION_Z); assert.equal(L0.sweep_s, 4);
});

test('radar kapsaması + EO bakış açıları (sunucu ile aynı)', () => {
  const T0 = siteLayout(0).tower, site = { radar: true, radar_km: 20 };
  assert.ok(radarCovers(site, T0, 85 + 19999, -40)); assert.ok(!radarCovers(site, T0, 85 + 20001, -40)); assert.ok(!radarCovers({ radar: false, radar_km: 20 }, T0, 85, -40));
  const lk = eoLook(T0, 85, 960, 18 + 1000);
  near(lk.az, 0, 1e-9); near(lk.el, 45, 1e-9); near(lk.range_m, 1000 * Math.SQRT2, 1e-6);
  near(eoLook(T0, -15, -40, 18).az, 270, 1e-9); near(eoLook(T0, 85, -140, 18).az, 180, 1e-9);
  near(bearingFrom(T0, 185, -40), 90, 1e-9);
});

test('mulberry32 bit düzeyinde sunucuyla aynı', () => {
  const r = mulberry32(42);
  assert.deepEqual([r(), r(), r()], [0.6011037519201636, 0.44829055899754167, 0.8524657934904099]);
});

test('görev planı: tohumdan deterministik, sunucu vektörleri', () => {
  const p = defendPlan({ seed: 12345 });
  assert.equal(p.length, 20);
  assert.deepEqual([p[0].model, p[0].spawn_t, p[0].bearing_deg, p[0].dist_m, p[0].alt_m, p[0].dive_deg, p[0].cruise_ms, p[0].dive_ms], ['tgt:octopus', 45, 110.43, 4452.6, 395.4, 37.74, 55.56, 70.83]);
  assert.deepEqual([p[1].model, p[1].spawn_t, p[1].bearing_deg, p[1].dist_m], ['tgt:sw300', 52.43, 275.9, 5990.5]);
  assert.deepEqual([p[3].model, p[3].spawn_t, p[3].bearing_deg, p[3].dist_m, p[3].alt_m, p[3].dive_deg, p[3].cruise_ms, p[3].dive_ms, p[3].damage], ['tgt:lancet', 123.31, 278.07, 5819.3, 343.9, 44.5, 32.08, 75, 35]);
  assert.deepEqual(defendPlan({ seed: 12345 }), p);
  assert.notDeepEqual(defendPlan({ seed: 12346 }), p);
  assert.deepEqual(defendPlan({ seed: 999, difficulty: 'easy', waves: 3 }).map(t => [t.model, t.spawn_t]),
    [['tgt:octopus', 45], ['tgt:altius', 135], ['tgt:sw300', 145.84], ['tgt:lancet', 225], ['tgt:sw300', 238.09], ['tgt:lancet', 246.22]]);
  assert.equal(defendPlan({ seed: 1, waves: 10, difficulty: 'hard' }).length, 60);   // THREAT_MAX
  for (const th of p) assert.ok(th.dive_ms > th.cruise_ms && th.dive_deg >= 25 && th.dive_deg <= 50);
});

test('tehdit kinematiği: seyir → dalış → çarpma (Python vektörleri)', () => {
  const th = defendPlan({ seed: 12345 })[3], g = threatGeometry(th, ST);
  near(g.t_impact, 300.375792, 1e-5);
  assert.equal(threatState(th, th.spawn_t - 0.01, ST, g), null);
  const V = [[133.31, [-5389.049991, 731.895032, 343.9, 31.762321, -4.503481, 0, 98.07, 0], 'cruise'],
    [295.831029, [-185.709071, -5.870604, 241.51, 52.964051, -7.509609, -52.568195, 98.07, -0.776672], 'dive'],
    [300.365792, [54.470359, -39.924904, 3.125682, 52.964051, -7.509609, -52.568195, 98.07, -0.776672], 'dive']];
  for (const [t, v, ph] of V) {
    const s = threatState(th, t, ST, g);
    ['x', 'y', 'z', 'vx', 'vy', 'vz', 'heading', 'pitch'].forEach((k, i) => near(s[k], v[i], 2e-5, `${k} t=${t}: ${s[k]} ≠ ${v[i]}`));
    assert.equal(s.phase, ph);
  }
  const s3 = threatState(th, g.t_impact + 3, ST, g);
  assert.equal(s3.phase, 'impact'); near(s3.x, 55, 1e-6); near(s3.z, STATION_Z, 1e-9);
});

test('düşüş (önlenen) ve yaşam evreleri', () => {
  const th = defendPlan({ seed: 12345 })[0], g = threatGeometry(th, ST), k0 = threatState(th, 60, ST, g);
  const f1 = fallState(k0, 1);
  assert.ok(f1.z < k0.z && f1.phase === 'fall');
  assert.equal(fallState(k0, FALL_S + 0.1), null);
  assert.equal(fallState({ ...k0, z: 2 }, 1, 0), null);   // yere değdi
  assert.equal(threatPhase(th, 44, null, null, g), 'pending');
  assert.equal(threatPhase(th, 50, null, null, g), 'active');
  assert.equal(threatPhase(th, 61, 60, null, g), 'killed');
  assert.equal(threatPhase(th, 60 + FALL_S + 1, 60, null, g), 'gone');
  assert.equal(threatPhase(th, g.t_impact + 0.1, null, null, g), 'gone');
});

test('radar tarama hüzmesi, parıltı, menzil basamakları', () => {
  near(sweepAngle(0), 0); near(sweepAngle(1), 90); near(sweepAngle(4), 0, 1e-9); near(sweepAngle(5.5), 135);
  near(sweepGlow(90, 90), 1, 1e-9);                       // hüzme şimdi üstünde
  assert.ok(sweepGlow(90, 180) < sweepGlow(90, 100));      // geçtikçe söner
  assert.ok(sweepGlow(90, 89) < 0.4 && sweepGlow(90, 89) >= 0.35);   // neredeyse tam tur önce geçti
  assert.deepEqual(radarSteps(20), [1, 2, 5, 10, 20]); assert.deepEqual(radarSteps(12), [1, 2, 5, 10, 12]); assert.deepEqual(radarSteps(50), [1, 2, 5, 10, 20, 50]);
  assert.equal(autoRadarRange([], 20), 1); assert.equal(autoRadarRange([4000], 20), 5); assert.equal(autoRadarRange([4500], 20), 10); assert.equal(autoRadarRange([30000], 20), 20);
});

test('EO yakınlaştırma ve durum', () => {
  const z1 = eoZoom(1000, 3), z2 = eoZoom(4000, 3);
  assert.ok(z2.fov < z1.fov && z2.zoom > z1.zoom);
  near(eoZoom(5, 3).fov, EO_FOV_MAX); near(eoZoom(1e7, 3).fov, EO_FOV_MIN);
  near(eoZoom(1000, 3).fov, 2 * Math.atan(3 / 0.22 / 2 / 1000) * 180 / Math.PI, 1e-9);
  assert.equal(eoStatus({ eo: false }, 1, 100), 'off'); assert.equal(eoStatus({ eo: true, eo_km: 5 }, null, null), 'idle');
  assert.equal(eoStatus({ eo: true, eo_km: 5 }, 2, 5001), 'out'); assert.equal(eoStatus({ eo: true, eo_km: 5 }, 2, 4999), 'track');
});

test('görev izleyicisi (sunucu SavunmaGorevi eşleniği)', () => {
  const L = siteLayout(0), tr = createDefendTracker({ seed: 12345, waves: 1, prep_s: 15 }, L);
  assert.equal(tr.plan.length, 2);
  let ev = tr.step(15, 0, 0, 0, false);
  assert.deepEqual(ev.map(e => e.kind), ['wave', 'spawn']); assert.equal(ev[0].count, 2);
  const k0 = threatState(tr.plan[0], 20, tr.station);
  assert.equal(tr.step(20, k0.x + 10, k0.y, k0.z, false).filter(e => e.kind === 'kill').length, 0);   // disarm
  ev = tr.step(20, k0.x + 10, k0.y, k0.z, true);
  const kill = ev.find(e => e.kind === 'kill');
  assert.ok(kill && kill.k === 0 && kill.dist_m === 10 && kill.ttk_s === 5 && kill.interceptor === 1);
  assert.equal(tr.redeploy(), true); assert.equal(tr.redeploy(), false);   // uçmuş → harcanır; uçmamış → ücretsiz
  const g1 = threatGeometry(tr.plan[1], tr.station);
  ev = tr.step(g1.t_impact + 0.5, 0, 0, 0, false);
  const leak = ev.find(e => e.kind === 'leak'), end = ev.find(e => e.kind === 'end');
  assert.ok(leak && leak.health === 100 - tr.plan[1].damage && end && end.success && end.reason === 'all_resolved');
  const oz = end.result;
  assert.equal(oz.accuracy, 0.5); assert.deepEqual(oz.icept, { total: 10, used: 2, lost: 1 });
  assert.equal(oz.score, 300 + Math.min(400, Math.round(kill.station_m / 10)) + 195 - 250 + Math.round(oz.health) * 10 + 800 + 1000);
  assert.deepEqual(tr.step(9999, 0, 0, 0, true), []);
  const st = tr.state();
  assert.deepEqual(st.killed, [[0, 20]]); assert.equal(st.remaining, 8); assert.ok(st.ended.success);
  const t2 = createDefendTracker({ seed: 1, interceptors: 1 }, L);
  t2.step(1, 0, 0, 0, true);
  assert.throws(() => t2.redeploy());
});

test('puan ve rütbe (sunucu savunma_puan)', () => {
  assert.deepEqual(scoreDefend({ kills: [{ station_m: 2500, ttk_s: 40 }, { station_m: 6000, ttk_s: 250 }], leaks: [{}], health: 65, icept: { total: 10, used: 3 }, success: true, spawned: 3 }),
    { score: 3510, accuracy: 0.667, rank: 'lieutenant', rank_ratio: 0.661 });
  assert.equal(scoreDefend({ kills: [], leaks: Array(20).fill({}), health: 0, icept: { total: 1, used: 1 }, spawned: 20 }).score, 0);
  assert.equal(rankOf(0.99), 'colonel'); assert.equal(rankOf(0.6), 'lieutenant'); assert.equal(rankOf(0.1), 'private');
});

test('doğrulama + gövde + sonraki dalga + kayıt durumu', () => {
  assert.equal(validateSite(null), null);
  assert.equal(validateSite({ radar: true, radar_km: 20, eo: true, eo_km: 5 }), null);
  assert.ok(validateSite({ radar: true, radar_km: 60 })); assert.ok(validateSite({ eo: true, eo_km: 0.2 })); assert.ok(validateSite({ radar: 'evet' }));
  assert.equal(siteBody({ station: false, radar: false, eo: false }), null);
  assert.deepEqual(siteBody({ station: true, radar: true, radar_km: 12.345, eo: false }), { station: true, radar: true, radar_km: 12.35, eo: false, eo_km: 5 });
  assert.ok(validateDefend({}, 'sabit_kanat')); assert.equal(validateDefend({ waves: 5 }, 'interceptor'), null); assert.ok(validateDefend({ waves: 11 }, 'interceptor'));
  assert.ok(validateDefend({ difficulty: 'x' }, 'interceptor')); assert.ok(validateDefend({ seed: -2 }, 'interceptor'));
  const p = defendPlan({ seed: 12345 });
  assert.deepEqual(nextWave(p, 0), { wave: 1, in_s: 45 }); assert.equal(nextWave(p, 46).wave, 2); assert.equal(nextWave(p, 1e6), null);
  const res = { config: { waves: 5, interceptors: 10 }, kills: [{ k: 0, t: 80, interceptor: 1 }, { k: 2, t: 160, interceptor: 2 }], leaks: [{ k: 1, t: 150, damage: 15 }], icept: { total: 10, used: 2 }, ended: { t: 400, success: true } };
  const a = defendStateAt(res, p, 155);
  assert.equal(a.health, 85); assert.deepEqual(a.killed, [[0, 80]]); assert.deepEqual(a.leaked, [[1, 150]]); assert.equal(a.wave, 2); assert.equal(a.ended, null); assert.equal(a.icept.used, 1);
  assert.equal(defendStateAt(res, p, 500).icept.used, 2); assert.ok(defendStateAt(res, p, 500).ended);
});

test('arayüz metinleri: anahtarlar tekil, çevirmen (HEPGO Türkçe anahtar / SIMUMAV site.*)', () => {
  const keys = M.SITE_TEXTS.map(([k]) => k);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(keys.every(k => k.startsWith('site.')));
  const hepgo = M.makeSiteT((s, p) => `TR:${s}${p ? JSON.stringify(p) : ''}`);
  assert.equal(hepgo('site.radar'), 'TR:Radar');
  const sm = M.makeSiteT((k, p) => (k === 'site.radar' ? 'Radar EN' : k), true);
  assert.equal(sm('site.radar'), 'Radar EN'); assert.equal(sm('site.wave', { w: 2, n: 5 }), 'DALGA 2/5');   // eksik çeviri → Türkçe + değişken
});

console.log(`${n} test geçti`);
