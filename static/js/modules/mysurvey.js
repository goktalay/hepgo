// Anketlerim (personel): aktif anketleri listeler, zorunlu olanları üstte işaretler; ankete tıklayınca
// soruları doldurup gönderir. Cevaplanan anket salt-okunur gösterilir. Gönderince uyarı şeridi güncellenir.
import { api } from '../api.js';
import { clear, h, pageHead, toast, toastError } from '../ui.js';

const RATE = ['1', '2', '3', '4', '5'];
const fmt = iso => (iso ? new Date(iso).toLocaleString('tr', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');

export async function render(host, params) {
  const id = (typeof params === 'string' && /^\d+$/.test(params)) ? +params : null;
  if (id) return openSurvey(host, id);
  clear(host, pageHead('Anketlerim'));
  const list = h('div', { class: 'card' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  host.append(list);
  let data;
  try { data = await api.get('/api/my/surveys'); } catch { clear(list, h('div', { class: 'empty' }, 'Anketler yüklenemedi')); return; }
  renderList(host, list, data.surveys || []);
}

function renderList(host, list, surveys) {
  clear(list);
  if (!surveys.length) { list.append(h('div', { class: 'empty' }, 'Şu an cevaplanacak anket yok.')); return; }
  const pending = surveys.filter(s => !s.answered);
  const done = surveys.filter(s => s.answered);
  if (pending.length) list.append(h('div', { class: 'sv-sec' }, 'Bekleyen anketler'));
  pending.forEach(s => list.append(card(host, s)));
  if (done.length) { list.append(h('div', { class: 'sv-sec muted' }, 'Cevaplananlar')); done.forEach(s => list.append(card(host, s))); }
}

function card(host, s) {
  const tags = h('div', { class: 'sv-tags' },
    s.mandatory ? h('span', { class: 'badge red' }, 'Zorunlu') : h('span', { class: 'badge' }, 'Gönüllü'),
    s.anonymous ? h('span', { class: 'badge teal' }, 'Anonim') : null,
    h('span', { class: 'muted sm' }, `${s.q_count} soru`));
  const action = s.answered
    ? h('span', { class: 'sv-done' }, '✓ Cevaplandı')
    : h('button', { class: 'btn sm primary', type: 'button', onclick: () => openSurvey(host, s.id) }, 'Cevapla');
  return h('button', {
    class: 'sv-card' + (s.answered ? ' answered' : ''), type: 'button',
    onclick: () => openSurvey(host, s.id),
  }, h('div', { class: 'sv-card-main' }, h('b', null, s.title), s.description ? h('p', { class: 'muted sm' }, s.description) : null, tags), action);
}

async function openSurvey(host, id) {
  clear(host, pageHead('Anket', { back: '#/my-surveys' }));
  const wrap = h('div', { class: 'card' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  host.append(wrap);
  let s;
  try { s = await api.get(`/api/my/surveys/${id}`); } catch { clear(wrap, h('div', { class: 'empty' }, 'Anket bulunamadı')); return; }
  clear(wrap);
  wrap.append(h('h2', { class: 'sv-title' }, s.title));
  if (s.description) wrap.append(h('p', { class: 'muted' }, s.description));
  const ro = s.answered;   // salt-okunur
  if (ro) wrap.append(h('div', { class: 'sv-answered-note' }, `✓ Bu anketi ${fmt(s.submitted_at)} tarihinde cevapladınız.`));

  const controls = {};   // question_id -> getValue()
  const form = h('div', { class: 'sv-form' });
  s.questions.forEach((q, i) => form.append(questionEl(q, i, s.my_answers[q.id], ro, controls)));
  wrap.append(form);

  if (!ro) {
    const btn = h('button', { class: 'btn primary', type: 'button' }, 'Gönder');
    btn.onclick = async () => {
      const answers = {};
      for (const q of s.questions) {
        const v = controls[q.id] ? controls[q.id]() : null;
        if (q.required && (v == null || v === '' || (Array.isArray(v) && !v.length))) {
          toastError(`Zorunlu soru boş: ${q.text}`); return;
        }
        answers[q.id] = v;
      }
      btn.disabled = true; btn.textContent = 'Gönderiliyor…';
      try {
        await api.post(`/api/my/surveys/${id}/submit`, { answers });
        toast('Anket gönderildi, teşekkürler');
        window.dispatchEvent(new CustomEvent('hepgo:surveys-changed'));
        location.hash = '#/my-surveys';
      } catch (e) { toastError(e.message || 'Gönderilemedi'); btn.disabled = false; btn.textContent = 'Gönder'; }
    };
    wrap.append(h('div', { class: 'sv-submit' }, btn));
  }
}

function questionEl(q, i, myVal, ro, controls) {
  const box = h('div', { class: 'sv-q' });
  box.append(h('div', { class: 'sv-q-head' }, h('span', { class: 'sv-q-no' }, i + 1), h('b', null, q.text), q.required ? h('span', { class: 'req' }, '*') : null));
  const body = h('div', { class: 'sv-q-body' });
  box.append(body);
  const name = `q${q.id}`;

  if (q.qtype === 'text') {
    const ta = h('textarea', { class: 'sv-input', rows: 3, placeholder: 'Cevabınız…', disabled: ro });
    if (myVal) ta.value = myVal;
    body.append(ta); controls[q.id] = () => ta.value.trim();

  } else if (q.qtype === 'rating') {
    const pick = { v: myVal || '' };
    const stars = h('div', { class: 'sv-rate' });
    RATE.forEach(n => {
      const b = h('button', { class: 'sv-star' + (myVal && +myVal >= +n ? ' on' : ''), type: 'button', disabled: ro }, '★');
      b.onclick = () => { pick.v = n; [...stars.children].forEach((c, idx) => c.classList.toggle('on', idx < +n)); };
      stars.append(b);
    });
    body.append(stars); controls[q.id] = () => pick.v;

  } else if (q.qtype === 'yesno') {
    const pick = { v: myVal || '' };
    const row = h('div', { class: 'sv-opts' });
    ['Evet', 'Hayır'].forEach(o => {
      const b = h('button', { class: 'sv-opt' + (myVal === o ? ' on' : ''), type: 'button', disabled: ro }, o);
      b.onclick = () => { pick.v = o; [...row.children].forEach(c => c.classList.toggle('on', c === b)); };
      row.append(b);
    });
    body.append(row); controls[q.id] = () => pick.v;

  } else if (q.qtype === 'single') {
    const pick = { v: myVal || '' };
    const row = h('div', { class: 'sv-opts col' });
    (q.options || []).forEach(o => {
      const b = h('button', { class: 'sv-opt' + (myVal === o ? ' on' : ''), type: 'button', disabled: ro }, o);
      b.onclick = () => { pick.v = o; [...row.children].forEach(c => c.classList.toggle('on', c === b)); };
      row.append(b);
    });
    body.append(row); controls[q.id] = () => pick.v;

  } else {   // multi
    const sel = new Set(Array.isArray(myVal) ? myVal : (myVal ? tryArr(myVal) : []));
    const row = h('div', { class: 'sv-opts col' });
    (q.options || []).forEach(o => {
      const b = h('button', { class: 'sv-opt multi' + (sel.has(o) ? ' on' : ''), type: 'button', disabled: ro }, h('span', { class: 'cb' }), o);
      b.onclick = () => { if (sel.has(o)) sel.delete(o); else sel.add(o); b.classList.toggle('on', sel.has(o)); };
      row.append(b);
    });
    body.append(row); controls[q.id] = () => [...sel];
  }
  return box;
}

function tryArr(s) { try { return JSON.parse(s); } catch { return []; } }
