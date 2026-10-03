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
import * as fieldMod from './modules/field.js';
import * as printers from './modules/printers.js';
import * as tools from './modules/tools.js';
import * as products from './modules/products.js';
import * as admin from './modules/admin.js';
import * as alertsPage from './modules/alerts.js';
import { renderDashboard } from './modules/dashboard.js';
import { renderMyCalls } from './modules/calls.js';
import * as voice from './modules/voice.js';
import * as messages from './modules/messages.js';
import * as sysconfig from './modules/sysconfig.js';
import * as meet from './modules/meet.js';
import * as radio from './modules/radio.js';
import { syncPush } from './push.js';
import { mountMascot } from './modules/mascot.js';
import { renderMail } from './modules/mail.js';
import { renderMeetings } from './modules/meetings.js';
import { accountChooser, accountToken, rememberAccount } from './accounts.js';
import * as companies from './modules/companies.js';
import * as documents from './modules/documents.js';
import * as signPage from './modules/sign.js';
import * as secretariat from './modules/secretariat.js';
import * as security from './modules/security.js';
import * as cammgmt from './modules/cammgmt.js';
import * as reportsMod from './modules/reports.js';
import * as announcements from './modules/announcements.js';
import * as cleaning from './modules/cleaning.js';
import * as design from './modules/design.js';
import * as hr from './modules/hr.js';
import * as mrp from './modules/mrp.js';
import * as purchasing from './modules/purchasing.js';
import * as master from './modules/master.js';
import * as mikro from './modules/mikro.js';
import * as sales from './modules/sales.js';
import * as crmHub from './modules/crmhub.js';
import { initLang, onLangChange, getLang } from './i18n.js';
import './i18n.en.js';   // İngilizce kataloğu kaydeder (registerCatalog('en', …))
import './i18n.en.extra.js';   // ek İngilizce katalog (modül içi statik metinler)
import './i18n.en.extra2.js';   // ek İngilizce katalog (dinamik/şablon metinler)
import './i18n.de.js';   // Almanca
import './i18n.fr.js';   // Fransızca
import './i18n.es.js';   // İspanyolca
import './i18n.ar.js';   // Arapça (RTL)
import './i18n.ru.js';   // Rusça
import { enableSegSelect } from './segselect.js';
import { enableListExport } from './listexport.js';
import { enableHeadGroup } from './headgroup.js';

// Ana sayfadaki modül düğmeleri; yeni modül eklemek için bu listeye bir satır eklenir.
// tone: 'red' → yalnızca yöneticilere açık modüller kırmızı tonlarda gösterilir.
// menu: true → ana ekranda ve modül menüsünde değil, sağ üstteki kullanıcı menüsünde gösterilir.
// sub: 'x' → x modülüne erişimi olan kullanıcıda ızgarada ayrı görünmez (x'in alt sekmesidir).
const MODULES = [
  { key: 'master', title: 'Veri & Yedek', mod: master, tone: 'purple', menu: true },   // yalnızca sistem sahibi; KVKK: veri göstermez, yalnız indir/yedek
  { key: 'admin', title: 'Yönetim', mod: admin, tone: 'red' },
  { key: 'production', title: 'Üretim Yönetimi', mod: production },
  { key: 'orders', title: 'İş Emri Yönetimi', mod: orders, hidden: true },   // Üretim Yönetimi'nin alt modülü (Yarı Mamul'ün yanında); ızgarada ayrı görünmez
  { key: 'mrp', title: 'MRP', mod: mrp },
  { key: 'purchasing', title: 'Satın Alma', mod: purchasing },   // Malzeme, Yarı Mamül (eski Stok), Onay (eski Depo), Depo Yönetimi
  { key: 'sales', title: 'Satış Yönetimi', mod: sales, sub: 'crm' },   // CRM alt modülü   // Firmalar için satış faturası oluşturma
  { key: 'mikro', title: 'Mikro ERP', mod: mikro, hidden: true },   // Program Ayarları › Entegrasyonlar altından açılır (yalnızca MASTER)
  { key: 'field', title: 'Saha Yönetimi', mod: fieldMod },
  { key: 'printers', title: 'Yazıcı Yönetimi', mod: printers, sub: 'production' },   // Üretim Yönetimi'nin alt modülü; Üretim'e erişimi olmayanda ızgarada kalır
  { key: 'products', title: 'Ürün Yönetimi', mod: products, tone: 'red' },
  { key: 'design', title: 'Endüstriyel Tasarım', mod: design },
  { key: 'crm', title: 'CRM', mod: crmHub },   // Firma + Evrak + Satış (grup; ayrı yetkisi yok)
  { key: 'companies', title: 'Firma Yönetimi', mod: companies, sub: 'crm' },
  { key: 'documents', title: 'Evrak Yönetimi', mod: documents, sub: 'crm' },
  { key: 'secretariat', title: 'Sekreterya', mod: secretariat, group: 'system' },
  { key: 'security', title: 'Güvenlik', mod: security, group: 'system' },
  // Kameralar: yalnızca sistem yöneticisi (admin/MASTER) ve NVR entegrasyonu aktifse görünür (Sistem Yönetimi)
  { key: 'cameras', title: 'Kameralar', mod: cammgmt, group: 'system',
    show: u => (u.master || u.modules.includes('admin')) && u.nvr },
  { key: 'hr', title: 'İnsan Kaynakları', mod: hr },
  { key: 'reports', title: 'Raporlar', mod: reportsMod, group: 'system' },
  { key: 'announcements', title: 'Duyurular', mod: announcements, group: 'system' },
  { key: 'cleaning', title: 'Temizlik', mod: cleaning, group: 'system' },
  { key: 'tools', title: 'Araçlar', mod: tools, menu: true },
  { key: 'users', title: 'Kullanıcı Yönetimi', mod: users, tone: 'red', menu: true },
];

// Ana ekran ızgarası / modül menüsü / ayarlardaki modül listesinde gösterilir mi?
const hasModule = (u, key) => (key === 'crm' ? crmHub.hasCrm(u) : u.modules.includes(key));
// Modül erişimi: özel 'show' varsa onu kullan (ör. Kameralar = sistem yöneticisi + NVR aktif), yoksa modül listesi
const canAccess = (m, u) => (m.show ? m.show(u) : hasModule(u, m.key));
const inGrid = (m, u) => !m.menu && !m.hidden && canAccess(m, u) && !(m.sub && hasModule(u, m.sub));

const root = document.getElementById('app');
const ctx = { user: null, meta: null };

async function boot() {
  // Dış katılımcı toplantı linki (/m/{code}): oturum gerektirmeden doğrudan katılım ekranı
  const mm = location.pathname.match(/^\/m\/([^/]+)/);
  if (mm) {
    document.title = 'Toplantıya Katıl';
    const r = meet.guestEntry(decodeURIComponent(mm[1]), new URLSearchParams(location.search).get('t'));
    window.__splashDone?.();
    return r;
  }
  // İki istek paralel (mobilde açılışı kısaltır); oturum yoksa yalnızca kullanıcı boş kalır
  const pMeta = api.get('/api/meta').catch(() => null);
  const pUser = api.get('/api/auth/me').catch(() => null);
  ctx.meta = await pMeta;
  ctx.user = await pUser;
  // Beyaz etiket: sekme başlığı firma adı (HEPGO görünmez); değilse ürün adı
  try { document.title = ctx.meta?.white_label ? (ctx.meta.company || '') : 'HEPGO ERP'; } catch { /* */ }
  initLang(ctx.user?.prefs?.settings?.lang);   // dil: kullanıcı tercihi → yoksa localStorage → Türkçe
  ctx.user ? enterApp() : renderLogin();
  requestAnimationFrame(() => window.__splashDone?.());   // ilk ekran çizildi → açılış ekranı kalkar
}

window.addEventListener('caymaz:unauthorized', e => {
  if (ctx.user) {
    ctx.user = null;
    // İzinli / raporlu personelin oturumu kapanınca sunucunun açıklaması gösterilir; diğer durumlarda genel mesaj
    const why = e?.detail && /izinli|rapor/i.test(e.detail) ? e.detail : 'Oturum süreniz doldu, lütfen tekrar giriş yapın';
    toast(why, 'err');
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
    enterApp();
  };
  const body = h('div', { class: 'login-body' });
  const wl = ctx.meta?.white_label;
  const form = h('form', { class: 'card login' },
    h('img', { src: '/static/img/logo-login.png', alt: ctx.meta?.company || '' }),
    h('h1', null, wl ? (ctx.meta.company || '') : 'HEPGO ERP'),
    body,
    wl ? null : h('a', { class: 'login-home', href: 'https://hepgo.com', target: '_blank', rel: 'noopener' }, 'hepgo.com'));
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

// Giriş sonrası: şifresini hiç değiştirmemiş kullanıcı önce şifresini değiştirir (sunucu da başka isteğe izin vermez)
function enterApp() {
  if (ctx.user.must_change_password) { renderForcePassword(); return; }
  if (/^#\/tv\//.test(location.hash)) {   // TV / kiosk ekranı: kabuk (başlık, alt çubuk, bildirimler) olmadan tam ekran
    import('./modules/tvroom.js').then(m => m.renderTv(root, ctx));
    return;
  }
  renderShell(); checkWhatsNew();
}
window.addEventListener('caymaz:mustchange', () => { if (ctx.user) { ctx.user.must_change_password = true; renderForcePassword(); } });

function renderForcePassword() {
  currentPage = null;
  stopTimers();
  const current = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
  const next = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true, minlength: 8 });
  const again = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true });
  const meter = h('div', { class: 'pw-meter' }, h('i'));
  const submit = h('button', { class: 'btn primary lg', type: 'submit' }, 'Şifremi Değiştir ve Devam Et');
  next.addEventListener('input', () => {   // basit güç göstergesi
    const v = next.value;
    const score = [v.length >= 8, v.length >= 12, /[A-ZÇĞİÖŞÜ]/.test(v) && /[a-zçğıöşü]/.test(v), /\d/.test(v), /[^\wçğıöşüÇĞİÖŞÜ]/.test(v)].filter(Boolean).length;
    meter.className = `pw-meter s${score}`;
  });
  const form = h('form', { class: 'card login force-pw' },
    h('img', { src: '/static/img/logo-login.png', alt: ctx.meta?.company || '' }),
    h('h1', null, 'Şifrenizi değiştirin'),
    h('p', { class: 'muted' }, `Merhaba ${ctx.user.full_name.split(' ')[0]}, güvenliğiniz için size verilen şifreyi ilk girişte kendi şifrenizle değiştirmeniz gerekiyor.`),
    field('Mevcut (size verilen) şifre', current),
    field('Yeni şifre', h('div', null, next, meter), 'En az 8 karakter; büyük-küçük harf, rakam ve işaret kullanın'),
    field('Yeni şifre (tekrar)', again),
    submit,
    h('button', { class: 'btn ghost', type: 'button', onclick: () => logout() }, 'Çıkış Yap'));
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (next.value !== again.value) { toastError(new Error('Yeni şifreler eşleşmiyor')); return; }
    submit.disabled = true;
    try {
      await api.post('/api/auth/password', { current: current.value, new: next.value });
      ctx.user = await api.get('/api/auth/me');
      toast('Şifreniz değiştirildi');
      renderShell();
    } catch (err) { toastError(err); } finally { submit.disabled = false; }
  });
  const canvas = h('canvas', { class: 'globe-bg', 'aria-hidden': 'true' });
  clear(root, h('div', { class: 'login-wrap' }, canvas, form));
  const globe = createGlobe(canvas, { size: 0.46, speed: 7 });
  onLeave(() => globe.destroy());
  current.focus();
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
  const allowed = MODULES.filter(m => inGrid(m, ctx.user));
  const btn = h('button', { class: 'icon-btn', 'aria-label': 'Modüller', title: 'Modüller', 'aria-haspopup': 'menu' },
    svgIcon(icons.apps));
  const current = () => location.hash.replace(/^#\/?/, '').split('/')[0];
  const panel = h('div', { class: 'dropdown apps-panel', role: 'menu' });
  // Alt modüller (Yazıcı Yönetimi, Firma/Evrak/Satış) da ait oldukları modül açıkken vurgulanır
  const isOn = m => current() === m.key || MODULES.some(x => x.sub === m.key && x.key === current());
  const tile = m => h('a', { class: `app-tile ${m.tone ? `tone-${m.tone}` : ''} ${isOn(m) ? 'on' : ''}`, href: `#/${m.key}`, role: 'menuitem',
    onclick: () => { panel.hidden = true; } },
    h('span', { class: 'ico' }, svgIcon(icons[m.key])),
    h('span', null, m.title));
  // İki grup: Modüller (iş modülleri) ve Sistem Yönetimi (Sekreterya, Güvenlik, Raporlar, Duyurular).
  // Başlığa dokununca grup açılır / kapanır; durum cihazda hatırlanır.
  const groups = [['mods', 'Modüller', icons.apps, allowed.filter(m => m.group !== 'system')],
    ['system', 'Sistem Yönetimi', icons.settings, allowed.filter(m => m.group === 'system')]].filter(g => g[3].length);
  const closedKey = 'caymaz.appsClosed';
  const closed = () => { try { return JSON.parse(localStorage.getItem(closedKey) || '[]'); } catch { return []; } };
  const group = ([key, title, ico, list]) => {
    const box = h('div', { class: `apps-group ${closed().includes(key) ? 'closed' : ''}` });
    const head = h('button', { class: 'apps-group-h', type: 'button', 'aria-expanded': String(!box.classList.contains('closed')) },
      h('span', { class: 'gi' }, svgIcon(ico)), h('span', { class: 'gt' }, title), h('span', { class: 'gn' }, list.length),
      h('span', { class: 'chev', 'aria-hidden': 'true' }));
    head.addEventListener('click', () => {
      const shut = box.classList.toggle('closed');
      head.setAttribute('aria-expanded', String(!shut));
      const set = new Set(closed()); shut ? set.add(key) : set.delete(key);
      try { localStorage.setItem(closedKey, JSON.stringify([...set])); } catch { /* gizli pencere */ }
    });
    box.append(head, h('div', { class: 'apps-body' }, h('div', { class: 'apps-grid' }, list.map(tile))));
    return box;
  };
  const fill = () => clear(panel,
    groups.length ? groups.map(group) : h('div', { class: 'empty' }, 'Erişebildiğiniz modül yok'));
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
  // Kişisel alt modül seçicisindeki sayılar da güncel kalsın
  for (const o of view?.querySelectorAll('.personal-sel option') || []) {
    const p = PERSONAL.find(x => x.route === o.value);
    const n = p ? by.get(p.notify) || 0 : 0;
    if (p) o.textContent = n ? `${p.title} (${n})` : p.title;
  }
}

// Birleşik bildirim düğmesi: üretim/yazıcı UYARILARI + kişiye özel BİLDİRİMLER tek zilde (mobilde yer kazanır).
// Rozet toplamı gösterir; rengi en önemli kayda göre: kritik (yanıp söner) > hata (kırmızı) > uyarı (turuncu) > bildirim (mavi).
let alertTimer, notifyTimer;
let refreshNotify = () => {};   // bildirimleri hemen yeniden oku (ör. Kişisel sayfası görüldü sayınca)
// Eksik özlük evrakı geri sayımı (zilin solunda, küçük): gün / saat / dakika; tıklayınca Evraklarım. Evrak tamamlanınca kaybolur.
function docsCountdown() {
  const el = h('a', { class: 'docs-cd', href: '#/my-documents', hidden: true, title: 'Eksik özlük evrakınızı yükleyin' });
  const pad = n => String(n).padStart(2, '0');
  const draw = () => {
    const d = ctx.user?.docs_due;
    if (!d?.deadline) { el.hidden = true; return; }
    el.hidden = false;
    const ms = new Date(d.deadline) - new Date();
    if (ms <= 0) { clear(el, h('b', null, 'Süre doldu'), h('span', null, `${d.missing} evrak eksik`)); el.classList.add('over'); return; }
    const m = Math.floor(ms / 60000), dd = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
    clear(el, h('span', { class: 'docs-cd-t' }, `${dd}g ${pad(hh)}s ${pad(mm)}dk`), h('span', { class: 'docs-cd-s' }, `${d.missing} evrak`));
  };
  const refresh = async () => { try { const me = await api.get('/api/auth/me'); ctx.user.docs_due = me.docs_due; draw(); } catch { /* */ } };
  draw();
  setInterval(draw, 30000);   // sayfa değişince durmasın (başlık öğesi)
  window.addEventListener('caymaz:docs', refresh);
  setInterval(refresh, 10 * 60000);
  return el;
}

function inboxButton() {
  const count = h('span', { class: 'alert-count', hidden: true });
  const btn = h('button', { class: 'icon-btn notify-btn alert-btn inbox-btn', title: 'Bildirimler ve uyarılar', 'aria-label': 'Bildirimler ve uyarılar', 'aria-haspopup': 'menu' },
    svgIcon(icons.bell), count);
  const panel = h('div', { class: 'dropdown alerts-panel inbox-panel', role: 'menu' });
  let al = { total: 0, alerts: [] }, nt = { total: 0, items: [] };
  const close = () => { panel.hidden = true; };
  const draw = () => {
    const alerts = securityOnly() ? [] : al.alerts;
    const total = alerts.length + nt.total;
    count.hidden = !total;
    count.textContent = total > 99 ? '99+' : total;
    btn.classList.toggle('on', !!total);
    btn.classList.toggle('warn', alerts.length > 0);
    btn.classList.toggle('danger', alerts.some(a => a.level === 'danger') || nt.items.some(n => n.critical));
    btn.classList.toggle('critical', alerts.some(a => a.critical));
    const sec = (title, n, tone) => h('div', { class: `inbox-sec ${tone}` }, h('span', null, title), n ? h('b', null, n) : null);
    clear(panel,
      h('div', { class: 'alerts-head' }, 'Bildirimler'),
      alerts.length ? [sec('Uyarılar', alerts.length, 'warn'),
        ...alerts.map(a => h('a', { class: `alert-item ${a.level} ${a.critical ? 'critical' : ''}`, href: `#/alerts/${a.key}`, onclick: close },
          h('span', { class: 'n' }, a.count),
          h('div', null, h('b', null, a.title),
            h('div', { class: 'small muted' }, a.names.join(', ') + (a.count > a.names.length ? '…' : '')))))] : null,
      nt.items.length ? [alerts.length ? sec('Bildirimler', nt.total, 'info') : null,
        ...nt.items.map(n => h('a', { class: `alert-item ${n.critical ? 'danger critical' : 'info'}`, href: n.href, onclick: close },
          h('span', { class: 'n' }, n.count),
          h('div', null, h('b', null, n.title),
            n.detail ? h('div', { class: 'small', style: { color: 'var(--primary)', fontWeight: 600 } }, n.detail) : null,
            h('div', { class: 'small muted' }, n.names.join(', ') + (n.count > n.names.length ? '…' : '')))))] : null,
      !alerts.length && !nt.items.length ? h('div', { class: 'empty small' }, 'Uyarı ya da bildiriminiz yok') : null);
  };
  const loadAlerts = async () => {
    if (securityOnly()) return;
    try { al = await api.get('/api/alerts'); draw(); announce('alerts', al.alerts); } catch { /* oturum kapanırsa kabuk yeniden çizilir */ }
  };
  const loadNotify = async () => {
    try { nt = await api.get('/api/notifications'); draw(); syncMenuCounts(nt.items); announce('notify', nt.items); } catch { /* */ }
  };
  refreshNotify = loadNotify;
  popup(btn, panel);
  btn.addEventListener('click', () => { loadAlerts(); loadNotify(); if (!panel.hidden) logActivity({ event: 'open', path: location.hash, title: 'Bildirim listesi' }); });
  clearInterval(alertTimer); clearInterval(notifyTimer);
  alertTimer = setInterval(loadAlerts, 5000);
  notifyTimer = setInterval(loadNotify, 5000);
  draw(); loadAlerts(); loadNotify();
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
  voice.connect(ctx);   // sesli görüşme WebSocket'i (gelen arama her ekranda çalar)
  radio.connect(ctx);   // telsiz: kanallardaki canlı konuşmalar her ekranda duyulur
  syncPush();          // arka plan bildirimi aboneliğini tazele (izin önceden verildiyse)
  mountMascot(ctx);     // köşedeki yapay zeka maskotu (anahtar tanımlıysa görünür)
  const menuModules = MODULES.filter(m => m.menu && u.modules.includes(m.key));
  const menu = h('div', { class: 'dropdown', role: 'menu' },
    h('a', { class: 'menu-link', href: '#/personal', onclick: () => { menu.hidden = true; } }, svgIcon(icons.person), 'Kişisel', menuCount('personal')),
    h('a', { class: 'menu-link', href: '#/settings', onclick: () => { menu.hidden = true; } }, svgIcon(icons.settings), 'Ayarlar'),
    securityOnly() ? null : h('a', { class: 'menu-link', href: '#/meet', onclick: () => { menu.hidden = true; } }, svgIcon(icons.phone), 'Görüntülü Toplantı'),
    menuModules.map(m => h('a', { class: `menu-link ${m.tone ? `tone-${m.tone}` : ''}`, href: `#/${m.key}`,
      onclick: () => { menu.hidden = true; } }, svgIcon(icons[m.key]), m.title)),
    menuModules.length ? h('div', { class: 'menu-sep' }) : null,
    installButton(),
    (u.master || u.roles.includes('Sistem Yöneticisi')) ? h('a', { class: 'menu-link', href: '#/sysconfig', onclick: () => { menu.hidden = true; } }, svgIcon(icons.settings), 'Program Ayarları') : null,
    h('button', { onclick: () => { menu.hidden = true; changePassword(); } }, 'Şifremi Değiştir'),
    h('button', { onclick: () => { menu.hidden = true; aboutModal(); } }, 'Program Hakkında'),
    h('button', { onclick: logout }, 'Çıkış Yap'));
  const userBtn = h('button', { class: 'user-btn', 'aria-haspopup': 'menu' },
    avatar(u),
    h('span', { class: 'who' }, h('b', null, u.full_name), h('span', null, u.master ? 'MASTER · Sistem Sahibi' : (u.roles.join(', ') || 'Rol atanmamış'))));
  popup(userBtn, menu);

  view = h('main', { id: 'view' });
  scroller = h('div', { class: 'scroller' }, view);
  clear(root, h('div', { class: 'shell' },
    h('header', { class: 'app-header' },
      h('a', { class: 'brand', href: '#/' },
        h('img', { src: '/static/img/logo.png', alt: ctx.meta?.company || '' }),
        ctx.meta?.white_label   // firma kendi markası: HEPGO yerine firma adı
          ? h('span', { class: 'product wl' }, h('b', null, ctx.meta.company || ''))
          : h('span', { class: 'product' }, h('b', null, 'HEPGO'), 'ERP')),
      h('div', { class: 'header-right' }, radio.button(popup), securityOnly() ? null : chatButton(popup),
        docsCountdown(), inboxButton(), fullscreenButton(), appsLauncher(), h('div', { class: 'menu-anchor' }, userBtn, menu))),
    scroller,
    h('footer', { class: 'app-footer' },
      brandBadge(ctx),
      statusBar())));
  // Açılış sayfası (Ayarlar → Arayüz): girişte ana sayfa yerine seçilen modül
  const start = u.prefs?.settings?.start;
  if (start && start !== 'dashboard' && hasModule(u, start) && !location.hash.replace(/^#\/?/, '')) {
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

// Footer marka rozeti: dar ekranda ünvan gizlenmez, yalnızca logo-ikon kalır. Üzerine gelince / dokununca
// (durum çubuğu kutucukları gibi) logo + şirket ünvanı + sistemi tasarlayan (Muhammed Kaderoğlu) şık bir kutuda açılır.
function brandBadge(ctx) {
  const company = ctx.meta?.company || 'GÖKKUBBE Teknoloji';
  const year = new Date().getFullYear();
  const badge = h('button', { class: 'footer-brand', type: 'button', 'aria-label': company },
    h('img', { class: 'fb-mark', src: '/static/img/logo-mark.png', alt: '' }),
    h('span', { class: 'fb-name' }, `© ${year} ${company}`));
  const hover = matchMedia('(hover: hover) and (pointer: fine)').matches;
  let pop = null, closeTimer;
  const close = () => { if (pop) { pop.remove(); pop = null; badge.classList.remove('open'); document.removeEventListener('click', close); } };
  const open = () => {
    if (pop) return;
    pop = h('div', { class: 'sb-pop fb-pop', role: 'dialog', onclick: e => e.stopPropagation(),
      onmouseenter: () => clearTimeout(closeTimer), onmouseleave: () => { if (hover) closeTimer = setTimeout(close, 300); } },
      h('img', { class: 'fb-logo', src: '/static/img/logo.png', alt: company }),
      h('div', { class: 'fb-title' }, company),
      h('div', { class: 'fb-by' }, h('span', { class: 'fb-by-label' }, 'Sistemi tasarlayan'), h('b', null, 'Muhammed Kaderoğlu')),
      h('div', { class: 'fb-copy' }, `© ${year} · Tüm hakları saklıdır`));
    document.body.append(pop);
    const r = badge.getBoundingClientRect();
    pop.style.bottom = `${innerHeight - r.top + 8}px`;
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8))}px`;
    badge.classList.add('open');
    setTimeout(() => document.addEventListener('click', close), 0);
  };
  badge.addEventListener('click', e => { e.stopPropagation(); open(); });   // dokununca açılır; dışarı dokununca / mouseleave ile kapanır
  if (hover) {
    badge.addEventListener('mouseenter', () => { clearTimeout(closeTimer); open(); });
    badge.addEventListener('mouseleave', () => { closeTimer = setTimeout(close, 300); });
  }
  return badge;
}

// Program Hakkında: sürüm numarası + değişiklik geçmişi (soldan sürüm seç, sağda neler değişti)
async function aboutModal() {
  let d;
  try { d = await api.get('/api/system/about'); } catch (err) { return toastError(err); }
  let sel = d.entries[0];
  const list = h('div', { class: 'about-vers' });
  const detail = h('div', { class: 'about-detail' });
  const drawDetail = () => clear(detail,
    h('div', { class: 'about-dh' }, h('b', null, `Sürüm ${sel.version}`), sel.title ? h('span', { class: 'about-title' }, sel.title) : null, h('span', { class: 'small muted' }, sel.date)),
    h('ul', { class: 'about-changes' }, sel.changes.map(c => h('li', null, c))));
  const drawList = () => clear(list, d.entries.map(e => h('button', { class: `about-ver ${e === sel ? 'on' : ''}`, type: 'button', onclick: () => { sel = e; drawList(); drawDetail(); } },
    h('b', null, `v${e.version}`), h('small', null, e.date), e === d.entries[0] ? h('span', { class: 'about-badge' }, 'Güncel') : null)));
  drawList(); drawDetail();
  modal({ title: `Program Hakkında · Sürüm ${d.version}`, wide: true,
    body: h('div', { class: 'about-wrap' }, h('div', { class: 'about-side' }, list), detail),
    actions: [{ label: 'Kapat' }] });
}

// "Neler değişti?": kullanıcının gördüğü sürümden sonraki değişiklik notları (yoksa en son sürümün notları)
const verCmp = (a, b) => { const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0); return 0; };
let loadedVersion = null;   // bu sayfa açıldığında çalışan sürüm
async function whatsNewModal(since) {
  let d;
  try { d = await api.get('/api/system/about'); } catch (err) { return toastError(err); }
  const fresh = since ? d.entries.filter(e => verCmp(e.version, since) > 0) : [];
  const list = fresh.length ? fresh : d.entries.slice(0, 1);
  modal({ title: fresh.length ? `Yenilikler · ${since} → ${d.version}` : `Sürüm ${d.version} · Yenilikler`, wide: true,
    body: h('div', { class: 'wn-list' },
      fresh.length ? null : h('p', { class: 'small muted' }, 'Bu güncelleme küçük iyileştirmeler ve düzeltmeler içeriyor. Son sürümün notları:'),
      list.map(e => h('section', { class: 'wn-item' },
        h('div', { class: 'about-dh' }, h('b', null, `Sürüm ${e.version}`), e.title ? h('span', { class: 'about-title' }, e.title) : null, h('span', { class: 'small muted' }, e.date)),
        h('ul', { class: 'about-changes' }, e.changes.map(c => h('li', null, c)))))),
    actions: [{ label: 'Tüm geçmiş', onClick: () => { aboutModal(); } }, 'spacer', { label: 'Kapat', class: 'primary' }] });
}
// Uygulama açılınca: önceki ziyaretten bu yana sürüm yükseldiyse "Yenilikler" kısa uyarısı (bir kez)
async function checkWhatsNew() {
  let d; try { d = await api.get('/api/system/about'); } catch { return; }
  loadedVersion = d.version;
  let seen = null; try { seen = localStorage.getItem('caymaz.seenVersion'); } catch { /* */ }
  try { localStorage.setItem('caymaz.seenVersion', d.version); } catch { /* */ }
  if (!seen || verCmp(d.version, seen) <= 0 || document.getElementById('wn-chip')) return;
  const chip = h('div', { id: 'wn-chip', class: 'wn-chip' },
    h('span', null, `✨ Sürüm ${d.version} yüklendi`),
    h('button', { class: 'btn sm', type: 'button', onclick: () => { chip.remove(); whatsNewModal(seen); } }, 'Neler değişti?'),
    h('button', { class: 'ver-x', type: 'button', title: 'Kapat', onclick: () => chip.remove() }, '×'));
  document.body.append(chip);
  setTimeout(() => chip.remove(), 20000);
}

// "Yeni sürüm" uyarısı: sunucudaki arayüz derlemesi değişince herkese üstte banner; dokununca önbelleği temizleyip yeniden yükler.
let buildId = null;
window.addEventListener('caymaz:build', e => {
  if (!buildId) { buildId = e.detail; return; }
  if (e.detail !== buildId && !document.getElementById('ver-banner')) showVersionBanner();
});
function showVersionBanner() {
  const bar = h('div', { id: 'ver-banner', class: 'ver-banner' },
    h('span', null, '🎉 Yeni sürüm hazır — güncellemek için dokunun'),
    h('button', { class: 'btn sm ghost-light', type: 'button', onclick: () => whatsNewModal(loadedVersion) }, 'Neler değişti?'),
    h('button', { class: 'btn sm', type: 'button', onclick: hardReload }, 'Güncelle'),
    h('button', { class: 'ver-x', type: 'button', title: 'Şimdilik kapat', onclick: () => bar.remove() }, '×'));
  document.body.append(bar);
}
async function hardReload() {
  try { if (window.caches) { const ks = await caches.keys(); await Promise.all(ks.map(k => caches.delete(k))); } } catch { /* */ }
  location.reload();
}

async function logout() {
  for (const k of Object.keys(seen)) delete seen[k];   // sonraki oturumda ilk yükleme yine "görüldü" sayılır
  clearInterval(alertTimer);
  clearInterval(notifyTimer);
  stopStatusBar();
  voice.disconnect();   // sesli görüşme WebSocket'ini kapat
  radio.disconnect();
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
  const allowed = MODULES.filter(m => inGrid(m, ctx.user));
  if (!ctx.user.modules.length) { clear(view, h('div', { class: 'card empty' }, 'Hesabınıza henüz bir rol atanmamış. Sistem yöneticisine başvurun.')); return; }
  clear(view, h('div', { class: 'loading' }, 'Yükleniyor…'));
  renderDashboard(view, ctx, allowed).catch(err => { if (err?.status !== 401) clear(view, h('div', { class: 'card empty' }, err.message)); });
}

// ---------- Hareket kaydı: her sayfaya giriş ve çıkış (kalınan süreyle) loglanır ----------
const SUB_PAGES = {
  production: p => `İş Emri #${p[0]}`,
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
  if (key === 'voice-call') return `Görüşme Detayı${params[0] ? ` #${params[0]}` : ''}`;
  if (key === 'my-cargo') return params[0] === 'history' ? 'Kişisel › Kargolarım › Kargo Geçmişi' : 'Kişisel › Kargolarım';
  if (key === 'my-guests') return 'Kişisel › Misafirlerim';
  if (key === 'my-calls') return 'Kişisel › Aramalarım';
  if (key === 'mail') return 'Kişisel › Mail';
  if (key === 'my-leaves') return 'Kişisel › İzinlerim';
  if (key === 'master') return `MASTER${params[0] ? ` › Kullanıcı #${params[0]}` : ''}`;
  if (key === 'purchasing') return `Satın Alma${params.length ? ` › ${{ requests: 'Talep Yönetimi', suppliers: 'Tedarikçi Yönetimi', invoices: 'Fatura İrsaliye', quotes: 'Teklif Yönetimi' }[params[0]] || params[0]}${params[1] ? ` #${params[1]}` : ''}` : ''}`;
  if (key === 'mrp') return `MRP${params.length ? ` › ${{ materials: 'Malzeme Yönetimi', semi: 'Yarı Mamül', approvals: 'Onay Yönetimi', depots: 'Depo Yönetimi' }[params[0]] || params[0]}${params[1] ? ` #${params[1]}` : ''}` : ''}`;
  if (key === 'meetings') return params[0] ? `Kişisel › Toplantı #${params[0]}` : 'Kişisel › Toplantılar';
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
  { key: 'meetings', route: 'meetings', title: 'Toplantılar', notify: 'meeting-invite', render: params => renderMeetings(view, params) },
  { key: 'sign', route: 'sign', title: 'İmza Talepleri', notify: 'signature-pending', render: params => signPage.render(view, params, ctx) },
  { key: 'cargo', route: 'my-cargo', title: 'Kargolarım', notify: 'cargo-waiting', render: params => secretariat.renderMyCargo(view, params) },
  { key: 'guests', route: 'my-guests', title: 'Misafirlerim', notify: 'guest-visit', render: () => secretariat.renderMyGuests(view) },
  { key: 'calls', route: 'my-calls', title: 'Aramalarım', notify: 'call-waiting', render: () => renderMyCalls(view) },
  { key: 'mail', route: 'mail', title: 'Mail', notify: 'mail-unread', render: params => renderMail(view, params) },
  { key: 'leaves', route: 'my-leaves', title: 'İzinlerim', notify: 'leave-decided', render: () => hr.renderMyLeaves(view) },
  { key: 'docs', route: 'my-documents', title: 'Evraklarım', notify: 'docs-missing', render: () => hr.renderMyDocuments(view) },
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
  if (key === 'voice-call' && params[0]) {   // görüşme detayı: bağımsız sayfa (arama kaydından açılır)
    view.className = '';
    return voice.renderCall(view, Number(params[0]), ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'messages') {   // Mesajlar: WhatsApp-Web tarzı sohbet + arama (herkese açık)
    view.className = 'msg-view';
    onLeave(() => messages.stop());
    return messages.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'sysconfig') {   // Program Ayarları (sistem yöneticisi / MASTER)
    view.className = '';
    return sysconfig.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'meet') {   // Görüntülü online toplantı (herkese açık)
    view.className = '';
    onLeave(() => meet.destroy());
    return meet.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
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
      .then(() => { if (!(personal.key === 'meetings' && params[1])) personalHead(personal); refreshNotify(); })   // toplantı ekranı / özeti kendi başlığıyla
      .catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'sign') {   // imza talebi ayrıntısı
    view.className = '';
    return signPage.render(view, params, ctx).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'settings') {   // kişisel ayarlar: herkese açık
    view.className = '';
    return renderSettings(view, ctx, { changePassword, modules: MODULES.filter(m => inGrid(m, ctx.user)) }, params[0]).catch(err => clear(view, h('div', { class: 'card empty' }, err.message)));
  }
  if (key === 'stock' || key === 'warehouse') {   // eski adresler: MRP alt modülleri
    location.replace(`#/mrp/${key === 'stock' ? 'semi' : 'approvals'}${params.length ? `/${params.join('/')}` : ''}`);
    return;
  }
  const m = MODULES.find(x => x.key === key);
  // Ton her geçişte yeniden ayarlanır; aksi halde kırmızı modülden dönünce ana sayfa kırmızı kalır
  view.className = m?.tone ? `tone-${m.tone}` : '';
  if (!m) return renderHome();
  if (!canAccess(m, ctx.user)) {
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
onLangChange(() => { if (ctx.user) renderShell(); else route(); });   // dil değişince kabuk (menü) + ekran yeniden çizilir
window.addEventListener('caymaz:logout', () => logout());   // bekleme ekranı: farklı kullanıcıyla giriş
enableDictation();   // tüm çok satırlı metin kutularında mikrofon (sesle yazdırma)
// Mobilde klavye açılınca görünür alan küçülür; uygulama kabuğunu görünür viewport yüksekliğine indir ki
// alttaki yazı kutuları (sohbet vb.) klavyenin arkasında kalmasın.
(function keyboardFit() {
  const vv = window.visualViewport;
  if (!vv) return;
  const fit = () => {
    document.documentElement.style.setProperty('--vvh', `${Math.round(vv.height)}px`);
    if (vv.offsetTop > 1 || window.scrollY > 0) window.scrollTo(0, 0);   // iOS'ta sayfayı klavye altına kaydırmasın
  };
  vv.addEventListener('resize', fit);
  vv.addEventListener('scroll', fit);
  fit();
})();
enableSegSelect();   // telefonda düğme grupları (sekme / görünüm / filtre) açılır listeye dönüşür
enableListExport();  // tüm listelerde başlığın en sağında Excel indirme düğmesi
enableHeadGroup();   // başlıktaki bağımsız eylem düğmelerini (ör. "+ Yeni" + "Excel") tek kapsülde toplar
window.addEventListener('caymaz:toast', e => toast(e.detail));
// İskelet kabları (başlık + içerik + alt çubuk) asla kaymamalı; tarayıcı odak / scrollIntoView ile kaydırırsa geri al
// Kaydırması kapalı (overflow: hidden / clip) her kap da buna dahil: ör. mesajlarda kayarsa yazma kutusu alt çubuğun arkasında kalıyordu.
const SKELETON = ['shell', 'msg-page', 'msg-conv', 'msg-view'];
const noScroll = el => {
  if (el === document.scrollingElement || SKELETON.some(c => el.classList?.contains(c))) return true;
  const cs = getComputedStyle(el);
  return /hidden|clip/.test(cs.overflowY) && /hidden|clip/.test(cs.overflowX);
};
document.addEventListener('scroll', e => {
  const t = e.target === document ? document.scrollingElement : e.target;
  if (t && (t.scrollTop || t.scrollLeft) && noScroll(t)) { t.scrollTop = 0; t.scrollLeft = 0; }
}, true);
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
