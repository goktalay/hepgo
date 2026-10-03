// Sipariş Yönetimi: CAYMAZ üretim siparişi açma ve takip
import { api } from '../api.js';
import { icons } from '../icons.js';
import { printOrderForm } from '../print.js';
import { companyTag, subnav } from './production.js';
import { logoOf } from './companies.js';
import { ORDER_STATES, badge, orderBadge, queuePlate } from '../status.js';
import {
  clear, confirmDialog, field, fmtDate, fmtDateTime, fmtDuration, h, matches, modal, moduleToolbar, pageHead, pref, progressBar, secondsBetween, segmented,
  selectInput, setPref, shortCompany, statStrip, svgIcon, t, toast, toastError, periodFilter
} from '../ui.js';

export async function render(view, params, ctx) {
  if (/^\d+$/.test(params[0] || '')) return renderDetail(view, Number(params[0]), ctx);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Sipariş kodu, firma, kişi, kuyruk no ara…', style: { width: '240px' } });
  const status = selectInput(Object.entries(ORDER_STATES).map(([k, s]) => [k, s.label]), { all: 'Tüm durumlar' });
  const product = h('select', { class: 'input' });
  const period = periodFilter('orders', () => load(), { title: 'Açık siparişler her zaman; tamamlananlar seçilen dönemde açılan / biten' });
  const stats = statStrip();
  const body = h('div');
  let orders = [];
  let mode = pref('orders.view', 'list');
  const viewSeg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('orders.view', v); draw(); });

  const draw = () => {
    const list = orders.filter(o =>
      (!status.value || o.status === status.value) &&
      (!product.value || String(o.product_id) === product.value) &&
      matches(q.value, o.code, o.created_by_name, o.queue_no, o.note, o.product_name, o.product_serial, o.company_name));
    const open = list.filter(o => o.status !== 'TAMAMLANDI');
    const month = new Date().toISOString().slice(0, 7);
    stats.set([
      { label: 'Listelenen sipariş', value: list.length },
      { label: 'Açık sipariş', value: open.length },
      { label: 'Tamamlanan', value: list.length - open.length, tone: 'ok', sub: period.label().toLocaleLowerCase('tr') },
      { label: 'Bu ay açılan', value: list.filter(o => o.created_at.startsWith(month)).length },
      { label: 'Hatalı sipariş', value: list.filter(o => o.status === 'HATA').length, tone: list.some(o => o.status === 'HATA') ? 'alert' : '' },
      { label: 'Montaja hazır', value: list.filter(o => o.status === 'MONTAJ').length },
      { label: 'Ortalama ilerleme', value: open.length ? `%${Math.round(open.reduce((a, o) => a + o.progress, 0) / open.length)}` : '—', sub: 'açık siparişlerde' },
    ]);
    clear(body, !list.length ? h('div', { class: 'card empty' }, 'Filtreye uyan sipariş yok')
      : mode === 'card' ? h('div', { class: 'oc-grid' }, list.map(orderCard)) : table(list, load, ctx));
  };
  const load = async () => {
    const [o, products] = await Promise.all([api.get(`/api/orders?${period.qs()}`), api.get('/api/products')]);
    orders = o;
    if (!product.options.length) clear(product, h('option', { value: '' }, 'Tüm ürünler'), products.filter(p => p.orderable).map(p => h('option', { value: p.id }, `${p.name} (${p.serial})`)));   // yalnızca sipariş verilebilir ürünler
    draw();
  };
  [q, status, product].forEach(el => el.addEventListener(el === q ? 'input' : 'change', draw));

  clear(view,
    pageHead('İş Emri Yönetimi', { back: '#/production', sub: 'Üretim Yönetimi', tabs: subnav('is-emri', ctx) }),
    moduleToolbar(
      h('button', { class: 'btn primary', onclick: () => newOrder(load) }, svgIcon(icons.plus), 'Yeni İş Emri'), viewSeg),
    stats,
    h('div', { class: 'filters' }, q, status, product, period.el),
    body);
  await load();
}

// Sipariş kartı: kod ve durum, firma, ürün, kuyruk numarası (metal etiket), ilerleme ve tarihler; tıklanınca detay
function orderCard(o) {
  return h('a', { class: 'card oc-card', href: `#/orders/${o.id}` },
    h('div', { class: 'oc-top' }, h('b', null, o.code), orderBadge(o)),
    o.company_name ? companyTag(o, 'sm') : h('span', { class: 'small muted' }, 'Firma seçilmedi'),
    h('div', { class: 'oc-product' }, h('span', null, o.product_name), h('span', { class: 'mono muted' }, o.product_serial || '')),
    o.queue_no ? h('div', null, queuePlate(o.queue_no)) : null,
    h('div', { class: 'oc-prog' }, progressBar(o.progress)),
    h('dl', { class: 'oc-dl' },
      h('dt', null, 'Sipariş'), h('dd', null, fmtDate(o.created_at)),
      h('dt', null, 'Başlama'), h('dd', null, fmtDate(o.start_date)),
      h('dt', null, 'Bitiş'), h('dd', null, fmtDate(o.end_date))),
    o.note ? h('div', { class: 'small muted oc-note' }, o.note) : null);
}

function table(list, reload, ctx) {
  return h('div', { class: 'table-wrap' }, h('table', null,
    h('thead', null, h('tr', null,
      ['Sipariş', 'Ürün', 'Sipariş tarihi', 'Başlama', 'Bitiş', 'Durum', 'İlerleme', 'Kuyruk no', ''].map(t => h('th', null, t)))),
    h('tbody', null, list.map(o => h('tr', null,
      h('td', null, h('a', { href: `#/orders/${o.id}` }, h('b', null, o.code)),
        // kodun altında firma (logo + kısa ad); tıklanınca firma değiştirilir
        h('div', { class: 'order-co-line' }, h('button', { class: 'link-btn', title: 'Firmayı değiştir', onclick: () => changeCompany(o, reload) },
          companyTag(o, 'xs') || h('span', { class: 'small muted' }, 'Firma seçin')))),
      h('td', null, o.product_name, o.product_stocked
        ? h('div', { class: 'small muted' }, t('Parça baskısı · 1 baskı = {n} adet', { n: o.per_print }))
        : h('div', { class: 'small muted mono' }, o.product_serial)),
      h('td', { class: 'muted' }, fmtDateTime(o.created_at)),
      h('td', null, fmtDate(o.start_date)),
      h('td', null, fmtDate(o.end_date)),
      h('td', null, orderBadge(o)),
      h('td', { style: { minWidth: '160px' } }, progressBar(o.progress)),
      h('td', null, queuePlate(o.queue_no) || '—'),
      h('td', { class: 'num' },
        h('button', { class: 'btn sm', onclick: () => printOrderForm(o, ctx.meta.company) }, 'Formu Yazdır'),
        o.status === 'SIPARIS'
          ? h('button', { class: 'btn sm ghost', onclick: () => remove(o, reload) }, 'Sil') : null))))));
}

const companies = () => api.get('/api/orders/companies');
const companySelect = (list, value) => h('select', { class: 'input' },
  h('option', { value: '' }, 'Firma seçin…'),
  list.map(c => h('option', { value: c.id, selected: c.id === value }, c.name)));

async function changeCompany(o, reload) {
  const sel = companySelect(await companies(), o.company_id);
  modal({
    title: t('{code} — Firma', { code: o.code }),
    body: field('Firma', sel),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          await api.put(`/api/orders/${o.id}/company`, { company_id: sel.value ? Number(sel.value) : null });
          toast('Firma güncellendi');
          reload();
        },
      },
    ],
  });
}

async function remove(o, reload) {
  if (!await confirmDialog('Siparişi sil', t('{code} silinsin mi? Bu işlem geri alınamaz.', { code: o.code }), { okLabel: 'Sil', danger: true })) return;
  try {
    await api.del(`/api/orders/${o.id}`);
    toast('Sipariş silindi');
    reload();
  } catch (err) { toastError(err); }
}

async function newOrder(done) {
  const products = (await api.get('/api/products?active_only=true')).filter(p => p.orderable);   // ürün ayarı
  const company = companySelect(await companies(), null);
  const group = (label, list) => (list.length ? h('optgroup', { label }, list.map(p => h('option', { value: p.id },
    p.stocked ? t('{code} — {name} (1 baskı = {n} adet · stok {stock})', { code: p.code, name: p.name, n: p.per_print, stock: p.stock })
      : t('{name} — seri no {serial} ({n} parça)', { name: p.name, serial: p.serial, n: p.part_count })))) : null);
  const product = h('select', { class: 'input' },
    group('Mamul', products.filter(p => p.role === 'mamul')),
    group('Montaj sarfı', products.filter(p => p.role === 'sarf')),
    // Parça yedekleri: ait oldukları yarı mamule göre (Sol Kanat, Sağ Kanat, Gövde, Elektronik)
    [...new Set(products.filter(p => p.part_spare).sort((a, b) => (a.parent?.id || 0) - (b.parent?.id || 0))
      .map(p => p.parent?.name || '—'))].map(name =>
      group(t('Parça yedeği · {name}', { name }), products.filter(p => p.part_spare && (p.parent?.name || '—') === name))));
  const today = new Date().toISOString().slice(0, 10);
  // Her sipariş tek üretimdir: bir uçak ya da bir baskı (yedek parçada bir baskıdaki adet stoğa girer)
  const hint = h('div', { class: 'small muted', style: { marginTop: '-6px', marginBottom: '10px' } });
  const syncHint = () => {
    const p = products.find(x => String(x.id) === product.value);
    hint.textContent = p?.stocked
      ? t('Tek baskı: depo onayından sonra {n} adet {name} stoğa girer.', { n: p.per_print, name: p.name })
      : 'Sipariş tek uçaktır; birden fazla uçak için ayrı sipariş açın.';
  };
  product.addEventListener('change', syncHint);
  syncHint();
  const start = h('input', { class: 'input', type: 'date', value: today });
  const end = h('input', { class: 'input', type: 'date' });
  const note = h('textarea', { class: 'input', rows: 2, placeholder: 'İsteğe bağlı' });
  modal({
    title: 'Yeni Sipariş',
    body: h('div', null,
      field('Firma', company),
      field('Ürün', product), hint,
      h('div', { class: 'row' }, field('Başlama tarihi', start), field('Bitiş tarihi', end)),
      field('Not', note)),
    actions: [
      { label: 'Vazgeç' },
      {
        label: 'Sipariş Ver', class: 'primary', onClick: async () => {
          if (!company.value) throw new Error('Siparişin firmasını seçin');
          const created = await api.post('/api/orders', {
            company_id: Number(company.value),
            product_id: Number(product.value),
            start_date: start.value || null, end_date: end.value || null,
            note: note.value.trim() || null,
          });
          toast(t('{code} oluşturuldu', { code: created[0].code }));
          location.hash = `#/orders/${created[0].id}`;
          done();
        },
      },
    ],
  });
}

// ---------- Sipariş detayı: özet ve birbirine bağlı aşama kartları
const STAGE_STATE = { done: ['green', 'Tamamlandı'], current: ['blue', 'Sürüyor'], todo: ['gray', 'Bekliyor'] };

async function renderDetail(view, id, ctx) {
  const { order: o, stages } = await api.get(`/api/orders/${id}/timeline`);
  const canProd = ctx.user.modules.includes('production');
  const reload = () => renderDetail(view, id, ctx);
  const info = [
    ['Firma', o.company_name ? h('button', { class: 'link-btn', title: 'Firmayı değiştir', onclick: () => changeCompany(o, reload) }, companyTag(o, 'xs'))
      : h('button', { class: 'link-btn muted', onclick: () => changeCompany(o, reload) }, 'Firma seçin')],
    ['Ürün', `${o.product_name}${o.product_serial ? ` (${o.product_serial})` : ''}`],
    ['Siparişi veren', o.created_by_name || '—'],
    ['Sipariş tarihi', fmtDateTime(o.created_at)],
    ['Başlama / Bitiş', `${fmtDate(o.start_date)} – ${fmtDate(o.end_date)}`],
    o.queue_no ? ['Kuyruk no', queuePlate(o.queue_no, 'md')] : null,
    ['İlerleme', h('div', { style: { minWidth: '160px' } }, progressBar(o.progress))],
    o.note ? ['Açıklama', o.note] : null,
  ].filter(Boolean);
  const lastDone = [...stages].reverse().find(s => s.state === 'done');
  clear(view,
    pageHead(h('span', { class: 'order-title' }, o.company_name ? logoOf({ name: o.company_name, logo: o.company_logo }, 'co-logo md') : null, o.code), {
      back: '#/orders',
      sub: h('span', null, orderBadge(o), '  ', o.company_name ? h('b', { title: o.company_name }, `${shortCompany(o.company_name)} · `) : null,
        `${o.product_name}`, lastDone?.at ? t(' · son aşama {at}', { at: fmtDateTime(lastDone.at) }) : ''),
    }),
    moduleToolbar(
      h('button', { class: 'btn', onclick: () => printOrderForm(o, ctx.meta.company) }, 'Formu Yazdır'),
      canProd ? h('a', { class: 'btn primary', href: `#/production/${o.id}` }, 'Üretimde Aç') : null,
      o.status === 'SIPARIS' ? h('button', { class: 'btn ghost', onclick: () => remove(o, () => { location.hash = '#/orders'; }) }, 'Sil') : null),
    h('div', { class: 'od-layout' },
      h('div', { class: 'card card-pad od-info' }, h('h2', { class: 'od-h' }, 'Sipariş bilgileri'),
        h('dl', { class: 'kv' }, info.map(([k, v]) => [h('dt', null, k), h('dd', null, v)]))),
      h('div', { class: 'od-flow' }, stages.map((s, i) => stageCard(s, i, stages, o, canProd)))));
}

function stageCard(s, i, stages, o, canProd) {
  const [cls, label] = STAGE_STATE[s.state];
  const prev = stages[i - 1];
  const took = s.state === 'done' && s.at && prev?.at ? secondsBetween(prev.at, s.at) : null;
  return h('div', { class: `od-stage ${s.state}` },
    h('div', { class: 'od-node' }, h('span', null, s.state === 'done' ? '✓' : String(i + 1))),
    h('div', { class: 'card od-card' },
      h('div', { class: 'od-top' }, h('b', null, s.title), h('span', { class: `badge ${cls}` }, label)),
      s.at ? h('div', { class: 'small muted' }, fmtDateTime(s.at), s.by ? ` · ${s.by}` : '',
        took != null && took > 0 && i > 0 ? t(' · önceki aşamadan {d} sonra', { d: fmtDuration(took) }) : '') : null,
      s.lines.length ? h('ul', { class: 'od-lines' }, s.lines.map(l => h('li', null, l))) : null,
      s.key === 'MONTAJ' && s.steps.length ? h('div', { class: 'od-steps' }, s.steps.map(st => h('div', { class: `od-step ${st.done ? 'done' : ''}` },
        h('span', { class: 'od-dot' }, st.done ? '✓' : ''), h('span', { class: 'grow' }, st.title),
        h('span', { class: 'small muted' }, st.done ? `${fmtDateTime(st.at)}${st.by ? ` · ${st.by}` : ''}` : 'Bekliyor')))) : null,
      s.key === 'SAHA' && s.steps.length ? h('div', { class: 'od-links' }, s.steps.map(st =>
        h('a', { class: 'btn sm', href: `#/field/task/${st.task_id}` }, t('{title} görevi', { title: st.title })))) : null,
      s.key === 'UCUS' && s.steps.length ? h('div', { class: 'od-links' }, s.steps.map(f =>
        h('a', { class: 'btn sm primary', href: `#/field/flight/${f.flight_id}` }, t('Uçuş detayı ({title})', { title: f.title })))) : null,
            s.key === 'URETIM' && canProd && s.state !== 'todo' ? h('a', { class: 'btn sm', href: `#/production/${o.id}` }, 'Parçaları gör') : null));
}
