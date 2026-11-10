// Görevlerim: bana atanan günlük görevler. "Yaptım" ya da "Reddet" (neden) işaretlenir; yapılana/reddedilene
// kadar bekler. Zorunlu görevler ana ekranda ayrıca uyarı şeridiyle hatırlatılır. Tek seferlik + tekrarlı (haftanın günleri).
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
  const bar = h('div', { class: 'filters cl-bar' },
    h('button', { class: 'btn cl-nav', type: 'button', title: 'Önceki gün', onclick: () => shift(-1) }, '‹'),
    dateInput,
    h('button', { class: 'btn cl-nav', type: 'button', title: 'Sonraki gün', onclick: () => shift(1) }, '›'),
    h('button', { class: 'btn', type: 'button', onclick: () => { day = today(); dateInput.value = day; load(); } }, 'Bugün'),
    h('span', { class: 'spacer' }), label);

  const act = async (it, action, reason) => {
    try { await api.post(`/api/my/tasks/${it.id}/action`, { date: day, action, reason }); await load(); window.dispatchEvent(new Event('hepgo:tasks-changed')); }
    catch (err) { toastError(err); }
  };

  function row(it) {
    const stateLine = it.done ? t('Yaptım · {a}', { a: hm(it.at) })
      : it.rejected ? t('Reddedildi · {a}{r}', { a: hm(it.at), r: it.reason ? ' · ' + it.reason : '' })
        : 'Bekliyor';
    return h('div', { class: `cl-item ${it.done ? 'done' : ''} ${it.rejected ? 'rejected' : ''} ${it.mandatory && !it.status ? 'task-must' : ''}` },
      h('button', { class: 'cl-check', type: 'button', title: it.status ? 'Geri al' : (it.done ? 'Yapıldı' : ''), onclick: () => it.status && act(it, 'undo') }, it.done ? '✓' : (it.rejected ? '✕' : '')),
      h('div', { class: 'grow' },
        h('b', null, it.title),
        it.task_time ? h('span', { class: 'badge blue', style: { marginLeft: '8px' } }, '🕑 ' + it.task_time) : null,
        h('span', { class: `badge ${it.mandatory ? 'red' : 'gray'}`, style: { marginLeft: '6px' } }, it.mandatory ? 'Zorunlu' : 'Serbest'),
        it.note ? h('div', { class: 'small muted' }, it.note) : null,
        h('div', { class: `small ${it.rejected ? 'rej-txt' : 'muted'}` }, stateLine)),
      it.status ? null : h('div', { class: 'cl-acts' },
        h('button', { class: 'btn sm primary', type: 'button', onclick: () => act(it, 'done') }, 'Yaptım'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: () => { const r = window.prompt('Reddetme nedeni (isteğe bağlı):', ''); if (r !== null) act(it, 'reject', r.trim()); } }, 'Reddet')));
  }

  async function load() {
    label.textContent = fmtDay(day);
    let d;
    try { d = await api.get(`/api/my/tasks?date=${day}`); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    if (!d.tasks.length) return clear(body, h('div', { class: 'card empty' }, 'Bu gün için size atanmış görev yok.'));
    clear(body,
      h('div', { class: 'cl-prog' }, t('Bu gün: {a} / {b} görev tamamlandı', { a: d.done, b: d.total }),
        d.pending_mandatory ? h('span', { class: 'badge red', style: { marginLeft: '10px' } }, t('{n} zorunlu bekliyor', { n: d.pending_mandatory })) : null),
      h('div', { class: 'cl-list' }, d.tasks.map(row)));
  }

  clear(view, pageHead('Görevlerim', { back: '#/', sub: 'Size atanan günlük görevler' }), bar, body);
  load();
}
