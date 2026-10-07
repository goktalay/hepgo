// Canlı mesajlaşma (birebir ve grup): sağ altta açılan sohbet penceresi ve başlıktaki mesaj düğmesi.
// Gruplar: kullanıcı grup kurar, üyeleri ekler; "Tüm Şirket" kanalına (şirket logolu) herkes üyedir, yalnızca Sistem Yöneticisi yazar.
// Pencere açıkken yeni mesajlar 2 sn'de bir çekilir. Metin, dosya / resim (sürükle-bırak ya da ataç) ve bas-konuş ses
// kaydı gönderilebilir: mikrofon düğmesine basılı tutulur, bırakınca gider (yukarı kaydırıp bırakınca iptal).
// Başlıktaki düğme okunmamış mesajları gönderene göre gruplar; sayı, okunmamış mesajı olan kişi sayısıdır.
import { api, fileUrl } from './api.js';
import { icons } from './icons.js';
import { desktopNotify, flashMs, flashOn } from './prefs.js';
import { playEvent } from './sounds.js';
import { avatar, clear, confirmDialog, field, fmtDateTime, h, matches, modal, peoplePicker, svgIcon, toast, toastError } from './ui.js';

let me = null;
let win = null;          // açık sohbet: { uid, el, timer, ... }
let refreshSummary = () => {};
let _summary = { people: 0, unread: 0 };   // son okunmamış özeti (Kişisel panelindeki Mesajlar rozeti için)
export const chatSummary = () => _summary;
export const setChatUser = u => { me = u; };

const hm = iso => iso.slice(11, 16);
const dayLabel = iso => {
  const d = iso.slice(0, 10), t = new Date(), y = new Date(Date.now() - 864e5);
  const f = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return d === f(t) ? 'Bugün' : d === f(y) ? 'Dün' : `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
};
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((b || 0) / 1024))} KB`);
const secs = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// Sohbet hedefi: kişi { kind: 'user', id, full_name, photo } ya da grup { kind: 'group', id, name, is_company }
const keyOf = t => `${t.kind === 'group' ? 'g' : 'u'}:${t.id}`;
const titleOf = t => (t.kind === 'group' ? t.name : t.full_name);
const COMPANY_LOGO = '/static/img/logo-mark.png?v=3';
function convAvatar(t, size = 'sm') {
  if (t.kind !== 'group') return avatar(t, size);
  if (t.is_company) return h('span', { class: `avatar ${size} chat-logo`, title: 'Tüm Şirket' }, h('img', { src: COMPANY_LOGO, alt: '' }));
  return h('span', { class: `avatar ${size} chat-grp` }, (t.name || '?').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr'));
}
const preview = m => (m.file_kind === 'audio' ? '🎤 Sesli mesaj' : m.file_kind === 'image' ? `🖼 ${m.body || 'Resim'}` : m.file_kind === 'file' ? `📎 ${m.file_name}` : m.body || '');

// ---------- Sohbet penceresi
// Not: sohbet artık tam sayfa (WhatsApp-Web) Mesajlar ekranında açılır. openChat oraya yönlendirir.
export function openChat(target) {
  const user = target?.kind ? target : { ...target, kind: 'user' };
  const group = user.kind === 'group';
  if (!user?.id || (!group && user.id === me?.id)) return;
  location.hash = `#/messages/${group ? 'g' : 'u'}${user.id}`;
}
async function openChatWindow(target) {   // (eski açılır pencere — kullanılmıyor)
  const user = target?.kind ? target : { ...target, kind: 'user' };
  const group = user.kind === 'group';
  if (!user?.id || (!group && user.id === me?.id)) return;
  if (win?.key === keyOf(user)) { win.input.focus(); return; }
  closeChat();
  const base = group ? `/api/chat/g/${user.id}` : `/api/chat/${user.id}`;
  const list = h('div', { class: 'chat-list' });
  const input = h('textarea', { class: 'chat-input', rows: 1, placeholder: 'Mesaj yazın…', 'data-no-mic': '' });
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const status = h('span', { class: 'chat-status' });
  const recBar = h('div', { class: 'chat-rec', hidden: true });
  const micBtn = h('button', { class: 'chat-mic', type: 'button', title: 'Bas-konuş: basılı tutun, bırakınca gönderilir' }, svgIcon(icons.mic));
  const sendBtn = h('button', { class: 'chat-send', type: 'button', title: 'Gönder (Enter)' }, svgIcon(icons.send));
  const emojiBtn = h('button', { class: 'chat-emoji', type: 'button', title: 'Emoji' }, '😊');
  const head = h('div', { class: 'chat-head' },
    convAvatar(user, 'sm'), h('div', { class: 'grow' }, h('b', null, titleOf(user)), status),
    group ? h('button', { class: 'chat-x', type: 'button', title: 'Grup bilgisi', onclick: () => groupInfo(user.id) }, '⋯') : null,
    h('button', { class: 'chat-x', type: 'button', title: 'Kapat', onclick: () => closeChat() }, '×'));
  const el = h('div', { class: `chat-win ${group ? 'group' : ''}`, role: 'dialog', 'aria-label': `${titleOf(user)} ile mesajlaşma` }, head, list, recBar,
    h('div', { class: 'chat-bar' },
      h('button', { class: 'chat-attach', type: 'button', title: 'Dosya ya da resim gönder', onclick: () => fileIn.click() }, svgIcon(icons.paperclip)),
      emojiBtn, input, fileIn, micBtn, sendBtn));
  document.body.append(el);
  const w = win = { key: keyOf(user), el, input, last: 0, first: 0, seen: 0, timer: null, lastDay: null };

  const bubble = m => {
    const mine = m.from_id === me.id;
    const url = m.file ? fileUrl(m.file) : null;
    const content = [];
    if (m.file_kind === 'image') content.push(h('a', { href: url, target: '_blank', rel: 'noopener', class: 'chat-img' }, h('img', { src: fileUrl(m.file, 512), alt: m.file_name || '', loading: 'lazy' })));
    else if (m.file_kind === 'audio') content.push(h('div', { class: 'chat-audio' }, h('audio', { src: url, controls: true, preload: 'metadata' }),
      m.duration ? h('small', null, secs(m.duration)) : null));
    else if (m.file) content.push(h('a', { href: url, target: '_blank', rel: 'noopener', class: 'chat-file', download: m.file_name },
      svgIcon(icons.paperclip), h('span', null, h('b', null, m.file_name), h('small', null, size(m.file_size)))));
    if (m.body) content.push(h('div', { class: 'chat-text' }, m.body));
    return h('div', { class: `chat-msg ${mine ? 'mine' : ''}`, 'data-id': m.id },
      group && !mine ? h('span', { class: 'chat-mav', title: m.from_name }, avatar({ full_name: m.from_name, photo: m.from_photo }, 'sm')) : null,
      h('div', { class: 'chat-bubble' }, group && !mine ? h('div', { class: 'chat-from' }, m.from_name) : null, content,
        h('span', { class: 'chat-meta' }, hm(m.created_at), mine && !group ? h('span', { class: 'chat-tick' }, '✓') : null)));
  };
  const markSeen = () => list.querySelectorAll('.chat-msg.mine').forEach(n => n.classList.toggle('seen', Number(n.dataset.id) <= w.seen));
  const append = items => {
    if (items.length) list.querySelector('.chat-empty')?.remove();
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    for (const m of items) {
      if (list.querySelector(`[data-id="${m.id}"]`)) continue;
      const d = m.created_at.slice(0, 10);
      if (d !== w.lastDay) { list.append(h('div', { class: 'chat-day' }, dayLabel(m.created_at))); w.lastDay = d; }
      list.append(bubble(m));
      w.last = Math.max(w.last, m.id);
    }
    if (atBottom || items.some(m => m.from_id === me.id)) list.scrollTop = list.scrollHeight;
  };
  const setGroup = g => {   // grup: üye sayısı; Tüm Şirket'e yalnızca Sistem Yöneticisi yazar
    el.classList.toggle('closed', !g.can_post);
    input.disabled = !g.can_post;
    input.placeholder = g.can_post ? (g.is_company ? 'Tüm şirkete duyuru yazın…' : 'Gruba mesaj yazın…') : 'Bu kanala yalnızca Sistem Yöneticisi yazabilir';
    status.textContent = g.is_company ? `Şirket kanalı · ${g.member_count} kişi` : `${g.member_count} üye · ${g.members.slice(0, 4).map(m => m.full_name.split(' ')[0]).join(', ')}${g.member_count > 4 ? '…' : ''}`;
  };
  const setPeer = p => {
    if (group) return setGroup(p);
    el.classList.toggle('closed', !!p.no_messages);
    input.disabled = !!p.no_messages;
    input.placeholder = p.no_messages ? `${p.full_name} mesaj almayı kapatmış` : 'Mesaj yazın…';
    status.textContent = p.online ? 'çevrimiçi' : p.last_seen ? `son görülme ${fmtDateTime(p.last_seen)}` : 'çevrimdışı';
    status.classList.toggle('on', p.online);
  };
  const poll = async () => {
    if (win !== w || document.hidden) return;
    try {
      const d = await api.get(`${base}?after=${w.last}`);
      if (win !== w) return;
      setPeer(group ? d.group : d.peer);
      if (d.items.length) {
        append(d.items);
        if (d.items.some(m => m.from_id !== me.id)) { playEvent('message'); refreshSummary(); }   // açık sohbette de sesle haber ver
      }
      if (!group && d.seen_upto !== w.seen) { w.seen = d.seen_upto; markSeen(); }
    } catch { /* bağlantı koparsa bir sonraki turda denenir */ }
  };
  // Eski mesajlar: listenin en üstüne kaydırınca
  const loadOlder = async () => {
    if (!w.more || w.loading) return;
    w.loading = true;
    try {
      const d = await api.get(`${base}?before=${w.first}`);
      const h0 = list.scrollHeight;
      const frag = document.createDocumentFragment();
      let day = null;
      for (const m of d.items) {
        const dd = m.created_at.slice(0, 10);
        if (dd !== day) { frag.append(h('div', { class: 'chat-day' }, dayLabel(m.created_at))); day = dd; }
        frag.append(bubble(m));
      }
      const firstDay = list.querySelector('.chat-day');
      if (firstDay && firstDay.textContent === (d.items.length ? dayLabel(d.items[d.items.length - 1].created_at) : '')) firstDay.remove();
      list.prepend(frag);
      list.scrollTop += list.scrollHeight - h0;
      if (d.items.length) w.first = d.items[0].id;
      w.more = d.more;
      markSeen();
    } catch { /* yok say */ } finally { w.loading = false; }
  };
  list.addEventListener('scroll', () => { if (list.scrollTop < 40) loadOlder(); });

  // Gönderme
  const send = async (fd, label) => {
    fd.append('body', fd.get('body') ?? '');
    const tmp = h('div', { class: 'chat-msg mine pending' }, h('div', { class: 'chat-bubble' }, h('div', { class: 'chat-text' }, label), h('span', { class: 'chat-meta' }, 'gönderiliyor…')));
    list.append(tmp);
    list.scrollTop = list.scrollHeight;
    try { const m = await api.post(base, fd); tmp.remove(); append([m]); refreshSummary(); } catch (err) { tmp.remove(); toastError(err); }
  };
  const sendText = () => {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    autosize();
    const fd = new FormData();
    fd.append('body', text);
    send(fd, text);
  };
  const sendFiles = files => {
    for (const f of files) {
      if (f.size > 25 * 1024 * 1024) { toast(`${f.name}: 25 MB sınırını aşıyor`, 'err'); continue; }
      const fd = new FormData();
      fd.append('file', f);
      send(fd, `📎 ${f.name}`);
    }
  };
  const autosize = () => { input.style.height = 'auto'; input.style.height = `${Math.min(120, input.scrollHeight)}px`; };
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendText(); } });
  input.addEventListener('paste', e => { const f = [...(e.clipboardData?.files || [])]; if (f.length) { e.preventDefault(); sendFiles(f); } });
  sendBtn.addEventListener('click', sendText);
  emojiBtn.addEventListener('click', e => { e.stopPropagation(); emojiPicker(el, input, autosize); });
  fileIn.addEventListener('change', () => { sendFiles([...fileIn.files]); fileIn.value = ''; });
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drop'); });
  el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('drop'); });
  el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('drop'); sendFiles([...(e.dataTransfer?.files || [])]); });

  // Bas-konuş
  pushToTalk(micBtn, recBar, (blob, dur, ext) => {
    const fd = new FormData();
    fd.append('file', new File([blob], `ses-${Date.now()}${ext}`, { type: blob.type }));
    fd.append('duration', String(dur));
    send(fd, `🎤 Sesli mesaj (${secs(dur)})`);
  });

  // İlk yükleme
  try {
    const d = await api.get(base);
    if (win !== w) return;
    setPeer(group ? d.group : d.peer);
    append(d.items);
    w.first = d.items[0]?.id || 0;
    w.more = d.more;
    w.seen = d.seen_upto || 0;
    markSeen();
    list.scrollTop = list.scrollHeight;
    if (!d.items.length) list.append(h('div', { class: 'chat-empty' }, 'Henüz mesaj yok. İlk mesajı yazın, dosya ekleyin ya da mikrofona basılı tutarak konuşun.'));
    refreshSummary();
  } catch (err) { toastError(err); closeChat(); return; }
  w.timer = setInterval(poll, 2000);
  input.focus();
}

export function closeChat() {
  if (!win) return;
  clearInterval(win.timer);
  win.stopRec?.();
  win.el.remove();
  win = null;
}

// Basılı tut → kayıt; bırak → gönder; düğmeden yukarı uzaklaşıp bırakınca iptal. En çok 5 dk.
export function pushToTalk(btn, bar, onDone) {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  let rec = null, stream = null, chunks = [], started = 0, tick = null, cancel = false, startY = 0, pending = false;
  const ext = t => (t.includes('ogg') ? '.ogg' : t.includes('mp4') ? '.m4a' : '.webm');
  const stopAll = () => { clearInterval(tick); stream?.getTracks().forEach(t => t.stop()); stream = null; bar.hidden = true; btn.classList.remove('rec', 'cancel'); };
  const start = async e => {
    e.preventDefault();
    if (rec || pending) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('Bu tarayıcı ses kaydını desteklemiyor', 'err'); return; }
    startY = e.clientY;
    cancel = false;
    pending = true;
    btn.setPointerCapture?.(e.pointerId);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch { pending = false; toast('Mikrofon izni verilmedi', 'err'); return; }
    pending = false;
    if (!btn.classList.contains('down')) { stopAll(); return; }   // izin beklerken bırakıldı
    const type = types.find(t => MediaRecorder.isTypeSupported?.(t)) || '';
    rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    rec.ondataavailable = ev => { if (ev.data.size) chunks.push(ev.data); };
    rec.onstop = () => {
      const dur = (Date.now() - started) / 1000;
      const mime = rec.mimeType || type || 'audio/webm';
      rec = null;
      stopAll();
      if (cancel) { toast('Ses kaydı iptal edildi'); return; }
      if (dur < 0.7) { toast('Konuşmak için mikrofona basılı tutun'); return; }
      onDone(new Blob(chunks, { type: mime }), Math.round(dur * 10) / 10, ext(mime));
    };
    rec.start(250);
    started = Date.now();
    btn.classList.add('rec');
    bar.hidden = false;
    const draw = () => {
      const s = (Date.now() - started) / 1000;
      clear(bar, h('span', { class: 'chat-rec-dot' }), `Kaydediliyor ${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`,
        h('small', null, cancel ? 'Bırakınca iptal edilecek' : 'Bırakınca gönderilir · iptal için yukarı kaydırın'));
      if (s >= 300) stop();
    };
    draw();
    tick = setInterval(draw, 250);
  };
  const stop = () => { btn.classList.remove('down'); if (rec && rec.state !== 'inactive') rec.stop(); else if (!pending) stopAll(); };
  btn.addEventListener('pointerdown', e => { btn.classList.add('down'); start(e); });
  btn.addEventListener('pointerup', stop);
  btn.addEventListener('pointercancel', () => { cancel = true; stop(); });
  btn.addEventListener('pointermove', e => {
    if (!rec) return;
    const c = startY - e.clientY > 60;
    if (c !== cancel) { cancel = c; btn.classList.toggle('cancel', c); }
  });
  btn.addEventListener('contextmenu', e => e.preventDefault());   // tablette uzun basınca menü açılmasın
  if (win) win.stopRec = () => { cancel = true; if (rec && rec.state !== 'inactive') rec.stop(); else stopAll(); };
}

// ---------- Başlıktaki mesaj düğmesi
let summaryTimer;
export function chatButton(popup) {
  const count = h('span', { class: 'alert-count', hidden: true });
  const btn = h('button', { class: 'icon-btn chat-btn', title: 'Mesajlar', 'aria-label': 'Mesajlar', 'aria-haspopup': 'menu' }, svgIcon(icons.chat), count);
  const panel = h('div', { class: 'dropdown alerts-panel chat-panel', role: 'menu' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara, yeni sohbet başlat…' });
  const body = h('div');
  let data = { people: 0, unread: 0, items: [] };
  let users = null;
  let prev = null;
  const row = (u, extra) => h('button', { class: `chat-row ${u.unread ? 'unread' : ''} ${u.is_company ? 'company' : ''}`, type: 'button', onclick: () => { panel.hidden = true; openChat(u); } },
    h('span', { class: 'chat-av' }, convAvatar(u, 'sm'), u.online ? h('i', { class: 'chat-on' }) : null),
    h('div', { class: 'grow' }, h('div', { class: 'chat-row-top' }, h('b', null, titleOf(u)), extra?.time ? h('small', null, extra.time) : null),
      extra?.text != null ? h('div', { class: 'chat-prev' }, extra.text) : null),
    u.unread ? h('span', { class: 'chat-n' }, u.unread > 99 ? '99+' : u.unread) : null);
  const draw = () => {
    count.hidden = !data.people;
    count.textContent = data.people;
    btn.classList.toggle('on', !!data.people);
    btn.title = data.unread ? `${data.people} sohbette ${data.unread} okunmamış mesaj` : 'Mesajlar';
    if (q.value.trim() && users) {
      const groups = data.items.filter(x => x.kind === 'group' && matches(q.value, x.name));
      const list = users.filter(u => u.id !== me?.id && matches(q.value, u.full_name, u.username)).slice(0, 30);
      clear(body, groups.length || list.length ? [...groups.map(g => row(g)), ...list.map(u => row({ ...u, kind: 'user', ...(data.items.find(x => x.kind === 'user' && x.id === u.id) || {}) }))]
        : h('div', { class: 'empty small' }, 'Kişi ya da grup bulunamadı'));
      return;
    }
    const time = u => (!u.created_at ? null : dayLabel(u.created_at) === 'Bugün' ? hm(u.created_at) : dayLabel(u.created_at));
    const text = u => (!u.created_at ? (u.is_company ? 'Şirket duyuru kanalı' : 'Henüz mesaj yok')
      : `${u.mine ? 'Siz: ' : u.kind === 'group' && u.from_name ? `${u.from_name.split(' ')[0]}: ` : ''}${preview(u)}`);
    clear(body, data.items.length ? data.items.map(u => row(u, { time: time(u), text: text(u) }))
      : h('div', { class: 'empty small' }, 'Henüz mesajınız yok. Kişi arayarak ya da alttaki çevrimiçi kişilere tıklayarak sohbet başlatın.'));
  };
  const load = async () => {
    try {
      data = await api.get('/api/chat/summary');
      _summary = { people: data.people || 0, unread: data.unread || 0 };
      window.dispatchEvent(new CustomEvent('caymaz:chat-summary'));   // Kişisel panelindeki Mesajlar rozeti
      draw();
      // yeni gelen mesaj: sağ üstte kısa bildirim (açık sohbetteki kişi hariç)
      const now = new Map(data.items.map(u => [keyOf(u), u.unread]));
      if (prev) for (const u of data.items) if (u.unread > (prev.get(keyOf(u)) || 0) && win?.key !== keyOf(u)) { playEvent('message'); flashMessage(u); }
      prev = now;
    } catch { /* oturum kapanırsa kabuk yeniden çizilir */ }
  };
  refreshSummary = load;
  q.addEventListener('input', async () => { if (!users) users = await api.get('/api/people').catch(() => []); draw(); });
  const newGroup = h('button', { class: 'btn sm', type: 'button', onclick: () => { panel.hidden = true; groupForm(); } }, '+ Yeni grup');
  clear(panel, h('div', { class: 'alerts-head chat-head-row' }, h('span', null, 'Mesajlar'), newGroup), h('div', { class: 'chat-search' }, q), body);
  // Tıklayınca tam sayfa Mesajlar (WhatsApp-Web) açılır; popup yerine birleşik ekran. Rozet/okunmamış sayacı burada güncellenir.
  btn.addEventListener('click', () => { location.hash = '#/messages'; });
  clearInterval(summaryTimer);
  summaryTimer = setInterval(load, 5000);
  draw();
  load();
  return btn;
}

function flashMessage(u) {
  const who = u.kind === 'group' && u.from_name ? `${u.from_name}: ` : '';
  desktopNotify(`Yeni mesaj · ${titleOf(u)}`, who + preview(u), () => openChat(u));
  if (!flashOn()) return;
  const stack = document.querySelector('.flash-stack') || document.body.appendChild(h('div', { class: 'flash-stack', 'aria-live': 'polite' }));
  const box = h('a', { class: 'flash notify chat-flash', href: 'javascript:void 0', onclick: e => { e.preventDefault(); box.remove(); openChat(u); } },
    h('span', { class: 'flash-ico' }, convAvatar(u, 'sm')),
    h('div', null, h('div', { class: 'flash-kind' }, u.is_company ? 'Tüm Şirket' : 'Yeni mesaj'), h('b', null, titleOf(u)), h('div', { class: 'small' }, who + preview(u))));
  stack.append(box);
  setTimeout(() => box.classList.add('out'), flashMs() + 1000);
  setTimeout(() => box.remove(), flashMs() + 1400);
}

// ---------- Grup kur / düzenle / bilgi
export async function groupForm(g = null) {
  const people = (await api.get('/api/people')).filter(u => u.id !== me?.id);
  const name = h('input', { class: 'input', value: g?.name || '', placeholder: 'Ör. Üretim ekibi' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Kişi ara…' });
  const chosen = new Set(g ? g.members.map(m => m.id).filter(id => id !== me?.id) : []);
  const box = h('div', { class: 'chat-gpick' });
  const count = h('span', { class: 'small muted' });
  const draw = () => {
    const list = people.filter(u => matches(q.value, u.full_name, u.username));
    const picker = peoplePicker(list, { selected: [...chosen], sub: u => u.username });
    picker.addEventListener('click', () => { list.forEach(u => chosen.delete(u.id)); picker.getIds().forEach(id => chosen.add(id)); count.textContent = `${chosen.size} kişi seçildi`; });
    clear(box, picker);
    count.textContent = `${chosen.size} kişi seçildi`;
  };
  q.addEventListener('input', draw);
  draw();
  modal({
    title: g ? 'Grubu Düzenle' : 'Yeni Grup',
    body: h('div', null, field('Grup adı', name), field('Üyeler', h('div', null, q, count)), box),
    actions: [{ label: 'Vazgeç' }, { label: g ? 'Kaydet' : 'Grubu Kur', class: 'primary', onClick: async () => {
      const body = { name: name.value, user_ids: [...chosen] };
      const r = g ? await api.put(`/api/chat/groups/${g.id}`, body) : await api.post('/api/chat/groups', body);
      toast(g ? 'Grup güncellendi' : 'Grup kuruldu');
      refreshSummary();
      if (!g) openChat({ kind: 'group', id: r.id, name: r.name, is_company: 0 });
    } }],
  });
  name.focus();
}

async function groupInfo(gid) {
  const g = await api.get(`/api/chat/groups/${gid}`);
  modal({
    title: g.name,
    body: g.is_company
      ? h('p', null, `Şirket duyuru kanalı: ${g.member_count} kişinin tamamı üyedir. Bu kanala yalnızca Sistem Yöneticisi yazar; yazılan her mesaj herkese düşer.`)
      : h('ul', { class: 'chat-members' }, g.members.map(m => h('li', null, avatar(m, 'sm'), h('span', { class: 'grow' }, m.full_name), m.is_admin ? h('span', { class: 'badge blue' }, 'Yönetici') : null))),
    actions: [
      !g.is_company ? { label: 'Gruptan Ayrıl', class: 'danger', onClick: async () => {
        if (!await confirmDialog('Gruptan ayrıl', `"${g.name}" grubundan ayrılmak istiyor musunuz?`, { okLabel: 'Ayrıl', danger: true })) return true;
        await api.del(`/api/chat/groups/${gid}/me`); toast('Gruptan ayrıldınız'); closeChat(); refreshSummary();
      } } : null,
      g.can_edit ? { label: 'Düzenle', onClick: () => { groupForm(g); } } : null,
      'spacer', { label: 'Kapat', class: 'primary' },
    ].filter(Boolean),
  });
}

// ---------- Emoji: sık kullanılanlar üstte (tarayıcıda hatırlanır), gruplara ayrılmış basit seçim paneli
const EMOJI = {
  'Yüzler': '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😎 🤓 🤔 🤨 😐 😑 😶 🙄 😏 😬 😌 😔 😴 😷 🤒 🤯 😲 😳 🥺 😢 😭 😤 😠 😡 🤗 🤭 🤫 🥳 😇 🤩',
  'Eller': '👍 👎 👌 ✌️ 🤞 🤝 👏 🙌 🙏 💪 👋 ✋ 👉 👈 👆 👇 ☝️ ✍️ 🤙 🫡',
  'İş': '✅ ❌ ⚠️ ❗ ❓ 📌 📎 📅 ⏰ ⏳ 📦 🚚 🛠️ 🔧 🔩 ⚙️ 🖨️ 💻 📱 📞 📧 📝 📊 📈 📉 💡 🔋 🔌 🚀 ✈️ 🛩️ 🎯 🏁 🔒 🔑',
  'Semboller': '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💯 🔥 ⭐ 🌟 ✨ 🎉 🎊 🎁 ☕ 🍰 🍕 🌞 🌧️ ❄️ ⚡ 🇹🇷',
};
let emojiPop = null;
export function emojiPicker(win, input, after) {
  if (emojiPop) { emojiPop.remove(); emojiPop = null; return; }
  let recent = [];
  try { recent = JSON.parse(localStorage.getItem('caymaz.emoji') || '[]'); } catch { /* yok */ }
  const put = e => {
    const a = input.selectionStart ?? input.value.length, b = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0, a) + e + input.value.slice(b);
    input.focus();
    input.setSelectionRange(a + e.length, a + e.length);
    after?.();
    recent = [e, ...recent.filter(x => x !== e)].slice(0, 16);
    try { localStorage.setItem('caymaz.emoji', JSON.stringify(recent)); } catch { /* gizli pencere */ }
  };
  const groups = { ...(recent.length ? { 'Son kullanılanlar': recent.join(' ') } : {}), ...EMOJI };
  emojiPop = h('div', { class: 'emoji-pop', onclick: e => e.stopPropagation() }, Object.entries(groups).map(([k, v]) => [
    h('div', { class: 'emoji-h' }, k),
    h('div', { class: 'emoji-grid' }, v.split(' ').map(e => h('button', { type: 'button', onclick: () => put(e) }, e))),
  ]));
  win.append(emojiPop);
  const close = ev => { if (emojiPop && !emojiPop.contains(ev.target)) { emojiPop.remove(); emojiPop = null; document.removeEventListener('click', close); } };
  setTimeout(() => document.addEventListener('click', close), 0);
}
