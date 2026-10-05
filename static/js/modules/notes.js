// Kişisel Notlar (yapışkan not): Kişisel › Notlar modülü + panodaki "Notlar" kutucuğu + ekrana iğnelenen global notlar.
// Yalnız sahibi görür. Not ekrana iğnelenirse (pinned) hangi modülde olunursa olunsun ekranda kalır (global katman).
import { api } from '../api.js';
import { clear, confirmDialog, h, pageHead, t, toast, toastError } from '../ui.js';

export const NOTE_COLORS = [['yellow', 'Sarı'], ['green', 'Yeşil'], ['blue', 'Mavi'], ['pink', 'Pembe'], ['orange', 'Turuncu'], ['purple', 'Mor']];
const notify = () => window.dispatchEvent(new CustomEvent('caymaz:notes-changed'));

// Düzenlenebilir yapışkan not kartı: metin (blur'da kaydedilir), renk, iğnele/çıkar, sil
export function noteCard(n, { onChange, onDelete, pinToggle = true } = {}) {
  const txt = h('div', { class: 'note-txt', contenteditable: 'plaintext-only', spellcheck: 'true', 'data-ph': 'Not yazın…' }, n.body || '');
  const save = async patch => { try { const r = await api.put(`/api/notes/${n.id}`, patch); Object.assign(n, r); onChange?.(n); notify(); } catch (e) { toastError(e); } };
  txt.addEventListener('blur', () => { const v = txt.innerText.trim(); if (v !== (n.body || '')) save({ body: v }); });
  const colorBtn = h('button', { class: 'note-color', type: 'button', title: 'Renk' });
  colorBtn.addEventListener('click', e => {
    e.stopPropagation();
    const pop = h('div', { class: 'note-colors' }, NOTE_COLORS.map(([c]) => h('button', { type: 'button', class: `note-sw ${c}`, title: c,
      onclick: () => { save({ color: c }); card.className = `note-card ${c}`; pop.remove(); } })));
    card.append(pop);
    setTimeout(() => document.addEventListener('click', () => pop.remove(), { once: true }), 0);
  });
  const pinBtn = pinToggle ? h('button', { class: `note-pin ${n.pinned ? 'on' : ''}`, type: 'button', title: n.pinned ? 'İğneyi çıkar' : 'Ekrana iğnele' },
    n.pinned ? '📌' : '📍') : null;
  pinBtn?.addEventListener('click', e => { e.stopPropagation(); const p = !n.pinned; save({ pinned: p, pin_x: n.pin_x ?? 0.8, pin_y: n.pin_y ?? 0.15 }); pinBtn.classList.toggle('on', p); pinBtn.textContent = p ? '📌' : '📍'; pinBtn.title = p ? 'İğneyi çıkar' : 'Ekrana iğnele'; });
  const delBtn = h('button', { class: 'note-del', type: 'button', title: 'Sil' }, '×');
  delBtn.addEventListener('click', async e => {
    e.stopPropagation();
    if (!await confirmDialog('Notu sil', 'Bu not silinsin mi?', { okLabel: 'Sil', danger: true })) return;
    try { await api.del(`/api/notes/${n.id}`); onDelete?.(n); notify(); } catch (err) { toastError(err); }
  });
  const card = h('div', { class: `note-card ${n.color || 'yellow'}` },
    h('div', { class: 'note-bar' }, pinBtn, h('span', { class: 'grow' }), colorBtn, delBtn), txt);
  return card;
}

// Kişisel › Notlar modülü
export async function render(view, ctx) {
  let notes = [];
  const grid = h('div', { class: 'note-grid' });
  const draw = () => clear(grid, notes.length ? notes.map(n => noteCard(n, { onDelete: nn => { notes = notes.filter(x => x.id !== nn.id); draw(); } }))
    : h('div', { class: 'card empty' }, 'Henüz notunuz yok. “Yeni not” ile ekleyin.'));
  const addBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    try { const n = await api.post('/api/notes', { body: '', color: 'yellow' }); notes.unshift(n); draw(); notify();
      setTimeout(() => grid.querySelector('.note-txt')?.focus(), 30); } catch (e) { toastError(e); }
  } }, '＋ Yeni not');
  clear(view, pageHead('Notlar', { back: '#/', sub: 'Yapışkan notlarınız · yalnız siz görürsünüz' }),
    h('div', { class: 'filters' }, h('div', { class: 'spacer' }), addBtn), grid);
  try { notes = await api.get('/api/notes'); } catch (e) { clear(grid, h('div', { class: 'card empty' }, e.message)); return; }
  draw();
}

// ---------- Ekrana iğnelenen notlar (global katman; her sayfada görünür) ----------
let pinsBox = null, pinsReady = false;
export function initNotePins(ctx) {
  if (!ctx?.user) return;
  if (!pinsReady) {
    pinsReady = true;
    window.addEventListener('caymaz:notes-changed', () => refreshPins());
    window.addEventListener('resize', () => positionPins());
  }
  refreshPins();
}

async function refreshPins() {
  let notes = [];
  try { notes = await api.get('/api/notes'); } catch { return; }
  const pinned = notes.filter(n => n.pinned);
  pinsBox ||= document.body.appendChild(h('div', { class: 'note-pins' }));
  clear(pinsBox, pinned.map(pinCard));
  positionPins();
}

function positionPins() {
  if (!pinsBox) return;
  for (const el of pinsBox.children) {
    const x = Number(el.dataset.x), y = Number(el.dataset.y);
    const w = el.offsetWidth, hh = el.offsetHeight;
    el.style.left = `${Math.max(4, Math.min((x || 0.8) * innerWidth, innerWidth - w - 4))}px`;
    el.style.top = `${Math.max(56, Math.min((y || 0.15) * innerHeight, innerHeight - hh - 4))}px`;
  }
}

function pinCard(n) {
  const txt = h('div', { class: 'note-txt', contenteditable: 'plaintext-only', spellcheck: 'true' }, n.body || '');
  txt.addEventListener('blur', async () => { const v = txt.innerText.trim(); if (v !== (n.body || '')) { try { await api.put(`/api/notes/${n.id}`, { body: v }); n.body = v; } catch { /* */ } } });
  const unpin = h('button', { class: 'note-pin on', type: 'button', title: 'İğneyi çıkar' }, '📌');
  unpin.addEventListener('click', async e => { e.stopPropagation(); try { await api.put(`/api/notes/${n.id}`, { pinned: false }); el.remove(); window.dispatchEvent(new CustomEvent('caymaz:notes-changed')); } catch (err) { toastError(err); } });
  const el = h('div', { class: `note-card note-pinned ${n.color || 'yellow'}`, 'data-x': n.pin_x ?? 0.8, 'data-y': n.pin_y ?? 0.15 },
    h('div', { class: 'note-bar note-drag' }, unpin, h('span', { class: 'grow' }), h('span', { class: 'note-handle', title: 'Taşı' }, '⠿')), txt);
  // Sürükle: başlık çubuğundan; oran olarak kaydedilir (ekran boyutundan bağımsız)
  const bar = el.querySelector('.note-drag');
  let d = null;
  bar.addEventListener('pointerdown', e => {
    if (e.target.closest('button')) return;
    const r = el.getBoundingClientRect();
    d = { dx: e.clientX - r.left, dy: e.clientY - r.top, id: e.pointerId };
    bar.setPointerCapture(e.pointerId); el.classList.add('dragging');
  });
  bar.addEventListener('pointermove', e => {
    if (!d) return;
    const left = Math.max(4, Math.min(e.clientX - d.dx, innerWidth - el.offsetWidth - 4));
    const top = Math.max(56, Math.min(e.clientY - d.dy, innerHeight - el.offsetHeight - 4));
    el.style.left = `${left}px`; el.style.top = `${top}px`;
    el.dataset.x = left / innerWidth; el.dataset.y = top / innerHeight;
  });
  const end = async () => { if (!d) return; d = null; el.classList.remove('dragging'); try { await api.put(`/api/notes/${n.id}`, { pin_x: Number(el.dataset.x), pin_y: Number(el.dataset.y) }); } catch { /* */ } };
  bar.addEventListener('pointerup', end); bar.addEventListener('pointercancel', end);
  return el;
}
