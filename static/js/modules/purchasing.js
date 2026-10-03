// Satın Alma: Talep Yönetimi, Tedarikçi Yönetimi (Firma Yönetimi ekranları, tedarikçi kapsamında), Fatura İrsaliye
// (kalemler seçilen depoya — varsayılan Ana Depo — stok girişi olur) ve Teklif Yönetimi (kalemler, firmaya iletme, revizyonlar).
import { api, fileUrl, upload } from '../api.js';
import { foot, head as printHead, printPage } from '../print.js';
import { renderSuppliers } from './companies.js';
import {
  clear, confirmDialog, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref, statStrip,
  t, toast, toastError, periodFilter
} from '../ui.js';

const SUBS = [
  { key: 'requests', title: 'Talep Yönetimi' },
  { key: 'suppliers', title: 'Tedarikçi Yönetimi' },
  { key: 'invoices', title: 'Fatura İrsaliye' },
  { key: 'quotes', title: 'Teklif Yönetimi' },
];
const REQ_TONE = { TASLAK: 'gray', ONAY_BEKLIYOR: 'yellow', ONAYLANDI: 'green', REDDEDILDI: 'red', TAMAMLANDI: 'blue', IPTAL: 'gray' };
const QUOTE_TONE = { TASLAK: 'gray', GONDERILDI: 'blue', KABUL: 'green', RED: 'red' };
const TYPE_CLS = { YEDEK_PARCA: 'spare', HAMMADDE: 'raw', DEMIRBAS: 'fixture', SARF: 'consumable' };
const num = v => (v == null ? '—' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: 3 }));
const money = (v, cur = 'TRY') => (v || v === 0 ? Number(v).toLocaleString('tr-TR', { style: 'currency', currency: cur }) : '—');
const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
let OPTS = null;
const options = async () => (OPTS = await api.get('/api/purchasing/options'));
const typeTag = (t, label) => h('span', { class: `type-tag ${TYPE_CLS[t] || ''}` }, label || OPTS?.types?.[t] || t);

export async function render(view, params, ctx) {
  const sub = SUBS.find(s => s.key === params[0]) || SUBS.find(s => s.key === pref('purchasing.last', 'requests')) || SUBS[0];
  if (!params[0]) { location.replace(`#/purchasing/${sub.key}`); return; }
  setPref('purchasing.last', sub.key);
  const rest = params.slice(1);
  const isAdmin = ctx.user.roles.includes('Sistem Yöneticisi');
  if (sub.key === 'suppliers') await renderSuppliers(view, rest, ctx);
  else if (sub.key === 'requests') {
    if (/^\d+$/.test(rest[0] || '')) return renderRequest(view, Number(rest[0]), isAdmin);
    await renderRequests(view);
  } else if (sub.key === 'invoices') await renderInvoices(view);
  else {
    if (/^\d+$/.test(rest[0] || '')) return renderQuote(view, Number(rest[0]), ctx);
    await renderQuotes(view);
  }
  if (!(sub.key === 'suppliers' && rest.length)) purchasingHead(view, sub);
}

function purchasingHead(view, cur) {
  const head = view.querySelector('.page-head');
  if (!head) return;
  head.querySelector('h1').textContent = 'Satın Alma';
  const subEl = head.querySelector('.sub');   // alt başlık sekmeyle tekrar olmasın
  if (subEl) subEl.remove();
  // Alt modüller açılır liste yerine başlık bandında sekme çubuğu (.seg.seg-tabs)
  if (!head.querySelector('.seg-tabs')) {
    head.append(segmented(SUBS.map(s => [s.key, s.title]), cur.key, k => { location.hash = `#/purchasing/${k}`; }, { tabs: true }));
  }
}

// Malzeme seçimi: tipe göre gruplu açılır liste
function materialSelect(value) {
  const groups = Object.entries(OPTS.types).map(([t, label]) => {
    const list = OPTS.materials.filter(m => m.type === t && m.active);
    return list.length ? h('optgroup', { label }, list.map(m => h('option', { value: m.id, selected: m.id === value }, `${m.code} — ${m.name} (${m.unit || 'adet'})`))) : null;
  });
  return h('select', { class: 'input' }, h('option', { value: '' }, 'Malzeme seçin'), groups);
}
const unitOf = id => OPTS.materials.find(m => m.id === Number(id))?.unit || 'adet';

// ---------- Talep Yönetimi
async function renderRequests(view) {
  const period = periodFilter('purchaseRequests', () => renderRequests(view), { title: 'Açık talepler her zaman; kapananlar seçilen dönemde' });
  const [list] = await Promise.all([api.get(`/api/purchasing/requests?${period.qs()}`), options()]);
  const stats = statStrip();
  const n = s => list.filter(r => r.status === s).length;
  stats.set([
    { label: 'Taslak', value: n('TASLAK') },
    { label: 'Onay bekleyen', value: n('ONAY_BEKLIYOR'), tone: n('ONAY_BEKLIYOR') ? 'alert' : '' },
    { label: 'Onaylanan (teslim bekliyor)', value: n('ONAYLANDI') },
    { label: 'Tamamlanan', value: n('TAMAMLANDI'), tone: 'ok' },
    { label: 'Reddedilen', value: n('REDDEDILDI') },
  ]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Talep no, başlık ara…', style: { width: '220px' } });
  const st = selectInput(Object.entries({ TASLAK: 'Taslak', ONAY_BEKLIYOR: 'Onay bekliyor', ONAYLANDI: 'Onaylandı', TAMAMLANDI: 'Tamamlandı', REDDEDILDI: 'Reddedildi', IPTAL: 'İptal' }), { all: 'Tüm durumlar' });
  const body = h('div');
  const draw = () => {
    const rows = list.filter(r => (!st.value || r.status === st.value) && matches(q.value, r.code, r.title, r.note, r.created_by_name));
    clear(body, rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, h('th', null, 'Talep'), h('th', null, 'Başlık'), h('th', { class: 'num' }, 'Kalem'), h('th', null, 'İhtiyaç tarihi'),
        h('th', null, 'Durum'), h('th', null, 'Açan'))),
      h('tbody', null, rows.map(r => h('tr', { class: 'click', onclick: () => { location.hash = `#/purchasing/requests/${r.id}`; } },
        h('td', { class: 'mono' }, h('b', null, r.code)), h('td', null, r.title), h('td', { class: 'num' }, r.item_count),
        h('td', null, fmtDate(r.needed_by) || '—'), h('td', null, h('span', { class: `badge ${REQ_TONE[r.status]}` }, r.status_label)),
        h('td', { class: 'small muted' }, `${r.created_by_name || ''} · ${fmtDate(r.created_at)}`))))))
      : h('div', { class: 'card empty' }, list.length ? 'Filtreye uyan talep yok' : 'Henüz talep yok. “Yeni Talep” ile başlayın.'));
  };
  q.addEventListener('input', draw); st.addEventListener('change', draw);
  clear(view, pageHead('Talep Yönetimi', { back: '#/' }),
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => requestForm(null) }, '＋ Yeni Talep')),
    stats, h('div', { class: 'filters' }, q, st, period.el), body);
  draw();
}

function requestForm(r) {
  const title = h('input', { class: 'input', value: r?.title || '', placeholder: 'ör. Ekim üretimi için motor ve klips' });
  const needed = h('input', { class: 'input', type: 'date', value: r?.needed_by || '' });
  const note = h('textarea', { class: 'input', rows: 3 }, r?.note || '');
  modal({
    title: r ? t('{code} · Düzenle', { code: r.code }) : 'Yeni Satın Alma Talebi',
    body: h('div', null, field('Talep başlığı *', title), field('İhtiyaç tarihi', needed), field('Açıklama', note)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = { title: title.value, needed_by: needed.value || null, note: note.value };
      if (r) { await api.put(`/api/purchasing/requests/${r.id}`, body); reload(); return; }
      const { id } = await api.post('/api/purchasing/requests', body);
      location.hash = `#/purchasing/requests/${id}`;
    } }],
  });
  title.focus();
}

async function renderRequest(view, id, isAdmin) {
  const [r] = await Promise.all([api.get(`/api/purchasing/requests/${id}`), options()]);
  const editable = ['TASLAK', 'REDDEDILDI'].includes(r.status);
  const itemForm = it => {
    const mat = materialSelect(it?.product_id);
    const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: it?.qty ?? '' });
    const unit = h('span', { class: 'muted' }, it ? unitOf(it.product_id) : '');
    mat.addEventListener('change', () => { unit.textContent = mat.value ? unitOf(mat.value) : ''; });
    const note = h('input', { class: 'input', value: it?.note || '', placeholder: 'Bu satıra özel açıklama (ör. marka, ölçü, aciliyet)' });
    modal({
      title: it ? 'Kalemi Düzenle' : 'Talebe Kalem Ekle',
      body: h('div', null, field('Malzeme (yedek parça, hammadde, demirbaş, sarf)', mat, 'Listede yoksa MRP › Malzeme Yönetimi’nden eklenir'),
        field('Talep miktarı', h('div', { class: 'row-inline' }, qty, unit)), field('Açıklama', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const body = { product_id: Number(mat.value), qty: Number(qty.value), note: note.value };
        if (!body.product_id) throw new Error('Malzeme seçin');
        if (it) await api.put(`/api/purchasing/requests/${id}/items/${it.id}`, body); else await api.post(`/api/purchasing/requests/${id}/items`, body);
        reload();
      } }],
    });
  };
  const act = async (url, msg, body) => { try { await api.post(url, body || {}); toast(msg); reload(); } catch (err) { toastError(err); } };
  const decide = ok => {
    const note = h('textarea', { class: 'input', rows: 3 });
    modal({
      title: `${r.code} · ${ok ? 'Onayla' : 'Reddet'}`, body: field(ok ? 'Not (isteğe bağlı)' : 'Reddetme sebebi *', note),
      actions: [{ label: 'Vazgeç' }, { label: ok ? 'Onayla' : 'Reddet', class: ok ? 'primary' : 'danger', onClick: async () => {
        await api.post(`/api/purchasing/requests/${id}/${ok ? 'approve' : 'reject'}`, { note: note.value }); toast(ok ? 'Talep onaylandı' : 'Talep reddedildi'); reload();
      } }],
    });
  };
  const remaining = r.items.map(i => ({ ...i, left: Math.max(0, i.qty - i.received) })).filter(i => i.left > 0);
  const actions = [
    editable ? h('button', { class: 'btn', onclick: () => requestForm(r) }, 'Düzenle') : null,
    editable ? h('button', { class: 'btn primary', onclick: () => act(`/api/purchasing/requests/${id}/submit`, 'Talep Sistem Yöneticisi onayına gönderildi') }, 'Onaya Gönder') : null,
    r.status === 'ONAY_BEKLIYOR' && r.can_approve ? [h('button', { class: 'btn primary', onclick: () => decide(true) }, 'Onayla'), h('button', { class: 'btn', onclick: () => decide(false) }, 'Reddet')] : null,
    r.status === 'ONAYLANDI' ? [h('button', { class: 'btn', onclick: () => quoteForm(null, r) }, 'Teklif Al'),
      remaining.length ? h('button', { class: 'btn primary', onclick: () => invoiceForm({ request: r, lines: remaining.map(i => ({ product_id: i.product_id, qty: i.left })) }) }, 'Fatura / İrsaliye Gir') : null] : null,
    !['TAMAMLANDI', 'IPTAL'].includes(r.status) ? h('button', { class: 'btn ghost danger-text', onclick: async () => {
      if (await confirmDialog('Talebi iptal et', t('{code} iptal edilsin mi?', { code: r.code }), { okLabel: 'İptal Et', danger: true })) act(`/api/purchasing/requests/${id}/cancel`, 'Talep iptal edildi');
    } }, 'İptal Et') : null,
  ];
  clear(view,
    pageHead(`${r.code} · ${r.title}`, { back: '#/purchasing/requests', sub: 'Satın Alma · Talep Yönetimi' }),
    moduleToolbar(actions),
    h('div', { class: 'card card-pad pu-head' },
      h('dl', { class: 'hr-kv' },
        h('dt', null, 'Durum'), h('dd', null, h('span', { class: `badge ${REQ_TONE[r.status]}` }, r.status_label)),
        h('dt', null, 'Açan'), h('dd', null, `${r.created_by_name || ''} · ${fmtDateTime(r.created_at)}`),
        h('dt', null, 'İhtiyaç tarihi'), h('dd', null, fmtDate(r.needed_by) || '—'),
        r.submitted_at ? [h('dt', null, 'Onaya gönderildi'), h('dd', null, fmtDateTime(r.submitted_at))] : null,
        r.decided_at ? [h('dt', null, r.status === 'REDDEDILDI' ? 'Reddeden' : 'Onaylayan'), h('dd', null, `${r.decided_by_name || ''} · ${fmtDateTime(r.decided_at)}${r.decision_note ? ` · ${r.decision_note}` : ''}`)] : null,
        r.note ? [h('dt', null, 'Açıklama'), h('dd', null, r.note)] : null,
        r.invoices.length ? [h('dt', null, 'Faturalar'), h('dd', null, r.invoices.map(d => `${d.kind === 'FATURA' ? 'Fatura' : 'İrsaliye'} ${d.number || ''} (${d.company_name || ''})`).join(', '))] : null),
      r.status === 'REDDEDILDI' ? h('div', { class: 'hr-alert' }, 'Talep reddedildi. Kalemleri düzeltip yeniden onaya gönderebilirsiniz.') : null),
    h('div', { class: 'card card-pad' },
      h('div', { class: 'tv-bar' }, h('b', null, t('Kalemler ({n})', { n: r.items.length })), h('span', { class: 'spacer' }),
        editable ? h('button', { class: 'btn sm primary', onclick: () => itemForm(null) }, '＋ Kalem Ekle') : null),
      r.items.length ? h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Malzeme'), h('th', null, 'Tip'), h('th', { class: 'num' }, 'Talep'), h('th', { class: 'num' }, 'Teslim alınan'),
          h('th', null, 'Açıklama'), editable ? h('th', null, '') : null)),
        h('tbody', null, r.items.map(i => h('tr', null,
          h('td', null, h('a', { href: `#/mrp/materials/${i.product_id}` }, h('b', { class: 'mono' }, i.code)), ` ${i.name}`),
          h('td', null, typeTag(i.type)), h('td', { class: 'num' }, h('b', null, num(i.qty)), ` ${i.unit || 'adet'}`),
          h('td', { class: `num ${i.received >= i.qty ? 'pos' : ''}` }, i.received ? h('b', null, num(i.received)) : '—'),
          h('td', { class: 'small' }, i.note || ''),
          editable ? h('td', { class: 'actions' }, h('button', { class: 'btn xs', onclick: () => itemForm(i) }, 'Düzenle'),
            h('button', { class: 'btn xs ghost', onclick: async () => { await api.del(`/api/purchasing/requests/${id}/items/${i.id}`); reload(); } }, '✕')) : null))))
        : h('div', { class: 'empty small' }, 'Kalem eklenmemiş')));
}

// ---------- Fatura İrsaliye
async function renderInvoices(view) {
  const period = periodFilter('purchaseInvoices', () => renderInvoices(view));
  const [list] = await Promise.all([api.get(`/api/purchasing/invoices?${period.qs()}`), options()]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Belge no, tedarikçi, malzeme ara…', style: { width: '240px' } });
  const kind = selectInput([['FATURA', 'Fatura'], ['IRSALIYE', 'İrsaliye']], { all: 'Fatura ve irsaliye' });
  const body = h('div');
  const month = new Date().toISOString().slice(0, 7);
  const stats = statStrip();
  stats.set([
    { label: 'Belge', value: list.length },
    { label: 'Bu ay', value: list.filter(d => (d.doc_date || '').startsWith(month)).length },
    { label: 'Bu ay tutar', value: money(list.filter(d => (d.doc_date || '').startsWith(month)).reduce((a, d) => a + (d.amount || d.lines_total || 0), 0)) },
    { label: 'Dosyası eksik', value: list.filter(d => !d.file).length, tone: list.some(d => !d.file) ? 'alert' : '' },
  ]);
  const draw = () => {
    const rows = list.filter(d => (!kind.value || d.kind === kind.value)
      && matches(q.value, d.number, d.company_name, d.supplier, d.request_code, ...d.lines.map(l => `${l.code} ${l.name}`)));
    clear(body, rows.length ? h('div', { class: 'pu-invoices' }, rows.map(d => h('div', { class: `card card-pad pu-invoice ${d.file ? '' : 'nofile'}` },
      h('div', { class: 'tv-bar' },
        h('span', { class: `badge ${d.kind === 'FATURA' ? 'blue' : 'purple'}` }, d.kind === 'FATURA' ? 'Fatura' : 'İrsaliye'),
        h('b', { class: 'mono' }, d.number || '—'), h('span', null, d.company_name || d.supplier || ''), h('span', { class: 'small muted' }, fmtDate(d.doc_date)),
        d.request_code ? h('a', { class: 'small', href: `#/purchasing/requests/${d.request_id}` }, t('Talep {code}', { code: d.request_code })) : null,
        h('span', { class: 'spacer' }),
        h('span', { class: 'small muted' }, `→ ${d.warehouse_name || '—'}`),
        d.file ? h('a', { class: 'btn sm', href: fileUrl(d.file), target: '_blank', rel: 'noopener' }, 'Belge') : h('button', { class: 'btn sm danger-text', onclick: () => attachFile(d) }, 'Belge dosyası ekle')),
      h('table', { class: 'table compact' }, h('tbody', null, d.lines.map(l => h('tr', null,
        h('td', null, h('a', { href: `#/mrp/materials/${l.product_id}` }, h('b', { class: 'mono' }, l.code)), ` ${l.name}`),
        h('td', null, typeTag(l.type)), h('td', { class: 'num' }, `${num(l.qty)} ${l.unit || ''}`),
        h('td', { class: 'num small muted' }, l.unit_price != null ? `${money(l.unit_price)} / ${l.unit || 'adet'}` : ''),
        h('td', { class: 'num' }, l.unit_price != null ? money(l.qty * l.unit_price) : ''))))),
      h('div', { class: 'pu-inv-total' }, d.amount ? t('Belge tutarı: {v}', { v: money(d.amount) }) : d.lines_total ? t('Kalemler toplamı: {v}', { v: money(d.lines_total) }) : '',
        h('span', { class: 'small muted' }, ` · ${d.user_name || ''} · ${fmtDateTime(d.created_at)}`)))))
      : h('div', { class: 'card empty' }, list.length ? 'Filtreye uyan belge yok' : 'Henüz fatura / irsaliye girilmedi'));
  };
  q.addEventListener('input', draw); kind.addEventListener('change', draw);
  clear(view, pageHead('Fatura İrsaliye', { back: '#/' }),
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => invoiceForm({}) }, '＋ Fatura / İrsaliye Gir')),
    stats, h('div', { class: 'filters' }, q, kind, period.el), body);
  draw();
}

function attachFile(d) {
  const input = h('input', { type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic,.xml,.zip', hidden: true });
  input.addEventListener('change', async () => {
    const fd = new FormData(); fd.append('file', input.files[0]);
    try { await upload(`/api/purchasing/invoices/${d.id}/file`, fd); toast('Belge dosyası eklendi'); reload(); } catch (err) { toastError(err); }
  });
  document.body.append(input); input.click(); setTimeout(() => input.remove(), 60000);
}

async function invoiceForm({ request = null, lines = [] }) {
  if (!OPTS) await options();
  if (!OPTS.suppliers.length) { toast('Önce Tedarikçi Yönetimi’nden tedarikçi ekleyin', 'err'); return; }
  const approved = (await api.get('/api/purchasing/requests')).filter(r => r.status === 'ONAYLANDI');
  const kind = h('select', { class: 'input' }, h('option', { value: 'FATURA' }, 'Fatura'), h('option', { value: 'IRSALIYE' }, 'İrsaliye'));
  const number = h('input', { class: 'input mono' });
  const date = h('input', { class: 'input', type: 'date', value: new Date().toLocaleDateString('sv') });
  const sup = h('select', { class: 'input' }, h('option', { value: '' }, 'Tedarikçi seçin'), OPTS.suppliers.map(s => h('option', { value: s.id }, s.name)));
  const dep = h('select', { class: 'input' }, OPTS.warehouses.map((w, i) => h('option', { value: w.id, selected: i === 0 }, w.name)));
  const req = h('select', { class: 'input' }, h('option', { value: '' }, 'Talebe bağlı değil'),
    approved.map(r => h('option', { value: r.id, selected: r.id === request?.id }, `${r.code} · ${r.title}`)));
  const amount = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', placeholder: 'KDV dahil belge tutarı' });
  const note = h('input', { class: 'input' });
  const file = h('input', { class: 'input', type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic,.xml,.zip' });
  const rows = h('tbody');
  const total = h('b');
  const syncTotal = () => {
    const t = [...rows.children].reduce((a, tr) => a + (Number(tr._qty.value) || 0) * (Number(tr._price.value) || 0), 0);
    total.textContent = money(t);
  };
  const addRow = (l = {}) => {
    const mat = materialSelect(l.product_id);
    const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: l.qty ?? '' });
    const price = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', value: l.unit_price ?? '' });
    const unit = h('span', { class: 'muted small' }, l.product_id ? unitOf(l.product_id) : '');
    mat.addEventListener('change', () => { unit.textContent = mat.value ? unitOf(mat.value) : ''; });
    const tr = h('tr', null, h('td', null, mat), h('td', null, h('div', { class: 'row-inline' }, qty, unit)), h('td', null, price),
      h('td', null, h('button', { class: 'btn xs ghost', type: 'button', onclick: () => { tr.remove(); syncTotal(); } }, '✕')));
    tr._mat = mat; tr._qty = qty; tr._price = price;
    [qty, price].forEach(i => i.addEventListener('input', syncTotal));
    rows.append(tr);
  };
  (lines.length ? lines : [{}]).forEach(addRow);
  syncTotal();
  modal({
    title: 'Fatura / İrsaliye Gir', wide: true,
    body: h('div', null,
      h('div', { class: 'form-grid' }, field('Belge türü', kind), field('Belge no', number), field('Belge tarihi', date), field('Tedarikçi *', sup),
        field('Giriş deposu', dep, 'Kalemler bu depoya stok girişi olarak işlenir'), field('Satın alma talebi', req)),
      h('table', { class: 'table pu-lines' }, h('thead', null, h('tr', null, h('th', null, 'Malzeme'), h('th', null, 'Miktar'), h('th', null, 'Birim fiyat (₺)'), h('th', null, ''))), rows),
      h('div', { class: 'row-inline', style: { justifyContent: 'space-between', margin: '6px 0 12px' } },
        h('button', { class: 'btn sm', type: 'button', onclick: () => addRow() }, '＋ Kalem'), h('span', null, 'Kalemler toplamı: ', total)),
      h('div', { class: 'form-grid' }, field('Belge tutarı', amount), field('Belge dosyası', file), field('Not', note))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet ve Depoya Al', class: 'primary', onClick: async () => {
      const lns = [...rows.children].map(tr => ({ product_id: Number(tr._mat.value), qty: Number(tr._qty.value), unit_price: tr._price.value === '' ? null : Number(tr._price.value) }))
        .filter(l => l.product_id || l.qty);
      if (lns.some(l => !l.product_id)) throw new Error('Her kalemde malzeme seçin');
      const { id } = await api.post('/api/purchasing/invoices', { kind: kind.value, number: number.value, doc_date: date.value, company_id: sup.value ? Number(sup.value) : null,
        warehouse_id: Number(dep.value), request_id: req.value ? Number(req.value) : null, amount: amount.value === '' ? null : Number(amount.value), note: note.value, lines: lns });
      if (file.files[0]) { const fd = new FormData(); fd.append('file', file.files[0]); await upload(`/api/purchasing/invoices/${id}/file`, fd).catch(toastError); }
      toast(t('{n} kalem {depot} deposuna girdi', { n: lns.length, depot: dep.selectedOptions[0].textContent }));
      location.hash = '#/purchasing/invoices';
      reload();
    } }],
  });
}

// ---------- Teklif Yönetimi
async function renderQuotes(view) {
  const period = periodFilter('purchaseQuotes', () => renderQuotes(view), { title: 'Açık teklifler her zaman; sonuçlananlar seçilen dönemde' });
  const [list] = await Promise.all([api.get(`/api/purchasing/quotes?${period.qs()}`), options()]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Teklif no, konu, tedarikçi ara…', style: { width: '240px' } });
  const st = selectInput([['TASLAK', 'Taslak'], ['GONDERILDI', 'Firmaya iletildi'], ['KABUL', 'Kabul edildi'], ['RED', 'Reddedildi']], { all: 'Tüm durumlar' });
  let mode = pref('purchasing.quoteView', 'card');
  const body = h('div');
  const draw = () => {
    const rows = list.filter(x => (!st.value || x.status === st.value) && matches(q.value, x.code, x.title, x.company_name, x.request_code));
    if (!rows.length) return clear(body, h('div', { class: 'card empty' }, list.length ? 'Filtreye uyan teklif yok' : 'Henüz teklif yok. “Yeni Teklif” ile başlayın.'));
    clear(body, mode === 'card' ? h('div', { class: 'pu-quotes' }, rows.map(x => h('a', { class: 'card pu-quote', href: `#/purchasing/quotes/${x.id}` },
      h('div', { class: 'tv-bar' }, h('b', { class: 'mono' }, x.code), h('span', { class: 'badge gray' }, `Rev. ${x.revision}`), h('span', { class: 'spacer' }),
        h('span', { class: `badge ${QUOTE_TONE[x.status]}` }, x.status_label)),
      h('div', { class: 'pu-quote-title' }, x.title), h('div', { class: 'small muted' }, x.company_name || ''),
      h('div', { class: 'pu-quote-total' }, money(x.total, x.currency), h('small', null, t('{n} kalem · KDV dahil', { n: x.items.length }))),
      h('div', { class: 'small muted' }, x.sent_at ? t('İletildi {at}', { at: fmtDateTime(x.sent_at) }) : t('Oluşturuldu {at}', { at: fmtDate(x.created_at) }), x.revision_count ? t(' · {n} eski revizyon', { n: x.revision_count }) : ''))))
      : h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, 'Teklif'), h('th', null, 'Konu'), h('th', null, 'Tedarikçi'), h('th', null, 'Rev.'), h('th', { class: 'num' }, 'Toplam'), h('th', null, 'Durum'))),
        h('tbody', null, rows.map(x => h('tr', { class: 'click', onclick: () => { location.hash = `#/purchasing/quotes/${x.id}`; } },
          h('td', { class: 'mono' }, h('b', null, x.code)), h('td', null, x.title), h('td', null, x.company_name || ''), h('td', null, x.revision),
          h('td', { class: 'num' }, money(x.total, x.currency)), h('td', null, h('span', { class: `badge ${QUOTE_TONE[x.status]}` }, x.status_label))))))));
  };
  const seg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('purchasing.quoteView', v); draw(); });
  q.addEventListener('input', draw); st.addEventListener('change', draw);
  clear(view, pageHead('Teklif Yönetimi', { back: '#/' }),
    moduleToolbar(h('button', { class: 'btn primary', onclick: () => quoteForm(null) }, '＋ Yeni Teklif')),
    h('div', { class: 'filters' }, q, st, period.el, h('span', { class: 'spacer' }), seg), body);
  draw();
}

async function quoteForm(x, request = null) {
  if (!OPTS) await options();
  if (!OPTS.suppliers.length) { toast('Önce Tedarikçi Yönetimi’nden tedarikçi ekleyin', 'err'); return; }
  const sup = h('select', { class: 'input' }, h('option', { value: '' }, 'Tedarikçi seçin'), OPTS.suppliers.map(s => h('option', { value: s.id, selected: s.id === x?.company_id }, s.name)));
  const title = h('input', { class: 'input', value: x?.title || (request ? `${request.code} · ${request.title}` : '') });
  const cur = h('select', { class: 'input' }, ['TRY', 'USD', 'EUR'].map(c => h('option', { value: c, selected: c === (x?.currency || 'TRY') }, c)));
  const vat = h('input', { class: 'input', type: 'number', min: 0, max: 100, value: x?.vat_rate ?? 20 });
  const valid = h('input', { class: 'input', type: 'date', value: x?.valid_until || '' });
  const note = h('textarea', { class: 'input', rows: 3 }, x?.note || '');
  modal({
    title: x ? t('{code} · Düzenle', { code: x.code }) : request ? t('{code} için teklif', { code: request.code }) : 'Yeni Teklif',
    body: h('div', null, h('div', { class: 'form-grid' }, field('Tedarikçi *', sup), field('Teklif konusu *', title), field('Para birimi', cur),
      field('KDV (%)', vat), field('Geçerlilik tarihi', valid)), field('Açıklama / koşullar', note),
      request ? h('div', { class: 'small muted' }, 'Talebin kalemleri teklife aktarılır; fiyatları teklif ekranında girin.') : null),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const body = { company_id: Number(sup.value) || 0, title: title.value, currency: cur.value, vat_rate: Number(vat.value) || 0, valid_until: valid.value || null,
        note: note.value, request_id: request?.id || x?.request_id || null };
      if (x) { await api.put(`/api/purchasing/quotes/${x.id}`, body); reload(); return; }
      const { id } = await api.post('/api/purchasing/quotes', body);
      location.hash = `#/purchasing/quotes/${id}`;
    } }],
  });
}

async function renderQuote(view, id, ctx) {
  const [x] = await Promise.all([api.get(`/api/purchasing/quotes/${id}`), options()]);
  const draft = x.status === 'TASLAK';
  const itemForm = it => {
    const mat = materialSelect(it?.product_id);
    mat.querySelector('option').textContent = 'Serbest kalem (malzeme listesinde değil)';
    const desc = h('input', { class: 'input', value: it?.description || '', placeholder: 'Açıklama (malzeme seçilirse adı gelir)' });
    const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: it?.qty ?? '' });
    const unit = h('input', { class: 'input', value: it?.unit || '', placeholder: 'adet', style: { width: '90px' } });
    const price = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', value: it?.unit_price ?? '' });
    const note = h('input', { class: 'input', value: it?.note || '' });
    mat.addEventListener('change', () => { const m = OPTS.materials.find(z => z.id === Number(mat.value)); if (m) { desc.value = m.name; unit.value = m.unit || 'adet'; } });
    modal({
      title: it ? 'Kalemi Düzenle' : 'Teklife Kalem Ekle', wide: true,
      body: h('div', null, field('Malzeme', mat), field('Açıklama', desc),
        h('div', { class: 'form-grid' }, field('Miktar', qty), field('Birim', unit), field(t('Birim fiyat ({cur})', { cur: x.currency }), price)), field('Not', note)),
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        const body = { product_id: mat.value ? Number(mat.value) : null, description: desc.value, qty: Number(qty.value), unit: unit.value, unit_price: price.value === '' ? null : Number(price.value), note: note.value };
        if (it) await api.put(`/api/purchasing/quotes/${id}/items/${it.id}`, body); else await api.post(`/api/purchasing/quotes/${id}/items`, body);
        reload();
      } }],
    });
  };
  const revise = () => {
    const reason = h('input', { class: 'input', placeholder: 'ör. Tedarikçi fiyat güncelledi, miktar değişti' });
    modal({
      title: t('{code} · Revize Et', { code: x.code }), body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, t('Rev. {rev} saklanır; teklif Rev. {rev2} olarak yeniden düzenlenebilir.', { rev: x.revision, rev2: x.revision + 1 })), field('Revizyon sebebi', reason)),
      actions: [{ label: 'Vazgeç' }, { label: 'Revize Et', class: 'primary', onClick: async () => { await api.post(`/api/purchasing/quotes/${id}/revise`, { reason: reason.value }); toast('Yeni revizyon açıldı'); reload(); } }],
    });
  };
  const setStatus = async s => { try { await api.post(`/api/purchasing/quotes/${id}/status`, { status: s }); reload(); } catch (err) { toastError(err); } };
  const actions = [
    draft ? h('button', { class: 'btn', onclick: () => quoteForm(x) }, 'Düzenle') : null,
    h('button', { class: 'btn', onclick: () => printQuote(x, ctx).catch(toastError) }, '🖨 Yazdır'),
    draft ? h('button', { class: 'btn primary', onclick: () => sendQuote(x, ctx) }, 'Firmaya İlet') : null,
    x.status === 'GONDERILDI' ? [h('button', { class: 'btn', onclick: () => setStatus('KABUL') }, 'Kabul Edildi'), h('button', { class: 'btn', onclick: () => setStatus('RED') }, 'Reddedildi')] : null,
    !draft ? h('button', { class: 'btn primary', onclick: revise }, 'Revize Et') : null,
  ];
  clear(view,
    pageHead(`${x.code} · ${x.title}`, { back: '#/purchasing/quotes', sub: t('Satın Alma · Teklif Yönetimi · Rev. {rev}', { rev: x.revision }) }),
    moduleToolbar(actions),
    h('div', { class: 'card card-pad pu-head' }, h('dl', { class: 'hr-kv' },
      h('dt', null, 'Durum'), h('dd', null, h('span', { class: `badge ${QUOTE_TONE[x.status]}` }, x.status_label), x.sent_to ? ` · ${x.sent_to}` : '', x.sent_at ? ` · ${fmtDateTime(x.sent_at)}` : ''),
      h('dt', null, 'Tedarikçi'), h('dd', null, x.company_name || '—'),
      h('dt', null, 'Revizyon'), h('dd', null, `Rev. ${x.revision}`),
      x.valid_until ? [h('dt', null, 'Geçerlilik'), h('dd', null, fmtDate(x.valid_until))] : null,
      x.request_code ? [h('dt', null, 'Talep'), h('dd', null, h('a', { href: `#/purchasing/requests/${x.request_id}` }, x.request_code))] : null,
      x.note ? [h('dt', null, 'Açıklama'), h('dd', { class: 'pre' }, x.note)] : null,
      h('dt', null, 'Hazırlayan'), h('dd', null, `${x.created_by_name || ''} · ${fmtDateTime(x.created_at)}`)),
    !draft ? h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Firmaya iletilen teklif değiştirilemez; değişiklik için “Revize Et”.') : null),
    h('div', { class: 'card card-pad' },
      h('div', { class: 'tv-bar' }, h('b', null, t('Kalemler ({n})', { n: x.items.length })), h('span', { class: 'spacer' }),
        draft ? h('button', { class: 'btn sm primary', onclick: () => itemForm(null) }, '＋ Kalem Ekle') : null),
      quoteTable(x, draft ? { edit: itemForm, del: async it => { await api.del(`/api/purchasing/quotes/${id}/items/${it.id}`); reload(); } } : null)),
    x.revisions.length ? h('div', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Eski revizyonlar'),
      h('ul', { class: 'stat-list' }, x.revisions.map(r => h('li', null,
        h('a', { href: '#', onclick: e => { e.preventDefault(); showRevision(x, r); } }, h('b', null, `Rev. ${r.revision}`)),
        h('span', { class: 'small muted' }, `${r.reason || 'Sebep yazılmadı'} · ${r.created_by_name || ''} · ${fmtDateTime(r.created_at)}`))))) : null);
}

function quoteTable(x, ops) {
  if (!x.items.length) return h('div', { class: 'empty small' }, 'Kalem yok');
  return h('table', { class: 'table' },
    h('thead', null, h('tr', null, h('th', null, '#'), h('th', null, 'Kalem'), h('th', { class: 'num' }, 'Miktar'), h('th', { class: 'num' }, 'Birim fiyat'),
      h('th', { class: 'num' }, 'Tutar'), ops ? h('th', null, '') : null)),
    h('tbody', null, x.items.map((i, n) => h('tr', null, h('td', { class: 'muted' }, n + 1),
      h('td', null, i.product_code ? h('b', { class: 'mono' }, `${i.product_code} `) : null, i.description, i.note ? h('div', { class: 'small muted' }, i.note) : null),
      h('td', { class: 'num' }, `${num(i.qty)} ${i.unit || ''}`), h('td', { class: 'num' }, i.unit_price != null ? money(i.unit_price, x.currency) : '—'),
      h('td', { class: 'num' }, i.unit_price != null ? money(i.qty * i.unit_price, x.currency) : '—'),
      ops ? h('td', { class: 'actions' }, h('button', { class: 'btn xs', onclick: () => ops.edit(i) }, 'Düzenle'), h('button', { class: 'btn xs ghost', onclick: () => ops.del(i) }, '✕')) : null))),
    h('tfoot', null,
      h('tr', null, h('td', { colspan: 4, class: 'num' }, 'Ara toplam'), h('td', { class: 'num' }, money(x.subtotal, x.currency)), ops ? h('td') : null),
      h('tr', null, h('td', { colspan: 4, class: 'num' }, `KDV %${num(x.vat_rate)}`), h('td', { class: 'num' }, money(x.vat, x.currency)), ops ? h('td') : null),
      h('tr', null, h('td', { colspan: 4, class: 'num' }, h('b', null, 'Genel toplam')), h('td', { class: 'num' }, h('b', null, money(x.total, x.currency))), ops ? h('td') : null)));
}

async function showRevision(x, r) {
  const d = await api.get(`/api/purchasing/quotes/${x.id}/revisions/${r.id}`);
  modal({
    title: `${x.code} · Rev. ${d.revision}`, wide: true,
    body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } },
      t('{title} · {company} · {status}{sent} · revize edildi {at}{reason}', { title: d.title, company: d.company_name || '', status: d.status_label, sent: d.sent_at ? t(' · iletildi {at}{to}', { at: fmtDateTime(d.sent_at), to: d.sent_to ? ` (${d.sent_to})` : '' }) : '', at: fmtDateTime(d.revised_at), reason: d.revision_reason ? ` — ${d.revision_reason}` : '' })),
    quoteTable({ ...d, items: d.items }, null), d.note ? h('p', { class: 'pre small' }, d.note) : null),
    actions: [{ label: 'Kapat' }],
  });
}

// Teklif belgesi (yazdırma ve e-posta eki için)
function quoteDoc(x, company) {
  return h('div', { class: 'mp-doc' },
    printHead(company, 'TEKLİF', [['Teklif no', `${x.code} / Rev. ${x.revision}`], ['Tarih', fmtDate(new Date().toISOString())], ['Firma', x.company_name || ''],
      ...(x.valid_until ? [['Geçerlilik', fmtDate(x.valid_until)]] : [])]),
    h('section', { class: 'mp-sec' }, h('h2', null, x.title), quoteTable(x, null)),
    x.note ? h('section', { class: 'mp-sec' }, h('h2', null, 'Açıklama / koşullar'), h('div', { class: 'mp-pre' }, x.note)) : null,
    foot(company, `${x.code} · Rev. ${x.revision}`));
}

async function printQuote(x) {
  const company = (await api.get('/api/meta').catch(() => ({}))).company || '';
  printPage(quoteDoc(x, company), `Teklif ${x.code}`);
}

// Firmaya ilet: e-postayla (bağlı Gmail hesabından, teklif HTML eki olarak) ya da "iletildi" olarak işaretle
async function sendQuote(x) {
  if (!x.items.length) { toast('Önce teklife kalem ekleyin', 'err'); return; }
  const company = (await api.get('/api/meta').catch(() => ({}))).company || '';
  const to = h('input', { class: 'input', type: 'email', value: x.company_email || '', placeholder: 'firma@ornek.com' });
  const subject = h('input', { class: 'input', value: `${company} · Teklif ${x.code} (Rev. ${x.revision}) · ${x.title}` });
  const msg = h('textarea', { class: 'input', rows: 5 }, `Merhaba,\n\n${x.title} konulu teklifimiz ektedir.\n\nSaygılarımızla,\n${company}`);
  const markOnly = async () => { await api.post(`/api/purchasing/quotes/${x.id}/sent`, { sent_to: to.value || 'elden / yazdırılarak' }); toast('Teklif firmaya iletildi olarak işaretlendi'); reload(); };
  modal({
    title: t('{code} · Firmaya İlet', { code: x.code }), wide: true,
    body: h('div', null, field('Alıcı e-posta', to), field('Konu', subject), field('Mesaj', msg),
      h('div', { class: 'small muted' }, 'E-posta, Kişisel › Mail’e bağlı hesabınızdan teklif belgesi (HTML) ekiyle gönderilir. İletildikten sonra teklif değiştirilemez; değişiklik revizyonla yapılır.')),
    actions: [{ label: 'Vazgeç' }, 'spacer', { label: 'Gönderildi Olarak İşaretle', onClick: markOnly },
      { label: 'E-postayla Gönder', class: 'primary', onClick: async () => {
        if (!to.value.trim()) throw new Error('Alıcı e-posta adresini girin');
        const doc = quoteDoc(x, company);
        const css = [...document.styleSheets].flatMap(s => { try { return [...s.cssRules].map(r => r.cssText); } catch { return []; } })
          .filter(t => /\.(mp-|pf-|table)/.test(t)).join('\n');
        const html = `<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Teklif ${x.code}</title><style>body{font-family:system-ui,sans-serif;margin:24px}${css}
          table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left}td.num,th.num{text-align:right}</style></head><body>${doc.outerHTML}</body></html>`;
        const fd = new FormData();
        fd.append('to', to.value.trim()); fd.append('subject', subject.value); fd.append('body', msg.value);
        fd.append('files', new File([html], `Teklif-${x.code}-Rev${x.revision}.html`, { type: 'text/html' }));
        await api.post('/api/mail/send', fd);
        await api.post(`/api/purchasing/quotes/${x.id}/sent`, { sent_to: to.value.trim() });
        toast('Teklif e-postayla gönderildi');
        reload();
      } }],
  });
}
