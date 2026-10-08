// Rehber: sistemde kaynağına bakılmaksızın kayıtlı tüm kişiler (personel, firma kişileri, aile üyeleri) tek rehberde.
// Kişiye tıklayınca detay: bilgiler, evraklar, yüz tanıma kayıtları, görüntülü görüşmeler, toplantılar, telefon notları.
import { api, fileUrl } from '../api.js';
import { avatar, clear, confirmDialog, field, fmtDate, fmtDateTime, h, modal, moduleToolbar, pageHead, segmented, t, toast } from '../ui.js';

const TYPE_BADGE = { user: ['blue', 'Personel'], person: ['', 'Firma kişisi'], family: ['green', 'Aile'], mine: ['yellow', 'Kişilerim'] };
const MINE_SRC = { mail: 'Yazışma', google: 'Google Kişiler', microsoft: 'Outlook Kişileri', manual: 'Elle eklendi', device: '📱 Telefon' };
// Mobil uygulama köprüsü (telefon rehberi ↔ sistem); yalnız native kabukta ve contacts eklentisi varsa
const nativeContacts = () => (window.HepgoNative && window.HepgoNative.hasContacts && window.HepgoNative.hasContacts()) ? window.HepgoNative : null;
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
  const importBtn = h('button', { class: 'btn', type: 'button', hidden: true, onclick: () => importFromPhone() }, '📱 Telefondan içe aktar');
  const exportBtn = h('button', { class: 'btn', type: 'button', hidden: true, onclick: () => exportToPhone() }, '📱 Telefona aktar');
  const grid = h('div', { class: 'gd-groups' });
  const info = h('span', { class: 'small muted' });
  const filtered = () => {
    const term = q.value.trim().toLocaleLowerCase('tr');
    return term ? people.filter(p => [p.name, p.subtitle, p.phone, p.email].some(x => (x || '').toLocaleLowerCase('tr').includes(term))) : people;
  };
  async function importFromPhone() {
    importBtn.disabled = true; importBtn.textContent = '📱 İçe aktarılıyor…';
    try {
      const r = await nativeContacts().importDeviceContacts();
      toast(t('{n} kişi içe aktarıldı (📱 Telefon)', { n: r.total || 0 }), 'success');
      if (kind === 'mine') load();
    } catch (err) {
      toast(err.message === 'no-perm' ? 'Telefon rehberi izni verilmedi' : (err.message === 'no-plugin' ? 'Bu özellik yalnızca uygulamada çalışır' : 'İçe aktarılamadı'), 'err');
    } finally { importBtn.disabled = false; importBtn.textContent = '📱 Telefondan içe aktar'; }
  }
  async function exportToPhone() {
    const shown = filtered().filter(p => p.phone || p.email);
    if (!shown.length) return toast('Aktarılacak telefon/e-posta olan kişi yok', 'err');
    if (!await confirmDialog('Telefona aktar', t('{n} kişi telefonunuzun rehberine eklenecek. Devam edilsin mi?', { n: shown.length }), { okLabel: 'Aktar' })) return;
    exportBtn.disabled = true; exportBtn.textContent = '📱 Aktarılıyor…';
    try {
      const r = await nativeContacts().addContactsToPhone(shown.map(p => ({
        name: tc(p.name), phone: p.phone, email: p.email,
        company: p.company || (p.type === 'person' ? p.subtitle : null), title: p.title })));
      toast(t('{n} kişi telefona eklendi', { n: r.count || 0 }), 'success');
    } catch (err) {
      toast(err.message === 'no-perm' ? 'Telefon rehberi izni verilmedi' : 'Telefona aktarılamadı', 'err');
    } finally { exportBtn.disabled = false; exportBtn.textContent = '📱 Telefona aktar'; }
  }
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
    const shown = filtered();
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
    const nat = nativeContacts();
    importBtn.hidden = !(nat && kind === 'mine');       // telefon → Kişilerim
    exportBtn.hidden = !(nat && kind !== 'mine');        // sistem rehberi → telefon
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
  clear(view, pageHead('Rehber', { back: '#/', sub: 'Sistemdeki tüm kişiler · Kişilerim yalnızca size özeldir' }), moduleToolbar(seg, [q, addBtn, importBtn, exportBtn]), h('p', null, info), grid);
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

// ---------------------------------------------------------------- Yapay Zeka alt modülü (yüz + ses eğitimi/kayıtları)
// Rehber kişi detayında, yüz (ctx.user.nvr) ve/veya ses (ctx.user.speech) eklentisi kuruluysa görünür.
function aiSection(type, id, name, ctx) {
  const colKey = { user: 'user_id', person: 'person_id', family: 'family_id' }[type];
  const faceQ = `subject_type=${type}&${colKey}=${id}`;
  const card = h('section', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, '🧠 Yapay Zeka'));

  // ---- YÜZ TANIMA
  if (ctx.user.nvr) {
    const faceWrap = h('div', { style: { marginTop: '6px' } });
    card.append(faceWrap);
    const sel = new Set();
    const drawFace = async () => {
      clear(faceWrap, h('div', { class: 'loading' }, 'Yüz kayıtları yükleniyor…'));
      let faces;
      try { faces = (await api.get(`/api/faces/enroll?${faceQ}`)).faces || []; }
      catch (err) { return clear(faceWrap, h('div', { class: 'muted small' }, err.message || 'Yüz kayıtları okunamadı')); }
      sel.clear();
      const manual = faces.filter(f => f.source !== 'auto');
      const auto = faces.filter(f => f.source === 'auto');
      const trainBtn = h('button', { class: 'btn primary sm', type: 'button' }, '📷 Yüz Tanıma Eğitimi');
      trainBtn.addEventListener('click', async () => {
        try { const m = await import('../livepanels.js'); await m.openFaceEnroll({ subject_type: type, user_id: type === 'user' ? id : null, person_id: type === 'person' ? id : null, family_id: type === 'family' ? id : null, name, onDone: drawFace }); }
        catch (err) { toast(err.message || 'Panel açılamadı', 'err'); }
      });
      const bulkBtn = h('button', { class: 'btn sm danger', type: 'button', disabled: true }, 'Seçilenleri sil');
      const group = (title, rows) => {
        if (!rows.length) return h('div', { class: 'muted small', style: { margin: '4px 0 10px' } }, `${title}: kayıt yok`);
        return h('div', { style: { margin: '4px 0 12px' } },
          h('div', { class: 'small muted', style: { marginBottom: '4px' } }, `${title} (${rows.length})`),
          h('div', { class: 'fg-recognized' }, rows.map(f => thumb(f))));
      };
      const thumb = f => {
        const img = h('img', { src: fileUrl(f.crop, 120), alt: '', loading: 'lazy', title: f.created_at ? fmtDateTime(f.created_at) : '' });
        const cb = h('input', { type: 'checkbox', style: { position: 'absolute', top: '3px', left: '3px' } });
        cb.addEventListener('change', () => { cb.checked ? sel.add(f.id) : sel.delete(f.id); bulkBtn.disabled = !sel.size; bulkBtn.textContent = sel.size ? `Seçilenleri sil (${sel.size})` : 'Seçilenleri sil'; });
        const del = h('button', { class: 'btn xs ghost danger-text', type: 'button', title: 'Sil', style: { position: 'absolute', top: '2px', right: '2px', padding: '0 5px' } }, '×');
        del.addEventListener('click', async () => {
          if (!await confirmDialog('Eğitim resmini sil', 'Bu yüz eğitim resmi silinsin mi?', { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/faces/enroll/${f.id}`); drawFace(); } catch (err) { toast(err.message, 'err'); }
        });
        return h('div', { style: { position: 'relative' } }, img, cb, del);
      };
      bulkBtn.addEventListener('click', async () => {
        if (!sel.size) return;
        if (!await confirmDialog('Seçilenleri sil', t('{n} eğitim resmi silinsin mi?', { n: sel.size }), { okLabel: 'Sil', danger: true })) return;
        try { await api.post('/api/faces/enroll/delete', { ids: [...sel] }); toast('Silindi'); drawFace(); } catch (err) { toast(err.message, 'err'); }
      });
      clear(faceWrap,
        h('div', { class: 'set-actions left', style: { marginBottom: '8px' } }, trainBtn, bulkBtn),
        h('div', { class: 'small muted', style: { marginBottom: '8px' } }, 'Yüz eğitim resimleri — elle eklediklerimiz ve kişiye kameradan atananlar ayrı gruplanır. Eğitim düğmesiyle kamera açılır; başınızı yavaşça çevirdikçe otomatik çeker.'),
        group('Elle eklenen eğitim resimleri', manual),
        group('Kameradan otomatik atanan', auto));
    };
    drawFace();
  }

  // ---- SES TANIMA (yalnız personel/user; ses profili user_id'ye bağlı)
  if (ctx.user.speech && type === 'user') {
    const voiceWrap = h('div', { style: { marginTop: '10px', borderTop: '1px solid var(--line,#e5e7eb)', paddingTop: '10px' } });
    card.append(voiceWrap);
    const drawVoice = async () => {
      clear(voiceWrap, h('div', { class: 'loading' }, 'Ses kayıtları yükleniyor…'));
      let data;
      try { data = await api.get(`/api/voice/person/${id}/samples`); }
      catch (err) { return clear(voiceWrap, h('div', { class: 'muted small' }, err.message || 'Ses kayıtları okunamadı')); }
      const trainBtn = h('button', { class: 'btn primary sm', type: 'button' }, '🎙️ Ses Tanıma Eğitimi');
      trainBtn.addEventListener('click', async () => {
        try { const m = await import('../livepanels.js'); await m.openVoiceEnroll({ user_id: id, name, onDone: drawVoice }); }
        catch (err) { toast(err.message || 'Panel açılamadı', 'err'); }
      });
      const manualRow = r => {
        const del = h('button', { class: 'btn xs ghost danger-text', type: 'button' }, 'Sil');
        del.addEventListener('click', async () => {
          if (!await confirmDialog('Ses kaydını sil', 'Bu ses eğitim kaydı silinsin mi? Profil kalan kayıtlardan yeniden kurulur.', { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/voice/samples/${r.id}`); toast('Silindi'); drawVoice(); } catch (err) { toast(err.message, 'err'); }
        });
        return h('div', { class: 'gd-li' }, h('b', null, `Eğitim kaydı #${r.id}`),
          h('small', { class: 'muted' }, [r.seconds && t('{n} sn', { n: Math.round(r.seconds) }), r.created_at && fmtDateTime(r.created_at)].filter(Boolean).join(' · ')), del);
      };
      const autoRow = r => {
        const del = h('button', { class: 'btn xs ghost danger-text', type: 'button', title: 'Bağı kaldır' }, 'Kaldır');
        del.addEventListener('click', async () => {
          if (!await confirmDialog('Otomatik kaydı kaldır', 'Bu otomatik tanıma kaydının kişiyle bağı kaldırılsın mı?', { okLabel: 'Kaldır', danger: true })) return;
          try { await api.del(`/api/voice/samples/auto/${r.id}`); toast('Kaldırıldı'); drawVoice(); } catch (err) { toast(err.message, 'err'); }
        });
        return h('div', { class: 'gd-li' }, h('b', null, r.label || `Konuşmacı #${r.id}`),
          h('small', { class: 'muted' }, ['Arama #' + r.call_id, r.seconds && t('{n} sn', { n: Math.round(r.seconds) }), r.score != null && `%${Math.round(r.score * 100)}`].filter(Boolean).join(' · ')), del);
      };
      const grp = (title, rows, fn, empty) => h('div', { style: { margin: '6px 0' } },
        h('div', { class: 'small muted', style: { marginBottom: '2px' } }, `${title}${rows.length ? ` (${rows.length})` : ''}`),
        rows.length ? h('div', { class: 'gd-list' }, rows.map(fn)) : h('div', { class: 'muted small' }, empty));
      clear(voiceWrap,
        h('h4', { style: { margin: '0 0 6px' } }, 'Ses Tanıma'),
        h('div', { class: 'set-actions left', style: { marginBottom: '6px' } }, trainBtn,
          data.profile ? h('span', { class: 'small muted' }, t('Profil: {n} örnek', { n: data.profile.samples || 0 })) : h('span', { class: 'small muted' }, 'Profil yok')),
        grp('Elle girilen', data.manual || [], manualRow, 'Elle eğitim kaydı yok.'),
        grp('Otomatik (toplantı/arama)', data.auto || [], autoRow, 'Otomatik tanıma kaydı yok.'));
    };
    drawVoice();
  }
  return card;
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
      row('Roller', (d.roles || []).join(', ')), d.note ? row('Not', d.note) : null),
    (nativeContacts() && (d.phone || d.email)) ? h('div', { class: 'set-actions left', style: { marginTop: '10px' } },
      (() => {
        const b = h('button', { class: 'btn sm', type: 'button' }, '📱 Telefona ekle');
        b.addEventListener('click', async () => {
          b.disabled = true;
          try {
            const r = await nativeContacts().addContactsToPhone([{ name: tc(d.full_name), phone: d.phone, email: d.email, company: tc(d.company), title: tc(d.title) }]);
            toast(r.count ? 'Telefona eklendi' : 'Eklenemedi', r.count ? 'success' : 'err');
          } catch (err) { toast(err.message === 'no-perm' ? 'Telefon rehberi izni verilmedi' : 'Telefona eklenemedi', 'err'); }
          finally { b.disabled = false; }
        });
        return b;
      })()) : null);

  const sec = (title, items, rowFn, empty) => h('section', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, `${title}${items?.length ? ` (${items.length})` : ''}`),
    items?.length ? h('div', { class: 'gd-list' }, items.map(rowFn)) : h('div', { class: 'muted small' }, empty));

  const blocks = [info];
  if (ctx.user.nvr || (ctx.user.speech && type === 'user')) blocks.push(aiSection(type, Number(id), tc(d.full_name), ctx));
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
