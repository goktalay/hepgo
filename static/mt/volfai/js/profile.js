// VOLFAI - oyuncu profili: ilerleme, onur puanı, HEPCOIN kasası, yükseltmeler
import { LEVEL_COUNT, HONOR, UPGRADES, SHIPS, MISSILE } from './config.js';
import { parkurCount } from './levels.js';

export function emptyProfile() {
  return {
    v: 1,
    coins: 0,
    hiScore: 0,
    upgrades: { engine: 0, shield: 0, laser: 0, cells: 0, time: 0, magnet: 0, armor: 0, deflector: 0 },
    ship: 'monotros',
    ships: { monotros: true },
    // levels[L] = { parkurs: { [p]: { honor, best, special } } }
    levels: {},
    settings: { muted: false, vibrate: true, field: 'normal', spriteScale: 1.3, difficulty: 'acemi' },
    stats: { parkursCleared: 0, coinsEarned: 0, bossKills: 0, deaths: 0 },
    updatedAt: 0,
  };
}

export function normalizeProfile(p) {
  const e = emptyProfile();
  if (!p || typeof p !== 'object') return e;
  return {
    ...e, ...p,
    upgrades: { ...e.upgrades, ...(p.upgrades || {}) },
    ship: SHIPS[p.ship] ? p.ship : 'monotros',
    ships: { ...e.ships, ...(p.ships || {}) },
    levels: p.levels || {},
    settings: { ...e.settings, ...(p.settings || {}) },
    stats: { ...e.stats, ...(p.stats || {}) },
  };
}

/** Bir bölümde kazanılmış toplam onur (her parkurun en iyi sonucu). */
export function levelHonor(profile, L) {
  const lv = profile.levels[L];
  if (!lv) return 0;
  let s = 0;
  for (const k in lv.parkurs) s += lv.parkurs[k].honor || 0;
  return s;
}
export function levelHonorRequired(L) { return parkurCount(L) * HONOR.PER_PARKUR_REQUIRED; }
export function totalHonor(profile) { let s = 0; for (let L = 1; L <= LEVEL_COUNT; L++) s += levelHonor(profile, L); return s; }

/** Bölüm açık mı? 1 her zaman açık; L açık ⇔ L-1'in onur eşiği aşılmış. */
export function isLevelUnlocked(profile, L) {
  if (L <= 1) return true;
  if (L > LEVEL_COUNT) return false;
  return levelHonor(profile, L - 1) >= levelHonorRequired(L - 1);
}
export function highestUnlockedLevel(profile) {
  let h = 1;
  while (h < LEVEL_COUNT && isLevelUnlocked(profile, h + 1)) h++;
  return h;
}

export function parkurResult(profile, L, p) { return profile.levels[L]?.parkurs?.[p] || null; }
export function isParkurCleared(profile, L, p) { return !!parkurResult(profile, L, p); }
/** Parkur açık mı? Bölüm açıksa 1. parkur açık; p açık ⇔ p-1 bitirilmiş. */
export function isParkurUnlocked(profile, L, p) {
  if (!isLevelUnlocked(profile, L)) return false;
  if (p <= 1) return true;
  return isParkurCleared(profile, L, p - 1);
}
export function levelClearedCount(profile, L) {
  const lv = profile.levels[L]; if (!lv) return 0;
  return Object.keys(lv.parkurs).length;
}

/** Parkur sonucu onur puanı hesabı. */
export function computeHonor({ percent, special, deaths, reward = 1 }) {
  let h = HONOR.CLEAR;
  h += Math.min(20, Math.max(0, Math.floor(percent) - 80)) * HONOR.PER_PERCENT_OVER;
  if (special) h += HONOR.SPECIAL;
  if (deaths === 0) h += HONOR.NO_DEATH;
  return Math.round(h * reward);
}

/** Parkur bitişini profile işle; en iyi sonuç saklanır. Döner: {honor, improved, prevHonor} */
export function recordParkur(profile, L, p, { percent, special, deaths, score, reward = 1, difficulty = 'acemi' }) {
  const honor = computeHonor({ percent, special, deaths, reward });
  profile.levels[L] = profile.levels[L] || { parkurs: {} };
  const prev = profile.levels[L].parkurs[p];
  const prevHonor = prev ? prev.honor : 0;
  const improved = !prev || honor > prev.honor;
  if (!prev) profile.stats.parkursCleared++;
  if (special) profile.stats.bossKills++;
  profile.levels[L].parkurs[p] = {
    honor: Math.max(prevHonor, honor),
    best: Math.max(prev?.best || 0, score || 0),
    special: !!(prev?.special || special),
    percent: Math.max(prev?.percent || 0, Math.floor(percent)),
    difficulty: improved ? difficulty : (prev?.difficulty || difficulty),
  };
  profile.updatedAt = Date.now();
  return { honor, improved, prevHonor };
}

export function addCoins(profile, n) { profile.coins += n; profile.stats.coinsEarned += Math.max(0, n); profile.updatedAt = Date.now(); }

export function upgradeCost(profile, key) {
  const lvl = profile.upgrades[key] || 0;
  const costs = UPGRADES[key].costs;
  return lvl >= costs.length ? null : costs[lvl];
}
export function canBuy(profile, key) { const c = upgradeCost(profile, key); return c !== null && profile.coins >= c; }
export function buyUpgrade(profile, key) {
  const c = upgradeCost(profile, key);
  if (c === null || profile.coins < c) return false;
  profile.coins -= c; profile.upgrades[key]++; profile.updatedAt = Date.now();
  return true;
}

// ---- gemiler ----
export function currentShip(profile) { return SHIPS[profile.ship] || SHIPS.monotros; }
export function ownsShip(profile, id) { return !!profile.ships[id]; }
export function canBuyShip(profile, id) { const s = SHIPS[id]; return !!s && !ownsShip(profile, id) && profile.coins >= s.price; }
export function buyShip(profile, id) {
  if (!canBuyShip(profile, id)) return false;
  profile.coins -= SHIPS[id].price; profile.ships[id] = true; profile.ship = id; profile.updatedAt = Date.now();
  return true;
}
export function selectShip(profile, id) { if (!ownsShip(profile, id)) return false; profile.ship = id; profile.updatedAt = Date.now(); return true; }

/** Yükseltmelerin ve seçili geminin oyun içi etkileri. */
export function upgradeEffects(profile) {
  const u = profile.upgrades;
  const ship = currentShip(profile);
  return {
    ship,
    speedMult: (1 + 0.08 * u.engine) * ship.speed,
    armorMax: ship.armor + (u.armor || 0),
    deflectors: ship.deflectors + (u.deflector || 0),
    deflectorRegen: (u.deflector || 0) >= 3 ? 14 : MISSILE.REGEN_BASE,
    startShields: u.shield >= 3 ? 2 : (u.shield >= 1 ? 1 : 0),
    shieldRegen: u.shield >= 2 ? 30 : 0,       // sn sonra kalkan yenilenir
    laserBonus: 3 * u.laser,
    laserDmg: 1 + 0.5 * u.laser,
    extraLives: u.cells,
    extraTime: 15 * u.time,
    coinRate: 1 + 0.35 * u.magnet,
    coinValueMult: 1 + 0.5 * u.magnet,
  };
}

/** İki profili birleştir (yerel + sunucu): daha yüksek değerler kazanır. */
export function mergeProfiles(a, b) {
  a = normalizeProfile(a); b = normalizeProfile(b);
  const out = normalizeProfile(a.updatedAt >= b.updatedAt ? a : b);
  out.coins = Math.max(a.coins, b.coins);
  out.hiScore = Math.max(a.hiScore, b.hiScore);
  for (const k in out.upgrades) out.upgrades[k] = Math.max(a.upgrades[k] || 0, b.upgrades[k] || 0);
  out.ships = { ...a.ships, ...b.ships };
  if (!out.ships[out.ship]) out.ship = 'monotros';
  for (const src of [a, b]) for (const L in src.levels) {
    out.levels[L] = out.levels[L] || { parkurs: {} };
    for (const p in src.levels[L].parkurs) {
      const r = src.levels[L].parkurs[p], cur = out.levels[L].parkurs[p];
      if (!cur || r.honor > cur.honor) out.levels[L].parkurs[p] = { ...cur, ...r, honor: Math.max(cur?.honor || 0, r.honor) };
    }
  }
  return out;
}
