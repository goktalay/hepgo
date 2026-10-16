// Sistem geneli arama: üst çubuktaki büyüteç (ya da Ctrl+K) ekranın ortasında bir arama kutusu açar. 3 harften sonra
// /api/search yetkili modüllerin tümünde arar (cari, stok, sipariş, personel, evrak OCR metni…); sonuçlar türe göre
// gruplanır, ok tuşlarıyla gezilir, Enter/tıklama ilgili detay ekranına götürür. Sunucu büyük/küçük harf ve Türkçe harf
// farkını yok sayar.
import { api } from '../api.js';
import { icons } from '../icons.js';
import { clear, h, svgIcon, t } from '../ui.js';

const MIN = 3;
let box = null;   // açık pencere (tek örnek)

export function searchButton() {
  const btn = h('button', { class: 'icon-btn gs-btn', type: 'button', title: 'Ara', 'aria-label': 'Ara', onclick: e => { e.stopPropagation(); openSearch(); } },
    svgIcon(icons.search));
  return btn;
}

// Ctrl+K / Cmd+K her ekranda arama kutusunu açar; "/" tuşu yazı alanı dışındayken de açar.
export function installShortcut() {
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName) || e.target?.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); }
    else if (e.key === '/' && !typing && !box) { e.preventDefault(); openSearch(); }
  });
}

export function openSearch(initial = '') {
  if (box) { box.input.focus(); return; }
  const input = h('input', { class: 'gs-input', type: 'search', placeholder: 'Sistemde ara: cari, stok, sipariş, personel, evrak…',
    autocomplete: 'off', spellcheck: 'false', value: initial });
  const hint = h('div', { class: 'gs-hint' }, t('En az {n} harf yazın', { n: MIN }));
  const list = h('div', { class: 'gs-list', role: 'listbox' });
  const panel = h('div', { class: 'gs-box', role: 'dialog', 'aria-label': 'Ara', onclick: e => e.stopPropagation() },
    h('div', { class: 'gs-head' }, svgIcon(icons.search), input,
      h('button', { class: 'x-btn', type: 'button', 'aria-label': 'Kapat', onclick: () => close() }, '×')),
    hint, list,
    h('div', { class: 'gs-foot' }, h('span', null, h('kbd', null, '↑'), h('kbd', null, '↓'), ' ', t('gez')),
      h('span', null, h('kbd', null, 'Enter'), ' ', t('aç')), h('span', null, h('kbd', null, 'Esc'), ' ', t('kapat'))));
  const back = h('div', { class: 'gs-back', onclick: () => close() }, panel);
  document.body.appendChild(back);
  box = { el: back, input };

  let timer = null, seq = 0, active = -1, items = [];
  const close = () => { if (!box) return; clearTimeout(timer); back.remove(); box = null; window.removeEventListener('hashchange', close); };
  window.addEventListener('hashchange', close);

  const go = it => { close(); if (it?.href) location.hash = it.href; };
  const setActive = i => {
    active = i;
    items.forEach((x, k) => x.el.classList.toggle('active', k === i));
    items[i]?.el.scrollIntoView({ block: 'nearest' });
  };
  const render = (groups, q) => {
    items = [];
    if (!groups.length) { clear(list, h('div', { class: 'gs-empty' }, t('"{q}" için sonuç yok', { q }))); return; }
    clear(list, groups.map(g => h('div', { class: 'gs-group' },
      h('div', { class: 'gs-group-head' }, t(g.label), h('span', { class: 'gs-count' }, String(g.items.length))),
      g.items.map(it => {
        const el = h('a', { class: `gs-item gs-${g.type}`, href: it.href || '#', role: 'option',
          onclick: e => { e.preventDefault(); go(it); },
          onmousemove: () => { const k = items.findIndex(x => x.el === el); if (k !== active) setActive(k); } },
          h('span', { class: 'gs-type' }, t(g.label)),
          h('span', { class: 'gs-main' }, h('b', null, mark(it.title, q)), it.sub ? h('small', null, mark(it.sub, q)) : null,
            it.snippet ? h('span', { class: 'gs-snippet' }, it.snippet.before, h('mark', null, it.snippet.match), it.snippet.after) : null));
        items.push({ el, it });
        return el;
      }))));
    setActive(0);
  };
  const run = async () => {
    const q = input.value.trim();
    if (q.length < MIN) { clear(list); hint.hidden = false; hint.textContent = t('En az {n} harf yazın', { n: MIN }); return; }
    hint.hidden = true;
    const my = ++seq;
    panel.classList.add('loading');
    try {
      const r = await api.get(`/api/search?q=${encodeURIComponent(q)}`);
      if (my !== seq) return;
      render(r.groups || [], q);
    } catch (e) {
      if (my === seq) clear(list, h('div', { class: 'gs-empty' }, e.message || t('Arama başarısız')));
    } finally {
      if (my === seq) panel.classList.remove('loading');
    }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 220); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (items.length) setActive((active + 1) % items.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (items.length) setActive((active - 1 + items.length) % items.length); }
    else if (e.key === 'Enter') { e.preventDefault(); if (items[active]) go(items[active].it); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  });
  input.focus();
  if (initial) run();
}

// Eşleşen parçayı vurgular (büyük/küçük ve Türkçe harf farkı gözetmeden; metin uzunluğu korunduğundan konumlar geçerlidir).
const FOLD = { 'İ': 'i', 'I': 'i', 'ı': 'i', 'Ş': 's', 'ş': 's', 'Ğ': 'g', 'ğ': 'g', 'Ü': 'u', 'ü': 'u', 'Ö': 'o', 'ö': 'o', 'Ç': 'c', 'ç': 'c' };
const fold = s => (s || '').replace(/[İIıŞşĞğÜüÖöÇç]/g, c => FOLD[c]).toLowerCase();
function mark(text, q) {
  text = text || '';
  const f = fold(text), fq = fold(q);
  const i = fq ? f.indexOf(fq) : -1;
  if (i < 0) return text;
  return [text.slice(0, i), h('mark', null, text.slice(i, i + fq.length)), text.slice(i + fq.length)];
}
