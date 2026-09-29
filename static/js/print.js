// Yazdırılabilir A4 belgeler: sipariş formu (iki kopya) ve yarı mamul raporu.
import { logActivity } from './api.js';
import { renderPlane } from './plane.js';
import { PART_STATES, queuePlate } from './status.js';
import { fmtDate, fmtDateTime, h } from './ui.js';

const now = () => fmtDateTime(new Date().toISOString());

export function head(company, title, lines) {
  return h('header', { class: 'pf-head' },
    h('img', { class: 'pf-logo', src: '/static/img/logo.png', alt: company }),
    h('div', { class: 'pf-title' },
      h('h1', null, title),
      lines.map(([k, v]) => h('div', null, `${k}: `, h('b', null, v)))));
}

export function foot(company, right) {
  return h('footer', { class: 'pf-foot' }, h('span', null, company), h('span', null, right));
}

// Sayfayı belgeye ekler, logolar yüklenince yazdırır, yazdırma bitince kaldırır.
export function printPage(page, title = 'Belge') {
  logActivity({ event: 'print', path: location.hash, title });
  document.querySelector('.print-area')?.remove();
  const area = h('div', { class: 'print-area' }, page);
  document.body.append(area);
  const cleanup = () => { area.remove(); window.removeEventListener('afterprint', cleanup); };
  window.addEventListener('afterprint', cleanup);
  const imgs = [...area.querySelectorAll('img')];
  Promise.all(imgs.map(i => (i.complete ? null : new Promise(r => { i.onload = i.onerror = r; }))))
    .then(() => window.print());
}

// ---------- Sipariş formu: tek sayfada iki kopya, ortada kesim çizgisi ----------
function copy(order, company, label) {
  return h('section', { class: 'pf-copy' },
    head(company, 'SİPARİŞ FORMU', [['Sipariş tarihi', fmtDate(order.created_at)], ['Sipariş no', order.code]]),
    h('table', { class: 'pf-table' }, h('tbody', null,
      row('Ürün', `${order.product_name} İnsansız Uçak`),
      row('Ürün seri numarası', order.product_serial),
      row('Adet', '1'),
      row('Parça sayısı', String(order.total_parts)),
      row('Üretim başlama tarihi', fmtDate(order.start_date)),
      row('Üretim bitiş tarihi', fmtDate(order.end_date)),
      row('Açıklama', order.note || '—'))),
    h('div', { class: 'pf-signs' },
      sign('Siparişi Oluşturan', order.created_by_name || ''),
      sign('Onaylayan', '')),
    foot(company, `${label} · Yazdırma: ${now()}`));
}

const row = (k, v) => h('tr', null, h('th', null, k), h('td', null, v));

export function sign(title, name) {
  return h('div', { class: 'pf-sign' },
    h('div', { class: 'pf-sign-title' }, title),
    h('div', { class: 'pf-sign-line' }, h('span', null, 'Ad Soyad:'), h('b', null, name)),
    h('div', { class: 'pf-sign-line' }, h('span', null, 'Tarih:')),
    h('div', { class: 'pf-sign-box' }, 'İmza'));
}

export function printOrderForm(order, company) {
  printPage(h('div', { class: 'pf-page' },
    copy(order, company, '1. Nüsha'),
    h('div', { class: 'pf-cut' }, h('span', null, '✂ Buradan kesiniz')),
    copy(order, company, '2. Nüsha')), `Sipariş formu ${order.code}`);
}

// ---------- Yarı mamul raporu: tamamlanan/kalan yüzde ve renkli uçak ----------
export function printWipReport(order, plane, company) {
  const byPart = new Map(order.parts.map(p => [p.part_id, p]));
  const done = order.progress;
  const counts = Object.fromEntries(Object.keys(PART_STATES).map(k => [k, 0]));
  order.parts.forEach(p => { counts[p.state]++; });
  const produced = counts.DEPO + counts.MONTAJ;

  const pl = renderPlane(plane, { fill: part => PART_STATES[byPart.get(part.id)?.state]?.color || 'var(--part-fill)' });

  printPage(h('div', { class: 'pf-page pf-report' },
    head(company, 'YARI MAMUL RAPORU', [
      ['Sipariş no', order.code],
      ['Rapor tarihi', fmtDate(new Date().toISOString())],
    ]),
    h('div', { class: 'wr-summary' },
      h('div', { class: 'wr-stat done' }, h('span', null, 'Tamamlanan'), h('b', null, `%${done}`),
        h('small', null, `${produced} / ${order.parts.length} parça`)),
      h('div', { class: 'wr-bar' }, h('i', { style: { width: `${done}%` } })),
      h('div', { class: 'wr-stat left' }, h('span', null, 'Kalan'), h('b', null, `%${100 - done}`),
        h('small', null, `${order.parts.length - produced} parça`))),
    h('div', { class: 'wr-plane' }, pl.svg),
    h('div', { class: 'wr-legend' }, Object.entries(PART_STATES).map(([k, s]) =>
      h('span', null, h('i', { style: { background: s.color } }), `${s.label}: `, h('b', null, counts[k])))),
    h('table', { class: 'pf-table wr-info' }, h('tbody', null,
      h('tr', null,
        h('th', null, 'Siparişi veren'), h('td', null, order.created_by_name || '—'),
        h('th', null, 'Başlama / Bitiş'), h('td', null, `${fmtDate(order.start_date)} – ${fmtDate(order.end_date)}`)))),
    foot(company, `Yazdırma: ${now()}`)), `Yarı mamul raporu ${order.code}`);
}

// ---------- Saha görev formu: görev, uçuşlar, yol ve masraflar; imzalı ----------
export function printTaskForm(t, company) {
  const launch = { ARAC_USTU: 'Araç Üstü', RAMPA: 'Fırlatma Rampası' };
  const drivers = [...new Set([t.driver_name, ...(t.vehicles || []).map(v => v.driver_name)].filter(Boolean))].join(', ');
  const money = v => `${Number(v || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
  const kv = rows => h('table', { class: 'pf-table' }, h('tbody', null,
    rows.filter(Boolean).map(([k, v]) => h('tr', null, h('th', null, k), h('td', null, v)))));
  const list = (cols, rows, empty) => (rows.length
    ? h('table', { class: 'pf-table pf-list' }, h('thead', null, h('tr', null, cols.map(c => h('th', null, c)))), h('tbody', null, rows))
    : h('p', { class: 'pf-empty' }, empty));
  const status = { BASLANGIC: 'Başlangıç', GOREVDE: 'Görevde', GOREV_TAMAMLANDI: 'Görev Tamamlandı', BASARISIZ: 'Başarısız',
    RAPOR_TAMAMLANDI: 'Rapor Tamamlandı', IPTAL: 'İptal' }[t.status] || t.status;
  printPage(h('div', { class: 'pf-page pf-flow' },
    head(company, 'SAHA GÖREV FORMU', [['Görev no', t.code], ['Tarih', fmtDate(t.started_at || t.created_at)]]),
    h('h2', { class: 'pf-h2' }, 'Görev bilgileri'),
    kv([
      ['Durum', `${status}${t.result ? ` (${t.result === 'BASARILI' ? 'Başarılı' : 'Başarısız'})` : ''}`],
      ['Saha sorumlusu', t.lead_name || '—'],
      ['Pilot', t.pilot_name || '—'],
      ['Şoför', drivers || '—'],
      ['Saha personeli', t.staff.map(s => s.full_name).join(', ') || '—'],
      ['Görev yeri', t.location_name || '—'],
      ['Başlama / bitiş', t.started_at ? `${fmtDateTime(t.started_at)} – ${t.finished_at ? fmtDateTime(t.finished_at) : 'devam ediyor'}` : '—'],
      t.note ? ['Not', t.note] : null,
    ]),
    h('h2', { class: 'pf-h2' }, `Uçuşlar (${t.flights.length})`),
    list(['Uçak', 'Ürün', 'Fırlatma sistemi', 'Uçuş raporu', 'Not'], t.flights.map(f => h('tr', null,
      h('td', null, queuePlate(f.queue_no) || f.order_code), h('td', null, `${f.product_name || ''} ${f.product_serial || ''}`),
      h('td', null, launch[f.launch] || '—'), h('td', null, f.log_status === 'TAMAM' ? 'Hazır' : f.log_status ? 'İşleniyor / hatalı' : 'Yok'),
      h('td', null, f.note || ''))), 'Uçuş yok'),
    h('h2', { class: 'pf-h2' }, 'Yol'),
    list(['Araç', 'Şoför', 'Başlangıç km', 'Bitiş km', 'Gidilen yol'], (t.vehicles || []).map(v => h('tr', null,
      h('td', null, v.plate), h('td', null, v.driver_name || ''), h('td', { class: 'num' }, v.start_km ?? '—'),
      h('td', { class: 'num' }, v.end_km ?? '—'), h('td', { class: 'num' }, v.distance_km != null ? `${v.distance_km} km` : '—'))),
    'Araç girilmedi'),
    kv([
      ['Toplam gidilen yol', t.distance_km != null ? `${t.distance_km} km` : '—'],
      t.road_note ? ['Not', t.road_note] : null,
    ]),
    h('h2', { class: 'pf-h2' }, `Masraflar (toplam ${money(t.expense_total)})`),
    list(['Tarih', 'Masrafı yapan', 'Kategori', 'Açıklama', 'Tutar'], (t.expenses || []).map(e => h('tr', null,
      h('td', null, fmtDate(e.spent_on)), h('td', null, e.spent_by_name || e.created_by_name || ''), h('td', null, e.category),
      h('td', null, e.description || ''),
      h('td', { class: 'num' }, money(e.amount)))), 'Masraf girilmedi'),
    h('div', { class: 'pf-signs' }, sign('Saha Sorumlusu', t.lead_name || ''), sign('Pilot', t.pilot_name || ''), sign('Şoför', drivers)),
    foot(company, `Yazdırma: ${now()}`)), `Saha görev formu ${t.code}`);
}
