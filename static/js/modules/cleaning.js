// Temizlik: günlük yapılacak işler çeklisti. Bir işe tıklayınca "yapıldı" saati düşer, açıklama girilebilir.
// Üstte tarih seçilir, geri/ileri gezilebilir. Çeklist maddeleri Program Ayarları › Modül Ayarları › Temizlik'ten düzenlenir.
import { api } from '../api.js';
import { clear, h, pageHead, t, toastError } from '../ui.js';

const today = () => new Date().toLocaleDateString('sv');
const fmtDay = d => { const x = new Date(d + 'T00:00'); return isNaN(x) ? d : x.toLocaleDateString('tr', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }); };
const hm = iso => (iso ? new Date(iso).toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' }) : '');

export async function render(view) {
  let day = today();
  const body = h('div');
  const dateInput = h('input', { type: 'date', class: 'input', value: day });
  dateInput.addEventListener('change', () => { day = dateInput.value || today(); load(); });
  const label = h('b', { class: 'cl-day' });
  const shift = n => { const d = new Date(day + 'T00:00'); d.setDate(d.getDate() + n); day = d.toLocaleDateString('sv'); dateInput.value = day; load(); };
  const bar = h('div', { class: 'cl-bar' },
    h('button', { class: 'btn', type: 'button', title: 'Önceki gün', onclick: () => shift(-1) }, '‹'),
    dateInput,
    h('button', { class: 'btn', type: 'button', title: 'Sonraki gün', onclick: () => shift(1) }, '›'),
    h('button', { class: 'btn', type: 'button', onclick: () => { day = today(); dateInput.value = day; load(); } }, 'Bugün'),
    h('span', { class: 'spacer' }), label);

  function row(it) {
    const note = h('input', { class: 'input cl-note', placeholder: 'Açıklama (isteğe bağlı)', value: it.note || '' });
    const mark = async done => {
      try { await api.post(`/api/cleaning/${it.id}`, { date: day, note: note.value, done }); await load(); }
      catch (err) { toastError(err); }
    };
    return h('div', { class: `cl-item ${it.done_at ? 'done' : ''}` },
      h('button', { class: 'cl-check', type: 'button', title: it.done_at ? 'Geri al' : 'Yapıldı işaretle', onclick: () => mark(!it.done_at) }, it.done_at ? '✓' : ''),
      h('div', { class: 'grow' }, h('b', null, it.label),
        h('div', { class: 'small muted' }, it.done_at ? t('Yapıldı {a} · {b}', { a: hm(it.done_at), b: it.done_by_name || '' }) : 'Bekliyor')),
      note,
      it.done_at ? h('button', { class: 'btn sm', type: 'button', onclick: () => mark(true) }, 'Notu Kaydet') : null);
  }

  async function load() {
    label.textContent = fmtDay(day);
    let d;
    try { d = await api.get(`/api/cleaning?date=${day}`); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    if (!d.items.length) return clear(body, h('div', { class: 'card empty' }, 'Henüz temizlik işi tanımlanmamış. Sistem Yöneticisi, Program Ayarları › Modül Ayarları › Temizlik’ten ekler.'));
    clear(body,
      h('div', { class: 'cl-prog' }, t('Bu gün: {a} / {b} iş tamamlandı', { a: d.done, b: d.total })),
      h('div', { class: 'cl-list' }, d.items.map(row)));
  }

  clear(view, pageHead('Temizlik', { back: '#/', sub: 'Günlük temizlik çeklisti' }), bar, body);
  load();
}
