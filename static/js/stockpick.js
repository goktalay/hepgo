// Stoktan ürün seçici: yazdıkça (3 karakterden sonra) stoktaki tüm ürünler (tip ayırmadan) açılır listede gelir.
// stockPicker({ value, placeholder, onPick(product|null) }) → { el, input, focus() }
import { api } from './api.js';
import { h, clear } from './ui.js';

const TYPE = { MAMUL: 'Mamul', YARI_MAMUL: 'Yarı mamul', SARF: 'Sarf malzeme', HAMMADDE: 'Hammadde', YEDEK_PARCA: 'Yedek parça' };
const TONE = { YEDEK_PARCA: 'blue', SARF: 'gray', HAMMADDE: 'yellow', YARI_MAMUL: 'purple', MAMUL: 'green' };
const fmt = n => Number(n || 0).toLocaleString('tr-TR', { maximumFractionDigits: 2 });

export function stockPicker({ value = '', linked = !!value, placeholder = 'Stokta ara: yedek parça, sarf, malzeme (ad, kod, barkod)…', url = '/api/field/equipment-search', onPick } = {}) {
  const input = h('input', { class: 'input sp-input', value, placeholder, autocomplete: 'off', role: 'combobox', 'aria-expanded': 'false' });
  const list = h('div', { class: 'sp-list', role: 'listbox', hidden: true });
  const el = h('div', { class: 'sp' }, input);
  // Liste sayfa katmanında (tablo / pencere kaydırma alanında kesilmesin), kutunun hemen altında
  const place = () => {
    const r = input.getBoundingClientRect();
    const below = innerHeight - r.bottom > 260 || r.top < 260;
    Object.assign(list.style, { left: `${r.left}px`, width: `${Math.max(r.width, 320)}px`,
      top: below ? `${r.bottom + 4}px` : '', bottom: below ? '' : `${innerHeight - r.top + 4}px` });
  };
  const onMove = () => { if (!list.hidden) place(); };
  let items = [], active = -1, timer = null, seq = 0, picked = value;
  const close = () => {
    list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1;
    list.remove(); removeEventListener('scroll', onMove, true); removeEventListener('resize', onMove);
  };
  const choose = p => {
    picked = p.name; input.value = p.name; close();
    el.classList.add('ok');
    onPick?.(p);
  };
  const draw = (msg) => {
    if (!list.isConnected) { document.body.append(list); addEventListener('scroll', onMove, true); addEventListener('resize', onMove); }
    list.hidden = false; input.setAttribute('aria-expanded', 'true');
    place();
    if (msg) return clear(list, h('div', { class: 'sp-msg' }, msg));
    clear(list, items.map((p, i) => h('button', { type: 'button', class: `sp-item ${i === active ? 'on' : ''}`, role: 'option',
      onmousedown: e => { e.preventDefault(); choose(p); } },
      h('span', { class: 'sp-name' }, h('b', null, p.name), h('small', null, [p.code, p.mikro_code && p.mikro_code !== p.code ? `Mikro: ${p.mikro_code}` : null, p.brand, p.model].filter(Boolean).join(' · '))),
      h('span', { class: 'sp-meta' }, h('span', { class: `badge ${TONE[p.kind || p.type] || 'gray'}` }, TYPE[p.kind || p.type] || p.type),
        h('small', { class: p.stock > 0 ? 'sp-in' : 'sp-out' }, `Stok: ${fmt(p.stock)} ${p.unit || ''}`)))));
  };
  const search = () => {
    const q = input.value.trim();
    if (q.length < 2) { items = []; return q ? draw('En az 3 karakter yazın (parça kodu için 2: R2, 09)') : close(); }
    const my = ++seq;
    draw('Aranıyor…');
    api.get(`${url}?q=${encodeURIComponent(q)}`).then(r => {
      if (my !== seq) return;
      items = r; active = r.length ? 0 : -1;
      r.length ? draw() : draw('Stokta eşleşen ürün yok');
    }).catch(err => { if (my === seq) draw(err.message); });
  };
  input.addEventListener('input', () => {
    if (input.value !== picked) { el.classList.remove('ok'); onPick?.(null); }
    clearTimeout(timer); timer = setTimeout(search, 220);
  });
  input.addEventListener('keydown', e => {
    if (list.hidden || !items.length) return;
    if (e.key === 'ArrowDown') { active = (active + 1) % items.length; draw(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; draw(); e.preventDefault(); }
    else if (e.key === 'Enter' && active >= 0) { choose(items[active]); e.preventDefault(); }
    else if (e.key === 'Escape') close();
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
  if (value && linked) el.classList.add('ok');
  return { el, input, focus: () => input.focus() };
}
