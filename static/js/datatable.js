// Veri tabloları: her sütun başlığından sıralama ve filtre — modüllere dokunmadan, sayfadaki tablolara sonradan eklenir
// (listexport.js / headgroup.js ile aynı gözlemci kalıbı). İstemcide, o an yüklü satırlar üzerinde çalışır.
//  - Başlığa tıkla: artan → azalan → özgün sıra. Huni düğmesi: arama, değer listesi, sayıda en az / en çok, tarihte aralık.
//  - Sütun tipi içerikten anlaşılır (sayı / para / yüzde, tarih, süre, metin); td[data-sort] varsa sıralama anahtarı odur.
//  - Tek hücreli geniş satır: gövdenin ilk satırıysa grup başlığı (sıralama grup içinde), değilse üstündeki satırın ayrıntısı.
//  - Kapsam dışı: düzenleme tabloları (satırda giriş kutusu), birleşik başlıklı / matris tablolar, yazdırma şablonları,
//    kendi sıralaması olanlar (th.sortable) ve data-dt="off" (tabloda ya da bir üst öğesinde; tek sütun için th'de).
import { t } from './i18n.js';

const SKIP = '.pf-table, .pr-table, .mp-table, .att-table, .matrix-table, .bz-xl, .sc-ai-table, .print-area, .print-root, .rl-matrix, .kv, .fm-xl, .ct-proof, .rp-heat, .dt-pop, [data-dt="off"]';
const EDIT = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=button]), textarea, [contenteditable=""], [contenteditable="true"]';
const FUNNEL = '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true"><path d="M1.2 2.2h13.6L9.6 8.7v4.6l-3.2 1.5V8.7z" fill="currentColor"/></svg>';
const LIST_MAX = 200;

const STATE = new Map();     // tablo anahtarı → { sort: { col, dir } | null, filters: Map(sütun → F) }
const ORIG = new WeakMap();  // tr → özgün sıra (sıralama kaldırılınca geri dönmek için)
let seq = 0;
const COLL = new Intl.Collator('tr', { numeric: true, sensitivity: 'base' });

const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const clean = s => (s || '').replace(/\s+/g, ' ').trim();
const fold = s => s.toLocaleLowerCase('tr').replace(/ı/g, 'i').normalize('NFD').replace(/[̀-ͯ]/g, '');
const label = th => clean(th.textContent);

// ---------- Hücre değeri ----------
function cellText(td) {
  if (!td) return '';
  const sel = td.querySelector('select');
  if (sel) return clean(sel.selectedOptions[0]?.textContent);
  const s = clean(td.textContent);
  if (s) return /^[—–-]$/.test(s) ? '' : s;
  const cb = td.querySelector('input[type=checkbox]');
  if (cb) return cb.checked ? '✓' : '';
  const x = td.querySelector('[title], [aria-label], img[alt]');
  return x ? clean(x.getAttribute('title') || x.getAttribute('aria-label') || x.getAttribute('alt')) : '';
}

const D_TR = /^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:[ ,T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;
const D_ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/;
const D_MON = /^(\d{1,2}) (oca|sub|mar|nis|may|haz|tem|agu|eyl|eki|kas|ara)[a-z]*\.?(?: (\d{4}))?(?:[ ,]+(\d{1,2}):(\d{2}))?$/;
const MONTHS = ['oca', 'sub', 'mar', 'nis', 'may', 'haz', 'tem', 'agu', 'eyl', 'eki', 'kas', 'ara'];
const T_HM = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/;
const DUR = /^(?:\d+\s*(?:gün|g|saat|sa|dk|sn)\s*)+$/i;
const DUR_SEC = { g: 86400, gün: 86400, sa: 3600, saat: 3600, dk: 60, sn: 1 };
const NUM = /^([-+−]?)\s*(?:[₺$€£]\s*|%\s*)?(\d[\d.,]*)\s*(%|[^\d\s.,%][^\d]{0,9})?$/;
const BYTES = { b: 1, kb: 1e3, mb: 1e6, gb: 1e9, tb: 1e12 };

function numOf(body) {
  if (body.includes(',')) {
    if (body.includes('.') && body.lastIndexOf('.') > body.lastIndexOf(',')) body = body.replace(/,/g, '');   // 1,234.56
    else body = body.replace(/\./g, '').replace(',', '.');                                                   // 1.234,56
  } else if (body.includes('.')) {
    if (/^\d{1,3}(\.\d{3})+$/.test(body)) body = body.replace(/\./g, '');   // 1.234 → bin ayırıcı
    else if (!/^\d+\.\d+$/.test(body)) return NaN;
  }
  return Number(body);
}
// Metin → [tür, sayısal değer] | null. Tür: 'date' (ms), 'dur' (sn), 'num'.
export function parse(s) {
  let m;
  if ((m = D_TR.exec(s))) return ['date', new Date(+m[3], m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)).getTime()];
  if ((m = D_ISO.exec(s))) return ['date', new Date(+m[1], m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0)).getTime()];
  if ((m = T_HM.exec(s))) return ['dur', m[1] * 3600 + m[2] * 60 + +(m[3] || 0)];
  if (DUR.test(s)) {
    let tot = 0;
    s.replace(/(\d+)\s*(gün|g|saat|sa|dk|sn)/gi, (_, n, u) => { tot += n * DUR_SEC[u.toLowerCase()]; return ''; });
    return ['dur', tot];
  }
  if ((m = NUM.exec(s))) {
    const n = numOf(m[2]);
    if (!Number.isNaN(n)) return ['num', (m[1] === '-' || m[1] === '−' ? -n : n) * (BYTES[(m[3] || '').trim().toLowerCase()] || 1)];
  }
  if (/^\d{1,2} \D/.test(s) && (m = D_MON.exec(fold(s)))) {
    return ['date', new Date(+(m[3] || new Date().getFullYear()), MONTHS.indexOf(m[2]), +m[1], +(m[4] || 0), +(m[5] || 0)).getTime()];
  }
  return null;
}

// ---------- Tablo modeli ----------
// Gövde → bölümler: { head: [tr], units: [{ tr, extra: [tr] }], tail: [tr] }. Birim = tam (başlık kadar hücreli) satır + ayrıntı satırları.
function build(table) {
  const n = table.tHead.rows[0].cells.length;
  const M = { n, units: [], blocks: [], kinds: [] };
  const wide = tr => n > 1 && tr.cells.length === 1;
  for (const tb of table.tBodies) {
    const rows = [...tb.rows];
    const group = rows.length > 1 && wide(rows[0]);
    let sec = { head: [], units: [], tail: [] }, last = null;
    const secs = [sec];
    for (const tr of rows) {
      if (tr.cells.length === n) {
        let i = ORIG.get(tr);
        if (i === undefined) ORIG.set(tr, i = ++seq);
        last = { tr, i, extra: [], txt: [], par: [] };
        sec.units.push(last);
        M.units.push(last);
      } else if (wide(tr) && group) {
        secs.push(sec = { head: [tr], units: [], tail: [] });
        last = null;
      } else if (wide(tr) && last) last.extra.push(tr);
      else (sec.units.length ? sec.tail : sec.head).push(tr);   // toplam / ara satır: yerinde kalır
    }
    M.blocks.push({ tb, rows, secs, group });
  }
  return M;
}
function txt(u, c) {
  let v = u.txt[c];
  if (v === undefined) v = u.txt[c] = cellText(u.tr.cells[c]);
  return v;
}
function raw(u, c) {
  const d = u.tr.cells[c]?.dataset.sort;
  return d != null ? clean(d) : txt(u, c);
}
function par(u, c) {
  let p = u.par[c];
  if (p === undefined) { const r = raw(u, c); p = u.par[c] = r ? parse(r) : null; }
  return p;
}
function kind(M, c) {
  if (M.kinds[c]) return M.kinds[c];
  const tally = { num: 0, date: 0, dur: 0 };
  let filled = 0;
  for (const u of M.units) {
    if (!raw(u, c)) continue;
    filled++;
    const p = par(u, c);
    if (p) tally[p[0]]++;
  }
  const best = Object.keys(tally).sort((a, b) => tally[b] - tally[a])[0];
  return (M.kinds[c] = filled && tally[best] >= filled * 0.7 ? best : 'text');
}
function val(M, u, c) {
  const p = par(u, c);
  return p && p[0] === kind(M, c) ? p[1] : null;
}
function comparer(M, c, dir) {
  const k = kind(M, c);
  return (a, b) => {
    const ra = raw(a, c), rb = raw(b, c);
    if (!ra || !rb) return ra ? -1 : rb ? 1 : a.i - b.i;   // boşlar her yönde sonda
    let d;
    if (k === 'text') d = COLL.compare(ra, rb);
    else {
      const va = val(M, a, c), vb = val(M, b, c);
      if (va === null || vb === null) {                   // tipe uymayanlar dolu olanların ardında
        if (va !== null) return -1;
        if (vb !== null) return 1;
        d = COLL.compare(ra, rb);
      } else d = va - vb;
    }
    return d ? d * dir : a.i - b.i;
  };
}

// ---------- Filtre ----------
const newF = () => ({ q: '', mode: 'ex', set: new Set(), a: '', b: '', lo: null, hi: null });
const on = F => !!(F.q || F.set.size || F.mode === 'in' || F.lo !== null || F.hi !== null);
function pass(M, u, c, F) {
  const s = txt(u, c);
  if (F.q && !fold(s).includes(fold(F.q))) return false;
  if (F.mode === 'in' ? !F.set.has(s) : F.set.has(s)) return false;
  if (F.lo !== null || F.hi !== null) {
    const v = val(M, u, c);
    if (v === null || (F.lo !== null && v < F.lo) || (F.hi !== null && v > F.hi)) return false;
  }
  return true;
}

// ---------- Durum ----------
const moduleOf = () => location.hash.split('?')[0].split('/')[1] || '';
const pathOf = () => location.hash.split('?')[0].replace(/\/\d+(?=\/|$)/g, '/*');
function state(table) {
  let st = STATE.get(table.__dtk);
  if (!st) STATE.set(table.__dtk, st = { sort: null, filters: new Map() });
  return st;
}
function eligible(table) {
  const hr = table.tHead?.rows;
  if (!hr || hr.length !== 1 || !hr[0].cells.length || !table.tBodies.length || table.closest(SKIP)) return false;
  for (const c of hr[0].cells) if (c.colSpan > 1 || c.rowSpan > 1 || c.classList.contains('sortable')) return false;
  const n = hr[0].cells.length;
  for (const tb of table.tBodies) {
    if (tb.querySelector(':scope > tr[draggable="true"], :scope > tr > [rowspan]:not([rowspan="1"])')) return false;
    for (const f of tb.querySelectorAll(EDIT)) {
      const tr = f.closest('tr');
      if (tr.parentNode === tb && tr.cells.length === n) return false;   // satır içi düzenleme tablosu
    }
  }
  return true;
}

function decorate(table) {
  for (const th of table.tHead.rows[0].cells) {
    if (th.querySelector(':scope > .dt-f')) continue;
    if (!label(th) || th.dataset.dt === 'off' || th.querySelector('input, select, button, a')) { th.classList.remove('dt-th'); continue; }
    th.classList.add('dt-th');
    const s = el('span', 'dt-s');
    s.setAttribute('aria-hidden', 'true');
    const f = el('button', 'dt-f');
    f.type = 'button';
    f.title = t('Filtrele');
    f.setAttribute('aria-label', `${t('Filtrele')}: ${label(th)}`);
    f.innerHTML = FUNNEL;
    f.addEventListener('click', e => {
      e.stopPropagation();
      e.preventDefault();
      if (pop && pop.th === th) closePop(); else openPop(table, th);
    });
    th.append(s, f);
    if (!th.__dt) {
      th.__dt = true;
      th.addEventListener('click', e => {
        if (!table.classList.contains('dt-on') || !th.classList.contains('dt-th') || e.target.closest('.dt-f, a, button, input, select, label')) return;
        cycle(table, th.cellIndex);
      });
    }
  }
}
function cycle(table, col, dir) {
  const st = state(table);
  const cur = st.sort?.col === col ? st.sort.dir : 0;
  if (dir) st.sort = cur === dir ? null : { col, dir };
  else st.sort = cur === 0 ? { col, dir: 1 } : cur === 1 ? { col, dir: -1 } : null;
  refresh(table.__dtk);
}

const hide = (tr, v) => { if (tr.classList.contains('dt-hide') !== v) tr.classList.toggle('dt-hide', v); };
function setCap(table, shown, total, active, key) {
  let cap = table.querySelector(':scope > caption.dt-cap');
  if (!active) { cap?.remove(); return; }
  if (!cap && table.caption) return;   // tablonun kendi başlığı varsa dokunma
  const text = t('{n} / {N} kayıt gösteriliyor', { n: shown, N: total });
  if (!cap) {
    cap = el('caption', 'dt-cap');
    const x = el('button', null, t('Filtreleri temizle'));
    x.type = 'button';
    x.addEventListener('click', () => { STATE.get(key)?.filters.clear(); closePop(); refresh(key); });
    const inner = el('span', 'dt-cap-in');
    inner.append(el('span', 'dt-cap-t', text), x);
    cap.append(inner);
    table.prepend(cap);
  } else {
    const s = cap.querySelector('.dt-cap-t');
    if (s.textContent !== text) s.textContent = text;
  }
}

function apply(table) {
  const key = table.__dtk, st = STATE.get(key);
  const flt = st ? [...st.filters].filter(([, F]) => on(F)) : [];
  const heads = table.tHead.rows[0].cells;
  for (let c = 0; c < heads.length; c++) {
    const th = heads[c];
    const s = th.classList.contains('dt-th') && st?.sort?.col === c ? (st.sort.dir > 0 ? 'ascending' : 'descending') : null;
    if (s) th.setAttribute('aria-sort', s); else if (th.hasAttribute('aria-sort') && th.__dt) th.removeAttribute('aria-sort');
    th.querySelector(':scope > .dt-f')?.classList.toggle('on', flt.some(([i]) => i === c));
  }
  if (!flt.length && !st?.sort && !table.__dtTouched) return;
  const M = build(table);
  let shown = 0;
  for (const u of M.units) {
    u.ok = flt.every(([c, F]) => pass(M, u, c, F));
    if (u.ok) shown++;
  }
  const cmp = st?.sort && st.sort.col < M.n ? comparer(M, st.sort.col, st.sort.dir) : null;
  const a = document.activeElement;
  const busy = !!a && a !== document.body && table.contains(a) && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName);   // yazarken satır taşıma
  for (const b of M.blocks) {
    if ((cmp || table.__dtSorted) && !busy) {
      const want = [];
      for (const s of b.secs) {
        const us = [...s.units].sort(cmp || ((x, y) => x.i - y.i));
        want.push(...s.head);
        for (const u of us) want.push(u.tr, ...u.extra);
        want.push(...s.tail);
      }
      if (want.some((tr, i) => tr !== b.rows[i])) b.tb.append(...want);
    }
    for (const s of b.secs) {
      for (const u of s.units) { hide(u.tr, !u.ok); for (const x of u.extra) hide(x, !u.ok); }
      if (b.group && s.units.length) for (const x of s.head) hide(x, flt.length > 0 && !s.units.some(u => u.ok));
      for (const x of s.tail) x.classList.toggle('dt-stale', flt.length > 0);
    }
  }
  table.__dtSorted = !!cmp || (busy && !!table.__dtSorted);
  const foot = table.tFoot;
  if (foot) {
    foot.classList.toggle('dt-stale', flt.length > 0);
    if (flt.length) foot.title = t('Toplamlar tüm kayıtlar içindir');
    else if (foot.title === t('Toplamlar tüm kayıtlar içindir')) foot.removeAttribute('title');
  }
  setCap(table, shown, M.units.length, flt.length > 0, key);
  table.__dtTouched = flt.length > 0 || !!cmp || table.__dtSorted;
}
function refresh(key) {
  for (const tb of document.querySelectorAll('table.dt-on')) if (tb.__dtk === key) apply(tb);
}

// ---------- Filtre penceresi ----------
let pop = null;   // { box, th, key, off }
function closePop() {
  if (!pop) return;
  const p = pop;
  pop = null;
  p.off();
  p.box.remove();
  p.th.querySelector(':scope > .dt-f')?.classList.remove('open');
}
function openPop(table, th) {
  closePop();
  const key = table.__dtk, col = th.cellIndex, st = state(table);
  const M = build(table), k = kind(M, col);
  let F = st.filters.get(col);
  if (!F) st.filters.set(col, F = newF());
  const others = [...st.filters].filter(([c, f]) => c !== col && on(f));
  const counts = new Map();
  for (const u of M.units) {
    if (!others.every(([c, f]) => pass(M, u, c, f))) continue;
    const v = txt(u, col);
    counts.set(v, (counts.get(v) || 0) + 1);
  }
  for (const v of F.set) if (!counts.has(v)) counts.set(v, 0);
  const pv = new Map([...counts.keys()].map(v => { const p = v ? parse(v) : null; return [v, p && p[0] === k ? p[1] : null]; }));
  const vals = [...counts.keys()].sort((x, y) => {
    if (!x || !y) return x ? -1 : y ? 1 : 0;
    const a = pv.get(x), b = pv.get(y);
    return a !== null && b !== null ? a - b || COLL.compare(x, y) : a !== null ? -1 : b !== null ? 1 : COLL.compare(x, y);
  });

  const box = el('div', 'dt-pop');
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', `${t('Filtrele')}: ${label(th)}`);
  const go = () => refresh(key);

  const sortRow = el('div', 'dt-pop-sort');
  const sortBtns = [[1, '↑', 'Artan'], [-1, '↓', 'Azalan']].map(([dir, arrow, text]) => {
    const b = el('button', null, `${arrow} ${t(text)}`);
    b.type = 'button';
    b.addEventListener('click', () => {
      const live = [...document.querySelectorAll('table.dt-on')].find(x => x.__dtk === key) || table;
      cycle(live, col, dir);
      paintSort();
    });
    sortRow.append(b);
    return [dir, b];
  });
  const paintSort = () => { for (const [dir, b] of sortBtns) b.classList.toggle('on', st.sort?.col === col && st.sort.dir === dir); };
  paintSort();

  const q = el('input', 'dt-pop-q');
  q.type = 'search';
  q.placeholder = t('Ara…');
  q.value = F.q;
  q.addEventListener('input', () => { F.q = q.value.trim(); list(); go(); });

  let range = null;
  const rangeIn = [];
  if (k === 'num' || k === 'date') {
    range = el('div', 'dt-pop-range');
    const bound = (field, text) => {
      const i = el('input');
      if (k === 'date') i.type = 'date'; else { i.type = 'text'; i.inputMode = 'decimal'; }
      i.value = F[field];
      i.addEventListener('input', () => {
        F[field] = i.value.trim();
        let v = null;
        if (F[field] && k === 'date') {
          const [y, m, d] = F[field].split('-').map(Number);
          v = field === 'a' ? new Date(y, m - 1, d).getTime() : new Date(y, m - 1, d, 23, 59, 59, 999).getTime();
        } else if (F[field]) { const p = parse(F[field]); v = p && p[0] === 'num' ? p[1] : null; }
        F[field === 'a' ? 'lo' : 'hi'] = Number.isNaN(v) ? null : v;
        go();
      });
      const l = el('label');
      l.append(el('span', null, t(text)), i);
      rangeIn.push(i);
      return l;
    };
    range.append(bound('a', k === 'date' ? 'Başlangıç' : 'En az'), bound('b', k === 'date' ? 'Bitiş' : 'En çok'));
  }

  const all = el('input');
  all.type = 'checkbox';
  const allRow = el('label', 'dt-pop-i dt-pop-all');
  allRow.append(all, el('span', 'dt-pop-v', t('Tümünü seç')));
  all.addEventListener('change', () => { F.mode = all.checked ? 'ex' : 'in'; F.set.clear(); list(); go(); });
  const listEl = el('div', 'dt-pop-list');
  const checked = v => (F.mode === 'in' ? F.set.has(v) : !F.set.has(v));
  function paintAll() {
    all.checked = F.mode === 'ex' && !F.set.size;
    all.indeterminate = !all.checked && vals.some(checked);
  }
  function list() {
    const needle = fold(F.q);
    const vis = needle ? vals.filter(v => fold(v).includes(needle)) : vals;
    const frag = document.createDocumentFragment();
    for (const v of vis.slice(0, LIST_MAX)) {
      const cb = el('input');
      cb.type = 'checkbox';
      cb.checked = checked(v);
      cb.addEventListener('change', () => {
        if ((F.mode === 'in') === cb.checked) F.set.add(v); else F.set.delete(v);
        paintAll();
        go();
      });
      const row = el('label', 'dt-pop-i');
      row.append(cb, el('span', `dt-pop-v${v ? '' : ' muted'}`, v || t('(Boş)')), el('span', 'dt-pop-c', String(counts.get(v))));
      frag.append(row);
    }
    if (vis.length > LIST_MAX) frag.append(el('div', 'dt-pop-more', `… +${vis.length - LIST_MAX}`));
    listEl.replaceChildren(frag);
    paintAll();
  }
  list();

  const foot = el('div', 'dt-pop-foot');
  const clr = el('button', 'dt-pop-clr', t('Temizle'));
  clr.type = 'button';
  clr.addEventListener('click', () => {
    Object.assign(F, newF());
    q.value = '';
    for (const i of rangeIn) i.value = '';
    list();
    go();
  });
  const ok = el('button', 'dt-pop-ok', t('Tamam'));
  ok.type = 'button';
  ok.addEventListener('click', closePop);
  foot.append(clr, ok);

  box.append(el('div', 'dt-pop-h', label(th)), sortRow, q);
  if (range) box.append(range);
  box.append(allRow, listEl, foot);
  document.body.append(box);

  const r = th.getBoundingClientRect(), W = box.offsetWidth, vh = window.innerHeight;
  let top = r.bottom + 4;
  if (vh - top < 260 && r.top > vh - r.bottom) top = Math.max(8, r.top - 4 - Math.min(box.offsetHeight, r.top - 12));   // altta yer yoksa üste aç
  box.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - W - 8))}px`;
  box.style.top = `${top}px`;
  box.style.maxHeight = `${Math.max(180, vh - top - 8)}px`;

  const onDown = e => { if (!box.contains(e.target) && !e.target.closest?.('.dt-f')) closePop(); };
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.stopImmediatePropagation();   // açık modal bununla kapanmasın
    e.preventDefault();
    const f = th.querySelector(':scope > .dt-f');
    closePop();
    f?.focus();
  };
  const onScroll = e => { if (!box.contains(e.target)) closePop(); };
  document.addEventListener('mousedown', onDown, true);
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('scroll', onScroll, true);
  window.addEventListener('resize', closePop);
  th.querySelector(':scope > .dt-f')?.classList.add('open');
  pop = {
    box, th, key,
    off() {
      document.removeEventListener('mousedown', onDown, true);
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', closePop);
    },
  };
  if (!matchMedia('(hover: none)').matches) q.focus();   // dokunmatikte klavye kendiliğinden açılmasın
}

// ---------- Gözlemci ----------
let raf = 0, full = true, obs = null;
const dirty = new Set();
const queue = () => { if (!raf) raf = requestAnimationFrame(sweep); };
function process(table) {
  if (!eligible(table)) { table.classList.remove('dt-on'); return; }
  table.classList.add('dt-on');
  decorate(table);
  apply(table);
}
function rescan() {
  const count = new Map(), path = pathOf();
  for (const tb of document.querySelectorAll('table')) {
    if (!tb.tHead) continue;
    const base = `${path}${tb.closest('.modal') ? '@m' : ''}|${[...tb.tHead.rows[0]?.cells || []].map(label).join('¦')}`;
    const n = count.get(base) || 0;
    count.set(base, n + 1);
    tb.__dtk = `${base}|${n}`;
    process(tb);
  }
}
function sweep() {
  raf = 0;
  if (!full) for (const tb of dirty) if (tb.isConnected && !tb.__dtk) { full = true; break; }
  if (full) rescan();
  else for (const tb of dirty) if (tb.isConnected) process(tb);
  full = false;
  dirty.clear();
  obs?.takeRecords();   // kendi değişikliklerimiz yeni tur başlatmasın
}
function onMutations(list) {
  for (const m of list) {
    const host = m.target.nodeType === 1 ? m.target : m.target.parentElement;
    if (!host || host.closest('.dt-pop')) continue;
    for (let tb = host.closest('table'); tb; tb = tb.parentElement?.closest('table')) dirty.add(tb);
    if (!full) {
      for (const n of [...m.addedNodes, ...m.removedNodes]) {
        if (n.nodeType === 1 && (n.tagName === 'TABLE' || n.tagName === 'THEAD' || n.querySelector('table'))) { full = true; break; }
      }
    }
  }
  if (full || dirty.size) queue();
}

export function enableDataTables() {
  if (obs) return;
  let mod = moduleOf();
  window.addEventListener('hashchange', () => {
    closePop();
    if (moduleOf() !== mod) {   // modül değişti: filtreler bırakılır (sıralama tercihi kalır)
      mod = moduleOf();
      for (const [k, st] of STATE) { st.filters.clear(); if (!st.sort) STATE.delete(k); }
    }
    full = true;
    queue();
  });
  obs = new MutationObserver(onMutations);
  obs.observe(document.body, { childList: true, subtree: true });
  queue();
}
