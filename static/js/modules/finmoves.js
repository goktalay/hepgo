// Finans hareketleri ilgili kaydın detayında gösterilir (ayrı "Hareketler" listesi yok):
// kasa / banka ve cari detayındaki ekstre tablosu, fatura detayındaki "Hareketler" (belge no ile bağlı cari hareketleri +
// muhasebe fişi satırları) ve personel detayındaki "Hesap Hareketleri" (açıklamada adı geçenler + elle bağlanan cari / hesaplar).
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDate, h, matches, modal, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { decideModal, projectChip } from './projdecide.js';

export const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const IN = 'var(--ok,#16a34a)', OUT = 'var(--danger,#dc2626)';
const KIND_LABEL = { satis: 'Satış faturası', alis: 'Alış faturası', FATURA: 'Alış faturası', IRSALIYE: 'İrsaliye' };
const ACC_KIND = { kasa: 'Kasa', banka: 'Banka', cari: 'Cari' };

// Hareket tablosu. cari: Borç/Alacak başlıkları; running: yürüyen bakiye; account: hesap sütunu; onDelete: elle girilen hareket silinir.
export function movesTable(rows, { cari = false, running = false, account = false, onDelete = null, onChange = null, empty = 'Hareket yok.' } = {}) {
  if (!rows.length) return h('div', { class: 'card empty' }, empty);
  const proj = rows.some(r => 'p_nature' in r);   // Proje Yönetimi: her harekette proje kararı
  const head = ['Tarih', account ? 'Hesap' : null, 'Belge', 'Açıklama', cari ? 'Vade' : null, cari ? 'Borç' : 'Giriş', cari ? 'Alacak' : 'Çıkış',
    running ? 'Bakiye' : null, proj ? 'Proje' : null, onDelete ? '' : null].filter(x => x !== null);
  return h('div', { class: 'card table-wrap' }, h('table', { class: 'table fm-table' },
    h('thead', null, h('tr', null, head.map(x => h('th', { class: /Giriş|Çıkış|Borç|Alacak|Bakiye/.test(x) ? 'num' : '' }, x)))),
    h('tbody', null, rows.map(r => h('tr', null,
      h('td', { class: 'nowrap' }, fmtDate(r.date)),
      account ? h('td', null, accountLink(r)) : null,
      h('td', { class: 'small mono' }, r.invoice && canFinance() ? h('button', { class: 'linkish', type: 'button', title: KIND_LABEL[r.invoice.kind] || 'Fatura', onclick: () => invoiceModal(r.invoice) }, `🧾 ${r.doc_no}`) : (r.doc_no || '—')),
      h('td', null, r.description || r.category || '—',
        r.category && r.description && r.category !== r.description ? h('span', { class: 'small muted' }, ` · ${r.category}`) : null,
        r.person ? h('a', { class: 'fm-person', href: `#/hr/${r.person.id}`, title: 'Personel detayı' }, `👤 ${r.person.name}`) : null,
        r.via === 'link' ? h('span', { class: 'badge', title: 'Bağlı hesabın hareketi' }, 'bağlı hesap') : null),
      cari ? h('td', { class: 'small nowrap' }, r.due_date && r.due_date !== r.date ? fmtDate(r.due_date) : '') : null,
      h('td', { class: 'num', style: { color: IN } }, r.direction === 'in' ? money(r.amount) : ''),
      h('td', { class: 'num', style: { color: OUT } }, r.direction === 'out' ? money(r.amount) : ''),
      running ? h('td', { class: 'num', style: { fontWeight: 600, color: r.balance < 0 ? OUT : '' } }, money(r.balance)) : null,
      proj ? h('td', null, r.p_nature ? projectChip(r.ptags, () => decideModal('txn', r.id, onChange || onDelete)) : h('span', { class: 'small muted' }, '—')) : null,
      onDelete ? h('td', null, r.mikro_ref ? null : h('button', { class: 'btn xs ghost', type: 'button', title: 'Sil', onclick: async () => {
        if (!await confirmDialog('Hareketi sil', 'Hareket silinsin mi?', { okLabel: 'Sil', danger: true })) return;
        try { await api.del(`/api/finance/txns/${r.id}`); onDelete(); } catch (e) { toastError(e); }
      } }, '×')) : null)))));
}

function accountLink(r) {
  const href = r.account_kind === 'cari' && r.company_id ? `#/finance/cari/${r.company_id}` : `#/finance/bank/${r.account_id}`;
  return [h('a', { href, onclick: e => { if (!canFinance()) e.preventDefault(); } }, r.account_name), h('div', { class: 'small muted' }, ACC_KIND[r.account_kind] || '')];
}
let FIN = null;
export const setFinanceAccess = v => { FIN = v; };
const canFinance = () => FIN !== false;

// Fatura / belge numarasına bağlı hareketler: cari-kasa-banka hareketleri + muhasebe fişi
export function docMovesPane(m) {
  if (!m.txns.length && !m.ledger.length) {
    return h('div', { class: 'card empty' }, 'Bu belge numarasına bağlı finans hareketi yok. (Hareketler Mikro senkronundaki belge no ile eşleşir.)');
  }
  const dr = m.ledger.reduce((s, l) => s + (l.debit || 0), 0), cr = m.ledger.reduce((s, l) => s + (l.credit || 0), 0);
  return h('div', { class: 'fm-doc' },
    m.txns.length ? [h('h4', { class: 'fm-h' }, 'Cari / kasa / banka hareketleri'), movesTable(m.txns, { account: true })] : null,
    m.ledger.length ? [h('h4', { class: 'fm-h' }, 'Muhasebe fişi'),
      h('div', { class: 'card table-wrap' }, h('table', { class: 'table fm-table' },
        h('thead', null, h('tr', null, ['Tarih', 'Hesap', 'Açıklama', 'Borç', 'Alacak'].map(x => h('th', { class: /Borç|Alacak/.test(x) ? 'num' : '' }, x)))),
        h('tbody', null, m.ledger.map(l => h('tr', null, h('td', { class: 'nowrap' }, fmtDate(l.date)),
          h('td', null, h('b', { class: 'mono small' }, l.account), h('div', { class: 'small muted' }, l.account_name || '')),
          h('td', { class: 'small' }, l.description || '—'),
          h('td', { class: 'num' }, l.debit ? money(l.debit) : ''), h('td', { class: 'num' }, l.credit ? money(l.credit) : '')))),
        h('tfoot', null, h('tr', null, h('th', { colspan: 3 }, 'Toplam'), h('th', { class: 'num' }, money(dr)), h('th', { class: 'num' }, money(cr))))))] : null);
}

export async function docMovesByNumber(root, number) {
  clear(root, h('div', { class: 'loading' }, 'Yükleniyor…'));
  try { clear(root, docMovesPane(await api.get(`/api/finance/docs/moves?number=${encodeURIComponent(number || '')}`))); } catch (e) { clear(root, h('div', { class: 'card empty' }, e.message)); }
}

// Faturayı (Finans içinden) aç: Kalemler | Hareketler
export async function invoiceModal(ref) {
  let x;
  try { x = await api.get(`/api/finance/invoices/${ref.id}?src=${ref.source || 'invoice'}`); } catch (e) { return toastError(e); }
  const pane = h('div');
  const items = () => (x.items.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Açıklama', 'Miktar', 'Birim fiyat', 'Tutar'].map(c => h('th', { class: c === 'Açıklama' ? '' : 'num' }, c)))),
    h('tbody', null, x.items.map(i => h('tr', null, h('td', null, i.description || '—'),
      h('td', { class: 'num' }, `${(i.qty || 0).toLocaleString('tr-TR')} ${i.unit || ''}`), h('td', { class: 'num' }, money(i.unit_price)),
      h('td', { class: 'num' }, money(i.line_total ?? (i.qty || 0) * (i.unit_price || 0)))))))) : h('div', { class: 'empty' }, 'Kalem yok.'));
  let tab = 'moves';
  const draw = () => clear(pane, tab === 'items' ? items() : docMovesPane(x.moves));
  const n = x.moves.txns.length + x.moves.ledger.length;
  modal({ title: x.number || 'Fatura', wide: true, body: h('div', null,
    h('dl', { class: 'hr-kv' }, h('dt', null, 'Tür'), h('dd', null, KIND_LABEL[x.kind] || x.kind), h('dt', null, 'Firma'), h('dd', null, x.company_name || '—'),
      h('dt', null, 'Tarih'), h('dd', null, fmtDate(x.invoice_date)), h('dt', null, 'Toplam'), h('dd', null, h('b', null, money(x.total)))),
    h('div', { class: 'fm-tabs' }, segmented([['moves', t('Hareketler ({n})', { n })], ['items', t('Kalemler ({n})', { n: x.items.length })]], tab, v => { tab = v; draw(); }, { tabs: true })),
    pane), actions: [{ label: 'Kapat', class: 'primary' }] });
  draw();
}

// ---------------- Personel › Hesap Hareketleri ----------------
export async function personPane(root, empId) {
  clear(root, h('div', { class: 'loading' }, 'Yükleniyor…'));
  let d;
  try { d = await api.get(`/api/finance/person/${empId}`); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  setFinanceAccess(d.can_finance);
  const reload = () => personPane(root, empId);
  const strip = statStrip();
  strip.set([{ icon: 'finance', label: 'Kişiye ödenen (kasa / banka)', value: money(d.totals.paid) },
    { icon: 'finance', label: 'Maaş ödemeleri', value: money(d.totals.salary), sub: d.totals.salary_count ? t('{n} ödeme', { n: d.totals.salary_count }) : null },
    { icon: 'calendar', label: 'Son maaş ödemesi', value: d.totals.last_salary ? fmtDate(d.totals.last_salary) : '—' },
    { icon: 'companies', label: 'Bağlı cari / hesap', value: d.links.length }]);
  const linkHref = l => (!d.can_finance ? null : l.kind === 'company' ? `#/finance/cari/${l.ref}` : l.kind === 'account' ? `#/finance/bank/${l.ref}` : null);
  const chip = l => h('span', { class: 'fm-link' }, h('small', null, l.sub || d.kinds[l.kind]),
    linkHref(l) ? h('a', { href: linkHref(l) }, l.label) : h('b', null, l.label),
    l.balance != null ? h('em', { style: { color: l.balance < 0 ? OUT : '' } }, money(l.balance)) : null,
    h('button', { class: 'x', type: 'button', title: 'Bağlantıyı kaldır', onclick: async () => {
      if (!await confirmDialog('Bağlantıyı kaldır', t('“{n}” bu personelden ayrılsın mı?', { n: l.label }), { okLabel: 'Kaldır', danger: true })) return;
      try { await api.del(`/api/finance/person/${empId}/links/${l.id}`); reload(); } catch (e) { toastError(e); }
    } }, '×'));
  const link = async (kind, ref) => { try { await api.post(`/api/finance/person/${empId}/links`, { kind, ref }); toast('Bağlandı', 'success'); reload(); } catch (e) { toastError(e); } };
  const linksBox = h('div', { class: 'card card-pad fm-links' },
    h('div', { class: 'fm-links-h' }, h('b', null, 'Bağlı cari ve hesaplar'),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => linkPicker(empId, reload) }, '＋ Cari / hesap bağla')),
    d.links.length ? h('div', { class: 'fm-chips' }, d.links.map(chip))
      : h('div', { class: 'small muted' }, 'Bağlı cari yok. Personelin Mikro’daki carisini, kullandığı şirket kartını (kasa) ya da muhasebe hesabını (ör. 331 / 335 alt hesabı) bağlayabilirsiniz.'),
    d.suggestions.length ? h('div', { class: 'fm-sugg' }, h('small', { class: 'muted' }, 'Adıyla eşleşen öneriler:'),
      d.suggestions.map(s => h('button', { class: 'fm-sugg-b', type: 'button', title: 'Bağla', onclick: () => link(s.kind, s.ref) }, h('small', null, s.sub), s.label, ' ＋'))) : null,
    h('div', { class: 'small muted', style: { marginTop: '6px' } }, d.name_keys
      ? 'Açıklamasında personelin adı soyadı geçen kasa / banka / cari hareketleri (ör. maaş havaleleri) otomatik listelenir; bağlanan cari ve hesapların tüm hareketleri de eklenir.'
      : 'Ad soyad çok kısa olduğu için isimle otomatik eşleşme yapılmıyor; cari / hesap bağlayın.'));
  let tab = 'txns', q = '';
  const pane = h('div');
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Açıklama, hesap, belge ara…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); draw(); });
  const draw = () => {
    if (tab === 'ledger') {
      const ls = d.ledger.filter(l => matches(q, l.description, l.account, l.account_name, l.doc_no));
      return clear(pane, docMovesPane({ txns: [], ledger: ls }));
    }
    clear(pane, movesTable(d.rows.filter(r => matches(q, r.description, r.account_name, r.category, r.doc_no)), { account: true,
      empty: 'Bu personelle ilişkili hareket bulunamadı. Adı açıklamada geçmiyorsa carisini ya da hesabını bağlayın.' }));
  };
  const tabs = d.ledger.length ? segmented([['txns', t('Hareketler ({n})', { n: d.rows.length })], ['ledger', t('Muhasebe ({n})', { n: d.ledger.length })]], tab,
    v => { tab = v; draw(); }, { tabs: true }) : null;
  clear(root, strip, linksBox, h('div', { class: 'filters' }, tabs || h('b', null, t('Hareketler ({n})', { n: d.rows.length })), h('span', { class: 'spacer' }), search), pane);
  draw();
}

function linkPicker(empId, done) {
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Cari, kasa / banka hesabı ya da muhasebe hesabı (ad veya kod)…' });
  const list = h('div', { class: 'fm-pick' }, h('div', { class: 'small muted' }, 'En az 2 harf yazın.'));
  let timer, m;
  q.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (q.value.trim().length < 2) return clear(list, h('div', { class: 'small muted' }, 'En az 2 harf yazın.'));
      let rows;
      try { rows = await api.get(`/api/finance/person-link-options?q=${encodeURIComponent(q.value.trim())}`); } catch (e) { return clear(list, h('div', { class: 'small muted' }, e.message)); }
      clear(list, rows.length ? rows.map(r => h('button', { class: 'fm-pick-row', type: 'button', onclick: async () => {
        try { await api.post(`/api/finance/person/${empId}/links`, { kind: r.kind, ref: r.ref }); toast('Bağlandı', 'success'); m.close(); done?.(); } catch (e) { toastError(e); }
      } }, h('span', { class: 'badge' }, r.sub), h('span', null, r.label))) : h('div', { class: 'small muted' }, 'Sonuç yok.'));
    }, 250);
  });
  m = modal({ title: 'Personeli cari / hesaba bağla', wide: true, body: h('div', null, field('Ara', q), list), actions: [{ label: 'Kapat' }] });
}
