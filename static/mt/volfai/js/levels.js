// VOLFAI - 30 bölüm × 5-10 parkur kampanyası ve prosedürel "gezegen" sanatı
// Volfied'de her bölümün kendine özgü arka planı vardır; alan kapattıkça ortaya çıkar.
import { LEVEL_COUNT, PARKUR_MIN, PARKUR_MAX, DIFFICULTY } from './config.js';

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 30 bölüm = 30 farklı yaratık (Volfied'de her bölümün kendine özgü ana düşmanı vardır).
// shape: çizim ailesi · pattern: hareket kalıbı (wander, bounce, zigzag, orbit, charge)
// pulse: boyut nefes alır · serpent: gövde halkaları takip eder · dual: iki yaratık birlikte
export const CREATURES = [
  { name: 'UZAY AMİBİ',          shape: 'amoeba',    pattern: 'wander', hue: 25,  rMul: 1.0 },
  { name: 'KIZIL AKREP',         shape: 'crab',      pattern: 'zigzag', hue: 10,  rMul: 1.0 },
  { name: 'BUZ KRİSTALİ',        shape: 'crystal',   pattern: 'bounce', hue: 195, rMul: 1.0 },
  { name: 'NEBULA DENİZANASI',   shape: 'jelly',     pattern: 'wander', hue: 290, rMul: 1.1, pulse: true },
  { name: 'HALKA BEKÇİSİ',       shape: 'ring',      pattern: 'orbit',  hue: 45,  rMul: 1.1 },
  { name: 'ŞEHİR GÖZÜ',          shape: 'eye',       pattern: 'charge', hue: 160, rMul: 1.0 },
  { name: 'LAV YILDIZI',         shape: 'star',      pattern: 'bounce', hue: 15,  rMul: 1.0, spin: 3 },
  { name: 'AY BÖCEĞİ',           shape: 'beetle',    pattern: 'zigzag', hue: 215, rMul: 1.0 },
  { name: 'ASTEROİT ÇEKİRDEĞİ',  shape: 'virus',     pattern: 'wander', hue: 30,  rMul: 1.2 },
  { name: 'İKİZ KALAMARLAR',     shape: 'squid',     pattern: 'wander', hue: 150, rMul: 0.9, dual: true },
  { name: 'FIRTINA GİRDABI',     shape: 'spiral',    pattern: 'orbit',  hue: 250, rMul: 1.1, spin: 2 },
  { name: 'KRİSTAL KÜP',         shape: 'cube',      pattern: 'bounce', hue: 300, rMul: 1.0, spin: 1.2 },
  { name: 'ÇİFT GÜNEŞ KÜRELERİ', shape: 'orb',       pattern: 'orbit',  hue: 50,  rMul: 0.9, dual: true, pulse: true },
  { name: 'OLAY UFKU GÖZÜ',      shape: 'eye',       pattern: 'wander', hue: 270, rMul: 1.25, pulse: true },
  { name: 'KOMUTA DRONU',        shape: 'saucer',    pattern: 'charge', hue: 0,   rMul: 1.0 },
  { name: 'GÖLGE PERVANESİ',     shape: 'moth',      pattern: 'wander', hue: 330, rMul: 1.1 },
  { name: 'DEMİR DİŞLİ',         shape: 'gear',      pattern: 'bounce', hue: 20,  rMul: 1.0, spin: 1.5 },
  { name: 'KUTUP YILANI',        shape: 'serpent',   pattern: 'wander', hue: 210, rMul: 0.8, serpent: 7 },
  { name: 'PLAZMA SOLUCANI',     shape: 'serpent',   pattern: 'zigzag', hue: 290, rMul: 0.8, serpent: 10 },
  { name: 'GAZ DEVİ BALONU',     shape: 'amoeba',    pattern: 'wander', hue: 35,  rMul: 1.35, pulse: true },
  { name: 'AYNA PRİZMASI',       shape: 'diamond',   pattern: 'zigzag', hue: 180, rMul: 1.0, spin: 0.8 },
  { name: 'ZÜMRÜT ÖRÜMCEKLER',   shape: 'spider',    pattern: 'charge', hue: 120, rMul: 0.85, dual: true },
  { name: 'ÇİFTE HALKA',         shape: 'ring',      pattern: 'bounce', hue: 320, rMul: 0.9, dual: true, spin: 2 },
  { name: 'ÖLÜ YILDIZ KAFASI',   shape: 'skull',     pattern: 'wander', hue: 60,  rMul: 1.1 },
  { name: 'SAFİR HİDRA',         shape: 'hydra',     pattern: 'charge', hue: 230, rMul: 1.15 },
  { name: 'ÜÇLÜ GÜNEŞ ÇEKİRDEĞİ', shape: 'trisun',   pattern: 'orbit',  hue: 10,  rMul: 1.0, spin: 1.4, pulse: true },
  { name: 'OLAY UFKU YUTUCUSU',  shape: 'blackhole', pattern: 'wander', hue: 200, rMul: 1.3, spin: 2.5, pulse: true },
  { name: 'KOMUTA GEMİSİ',       shape: 'saucer',    pattern: 'charge', hue: 350, rMul: 1.25, dual: true, twin: { shape: 'orb', rMul: 0.5, hue: 350 } },
  { name: 'SON SAVUNMA KULELERİ', shape: 'cube',     pattern: 'zigzag', hue: 45,  rMul: 0.95, dual: true, spin: 0.6 },
  { name: 'VOLFAI KRALİÇESİ',    shape: 'queen',     pattern: 'charge', hue: 205, rMul: 1.35, pulse: true },
];

// 30 bölüm: ad, sanat teması, renk tonu
export const LEVELS = [
  { name: 'VOLFAI YÖRÜNGESİ',   art: 'planet',     hue: 200 },
  { name: 'KIZIL ÇÖL',          art: 'desert',     hue: 15 },
  { name: 'BUZ KUŞAĞI',         art: 'ice',        hue: 190 },
  { name: 'NEBULA GEÇİDİ',      art: 'nebula',     hue: 280 },
  { name: 'HALKALI DEV',        art: 'rings',      hue: 40 },
  { name: 'TERK EDİLMİŞ ŞEHİR', art: 'city',       hue: 160 },
  { name: 'LAV DENİZİ',         art: 'lava',       hue: 5 },
  { name: 'AY TÜNELLERİ',       art: 'moon',       hue: 220 },
  { name: 'ASTEROİT KUŞAĞI',    art: 'asteroids',  hue: 30 },
  { name: 'YEŞİL OKYANUS',      art: 'ocean',      hue: 140 },
  { name: 'FIRTINA GEZEGENİ',   art: 'storm',      hue: 250 },
  { name: 'KRİSTAL MAĞARA',     art: 'crystal',    hue: 300 },
  { name: 'ÇİFT GÜNEŞ',         art: 'twinsun',    hue: 50 },
  { name: 'KARA DELİK',         art: 'blackhole',  hue: 270 },
  { name: 'ANA GEMİ',           art: 'mothership', hue: 0 },
  { name: 'GÖLGE KUŞAĞI',       art: 'nebula',     hue: 330 },
  { name: 'DEMİR GEZEGEN',      art: 'asteroids',  hue: 20 },
  { name: 'KUTUP İSTASYONU',    art: 'ice',        hue: 210 },
  { name: 'PLAZMA DENİZİ',      art: 'lava',       hue: 290 },
  { name: 'GAZ DEVİ',           art: 'storm',      hue: 35 },
  { name: 'AYNA OKYANUSU',      art: 'ocean',      hue: 180 },
  { name: 'ZÜMRÜT ŞEHİR',       art: 'city',       hue: 120 },
  { name: 'ÇİFTE HALKA',        art: 'rings',      hue: 320 },
  { name: 'ÖLÜ YILDIZ',         art: 'moon',       hue: 60 },
  { name: 'SAFİR MAĞARA',       art: 'crystal',    hue: 230 },
  { name: 'ÜÇLÜ GÜNEŞ',         art: 'twinsun',    hue: 10 },
  { name: 'OLAY UFKU',          art: 'blackhole',  hue: 200 },
  { name: 'KOMUTA GEMİSİ',      art: 'mothership', hue: 350 },
  { name: 'SON SAVUNMA HATTI',  art: 'desert',     hue: 45 },
  { name: 'VOLFAI: EVE DÖNÜŞ',  art: 'home',       hue: 205 },
];

export function levelInfo(L) {
  const i = Math.max(1, Math.min(LEVEL_COUNT, L)) - 1;
  return { ...LEVELS[i], no: i + 1, parkurs: parkurCount(i + 1) };
}

/** Bölümdeki parkur sayısı: 1. bölümde 5, 30. bölümde 10, arada doğrusal artar. */
export function parkurCount(L) {
  const t = (L - 1) / (LEVEL_COUNT - 1);
  return Math.min(PARKUR_MAX, Math.max(PARKUR_MIN, PARKUR_MIN + Math.floor(t * (PARKUR_MAX - PARKUR_MIN) + 1e-9)));
}

/** Toplam parkur sayısı (ilerleme yüzdesi için). */
export function totalParkurs() { let n = 0; for (let L = 1; L <= LEVEL_COUNT; L++) n += parkurCount(L); return n; }

/**
 * Bir parkurun oyun parametreleri. Zorluk, bölüm ve parkur ile sürekli artar.
 * @param {number} L bölüm (1..30)
 * @param {number} p parkur (1..parkurCount(L))
 */
export function parkurDef(L, p, difficulty = 'acemi') {
  const D = DIFFICULTY[difficulty] || DIFFICULTY.acemi;
  const info = levelInfo(L);
  const n = info.parkurs;
  // küresel zorluk 0..1: bölüm ağırlıklı, parkur içi ince artış
  const d = Math.min(1, ((L - 1) + (p - 1) / n) / LEVEL_COUNT);
  const rng = mulberry32(L * 1000 + p * 17 + 3);
  const isBossParkur = p === n;                  // bölümün son parkuru: daha büyük boss, daha az kutu
  const lerp = (a, b) => a + (b - a) * d;
  const creature = CREATURES[(L - 1) % CREATURES.length];
  return {
    L, p, n, index: L * 100 + p, isBossParkur,
    name: info.name, art: info.art,
    hue: (info.hue + (p - 1) * 9) % 360,
    creature, difficulty, diff: D,
    boss: creature.shape,
    bossR: (lerp(4.5, 8) + (isBossParkur ? 1 : 0)) * creature.rMul,
    bossSpeed: (lerp(14, 36) + (isBossParkur ? 3 : 0)) * D.bossSpeed,
    bossHp: Math.round(lerp(40, 160) * (isBossParkur ? 1.5 : 1) * D.bossHp),
    smalls: Math.round(lerp(2, 10)) + (isBossParkur ? 1 : 0) + D.smalls,
    smallSpeed: lerp(10, 28) * D.smallSpeed,
    shoot: Math.max(D.shootMin, (L <= 2 ? 0 : lerp(0, 0.9)) * D.shoot),
    time: Math.round(lerp(150, 90) * D.time),
    missileFrom: D.missileFrom,
    fuseMult: D.fuse,
    reward: D.reward,
    blocks: isBossParkur ? 2 : Math.round(lerp(2, 6)),
    dualBoss: !!creature.dual,  // ikili yaratıklar bölüm boyunca çift gelir
  };
}

// --- Prosedürel sanat -------------------------------------------------------
function hsl(h, s, l, a = 1) { return `hsla(${h},${s}%,${l}%,${a})`; }

function stars(ctx, w, h, rng, n, bright = 1) {
  for (let i = 0; i < n; i++) {
    const x = rng() * w, y = rng() * h, r = rng() * 1.4 + 0.3;
    ctx.fillStyle = `rgba(255,255,255,${(0.3 + rng() * 0.7) * bright})`;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  }
}

function spaceBg(ctx, w, h, hue, rng) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, hsl(hue, 60, 6));
  g.addColorStop(1, hsl((hue + 40) % 360, 50, 12));
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  stars(ctx, w, h, rng, 220);
}

function planet(ctx, x, y, r, hue, rng, opts = {}) {
  const g = ctx.createRadialGradient(x - r * 0.35, y - r * 0.35, r * 0.1, x, y, r);
  g.addColorStop(0, hsl(hue, 70, 70));
  g.addColorStop(0.6, hsl(hue, 65, 45));
  g.addColorStop(1, hsl(hue, 60, 15));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.clip();
  const bands = opts.bands ?? 5;
  for (let i = 0; i < bands; i++) {
    ctx.fillStyle = hsl((hue + rng() * 40 - 20) % 360, 60, 35 + rng() * 30, 0.35);
    const by = y - r + (i + 0.5) * (2 * r / bands);
    ctx.beginPath();
    ctx.ellipse(x, by, r * 1.1, r * (0.08 + rng() * 0.08), 0, 0, Math.PI * 2);
    ctx.fill();
  }
  if (opts.continents) {
    for (let i = 0; i < 9; i++) {
      ctx.fillStyle = hsl((hue + 120) % 360, 50, 40, 0.7);
      const cx = x + (rng() - 0.5) * 1.6 * r, cy = y + (rng() - 0.5) * 1.6 * r;
      ctx.beginPath();
      for (let k = 0; k < 8; k++) {
        const a = (k / 8) * Math.PI * 2, rr = r * (0.12 + rng() * 0.2);
        ctx.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
      }
      ctx.closePath(); ctx.fill();
    }
  }
  const sh = ctx.createRadialGradient(x + r * 0.5, y + r * 0.4, r * 0.3, x, y, r * 1.05);
  sh.addColorStop(0, 'rgba(0,0,0,0)'); sh.addColorStop(1, 'rgba(0,0,0,0.75)');
  ctx.fillStyle = sh; ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
  ctx.restore();
  ctx.strokeStyle = hsl(hue, 80, 70, 0.5); ctx.lineWidth = r * 0.06;
  ctx.beginPath(); ctx.arc(x, y, r * 1.02, 0, Math.PI * 2); ctx.stroke();
}

function nebula(ctx, w, h, hue, rng, n = 14) {
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < n; i++) {
    const x = rng() * w, y = rng() * h, r = (0.15 + rng() * 0.3) * w;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, hsl((hue + rng() * 80 - 40 + 360) % 360, 80, 50, 0.22));
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g; ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  ctx.globalCompositeOperation = 'source-over';
}

function rings(ctx, x, y, r, hue, rng) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(-0.35); ctx.scale(1, 0.32);
  for (let i = 0; i < 6; i++) {
    ctx.strokeStyle = hsl((hue + i * 8) % 360, 50, 55 + i * 4, 0.55 - i * 0.05);
    ctx.lineWidth = r * (0.06 + rng() * 0.08);
    ctx.beginPath(); ctx.arc(0, 0, r * (1.45 + i * 0.16), 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
}

function city(ctx, w, h, hue, rng) {
  const horizon = h * 0.72;
  const g = ctx.createLinearGradient(0, horizon, 0, h);
  g.addColorStop(0, hsl(hue, 30, 12)); g.addColorStop(1, hsl(hue, 30, 4));
  ctx.fillStyle = g; ctx.fillRect(0, horizon, w, h - horizon);
  for (let x = 0; x < w; x += 6 + rng() * 10) {
    const bw = 8 + rng() * 16, bh = 30 + rng() * (h * 0.4);
    ctx.fillStyle = hsl(hue, 20, 8 + rng() * 10);
    ctx.fillRect(x, horizon - bh, bw, bh);
    for (let wy = horizon - bh + 4; wy < horizon - 4; wy += 7) for (let wx = x + 2; wx < x + bw - 2; wx += 5) {
      if (rng() < 0.45) { ctx.fillStyle = hsl((hue + 60) % 360, 90, 65, 0.8); ctx.fillRect(wx, wy, 2, 3); }
    }
  }
}

function terrain(ctx, w, h, hue, rng, { light = 30, rough = 1 } = {}) {
  let y0 = h * 0.6;
  for (let layer = 0; layer < 4; layer++) {
    ctx.fillStyle = hsl(hue, 45, light - layer * 6);
    ctx.beginPath(); ctx.moveTo(0, h);
    let y = y0 + layer * h * 0.09;
    for (let x = 0; x <= w; x += 8) {
      y += (rng() - 0.5) * 16 * rough;
      y = Math.max(h * 0.4, Math.min(h * 0.95, y));
      ctx.lineTo(x, y);
    }
    ctx.lineTo(w, h); ctx.closePath(); ctx.fill();
  }
}

function craters(ctx, w, h, hue, rng, n) {
  for (let i = 0; i < n; i++) {
    const x = rng() * w, y = h * 0.55 + rng() * h * 0.45, r = 4 + rng() * 18;
    ctx.fillStyle = hsl(hue, 20, 18); ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.5, 0, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = hsl(hue, 20, 45); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.ellipse(x, y - 1, r, r * 0.5, 0, Math.PI, Math.PI * 2); ctx.stroke();
  }
}

/** Bölüm/parkur arka plan sanatını (w x h piksel) üretir. def: {index, hue, art} */
export function drawLevelArt(ctx, w, h, def) {
  const rng = mulberry32(def.index * 7919 + 17);
  const hue = def.hue;
  spaceBg(ctx, w, h, hue, rng);
  switch (def.art) {
    case 'planet':   nebula(ctx, w, h, hue, rng, 6); planet(ctx, w * 0.55, h * 0.42, w * 0.3, hue, rng, { continents: true }); break;
    case 'desert':   planet(ctx, w * 0.75, h * 0.2, w * 0.12, 40, rng); terrain(ctx, w, h, hue, rng, { light: 38 }); break;
    case 'ice':      nebula(ctx, w, h, hue, rng, 5); terrain(ctx, w, h, hue, rng, { light: 70, rough: 2 }); break;
    case 'nebula':   nebula(ctx, w, h, hue, rng, 22); stars(ctx, w, h, rng, 120); break;
    case 'rings':    nebula(ctx, w, h, hue, rng, 4); planet(ctx, w * 0.5, h * 0.45, w * 0.26, hue, rng, { bands: 9 }); rings(ctx, w * 0.5, h * 0.45, w * 0.26, hue, rng); break;
    case 'city':     nebula(ctx, w, h, hue, rng, 5); planet(ctx, w * 0.3, h * 0.22, w * 0.1, (hue + 180) % 360, rng); city(ctx, w, h, hue, rng); break;
    case 'lava':     terrain(ctx, w, h, hue, rng, { light: 25, rough: 1.5 }); nebula(ctx, w, h * 0.6, 20, rng, 6); craters(ctx, w, h, 10, rng, 12); break;
    case 'moon':     planet(ctx, w * 0.7, h * 0.18, w * 0.14, 210, rng, { continents: true }); terrain(ctx, w, h, hue, rng, { light: 45, rough: 0.6 }); craters(ctx, w, h, hue, rng, 22); break;
    case 'asteroids': nebula(ctx, w, h, hue, rng, 6); for (let i = 0; i < 40; i++) { const r = 3 + rng() * 14; planet(ctx, rng() * w, rng() * h, r, hue, rng, { bands: 2 }); } break;
    case 'ocean':    planet(ctx, w * 0.5, h * 0.5, w * 0.42, hue, rng, { continents: true, bands: 3 }); break;
    case 'storm':    planet(ctx, w * 0.45, h * 0.4, w * 0.34, hue, rng, { bands: 14 }); nebula(ctx, w, h, hue, rng, 8); break;
    case 'crystal':  terrain(ctx, w, h, hue, rng, { light: 30, rough: 2.5 }); for (let i = 0; i < 30; i++) { const x = rng() * w, y = h * 0.5 + rng() * h * 0.5, s = 10 + rng() * 40; ctx.fillStyle = hsl((hue + rng() * 30) % 360, 70, 60, 0.8); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + s * 0.3, y - s); ctx.lineTo(x + s * 0.6, y); ctx.closePath(); ctx.fill(); } break;
    case 'twinsun':  planet(ctx, w * 0.3, h * 0.3, w * 0.16, 50, rng, { bands: 2 }); planet(ctx, w * 0.62, h * 0.24, w * 0.11, 20, rng, { bands: 2 }); terrain(ctx, w, h, hue, rng, { light: 40 }); break;
    case 'blackhole': { nebula(ctx, w, h, hue, rng, 10); const x = w * 0.5, y = h * 0.45;
      for (let i = 10; i > 0; i--) { ctx.strokeStyle = hsl((hue + i * 10) % 360, 90, 60, 0.6); ctx.lineWidth = 6; ctx.beginPath(); ctx.ellipse(x, y, w * 0.08 + i * 9, (w * 0.08 + i * 9) * 0.35, 0.4, 0, Math.PI * 2); ctx.stroke(); }
      ctx.fillStyle = '#000'; ctx.beginPath(); ctx.arc(x, y, w * 0.1, 0, Math.PI * 2); ctx.fill(); break; }
    case 'mothership': { nebula(ctx, w, h, hue, rng, 6);
      ctx.fillStyle = hsl(hue, 10, 30); ctx.beginPath(); ctx.ellipse(w * 0.5, h * 0.5, w * 0.42, h * 0.12, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = hsl(hue, 10, 45); ctx.beginPath(); ctx.ellipse(w * 0.5, h * 0.46, w * 0.2, h * 0.08, 0, 0, Math.PI * 2); ctx.fill();
      for (let i = 0; i < 24; i++) { ctx.fillStyle = hsl((hue + 180 + rng() * 40) % 360, 90, 60); ctx.beginPath(); ctx.arc(w * 0.1 + i * (w * 0.8 / 23), h * 0.53, 3, 0, Math.PI * 2); ctx.fill(); }
      break; }
    case 'home': default:
      nebula(ctx, w, h, hue, rng, 8); planet(ctx, w * 0.5, h * 0.5, w * 0.36, hue, rng, { continents: true, bands: 4 }); rings(ctx, w * 0.5, h * 0.5, w * 0.36, (hue + 30) % 360, rng); break;
  }
}
