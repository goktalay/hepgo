// Kullanıcı Yönetimi (yalnızca Sistem Yöneticisi)
import { segIcon } from '../segicons.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import {
  avatar, clear, confirmDialog, field, fmtDateTime, h, matches, modal, pageHead, pref, segmented, selectInput, setPref, statStrip, svgIcon,
  toast, toastError,
} from '../ui.js';

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
  };
  const load = async () => { users = await api.get('/api/users'); draw(); };
  role.addEventListener('change', draw);
  act.addEventListener('change', draw);

  clear(view,
    pageHead('Kullanıcı Yönetimi', { back: '#/', right: h('div', { class: 'head-right' },
      role, act,
      h('button', { class: 'btn primary', onclick: () => userForm(null, ctx, load) }, svgIcon(icons.plus), 'Yeni Kullanıcı'),
      segmented([['cards', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('users.view', v); draw(); })) }),
    body);
  await load();
}

const open = u => { location.hash = `#/users/${u.id}`; };

function cards(users) {
  return h('div', { class: 'grid-cards' }, users.map(u =>
    h('div', { class: 'card user-card', onclick: () => open(u) },
      avatar(u, 'lg'),
      h('div', { class: 'name' }, u.full_name),
      h('div', { class: 'uname' }, u.username),
      h('div', { class: 'chips' }, u.roles.map(r => h('span', { class: 'chip' }, r))),
      u.active ? null : h('span', { class: 'badge red' }, 'Pasif'))));
}

function table(users) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null, ['', 'Personel', 'Kullanıcı adı', 'Roller', 'Durum', 'Son giriş'].map(t => h('th', null, t)))),
    h('tbody', null, users.map(u => h('tr', { class: 'click', onclick: () => open(u) },
      h('td', { style: { width: '48px' } }, avatar(u)),
      h('td', null, h('b', null, u.full_name)),
      h('td', { class: 'muted' }, u.username),
      h('td', { style: { whiteSpace: 'normal' } }, u.roles.join(', ') || '—'),
      h('td', null, u.active ? h('span', { class: 'badge green' }, 'Aktif') : h('span', { class: 'badge red' }, 'Pasif')),
      h('td', { class: 'muted' }, fmtDateTime(u.last_login)))))));
}

// ---------- Form (yeni / düzenle) ----------
function formFields(user, ctx) {
  const f = {
    username: h('input', { class: 'input', type: 'email', value: user?.username || '', autocomplete: 'off' }),
    full_name: h('input', { class: 'input', value: user?.full_name || '' }),
    phone: h('input', { class: 'input', type: 'tel', value: user?.phone || '' }),
    password: h('input', { class: 'input', type: 'password', autocomplete: 'new-password' }),
    active: h('input', { type: 'checkbox', checked: user ? !!user.active : true }),
    roles: ctx.meta.roles.map(r => [r, h('input', { type: 'checkbox', checked: !!user?.roles.includes(r) })]),
  };
  const el = h('div', null,
    h('div', { class: 'row' }, field('Personel adı soyadı', f.full_name), field('Telefon', f.phone)),
    field('Kullanıcı adı (e-posta)', f.username),
    field(user ? 'Yeni şifre' : 'Şifre', f.password, user ? 'Boş bırakırsanız şifre değişmez. En az 8 karakter.' : 'En az 8 karakter'),
    field('Roller', h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: '6px' } },
      f.roles.map(([r, cb]) => h('label', { class: 'check' }, cb, r)))),
    h('label', { class: 'check' }, f.active, 'Hesap aktif'));
  const value = () => ({
    username: f.username.value.trim(),
    full_name: f.full_name.value.trim(),
    phone: f.phone.value.trim() || null,
    password: f.password.value || null,
    active: f.active.checked,
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
          const { id } = await api.post('/api/users', form.value());
          toast('Kullanıcı oluşturuldu');
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
          h('div', { class: 'chips' }, user.roles.map(r => h('span', { class: 'chip' }, r)))),
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
      await api.put(`/api/users/${user.id}`, form.value());
      toast('Bilgiler kaydedildi');
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
    `${user.full_name} (${user.username}) silinsin mi? Kullanıcı sisteme giriş yapamaz ve listeden kaldırılır. `
    + 'Üretim, depo veya saha kayıtlarında adı geçiyorsa bu geçmiş kayıtlarda adı görünmeye devam eder.',
    { okLabel: 'Sil', danger: true })) return;
  try {
    const { mode } = await api.del(`/api/users/${user.id}`);
    toast(mode === 'archived' ? `${user.full_name} silindi (geçmiş kayıtlardaki adı korundu)` : `${user.full_name} silindi`);
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
  const from = h('input', { class: 'input', type: 'date', title: 'Başlangıç tarihi' });
  const to = h('input', { class: 'input', type: 'date', title: 'Bitiş tarihi' });
  const limit = selectInput([['200', 'Son 200'], ['1000', 'Son 1000'], ['5000', 'Son 5000']], { all: null, value: '1000' });
  const count = h('span', { class: 'small muted' });
  const body = h('div');
  const load = async () => {
    const qs = new URLSearchParams({ kind: kind.value, q: q.value.trim(), date_from: from.value, date_to: to.value, limit: limit.value });
    const d = await api.get(`/api/users/${id}/logs?${qs}`);
    const s = d.summary;
    stats.set([
      { label: 'Toplam kayıt', value: s.all },
      { label: 'Sayfa girişi', value: s.page_views },
      { label: 'İşlem', value: s.actions },
      { label: 'Bugünkü kayıt', value: s.today },
      { label: 'İlk kayıt', value: s.first ? fmtDateTime(s.first).slice(0, 10) : '—', sub: s.first ? fmtDateTime(s.first).slice(11) : '' },
      { label: 'Son kayıt', value: s.last ? fmtDateTime(s.last).slice(11) : '—', sub: s.last ? fmtDateTime(s.last).slice(0, 10) : '' },
      ...s.top_pages.map((t, i) => ({ label: `En çok girilen ${i + 1}.`, value: t.n, sub: t.page })),
    ]);
    count.textContent = d.total > d.rows.length ? `${d.rows.length} / ${d.total} kayıt gösteriliyor` : `${d.total} kayıt`;
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
  let t;
  q.addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 300); });
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
  const from = h('input', { class: 'input', type: 'date' });
  const to = h('input', { class: 'input', type: 'date' });
  const body = h('div');
  const ok = logs.filter(l => l.success);
  stats.set([
    { label: 'Toplam giriş denemesi', value: logs.length },
    { label: 'Başarılı', value: ok.length, tone: 'ok' },
    { label: 'Hatalı şifre', value: logs.length - ok.length, tone: logs.length - ok.length ? 'alert' : '' },
    { label: 'Farklı IP adresi', value: new Set(logs.map(l => l.ip)).size },
    { label: 'Son başarılı giriş', value: ok[0] ? fmtDateTime(ok[0].at).slice(11) : '—', sub: ok[0] ? fmtDateTime(ok[0].at).slice(0, 10) : '' },
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
