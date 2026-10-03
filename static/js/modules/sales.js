// Satış Yönetimi (M21): firmalar için satış faturası oluşturma / düzenleme / yazdırma.
// Faturalar ortak `invoices` tablosunda tutulur; Mikro'dan çekilen satış faturaları listede kilitli görünür.
import { crmNav } from './crmhub.js';
import { api } from '../api.js';
import { foot, head as printHead, printPage } from '../print.js';
import { clear, confirmDialog, field, fmtDate, fmtDateTime, h, modal, pageHead, t, toast, toastError, periodFilter } from '../ui.js';

const money = v => (v == null ? '—' : Number(v).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₺');
const num = v => (v == null ? '' : (Math.round(Number(v) * 1000) / 1000).toLocaleString('tr-TR'));
const SRC = { manual: ['Elle', 'blue'], mikro: ['Mikro', 'gray'] };

let OPTS = null;
async function loadOpts() {
  const [cs, cs2, ps, meta, whs] = await Promise.all([
    api.get('/api/companies?supplier=false').catch(() => []),
    api.get('/api/companies?supplier=true').catch(() => []),
    api.get('/api/sales/products?q=').catch(() => []),
    api.get('/api/meta').catch(() => ({})),
    api.get('/api/sales/warehouses').catch(() => []),
  ]);
  const seen = new Set();
  const companies = [...cs, ...cs2].filter(c => !seen.has(c.id) && seen.add(c.id)).sort((a, b) => (a.name || '').localeCompare(b.name || '', 'tr'));
  OPTS = { companies, products: ps, company: meta.company || '', warehouses: whs };
  return OPTS;
}

let reloadList = () => {};

export async function render(view, params, ctx) {
  await loadOpts();
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Fatura no ya da firma ara…', style: { maxWidth: '280px' } });
  const body = h('div');
  const period = periodFilter('sales', () => draw());
  reloadList = () => draw();

  const draw = async () => {
    clear(body, h('div', { class: 'card card-pad loading' }, 'Yükleniyor…'));
    try {
      const rows = await api.get(`/api/sales?q=${encodeURIComponent(q.value.trim())}&${period.qs()}`);
      if (!rows.length) { clear(body, h('div', { class: 'card empty' }, t('{label} için satış faturası yok. Dönemi değiştirin ya da “Yeni Fatura” ile oluşturun.', { label: period.label() }))); return; }
      clear(body, h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Fatura No'), h('th', null, 'Firma'), h('th', null, 'Tarih'),
          h('th', { class: 'num' }, 'Ara Toplam'), h('th', { class: 'num' }, 'Toplam'), h('th', null, 'Kaynak'), h('th', null, 'Stok'), h('th', null, ''))),
        h('tbody', null, rows.map(r => {
          const [sl, st] = SRC[r.source] || SRC.manual;
          return h('tr', { class: 'clickable', onclick: () => openInvoice(r.id, ctx) },
            h('td', { class: 'mono small' }, r.number || '—'),
            h('td', null, r.company_name || r.company_current || '—'),
            h('td', { class: 'small' }, r.invoice_date ? fmtDate(r.invoice_date) : fmtDate(r.created_at)),
            h('td', { class: 'num small' }, money(r.subtotal)),
            h('td', { class: 'num' }, money(r.total)),
            h('td', null, h('span', { class: `badge ${st}` }, sl)),
            h('td', null, r.stock_applied ? h('span', { class: 'badge green' }, 'Düşüldü') : h('span', { class: 'badge gray' }, '—')),
            h('td', { class: 'actions', onclick: e => e.stopPropagation() },
              h('button', { class: 'btn xs', onclick: () => printInvoice(r.id) }, '🖨'),
              r.source === 'manual' ? h('button', { class: 'btn xs', onclick: () => invoiceForm(ctx, r.id) }, 'Düzenle') : null));
        })))));
    } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); }
  };
  let searchT; q.addEventListener('input', () => { clearTimeout(searchT); searchT = setTimeout(draw, 300); });

  clear(view, pageHead('Satış Yönetimi', { back: '#/', sub: 'Firmalar için satış faturası',
    tabs: crmNav('sales', ctx),
    right: h('button', { class: 'btn primary', type: 'button', onclick: () => invoiceForm(ctx, null) }, '＋ Yeni Fatura') }),
    h('div', { class: 'filters' }, q, period.el), body);
  draw();
}

function lineTotals(rows) {
  let sub = 0, vat = 0;
  for (const tr of rows.children) {
    const q = Number(tr._qty.value) || 0, p = Number(tr._price.value) || 0, v = Number(tr._vat.value) || 0;
    const s = q * p; sub += s; vat += s * v / 100;
  }
  return { sub: Math.round(sub * 100) / 100, vat: Math.round(vat * 100) / 100, total: Math.round((sub + vat) * 100) / 100 };
}

async function invoiceForm(ctx, id) {
  if (!OPTS) await loadOpts();
  if (!OPTS.companies.length) { toast('Önce Firma Yönetimi’nden bir firma ekleyin', 'err'); return; }
  const existing = id ? await api.get(`/api/sales/${id}`) : null;
  if (existing && existing.source !== 'manual') { toast('Mikro’dan gelen fatura düzenlenemez', 'err'); return; }

  const comp = h('select', { class: 'input' }, h('option', { value: '' }, 'Firma seçin'),
    OPTS.companies.map(c => h('option', { value: c.id, selected: c.id === existing?.company_id }, c.name)));
  const number = h('input', { class: 'input mono', value: existing?.number || '', placeholder: 'Boş bırakılırsa otomatik' });
  const date = h('input', { class: 'input', type: 'date', value: existing?.invoice_date || new Date().toLocaleDateString('sv') });
  const note = h('input', { class: 'input', value: existing?.note || '' });
  const reduce = h('input', { type: 'checkbox', checked: !!(existing?.stock_applied) });
  const dep = h('select', { class: 'input' }, OPTS.warehouses.map((w, i) => h('option', { value: w.id, selected: existing?.warehouse_id ? w.id === existing.warehouse_id : i === 0 }, w.name)));
  const depWrap = h('div', { style: { display: reduce.checked ? '' : 'none' } }, field('Stok çıkışı deposu', dep));
  reduce.addEventListener('change', () => { depWrap.style.display = reduce.checked ? '' : 'none'; });

  const rows = h('tbody');
  const sumSub = h('b'), sumVat = h('b'), sumTot = h('b');
  const sync = () => { const t = lineTotals(rows); sumSub.textContent = money(t.sub); sumVat.textContent = money(t.vat); sumTot.textContent = money(t.total); };
  const addRow = (l = {}) => {
    const prod = h('select', { class: 'input' }, h('option', { value: '' }, 'Serbest kalem'),
      OPTS.products.map(p => h('option', { value: p.id, selected: p.id === l.product_id }, `${p.code} · ${p.name}`)));
    const desc = h('input', { class: 'input', value: l.description || '', placeholder: 'Açıklama' });
    const qty = h('input', { class: 'input num', type: 'number', min: 0, step: 'any', value: l.qty ?? '' });
    const unit = h('input', { class: 'input', value: l.unit || '', placeholder: 'adet', style: { width: '72px' } });
    const price = h('input', { class: 'input num', type: 'number', min: 0, step: '0.01', value: l.unit_price ?? '' });
    const vat = h('input', { class: 'input num', type: 'number', min: 0, max: 100, step: '0.1', value: l.vat_rate ?? 20, style: { width: '68px' } });
    prod.addEventListener('change', () => { const p = OPTS.products.find(z => z.id === Number(prod.value)); if (p) { if (!desc.value) desc.value = p.name; if (!unit.value) unit.value = p.unit || 'adet'; } });
    const tr = h('tr', null, h('td', null, prod, desc), h('td', null, qty), h('td', null, unit), h('td', null, price), h('td', null, vat),
      h('td', null, h('button', { class: 'btn xs ghost', type: 'button', onclick: () => { tr.remove(); sync(); } }, '✕')));
    tr._prod = prod; tr._desc = desc; tr._qty = qty; tr._unit = unit; tr._price = price; tr._vat = vat;
    [qty, price, vat].forEach(i => i.addEventListener('input', sync));
    rows.append(tr);
  };
  (existing?.items?.length ? existing.items : [{}]).forEach(addRow);
  sync();

  modal({
    title: existing ? t('{num} · Düzenle', { num: existing.number || 'Fatura' }) : 'Yeni Satış Faturası', wide: true,
    body: h('div', null,
      h('div', { class: 'form-grid' }, field('Firma *', comp), field('Fatura no', number), field('Tarih', date)),
      h('table', { class: 'table sl-lines' }, h('thead', null, h('tr', null, h('th', null, 'Ürün / Açıklama'), h('th', null, 'Miktar'),
        h('th', null, 'Birim'), h('th', null, 'Birim fiyat'), h('th', null, 'KDV %'), h('th', null, ''))), rows),
      h('div', { class: 'row-inline', style: { margin: '6px 0 12px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => { addRow(); sync(); } }, '＋ Satır')),
      h('div', { class: 'sl-totals' }, h('div', null, 'Ara toplam: ', sumSub), h('div', null, 'KDV: ', sumVat), h('div', { class: 'big' }, 'Genel toplam: ', sumTot)),
      h('label', { class: 'mk-check', style: { marginTop: '10px' } }, reduce, h('span', null, 'Bu faturayı stoktan düş (eşleşen malzemelerden çıkış)')),
      depWrap,
      field('Not', note)),
    actions: [{ label: 'Vazgeç' }, { label: existing ? 'Kaydet' : 'Oluştur', class: 'primary', onClick: async () => {
      const items = [...rows.children].map(tr => ({ product_id: tr._prod.value ? Number(tr._prod.value) : null,
        description: tr._desc.value || (tr._prod.selectedOptions[0]?.textContent || ''), qty: Number(tr._qty.value) || 0,
        unit: tr._unit.value || null, unit_price: Number(tr._price.value) || 0, vat_rate: Number(tr._vat.value) || 0 }))
        .filter(l => l.product_id || (l.description && l.qty));
      if (!items.length) throw new Error('En az bir satır ekleyin');
      const payload = { company_id: Number(comp.value) || 0, number: number.value.trim() || null, invoice_date: date.value || null,
        note: note.value, reduce_stock: reduce.checked, warehouse_id: reduce.checked ? Number(dep.value) : null, items };
      if (!payload.company_id) throw new Error('Firma seçin');
      if (existing) await api.put(`/api/sales/${id}`, payload); else await api.post('/api/sales', payload);
      toast(existing ? 'Fatura güncellendi' : 'Satış faturası oluşturuldu', 'success');
      reloadList();
    } }],
  });
}

async function openInvoice(id, ctx) {
  const x = await api.get(`/api/sales/${id}`);
  const [sl, st] = SRC[x.source] || SRC.manual;
  modal({
    title: `${x.number || 'Satış Faturası'}`, wide: true,
    body: h('div', null,
      h('dl', { class: 'hr-kv' },
        h('dt', null, 'Firma'), h('dd', null, x.company_name || (x.company && x.company.name) || '—'),
        h('dt', null, 'Tarih'), h('dd', null, x.invoice_date ? fmtDate(x.invoice_date) : fmtDateTime(x.created_at)),
        h('dt', null, 'Kaynak'), h('dd', null, h('span', { class: `badge ${st}` }, sl), x.stock_applied ? h('span', { class: 'badge green', style: { marginLeft: '6px' } }, 'Stoktan düşüldü') : null),
        x.note ? [h('dt', null, 'Not'), h('dd', { class: 'pre' }, x.note)] : null),
      invoiceTable(x)),
    actions: [
      x.source === 'manual' ? { label: 'Düzenle', onClick: () => invoiceForm(ctx, id) } : null,
      { label: '🖨 Yazdır', onClick: () => printInvoice(id) },
      x.source === 'manual' ? { label: 'Sil', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Faturayı sil', t('{num} silinsin mi? Stoktan düşülmüşse stok geri alınır.', { num: x.number || 'Fatura' }), { okLabel: 'Sil', danger: true })) return;
        await api.del(`/api/sales/${id}`); toast('Fatura silindi'); reloadList();
      } } : null,
    ].filter(Boolean),
  });
}

function invoiceTable(x) {
  return h('table', { class: 'table' },
    h('thead', null, h('tr', null, h('th', null, '#'), h('th', null, 'Ürün / Açıklama'), h('th', { class: 'num' }, 'Miktar'),
      h('th', { class: 'num' }, 'Birim fiyat'), h('th', { class: 'num' }, 'KDV %'), h('th', { class: 'num' }, 'Tutar'))),
    h('tbody', null, x.items.map((i, n) => h('tr', null, h('td', { class: 'muted' }, n + 1),
      h('td', null, i.product_code ? h('b', { class: 'mono' }, `${i.product_code} `) : null, i.description),
      h('td', { class: 'num' }, `${num(i.qty)} ${i.unit || ''}`), h('td', { class: 'num' }, money(i.unit_price)),
      h('td', { class: 'num' }, num(i.vat_rate)), h('td', { class: 'num' }, money((i.qty || 0) * (i.unit_price || 0)))))),
    h('tfoot', null,
      h('tr', null, h('td', { colspan: 5, class: 'num' }, 'Ara toplam'), h('td', { class: 'num' }, money(x.subtotal))),
      h('tr', null, h('td', { colspan: 5, class: 'num' }, 'KDV'), h('td', { class: 'num' }, money(x.vat_total))),
      h('tr', null, h('td', { colspan: 5, class: 'num' }, h('b', null, 'Genel toplam')), h('td', { class: 'num' }, h('b', null, money(x.total))))));
}

async function printInvoice(id) {
  const x = await api.get(`/api/sales/${id}`);
  const company = (await api.get('/api/meta').catch(() => ({}))).company || '';
  const doc = h('div', { class: 'mp-doc' },
    printHead(company, 'SATIŞ FATURASI', [['Fatura no', x.number || '—'], ['Tarih', fmtDate(x.invoice_date || x.created_at)],
      ['Firma', x.company_name || (x.company && x.company.name) || '']]),
    h('section', { class: 'mp-sec' }, invoiceTable(x)),
    x.note ? h('section', { class: 'mp-sec' }, h('h2', null, 'Not'), h('div', { class: 'mp-pre' }, x.note)) : null,
    foot(company, x.number || ''));
  printPage(doc, `Satış Faturası ${x.number || ''}`);
}
