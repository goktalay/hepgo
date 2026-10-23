// Uçuş Simülatörü §47 — HAZIR FPV PARKURLARI ön yüz saf katmanı (flightsim_fpvcourse.js + flightsim_fpvcourse3d.splitBoxHoles) tarayıcısız birim testi:
//   • hayalet çözücü Python'la (app/flightsim_fpv.hayalet_kodla / hayalet_coz) birebir: gömülü fikstür + (varsa .venv) canlı çapraz denetim
//   • ghostPoseAt (ara değer, yaw sarması, önce/sonra), ghostDelta, biçimleme (m:ss.000, ±fark), sektör rengi, ara sürelerden sektörler
//   • kapı eksenleri / geçiş / başlangıç ızgarası Python'la aynı (8 parkurun tüm kapıları), sıradaki kapı + kapı durumları, ilerleme metni
//   • çubuk konumu (mod-2; PWM ve eksen girdisi), tek kişilik doğrulama (halka/FPV serbest, it dalaşı tam 2), istemci FPV doğrulaması, sınırlar sunucuyla aynı
//   • galeri kartı + kuş bakışı SVG, delikli kutu bölme (alan korunur, delik boş), ortam kademeleri, metinler HEPGO 6 dil, bağlama
// Çalıştırma: node tests/test_flightsim_fpvcourse.mjs
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FPV_LIMITS, FPV_TEXTS, bestSectors, checkpointGate, courseSvg, decodeGhost, envAtmosphere, fmtDelta, fmtLap, fpvBody, fpvDefaults, fpvError, fpvPoints, fpvRow,
  galleryCard, gateAxes, gateCorners, gateCrossing, gateStates, ghostDelta, ghostPoseAt, isSolo, leaderboardPlace, makeFpvT, matchIsSolo, nextCheckpoint, opponentsErrorSolo,
  pbDelta, progressInfo, sectorClass, sectorTimesFromSplits, soloAllowed, startSlots, stars, stickPositions, sticksPref, ghostPref, upcoming } from '../static/js/modules/flightsim_fpvcourse.js';
import { splitBoxHoles } from '../static/js/modules/flightsim_fpvcourse3d.js';
import { SFX_EVENTS, sfxPlan, planLength } from '../static/js/modules/flightsim_sfx.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };
const near = (a, b, e = 1e-9, msg = '') => assert.ok(Math.abs(a - b) <= e, `${msg} ${a} ≠ ${b}`);
const PY = join(ROOT, '.venv/bin/python');
const py = code => { if (!existsSync(PY)) return null; const r = spawnSync(PY, ['-c', code], { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 << 20 }); if (r.status !== 0) throw new Error(r.stderr); return JSON.parse(r.stdout); };
const mem = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };

// app/flightsim_fpv.hayalet_kodla ile üretilmiş fikstür; beklenen değerler hayalet_coz (yaw tam sayı uzayında mod → [−π, π): 3,14 → −3,124; büyük sıçrama satırı)
const GHOST = 'g1.GgC_DMsI3AGcGADHARSIASoEFGIKFIoBBAIUWAoUigElAhRCChSIAS0EFCgKFIoBCQQUBgoUiAEiAi0ZChSKAS4CFDcKFIgBEgQUTQoUigEdBBRfChSIAS8CFGMKFIoBFQQUWwoo-E7hugGyB9YX3QLOBA';
const GHOST_PY = [[0.0, -16.0, -11.0, 2.2, 3.1, 0.0, -0.2], [0.1, -14.64, -10.58, 2.24, 3.12, 0.098, -0.19], [0.2, -13.26, -10.54, 2.26, 3.14, 0.186, -0.18], [0.3, -11.88, -10.92, 2.28, -3.124, 0.252, -0.17],
  [0.4, -10.52, -11.38, 2.32, -3.104, 0.292, -0.16], [0.5, -9.14, -11.48, 2.36, -3.084, 0.298, -0.15], [0.6, -7.78, -11.14, 2.38, -3.13, 0.272, -0.14], [0.7, -6.4, -10.68, 2.4, -3.11, 0.216, -0.13],
  [0.8, -5.04, -10.5, 2.44, -3.09, 0.138, -0.12], [0.9, -3.66, -10.8, 2.48, -3.07, 0.042, -0.11], [1.0, -2.3, -11.28, 2.5, -3.05, -0.058, -0.1], [1.1, -0.92, -11.5, 2.54, -3.03, -0.15, -0.09],
  [1.3, 100.12, -250.56, 12.0, 0.0, -0.5, 0.5]];
const asArr = s => [s.t, s.x, s.y, s.z, s.yaw, s.roll, s.pitch];

console.log('hayalet');
test('decodeGhost: Python fikstürüyle birebir (13 örnek, yaw sarması, büyük sıçrama)', () => {
  const d = decodeGhost(GHOST);
  assert.equal(d.length, GHOST_PY.length);
  d.forEach((s, i) => asArr(s).forEach((v, k) => near(v, GHOST_PY[i][k], 1e-9, `örnek ${i} alan ${k}`)));
  assert.throws(() => decodeGhost('x1.abc')); assert.throws(() => decodeGhost(null)); assert.throws(() => decodeGhost('g1.@@'));
  assert.deepEqual(decodeGhost('g1.AA'), []);   // 0 örnek
});
test('decodeGhost: canlı Python çapraz denetimi (rastgele 600 örnek, uzun koşu, negatif koordinat)', () => {
  const r = py(`
import json, math, random
from app import flightsim_fpv as F
R = random.Random(7); o = []; t = 0.0; x = y = 0.0; yaw = 0.0
for k in range(600):
    t += 0.1; x += R.uniform(-2, 2); y += R.uniform(-2, 2); yaw += R.uniform(-0.7, 0.7)
    o.append((round(t, 2), x - 300, y + 120, R.uniform(0.5, 40), (yaw + math.pi) % (2 * math.pi) - math.pi, R.uniform(-1.2, 1.2), R.uniform(-1, 1)))
s = F.hayalet_kodla(o)
print(json.dumps({'s': s, 'd': [list(v) for v in F.hayalet_coz(s)]}))`);
  if (!r) { console.log('    (.venv yok — canlı denetim atlandı)'); return; }
  const d = decodeGhost(r.s);
  assert.equal(d.length, r.d.length);
  d.forEach((s, i) => asArr(s).forEach((v, k) => near(v, r.d[i][k], 1e-9, `örnek ${i} alan ${k}`)));
});
test('ghostPoseAt: ara değer, yaw en kısa yaydan, önce → ilk, sonra → son (done)', () => {
  const S = [{ t: 0, x: 0, y: 0, z: 2, yaw: 3.1, roll: 0, pitch: 0 }, { t: 1, x: 10, y: -4, z: 4, yaw: -3.1 + 2 * Math.PI * 0, roll: 0.2, pitch: -0.2 }, { t: 2, x: 20, y: 0, z: 2, yaw: 0, roll: 0, pitch: 0 }];
  const a = ghostPoseAt(S, 0.5);
  near(a.x, 5); near(a.y, -2); near(a.z, 3); near(a.roll, 0.1); near(a.pitch, -0.1);
  // 3,1 → −3,1 en kısa yay ±π üzerinden (π'ye yakın), 0'dan geçmez
  assert.ok(Math.abs(Math.abs(Math.atan2(Math.sin(a.yaw), Math.cos(a.yaw))) - Math.PI) < 0.05, `yaw ${a.yaw}`);
  assert.equal(ghostPoseAt(S, -3).before, true); near(ghostPoseAt(S, -3).x, 0);
  assert.equal(ghostPoseAt(S, 9).done, true); near(ghostPoseAt(S, 9).x, 20);
  assert.equal(ghostPoseAt([], 1), null); assert.equal(ghostPoseAt(S, null), null);
  const d = decodeGhost(GHOST), m = ghostPoseAt(d, 1.2);   // 1,1 ile 1,3 arasında: büyük sıçramanın ortası
  near(m.x, (-0.92 + 100.12) / 2, 1e-9); near(m.idx, 11);
});
test('ghostDelta: + gerideyim / − öndeyim; eksik → null', () => {
  assert.equal(ghostDelta([1.2, 5.5, 9.25], [1.0, 5.9, 9.0]), 0.25);
  assert.equal(ghostDelta([1.2, 5.5, 9.25], [1.0, 5.9, 9.0], 1), -0.4);
  assert.equal(ghostDelta([1.2, 5.5], [1.0]), null); assert.equal(ghostDelta([], [1]), null); assert.equal(ghostDelta(null, [1]), null);
});

console.log('biçimleme + sektör');
test('fmtLap m:ss.000, fmtDelta ±, yıldız, puan, kişisel rekor farkı', () => {
  assert.equal(fmtLap(0), '0:00.000'); assert.equal(fmtLap(83.4567), '1:23.457'); assert.equal(fmtLap(599.9999), '10:00.000'); assert.equal(fmtLap(-2), '0:00.000'); assert.equal(fmtLap(null), '—');
  assert.equal(fmtDelta(0.412), '+0.412'); assert.equal(fmtDelta(-1.5, 2), '−1.50'); assert.equal(fmtDelta(null), '—');
  assert.equal(stars(3), '★★★☆☆'); assert.equal(stars(9), '★★★★★');
  assert.equal(pbDelta(80.5, 82), -1.5); assert.equal(pbDelta(80, null), null);
  assert.equal(fpvPoints({ par_lap_s: 28 }, 84, 3), 250); assert.equal(fpvPoints({ par_lap_s: 28 }, 40, 3), 375); assert.equal(fpvPoints({ par_lap_s: 28 }, null, 3), 0);
});
test('sektör rengi: genel en iyi mor, kişisel en iyi yeşil, yavaş sarı; ara sürelerden sektörler (sunucu kuralı)', () => {
  assert.equal(sectorClass(9.1, { pb: 9.5, best: 9.2 }), 'purple');
  assert.equal(sectorClass(9.4, { pb: 9.5, best: 9.2 }), 'green');
  assert.equal(sectorClass(9.6, { pb: 9.5, best: 9.2 }), 'yellow');
  assert.equal(sectorClass(9.6, {}), 'green'); assert.equal(sectorClass(null, {}), 'none');
  // 2 tur, kapılar 0..3, sektör sonu kapı 2 ve S/F (0)
  const cps = [{ i: 1, gate: 0, lap: 0, sector_end: false }, { i: 2, gate: 1, lap: 1, sector_end: false }, { i: 3, gate: 2, lap: 1, sector_end: true }, { i: 4, gate: 3, lap: 1, sector_end: false },
    { i: 5, gate: 0, lap: 1, sector_end: true }, { i: 6, gate: 1, lap: 2, sector_end: false }, { i: 7, gate: 2, lap: 2, sector_end: true }, { i: 8, gate: 3, lap: 2, sector_end: false }, { i: 9, gate: 0, lap: 2, sector_end: true }];
  const st = sectorTimesFromSplits([2, 5, 9, 12, 15, 18, 21.5, 24, 28], cps);
  assert.deepEqual(st, [[7, 6], [6.5, 6.5]]);
  assert.deepEqual(bestSectors(st), { 1: 6.5, 2: 6 });
});
test('sunucu ParkurIzleyici sektörleriyle aynı (canlı Python: hangar 2 tur, yarış hattı boyunca)', () => {
  const r = py(`
import json
from app import flightsim_fpv as F
M = {'lat': 39.9, 'lon': 32.8, 'alt': 900.0}
cfg = F.fpv_ayar_dogrula({'course_id': 'hangar', 'laps': 2}, 'multirotor')
cps = F.kontrol_noktalari(cfg, M)
iz = F.ParkurIzleyici(cps, cfg, M, 0.0)
c = F.parkur('hangar'); t = 0.0
pts = []
for k, seg in enumerate(c['line']):
    pts += seg if not pts else seg[1:]
pts += [p for seg in c['line'][1:] for p in seg[1:]]
prev = pts[0]
for p in pts[1:]:
    n = max(1, int(((p[0]-prev[0])**2 + (p[1]-prev[1])**2 + (p[2]-prev[2])**2) ** .5 / 0.3))
    for s in range(1, n + 1):
        f = s / n; t += 0.04
        iz.konum(prev[0] + (p[0]-prev[0])*f, prev[1] + (p[1]-prev[1])*f, 900 + prev[2] + (p[2]-prev[2])*f, t)
    prev = p
o = iz.ozet()
print(json.dumps({'cps': cps, 'splits': o['splits'], 'sectors': o['sectors'], 'laps': o['lap_times']}))`);
  if (!r) { console.log('    (.venv yok — atlandı)'); return; }
  assert.equal(r.splits.length, r.cps.length);
  const st = sectorTimesFromSplits(r.splits, r.cps);
  assert.equal(st.length, r.sectors.length);
  st.forEach((row, i) => row.forEach((s, k) => near(s, r.sectors[i][k], 2e-3, `tur ${i} sektör ${k}`)));
});

console.log('kapı geometrisi (Python ile aynı)');
const PYC = py(`
import json
from app import flightsim_fpv as F
out = {}
for cid in F.PARKUR_IDLER:
    c = F.parkur(cid)
    ax = [[list(v) for v in F.kapi_eksenleri(g)] for g in c['gates']]
    tests = []
    for g in c['gates']:
        a, m, b = F.kapi_giris_cikis(g)
        for p0, p1 in ((a, b), (b, a), ((a[0], a[1], a[2] + 30), (b[0], b[1], b[2] + 30))):
            y, ic, d = F.kapi_kesisim(p0, p1, g)
            tests.append([list(p0), list(p1), y, ic, d])
    cps = F.kontrol_noktalari(F.fpv_ayar_dogrula({'course_id': cid, 'laps': 2}, 'multirotor'), {'lat': 39.9, 'lon': 32.8, 'alt': 900.0})
    out[cid] = {'course': c, 'axes': ax, 'cross': tests, 'starts': F.parkur_baslangiclari(c, 7), 'cps': cps}
print(json.dumps(out))`);
test('gateAxes / gateCrossing / startSlots: 8 parkurun tüm kapıları Python kapi_eksenleri / kapi_kesisim / parkur_baslangiclari ile aynı', () => {
  if (!PYC) { console.log('    (.venv yok — yerel örnekler)'); const g = { kind: 'gate', x: 0, y: 0, z: 2, yaw: 90, w: 3, h: 2 }; assert.deepEqual(gateAxes(g).n.map(v => +v.toFixed(9)), [1, 0, 0]); return; }
  for (const [cid, P] of Object.entries(PYC)) {
    P.course.gates.forEach((g, i) => { const A = gateAxes(g); ['n', 'u', 'v'].forEach((k, j) => A[k].forEach((v, q) => near(v, P.axes[i][j][q], 1e-12, `${cid} kapı ${i} ${k}`))); });
    P.cross.forEach(([p0, p1, y, ic, d], k) => {
      const g = P.course.gates[Math.floor(k / 3)], r = gateCrossing(p0, p1, g);
      assert.equal(r.dir, y, `${cid} ${k}`); assert.equal(r.inside, ic, `${cid} ${k}`); if (d != null) near(r.dist, d, 1e-9);
    });
    startSlots(P.course, 7).forEach((s, k) => { near(s.x, P.starts[k][0], 1e-9); near(s.y, P.starts[k][1], 1e-9); });
    // kontrol noktası → kapı (sunucu kontrol_kapisi) ve köşeler açıklık içinde
    for (const c of P.cps.slice(0, 4)) { const g = checkpointGate(c); assert.equal(gateCorners(g).length, c.shape === 'circle' ? 16 : 4); }
  }
});
test('sıradaki kapı, kapı durumları (yeşil sıradaki, sonraki 2 pembe/mor, diğerleri sönük), ilerleme metni', () => {
  const cps = PYC ? PYC.hangar.cps : [{ i: 1, gate: 0, lap: 0 }, { i: 2, gate: 1, lap: 1 }, { i: 3, gate: 2, lap: 1 }, { i: 4, gate: 0, lap: 1 }];
  const nG = PYC ? PYC.hangar.course.gates.length : 3;
  assert.equal(nextCheckpoint(cps, 1).gate, 0); assert.equal(nextCheckpoint(cps, null), null);
  let st = gateStates(nG, cps, 1);
  assert.equal(st[0], 'next'); assert.equal(st[1], 'soon'); assert.equal(st[2], 'soon2'); assert.ok(st.slice(3).every(s => s === 'done'));
  st = gateStates(nG, cps, cps.length);   // son kontrol noktası: S/F sıradaki
  assert.equal(st[0], 'next'); assert.equal(st.filter(s => s !== 'done').length, 1);
  assert.ok(gateStates(nG, cps, null).every(s => s === 'done'));
  assert.equal(upcoming(cps, 2, 2).length, 3);
  const p0 = progressInfo(cps, 1), p1 = progressInfo(cps, 3);
  assert.equal(p0.lap, 0); assert.equal(p1.lap, 1); assert.equal(p1.gateNo, 2); assert.equal(p1.gatesPerLap, nG);
  assert.equal(progressInfo(cps, null).done, true);
});

console.log('çubuk + doğrulama');
test('çubuk konumu mod-2: PWM (ch1 yatış, ch2 yunuslama düşük = ileri, ch3 gaz, ch4 sapma) ve eksen girdisi', () => {
  const p = stickPositions([2000, 1000, 1000, 1500, 1500, 1000, 1000, 1500]);
  assert.deepEqual([p.left.x, p.left.y, p.right.x, p.right.y], [0, -1, 1, 1]);
  const q = stickPositions([1500, 1500, 2000, 1000]);
  assert.deepEqual([q.left.x, q.left.y, q.right.x, q.right.y], [-1, 1, 0, 0]);
  const r = stickPositions({ thr: 0.5, yaw: 0.3, pitch: -0.4, roll: 2 });
  assert.deepEqual([r.left.x, r.left.y, r.right.x, r.right.y], [0.3, 0, 1, -0.4]);
  assert.equal(stickPositions([1, 2]), null); assert.equal(stickPositions(null), null); assert.equal(stickPositions([0, 0, 0, 0]), null);
  const s = mem(), sp = sticksPref(s); assert.equal(sp.get(), true); sp.set(false); assert.equal(s.getItem('fs.fpv.sticks'), '0'); assert.equal(sticksPref(s).get(), false);
  const g = ghostPref(mem()); assert.equal(g.get(), 'pb'); assert.equal(g.set('off'), 'off'); assert.equal(g.get(), 'off');
});
test('tek kişilik: halka yarışı ve FPV davet + bot 0 serbest, it dalaşı tam 2; sınır aşımı', () => {
  assert.equal(opponentsErrorSolo(0, 0, 'rings'), null); assert.equal(opponentsErrorSolo(0, 0, 'fpv'), null);
  assert.ok(opponentsErrorSolo(0, 0, 'dogfight')); assert.equal(opponentsErrorSolo(1, 0, 'dogfight', 1), null); assert.ok(opponentsErrorSolo(1, 1, 'dogfight', 1));
  assert.ok(opponentsErrorSolo(5, 3, 'rings', 7)); assert.equal(opponentsErrorSolo(4, 3, 'fpv', 7), null);
  assert.equal(soloAllowed('rings'), true); assert.equal(soloAllowed('fpv'), true); assert.equal(soloAllowed('dogfight'), false);
  assert.equal(isSolo(0, 0), true); assert.equal(isSolo(0, 1), false);
  assert.equal(matchIsSolo({ players: [{ id: 1, status: 'hazir' }] }), true); assert.equal(matchIsSolo({ players: [{ id: 1 }, { id: -1, is_bot: true }] }), false);
  assert.equal(matchIsSolo({ result: { solo: true }, players: [{}, {}] }), true);
});
test('FPV istemci doğrulaması + sınırlar sunucuyla aynı (app/flightsim_fpv.py)', () => {
  const src = readFileSync(join(ROOT, 'app/flightsim_fpv.py'), 'utf8');
  const pair = name => { const m = src.match(new RegExp(`^${name} = \\(([\\d.]+), ([\\d.]+)\\)`, 'm')); return m ? [Number(m[1]), Number(m[2])] : null; };
  assert.deepEqual(FPV_LIMITS.laps, pair('TUR')); assert.deepEqual(FPV_LIMITS.penalty_s, pair('CEZA_S')); assert.deepEqual(FPV_LIMITS.time_limit_min, pair('SURE_DK'));
  assert.ok(src.includes("FPV_TIPLER = ('multirotor', 'hexarotor', 'helikopter')") && src.includes("CARPMA_KURALLARI = ('penalty', 'reset', 'continue')"));
  assert.ok(src.includes("'crash_rule': 'penalty', 'crash_penalty_s': 2.0, 'miss_penalty_s': 3.0, 'time_limit_min': 10"));
  const d = fpvDefaults({ id: 'forest', laps: 2 });
  assert.equal(fpvError(d, 'multirotor'), null); assert.equal(fpvError(d, 'sabit_kanat'), 'fpv.type_warn'); assert.equal(fpvError({ ...d, course_id: null }), 'fpv.pick');
  for (const bad of [{ laps: 11 }, { laps: 1.5 }, { crash_rule: 'x' }, { crash_penalty_s: 31 }, { time_limit_min: 1 }]) assert.ok(fpvError({ ...d, ...bad }, 'hexarotor'), JSON.stringify(bad));
  assert.deepEqual(fpvBody(d), { course_id: 'forest', laps: 2, crash_rule: 'penalty', crash_penalty_s: 2, miss_penalty_s: 3, time_limit_min: 10 });
});

console.log('galeri + 3B saf');
test('galeri kartı (uzunluk, kapı, zorluk yıldızı, rekor / en iyim) + kuş bakışı SVG (engeller, hat, kapılar, S/F)', () => {
  const c = PYC ? { ...PYC.woodframe.course, record: { name: 'Ayşe', time_s: 71.234 }, my_best: 75.5, runs: 4 } : { id: 'woodframe', name: 'X', length_m: 120, gate_count: 9, difficulty: 3, laps: 3, gates: [], env: {} };
  const d = galleryCard(c);
  assert.equal(d.name, 'Tepedeki Ahşap Ev İskeleti'); assert.equal(d.stars, '★★★☆☆'); assert.equal(d.difficultyName, 'Zor');
  if (PYC) { assert.equal(d.record.time, '1:11.234'); assert.equal(d.myBest, '1:15.500'); assert.equal(d.gates, 9); assert.match(d.length, /^\d+ m$/); }
  if (PYC) {
    for (const cid of Object.keys(PYC)) {
      const s = courseSvg(PYC[cid].course);
      assert.ok(s.startsWith('<svg') && s.includes('S/F') && s.includes('<polyline') && (s.match(/<(polygon|circle|line)/g) || []).length > 10, cid);
    }
  }
  assert.equal(leaderboardPlace([{ user_id: 3, rank: 1 }, { user_id: 7, rank: 2 }], 7).rank, 2); assert.equal(leaderboardPlace([], 7), null);
  const r = fpvRow({ time_s: 80.1, pen_s: 3, new_pb: true, pb_prev: 82, fpv: { lap_times: [40, 37.1], best_lap_s: 37.1, misses: 1, hits: 0, laps: 2, laps_done: 2, sectors: [[1, 2]] } });
  assert.deepEqual([r.total, r.best, r.misses, r.newPb, r.pbPrev, r.lapsDone], [80.1, 37.1, 1, true, 82, 2]);
});
test('delikli kutu bölme: alan korunur, delik içinde parça yok (pencere / çoklu delik / döşeme boşluğu)', () => {
  const area = ps => ps.reduce((a, p) => a + (p.u1 - p.u0) * (p.v1 - p.v0) * (p.z1 - p.z0), 0);
  const inside = (ps, u, v, z) => ps.some(p => u > p.u0 && u < p.u1 && v > p.v0 && v < p.v1 && z > p.z0 && z < p.z1);
  const e = { w: 24, d: 0.35, h: 9, holes: [{ u: -5, v: 2, w: 3, h: 3 }, { u: 4, v: 5, w: 2, h: 2 }, { u: 4, v: 1.5, w: 2, h: 2 }], axis: 'y' };
  const ps = splitBoxHoles(e);
  near(area(ps), 24 * 0.35 * 9 - 0.35 * (9 + 4 + 4), 1e-9);
  assert.ok(!inside(ps, -5, 0, 2) && !inside(ps, 4, 0, 5) && !inside(ps, 4, 0, 1.5) && inside(ps, 0, 0, 8));
  assert.ok(ps.length <= 12, `parça sayısı ${ps.length}`);
  const f = { w: 24.6, d: 12.6, h: 0.3, holes: [{ u: 8, v: -3, w: 4, h: 4 }], axis: 'z' };
  const pf = splitBoxHoles(f);
  near(area(pf), 24.6 * 12.6 * 0.3 - 16 * 0.3, 1e-9); assert.ok(!inside(pf, 8, -3, 0.15) && inside(pf, -8, 3, 0.15));
  assert.equal(splitBoxHoles({ w: 2, d: 2, h: 2 }).length, 1);
  if (PYC) for (const cid of Object.keys(PYC)) for (const o of PYC[cid].course.obstacles.filter(x => x.t === 'box' && x.holes?.length && x.vis !== false)) {
    const p = splitBoxHoles(o); assert.ok(p.length >= 1 && p.every(q => q.u1 > q.u0 && q.v1 > q.v0 && q.z1 > q.z0), `${cid} ${o.mat}`);
  }
});
test('ortam kademeleri: Düşük gölgesiz / az dekor; kapalı mekan lambalar; gece stadyumu projektör; sisli altın saat', () => {
  const lo = envAtmosphere({ sky: 'indoor', size: [60, 36], ceiling: 9 }, 'low'), hi = envAtmosphere({ sky: 'indoor', size: [60, 36], ceiling: 9 }, 'ultra');
  assert.equal(lo.shadows, false); assert.equal(hi.shadows, true); assert.ok(lo.decorK < hi.decorK && lo.lamps < hi.lamps && lo.indoor);
  assert.ok(envAtmosphere({ sky: 'night_stadium' }, 'high').flood >= 4);
  const m = envAtmosphere({ sky: 'misty' }, 'high'); assert.ok(m.fog.far < 250 && m.sun && m.sun.el < 15);
  assert.ok(envAtmosphere({ sky: 'clear', size: [140, 90] }, 'medium').fog.far > 300);
});

console.log('ses + metinler + bağlama');
test('ses: FPV olayları çalınabilir (tur, sektör rekoru, kişisel rekor fanfarı, kaçırma, çarpma, hayalet)', () => {
  for (const ev of ['lap', 'sector_best', 'pb', 'miss', 'hit', 'ghost_ahead', 'ghost_behind']) { assert.ok(SFX_EVENTS.includes(ev), ev); const p = sfxPlan(ev, { best: true }); assert.ok(p.length && planLength(p) <= 1.6, ev); }
  assert.ok(planLength(sfxPlan('pb')) > planLength(sfxPlan('lap')));
  assert.ok(sfxPlan('lap', { best: true }).length > sfxPlan('lap').length);
});
test('HEPGO 6 dil: FPV_TEXTS (Türkçe anahtar) mevcut, yer tutucular korunur; makeFpvT', () => {
  const files = { en: ['i18n.en.js', 'i18n.en.extra.js', 'i18n.en.extra2.js'], de: ['i18n.de.js'], fr: ['i18n.fr.js'], es: ['i18n.es.js'], ru: ['i18n.ru.js'], ar: ['i18n.ar.js'] };
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  assert.ok(FPV_TEXTS.every(([k]) => k.startsWith('fpv.')) && new Set(FPV_TEXTS.map(([k]) => k)).size === FPV_TEXTS.length, 'anahtarlar fpv.* ve tekil');
  for (const [lang, fs] of Object.entries(files)) {
    const src = fs.map(f => readFileSync(join(ROOT, 'static/js', f), 'utf8')).join('\n');
    const missing = [...new Set(FPV_TEXTS.map(([, v]) => v))].filter(k => !new RegExp(`^\\s*(${esc(JSON.stringify(k))}|'${esc(k)}')\\s*:`, 'm').test(src));
    assert.deepEqual(missing, [], `${lang}: eksik ${missing.join(' | ')}`);
    for (const [, v] of FPV_TEXTS) {
      const m = src.match(new RegExp(`^\\s*${esc(JSON.stringify(v))}\\s*:\\s*("(?:[^"\\\\]|\\\\.)*")`, 'm'));
      if (m) for (const ph of v.match(/\{\w+\}/g) || []) assert.ok(JSON.parse(m[1]).includes(ph), `${lang} ${v} ${ph}`);
    }
  }
  assert.equal(makeFpvT(null)('fpv.missed', { s: 3 }), 'KAPI KAÇIRILDI +3 sn');
  assert.equal(makeFpvT(k => (k === 'fpv.lap' ? 'LAP' : k), true)('fpv.lap'), 'LAP');
  assert.equal(makeFpvT(k => k, true)('fpv.best'), 'EN İYİ');   // SIMUMAV'da çeviri yoksa Türkçe
});
test('bağlama: sihirbaz FPV kartı + tek kişilik, oturumda 3B + HUD + hayalet, match3d halkaları FPV\'de kapalı, sonuç, Karşılaşmalar türü', () => {
  const ui = readFileSync(join(ROOT, 'static/js/modules/flightsim_match_ui.js'), 'utf8');
  assert.ok(/\['rings', 'dogfight', 'fpv'\]/.test(ui) && /createFpvSection\(/.test(ui) && /attachFpvMatch\(\{/.test(ui) && /fpvResultsBody\(match, me/.test(ui));
  assert.ok(/layer\.setRings\(isFpv\(M\) \? \[\] :/.test(ui) && /opponentsErrorSolo\(invited\.size, bots\.length, kind/.test(ui) && /soloRingsHead\(/.test(ui) && /FT\('fpv\.kind_short'\)/.test(ui));
  const fs = readFileSync(join(ROOT, 'static/js/modules/flightsim.js'), 'utf8');
  assert.ok(/fpv: ringsSec\.kind\(\) === 'fpv' \? ringsSec\.fpv\(\) : null/.test(fs) && /inviteSec\?\.setKind\(k\)/.test(fs) && /fpvTimeTrialCard\(/.test(fs) && /getRc: \(\) => rc\?\.channels/.test(fs));
  assert.ok(/setFollowView/.test(readFileSync(join(ROOT, 'static/js/modules/flightsim3d.js'), 'utf8')));
  const fu = readFileSync(join(ROOT, 'static/js/modules/flightsim_fpvcourse_ui.js'), 'utf8');
  assert.ok(/kind: 'fpv', fpv: sec\.body\(\), invite: \[\], bots: \[\]/.test(fu) && /createFpvCourseLayer\(sim, course/.test(fu) && /fpvApi\.ghost\(/.test(fu));
  const l3 = readFileSync(join(ROOT, 'static/js/modules/flightsim_fpvcourse3d.js'), 'utf8');
  assert.ok(!/new T\.WebGLRenderer|WebGLRenderer\(/.test(l3), 'yeni renderer açılmaz') ;
  assert.ok(/InstancedMesh/.test(l3) && /e\.vis === false\) return/.test(l3));
});
console.log(`\n${n} test geçti`);
