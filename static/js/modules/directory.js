// Rehber: sistemde kaynağına bakılmaksızın kayıtlı tüm kişiler (personel, firma kişileri, aile üyeleri) tek rehberde.
// Kişiye tıklayınca detay: bilgiler, evraklar, yüz tanıma kayıtları, görüntülü görüşmeler, toplantılar, telefon notları.
import { api, fileUrl } from '../api.js';
import { avatar, clear, fmtDate, fmtDateTime, h, modal, moduleToolbar, pageHead, segmented, t } from '../ui.js';

const TYPE_BADGE = { user: ['blue', 'Personel'], person: ['', 'Firma kişisi'], family: ['green', 'Aile'] };

export async function render(view, params, ctx) {
  if (params[0] && params[1]) return detail(view, params[0], params[1], ctx);
  return list(view, ctx);
}

async function list(view) {
  let kind = 'all', people = [];
  const q = h('input', { class: 'input', type: 'search', placeholder: 'İsim, telefon, firma ara…', style: { maxWidth: '280px' } });
  const seg = segmented([['all', 'Tümü'], ['user', 'Personel'], ['person', 'Firma kişileri'], ['family', 'Aile']], kind,
    v => { kind = v; load(); });
  const grid = h('div', { class: 'dir-grid' });
  const info = h('span', { class: 'small muted' });
  const draw = () => {
    const term = q.value.trim().toLowerCase();
    const shown = term ? people.filter(p => [p.name, p.subtitle, p.phone, p.email].some(x => (x || '').toLowerCase().includes(term))) : people;
    info.textContent = t('{n} kişi', { n: shown.length });
    clear(grid, shown.length ? shown.map(p => h('a', { class: 'card dir-card', href: `#/rehber/${p.type}/${p.id}` },
      avatar({ full_name: p.name, photo: p.photo }, 44),
      h('div', { class: 'dir-info' }, h('b', null, p.name),
        h('small', { class: 'muted' }, p.subtitle || ''),
        p.phone ? h('small', { class: 'muted' }, p.phone) : null),
      h('span', { class: `badge ${TYPE_BADGE[p.type][0]}` }, TYPE_BADGE[p.type][1])))
      : h('div', { class: 'card empty' }, 'Kişi bulunamadı.'));
  };
  const load = async () => {
    clear(grid, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
    try { people = (await api.get(`/api/directory?kind=${kind}`)).people; draw(); }
    catch (err) { clear(grid, h('div', { class: 'card empty' }, err.message)); }
  };
  q.addEventListener('input', draw);
  clear(view, pageHead('Rehber', { back: '#/', sub: 'Sistemdeki tüm kişiler' }), moduleToolbar(seg, q), h('p', null, info), grid);
  load();
}

async function detail(view, type, id, ctx) {
  clear(view, pageHead('Rehber', { back: '#/rehber', sub: 'Kişi detayı' }), h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get(`/api/directory/${type}/${id}`); } catch (err) { return clear(view, pageHead('Rehber', { back: '#/rehber' }), h('div', { class: 'card empty' }, err.message)); }
  const s = d.sections || {};
  const row = (label, val) => val ? h('div', { class: 'dir-row' }, h('span', { class: 'muted' }, label), h('b', null, val)) : null;
  const info = h('section', { class: 'card card-pad' },
    h('div', { class: 'dir-head' }, avatar({ full_name: d.full_name, photo: d.photo }, 64),
      h('div', null, h('h2', { style: { margin: 0 } }, d.full_name), h('span', { class: `badge ${TYPE_BADGE[type][0]}` }, d.type_label))),
    h('div', { class: 'dir-rows' },
      row('Görev', d.title), row('Departman', d.department), row('Firma', d.company), row('Yakınlık', d.relation),
      row('Ailesi', d.employee_name && t('{n} ailesi', { n: d.employee_name })),
      row('Telefon', d.phone), row('E-posta', d.email), row('Doğum', d.birth_date && fmtDate(d.birth_date)),
      row('Roller', (d.roles || []).join(', ')), d.note ? row('Not', d.note) : null));

  const sec = (title, items, rowFn, empty) => h('section', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, `${title}${items?.length ? ` (${items.length})` : ''}`),
    items?.length ? h('div', { class: 'dir-list' }, items.map(rowFn)) : h('div', { class: 'muted small' }, empty));

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
  if (s.documents) blocks.push(sec('Evraklar', s.documents, dd => h('a', { class: 'dir-li', href: `#/documents/${dd.id}` },
    h('b', null, dd.title || `#${dd.id}`), h('small', { class: 'muted' }, [dd.kind, dd.created_at && fmtDate(dd.created_at)].filter(Boolean).join(' · '))), 'Bağlı evrak yok.'));
  if (s.meetings) blocks.push(sec('Toplantılar', s.meetings, mm => h('div', { class: 'dir-li' },
    h('b', null, mm.title), h('small', { class: 'muted' }, [mm.starts_at && fmtDateTime(mm.starts_at), mm.company, mm.location].filter(Boolean).join(' · '))), 'Toplantı yok.'));
  if (s.calls) blocks.push(sec('Görüntülü Görüşmeler', s.calls, cc => h('div', { class: 'dir-li' },
    h('b', null, cc.title || (cc.kind === 'grup' ? 'Grup görüşmesi' : 'Görüşme')),
    h('small', { class: 'muted' }, [cc.started_at && fmtDateTime(cc.started_at), cc.status, cc.seconds && t('{n} sn', { n: Math.round(cc.seconds) })].filter(Boolean).join(' · '))), 'Görüşme yok.'));
  if (s.phone_calls) blocks.push(sec('Telefon Notları', s.phone_calls, pc => h('div', { class: 'dir-li' },
    h('b', null, pc.caller_name), h('small', { class: 'muted' }, [pc.subject, pc.created_at && fmtDateTime(pc.created_at)].filter(Boolean).join(' · '))), 'Telefon notu yok.'));

  clear(view, pageHead(d.full_name, { back: '#/rehber', sub: d.type_label }), h('div', { class: 'dir-detail' }, ...blocks));
}
