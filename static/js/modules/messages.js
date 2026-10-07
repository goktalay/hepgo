// Mesajlar (WhatsApp-Web tarzı): solda sohbet listesi, sağda konuşma. Sesli arama sohbetin içinden başlatılır;
// görüşme bitince arama kaydı ve (kayıt varsa) konuşmacı bazlı transkript balonları dizide görünür — balona tıklayınca
// o anın sesi çalar. Mobilde tek panel (liste → sohbet, geri). Sohbet backend'i (api/chat) ve ses backend'i (api/voice) yeniden kullanılır.
import { api, fileUrl } from '../api.js';
import { icons } from '../icons.js';
import { playEvent } from '../sounds.js';
import { emojiPicker, groupForm, pushToTalk } from '../chat.js';
import * as voice from './voice.js';
import { avatar, clear, confirmDialog, fmtDateTime, h, matches, modal, svgIcon, t, toast, toastError } from '../ui.js';

let me = null, ctx = null;
const hm = iso => (iso || '').slice(11, 16);
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((b || 0) / 1024))} KB`);
const secs = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const mmss = s => `${String(Math.floor((s || 0) / 60)).padStart(2, '0')}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`;
const COMPANY_LOGO = '/static/img/logo-mark.png?v=3';
const keyOf = t => `${t.kind === 'group' ? 'g' : 'u'}${t.id}`;
const dayLabel = iso => {
  const d = (iso || '').slice(0, 10), t = new Date(), y = new Date(Date.now() - 864e5);
  const f = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return d === f(t) ? 'Bugün' : d === f(y) ? 'Dün' : `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
};
function convAvatar(t, sz = 'md') {
  if (t.kind === 'group') {
    if (t.is_company) return h('span', { class: `avatar ${sz} chat-logo`, title: 'Tüm Şirket' }, h('img', { src: COMPANY_LOGO, alt: '' }));
    return h('span', { class: `avatar ${sz} chat-grp` }, (t.name || '?').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr'));
  }
  return avatar(t, sz);
}
const rowName = r => (r.kind === 'group' ? r.name : r.full_name);
const preview = m => (!m ? '' : m.deleted_at ? '🚫 Bu mesaj silindi' : m.file_kind === 'audio' ? '🎤 Sesli mesaj' : m.file_kind === 'image' ? `🖼 ${m.body || 'Resim'}` : m.file_kind === 'file' ? `📎 ${m.file_name}` : m.call ? '📞 Sesli arama' : (m.body || ''));

let state = null;   // { view, listEl, convEl, conv, poll }

export async function render(view, params, context) {
  ctx = context; me = ctx.user;
  const sel = params[0] || '';
  if (state?.view === view && state.page) {
    // aynı sayfa; yalnızca seçimi değiştir
    openConversation(sel);
    return;
  }
  stop();
  const search = h('input', { class: 'input msg-search', type: 'search', placeholder: 'Sohbet ara…' });
  const listEl = h('div', { class: 'msg-rows' });
  const newBtn = h('button', { class: 'btn sm primary msg-new', type: 'button', title: 'Yeni sohbet', onclick: newChat }, svgIcon(icons.plus), 'Yeni');
  const groupBtn = h('button', { class: 'btn sm msg-new', type: 'button', title: 'Yeni grup', onclick: () => groupForm() }, 'Grup');
  const convEl = h('div', { class: 'msg-conv' });
  const page = h('div', { class: 'msg-page' },
    h('div', { class: 'msg-side' },
      h('div', { class: 'msg-side-head' }, h('b', null, 'Mesajlar'), h('div', { class: 'msg-side-btns pill-group' }, groupBtn, newBtn)),
      h('div', { class: 'msg-side-search' }, search), listEl),
    convEl);
  clear(view, page);
  state = { view, page, listEl, convEl, search, rows: [], conv: null };
  search.addEventListener('input', drawList);
  window.addEventListener('voice:callended', onCallEnded);
  await loadList();
  openConversation(sel);
  state.listTimer = setInterval(() => loadList().catch(() => {}), 8000);
}

export function stop() {
  if (!state) return;
  clearInterval(state.listTimer);
  window.removeEventListener('voice:callended', onCallEnded);
  if (state.conv) state.conv.destroy();
  state = null;
}

function onCallEnded() { loadList().catch(() => {}); if (state?.conv) state.conv.reloadCalls(); }

// ---------- Sol liste ----------
async function loadList() {
  if (!state) return;
  const [sum, calls] = await Promise.all([
    api.get('/api/chat/summary').catch(() => ({ items: [] })),
    api.get('/api/voice/calls').catch(() => []),
  ]);
  const byKey = new Map();
  for (const it of sum.items) byKey.set(keyOf(it), { ...it });
  // Sadece araması olan kişileri de listeye kat
  for (const c of calls) {
    if (c.kind !== 'bire_bir') continue;
    const other = (c.participants || []).find(p => p.user_id !== me.id);
    if (!other) continue;
    const k = `u${other.user_id}`;
    let row = byKey.get(k);
    if (!row) { row = { kind: 'user', id: other.user_id, full_name: other.full_name, photo: other.photo, unread: 0, created_at: null }; byKey.set(k, row); }
    if (!row.last_call || (c.started_at || '') > row.last_call) { row.last_call = c.started_at; row.last_call_status = c.status; }
    if (!row.created_at || (c.started_at || '') > row.created_at) { row.created_at = c.started_at; row.call = true; }
  }
  state.rows = [...byKey.values()].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
  state.rows.sort((a, b) => (b.unread || 0 ? 1 : 0) - (a.unread || 0 ? 1 : 0));
  drawList();
}

function drawList() {
  if (!state) return;
  const q = state.search.value.trim();
  const rows = state.rows.filter(r => matches(q, rowName(r)));
  const curKey = state.conv?.key;
  clear(state.listEl, rows.length ? rows.map(r => {
    const k = keyOf(r);
    const time = r.created_at ? (r.created_at.slice(0, 10) === new Date().toISOString().slice(0, 10) ? hm(r.created_at) : dayLabel(r.created_at)) : '';
    return h('button', { class: `msg-row ${k === curKey ? 'on' : ''}`, type: 'button', onclick: () => { location.hash = `#/messages/${k}`; } },
      h('span', { class: `msg-av ${r.kind === 'user' && r.online ? 'online' : ''}`, title: r.kind === 'user' && r.online ? 'Çevrimiçi' : null }, convAvatar(r, 'md')),
      h('div', { class: 'msg-row-mid' },
        h('div', { class: 'msg-row-top' }, h('b', null, rowName(r)), r.absence ? h('span', { class: `badge ${r.absence.kind === 'RAPOR' ? 'yellow' : 'blue'} msg-absent` }, r.absence.label) : null,
          h('span', { class: 'msg-row-time' }, time)),
        h('div', { class: 'msg-row-sub' },
          h('span', { class: 'msg-row-prev' }, r.call && !r.body ? '📞 Sesli arama' : (r.mine ? 'Siz: ' : '') + (preview(r) || '—')),
          r.unread ? h('span', { class: 'msg-unread' }, r.unread) : null)));
  }) : h('div', { class: 'msg-empty-list' }, q ? 'Sonuç yok' : 'Henüz sohbet yok. “Yeni” ile başlatın.'));
}

async function newChat() {
  let users;
  try { users = await api.get('/api/voice/users'); } catch (err) { return toastError(err); }
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara…' });
  const list = h('div', { class: 'msg-picklist' });
  const draw = () => clear(list, users.filter(u => matches(q.value, u.full_name)).map(u =>
    h('button', { class: 'msg-pick', type: 'button', onclick: () => { location.hash = `#/messages/u${u.id}`; } },   // hashchange modalı kapatır
      avatar(u, 'sm'), h('span', { class: 'grow' }, u.full_name), u.online ? h('span', { class: 'msg-online' }) : null)));
  q.addEventListener('input', draw); draw();
  modal({ title: 'Yeni Sohbet', body: h('div', null, q, list), actions: [{ label: 'Kapat' }] });
}

// ---------- Sağ: konuşma ----------
function openConversation(sel) {
  if (!state) return;
  if (state.conv?.key === sel) return;
  if (state.conv) { state.conv.destroy(); state.conv = null; }
  state.page.classList.toggle('show-conv', !!sel);
  if (!sel) { clear(state.convEl, h('div', { class: 'msg-placeholder' }, h('div', null, svgIcon(icons.chat), h('p', null, 'Bir sohbet seçin ya da yeni bir sohbet başlatın.')))); drawList(); return; }
  const kind = sel[0] === 'g' ? 'group' : 'user';
  const id = Number(sel.slice(1));
  if (!id) return;
  state.conv = conversation(state.convEl, { kind, id });
  drawList();
}

function conversation(container, target) {
  const group = target.kind === 'group';
  const base = group ? `/api/chat/g/${target.id}` : `/api/chat/${target.id}`;
  const conv = { key: keyOf({ kind: target.kind, id: target.id }), destroy, reloadCalls };
  let peer = { full_name: '…', online: false }, calls = [], msgs = [], lastId = 0, seen = 0, timer = null, audios = {};
  let seenUpto = 0, deliveredUpto = 0, typingNow = null, typingSentAt = 0;   // tikler ve "yazıyor…"
  let replyTo = null, lastSync = '', starOnly = false;   // yanıtlanan mesaj · değişiklik akışı · yalnız yıldızlılar
  const kindCode = group ? 'g' : 'd';
  const openCalls = new Set();   // açık kalan arama panelleri (rebuild'de kapanmasın)

  const backBtn = h('button', { class: 'msg-back', type: 'button', title: 'Geri', onclick: () => { location.hash = '#/messages'; } }, '←');
  const av = h('span');
  const nameEl = h('b'); const statusEl = h('span', { class: 'msg-conv-status' });
  const callBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Sesli ara', onclick: startCall }, svgIcon(icons.phone));
  const videoBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Görüntülü ara', onclick: startVideoCall }, svgIcon(icons.videocam));
  const starBtn = h('button', { class: 'icon-btn msg-starbtn', type: 'button', title: 'Yıldızlı mesajlar', onclick: () => {
    starOnly = !starOnly; starBtn.classList.toggle('on', starOnly); rebuild(true);
    if (starOnly && !msgs.some(m => m.starred)) toast('Bu sohbette yıldızlı mesaj yok');
  } }, '★');
  const head = h('div', { class: 'msg-conv-head' }, backBtn, av, h('div', { class: 'grow' }, nameEl, statusEl),
    h('div', { class: 'pill-group msg-head-pill' }, starBtn, group ? null : videoBtn, group ? null : callBtn));
  const timeline = h('div', { class: 'msg-timeline' });
  const input = h('textarea', { class: 'chat-input', rows: 1, placeholder: 'Mesaj yazın…' });
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const recBar = h('div', { class: 'chat-rec', hidden: true });
  const micBtn = h('button', { class: 'chat-mic', type: 'button', title: 'Bas-konuş' }, svgIcon(icons.mic));
  const sendBtn = h('button', { class: 'chat-send', type: 'button', title: 'Gönder' }, svgIcon(icons.send));
  const emojiBtn = h('button', { class: 'chat-emoji', type: 'button', title: 'Emoji' }, '😊');
  const bar = h('div', { class: 'chat-bar' },
    h('button', { class: 'chat-attach', type: 'button', title: 'Dosya / resim', onclick: () => fileIn.click() }, svgIcon(icons.paperclip)),
    emojiBtn, input, fileIn, micBtn, sendBtn);
  const replyBar = h('div', { class: 'msg-replybar', hidden: true });
  clear(container, head, timeline, recBar, replyBar, bar);
  function setReply(m) {
    replyTo = m;
    if (!m) { replyBar.hidden = true; clear(replyBar); return; }
    clear(replyBar,
      h('div', { class: 'msg-quote' }, h('b', null, m.from_id === me.id ? 'Siz' : (m.from_name || peer.full_name)), h('span', null, snippet(m))),
      h('button', { class: 'msg-reply-x', type: 'button', title: 'Yanıtı iptal et', onclick: () => setReply(null) }, '✕'));
    replyBar.hidden = false;
    input.focus({ preventScroll: true });
  }

  function startCall() {
    if (!peer.online) { toast(t('{name} çevrimiçi değil', { name: peer.full_name }), 'err'); return; }
    voice.startCall([target.id], { [target.id]: peer.full_name }, { [target.id]: peer.photo });
  }
  function startVideoCall() {
    if (!peer.online) { toast(t('{name} çevrimiçi değil', { name: peer.full_name }), 'err'); return; }
    voice.startCall([target.id], { [target.id]: peer.full_name }, { [target.id]: peer.photo }, { video: true });
  }

  function setPeer(p) {
    peer = p;
    clear(av, convAvatar(group ? p : { kind: 'user', ...p }, 'md'));
    nameEl.textContent = group ? p.name : p.full_name;
    if (group) { statusEl.textContent = p.is_company ? t('Şirket kanalı · {n} kişi', { n: p.member_count }) : t('{n} üye', { n: p.member_count }); input.disabled = !p.can_post; }
    else { statusEl.textContent = p.absence ? t('{label} · {date} tarihine kadar', { label: p.absence.label, date: p.absence.until.split('-').reverse().join('.') }) : p.online ? 'çevrimiçi' : p.last_seen ? t('son görülme {d}', { d: fmtDateTime(p.last_seen) }) : 'çevrimdışı'; statusEl.classList.toggle('on', p.online); callBtn.disabled = !p.online; callBtn.classList.toggle('dim', !p.online); videoBtn.disabled = !p.online; videoBtn.classList.toggle('dim', !p.online); }
  }

  // Zaman çizelgesi: mesajlar + arama kayıtları + transkript balonları (zamana göre)
  function rebuild(forceScroll) {
    // Yeniden kurmadan önce kullanıcının konumunu koru: alttaysa altta kalsın, yukarı kaydırmışsa yerinde kalsın.
    const atBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 60;
    const prevTop = timeline.scrollTop;
    const items = [];
    for (const m of msgs) if (!starOnly || m.starred) items.push({ at: m.created_at, sort: m.created_at, el: () => msgBubble(m) });
    if (!starOnly) for (const c of calls) items.push({ at: c.started_at, sort: c.started_at, el: () => callBlock(c) });
    items.sort((a, b) => (a.sort || '').localeCompare(b.sort || ''));
    clear(timeline, items.length ? [] : [h('div', { class: 'msg-empty-conv' }, 'Henüz mesaj yok. Yazın ya da 📞 ile arayın.')]);
    let day = null;
    for (const it of items) {
      const d = (it.at || '').slice(0, 10);
      if (d && d !== day) { timeline.append(h('div', { class: 'chat-day' }, dayLabel(it.at))); day = d; }
      timeline.append(it.el());
    }
    if (typingNow) timeline.append(typingBubble);
    if (forceScroll || atBottom) timeline.scrollTop = timeline.scrollHeight;
    else timeline.scrollTop = prevTop;
  }

  function msgBubble(m) {
    const mine = m.from_id === me.id;
    const url = m.file ? fileUrl(m.file) : null;
    const content = [];
    if (m.deleted) {
      const el = h('div', { class: `chat-msg ${mine ? 'mine' : ''}`, 'data-id': m.id },
        group && !mine ? h('span', { class: 'chat-mav' }, avatar({ full_name: m.from_name, photo: m.from_photo }, 'sm')) : null,
        h('div', { class: 'chat-bubble msg-deleted' }, group && !mine ? h('div', { class: 'chat-from' }, m.from_name) : null,
          h('div', { class: 'chat-text' }, '🚫 ', mine ? 'Bu mesajı sildiniz' : 'Bu mesaj silindi'), h('span', { class: 'chat-meta' }, hm(m.created_at))));
      attachMenu(el, m);
      return el;
    }
    if (m.forwarded) content.push(h('div', { class: 'msg-fwd' }, '↪ İletildi'));
    if (m.reply) content.push(h('button', { class: 'msg-quote in', type: 'button', onclick: e => { e.stopPropagation(); jumpTo(m.reply.id); } },
      h('b', null, m.reply.from_id === me.id ? 'Siz' : m.reply.from_name), h('span', null, m.reply.text)));
    if (m.file_kind === 'image') content.push(h('a', { href: url, target: '_blank', rel: 'noopener', class: 'chat-img' }, h('img', { src: fileUrl(m.file, 512), loading: 'lazy', alt: '' })));
    else if (m.file_kind === 'audio') content.push(h('div', { class: 'chat-audio' }, h('audio', { src: url, controls: true, preload: 'metadata' })));
    else if (m.file) content.push(h('a', { href: url, target: '_blank', rel: 'noopener', class: 'chat-file', download: m.file_name }, svgIcon(icons.paperclip), h('span', null, h('b', null, m.file_name), h('small', null, size(m.file_size)))));
    if (m.body) content.push(h('div', { class: 'chat-text' }, m.body));
    const el = h('div', { class: `chat-msg ${mine ? 'mine' : ''} ${mine && !group ? tickState(m.id) : ''} ${m.reactions?.length ? 'has-react' : ''}`, 'data-id': m.id },
      group && !mine ? h('span', { class: 'chat-mav' }, avatar({ full_name: m.from_name, photo: m.from_photo }, 'sm')) : null,
      h('div', { class: 'chat-bubble' }, group && !mine ? h('div', { class: 'chat-from' }, m.from_name) : null, ...content,
        h('button', { class: 'msg-menu-btn', type: 'button', title: 'Mesaj menüsü', 'aria-label': 'Mesaj menüsü', onclick: e => { e.stopPropagation(); openMenu(m, e.currentTarget); } }, '⌄'),
        h('span', { class: 'chat-meta' }, m.starred ? h('span', { class: 'msg-star' }, '★') : null, m.edited_at ? h('span', { class: 'msg-edited' }, 'düzenlendi') : null,
          hm(m.created_at), mine && !group ? tickIcon() : null),
        m.reactions?.length ? reactChips(m) : null));
    attachMenu(el, m);
    return el;
  }

  // ---------- Mesaj menüsü (sağ tık / basılı tut / ⌄) ----------
  const QUICK = ['👍', '❤️', '😂', '😮', '😢', '🙏'];
  const snippet = m => (m.deleted ? 'Bu mesaj silindi' : m.body ? m.body.slice(0, 140) : m.file_kind === 'image' ? '📷 Fotoğraf' : m.file_kind === 'audio' ? '🎤 Sesli mesaj' : `📎 ${m.file_name || 'Dosya'}`);
  const ageMin = m => (Date.now() - new Date(m.created_at).getTime()) / 60000;
  function attachMenu(el, m) {
    el.addEventListener('contextmenu', e => {
      if (e.target.closest('a, audio, video')) return;   // bağlantı / ses için tarayıcı menüsü kalsın
      e.preventDefault(); openMenu(m, null, e.clientX, e.clientY);
    });
    let t = null, sx = 0, sy = 0;
    el.addEventListener('touchstart', e => {
      const p = e.touches[0]; sx = p.clientX; sy = p.clientY;
      t = setTimeout(() => { t = null; navigator.vibrate?.(12); openMenu(m, null, sx, sy); }, 480);
    }, { passive: true });
    const cancel = () => { if (t) { clearTimeout(t); t = null; } };
    el.addEventListener('touchmove', e => { const p = e.touches[0]; if (Math.hypot(p.clientX - sx, p.clientY - sy) > 10) cancel(); }, { passive: true });
    el.addEventListener('touchend', cancel);
    el.addEventListener('touchcancel', cancel);
  }
  function reactChips(m) {
    const by = new Map();
    for (const r of m.reactions) { const x = by.get(r.emoji) || { n: 0, mine: false, names: [] }; x.n++; x.names.push(r.name); if (r.user_id === me.id) x.mine = true; by.set(r.emoji, x); }
    return h('div', { class: 'msg-reacts' }, [...by].map(([e, x]) =>
      h('button', { class: `msg-react ${x.mine ? 'mine' : ''}`, type: 'button', title: x.names.join(', '), onclick: ev => { ev.stopPropagation(); react(m, e); } },
        e, x.n > 1 ? h('small', null, x.n) : null)));
  }
  let menuEl = null;
  function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; document.removeEventListener('pointerdown', outside, true); } }
  function outside(e) { if (menuEl && !menuEl.contains(e.target)) closeMenu(); }
  function openMenu(m, anchor, x, y) {
    closeMenu();
    const mine = m.from_id === me.id;
    const item = (label, fn, cls = '') => h('button', { class: `msg-mi ${cls}`, type: 'button', onclick: () => { closeMenu(); fn(); } }, label);
    const items = m.deleted ? [item('🗑  Benden sil', () => delMsg(m, 'me'), 'danger')] : [
      item('↩  Yanıtla', () => setReply(m)),
      m.body ? item('⧉  Kopyala', () => copyText(m.body)) : null,
      item('↪  İlet', () => forwardModal([m])),
      item(m.starred ? '☆  Yıldızı kaldır' : '★  Yıldızla', () => toggleStar(m)),
      mine && m.body && !m.forwarded && ageMin(m) <= 15 ? item('✎  Düzenle', () => editMsg(m)) : null,
      mine ? item('ⓘ  Bilgi', () => infoModal(m)) : null,
      item('🗑  Sil', () => deleteModal(m), 'danger'),
    ];
    menuEl = h('div', { class: 'msg-menu', role: 'menu' },
      m.deleted ? null : h('div', { class: 'msg-quick' }, QUICK.map(e => h('button', { class: `msg-qe ${m.reactions?.some(r => r.user_id === me.id && r.emoji === e) ? 'on' : ''}`, type: 'button',
        onclick: () => { closeMenu(); react(m, e); } }, e)),
        h('button', { class: 'msg-qe more', type: 'button', title: 'Diğer emojiler', onclick: ev => { ev.stopPropagation(); moreEmoji(m); } }, '＋')),
      ...items.filter(Boolean));
    document.body.append(menuEl);
    const r = anchor ? anchor.getBoundingClientRect() : { left: x, right: x, top: y, bottom: y };
    const w = menuEl.offsetWidth, hgt = menuEl.offsetHeight;
    const left = Math.min(Math.max(8, (mine ? r.right - w : r.left)), innerWidth - w - 8);
    const top = r.bottom + 6 + hgt > innerHeight - 8 ? Math.max(8, r.top - hgt - 6) : r.bottom + 6;
    Object.assign(menuEl.style, { left: `${left}px`, top: `${top}px` });
    setTimeout(() => document.addEventListener('pointerdown', outside, true));
  }
  function moreEmoji(m) {
    const all = ['👍', '👎', '❤️', '🔥', '👏', '🎉', '😂', '😊', '😍', '😮', '😢', '😡', '🙏', '💯', '✅', '❌', '👀', '🤝', '💪', '🚀', '⚠️', '🙌', '😅', '🤔'];
    const box = menuEl.querySelector('.msg-quick');
    clear(box, all.map(e => h('button', { class: 'msg-qe', type: 'button', onclick: () => { closeMenu(); react(m, e); } }, e)));
    box.classList.add('all');
  }
  const replace = d => { const i = msgs.findIndex(x => x.id === d.id); if (i >= 0) msgs[i] = { ...msgs[i], ...d }; rebuild(); };
  async function react(m, emoji) {
    try { replace(await api.post(`/api/chat/msg/${kindCode}/${m.id}/react`, { emoji })); } catch (err) { toastError(err); }
  }
  async function toggleStar(m) {
    try { const r = await api.post(`/api/chat/msg/${kindCode}/${m.id}/star`, {}); replace({ id: m.id, starred: r.starred }); toast(r.starred ? 'Yıldızlandı' : 'Yıldız kaldırıldı'); }
    catch (err) { toastError(err); }
  }
  function copyText(t) {
    (navigator.clipboard?.writeText(t) || Promise.reject()).then(() => toast('Kopyalandı'), () => {
      const ta = h('textarea', { style: { position: 'fixed', opacity: '0' } }, t); document.body.append(ta); ta.select();
      try { document.execCommand('copy'); toast('Kopyalandı'); } catch { toast('Kopyalanamadı', 'err'); } ta.remove();
    });
  }
  function jumpTo(id) {
    const el = timeline.querySelector(`.chat-msg[data-id="${id}"]`);
    if (!el) { toast('Bu mesaj sohbetin eski kısmında'); return; }
    const tr = timeline.getBoundingClientRect(), r = el.getBoundingClientRect();   // yalnızca sohbet akışı kayar (iskelet değil)
    timeline.scrollTo({ top: timeline.scrollTop + r.top - tr.top - timeline.clientHeight / 2 + r.height / 2, behavior: 'smooth' });
    el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400);
  }
  function editMsg(m) {
    const ta = h('textarea', { class: 'input', rows: 3 }, m.body);
    modal({ title: 'Mesajı düzenle', body: h('div', null, ta, h('p', { class: 'small muted' }, 'Mesajlar gönderildikten sonraki 15 dakika içinde düzenlenebilir.')),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: async () => {
        replace(await api.put(`/api/chat/msg/${kindCode}/${m.id}`, { body: ta.value })); toast('Mesaj düzenlendi');
      } }] });
    setTimeout(() => { ta.focus({ preventScroll: true }); ta.setSelectionRange(ta.value.length, ta.value.length); }, 50);
  }
  async function delMsg(m, scope) {
    try {
      await api.del(`/api/chat/msg/${kindCode}/${m.id}?scope=${scope}`);
      if (scope === 'me') { msgs = msgs.filter(x => x.id !== m.id); rebuild(); } else replace({ id: m.id, deleted: true, body: null, file: null, reactions: [], reply: null });
      if (replyTo?.id === m.id) setReply(null);
    } catch (err) { toastError(err); }
  }
  function deleteModal(m) {
    const canAll = m.from_id === me.id && !m.deleted && ageMin(m) <= 48 * 60;
    modal({ title: 'Mesaj silinsin mi?', body: h('p', null, canAll ? 'Herkesten silerseniz sohbetteki herkes için “Bu mesaj silindi” görünür.' : 'Mesaj yalnızca sizin ekranınızdan kaldırılır.'),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'Benden sil', class: canAll ? '' : 'danger', onClick: () => delMsg(m, 'me') },
        canAll ? { label: 'Herkesten sil', class: 'danger', onClick: () => delMsg(m, 'all') } : null].filter(Boolean) });
  }
  async function infoModal(m) {
    let d; try { d = await api.get(`/api/chat/msg/${kindCode}/${m.id}/info`); } catch (err) { return toastError(err); }
    const when = v => (v ? fmtDateTime(v) : '—');
    const row = (ic, label, v) => h('div', { class: 'msg-info-row' }, h('span', { class: 'msg-info-ic' }, ic), h('div', null, h('b', null, label), h('small', null, v)));
    const people = (title, list) => list?.length ? [h('div', { class: 'msg-info-sec' }, `${title} (${list.length})`),
      h('div', { class: 'msg-info-people' }, list.map(p => h('span', null, avatar(p, 'sm'), p.full_name)))] : [];
    modal({ title: 'Mesaj bilgisi', body: h('div', { class: 'msg-info' },
      h('div', { class: 'msg-info-quote' }, snippet(m)),
      row('🕓', 'Gönderildi', when(d.created_at)),
      d.edited_at ? row('✎', 'Düzenlendi', when(d.edited_at)) : null,
      group ? null : row('✓✓', 'İletildi', d.hidden_receipts && !d.delivered_at ? 'Gizlilik ayarı nedeniyle görünmüyor' : when(d.delivered_at)),
      group ? null : row('👁', 'Okundu', d.hidden_receipts ? 'Gizlilik ayarı nedeniyle görünmüyor' : when(d.read_at)),
      ...(group ? [...people('Okuyanlar', d.read), ...people('Henüz okumayanlar', d.unread)] : [])),
      actions: [{ label: 'Kapat' }] });
  }

  // İlet: kişiler ve gruplar arasından çoklu seçim
  async function forwardModal(items) {
    let users = [], convs = [];
    try { [users, convs] = await Promise.all([api.get('/api/voice/users'), api.get('/api/chat/summary').then(s => s.items)]); } catch (err) { return toastError(err); }
    const groups = convs.filter(c => c.kind === 'group');
    const recent = convs.filter(c => c.kind === 'user').map(c => c.id);
    users.sort((a, b) => (recent.indexOf(a.id) < 0 ? 999 : recent.indexOf(a.id)) - (recent.indexOf(b.id) < 0 ? 999 : recent.indexOf(b.id)) || a.full_name.localeCompare(b.full_name, 'tr'));
    const pickU = new Set(), pickG = new Set();
    const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ya da grup ara…' });
    const list = h('div', { class: 'msg-picklist fwd' });
    const chosen = h('div', { class: 'msg-fwd-chosen small muted' });
    const sendBtnRef = {};
    const upd = () => {
      const n = pickU.size + pickG.size;
      chosen.textContent = n ? t('{n} alıcı seçildi', { n }) : 'Alıcı seçin';
      if (sendBtnRef.el) sendBtnRef.el.disabled = !n;
    };
    const row = (key, set, id, av, name, sub) => {
      const cb = h('input', { type: 'checkbox', checked: set.has(id), onchange: e => { e.target.checked ? set.add(id) : set.delete(id); upd(); } });
      return h('label', { class: 'msg-pick' }, cb, av, h('span', { class: 'grow' }, name, sub ? h('small', { class: 'muted' }, ` · ${sub}`) : null));
    };
    const draw = () => clear(list,
      ...groups.filter(g => g.kind === 'group' && matches(q.value, g.name)).map(g => row('g', pickG, g.id, convAvatar(g, 'sm'), g.name, g.is_company ? 'Şirket kanalı' : 'Grup')),
      ...users.filter(u => u.id !== me.id && matches(q.value, u.full_name)).map(u => row('u', pickU, u.id, avatar(u, 'sm'), u.full_name, recent.includes(u.id) ? 'son sohbet' : '')));
    q.addEventListener('input', draw); draw(); upd();
    const dlg = modal({ title: items.length > 1 ? t('{n} mesajı ilet', { n: items.length }) : 'Mesajı ilet', body: h('div', { class: 'msg-fwd' },
      h('div', { class: 'msg-info-quote' }, items.length > 1 ? t('{n} mesaj', { n: items.length }) : snippet(items[0])), q, list, chosen),
      actions: ['spacer', { label: 'Vazgeç' }, { label: 'İlet', class: 'primary', onClick: async () => {
        if (!pickU.size && !pickG.size) { toast('Alıcı seçin', 'err'); return true; }
        const r = await api.post('/api/chat/forward', { items: items.map(m => ({ kind: kindCode, id: m.id })), users: [...pickU], groups: [...pickG] });
        toast(r.skipped?.length ? t('{n} alıcıya iletildi · gönderilemedi: {who}', { n: r.sent, who: r.skipped.join(', ') }) : t('{n} alıcıya iletildi', { n: r.sent }), r.skipped?.length ? '' : 'success');
        loadList().catch(() => {});
        if (pickU.has(target.id) && !group || pickG.has(target.id) && group) poll();
      } }] });
    sendBtnRef.el = dlg?.el?.querySelector('.modal-foot .btn.primary');
    upd();
  }

  // WhatsApp tarzı tikler: ✓ gönderildi · ✓✓ iletildi · mavi ✓✓ okundu
  function tickState(id) { return id <= seenUpto ? 't-read' : id <= Math.max(deliveredUpto, seenUpto) ? 't-deliv' : 't-sent'; }
  function tickIcon() {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 18 12'); s.setAttribute('class', 'msg-tick');
    s.innerHTML = '<path class="t1" d="M1.5 6.5l3.3 3.3L11.5 2.5"/><path class="t2" d="M7.6 9.6l.2.2L15.5 2.5"/>';
    return s;
  }
  function updateTicks() {
    for (const el of timeline.querySelectorAll('.chat-msg.mine[data-id]')) {
      el.classList.remove('t-read', 't-deliv', 't-sent'); el.classList.add(tickState(Number(el.dataset.id)));
    }
  }
  // "Yazıyor…": başlıkta durum + sohbetin altında üç noktalı balon
  const typingBubble = h('div', { class: 'chat-msg msg-typing' }, h('div', { class: 'chat-bubble' }, h('span', { class: 'msg-typing-who' }), h('span', { class: 'msg-dots' }, h('i'), h('i'), h('i'))));
  function applyTyping(tp) {
    const who = group ? (tp && tp.length ? tp : null) : (tp ? [peer.full_name] : null);
    const changed = JSON.stringify(who) !== JSON.stringify(typingNow);
    typingNow = who;
    if (who) {
      statusEl.textContent = group ? t('{who} yazıyor…', { who: who.map(n => n.split(' ')[0]).join(', ') }) : 'yazıyor…';
      statusEl.classList.add('typing');
      typingBubble.querySelector('.msg-typing-who').textContent = group ? `${who.map(n => n.split(' ')[0]).join(', ')}` : '';
    } else statusEl.classList.remove('typing');
    if (!changed) return;
    const atBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 80;
    if (who) timeline.append(typingBubble); else typingBubble.remove();
    if (atBottom) timeline.scrollTop = timeline.scrollHeight;
  }

  // Arama kaydı: tek satır özet + (kayıt varsa) altında AÇILIR panel (transkript + kayıt) — sohbeti doldurmaz.
  function callBlock(c) {
    const mine = c.initiator_id === me.id;
    const st = c.status === 'BITTI' ? 'Görüşüldü' : c.status === 'KACIRILDI' ? (mine ? 'Cevapsız' : 'Cevapsız arama') : c.status;
    const dur = c.seconds ? ` · ${secs(c.seconds)}` : '';
    const hasText = c.recorded && c.segments?.length;
    const processing = c.recorded && c.process_status !== 'TAMAM' && c.process_status !== 'HATA';
    const failed = c.recorded && c.process_status === 'HATA';
    const tag = !c.recorded ? null
      : hasText ? t('🎧 {n} konuşma · aç', { n: c.segments.length }) : processing ? '🎧 işleniyor…' : failed ? 'kayıt hatası' : '🎧 kayıt · aç';
    const panel = h('div', { class: 'msg-call-panel', hidden: true });
    let built = false;
    const buildPanel = () => {
      built = true;
      if (hasText) {
        // Her katılımcının kaydı ayrı dosya (audio_id); her segment kendi dosyasında o ana gider.
        const audioFor = aid => {
          const key = `${c.id}:${aid || 0}`;
          return audios[key] || (audios[key] = h('audio', { src: `/api/voice/calls/${c.id}/audio${aid ? `?aid=${aid}` : ''}`, preload: 'metadata' }));
        };
        const seek = (aid, t) => {
          const audio = audioFor(aid);
          for (const k in audios) if (audios[k] !== audio) audios[k].pause();   // diğer dosyaları durdur
          const go = () => { try { audio.currentTime = t; } catch { /* */ } audio.play().catch(() => {}); };
          if (audio.readyState >= 1) go();
          else { audio.addEventListener('loadedmetadata', go, { once: true }); try { audio.load(); } catch { /* */ } }
        };
        clear(panel, h('div', { class: 'msg-tr-head' }, '🎧 Kaydı dinlemek için bir satıra dokunun'),
          ...c.segments.map(s => h('div', { class: `chat-msg ${s.speaker_user === me.id ? 'mine' : ''}` },
            h('div', { class: 'chat-bubble tr-bubble', onclick: () => seek(s.audio_id, s.t0), title: 'Bu anı dinle' },
              h('div', { class: `tr-who ${s.speaker_user ? '' : 'unknown'}` }, s.speaker_label || 'Konuşmacı'),
              h('div', { class: 'chat-text' }, s.text), h('span', { class: 'chat-meta' }, mmss(s.t0), ' ▶')))));
      } else if (failed) {
        clear(panel, h('div', { class: 'msg-tr-note err' }, t('Kayıt işlenemedi: {err}', { err: c.process_error || 'bilinmeyen hata' })));
      } else if (c.process_status === 'TAMAM') {
        const audio = audios[c.id] || (audios[c.id] = h('audio', { class: 'msg-tr-audio', src: `/api/voice/calls/${c.id}/audio`, controls: true, preload: 'none' }));
        clear(panel, h('div', { class: 'msg-tr-head' }, 'Anlaşılır konuşma bulunamadı — kaydı dinleyebilirsiniz'), audio);
      } else {
        clear(panel, callStages(c));   // yükleme + metne çevirme aşamaları
      }
    };
    const apply = open => { if (open && !built) buildPanel(); panel.hidden = !open; log.classList.toggle('open', open); };
    const toggle = () => { if (!c.recorded) return; const open = panel.hidden; openCalls[open ? 'add' : 'delete'](c.id); apply(open); };
    const log = h('div', { class: `msg-callog ${c.recorded ? 'clickable' : ''}`, onclick: toggle },
      h('span', { class: 'msg-callog-ic' }, svgIcon(icons.phone)),
      h('span', { class: 'grow' }, h('b', null, t('{dir} arama', { dir: mine ? 'Giden' : 'Gelen' })), h('small', null, `${st}${dur} · ${hm(c.started_at)}`)),
      tag ? h('span', { class: `msg-callog-tag ${processing ? 'proc' : ''}` }, tag) : null,
      c.recorded ? h('span', { class: 'msg-callog-chev' }, '▾') : null);
    if (c.recorded && openCalls.has(c.id)) apply(true);   // rebuild sonrası açık kalsın
    return h('div', { class: 'msg-call' }, log, panel);
  }

  // Kayıt işleme aşamaları: yükleme + metne çevirme, her aktif adımda ilerleme çubuğu
  function callStages(c) {
    const uploaded = c.has_audio;
    const s1 = uploaded ? 'done' : 'active';
    const s2 = uploaded ? 'active' : 'wait';
    const step = (label, state) => h('div', { class: `msg-step ${state}` },
      h('span', { class: 'msg-step-ic' }, state === 'done' ? '✓' : state === 'active' ? h('span', { class: 'msg-spin' }) : '○'),
      h('div', { class: 'msg-step-body' }, h('span', null, label), state === 'active' ? h('div', { class: 'msg-prog' }, h('i')) : null));
    return h('div', { class: 'msg-stages' },
      h('div', { class: 'msg-tr-head' }, '🎧 Görüşme kaydı işleniyor'),
      step('Kayıt yükleniyor', s1),
      step('Metne çevriliyor, kişilere ayrılıyor', s2));
  }

  // Gönderme
  async function send(fd, label) {
    fd.append('body', fd.get('body') ?? '');
    if (replyTo) { fd.append('reply_to', String(replyTo.id)); setReply(null); }
    const tmp = h('div', { class: 'chat-msg mine' }, h('div', { class: 'chat-bubble' }, h('div', { class: 'chat-text' }, label), h('span', { class: 'chat-meta' }, 'gönderiliyor…')));
    timeline.append(tmp); timeline.scrollTop = timeline.scrollHeight;
    try { const m = await api.post(base, fd); tmp.remove(); msgs.push(m); lastId = Math.max(lastId, m.id); rebuild(true); }
    catch (err) { tmp.remove(); toastError(err); }
  }
  const sendText = () => { const t = input.value.trim(); if (!t) return; input.value = ''; autosize(); const fd = new FormData(); fd.append('body', t); send(fd, t); };
  const sendFiles = files => { for (const f of files) { if (f.size > 25 * 1024 * 1024) { toast(t('{name}: 25 MB üstü', { name: f.name }), 'err'); continue; } const fd = new FormData(); fd.append('file', f); send(fd, `📎 ${f.name}`); } };
  const autosize = () => { input.style.height = 'auto'; input.style.height = `${Math.min(120, input.scrollHeight)}px`; };
  input.addEventListener('input', autosize);
  input.addEventListener('input', () => {   // karşı tarafa "yazıyor…" (en fazla ~2,5 sn'de bir)
    if (!input.value.trim() || Date.now() - typingSentAt < 2500) return;
    typingSentAt = Date.now();
    api.post(`${base}/typing`, {}).catch(() => {});
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendText(); } });
  sendBtn.addEventListener('click', sendText);
  emojiBtn.addEventListener('click', e => { e.stopPropagation(); emojiPicker(container, input, autosize); });
  fileIn.addEventListener('change', () => { sendFiles([...fileIn.files]); fileIn.value = ''; });
  pushToTalk(micBtn, recBar, (blob, dur, ext) => { const fd = new FormData(); fd.append('file', new File([blob], `ses-${Date.now()}${ext}`, { type: blob.type })); fd.append('duration', String(dur)); send(fd, `🎤 Sesli mesaj`); });

  async function reloadCalls() {
    if (group) return;
    try { calls = await api.get(`/api/voice/with/${target.id}`); rebuild(); } catch { /* */ }
  }
  async function poll() {
    if (state?.conv !== conv || document.hidden) return;
    try {
      const d = await api.get(`${base}?after=${lastId}${lastSync ? `&since=${encodeURIComponent(lastSync)}` : ''}`);
      if (state?.conv !== conv) return;
      setPeer(group ? d.group : d.peer);
      if (d.sync) lastSync = d.sync;
      if (d.updates?.length) { for (const u of d.updates) { const i = msgs.findIndex(x => x.id === u.id); if (i >= 0) msgs[i] = u; } rebuild(); }
      if (d.items.length) { for (const m of d.items) { if (!msgs.some(x => x.id === m.id)) { msgs.push(m); lastId = Math.max(lastId, m.id); } } if (d.items.some(m => m.from_id !== me.id)) { playEvent('message'); typingNow = null; } rebuild(); }
      if (!group && (d.seen_upto !== seenUpto || d.delivered_upto !== deliveredUpto)) { seenUpto = d.seen_upto || 0; deliveredUpto = d.delivered_upto || 0; updateTicks(); }
      applyTyping(d.typing);
      // Kayıt işlenirken çağrıları tazele (aşamalar → transkript güncellensin)
      if (!group && calls.some(c => c.recorded && c.process_status !== 'TAMAM' && c.process_status !== 'HATA')) reloadCalls();
    } catch { /* */ }
  }

  (async () => {
    try {
      const [d, cl] = await Promise.all([api.get(base), group ? Promise.resolve([]) : api.get(`/api/voice/with/${target.id}`).catch(() => [])]);
      if (state?.conv !== conv) return;
      setPeer(group ? d.group : d.peer);
      msgs = d.items || []; calls = cl || []; lastSync = d.sync || '';
      seenUpto = d.seen_upto || 0; deliveredUpto = d.delivered_upto || 0;
      lastId = msgs.reduce((a, m) => Math.max(a, m.id), 0);
      rebuild(true);
      applyTyping(d.typing);
      timer = setInterval(poll, 1500);
    } catch (err) { toastError(err); }
  })();

  function destroy() { clearInterval(timer); closeMenu(); }
  return conv;
}
