// Duyurular: Sistem Yöneticisi yazar, herkes okur. Açınca okundu sayılır ve "Okunmamış" listesinden düşer;
// yönetici her duyuruyu kimin okuduğunu ve okumadığını görür.
import { api } from '../api.js';
import { avatar, clear, confirmDialog, field, fmtDate, fmtDateTime, h, modal, moduleToolbar, pageHead, pref, segmented, setPref, toast } from '../ui.js';

export const LEVELS = { BILGI: ['blue', 'Bilgi'], ONEMLI: ['yellow', 'Önemli'], KRITIK: ['red', 'Kritik'] };

export async function render(view, params, ctx) {
  if (params[0]) return renderDetail(view, Number(params[0]), ctx);
  let mode = pref('ann.view', 'unread');
  const out = h('div');
  let data = { items: [], can_edit: false };
  const draw = () => {
    const list = data.items.filter(a => mode === 'all' || !a.read_at);
    clear(out, list.length ? h('div', { class: 'ann-list' }, list.map(card))
      : h('div', { class: 'card empty' }, mode === 'unread' ? 'Okunmamış duyurunuz yok. Eskiler için "Tümü"ne bakın.' : 'Henüz duyuru yok'));
  };
  const card = a => {
    const [cls, label] = LEVELS[a.level] || LEVELS.BILGI;
    return h('a', { class: `card ann-card lv-${a.level} ${a.read_at ? 'read' : 'unread'}`, href: `#/announcements/${a.id}` },
      h('div', { class: 'ann-top' },
        a.pinned ? h('span', { class: 'ann-pin', title: 'Sabitlenmiş' }, '📌') : null,
        h('b', null, a.title), h('span', { class: 'grow' }),
        !a.read_at ? h('span', { class: 'badge blue' }, 'Yeni') : null,
        h('span', { class: `badge ${cls}` }, label)),
      h('div', { class: 'ann-snip' }, a.body.length > 220 ? `${a.body.slice(0, 220)}…` : a.body),
      h('div', { class: 'small muted' }, `${fmtDateTime(a.created_at)} · ${a.created_by_name || 'Yönetim'}`,
        a.expires_at ? ` · ${a.expired ? 'süresi doldu' : `${fmtDate(a.expires_at)} tarihine kadar`}` : '',
        data.can_edit ? ` · ${a.read_count} / ${a.user_total} kişi okudu` : ''));
  };
  const load = async () => { data = await api.get('/api/announcements'); draw(); };
  await load();
  const seg = segmented([['unread', 'Okunmamış'], ['all', 'Tümü']], mode, v => { mode = v; setPref('ann.view', v); draw(); });
  clear(view, pageHead('Duyurular', { back: '#/', sub: 'Yönetim duyuruları', tabs: seg }),
    moduleToolbar(data.can_edit ? h('button', { class: 'btn primary', onclick: () => annForm(null, load) }, '+ Yeni Duyuru') : null),
    out);
}

async function renderDetail(view, id, ctx) {
  const a = await api.get(`/api/announcements/${id}`);   // açmak okundu yapar
  const admin = !!a.readers;
  const [cls, label] = LEVELS[a.level] || LEVELS.BILGI;
  const total = admin ? a.readers.length + a.unread.length : 0;
  clear(view,
    pageHead(a.title, { back: '#/announcements', sub: h('span', null, h('span', { class: `badge ${cls}` }, label), `  ${fmtDateTime(a.created_at)} · ${a.created_by_name || 'Yönetim'}`,
      a.updated_at ? ` · düzenlendi ${fmtDateTime(a.updated_at)}` : '') }),
    moduleToolbar(admin ? [
      h('button', { class: 'btn', onclick: () => annForm(a, () => renderDetail(view, id, ctx)) }, 'Düzenle'),
      h('button', { class: 'btn ghost', onclick: async () => {
        if (!await confirmDialog('Duyuruyu sil', `"${a.title}" silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
        await api.del(`/api/announcements/${id}`); toast('Duyuru silindi'); location.hash = '#/announcements';
      } }, 'Sil')] : null),
    h('div', { class: `card card-pad ann-body lv-${a.level}` }, a.body),
    admin ? h('div', { class: 'ann-reads' },
      h('div', { class: 'card card-pad' },
        h('h3', null, `Okuyanlar (${a.readers.length} / ${total})`),
        h('div', { class: 'ann-prog' }, h('i', { style: { width: `${total ? Math.round(100 * a.readers.length / total) : 0}%` } })),
        a.readers.length ? h('ul', { class: 'ann-people' }, a.readers.map(u => h('li', null, avatar(u), h('span', { class: 'grow' }, u.full_name),
          h('span', { class: 'small muted' }, fmtDateTime(u.read_at))))) : h('div', { class: 'empty small' }, 'Henüz okuyan yok')),
      h('div', { class: 'card card-pad' },
        h('h3', null, `Okumayanlar (${a.unread.length})`),
        a.unread.length ? h('ul', { class: 'ann-people' }, a.unread.map(u => h('li', null, avatar(u), h('span', { class: 'grow' }, u.full_name))))
          : h('div', { class: 'empty small' }, 'Herkes okudu'))) : null);
}

function annForm(a, done) {
  const title = h('input', { class: 'input', value: a?.title || '', placeholder: 'Duyuru başlığı' });
  const body = h('textarea', { class: 'input', rows: 7, placeholder: 'Duyuru metni' }, a?.body || '');
  const level = h('select', { class: 'input' }, Object.entries(LEVELS).map(([k, [, l]]) => h('option', { value: k, selected: (a?.level || 'BILGI') === k }, l)));
  const pinned = h('input', { type: 'checkbox', checked: !!a?.pinned });
  const expires = h('input', { class: 'input', type: 'date', value: a?.expires_at || '' });
  modal({
    title: a ? 'Duyuruyu Düzenle' : 'Yeni Duyuru', wide: true,
    body: h('div', null, field('Başlık', title), field('Metin', body),
      h('div', { class: 'row' }, field('Önem', level), field('Son geçerlilik (isteğe bağlı)', expires)),
      h('label', { class: 'check' }, pinned, 'Sabitle (listede en üstte)'),
      h('p', { class: 'small muted' }, 'Duyuru tüm kullanıcılara bildirim olarak düşer; açan kullanıcı okumuş sayılır.')),
    actions: [{ label: 'Vazgeç' }, { label: a ? 'Kaydet' : 'Yayımla', class: 'primary', onClick: async () => {
      const b = { title: title.value, body: body.value, level: level.value, pinned: pinned.checked, expires_at: expires.value || null };
      if (a) await api.put(`/api/announcements/${a.id}`, b); else await api.post('/api/announcements', b);
      toast(a ? 'Duyuru güncellendi' : 'Duyuru yayımlandı');
      done();
    } }],
  });
}
