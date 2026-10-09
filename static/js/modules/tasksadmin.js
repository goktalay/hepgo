// Görev Yönetimi (yalnız Sistem Yöneticisi): kullanıcılara günlük görev atama. Tek seferlik veya her gün tekrarlı;
// zorunlu işaretlenen görev, atanan kişinin ana ekranında uyarı şeridiyle "yaptım" diyene kadar durur.
import { api } from '../api.js';
import { clear, h, pageHead, t, toast, toastError, confirmDialog } from '../ui.js';

const today = () => new Date().toLocaleDateString('sv');

export async function render(view) {
  const body = h('div');

  async function load() {
    let people, tasks;
    try { [people, tasks] = await Promise.all([api.get('/api/people'), api.get('/api/tasks')]); }
    catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }

    const who = h('select', { class: 'input' }, h('option', { value: '' }, 'Kişi seçin…'), ...people.map(p => h('option', { value: String(p.id) }, p.full_name)));
    const title = h('input', { class: 'input', placeholder: 'Görev (ör. Saat 09:00 vardiya raporu)' });
    const note = h('textarea', { class: 'input', rows: 2, placeholder: 'Açıklama (isteğe bağlı)' });
    const mandatory = h('input', { type: 'checkbox' });
    const recurring = h('select', { class: 'input' }, h('option', { value: '0' }, 'Tek seferlik (belirli gün)'), h('option', { value: '1' }, 'Her gün tekrar eder'));
    const dueDay = h('input', { type: 'date', class: 'input', value: today() });
    recurring.addEventListener('change', () => { dueDay.disabled = recurring.value === '1'; });

    const fld = (lbl, el) => h('label', { class: 'sc-field' }, h('span', { class: 'sc-f-label' }, lbl), el);
    const add = async () => {
      if (!who.value) return toast('Kişi seçin');
      if (!title.value.trim()) return toast('Görev başlığı girin');
      try {
        await api.post('/api/tasks', {
          user_id: Number(who.value), title: title.value.trim(), note: note.value.trim() || null,
          mandatory: mandatory.checked, recurring: recurring.value === '1',
          due_day: recurring.value === '1' ? null : (dueDay.value || today()),
        });
        title.value = ''; note.value = ''; mandatory.checked = false;
        toast('Görev atandı', 'success'); load();
      } catch (err) { toastError(err); }
    };

    const taskRow = tk => h('div', { class: 'cl-set-row' },
      h('div', { class: 'grow' },
        h('b', null, tk.title), h('span', { class: 'small muted', style: { marginLeft: '8px' } }, '→ ' + tk.user_name),
        tk.mandatory ? h('span', { class: 'badge red', style: { marginLeft: '6px' } }, 'Zorunlu') : null,
        h('span', { class: 'small muted', style: { marginLeft: '6px' } }, tk.recurring ? '· her gün' : ('· ' + (tk.due_day || '')))),
      h('button', {
        class: 'btn sm danger', type: 'button', title: 'Kaldır',
        onclick: async () => { if (await confirmDialog('Görevi kaldır', t('“{t}” kaldırılsın mı?', { t: tk.title }), { okLabel: 'Kaldır', danger: true })) { try { await api.del(`/api/tasks/${tk.id}`); load(); } catch (e) { toastError(e); } } },
      }, '×'));

    clear(body,
      h('section', { class: 'card card-pad' },
        h('h3', { style: { marginTop: 0 } }, 'Yeni Görev Ata'),
        h('div', { class: 'sc-grid' },
          fld('Kişi', who),
          fld('Görev', title),
          fld('Tekrar', recurring),
          fld('Gün (tek seferlik için)', dueDay)),
        fld('Açıklama', note),
        h('label', { class: 'gx-check', style: { margin: '10px 0' } }, mandatory, h('span', null, 'Zorunlu (atanan kişinin ana ekranında “yaptım” diyene kadar uyarı şeridi gösterilir)')),
        h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Görevi Ata')),
      h('section', { class: 'card card-pad' },
        h('h3', { style: { marginTop: 0 } }, 'Atanmış Görevler'),
        tasks.length ? h('div', { class: 'cl-set-list' }, tasks.map(taskRow)) : h('div', { class: 'muted', style: { margin: '8px 0' } }, 'Henüz görev atanmadı.')));
  }

  clear(view, pageHead('Görev Yönetimi', { back: '#/', sub: 'Kullanıcılara günlük görev atama' }), body);
  load();
}
