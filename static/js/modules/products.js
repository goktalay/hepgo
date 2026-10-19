// Ürün Yönetimi: mamul, yarı mamul, yedek parça ve hammadde kayıtları.
// Tip bir etikettir; üretim davranışı şemadan gelir (CAYMAZ, ana yapılar, basılı parçalar). "Yeni" ile açılan ürünün
// yapısı ürün ağacı (iç içe yarı mamuller), reçete (yedek parça / hammadde miktarları), resim ve G-code ile tanımlanır.
import { setListExport } from '../listexport.js';
import { api, fileUrl, upload, uploadLarge } from '../api.js';
import { viewer } from '../gcode3d.js';
import { mountAssembly } from '../assembly3d.js';
import { layerToggle, loadPlane, partInfoLines, renderAssembly, renderPlane } from '../plane.js';
import {
  clear, confirmDialog, field, fmtMinutes, h, matches, modal, moduleToolbar, onLeave, pageHead, pref, segmented, selectInput, setPref, statStrip,
  t, toast, toastError,
} from '../ui.js';
import { spareMovesModal, spareAdjustModal } from './stock.js';

const TYPE_LABELS = { MAMUL: 'Mamul', YARI_MAMUL: 'Yarı mamul', YEDEK_PARCA: 'Yedek parça', HAMMADDE: 'Hammadde', DEMIRBAS: 'Demirbaş', SARF: 'Sarf malzeme' };
const TYPE_CLS = { MAMUL: 'mamul', YARI_MAMUL: 'semi', YEDEK_PARCA: 'spare', HAMMADDE: 'raw', DEMIRBAS: 'fixture', SARF: 'consumable' };
const UNITS = ['adet', 'g', 'kg', 'm', 'cm', 'mm', 'lt', 'ml', 'm²', 'paket'];
const ITEM_TYPES = ['YEDEK_PARCA', 'HAMMADDE', 'SARF'];   // reçete kalemleri (sarf malzeme dahil)
const MATERIAL_TYPES = ['YEDEK_PARCA', 'HAMMADDE', 'DEMIRBAS', 'SARF'];   // MRP malzemeleri (birimli)
const num = v => (v == null ? '' : Number.isInteger(Number(v)) ? String(Number(v)) : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: 3 }));
const typeTag = t => h('span', { class: `type-tag ${TYPE_CLS[t] || 'mamul'}` }, TYPE_LABELS[t] || t);

export async function render(view, params, ctx) {
  if (params[0]) return renderDetail(view, Number(params[0]), ctx);
  const ORDER = { MAMUL: 0, YARI_MAMUL: 1, YEDEK_PARCA: 2, HAMMADDE: 3 };
  const products = (await api.get('/api/products')).sort((a, b) => (ORDER[a.type] ?? 9) - (ORDER[b.type] ?? 9) || a.id - b.id);
  const planes = await Promise.all(products.map(p => (p.role === 'custom' ? null : loadPlane(p.id))));
  const sum = k => products.reduce((a, p) => a + (p[k] || 0), 0);
  const stats = statStrip();
  stats.set([
    { icon: 'products', label: 'Aktif ürün', value: products.filter(p => p.active).length, tone: 'ok' },
    { icon: 'orders', label: 'Toplam sipariş', value: sum('order_count') },
    { icon: 'production', label: 'Üretimdeki sipariş', value: sum('wip_count') },
  ]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ürün adı, kod ara…', style: { width: '220px' } });
  const act = selectInput([['1', 'Aktif'], ['0', 'Pasif']], { all: 'Aktif ve pasif' });
  const cards = products.map((p, i) => [p, productCard(p, planes[i])]);
  const empty = h('div', { class: 'card empty', hidden: true }, 'Filtreye uyan ürün yok');
  const kind = selectInput(Object.entries(TYPE_LABELS), { all: 'Tüm ürün tipleri', value: pref('products.kind', 'MAMUL') });
  const draw = () => {
    let shown = 0;
    for (const [p, card] of cards) {
      const ok = (!act.value || String(p.active) === act.value) && (!kind.value || kind.value === p.type)
        && matches(q.value, p.name, p.serial, p.code, p.description);
      card.hidden = !ok;
      shown += ok;
    }
    empty.hidden = shown > 0;
    setListExport(() => ({ columns: ['Kod', 'Ürün', 'Tip', 'Seri', 'Açıklama', 'Durum'],
      rows: cards.filter(([, c]) => !c.hidden).map(([p]) => [p.code, p.name, TYPE_LABELS[p.type] || p.type, p.serial || '', p.description || '', p.active ? 'Aktif' : 'Pasif']) }));
  };
  kind.addEventListener('change', () => { setPref('products.kind', kind.value); draw(); });
  q.addEventListener('input', draw);
  act.addEventListener('change', draw);
  clear(view,
    pageHead('Ürün Yönetimi', { back: '#/', sub: 'Mamul, yarı mamul ve parçalar' }),
    moduleToolbar(newButton()),
    stats,
    h('div', { class: 'filters' }, q, kind, act),
    h('div', { class: 'grid-cards product-grid' }, cards.map(c => c[1])),
    empty);
  draw();
}

function productCard(p, plane) {
  const cls = TYPE_CLS[p.type] || 'mamul';
  const dl = (...rows) => h('dl', null, rows.filter(Boolean).flatMap(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
  const usedIn = p.used_in?.length ? p.used_in.map(x => x.name).join(', ') : p.parent ? p.parent.name : '—';
  let preview;
  if (p.image) preview = h('img', { class: 'g3d-img', src: fileUrl(p.image, 480), alt: p.name, loading: 'lazy' });
  else if (p.gcode_preview) preview = h('img', { class: 'g3d-img', src: fileUrl(p.gcode_preview.replace(/\.bin$/, '.png')), alt: p.name, loading: 'lazy' });   // G-code'dan 3B parça (sunucuda çizilmiş kart resmi)
  else if (plane) preview = renderPlane(plane, { fill: () => 'var(--part-fill)', label: () => null }).svg;
  else preview = h('div', { class: 'product-ph' }, h('span', null, p.code));
  const info = p.role === 'part' ? dl(['Kod', h('span', { class: 'mono' }, p.code)], ['Ait olduğu', usedIn],
    ['Baskı süresi', fmtMinutes(p.print_minutes)], ['Stok', h('b', null, t('{n} adet', { n: p.stock }))],
    ['Sipariş', t('{a} (tamamlanan {b})', { a: p.order_count, b: p.completed_count })])
    : p.role === 'section' ? dl(['Kod', h('span', { class: 'mono' }, p.code)], ['Ait olduğu', p.parent?.name || '—'],
      ['Parça', p.part_count], ['İçerik', Object.entries(p.groups).map(([g, n]) => `${g} ${n}`).join(' · ')])
      : p.role === 'sarf' ? dl(['Kod', h('span', { class: 'mono' }, p.code)], ['Bir baskıda', t('{n} adet', { n: p.per_print })],
        ['CAYMAZ başına', t('{n} adet', { n: num(p.usages.reduce((a, u) => a + u.qty, 0)) })],
        ['Kullanım', p.usages.map(u => `${u.parent_name} ${num(u.qty)}`).join(' · ') || '—'],
        ['Stok', h('b', null, t('{n} adet', { n: p.stock }))], ['Sipariş', t('{a} (tamamlanan {b})', { a: p.order_count, b: p.completed_count })])
        : p.role === 'mamul' ? dl(['Seri no', h('span', { class: 'mono' }, p.serial)], ['Ürün kodu', h('span', { class: 'mono' }, p.code)],
          ['Parça', p.part_count], ['Kullanım', p.usage_type === 'COKLU' ? 'Çoklu kullanım' : 'Tek kullanımlık'],
          ['Sipariş', t('{a} (üretimde {b}, tamamlanan {c})', { a: p.order_count, b: p.wip_count, c: p.completed_count })])
          : MATERIAL_TYPES.includes(p.type) ? dl(['Kod', h('span', { class: 'mono' }, p.code)], ['Birim', p.unit || 'adet'],
            ['Reçetelerde', t('{n} üründe', { n: p.used_in_recipes?.length || 0 })])
            : dl(['Kod', h('span', { class: 'mono' }, p.code)], ['Ürün ağacı', t('{n} alt ürün', { n: p.bom_count })],
              ['Reçete', t('{n} kalem', { n: p.recipe_count })], ['Kullanıldığı', usedIn]);
  return h('a', { class: `card product-card ${cls}`, href: `#/products/${p.id}` },
    h('div', { class: `product-preview ${p.image || p.gcode_preview ? 'g3d' : ''}` }, preview),
    h('div', { class: 'product-info' },
      h('div', { class: 'top' }, h('b', null, p.name), h('span', { class: 'grow' }), typeTag(p.type),
        p.active ? h('span', { class: 'badge green' }, 'Aktif') : h('span', { class: 'badge gray' }, 'Pasif')),
      !p.orderable && ['MAMUL', 'YARI_MAMUL'].includes(p.type) ? h('div', { class: 'small muted', style: { marginTop: '-4px', marginBottom: '6px' } }, 'Sipariş verilmez') : null,
      info));
}

// "Yeni" açılır düğmesi: tip seçilir, kod / ad / tip penceresi açılır; kaydedilince ürün sayfasına gidilir
function newButton() {
  const menu = h('div', { class: 'dropdown new-menu', hidden: true },
    Object.entries(TYPE_LABELS).map(([t, label]) => h('button', { type: 'button', onclick: () => { menu.hidden = true; createModal(t); } },
      typeTag(t), label)));
  const btn = h('button', { class: 'btn primary', type: 'button', 'aria-haspopup': 'menu' }, '＋ Yeni ', h('span', { class: 'caret' }, '▾'));
  const wrap = h('div', { class: 'new-wrap' }, btn, menu);
  btn.addEventListener('click', e => { e.stopPropagation(); menu.hidden = !menu.hidden; });
  const outside = e => { if (!wrap.contains(e.target)) menu.hidden = true; };
  document.addEventListener('click', outside);
  onLeave(() => document.removeEventListener('click', outside));
  return wrap;
}

// Yeni ürün penceresi. stay: sayfadan ayrılmadan oluştur (ör. reçete seçiminden); oluşturulan ürünü döner
export function createModal(type = 'MAMUL', { stay = false, types = Object.keys(TYPE_LABELS) } = {}) {
  return new Promise(resolve => {
    const code = h('input', { class: 'input mono', placeholder: 'ör. KNT-01', maxlength: 24, style: { textTransform: 'uppercase' } });
    const name = h('input', { class: 'input', placeholder: 'ör. Kanat Grubu', maxlength: 200 });
    const kind = h('select', { class: 'input' }, types.map(t => h('option', { value: t, selected: t === type }, TYPE_LABELS[t])));
    const unit = h('select', { class: 'input' }, UNITS.map(u => h('option', { value: u }, u)));
    const unitField = field('Birim', unit, 'Reçetede miktar bu birimle girilir');
    const sync = () => {
      const t = kind.value;
      unitField.hidden = !MATERIAL_TYPES.includes(t);
      code.placeholder = t === 'HAMMADDE' ? 'ör. HM-PLA' : t === 'YEDEK_PARCA' ? 'ör. VD-M3' : 'ör. KNT-01';
      name.placeholder = t === 'HAMMADDE' ? 'ör. PLA Filament' : t === 'YEDEK_PARCA' ? 'ör. M3 Vida' : 'ör. Kanat Grubu';
    };
    kind.addEventListener('change', sync);
    sync();
    let created = null;
    modal({
      title: 'Yeni ürün',
      body: h('div', null,
        field('Parça / Mamul Kodu', code), field('Parça / Mamul Adı', name), field('Tipi', kind), unitField),
      onClose: () => resolve(created),
      actions: [{ label: 'Vazgeç' }, {
        label: 'Kaydet', class: 'primary', onClick: async () => {
          const body = { code: code.value.trim(), name: name.value.trim(), type: kind.value, unit: MATERIAL_TYPES.includes(kind.value) ? unit.value : null };
          const { id } = await api.post('/api/products', body);
          created = { id, ...body, code: body.code.toUpperCase() };
          toast('Ürün eklendi');
          if (!stay) location.hash = `#/products/${id}`;
        },
      }],
    });
    code.focus();
  });
}

// G-code dosyası: dilimleyici bilgileri, önizleme resmi ve indirme
function gcodeCard(p) {
  let m = {};
  try { m = JSON.parse(p.gcode_meta || '{}'); } catch { /* yok */ }
  const name = p.gcode_file.split('/').pop();
  const hms = s => (s ? t('{h} sa {m} dk', { h: Math.floor(s / 3600), m: Math.round((s % 3600) / 60) }) : '—');
  const row = (k, v) => (v == null || v === '' ? null : [h('dt', null, k), h('dd', null, v)]);
  return h('div', { class: 'gcode-card' },
    h('div', { class: 'gcode-head' }, p.gcode_thumb ? h('img', { src: fileUrl(p.gcode_thumb), alt: '' }) : null,
      h('div', null, h('b', { class: 'mono', style: { wordBreak: 'break-all' } }, name), h('div', { class: 'small muted' }, m.size ? `${(m.size / 1048576).toFixed(1)} MB` : ''))),
    h('dl', { class: 'sys-kv' },
      row('Tahmini süre', hms(m.seconds)), row('Filament', m.filament_g ? `${m.filament_g.toFixed(0)} g · ${(m.filament_mm / 1000).toFixed(1)} m` : null),
      row('Malzeme', [m.material, m.filament_profile].filter(Boolean).join(' · ')), row('Maliyet', m.cost ? `${m.cost.toFixed(2)}` : null),
      row('Katman', m.layers ? `${m.layers} × ${m.layer_height} mm` : null), row('Yükseklik', m.max_z ? `${m.max_z} mm` : null),
      row('Sıcaklık', m.nozzle_temp ? t('Nozül {temp}°C{bed}', { temp: m.nozzle_temp, bed: m.bed_temp ? t(' · Tabla {bt}°C', { bt: m.bed_temp }) : '' }) : null),
      row('Yazıcı', [m.printer, m.nozzle ? t('{n} mm nozül', { n: m.nozzle }) : null].filter(Boolean).join(' · ')), row('Dilimleyici', m.slicer)),
    h('a', { class: 'btn', href: fileUrl(p.gcode_file), download: name }, '⬇ G-code İndir'));
}

const reload = () => window.dispatchEvent(new HashChangeEvent('hashchange'));

async function renderDetail(view, id, ctx) {
  const p = await api.get(`/api/products/${id}`);
  const canEdit = ctx.user.modules.includes('products');
  const custom = p.role === 'custom', stocked = !!p.stocked, section = p.role === 'section';
  const partSpare = !!p.part_spare;
  const locked = p.order_count > 0 || partSpare;   // parça yedeğinin kodu parça kodudur
  const f = {
    code: h('input', { class: 'input mono', value: p.code, disabled: locked }),
    name: h('input', { class: 'input', value: p.name }),
    type: h('select', { class: 'input', disabled: !custom }, Object.entries(TYPE_LABELS).map(([v, l]) => h('option', { value: v, selected: v === p.type }, l))),
    unit: h('select', { class: 'input' }, UNITS.map(u => h('option', { value: u, selected: u === (p.unit || 'adet') }, u))),
    serial: h('input', { class: 'input mono', value: p.serial }),
    prefix: h('input', { class: 'input mono', value: p.queue_prefix, disabled: locked }),
    desc: h('textarea', { class: 'input', rows: 2 }, p.description || ''),
    active: h('input', { type: 'checkbox', checked: !!p.active }),
    orderable: h('input', { type: 'checkbox', checked: !!p.orderable, disabled: section }),
    usage: h('select', { class: 'input' }, [['TEK', 'Tek kullanımlık (uçunca hurda)'], ['COKLU', 'Çoklu kullanım']]
      .map(([v, l]) => h('option', { value: v, selected: (p.usage_type || 'TEK') === v }, l))),
  };
  const perPrint = h('input', { class: 'input', type: 'number', min: 1, value: p.per_print });
  const printFile = h('input', { class: 'input mono', value: p.print_file || '', placeholder: 'ör. c5- sol - part 1_ABS_9h16m' });
  const printH = h('input', { class: 'input', type: 'number', min: 0, max: 336, value: p.print_minutes ? Math.floor(p.print_minutes / 60) : '' });
  const printM = h('input', { class: 'input', type: 'number', min: 0, max: 59, value: p.print_minutes ? p.print_minutes % 60 : '' });
  // Custom MAMUL/YARI_MAMUL: 'Basılıp stokta tutulur' → yerleşik sarf gibi (baskı alanları + kuyruk öneki + stok)
  const printable = custom && ['MAMUL', 'YARI_MAMUL'].includes(p.type);
  f.printed = h('input', { type: 'checkbox', checked: !!p.printed });
  const prefixField = field('Kuyruk öneki', f.prefix);
  const perPrintField = field('Bir baskıda üretilen adet', perPrint);
  const printFileField = field('Baskı dosyası (yazıcıya verilen)', printFile);
  const printTimeField = h('div', { class: 'row' }, field('Baskı süresi (saat)', printH), field('(dakika)', printM));
  const showPrint = () => stocked || (printable && f.printed.checked);
  const refreshPrint = () => {
    if (custom) { prefixField.hidden = !f.printed.checked; f.prefix.disabled = locked || !f.printed.checked; }
    perPrintField.hidden = printFileField.hidden = printTimeField.hidden = !showPrint();
  };
  f.printed.addEventListener('change', refreshPrint);
  if (printable) f.type.addEventListener('change', () => { if (!['MAMUL', 'YARI_MAMUL'].includes(f.type.value)) { f.printed.checked = false; } refreshPrint(); });
  refreshPrint();
  const unitField = field('Birim', f.unit);
  const usageField = field('Kullanım durumu', f.usage, 'Tek kullanımlık uçak uçtuktan sonra HURDA olur ve yeniden sahaya gidemez');
  const syncType = () => {
    unitField.hidden = !MATERIAL_TYPES.includes(f.type.value);
    usageField.hidden = f.type.value !== 'MAMUL';
  };
  f.type.addEventListener('change', syncType);
  syncType();
  const save = h('button', { class: 'btn primary' }, 'Kaydet');
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api.put(`/api/products/${id}`, {
        name: f.name.value, serial: custom ? f.code.value : f.serial.value, code: f.code.value, queue_prefix: f.prefix.value,
        description: f.desc.value.trim() || null, active: f.active.checked,
        ...(custom ? { type: f.type.value } : {}),
        ...((!custom || ['MAMUL', 'YARI_MAMUL'].includes(f.type.value)) ? { orderable: f.orderable.checked } : {}),
        ...(printable ? { printed: f.printed.checked } : {}),
        ...(MATERIAL_TYPES.includes(f.type.value) ? { unit: f.unit.value } : {}),
        ...(f.type.value === 'MAMUL' ? { usage_type: f.usage.value } : {}),
        ...(showPrint() ? { per_print: Number(perPrint.value), print_file: printFile.value.trim() || null,
          print_minutes: (Number(printH.value) || 0) * 60 + (Number(printM.value) || 0) || null } : {}),
      });
      toast('Ürün bilgileri kaydedildi');
      reload();
    } catch (err) {
      toastError(err);
    } finally {
      save.disabled = false;
    }
  });
  const del = custom && canEdit ? h('button', { class: 'btn ghost danger-text', onclick: async () => {
    if (!await confirmDialog('Ürünü sil', t('{code} — {name} silinsin mi? Ürün ağacı ve reçete bağlantıları da kaldırılır.', { code: p.code, name: p.name }), { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/products/${id}`); toast('Ürün silindi'); location.hash = '#/products'; } catch (err) { toastError(err); }
  } }, 'Sil') : null;

  // Üst: girilen bilgiler (kod, ad, tip ve ürüne göre diğer ayarlar)
  const infoCard = h('div', { class: 'card card-pad pd-info' },
    h('h3', null, 'Ürün Bilgileri'),
    h('div', { class: 'pd-info-grid' },
      field('Parça / Mamul Kodu', f.code), field('Parça / Mamul Adı', f.name), field('Tipi', f.type), unitField,
      custom ? null : field('Seri numarası', f.serial), prefixField,
      perPrintField, printFileField, printTimeField,
      usageField),
    field('Açıklama', f.desc),
    locked ? h('div', { class: 'small muted', style: { marginBottom: '8px' } },
      partSpare ? 'Parça yedeğinin kodu, uçaktaki parça kodudur; değiştirilemez.' : 'Siparişi olan ürünün kodu değiştirilemez.') : null,
    h('div', { class: 'pd-info-foot' },
      h('label', { class: 'check' }, f.active, 'Aktif'),
      (custom && !['MAMUL', 'YARI_MAMUL'].includes(p.type))
        ? h('span', { class: 'small muted' }, 'Ürün ağacı ve reçeteyle tanımlı; üretim siparişi açılmaz')
        : h('label', { class: 'check', title: 'İşaretlenirse bu ürün için üretim siparişi / iş emri açılabilir' }, f.orderable, 'Sipariş verilebilir (iş emri açılabilir)'),
      printable ? h('label', { class: 'check', title: 'İşaretlenirse bu ürün yazıcıda basılıp stokta tutulur; baskı alanları ve stok açılır (yerleşik yedek parçalar gibi)' }, f.printed, 'Basılıp stokta tutulur') : null,
      section ? h('span', { class: 'small muted' }, t('Montajda {name} siparişiyle birleştirilir', { name: p.parent?.name || 'mamul' })) : null,
      h('span', { class: 'spacer' }), del, canEdit ? save : null));

  const sideCard = h('div', { class: 'card card-pad pd-side' },
    stocked ? [
      h('h3', null, 'Stok'),
      h('div', { class: 'spare-stock' }, h('b', null, p.stock), h('span', null, 'adet stokta')),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '8px', margin: '10px 0' } },
        h('button', { class: 'btn sm', onclick: () => spareMovesModal(p) }, 'Stok hareketleri'),
        h('button', { class: 'btn sm', onclick: () => spareAdjustModal(p) }, 'Sayım düzeltmesi')),
    ] : null,
    h('h3', null, 'Kullanıldığı yerler'),
    p.used_in?.length || p.used_in_recipes?.length
      ? h('ul', { class: 'stat-list' },
        (p.used_in || []).map(x => h('li', null, h('a', { href: `#/products/${x.id}` }, `${x.code} — ${x.name}`), h('b', null, `×${num(x.qty)}`))),
        (p.used_in_recipes || []).map(x => h('li', null, h('a', { href: `#/products/${x.id}` }, `${x.code} — ${x.name}`), h('b', null, `${num(x.qty)} ${p.unit || ''}`))))
      : h('div', { class: 'small muted' }, 'Başka bir ürünün ağacında ya da reçetesinde yok'),
    p.order_count ? h('div', { class: 'small muted', style: { marginTop: '10px' } }, t('{a} sipariş · üretimde {b} · tamamlanan {c}', { a: p.order_count, b: p.wip_count, c: p.completed_count })) : null);

  // Alt modüller
  const tabs = MATERIAL_TYPES.includes(p.type) ? [['image', 'Resim'], ['3d', '3B']] : [['tree', 'Ürün Ağacı'], ['recipe', 'Reçete'], ['image', 'Resim'], ['3d', '3B']];
  let tab = pref('products.tab', 'tree');
  if (!tabs.some(t => t[0] === tab)) tab = tabs[0][0];
  const stage = h('div', { class: 'pd-stage' });
  let cleanup = null;
  onLeave(() => cleanup?.());
  const show = async () => {
    cleanup?.(); cleanup = null;
    clear(stage, h('div', { class: 'card card-pad loading' }, 'Yükleniyor…'));
    try {
      if (tab === 'tree') await treeTab(stage, p, canEdit);
      else if (tab === 'recipe') await recipeTab(stage, p, canEdit);
      else if (tab === 'image') await imageTab(stage, p, canEdit);
      else if (p.type === 'MAMUL' && ['caymaz', 'caymaz-v2', 'caymaz-v3', 'caymaz-v4'].includes(p.schema)) cleanup = assemblyTab(stage, p, canEdit);   // uçak: 3B montaj
      else cleanup = await gcodeTab(stage, p, canEdit);
    } catch (err) {
      clear(stage, h('div', { class: 'card empty' }, err.message));
    }
  };
  const seg = segmented(tabs, tab, v => { tab = v; setPref('products.tab', v); show(); }, { tabs: true });

  clear(view,
    pageHead(p.name, { back: '#/products', sub: `${p.code} · ${TYPE_LABELS[p.type] || p.type}${custom ? '' : ` · ${p.schema_title}`}`, right: h('div', { class: 'head-right' }, typeTag(p.type)) }),
    h('div', { class: 'pd-top' }, infoCard, sideCard),
    h('div', { class: 'pd-tabs' }, seg),
    stage);
  show();
}

// ---------- Ürün Ağacı: iç içe yarı mamuller (Treeview)
async function treeTab(stage, p, canEdit) {
  const [tree, options] = await Promise.all([api.get(`/api/products/${p.id}/tree`), api.get('/api/products/options')]);
  const open = new Set(JSON.parse(sessionStorage.getItem(`ptree.${p.id}`) || 'null') || [String(p.id)]);
  const remember = () => { try { sessionStorage.setItem(`ptree.${p.id}`, JSON.stringify([...open])); } catch { /* yok */ } };
  const refresh = () => treeTab(stage, p, canEdit).catch(toastError);
  const canHold = t => t === 'MAMUL' || t === 'YARI_MAMUL';
  const addUnder = node => pickModal({
    title: t('{code} altına yarı mamul ekle', { code: node.code }), options: options.filter(o => o.type === 'YARI_MAMUL' && o.id !== node.id && !node.children.some(c => c.id === o.id)),
    newType: 'YARI_MAMUL', qtyLabel: 'Adet', unitOf: () => 'adet',
    onPick: async (item, qty) => { await api.post(`/api/products/${node.id}/bom`, { child_id: item.id, qty }); open.add(`${node.path}`); remember(); toast('Ürün ağacına eklendi'); refresh(); },
  });
  const editQty = (parent, node) => qtyModal(t('{p} içinde {c} adedi', { p: parent.code, c: node.code }), node.qty, 'adet', async qty => {
    await api.put(`/api/products/${parent.id}/bom/${node.id}`, { qty }); refresh();
  });
  const remove = async (parent, node) => {
    if (!await confirmDialog('Ağaçtan çıkar', t('{code} — {name}, {parent} ağacından çıkarılsın mı? Ürünün kendisi silinmez.', { code: node.code, name: node.name, parent: parent.code }), { okLabel: 'Çıkar', danger: true })) return;
    try { await api.del(`/api/products/${parent.id}/bom/${node.id}`); toast('Ağaçtan çıkarıldı'); refresh(); } catch (err) { toastError(err); }
  };
  let rows = 0;
  const row = (node, parent, depth, path) => {
    node.path = path;
    rows++;
    const has = node.children.length > 0;
    const isOpen = open.has(path);
    const kids = h('div', { class: 'tv-kids', hidden: !isOpen });
    const caret = h('button', { class: `tv-caret ${has ? '' : 'none'} ${isOpen ? 'open' : ''}`, type: 'button', 'aria-label': 'Aç / kapat' }, has ? '▸' : '');
    caret.addEventListener('click', () => {
      if (!has) return;
      kids.hidden = !kids.hidden;
      caret.classList.toggle('open', !kids.hidden);
      if (kids.hidden) open.delete(path); else open.add(path);
      if (!kids.hidden && !kids.childElementCount) kids.append(...node.children.map(c => row(c, node, depth + 1, `${path}/${c.id}`)));
      remember();
    });
    if (isOpen) kids.append(...node.children.map(c => row(c, node, depth + 1, `${path}/${c.id}`)));
    const meta = [
      node.children.length ? h('span', { class: 'tv-meta' }, t('{n} alt', { n: node.children.length })) : null,
      node.recipe_count ? h('span', { class: 'tv-meta', title: 'Reçete kalemi' }, `🧾 ${node.recipe_count}`) : null,
      node.has_3d ? h('span', { class: 'tv-meta', title: '3B görünüm var' }, '3B') : null,
      node.stock != null ? h('span', { class: `tree-stock ${node.stock > 0 ? 'on' : ''}`, title: 'Stok' }, node.stock) : null,
    ];
    const actions = canEdit ? h('span', { class: 'tv-actions' },
      canHold(node.type) ? h('button', { class: 'btn xs', type: 'button', title: 'Altına yarı mamul ekle', onclick: () => addUnder(node) }, '＋') : null,
      parent ? h('button', { class: 'btn xs ghost', type: 'button', title: 'Çıkar', onclick: () => remove(parent, node) }, '✕') : null) : null;
    const qty = parent ? h(canEdit ? 'button' : 'span', { class: 'tv-qty', type: 'button', title: canEdit ? 'Adedi değiştir' : '', onclick: canEdit ? () => editQty(parent, node) : null }, `×${num(node.qty)}`) : null;
    return h('div', { class: 'tv-node' },
      h('div', { class: `tv-row ${parent ? '' : 'root'} ${node.active ? '' : 'passive'}`, style: { paddingLeft: `${depth * 22 + 6}px` } },
        caret, typeTag(node.type), h('a', { class: 'mono tv-code', href: `#/products/${node.id}` }, node.code), h('span', { class: 'tv-name' }, node.name),
        qty, h('span', { class: 'spacer' }), meta, actions),
      kids);
  };
  const expandAll = on => {
    const walk = (n, path) => { if (n.children.length) { if (on) open.add(path); else open.delete(path); } n.children.forEach(c => walk(c, `${path}/${c.id}`)); };
    walk(tree, String(tree.id));
    if (!on) open.add(String(tree.id));
    remember();
    refresh();
  };
  const body = row(tree, null, 0, String(tree.id));
  clear(stage, h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' },
      h('b', null, 'Ürün ağacı'), h('span', { class: 'small muted' }, 'İç içe yarı mamuller ve üst üründe kullanılan adet'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', onclick: () => expandAll(true) }, 'Tümünü aç'),
      h('button', { class: 'btn sm', onclick: () => expandAll(false) }, 'Tümünü kapat'),
      canEdit ? h('button', { class: 'btn sm primary', onclick: () => addUnder(tree) }, '＋ Yarı mamul ekle') : null),
    h('div', { class: 'tv' }, body),
    !tree.children.length ? h('div', { class: 'small muted', style: { padding: '10px 6px' } }, 'Henüz alt ürün yok. “Yarı mamul ekle” ile ekleyin; eklenen yarı mamulün de altına ekleme yapabilirsiniz.') : null,
    p.role !== 'custom' ? h('div', { class: 'small muted', style: { marginTop: '10px' } },
      'Uçak şemasındaki parçalar üretimde şemadan basılır; montaj sarfı (KMH, BBK, KBK) adetleri montajda stoktan düşülür.') : null));
  return rows;
}

// ---------- Reçete: yedek parça ve hammadde miktarları
async function recipeTab(stage, p, canEdit) {
  const [recipe, options] = await Promise.all([api.get(`/api/products/${p.id}/recipe`), api.get('/api/products/options')]);
  const refresh = () => recipeTab(stage, p, canEdit).catch(toastError);
  const add = () => pickModal({
    title: 'Reçeteye ekle', options: options.filter(o => ITEM_TYPES.includes(o.type)), newType: 'YEDEK_PARCA', newTypes: ITEM_TYPES,
    qtyLabel: 'Kullanılan miktar', unitOf: o => o.unit || 'adet', note: true,
    onPick: async (item, qty, note) => { await api.post(`/api/products/${p.id}/recipe`, { item_id: item.id, qty, note }); toast('Reçeteye eklendi'); refresh(); },
  });
  const edit = r => qtyModal(`${r.code} — ${r.name}`, r.qty, r.unit || 'adet', async (qty, note) => {
    await api.post(`/api/products/${p.id}/recipe`, { item_id: r.item_id, qty, note }); refresh();
  }, r.note);
  const remove = async r => {
    if (!await confirmDialog('Reçeteden çıkar', t('{code} — {name} reçeteden çıkarılsın mı?', { code: r.code, name: r.name }), { okLabel: 'Çıkar', danger: true })) return;
    try { await api.del(`/api/products/${p.id}/recipe/${r.item_id}`); refresh(); } catch (err) { toastError(err); }
  };
  const table = (list, editable) => h('table', { class: 'table' },
    h('thead', null, h('tr', null, h('th', null, 'Kod'), h('th', null, 'Ad'), h('th', null, 'Tip'), h('th', { class: 'num' }, 'Miktar'),
      editable ? h('th', null, 'Not') : null, editable && canEdit ? h('th', null, '') : null)),
    h('tbody', null, list.map(r => h('tr', null,
      h('td', { class: 'mono' }, h('a', { href: `#/products/${r.item_id}` }, r.code)), h('td', null, r.name), h('td', null, typeTag(r.type)),
      h('td', { class: 'num' }, h('b', null, num(r.qty)), ' ', h('span', { class: 'muted' }, r.unit || 'adet')),
      editable ? h('td', { class: 'small muted' }, r.note || '') : null,
      editable && canEdit ? h('td', { class: 'actions' },
        h('button', { class: 'btn xs', onclick: () => edit(r) }, 'Düzenle'),
        h('button', { class: 'btn xs ghost', onclick: () => remove(r) }, '✕')) : null))));
  const own = recipe.items.map(r => r.item_id).sort().join();
  const rolled = recipe.total.length && recipe.total.map(r => `${r.item_id}:${r.qty}`).sort().join() !== recipe.items.map(r => `${r.item_id}:${r.qty}`).sort().join();
  clear(stage,
    h('div', { class: 'card card-pad' },
      h('div', { class: 'tv-bar' }, h('b', null, 'Reçete'), h('span', { class: 'small muted' }, t('{name} için kullanılan yedek parça ve hammaddeler', { name: p.name })),
        h('span', { class: 'spacer' }), canEdit ? h('button', { class: 'btn sm primary', onclick: add }, '＋ Kalem ekle') : null),
      recipe.items.length ? table(recipe.items, true) : h('div', { class: 'empty small' }, 'Reçetede kalem yok')),
    rolled ? h('div', { class: 'card card-pad', style: { marginTop: '14px' } },
      h('div', { class: 'tv-bar' }, h('b', null, 'Toplam ihtiyaç'), h('span', { class: 'small muted' }, 'Ürün ağacındaki tüm alt ürünlerin reçeteleri, adetleriyle çarpılarak')),
      table(recipe.total, false)) : null);
  return own;
}

// ---------- Resim: 2B üstten görünüm (ve şemalı ürünlerde çizim)
async function imageTab(stage, p, canEdit) {
  const file = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,image/gif', hidden: true });
  const bar = h('div', { class: 'progress pd-progress', hidden: true }, h('i'));
  file.addEventListener('change', async () => {
    if (!file.files[0]) return;
    const fd = new FormData();
    fd.append('file', file.files[0]);
    bar.hidden = false;
    try {
      const res = await upload(`/api/products/${p.id}/image`, fd, pct => { bar.firstChild.style.width = `${pct}%`; });
      p.image = res.image;
      toast('Resim yüklendi');
      imageTab(stage, p, canEdit);
    } catch (err) { toastError(err); bar.hidden = true; }
  });
  const pick = () => file.click();
  const remove = async () => {
    if (!await confirmDialog('Resmi kaldır', 'Üstten görünüm resmi kaldırılsın mı?', { okLabel: 'Kaldır', danger: true })) return;
    try { await api.del(`/api/products/${p.id}/image`); p.image = null; imageTab(stage, p, canEdit); } catch (err) { toastError(err); }
  };
  const drop = el => {
    if (!canEdit) return el;
    el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('over'); });
    el.addEventListener('dragleave', () => el.classList.remove('over'));
    el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('over'); if (e.dataTransfer.files[0]) { file.files = e.dataTransfer.files; file.dispatchEvent(new Event('change')); } });
    return el;
  };
  const imgCard = h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' }, h('b', null, '2B üstten görünüm'), h('span', { class: 'spacer' }),
      canEdit && p.image ? [h('button', { class: 'btn sm', onclick: pick }, 'Değiştir'), h('button', { class: 'btn sm ghost', onclick: remove }, 'Kaldır')] : null),
    p.image
      ? drop(h('a', { class: 'pd-image', href: fileUrl(p.image), target: '_blank', rel: 'noopener' }, h('img', { src: fileUrl(p.image, 1600), alt: t('{name} üstten görünüm', { name: p.name }) })))
      : drop(h('div', { class: 'drop-zone', onclick: canEdit ? pick : null },
        h('div', { class: 'dz-ico' }, '🖼'), h('b', null, canEdit ? 'Üstten görünüm resmini yükleyin' : 'Resim yüklenmemiş'),
        canEdit ? h('span', { class: 'small muted' }, 'Tıklayın ya da resmi buraya sürükleyin · PNG, JPG, WEBP') : null)),
    bar, file);
  if (p.role === 'custom') return clear(stage, imgCard);
  // Şemalı ürün: parça çizimi (mamulde Mamul / Yarı mamul / Parça görünümleri)
  const [plane, tree] = await Promise.all([loadPlane(p.id), p.role === 'mamul' ? api.get(`/api/products/${p.id}/tree`).catch(() => null) : null]);
  const schemaStage = h('div', { class: 'card plane-stage' });
  const pl = renderPlane(plane, {
    fill: part => (part.group === 'cover' ? 'var(--cover-fill)' : 'var(--part-fill)'),
    tooltip: part => partInfoLines(part, plane.groups),
    onClick: tree ? part => goPart(tree, part.id) : undefined,
  });
  if (p.role === 'sarf') {   // tek parçalı çizim (KMH, MKHV2…): ayrı 'Şema çizimi' bölümü YOK; resim yüklenmemişse çizim 2B üstten görünüm kartında
    pl.setLayer(null);
    const dz = imgCard.querySelector('.drop-zone');
    if (dz) {
      dz.replaceWith(h('div', { class: 'pd-image pd-schema' }, pl.svg));
      if (canEdit) imgCard.querySelector('.tv-bar').append(h('button', { class: 'btn sm', onclick: pick }, 'Resim yükle'));
    }
    return clear(stage, imgCard);
  }
  if (!tree) {
    clear(schemaStage, p.role === 'mamul' ? layerToggle(pl, 'plane.layer', plane) : (pl.setLayer(null), null), pl.svg);
  } else {
    let mode = pref('products.treeView', 'YEDEK_PARCA');
    const draw = () => {
      const sw = segmented([['MAMUL', 'Mamul'], ['YARI_MAMUL', 'Yarı mamul'], ['YEDEK_PARCA', 'Parçalar']], mode,
        v => { mode = v; setPref('products.treeView', v); draw(); });
      const vb = h('div', { class: 'tree-view-bar' }, h('span', { class: 'small muted' }, 'Görünüm'), sw);
      if (mode === 'YEDEK_PARCA') return clear(schemaStage, vb, layerToggle(pl, 'plane.layer', plane), pl.svg);
      if (mode === 'MAMUL') {
        const a = renderAssembly(plane, { whole: true, items: { ALL: { state: 'info',
          label: [p.name, { text: 'Mamul', class: 'sub' }, { text: t('{serial} · {n} parça', { serial: p.serial, n: p.part_count }), class: 'muted' }] } } });
        return clear(schemaStage, vb, a.svg);
      }
      const semis = tree.children.filter(n => n.section);
      const bySection = Object.fromEntries(semis.map(n => [n.section, n]));
      const items = Object.fromEntries(semis.map(n => [n.section, { state: 'info',
        label: [n.name, { text: t('{code} · {n} parça', { code: n.code, n: n.children.filter(c => c.part_spare).length }), class: 'sub' }, { text: 'Açmak için tıklayın', class: 'muted' }] }]));
      const a = renderAssembly(plane, {
        whole: false, items,
        extra: { fill: () => 'var(--part-fill)', label: part => (part.name ? part.name.split(' ') : [part.id]),
          clickable: () => true, onClick: part => goPart(tree, part.id) },
        onElecClick: bySection.ELEKTRONIK ? () => { location.hash = `#/products/${bySection.ELEKTRONIK.id}`; } : null,
        onClick: key => { if (bySection[key]) location.hash = `#/products/${bySection[key].id}`; },
      });
      return clear(schemaStage, vb, a.svg);
    };
    draw();
  }
  clear(stage, imgCard, h('h3', { class: 'pd-sub' }, 'Şema çizimi'), schemaStage);
}

function goPart(tree, partId) {
  // Uçaktaki parça → parça yedeği ürün sayfası
  for (const semi of tree.children) for (const n of semi.children || []) {
    if (n.part_spare && (n.code === partId || n.code === `P-${partId}`)) { location.hash = `#/products/${n.id}`; return; }
  }
}

// ---------- 3B: G-code yükleme ve 3B görünüm
// 3B sekmesi; base: yükleme / kaldırma uçlarının kökü (MRP malzemeleri kendi yetkisiyle kullanır)
export async function gcodeTab(stage, p, canEdit, base = `/api/products/${p.id}`) {
  let v3 = null;
  const file = h('input', { type: 'file', accept: '.gcode', hidden: true });
  const bar = h('div', { class: 'progress pd-progress', hidden: true }, h('i'));
  const status = h('div', { class: 'small muted' });
  file.addEventListener('change', async () => {
    const f = file.files[0];
    if (!f) return;
    if (!/\.gcode$/i.test(f.name)) { toastError(new Error('Yalnızca .gcode dosyası yüklenebilir')); return; }
    bar.hidden = false;
    status.textContent = 'Yükleniyor…';
    try {
      const uid = await uploadLarge(f, 'gcode', pct => { bar.firstChild.style.width = `${pct}%`; status.textContent = t('Yükleniyor… %{p}', { p: pct }); });
      status.textContent = 'G-code işleniyor (bilgiler ve 3B yol çıkarılıyor)…';
      await api.post(`${base}/gcode`, { upload_id: uid });
      toast('G-code yüklendi');
      reload();
    } catch (err) { toastError(err); bar.hidden = true; status.textContent = ''; }
  });
  const pick = () => file.click();
  const remove = async () => {
    if (!await confirmDialog('G-code kaldır', 'G-code ve 3B görünüm bu üründen kaldırılsın mı?', { okLabel: 'Kaldır', danger: true })) return;
    try { await api.del(`${base}/gcode`); reload(); } catch (err) { toastError(err); }
  };
  const zone = h('div', { class: 'drop-zone', onclick: canEdit ? pick : null },
    h('div', { class: 'dz-ico' }, '⬡'), h('b', null, canEdit ? 'G-code dosyasını yükleyin' : 'G-code yüklenmemiş'),
    canEdit ? h('span', { class: 'small muted' }, 'Tıklayın ya da .gcode dosyasını buraya sürükleyin · yüklenince 3B olarak gösterilir') : null);
  if (canEdit) {
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('over'));
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('over'); if (e.dataTransfer.files[0]) { file.files = e.dataTransfer.files; file.dispatchEvent(new Event('change')); } });
  }
  if (!p.gcode_preview) {
    clear(stage, h('div', { class: 'card card-pad' }, h('div', { class: 'tv-bar' }, h('b', null, '3B görünüm')), zone, bar, status, file));
    return null;
  }
  const box = h('div', { class: 'g3d-view' });   // yükleme halkasını viewer gösterir
  clear(stage, h('div', { class: 'pd-3d' },
    h('div', { class: 'card card-pad' },
      h('div', { class: 'tv-bar' }, h('b', null, '3B görünüm'), h('span', { class: 'small muted' }, 'Fareyle döndürün, tekerlekle yakınlaştırın'),
        h('span', { class: 'spacer' }),
        canEdit ? [h('button', { class: 'btn sm', onclick: pick }, 'Yeni G-code yükle'), h('button', { class: 'btn sm ghost', onclick: remove }, 'Kaldır')] : null),
      box, bar, status, file),
    h('div', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Baskı dosyası (G-code)'), gcodeCard(p))));
  viewer(box, p.gcode_preview, { autoRotate: true }).then(v => { v3 = v; }).catch(err => clear(box, h('div', { class: 'empty small' }, err.message)));
  return () => v3?.destroy();
}

// ---------- Seçim pencereleri
// Aranabilir ürün listesinden seçim + miktar; listede yoksa yeni tanımlanabilir
function pickModal({ title, options, newType, newTypes, qtyLabel, unitOf, note = false, onPick }) {
  let chosen = null;
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kod ya da ad ara…' });
  const list = h('div', { class: 'pick-list' });
  const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value: 1, style: { width: '140px' } });
  const unit = h('span', { class: 'muted' }, '');
  const noteIn = h('input', { class: 'input', placeholder: 'Not (isteğe bağlı)', maxlength: 200 });
  const draw = () => {
    const shown = options.filter(o => matches(q.value, o.code, o.name)).slice(0, 200);
    clear(list, shown.length ? shown.map(o => h('button', { type: 'button', class: `pick-item ${chosen?.id === o.id ? 'on' : ''} ${o.active ? '' : 'passive'}`,
      onclick: () => { chosen = o; unit.textContent = unitOf(o); draw(); } },
    typeTag(o.type), h('span', { class: 'mono' }, o.code), h('span', { class: 'grow' }, o.name), o.unit ? h('span', { class: 'small muted' }, o.unit) : null))
      : h('div', { class: 'empty small' }, 'Eşleşen ürün yok'));
  };
  q.addEventListener('input', draw);
  const createNew = h('button', { type: 'button', class: 'link-btn' }, '＋ Listede yok, yeni tanımla');
  createNew.addEventListener('click', async () => {
    const made = await createModal(newType, { stay: true, types: newTypes || [newType] });
    if (!made) return;
    const o = { id: made.id, code: made.code, name: made.name, type: made.type, unit: made.unit, active: 1 };
    options.unshift(o);
    chosen = o; unit.textContent = unitOf(o); q.value = ''; draw();
  });
  draw();
  modal({
    title, wide: true,
    body: h('div', null, q, list, createNew,
      h('div', { class: 'pick-qty' }, field(qtyLabel, h('div', { class: 'row-inline' }, qty, unit)), note ? field('Not', noteIn) : null)),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Ekle', class: 'primary', onClick: async () => {
        if (!chosen) throw new Error('Listeden bir ürün seçin');
        const v = Number(qty.value);
        if (!(v > 0)) throw new Error('Miktar 0’dan büyük olmalı');
        await onPick(chosen, v, noteIn.value.trim() || null);
      },
    }],
  });
  q.focus();
}

function qtyModal(title, value, unit, onSave, noteValue) {
  const qty = h('input', { class: 'input', type: 'number', min: 0, step: 'any', value, style: { width: '160px' } });
  const noteIn = noteValue !== undefined ? h('input', { class: 'input', value: noteValue || '', maxlength: 200 }) : null;
  modal({
    title,
    body: h('div', null, field('Miktar', h('div', { class: 'row-inline' }, qty, h('span', { class: 'muted' }, unit))), noteIn ? field('Not', noteIn) : null),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Kaydet', class: 'primary', onClick: async () => {
        const v = Number(qty.value);
        if (!(v > 0)) throw new Error('Miktar 0’dan büyük olmalı');
        await onSave(v, noteIn ? noteIn.value.trim() || null : undefined);
      },
    }],
  });
  qty.select();
}


// Mamul (uçak): parçaların G-code'larından 3B montaj; yetkili kullanıcı parçaları elle çevirip taşıyıp kaydedebilir
function assemblyTab(stage, p, canEdit) {
  const host = h('div');
  clear(stage, h('div', { class: 'card card-pad' },
    h('div', { class: 'tv-bar' }, h('b', null, '3B montaj'),
      h('span', { class: 'small muted' }, canEdit ? 'Parçalar G-code dosyalarından birleştirilir. “Düzenle” ile yerine oturmayan parçaları elle çevirip taşıyabilirsiniz; kayıt tüm siparişlerdeki 3B Montaj’a yansır.'
        : 'Parçalar G-code dosyalarından birleştirilir.')),
    host));
  const v = mountAssembly(host, { schema: p.schema, editable: canEdit });
  return () => v.destroy();
}

