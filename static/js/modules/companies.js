// Firma Yönetimi: firmalar, logoları, firmada çalışan / ilişkili kişiler ve firmanın evrakları.
import { setListExport } from '../listexport.js';
import { api, fileUrl } from '../api.js';
import { icons } from '../icons.js';
import {
  clear, confirmDialog, dateTimeInput, field, fmtDate, fmtDateTime, h, matches, modal, pageHead, peoplePicker, pref, segmented,
  selectInput, setPref, statStrip, svgIcon, toast, toastError,
} from '../ui.js';
import { calendarPanel, docList, notesPanel, tabView } from './crm.js';
import { crmNav } from './crmhub.js';
import { openUpload } from './documents.js';

// Aynı ekranlar Satın Alma › Tedarikçi Yönetimi'nde tedarikçiler için kullanılır (adres kökü, API kapsamı ve başlık değişir)
let BASE = '#/companies', SUP = false, TITLE = 'Firma Yönetimi';
const Q = () => (SUP ? '?supplier=1' : '');

export function renderSuppliers(view, params, ctx) {
  BASE = '#/purchasing/suppliers'; SUP = true; TITLE = 'Tedarikçi Yönetimi';
  return route(view, params, ctx);
}

let canLinkUsers = false;   // Kullanıcı Yönetimi yetkisi: dış firma kişisine sistem kullanıcısı bağlayabilir
export async function render(view, params, ctx) {
  canLinkUsers = ctx.user.modules.includes('users');
  BASE = '#/companies'; SUP = false; TITLE = 'Firma Yönetimi';
  return route(view, params, ctx);
}

async function route(view, params, ctx) {
  // #/companies/rehber[/person|user/<id>[/<sekme>]] · #/companies/<id>[/<sekme>]
  if (params[0] === 'rehber') {
    if (['person', 'user'].includes(params[1]) && params[2]) return renderContact(view, ctx, params[1], Number(params[2]), params[3]);
    return renderDirectory(view, ctx);
  }
  if (params[0]) return renderDetail(view, Number(params[0]), ctx, params[1]);
  return renderList(view, ctx);
}

// Firmalar / Rehber görünüm seçici (adres çubuğunda: #/companies ve #/companies/rehber)
const viewSwitch = current => segmented([['companies', SUP ? 'Tedarikçiler' : 'Firmalar'], ['rehber', 'Rehber']], current,
  v => { location.hash = v === 'rehber' ? `${BASE}/rehber` : BASE; });

const initials = name => name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toLocaleUpperCase('tr');
export const logoOf = (c, cls = 'co-logo') => (c.logo ? h('img', { class: cls, src: fileUrl(c.logo, 256), alt: c.name })
  : h('span', { class: `${cls} co-initials` }, initials(c.name)));

// ---------- Firma formu (yeni / düzenle)
function companyForm(c = {}, done) {
  const inp = (k, ph = '') => h('input', { class: 'input', value: c[k] || '', placeholder: ph });
  const f = {
    name: inp('name'), tax_office: inp('tax_office'), tax_no: inp('tax_no'), phone: inp('phone'), email: inp('email'),
    website: inp('website', 'https://…'), address: h('textarea', { class: 'input', rows: 2 }, c.address || ''),
    note: h('textarea', { class: 'input', rows: 2 }, c.note || ''),
    active: h('input', { type: 'checkbox', checked: c.active !== 0 }),
  };
  const logo = h('input', { class: 'input', type: 'file', accept: 'image/*', style: { height: 'auto', padding: '6px' } });
  modal({
    title: c.id ? (SUP ? 'Tedarikçiyi düzenle' : 'Firmayı düzenle') : SUP ? 'Yeni Tedarikçi' : 'Yeni Firma',
    wide: true,
    body: h('div', null,
      field('Firma adı', f.name),
      h('div', { class: 'row' }, field('Vergi dairesi', f.tax_office), field('Vergi no', f.tax_no)),
      h('div', { class: 'row' }, field('Telefon', f.phone), field('E-posta', f.email), field('Web sitesi', f.website)),
      c.id ? null : field('Merkez adresi', f.address, 'İsteğe bağlı; diğer adresler firma detayında eklenir.'),
      field('Not', f.note),
      field('Logo', logo, c.logo ? 'Yeni logo seçerseniz eskisinin yerine geçer.' : 'PNG, JPG, SVG'),
      h('label', { class: 'check' }, f.active, 'Aktif (evraklarda seçilebilir)')),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, k === 'active' ? el.checked : el.value.trim() || null]));
          if (!body.name) throw new Error('Firma adı zorunlu');
          const id = c.id || (await api.post(`/api/companies${Q()}`, body)).id;
          if (c.id) await api.put(`/api/companies/${c.id}`, body);
          if (logo.files[0]) {
            const fd = new FormData();
            fd.append('file', logo.files[0]);
            await api.post(`/api/companies/${id}/logo`, fd);
          }
          toast('Firma kaydedildi');
          done?.(id);
        },
      },
    ],
  });
}

// ---------- Liste
async function renderList(view, ctx) {
  let companies = await api.get(`/api/companies${Q()}`);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Firma, vergi no, telefon ara…', style: { width: '240px' } });
  const act = selectInput([['1', 'Aktif'], ['0', 'Pasif']], { all: 'Aktif ve pasif' });
  const stats = statStrip();
  const grid = h('div');
  const draw = () => {
    stats.set([
      { label: SUP ? 'Tedarikçi' : 'Firma', value: companies.length },
      { label: 'Aktif', value: companies.filter(c => c.active).length, tone: 'ok' },
      { label: 'Kişi', value: companies.reduce((a, c) => a + c.people_count, 0) },
      { label: 'Evrak', value: companies.reduce((a, c) => a + c.document_count, 0), sub: 'görebildiğiniz' },
    ]);
    const list = companies.filter(c => (!act.value || String(c.active) === act.value)
      && matches(q.value, c.name, c.tax_no, c.phone, c.email, c.tax_office));
    setListExport(() => ({ columns: ['Firma', 'Vergi dairesi', 'Vergi no', 'Telefon', 'E-posta', 'Web', 'Kişi', 'Evrak', 'Durum'],
      rows: list.map(c => [c.name, c.tax_office || '', c.tax_no || '', c.phone || '', c.email || '', c.website || '', c.people_count, c.document_count, c.active ? 'Aktif' : 'Pasif']) }));
    clear(grid, list.length ? h('div', { class: 'co-grid' }, list.map(c => h('a', { class: `card co-card ${c.active ? '' : 'inactive'}`, href: `${BASE}/${c.id}` },
      logoOf(c),
      h('div', { class: 'grow' },
        h('b', null, c.name), c.active ? null : h('span', { class: 'badge gray', style: { marginLeft: '6px' } }, 'Pasif'),
        h('div', { class: 'small muted' }, [c.city, c.tax_no ? `VN ${c.tax_no}` : null, c.phone].filter(Boolean).join(' · ') || '—'),
        h('div', { class: 'co-counts' }, h('span', null, `${c.address_count} adres`), h('span', null, `${c.people_count} kişi`),
          h('span', null, `${c.document_count} evrak`))))))
      : h('div', { class: 'card empty' }, companies.length ? 'Filtreye uyan firma yok' : 'Henüz firma eklenmedi'));
  };
  q.addEventListener('input', draw);
  act.addEventListener('change', draw);
  const reload = async () => { companies = await api.get(`/api/companies${Q()}`); draw(); };
  clear(view,
    pageHead(TITLE, { back: '#/', sub: 'Firmalar, firma kişileri ve firmaların evrakları',
      right: h('div', { class: 'head-right' }, h('button', { class: 'btn primary', onclick: () => companyForm({}, id => { location.hash = `${BASE}/${id}`; }) },
        svgIcon(icons.plus), SUP ? 'Yeni Tedarikçi' : 'Yeni Firma'), viewSwitch('companies')) }),
    SUP ? null : crmNav('companies', ctx),
    stats,
    h('div', { class: 'filters' }, q, act),
    grid);
  draw();
  void reload;
}

// ---------- Rehber: firma kişileri ve sistem kullanıcıları (kart / liste, alfabetik)
const trUpper = s => (s || '').toLocaleUpperCase('tr');
const telHref = phone => `tel:${phone.replace(/[^\d+]/g, '')}`;

function vcard(p) {
  // Telefona / e-posta programına kaydetmek için vCard (.vcf)
  const esc = v => String(v || '').replace(/([\\,;])/g, '\\$1').replace(/\n/g, '\\n');
  const parts = p.full_name.trim().split(/\s+/);
  const last = parts.length > 1 ? parts.pop() : '';
  const lines = ['BEGIN:VCARD', 'VERSION:3.0', `N:${esc(last)};${esc(parts.join(' '))};;;`, `FN:${esc(p.full_name)}`,
    `ORG:${esc(p.company_name)}`, p.title ? `TITLE:${esc(p.title)}` : null, p.phone ? `TEL;TYPE=WORK,VOICE:${esc(p.phone)}` : null,
    p.email ? `EMAIL;TYPE=WORK:${esc(p.email)}` : null, p.note ? `NOTE:${esc(p.note)}` : null, 'END:VCARD'].filter(Boolean);
  const a = h('a', { href: URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/vcard' })),
    download: `${p.full_name}.vcf` });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// Rehber kaydı: firma kişisi (person) ya da sistem kullanıcısı (user) tek biçimde
const contactOf = (kind, x, ctx) => (kind === 'person'
  ? { kind, id: x.id, full_name: x.full_name, title: x.title, phone: x.phone, email: x.email, note: x.note,
    company_id: x.company_id, company_name: x.company_name, company_logo: x.company_logo, href: `${BASE}/rehber/person/${x.id}` }
  : { kind, id: x.id, full_name: x.full_name, title: (x.roles || []).join(', '), phone: x.phone, email: x.email, photo: x.photo,
    company_name: ctx.meta?.company || 'Personel', href: `${BASE}/rehber/user/${x.id}` });

const contactAvatar = (c, cls = 'dir-avatar') => (c.photo ? h('img', { class: `${cls} photo`, src: fileUrl(c.photo, 256), alt: '', loading: 'lazy' })
  : h('span', { class: `${cls} ${c.kind}` }, initials(c.full_name)));

const stop = e => e.stopPropagation();
const contactLinks = c => [
  c.phone ? h('a', { href: telHref(c.phone), class: 'dir-link', onclick: stop }, svgIcon(icons.phone), c.phone) : null,
  c.email ? h('a', { href: `mailto:${c.email}`, class: 'dir-link', onclick: stop }, svgIcon(icons.mail), c.email) : null,
];
const orgLine = c => (c.kind === 'person'
  ? h('span', { class: 'dir-company' }, logoOf({ name: c.company_name, logo: c.company_logo }, 'co-logo xs'), c.company_name)
  : h('span', { class: 'dir-company' }, h('span', { class: 'dir-kind' }, 'Kullanıcı'), h('span', { class: 'dir-org' }, c.company_name)));

async function renderDirectory(view, ctx) {
  let data = await api.get(`/api/crm/contacts${Q()}`);
  const companies = [...new Map(data.people.map(p => [p.company_id, p.company_name])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], 'tr'));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad, ünvan, firma, telefon, e-posta ara…', style: { width: '260px' } });
  const kindSel = selectInput([['person', 'Firma kişileri'], ['user', 'Kullanıcılar']], { all: 'Tüm kişiler' });
  const co = selectInput(companies.map(([id, name]) => [String(id), name]), { all: 'Tüm firmalar' });
  let mode = pref('rehber.view', 'cards');
  const stats = statStrip();
  const body = h('div');
  const reload = async () => { data = await api.get(`/api/crm/contacts${Q()}`); draw(); };
  const addPerson = () => {
    const pick = selectInput(companies.map(([id, name]) => [String(id), name]), { all: null });
    if (co.value) pick.value = co.value;
    modal({
      title: 'Rehbere kişi ekle',
      body: h('div', null, field('Firma', pick), h('div', { class: 'small muted' }, 'Kişi seçilen firmanın kişilerine eklenir. Kullanıcılar Kullanıcı Yönetimi\'nden eklenir.')),
      actions: [{ label: 'Vazgeç' }, { label: 'Devam', class: 'primary', onClick: () => { setTimeout(() => personForm(Number(pick.value), {}, reload)); } }],
    });
  };
  const draw = () => {
    const all = [...data.people.map(p => contactOf('person', p, ctx)), ...data.users.map(u => contactOf('user', u, ctx))];
    co.hidden = kindSel.value === 'user';
    stats.set([
      { label: 'Kişi', value: all.length },
      { label: 'Firma kişisi', value: data.people.length },
      { label: 'Kullanıcı', value: data.users.length },
      { label: 'Telefonu olan', value: all.filter(c => c.phone).length },
    ]);
    const list = all.filter(c => (!kindSel.value || c.kind === kindSel.value)
      && (!co.value || kindSel.value === 'user' || (c.kind === 'person' && String(c.company_id) === co.value))
      && matches(q.value, c.full_name, c.title, c.company_name, c.phone, c.email, c.note))
      .sort((a, b) => a.full_name.localeCompare(b.full_name, 'tr'));
    setListExport(() => ({ columns: ['Ad Soyad', 'Tür', 'Ünvan', 'Firma', 'Telefon', 'E-posta', 'Not'],
      rows: list.map(c => [c.full_name, c.kind === 'user' ? 'Kullanıcı' : 'Firma kişisi', c.title || '', c.company_name || '', c.phone || '', c.email || '', c.note || '']) }));
    const groups = new Map();
    for (const c of list) {
      const letter = trUpper(c.full_name.trim()[0]) || '#';
      if (!groups.has(letter)) groups.set(letter, []);
      groups.get(letter).push(c);
    }
    const card = c => h('a', { class: `card dir-tile ${c.kind}`, href: c.href },
      contactAvatar(c, 'dir-avatar lg'),
      h('b', { class: 'dir-name' }, c.full_name),
      c.title ? h('div', { class: 'small muted dir-title' }, c.title) : null,
      orgLine(c),
      h('div', { class: 'dir-tile-links' }, contactLinks(c)));
    const row = c => h('a', { class: 'dir-row', href: c.href },
      contactAvatar(c),
      h('div', { class: 'dir-main' }, h('b', null, c.full_name), c.title ? h('div', { class: 'small muted' }, c.title) : null, orgLine(c)),
      h('div', { class: 'dir-contact' }, contactLinks(c), !c.phone && !c.email ? h('span', { class: 'small muted' }, 'İletişim bilgisi yok') : null),
      h('div', { class: 'dir-actions' },
        h('button', { class: 'btn sm', title: 'Telefona / e-postaya kaydet (vCard)', onclick: e => { e.preventDefault(); stop(e); vcard(c); } }, '.vcf')));
    clear(body, list.length ? h('div', { class: 'dir-wrap' },
      h('nav', { class: 'dir-index', 'aria-label': 'Harf' }, [...groups.keys()].map(l =>
        h('a', { href: '#', onclick: e => { e.preventDefault(); view.querySelector(`[data-letter="${l}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, l))),
      h('div', { class: 'dir-list' }, [...groups].map(([letter, rows]) => h('section', { class: 'dir-group', 'data-letter': letter },
        h('h2', { class: 'dir-letter' }, letter),
        mode === 'cards' ? h('div', { class: 'dir-tiles' }, rows.map(card)) : h('div', { class: 'card dir-card' }, rows.map(row))))))
      : h('div', { class: 'card empty' }, 'Aramaya uyan kişi yok'));
  };
  q.addEventListener('input', draw);
  co.addEventListener('change', draw);
  kindSel.addEventListener('change', draw);
  const modeSeg = segmented([['cards', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('rehber.view', v); draw(); });
  clear(view,
    pageHead(TITLE, { back: '#/', sub: 'Rehber: firma kişileri ve kullanıcılar',
      right: h('div', { class: 'head-right' }, h('button', { class: 'btn primary', onclick: addPerson }, svgIcon(icons.plus), 'Kişi Ekle'),
        viewSwitch('rehber')) }),
    SUP ? null : crmNav('companies', ctx),
    stats,
    h('div', { class: 'filters' }, q, kindSel, co, h('span', { class: 'spacer' }), modeSeg),
    body);
  draw();
}

// ---------- Rehber detayı: kişi (firma kişisi) ya da kullanıcı; sekmeler: Evrak, Notlar, Toplantılar, Takvim
async function renderContact(view, ctx, kind, id, tab) {
  const x = await api.get(`/api/crm/${kind}/${id}`);
  const c = contactOf(kind, x, ctx);
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  let company = null;   // kişinin firması (toplantı formu için gerekir)
  const getCompany = async () => (company ||= await api.get(`/api/companies/${x.company_id}`));
  const meetings = async () => {
    if (kind === 'person') {
      const co = await getCompany();
      const cm = { ...co, meetings: x.meetings };
      return h('div', null,
        h('div', { class: 'co-section-head' }, h('h2', null, `${c.full_name} katıldığı toplantılar`),
          h('button', { class: 'btn sm primary', onclick: () => meetingForm(co, { people: [{ id }] }, reload) }, svgIcon(icons.plus), 'Toplantı Ekle')),
        meetingList(cm, reload));
    }
    return x.meetings.length ? h('div', { class: 'meet-list' }, x.meetings.map(m => h('a', { class: 'meet-item link', href: `${BASE}/${m.company_id}/meetings` },
      h('div', { class: 'meet-head' }, h('div', { class: 'meet-when' }, h('b', null, fmtDateTime(m.meeting_at))),
        h('div', { class: 'grow' }, h('b', null, m.subject), h('span', { class: 'small muted' }, ` · ${m.company_name}`))),
      h('div', { class: 'meet-sub' }, h('span', null, 'Karşı taraf: '), m.people.map(p => p.full_name).join(', ') || '—'),
      h('div', { class: 'meet-sub' }, h('span', null, 'Bizden: '), m.users.map(u => u.full_name).join(', ') || '—'))))
      : h('div', { class: 'empty small' }, 'Katıldığı toplantı yok');
  };
  const docs = () => h('div', null,
    kind === 'person' && ctx.user.modules.includes('documents') ? h('div', { class: 'co-section-head' }, h('h2', null, 'Evraklar'),
      h('button', { class: 'btn sm primary', onclick: () => openUpload(ctx, { company_ids: [x.company_id], person_ids: [id] }, reload) },
        svgIcon(icons.upload), 'Evrak Yükle')) : null,
    docList(x.documents, kind === 'person' ? 'Bu kişiye bağlı (görebildiğiniz) evrak yok' : 'Yüklediği ya da imzaladığı (görebildiğiniz) evrak yok'));
  const kv = (k, v) => (v ? [h('dt', null, k), h('dd', null, v)] : null);
  clear(view,
    pageHead(c.full_name, { back: `${BASE}/rehber`, sub: kind === 'person' ? `Rehber · ${c.company_name}` : 'Rehber · Kullanıcı',
      right: h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap' } },
        h('button', { class: 'btn', onclick: () => vcard(c) }, 'Kaydet .vcf'),
        kind === 'person' ? h('button', { class: 'btn', onclick: () => personForm(x.company_id, x, reload) }, 'Düzenle') : null) }),
    h('div', { class: 'card card-pad contact-head' },
      contactAvatar(c, 'dir-avatar xl'),
      h('div', { class: 'grow' },
        h('h2', null, c.full_name),
        c.title ? h('div', { class: 'muted' }, c.title) : null,
        kind === 'person' ? h('a', { class: 'dir-company', href: `${BASE}/${x.company_id}` },
          logoOf({ name: x.company_name, logo: x.company_logo }, 'co-logo xs'), x.company_name) : orgLine(c)),
      h('dl', { class: 'kv contact-kv' },
        kv('Telefon', c.phone ? h('a', { href: telHref(c.phone) }, c.phone) : null),
        kv('E-posta', c.email ? h('a', { href: `mailto:${c.email}` }, c.email) : null),
        kv('Not', c.note))),
    tabView([
      { key: 'documents', label: 'Evrak Yönetimi', count: x.documents.length, render: docs },
      { key: 'notes', label: 'Notlar', render: () => notesPanel(kind, id, ctx) },
      { key: 'meetings', label: 'Toplantı Yönetimi', count: x.meetings.length, render: meetings },
      { key: 'calendar', label: 'Takvim', render: () => calendarPanel(kind, id, ctx) },
    ], tab || pref('contact.tab', 'documents'), k => setPref('contact.tab', k)));
}

// ---------- Kişi formu
function personForm(cid, p = {}, done) {
  const inp = k => h('input', { class: 'input', value: p[k] || '' });
  const f = { full_name: inp('full_name'), title: inp('title'), phone: inp('phone'), email: inp('email'),
    note: h('textarea', { class: 'input', rows: 2 }, p.note || '') };
  // Dış firma personeli (ör. kiralık güvenlik): sisteme giriş yapacaksa kullanıcı hesabı bu kişiye bağlanır; İK'da personel açılmaz
  const userSel = canLinkUsers ? h('select', { class: 'input' }, h('option', { value: '' }, '— Sistem kullanıcısı yok —'),
    p.user_id ? h('option', { value: p.user_id, selected: true }, p.user_name || `#${p.user_id}`) : null) : null;
  if (userSel) api.get('/api/users').then(list => {
    for (const u of list.filter(u => u.id !== p.user_id && (!u.external || u.external.person_id === p.id))) {
      userSel.append(h('option', { value: u.id }, `${u.full_name} (${u.username})${u.roles?.length ? ` · ${u.roles.join(', ')}` : ''}`));
    }
  }).catch(() => {});
  modal({
    title: p.id ? 'Kişiyi düzenle' : 'Kişi ekle',
    body: h('div', null, field('Ad soyad', f.full_name), field('Görevi / ünvanı', f.title),
      h('div', { class: 'row' }, field('Telefon', f.phone), field('E-posta', f.email)), field('Not', f.note),
      userSel ? field('Sistem kullanıcısı', userSel,
        'Firmanın bize çalışan personeli (ör. kiralık güvenlik) sisteme giriş yapacaksa hesabını seçin. Bağlanan kullanıcı İK’da personel olarak görünmez; firma başka birini gönderirse yeni kişiyi ekleyip hesabı ona bağlayın.') : null),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value.trim() || null]));
          if (userSel) { body.link_user = true; body.user_id = userSel.value ? Number(userSel.value) : null; }
          if (!body.full_name) throw new Error('Ad soyad zorunlu');
          if (p.id) await api.put(`/api/companies/people/${p.id}`, body); else await api.post(`/api/companies/${cid}/people`, body);
          toast('Kişi kaydedildi');
          done?.();
        },
      },
    ],
  });
}

// ---------- Adresler
const addrText = a => [a.address, a.city].filter(Boolean).join(', ');

function addressForm(cid, a = {}, done) {
  const label = h('input', { class: 'input', value: a.label || '', placeholder: 'Ör. Merkez, Fabrika, Ankara Şube' });
  const address = h('textarea', { class: 'input', rows: 3 }, a.address || '');
  const city = h('input', { class: 'input', value: a.city || '', placeholder: 'Ör. Ankara / Çankaya' });
  const note = h('input', { class: 'input', value: a.note || '', placeholder: 'Ör. giriş kapısı, kat, yol tarifi' });
  modal({
    title: a.id ? 'Adresi düzenle' : 'Adres ekle',
    body: h('div', null, h('div', { class: 'row' }, field('Adres adı', label), field('İl / ilçe', city)),
      field('Açık adres', address), field('Not', note)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = { label: label.value.trim(), address: address.value.trim(), city: city.value.trim() || null, note: note.value.trim() || null };
          if (!body.label || !body.address) throw new Error('Adres adı ve açık adres zorunlu');
          if (a.id) await api.put(`/api/companies/addresses/${a.id}`, body); else await api.post(`/api/companies/${cid}/addresses`, body);
          toast('Adres kaydedildi');
          done?.();
        },
      },
    ],
  });
}

function addressList(c, reload) {
  if (!c.addresses.length) return h('div', { class: 'empty small' }, 'Henüz adres eklenmedi');
  return h('div', { class: 'addr-list' }, c.addresses.map(a => h('div', { class: 'addr-item' },
    h('div', { class: 'grow' }, h('b', null, a.label), h('div', null, addrText(a)),
      a.note ? h('div', { class: 'small muted' }, a.note) : null),
    h('a', { class: 'btn sm ghost', target: '_blank', rel: 'noopener',
      href: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addrText(a))}` }, 'Harita'),
    h('button', { class: 'btn sm', onclick: () => addressForm(c.id, a, reload) }, 'Düzenle'),
    h('button', { class: 'btn sm ghost', onclick: async () => {
      if (!await confirmDialog('Adresi sil', `${a.label} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
      try { await api.del(`/api/companies/addresses/${a.id}`); toast('Adres silindi'); reload(); } catch (err) { toastError(err); }
    } }, 'Sil'))));
}

// ---------- Toplantı formu: karşı taraftan (firma kişileri) ve bizden (sistem kullanıcıları) katılanlar
async function meetingForm(c, m = {}, done) {
  const users = await api.get('/api/people');
  const subject = h('input', { class: 'input', value: m.subject || '', placeholder: 'Ör. Tedarik görüşmesi' });
  const when = dateTimeInput({ value: m.meeting_at });
  const address = h('select', { class: 'input' }, h('option', { value: '' }, c.addresses.length ? 'Adres seçilmedi' : 'Firmaya adres eklenmemiş'),
    c.addresses.map(a => h('option', { value: a.id, selected: a.id === m.address_id }, `${a.label} — ${addrText(a)}`)));
  const location = h('input', { class: 'input', value: m.location || '', placeholder: 'Ör. toplantı salonu, çevrim içi (Teams)' });
  const theirs = peoplePicker(c.people, { empty: 'Firmaya henüz kişi eklenmedi (Kişi Ekle)', selected: (m.people || []).map(p => p.id),
    sub: p => p.title || '' });
  const ours = peoplePicker(users, { selected: (m.users || []).map(u => u.id) });
  const others = h('input', { class: 'input', value: m.other_attendees || '', placeholder: 'Listede olmayan katılımcılar (isteğe bağlı)' });
  const notes = h('textarea', { class: 'input', rows: 5, placeholder: 'Görüşülen konular, kararlar, yapılacaklar…' }, m.notes || '');
  modal({
    title: m.id ? 'Toplantıyı düzenle' : `${c.name} — Yeni toplantı`,
    wide: true,
    body: h('div', null,
      field('Konu', subject),
      h('div', { class: 'row' }, field('Tarih ve saat', when), field('Adres', address)),
      field('Yer / açıklama', location, 'Adres dışında yer bilgisi ya da çevrim içi toplantı'),
      h('div', { class: 'row meet-sides' },
        field(`Karşı taraftan katılanlar (${c.name})`, theirs),
        field('Bizden katılanlar', ours)),
      field('Diğer katılımcılar', others),
      field('Toplantı notları / tutanak', notes)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          if (!subject.value.trim()) throw new Error('Toplantı konusu zorunlu');
          const body = { subject: subject.value.trim(), meeting_at: when.getValue(), address_id: address.value ? Number(address.value) : null,
            location: location.value.trim() || null,
            notes: notes.value.trim() || null, other_attendees: others.value.trim() || null,
            person_ids: theirs.getIds(), user_ids: ours.getIds() };
          if (m.id) await api.put(`/api/companies/meetings/${m.id}`, body); else await api.post(`/api/companies/${c.id}/meetings`, body);
          toast('Toplantı kaydedildi');
          done?.();
        },
      },
    ],
  });
}

function meetingList(c, reload) {
  if (!c.meetings.length) return h('div', { class: 'empty small' }, 'Henüz toplantı girilmedi');
  return h('div', { class: 'meet-list' }, c.meetings.map(m => {
    const notes = m.notes ? h('div', { class: 'meet-notes collapsed' }, m.notes) : null;
    notes?.addEventListener('click', () => notes.classList.toggle('collapsed'));
    return h('div', { class: 'meet-item' },
      h('div', { class: 'meet-head' },
        h('div', { class: 'meet-when' }, h('b', null, fmtDateTime(m.meeting_at))),
        h('div', { class: 'grow' }, h('b', null, m.subject), m.location ? h('span', { class: 'small muted' }, ` · ${m.location}`) : null),
        h('button', { class: 'btn sm', onclick: () => meetingForm(c, m, reload) }, 'Düzenle'),
        h('button', { class: 'btn sm ghost', onclick: async () => {
          if (!await confirmDialog('Toplantıyı sil', `${m.subject} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/companies/meetings/${m.id}`); toast('Toplantı silindi'); reload(); } catch (err) { toastError(err); }
        } }, 'Sil')),
      m.address_id ? h('div', { class: 'meet-sub' }, h('span', null, 'Adres: '),
        `${m.address_label} — ${addrText({ address: m.address_text, city: m.address_city })}`) : null,
      h('div', { class: 'meet-sub' }, h('span', null, 'Karşı taraf: '),
        m.people.length ? m.people.map(p => `${p.full_name}${p.title ? ` (${p.title})` : ''}`).join(', ') : '—'),
      h('div', { class: 'meet-sub' }, h('span', null, 'Bizden: '), m.users.length ? m.users.map(u => u.full_name).join(', ') : '—'),
      m.other_attendees ? h('div', { class: 'meet-sub' }, h('span', null, 'Diğer: '), m.other_attendees) : null,
      notes);
  }));
}

// ---------- Detay: üstte firma bilgileri, altta sekmeler (Kişiler, Adresler, Evrak, Notlar, Toplantılar, Takvim)
async function renderDetail(view, id, ctx, tab) {
  const c = await api.get(`/api/companies/${id}`);
  const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
  const remove = async () => {
    if (!await confirmDialog('Firmayı sil', `${c.name} silinsin mi? Kişileri, notları ve takvim kayıtları da silinir.`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/companies/${id}`); toast(SUP ? 'Tedarikçi silindi' : 'Firma silindi'); location.hash = BASE; } catch (err) { toastError(err); }
  };
  const kv = (k, v) => (v ? [h('dt', null, k), h('dd', null, v)] : null);
  const people = () => h('div', null,
    h('div', { class: 'co-section-head' }, h('h2', null, `Kişiler (${c.people.length})`),
      h('button', { class: 'btn sm primary', onclick: () => personForm(id, {}, reload) }, svgIcon(icons.plus), 'Kişi Ekle')),
    c.people.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Ad soyad', 'Görevi', 'Telefon', 'E-posta', ''].map(t => h('th', null, t)))),
      h('tbody', null, c.people.map(p => h('tr', null,
        h('td', null, h('a', { href: `${BASE}/rehber/person/${p.id}` }, h('b', null, p.full_name)),
          p.user_id ? h('span', { class: `badge ${p.user_active ? 'blue' : 'gray'}`, style: { marginLeft: '6px' }, title: `Sistem hesabı: ${p.user_username || ''}` }, 'Sistem kullanıcısı') : null,
          p.note ? h('div', { class: 'small muted' }, p.note) : null),
        h('td', null, p.title || '—'),
        h('td', null, p.phone ? h('a', { href: `tel:${p.phone}` }, p.phone) : '—'),
        h('td', null, p.email ? h('a', { href: `mailto:${p.email}` }, p.email) : '—'),
        h('td', { class: 'num', style: { whiteSpace: 'nowrap' } },
          h('button', { class: 'btn sm', onclick: () => personForm(id, p, reload) }, 'Düzenle'), ' ',
          h('button', { class: 'btn sm ghost', onclick: async () => {
            if (!await confirmDialog('Kişiyi sil', `${p.full_name} silinsin mi? Notları ve takvim kayıtları da silinir.`, { okLabel: 'Sil', danger: true })) return;
            try { await api.del(`/api/companies/people/${p.id}`); toast('Kişi silindi'); reload(); } catch (err) { toastError(err); }
          } }, 'Sil')))))))
      : h('div', { class: 'empty small' }, 'Henüz kişi eklenmedi'));
  const addresses = () => h('div', null,
    h('div', { class: 'co-section-head' }, h('h2', null, `Adresler (${c.addresses.length})`),
      h('button', { class: 'btn sm primary', onclick: () => addressForm(id, {}, reload) }, svgIcon(icons.plus), 'Adres Ekle')),
    addressList(c, reload));
  const docs = () => h('div', null,
    h('div', { class: 'co-section-head' }, h('h2', null, `Evraklar (${c.documents.length})`),
      ctx.user.modules.includes('documents')
        ? h('button', { class: 'btn sm primary', onclick: () => openUpload(ctx, { company_ids: [id] }, reload) }, svgIcon(icons.upload), 'Evrak Yükle')
        : null),
    docList(c.documents, 'Bu firmaya bağlı (görebildiğiniz) evrak yok'));
  const meetings = () => h('div', null,
    h('div', { class: 'co-section-head' }, h('h2', null, `Toplantılar (${c.meetings.length})`),
      h('button', { class: 'btn sm primary', onclick: () => meetingForm(c, {}, reload) }, svgIcon(icons.plus), 'Toplantı Ekle')),
    meetingList(c, reload));
  clear(view,
    pageHead(c.name, { back: BASE, sub: SUP ? (c.active ? 'Tedarikçi' : 'Pasif tedarikçi') : c.active ? 'Firma' : 'Pasif firma',
      right: h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap' } },
        h('button', { class: 'btn', onclick: () => companyForm(c, reload) }, 'Düzenle'),
        h('button', { class: 'btn danger', onclick: remove }, 'Sil')) }),
    h('div', { class: 'card card-pad co-top' },
      h('div', { class: 'co-head' }, logoOf(c, 'co-logo big'), h('div', null, h('h2', null, c.name),
        h('div', { class: 'small muted' }, [c.tax_office, c.tax_no ? `VN ${c.tax_no}` : null].filter(Boolean).join(' · ')))),
      h('dl', { class: 'kv co-top-kv' },
        kv('Telefon', c.phone ? h('a', { href: `tel:${c.phone}` }, c.phone) : null),
        kv('E-posta', c.email ? h('a', { href: `mailto:${c.email}` }, c.email) : null),
        kv('Web', c.website ? h('a', { href: c.website, target: '_blank', rel: 'noopener' }, c.website) : null),
        kv('Merkez', c.addresses[0] ? `${c.addresses[0].label} — ${addrText(c.addresses[0])}` : null),
        kv('Not', c.note))),
    tabView([
      { key: 'people', label: 'Kişiler', count: c.people.length, render: people },
      { key: 'addresses', label: 'Adresler', count: c.addresses.length, render: addresses },
      { key: 'documents', label: 'Evrak Yönetimi', count: c.documents.length, render: docs },
      { key: 'notes', label: 'Notlar', render: () => notesPanel('company', id, ctx) },
      { key: 'meetings', label: 'Toplantı Yönetimi', count: c.meetings.length, render: meetings },
      { key: 'calendar', label: 'Takvim', render: () => calendarPanel('company', id, ctx) },
    ], tab || pref('company.tab', 'people'), k => setPref('company.tab', k)));
}
