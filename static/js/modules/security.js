// Güvenlik (fabrika girişi): gelen aracın plakası kaydedilir; parktaki araçlar plaka kartı olarak görünür, karta
// tıklanınca "çıkış yaptı" denir. Giriş / çıkış kayıtları ayrı sekmede. Kameralar ve tanımlanamayan yüzler de burada.
import { api } from '../api.js';
import {
  clear, confirmDialog, every, field, fmtDateTime, fmtDuration, h, modal, pageHead, secondsBetween, secondsSince, segmented, statStrip,
  toast, toastError,
} from '../ui.js';
import { renderCameras } from './cameras.js';
import { renderFaces } from './faces.js';

const TABS = [['', 'Araçlar'], ['log', 'Giriş / Çıkış Kayıtları'], ['cameras', 'Kameralar'], ['faces', 'Tanımlanamayan Kişiler']];

export async function render(view, params, ctx) {
  const tab = TABS.some(t => t[0] === params[0]) ? params[0] || '' : '';
  const nav = segmented(TABS, tab, v => { location.hash = v ? `#/security/${v}` : '#/security'; });
  const body = h('div');
  // Araçlar sekmesinde yeni giriş düğmesi başlığın sağında (popup)
  const addBtn = h('button', { class: 'btn primary', type: 'button' }, '+ Yeni Araç Girişi');
  clear(view, pageHead('Güvenlik', { back: '#/', sub: 'Fabrika girişi: araç giriş / çıkış kaydı, kameralar',
    right: h('div', { class: 'head-right' }, tab === '' ? addBtn : null, nav) }), body);
  if (tab === 'log') return renderLog(body);
  if (tab === 'cameras') return renderCameras(body, ctx, params.slice(1));
  if (tab === 'faces') return renderFaces(body, ctx);
  return renderVehicles(body, addBtn);
}

// Türk plakası görünümü: solda mavi TR şeridi
export const plateEl = (plate, cls = '') => h('span', { class: `tr-plate ${cls}` }, h('i', null, 'TR'), h('b', null, plate));

async function renderVehicles(body, addBtn) {
  const grid = h('div', { class: 'veh-grid' });
  let list = [];
  const draw = () => clear(grid, list.length ? list.map(v => h('button', { class: 'card veh-card', type: 'button', onclick: () => exit(v) },
    plateEl(v.plate),
    h('div', { class: 'veh-time' }, `Giriş ${fmtDateTime(v.entered_at)}`),
    h('div', { class: 'veh-dur' }, `${fmtDuration(secondsSince(v.entered_at))} içeride`),
    v.note ? h('div', { class: 'small muted' }, v.note) : null,
    v.visit_code ? h('span', { class: 'badge blue' }, `Misafir ${v.visit_code}`) : null,
    h('span', { class: 'veh-exit' }, 'Çıkış yaptı →')))
    : h('div', { class: 'card empty' }, 'İçeride kayıtlı araç yok. Gelen araç için sağ üstteki "Yeni Araç Girişi"ni kullanın.'));
  const load = async () => { list = await api.get('/api/security/vehicles'); draw(); };
  async function exit(v) {
    if (!await confirmDialog('Araç çıkışı', `${v.plate} çıkış yaptı mı?`, { okLabel: 'Çıkış Yaptı' })) return;
    try {
      await api.post(`/api/security/vehicles/${v.id}/exit`);
      toast(`${v.plate} çıkış yaptı`);
      await load();
    } catch (err) { toastError(err); }
  }
  // Yeni araç girişi: plaka (büyük kutu) ve isteğe bağlı not; Enter ile kaydedilir
  addBtn.onclick = () => {
    const plate = h('input', { class: 'input plate-input', placeholder: '34 ABC 123', autocomplete: 'off', autocapitalize: 'characters',
      spellcheck: false, 'aria-label': 'Plaka', style: { width: '100%' } });
    const note = h('input', { class: 'input', placeholder: 'Not (isteğe bağlı): sürücü, firma…' });
    const submit = async () => {
      const r = await api.post('/api/security/vehicles', { plate: plate.value, note: note.value });
      toast(`${r.plate} giriş yaptı`);
      await load();
    };
    const m = modal({
      title: 'Yeni Araç Girişi',
      body: h('div', null, field('Gelen aracın plakası', plate), field('Not', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Giriş Kaydet', class: 'primary', onClick: submit }],
    });
    for (const el of [plate, note]) {
      el.addEventListener('keydown', async e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        try { await submit(); m.close(); } catch (err) { toastError(err); }
      });
    }
    plate.focus();
  };
  clear(body, grid);
  await load();
  every(15000, () => load().catch(() => {}));
}

async function renderLog(body) {
  const today = new Date().toISOString().slice(0, 10);
  const from = h('input', { class: 'input', type: 'date', value: today, title: 'Başlangıç' });
  const to = h('input', { class: 'input', type: 'date', value: today, title: 'Bitiş' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Plaka ara…', style: { width: '180px' } });
  const stats = statStrip();
  const out = h('div');
  let rows = [];
  const load = async () => {
    rows = await api.get(`/api/security/log?date_from=${from.value}&date_to=${to.value}&q=${encodeURIComponent(q.value)}`);
    stats.set([
      { label: 'Giriş', value: rows.length },
      { label: 'Çıkış', value: rows.filter(r => r.exited_at).length },
      { label: 'Hâlâ içeride', value: rows.filter(r => !r.exited_at).length, tone: 'ok' },
    ]);
    clear(out, rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Plaka', 'Giriş', 'Kaydeden', 'Çıkış', 'Kaydeden', 'Süre', 'Not', 'Misafir'].map(t => h('th', null, t)))),
      h('tbody', null, rows.map(r => h('tr', null,
        h('td', null, plateEl(r.plate, 'sm')),
        h('td', null, fmtDateTime(r.entered_at)), h('td', { class: 'muted' }, r.entered_by_name || '—'),
        h('td', null, r.exited_at ? fmtDateTime(r.exited_at) : h('span', { class: 'badge green' }, 'İçeride')),
        h('td', { class: 'muted' }, r.exited_by_name || '—'),
        h('td', null, fmtDuration(r.exited_at ? secondsBetween(r.entered_at, r.exited_at) : secondsSince(r.entered_at))),
        h('td', { class: 'small' }, r.note || '—'),
        h('td', null, r.visit_code || '—')))))))
      : h('div', { class: 'card empty' }, 'Bu aralıkta kayıt yok'));
  };
  const csv = h('button', { class: 'btn', type: 'button', onclick: () => {
    const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [['Plaka', 'Giriş', 'Giriş kaydeden', 'Çıkış', 'Çıkış kaydeden', 'Not', 'Misafir kaydı'].map(cell).join(';'),
      ...rows.map(r => [r.plate, fmtDateTime(r.entered_at), r.entered_by_name, r.exited_at ? fmtDateTime(r.exited_at) : 'İçeride',
        r.exited_by_name, r.note, r.visit_code].map(cell).join(';'))];
    const a = h('a', { href: URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })),
      download: `arac-giris-cikis-${from.value}_${to.value}.csv` });
    document.body.append(a); a.click(); a.remove();
  } }, 'Excel (CSV) indir');
  for (const el of [from, to]) el.addEventListener('change', () => load().catch(toastError));
  q.addEventListener('input', () => load().catch(toastError));
  clear(body, h('div', { class: 'filters' }, from, to, q, h('span', { class: 'spacer' }), csv), stats, out);
  await load();
}
