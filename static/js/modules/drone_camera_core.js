// Dron Kameraları — SAF yardımcılar (DOM yok; tests/test_drone_camera.mjs). Görüntü köprüsü protokolü v1.3 (docs/dron-kopru-protokolu.md):
//  • İzleyici WebSocket'inde ikili çerçeve = [tür:1][yük]: 1 init (ftyp+moov) · 2 anahtar kareyle başlayan parça · 3 ara parça (moof+mdat).
//  • Canlı uca yakın oynatma: tampon sonu ile oynatma konumu arası (gecikme) hedefin üstündeyse hız 1,1×, çok gerideyse ileri atlanır.
//  • Yüzen kamera pencereleri (Canlı Uçuş): yerleşim flightsim_dock.js'nin oranlı kaydıyla ({fx, fy, fw, sx, sy}) kamera başına localStorage
//    'dr.cam.win' altında saklanır — Uçuş Simülatörü radar/EO pencereleriyle aynı kurallar (yapışma, kırpma, oran korunarak boyut).
//  • Yeşil HUD (yalnız gösterge): yön şeridi işaretleri, ufuk/eğim merdiveni geometrisi, telemetri alanlarının metinleri.
import { boundsOf, clampRect, fromFrac, normWin, sizeFor, toFrac, WIN_MARGIN } from './flightsim_dock.js';

export const T_INIT = 1, T_KEY = 2, T_DELTA = 3;
export const WIN_KEY = 'dr.cam.win';        // {<kamera id>: {fx, fy, fw, sx, sy}}
export const OPEN_KEY = 'dr.cam.open';      // {<görev id>: [kamera id…]} — Canlı Uçuş'ta açık pencereler
export const HUD_KEY = 'dr.cam.hud';        // HUD açık/kapalı (varsayılan açık)
export const HDR = 26;                      // pencere başlık yüksekliği (px)
export const ASPECT = 16 / 9;
export const STATUS_BADGE = { canli: 'green', hazir: 'blue', goruntu_yok: 'yellow', kopru_cevrimdisi: 'gray', kopru_yok: 'gray', pasif: 'gray' };
export const FPS_TEXT = fps => (Number(fps) ? `${Number(fps)} FPS` : 'Kaynak FPS');

/** İkili çerçeve → {type, data(Uint8Array)} (geçersizse null). */
export function splitFrame(buf) {
  const u = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  if (u.length < 2 || ![T_INIT, T_KEY, T_DELTA].includes(u[0])) return null;
  return { type: u[0], data: u.subarray(1) };
}

/** Canlı uç politikası: lag = tampon sonu − oynatma konumu (sn). → {seek: hedef konum | null, rate}. */
export function liveEdge(bufEnd, cur, { target = 0.5, max = 2.5 } = {}) {
  if (!Number.isFinite(bufEnd) || !Number.isFinite(cur)) return { seek: null, rate: 1, lag: null };
  const lag = Math.max(0, bufEnd - cur);
  if (lag > max) return { seek: Math.max(0, bufEnd - target), rate: 1, lag };
  if (lag > target * 2) return { seek: null, rate: 1.1, lag };
  return { seek: null, rate: 1, lag };
}

/** Gecikme metni: tampon gecikmesi + son parçanın yaşı (sunucunun bildirdiği). */
export function latencyText(lag, age, tr = (s, p) => s.replace(/\{(\w+)\}/g, (m, k) => p[k])) {
  const parts = [];
  if (Number.isFinite(lag)) parts.push(tr('{s} sn', { s: lag.toFixed(1) }));
  if (Number.isFinite(age) && age > 2) parts.push(tr('son parça {s} sn önce', { s: age.toFixed(0) }));
  return parts.join(' · ') || '—';
}

/** Tampon temizliği: oynatma konumunun keep sn gerisinden eski aralık silinsin mi → [başlangıç, bitiş] | null. */
export function trimRange(bufStart, cur, keep = 10) {
  return Number.isFinite(bufStart) && Number.isFinite(cur) && cur - bufStart > keep * 2 ? [bufStart, cur - keep] : null;
}

// ---------------- yüzen pencere yerleşimi (kamera başına) ----------------
const parse = s => { try { const v = JSON.parse(s || 'null'); return v && typeof v === 'object' ? v : null; } catch { return null; } };
export function loadWins(storage) { const v = parse(storage?.getItem?.(WIN_KEY)) || {}; const out = {}; for (const [k, f] of Object.entries(v)) { const n = normWin(f); if (n) out[k] = n; } return out; }
export function saveWin(storage, camId, rect, W, H) {
  const all = loadWins(storage);
  if (rect) all[String(camId)] = toFrac(rect, W, H); else delete all[String(camId)];
  try { storage?.setItem?.(WIN_KEY, JSON.stringify(all)); } catch { /* kota */ }
  return all;
}
/** Kayıtlı yerleşim varsa onu (ekran boyutuna oranlı), yoksa sağ üstten başlayıp aşağı/sola basamaklı varsayılan dikdörtgen. */
export function placeWin(saved, index, W, H, { aspect = ASPECT, hdr = HDR, bounds = null, width = 360 } = {}) {
  const B = bounds || boundsOf(W, H);
  const r = saved ? fromFrac(saved, W, H, aspect, { hdr, bounds: B }) : null;
  if (r) return r;
  const s = sizeFor(Math.min(width, Math.max(200, W * 0.3)), aspect, { W, H, hdr, bounds: B });
  const perCol = Math.max(1, Math.floor((B.bottom - B.top + 10) / (s.h + 10)));   // sağ kenardan sola doğru sütunlar
  const col = Math.floor(index / perCol), row = index % perCol;
  const x = B.right - s.w - col * (s.w + 10), y = B.top + row * (s.h + 10);
  return { ...clampRect({ x, y, w: s.w, h: s.h }, B), sx: null, sy: null };
}
/** Açık pencereler listesi (görev başına). */
export function loadOpen(storage, taskId) { const v = parse(storage?.getItem?.(OPEN_KEY)) || {}; const l = v[String(taskId)]; return Array.isArray(l) ? l.map(Number).filter(Number.isFinite) : null; }
export function saveOpen(storage, taskId, ids) {
  const v = parse(storage?.getItem?.(OPEN_KEY)) || {};
  v[String(taskId)] = [...new Set(ids.map(Number))];
  const keys = Object.keys(v); if (keys.length > 30) delete v[keys[0]];   // eski görevler birikmesin
  try { storage?.setItem?.(OPEN_KEY, JSON.stringify(v)); } catch { /* */ }
  return v[String(taskId)];
}
export { WIN_MARGIN };

// ---------------- HUD ----------------
const wrap = d => ((d % 360) + 360) % 360;
const CARD = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' };   // havacılık standardı (dilden bağımsız)
/** Yön şeridi işaretleri: hdg merkezde, ±span/2 derece; x ∈ [-1, 1]. major her 10°, etiket her 30° (ana yönler harf). */
export function headingTicks(hdg, span = 90, step = 5) {
  if (!Number.isFinite(hdg)) return [];
  const out = [], half = span / 2;
  const first = Math.ceil((hdg - half) / step) * step;
  for (let d = first; d <= hdg + half + 1e-9; d += step) {
    const deg = wrap(d), major = deg % 10 === 0;
    out.push({ x: (d - hdg) / half, deg, major, label: deg % 30 === 0 ? (CARD[deg] || String(deg / 10).padStart(2, '0')) : null });
  }
  return out;
}
/** Ufuk/eğim merdiveni: roll/pitch (derece) → satırlar {p (derece), y (px, merkezden aşağı +), label}; pxPerDeg ölçek. */
export function pitchLadder(pitch, { pxPerDeg = 6, range = 25, step = 5 } = {}) {
  if (!Number.isFinite(pitch)) return [];
  const out = [];
  const lo = Math.ceil((pitch - range) / step) * step;
  for (let p = lo; p <= pitch + range; p += step) out.push({ p, y: (pitch - p) * pxPerDeg, label: p === 0 ? null : String(Math.abs(p)), horizon: p === 0 });
  return out;
}
const f = (v, d = 0) => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(d));
export function fmtFlight(sec) {
  if (!Number.isFinite(Number(sec)) || sec <= 0) return '00:00';
  const s = Math.floor(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return `${h ? `${h}:` : ''}${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
export function fmtCoord(lat, lon) {
  if (!Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return '—';
  const one = (v, p, n) => `${Math.abs(v).toFixed(6)}°${v >= 0 ? p : n}`;
  return `${one(Number(lat), 'N', 'S')} ${one(Number(lon), 'E', 'W')}`;
}
const GPS_FIX = { 0: 'GPS YOK', 1: 'FIX YOK', 2: '2D', 3: '3D', 4: 'DGPS', 5: 'RTK-F', 6: 'RTK' };
/** Telemetri (drone_hub DroneState.d) → HUD metinleri. tr: çevirmen (HEPGO t; yoksa Türkçe). */
export function hudFields(st, tr = (s, p) => (p ? s.replace(/\{(\w+)\}/g, (m, k) => p[k]) : s)) {
  const s = st || {};
  const vz = s.climb != null ? s.climb : (s.vz != null ? -s.vz : null);
  return {
    hdg: Number.isFinite(Number(s.hdg)) ? Number(s.hdg) : (Number.isFinite(Number(s.yaw)) ? Number(s.yaw) : null),
    alt: `${f(s.alt_rel, 1)} m`, altMsl: s.alt != null ? `MSL ${f(s.alt, 0)}` : '',
    gs: `${f(s.groundspeed, 1)} m/s`, vs: `${vz != null && vz > 0 ? '+' : ''}${f(vz, 1)} m/s`,
    batt: s.batt_pct != null ? `${f(s.batt_pct)}%${s.volt != null ? ` ${f(s.volt, 1)}V` : ''}` : (s.volt != null ? `${f(s.volt, 1)}V` : '—'),
    battLow: s.batt_pct != null && s.batt_pct < 25,
    gps: `${GPS_FIX[s.fix] ? tr(GPS_FIX[s.fix]) : (s.fix != null ? String(s.fix) : '—')} ${s.sats != null ? tr('{n} UYDU', { n: s.sats }) : ''}`.trim(), gpsBad: !(s.fix >= 3),
    mode: s.mode || '—', armed: !!s.armed, pos: fmtCoord(s.lat, s.lon), time: fmtFlight(s.flight_s),
    roll: Number.isFinite(Number(s.roll)) ? Number(s.roll) : null, pitch: Number.isFinite(Number(s.pitch)) ? Number(s.pitch) : null,
  };
}
