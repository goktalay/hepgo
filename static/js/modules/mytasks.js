// Görevlerim: Sistem Yöneticisi tarafından bana atanan günlük görevler. "Yaptım" işaretlenene kadar durur;
// zorunlu görevler ana ekranda ayrıca uyarı şeridiyle hatırlatılır. Tek seferlik + her gün tekrarlı görevler.
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
    const mark = async done => {
      try { await api.post(`/api/my/tasks/${it.id}/done`, { date: day, done }); await load(); window.dispatchEvent(new Event('hepgo:tasks-changed')); }
      catch (err) { toastError(err); }
    };
    return h('div', { class: `cl-item ${it.done ? 'done' : ''} ${it.mandatory && !it.done ? 'task-must' : ''}` },
      h('button', { class: 'cl-check', type: 'button', title: it.done ? 'Geri al' : 'Yaptım işaretle', onclick: () => mark(!it.done) }, it.done ? '✓' : ''),
      h('div', { class: 'grow' },
        h('b', null, it.title),
        it.mandatory ? h('span', { class: 'badge red', style: { marginLeft: '8px' } }, 'Zorunlu') : null,
        it.recurring ? h('span', { class: 'small muted', style: { marginLeft: '6px' } }, '· her gün') : null,
        it.note ? h('div', { class: 'small muted' }, it.note) : null,
        h('div', { class: 'small muted' }, it.done ? t('Yapıldı {a}', { a: hm(it.done_at) }) : 'Bekliyor')),
      it.done ? null : h('button', { class: 'btn sm primary', type: 'button', onclick: () => mark(true) }, 'Yaptım'));
  }

  async function load() {
    label.textContent = fmtDay(day);
    let d;
    try { d = await api.get(`/api/my/tasks?date=${day}`); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    if (!d.tasks.length) return clear(body, h('div', { class: 'card empty' }, 'Bu gün için size atanmış görev yok.'));
    clear(body,
      h('div', { class: 'cl-prog' }, t('Bu gün: {a} / {b} görev tamamlandı', { a: d.total - d.pending, b: d.total }),
        d.pending_mandatory ? h('span', { class: 'badge red', style: { marginLeft: '10px' } }, t('{n} zorunlu bekliyor', { n: d.pending_mandatory })) : null),
      h('div', { class: 'cl-list' }, d.tasks.map(row)));
  }

  clear(view, pageHead('Görevlerim', { back: '#/', sub: 'Size atanan günlük görevler' }), bar, body);
  load();
}
