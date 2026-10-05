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
  // Yüz tanıma hassasiyeti (eşik) — düşük = daha çok yüz yakalar; anında fabrikaya uygulanır
  let facerecCfg = { score: 0.6, min_face: 36 };
  const sens = h('input', { type: 'range', min: '0.3', max: '0.95', step: '0.05', value: '0.6', style: { width: '120px' },
    title: 'Yüz tanıma hassasiyeti: düşük değer daha çok yüz yakalar (yanlış tespit artabilir)' });
  const sensVal = h('b', { style: { minWidth: '34px', textAlign: 'right' } }, '0.60');
  const sensWrap = h('label', { class: 'fc-sens' }, h('span', { class: 'small muted' }, 'Hassasiyet'), sens, sensVal);
  api.get('/api/system/nvr/facerec').then(c => { facerecCfg = c; sens.value = c.score; sensVal.textContent = Number(c.score).toFixed(2); }).catch(() => {});
  sens.addEventListener('input', () => { sensVal.textContent = Number(sens.value).toFixed(2); });
  sens.addEventListener('change', async () => {
    try { const r = await api.put('/api/system/nvr/facerec', { score: Number(sens.value), min_face: facerecCfg.min_face || 36 }); facerecCfg = r; sens.value = r.score; sensVal.textContent = Number(r.score).toFixed(2); toast('Hassasiyet kaydedildi · anında geçerli', 'success'); }
    catch (err) { toastError(err); }
  });
  const info = h('span', { class: 'small muted' });
  const out = h('div');
  const selected = new Set();
  let rows = [];
  // Sıralama: görülme sayısı / son görülme / kamera + yön (↑/↓)
  const sortSel = h('select', { class: 'input', title: 'Sırala', style: { maxWidth: '170px' } },
    h('option', { value: 'last' }, 'Son görülme'), h('option', { value: 'count' }, 'Görülme sayısı'), h('option', { value: 'camera' }, 'Kamera'));
  let dir = -1;   // -1 azalan (yeni/çok önce), 1 artan
  const dirBtn = h('button', { class: 'btn', type: 'button', title: 'Yön', onclick: () => { dir = -dir; dirBtn.textContent = dir < 0 ? '↓' : '↑'; draw(); } }, '↓');
  sortSel.addEventListener('change', () => draw());
  const sortKey = g => sortSel.value === 'count' ? (g.sightings || 0)
    : sortSel.value === 'camera' ? (g.last_camera_name || g.cameras || '').toLocaleLowerCase('tr')
      : (g.last_seen || '');
  const syncBtn = () => {
    mergeBtn.disabled = selected.size < 2; mergeBtn.textContent = t('Seçilenleri Birleştir{n}', { n: selected.size ? ` (${selected.size})` : '' });
    delBtn.disabled = selected.size < 1; delBtn.textContent = t('Seçilenleri Kaldır{n}', { n: selected.size ? ` (${selected.size})` : '' });
  };

  const draw = () => {
    const list = rows.filter(g => matches(q.value, g.cameras, g.user_name, g.person_name, g.person_company, g.last_camera_name));
    list.sort((a, b) => { const ka = sortKey(a), kb = sortKey(b); return (ka < kb ? -1 : ka > kb ? 1 : 0) * dir; });
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
    const sel = new Set();   // bu grupta seçili görülme id'leri (iPhone tarzı seçim)
    const selDelBtn = h('button', { class: 'btn danger', type: 'button', disabled: true, onclick: () => removeSelected() }, 'Seçilenleri Kaldır');
    const selAssignBtn = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: () => assignSelected() }, 'Seçilenleri Kaldır ve Kişiye Ata');
    const selInfo = h('span', { class: 'small muted' });
    const syncSel = () => {
      const n = sel.size;
      selDelBtn.disabled = selAssignBtn.disabled = n < 1;
      selDelBtn.textContent = t('Seçilenleri Kaldır{n}', { n: n ? ` (${n})` : '' });
      selAssignBtn.textContent = t('Seçilenleri Kaldır ve Kişiye Ata{n}', { n: n ? ` (${n})` : '' });
      selInfo.textContent = n ? t('{n} resim seçili', { n }) : 'Resimleri seçmek için her resmin sağ üstündeki kutucuğa dokunun.';
    };
    const shots = h('div', { class: 'fg-shots' }, g.items.map(s => {
      const pick = h('button', { class: 'fg-pick', type: 'button', title: 'Seç', 'aria-pressed': 'false' });
      const shot = h('div', { class: 'fg-shot' }, pick,
        h('button', { class: 'fg-shot-img', type: 'button', onclick: () => showFrame(s) }, h('img', { src: fileUrl(s.crop, 256), alt: '', loading: 'lazy' })),
        h('span', null, fmtDateTime(s.at)), h('span', { class: 'muted' }, s.camera_name || '—'),
        s.threshold != null ? h('span', { class: 'muted' }, t('hassasiyet {v}', { v: s.threshold })) : null);
      pick.addEventListener('click', e => {
        e.stopPropagation();
        sel.has(s.id) ? sel.delete(s.id) : sel.add(s.id);
        const on = sel.has(s.id);
        shot.classList.toggle('selected', on);
        pick.setAttribute('aria-pressed', on ? 'true' : 'false');
        syncSel();
      });
      return shot;
    }));
    syncSel();
    const m = modal({
      title: who ? `${who}${g.person_company ? ` · ${g.person_company}` : ''}` : 'Tanımlanamayan kişi', wide: true,
      body: h('div', null,
        h('div', { class: 'fg-head' }, g.best_crop ? h('img', { src: fileUrl(g.best_crop, 256), alt: '' }) : null,
          h('div', null, h('div', null, h('b', null, t('{n} görülme', { n: g.sightings })), t(' · {n} yüz örneği', { n: g.samples })),
            h('div', { class: 'small muted' }, t('İlk {a} · Son {b}', { a: fmtDateTime(g.first_seen), b: fmtDateTime(g.last_seen) })),
            h('div', { class: 'small muted' }, t('Kameralar: {c}', { c: g.cameras || '—' })),
            h('p', { class: 'small muted' }, 'Yüze tıklayınca görüldüğü anın tam karesi açılır.'))),
        h('div', { class: 'fg-seltools' }, selInfo, h('span', { class: 'spacer' }), selDelBtn, selAssignBtn),
        shots),
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

    async function reopen() {   // kaynak grup kaldıysa yeniden aç, boşaldıysa listeye dön
      m.close();
      try { await openGroup(id); } catch { load(); }
    }
    async function removeSelected() {
      if (!sel.size) return;
      if (!await confirmDialog('Seçilenleri kaldır', t('Seçili {n} görülme (yüz / kare resimleri) silinsin mi? (gereksiz tespitler için)', { n: sel.size }), { okLabel: 'Kaldır', danger: true })) return;
      try {
        const r = await api.post('/api/faces/sightings/delete', { ids: [...sel] });
        toast(t('{n} görülme kaldırıldı', { n: r.deleted ?? sel.size }));
        if (r.left) reopen(); else { m.close(); load(); }
      } catch (err) { toastError(err); }
    }
    function assignSelected() {
      if (!sel.size) return;
      const ids = [...sel];
      pickPerson(async (p, pm) => {
        try {
          await api.post('/api/faces/sightings/assign', { ids, ...bodyFor(p.kind, p.id) });
          toast(t('Seçili {n} yüz {name} kişisine atandı', { n: ids.length, name: p.name }));
          pm.close(); reopen();
        } catch (err) { toastError(err); }
      });
    }
  }

  function showFrame(s) {
    modal({ title: `${fmtDateTime(s.at)} · ${s.camera_name || ''}`, wide: true,
      body: h('a', { href: fileUrl(s.frame), target: '_blank', rel: 'noopener' }, h('img', { class: 'fg-frame', src: fileUrl(s.frame), alt: '' })),
      actions: [{ label: 'Kapat', class: 'primary' }] });
  }

  // Atama hedefi gövdesi: seçilen türe göre { user_id | person_id | family_id }
  function bodyFor(kind, id) {
    return kind === 'user' ? { user_id: id } : kind === 'person' ? { person_id: id } : { family_id: id };
  }

  // Yeniden kullanılabilir kişi seçici (personel / firma kişisi / aile üyesi). Seçimde onPick({ kind, id, name }, modal) çağrılır.
  async function pickPerson(onPick) {
    const { users, people, family = [] } = await api.get('/api/faces/people');
    let kind = 'user';
    const q2 = h('input', { class: 'input', type: 'search', placeholder: 'Ad ara…' });
    const list = h('div', { class: 'pick-list' });
    const fill = () => {
      const src = kind === 'user' ? users : kind === 'person' ? people : family;
      clear(list, src.filter(p => matches(q2.value, p.full_name, p.company_name, p.title, p.relation, p.employee_name)).slice(0, 60).map(p =>
        h('button', { class: 'pick', type: 'button', onclick: () => onPick({ kind, id: p.id, name: p.full_name }, m) },
          h('div', { class: 'grow' }, h('b', null, p.full_name),
            h('span', { class: 'small muted' }, kind === 'user' ? ' Personel'
              : kind === 'person' ? ` ${[p.title, p.company_name].filter(Boolean).join(' · ')}`
                : ` ${[p.relation, p.employee_name && t('{n} ailesi', { n: p.employee_name })].filter(Boolean).join(' · ')}`)))));
    };
    const seg = segmented([['user', 'Personel'], ['person', 'Firma personeli'], ['family', 'Aile üyeleri']], kind, v => { kind = v; fill(); });
    q2.addEventListener('input', fill);
    fill();
    const m = modal({ title: 'Kişiye Ata', body: h('div', null, seg, h('div', { style: { margin: '10px 0' } }, q2), list), actions: [{ label: 'Vazgeç' }] });
    q2.focus();
    return m;
  }

  // Grup düzeyinde atama (gruptaki tüm yüzler) — eskiden olduğu gibi.
  function assign(id, done) {
    pickPerson(async (p, m) => {
      try {
        await api.post(`/api/faces/groups/${id}/assign`, bodyFor(p.kind, p.id));
        toast(t('Gruptaki tüm yüzler {name} kişisine atandı', { name: p.name }));
        m.close();
        done();
      } catch (err) { toastError(err); }
    });
  }

  q.addEventListener('input', draw);
  clear(body, h('div', { class: 'filters' }, nav, q, h('span', { class: 'fc-sens' }, h('span', { class: 'small muted' }, 'Sırala'), sortSel, dirBtn), h('span', { class: 'spacer' }), sensWrap, delBtn, mergeBtn), h('p', null, info), out);
  await load();
  every(15000, () => { if (!document.querySelector('.modal-back')) load().catch(() => {}); });
}
