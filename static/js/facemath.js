// Yüz ile giriş — SAF yardımcılar (DOM yok; Node testinde de çalışır: tests/test_face.mjs). Sunucudaki
// app/facelogin.py ile AYNI eşleme: baş pozu (yaw, pitch ∈ [-1,1], facecore._head_pose) → merkez / 8 yön yuvası.
// Ön kamera aynalı gösterildiği için ham yaw ters çevrilir (ham yaw<0 = burun görüntüde sola = kullanıcı KENDİ SAĞINA bakıyor).
export const SEGMENTS = ['right', 'up_right', 'up', 'up_left', 'left', 'down_left', 'down', 'down_right'];
export const SLOTS = ['center', ...SEGMENTS];
export const R_CENTER = 0.14;   // |poz| < R_CENTER → merkez
export const R_SEG = 0.20;      // |poz| ≥ R_SEG → yön; arası belirsiz (null)
export const POSE_MIN = 0.18;   // canlılık adımında yön bileşeni en az bu kadar

// Ekran koordinatına çevir: sx>0 sağ, sy>0 yukarı
export function screenPose(yaw, pitch, mirror = true) {
  return { sx: mirror ? -yaw : yaw, sy: -pitch };
}

export function segmentOf(yaw, pitch, mirror = true) {
  const { sx, sy } = screenPose(yaw, pitch, mirror);
  const r = Math.hypot(sx, sy);
  if (r < R_CENTER) return 'center';
  if (r < R_SEG) return null;
  const ang = ((Math.atan2(sy, sx) * 180) / Math.PI + 360) % 360;
  return SEGMENTS[Math.floor(((ang + 22.5) % 360) / 45)];
}

// Halka açısı (derece, SVG: 0° = sağ, saat yönünün tersi yukarı) — segment i'nin merkezi
export const segmentAngle = i => i * 45;

export function poseMatches(yaw, pitch, want, mirror = true) {
  const { sx, sy } = screenPose(yaw, pitch, mirror);
  return { right: sx >= POSE_MIN, left: sx <= -POSE_MIN, up: sy >= POSE_MIN, down: sy <= -POSE_MIN }[want] || false;
}

export function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return na && nb ? dot / Math.sqrt(na * nb) : 0;
}

export function normalize(v) {
  const n = Math.sqrt(v.reduce((s, x) => s + x * x, 0)) || 1;
  return v.map(x => x / n);
}

// Dolu yuvalardan ilerleme [0,1]: merkez 1 pay, her yön 1 pay
export function ringProgress(slots) {
  const set = new Set(slots || []);
  return SLOTS.filter(s => set.has(s)).length / SLOTS.length;
}

// Eksik yuvalar arasından kullanıcıya önerilecek sıradaki yön: dolulardan saat yönünde en yakın boş (akıcı daire çizimi)
export function nextSegment(slots) {
  const set = new Set(slots || []);
  if (!set.has('center')) return 'center';
  const missing = SEGMENTS.filter(s => !set.has(s));
  if (!missing.length) return null;
  const lastIdx = Math.max(-1, ...SEGMENTS.map((s, i) => (set.has(s) ? i : -1)));
  for (let k = 1; k <= SEGMENTS.length; k++) {
    const s = SEGMENTS[(lastIdx + k) % SEGMENTS.length];
    if (!set.has(s)) return s;
  }
  return missing[0];
}

// Yönlendirme metni anahtarı (i18n: t() ile çevrilir)
export const DIRECTION_TEXT = {
  center: 'Yüzünüzü dairenin içine alın',
  right: 'Başınızı yavaşça sağa çevirin',
  up_right: 'Başınızı sağ üste doğru çevirin',
  up: 'Başınızı hafifçe yukarı kaldırın',
  up_left: 'Başınızı sol üste doğru çevirin',
  left: 'Başınızı yavaşça sola çevirin',
  down_left: 'Başınızı sol alta doğru çevirin',
  down: 'Başınızı hafifçe aşağı eğin',
  down_right: 'Başınızı sağ alta doğru çevirin',
};

// Yüz kutusunun dairede konumu: kutu merkezinin kare merkezine uzaklığı (0 = ortada) ve göreli boyut
export function framing(box, w, h) {
  if (!box || !w || !h) return null;
  const [x, y, bw, bh] = box;
  const cx = (x + bw / 2) / w - 0.5, cy = (y + bh / 2) / h - 0.5;
  return { off: Math.hypot(cx, cy), size: Math.max(bw / w, bh / h) };
}

// Kullanıcıya konum ipucu: null = iyi
export function framingHint(fr) {
  if (!fr) return null;
  if (fr.size < 0.28) return 'Biraz yaklaşın';
  if (fr.size > 0.85) return 'Biraz uzaklaşın';
  if (fr.off > 0.22) return 'Yüzünüzü ortalayın';
  return null;
}
