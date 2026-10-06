// Kişisel → Mail (Gmail tarzı): birden çok hesap (Gmail, Outlook / Microsoft 365, Yandex, iCloud, Yahoo, IMAP / Exchange, POP3).
// Mobil: arama çubuğu + çekmece menü, avatarlı / önizlemeli liste, dokun-seç, kaydırarak arşivle / sil (geri al), aşağı çekip yenile,
// sağ altta "Oluştur", tam ekran okuma ve yazma. Masaüstü: solda klasörler, ortada liste (üzerine gelince işlemler), genişse sağda
// okuma bölmesi, sağ altta yüzen yazma penceresi. İçerik güvenli kutuda (betik çalışmaz); uzak resimler istenirse yüklenir.
import { api } from '../api.js';
import { cleanHtml } from '../sanitize.js';
import { clear, confirmDialog, h, modal, segmented, t, toast, toastError } from '../ui.js';

// ---------------- simgeler (Material) ----------------
const P = {
  menu: 'M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z',
  search: 'M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z',
  archive: 'M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5 6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z',
  unarchive: 'M20.55 5.22l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.15.55L3.46 5.22C3.17 5.57 3 6.01 3 6.5V19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.49-.17-.93-.45-1.28zM12 9.5l5.5 5.5H14v2h-4v-2H6.5L12 9.5zM5.12 5l.82-1h12l.93 1H5.12z',
  delete: 'M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z',
  unread: 'M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4-8 5-8-5V6l8 5 8-5v2z',
  read: 'M21.99 8c0-.72-.37-1.35-.94-1.7L12 1 2.95 6.3C2.38 6.65 2 7.28 2 8v10c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2l-.01-10zM12 13 3.74 7.84 12 3l8.26 4.84L12 13z',
  star: 'M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z',
  starO: 'M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28L12 15.4z',
  attach: 'M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z',
  reply: 'M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z',
  replyAll: 'M7 8V5l-7 7 7 7v-3l-4-4 4-4zm6 1V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z',
  forward: 'M14 8V4l8 8-8 8v-4.1C9 15.9 5.5 17.5 3 21c1-5 4-10 11-13z',
  more: 'M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z',
  back: 'M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z',
  close: 'M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
  send: 'M2.01 21 23 12 2.01 3 2 10l15 2-15 2z',
  edit: 'M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z',
  inbox: 'M19 3H4.99c-1.11 0-1.98.89-1.98 2L3 19c0 1.1.88 2 1.99 2H19c1.1 0 2-.9 2-2V5c0-1.11-.9-2-2-2zm0 12h-4c0 1.66-1.35 3-3 3s-3-1.34-3-3H4.99V5H19v10z',
  inboxes: 'M20 6H10v6H8V4h6V0H6v6H4v14h18V8h-2V6zm-2 12H6v-2h12v2zm0-4H6v-2h12v2z',
  draft: 'M6 2c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6H6zm7 7V3.5L18.5 9H13z',
  spam: 'M15.73 3H8.27L3 8.27v7.46L8.27 21h7.46L21 15.73V8.27L15.73 3zM12 17.3c-.72 0-1.3-.58-1.3-1.3s.58-1.3 1.3-1.3 1.3.58 1.3 1.3-.58 1.3-1.3 1.3zm1-4.3h-2V7h2v6z',
  imp: 'M3.5 18.99l11 .01c.67 0 1.27-.33 1.63-.84L20.5 12l-4.37-6.16c-.36-.51-.96-.84-1.63-.84l-11 .01L8.34 12 3.5 18.99z',
  allMail: 'M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z',
  folder: 'M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z',
  move: 'M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 12v-3h-4v-4h4V8l5 5-5 5z',
  refresh: 'M17.65 6.35A7.96 7.96 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z',
  check: 'M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z',
  expand: 'M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z',
  event: 'M17 12h-5v5h5v-5zM16 1v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2h-1V1h-2zm3 18H5V8h14v11z',
  doc: 'M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z',
  settings: 'M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.49.49 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.48.48 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.49.49 0 0 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32a.48.48 0 0 0-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z',
  home: 'M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z',
  add: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z',
  sort: 'M3 18h6v-2H3v2zM3 6v2h18V6H3zm0 7h12v-2H3v2z',
  person: 'M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z',
  business: 'M12 7V3H2v18h20V7H12zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z',
  personAdd: 'M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z',
  unfoldLess: 'M7.41 18.59 8.83 20 12 16.83 15.17 20l1.41-1.41L12 14l-4.59 4.59zm9.18-13.18L15.17 4 12 7.17 8.83 4 7.41 5.41 12 10l4.59-4.59z',
  unfoldMore: 'M12 5.83 15.17 9l1.41-1.41L12 3 7.41 7.59 8.83 9 12 5.83zm0 12.34L8.83 15l-1.41 1.41L12 21l4.59-4.59L15.17 15 12 18.17z',
  minimize: 'M6 19h12v2H6z',
  maximize: 'M21 11V3h-8l3.29 3.29-10 10L3 13v8h8l-3.29-3.29 10-10z',
  image: 'M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z',
  text: 'M5 4v3h5.5v12h3V7H19V4z',
  prev: 'M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z',
  next: 'M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z',
};
const ic = (name, title) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', `gi gi-${name}`); s.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', P[name] || P.folder); s.append(p);
  if (title) { const tt = document.createElementNS('http://www.w3.org/2000/svg', 'title'); tt.textContent = title; s.prepend(tt); }
  return s;
};
const ibtn = (name, title, onclick, cls = '') => h('button', { class: `gm-ib ${cls}`, type: 'button', title: t(title), 'aria-label': t(title), onclick }, ic(name));
const FOLDER_ICON = { inbox: 'inbox', starred: 'starO', important: 'imp', sent: 'send', drafts: 'draft', archive: 'archive', all: 'allMail', spam: 'spam', trash: 'delete' };
const PALETTE = ['#DB4437', '#E91E63', '#9C27B0', '#673AB7', '#3F51B5', '#4285F4', '#039BE5', '#0097A7', '#009688', '#0F9D58', '#689F38', '#EF6C00', '#FF5722', '#757575'];
const colorOf = s => { let x = 0; for (const c of String(s || '').toLowerCase()) x = (x * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[x % PALETTE.length]; };
const letter = a => ((a?.name || a?.email || '?').replace(/["'(<]/g, '').trim()[0] || '?').toLocaleUpperCase('tr');
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const esc = s => String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const when = iso => {
  if (!iso) return '';
  const d = new Date(iso), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
  return d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};
const full = iso => (iso ? new Date(iso).toLocaleString('tr-TR', { dateStyle: 'long', timeStyle: 'short' }) : '');
const person = a => (a ? (a.name && a.name !== a.email ? `${a.name} <${a.email}>` : a.email) : '');
const nameOf = a => (a?.name && a.name !== a.email ? a.name : a?.email || '');
const mobile = () => matchMedia('(max-width: 760px)').matches;
const wide = () => matchMedia('(min-width: 1280px)').matches;

function avatarEl(a, onclick) {
  const el = h('button', { class: 'gm-av', type: 'button', tabindex: onclick ? 0 : -1, 'aria-label': t('Seç'), onclick }, h('span', { class: 'gm-av-l' }, letter(a)), h('span', { class: 'gm-av-c' }, ic('check')));
  el.style.setProperty('--av', colorOf(a?.email || a?.name));
  return el;
}

// Açılır menü: masaüstünde düğmenin altında, mobilde alttan açılan sayfa
function popMenu(anchor, items) {
  document.querySelectorAll('.gm-pop').forEach(x => x.remove());
  const back = h('div', { class: 'gm-pop' });
  const box = h('div', { class: 'gm-pop-box', role: 'menu' }, items.filter(Boolean).map(it => it === '-' ? h('div', { class: 'gm-pop-sep' })
    : it.head ? h('div', { class: 'gm-pop-head' }, it.head)
      : h('button', { type: 'button', class: `gm-pop-i ${it.on ? 'on' : ''}`, role: 'menuitem', disabled: it.disabled,
        onclick: () => { back.remove(); it.run(); } }, it.icon ? ic(it.icon) : h('span', { class: 'gm-pop-sp' }), h('span', { class: 'grow' }, it.label),
      it.badge ? h('b', { class: 'gm-pop-n' }, it.badge) : null)));
  back.append(box);
  back.addEventListener('mousedown', e => { if (e.target === back) back.remove(); });
  back.addEventListener('touchstart', e => { if (e.target === back) { e.preventDefault(); back.remove(); } }, { passive: false });
  document.body.append(back);
  if (!mobile()) {
    const r = anchor.getBoundingClientRect();
    const w = Math.min(300, innerWidth - 16);
    box.style.left = `${Math.max(8, Math.min(r.right - w, innerWidth - w - 8))}px`;
    box.style.width = `${w}px`;
    const below = r.bottom + 4;
    if (below + 320 > innerHeight && r.top > 340) box.style.bottom = `${innerHeight - r.top + 4}px`; else box.style.top = `${below}px`;
  }
  return back;
}

// Alttaki bilgi şeridi (Gmail "snackbar"): isteğe bağlı GERİ AL
let snackEl = null;
function snack(text, undo, ms = 5000) {
  snackEl?.remove();
  const el = h('div', { class: 'gm-snack', role: 'status' }, h('span', { class: 'grow' }, text),
    undo ? h('button', { type: 'button', onclick: () => { el.remove(); undo(); } }, t('GERİ AL')) : null);
  snackEl = el; document.body.append(el);
  setTimeout(() => { if (el.isConnected) { el.classList.add('out'); setTimeout(() => el.remove(), 250); } }, ms);
}

export async function renderMail(view, params = []) {
  let d;
  try { d = await api.get('/api/mail/boxes'); } catch (e) { clear(view, h('div', { class: 'card empty' }, e.message)); return; }
  const boxes = d.boxes;
  if (!boxes.length) {
    const head = h('div', { class: 'page-head' }, h('a', { class: 'back', href: '#/', 'aria-label': t('Geri') }, '←'),
      h('div', { class: 'page-head-t' }, h('h1', null, t('Mail')), h('div', { class: 'sub' }, t('Mail hesabınızı bağlayın'))), h('div', { class: 'spacer' }));
    clear(view, head, h('div', { class: 'gm-empty-acc' }, h('div', { class: 'gm-empty-art' }, ic('allMail')),
      h('h2', null, t('Mail hesabınızı bağlayın')),
      h('p', null, t('Gmail, Outlook / Microsoft 365, Yandex, iCloud, Yahoo, şirket (IMAP / Exchange) ya da POP3 hesaplarınızı ekleyin. Hesaplarınızı ve postalarınızı yönetici dahil kimse göremez.')),
      h('a', { class: 'gm-btn-fill', href: '#/settings/mailboxes' }, ic('add'), t('Mail hesabı ekle'))));
    return;
  }
  view.classList.add('gm-view');
  const boxOf = id => boxes.find(b => b.id === Number(id));
  // ---- durum
  const deep = params[1] === 'm' && /^\d+$/.test(params[2] || '')
    ? { box: Number(params[0]), uid: Number(params[2]), folder: params[3] ? decodeURIComponent(params[3]) : 'inbox' } : null;
  let cur = { box: deep ? deep.box : (params[0] && params[0] !== 'all' && boxOf(params[0]) ? Number(params[0]) : (boxes.length > 1 ? 'all' : boxes[0].id)), folder: 'inbox' };
  if (cur.box !== 'all' && !boxOf(cur.box)) cur.box = boxes[0].id;
  let q = '', items = [], total = 0, loading = false, loadSeq = 0, openKey = null, msgCur = null;
  const folderCache = {};
  const collapsed = new Set();
  // Liste sıralaması ve filtresi: bütün klasöre uygulanır (klasör kaydedildiyse kayıtlı mailler arasında, hızlı)
  const SORTS = [['date', 'Tarih (yeniden eskiye)'], ['date_asc', 'Tarih (eskiden yeniye)'], ['from', 'Gönderene göre (A→Z)'],
    ['subject', 'Konuya göre (A→Z)'], ['size', 'Boyuta göre (büyükten)']];
  const FILTERS = [['', 'Tüm postalar', 'allMail'], ['unread', 'Yalnız okunmamışlar', 'unread'], ['starred', 'Yalnız yıldızlılar', 'star'], ['attach', 'Yalnız ekli olanlar', 'attach']];
  // Görünüm: Klasörler (Gmail gibi) · Kişiler (Rehber solda) · Cariler (firmalar solda); seçilen kişi / carinin mailleri adrese göre gruplu
  const VIEWS = [['folders', 'Klasörler', 'inbox'], ['people', 'Kişiler', 'person'], ['cari', 'Cariler', 'business']];
  let vmode = params[1] === 'm' ? 'folders' : (localStorage.getItem('gm.mode') || 'folders');
  if (!VIEWS.some(v => v[0] === vmode)) vmode = 'folders';
  const pv = { data: null, kind: null, sel: null, q: '', seq: 0 };
  let lv;
  try { lv = { sort: 'date', filter: '', ...JSON.parse(localStorage.getItem('gm.view') || '{}') }; } catch { lv = { sort: 'date', filter: '' }; }
  const setLv = patch => { lv = { ...lv, ...patch }; try { localStorage.setItem('gm.view', JSON.stringify(lv)); } catch { /* */ } drawListHead(); loadList(); };
  const lvQuery = () => `&sort=${lv.sort}&filter=${lv.filter}`;
  // Klasör ağacı (ör. Gmail etiketleri "Bankalar/Akbank"): ayırıcıya göre hiyerarşi; kapalı dallar hatırlanır
  let treeClosed;
  try { treeClosed = new Set(JSON.parse(localStorage.getItem('gm.tree') || '[]')); } catch { treeClosed = new Set(); }
  const saveTree = () => { try { localStorage.setItem('gm.tree', JSON.stringify([...treeClosed])); } catch { /* */ } };
  const folderTree = fs => {   // özel klasörler → { kids: Map(ad → { name, path, f (gerçek klasör | null: ara düğüm), kids }) }
    const top = { kids: new Map() };
    for (const f of fs) {
      let n = top, path = '';
      for (const part of (f.sep ? f.title.split(f.sep) : [f.title])) {
        path = path ? `${path}${f.sep}${part}` : part;
        if (!n.kids.has(part)) n.kids.set(part, { name: part, path, f: null, kids: new Map() });
        n = n.kids.get(part);
      }
      n.f = f;
    }
    return top;
  };
  // Klasörün bütün alt klasörleri (alfabetik = derinlik öncelikli): üst klasör açılınca kendi postalarının altında gösterilir
  const subFolders = (bid, key) => {
    const fs = (folderCache[bid] || []).filter(f => f.custom);
    const me = fs.find(f => f.key === key);
    return me?.sep ? fs.filter(f => f.title.startsWith(me.title + me.sep)).sort((a, b) => a.title.localeCompare(b.title, 'tr')) : [];
  };
  const subsHere = () => (cur.box !== 'all' && !q ? subFolders(cur.box, cur.folder) : []);
  const sel = new Map();   // anahtar → öğe
  const keyOf = m => `${m.box_id || cur.box}:${m.uid}`;
  const bidOf = m => m.box_id || cur.box;
  // "Tüm Hesaplar" (box='all') için birleştirilebilen temel klasörler + kanonik başlıklar
  const UNIFIED_STD = [['inbox', 'Gelen Kutusu'], ['starred', 'Yıldızlı'], ['sent', 'Gönderilmiş'],
    ['drafts', 'Taslaklar'], ['archive', 'Arşiv'], ['spam', 'Gereksiz'], ['trash', 'Çöp Kutusu']];
  const STD_TITLE = Object.fromEntries(UNIFIED_STD.concat([['important', 'Önemli'], ['all', 'Tüm Postalar']]));
  const folderOfList = () => (cur.box === 'all' ? (cur.folder || 'inbox') : cur.folder);
  const isPop = bid => boxOf(bid)?.provider === 'pop3';
  const folderTitle = () => (cur.box === 'all'
    ? (folderOfList() === 'inbox' ? t('Tüm gelen kutuları') : `${t('Tüm Hesaplar')} · ${t(STD_TITLE[folderOfList()] || 'Gelen Kutusu')}`)
    : ((folderCache[cur.box] || []).find(f => f.key === cur.folder)?.title || t('Gelen Kutusu')));

  // ---- iskelet
  const nav = h('aside', { class: 'gm-nav' });
  const scrim = h('div', { class: 'gm-scrim', onclick: () => closeDrawer() });
  const search = h('input', { class: 'gm-search-in', type: 'search', placeholder: t('Postalarda arayın'), enterkeyhint: 'search', autocomplete: 'off' });
  const clearQ = ibtn('close', 'Aramayı temizle', () => { search.value = ''; setQ(''); }, 'gm-search-x');
  const acctBtn = h('button', { class: 'gm-acct', type: 'button', title: t('Hesap değiştir'), onclick: e => accountMenu(e.currentTarget) });
  const topbar = h('div', { class: 'gm-top' },
    ibtn('menu', 'Menü', () => openDrawer(), 'gm-menu-btn'),
    h('form', { class: 'gm-search', onsubmit: e => { e.preventDefault(); search.blur(); setQ(search.value.trim()); } }, ic('search'), search, clearQ),
    ibtn('sort', 'Sırala ve filtrele', e => viewMenu(e.currentTarget), 'gm-sort-btn'),
    acctBtn);
  function viewMenu(anchor) {
    popMenu(anchor, [{ head: t('Sırala') },
      ...SORTS.map(([k, l]) => ({ icon: lv.sort === k ? 'check' : null, label: t(l), on: lv.sort === k, run: () => setLv({ sort: k }) })),
      '-', { head: t('Göster') },
      ...FILTERS.map(([k, l, i]) => ({ icon: i, label: t(l), on: lv.filter === k, run: () => setLv({ filter: k }) }))]);
  }
  const selbar = h('div', { class: 'gm-selbar', hidden: true });
  const listHead = h('div', { class: 'gm-lhead' });
  const syncBar = h('div', { class: 'gm-sync', hidden: true });   // klasör kaydedilirken ilerleme
  const label = h('div', { class: 'gm-label' });
  const ptr = h('div', { class: 'gm-ptr' }, ic('refresh'));
  const list = h('div', { class: 'gm-list', role: 'list' });
  const more = h('div', { class: 'gm-more' });
  const subWrap = h('div', { class: 'gm-subs' });   // üst klasörde alt klasörlerin postaları (kalın şeritlerle)
  const bars = h('div', { class: 'gm-bars' }, topbar, selbar, syncBar, listHead);
  const card = h('div', { class: 'gm-card' }, label, list, more, subWrap);
  const scroll = h('div', { class: 'gm-scroll' }, bars, ptr, card);
  const fab = h('button', { class: 'gm-fab', type: 'button', onclick: () => compose() }, ic('edit'), h('span', null, t('Oluştur')));
  const listPane = h('section', { class: 'gm-listpane' }, scroll, fab);
  const reader = h('section', { class: 'gm-read', 'aria-live': 'polite' });
  const pplQ = h('input', { class: 'gm-ppl-q', type: 'search', placeholder: t('Ad, e-posta ya da firma…'), autocomplete: 'off' });
  pplQ.addEventListener('input', () => { pv.q = pplQ.value; drawPeople(); });
  const pplList = h('div', { class: 'gm-ppl-list' });
  const pplHead = h('div', { class: 'gm-ppl-h' });
  const ppl = h('section', { class: 'gm-ppl' }, pplHead, h('div', { class: 'gm-ppl-s' }, ic('search'), pplQ), pplList);
  const pickHead = h('div', { class: 'gm-pickhead' });   // Kişiler / Cariler: seçilen kişi ya da cari (mobilde geri düğmesiyle)
  bars.insertBefore(pickHead, listHead);
  const root = h('div', { class: 'gm' }, nav, scrim, ppl, listPane, reader);
  clear(view, root);
  const onKey = e => keys(e);
  // Geri: varılan geçmiş kaydına göre karar (yazma penceresi kapanıp okuma kaydına dönüldüyse okuma açık kalır)
  const onPop = e => {
    const s = e.state?.gm;
    if (root.classList.contains('drawer') && s !== 'drawer') closeDrawer(true);
    if (root.classList.contains('reading') && s !== 'read' && s !== 'compose') closeReader(true);
    if (root.classList.contains('picked') && !['picked', 'read', 'compose'].includes(s) && !wide2()) unpick(true);
  };
  document.addEventListener('keydown', onKey);
  window.addEventListener('popstate', onPop);
  const cleanup = () => { document.removeEventListener('keydown', onKey); window.removeEventListener('popstate', onPop); flush(); composeWin?.close(); document.querySelectorAll('.gm-pop,.gm-snack').forEach(x => x.remove()); };
  window.addEventListener('hashchange', cleanup, { once: true });

  // ---- görünümler: Klasörler / Kişiler / Cariler
  const wide2 = () => matchMedia('(min-width: 761px)').matches;
  const modeSwitch = () => h('div', { class: 'gm-modes', role: 'tablist' }, VIEWS.map(([k, l, i]) =>
    h('button', { type: 'button', role: 'tab', class: `gm-mode ${vmode === k ? 'on' : ''}`, 'aria-selected': String(vmode === k),
      onclick: () => { closeDrawer(); setMode(k); } }, ic(i), h('span', null, t(l)))));
  function setMode(k) {
    flush();
    vmode = k;
    try { localStorage.setItem('gm.mode', k); } catch { /* */ }
    root.classList.toggle('mode-p', k !== 'folders');
    root.dataset.mode = k;
    closeReader(); sel.clear(); syncSel();
    if (k === 'folders') { root.classList.remove('picked'); pv.sel = null; drawNav(); loadList(); syncFolder(); return; }
    syncSeq++; syncBar.hidden = true;
    if (pv.kind !== k) { pv.data = null; pv.sel = null; pv.kind = k; root.classList.remove('picked'); }
    drawNav(); loadPeople();
  }
  async function loadPeople() {
    const k = vmode, seq = ++pv.seq;
    clear(pplHead, modeSwitch());
    if (!pv.data) clear(pplList, h('div', { class: 'gm-loading' }, h('div', { class: 'gm-spin' })));
    try { pv.data = await api.get(k === 'cari' ? '/api/mail/view/cari' : '/api/mail/view/people'); }
    catch (e) { if (seq === pv.seq) clear(pplList, h('div', { class: 'gm-empty' }, ic('spam'), h('b', null, e.message))); return; }
    if (seq !== pv.seq || vmode !== k) return;
    drawPeople();
    if (pv.sel) loadList(); else drawList();
  }
  const fold = x => String(x || '').toLocaleLowerCase('tr').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/ı/g, 'i');
  const lastWhen = iso => (iso ? when(iso) : '');
  const avSpan = a => { const el = h('span', { class: 'gm-av gm-av-s' }, h('span', { class: 'gm-av-l' }, letter(a))); el.style.setProperty('--av', colorOf(a?.email || a?.name)); return el; };
  function drawPeople() {
    if (!pv.data) return;
    const qq = fold(pv.q).split(/\s+/).filter(Boolean);
    const hit = (...xs) => { const hay = fold(xs.flat().join(' ')); return qq.every(w => hay.includes(w)); };
    const isOn = e => pv.sel && pv.sel.key === e.key;
    const entry = (e, main, sub, n, last, avatarOf, cls = '') => {
      const r = h('button', { type: 'button', class: `gm-pr ${isOn(e) ? 'on' : ''} ${cls}`, onclick: () => pick(e) },
        avSpan(avatarOf), h('span', { class: 'gm-pr-t' }, h('b', null, main), sub ? h('small', null, sub) : null),
        h('span', { class: 'gm-pr-r' }, last ? h('small', null, lastWhen(last)) : null, n ? h('span', { class: 'gm-pr-n' }, n) : null));
      return r;
    };
    const head = (txt, n) => h('div', { class: 'gm-pr-h' }, h('span', { class: 'grow' }, txt), h('small', null, n));
    if (vmode === 'people') {
      const known = pv.data.known.filter(p => hit(p.name, p.companies, p.emails.map(x => x.email)))
        .map(p => ({ ...p, key: `${p.kind}:${p.id}`, title: p.name, emails: p.emails.map(x => x.email), labels: {} }));
      const unknown = pv.data.unknown.filter(u => hit(u.name, u.email))
        .map(u => ({ ...u, key: `addr:${u.email}`, title: u.name || u.email, emails: [u.email], labels: {} }));
      clear(pplList,
        head(t('Rehberde kayıtlı'), known.length),
        known.length ? known.map(p => entry(p, p.name, p.companies.join(' · ') || p.emails.join(', '), p.count, p.last, { name: p.name, email: p.emails[0] }))
          : h('div', { class: 'gm-pr-empty' }, t('Eşleşen kişi yok')),
        head(t('Bilinmeyen adresler'), pv.data.unknown_total > unknown.length && !qq.length ? `${unknown.length} / ${pv.data.unknown_total}` : unknown.length),
        unknown.slice(0, 400).map(u => entry(u, u.name || u.email, u.name ? u.email : null, u.count, u.last, { name: u.name, email: u.email }, 'unk')));
    } else {
      const cos = pv.data.filter(c => hit(c.name, c.people.map(x => [x.name, x.email])))
        .map(c => ({ ...c, key: `cari:${c.id}`, title: c.name, emails: c.people.map(x => x.email),
          labels: Object.fromEntries(c.people.map(x => [x.email, x.name])) }));
      const withMail = cos.filter(c => c.count), without = cos.filter(c => !c.count);
      clear(pplList,
        head(t('Yazışılan cariler'), withMail.length),
        withMail.length ? withMail.map(c => entry(c, c.name, t('{n} kişi', { n: c.people.length }) + (c.supplier ? ` · ${t('tedarikçi')}` : ''), c.count, c.last, { name: c.name, email: c.name }))
          : h('div', { class: 'gm-pr-empty' }, t('Kayıtlı maillerde carilerle yazışma yok')),
        without.length ? [head(t('Yazışma olmayan cariler'), without.length),
          without.map(c => entry(c, c.name, t('{n} kişi', { n: c.people.length }), 0, null, { name: c.name, email: c.name }, 'unk'))] : null);
    }
    if (!pv.data || (vmode === 'people' ? !pv.data.known.length && !pv.data.unknown.length : !pv.data.length))
      pplList.append(h('div', { class: 'gm-pr-empty' }, t('Mailler sisteme kaydedildikçe burada görünür. Klasörler görünümünde Gelen Kutusu’nu bir kez açın.')));
  }
  function pick(e) {
    pv.sel = e;
    closeReader();
    if (!root.classList.contains('picked')) { root.classList.add('picked'); if (!wide2()) history.pushState({ gm: 'picked' }, ''); }
    pplList.querySelectorAll('.gm-pr').forEach(r => r.classList.remove('on'));
    drawPeople();
    scroll.scrollTop = 0;
    loadList();
  }
  function unpick(fromPop) {
    if (!root.classList.contains('picked')) return;
    root.classList.remove('picked'); closeReader(true);
    if (!fromPop && history.state?.gm === 'picked') history.back();
  }
  function drawPickHead() {
    const e = pv.sel;
    clear(pickHead, ibtn('back', 'Geri', () => unpick(), 'gm-pick-back'),
      e ? [avSpan({ name: e.title, email: e.emails[0] }), h('div', { class: 'gm-pick-ti' }, h('b', null, e.title),
        h('small', null, vmode === 'cari' ? t('{n} çalışanın adresleri', { n: e.emails.length }) : e.emails.join(' · ')))]
        : h('div', { class: 'gm-pick-ti' }, h('b', null, t(vmode === 'cari' ? 'Soldan bir cari seçin' : 'Soldan bir kişi seçin'))),
      h('span', { class: 'grow' }), e ? h('span', { class: 'gm-count' }, t('{n} ileti', { n: items.length })) : null,
      e ? ibtn('edit', 'Yeni ileti', () => compose({ to: e.kind === 'cari' ? [] : [{ name: e.title, email: e.emails[0] }] })) : null);
  }
  function drawGrouped() {
    drawPickHead();
    clear(subWrap); clear(more);
    if (!pv.sel) { clear(list, h('div', { class: 'gm-empty' }, ic(vmode === 'cari' ? 'business' : 'person'), h('b', null, t(vmode === 'cari' ? 'Bir cari seçin' : 'Bir kişi seçin')),
      h('small', null, t('Mailleri adreslerine göre gruplu görünür')))); return; }
    if (!items.length) { clear(list, h('div', { class: 'gm-empty' }, ic('allMail'), h('b', null, t('Kayıtlı maillerde yazışma yok')))); return; }
    const groups = new Map(pv.sel.emails.map(e => [e, []]));
    items.forEach(m => (groups.get(m.match) || groups.set(m.match, []).get(m.match)).push(m));
    clear(list, [...groups].filter(([, ms]) => ms.length).map(([e, ms]) => h('section', { class: 'gm-grp' },
      h('div', { class: 'gm-substrip' }, ic(pv.sel.kind === 'cari' ? 'person' : 'allMail'),
        h('b', { class: 'grow' }, pv.sel.labels[e] ? `${pv.sel.labels[e]} · ${e}` : e), h('span', { class: 'gm-sub-n' }, t('{n} ileti', { n: ms.length }))),
      ms.map(row))));
  }
  async function loadPicked() {
    const e = pv.sel, seq = ++loadSeq;
    if (!e) { items = []; total = 0; drawList(); return; }
    clear(list, h('div', { class: 'gm-skel' }, Array.from({ length: 6 }, () => h('div', { class: 'gm-skel-row' }, h('i'), h('span', null, h('b'), h('em'), h('em'))))));
    drawPickHead();
    try {
      const r = await api.get(`/api/mail/view/mails?emails=${encodeURIComponent(e.emails.join(','))}`);
      if (seq !== loadSeq || pv.sel !== e) return;
      items = r.items; total = r.total;
    } catch (err) { if (seq !== loadSeq) return; items = []; total = 0; toastError(err); }
    drawList(); syncSel();
  }

  // ---- çekmece / klasörler
  const openDrawer = () => { root.classList.add('drawer'); history.pushState({ gm: 'drawer' }, ''); };
  const closeDrawer = fromPop => { if (!root.classList.contains('drawer')) return; root.classList.remove('drawer'); if (!fromPop && history.state?.gm === 'drawer') history.back(); };
  // Çekmeceyi kapat, geri gitme bitince devam et (yoksa yeni pencerenin geçmiş kaydı geri gitmeyle birlikte kapanırdı)
  const closeDrawerThen = fn => {
    if (!root.classList.contains('drawer') || history.state?.gm !== 'drawer') { closeDrawer(); fn(); return; }
    window.addEventListener('popstate', () => setTimeout(fn), { once: true });
    closeDrawer();
  };
  async function loadFolders(id) {
    try { folderCache[id] = await api.get(`/api/mail/${id}/folders`); boxOf(id).last_error = null; } catch (e) { boxOf(id).last_error = e.message; }
    drawNav(); drawAcct(); drawLabel();
  }
  const inboxUnseen = b => (folderCache[b.id] || []).find(f => f.key === 'inbox')?.unseen || 0;
  function drawNav() {
    const item = (on, icon, title, n, onclick, cls = '') => h('button', { type: 'button', class: `gm-nf ${on ? 'on' : ''} ${cls}`, onclick },
      ic(icon), h('span', { class: 'grow' }, title), n ? h('b', { class: 'gm-nf-n' }, n) : null);
    const go = (box, folder) => () => { closeDrawer(); select(box, folder); };
    // Klasörler başlığı: alt klasörü olan bütün dalları tek dokunuşla kapat / aç
    const treeHead = (b, custom) => {
      const parents = [];
      const walk = kids => kids.forEach(n => { if (n.kids.size) { parents.push(`${b.id}|${n.path}`); walk(n.kids); } });
      walk(folderTree(custom).kids);
      const anyOpen = parents.some(k => !treeClosed.has(k));
      return h('div', { class: 'gm-nav-sub gm-tree-h' }, h('span', { class: 'grow' }, t('Klasörler')),
        parents.length ? h('button', { type: 'button', class: 'gm-tree-all', title: t(anyOpen ? 'Tümünü kapat' : 'Tümünü aç'),
          onclick: e => { e.stopPropagation(); parents.forEach(k => (anyOpen ? treeClosed.add(k) : treeClosed.delete(k))); saveTree(); drawNav(); } },
        ic(anyOpen ? 'unfoldLess' : 'unfoldMore'), h('span', null, t(anyOpen ? 'Tümünü kapat' : 'Tümünü aç'))) : null);
    };
    const treeItems = (b, kids, depth) => [...kids.values()].sort((x, y) => x.name.localeCompare(y.name, 'tr')).map(n => {
      const ck = `${b.id}|${n.path}`, has = n.kids.size > 0, closed = treeClosed.has(ck);
      const toggle = e => { e?.stopPropagation(); closed ? treeClosed.delete(ck) : treeClosed.add(ck); saveTree(); drawNav(); };
      const on = cur.box === b.id && n.f && cur.folder === n.f.key;
      const row = h('button', { type: 'button', class: `gm-nf gm-tree ${on ? 'on' : ''} ${n.f ? '' : 'virtual'}`, title: n.path,
        onclick: n.f ? go(b.id, n.f.key) : toggle },
        has ? h('span', { class: `gm-caret ${closed ? '' : 'open'}`, role: 'button', title: t(closed ? 'Aç' : 'Kapat'), onclick: toggle }, '▸')
          : h('span', { class: 'gm-caret' }),
        ic('folder'), h('span', { class: 'grow' }, n.name), n.f?.unseen ? h('b', { class: 'gm-nf-n' }, n.f.unseen) : null);
      row.style.setProperty('--d', depth);
      return [row, has && !closed ? treeItems(b, n.kids, depth + 1) : null];
    });
    const totalUnseen = boxes.reduce((a, b) => a + inboxUnseen(b), 0);
    // "Tüm Hesaplar": birleşik temel klasörler (yalnız en az bir hesapta bulunanlar; inbox her zaman)
    const unifiedUnseen = key => (key === 'inbox' ? totalUnseen
      : boxes.reduce((a, b) => a + (((folderCache[b.id] || []).find(f => f.key === key) || {}).unseen || 0), 0));
    const hasKey = key => key === 'inbox' || boxes.some(b => (folderCache[b.id] || []).some(f => f.key === key));
    const allGroup = boxes.length > 1 ? h('div', { class: 'gm-nav-acc' },
      h('div', { class: 'gm-nav-sub gm-tree-h' }, h('span', { class: 'grow' }, t('Tüm Hesaplar'))),
      UNIFIED_STD.filter(([k]) => hasKey(k)).map(([k, ttl]) =>
        item(cur.box === 'all' && folderOfList() === k, FOLDER_ICON[k] || 'folder', t(ttl),
          k === 'drafts' ? null : (unifiedUnseen(k) || null), go('all', k), k === 'inbox' ? 'strong' : ''))) : null;
    clear(nav,
      h('div', { class: 'gm-nav-brand' }, h('span', { class: 'gm-nav-logo' }, ic('allMail')), h('b', null, t('Mail'))),
      h('button', { class: 'gm-compose-btn', type: 'button', onclick: () => closeDrawerThen(() => compose()) }, ic('edit'), t('Oluştur')),
      modeSwitch(),
      h('div', { class: 'gm-nav-scroll' },
        allGroup,
        boxes.map(b => {
          const fs = folderCache[b.id] || [];
          const open = !collapsed.has(b.id);
          const std = fs.filter(f => !f.custom), custom = fs.filter(f => f.custom);
          const dot = h('span', { class: 'gm-nav-dot' }); dot.style.background = b.color || colorOf(b.email);
          return h('div', { class: `gm-nav-acc ${open ? '' : 'closed'}` },
            h('button', { type: 'button', class: 'gm-nav-acc-h', title: b.last_error || b.email, onclick: () => { open ? collapsed.add(b.id) : collapsed.delete(b.id); drawNav(); } },
              dot, h('span', { class: 'grow' }, b.email), b.last_error ? h('span', { class: 'gm-nav-err' }, '!') : null, ic('expand')),
            open ? [fs.length ? std.map(f => item(cur.box === b.id && cur.folder === f.key, FOLDER_ICON[f.key] || 'folder', f.title, f.key === 'drafts' ? f.unseen && null : f.unseen, go(b.id, f.key)))
              : h('div', { class: 'gm-nav-note' }, b.last_error || t('Yükleniyor…')),
            custom.length ? [treeHead(b, custom), treeItems(b, folderTree(custom).kids, 0)] : null] : null);
        })),
      h('div', { class: 'gm-nav-foot' },
        h('a', { class: 'gm-nf', href: '#/settings/mailboxes' }, ic('settings'), h('span', { class: 'grow' }, t('Hesapları yönet'))),
        h('a', { class: 'gm-nf gm-only-m', href: '#/' }, ic('home'), h('span', { class: 'grow' }, t('Ana sayfa')))));
  }
  function drawAcct() {
    const b = cur.box === 'all' ? null : boxOf(cur.box);
    clear(acctBtn, b ? h('span', { class: 'gm-acct-av' }, letter({ email: b.name || b.email })) : h('span', { class: 'gm-acct-av all' }, ic('inboxes')));
    if (b) acctBtn.firstChild.style.background = b.color || colorOf(b.email);
  }
  function accountMenu(anchor) {
    popMenu(anchor, [{ head: t('Hesaplar') },
      boxes.length > 1 ? { icon: 'inboxes', label: t('Tüm gelen kutuları'), on: cur.box === 'all', badge: boxes.reduce((a, b) => a + inboxUnseen(b), 0) || null, run: () => select('all', 'inbox') } : null,
      ...boxes.map(b => ({ icon: 'allMail', label: b.email, on: cur.box === b.id, badge: inboxUnseen(b) || null, run: () => select(b.id, 'inbox') })),
      '-', { icon: 'add', label: t('Başka hesap ekle'), run: () => { location.hash = '#/settings/mailboxes'; } }]);
  }
  function select(box, folder) {
    if (vmode !== 'folders') { vmode = 'folders'; try { localStorage.setItem('gm.mode', 'folders'); } catch { /* */ } root.classList.remove('mode-p', 'picked'); root.dataset.mode = 'folders'; }
    flush();
    cur = { box, folder }; q = ''; search.value = ''; sel.clear();
    collapsed.delete(box);
    if (box !== 'all' && !folderCache[box]) loadFolders(box);
    drawNav(); drawAcct(); closeReader(); loadList(); syncFolder();
  }
  let syncSeq = 0;
  async function syncFolder() {
    const seq = ++syncSeq, bid = cur.box, folder = cur.folder;
    syncBar.hidden = true;
    if (bid === 'all' || isPop(bid) || vmode !== 'folders') return;
    let st, was = false;
    try { st = await api.post(`/api/mail/${bid}/cache-sync?folder=${encodeURIComponent(folder)}`, {}); } catch { return; }
    while (seq === syncSeq && st && st.running && root.isConnected) {
      was = true;
      const pct = st.total ? Math.floor((st.done / st.total) * 100) : 0;
      syncBar.hidden = false;
      clear(syncBar, h('div', { class: 'gm-sync-t' }, h('span', null, t('Mailler sisteme kaydediliyor')),
        h('b', null, st.total ? t('{d} / {n} · %{p}', { d: st.done.toLocaleString('tr-TR'), n: st.total.toLocaleString('tr-TR'), p: pct }) : t('hazırlanıyor…'))),
        h('div', { class: 'gm-sync-bar' }, h('i', { style: { width: `${pct}%` } })));
      await new Promise(r => setTimeout(r, 1200));
      if (seq !== syncSeq) return;
      try { st = await api.get(`/api/mail/${bid}/cache-sync?folder=${encodeURIComponent(folder)}`); } catch { break; }
    }
    if (seq !== syncSeq) return;
    syncBar.hidden = true;
    if (st?.error) toast(t('Klasör kaydedilemedi: {e}', { e: st.error }), 'err');
    else if (was && (lv.sort !== 'date' || lv.filter)) loadList();   // artık kayıtlı mailler arasında sıralanır
  }
  function drawLabel() {
    const b = cur.box === 'all' ? null : boxOf(cur.box);
    clear(label, h('span', null, q ? t('Arama sonuçları') : folderTitle()), b && boxes.length > 1 ? h('small', null, b.email) : null);
  }
  function setQ(v) { flush(); q = v; root.classList.toggle('searching', !!q); loadList(); }

  // ---- liste
  function drawListHead() {
    const allOn = items.length && items.every(m => sel.has(keyOf(m)));
    const cb = h('input', { type: 'checkbox', class: 'gm-cb', checked: !!allOn, title: t('Tümünü seç'),
      onchange: e => { items.forEach(m => (e.target.checked ? sel.set(keyOf(m), m) : sel.delete(keyOf(m)))); syncSel(); } });
    const chip = (label, reset) => h('button', { type: 'button', class: 'gm-chip', title: t('Kaldır'), onclick: reset }, h('span', null, label), ic('close'));
    clear(listHead, cb, ibtn('refresh', 'Yenile', () => { loadList(); refreshFolders(); }),
      lv.filter ? chip(t(FILTERS.find(f => f[0] === lv.filter)?.[1] || ''), () => setLv({ filter: '' })) : null,
      lv.sort !== 'date' ? chip(t(SORTS.find(x => x[0] === lv.sort)?.[1] || ''), () => setLv({ sort: 'date' })) : null,
      h('span', { class: 'grow' }),
      total ? h('span', { class: 'gm-count' }, `${Math.min(items.length, total)} / ${total}`) : null);
  }
  function row(m) {
    const k = keyOf(m), bid = bidOf(m);
    const sentLike = ['sent', 'drafts'].includes(folderOfList());
    const who = sentLike ? t('Kime: {n}', { n: nameOf(m.to) || '—' }) : nameOf(m.from);
    const star = isPop(bid) ? null : h('button', { type: 'button', class: `gm-star ${m.starred ? 'on' : ''}`, title: t(m.starred ? 'Yıldızı kaldır' : 'Yıldızla'),
      onclick: e => { e.stopPropagation(); toggleStar(m, e.currentTarget); } }, ic(m.starred ? 'star' : 'starO'));
    const starSlot = star || h('span', { class: 'gm-star gm-star-ph', 'aria-hidden': 'true' });   // POP3: yıldız yok, sütun hizası korunur
    const cb = h('input', { type: 'checkbox', class: 'gm-cb', checked: sel.has(k), onclick: e => e.stopPropagation(), onchange: () => toggleSel(m) });
    const hover = h('div', { class: 'gm-hover' },
      cur.folder === 'inbox' && !isPop(bid) ? ibtn('archive', 'Arşivle', e => { e.stopPropagation(); act([m], 'archive'); }) : null,
      ibtn('delete', isPop(bid) ? 'Kalıcı sil' : 'Sil', e => { e.stopPropagation(); act([m], 'trash'); }),
      ibtn(m.seen ? 'unread' : 'read', m.seen ? 'Okunmadı işaretle' : 'Okundu işaretle', e => { e.stopPropagation(); act([m], m.seen ? 'unread' : 'read'); }));
    const inner = h('div', { class: 'gm-row-in' },
      cb, avatarEl(m.from, e => { e.stopPropagation(); toggleSel(m); }), starSlot,
      h('div', { class: 'gm-row-main' },
        h('div', { class: 'gm-l1' }, h('span', { class: 'gm-who' }, h('span', { class: 'gm-who-n' }, who || t('(gönderen yok)')),
          m.company ? h('span', { class: 'gm-co', title: t('Firma') }, m.company) : null,
          cur.box === 'all' && boxes.length > 1 ? h('span', { class: 'gm-boxdot', title: m.box_email }) : null),
          h('span', { class: 'gm-time', title: full(m.date) }, when(m.date))),
        h('div', { class: 'gm-l2' }, h('span', { class: 'gm-subj' }, m.subject),
          h('span', { class: 'gm-snip' }, m.snippet ? ` — ${m.snippet}` : ''),
          h('span', { class: 'gm-flags' }, m.invite ? ic('event', t('Takvim daveti')) : null, m.attach ? ic('attach', t('Ekli')) : null)),
        h('div', { class: 'gm-l3' }, h('span', { class: 'gm-snip' }, m.snippet || ''), star ? star.cloneNode(true) : null)),
      hover);
    const l3star = inner.querySelector('.gm-l3 .gm-star');
    if (l3star) l3star.addEventListener('click', e => { e.stopPropagation(); toggleStar(m, l3star); });
    if (cur.box === 'all') inner.querySelector('.gm-boxdot')?.style.setProperty('background', boxOf(bid)?.color || colorOf(m.box_email));
    const r = h('div', { class: `gm-row ${m.seen ? '' : 'unread'} ${sel.has(k) ? 'sel' : ''} ${openKey === k ? 'open' : ''}`, role: 'listitem', 'data-k': k, tabindex: 0,
      onclick: () => (sel.size && mobile() ? toggleSel(m) : openMsg(m)), onkeydown: e => { if (e.key === 'Enter') openMsg(m); } },
    h('div', { class: `gm-swipe l ${folderOfList() === 'inbox' ? '' : 'del'}` }, ic(folderOfList() === 'inbox' ? 'archive' : 'delete')), h('div', { class: 'gm-swipe r' }, ic('delete')), inner);
    // Uzun basma / kaydırma sonrası hemen gelen tıklama yutulur; süre dolunca sonraki dokunuş normal çalışır
    r.addEventListener('click', e => { if (Date.now() < (r._noClick || 0)) { e.stopPropagation(); e.preventDefault(); } }, { capture: true });
    swipeable(r, inner, m);
    let lp = null;   // uzun basınca seç (mobil)
    r.addEventListener('touchstart', () => { r._noClick = 0; lp = setTimeout(() => { lp = 'done'; toggleSel(m); navigator.vibrate?.(15); }, 480); }, { passive: true });
    const cancelLp = () => { if (lp && lp !== 'done') clearTimeout(lp); };
    r.addEventListener('touchmove', cancelLp, { passive: true });
    r.addEventListener('touchend', e => { if (lp === 'done') { e.preventDefault(); r._noClick = Date.now() + 400; } cancelLp(); lp = null; });
    return r;
  }
  function drawList() {
    if (vmode !== 'folders') { drawGrouped(); return; }
    drawLabel(); drawListHead();
    if (!items.length) {
      clear(list, h('div', { class: 'gm-empty' }, ic(q ? 'search' : (FOLDER_ICON[folderOfList()] || 'inbox')),
        h('b', null, q ? t('Aramanızla eşleşen ileti yok') : t('Burada ileti yok')),
        q ? h('small', null, t('Farklı bir kelimeyle deneyin')) : null));
    } else clear(list, items.map(row));
    const subs = subsHere();
    if (subs.length) {   // üst klasör: kendi postalarının altında "daha fazla", sonra kalın şeritle alt klasörlerin postaları
      clear(more, items.length < total ? h('button', { class: 'gm-more-btn', type: 'button', onclick: () => loadList(true) },
        t('Bu klasörde {n} ileti daha — göster', { n: total - items.length })) : null);
      drawSubSections(subs);
    } else {
      clear(subWrap);
      clear(more, hasMore() ? h('div', { class: 'gm-spin' }) : null);
    }
  }
  const hasMore = () => vmode === 'folders' && cur.box !== 'all' && items.length < total && !subsHere().length;
  // Alt klasör bölümleri: her alt klasör için kalın şerit + en yeni 20 ileti + "klasörü aç". İletiye tıklayınca kendi
  // klasöründe açılır (okuma ekranındaki işlemler o klasöre uygulanır).
  const subCache = {};   // `${hesap}|${klasör}` → { items, total, at }
  let subSeq = 0;
  async function drawSubSections(subs) {
    const seq = ++subSeq, bid = cur.box;
    const sec = f => {
      const c = subCache[`${bid}|${f.key}`];
      const short = f.title.slice(f.title.lastIndexOf(f.sep) + 1);
      return h('section', { class: 'gm-subsec' },
        h('div', { class: 'gm-substrip', title: f.title }, ic('folder'), h('b', { class: 'grow' }, f.title),
          c ? h('span', { class: 'gm-sub-n' }, t('{n} ileti', { n: c.total })) : null,
          h('button', { type: 'button', class: 'gm-more-btn sm', onclick: () => select(bid, f.key) }, t('{f} klasörünü aç', { f: short }))),
        c ? (c.items.length ? c.items.map(m => subRow(m, bid, f.key)) : h('div', { class: 'gm-subempty' }, t('Bu klasörde ileti yok')))
          : h('div', { class: 'gm-spin' }));
    };
    const paint = () => { if (seq === subSeq) clear(subWrap, subs.map(sec)); };
    paint();
    for (const f of subs) {
      const ck = `${bid}|${f.key}`;
      if (subCache[ck] && Date.now() - subCache[ck].at < 60_000) continue;
      try {
        const r = await api.get(`/api/mail/${bid}/list?folder=${encodeURIComponent(f.key)}&offset=0`);
        subCache[ck] = { items: r.items.slice(0, 20), total: r.total, at: Date.now() };
      } catch { subCache[ck] = { items: [], total: 0, at: Date.now() }; }
      if (seq !== subSeq) return;
      paint();
    }
  }
  const subRow = (m, bid, fkey) => {
    const who = fkey === 'sent' ? (m.to?.name || m.to?.email) : nameOf(m.from);
    return h('div', { class: `gm-row gm-subrow ${m.seen ? '' : 'unread'}`, role: 'listitem', tabindex: 0,
      onclick: () => openMsg({ ...m, box_id: bid }, fkey), onkeydown: e => { if (e.key === 'Enter') openMsg({ ...m, box_id: bid }, fkey); } },
      h('div', { class: 'gm-row-in' }, avatarEl(m.from),
        h('div', { class: 'gm-row-main' },
          h('div', { class: 'gm-l1' }, h('span', { class: 'gm-who' }, h('span', { class: 'gm-who-n' }, who || t('(gönderen yok)')),
            m.company ? h('span', { class: 'gm-co' }, m.company) : null), h('span', { class: 'gm-time', title: full(m.date) }, when(m.date))),
          h('div', { class: 'gm-l2' }, h('span', { class: 'gm-subj' }, m.subject), h('span', { class: 'gm-snip' }, m.snippet ? ` — ${m.snippet}` : ''),
            h('span', { class: 'gm-flags' }, m.attach ? ic('attach', t('Ekli')) : null)),
          h('div', { class: 'gm-l3' }, h('span', { class: 'gm-snip' }, m.snippet || '')))));
  };
  // Her yükleme bir sıra numarası alır: klasör / arama değişince eski yanıt yeni listenin yerine çizilmez.
  // Sonraki sayfa sıra konumuyla (offset) istenir: arşivle / sil sonrası ileti atlanmaz.
  async function loadList(append = false) {
    if (vmode !== 'folders') { if (!append) loadPicked(); return; }
    if (append && loading) return;
    const seq = ++loadSeq, key = `${cur.box}|${cur.folder}|${q}|${lv.sort}|${lv.filter}`;
    loading = true;
    if (!append && (!items.length || root.dataset.k !== key)) clear(list, h('div', { class: 'gm-skel' }, Array.from({ length: 8 }, () => h('div', { class: 'gm-skel-row' }, h('i'), h('span', null, h('b'), h('em'), h('em'))))));
    root.dataset.k = key;
    try {
      if (cur.box === 'all') {
        const r = await api.get(`/api/mail/unified/list?folder=${encodeURIComponent(folderOfList())}&q=${encodeURIComponent(q)}${lvQuery()}`);
        if (seq !== loadSeq) return;
        items = r.items; total = r.items.length;
        r.errors.forEach(e => { const b = boxOf(e.box_id); if (b) b.last_error = e.error; });
      } else {
        const r = await api.get(`/api/mail/${cur.box}/list?folder=${encodeURIComponent(cur.folder)}&offset=${append ? items.length : 0}&q=${encodeURIComponent(q)}${lvQuery()}`);
        if (seq !== loadSeq) return;
        if (append) { const have = new Set(items.map(keyOf)); items = items.concat(r.items.filter(m => !have.has(keyOf(m)))); }
        else items = r.items;
        total = r.total;
      }
    } catch (e) { if (seq !== loadSeq) return; if (!append) { items = []; total = 0; } toastError(e); }
    loading = false;
    for (const k of [...sel.keys()]) if (!items.some(m => keyOf(m) === k)) sel.delete(k);
    drawList(); syncSel();
  }
  let lastTop = 0;
  scroll.addEventListener('scroll', () => {
    const y = scroll.scrollTop;
    fab.classList.toggle('mini', y > 40);
    if (Math.abs(y - lastTop) > 24 || y < 60) { bars.classList.toggle('away', y > lastTop && y > 120 && !sel.size); lastTop = y; }   // Gmail: aşağı kayınca arama çubuğu çekilir

    if (!loading && hasMore() && scroll.scrollTop + scroll.clientHeight > scroll.scrollHeight - 400) loadList(true);
  }, { passive: true });
  // aşağı çekip yenile (mobil)
  let ptrY = null;
  scroll.addEventListener('touchstart', e => { ptrY = scroll.scrollTop <= 0 ? e.touches[0].clientY : null; }, { passive: true });
  scroll.addEventListener('touchmove', e => {
    if (ptrY === null) return;
    const dy = Math.max(0, Math.min(120, e.touches[0].clientY - ptrY));
    ptr.style.transform = `translateY(${dy - 48}px) rotate(${dy * 3}deg)`; ptr.classList.toggle('arm', dy > 70);
  }, { passive: true });
  scroll.addEventListener('touchend', () => {
    if (ptrY !== null && ptr.classList.contains('arm')) { ptr.classList.add('spin'); Promise.all([loadList(), refreshFolders()]).finally(() => ptr.classList.remove('spin', 'arm')); }
    ptrY = null; ptr.style.transform = '';
  });

  // ---- seçim
  function toggleSel(m) {
    const k = keyOf(m);
    sel.has(k) ? sel.delete(k) : sel.set(k, m);
    syncSel();
  }
  function syncSel() {
    list.querySelectorAll('.gm-row').forEach(r => {
      const on = sel.has(r.dataset.k);
      r.classList.toggle('sel', on);
      const cb = r.querySelector('.gm-cb'); if (cb) cb.checked = on;
    });
    const n = sel.size, ms = [...sel.values()];
    root.classList.toggle('selecting', n > 0);
    selbar.hidden = !n;
    const hc = listHead.querySelector('.gm-cb'); if (hc) { hc.checked = n > 0 && n === items.length; hc.indeterminate = n > 0 && n < items.length; }
    if (!n) return;
    const pop = ms.some(m => isPop(bidOf(m)));   // seçimde POP3 iletisi varsa arşiv / yıldız / taşı / spam yok
    const allRead = ms.every(m => m.seen);
    clear(selbar, ibtn('close', 'Seçimi kaldır', () => { sel.clear(); syncSel(); }), h('b', { class: 'grow' }, String(n)),
      folderOfList() === 'inbox' && !pop ? ibtn('archive', 'Arşivle', () => act(ms, 'archive')) : null,
      ['spam', 'trash', 'archive', 'all'].includes(folderOfList()) && !pop ? ibtn('unarchive', 'Gelen kutusuna taşı', () => act(ms, 'inbox')) : null,
      ibtn('delete', pop || folderOfList() === 'trash' ? 'Kalıcı sil' : 'Sil', () => act(ms, 'trash')),
      ibtn(allRead ? 'unread' : 'read', allRead ? 'Okunmadı işaretle' : 'Okundu işaretle', () => act(ms, allRead ? 'unread' : 'read')),
      ibtn('more', 'Diğer', e => popMenu(e.currentTarget, [
        pop ? null : { icon: 'star', label: t('Yıldızla'), run: () => act(ms, 'star') },
        pop ? null : { icon: 'starO', label: t('Yıldızı kaldır'), run: () => act(ms, 'unstar') },
        folderOfList() !== 'spam' && !pop ? { icon: 'spam', label: t('Gereksiz olarak bildir'), run: () => act(ms, 'spam') } : null,
        { icon: 'check', label: t('Tümünü seç'), run: () => { items.forEach(m => sel.set(keyOf(m), m)); syncSel(); } }])));
  }

  // ---- işlemler (iyimser; arşiv / sil 5 sn geri alınabilir)
  let pending = null;
  function flush() {   // bekleyen arşiv / sil hemen uygulanır (artık geri alınamaz → şerit de kalkar)
    if (!pending) return;
    const p = pending; pending = null; clearTimeout(p.timer); snackEl?.remove(); commit(p.ms, p.act, p.target, p.folder);
  }
  // Klasör işlem anında sabitlenir (bekleme sırasında başka klasöre geçilse de doğru klasöre gider); hesaplar ayrı ayrı denenir
  async function commit(ms, act, target, folder = folderOfList()) {
    const groups = new Map();
    ms.forEach(m => { const bid = bidOf(m); (groups.get(bid) || groups.set(bid, []).get(bid)).push(m.uid); });
    let failed = false;
    for (const [bid, uids] of groups) {
      try { await api.post(`/api/mail/${bid}/action`, { folder, uids, action: act, target }); } catch (e) { failed = true; toastError(e); }
    }
    if (!root.isConnected) return;
    if (failed) loadList();
    groups.forEach((_, bid) => loadFolders(bid));
  }
  function act(ms, action, target) {
    if (!ms.length) return;
    const fOf = m => m.folder || folderOfList();
    const fs = [...new Set(ms.map(fOf))];
    if (fs.length > 1) { fs.forEach(f => act(ms.filter(m => fOf(m) === f), action, target)); return; }   // Kişiler / Cariler: farklı klasörler
    const folder = fOf(ms[0]);
    const removes = ['archive', 'trash', 'inbox', 'spam', 'move'].includes(action);
    const permanent = action === 'trash' && (folder === 'trash' || ms.some(m => isPop(bidOf(m))));
    if (permanent) {
      confirmDialog(t('Kalıcı sil'), t('{n} ileti sunucudan kalıcı olarak silinsin mi?', { n: ms.length }), { okLabel: t('Sil'), danger: true }).then(okd => { if (okd) doRemove(); });
      return;
    }
    if (!removes) {
      ms.forEach(m => { if (action === 'read') m.seen = true; if (action === 'unread') m.seen = false; if (action === 'star') m.starred = true; if (action === 'unstar') m.starred = false; });
      sel.clear(); drawList(); syncSel();
      commit(ms, action, target, folder);
      return;
    }
    doRemove();
    function doRemove() {
      flush();
      const keys = new Set(ms.map(keyOf));
      const before = items.slice();
      items = items.filter(m => !keys.has(keyOf(m)));
      total = Math.max(0, total - ms.length);
      sel.clear(); drawList(); syncSel();
      if (msgCur && keys.has(openKey)) closeReader();
      const word = { archive: 'arşivlendi', trash: permanent ? 'kalıcı silindi' : 'çöp kutusuna taşındı', inbox: 'gelen kutusuna taşındı', spam: 'gereksiz olarak bildirildi', move: 'taşındı' }[action];
      const text = ms.length > 1 ? t('{n} ileti {w}', { n: ms.length, w: t(word) }) : t('İleti {w}', { w: t(word) });
      if (permanent) { commit(ms, action, target, folder); snack(text); return; }
      pending = { ms, act: action, target, folder, timer: setTimeout(() => { if (pending?.ms === ms) { pending = null; commit(ms, action, target, folder); } }, 5200) };
      snack(text, () => { if (pending?.ms === ms) { clearTimeout(pending.timer); pending = null; items = before; total += ms.length; drawList(); } });
    }
  }
  function toggleStar(m, btn) {
    m.starred = !m.starred;
    document.querySelectorAll(`.gm-row[data-k="${keyOf(m)}"] .gm-star`).forEach(b => { b.classList.toggle('on', m.starred); clear(b, ic(m.starred ? 'star' : 'starO')); });
    if (btn && !btn.closest('.gm-row')) { btn.classList.toggle('on', m.starred); clear(btn, ic(m.starred ? 'star' : 'starO')); }
    commit([m], m.starred ? 'star' : 'unstar');
  }
  // kaydırarak arşivle / sil (dokunmatik)
  function swipeable(r, inner, m) {
    if (isPop(bidOf(m))) return;
    let x0 = null, y0 = 0, dx = 0, lock = null;
    r.addEventListener('touchstart', e => { if (sel.size) return; x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; lock = null; inner.style.transition = 'none'; }, { passive: true });
    r.addEventListener('touchmove', e => {
      if (x0 === null) return;
      const mx = e.touches[0].clientX - x0, my = e.touches[0].clientY - y0;
      if (lock === null && (Math.abs(mx) > 8 || Math.abs(my) > 8)) lock = Math.abs(mx) > Math.abs(my) ? 'x' : 'y';
      if (lock !== 'x') return;
      dx = mx; inner.style.transform = `translateX(${dx}px)`;
      r.classList.toggle('sw-l', dx > 0); r.classList.toggle('sw-r', dx < 0);
      r.classList.toggle('sw-arm', Math.abs(dx) > r.clientWidth * 0.4);
    }, { passive: true });
    r.addEventListener('touchend', () => {
      if (x0 === null) return;
      inner.style.transition = '';
      const go = lock === 'x' && Math.abs(dx) > r.clientWidth * 0.4;
      if (go) {
        inner.style.transform = `translateX(${dx > 0 ? '' : '-'}110%)`;
        const action = dx > 0 && folderOfList() === 'inbox' ? 'archive' : 'trash';
        setTimeout(() => act([m], action), 160);
      } else inner.style.transform = '';
      if (lock === 'x') r._noClick = Date.now() + 400;
      x0 = null; r.classList.remove('sw-arm');
    });
  }

  // ---- okuma
  async function openMsg(m, folder = m.folder || folderOfList()) {
    flush();
    const bid = bidOf(m);
    openKey = `${bid}:${m.uid}`;
    msgCur = null;   // yeni ileti yüklenirken kısayollar önceki iletiye uygulanmasın
    list.querySelectorAll('.gm-row').forEach(r => r.classList.toggle('open', r.dataset.k === openKey));
    if (!root.classList.contains('reading')) { root.classList.add('reading'); if (!wide()) history.pushState({ gm: 'read' }, ''); }
    clear(reader, h('div', { class: 'gm-rbar' }, ibtn('back', 'Geri', () => closeReader())), h('div', { class: 'gm-loading' }, h('div', { class: 'gm-spin' })));
    let msg;
    try { msg = await api.get(`/api/mail/${bid}/msg?folder=${encodeURIComponent(folder)}&uid=${m.uid}`); }
    catch (e) { clear(reader, h('div', { class: 'gm-rbar' }, ibtn('back', 'Geri', () => closeReader())), h('div', { class: 'gm-empty' }, ic('spam'), h('b', null, e.message))); return; }
    if (openKey !== `${bid}:${m.uid}`) return;
    m.starred ??= msg.starred;
    msgCur = { ...msg, box: bid, folder, item: m };
    if (!m.seen) {
      m.seen = true;
      list.querySelector(`.gm-row[data-k="${openKey}"]`)?.classList.remove('unread');
      loadFolders(bid);
    }
    drawReader();
  }
  function closeReader(fromPop) {
    if (!root.classList.contains('reading')) return;
    root.classList.remove('reading'); openKey = null; msgCur = null;
    list.querySelectorAll('.gm-row.open').forEach(r => r.classList.remove('open'));
    clear(reader, h('div', { class: 'gm-noread' }, ic('allMail'), h('span', null, t('Okumak için bir ileti seçin'))));
    if (!fromPop && !wide() && history.state?.gm === 'read') history.back();
  }
  function drawReader() {
    const msg = msgCur, bid = msg.box, folder = msg.folder, m = msg.item, box = boxOf(bid);
    const pop = isPop(bid);
    const people = msg.people || {};
    const coOf = a => people[(a?.email || '').toLowerCase()];
    let remote = false;
    const frame = h('iframe', { class: 'gm-frame', sandbox: 'allow-same-origin allow-popups allow-popups-to-escape-sandbox', title: msg.subject, scrolling: 'no' });
    const dark = document.documentElement.dataset.theme === 'dark';
    // Koyu temada: sade e-posta koyu renklerle; tasarımlı (arka planı / renkleri belirlenmiş) bülten beyaz "kâğıt" üzerinde
    const designed = /bgcolor=|background(-color)?\s*:|<table[^>]+background=/i.test(msg.html || '') || ((msg.html || '').match(/color\s*:/gi) || []).length > 6;
    const paper = dark && msg.html && designed;
    frame.classList.toggle('paper', !!paper);
    const fit = () => {
      try {
        const doc = frame.contentDocument; if (!doc?.body) return;
        const body = doc.body, de = doc.documentElement;
        body.style.zoom = '';
        const cw = frame.clientWidth, sw = Math.max(body.scrollWidth, de.scrollWidth);
        if (sw > cw + 4) body.style.zoom = String(Math.max(0.35, cw / sw));   // geniş bülten e-postası telefona sığsın (Gmail gibi)
        // Yükseklik zaten ölçekli düzenden: gövdenin alt kenarı (çerçeve küçülebilsin), taşma varsa belgenin kaydırma yüksekliği
        const hgt = Math.max(body.getBoundingClientRect().bottom, de.scrollHeight > frame.clientHeight + 1 ? de.scrollHeight : 0);
        frame.style.height = `${Math.max(80, Math.ceil(hgt) + 12)}px`;
      } catch { frame.style.height = '70vh'; }
    };
    const setDoc = () => {
      const csp = `default-src 'none'; img-src data: cid: ${remote ? 'https: http:' : ''}; style-src 'unsafe-inline' ${remote ? 'https:' : ''}; font-src data: ${remote ? 'https:' : ''}`;
      const body = msg.html ? (remote ? stripSelf(msg.html) : msg.html) : `<div class="pt">${esc(msg.text)}</div>`;
      const fg = dark && !paper ? '#E3E3E3' : '#1F1F1F', ln = dark && !paper ? '#A8C7FA' : '#0B57D0';
      frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank">
        <style>:root{color-scheme:${dark && !paper ? 'dark' : 'light'}}html,body{margin:0;padding:0;background:transparent}body{font:14px/1.55 Roboto,-apple-system,"Segoe UI",Arial,sans-serif;color:${fg};word-wrap:break-word;overflow-wrap:anywhere}
        .pt{white-space:pre-wrap;font-size:15px;line-height:1.6}img{max-width:100%;height:auto}a{color:${ln}}blockquote{margin:0 0 0 .8ex;border-left:1px solid #ccc;padding-left:1ex}pre{white-space:pre-wrap}</style></head><body>${body}</body></html>`;
    };
    frame.addEventListener('load', () => {
      fit();
      try { frame.contentDocument.querySelectorAll('img').forEach(i => i.addEventListener('load', fit)); new ResizeObserver(fit).observe(frame.contentDocument.body); } catch { /* */ }
      let n = 0; const tm = setInterval(() => { fit(); if (++n > 8) clearInterval(tm); }, 400);
    });
    setDoc();
    const hasRemote = /<img[^>]+src=["']?https?:/i.test(msg.html || '');
    const fs = (folderCache[bid] || []).filter(f => !['inbox', 'starred', 'important', 'all', 'drafts'].includes(f.key) && f.key !== folder);
    const remove = action => act([m], action);
    const moreItems = anchor => [
      { icon: 'reply', label: t('Yanıtla'), run: () => compose({ mode: 'reply', msg, box: bid }) },
      { icon: 'replyAll', label: t('Tümünü yanıtla'), run: () => compose({ mode: 'all', msg, box: bid }) },
      { icon: 'forward', label: t('Yönlendir'), run: () => compose({ mode: 'forward', msg, box: bid }) },
      '-',
      pop ? null : { icon: m.starred ? 'starO' : 'star', label: t(m.starred ? 'Yıldızı kaldır' : 'Yıldızla'), run: () => { toggleStar(m); drawReader(); } },
      fs.length && !pop ? { icon: 'move', label: t('Taşı…'), run: () => popMenu(anchor, [{ head: t('Şuraya taşı') },
        ...fs.map(f => ({ icon: FOLDER_ICON[f.key] || 'folder', label: f.title, run: () => act([m], 'move', f.key) }))]) } : null,
      folder !== 'spam' && !pop ? { icon: 'spam', label: t('Spam olarak bildir'), run: () => remove('spam') } : null,
      d.can_import && msg.attachments.length && !pop ? { icon: 'doc', label: t('Ekleri Evraklara kaydet'), run: () => importDocs() } : null,
    ];
    async function importDocs() {
      try {
        const r = await api.post(`/api/mail/${bid}/import`, { folder, uid: msg.uid });
        toast(r.imported ? t('{n} ek evraklara kaydedildi (yalnızca siz görürsünüz)', { n: r.imported }) : t('Ekler zaten kayıtlı ya da desteklenmeyen türde'));
      } catch (e) { toastError(e); }
    }
    const isDraft = folder === 'drafts';
    const star = pop ? null : h('button', { type: 'button', class: `gm-star big ${m.starred ? 'on' : ''}`, title: t('Yıldız'), onclick: e => toggleStar(m, e.currentTarget) }, ic(m.starred ? 'star' : 'starO'));
    const meWord = () => {
      const mine = new Set(boxes.map(b => b.email.toLowerCase()));
      const all = [...msg.to, ...msg.cc].map(a => (mine.has((a.email || '').toLowerCase()) ? t('bana') : nameOf(a)));
      const shown = all.slice(0, 2);
      return (shown.length ? shown : [t('alıcı yok')]).join(', ') + (all.length > shown.length ? ` +${all.length - shown.length}` : '');
    };

    // ---- "Mail bilgileri" kartı: Kişiler (firmaya atanabilir) ve Ekler (düğme)
    let infoOpen = true, infoTab = 'people';
    try { infoOpen = localStorage.getItem('gm.info') !== '0'; infoTab = localStorage.getItem('gm.infoTab') || 'people'; } catch { /* */ }
    const info = h('section', { class: 'gm-info' });
    const personBtn = a => {
      const co = coOf(a);
      const b = h('button', { type: 'button', class: `gm-pbtn ${co ? 'has-co' : ''}`, title: a.email, onclick: e => personMenu(e.currentTarget, a) },
        avatarEl(a), h('span', { class: 'gm-pbtn-t' }, h('b', null, nameOf(a) || a.email), co ? h('small', { class: 'gm-pbtn-co' }, co.company_name + (co.title ? ` · ${co.title}` : ''))
          : h('small', null, a.email)));
      b.querySelector('.gm-av').tabIndex = -1;
      return b;
    };
    const group = (title, list) => (list.length ? h('div', { class: 'gm-pgroup' }, h('div', { class: 'gm-pgroup-h' }, title), h('div', { class: 'gm-pgroup-l' }, list.map(personBtn))) : null);
    const attBtn = a => {
      const url = `/api/mail/${bid}/att?folder=${encodeURIComponent(folder)}&uid=${msg.uid}&idx=${a.idx}`;
      const img = /^image\//.test(a.type);
      const ext = (a.name.split('.').pop() || '').slice(0, 4).toUpperCase();
      const kind = img ? 'img' : /pdf$/i.test(a.type) || ext === 'PDF' ? 'pdf' : /sheet|excel|csv/i.test(a.type) || /XLS|CSV/.test(ext) ? 'xls' : /word|document/i.test(a.type) || /DOC/.test(ext) ? 'doc' : 'file';
      return h('a', { class: `gm-abtn ${kind}`, href: `${url}${/^(image|audio|video)\/|pdf$/.test(a.type) ? '&inline=true' : ''}`, target: '_blank', rel: 'noopener', title: a.name },
        img ? h('span', { class: 'gm-abtn-th' }, h('img', { src: `${url}&inline=true`, alt: '', loading: 'lazy' })) : h('span', { class: 'gm-abtn-ic' }, ext || '•'),
        h('span', { class: 'gm-abtn-t' }, h('b', null, a.name), h('small', null, size(a.size))));
    };
    const drawInfo = () => {
      const tabs = [['people', t('Kişiler'), 1 + msg.to.length + msg.cc.length], ['att', t('Ekler'), msg.attachments.length]];
      const replyTo = msg.reply_to.filter(a => a.email && a.email.toLowerCase() !== (msg.from.email || '').toLowerCase());
      const fromCo = coOf(msg.from);
      clear(info,
        h('button', { type: 'button', class: 'gm-info-h', 'aria-expanded': String(infoOpen), onclick: () => { infoOpen = !infoOpen; try { localStorage.setItem('gm.info', infoOpen ? '1' : '0'); } catch { /* */ } drawInfo(); } },
          h('span', { class: 'gm-info-ttl' }, t('Mail bilgileri')),
          infoOpen ? null : h('span', { class: 'gm-info-sum' }, [nameOf(msg.from) + (fromCo ? ` (${fromCo.company_name})` : ''), msg.attachments.length ? t('{n} ek', { n: msg.attachments.length }) : null].filter(Boolean).join(' · ')),
          h('span', { class: 'grow' }), ic('expand')),
        infoOpen ? [
          h('div', { class: 'gm-tabs', role: 'tablist' }, tabs.map(([k, l, n]) => h('button', { type: 'button', role: 'tab', class: `gm-tab ${infoTab === k ? 'on' : ''}`, 'aria-selected': String(infoTab === k),
            onclick: () => { infoTab = k; try { localStorage.setItem('gm.infoTab', k); } catch { /* */ } drawInfo(); } }, l, h('span', { class: 'gm-tab-n' }, n)))),
          infoTab === 'people' ? h('div', { class: 'gm-tabp' },
            group(t('Gönderen'), [msg.from]), group(t('Kime'), msg.to), group(t('Bilgi (CC)'), msg.cc), group(t('Yanıt adresi'), replyTo),
            h('div', { class: 'gm-info-meta' }, h('span', null, full(msg.date)), h('span', null, box?.email || ''),
              msg.can_assign ? h('span', { class: 'gm-info-hint' }, t('Kişiye dokunup bir firmanın personeli olarak atayabilirsiniz')) : null))
            : h('div', { class: 'gm-tabp' }, msg.attachments.length
              ? [h('div', { class: 'gm-abtns' }, msg.attachments.map(attBtn)),
                d.can_import && !pop ? h('button', { type: 'button', class: 'gm-btn-text', onclick: importDocs }, ic('doc'), t('Tümünü Evraklara kaydet')) : null]
              : h('div', { class: 'gm-info-none' }, ic('attach'), t('Bu iletide ek yok')))] : null);
    };
    function personMenu(anchor, a) {
      const co = coOf(a);
      popMenu(anchor, [{ head: `${nameOf(a) || ''} <${a.email}>` },
        co ? { icon: 'folder', label: t('Firma: {c}', { c: co.company_name }), run: () => { location.hash = `#/companies/${co.company_id}`; } } : null,
        msg.can_assign ? { icon: co ? 'move' : 'add', label: co ? t('Başka firmaya ata') : t('Bir firmanın personeli olarak ata'), run: () => assign(a) } : null,
        msg.can_assign && co ? { icon: 'close', label: t('Firma bağlantısını kaldır'), run: () => unassign(a) } : null,
        '-',
        { icon: 'edit', label: t('E-posta gönder'), run: () => compose({ to: [a] }) },
        { icon: 'doc', label: t('Adresi kopyala'), run: () => navigator.clipboard?.writeText(a.email).then(() => snack(t('Adres kopyalandı'))) }]);
    }
    const applyCo = (email, co) => {
      const key = email.toLowerCase();
      if (co) people[key] = co; else delete people[key];
      items.forEach(it => { if ((it.from?.email || '').toLowerCase() === key) it.company = co?.company_name || null; });
      drawList(); syncSel(); drawReader();
    };
    async function unassign(a) {
      const co = coOf(a);
      if (!co || !await confirmDialog(t('Firma bağlantısını kaldır'), t('{e} adresi {c} firmasındaki kişiden ({p}) kaldırılsın mı? Kişi firmada kalır, yalnız e-posta adresi silinir.', { e: a.email, c: co.company_name, p: co.person_name }), { okLabel: t('Kaldır') })) return;
      try {
        const r = await api.del(`/api/mail/people/assign?person_id=${co.person_id}&email=${encodeURIComponent(a.email)}`);
        applyCo(a.email, r.company || null);
        snack(r.company ? t('Bağlantı kaldırıldı; adres {c} firmasında da kayıtlı', { c: r.company.company_name }) : t('Firma bağlantısı kaldırıldı'));
      } catch (e) { toastError(e); }
    }
    function assign(a) {
      const co = coOf(a);
      let picked = co ? { id: co.company_id, name: co.company_name } : null;
      const nm = h('input', { class: 'input', value: co?.person_name || nameOf(a) || '', placeholder: t('Ad soyad') });
      const title = h('input', { class: 'input', value: co?.title || '', placeholder: t('ör. Satın Alma Müdürü') });
      const phone = h('input', { class: 'input', type: 'tel', placeholder: '05xx xxx xx xx' });
      const qIn = h('input', { class: 'input', type: 'search', placeholder: t('Firma adı yazın…'), value: picked?.name || '' });
      const res = h('div', { class: 'gm-colist' });
      const chosen = h('div', { class: 'gm-cochosen' });
      const drawChosen = () => clear(chosen, picked ? [ic('check'), h('b', null, picked.name)] : h('small', { class: 'muted' }, t('Listeden bir firma seçin')));
      // Aynı kişinin başka bir adresi mi? Firmanın kişilerinden biri seçilirse adres ona EK ADRES olarak eklenir (yeni kişi açılmaz)
      const who = h('select', { class: 'input' }, h('option', { value: '' }, t('— Yeni kişi olarak ekle —')));
      const newFields = h('div', null);
      // Rehber'deki herhangi bir kişi (başka firmadaki ya da firmasız): seçilince "Kişi" listesine eklenip seçilir
      const pq = h('input', { class: 'input', type: 'search', placeholder: t('Ad ya da e-posta…') });
      const pres = h('div', { class: 'gm-colist' });
      let ptm;
      pq.addEventListener('input', () => { clearTimeout(ptm); ptm = setTimeout(async () => {
        if (!pq.value.trim()) { clear(pres); return; }
        try {
          const ps = await api.get(`/api/mail/people/search?q=${encodeURIComponent(pq.value.trim())}`);
          clear(pres, ps.map(p => h('button', { type: 'button', class: 'gm-coitem', onclick: () => {
            if (![...who.options].some(o => o.value === String(p.id))) who.append(h('option', { value: p.id }, p.full_name));
            who.value = String(p.id); newFields.hidden = true; clear(pres); pq.value = '';
          } }, h('span', { class: 'grow' }, p.full_name), h('small', null, (p.companies || []).map(z => z.name).join(', ') || t('firmasız')))));
        } catch { clear(pres); }
      }, 200); });
      newFields.append(
        h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', null, t('Ad soyad')), nm), h('label', { class: 'field' }, h('span', null, t('Ünvan')), title)),
        h('label', { class: 'field' }, h('span', null, t('Telefon (isteğe bağlı)')), phone));
      who.addEventListener('change', () => { newFields.hidden = !!who.value; });
      const loadPeople = async () => {
        clear(who, h('option', { value: '' }, t('— Yeni kişi olarak ekle —')));
        newFields.hidden = false;
        if (!picked) return;
        try {
          const ps = await api.get(`/api/mail/companies/${picked.id}/people`);
          ps.forEach(p => who.append(h('option', { value: p.id }, `${p.full_name}${p.emails.length ? ` (${p.emails.join(', ')})` : ''}`)));
        } catch { /* kişiler yüklenemezse yalnız yeni kişi */ }
      };
      let tm;
      const search = async () => {
        try {
          const rows = await api.get(`/api/mail/companies?q=${encodeURIComponent(qIn.value.trim())}`);
          clear(res, rows.length ? rows.map(c => h('button', { type: 'button', class: `gm-coitem ${picked?.id === c.id ? 'on' : ''}`, onclick: () => { picked = { id: c.id, name: c.name }; drawChosen(); search(); loadPeople(); } },
            h('span', { class: 'grow' }, c.name), c.is_supplier ? h('small', { class: 'gm-co-sup' }, t('Tedarikçi')) : null, h('small', null, t('{n} kişi', { n: c.people })))) :h('div', { class: 'small muted', style: 'padding:8px' }, t('Firma bulunamadı (Firma Yönetimi’nden ekleyin)')));
        } catch (e) { clear(res, h('div', { class: 'small muted' }, e.message)); }
      };
      qIn.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(search, 200); });
      drawChosen(); search(); loadPeople();
      modal({ title: t('Firmaya personel olarak ata'), body: h('div', { class: 'gm-assign' },
        h('div', { class: 'gm-assign-who' }, avatarEl(a), h('div', null, h('b', null, nameOf(a) || a.email), h('small', null, a.email))),
        h('label', { class: 'field' }, h('span', null, t('Firma')), qIn), res, chosen,
        h('label', { class: 'field' }, h('span', null, t('Kişi')), who,
          h('small', { class: 'hint' }, t('Bu adres zaten tanıdığınız birine aitse (başka firmadaki adresiyle bile) onu seçin: adres o kişiye bu firmayla eklenir.'))),
        h('label', { class: 'field' }, h('span', null, t('Rehber’de ara')), pq, pres),
        newFields,
        h('p', { class: 'small muted' }, t('Kişi seçilen firmanın kişileri arasına kalıcı olarak kaydedilir; bu adresten gelen e-postalarda firma adı görünür. Adres başka bir firmada da kayıtlıysa oradaki kişiye dokunulmaz.'))),
      actions: [{ label: t('Vazgeç') }, { label: t('Kaydet'), class: 'primary', onClick: async () => {
        if (!picked) throw new Error(t('Bir firma seçin'));
        // maildeki diğer kişiler: aynı alan adından bilinmeyenler sunucuda aynı firmaya otomatik eklenir (sihirbaz açılmaz)
        const others = [msg.from, ...msg.to, ...msg.cc, ...msg.reply_to]
          .filter(x => x?.email && x.email.toLowerCase() !== a.email.toLowerCase()).map(x => ({ email: x.email, name: x.name || null }));
        const r = await api.post('/api/mail/people/assign', { email: a.email, full_name: nm.value.trim(), company_id: picked.id, title: title.value, phone: phone.value,
          person_id: who.value ? Number(who.value) : null, others });
        const also = r.also || [];
        delete r.also;
        applyCo(a.email, r);
        also.forEach(x => applyCo(x.email, x));
        const who = r.person_name || nm.value.trim() || a.email;
        if (!also.length) snack(t('{n}, {c} firmasına eklendi', { n: who, c: picked.name }));
        else snack(t('{n} ve aynı alan adından {k} kişi daha {c} firmasına eklendi', { n: who, k: also.length, c: picked.name }), async () => {
          try {   // geri al: otomatik eklenen kişiler silinir (elle eklenen kişiye dokunulmaz)
            for (const x of also) {
              const u = await api.del(`/api/mail/people/assign?person_id=${x.person_id}&email=${encodeURIComponent(x.email)}&auto=1`);
              applyCo(x.email, u.company || null);
            }
            snack(t('Otomatik eklenen {k} kişi geri alındı', { k: also.length }));
          } catch (e) { toastError(e); }
        }, 8000);
      } }] });
      setTimeout(() => qIn.focus(), 50);
    }
    drawInfo();

    const inv = msg.invite;
    const fromCo = coOf(msg.from);
    clear(reader,
      h('div', { class: 'gm-rbar' }, ibtn('back', 'Geri', () => closeReader(), 'gm-back'), h('span', { class: 'grow' }),
        folder === 'inbox' && !pop ? ibtn('archive', 'Arşivle', () => remove('archive')) : null,
        ['spam', 'trash', 'archive', 'all'].includes(folder) && !pop ? ibtn('unarchive', 'Gelen kutusuna taşı', () => remove('inbox')) : null,
        ibtn('delete', pop || folder === 'trash' ? 'Kalıcı sil' : 'Sil', () => remove('trash')),
        ibtn('unread', 'Okunmadı olarak işaretle', () => { act([m], 'unread'); closeReader(); }),
        ibtn('more', 'Diğer', e => popMenu(e.currentTarget, moreItems(e.currentTarget)))),
      h('div', { class: 'gm-rscroll' },
        h('div', { class: 'gm-subj-row' }, h('h1', null, msg.subject, h('button', { type: 'button', class: 'gm-fchip', onclick: () => { closeReader(); if (cur.box !== bid || cur.folder !== folder) select(bid, folder); } }, folderTitleFor(bid, folder))), star),
        info,
        h('div', { class: 'gm-from' }, avatarEl(msg.from),
          h('div', { class: 'gm-from-t' },
            h('div', { class: 'gm-from-l1' }, h('b', null, nameOf(msg.from)), fromCo ? h('span', { class: 'gm-co' }, fromCo.company_name) : h('span', { class: 'gm-from-em' }, `<${msg.from.email}>`),
              h('span', { class: 'gm-from-time', title: full(msg.date) }, when(msg.date))),
            h('button', { type: 'button', class: 'gm-to', onclick: () => { infoOpen = true; infoTab = 'people'; drawInfo(); info.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } },
              t('kime: {w}', { w: meWord() }), ic('expand'))),
          isDraft ? null : ibtn('reply', 'Yanıtla', () => compose({ mode: 'reply', msg, box: bid }), 'gm-from-reply'),
          ibtn('more', 'Diğer', e => popMenu(e.currentTarget, moreItems(e.currentTarget)), 'gm-from-more')),
        inv ? h('div', { class: 'gm-invite' }, h('span', { class: 'gm-invite-d' }, h('small', null, new Date(inv.starts_at).toLocaleDateString('tr-TR', { month: 'short' })), h('b', null, new Date(inv.starts_at).getDate())),
          h('div', { class: 'grow' }, h('b', null, inv.title), h('small', null, [full(inv.starts_at), inv.location, inv.organizer].filter(Boolean).join(' · ')),
            inv.status === 'cancelled' ? h('small', { class: 'gm-red' }, t('Etkinlik iptal edildi')) : null),
          inv.added ? h('span', { class: 'gm-ok' }, ic('check'), t('Takviminizde')) : h('button', { class: 'gm-btn-tonal', type: 'button', onclick: async () => {
            try { await api.post(`/api/mail/${bid}/invite`, { folder, uid: msg.uid }); inv.added = true; toast(t('Kişisel takviminize eklendi'), 'success'); drawReader(); } catch (err) { toastError(err); }
          } }, ic('event'), t('Takvime ekle'))) : null,
        hasRemote ? h('div', { class: 'gm-remote' }, ic('image'), h('span', { class: 'grow' }, t('Uzak resimler gizliliğiniz için gösterilmiyor.')),
          h('button', { type: 'button', onclick: e => { remote = true; setDoc(); e.currentTarget.parentElement.remove(); } }, t('Resimleri göster'))) : null,
        frame),
      h('div', { class: 'gm-replybar' }, isDraft
        ? h('button', { class: 'gm-pill', type: 'button', onclick: () => compose({ mode: 'draft', msg, box: bid }) }, ic('edit'), t('Taslağı düzenle'))
        : [h('button', { class: 'gm-pill', type: 'button', onclick: () => compose({ mode: 'reply', msg, box: bid }) }, ic('reply'), t('Yanıtla')),
          msg.to.length + msg.cc.length > 1 ? h('button', { class: 'gm-pill', type: 'button', onclick: () => compose({ mode: 'all', msg, box: bid }) }, ic('replyAll'), t('Tümünü yanıtla')) : null,
          h('button', { class: 'gm-pill', type: 'button', onclick: () => compose({ mode: 'forward', msg, box: bid }) }, ic('forward'), t('Yönlendir'))]));
  }
  const folderTitleFor = (bid, key) => (folderCache[bid] || []).find(f => f.key === key)?.title || (key === 'inbox' ? t('Gelen Kutusu') : key);

  // ---- yazma penceresi
  let composeWin = null;
  function compose({ mode = 'new', msg = null, box = null, to = null } = {}) {
    if (composeWin) { composeWin.focus(); if (mode === 'new' && !to) return; composeWin.close(); }
    const w = composer({ mode, msg, to, box: box || (cur.box !== 'all' ? cur.box : boxes[0].id), boxes,
      onSent: () => {
        if (!root.isConnected) return;   // gönderim, sayfadan çıkıldıktan sonra tamamlandıysa
        if (mode === 'draft' && msgCur?.folder === 'drafts' && msgCur.uid === msg.uid) closeReader();   // eski taslak yerini yenisine bıraktı
        if (['sent', 'drafts'].includes(cur.folder)) loadList();
        refreshFolders();
      },
      onClose: () => { if (composeWin === w) composeWin = null; },
      onReopen: () => { if (composeWin && composeWin !== w) composeWin.close(); composeWin = w; } });
    composeWin = w;
  }

  // ---- klavye (masaüstü, Gmail kısayolları): c yeni, / ara, e arşivle, # sil, u listeye dön
  function keys(e) {
    if (e.target.closest('input, textarea, [contenteditable="true"], select, .gm-c, .gm-pop, .modal, .modal-back') || e.metaKey || e.ctrlKey || e.altKey || document.querySelector('.modal-back, .gm-pop')) return;
    const open = msgCur && `${msgCur.box}:${msgCur.item.uid}` === openKey ? msgCur : null;   // yalnız ekranda açık olan ileti
    if (e.key === 'c') { e.preventDefault(); compose(); }
    else if (e.key === '/') { e.preventDefault(); search.focus(); }
    else if (e.key === 'Escape' && sel.size) { sel.clear(); syncSel(); }
    else if (open && e.key === 'u') { e.preventDefault(); closeReader(); }
    else if (open && e.key === '#') { e.preventDefault(); act([open.item], 'trash'); }
    else if (open && e.key === 'e' && open.folder === 'inbox' && !isPop(open.box)) { e.preventDefault(); act([open.item], 'archive'); }   // araç çubuğundaki gibi
  }

  const refreshFolders = () => Promise.all(boxes.map(b => loadFolders(b.id)));
  drawNav(); drawAcct();
  closeReader();
  refreshFolders();
  if (vmode !== 'folders') setMode(vmode);
  else { await loadList(); syncFolder(); }   // açılan klasörün tamamı kaydedilir (üstte ilerleme)
  if (deep) openMsg(items.find(x => keyOf(x) === `${deep.box}:${deep.uid}`) || { uid: deep.uid, seen: false, box_id: deep.box }, deep.folder);
  const tick = setInterval(() => {   // dakikada bir: yeni ileti ve klasör sayıları (seçim / okuma yokken liste yenilenir)
    if (!root.isConnected) { clearInterval(tick); return; }
    if (document.visibilityState !== 'visible') return;
    refreshFolders();
    if (vmode !== 'folders') { if (!root.classList.contains('reading')) loadPeople(); return; }
    if (!sel.size && !pending && scroll.scrollTop < 200 && !q) loadList();
  }, 60000);
}

// ---------------- yazma penceresi (masaüstü: sağ altta yüzen; mobil: tam ekran) ----------------
function composer({ mode, msg, box, boxes, onSent, onClose, onReopen, to: toInit }) {
  const re = s => (/^(re|ynt|yanıt):/i.test(s) ? s : `Re: ${s}`), fw = s => (/^(fwd?|ilt):/i.test(s) ? s : `Fwd: ${s}`);
  const me = new Set(boxes.map(b => b.email.toLowerCase()));
  // Taslak düzenlenirken gönderen hesap değişmez (taslak kendi hesabının Taslaklar klasöründe değiştirilir / silinir)
  const from = h('select', { class: 'gm-c-from', disabled: mode === 'draft' }, boxes.map(b => h('option', { value: b.id, selected: b.id === box }, b.name ? `${b.name} <${b.email}>` : b.email)));
  let dirty = false;   // yalnız değiştirilen pencere kapatılınca taslak kaydedilir
  const touch = () => { dirty = true; };
  const replyTo = msg && mode !== 'draft' ? (msg.reply_to[0] || msg.from) : null;
  const others = msg && mode === 'all' ? [...msg.to, ...msg.cc].filter(a => !me.has(a.email.toLowerCase()) && a.email !== replyTo.email) : [];
  const to = chips(toInit || (mode === 'draft' ? msg.to : (mode === 'reply' || mode === 'all') ? [replyTo] : []), touch);
  const cc = chips(mode === 'draft' ? msg.cc : others, touch);
  const bcc = chips([], touch);
  const subject = h('input', { class: 'gm-c-in', placeholder: t('Konu'), value: msg ? (mode === 'draft' ? msg.subject : mode === 'forward' ? fw(msg.subject) : re(msg.subject)) : '' });
  const quoted = msg && mode !== 'draft' ? (msg.html || `<div style="white-space:pre-wrap">${esc(msg.text)}</div>`) : '';
  const head = msg && mode === 'forward' ? `<p>---------- ${esc(t('İletilen ileti'))} ----------<br>${esc(t('Kimden'))}: ${esc(person(msg.from))}<br>${esc(t('Tarih'))}: ${esc(full(msg.date))}<br>${esc(t('Konu'))}: ${esc(msg.subject)}<br>${esc(t('Kime'))}: ${esc(msg.to.map(person).join(', '))}</p>`
    : msg && mode !== 'draft' ? `<p>${esc(t('{d} tarihinde {p} şunu yazdı:', { d: full(msg.date), p: person(msg.from) }))}</p>` : '';
  const editor = h('div', { class: 'gm-c-body', contenteditable: 'true', spellcheck: 'true', 'aria-label': t('İleti metni'), 'data-ph': t('E-posta oluşturun') });
  const syncPh = () => editor.classList.toggle('ph', !editor.innerText.trim() && !editor.querySelector('img,blockquote'));
  editor.addEventListener('input', syncPh);
  editor.innerHTML = mode === 'draft' ? (msg.html ? sanitize(msg.html) : esc(msg.text || '').replace(/\n/g, '<br>')) : (msg ? `<div><br></div><div><br></div>${head}<blockquote class="gm-quote">${sanitize(quoted)}</blockquote>` : '<div><br></div>');
  syncPh();
  const cmd = (c, v) => () => { editor.focus(); document.execCommand(c, false, v); };
  const tb = (label, c, v, title) => h('button', { type: 'button', class: 'gm-fmt-b', title: t(title), onmousedown: e => e.preventDefault(), onclick: cmd(c, v) }, label);
  const fmt = h('div', { class: 'gm-fmt', hidden: true }, tb(h('b', null, 'K'), 'bold', null, 'Kalın'), tb(h('i', null, 'İ'), 'italic', null, 'İtalik'), tb(h('u', null, 'A'), 'underline', null, 'Altı çizili'),
    tb('•', 'insertUnorderedList', null, 'Madde işaretli liste'), tb('1.', 'insertOrderedList', null, 'Numaralı liste'),
    h('button', { type: 'button', class: 'gm-fmt-b', title: t('Bağlantı'), onmousedown: e => e.preventDefault(), onclick: () => { const u = prompt(t('Bağlantı adresi')); if (u) cmd('createLink', u)(); } }, '🔗'),
    tb('⌫', 'removeFormat', null, 'Biçimi temizle'));
  const files = [];
  const docs = [];   // sistemdeki evraklardan ekler (gönderirken sunucu görme yetkisini yeniden denetler)
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const attBox = h('div', { class: 'gm-c-atts' });
  const drawAtts = () => clear(attBox,
    files.map((f, i) => h('span', { class: 'gm-c-att' }, ic('attach'), h('span', { class: 'grow' }, f.name), h('small', null, size(f.size)),
      h('button', { type: 'button', title: t('Kaldır'), onclick: () => { files.splice(i, 1); touch(); drawAtts(); } }, ic('close')))),
    docs.map((d, i) => h('span', { class: 'gm-c-att doc', title: t('Evrak Yönetimi’nden') }, ic('doc'), h('span', { class: 'grow' }, d.file_name || d.title),
      d.size ? h('small', null, size(d.size)) : null,
      h('button', { type: 'button', title: t('Kaldır'), onclick: () => { docs.splice(i, 1); touch(); drawAtts(); } }, ic('close')))));
  const addFiles = fl => { [...fl].forEach(f => files.push(f)); if (fl.length) touch(); drawAtts(); };
  fileIn.addEventListener('change', () => { addFiles(fileIn.files); fileIn.value = ''; });
  let ccOpen = !!(cc.value() || (mode === 'draft' && msg.cc.length));
  const ccRows = h('div', { hidden: !ccOpen }, h('div', { class: 'gm-c-row' }, h('label', null, t('Bilgi')), cc.el), h('div', { class: 'gm-c-row' }, h('label', null, t('Gizli')), bcc.el));
  const ccToggle = h('button', { type: 'button', class: 'gm-c-cc', hidden: ccOpen, onclick: e => { ccRows.hidden = false; e.currentTarget.hidden = true; cc.focus(); } }, ic('expand'));
  let sent = false, closed = false, sending = false, ownsHist = false;
  // Mobilde tam ekran pencere geçmişe bir kayıt ekler: telefonun geri tuşu yalnız bu pencereyi kapatır
  function onPop(e) { if (e.state?.gm === 'compose') return; ownsHist = false; window.removeEventListener('popstate', onPop); close(); }
  const pushHist = () => { if (!mobile()) return; history.pushState({ gm: 'compose' }, ''); ownsHist = true; window.addEventListener('popstate', onPop); };
  const dropHist = () => { window.removeEventListener('popstate', onPop); if (ownsHist) { ownsHist = false; if (history.state?.gm === 'compose') history.back(); } };
  const reattach = () => { onReopen?.(); pushHist(); };
  const hasContent = () => to.value() || cc.value() || subject.value.trim() || editor.innerText.trim() || files.length || docs.length;
  const form = () => {
    const fd = new FormData();
    fd.append('to', to.value()); fd.append('cc', cc.value()); fd.append('bcc', bcc.value());
    fd.append('subject', subject.value); fd.append('html', editor.innerHTML); fd.append('body', editor.innerText);
    if (msg && (mode === 'reply' || mode === 'all')) { fd.append('reply_id', msg.message_id || ''); fd.append('references', msg.references || ''); }
    if (msg && mode === 'forward') { fd.append('fwd_folder', msg.folder); fd.append('fwd_uid', String(msg.uid)); }
    files.forEach(f => fd.append('files', f));
    if (docs.length) fd.append('doc_ids', docs.map(d => d.id).join(','));
    return fd;
  };
  const send = async () => {
    if (!to.value() && !cc.value() && !bcc.value()) { toast(t('En az bir alıcı girin'), 'err'); to.focus(); return; }
    const bad = [to, cc, bcc].flatMap(x => x.invalid());
    if (bad.length) { toast(t('Geçersiz e-posta adresi: {a}', { a: bad.join(', ') }), 'err'); return; }
    if (!subject.value.trim() && !await confirmDialog(t('Konu yok'), t('Bu ileti konu satırı olmadan gönderilsin mi?'), { okLabel: t('Gönder') })) return;
    sendBtns.forEach(b => { b.disabled = true; });
    const fd = form();
    if (mode === 'draft') fd.append('draft_uid', String(msg.uid));
    // Gmail gibi: pencere kapanır, 5 sn içinde "GERİ AL" ile gönderim iptal edilip pencere geri açılabilir.
    // Bu sürede pencere ayrılır: yeni yazma penceresi, geri tuşu ya da sayfadan çıkmak gönderimi iptal etmez.
    sending = true; win.hidden = true;
    onClose?.(); dropHist();
    let undone = false;
    snack(t('Gönderiliyor…'), () => {
      undone = true; sending = false; win.hidden = false; sendBtns.forEach(b => { b.disabled = false; });
      reattach();
    }, 5000);
    await new Promise(r => setTimeout(r, 5000));
    if (undone) return;
    try {
      await api.post(`/api/mail/${from.value}/send`, fd);
      sent = true; sending = false; close(true);
      snack(t('İleti gönderildi'));
      onSent?.();
    } catch (e) { sending = false; win.hidden = false; reattach(); toastError(e); sendBtns.forEach(b => { b.disabled = false; }); }
  };
  const saveDraft = async () => {
    const fd = form();
    if (mode === 'draft') fd.append('replace_uid', String(msg.uid));
    try { await api.post(`/api/mail/${from.value}/draft`, fd); snack(t('Taslak kaydedildi')); onSent?.(); } catch (e) { toastError(e); }
  };
  function close(force) {
    if (closed || sending) return;   // gönderilirken kapatma yok sayılır (gönderim sürer)
    closed = true;
    if (!force && !sent && dirty && hasContent()) saveDraft();   // Gmail gibi: değiştirilen ileti kapatınca taslak olarak saklanır
    win.remove(); onClose?.(); dropHist();
  }
  const discard = async () => {
    if (mode === 'draft') {   // kayıtlı taslak: sunucudaki Taslaklar'dan da silinir
      if (!await confirmDialog(t('Taslağı sil'), t('Bu taslak silinsin mi?'), { okLabel: t('Sil'), danger: true })) return;
      try { await api.post(`/api/mail/${box}/action`, { folder: 'drafts', uids: [msg.uid], action: 'trash' }); } catch (e) { toastError(e); return; }
      close(true); snack(t('Taslak silindi')); onSent?.();
      return;
    }
    if (dirty && hasContent() && !await confirmDialog(t('Taslağı sil'), t('Bu ileti silinsin mi? Kaydedilmeyecek.'), { okLabel: t('Sil'), danger: true })) return;
    close(true);
  };
  const title = { new: mobile() ? t('Oluştur') : t('Yeni ileti'), reply: t('Yanıtla'), all: t('Tümünü yanıtla'), forward: t('Yönlendir'), draft: t('Taslak') }[mode];
  const sendBtns = [];
  const sendM = h('button', { type: 'button', class: 'gm-ib gm-c-send-m', title: t('Gönder'), 'aria-label': t('Gönder'), onclick: send }, ic('send')); sendBtns.push(sendM);
  const sendD = h('button', { type: 'button', class: 'gm-c-send', onclick: send }, t('Gönder')); sendBtns.push(sendD);
  const win = h('div', { class: 'gm-c', role: 'dialog', 'aria-label': title },
    h('div', { class: 'gm-c-head' },
      ibtn('close', 'Kapat', () => close(), 'gm-c-x-m'),
      h('b', { class: 'grow' }, title),
      ibtn('attach', 'Dosya ekle', () => fileIn.click(), 'gm-only-m'), sendM,
      ibtn('minimize', 'Simge durumuna küçült', () => win.classList.toggle('min'), 'gm-only-d'),
      ibtn('maximize', 'Tam ekran', () => win.classList.toggle('max'), 'gm-only-d'),
      ibtn('close', 'Kaydet ve kapat', () => close(), 'gm-only-d')),
    h('div', { class: 'gm-c-scroll' },
      boxes.length > 1 ? h('div', { class: 'gm-c-row' }, h('label', null, t('Kimden')), from) : null,
      h('div', { class: 'gm-c-row' }, h('label', null, t('Kime')), to.el, ccToggle), ccRows,
      h('div', { class: 'gm-c-row' }, subject),
      editor, attBox,
      msg && mode === 'forward' && msg.attachments.length ? h('div', { class: 'gm-c-note' }, t('Orijinal {n} ek de iletilecek', { n: msg.attachments.length })) : null),
    fmt,
    h('div', { class: 'gm-c-foot' }, sendD,
      h('button', { type: 'button', class: 'gm-ib', title: t('Biçimlendirme seçenekleri'), onclick: e => { fmt.hidden = !fmt.hidden; e.currentTarget.classList.toggle('on', !fmt.hidden); } }, ic('text')),
      ibtn('attach', 'Dosya ekle', () => fileIn.click()), fileIn,
      ibtn('doc', 'Evrak ekle (Evrak Yönetimi)', () => pickDocs({ recipients: () => [...to.emails(), ...cc.emails(), ...bcc.emails()], picked: docs, onPick: ds => { ds.forEach(d => { if (!docs.some(x => x.id === d.id)) docs.push(d); }); touch(); drawAtts(); } })),
      ibtn('personAdd', 'Kişi ekle (Rehber)', () => pickPeople({ to, cc, bcc, openCc: () => { ccRows.hidden = false; ccToggle.hidden = true; }, onPick: touch })),
      h('span', { class: 'grow' }), ibtn('delete', 'Taslağı sil', discard)));
  win.addEventListener('dragover', e => { e.preventDefault(); win.classList.add('drop'); });
  win.addEventListener('dragleave', e => { if (e.target === win) win.classList.remove('drop'); });
  win.addEventListener('drop', e => { e.preventDefault(); win.classList.remove('drop'); addFiles(e.dataTransfer.files); });
  win.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } if (e.key === 'Escape' && !document.querySelector('.gm-sug:not([hidden])')) close(); });
  win.querySelector('.gm-c-head b').addEventListener('click', () => { if (win.classList.contains('min')) win.classList.remove('min'); });
  document.body.append(win);
  pushHist();
  win.addEventListener('input', touch);
  from.addEventListener('change', touch);
  if ((mode === 'new' && !toInit) || mode === 'forward') to.focus();
  else { editor.focus(); const r = document.createRange(); r.setStart(editor, 0); r.collapse(true); getSelection().removeAllRanges(); getSelection().addRange(r); }
  return { close: f => close(f), focus: () => { win.classList.remove('min'); win.classList.add('flash'); setTimeout(() => win.classList.remove('flash'), 600); } };
}

// Yeni mail › Kişi ekle: Rehber'de erişilebilen e-postalı kişiler (ad, e-posta ya da firma adıyla); bağlı firma görünür
function pickPeople({ to, cc, bcc, openCc, onPick }) {
  let target = 'to';
  const q = h('input', { class: 'input', type: 'search', placeholder: t('Ad, e-posta ya da firma adı…'), autocomplete: 'off' });
  const res = h('div', { class: 'gm-pick-list' });
  const added = new Set([...to.emails(), ...cc.emails(), ...bcc.emails()].map(e => e.toLowerCase()));
  const tgt = segmented([['to', t('Kime')], ['cc', t('Bilgi')], ['bcc', t('Gizli')]], target, v => { target = v; });
  let tm, seq = 0;
  const search = async () => {
    const my = ++seq;
    let rows;
    try { rows = await api.get(`/api/mail/people/pick?q=${encodeURIComponent(q.value.trim())}`); } catch (e) { clear(res, h('div', { class: 'small muted' }, e.message)); return; }
    if (my !== seq) return;
    clear(res, rows.length ? rows.map(r => {
      const on = added.has(r.email.toLowerCase());
      const row = h('button', { type: 'button', class: `gm-pick-row ${on ? 'on' : ''}`, onclick: () => {
        if (added.has(r.email.toLowerCase())) return;
        ({ to, cc, bcc })[target].add({ name: r.name, email: r.email });
        if (target !== 'to') openCc();
        added.add(r.email.toLowerCase()); row.classList.add('on'); onPick?.();
      } },
      h('span', { class: 'gm-chip-av' }, letter(r)),
      h('span', { class: 'gm-pick-t' }, h('b', null, r.name), h('small', null, r.email)),
      r.company ? h('span', { class: `gm-pick-co ${r.kind === 'user' ? 'us' : ''}` }, r.company) : h('span', { class: 'gm-pick-co none' }, t('Firmasız')),
      h('span', { class: 'gm-pick-ok' }, ic('check')));
      return row;
    }) : h('div', { class: 'small muted gm-pick-empty' }, q.value.trim() ? t('Eşleşen kişi yok') : t('Rehberde e-postası olan kişi yok')));
  };
  q.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(search, 180); });
  modal({ title: t('Rehberden kişi ekle'), wide: true,
    body: h('div', { class: 'gm-pick' }, h('div', { class: 'gm-pick-top' }, q, tgt),
      h('div', { class: 'small muted' }, t('Yalnızca Rehber’de görebildiğiniz ve e-postası olan kişiler. Firma adıyla da arayabilirsiniz; dokunduğunuz kişi seçili alana eklenir.')), res),
    actions: [{ label: t('Tamam'), class: 'primary' }] });
  search();
  setTimeout(() => q.focus(), 50);
}

// Yeni mail › Evrak ekle: Evrak Yönetimi'nde görebildiğiniz evraklar; tümü ya da alıcıların firmasına etiketli olanlar
async function pickDocs({ recipients, picked, onPick }) {
  let comps = [];
  try { const em = recipients(); if (em.length) comps = await api.get(`/api/mail/people/companies?emails=${encodeURIComponent(em.join(','))}`); } catch { /* */ }
  let scope = comps.length ? 'company' : 'all', cid = comps[0]?.id || null;
  const chosen = new Map(picked.map(d => [d.id, d]));
  const q = h('input', { class: 'input', type: 'search', placeholder: t('Evrak adı ya da içeriğinde ara…'), autocomplete: 'off' });
  const coSel = h('select', { class: 'input gm-pick-cosel', hidden: scope !== 'company' || comps.length < 2, onchange: e => { cid = Number(e.target.value); search(); } },
    comps.map(c => h('option', { value: c.id }, c.name)));
  const res = h('div', { class: 'gm-pick-list' });
  const countEl = h('b');
  const syncCount = () => { countEl.textContent = chosen.size ? t('{n} evrak seçili', { n: chosen.size }) : ''; };
  const seg = segmented([['all', t('Tüm evraklar')], ['company', comps.length === 1 ? t('{c} evrakları', { c: comps[0].name }) : t('Seçili firmaya etiketli evraklar')]], scope, v => {
    if (v === 'company' && !comps.length) { toast(t('Alıcılar arasında bir firmaya bağlı kişi yok; önce firmadan bir kişi ekleyin'), 'err'); return; }
    scope = v; coSel.hidden = v !== 'company' || comps.length < 2; search();
  });
  let tm, seq = 0;
  const search = async () => {
    const my = ++seq;
    let r;
    try {
      r = await api.get(`/api/documents?limit=200&q=${encodeURIComponent(q.value.trim())}${scope === 'company' && cid ? `&company_id=${cid}` : ''}`);
    } catch (e) { clear(res, h('div', { class: 'small muted gm-pick-empty' }, e.status === 403 ? t('Evrak Yönetimi yetkiniz yok') : e.message)); return; }
    if (my !== seq) return;
    const docsL = r.documents || [];
    clear(res, docsL.length ? docsL.map(d => {
      const row = h('button', { type: 'button', class: `gm-pick-row ${chosen.has(d.id) ? 'on' : ''}`, onclick: () => {
        if (chosen.has(d.id)) chosen.delete(d.id); else chosen.set(d.id, d);
        row.classList.toggle('on', chosen.has(d.id)); syncCount();
      } },
      h('span', { class: 'gm-pick-ic' }, ic('doc')),
      h('span', { class: 'gm-pick-t' }, h('b', null, d.title || d.file_name), h('small', null, [d.file_name, d.doc_date || (d.uploaded_at || '').slice(0, 10), d.size ? size(d.size) : null].filter(Boolean).join(' · '))),
      (d.companies || []).length ? h('span', { class: 'gm-pick-co' }, d.companies.map(c => c.name).join(', ')) : null,
      h('span', { class: 'gm-pick-ok' }, ic('check')));
      return row;
    }) : h('div', { class: 'small muted gm-pick-empty' }, t('Bu ölçütlere uyan, görebildiğiniz evrak yok')));
  };
  q.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(search, 220); });
  modal({ title: t('Evraklardan ekle'), wide: true,
    body: h('div', { class: 'gm-pick' }, h('div', { class: 'gm-pick-top' }, seg, coSel), q,
      h('div', { class: 'gm-pick-info small muted' }, h('span', { class: 'grow' }, t('Yalnızca görme yetkiniz olan evraklar listelenir. Toplam ek sınırı 25 MB.')), countEl), res),
    actions: [{ label: t('Vazgeç') }, 'spacer', { label: t('Seçilenleri ekle'), class: 'primary', onClick: () => { onPick([...chosen.values()]); } }] });
  syncCount();
  search();
}

// Alıcılar: Gmail gibi çipler; virgül / Enter / boşlukla ayrılır, yazdıkça kişisel rehber + şirket önerisi
function chips(initial = [], onChange) {
  const list = (initial || []).filter(a => a?.email).map(a => ({ name: a.name && a.name !== a.email ? a.name : '', email: a.email }));
  const inp = h('input', { class: 'gm-chip-in', autocomplete: 'off', type: 'email', inputmode: 'email', 'aria-label': t('Alıcı') });
  const wrap = h('div', { class: 'gm-chips', onclick: e => { if (e.target === wrap) inp.focus(); } });
  const sug = h('div', { class: 'gm-sug', hidden: true });
  const valid = e => /^[^\s@<>,]+@[^\s@<>,]+\.[^\s@<>,]+$/.test(e);
  let ready = false;
  const draw = () => {
    clear(wrap, list.map((a, i) => h('span', { class: `gm-chip ${valid(a.email) ? '' : 'bad'}`, title: a.email },
      h('span', { class: 'gm-chip-av' }, letter(a)), h('span', null, a.name || a.email),
      h('button', { type: 'button', 'aria-label': t('Kaldır'), onclick: () => { list.splice(i, 1); draw(); inp.focus(); } }, ic('close')))), inp, sug);
    if (ready) onChange?.();
  };
  // Adres listesini böl: tırnak içindeki ya da <...> içindeki virgül bölmez ("Kaderoğlu, Muhammed" <m@x.com>)
  const split = s => {
    const out = []; let part = '', qd = false, ang = false;
    for (const c of s) {
      if (c === '"') qd = !qd; else if (c === '<' && !qd) ang = true; else if (c === '>' && !qd) ang = false;
      if (/[,;\n]/.test(c) && !qd && !ang) { out.push(part); part = ''; } else part += c;
    }
    out.push(part);
    return out.map(x => x.trim()).filter(Boolean);
  };
  const parse = s => {
    const m = s.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    return m ? { name: m[1].trim(), email: m[2].trim() } : { name: '', email: s.trim() };
  };
  const commit = () => {
    const parts = split(inp.value);
    if (!parts.length) return;
    parts.forEach(p => list.push(parse(p)));
    inp.value = ''; sug.hidden = true; draw(); inp.focus();
  };
  let timer, items = [], active = -1;
  const drawSug = () => {
    clear(sug, items.map((it, i) => h('button', { type: 'button', class: `gm-sug-i ${i === active ? 'on' : ''}`,
      onmousedown: e => { e.preventDefault(); list.push({ name: it.name && it.name !== it.email ? it.name : '', email: it.email }); inp.value = ''; sug.hidden = true; draw(); inp.focus(); } },
    h('span', { class: 'gm-chip-av' }, letter(it)), h('span', { class: 'gm-sug-t' }, h('b', null, it.name || it.email), h('small', null, it.email + (it.company ? ` · ${t('şirket')}` : ''))))));
    sug.hidden = !items.length;
  };
  inp.addEventListener('input', () => {
    if (/[,;]$/.test(inp.value) && !((inp.value.match(/"/g) || []).length % 2)) { commit(); return; }
    clearTimeout(timer);
    const q = inp.value.trim();
    if (q.length < 2) { sug.hidden = true; return; }
    timer = setTimeout(async () => { try { items = await api.get(`/api/mail/contacts/suggest?q=${encodeURIComponent(q)}`); active = -1; drawSug(); } catch { /* */ } }, 180);
  });
  inp.addEventListener('keydown', e => {
    if (!sug.hidden && ['ArrowDown', 'ArrowUp'].includes(e.key)) { active = Math.max(0, Math.min(items.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1))); drawSug(); e.preventDefault(); return; }
    if (e.key === ' ' && !valid(inp.value.trim())) return;   // boşluk yalnız tam bir adresten sonra kutucuk yapar ("Soyad, Ad" <...> yazılabilsin)
    if (e.key === 'Enter' || e.key === 'Tab' || e.key === ' ') {
      if (!sug.hidden && items.length && e.key !== ' ') { e.preventDefault(); const it = items[Math.max(0, active)]; list.push({ name: it.name && it.name !== it.email ? it.name : '', email: it.email }); inp.value = ''; sug.hidden = true; draw(); inp.focus(); return; }
      if (inp.value.trim() && (e.key !== 'Tab' || inp.value.includes('@'))) { e.preventDefault(); commit(); }
    } else if (e.key === 'Backspace' && !inp.value && list.length) { list.pop(); draw(); inp.focus(); }
    else if (e.key === 'Escape' && !sug.hidden) { sug.hidden = true; e.stopPropagation(); }
  });
  inp.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== inp) { if (inp.value.trim()) commit(); sug.hidden = true; } }, 150));
  inp.addEventListener('paste', e => { const txt = e.clipboardData?.getData('text') || ''; if (/[,;\n]/.test(txt)) { e.preventDefault(); inp.value = txt; commit(); } });
  draw(); ready = true;
  const fmt = a => (a.name ? `"${a.name.replace(/["\\]/g, '\\$&')}" <${a.email}>` : a.email);   // ad tırnaklı: virgüllü adlar bozulmaz
  return { el: h('div', { class: 'gm-chips-wrap' }, wrap),
    add: a => { if (a?.email && !list.some(x => x.email.toLowerCase() === a.email.toLowerCase())) { list.push({ name: a.name && a.name !== a.email ? a.name : '', email: a.email }); draw(); } },
    emails: () => list.map(a => a.email),
    invalid: () => [...list, ...(inp.value.trim() ? [parse(inp.value)] : [])].filter(a => !valid(a.email)).map(a => a.email), value: () => [...list, ...(inp.value.trim() ? [parse(inp.value)] : [])].map(fmt).join(', '), focus: () => inp.focus() };
}

// Uzak resimler açılınca: bu sitenin kendi adresine (ya da göreli adrese) giden kaynaklar atılır — okuma çerçevesi aynı kökenli
// olduğundan böyle bir istek oturum çerezini taşırdı. DOMParser belgesi etkisizdir (ayrıştırırken hiçbir şey yüklenmez).
function stripSelf(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const self = u => { try { return new URL(String(u).trim(), location.href).origin === location.origin; } catch { return false; } };
  doc.querySelectorAll('[src],[srcset],[background],[poster],link[href]').forEach(n => {
    for (const a of ['src', 'background', 'poster']) if (n.hasAttribute(a) && self(n.getAttribute(a))) n.removeAttribute(a);
    if (n.hasAttribute('srcset') && n.getAttribute('srcset').split(',').some(p => self(p.trim().split(/\s+/)[0]))) n.removeAttribute('srcset');
    if (n.tagName === 'LINK' && self(n.getAttribute('href'))) n.remove();
  });
  const css = s => s.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (m, _q, u) => (self(u) ? 'none' : m))
    .replace(/@import\s+(['"])([^'"]*)\1/gi, (m, _q, u) => (self(u) ? '' : m));
  doc.querySelectorAll('[style]').forEach(n => n.setAttribute('style', css(n.getAttribute('style'))));
  doc.querySelectorAll('style').forEach(n => { n.textContent = css(n.textContent); });
  return doc.head.innerHTML + doc.body.innerHTML;
}

// Alıntılanan HTML: betik / olay öznitelikleri / dış kaynaklar ayıklanır (yazma alanında çalışmasın)
// Yanıtlanan / iletilen / taslak HTML'i düzenleyiciye (contenteditable, innerHTML) girmeden önce izin listesiyle temizlenir
// (sanitize.js — Belge Yönetim ile aynı kural): betik, olay öznitelikleri, javascript:/data: bağlantılar ve uzak resimler atılır.
function sanitize(html) {
  return cleanHtml(html || '');
}
