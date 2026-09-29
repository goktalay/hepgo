// Stok Yönetimi: depodaki/yarı mamul uçak sayıları ve uçak üzerinde parça adetleri
import { api } from '../api.js';
import { layerToggle, loadPlane, partInfoLines, renderPlane } from '../plane.js';
import { ORDER_STATES, badge, queuePlate } from '../status.js';
import { clear, field, fmtDateTime, h, matches, modal, pageHead, selectInput, statStrip, toast } from '../ui.js';

// ---------- Yedek parça stoğu (kamera tutucu, klipsler): hareketler ve sayım düzeltmesi
export async function spareMovesModal(p) {
  const moves = await api.get(`/api/products/${p.id}/moves`);
  modal({
    title: `${p.code} — ${p.name}: stok hareketleri`,
    wide: true,
    body: moves.length ? h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Tarih', 'Hareket', 'Adet', 'Sipariş', 'Kişi'].map(t => h('th', null, t)))),
      h('tbody', null, moves.map(m => h('tr', null,
        h('td', { class: 'muted' }, fmtDateTime(m.created_at)),
        h('td', null, m.reason),
        h('td', { class: 'num' }, h('b', { style: { color: m.qty < 0 ? 'var(--danger)' : 'var(--ok, #1f9d55)' } }, m.qty > 0 ? `+${m.qty}` : m.qty)),
        h('td', { class: 'mono' }, m.order_code || '—'),
        h('td', null, m.user_name || '—'))))))
      : h('div', { class: 'empty' }, 'Hareket yok'),
    actions: [{ label: 'Kapat', class: 'primary' }],
  });
}

export function spareAdjustModal(p, done) {
  const qty = h('input', { class: 'input', type: 'number', placeholder: 'Ör. 12 ya da -3' });
  const reason = h('input', { class: 'input', placeholder: 'Ör. Sayım farkı, hurda' });
  modal({
    title: `${p.code} — sayım düzeltmesi`,
    body: h('div', null, h('p', { style: { marginTop: 0 } }, `Şu anki stok: ${p.stock} adet. Eklemek için artı, düşmek için eksi adet girin.`),
      h('div', { class: 'row' }, field('Adet', qty), field('Açıklama', reason))),
    actions: [{ label: 'Vazgeç' }, {
      label: 'Kaydet', class: 'primary', onClick: async () => {
        const n = Number(qty.value);
        if (!n || !reason.value.trim()) throw new Error('Adet (sıfırdan farklı) ve açıklama zorunlu');
        const r = await api.post(`/api/products/${p.id}/adjust`, { qty: n, reason: reason.value.trim() });
        toast(`Yeni stok: ${r.stock} adet`);
        (done || (() => window.dispatchEvent(new HashChangeEvent('hashchange'))))();
      },
    }],
  });
}

function sparesCard(spares, ctx, partSpares = []) {
  const inStock = partSpares.filter(x => x.stock > 0);
  const canAdjust = ['warehouse', 'products'].some(m => ctx.user.modules.includes(m));
  return h('div', { class: 'card card-pad' },
    h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Yedek parça stoğu'),
    spares.length ? h('div', { class: 'spare-list' }, spares.map(sp => {
      const low = sp.per_aircraft && sp.stock < sp.per_aircraft;
      return h('div', { class: `spare-row ${low ? 'low' : ''}` },
        h('div', { class: 'grow' }, h('b', null, `${sp.code} · ${sp.name}`),
          h('div', { class: 'small muted' }, `CAYMAZ başına ${sp.per_aircraft} · baskıda ${sp.per_print}`
            + (sp.open_orders ? ` · ${sp.open_orders} açık sipariş` : ''))),
        h('div', { class: 'spare-num' }, h('b', null, sp.stock),
          h('span', null, sp.enough_for == null ? 'adet' : `${sp.enough_for} uçağa yeter`)),
        h('div', { class: 'spare-btns' },
          h('button', { class: 'btn sm', onclick: () => spareMovesModal(sp) }, 'Hareketler'),
          canAdjust ? h('button', { class: 'btn sm', onclick: () => spareAdjustModal(sp) }, 'Düzelt') : null));
    })) : h('div', { class: 'muted small' }, 'Yedek parça tanımlı değil'),
    partSpares.length ? h('a', { class: 'spare-row', href: '#/products', style: { marginTop: '8px', color: 'inherit' } },
      h('div', { class: 'grow' }, h('b', null, 'Parça yedekleri'),
        h('div', { class: 'small muted' }, `${partSpares.length} parça tanımlı · ${inStock.length} çeşidi stokta`)),
      h('div', { class: 'spare-num' }, h('b', null, inStock.reduce((a, x) => a + x.stock, 0)), h('span', null, 'adet'))) : null);
}

export async function render(view, params, ctx) {
  const canOpen = ctx.user.modules.includes('production');
  const qs = params[0] ? `?product_id=${Number(params[0])}` : '';
  const [allProducts, stock, allSpares] = await Promise.all([api.get('/api/products'), api.get(`/api/stock${qs}`),
    api.get('/api/products/spares/summary').catch(() => [])]);
  // Kartta montaj sarfı yedek parçalar (uçak başına kullanılan); parça yedekleri tek satırda özetlenir
  const spares = allSpares.filter(x => x.per_aircraft > 0);
  const partSpares = allSpares.filter(x => !x.per_aircraft);
  const products = allProducts.filter(p => p.type === 'MAMUL');   // stok haritası mamuller için
  const plane = await loadPlane(stock.product.id);
  const picker = h('select', { class: 'input', onchange: e => { location.hash = `#/stock/${e.target.value}`; } },
    products.map(p => h('option', { value: p.id, selected: p.id === stock.product.id }, `${p.name} (${p.serial})`)));
  const counts = stock.part_counts;
  const pending = stock.pending_counts;
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Parça kodu ara (ör. L15, 03)…', style: { width: '220px' } });
  const group = selectInput(Object.entries(plane.groups), { all: 'Tüm gruplar' });
  const inStock = h('input', { type: 'checkbox' });
  const shown = part => (!group.value || part.group === group.value) && (!inStock.checked || counts[part.id] > 0) &&
    matches(q.value, part.id);

  const pl = renderPlane(plane, {
    fill: part => (!shown(part) ? 'var(--part-off)' : counts[part.id] ? 'var(--st-depo)' : 'var(--part-fill)'),
    label: part => String(counts[part.id]),
    labelClass: part => `count ${counts[part.id] ? '' : 'zero'} ${shown(part) ? '' : 'faded'}`,
    tooltip: part => [
      h('span', null, 'Yarı mamul stok: ', h('b', null, `${counts[part.id]} adet`)),
      pending[part.id] ? `Depo onayı bekleyen: ${pending[part.id]} adet` : null,
      ...partInfoLines(part, plane.groups),
    ],
  });

  const totalParts = Object.values(counts).reduce((a, b) => a + b, 0);
  const totalPending = Object.values(pending).reduce((a, b) => a + b, 0);
  const covers = plane.parts.filter(p => p.group === 'cover');
  const ids = plane.parts.map(p => p.id);
  // Tam bir uçak için stoktaki en az adet: en az bulunan parçanın adedi (hiç yoksa 0)
  const fullSets = Math.min(...ids.map(id => counts[id] || 0));
  const stats = statStrip();
  stats.set([
    { label: 'Saha deposundaki uçak', value: stock.ready_aircraft.length, tone: 'ok' },
    { label: 'Yarı mamuldeki uçak', value: stock.wip_aircraft.length },
    { label: 'Yarı mamul parça (depoda)', value: totalParts },
    { label: 'Depo onayı bekleyen parça', value: totalPending, tone: totalPending ? 'alert' : '' },
    { label: 'Stokta olan parça çeşidi', value: `${ids.filter(id => counts[id] > 0).length}/${ids.length}` },
    { label: 'Stokta olmayan parça', value: ids.filter(id => !counts[id]).length },
    { label: 'Tam takım (uçak) adedi', value: fullSets, sub: 'depodaki parçalardan' },
    spares.length ? { label: 'Yedek parçanın yettiği uçak', value: Math.min(...spares.map(x => x.enough_for ?? Infinity)),
      tone: spares.some(x => x.per_aircraft && x.stock < x.per_aircraft) ? 'alert' : 'ok', sub: 'klips + kamera tutucu' } : null,
  ]);
  const redraw = () => pl.update();
  q.addEventListener('input', redraw);
  group.addEventListener('change', redraw);
  inStock.addEventListener('change', redraw);

  clear(view,
    pageHead('Stok Yönetimi', { back: '#/', sub: `${stock.product.name} · seri no ${stock.product.serial}` }),
    stats,
    h('div', { class: 'filters' }, picker, q, group, h('label', { class: 'check' }, inStock, 'Sadece stokta olanlar')),
    h('div', { class: 'plane-layout stock-layout' },
      h('div', { class: 'card plane-stage' },
        layerToggle(pl, 'plane.layer', plane),
        h('p', { class: 'small muted', style: { margin: '4px 6px 8px' } },
          'Her parçanın üzerindeki sayı, tamamlanmamış uçaklar için depoda bekleyen (onaylı) adettir.'),
        pl.svg),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: '16px' } },
        sparesCard(spares, ctx, partSpares),
        h('div', { class: 'card card-pad' },
          h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Kapaklar'),
          h('ul', { class: 'stat-list' }, covers.map(c =>
            h('li', null, h('span', { class: 'mono' }, c.id), h('b', null, counts[c.id]))))),
        h('div', { class: 'card card-pad' },
          h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Saha deposundaki uçaklar'),
          stock.ready_aircraft.length
            ? h('ul', { class: 'stat-list' }, stock.ready_aircraft.map(a =>
              h('li', null, h('span', null, queuePlate(a.queue_no), h('div', { class: 'small muted' }, a.code)),
                h('span', { class: 'small muted' }, fmtDateTime(a.completed_at)))))
            : h('div', { class: 'muted small' }, 'Saha deposunda uçak yok')),
        h('div', { class: 'card card-pad' },
          h('h2', { style: { fontSize: '15px', marginBottom: '8px' } }, 'Yarı mamuldeki uçaklar'),
          stock.wip_aircraft.length
            ? h('ul', { class: 'stat-list' }, stock.wip_aircraft.map(o =>
              h('li', null, canOpen ? h('a', { href: `#/production/${o.id}` }, o.code) : h('span', null, o.code),
                badge(ORDER_STATES, o.status))))
            : h('div', { class: 'muted small' }, 'Yarı mamulde uçak yok')))));
}
