// Ürün Yönetimi: ürün tipleri, seri numaraları ve parça şemaları.
// Yeni ürün tipi (yeni uçak şeması) yazılım tarafında eklenir; burada ürün bilgileri düzenlenir ve şema incelenir.
import { api } from '../api.js';
import { layerToggle, loadPlane, partInfoLines, renderAssembly, renderPlane } from '../plane.js';
import { clear, field, fmtDateTime, fmtMinutes, h, matches, pageHead, pref, segmented, selectInput, setPref, statStrip, toast, toastError } from '../ui.js';
import { spareMovesModal, spareAdjustModal } from './stock.js';

const TYPE_LABELS = { MAMUL: 'Mamul', YARI_MAMUL: 'Yarı mamul', YEDEK_PARCA: 'Yedek parça' };

export async function render(view, params, ctx) {
  if (params[0]) return renderDetail(view, Number(params[0]), ctx);
  const ORDER = { MAMUL: 0, YARI_MAMUL: 1, YEDEK_PARCA: 2 };
  const products = (await api.get('/api/products')).sort((a, b) => (ORDER[a.type] ?? 9) - (ORDER[b.type] ?? 9) || a.id - b.id);
  const planes = await Promise.all(products.map(p => loadPlane(p.id)));
  const sum = k => products.reduce((a, p) => a + (p[k] || 0), 0);
  const stats = statStrip();
  stats.set([
    { label: 'Mamul', value: products.filter(p => p.type === 'MAMUL').length },
    { label: 'Yarı mamul', value: products.filter(p => p.type === 'YARI_MAMUL').length },
    { label: 'Yedek parça', value: products.filter(p => p.type === 'YEDEK_PARCA').length },
    { label: 'Aktif ürün', value: products.filter(p => p.active).length, tone: 'ok' },
    { label: 'Toplam sipariş', value: sum('order_count') },
    { label: 'Üretimdeki sipariş', value: sum('wip_count') },
    { label: 'Tamamlanan uçak', value: sum('completed_count') },
  ]);
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Ürün adı, seri no, kod ara…', style: { width: '240px' } });
  const act = selectInput([['1', 'Aktif'], ['0', 'Pasif']], { all: 'Aktif ve pasif' });
  const cards = products.map((p, i) => {
    const preview = renderPlane(planes[i], { fill: () => 'var(--part-fill)', label: () => null });
    const spare = p.type === 'YEDEK_PARCA', semi = p.type === 'YARI_MAMUL';
    const cls = spare ? 'spare' : semi ? 'semi' : 'mamul';
    const card = h('a', { class: `card product-card ${cls}`, href: `#/products/${p.id}` },
      h('div', { class: 'product-preview' }, preview.svg),
      h('div', { class: 'product-info' },
        h('div', { class: 'top' }, h('b', null, p.name), h('span', { class: 'grow' }),
          h('span', { class: `type-tag ${cls}` }, TYPE_LABELS[p.type] || 'Mamul'),
          p.active ? h('span', { class: 'badge green' }, 'Aktif') : h('span', { class: 'badge gray' }, 'Pasif')),
        !p.orderable ? h('div', { class: 'small muted', style: { marginTop: '-4px', marginBottom: '6px' } }, 'Sipariş verilmez') : null,
        p.part_spare ? h('dl', null,
          h('dt', null, 'Kod'), h('dd', { class: 'mono' }, p.code),
          h('dt', null, 'Ait olduğu'), h('dd', null, p.used_in?.length ? p.used_in.map(x => x.name).join(', ') : p.parent ? `${p.parent.name} (yarı mamul)` : '—'),
          h('dt', null, 'Baskı süresi'), h('dd', null, fmtMinutes(p.print_minutes)),
          h('dt', null, 'Stok'), h('dd', null, h('b', null, `${p.stock} adet`)),
          h('dt', null, 'Sipariş'), h('dd', null, `${p.order_count} (tamamlanan ${p.completed_count})`))
        : semi ? h('dl', null,
          h('dt', null, 'Kod'), h('dd', { class: 'mono' }, p.code),
          h('dt', null, 'Ait olduğu'), h('dd', null, p.parent?.name || '—'),
          h('dt', null, 'Parça'), h('dd', null, p.part_count),
          h('dt', null, 'İçerik'), h('dd', null, Object.entries(p.groups).map(([g, n]) => `${g} ${n}`).join(' · ')))
        : spare ? h('dl', null,
          h('dt', null, 'Kod'), h('dd', { class: 'mono' }, p.code),
          h('dt', null, 'Bir baskıda'), h('dd', null, `${p.per_print} adet`),
          h('dt', null, 'CAYMAZ başına'), h('dd', null, `${p.usages.reduce((a, u) => a + u.qty, 0)} adet`),
          h('dt', null, 'Kullanım'), h('dd', null, p.usages.map(u => `${u.parent_name} ${u.qty}`).join(' · ') || '—'),
          h('dt', null, 'Stok'), h('dd', null, h('b', null, `${p.stock} adet`)),
          h('dt', null, 'Sipariş'), h('dd', null, `${p.order_count} (tamamlanan ${p.completed_count})`))
        : h('dl', null,
          h('dt', null, 'Seri no'), h('dd', { class: 'mono' }, p.serial),
          h('dt', null, 'Ürün kodu'), h('dd', { class: 'mono' }, p.code),
          h('dt', null, 'Parça'), h('dd', null, p.part_count),
          h('dt', null, 'Kullanım'), h('dd', null, p.usage_type === 'COKLU' ? 'Çoklu kullanım' : 'Tek kullanımlık'),
          h('dt', null, 'Sipariş'), h('dd', null, `${p.order_count} (üretimde ${p.wip_count}, tamamlanan ${p.completed_count})`))));
    return [p, card];
  });
  const empty = h('div', { class: 'card empty', hidden: true }, 'Filtreye uyan ürün yok');
  const kind = selectInput(Object.entries(TYPE_LABELS), { all: 'Tüm ürün tipleri', value: 'MAMUL' });   // varsayılan: mamuller
  const draw = () => {
    let shown = 0;
    for (const [p, card] of cards) {
      const ok = (!act.value || String(p.active) === act.value) && (!kind.value || kind.value === (p.type || 'MAMUL'))
        && matches(q.value, p.name, p.serial, p.code, p.description);
      card.hidden = !ok;
      shown += ok;
    }
    empty.hidden = shown > 0;
  };
  kind.addEventListener('change', draw);
  q.addEventListener('input', draw);
  act.addEventListener('change', draw);
  clear(view,
    pageHead('Ürün Yönetimi', { back: '#/', sub: 'Üretilen ürün tipleri ve parça şemaları', right: h('div', { class: 'head-right' }, q, kind, act) }),
    stats,
    h('div', { class: 'grid-cards product-grid' }, cards.map(c => c[1])),
    empty);
  draw();
}

async function renderDetail(view, id, ctx) {
  const [p, plane] = await Promise.all([api.get(`/api/products/${id}`), loadPlane(id)]);
  const mamul = p.type === 'MAMUL', spare = p.type === 'YEDEK_PARCA', semi = p.type === 'YARI_MAMUL';
  const partSpare = !!p.part_spare;
  const tree = mamul ? await api.get(`/api/products/${id}/tree`).catch(() => null) : null;
  const locked = p.order_count > 0 || partSpare;   // parça yedeğinin kodu parça kodudur
  const f = {
    name: h('input', { class: 'input', value: p.name }),
    serial: h('input', { class: 'input mono', value: p.serial }),
    code: h('input', { class: 'input mono', value: p.code, disabled: locked }),
    prefix: h('input', { class: 'input mono', value: p.queue_prefix, disabled: locked }),
    desc: h('textarea', { class: 'input', rows: 3 }, p.description || ''),
    active: h('input', { type: 'checkbox', checked: !!p.active }),
    orderable: h('input', { type: 'checkbox', checked: !!p.orderable, disabled: semi }),
    usage: h('select', { class: 'input' }, [['TEK', 'Tek kullanımlık (uçunca hurda)'], ['COKLU', 'Çoklu kullanım']]
      .map(([v, l]) => h('option', { value: v, selected: (p.usage_type || 'TEK') === v }, l))),
  };
  const perPrint = h('input', { class: 'input', type: 'number', min: 1, value: p.per_print });
  // Baskı dosyası (yazıcıya verilen gcode adı) ve bir baskının süresi
  const printFile = h('input', { class: 'input mono', value: p.print_file || '', placeholder: 'ör. c5- sol - part 1_ABS_9h16m' });
  const printH = h('input', { class: 'input', type: 'number', min: 0, max: 336, value: p.print_minutes ? Math.floor(p.print_minutes / 60) : '' });
  const printM = h('input', { class: 'input', type: 'number', min: 0, max: 59, value: p.print_minutes ? p.print_minutes % 60 : '' });
  // Montaj sarfı yedek parça: yarı mamul başına kullanılan adet (CAYMAZ başına = toplam)
  const usageInputs = (p.semi_options || []).map(sm => [sm, h('input', { class: 'input', type: 'number', min: 0,
    value: p.usages?.find(u => u.parent_id === sm.id)?.qty || 0 })]);
  const usageTotal = h('b');
  const syncTotal = () => { usageTotal.textContent = `${usageInputs.reduce((a, [, i]) => a + (Number(i.value) || 0), 0)} adet`; };
  usageInputs.forEach(([, i]) => i.addEventListener('input', syncTotal));
  syncTotal();
  const save = h('button', { class: 'btn primary' }, 'Kaydet');
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      await api.put(`/api/products/${id}`, {
        name: f.name.value, serial: f.serial.value, code: f.code.value, queue_prefix: f.prefix.value,
        description: f.desc.value.trim() || null, active: f.active.checked, orderable: f.orderable.checked,
        ...(mamul ? { usage_type: f.usage.value } : {}),
        ...(spare ? { per_print: Number(perPrint.value), print_file: printFile.value.trim() || null,
          print_minutes: (Number(printH.value) || 0) * 60 + (Number(printM.value) || 0) || null, ...(partSpare ? {} : { usages: Object.fromEntries(usageInputs.map(([sm, i]) => [sm.id, Number(i.value) || 0])) }) } : {}),
      });
      toast('Ürün bilgileri kaydedildi');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    } catch (err) {
      toastError(err);
    } finally {
      save.disabled = false;
    }
  });

  const groups = Object.entries(plane.groups).map(([g, label]) => {
    const parts = plane.parts.filter(x => x.group === g);
    return parts.length ? h('div', { class: 'part-group' }, h('h3', null, `${label} (${parts.length})`),
      h('div', { class: 'chips', style: { justifyContent: 'flex-start' } }, parts.map(x => h('span', { class: 'chip mono' }, x.id)))) : null;
  });
  const parentLink = p.used_in?.length ? h('div', { class: 'part-group' },
    h('h3', null, p.used_in.length > 1 ? 'Kullanıldığı yarı mamuller' : 'Ait olduğu yarı mamul'),
    h('ul', { class: 'stat-list' }, p.used_in.map(x => h('li', null, h('a', { href: `#/products/${x.id}` }, `${x.code} — ${x.name}`)))))
    : p.parent ? h('div', { class: 'part-group' },
      h('h3', null, p.parent.type === 'YARI_MAMUL' ? 'Ait olduğu yarı mamul' : 'Ait olduğu mamul'),
      h('a', { href: `#/products/${p.parent.id}` }, `${p.parent.code} — ${p.parent.name}`)) : null;

  const infoCard = h('div', { class: 'card card-pad' },
    h('h2', { style: { fontSize: '15px', marginBottom: '12px' } }, 'Ürün bilgileri'),
    field('Ürün adı', f.name),
    field('Seri numarası', f.serial),
    h('div', { class: 'row' }, field('Ürün kodu', f.code), field('Kuyruk öneki', f.prefix)),
    locked ? h('div', { class: 'small muted', style: { marginTop: '-6px', marginBottom: '10px' } },
      partSpare ? 'Parça yedeğinin kodu, uçaktaki parça kodudur; değiştirilemez.' : 'Siparişi olan ürünün kodu ve kuyruk öneki değiştirilemez.') : null,
    spare ? (partSpare ? field('Bir baskıda üretilen adet', perPrint)
      : h('div', null, field('Bir baskıda üretilen adet', perPrint),
        h('div', { class: 'usage-grid' }, h('div', { class: 'usage-head' }, 'Yarı mamulde kullanılan adet'),
          usageInputs.map(([sm, i]) => h('label', { class: 'usage-row' }, h('span', null, sm.name), i)),
          h('div', { class: 'usage-row total' }, h('span', null, 'CAYMAZ başına toplam'), usageTotal)))) : null,
    spare ? field('Baskı dosyası (yazıcıya verilen)', printFile) : null,
    spare ? h('div', { class: 'row' }, field('Baskı süresi (saat)', printH), field('(dakika)', printM)) : null,
    mamul ? field('Kullanım durumu', f.usage, 'Tek kullanımlık uçak uçtuktan sonra HURDA olur ve yeniden sahaya gidemez') : null,
    field('Açıklama', f.desc),
    h('label', { class: 'check', style: { marginBottom: '6px' } }, f.active, 'Aktif'),
    h('label', { class: 'check', style: { marginBottom: semi ? '2px' : '14px' } }, f.orderable, 'Sipariş verilebilir'),
    semi ? h('div', { class: 'small muted', style: { marginBottom: '14px' } },
      `Yarı mamul için sipariş açılmaz; ${p.parent?.name || 'mamul'} siparişinin montaj aşamasında birleştirilir.`) : null,
    h('div', { style: { display: 'flex', justifyContent: 'flex-end' } }, save));

  const sideCard = spare ? h('div', { class: 'card card-pad' },
    h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Stok'),
    h('div', { class: 'spare-stock' }, h('b', null, p.stock), h('span', null, 'adet stokta')),
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px' } },
      h('button', { class: 'btn', onclick: () => spareMovesModal(p) }, 'Stok hareketleri'),
      h('button', { class: 'btn', onclick: () => spareAdjustModal(p) }, 'Sayım düzeltmesi')),
    parentLink)
    : mamul && tree ? treeCard(tree)
      : h('div', { class: 'card card-pad' },
        h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, `Parça kodları (${p.part_count})`),
        groups, parentLink);

  const stage = h('div', { class: 'card plane-stage' });
  const pl = renderPlane(plane, {
    fill: part => (part.group === 'cover' ? 'var(--cover-fill)' : 'var(--part-fill)'),
    tooltip: part => partInfoLines(part, plane.groups),
    onClick: mamul && tree ? part => goPart(tree, part.id) : undefined,
  });
  if (!mamul || !tree) {
    clear(stage, semi || spare ? (pl.setLayer(null), null) : layerToggle(pl, 'plane.layer', plane), pl.svg);
  } else {
    // Mamul: MAMUL (tek parça uçak) / YARI MAMUL (dört ana yapı) / YEDEK PARÇA (tüm parçalar) görünümü
    let mode = pref('products.treeView', 'YEDEK_PARCA');
    const draw = () => {
      const sw = segmented([['MAMUL', 'Mamul'], ['YARI_MAMUL', 'Yarı mamul'], ['YEDEK_PARCA', 'Yedek parça']], mode,
        v => { mode = v; setPref('products.treeView', v); draw(); });
      const bar = h('div', { class: 'tree-view-bar' }, h('span', { class: 'small muted' }, 'Görünüm'), sw);
      if (mode === 'YEDEK_PARCA') return clear(stage, bar, layerToggle(pl, 'plane.layer', plane), pl.svg);
      if (mode === 'MAMUL') {
        const a = renderAssembly(plane, { whole: true, items: { ALL: { state: 'info',
          label: [p.name, { text: 'Mamul', class: 'sub' }, { text: `${p.serial} · ${p.part_count} parça`, class: 'muted' }] } } });
        return clear(stage, bar, a.svg);
      }
      const semis = tree.children.filter(n => n.type === 'YARI_MAMUL');
      const bySection = Object.fromEntries(semis.map(n => [n.section, n]));
      const items = Object.fromEntries(semis.map(n => [n.section, { state: 'info',
        label: [n.name, { text: `${n.code} · ${n.children.filter(c => c.part_spare).length} parça`, class: 'sub' }, { text: 'Açmak için tıklayın', class: 'muted' }] }]));
      const a = renderAssembly(plane, {
        whole: false, items,
        extra: { fill: () => 'var(--part-fill)', label: part => (part.name ? part.name.split(' ') : [part.id]),
          clickable: () => true, onClick: part => goPart(tree, part.id) },
        onElecClick: bySection.ELEKTRONIK ? () => { location.hash = `#/products/${bySection.ELEKTRONIK.id}`; } : null,
        onClick: key => { if (bySection[key]) location.hash = `#/products/${bySection[key].id}`; },
      });
      return clear(stage, bar, a.svg);
    };
    draw();
  }

  clear(view,
    pageHead(p.name, { back: '#/products', sub: `Seri no ${p.serial} · ${p.schema_title}` }),
    h('div', { class: 'plane-layout' },
      stage,
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px' } }, infoCard, sideCard)));
}

function goPart(tree, partId) {
  // Uçaktaki parça → parça yedeği ürün sayfası
  for (const semi of tree.children) for (const n of semi.children || []) {
    if (n.part_spare && (n.code === partId || n.code === `P-${partId}`)) { location.hash = `#/products/${n.id}`; return; }
  }
}

function treeCard(tree) {
  // Ürün ağacı: mamul → yarı mamul → yedek parça
  const stockBadge = n => h('span', { class: `tree-stock ${n.stock > 0 ? 'on' : ''}`, title: 'Stok' }, n.stock);
  const semis = tree.children.filter(n => n.type === 'YARI_MAMUL');
  const direct = tree.children.filter(n => n.type !== 'YARI_MAMUL');
  return h('div', { class: 'card card-pad ptree' },
    h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Ürün ağacı'),
    h('div', { class: 'ptree-root' }, h('span', { class: 'type-tag mamul' }, 'Mamul'), h('b', null, `${tree.code} — ${tree.name}`)),
    h('div', { class: 'ptree-level' },
      semis.map(s => h('details', { class: 'ptree-node' },
        h('summary', null, h('span', { class: 'type-tag semi' }, 'Yarı mamul'),
          h('a', { href: `#/products/${s.id}`, onclick: e => e.stopPropagation() }, s.name),
          h('span', { class: 'small muted' }, `${s.children.filter(c => c.part_spare).length} parça`
            + (s.children.some(c => !c.part_spare) ? ` · ${s.children.filter(c => !c.part_spare).length} sarf` : ''))),
        h('div', { class: 'ptree-parts' }, s.children.filter(c => c.part_spare).map(c => h('a', { class: 'ptree-part', href: `#/products/${c.id}`,
          title: `${c.name}${c.print_minutes ? ` · baskı ${fmtMinutes(c.print_minutes)}` : ''}` },
          h('span', { class: 'mono' }, c.code), stockBadge(c)))),
        s.children.some(c => !c.part_spare) ? h('ul', { class: 'stat-list ptree-sarf' }, s.children.filter(c => !c.part_spare).map(c => h('li', null,
          h('a', { href: `#/products/${c.id}` }, `${c.code} — ${c.name}`),
          h('span', null, h('b', null, `×${c.qty}`), ' ', stockBadge(c))))) : null)),
      direct.length ? h('div', { class: 'ptree-node flat' },
        h('div', { class: 'ptree-head' }, h('span', { class: 'type-tag spare' }, 'Yedek parça'), h('span', { class: 'small muted' }, 'Montaj sarfı')),
        h('ul', { class: 'stat-list' }, direct.map(c => h('li', null,
          h('a', { href: `#/products/${c.id}` }, `${c.code} — ${c.name}`),
          h('span', null, h('b', null, `×${c.qty}`), ' ', stockBadge(c)))))) : null),
    h('div', { class: 'small muted', style: { marginTop: '8px' } }, 'Parçanın yanındaki sayı stoktaki yedek adedidir.'));
}
