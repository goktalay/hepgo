// Canlı mesajlaşma (birebir): sağ altta açılan sohbet penceresi ve başlıktaki mesaj düğmesi.
// Pencere açıkken yeni mesajlar 2 sn'de bir çekilir. Metin, dosya / resim (sürükle-bırak ya da ataç) ve bas-konuş ses
// kaydı gönderilebilir: mikrofon düğmesine basılı tutulur, bırakınca gider (yukarı kaydırıp bırakınca iptal).
// Başlıktaki düğme okunmamış mesajları gönderene göre gruplar; sayı, okunmamış mesajı olan kişi sayısıdır.
import { api, fileUrl } from './api.js';
import { icons } from './icons.js';
import { desktopNotify, flashMs, flashOn } from './prefs.js';
import { playEvent } from './sounds.js';
import { avatar, clear, fmtDateTime, h, matches, svgIcon, toast, toastError } from './ui.js';

let me = null;
let win = null;          // açık sohbet: { uid, el, timer, ... }
let refreshSummary = () => {};
export const setChatUser = u => { me = u; };

const hm = iso => iso.slice(11, 16);
const dayLabel = iso => {
  const d = iso.slice(0, 10), t = new Date(), y = new Date(Date.now() - 864e5);
  const f = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  return d === f(t) ? 'Bugün' : d === f(y) ? 'Dün' : `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
};
const size = b => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((b || 0) / 1024))} KB`);
const secs = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const preview = m => (m.file_kind === 'audio' ? '🎤 Sesli mesaj' : m.file_kind === 'image' ? `🖼 ${m.body || 'Resim'}` : m.file_kind === 'file' ? `📎 ${m.file_name}` : m.body || '');

// ---------- Sohbet penceresi
export async function openChat(user) {
  if (!user?.id || user.id === me?.id) return;
  if (win?.uid === user.id) { win.input.focus(); return; }
  closeChat();
  const list = h('div', { class: 'chat-list' });
  const input = h('textarea', { class: 'chat-input', rows: 1, placeholder: 'Mesaj yazın…', 'data-no-mic': '' });
  const fileIn = h('input', { type: 'file', multiple: true, hidden: true });
  const status = h('span', { class: 'chat-status' });
  const recBar = h('div', { class: 'chat-rec', hidden: true });
  const micBtn = h('button', { class: 'chat-mic', type: 'button', title: 'Bas-konuş: basılı tutun, bırakınca gönderilir' }, svgIcon(icons.mic));
  const sendBtn = h('button', { class: 'chat-send', type: 'button', title: 'Gönder (Enter)' }, svgIcon(icons.send));
  const head = h('div', { class: 'chat-head' },
    avatar(user, 'sm'), h('div', { class: 'grow' }, h('b', null, user.full_name), status),
    h('button', { class: 'chat-x', type: 'button', title: 'Kapat', onclick: () => closeChat() }, '×'));
  const el = h('div', { class: 'chat-win', role: 'dialog', 'aria-label': `${user.full_name} ile mesajlaşma` }, head, list, recBar,
    h('div', { class: 'chat-bar' },
      h('button', { class: 'chat-attach', type: 'button', title: 'Dosya ya da resim gönder', onclick: () => fileIn.click() }, svgIcon(icons.paperclip)),
      input, fileIn, micBtn, sendBtn));
  document.body.append(el);
  const w = win = { uid: user.id, el, input, last: 0, first: 0, seen: 0, timer: null, lastDay: null };

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
      h('div', { class: 'chat-bubble' }, content,
        h('span', { class: 'chat-meta' }, hm(m.created_at), mine ? h('span', { class: 'chat-tick' }, '✓') : null)));
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
  const setPeer = p => {
    el.classList.toggle('closed', !!p.no_messages);
    input.disabled = !!p.no_messages;
    input.placeholder = p.no_messages ? `${p.full_name} mesaj almayı kapatmış` : 'Mesaj yazın…';
    status.textContent = p.online ? 'çevrimiçi' : p.last_seen ? `son görülme ${fmtDateTime(p.last_seen)}` : 'çevrimdışı';
    status.classList.toggle('on', p.online);
  };
  const poll = async () => {
    if (win !== w || document.hidden) return;
    try {
      const d = await api.get(`/api/chat/${user.id}?after=${w.last}`);
      if (win !== w) return;
      setPeer(d.peer);
      if (d.items.length) {
        append(d.items);
        if (d.items.some(m => m.from_id !== me.id)) { playEvent('message'); refreshSummary(); }   // açık sohbette de sesle haber ver
      }
      if (d.seen_upto !== w.seen) { w.seen = d.seen_upto; markSeen(); }
    } catch { /* bağlantı koparsa bir sonraki turda denenir */ }
  };
  // Eski mesajlar: listenin en üstüne kaydırınca
  const loadOlder = async () => {
    if (!w.more || w.loading) return;
    w.loading = true;
    try {
      const d = await api.get(`/api/chat/${user.id}?before=${w.first}`);
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
    try { const m = await api.post(`/api/chat/${user.id}`, fd); tmp.remove(); append([m]); refreshSummary(); } catch (err) { tmp.remove(); toastError(err); }
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
    const d = await api.get(`/api/chat/${user.id}`);
    if (win !== w) return;
    setPeer(d.peer);
    append(d.items);
    w.first = d.items[0]?.id || 0;
    w.more = d.more;
    w.seen = d.seen_upto;
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
function pushToTalk(btn, bar, onDone) {
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
  const row = (u, extra) => h('button', { class: `chat-row ${u.unread ? 'unread' : ''}`, type: 'button', onclick: () => { panel.hidden = true; openChat(u); } },
    h('span', { class: 'chat-av' }, avatar(u, 'sm'), u.online ? h('i', { class: 'chat-on' }) : null),
    h('div', { class: 'grow' }, h('div', { class: 'chat-row-top' }, h('b', null, u.full_name), extra?.time ? h('small', null, extra.time) : null),
      extra?.text != null ? h('div', { class: 'chat-prev' }, extra.text) : null),
    u.unread ? h('span', { class: 'chat-n' }, u.unread > 99 ? '99+' : u.unread) : null);
  const draw = () => {
    count.hidden = !data.people;
    count.textContent = data.people;
    btn.classList.toggle('on', !!data.people);
    btn.title = data.unread ? `${data.people} kişiden ${data.unread} okunmamış mesaj` : 'Mesajlar';
    if (q.value.trim() && users) {
      const list = users.filter(u => u.id !== me?.id && matches(q.value, u.full_name, u.username)).slice(0, 30);
      clear(body, list.length ? list.map(u => row({ ...u, ...(data.items.find(x => x.id === u.id) || {}) })) : h('div', { class: 'empty small' }, 'Kişi bulunamadı'));
      return;
    }
    clear(body, data.items.length ? data.items.map(u => row(u, { time: dayLabel(u.created_at) === 'Bugün' ? hm(u.created_at) : dayLabel(u.created_at),
      text: `${u.mine ? 'Siz: ' : ''}${preview(u)}` }))
      : h('div', { class: 'empty small' }, 'Henüz mesajınız yok. Kişi arayarak ya da alttaki çevrimiçi kişilere tıklayarak sohbet başlatın.'));
  };
  const load = async () => {
    try {
      data = await api.get('/api/chat/summary');
      draw();
      // yeni gelen mesaj: sağ üstte kısa bildirim (açık sohbetteki kişi hariç)
      const now = new Map(data.items.map(u => [u.id, u.unread]));
      if (prev) for (const u of data.items) if (u.unread > (prev.get(u.id) || 0) && win?.uid !== u.id) { playEvent('message'); flashMessage(u); }
      prev = now;
    } catch { /* oturum kapanırsa kabuk yeniden çizilir */ }
  };
  refreshSummary = load;
  q.addEventListener('input', async () => { if (!users) users = await api.get('/api/people').catch(() => []); draw(); });
  clear(panel, h('div', { class: 'alerts-head' }, 'Mesajlar'), h('div', { class: 'chat-search' }, q), body);
  popup(btn, panel);
  btn.addEventListener('click', () => { load(); q.value = ''; });
  clearInterval(summaryTimer);
  summaryTimer = setInterval(load, 5000);
  draw();
  load();
  return h('div', { class: 'menu-anchor' }, btn, panel);
}

function flashMessage(u) {
  desktopNotify(`Yeni mesaj · ${u.full_name}`, preview(u), () => openChat(u));
  if (!flashOn()) return;
  const stack = document.querySelector('.flash-stack') || document.body.appendChild(h('div', { class: 'flash-stack', 'aria-live': 'polite' }));
  const box = h('a', { class: 'flash notify chat-flash', href: 'javascript:void 0', onclick: e => { e.preventDefault(); box.remove(); openChat(u); } },
    h('span', { class: 'flash-ico' }, avatar(u, 'sm')),
    h('div', null, h('div', { class: 'flash-kind' }, 'Yeni mesaj'), h('b', null, u.full_name), h('div', { class: 'small' }, preview(u))));
  stack.append(box);
  setTimeout(() => box.classList.add('out'), flashMs() + 1000);
  setTimeout(() => box.remove(), flashMs() + 1400);
}
