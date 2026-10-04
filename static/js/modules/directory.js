// Rehber: sistemde kaynağına bakılmaksızın kayıtlı tüm kişiler (personel, firma kişileri, aile üyeleri) tek rehberde.
// Kişiye tıklayınca detay: bilgiler, evraklar, yüz tanıma kayıtları, görüntülü görüşmeler, toplantılar, telefon notları.
import { api, fileUrl } from '../api.js';
import { avatar, clear, confirmDialog, field, fmtDate, fmtDateTime, h, modal, moduleToolbar, pageHead, segmented, t, toast } from '../ui.js';

const TYPE_BADGE = { user: ['blue', 'Personel'], person: ['', 'Firma kişisi'], family: ['green', 'Aile'], mine: ['yellow', 'Kişilerim'] };
const MINE_SRC = { mail: 'Yazışma', google: 'Google Kişiler', microsoft: 'Outlook Kişileri', manual: 'Elle eklendi' };
// Türkçe Yazım Düzeni (Title Case): her kelimenin ilk harfi büyük, kalanı küçük (İ/ı duyarlı)
const tc = str => (str || '').toLocaleLowerCase('tr').replace(/(^|[\s\-/·.(,])(\p{L})/gu, (m, p, c) => p + c.toLocaleUpperCase('tr'));

let canShare = false;   // Kişilerim'den paylaşılan Rehber'e ekleyebilir mi (Firma Yönetimi yazma yetkisi)

export async function render(view, params, ctx) {
  canShare = (ctx.user.write_modules || ctx.user.modules || []).includes('companies');
  if (params[0] && params[1]) return detail(view, params[0], params[1], ctx);
  return list(view, ctx);
}

async function list(view) {
  let kind = 'all', people = [];
  const q = h('input', { class: 'input', type: 'search', placeholder: 'İsim, telefon, firma ara…', style: { maxWidth: '280px' } });
  const seg = segmented([['all', 'Tümü'], ['user', 'Personel'], ['person', 'Firma kişileri'], ['family', 'Aile'], ['mine', '🔒 Kişilerim']], kind,
    v => { kind = v; load(); });
  const addBtn = h('button', { class: 'btn primary', type: 'button', hidden: true, onclick: () => editMine(null, load) }, '＋ Kişi ekle');
  const grid = h('div', { class: 'gd-groups' });
  const info = h('span', { class: 'small muted' });
  const card = p => p.type === 'mine' ? h('button', { class: 'card gd-card mine', type: 'button', onclick: () => editMine(p, load) },
    avatar({ full_name: tc(p.name) }, 44),
    h('div', { class: 'gd-info' },
      h('b', { title: p.name }, p.name),
      p.subtitle ? h('small', { class: 'muted', title: p.subtitle }, p.subtitle) : null,
      p.phone ? h('small', { class: 'muted' }, p.phone) : null),
    h('span', { class: 'badge yellow', title: 'Yalnızca siz görürsünüz' }, MINE_SRC[p.source] || 'Kişilerim'))
    : h('a', { class: `card gd-card ${TYPE_BADGE[p.type][0] === 'green' ? 'fam' : ''}`, href: `#/rehber/${p.type}/${p.id}` },
    avatar({ full_name: tc(p.name), photo: p.photo }, 44),
    h('div', { class: 'gd-info' },
      h('b', { title: tc(p.name) }, tc(p.name)),
      p.subtitle ? h('small', { class: 'muted', title: tc(p.subtitle) }, tc(p.subtitle)) : null,
      p.phone ? h('small', { class: 'muted' }, p.phone) : null),
    h('span', { class: `badge ${TYPE_BADGE[p.type][0]}` }, TYPE_BADGE[p.type][1]));
  const draw = () => {
    const term = q.value.trim().toLocaleLowerCase('tr');
    const shown = term ? people.filter(p => [p.name, p.subtitle, p.phone, p.email].some(x => (x || '').toLocaleLowerCase('tr').includes(term))) : people;
    info.textContent = t('{n} kişi', { n: shown.length });
    if (!shown.length) return clear(grid, h('div', { class: 'card empty' }, 'Kişi bulunamadı.'));
    const groups = new Map();   // ilk harf → kişiler (alfabetik)
    for (const p of shown) {
      const L = (tc(p.name)[0] || '#').toLocaleUpperCase('tr');
      if (!groups.has(L)) groups.set(L, []);
      groups.get(L).push(p);
    }
    clear(grid, [...groups.entries()].map(([L, list]) => h('div', { class: 'gd-group' },
      h('div', { class: 'gd-letter' }, L),
      h('div', { class: 'gd-grid' }, list.map(card)))));
  };
  const load = async () => {
    clear(grid, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
    addBtn.hidden = kind !== 'mine';
    try {
      if (kind === 'mine') {
        people = (await api.get('/api/my/contacts')).contacts.map(c => ({ ...c, type: 'mine', name: c.name || c.email || c.phone,
          subtitle: [c.name ? c.email : null, c.company, c.title].filter(Boolean).join(' · ') }));
      } else people = (await api.get(`/api/directory?kind=${kind}`)).people;
      draw();
    }
    catch (err) { clear(grid, h('div', { class: 'card empty' }, err.message)); }
  };
  q.addEventListener('input', draw);
  clear(view, pageHead('Rehber', { back: '#/', sub: 'Sistemdeki tüm kişiler · Kişilerim yalnızca size özeldir' }), moduleToolbar(seg, [q, addBtn]), h('p', null, info), grid);
  load();
}

// Kişilerim: mail yazışmaları, Google / Outlook kişileri ve elle eklenenler — yalnızca sahibi görür / düzenler
function editMine(c, done) {
  const inp = (k, ph, type = 'text') => h('input', { class: 'input', type, value: c?.[k] || '', placeholder: ph || '' });
  const f = { name: inp('name'), email: inp('email', 'ad@firma.com', 'email'), phone: inp('phone', '+90 …', 'tel'), company: inp('company'), title: inp('title') };
  const note = h('textarea', { class: 'input', rows: 3 }, c?.note || '');
  modal({
    title: c ? (c.name || c.email) : 'Kişi ekle',
    body: h('div', null,
      c ? h('p', { class: 'small muted' }, t('Kaynak: {s} · yalnızca siz görürsünüz', { s: MINE_SRC[c.source] || c.source })) : h('p', { class: 'small muted' }, 'Bu kişiyi yalnızca siz görürsünüz.'),
      h('div', { class: 'row' }, field('Ad Soyad', f.name), field('E-posta', f.email)),
      h('div', { class: 'row' }, field('Telefon', f.phone), field('Firma', f.company)),
      field('Unvan', f.title), field('Not', note),
      c?.email ? h('div', { class: 'set-actions left' }, h('a', { class: 'btn sm', href: `mailto:${c.email}` }, '✉ E-posta'),
        c.phone ? h('a', { class: 'btn sm', href: `tel:${c.phone}` }, '📞 Ara') : null) : null),
    actions: [c && canShare ? { label: 'Rehbere ekle', onClick: async () => {
      // Google / Outlook / yazışma kişisi → paylaşılan Rehber (firmasız; adresi bir firmaya atanınca o firmanın kişisi olur)
      const r = await api.post('/api/companies/people', { full_name: f.name.value.trim() || f.email.value.trim(), title: f.title.value.trim() || null,
        phone: f.phone.value.trim() || null, emails: f.email.value.trim() ? [f.email.value.trim()] : [],
        note: [note.value.trim(), f.company.value.trim() ? t('Firma (Kişilerim): {c}', { c: f.company.value.trim() }) : ''].filter(Boolean).join('\n') || null });
      toast('Rehbere eklendi', 'success');
      location.hash = `#/companies/rehber/person/${r.id}`;
    } } : null, c ? { label: 'Sil', class: 'danger', onClick: async () => {
      if (!await confirmDialog('Kişiyi sil', 'Bu kişi rehberinizden silinsin mi?', { okLabel: 'Sil', danger: true })) return true;
      await api.del(`/api/my/contacts/${c.id}`); toast('Kişi silindi'); done();
    } } : null, 'spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value.trim() || null]));
      body.note = note.value.trim() || null;
      if (c) await api.put(`/api/my/contacts/${c.id}`, body); else await api.post('/api/my/contacts', body);
      toast('Kaydedildi', 'success'); done();
    } }].filter(Boolean),
  });
}

async function detail(view, type, id, ctx) {
  clear(view, pageHead('Rehber', { back: '#/rehber', sub: 'Kişi detayı' }), h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get(`/api/directory/${type}/${id}`); } catch (err) { return clear(view, pageHead('Rehber', { back: '#/rehber' }), h('div', { class: 'card empty' }, err.message)); }
  const s = d.sections || {};
  const row = (label, val) => val ? h('div', { class: 'gd-row' }, h('span', { class: 'muted' }, label), h('b', null, val)) : null;
  const info = h('section', { class: 'card card-pad' },
    h('div', { class: 'gd-head' }, avatar({ full_name: tc(d.full_name), photo: d.photo }, 64),
      h('div', null, h('h2', { style: { margin: 0 } }, tc(d.full_name)), h('span', { class: `badge ${TYPE_BADGE[type][0]}` }, d.type_label))),
    h('div', { class: 'gd-rows' },
      row('Görev', tc(d.title)), row('Departman', tc(d.department)), row('Firma', tc(d.company)), row('Yakınlık', tc(d.relation)),
      row('Ailesi', d.employee_name && t('{n} ailesi', { n: tc(d.employee_name) })),
      row('Telefon', d.phone), row('E-posta', d.email), row('Doğum', d.birth_date && fmtDate(d.birth_date)),
      row('Roller', (d.roles || []).join(', ')), d.note ? row('Not', d.note) : null));

  const sec = (title, items, rowFn, empty) => h('section', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, `${title}${items?.length ? ` (${items.length})` : ''}`),
    items?.length ? h('div', { class: 'gd-list' }, items.map(rowFn)) : h('div', { class: 'muted small' }, empty));

  const blocks = [info];
  if (s.face) {
    blocks.push(h('section', { class: 'card card-pad' },
      h('h3', { style: { marginTop: 0 } }, t('Yüz Tanıma Kayıtları ({n} görülme)', { n: s.face.sightings || 0 })),
      s.face.last_seen ? h('div', { class: 'small muted' }, t('İlk {a} · Son {b}', { a: fmtDateTime(s.face.first_seen), b: fmtDateTime(s.face.last_seen) })) : null,
      s.face.shots?.length ? h('div', { class: 'fg-recognized' }, s.face.shots.map(x => h('img', {
        src: fileUrl(x.crop, 160), alt: '', loading: 'lazy', title: `${x.camera_name || ''} ${x.at ? fmtDateTime(x.at) : ''}`,
        onclick: () => x.frame && modal({ title: `${x.camera_name || ''} · ${fmtDateTime(x.at)}`, wide: true, body: h('img', { class: 'fg-frame', src: fileUrl(x.frame), alt: '' }), actions: [{ label: 'Kapat' }] }) })))
        : h('div', { class: 'muted small' }, 'Kamerada tanınan görülme yok.')));
  }
  if (s.documents) blocks.push(sec('Evraklar', s.documents, dd => h('a', { class: 'gd-li', href: `#/documents/${dd.id}` },
    h('b', null, dd.title || `#${dd.id}`), h('small', { class: 'muted' }, [dd.kind, dd.created_at && fmtDate(dd.created_at)].filter(Boolean).join(' · '))), 'Bağlı evrak yok.'));
  if (s.meetings) blocks.push(sec('Toplantılar', s.meetings, mm => h('div', { class: 'gd-li' },
    h('b', null, mm.title), h('small', { class: 'muted' }, [mm.starts_at && fmtDateTime(mm.starts_at), mm.company, mm.location].filter(Boolean).join(' · '))), 'Toplantı yok.'));
  if (s.calls) blocks.push(sec('Görüntülü Görüşmeler', s.calls, cc => h('div', { class: 'gd-li' },
    h('b', null, cc.title || (cc.kind === 'grup' ? 'Grup görüşmesi' : 'Görüşme')),
    h('small', { class: 'muted' }, [cc.started_at && fmtDateTime(cc.started_at), cc.status, cc.seconds && t('{n} sn', { n: Math.round(cc.seconds) })].filter(Boolean).join(' · '))), 'Görüşme yok.'));
  if (s.phone_calls) blocks.push(sec('Telefon Notları', s.phone_calls, pc => h('div', { class: 'gd-li' },
    h('b', null, pc.caller_name), h('small', { class: 'muted' }, [pc.subject, pc.created_at && fmtDateTime(pc.created_at)].filter(Boolean).join(' · '))), 'Telefon notu yok.'));

  clear(view, pageHead(tc(d.full_name), { back: '#/rehber', sub: d.type_label }), h('div', { class: 'gd-detail' }, ...blocks));
}
