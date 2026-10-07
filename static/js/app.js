// Uygulama kabuğu: oturum, üst/alt bölüm, ana sayfa modül düğmeleri ve yönlendirme.
import { api, logActivity } from './api.js';
import { icons } from './icons.js';
import { statusBar, stopStatusBar } from './statusbar.js';
import { chatButton, chatSummary, closeChat, setChatUser } from './chat.js';
import { eventOfNotification, playEvent } from './sounds.js';
import { applySettings, desktopNotify, flashMs, flashOn } from './prefs.js';
import { renderSettings } from './modules/settings.js';
import { calendarPanel } from './modules/crm.js';
import { enableDictation, setDictationEnabled } from './dictation.js';
import { avatar, clear, field, h, modal, onLeave, pageHead, pref, setPref, stopTimers, svgIcon, t, toast, toastError } from './ui.js';
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
import * as finance from './modules/finance.js';
import * as certs from './modules/certs.js';
import * as fleet from './modules/fleet.js';
import * as notesMod from './modules/notes.js';
import * as fileManager from './modules/filemanager.js';
import { initAlarms } from './alarms.js';
import * as boss from './modules/boss.js';
import * as projectsMod from './modules/projects.js';
import * as members from './modules/members.js';
import * as ticketsMod from './modules/tickets.js';
import * as smsMod from './modules/sms.js';
import * as membershipMod from './modules/membership.js';
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
import { companySwitcher, rememberCompany } from './companies.js';
import * as companies from './modules/companies.js';
import * as documents from './modules/documents.js';
import * as signPage from './modules/sign.js';
import * as secretariat from './modules/secretariat.js';
import * as security from './modules/security.js';
import * as cammgmt from './modules/cammgmt.js';
import * as directory from './modules/directory.js';
import * as reportsMod from './modules/reports.js';
import * as announcements from './modules/announcements.js';
import * as cleaning from './modules/cleaning.js';
import * as design from './modules/design.js';
import * as hr from './modules/hr.js';
import * as duty from './modules/duty.js';
import * as mrp from './modules/mrp.js';
import * as purchasing from './modules/purchasing.js';
import * as master from './modules/master.js';
import * as usermap from './modules/usermap.js';
import * as mikro from './modules/mikro.js';
import * as sales from './modules/sales.js';
import * as crmHub from './modules/crmhub.js';
import * as factory from './modules/factory.js';
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
import { enableToolbarMerge } from './toolbarmerge.js';

// Ana sayfadaki modül düğmeleri; yeni modül eklemek için bu listeye bir satır eklenir.
// tone: 'red' → yalnızca yöneticilere açık modüller kırmızı tonlarda gösterilir.
// menu: true → ana ekranda ve modül menüsünde değil, sağ üstteki kullanıcı menüsünde gösterilir.
// sub: 'x' → x modülüne erişimi olan kullanıcıda ızgarada ayrı görünmez (x'in alt sekmesidir).
const MODULES = [
  { key: 'master', title: 'Veri & Yedek', mod: master, tone: 'purple', hidden: true },   // yalnızca sistem sahibi; Program Ayarları altından açılır (KVKK: veri göstermez, yalnız indir/yedek)
  { key: 'konum', title: 'Canlı Konum', mod: usermap, tone: 'purple', show: u => !!u.master },   // MASTER: personelin mobil konumu harita üzerinde (açık rıza ile)
  { key: 'boss', title: 'Patron', mod: boss },   // Patron ekranı: üst yönetim özeti (ızgarada ilk sırada)
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
  // Kameralar: "Kamera Yetkilisi" rolü (ya da Sistem Yöneticisi) ve NVR entegrasyonu aktifse görünür (Sistem Yönetimi)
  { key: 'cameras', title: 'Kameralar', mod: cammgmt, group: 'system',
    show: u => u.modules.includes('cameras') && u.nvr },
  { key: 'rehber', title: 'Rehber', mod: directory, group: 'system' },
  // Fabrika dijital ikizi: 2D kat planı + kamera/personel yerleşimi + yüz tanımadan hareket izi (Sistem Yönetimi)
  { key: 'factory', title: 'Fabrika', mod: factory, group: 'system' },
  { key: 'hr', title: 'İnsan Kaynakları', mod: hr },
  { key: 'finance', title: 'Finans', mod: finance, tone: 'green' },
  { key: 'certs', title: 'Sertifikasyon', mod: certs },
  { key: 'fleet', title: 'Araç Yönetimi', mod: fleet },
  { key: 'projects', title: 'Proje Yönetimi', mod: projectsMod },
  // Merkez modu (Veilox Merkez): üyelik yönetimi, destek talepleri, toplu SMS — yalnız merkez instance'ında yetkili olur
  { key: 'members', title: 'Üyelik Yönetimi', mod: members, tone: 'red' },
  { key: 'tickets', title: 'Destek Merkezi', mod: ticketsMod },
  { key: 'sms', title: 'Toplu SMS', mod: smsMod, group: 'system' },
  // Firma paneli: merkezle ilişki (paket, ödemeler, destek talepleri) — firma instance'ında
  { key: 'uyelik', title: 'Üyeliğim & Destek', mod: membershipMod, group: 'system' },
  { key: 'reports', title: 'Raporlar', mod: reportsMod, group: 'system' },
  { key: 'announcements', title: 'Duyurular', mod: announcements, group: 'system' },
  { key: 'cleaning', title: 'Temizlik', mod: cleaning, group: 'system' },
  { key: 'tools', title: 'Araçlar', mod: tools, group: 'system' },   // Modül ızgarası › Sistem Yönetimi
  { key: 'users', title: 'Kullanıcı Yönetimi', mod: users, tone: 'red', hidden: true },   // Program Ayarları altından açılır
];

// Türkçe-duyarlı normalizasyon (arama için): küçük harf + aksan sadeleştirme
const normTr = s => (s || '').toLocaleLowerCase('tr')
  .replace(/ç/g, 'c').replace(/ş/g, 's').replace(/ğ/g, 'g').replace(/ı/g, 'i').replace(/ö/g, 'o').replace(/ü/g, 'u')
  .replace(/\s+/g, ' ').trim();
// Modül anahtar kelimeleri (başlık dışında eşanlamlılar) — akıllı arama için
const MOD_KEYWORDS = {
  hr: 'insan kaynaklari personel ozluk bordro izin aile maas kadro',
  cameras: 'kamera nvr yuz tanima isg kkd gorus tanimlanmayan',
  factory: 'fabrika kat plani kamera yerlesim hareket canli kim nerede dijital ikiz',
  rehber: 'rehber kisi kisiler telefon adres',
  companies: 'firma cari musteri tedarikci',
  documents: 'evrak belge dosya',
  sales: 'satis fatura teklif crm siparis',
  purchasing: 'satin alma malzeme stok depo yari mamul',
  production: 'uretim is emri yari mamul recete',
  printers: 'yazici 3b baski moonraker',
  finance: 'finans kasa banka cari hesap odeme tahsilat',
  fleet: 'arac filo yakit bakim',
  projects: 'proje gorev',
  security: 'guvenlik giris cikis ziyaretci nobet',
  secretariat: 'sekreterya telefon notu randevu',
  reports: 'rapor',
  design: 'tasarim endustriyel urun',
  products: 'urun malzeme recete',
  certs: 'sertifika belgelendirme',
  members: 'uyelik abonelik',
  tickets: 'destek talep ticket',
};
// Alt modül / sık yapılan işler indeksi (küratörlü): arama bunları da bulur ve ilgili yere götürür.
// [anahtar kelimeler, başlık, href, ipucu (yol), gereken modül anahtarı]
const FEATURES = [
  ['aile ailesi aile uyesi akraba es cocuk', 'Personel Ailesi — ekle', '#/hr', 'Personel seç › Özlük › Ailesi', 'hr'],
  ['izin izinler yillik izin izin talebi', 'İzinler', '#/hr', 'Personel seç › İzin ve Sağlık › İzinler', 'hr'],
  ['saglik raporu rapor', 'Sağlık Raporları', '#/hr', 'Personel seç › İzin ve Sağlık', 'hr'],
  ['ozluk dosya belge sozlesme', 'Özlük Dosyaları / Sözleşmeler', '#/hr', 'Personel seç › Özlük', 'hr'],
  ['adres ev tebligat acil', 'Personel Adresleri', '#/hr', 'Personel seç › Özlük › Adresler', 'hr'],
  ['kkd kask eldiven koruyucu isg zorunlu', 'Zorunlu KKD (İSG)', '#/hr', 'Personel seç › İSG › KKD', 'hr'],
  ['egitim yeterlilik isg', 'Zorunlu Eğitimler (İSG)', '#/hr', 'Personel seç › İSG › Eğitimler', 'hr'],
  ['organizasyon sema org', 'Organizasyon Şeması', '#/hr', 'İnsan Kaynakları', 'hr'],
  ['personel ekle calisan yeni', 'Personel Ekle', '#/hr', 'İnsan Kaynakları › ＋', 'hr'],
  ['yuz tanima face egitim', 'Yüz Tanıma', '#/cameras/facerec', 'Kameralar › Yüz Tanıma', 'cameras'],
  ['isg kkd kask eldiven alarm goruntu isleme', 'İSG (KKD denetimi)', '#/cameras/isg', 'Kameralar › İSG', 'cameras'],
  ['tanimlanmayan kisi bilinmeyen yuz', 'Tanımlanmayan Kişiler', '#/cameras/unknown', 'Kameralar › Tanımlanmayan', 'cameras'],
  ['kamera ekle nvr onvif', 'Kamera Ekle (NVR)', '#/cameras', 'Kameralar', 'cameras'],
  ['canli kim nerede konum fabrika', 'Fabrika · Canlı Konum', '#/factory/live', 'Fabrika › Canlı', 'factory'],
  ['hareket iz yol fabrika', 'Fabrika · Hareket İzi', '#/factory/move', 'Fabrika › Hareket', 'factory'],
  ['kat plani oda cizim yerlesim', 'Fabrika · Kat Planı Düzenle', '#/factory', 'Fabrika › Düzen', 'factory'],
  ['ziyaretci misafir', 'Ziyaretçiler', '#/cameras/unknown', 'Kameralar / Rehber', 'cameras'],
  ['mail eposta gelen kutusu', 'Mail', '#/mail', 'Kişisel › Mail', null],
  ['firma ekle cari musteri', 'Firma Ekle', '#/companies', 'Firma Yönetimi', 'companies'],
  ['evrak ekle belge yukle', 'Evrak Ekle', '#/documents', 'Evrak Yönetimi', 'documents'],
  ['satis faturasi teklif', 'Satış / Fatura', '#/sales', 'Satış Yönetimi', 'sales'],
  ['arac ekle filo yakit', 'Araç Yönetimi', '#/fleet', 'Araç Yönetimi', 'fleet'],
  ['ses tanima konusmaci egitim', 'Ses Tanıma Eğitimi', '#/rehber', 'Rehber › kişi › Yapay Zeka', 'rehber'],
  ['yapay zeka egitim resmi konum', 'Yapay Zeka (yüz/ses eğitimi)', '#/rehber', 'Rehber › kişi › Yapay Zeka', 'rehber'],
];

// Ana ekran ızgarası / modül menüsü / ayarlardaki modül listesinde gösterilir mi?
const hasModule = (u, key) => (key === 'crm' ? crmHub.hasCrm(u) : u.modules.includes(key));
// Modül erişimi: özel 'show' varsa onu kullan (ör. Kameralar = sistem yöneticisi + NVR aktif), yoksa modül listesi
const canAccess = (m, u) => (m.show ? m.show(u) : hasModule(u, m.key));
const inGrid = (m, u) => !m.menu && !m.hidden && canAccess(m, u) && !(m.sub && hasModule(u, m.sub));

const root = document.getElementById('app');
const ctx = { user: null, meta: null };

// Native his: iki parmakla SAYFA yakınlaştırmayı (pinch) engelle — arayüz sabit kalsın. Safari, viewport user-scalable=no'yu
// yok saydığından burada da engellenir. Fabrika krokisi kendi dokunmatik zoom'unu JS touch olaylarıyla yapar (gesture
// olayı değil), bu yüzden etkilenmez.
['gesturestart', 'gesturechange', 'gestureend'].forEach(ev =>
  document.addEventListener(ev, e => e.preventDefault(), { passive: false }));

// Mobil klavye: açılınca modal/alanlar klavyenin arkasında kalmasın. (1) Görünür alanı (visualViewport) CSS
// değişkenlerine yaz → .modal-back görünür alana oturur. (2) Odaklanan girişi görünür alana kaydır.
(function () {
  const vv = window.visualViewport, root = document.documentElement;
  const sync = () => {
    root.style.setProperty('--app-vh', (vv ? vv.height : innerHeight) + 'px');
    root.style.setProperty('--app-vt', (vv ? vv.offsetTop : 0) + 'px');
  };
  sync();
  if (vv) { vv.addEventListener('resize', sync); vv.addEventListener('scroll', sync); } else addEventListener('resize', sync);
  const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const scrollable = el => { for (let n = el.parentElement; n; n = n.parentElement) { const s = getComputedStyle(n); if (/(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 2) return n; } return null; };
  const keepInView = el => {
    if (!editable(el)) return;
    const top = vv ? vv.offsetTop : 0, bottom = (vv ? vv.offsetTop + vv.height : innerHeight), pad = 20;
    const r = el.getBoundingClientRect(), sc = scrollable(el) || document.scrollingElement;
    if (!sc) return;
    if (r.bottom > bottom - pad) sc.scrollTop += r.bottom - (bottom - pad);
    else if (r.top < top + pad) sc.scrollTop -= (top + pad) - r.top;
  };
  let focused = null;
  addEventListener('focusin', e => { if (editable(e.target)) { focused = e.target; setTimeout(() => keepInView(e.target), 280); } });
  addEventListener('focusout', () => { focused = null; });
  if (vv) vv.addEventListener('resize', () => { if (focused && document.activeElement === focused) setTimeout(() => keepInView(focused), 60); });
})();

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
    try { voice.disconnect(); radio.disconnect(); } catch { /* */ }   // oturum bitti: canlı kanallar (arama, akış olayları, telsiz) kapanır
    for (const k of Object.keys(seen)) delete seen[k];
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
  clearInterval(spotifyTimer);
  clearInterval(supportWatch);
  document.querySelector('.support-pill')?.remove();
  const username = h('input', { class: 'input', type: 'email', autocomplete: 'username', required: true });
  const password = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
  const submit = h('button', { class: 'btn primary lg', type: 'submit' }, 'Giriş Yap');
  const done = async deviceToken => {   // giriş başarılı: kabuk açılır, hesap + firma bu cihazda hatırlanır
    ctx.user = await api.get('/api/auth/me');
    if (deviceToken) rememberAccount(ctx.user, deviceToken);
    rememberCompany(ctx.meta, ctx.user.username).catch(() => {});
    enterApp();
  };
  const body = h('div', { class: 'login-body' });
  const wl = ctx.meta?.white_label;
  const brandSrc = ctx.meta?.logo_url || '/static/img/logo-login.png';
  const brandTitle = wl ? (ctx.meta.company || '') : 'HEPGO ERP';
  const logoImg = h('img', { src: brandSrc, alt: ctx.meta?.company || '' });
  const titleEl = h('h1', null, brandTitle);
  const homeLink = wl ? null : h('a', { class: 'login-home', href: 'https://hepgo.com', target: '_blank', rel: 'noopener' }, 'hepgo.com');
  // Alt bağlantı: başka firmaya geç. Tıklayınca üst logo/başlık HEPGO'ya döner, firma seçici açılır.
  const switchLink = h('button', { type: 'button', class: 'login-switch', onclick: () => showSwitcher() }, '🏢 Şirket değiştir');
  const form = h('form', { class: 'card login' }, logoImg, titleEl, body, homeLink, switchLink);
  const showForm = () => {
    logoImg.src = brandSrc; logoImg.alt = ctx.meta?.company || ''; titleEl.textContent = brandTitle;
    if (homeLink) homeLink.style.display = ''; switchLink.style.display = '';
    clear(body, field('Kullanıcı adı', username), field('Şifre', password), submit);
    username.focus();
    accountChooser(body, { onLogin: done, onOther: showForm }).catch(() => {});
  };
  // Firma değiştirici: HEPGO markalı başlık + hatırlanan firmalar / adresle giriş
  const showSwitcher = () => {
    logoImg.src = '/static/img/logo-login.png'; logoImg.alt = 'HEPGO'; titleEl.textContent = 'Şirket değiştir';
    if (homeLink) homeLink.style.display = 'none'; switchLink.style.display = 'none';
    companySwitcher(body, { onBack: showForm });
  };
  form.addEventListener('submit', async e => {
    if (!body.contains(username)) return;   // hesap listesi / PIN kendi formunu yönetir
    e.preventDefault();
    submit.disabled = true;
    try {
      const r = await api.post('/api/auth/login', { username: username.value, password: password.value, device_token: accountToken(username.value.trim()) });
      if (r.pending) { waitApproval(r); return; }   // merkez destek girişi: firma yöneticisinin onayı bekleniyor
      await done(r.device_token);
    } catch (err) {
      toastError(err);
    } finally {
      submit.disabled = false;
    }
  });
  // Merkez (Veilox) destek girişi: onay beklenirken ekran; onaylanınca otomatik giriş
  function waitApproval(r) {
    let left = r.expires_in || 120, done2 = false;
    const info = h('p', { class: 'small muted', style: { textAlign: 'center' } });
    const tick = () => { info.textContent = t('Kalan süre: {s} sn', { s: left }); };
    tick();
    clear(body,
      h('div', { class: 'login-wait' },
        h('div', { class: 'loading' }),
        h('h3', null, 'Onay bekleniyor'),
        h('p', null, t('{name} için firma yöneticisinden giriş onayı bekleniyor…', { name: r.full_name || '' })),
        info),
      h('button', { class: 'btn', type: 'button', onclick: () => { done2 = true; clearInterval(iv); showForm(); } }, 'Vazgeç'));
    const iv = setInterval(async () => {
      left -= 2;
      if (left <= 0 || done2) { clearInterval(iv); if (!done2) { toast('Onay süresi doldu', 'err'); showForm(); } return; }
      tick();
      try {
        const s = await api.get(`/api/auth/crosslogin/status/${r.token}`);
        if (s.status === 'approved') { clearInterval(iv); done2 = true; await done(null); }
        else if (s.status === 'rejected') { clearInterval(iv); done2 = true; toast('Giriş reddedildi', 'err'); showForm(); }
        else if (s.status === 'expired') { clearInterval(iv); done2 = true; toast('Onay süresi doldu', 'err'); showForm(); }
      } catch { /* yoklama hatası: sürdür */ }
    }, 2000);
  }
  const canvas = h('canvas', { class: 'globe-bg', 'aria-hidden': 'true' });
  clear(root, h('div', { class: 'login-wrap' }, canvas, form));
  const globe = createGlobe(canvas, { size: 0.46, speed: 7 });
  onLeave(() => globe.destroy());
  showForm();
}

// Giriş sonrası: şifresini hiç değiştirmemiş kullanıcı önce şifresini değiştirir (sunucu da başka isteğe izin vermez)
function enterApp() {
  if (ctx.user.must_change_password) { renderForcePassword(); return; }
  if (ctx.user.kvkk_pending && !/^#\/tv\//.test(location.hash)) { renderKvkkConsent(); return; }   // girişte zorunlu KVKK aydınlatma/açık rıza onayı (TV/kiosk hariç)
  if (/^#\/tv\//.test(location.hash)) {   // TV / kiosk ekranı: kabuk (başlık, alt çubuk, bildirimler) olmadan tam ekran
    import('./modules/tvroom.js').then(m => m.renderTv(root, ctx));
    return;
  }
  renderShell(); checkWhatsNew(); startSupportWatch(); checkDevicePush();
  document.querySelector('.support-pill')?.remove();
  if (ctx.user?.support) {   // merkez destek oturumu göstergesi
    document.body.append(h('div', { class: 'support-pill' }, '🛟 ',
      h('b', null, 'Destek oturumu'), h('span', null, ` · ${ctx.meta?.company || ''}`)));
  }
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
    h('img', { src: ctx.meta?.logo_url || '/static/img/logo-login.png', alt: ctx.meta?.company || '' }),
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
      enterApp();   // şifre sonrası varsa KVKK onay gate'ine geç, sonra kabuk
    } catch (err) { toastError(err); } finally { submit.disabled = false; }
  });
  const canvas = h('canvas', { class: 'globe-bg', 'aria-hidden': 'true' });
  clear(root, h('div', { class: 'login-wrap' }, canvas, form));
  const globe = createGlobe(canvas, { size: 0.46, speed: 7 });
  onLeave(() => globe.destroy());
  current.focus();
}

// Girişte zorunlu KVKK aydınlatma/açık rıza onayı: onaylamadan uygulamaya girilemez.
async function renderKvkkConsent() {
  currentPage = null;
  stopTimers();
  let d;
  try { d = await api.get('/api/kvkk/terms'); } catch { ctx.user.kvkk_pending = false; enterApp(); return; }   // metin alınamazsa engelleme
  if (!d.pending) { ctx.user.kvkk_pending = false; enterApp(); return; }
  const box = h('div', { class: 'kvkk-text', style: { maxHeight: '46vh', overflow: 'auto', textAlign: 'left', border: '1px solid var(--line)', borderRadius: '10px', padding: '14px', margin: '8px 0', fontSize: '14px', lineHeight: '1.5' } });
  box.innerHTML = d.html;   // sunucu sabiti (güvenilir metin), kullanıcı girişi değil
  const chk = h('input', { type: 'checkbox' });
  const ok = h('button', { class: 'btn primary lg', type: 'button', disabled: true }, 'Onayla ve Devam Et');
  chk.addEventListener('change', () => { ok.disabled = !chk.checked; });
  ok.addEventListener('click', async () => {
    ok.disabled = true;
    try {
      await api.post('/api/kvkk/accept-terms', {});
      ctx.user.kvkk_pending = false;
      toast('Onayınız alındı, teşekkürler');
      enterApp();
    } catch (err) { toastError(err); ok.disabled = false; }
  });
  const form = h('div', { class: 'card login force-pw' },
    h('img', { src: ctx.meta?.logo_url || '/static/img/logo-login.png', alt: ctx.meta?.company || '' }),
    h('h1', null, 'Kişisel Verilerin Korunması'),
    h('p', { class: 'muted' }, `Merhaba ${(ctx.user.full_name || '').split(' ')[0]}, devam etmeden önce aşağıdaki aydınlatma ve açık rıza metnini onaylamanız gerekiyor.`),
    box,
    h('label', { class: 'kvkk-accept', style: { display: 'flex', gap: '8px', alignItems: 'flex-start', textAlign: 'left', margin: '6px 0 14px', cursor: 'pointer' } }, chk,
      h('span', null, 'Okudum, anladım ve açık rızamla onaylıyorum.')),
    ok,
    h('button', { class: 'btn ghost', type: 'button', onclick: () => logout() }, 'Çıkış Yap'));
  const canvas = h('canvas', { class: 'globe-bg', 'aria-hidden': 'true' });
  clear(root, h('div', { class: 'login-wrap' }, canvas, form));
  const globe = createGlobe(canvas, { size: 0.46, speed: 7 });
  onLeave(() => globe.destroy());
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
// Tek uygulama (ızgara) ikonu: dört bölüm — Modüller · Sistem Yönetimi · Kişisel · Araçlar.
// Üst bar sadeleşsin diye ayrı Kişisel / Araçlar düğmeleri burada toplanır. Düğmedeki rozet = Kişisel'deki bekleyen iş sayısı.
function appsLauncher() {
  const allowed = MODULES.filter(m => inGrid(m, ctx.user));
  const btn = h('button', { class: 'icon-btn notify-btn', 'aria-label': 'Uygulamalar', title: 'Uygulamalar', 'aria-haspopup': 'menu' },
    svgIcon(icons.apps), menuCount('personal'));
  const current = () => location.hash.replace(/^#\/?/, '').split('/')[0];
  const curTool = () => location.hash.replace(/^#\/?/, '').replace(/^tools\//, '').split('/')[0];
  const panel = h('div', { class: 'dropdown apps-panel', role: 'menu' });
  // Alt modüller (Yazıcı Yönetimi, Firma/Evrak/Satış) da ait oldukları modül açıkken vurgulanır
  const isOn = m => current() === m.key || MODULES.some(x => x.sub === m.key && x.key === current());
  const modTile = m => h('a', { class: `app-tile ${m.tone ? `tone-${m.tone}` : ''} ${isOn(m) ? 'on' : ''}`, href: `#/${m.key}`, role: 'menuitem',
    onclick: () => { panel.hidden = true; } },
    h('span', { class: 'ico' }, svgIcon(icons[m.key])), h('span', null, m.title));
  // Kişisel kutucukları: bekleyen iş sayısı rozetiyle (canlı güncellenir)
  const countTile = (route, title, icon, count) => {
    const n = h('span', { class: 'tile-count', hidden: !count }, count > 99 ? '99+' : count);
    return h('a', { class: `app-tile ${current() === route ? 'on' : ''}`, href: `#/${route}`, role: 'menuitem', onclick: () => { panel.hidden = true; } },
      h('span', { class: 'ico' }, svgIcon(icon), n), h('span', null, title));
  };
  const toolTile = tl => h('a', { class: `app-tile ${curTool() === tl.key ? 'on' : ''}`, href: `#/tools/${tl.key}`, role: 'menuitem',
    onclick: () => { panel.hidden = true; } },
    h('span', { class: 'ico' }, svgIcon(icons[tl.icon] || icons.tools)), h('span', null, tl.title));
  // Başlığa dokununca grup açılır / kapanır; durum cihazda hatırlanır.
  const closedKey = 'caymaz.appsClosed';
  const closed = () => { try { return JSON.parse(localStorage.getItem(closedKey) || '[]'); } catch { return []; } };
  const group = (key, title, ico, tiles) => {
    if (!tiles.length) return null;
    const box = h('div', { class: `apps-group ${closed().includes(key) ? 'closed' : ''}` });
    const head = h('button', { class: 'apps-group-h', type: 'button', 'aria-expanded': String(!box.classList.contains('closed')) },
      h('span', { class: 'gi' }, svgIcon(ico)), h('span', { class: 'gt' }, title), h('span', { class: 'gn' }, tiles.length),
      h('span', { class: 'chev', 'aria-hidden': 'true' }));
    head.addEventListener('click', () => {
      const shut = box.classList.toggle('closed');
      head.setAttribute('aria-expanded', String(!shut));
      const set = new Set(closed()); shut ? set.add(key) : set.delete(key);
      try { localStorage.setItem(closedKey, JSON.stringify([...set])); } catch { /* gizli pencere */ }
    });
    box.append(head, h('div', { class: 'apps-body' }, h('div', { class: 'apps-grid' }, tiles)));
    return box;
  };
  // AKILLI ARAMA: modülleri VE alt modülleri/işlemleri arar, sonuçları filtreler (Türkçe-duyarlı)
  const results = h('div', { class: 'apps-results' });
  const searchInp = h('input', { class: 'apps-search', type: 'search', autocomplete: 'off', spellcheck: 'false',
    placeholder: 'Ara: modül veya işlem (ör. aile, izin, yüz tanıma, canlı)…', 'aria-label': 'Uygulamalarda ara' });
  const featTile = f => h('a', { class: 'app-tile feat', href: f[2], role: 'menuitem', onclick: () => { panel.hidden = true; } },
    h('span', { class: 'ico' }, svgIcon(icons[f[4]] || icons.apps)),
    h('span', { class: 'feat-txt' }, h('b', null, f[1]), f[3] ? h('small', { class: 'feat-hint' }, f[3]) : null));
  const fill = () => {
    const q = normTr(searchInp.value);
    personalTileCounts.clear();
    if (q) {   // arama modu: eşleşen modüller + eşleşen işlemler/alt modüller
      const mTiles = allowed.filter(m => normTr(`${m.title} ${MOD_KEYWORDS[m.key] || ''}`).includes(q)).map(modTile);
      const fTiles = FEATURES.filter(f => (!f[4] || canAccess({ key: f[4] }, ctx.user)) && normTr(`${f[0]} ${f[1]} ${f[3] || ''}`).includes(q)).map(featTile);
      const boxes = [
        group('mods', 'Modüller', icons.apps, mTiles),
        group('feat', 'İşlemler / Alt modüller', icons.search || icons.apps, fTiles),
      ].filter(Boolean);
      clear(results, boxes.length ? boxes : h('div', { class: 'empty' }, `“${searchInp.value.trim()}” için sonuç yok`));
      return;
    }
    // Normal (aramasız) görünüm: Kişisel kutucukları + Mesajlar; canlı sayaç güncellemeleri personalTileCounts'a kaydedilir
    const personalTiles = PERSONAL.map(p => {
      const el = countTile(p.route, p.title, icons[PERSONAL_ICONS[p.key]] || icons.person, notifyCounts.get(p.notify) || 0);
      const n = el.querySelector('.tile-count');
      personalTileCounts.add(() => { const c = notifyCounts.get(p.notify) || 0; n.hidden = !c; n.textContent = c > 99 ? '99+' : c; });
      return el;
    });
    const msgTile = countTile('messages', 'Mesajlar', icons.chat, chatSummary().people || 0);
    const msgN = msgTile.querySelector('.tile-count');
    personalTileCounts.add(() => { const c = chatSummary().people || 0; msgN.hidden = !c; msgN.textContent = c > 99 ? '99+' : c; });
    personalTiles.push(msgTile);
    const toolList = tools.visibleTools(ctx);
    const boxes = [
      group('mods', 'Modüller', icons.apps, allowed.filter(m => m.group !== 'system').map(modTile)),
      group('system', 'Sistem Yönetimi', icons.settings, allowed.filter(m => m.group === 'system').map(modTile)),
      group('personal', 'Kişisel', icons.person, personalTiles),
      group('tools', 'Araçlar', icons.tools, toolList.map(toolTile)),
    ].filter(Boolean);
    clear(results, boxes.length ? boxes : h('div', { class: 'empty' }, 'Erişebildiğiniz bir şey yok'));
  };
  searchInp.addEventListener('input', fill);
  searchInp.addEventListener('keydown', e => {
    if (e.key === 'Escape') { if (searchInp.value) { searchInp.value = ''; fill(); e.stopPropagation(); } }
    else if (e.key === 'Enter') { const a = results.querySelector('a.app-tile'); if (a) { location.hash = a.getAttribute('href'); panel.hidden = true; } }
  });
  clear(panel, h('div', { class: 'apps-search-wrap' },
    h('div', { class: 'apps-search-title' }, svgIcon(icons.search || icons.apps), h('span', null, 'Arama Kutusu')),
    searchInp), results);
  btn.addEventListener('click', () => {   // popup'tan önce çalışır: panel henüz gizliyse şimdi açılıyor
    const opening = panel.hidden;
    if (opening) { searchInp.value = ''; }
    fill();
    if (opening) { logActivity({ event: 'open', path: location.hash, title: 'Uygulamalar menüsü' }); setTimeout(() => searchInp.focus(), 60); }
  });
  popup(btn, panel);
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

// Kişisel alt modülleri (Takvim, Toplantılar, Mail, İzinlerim…) ve Araçlar artık ayrı üst-bar düğmesi değil;
// tek "Uygulamalar" (ızgara) ikonunun içinde bölüm olarak gösterilir (bkz. appsLauncher). PERSONAL_ICONS ve
// personalTileCounts oradan kullanılır (kutucuk bekleyen-iş sayıları canlı güncellenir).
const PERSONAL_ICONS = { calendar: 'calendar', meetings: 'video', sign: 'documents', cargo: 'cargo', guests: 'guest', calls: 'phone',
  mail: 'mail', leaves: 'hr', docs: 'paperclip', vehicles: 'fleet', notes: 'note', files: 'folder', duties: 'flightlog' };
const personalTileCounts = new Set();
window.addEventListener('caymaz:chat-summary', () => { for (const fn of personalTileCounts) { try { fn(); } catch { /* */ } } });

// Yeni uyarı / bildirim: sağ üst köşede kısa kutu, 3 sn sonra gizlenir. İlk yüklemede var olanlar "görüldü" sayılır;
// sonra yeni bir başlık, artan sayı ya da listede yeni bir ad gelirse gösterilir. Kutuya tıklanınca ilgili sayfa açılır.
const seen = {};
let flashBox;
// Ana ekran (pano / tam ekran haber akışı) açık ve görünür mü? Yeni paylaşım orada doğrudan akışa düşer, bildirim kutusu gerekmez.
// Harita görünümünde akış listesi yok → orada da bildirim gösterilir.
const onHomeVisible = () => {
  const k = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  return (!k.length || (k.length === 1 && k[0] === 'home')) && document.visibilityState === 'visible'
    && ctx.user?.prefs?.settings?.feedView !== 'map';
};
window.addEventListener('caymaz:feed', () => { if (!onHomeVisible()) refreshNotify(); });   // başka ekrandaysa zil + kutu hemen
window.addEventListener('caymaz:feed-seen', () => refreshNotify());                       // ana ekranda görüldü → zilden düşsün
window.addEventListener('caymaz:live', () => refreshNotify());   // canlı yayın başladı / bitti → zil ve kutu hemen
// Cihaz bildirimi (Web Push) açıksa yeni paylaşımın OS bildirimini sunucu atar; masaüstü bildirimi ikinci kez gösterilmez.
let devicePush = false;
const checkDevicePush = () => import('./push.js').then(m => m.pushState()).then(v => { devicePush = v === 'on'; }).catch(() => {});
function announce(kind, items) {
  const prev = seen[kind];
  seen[kind] = new Map(items.map(i => [i.key, { count: i.count, names: new Set(i.names) }]));
  if (!prev) return;
  for (const i of items) {
    if (i.key === 'feed-new' && onHomeVisible()) continue;   // ana ekrandaysa paylaşım zaten akışa düştü
    const p = prev.get(i.key);
    const fresh = p ? i.names.filter(n => !p.names.has(n)) : i.names;
    if (p && i.count <= p.count && !fresh.length) continue;
    playEvent(kind === 'alerts' ? (i.critical ? 'critical' : 'alert') : eventOfNotification(i.key));
    const names = fresh.length ? fresh : i.names;
    if (flashOn()) flash(kind, i, names);
    const go = () => { location.hash = kind === 'alerts' ? `#/alerts/${i.key}` : i.href; };
    if (i.key === 'mail-unread' && devicePush) continue;   // e-posta: telefon / masaüstü bildirimini sunucu (özetiyle) atar
    if (!((i.key === 'feed-new' || i.key === 'live-now') && devicePush)) desktopNotify(i.push?.title || i.title, i.push?.body || names.slice(0, 3).join(', '), go);
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
      h('b', null, item.push?.title || item.title),
      item.push?.body ? h('div', { class: 'small flash-body' }, item.push.body)
        : names.length ? h('div', { class: 'small' }, names.slice(0, 3).join(', ') + (names.length > 3 ? ` +${names.length - 3}` : '')) : null));
  flashBox.append(box);
  setTimeout(() => box.classList.add('out'), flashMs());
  setTimeout(() => box.remove(), flashMs() + 400);
}

const settingsTheme = () => ctx.user?.prefs?.settings?.theme;

// Kullanıcı menüsündeki sayılar: bildirimlerden (bekleyen kargo, arama, imza, misafir, takvim) sağa yaslı rozet
const menuCounts = new Map();
function menuCount(key) {
  const el = h('span', { class: 'menu-count', hidden: true });
  if (!menuCounts.has(key)) menuCounts.set(key, new Set());
  menuCounts.get(key).add(el);   // aynı sayı birden çok yerde (ör. Kişisel: kullanıcı menüsü + üst bardaki düğme)
  return el;
}
function syncMenuCounts(items) {
  const by = new Map(items.map(n => [n.key, n.count]));
  notifyCounts = by;
  by.set('personal', PERSONAL.reduce((a, p) => a + (by.get(p.notify) || 0), 0));
  for (const t of personalTileCounts) t();   // Kişisel paneli açıksa kutucuk sayıları
  for (const [key, els] of menuCounts) {
    const n = by.get(key) || 0;
    for (const el of els) { el.hidden = !n; el.textContent = n > 99 ? '99+' : n; }
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
let spotifyTimer;   // üst bardaki “şu an çalıyor” şeridi için anlık çalan parça yoklaması
let supportWatch, supportReq = null;   // merkez destek girişi: master onay bekleyen talebi izler

// Üst barın ORTASINDA “şu an çalıyor” şeridi: yalnız bir parça çalarken görünür (albüm kapağı + ekolayzer + kayan başlık).
// Spotify bağlı değilse hiç yoklanmaz (konsol kirliliği / gereksiz istek yok). Tıklayınca panoya (Spotify kutucuğu) gider.
function spotifyStrip() {
  const art = h('img', { class: 'np-art', alt: '', referrerpolicy: 'no-referrer' });
  const eq = h('span', { class: 'np-eq', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i'));
  const textInner = h('span', { class: 'np-text' });
  const marquee = h('div', { class: 'np-marquee' }, textInner);
  const strip = h('a', { class: 'np-strip', href: '#/', title: 'Spotify — şu an çalıyor', hidden: true }, art, eq, marquee);
  let connected = false;
  const setTrack = np => {
    if (!np || !np.playing || !np.is_playing) { strip.hidden = true; strip.classList.remove('np-scroll'); return; }
    const label = [np.title, np.artists].filter(Boolean).join(' · ') || 'Spotify';
    if (np.art) art.src = np.art; else art.removeAttribute('src');
    textInner.textContent = label;
    strip.hidden = false;
    requestAnimationFrame(() => {   // başlık taşıyorsa nazikçe kaydır (ölçülen taşma kadar)
      const dx = textInner.scrollWidth - marquee.clientWidth;
      if (dx > 4) { textInner.style.setProperty('--np-dx', `-${dx}px`); strip.classList.add('np-scroll'); }
      else strip.classList.remove('np-scroll');
    });
  };
  const poll = async () => { if (!connected) return; try { setTrack(await api.get('/api/spotify/now-playing')); } catch { strip.hidden = true; } };
  (async () => {
    try { connected = !!(await api.get('/api/spotify/status')).connected; } catch { connected = false; }
    if (connected) { poll(); clearInterval(spotifyTimer); spotifyTimer = setInterval(poll, 10000); }
  })();
  return strip;
}
function startSupportWatch() {
  clearInterval(supportWatch); supportReq = null;
  if (!ctx.user?.master) return;
  const check = async () => {
    let d; try { d = await api.get('/api/auth/crosslogin/pending'); } catch { return; }
    const ids = new Set((d.pending || []).map(r => r.id));
    if (supportReq && !ids.has(supportReq)) supportReq = null;   // yanıtlandı / süre doldu → tekrar açılabilir
    if (supportReq || !d.pending?.length) return;
    const req = d.pending[0]; supportReq = req.id;
    modal({
      title: 'Merkez destek girişi onayı',
      body: h('div', null,
        h('p', null, t('{name} ({user}) firmanıza destek için giriş yapmak istiyor.', { name: req.full_name, user: req.username })),
        h('p', { class: 'small muted' }, `IP: ${req.ip}`),
        h('p', { class: 'small muted' }, 'Onaylarsanız destek görevlisi süreli ve kayıt altında, master-benzeri yetkiyle girer. Oturumu dilediğinizde Program Ayarları’ndan sonlandırabilirsiniz.')),
      actions: [
        { label: 'Reddet', class: 'danger', onClick: async () => { try { await api.post(`/api/auth/crosslogin/${req.id}/decision`, { approve: false }); toast('Giriş reddedildi'); } catch (e) { toastError(e); } supportReq = null; } },
        { label: 'Onayla', class: 'primary', onClick: async () => { try { await api.post(`/api/auth/crosslogin/${req.id}/decision`, { approve: true }); toast('Onaylandı — destek girişi açıldı'); } catch (e) { toastError(e); } supportReq = null; } },
      ],
    });
  };
  supportWatch = setInterval(check, 5000); check();
}
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

// Bildirim satır(lar)ı: ad "kimden\nkonu" içeriyorsa iki satır (üstte kimden, altında konu); her satır taşarsa … ile kesilir.
// E-posta bildiriminde (n.mails) her satırda "Okundu" ve "Sil" düğmeleri: maile girmeden doğrudan işlenir.
function notifNames(n) {
  const wrap = h('div', { class: 'ntf-names' });
  if (n.key === 'mail-unread' && Array.isArray(n.mails) && n.mails.length) {
    for (const m of n.mails) {
      const row = h('div', { class: 'ntf-mail' });
      const act = async (action, e) => {
        e.preventDefault(); e.stopPropagation();
        try {
          await api.post(`/api/mail/${m.box_id}/action`, { folder: m.folder || 'inbox', uids: [m.uid], action });
          row.remove();
          toast(action === 'trash' ? 'E-posta silindi' : 'Okundu olarak işaretlendi');
          refreshNotify();
        } catch (err) { toastError(err); }
      };
      row.append(
        h('a', { class: 'ntf-mail-t', href: `#/mail/${m.box_id}/m/${m.uid}/${encodeURIComponent(m.folder || 'inbox')}` },
          h('div', { class: 'ntf-from' }, m.from || '(gönderen yok)'), h('div', { class: 'ntf-sub' }, m.subject || '(konu yok)')),
        h('div', { class: 'ntf-mail-acts' },
          h('button', { class: 'ntf-mb', type: 'button', title: 'Okundu işaretle', onclick: e => act('read', e) }, svgIcon(icons.read)),
          h('button', { class: 'ntf-mb del', type: 'button', title: 'Sil', onclick: e => act('trash', e) }, svgIcon(icons.delete))));
      wrap.append(row);
    }
    if (n.count > n.mails.length) wrap.append(h('div', { class: 'ntf-line muted' }, t('+{k} okunmamış e-posta daha', { k: n.count - n.mails.length })));
    return wrap;
  }
  for (const name of n.names) {
    const nl = name.indexOf('\n');
    if (nl >= 0) wrap.append(h('div', { class: 'ntf-item' },
      h('div', { class: 'ntf-from' }, name.slice(0, nl)), h('div', { class: 'ntf-sub' }, name.slice(nl + 1))));
    else wrap.append(h('div', { class: 'ntf-line' }, name));
  }
  if (n.count > n.names.length) wrap.append(h('div', { class: 'ntf-line muted' }, '…'));
  return wrap;
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
          h('div', { class: 'grow', style: { minWidth: '0' } }, h('b', null, n.title),
            n.detail ? h('div', { class: 'small', style: { color: 'var(--primary)', fontWeight: 600 } }, n.detail) : null,
            notifNames(n))))] : null,
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
  setDictationEnabled(ctx.user.speech);   // sesle yazdırma yalnız Konuşma Tanıma entegrasyonu açıkken
  popups.clear();
  menuCounts.clear();
  applySettings(ctx.user.prefs?.settings, ctx.user);
  const u = ctx.user;
  setChatUser(u);
  voice.connect(ctx);   // sesli görüşme WebSocket'i (gelen arama her ekranda çalar)
  radio.connect(ctx);   // telsiz: kanallardaki canlı konuşmalar her ekranda duyulur
  syncPush();          // arka plan bildirimi aboneliğini tazele (izin önceden verildiyse)
  mountMascot(ctx);     // köşedeki yapay zeka maskotu (anahtar tanımlıysa görünür)
  notesMod.initNotePins(ctx);   // ekrana iğnelenen notlar her sayfada görünür
  initAlarms();   // alarm denetleyicisi (saat gelince sesle uyarır)
  membershipMod.initSupportDock?.(ctx);   // firma: aktif canlı destek sohbeti başka sayfadayken köşede görünür
  const menuModules = MODULES.filter(m => m.menu && u.modules.includes(m.key));
  const menu = h('div', { class: 'dropdown', role: 'menu' },
    h('a', { class: 'menu-link', href: '#/settings', onclick: () => { menu.hidden = true; } }, svgIcon(icons.settings), 'Kişisel Ayarlar'),
    securityOnly() ? null : h('a', { class: 'menu-link', href: '#/meet', onclick: () => { menu.hidden = true; } }, svgIcon(icons.video), 'Görüntülü Toplantı'),
    h('a', { class: 'menu-link', href: '#', onclick: e => { e.preventDefault(); menu.hidden = true; import('./modules/screenshare.js').then(m => m.startScreenShare(ctx)); } }, svgIcon(icons.screen), 'Ekranı Paylaş'),
    u.modules.includes('uyelik') ? h('a', { class: 'menu-link', href: '#/uyelik/live', onclick: () => { menu.hidden = true; } }, svgIcon(icons.message || icons.chat || icons.person), 'Canlı Destek') : null,
    menuModules.map(m => h('a', { class: `menu-link ${m.tone ? `tone-${m.tone}` : ''}`, href: `#/${m.key}`,
      onclick: () => { menu.hidden = true; } }, svgIcon(icons[m.key]), m.title)),
    menuModules.length ? h('div', { class: 'menu-sep' }) : null,
    installButton(),
    (u.master || u.roles.includes('Sistem Yöneticisi')) ? h('a', { class: 'menu-link', href: '#/sysconfig', onclick: () => { menu.hidden = true; } }, svgIcon(icons.settings), 'Program Ayarları') : null,
    h('button', { onclick: () => { menu.hidden = true; aboutModal(); } }, 'Program Hakkında'),
    h('button', { onclick: logout }, 'Çıkış Yap'));
  const userBtn = h('button', { class: 'user-btn', 'aria-haspopup': 'menu' },
    avatar(u),
    h('span', { class: 'who' }, h('b', null, u.full_name), h('span', null, u.master ? 'MASTER · Sistem Sahibi' : (u.roles.join(', ') || 'Rol atanmamış'))));
  popup(userBtn, menu);
  // Mesajlar artık Kişisel panelinde; yine de sohbet yoklaması + yeni mesaj bildirimleri arka planda sürsün (düğme üst barda değil)
  if (!securityOnly()) chatButton(popup);

  view = h('main', { id: 'view' });
  scroller = h('div', { class: 'scroller' }, view);
  clear(root, h('div', { class: 'shell' },
    h('header', { class: 'app-header' },
      h('a', { class: 'brand', href: '#/' },
        h('img', { src: ctx.meta?.logo_url || '/static/img/logo.png', alt: ctx.meta?.company || '' }),
        ctx.meta?.white_label   // firma kendi markası: HEPGO yerine firma adı
          ? h('span', { class: 'product wl' }, h('b', null, ctx.meta.company || ''))
          : h('span', { class: 'product' }, h('b', null, 'HEPGO'), 'ERP')),
      spotifyStrip(),
      h('div', { class: 'header-right' }, radio.button(popup),
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
  initPanelCollapse(view);
  route();
}

// Tüm arayüzlerde panelleri (başlıkla başlayan .card/.set-card) katlanabilir yapar. Modülleri tek tek değiştirmeden
// #view'ı gözlemler; başlığa tıklayınca panel katlanır/açılır, durum cihazda hatırlanır. Pano kutucukları (.db-tile),
// KPI şeritleri, nav kartları ve modal içerikleri hariç.
let _collapseMO = null;
function initPanelCollapse(viewEl) {
  const KEY = 'hepgo.collapsed';
  const read = () => { try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch { return new Set(); } };
  const write = s => { try { localStorage.setItem(KEY, JSON.stringify([...s].slice(-800))); } catch { /* gizli pencere */ } };
  const keyOf = head => (location.hash || '').split('?')[0] + '|' + (head.textContent || '').trim().slice(0, 50);
  // Başlığı yazım düzenine çevir: HER kelimenin ilk harfi büyük, devamı küçük ("Ürün Ağacı"); bağlaçlar (ve, ile…)
  // ilk kelime değilse küçük; TÜMÜ BÜYÜK kısaltmalar (KVKK, İSG, CV, NVR, PDKS…) olduğu gibi korunur. Yalnız başlık
  // öğesinin METİN düğümlerini değiştirir (rozet/sayaç gibi alt öğeler korunur). Bir kez uygulanır (dataset işareti).
  const SMALL_WORDS = new Set(['ve', 'ile', 'veya', 'ya', 'da', 'de', 'ki', 'mi', 'mı', 'mu', 'mü']);
  const sentenceCase = el => {
    if (!el || el.dataset.sc) return;
    el.dataset.sc = '1';
    let first = true;
    el.childNodes.forEach(n => {
      if (n.nodeType !== 3) { if ((n.textContent || '').trim()) first = false; return; }
      if (!n.nodeValue || !/[\p{L}]/u.test(n.nodeValue)) return;
      n.nodeValue = n.nodeValue.replace(/\S+/g, w => {
        if (!/[\p{L}]/u.test(w)) return w;
        if (w.length >= 2 && w === w.toLocaleUpperCase('tr')) { first = false; return w; }   // kısaltma, dokunma
        const low = w.toLocaleLowerCase('tr');
        const cap = low.charAt(0).toLocaleUpperCase('tr') + low.slice(1);
        const out = (!first && SMALL_WORDS.has(low)) ? low : cap;
        first = false;
        return out;
      });
    });
  };
  // Panel başlığına konuya özel ikon: başlık metnindeki anahtar kelimeye göre (ilk eşleşen kazanır, özelden → genele).
  const PANEL_ICONS = [
    [['kvkk', 'aydınlat', 'rıza', 'onam', 'gizlilik'], '🔒'],
    [['sözleşme', 'şartlar', 'kullanım şart', 'taahhüt'], '📜'],
    [['imza'], '✍️'],
    [['ürün ağac', 'reçete', 'ağaç yapı'], '🌳'],
    [['yazıcı', 'baskı', 'basıl', 'kuyruk'], '🖨️'],
    [['kamera', 'nvr', 'görüntü kay'], '📹'],
    [['yüz tanı', 'yüz kay'], '🙂'],
    [['kkd', 'ppe', 'denetlenecek', 'iş güvenli', 'isg'], '🦺'],
    [['çıkış kontrol', 'güvenlik', 'nöbet'], '🛡️'],
    [['qr', 'karekod'], '🔳'],
    [['uçuş', 'uçak', 'saha', 'drone', 'pervane'], '🛩️'],
    [['depo', 'ambar', 'stok'], '📦'],
    [['sipariş'], '🧾'],
    [['fatura', 'irsaliye'], '🧾'],
    [['satış'], '💰'],
    [['satın', 'alım', 'tedarik'], '🛒'],
    [['üretim', 'iş emri', 'imalat', 'mrp'], '🏭'],
    [['bakım', 'onarım'], '🔧'],
    [['araç', 'plaka', 'filo'], '🚗'],
    [['bordro', 'maaş', 'ücret', 'puantaj'], '💵'],
    [['izin', 'tatil'], '🌴'],
    [['personel', 'çalışan', 'özlük', 'insan kaynak', 'görev'], '🧑‍💼'],
    [['toplantı', 'randevu'], '🤝'],
    [['takvim', 'etkinlik', 'ajanda'], '📅'],
    [['e-posta', 'eposta', 'mail', 'posta', 'gelen kutu'], '✉️'],
    [['mesaj', 'sohbet'], '💬'],
    [['bildirim', 'uyarı'], '🔔'],
    [['alarm', 'hatırlat'], '⏰'],
    [['not'], '📝'],
    [['evrak', 'belge', 'doküman', 'dokuman'], '📄'],
    [['dosya', 'klasör'], '📁'],
    [['rapor', 'istatistik', 'analiz', 'grafik', 'özet'], '📊'],
    [['entegrasyon'], '🔌'],
    [['yedek'], '💾'],
    [['üyelik', 'lisans', 'paket', 'abonelik'], '🎫'],
    [['yetki', 'rol'], '🗝️'],
    [['kullanıcı', 'hesap'], '👥'],
    [['adres', 'konum'], '📍'],
    [['harita', 'kroki'], '🗺️'],
    [['hava durum'], '🌤️'],
    [['dünya saat', 'saat', 'zaman'], '🕐'],
    [['spotify', 'müzik', 'şarkı', 'çalma list'], '🎵'],
    [['ssh', 'terminal', 'sunucu'], '🖥️'],
    [['telsiz'], '📻'],
    [['banka', 'iban', 'ödeme'], '🏦'],
    [['firma', 'şirket', 'cari', 'kurum'], '🏢'],
    [['rehber'], '📇'],
    [['kişi', 'iletişim', 'müşteri'], '👤'],
    [['telefon'], '📞'],
    [['transfer', 'yükleme', 'indirme'], '🔄'],
    [['maskot'], '🤖'],
    [['haber', 'duyuru', 'akış'], '📣'],
    [['ayar', 'tercih', 'konfig', 'seçenek'], '⚙️'],
    [['şema', 'çizim', 'teknik resim'], '📐'],
    [['bilgi', 'detay', 'tanım', 'genel', 'künye', 'kimlik'], 'ℹ️'],
  ];
  const iconFor = text => {
    const t = (text || '').toLocaleLowerCase('tr');
    for (const [keys, ic] of PANEL_ICONS) if (keys.some(k => t.includes(k))) return ic;
    return '📋';   // eşleşme yoksa nötr panel ikonu (her panel bir ikon alsın)
  };
  const addIcon = (head, titleEl) => {
    if (!titleEl) return;
    const txt = (titleEl.textContent || '').trim();
    if (!txt || /^\p{Extended_Pictographic}/u.test(txt)) return;   // başlık zaten ikon/emoji ile başlıyorsa dokunma
    const span = Object.assign(document.createElement('span'), { className: 'collapse-ic', textContent: iconFor(txt) });
    span.setAttribute('aria-hidden', 'true');
    const chev = head.querySelector(':scope > .collapse-chev');
    head.insertBefore(span, chev ? chev.nextSibling : head.firstChild);   // chevron'dan hemen sonra, başlıktan önce
  };
  // Panelin başlığı: ya düz başlık (h2-h4) ya da başlık satırı (başta h/b/strong + aksiyon/boşluk içeren satır; ör. .tv-bar)
  const headerOf = card => {
    const f = card.firstElementChild;
    if (!f || f.classList.contains('collapse-head')) return null;
    if (/^H[2-4]$/.test(f.tagName)) return f;
    if (!f.nextElementSibling || f.matches('.filters, .stat-strip, .seg-tabs, .tabs, .pick-list, .guest-list, .acc-list, .set-ios, .toolbar')) return null;
    const ti = f.firstElementChild;
    const isTitle = ti && (/^H[2-4]$/.test(ti.tagName) || /^(B|STRONG)$/.test(ti.tagName));
    // Başlık satırı: gerçek aksiyon düğmesi YA DA .spacer YA DA bar/head/title/toolbar sınıfı içermeli (başlık barı).
    // Böylece 'ad + rozet + tarih' içerik satırları (ör. sc-change-h) hariç kalır.
    const hasBtn = f.querySelector(':scope > .btn, :scope > button, :scope > a.btn');
    const hasSpacer = f.querySelector(':scope > .spacer');
    const barClass = f.className.split(/[\s-]+/).some(c => ['bar', 'head', 'header', 'heading', 'title', 'toolbar'].includes(c));
    return (isTitle && (hasBtn || hasSpacer || barClass)) ? f : null;
  };
  const make = (el, head, card) => {
    if (el.dataset.collapsible) return;
    el.dataset.collapsible = '1';
    el.classList.add('collapsible');
    head.classList.add('collapse-head');
    // Başlık satırıysa (düz başlık değil) başlık öğesini işaretle → sola yaslı büyür, düğmeler en sağa gider
    const isRow = !/^H[2-4]$/.test(head.tagName);
    if (isRow && head.firstElementChild) head.firstElementChild.classList.add('collapse-title');
    // Başlığı yazım düzenine çevir (her kelime ilk harfi büyük); KVKK/İSG/CV gibi kısaltmalar (tümü büyük) korunur
    const titleEl = isRow ? (head.querySelector(':scope > .collapse-title') || head) : head;
    sentenceCase(titleEl);
    // Düğmeleri en sağa it: başlık (+ varsa açıklama) solda, aksiyon düğmeleri sağda. Satırda .spacer varsa dokunma.
    if (isRow && !head.querySelector(':scope > .spacer')) {
      const fa = head.querySelector(':scope > .btn, :scope > button, :scope > a.btn');
      if (fa) fa.classList.add('collapse-push');
    }
    head.insertBefore(Object.assign(document.createElement('span'), { className: 'collapse-chev' }), head.firstChild);
    addIcon(head, titleEl);   // konuya özel ikon (chevron ile başlık arasına)
    if (read().has(keyOf(head))) el.classList.add('collapsed');
    head.addEventListener('click', e => {
      if (e.target.closest('button, a, input, select, textarea, label')) return;   // aksiyon öğeleri katlamaz
      const k = keyOf(head), s = read();
      el.classList.toggle('collapsed') ? s.add(k) : s.delete(k);
      write(s);
    });
    // Footer: son çocuk aksiyon satırı ise header renginde bant yap
    if (card) {
      const last = el.lastElementChild;
      if (last && last !== head && !last.classList.contains('panel-foot')
          && (last.querySelector(':scope > .btn, :scope > button, :scope > a.btn') || /foot|save|action|sign|actions/i.test(last.className))
          && (last.tagName === 'DIV' || last.tagName === 'FOOTER') && last.children.length <= 10) {
        last.classList.add('panel-foot');
      }
    }
  };
  const enhance = () => {
    viewEl.querySelectorAll('.card, .set-card').forEach(card => {
      if (card.tagName === 'A') return;
      if (['db-tile', 'stat-strip', 'empty', 'loading'].some(c => card.classList.contains(c))) return;
      if (card.closest('.grid-stack, .modal-back')) return;
      if (!card.dataset.collapsible) {
        const head = headerOf(card);
        if (head) make(card, head, true);
      }
      // İç içe (nested) bölümler: başlıkla (h3/h4) başlayan ve içeriği olan alt bloklar — ör. görev tanımı maddeleri
      card.querySelectorAll('h3, h4').forEach(hd => {
        const par = hd.parentElement;
        if (!par || par === card || par.dataset.collapsible || par.closest('.collapse-head, .panel-foot')) return;
        if (par.firstElementChild !== hd || !hd.nextElementSibling) return;
        if (hd.matches('.set-sub, .sub-h, .dd-role')) return;
        if (par.querySelectorAll(':scope > h2, :scope > h3, :scope > h4').length > 1) return;   // düz başlık listesi değil, tek bölüm olmalı
        make(par, hd, false);
      });
    });
    // Gevşek bölüm başlıkları (kart içinde DEĞİL): h3/h4 + ardından gelen içerik (ör. "Şema çizimi"). Başlığa tıklayınca
    // sonraki başlığa kadar olan kardeşler gizlenir. Sayfa başlığı (.page-head) ve bilinen alt-etiketler hariç.
    viewEl.querySelectorAll('h3, h4').forEach(hd => {
      if (hd.dataset.collapsible) return;
      if (hd.closest('.card, .set-card, .collapse-head, .panel-foot, .grid-stack, .page-head, .modal-back')) return;
      if (hd.matches('.set-sub, .sub-h, .dd-role')) return;
      const sibs = [];
      for (let n = hd.nextElementSibling; n; n = n.nextElementSibling) { if (/^H[1-4]$/.test(n.tagName)) break; sibs.push(n); }
      if (!sibs.length) return;
      hd.dataset.collapsible = '1';
      hd.classList.add('collapse-head', 'loose-head');
      sentenceCase(hd);
      hd.insertBefore(Object.assign(document.createElement('span'), { className: 'collapse-chev' }), hd.firstChild);
      addIcon(hd, hd);   // konuya özel ikon
      const k = keyOf(hd);
      const apply = col => { hd.classList.toggle('collapsed', col); sibs.forEach(s => { s.style.display = col ? 'none' : ''; }); };
      if (read().has(k)) apply(true);
      hd.addEventListener('click', e => {
        if (e.target.closest('button, a, input, select, textarea, label')) return;
        const col = !hd.classList.contains('collapsed');
        apply(col);
        const s = read(); col ? s.add(k) : s.delete(k); write(s);
      });
    });
  };
  if (_collapseMO) _collapseMO.disconnect();
  let deb;
  _collapseMO = new MutationObserver(() => { clearTimeout(deb); deb = setTimeout(enhance, 80); });
  _collapseMO.observe(viewEl, { childList: true, subtree: true });
  enhance();
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
    h('img', { class: 'fb-mark', src: '/static/img/logo-mark.png?v=3', alt: '' }),
    h('span', { class: 'fb-name' }, `© ${year} ${company}`));
  const hover = matchMedia('(hover: hover) and (pointer: fine)').matches;
  let pop = null, closeTimer;
  const close = () => { if (pop) { pop.remove(); pop = null; badge.classList.remove('open'); document.removeEventListener('click', close); } };
  const open = () => {
    if (pop) return;
    pop = h('div', { class: 'sb-pop fb-pop', role: 'dialog', onclick: e => e.stopPropagation(),
      onmouseenter: () => clearTimeout(closeTimer), onmouseleave: () => { if (hover) closeTimer = setTimeout(close, 300); } },
      h('img', { class: 'fb-logo', src: ctx.meta?.logo_url || '/static/img/logo.png', alt: company }),
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
  if (!d.entries?.length) {   // sürüm notları yalnızca MASTER'a açık; diğerleri yalnız sürüm numarasını görür
    return modal({ title: 'Program Hakkında', body: h('div', { class: 'about-plain' }, h('b', null, `Sürüm ${d.version}`)), actions: [{ label: 'Kapat' }] });
  }
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
  if (!ctx.user?.master) return;   // sürüm notları yalnızca MASTER
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
  if (!ctx.user?.master || !seen || verCmp(d.version, seen) <= 0 || document.getElementById('wn-chip')) return;   // "Neler değişti?" yalnız MASTER
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
    ctx.user?.master ? h('button', { class: 'btn sm ghost-light', type: 'button', onclick: () => whatsNewModal(loadedVersion) }, 'Neler değişti?') : null,
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
  clearInterval(spotifyTimer);
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
  tickets: p => { const k = (p[0] || '').split('?')[0]; return k === 't' ? `Talep #${p[1]}` : k === 'live' ? (p[1] ? `Canlı Destek › Sohbet #${p[1]}` : 'Canlı Destek')
    : ({ list: 'Talepler', team: 'Ekip', canned: 'Hazır Yanıtlar', settings: 'Ayarlar' }[k] || k); },
  uyelik: p => { const k = (p[0] || '').split('?')[0]; const lbl = { overview: 'Genel Bakış', live: 'Canlı Destek', tickets: 'Destek Taleplerim', payments: 'Ödemelerim', contracts: 'Sözleşmelerim' }[k] || k;
    return p[1] ? `${lbl} #${p[1]}` : lbl; },
  projects: p => { const k = (p[0] || '').split('?')[0]; return /^\d+$/.test(k) ? `Proje #${k}` : ({ queue: 'Hareketlere Proje', scan: 'Proje Taraması' }[k] || k); },
  fleet: p => { const k = (p[0] || '').split('?')[0]; return /^\d+$/.test(k) ? `Araç #${k}` : ({ moves: 'Gider Etiketleme', report: 'Rapor', settings: 'Zimmet Formu' }[k] || k); },
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
  if (key === 'my-vehicles') return 'Kişisel › Araç Zimmetim';
  if (key === 'master') return `MASTER${params[0] ? ` › Kullanıcı #${params[0]}` : ''}`;
  if (key === 'purchasing') return `Satın Alma${params.length ? ` › ${{ requests: 'Talep Yönetimi', suppliers: 'Tedarikçi Yönetimi', invoices: 'Fatura İrsaliye', quotes: 'Teklif Yönetimi' }[params[0]] || params[0]}${params[1] ? ` #${params[1]}` : ''}` : ''}`;
  if (key === 'mrp') return `MRP${params.length ? ` › ${{ materials: 'Malzeme Yönetimi', semi: 'Yarı Mamül', approvals: 'Onay Yönetimi', depots: 'Depo Yönetimi' }[params[0]] || params[0]}${params[1] ? ` #${params[1]}` : ''}` : ''}`;
  if (key === 'meetings') return params[0] ? `Kişisel › Toplantı #${params[0]}` : 'Kişisel › Toplantılar';
  if (key === 'settings') return params[0] ? `Ayarlar › ${params[0].split('?')[0]}` : 'Ayarlar';
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
  { key: 'vehicles', route: 'my-vehicles', title: 'Araç Zimmetim', notify: 'vehicle-assign-pending', render: () => fleet.renderMine(view) },
  { key: 'notes', route: 'my-notes', title: 'Notlar', notify: null, render: () => notesMod.render(view, ctx) },
  { key: 'files', route: 'my-files', title: 'Dosya Yöneticisi', notify: 'file-shared', render: params => fileManager.render(view, params, ctx) },
  { key: 'duties', route: 'my-duties', title: 'Görev Formu', notify: 'duty-decided', render: params => duty.render(view, params, ctx) },
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
  if (key === 'live' && params[0]) {   // canlı yayın izle: ana ekranın üstünde tam ekran
    view.className = '';
    await renderHome();
    return import('./modules/live.js').then(lv => lv.watch(Number(params[0]), ctx)).catch(err => toastError(err));
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
      .then(() => { if (!(personal.key === 'meetings' && params[1]) && personal.key !== 'files') personalHead(personal); refreshNotify(); })   // toplantı ekranı / özeti + Dosya Yöneticisi kendi başlığıyla (alt-modül seçicisi yok)
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
    // Rol Yönetimi: bu modülde yalnızca okuma yetkisi varsa üstte bilgi şeridi (kaydetme istekleri sunucuda reddedilir)
    if (!ctx.user.master && ctx.user.write_modules && !ctx.user.write_modules.includes(key) && key === location.hash.slice(2).split('/')[0]) {
      view.prepend(h('div', { class: 'ro-banner' }, '👁 ', t('Bu modülde yalnızca görüntüleme yetkiniz var; değişiklikler kaydedilmez.')));
    }
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
enableToolbarMerge();   // alt-modül eylem düğmelerini (Yeni/Excel/görünüm) filtre satırına taşır (boşuna satır olmasın)
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
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register('/sw.js').catch(() => {});
  let swReloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!hadController || swReloaded) return;   // ilk kurulumda değil, yalnız GÜNCELLEMEDE bir kez yenile
    swReloaded = true; safeReload();
  });
}
// ANINDA GÜNCELLEME: açık uygulama arayüz sürümünü yoklar; sunucuya yeni sürüm deploy edilince kendini yeniler
// (kullanıcıyı bölmeden: modal/okuma açıkken, yazarken ya da aramada ERTELER; sonraki yoklamada yeniler).
function safeReload() {
  try {
    const ae = document.activeElement, tag = ae && ae.tagName;
    const busy = document.querySelector('.modal-back, .gm-reader.open, .voice-call, .screen-share, .fv-overlay')
      || tag === 'INPUT' || tag === 'TEXTAREA' || (ae && ae.isContentEditable) || window.__inCall;
    if (busy) return false;
  } catch { /* yut */ }
  location.reload();
  return true;
}
let verReloaded = false;
function checkUpdate() {
  if (verReloaded || !window.__VER) return;
  fetch('/api/version', { cache: 'no-store' }).then(r => r.json()).then(d => {
    if (d && d.ver && d.ver !== window.__VER) { if (safeReload()) verReloaded = true; }
  }).catch(() => {});
}
setInterval(checkUpdate, 3 * 60000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkUpdate(); });
// iOS/Android uygulama kabuğunda (Capacitor): native köprüyü yükle (push + konum + çevrimdışı kaplaması). Tarayıcıda çalışmaz.
if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
  const ns = document.createElement('script'); ns.src = '/static/js/native.js'; document.head.appendChild(ns);
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
