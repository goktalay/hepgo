// Proje Yönetimi (Ar-Ge): projeler (kapak + resimli tanım, sorumlu, başlama tarihi, bütçe), proje kâr-zararı, proje kararı
// bekleyen finansal hareketler (toplu atama) ve tarama (anahtar kelime eşleşmeleri + açıklamalardan proje adayları).
// Proje bir gruplamadır: silinince yalnız etiketler kalkar, finansal veri silinmez.
import { api, fileUrl, upload, uploadLarge } from '../api.js';
import { clear, confirmDialog, field, fmtDate, h, matches, modal, moduleToolbar, pageHead, segmented, statStrip, t, toast, toastError } from '../ui.js';
import { decideModal, natureBadge, projectChip } from './projdecide.js';
import { loadChart } from './reports.js';

const SUBS = [['list', 'Projeler'], ['queue', 'Hareketlere Proje'], ['scan', 'Proje Taraması']];
const ST_TONE = { fikir: '', planlama: 'blue', devam: 'green', beklemede: 'yellow', tamamlandi: 'purple', iptal: 'red' };
const money = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 }).format(n || 0);
const money2 = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 2 }).format(n || 0);
const loading = el => clear(el, h('div', { class: 'card card-pad' }, h('div', { class: 'loading' }, 'Yükleniyor…')));
const initials = n => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toLocaleUpperCase('tr');
const hue = s => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
let META = null;
const charts = [];

export async function render(view, params, ctx) {
  const p0 = (params[0] || '').split('?')[0];
  if (/^\d+$/.test(p0)) return detail(view, Number(p0), ctx);
  const sub = SUBS.some(([k]) => k === p0) ? p0 : 'list';
  const nav = segmented(SUBS, sub, v => { location.hash = v === 'list' ? '#/projects' : `#/projects/${v}`; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Proje Yönetimi', { back: '#/', sub: 'Ar-Ge ve şirket projeleri · proje kâr-zararı', tabs: nav }), body);
  if (sub === 'queue') return queueView(body);
  if (sub === 'scan') return scanView(body);
  return listView(body);
}

const cover = (p, cls = '') => h('div', { class: `pj-cover ${cls}`, style: p.image ? null : `--h:${hue(p.name)}` },
  p.image ? h('img', { src: fileUrl(p.image, 1024), alt: '', loading: 'lazy' }) : h('span', { class: 'pj-ini' }, initials(p.name)));
const stBadge = s => h('span', { class: `badge ${ST_TONE[s] || ''}` }, META?.statuses?.[s] || s);

// ---------------- Projeler ----------------
async function listView(root) {
  loading(root);
  let d;
  try { d = await api.get('/api/projects'); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  META = d.meta;
  const rows = d.rows;
  const act = rows.filter(p => ['devam', 'planlama'].includes(p.status));
  const sum = k => rows.reduce((a, p) => a + (p.fin[k] || 0), 0);
  const strip = statStrip();
  strip.set([{ label: 'Aktif proje', value: act.length, sub: t('toplam {n}', { n: rows.length }) }, { label: 'Proje gelirleri', value: money(sum('gelir')) },
    { label: 'Proje giderleri', value: money(sum('gider')) }, { label: 'Proje kârı', value: money(sum('kar')), tone: sum('kar') < 0 ? 'alert' : 'ok' },
    { label: 'Proje bekleyen hareket', value: d.pending, tone: d.pending ? 'alert' : '' }]);
  let filter = 'active', q = '';
  const grid = h('div', { class: 'pj-grid' });
  const pass = p => ({ active: !['tamamlandi', 'iptal'].includes(p.status), done: p.status === 'tamamlandi', all: true }[filter]);
  const draw = () => {
    const shown = rows.filter(p => pass(p) && matches(q, p.name, p.code, p.manager_name, p.company_name, p.summary));
    clear(grid, shown.length ? shown.map(p => {
      const used = p.budget ? Math.min(100, (p.fin.gider / p.budget) * 100) : null;
      return h('a', { class: 'pj-card', href: `#/projects/${p.id}` }, cover(p),
        h('div', { class: 'pj-body' },
          h('div', { class: 'pj-row' }, h('span', { class: 'pj-code' }, p.code), stBadge(p.status)),
          h('b', { class: 'pj-name' }, p.name),
          p.summary ? h('p', { class: 'pj-sum' }, p.summary) : null,
          h('div', { class: 'pj-meta small muted' }, p.manager_name ? h('span', null, '👤 ', p.manager_name) : null, p.start_date ? h('span', null, '📅 ', fmtDate(p.start_date)) : null),
          h('div', { class: 'pj-fin' }, h('div', null, h('small', null, 'Gelir'), h('b', null, money(p.fin.gelir))), h('div', null, h('small', null, 'Gider'), h('b', null, money(p.fin.gider))),
            h('div', null, h('small', null, 'Kâr'), h('b', { class: p.fin.kar < 0 ? 'neg' : 'pos' }, money(p.fin.kar)))),
          used != null ? h('div', { class: 'pj-budget', title: t('Bütçe {b} · harcanan %{p}', { b: money(p.budget), p: Math.round(used) }) },
            h('i', { style: { width: `${used}%` }, class: used >= 90 ? 'hot' : '' })) : null));
    }) : h('div', { class: 'card empty', style: { gridColumn: '1/-1' } }, rows.length ? 'Bu filtrede proje yok.' : 'Henüz proje yok. “＋ Yeni proje” ile ekleyin ya da “Proje Taraması”ndan mevcut verilerde bulunan proje adaylarına bakın.'));
  };
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Proje, kod, sorumlu ara…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); draw(); });
  clear(root, moduleToolbar(h('button', { class: 'btn primary', type: 'button', onclick: () => projectForm(null, id => { location.hash = `#/projects/${id}`; }) }, '＋ Yeni proje')),
    strip,
    d.pending ? h('a', { class: 'fl-banner', href: '#/projects/queue' }, h('span', { class: 'fl-banner-i' }, '?'),
      h('div', null, h('b', null, t('{n} finansal hareket proje kararı bekliyor', { n: d.pending })), h('div', { class: 'small muted' }, 'Her hareket için proje seçin ya da “Projesiz” işaretleyin (toplu yapılabilir)')),
      h('span', { class: 'fl-banner-go' }, '→')) : null,
    h('div', { class: 'filters' }, segmented([['active', 'Süren'], ['done', 'Tamamlanan'], ['all', 'Tümü']], filter, v => { filter = v; draw(); }), search), grid);
  draw();
}

async function projectForm(p, done, pre) {
  let o;
  try { o = await api.get('/api/projects/people/options'); } catch (e) { return toastError(e); }
  META = META || o;
  p = p || { kind: 'arge', status: 'devam', start_date: new Date().toISOString().slice(0, 10), ...(pre || {}) };
  const v = k => p[k] ?? '';
  const inp = (k, a = {}) => h('input', { class: 'input', value: v(k), ...a });
  const f = {
    name: inp('name', { placeholder: 'ör. Dikey İnişli İHA Prototipi' }), code: inp('code', { placeholder: 'Boş bırakılırsa otomatik (P-0001)' }),
    kind: h('select', { class: 'input' }, Object.entries(o.kinds).map(([k, l]) => h('option', { value: k, selected: k === p.kind }, l))),
    status: h('select', { class: 'input' }, Object.entries(o.statuses).map(([k, l]) => h('option', { value: k, selected: k === p.status }, l))),
    manager: h('select', { class: 'input' }, h('option', { value: '' }, '— Proje sorumlusu —'), o.users.map(u => h('option', { value: u.id, selected: u.id === p.manager_id }, u.full_name))),
    company: h('select', { class: 'input' }, h('option', { value: '' }, '— Müşteri / destek kurumu (ops.) —'), o.companies.map(c => h('option', { value: c.id, selected: c.id === p.company_id }, c.name))),
    start: inp('start_date', { type: 'date' }), end: inp('end_date', { type: 'date' }), budget: inp('budget', { type: 'number', step: '0.01', min: 0 }),
    summary: inp('summary', { placeholder: 'Tek cümlelik özet (kartta görünür)' }),
    desc: h('textarea', { class: 'input', rows: 8, placeholder: 'Projenin amacı, kapsamı, hedefleri, iş paketleri…' }),
    keywords: inp('keywords', { placeholder: 'ör. VTOL, DİKEY İNİŞ, TÜBİTAK 1501' }), mikro: inp('mikro_code', { placeholder: 'Mikro proje kodu (varsa)' }),
  };
  f.desc.value = v('description');
  const img = h('input', { type: 'file', accept: 'image/*' });
  modal({ title: p.id ? t('{c} · proje bilgileri', { c: p.code }) : 'Yeni proje', wide: true, body: h('div', { class: 'fl-form' },
    h('div', { class: 'cf-2' }, field('Proje adı', f.name), field('Proje kodu', f.code)),
    h('div', { class: 'cf-3' }, field('Tür', f.kind), field('Durum', f.status), field('Proje sorumlusu', f.manager)),
    h('div', { class: 'cf-3' }, field('Başlama tarihi', f.start), field('Hedef bitiş', f.end), field('Bütçe (₺)', f.budget)),
    field('Müşteri / destek kurumu', f.company), field('Özet', f.summary), field('Detaylı anlatım', f.desc),
    h('div', { class: 'cf-2' }, field('Anahtar kelimeler', f.keywords, 'Hareket açıklamalarında bu kelimeler geçerse proje önerilir (virgülle).'), field('Mikro proje kodu', f.mikro)),
    p.id ? null : field('Kapak resmi', img)),
  actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
    const b = { name: f.name.value, code: f.code.value || null, kind: f.kind.value, status: f.status.value, manager_id: Number(f.manager.value) || null,
      company_id: Number(f.company.value) || null, start_date: f.start.value || null, end_date: f.end.value || null, budget: f.budget.value === '' ? null : Number(f.budget.value),
      summary: f.summary.value, description: f.desc.value, keywords: f.keywords.value, mikro_code: f.mikro.value };
    let id = p.id;
    if (id) await api.put(`/api/projects/${id}`, b); else id = (await api.post('/api/projects', b)).id;
    if (img.files?.[0]) { const fd = new FormData(); fd.append('file', img.files[0]); await upload(`/api/projects/${id}/cover`, fd); }
    toast('Kaydedildi', 'success'); done?.(id);
  } }] });
}

// ---------------- Proje detayı ----------------
async function detail(view, id, ctx) {
  loading(view);
  let p;
  try { p = await api.get(`/api/projects/${id}`); } catch (e) { return clear(view, h('div', { class: 'card empty' }, e.message)); }
  META = p.meta;
  const reload = () => detail(view, id, ctx);
  const F = p.finance;
  let tab = sessionStorage.getItem('pj.tab') || 'overview';
  const pane = h('div');
  const mats = F.items.filter(x => x.line_ref);
  const tabs = segmented([['overview', 'Genel'], ['finance', t('Finans ({n})', { n: F.items.length })], ['materials', t('Malzemeler ({n})', { n: mats.length })]], tab,
    k => { tab = k; try { sessionStorage.setItem('pj.tab', k); } catch { /* */ } show(); }, { tabs: true });
  const show = () => (tab === 'finance' ? financePane(pane, p, reload) : tab === 'materials' ? materialsPane(pane, mats, reload) : overviewPane(pane, p, reload));
  const coverIn = h('input', { type: 'file', accept: 'image/*', hidden: true });
  coverIn.addEventListener('change', async () => {
    if (!coverIn.files[0]) return;
    const fd = new FormData(); fd.append('file', coverIn.files[0]);
    try { await upload(`/api/projects/${id}/cover`, fd); reload(); } catch (e) { toastError(e); }
  });
  const used = p.budget ? Math.min(100, (F.gider / p.budget) * 100) : null;
  const strip = statStrip();
  strip.set([{ label: 'Gelir (KDV hariç)', value: money(F.gelir) }, { label: 'Gider (KDV hariç)', value: money(F.gider) },
    { label: 'Kâr / zarar', value: money(F.kar), tone: F.kar < 0 ? 'alert' : 'ok', sub: F.marj != null ? t('marj %{m}', { m: F.marj }) : null },
    p.budget ? { label: 'Bütçe kullanımı', value: `%${Math.round(used)}`, sub: t('{g} / {b}', { g: money(F.gider), b: money(p.budget) }), tone: used >= 90 ? 'alert' : '' } : null,
    { label: 'Tahsilat / ödeme', value: `${money(F.tahsilat)} / ${money(F.odeme)}` }]);
  clear(view,
    h('div', { class: 'cf-head' }, h('a', { class: 'small', href: '#/projects' }, '← Projeler')),
    h('section', { class: 'pj-hero' }, cover(p, 'big'),
      h('div', { class: 'pj-hero-in' },
        h('div', { class: 'pj-row' }, h('span', { class: 'pj-code' }, p.code), stBadge(p.status), h('span', { class: 'badge' }, META.kinds[p.kind] || p.kind)),
        h('h1', null, p.name), p.summary ? h('p', null, p.summary) : null,
        h('div', { class: 'pj-chips' }, p.manager_name ? h('span', null, '👤 ', p.manager_name) : null, p.start_date ? h('span', null, '📅 ', fmtDate(p.start_date), p.end_date ? ` → ${fmtDate(p.end_date)}` : '') : null,
          p.company_name ? h('span', null, '🏢 ', p.company_name) : null),
        h('div', { class: 'ct-acts' }, h('button', { class: 'btn sm primary', type: 'button', onclick: () => projectForm(p, reload) }, 'Düzenle'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => coverIn.click() }, p.image ? 'Kapağı değiştir' : 'Kapak ekle'), coverIn,
          h('button', { class: 'btn sm ghost', type: 'button', onclick: () => deleteProject(p) }, 'Sil')))),
    p.suggest_count ? h('div', { class: 'fl-banner' }, h('span', { class: 'fl-banner-i' }, '⚲'),
      h('div', null, h('b', null, t('{n} hareket bu projenin anahtar kelimeleriyle eşleşiyor', { n: p.suggest_count })), h('div', { class: 'small muted' }, 'Kararı verilmemiş hareketler; tek tıkla projeye bağlayın.')),
      h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
        try { const r = await api.post(`/api/projects/scan/apply?project_id=${id}`); toast(t('{n} hareket bağlandı', { n: r.tagged }), 'success'); reload(); } catch (e) { toastError(e); }
      } }, 'Bağla')) : null,
    strip, h('div', { class: 'cf-tabs' }, tabs), pane);
  show();
}

function overviewPane(root, p, reload) {
  const imgIn = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
  imgIn.addEventListener('change', async () => {
    for (const f of [...imgIn.files]) {
      try { const tok = await uploadLarge(f, 'projects'); await api.post(`/api/projects/${p.id}/images`, { upload_id: tok }); } catch (e) { toastError(e); }
    }
    reload();
  });
  const paras = String(p.description || '').split(/\n{2,}|\r\n\r\n/).filter(s => s.trim());
  clear(root, h('div', { class: 'pj-over' },
    h('section', { class: 'card card-pad pj-desc' }, h('h3', null, 'Proje tanımı'),
      paras.length ? paras.map(s => h('p', null, s)) : h('p', { class: 'muted' }, 'Detaylı anlatım henüz girilmedi. “Düzenle” ile ekleyin.'),
      p.keywords ? h('div', { class: 'pj-kw' }, h('small', { class: 'muted' }, 'Anahtar kelimeler: '), p.keywords.split(',').map(k => h('span', null, k.trim()))) : null),
    h('section', { class: 'card card-pad' }, h('div', { class: 'pj-gal-h' }, h('h3', null, t('Görseller ({n})', { n: p.images.length })),
      h('button', { class: 'btn sm', type: 'button', onclick: () => imgIn.click() }, '＋ Resim ekle'), imgIn),
    p.images.length ? h('div', { class: 'pj-gal' }, p.images.map(im => h('figure', null,
      h('img', { src: fileUrl(im.path, 640), alt: '', loading: 'lazy', onclick: () => modal({ title: im.caption || p.name, wide: true, body: h('div', { class: 'cf-big' }, h('img', { src: fileUrl(im.path), alt: '' })), actions: [{ label: 'Kapat', class: 'primary' }] }) }),
      h('button', { class: 'pj-gal-x', type: 'button', title: 'Sil', onclick: async () => {
        if (!await confirmDialog('Resmi sil', 'Resim silinsin mi?', { okLabel: 'Sil', danger: true })) return;
        try { await api.del(`/api/projects/images/${im.id}`); reload(); } catch (e) { toastError(e); }
      } }, '×'))))
      : h('p', { class: 'muted' }, 'Projeyi anlatan çizim, prototip, test fotoğrafı ekleyin.'))));
}

const SRC_LABEL = { txn: 'Hareket', invoice: 'Fatura', mdoc: 'Satın Alma' };
function financePane(root, p, reload) {
  const F = p.finance;
  charts.splice(0).forEach(c => c.destroy());
  const cv = h('canvas');
  const cats = Object.entries(F.categories);
  const maxc = Math.max(1, ...cats.map(c => c[1]));
  clear(root,
    F.items.length ? h('div', { class: 'fl-two' },
      h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Aylara göre gelir / gider'), h('div', { class: 'bx-chart' }, cv)),
      h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, 'Gider dağılımı'),
        cats.length ? h('div', { class: 'fl-cats' }, cats.map(([k, v]) => h('div', { class: 'fl-cat' }, h('span', { class: 'fl-cat-l' }, h('i', { style: { background: '#6366f1' } }), k),
          h('div', { class: 'fl-cat-bar' }, h('i', { style: { width: `${(v / maxc) * 100}%`, background: '#6366f1' } })), h('b', null, money(v))))) : h('p', { class: 'muted' }, 'Gider yok.'))) : null,
    F.items.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, ['Tarih', 'Nitelik', 'Hareket', 'Belge', 'Kategori', 'Tutar (KDV hariç)', ''].map(x => h('th', { class: /Tutar/.test(x) ? 'num' : '' }, x)))),
      h('tbody', null, F.items.map(x => h('tr', null, h('td', { class: 'nowrap' }, fmtDate(x.date)), h('td', null, natureBadge(x.nature)),
        h('td', null, h('div', null, x.title || '—'), h('div', { class: 'small muted' }, [x.account, x.line_desc, SRC_LABEL[x.source]].filter(Boolean).join(' · '))),
        h('td', { class: 'mono small' }, x.doc_no || '—'), h('td', { class: 'small' }, x.category || '—'),
        h('td', { class: 'num' }, h('b', null, money2(x.nature === 'odeme' ? x.amount : x.net))),
        h('td', null, h('button', { class: 'btn xs', type: 'button', title: 'Proje kararını düzenle', onclick: () => decideModal(x.source, x.ref, reload) }, '✎')))))))
      : h('div', { class: 'card empty' }, 'Bu projeye bağlı hareket yok. “Hareketlere Proje” sekmesinden ya da hesap / cari detayındaki proje sütunundan bağlayın.'));
  if (F.months.length) {
    loadChart().then(Chart => { if (cv.isConnected) charts.push(new Chart(cv, { type: 'bar', data: { labels: F.months.map(m => m.month), datasets: [
      { label: t('Gelir'), data: F.months.map(m => m.gelir), backgroundColor: '#10b981cc', borderRadius: 5 },
      { label: t('Gider'), data: F.months.map(m => m.gider), backgroundColor: '#ef4444cc', borderRadius: 5 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { x: { grid: { display: false } } } } })); }).catch(() => {});
  }
}

function materialsPane(root, mats, reload) {
  clear(root, mats.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, ['Tarih', 'Kalem', 'Fatura', 'Tutar (KDV hariç)', ''].map(x => h('th', { class: /Tutar/.test(x) ? 'num' : '' }, x)))),
    h('tbody', null, mats.map(x => h('tr', null, h('td', null, fmtDate(x.date)), h('td', null, x.line_desc || '—', h('div', { class: 'small muted' }, x.account || '')),
      h('td', { class: 'mono small' }, x.doc_no || '—'), h('td', { class: 'num' }, money2(x.net)),
      h('td', null, h('button', { class: 'btn xs', type: 'button', onclick: () => decideModal(x.source, x.ref, reload) }, '✎')))))))
    : h('div', { class: 'card empty' }, 'Alış faturalarından bu proje için ayrılmış malzeme yok. Faturanın proje kararında “Kalem bazında” seçeneğiyle malzemeleri projeye ayırabilirsiniz.'));
}

function deleteProject(p) {
  const inp = h('input', { class: 'input', placeholder: p.name });
  modal({ title: 'Projeyi sil', body: h('div', null, h('p', null, t('“{n}” silinecek. Bağlı hareketler, faturalar ve malzemeler SİLİNMEZ; yalnızca bu projeyle ilişkileri kalkar ve yeniden proje kararı bekler. Onaylamak için proje adını yazın:', { n: p.name })), inp),
    actions: [{ label: 'Vazgeç' }, { label: 'Sil', class: 'danger', onClick: async () => {
      const r = await api.del(`/api/projects/${p.id}?confirm=${encodeURIComponent(inp.value)}`); toast(t('Proje silindi · {n} bağlantı kaldırıldı', { n: r.untagged })); location.hash = '#/projects';
    } }] });
}

// ---------------- Hareketlere proje (karar kuyruğu) ----------------
async function queueView(root) {
  let d, status = 'open', nature = '', q = '', since = `${new Date().getFullYear()}-01-01`, shownN = 200;
  const chosen = new Set();
  const head = h('div'), out = h('div');
  const key = m => `${m.source}:${m.ref}`;
  async function load() {
    loading(out);
    try { d = await api.get(`/api/projects/queue/list?status=${status}&nature=${nature}&since=${since}`); } catch (e) { return clear(out, h('div', { class: 'card empty' }, e.message)); }
    chosen.clear(); shownN = 200; draw();
  }
  const bulkSel = h('select', { class: 'input', style: { maxWidth: '260px' } });
  const bulkBar = h('div', { class: 'pj-bulk' });
  function drawBulk() {
    clear(bulkSel, h('option', { value: '' }, '— Proje —'), (d?.projects || []).map(p => h('option', { value: p.id }, `${p.code} · ${p.name}`)));
    clear(bulkBar, h('b', null, t('{n} seçili', { n: chosen.size })), bulkSel,
      h('button', { class: 'btn sm primary', type: 'button', disabled: !chosen.size, onclick: () => bulk(Number(bulkSel.value) || 'need') }, 'Projeye bağla'),
      h('button', { class: 'btn sm', type: 'button', disabled: !chosen.size, onclick: () => bulk(null) }, 'Projesiz işaretle'));
    bulkBar.hidden = !chosen.size;
  }
  async function bulk(pid) {
    if (pid === 'need') return toast('Proje seçin', 'err');
    const items = [...chosen].map(k => { const [source, ref] = k.split(':'); return { source, ref: Number(ref), allocations: [] }; });
    try { const r = await api.post('/api/projects/decide/bulk', { items, project_id: pid }); toast(t('{n} hareket işlendi', { n: r.count }), 'success'); load(); } catch (e) { toastError(e); }
  }
  function draw() {
    const rows = d.rows.filter(m => matches(q, m.title, m.account, m.doc_no, m.category));
    const projName = id => d.projects.find(p => p.id === id);
    clear(head, h('div', { class: 'filters' },
      segmented([['open', t('Karar bekleyen ({n})', { n: d.counts.open })], ['done', t('Karar verilen ({n})', { n: d.counts.done })]], status, v => { status = v; load(); }),
      segmented([['', 'Tümü'], ['gider', 'Gider'], ['gelir', 'Gelir'], ['odeme', 'Tahsilat / ödeme']], nature, v => { nature = v; load(); })),
    h('div', { class: 'small muted', style: { margin: '-2px 0 8px' } }, t('{n} hareket · tümünü seçip toplu proje / projesiz işaretleyebilirsiniz', { n: rows.length })), bulkBar);
    drawBulk();
    const all = h('input', { type: 'checkbox', checked: rows.length && rows.slice(0, shownN).every(m => chosen.has(key(m))) });
    all.addEventListener('change', () => { rows.slice(0, shownN).forEach(m => (all.checked ? chosen.add(key(m)) : chosen.delete(key(m)))); draw(); });
    clear(out, rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table pj-q' },
      h('thead', null, h('tr', null, h('th', null, all), ['Tarih', 'Nitelik', 'Hareket', 'Belge', 'Tutar', 'Proje'].map(x => h('th', { class: x === 'Tutar' ? 'num' : '' }, x)))),
      h('tbody', null, rows.slice(0, shownN).map(m => {
        const c = h('input', { type: 'checkbox', checked: chosen.has(key(m)) });
        c.addEventListener('change', () => { if (c.checked) chosen.add(key(m)); else chosen.delete(key(m)); drawBulk(); });
        const sugg = !m.tags.length && m.suggest.length === 1 ? projName(m.suggest[0]) : null;
        return h('tr', null, h('td', null, c), h('td', { class: 'nowrap' }, fmtDate(m.date)), h('td', null, natureBadge(m.nature)),
          h('td', null, h('div', null, m.title), h('div', { class: 'small muted' }, m.account || '')),
          h('td', { class: 'mono small' }, m.doc_no || '—'),
          h('td', { class: 'num' }, h('b', null, money2(m.amount)), m.nature !== 'odeme' && m.net_exact && Math.abs(m.net - m.amount) > 0.01 ? h('div', { class: 'small muted' }, t('KDV hariç {n}', { n: money2(m.net) })) : null),
          h('td', null, sugg ? h('button', { class: 'pj-chip set', type: 'button', title: 'Anahtar kelime eşleşmesi — tek tıkla bağla', onclick: async () => {
            try { await api.put('/api/projects/decide', { source: m.source, ref: m.ref, allocations: [{ project_id: sugg.id }] }); toast(t('{p} projesine bağlandı', { p: sugg.code }), 'success'); load(); } catch (e) { toastError(e); }
          } }, `✓ ${sugg.code}`) : null, ' ', projectChip(m.tags, () => decideModal(m.source, m.ref, load))));
      }))), rows.length > shownN ? h('div', { class: 'ct-acts', style: { padding: '10px' } }, h('button', { class: 'btn sm', type: 'button', onclick: () => { shownN += 300; draw(); } }, t('Daha fazla göster ({n} kaldı)', { n: rows.length - shownN }))) : null)
      : h('div', { class: 'card empty' }, status === 'open' ? 'Proje kararı bekleyen hareket yok. 🎉' : 'Kayıt yok.'));
  }
  const sinceSel = h('select', { class: 'input', style: { maxWidth: '170px' } }, [[`${new Date().getFullYear()}-01-01`, 'Bu yıl'], [`${new Date().getFullYear() - 1}-01-01`, 'Geçen yıldan beri'], ['', 'Tüm zamanlar']]
    .map(([v, l]) => h('option', { value: v, selected: v === since }, l)));
  sinceSel.addEventListener('change', () => { since = sinceSel.value; load(); });
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Açıklama, cari, belge no ara…', style: { maxWidth: '240px' } });
  search.addEventListener('input', () => { q = search.value.trim(); if (d) draw(); });
  clear(root, h('p', { class: 'small muted fl-intro' }, 'Her finansal hareket için proje seçin ya da “Projesiz” işaretleyin. Gelir ve gider proje kâr-zararına KDV hariç girer; tahsilat / ödemeler projenin nakit akışında görünür. Alış faturalarında “Kalem bazında” seçeneğiyle yalnızca projeye alınan malzemeleri ayırabilirsiniz.'),
    h('div', { class: 'filters' }, sinceSel, search), head, out);
  await load();
}

// ---------------- Proje taraması ----------------
async function scanView(root) {
  loading(root);
  let d, list, mk;
  try { [d, list, mk] = await Promise.all([api.get('/api/projects/scan/discover'), api.get('/api/projects'), api.get('/api/projects/scan/mikro')]); } catch (e) { return clear(root, h('div', { class: 'card empty' }, e.message)); }
  META = list.meta;
  const withKw = list.rows.filter(p => p.keywords || p.mikro_code);
  const pr = mk.probe;
  const probeTxt = !pr ? 'Mikro proje kodları henüz senkronlanmadı (Program Ayarları › Entegrasyonlar › Mikro senkronu çalışınca gelir).'
    : t('Son senkron {d}: proje kartı {a}, kodlu cari hareketi {b}, kodlu muhasebe satırı {c}', { d: fmtDate(pr.at), a: pr.projeler, b: pr.cari_hareket, c: pr.muhasebe });
  clear(root,
    h('section', { class: 'card card-pad', style: { marginBottom: '12px' } }, h('h3', { class: 'fl-h3' }, t('Mikro projeleri ({n})', { n: mk.rows.length })),
      h('p', { class: 'small muted' }, probeTxt),
      mk.rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['Kod', 'Ad', 'Cari hareketi', 'Muhasebe satırı', ''].map(x => h('th', { class: /hareketi|satırı/.test(x) ? 'num' : '' }, x)))),
        h('tbody', null, mk.rows.map(r => h('tr', null, h('td', { class: 'mono' }, r.code), h('td', null, r.name || '—'), h('td', { class: 'num' }, r.txns), h('td', { class: 'num' }, r.ledger),
          h('td', null, r.project_id ? h('a', { class: 'btn sm', href: `#/projects/${r.project_id}` }, 'Projeye git')
            : h('button', { class: 'btn sm primary', type: 'button', onclick: () => projectForm(null, id => { location.hash = `#/projects/${id}`; }, { name: r.name || r.code, mikro_code: r.code }) }, 'Proje oluştur')))))))
        : null),
    h('section', { class: 'card card-pad', style: { marginBottom: '12px' } }, h('h3', { class: 'fl-h3' }, 'Anahtar kelime eşleşmeleri'),
      h('p', { class: 'small muted' }, 'Projelerin anahtar kelimeleri, kararı verilmemiş hareketlerin açıklamaları ve muhasebe kayıtlarında aranır. Yalnızca tek bir projeyle eşleşen hareketler bağlanır.'),
      withKw.length ? h('div', { class: 'ct-acts' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        try { const r = await api.post('/api/projects/scan/apply'); toast(t('{n} hareket projelerine bağlandı', { n: r.tagged }), 'success'); scanView(root); } catch (e) { toastError(e); }
      } }, 'Tüm eşleşmeleri bağla'), h('span', { class: 'small muted' }, t('{n} projede anahtar kelime tanımlı', { n: withKw.length }))) : h('p', { class: 'muted' }, 'Henüz anahtar kelimesi tanımlı proje yok.')),
    h('section', { class: 'card card-pad' }, h('h3', { class: 'fl-h3' }, t('Mevcut verilerde bulunan proje adayları ({n})', { n: d.candidates.length })),
      h('p', { class: 'small muted' }, 'Gelir / gider hareketlerinin ve muhasebe kayıtlarının açıklamalarında farklı aylarda ve belgelerde tekrar eden, firma ya da hesap adı olmayan ifadeler. Bir aday gerçek bir projeyse “Proje oluştur” deyin; ifade anahtar kelime olarak eklenir ve eşleşen hareketler önerilir.'),
      d.candidates.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, ['İfade', 'Belge', 'Ay', 'Tutar', 'Örnekler', ''].map(x => h('th', { class: ['Belge', 'Ay', 'Tutar'].includes(x) ? 'num' : '' }, x)))),
        h('tbody', null, d.candidates.map(c => h('tr', null, h('td', null, h('b', null, c.phrase)), h('td', { class: 'num' }, c.count), h('td', { class: 'num' }, c.months),
          h('td', { class: 'num' }, money(c.amount)), h('td', { class: 'small muted' }, c.samples.join(' · ')),
          h('td', null, h('button', { class: 'btn sm', type: 'button', onclick: () => projectForm(null, id => { location.hash = `#/projects/${id}`; },
            { name: c.phrase.toLocaleLowerCase('tr').replace(/(^|\s)\S/g, s => s.toLocaleUpperCase('tr')), keywords: c.phrase }) }, 'Proje oluştur')))))))
        : h('p', { class: 'muted' }, 'Belirgin bir proje adayı bulunamadı.')));
}
