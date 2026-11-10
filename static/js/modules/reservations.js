// Rezervasyon (esnaf): berberde personel+hizmet randevusu, lokantada masa rezervasyonu.
// Gün görünümü (saat sıralı liste) + gün gezinme + yeni/düzenle rezervasyon. Çakışma sunucuda doğrulanır (409).
import { api } from '../api.js';
import { clear, confirmDialog, h, modal, pageHead, toast, toastError } from '../ui.js';

const pad = n => String(n).padStart(2, '0');
const today = () => new Date().toLocaleDateString('sv');
const hm = iso => (iso ? iso.slice(11, 16) : '');
const STATUS = { ONAYLI: 'Onaylı', GELMEDI: 'Gelmedi', TAMAM: 'Tamamlandı', IPTAL: 'İptal' };

export async function render(view, params, ctx) {
  const lokanta = (ctx?.meta?.esnaf_pkg || '') === 'lokanta';
  let day = today(), list = [], people = [], services = [], tables = [];
  const body = h('div', { class: 'shop-rsv-body' });
  const dateInput = h('input', { type: 'date', class: 'input', value: day });
  const shift = n => { const d = new Date(day + 'T00:00'); d.setDate(d.getDate() + n); day = d.toLocaleDateString('sv'); dateInput.value = day; load(); };
  dateInput.addEventListener('change', () => { day = dateInput.value || today(); load(); });
  const bar = h('div', { class: 'filters cl-bar' },
    h('button', { class: 'btn cl-nav', type: 'button', onclick: () => shift(-1) }, '‹'),
    dateInput,
    h('button', { class: 'btn cl-nav', type: 'button', onclick: () => shift(1) }, '›'),
    h('button', { class: 'btn', type: 'button', onclick: () => { day = today(); dateInput.value = day; load(); } }, 'Bugün'),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn primary', type: 'button', onclick: () => edit() }, '＋ Rezervasyon'));
  clear(view, pageHead('Rezervasyon', { back: '#/', sub: lokanta ? 'Masa rezervasyonları' : 'Randevu takvimi' }), bar, body);

  async function refs() {
    const jobs = [api.get('/api/people').catch(() => [])];
    if (lokanta) jobs.push(api.get('/api/sections').catch(() => []));
    else jobs.push(api.get('/api/services').catch(() => []));
    const [pp, other] = await Promise.all(jobs);
    people = pp;
    if (lokanta) tables = (other || []).flatMap(s => (s.tables || []).map(t => ({ ...t, section: s.name })));
    else services = other || [];
  }

  async function load() {
    if (!people.length) { try { await refs(); } catch { /* */ } }
    try { list = await api.get(`/api/reservations?start=${day}&end=${day}`); }
    catch (e) { clear(body, h('div', { class: 'card empty' }, e.message)); return; }
    draw();
  }

  function draw() {
    clear(body);
    if (!list.length) { body.append(h('div', { class: 'card empty' }, 'Bu gün rezervasyon yok.')); return; }
    const wrap = h('div', { class: 'esnaf-rsv-list' });
    list.forEach(r => {
      const who = lokanta ? (r.table_name || 'Masa') : (r.staff_name || 'Personel');
      const what = lokanta ? (r.party ? `${r.party} kişi` : '') : (r.service_name || '');
      wrap.append(h('div', { class: `esnaf-rsv st-${r.status}` },
        h('div', { class: 'esnaf-rsv-time' }, hm(r.starts_at), h('small', null, '– ' + hm(r.ends_at))),
        h('div', { class: 'grow' }, h('b', null, r.customer || who),
          h('div', { class: 'small muted' }, [who, what].filter(Boolean).join(' · ') + (r.phone ? ' · ' + r.phone : ''))),
        h('span', { class: 'chip st-chip' }, STATUS[r.status] || r.status),
        h('div', { class: 'esnaf-rsv-acts' },
          r.status === 'ONAYLI' ? h('button', { class: 'btn sm', type: 'button', title: 'Geldi/Tamam', onclick: () => setStatus(r, 'TAMAM') }, '✓') : null,
          r.status === 'ONAYLI' ? h('button', { class: 'btn sm', type: 'button', title: 'Gelmedi', onclick: () => setStatus(r, 'GELMEDI') }, '∅') : null,
          h('button', { class: 'btn sm', type: 'button', onclick: () => edit(r) }, 'Düzenle'),
          h('button', { class: 'btn sm danger', type: 'button', onclick: () => del(r) }, 'Sil'))));
    });
    body.append(wrap);
  }

  async function setStatus(r, status) {
    try { await api.post(`/api/reservations/${r.id}/status`, { status }); await load(); } catch (e) { toastError(e); }
  }
  async function del(r) {
    if (!await confirmDialog('Rezervasyonu sil', 'Bu rezervasyon silinsin mi?', { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/reservations/${r.id}`); await load(); } catch (e) { toastError(e); }
  }

  function edit(r) {
    const d = r ? r.starts_at.slice(0, 10) : day;
    const dateF = h('input', { class: 'input', type: 'date', value: d });
    const timeF = h('input', { class: 'input', type: 'time', value: r ? hm(r.starts_at) : '10:00' });
    const dur = h('input', { class: 'input', type: 'number', min: '5', step: '5', value: r ? minutesBetween(r.starts_at, r.ends_at) : (lokanta ? 90 : 30) });
    const customer = h('input', { class: 'input', placeholder: 'Müşteri adı', value: r?.customer || '' });
    const phone = h('input', { class: 'input', type: 'tel', placeholder: 'Telefon', value: r?.phone || '' });
    let fieldA, fieldB;
    if (lokanta) {
      fieldA = h('select', { class: 'input' }, h('option', { value: '' }, 'Masa seçin'),
        ...tables.map(t => h('option', { value: t.id, selected: r?.table_id === t.id }, `${t.name} (${t.section || ''}, ${t.seats} kişi)`)));
      fieldB = h('input', { class: 'input', type: 'number', min: '1', placeholder: 'Kişi', value: r?.party || '' });
    } else {
      fieldA = h('select', { class: 'input' }, h('option', { value: '' }, 'Personel seçin'),
        ...people.map(p => h('option', { value: p.id, selected: r?.staff_id === p.id }, p.full_name)));
      fieldB = h('select', { class: 'input' }, h('option', { value: '' }, 'Hizmet seçin'),
        ...services.map(s => h('option', { value: s.id, selected: r?.service_id === s.id, 'data-dur': s.duration_min }, `${s.name} · ${s.duration_min}dk`)));
      fieldB.addEventListener('change', () => { const o = fieldB.selectedOptions[0]; if (o?.dataset.dur) dur.value = o.dataset.dur; });
    }
    const m = modal({
      title: r ? 'Rezervasyonu Düzenle' : 'Yeni Rezervasyon', wide: true,
      body: h('div', { class: 'form-col' },
        h('div', { class: 'form-row' }, h('label', null, 'Tarih', dateF), h('label', null, 'Saat', timeF), h('label', null, 'Süre (dk)', dur)),
        h('div', { class: 'form-row' }, h('label', null, lokanta ? 'Masa' : 'Personel', fieldA), h('label', null, lokanta ? 'Kişi' : 'Hizmet', fieldB)),
        h('div', { class: 'form-row' }, h('label', null, 'Müşteri', customer), h('label', null, 'Telefon', phone))),
      actions: [{ label: 'Vazgeç' }, { label: r ? 'Kaydet' : 'Oluştur', class: 'primary', onClick: async () => {
        const starts = `${dateF.value}T${timeF.value || '00:00'}:00`;
        const ends = addMinutes(starts, +dur.value || 30);
        const payload = { kind: lokanta ? 'table' : 'staff', customer: customer.value.trim(), phone: phone.value.trim(),
          starts_at: starts, ends_at: ends, note: '' };
        if (lokanta) { payload.table_id = +fieldA.value || null; payload.party = +fieldB.value || null; if (!payload.table_id) { toastError('Masa seçin'); return true; } }
        else { payload.staff_id = +fieldA.value || null; payload.service_id = +fieldB.value || null; if (!payload.staff_id) { toastError('Personel seçin'); return true; } }
        try { if (r) await api.put(`/api/reservations/${r.id}`, payload); else await api.post('/api/reservations', payload); toast('Kaydedildi'); m.close(); await load(); }
        catch (e) { toastError(e); return true; }
      } }],
    });
  }

  load();
}

function minutesBetween(a, b) { return Math.max(5, Math.round((new Date(b) - new Date(a)) / 60000)); }
function addMinutes(iso, min) {
  const d = new Date(iso); d.setMinutes(d.getMinutes() + min);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}
