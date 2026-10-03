// Güvenlik → Tanımlanamayan Kişiler: kameralarda görülen, henüz kimseye atanmamış yüzler; benzer yüzler bir grupta.
// Gruba tıklanınca tüm görülmeler (yüz ve görüldüğü anın tam karesi); "Kişiye Ata" ile gruptaki tüm yüzler bir kullanıcıya
// ya da firma personeline atanır ve sonraki görülmelerde o kişi tanınır. Aynı kişinin grupları birleştirilebilir.
import { api, fileUrl } from '../api.js';
import { clear, confirmDialog, every, fmtDateTime, h, matches, modal, segmented, t, toast, toastError } from '../ui.js';

export async function renderFaces(body) {
  let state = 'unknown';
  const nav = h('select', { class: 'input', title: 'Durum' }, h('option', { value: 'unknown' }, 'Tanımlanamayanlar'), h('option', { value: 'known' }, 'Tanınan kişiler'));
  nav.addEventListener('change', () => { state = nav.value; selected.clear(); load(); });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kamera, kişi ara…', style: { width: '200px' } });
  const mergeBtn = h('button', { class: 'btn', type: 'button', disabled: true, onclick: () => mergeSelected() }, 'Seçilenleri Birleştir');
  const delBtn = h('button', { class: 'btn danger', type: 'button', disabled: true, onclick: () => deleteSelected() }, 'Seçilenleri Kaldır');
  const info = h('span', { class: 'small muted' });
  const out = h('div');
  const selected = new Set();
  let rows = [];
  const syncBtn = () => {
    mergeBtn.disabled = selected.size < 2; mergeBtn.textContent = t('Seçilenleri Birleştir{n}', { n: selected.size ? ` (${selected.size})` : '' });
    delBtn.disabled = selected.size < 1; delBtn.textContent = t('Seçilenleri Kaldır{n}', { n: selected.size ? ` (${selected.size})` : '' });
  };

  const draw = () => {
    const list = rows.filter(g => matches(q.value, g.cameras, g.user_name, g.person_name, g.person_company, g.last_camera_name));
    info.textContent = state === 'unknown'
      ? t('{n} tanımlanamayan kişi grubu · aynı kişiye ait grupları seçip birleştirebilirsiniz', { n: list.length })
      : t('{n} tanınan kişi', { n: list.length });
    clear(out, list.length ? h('div', { class: 'fg-grid' }, list.map(g => {
      const cb = h('input', { type: 'checkbox', checked: selected.has(g.id), onclick: e => e.stopPropagation(),
        onchange: e => { e.target.checked ? selected.add(g.id) : selected.delete(g.id); card.classList.toggle('on', e.target.checked); syncBtn(); } });
      const card = h('div', { class: `card fg-card ${selected.has(g.id) ? 'on' : ''}`, onclick: () => openGroup(g.id) },
        h('div', { class: 'fg-img' }, g.best_crop ? h('img', { src: fileUrl(g.best_crop, 256), alt: '', loading: 'lazy' }) : null,
          state === 'unknown' ? h('label', { class: 'fg-check', onclick: e => e.stopPropagation() }, cb) : null),
        h('div', { class: 'fg-body' },
          state === 'known' ? h('b', null, g.user_name || g.person_name || g.family_name, g.person_company ? h('span', { class: 'small muted' }, ` · ${g.person_company}`) : null)
            : h('b', null, 'Tanımlanamayan kişi'),
          h('div', { class: 'small' }, t('{n} görülme', { n: g.sightings })),
          h('div', { class: 'small muted' }, t('Son: {d}{cam}', { d: fmtDateTime(g.last_seen), cam: g.last_camera_name ? ` · ${g.last_camera_name}` : '' })),
          h('div', { class: 'small muted' }, t('İlk: {d}', { d: fmtDateTime(g.first_seen) }))));
      return card;
    })) : h('div', { class: 'card empty' }, state === 'unknown'
      ? 'Tanımlanamayan kişi yok. Kameralarda yüz tanıma açıksa görülen yüzler burada gruplanır.' : 'Henüz kişiye atanmış yüz yok'));
  };
  async function load() {
    rows = await api.get(`/api/faces/groups?state=${state}`);
    for (const id of [...selected]) if (!rows.some(g => g.id === id)) selected.delete(id);
    syncBtn();
    mergeBtn.hidden = delBtn.hidden = state !== 'unknown';
    draw();
  }
  async function mergeSelected() {
    if (!await confirmDialog('Grupları birleştir', t('{n} grup aynı kişi olarak birleştirilsin mi?', { n: selected.size }), { okLabel: 'Birleştir' })) return;
    try { await api.post('/api/faces/merge', { ids: [...selected] }); selected.clear(); toast('Gruplar birleştirildi'); load(); } catch (err) { toastError(err); }
  }
  async function deleteSelected() {
    if (!await confirmDialog('Seçilenleri kaldır', t('Seçili {n} grup ve tüm yüz / kare resimleri silinsin mi? (gereksiz tespitler için)', { n: selected.size }), { okLabel: 'Kaldır', danger: true })) return;
    try {
      for (const id of [...selected]) await api.del(`/api/faces/groups/${id}`);
      toast(t('{n} grup kaldırıldı', { n: selected.size })); selected.clear(); load();
    } catch (err) { toastError(err); }
  }

  async function openGroup(id) {
    const g = await api.get(`/api/faces/groups/${id}`);
    const who = g.user_name || g.person_name || g.family_name;
    const m = modal({
      title: who ? `${who}${g.person_company ? ` · ${g.person_company}` : ''}` : 'Tanımlanamayan kişi', wide: true,
      body: h('div', null,
        h('div', { class: 'fg-head' }, g.best_crop ? h('img', { src: fileUrl(g.best_crop, 256), alt: '' }) : null,
          h('div', null, h('div', null, h('b', null, t('{n} görülme', { n: g.sightings })), t(' · {n} yüz örneği', { n: g.samples })),
            h('div', { class: 'small muted' }, t('İlk {a} · Son {b}', { a: fmtDateTime(g.first_seen), b: fmtDateTime(g.last_seen) })),
            h('div', { class: 'small muted' }, t('Kameralar: {c}', { c: g.cameras || '—' })),
            h('p', { class: 'small muted' }, 'Yüze tıklayınca görüldüğü anın tam karesi açılır.'))),
        h('div', { class: 'fg-shots' }, g.items.map(s => h('button', { class: 'fg-shot', type: 'button', onclick: () => showFrame(s) },
          h('img', { src: fileUrl(s.crop, 256), alt: '', loading: 'lazy' }),
          h('span', null, fmtDateTime(s.at)), h('span', { class: 'muted' }, s.camera_name || '—'))))),
      actions: [
        { label: 'Grubu Sil', class: 'danger', onClick: async () => {
          if (!await confirmDialog('Grubu sil', 'Bu gruptaki tüm yüz ve kare resimleri silinsin mi? (yanlış tespitler için)', { okLabel: 'Sil', danger: true })) return true;
          await api.del(`/api/faces/groups/${id}`); toast('Grup silindi'); load();
        } },
        who ? { label: 'Atamayı Kaldır', onClick: async () => { await api.post(`/api/faces/groups/${id}/unassign`); toast('Atama kaldırıldı'); load(); } } : null,
        'spacer',
        { label: 'Kapat' },
        { label: who ? 'Başka Kişiye Ata' : 'Kişiye Ata', class: 'primary', onClick: () => { assign(id, () => { m.close(); load(); }); return true; } },
      ].filter(Boolean),
    });
  }

  function showFrame(s) {
    modal({ title: `${fmtDateTime(s.at)} · ${s.camera_name || ''}`, wide: true,
      body: h('a', { href: fileUrl(s.frame), target: '_blank', rel: 'noopener' }, h('img', { class: 'fg-frame', src: fileUrl(s.frame), alt: '' })),
      actions: [{ label: 'Kapat', class: 'primary' }] });
  }

  async function assign(id, done) {
    const { users, people, family = [] } = await api.get('/api/faces/people');
    let kind = 'user';
    const q2 = h('input', { class: 'input', type: 'search', placeholder: 'Ad ara…' });
    const list = h('div', { class: 'pick-list' });
    const fill = () => {
      const src = kind === 'user' ? users : kind === 'person' ? people : family;
      clear(list, src.filter(p => matches(q2.value, p.full_name, p.company_name, p.title, p.relation, p.employee_name)).slice(0, 60).map(p =>
        h('button', { class: 'pick', type: 'button', onclick: async () => {
          try {
            const body = kind === 'user' ? { user_id: p.id } : kind === 'person' ? { person_id: p.id } : { family_id: p.id };
            await api.post(`/api/faces/groups/${id}/assign`, body);
            toast(t('Gruptaki tüm yüzler {name} kişisine atandı', { name: p.full_name }));
            m.close();
            done();
          } catch (err) { toastError(err); }
        } }, h('div', { class: 'grow' }, h('b', null, p.full_name),
          h('span', { class: 'small muted' }, kind === 'user' ? ' Personel'
            : kind === 'person' ? ` ${[p.title, p.company_name].filter(Boolean).join(' · ')}`
              : ` ${[p.relation, p.employee_name && t('{n} ailesi', { n: p.employee_name })].filter(Boolean).join(' · ')}`)))));
    };
    const seg = segmented([['user', 'Personel'], ['person', 'Firma personeli'], ['family', 'Aile üyeleri']], kind, v => { kind = v; fill(); });
    q2.addEventListener('input', fill);
    fill();
    const m = modal({ title: 'Kişiye Ata', body: h('div', null, seg, h('div', { style: { margin: '10px 0' } }, q2), list), actions: [{ label: 'Vazgeç' }] });
    q2.focus();
  }

  q.addEventListener('input', draw);
  clear(body, h('div', { class: 'filters' }, nav, q, h('span', { class: 'spacer' }), delBtn, mergeBtn), h('p', null, info), out);
  await load();
  every(15000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
}
