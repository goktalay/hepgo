// Patron ekranı: üst yönetimin tek bakışta görmesi gerekenler — nakit, alacak / borç, kârlılık, nakit projeksiyonu, satış,
// üretim, insan kaynakları, operasyon ve dikkat gerektirenler. Her karta tıklayınca sağdan ayrıntı paneli açılır.
import { api } from '../api.js';
import { clear, every, fmtDate, h, svgIcon, t, toastError } from '../ui.js';
import { icons } from '../icons.js';
import { loadChart } from './reports.js';

const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const compact = n => {
  const a = Math.abs(n || 0), sg = n < 0 ? '−' : '';
  if (a >= 1e9) return `${sg}₺${(a / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 2 })} Mr`;
  if (a >= 1e6) return `${sg}₺${(a / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 })} Mn`;
  if (a >= 1e4) return `${sg}₺${Math.round(a / 1e3).toLocaleString('tr-TR')} B`;
  return `${sg}₺${Math.round(a).toLocaleString('tr-TR')}`;
};
const pct = (a, b) => (b ? Math.round(((a - b) / Math.abs(b)) * 1000) / 10 : null);
const MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
const mLabel = m => `${t(MONTHS[Number(m.slice(5, 7)) - 1])} ${m.slice(2, 4)}`;
const charts = [];
let CTX = null;

const delta = (cur, prev, label = 'geçen yıl') => {
  const p = pct(cur, prev);
  if (p == null) return null;
  return h('span', { class: `bx-delta ${p >= 0 ? 'up' : 'down'}`, title: `${t(label)}: ${money(prev)}` }, `${p >= 0 ? '▲' : '▼'} %${Math.abs(p).toLocaleString('tr-TR')}`);
};
const greet = () => {
  const hr = new Date().getHours();
  return hr < 5 ? 'İyi geceler' : hr < 12 ? 'Günaydın' : hr < 18 ? 'İyi günler' : hr < 22 ? 'İyi akşamlar' : 'İyi geceler';
};

export async function render(view, params, ctx) {
  CTX = ctx;
  view.classList.add('bx-view');
  const root = h('div', { class: 'bx' }, h('div', { class: 'bx-loading' }, h('span', { class: 'bx-spin' }), 'Şirketin nabzı ölçülüyor…'));
  clear(view, root);
  const load = async fresh => {
    let s;
    try { s = await api.get(`/api/boss${fresh ? '?fresh=1' : ''}`); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
    draw(root, s, () => load(true));
  };
  await load(false);
  every(5 * 60 * 1000, () => { if (document.visibilityState === 'visible' && root.isConnected) load(false); });
}

function draw(root, s, refresh) {
  charts.splice(0).forEach(c => c.destroy());
  const f = s.finance || {}, p = s.profit, cp = s.cash, sa = s.sales, pr = s.production, pe = s.people, op = s.operations;
  const first = String(s.user || '').split(' ')[0];
  const now = new Date();
  const tile = (key, label, value, sub, extra) => h('button', { class: 'bx-kpi', type: 'button', onclick: () => openDetail(key) },
    h('span', { class: 'bx-kpi-l' }, label), h('b', { class: 'bx-kpi-v', title: money(value) }, compact(value)), extra || null, sub ? h('span', { class: 'bx-kpi-s' }, sub) : null);
  const ytd = p?.ytd || {}, ly = p?.ly || {};
  const hero = h('section', { class: 'bx-hero' },
    h('i', { class: 'bx-orb a' }), h('i', { class: 'bx-orb b' }),
    h('div', { class: 'bx-hello' },
      h('small', null, now.toLocaleDateString('tr-TR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })),
      h('h1', null, `${t(greet())}${first ? `, ${first}` : ''}`),
      h('p', null, t('Şirketin bugünkü durumu · son güncelleme {s}', { s: s.generated_at.slice(11, 16) }),
        h('button', { class: 'bx-refresh', type: 'button', title: 'Yenile', onclick: refresh }, '↻'))),
    h('div', { class: 'bx-kpis' },
      tile('cash', 'Nakit (kasa + banka)', f.cash, f.month_in || f.month_out ? t('Bu ay +{a} / −{b}', { a: compact(f.month_in), b: compact(f.month_out) }) : null),
      tile('receivables', 'Alacaklar', f.receivable, f.overdue_rec ? h('span', { class: 'bx-warn' }, t('Vadesi geçen {v}', { v: compact(f.overdue_rec) })) : t('Vadesi geçen yok')),
      tile('payables', 'Borçlar', f.payable, f.overdue_pay ? h('span', { class: 'bx-warn' }, t('Vadesi geçen {v}', { v: compact(f.overdue_pay) })) : t('Vadesi geçen yok')),
      p ? tile('profit', t('{y} net kâr', { y: now.getFullYear() }), ytd.net_kar, ytd.net_marj != null ? t('Net marj %{m}', { m: ytd.net_marj.toLocaleString('tr-TR') }) : null, delta(ytd.net_kar, ly.net_kar))
        : tile('sales', t('{y} satış', { y: now.getFullYear() }), sa?.ytd, null, delta(sa?.ytd, sa?.ly))));

  const attn = s.attention.length ? h('section', { class: 'bx-attn' }, h('div', { class: 'bx-sec-h' }, h('b', null, 'Dikkat gerektirenler'), h('small', null, t('{n} konu', { n: s.attention.length }))),
    h('div', { class: 'bx-attn-list' }, s.attention.map(a => h('button', { class: `bx-attn-i ${a.level}`, type: 'button', onclick: () => openDetail(a.key) },
      h('i'), h('div', null, h('b', null, a.title), h('span', null, a.text))))))
    : h('section', { class: 'bx-attn ok' }, h('div', { class: 'bx-attn-i green' }, h('i'), h('div', null, h('b', null, 'Her şey yolunda'), h('span', null, 'Acil dikkat gerektiren bir konu görünmüyor.'))));

  const card = (key, title, icon, body, cls = '') => h('section', { class: `bx-card ${cls}`, tabindex: 0, onclick: e => { if (!e.target.closest('a,button')) openDetail(key); },
    onkeydown: e => { if (e.key === 'Enter') openDetail(key); } },
  h('header', null, h('span', { class: 'bx-ic' }, icons[icon] ? svgIcon(icons[icon]) : icon), h('b', null, title), h('span', { class: 'bx-more' }, 'Ayrıntı →')), body);

  const cards = [];
  if (p) {
    const cv = h('canvas');
    cards.push(card('profit', 'Ciro ve kârlılık', 'finance', h('div', null,
      h('div', { class: 'bx-stats' },
        h('div', null, h('small', null, t('{y} net satış', { y: now.getFullYear() })), h('b', null, compact(ytd.net_satis)), delta(ytd.net_satis, ly.net_satis)),
        h('div', null, h('small', null, 'Brüt kâr'), h('b', null, compact(ytd.brut_kar)), ytd.brut_marj != null ? h('em', null, `%${ytd.brut_marj.toLocaleString('tr-TR')}`) : null),
        h('div', null, h('small', null, 'Faaliyet kârı'), h('b', null, compact(ytd.faaliyet_kar))),
        h('div', null, h('small', null, 'Net kâr'), h('b', { class: ytd.net_kar < 0 ? 'neg' : 'pos' }, compact(ytd.net_kar)), ytd.net_marj != null ? h('em', null, `%${ytd.net_marj.toLocaleString('tr-TR')}`) : null)),
      h('div', { class: 'bx-chart tall' }, cv)), 'wide'));
    chartLater(cv, Chart => ({ type: 'bar', data: { labels: p.months.map(m => mLabel(m.month)), datasets: [
      { type: 'line', label: t('Net kâr'), data: p.months.map(m => m.net), borderColor: '#10b981', backgroundColor: '#10b98122', tension: 0.35, pointRadius: 3, borderWidth: 2.5, fill: true, order: 0 },
      { type: 'bar', label: t('Net satış'), data: p.months.map(m => m.sales), backgroundColor: grad(Chart, '#6366f1', '#6366f155'), borderRadius: 6, maxBarThickness: 34, order: 1 }] },
    options: baseOpts(true) }));
  }
  if (cp && cp.weeks?.length) {
    const cv = h('canvas');
    const low = cp.low;
    cards.push(card('cash', 'Nakit projeksiyonu · 12 hafta', 'reports', h('div', null,
      h('div', { class: 'bx-stats' }, h('div', null, h('small', null, 'Bugün'), h('b', null, compact(cp.cash))),
        h('div', null, h('small', null, '12 hafta sonra'), h('b', { class: cp.end < 0 ? 'neg' : '' }, compact(cp.end))),
        low ? h('div', null, h('small', null, 'En düşük'), h('b', { class: low.balance < 0 ? 'neg' : '' }, compact(low.balance)), h('em', null, fmtDate(low.start))) : null),
      h('div', { class: 'bx-chart' }, cv))));
    chartLater(cv, () => ({ type: 'line', data: { labels: cp.weeks.map(w => `${w.start.slice(8, 10)}.${w.start.slice(5, 7)}`), datasets: [
      { label: t('Öngörülen nakit'), data: cp.weeks.map(w => w.balance), borderColor: '#0ea5e9', backgroundColor: '#0ea5e926', fill: true, tension: 0.35, pointRadius: 2.5, borderWidth: 2.5,
        segment: { borderColor: c => (c.p1.parsed.y < 0 ? '#ef4444' : '#0ea5e9') } }] }, options: baseOpts(false) }));
  }
  if (f.aging_rec) {
    const tot = f.aging_rec.total || f.aging_rec.totals?.reduce?.((a, b) => a + b, 0) || 0;
    cards.push(card('overdue', 'Alacak yaşlandırma', 'calendar', agingBar(f.aging_rec, tot)));
  }
  if (sa) {
    const max = Math.max(1, ...sa.top.map(x => x.amount));
    cards.push(card('sales', 'Satış', 'sales', h('div', null,
      h('div', { class: 'bx-stats' }, h('div', null, h('small', null, t('{y} faturalanan (KDV dahil)', { y: now.getFullYear() })), h('b', null, compact(sa.ytd)), delta(sa.ytd, sa.ly)),
        h('div', null, h('small', null, 'Bu ay'), h('b', null, compact(sa.month)))),
      sa.top.length ? h('ol', { class: 'bx-rank' }, sa.top.map(x => h('li', null, h('span', null, x.name), h('i', { style: { width: `${(x.amount / max) * 100}%` } }), h('b', null, compact(x.amount)))))
        : h('p', { class: 'bx-empty' }, 'Bu yıl faturalanmış satış yok.'))));
  }
  if (pr) {
    const cv = h('canvas');
    const P = pr.printers;
    cards.push(card('production', 'Üretim', 'production', h('div', { class: 'bx-prod' },
      h('div', { class: 'bx-donut' }, cv, h('div', null, h('b', null, P.total ? `%${Math.round((P.printing / P.total) * 100)}` : '—'), h('small', null, 'yazıcı çalışıyor'))),
      h('div', { class: 'bx-mini' },
        mini('Açık iş emri', pr.open_orders), mini('Yazıcıdaki parça', pr.in_print), mini('Bugün biten', pr.done_today, 'pos'),
        mini('Bu ay biten', pr.done_month), mini('Hata oranı (ay)', pr.err_rate != null ? `%${pr.err_rate.toLocaleString('tr-TR')}` : '—', pr.err_rate >= 10 ? 'neg' : ''),
        mini('Hatadaki yazıcı', P.error, P.error ? 'neg' : '')))));
    chartLater(cv, () => ({ type: 'doughnut', data: { labels: ['Yazdırıyor', 'Boşta', 'Duraklatıldı', 'Hata', 'Çevrimdışı'].map(x => t(x)),
      datasets: [{ data: [P.printing, P.idle, P.paused, P.error, P.offline], backgroundColor: ['#10b981', '#94a3b8', '#f59e0b', '#ef4444', '#334155'], borderWidth: 0 }] },
    options: { cutout: '74%', plugins: { legend: { display: false }, tooltip: { enabled: true } }, animation: { duration: 900 } } }));
  }
  if (pe) {
    cards.push(card('people', 'İnsan kaynakları', 'hr', h('div', { class: 'bx-people' },
      h('div', { class: 'bx-big' }, h('b', null, pe.active), h('small', null, 'aktif personel')),
      h('div', { class: 'bx-mini' }, mini('Bugün izinli', pe.on_leave), mini('Raporlu', pe.on_report, pe.on_report ? 'neg' : ''),
        mini('Aylık maaş yükü', compact(pe.payroll)), mini(t('{y} işe giren', { y: now.getFullYear() }), pe.hired, 'pos'),
        mini('Ayrılan', pe.left), mini('Onay bekleyen izin', pe.pending_leaves)))));
  }
  if (op) {
    cards.push(card('operations', 'Operasyon', 'fleet', h('div', { class: 'bx-mini cols3' },
      mini('Aktif araç', op.vehicles), mini(t('Araç gideri ({y})', { y: now.getFullYear() }), compact(op.fleet_year)),
      mini('Geçerli sertifika', op.certs_valid, 'pos'), mini('Süresi yaklaşan', op.certs_expiring, op.certs_expiring ? 'neg' : ''),
      mini('Yaklaşan denetim', op.audits_upcoming), mini('Satın alma onayı', op.purchase_pending, op.purchase_pending ? 'warn' : ''),
      mini('Depo onayı bekleyen', op.parts_pending), mini('Sahada görev', op.field_active)), 'wide'));
  }
  clear(root, hero, attn, h('div', { class: 'bx-grid' }, cards));
}

const mini = (label, value, tone = '') => h('div', { class: `bx-m ${tone}` }, h('b', null, value ?? '—'), h('small', null, label));

function agingBar(ag, total) {
  const buckets = ag.buckets || ag.labels || [];
  const vals = ag.totals || ag.total_by || [];
  const sum = vals.reduce((a, b) => a + b, 0) || total || 0;
  const COL = ['#10b981', '#f59e0b', '#f97316', '#ef4444', '#991b1b'];
  return h('div', { class: 'bx-aging' },
    h('div', { class: 'bx-stats' }, h('div', null, h('small', null, 'Açık alacak'), h('b', null, compact(sum))),
      h('div', null, h('small', null, 'Vadesi geçen'), h('b', { class: 'neg' }, compact(sum - (vals[0] || 0))))),
    h('div', { class: 'bx-abar' }, vals.map((v, i) => (v ? h('i', { style: { flex: v, background: COL[i] }, title: `${t(buckets[i] || '')}: ${money(v)}` }) : null))),
    h('ul', { class: 'bx-legend' }, vals.map((v, i) => h('li', null, h('i', { style: { background: COL[i] } }), h('span', null, buckets[i] || ''), h('b', null, compact(v))))));
}

const grad = (Chart, a, b) => ctx => {
  const { chart } = ctx;
  const area = chart.chartArea;
  if (!area) return a;
  const g = chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, a); g.addColorStop(1, b);
  return g;
};
function baseOpts(legend) {
  const cs = getComputedStyle(document.documentElement);
  const muted = cs.getPropertyValue('--muted').trim() || '#64748b';
  const grid = document.documentElement.dataset.theme === 'dark' ? 'rgba(255,255,255,.07)' : 'rgba(15,23,42,.06)';
  return { responsive: true, maintainAspectRatio: false, animation: { duration: 900, easing: 'easeOutQuart' }, interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: legend, position: 'bottom', labels: { color: muted, usePointStyle: true, boxWidth: 8, padding: 14 } },
      tooltip: { callbacks: { label: c => `${c.dataset.label}: ${money(c.parsed.y)}` } } },
    scales: { x: { grid: { display: false }, ticks: { color: muted } },
      y: { grid: { color: grid }, border: { display: false }, ticks: { color: muted, callback: v => compact(v) } } } };
}
function chartLater(canvas, cfg) {
  loadChart().then(Chart => {
    if (!canvas.isConnected) return requestAnimationFrame(() => canvas.isConnected && charts.push(new Chart(canvas, cfg(Chart))));
    charts.push(new Chart(canvas, cfg(Chart)));
  }).catch(() => {});
}

// ---------------- Ayrıntı paneli ----------------
const TITLES = { cash: 'Nakit ve hesaplar', receivables: 'Alacaklar', payables: 'Borçlar', overdue: 'Vadesi geçen alacaklar', profit: 'Kârlılık (gelir tablosu)',
  sales: 'Satış', production: 'Üretim', people: 'İnsan kaynakları', operations: 'Operasyon' };
const LINKS = { cash: ['finance', '#/finance/bank', 'Finans’ta aç'], receivables: ['finance', '#/finance/cari', 'Carilere git'], payables: ['finance', '#/finance/cari', 'Carilere git'],
  overdue: ['finance', '#/finance/cash', 'Nakit akışına git'], profit: ['finance', '#/finance/statements', 'Mali tablolar'], sales: ['sales', '#/sales', 'Satış Yönetimi'],
  production: ['production', '#/production', 'Üretim Yönetimi'], people: ['hr', '#/hr', 'İnsan Kaynakları'], operations: ['fleet', '#/fleet', 'Araç Yönetimi'] };

async function openDetail(key) {
  const body = h('div', { class: 'bx-dr-body' }, h('div', { class: 'bx-loading' }, h('span', { class: 'bx-spin' }), 'Yükleniyor…'));
  const lk = LINKS[key];
  const canGo = lk && CTX?.user?.modules?.includes(lk[0]);
  const close = () => { back.classList.remove('on'); setTimeout(() => back.remove(), 260); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  const back = h('div', { class: 'bx-dr-back', onmousedown: e => { if (e.target === back) close(); } },
    h('aside', { class: 'bx-dr', role: 'dialog', 'aria-modal': 'true' },
      h('header', null, h('b', null, TITLES[key] || key), canGo ? h('a', { class: 'btn sm', href: lk[1], onclick: close }, lk[2]) : null,
        h('button', { class: 'x-btn', type: 'button', 'aria-label': 'Kapat', onclick: close }, '×')), body));
  document.body.append(back);
  document.addEventListener('keydown', onKey);
  window.addEventListener('hashchange', close, { once: true });
  requestAnimationFrame(() => back.classList.add('on'));
  let d;
  try { d = await api.get(`/api/boss/detail/${key}`); } catch (e) { toastError(e); return clear(body, h('div', { class: 'card empty' }, e.message)); }
  clear(body, (DETAIL[key] || (() => h('div')))(d));
}

const table = (head, rows, empty = 'Kayıt yok.') => (rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table bx-t' },
  h('thead', null, h('tr', null, head.map(([l, num]) => h('th', { class: num ? 'num' : '' }, l)))),
  h('tbody', null, rows))) : h('p', { class: 'bx-empty' }, empty));
const td = (v, cls = '') => h('td', { class: cls }, v);

const DETAIL = {
  cash: d => h('div', null,
    h('h4', null, 'Kasa ve banka hesapları'),
    table([['Hesap'], ['Tür'], ['Bakiye', 1]], d.accounts.map(a => h('tr', null, td(a.name), td(a.kind), td(money(a.balance), `num ${a.balance < 0 ? 'neg' : ''}`)))),
    d.projection ? [h('h4', null, '12 haftalık projeksiyon'),
      table([['Hafta'], ['Giriş', 1], ['Çıkış', 1], ['Bakiye', 1]], d.projection.weeks.map(w => h('tr', null, td(`${fmtDate(w.start)}`),
        td(w.in ? money(w.in) : '—', 'num pos'), td(w.out ? money(w.out) : '—', 'num neg'), td(money(w.balance), `num ${w.balance < 0 ? 'neg' : ''}`)))),
      h('p', { class: 'bx-note' }, 'Vadesi gelen cari alacak / borçlar, çek-senetler, planlı ödemeler ve maaş günüyle hesaplanır (Finans › Nakit Akışı).')] : null),
  receivables: d => agingDetail(d, 'Cari'), payables: d => agingDetail(d, 'Cari'), overdue: d => agingDetail(d, 'Cari', true),
  profit: d => (d ? h('div', null,
    h('h4', null, t('{y} yılbaşından bugüne', { y: new Date().getFullYear() })),
    table([['Kalem'], ['Tutar', 1]], d.income.filter(r => r.amount || r.total).map(r => h('tr', { class: r.total ? 'bx-tot' : '' }, td(r.label), td(money(r.amount), `num ${r.amount < 0 ? 'neg' : ''}`)))),
    h('h4', null, 'Aylara göre'),
    table([['Ay'], ['Net satış', 1], ['Brüt kâr', 1], ['Net kâr', 1]], d.months.slice().reverse().map(m => h('tr', null, td(mLabel(m.month)), td(money(m.sales), 'num'),
      td(money(m.gross), 'num'), td(money(m.net), `num ${m.net < 0 ? 'neg' : 'pos'}`)))),
    h('p', { class: 'bx-note' }, 'Muhasebe (Mikro yevmiye) kayıtlarından; dönem kapanışı yapılmadan önceki tahmini sonuçtur.')) : h('p', { class: 'bx-empty' }, 'Muhasebe verisi yok.')),
  sales: d => h('div', null,
    h('h4', null, 'Son 12 ay faturalanan satış'),
    table([['Ay'], ['Tutar', 1]], d.months.slice().reverse().map(m => h('tr', null, td(mLabel(m.month)), td(money(m.amount), 'num')))),
    h('h4', null, 'En büyük müşteriler (bu yıl)'),
    table([['Müşteri'], ['Fatura', 1], ['Tutar', 1]], d.top.map(x => h('tr', null, td(x.name), td(x.n, 'num'), td(money(x.amount), 'num')))),
    h('h4', null, 'En büyük tedarikçiler (bu yıl)'),
    table([['Tedarikçi'], ['Fatura', 1], ['Tutar', 1]], d.suppliers.map(x => h('tr', null, td(x.name), td(x.n, 'num'), td(money(x.amount), 'num'))))),
  production: d => h('div', null,
    h('h4', null, t('Açık iş emirleri ({n})', { n: d.orders.length })),
    d.orders.length ? h('div', { class: 'bx-orders' }, d.orders.map(o => h('div', { class: 'bx-order' },
      h('div', null, h('b', null, o.code), h('small', null, [o.product_name, o.company_name].filter(Boolean).join(' · '))),
      h('div', { class: 'bx-prog' }, h('i', { style: { width: `${Math.round(o.progress || 0)}%` } })), h('em', null, `%${Math.round(o.progress || 0)}`)))) : h('p', { class: 'bx-empty' }, 'Açık iş emri yok.'),
    h('h4', null, t('Yazıcılar ({n})', { n: d.printers.length })),
    h('div', { class: 'bx-printers' }, d.printers.map(p => h('span', { class: `bx-pr ${String(p.live_state || 'CEVRIMDISI').toLowerCase()}`, title: [p.live_state, p.live_file].filter(Boolean).join(' · ') },
      p.name, p.live_state === 'YAZDIRIYOR' && p.live_progress != null ? h('small', null, `%${Math.round(p.live_progress * (p.live_progress <= 1 ? 100 : 1))}`) : null)))),
  people: d => h('div', null,
    h('h4', null, t('Bugün işte olmayanlar ({n})', { n: d.away.length })),
    table([['Personel'], ['Durum'], ['Dönüş']], d.away.map(a => h('tr', null, td(a.name), td(a.label), td(fmtDate(a.until)))), 'Bugün izinli / raporlu personel yok.'),
    h('h4', null, 'Görevlere göre'),
    table([['Görev'], ['Kişi', 1], ['Maaş toplamı', 1]], d.titles.map(x => h('tr', null, td(x.title), td(x.n, 'num'), td(money(x.payroll), 'num')))),
    h('h4', null, 'Son işe girenler'),
    table([['Personel'], ['Görev'], ['Başlama']], d.recent.map(x => h('tr', null, td(x.name), td(x.title || '—'), td(fmtDate(x.start_date)))))),
  operations: d => h('div', null,
    h('h4', null, t('Araç giderleri ({y})', { y: new Date().getFullYear() })),
    table([['Araç'], ['Gider', 1]], d.fleet.map(v => h('tr', null, td([h('b', null, v.plate), ' ', [v.brand, v.model].filter(Boolean).join(' ')]), td(money(v.amount), 'num'))), 'Araç yok.'),
    h('h4', null, 'Sertifikalar'),
    table([['Sertifika'], ['Durum'], ['Geçerlilik']], d.certs.map(c => h('tr', null, td([c.name, c.standard ? h('small', { class: 'muted' }, ` · ${c.standard}`) : null]), td(c.status), td(c.expiry_date ? fmtDate(c.expiry_date) : '—'))), 'Sertifika yok.'),
    h('h4', null, 'Onay bekleyen satın alma talepleri'),
    table([['Talep'], ['Başlık'], ['İhtiyaç']], d.requests.map(r => h('tr', null, td(r.code), td(r.title), td(r.needed_by ? fmtDate(r.needed_by) : '—'))), 'Onay bekleyen talep yok.')),
};

function agingDetail(d, label, overdueOnly) {
  const rows = overdueOnly ? d.rows.filter(r => r.overdue > 0) : d.rows;
  return h('div', null, agingBar(d.aging, d.total),
    h('h4', null, overdueOnly ? 'Vadesi geçen tutara göre' : 'Açık tutara göre'),
    table([[label], ['Açık', 1], ['Vadesi geçen', 1], ['Gecikme', 1]], rows.map(r => h('tr', null, td(r.name), td(money(r.amount), 'num'),
      td(r.overdue ? money(r.overdue) : '—', `num ${r.overdue ? 'neg' : ''}`), td(r.late_days ? t('{n} gün', { n: r.late_days }) : '—', 'num'))), 'Açık kalem yok.'),
    h('p', { class: 'bx-note' }, 'Ödemeler en eski faturaya sayılarak (FIFO) hesaplanan açık kalemler.'));
}
