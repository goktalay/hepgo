// Hizmetler (esnaf · berber/kuaför): hizmet + ücret + ortalama süre + yapabilen personel(ler) + personel yüzdesi.
// Rezervasyon ve Esnaf Kasa bu hizmetleri kullanır.
import { api } from '../api.js';
import { clear, confirmDialog, h, modal, pageHead, toast, toastError } from '../ui.js';

const TL = n => `${(Number(n) || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;

export async function render(view, params, ctx) {
  let services = [], people = [];
  const body = h('div', { class: 'shop-svc-wrap' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => edit() }, '＋ Hizmet');
  clear(view, pageHead('Hizmetler', { back: '#/', sub: 'Hizmet ücreti, süresi ve personel payı' }),
    h('div', { class: 'filters' }, h('div', { class: 'spacer' }), addBtn), body);

  const load = async () => {
    try { [services, people] = await Promise.all([api.get('/api/services'), api.get('/api/people').catch(() => [])]); }
    catch (e) { clear(body, h('div', { class: 'card empty' }, e.message)); return; }
    draw();
  };

  function draw() {
    clear(body);
    if (!services.length) { body.append(h('div', { class: 'card empty' }, 'Henüz hizmet yok. “＋ Hizmet” ile ekleyin.')); return; }
    const grid = h('div', { class: 'esnaf-grid' });
    services.forEach(s => grid.append(h('div', { class: 'esnaf-card' },
      h('div', { class: 'esnaf-card-top' },
        h('div', { class: 'esnaf-ic' }, '✂️'),
        h('div', { class: 'esnaf-card-price' }, TL(s.price))),
      h('h3', { class: 'esnaf-card-title' }, s.name),
      h('div', { class: 'esnaf-card-meta' },
        h('span', { class: 'chip' }, `⏱ ${s.duration_min} dk`),
        h('span', { class: 'chip' }, `%${s.staff_pct} personel payı`)),
      (s.staff || []).length
        ? h('div', { class: 'esnaf-card-people' }, s.staff.map(x => h('span', { class: 'av' }, x.name)))
        : h('p', { class: 'esnaf-card-sub' }, 'Personel atanmadı'),
      h('div', { class: 'esnaf-card-acts' },
        h('button', { class: 'btn sm', type: 'button', onclick: () => edit(s) }, 'Düzenle'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: () => del(s) }, 'Sil')))));
    body.append(grid);
  }

  function edit(s) {
    const name = h('input', { class: 'input', placeholder: 'Hizmet adı', value: s?.name || '' });
    const price = h('input', { class: 'input', type: 'number', step: '0.01', placeholder: '₺', value: s?.price ?? '' });
    const dur = h('input', { class: 'input', type: 'number', min: '5', step: '5', value: s?.duration_min ?? 30 });
    const pct = h('input', { class: 'input', type: 'number', min: '0', max: '100', value: s?.staff_pct ?? 0 });
    const sel = new Set(s?.staff_ids || []);
    const staffBox = h('div', { class: 'shop-staff-pick' }, people.map(p => {
      const on = sel.has(p.id);
      return h('button', { type: 'button', class: 'chip-btn' + (on ? ' on' : ''), onclick: e => {
        const b = e.currentTarget; if (sel.has(p.id)) sel.delete(p.id); else sel.add(p.id); b.classList.toggle('on', sel.has(p.id));
      } }, p.full_name);
    }));
    const m = modal({
      title: s ? 'Hizmeti Düzenle' : 'Yeni Hizmet', wide: true,
      body: h('div', { class: 'form-col' },
        h('label', null, 'Ad', name),
        h('div', { class: 'form-row' }, h('label', null, 'Ücret (₺)', price), h('label', null, 'Süre (dk)', dur), h('label', null, 'Personel payı (%)', pct)),
        h('label', null, 'Yapabilen personel', staffBox)),
      actions: [{ label: 'Vazgeç' }, { label: s ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
        const payload = { name: name.value.trim(), price: +price.value || 0, duration_min: +dur.value || 30, staff_pct: +pct.value || 0, staff_ids: [...sel] };
        if (!payload.name) { toastError('Hizmet adı gerekli'); return true; }
        try { if (s) await api.put(`/api/services/${s.id}`, payload); else await api.post('/api/services', payload); toast('Kaydedildi'); m.close(); await load(); }
        catch (e) { toastError(e); return true; }
      } }],
    });
  }

  async function del(s) {
    if (!await confirmDialog('Hizmeti sil', `“${s.name}” silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/services/${s.id}`); await load(); } catch (e) { toastError(e); }
  }

  load();
}
