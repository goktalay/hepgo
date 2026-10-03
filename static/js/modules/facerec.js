// Güvenlik → Yüz Tanıma: (1) Eğitim — bir kişi için fotoğraf yükleyip yüzünü eğit; (2) Olaylar — seçilen tarih
// aralığında kameralarda tanınan kişilerin görülmeleri. Yüz verisi ve kayıtlar fabrikada (lokal) tutulur; buluta taşınmaz.
import { api, fileUrl } from '../api.js';
import { clear, confirmDialog, fmtDateTime, h, matches, modal, moduleToolbar, segmented, t, toast, toastError } from '../ui.js';

export async function renderFaceRec(body, ctx, params) {
  const sub = ['train', 'events'].includes(params[0]) ? params[0] : 'train';
  const nav = segmented([['train', 'Eğitim'], ['events', 'Olaylar']], sub,
    v => { location.hash = `#/cameras/facerec/${v}`; }, { tabs: true });
  const inner = h('div');
  clear(body, moduleToolbar(nav), inner);
  if (sub === 'events') return renderEvents(inner);
  return renderTrain(inner);
}

// ---- Eğitim: kişi seç + fotoğraf yükle → yüz eğitilsin ----
async function renderTrain(wrap) {
  clear(wrap, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let people;
  try { people = await api.get('/api/faces/people'); }
  catch (err) { return clear(wrap, h('div', { class: 'card empty' }, err.message)); }

  let kind = 'user';           // 'user' = personel, 'person' = firma kişisi
  let subject = null;          // seçili kişi
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara…', style: { maxWidth: '260px' } });
  const kindSeg = segmented([['user', 'Personel'], ['person', 'Firma Kişisi']], kind,
    v => { kind = v; subject = null; drawList(); drawSubject(); });
  const listBox = h('div', { class: 'fr-people' });
  const subjectBox = h('div', { class: 'fr-subject' });

  const source = () => (kind === 'user' ? people.users : people.people);
  const nameOf = p => p.full_name;
  const subOf = p => (kind === 'user' ? '' : [p.title, p.company_name].filter(Boolean).join(' · '));

  const drawList = () => {
    const list = source().filter(p => matches(q.value, p.full_name, p.title, p.company_name));
    clear(listBox, list.length ? list.map(p => h('button', {
      class: `fr-person ${subject && subject.id === p.id ? 'on' : ''}`, type: 'button',
      onclick: () => { subject = p; drawList(); drawSubject(); },
    }, h('b', null, nameOf(p)), subOf(p) ? h('small', { class: 'muted' }, subOf(p)) : null))
      : h('div', { class: 'muted', style: { padding: '10px' } }, 'Kişi bulunamadı.'));
  };
  q.addEventListener('input', drawList);

  async function drawSubject() {
    if (!subject) return clear(subjectBox, h('div', { class: 'card empty' }, 'Eğitmek için soldan bir kişi seçin.'));
    clear(subjectBox, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
    let faces = [];
    try { faces = (await api.get(`/api/faces/enroll?subject_type=${kind}&${kind}_id=${subject.id}`)).faces; } catch { /* */ }
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
    clear(subjectBox, h('section', { class: 'card card-pad' },
      h('div', { class: 'fr-subject-h' },
        h('div', { class: 'grow' }, h('h3', { style: { margin: 0 } }, nameOf(subject)),
          subOf(subject) ? h('small', { class: 'muted' }, subOf(subject)) : null),
        addBtn, fileInp, status),
      h('p', { class: 'small muted' }, 'Kişinin net, önden çekilmiş fotoğraflarını yükleyin. Her fotoğraftaki en büyük yüz eğitime eklenir; birden çok fotoğraf tanımayı güçlendirir.'),
      faces.length ? h('div', { class: 'fr-crops' }, faces.map(f => h('div', { class: 'fr-crop' },
        h('img', { src: fileUrl(f.crop, 160), alt: '', loading: 'lazy' }),
        h('button', { class: 'fr-crop-x', type: 'button', title: 'Sil', onclick: async () => {
          if (!await confirmDialog('Sil', 'Bu eğitim fotoğrafı silinsin mi?', { okLabel: 'Sil', danger: true })) return;
          try { await api.del(`/api/faces/enroll/${f.id}`); drawSubject(); } catch (err) { toastError(err); }
        } }, '×'))))
        : h('div', { class: 'muted', style: { padding: '10px 0' } }, 'Henüz eğitim fotoğrafı yok.')));
  }

  clear(wrap, h('div', { class: 'fr-train' },
    h('section', { class: 'card card-pad fr-list-card' }, kindSeg, q, listBox),
    subjectBox));
  drawList(); drawSubject();
}

// ---- Olaylar: tarih aralığında tanınan kişi görülmeleri ----
async function renderEvents(wrap) {
  const today = new Date().toISOString().slice(0, 10);
  const weekAgo = new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10);
  const from = h('input', { type: 'date', class: 'input', value: weekAgo, max: today });
  const to = h('input', { type: 'date', class: 'input', value: today, max: today });
  const kindSel = h('select', { class: 'input' }, h('option', { value: 'known' }, 'Tanınanlar'), h('option', { value: 'all' }, 'Tüm yüzler'));
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi, kamera ara…', style: { maxWidth: '200px' } });
  const info = h('span', { class: 'small muted' });
  const out = h('div');
  let rows = [];

  const draw = () => {
    const list = rows.filter(e => matches(q.value, e.user_name, e.person_name, e.person_company, e.camera_name));
    info.textContent = t('{n} görülme', { n: list.length });
    clear(out, list.length ? h('div', { class: 'fr-events' }, list.map(e => h('button', {
      class: 'card fr-ev', type: 'button', onclick: () => showFrame(e),
    },
      h('div', { class: 'fr-ev-img' }, e.crop ? h('img', { src: fileUrl(e.crop, 160), alt: '', loading: 'lazy' }) : null),
      h('div', { class: 'fr-ev-body' },
        h('b', null, e.user_name || e.person_name || 'Tanımlanamayan',
          e.person_company ? h('span', { class: 'small muted' }, ` · ${e.person_company}`) : null),
        h('div', { class: 'small muted' }, e.camera_name || '—'),
        h('div', { class: 'small muted' }, fmtDateTime(e.at))))))
      : h('div', { class: 'card empty' }, 'Bu tarih aralığında görülme yok. Kameralarda yüz tanıma açık olmalı ve kişi eğitilmiş olmalı.'));
  };
  function showFrame(e) {
    const media = e.clip
      ? h('video', { class: 'fr-clip', src: fileUrl(e.clip), controls: true, autoplay: true, loop: true, muted: true, playsinline: true })
      : (e.frame ? h('img', { src: fileUrl(e.frame), alt: '' }) : h('div', { class: 'muted' }, 'Görüntü yok'));
    modal({ title: `${e.user_name || e.person_name || 'Görülme'} · ${fmtDateTime(e.at)}`, wide: true,
      body: h('div', { class: 'fr-frame' }, media,
        h('div', { class: 'small muted' }, [e.camera_name, e.clip ? 'video' : null].filter(Boolean).join(' · '))),
      actions: [{ label: 'Kapat' }] });
  }
  async function load() {
    info.textContent = 'Yükleniyor…';
    try { rows = (await api.get(`/api/faces/events?date_from=${from.value}&date_to=${to.value}&kind=${kindSel.value}`)).events; draw(); }
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
