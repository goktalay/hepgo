// Bekleme ekranı (ekran koruyucu): Ayarlar → Bekleme ekranı. Belirlenen süre boyunca dokunma / fare / klavye yoksa tam ekran
// animasyon, saat ve tarih gösterilir; herhangi bir dokunuşta kapanır (o dokunuş alttaki sayfaya geçmez).
import { api, fileUrl } from './api.js';
import { createGlobe } from './globe.js';
import { captureShards, createGravityScene } from './screensaver-gravity.js';

export const ANIMATIONS = [
  ['gravity', 'Yıkım (interaktif)', 'Ekrandaki öğeler düşer; telefonda sallayın, bilgisayarda çöp adam fırlatır'],
  ['globe', 'Dünya', 'Yavaşça dönen çizgisel dünya'],
  ['matrix', 'Soft Matrix', 'Yumuşak renklerle akan karakterler'],
  ['wave', 'Soft Ses Dalgası', 'Üst üste dalgalanan ses dalgaları'],
  ['aurora', 'Kuzey Işıkları', 'Süzülen renk perdeleri'],
  ['network', 'Parçacık Ağı', 'Birbirine bağlanan noktalar'],
  ['stars', 'Yıldız Yolculuğu', 'Uzayda ileri doğru yolculuk'],
  ['radar', 'Radar', 'Dönen tarama ve beliren hedefler'],
  ['bubbles', 'Lav Lambası', 'Yavaşça yükselen yumuşak kabarcıklar'],
  ['random', 'Rastgele', 'Her açılışta farklı bir animasyon'],
];

let cfg = { on: false, after: 300, anim: 'globe', lock: true };
let idleTimer = null, overlay = null, user = null;
const LOCK_KEY = 'caymaz.locked';

export function setScreensaver(s, u) {
  cfg = { on: false, after: 300, anim: 'globe', lock: true, ...(s || {}) };
  user = u || null;
  if (!user) { try { sessionStorage.removeItem(LOCK_KEY); } catch { /* yok say */ } }
  reset();
  armMotionPrimer();
  // Kilitliyken sayfa yenilendiyse kilit ekranı yeniden açılır
  let locked = false;
  try { locked = sessionStorage.getItem(LOCK_KEY) === '1'; } catch { /* yok say */ }
  if (user && locked && !overlay) showScreensaver(cfg.anim, { unlock: true });
}

function reset() {
  clearTimeout(idleTimer);
  if (cfg.on && !overlay) idleTimer = setTimeout(() => showScreensaver(), cfg.after * 1000);
}

// iOS 13+ DeviceMotion iznini bir kullanıcı dokunuşuyla önceden iste (yıkım sahnesi sallama için gerekir; bekleme
// boşta açıldığından o an jest olmaz). Yalnız dokunmatik + 'gravity' seçiliyken, bir kez.
let _motionPrimed = false;
export function primeMotionPermission() {
  if (_motionPrimed) return Promise.resolve();
  const DM = window.DeviceMotionEvent;
  if (!DM || typeof DM.requestPermission !== 'function') { _motionPrimed = true; return Promise.resolve(); }
  _motionPrimed = true;
  return DM.requestPermission().catch(() => { _motionPrimed = false; });
}
function armMotionPrimer() {
  const coarse = matchMedia('(pointer: coarse)').matches || ('ontouchstart' in window);
  if (!coarse || !cfg.on || cfg.anim !== 'gravity') return;
  const h = () => { removeEventListener('pointerdown', h, true); primeMotionPermission(); };
  addEventListener('pointerdown', h, { capture: true, once: true });
}
['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll'].forEach(ev =>
  addEventListener(ev, () => { if (!overlay) reset(); }, { passive: true, capture: true }));
document.addEventListener('visibilitychange', () => { if (!document.hidden) reset(); });

// ---------- animasyonlar: (ctx, w, h, t sn) çizimi; kurulum gerekiyorsa init ile
const rnd = (a, b) => a + Math.random() * (b - a);
const SCENES = {
  matrix() {
    const chars = 'アイウエオカキクケコサシスセソ0123456789ABCDEFÇĞİÖŞÜ';
    let cols = [], size = 18, last = 0;
    return (c, w, h, t) => {
      if (cols.length !== Math.ceil(w / size)) cols = Array.from({ length: Math.ceil(w / size) }, () => rnd(-h, 0));
      c.fillStyle = 'rgba(8, 14, 24, 0.10)';
      c.fillRect(0, 0, w, h);
      if (t - last < 0.05) return;
      last = t;
      c.font = `${size - 2}px monospace`;
      cols.forEach((y, i) => {
        const hue = 170 + (i / cols.length) * 60 + Math.sin(t / 4) * 20;
        c.fillStyle = `hsla(${hue}, 70%, 72%, 0.85)`;
        c.fillText(chars[Math.floor(Math.random() * chars.length)], i * size, y);
        cols[i] = y > h + rnd(0, 400) ? 0 : y + size;
      });
    };
  },
  wave() {
    return (c, w, h, t) => {
      c.clearRect(0, 0, w, h);
      for (let k = 0; k < 7; k++) {
        c.beginPath();
        const amp = h * (0.06 + k * 0.022), freq = 1.2 + k * 0.35, ph = t * (0.5 + k * 0.12);
        for (let x = 0; x <= w; x += 4) {
          const env = Math.sin((x / w) * Math.PI);   // kenarlarda sönümlü
          const y = h / 2 + Math.sin((x / w) * freq * Math.PI * 2 + ph) * amp * env * (0.7 + 0.3 * Math.sin(t * 0.7 + k));
          x ? c.lineTo(x, y) : c.moveTo(x, y);
        }
        c.strokeStyle = `hsla(${200 + k * 18}, 80%, 65%, ${0.55 - k * 0.05})`;
        c.lineWidth = 2.2 - k * 0.2;
        c.shadowColor = c.strokeStyle; c.shadowBlur = 12;
        c.stroke();
      }
      c.shadowBlur = 0;
    };
  },
  aurora() {
    return (c, w, h, t) => {
      c.clearRect(0, 0, w, h);
      c.globalCompositeOperation = 'lighter';
      for (let k = 0; k < 4; k++) {
        const g = c.createLinearGradient(0, 0, 0, h);
        const hue = [150, 180, 280, 210][k];
        g.addColorStop(0, `hsla(${hue}, 80%, 60%, 0)`);
        g.addColorStop(0.45, `hsla(${hue}, 80%, 60%, 0.18)`);
        g.addColorStop(1, `hsla(${hue}, 80%, 60%, 0)`);
        c.fillStyle = g;
        c.beginPath();
        c.moveTo(0, h);
        for (let x = 0; x <= w; x += 8) c.lineTo(x, h * (0.35 + 0.15 * Math.sin(x / w * 3 + t * 0.3 + k * 1.7) + 0.08 * Math.sin(x / w * 9 - t * 0.5 + k)));
        c.lineTo(w, h); c.closePath(); c.fill();
      }
      c.globalCompositeOperation = 'source-over';
    };
  },
  network() {
    let pts = [];
    return (c, w, h) => {
      const n = Math.round(w * h / 16000);
      if (pts.length !== n) pts = Array.from({ length: n }, () => ({ x: rnd(0, w), y: rnd(0, h), vx: rnd(-0.3, 0.3), vy: rnd(-0.3, 0.3) }));
      c.clearRect(0, 0, w, h);
      for (const p of pts) { p.x = (p.x + p.vx + w) % w; p.y = (p.y + p.vy + h) % h; }
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, d = Math.hypot(dx, dy);
          if (d < 130) { c.strokeStyle = `rgba(120, 190, 255, ${0.35 * (1 - d / 130)})`; c.beginPath(); c.moveTo(pts[i].x, pts[i].y); c.lineTo(pts[j].x, pts[j].y); c.stroke(); }
        }
        c.fillStyle = 'rgba(170, 215, 255, 0.9)';
        c.beginPath(); c.arc(pts[i].x, pts[i].y, 1.8, 0, 7); c.fill();
      }
    };
  },
  stars() {
    let st = [];
    return (c, w, h) => {
      if (!st.length) st = Array.from({ length: 500 }, () => ({ x: rnd(-1, 1), y: rnd(-1, 1), z: rnd(0.05, 1) }));
      c.fillStyle = 'rgba(5, 8, 16, 0.35)';
      c.fillRect(0, 0, w, h);
      for (const s of st) {
        const pz = s.z;
        s.z -= 0.004;
        if (s.z <= 0.02) { s.x = rnd(-1, 1); s.y = rnd(-1, 1); s.z = 1; continue; }
        const k = Math.min(w, h) * 0.5;
        const x = w / 2 + s.x / s.z * k, y = h / 2 + s.y / s.z * k, px = w / 2 + s.x / pz * k, py = h / 2 + s.y / pz * k;
        c.strokeStyle = `rgba(200, 225, 255, ${1 - s.z})`;
        c.lineWidth = (1 - s.z) * 2.2;
        c.beginPath(); c.moveTo(px, py); c.lineTo(x, y); c.stroke();
      }
    };
  },
  radar() {
    let blips = [];
    return (c, w, h, t) => {
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.42, a = (t * 0.9) % (Math.PI * 2);
      c.fillStyle = 'rgba(4, 16, 12, 0.12)';
      c.fillRect(0, 0, w, h);
      c.strokeStyle = 'rgba(80, 220, 150, 0.25)';
      c.lineWidth = 1;
      for (let r = 1; r <= 4; r++) { c.beginPath(); c.arc(cx, cy, R * r / 4, 0, 7); c.stroke(); }
      c.beginPath(); c.moveTo(cx - R, cy); c.lineTo(cx + R, cy); c.moveTo(cx, cy - R); c.lineTo(cx, cy + R); c.stroke();
      const g = c.createConicGradient ? c.createConicGradient(a - 0.6, cx, cy) : null;
      if (g) { g.addColorStop(0, 'rgba(80,220,150,0)'); g.addColorStop(0.095, 'rgba(80,220,150,0.35)'); g.addColorStop(0.1, 'rgba(80,220,150,0)'); c.fillStyle = g; c.beginPath(); c.arc(cx, cy, R, 0, 7); c.fill(); }
      c.strokeStyle = 'rgba(120, 255, 180, 0.8)'; c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); c.stroke();
      if (Math.random() < 0.03) { const r = rnd(0.15, 0.95) * R; blips.push({ x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r, t }); }
      blips = blips.filter(b => t - b.t < 4);
      for (const b of blips) { c.fillStyle = `rgba(150, 255, 190, ${1 - (t - b.t) / 4})`; c.beginPath(); c.arc(b.x, b.y, 4, 0, 7); c.fill(); }
    };
  },
  bubbles() {
    let bs = [];
    return (c, w, h, t) => {
      if (!bs.length) bs = Array.from({ length: 14 }, (_, i) => ({ x: rnd(0, w), y: rnd(0, h), r: rnd(60, 180), s: rnd(8, 25), hue: 190 + i * 11, ph: rnd(0, 6) }));
      c.clearRect(0, 0, w, h);
      c.globalCompositeOperation = 'lighter';
      for (const b of bs) {
        b.y -= b.s / 60;
        if (b.y < -b.r) { b.y = h + b.r; b.x = rnd(0, w); }
        const x = b.x + Math.sin(t * 0.3 + b.ph) * 40;
        const g = c.createRadialGradient(x, b.y, 0, x, b.y, b.r);
        g.addColorStop(0, `hsla(${b.hue}, 75%, 62%, 0.35)`);
        g.addColorStop(1, `hsla(${b.hue}, 75%, 62%, 0)`);
        c.fillStyle = g; c.beginPath(); c.arc(x, b.y, b.r, 0, 7); c.fill();
      }
      c.globalCompositeOperation = 'source-over';
    };
  },
};

// Yıkım sahnesinin küçük önizlemesi: ekran yakalamadan, düşüp seken renkli kartlar (birkaç saniyede bir yeniden)
const MINI_ACCENTS = ['#4a8ae0', '#22c55e', '#f59e0b', '#a855f7', '#ef4444'];
function miniGravity() {
  let bodies = [], born = -99, lastT = 0;
  return (c, w, h, t) => {
    if (t - born > 5 || !bodies.length) {
      born = t;
      bodies = Array.from({ length: 9 }, (_, i) => {
        const bw = rnd(70, 120), bh = rnd(34, 54);
        return { x: 40 + (i % 3) * (w / 3) + rnd(-10, 10), y: 40 + Math.floor(i / 3) * 64, w: bw, h: bh, vx: rnd(-90, 90), vy: rnd(-120, 0),
          a: 0, va: rnd(-2, 2), col: MINI_ACCENTS[i % MINI_ACCENTS.length] };
      });
    }
    const dt = Math.min(0.05, Math.max(0, t - lastT)); lastT = t;
    c.clearRect(0, 0, w, h);
    for (const b of bodies) {
      if (t - born > 0.5) {   // önce yerinde durur, sonra çöker
        b.vy += 1100 * dt; b.x += b.vx * dt; b.y += b.vy * dt; b.a += b.va * dt;
        if (b.y + b.h / 2 > h - 4) { b.y = h - 4 - b.h / 2; b.vy *= -0.38; b.vx *= 0.8; b.va *= 0.6; }
        if (b.x - b.w / 2 < 0 || b.x + b.w / 2 > w) { b.vx *= -0.6; b.x = Math.min(w - b.w / 2, Math.max(b.w / 2, b.x)); }
      }
      c.save(); c.translate(b.x, b.y); c.rotate(b.a);
      c.fillStyle = 'rgba(236, 242, 250, 0.92)';
      c.beginPath(); c.roundRect ? c.roundRect(-b.w / 2, -b.h / 2, b.w, b.h, 8) : c.rect(-b.w / 2, -b.h / 2, b.w, b.h); c.fill();
      c.fillStyle = b.col; c.fillRect(-b.w / 2 + 8, -b.h / 2 + 8, b.w * 0.45, 5);
      c.fillStyle = 'rgba(100, 116, 139, 0.45)'; c.fillRect(-b.w / 2 + 8, -b.h / 2 + 18, b.w * 0.7, 4);
      c.restore();
    }
  };
}

// Ayarlar › Bekleme ekranı: seçim karesinde CANLI küçük önizleme. Sahneler sanal 640 px genişlikte çizilip kareye ölçeklenir
// (tam ekrandakiyle aynı görünüm). play()/pause() dışarıdan (görünürlük gözlemcisi) çağrılır; ~30 kare/sn ile sınırlı.
// still=true (hareketleri azalt): tek bir temsilî kare çizilir, döngü kurulmaz.
const PV_W = 640;
export function createAnimPreview(canvas, anim, { still = false } = {}) {
  let raf = 0, globe = null, draw = null, cur = null, t0 = performance.now(), last = 0, alive = true, swapAt = 0;
  const c = canvas.getContext('2d');
  const pool = ANIMATIONS.map(a => a[0]).filter(k => k !== 'random');
  const fit = () => {
    const r = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
    const W = Math.max(1, Math.round(r.width * dpr)), H = Math.max(1, Math.round(r.height * dpr));
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    return { W, H };
  };
  const setup = a => {
    globe?.destroy(); globe = null; cur = a; draw = null;
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, canvas.width, canvas.height);
    if (a !== 'globe') draw = a === 'gravity' ? miniGravity() : (SCENES[a] || SCENES.wave)();
  };
  const frame = t => {
    const { W, H } = fit(), k = W / PV_W, vh = H / k;
    c.setTransform(k, 0, 0, k, 0, 0);
    draw(c, PV_W, vh, t);
  };
  const first = anim === 'random' ? pool[Math.floor(Math.random() * pool.length)] : anim;
  setup(first);
  const startGlobe = () => { if (!globe) globe = createGlobe(canvas, { size: 0.38, speed: 14, color: '120,180,255', land: 0.8, grid: 0.25, back: 0.08 }); };
  if (still) {   // tek kare: sahneyi ~3 sn ileri sarıp son durumu bırak
    if (cur === 'globe') { startGlobe(); setTimeout(() => { globe?.destroy(); globe = null; }, 1500); }
    else for (let i = 0; i < 90; i++) frame(i / 30);
    return { play() {}, pause() {}, destroy() { globe?.destroy(); globe = null; } };
  }
  const loop = now => {
    raf = 0;
    if (!alive) return;
    if (!canvas.isConnected) { api.destroy(); return; }   // ayar sayfasından çıkıldı
    if (anim === 'random' && now > swapAt) {   // Rastgele: birkaç saniyede bir başka sahne
      swapAt = now + 3500;
      let next = cur; while (next === cur) next = pool[Math.floor(Math.random() * pool.length)];
      setup(next); t0 = now;
    }
    if (cur === 'globe') startGlobe();
    else if (now - last >= 33) { last = now; frame((now - t0) / 1000); }
    raf = requestAnimationFrame(loop);
  };
  const api = {
    play() { if (!alive || raf) return; if (anim === 'random' && !swapAt) swapAt = performance.now() + 3500; raf = requestAnimationFrame(loop); },
    pause() { cancelAnimationFrame(raf); raf = 0; globe?.destroy(); globe = null; if (cur === 'globe') { /* son kare tuvalde kalır */ } },
    destroy() { alive = false; api.pause(); },
  };
  if (cur !== 'globe') for (let i = 0; i < 60; i++) frame(i / 30);   // görünür olana dek dolu bir ilk kare dursun (~2 sn ileri sarılmış)
  return api;
}

export function showScreensaver(anim = cfg.anim, { preview = false, unlock = false } = {}) {
  if (overlay) return;
  if (preview && anim === 'gravity') primeMotionPermission();   // önizleme bir kullanıcı jesti → iOS izni iste
  const lock = !preview && cfg.lock && !!user;
  if (lock) { try { sessionStorage.setItem(LOCK_KEY, '1'); } catch { /* yok say */ } }
  clearTimeout(idleTimer);
  if (anim === 'random') { const list = ANIMATIONS.filter(a => a[0] !== 'random'); anim = list[Math.floor(Math.random() * list.length)][0]; }
  // Yıkım sahnesi: overlay sayfayı örtmeden ÖNCE mevcut ekran bileşenlerini yakala
  const shards = anim === 'gravity' ? captureShards() : null;
  const canvas = document.createElement('canvas');
  canvas.className = 'ss-canvas';
  const time = document.createElement('div'); time.className = 'ss-time';
  const date = document.createElement('div'); date.className = 'ss-date';
  const logo = document.createElement('img'); logo.className = 'ss-logo'; logo.src = '/static/img/logo-mark.png?v=3'; logo.alt = '';
  const clock = document.createElement('div'); clock.className = 'ss-clock'; clock.append(time, date);
  const hint = document.createElement('div'); hint.className = 'ss-hint';
  hint.textContent = !preview && cfg.lock && user ? '🔒 Kilidi açmak için dokunun' : 'Devam etmek için dokunun';
  overlay = document.createElement('div');
  overlay.className = `ss ss-${anim}`;
  overlay.append(canvas, logo, clock, hint);
  document.body.append(overlay);
  const tick = () => {
    const d = new Date();
    time.textContent = d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
    date.textContent = d.toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    // Saat yazısı yavaşça yer değiştirir (ekran izi kalmasın)
    clock.style.transform = `translate(${Math.sin(d / 60000) * 8}vw, ${Math.cos(d / 47000) * 6}vh)`;
  };
  tick();
  const clockTimer = setInterval(tick, 1000);

  let stop;
  if (anim === 'globe') {
    const g = createGlobe(canvas, { size: 0.36, speed: 5, color: '120,180,255', land: 0.8, grid: 0.25, back: 0.08 });
    stop = () => g.destroy();
  } else if (anim === 'gravity') {
    const scene = createGravityScene(canvas, shards, { preview });
    stop = () => scene.destroy();
  } else {
    const c = canvas.getContext('2d');
    const draw = (SCENES[anim] || SCENES.wave)();
    let raf, t0 = performance.now();
    const fit = () => { const r = devicePixelRatio || 1; canvas.width = innerWidth * r; canvas.height = innerHeight * r; c.setTransform(r, 0, 0, r, 0, 0); };
    fit();
    addEventListener('resize', fit);
    const loop = now => { draw(c, innerWidth, innerHeight, (now - t0) / 1000); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    stop = () => { cancelAnimationFrame(raf); removeEventListener('resize', fit); };
  }
  requestAnimationFrame(() => overlay?.classList.add('on'));

  const listen = on => ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(ev =>
    (on ? addEventListener : removeEventListener)(ev, wake, { capture: true, passive: false }));
  const finish = () => {
    listen(false);
    if (!overlay) return;
    const el = overlay;
    overlay = null;
    try { sessionStorage.removeItem(LOCK_KEY); } catch { /* yok say */ }
    el.classList.remove('on');
    setTimeout(() => { stop(); clearInterval(clockTimer); el.remove(); }, 350);
    reset();
  };
  // Kilit paneli: saat yukarı kayar, arka plan bulanıklaşır, şifre kartı yükselir
  let panel = null;
  const askPassword = (mode = user.has_pin ? 'pin' : 'password') => {
    if (panel && panel.dataset.mode === mode) { panel.querySelector('input')?.focus(); return; }
    panel?.remove();
    overlay.classList.add('ask');
    const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
    const err = el('div', 'ss-err');
    const av = el('div', 'ss-av');
    if (user.photo) { const im = document.createElement('img'); im.src = fileUrl(user.photo, 256); im.alt = ''; av.append(im); }
    else av.textContent = (user.full_name || '?').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr');
    const other = el('a', 'ss-other', 'Farklı kullanıcıyla giriş');
    other.href = '#';
    other.addEventListener('click', e => { e.preventDefault(); finish(); dispatchEvent(new Event('caymaz:logout')); });
    panel = el('form', 'ss-lock');
    panel.dataset.mode = mode;
    let backTimer = null;
    const idle = ms => { clearTimeout(backTimer); backTimer = setTimeout(() => { if (panel) { overlay?.classList.remove('ask'); panel.remove(); panel = null; } }, ms); };
    idle(20000);   // bir süre dokunulmazsa animasyona geri döner
    const shake = msg => { err.textContent = msg; panel.classList.remove('shake'); void panel.offsetWidth; panel.classList.add('shake'); };
    const tryUnlock = async body => {
      try {
        await api.post('/api/auth/unlock', body);
        clearTimeout(backTimer);
        panel.classList.add('ok');
        setTimeout(finish, 250);
        return true;
      } catch (ex) {
        if (ex.status === 401) { finish(); return false; }   // çok fazla hata: oturum kapandı, giriş ekranı açılır
        shake(ex.message || 'Hatalı');
        return false;
      }
    };
    panel.append(av, el('div', 'ss-name', user.full_name));
    if (mode === 'pin') {
      // PIN: 4 nokta + tuş takımı (klavyeden de yazılır)
      let pin = '';
      const dots = el('div', 'ss-dots');
      const draw = () => { dots.replaceChildren(...[0, 1, 2, 3].map(i => el('i', i < pin.length ? 'on' : ''))); };
      const press = async k => {
        idle(30000);
        err.textContent = '';
        if (k === '⌫') pin = pin.slice(0, -1); else if (pin.length < 4) pin += k;
        draw();
        if (pin.length === 4) { const p = pin; pin = ''; if (!await tryUnlock({ pin: p })) draw(); }
      };
      const pad = el('div', 'ss-pad');
      ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫'].forEach(k => {
        if (!k) { pad.append(el('span')); return; }
        const b = el('button', `ss-key ${k === '⌫' ? 'del' : ''}`, k);
        b.type = 'button';
        b.addEventListener('click', () => press(k));
        pad.append(b);
      });
      const onKey = e => {
        if (!panel || panel.dataset.mode !== 'pin') { removeEventListener('keydown', onKey, true); return; }
        if (/^\d$/.test(e.key)) { e.preventDefault(); e.stopPropagation(); press(e.key); }
        else if (e.key === 'Backspace') { e.preventDefault(); e.stopPropagation(); press('⌫'); }
      };
      addEventListener('keydown', onKey, true);
      draw();
      const pw = el('a', 'ss-other', 'Şifreyle aç');
      pw.href = '#';
      pw.addEventListener('click', e => { e.preventDefault(); askPassword('password'); });
      panel.append(el('div', 'ss-sub', 'PIN kodunuzu girin'), dots, err, pad, pw, other);
    } else {
      const pw = el('input', 'ss-pw');
      Object.assign(pw, { type: 'password', placeholder: 'Şifreniz', autocomplete: 'current-password' });
      const btn = el('button', 'ss-go', '→'); btn.type = 'submit'; btn.title = 'Kilidi aç';
      const row = el('div', 'ss-row'); row.append(pw, btn);
      pw.addEventListener('input', () => { idle(30000); err.textContent = ''; });
      panel.addEventListener('submit', async e => {
        e.preventDefault();
        if (!pw.value) return;
        btn.disabled = true;
        if (!await tryUnlock({ password: pw.value })) { pw.value = ''; pw.focus(); }
        btn.disabled = false;
      });
      panel.append(row, err);
      if (user.has_pin) {
        const pinLink = el('a', 'ss-other', 'PIN ile aç');
        pinLink.href = '#';
        pinLink.addEventListener('click', e => { e.preventDefault(); askPassword('pin'); });
        panel.append(pinLink);
      }
      panel.append(other);
      requestAnimationFrame(() => pw.focus());
    }
    overlay.append(panel);
    requestAnimationFrame(() => panel?.classList.add('in'));
  };
  function wake(e) {
    if (panel && panel.contains(e.target)) return;   // kilit kartındaki yazma / tıklama serbest
    e.preventDefault?.(); e.stopPropagation?.();
    if (!overlay) return;
    if (lock) askPassword(); else finish();
  }
  addEventListener('caymaz:unauthorized', finish, { once: true });
  // Açılış anındaki fare kıpırtısı kapatmasın: kapatma yalnızca dokunuş / tuş / tekerlek ile (0.6 sn sonra)
  setTimeout(() => { if (overlay) listen(true); }, unlock ? 0 : 600);
  if (unlock) setTimeout(() => overlay && askPassword(), 50);
  overlay.addEventListener('click', e => { if (!panel?.contains(e.target)) { e.preventDefault(); e.stopPropagation(); } }, true);
}
