// Uçuş Simülatörü — §27 Kayıtlı Simülasyonlar tarayıcısız birim testi: azami uçuş süresi / menzil (flightBudget — sunucu flightsim_power.menzil_sure
// ile BİREBİR sayılar; tests/test_flightsim.py preset_testleri aynı değerleri denetler), özet kutusu modeli (budgetView), kayıt adı benzersizliği
// (nameKey/nameConflict/nameError — sunucu ad_anahtari ile aynı kural), kayda giren gövde alanları, uçuş özeti karoları (runFacts).
// Çalıştırma: node tests/test_flightsim_saved.mjs
import assert from 'node:assert/strict';
import { flightBudget, roundN, ICEPT_SEYIR_ORAN, SEYIR_ORAN } from '../static/js/modules/flightsim_power.js';
import { budgetView, fmtKm, fmtMin, fmtSec, nameConflict, nameError, nameKey, normName, presetBodyFromSession, PRESET_FIELDS, resultBadge, runFacts } from '../static/js/modules/flightsim_presets.js';

let n = 0;
const test = (name, fn) => { fn(); n++; console.log('  ✓', name); };

console.log('Azami süre / menzil (sunucuyla birebir)');
test('CAYMAZ varsayılanı: seyir 24,5 m/s, gaz %30; yakıt 2 sa 11 dk / 192,7 km sınırlar; batarya 296 dk', () => {
  const b = flightBudget({}, 'sabit_kanat');
  assert.deepEqual(b.speed, { cruise_ms: 24.5, max_ms: 45, cruise_thr: 0.3 });
  assert.deepEqual(b.fuel, { range_km: 192.7, time_min: 130.8, range_km_max: 125, time_min_max: 46.3 });
  assert.deepEqual(b.elec, { wh: 148, time_min: 296, range_km: 435.9, time_min_max: 296, range_km_max: 799.2 });
  assert.equal(b.limit, 'fuel'); assert.equal(b.time_min, 130.8); assert.equal(b.range_km, 192.7); assert.equal(b.time_min_max, 46.3); assert.equal(b.range_km_max, 125);
});
test('kopter: 10 m/s seyir, askı gazı 0,5; 2 L yakıt → 66,7 km / 111,1 dk', () => {
  const k = flightBudget({ fuel_l: 2 }, 'multirotor');
  assert.equal(k.speed.cruise_ms, 10); assert.deepEqual(k.fuel, { range_km: 66.7, time_min: 111.1, range_km_max: 50, time_min_max: 66.7 }); assert.equal(k.limit, 'fuel');
});
test('INTERCEPTOR: elektrikli (yakıt yok), seyir azami × 0,8', () => {
  const i = flightBudget({}, 'interceptor');
  assert.equal(i.fuel, null); assert.equal(i.limit, 'elec'); assert.equal(i.speed.cruise_ms, 88.9); assert.equal(i.elec.time_min, 266.4); assert.equal(ICEPT_SEYIR_ORAN, 0.8);
});
test('sınırlayan: süresi kısa olan; batarya sınırlar; ikisi de yok → null', () => {
  const e = flightBudget({ fuel_l: 1, elec_w: 5 }, 'sabit_kanat'); assert.equal(e.limit, 'fuel'); assert.equal(e.time_min, 26.2); assert.equal(e.elec.time_min, 1776);
  const w = flightBudget({ fuel_l: 50, fuel_km_per_l: 100, elec_mah: 1000, elec_cells: 1 }, 'sabit_kanat'); assert.equal(w.limit, 'elec'); assert.equal(w.time_min, 7.4); assert.equal(w.range_km, 10.9);
  const y = flightBudget({ fuel_l: 0, elec_w: 0 }, 'sabit_kanat'); assert.equal(y.fuel, null); assert.equal(y.elec, null); assert.equal(y.limit, null); assert.equal(y.time_min, null);
});
test('yuvarlama: yarım yukarı (Python yuvarla ile aynı); seyir oranı 12/22', () => {
  assert.equal(roundN(0.25, 1), 0.3); assert.equal(roundN(2.675, 2), 2.68); assert.equal(roundN(null), null); assert.equal(Math.round(45 * SEYIR_ORAN * 10) / 10, 24.5);
});
test('budgetView: satırlar, sınırlayan vurgusu, biçimler', () => {
  const v = budgetView(flightBudget({}, 'sabit_kanat'));
  assert.equal(v.empty, false); assert.equal(v.limit, 'fuel'); assert.deepEqual(v.headline, { time: '2 sa 11 dk', range: '193 km', timeMax: '46 dk', rangeMax: '125 km' });
  assert.deepEqual(v.rows.map(r => [r.key, r.limit, r.time, r.range]), [['fuel', true, '2 sa 11 dk', '193 km'], ['elec', false, '4 sa 56 dk', '436 km']]);
  assert.deepEqual(v.speed, { cruiseKmh: 88, maxKmh: 162, thrPct: 30 });
  assert.equal(budgetView(flightBudget({ fuel_l: 0, elec_w: 0 }, 'sabit_kanat')).empty, true); assert.equal(budgetView(null).empty, true);
  assert.equal(fmtMin(59.6), '1 sa'); assert.equal(fmtMin(45), '45 dk'); assert.equal(fmtMin(null), '—'); assert.equal(fmtKm(10.94), '10.9 km'); assert.equal(fmtKm(192.7), '193 km');
  assert.equal(fmtSec(3), '3 sn'); assert.equal(fmtSec(125), '2 dk 5 sn'); assert.equal(fmtSec(3725), '1 sa 2 dk'); assert.equal(fmtSec(null), '—');
});

console.log('Kayıt adı ve gövde');
test('nameKey: boşluk ve Türkçe büyük/küçük harf duyarsız (sunucu ad_anahtari)', () => {
  assert.equal(nameKey('  Termal   KEŞİF '), 'termal keşif'); assert.equal(nameKey('IŞIK İz'), nameKey('ışık iz')); assert.equal(normName('  a   b '), 'a b');
});
test('nameConflict / nameError: çakışma, kendisi hariç, silinmiş yok sayılır, boş/uzun ad', () => {
  const list = [{ id: 1, name: 'Termal keşif' }, { id: 2, name: 'Gece', deleted_at: '2026-01-01' }];
  assert.equal(nameConflict(list, 'TERMAL  KEŞİF')?.id, 1); assert.equal(nameConflict(list, 'termal keşif', 1), null); assert.equal(nameConflict(list, 'gece'), null);
  assert.equal(nameError(list, '   '), 'Kayıt adı gerekir'); assert.equal(nameError(list, 'x'.repeat(81)), 'Kayıt adı en çok {n} karakter olmalı');
  assert.match(nameError(list, 'termal keşif'), /zaten var/); assert.equal(nameError(list, 'Yeni ad'), null);
});
test('presetBodyFromSession: mode/log_id/airframe atılır; null/undefined alanlar girmez', () => {
  const b = presetBodyFromSession({ mode: 'sitl', log_id: 4, airframe: 'delta', type: 'sabit_kanat', center_id: 3, world: { seed: 1 }, drone_id: undefined, targets: undefined, site: null, power: { fuel_l: 2 }, camera: 'day' });
  assert.deepEqual(b, { type: 'sabit_kanat', center_id: 3, world: { seed: 1 }, power: { fuel_l: 2 }, camera: 'day' });
  assert.deepEqual(PRESET_FIELDS, ['type', 'center_id', 'world', 'model', 'drone_id', 'rec', 'power', 'camera', 'layout', 'targets', 'site', 'defend']);   // sunucu ALANLAR
});

console.log('Uçuş özeti karoları');
test('runFacts: süre, mesafe, sonuç (çarpışma kırmızı), yakıt/batarya bitti vurgusu, önleme, hız', () => {
  const r = { duration_s: 125, result: 'carpisma', crash_count: 2, intercept_count: 3, targets: JSON.stringify({ config: { items: [{}, {}, {}, {}] } }), speedup_max: 4, end_reason: 'kapatildi',
    power: { dist_m: 2300, max_speed_seen: 12.5, settings: { max_speed_ms: 45 }, fuel: { used_l: 0.15, km_per_l: 15.36, start_l: 0.15, left_l: 0, empty_t: 69.4 }, elec: { wh_used: 1.11, w_avg: 49.1, pct: 0, empty_t: 66.5 } } };
  const f = Object.fromEntries(runFacts(r).map(x => [x.key, x]));
  assert.equal(f.duration.value, '2 dk 5 sn'); assert.equal(f.dist.value, '2.3 km'); assert.equal(f.result.value, 'ÇARPIŞMA'); assert.equal(f.result.tone, 'alert'); assert.equal(f.crash.value, '2');
  assert.equal(f.intercept.value, '3 / 4'); assert.equal(f.fuel.value, '0.15 L · 15.4 km/L'); assert.equal(f.fuel.tone, 'alert'); assert.equal(f.elec.value, '1.1 Wh · 49 W'); assert.equal(f.elec.tone, 'alert');
  assert.equal(f.vmax.value, '45 km/h'); assert.equal(f.speedup.value, '4×'); assert.equal(f.end.value, 'Bitir ile kapandı');
  const t = Object.fromEntries(runFacts({ duration_s: 4, result: 'tamam', crash_count: 0 }).map(x => [x.key, x]));
  assert.equal(t.result.tone, 'ok'); assert.equal(t.dist.value, '—'); assert.equal(t.fuel, undefined); assert.equal(t.intercept, undefined);
  assert.deepEqual(resultBadge({ result: 'hata' }), ['orange', 'Hata']); assert.deepEqual(runFacts(null), []);
});

console.log(`\n${n} test geçti`);
