// VOLFAI - giriş noktası: döngü, HUD, ekranlar (bölümler, hangar, ayarlar)
import { Game, STATE } from './game.js';
import { Renderer, drawShipShape } from './render.js';
import { Input } from './input.js';
import { Sfx } from './audio.js';
import { Account } from './account.js';
import { POWERUPS, CLEAR_PERCENT, LEVEL_COUNT, UPGRADES, SHIPS, TIMER, FIELD_SIZES, SPRITE_SCALES, DIFFICULTY } from './config.js';
import { levelInfo, parkurCount, totalParkurs, drawLevelArt } from './levels.js';
import { isLevelUnlocked, isParkurUnlocked, isParkurCleared, parkurResult, levelHonor, levelHonorRequired, totalHonor, highestUnlockedLevel, levelClearedCount, upgradeCost, buyUpgrade, upgradeEffects, currentShip, ownsShip, canBuyShip, buyShip, selectShip } from './profile.js';

const $ = id => document.getElementById(id);
const sfx = new Sfx();
const account = new Account();
const game = new Game(sfx, account);
const renderer = new Renderer($('game'), $('stick'));
const input = new Input(document.body, $('btn-fire'));
window.__volfai = { game, input, renderer, account };

const tap = (el, fn) => {
  let lastTouch = 0;
  el.addEventListener('touchend', e => { e.preventDefault(); e.stopPropagation(); lastTouch = Date.now(); sfx.init(); sfx.resume(); fn(); }, { passive: false });
  el.addEventListener('click', e => { e.preventDefault(); if (Date.now() - lastTouch < 700) return; sfx.init(); sfx.resume(); fn(); });
};
const screens = { title: $('screen-title'), levels: $('screen-levels'), hangar: $('screen-hangar'), settings: $('screen-settings'), intro: $('screen-intro'), clear: $('screen-clear'), pause: $('screen-pause'), over: $('screen-over') };
let currentScreen = 'title', prevScreen = 'title';
function showScreen(name) {
  if (name && name !== currentScreen) prevScreen = currentScreen;
  currentScreen = name;
  for (const k in screens) screens[k].classList.toggle('hidden', k !== name);
  if (name === 'levels') renderLevels();
  if (name === 'hangar') renderHangar();
  if (name === 'settings') renderSettings();
  if (name === 'title') renderTitleUser();
}
// HEPGO kullanıcısı: başlık ekranındaki çip (avatar + ad); oturum okunamadıysa uyarı
function renderTitleUser() {
  const el = $('title-user'); el.textContent = '';
  if (!account.isLoggedIn) { el.textContent = account.syncState === 'idle' ? 'HEPGO…' : 'HEPGO oturumu bulunamadı'; return; }
  const av = account.avatarUrl;
  if (av) { const img = document.createElement('img'); img.src = av; img.alt = ''; img.className = 'user-avatar'; el.appendChild(img); }
  el.appendChild(document.createTextNode(`${av ? '' : '👤 '}${account.user.name}`));
}

// --- görünüm ayarları ---
renderer.spriteScale = account.profile.settings.spriteScale || 1.3;

// --- ses ---
input.onAny = () => { sfx.init(); sfx.resume(); };
sfx.setMuted(!!account.profile.settings.muted);

// --- boyutlandırma ---
function layout() { const r = $('field').getBoundingClientRect(); renderer.resize(r.width - 8, r.height - 8); }
window.addEventListener('resize', layout);
window.addEventListener('orientationchange', () => setTimeout(layout, 200));
layout();

// --- HUD ---
const fmt = n => Math.round(n).toLocaleString('tr-TR');
function updateHud() {
  $('score').textContent = fmt(game.score);
  $('hud-coins').textContent = fmt(account.profile.coins);
  const pct = Math.floor(game.grid.percent());
  const pe = $('percent');
  pe.innerHTML = `${pct}<small>%</small>`;
  pe.classList.toggle('done', pct >= CLEAR_PERCENT);
  $('lives').textContent = '▲'.repeat(Math.max(0, game.lives));
  const te = $('timer'); const tl = Math.ceil(game.timeLeft || 0); te.textContent = tl; te.classList.toggle('hurry', !!game.hurry && tl === 0);
  te.classList.toggle('warn', tl > 0 && tl <= TIMER.WARN_AT); te.classList.toggle('last', tl > 0 && tl <= 3);
  if (game.fx) {
    const am = game.fx.armorMax, dm = game.fx.deflectors;
    const ak = `${game.armor}/${am}`, dk = `${game.deflectors}/${dm}`;
    if ($('armor').dataset.k !== ak) { $('armor').dataset.k = ak; $('armor').innerHTML = Array.from({ length: am }, (_, i) => `<i class="${i < game.armor ? '' : 'off'}"></i>`).join(''); }
    if ($('defl').dataset.k !== dk) { $('defl').dataset.k = dk; $('defl').innerHTML = Array.from({ length: dm }, (_, i) => `<i class="${i < game.deflectors ? '' : 'off'}"></i>`).join(''); }
  }
  if (game.def) { const ln = $('levelname'); ln.textContent = `${DIFFICULTY[game.def.difficulty].name} · B${game.def.L} · P${game.def.p}/${game.def.n} · ${game.def.name}`; ln.className = `lvl diff-${game.def.difficulty}`; }
  let html = '';
  for (const k of ['S', 'T', 'L']) if (game.powers[k] > 0) {
    const d = POWERUPS[k].duration + (k === 'L' ? game.fx.laserBonus : 0);
    const frac = Math.min(1, game.powers[k] / (game.superWeapon && k === 'L' ? 20 + game.fx.laserBonus : d));
    html += `<span class="power" style="color:${POWERUPS[k].color}">${k} ${POWERUPS[k].name}<span class="bar"><i style="width:${frac * 100}%"></i></span></span>`;
  }
  if (game.shields > 0) html += `<span class="power" style="color:${POWERUPS.P.color}">P KALKAN ×${game.shields}</span>`;
  if (game.superWeapon) html += `<span class="power" style="color:#fff">SÜPER</span>`;
  $('powers').innerHTML = html;
  $('btn-fire').classList.toggle('hidden', !(game.powers.L > 0 && game.state === STATE.PLAY));
}

// --- oyun olayları ---
function handleEvents() {
  for (const ev of game.events) {
    switch (ev.type) {
      case 'trail': renderer.setTrailPixel(ev.x, ev.y); break;
      case 'parkur':
        $('intro-no').textContent = ev.def.L; $('intro-p').textContent = ev.def.p; $('intro-n').textContent = ev.def.n; $('intro-name').textContent = ev.def.name; $('intro-creature').textContent = ev.def.creature.name + (ev.def.dualBoss ? ' ×2' : ''); const dd = DIFFICULTY[ev.def.difficulty]; $('intro-diff').textContent = `ZORLUK: ${dd.name}${dd.reward > 1 ? ` · ÖDÜL ×${dd.reward}` : ''}`; $('intro-diff').style.color = dd.color; break;
      case 'state':
        if (ev.state === STATE.INTRO) showScreen('intro');
        else if (ev.state === STATE.PLAY) showScreen(null);
        else if (ev.state === STATE.PAUSE) showScreen('pause');
        else if (ev.state === STATE.MENU) showScreen('levels');
        else if (ev.state === STATE.GAMEOVER) {
          $('over-score').textContent = fmt(game.score);
          $('over-coins').textContent = `+${game.coinsRun}`;
          showScreen('over');
        }
        break;
      case 'clear': {
        const r = ev.result, b = r.bonus;
        $('clear-title').textContent = r.special ? 'ÖZEL BİTİRİŞ!' : 'PARKUR TAMAMLANDI';
        $('clear-honor').textContent = r.honor;
        $('clear-honor-note').textContent = r.improved ? (r.prevHonor ? `Önceki en iyi: ${r.prevHonor} → yeni rekor!` : (r.deaths === 0 ? 'Hiç can kaybetmedin: +5 onur' : '')) : `En iyi sonucun ${r.prevHonor} onur olarak kalıyor.`;
        { const dd = DIFFICULTY[r.difficulty] || DIFFICULTY.acemi; $('clear-diff').innerHTML = `Zorluk: <b style="color:${dd.color}">${dd.name}</b>${dd.reward > 1 ? ` · onur ve HEPCOIN ×${dd.reward}` : ''}`; }
        $('clear-pct').textContent = `${Math.floor(b.percent)}%`;
        $('clear-over').textContent = fmt(b.over);
        $('clear-time').textContent = fmt(b.time);
        $('clear-special-row').classList.toggle('hidden', !r.special);
        $('clear-special').textContent = fmt(b.special);
        $('clear-coins').textContent = `+${r.coins}`;
        $('clear-score').textContent = fmt(game.score);
        const hasNext = r.p < r.n;
        const nextLevelOpen = !hasNext && r.L < LEVEL_COUNT && isLevelUnlocked(account.profile, r.L + 1);
        $('clear-unlock').classList.toggle('hidden', !(nextLevelOpen && levelClearedCount(account.profile, r.L + 1) === 0));
        const nb = $('btn-next');
        if (hasNext) { nb.textContent = `PARKUR ${r.p + 1}'E GEÇ`; nb.disabled = false; }
        else if (nextLevelOpen) { nb.textContent = `BÖLÜM ${r.L + 1}'E GEÇ`; nb.disabled = false; }
        else if (r.L < LEVEL_COUNT) { nb.textContent = `BÖLÜM ${r.L + 1} İÇİN ${levelHonorRequired(r.L) - levelHonor(account.profile, r.L)} ONUR DAHA GEREK`; nb.disabled = true; }
        else { nb.textContent = 'KAMPANYA TAMAMLANDI!'; nb.disabled = true; }
        showScreen('clear');
        break;
      }
      default: break;
    }
  }
  game.events.length = 0;
}

// ===== BÖLÜM SEÇİMİ =====
let selLevel = null, selParkur = 1;
const thumbCache = new Map();
function thumb(L) {
  if (thumbCache.has(L)) return thumbCache.get(L);
  const c = document.createElement('canvas'); c.width = 240; c.height = 300;
  const info = levelInfo(L);
  drawLevelArt(c.getContext('2d'), c.width, c.height, { index: L * 100 + 1, hue: info.hue, art: info.art });
  thumbCache.set(L, c); return c;
}
function renderLevels() {
  const prof = account.profile;
  const car = $('level-carousel');
  if (selLevel === null) selLevel = highestUnlockedLevel(prof);
  car.innerHTML = '';
  for (let L = 1; L <= LEVEL_COUNT; L++) {
    const info = levelInfo(L);
    const unlocked = isLevelUnlocked(prof, L);
    const done = levelClearedCount(prof, L), n = info.parkurs;
    const honor = levelHonor(prof, L), req = levelHonorRequired(L);
    const card = document.createElement('div');
    card.className = 'level-card' + (unlocked ? '' : ' locked') + (done === n ? ' done' : '') + (L === selLevel ? ' active' : '');
    card.dataset.level = L;
    card.appendChild(thumb(L));
    card.insertAdjacentHTML('beforeend', `<div class="shade"></div><div class="no">BÖLÜM ${L}</div><div class="nm">${info.name}</div><div class="bar"><i style="width:${Math.min(100, honor / req * 100)}%"></i></div><div class="meta"><span>${done}/${n} parkur</span><span>★ ${honor}/${req}</span></div>`);
    card.addEventListener('click', () => { selectLevel(L); card.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' }); });
    car.appendChild(card);
  }
  $('levels-honor').textContent = `★ ${totalHonor(prof)}`;
  renderDiffSeg();
  let cleared = 0; for (let L = 1; L <= LEVEL_COUNT; L++) cleared += levelClearedCount(prof, L);
  $('levels-progress').style.width = `${(cleared / totalParkurs()) * 100}%`;
  selectLevel(selLevel, true);
  requestAnimationFrame(() => { const el = car.querySelector(`[data-level="${selLevel}"]`); if (el) el.scrollIntoView({ inline: 'center', block: 'nearest' }); });
}
// kaydırınca ortadaki kart seçilsin
let scrollT = null;
$('level-carousel').addEventListener('scroll', () => {
  clearTimeout(scrollT);
  scrollT = setTimeout(() => {
    const car = $('level-carousel'); const mid = car.scrollLeft + car.clientWidth / 2;
    let best = null, bd = Infinity;
    for (const el of car.children) { const c = el.offsetLeft + el.offsetWidth / 2; const d = Math.abs(c - mid); if (d < bd) { bd = d; best = el; } }
    if (best && +best.dataset.level !== selLevel) selectLevel(+best.dataset.level);
  }, 80);
}, { passive: true });

function renderDiffSeg() {
  const prof = account.profile, cur = prof.settings.difficulty || 'acemi';
  $('diff-seg').innerHTML = Object.keys(DIFFICULTY).map(k => `<button type="button" data-k="${k}" class="${k === cur ? 'on ' + k : ''}">${DIFFICULTY[k].name}${DIFFICULTY[k].reward > 1 ? ` ×${DIFFICULTY[k].reward}` : ''}</button>`).join('');
  $('diff-desc').textContent = DIFFICULTY[cur].desc;
  $('diff-seg').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { prof.settings.difficulty = b.dataset.k; account.save(); sfx.tap(); renderDiffSeg(); }));
}

function scrollToLevel(L, smooth = true) {
  const el = $('level-carousel').querySelector(`[data-level="${L}"]`);
  if (el) el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', inline: 'center', block: 'nearest' });
}
tap($('car-left'), () => { if (selLevel > 1) { selectLevel(selLevel - 1); scrollToLevel(selLevel); } });
tap($('car-right'), () => { if (selLevel < LEVEL_COUNT) { selectLevel(selLevel + 1); scrollToLevel(selLevel); } });
// fare ile sürükleyerek kaydırma (masaüstü) + dikey tekerleği yataya çevir
(() => {
  const car = $('level-carousel');
  let down = false, sx = 0, sl = 0, moved = false;
  car.addEventListener('mousedown', e => { down = true; moved = false; sx = e.clientX; sl = car.scrollLeft; car.classList.add('dragging'); e.preventDefault(); });
  window.addEventListener('mousemove', e => { if (!down) return; const dx = e.clientX - sx; if (Math.abs(dx) > 4) moved = true; car.scrollLeft = sl - dx; });
  window.addEventListener('mouseup', () => { if (!down) return; down = false; car.classList.remove('dragging'); if (moved) { setTimeout(() => scrollToLevel(selLevel), 120); } });
  car.addEventListener('click', e => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  car.addEventListener('wheel', e => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { e.preventDefault(); car.scrollLeft += e.deltaY; } }, { passive: false });
  $('level-dots').addEventListener('click', e => { const i = [...$('level-dots').children].indexOf(e.target); if (i >= 0) { selectLevel(i + 1); scrollToLevel(i + 1); } });
})();

function selectLevel(L, silent) {
  selLevel = L;
  const prof = account.profile, info = levelInfo(L), n = info.parkurs;
  for (const el of $('level-carousel').children) el.classList.toggle('active', +el.dataset.level === L);
  $('level-dots').innerHTML = Array.from({ length: LEVEL_COUNT }, (_, i) => `<i class="${i + 1 === L ? 'on' : (levelClearedCount(prof, i + 1) === levelInfo(i + 1).parkurs ? 'done' : '')}"></i>`).join('');
  $('car-left').disabled = L <= 1; $('car-right').disabled = L >= LEVEL_COUNT;
  $('parkur-title').textContent = `BÖLÜM ${L} · ${info.name}`;
  $('parkur-honor').textContent = `ONUR ${levelHonor(prof, L)} / ${levelHonorRequired(L)}`;
  // varsayılan parkur: ilk bitirilmemiş açık parkur
  selParkur = 1; for (let p = 1; p <= n; p++) if (isParkurUnlocked(prof, L, p) && !isParkurCleared(prof, L, p)) { selParkur = p; break; }
  if (isParkurCleared(prof, L, n) && selParkur === 1 && isParkurCleared(prof, L, 1)) selParkur = n;
  const grid = $('parkur-grid'); grid.innerHTML = '';
  for (let p = 1; p <= n; p++) {
    const r = parkurResult(prof, L, p), un = isParkurUnlocked(prof, L, p);
    const b = document.createElement('button');
    b.className = 'pk' + (r ? ' done' : '') + (un ? '' : ' locked') + (p === selParkur ? ' sel' : '') + (p === n ? ' boss' : '');
    b.innerHTML = `${p}${r ? `<small>★${r.honor}</small>` : ''}`;
    b.disabled = !un;
    b.addEventListener('click', () => { selParkur = p; for (const e of grid.children) e.classList.remove('sel'); b.classList.add('sel'); updatePlayBtn(); sfx.tap(); });
    grid.appendChild(b);
  }
  updatePlayBtn();
  if (!silent) sfx.tap();
}
function updatePlayBtn() {
  const btn = $('btn-play-parkur');
  const un = isLevelUnlocked(account.profile, selLevel);
  btn.disabled = !un;
  btn.textContent = un ? `PARKUR ${selParkur} · BAŞLA` : `BÖLÜM ${selLevel - 1}'DE ${levelHonorRequired(selLevel - 1)} ONUR GEREK`;
}
$('btn-play-parkur').addEventListener('click', () => { sfx.init(); sfx.resume(); game.startParkur(selLevel, selParkur); });

// ===== HANGAR =====
function renderHangar() {
  const prof = account.profile;
  $('hangar-coins').textContent = fmt(prof.coins);
  const fx = upgradeEffects(prof);
  $('ship-stats').innerHTML = `<b style="color:${fx.ship.glow}">${fx.ship.name}</b><br>Hız <b>×${fx.speedMult.toFixed(2)}</b> · Zırh <b>${fx.armorMax}</b><br>Saptırıcı <b>${fx.deflectors}</b> · Kalkan <b>${fx.startShields}</b><br>Can <b>${3 + fx.extraLives}</b> · Lazer <b>+${fx.laserBonus} sn</b><br>Süre <b>+${fx.extraTime} sn</b> · Coin <b>×${fx.coinValueMult.toFixed(1)}</b>`;
  drawShip($('ship-canvas'), prof.upgrades, prof.ship);
  const sl = $('ship-list'); sl.innerHTML = '';
  for (const id in SHIPS) {
    const sh = SHIPS[id], owned = ownsShip(prof, id), cur = prof.ship === id;
    const el = document.createElement('div'); el.className = 'ship' + (cur ? ' sel' : '');
    const cv = document.createElement('canvas'); cv.width = 200; cv.height = 100;
    el.appendChild(cv);
    el.insertAdjacentHTML('beforeend', `<div class="nm" style="color:${sh.glow}">${sh.name}</div><div class="st">Hız <b>×${sh.speed.toFixed(2)}</b> · Zırh <b>${sh.armor}</b> · Saptırıcı <b>${sh.deflectors}</b><br>${sh.desc}</div>`);
    const b = document.createElement('button');
    if (cur) { b.textContent = 'SEÇİLİ'; b.className = 'cur'; b.disabled = true; }
    else if (owned) { b.textContent = 'SEÇ'; b.className = 'use'; b.addEventListener('click', () => { selectShip(prof, id); account.save(true); sfx.tap(); renderHangar(); }); }
    else { b.textContent = `${sh.price} H`; b.disabled = !canBuyShip(prof, id); b.addEventListener('click', () => { if (buyShip(prof, id)) { account.save(true); sfx.buy(); renderHangar(); } }); }
    el.appendChild(b); sl.appendChild(el);
    const c = cv.getContext('2d'); c.save(); c.translate(100, 52); c.shadowColor = sh.glow; c.shadowBlur = 18; c.fillStyle = sh.color; drawShipShape(c, id, 14); c.shadowBlur = 0; c.fillStyle = sh.glow; c.beginPath(); c.arc(0, 0, 5, 0, Math.PI * 2); c.fill(); c.restore();
  }
  const list = $('upgrade-list'); list.innerHTML = '';
  for (const key in UPGRADES) {
    const u = UPGRADES[key], lvl = prof.upgrades[key] || 0, cost = upgradeCost(prof, key);
    const el = document.createElement('div'); el.className = 'upg';
    el.innerHTML = `<div class="ic">${u.icon}</div><div><div class="nm">${u.name}</div><div class="ds">${u.desc}</div><div class="pips">${[0, 1, 2].map(i => `<i class="${i < lvl ? 'on' : ''}"></i>`).join('')}</div></div>`;
    const b = document.createElement('button');
    if (cost === null) { b.textContent = 'MAKS'; b.disabled = true; b.className = 'max'; }
    else { b.textContent = `${cost} H`; b.disabled = prof.coins < cost; b.addEventListener('click', () => { if (buyUpgrade(prof, key)) { account.save(true); sfx.buy(); renderHangar(); } }); }
    el.appendChild(b); list.appendChild(el);
  }
}
function drawShip(cv, up, shipId) {
  const c = cv.getContext('2d'); const W = cv.width, H = cv.height; c.clearRect(0, 0, W, H);
  const sh = SHIPS[shipId] || SHIPS.monotros;
  c.save(); c.translate(W / 2, H / 2);
  c.shadowColor = sh.glow; c.shadowBlur = 24;
  // gövde
  c.fillStyle = sh.color; drawShipShape(c, shipId, 28);
  c.shadowBlur = 0;
  // zırh plakaları
  for (let i = 0; i < sh.armor + (up.armor || 0); i++) { const aa = Math.PI / 2 + (i - (sh.armor + (up.armor || 0) - 1) / 2) * 0.5; c.fillStyle = '#ffa94d'; c.fillRect(Math.cos(aa) * 54 - 4, Math.sin(aa) * 54 - 4, 8, 8); }
  // saptırıcılar
  for (let i = 0; i < sh.deflectors + (up.deflector || 0); i++) { const ox = (i - (sh.deflectors + (up.deflector || 0) - 1) / 2) * 16; c.fillStyle = 'rgba(180,140,255,0.9)'; c.beginPath(); c.moveTo(ox, 40); c.lineTo(ox - 6, 52); c.lineTo(ox + 6, 52); c.closePath(); c.fill(); }
  // motor alevleri (engine seviyesi)
  for (let i = 0; i <= up.engine; i++) { c.fillStyle = `rgba(255,${160 - i * 30},60,${0.5 + i * 0.15})`; c.beginPath(); c.moveTo(-10 + i * 2, 30); c.lineTo(0, 52 + up.engine * 8 + i * 6); c.lineTo(10 - i * 2, 30); c.closePath(); c.fill(); }
  // kalkan halkaları
  for (let i = 0; i < up.shield; i++) { c.strokeStyle = `rgba(155,255,138,${0.8 - i * 0.2})`; c.lineWidth = 2; c.beginPath(); c.arc(0, 0, 52 + i * 7, 0, Math.PI * 2); c.stroke(); }
  // lazer namluları
  for (let i = 0; i < up.laser; i++) { c.fillStyle = '#ff5d8f'; c.fillRect(-26 + i * 24, -8 - i * 4, 4, 22); }
  // güç hücreleri
  for (let i = 0; i < up.cells; i++) { c.fillStyle = '#ffd23f'; c.beginPath(); c.arc(-16 + i * 16, 22, 4, 0, Math.PI * 2); c.fill(); }
  // zaman dilatörü (mavi çekirdek)
  c.fillStyle = up.time ? `rgba(93,228,255,${0.5 + up.time * 0.15})` : '#5de4ff'; c.beginPath(); c.arc(0, 0, 6 + up.time * 2, 0, Math.PI * 2); c.fill();
  // mıknatıs (coin yörüngesi)
  for (let i = 0; i < up.magnet; i++) { c.fillStyle = '#ffcc33'; const a = Date.now() / 600 + i * 2.1; c.beginPath(); c.arc(Math.cos(a) * 60, Math.sin(a) * 30, 4, 0, Math.PI * 2); c.fill(); }
  c.restore();
}

// ===== AYARLAR =====
function renderSettings() {
  const prof = account.profile;
  $('set-sound').checked = !prof.settings.muted;
  $('set-vibrate').checked = !!prof.settings.vibrate;
  // HEPGO hesabı: ayrı giriş yok; ilerleme HEPGO kullanıcısında saklanır
  const info = $('acct-info'); info.textContent = '';
  if (account.isLoggedIn) {
    const b = document.createElement('b'); b.textContent = `👤 ${account.user.name}`;
    info.append(b, ' olarak HEPGO oturumundasın. İlerlemen HEPGO hesabında saklanır', account.syncState === 'error' ? ' (son eşitleme başarısız)' : '', '.');
  } else {
    info.textContent = account.syncState === 'idle' ? 'HEPGO oturumu okunuyor…' : 'HEPGO oturumu bulunamadı; ilerlemen yalnız bu cihazda saklanır. Sayfayı yenileyip HEPGO\'ya giriş yap.';
  }
  renderLeaderboard();
  // görünüm
  const fsel = prof.settings.field || 'normal', ssel = prof.settings.spriteScale || 1.3;
  $('opt-field').innerHTML = Object.keys(FIELD_SIZES).map(k => `<button type="button" data-k="${k}" class="${k === fsel ? 'on' : ''}">${FIELD_SIZES[k].name}<small>${FIELD_SIZES[k].w}×${FIELD_SIZES[k].h}</small></button>`).join('');
  $('opt-scale').innerHTML = SPRITE_SCALES.map(v => `<button type="button" data-v="${v}" class="${v === ssel ? 'on' : ''}">×${v}</button>`).join('');
  $('opt-field').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { prof.settings.field = b.dataset.k; account.save(); sfx.tap(); renderSettings(); }));
  $('opt-scale').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { prof.settings.spriteScale = +b.dataset.v; renderer.spriteScale = +b.dataset.v; account.save(); sfx.tap(); renderSettings(); }));
  const s = prof.stats;
  $('stats').innerHTML = `<span>Parkur</span><b>${s.parkursCleared}/${totalParkurs()}</b><span>Toplam onur</span><b>${totalHonor(prof)}</b><span>Kazanılan HEPCOIN</span><b>${fmt(s.coinsEarned)}</b><span>Boss</span><b>${s.bossKills}</b><span>Rekor</span><b>${fmt(prof.hiScore)}</b><span>Ölüm</span><b>${s.deaths}</b>`;
}
// Şirket içi skor tablosu (HEPGO: /api/tools/volfai/leaderboard)
let lbSeq = 0;
async function renderLeaderboard() {
  const box = $('leaderboard'); const seq = ++lbSeq;
  const rows = await account.leaderboard();
  if (seq !== lbSeq) return;
  box.textContent = '';
  if (!rows.length) { box.textContent = 'Henüz skor yok — ilk parkuru bitiren sen ol!'; return; }
  rows.forEach((r, i) => {
    const s = document.createElement('span'); s.textContent = `${i + 1}. ${r.name}${String(r.user_id) === String(account.uid) ? ' (sen)' : ''}`;
    const b = document.createElement('b'); b.textContent = `${fmt(r.hi_score)} · ★${r.honor}`;
    box.append(s, b);
  });
}
$('set-sound').addEventListener('change', e => { account.profile.settings.muted = !e.target.checked; sfx.setMuted(!e.target.checked); account.save(); });
$('set-vibrate').addEventListener('change', e => { account.profile.settings.vibrate = e.target.checked; account.save(); });
$('btn-reset').addEventListener('click', () => { if (confirm('Tüm ilerleme, HEPCOIN ve yükseltmeler silinecek. Emin misin?')) { account.resetProgress(); selLevel = null; renderSettings(); } });

// ===== düğmeler =====
tap($('btn-start'), () => { selLevel = null; showScreen('levels'); });
tap($('btn-hangar-t'), () => showScreen('hangar'));
tap($('btn-settings-t'), () => showScreen('settings'));
tap($('btn-again'), () => game.startParkur(game.L, game.p));
tap($('btn-menu'), () => { selLevel = game.L; game.toMenu(); });
tap($('btn-quit'), () => { selLevel = game.L; game.toMenu(); });
tap($('btn-clear-levels'), () => { selLevel = game.L; game.toMenu(); });
tap($('btn-next'), () => { const r = game.lastResult; if (!r) return; if (r.p < r.n) game.startParkur(r.L, r.p + 1); else if (r.L < LEVEL_COUNT) game.startParkur(r.L + 1, 1); });
tap($('btn-resume'), () => game.togglePause());
tap($('btn-pause'), () => game.togglePause());
document.querySelectorAll('.back').forEach(b => tap(b, () => { const t = b.dataset.back === 'prev' ? (['title', 'levels'].includes(prevScreen) ? prevScreen : 'title') : b.dataset.back; if (t === 'levels') game.toMenu(); else showScreen(t); }));
window.addEventListener('keydown', e => { if (e.key === 'p' || e.key === 'P' || e.key === 'Escape') game.togglePause(); });
document.addEventListener('visibilitychange', () => { if (document.hidden && game.state === STATE.PLAY) game.togglePause(); });
for (const k in screens) screens[k].addEventListener('touchstart', e => e.stopPropagation(), { passive: true });
$('hud').addEventListener('touchstart', e => e.stopPropagation(), { passive: true });
account.onChange(() => { if (currentScreen === 'hangar') renderHangar(); if (currentScreen === 'title') renderTitleUser(); });
// HEPGO oturumu/sunucu profili geldiğinde açık ekranı tazele (hangar/ayarlar/bölümler sunucudaki ilerlemeyi göstersin)
account.ready.then(() => { renderer.spriteScale = account.profile.settings.spriteScale || 1.3; sfx.setMuted(!!account.profile.settings.muted); if (['title', 'levels', 'hangar', 'settings'].includes(currentScreen)) { selLevel = null; showScreen(currentScreen); } });

showScreen('title');

// --- döngü ---
let last = performance.now();
function frame(now) {
  const dt = (now - last) / 1000; last = now;
  if (game.def && ![STATE.TITLE, STATE.MENU].includes(game.state)) {
    game.update(dt, input);
    handleEvents();
    renderer.draw(game, input);
    updateHud();
  } else {
    handleEvents();
    renderer.drawStick(input);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// HEPGO sürümünde service worker yok: oyun HEPGO oturumuyla çevrimiçi oynanır; sw.js önbelleği güncellemeleri geciktirmesin.
