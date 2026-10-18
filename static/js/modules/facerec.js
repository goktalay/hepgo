// Güvenlik → Yüz Tanıma: (1) Eğitim — bir kişi için fotoğraf yükleyip yüzünü eğit; (2) Olaylar — seçilen tarih
// aralığında kameralarda tanınan kişilerin görülmeleri. Yüz verisi ve kayıtlar fabrikada (lokal) tutulur; buluta taşınmaz.
import { api, fileUrl, videoUrl } from '../api.js';
import { avatar, clear, confirmDialog, fmtDateTime, h, matches, modal, moduleToolbar, onLeave, segmented, t, toast, toastError } from '../ui.js';

export async function renderFaceRec(body, ctx, params) {
  const sub = ['train', 'events'].includes(params[0]) ? params[0] : 'train';
  const nav = segmented([['train', 'Eğitim'], ['events', 'Olaylar']], sub,
    v => { location.hash = `#/cameras/facerec/${v}`; }, { tabs: true });
  const inner = h('div');
  clear(body, moduleToolbar(nav), inner);
  if (sub === 'events') return renderEvents(inner, params[1], params[2]);
  return renderTrain(inner, ctx);
}

// ---- Eğitim: kişi seç + fotoğraf yükle → yüz eğitilsin ----
// Üst çubuk: "Seç" (iPhone Fotoğraflar kalıbı) → seçim kipinde her kırpığın köşesinde daire onay işareti; "Tümünü seç",
// sayaç, kırmızı "Seçilenleri sil" (onay penceresi → DELETE /api/cameras/face/photos {ids}); "Vazgeç"/Escape kapatır;
// dokunmatikte uzun basma seçim kipini açar. Başlıkta adın yanında EN SON tanınan yüz (yuvarlak avatar; yoksa baş harf).
const LAST_FACE_MAX = 300;   // listede avatar için tek istekte en çok bu kadar kişi sorulur
async function renderTrain(wrap, ctx) {
  clear(wrap, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let people;
  try { people = await api.get('/api/faces/people'); }
  catch (err) { return clear(wrap, h('div', { class: 'card empty' }, err.message)); }

  let kind = 'user';           // 'user' = personel, 'person' = firma kişisi
  let subject = null;          // seçili kişi
  let lastFaces = {};          // 'user:5' → {crop, frame, at, camera_name, sighting_id}
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara…', style: { maxWidth: '260px' } });
  const kindSeg = segmented([['user', 'Personel'], ['person', 'Firma Kişisi']], kind,
    v => { kind = v; subject = null; drawList(); drawSubject(); loadLastFaces(); });
  const listBox = h('div', { class: 'fr-people' });
  const subjectBox = h('div', { class: 'fr-subject' });

  const source = () => (kind === 'user' ? people.users : people.people);
  const nameOf = p => p.full_name;
  const subOf = p => (kind === 'user' ? '' : [p.title, p.company_name].filter(Boolean).join(' · '));
  const keyOf = (p, k = kind) => `${k}:${p.id}`;

  // Son tanınan yüz avatarı: kırpık varsa yuvarlak resim (tooltip: tarih/saat + kamera), yoksa baş harf avatarı
  const lastAvatar = (p, size, k = kind) => {
    const f = lastFaces[keyOf(p, k)];
    const tip = f ? t('Son tanınma: {when} · {cam}', { when: fmtDateTime(f.at), cam: f.camera_name || '—' }) : 'Kamerada henüz tanınmadı';
    const el = f ? h('button', { class: `avatar fr-last ${size}`, type: 'button', title: tip, onclick: e => { e.stopPropagation(); showLastFace(p, f, k); } },
      h('img', { src: fileUrl(f.crop, 128), alt: '', loading: 'lazy' }), h('span', { class: 'fr-last-dot', 'aria-hidden': 'true' }))
      : avatar({ full_name: p.full_name }, size);
    if (!f) el.title = tip;
    return el;
  };
  function showLastFace(p, f, k) {
    const date = (f.at || '').slice(0, 10);
    modal({ title: t('{name} · son tanınma', { name: p.full_name }), wide: true,
      body: h('div', { class: 'fr-frame fr-last-view' },
        f.frame ? h('img', { src: fileUrl(f.frame), alt: '' }) : h('img', { src: fileUrl(f.crop), alt: '', style: { maxWidth: '320px' } }),
        h('div', { class: 'fr-last-meta' }, h('img', { class: 'fr-last-crop', src: fileUrl(f.crop, 160), alt: '' }),
          h('div', null, h('b', null, fmtDateTime(f.at)), h('div', { class: 'small muted' }, f.camera_name || '—')))),
      actions: [{ label: 'Kapat' }, { label: 'Olaya git', class: 'primary', onClick: () => {
        location.hash = `#/cameras/facerec/events/${date}/${f.sighting_id || ''}`;
      } }] });
    void k;
  }
  async function loadLastFaces() {
    const keys = source().slice(0, LAST_FACE_MAX).map(p => keyOf(p));
    if (!keys.length) return;
    try { lastFaces = { ...lastFaces, ...((await api.get(`/api/faces/last-face?keys=${keys.join(',')}`)).faces || {}) }; }
    catch { /* fabrika ajanı eski olabilir */ }
    drawList(); if (subject) drawSubject(false);
  }

  const drawList = () => {
    const list = source().filter(p => matches(q.value, p.full_name, p.title, p.company_name));
    clear(listBox, list.length ? list.map(p => h('button', {
      class: `fr-person ${subject && subject.id === p.id ? 'on' : ''}`, type: 'button',
      onclick: () => { subject = p; drawList(); drawSubject(); },
    }, lastAvatar(p, 'fr-ava-sm'), h('span', { class: 'fr-person-t' }, h('b', null, nameOf(p)), subOf(p) ? h('small', { class: 'muted' }, subOf(p)) : null)))
      : h('div', { class: 'muted', style: { padding: '10px' } }, 'Kişi bulunamadı.'));
  };
  q.addEventListener('input', drawList);

  let faces = [];            // seçili kişinin eğitim kırpıkları
  let selecting = false;     // seçim kipi
  const sel = new Set();
  const onKey = e => { if (e.key === 'Escape' && selecting) { setSelecting(false); } };
  document.addEventListener('keydown', onKey);
  onLeave(() => document.removeEventListener('keydown', onKey));
  function setSelecting(on) { selecting = on; if (!on) sel.clear(); drawSubject(false); }

  async function drawSubject(reload = true) {
    if (!subject) return clear(subjectBox, h('div', { class: 'card empty' }, 'Eğitmek için soldan bir kişi seçin.'));
    if (reload) {
      clear(subjectBox, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
      faces = [];
      try { faces = (await api.get(`/api/faces/enroll?subject_type=${kind}&${kind}_id=${subject.id}`)).faces; } catch { /* */ }
      sel.clear();
      if (!faces.length) selecting = false;
    }
    const fileInp = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
    const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => fileInp.click() }, '+ Fotoğraf yükle');
    const status = h('span', { class: 'small muted' });
    fileInp.addEventListener('change', async () => {
      const files = [...fileInp.files]; fileInp.value = '';
      for (const file of files) {
        status.textContent = t('{name} işleniyor…', { name: file.name });
        const fd = new FormData();
        fd.append('file', file); fd.append('subject_type', kind); fd.append(`${kind}_id`, subject.id);
        try { await api.post('/api/faces/enroll', fd); }
        catch (err) { toast(err.message || 'Yüz bulunamadı', 'err'); }
      }
      status.textContent = ''; drawSubject();
    });
    // Seçim çubuğu (iPhone "Seç" kalıbı)
    const count = h('span', { class: 'fr-sel-count' });
    const delBtn = h('button', { class: 'btn danger fr-sel-del', type: 'button' }, 'Seçilenleri sil');
    const allBtn = h('button', { class: 'btn ghost sm', type: 'button' }, 'Tümünü seç');
    const refreshBar = () => {
      count.textContent = sel.size ? t('{n} seçildi', { n: sel.size }) : 'Fotoğraf seçin';
      delBtn.hidden = !sel.size;
      allBtn.textContent = sel.size === faces.length ? 'Seçimi kaldır' : 'Tümünü seç';
      grid.querySelectorAll('.fr-crop').forEach(el => {
        const on = sel.has(Number(el.dataset.id));
        el.classList.toggle('selected', on);
        el.querySelector('.fr-pick')?.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    };
    allBtn.addEventListener('click', () => { if (sel.size === faces.length) sel.clear(); else faces.forEach(f => sel.add(f.id)); refreshBar(); });
    delBtn.addEventListener('click', async () => {
      if (!sel.size) return;
      if (!await confirmDialog('Seçilenleri sil', t('{n} eğitim fotoğrafı silinsin mi? Bu işlem geri alınamaz.', { n: sel.size }), { okLabel: 'Sil', danger: true })) return;
      try {
        const r = await api.del('/api/cameras/face/photos', { ids: [...sel] });
        toast(t('{n} fotoğraf silindi', { n: r.deleted ?? sel.size }));
        selecting = false; drawSubject();
      } catch (err) { toastError(err); }
    });
    const selectBtn = h('button', { class: 'btn', type: 'button', disabled: !faces.length, onclick: () => setSelecting(true) }, 'Seç');
    const cancelBtn = h('button', { class: 'btn ghost', type: 'button', onclick: () => setSelecting(false) }, 'Vazgeç');
    const bar = selecting
      ? h('div', { class: 'fr-selbar' }, allBtn, count, h('span', { class: 'spacer' }), delBtn, cancelBtn)
      : null;
    const toggle = f => { sel.has(f.id) ? sel.delete(f.id) : sel.add(f.id); refreshBar(); };
    const crop = f => {
      const img = h('img', { src: fileUrl(f.crop, 160), alt: '', loading: 'lazy', title: f.created_at ? fmtDateTime(f.created_at) : '' });
      const pick = h('button', { class: 'fr-pick', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Seç', onclick: e => { e.stopPropagation(); toggle(f); } });
      const x = h('button', { class: 'fr-crop-x', type: 'button', title: 'Sil', onclick: async e => {
        e.stopPropagation();
        if (!await confirmDialog('Sil', 'Bu eğitim fotoğrafı silinsin mi?', { okLabel: 'Sil', danger: true })) return;
        try { await api.del(`/api/faces/enroll/${f.id}`); drawSubject(); } catch (err) { toastError(err); }
      } }, '×');
      const el = h('div', { class: 'fr-crop', 'data-id': f.id }, img, selecting ? pick : x);
      el.addEventListener('click', () => { if (selecting) toggle(f); });
      // Uzun basma (dokunmatik/fare): seçim kipini açıp bu kırpığı seçer
      let press;
      const startPress = () => { clearTimeout(press); press = setTimeout(() => { if (!selecting) { selecting = true; sel.add(f.id); drawSubject(false); } }, 500); };
      const endPress = () => clearTimeout(press);
      el.addEventListener('pointerdown', startPress);
      ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => el.addEventListener(ev, endPress));
      el.addEventListener('contextmenu', e => { if (selecting) e.preventDefault(); });
      return el;
    };
    const grid = faces.length ? h('div', { class: `fr-crops ${selecting ? 'selecting' : ''}` }, faces.map(crop))
      : h('div', { class: 'muted', style: { padding: '10px 0' } }, 'Henüz eğitim fotoğrafı yok.');
    clear(subjectBox, h('section', { class: 'card card-pad' },
      h('div', { class: 'fr-subject-h' },
        lastAvatar(subject, 'fr-ava-lg'),
        h('div', { class: 'grow' }, h('h3', { style: { margin: 0 } }, nameOf(subject)),
          h('small', { class: 'muted fr-subject-sub' }, [subOf(subject),
            lastFaces[keyOf(subject)] ? t('Son tanınma {when}', { when: fmtDateTime(lastFaces[keyOf(subject)].at) }) : null,
            t('{n} eğitim fotoğrafı', { n: faces.length })].filter(Boolean).join(' · '))),
        selecting ? null : selectBtn, selecting ? null : addBtn, fileInp, status),
      bar,
      selecting ? null : h('p', { class: 'small muted' }, 'Kişinin net, önden çekilmiş fotoğraflarını yükleyin. Her fotoğraftaki en büyük yüz eğitime eklenir; birden çok fotoğraf tanımayı güçlendirir.'),
      grid));
    if (selecting) refreshBar();
  }

  clear(wrap, h('div', { class: 'fr-train' },
    h('section', { class: 'card card-pad fr-list-card' }, kindSeg, q, listBox),
    subjectBox));
  drawList(); drawSubject(); loadLastFaces();
  void ctx;
}

// ---- Olaylar: tarih aralığında tanınan kişi görülmeleri ----
async function renderEvents(wrap, focusDate, focusId) {
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10);
  const dateOk = /^\d{4}-\d{2}-\d{2}$/.test(focusDate || '');   // Eğitim › son tanınma → "Olaya git": o güne odaklan
  const from = h('input', { type: 'date', class: 'input', value: dateOk ? focusDate : weekAgo, max: today });
  const to = h('input', { type: 'date', class: 'input', value: dateOk ? focusDate : today, max: today });
  const kindSel = h('select', { class: 'input' }, h('option', { value: 'known' }, 'Tanınanlar'), h('option', { value: 'all' }, 'Tüm yüzler'));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi, kamera ara…', style: { maxWidth: '200px' } });
  const info = h('span', { class: 'small muted' });
  const out = h('div');
  let rows = [];

  const draw = () => {
    const list = rows.filter(e => matches(q.value, e.user_name, e.person_name, e.person_company, e.family_name, e.visitor_name, e.visitor_company, e.camera_name));
    info.textContent = t('{n} görülme', { n: list.length });
    clear(out, list.length ? h('div', { class: 'fr-events' }, list.map(e => h('button', {
      class: `card fr-ev ${String(e.id) === String(focusId) ? 'focus' : ''}`, type: 'button', onclick: () => showFrame(e),
    },
      h('div', { class: 'fr-ev-img' }, e.crop ? h('img', { src: fileUrl(e.crop, 160), alt: '', loading: 'lazy' }) : null),
      h('div', { class: 'fr-ev-body' },
        h('b', null, e.user_name || e.person_name || e.family_name || e.visitor_name || "Tanımlanamayan",
          (e.person_company || e.visitor_company) ? h('span', { class: 'small muted' }, ` · ${e.person_company || e.visitor_company}`) : null,
          e.visitor_name ? h('span', { class: 'badge', style: { marginLeft: '6px' } }, 'Ziyaretçi') : null),
        h('div', { class: 'small muted' }, e.camera_name || '—'),
        h('div', { class: 'small muted' }, fmtDateTime(e.at), e.threshold != null ? ` · hassasiyet ${e.threshold}` : '')))))
      : h('div', { class: 'card empty' }, 'Bu tarih aralığında görülme yok. Kameralarda yüz tanıma açık olmalı ve kişi eğitilmiş olmalı.'));
  };
  function showFrame(e) {
    const media = e.clip
      ? h('video', { class: 'fr-clip', src: videoUrl(e.clip), controls: true, loop: true, muted: true, playsinline: true, preload: 'metadata' })
      : (e.frame ? h('img', { src: fileUrl(e.frame), alt: '' }) : h('div', { class: 'muted' }, 'Görüntü yok'));
    modal({ title: `${e.user_name || e.person_name || e.family_name || e.visitor_name || "Görülme"} · ${fmtDateTime(e.at)}`, wide: true,
      body: h('div', { class: 'fr-frame' }, media,
        h('div', { class: 'small muted' }, [e.camera_name, e.clip ? 'video' : null].filter(Boolean).join(' · '))),
      actions: [{ label: 'Kapat' }] });
  }
  async function load() {
    info.textContent = 'Yükleniyor…';
    try {
      rows = (await api.get(`/api/faces/events?date_from=${from.value}&date_to=${to.value}&kind=${kindSel.value}`)).events; draw();
      if (focusId) { const el = out.querySelector('.fr-ev.focus'); el?.scrollIntoView({ block: 'center' }); focusId = null; }
    }
    catch (err) { clear(out, h('div', { class: 'card empty' }, err.message)); }
  }
  [from, to, kindSel].forEach(el => el.addEventListener('change', load));
  q.addEventListener('input', draw);

  clear(wrap,
    moduleToolbar(h('span', { class: 'fr-range' }, from, h('span', { class: 'muted' }, '–'), to), kindSel, q),
    h('p', { class: 'small muted' }, 'Yüz verisi ve kayıtlar fabrikada (lokal) tutulur; burada yalnızca seçtiğiniz tarih aralığı görüntülenir.'),
    info, out);
  load();
}
