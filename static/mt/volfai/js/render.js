// VOLFAI - çizim katmanı
import { GRID_W, GRID_H, CELL, POWERUPS, TIMER } from './config.js';
import { drawLevelArt } from './levels.js';
import { DIR_VEC } from './input.js';
import { STATE } from './game.js';

export class Renderer {
  constructor(canvas, stickCanvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.stickCanvas = stickCanvas;
    this.sctx = stickCanvas.getContext('2d');
    this.dpr = Math.min(2, window.devicePixelRatio || 1);
    this.cs = 4; // hücre boyutu (css px)
    this.art = document.createElement('canvas');
    this.comp = document.createElement('canvas');
    this.gw = GRID_W; this.gh = GRID_H;
    this.mask = document.createElement('canvas'); this.mask.width = GRID_W; this.mask.height = GRID_H;
    this.lines = document.createElement('canvas'); this.lines.width = GRID_W; this.lines.height = GRID_H;
    this.spriteScale = 1.3;   // gemi, küçük düşman, coin, mermi, füze boyutu (Ayarlar)
    this.availW = 300; this.availH = 500;
    this.starsC = document.createElement('canvas');
    this.gridVersion = -1;
    this.artLevel = -1;
    this.t = 0;
  }

  setGridSize(w, h) {
    if (this.gw === w && this.gh === h) return;
    this.gw = w; this.gh = h;
    this.mask.width = w; this.mask.height = h; this.lines.width = w; this.lines.height = h;
    this.gridVersion = -1;
    this.resize(this.availW, this.availH);
  }

  resize(availW, availH) {
    this.availW = availW; this.availH = availH;
    const GRID_W = this.gw, GRID_H = this.gh;
    const cs = Math.max(2, Math.floor(Math.min(availW / GRID_W, availH / GRID_H) * 4) / 4);
    this.cs = cs;
    const w = Math.round(cs * GRID_W), h = Math.round(cs * GRID_H);
    this.canvas.style.width = w + 'px'; this.canvas.style.height = h + 'px';
    this.canvas.width = Math.round(w * this.dpr); this.canvas.height = Math.round(h * this.dpr);
    this.art.width = this.comp.width = this.canvas.width;
    this.art.height = this.comp.height = this.canvas.height;
    this.starsC.width = this.canvas.width; this.starsC.height = this.canvas.height;
    this.artLevel = -1;
    this.makeStars();
    this.stickCanvas.width = Math.round(window.innerWidth * this.dpr);
    this.stickCanvas.height = Math.round(window.innerHeight * this.dpr);
    this.stickCanvas.style.width = window.innerWidth + 'px';
    this.stickCanvas.style.height = window.innerHeight + 'px';
  }

  makeStars() {
    const c = this.starsC.getContext('2d');
    c.fillStyle = '#04060d'; c.fillRect(0, 0, this.starsC.width, this.starsC.height);
    for (let i = 0; i < 160; i++) {
      c.fillStyle = `rgba(120,160,255,${0.15 + Math.random() * 0.35})`;
      c.fillRect(Math.random() * this.starsC.width, Math.random() * this.starsC.height, 2, 2);
    }
  }

  ensureArt(def) {
    if (this.artLevel === def.index) return;
    this.artLevel = def.index;
    const c = this.art.getContext('2d');
    c.setTransform(1, 0, 0, 1, 0, 0);
    drawLevelArt(c, this.art.width, this.art.height, def);
  }

  rebuildMask(grid) {
    if (grid.w !== this.gw || grid.h !== this.gh) this.setGridSize(grid.w, grid.h);
    const GRID_W = grid.w, GRID_H = grid.h;
    const m = this.mask.getContext('2d');
    const l = this.lines.getContext('2d');
    const img = m.createImageData(GRID_W, GRID_H);
    const limg = l.createImageData(GRID_W, GRID_H);
    const d = img.data, ld = limg.data;
    for (let y = 0; y < GRID_H; y++) for (let x = 0; x < GRID_W; x++) {
      const i = y * GRID_W + x, v = grid.cells[i], o = i * 4;
      if (v === CELL.CLAIMED || v === CELL.BLOCK) { d[o] = d[o + 1] = d[o + 2] = 255; d[o + 3] = 255; }
      if (v === CELL.CLAIMED && grid.hasEmptyNeighbour8(x, y)) { ld[o] = 120; ld[o + 1] = 230; ld[o + 2] = 255; ld[o + 3] = 255; }
      else if (v === CELL.TRAIL) { ld[o] = 255; ld[o + 1] = 90; ld[o + 2] = 140; ld[o + 3] = 255; }
    }
    m.putImageData(img, 0, 0);
    l.putImageData(limg, 0, 0);
  }

  setTrailPixel(x, y) {
    const l = this.lines.getContext('2d');
    l.fillStyle = '#ff5a8c'; l.fillRect(x, y, 1, 1);
  }

  // --- ana çizim ---
  draw(game, input) {
    const ctx = this.ctx, g = game.grid, S = this.cs * this.dpr;
    this.t += 1 / 60;
    if (!game.def) return;
    if (g.w !== this.gw || g.h !== this.gh) this.setGridSize(g.w, g.h);
    this.ensureArt(game.def);
    if (this.gridVersion !== game.gridVersion) { this.rebuildMask(g); this.gridVersion = game.gridVersion; }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (game.shake > 0) { const k = game.shake * 6 * this.dpr; ctx.translate((Math.random() - 0.5) * k, (Math.random() - 0.5) * k); }

    // 1) boş alan: uzay
    ctx.drawImage(this.starsC, 0, 0);
    // 2) ele geçirilmiş alan: bölüm sanatı maske ile
    const cc = this.comp.getContext('2d');
    cc.setTransform(1, 0, 0, 1, 0, 0);
    cc.globalCompositeOperation = 'source-over';
    cc.clearRect(0, 0, this.comp.width, this.comp.height);
    cc.drawImage(this.art, 0, 0);
    cc.globalCompositeOperation = 'destination-in';
    cc.imageSmoothingEnabled = false;
    cc.drawImage(this.mask, 0, 0, this.comp.width, this.comp.height);
    ctx.drawImage(this.comp, 0, 0);
    // 3) kenar çizgileri ve hat
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(this.lines, 0, 0, this.canvas.width, this.canvas.height);
    ctx.imageSmoothingEnabled = true;

    // 4) kutular
    for (const b of g.blocks) this.drawBlock(ctx, b, S);
    // 5) fitil
    if (game.fuse.active && game.player.drawing) {
      const i = Math.min(game.player.trail.length - 1, Math.floor(game.fuse.idx));
      const c = game.player.trail[i];
      if (c) {
        const x = (c[0] + 0.5) * S, y = (c[1] + 0.5) * S;
        ctx.fillStyle = `rgba(255,240,150,${0.6 + 0.4 * Math.sin(this.t * 40)})`;
        ctx.beginPath(); ctx.arc(x, y, S * 1.3, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x, y, S * 0.6, 0, Math.PI * 2); ctx.fill();
      }
    }
    // 6) düşmanlar
    const frozen = game.powers.T > 0;
    const SS = S * this.spriteScale;   // nesne ölçeği
    for (const s of game.smalls) if (s.alive) this.drawSmall(ctx, s, SS, frozen);
    for (const b of game.bosses) if (b.alive) this.drawBoss(ctx, b, S, frozen, game.def);
    for (const c of game.coins) this.drawCoin(ctx, c, S, SS);
    for (const sh of game.shots) {
      ctx.fillStyle = '#ff6b6b'; ctx.beginPath(); ctx.arc(sh.x * S, sh.y * S, SS * 0.7, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(sh.x * S, sh.y * S, SS * 0.3, 0, Math.PI * 2); ctx.fill();
    }
    for (const m of game.missiles) this.drawMissile(ctx, m, S, SS);
    if (game.deflectFx) {
      const f = game.deflectFx, k = f.t / 0.35;
      ctx.strokeStyle = `rgba(180,140,255,${k})`; ctx.lineWidth = S * 0.8;
      ctx.beginPath(); ctx.arc(f.x * S, f.y * S, SS * 4.5 * (1.4 - k * 0.4), 0, Math.PI * 2); ctx.stroke();
    }
    for (const be of game.beams) {
      const len = S * 3.5, a = Math.atan2(be.vy, be.vx);
      ctx.strokeStyle = be.dmg > 1 ? '#fff' : '#ff5d8f'; ctx.lineWidth = S * (be.dmg > 1 ? 1.2 : 0.7); ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(be.x * S, be.y * S); ctx.lineTo(be.x * S - Math.cos(a) * len, be.y * S - Math.sin(a) * len); ctx.stroke();
    }
    // 7) oyuncu
    if (game.state !== STATE.DYING) this.drawPlayer(ctx, game, S, SS);
    // 8) parçacıklar & yazılar
    for (const p of game.particles) {
      ctx.globalAlpha = Math.max(0, p.life / p.max);
      ctx.fillStyle = p.color; ctx.fillRect(p.x * S - p.size * S / 2, p.y * S - p.size * S / 2, p.size * S, p.size * S);
    }
    ctx.globalAlpha = 1;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const t of game.texts) {
      ctx.globalAlpha = Math.min(1, t.life / 0.3);
      ctx.font = `bold ${Math.round(S * 3.2)}px "Segoe UI", system-ui, sans-serif`;
      ctx.lineWidth = S * 0.8; ctx.strokeStyle = 'rgba(0,0,0,0.8)';
      ctx.strokeText(t.text, t.x * S, t.y * S); ctx.fillStyle = t.color; ctx.fillText(t.text, t.x * S, t.y * S);
    }
    ctx.globalAlpha = 1;
    // son 10 saniye geri sayım uyarısı
    if (game.state === STATE.PLAY && game.timeLeft > 0 && game.timeLeft <= TIMER.WARN_AT) {
      const sec = Math.ceil(game.timeLeft), frac = 1 - (sec - game.timeLeft);
      const W = this.canvas.width, H = this.canvas.height;
      ctx.fillStyle = `rgba(255,60,60,${0.10 + 0.08 * Math.sin(this.t * 12)})`;
      ctx.lineWidth = S * 1.5; ctx.strokeStyle = `rgba(255,70,70,${0.5 + 0.4 * Math.sin(this.t * 12)})`; ctx.strokeRect(S * 0.75, S * 0.75, W - S * 1.5, H - S * 1.5);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.globalAlpha = 0.25 + 0.55 * (1 - frac);
      ctx.font = `900 ${Math.round(S * (16 + 6 * frac))}px system-ui, sans-serif`;
      ctx.lineWidth = S * 1.2; ctx.strokeStyle = 'rgba(0,0,0,0.8)'; ctx.strokeText(String(sec), W / 2, H * 0.3);
      ctx.fillStyle = sec <= 3 ? '#ff4d4d' : '#ffd23f'; ctx.fillText(String(sec), W / 2, H * 0.3);
      ctx.globalAlpha = 1;
      ctx.font = `800 ${Math.round(S * 3)}px system-ui, sans-serif`; ctx.fillStyle = '#ff8a8a';
      ctx.strokeText('SÜRE AZALIYOR', W / 2, H * 0.3 + S * 13); ctx.fillText('SÜRE AZALIYOR', W / 2, H * 0.3 + S * 13);
    }
    // donma efekti
    if (frozen) { ctx.fillStyle = `rgba(93,228,255,${0.08 + 0.04 * Math.sin(this.t * 10)})`; ctx.fillRect(0, 0, this.canvas.width, this.canvas.height); }

    this.drawStick(input);
  }

  drawBlock(ctx, b, S) {
    const x = b.x * S, y = b.y * S, w = b.size * S;
    const grad = ctx.createLinearGradient(x, y, x + w, y + w);
    if (b.captured) { grad.addColorStop(0, '#3a4660'); grad.addColorStop(1, '#1a2030'); }
    else { grad.addColorStop(0, '#b8c2d6'); grad.addColorStop(1, '#5a6478'); }
    ctx.fillStyle = grad; ctx.fillRect(x, y, w, w);
    ctx.strokeStyle = b.captured ? '#5de4ff' : '#eef2ff'; ctx.lineWidth = Math.max(1, S * 0.25); ctx.strokeRect(x + 0.5, y + 0.5, w - 1, w - 1);
    ctx.fillStyle = b.captured ? (POWERUPS[b.letter]?.color || '#fff') : '#1a2030';
    ctx.font = `bold ${Math.round(w * 0.6)}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(b.captured ? b.letter : '?', x + w / 2, y + w / 2 + w * 0.03);
  }

  drawPlayer(ctx, game, S0, S) {
    const p = game.player;
    const x = (p.x + 0.5) * S0, y = (p.y + 0.5) * S0;
    // korumalı bölge halkası: kenardayken görünür, çizime geçince kaybolur
    if (!p.drawing) {
      const pulse = 0.55 + 0.25 * Math.sin(this.t * 5);
      const rr = S * 3.2;
      const grd = ctx.createRadialGradient(x, y, rr * 0.5, x, y, rr);
      grd.addColorStop(0, 'rgba(93,228,255,0)'); grd.addColorStop(1, `rgba(93,228,255,${0.22 * pulse})`);
      ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = `rgba(93,228,255,${pulse})`; ctx.lineWidth = Math.max(1, S * 0.35);
      ctx.setLineDash([S * 1.2, S * 0.8]); ctx.lineDashOffset = -this.t * S * 6;
      ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    }
    // P kalkanı: yeşil altıgen(ler)
    for (let i = 0; i < game.shields; i++) {
      ctx.strokeStyle = `rgba(155,255,138,${0.6 + 0.3 * Math.sin(this.t * 8 + i)})`; ctx.lineWidth = S * 0.35;
      const r = S * (2.0 + i * 0.5);
      ctx.beginPath(); for (let k = 0; k < 6; k++) { const a = this.t * 2 + k * Math.PI / 3; ctx.lineTo(x + Math.cos(a) * r, y + Math.sin(a) * r); } ctx.closePath(); ctx.stroke();
    }
    const blink = p.invuln > 0 && Math.floor(this.t * 12) % 2 === 0;
    if (blink) return;
    const [dx, dy] = DIR_VEC[p.face] || [0, -1];
    const a = Math.atan2(dy, dx);
    ctx.save(); ctx.translate(x, y); ctx.rotate(a + Math.PI / 2);
    const ship = game.fx?.ship || { color: '#d8f7ff', glow: '#5de4ff' };
    ctx.shadowColor = p.drawing ? '#ff5d8f' : ship.glow; ctx.shadowBlur = S * 2;
    ctx.fillStyle = p.drawing ? '#ffd1df' : ship.color;
    drawShipShape(ctx, game.profile.ship, S);
    ctx.shadowBlur = 0;
    ctx.fillStyle = p.drawing ? '#ff5d8f' : ship.glow; ctx.beginPath(); ctx.arc(0, 0, S * 0.45, 0, Math.PI * 2); ctx.fill();
    // zırh göstergesi: gövde çevresinde küçük plakalar
    for (let i = 0; i < game.armor; i++) { const aa = Math.PI / 2 + (i - (game.armor - 1) / 2) * 0.55; ctx.fillStyle = '#ffa94d'; ctx.fillRect(Math.cos(aa) * S * 1.9 - S * 0.25, Math.sin(aa) * S * 1.9 - S * 0.25, S * 0.5, S * 0.5); }
    // saptırıcılar: arkada mor üçgenler
    for (let i = 0; i < game.deflectors; i++) { const ox = (i - (game.deflectors - 1) / 2) * S * 1.1; ctx.fillStyle = 'rgba(180,140,255,0.9)'; ctx.beginPath(); ctx.moveTo(ox, S * 2.2); ctx.lineTo(ox - S * 0.45, S * 2.9); ctx.lineTo(ox + S * 0.45, S * 2.9); ctx.closePath(); ctx.fill(); }
    ctx.restore();
  }

  drawMissile(ctx, m, S0, S) {
    // iz
    for (let i = 0; i < m.trail.length; i++) { const [tx, ty] = m.trail[i]; ctx.fillStyle = `rgba(255,120,80,${(i / m.trail.length) * 0.5})`; ctx.fillRect(tx * S0 - S * 0.3, ty * S0 - S * 0.3, S * 0.6, S * 0.6); }
    ctx.save(); ctx.translate(m.x * S0, m.y * S0); ctx.rotate(m.ang);
    ctx.shadowColor = '#ff5d5d'; ctx.shadowBlur = S * 1.5;
    ctx.fillStyle = '#ff6b6b'; ctx.beginPath(); ctx.moveTo(S * 1.6, 0); ctx.lineTo(-S * 1.0, -S * 0.7); ctx.lineTo(-S * 0.6, 0); ctx.lineTo(-S * 1.0, S * 0.7); ctx.closePath(); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(S * 0.6, 0, S * 0.3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  drawCoin(ctx, c, S0, S) {
    const x = (c.x + 0.5) * S0, y = (c.y + 0.5) * S0;
    const sx = Math.abs(Math.cos(c.spin));              // dönüş efekti
    const fade = c.life < 3 ? (Math.floor(c.life * 6) % 2 ? 0.3 : 1) : 1;
    ctx.save(); ctx.translate(x, y); ctx.scale(Math.max(0.15, sx), 1); ctx.globalAlpha = fade;
    ctx.shadowColor = '#ffcc33'; ctx.shadowBlur = S * 2;
    const g = ctx.createRadialGradient(-S * 0.4, -S * 0.4, S * 0.2, 0, 0, S * 1.5);
    g.addColorStop(0, '#fff3b0'); g.addColorStop(0.5, '#ffcc33'); g.addColorStop(1, '#b8860b');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, S * 1.5, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = '#7a5a00'; ctx.lineWidth = S * 0.2; ctx.beginPath(); ctx.arc(0, 0, S * 1.05, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = '#7a5a00'; ctx.font = `bold ${Math.round(S * 1.6)}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('H', 0, S * 0.05);
    ctx.restore();
    if (c.value > 1) { ctx.fillStyle = '#ffe680'; ctx.font = `bold ${Math.round(S * 1.6)}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.fillText(`x${c.value}`, x, y - S * 2.4); }
  }

  drawSmall(ctx, s, SS, frozen) {
    const S = this.cs * this.dpr;
    const x = s.x * S, y = s.y * S, r = SS * 1.1;
    ctx.save(); ctx.translate(x, y); ctx.rotate(frozen ? 0 : s.spin);
    ctx.fillStyle = frozen ? '#9fdcff' : '#ff8a5d';
    ctx.beginPath();
    for (let i = 0; i < 8; i++) { const a = (i / 8) * Math.PI * 2, rr = i % 2 ? r : r * 0.5; ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr); }
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#2a0a00'; ctx.beginPath(); ctx.arc(0, 0, r * 0.3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  drawBoss(ctx, b, S, frozen, def) {
    const x = b.x * S, y = b.y * S, r = b.r * S;
    const hue = b.hue ?? (def.hue + 180) % 360;
    const flash = b.hitFlash > 0;
    const body = flash ? '#fff' : (frozen ? '#9fdcff' : `hsl(${hue},80%,55%)`);
    const light = flash ? '#fff' : (frozen ? '#d8f4ff' : `hsl(${hue},90%,78%)`);
    const dark = `hsl(${hue},70%,25%)`;
    const t = this.t, a = b.angle;
    const P = Math.PI, TAU = P * 2;
    const poly = (n, rr, rot = 0, inner = null) => { ctx.beginPath(); for (let i = 0; i < n * (inner ? 2 : 1); i++) { const ang = rot + (i / (n * (inner ? 2 : 1))) * TAU; const q = inner && i % 2 ? inner : rr; ctx.lineTo(Math.cos(ang) * q, Math.sin(ang) * q); } ctx.closePath(); };
    const eye = (ex, ey, er) => { ctx.fillStyle = '#0a0a14'; ctx.beginPath(); ctx.arc(ex, ey, er, 0, TAU); ctx.fill(); ctx.fillStyle = flash ? '#fff' : '#ff3b3b'; ctx.beginPath(); ctx.arc(ex + er * 0.3 * Math.cos(a), ey + er * 0.3 * Math.sin(a), er * 0.45, 0, TAU); ctx.fill(); };
    // yılan gövdesi önce (başın altında kalsın)
    if (b.segs && b.segs.length) {
      for (let i = b.segs.length - 1; i >= 0; i--) {
        const sg = b.segs[i], sr = r * (0.8 - i * 0.04);
        ctx.fillStyle = i % 2 ? body : light; ctx.beginPath(); ctx.arc(sg.x * S, sg.y * S, sr, 0, TAU); ctx.fill();
        ctx.fillStyle = dark; ctx.beginPath(); ctx.arc(sg.x * S, sg.y * S, sr * 0.35, 0, TAU); ctx.fill();
      }
    }
    ctx.save(); ctx.translate(x, y);
    ctx.shadowColor = `hsl(${hue},90%,60%)`; ctx.shadowBlur = S * 3;
    ctx.fillStyle = body;
    switch (b.type) {
      case 'amoeba':
        ctx.beginPath(); for (let i = 0; i <= 32; i++) { const ang = (i / 32) * TAU; const rr = r * (1 + 0.14 * Math.sin(ang * 5 + a * 3) + 0.06 * Math.sin(ang * 9 - a * 5)); ctx.lineTo(Math.cos(ang) * rr, Math.sin(ang) * rr); } ctx.closePath(); ctx.fill();
        ctx.shadowBlur = 0; ctx.fillStyle = light; for (let i = 0; i < 4; i++) { ctx.beginPath(); ctx.arc(Math.cos(a + i * 1.6) * r * 0.45, Math.sin(a * 0.7 + i * 1.6) * r * 0.45, r * 0.14, 0, TAU); ctx.fill(); }
        eye(0, 0, r * 0.3); break;
      case 'crab':
        ctx.beginPath(); ctx.ellipse(0, 0, r, r * 0.7, 0, 0, TAU); ctx.fill();
        ctx.shadowBlur = 0; ctx.strokeStyle = body; ctx.lineWidth = r * 0.18; ctx.lineCap = 'round';
        for (let sd = -1; sd <= 1; sd += 2) for (let i = 0; i < 3; i++) { const ly = (i - 1) * r * 0.5, w = Math.sin(t * 8 + i) * r * 0.15; ctx.beginPath(); ctx.moveTo(sd * r * 0.7, ly); ctx.lineTo(sd * r * 1.4, ly - r * 0.3 + w); ctx.lineTo(sd * r * 1.7, ly + r * 0.2 + w); ctx.stroke(); }
        for (let sd = -1; sd <= 1; sd += 2) { const o = Math.sin(t * 5) * 0.3; ctx.fillStyle = light; ctx.beginPath(); ctx.arc(sd * r * 1.1, -r * 0.9, r * 0.35, 0, TAU); ctx.fill(); ctx.fillStyle = dark; ctx.beginPath(); ctx.moveTo(sd * r * 1.1, -r * 0.9); ctx.arc(sd * r * 1.1, -r * 0.9, r * 0.36, -P / 2 - o, -P / 2 + 0.9 + o); ctx.closePath(); ctx.fill(); }
        eye(-r * 0.3, -r * 0.2, r * 0.16); eye(r * 0.3, -r * 0.2, r * 0.16); break;
      case 'crystal':
        ctx.rotate(a * 0.7); poly(6, r); ctx.fill(); ctx.shadowBlur = 0; ctx.fillStyle = `hsla(${hue},90%,85%,0.6)`; poly(6, r * 0.55, 0.5); ctx.fill(); ctx.rotate(-a * 0.7); eye(0, 0, r * 0.3); break;
      case 'jelly':
        ctx.beginPath(); ctx.arc(0, 0, r, P, TAU); ctx.lineTo(r, r * 0.2); ctx.quadraticCurveTo(0, r * 0.5, -r, r * 0.2); ctx.closePath(); ctx.fill();
        ctx.shadowBlur = 0; ctx.strokeStyle = `hsla(${hue},80%,70%,0.8)`; ctx.lineWidth = r * 0.1; ctx.lineCap = 'round';
        for (let i = 0; i < 6; i++) { const tx = (i - 2.5) * r * 0.32; ctx.beginPath(); ctx.moveTo(tx, r * 0.3); ctx.quadraticCurveTo(tx + Math.sin(t * 4 + i) * r * 0.4, r * 1.1, tx + Math.sin(t * 3 + i * 2) * r * 0.5, r * 1.9); ctx.stroke(); }
        ctx.fillStyle = light; ctx.beginPath(); ctx.arc(-r * 0.3, -r * 0.4, r * 0.18, 0, TAU); ctx.fill(); eye(0, -r * 0.15, r * 0.25); break;
      case 'ring':
        ctx.shadowBlur = S * 2; ctx.strokeStyle = body; ctx.lineWidth = r * 0.34; ctx.beginPath(); ctx.arc(0, 0, r * 0.8, 0, TAU); ctx.stroke();
        ctx.shadowBlur = 0; ctx.fillStyle = light; for (let i = 0; i < 6; i++) { const ang = a * 1.5 + i * TAU / 6; ctx.beginPath(); ctx.arc(Math.cos(ang) * r * 0.8, Math.sin(ang) * r * 0.8, r * 0.2, 0, TAU); ctx.fill(); }
        eye(0, 0, r * 0.28); break;
      case 'eye': {
        ctx.fillStyle = flash ? '#fff' : '#f4f0ff'; ctx.beginPath(); ctx.ellipse(0, 0, r, r * 0.72, 0, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = `hsla(${hue},80%,40%,0.7)`; ctx.lineWidth = r * 0.06; for (let i = 0; i < 6; i++) { ctx.beginPath(); ctx.moveTo(Math.cos(i) * r * 0.5, Math.sin(i) * r * 0.36); ctx.lineTo(Math.cos(i) * r, Math.sin(i) * r * 0.72); ctx.stroke(); }
        const px = Math.cos(a) * r * 0.25, py = Math.sin(a) * r * 0.18;
        ctx.fillStyle = body; ctx.beginPath(); ctx.arc(px, py, r * 0.45, 0, TAU); ctx.fill(); ctx.fillStyle = '#0a0a14'; ctx.beginPath(); ctx.arc(px, py, r * 0.22 * (1 + 0.3 * Math.sin(t * 3)), 0, TAU); ctx.fill(); ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(px - r * 0.12, py - r * 0.12, r * 0.07, 0, TAU); ctx.fill(); break; }
      case 'star': ctx.rotate(a); poly(5, r, -P / 2, r * 0.45); ctx.fill(); ctx.shadowBlur = 0; ctx.fillStyle = light; poly(5, r * 0.4, -P / 2, r * 0.18); ctx.fill(); ctx.rotate(-a); eye(0, 0, r * 0.22); break;
      case 'beetle':
        ctx.beginPath(); ctx.ellipse(0, 0, r * 0.8, r, 0, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = dark; ctx.lineWidth = r * 0.08; ctx.beginPath(); ctx.moveTo(0, -r); ctx.lineTo(0, r); ctx.stroke();
        ctx.fillStyle = light; for (let i = 0; i < 6; i++) { ctx.beginPath(); ctx.arc((i % 2 ? 1 : -1) * r * 0.4, (Math.floor(i / 2) - 1) * r * 0.5, r * 0.12, 0, TAU); ctx.fill(); }
        ctx.strokeStyle = body; ctx.lineWidth = r * 0.14; for (let sd = -1; sd <= 1; sd += 2) for (let i = 0; i < 3; i++) { const ly = (i - 1) * r * 0.55; ctx.beginPath(); ctx.moveTo(sd * r * 0.7, ly); ctx.lineTo(sd * r * 1.3, ly + Math.sin(t * 10 + i + sd) * r * 0.25); ctx.stroke(); }
        eye(-r * 0.25, -r * 0.6, r * 0.14); eye(r * 0.25, -r * 0.6, r * 0.14); break;
      case 'virus':
        ctx.beginPath(); ctx.arc(0, 0, r * 0.75, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        for (let i = 0; i < 10; i++) { const ang = i * TAU / 10 + a * 0.3; ctx.fillStyle = light; ctx.beginPath(); ctx.arc(Math.cos(ang) * r * 0.95, Math.sin(ang) * r * 0.95, r * 0.17, 0, TAU); ctx.fill(); ctx.strokeStyle = body; ctx.lineWidth = r * 0.1; ctx.beginPath(); ctx.moveTo(Math.cos(ang) * r * 0.7, Math.sin(ang) * r * 0.7); ctx.lineTo(Math.cos(ang) * r * 0.9, Math.sin(ang) * r * 0.9); ctx.stroke(); }
        ctx.fillStyle = dark; for (let i = 0; i < 5; i++) { ctx.beginPath(); ctx.arc(Math.cos(i * 2.4) * r * 0.35, Math.sin(i * 1.7) * r * 0.35, r * 0.1, 0, TAU); ctx.fill(); } eye(0, 0, r * 0.2); break;
      case 'squid':
        ctx.beginPath(); ctx.moveTo(0, -r * 1.2); ctx.quadraticCurveTo(r * 0.9, -r * 0.4, r * 0.7, r * 0.3); ctx.lineTo(-r * 0.7, r * 0.3); ctx.quadraticCurveTo(-r * 0.9, -r * 0.4, 0, -r * 1.2); ctx.fill();
        ctx.shadowBlur = 0; ctx.strokeStyle = body; ctx.lineWidth = r * 0.12; ctx.lineCap = 'round';
        for (let i = 0; i < 8; i++) { const tx = (i - 3.5) * r * 0.18; ctx.beginPath(); ctx.moveTo(tx, r * 0.3); ctx.quadraticCurveTo(tx * 2 + Math.sin(t * 5 + i) * r * 0.3, r * 0.9, tx * 2.5 + Math.cos(t * 4 + i) * r * 0.4, r * 1.5); ctx.stroke(); }
        eye(-r * 0.3, -r * 0.1, r * 0.17); eye(r * 0.3, -r * 0.1, r * 0.17); break;
      case 'spiral':
        ctx.rotate(a); ctx.shadowBlur = S * 2; ctx.strokeStyle = body; ctx.lineWidth = r * 0.22; ctx.lineCap = 'round';
        for (let k = 0; k < 3; k++) { ctx.beginPath(); for (let i = 0; i <= 20; i++) { const q = i / 20; const ang = k * TAU / 3 + q * 3.5; ctx.lineTo(Math.cos(ang) * r * q, Math.sin(ang) * r * q); } ctx.stroke(); }
        ctx.rotate(-a); ctx.shadowBlur = 0; eye(0, 0, r * 0.25); break;
      case 'cube': {
        ctx.rotate(a); const d = r * 0.72; ctx.fillStyle = dark; ctx.fillRect(-d, -d, 2 * d, 2 * d); ctx.shadowBlur = 0;
        ctx.fillStyle = body; ctx.fillRect(-d, -d, 2 * d, d); ctx.fillStyle = light; ctx.fillRect(-d, -d, d, d);
        ctx.strokeStyle = `hsla(${hue},90%,85%,0.9)`; ctx.lineWidth = r * 0.08; ctx.strokeRect(-d, -d, 2 * d, 2 * d); ctx.rotate(-a); eye(0, 0, r * 0.26); break; }
      case 'orb': {
        const g = ctx.createRadialGradient(-r * 0.3, -r * 0.3, r * 0.1, 0, 0, r); g.addColorStop(0, light); g.addColorStop(0.6, body); g.addColorStop(1, dark);
        ctx.fillStyle = flash ? '#fff' : g; ctx.beginPath(); ctx.arc(0, 0, r, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = `hsla(${hue},90%,80%,0.7)`; ctx.lineWidth = r * 0.08; for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.ellipse(0, 0, r * 1.2, r * 0.35, a + i * 1.05, 0, TAU); ctx.stroke(); } break; }
      case 'saucer':
        ctx.beginPath(); ctx.ellipse(0, r * 0.1, r * 1.3, r * 0.42, 0, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = light; ctx.beginPath(); ctx.arc(0, -r * 0.15, r * 0.55, P, TAU); ctx.fill();
        ctx.fillStyle = dark; ctx.beginPath(); ctx.ellipse(0, r * 0.3, r * 1.3, r * 0.22, 0, 0, P); ctx.fill();
        for (let i = 0; i < 7; i++) { const ang = a * 2 + i * TAU / 7; ctx.fillStyle = Math.sin(t * 6 + i) > 0 ? '#fff' : light; ctx.beginPath(); ctx.arc(Math.cos(ang) * r * 1.1, r * 0.12 + Math.sin(ang) * r * 0.3, r * 0.09, 0, TAU); ctx.fill(); }
        eye(0, -r * 0.2, r * 0.22); break;
      case 'moth': {
        const flap = 0.55 + 0.45 * Math.abs(Math.sin(t * 7));
        for (let sd = -1; sd <= 1; sd += 2) { ctx.fillStyle = body; ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(sd * r * 1.4 * flap, -r * 1.2, sd * r * 1.6 * flap, -r * 0.1); ctx.quadraticCurveTo(sd * r * 1.2 * flap, r * 0.9, 0, r * 0.4); ctx.closePath(); ctx.fill(); ctx.fillStyle = light; ctx.beginPath(); ctx.arc(sd * r * 0.9 * flap, -r * 0.3, r * 0.2, 0, TAU); ctx.fill(); }
        ctx.shadowBlur = 0; ctx.fillStyle = dark; ctx.beginPath(); ctx.ellipse(0, 0, r * 0.22, r * 0.75, 0, 0, TAU); ctx.fill(); eye(0, -r * 0.5, r * 0.16); break; }
      case 'gear':
        ctx.rotate(-a); poly(10, r, 0, r * 0.68); ctx.fill(); ctx.shadowBlur = 0; ctx.fillStyle = dark; ctx.beginPath(); ctx.arc(0, 0, r * 0.45, 0, TAU); ctx.fill(); ctx.rotate(a); eye(0, 0, r * 0.25); break;
      case 'serpent': // baş
        ctx.beginPath(); ctx.ellipse(0, 0, r * 1.05, r * 0.85, Math.atan2(b.vy, b.vx), 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        { const ang = Math.atan2(b.vy, b.vx); ctx.fillStyle = light; ctx.beginPath(); ctx.arc(Math.cos(ang + 0.6) * r * 0.5, Math.sin(ang + 0.6) * r * 0.5, r * 0.18, 0, TAU); ctx.arc(Math.cos(ang - 0.6) * r * 0.5, Math.sin(ang - 0.6) * r * 0.5, r * 0.18, 0, TAU); ctx.fill(); ctx.strokeStyle = '#ff5d5d'; ctx.lineWidth = r * 0.1; ctx.beginPath(); ctx.moveTo(Math.cos(ang) * r, Math.sin(ang) * r); ctx.lineTo(Math.cos(ang) * r * 1.5 + Math.sin(t * 20) * r * 0.1, Math.sin(ang) * r * 1.5); ctx.stroke(); eye(Math.cos(ang) * r * 0.3, Math.sin(ang) * r * 0.3, r * 0.2); }
        break;
      case 'diamond':
        ctx.rotate(a); poly(4, r * 1.1, 0); ctx.fill(); ctx.shadowBlur = 0; ctx.fillStyle = light; poly(4, r * 0.6, P / 4); ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = r * 0.06; ctx.beginPath(); ctx.moveTo(-r * 1.1, 0); ctx.lineTo(r * 1.1, 0); ctx.moveTo(0, -r * 1.1); ctx.lineTo(0, r * 1.1); ctx.stroke(); ctx.rotate(-a); eye(0, 0, r * 0.22); break;
      case 'spider':
        ctx.shadowBlur = 0; ctx.strokeStyle = body; ctx.lineWidth = r * 0.12; ctx.lineCap = 'round';
        for (let i = 0; i < 8; i++) { const sd = i < 4 ? -1 : 1, k = i % 4, ang = sd * (0.5 + k * 0.5) - P / 2 * (sd - 1) + (sd > 0 ? 0 : P), w = Math.sin(t * 9 + k * 1.3) * 0.25; const lx = Math.cos(ang) * r * 0.6, ly = Math.sin(ang) * r * 0.6; ctx.beginPath(); ctx.moveTo(lx * 0.5, ly * 0.5); ctx.lineTo(lx * 1.9, ly * 1.9 - r * 0.6); ctx.lineTo(lx * 2.4 + w * r, ly * 2.4 + r * 0.6); ctx.stroke(); }
        ctx.shadowBlur = S * 3; ctx.fillStyle = body; ctx.beginPath(); ctx.ellipse(0, r * 0.2, r * 0.75, r * 0.9, 0, 0, TAU); ctx.fill(); ctx.beginPath(); ctx.arc(0, -r * 0.7, r * 0.4, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = light; ctx.beginPath(); ctx.moveTo(0, -r * 0.2); ctx.lineTo(r * 0.3, r * 0.5); ctx.lineTo(0, r * 0.9); ctx.lineTo(-r * 0.3, r * 0.5); ctx.closePath(); ctx.fill();
        for (let i = 0; i < 4; i++) eye((i - 1.5) * r * 0.22, -r * 0.75, r * 0.08); break;
      case 'skull':
        ctx.fillStyle = flash ? '#fff' : (frozen ? '#9fdcff' : `hsl(${hue},25%,88%)`); ctx.beginPath(); ctx.arc(0, -r * 0.15, r * 0.85, P * 0.9, P * 2.1); ctx.lineTo(r * 0.55, r * 0.5); ctx.lineTo(r * 0.4, r * 0.95); ctx.lineTo(-r * 0.4, r * 0.95); ctx.lineTo(-r * 0.55, r * 0.5); ctx.closePath(); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = '#0a0a14'; ctx.beginPath(); ctx.ellipse(-r * 0.32, -r * 0.2, r * 0.24, r * 0.3, 0, 0, TAU); ctx.ellipse(r * 0.32, -r * 0.2, r * 0.24, r * 0.3, 0, 0, TAU); ctx.fill(); ctx.beginPath(); ctx.moveTo(0, r * 0.1); ctx.lineTo(r * 0.12, r * 0.4); ctx.lineTo(-r * 0.12, r * 0.4); ctx.closePath(); ctx.fill();
        ctx.fillStyle = body; ctx.beginPath(); ctx.arc(-r * 0.32 + Math.cos(a) * r * 0.08, -r * 0.2, r * 0.1 * (1 + 0.4 * Math.sin(t * 6)), 0, TAU); ctx.arc(r * 0.32 + Math.cos(a) * r * 0.08, -r * 0.2, r * 0.1 * (1 + 0.4 * Math.sin(t * 6)), 0, TAU); ctx.fill();
        ctx.strokeStyle = '#0a0a14'; ctx.lineWidth = r * 0.06; for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * r * 0.16, r * 0.6); ctx.lineTo(i * r * 0.16, r * 0.95); ctx.stroke(); } break;
      case 'hydra':
        ctx.beginPath(); ctx.arc(0, r * 0.25, r * 0.7, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        for (let i = -1; i <= 1; i++) { const sway = Math.sin(t * 3 + i * 2) * r * 0.2; const hx = i * r * 0.85 + sway, hy = -r * 0.75; ctx.strokeStyle = body; ctx.lineWidth = r * 0.32; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(i * r * 0.3, 0); ctx.quadraticCurveTo(i * r * 0.7, -r * 0.4, hx, hy); ctx.stroke(); ctx.fillStyle = light; ctx.beginPath(); ctx.arc(hx, hy, r * 0.34, 0, TAU); ctx.fill(); eye(hx, hy, r * 0.16); }
        break;
      case 'trisun':
        ctx.rotate(a); for (let i = 0; i < 3; i++) { const ang = i * TAU / 3; ctx.fillStyle = i === 0 ? light : body; ctx.beginPath(); ctx.arc(Math.cos(ang) * r * 0.5, Math.sin(ang) * r * 0.5, r * 0.5, 0, TAU); ctx.fill(); }
        ctx.shadowBlur = 0; ctx.rotate(-a); ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(0, 0, r * 0.25, 0, TAU); ctx.fill(); eye(0, 0, r * 0.18); break;
      case 'blackhole': {
        ctx.shadowBlur = 0; for (let i = 5; i >= 1; i--) { ctx.strokeStyle = `hsla(${(hue + i * 12) % 360},90%,65%,${0.9 - i * 0.12})`; ctx.lineWidth = r * 0.1; ctx.beginPath(); ctx.ellipse(0, 0, r * (0.5 + i * 0.14), r * (0.5 + i * 0.14) * 0.45, a * 0.5 + i * 0.3, 0, TAU); ctx.stroke(); }
        ctx.fillStyle = '#000'; ctx.beginPath(); ctx.arc(0, 0, r * 0.5, 0, TAU); ctx.fill(); ctx.strokeStyle = flash ? '#fff' : light; ctx.lineWidth = r * 0.08; ctx.beginPath(); ctx.arc(0, 0, r * 0.52, 0, TAU); ctx.stroke(); break; }
      case 'queen':
        ctx.beginPath(); ctx.arc(0, 0, r, P, TAU); ctx.quadraticCurveTo(r * 0.6, r * 0.7, 0, r * 0.5); ctx.quadraticCurveTo(-r * 0.6, r * 0.7, -r, 0); ctx.closePath(); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = `hsla(${hue},80%,70%,0.85)`; ctx.lineWidth = r * 0.12; ctx.lineCap = 'round'; for (let i = 0; i < 8; i++) { const tx = (i - 3.5) * r * 0.26; ctx.beginPath(); ctx.moveTo(tx, r * 0.4); ctx.quadraticCurveTo(tx + Math.sin(t * 4 + i) * r * 0.5, r * 1.2, tx * 1.3 + Math.cos(t * 3 + i) * r * 0.4, r * 2.1); ctx.stroke(); }
        ctx.fillStyle = '#ffd23f'; ctx.beginPath(); ctx.moveTo(-r * 0.6, -r * 0.75); ctx.lineTo(-r * 0.45, -r * 1.35); ctx.lineTo(-r * 0.2, -r * 0.95); ctx.lineTo(0, -r * 1.5); ctx.lineTo(r * 0.2, -r * 0.95); ctx.lineTo(r * 0.45, -r * 1.35); ctx.lineTo(r * 0.6, -r * 0.75); ctx.closePath(); ctx.fill();
        eye(-r * 0.3, -r * 0.2, r * 0.2); eye(r * 0.3, -r * 0.2, r * 0.2); break;
      default: // spiker (eski)
        ctx.rotate(-a); poly(10, r, 0, r * 0.62); ctx.fill(); ctx.shadowBlur = 0; ctx.rotate(a); eye(0, 0, r * 0.3);
    }
    ctx.restore();
    if (b.hp < b.maxHp) {
      const w = r * 2.4, h = S * 0.8;
      ctx.fillStyle = 'rgba(0,0,0,0.6)'; ctx.fillRect(x - w / 2, y - r - h * 2.2, w, h);
      ctx.fillStyle = '#ff5d8f'; ctx.fillRect(x - w / 2, y - r - h * 2.2, w * (b.hp / b.maxHp), h);
    }
  }

  drawStick(input) {
    const c = this.sctx; c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.clearRect(0, 0, this.stickCanvas.width, this.stickCanvas.height);
    if (!input.visible || !input.anchor) return;
    const a = input.anchor, p = input.pos || a;
    c.strokeStyle = 'rgba(93,228,255,0.45)'; c.lineWidth = 2;
    c.beginPath(); c.arc(a.x, a.y, 44, 0, Math.PI * 2); c.stroke();
    c.fillStyle = 'rgba(93,228,255,0.1)'; c.fill();
    let dx = p.x - a.x, dy = p.y - a.y; const d = Math.hypot(dx, dy);
    if (d > 44) { dx *= 44 / d; dy *= 44 / d; }
    c.fillStyle = 'rgba(255,255,255,0.75)'; c.beginPath(); c.arc(a.x + dx, a.y + dy, 18, 0, Math.PI * 2); c.fill();
  }
}


/** Gemi silueti (merkez 0,0; burun -y yönünde). Hangar önizlemesi de aynı çizimi kullanır. */
export function drawShipShape(ctx, id, S) {
  ctx.beginPath();
  switch (id) {
    case 'kirlangic': // ince, uzun, çatal kanat
      ctx.moveTo(0, -S * 2.2); ctx.lineTo(S * 0.7, S * 0.6); ctx.lineTo(S * 1.5, S * 1.6); ctx.lineTo(S * 0.35, S * 1.0); ctx.lineTo(0, S * 1.4); ctx.lineTo(-S * 0.35, S * 1.0); ctx.lineTo(-S * 1.5, S * 1.6); ctx.lineTo(-S * 0.7, S * 0.6); break;
    case 'kale': // geniş, köşeli, ağır
      ctx.moveTo(-S * 0.8, -S * 1.5); ctx.lineTo(S * 0.8, -S * 1.5); ctx.lineTo(S * 1.6, S * 0.2); ctx.lineTo(S * 1.6, S * 1.4); ctx.lineTo(S * 0.6, S * 1.0); ctx.lineTo(-S * 0.6, S * 1.0); ctx.lineTo(-S * 1.6, S * 1.4); ctx.lineTo(-S * 1.6, S * 0.2); break;
    case 'hayalet': // ok ucu, yarı saydam kanatlar
      ctx.moveTo(0, -S * 1.9); ctx.lineTo(S * 1.6, S * 1.3); ctx.lineTo(S * 0.5, S * 0.7); ctx.lineTo(0, S * 1.6); ctx.lineTo(-S * 0.5, S * 0.7); ctx.lineTo(-S * 1.6, S * 1.3); break;
    default: // monotros
      ctx.moveTo(0, -S * 1.6); ctx.lineTo(S * 1.2, S * 1.2); ctx.lineTo(0, S * 0.6); ctx.lineTo(-S * 1.2, S * 1.2);
  }
  ctx.closePath(); ctx.fill();
}
