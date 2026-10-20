// Master Tool web başlatıcısı (mastertool.download/uygulamalar) — masaüstü Master Tool ana ekranının (src/renderer/app.js) web karşılığı.
// Katalog: GET /api/mt/apps?web=1 (uygulamalar, araçlar, oyunlar; web sürümü yolu ve kişiye özel indirme bağlantısı).
// Web sürümü olan uygulamalar aynı sayfada sekmede açılır (iframe; YALNIZ aynı köken /web/<slug>/ ve /oyunlar/<slug>/), ayrıca yeni sekmede.
// Araçların (IP Tools …) web sürümü yoktur: yalnız İndir. Oturum yoksa sayfa içinde giriş / kayıt (hesap.js ile aynı akış: şifre tarayıcıda
// PBKDF2 ile türetilir, sunucuya düz gitmez). Metinler Türkçe kaynak; kit.js sözlüğü (mt + hesap) ile t(); dil değişince yeniden çizilir.
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const t = (s, v) => (window.mtKit ? window.mtKit.t(s, v) : s.replace(/\{(\w+)\}/g, (m, k) => (v && k in v ? v[k] : m)));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ltr = s => `⁦${s}⁩`;   // sağdan sola dillerde "40 MB" ters görünmesin
const enc = new TextEncoder();
const b64 = buf => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const API = '/api/mt';
const lang = () => window.mtKit?.lang || 'tr';

const ICONS = {
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  bolt: '<path d="M13 3 4 14h7l-1 7 9-11h-7z"/>',
  home: '<path d="M3 11l9-7 9 7M5 10v10h14V10"/>',
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
const h = html => { const tpl = document.createElement('template'); tpl.innerHTML = html.trim(); return tpl.content.firstElementChild; };
function fmtSize(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return ltr(`${(n < 10 && i ? n.toFixed(1) : Math.round(n)).toLocaleString(lang())} ${u[i]}`);
}

async function api(path, opts = {}) {
  const r = await fetch(path, { method: opts.method || 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-SSHM': '1' }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let d = null;
  try { d = await r.json(); } catch { /* boş */ }
  if (!r.ok) {
    const e = new Error(d && (d.message || d.detail) ? t(d.message || d.detail) : t('Hata ({n})', { n: r.status }));
    e.code = d && d.code; e.status = r.status; throw e;
  }
  return d;
}
async function authHash(password, kdf) {   // hesap.js ve uygulamalarla aynı türetme (docs/sshmaster-api.md v2)
  const pw = enc.encode(password);
  const base = await crypto.subtle.importKey('raw', pw, 'PBKDF2', false, ['deriveBits']);
  const master = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: unb64(kdf.salt), iterations: kdf.iter }, base, 256);
  const mk = await crypto.subtle.importKey('raw', master, 'PBKDF2', false, ['deriveBits']);
  return b64(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: pw, iterations: 1 }, mk, 256));
}

// Yalnız aynı kökende /web/<slug>/ ve /oyunlar/<slug>/ çerçevede açılır; başka her adres yeni sekmede.
function frameSrc(u) {
  try {
    const x = new URL(u, location.origin);
    if (x.origin === location.origin && /^\/(web|oyunlar)\/[a-z0-9-]+\/$/.test(x.pathname)) return x.pathname;
  } catch { /* geçersiz adres */ }
  return null;
}
const safeHref = u => { try { const x = new URL(u, location.origin); return /^https?:$/.test(x.protocol) ? x.href : '#'; } catch { return '#'; } };

// ---------------------------------------------------------------- durum
const S = { user: null, apps: [], launcher: null, tabs: [], active: 'home', mode: 'loading', authView: 'login' };
const app = $('#app'), content = $('#content'), tabbar = $('#tabbar'), frames = $('#frames');

function toast(text, type = '') {
  let box = $('.toasts');
  if (!box) { box = h('<div class="toasts"></div>'); document.body.append(box); }
  const el = h(`<div class="toast ${type}">${esc(text)}</div>`);
  box.append(el);
  setTimeout(() => el.remove(), type === 'err' ? 8000 : 3500);
}

let ctxEl = null;
const closeCtx = () => { ctxEl?.remove(); ctxEl = null; };
function contextMenu(x, y, items) {
  closeCtx();
  ctxEl = h('<div class="ctx" role="menu"></div>');
  for (const it of items.filter(Boolean)) {
    if (it === '-') { ctxEl.append(h('<hr>')); continue; }
    const el = it.href
      ? h(`<a role="menuitem" href="${esc(it.href)}" ${it.blank ? 'target="_blank" rel="noopener"' : ''}>${icon(it.icon)}<span>${esc(it.label)}</span></a>`)
      : h(`<button type="button" role="menuitem" class="${it.danger ? 'danger' : ''}${it.disabled ? ' dis' : ''}">${icon(it.icon)}<span>${esc(it.label)}</span></button>`);
    if (!it.href && !it.disabled) el.onclick = () => { closeCtx(); it.action(); };
    if (it.href) el.addEventListener('click', closeCtx);
    ctxEl.append(el);
  }
  document.body.append(ctxEl);
  const r = ctxEl.getBoundingClientRect();
  ctxEl.style.left = `${Math.max(6, Math.min(x, innerWidth - r.width - 6))}px`;
  ctxEl.style.top = `${Math.max(6, Math.min(y, innerHeight - r.height - 6))}px`;
}
addEventListener('click', e => { if (ctxEl && !ctxEl.contains(e.target)) closeCtx(); }, true);
addEventListener('keydown', e => { if (e.key === 'Escape') closeCtx(); });
addEventListener('resize', closeCtx);

// ---------------------------------------------------------------- üst şerit
function renderTop() {
  const signed = !!S.user;
  const n = S.apps.filter(a => a.web).length, total = S.apps.filter(a => a.kind !== 'web').length;
  $('#stats').textContent = signed ? t('{n}/{total} uygulama tarayıcıda açılır', { n, total }) : t('Mastertool hesabınızla giriş yapın');
  const rb = $('#btnRefresh');
  rb.classList.toggle('hidden', !signed);
  rb.innerHTML = icon('refresh'); rb.title = rb.ariaLabel = t('Yenile');
  const chip = $('#btnAccount');
  chip.classList.toggle('hidden', !signed);
  if (signed) {
    const name = S.user.name || S.user.email || '?';
    chip.querySelector('.ac-avatar').textContent = name.trim().slice(0, 1).toLocaleUpperCase(lang());
    chip.querySelector('.ac-name').textContent = name;
    chip.title = S.user.email || '';
  }
  $('#portal').title = t('Ana sayfa');
}
$('#btnRefresh').onclick = async () => {
  const b = $('#btnRefresh');
  b.disabled = true; b.innerHTML = '<span class="spin"></span>';
  try { await loadApps(); } finally { b.disabled = false; b.innerHTML = icon('refresh'); }
};
$('#btnAccount').onclick = e => {
  const r = e.currentTarget.getBoundingClientRect(), rtl = document.documentElement.dir === 'rtl';
  contextMenu(rtl ? r.left : r.right - 240, r.bottom + 6, [
    { label: S.user?.email || '', icon: 'user', disabled: true },
    '-',
    { label: t('Hesabım'), icon: 'open', href: '/hesabim' },
    { label: t('Ana sayfa'), icon: 'home', href: '/' },
    '-',
    { label: t('Çıkış'), icon: 'logout', danger: true, action: logout },
  ]);
};
async function logout() {
  await api(`${API}/auth/logout`, { method: 'POST' }).catch(() => {});
  location.reload();
}

// ---------------------------------------------------------------- kutucuklar
const GROUPS = a => (a.kind === 'web' ? (a.group === 'apps' ? 'apps' : 'games') : a.group === 'tools' || a.group === 'launcher' ? a.group : 'apps');
const desc = a => { const d = a.description; return (d && typeof d === 'object' ? d[lang()] || d.en || d.tr : d) || DESC[a.app]?.() || ''; };
const DESC = {   // uygulamaların kısa tanımı (masaüstü Master Tool sözlüğüyle aynı)
  sm: () => t('SSH bağlantıları, terminal ve SFTP'), fm: () => t('FTP, FTPS ve SFTP dosya yöneticisi'), sq: () => t('Veritabanı istemcisi ve sorgu düzenleyici'),
  np: () => t('Kod ve metin düzenleyici'), cv: () => t('Video, resim ve ses dönüştürücü'),
};
const iconOf = a => a.icon_svg || `/brand/${a.app}.svg`;
const off = a => a.kind !== 'web' && a.license && a.license !== 'AKTIF';

function renderHome() {
  const g = { apps: [], tools: [], games: [] };
  S.apps.forEach(a => g[GROUPS(a)].push(a));
  const sec = (key, title, hint, list, cls = '') => (list.length ? `<section class="group ${cls}">
      <div class="section-title"><span>${esc(title)}</span><span class="count">${list.length}</span><span class="hint">${esc(hint)}</span></div>
      <div class="tiles" data-group="${key}"></div></section>` : '');
  content.innerHTML = sec('apps', t('Uygulamalar'), t('Tarayıcıda açılır ya da Windows için indirilir'), g.apps)
    + sec('tools', t('Araçlar'), t('Yalnız Windows için; tarayıcı sürümü yok'), g.tools, 'tools-group')
    + sec('games', t('Oyunlar'), t('Tarayıcıda oynanır; Mastertool hesabınızla giriş yapılır'), g.games, 'tools-group')
    + (S.launcher?.release && S.launcher.download_url ? `<section class="group tools-group"><div class="section-title"><span>Master Tool</span><span class="hint">${esc(t('Masaüstü başlatıcı: tüm uygulamaları Windows\'ta tek pencereden kurun ve açın'))}</span></div>
      <div class="tiles" data-group="launcher"></div></section>` : '');
  for (const [k, list] of Object.entries(g)) { const el = content.querySelector(`[data-group="${k}"]`); if (el) list.forEach(a => el.append(tile(a))); }
  const L = content.querySelector('[data-group="launcher"]');
  if (L) L.append(tile({ app: 'mt', name: 'Master Tool', group: 'launcher', icon_svg: '/brand/mt.svg', release: S.launcher.release, download_url: S.launcher.download_url,
    description: null, license: 'AKTIF' }));
}

function tile(a) {
  const g = GROUPS(a), r = a.release, dis = off(a);
  const webSrc = a.web && frameSrc(a.web);
  const site = a.kind === 'web';   // tarayıcıda açılan kayıt: oyun (games) ya da kendi sitesindeki web uygulaması (MASTERWORLD, group 'apps')
  const gameFrame = site ? frameSrc(a.url) : null;
  const play = g === 'games' ? t('Oyna') : t('Aç');
  const canDl = !dis && r && a.download_url;
  let cls = 'tile', sub = '', subCls = 't-sub', acts = '';
  if (dis) { cls += ' disabled'; sub = `${icon('lock')}<span>${esc(t('Hesabınızda kapalı'))}</span>`; subCls += ' muted'; }
  else if (site) { cls += ' web'; sub = `${icon('globe')}<span>${esc(t('Tarayıcıda açılır'))}</span>`; }
  else if (webSrc) { cls += ' web'; sub = `${icon('globe')}<span>${esc(t('Web + Windows'))}${r ? ` · ${esc(t('Sürüm {version}', { version: r.version }))}` : ''}</span>`; }
  else if (r) { cls += ' dl'; sub = `${icon('monitor')}<span>${esc(t('Sürüm {version}', { version: r.version }))}${r.size ? ` · ${fmtSize(r.size)}` : ''}</span>`; }
  else { cls += ' unreleased'; sub = esc(t('Yakında')); subCls += ' warn'; }
  if (S.tabs.some(x => x.id === a.app)) cls += ' running';
  if (!dis) {
    if (site) {
      acts += `<button class="btn sm primary" data-act="open" type="button">${icon('play')}${esc(play)}</button>`;
      acts += `<a class="icon-btn" href="${esc(safeHref(a.url))}" target="_blank" rel="noopener" title="${esc(t('Yeni sekmede aç'))}" aria-label="${esc(t('Yeni sekmede aç'))}">${icon('open')}</a>`;
    } else {
      if (webSrc) {
        acts += `<button class="btn sm primary" data-act="open" type="button">${icon('play')}${esc(t('Aç'))}</button>`;
        acts += `<a class="icon-btn" href="${esc(webSrc)}" target="_blank" rel="noopener" title="${esc(t('Yeni sekmede aç'))}" aria-label="${esc(t('Yeni sekmede aç'))}">${icon('open')}</a>`;
      }
      if (canDl) acts += webSrc
        ? `<a class="icon-btn" href="${esc(a.download_url)}" title="${esc(t('İndir (.exe)'))}" aria-label="${esc(t('İndir (.exe)'))}">${icon('download')}</a>`
        : `<a class="btn sm ${g === 'launcher' ? 'primary' : ''}" href="${esc(a.download_url)}">${icon('download')}${esc(t('İndir (.exe)'))}</a>`;
    }
  }
  const noWeb = g === 'tools' ? (a.app === 'ip' ? t('Ağ taraması güvenlik nedeniyle web sürümünde sunulmaz; yalnız Windows için indirilir') : t('Web sürümü yok; yalnız Windows için indirilir')) : '';
  const note = g === 'tools' ? (a.app === 'ip' ? noWeb : t('Yalnız Windows için; tarayıcı sürümü yok')) : '';
  const el = h(`<div class="${cls}" data-app="${esc(a.app)}" tabindex="0" title="${esc(noWeb)}">
    <div class="ic-wrap"><img class="ic" src="${esc(iconOf(a))}" alt="" loading="lazy">${webSrc || gameFrame ? `<span class="badge-web">${icon('globe')}</span>` : ''}</div>
    <div class="t-name">${esc(a.name)}</div>
    <div class="${subCls}">${sub}</div>
    <div class="t-desc">${esc(g === 'launcher' ? t('Tüm Mastertool uygulamalarını tek pencereden kurun, açın ve güncelleyin; bir kez giriş yapın, hepsi açılsın.') : desc(a))}</div>
    ${note ? `<div class="t-note">${icon('monitor')}<span>${esc(note)}</span></div>` : ''}
    <div class="t-act">${acts}</div>
  </div>`);
  const primary = () => {
    if (dis) { toast(t('Bu uygulamanın kullanımı hesabınız için kapatılmış. Bilgi için Destek sekmesinden talep açabilirsiniz.'), 'err'); return; }
    if (site) { if (gameFrame) openTab(a, gameFrame); else window.open(safeHref(a.url), '_blank', 'noopener'); return; }
    if (webSrc) { openTab(a, webSrc); return; }
    if (canDl) location.href = a.download_url;
  };
  el.querySelector('[data-act="open"]')?.addEventListener('click', e => { e.stopPropagation(); primary(); });
  el.addEventListener('click', e => { if (!e.target.closest('.t-act a, .t-act button')) primary(); });
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); primary(); } });
  el.addEventListener('contextmenu', e => {
    e.preventDefault();
    contextMenu(e.clientX, e.clientY, [
      (webSrc || gameFrame) && !dis && { label: play, icon: 'play', action: primary },
      site && !gameFrame && !dis && { label: play, icon: 'play', href: safeHref(a.url), blank: true },
      (webSrc || gameFrame) && !dis && { label: t('Yeni sekmede aç'), icon: 'open', href: webSrc || gameFrame, blank: true },
      canDl && { label: t('İndir (.exe)'), icon: 'download', href: a.download_url },
      canDl && r.portable && { label: t('Taşınabilir sürüm'), icon: 'download', href: `${a.download_url}?tur=portable` },
      a.site && '-',
      a.site && { label: t('Web sitesi'), icon: 'globe', href: safeHref(a.site), blank: true },
    ]);
  });
  return el;
}

// ---------------------------------------------------------------- sekmeler (iframe)
function openTab(a, src) {
  const id = a.app;
  if (!S.tabs.some(x => x.id === id)) {
    S.tabs.push({ id, name: a.name, icon: iconOf(a), src });
    const f = document.createElement('iframe');
    f.dataset.tab = id; f.title = a.name; f.src = src;
    f.setAttribute('allow', 'clipboard-read; clipboard-write; fullscreen');
    f.setAttribute('referrerpolicy', 'same-origin');
    frames.append(f);
  }
  const el = content.querySelector(`.tile[data-app="${CSS.escape(id)}"]`);
  if (el) { el.classList.add('launching'); setTimeout(() => el.classList.remove('launching'), 900); }
  activate(id);
}
function closeTab(id) {
  S.tabs = S.tabs.filter(x => x.id !== id);
  frames.querySelector(`iframe[data-tab="${CSS.escape(id)}"]`)?.remove();
  if (S.active === id) activate(S.tabs.length ? S.tabs[S.tabs.length - 1].id : 'home'); else renderTabs();
}
function activate(id) {
  S.active = S.tabs.some(x => x.id === id) ? id : 'home';
  app.classList.toggle('framed', S.active !== 'home');
  frames.querySelectorAll('iframe').forEach(f => f.classList.toggle('on', f.dataset.tab === S.active));
  const slug = S.active !== 'home' && (S.tabs.find(x => x.id === S.active)?.src.match(/^\/(?:web|oyunlar)\/([a-z0-9-]+)\//) || [])[1];
  history.replaceState(null, '', location.pathname + location.search + (slug ? `#${slug}` : ''));
  renderTabs();
  if (S.active === 'home') content.querySelectorAll('.tile').forEach(el => el.classList.toggle('running', S.tabs.some(x => x.id === el.dataset.app)));
}
function renderTabs() {
  tabbar.classList.toggle('hidden', !S.tabs.length);
  tabbar.innerHTML = `<button type="button" class="tab home ${S.active === 'home' ? 'on' : ''}" data-tab="home">${icon('grid')}<span class="tn">${esc(t('Uygulamalar'))}</span></button>`
    + S.tabs.map(x => `<div class="tab ${S.active === x.id ? 'on' : ''}" data-tab="${esc(x.id)}" role="button" tabindex="0">
        <img src="${esc(x.icon)}" alt=""><span class="tn">${esc(x.name)}</span>
        <a class="icon-btn" href="${esc(x.src)}" target="_blank" rel="noopener" title="${esc(t('Yeni sekmede aç'))}" aria-label="${esc(t('Yeni sekmede aç'))}">${icon('open')}</a>
        <button type="button" class="icon-btn" data-close="${esc(x.id)}" title="${esc(t('Kapat'))}" aria-label="${esc(t('Kapat'))}">${icon('x')}</button></div>`).join('');
  tabbar.querySelectorAll('[data-tab]').forEach(el => {
    el.addEventListener('click', e => { if (!e.target.closest('a, [data-close]')) activate(el.dataset.tab); });
    el.addEventListener('keydown', e => { if (e.key === 'Enter') activate(el.dataset.tab); });
  });
  tabbar.querySelectorAll('[data-close]').forEach(b => { b.onclick = e => { e.stopPropagation(); closeTab(b.dataset.close); }; });
  tabbar.querySelectorAll('a.icon-btn').forEach(a => a.addEventListener('click', () => {   // yeni sekmede açılan uygulama burada kapanır
    const id = a.closest('[data-tab]').dataset.tab; setTimeout(() => closeTab(id), 0);
  }));
}
$('#home').addEventListener('click', e => { if (S.user) { e.preventDefault(); activate('home'); } });

// ---------------------------------------------------------------- giriş / kayıt
function renderAuth() {
  app.classList.remove('framed');
  tabbar.classList.add('hidden');
  const reg = S.authView === 'register';
  content.innerHTML = `<div class="login-wrap"><div class="login">
    <div class="lbrand"><img src="/brand/mt.svg" alt=""><h1>Master Tool</h1>
      <p>${esc(reg ? t('Tek Mastertool hesabıyla tüm Mastertool uygulamalarını indirin, kayıtlarınızı cihazlar arasında şifreli eşitleyin.') : t('Mastertool hesabınızla giriş yapın'))}</p></div>
    <form id="f" autocomplete="on" novalidate>
      ${reg ? `<div class="field"><label for="n">${esc(t('Ad soyad'))}</label><input class="input" id="n" autocomplete="name" required></div>` : ''}
      <div class="field"><label for="e">${esc(t('E-posta'))}</label><input class="input" id="e" type="email" autocomplete="${reg ? 'email' : 'username'}" spellcheck="false" required></div>
      <div class="field"><label for="p">${esc(t('Şifre'))}</label><div class="pw-wrap"><input class="input" id="p" type="password" autocomplete="${reg ? 'new-password' : 'current-password'}" required>
        <button class="icon-btn" id="eye" type="button" title="${esc(t('Şifreyi göster'))}" aria-label="${esc(t('Şifreyi göster'))}">${icon('eye')}</button></div></div>
      ${reg ? `<div class="hint-s">${esc(t('En az 8 karakter. Şifreniz bu tarayıcıda şifrelenir; sunucuya düz hâliyle gitmez.'))}</div>
        <div class="field"><label for="p2">${esc(t('Şifre (tekrar)'))}</label><input class="input" id="p2" type="password" autocomplete="new-password" required></div>`
      : `<div class="row-end"><a href="/sifremi-unuttum">${esc(t('Şifremi unuttum'))}</a></div>`}
      <div id="m"></div>
      <button class="btn primary submit" id="b" type="submit">${esc(reg ? t('Hesap oluştur') : t('Giriş yap'))}</button>
      ${reg ? '' : `<div class="sso-hint">${icon('bolt')}<span>${esc(t('Bir kez giriş yapın; tüm web uygulamaları bu hesapla açılır.'))}</span></div>`}
      <div class="register">${reg ? `<a href="#" id="sw">${esc(t('Zaten hesabım var'))}</a>` : `${esc(t('Hesabınız yok mu?'))} <a href="#" id="sw">${esc(t('Hesap oluştur'))}</a>`}</div>
    </form></div></div>`;
  $('#sw').onclick = e => { e.preventDefault(); S.authView = reg ? 'login' : 'register'; renderAuth(); };
  $('#eye').onclick = () => { const p = $('#p'); p.type = p.type === 'password' ? 'text' : 'password'; };
  const m = $('#m'), b = $('#b');
  const msg = (text, cls = 'error') => { m.innerHTML = text ? `<div class="${cls}">${text}</div>` : ''; };
  const busy = on => { b.disabled = on; b.innerHTML = on ? `<span class="spin"></span>${esc(t('Lütfen bekleyin…'))}` : esc(reg ? t('Hesap oluştur') : t('Giriş yap')); };
  $('#f').onsubmit = async ev => {
    ev.preventDefault();
    const email = $('#e').value.trim(), p = $('#p').value;
    if (!email || !p) return msg(esc(t('Geçerli bir e-posta adresi girin')));
    if (reg) {
      const name = $('#n').value.trim();
      if (p.length < 8) return msg(esc(t('Şifre en az 8 karakter olmalı')));
      if (p !== $('#p2').value) return msg(esc(t('Şifreler aynı değil')));
      busy(true);
      try {
        const kdf = (await api(`${API}/auth/prelogin`, { method: 'POST', body: { email } })).kdf;
        await api(`${API}/auth/register`, { method: 'POST', body: { name, email, auth_hash: await authHash(p, kdf), brand: 'mt' } });
        content.querySelector('.login form').innerHTML = `<div class="okmsg"><b>${esc(t('E-postanızı kontrol edin'))}</b><br>${t('{email} adresine bir doğrulama bağlantısı gönderdik. Bağlantıya tıklayınca hesabınız açılır ve indirme sayfanıza yönlenirsiniz. Bağlantı 24 saat geçerlidir.', { email: `<b>${esc(email)}</b>` })}</div>
          <div class="register"><a href="#" id="sw2">${esc(t('Girişe dön'))}</a></div>`;
        $('#sw2').onclick = e => { e.preventDefault(); S.authView = 'login'; renderAuth(); };
      } catch (e) { msg(esc(e.message)); busy(false); }
      return;
    }
    busy(true);
    try {
      const kdf = (await api(`${API}/auth/prelogin`, { method: 'POST', body: { email } })).kdf;
      const r = await api(`${API}/auth/login`, { method: 'POST', body: { email, auth_hash: await authHash(p, kdf), client: 'web' } });
      S.user = r.user;
      await loadApps();
    } catch (e) {
      msg(esc(e.message) + (e.code === 'unverified' ? ` <a href="#" id="rs">${esc(t('Doğrulama e-postasını yeniden gönder'))}</a>` : ''));
      const rs = $('#rs');
      if (rs) rs.onclick = async x => { x.preventDefault(); await api(`${API}/auth/resend-verify`, { method: 'POST', body: { email, brand: 'mt' } }).catch(() => {}); msg(esc(t('Doğrulama e-postası yeniden gönderildi')), 'okmsg'); };
      busy(false);
    }
  };
}

// ---------------------------------------------------------------- yükleme
async function loadApps() {
  try {
    const d = await api(`${API}/apps?web=1`);
    S.apps = d.apps || []; S.launcher = d.launcher || null; S.mode = 'apps';
  } catch (e) {
    if (e.status === 401 || e.status === 403) { S.user = null; S.mode = 'auth'; } else { S.mode = 'error'; S.err = e.message; }
  }
  draw();
  const want = (location.hash || '').slice(1);   // /uygulamalar#sshmaster → o uygulama açık gelir
  if (S.mode === 'apps' && /^[a-z0-9-]+$/.test(want) && !S.tabs.length) {
    const a = S.apps.find(x => (x.web && x.web === `/web/${want}/`) || (x.kind === 'web' && frameSrc(x.url) === `/oyunlar/${want}/`));
    if (a && !off(a)) openTab(a, a.web ? frameSrc(a.web) : frameSrc(a.url));
  }
}
function draw() {
  document.title = `${S.mode === 'auth' ? t('Giriş') : t('Uygulamalar')} — Master Tool`;
  renderTop();
  if (S.mode === 'auth') return renderAuth();
  if (S.mode === 'error') { content.innerHTML = `<div class="empty-note">${esc(S.err || t('Bağlantı kurulamadı. Yeniden deneyin.'))}</div>`; return; }
  if (S.mode === 'apps') { renderHome(); renderTabs(); activate(S.active); }
}
async function boot() {
  try { S.user = (await api(`${API}/session`)).user; } catch { S.user = null; }
  if (!S.user) { S.mode = 'auth'; draw(); return; }
  await loadApps();
}
// kit sözlüğü yüklenip 'mt-lang' yayınlanınca başla; dil değişince yeniden çiz (açık sekmeler / iframe'ler korunur)
let started = false;
addEventListener('mt-lang', () => { if (!started) { started = true; boot(); } else if (S.mode === 'apps' || S.mode === 'error') draw(); else if (S.mode === 'auth') { renderTop(); renderAuth(); } });
setTimeout(() => { if (!started) { started = true; boot(); } }, 1500);
