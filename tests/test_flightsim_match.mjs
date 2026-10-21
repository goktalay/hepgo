// Uçuş Simülatörü §33 — çok oyunculu karşılaşma SAF ön yüz yardımcıları (static/js/modules/flightsim_match.js): halka ayarı doğrulama (sunucuyla aynı
// kurallar), davet listesi (solda davet edilmeyenler, sağda edilenler; arama, tavan), saat eşitleme, geri sayım evresi, geometri (halka/oyuncu yerel,
// açı ara değeri, kerteriz), canlı sıralama, sihirbaz adım listesi (Yeni Karşılaşma: Hedefler/Yer kontrol yok, Halkalar + Davet et var).
// Çalıştırma: node tests/test_flightsim_match.mjs
import assert from 'node:assert/strict';
import { MATCH_LIMITS, arrowFor, bearingDeg, colorFor, countdownPhase, createClock, fmtClock, fmtDist, inviteAdd, inviteError, inviteRemove, lerpPose, liveStandings,
  lobbyCounts, partitionInvite, playerLocal, relAngle, ringDefaults, ringLocal, ringsError, ringsSummary, ringsViewBox, sessionHref, matchHref } from '../static/js/modules/flightsim_match.js';
import { stepDefFor, wizardSteps } from '../static/js/modules/flightsim_wizard.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

console.log('Halka ayarı');
test('varsayılanlar tip sınıfına göre (dikey / uçak) ve sunucu çekirdeğiyle aynı', () => {
  assert.deepEqual(ringDefaults('multirotor'), { count: 8, min_alt_m: 15, max_alt_m: 60, diameter_m: 12, radius_m: 220, time_limit_min: 15, seed: null });
  assert.equal(ringDefaults('sabit_kanat').diameter_m, 36);
  assert.equal(ringDefaults('vtol').radius_m, 220);
});
test('doğrulama: min > max, sınır dışı sayı, kesirli halka sayısı', () => {
  assert.equal(ringsError(ringDefaults('multirotor')), null);
  assert.equal(ringsError({ ...ringDefaults('multirotor'), min_alt_m: 80, max_alt_m: 40 }), 'Minimum yükseklik maksimum yükseklikten büyük olamaz');
  assert.equal(ringsError({ ...ringDefaults('multirotor'), count: 0 }), 'Halka sayısı geçersiz');
  assert.equal(ringsError({ ...ringDefaults('multirotor'), count: 2.5 }), 'Halka sayısı geçersiz');
  assert.equal(ringsError({ ...ringDefaults('multirotor'), max_alt_m: 500 }), 'Yükseklik sınır dışında');
  assert.equal(ringsError({ ...ringDefaults('multirotor'), diameter_m: 1 }), 'Halka çapı geçersiz');
  assert.equal(ringsError({ ...ringDefaults('multirotor'), time_limit_min: 1 }), 'Süre sınırı geçersiz');
  assert.equal(ringsSummary({ count: 5, min_alt_m: 10, max_alt_m: 50, diameter_m: 12, radius_m: 200 }), '5 · 10–50 m · Ø 12 m · R 200 m');
});

console.log('Davet listesi');
const U = [{ id: 1, full_name: 'Zeynep Uçar', username: 'zeynep' }, { id: 2, full_name: 'Ayşe Pilot', username: 'ayse' }, { id: 3, full_name: 'İsmail Şahin', username: 'ismail' }, { id: 4, full_name: 'Can', username: 'can' }];
test('solda davet edilmeyenler (ada göre), sağda edilenler (ekleme sırasıyla)', () => {
  const p = partitionInvite(U, new Set([3, 1]));
  assert.deepEqual(p.left.map(u => u.id), [2, 4]);
  assert.deepEqual(p.right.map(u => u.id), [3, 1]);
  assert.equal(p.total, 2);
});
test('arama iki listeye uygulanır (Türkçe küçük harf: İ → i)', () => {
  const p = partitionInvite(U, new Set([3]), 'ism');
  assert.deepEqual(p.left, []); assert.deepEqual(p.right.map(u => u.id), [3]);
  assert.deepEqual(partitionInvite(U, new Set(), 'AYŞE').left.map(u => u.id), [2]);
});
test('ekle/çıkar: tavan (oyuncu sınırı − kurucu) aşılmaz; hata metinleri', () => {
  let s = inviteAdd(new Set(), [1, 2, 3], 2);
  assert.deepEqual([...s], [1, 2]);
  s = inviteRemove(s, 1);
  assert.deepEqual([...s], [2]);
  assert.equal(inviteError(new Set()), 'En az bir kullanıcı davet edin');
  assert.equal(inviteError(new Set([1])), null);
  assert.equal(inviteError(new Set([1, 2, 3, 4, 5, 6, 7, 8])), 'Davet sınırı aşıldı');
  assert.equal(inviteAdd(new Set(), [1, 2, 3, 4, 5, 6, 7, 8, 9]).size, MATCH_LIMITS.players_max - 1);
});

console.log('Saat ve geri sayım');
test('saat: en küçük gidiş-dönüşlü örnek; sunucu saati = istemci + fark', () => {
  let t = 1000000;
  const c = createClock(() => t);
  c.sample(2000.0, t - 400, t);       // rtt 400 → off = 2000000 - (999600 + 200)
  assert.equal(c.offsetMs, 2000000 - 999800);
  c.sample(2000.5, t - 100, t);       // daha iyi örnek
  assert.equal(c.rttMs, 100); assert.equal(c.offsetMs, 2000500 - 999950);
  c.sample(9999, t - 900, t);         // kötü örnek yok sayılır
  assert.equal(c.offsetMs, 2000500 - 999950);
  t += 1000;
  assert.equal(c.now(), (1001000 + 2000500 - 999950) / 1000);
});
test('geri sayım evresi: bekle → giriş (son 3 sn) → yarış', () => {
  assert.deepEqual(countdownPhase(100, 94), { phase: 'wait', remain: 6 });
  assert.deepEqual(countdownPhase(100, 97), { phase: 'intro', remain: 3 });
  assert.deepEqual(countdownPhase(100, 100.2), { phase: 'race', remain: 0 });
  assert.equal(countdownPhase(null, 5).phase, 'none');
});

console.log('Geometri');
test('halka yereli: z = alt_msl − ev irtifası; oyuncu yereli toLocal ile', () => {
  assert.deepEqual(ringLocal({ x: 10, y: -20, alt_msl: 935, nx: 0.6, ny: 0.8, radius_m: 6 }, 900), { x: 10, y: -20, z: 35, nx: 0.6, ny: 0.8, r: 6 });
  const l = playerLocal({ lat: 1, lon: 2, alt_msl: 912 }, (a, b) => ({ x: b * 10, y: a * 10 }), 900);
  assert.deepEqual(l, { x: 20, y: 10, z: 12 });
});
test('poz ara değeri: açı en kısa yoldan (359° → 1°)', () => {
  const a = { x: 0, y: 0, z: 0, yaw: 359 * Math.PI / 180 }, b = { x: 10, y: 0, z: 2, yaw: 1 * Math.PI / 180 };
  const m = lerpPose(a, b, 0.5);
  assert.equal(m.x, 5); assert.equal(m.z, 1);
  assert.ok(Math.abs(((m.yaw * 180 / Math.PI) + 360) % 360) < 1e-6 || Math.abs(((m.yaw * 180 / Math.PI) + 360) % 360 - 360) < 1e-6, m.yaw);
});
test('kerteriz ve bağıl açı (+ sağ)', () => {
  assert.equal(bearingDeg(0, 0, 0, 10), 0); assert.equal(bearingDeg(0, 0, 10, 0), 90); assert.equal(bearingDeg(0, 0, -10, 0), 270);
  assert.equal(relAngle(350, 10), 20); assert.equal(relAngle(10, 350), -20); assert.equal(relAngle(0, 180), -180);
  assert.equal(arrowFor(0), '⬆'); assert.equal(arrowFor(90), '➡'); assert.equal(arrowFor(-90), '⬅');
});
test('kuş bakışı ölçeği: kare, merkez ve halkalar içeride', () => {
  const vb = ringsViewBox([{ x: 100, y: 0 }, { x: -50, y: 200 }]);
  for (const [x, y] of [[0, 0], [100, 0], [-50, 200]]) { const [u, v] = vb.toSvg(x, y); assert.ok(u > 0 && u < 1 && v > 0 && v < 1, [x, y, u, v]); }
});

console.log('Sıralama ve gösterim');
test('canlı sıralama: bitiren önce (süreyle), sonra halka çok, mesafe az; düşen sonda; davetli/çıkarılan yok', () => {
  const P = [{ id: 1, name: 'A', status: 'hazir', rings: 2, dist_next_m: 50 }, { id: 2, name: 'B', status: 'hazir', rings: 2, dist_next_m: 20 },
    { id: 3, name: 'C', status: 'hazir', rings: 4, finished: true, finish_t: 120 }, { id: 4, name: 'D', status: 'dustu', rings: 3 },
    { id: 5, name: 'E', status: 'davetli' }, { id: 6, name: 'F', status: 'hazir', rings: 4, finished: true, finish_t: 110 }];
  assert.deepEqual(liveStandings(P).map(p => p.id), [6, 3, 2, 1, 4]);
  assert.deepEqual(liveStandings(P, { 1: { rings: 3, dist: 5 } }).map(p => p.id), [6, 3, 1, 2, 4]);   // pos çerçevesi önde
});
test('salon sayaçları, renk, biçim, bağlantılar', () => {
  assert.deepEqual(lobbyCounts([{ status: 'geldi' }, { status: 'davetli' }, { status: 'hazir' }, { status: 'cikarildi' }]), { total: 3, arrived: 2, ready: 1 });
  assert.equal(colorFor([{ id: 7 }, { id: 9 }], 9), '#3b82f6');
  assert.equal(fmtClock(75.25), '1:15.3'); assert.equal(fmtClock(null), '—');
  assert.equal(fmtDist(1234), '1.23 km'); assert.equal(fmtDist(87.4), '87 m');
  assert.equal(matchHref(5), '#/drone/sim/match/5'); assert.equal(sessionHref(12, 5), '#/drone/sim/12?match=5');
});

console.log('Sihirbaz adımları');
test('Yeni Karşılaşma: Hedefler / Yer kontrol yok, Halkalar + Davet et var; özet "Özet ve başlat"', () => {
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'multirotor' }), ['vehicle', 'world', 'power', 'camera', 'targets', 'site', 'summary']);
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'multirotor', match: true }), ['vehicle', 'world', 'power', 'camera', 'rings', 'invite', 'summary']);
  assert.deepEqual(wizardSteps({ mode: 'sitl', type: 'sabit_kanat', match: true }), ['vehicle', 'world', 'launch', 'power', 'camera', 'rings', 'invite', 'summary']);
  assert.equal(stepDefFor('summary', true).title, 'Özet ve başlat');
  assert.equal(stepDefFor('summary', false).title, 'Kayıt ve özet');
});

console.log(`\n${n} test geçti`);
