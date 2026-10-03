// Finans / Ön-Muhasebe: Özet (nakit pozisyonu + grafik), Kasa & Banka, Cariler, nakit akışı, çek/senet, mizan, mali tablolar.
// Ayrı "Hareketler" listesi yok: hareketler ilgili kaydın detayında (hesap / cari detayı, fatura, personel) görünür.
// Cariler = Firma Yönetimi'ndeki firmalar + Satın Alma'daki tedarikçiler (ayrı cari listesi yok); ekstre yürüyen bakiyeyle.
// Mikro ERP aktarımı bu modülde değil, Program Ayarları › Entegrasyonlar'dadır.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDate, h, matches, modal, moduleToolbar, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { chartConfig, loadChart, theme } from './reports.js';
import { invoiceModal, movesTable, setFinanceAccess } from './finmoves.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const SUBS = [['summary', 'Özet'], ['bank', 'Kasa & Banka'], ['cari', 'Cariler'], ['cash', 'Nakit Akışı'],
  ['instruments', 'Çek / Senet'], ['trial', 'Mizan'], ['statements', 'Mali Tablolar']];

export async function render(view, params, ctx) {
  if (params[0] === 'txns') { location.replace('#/finance/bank'); return; }   // eski adres: hareketler artık hesap / cari detayında
  setFinanceAccess(true);
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'summary';
  const id = /^\d+$/.test(params[1] || '') ? Number(params[1]) : null;
  const nav = segmented(SUBS, sub, v => { location.hash = `#/finance/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Finans', { back: '#/', sub: 'Ön muhasebe · kasa-banka, cari, nakit akışı', tabs: nav }), body);
  if (sub === 'bank') return id ? accountDetail(body, id) : accountsView(body, 'bank');
  if (sub === 'cari') return id ? cariDetail(body, id) : cariView(body);
  if (sub === 'cash') return cashView(body);
  if (sub === 'instruments') return instrumentsView(body);
  if (sub === 'trial') return trialView(body);
  if (sub === 'statements') return statementsView(body);
  return summaryView(body);
}

// ---------- Özet ----------
async function summaryView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/finance/summary'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const kpis = [
    { label: 'Nakit (kasa + banka)', value: money(d.cash), tone: d.cash >= 0 ? 'ok' : 'alert' },
    { label: 'Alacak (cari +)', value: money(d.receivable) },
    { label: 'Borç (cari −)', value: money(d.payable), tone: d.payable ? 'alert' : '' },
    { label: 'Bu ay giriş', value: money(d.month_in), tone: 'ok' },
    { label: 'Bu ay çıkış', value: money(d.month_out), tone: 'alert' },
  ];
  const canvas = h('canvas');
  const chartCard = h('section', { class: 'card card-pad' }, h('h3', null, 'Son 6 ay giriş / çıkış'), h('div', { class: 'db-chart', style: { height: '260px' } }, canvas));
  const recent = h('section', { class: 'card card-pad' }, h('h3', null, 'Son hareketler'),
    d.recent.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Tarih', 'Hesap', 'Açıklama', 'Tutar'].map(x => h('th', null, x)))),
      h('tbody', null, d.recent.map(t => h('tr', { class: 'fin-click', onclick: () => { location.hash = t.account_kind === 'cari' && t.company_id ? `#/finance/cari/${t.company_id}` : `#/finance/bank/${t.account_id}`; } },
        h('td', null, fmtDate(t.date)), h('td', null, t.account_name),
        h('td', { class: 'muted' }, t.description || t.category || '—'),
        h('td', { class: 'num', style: { color: t.direction === 'in' ? 'var(--ok,#16a34a)' : 'var(--danger,#dc2626)' } },
          `${t.direction === 'in' ? '+' : '−'}${money(t.amount)}`))))))
      : h('div', { class: 'empty' }, 'Henüz hareket yok. “Kasa & Banka” ya da “Cariler”de hesabı açıp “＋ Hareket” ile ekleyin.'));
  const strip = statStrip(); strip.set(kpis);
  clear(view, strip, chartCard, recent);
  loadChart().then(Chart => {
    const labels = d.series.map(s => s.ay);
    new Chart(canvas, chartConfig({ type: 'bar', labels,
      datasets: [{ label: 'Giriş', data: d.series.map(s => s.giris) }, { label: 'Çıkış', data: d.series.map(s => s.cikis) }] }, theme(), true));
  }).catch(() => {});
}

// ---------- Kasa & Banka / Cari hesap listesi ----------
async function accountsView(view, group) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  const kinds = ['kasa', 'banka'];
  let list = [];
  const load = async () => {
    try {
      const all = await Promise.all(kinds.map(k => api.get(`/api/finance/accounts?kind=${k}`)));
      list = all.flat();
    } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ara…', style: { maxWidth: '220px' } });
  q.addEventListener('input', draw);
  const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => accountForm(null, load) }, '＋ Hesap Ekle');
  const out = h('div');

  function draw() {
    const rows = list.filter(a => matches(q.value, a.name, a.company_name, a.bank, a.iban));
    const total = rows.reduce((s, a) => s + (a.balance || 0), 0);
    clear(out, rows.length ? h('div', { class: 'fin-cards' }, rows.map(a => h('button', {
      class: 'card fin-acc', type: 'button', onclick: () => { location.hash = `#/finance/bank/${a.id}`; },
    },
      h('div', { class: 'fin-acc-top' }, h('b', null, a.name),
        h('span', { class: `badge ${a.kind === 'kasa' ? 'green' : a.kind === 'banka' ? 'blue' : ''}` }, a.kind)),
      a.company_name ? h('div', { class: 'small muted' }, a.company_name) : (a.bank ? h('div', { class: 'small muted' }, a.bank) : null),
      a.iban ? h('div', { class: 'small muted mono' }, a.iban) : null,
      h('div', { class: 'fin-bal', style: { color: a.balance >= 0 ? 'var(--text)' : 'var(--danger,#dc2626)' } }, money(a.balance)))))
      : h('div', { class: 'card empty' }, 'Kasa / banka hesabı yok.'),
    rows.length ? h('div', { class: 'fin-total' }, 'Toplam: ', h('b', null, money(total))) : null);
  }
  clear(view, moduleToolbar(addBtn), h('div', { class: 'filters' }, q), out);
  await load();
}

function accountForm(acc, done) {
  const kind = h('select', { class: 'input' }, [['kasa', 'Kasa'], ['banka', 'Banka']].map(([v, l]) => h('option', { value: v, selected: acc?.kind === v }, l)));
  const name = h('input', { class: 'input', value: acc?.name || '', placeholder: 'Ör. Merkez Kasa, Ziraat TL' });
  const bank = h('input', { class: 'input', value: acc?.bank || '', placeholder: 'Banka' });
  const iban = h('input', { class: 'input', value: acc?.iban || '', placeholder: 'TR..' });
  const opening = h('input', { class: 'input', type: 'number', step: '0.01', value: acc?.opening ?? 0 });
  modal({
    title: acc ? 'Hesabı düzenle' : 'Yeni kasa / banka hesabı',
    body: h('div', null, field('Tür', kind), field('Ad', name), field('Banka', bank), field('IBAN', iban), field('Açılış bakiyesi', opening)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      if (!name.value.trim()) throw new Error('Ad girin');
      const payload = { kind: kind.value, name: name.value.trim(), bank: bank.value || null, iban: iban.value || null, opening: Number(opening.value) || 0 };
      if (acc) await api.put(`/api/finance/accounts/${acc.id}`, payload); else await api.post('/api/finance/accounts', payload);
      toast('Kaydedildi'); done?.();
    } }],
  });
}

// ---------- Cariler = firmalar / tedarikçiler ----------
async function cariView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let list = [], kind = '-1';
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Firma, vergi no, telefon ara…', style: { maxWidth: '240px' } });
  const seg = segmented([['-1', 'Hepsi'], ['0', 'Müşteriler'], ['1', 'Tedarikçiler']], kind, v => { kind = v; load(); });
  const onlyBal = h('label', { class: 'check' }, h('input', { type: 'checkbox', onchange: () => draw() }), 'Bakiyesi olanlar');
  const out = h('div');
  const load = async () => {
    try { list = await api.get(`/api/finance/cari?supplier=${kind}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  function draw() {
    const nz = onlyBal.querySelector('input').checked;
    const rows = list.filter(c => matches(q.value, c.name, c.tax_no, c.phone)).filter(c => !nz || Math.abs(c.balance) > 0.004);
    const rec = rows.filter(c => c.balance > 0).reduce((a, c) => a + c.balance, 0), pay = rows.filter(c => c.balance < 0).reduce((a, c) => a - c.balance, 0);
    clear(out, rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Firma', 'Tür', 'Vergi no', 'Son hareket', 'Bakiye'].map(x => h('th', null, x)))),
      h('tbody', null, rows.map(c => h('tr', { class: 'fin-click', onclick: () => { location.hash = `#/finance/cari/${c.id}`; } },
        h('td', null, h('b', null, c.name), c.phone ? h('div', { class: 'small muted' }, c.phone) : null),
        h('td', null, c.is_supplier ? h('span', { class: 'badge yellow' }, 'Tedarikçi') : h('span', { class: 'badge blue' }, 'Müşteri')),
        h('td', { class: 'mono small' }, c.tax_no || '—'), h('td', { class: 'muted' }, c.last_date ? fmtDate(c.last_date) : '—'),
        h('td', { class: 'num', style: { fontWeight: 700, color: c.balance > 0 ? 'var(--ok,#16a34a)' : c.balance < 0 ? 'var(--danger,#dc2626)' : 'var(--muted)' } },
          money(c.balance)))))))) : h('div', { class: 'card empty' }, 'Firma bulunamadı.'),
    h('div', { class: 'fin-total' }, 'Alacak: ', h('b', null, money(rec)), ' · Borç: ', h('b', null, money(pay))));
  }
  q.addEventListener('input', draw);
  clear(view, h('div', { class: 'filters' }, q, seg, onlyBal), out,
    h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Cariler, Firma Yönetimi’ndeki firmalar ve Satın Alma’daki tedarikçilerdir. Yeni cari için firmayı oradan ekleyin; Mikro aktarımı Program Ayarları › Entegrasyonlar’dadır.'));
  await load();
}

// ---------- Kasa / banka hesabı detayı: hesap bilgisi + hareketler ----------
const loadingCard = el => clear(el, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
function periodBar(onChange) {
  const st = { from: '', to: '', q: '' };
  const from = h('input', { class: 'input', type: 'date', title: 'Başlangıç' }), to = h('input', { class: 'input', type: 'date', title: 'Bitiş' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Açıklama, belge no ara…', style: { maxWidth: '240px' } });
  from.addEventListener('change', () => { st.from = from.value; onChange(true); });
  to.addEventListener('change', () => { st.to = to.value; onChange(true); });
  q.addEventListener('input', () => { st.q = q.value.trim(); onChange(false); });
  st.el = h('div', { class: 'filters' }, from, to, q);
  st.qs = () => `date_from=${st.from}&date_to=${st.to}`;
  return st;
}

async function accountDetail(view, id) {
  loadingCard(view);
  let d;
  const out = h('div'), head = h('div');
  const pb = periodBar(reload => (reload ? load() : draw()));
  async function load() {
    try { d = await api.get(`/api/finance/accounts/${id}/detail?${pb.qs()}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
    const a = d.account;
    const strip = statStrip();
    strip.set([{ label: 'Bakiye', value: money(a.balance), tone: a.balance < 0 ? 'alert' : 'ok' }, { label: 'Toplam giriş', value: money(d.kpi.in) },
      { label: 'Toplam çıkış', value: money(d.kpi.out) }, { label: 'Bu ay giriş', value: money(d.kpi.month_in) }, { label: 'Bu ay çıkış', value: money(d.kpi.month_out) }]);
    clear(head, h('div', { class: 'cf-head' }, h('a', { class: 'small', href: '#/finance/bank' }, '← Kasa & Banka')),
      h('section', { class: 'card card-pad fin-dhead' },
        h('div', null, h('div', { class: 'fin-dtitle' }, h('h2', null, a.name), h('span', { class: `badge ${a.kind === 'kasa' ? 'green' : 'blue'}` }, a.kind)),
          h('div', { class: 'small muted' }, [a.bank, a.iban, a.mikro_code ? `Mikro: ${a.mikro_code}` : null].filter(Boolean).join(' · ') || '—')),
        h('div', { class: 'ct-acts' }, h('button', { class: 'btn sm', type: 'button', onclick: () => accountForm(a, load) }, 'Düzenle'),
          h('button', { class: 'btn sm primary', type: 'button', onclick: () => txnForm(a, load) }, '＋ Hareket'))),
      strip, pb.el);
    draw();
  }
  function draw() {
    const rows = d.rows.filter(r => matches(pb.q, r.description, r.category, r.doc_no, r.person?.name));
    clear(out, h('h3', { class: 'fin-h3' }, t('Hareketler ({n})', { n: rows.length })), movesTable(rows, { running: true, onDelete: load, empty: 'Bu dönemde hareket yok.' }));
  }
  clear(view, head, out);
  await load();
}

// ---------- Cari detayı: bakiye, hareketler (ekstre), faturalar, açık kalemler, çek / senet ----------
async function cariDetail(view, cid) {
  loadingCard(view);
  let d, tab = 'moves';
  const out = h('div'), head = h('div');
  const pb = periodBar(reload => (reload ? load() : draw()));
  async function load() {
    try { d = await api.get(`/api/finance/cari/${cid}/detail?${pb.qs()}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
    const c = d.company, b = d.account.balance;
    const strip = statStrip();
    strip.set([{ label: b > 0 ? 'Bakiye (alacaklıyız)' : b < 0 ? 'Bakiye (borçluyuz)' : 'Bakiye', value: money(Math.abs(b)), tone: b < 0 ? 'alert' : b > 0 ? 'ok' : '' },
      { label: 'Toplam borç', value: money(d.kpi.in) }, { label: 'Toplam alacak', value: money(d.kpi.out) },
      { label: 'Açık kalem', value: money(d.kpi.open_rec + d.kpi.open_pay), sub: t('{n} kalem', { n: d.open_items.length }) },
      { label: 'Vadesi geçen', value: money(d.kpi.overdue), tone: d.kpi.overdue > 0 ? 'alert' : '' }]);
    const tabs = segmented([['moves', t('Hareketler ({n})', { n: d.rows.length })], ['invoices', t('Faturalar ({n})', { n: d.invoices.length })],
      ['open', t('Açık kalemler ({n})', { n: d.open_items.length })], ['instruments', t('Çek / Senet ({n})', { n: d.instruments.length })]], tab, v => { tab = v; draw(); }, { tabs: true });
    clear(head, h('div', { class: 'cf-head' }, h('a', { class: 'small', href: '#/finance/cari' }, '← Cariler')),
      h('section', { class: 'card card-pad fin-dhead' },
        h('div', null, h('div', { class: 'fin-dtitle' }, h('h2', null, c.name), c.is_supplier ? h('span', { class: 'badge yellow' }, 'Tedarikçi') : h('span', { class: 'badge blue' }, 'Müşteri')),
          h('div', { class: 'small muted' }, [c.tax_office && c.tax_no ? `${c.tax_office} · ${c.tax_no}` : c.tax_no, c.phone, c.email].filter(Boolean).join(' · ') || '—')),
        h('div', { class: 'ct-acts' }, h('a', { class: 'btn sm', href: `#/companies/${cid}` }, 'Firma kartı'),
          h('button', { class: 'btn sm primary', type: 'button', onclick: () => txnForm({ ...d.account, cari: true }, load) }, '＋ Hareket'))),
      strip, h('div', { class: 'cf-tabs' }, tabs));
    draw();
  }
  function draw() {
    pb.el.hidden = tab !== 'moves';   // tarih / arama süzgeci yalnız Hareketler sekmesinde
    if (tab === 'invoices') {
      return clear(out, d.invoices.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Tarih', 'Belge no', 'Tür', 'Toplam', ''].map(x => h('th', { class: x === 'Toplam' ? 'num' : '' }, x)))),
        h('tbody', null, d.invoices.map(r => h('tr', { class: 'fin-click', onclick: () => invoiceModal({ id: r.id, source: r.src }) },
          h('td', null, fmtDate(r.date)), h('td', { class: 'mono small' }, r.number || '—'),
          h('td', null, h('span', { class: `badge ${r.kind === 'satis' ? 'blue' : 'yellow'}` }, { satis: 'Satış', alis: 'Alış', FATURA: 'Alış (Satın Alma)', IRSALIYE: 'İrsaliye' }[r.kind] || r.kind),
            r.source === 'mikro' ? h('span', { class: 'badge', style: { marginLeft: '4px' } }, 'Mikro') : null),
          h('td', { class: 'num' }, money(r.total)), h('td', { class: 'small muted' }, r.has_moves ? '↔ hareketli' : '')))))) : h('div', { class: 'card empty' }, 'Bu cariye ait fatura kaydı yok.'));
    }
    if (tab === 'open') {
      return clear(out, d.open_items.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Belge tarihi', 'Vade', 'Belge no', 'Açıklama', 'Taraf', 'Kalan tutar'].map(x => h('th', { class: x === 'Kalan tutar' ? 'num' : '' }, x)))),
        h('tbody', null, d.open_items.map(i => h('tr', null, h('td', null, fmtDate(i.date)),
          h('td', null, fmtDate(i.due), i.late > 0 ? h('div', { class: 'small fin-late' }, t('{n} gün geçti', { n: i.late })) : i.late > -15 ? h('div', { class: 'small muted' }, t('{n} gün kaldı', { n: -i.late })) : null),
          h('td', { class: 'mono small' }, i.doc_no || '—'), h('td', { class: 'small' }, i.description || '—'),
          h('td', null, i.side === 'rec' ? h('span', { class: 'badge green' }, 'Alacağımız') : h('span', { class: 'badge red' }, 'Borcumuz')),
          h('td', { class: 'num' }, h('b', null, money(i.amount)))))))) : h('div', { class: 'card empty' }, 'Açık kalem yok — cari kapanmış.'));
    }
    if (tab === 'instruments') {
      return clear(out, d.instruments.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Vade', 'Tür', 'No', 'Banka', 'Durum', 'Tutar'].map(x => h('th', { class: x === 'Tutar' ? 'num' : '' }, x)))),
        h('tbody', null, d.instruments.map(i => h('tr', null, h('td', null, fmtDate(i.due_date)), h('td', null, `${i.kind === 'cek' ? 'Çek' : 'Senet'} · ${i.direction === 'alinan' ? 'alınan' : 'verilen'}`),
          h('td', { class: 'mono small' }, i.number || '—'), h('td', { class: 'small' }, i.bank || '—'), h('td', null, h('span', { class: 'badge' }, d.instr_status[i.status] || i.status)),
          h('td', { class: 'num' }, money(i.amount))))))) : h('div', { class: 'card empty' }, 'Bu cariye ait çek / senet yok.'));
    }
    const rows = d.rows.filter(r => matches(pb.q, r.description, r.category, r.doc_no));
    clear(out, movesTable(rows, { cari: true, running: true, onDelete: load, empty: 'Bu dönemde hareket yok.' }));
  }
  clear(view, head, pb.el, out);
  await load();
}

function txnForm(acc, done) {
  let dirVal = 'in';
  // Cari: bakiye + = firmanın bize borcu (alacağımız). Borç = fatura kestik / ödeme yaptık; Alacak = tahsilat / fatura aldık.
  const isCari = acc?.kind === 'cari' || acc?.cari;
  const dir = segmented([['in', isCari ? 'Borç (satış faturası / ödeme yaptık)' : 'Giriş'], ['out', isCari ? 'Alacak (tahsilat / alış faturası)' : 'Çıkış']], 'in', v => { dirVal = v; });
  const date = h('input', { class: 'input', type: 'date', value: new Date().toISOString().slice(0, 10) });
  const amount = h('input', { class: 'input', type: 'number', step: '0.01', placeholder: '0,00' });
  const desc = h('input', { class: 'input', placeholder: 'Açıklama' });
  const cat = h('input', { class: 'input', placeholder: 'Kategori (ops.)' });
  modal({
    title: `${acc.name} · Hareket`,
    body: h('div', null, field('Tür', dir), field('Tarih', date), field('Tutar', amount), field('Açıklama', desc), field('Kategori', cat)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const a = Number(amount.value);
      if (!a || a <= 0) throw new Error('Tutar girin');
      await api.post('/api/finance/txns', { account_id: acc.id, date: date.value, direction: dirVal, amount: a, description: desc.value || null, category: cat.value || null });
      toast('Hareket eklendi'); done?.();
    } }],
  });
}

// ================= Finans v2 =================
const today = () => new Date().toISOString().slice(0, 10);
const yearStart = () => `${new Date().getFullYear()}-01-01`;
const dt = (v, onChange) => { const i = h('input', { class: 'input', type: 'date', value: v, style: { width: 'auto' } }); i.addEventListener('change', onChange); return i; };
const short = n => {
  const a = Math.abs(n || 0), sg = n < 0 ? '−' : '';
  if (a >= 1e9) return `${sg}${(a / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 2 })}\u00a0Mr\u00a0₺`;
  if (a >= 1e6) return `${sg}${(a / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}\u00a0Mn\u00a0₺`;
  if (a >= 1e4) return `${sg}${(a / 1e3).toLocaleString('tr-TR', { maximumFractionDigits: 0 })}\u00a0B\u00a0₺`;
  return money(n);
};
const kpi = (label, n, tone) => ({ label, value: short(n), sub: Math.abs(n || 0) >= 1e4 ? money(n) : null, tone });
const num0 = n => new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n || 0);
const noLedger = () => h('div', { class: 'card card-pad ct-note' }, h('b', null, 'Muhasebe verisi yok. '),
  'Mizan ve mali tablolar Mikro ERP muhasebe fişlerinden oluşur. Program Ayarları › Entegrasyonlar › Mikro ERP sayfasında “Finans · Banka · Kasa” sekmesinden senkronize edin (otomatik senkron açıksa kendiliğinden gelir).');

// ---------- Nakit akışı ----------
async function cashView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d;
  try { d = await api.get('/api/finance/cashflow?weeks=12'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const reload = () => cashView(view);
  const strip = statStrip();
  const min = Math.min(...d.weeks.map(w => w.balance), d.cash);
  strip.set([kpi('Bugünkü nakit (kasa + banka)', d.cash, d.cash >= 0 ? 'ok' : 'alert'), kpi('Vadesi geçmiş alacak', d.overdue.in, d.overdue.in ? 'alert' : ''),
    kpi('Vadesi geçmiş borç', d.overdue.out, d.overdue.out ? 'alert' : ''), kpi('12 hafta sonu tahmini', d.end_balance, d.end_balance >= 0 ? 'ok' : 'alert'),
    kpi('En düşük nokta', min, min < 0 ? 'alert' : '')]);
  const canvas = h('canvas', { height: 120 });
  const items = d.items.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Tarih', 'Tür', 'Kim / Ne', 'Açıklama', 'Giriş', 'Çıkış'].map(x => h('th', null, x)))),
    h('tbody', null, d.items.map(i => h('tr', null, h('td', null, fmtDate(i.date)), h('td', null, h('span', { class: `badge ${i.dir === 'in' ? 'green' : ''}` }, i.kind)),
      h('td', null, i.label || '—'), h('td', { class: 'muted small' }, i.detail || ''),
      h('td', { class: 'num', style: { color: 'var(--ok,#16a34a)' } }, i.dir === 'in' ? money(i.amount) : ''),
      h('td', { class: 'num', style: { color: 'var(--danger,#dc2626)' } }, i.dir === 'out' ? money(i.amount) : '')))))) :
    h('div', { class: 'empty' }, 'Önümüzdeki 12 haftada vadesi gelen kalem yok.');
  const agingCard = (title, a) => h('section', { class: 'card card-pad fin-aging' }, h('div', { class: 'mk-fin-h', style: { padding: 0 } }, h('b', null, title), h('span', { class: 'small muted' }, `Toplam ${money(a.total)}`)),
    h('div', { class: 'fin-buckets' }, a.labels.map((l, k) => h('div', { class: `fin-bucket b${k}` }, h('small', null, l), h('b', null, money(a.totals[k]))))),
    a.top.length ? h('table', { class: 'table small' }, h('thead', null, h('tr', null, h('th', null, 'Cari'), ...a.labels.map(l => h('th', { class: 'num' }, l)), h('th', { class: 'num' }, 'Toplam'))),
      h('tbody', null, a.top.map(r => h('tr', null, h('td', null, r.name), ...r.buckets.map(v => h('td', { class: 'num' }, v ? num0(v) : '')), h('td', { class: 'num' }, h('b', null, num0(r.total))))))) : null);
  const payday = h('input', { class: 'input', type: 'number', min: 0, max: 28, value: d.settings.payday || '', placeholder: 'yok', style: { width: '80px' } });
  payday.addEventListener('change', async () => { try { await api.put('/api/finance/settings', { payday: Number(payday.value) || 0, salaries: true }); toast('Maaş günü kaydedildi', 'success'); reload(); } catch (e) { toastError(e); } });
  clear(view,
    moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => planForm(reload) }, '＋ Planlı ödeme / tahsilat'),
      h('button', { class: 'btn', type: 'button', onclick: () => plansModal(reload) }, 'Planlı kalemler'),
      h('label', { class: 'small muted', style: { display: 'inline-flex', alignItems: 'center', gap: '6px' } }, 'Maaş günü (ayın):', payday)),
    strip,
    h('section', { class: 'card card-pad' }, h('div', { class: 'mk-fin-h', style: { padding: 0 } }, h('b', null, 'Haftalık nakit akışı (12 hafta)'),
      h('span', { class: 'small muted' }, 'Açık alacak/borç vadeleri (FIFO), çek/senet, planlı kalemler ve maaş günü')), canvas),
    h('div', { class: 'fin-two' }, agingCard('Alacak yaşlandırma', d.aging_rec), agingCard('Borç yaşlandırma', d.aging_pay)),
    h('section', { class: 'card' }, h('div', { class: 'mk-fin-h' }, h('b', null, 'Yaklaşan kalemler'), h('span', { class: 'small muted' }, `${d.items_total} kalem`)), items));
  loadChart().then(Chart => {
    const cfg = chartConfig({ type: 'bar', labels: d.weeks.map(w => fmtDate(w.start).slice(0, 5)),
      datasets: [{ label: 'Giriş', data: d.weeks.map(w => w.in) }, { label: 'Çıkış', data: d.weeks.map(w => w.out) }] }, theme(), true);
    Object.assign(cfg.data.datasets[0], { backgroundColor: '#22c55e', borderColor: '#22c55e' });
    Object.assign(cfg.data.datasets[1], { backgroundColor: '#ef4444', borderColor: '#ef4444' });
    cfg.data.datasets.push({ type: 'line', label: 'Tahmini nakit', data: d.weeks.map(w => w.balance), borderColor: '#7c3aed', backgroundColor: '#7c3aed',
      borderWidth: 2.5, pointRadius: 3, tension: .3 });
    new Chart(canvas, cfg);
  }).catch(() => {});
}

function planForm(done) {
  const date = h('input', { class: 'input', type: 'date', value: today() });
  let dir = 'out';
  const dirSeg = segmented([['out', 'Ödeme'], ['in', 'Tahsilat']], 'out', v => { dir = v; });
  const amount = h('input', { class: 'input', type: 'number', step: '0.01' });
  const desc = h('input', { class: 'input', placeholder: 'ör. Kira, kredi taksidi, SGK primi' });
  const cat = h('input', { class: 'input', placeholder: 'Kategori (ops.)' });
  const rep = h('select', { class: 'input' }, h('option', { value: 'none' }, 'Tek sefer'), h('option', { value: 'monthly' }, 'Her ay'));
  const until = h('input', { class: 'input', type: 'date' });
  modal({ title: 'Planlı ödeme / tahsilat', body: h('div', null, field('Yön', dirSeg), field('Tarih', date), field('Tutar', amount), field('Açıklama', desc),
      field('Kategori', cat), field('Tekrar', rep), field('Bitiş (her ay için, ops.)', until)),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      await api.post('/api/finance/plans', { date: date.value, direction: dir, amount: Number(amount.value), description: desc.value, category: cat.value || null, repeat: rep.value, until: until.value || null });
      toast('Kaydedildi', 'success'); done?.();
    } }] });
}

async function plansModal(done) {
  let rows; try { rows = await api.get('/api/finance/plans'); } catch (e) { return toastError(e); }
  const m = modal({ title: 'Planlı kalemler', wide: true, body: rows.length ? h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Tarih', 'Açıklama', 'Tekrar', 'Tutar', ''].map(x => h('th', null, x)))),
    h('tbody', null, rows.map(r => h('tr', null, h('td', null, fmtDate(r.date)), h('td', null, r.description, r.category ? h('div', { class: 'small muted' }, r.category) : null),
      h('td', null, r.repeat === 'monthly' ? `Her ay${r.until ? ` · ${fmtDate(r.until)}’e kadar` : ''}` : 'Tek sefer'),
      h('td', { class: 'num', style: { color: r.direction === 'in' ? 'var(--ok,#16a34a)' : 'var(--danger,#dc2626)' } }, `${r.direction === 'in' ? '+' : '−'}${money(r.amount)}`),
      h('td', null, h('button', { class: 'btn sm ghost', type: 'button', onclick: async () => { await api.del(`/api/finance/plans/${r.id}`); m.close(); done?.(); } }, 'Sil')))))) :
    h('div', { class: 'empty' }, 'Planlı kalem yok.'), actions: [{ label: 'Kapat' }] });
}

// ---------- Çek / senet ----------
async function instrumentsView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let d, firms = [];
  try { [d, firms] = await Promise.all([api.get('/api/finance/instruments'), api.get('/api/finance/cari')]); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const reload = () => instrumentsView(view);
  const open = d.rows.filter(r => ['portfoy', 'tahsilde', 'teminatta'].includes(r.status));
  const sum = (dir) => open.filter(r => r.direction === dir).reduce((a, r) => a + r.amount, 0);
  const strip = statStrip();
  strip.set([kpi('Portföydeki alınan çek/senet', sum('alinan')), kpi('Ödenecek verilen çek/senet', sum('verilen'), sum('verilen') ? 'alert' : ''),
    kpi('Bu ay vadesi gelen', open.filter(r => r.due_date.slice(0, 7) === today().slice(0, 7)).reduce((a, r) => a + r.amount, 0))]);
  const ST = d.statuses;
  const tone = { portfoy: 'blue', tahsilde: 'yellow', teminatta: 'yellow', ciro: '', tahsil: 'green', odendi: 'green', karsiliksiz: 'red', iade: '' };
  clear(view,
    moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => instrForm(null, firms, ST, reload) }, '＋ Çek / senet')),
    strip,
    d.rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Vade', 'Tür', 'No', 'Cari / keşideci', 'Banka', 'Tutar', 'Durum', ''].map(x => h('th', null, x)))),
      h('tbody', null, d.rows.map(r => {
        const late = ['portfoy', 'tahsilde', 'teminatta'].includes(r.status) && r.due_date < today();
        return h('tr', null, h('td', { class: late ? 'fin-late' : '' }, fmtDate(r.due_date)),
          h('td', null, `${r.direction === 'alinan' ? 'Alınan' : 'Verilen'} ${r.kind === 'cek' ? 'çek' : 'senet'}`),
          h('td', { class: 'mono small' }, r.number || '—'), h('td', null, r.company || r.drawer || '—'), h('td', { class: 'small' }, r.bank || '—'),
          h('td', { class: 'num' }, money(r.amount)), h('td', null, h('span', { class: `badge ${tone[r.status] || ''}` }, ST[r.status] || r.status)),
          h('td', null, h('button', { class: 'btn sm', type: 'button', onclick: () => instrForm(r, firms, ST, reload) }, 'Düzenle')));
      })))) : h('div', { class: 'card empty' }, 'Kayıtlı çek / senet yok. “＋ Çek / senet” ile ekleyin; vadeleri nakit akışına otomatik girer.'));
}

function instrForm(r, firms, ST, done) {
  r = r || { kind: 'cek', direction: 'alinan', status: 'portfoy', due_date: today() };
  let kind = r.kind, dir = r.direction;
  const kindSeg = segmented([['cek', 'Çek'], ['senet', 'Senet']], kind, v => { kind = v; });
  const dirSeg = segmented([['alinan', 'Alınan (müşteriden)'], ['verilen', 'Verilen (tedarikçiye)']], dir, v => { dir = v; });
  const number = h('input', { class: 'input', value: r.number || '' });
  const bank = h('input', { class: 'input', value: r.bank || '', placeholder: 'Banka / şube' });
  const drawer = h('input', { class: 'input', value: r.drawer || '', placeholder: 'Keşideci / borçlu' });
  const company = h('select', { class: 'input' }, h('option', { value: '' }, '— cari seçin (ops.) —'), firms.map(f => h('option', { value: f.id, selected: f.id === r.company_id }, f.name)));
  const amount = h('input', { class: 'input', type: 'number', step: '0.01', value: r.amount || '' });
  const issue = h('input', { class: 'input', type: 'date', value: r.issue_date || '' });
  const due = h('input', { class: 'input', type: 'date', value: r.due_date || '' });
  const status = h('select', { class: 'input' }, Object.entries(ST).map(([k, l]) => h('option', { value: k, selected: k === r.status }, l)));
  const note = h('input', { class: 'input', value: r.note || '' });
  const actions = [{ label: 'Vazgeç' }];
  if (r.id) actions.push({ label: 'Sil', class: 'danger', onClick: async () => { if (!await confirmDialog('Sil', 'Kayıt silinsin mi?', { okLabel: 'Sil', danger: true })) return true; await api.del(`/api/finance/instruments/${r.id}`); done?.(); } });
  actions.push({ label: 'Kaydet', class: 'primary', onClick: async () => {
    const b = { kind, direction: dir, number: number.value, bank: bank.value, drawer: drawer.value, company_id: company.value ? Number(company.value) : null,
      amount: Number(amount.value), issue_date: issue.value || null, due_date: due.value, status: status.value, note: note.value };
    if (r.id) await api.put(`/api/finance/instruments/${r.id}`, b); else await api.post('/api/finance/instruments', b);
    toast('Kaydedildi', 'success'); done?.();
  } });
  modal({ title: r.id ? 'Çek / senet' : 'Yeni çek / senet', wide: true,
    body: h('div', { class: 'fin-form2' }, field('Tür', kindSeg), field('Yön', dirSeg), field('Cari', company), field('Keşideci / borçlu', drawer),
      field('Çek / senet no', number), field('Banka', bank), field('Tutar (TL)', amount), field('Düzenleme tarihi', issue), field('Vade', due),
      field('Durum', status), field('Not', note)), actions });
}

// ---------- Mizan (ağaç) ----------
// Tekdüzen hiyerarşi: 1 → 10 → 100 → 100.01 → 100.01.0001. ▸/▾ ile açılıp kapanır; seviye seçimi o derinliğe kadar açar;
// arama eşleşen hesapları üst hesaplarıyla birlikte gösterir; satıra dokununca hesap ekstresi.
const ancestorsOf = code => {
  const [head, ...rest] = String(code).split('.');
  const out = [];
  for (let i = 1; i <= Math.min(3, head.length); i++) out.push(head.slice(0, i));
  if (head.length > 3) out.push(head);
  let cur = head;
  for (const seg of rest) { cur = `${cur}.${seg}`; out.push(cur); }
  return out;
};
async function trialView(view) {
  let from = yearStart(), to = today(), q = '', d = null;
  let expanded = new Set();
  const levelSel = h('select', { class: 'input', style: { width: 'auto' } }, [[1, 'Sınıflar'], [2, 'Gruplar'], [3, 'Ana hesaplar'], [4, 'Alt hesaplar'], [9, 'Tüm detay']]
    .map(([v, l]) => h('option', { value: v, selected: v === 2 }, l)));
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Hesap kodu / adı ara…', style: { maxWidth: '220px' } });
  const out = h('div');
  const openTo = lvl => { expanded = new Set(d.rows.filter(r => r.depth < lvl && r.has_children).map(r => r.code)); };
  function draw() {
    if (!d) return;
    let rows;
    if (q) {   // arama: eşleşenler + üst hesapları
      const keep = new Set();
      d.rows.filter(r => matches(q, r.code, r.name)).forEach(r => ancestorsOf(r.code).forEach(c => keep.add(c)));
      rows = d.rows.filter(r => keep.has(r.code));
    } else {
      rows = d.rows.filter(r => ancestorsOf(r.code).slice(0, -1).every(c => expanded.has(c)));
    }
    const tbody = h('tbody', null, rows.map(r => {
      const open = q || expanded.has(r.code);
      const caret = r.has_children ? h('button', { class: `fin-caret ${open ? 'open' : ''}`, type: 'button', title: open ? 'Kapat' : 'Aç',
        onclick: e => { e.stopPropagation(); if (q) return; expanded.has(r.code) ? expanded.delete(r.code) : expanded.add(r.code); draw(); } }, '▸')
        : h('span', { class: 'fin-caret leaf' });
      return h('tr', { class: `d${Math.min(r.depth, 5)} ${r.has_children ? 'grp' : ''}`, onclick: () => ledgerModal(r.code, r.name, from, to) },
        h('td', { class: 'fin-tree-cell' }, h('span', { class: 'fin-tree', style: { paddingLeft: `${(r.depth - 1) * 18}px` } }, caret,
          h('span', { class: 'mono fin-code' }, r.code), h('span', { class: 'fin-name' }, r.name || '—'))),
        h('td', { class: 'num' }, num0(r.debit)), h('td', { class: 'num' }, num0(r.credit)),
        h('td', { class: 'num' }, r.bal_debit ? num0(r.bal_debit) : ''), h('td', { class: 'num' }, r.bal_credit ? num0(r.bal_credit) : ''));
    }));
    clear(out, h('div', { class: 'card table-wrap' }, h('table', { class: 'table fin-trial' },
      h('thead', null, h('tr', null, h('th', null, 'Hesap'), h('th', { class: 'num' }, 'Borç'), h('th', { class: 'num' }, 'Alacak'),
        h('th', { class: 'num' }, 'Borç bakiye'), h('th', { class: 'num' }, 'Alacak bakiye'))),
      tbody,
      h('tfoot', null, h('tr', null, h('td', null, h('b', null, 'Toplam'), d.balanced ? h('span', { class: 'badge green', style: { marginLeft: '8px' } }, 'Dengeli') : h('span', { class: 'badge red', style: { marginLeft: '8px' } }, 'Dengesiz')),
        ...['debit', 'credit', 'bal_debit', 'bal_credit'].map(k => h('td', { class: 'num' }, h('b', null, num0(d.total[k])))))))));
  }
  const load = async () => {
    clear(out, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
    try { d = await api.get(`/api/finance/trial?date_from=${from}&date_to=${to}&level=9`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    if (!d.has_ledger) { d = null; return clear(out, noLedger()); }
    if (!expanded.size) openTo(Number(levelSel.value));
    draw();
  };
  levelSel.addEventListener('change', () => { if (d) { openTo(Number(levelSel.value)); draw(); } });
  let st; search.addEventListener('input', () => { clearTimeout(st); st = setTimeout(() => { q = search.value.trim(); draw(); }, 250); });
  const allBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => { if (d) { openTo(99); draw(); } } }, 'Tümünü aç');
  const noneBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => { if (d) { expanded = new Set(); draw(); } } }, 'Tümünü kapat');
  clear(view, h('div', { class: 'filters' }, h('span', { class: 'small muted' }, 'Dönem'), dt(from, e => { from = e.target.value; load(); }), dt(to, e => { to = e.target.value; load(); }),
    h('span', { class: 'small muted' }, 'Aç'), levelSel, allBtn, noneBtn, search, h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, 'Satıra dokunun: hesap ekstresi')), out);
  load();
}

async function ledgerModal(code, name, from, to) {
  let d;
  try { d = await api.get(`/api/finance/ledger?account=${encodeURIComponent(code)}&date_from=${from}&date_to=${to}`); } catch (e) { return toastError(e); }
  modal({ title: `${code} ${name || ''} · ekstre`, wide: true,
    body: h('div', null, h('div', { class: 'small muted', style: { marginBottom: '8px' } }, `Devreden: ${money(d.opening)} · Kapanış: ${money(d.closing)} · ${d.rows.length} satır`),
      h('div', { class: 'table-wrap', style: { maxHeight: '60vh' } }, h('table', { class: 'table small' },
        h('thead', null, h('tr', null, ['Tarih', 'Yevmiye', 'Hesap', 'Açıklama', 'Borç', 'Alacak', 'Bakiye'].map(x => h('th', null, x)))),
        h('tbody', null, d.rows.slice(-1500).map(r => h('tr', null, h('td', null, fmtDate(r.date)), h('td', { class: 'mono' }, r.journal_no || ''), h('td', { class: 'mono' }, r.account),
          h('td', null, r.description || r.doc_no || ''), h('td', { class: 'num' }, r.debit ? num0(r.debit) : ''), h('td', { class: 'num' }, r.credit ? num0(r.credit) : ''),
          h('td', { class: 'num' }, num0(r.balance)))))))),
    actions: [{ label: 'Kapat' }] });
}

// ---------- Mali tablolar ----------
async function statementsView(view) {
  let from = yearStart(), to = today();
  const out = h('div');
  const load = async () => {
    clear(out, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
    let d;
    try { d = await api.get(`/api/finance/statements?date_from=${from}&date_to=${to}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    if (!d.has_ledger) return clear(out, noLedger());
    const k = d.kpi;
    const strip = statStrip();
    strip.set([kpi('Net satışlar', k.net_satis), kpi('Brüt kâr', k.brut_kar, k.brut_kar >= 0 ? 'ok' : 'alert'),
      kpi('Faaliyet kârı', k.faaliyet_kar, k.faaliyet_kar >= 0 ? 'ok' : 'alert'), kpi('Net kâr', k.net_kar, k.net_kar >= 0 ? 'ok' : 'alert'),
      { label: 'Brüt / net marj', value: k.brut_marj == null ? '—' : `%${k.brut_marj} / %${k.net_marj}` }]);
    const income = h('section', { class: 'card card-pad' }, h('h3', null, 'Gelir tablosu'), h('div', { class: 'small muted' }, `${fmtDate(d.date_from)} – ${fmtDate(d.date_to)}`),
      h('table', { class: 'table fin-is' }, h('tbody', null, d.income.map(r => h('tr', { class: r.total ? 'tot' : '' }, h('td', { class: 'muted' }, r.code),
        h('td', null, r.label), h('td', { class: `num ${r.amount < 0 ? 'neg' : ''}` }, num0(r.amount)))))),
      d.yansitilmamis ? h('p', { class: 'small muted' }, `Not: 7/A maliyet hesaplarında henüz 6’ya yansıtılmamış ${money(d.yansitilmamis)} faaliyet/finansman gideri tabloya dahil edildi.`) : null,
      d.uretim_maliyeti ? h('p', { class: 'small muted' }, `Üretim maliyetleri (71–74) ${money(d.uretim_maliyeti)}: stoğa / satılan mamul maliyetine yansıtılır, doğrudan gider değildir.`) : null);
    const b = d.balance;
    const side = (title, rows, extra) => h('div', { class: 'fin-bs-side' }, h('b', null, title),
      h('table', { class: 'table' }, h('tbody', null, rows.map(r => h('tr', null, h('td', { class: 'mono muted' }, r.code), h('td', null, r.name), h('td', { class: 'num' }, num0(r.amount)))),
        extra || null)));
    const balance = h('section', { class: 'card card-pad' }, h('h3', null, 'Bilanço özeti'), h('div', { class: 'small muted' }, `${fmtDate(d.date_to)} itibarıyla (kapanmamış dönem)`),
      h('div', { class: 'fin-bs' }, side('Aktif', b.aktif), side('Pasif', b.pasif, h('tr', null, h('td'), h('td', null, 'Dönem kârı / zararı'), h('td', { class: 'num' }, num0(b.donem_sonucu))))),
      h('div', { class: 'fin-bs fin-bs-tot' }, h('div', null, 'Toplam aktif ', h('b', null, money(b.toplam_aktif))), h('div', null, 'Toplam pasif ', h('b', null, money(b.toplam_pasif)))),
      h('details', { class: 'fin-bs-detail' }, h('summary', null, 'Ana hesap kırılımı'), h('table', { class: 'table small' }, h('tbody', null,
        b.detail.map(r => h('tr', null, h('td', { class: 'mono' }, r.code), h('td', null, r.name), h('td', { class: 'num' }, num0(r.amount))))))));
    clear(out, strip, h('div', { class: 'fin-stack' }, income, balance));
  };
  clear(view, h('div', { class: 'filters' }, h('span', { class: 'small muted' }, 'Dönem'), dt(from, e => { from = e.target.value; load(); }), dt(to, e => { to = e.target.value; load(); }),
    h('span', { class: 'spacer' }), h('span', { class: 'small muted' }, 'Kaynak: Mikro ERP muhasebe fişleri')), out);
  load();
}
