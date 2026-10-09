// Görev Yönetimi (yalnız Sistem Yöneticisi): 4 panelli çalışma ekranı.
// [Personeller] → seçili personelin [Görevler] → seçili görevin [Detay] + [Geçmiş].
// Görev ekleme popup form ile. Görev tipi (Zorunlu/Serbest), tek seferlik (tarih) ya da tekrarlı (haftanın günleri),
// görev saati zorunlu. Geçmişte görevi hangi gün saat kaçta tamamladı / reddetti gösterilir.
import { api } from '../api.js';
import { clear, h, pageHead, svgIcon, t, toast, toastError, confirmDialog } from '../ui.js';
import { icons } from '../icons.js';

const WD = [[1, 'Pzt'], [2, 'Sal'], [3, 'Çar'], [4, 'Per'], [5, 'Cum'], [6, 'Cmt'], [7, 'Paz']];
const today = () => new Date().toLocaleDateString('sv');
const fmtDay = d => { const x = new Date((d || '') + 'T00:00'); return isNaN(x) ? (d || '—') : x.toLocaleDateString('tr', { day: 'numeric', month: 'short', year: 'numeric' }); };
const hm = iso => (iso ? new Date(iso).toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' }) : '');
const wdLabel = csv => (csv ? csv.split(',').map(n => (WD.find(w => String(w[0]) === n.trim()) || [0, n])[1]).join(', ') : 'Her gün');

function panel(title, icon, headRight) {
  const body = h('div', { class: 'tp-body' });
  const foot = h('div', { class: 'tp-foot' }, '—');
  const head = h('div', { class: 'tp-head' }, svgIcon(icons[icon]), h('span', { class: 'tp-title' }, title), h('span', { class: 'spacer' }), headRight || null);
  const el = h('div', { class: 'tp-panel' }, head, body, foot);
  return { el, body, foot, head };
}

export async function render(view) {
  const st = { people: [], tasks: [], selUser: null, selTask: null };

  const pPeople = panel('Personeller', 'users');
  const addBtn = h('button', { class: 'btn sm primary', type: 'button', disabled: true }, '+ Görev Ekle');
  const pTasks = panel('Görevler', 'documents', addBtn);
  const pDetail = panel('Görev Detayı', 'note');
  const pLog = panel('Tamamlama / Red Geçmişi', 'calendar');

  addBtn.addEventListener('click', () => { if (st.selUser) openForm(st.selUser, null); });

  // ---- Panel 1: Personeller ----
  async function loadPeople() {
    try { st.people = await api.get('/api/people'); } catch (err) { return clear(pPeople.body, h('div', { class: 'tp-empty' }, err.message)); }
    clear(pPeople.body, ...st.people.map(p => {
      const ava = p.photo ? h('img', { class: 'tp-ava', src: p.photo, alt: '' })
        : h('span', { class: 'tp-ava tp-ava-ph' }, ((p.full_name || '?').trim()[0] || '?'));
      return h('button', { class: `tp-row tp-prow ${st.selUser === p.id ? 'on' : ''}`, type: 'button', onclick: () => selectUser(p.id) },
        ava,
        h('div', { class: 'tp-prow-txt' },
          h('span', { class: 'tp-name' }, p.full_name),
          h('span', { class: 'small muted tp-mail' }, p.username || '')));
    }));
    pPeople.foot.textContent = t('{n} personel', { n: st.people.length });
  }

  function selectUser(uid) {
    st.selUser = uid; st.selTask = null; addBtn.disabled = false;
    loadPeople(); loadTasks(); clearDetail();
  }

  // ---- Panel 2: Görevler ----
  async function loadTasks() {
    if (!st.selUser) { clear(pTasks.body, h('div', { class: 'tp-empty' }, 'Soldan bir personel seçin.')); pTasks.foot.textContent = '—'; return; }
    try { st.tasks = await api.get(`/api/tasks?user_id=${st.selUser}`); } catch (err) { return clear(pTasks.body, h('div', { class: 'tp-empty' }, err.message)); }
    const who = (st.people.find(p => p.id === st.selUser) || {}).full_name || '';
    if (!st.tasks.length) clear(pTasks.body, h('div', { class: 'tp-empty' }, 'Bu personele görev atanmamış. “+ Görev Ekle” ile ekleyin.'));
    else clear(pTasks.body, ...st.tasks.map(tk => h('button', { class: `tp-row ${st.selTask === tk.id ? 'on' : ''}`, type: 'button', onclick: () => selectTask(tk.id) },
      h('b', null, tk.title),
      h('span', { class: 'tp-row-meta' },
        h('span', { class: `dot ${tk.mandatory ? 'red' : 'gray'}` }),
        tk.task_time ? tk.task_time + ' · ' : '', tk.recurring ? wdLabel(tk.weekdays) : ('Tek: ' + fmtDay(tk.due_day))))));
    pTasks.foot.textContent = t('{n} görev · {who}', { n: st.tasks.length, who });
  }

  function selectTask(id) { st.selTask = id; loadTasks(); loadDetail(id); }

  function clearDetail() {
    clear(pDetail.body, h('div', { class: 'tp-empty' }, 'Bir görev seçin.'));
    clear(pLog.body, h('div', { class: 'tp-empty' }, '—')); pDetail.foot.textContent = '—'; pLog.foot.textContent = '—';
  }

  // ---- Panel 3: Detay + Panel 4: Geçmiş ----
  async function loadDetail(id) {
    const tk = st.tasks.find(x => x.id === id);
    if (!tk) return clearDetail();
    const field = (k, v) => h('div', { class: 'tp-field' }, h('span', { class: 'tp-f-k' }, k), h('span', { class: 'tp-f-v' }, v));
    clear(pDetail.body,
      h('div', { class: 'tp-detail' },
        h('h3', null, tk.title),
        field('Tip', h('span', { class: `badge ${tk.mandatory ? 'red' : 'gray'}` }, tk.mandatory ? 'Zorunlu Görev' : 'Serbest Görev')),
        field('Saat', tk.task_time || '—'),
        field('Tekrar', tk.recurring ? ('Tekrarlı · ' + wdLabel(tk.weekdays)) : ('Tek seferlik · ' + fmtDay(tk.due_day))),
        field('Detay', tk.note || '—'),
        h('div', { class: 'tp-detail-acts' },
          h('button', { class: 'btn sm', type: 'button', onclick: () => openForm(st.selUser, tk) }, 'Düzenle'),
          h('button', { class: 'btn sm danger', type: 'button', onclick: () => removeTask(tk) }, 'Kaldır'))));
    pDetail.foot.textContent = t('Oluşturulma: {d}', { d: fmtDay((tk.created_at || '').slice(0, 10)) });
    // Geçmiş
    clear(pLog.body, h('div', { class: 'loading' }, 'Yükleniyor…'));
    let log;
    try { log = await api.get(`/api/tasks/${id}/log`); } catch (err) { return clear(pLog.body, h('div', { class: 'tp-empty' }, err.message)); }
    if (!log.length) { clear(pLog.body, h('div', { class: 'tp-empty' }, 'Henüz tamamlama/red kaydı yok.')); pLog.foot.textContent = '0 kayıt'; return; }
    clear(pLog.body, ...log.map(r => h('div', { class: `tp-log ${r.status}` },
      h('span', { class: `badge ${r.status === 'done' ? 'green' : 'red'}` }, r.status === 'done' ? 'Yaptı' : 'Reddetti'),
      h('div', { class: 'grow' },
        h('b', null, fmtDay(r.day)), h('span', { class: 'small muted' }, ' · ' + hm(r.done_at)),
        r.reason ? h('div', { class: 'small rej-txt' }, 'Neden: ' + r.reason) : null))));
    const done = log.filter(r => r.status === 'done').length;
    pLog.foot.textContent = t('{d} tamamlandı · {r} reddedildi', { d: done, r: log.length - done });
  }

  async function removeTask(tk) {
    if (!await confirmDialog('Görevi kaldır', t('“{t}” kaldırılsın mı? (geçmiş kayıtlar korunur)', { t: tk.title }), { okLabel: 'Kaldır', danger: true })) return;
    try { await api.del(`/api/tasks/${tk.id}`); st.selTask = null; loadTasks(); clearDetail(); toast('Görev kaldırıldı'); } catch (e) { toastError(e); }
  }

  // ---- Popup form: görev ekle / düzenle ----
  function openForm(userId, existing) {
    const title = h('input', { class: 'input', value: existing?.title || '', placeholder: 'Görev başlığı (zorunlu)' });
    const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Görev detayı (zorunlu)' }, existing?.note || '');
    const mandatory = h('select', { class: 'input' },
      h('option', { value: '1', selected: existing ? !!existing.mandatory : true }, 'Zorunlu Görev'),
      h('option', { value: '0', selected: existing ? !existing.mandatory : false }, 'Serbest Görev'));
    const repeat = h('select', { class: 'input' },
      h('option', { value: '0', selected: existing ? !existing.recurring : true }, 'Tek seferlik (tarih)'),
      h('option', { value: '1', selected: existing ? !!existing.recurring : false }, 'Tekrarlı (haftanın günleri)'));
    const dueDay = h('input', { type: 'date', class: 'input', value: existing?.due_day || today() });
    const taskTime = h('input', { type: 'time', class: 'input', value: existing?.task_time || '09:00' });
    const selDays = new Set((existing?.weekdays || '').split(',').filter(Boolean).map(Number));
    const dayToggles = WD.map(([n, lbl]) => {
      const sw = h('button', { type: 'button', class: `ios-sw ${selDays.has(n) ? 'on' : ''}`, 'aria-pressed': selDays.has(n) ? 'true' : 'false' }, h('i'));
      sw.addEventListener('click', () => { selDays.has(n) ? selDays.delete(n) : selDays.add(n); sw.classList.toggle('on'); });
      return h('label', { class: 'ios-row' }, h('span', null, lbl), sw);
    });
    const daysWrap = h('div', { class: 'ios-days' }, ...dayToggles);
    const dueWrap = h('label', { class: 'tf-field' }, h('span', null, 'Gün'), dueDay);
    const daysField = h('label', { class: 'tf-field' }, h('span', null, 'Haftanın günleri'), daysWrap);
    const syncRepeat = () => { const rec = repeat.value === '1'; dueWrap.hidden = rec; daysField.hidden = !rec; };
    repeat.addEventListener('change', syncRepeat); syncRepeat();

    const err = h('div', { class: 'vx-err' });
    const save = h('button', { class: 'btn primary', type: 'button' }, existing ? 'Kaydet' : 'Görevi Ata');
    save.addEventListener('click', async () => {
      err.textContent = '';
      const payload = {
        user_id: userId, title: title.value.trim(), note: note.value.trim(),
        mandatory: mandatory.value === '1', recurring: repeat.value === '1',
        task_time: taskTime.value, due_day: repeat.value === '1' ? null : dueDay.value,
        weekdays: repeat.value === '1' ? [...selDays] : null,
      };
      if (!payload.title) return (err.textContent = 'Görev başlığı zorunlu');
      if (!payload.note) return (err.textContent = 'Görev detayı zorunlu');
      if (!payload.task_time) return (err.textContent = 'Görev saati zorunlu');
      save.disabled = true;
      try {
        if (existing) await api.put(`/api/tasks/${existing.id}`, payload);
        else await api.post('/api/tasks', payload);
        close(); toast(existing ? 'Görev güncellendi' : 'Görev atandı', 'success');
        loadTasks(); if (existing) loadDetail(existing.id);
      } catch (e) { err.textContent = e.message; save.disabled = false; }
    });

    const box = h('div', { class: 'tf-modal' },
      h('div', { class: 'tf-head' }, h('b', null, existing ? 'Görevi Düzenle' : 'Yeni Görev'), h('button', { class: 'tf-x', type: 'button', onclick: () => close() }, '×')),
      h('div', { class: 'tf-body' },
        h('label', { class: 'tf-field' }, h('span', null, 'Görev Başlığı'), title),
        h('label', { class: 'tf-field' }, h('span', null, 'Görev Detayı'), note),
        h('div', { class: 'tf-grid' },
          h('label', { class: 'tf-field' }, h('span', null, 'Görev Tipi'), mandatory),
          h('label', { class: 'tf-field' }, h('span', null, 'Görev Saati'), taskTime),
          h('label', { class: 'tf-field' }, h('span', null, 'Zamanlama'), repeat),
          dueWrap),
        daysField, err),
      h('div', { class: 'tf-foot' }, save));
    const wrap = h('div', { class: 'tf-wrap', onclick: e => { if (e.target === wrap) close(); } }, box);
    function close() { wrap.remove(); }
    document.body.append(wrap);
    title.focus();
  }

  const col3 = h('div', { class: 'tp-col' }, pDetail.el, pLog.el);   // Detay (üst %50) + Geçmiş (alt %50)
  const grid = h('div', { class: 'tp-grid' }, pPeople.el, pTasks.el, col3);
  clear(view, pageHead('Görev Yönetimi', { back: '#/', sub: 'Kullanıcılara günlük görev atama' }), grid);
  clearDetail();
  loadPeople(); loadTasks();
}
