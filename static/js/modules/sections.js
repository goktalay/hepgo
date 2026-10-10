// Bölümler (esnaf): berber/kuaförde odalar (Kadın, Erkek, VIP…), lokantada salonlar/katlar + masalar.
// Paket (ctx.meta.esnaf_pkg) lokanta ise her bölüme masa (ad, şekil, kişi kapasitesi, sorumlu garson) eklenir.
import { api } from '../api.js';
import { clear, confirmDialog, h, modal, pageHead, toast, toastError } from '../ui.js';

export async function render(view, params, ctx) {
  const lokanta = (ctx?.meta?.esnaf_pkg || '') === 'lokanta';
  let sections = [], people = [];
  const body = h('div', { class: 'shop-sec-wrap' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => editSection() }, '＋ Bölüm');
  clear(view, pageHead('Bölümler', { back: '#/', sub: lokanta ? 'Salonlar ve masalar' : 'Çalışma bölümleri / odalar' }),
    h('div', { class: 'filters' }, h('div', { class: 'spacer' }), addBtn), body);

  const load = async () => {
    try { sections = await api.get('/api/sections'); } catch (e) { clear(body, h('div', { class: 'card empty' }, e.message)); return; }
    if (lokanta && !people.length) { try { people = await api.get('/api/people'); } catch { /* */ } }
    draw();
  };

  function draw() {
    clear(body);
    if (!sections.length) { body.append(h('div', { class: 'card empty' }, 'Henüz bölüm yok. “＋ Bölüm” ile ekleyin.')); return; }
    sections.forEach(s => {
      const head = h('div', { class: 'shop-sec-h' },
        h('b', null, s.name),
        s.kind === 'hall' ? h('span', { class: 'chip' }, 'Salon') : h('span', { class: 'chip' }, 'Oda'),
        s.smoking ? h('span', { class: 'chip warn' }, '🚬 Sigara') : null,
        h('span', { class: 'spacer' }),
        lokanta ? h('button', { class: 'btn sm', type: 'button', onclick: () => editTable(s) }, '＋ Masa') : null,
        h('button', { class: 'btn sm', type: 'button', onclick: () => editSection(s) }, 'Düzenle'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: () => delSection(s) }, 'Sil'));
      const card = h('div', { class: 'card shop-sec' }, head);
      if (lokanta) {
        const tbls = s.tables || [];
        card.append(tbls.length
          ? h('div', { class: 'shop-tbls' }, tbls.map(t => h('div', { class: 'shop-tbl-chip ' + (t.shape === 'round' ? 'round' : '') },
              h('b', null, t.name), h('small', null, `${t.seats} kişi`),
              h('div', { class: 'shop-tbl-acts' },
                h('button', { class: 'mini', type: 'button', title: 'Düzenle', onclick: () => editTable(s, t) }, '✎'),
                h('button', { class: 'mini', type: 'button', title: 'Sil', onclick: () => delTable(t) }, '×')))))
          : h('div', { class: 'muted small', style: 'padding:6px 2px' }, 'Masa yok'));
      }
      body.append(card);
    });
  }

  function editSection(s) {
    const name = h('input', { class: 'input', placeholder: 'Bölüm adı', value: s?.name || '' });
    const kind = h('select', { class: 'input' },
      h('option', { value: 'room', selected: (s?.kind || (lokanta ? 'hall' : 'room')) === 'room' }, 'Oda / Bölüm'),
      h('option', { value: 'hall', selected: (s?.kind || (lokanta ? 'hall' : 'room')) === 'hall' }, 'Salon / Kat'));
    const smoking = h('input', { type: 'checkbox', ...(s?.smoking ? { checked: true } : {}) });
    const m = modal({
      title: s ? 'Bölümü Düzenle' : 'Yeni Bölüm', wide: false,
      body: h('div', { class: 'form-col' },
        h('label', null, 'Ad', name),
        h('label', null, 'Tür', kind),
        lokanta ? h('label', { class: 'row-check' }, smoking, h('span', null, 'Sigara içilen bölüm')) : null),
      actions: [{ label: 'Vazgeç' }, { label: s ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const payload = { name: name.value.trim(), kind: kind.value, smoking: smoking.checked };
        if (!payload.name) { toastError('Bölüm adı gerekli'); return true; }
        try { if (s) await api.put(`/api/sections/${s.id}`, payload); else await api.post('/api/sections', payload); toast('Kaydedildi'); m.close(); await load(); }
        catch (e) { toastError(e); return true; }
      } }],
    });
  }

  async function delSection(s) {
    if (!await confirmDialog('Bölümü sil', `“${s.name}” bölümü silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/sections/${s.id}`); await load(); } catch (e) { toastError(e); }
  }

  function editTable(s, t) {
    const name = h('input', { class: 'input', placeholder: 'Masa adı (ör. M5)', value: t?.name || '' });
    const shape = h('select', { class: 'input' },
      h('option', { value: 'square', selected: (t?.shape || 'square') === 'square' }, 'Kare'),
      h('option', { value: 'round', selected: t?.shape === 'round' }, 'Yuvarlak'));
    const seats = h('input', { class: 'input', type: 'number', min: '1', value: t?.seats || 4 });
    const waiter = h('select', { class: 'input' }, h('option', { value: '' }, 'Garson atanmadı'),
      ...people.map(p => h('option', { value: p.id, selected: t?.waiter_id === p.id }, p.full_name)));
    const m = modal({
      title: (t ? 'Masayı Düzenle' : 'Yeni Masa') + ' · ' + s.name, wide: false,
      body: h('div', { class: 'form-col' },
        h('label', null, 'Ad', name),
        h('div', { class: 'form-row' }, h('label', null, 'Şekil', shape), h('label', null, 'Kişi', seats)),
        h('label', null, 'Sorumlu garson', waiter)),
      actions: [{ label: 'Vazgeç' }, { label: t ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const payload = { section_id: s.id, name: name.value.trim(), shape: shape.value, seats: +seats.value || 1, waiter_id: +waiter.value || null };
        if (!payload.name) { toastError('Masa adı gerekli'); return true; }
        try { if (t) await api.put(`/api/sections/tables/${t.id}`, payload); else await api.post('/api/sections/tables', payload); toast('Kaydedildi'); m.close(); await load(); }
        catch (e) { toastError(e); return true; }
      } }],
    });
  }

  async function delTable(t) {
    if (!await confirmDialog('Masayı sil', `“${t.name}” masası silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/sections/tables/${t.id}`); await load(); } catch (e) { toastError(e); }
  }

  load();
}
