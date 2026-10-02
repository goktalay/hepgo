// Raporlar: tüm modüllerin raporları. Kullanıcı yalnızca girebildiği modüllerin raporlarını görür (sunucu süzer).
// Liste: düğmeler (üstte rapor adı, altta modülü), kart / liste görünümü, modül filtresi. Rapor: dönem seçimi; Grafik
// (göstergeler, çıkarımlar, grafikler) ya da Baskı (göstergeler, tablolar) görünümü; ikisi de antetli yazdırılır.
// Grafikler Chart.js (static/vendor/chartjs, yerel kopya) ile; gün × saat ısı haritası kendi bileşenimiz.
import { api } from '../api.js';
import { icons } from '../icons.js';
import { foot, head, printPage } from '../print.js';
import { clear, fmtDateTime, h, matches, moduleToolbar, onLeave, pageHead, pref, segmented, setPref, statStrip, svgIcon, toastError, periodRange } from '../ui.js';

export const MODULE_NAMES = {
  production: 'Üretim Yönetimi', orders: 'İş Emri Yönetimi', warehouse: 'Depo Yönetimi', stock: 'Stok Yönetimi', printers: 'Yazıcı Yönetimi',
  field: 'Saha Yönetimi', companies: 'Firma Yönetimi', documents: 'Evrak Yönetimi', secretariat: 'Sekreterya', security: 'Güvenlik', hr: 'İnsan Kaynakları', mrp: 'MRP', purchasing: 'Satın Alma',
  admin: 'Yönetim', products: 'Ürün Yönetimi',
};
const MODULE_TONE = {
  production: '#1f6feb', orders: '#0891b2', warehouse: '#d97706', stock: '#65a30d', printers: '#7c3aed', field: '#16a34a',
  companies: '#db2777', documents: '#9333ea', secretariat: '#ea580c', security: '#dc2626', admin: '#475569', products: '#0d9488',
};
const PALETTE = ['#1f6feb', '#16a34a', '#f59e0b', '#dc2626', '#9333ea', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569', '#0d9488', '#7c3aed'];

let chartLib;
export const loadChart = () => (chartLib ??= new Promise((resolve, reject) => {
  if (window.Chart) return resolve(window.Chart);
  const s = h('script', { src: '/static/vendor/chartjs/chart.umd.min.js' });
  s.onload = () => resolve(window.Chart);
  s.onerror = () => { chartLib = null; reject(new Error('Grafik kütüphanesi yüklenemedi')); };
  document.head.append(s);
}));

export async function render(view, params, ctx) {
  if (params[0]) return renderReport(view, params[0], ctx);
  const list = await api.get('/api/reports');
  let mode = pref('reports.view', 'card');
  let mod = '';
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Rapor ara…', style: { width: '220px' } });
  const modSel = h('select', { class: 'input', title: 'Modül' });
  const out = h('div');
  const mods = [...new Set(list.map(r => r.module))];
  const drawChips = () => clear(modSel, [['', 'Tüm modüller', list.length], ...mods.map(m => [m, MODULE_NAMES[m] || m, list.filter(r => r.module === m).length])]
    .map(([k, label, n]) => h('option', { value: k, selected: mod === k }, `${label} (${n})`)));
  modSel.addEventListener('change', () => { mod = modSel.value; draw(); });
  const draw = () => {
    const rows = list.filter(r => (!mod || r.module === mod) && matches(q.value, r.title, r.desc, MODULE_NAMES[r.module]));
    clear(out, !rows.length ? h('div', { class: 'card empty' }, 'Rapor bulunamadı')
      : mode === 'card' ? h('div', { class: 'rp-grid' }, rows.map(r => h('a', { class: 'rp-card', href: `#/reports/${r.key}`, title: r.desc, style: { '--tone': MODULE_TONE[r.module] } },
        h('span', { class: 'rp-ico' }, svgIcon(icons[r.module] || icons.documents)),
        h('b', null, r.title),
        h('span', { class: 'rp-mod' }, MODULE_NAMES[r.module] || r.module),
        h('small', null, r.desc))))
        : h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, ['Rapor', 'Modül', 'Açıklama'].map(t => h('th', null, t)))),
          h('tbody', null, rows.map(r => h('tr', { class: 'click', onclick: () => { location.hash = `#/reports/${r.key}`; } },
            h('td', null, h('b', null, r.title)),
            h('td', null, h('span', { class: 'rp-mod-tag', style: { '--tone': MODULE_TONE[r.module] } }, MODULE_NAMES[r.module] || r.module)),
            h('td', { class: 'wrap muted' }, r.desc))))))));
  };
  q.addEventListener('input', draw);
  const viewSeg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('reports.view', v); draw(); });
  clear(view, pageHead('Raporlar', { back: '#/', sub: `${list.length} rapor · modül raporları` }),
    moduleToolbar(viewSeg),
    h('div', { class: 'filters' }, modSel, q), out);
  drawChips();
  draw();
}

// ---------- Rapor
const iso = d => d.toISOString().slice(0, 10);
function preset(key) {
  const t = new Date();
  const d = n => { const x = new Date(t); x.setDate(x.getDate() - n); return x; };
  if (key === 'week') { const r = periodRange('week'); return [r.date_from, r.date_to]; }
  if (key === '7') return [iso(d(6)), iso(t)];
  if (key === '30') return [iso(d(29)), iso(t)];
  if (key === '90') return [iso(d(89)), iso(t)];
  if (key === 'month') return [iso(new Date(t.getFullYear(), t.getMonth(), 1, 12)), iso(t)];
  if (key === 'last') return [iso(new Date(t.getFullYear(), t.getMonth() - 1, 1, 12)), iso(new Date(t.getFullYear(), t.getMonth(), 0, 12))];
  if (key === 'year') return [iso(new Date(t.getFullYear(), 0, 1, 12)), iso(t)];
  return null;
}

async function renderReport(view, key, ctx) {
  let range = pref(`reports.range2`, 'week');   // varsayılan: bu hafta
  let [from, to] = preset(range) || preset('week');
  let type = pref('reports.type', 'chart');
  let data = null;
  let charts = [];
  const destroy = () => { charts.forEach(c => c.destroy()); charts = []; };
  onLeave(destroy);
  const body = h('div');
  const fromI = h('input', { class: 'input', type: 'date', value: from });
  const toI = h('input', { class: 'input', type: 'date', value: to });
  // Dönem: açılır liste; tarih elle değişince "Özel aralık"
  const rangeSeg = h('select', { class: 'input', title: 'Dönem' }, [['week', 'Bu hafta'], ['7', 'Son 7 gün'], ['30', 'Son 30 gün'], ['month', 'Bu ay'], ['last', 'Geçen ay'],
    ['90', 'Son 90 gün'], ['year', 'Bu yıl'], ['', 'Özel aralık']].map(([k, label]) => h('option', { value: k, selected: k === range }, label)));
  rangeSeg.addEventListener('change', () => {
    range = rangeSeg.value;
    if (!range) return;
    setPref('reports.range2', range);
    [fromI.value, toI.value] = preset(range);
    load();
  });
  for (const el of [fromI, toI]) el.addEventListener('change', () => { range = ''; rangeSeg.value = ''; load(); });
  const typeSeg = segmented([['chart', 'Grafik'], ['print', 'Baskı']], type, v => { type = v; setPref('reports.type', v); draw(); });
  const printBtn = h('button', { class: 'btn primary', type: 'button', onclick: () => printReport() }, 'Yazdır (antetli)');
  const headBox = h('div');

  async function load() {
    clear(body, h('div', { class: 'loading' }, 'Rapor hazırlanıyor…'));
    try {
      data = await api.get(`/api/reports/${key}?date_from=${fromI.value}&date_to=${toI.value}`);
    } catch (err) { clear(body, h('div', { class: 'card empty' }, err.message)); return; }
    clear(headBox, pageHead(data.title, { back: '#/reports', sub: h('span', null, h('span', { class: 'rp-mod-tag', style: { '--tone': MODULE_TONE[data.module] } },
      MODULE_NAMES[data.module] || data.module), `  ${data.desc}`) }), moduleToolbar(typeSeg, printBtn));
    draw();
  }

  async function draw() {
    destroy();
    const d = data;
    const stats = statStrip();
    stats.set(d.kpis);
    const insights = d.insights.length ? h('div', { class: 'rp-insights' }, h('b', null, 'Öne çıkanlar'), h('ul', null, d.insights.map(t => h('li', null, t)))) : null;
    if (type === 'print') {
      clear(body, stats, insights, d.tables.map(tableCard));
      return;
    }
    const grid = h('div', { class: 'rp-charts' });
    clear(body, stats, insights, grid);
    let Chart;
    try { Chart = await loadChart(); } catch (err) { toastError(err); }
    for (const c of d.charts) {
      if (c.type === 'heat') { grid.append(h('div', { class: `card rp-chart ${c.wide ? 'wide' : ''}` }, h('h3', null, c.title), heatEl(c.heat))); continue; }
      const canvas = h('canvas');
      // yatay çubukta yükseklik satır sayısına göre (çok yazıcı / parça üst üste binmesin)
      const tall = c.type === 'hbar' && hasData(c) ? { height: `${Math.max(c.wide ? 340 : 300, c.labels.length * 26 + 60)}px` } : {};
      const card = h('div', { class: `card rp-chart ${c.wide ? 'wide' : ''} ${c.type === 'doughnut' ? 'donut' : ''}` }, h('h3', null, c.title),
        h('div', { class: 'rp-canvas', style: tall }, canvas));
      grid.append(card);
      if (Chart && hasData(c)) charts.push(new Chart(canvas, chartConfig(c, theme(), true)));
      else card.append(h('div', { class: 'empty small' }, 'Bu dönemde veri yok'));
    }
    if (!d.charts.length) grid.append(h('div', { class: 'card empty wide' }, 'Bu raporda grafik yok; Baskı görünümünü kullanın.'));
  }

  // Antetli çıktı: logo, rapor adı, dönem, hazırlayan; grafik görünümünde grafikler (açık tema resim), baskıda tablolar
  async function printReport() {
    const d = data;
    let chartImgs = [];
    if (type === 'chart') {
      const Chart = await loadChart().catch(() => null);
      chartImgs = d.charts.map(c => {
        if (c.type === 'heat') return h('div', { class: 'pr-chart' }, h('h3', null, c.title), heatEl(c.heat));
        if (!Chart || !hasData(c)) return null;
        const canvas = h('canvas', { width: c.wide ? 1400 : 900, height: c.type === 'hbar' ? Math.max(360, c.labels.length * 34) : 460 });
        const box = h('div', { style: { position: 'fixed', left: '-5000px', top: 0, width: `${canvas.width}px`, height: `${canvas.height}px` } }, canvas);
        document.body.append(box);
        const ch = new Chart(canvas, chartConfig(c, lightTheme, false, true));
        const img = ch.toBase64Image('image/png', 1);
        ch.destroy();
        box.remove();
        return h('div', { class: `pr-chart ${c.wide ? 'wide' : ''}` }, h('h3', null, c.title), h('img', { src: img, alt: c.title }));
      }).filter(Boolean);
    }
    const kpis = h('div', { class: 'pr-kpis' }, d.kpis.map(k => h('div', null, h('b', null, String(k.value ?? '—')), h('span', null, k.label))));
    const ins = d.insights.length ? h('div', { class: 'pr-ins' }, h('b', null, 'Öne çıkanlar'), h('ul', null, d.insights.map(t => h('li', null, t)))) : null;
    const fmtD = s => `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}`;
    printPage(h('div', { class: 'pf-page pf-flow rp-print' },
      head(ctx.meta.company, data.title.toLocaleUpperCase('tr'), [
        ['Modül', MODULE_NAMES[d.module] || d.module], ['Dönem', `${fmtD(d.params.from)} – ${fmtD(d.params.to)}`],
        ['Rapor tarihi', fmtDateTime(new Date().toISOString())], ['Hazırlayan', ctx.user.full_name]]),
      h('p', { class: 'pr-desc' }, d.desc), kpis, ins,
      type === 'chart' ? h('div', { class: 'pr-charts' }, chartImgs) : d.tables.map(t => h('div', { class: 'pr-table' },
        h('h2', { class: 'pf-h2' }, t.title), t.sub ? h('p', { class: 'pr-sub' }, t.sub) : null, tableEl(t, true))),
      foot(ctx.meta.company, `${data.title} · ${type === 'chart' ? 'Grafik' : 'Baskı'} · Yazdırma: ${fmtDateTime(new Date().toISOString())}`)),
    `Rapor: ${data.title}`);
  }

  clear(view, headBox, h('div', { class: 'filters' }, rangeSeg, fromI, toI), body);
  await load();
}

const hasData = c => c.datasets?.some(ds => ds.data?.some(v => v));

function tableCard(t) {
  return h('div', { class: 'card rp-table' }, h('div', { class: 'rp-table-head' }, h('h3', null, t.title), h('span', { class: 'small muted' }, `${t.rows.length} satır`)),
    t.sub ? h('p', { class: 'small muted', style: { margin: '0 14px 8px' } }, t.sub) : null,
    t.rows.length ? h('div', { class: 'table-wrap' }, tableEl(t)) : h('div', { class: 'empty small' }, 'Bu dönemde kayıt yok'));
}

function tableEl(t, print = false) {
  return h('table', { class: print ? 'pf-table pf-list' : '' },
    h('thead', null, h('tr', null, t.columns.map(c => h('th', { class: c.align === 'num' ? 'num' : '' }, c.label)))),
    h('tbody', null, t.rows.map(r => h('tr', null, t.columns.map(c => h('td', { class: c.align === 'num' ? 'num' : 'wrap' }, r[c.key] ?? '—'))))));
}

// Gün × saat ısı haritası
export function heatEl(hm) {
  const max = Math.max(1, ...hm.values.flat());
  return h('div', { class: 'rp-heat' }, h('table', null,
    h('thead', null, h('tr', null, h('th', null, ''), hm.cols.map(c => h('th', null, c)))),
    h('tbody', null, hm.rows.map((r, i) => h('tr', null, h('th', null, r), hm.values[i].map((v, j) => h('td', {
      title: `${r} ${hm.cols[j]}:00 · ${v}`,
      style: { background: v ? `rgba(31, 111, 235, ${0.12 + 0.88 * v / max})` : 'transparent', color: v / max > 0.55 ? '#fff' : 'inherit' },
    }, v || '')))))));
}

// ---------- Chart.js yapılandırması
const lightTheme = { text: '#1f2937', muted: '#6b7280', grid: 'rgba(0,0,0,.08)', bg: '#ffffff' };
export function theme() {
  const cs = getComputedStyle(document.documentElement);
  return { text: cs.getPropertyValue('--text').trim() || '#1f2937', muted: cs.getPropertyValue('--muted').trim() || '#6b7280',
    grid: document.documentElement.dataset.theme === 'dark' ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.07)', bg: 'transparent' };
}

export function chartConfig(c, th, animate, forPrint = false) {
  const doughnut = c.type === 'doughnut';
  const horizontal = c.type === 'hbar';
  const stacked = !!c.stacked;
  const datasets = c.datasets.map((ds, i) => {
    const color = PALETTE[i % PALETTE.length];
    if (doughnut) return { label: ds.label, data: ds.data, backgroundColor: c.labels.map((_, j) => PALETTE[j % PALETTE.length]), borderWidth: 2, borderColor: th.bg === 'transparent' ? '#ffffff00' : '#fff' };
    if (ds.line || c.type === 'line' || c.type === 'area') {
      return { type: 'line', label: ds.label, data: ds.data, borderColor: color, backgroundColor: `${color}33`, fill: c.type === 'area',
        tension: 0.3, pointRadius: c.labels.length > 40 ? 0 : 3, borderWidth: 2.5, yAxisID: ds.axis ? 'y2' : 'y', spanGaps: false, order: 0,
        borderDash: ds.dash ? [6, 5] : undefined };
    }
    return { type: 'bar', label: ds.label, data: ds.data, backgroundColor: `${color}d9`, borderColor: color, borderWidth: 0, borderRadius: 4,
      maxBarThickness: 42, order: 1 };
  });
  const y2 = c.datasets.find(ds => ds.axis);
  const scales = doughnut ? {} : {
    x: { stacked, beginAtZero: true, ticks: { color: th.muted, maxRotation: 60, autoSkip: !horizontal, ...(horizontal ? { precision: 0 } : {}) }, grid: { display: horizontal, color: th.grid }, ...(horizontal && c.max ? { max: c.max } : {}) },
    y: { stacked, beginAtZero: true, ticks: { color: th.muted, precision: 0 }, grid: { display: !horizontal, color: th.grid }, ...(!horizontal && c.max ? { max: c.max } : {}) },
    ...(y2 ? { y2: { position: 'right', beginAtZero: true, ticks: { color: th.muted }, grid: { display: false }, ...(y2.axis === 'pct' ? { max: 100, ticks: { color: th.muted, callback: v => `%${v}` } } : {}) } } : {}),
  };
  return {
    type: doughnut ? 'doughnut' : c.type === 'line' || c.type === 'area' ? 'line' : 'bar',
    data: { labels: c.labels, datasets },
    options: {
      indexAxis: horizontal ? 'y' : 'x', responsive: !forPrint, maintainAspectRatio: false, animation: animate ? { duration: 500 } : false,
      devicePixelRatio: forPrint ? 2 : undefined, cutout: doughnut ? '58%' : undefined,
      plugins: {
        legend: { display: doughnut || c.datasets.length > 1, position: doughnut ? 'right' : 'top', labels: { color: th.text, boxWidth: 12, font: { size: forPrint ? 15 : 12 } } },
        tooltip: { mode: doughnut ? 'nearest' : 'index', intersect: false },
      },
      scales,
    },
    plugins: forPrint ? [{ id: 'bg', beforeDraw: ch => { const x = ch.ctx; x.save(); x.fillStyle = '#fff'; x.fillRect(0, 0, ch.width, ch.height); x.restore(); } }] : [],
  };
}
