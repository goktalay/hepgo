// Anket Yönetimi (yalnız Sistem Yöneticisi): anket oluştur/düzenle/sil, kapat-aç, sonuçları gör.
// Her anket: başlık + açıklama + zorunlu/anonim + sorular (metin/tek seçim/çok seçim/puan/evet-hayır).
// Sonuçlar: her soru için dağılım grafiği + metin cevaplar + (anonim değilse) kişi bazlı cevap tablosu.
import { api } from '../api.js';
import { clear, h, pageHead, toast, toastError, confirmDialog } from '../ui.js';

const QTYPES = [['single', 'Tek seçim'], ['multi', 'Çok seçim'], ['yesno', 'Evet / Hayır'], ['rating', 'Puan (1-5)'], ['text', 'Serbest metin']];
const qLabel = t => (QTYPES.find(x => x[0] === t) || [, t])[1];
const fmt = iso => (iso ? new Date(iso).toLocaleString('tr', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');

export async function render(view) {
  clear(view, pageHead('Anket Yönetimi'));
  const bar = h('div', { class: 'toolbar' },
    h('button', { class: 'btn primary', type: 'button', onclick: () => openEditor(view, null) }, '+ Yeni Anket'));
  const list = h('div', { class: 'card' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  view.append(bar, list);
  await reload(view, list);
}

async function reload(view, list) {
  clear(list);
  let data;
  try { data = await api.get('/api/surveys'); } catch { list.append(h('div', { class: 'empty' }, 'Anketler yüklenemedi')); return; }
  if (!data.surveys.length) { list.append(h('div', { class: 'empty' }, 'Henüz anket yok. “+ Yeni Anket” ile oluşturun.')); return; }
  data.surveys.forEach(s => list.append(surveyRow(view, list, s)));
}

function surveyRow(view, list, s) {
  const pct = s.total ? Math.round(s.answered / s.total * 100) : 0;
  const tags = h('div', { class: 'sv-tags' },
    s.active ? h('span', { class: 'badge green' }, 'Aktif') : h('span', { class: 'badge' }, 'Kapalı'),
    s.mandatory ? h('span', { class: 'badge red' }, 'Zorunlu') : h('span', { class: 'badge' }, 'Gönüllü'),
    s.anonymous ? h('span', { class: 'badge teal' }, 'Anonim') : null,
    h('span', { class: 'muted sm' }, `${s.q_count} soru`));
  const prog = h('div', { class: 'sv-prog', title: `${s.answered}/${s.total} personel cevapladı` },
    h('div', { class: 'sv-prog-bar' }, h('i', { style: `width:${pct}%` })),
    h('span', { class: 'sv-prog-txt' }, `${s.answered}/${s.total} · %${pct}`));
  const acts = h('div', { class: 'sv-row-acts' },
    h('button', { class: 'btn sm primary', type: 'button', onclick: () => openResults(view, s.id) }, 'Sonuçlar'),
    h('button', { class: 'btn sm', type: 'button', onclick: () => openEditor(view, s.id) }, 'Düzenle'),
    h('button', {
      class: 'btn sm', type: 'button',
      onclick: async () => { await api.post(`/api/surveys/${s.id}/${s.active ? 'close' : 'reopen'}`); toast(s.active ? 'Kapatıldı' : 'Açıldı'); reload(view, list); },
    }, s.active ? 'Kapat' : 'Aç'),
    h('button', {
      class: 'btn sm danger', type: 'button',
      onclick: async () => { if (await confirmDialog('Anket silinsin mi?', `“${s.title}” ve tüm cevapları silinecek.`, { danger: true })) { await api.del(`/api/surveys/${s.id}`); toast('Silindi'); reload(view, list); } },
    }, 'Sil'));
  return h('div', { class: 'sv-adminrow' },
    h('div', { class: 'sv-adminrow-main' }, h('b', null, s.title), s.description ? h('p', { class: 'muted sm' }, s.description) : null, tags, prog), acts);
}

// ---------- Oluştur / Düzenle ----------
async function openEditor(view, id) {
  let survey = { title: '', description: '', mandatory: true, anonymous: false, active: true, questions: [], locked: false };
  if (id) {
    try { survey = await api.get(`/api/surveys/${id}`); } catch { toastError('Anket yüklenemedi'); return; }
  }
  const body = h('div', { class: 'sv-editor' });
  const title = inputRow('Anket başlığı', survey.title, 'text');
  const desc = h('textarea', { class: 'sv-input', rows: 2, placeholder: 'Açıklama (isteğe bağlı)' }); desc.value = survey.description || '';
  const mand = toggle('Zorunlu (tüm personel cevaplamalı)', survey.mandatory);
  const anon = toggle('Anonim (kimin cevapladığı görünmez)', survey.anonymous);
  const qWrap = h('div', { class: 'sv-qlist' });
  const addBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => qWrap.append(questionRow({})) }, '+ Soru ekle');
  (survey.questions || []).forEach(q => qWrap.append(questionRow(q)));
  if (!survey.questions?.length) qWrap.append(questionRow({}));

  body.append(
    h('label', { class: 'sv-lbl' }, 'Başlık', title),
    h('label', { class: 'sv-lbl' }, 'Açıklama', desc),
    h('div', { class: 'sv-flags' }, mand.el, anon.el),
    survey.locked ? h('div', { class: 'sv-warn' }, '⚠️ Bu ankete cevap gelmiş; sorular değiştirilemez (başlık/zorunluluk güncellenebilir).') : null,
    h('div', { class: 'sv-lbl' }, 'Sorular', qWrap, addBtn));

  modal(id ? 'Anketi Düzenle' : 'Yeni Anket', body, async () => {
    const questions = [...qWrap.querySelectorAll('.sv-qrow')].map(readQuestion).filter(Boolean);
    if (!title.value.trim()) { toastError('Başlık zorunlu'); return false; }
    if (!questions.length) { toastError('En az bir soru ekleyin'); return false; }
    const payload = { title: title.value.trim(), description: desc.value.trim(), mandatory: mand.get(), anonymous: anon.get(), active: survey.active !== false, questions };
    try {
      if (id) await api.put(`/api/surveys/${id}`, payload);
      else await api.post('/api/surveys', payload);
      toast('Kaydedildi');
      return true;
    } catch (e) { toastError(e.message || 'Kaydedilemedi'); return false; }
  }, () => { const v = view; const list = v.querySelector('.card'); if (list) reload(v, list); });
}

function questionRow(q) {
  const row = h('div', { class: 'sv-qrow' });
  const text = h('input', { class: 'sv-input', type: 'text', placeholder: 'Soru metni', value: q.text || '' });
  const type = h('select', { class: 'sv-input sv-qtype' }, ...QTYPES.map(([v, l]) => h('option', { value: v, selected: (q.qtype || 'single') === v }, l)));
  const req = toggle('Zorunlu', q.required !== false);
  const opts = h('textarea', { class: 'sv-input sv-opts-edit', rows: 3, placeholder: 'Seçenekler (her satıra bir seçenek)' });
  opts.value = (q.options || []).join('\n');
  const optWrap = h('div', { class: 'sv-optwrap' }, h('span', { class: 'muted sm' }, 'Seçenekler (her satıra bir tane):'), opts);
  const syncOpts = () => { optWrap.style.display = (type.value === 'single' || type.value === 'multi') ? '' : 'none'; };
  type.onchange = syncOpts; syncOpts();
  const del = h('button', { class: 'btn sm danger', type: 'button', title: 'Soruyu sil', onclick: () => row.remove() }, '✕');
  row.append(h('div', { class: 'sv-qrow-top' }, text, type, req.el, del), optWrap);
  return row;
}

function readQuestion(row) {
  const text = row.querySelector('input[type=text]').value.trim();
  if (!text) return null;
  const qtype = row.querySelector('.sv-qtype').value;
  const required = row.querySelector('.ios-sw')?.classList.contains('on');
  let options = null;
  if (qtype === 'single' || qtype === 'multi') {
    options = row.querySelector('.sv-opts-edit').value.split('\n').map(s => s.trim()).filter(Boolean);
  }
  return { text, qtype, options, required };
}

// ---------- Sonuçlar ----------
async function openResults(view, id) {
  let r;
  try { r = await api.get(`/api/surveys/${id}/results`); } catch { toastError('Sonuçlar yüklenemedi'); return; }
  const body = h('div', { class: 'sv-results' });
  body.append(h('div', { class: 'sv-res-top' },
    h('span', { class: 'badge green' }, `${r.answered}/${r.total_staff} cevap`),
    r.mandatory ? h('span', { class: 'badge red' }, 'Zorunlu') : null,
    r.anonymous ? h('span', { class: 'badge teal' }, 'Anonim') : null,
    r.active ? null : h('span', { class: 'badge' }, 'Kapalı')));

  r.summary.forEach((q, i) => {
    const qb = h('div', { class: 'sv-resq' }, h('div', { class: 'sv-resq-head' }, h('span', { class: 'sv-q-no' }, i + 1), h('b', null, q.text), h('span', { class: 'muted sm' }, qLabel(q.qtype))));
    if (q.counts) {
      const max = Math.max(1, ...q.counts.map(c => c.count));
      q.counts.forEach(c => qb.append(h('div', { class: 'sv-barrow' },
        h('span', { class: 'sv-barlbl' }, c.option),
        h('div', { class: 'sv-bar' }, h('i', { style: `width:${Math.round(c.count / max * 100)}%` })),
        h('span', { class: 'sv-barn' }, c.count))));
    } else {   // text
      if (!q.texts || !q.texts.length) qb.append(h('p', { class: 'muted sm' }, 'Cevap yok'));
      (q.texts || []).forEach(tx => qb.append(h('div', { class: 'sv-textans' }, tx.name ? h('b', null, tx.name + ': ') : null, h('span', null, tx.value))));
    }
    body.append(qb);
  });

  if (!r.anonymous && r.people.length) {
    const det = h('details', { class: 'sv-people' }, h('summary', null, `Kişi bazlı cevaplar (${r.people.length})`));
    r.people.forEach(p => {
      const pc = h('div', { class: 'sv-person' }, h('div', { class: 'sv-person-h' }, h('b', null, p.name), h('span', { class: 'muted sm' }, fmt(p.submitted_at))));
      p.answers.forEach(a => pc.append(h('div', { class: 'sv-person-a' }, h('span', { class: 'muted sm' }, a.q), h('span', null, a.value || '—'))));
      det.append(pc);
    });
    body.append(det);
  }
  modal(`Sonuçlar — ${r.title}`, body, null, null, true);
}

// ---------- Küçük yardımcılar ----------
function inputRow(ph, val, type) { return h('input', { class: 'sv-input', type: type || 'text', placeholder: ph, value: val || '' }); }

function toggle(label, on) {
  const sw = h('button', { class: 'ios-sw' + (on ? ' on' : ''), type: 'button', role: 'switch' }, h('i'));
  sw.onclick = () => sw.classList.toggle('on');
  const el = h('label', { class: 'sv-toggle' }, sw, h('span', null, label));
  return { el, get: () => sw.classList.contains('on') };
}

function modal(title, body, onSave, onClose, readonly) {
  const ov = h('div', { class: 'sv-modal-ov' });
  const close = () => { ov.remove(); onClose && onClose(); };
  const foot = readonly
    ? h('div', { class: 'sv-modal-foot' }, h('button', { class: 'btn', type: 'button', onclick: close }, 'Kapat'))
    : h('div', { class: 'sv-modal-foot' },
      h('button', { class: 'btn', type: 'button', onclick: close }, 'İptal'),
      h('button', { class: 'btn primary', type: 'button', onclick: async (e) => { const b = e.currentTarget; b.disabled = true; const ok = await onSave(); if (ok) close(); else b.disabled = false; } }, 'Kaydet'));
  const card = h('div', { class: 'sv-modal' }, h('div', { class: 'sv-modal-head' }, h('b', null, title), h('button', { class: 'sv-modal-x', type: 'button', onclick: close }, '✕')), h('div', { class: 'sv-modal-body' }, body), foot);
  ov.append(card);
  ov.onclick = e => { if (e.target === ov) close(); };
  document.body.append(ov);
}
