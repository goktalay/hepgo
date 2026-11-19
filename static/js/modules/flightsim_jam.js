// Uçuş Simülatörü — KARIŞTIRMA (docs/ucus-simulatoru.md §48 + §49; yalnız HEPGO oturum ekranı, ArduPilot oturumları). Alt bantta "Karıştırma" düğmesi;
// basınca düğmenin üstünde yukarı açılan panel: GPS karıştırma seviyesi (Kapalı / Hafif / Ağır / Tam), GPS aldatma (aç/kapa + sürükleme yönü ° +
// hız m/s + azami sapma m), bağlantı karıştırma (kumanda / telemetri), karıştırıcı bölgesi (merkez + yarıçap: etkiler yalnız araç içindeyken),
// kopterde konum kaybında otopilot tepkisi (İrtifa tut / İniş / Yalnız bildir), süre (sn; 0 = elle kapatılana kadar) ve Başlat / Uygula / Durdur.
// Etkinken düğme kırmızı yanıp söner ve sahnenin üstünde "KARIŞTIRMA" bandı görünür (seviye · sahte konum sapması · seyrüsefer hatası · kalan süre);
// bölge kuruluyken araç dışarıdaysa bant turuncu "bölge dışında" bekleme bandıdır. Sahnenin sol üstünde küçük harita (kuzey yukarı, araç ortada):
// karıştırıcı bölgesi, ev, gerçek iz ve otopilotun sandığı konumu gösteren "hayalet" işaretçi; panel açıkken haritaya tıklamak bölge merkezini taşır.
// Aynı model 3B sahnede de çizilir (flightsim_jam3d.js: bölge silindiri + hayalet işaretçi). Telemetri kesikken yer istasyonu göstergeleri
// (HUD) son alınan değerde kalır — 3B sahne "tanrı bakışı"dır, akmayı sürdürür.
// Benzetim SUNUCUDADIR (app/flightsim_jam.py: SITL'in SIM_GPS1_* / SIM_RC_FAIL parametreleri, sunucu içi bağlantı kapıları; ekranda araç GERÇEK
// konumunda çizilir, otopilotun sandığı konum tele.nav_lat / nav_lon) — ön yüz yalnız `jam` komutunu yollar ve `{t:'jam', reason, …durum}`
// çerçeveleri ile tele.jam / tele.nav_err alanlarını gösterir. Simülatör kip ZORLAMAZ: araç kendi arıza koruma ayarlarına göre davranır.
// Olay şeridi metinleri sunucudan gelir. Tercih kalıcı (localStorage fs.jam; bölge merkezi oturuma özgüdür, saklanmaz).
// Düğme yalnız session.jam.supported iken oluşturulur (PX4 / SIMUMAV oturumlarında yok).
// Saf katman (node testi tests/test_flightsim_jam.mjs): JAM_TEXTS, makeJamT, GPS_LEVELS, FS_MODES, LIMITS, DEFAULT_CFG, normalizeCfg, isActive, cmdBody,
//   cfgText, jamBtnKey, bannerText, mergeTele, tlmLost, parseLatLon, distM, moveM, zoneAhead, sceneModel, mapScale, mapProject, mapUnproject, jamReportLines.
// createJam({ tr, keyed, cmd(name, params) → Promise, onEvent(text, sev), session, stage, storage }) →
//   { el, banner, map, tlmBadge, update(tele), onFrame(m), attachSim(sim), open(), close(), isOpen, dispose(), get state }
//   ·  jamSection(sum, tr, h) → rapor bölümü (flightsim_report.js)
import { createJamLayer } from './flightsim_jam3d.js';

export const GPS_LEVELS = ['off', 'light', 'heavy', 'full'];
export const FS_MODES = ['althold', 'land', 'none'];   // kopter: GPS kaybında otopilot tepkisi (FS_EKF_ACTION 2 / 1 / 0)
export const LIMITS = { dir: [0, 360], speed: [0, 50], max_m: [1, 5000], dur_s: [0, 3600], r_m: [10, 20000] };
export const DEFAULT_CFG = { gps: 'off', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 0, rc: false, tlm: false, zone: { on: false, lat: null, lon: null, r_m: 300 } };

export const JAM_TEXTS = [
  ['jam.title', 'Karıştırma'],
  ['jam.title_t', 'Karıştırma: GPS karıştırma (jamming), GPS aldatma (spoofing) ve kumanda / telemetri bağlantısı kesintisini simülasyonda dener'],
  ['jam.btn_t', 'Karıştırma: GPS karıştırma, GPS aldatma, kumanda / telemetri bağlantısı, karıştırıcı bölgesi ve süre ayarı; başlat / durdur'],
  ['jam.gps', 'GPS karıştırma'], ['jam.off', 'Kapalı'], ['jam.light', 'Hafif'], ['jam.heavy', 'Ağır'], ['jam.full', 'Tam'],
  ['jam.off_t', 'GPS karıştırma yok'],
  ['jam.light_t', 'Hafif: uydu sayısı düşer, konum gürültülenir; uçuş sürer'],
  ['jam.heavy_t', 'Ağır: GPS kilidi aralıklı kaybolur, konum savrulur; otopilot konum kaybı tepkisini verebilir'],
  ['jam.full_t', 'Tam: GPS sinyali yok; otopilot konumunu yitirir ve konum kaybı tepkisini verir'],
  ['jam.spoof', 'GPS aldatma'],
  ['jam.spoof_t', 'GPS aldatma: alıcıya sahte konum verilir; otopilot kendini sürüklenen konumda sanar, araç gerçekte ters yöne kayar'],
  ['jam.dir', 'Sürükleme yönü'], ['jam.dir_t', 'Sahte konumun sürüklendiği yön (°; 0 = kuzey, 90 = doğu)'],
  ['jam.speed', 'Sürükleme hızı'], ['jam.speed_t', 'Sürükleme hızı (m/s; 0 = anında sıçrama)'],
  ['jam.max', 'Azami sapma'], ['jam.max_t', 'Sahte konumun gerçek konumdan en çok uzaklaşacağı mesafe (m)'],
  ['jam.dur', 'Süre'], ['jam.dur_t', 'Süre (sn; 0 = elle kapatılana kadar)'], ['jam.forever', 'süresiz'], ['jam.sec', 'sn'],
  ['jam.start', 'Başlat'], ['jam.apply', 'Uygula'], ['jam.stop', 'Durdur'], ['jam.close', 'Kapat'],
  ['jam.active', 'Karıştırılıyor'], ['jam.recovering', 'Toparlanıyor'],
  ['jam.fake_note', 'Bu oturum SITL\'siz çalışıyor: yalnız göstergeler etkilenir'],
  ['jam.nothing', 'Önce bir karıştırma seçin: GPS karıştırma, GPS aldatma, kumanda ya da telemetri bağlantısı'],
  ['jam.link', 'Bağlantı karıştırma'],
  ['jam.rc', 'Kumanda bağlantısı'],
  ['jam.rc_t', 'Kumanda bağlantısı kesilir: çubuk ve düğme komutları araca ulaşmaz; araç kendi kumanda kaybı (failsafe) ayarına göre davranır'],
  ['jam.tlm', 'Telemetri bağlantısı'],
  ['jam.tlm_t', 'Telemetri bağlantısı kesilir: yer istasyonu komutları araca ulaşmaz, göstergeler son alınan değerde kalır; araç kendi yer istasyonu kaybı ayarına göre davranır'],
  ['jam.link_h', 'Simülatör kip zorlamaz: araç kendi arıza koruma ayarlarına göre davranır'],
  ['jam.zone', 'Karıştırıcı bölgesi'],
  ['jam.zone_t', 'Karıştırıcı bölgesi: etkiler yalnız araç bölgenin içindeyken uygulanır, dışarı çıkınca kalkar'],
  ['jam.zone_r', 'Yarıçap'], ['jam.zone_r_t', 'Bölge yarıçapı (m)'],
  ['jam.zone_c', 'Bölge merkezi'], ['jam.zone_c_t', 'Bölge merkezi: enlem, boylam (ondalık derece)'],
  ['jam.zone_here', 'Araç konumu'], ['jam.zone_here_t', 'Bölge merkezini aracın şimdiki konumuna koyar (araç hemen etkilenir)'],
  ['jam.zone_ahead', 'Aracın önüne'], ['jam.zone_ahead_t', 'Bölgeyi aracın burun yönüne, sınırı 150 m ileride olacak biçimde koyar'],
  ['jam.zone_map', 'Merkezi taşımak için küçük haritaya tıklayın'],
  ['jam.zone_nopos', 'Araç konumu bilinmiyor: bölge merkezi atanamadı'],
  ['jam.zone_bad', 'Bölge merkezi "enlem, boylam" biçiminde olmalı (örn. 39.92500, 32.83700)'],
  ['jam.fs', 'Konum kaybında otopilot'],
  ['jam.fs_althold', 'İrtifa tut'], ['jam.fs_land', 'İniş'], ['jam.fs_none', 'Yalnız bildir'],
  ['jam.fs_althold_t', 'İrtifa tut: otopilot ALT_HOLD kipine geçer; irtifayı korur, araç rüzgârla sürüklenir (FS_EKF_ACTION 2)'],
  ['jam.fs_land_t', 'İniş: otopilot LAND kipine geçip bulunduğu yere iner — ArduPilot fabrika ayarı (FS_EKF_ACTION 1)'],
  ['jam.fs_none_t', 'Yalnız bildir: otopilot kip değiştirmez; hatalı konumla uçmayı sürdürür ve sürüklenir (FS_EKF_ACTION 0)'],
  ['jam.c_rc', 'kumanda kesik'], ['jam.c_tlm', 'telemetri kesik'], ['jam.c_zone', 'bölge {r} m'],
  ['jam.banner', 'KARIŞTIRMA'], ['jam.b_spoof', 'GPS ALDATMA'], ['jam.b_recover', 'GPS TOPARLANIYOR'],
  ['jam.b_light', 'GPS ZAYIF'], ['jam.b_heavy', 'GPS KESİNTİLİ'], ['jam.b_full', 'GPS YOK'],
  ['jam.b_off', 'sahte konum sapması {m} m'], ['jam.b_err', 'seyrüsefer hatası {m} m'], ['jam.b_left', 'kalan {s} sn'],
  ['jam.b_fake', 'yalnız göstergeler'],
  ['jam.b_rc', 'KUMANDA YOK'], ['jam.b_tlm', 'TELEMETRİ YOK'], ['jam.b_zone', 'KARIŞTIRICI BÖLGESİ DIŞINDA'],
  ['jam.b_zone_d', 'bölge sınırına {m} m'], ['jam.b_thr', 'gaz ortada (irtifa korunur)'], ['jam.b_hold', 'göstergeler son alınan değerde'],
  ['jam.map', 'Karıştırma haritası'],
  ['jam.map_t', 'Karıştırma haritası: kuzey yukarı, araç ortada. Daire: karıştırıcı bölgesi; pembe işaret: otopilotun sandığı konum'],
  ['jam.map_click', 'Tıklayın: bölge merkezi'], ['jam.lg_ghost', 'otopilot konumu'], ['jam.lg_in', 'bölge içinde'],
  ['jam.zone_l', 'KARIŞTIRICI · {r} m'], ['jam.ghost_l', 'OTOPİLOT KONUMU · {m} m'],
  ['jam.hud_lost', 'TELEMETRİ YOK · son alınan değerler'],
  ['jam.ev_settled', 'GPS toparlandı — seyrüsefer gerçek konuma döndü'],
  ['jam.err', 'Karıştırma: {e}'],
];
const TXT = Object.fromEntries(JAM_TEXTS);
const fill = (s, p) => (p ? String(s).replace(/\{(\w+)\}/g, (m, k) => (p[k] != null ? String(p[k]) : m)) : String(s));
/** HEPGO (keyed=false) Türkçe metni anahtar verir; keyed=true ise `jam.*` anahtarını, yoksa Türkçe. */
export const makeJamT = (tr, keyed = false) => (k, p) => {
  const tx = TXT[k] ?? k;
  if (!tr) return fill(tx, p);
  if (!keyed) return tr(tx, p);
  const r = tr(k, p);
  return r && r !== k ? r : fill(tx, p);
};

const clampNum = (v, [a, b], d, step = 1) => {
  const n = Number(v);
  if (v === '' || v == null || !Number.isFinite(n)) return d;
  return Math.min(b, Math.max(a, Math.round(n / step) * step));
};
const r7 = v => Math.round(Number(v) * 1e7) / 1e7;
const coord = (v, lim) => { const n = Number(v); return v == null || v === '' || !Number.isFinite(n) || Math.abs(n) > lim ? null : r7(n); };
/** Ayar sözlüğü → sunucu sınırlarına kırpılmış {gps, spoof: {on, dir, speed, max_m}, dur_s, rc, tlm, zone: {on, lat, lon, r_m}} (merkezsiz bölge açık sayılmaz). */
export function normalizeCfg(c = {}) {
  const sp = c?.spoof || {}, d = DEFAULT_CFG.spoof, z = c?.zone || {};
  const lat = coord(z.lat, 90), lon = coord(z.lon, 180), ok = lat != null && lon != null;
  return {
    gps: GPS_LEVELS.includes(c?.gps) ? c.gps : 'off',
    spoof: { on: !!sp.on, dir: clampNum(sp.dir, LIMITS.dir, d.dir) % 360, speed: Number(clampNum(sp.speed, LIMITS.speed, d.speed, 0.1).toFixed(1)),
      max_m: clampNum(sp.max_m, LIMITS.max_m, d.max_m) },
    dur_s: clampNum(c?.dur_s, LIMITS.dur_s, 0),
    rc: !!c?.rc, tlm: !!c?.tlm,
    zone: { on: !!z.on && ok, lat: ok ? lat : null, lon: ok ? lon : null, r_m: clampNum(z.r_m, LIMITS.r_m, DEFAULT_CFG.zone.r_m) },
  };
}
/** Karıştırılacak bir şey var mı (bölge tek başına bir etki değildir). */
export const isActive = c => !!c && (c.gps !== 'off' && c.gps != null || !!c.spoof?.on || !!c.rc || !!c.tlm);
/** `jam` komutunun gövdesi (etkin olmayan ayar → null: gönderilmez). `fs` yalnız kopter oturumunda verilir. */
export function cmdBody(c, fs) {
  const n = normalizeCfg(c);
  if (!isActive(n)) return null;
  const b = { gps: n.gps, spoof: { ...n.spoof }, dur_s: n.dur_s, rc: n.rc, tlm: n.tlm, zone: { ...n.zone } };
  if (FS_MODES.includes(fs)) b.fs = fs;
  return b;
}
const f1 = v => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(1));
const f0 = v => (v == null || !Number.isFinite(Number(v)) ? '—' : String(Math.round(Number(v))));
/** Kısa ayar metni: "GPS karıştırma: Ağır · GPS aldatma 90° · 2 m/s · 200 m · kumanda kesik · bölge 300 m · 30 sn". */
export function cfgText(c, T = (k, p) => fill(TXT[k] ?? k, p)) {
  const n = normalizeCfg(c), p = [];
  if (n.gps !== 'off') p.push(`${T('jam.gps')}: ${T(`jam.${n.gps}`)}`);
  if (n.spoof.on) p.push(`${T('jam.spoof')} ${n.spoof.dir}° · ${n.spoof.speed} m/s · ${n.spoof.max_m} m`);
  if (n.rc) p.push(T('jam.c_rc'));
  if (n.tlm) p.push(T('jam.c_tlm'));
  if (p.length && n.zone.on) p.push(T('jam.c_zone', { r: n.zone.r_m }));
  if (p.length && n.dur_s) p.push(`${n.dur_s} ${T('jam.sec')}`);
  return p.join(' · ') || T('jam.off');
}
/** Alt bant düğmesinin metin anahtarı: boşta "Karıştırma", etkinken "Karıştırılıyor", kapandıktan sonra EKF toparlanırken "Toparlanıyor". */
export const jamBtnKey = st => (st?.on ? 'jam.active' : st?.real ? 'jam.recovering' : 'jam.title');
/** Sahne üstü bandı: {main, sub, recover, wait} ya da null (band gizli). wait = bölge kurulu ama araç dışarıda (etki yok). */
export function bannerText(st, T = (k, p) => fill(TXT[k] ?? k, p)) {
  if (!st?.supported) return null;
  const err = st.nav_err != null ? T('jam.b_err', { m: f1(st.nav_err) }) : null;
  if (!st.on) return st.real ? { main: T('jam.b_recover'), sub: err || '', recover: true, wait: false } : null;
  const left = st.left_s != null ? T('jam.b_left', { s: Math.ceil(Number(st.left_s)) }) : null;
  const z = st.zone;
  if (z?.on && st.active === false) {
    const d = z.dist_m != null && z.r_m != null ? T('jam.b_zone_d', { m: f0(Math.max(0, Number(z.dist_m) - Number(z.r_m))) }) : null;
    return { main: T('jam.b_zone'), sub: [d, st.real ? err : null, left].filter(Boolean).join(' · '), recover: false, wait: true };
  }
  const sp = st.spoof?.on, main = [T('jam.banner')];
  if (st.gps && st.gps !== 'off') main.push(T(`jam.b_${st.gps}`));
  if (sp) main.push(T('jam.b_spoof'));
  if (st.rc) main.push(T('jam.b_rc'));
  if (st.tlm) main.push(T('jam.b_tlm'));
  const sub = [sp ? T('jam.b_off', { m: f1(st.off_m) }) : null, st.sim === 'fake' ? T('jam.b_fake') : err, st.thr_mid ? T('jam.b_thr') : null, st.tlm ? T('jam.b_hold') : null, left];
  return { main: main.join(' · '), sub: sub.filter(Boolean).join(' · '), recover: false, wait: false };
}
/** Telemetriden canlı alanlar (tele.jam = {gps, spoof, off_m, left_s, rc, tlm, active, inside?, dist_m?}; tele.nav_err) durum sözlüğüne işlenir. */
export function mergeTele(st, t) {
  if (!st?.supported || !t) return st;
  const j = t.jam, out = { ...st };
  if (j) {
    out.off_m = j.off_m ?? out.off_m; out.left_s = j.left_s ?? null;
    if (j.active != null) out.active = !!j.active;
    if (j.inside !== undefined || j.dist_m !== undefined) out.zone = { ...(out.zone || {}), inside: j.inside ?? null, dist_m: j.dist_m ?? null };
  }
  if (st.on || st.real) out.nav_err = t.nav_err ?? (st.sim === 'fake' ? null : out.nav_err);
  return out;
}
/** Telemetri bağlantısı şu an kesik mi (yer istasyonu göstergeleri son alınan değerde kalır). */
export const tlmLost = t => !!(t?.jam?.tlm && t.jam.active);

// ---- konum yardımcıları (düz dünya yaklaşımı; sunucudaki fark_m / ofset_derece ile aynı sabitler) ----
const M_LAT = 110574, M_LON = 111320, RAD = Math.PI / 180;
export const GHOST_MIN_M = 2;   // otopilotun sandığı konum bundan az sapmışsa hayalet çizilmez (araçla üst üste biner)
/** "enlem, boylam" metni → {lat, lon} ya da null. */
export function parseLatLon(s) {
  const m = /^\s*(-?\d+(?:\.\d+)?)\s*(?:[,;]\s*|\s+)(-?\d+(?:\.\d+)?)\s*$/.exec(String(s ?? ''));
  if (!m) return null;
  const lat = coord(m[1], 90), lon = coord(m[2], 180);
  return lat != null && lon != null ? { lat, lon } : null;
}
/** a → b ofseti (m; e doğu, n kuzey). */
export const offsetM = (a, b) => ({ e: (b.lon - a.lon) * M_LON * Math.cos((a.lat + b.lat) / 2 * RAD), n: (b.lat - a.lat) * M_LAT });
export const distM = (a, b) => { const o = offsetM(a, b); return Math.hypot(o.e, o.n); };
/** a noktasının e m doğusu, n m kuzeyi. */
export const moveM = (a, e, n) => ({ lat: r7(a.lat + n / M_LAT), lon: r7(a.lon + e / (M_LON * Math.cos(a.lat * RAD))) });
export const headingOf = t => (t?.heading != null ? Number(t.heading) : t?.yaw != null ? ((Number(t.yaw) / RAD) % 360 + 360) % 360 : 0);
/** Bölge merkezi: aracın burun yönünde, sınırı `gap` m ileride. */
export function zoneAhead(veh, r_m, gap = 150) {
  const d = Number(r_m) + gap, h = (Number(veh.hdg) || 0) * RAD;
  return moveM(veh, Math.sin(h) * d, Math.cos(h) * d);
}
/** Sahne modeli (küçük harita + 3B katman ortak): {zone: {lat, lon, r_m, state: 'in' | 'out' | 'draft'} | null, ghost: {lat, lon, err} | null, veh, home, live}.
 *  Panel açıkken henüz uygulanmamış bölge 'draft' (taslak) çizilir; hayalet = otopilotun sandığı konum (tele.nav_lat / nav_lon). */
export function sceneModel(st, cfg, t, { panelOpen = false, home = null } = {}) {
  const live = !!(st?.on || st?.real);
  const veh = t && t.lat != null && t.lon != null ? { lat: Number(t.lat), lon: Number(t.lon), hdg: headingOf(t) } : null;
  const sz = st?.on && st.zone?.on && st.zone.lat != null ? st.zone : null, cz = cfg?.zone?.on && cfg.zone.lat != null ? cfg.zone : null;
  const same = !!(sz && cz) && sz.lat === cz.lat && sz.lon === cz.lon && Number(sz.r_m) === Number(cz.r_m);
  let zone = null;
  if (panelOpen && cz && !same) zone = { lat: cz.lat, lon: cz.lon, r_m: Number(cz.r_m), state: 'draft' };
  else if (sz) zone = { lat: sz.lat, lon: sz.lon, r_m: Number(sz.r_m), state: (sz.inside ?? st.active !== false) ? 'in' : 'out' };
  let ghost = null;
  if (live && veh && t.nav_lat != null && t.nav_lon != null) {
    const g = { lat: Number(t.nav_lat), lon: Number(t.nav_lon) }, err = t.nav_err != null ? Number(t.nav_err) : distM(veh, g);
    if (err >= GHOST_MIN_M) ghost = { ...g, err };
  }
  return { zone, ghost, veh, home: home && home.lat != null && home.lon != null ? { lat: Number(home.lat), lon: Number(home.lon) } : null, live };
}
const MAP_STEPS = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];
/** Küçük haritanın yarı genişliği (m; 1-2-5 basamaklı): araç ortada; bölgenin tamamı ve hayalet sığar. Taslak bölgede tıklanacak pay bırakılır.
 *  pad > 1: küçülme eşiği (ölçek basamak sınırında gidip gelmesin diye çağıran histerezis uygular). */
export function mapScale(m, pad = 1) {
  const c = m?.veh || m?.home;
  let need = MAP_STEPS[0];
  if (c && m.ghost) need = Math.max(need, distM(c, m.ghost) * 1.25);
  if (m?.zone) {
    need = Math.max(need, ((c ? distM(c, m.zone) : 0) + m.zone.r_m) * 1.1);
    if (m.zone.state === 'draft') need = Math.max(need, 500, m.zone.r_m * 2.5);
  }
  return MAP_STEPS.find(v => v >= need * pad) ?? MAP_STEPS[MAP_STEPS.length - 1];
}
/** Konum → harita pikseli (kuzey yukarı; c merkez, half yarı genişlik m, size kenar px). */
export function mapProject(c, half, size, p) {
  const o = offsetM(c, p), k = size / 2 / half;
  return { x: size / 2 + o.e * k, y: size / 2 - o.n * k };
}
/** Harita pikseli → konum. */
export const mapUnproject = (c, half, size, x, y) => moveM(c, (x - size / 2) * 2 * half / size, (size / 2 - y) * 2 * half / size);
export const fmtDist = m => (m >= 1000 ? `${Number((m / 1000).toFixed(m % 1000 ? 1 : 0))} km` : `${Math.round(m)} m`);

const LEVEL_LABEL = { light: 'hafif', heavy: 'ağır', full: 'tam' };
/** Rapor metni satırı (paylaşım metni): oturumda karıştırma hiç açılmadıysa []. */
export function jamReportLines(sum, tr = fill) {
  const J = sum?.jam; if (!J?.count) return [];
  const p = [tr('{n} kez', { n: J.count })];
  const g = Object.entries(J.gps_s || {}).filter(([k, v]) => LEVEL_LABEL[k] && v > 0).map(([k, v]) => `${tr(LEVEL_LABEL[k])} ${f0(v)} ${tr('sn')}`);
  if (g.length) p.push(`${tr('GPS karıştırma')} ${g.join(', ')}`);
  if (J.spoof_s > 0) p.push(`${tr('GPS aldatma')} ${f0(J.spoof_s)} ${tr('sn')} (${tr('en büyük sapma')} ${f1(J.max_off_m)} m)`);
  if (J.rc_s > 0) p.push(`${tr('kumanda bağlantısı')} ${f0(J.rc_s)} ${tr('sn')}`);
  if (J.tlm_s > 0) p.push(`${tr('telemetri bağlantısı')} ${f0(J.tlm_s)} ${tr('sn')}`);
  if (J.zone) p.push(`${tr('bölge')} ${f0(J.zone.r_m)} m (${tr('{n} giriş', { n: J.zone.entries ?? 0 })})`);
  if (J.sim === 'fake') p.push(tr('yalnız göstergeler'));
  else if (J.max_nav_err > 0) p.push(`${tr('en büyük seyrüsefer hatası')} ${f1(J.max_nav_err)} m`);
  return [`${tr('Karıştırma')}: ${p.join(' · ')}`];
}
/** Rapor bölümü (flightsim_report.js reportBody içinden; h = ui.js h). */
export function jamSection(sum, tr, h) {
  const J = sum?.jam; if (!J?.count) return null;
  ensureCss();
  const tile = (label, value, unit, cls = '') => h('div', { class: `fs-rp-tile ${cls}` }, h('b', null, value, unit ? h('i', null, unit) : null), h('span', null, label));
  const kv = (k, v) => h('div', { class: 'fs-rp-kv' }, h('span', null, k), h('b', null, v));
  const gs = J.gps_s || {}, gTot = Object.values(gs).reduce((a, v) => a + (Number(v) || 0), 0), fake = J.sim === 'fake';
  const lv = Object.entries(gs).filter(([k, v]) => LEVEL_LABEL[k] && v > 0).map(([k, v]) => `${tr(LEVEL_LABEL[k])} ${f0(v)} ${tr('sn')}`).join(' · ');
  return h('div', { class: 'fs-rp-sec fs-rp-jam' }, h('h4', null, '📡 ', tr('Karıştırma')),
    h('div', { class: 'fs-rp-tiles fs-rp-jam-tiles' },
      tile(tr('Karıştırma sayısı'), String(J.count), ''),
      tile(tr('GPS karıştırma süresi'), f0(gTot), tr('sn'), gTot > 0 ? 'orange' : ''),
      tile(tr('GPS aldatma süresi'), f0(J.spoof_s), tr('sn'), J.spoof_s > 0 ? 'orange' : ''),
      J.rc_s > 0 ? tile(tr('Kumanda kesintisi süresi'), f0(J.rc_s), tr('sn'), 'orange') : null,
      J.tlm_s > 0 ? tile(tr('Telemetri kesintisi süresi'), f0(J.tlm_s), tr('sn'), 'orange') : null,
      tile(tr('En büyük sahte konum sapması'), f1(J.max_off_m), 'm'),
      fake ? null : tile(tr('En büyük seyrüsefer hatası'), f1(J.max_nav_err), 'm', J.max_nav_err > 0 ? 'red' : '')),
    lv ? kv(tr('Seviye başına süre'), lv) : null,
    J.zone ? kv(tr('Karıştırıcı bölgesi'), `${Number(J.zone.lat).toFixed(5)}, ${Number(J.zone.lon).toFixed(5)} · ${f0(J.zone.r_m)} m · ${tr('{n} giriş', { n: J.zone.entries ?? 0 })}`) : null,
    h('div', { class: 'small muted' }, fake ? tr('Bu oturum SITL\'siz çalıştı: karıştırma yalnız göstergeleri etkiledi')
      : tr('Seyrüsefer hatası: otopilotun sandığı konum ile aracın gerçek konumu arasındaki yatay mesafe')));
}

// ---------------- alt bant bileşeni ----------------
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const CSS = `
.fs-jam{display:inline-flex;align-items:center;position:relative}
.fs-jam-btn{display:inline-flex;align-items:center;gap:6px;font-weight:700}
.fs-jam-btn svg{flex:none;opacity:.9}
.fs-bar .fs-jam[data-state=on] .fs-jam-btn{background:#dc2626;border-color:#dc2626;color:#fff;animation:fs-jam-pulse 1s ease-in-out infinite}
.fs-bar .fs-jam[data-state=recover] .fs-jam-btn,.fs-bar .fs-jam[data-state=wait] .fs-jam-btn{background:#b45309;border-color:#b45309;color:#fff}
@keyframes fs-jam-pulse{0%,100%{background:#dc2626;box-shadow:0 0 0 0 rgba(239,68,68,.65)}50%{background:#7f1d1d;box-shadow:0 0 0 6px rgba(239,68,68,0)}}
@media (prefers-reduced-motion:reduce){.fs-bar .fs-jam .fs-jam-btn{animation:none!important}}
.fs-jam-pop{position:absolute;bottom:calc(100% + 10px);left:0;z-index:40;width:max-content;min-width:288px;max-width:min(92vw,360px);padding:10px 12px 12px;border-radius:12px;
  background:rgba(14,20,30,.97);color:#e6edf3;border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 44px rgba(0,0,0,.55);backdrop-filter:blur(6px);display:grid;gap:8px;font-size:12px}
.fs-jam-pop[hidden]{display:none}
.fs-jam-pop::after{content:'';position:absolute;left:var(--fs-jam-arrow,28px);bottom:-6px;width:10px;height:10px;background:inherit;border-right:1px solid rgba(255,255,255,.14);border-bottom:1px solid rgba(255,255,255,.14);transform:rotate(45deg)}
.fs-jam-pop h6{margin:0;display:flex;align-items:center;gap:8px;font:800 10.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;opacity:.8}
.fs-jam-pop h6 span{flex:1}
.fs-jam-pop .fs-jam-x{border:0;background:transparent;color:inherit;opacity:.7;cursor:pointer;font-size:16px;line-height:1;padding:0 2px}
.fs-jam-pop .fs-jam-x:hover{opacity:1}
.fs-jam-sec{display:grid;gap:6px;padding-top:8px;border-top:1px solid rgba(255,255,255,.1)}
.fs-jam-sec>b{font:700 12px/1.2 system-ui,sans-serif}
.fs-jam-seg{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.fs-jam-seg button{height:30px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);color:#e6edf3;font:600 12px/1 system-ui,sans-serif;cursor:pointer;padding:0 6px}
.fs-jam-seg button:hover{background:rgba(255,255,255,.13)}
.fs-jam-seg button[aria-pressed=true]{background:#1f6feb;border-color:#1f6feb;color:#fff}
.fs-jam-seg button[aria-pressed=true]:not([data-v=off]){background:#dc2626;border-color:#dc2626}
.fs-jam-hint{opacity:.7;font-size:11px;line-height:1.35;min-height:2.7em}
.fs-jam-sw{display:flex;align-items:center;gap:8px;cursor:pointer;font:700 12px/1.2 system-ui,sans-serif}
.fs-jam-sw input{width:16px;height:16px;accent-color:#dc2626;margin:0}
.fs-jam-row{display:grid;grid-template-columns:104px 1fr;align-items:center;gap:8px}
.fs-jam-row[hidden]{display:none}
.fs-jam-row>span{opacity:.75}
.fs-jam-row>div{display:flex;align-items:center;gap:6px;min-width:0}
.fs-jam-pop input[type=number]{height:30px;width:84px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);color:#e6edf3;font:600 12.5px/1 system-ui,sans-serif;padding:0 8px;min-width:0;text-align:right;font-variant-numeric:tabular-nums}
.fs-jam-pop i{font-style:normal;opacity:.6;font-size:11px}
.fs-jam-arrow{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;border:1px solid rgba(255,255,255,.2);opacity:1!important;font-size:13px!important;transition:transform .15s}
.fs-jam-live{font:700 12px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;color:#fca5a5}
.fs-jam-live[hidden],.fs-jam-note[hidden]{display:none}
.fs-jam-note{padding:6px 8px;border-radius:8px;background:rgba(245,158,11,.14);border:1px solid rgba(245,158,11,.4);color:#fde68a;font-size:11px;line-height:1.35}
.fs-jam-acts{display:flex;gap:6px}
.fs-jam-act{flex:1;height:34px;border-radius:9px;border:1px solid #1f6feb;background:#1f6feb;color:#fff;font:700 13px/1 system-ui,sans-serif;cursor:pointer}
.fs-jam-act:hover{filter:brightness(1.1)}
.fs-jam-act.stop{background:#dc2626;border-color:#dc2626}
.fs-jam-act[hidden]{display:none}
.fs-jam-act:disabled{opacity:.55;cursor:default}
.fs-bar:has(.fs-jam-pop:not([hidden])){z-index:9}
.fs-jam-banner{position:absolute;left:50%;top:104px;transform:translateX(-50%);z-index:8;pointer-events:none;display:flex;flex-direction:column;align-items:center;gap:2px;width:max-content;max-width:92%;text-align:center;
  padding:7px 16px;border-radius:10px;background:rgba(60,8,8,.86);border:1px solid rgba(248,113,113,.8);color:#fecaca;font:800 14px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.fs-jam-banner.recover,.fs-jam-banner.wait{background:rgba(60,34,6,.86);border-color:rgba(251,191,36,.75);color:#fde68a}
.fs-jam-banner small{font:600 11px/1.2 system-ui,sans-serif;letter-spacing:0;color:#fee2e2}
.fs-jam-banner.recover small,.fs-jam-banner.wait small{color:#fef3c7}
.fs-jam-banner small:empty{display:none}
.fs-jam-banner[hidden]{display:none}
.fs-srv-banner:not([hidden])~.fs-jam-banner{top:156px}
@media (max-width:640px){.fs-jam-banner{font-size:11px;letter-spacing:.02em;padding:6px 10px;max-width:calc(100% - 16px)}.fs-jam-banner span,.fs-jam-banner small{max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
/* Dar sahnede bant ortalanınca sol üstteki rüzgâr kutusunun altında kalır: bandı kutunun, haritayı bandın altına al */
@media (max-width:1000px){.fs-jam-banner{top:152px}.fs-srv-banner:not([hidden])~.fs-jam-banner{top:204px}}
@media (max-width:760px){.fs-jam-banner{top:142px}.fs-srv-banner:not([hidden])~.fs-jam-banner{top:194px}}
.fs-stage.fs-mob-open:has(.fs-jam-pop:not([hidden])) .fs-nav{display:none!important}
.fs-rp-jam-tiles .fs-rp-tile.red b{color:#dc2626}
.fs-jam-body{display:grid;gap:8px;overflow-y:auto;overscroll-behavior:contain;max-height:max(150px,min(600px,calc(100vh - 300px)));margin-right:-6px;padding-right:6px;scrollbar-width:thin}
.fs-jam-body>.fs-jam-sec:first-child,.fs-jam-body>.fs-jam-note+.fs-jam-sec{border-top:0;padding-top:0}
.fs-jam-sec[hidden],.fs-jam-mini[hidden],.fs-jam-sub[hidden]{display:none}
.fs-jam-seg.fs-jam-fs{grid-template-columns:repeat(3,1fr)}
.fs-jam-seg.fs-jam-fs button[aria-pressed=true]{background:#1f6feb;border-color:#1f6feb}
.fs-jam-fs+.fs-jam-hint{min-height:4em}
.fs-jam-sub{opacity:.7;font-size:11px;line-height:1.35}
.fs-jam-pop input[type=text]{height:30px;flex:1;width:100%;min-width:0;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);color:#e6edf3;font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;padding:0 8px}
.fs-jam-mini{display:flex;gap:6px}
.fs-jam-mini button{flex:1;height:28px;border-radius:8px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.07);color:#e6edf3;font:600 11.5px/1 system-ui,sans-serif;cursor:pointer;padding:0 6px}
.fs-jam-mini button:hover{background:rgba(255,255,255,.14)}
.fs-jam-map{position:absolute;left:14px;top:154px;z-index:7;box-sizing:border-box;width:178px;padding:5px 6px 6px;border-radius:10px;background:rgba(10,16,26,.8);border:1px solid rgba(255,255,255,.16);color:#e6edf3;
  font:600 10.5px/1.25 system-ui,sans-serif;pointer-events:none;backdrop-filter:blur(4px);box-shadow:0 4px 16px rgba(0,0,0,.3);user-select:none}
.fs-jam-map[hidden]{display:none}
.fs-jam-map.fs-jam-pick{pointer-events:auto;cursor:crosshair;border-color:#38bdf8;box-shadow:0 0 0 2px rgba(56,189,248,.35),0 4px 16px rgba(0,0,0,.3)}
.fs-jam-map header{display:flex;justify-content:space-between;align-items:baseline;gap:6px;margin-bottom:4px;font:800 9.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;text-transform:uppercase}
.fs-jam-map header b{opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-jam-map header span{flex:none;color:#9fb1c4;text-transform:none;letter-spacing:0}
.fs-jam-map canvas{display:block;width:166px;height:166px;border-radius:6px;background:#0b1220}
.fs-jam-map footer{display:grid;gap:2px;margin-top:4px;min-height:13px}
.fs-jam-map footer div{display:flex;align-items:center;gap:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-jam-map footer i{flex:none;width:8px;height:8px;border-radius:50%;border:2px solid currentColor;box-sizing:border-box}
.fs-jam-map footer .in{color:#fca5a5}.fs-jam-map footer .out{color:#fcd34d}.fs-jam-map footer .draft{color:#7dd3fc}.fs-jam-map footer .ghost{color:#f0abfc}
@media (max-width:640px){.fs-jam-map{width:124px;padding:4px 5px 5px}.fs-jam-map canvas{width:112px;height:112px}.fs-jam-map header b{display:none}.fs-jam-map header{justify-content:flex-end}}
@media (max-width:1000px){.fs-jam-map{top:206px}}
@media (max-width:760px){.fs-jam-map{top:192px}}
.fs-jam-tlmb{display:block;margin:0 0 6px;padding:5px 8px;border-radius:7px;background:rgba(127,29,29,.92);border:1px solid rgba(248,113,113,.8);color:#fecaca;font:800 10.5px/1.25 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.03em;text-align:center}
.fs-jam-tlmb[hidden]{display:none}
.fs-stage.fs-tlm-lost .fs-hud>*:not(.fs-jam-tlmb),.fs-stage.fs-tlm-lost .fs-pn{opacity:.55}
`;
function ensureCss() {
  if (typeof document === 'undefined' || document.getElementById('fs-jam-css')) return;
  const s = document.createElement('style'); s.id = 'fs-jam-css'; s.textContent = CSS; document.head.appendChild(s);
}

const PREF = 'fs.jam';
const readJson = (st, k) => { try { return JSON.parse(st?.getItem(k) || 'null'); } catch { return null; } };
// Yayın simgesi (anten + çapraz çizgi: bozulan sinyal); düğmede metnin solunda
const JAM_ICON_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 13v8"/><circle cx="12" cy="11" r="1.6"/><path d="M8.2 14.8a5.4 5.4 0 0 1 0-7.6M15.8 7.2a5.4 5.4 0 0 1 0 7.6M5.4 17.6a9.4 9.4 0 0 1 0-13.2M18.6 4.4a9.4 9.4 0 0 1 0 13.2"/><path d="M3 3l18 18"/></svg>';

const ZONE_CSS = { in: '#ef4444', out: '#f59e0b', draft: '#38bdf8' }, GHOST_CSS = '#e879f9';
const TRAIL_MAX = 160;
const PAINT_MS = 100;   // telemetri 50 Hz gelir; panel / bant / küçük harita / 3B katman telemetriyle en çok 10 Hz boyanır (komut ve durum çerçevesi anında)

// Alt bantta "Karıştırma" düğmesi; basınca düğmenin ÜSTÜNDE yukarı açılan panel. Etkinken ayarlar değiştirilebilir ("Uygula"); "Durdur" kapatır.
// Başlat / Uygula sonrası panel kapanır (durum sahne üstü bandında izlenir). Dışarı tıklama / Esc kapatır.
// Sahneye üç öğe ekler: bant (üst orta), küçük harita (sol üst; bölge / hayalet varken) ve 3B katman (attachSim ile; flightsim_jam3d.js).
export function createJam({ tr, keyed = false, cmd, onEvent = () => {}, session = null, stage = null, storage = (typeof localStorage !== 'undefined' ? localStorage : null), btnClass = 'btn sm' } = {}) {
  ensureCss();
  const T = makeJamT(tr, keyed);
  let st = { supported: true, on: false, real: false, sim: 'sitl', off_m: 0, left_s: null, nav_err: null, ...(session?.jam || {}) };
  // Sayfa yenilendi / ikinci sekme: sunucudaki etkin ayar. Boştayken kayıtlı tercih; bölge merkezi oturuma özgüdür (sunucunun son bildiği merkez, kapalı).
  const saved = readJson(storage, PREF) || DEFAULT_CFG;
  let cfg = normalizeCfg(st.on ? st : { ...saved, zone: { r_m: saved.zone?.r_m, ...(st.zone?.lat != null ? { lat: st.zone.lat, lon: st.zone.lon, r_m: st.zone.r_m } : {}), on: false } });
  let fsSel = FS_MODES.includes(st.fs) ? st.fs : FS_MODES[0], fsTouched = false;   // konum kaybı tepkisi (kopter): sunucudaki değer; kullanıcı değiştirince onunki
  let busy = false, lastT = null, layer = null, mapGeo = null, mapHalf = 0, paintAt = -Infinity;
  const nowMs = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const paintDue = () => nowMs() - paintAt >= PAINT_MS;
  const realTrail = [], navTrail = [];
  const keys = inp => inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });   // rakamlar kamera kısayollarına gitmesin
  const seg = el('div', { class: 'fs-jam-seg', role: 'group', 'aria-label': T('jam.gps') },
    GPS_LEVELS.map(v => el('button', { type: 'button', 'data-v': v, title: T(`jam.${v}_t`), onclick: e => { e.stopPropagation(); cfg.gps = v; save(); paint(); } }, T(`jam.${v}`))));
  const hint = el('div', { class: 'fs-jam-hint' });
  const spoofChk = el('input', { type: 'checkbox', class: 'fs-jam-spoof', onchange: () => { cfg.spoof.on = spoofChk.checked; save(); paint(); } });
  const num = (cls, lim, title, get, set, step = 1) => {
    const inp = el('input', { class: cls, type: 'number', min: lim[0], max: lim[1], step, title, 'aria-label': title,
      onchange: () => { set(inp.value); cfg = normalizeCfg(cfg); inp.value = String(get()); save(); paint(); } });
    keys(inp);
    return inp;
  };
  const dirInp = num('fs-jam-dir', LIMITS.dir, T('jam.dir_t'), () => cfg.spoof.dir, v => { cfg.spoof.dir = v; });
  const speedInp = num('fs-jam-speed', LIMITS.speed, T('jam.speed_t'), () => cfg.spoof.speed, v => { cfg.spoof.speed = v; }, 0.1);
  const maxInp = num('fs-jam-max', LIMITS.max_m, T('jam.max_t'), () => cfg.spoof.max_m, v => { cfg.spoof.max_m = v; });
  const durInp = num('fs-jam-dur', LIMITS.dur_s, T('jam.dur_t'), () => cfg.dur_s, v => { cfg.dur_s = v; });
  const arrow = el('i', { class: 'fs-jam-arrow', 'aria-hidden': 'true' }, '↑');
  const durNote = el('i');
  const row = (label, title, ...kids) => el('label', { class: 'fs-jam-row', title }, el('span', null, label), el('div', null, kids));
  const spoofRows = [row(T('jam.dir'), T('jam.dir_t'), dirInp, el('i', null, '°'), arrow), row(T('jam.speed'), T('jam.speed_t'), speedInp, el('i', null, 'm/s')),
    row(T('jam.max'), T('jam.max_t'), maxInp, el('i', null, 'm'))];
  // ---- bağlantı karıştırma (§49) ----
  const rcChk = el('input', { type: 'checkbox', class: 'fs-jam-rc', onchange: () => { cfg.rc = rcChk.checked; save(); paint(); } });
  const tlmChk = el('input', { type: 'checkbox', class: 'fs-jam-tlm', onchange: () => { cfg.tlm = tlmChk.checked; save(); paint(); } });
  // ---- karıştırıcı bölgesi (§49) ----
  const home = () => (session?.center?.lat != null && session.center.lon != null ? { lat: Number(session.center.lat), lon: Number(session.center.lon) } : null);
  const vehNow = () => (lastT?.lat != null && lastT.lon != null ? { lat: Number(lastT.lat), lon: Number(lastT.lon), hdg: headingOf(lastT) } : home() ? { ...home(), hdg: 0 } : null);
  const zcText = () => (cfg.zone.lat != null && cfg.zone.lon != null ? `${cfg.zone.lat.toFixed(5)}, ${cfg.zone.lon.toFixed(5)}` : '');
  function placeZone(how) {
    const v = vehNow();
    if (!v) { onEvent(T('jam.zone_nopos'), 'warning'); return false; }
    const c = how === 'here' ? moveM(v, 0, 0) : zoneAhead(v, cfg.zone.r_m);
    cfg = normalizeCfg({ ...cfg, zone: { ...cfg.zone, lat: c.lat, lon: c.lon, on: true } });
    return true;
  }
  const zoneChk = el('input', { type: 'checkbox', class: 'fs-jam-zone', onchange: () => {
    if (zoneChk.checked && cfg.zone.lat == null) placeZone('ahead');   // ilk açılış: aracın önünde (araç hemen etkilenmez; içine uçulur)
    else cfg.zone.on = zoneChk.checked && cfg.zone.lat != null;
    save(); paint();
  } });
  const zrInp = num('fs-jam-zr', LIMITS.r_m, T('jam.zone_r_t'), () => cfg.zone.r_m, v => { cfg.zone.r_m = v; });
  const zcInp = el('input', { class: 'fs-jam-zc', type: 'text', spellcheck: 'false', autocomplete: 'off', placeholder: '39.92500, 32.83700', title: T('jam.zone_c_t'), 'aria-label': T('jam.zone_c_t'),
    onchange: () => {
      const p = parseLatLon(zcInp.value);
      if (!p) { onEvent(T('jam.zone_bad'), 'warning'); zcInp.value = zcText(); return; }
      cfg.zone.lat = p.lat; cfg.zone.lon = p.lon; paint();
    } });
  keys(zcInp);
  const mini = (cls, key, how) => el('button', { class: cls, type: 'button', title: T(`${key}_t`), onclick: e => { e.stopPropagation(); placeZone(how); save(); paint(); } }, T(key));
  const zoneRows = [row(T('jam.zone_r'), T('jam.zone_r_t'), zrInp, el('i', null, 'm')), row(T('jam.zone_c'), T('jam.zone_c_t'), zcInp),
    el('div', { class: 'fs-jam-mini' }, mini('fs-jam-zhere', 'jam.zone_here', 'here'), mini('fs-jam-zahead', 'jam.zone_ahead', 'ahead')),
    el('div', { class: 'fs-jam-sub' }, T('jam.zone_map'))];
  // ---- konum kaybında otopilot tepkisi (yalnız kopter; §49) ----
  const fsSeg = el('div', { class: 'fs-jam-seg fs-jam-fs', role: 'group', 'aria-label': T('jam.fs') },
    FS_MODES.map(v => el('button', { type: 'button', 'data-v': v, title: T(`jam.fs_${v}_t`), onclick: e => { e.stopPropagation(); fsSel = v; fsTouched = true; paint(); } }, T(`jam.fs_${v}`))));
  const fsHint = el('div', { class: 'fs-jam-hint' });
  const fsSec = el('div', { class: 'fs-jam-sec', hidden: st.fs == null }, el('b', null, T('jam.fs')), fsSeg, fsHint);
  const live = el('div', { class: 'fs-jam-live', hidden: true });
  const note = el('div', { class: 'fs-jam-note', hidden: st.sim !== 'fake' }, T('jam.fake_note'));
  const btnTxt = el('span', { class: 'fs-jam-btn-txt' }, T('jam.title'));
  const btnIco = el('span', { class: 'fs-jam-ico', 'aria-hidden': 'true' }); btnIco.innerHTML = JAM_ICON_SVG;
  const btn = el('button', { class: `${btnClass} fs-jam-btn`, type: 'button', title: T('jam.btn_t'), 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    onclick: e => { e.stopPropagation(); setOpen(pop.hidden); } }, btnIco, btnTxt);
  const startBtn = el('button', { class: 'fs-jam-act fs-jam-start', type: 'button', onclick: e => { e.stopPropagation(); send(true); } }, T('jam.start'));
  const stopBtn = el('button', { class: 'fs-jam-act stop fs-jam-stop', type: 'button', hidden: true, onclick: e => { e.stopPropagation(); send(false); } }, T('jam.stop'));
  const pop = el('div', { class: 'fs-jam-pop', role: 'dialog', 'aria-label': T('jam.title'), hidden: true },
    el('h6', null, btnIco.cloneNode(true), el('span', null, T('jam.title')), el('button', { class: 'fs-jam-x', type: 'button', title: T('jam.close'), 'aria-label': T('jam.close'), onclick: e => { e.stopPropagation(); setOpen(false); } }, '×')),
    el('div', { class: 'fs-jam-body' },
      note,
      el('div', { class: 'fs-jam-sec' }, el('b', null, T('jam.gps')), seg, hint),
      el('div', { class: 'fs-jam-sec' }, el('label', { class: 'fs-jam-sw', title: T('jam.spoof_t') }, spoofChk, T('jam.spoof')), spoofRows),
      el('div', { class: 'fs-jam-sec' }, el('b', null, T('jam.link')),
        el('label', { class: 'fs-jam-sw', title: T('jam.rc_t') }, rcChk, T('jam.rc')), el('label', { class: 'fs-jam-sw', title: T('jam.tlm_t') }, tlmChk, T('jam.tlm')),
        el('div', { class: 'fs-jam-sub' }, T('jam.link_h'))),
      el('div', { class: 'fs-jam-sec' }, el('label', { class: 'fs-jam-sw', title: T('jam.zone_t') }, zoneChk, T('jam.zone')), zoneRows),
      fsSec,
      el('div', { class: 'fs-jam-sec' }, row(T('jam.dur'), T('jam.dur_t'), durInp, el('i', null, T('jam.sec')), durNote), live)),
    el('div', { class: 'fs-jam-acts' }, startBtn, stopBtn));
  const root = el('div', { class: 'pill-group fs-jam', title: T('jam.title_t'), 'data-state': 'off' }, btn, pop);
  pop.addEventListener('click', e => e.stopPropagation());
  // Panel taşmasın (dar ekran): açılınca görüntü alanına sığacak biçimde yatay kaydır; ok düğmenin ortasını gösterir
  function place() {
    pop.style.left = '0px';
    if (typeof window === 'undefined' || !pop.getBoundingClientRect) return;
    const r = pop.getBoundingClientRect(), W = window.innerWidth || document.documentElement.clientWidth || 0, b = btn.getBoundingClientRect();
    let dx = 0;
    if (r.right > W - 8) dx = W - 8 - r.right;
    if (r.left + dx < 8) dx = 8 - r.left;
    pop.style.left = `${Math.round(dx)}px`;
    pop.style.setProperty('--fs-jam-arrow', `${Math.round(Math.min(Math.max(b.left + b.width / 2 - (r.left + dx) - 5, 12), r.width - 22))}px`);
  }
  function setOpen(v) {
    pop.hidden = !v; btn.setAttribute('aria-expanded', v ? 'true' : 'false');
    paint();
    if (v) place();
  }
  const banner = el('div', { class: 'fs-jam-banner', role: 'status', hidden: true }, el('span'), el('small'));
  // ---- küçük harita (§49): kuzey yukarı, araç ortada ----
  const mapScaleEl = el('span'), mapCv = el('canvas'), mapLg = el('footer');
  const mapEl = el('div', { class: 'fs-jam-map', hidden: true, title: T('jam.map_t') }, el('header', null, el('b', null, T('jam.map')), mapScaleEl), mapCv, mapLg);
  mapEl.addEventListener('pointerdown', e => {   // panel açıkken: tıklanan nokta bölge merkezi olur
    if (!mapEl.classList.contains('fs-jam-pick') || !mapGeo) return;
    e.stopPropagation(); e.preventDefault();
    const r = mapCv.getBoundingClientRect(), x = (e.clientX - r.left) * mapGeo.size / (r.width || 1), y = (e.clientY - r.top) * mapGeo.size / (r.height || 1);
    if (x < 0 || y < 0 || x > mapGeo.size || y > mapGeo.size) return;
    const p = mapUnproject(mapGeo.c, mapGeo.half, mapGeo.size, x, y);
    cfg = normalizeCfg({ ...cfg, zone: { ...cfg.zone, lat: p.lat, lon: p.lon, on: true } });
    paint();
  });
  const tlmBadge = el('div', { class: 'fs-jam-tlmb', role: 'status', hidden: true }, T('jam.hud_lost'));   // sağ veri panelinin başına (flightsim.js)
  stage?.append(banner, mapEl);
  function save() {   // bölge merkezi oturuma özgü: saklanmaz (yarıçap saklanır)
    const n = normalizeCfg(cfg);
    try { storage?.setItem(PREF, JSON.stringify({ ...n, zone: { on: false, lat: null, lon: null, r_m: n.zone.r_m } })); } catch { /* depolama kapalı */ }
  }
  async function send(on) {
    if (busy) return;
    const zc = parseLatLon(zcInp.value);
    if (on && cfg.zone.on && !zc) { onEvent(T('jam.zone_bad'), 'warning'); return; }
    cfg = normalizeCfg({ ...cfg, spoof: { ...cfg.spoof, dir: dirInp.value, speed: speedInp.value, max_m: maxInp.value }, dur_s: durInp.value,
      zone: { ...cfg.zone, r_m: zrInp.value, ...(cfg.zone.on && zc ? zc : {}) } });
    save();
    const body = on ? cmdBody(cfg, st.fs != null ? fsSel : undefined) : { off: true };
    if (!body) { onEvent(T('jam.nothing'), 'warning'); paint(); return; }
    busy = true; paint();
    try {
      const r = await cmd('jam', body);
      const j = r?.jam || r?.result?.jam;
      if (j) st = { ...st, ...j };
      if (on) setOpen(false);   // başladı: panel kapanır, durum sahne üstü bandında
    } catch (e) { onEvent(T('jam.err', { e: e?.message || String(e) }), 'error'); }
    busy = false; paint();
  }
  // ---- küçük harita çizimi ----
  function track(t) {   // izler: gerçek konum + otopilotun sandığı konum (ölçekle seyrelir)
    const gap = Math.max(3, (mapHalf || 100) / 40);
    const push = (arr, p) => { const l = arr[arr.length - 1]; if (!l || distM(l, p) >= gap) { arr.push(p); if (arr.length > TRAIL_MAX) arr.shift(); } };
    if (t?.lat != null && t.lon != null) push(realTrail, { lat: Number(t.lat), lon: Number(t.lon) });
    if (t?.nav_lat != null && t.nav_lon != null) push(navTrail, { lat: Number(t.nav_lat), lon: Number(t.nav_lon) });
  }
  function drawMap(m) {
    const size = mapCv.clientWidth || 166, dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1), px = Math.round(size * dpr);
    if (mapCv.width !== px) { mapCv.width = px; mapCv.height = px; }
    const g = mapCv.getContext?.('2d'); if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, size, size);
    const c = m.veh || m.home;
    if (!c) { mapGeo = null; mapScaleEl.textContent = ''; return; }
    const up = mapScale(m), down = mapScale(m, 1.2);
    mapHalf = !mapHalf || up > mapHalf ? up : Math.min(mapHalf, down);
    const half = mapHalf, mid = size / 2, k = mid / half, P = p => mapProject(c, half, size, p), TAU = Math.PI * 2;
    mapGeo = { c, half, size };
    mapScaleEl.textContent = `±${fmtDist(half)}`;
    g.lineWidth = 1; g.strokeStyle = 'rgba(255,255,255,.12)';
    g.beginPath(); g.moveTo(mid, 0); g.lineTo(mid, size); g.moveTo(0, mid); g.lineTo(size, mid); g.stroke();
    g.beginPath(); g.arc(mid, mid, mid / 2, 0, TAU); g.stroke();
    g.fillStyle = 'rgba(255,255,255,.45)'; g.font = '600 9px system-ui, sans-serif'; g.textAlign = 'left'; g.textBaseline = 'bottom';
    g.fillText(fmtDist(half / 2), mid + 3, mid / 2 - 1);
    if (m.zone) {
      const z = P(m.zone), col = ZONE_CSS[m.zone.state] || ZONE_CSS.out, rr = Math.max(2, m.zone.r_m * k);
      g.beginPath(); g.arc(z.x, z.y, rr, 0, TAU); g.fillStyle = `${col}2b`; g.fill();
      g.setLineDash(m.zone.state === 'draft' ? [5, 4] : []); g.strokeStyle = col; g.lineWidth = 1.6; g.stroke(); g.setLineDash([]);
      g.beginPath(); g.moveTo(z.x - 4, z.y); g.lineTo(z.x + 4, z.y); g.moveTo(z.x, z.y - 4); g.lineTo(z.x, z.y + 4); g.lineWidth = 1.4; g.stroke();
    }
    if (m.home && m.veh) {   // ev (kalkış noktası)
      const hp = P(m.home);
      g.fillStyle = '#22c55e'; g.strokeStyle = '#0b1220'; g.lineWidth = 1; g.beginPath(); g.rect(hp.x - 3, hp.y - 3, 6, 6); g.fill(); g.stroke();
    }
    const trail = (arr, col, dash) => {
      if (arr.length < 2) return;
      g.beginPath(); arr.forEach((p, i) => { const q = P(p); if (i) g.lineTo(q.x, q.y); else g.moveTo(q.x, q.y); });
      g.setLineDash(dash); g.strokeStyle = col; g.lineWidth = 1.2; g.stroke(); g.setLineDash([]);
    };
    trail(realTrail, 'rgba(255,255,255,.55)', []);
    trail(navTrail, 'rgba(232,121,249,.7)', [3, 3]);
    if (m.ghost) {
      const q = P(m.ghost);
      g.strokeStyle = GHOST_CSS; g.lineWidth = 1.2; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(mid, mid); g.lineTo(q.x, q.y); g.stroke(); g.setLineDash([]);
      g.lineWidth = 2; g.beginPath(); g.arc(q.x, q.y, 5.5, 0, TAU); g.stroke();
      g.lineWidth = 1.4; g.beginPath(); g.moveTo(q.x - 9, q.y); g.lineTo(q.x - 3, q.y); g.moveTo(q.x + 3, q.y); g.lineTo(q.x + 9, q.y); g.moveTo(q.x, q.y - 9); g.lineTo(q.x, q.y - 3); g.moveTo(q.x, q.y + 3); g.lineTo(q.x, q.y + 9); g.stroke();
    }
    if (m.veh) {   // araç: baş açısına dönük üçgen (merkezde)
      g.save(); g.translate(mid, mid); g.rotate((m.veh.hdg || 0) * Math.PI / 180);
      g.beginPath(); g.moveTo(0, -8); g.lineTo(5.5, 6); g.lineTo(0, 3); g.lineTo(-5.5, 6); g.closePath();
      g.fillStyle = '#fff'; g.strokeStyle = '#0b1220'; g.lineWidth = 1.2; g.fill(); g.stroke(); g.restore();
    }
    g.fillStyle = 'rgba(255,255,255,.8)'; g.beginPath(); g.moveTo(size - 9, 4); g.lineTo(size - 5, 14); g.lineTo(size - 9, 11.5); g.lineTo(size - 13, 14); g.closePath(); g.fill();   // kuzey oku
  }
  function paintScene() {
    paintAt = nowMs();
    const draft = !pop.hidden && cfg.zone.on;
    const m = sceneModel(st, cfg, lastT, { panelOpen: !pop.hidden, home: home() });
    const show = draft || ((st.on || st.real) && (st.sim !== 'fake' || !!m.zone));
    mapEl.hidden = !show;
    mapEl.classList.toggle('fs-jam-pick', draft);
    if (show) {
      drawMap(m);
      const lg = [];
      if (m.zone?.state === 'draft') lg.push(el('div', { class: 'draft' }, el('i'), T('jam.map_click')));
      else if (m.zone) {
        const d = st.zone?.dist_m != null ? Math.max(0, Number(st.zone.dist_m) - m.zone.r_m) : null;
        lg.push(el('div', { class: m.zone.state }, el('i'), m.zone.state === 'in' ? T('jam.lg_in') : d != null ? T('jam.b_zone_d', { m: f0(d) }) : T('jam.zone')));
      }
      if (m.ghost) lg.push(el('div', { class: 'ghost' }, el('i'), `${T('jam.lg_ghost')} · ${f0(m.ghost.err)} m`));
      mapLg.replaceChildren(...lg);
    } else mapHalf = 0;
    try { layer?.set(m, { zone: m.zone ? T('jam.zone_l', { r: f0(m.zone.r_m) }) : '', ghost: m.ghost ? T('jam.ghost_l', { m: f0(m.ghost.err) }) : '' }); } catch { /* 3B katman isteğe bağlı */ }
  }
  function paint() {
    root.dataset.state = st.on ? (st.zone?.on && st.active === false ? 'wait' : 'on') : st.real ? 'recover' : 'off';
    const act = typeof document !== 'undefined' ? document.activeElement : null;   // yazılan değer telemetri boyamasıyla ezilmesin
    for (const b of seg.children) b.setAttribute('aria-pressed', b.dataset.v === cfg.gps ? 'true' : 'false');
    hint.textContent = T(`jam.${cfg.gps}_t`);
    spoofChk.checked = !!cfg.spoof.on;
    for (const r of spoofRows) r.hidden = !cfg.spoof.on;
    if (act !== dirInp) dirInp.value = String(cfg.spoof.dir);
    if (act !== speedInp) speedInp.value = String(cfg.spoof.speed);
    if (act !== maxInp) maxInp.value = String(cfg.spoof.max_m);
    if (act !== durInp) durInp.value = String(cfg.dur_s);
    arrow.style.transform = `rotate(${cfg.spoof.dir}deg)`;
    durNote.textContent = cfg.dur_s ? '' : T('jam.forever');
    rcChk.checked = !!cfg.rc; tlmChk.checked = !!cfg.tlm;
    zoneChk.checked = !!cfg.zone.on;
    for (const r of zoneRows) r.hidden = !cfg.zone.on;
    if (act !== zrInp) zrInp.value = String(cfg.zone.r_m);
    if (act !== zcInp) zcInp.value = zcText();
    fsSec.hidden = st.fs == null;
    for (const b of fsSeg.children) b.setAttribute('aria-pressed', b.dataset.v === fsSel ? 'true' : 'false');
    fsHint.textContent = T(`jam.fs_${fsSel}_t`);
    btnTxt.textContent = T(jamBtnKey(st));
    btn.classList.toggle('on', !!st.on);
    btn.title = st.on ? `${T('jam.active')}: ${cfgText(st, T)}` : T('jam.btn_t');
    startBtn.textContent = T(st.on ? 'jam.apply' : 'jam.start');
    startBtn.disabled = busy; stopBtn.disabled = busy; stopBtn.hidden = !st.on;
    note.hidden = st.sim !== 'fake';
    const b = bannerText(st, T);
    banner.hidden = !b;
    banner.classList.toggle('recover', !!b?.recover); banner.classList.toggle('wait', !!b?.wait);
    if (b) { banner.firstChild.textContent = b.main; banner.lastChild.textContent = b.sub; }
    live.hidden = !b;
    if (b) live.textContent = b.sub || b.main;
    const lost = !!(st.on && st.tlm && st.active !== false);   // telemetri kesik: yer istasyonu göstergeleri son değerde (flightsim.js tlmLost)
    tlmBadge.hidden = !lost;
    stage?.classList?.toggle('fs-tlm-lost', lost);
    paintScene();
  }
  // Panel dışına tıklama / Esc kapatır (Esc yakalama evresinde: oturumdan çıkış kısayoluna gitmez). Küçük harita panelin parçası sayılır (merkez seçimi).
  const onDoc = e => { if (!pop.hidden && !root.contains(e.target) && !mapEl.contains(e.target)) setOpen(false); };
  const onEsc = e => { if (e.key === 'Escape' && !pop.hidden) { setOpen(false); e.preventDefault(); e.stopPropagation(); } };
  if (typeof document !== 'undefined') document.addEventListener('pointerdown', onDoc, true);
  if (typeof window !== 'undefined') window.addEventListener('keydown', onEsc, true);
  paint();
  return {
    el: root, banner, map: mapEl, tlmBadge,
    get state() { return { ...st }; }, get cfg() { return normalizeCfg(cfg); },
    update(t) {
      lastT = t;
      if (!st.on && !st.real) {   // boştayken telemetriyle boyama yok (panelde taslak bölge varsa yalnız harita / 3B)
        if (realTrail.length || navTrail.length) { realTrail.length = 0; navTrail.length = 0; }
        if (!pop.hidden && cfg.zone.on && paintDue()) paintScene();
        return;
      }
      track(t);
      st = mergeTele(st, t);
      if (paintDue()) paint();
    },
    /** WS `{t:'jam', reason, …durum}` çerçevesi (komut / süre doldu / sıfırla / EKF toparlandı / bölgeye giriş-çıkış / gaz-orta). */
    onFrame(m) {
      const { t: _t, ts: _ts, reason, ...d } = m || {};
      st = { ...st, ...d };
      if (st.on && reason === 'cmd') cfg = normalizeCfg(st);   // başka izleyici / sekme ayarı değiştirdi: panel aynı ayarı göstersin
      if (FS_MODES.includes(d.fs) && (!fsTouched || reason === 'cmd' || reason === 'init')) { fsSel = d.fs; fsTouched = false; }
      if (reason === 'settled') onEvent(T('jam.ev_settled'), 'info');   // sunucu bu geçişte olay yollamaz
      paint();
      return st;
    },
    /** 3B dünya kuruldu / yeniden kuruldu: bölge + hayalet katmanı o sahneye çizilir. */
    attachSim(sim) {
      try { layer?.dispose(); } catch { /* sahne zaten kapanmış */ }
      layer = null;
      try { layer = sim ? createJamLayer(sim) : null; } catch { layer = null; }
      paintScene();
    },
    open: () => setOpen(true), close: () => setOpen(false), get isOpen() { return !pop.hidden; },
    dispose() {
      document.removeEventListener('pointerdown', onDoc, true); window.removeEventListener('keydown', onEsc, true);
      try { layer?.dispose(); } catch { /* sahne zaten kapanmış */ }
      layer = null; stage?.classList?.remove('fs-tlm-lost');
      root.remove(); banner.remove(); mapEl.remove(); tlmBadge.remove();
    },
  };
}
