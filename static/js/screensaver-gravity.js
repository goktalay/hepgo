// Bekleme ekranı: "Yıkım" (interaktif yerçekimi) sahnesi.
// Bekleme başlarken ekrandaki bileşenler (kartlar, kutucuklar, düğmeler…) yakalanır; parçalara ayrılıp yerçekimiyle
// düşer ve zeminde yığılır. Dokunmatik cihazda (telefon/tablet) cihaz sallanınca parçalar hareket eder (devicemotion).
// Bilgisayarda bir çöp adam belirip parçaları sağa sola fırlatır. Dokunuş/tuş bekleme ekranını kapatır (screensaver.js).

const rnd = (a, b) => a + Math.random() * (b - a);
const isTransparent = col => !col || col === 'transparent' || /rgba?\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(col);

// Renkli vurgu paleti (beyaz kartlara kimlik/çeşitlilik verir)
const ACCENTS = [[10, 132, 255], [52, 199, 89], [255, 159, 10], [255, 55, 95], [94, 92, 230],
  [100, 210, 255], [191, 90, 242], [255, 100, 130], [48, 209, 88], [255, 214, 10], [50, 173, 230], [255, 112, 67]];
const parseRGB = s => { const m = (s || '').match(/\d+\.?\d*/g); return m ? m.slice(0, 3).map(Number) : [255, 255, 255]; };
const lum = ([r, g, b]) => (0.299 * r + 0.587 * g + 0.114 * b) / 255;

// Görünür ekrandaki bileşenleri yakala: konum/boyut + renk + köşe + başlık + vurgu. En dıştaki bloklar seçilir
// (iç içe elenir), çok büyük bloklar bileşen çocuklarına bölünür. Overlay DOM'a eklenmeden ÖNCE çağrılmalı.
export function captureShards(max = 48) {
  const vw = innerWidth, vh = innerHeight, vwh = vw * vh;
  const SEL = '.card, .set-card, .db-tile, .stat, .page-head, .topbar, .btn, .seg-tabs, .filters, .chip, .kpi, table, .empty, h1, h2';
  const bgOf = el => {
    for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
      const b = getComputedStyle(n).backgroundColor;
      if (!isTransparent(b)) return b;
    }
    return null;
  };
  const visible = (el, r) => r.width >= 26 && r.height >= 16 && r.bottom > 4 && r.top < vh - 4 && r.right > 4 && r.left < vw - 4;
  const cand = [];
  document.querySelectorAll(SEL).forEach(el => {
    if (el.closest('.ss, .modal-back, .ss-panel')) return;
    const r = el.getBoundingClientRect();
    if (!visible(el, r)) return;
    if (r.width > vw * 0.985 && r.height > vh * 0.88) return;   // tüm sayfa kabı
    cand.push({ el, r });
  });
  cand.sort((a, b) => b.r.width * b.r.height - a.r.width * a.r.height);   // büyükten küçüğe
  const picked = [];
  for (const o of cand) {
    if (picked.some(p => p.el.contains(o.el) || o.el.contains(p.el))) continue;   // iç içe olanı tekrarlama
    picked.push(o);
  }
  // Çok büyük seçimleri (yarım ekran gibi) bileşen çocuklarına böl → daha küçük, çeşitli parçalar
  const KID = '.card, .db-tile, .stat, .kpi, .btn, .chip, .set-card, tr, .list-row, .row, .ba-row, h2, h3';
  const out = [];
  for (const o of picked) {
    const area = o.r.width * o.r.height;
    if (area > vwh * 0.14) {
      const kids = [...o.el.querySelectorAll(KID)].map(k => ({ el: k, r: k.getBoundingClientRect() }))
        .filter(k => visible(k.el, k.r) && k.r.width * k.r.height < area * 0.6);
      kids.sort((a, b) => b.r.width * b.r.height - a.r.width * a.r.height);
      const uniq = [];
      for (const k of kids) { if (uniq.some(u => u.el.contains(k.el) || k.el.contains(u.el))) continue; uniq.push(k); }
      if (uniq.length >= 2) { out.push(...uniq.slice(0, 12)); continue; }
    }
    out.push(o);
  }
  const final = out.slice(0, max);
  return final.map(({ el, r }, i) => {
    const st = getComputedStyle(el);
    const col = isTransparent(st.backgroundColor) ? (bgOf(el) || 'rgb(148,163,184)') : st.backgroundColor;
    const radius = Math.min(18, parseFloat(st.borderTopLeftRadius) || 6);
    const hd = el.querySelector('h1,h2,h3,h4,.db-head h3,b,strong,.stat-v,.kpi-v,.set-h');
    let text = (hd?.textContent || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 26);
    if (el.matches('table') && !hd) text = '';
    return { x: r.left, y: r.top, w: r.width, h: r.height, color: col, radius, text, accent: ACCENTS[i % ACCENTS.length] };
  });
}

// Sahneyi kur. canvas = .ss-canvas; shards = captureShards() çıktısı. { destroy } döner.
export function createGravityScene(canvas, shards, { preview = false } = {}) {
  const c = canvas.getContext('2d');
  let W = 0, H = 0;
  const fit = () => {
    const dpr = devicePixelRatio || 1;
    W = innerWidth; H = innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  fit();
  addEventListener('resize', fit);

  const isTouch = matchMedia('(pointer: coarse)').matches || ('ontouchstart' in window);
  const G = 2300;        // yerçekimi (px/sn²)
  const REST = 0.42;     // zeminden/duvardan zıplama katsayısı
  const FR = 0.84;       // zemin yatay sürtünme

  // Yakalanan bileşen yoksa (boş sayfa) dekoratif kutular üret
  const src = shards && shards.length ? shards : Array.from({ length: 16 }, (_, i) => {
    const w = rnd(80, 190), hh = rnd(50, 130);
    return { x: rnd(0, W - w), y: rnd(0, H * 0.5), w, h: hh, color: 'rgb(255,255,255)', radius: 12, text: '', accent: ACCENTS[i % ACCENTS.length] };
  });

  // Cisimler: başlangıçta ekrandaki yerlerinde, sonra dışa doğru savrulup düşerler.
  // Beyaz/çok açık kartlara vurgu renginden hafif ton katılır (hepsi tek düze beyaz görünmesin).
  const bodies = src.map(s => {
    const cx = s.x + s.w / 2, cy = s.y + s.h / 2;
    const accent = s.accent || [120, 140, 170];
    let rgb = parseRGB(s.color);
    if (lum(rgb) > 0.86) rgb = rgb.map((v, i) => Math.round(v * 0.82 + accent[i] * 0.18));   // açık kartlara renk tonu
    const fill = `rgb(${rgb.join(',')})`;
    const textColor = lum(rgb) > 0.6 ? 'rgba(20,28,45,.92)' : 'rgba(255,255,255,.95)';
    return {
      w: s.w, h: s.h, cx, cy,
      vx: ((cx - W / 2) / Math.max(W, 1)) * rnd(140, 420) + rnd(-90, 90),
      vy: rnd(-280, -30), a: 0, va: rnd(-2.4, 2.4),
      color: fill, accent: `rgb(${accent.join(',')})`, textColor, lineColor: lum(rgb) > 0.6 ? 'rgba(20,28,45,.14)' : 'rgba(255,255,255,.2)',
      radius: s.radius, text: s.text, asleep: false,
      lines: [0.9, 0.5 + Math.random() * 0.4, 0.5 + Math.random() * 0.4, 0.5 + Math.random() * 0.4],
    };
  });

  // --- Mobil: cihaz sallama (devicemotion) ---
  let motionFx = 0, motionFy = 0, grav = { x: 0, y: 0, z: 0 };
  const onMotion = e => {
    let a = e.acceleration;
    if (a && a.x != null) { motionFx = a.x; motionFy = a.y; }
    else {                                   // ivme (yerçekimsiz) yoksa: yüksek-geçiren filtre ile ayıkla
      const g = e.accelerationIncludingGravity; if (!g) return;
      grav.x += ((g.x || 0) - grav.x) * 0.2; grav.y += ((g.y || 0) - grav.y) * 0.2;
      motionFx = (g.x || 0) - grav.x; motionFy = (g.y || 0) - grav.y;
    }
  };
  if (isTouch) addEventListener('devicemotion', onMotion);

  // --- Masaüstü: çöp adam (parçaları sağa sola fırlatır) ---
  const stick = isTouch ? null : {
    x: -70, face: 1, speed: 0, phase: 0, arm: 0,           // arm: 0..1 fırlatma açısı
    state: 'enter', t: 0, target: null,
  };

  const pickTarget = () => {
    // zemine yakın, ekran içinde, en yakın cisim
    let best = null, bd = 1e9;
    for (const b of bodies) {
      if (b.cx < -40 || b.cx > W + 40) continue;
      const d = Math.abs(b.cx - stick.x) + Math.max(0, (H - b.cy) - H * 0.35) * 0.4;
      if (d < bd) { bd = d; best = b; }
    }
    return best;
  };

  const updateStick = dt => {
    const s = stick;
    s.phase += dt * (6 + Math.abs(s.speed) * 0.03);
    if (s.state === 'enter') {
      s.speed = 150; s.x += s.speed * dt;
      if (s.x > W * 0.22) { s.state = 'seek'; s.target = pickTarget(); }
    } else if (s.state === 'seek') {
      if (!s.target || s.target.cx < -40 || s.target.cx > W + 40) { s.target = pickTarget(); s.t = 0; }
      if (!s.target) { s.speed = 110 * (Math.sin(s.phase * 0.2) > 0 ? 1 : -1); s.x += s.speed * dt; s.face = Math.sign(s.speed) || 1; s.x = Math.max(30, Math.min(W - 30, s.x)); return; }
      const dx = s.target.cx - s.x;
      s.face = dx >= 0 ? 1 : -1;
      if (Math.abs(dx) > 46) { s.speed = 230 * s.face; s.x += s.speed * dt; }
      else { s.speed = 0; s.state = 'wind'; s.t = 0; s.arm = 0; }
    } else if (s.state === 'wind') {        // kolu geriye al
      s.speed = 0; s.t += dt; s.arm = Math.min(1, s.t / 0.32);
      if (s.t >= 0.32) { s.state = 'throw'; s.t = 0; }
    } else if (s.state === 'throw') {       // fırlat: hedefe hız ver
      s.t += dt;
      if (s.target) {
        const dir = Math.random() < 0.5 ? -1 : 1;    // sağa ya da sola
        s.face = dir;
        s.target.vx = dir * rnd(620, 1180);
        s.target.vy = rnd(-820, -360);
        s.target.va = rnd(-9, 9);
        s.target.asleep = false;
        s.target = null;
      }
      s.arm = 0; s.state = 'cool'; s.t = 0;
    } else if (s.state === 'cool') {
      s.t += dt; if (s.t > 0.25) { s.state = 'seek'; s.target = pickTarget(); }
    }
  };

  const step = dt => {
    dt = Math.min(dt, 0.034);
    for (const b of bodies) {
      if (!b.asleep) {
        b.vy += G * dt;
        if (isTouch) { b.vx += (-motionFx) * 300 * dt; b.vy += (motionFy) * 180 * dt; }   // sallama kuvveti
        b.cx += b.vx * dt; b.cy += b.vy * dt; b.a += b.va * dt;
        b.va *= 0.995;
      } else if (isTouch && (Math.abs(motionFx) > 2.2 || Math.abs(motionFy) > 2.6)) {
        b.asleep = false; b.vy = -Math.abs(motionFx + motionFy) * 20 - 40;   // sallayınca uyandır
        b.vx += (-motionFx) * 40;
      }
      // duvarlar
      const rw = Math.max(b.w, b.h) / 2 * 0.72;
      if (b.cx < rw) { b.cx = rw; b.vx = Math.abs(b.vx) * REST; b.va *= 0.7; b.asleep = false; }
      else if (b.cx > W - rw) { b.cx = W - rw; b.vx = -Math.abs(b.vx) * REST; b.va *= 0.7; b.asleep = false; }
      // zemin
      const fh = b.h / 2;
      if (b.cy > H - fh) {
        b.cy = H - fh;
        b.vx *= FR; b.va *= 0.55;
        if (Math.abs(b.vy) < 70) { b.vy = 0; b.a += (0 - b.a) * 0.18; if (Math.abs(b.vx) < 6 && Math.abs(b.a) < 0.05) b.asleep = true; }
        else b.vy = -b.vy * REST;
      }
    }
    // cisim-cisim ayrışma (dairesel yaklaşım) → yığın
    for (let i = 0; i < bodies.length; i++) {
      for (let j = i + 1; j < bodies.length; j++) {
        const a = bodies[i], b = bodies[j];
        const ra = Math.min(a.w, a.h) / 2 * 0.92, rb = Math.min(b.w, b.h) / 2 * 0.92;
        let dx = b.cx - a.cx, dy = b.cy - a.cy, d = Math.hypot(dx, dy) || 0.01, ov = ra + rb - d;
        if (ov > 0) {
          const nx = dx / d, ny = dy / d, push = ov / 2;
          a.cx -= nx * push; a.cy -= ny * push; b.cx += nx * push; b.cy += ny * push;
          const rel = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny;
          if (rel < 0) { const imp = rel * 0.5; a.vx += nx * imp; a.vy += ny * imp; b.vx -= nx * imp; b.vy -= ny * imp; }
          if (ov > 2) { a.asleep = false; b.asleep = false; }
        }
      }
    }
    if (stick) updateStick(dt);
  };

  const roundRect = (x, y, w, h, r) => {
    if (c.roundRect) { c.beginPath(); c.roundRect(x, y, w, h, r); return; }
    r = Math.min(r, w / 2, h / 2);
    c.beginPath();
    c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  };

  const drawBody = b => {
    const hw = b.w / 2, hh = b.h / 2;
    c.save();
    c.translate(b.cx, b.cy); c.rotate(b.a);
    // gövde (gölgeli)
    c.shadowColor = 'rgba(0,0,0,.5)'; c.shadowBlur = 16; c.shadowOffsetY = 7;
    c.fillStyle = b.color;
    roundRect(-hw, -hh, b.w, b.h, b.radius); c.fill();
    c.shadowColor = 'transparent'; c.shadowBlur = 0; c.shadowOffsetY = 0;
    // içerik yalnız panel içine
    c.save(); roundRect(-hw, -hh, b.w, b.h, b.radius); c.clip();
    const strip = Math.max(6, Math.min(14, b.h * 0.16));   // renkli üst vurgu şeridi (başlık bandı)
    c.fillStyle = b.accent; c.fillRect(-hw, -hh, b.w, strip);
    const padX = Math.min(12, b.w * 0.08);
    // başlık metni (vurgu şeridinin altında)
    if (b.text && b.w > 46 && b.h > strip + 14) {
      c.fillStyle = b.textColor;
      c.font = `600 ${Math.max(11, Math.min(16, b.h * 0.2))}px system-ui, -apple-system, sans-serif`;
      c.textAlign = 'left'; c.textBaseline = 'top';
      c.fillText(b.text, -hw + padX, -hh + strip + Math.min(10, b.h * 0.1), b.w - padX * 2);
    }
    // içerik çizgileri (gri placeholder) — yeterince büyük panellerde
    const lineY0 = -hh + strip + (b.text ? Math.min(10, b.h * 0.1) + 22 : 14);
    c.fillStyle = b.lineColor;
    for (let i = 0, y = lineY0; i < 4 && y < hh - 10; i++, y += 14) {
      const lw = (b.w - padX * 2) * b.lines[i];
      roundRect(-hw + padX, y, lw, 6, 3); c.fill();
    }
    c.restore();
    // kenarlık
    c.strokeStyle = 'rgba(0,0,0,.12)'; c.lineWidth = 1;
    roundRect(-hw + 0.5, -hh + 0.5, b.w - 1, b.h - 1, b.radius); c.stroke();
    c.restore();
  };

  const drawStick = () => {
    const s = stick;
    const hgt = Math.min(H * 0.2, 150), lw = Math.max(3, hgt * 0.035);
    const foot = H - 2, hipY = foot - hgt * 0.42, shoY = foot - hgt * 0.74, headR = hgt * 0.12, headY = shoY - headR - 2;
    c.save();
    c.strokeStyle = 'rgba(255,255,255,.92)'; c.fillStyle = 'rgba(255,255,255,.92)';
    c.lineWidth = lw; c.lineCap = 'round'; c.lineJoin = 'round';
    const moving = Math.abs(s.speed) > 5;
    const sw = moving ? Math.sin(s.phase) * hgt * 0.14 : 0;
    // bacaklar
    c.beginPath(); c.moveTo(s.x, hipY); c.lineTo(s.x + sw, foot); c.moveTo(s.x, hipY); c.lineTo(s.x - sw, foot); c.stroke();
    // gövde
    c.beginPath(); c.moveTo(s.x, hipY); c.lineTo(s.x, shoY); c.stroke();
    // kollar: fırlatma durumunda bir kol yukarı/geri, değilse yürüme sallanışı
    const asw = moving ? Math.sin(s.phase + Math.PI) * hgt * 0.1 : 0;
    const throwing = s.state === 'wind' || s.state === 'throw';
    c.beginPath();
    if (throwing) {
      const up = s.arm;                                   // 0: yatay, 1: tam geride/yukarıda
      const ax = s.x - s.face * hgt * 0.34 * (1 - up) + s.face * hgt * 0.1 * up;
      const ay = shoY - hgt * 0.3 * up;
      c.moveTo(s.x, shoY + hgt * 0.06); c.lineTo(ax, ay);                       // fırlatan kol
      c.moveTo(s.x, shoY + hgt * 0.06); c.lineTo(s.x - s.face * hgt * 0.18, shoY + hgt * 0.16);   // diğer kol
    } else {
      c.moveTo(s.x, shoY + hgt * 0.06); c.lineTo(s.x + asw, shoY + hgt * 0.26);
      c.moveTo(s.x, shoY + hgt * 0.06); c.lineTo(s.x - asw, shoY + hgt * 0.26);
    }
    c.stroke();
    // kafa
    c.beginPath(); c.arc(s.x, headY, headR, 0, 7); c.fill();
    c.restore();
  };

  let raf, prev = performance.now();
  const loop = now => {
    const dt = (now - prev) / 1000; prev = now;
    step(dt || 0.016);
    c.clearRect(0, 0, W, H);
    for (const b of bodies) drawBody(b);
    if (stick) drawStick();
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);

  return {
    destroy() {
      cancelAnimationFrame(raf);
      removeEventListener('resize', fit);
      if (isTouch) removeEventListener('devicemotion', onMotion);
    },
  };
}
