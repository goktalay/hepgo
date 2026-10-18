// VOLFAI - oyun durumu ve güncelleme mantığı
import { GRID_W, GRID_H, CELL, FIELD_SIZES, CLEAR_PERCENT, BASE_PLAYER_SPEED, SPEED_BOOST_MULT, FUSE_SPEED_RATIO, LIVES_START, POWERUPS, SCORE, COIN, MISSILE, TIMER } from './config.js';
import { Grid } from './grid.js';
import { parkurDef, parkurCount, mulberry32 } from './levels.js';
import { upgradeEffects, recordParkur, addCoins } from './profile.js';
import { DIR, DIR_VEC } from './input.js';

export const STATE = { TITLE: 'title', MENU: 'menu', INTRO: 'intro', PLAY: 'play', DYING: 'dying', CLEAR: 'clear', GAMEOVER: 'gameover', PAUSE: 'pause' };

export class Game {
  constructor(sfx, account) {
    this.sfx = sfx;
    this.account = account;
    this.grid = new Grid(GRID_W, GRID_H); // startParkur ayara göre yeniden boyutlandırır
    this.state = STATE.TITLE;
    this.events = [];
    this.rng = mulberry32(Date.now() & 0xffff);
    this.score = 0;
    this.lives = LIVES_START;
    this.stateTime = 0;
    this.gridVersion = 0;
    this.particles = []; this.texts = [];
    this.shake = 0;
    this.def = null;
    this.bosses = [];
    this.smalls = []; this.shots = []; this.beams = []; this.coins = []; this.missiles = [];
    this.powers = { S: 0, T: 0, L: 0 };
    this.shields = 0; this.armor = 0; this.deflectors = 0;
    this.fuse = { active: false, idx: 0 };
  }
  get profile() { return this.account.profile; }
  get hiScore() { return this.profile.hiScore; }

  emit(type, data = {}) { this.events.push({ type, ...data }); }
  setState(s) { this.state = s; this.stateTime = 0; this.emit('state', { state: s }); }
  togglePause() {
    if (this.state === STATE.PLAY) this.setState(STATE.PAUSE);
    else if (this.state === STATE.PAUSE) this.setState(STATE.PLAY);
  }
  toMenu() { this.def = null; this.setState(STATE.MENU); }

  // ---------------- parkur kurulumu ----------------
  startParkur(L, p) {
    const def = parkurDef(L, p, this.profile.settings.difficulty || 'acemi');
    const fx = upgradeEffects(this.profile);
    this.def = def; this.fx = fx;
    // oyun alanı çözünürlüğü (Ayarlar)
    const fs = FIELD_SIZES[this.profile.settings.field] || FIELD_SIZES.normal;
    if (this.grid.w !== fs.w || this.grid.h !== fs.h) { this.grid = new Grid(fs.w, fs.h); this.emit('gridsize'); }
    const GRID_W = this.grid.w, GRID_H = this.grid.h;
    this.L = L; this.p = p;
    this.score = 0;
    this.lives = Math.max(1, LIVES_START + fx.extraLives + (def.diff.lives || 0));
    this.deaths = 0;
    this.coinsRun = 0;
    this.grid.reset();
    this.rng = mulberry32(L * 1337 + p * 101 + 7);
    this.gridVersion++;
    this.timeLeft = def.time + fx.extraTime;
    this.hurry = false;
    this.particles = []; this.texts = []; this.shots = []; this.beams = []; this.coins = [];
    this.powers = { S: 0, T: 0, L: 0 };
    this.shields = fx.startShields;
    this.shieldRegenT = fx.shieldRegen;
    this.armor = fx.armorMax;
    this.deflectors = fx.deflectors;
    this.deflRegenT = fx.deflectorRegen;
    this.missiles = [];
    this.lastTick = -1;
    this.overtime = 0;
    this.superWeapon = false;
    this.allBlocksBonusGiven = false;
    this.laserCooldown = 0;
    this.coinT = this.coinDelay();

    for (let i = 0; i < def.blocks; i++) {
      for (let t = 0; t < 60; t++) {
        const size = 4;
        const x = 8 + Math.floor(this.rng() * (GRID_W - 16 - size));
        const y = 10 + Math.floor(this.rng() * (GRID_H - 20 - size));
        let ok = true;
        for (const b of this.grid.blocks) if (Math.abs(b.x - x) < 10 && Math.abs(b.y - y) < 10) ok = false;
        if (Math.abs(x - GRID_W / 2) < 10 && Math.abs(y - GRID_H / 2) < 12) ok = false;
        if (def.dualBoss && Math.abs(x - GRID_W / 2) < 10 && Math.abs(y - GRID_H / 4) < 12) ok = false;
        if (ok) { this.grid.addBlock(x, y, size); break; }
      }
    }

    this.player = { x: GRID_W >> 1, y: GRID_H - 1, dir: DIR.NONE, face: DIR.UP, drawing: false, trail: [], start: null, acc: 0, invuln: 2.0, idle: 0 };

    const cr = def.creature;
    this.bosses = [this.makeBoss(def, GRID_W / 2, GRID_H / 2, cr)];
    if (def.dualBoss) {
      const twin = cr.twin ? { ...cr, ...cr.twin, pattern: cr.twin.pattern || 'orbit' } : cr;
      const b2 = this.makeBoss(def, GRID_W / 2, GRID_H / 4, twin);
      b2.r *= cr.twin ? 1 : 0.8; b2.baseR = b2.r; b2.hp = b2.maxHp = Math.round(def.bossHp * 0.6);
      b2.phase = Math.PI; // zıt fazda dönsün
      this.bosses.push(b2);
    }

    this.smalls = [];
    for (let i = 0; i < def.smalls; i++) {
      const c = this.grid.randomEmptyCell(this.rng, 6);
      if (this.bosses.some(b => Math.hypot(c.x - b.x, c.y - b.y) < 12)) { i--; continue; }
      const ang = this.rng() * Math.PI * 2;
      this.smalls.push({ x: c.x + 0.5, y: c.y + 0.5, vx: Math.cos(ang) * def.smallSpeed, vy: Math.sin(ang) * def.smallSpeed, speed: def.smallSpeed, alive: true, spin: this.rng() * 6 });
    }
    this.fuse = { active: false, idx: 0 };
    this.setState(STATE.INTRO);
    this.emit('parkur', { def });
    this.emit('powers'); this.emit('lives'); this.emit('coins');
  }

  makeBoss(def, x, y, cr) {
    const a = this.rng() * Math.PI * 2;
    const r = def.bossR * (cr.rMul / def.creature.rMul);
    const b = {
      x, y, r, baseR: r, type: cr.shape, cr, hue: cr.hue, pattern: cr.pattern,
      vx: Math.cos(a) * def.bossSpeed, vy: Math.sin(a) * def.bossSpeed,
      speed: def.bossSpeed, turnT: 1.5, dashT: 0, shootT: 2 + this.rng() * 3,
      hp: def.bossHp, maxHp: def.bossHp, hitFlash: 0, angle: 0, alive: true,
      phase: 0, orbitW: 1.6, chargeT: 2 + this.rng() * 2, segs: [], hist: [],
    };
    if (cr.serpent) for (let i = 0; i < cr.serpent; i++) b.segs.push({ x, y });
    return b;
  }

  coinDelay() { return (COIN.SPAWN_MIN + this.rng() * (COIN.SPAWN_MAX - COIN.SPAWN_MIN)) / (this.fx?.coinRate || 1); }

  // ---------------- ana güncelleme ----------------
  update(dt, input) {
    dt = Math.min(dt, 0.05);
    this.stateTime += dt;
    this.updateFx(dt);
    switch (this.state) {
      case STATE.INTRO: if (this.stateTime > 2.2) this.setState(STATE.PLAY); break;
      case STATE.PLAY: this.updatePlay(dt, input); break;
      case STATE.DYING: if (this.stateTime > 1.3) this.afterDeath(); break;
      default: break;
    }
  }

  updatePlay(dt, input) {
    const p = this.player;
    if (this.timeLeft > 0) {
      this.timeLeft -= dt;
      const sec = Math.ceil(this.timeLeft);
      if (this.timeLeft <= TIMER.WARN_AT && sec !== this.lastTick) {
        this.lastTick = sec;
        if (sec > 0) { this.sfx.tick(sec <= 3); this.emit('timewarn', { sec }); }
      }
      if (this.timeLeft <= 0) {
        this.timeLeft = 0;
        this.overtime++;
        this.hurry = true; this.sfx.hurry(); this.emit('hurry');
        this.floatText(this.grid.w / 2, this.grid.h / 2 - 6, 'SÜRE DOLDU!', '#ff5d5d', 2.2);
        this.takeHit('timeout', true);
        if (this.state === STATE.PLAY) { this.timeLeft = TIMER.OVERTIME; this.lastTick = -1; this.floatText(this.grid.w / 2, this.grid.h / 2 + 4, `+${TIMER.OVERTIME} SN EK SÜRE`, '#ffd23f', 2.2); }
        else this.pendingOvertime = true;
      }
    }
    // saptırıcı dolumu
    if (this.deflectors < this.fx.deflectors) {
      this.deflRegenT -= dt;
      if (this.deflRegenT <= 0) { this.deflectors++; this.deflRegenT = this.fx.deflectorRegen; this.floatText(p.x, p.y - 3, 'SAPTIRICI HAZIR', '#b48cff', 1.0); this.emit('powers'); }
    }
    for (const k of ['S', 'T', 'L']) if (this.powers[k] > 0) { this.powers[k] -= dt; if (this.powers[k] <= 0) { this.powers[k] = 0; if (k === 'L') this.superWeapon = false; this.emit('powers'); } }
    if (p.invuln > 0) p.invuln -= dt;
    if (this.laserCooldown > 0) this.laserCooldown -= dt;
    // kalkan yenilenmesi (yükseltme)
    if (this.fx.shieldRegen && this.shields < Math.max(1, this.fx.startShields)) {
      this.shieldRegenT -= dt;
      if (this.shieldRegenT <= 0) { this.shields++; this.shieldRegenT = this.fx.shieldRegen; this.floatText(p.x, p.y - 3, 'KALKAN YENİLENDİ', '#9bff8a', 1.2); this.emit('powers'); }
    }

    this.updatePlayer(dt, input);
    if (this.state !== STATE.PLAY) return;
    const frozen = this.powers.T > 0;
    const spd = this.hurry ? 1.6 : 1;
    if (!frozen) {
      for (const b of this.bosses) this.updateBoss(b, dt * spd);
      if (this.state !== STATE.PLAY) return;
      this.updateSmalls(dt * spd);
      this.updateShots(dt * spd);
      this.updateMissiles(dt * spd);
    }
    this.updateBeams(dt);
    this.updateFuse(dt);
    this.updateCoins(dt);
    if ((input.fire || input.keyFire) && this.powers.L > 0 && this.laserCooldown <= 0) this.fireLaser();
  }

  // ---------------- oyuncu ----------------
  playerSpeed() { return BASE_PLAYER_SPEED * this.fx.speedMult * (this.powers.S > 0 ? SPEED_BOOST_MULT : 1); }
  isSafe() { return !this.player.drawing; }

  updatePlayer(dt, input) {
    const p = this.player;
    const want = input.primary;
    if (want === DIR.NONE) { p.acc = 0; if (p.drawing) p.idle += dt; return; }
    p.acc += this.playerSpeed() * dt;
    let moved = false;
    while (p.acc >= 1) {
      p.acc -= 1;
      if (this.tryStep(input.primary) || (input.secondary && this.tryStep(input.secondary))) { moved = true; if (this.state !== STATE.PLAY) return; }
      else { p.acc = 0; break; }
    }
    if (moved) p.idle = 0; else if (p.drawing) p.idle += dt;
  }

  tryStep(dir) {
    const p = this.player, g = this.grid;
    const [dx, dy] = DIR_VEC[dir];
    const nx = p.x + dx, ny = p.y + dy;
    if (!g.inBounds(nx, ny)) return false;
    const v = g.get(nx, ny);
    if (!p.drawing) {
      if (v === CELL.CLAIMED) {
        if (!g.isWalkableEdge(nx, ny)) return false;
        p.x = nx; p.y = ny; p.face = dir; return true;
      }
      if (v === CELL.EMPTY) {
        p.drawing = true; p.start = { x: p.x, y: p.y }; p.trail = [];
        this.fuse.active = false;
        this.emit('safe', { safe: false });
        return this.extend(nx, ny, dir);
      }
      return false;
    }
    if (v === CELL.EMPTY) {
      if (!g.canExtendTrail(nx, ny, p.x, p.y)) return false;
      return this.extend(nx, ny, dir);
    }
    if (v === CELL.CLAIMED) { p.x = nx; p.y = ny; p.face = dir; this.closeTrail(); return true; }
    return false;
  }

  extend(nx, ny, dir) {
    const p = this.player;
    this.grid.set(nx, ny, CELL.TRAIL);
    p.trail.push([nx, ny]);
    p.x = nx; p.y = ny; p.face = dir;
    this.emit('trail', { x: nx, y: ny });
    this.pickCoinAt(nx, ny);
    if (this.enemyAtCell(nx, ny)) { this.die(); return true; }
    return true;
  }

  enemyAtCell(x, y) {
    for (const b of this.bosses) if (b.alive && Math.hypot(b.x - (x + 0.5), b.y - (y + 0.5)) < b.r + 0.4) return true;
    for (const s of this.smalls) if (s.alive && Math.abs(s.x - (x + 0.5)) < 1 && Math.abs(s.y - (y + 0.5)) < 1) return true;
    return false;
  }

  closeTrail() {
    const p = this.player, g = this.grid;
    const trail = p.trail;
    const seeds = this.bosses.filter(b => b.alive).map(b => ({ x: b.x, y: b.y }));
    const res = g.closeTrail(trail, seeds);
    p.drawing = false; p.trail = []; p.idle = 0;
    this.fuse.active = false;
    this.gridVersion++;
    this.emit('safe', { safe: true });

    let chain = 0;
    for (const s of this.smalls) {
      if (!s.alive) continue;
      const cx = Math.floor(s.x), cy = Math.floor(s.y);
      if (res.filledRegion[g.idx(cx, cy)] || !g.isEmpty(cx, cy)) {
        s.alive = false; chain++;
        const pts = SCORE.SMALL_ENEMY * Math.pow(2, chain - 1);
        this.addScore(pts); this.floatText(s.x, s.y, `${pts}`, '#ffd23f');
        this.burst(s.x, s.y, '#ff8a5d', 14);
        this.sfx.enemyDie();
      }
    }
    this.shots = this.shots.filter(sh => g.isEmpty(Math.floor(sh.x), Math.floor(sh.y)));
    this.missiles = this.missiles.filter(m => g.isEmpty(Math.floor(m.x), Math.floor(m.y)));
    // kuşatılan coin'ler toplanır
    for (const c of this.coins) if (!g.isEmpty(Math.floor(c.x), Math.floor(c.y))) this.collectCoin(c);
    this.coins = this.coins.filter(c => !c.taken);

    const frac = res.claimedCells / Math.max(1, g.interiorTotal);
    let pts = res.claimedCells * SCORE.PER_CELL;
    const big = frac >= SCORE.BIG_AREA_THRESHOLD;
    if (big) { pts *= SCORE.BIG_AREA_MULT; this.floatText(p.x, p.y - 4, 'BÜYÜK ALAN x2!', '#5de4ff', 1.6); this.shake = 0.3; }
    this.addScore(pts);
    this.sfx.claim(big);
    this.emit('percent');

    for (const b of res.newlyCaptured) this.grantPower(b);
    if (g.blocks.length && g.blocks.every(b => b.captured) && !this.allBlocksBonusGiven) {
      this.allBlocksBonusGiven = true;
      this.addScore(SCORE.ALL_BLOCKS);
      this.superWeapon = true; this.powers.L = 20 + this.fx.laserBonus;
      this.floatText(this.grid.w / 2, this.grid.h / 2, 'SÜPER SİLAH!', '#ff5d8f', 2.4);
      this.sfx.power(); this.emit('powers');
    }
    if (g.percent() >= CLEAR_PERCENT) this.parkurClear(false);
  }

  grantPower(block) {
    const keys = Object.keys(POWERUPS);
    const total = keys.reduce((a, k) => a + POWERUPS[k].weight, 0);
    let r = this.rng() * total, pick = 'B';
    for (const k of keys) { r -= POWERUPS[k].weight; if (r <= 0) { pick = k; break; } }
    block.letter = pick;
    const cx = block.x + block.size / 2, cy = block.y + block.size / 2;
    const pu = POWERUPS[pick];
    switch (pick) {
      case 'S': case 'T': this.powers[pick] = Math.max(this.powers[pick], pu.duration); break;
      case 'L': this.powers.L = Math.max(this.powers.L, pu.duration + this.fx.laserBonus); break;
      case 'P': this.shields = Math.min(3, this.shields + 1); break;
      case 'E': this.lives++; this.emit('lives'); break;
      case 'B': this.addScore(SCORE.BONUS_BOX); this.earnCoins(5 + Math.floor(this.rng() * 6), cx, cy); break;
    }
    this.floatText(cx, cy - 3, pu.name, pu.color, 1.8);
    this.burst(cx, cy, pu.color, 20);
    this.sfx.power();
    this.emit('powers');
  }

  // ---------------- HEPCOIN ----------------
  updateCoins(dt) {
    this.coinT -= dt;
    if (this.coinT <= 0) {
      this.coinT = this.coinDelay();
      if (this.coins.length < COIN.MAX_ON_FIELD) {
        const c = this.grid.randomEmptyCell(this.rng, 4);
        const far = this.bosses.every(b => Math.hypot(c.x - b.x, c.y - b.y) > b.r + 3);
        if (far) {
          const v = COIN.VALUES[Math.floor(this.rng() * COIN.VALUES.length)];
          this.coins.push({ x: c.x, y: c.y, value: Math.max(1, Math.round(v * this.fx.coinValueMult)), life: COIN.LIFETIME, spin: 0, taken: false });
          this.emit('coinspawn');
        }
      }
    }
    for (const c of this.coins) { c.life -= dt; c.spin += dt * 4; }
    this.coins = this.coins.filter(c => c.life > 0 && !c.taken);
  }
  pickCoinAt(x, y) { for (const c of this.coins) if (!c.taken && c.x === x && c.y === y) this.collectCoin(c); }
  collectCoin(c) { if (c.taken) return; c.taken = true; this.earnCoins(c.value, c.x + 0.5, c.y + 0.5); }
  earnCoins(n, x, y) {
    n = Math.max(1, Math.round(n * (this.def?.reward || 1)));
    this.coinsRun += n;
    addCoins(this.profile, n);
    this.account.save();
    this.floatText(x, y - 2, `+${n} HEPCOIN`, '#ffcc33', 1.2);
    this.burst(x, y, '#ffcc33', 10);
    this.sfx.coin();
    this.emit('coins');
  }

  // ---------------- boss ----------------
  bossCollides(x, y, r) {
    const n = 12;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const cx = Math.floor(x + Math.cos(a) * r), cy = Math.floor(y + Math.sin(a) * r);
      const v = this.grid.get(cx, cy);
      if (v !== CELL.EMPTY) return { cx, cy, v };
    }
    return null;
  }

  updateBoss(b, dt) {
    if (!b.alive) return;
    b.angle += dt * (b.cr.spin || 1.5);
    b.phase += dt;
    if (b.hitFlash > 0) b.hitFlash -= dt;
    if (b.cr.pulse) b.r = b.baseR * (1 + 0.18 * Math.sin(b.phase * 2.2));
    const p = this.player;
    const norm = (sp) => { const l = Math.hypot(b.vx, b.vy) || 1; b.vx = b.vx / l * sp; b.vy = b.vy / l * sp; };
    switch (b.pattern) {
      case 'bounce': // düz çizgiler, keskin sekmeler, hep tam hız
        norm(b.speed * 1.15);
        break;
      case 'zigzag': // kısa aralıklarla 90° dönüşler
        b.turnT -= dt;
        if (b.turnT <= 0) { b.turnT = 0.45 + this.rng() * 0.6; const ang = Math.atan2(b.vy, b.vx) + (this.rng() < 0.5 ? 1 : -1) * Math.PI / 2; b.vx = Math.cos(ang) * b.speed; b.vy = Math.sin(ang) * b.speed; }
        break;
      case 'orbit': { // sürüklenen bir merkez etrafında daire
        const ang = Math.atan2(b.vy, b.vx) + b.orbitW * dt;
        b.vx = Math.cos(ang) * b.speed; b.vy = Math.sin(ang) * b.speed;
        b.turnT -= dt; if (b.turnT <= 0) { b.turnT = 2 + this.rng() * 3; if (this.rng() < 0.4) b.orbitW = -b.orbitW; }
        break; }
      case 'charge': // yavaş dolaşır, oyuncu çizerken ona doğru hamle yapar
        b.chargeT -= dt;
        if (b.dashT > 0) { b.dashT -= dt; if (b.dashT <= 0) norm(b.speed * 0.7); }
        else if (b.chargeT <= 0) {
          b.chargeT = 2.2 + this.rng() * 2.5;
          if (p.drawing) { const ang = Math.atan2((p.y + 0.5) - b.y, (p.x + 0.5) - b.x); b.vx = Math.cos(ang) * b.speed * 2.6; b.vy = Math.sin(ang) * b.speed * 2.6; b.dashT = 0.75; this.floatText(b.x, b.y - b.r - 2, '!', '#ff5d5d', 0.5); }
          else { const ang = this.rng() * Math.PI * 2; b.vx = Math.cos(ang) * b.speed * 0.7; b.vy = Math.sin(ang) * b.speed * 0.7; }
        }
        break;
      default: // wander: Volfied benzeri yarı rastgele
        b.turnT -= dt;
        if (b.turnT <= 0) {
          b.turnT = 0.8 + this.rng() * 2.2;
          const ang = Math.atan2(b.vy, b.vx) + (this.rng() - 0.5) * 2.4;
          const sp = b.speed * (b.dashT > 0 ? 2 : 1);
          b.vx = Math.cos(ang) * sp; b.vy = Math.sin(ang) * sp;
          if (this.rng() < 0.25) { b.dashT = 0.6; b.vx *= 2; b.vy *= 2; }
        }
        if (b.dashT > 0) { b.dashT -= dt; if (b.dashT <= 0) { b.vx *= 0.5; b.vy *= 0.5; } }
    }
    let nx = b.x + b.vx * dt;
    let hit = this.bossCollides(nx, b.y, b.r);
    if (hit) { b.vx = -b.vx; nx = b.x; if (hit.v === CELL.TRAIL) this.igniteFuse(hit.cx, hit.cy); }
    b.x = nx;
    let ny = b.y + b.vy * dt;
    hit = this.bossCollides(b.x, ny, b.r);
    if (hit) { b.vy = -b.vy; ny = b.y; if (hit.v === CELL.TRAIL) this.igniteFuse(hit.cx, hit.cy); }
    b.y = ny;
    b.x = Math.max(b.r + 1, Math.min(this.grid.w - 1 - b.r, b.x));
    b.y = Math.max(b.r + 1, Math.min(this.grid.h - 1 - b.r, b.y));
    if (b.segs.length) {
      b.hist.unshift([b.x, b.y]); if (b.hist.length > 400) b.hist.length = 400;
      const gap = Math.max(1, Math.round(b.r * 1.6 / Math.max(0.05, Math.hypot(b.vx, b.vy) * dt)));
      for (let i = 0; i < b.segs.length; i++) {
        const h = b.hist[Math.min(b.hist.length - 1, (i + 1) * gap)]; if (!h) continue;
        b.segs[i].x = h[0]; b.segs[i].y = h[1];
        const sr = b.r * (0.8 - i * 0.04);
        const cx = Math.floor(b.segs[i].x), cy = Math.floor(b.segs[i].y);
        if (this.grid.get(cx, cy) === CELL.TRAIL) this.igniteFuse(cx, cy);
        if (p.drawing && Math.hypot(b.segs[i].x - (p.x + 0.5), b.segs[i].y - (p.y + 0.5)) < sr + 0.5) { this.takeHit('serpent'); if (this.state !== STATE.PLAY) return; }
      }
    }

    if (this.def.shoot > 0) {
      b.shootT -= dt;
      if (b.shootT <= 0) {
        b.shootT = (1.2 + this.rng() * 2.5) / this.def.shoot;
        const ang = Math.atan2((p.y + 0.5) - b.y, (p.x + 0.5) - b.x) + (this.rng() - 0.5) * 0.3;
        const sp = 22 + this.L * 0.8;
        if (this.L >= this.def.missileFrom && p.drawing && this.rng() < Math.min(0.75, 0.25 + this.L * 0.02)) this.fireMissile(b, ang);
        else this.shots.push({ x: b.x + Math.cos(ang) * (b.r + 0.5), y: b.y + Math.sin(ang) * (b.r + 0.5), vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, life: 6 });
      }
    }
    if (p.drawing && Math.hypot(b.x - (p.x + 0.5), b.y - (p.y + 0.5)) < b.r + 0.6) this.die();
  }

  // ---------------- küçük düşmanlar ----------------
  updateSmalls(dt) {
    const g = this.grid, p = this.player;
    for (const s of this.smalls) {
      if (!s.alive) continue;
      s.spin += dt * 6;
      let nx = s.x + s.vx * dt;
      let v = g.get(Math.floor(nx), Math.floor(s.y));
      if (v !== CELL.EMPTY) { if (v === CELL.TRAIL) this.igniteFuse(Math.floor(nx), Math.floor(s.y)); s.vx = -s.vx; nx = s.x; }
      s.x = nx;
      let ny = s.y + s.vy * dt;
      v = g.get(Math.floor(s.x), Math.floor(ny));
      if (v !== CELL.EMPTY) { if (v === CELL.TRAIL) this.igniteFuse(Math.floor(s.x), Math.floor(ny)); s.vy = -s.vy; ny = s.y; }
      s.y = ny;
      if (this.rng() < dt * 0.4) { const a = Math.atan2(s.vy, s.vx) + (this.rng() - 0.5) * 1.2; s.vx = Math.cos(a) * s.speed; s.vy = Math.sin(a) * s.speed; }
      if (p.drawing && Math.abs(s.x - (p.x + 0.5)) < 1 && Math.abs(s.y - (p.y + 0.5)) < 1) { this.die(); return; }
    }
  }

  // ---------------- güdümlü füzeler & saptırıcılar ----------------
  fireMissile(b, ang) {
    const t = Math.min(1, Math.max(0, this.L - this.def.missileFrom) / 20);
    const sp = MISSILE.SPEED_MIN + (MISSILE.SPEED_MAX - MISSILE.SPEED_MIN) * t;
    // oyuncunun arkasından gelsin: hedefin ters yönünden değil, boss'tan çıkar ama ilk yönü oyuncunun gidiş yönünün tersi
    const [fdx, fdy] = DIR_VEC[this.player.face] || [0, -1];
    const a0 = Math.atan2(-fdy, -fdx) + (this.rng() - 0.5) * 0.8;
    this.missiles.push({ x: b.x + Math.cos(ang) * (b.r + 0.5), y: b.y + Math.sin(ang) * (b.r + 0.5), ang: a0, speed: sp, turn: MISSILE.TURN_MIN + (MISSILE.TURN_MAX - MISSILE.TURN_MIN) * t, life: MISSILE.LIFE, trail: [] });
    this.sfx.missile();
  }

  updateMissiles(dt) {
    const g = this.grid, p = this.player;
    const px = p.x + 0.5, py = p.y + 0.5;
    for (const m of this.missiles) {
      m.life -= dt;
      // güdüm: oyuncu çiziyorsa oyuncuya, değilse hattın başına/boşluğa doğru sürüklen
      if (p.drawing) {
        const want = Math.atan2(py - m.y, px - m.x);
        let d = want - m.ang; while (d > Math.PI) d -= Math.PI * 2; while (d < -Math.PI) d += Math.PI * 2;
        m.ang += Math.max(-m.turn * dt, Math.min(m.turn * dt, d));
      }
      m.x += Math.cos(m.ang) * m.speed * dt; m.y += Math.sin(m.ang) * m.speed * dt;
      m.trail.push([m.x, m.y]); if (m.trail.length > 8) m.trail.shift();
      const cx = Math.floor(m.x), cy = Math.floor(m.y);
      const v = g.get(cx, cy);
      if (v === CELL.TRAIL) { this.igniteFuse(cx, cy); m.life = 0; this.burst(m.x, m.y, '#ff5d5d', 10); continue; }
      if (v !== CELL.EMPTY) { m.life = 0; this.burst(m.x, m.y, '#8899aa', 6); continue; }
      const dist = Math.hypot(m.x - px, m.y - py);
      // saptırıcı: menzile giren füzeyi imha eder (yalnız çizim halindeyken tehdit var)
      if (p.drawing && this.deflectors > 0 && dist < MISSILE.DEFLECT_RANGE) {
        this.deflectors--; if (this.deflRegenT <= 0) this.deflRegenT = this.fx.deflectorRegen;
        m.life = 0; this.burst(m.x, m.y, '#b48cff', 18); this.deflectFx = { x: px, y: py, t: 0.35 };
        this.floatText(px, py - 3, 'SAPTIRILDI', '#b48cff', 0.9); this.sfx.deflect(); this.emit('powers');
        continue;
      }
      if (p.drawing && dist < 0.9) { m.life = 0; this.burst(m.x, m.y, '#ff5d5d', 16); this.takeHit('missile'); if (this.state !== STATE.PLAY) return; }
    }
    this.missiles = this.missiles.filter(m => m.life > 0);
    if (this.deflectFx) { this.deflectFx.t -= dt; if (this.deflectFx.t <= 0) this.deflectFx = null; }
  }

  // ---------------- boss mermileri ----------------
  updateShots(dt) {
    const g = this.grid, p = this.player;
    for (const sh of this.shots) {
      sh.x += sh.vx * dt; sh.y += sh.vy * dt; sh.life -= dt;
      const cx = Math.floor(sh.x), cy = Math.floor(sh.y);
      const v = g.get(cx, cy);
      if (v === CELL.TRAIL) { this.igniteFuse(cx, cy); sh.life = 0; this.burst(sh.x, sh.y, '#ff5d5d', 6); }
      else if (v !== CELL.EMPTY) { sh.life = 0; this.burst(sh.x, sh.y, '#8899aa', 4); }
      if (p.drawing && cx === p.x && cy === p.y) { this.die(); return; }
    }
    this.shots = this.shots.filter(s => s.life > 0);
  }

  // ---------------- fitil ----------------
  igniteFuse(cx, cy) {
    const p = this.player;
    if (!p.drawing) return;
    if (cx === p.x && cy === p.y) { this.die(); return; }
    let idx = -1;
    for (let i = p.trail.length - 1; i >= 0; i--) if (p.trail[i][0] === cx && p.trail[i][1] === cy) { idx = i; break; }
    if (idx < 0) return;
    if (!this.fuse.active || idx > this.fuse.idx) { this.fuse.active = true; this.fuse.idx = idx; this.sfx.fuse(); }
  }

  updateFuse(dt) {
    const p = this.player, f = this.fuse;
    if (!p.drawing) { f.active = false; return; }
    if (!f.active && p.idle > 0.6 && p.trail.length > 1) { f.active = true; f.idx = 0; this.sfx.fuse(); }
    if (!f.active) return;
    f.idx += this.playerSpeed() * FUSE_SPEED_RATIO * this.def.fuseMult * dt;
    if (Math.floor(f.idx) % 4 === 0 && this.rng() < 0.5) { const c = p.trail[Math.min(p.trail.length - 1, Math.floor(f.idx))]; this.spark(c[0] + 0.5, c[1] + 0.5); }
    if (f.idx >= p.trail.length - 1) this.die();
  }

  // ---------------- lazer ----------------
  nearestBoss(x, y) {
    let best = null, bd = Infinity;
    for (const b of this.bosses) if (b.alive) { const d = Math.hypot(b.x - x, b.y - y); if (d < bd) { bd = d; best = b; } }
    return best;
  }
  fireLaser() {
    const p = this.player;
    this.laserCooldown = this.superWeapon ? 0.12 : 0.2;
    const b = this.nearestBoss(p.x + 0.5, p.y + 0.5);
    let ang;
    if (b) ang = Math.atan2(b.y - (p.y + 0.5), b.x - (p.x + 0.5));
    else { const [dx, dy] = DIR_VEC[p.face] || [0, -1]; ang = Math.atan2(dy, dx); }
    const sp = 110;
    this.beams.push({ x: p.x + 0.5, y: p.y + 0.5, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, life: 1.5, dmg: (this.superWeapon ? 2 : 1) * this.fx.laserDmg, born: true });
    this.sfx.laser();
  }

  updateBeams(dt) {
    const g = this.grid;
    for (const be of this.beams) {
      const steps = 3;
      for (let k = 0; k < steps && be.life > 0; k++) {
        be.x += be.vx * dt / steps; be.y += be.vy * dt / steps;
        const cx = Math.floor(be.x), cy = Math.floor(be.y);
        const v = g.get(cx, cy);
        if (v === CELL.EMPTY) be.born = false;
        else if (!be.born) { be.life = 0; this.burst(be.x, be.y, '#ff5d8f', 3); break; }
        for (const s of this.smalls) if (s.alive && Math.hypot(s.x - be.x, s.y - be.y) < 1.6) {
          s.alive = false; be.life = 0; this.addScore(SCORE.SMALL_ENEMY); this.floatText(s.x, s.y, `${SCORE.SMALL_ENEMY}`, '#ffd23f'); this.burst(s.x, s.y, '#ff8a5d', 14); this.sfx.enemyDie();
        }
        for (const b of this.bosses) if (b.alive && Math.hypot(b.x - be.x, b.y - be.y) < b.r + 0.5) {
          be.life = 0; b.hp -= be.dmg; b.hitFlash = 0.12; this.addScore(SCORE.BOSS_HIT); this.sfx.bossHit(); this.burst(be.x, be.y, '#ffffff', 5);
          if (b.hp <= 0) {
            b.alive = false; this.burst(b.x, b.y, '#ffd23f', 60); this.shake = 0.8;
            this.earnCoins(10 + this.L, b.x, b.y);
            if (!this.bosses.some(o => o.alive)) { this.parkurClear(true); return; }
            this.floatText(b.x, b.y - 4, 'BOSS YOK EDİLDİ!', '#ffd23f', 1.8);
          }
        }
      }
      be.life -= dt;
    }
    this.beams = this.beams.filter(b => b.life > 0);
  }

  // ---------------- ölüm / parkur sonu ----------------
  die() { this.takeHit('contact'); }

  /** Darbe al: önce P kalkanı, sonra gövde zırhı, sonra can. force: dokunulmazlığı yok sayar (süre dolması). */
  takeHit(source = 'contact', force = false) {
    const p = this.player;
    if (this.state !== STATE.PLAY || (p.invuln > 0 && !force)) return;
    if (this.shields > 0) {
      this.shields--; p.invuln = 1.5; this.emit('powers');
      this.floatText(p.x, p.y - 3, 'KALKAN!', '#9bff8a', 1.2); this.burst(p.x + 0.5, p.y + 0.5, '#9bff8a', 24); this.sfx.bossHit();
      this.fuse.active = false; p.idle = 0;
      return;
    }
    if (this.armor > 0) {
      this.armor--; p.invuln = 1.5; this.shake = 0.25; this.emit('powers');
      this.floatText(p.x, p.y - 3, `ZIRH ${this.armor}/${this.fx.armorMax}`, '#ffa94d', 1.2); this.burst(p.x + 0.5, p.y + 0.5, '#ffa94d', 20); this.sfx.hit();
      if (this.profile.settings.vibrate && navigator.vibrate) { try { navigator.vibrate(40); } catch (e) { /* yok say */ } }
      this.fuse.active = false; p.idle = 0;
      return;
    }
    this.burst(p.x + 0.5, p.y + 0.5, '#5de4ff', 40);
    this.shake = 0.6;
    this.sfx.die();
    if (this.profile.settings.vibrate && navigator.vibrate) { try { navigator.vibrate([80, 40, 120]); } catch (e) { /* yok say */ } }
    this.setState(STATE.DYING);
  }

  afterDeath() {
    const p = this.player, g = this.grid;
    if (p.drawing) { g.clearTrail(p.trail); p.trail = []; p.drawing = false; }
    this.emit('safe', { safe: true });
    this.gridVersion++;
    this.fuse.active = false;
    this.lives--; this.deaths++;
    this.profile.stats.deaths++;
    this.emit('lives');
    if (this.lives < 0) { this.gameOver(); return; }
    if (p.start) { p.x = p.start.x; p.y = p.start.y; }
    p.invuln = 2.5; p.idle = 0; p.acc = 0;
    this.shots = []; this.missiles = [];
    this.armor = this.fx.armorMax;
    if (this.pendingOvertime) { this.pendingOvertime = false; this.timeLeft = TIMER.OVERTIME; this.lastTick = -1; }
    this.emit('powers');
    this.setState(STATE.PLAY);
  }

  parkurClear(special) {
    const g = this.grid;
    const pct = special ? 100 : g.percent();
    const over = Math.max(0, Math.floor(pct) - CLEAR_PERCENT);
    const bonus = {
      special: special ? SCORE.SPECIAL_CLEAR : 0,
      over: over * SCORE.PER_PERCENT_OVER,
      time: Math.floor(this.timeLeft) * SCORE.PER_SECOND_LEFT,
      percent: pct,
    };
    this.addScore(bonus.special + bonus.over + bonus.time);
    if (special) {
      for (let i = 0; i < g.cells.length; i++) if (g.cells[i] === CELL.EMPTY || g.cells[i] === CELL.TRAIL) g.cells[i] = CELL.CLAIMED;
      g.claimedInterior = g.interiorTotal;
    }
    this.player.drawing = false; this.player.trail = [];
    this.gridVersion++;
    // parkur bitirme coin ödülü
    const coinReward = 3 + Math.floor(this.L / 2) + (special ? 5 : 0) + (this.deaths === 0 ? 2 : 0);
    this.coinsRun += coinReward;
    addCoins(this.profile, coinReward);
    // onur ve profil
    const hr = recordParkur(this.profile, this.L, this.p, { percent: pct, special, deaths: this.deaths, score: this.score, reward: this.def.reward, difficulty: this.def.difficulty });
    if (this.score > this.profile.hiScore) this.profile.hiScore = this.score;
    this.account.save(true);
    this.lastResult = { bonus, honor: hr.honor, improved: hr.improved, prevHonor: hr.prevHonor, coins: this.coinsRun, coinReward, special, deaths: this.deaths, L: this.L, p: this.p, n: parkurCount(this.L), difficulty: this.def.difficulty, reward: this.def.reward };
    this.sfx.levelClear();
    this.setState(STATE.CLEAR);
    this.emit('clear', { result: this.lastResult });
  }

  gameOver() {
    if (this.score > this.profile.hiScore) this.profile.hiScore = this.score;
    this.account.save(true);
    this.sfx.gameOver();
    this.setState(STATE.GAMEOVER);
  }

  addScore(n) { this.score += n; this.emit('score'); }

  // ---------------- efektler ----------------
  burst(x, y, color, n) {
    for (let i = 0; i < n; i++) {
      const a = this.rng() * Math.PI * 2, sp = 6 + this.rng() * 22;
      this.particles.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 0.4 + this.rng() * 0.5, max: 0.9, color, size: 0.4 + this.rng() * 0.6 });
    }
  }
  spark(x, y) { this.particles.push({ x, y, vx: (this.rng() - 0.5) * 10, vy: (this.rng() - 0.5) * 10, life: 0.25, max: 0.25, color: '#fff2a0', size: 0.5 }); }
  floatText(x, y, text, color, life = 1.1) { this.texts.push({ x, y, text, color, life, max: life }); }
  updateFx(dt) {
    for (const p of this.particles) { p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.96; p.vy *= 0.96; p.life -= dt; }
    this.particles = this.particles.filter(p => p.life > 0);
    for (const t of this.texts) { t.y -= dt * 4; t.life -= dt; }
    this.texts = this.texts.filter(t => t.life > 0);
    if (this.shake > 0) this.shake -= dt;
  }
}
