// Üretim Yönetimi: sipariş panosu (Todo / Liste / Kart) ve parça bazlı sipariş detayı
import { setListExport } from '../listexport.js';
import { api, fileUrl } from '../api.js';
import { icons } from '../icons.js';
import { layerToggle, loadPlane, partInfoLines, renderAssembly, renderPlane } from '../plane.js';
import { logoOf } from './companies.js';
import { printWipReport } from '../print.js';
import { partInPrinter } from '../gcode3d.js';
import { ORDER_STATES, PART_STATES, PRINTER_STATES, badge, orderBadge, queuePlate } from '../status.js';
import {
  clear, dateTimeInput, every, field, fmtDate, fmtDateTime, fmtDuration, fmtMinutes, h, matches, modal, moduleToolbar, pageHead, pref,
  multiSelect, peoplePicker, progressBar, secondsBetween, secondsSince, segmented, selectInput, setPref, shortCompany, svgIcon, t, toast, toastError,
} from '../ui.js';

const BOARD_COLUMNS = ['SIPARIS', 'URETIM', 'HATA', 'DEPO', 'MONTAJ', 'SAHADA_MONTAJ', 'KALIBRASYON', 'SAHA_ONAY'];
// Todo panosunda varsayılan sütunlar; diğerleri "Sütunlar" düğmeleriyle açılıp kapatılır (kullanıcı tercihi)
const DEFAULT_COLUMNS = ['SIPARIS', 'URETIM', 'DEPO', 'MONTAJ', 'SAHADA_MONTAJ', 'KALIBRASYON'];
// Montaja geçmiş uçak parça parça değil, bölüm / bütün olarak gösterilir
const ASSEMBLY_VIEW = ['MONTAJ', 'SAHADA_MONTAJ', 'KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI'];
const IN_ASSEMBLY = ['MONTAJ', 'SAHADA_MONTAJ'];
const PART_OPERATORS = ['Sistem Yöneticisi', 'Üretim Yöneticisi', 'Üretim Sorumlusu'];

export async function render(view, params, ctx) {
  if (params[0]) return renderOrder(view, Number(params[0]), ctx);
  return renderBoard(view, ctx);
}

// Üretim Yönetimi alt-modül sekmeleri: Yarı Mamul (üretim panosu), İş Emri Yönetimi ve Yazıcı Yönetimi.
export function subnav(active, ctx) {
  const mk = (k, label, href, ico) => h('button', { class: k === active ? 'on' : '', type: 'button', onclick: () => { location.hash = href; } },
    svgIcon(icons[ico]), label);
  const tabs = [mk('room', 'Yarı Mamul', '#/production', 'stock')];
  if (ctx.user.modules.includes('orders')) tabs.push(mk('is-emri', 'İş Emri Yönetimi', '#/orders', 'orders'));
  if (ctx.user.modules.includes('printers') && ctx.user.printer) tabs.push(mk('printers', 'Yazıcı Yönetimi', '#/printers', 'printers'));   // yalnız yazıcı entegrasyonu eklenmiş + açıksa
  return h('div', { class: 'seg seg-tabs' }, tabs);
}

// ---------- Pano ----------
async function renderBoard(view, ctx) {
  let mode = pref('production.view', 'todo');
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Sipariş, firma, kişi, kuyruk no ara…', style: { width: '220px' } });
  const status = selectInput(BOARD_COLUMNS.map(k => [k, ORDER_STATES[k].label]), { all: 'Tüm durumlar' });
  const product = h('select', { class: 'input' });
  const body = h('div');
  let orders = [];

  const draw = () => {
    const list = orders.filter(o =>
      o.status !== 'TAMAMLANDI' &&
      (!status.value || o.status === status.value) &&
      (!product.value || String(o.product_id) === product.value) &&
      matches(q.value, o.code, o.created_by_name, o.queue_no, o.product_name, o.product_serial, o.company_name));
    setListExport(() => ({ columns: ['Sipariş', 'Kuyruk no', 'Firma', 'Ürün', 'Durum', 'Siparişi veren', 'Sipariş tarihi', 'Başlama', 'Bitiş', 'İlerleme %'],
      rows: list.map(o => [o.code, o.queue_no || '', o.company_name || '', o.product_name || '', ORDER_STATES[o.status]?.label || o.status, o.created_by_name || '', o.created_at, o.start_date || '', o.end_date || '',
        o.progress != null ? Math.round(o.progress) : '']) }));
    colBar.hidden = mode !== 'todo';
    if (mode === 'todo') {
      drawColBar(list);
      return clear(body, kanban(list.filter(o => o.status !== 'TAMAMLANDI'), columns));
    }
    if (!list.length) return clear(body, h('div', { class: 'card empty' }, 'Filtreye uyan sipariş yok'));
    clear(body, mode === 'list' ? listView(list) : h('div', { class: 'grid-cards' }, list.map(orderCard)));
  };
  const load = async () => {
    const [o, products] = await Promise.all([api.get('/api/orders'), api.get('/api/products')]);
    orders = o;
    if (!product.options.length) clear(product, h('option', { value: '' }, 'Tüm ürünler'), products.filter(p => p.orderable).map(p => h('option', { value: p.id }, `${p.name} (${p.serial})`)));   // yalnızca sipariş verilebilir ürünler
    draw();
  };
  q.addEventListener('input', draw);
  [status, product].forEach(el => el.addEventListener('change', draw));

  // Sütun seçimi: her aşama bir düğme; açık olanlar panoda sütun olarak görünür
  let columns = String(pref('production.columns.v2', DEFAULT_COLUMNS.join(','))).split(',').filter(c => BOARD_COLUMNS.includes(c));
  if (!columns.length) columns = [...DEFAULT_COLUMNS];
  // Sütunlar: onay kutulu açılır liste (en az bir sütun kalır); yanında her durumdaki sipariş sayısı
  const colOptions = list => BOARD_COLUMNS.map(c => [c, ORDER_STATES[c].label, list.filter(o => o.status === c).length]);
  const colBar = multiSelect('Sütunlar', colOptions([]), columns, v => { columns = v; setPref('production.columns.v2', columns.join(',')); draw(); }, {
    min: 1,
    extra: h('button', { class: 'btn sm', type: 'button', onclick: () => { columns = [...DEFAULT_COLUMNS]; setPref('production.columns.v2', columns.join(',')); draw(); } }, 'Varsayılan'),
  });
  function drawColBar(list) { colBar.set(columns, colOptions(list)); }

  const viewSeg = segmented([['todo', 'Todo'], ['list', 'Liste'], ['cards', 'Kart']], mode, v => { mode = v; setPref('production.view', v); draw(); });
  clear(view,
    pageHead('Üretim Yönetimi', { back: '#/', sub: 'Yarı Mamul', tabs: subnav('room', ctx) }),
    h('div', { class: 'filters' },
      q, status, product, colBar,
      h('span', { class: 'spacer' }),
      viewSeg, h('div', { class: 'pill-group module-pills' })),   // Excel bu gruba (görünüm seçicisinin sağına) düşer
    body);
  await load();
  every(30000, () => load().catch(() => {}));
}

const openOrder = o => { location.hash = `#/production/${o.id}`; };

// Siparişin firması: logo + ad
export const companyTag = (o, size = 'sm') => (o.company_name
  ? h('span', { class: 'order-co', title: o.company_name }, logoOf({ name: o.company_name, logo: o.company_logo }, `co-logo ${size}`),
    h('span', { class: 'order-co-name' }, shortCompany(o.company_name)))
  : null);

function orderCard(o) {
  return h('div', { class: 'card order-card', onclick: () => openOrder(o) },
    h('div', { class: 'top' }, h('span', { class: 'code' }, o.code), orderBadge(o)),
    companyTag(o),
    h('div', { class: 'small muted' }, o.product_stocked
      ? t('Parça baskısı · {name} · {n} adet', { name: o.product_name, n: o.per_print }) : `${o.product_name} · ${o.product_serial}`),
    h('dl', null,
      h('dt', null, 'Siparişi veren'), h('dd', null, o.created_by_name || '—'),
      h('dt', null, 'Sipariş'), h('dd', null, fmtDate(o.created_at)),
      h('dt', null, 'Başlama'), h('dd', null, fmtDate(o.start_date)),
      h('dt', null, 'Bitiş'), h('dd', null, fmtDate(o.end_date)),
      o.queue_no ? [h('dt', null, 'Kuyruk no'), h('dd', null, queuePlate(o.queue_no))] : null),
    progressBar(o.progress),
    o.counts.HATA ? h('div', { class: 'small', style: { color: 'var(--danger)' } }, t('{n} parçada hata', { n: o.counts.HATA })) : null);
}

function kanban(list, columns) {
  return h('div', { class: 'kanban', style: { gridTemplateColumns: `repeat(${columns.length}, minmax(210px, 1fr))` } }, columns.map(col => {
    const items = list.filter(o => o.status === col);
    return h('div', { class: 'kanban-col' },
      h('h3', null, ORDER_STATES[col].label, h('span', { class: 'badge gray' }, items.length)),
      h('div', { class: 'stack' }, items.map(orderCard)));
  }));
}

function listView(list) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null,
      ['Sipariş', 'Ürün', 'Başlama', 'Bitiş', 'Durum', 'İlerleme', 'Üretimde', 'Hata', 'Kuyruk no'].map(t => h('th', null, t)))),
    h('tbody', null, list.map(o => h('tr', { class: 'click', onclick: () => openOrder(o) },
      h('td', null, h('b', null, o.code), o.company_name ? h('div', { class: 'order-co-line' }, companyTag(o, 'xs')) : null),
      h('td', null, o.product_name, h('div', { class: 'small muted' }, o.product_serial)),
      h('td', null, fmtDate(o.start_date)),
      h('td', null, fmtDate(o.end_date)),
      h('td', null, orderBadge(o)),
      h('td', { style: { minWidth: '160px' } }, progressBar(o.progress)),
      h('td', { class: 'num' }, o.counts.URETIMDE || 0),
      h('td', { class: 'num' }, o.counts.HATA || 0),
      h('td', null, queuePlate(o.queue_no) || '—'))))));
}

// ---------- Sipariş detayı ----------
async function renderOrder(view, id, ctx) {
  let order = await api.get(`/api/orders/${id}`);
  const plane = await loadPlane(order.product_id);
  const spare = !!order.product_stocked;   // basılı stok parçası: montaj yok, parça görünümünde kalır
  if (!spare && ASSEMBLY_VIEW.includes(order.status)) return renderAssemblyOrder(view, order, plane, ctx);
  const canOperate = ctx.user.roles.some(r => PART_OPERATORS.includes(r));
  let byPart = new Map(order.parts.map(p => [p.part_id, p]));

  const head = h('div');
  const stats = h('ul', { class: 'stat-list' });
  const sectionsBox = h('div');
  // Bölüm bölüm montaj: bölümün tüm parçaları depoda (onaylı) ise, sipariş üretimdeyken de o bölüm monte edilebilir
  const secState = key => (order.assembly?.steps?.[key] ? 'done' : order.assembly?.section_parts?.[key]?.all_ready ? 'ready' : null);
  const pl = renderPlane(plane, {
    sections: !spare,
    sectionState: secState,
    sectionLabel: key => {
      const name = order.assembly.sections[key];
      return secState(key) === 'done'
        ? [name, { text: 'Montaj tamamlandı', class: 'sub' }]
        : [name, { text: 'Montaja hazır', class: 'sub' }, { text: 'Tıklayın', class: 'muted' }];
    },
    fill: part => PART_STATES[byPart.get(part.id)?.state]?.color || 'var(--part-fill)',
    tooltip: part => {
      const op = byPart.get(part.id);
      const sec = !spare && part.section && part.group !== 'cover' ? secState(part.section) : null;
      return [
        sec === 'ready' ? h('b', { style: { color: 'var(--warning)' } }, t('{name} montaja hazır — tıklayın', { name: order.assembly.sections[part.section] })) : null,
        sec === 'done' ? h('b', { style: { color: 'var(--success)' } }, t('{name} montajı tamamlandı', { name: order.assembly.sections[part.section] })) : null,
        h('span', null, 'Durum: ', h('b', null, PART_STATES[op.state].label)),
        op.printer_name && op.state === 'URETIMDE' ? t('Yazıcı: {name}', { name: op.printer_name }) : null,
        op.state === 'URETIMDE' ? t('Yazdırma: {d}', { d: fmtDuration(op.print_seconds ?? (op.printer_started_at
          ? secondsBetween(op.printer_started_at, op.printer_done_at || new Date().toISOString()) : secondsSince(op.started_at))) })
          + (part.print_minutes ? ` / ${fmtMinutes(part.print_minutes)}` : '') : null,
        ...waitLines(op),
        op.direct_pending ? 'Doğrudan depo ekleme: onay bekliyor' : null,
        op.state === 'DEPO' && !op.approved_at ? 'Depo onayı bekliyor' : null,
        part.layer === 'electronics' ? ekStateText(op) : null,
        ...partInfoLines(part, plane.groups),
      ];
    },
    onClick: part => {
      const sec = !spare && part.section && part.group !== 'cover' ? secState(part.section) : null;
      if (sec === 'ready') return sectionModal(order, part.section, order.assembly.sections[part.section], refresh);
      if (sec === 'done') return stepInfo(order, order.assembly, part.section);
      return clickPart(order, byPart.get(part.id), part, refresh, canOperate);
    },
  });

  function drawSections() {
    if (spare || !order.assembly) return;
    const asm = order.assembly;
    clear(sectionsBox,
      h('h2', { style: { fontSize: '15px', margin: '14px 0 8px' } }, 'Bölüm montajı'),
      h('div', { class: 'asm-summary' }, Object.entries(asm.sections).map(([k, name]) => {
        const sp = asm.section_parts[k];
        const st = secState(k);
        return h('div', { class: `row-step ${st === 'done' ? 'done' : 'todo'}` },
          h('div', { class: 'top', style: { display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' } },
            h('b', null, name),
            st === 'done' ? h('span', { class: 'badge green' }, 'Tamamlandı')
              : st === 'ready' ? h('button', { class: 'btn sm success', onclick: () => sectionModal(order, k, name, refresh) }, 'Montajı Tamamla')
                : h('span', { class: 'badge gray' }, t('{ready}/{total} parça depoda', { ready: sp.ready, total: sp.total }))),
          st === 'done' ? h('div', { class: 'small muted' }, [fmtDateTime(asm.steps[k].at), staffNames(asm.steps[k])].filter(Boolean).join(' · '))
            : st === 'ready' ? h('div', { class: 'small muted' }, 'Tüm parçalar depoda; montaja başlanabilir') : null);
      }),
      // Birleştirme, kapaklar basılırken de yapılabilir; kapaklar en son (tüm parçalar depoya girince) takılır
      h('div', { class: `row-step ${asm.steps[asm.final.step] ? 'done' : 'todo'}` },
        h('div', { class: 'top', style: { display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' } },
          h('b', null, 'Birleştirme montajı'),
          asm.steps[asm.final.step] ? h('span', { class: 'badge green' }, 'Tamamlandı')
            : asm.final.ready ? h('button', { class: 'btn sm success', onclick: () => finalModal(order, asm, refresh) }, 'Birleştirme Montajı')
              : h('span', { class: 'badge gray' }, 'Bekliyor'))),
      asm.covers ? h('div', { class: 'row-step todo' },
        h('div', { class: 'top', style: { display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' } },
          h('b', null, 'Kapak montajı'),
          h('span', { class: 'badge gray' }, t('{ready}/{total} kapak depoda', { ready: asm.covers.ready, total: asm.covers.total }))),
        h('div', { class: 'small muted' }, 'Kapaklar en son, birleştirmeden sonra takılır')) : null));
  }

  function drawHead() {
    clear(head, orderHead(order, plane, ctx));
    const counts = Object.fromEntries(Object.keys(PART_STATES).map(k => [k, 0]));
    order.parts.forEach(p => { counts[p.state]++; });
    const pending = order.parts.filter(p => p.state === 'DEPO' && !p.approved_at).length;
    clear(stats,
      h('li', null, h('span', null, 'İlerleme'), h('span', { style: { width: '150px' } }, progressBar(order.progress))),
      Object.entries(PART_STATES).map(([k, s]) => h('li', null,
        h('span', { class: 'legend' }, h('span', null, h('i', { style: { background: s.color } }), s.label)),
        h('b', null, counts[k]))),
      pending ? h('li', null, h('span', { class: 'muted' }, 'Depo onayı bekleyen'), h('b', null, pending)) : null,
      h('li', null, h('span', { class: 'muted' }, 'Toplam parça'), h('b', null, order.parts.length)),
      ...printStats(order),
      h('li', null, h('span', { class: 'muted' }, 'Başlama / Bitiş'), h('span', null, `${fmtDate(order.start_date)} – ${fmtDate(order.end_date)}`)));
  }

  async function refresh() {
    order = await api.get(`/api/orders/${id}`);
    if (!spare && ASSEMBLY_VIEW.includes(order.status)) return rerender();   // son parça onaylandı: montaj görünümüne geç
    byPart = new Map(order.parts.map(p => [p.part_id, p]));
    drawHead();
    drawSections();
    pl.update();
  }

  drawHead();
  drawSections();
  clear(view, head,
    h('div', { class: 'plane-layout' },
      h('div', { class: 'card plane-stage' }, layerToggle(pl, 'plane.layer', plane), pl.svg),
      h('div', { class: 'card card-pad' },
        h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Parça durumu'),
        spare ? h('div', { class: 'alert info' }, order.status === 'TAMAMLANDI'
          ? t('Bu baskı stoğa girdi: {n} adet {name}.', { n: order.per_print, name: order.product_name })
          : t('Yedek parça siparişi (tek baskı). Depo onaylayınca {n} adet {name} stoğa girer.', { n: order.per_print, name: order.product_name })) : null,
        stats,
        sectionsBox,
        h('p', { class: 'small muted', style: { marginBottom: 0 } }, (canOperate
          ? 'Parçaya tıklayarak üretime başlatın, tamamlayın veya hata bildirin.'
          : 'Parçaya tıklayarak işlem geçmişini görün.')
          + (spare ? '' : ' Bir bölümün (sol kanat, sağ kanat, orta gövde) tüm parçaları depoya girince o bölüm sarı çerçeveyle '
            + 'gösterilir ve diğer parçalar basılırken montajı yapılabilir.')))));
  every(15000, () => refresh().catch(() => {}));
}

const rerender = () => window.dispatchEvent(new HashChangeEvent('hashchange'));

// ---------- Baskı süresi ve yazıcıda bekleme (yazıcının "tamamlandı" dediği an → "Üretim Tamamlandı")
function waitLines(op) {
  if (!op?.printer_done_at) return [];
  if (op.state === 'URETIMDE') return [t('Yazıcıda bitti: {at}', { at: fmtDateTime(op.printer_done_at) }),
    h('span', { style: { color: 'var(--danger)' } }, t('Yazıcıda bekliyor: {d}', { d: fmtDuration(secondsSince(op.printer_done_at)) }))];
  return op.finished_at ? [t('Yazıcıda bekledi: {d}', { d: fmtDuration(secondsBetween(op.printer_done_at, op.finished_at)) })] : [];
}

// Parçaların baskı sürelerinin toplamı gösterilmez: yazıcılar paralel çalıştığı için gerçekte yaşanmayan bir süredir
function printStats(order) {
  const waits = order.parts.filter(op => op.printer_done_at && op.finished_at).map(op => secondsBetween(op.printer_done_at, op.finished_at));
  const waiting = order.parts.filter(op => op.state === 'URETIMDE' && op.printer_done_at).length;
  return [
    waits.length ? h('li', null, h('span', { class: 'muted' }, t('Yazıcıda ort. bekleme ({n} parça)', { n: waits.length })),
      h('b', null, fmtDuration(waits.reduce((a, x) => a + x, 0) / waits.length))) : null,
    waiting ? h('li', null, h('span', { style: { color: 'var(--danger)' } }, 'Yazıcıda bitmiş, teslim bekleyen'), h('b', null, waiting)) : null,
  ];
}

function printBlock(part, detail) {
  // Parça penceresi: yazıcıya verilecek dosya, beklenen süre, yazıcının bildirdiği başlangıç / bitiş ve bekleme
  const rows = [
    part.print_file ? ['Baskı dosyası', h('span', { class: 'mono' }, part.print_file)] : null,
    part.print_minutes ? ['Baskı süresi', fmtMinutes(part.print_minutes)] : null,
    detail?.printer_started_at ? ['Yazıcıda başladı', fmtDateTime(detail.printer_started_at)] : null,
    detail?.printer_done_at ? ['Yazıcıda bitti', `${fmtDateTime(detail.printer_done_at)}`
      + (detail.print_seconds != null ? t(' · net baskı {d}', { d: fmtDuration(detail.print_seconds) })
        : detail.printer_started_at ? t(' · gerçek baskı {d}', { d: fmtDuration(secondsBetween(detail.printer_started_at, detail.printer_done_at)) }) : '')] : null,
    detail?.printer_done_at && detail.finished_at ? ['Yazıcıda bekleme', h('b', null, fmtDuration(secondsBetween(detail.printer_done_at, detail.finished_at)))] : null,
    detail?.printer_done_at && detail.state === 'URETIMDE' ? ['Yazıcıda bekleme', h('b', { style: { color: 'var(--danger)' } },
      t('{d} (sürüyor)', { d: fmtDuration(secondsSince(detail.printer_done_at)) }))] : null,
  ].filter(Boolean);
  return rows.length ? h('dl', { class: 'kv print-kv' }, rows.map(([k, v]) => [h('dt', null, k), h('dd', null, v)])) : null;
}

function orderHead(order, plane, ctx) {
  // Üst satır: ← · firma logosu · sipariş no · durum; alt satır: diğer bilgiler
  return [pageHead(h('span', { class: 'order-title' }, order.company_name
    ? logoOf({ name: order.company_name, logo: order.company_logo }, 'co-logo md') : null, h('span', null, order.code),
  h('span', { class: 'order-title-badge' }, orderBadge(order))), {
    back: '#/production',
    sub: h('span', { class: 'order-sub' },
      order.company_name ? h('b', { title: order.company_name }, `${shortCompany(order.company_name)} · `) : null,
      `${order.product_name} (${order.product_serial}) · `,
      order.queue_no ? [queuePlate(order.queue_no), ' · '] : null,
      t('Siparişi veren: {name}', { name: order.created_by_name || '—' }),
      order.note ? h('span', { class: 'muted' }, ` · ${order.note}`) : null,
      order.field_task ? h('a', { href: `#/field/task/${order.field_task.id}`, style: { marginLeft: '6px' } }, t(' · Saha görevi {code}', { code: order.field_task.code })) : null),
  }),
  moduleToolbar(h('button', { class: 'btn lg', onclick: () => printWipReport(order, plane, ctx.meta.company) }, 'Yarı Mamul Raporu'))];
}

// ---------- Montaj → kalibrasyon → saha deposu ----------
const staffNames = step => step.staff.map(s => s.full_name).join(', ');

async function renderAssemblyOrder(view, order, plane, ctx) {
  const asm = order.assembly;
  const steps = asm.steps;
  const whole = !IN_ASSEMBLY.includes(order.status);
  const finalDone = !!steps[asm.final.step];
  const coverTodo = !!asm.covers && finalDone && !steps[asm.covers.step];   // birleştirme bitti, kapaklar takılacak
  const items = {};
  if (!whole) {
    for (const [key, name] of Object.entries(asm.sections)) {
      const st = steps[key];
      items[key] = coverTodo && key === 'GOVDE'
        ? { state: 'todo', label: [name, { text: 'Kapak montajı bekliyor', class: 'sub' }, { text: 'Tıklayın', class: 'muted' }] }
        : st
        ? { state: 'done', label: [name, { text: 'Montaj tamamlandı', class: 'sub' }, { text: fmtDateTime(st.at), class: 'muted' }] }
        : { state: 'todo', label: [name, { text: 'Montaj bekliyor', class: 'sub' }, { text: 'Tıklayın', class: 'muted' }] };
    }
    if (asm.electronics.length) {   // dördüncü yapı: elektronik (her parçaya ayrı elektronik montajı)
      const done = asm.electronics.filter(e => steps[e.step]).length;
      items.ELEKTRONIK = done === asm.electronics.length
        ? { state: 'done', label: ['Elektronik', { text: 'Montaj tamamlandı', class: 'sub' }] }
        : { state: 'todo', label: ['Elektronik', { text: t('Montaj {done}/{total}', { done, total: asm.electronics.length }), class: 'sub' }, { text: 'Parçaya tıklayın', class: 'muted' }] };
    }
  } else if (order.status === 'KALIBRASYON') {
    items.ALL = { state: 'todo', label: [order.code, { text: 'Kalibrasyon bekliyor', class: 'sub' }, { text: 'Tıklayın', class: 'muted' }] };
  } else if (order.status === 'SAHA_ONAY') {
    items.ALL = { state: 'done', label: [order.code, { text: 'Kalibrasyon tamamlandı', class: 'sub' }, { text: 'Saha deposu onayı bekliyor', class: 'muted' }] };
  } else {
    items.ALL = { state: 'done', label: [order.queue_no || order.code, { text: 'Saha deposunda', class: 'sub' }, { text: order.code, class: 'muted' }] };
  }
  const refresh = rerender;
  const canOperate = ctx.user.roles.some(r => PART_OPERATORS.includes(r));
  const opOf = part => order.parts.find(p => p.part_id === part.id);
  const pl = renderAssembly(plane, {
    whole, items,
    // Elektronik kat ve K04 yalnızca montaj bölümlerinde ayrı çizilir; tek parça uçakta (kalibrasyon ve sonrası) görünmez
    extra: asm.electronics.length && !whole ? {
      fill: part => PART_STATES[opOf(part)?.state]?.color || 'var(--part-fill)',
      // Elektronik kat kutusuna durum yazılır; küçük K04 kapağında yalnızca kodu
      label: part => (part.name ? [...part.name.split(' '), { text: ekShortText(opOf(part)), class: 'sub' }] : [part.id]),
      clickable: () => true,
      onClick: part => clickPart(order, opOf(part), part, refresh, canOperate),
    } : null,
    onClick: key => {
      if (!whole && !steps[key]) return sectionModal(order, key, asm.sections[key], refresh);
      if (!whole && asm.final.ready && !finalDone) return finalModal(order, asm, refresh);   // bölümler hazır: birleştir
      if (!whole && coverTodo) return coverModal(order, refresh);                             // en son kapaklar
      if (order.status === 'KALIBRASYON') return calibrationModal(order, asm, refresh);
      return stepInfo(order, asm, whole ? null : key);
    },
  });

  const rows = [
    ...Object.entries(asm.sections).map(([k, name]) => [k, t('{name} montajı', { name })]),
    ...asm.electronics.map(e => [e.step, t('Elektronik montajı: {name}', { name: e.name })]),
    [asm.final.step, 'Birleştirme montajı'],
    // kapak adımı öncesi montajı bitmiş eski siparişlerde kapak satırı gösterilmez
    ...(asm.covers && (!whole || steps[asm.covers.step]) ? [[asm.covers.step, 'Kapak montajı']] : []),
    ['KALIBRASYON', 'Kalibrasyon'], ['SAHA_DEPO', 'Saha deposu onayı'],
  ];
  const summary = h('div', { class: 'asm-summary' }, rows.map(([k, title]) => {
    const st = steps[k];
    return h('div', { class: `row-step ${st ? 'done' : 'todo'}` },
      h('div', { class: 'top', style: { display: 'flex', justifyContent: 'space-between', gap: '8px' } },
        h('b', null, title), st ? h('span', { class: 'badge green' }, 'Tamamlandı') : h('span', { class: 'badge yellow' }, 'Bekliyor')),
      st ? h('div', { class: 'small muted' }, [fmtDateTime(st.at), st.staff.length ? staffNames(st) : st.recorded_by_name].filter(Boolean).join(' · ')) : null);
  }));
  const hint = {
    MONTAJ: coverTodo
      ? 'Birleştirme tamamlandı. Kapakları takıp "Kapak Montajı" ile onaylayın; uçak kalibrasyona geçer.'
      : asm.final.ready
      ? t('Bölümler ve elektronik montajlar tamamlandı. Kanatları ve elektronik parçaları gövdeye takıp "Birleştirme Montajı" ile onaylayın{tail}.', { tail: asm.covers ? t('; ardından kapaklar takılır') : t('; uçak kalibrasyona geçer') })
      : Object.keys(asm.sections).every(k => steps[k])
        ? 'Montaj bölümleri tamamlandı. Elektronik montajlar (elektronik kat ve K04) bitince birleştirme montajı yapılabilir.'
        : 'Sarı çerçeveli bölüme tıklayıp montajı tamamlayın. Üç bölüm ve elektronik yapının montajları bitince birleştirme montajı yapılır, ardından kalibrasyon.',
    KALIBRASYON: 'Uçağa tıklayıp kalibrasyon kontrol listesini doldurun.',
    SAHA_ONAY: 'Kalibrasyon tamamlandı. Uçak, depocu onayladığında saha deposuna girer ve sahaya gönderilebilir.',
    TAMAMLANDI: 'Uçak saha deposunda; saha görevlerinde seçilebilir.',
  }[order.status === 'SAHADA_MONTAJ' ? 'MONTAJ' : order.status];
  clear(view, orderHead(order, plane, ctx),
    h('div', { class: 'plane-layout' },
      h('div', { class: 'card plane-stage' }, pl.svg),
      h('div', { class: 'card card-pad' },
        h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Montaj durumu'),
        summary,
        IN_ASSEMBLY.includes(order.status) && asm.final.ready && !finalDone
          ? h('button', { class: 'btn success lg', style: { width: '100%', marginTop: '12px' }, onclick: () => finalModal(order, asm, refresh) },
            'Birleştirme Montajı')
          : IN_ASSEMBLY.includes(order.status) && coverTodo
            ? h('button', { class: 'btn success lg', style: { width: '100%', marginTop: '12px' }, onclick: () => coverModal(order, refresh) },
              'Kapak Montajı')
            : null,
        h('p', { class: 'small muted', style: { marginBottom: 0 } }, hint))));
  // Başka ekrandan yapılan adımlar görünsün
  every(15000, async () => {
    const fresh = await api.get(`/api/orders/${order.id}`).catch(() => null);
    if (fresh && (fresh.status !== order.status || Object.keys(fresh.assembly.steps).length !== Object.keys(steps).length)) rerender();
  });
}

const assemblers = () => api.get(`/api/people?role=${encodeURIComponent('Montaj Personeli')}`);

// ---------- Elektronik kat ----------
const AFTER_ASSEMBLY = ['KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI'];
function ekStateText(op) {
  if (op.state === 'DEPO') return op.approved_at ? 'Elektronik montajı bekliyor' : 'Depo onayı bekliyor';
  if (op.state === 'MONTAJ') return 'Elektronik monte edildi';
  return PART_STATES[op.state]?.label || '';
}

const ekShortText = op => (op.state === 'DEPO' ? (op.approved_at ? 'Montaj bekliyor' : 'Depo onayı')
  : op.state === 'MONTAJ' ? 'Monte edildi' : PART_STATES[op.state]?.label || '');

// Parçaya tıklama: depodaki (onaylı) elektronik kat → elektronik montajı; diğerleri → parça işlemi / geçmiş
function clickPart(order, op, part, refresh, canOperate) {
  if (part.layer === 'electronics' && op.state === 'DEPO' && op.approved_at && !AFTER_ASSEMBLY.includes(order.status)) {
    return electronicsModal(order, part.id, refresh);
  }
  return canOperate ? partAction(order, op, part, refresh) : showHistory(order, op, part);
}

async function electronicsModal(order, partId, refresh) {
  const people = await api.get(`/api/people?role=${encodeURIComponent('Elektronik Personeli')}`);
  const picker = peoplePicker(people, { empty: 'Elektronik Personeli rolünde kullanıcı yok. Kullanıcı Yönetimi\'nden rol verin.' });
  const min = order.assembly.min_electronics_staff;
  const info = order.assembly.electronics.find(e => e.part_id === partId);
  const when = dateTimeInput({ min: info?.approved_at });
  modal({
    title: `${order.code} — ${info?.name || partId}`,
    body: h('div', null,
      h('p', { style: { marginTop: 0 } }, h('b', null, 'Elektronik komponentler monte edildi mi?')),
      field(t('Montajı yapan elektronik personeli (en az {min})', { min }), picker),
      field('Montaj zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Monte Edildi', class: 'success', onClick: async () => {
          const ids = picker.getIds();
          if (ids.length < min) throw new Error(t('En az {min} elektronik personeli seçin', { min }));
          const r = await api.post(`/api/orders/${order.id}/electronics/${encodeURIComponent(partId)}`, { staff_ids: ids, at: when.getValue() });
          if (r.status === 'KALIBRASYON') queueNoticeModal(order, r.queue_no);
          else toast(t('{name}: elektronik montaj tamamlandı', { name: info?.name || partId }));
          await refresh();
        },
      },
    ],
  });
}

async function sectionModal(order, key, name, refresh, { url = `/api/orders/${order.id}/assembly/${key}`, min = order.assembly.min_staff } = {}) {
  const people = await assemblers();
  const picker = peoplePicker(people, { empty: 'Montaj Personeli rolünde kullanıcı yok. Kullanıcı Yönetimi\'nden rol verin.' });
  const when = dateTimeInput();
  modal({
    title: `${order.code} — ${name}`,
    body: h('div', null,
      h('p', { style: { marginTop: 0 } }, h('b', null, t('{name} montajı tamamlandı mı?', { name }))),
      field(t('Montajda çalışan personel (en az {min})', { min }), picker),
      field('Tamamlanma zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Tamamlandı', class: 'success', onClick: async () => {
          const ids = picker.getIds();
          if (ids.length < min) throw new Error(t('En az {min} montaj personeli seçin', { min }));
          const r = await api.post(url, { staff_ids: ids, at: when.getValue() });
          if (r.status === 'KALIBRASYON') queueNoticeModal(order, r.queue_no);
          else toast(t('{name} montajı tamamlandı', { name }));
          refresh();
        },
      },
    ],
  });
}

// Kapak montajı: kapaklar en son, birleştirmeden sonra takılır
const coverModal = (order, refresh) => sectionModal(order, 'KAPAK', 'Kapak', refresh,
  { url: `/api/orders/${order.id}/covers`, min: order.assembly.covers.min_staff });

// Kontrol listeli, montaj personelli adım penceresi (birleştirme montajı ve kalibrasyon)
async function checklistModal({ title, checks, minStaff, submit, done }) {
  const people = await assemblers();
  const picker = peoplePicker(people, { empty: 'Montaj Personeli rolünde kullanıcı yok.' });
  const when = dateTimeInput();
  const rows = Object.entries(checks).map(([k, q], i) => {
    const cb = h('input', { type: 'checkbox' });
    const label = h('label', null, cb, h('span', null, `${i + 1}. ${q}`));
    cb.addEventListener('change', () => label.classList.toggle('on', cb.checked));
    return [k, cb, label];
  });
  modal({
    title,
    body: h('div', null,
      h('div', { class: 'checklist' }, rows.map(c => c[2])),
      field(t('Çalışan montaj personeli (en az {min})', { min: minStaff }), picker),
      field('Tamamlanma zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Tamamlandı', class: 'success', onClick: async () => {
          if (rows.some(c => !c[1].checked)) throw new Error('Tamamlamak için tüm maddeler işaretlenmeli');
          const ids = picker.getIds();
          if (ids.length < minStaff) throw new Error(t('En az {min} montaj personeli seçin', { min: minStaff }));
          await submit({ staff_ids: ids, at: when.getValue(), checklist: Object.fromEntries(rows.map(c => [c[0], c[1].checked])) });
          done();
        },
      },
    ],
  });
}

// Montaj bitti, uçak kalibrasyona geçti: kuyruk numarası (metal etikete yazılır) büyük gösterilir
function queueNoticeModal(order, queueNo) {
  if (!queueNo) { toast('Montaj tamamlandı, uçak kalibrasyona geçti'); return; }
  modal({
    title: t('{code} — Montaj tamamlandı', { code: order.code }),
    body: h('div', { class: 'queue-notice' },
      h('p', null, 'Uçak kalibrasyona geçti ve kuyruk numarası atandı. Bu numarayı metal etikete yazıp uçağa takın:'),
      h('div', { style: { margin: '10px 0 14px' } }, queuePlate(queueNo, 'lg')),
      h('p', { class: 'small muted' }, 'Kuyruk numarası bir kez atanır, değişmez; sipariş detayında ve saha görevlerinde bu numarayla görünür.')),
    actions: [{ label: 'Tamam', class: 'primary' }],
  });
}

function finalModal(order, asm, refresh) {
  return checklistModal({
    title: t('{code} — Birleştirme montajı', { code: order.code }), checks: asm.final.checks, minStaff: asm.min_staff,
    submit: async body => {
      const r = await api.post(`/api/orders/${order.id}/final`, body);
      if (r.status === 'KALIBRASYON') queueNoticeModal(order, r.queue_no);
      return r;
    },
    done: () => { toast('Birleştirme montajı tamamlandı'); refresh(); },
  });
}

async function calibrationModal(order, asm, refresh) {
  const people = await assemblers();
  const picker = peoplePicker(people, { empty: 'Montaj Personeli rolünde kullanıcı yok.' });
  const when = dateTimeInput();
  const checks = Object.entries(asm.checks).map(([k, q], i) => {
    const cb = h('input', { type: 'checkbox' });
    const label = h('label', null, cb, h('span', null, `${i + 1}. ${q}`));
    cb.addEventListener('change', () => label.classList.toggle('on', cb.checked));
    return [k, cb, label];
  });
  modal({
    title: t('{code} — Kalibrasyon', { code: order.code }),
    body: h('div', null,
      h('div', { class: 'checklist' }, checks.map(c => c[2])),
      field(t('Çalışan montaj personeli (en az {min})', { min: asm.min_staff }), picker),
      field('Tamamlanma zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Tamamlandı', class: 'success', onClick: async () => {
          if (checks.some(c => !c[1].checked)) throw new Error('Tamamlamak için tüm maddeler işaretlenmeli');
          const ids = picker.getIds();
          if (ids.length < asm.min_staff) throw new Error(t('En az {min} montaj personeli seçin', { min: asm.min_staff }));
          await api.post(`/api/orders/${order.id}/calibration`, {
            staff_ids: ids, at: when.getValue(), checklist: Object.fromEntries(checks.map(c => [c[0], c[1].checked])),
          });
          toast('Kalibrasyon tamamlandı; uçak saha deposu onayına gönderildi');
          refresh();
        },
      },
    ],
  });
}

function stepInfo(order, asm, key) {
  const keys = key ? [key] : [...Object.keys(asm.sections), ...asm.electronics.map(e => e.step), asm.final.step, 'KAPAK', 'KALIBRASYON', 'SAHA_DEPO'];
  const title = k => asm.sections[k] ? t('{name} montajı', { name: asm.sections[k] })
    : asm.electronics.find(e => e.step === k) ? t('Elektronik montajı: {name}', { name: asm.electronics.find(e => e.step === k).name })
      : { BIRLESTIRME: 'Birleştirme montajı', KAPAK: 'Kapak montajı', KALIBRASYON: 'Kalibrasyon', SAHA_DEPO: 'Saha deposu onayı' }[k];
  modal({
    title: key ? `${order.code} — ${asm.sections[key]}` : t('{code} — Montaj geçmişi', { code: order.queue_no || order.code }),
    body: h('ul', { class: 'timeline' }, keys.filter(k => asm.steps[k]).map(k => {
      const st = asm.steps[k];
      return h('li', null, h('b', null, title(k)),
        h('div', { class: 'when' }, [fmtDateTime(st.at), t('kaydeden: {name}', { name: st.recorded_by_name || '—' })].join(' · ')),
        st.staff.length ? h('div', { class: 'small' }, t('Personel: {names}', { names: staffNames(st) })) : null,
        st.checklist ? h('div', { class: 'small' }, Object.entries(k === asm.final.step ? asm.final.checks : asm.checks)
          .map(([c, q]) => `${st.checklist[c] ? '✓' : '✗'} ${q}`).join(' · ')) : null);
    })),
    actions: [{ label: 'Kapat', class: 'primary' }],
  });
}

// ---------- Parça işlemleri ----------
async function partAction(order, op, part, refresh) {
  if (order.status === 'TAMAMLANDI') return showHistory(order, op, part);
  if (op.state === 'BEKLIYOR' || op.state === 'HATA') {
    const d = await api.get(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}`).catch(() => null);
    if (d?.direct_request?.status === 'BEKLIYOR') return directReview(order, op, part, d, refresh);
    return choosePrinter(order, op, part, refresh);
  }
  if (op.state === 'URETIMDE') return inProduction(order, op, part, refresh);
  return showHistory(order, op, part, refresh, true);
}

async function choosePrinter(order, op, part, refresh) {
  const [printers, detail] = await Promise.all([api.get('/api/printers'), api.get(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}`)]);
  let selected = null;
  const lastError = [...detail.events].reverse().find(e => e.event === 'HATA');
  const list = h('div', { class: 'pick-list' });
  // Pencere açıkken yazıcı durumları 5 sn'de bir yenilenir: başka ekrandan boşaltılan yazıcı hemen seçilebilir olur
  const draw = printers => {
    if (selected && !printers.some(p => p.id === selected && !p.current_part_id)) selected = null;
    clear(list, printers.length ? printers.map(p => {
      const busy = !!p.current_part_id;
      const el = h('div', { class: `pick ${busy ? 'disabled' : ''} ${p.id === selected ? 'on' : ''}` },
        h('input', { type: 'radio', name: 'printer', disabled: busy, checked: p.id === selected }),
        h('div', { class: 'grow' }, h('b', null, p.name),
          h('span', { class: 'small muted' }, busy ? t('Meşgul: {order} / {part}', { order: p.current_order, part: p.current_part }) : p.ip)),
        p.live_state ? badge(PRINTER_STATES, p.live_state) : null);
      if (!busy) {
        el.addEventListener('click', () => {
          selected = p.id;
          list.querySelectorAll('.pick').forEach(x => x.classList.remove('on'));
          el.classList.add('on');
          el.querySelector('input').checked = true;
        });
      }
      return el;
    }) : h('div', { class: 'empty' }, 'Kayıtlı yazıcı yok. Yazıcı Yönetimi modülünden ekleyin.'));
  };
  draw(printers);
  const when = dateTimeInput();
  const poll = setInterval(async () => {
    try { draw(await api.get('/api/printers')); } catch { /* geçici ağ hatası: sonraki denemede */ }
  }, 5000);

  modal({
    title: t('{id} — Yazıcı seçin', { id: part.id }),
    onClose: () => clearInterval(poll),
    body: h('div', null,
      lastError ? h('div', { class: 'alert err' },
        h('b', null, t('Önceki hata: {code}', { code: lastError.error_code })), lastError.note ? ` — ${lastError.note}` : '',
        h('div', { class: 'small' }, `${fmtDateTime(lastError.at)} · ${lastError.user_name || ''}`)) : null,
      part.print_file ? h('div', { class: 'alert info' }, 'Yazıcıya verilecek dosya: ', h('b', { class: 'mono' }, part.print_file),
        part.print_minutes ? t(' · baskı süresi {d}', { d: fmtMinutes(part.print_minutes) }) : '') : null,
      h('p', { class: 'muted', style: { marginTop: 0 } }, 'Seçtiğiniz yazıcıda, seçtiğiniz zamandan itibaren üretimde görünecek.'),
      list,
      field('Üretime başlama zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Doğrudan Depoya Ekle', onClick: async () => {
          if (!selected) throw new Error('Önce yazıcıyı seçin');
          await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/direct-request`, { printer_id: selected, at: when.getValue() });
          toast('Doğrudan depo ekleme talebi Sistem Yöneticisi onayına gönderildi');
          await refresh();
        },
      },
      {
        label: 'Yazıcıya Gönder', onClick: async () => {
          if (!selected) throw new Error('Bir yazıcı seçin');
          await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/send-to-printer`, { printer_id: selected, at: when.getValue() });
          sendProgress(order, op, part, refresh);   // yükleme ilerleme ekranı
        },
      },
      {
        label: 'Üretime Al', class: 'primary', onClick: async () => {
          if (!selected) throw new Error('Bir yazıcı seçin');
          await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/start`, { printer_id: selected, at: when.getValue() });
          toast(t('{id} üretime alındı', { id: part.id }));
          await refresh();
        },
      },
    ],
  });
}

// Doğrudan depo ekleme talebi onay bekliyor: Sistem Yöneticisi onaylar/reddeder; diğerleri durumu görür
function directReview(order, op, part, detail, refresh) {
  const d = detail.direct_request;
  const admin = detail.can_approve_direct;
  const note = h('textarea', { class: 'input', rows: 2, placeholder: admin ? 'Not (isteğe bağlı; redde sebep)' : '' });
  const act = async (kind) => {
    await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/direct-${kind}`, { note: note.value });
    toast(kind === 'approve' ? 'Onaylandı; parça depo onayına düştü' : 'Talep reddedildi');
    await refresh();
  };
  modal({
    title: t('{id} — Doğrudan depo ekleme', { id: part.id }),
    body: h('div', null,
      h('div', { class: 'alert info' }, h('b', null, 'Basılmış kabul edilip doğrudan depoya eklenecek.'),
        h('div', { class: 'small', style: { marginTop: '4px' } },
          t('Yazıcı: {printer} · Talep: {at} · {by}', { printer: d.printer_name || '—', at: fmtDateTime(d.requested_at), by: d.requested_by_name || '' }))),
      admin ? h('p', { class: 'muted', style: { marginBottom: 0 } }, 'Onaylarsanız parça, seçili yazıcıdan çıkmış gibi depo onayına gider.')
        : h('p', { class: 'muted', style: { marginBottom: 0 } }, 'Sistem Yöneticisi onayı bekleniyor.'),
      admin ? field('Not', note) : null),
    actions: admin ? [
      { label: 'Kapat' },
      { label: 'Reddet', class: 'danger', onClick: () => act('reject') },
      { label: 'Onayla', class: 'primary', onClick: () => act('approve') },
    ] : [{ label: 'Kapat' }],
  });
}

// Yazıcıya G-code yükleme ilerlemesi: sunucu → yazıcı yükleme arka planda; bu ekran ilerlemeyi saniyede birkaç kez okur
function sendProgress(order, op, part, refresh) {
  const bar = h('i');
  const track = h('div', { class: 'print-progress' }, h('div', { class: 'track' }, bar));
  const label = h('div', { class: 'small muted', style: { textAlign: 'center' } }, 'Bağlanıyor…');
  const stage = h('div', { class: 'send3d g3d-view' }, h('div', { class: 'loading' }, '3B hazırlanıyor…'));
  const box = h('div', null, stage,
    h('p', { class: 'small muted', style: { textAlign: 'center', margin: '8px 0 6px' } }, t('{id} · {file} yazıcıya gönderiliyor', { id: part.id, file: part.print_file || 'G-code' })),
    track, label);
  let closed = false, done = false, v3 = null;
  // Yazıcının 3B hali ve parçanın yazıcı içinde dolan 3B görünümü
  if (part.gcode_preview) {
    partInPrinter(stage, part.gcode_preview, { progress: 0 }).then(v => { v3 = v; if (closed) v.destroy(); })
      .catch(() => clear(stage, h('div', { class: 'empty small' }, '3B görünüm yüklenemedi')));
  } else { clear(stage, h('div', { class: 'empty small' }, 'Bu parçanın 3B önizlemesi yok')); }
  const m = modal({
    title: t('{id} — Yazıcıya gönderiliyor', { id: part.id }),
    body: box,
    onClose: () => { closed = true; v3?.destroy(); if (done) refresh(); },
    actions: [{ label: 'Arka planda sürdür' }],
  });
  const mb = v => `${(v / 1048576).toFixed(1)} MB`;
  const poll = async () => {
    if (closed) return;
    let st;
    try { st = await api.get(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/send-progress`); } catch { setTimeout(poll, 1000); return; }
    if (st.status === 'uploading') {
      bar.style.width = `${st.percent}%`;
      v3?.setProgress(st.percent / 100);   // parça yükleme yüzdesi kadar dolar
      label.textContent = t('Yükleniyor… %{percent} ({sent} / {total}) · {printer}', { percent: Math.floor(st.percent), sent: mb(st.sent), total: mb(st.total), printer: st.printer });
    } else if (st.status === 'starting') {
      bar.style.width = '100%'; v3?.done();
      label.textContent = 'Yükleme bitti, baskı başlatılıyor…';
    } else if (st.status === 'done') {
      done = true;
      bar.style.width = '100%'; bar.classList.add('ok'); v3?.done();
      label.textContent = t('Gönderildi. {id} {printer} yazıcısında üretime alındı.', { id: part.id, printer: st.printer });
      toast(t('{id} yazıcıya gönderildi, baskı başladı', { id: part.id }));
      setTimeout(() => { if (!closed) m.close(); refresh(); }, 1600);
      return;
    } else if (st.status === 'error') {
      bar.classList.add('err');
      clear(box, h('div', { class: 'alert err' }, h('b', null, 'Gönderilemedi'), h('div', { class: 'small' }, st.error || '')),
        h('p', { class: 'small muted' }, 'Parça üretime alınmadı. Yazıcıyı ve bağlantıyı kontrol edip tekrar deneyin.'));
      v3?.destroy(); v3 = null;
      return;
    } else {
      label.textContent = 'Hazırlanıyor…';
    }
    setTimeout(poll, 700);
  };
  poll();
}

// Bu parçanın yazdırma süresi: yazıcının bildirdiği net baskı süresi (duraklamalar hariç; yalnızca basarken ilerler).
// Yazıcı süre bildirmiyorsa yazıcıda başladığı andan (bittiyse bitişine kadar), o da yoksa üretime alındığı andan.
function printSeconds(detail, loadedAt) {
  const live = detail.printer_live;
  const printing = live?.state === 'YAZDIRIYOR';
  if (detail.print_seconds != null) {
    return { value: () => detail.print_seconds + (printing ? (Date.now() - loadedAt) / 1000 : 0), exact: true };
  }
  if (detail.printer_started_at) {
    return { value: () => (detail.printer_done_at ? secondsBetween(detail.printer_started_at, detail.printer_done_at) : secondsSince(detail.printer_started_at)) };
  }
  return { value: () => secondsSince(detail.started_at) };
}

async function inProduction(order, op, part, refresh) {
  const url = `/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}`;
  let detail = await api.get(url);
  let secs = printSeconds(detail, Date.now());
  const live = detail.printer_live;
  const clock = h('div', { class: 'big-clock' }, fmtDuration(secs.value()));
  // İnce ilerleme çubuğu: yazıcının bildirdiği yüzde; yoksa net baskı süresi / beklenen baskı süresi
  const fill = h('i');
  const pct = h('span');
  const bar = h('div', { class: 'print-progress' }, h('div', { class: 'track' }, fill), pct);
  // Yazıcının 3B hali ve parçanın yazıcı içinde, baskı yüzdesi kadar dolan 3B görünümü
  const stage = h('div', { class: 'send3d g3d-view' }, h('div', { class: 'loading' }, '3B hazırlanıyor…'));
  let v3 = null, v3closed = false;
  if (part.gcode_preview) {
    partInPrinter(stage, part.gcode_preview, { progress: 0 }).then(v => { v3 = v; if (v3closed) v.destroy(); else drawBar(); })
      .catch(() => clear(stage, h('div', { class: 'empty small' }, '3B görünüm yüklenemedi')));
  } else { clear(stage, h('div', { class: 'empty small' }, 'Bu parçanın 3B önizlemesi yok')); }
  const drawBar = () => {
    const lv = detail.printer_live;
    let v = lv?.state === 'TAMAMLANDI' || detail.printer_done_at ? 100 : lv?.progress != null && lv.progress > 0 ? lv.progress : null;
    if (v == null && part.print_minutes) v = Math.min(99, (secs.value() / 60 / part.print_minutes) * 100);
    bar.hidden = v == null;
    fill.style.width = `${Math.max(0, Math.min(100, v || 0))}%`;
    fill.classList.toggle('paused', lv?.state === 'DURAKLADI');
    pct.textContent = v == null ? '' : `%${Math.floor(v)}`;
    if (v != null) (lv?.state === 'TAMAMLANDI' || detail.printer_done_at) ? v3?.done() : v3?.setProgress(v / 100);
  };
  drawBar();
  const tick = setInterval(() => { clock.textContent = fmtDuration(secs.value()); drawBar(); }, 1000);
  const poll = setInterval(async () => {   // yazıcıdan gelen yüzde ve süre tazelenir
    const fresh = await api.get(url).catch(() => null);
    if (fresh) { detail = fresh; secs = printSeconds(detail, Date.now()); }
  }, 15000);
  const stateText = { YAZDIRIYOR: 'Basıyor', DURAKLADI: 'Duraklatıldı', TAMAMLANDI: 'Baskı bitti', HAZIR: 'Boşta', HATA: 'Hata', CEVRIMDISI: 'Çevrimdışı' };
  modal({
    title: t('{id} — Üretimde', { id: part.id }),
    onClose: () => { clearInterval(tick); clearInterval(poll); v3closed = true; v3?.destroy(); },
    body: h('div', null,
      stage,
      h('p', { class: 'muted', style: { textAlign: 'center', margin: '10px 0 0' } }, 'Yazdırma süresi'),
      clock,
      bar,
      h('p', { class: 'small muted', style: { textAlign: 'center', margin: '0 0 12px' } }, secs.exact
        ? 'Yazıcının bildirdiği net baskı süresi (duraklamalar hariç)'
        : detail.printer_started_at ? 'Yazıcıda baskının başladığı andan itibaren' : 'Yazıcı bilgisi yok; üretime alındığı andan itibaren'),
      h('dl', { class: 'kv' },
        h('dt', null, 'Yazıcı'), h('dd', null, detail.printer_name || '—'),
        live ? [h('dt', null, 'Yazıcı durumu'), h('dd', null,
          `${stateText[live.state] || live.state || '—'}${live.progress != null && live.state !== 'TAMAMLANDI' ? ` · %${Math.round(live.progress)}` : ''}`)] : null,
        h('dt', null, 'Üretime alındı'), h('dd', null, t('{at} · {ago} önce', { at: fmtDateTime(detail.started_at), ago: fmtDuration(secondsSince(detail.started_at)) })),
        h('dt', null, 'Sipariş'), h('dd', null, order.code)),
      printBlock(part, detail)),
    actions: [
      { label: 'Kapat' },
      'spacer',
      { label: 'Hata Verdi', class: 'danger', onClick: () => { reportError(order, op, part, refresh); } },
      { label: 'Üretim Tamamlandı', class: 'success', onClick: () => { deliver(order, op, part, refresh); } },
    ],
  });
}

async function deliver(order, op, part, refresh) {
  const keepers = await api.get(`/api/people?role=${encodeURIComponent('Depo Yöneticisi')}`);
  let selected = null;
  const list = h('div', { class: 'pick-list' }, keepers.length ? keepers.map(k => {
    const el = h('div', { class: 'pick' }, h('input', { type: 'radio', name: 'keeper' }),
      h('div', { class: 'grow' }, h('b', null, k.full_name), h('span', { class: 'small muted' }, k.username)));
    el.addEventListener('click', () => {
      selected = k.id;
      list.querySelectorAll('.pick').forEach(x => x.classList.remove('on'));
      el.classList.add('on');
      el.querySelector('input').checked = true;
    });
    return el;
  }) : h('div', { class: 'empty' }, 'Depo yöneticisi rolünde kullanıcı yok'));
  const when = dateTimeInput({ min: op.started_at });
  modal({
    title: t('{id} — Kime teslim ettiniz?', { id: part.id }),
    body: h('div', null, list, field('Teslim zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Depoya Teslim Et', class: 'success', onClick: async () => {
          if (!selected) throw new Error('Teslim alan depocuyu seçin');
          await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/finish`, { warehouse_user_id: selected, at: when.getValue() });
          toast(t('{id} depoya teslim edildi', { id: part.id }));
          await refresh();
        },
      },
    ],
  });
}

function reportError(order, op, part, refresh) {
  const code = h('input', { class: 'input', placeholder: 'Ör. E-101' });
  const desc = h('textarea', { class: 'input', rows: 3, placeholder: 'Hatanın açıklaması' });
  const photo = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
  const preview = h('img', { class: 'photo-preview', hidden: true, alt: 'Hata fotoğrafı' });
  photo.addEventListener('change', () => {
    const f = photo.files[0];
    preview.hidden = !f;
    if (f) preview.src = URL.createObjectURL(f);
  });
  const when = dateTimeInput({ min: op.started_at });
  modal({
    title: t('{id} — Hata bildir', { id: part.id }),
    body: h('div', null,
      field('Hata kodu', code),
      field('Açıklama', desc),
      field('Fotoğraf', h('div', null,
        h('button', { class: 'btn', type: 'button', onclick: () => photo.click() }, svgIcon(icons.camera), 'Fotoğraf Çek'),
        photo, preview)),
      field('Hata zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Hatayı Kaydet', class: 'danger', onClick: async () => {
          if (!code.value.trim()) throw new Error('Hata kodu zorunlu');
          const fd = new FormData();
          fd.append('error_code', code.value.trim());
          fd.append('description', desc.value.trim());
          if (photo.files[0]) fd.append('photo', photo.files[0]);
          if (when.getValue()) fd.append('at', when.getValue());
          await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/error`, fd);
          toast(t('{id} hata durumuna alındı', { id: part.id }), 'err');
          await refresh();
        },
      },
    ],
  });
}

async function showHistory(order, op, part, refresh, canOperate) {
  const detail = await api.get(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}`);
  // Montajda hatalı bulunan parça: depoda onaylı ya da montajdaki parça hataya atanıp yeniden üretime alınır
  const rejectable = canOperate && refresh && ['DEPO', 'MONTAJ'].includes(detail.state) && !AFTER_ASSEMBLY.includes(order.status);
  modal({
    title: t('{id} — İşlem geçmişi', { id: part.id }),
    wide: true,
    body: h('div', null,
      h('div', { style: { marginBottom: '14px' } }, badge(PART_STATES, detail.state),
        detail.state === 'DEPO' && !detail.approved_at ? h('span', { class: 'badge yellow', style: { marginLeft: '6px' } }, 'Depo onayı bekliyor') : null),
      printBlock(part, detail),
      timeline(detail.events)),
    actions: [
      ...(rejectable ? [{ label: 'Montajda Hatalı', class: 'danger', onClick: () => { reportAssemblyError(order, op, part, refresh); } }] : []),
      { label: 'Kapat', class: 'primary' }],
  });
}

function reportAssemblyError(order, op, part, refresh) {
  const code = h('input', { class: 'input', placeholder: 'Ör. M-101' });
  const desc = h('textarea', { class: 'input', rows: 3, placeholder: 'Montajda görülen hatanın açıklaması' });
  const photo = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
  const preview = h('img', { class: 'photo-preview', hidden: true, alt: 'Hata fotoğrafı' });
  photo.addEventListener('change', () => { const f = photo.files[0]; preview.hidden = !f; if (f) preview.src = URL.createObjectURL(f); });
  const when = dateTimeInput({});
  modal({
    title: t('{id} — Montajda hatalı parça', { id: part.id }),
    body: h('div', null,
      h('p', { class: 'muted' }, 'Parça hataya atanır ve yeniden üretime girer. Parçanın bölümü monte edildiyse bölüm montajı geri alınır; uçak montajdaysa sipariş üretime döner.'),
      field('Hata kodu', code),
      field('Açıklama', desc),
      field('Fotoğraf', h('div', null,
        h('button', { class: 'btn', type: 'button', onclick: () => photo.click() }, svgIcon(icons.camera), 'Fotoğraf Çek'),
        photo, preview)),
      field('Hata zamanı', when)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Hataya Al ve Yeniden Üret', class: 'danger', onClick: async () => {
          if (!code.value.trim()) throw new Error('Hata kodu zorunlu');
          const fd = new FormData();
          fd.append('error_code', code.value.trim());
          fd.append('description', desc.value.trim());
          if (photo.files[0]) fd.append('photo', photo.files[0]);
          if (when.getValue()) fd.append('at', when.getValue());
          const r = await api.post(`/api/orders/${order.id}/parts/${encodeURIComponent(op.part_id)}/assembly-error`, fd);
          toast(r.undone?.length ? t('{id} hataya alındı; geri alınan: {s}', { id: part.id, s: r.undone.join(', ') }) : t('{id} hataya alındı', { id: part.id }), 'err');
          await refresh();
        },
      },
    ],
  });
}

export function timeline(events) {
  if (!events.length) return h('div', { class: 'empty' }, 'Kayıt yok');
  return h('ul', { class: 'timeline' }, events.map(e => h('li', { class: e.event === 'HATA' ? 'err' : '' },
    h('b', null, e.text),
    h('div', { class: 'when' }, [fmtDateTime(e.at), e.user_name, e.printer_name].filter(Boolean).join(' · ')),
    e.target_name ? h('div', { class: 'small' }, t('Teslim alan: {name}', { name: e.target_name })) : null,
    e.error_code ? h('div', { class: 'small' }, t('Hata kodu: {code}{note}', { code: e.error_code, note: e.note ? ` — ${e.note}` : '' })) : null,
    e.photo ? h('a', { href: fileUrl(e.photo), target: '_blank' }, h('img', { src: fileUrl(e.photo, 512), alt: 'Hata fotoğrafı' })) : null)));
}
