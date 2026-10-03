// Canlı yayın (Instagram / TikTok Live tarzı). Yayıncı: kamera → tuval (kamera değiştirilebilsin diye) → MediaRecorder
// (parçalı MP4, ~1 sn) → /ws/live/{id}?role=pub. İzleyici: /ws/live/{id} → MediaSource ('sequence' kipi, iPhone'da
// ManagedMediaSource) ile oynatır; yorum, kalp (çift dokunuş / düğme), sol altta katılımcılar ve yorumlar, sağda uçuşan kalpler.
// Yayın bitince kayıt Şirketten Haberler'e düşer (sunucu kaydeder).
import { api } from '../api.js';
import { avatar, clear, confirmDialog, h, toast, toastError } from '../ui.js';

const MIMES = ['video/mp4;codecs=avc1.42E01F,mp4a.40.2', 'video/mp4;codecs=avc1,mp4a.40.2', 'video/mp4;codecs=avc1.42E01F,opus',
  'video/mp4;codecs=avc1,opus', 'video/mp4;codecs=vp9,opus', 'video/mp4'];
const pickMime = () => {
  if (!window.MediaRecorder) return null;
  let forced = null;
  try { forced = localStorage.getItem('caymaz.liveMime'); } catch { /* */ }   // test / tanı için zorlanmış biçim
  return [forced, ...MIMES].filter(Boolean).find(m => { try { return MediaRecorder.isTypeSupported(m); } catch { return false; } }) || null;
};
export const canBroadcast = () => !!(navigator.mediaDevices?.getUserMedia && pickMime());
const MSC = () => window.ManagedMediaSource || window.MediaSource;
const wsUrl = path => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;
const ICON = {
  heart: '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 21s-7.5-4.6-9.6-9.3C.9 8.3 3 4.5 6.7 4.5c2.1 0 3.6 1.2 4.3 2.4h2c.7-1.2 2.2-2.4 4.3-2.4 3.7 0 5.8 3.8 4.3 7.2C19.5 16.4 12 21 12 21z" fill="currentColor"/></svg>',
  eye: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><path d="M1.5 12S5.5 5 12 5s10.5 7 10.5 7-4 7-10.5 7S1.5 12 1.5 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  flip: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><path d="M9.5 13.5a3 3 0 0 0 5 1.6M14.5 12.5a3 3 0 0 0-5-1.6"/><path d="M14.5 15.6V13.6h-2M9.5 10.4v2h2"/></svg>',
  mic: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  micOff: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 11.6 5.3M19 11v0M12 18v3M3 3l18 18"/></svg>',
  send: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M3.4 20.4l17.4-7.5c.8-.3.8-1.5 0-1.8L3.4 3.6c-.7-.3-1.4.3-1.3 1l.9 5.3c.1.4.4.7.8.8l7.7 1.3-7.7 1.3c-.4.1-.7.4-.8.8l-.9 5.3c-.1.7.6 1.3 1.3 1z"/></svg>',
  sound: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9l4 6M21 9l-4 6"/></svg>',
};
const ico = (k, cls = '') => { const s = document.createElement('span'); s.className = `lv-ic ${cls}`; s.innerHTML = ICON[k]; return s; };
const pad = n => String(n).padStart(2, '0');
const clock = sec => (sec >= 3600 ? `${Math.floor(sec / 3600)}:${pad(Math.floor(sec % 3600 / 60))}:${pad(sec % 60)}` : `${pad(Math.floor(sec / 60))}:${pad(sec % 60)}`);
const HEART_COLORS = ['#ff3040', '#ff6b8b', '#ffb000', '#ff4fd8', '#a855f7', '#22c55e', '#38bdf8'];

// ---------- Ortak sahne: üst bilgi, yorumlar + katılımcılar (sol alt), uçan kalpler (sağ), yorum kutusu ----------
function scene({ owner, title, isPub }) {
  const media = h('div', { class: 'lv-media' });
  const live = h('span', { class: 'lv-badge' }, 'CANLI');
  const timer = h('span', { class: 'lv-timer' });
  const count = h('span', { class: 'lv-count' }, ico('eye'), h('b', null, '0'));
  const close = h('button', { class: 'lv-x', type: 'button', title: 'Kapat' }, '✕');
  const top = h('div', { class: 'lv-top' },
    h('div', { class: 'lv-owner' }, h('span', { class: 'lv-ring' }, avatar({ full_name: owner.name, photo: owner.photo }, 36)),
      h('div', { class: 'lv-owner-t' }, h('b', null, owner.name), title ? h('small', null, title) : null)),
    h('div', { class: 'lv-top-r' }, live, timer, count, close));
  const tools = h('div', { class: 'lv-tools' });
  const hearts = h('div', { class: 'lv-hearts' });
  const chat = h('div', { class: 'lv-chat' });
  const people = h('div', { class: 'lv-people' });
  const input = h('input', { class: 'lv-input', type: 'text', placeholder: 'Yorum yaz…', maxlength: 300, enterkeyhint: 'send' });
  const sendBtn = h('button', { class: 'lv-send', type: 'button', title: 'Gönder' }, ico('send'));
  const heartBtn = h('button', { class: 'lv-heartbtn', type: 'button', title: 'Beğen' }, ico('heart'));
  const bottom = h('div', { class: 'lv-bottom' }, chat, people,
    h('div', { class: 'lv-bar' }, h('div', { class: 'lv-inwrap' }, input, sendBtn), isPub ? null : heartBtn));
  const banner = h('div', { class: 'lv-banner', hidden: true });
  const root = h('div', { class: `lv ${isPub ? 'pub' : 'viewer'}` }, media, h('div', { class: 'lv-shade' }), top, tools, hearts, bottom, banner);

  const msgs = [];
  function addChat(m, kind = '') {
    const el = h('div', { class: `lv-msg ${kind}` },
      kind === 'join' ? null : avatar({ full_name: m.name, photo: m.photo }, 24),
      h('div', { class: 'lv-msg-t' }, h('b', null, m.name || ''), ' ', m.text));
    chat.append(el);
    msgs.push(el);
    while (msgs.length > 40) msgs.shift().remove();
    chat.scrollTop = chat.scrollHeight;
  }
  function setPeople(list) {
    count.lastChild.textContent = String(list.length);
    const shown = list.slice(0, 6);
    clear(people, list.length ? [h('div', { class: 'lv-stack' }, shown.map(u => h('span', { class: 'lv-pp', title: u.name }, avatar({ full_name: u.name, photo: u.photo }, 26)))),
      h('span', { class: 'lv-pp-t' }, list.length === 1 ? `${list[0].name} izliyor` : `${list[0].name} ve ${list.length - 1} kişi izliyor`)] : null);
  }
  function heart(x) {   // sağ alttan yükselen, salınan kalp
    const el = ico('heart', 'lv-fly');
    el.style.color = HEART_COLORS[Math.floor(Math.random() * HEART_COLORS.length)];
    el.style.setProperty('--dx', `${Math.round((Math.random() - 0.5) * 70)}px`);
    el.style.setProperty('--s', (0.8 + Math.random() * 0.6).toFixed(2));
    if (x != null) el.style.left = `${x}px`;
    hearts.append(el);
    setTimeout(() => el.remove(), 2600);
  }
  function burst(x, y) {   // çift dokunuş noktasında büyük kalp
    const el = ico('heart', 'lv-pop');
    el.style.left = `${x}px`; el.style.top = `${y}px`;
    root.append(el);
    setTimeout(() => el.remove(), 900);
  }
  function setBanner(text) { banner.hidden = !text; banner.textContent = text || ''; }
  return { root, media, top, tools, close, timer, input, sendBtn, heartBtn, addChat, setPeople, heart, burst, setBanner, chat };
}

function mount(root) {
  document.body.classList.add('lv-open');
  document.body.append(root);
}
function unmount(root) {
  root.remove();
  if (!document.querySelector('.lv')) document.body.classList.remove('lv-open');
}

// ---------- İzleyici ----------
let current = null;
export function watch(id, ctx) {
  if (current?.id === id) return;
  current?.destroy();
  const sc = scene({ owner: { name: 'Canlı yayın' }, isPub: false });
  const video = h('video', { class: 'lv-video', playsinline: true, autoplay: true, muted: true });
  video.disableRemotePlayback = true;
  const soundBtn = h('button', { class: 'lv-sound', type: 'button', hidden: true }, ico('sound'), 'Sesi aç');
  soundBtn.addEventListener('click', () => { video.muted = false; video.play().catch(() => {}); soundBtn.hidden = true; });
  sc.media.append(video, soundBtn);
  mount(sc.root);
  let ws = null, ms = null, sb = null, queue = [], mime = null, started = 0, timerT = 0, liveT = 0, closed = false, ended = false;
  sc.setBanner('Yayına bağlanılıyor…');

  const destroy = () => {
    if (closed) return;
    closed = true;
    clearInterval(timerT); clearInterval(liveT);
    try { ws?.close(); } catch { /* */ }
    try { video.pause(); video.removeAttribute('src'); video.load(); } catch { /* */ }
    window.removeEventListener('hashchange', onHash);
    unmount(sc.root);
    if (current?.destroy === destroy) current = null;
  };
  const leave = () => { destroy(); if (location.hash.startsWith('#/live')) location.hash = '#/home'; };
  const onHash = () => { if (!location.hash.startsWith(`#/live/${id}`)) destroy(); };
  window.addEventListener('hashchange', onHash);
  sc.close.addEventListener('click', leave);
  current = { id, destroy };

  function setupMSE(m) {
    const MS = MSC();
    if (!MS || !MS.isTypeSupported(m)) {
      sc.setBanner('Bu cihaz canlı yayın görüntüsünü oynatamıyor. Yorum ve beğeni gönderebilirsiniz; kayıt yayın bitince Şirketten Haberler’de.');
      return;
    }
    mime = m; queue = queue.length ? queue : []; sb = null;
    ms = new MS();
    video.src = URL.createObjectURL(ms);
    ms.addEventListener('sourceopen', () => {
      try {
        sb = ms.addSourceBuffer(mime);
        sb.mode = 'sequence';   // yayıncı kaydediciyi yeniden başlatsa da (yeni init, sıfırlanan zaman) kesintisiz
        sb.addEventListener('updateend', pump);
        pump();
      } catch (e) { sc.setBanner(`Oynatıcı açılamadı: ${e.message}`); }
    }, { once: true });
  }
  function pump() {
    if (!sb || sb.updating || !queue.length || ms?.readyState !== 'open') return;
    try {
      sb.appendBuffer(queue.shift());
      if (!started) {
        started = 1;
        video.play().then(() => { sc.setBanner(''); if (video.muted) soundBtn.hidden = false; })
          .catch(() => { sc.setBanner(''); soundBtn.hidden = false; });
      }
    } catch (e) {
      if (e.name === 'QuotaExceededError' && video.buffered.length) {
        const b0 = video.buffered.start(0);
        try { sb.remove(b0, Math.max(b0 + 1, video.currentTime - 6)); } catch { /* */ }
      }
    }
  }
  // gecikme denetimi + eski tamponu temizleme
  liveT = setInterval(() => {
    if (!sb || !video.buffered.length) return;
    const end = video.buffered.end(video.buffered.length - 1);
    if (end - video.currentTime > 3.5) video.currentTime = Math.max(0, end - 0.8);
    else if (video.paused && started && !ended) video.play().catch(() => {});
    const b0 = video.buffered.start(0);
    if (!sb.updating && video.currentTime - b0 > 40) { try { sb.remove(b0, video.currentTime - 20); } catch { /* */ } }
  }, 1000);

  function onEnd(m) {
    ended = true;
    clearInterval(timerT);
    sc.setBanner('');
    const card = h('div', { class: 'lv-end' }, h('div', { class: 'lv-end-ic' }, '🔴'), h('b', null, 'Canlı yayın sona erdi'),
      h('p', null, m.post_id ? 'Yayının kaydı Şirketten Haberler’de paylaşıldı.' : 'Teşekkürler!'),
      h('button', { class: 'btn primary', type: 'button', onclick: leave }, m.post_id ? 'Şirketten Haberler’e git' : 'Kapat'));
    sc.root.append(card);
  }
  function connect() {
    ws = new WebSocket(wsUrl(`/ws/live/${id}`));
    ws.binaryType = 'arraybuffer';
    ws.onmessage = e => {
      if (typeof e.data !== 'string') { queue.push(e.data); if (queue.length > 120) queue.splice(0, queue.length - 60); pump(); return; }
      let m; try { m = JSON.parse(e.data); } catch { return; }
      switch (m.t) {
        case 'hello': {
          queue = [];
          const o = m.owner;
          const ot = sc.top.querySelector('.lv-owner');
          clear(ot, h('span', { class: 'lv-ring' }, avatar({ full_name: o.name, photo: o.photo }, 36)),
            h('div', { class: 'lv-owner-t' }, h('b', null, o.name), m.title ? h('small', null, m.title) : null));
          started = 0;
          const t0 = new Date(m.started_at).getTime();
          clearInterval(timerT);
          timerT = setInterval(() => { sc.timer.textContent = clock(Math.max(0, Math.floor((Date.now() - t0) / 1000))); }, 1000);
          (m.comments || []).forEach(c => sc.addChat({ name: c.name, photo: c.photo, text: c.text }));
          sc.setPeople(m.viewers || []);
          if (m.mime) setupMSE(m.mime); else sc.setBanner('Yayıncı bekleniyor…');
          break;
        }
        case 'mime': if (!sb || m.mime !== mime) setupMSE(m.mime); break;
        case 'chat': sc.addChat(m); break;
        case 'like': if (m.uid !== ctx.user.id) sc.heart(); break;
        case 'viewers': sc.setPeople(m.list || []); if (m.join && m.join.id !== ctx.user.id) sc.addChat({ name: m.join.name, text: 'katıldı 👋' }, 'join'); break;
        case 'status': sc.setBanner(m.on_air ? '' : 'Yayıncının bağlantısı koptu, bekleniyor…'); break;
        case 'end': onEnd(m); break;
      }
    };
    ws.onclose = () => { if (!closed && !ended) setTimeout(() => { if (!closed && !ended) { sc.setBanner('Yeniden bağlanılıyor…'); connect(); } }, 2000); };
  }
  connect();

  const sendChat = () => {
    const text = sc.input.value.trim();
    if (!text || ws?.readyState !== 1) return;
    ws.send(JSON.stringify({ t: 'chat', text }));
    sc.input.value = '';
  };
  sc.input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); sendChat(); } });
  sc.sendBtn.addEventListener('click', sendChat);
  const like = () => { sc.heart(); if (ws?.readyState === 1) ws.send(JSON.stringify({ t: 'like' })); };
  sc.heartBtn.addEventListener('click', like);
  let lastTap = 0;
  sc.media.addEventListener('pointerup', e => {   // çift dokunuş = beğeni (Instagram)
    if (e.target.closest('button')) return;
    const now = e.timeStamp;
    if (now - lastTap < 320) { const r = sc.root.getBoundingClientRect(); sc.burst(e.clientX - r.left, e.clientY - r.top); like(); lastTap = 0; } else lastTap = now;
  });
}

// ---------- Yayıncı ----------
export async function startBroadcast(ctx) {
  const mime = pickMime();
  if (!mime || !navigator.mediaDevices?.getUserMedia) {
    toast('Bu tarayıcı canlı yayın kaydını desteklemiyor. Telefonda Safari / Chrome’un güncel sürümünü kullanın.', 'err');
    return;
  }
  const me = { name: ctx.user.full_name, photo: ctx.user.photo };
  const sc = scene({ owner: me, isPub: true });
  const video = h('video', { class: 'lv-video', playsinline: true, autoplay: true, muted: true });
  sc.media.append(video);
  mount(sc.root);
  let facing = 'user', cam = null, audioTracks = [], micOn = true;
  let canvas = null, g = null, drawing = false, rec = null, ws = null, sid = null, onAir = false, ending = false, t0 = 0, timerT = 0, wake = null;

  async function openCam() {
    const s = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30, max: 30 } },
      audio: cam ? false : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (!cam) audioTracks = s.getAudioTracks();
    cam?.getVideoTracks().forEach(t => t.stop());
    cam = new MediaStream([...s.getVideoTracks(), ...audioTracks]);
    video.srcObject = cam;
    video.classList.toggle('mirror', facing === 'user');
    await video.play().catch(() => {});
  }
  try { await openCam(); } catch (e) { unmount(sc.root); toastError(new Error(`Kameraya erişilemedi: ${e.message}`)); return; }

  // Ön hazırlık: başlık + "Canlı yayını başlat"
  const titleIn = h('input', { class: 'lv-title-in', type: 'text', placeholder: 'Yayın başlığı (ör. Sahadan: montaj hattı)', maxlength: 120 });
  const goBtn = h('button', { class: 'lv-go', type: 'button' }, h('span', { class: 'lv-go-dot' }), 'Canlı yayını başlat');
  const pre = h('div', { class: 'lv-pre' }, titleIn, goBtn, h('small', null, 'Başlayınca herkese bildirim gider; yayın bitince kayıt Şirketten Haberler’de paylaşılır.'));
  sc.root.append(pre);
  sc.root.classList.add('prelive');
  const flipBtn = h('button', { class: 'lv-tool', type: 'button', title: 'Kamerayı çevir' }, ico('flip'));
  const micBtn = h('button', { class: 'lv-tool', type: 'button', title: 'Mikrofon' }, ico('mic'));
  clear(sc.tools, flipBtn, micBtn);
  flipBtn.addEventListener('click', async () => {
    facing = facing === 'user' ? 'environment' : 'user';
    try { await openCam(); } catch { facing = facing === 'user' ? 'environment' : 'user'; toast('Diğer kamera açılamadı', 'err'); }
  });
  micBtn.addEventListener('click', () => {
    micOn = !micOn;
    audioTracks.forEach(t => { t.enabled = micOn; });
    clear(micBtn, ico(micOn ? 'mic' : 'micOff'));
    micBtn.classList.toggle('off', !micOn);
  });

  const stopAll = () => {
    drawing = false;
    clearInterval(timerT);
    try { rec?.state !== 'inactive' && rec?.stop(); } catch { /* */ }
    cam?.getTracks().forEach(t => t.stop());
    try { wake?.release(); } catch { /* */ }
    try { ws?.close(); } catch { /* */ }
  };
  const quit = () => { stopAll(); unmount(sc.root); };

  // Kamera → tuval (kamera değişse de kayıt sürer) → captureStream + mikrofon → MediaRecorder
  function outStream() {
    const vw = video.videoWidth || 1280, vh = video.videoHeight || 720;
    const portrait = vh > vw;
    const long = 1280, short = 720;
    canvas = h('canvas', { width: portrait ? short : long, height: portrait ? long : short });
    g = canvas.getContext('2d', { alpha: false });
    drawing = true;
    const draw = () => {
      if (!drawing) return;
      const sw = video.videoWidth, sh = video.videoHeight;
      if (sw && sh) {   // kapla (cover): kenarlardan kırp
        const s = Math.max(canvas.width / sw, canvas.height / sh);
        const dw = sw * s, dh = sh * s;
        g.drawImage(video, (canvas.width - dw) / 2, (canvas.height - dh) / 2, dw, dh);
      }
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw); else requestAnimationFrame(draw);
    };
    draw();
    try {
      const out = canvas.captureStream(30);
      return new MediaStream([...out.getVideoTracks(), ...audioTracks]);
    } catch { return cam; }   // captureStream yoksa doğrudan kamera (kamera değişimi yayını yeniden başlatır)
  }
  let recStream = null;
  function startRecorder() {
    recStream ??= outStream();
    const opts = { mimeType: mime, videoBitsPerSecond: 1_600_000, audioBitsPerSecond: 64_000 };
    try { rec = new MediaRecorder(recStream, { ...opts, videoKeyFrameIntervalDuration: 2000 }); }
    catch { rec = new MediaRecorder(recStream, opts); }
    rec.ondataavailable = e => { if (e.data?.size && ws?.readyState === 1) ws.send(e.data); };
    rec.onerror = () => toast('Kayıt hatası; yayın yeniden başlatılıyor', 'err');
    rec.start(1000);
  }
  function restartRecorder() {
    try { if (rec && rec.state !== 'inactive') { rec.ondataavailable = null; rec.stop(); } } catch { /* */ }
    startRecorder();
  }
  function connect() {
    ws = new WebSocket(wsUrl(`/ws/live/${sid}?role=pub`));
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => { sc.setBanner(''); restartRecorder(); };   // her bağlantıda yeni init (sunucu yeni parça açar)
    ws.onmessage = e => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.t === 'hello') sc.setPeople(m.viewers || []);
      else if (m.t === 'viewers') { sc.setPeople(m.list || []); if (m.join) sc.addChat({ name: m.join.name, text: 'katıldı 👋' }, 'join'); }
      else if (m.t === 'chat') sc.addChat(m);
      else if (m.t === 'like') sc.heart();
      else if (m.t === 'end') finish(m);
    };
    ws.onclose = () => { if (onAir && !ending) { sc.setBanner('Bağlantı koptu, yeniden bağlanılıyor…'); setTimeout(() => { if (onAir && !ending) connect(); }, 1500); } };
  }
  goBtn.addEventListener('click', async () => {
    goBtn.disabled = true; goBtn.lastChild.textContent = 'Başlatılıyor…';
    try {
      const r = await api.post('/api/live/start', { title: titleIn.value.trim() || null });
      sid = r.id;
    } catch (e) { toastError(e); goBtn.disabled = false; goBtn.lastChild.textContent = 'Canlı yayını başlat'; return; }
    onAir = true;
    pre.remove(); sc.root.classList.remove('prelive');
    sc.close.textContent = 'Bitir'; sc.close.classList.add('end'); sc.close.title = 'Yayını bitir';
    const tt = titleIn.value.trim();
    if (tt) sc.top.querySelector('.lv-owner-t').append(h('small', null, tt));
    t0 = Date.now();
    timerT = setInterval(() => { sc.timer.textContent = clock(Math.floor((Date.now() - t0) / 1000)); }, 1000);
    try { wake = await navigator.wakeLock?.request('screen'); } catch { /* */ }
    connect();
  });

  async function finish(m) {
    if (ending && m?.t !== 'end') return;
    ending = true; onAir = false;
    stopAll();
    const card = h('div', { class: 'lv-end' }, h('div', { class: 'lv-end-ic' }, '✅'), h('b', null, 'Canlı yayın bitti'),
      h('p', null, `Süre ${sc.timer.textContent || '00:00'} · kayıt Şirketten Haberler’de paylaşıldı.`),
      h('button', { class: 'btn primary', type: 'button', onclick: () => { unmount(sc.root); location.hash = '#/home'; } }, 'Tamam'));
    sc.root.append(card);
  }
  sc.close.addEventListener('click', async () => {
    if (!onAir) return quit();
    if (!await confirmDialog('Yayını bitir', 'Canlı yayın sonlandırılsın mı? Kayıt Şirketten Haberler’de paylaşılacak.', { okLabel: 'Bitir', danger: true })) return;
    ending = true;
    try { if (rec && rec.state !== 'inactive') { await new Promise(r => { rec.addEventListener('stop', r, { once: true }); rec.stop(); setTimeout(r, 1500); }); } } catch { /* */ }
    try { ws?.readyState === 1 && ws.send(JSON.stringify({ t: 'end' })); } catch { /* */ }
    try { await api.post(`/api/live/${sid}/end`, {}); } catch { /* sunucu zaten bitirdi */ }
    finish();
  });
  const sendChat = () => {
    const text = sc.input.value.trim();
    if (!text || ws?.readyState !== 1) return;
    ws.send(JSON.stringify({ t: 'chat', text }));
    sc.input.value = '';
  };
  sc.input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); sendChat(); } });
  sc.sendBtn.addEventListener('click', sendChat);
}
