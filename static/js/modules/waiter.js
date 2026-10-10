// Garson (esnaf · lokanta): bölüm+masa yerleşimi; masaya adisyon aç; kişi (seat) bazlı sipariş; masa birleştir; hesap al.
// Hesap alınca adisyon bir POS satışına dönüşür (fatura + stok + kasa tahsilatı + bahşiş). Masa boşalır.
import { api } from '../api.js';
import { clear, h, modal, pageHead, toast, toastError } from '../ui.js';

const TL = n => `${(Number(n) || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;

export async function render(view, params, ctx) {
  let menuItems = [], accounts = [];
  const root = h('div', { class: 'waiter-root' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  clear(view, pageHead('Garson', { back: '#/', sub: 'Masa düzeni ve adisyonlar' }), root);

  try { [menuItems, accounts] = await Promise.all([api.get('/api/waiter/menu'), api.get('/api/waiter/accounts')]); }
  catch { /* menü boş olabilir */ }

  await showFloor();

  async function showFloor() {
    let data;
    try { data = await api.get('/api/waiter/floor'); } catch (e) { clear(root, h('div', { class: 'card empty' }, e.message)); return; }
    const secs = data.sections || [];
    const loose = data.loose || [];
    clear(root);
    if (!secs.length && !loose.length) { root.append(h('div', { class: 'card empty' }, 'Masa tanımlı değil. Bölümler modülünden salon ve masa ekleyin.')); return; }
    const drawSec = (name, tables) => h('div', { class: 'card waiter-sec' },
      h('div', { class: 'waiter-sec-h' }, h('b', null, name)),
      h('div', { class: 'waiter-tables' }, tables.map(tableBtn)));
    secs.forEach(s => root.append(drawSec(s.name, s.tables || [])));
    if (loose.length) root.append(drawSec('Diğer masalar', loose));
  }

  function tableBtn(t) {
    const o = t.order;
    const busy = !!o;
    return h('button', { class: `waiter-table ${busy ? 'busy' : 'free'} ${t.shape === 'round' ? 'round' : ''}`, type: 'button',
      onclick: () => onTable(t) },
      h('b', null, t.name),
      busy ? h('span', { class: 'wt-total' }, TL(o.total)) : h('span', { class: 'wt-seats' }, `${t.seats} kişi`),
      busy ? h('span', { class: 'wt-party' }, `${o.party} kişi`) : null,
      t.waiter_name ? h('small', { class: 'wt-waiter' }, t.waiter_name) : null);
  }

  async function onTable(t) {
    if (t.order) return openOrder(t.order.id, t);
    // boş masa: kişi sayısı sor, adisyon aç
    const party = h('input', { class: 'input', type: 'number', min: '1', value: t.seats || 2 });
    const m = modal({
      title: `${t.name} · Adisyon Aç`, wide: false,
      body: h('div', { class: 'form-col' }, h('label', null, 'Kişi sayısı', party)),
      actions: [{ label: 'Vazgeç' }, { label: 'Aç', class: 'primary', onClick: async () => {
        try { const r = await api.post(`/api/waiter/table/${t.id}/open`, { party: +party.value || 1 }); m.close(); await openOrder(r.id, t); }
        catch (e) { toastError(e); return true; }
      } }],
    });
  }

  async function openOrder(oid, t) {
    let order;
    try { order = await api.get(`/api/waiter/order/${oid}`); } catch (e) { toastError(e); return; }
    let seat = 1;
    const party = Math.max(1, order.party || 1);

    const seatTabs = h('div', { class: 'waiter-seats' });
    const itemsBox = h('div', { class: 'waiter-items' });
    const totalEl = h('b', { class: 'waiter-grand' }, TL(order.total));
    const search = h('input', { class: 'input waiter-menu-search', type: 'search', placeholder: 'Menüden ürün ara / ekle…' });
    const menuGrid = h('div', { class: 'waiter-menu' });

    const drawSeats = () => {
      clear(seatTabs);
      for (let i = 1; i <= party; i++) {
        seatTabs.append(h('button', { class: 'waiter-seat' + (i === seat ? ' on' : ''), type: 'button', onclick: () => { seat = i; drawSeats(); drawItems(); } }, `Kişi ${i}`));
      }
      seatTabs.append(h('button', { class: 'waiter-seat' + (seat === 0 ? ' on' : ''), type: 'button', onclick: () => { seat = 0; drawSeats(); drawItems(); } }, 'Tümü'));
    };
    const drawItems = () => {
      clear(itemsBox);
      const its = order.items.filter(x => seat === 0 || x.seat === seat);
      if (!its.length) { itemsBox.append(h('div', { class: 'muted small', style: 'padding:10px' }, 'Bu kişide kalem yok. Menüden ekleyin.')); }
      its.forEach(x => itemsBox.append(h('div', { class: 'waiter-item' },
        seat === 0 ? h('span', { class: 'wi-seat' }, `K${x.seat}`) : null,
        h('span', { class: 'grow' }, `${x.qty} × ${x.name}`),
        h('b', null, TL(x.qty * x.price)),
        h('button', { class: 'mini danger', type: 'button', title: 'Kaldır', onclick: () => removeItem(x) }, '×'))));
      totalEl.textContent = TL(order.total);
    };
    const drawMenu = () => {
      const q = search.value.trim().toLocaleLowerCase('tr');
      const list = q ? menuItems.filter(p => `${p.name} ${p.barcode || ''}`.toLocaleLowerCase('tr').includes(q)) : menuItems;
      clear(menuGrid, list.slice(0, 60).map(p => h('button', { class: 'waiter-menu-b', type: 'button', onclick: () => addItem(p) },
        h('span', null, p.name), h('small', null, TL(p.price)))));
    };
    search.addEventListener('input', drawMenu);

    async function addItem(p) {
      try {
        await api.post(`/api/waiter/order/${oid}/item`, { seat: seat || 1, product_id: p.id, name: p.name, qty: 1, price: p.price });
        order = await api.get(`/api/waiter/order/${oid}`); drawItems();
      } catch (e) { toastError(e); }
    }
    async function removeItem(x) {
      try { await api.del(`/api/waiter/order/${oid}/item/${x.id}`); order = await api.get(`/api/waiter/order/${oid}`); drawItems(); }
      catch (e) { toastError(e); }
    }

    const payBtn = h('button', { class: 'btn primary lg', type: 'button', onclick: () => payModal() }, 'Hesap Al');
    const mergeBtn = h('button', { class: 'btn', type: 'button', onclick: () => mergeModal() }, '⇄ Masa Birleştir');
    const backBtn = h('button', { class: 'btn', type: 'button', onclick: showFloor }, '← Masalar');

    clear(root,
      h('div', { class: 'waiter-order-head' }, backBtn, h('b', null, `${t?.name || 'Masa'} · Adisyon`), h('span', { class: 'spacer' }), mergeBtn),
      h('div', { class: 'waiter-order' },
        h('div', { class: 'waiter-order-left' }, seatTabs, itemsBox,
          h('div', { class: 'waiter-order-foot' }, h('span', null, 'Toplam'), totalEl, payBtn)),
        h('div', { class: 'waiter-order-right' }, search, menuGrid)));
    drawSeats(); drawItems(); drawMenu();

    function payModal() {
      if (!order.items.length) { toastError('Adisyon boş'); return; }
      const acct = h('select', { class: 'input' }, ...accounts.map(a => h('option', { value: a.id }, a.name)));
      if (!accounts.length) acct.append(h('option', { value: '' }, 'Kasa tanımsız'));
      const payment = h('select', { class: 'input' }, ...['Nakit', 'Kart', 'Veresiye'].map(p => h('option', { value: p }, p)));
      const tip = h('input', { class: 'input', type: 'number', min: '0', max: '100', value: 0 });
      const m = modal({
        title: 'Hesap Al', wide: false,
        body: h('div', { class: 'form-col' },
          h('div', { class: 'waiter-pay-total' }, 'Tutar: ', h('b', null, TL(order.total))),
          h('label', null, 'Kasa', acct),
          h('div', { class: 'form-row' }, h('label', null, 'Ödeme', payment), h('label', null, 'Bahşiş (%)', tip))),
        actions: [{ label: 'Vazgeç' }, { label: 'Tahsil Et', class: 'primary', onClick: async () => {
          try {
            const r = await api.post(`/api/waiter/order/${oid}/pay`, { account_id: +acct.value || null, payment: payment.value, tip_pct: +tip.value || 0 });
            toast(`Hesap tamam · ${r.number} · ${TL(r.grand)}`); m.close(); await showFloor();
          } catch (e) { toastError(e); return true; }
        } }],
      });
    }

    async function mergeModal() {
      let floor;
      try { floor = await api.get('/api/waiter/floor'); } catch (e) { toastError(e); return; }
      const all = [...(floor.sections || []).flatMap(s => s.tables || []), ...(floor.loose || [])].filter(x => x.id !== (t?.id));
      const sel = h('select', { class: 'input' }, h('option', { value: '' }, 'Masa seçin'),
        ...all.map(x => h('option', { value: x.id }, `${x.name}${x.order ? ' (dolu)' : ''}`)));
      const m = modal({
        title: 'Masa Birleştir', wide: false,
        body: h('div', { class: 'form-col' }, h('p', { class: 'muted small' }, 'Seçilen masanın adisyonu bu masaya taşınır.'), sel),
        actions: [{ label: 'Vazgeç' }, { label: 'Birleştir', class: 'primary', onClick: async () => {
          if (!sel.value) { toastError('Masa seçin'); return true; }
          try { await api.post(`/api/waiter/order/${oid}/merge`, { other_table_id: +sel.value }); order = await api.get(`/api/waiter/order/${oid}`); m.close(); toast('Birleştirildi'); drawItems(); }
          catch (e) { toastError(e); return true; }
        } }],
      });
    }
  }
}
