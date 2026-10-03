// Finans / Ön-Muhasebe: Özet (nakit pozisyonu + grafik), Kasa & Banka, Cariler, Hareketler.
// Cariler = Firma Yönetimi'ndeki firmalar + Satın Alma'daki tedarikçiler (ayrı cari listesi yok); ekstre yürüyen bakiyeyle.
// Mikro ERP aktarımı bu modülde değil, Program Ayarları › Entegrasyonlar'dadır.
import { api } from '../api.js';
import { clear, confirmDialog, field, fmtDate, h, matches, modal, moduleToolbar, pageHead, segmented, selectInput, statStrip, toast, toastError } from '../ui.js';
import { chartConfig, loadChart, theme } from './reports.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const SUBS = [['summary', 'Özet'], ['bank', 'Kasa & Banka'], ['cari', 'Cariler'], ['txns', 'Hareketler']];

export async function render(view, params, ctx) {
  const sub = SUBS.some(s => s[0] === params[0]) ? params[0] : 'summary';
  const nav = segmented(SUBS, sub, v => { location.hash = `#/finance/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Finans', { back: '#/', sub: 'Ön muhasebe · kasa-banka, cari, nakit akışı', tabs: nav }), body);
  if (sub === 'bank') return accountsView(body, 'bank');
  if (sub === 'cari') return cariView(body);
  if (sub === 'txns') return txnsView(body);
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
      h('tbody', null, d.recent.map(t => h('tr', null,
        h('td', null, fmtDate(t.date)), h('td', null, t.account_name),
        h('td', { class: 'muted' }, t.description || t.category || '—'),
        h('td', { class: 'num', style: { color: t.direction === 'in' ? 'var(--ok,#16a34a)' : 'var(--danger,#dc2626)' } },
          `${t.direction === 'in' ? '+' : '−'}${money(t.amount)}`))))))
      : h('div', { class: 'empty' }, 'Henüz hareket yok. “Hareketler” ya da “Kasa & Banka”dan ekleyin.'));
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
      class: 'card fin-acc', type: 'button', onclick: () => statementModal(a, load),
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
      h('tbody', null, rows.map(c => h('tr', { class: 'fin-click', onclick: () => statementModal({ cari: true, company_id: c.id, name: c.name }, load) },
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

// ---------- Cari / hesap ekstresi ----------
async function statementModal(acc, done) {
  let d;
  try { d = await api.get(acc.cari ? `/api/finance/cari/${acc.company_id}` : `/api/finance/accounts/${acc.id}/statement`); } catch (e) { return toastError(e); }
  const account = { ...d.account, cari: acc.cari };
  const b = d.account.balance;
  let m;
  const bodyEl = h('div', null,
    h('div', { class: 'fin-stmt-head' }, h('div', null, acc.cari ? h('div', { class: 'muted' }, 'Cari ekstre') : null,
      h('div', null, 'Güncel bakiye: ', h('b', { style: { color: b >= 0 ? 'var(--text)' : 'var(--danger,#dc2626)' } }, money(b))))),
    d.rows.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Tarih', 'Açıklama', 'Giriş', 'Çıkış', 'Bakiye', ''].map(x => h('th', null, x)))),
      h('tbody', null, [h('tr', { class: 'muted' }, h('td', null, '—'), h('td', null, 'Açılış'), h('td', null, ''), h('td', null, ''), h('td', { class: 'num' }, money(d.opening)), h('td', null, '')),
        ...d.rows.map(t => h('tr', null,
          h('td', null, fmtDate(t.date)), h('td', null, t.description || t.category || '—'),
          h('td', { class: 'num', style: { color: 'var(--ok,#16a34a)' } }, t.direction === 'in' ? money(t.amount) : ''),
          h('td', { class: 'num', style: { color: 'var(--danger,#dc2626)' } }, t.direction === 'out' ? money(t.amount) : ''),
          h('td', { class: 'num' }, money(t.balance)),
          h('td', null, h('button', { class: 'btn xs ghost', type: 'button', onclick: async () => {
            if (!await confirmDialog('Sil', 'Hareket silinsin mi?', { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/finance/txns/${t.id}`); m.close(); done?.(); statementModal(acc, done);
          } }, '×'))))])))
      : h('div', { class: 'empty' }, 'Henüz hareket yok.'));
  m = modal({ title: acc.name || d.account.name, wide: true, body: bodyEl,
    actions: [acc.cari
      ? { label: 'Firma kartı', onClick: () => { m.close(); location.hash = `#/companies/${acc.company_id}`; return true; } }
      : { label: 'Düzenle', onClick: () => { m.close(); accountForm(acc, done); return true; } },
    { label: 'Hareket Ekle', class: 'primary', onClick: () => { m.close(); txnForm(account, () => { done?.(); statementModal(acc, done); }); return true; } },
    { label: 'Kapat' }] });
}

function txnForm(acc, done) {
  let dirVal = 'in';
  const dir = segmented([['in', acc?.kind === 'cari' ? 'Tahsilat' : 'Giriş'], ['out', acc?.kind === 'cari' ? 'Ödeme' : 'Çıkış']], 'in', v => { dirVal = v; });
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

// ---------- Tüm hareketler ----------
async function txnsView(view) {
  clear(view, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
  let accs = [], rows = [];
  try { accs = await api.get('/api/finance/accounts'); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  const accSel = selectInput(accs.map(a => [String(a.id), a.name]), { all: 'Tüm hesaplar' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ara…', style: { maxWidth: '200px' } });
  const out = h('div');
  const addBtn = accs.length ? h('button', { class: 'btn primary', type: 'button', onclick: () => {
    const a = accs.find(x => String(x.id) === accSel.value) || accs[0];
    txnForm(a, load);
  } }, '＋ Hareket') : null;
  const load = async () => {
    try { rows = await api.get(`/api/finance/txns${accSel.value ? `?account_id=${accSel.value}` : ''}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    draw();
  };
  const draw = () => {
    const list = rows.filter(t => matches(q.value, t.account_name, t.description, t.category, t.doc_no));
    clear(out, list.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Tarih', 'Hesap', 'Açıklama', 'Kategori', 'Giriş', 'Çıkış', ''].map(x => h('th', null, x)))),
      h('tbody', null, list.map(t => h('tr', null,
        h('td', null, fmtDate(t.date)), h('td', null, t.account_name),
        h('td', null, t.description || '—'), h('td', { class: 'muted' }, t.category || '—'),
        h('td', { class: 'num', style: { color: 'var(--ok,#16a34a)' } }, t.direction === 'in' ? money(t.amount) : ''),
        h('td', { class: 'num', style: { color: 'var(--danger,#dc2626)' } }, t.direction === 'out' ? money(t.amount) : ''),
        h('td', null, h('button', { class: 'btn xs ghost', type: 'button', onclick: async () => {
          if (!await confirmDialog('Sil', 'Hareket silinsin mi?', { okLabel: 'Sil', danger: true })) return;
          await api.del(`/api/finance/txns/${t.id}`); load();
        } }, '×')))))))) : h('div', { class: 'card empty' }, 'Hareket yok.'));
  };
  accSel.addEventListener('change', load); q.addEventListener('input', draw);
  clear(view, moduleToolbar(addBtn), h('div', { class: 'filters' }, accSel, q), out);
  await load();
}
