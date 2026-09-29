// Uygulama kabuğu: oturum, üst/alt bölüm, ana sayfa modül düğmeleri ve yönlendirme.
import { api, logActivity } from './api.js';
import { icons } from './icons.js';
import { statusBar, stopStatusBar } from './statusbar.js';
import { chatButton, closeChat, setChatUser } from './chat.js';
import { eventOfNotification, playEvent } from './sounds.js';
import { applySettings, desktopNotify, flashMs, flashOn } from './prefs.js';
import { renderSettings } from './modules/settings.js';
import { calendarPanel } from './modules/crm.js';
import { enableDictation } from './dictation.js';
import { avatar, clear, field, h, modal, onLeave, pageHead, pref, setPref, stopTimers, svgIcon, toast, toastError } from './ui.js';
import { createGlobe } from './globe.js';
import { hideTip } from './plane.js';
import * as users from './modules/users.js';
import * as orders from './modules/orders.js';
import * as production from './modules/production.js';
import * as warehouse from './modules/warehouse.js';
import * as stock from './modules/stock.js';
import * as fieldMod from './modules/field.js';
import * as printers from './modules/printers.js';
import * as tools from './modules/tools.js';
import * as products from './modules/products.js';
import * as admin from './modules/admin.js';
import * as alertsPage from './modules/alerts.js';
import { renderDashboard } from './modules/dashboard.js';
import { renderMyCalls } from './modules/calls.js';
import { accountChooser, accountToken, rememberAccount } from './accounts.js';
import * as companies from './modules/companies.js';
import * as documents from './modules/documents.js';
import * as signPage from './modules/sign.js';
import * as secretariat from './modules/secretariat.js';
import * as security from './modules/security.js';
import * as reportsMod from './modules/reports.js';
import * as announcements from './modules/announcements.js';

// Ana sayfadaki modül düğmeleri; yeni modül eklemek için bu listeye bir satır eklenir.
// tone: 'red' → yalnızca yöneticilere açık modüller kırmızı tonlarda gösterilir.
// menu: true → ana ekranda ve modül menüsünde değil, sağ üstteki kullanıcı menüsünde gösterilir.
const MODULES = [
  { key: 'admin', title: 'Yönetim', mod: admin, tone: 'red' },
  { key: 'production', title: 'Üretim Yönetimi', mod: production },
  { key: 'orders', title: 'Sipariş Yönetimi', mod: orders },
  { key: 'warehouse', title: 'Depo Yönetimi', mod: warehouse },
  { key: 'stock', title: 'Stok Yönetimi', mod: stock },
  { key: 'field', title: 'Saha Yönetimi', mod: fieldMod },
  { key: 'printers', title: 'Yazıcı Yönetimi', mod: printers },
  { key: 'products', title: 'Ürün Yönetimi', mod: products, tone: 'red' },
  { key: 'companies', title: 'Firma Yönetimi', mod: companies },
  { key: 'documents', title: 'Evrak Yönetimi', mod: documents },
  { key: 'secretariat', title: 'Sekreterya', mod: secretariat },
  { key: 'security', title: 'Güvenlik', mod: security },
  { key: 'reports', title: 'Raporlar', mod: reportsMod },
  { key: 'announcements', title: 'Duyurular', mod: announcements },
  { key: 'tools', title: 'Araçlar', mod: tools, menu: true },
  { key: 'users', title: 'Kullanıcı Yönetimi', mod: users, tone: 'red', menu: true },
];

const root = document.getElementById('app');
const ctx = { user: null, meta: null };

async function boot() {
  try {
    ctx.meta = await api.get('/api/meta');
    ctx.user = await api.get('/api/auth/me');
  } catch {
    ctx.user = null;
  }
  ctx.user ? renderShell() : renderLogin();
}

window.addEventListener('caymaz:unauthorized', () => {
  if (ctx.user) {
    ctx.user = null;
    toast('Oturum süreniz doldu, lütfen tekrar giriş yapın', 'err');
    renderLogin();
  }
});

// ---------- Giriş ----------
function renderLogin() {
  currentPage = null;
  stopTimers();
  clearInterval(alertTimer);
  clearInterval(notifyTimer);
  const username = h('input', { class: 'input', type: 'email', autocomplete: 'username', required: true });
  const password = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
  const submit = h('button', { class: 'btn primary lg', type: 'submit' }, 'Giriş Yap');
  const done = async deviceToken => {   // giriş başarılı: kabuk açılır, hesap bu cihazda hatırlanır
    ctx.user = await api.get('/api/auth/me');
    if (deviceToken) rememberAccount(ctx.user, deviceToken);
    renderShell();
  };
  const body = h('div', { class: 'login-body' });
  const form = h('form', { class: 'card login' },
    h('img', { src: '/static/img/logo-login.png', alt: ctx.meta?.company || '' }),
    h('h1', null, 'Fabrika Yönetim Sistemi'),
    body);
  const showForm = () => {
    clear(body, field('Kullanıcı adı', username), field('Şifre', password), submit);
    username.focus();
  };
  form.addEventListener('submit', async e => {
    if (!body.contains(username)) return;   // hesap listesi / PIN kendi formunu yönetir
    e.preventDefault();
    submit.disabled = true;
    try {
      const r = await api.post('/api/auth/login', { username: username.value, password: password.value, device_token: accountToken(username.value.trim()) });
      await done(r.device_token);
    } catch (err) {
      toastError(err);
    } finally {
      submit.disabled = false;
    }
  });
  const canvas = h('canvas', { class: 'globe-bg', 'aria-hidden': 'true' });
  clear(root, h('div', { class: 'login-wrap' }, canvas, form));
  const globe = createGlobe(canvas, { size: 0.46, speed: 7 });
  onLeave(() => globe.destroy());
  showForm();
  accountChooser(body, { onLogin: done, onOther: showForm }).catch(() => {});
}

// ---------- Kabuk ----------
let view, scroller;
// Açılır menüler (modül ızgarası, kullanıcı menüsü) dışarı tıklanınca ya da Esc ile kapanır.
const popups = new Set();
const closePopups = except => popups.forEach(p => { if (p !== except) p.hidden = true; });
document.addEventListener('click', () => closePopups());
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePopups(); });

function popup(button, panel) {
  panel.hidden = true;
  popups.add(panel);
  button.addEventListener('click', e => {
    e.stopPropagation();
    closePopups(panel);
    panel.hidden = !panel.hidden;
    button.setAttribute('aria-expanded', String(!panel.hidden));
  });
  panel.addEventListener('click', e => e.stopPropagation());
}

// Google tarzı modül ızgarası: yalnızca kullanıcının girebildiği modüller
function appsLauncher() {
  const allowed = MODULES.filter(m => !m.menu && ctx.user.modules.includes(m.key));
  const btn = h('button', { class: 'icon-btn', 'aria-label': 'Modüller', title: 'Modüller', 'aria-haspopup': 'menu' },
    svgIcon(icons.apps));
  const current = () => location.hash.replace(/^#\/?/, '').split('/')[0];
  const panel = h('div', { class: 'dropdown apps-panel', role: 'menu' });
  const fill = () => clear(panel,
    allowed.length ? h('div', { class: 'apps-grid' }, allowed.map(m =>
      h('a', { class: `app-tile ${m.tone ? `tone-${m.tone}` : ''} ${current() === m.key ? 'on' : ''}`, href: `#/${m.key}`, role: 'menuitem',
        onclick: () => { panel.hidden = true; } },
        h('span', { class: 'ico' }, svgIcon(icons[m.key])),
        h('span', null, m.title))))
      : h('div', { class: 'empty' }, 'Erişebildiğiniz modül yok'));
  btn.addEventListener('click', () => {   // popup'tan önce çalışır: panel henüz gizliyse şimdi açılıyor
    fill();
    if (panel.hidden) logActivity({ event: 'open', path: location.hash, title: 'Modül menüsü' });
  });
  popup(btn, panel);
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

// Yeni uyarı / bildirim: sağ üst köşede kısa kutu, 3 sn sonra gizlenir. İlk yüklemede var olanlar "görüldü" sayılır;
// sonra yeni bir başlık, artan sayı ya da listede yeni bir ad gelirse gösterilir. Kutuya tıklanınca ilgili sayfa açılır.
const seen = {};
let flashBox;
function announce(kind, items) {
  const prev = seen[kind];
  seen[kind] = new Map(items.map(i => [i.key, { count: i.count, names: new Set(i.names) }]));
  if (!prev) return;
  for (const i of items) {
    const p = prev.get(i.key);
    const fresh = p ? i.names.filter(n => !p.names.has(n)) : i.names;
    if (p && i.count <= p.count && !fresh.length) continue;
    playEvent(kind === 'alerts' ? (i.critical ? 'critical' : 'alert') : eventOfNotification(i.key));
    const names = fresh.length ? fresh : i.names;
    if (flashOn()) flash(kind, i, names);
    desktopNotify(i.title, names.slice(0, 3).join(', '), () => { location.hash = kind === 'alerts' ? `#/alerts/${i.key}` : i.href; });
  }
}
function flash(kind, item, names) {
  flashBox ??= document.body.appendChild(h('div', { class: 'flash-stack', 'aria-live': 'polite' }));
  const alert = kind === 'alerts';
  const href = alert ? `#/alerts/${item.key}` : item.href;
  const box = h('a', { class: `flash ${alert ? `alert ${item.level || ''} ${item.critical ? 'critical' : ''}` : 'notify'}`, href,
    onclick: () => box.remove() },
    h('span', { class: 'flash-ico' }, svgIcon(alert ? icons.warning : icons.bell)),
    h('div', null,
      h('div', { class: 'flash-kind' }, alert ? (item.critical ? 'Yeni kritik uyarı' : 'Yeni uyarı') : 'Yeni bildirim'),
      h('b', null, item.title),
      names.length ? h('div', { class: 'small' }, names.slice(0, 3).join(', ') + (names.length > 3 ? ` +${names.length - 3}` : '')) : null));
  flashBox.append(box);
  setTimeout(() => box.classList.add('out'), flashMs());
  setTimeout(() => box.remove(), flashMs() + 400);
}

// Uyarı düğmesi: tüm kullanıcılar; 5 sn'de bir sayıyı günceller, tıklanınca uyarıları listeler
let alertTimer;
function alertsButton() {
  const count = h('span', { class: 'alert-count', hidden: true });
  const btn = h('button', { class: 'icon-btn alert-btn', title: 'Uyarılar', 'aria-label': 'Uyarılar', 'aria-haspopup': 'menu' },
    svgIcon(icons.warning), count);
  const panel = h('div', { class: 'dropdown alerts-panel', role: 'menu' });
  let data = { total: 0, alerts: [] };
  const draw = () => {
    count.hidden = !data.total;
    count.textContent = data.total > 99 ? '99+' : data.total;
    btn.classList.toggle('danger', data.alerts.some(a => a.level === 'danger'));
    btn.classList.toggle('warn', !!data.total);
    btn.classList.toggle('critical', data.alerts.some(a => a.critical));   // kritik uyarı: yanıp söner
    clear(panel,
      h('div', { class: 'alerts-head' }, 'Uyarılar'),
      data.alerts.length ? data.alerts.map(a => h('a', { class: `alert-item ${a.level} ${a.critical ? 'critical' : ''}`, href: `#/alerts/${a.key}`, onclick: () => { panel.hidden = true; } },
        h('span', { class: 'n' }, a.count),
        h('div', null, h('b', null, a.title),
          h('div', { class: 'small muted' }, a.names.join(', ') + (a.count > a.names.length ? '…' : '')))))
        : h('div', { class: 'empty small' }, 'Uyarı yok'));
  };
  const load = async () => {
    try { data = await api.get('/api/alerts'); draw(); announce('alerts', data.alerts); } catch { /* oturum kapanırsa kabuk yeniden çizilir */ }
  };
  popup(btn, panel);
  btn.addEventListener('click', () => { load(); if (!panel.hidden) logActivity({ event: 'open', path: location.hash, title: 'Uyarı listesi' }); });
  clearInterval(alertTimer);
  alertTimer = setInterval(load, 5000);
  draw();
  load();
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

const settingsTheme = () => ctx.user?.prefs?.settings?.theme;

// Kullanıcı menüsündeki sayılar: bildirimlerden (bekleyen kargo, arama, imza, misafir, takvim) sağa yaslı rozet
const menuCounts = new Map();
function menuCount(key) {
  const el = h('span', { class: 'menu-count', hidden: true });
  menuCounts.set(key, el);
  return el;
}
function syncMenuCounts(items) {
  const by = new Map(items.map(n => [n.key, n.count]));
  notifyCounts = by;
  by.set('personal', PERSONAL.reduce((a, p) => a + (by.get(p.notify) || 0), 0));
  for (const [key, el] of menuCounts) {
    const n = by.get(key) || 0;
    el.hidden = !n;
    el.textContent = n > 99 ? '99+' : n;
  }
}

// Bildirim düğmesi: kullanıcıyı ilgilendiren bildirimler (rolüne göre); uyarılarla aynı zamanlayıcıda güncellenir
let notifyTimer;
function notificationsButton() {
  const count = h('span', { class: 'alert-count', hidden: true });
  const btn = h('button', { class: 'icon-btn notify-btn', title: 'Bildirimler', 'aria-label': 'Bildirimler', 'aria-haspopup': 'menu' },
    svgIcon(icons.bell), count);
  const panel = h('div', { class: 'dropdown alerts-panel', role: 'menu' });
  let data = { total: 0, items: [] };
  const draw = () => {
    count.hidden = !data.total;
    count.textContent = data.total > 99 ? '99+' : data.total;
    btn.classList.toggle('on', !!data.total);
    clear(panel,
      h('div', { class: 'alerts-head' }, 'Bildirimler'),
      data.items.length ? data.items.map(n => h('a', { class: 'alert-item info', href: n.href, onclick: () => { panel.hidden = true; } },
        h('span', { class: 'n' }, n.count),
        h('div', null, h('b', null, n.title),
          n.detail ? h('div', { class: 'small', style: { color: 'var(--primary)', fontWeight: 600 } }, n.detail) : null,
          h('div', { class: 'small muted' }, n.names.join(', ') + (n.count > n.names.length ? '…' : '')))))
        : h('div', { class: 'empty small' }, 'Bildiriminiz yok'));
  };
  const load = async () => {
    try { data = await api.get('/api/notifications'); draw(); syncMenuCounts(data.items); announce('notify', data.items); } catch { /* oturum kapanırsa kabuk yeniden çizilir */ }
  };
  popup(btn, panel);
  btn.addEventListener('click', () => { load(); if (!panel.hidden) logActivity({ event: 'open', path: location.hash, title: 'Bildirim listesi' }); });
  clearInterval(notifyTimer);
  notifyTimer = setInterval(load, 5000);
  draw();
  load();
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

// Gece / gündüz teması (bu cihazda hatırlanır; ilk boyamadan önce index.html uygular)
// Tam ekran düğmesi (tarayıcı desteklemiyorsa gösterilmez, ör. iPhone Safari)
function fullscreenButton() {
  if (!document.fullscreenEnabled) return null;
  const btn = h('button', { class: 'icon-btn' });
  const sync = () => {
    const on = !!document.fullscreenElement;
    btn.replaceChildren(svgIcon(on ? icons.fullscreenExit : icons.fullscreen));
    btn.title = on ? 'Tam ekrandan çık' : 'Tam ekran';
    btn.setAttribute('aria-label', btn.title);
  };
  btn.addEventListener('click', () => {
    (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(() => {});
  });
  document.addEventListener('fullscreenchange', sync);
  sync();
  return btn;
}

function renderShell() {
  popups.clear();
  menuCounts.clear();
  applySettings(ctx.user.prefs?.settings, ctx.user);
  const u = ctx.user;
  setChatUser(u);
  const menuModules = MODULES.filter(m => m.menu && u.modules.includes(m.key));
  const menu = h('div', { class: 'dropdown', role: 'menu' },
    h('a', { class: 'menu-link', href: '#/personal', onclick: () => { menu.hidden = true; } }, svgIcon(icons.person), 'Kişisel', menuCount('personal')),
    h('a', { class: 'menu-link', href: '#/settings', onclick: () => { menu.hidden = true; } }, svgIcon(icons.settings), 'Ayarlar'),
    menuModules.map(m => h('a', { class: `menu-link ${m.tone ? `tone-${m.tone}` : ''}`, href: `#/${m.key}`,
      onclick: () => { menu.hidden = true; } }, svgIcon(icons[m.key]), m.title)),
    menuModules.length ? h('div', { class: 'menu-sep' }) : null,
    installButton(),
    h('button', { onclick: () => { menu.hidden = true; changePassword(); } }, 'Şifremi Değiştir'),
    h('button', { onclick: logout }, 'Çıkış Yap'));
  const userBtn = h('button', { class: 'user-btn', 'aria-haspopup': 'menu' },
    avatar(u),
    h('span', { class: 'who' }, h('b', null, u.full_name), h('span', null, u.roles.join(', ') || 'Rol atanmamış')));
  popup(userBtn, menu);

  view = h('main', { id: 'view' });
  scroller = h('div', { class: 'scroller' }, view);
  clear(root, h('div', { class: 'shell' },
    h('header', { class: 'app-header' },
      h('a', { class: 'brand', href: '#/' },
        h('img', { src: '/static/img/logo.png', alt: ctx.meta?.company || '' }),
        h('span', { class: 'product' }, h('b', null, 'FABRİKA'), 'Yönetim Sistemi')),
      h('div', { class: 'header-right' }, securityOnly() ? null : alertsButton(), securityOnly() ? null : chatButton(popup), notificationsButton(), fullscreenButton(), appsLauncher(), h('div', { class: 'menu-anchor' }, userBtn, menu))),
    scroller,
    h('footer', { class: 'app-footer' },
      h('span', { class: 'footer-copy' }, `© ${new Date().getFullYear()} ${ctx.meta?.company || ''}`),
      statusBar())));
  // Açılış sayfası (Ayarlar → Arayüz): girişte ana sayfa yerine seçilen modül
  const start = u.prefs?.settings?.start;
  if (start && start !== 'dashboard' && u.modules.includes(start) && !location.hash.replace(/^#\/?/, '')) {
    history.replaceState(null, '', `#/${start}`);
  }
  route();
}

// Kişisel takvim: randevu, hatırlatma ve katıldığım toplantılar
async function calendarPage(view, ctx) {
  clear(view,
    pageHead('Takvim', { back: '#/', sub: 'Randevularınız, hatırlatmalarınız ve katıldığınız toplantılar' }),
    h('div', { class: 'card card-pad' }, calendarPanel('user', ctx.user.id, ctx, { mine: true })));
}

async function logout() {
  for (const k of Object.keys(seen)) delete seen[k];   // sonraki oturumda ilk yükleme yine "görüldü" sayılır
  clearInterval(alertTimer);
  clearInterval(notifyTimer);
  stopStatusBar();
  await leavePage();   // son sayfa kaydı, oturum kapanmadan yazılsın
  closeChat();
  applySettings({ theme: settingsTheme(), screensaver: { on: false } }, null);
  try { await api.post('/api/auth/logout'); } catch { /* yok say */ }
  ctx.user = null;
  location.hash = '#/';
  renderLogin();
}

function changePassword() {
  const current = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
  const next = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const again = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  modal({
    title: 'Şifremi Değiştir',
    body: h('div', null, field('Mevcut şifre', current), field('Yeni şifre', next, 'En az 8 karakter'), field('Yeni şifre (tekrar)', again)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          if (next.value !== again.value) throw new Error('Yeni şifreler eşleşmiyor');
          await api.post('/api/auth/password', { current: current.value, new: next.value });
          toast('Şifreniz değiştirildi');
        },
      },
    ],
  });
}

// Yalnızca Güvenlik modülü olan kullanıcı (fabrika girişi): üretim uyarılarını görmez
const securityOnly = () => ctx.user.modules.includes('security') && ctx.user.modules.every(m => m === 'security' || m === 'announcements');

// ---------- Ana sayfa ----------
function renderHome() {
  if (securityOnly()) { location.hash = '#/security'; return; }   // güvenliğin tek ekranı
  const allowed = MODULES.filter(m => !m.menu && ctx.user.modules.includes(m.key));
  if (!ctx.user.modules.length) { clear(view, h('div', { class: 'card empty' }, 'Hesabınıza henüz bir rol atanmamış. Sistem yöneticisine başvurun.')); return; }
  clear(view, h('div', { class: 'loading' }, 'Yükleniyor…'));
  renderDashboard(view, ctx, allowed).catch(err => { if (err?.status !== 401) clear(view, h('div', { class: 'card empty' }, err.message)); });
}

// ---------- Hareket kaydı: her sayfaya giriş ve çıkış (kalınan süreyle) loglanır ----------
const SUB_PAGES = {
  production: p => `Sipariş #${p[0]}`,
  users: p => `Kullanıcı #${p[0]}${p[1] ? ` · ${{ edit: 'Bilgileri Düzenle', logs: 'Kullanıcı Logları', logins: 'Giriş Logları' }[p[1]] || p[1]}` : ''}`,
  products: p => `Ürün #${p[0]}`,
  stock: p => `Ürün #${p[0]}`,
  field: p => (p[0] === 'report' ? `Uçuş raporu #${p[1]}` : p.join('/')),
  tools: p => (p[0] === 'flight-log' ? `Uçuş Logu Analizi${p[1] ? ` · Rapor #${p[1]}` : ''}` : p.join('/')),
};
let currentPage = null;
let hiddenPage = null;   // sekme arka plandayken kapatılan sayfa; öne gelince yeniden giriş yazılır
function pageTitle(key, params) {
  if (!key) return 'Ana sayfa';
  if (key === 'alerts') return `Uyarılar › ${params[0] || ''}`;
  if (key === 'sign') return params[0] ? `İmza talebi #${params[0]}` : 'Kişisel › İmza talepleri';
  if (key === 'calendar') return 'Kişisel › Takvim';
  if (key === 'personal') return 'Kişisel';
  if (key === 'my-cargo') return params[0] === 'history' ? 'Kişisel › Kargolarım › Kargo Geçmişi' : 'Kişisel › Kargolarım';
  if (key === 'my-guests') return 'Kişisel › Misafirlerim';
  if (key === 'my-calls') return 'Kişisel › Aramalarım';
  if (key === 'settings') return params[0] ? `Ayarlar › ${params[0]}` : 'Ayarlar';
  const m = MODULES.find(x => x.key === key);
  const base = m ? m.title : key;
  return params.length ? `${base} › ${(SUB_PAGES[key] || (p => p.join('/')))(params)}` : base;
}
function leaveEvent() {
  const e = currentPage && { event: 'leave', path: currentPage.path, title: currentPage.title,
    seconds: Math.round((Date.now() - currentPage.since) / 1000) };
  currentPage = null;
  return e;
}
function leavePage(beacon = false) {
  if (!currentPage || !ctx.user) return null;
  return logActivity(leaveEvent(), { beacon });
}
// Önceki sayfadan çıkış ve yeni sayfaya giriş tek istekte gider; kayıt sırası hep doğru kalır
function enterPage(path, title) {
  const events = [leaveEvent(), { event: 'enter', path, title }].filter(Boolean);
  currentPage = { path, title, since: Date.now() };
  logActivity(events);
}
document.addEventListener('visibilitychange', () => {
  if (!ctx.user) return;
  if (document.hidden) {
    const p = currentPage;
    leavePage(true);
    hiddenPage = p;
  } else if (hiddenPage) {
    enterPage(hiddenPage.path, hiddenPage.title);
    hiddenPage = null;
  }
});
window.addEventListener('pagehide', () => leavePage(true));

// ---------- Kişisel modülü: kullanıcının kendi kayıtları (Takvim, İmza Talepleri, Kargolarım, Misafirlerim, Aramalarım)
// Her alt modül kendi sayfasını çizer; başlık "Kişisel" olur ve alt modül seçimi başlığın en sağında açılır liste olarak eklenir.
const PERSONAL = [
  { key: 'calendar', route: 'calendar', title: 'Takvim', notify: 'calendar-due', render: () => calendarPage(view, ctx) },
  { key: 'sign', route: 'sign', title: 'İmza Talepleri', notify: 'signature-pending', render: params => signPage.render(view, params, ctx) },
  { key: 'cargo', route: 'my-cargo', title: 'Kargolarım', notify: 'cargo-waiting', render: params => secretariat.renderMyCargo(view, params) },
  { key: 'guests', route: 'my-guests', title: 'Misafirlerim', notify: 'guest-visit', render: () => secretariat.renderMyGuests(view) },
  { key: 'calls', route: 'my-calls', title: 'Aramalarım', notify: 'call-waiting', render: () => renderMyCalls(view) },
];
let notifyCounts = new Map();
function personalHead(cur) {
  const head = view.querySelector('.page-head');
  if (!head) return;
  head.querySelector('h1').textContent = 'Kişisel';
  const sel = h('select', { class: 'input personal-sel', title: 'Kişisel', 'aria-label': 'Kişisel alt modül' },
    PERSONAL.map(p => {
      const n = notifyCounts.get(p.notify) || 0;
      return h('option', { value: p.route, selected: p === cur }, n ? `${p.title} (${n})` : p.title);
    }));
  sel.addEventListener('change', () => { location.hash = `#/${sel.value}`; });
  let right = head.querySelector(':scope > .head-right');
  if (!right) {
    const last = head.lastElementChild;
    const old = last && !last.classList.contains('spacer') ? last : null;   // tek düğme / seçici sağda duruyorsa
    right = h('div', { class: 'head-right' });
    if (old) right.append(old);
    head.append(right);
  }
  right.append(sel);
}

// ---------- Yönlendirme ----------
async function route() {
  if (!ctx.user || !view) return;
  stopTimers();
  hideTip();
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const [key, ...params] = parts;
  const path = `#/${parts.join('/')}`;
  if (currentPage?.path !== path) {   // aynı sayfanın yeniden çizimi (kaydet sonrası vb.) yeni giriş sayılmaz
    enterPage(path, pageTitle(key, params));
  }
  scroller.scrollTop = 0;
  if (key === 'alerts' && params[0]) {   // uyarı ayrıntısı: modül değil, herkese açık
    view.className = '';
    return alertsPage.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'personal') {   // Kişisel modülü: son açılan (ya da ilk) alt modüle git
    const last = pref('personal.last', 'calendar');
    location.replace(`#/${(PERSONAL.find(p => p.key === last) || PERSONAL[0]).route}`);
    return;
  }
  const personal = PERSONAL.find(p => p.route === key);
  if (personal && !(key === 'sign' && params[0])) {   // Kişisel alt modülleri (imza talebinin ayrıntısı hariç)
    view.className = '';
    setPref('personal.last', personal.key);
    return personal.render(params)
      .then(() => personalHead(personal))
      .catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'sign') {   // imza talebi ayrıntısı
    view.className = '';
    return signPage.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'settings') {   // kişisel ayarlar: herkese açık
    view.className = '';
    return renderSettings(view, ctx, { changePassword, modules: MODULES.filter(m => !m.menu && ctx.user.modules.includes(m.key)) }, params[0]).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  const m = MODULES.find(x => x.key === key);
  // Ton her geçişte yeniden ayarlanır; aksi halde kırmızı modülden dönünce ana sayfa kırmızı kalır
  view.className = m?.tone ? `tone-${m.tone}` : '';
  if (!m) return renderHome();
  if (!ctx.user.modules.includes(key)) {
    clear(view, h('div', { class: 'card empty' }, 'Bu modüle erişim yetkiniz yok.'));
    return;
  }
  clear(view, h('div', { class: 'loading' }, 'Yükleniyor…'));
  try {
    await m.mod.render(view, params, ctx);
  } catch (err) {
    if (err?.status === 401) return;
    clear(view, h('div', { class: 'card empty' }, err.message || 'Bir hata oluştu'));
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('caymaz:logout', () => logout());   // bekleme ekranı: farklı kullanıcıyla giriş
enableDictation();   // tüm çok satırlı metin kutularında mikrofon (sesle yazdırma)
boot();

// Web uygulaması: service worker ve "Uygulamayı Yükle" (tarayıcı destekliyorsa kullanıcı menüsünde görünür)
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
let installPrompt = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  installPrompt = e;
  document.querySelectorAll('.install-app').forEach(b => { b.hidden = false; });
});
window.addEventListener('appinstalled', () => {
  installPrompt = null;
  document.querySelectorAll('.install-app').forEach(b => { b.hidden = true; });
  toast('Fabrika Yönetim Sistemi yüklendi');
});
function installButton() {
  const b = h('button', { class: 'install-app', hidden: !installPrompt }, 'Uygulamayı Yükle');
  b.addEventListener('click', async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice.catch(() => null);
    installPrompt = null;
  });
  return b;
}
