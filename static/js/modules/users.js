// Kullanıcı Yönetimi (yalnızca Sistem Yöneticisi)
import { setListExport } from '../listexport.js';
import { segIcon } from '../segicons.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import {
  avatar, clear, confirmDialog, field, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref, statStrip, svgIcon, t,
  toast, toastError, periodRange
} from '../ui.js';
import { conflictModal } from './roles.js';

// Rol Yönetimi: atanan roller arasında izin / yasak çakışması ya da görev ayrılığı varsa uyar (yasak geçerlidir)
const warnConflicts = (name, c) => { if (c && (c.perm?.length || c.sod?.length)) conflictModal([{ user: name, ...c }]); };

export async function render(view, params, ctx) {
  if (params[0]) return renderDetail(view, Number(params[0]), params[1] || 'edit', ctx);
  return renderList(view, ctx);
}

// ---------- Liste ----------
async function renderList(view, ctx) {
  let mode = pref('users.view', 'cards');
  // Filtreler başlıkta (bilgilendirme kartları ve arama yok)
  const role = selectInput(ctx.meta.roles.map(r => [r, r]), { all: 'Tüm roller' });
  const act = selectInput([['1', 'Aktif'], ['0', 'Pasif']], { all: 'Aktif ve pasif' });
  const body = h('div');
  let users = [];
  const draw = () => {
    const list = users.filter(u => (!role.value || u.roles.includes(role.value)) && (!act.value || String(u.active) === act.value));
    clear(body, list.length ? (mode === 'cards' ? cards(list) : table(list)) : h('div', { class: 'card empty' }, 'Kullanıcı bulunamadı'));
    setListExport(() => ({ columns: ['Ad Soyad', 'Kullanıcı adı', 'Telefon', 'Roller', 'Durum', 'Son giriş'],
      rows: list.map(u => [u.full_name, u.username, u.phone || '', (u.roles || []).join(', '), u.active ? (u.absence ? u.absence.label : 'Aktif') : 'Pasif', u.last_login || u.last_seen || '']) }));
  };
  const load = async () => { users = await api.get('/api/users'); draw(); };
  role.addEventListener('change', draw);
  act.addEventListener('change', draw);

  clear(view,
    pageHead('Kullanıcı Yönetimi', { back: '#/' }),
    moduleToolbar(
      role, act,
      h('button', { class: 'btn primary', onclick: () => userForm(null, ctx, load) }, svgIcon(icons.plus), 'Yeni Kullanıcı'),
      segmented([['cards', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('users.view', v); draw(); })),
    body);
  await load();
}

const open = u => { location.hash = `#/users/${u.id}`; };

// Kaba kuvvet kilidi: kilitliyse kırmızı "Kilitli · Aç" rozeti; tıklayınca (sistem yöneticisi) kilidi açar.
// <span> kullanılır (satır görünümü <button>, iç içe <button> geçersiz olur).
function lockInfo(u) {
  if (!u.locked) return null;
  return h('span', { class: 'badge red u-unlock', role: 'button', tabindex: '0',
    title: t('Çok fazla hatalı şifre; {n} dk kilitli. Kilidi açmak için tıklayın.', { n: u.locked }),
    onclick: async e => {
      e.stopPropagation(); e.preventDefault();
      try { await api.post(`/api/users/${u.id}/unlock`); toast(t('{name} kilidi açıldı', { name: u.full_name })); window.dispatchEvent(new HashChangeEvent('hashchange')); }
      catch (err) { toastError(err); }
    } }, '🔒 ', t('Kilitli ({n} dk) · Aç', { n: u.locked }));
}

function cards(users) {
  return h('div', { class: 'grid-cards' }, users.map(u =>
    h('div', { class: 'card user-card', onclick: () => open(u) },
      avatar(u, 'lg'),
      h('div', { class: 'name' }, u.full_name),
      h('div', { class: 'uname' }, u.username),
      h('div', { class: 'chips' }, u.roles.map(r => h('span', { class: `chip ${r === 'Stajer' ? 'intern' : ''}` }, r))),
      u.active ? null : h('span', { class: 'badge red' }, 'Pasif'),
      lockInfo(u),
      u.absence ? h('span', { class: `badge ${u.absence.kind === 'RAPOR' ? 'yellow' : 'blue'}`, title: t('{d} tarihine kadar', { d: u.absence.until }) }, u.absence.label) : null,
      u.external ? h('a', { class: 'badge purple', href: u.external.href, title: 'Dış firma personeli (İK personeli değil)' }, t('Dış firma: {name}', { name: u.external.company_name })) : null)));
}

const DEVICE_LABEL = { android_app: 'Android App', ios_app: 'iOS App', web_mobile: 'Mobil Web', web: 'Web App' };   // çevrimiçi oturumun cihaz türü
// WhatsApp tarzı satır listesi: çevrimiçi ise avatar etrafında yeşil halka, pasif kullanıcıda tüm satır gri. Tutarlı satır yükseklikleri.
function table(users) {
  return h('div', { class: 'u-list' }, users.map(u =>
    h('button', { class: `u-row ${u.active ? '' : 'passive'} ${u.is_foreign ? 'foreign' : ''} ${u.external ? 'external' : ''}`, type: 'button', onclick: () => open(u) },
      h('span', { class: `u-av ${u.active && u.online ? 'online' : ''}`, title: u.active && u.online ? 'Çevrimiçi' + (u.device ? ' · ' + (DEVICE_LABEL[u.device] || u.device) : '') : null }, avatar(u, 'md')),
      h('div', { class: 'u-row-mid' },
        h('div', { class: 'u-row-top' }, h('b', null, u.full_name),
          u.active ? null : h('span', { class: 'u-pill' }, 'Pasif'),
          lockInfo(u),
          u.absence ? h('span', { class: `badge ${u.absence.kind === 'RAPOR' ? 'yellow' : 'blue'}`, title: t('{d} tarihine kadar', { d: u.absence.until }) }, u.absence.label) : null,
          u.external ? h('span', { class: 'badge purple' }, t('Dış: {name}', { name: u.external.company_name })) : null),
        h('div', { class: 'u-row-sub' }, u.username, u.active && u.online && u.device ? h('span', { class: 'u-dev' }, ' · ' + (DEVICE_LABEL[u.device] || u.device)) : null)),
      h('div', { class: 'u-row-end' },
        h('span', { class: 'u-row-roles' }, u.roles.join(', ') || '—'),
        h('span', { class: 'u-row-seen' }, fmtDateTime(u.last_login) || '—')))));
}

// ---------- Form (yeni / düzenle) ----------
function formFields(user, ctx) {
  const f = {
    username: h('input', { class: 'input', type: 'email', value: user?.username || '', autocomplete: 'off' }),
    full_name: h('input', { class: 'input', value: user?.full_name || '' }),
    phone: h('input', { class: 'input', type: 'tel', value: user?.phone || '' }),
    password: h('input', { class: 'input', type: 'password', autocomplete: 'new-password' }),
    active: h('input', { type: 'checkbox', checked: user ? !!user.active : true }),
    ai_offtopic: h('input', { type: 'checkbox', checked: user ? user.ai_offtopic !== 0 : true }),
    location_off: h('input', { type: 'checkbox', checked: user ? !!user.location_off : false }),
    roles: ctx.meta.roles.map(r => [r, h('input', { type: 'checkbox', checked: !!user?.roles.includes(r) })]),
  };
  const el = h('div', null,
    h('div', { class: 'row' }, field('Personel adı soyadı', f.full_name), field('Telefon', f.phone)),
    field('Kullanıcı adı (e-posta)', f.username),
    field(user ? 'Yeni şifre' : 'Şifre', f.password, user ? 'Boş bırakırsanız şifre değişmez. En az 8 karakter.' : 'En az 8 karakter'),
    h('fieldset', { class: 'uf-group' }, h('legend', null, 'Roller'),
      h('p', { class: 'uf-info' }, 'Roller, kullanıcının hangi modülleri göreceğini, hangi işlemleri yapabileceğini ve hangi bildirimleri alacağını belirler. Birden çok rol seçilebilir.'),
      h('div', { class: 'uf-roles' }, f.roles.map(([r, cb]) => h('label', { class: 'check' }, cb, r)))),
    h('fieldset', { class: 'uf-group' }, h('legend', null, 'Hesap Durumu'),
      h('label', { class: 'check' }, f.active, h('b', null, 'Hesap aktif')),
      h('p', { class: 'uf-info' },
        'Açıkken kullanıcı sisteme giriş yapabilir. Kapatıldığında (pasif): kullanıcı giriş yapamaz ve açık oturumu bir sonraki işlemde sonlanır; ',
        'görev, sohbet ve atama listelerinde seçilemez. Kullanıcının geçmiş kayıtları, mesajları ve raporları silinmez; hesap istenildiği zaman yeniden aktif edilebilir. ',
        'İşten ayrılan ya da uzun süre kullanmayacak kişiler için silmek yerine pasif yapmanız önerilir.')),
    ctx.user.ai === false ? null : h('fieldset', { class: 'uf-group' }, h('legend', null, 'Yapay Zeka Asistanı'),
      h('label', { class: 'check' }, f.ai_offtopic, h('b', null, 'Sistem dışı (genel) soru sorabilir')),
      h('p', { class: 'uf-info' },
        'Asistan (Kubbe) sistemle ilgili soruları her kullanıcıya, yalnızca kullanıcının yetkili olduğu veriler üzerinden yanıtlar. ',
        'Bu seçenek açıksa kullanıcı sistem dışı genel sorular da sorabilir (ör. genel bilgi, çeviri, metin yazma); kapalıysa asistan bu tür soruları kibarca geri çevirir. ',
        'Tüm sorular kullanıcının aylık token kotasından düşer (Program Ayarları › Yapay Zeka).')),
    h('fieldset', { class: 'uf-group' }, h('legend', null, 'Konum'),
      h('label', { class: 'check' }, f.location_off, h('b', null, 'Konumu kapat')),
      h('p', { class: 'uf-info' },
        'Açıkken bu kullanıcının konum bilgisi HİÇ alınmaz: mesai, görev ya da rol fark etmeksizin konum kaydedilmez ve ',
        'Canlı Konum haritasında görünmez. Açtığınızda kullanıcının geçmiş konum kayıtları da silinir. ',
        'Bu, kullanıcının kendi “mesai dışında konumu kapat” ayarından bağımsız, yönetici seviyesinde bir kapatmadır.')));
  const value = () => ({
    username: f.username.value.trim(),
    full_name: f.full_name.value.trim(),
    phone: f.phone.value.trim() || null,
    password: f.password.value || null,
    active: f.active.checked,
    ai_offtopic: f.ai_offtopic.checked,
    location_off: f.location_off.checked,
    roles: f.roles.filter(([, cb]) => cb.checked).map(([r]) => r),
  });
  return { el, value };
}

function userForm(user, ctx, done) {
  const form = formFields(user, ctx);
  modal({
    title: 'Yeni Kullanıcı', body: form.el, wide: true,
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const { id, conflicts } = await api.post('/api/users', form.value());
          toast('Kullanıcı oluşturuldu');
          warnConflicts(form.value().full_name, conflicts);
          location.hash = `#/users/${id}`;
          done?.();
        },
      },
    ],
  });
}

// ---------- Detay ----------
const TABS = [['edit', 'Bilgileri Düzenle'], ['logs', 'Kullanıcı Logları'], ['logins', 'Giriş Logları']];

async function renderDetail(view, id, tab, ctx) {
  const user = await api.get(`/api/users/${id}`);
  const content = h('div', { class: 'card card-pad' });
  clear(view,
    pageHead(user.full_name, { back: '#/users', sub: user.username }),
    h('div', { class: 'split' },
      h('nav', { class: 'card side-nav' },
        h('div', { class: 'who' }, avatar(user, 'lg'), h('b', null, user.full_name),
          h('div', { class: 'chips' }, user.roles.map(r => h('span', { class: `chip ${r === 'Stajer' ? 'intern' : ''}` }, r)))),
        TABS.map(([k, label]) => h('a', { href: `#/users/${id}/${k}`, class: k === tab ? 'on' : '' }, segIcon(label), label))),
      content));

  if (tab === 'logs') return renderLogs(content, id);
  if (tab === 'logins') return renderLogins(content, id);
  return renderEdit(content, user, ctx);
}

function renderEdit(content, user, ctx) {
  const form = formFields(user, ctx);
  const photo = h('input', { type: 'file', accept: 'image/*', hidden: true });
  photo.addEventListener('change', async () => {
    if (!photo.files[0]) return;
    const fd = new FormData();
    fd.append('file', photo.files[0]);
    try {
      await api.post(`/api/users/${user.id}/photo`, fd);
      toast('Resim güncellendi');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    } catch (err) { toastError(err); }
  });
  const save = h('button', { class: 'btn primary' }, 'Kaydet');
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      const res = await api.put(`/api/users/${user.id}`, form.value());
      toast('Bilgiler kaydedildi');
      warnConflicts(form.value().full_name, res?.conflicts);
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    } catch (err) {
      toastError(err);
    } finally {
      save.disabled = false;
    }
  });
  clear(content,
    h('div', { style: { display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '18px' } },
      avatar(user, 'lg'),
      h('div', null, h('button', { class: 'btn', onclick: () => photo.click() }, 'Resim Yükle'), photo,
        h('div', { class: 'small muted', style: { marginTop: '4px' } }, 'JPG, PNG veya WEBP'))),
    form.el,
    h('div', { style: { marginTop: '16px', display: 'flex', justifyContent: 'space-between', gap: '8px' } },
      user.id === ctx.user.id ? h('span') : h('button', { class: 'btn danger', onclick: () => removeUser(user) }, 'Kullanıcıyı Sil'),
      save));
}

async function removeUser(user) {
  if (!await confirmDialog('Kullanıcıyı sil',
    t('{name} ({u}) silinsin mi? Kullanıcı sisteme giriş yapamaz ve listeden kaldırılır. ', { name: user.full_name, u: user.username })
    + 'Üretim, depo veya saha kayıtlarında adı geçiyorsa bu geçmiş kayıtlarda adı görünmeye devam eder.',
    { okLabel: 'Sil', danger: true })) return;
  try {
    const { mode } = await api.del(`/api/users/${user.id}`);
    toast(mode === 'archived' ? t('{name} silindi (geçmiş kayıtlardaki adı korundu)', { name: user.full_name }) : t('{name} silindi', { name: user.full_name }));
    location.hash = '#/users';
  } catch (err) { toastError(err); }
}

const KIND_BADGE = {
  'Sayfaya girdi': 'blue', 'Sayfadan çıktı': 'gray', 'Yazdırdı': 'purple', 'Açtı': 'gray',
  'Sisteme giriş yaptı': 'green', 'Sistemden çıkış yaptı': 'gray',
};
const fmtSec = iso => (iso ? `${fmtDateTime(iso)}:${iso.slice(17, 19)}` : '—');

async function renderLogs(content, id) {
  const stats = statStrip();
  const kind = selectInput([['page', 'Sayfa hareketleri'], ['action', 'İşlemler']], { all: 'Tüm kayıtlar' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'İşlem, sayfa veya detay ara…', style: { width: '220px' } });
  const wk = periodRange('week');   // varsayılan: bu hafta
  const from = h('input', { class: 'input', type: 'date', title: 'Başlangıç tarihi', value: wk.date_from });
  const to = h('input', { class: 'input', type: 'date', title: 'Bitiş tarihi', value: wk.date_to });
  const limit = selectInput([['200', 'Son 200'], ['1000', 'Son 1000'], ['5000', 'Son 5000']], { all: null, value: '1000' });
  const count = h('span', { class: 'small muted' });
  const body = h('div');
  const load = async () => {
    const qs = new URLSearchParams({ kind: kind.value, q: q.value.trim(), date_from: from.value, date_to: to.value, limit: limit.value });
    const d = await api.get(`/api/users/${id}/logs?${qs}`);
    const s = d.summary;
    stats.set([
      { icon: 'documents', label: 'Toplam kayıt', value: s.all },
      { icon: 'read', label: 'Sayfa girişi', value: s.page_views },
      { icon: 'terminal', label: 'İşlem', value: s.actions },
      { icon: 'calendar', label: 'Bugünkü kayıt', value: s.today },
    ]);
    count.textContent = d.total > d.rows.length ? t('{a} / {b} kayıt gösteriliyor', { a: d.rows.length, b: d.total }) : t('{n} kayıt', { n: d.total });
    clear(body, d.rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Zaman', 'Tür', 'Hareket', 'Sayfa / detay'].map(t => h('th', null, t)))),
      h('tbody', null, d.rows.map(l => h('tr', null,
        h('td', { class: 'muted mono small' }, fmtSec(l.at)),
        h('td', null, l.entity === 'page' ? h('span', { class: 'badge blue' }, 'Sayfa') : h('span', { class: 'badge purple' }, 'İşlem')),
        h('td', null, h('span', { class: `badge ${KIND_BADGE[l.action] || 'gray'}` }, l.action)),
        h('td', { style: { whiteSpace: 'normal' } }, l.detail || '—',
          l.entity === 'page' && l.entity_id ? h('div', { class: 'small muted mono' }, l.entity_id) : null))))))
      : h('div', { class: 'empty' }, 'Filtreye uyan kayıt yok'));
  };
  let qTimer;
  q.addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(load, 300); });
  [kind, from, to, limit].forEach(el => el.addEventListener('change', load));
  clear(content,
    h('h2', { style: { fontSize: '16px', marginBottom: '12px' } }, 'Kullanıcı Logları'),
    stats,
    h('div', { class: 'filters' }, kind, q, h('span', { class: 'lbl' }, 'Tarih'), from, to, limit, h('span', { class: 'spacer' }), count),
    body);
  await load();
}

async function renderLogins(content, id) {
  const logs = await api.get(`/api/users/${id}/logins`);
  const stats = statStrip();
  const result = selectInput([['1', 'Başarılı'], ['0', 'Hatalı şifre']], { all: 'Tüm sonuçlar' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'IP veya tarayıcı ara…', style: { width: '200px' } });
  const wkl = periodRange('week');
  const from = h('input', { class: 'input', type: 'date', value: wkl.date_from });
  const to = h('input', { class: 'input', type: 'date', value: wkl.date_to });
  const body = h('div');
  const ok = logs.filter(l => l.success);
  stats.set([
    { icon: 'person', label: 'Toplam giriş denemesi', value: logs.length },
    { icon: 'security', label: 'Başarılı', value: ok.length, tone: 'ok' },
    { icon: 'warning', label: 'Hatalı şifre', value: logs.length - ok.length, tone: logs.length - ok.length ? 'alert' : '' },
    { icon: 'network', label: 'Farklı IP adresi', value: new Set(logs.map(l => l.ip)).size },
  ]);
  const draw = () => {
    const rows = logs.filter(l => (!result.value || String(l.success) === result.value) &&
      (!from.value || l.at.slice(0, 10) >= from.value) && (!to.value || l.at.slice(0, 10) <= to.value) &&
      matches(q.value, l.ip, l.user_agent));
    clear(body, rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Zaman', 'Sonuç', 'IP adresi', 'Tarayıcı'].map(t => h('th', null, t)))),
      h('tbody', null, rows.map(l => h('tr', null,
        h('td', { class: 'muted mono small' }, fmtSec(l.at)),
        h('td', null, l.success ? h('span', { class: 'badge green' }, 'Başarılı') : h('span', { class: 'badge red' }, 'Hatalı şifre')),
        h('td', { class: 'mono' }, l.ip || '—'),
        h('td', { class: 'small muted', style: { whiteSpace: 'normal', maxWidth: '420px' } }, l.user_agent || '—'))))))
      : h('div', { class: 'empty' }, 'Filtreye uyan giriş kaydı yok'));
  };
  q.addEventListener('input', draw);
  [result, from, to].forEach(el => el.addEventListener('change', draw));
  clear(content, h('h2', { style: { fontSize: '16px', marginBottom: '12px' } }, 'Giriş Logları'), stats,
    h('div', { class: 'filters' }, result, q, h('span', { class: 'lbl' }, 'Tarih'), from, to), body);
  draw();
}
