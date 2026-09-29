// Küçük DOM yardımcıları: öğe oluşturma, modal, bildirim, biçimlendirme.
import { fileUrl } from './api.js';
import { segIcon } from './segicons.js';

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function svgIcon(markup) {
  const wrap = document.createElement('span');
  wrap.style.display = 'contents';
  wrap.innerHTML = markup;
  return wrap.firstElementChild;
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

// ---------- Bildirim ----------
let toastBox;
export function toast(message, type = '') {
  if (!toastBox) toastBox = document.body.appendChild(h('div', { class: 'toasts' }));
  const t = toastBox.appendChild(h('div', { class: `toast ${type}` }, message));
  setTimeout(() => t.remove(), type === 'err' ? 6000 : 3500);
}
export const toastError = err => toast(err?.message || String(err), 'err');

// Firma kısa adı (Firmalar modülü dışında): ilk kelime; "T. C. …", "4N …", "C TECH …" gibi kısaltmalarda anlamlı
// bir kelimeye (3+ harf) ulaşana kadar devam edilir. Tam ad üzerine gelince (title) gösterilir.
export function shortCompany(name) {
  const words = String(name || '').trim().split(/\s+/).filter(Boolean);
  const out = [];
  for (const w of words) {
    out.push(w);
    if (w.replace(/[^\p{L}]/gu, '').length >= 3) break;
  }
  return out.join(' ');
}
export const companyName = (name, attrs = {}) => h('span', { title: name, ...attrs }, shortCompany(name));

// ---------- Modal ----------
// modal({ title, body, actions: [{label, class, onClick}], wide }) → { close, el }
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const foot = h('div', { class: 'modal-foot' });
  const box = h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true' },
    h('div', { class: 'modal-head' }, h('h2', null, title),
      h('button', { class: 'x-btn', 'aria-label': 'Kapat', onclick: () => close() }, '×')),
    h('div', { class: 'modal-body' }, body),
    actions.length ? foot : null);
  const back = h('div', { class: 'modal-back' }, box);
  back.addEventListener('mousedown', e => { if (e.target === back) close(); });
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  window.addEventListener('hashchange', close, { once: true });   // sayfa değişince açık pencere kapanır

  let closed = false;
  function close() {
    if (closed) return;
    closed = true;
    back.remove();
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('hashchange', close);
    onClose?.();
  }
  for (const a of actions) {
    if (a === 'spacer') { foot.append(h('span', { class: 'spacer' })); continue; }
    const b = h('button', { class: `btn ${a.class || ''}` }, a.label);
    b.addEventListener('click', async () => {
      if (!a.onClick) return close();
      b.disabled = true;
      try {
        const keep = await a.onClick({ close, button: b });
        if (keep !== true) close();
      } catch (err) {
        toastError(err);
      } finally {
        b.disabled = false;
      }
    });
    foot.append(b);
  }
  document.body.append(back);
  box.querySelector('input, select, textarea')?.focus();
  return { close, el: box };
}

export function confirmDialog(title, message, { okLabel = 'Onayla', danger = false } = {}) {
  return new Promise(resolve => {
    let answered = false;
    modal({
      title, body: h('p', { style: { margin: 0 } }, message),
      onClose: () => { if (!answered) resolve(false); },
      actions: [
        { label: 'Vazgeç' },
        { label: okLabel, class: danger ? 'danger' : 'primary', onClick: () => { answered = true; resolve(true); } },
      ],
    });
  });
}

// ---------- Biçimlendirme ----------
const pad = n => String(n).padStart(2, '0');
export function fmtDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
}
export function fmtDuration(sec) {
  if (sec === null || sec === undefined) return '—';
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hh = Math.floor(sec % 86400 / 3600), mm = Math.floor(sec % 3600 / 60), ss = sec % 60;
  if (d) return `${d} g ${hh} sa ${mm} dk`;
  if (hh) return `${hh} sa ${mm} dk`;
  return `${mm} dk ${pad(ss)} sn`;
}
export const secondsSince = iso => (Date.now() - new Date(iso).getTime()) / 1000;
export const secondsBetween = (a, b) => (a && b ? (new Date(b).getTime() - new Date(a).getTime()) / 1000 : null);
// Baskı süresi (dakika) → "9 sa 16 dk", "1 g 3 sa 20 dk"
export const fmtMinutes = min => (min || min === 0 ? fmtDuration(min * 60).replace(/ 00 sn$| \d+ sn$/, '') : '—');

export function avatar(user, size = '') {
  const initials = (user.full_name || user.username || '?')
    .split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toLocaleUpperCase('tr')).join('');
  return h('span', { class: `avatar ${size}` },
    user.photo ? h('img', { src: fileUrl(user.photo, size === 'lg' || size === 'xl' ? 512 : 128), alt: '', loading: 'lazy' }) : initials);
}

// Yükleme çubuğu + iptal düğmesi. start() → AbortController sinyali (yükleme fonksiyonuna verilir).
export function uploadPanel() {
  let ctl = null;
  const bar = h('div', { class: 'grow' });
  const cancel = h('button', { class: 'btn sm danger', type: 'button', onclick: () => ctl?.abort() }, 'Yüklemeyi İptal Et');
  const el = h('div', { class: 'upload-progress upload-panel', hidden: true }, bar, cancel);
  el.start = () => { ctl = new AbortController(); el.hidden = false; clear(bar); return ctl.signal; };
  el.set = (label, pct) => clear(bar, h('div', { class: 'small muted' }, label), progressBar(pct));
  el.done = () => { el.hidden = true; ctl = null; };
  el.abort = () => ctl?.abort();
  return el;
}

// İnternetten (caymaz.app) bağlanınca büyük dosya yükleme yerine gösterilen uyarı: yerel adrese bağlantı
export function localUploadNotice(meta, what = 'Video ve uçuş logu') {
  const url = `${meta.local_url}/${location.hash}`;
  return h('div', { class: 'alert warn', style: { marginBottom: 0 } },
    h('b', null, `${what} yalnızca yerel ağdan yüklenebilir. `),
    'İnternet üzerinden yükleme çok yavaş olduğu için bu işlem şirket ağına bağlıyken yapılır: ',
    h('a', { href: url }, meta.local_url), '.');
}

export function progressBar(pct) {
  return h('div', { class: 'progress-line' },
    h('div', { class: 'progress', style: { flex: '1' } }, h('i', { style: { width: `${pct}%` } })),
    h('b', null, `%${pct}`));
}

export function field(label, control, hint) {
  return h('div', { class: 'field' }, h('label', null, label), control, hint ? h('div', { class: 'hint' }, hint) : null);
}

export function segmented(options, value, onChange) {
  const el = h('div', { class: 'seg' });
  const render = v => {
    el.replaceChildren(...options.map(([key, label]) =>
      h('button', { class: key === v ? 'on' : '', type: 'button', onclick: () => { render(key); onChange(key); } }, segIcon(label), label)));
  };
  render(value);
  return el;
}

export function pageHead(title, { back, sub, right } = {}) {
  return h('div', { class: 'page-head' },
    back ? h('a', { class: 'back', href: back, 'aria-label': 'Geri' }, '←') : null,
    h('div', null, h('h1', null, title), sub ? h('div', { class: 'sub' }, sub) : null),
    h('div', { class: 'spacer' }),
    right || null);
}

// Görünüm tercihlerini (kart/liste vb.) tarayıcıda hatırla.
export function pref(key, fallback) {
  try { return localStorage.getItem(`caymaz.${key}`) || fallback; } catch { return fallback; }
}
export function setPref(key, value) {
  try { localStorage.setItem(`caymaz.${key}`, value); } catch { /* yok say */ }
}

// Sayfa değişince durdurulan zamanlayıcılar ve temizlik işleri (ör. animasyonlar)
const timers = new Set();
const cleanups = new Set();
export function every(ms, fn) {
  const id = setInterval(fn, ms);
  timers.add(id);
  return id;
}
export function onLeave(fn) {
  cleanups.add(fn);
}
export function stopTimers() {
  timers.forEach(clearInterval);
  timers.clear();
  cleanups.forEach(fn => fn());
  cleanups.clear();
}

// Modül üstü özet sayılar: [{ label, value, sub?, tone?: 'alert' | 'ok' | 'muted' }]
// ---------- Tarih-saat seçici (flatpickr, Türkçe) ----------
// İşlem zamanını kullanıcı serbestçe seçer; varsayılan şimdi. getValue() → 'YYYY-MM-DDTHH:MM+03:00'
// (cihazın yerel saati ve saat dilimi; sunucu kendi saatine çevirir).
const isoLocal = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
export function dateTimeInput({ value, min } = {}) {
  const input = h('input', { class: 'input', type: window.flatpickr ? 'text' : 'datetime-local' });
  const now = () => new Date();
  let fp = null;
  const nowBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => {
    if (fp) fp.setDate(now(), true); else input.value = isoLocal(now());
  } }, 'Şimdi');
  const el = h('div', { class: 'dt-field' }, input, nowBtn);   // flatpickr görünür kutuyu input'un yanına ekler
  if (window.flatpickr) {
    fp = window.flatpickr(input, {
      enableTime: true, time_24hr: true, locale: 'tr', minuteIncrement: 1,
      dateFormat: 'Y-m-d\\TH:i', altInput: true, altFormat: 'd.m.Y  H:i', altInputClass: 'input dt-alt',
      defaultDate: value ? new Date(value) : now(), minDate: min ? new Date(min) : null,
    });
  } else {
    input.value = isoLocal(value ? new Date(value) : now());
  }
  el.getValue = () => {
    if (!input.value) return null;
    const off = -new Date(input.value).getTimezoneOffset();   // seçilen andaki saat dilimi farkı (dakika)
    return `${input.value}${off >= 0 ? '+' : '-'}${pad(Math.floor(Math.abs(off) / 60))}:${pad(Math.abs(off) % 60)}`;
  };
  return el;
}

// Çoklu kişi seçimi (ör. montaj personeli): kartlara dokunarak seçilir. getIds() → seçilen id'ler.
export function peoplePicker(people, { empty = 'Kişi yok', selected = [], sub = p => p.username || '' } = {}) {
  const chosen = new Set(selected);
  const el = h('div', { class: 'pick-list multi' }, people.length ? people.map(p => {
    const cb = h('input', { type: 'checkbox', checked: chosen.has(p.id) });
    const row = h('div', { class: `pick ${chosen.has(p.id) ? 'on' : ''}` }, cb,
      h('div', { class: 'grow' }, h('b', null, p.full_name), h('span', { class: 'small muted' }, sub(p))));
    row.addEventListener('click', e => {
      if (e.target !== cb) cb.checked = !cb.checked;
      cb.checked ? chosen.add(p.id) : chosen.delete(p.id);
      row.classList.toggle('on', cb.checked);
    });
    return row;
  }) : h('div', { class: 'empty' }, empty));
  el.getIds = () => [...chosen];
  return el;
}

export function statStrip() {
  const el = h('div', { class: 'stat-strip' });
  el.set = stats => clear(el, stats.filter(Boolean).map(s =>
    h('div', { class: `stat ${s.tone || ''}` },
      h('span', { class: 'v' }, s.value ?? '—'),
      h('span', { class: 'l' }, s.label),
      s.sub ? h('span', { class: 's' }, s.sub) : null)));
  return el;
}

export function selectInput(options, { all = 'Tümü', value = '' } = {}) {
  return h('select', { class: 'input' },
    all ? h('option', { value: '' }, all) : null,
    options.map(([v, label]) => h('option', { value: v, selected: String(v) === String(value) }, label)));
}

// Türkçe büyük/küçük harf duyarsız arama
export const matches = (term, ...values) => {
  const t = term.trim().toLocaleLowerCase('tr');
  return !t || values.some(v => v != null && String(v).toLocaleLowerCase('tr').includes(t));
};

// Çoklu seçim açılır listesi (onay kutulu). options: [[değer, etiket, ek?]], selected: değerler; onChange(değerler).
// Düğmede "Etiket: 6/8" yazar; dışarı tıklanınca kapanır. extra: panelin altına eklenecek öğe (ör. "Varsayılan" düğmesi).
export function multiSelect(label, options, selected, onChange, { extra = null, min = 0 } = {}) {
  let chosen = new Set(selected);
  const btn = h('button', { class: 'input ms-btn', type: 'button', 'aria-haspopup': 'listbox' });
  const panel = h('div', { class: 'ms-panel', hidden: true, role: 'listbox' });
  const wrap = h('div', { class: 'ms' }, btn, panel);
  const drawBtn = () => { btn.textContent = `${label}: ${chosen.size}/${options.length}`; };
  const drawPanel = () => clear(panel, options.map(([v, text, note]) => {
    const cb = h('input', { type: 'checkbox', checked: chosen.has(v) });
    cb.addEventListener('change', () => {
      if (!cb.checked && chosen.size <= min) { cb.checked = true; return; }
      cb.checked ? chosen.add(v) : chosen.delete(v);
      drawBtn();
      onChange(options.map(o => o[0]).filter(x => chosen.has(x)));
    });
    return h('label', { class: 'ms-row' }, cb, h('span', { class: 'grow' }, text), note != null ? h('span', { class: 'ms-note' }, note) : null);
  }), extra);
  btn.addEventListener('click', () => { panel.hidden = !panel.hidden; if (!panel.hidden) drawPanel(); });
  const outside = e => { if (!wrap.contains(e.target)) panel.hidden = true; };
  document.addEventListener('click', outside);
  onLeave(() => document.removeEventListener('click', outside));
  wrap.set = (values, opts) => { if (opts) options = opts; chosen = new Set(values); drawBtn(); if (!panel.hidden) drawPanel(); };
  drawBtn();
  return wrap;
}
