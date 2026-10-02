// Malzeme İhtiyaç Planlaması (MRP): Malzeme Yönetimi (yedek parça / hammadde), Yarı Mamül (eski Stok Yönetimi),
// Onay Yönetimi (eski Depo Yönetimi) ve Depo Yönetimi (depolar, sorumlular). Alt modül seçimi başlığın sağındaki
// açılır listededir. Malzeme ayrıntısı: üstte stok kodu, barkod, marka, model; altta Fiziksel Özellikler, Stok Hareketi,
// Depo, 3B, Resimler, Fatura İrsaliye, Hurda ve Kullanım, Kullanıldığı Ürünler.
import { setListExport } from '../listexport.js';
import { api, fileUrl, upload } from '../api.js';
import { gcodeTab } from './products.js';
import * as stock from './stock.js';
import * as warehouse from './warehouse.js';
import {
  clear, confirmDialog, field, fmtDate, fmtDateTime, h, matches, modal, moduleToolbar, pageHead, pref, segmented, selectInput, setPref, statStrip,
  toast, toastError,
} from '../ui.js';

const TYPE = { YEDEK_PARCA: ['Yedek parça', 'spare'], HAMMADDE: ['Hammadde', 'raw'], DEMIRBAS: ['Demirbaş', 'fixture'], SARF: ['Sarf malzeme', 'consumable'] };
const UNITS = ['adet', 'g', 'kg', 'm', 'cm', 'mm', 'lt', 'ml', 'm²', 'paket'];
const SUBS = [
  { key: 'materials', title: 'Malzeme Yönetimi' },
  { key: 'semi', title: 'Yarı Mamül', module: 'stock' },
  { key: 'approvals', title: 'Onay Yönetimi', module: 'warehouse' },
  { key: 'depots', title: 'Depo Yönetimi' },
];
const MOVE_TONE = { GIRIS: 'green', GERI_KAZANIM: 'green', CIKIS: 'yellow', TRANSFER: 'blue', SAYIM: 'purple', KULLANIM: 'yellow', HURDA: 'red' };
const num = v => (v == null ? '—' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: 3 }));
const money = v => (v || v === 0 ? Number(v).toLocaleString('tr-TR', { style: 'currency', currency: 'TRY' }) : '—');
const typeTag = t => h('span', { class: `type-tag ${(TYPE[t] || [])[1] || ''}` }, (TYPE[t] || [t])[0]);
const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));
let canEdit = false;

export async function render(view, params, ctx) {
  canEdit = ctx.user.roles.some(r => ['Sistem Yöneticisi', 'Depo Yöneticisi', 'MRP Sorumlusu'].includes(r));
  const subs = SUBS.filter(s => !s.module || ctx.user.modules.includes(s.module));
  const sub = subs.find(s => s.key === params[0]) || subs[0];
  const rest = params[0] === sub.key ? params.slice(1) : [];
  setPref('mrp.last', sub.key);
  if (sub.key === 'semi') await stock.render(view, rest, ctx);
  else if (sub.key === 'approvals') await warehouse.render(view, rest, ctx);
  else if (sub.key === 'depots') await renderDepots(view, ctx);
  else if (/^\d+$/.test(rest[0] || '')) return renderMaterial(view, Number(rest[0]), ctx);   // ayrıntı kendi başlığıyla
  else await renderMaterials(view);
  mrpHead(view, sub, subs);
}

// Başlık: "MRP", alt modül adı alt satırda, alt modül seçimi sağda açılır liste
function mrpHead(view, cur, subs) {
  const head = view.querySelector('.page-head');
  if (!head) return;
  head.querySelector('h1').textContent = 'MRP';
  const subEl = head.querySelector('.sub');
  const text = (subEl?.textContent || '').trim();
  const detail = text && !text.startsWith(cur.title) ? text : '';   // detay bağlamı (ör. malzeme adı) korunur
  if (subEl) subEl.remove();
  if (detail) head.querySelector('h1').after(h('div', { class: 'sub' }, detail));
  const back = head.querySelector('a.back');
  if (back) back.setAttribute('href', '#/');
  // Alt modüller açılır liste yerine başlık bandında sekme çubuğu (.seg.seg-tabs)
  if (!head.querySelector('.seg-tabs')) {
    head.append(segmented(subs.map(s => [s.key, s.title]), cur.key, k => { location.hash = `#/mrp/${k}`; }, { tabs: true }));
  }
}

// ---------- Malzeme Yönetimi: liste / kart
async function renderMaterials(view) {
  const list = await api.get('/api/mrp/materials');
  const stats = statStrip();
  stats.set([
    { label: 'Malzeme', value: list.length },
    { label: 'Yedek parça', value: list.filter(m => m.type === 'YEDEK_PARCA').length },
    { label: 'Hammadde', value: list.filter(m => m.type === 'HAMMADDE').length },
    { label: 'Demirbaş', value: list.filter(m => m.type === 'DEMIRBAS').length },
    { label: 'Sarf malzeme', value: list.filter(m => m.type === 'SARF').length },
    { label: 'Kritik stok altında', value: list.filter(m => m.critical).length, tone: list.some(m => m.critical) ? 'alert' : 'ok' },
    { label: 'Stokta olmayan', value: list.filter(m => !m.stock).length },
  ]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Stok kodu, ad, barkod, marka ara…', style: { width: '240px' } });
  const kind = selectInput(Object.entries(TYPE).map(([k, v]) => [k, v[0]]), { all: 'Tüm malzeme tipleri', value: pref('mrp.kind', '') });
  const state = selectInput([['critical', 'Kritik stok altında'], ['empty', 'Stokta olmayan'], ['passive', 'Pasif']], { all: 'Tüm durumlar' });
  let mode = pref('mrp.view', 'card');
  const body = h('div');
  const draw = () => {
    setPref('mrp.kind', kind.value);
    const rows = list.filter(m => (!kind.value || m.type === kind.value)
      && (!state.value || (state.value === 'critical' ? m.critical : state.value === 'empty' ? !m.stock : !m.active))
      && (state.value === 'passive' || m.active)
      && matches(q.value, m.code, m.name, m.barcode, m.brand, m.model, m.description));
    setListExport(() => ({ columns: ['Kod', 'Malzeme', 'Tür', 'Barkod', 'Marka', 'Model', 'Stok', 'Birim', 'Kritik stok', 'Durum'],
      rows: rows.map(m => [m.code, m.name, (TYPE[m.type] || [m.type])[0], m.barcode || '', m.brand || '', m.model || '', m.stock ?? '', m.unit || '', m.min_stock ?? '', m.active ? 'Aktif' : 'Pasif']) }));
    if (!rows.length) return clear(body, h('div', { class: 'card empty' }, list.length ? 'Filtreye uyan malzeme yok' : 'Henüz malzeme yok. “Yeni” ile yedek parça ya da hammadde ekleyin.'));
    clear(body, mode === 'card'
      ? h('div', { class: 'grid-cards product-grid mrp-grid' }, rows.map(materialCard))
      : h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
        h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Stok kodu'), h('th', null, 'Ad'), h('th', null, 'Tip'), h('th', null, 'Marka / Model'),
          h('th', null, 'Barkod'), h('th', { class: 'num' }, 'Stok'), h('th', { class: 'num' }, 'Kritik'))),
        h('tbody', null, rows.map(m => h('tr', { class: `click ${m.critical ? 'row-alert' : ''}`, onclick: () => { location.hash = `#/mrp/materials/${m.id}`; } },
          h('td', null, m.cover ? h('img', { class: 'mrp-thumb', src: fileUrl(m.cover, 128), alt: '', loading: 'lazy' }) : null),
          h('td', { class: 'mono' }, h('b', null, m.code)), h('td', null, m.name), h('td', null, typeTag(m.type)),
          h('td', null, [m.brand, m.model].filter(Boolean).join(' · ') || '—'), h('td', { class: 'mono small' }, m.barcode || '—'),
          h('td', { class: 'num' }, h('b', null, num(m.stock)), ` ${m.unit || 'adet'}`), h('td', { class: 'num small muted' }, m.min_stock != null ? num(m.min_stock) : '—')))))));
  };
  const seg = segmented([['card', 'Kart'], ['list', 'Liste']], mode, v => { mode = v; setPref('mrp.view', v); draw(); });
  [q, kind, state].forEach(el => el.addEventListener(el === q ? 'input' : 'change', draw));
  clear(view, pageHead('Malzeme Yönetimi', { back: '#/', sub: 'Yedek parça, hammadde, demirbaş ve sarf malzemeler' }),
    moduleToolbar(canEdit ? newMenu() : null),
    stats, h('div', { class: 'filters' }, q, kind, state, h('span', { class: 'spacer' }), seg), body);
  draw();
}

function materialCard(m) {
  return h('a', { class: `card product-card mrp-card ${(TYPE[m.type] || [])[1] || ''} ${m.critical ? 'critical' : ''}`, href: `#/mrp/materials/${m.id}` },
    h('div', { class: `product-preview ${m.cover ? 'g3d' : ''}` }, m.cover ? h('img', { class: 'g3d-img', src: fileUrl(m.cover, 480), alt: m.name, loading: 'lazy' })
      : h('div', { class: 'product-ph' }, h('span', null, m.code))),
    h('div', { class: 'product-info' },
      h('div', { class: 'top' }, h('b', null, m.name), h('span', { class: 'grow' }), typeTag(m.type), m.active ? null : h('span', { class: 'badge gray' }, 'Pasif')),
      h('div', { class: 'mrp-card-stock' }, h('b', null, num(m.stock)), h('span', null, m.unit || 'adet'),
        m.critical ? h('span', { class: 'badge red' }, `Kritik: ${num(m.min_stock)}`) : null),
      h('dl', null,
        h('dt', null, 'Stok kodu'), h('dd', { class: 'mono' }, m.code),
        m.barcode ? [h('dt', null, 'Barkod'), h('dd', { class: 'mono' }, m.barcode)] : null,
        m.brand || m.model ? [h('dt', null, 'Marka / Model'), h('dd', null, [m.brand, m.model].filter(Boolean).join(' · '))] : null)));
}

function newMenu() {
  const menu = h('div', { class: 'dropdown new-menu', hidden: true },
    Object.entries(TYPE).map(([t, [label]]) => h('button', { type: 'button', onclick: () => { menu.hidden = true; newMaterial(t); } }, typeTag(t), label)));
  const btn = h('button', { class: 'btn primary', type: 'button' }, '＋ Yeni ', h('span', { class: 'caret' }, '▾'));
  const wrap = h('div', { class: 'new-wrap' }, btn, menu);
  btn.addEventListener('click', e => { e.stopPropagation(); menu.hidden = !menu.hidden; });
  document.addEventListener('click', e => { if (!wrap.contains(e.target)) menu.hidden = true; });
  return wrap;
}

function newMaterial(type) {
  const code = h('input', { class: 'input mono', maxlength: 24, placeholder: type === 'HAMMADDE' ? 'ör. HM-PLA' : 'ör. MT-2212', style: { textTransform: 'uppercase' } });
  const name = h('input', { class: 'input', placeholder: type === 'HAMMADDE' ? 'ör. PLA Filament' : 'ör. Fırçasız Motor 2212' });
  const kind = h('select', { class: 'input' }, Object.entries(TYPE).map(([k, [l]]) => h('option', { value: k, selected: k === type }, l)));
  const unit = h('select', { class: 'input' }, UNITS.map(u => h('option', { value: u, selected: u === (type === 'HAMMADDE' ? 'g' : 'adet') }, u)));
  modal({
    title: 'Yeni malzeme',
    body: h('div', null, field('Stok kodu', code), field('Malzeme adı', name), h('div', { class: 'row' }, field('Tipi', kind), field('Birim', unit))),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const { id } = await api.post('/api/mrp/materials', { code: code.value, name: name.value, type: kind.value, unit: unit.value });
      toast('Malzeme eklendi');
      location.hash = `#/mrp/materials/${id}`;
    } }],
  });
  code.focus();
}

// ---------- Malzeme ayrıntısı
async function renderMaterial(view, id, ctx) {
  const m = await api.get(`/api/mrp/materials/${id}`);
  const edit = m.can_edit;
  const f = {
    code: h('input', { class: 'input mono', value: m.code, disabled: !edit }),
    name: h('input', { class: 'input', value: m.name, disabled: !edit }),
    type: h('select', { class: 'input', disabled: !edit }, Object.entries(TYPE).map(([k, [l]]) => h('option', { value: k, selected: k === m.type }, l))),
    unit: h('select', { class: 'input', disabled: !edit }, UNITS.map(u => h('option', { value: u, selected: u === (m.unit || 'adet') }, u))),
    barcode: h('input', { class: 'input mono', value: m.barcode || '', disabled: !edit, inputmode: 'numeric' }),
    brand: h('input', { class: 'input', value: m.brand || '', disabled: !edit }),
    model: h('input', { class: 'input', value: m.model || '', disabled: !edit }),
    min: h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: m.min_stock ?? '', disabled: !edit, placeholder: 'Uyarı sınırı' }),
    desc: h('textarea', { class: 'input', rows: 2, disabled: !edit }, m.description || ''),
    active: h('input', { type: 'checkbox', checked: !!m.active, disabled: !edit }),
  };
  const save = h('button', { class: 'btn primary', onclick: async () => {
    try {
      await api.put(`/api/mrp/materials/${id}`, { code: f.code.value, name: f.name.value, type: f.type.value, unit: f.unit.value, barcode: f.barcode.value,
        brand: f.brand.value, model: f.model.value, description: f.desc.value, min_stock: f.min.value === '' ? null : Number(f.min.value), active: f.active.checked });
      toast('Malzeme bilgileri kaydedildi'); reload();
    } catch (err) { toastError(err); }
  } }, 'Kaydet');
  const top = h('div', { class: `card card-pad mrp-top ${m.critical ? 'critical' : ''}` },
    h('div', { class: 'mrp-top-img' }, m.cover ? h('img', { src: fileUrl(m.cover, 480), alt: '' }) : h('div', { class: 'product-ph' }, h('span', null, m.code))),
    h('div', { class: 'mrp-top-body' },
      h('div', { class: 'mrp-top-stock' }, h('b', null, num(m.stock)), h('span', null, `${m.unit || 'adet'} toplam stok`),
        m.critical ? h('span', { class: 'badge red' }, `Kritik stok (${num(m.min_stock)}) altında`) : null),
      h('div', { class: 'form-grid' }, field('Stok kodu', f.code), field('Barkod', f.barcode), field('Marka', f.brand), field('Model', f.model),
        field('Malzeme adı', f.name), field('Tipi', f.type), field('Birim', f.unit), field('Kritik stok', f.min)),
      field('Açıklama', f.desc),
      edit ? h('div', { class: 'pd-info-foot' }, h('label', { class: 'check' }, f.active, 'Aktif'), h('span', { class: 'spacer' }), save) : null));
  const tabs = [['physical', 'Fiziksel Özellikler'], ['moves', 'Stok Hareketi'], ['depots', 'Depo'], ['3d', '3B'], ['images', `Resimler${m.images.length ? ` (${m.images.length})` : ''}`],
    ['docs', 'Fatura İrsaliye'], ['scrap', 'Hurda ve Kullanım'], ['used', `Kullanıldığı Ürünler${m.used_in.length ? ` (${m.used_in.length})` : ''}`]];
  let tab = pref('mrp.tab', 'physical');
  if (!tabs.some(t => t[0] === tab)) tab = 'physical';
  const stage = h('div');
  let cleanup = null;
  const show = async () => {
    cleanup?.(); cleanup = null;
    clear(stage, h('div', { class: 'card card-pad loading' }, 'Yükleniyor…'));
    try {
      if (tab === 'physical') clear(stage, physicalTab(m));
      else if (tab === 'moves') clear(stage, await movesTab(m));
      else if (tab === 'depots') clear(stage, depotsTab(m));
      else if (tab === '3d') cleanup = await gcodeTab(stage, m, edit, `/api/mrp/materials/${m.id}`);
      else if (tab === 'images') clear(stage, imagesTab(m));
      else if (tab === 'docs') clear(stage, await docsTab(m));
      else if (tab === 'scrap') clear(stage, await scrapTab(m));
      else clear(stage, usedTab(m));
    } catch (err) { clear(stage, h('div', { class: 'card empty' }, err.message)); }
  };
  const seg = segmented(tabs, tab, v => { tab = v; setPref('mrp.tab', v); show(); });
  seg.classList.add('hr-tabs');
  clear(view, pageHead(m.name, { back: '#/mrp/materials', sub: `MRP · ${m.code} · ${(TYPE[m.type] || [m.type])[0]}` }),
  moduleToolbar(edit ? [h('button', { class: 'btn', onclick: () => moveModal(m, 'GIRIS') }, '＋ Stok Girişi'),
    h('button', { class: 'btn', onclick: () => moveModal(m, 'CIKIS') }, 'Stok Çıkışı')] : null),
  top, seg, stage);
  show();
}

function physicalTab(m) {
  const n = (v, ph) => h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: v ?? '', placeholder: ph, disabled: !m.can_edit });
  const color = h('input', { class: 'input', value: m.color || '', placeholder: 'ör. Siyah, RAL 9005', disabled: !m.can_edit });
  const swatch = h('input', { type: 'color', class: 'mrp-color', title: 'Renk seç', disabled: !m.can_edit,
    oninput: e => { color.value = e.target.value.toUpperCase(); } });
  const w = n(m.width_mm, 'mm'), hh = n(m.height_mm, 'mm'), d = n(m.depth_mm, 'mm'), g = n(m.weight_g, 'g');
  const save = h('button', { class: 'btn primary', onclick: async () => {
    const v = el => (el.value === '' ? null : Number(el.value));
    try { await api.put(`/api/mrp/materials/${m.id}/physical`, { color: color.value, width_mm: v(w), height_mm: v(hh), depth_mm: v(d), weight_g: v(g) }); toast('Fiziksel özellikler kaydedildi'); reload(); } catch (err) { toastError(err); }
  } }, 'Kaydet');
  const file = h('input', { type: 'file', accept: 'image/*', hidden: true });
  file.addEventListener('change', async () => {
    const fd = new FormData(); fd.append('file', file.files[0]);
    try { await upload(`/api/mrp/materials/${m.id}/image`, fd); toast('Tanımlama resmi yüklendi'); reload(); } catch (err) { toastError(err); }
  });
  return h('div', { class: 'hr-general' },
    h('div', { class: 'card card-pad' }, h('h3', null, 'Fiziksel özellikler'),
      h('div', { class: 'form-grid' },
        field('Renk', h('div', { class: 'row-inline' }, swatch, color)),
        field('Genişlik (mm)', w), field('Yükseklik (mm)', hh), field('Derinlik (mm)', d), field('Ağırlık (g)', g)),
      m.width_mm && m.height_mm && m.depth_mm ? h('div', { class: 'small muted' }, `Hacim: ${num(m.width_mm * m.height_mm * m.depth_mm / 1000)} cm³`) : null,
      m.can_edit ? h('div', { class: 'hr-save' }, save) : null),
    h('div', { class: 'card card-pad' }, h('h3', null, 'Tanımlama resmi'),
      m.image ? h('a', { class: 'pd-image', href: fileUrl(m.image), target: '_blank', rel: 'noopener' }, h('img', { src: fileUrl(m.image, 800), alt: '' }))
        : h('div', { class: 'drop-zone', onclick: m.can_edit ? () => file.click() : null }, h('div', { class: 'dz-ico' }, '🖼'),
          h('b', null, m.can_edit ? 'Tanımlama resmini yükleyin' : 'Resim yok'), h('span', { class: 'small muted' }, 'Malzeme kartında ve listede görünür')),
      m.can_edit && m.image ? h('div', { class: 'row-inline', style: { marginTop: '8px' } },
        h('button', { class: 'btn sm', onclick: () => file.click() }, 'Değiştir'),
        h('button', { class: 'btn sm ghost', onclick: async () => { await api.del(`/api/mrp/materials/${m.id}/image`); reload(); } }, 'Kaldır')) : null, file));
}

const moveTable = (rows, { product = false } = {}) => h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
  h('thead', null, h('tr', null, h('th', null, 'Tarih'), product ? h('th', null, 'Malzeme') : null, h('th', null, 'Hareket'), h('th', null, 'Depo'),
    h('th', { class: 'num' }, 'Miktar'), h('th', null, 'Açıklama'), h('th', null, 'Belge'), h('th', null, 'Kişi'))),
  h('tbody', null, rows.map(r => h('tr', null,
    h('td', { class: 'small' }, fmtDateTime(r.created_at)),
    product ? h('td', null, h('a', { href: `#/mrp/materials/${r.product_id}` }, `${r.product_code} — ${r.product_name}`)) : null,
    h('td', null, h('span', { class: `badge ${MOVE_TONE[r.kind] || 'gray'}` }, r.kind_label), r.source === 'UCUS' ? h('div', { class: 'small muted' }, 'Uçuş kaynaklı') : null),
    h('td', null, r.warehouse_name || h('span', { class: 'muted' }, 'Stok dışı')),
    h('td', { class: `num ${r.qty < 0 ? 'neg' : 'pos'}` }, h('b', null, `${r.qty > 0 ? '+' : ''}${num(r.qty)}`), ` ${r.unit || ''}`,
      r.unit_price ? h('div', { class: 'small muted' }, `${money(r.unit_price)} / ${r.unit || 'adet'}`) : null),
    h('td', { class: 'small' }, r.reason || '', r.order_code ? h('div', { class: 'muted' }, `Uçak: ${r.queue_no || r.order_code}`) : null),
    h('td', { class: 'small' }, r.doc_number || r.doc_kind ? (r.doc_file ? h('a', { href: fileUrl(r.doc_file), target: '_blank', rel: 'noopener' }, `${r.doc_kind === 'FATURA' ? 'Fatura' : 'İrsaliye'} ${r.doc_number || ''}`)
      : `${r.doc_kind === 'FATURA' ? 'Fatura' : 'İrsaliye'} ${r.doc_number || ''}`) : '—'),
    h('td', { class: 'small muted' }, r.user_name || '—'))))));

async function movesTab(m) {
  const rows = await api.get(`/api/mrp/materials/${m.id}/moves`);
  return h('div', null,
    m.can_edit ? h('div', { class: 'tv-bar' }, h('span', { class: 'spacer' }),
      [['GIRIS', '＋ Giriş'], ['CIKIS', 'Çıkış'], ['TRANSFER', 'Transfer'], ['SAYIM', 'Sayım']].map(([k, l]) =>
        h('button', { class: `btn sm ${k === 'GIRIS' ? 'primary' : ''}`, onclick: () => moveModal(m, k) }, l))) : null,
    rows.length ? moveTable(rows) : h('div', { class: 'card empty' }, 'Stok hareketi yok'));
}

function depotsTab(m) {
  return h('div', { class: 'mrp-depots' }, m.warehouses.length ? m.warehouses.map(w => h('div', { class: `card mrp-depot ${w.qty > 0 ? '' : 'empty'}` },
    h('div', { class: 'mrp-depot-name' }, h('b', null, w.name), w.code ? h('span', { class: 'mono small muted' }, w.code) : null),
    h('div', { class: 'mrp-depot-qty' }, num(w.qty), h('small', null, m.unit || 'adet')),
    h('div', { class: 'small muted' }, [w.location, w.responsible_name ? `Sorumlu: ${w.responsible_name}` : null].filter(Boolean).join(' · ') || ' '),
    m.can_edit ? h('div', { class: 'row-inline' }, h('button', { class: 'btn sm', onclick: () => moveModal(m, 'GIRIS', w.id) }, 'Giriş'),
      w.qty > 0 ? h('button', { class: 'btn sm', onclick: () => moveModal(m, 'TRANSFER', w.id) }, 'Transfer') : null) : null))
    : h('div', { class: 'card empty' }, 'Depo tanımlı değil. Depo Yönetimi’nden depo ekleyin.'));
}

function imagesTab(m) {
  const input = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
  input.addEventListener('change', async () => {
    if (!input.files.length) return;
    const fd = new FormData();
    for (const f of input.files) fd.append('files', f);
    try { await upload(`/api/mrp/materials/${m.id}/images`, fd); toast(`${input.files.length} resim yüklendi`); reload(); } catch (err) { toastError(err); }
  });
  const remove = async i => {
    if (!await confirmDialog('Resmi sil', `${i.file_name || 'Resim'} silinsin mi?`, { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/mrp/materials/${m.id}/images/${i.id}`); reload(); } catch (err) { toastError(err); }
  };
  return h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' }, h('b', null, 'Resimler'), h('span', { class: 'spacer' }),
      m.can_edit ? h('button', { class: 'btn sm primary', onclick: () => input.click() }, '＋ Resim Ekle') : null, input),
    m.images.length ? h('div', { class: 'mrp-gallery' }, m.images.map(i => h('figure', null,
      h('a', { href: fileUrl(i.path), target: '_blank', rel: 'noopener' }, h('img', { src: fileUrl(i.path, 480), alt: i.file_name || '', loading: 'lazy' })),
      h('figcaption', { class: 'small muted' }, `${fmtDate(i.created_at)} · ${i.user_name || ''}`,
        m.can_edit ? h('button', { class: 'link-btn small danger-text', onclick: () => remove(i) }, 'Sil') : null))))
      : h('div', { class: 'drop-zone', onclick: m.can_edit ? () => input.click() : null }, h('div', { class: 'dz-ico' }, '🖼'),
        h('b', null, m.can_edit ? 'Birden fazla resim seçebilirsiniz' : 'Resim yok')));
}

async function docsTab(m) {
  const rows = await api.get(`/api/mrp/materials/${m.id}/docs`);
  return h('div', null,
    m.can_edit ? h('div', { class: 'tv-bar' }, h('span', { class: 'small muted' }, 'Belgeler stok girişinde eklenir'), h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm primary', onclick: () => moveModal(m, 'GIRIS') }, '＋ Faturalı / İrsaliyeli Giriş')) : null,
    rows.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, h('th', null, 'Belge'), h('th', null, 'No'), h('th', null, 'Tarih'), h('th', null, 'Tedarikçi'),
        h('th', { class: 'num' }, 'Miktar'), h('th', { class: 'num' }, 'Birim fiyat'), h('th', { class: 'num' }, 'Belge tutarı'), h('th', null, 'Dosya'))),
      h('tbody', null, rows.map(d => h('tr', null,
        h('td', null, h('span', { class: `badge ${d.kind === 'FATURA' ? 'blue' : 'purple'}` }, d.kind === 'FATURA' ? 'Fatura' : 'İrsaliye')),
        h('td', { class: 'mono' }, d.number || '—'), h('td', null, fmtDate(d.doc_date) || fmtDate(d.created_at)),
        h('td', null, d.company_name || d.supplier || '—'), h('td', { class: 'num' }, `${num(d.qty)} ${m.unit || ''}`),
        h('td', { class: 'num' }, money(d.unit_price)), h('td', { class: 'num' }, money(d.amount)),
        h('td', null, d.file ? h('a', { href: fileUrl(d.file), target: '_blank', rel: 'noopener' }, d.file_name || 'Aç') : '—'))))))
      : h('div', { class: 'card empty' }, 'Bu malzemeye bağlı fatura / irsaliye yok'));
}

async function scrapTab(m) {
  const rows = await api.get(`/api/mrp/materials/${m.id}/scrap`);
  const sum = k => rows.filter(r => r.kind === k).reduce((a, r) => a + Math.abs(r.qty), 0);
  return h('div', null,
    h('div', { class: 'stat-strip' },
      h('div', { class: 'stat' }, h('span', { class: 'v' }, num(sum('KULLANIM'))), h('span', { class: 'l' }, 'Kullanım (eritme)')),
      h('div', { class: 'stat alert' }, h('span', { class: 'v' }, num(sum('HURDA'))), h('span', { class: 'l' }, 'Hurda')),
      h('div', { class: 'stat' }, h('span', { class: 'v' }, num(rows.filter(r => r.kind === 'HURDA' && r.source === 'UCUS').reduce((a, r) => a + Math.abs(r.qty), 0))), h('span', { class: 'l' }, 'Uçuş kaynaklı hurda')),
      h('div', { class: 'stat ok' }, h('span', { class: 'v' }, num(sum('GERI_KAZANIM'))), h('span', { class: 'l' }, 'Hurda uçaktan geri kazanım'))),
    m.can_edit ? h('div', { class: 'tv-bar' }, h('span', { class: 'small muted' }, 'Uçuş kaynaklı hurda, uçak hurdaya ayrılırken içindeki malzemeler değerlendirilince yazılır'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', onclick: () => moveModal(m, 'KULLANIM') }, 'Kullanım / Eritme Kaydı'),
      h('button', { class: 'btn sm danger', onclick: () => moveModal(m, 'HURDA') }, 'Hurdaya Ayır')) : null,
    rows.length ? moveTable(rows) : h('div', { class: 'card empty' }, 'Kullanım ya da hurda kaydı yok'));
}

function usedTab(m) {
  return m.used_in.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
    h('thead', null, h('tr', null, h('th', null, 'Ürün'), h('th', null, 'Tip'), h('th', { class: 'num' }, 'Reçetedeki miktar'))),
    h('tbody', null, m.used_in.map(u => h('tr', null, h('td', null, h('a', { href: `#/products/${u.id}` }, `${u.code} — ${u.name}`)),
      h('td', null, u.type === 'MAMUL' ? 'Mamul' : 'Yarı mamul'), h('td', { class: 'num' }, `${num(u.qty)} ${m.unit || ''}`))))))
    : h('div', { class: 'card empty' }, 'Bu malzeme henüz bir ürünün reçetesinde yok (Ürün Yönetimi › Reçete)');
}

// Stok hareketi penceresi: giriş (fatura / irsaliyeyle), çıkış, transfer, sayım, kullanım, hurda
async function moveModal(m, kind, depotId) {
  const ws = (await api.get('/api/mrp/warehouses')).filter(w => w.active);
  if (!ws.length) { toast('Önce Depo Yönetimi’nden depo ekleyin', 'err'); return; }
  const stockOf = id => m.warehouses.find(w => w.id === id)?.qty || 0;
  const titles = { GIRIS: 'Stok Girişi', CIKIS: 'Stok Çıkışı', TRANSFER: 'Depolar Arası Transfer', SAYIM: 'Sayım Düzeltmesi', KULLANIM: 'Kullanım / Eritme Kaydı', HURDA: 'Hurdaya Ayır' };
  const dep = h('select', { class: 'input' }, ws.map(w => h('option', { value: w.id, selected: w.id === (depotId || ws[0].id) }, `${w.name} (${num(stockOf(w.id))} ${m.unit || 'adet'})`)));
  const to = h('select', { class: 'input' }, ws.map(w => h('option', { value: w.id }, w.name)));
  const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', placeholder: kind === 'SAYIM' ? 'Sayılan miktar' : 'Miktar' });
  const price = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', placeholder: '₺' });
  const reason = h('input', { class: 'input', placeholder: kind === 'KULLANIM' ? 'ör. Test tezgâhında aşındı' : kind === 'HURDA' ? 'ör. Kırık, yanık' : 'Açıklama' });
  // belge (yalnızca giriş)
  const docKind = h('select', { class: 'input' }, h('option', { value: '' }, 'Belge yok'), h('option', { value: 'FATURA' }, 'Fatura'), h('option', { value: 'IRSALIYE' }, 'İrsaliye'));
  const docNo = h('input', { class: 'input mono' });
  const docDate = h('input', { class: 'input', type: 'date', value: new Date().toLocaleDateString('sv') });
  const companies = kind === 'GIRIS' ? await api.get('/api/mrp/companies').catch(() => []) : [];
  const company = h('select', { class: 'input' }, h('option', { value: '' }, 'Firma seçin (ya da yazın)'), companies.map(c => h('option', { value: c.id }, c.name)));
  const supplier = h('input', { class: 'input', placeholder: 'Tedarikçi adı' });
  const amount = h('input', { class: 'input', type: 'number', min: 0, step: '0.01', placeholder: '₺' });
  const file = h('input', { class: 'input', type: 'file', accept: '.pdf,.jpg,.jpeg,.png,.webp,.heic,.xml,.zip' });
  const docBox = h('div', { class: 'mrp-doc', hidden: true },
    h('div', { class: 'form-grid' }, field('Belge no', docNo), field('Belge tarihi', docDate), field('Firma', company), field('Tedarikçi (firma yoksa)', supplier),
      field('Belge tutarı', amount), field('Belge dosyası', file)));
  docKind.addEventListener('change', () => { docBox.hidden = !docKind.value; });
  modal({
    title: `${m.code} · ${titles[kind]}`, wide: kind === 'GIRIS',
    body: h('div', null,
      h('div', { class: 'form-grid' },
        field(kind === 'TRANSFER' ? 'Kaynak depo' : 'Depo', dep), kind === 'TRANSFER' ? field('Hedef depo', to) : null,
        field(kind === 'SAYIM' ? `Sayılan miktar (${m.unit || 'adet'})` : `Miktar (${m.unit || 'adet'})`, qty),
        kind === 'GIRIS' ? field('Birim fiyat', price) : null),
      field(['CIKIS', 'KULLANIM', 'HURDA'].includes(kind) ? 'Açıklama *' : 'Açıklama', reason),
      kind === 'GIRIS' ? [field('Fatura / İrsaliye', docKind), docBox] : null),
    actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: kind === 'HURDA' ? 'danger' : 'primary', onClick: async () => {
      let docId = null;
      if (kind === 'GIRIS' && docKind.value) {
        const fd = new FormData();
        fd.append('kind', docKind.value); fd.append('number', docNo.value); fd.append('doc_date', docDate.value);
        if (company.value) fd.append('company_id', company.value);
        fd.append('supplier', supplier.value); if (amount.value) fd.append('amount', amount.value);
        if (file.files[0]) fd.append('file', file.files[0]);
        docId = (await upload('/api/mrp/docs', fd)).id;
      }
      await api.post(`/api/mrp/materials/${m.id}/moves`, { kind, warehouse_id: Number(dep.value), to_warehouse_id: kind === 'TRANSFER' ? Number(to.value) : null,
        qty: Number(qty.value), unit_price: price.value === '' ? null : Number(price.value), reason: reason.value, doc_id: docId });
      toast(`${titles[kind]} kaydedildi`);
      reload();
    } }],
  });
  qty.focus();
}

// ---------- Depo Yönetimi: depolar (kart) ve sorumluları
async function renderDepots(view, ctx) {
  const [ws, people] = await Promise.all([api.get('/api/mrp/warehouses'), api.get('/api/people').catch(() => [])]);
  const form = w => {
    const name = h('input', { class: 'input', value: w?.name || '' });
    const code = h('input', { class: 'input mono', value: w?.code || '', maxlength: 12, style: { textTransform: 'uppercase' } });
    const loc = h('input', { class: 'input', value: w?.location || '', placeholder: 'ör. Fabrika zemin kat, Polatlı saha' });
    const resp = h('select', { class: 'input' }, h('option', { value: '' }, 'Sorumlu seçin'),
      people.map(p => h('option', { value: p.id, selected: p.id === w?.responsible_id }, p.full_name)));
    const note = h('input', { class: 'input', value: w?.note || '' });
    const active = h('input', { type: 'checkbox', checked: w ? !!w.active : true });
    modal({
      title: w ? `${w.name} · Düzenle` : 'Yeni Depo',
      body: h('div', null, h('div', { class: 'form-grid' }, field('Depo adı *', name), field('Kod', code), field('Konum', loc), field('Depo sorumlusu', resp)),
        field('Not', note), h('label', { class: 'check' }, active, 'Aktif')),
      actions: [
        w && !w.move_count && canEdit ? { label: 'Sil', class: 'danger', onClick: async () => { await api.del(`/api/mrp/warehouses/${w.id}`); toast('Depo silindi'); reload(); } } : null,
        'spacer', { label: 'Vazgeç' },
        { label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = { name: name.value, code: code.value, location: loc.value, responsible_id: resp.value ? Number(resp.value) : null, note: note.value, active: active.checked };
          if (w) await api.put(`/api/mrp/warehouses/${w.id}`, body); else await api.post('/api/mrp/warehouses', body);
          toast('Depo kaydedildi'); reload();
        } }].filter(Boolean),
    });
    name.focus();
  };
  clear(view,
    pageHead('Depo Yönetimi', { back: '#/', sub: 'Depolar ve sorumluları' }),
    moduleToolbar(canEdit ? h('button', { class: 'btn primary', onclick: () => form(null) }, '＋ Yeni Depo') : null),
    h('div', { class: 'mrp-depots' }, ws.map(w => h('div', { class: `card mrp-depot big ${w.active ? '' : 'passive'}` },
      h('div', { class: 'mrp-depot-name' }, h('b', null, w.name), w.code ? h('span', { class: 'mono small muted' }, w.code) : null, w.active ? null : h('span', { class: 'badge gray' }, 'Pasif')),
      h('div', { class: 'mrp-depot-qty' }, w.material_count, h('small', null, 'çeşit malzeme')),
      h('div', { class: 'small' }, w.location || h('span', { class: 'muted' }, 'Konum girilmemiş')),
      h('div', { class: 'mrp-resp' }, w.responsible_name ? [h('span', { class: 'avatar sm' }, w.responsible_photo ? h('img', { src: fileUrl(w.responsible_photo, 128), alt: '' })
        : w.responsible_name.split(/\s+/).slice(0, 2).map(s => s[0]).join('')), h('span', null, w.responsible_name)] : h('span', { class: 'muted small' }, 'Sorumlu atanmamış')),
      w.note ? h('div', { class: 'small muted' }, w.note) : null,
      canEdit ? h('button', { class: 'btn sm', onclick: () => form(w) }, 'Düzenle') : null))));
}

// ---------- Uçuş kaynaklı hurda: hurdaya ayrılan uçağın malzemeleri (Saha › uçuş sayfasından açılır)
export async function aircraftReviewModal(orderId, done) {
  const d = await api.get(`/api/mrp/aircraft/${orderId}/materials`);
  if (!d.items.length) { done?.(); return; }
  const rows = d.items.map(i => {
    const scrap = h('input', { class: 'input', type: 'number', min: 0, max: i.qty, step: 'any', value: i.type === 'HAMMADDE' ? i.qty : i.qty });
    const good = h('input', { class: 'input', type: 'number', min: 0, max: i.qty, step: 'any', value: 0 });
    const dep = h('select', { class: 'input' }, d.warehouses.map(w => h('option', { value: w.id }, w.name)));
    good.addEventListener('input', () => { scrap.value = Math.max(0, i.qty - (Number(good.value) || 0)); });
    scrap.addEventListener('input', () => { good.value = Math.max(0, i.qty - (Number(scrap.value) || 0)); });
    return { i, scrap, good, dep };
  });
  modal({
    title: `${d.queue_no || d.code} · İçindeki malzemeler`, wide: true,
    body: h('div', null,
      h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Uçak hurdaya ayrıldı. Reçetesindeki malzemelerden hurda olanları ve sağlam çıkıp depoya geri alınacakları girin. Hurda, uçuş kaynaklı hurda olarak kaydedilir.'),
      h('table', { class: 'table mrp-review' },
        h('thead', null, h('tr', null, h('th', null, 'Malzeme'), h('th', { class: 'num' }, 'Uçaktaki'), h('th', null, 'Hurda'), h('th', null, 'Sağlam'), h('th', null, 'Sağlam → depo'))),
        h('tbody', null, rows.map(r => h('tr', null,
          h('td', null, h('b', null, r.i.code), ` ${r.i.name}`, h('div', { class: 'small muted' }, TYPE[r.i.type]?.[0] || '')),
          h('td', { class: 'num' }, `${num(r.i.qty)} ${r.i.unit || 'adet'}`), h('td', null, r.scrap), h('td', null, r.good), h('td', null, r.dep)))))),
    actions: [{ label: 'Sonra' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
      const items = rows.flatMap(r => [{ item_id: r.i.item_id, qty: Number(r.scrap.value) || 0, result: 'HURDA' },
        { item_id: r.i.item_id, qty: Number(r.good.value) || 0, result: 'SAGLAM', warehouse_id: Number(r.dep.value) }]).filter(x => x.qty > 0);
      await api.post(`/api/mrp/aircraft/${orderId}/review`, { items });
      toast('Malzemeler kaydedildi');
      done?.();
    } }],
  });
}
