// Esnaf Kasa (POS): dokunmatik perakende satış. Solda satılık ürün ızgarası + barkod/ad arama,
// sağda sepet (adet +/-), altta ödeme (Nakit/Kart/Veresiye) + kasa seçimi + Satışı Tamamla.
// Barkod: arama kutusuna el tarayıcı (klavye) yazar; Enter → ilk eşleşen ürün sepete eklenir.
import { api } from '../api.js';
import { clear, h, pageHead, toast, toastError } from '../ui.js';

const TL = n => `${(Number(n) || 0).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;

export async function render(view, params, ctx) {
  const reloadRef = { fn: null };
  const catBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => openCatalog(() => reloadRef.fn && reloadRef.fn()) }, '🏷️ Ürünler');
  clear(view, pageHead('Esnaf Kasa', { right: catBtn }));
  const wrap = h('div', { class: 'pos-wrap' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  view.append(wrap);

  let prods = [], accounts = [];
  try { [prods, accounts] = await Promise.all([api.get('/api/pos/products'), api.get('/api/pos/accounts')]); }
  catch { clear(wrap, h('div', { class: 'empty' }, 'Yüklenemedi. Satılık ürün tanımlı mı?')); return; }

  const cart = new Map();   // product_id -> { p, qty }
  const state = { payment: 'Nakit', account: accounts[0]?.id || null };

  // ---- sol: ürünler ----
  const search = h('input', { class: 'pos-search', type: 'search', placeholder: 'Barkod okut veya ürün ara…', autocomplete: 'off' });
  const grid = h('div', { class: 'pos-grid' });
  const drawGrid = (list) => {
    clear(grid);
    if (!list.length) { grid.append(h('div', { class: 'empty' }, 'Ürün yok')); return; }
    list.forEach(p => grid.append(h('button', { class: 'pos-prod', type: 'button', onclick: () => addToCart(p) },
      h('span', { class: 'pos-prod-n' }, p.name),
      h('span', { class: 'pos-prod-p' }, TL(p.sale_price)))));
  };
  const filter = () => {
    const q = search.value.trim().toLocaleLowerCase('tr');
    drawGrid(q ? prods.filter(p => `${p.name} ${p.code} ${p.barcode || ''}`.toLocaleLowerCase('tr').includes(q)) : prods);
  };
  search.addEventListener('input', filter);
  search.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const q = search.value.trim();
    if (!q) return;
    const exact = prods.find(p => (p.barcode || '') === q) || prods.find(p => p.code === q)
      || prods.filter(p => p.name.toLocaleLowerCase('tr').includes(q.toLocaleLowerCase('tr')))[0];
    if (exact) { addToCart(exact); search.value = ''; filter(); } else toastError('Ürün bulunamadı');
  });

  // ---- sağ: sepet ----
  const cartBox = h('div', { class: 'pos-cart-items' });
  const totalEl = h('b', { class: 'pos-total-v' }, TL(0));
  const payBtns = h('div', { class: 'pos-pay' }, ...['Nakit', 'Kart', 'Veresiye'].map(p =>
    h('button', { class: 'pos-pay-b' + (p === state.payment ? ' on' : ''), type: 'button', 'data-pay': p,
      onclick: e => { state.payment = p; [...payBtns.children].forEach(b => b.classList.toggle('on', b.dataset.pay === p)); acctSel.hidden = p === 'Veresiye'; } }, p)));
  const acctSel = h('select', { class: 'pos-acct' }, ...accounts.map(a => h('option', { value: a.id }, a.name)));
  if (!accounts.length) acctSel.append(h('option', { value: '' }, 'Kasa tanımsız'));
  acctSel.onchange = () => { state.account = +acctSel.value || null; };
  const finishBtn = h('button', { class: 'btn primary pos-finish', type: 'button' }, 'Satışı Tamamla');

  const total = () => [...cart.values()].reduce((s, x) => s + (x.p.sale_price || 0) * x.qty, 0);
  const drawCart = () => {
    clear(cartBox);
    if (!cart.size) { cartBox.append(h('div', { class: 'pos-cart-empty' }, 'Sepet boş')); }
    for (const x of cart.values()) {
      cartBox.append(h('div', { class: 'pos-citem' },
        h('span', { class: 'pos-ci-n' }, x.p.name),
        h('div', { class: 'pos-ci-qty' },
          h('button', { class: 'pos-q', type: 'button', onclick: () => chQty(x, -1) }, '−'),
          h('span', null, x.qty),
          h('button', { class: 'pos-q', type: 'button', onclick: () => chQty(x, 1) }, '+')),
        h('span', { class: 'pos-ci-t' }, TL((x.p.sale_price || 0) * x.qty))));
    }
    totalEl.textContent = TL(total());
    finishBtn.disabled = !cart.size;
  };
  function addToCart(p) { const x = cart.get(p.id) || { p, qty: 0 }; x.qty++; cart.set(p.id, x); drawCart(); }
  function chQty(x, d) { x.qty += d; if (x.qty <= 0) cart.delete(x.p.id); drawCart(); }

  finishBtn.onclick = async () => {
    if (!cart.size) return;
    if (state.payment !== 'Veresiye' && !state.account && accounts.length) { toastError('Kasa seçin'); return; }
    finishBtn.disabled = true; finishBtn.textContent = 'Kaydediliyor…';
    try {
      const r = await api.post('/api/pos/sale', {
        items: [...cart.values()].map(x => ({ product_id: x.p.id, qty: x.qty })),
        payment: state.payment, account_id: state.account,
      });
      toast(`Satış tamam · ${r.number} · ${TL(r.total)}`);
      cart.clear(); drawCart(); search.focus();
    } catch (e) { toastError(e.message || 'Satış kaydedilemedi'); }
    finishBtn.disabled = false; finishBtn.textContent = 'Satışı Tamamla';
  };

  clear(wrap);
  wrap.append(
    h('div', { class: 'pos-left' }, search, grid),
    h('div', { class: 'pos-right' },
      h('div', { class: 'pos-cart-h' }, 'Sepet'),
      cartBox,
      h('div', { class: 'pos-foot' },
        h('div', { class: 'pos-total' }, h('span', null, 'Toplam'), totalEl),
        payBtns, acctSel, finishBtn)));
  drawGrid(prods); drawCart(); search.focus();
  reloadRef.fn = async () => { try { prods = await api.get('/api/pos/products'); filter(); } catch { /* */ } };
}

// Satılık ürün yönetimi (modal): liste + ekle/düzenle + stok. onDone: POS ızgarasını tazeler.
async function openCatalog(onDone) {
  const ov = h('div', { class: 'pos-modal-ov' });
  const body = h('div', { class: 'pos-cat' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
  const close = () => { ov.remove(); onDone && onDone(); };
  ov.append(h('div', { class: 'pos-modal' },
    h('div', { class: 'pos-modal-h' }, h('b', null, 'Satılık Ürünler'), h('button', { class: 'pos-modal-x', type: 'button', onclick: close }, '✕')),
    body));
  ov.onclick = e => { if (e.target === ov) close(); };
  document.body.append(ov);

  const draw = (list) => {
    clear(body);
    // yeni/düzenle form
    const edit = { id: null };
    const fName = h('input', { class: 'sv-input', placeholder: 'Ürün adı' });
    const fBarcode = h('input', { class: 'sv-input', placeholder: 'Barkod (ops.)' });
    const fPrice = h('input', { class: 'sv-input', type: 'number', step: '0.01', placeholder: 'Fiyat ₺' });
    const fUnit = h('input', { class: 'sv-input', placeholder: 'Birim', value: 'Adet' });
    const fStock = h('input', { class: 'sv-input', type: 'number', step: '1', placeholder: 'Açılış stok' });
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Ekle');
    const resetForm = () => { edit.id = null; fName.value = ''; fBarcode.value = ''; fPrice.value = ''; fUnit.value = 'Adet'; fStock.value = ''; fStock.disabled = false; saveBtn.textContent = 'Ekle'; };
    saveBtn.onclick = async () => {
      if (!fName.value.trim()) { toastError('Ürün adı gerekli'); return; }
      saveBtn.disabled = true;
      try {
        const payload = { name: fName.value.trim(), barcode: fBarcode.value.trim(), sale_price: +fPrice.value || 0, unit: fUnit.value.trim() || 'Adet', stock: +fStock.value || 0 };
        if (edit.id) await api.put(`/api/pos/product/${edit.id}`, payload);
        else await api.post('/api/pos/product', payload);
        toast('Kaydedildi'); resetForm();
        draw(await api.get('/api/pos/catalog'));
      } catch (e) { toastError(e.message || 'Hata'); }
      saveBtn.disabled = false;
    };
    const form = h('div', { class: 'pos-cat-form' }, fName, fBarcode, fPrice, fUnit, fStock, saveBtn);

    const listBox = h('div', { class: 'pos-cat-list' });
    if (!list.length) listBox.append(h('p', { class: 'muted', style: 'padding:10px' }, 'Henüz satılık ürün yok. Yukarıdan ekleyin.'));
    list.forEach(p => {
      const row = h('div', { class: 'pos-cat-row' },
        h('span', { class: 'pos-cat-n' }, p.name, p.barcode ? h('small', { class: 'muted' }, ' · ' + p.barcode) : null),
        h('span', { class: 'pos-cat-p' }, TL(p.sale_price)),
        h('span', { class: 'pos-cat-s' }, `Stok: ${p.stock}`),
        h('button', { class: 'btn sm', type: 'button', onclick: () => { edit.id = p.id; fName.value = p.name; fBarcode.value = p.barcode || ''; fPrice.value = p.sale_price; fUnit.value = p.unit || 'Adet'; fStock.value = ''; fStock.disabled = true; saveBtn.textContent = 'Güncelle'; fName.focus(); } }, 'Düzenle'),
        h('button', { class: 'btn sm', type: 'button', onclick: async () => { const q = prompt(`${p.name} — yeni stok adedi:`, p.stock); if (q === null) return; await api.post(`/api/pos/product/${p.id}/stock`, { qty: +q || 0, mode: 'set' }); draw(await api.get('/api/pos/catalog')); } }, 'Stok'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { if (!confirm(`${p.name} kaldırılsın mı?`)) return; await api.del(`/api/pos/product/${p.id}`); draw(await api.get('/api/pos/catalog')); } }, 'Sil'));
      listBox.append(row);
    });
    body.append(form, listBox);
  };
  try { draw(await api.get('/api/pos/catalog')); } catch { clear(body, h('p', { class: 'muted' }, 'Yüklenemedi')); }
}
