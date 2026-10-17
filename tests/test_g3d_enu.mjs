// Google 3B kipi — ECEF → yerel ENU dönüşümü (flightsim_g3d.js `enuMatrix` ile aynı yöntem): bilinen enlem/boylamdaki ECEF nokta
// tiles grubunun ters ENU matrisiyle yerel (0,0,0)'a; 100 m kuzeydeki nokta (≈0, ≈100, ≈0); 100 m yukarıdaki nokta (0, 0, 100).
// Çalıştırma: node tests/test_g3d_enu.mjs   (vendor bundle'ı tarayıcısız node'da da yüklenir)
import { Matrix4, Vector3 } from '../static/vendor/three/three.module.min.js';
import { WGS84_ELLIPSOID } from '../static/vendor/three/3DTilesRenderer.js';
import { enuMatrix } from '../static/js/modules/flightsim_g3d.js';

const DEG = Math.PI / 180;
const lat = 39.925, lon = 32.837, h = 900;   // Ankara
const yakin = (a, b, eps, ad) => { if (Math.abs(a - b) > eps) throw new Error(`${ad}: ${a} ≠ ${b} (±${eps})`); };

const M = enuMatrix(WGS84_ELLIPSOID, Matrix4, lat, lon, h);   // ECEF → ENU (X doğu, Y kuzey, Z yukarı), merkez 0
const ecef = p => { const v = new Vector3(); WGS84_ELLIPSOID.getCartographicToPosition(p.lat * DEG, p.lon * DEG, p.h, v); return v; };

// 1) merkez → (0, 0, 0)
const c = ecef({ lat, lon, h }).applyMatrix4(M);
yakin(c.x, 0, 1e-6, 'merkez x'); yakin(c.y, 0, 1e-6, 'merkez y'); yakin(c.z, 0, 1e-6, 'merkez z');
// ECEF büyüklüğü makul (Dünya yarıçapı ~6.37e6 m)
yakin(ecef({ lat, lon, h }).length(), 6370e3, 20e3, 'ECEF yarıçap');

// 2) 100 m kuzey (sahne toLocal: 1° enlem ≈ 110574 m; WGS84 meridyen yarıçapı Ankara'da ≈ 111,0 km → %0,4 fark) → y ≈ +100, x ≈ 0, z ≈ 0
const n = ecef({ lat: lat + 100 / 110574, lon, h }).applyMatrix4(M);
yakin(n.y, 100, 0.6, 'kuzey y'); yakin(n.x, 0, 0.01, 'kuzey x'); yakin(n.z, 0, 0.01, 'kuzey z');

// 3) 100 m doğu (1° boylam ≈ 111320·cos(lat) m) → x ≈ +100
const e = ecef({ lat, lon: lon + 100 / (111320 * Math.cos(lat * DEG)), h }).applyMatrix4(M);
yakin(e.x, 100, 0.6, 'doğu x'); yakin(e.y, 0, 0.01, 'doğu y');

// 4) 100 m yukarı → z = 100
const u = ecef({ lat, lon, h: h + 100 }).applyMatrix4(M);
yakin(u.z, 100, 1e-6, 'yukarı z'); yakin(u.x, 0, 1e-6, 'yukarı x'); yakin(u.y, 0, 1e-6, 'yukarı y');

// 5) Ters yön: ENU (0,0,0) → ECEF, matrisin tersi merkez noktasını geri verir
const back = new Vector3(0, 0, 0).applyMatrix4(M.clone().invert());
yakin(back.distanceTo(ecef({ lat, lon, h })), 0, 1e-6, 'ters dönüşüm');

console.log('g3d ENU testi geçti: merkez→(0,0,0), kuzey→+Y, doğu→+X, yukarı→+Z');
