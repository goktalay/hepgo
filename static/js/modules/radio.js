// Telsiz (bas-konuş): üst çubuktaki telsiz düğmesi kanalları listeler; kanala tıklanınca küçük dinleme paneli açılır.
// Üstte kendi resminize BASILI TUTARAK konuşursunuz; altta kanal üyeleri. Ses /ws/radio üzerinden kanalın çevrimiçi
// herkesine onaysız, canlı çalınır; aynı anda konuşanların sesleri ayrı ayrı gelir ve alıcıda karışır.
// Görsel standart sesli görüşmeyle aynı: arka plan teması ve avatar çevresinde ses halkası.
import { avatar, clear, h, svgIcon, t, toast } from '../ui.js';
import { api } from '../api.js';
import { icons } from '../icons.js';
import { CALL_BACKGROUNDS } from './voice.js';

const SR = 16000;              // iletim örnekleme hızı (μ-law, mono)
const FRAME = 640;             // 40 ms
const MAX_TALK_MS = 90000;     // basılı kalan düğmeye karşı güvenlik
const MUTE_KEY = 'caymaz.radioMute';

let ctx = null, ws = null, retryT = null, retryN = 0, pingT = null, wanted = false;
let channels = [];                       // [{id,name,color,members:[{id,full_name,photo,online}],talking:[uid]}]
let desks = [];                          // Sekreterya / Güvenlik birim hatları (kanal gibi; id = 0xF0000000|birim)
let staffOf = new Set();                 // kullanıcının görevli olduğu birim kanalları → bekleme odası
const queue = new Map();                 // bekleme odası: uid -> {uid, desk, at, unread}
let dock = null;                         // görevlinin ekranındaki kalıcı bekleme odası
// Birim kanal kodları (sunucuyla aynı): seslenme 0xF0000000|birim, görevliden kişiye özel 0x80000000|birim<<24|kişi
const DESK_BASE = 0xF0000000;
const isDesk = ch => (ch >>> 28) === 0xF;
const isPriv = ch => (ch >>> 31) === 1 && !isDesk(ch);
const privCh = (deskCh, uid) => ((0x80000000 | ((deskCh & 0xFF) << 24) | uid) >>> 0);
const norm = ch => (isPriv(ch) ? ((DESK_BASE | ((ch >>> 24) & 0x7F)) >>> 0) : ch);
const allChans = () => [...channels, ...desks];
// Renkli öğe: CSS özel değişkeni (--c) stil nesnesiyle atanamadığı için setProperty ile
const tinted = (el, color) => { el.style.setProperty('--c', color); return el; };
const chanById = id => allChans().find(c => c.id === id);
const talking = new Map();               // ch -> Set(uid)
let listEls = null;                      // üst çubuk düğmesi parçaları
let panel = null;                        // açık dinleme paneli
let onair = null;                        // panel kapalıyken "konuşuyor" çipi

// ---------------- μ-law (G.711) ----------------
const MU_DEC = new Float32Array(256);
for (let i = 0; i < 256; i++) {
  const u = ~i & 0xff, sign = u & 0x80, exp = (u >> 4) & 7, man = u & 0x0f;
  const s = (((man << 3) + 0x84) << exp) - 0x84;
  MU_DEC[i] = (sign ? -s : s) / 32768;
}
function muEnc(x) {
  let s = Math.max(-1, Math.min(1, x)) * 32767;
  const sign = s < 0 ? 0x80 : 0;
  if (sign) s = -s;
  s = Math.min(32635, s) + 0x84;
  let exp = 7;
  for (let m = 0x4000; (s & m) === 0 && exp > 0; m >>= 1) exp--;
  return ~(sign | (exp << 4) | ((s >> (exp + 3)) & 0x0f)) & 0xff;
}

// ---------------- Ses motoru ----------------
let ac = null;
function audio() {
  if (!ac) { try { ac = new (window.AudioContext || window.webkitAudioContext)(); } catch { return null; } }
  if (ac.state !== 'running' && ac.state !== 'closed') ac.resume().catch(() => {});   // iOS: 'suspended' ya da 'interrupted'
  return ac;
}
// Tarayıcılar sesi ilk dokunuştan önce çaldırmaz: ilk etkileşimde sesi aç
const unlock = () => { audio(); hideUnlock(); };
['pointerdown', 'keydown', 'touchstart'].forEach(e => document.addEventListener(e, unlock, { capture: true, passive: true }));
let unlockChip = null;
function needUnlock() {
  if (unlockChip) return;
  unlockChip = h('button', { class: 'rd-unlock', type: 'button', onclick: unlock }, svgIcon(icons.radio), 'Telsiz sesi için dokunun');
  document.body.append(unlockChip);
}
function hideUnlock() { if (ac && ac.state === 'running' && unlockChip) { unlockChip.remove(); unlockChip = null; } }

function beep(freqs, vol = 0.05) {
  const c = audio(); if (!c || c.state !== 'running') return;
  let t = c.currentTime;
  for (const [f, d] of freqs) {
    const o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.value = f; o.connect(g); g.connect(c.destination);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + d);
    o.start(t); o.stop(t + d + 0.02); t += d;
  }
}

// Gelen ses: konuşan başına kendi zamanlaması (titreşim tamponu) ve halka için analizörü
const players = new Map();   // `${ch}:${uid}` -> {next, gain, an, last}
function player(ch, uid) {
  const key = `${ch}:${uid}`;
  let p = players.get(key);
  if (!p) {
    const c = audio();
    const gain = c.createGain(), an = c.createAnalyser();
    an.fftSize = 64; an.smoothingTimeConstant = 0.7;
    gain.connect(an); an.connect(c.destination);
    p = { next: 0, gain, an, last: 0 };
    players.set(key, p);
  }
  return p;
}
function playFrame(wch, uid, bytes) {
  const ch = norm(wch);
  if (!isDesk(ch) && muted().has(ch)) return;
  if (isDesk(ch) && staffOf.has(ch) && !isPriv(wch)) queueTouch(uid, ch);
  const c = audio();
  if (!c || c.state !== 'running') { needUnlock(); return; }
  const p = player(ch, uid);
  // Tampon, ses motorunun kendi hızında üretilir (eski Safari 22 kHz altı tamponu reddediyor → ses hiç çalmıyordu)
  const n = bytes.length, rate = c.sampleRate, m = Math.max(1, Math.round(n * rate / SR));
  const buf = c.createBuffer(1, m, rate), d = buf.getChannelData(0);
  const step = (n - 1) / Math.max(1, m - 1);
  for (let i = 0; i < m; i++) {
    const x = i * step, k = x | 0, f = x - k, a = MU_DEC[bytes[k]], b = MU_DEC[bytes[Math.min(n - 1, k + 1)]];
    d[i] = a + (b - a) * f;
  }
  const src = c.createBufferSource();
  src.buffer = buf; src.connect(p.gain);
  const now = c.currentTime;
  if (p.next < now + 0.04 || p.next > now + 1.2) p.next = now + 0.14;   // boşluk / birikme → yeniden hizala
  src.start(p.next); p.next += n / SR; p.last = Date.now();
}

// Mikrofon: AudioWorklet (yoksa ScriptProcessor) → 16 kHz → μ-law → WS
// Eski iOS / tabletler için: worklet yüklemesi takılırsa ScriptProcessor'a düşülür; mikrofon açılınca askıya alınan ses
// motoru yeniden başlatılır; mikrofondan hiç ses gelmezse (WebKit hatası) yakalama yeni bir ses motoruyla kurulur.
const WORKLET = `class C extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage(c.slice(0));return true}}registerProcessor('radio-cap',C);`;
const workletCtx = new WeakSet();
let cap = null, talk = null;
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('zaman aşımı')), ms))]);
async function buildCap(c, stream, own) {
  if (c.state !== 'running') { try { await withTimeout(c.resume(), 1500); } catch { /* */ } }
  const src = c.createMediaStreamSource(stream);
  const an = c.createAnalyser(); an.fftSize = 64; an.smoothingTimeConstant = 0.7; src.connect(an);
  let node = null;
  if (window.AudioWorkletNode && c.audioWorklet) {
    try {
      if (!workletCtx.has(c)) { await withTimeout(c.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))), 1500); workletCtx.add(c); }
      node = new AudioWorkletNode(c, 'radio-cap');
      node.port.onmessage = e => onPcm(e.data);
    } catch { node = null; }
  }
  if (!node) {
    node = (c.createScriptProcessor || c.createJavaScriptNode).call(c, 2048, 1, 1);
    node.onaudioprocess = e => onPcm(e.inputBuffer.getChannelData(0));
  }
  const sink = c.createGain(); sink.gain.value = 0;   // işlemcinin çalışması için hedefe bağlı olmalı (sessiz)
  src.connect(node); node.connect(sink); sink.connect(c.destination);
  return { stream, ctx: c, own, src, node, sink, an, rate: c.sampleRate };
}
async function ensureMic() {
  if (cap) return cap;
  const c = audio(); if (!c) throw new Error('Ses desteklenmiyor');   // dokunuş anında: ses motoru izinli başlar
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Bu tarayıcı mikrofonu desteklemiyor');
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  cap = await buildCap(c, stream, false);
  return cap;
}
// Mikrofon açık ama örnek gelmiyor / hep sıfır → yakalamayı yeni bir ses motoruyla yeniden kur (iOS WebKit hatası)
async function rebuildCap() {
  if (!cap) return;
  const stream = cap.stream;
  try { cap.src.disconnect(); cap.node.disconnect(); cap.sink.disconnect(); if (cap.own) cap.ctx.close(); } catch { /* */ }
  const C = window.AudioContext || window.webkitAudioContext;
  cap = await buildCap(new C(), stream, true);
}
function releaseMic() {
  if (!cap) return;
  try { cap.stream.getTracks().forEach(t => t.stop()); cap.src.disconnect(); cap.node.disconnect(); cap.sink.disconnect(); if (cap.own) cap.ctx.close(); } catch { /* */ }
  cap = null;
}
const rs = { acc: 0, cnt: 0, frac: 0, out: [], got: 0, peak: 0 };
function onPcm(x) {
  if (!talk || !cap) return;
  const ratio = cap.rate / SR;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (v > rs.peak) rs.peak = v; else if (-v > rs.peak) rs.peak = -v;
    rs.acc += v; rs.cnt++; rs.frac += 1;
    if (rs.frac >= ratio) {
      rs.frac -= ratio; rs.out.push(rs.acc / rs.cnt); rs.acc = 0; rs.cnt = 0;
      if (rs.out.length >= FRAME) flush();
    }
  }
  rs.got += x.length;
}
function flush() {
  if (!talk || !rs.out.length || ws?.readyState !== 1) { rs.out = []; return; }
  const n = rs.out.length, b = new Uint8Array(5 + n);
  b[0] = 1; new DataView(b.buffer).setUint32(1, talk.ch);
  for (let i = 0; i < n; i++) b[5 + i] = muEnc(rs.out[i]);
  rs.out = [];
  try { ws.send(b); } catch { /* */ }
}

// Basılı tut-konuş: Pointer Events (yeni tarayıcılar) yoksa dokunma + fare olaylarıyla (eski iPhone / tablet).
function holdToTalk(el, down, up) {
  el.addEventListener('contextmenu', e => e.preventDefault());
  if (window.PointerEvent) {
    el.addEventListener('pointerdown', e => { e.preventDefault(); try { el.setPointerCapture(e.pointerId); } catch { /* */ } down(e); });
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    return;
  }
  let touching = false;
  el.addEventListener('touchstart', e => { e.preventDefault(); touching = true; down(e); }, { passive: false });
  el.addEventListener('touchend', e => { e.preventDefault(); touching = false; up(e); }, { passive: false });
  el.addEventListener('touchcancel', () => { touching = false; up(); });
  el.addEventListener('mousedown', e => { if (!touching) { e.preventDefault(); down(e); } });
  el.addEventListener('mouseup', () => { if (!touching) up(); });
  el.addEventListener('mouseleave', () => { if (!touching) up(); });
}

// Telsiz gibi: mikrofon YALNIZCA basılı tutulduğu sürece açık; bırakınca hemen kapanır.
async function startTalk(ch) {
  if (talk) return;
  if (ws?.readyState !== 1) { toast('Telsiz bağlantısı yok, yeniden bağlanılıyor…', 'err'); return; }
  const pending = { ch, cancelled: false };
  talk = pending;
  try { await ensureMic(); }
  catch (err) {
    talk = null;
    toast(err?.name === 'NotAllowedError' ? 'Mikrofon izni verilmedi. Tarayıcı ayarlarından bu site için mikrofona izin verin.'
      : err?.message === 'Bu tarayıcı mikrofonu desteklemiyor' ? err.message : 'Mikrofona erişilemedi', 'err');
    return;
  }
  if (pending.cancelled || talk !== pending) { if (talk === pending) talk = null; if (!talk) releaseMic(); return; }
  Object.assign(rs, { acc: 0, cnt: 0, frac: 0, out: [], got: 0, peak: 0 });
  send({ t: 'talk', ch, on: true });
  watchMic(pending);
  setTalking(ch, ctx.user.id, true);
  beep([[1046, 0.06]], 0.04);
  talk.timer = setTimeout(() => stopTalk(), MAX_TALK_MS);
  navigator.vibrate?.(15);
}
// Bekçi: konuşma başladıktan sonra mikrofondan örnek gelmiyor ya da hepsi sıfırsa bir kez yeniden kur, olmazsa uyar
function watchMic(t) {
  setTimeout(async () => {
    if (talk !== t || !cap || (rs.got > 0 && rs.peak > 1e-5)) return;
    try { await rebuildCap(); } catch { /* */ }
    rs.got = 0; rs.peak = 0;
    setTimeout(() => {
      if (talk === t && cap && !(rs.got > 0 && rs.peak > 1e-5)) toast('Mikrofondan ses alınamıyor. Tarayıcının mikrofon iznini kontrol edin.', 'err');
    }, 900);
  }, 700);
}

function stopTalk() {
  const t = talk; if (!t) return;
  t.cancelled = true;
  if (t.timer) { clearTimeout(t.timer); flush(); send({ t: 'talk', ch: t.ch, on: false }); setTalking(t.ch, ctx.user.id, false); beep([[880, 0.05], [660, 0.07]], 0.035); }
  talk = null;
  releaseMic();
}

// ---------------- Bağlantı ----------------
const send = m => { try { ws?.readyState === 1 && ws.send(JSON.stringify(m)); } catch { /* */ } };
export function connect(context) {
  ctx = context; wanted = true;
  loadChannels();
  if (ws && ws.readyState <= 1) return;
  open();
}
function open() {
  clearTimeout(retryT);
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/radio`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { retryN = 0; loadChannels(); };
  ws.onmessage = ev => {
    if (typeof ev.data !== 'string') {
      const dv = new DataView(ev.data);
      if (dv.byteLength < 10 || dv.getUint8(0) !== 1) return;
      playFrame(dv.getUint32(1), dv.getUint32(5), new Uint8Array(ev.data, 9));
      return;
    }
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    if (m.t === 'talk') setTalking(m.ch, m.uid, m.on);
    else if (m.t === 'presence') presence(m.uid, m.online);
    else if (m.t === 'channels') loadChannels();
  };
  ws.onclose = () => {
    stopTalk();
    clearInterval(pingT);
    if (wanted) retryT = setTimeout(open, Math.min(30000, 1500 * 2 ** retryN++));
  };
  clearInterval(pingT);
  pingT = setInterval(() => send({ t: 'ping' }), 25000);
}
export function disconnect() {
  wanted = false; stopTalk(); closePanel(); closeDock();
  clearTimeout(retryT); clearInterval(pingT);
  try { ws?.close(); } catch { /* */ }
  ws = null; channels = [];
}

async function loadChannels() {
  try {
    const [ch, dk] = await Promise.all([api.get('/api/radio/channels'), api.get('/api/radio/desks')]);
    channels = ch; desks = dk.desks; staffOf = new Set(dk.staff_of);
  } catch { return; }
  for (const c of channels) talking.set(c.id, new Set(c.talking || []));
  renderList();
  if (panel) { chanById(panel.ch) ? renderPanel() : closePanel(); }
  if (staffOf.size) { if (!people.size) await loadPeople(); loadQueue(); if (dockPref()) openDock(false); else renderDock(); }
}
function presence(uid, online) {
  for (const c of allChans()) for (const m of c.members) if (m.id === uid) m.online = online;
  for (const c of allChans()) c.online = c.members.filter(m => m.online).length;
  renderList(); if (panel) renderPanel(); renderDock();
}
function setTalking(wch, uid, on) {
  const ch = norm(wch);
  if (on && uid !== ctx?.user?.id && isDesk(ch) && staffOf.has(ch) && !isPriv(wch)) { queueTouch(uid, ch); openDock(true); }
  const s = talking.get(ch) || new Set();
  const was = s.has(uid);
  on ? s.add(uid) : s.delete(uid);
  talking.set(ch, s);
  if (uid !== ctx?.user?.id && (isDesk(ch) || !muted().has(ch))) {
    if (on && !was) beep([[1318, 0.05]], 0.03);
    if (!on && was) beep([[784, 0.05], [988, 0.06]], 0.025);   // "anlaşıldı" tonu
  }
  renderList(); if (panel) markTalking(); updateOnair(); renderDock();
}

// ---------------- Sessize alma (cihaz tercihi) ----------------
function muted() { try { return new Set(JSON.parse(localStorage.getItem(MUTE_KEY) || '[]')); } catch { return new Set(); } }
function toggleMute(ch) {
  const m = muted(); m.has(ch) ? m.delete(ch) : m.add(ch);
  try { localStorage.setItem(MUTE_KEY, JSON.stringify([...m])); } catch { /* */ }
  renderList(); if (panel) renderPanel(); updateOnair();
}

// ---------------- Üst çubuk düğmesi + kanal listesi ----------------
export function button(popup) {
  const count = h('span', { class: 'rd-live', hidden: true });
  const btn = h('button', { class: 'icon-btn rd-btn', type: 'button', title: 'Telsiz', 'aria-label': 'Telsiz', 'aria-haspopup': 'menu', hidden: true },
    svgIcon(icons.radio), count);
  const menu = h('div', { class: 'dropdown rd-menu', role: 'menu' });
  // Sekreterya / güvenlik görevlisi: düğme kanal listesi yerine kalıcı bekleme odasını açar (popup'tan ÖNCE kaydedilir)
  btn.addEventListener('click', e => {
    if (!staffOf.size) return;
    e.stopImmediatePropagation(); e.stopPropagation();
    dock && !dock.min ? minimizeDock() : openDock(true);
  });
  popup(btn, menu);
  listEls = { btn, menu, count };
  renderList();
  return h('div', { class: 'menu-anchor' }, btn, menu);
}
function renderList() {
  if (!listEls) return;
  const { btn, menu, count } = listEls;
  btn.hidden = !channels.length;
  const live = channels.some(c => (talking.get(c.id)?.size || 0) > 0 && !muted().has(c.id));
  btn.classList.toggle('live', live);
  count.hidden = !live;
  const mt = muted();
  const deskBtns = desks.filter(d => !staffOf.has(d.id)).map(d => tinted(h('button', { class: 'rd-deskbtn', type: 'button', title: t('{name} birimine seslen ({n} çevrimiçi görevli)', { name: d.name, n: d.online }),
    onclick: () => { menu.hidden = true; openPanel(d.id); } }, h('i'), d.name), d.color));
  clear(menu, h('div', { class: 'alerts-head rd-menu-head' }, h('span', null, 'Telsiz kanalları'), h('span', { class: 'rd-deskbtns' }, ...deskBtns)),
    channels.length ? channels.map(c => {
      const speakers = [...(talking.get(c.id) || [])].map(u => c.members.find(m => m.id === u)?.full_name).filter(Boolean);
      return h('div', { class: `rd-item ${speakers.length ? 'on' : ''}` },
        h('button', { class: 'rd-item-main', type: 'button', onclick: () => { menu.hidden = true; openPanel(c.id); } },
          h('span', { class: 'rd-dot', style: { background: c.color || '#2f6fed' } }),
          h('span', { class: 'rd-item-txt' }, h('b', null, c.name),
            h('small', null, speakers.length ? t('{name} konuşuyor…', { name: speakers[0].split(' ')[0] }) : t('{online}/{total} çevrimiçi', { online: c.online, total: c.members.length }))),
          h('span', { class: 'rd-stack' }, ...c.members.slice(0, 4).map(m => h('span', { class: m.online ? '' : 'off' }, avatar(m, 'sm'))))),
        h('button', { class: `rd-mute ${mt.has(c.id) ? 'on' : ''}`, type: 'button', title: mt.has(c.id) ? 'Sesi aç' : 'Sessize al (bu cihaz)',
          onclick: e => { e.stopPropagation(); toggleMute(c.id); } }, svgIcon(mt.has(c.id) ? SPK_OFF : SPK)));
    }) : h('div', { class: 'empty small' }, 'Üyesi olduğunuz kanal yok'),
    h('a', { class: 'rd-manage', href: '#/settings/radio', onclick: () => { menu.hidden = true; } }, '＋ Kanal oluştur / kanallarımı yönet'));
}
window.addEventListener('caymaz:radio-refresh', () => loadChannels());
const SPK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5v5h4l5 4v-13l-5 4z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a7.5 7.5 0 0 1 0 11"/></svg>';
const SPK_OFF = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9.5v5h4l5 4v-13l-5 4z"/><path d="M17 9.5l5 5M22 9.5l-5 5"/></svg>';

// ---------------- Dinleme paneli ----------------
function ring(size) {
  const cv = h('canvas', { class: 'rd-ring' });
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  cv.width = cv.height = Math.round(size * dpr); cv.style.width = cv.style.height = `${size}px`;
  return cv;
}
// Sesli görüşmedeki halka: avatarın çevresine sarılı, ses yükseldikçe uzayan çubuklar
function drawRing(cv, an, active) {
  const g = cv.getContext('2d'); if (!g) return;
  const w = cv.width, cx = w / 2, rMax = cx - 3, inner = rMax * 0.68, n = w > 200 ? 56 : 36;
  g.clearRect(0, 0, w, w);
  let data = null;
  if (an && active) { data = new Uint8Array(an.frequencyBinCount); an.getByteFrequencyData(data); }
  g.lineCap = 'round'; g.lineWidth = Math.max(2, w / 70);
  for (let i = 0; i < n; i++) {
    const v = data ? (data[(i * 3) % data.length] || 0) / 255 : 0;
    const len = 2 + v * (rMax - inner - 2);
    const a = (i / n) * Math.PI * 2 - Math.PI / 2, c = Math.cos(a), s = Math.sin(a);
    g.strokeStyle = `rgba(255,255,255,${active ? 0.5 + v * 0.5 : 0.22})`;
    g.beginPath(); g.moveTo(cx + c * inner, cx + s * inner); g.lineTo(cx + c * (inner + len), cx + s * (inner + len)); g.stroke();
  }
}
function bg() { return CALL_BACKGROUNDS[ctx?.user?.prefs?.settings?.callBg] || CALL_BACKGROUNDS.aurora; }

function openPanel(ch) {
  audio();
  if (panel && panel.ch === ch) return;
  if (panel) closePanel(true);
  const el = h('div', { class: 'rd-panel', style: { background: bg() } });
  document.body.append(el);
  panel = { ch, el, raf: 0, refs: null };
  renderPanel();
  dragify(el);
  const loop = () => {
    if (!panel) return;
    const r = panel.refs;
    if (r) {
      drawRing(r.meRing, cap?.an, !!talk && norm(talk.ch) === panel.ch && !!talk.timer);
      for (const m of r.members) {
        const p = players.get(`${panel.ch}:${m.id}`);
        drawRing(m.ring, p?.an, talking.get(panel.ch)?.has(m.id) || (p && Date.now() - p.last < 400));
      }
    }
    panel.raf = requestAnimationFrame(loop);
  };
  panel.raf = requestAnimationFrame(loop);
  document.addEventListener('keydown', spaceDown); document.addEventListener('keyup', spaceUp);
  updateOnair();
}
function closePanel(switching) {
  if (!panel) return;
  stopTalk();
  cancelAnimationFrame(panel.raf);
  panel.el.remove(); panel = null;
  document.removeEventListener('keydown', spaceDown); document.removeEventListener('keyup', spaceUp);
  if (!switching) releaseMic();
  updateOnair();
}
const typing = () => /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
function spaceDown(e) { if (e.code === 'Space' && !e.repeat && panel && !typing()) { e.preventDefault(); startTalk(panel.ch).then(markTalking); } }
function spaceUp(e) { if (e.code === 'Space' && panel && !typing()) { e.preventDefault(); stopTalk(); markTalking(); } }

function renderPanel() {
  const c = chanById(panel.ch);
  if (!c) return;
  const me = ctx.user;
  const mt = !c.is_desk && muted().has(c.id);
  const meRing = ring(196);
  const meAv = h('button', { class: 'rd-me-av', type: 'button', 'aria-label': 'Konuşmak için basılı tutun' }, meRing, avatar(me, 'xl'));
  const hint = h('div', { class: 'rd-hint' });
  const press = () => { meAv.classList.add('down'); startTalk(c.id).then(markTalking); markTalking(); };
  const release = () => { meAv.classList.remove('down'); stopTalk(); markTalking(); };
  holdToTalk(meAv, press, release);
  const others = c.members.filter(m => m.id !== me.id);
  const members = others.map(m => {
    const r = ring(72);
    const el = h('div', { class: `rd-m ${m.online ? '' : 'off'}`, title: m.online ? m.full_name : t('{name} · çevrimdışı', { name: m.full_name }) },
      h('div', { class: 'rd-m-av' }, r, avatar(m, 'md')), h('span', null, m.full_name.split(' ')[0]));
    return { id: m.id, el, ring: r };
  });
  clear(panel.el,
    h('div', { class: 'rd-head' },
      h('span', { class: 'rd-dot', style: { background: c.color || '#2f6fed' } }),
      h('div', { class: 'rd-title' }, h('b', null, c.name),
        h('small', null, c.is_desk ? (c.online ? t('{n} görevli çevrimiçi', { n: c.online }) : 'Şu an çevrimiçi görevli yok') : t('{online} çevrimiçi · {total} üye', { online: c.online, total: c.members.length }))),
      c.is_desk ? null : h('button', { class: `rd-hbtn ${mt ? 'on' : ''}`, type: 'button', title: mt ? 'Sesi aç' : 'Sessize al', onclick: () => toggleMute(c.id) }, svgIcon(mt ? SPK_OFF : SPK)),
      h('button', { class: 'rd-hbtn', type: 'button', title: 'Kapat', onclick: () => closePanel() }, '✕')),
    h('div', { class: 'rd-me' }, meAv, hint),
    others.length ? h('div', { class: 'rd-members' }, ...members.map(m => m.el)) : h('div', { class: 'rd-empty' }, c.is_desk ? 'Bu birimde tanımlı görevli yok' : 'Kanalda başka üye yok'));
  panel.refs = { meAv, meRing, hint, members };
  markTalking();
}
function markTalking() {
  if (!panel?.refs) return;
  const s = talking.get(panel.ch) || new Set();
  const c = chanById(panel.ch);
  const meTalking = !!talk && norm(talk.ch) === panel.ch && !!talk.timer;
  panel.refs.meAv.classList.toggle('talking', meTalking);
  for (const m of panel.refs.members) m.el.classList.toggle('talking', s.has(m.id));
  const speakers = [...s].filter(u => u !== ctx.user.id).map(u => c?.members.find(m => m.id === u)?.full_name).filter(Boolean);
  panel.refs.hint.textContent = meTalking ? 'Konuşuyorsunuz — bırakınca biter'
    : speakers.length ? t('{who} konuşuyor…', { who: speakers.join(', ') })
      : talk ? 'Mikrofon hazırlanıyor…' : 'Konuşmak için resminize basılı tutun';
  panel.refs.hint.classList.toggle('live', meTalking || speakers.length > 0);
}

// Panel kapalıyken: kim konuşuyor çipi (tıklayınca paneli açar)
function updateOnair() {
  const mt = muted();
  let hit = null;
  for (const c of allChans()) {
    if ((!c.is_desk && mt.has(c.id)) || panel?.ch === c.id || staffOf.has(c.id)) continue;
    const u = [...(talking.get(c.id) || [])].find(x => x !== ctx?.user?.id);
    if (u) { hit = { c, m: c.members.find(m => m.id === u) }; break; }
  }
  if (!hit) { if (onair) { const o = onair; onair = null; o.classList.add('out'); setTimeout(() => o.remove(), 300); } return; }
  if (!onair) { onair = h('button', { class: 'rd-onair', type: 'button' }); document.body.append(onair); }
  onair.onclick = () => openPanel(hit.c.id);
  clear(onair, h('span', { class: 'rd-onair-av' }, avatar(hit.m || { full_name: '?' }, 'sm')),
    h('span', { class: 'rd-onair-txt' }, h('b', null, hit.m?.full_name || 'Biri'), h('small', null, hit.c.name)),
    h('span', { class: 'rd-bars' }, h('i'), h('i'), h('i'), h('i')));
}

// Paneli başlığından sürükleyerek taşıma
function dragify(el) {
  let d = null;
  el.addEventListener('pointerdown', e => {
    if (!e.target.closest('.rd-head') || e.target.closest('button')) return;
    const r = el.getBoundingClientRect();
    d = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', e => {
    if (!d) return;
    const x = Math.min(Math.max(6, e.clientX - d.dx), innerWidth - el.offsetWidth - 6);
    const y = Math.min(Math.max(6, e.clientY - d.dy), innerHeight - el.offsetHeight - 6);
    Object.assign(el.style, { left: `${x}px`, top: `${y}px`, right: 'auto', bottom: 'auto' });
  });
  el.addEventListener('pointerup', () => { d = null; });
}

// ---------------- Görevli bekleme odası (Sekreterya / Güvenlik) ----------------
// Birime seslenen herkes burada resmiyle sıraya girer (birden çok kişi aynı anda bekleyebilir). Görevli bir resme
// BASILI TUTTUĞU sürece yalnızca o kişiyle konuşur; ses yalnız ikisi arasındadır. Oda ekranda kalıcıdır.
const DOCK_KEY = 'caymaz.radioDock', QUEUE_KEY = 'caymaz.radioQueue';
const dockPref = () => { try { return localStorage.getItem(DOCK_KEY) !== '0'; } catch { return true; } };
const setDockPref = v => { try { localStorage.setItem(DOCK_KEY, v ? '1' : '0'); } catch { /* */ } };
// Kişi adı / fotoğrafı: önce kanal üyelerinden, yoksa şirketteki tüm kullanıcılar listesinden (görevliye herkes seslenebilir)
let people = new Map();
async function loadPeople() {
  try { people = new Map((await api.get('/api/voice/users')).map(u => [u.id, u])); } catch { /* */ }
}
function person(uid) {
  for (const c of allChans()) { const m = c.members.find(x => x.id === uid); if (m) return m; }
  if (people.has(uid)) return people.get(uid);
  if (!people.size || !person.asked?.has(uid)) {   // listede yoksa (yeni kullanıcı) bir kez tazele
    (person.asked ||= new Set()).add(uid);
    loadPeople().then(() => renderDock());
  }
  return { id: uid, full_name: 'Bilinmeyen kişi' };
}
function loadQueue() {
  if (queue.size) return;
  try { for (const q of JSON.parse(sessionStorage.getItem(QUEUE_KEY) || '[]')) queue.set(q.uid, q); } catch { /* */ }
}
function saveQueue() { try { sessionStorage.setItem(QUEUE_KEY, JSON.stringify([...queue.values()].slice(-20))); } catch { /* */ } }
function queueTouch(uid, deskCh) {
  if (uid === ctx?.user?.id) return;
  const q = queue.get(uid) || { uid, desk: deskCh, unread: true };
  const fresh = !queue.has(uid);
  q.desk = deskCh; q.at = Date.now(); q.unread = true;
  queue.delete(uid); queue.set(uid, q);   // en son seslenen sona (en üstte gösterilir)
  saveQueue();
  if (fresh) renderDock(true);
}
function dockHint() {
  return talk && isPriv(talk.ch) && talk.timer ? t('{name} ile konuşuyorsunuz — bırakınca biter', { name: person(talk.ch & 0xFFFFFF).full_name.split(' ')[0] })
    : 'Cevap vermek için kişinin resmine basılı tutun';
}
function ago(ts) {
  const s = Math.round((Date.now() - ts) / 1000);
  return s < 45 ? 'şimdi' : s < 3600 ? t('{n} dk önce', { n: Math.round(s / 60) }) : t('{n} sa önce', { n: Math.round(s / 3600) });
}
function openDock(user) {
  if (!staffOf.size) return;
  if (user) setDockPref(true);
  if (!dock) {
    dock = { el: h('div', { class: 'rd-dock' }), raf: 0, refs: [], min: false, tick: setInterval(() => renderDock(true), 30000) };
    document.body.append(dock.el);
    document.body.classList.add('rd-docked');
    const loop = () => {
      if (!dock) return;
      if (!dock.min) for (const r of dock.refs) {
        const p = players.get(`${r.desk}:${r.uid}`);
        drawRing(r.ring, r.answering ? cap?.an : p?.an, r.answering || talking.get(r.desk)?.has(r.uid) || (p && Date.now() - p.last < 400));
      }
      dock.raf = requestAnimationFrame(loop);
    };
    dock.raf = requestAnimationFrame(loop);
  }
  dock.min = false;
  renderDock(true);
}
function minimizeDock() { if (!dock) return; dock.min = true; setDockPref(false); renderDock(true); }
function closeDock() {
  if (!dock) return;
  cancelAnimationFrame(dock.raf); clearInterval(dock.tick);
  dock.el.remove(); dock = null; document.body.classList.remove('rd-docked');
}
function renderDock(full) {
  if (!dock) return;
  const desksMine = desks.filter(d => staffOf.has(d.id));
  const entries = [...queue.values()].filter(q => staffOf.has(q.desk)).reverse();
  const liveIds = new Set(entries.filter(q => talking.get(q.desk)?.has(q.uid)).map(q => q.uid));
  const unread = entries.filter(q => q.unread).length;
  dock.el.classList.toggle('min', dock.min);
  dock.el.style.background = bg();
  if (dock.min) {
    clear(dock.el, h('button', { class: 'rd-dock-pill', type: 'button', onclick: () => openDock(true) },
      svgIcon(icons.radio), h('b', null, 'Bekleme odası'),
      liveIds.size ? h('span', { class: 'rd-bars' }, h('i'), h('i'), h('i'), h('i')) : unread ? h('span', { class: 'rd-dock-n' }, unread) : null));
    dock.refs = [];
    return;
  }
  if (!full && dock.refs.length === entries.length) {   // yalnızca durum sınıflarını güncelle (yeniden çizme yok)
    for (const r of dock.refs) {
      r.el.classList.toggle('talking', liveIds.has(r.uid));
      r.el.classList.toggle('answering', !!talk && isPriv(talk.ch) && (talk.ch & 0xFFFFFF) === r.uid && !!talk.timer);
      r.answering = r.el.classList.contains('answering');
    }
    if (dock.hint) dock.hint.textContent = dockHint();
    return;
  }
  const refs = [];
  const cards = entries.map(q => {
    const m = person(q.uid), d = desks.find(x => x.id === q.desk);
    const r = ring(96);
    const av = h('button', { class: 'rd-q-av', type: 'button', 'aria-label': t('{name} ile konuşmak için basılı tutun', { name: m.full_name }) }, r, avatar(m, 'lg'));
    const press = () => {
      q.unread = false; saveQueue(); el.classList.remove('unread');
      startTalk(privCh(q.desk, q.uid)).then(() => renderDock());
      renderDock();
    };
    const release = () => { stopTalk(); renderDock(); };
    holdToTalk(av, press, release);
    const el = h('div', { class: `rd-q ${q.unread ? 'unread' : ''} ${liveIds.has(q.uid) ? 'talking' : ''}` },
      h('button', { class: 'rd-q-x', type: 'button', title: 'Bekleme odasından kaldır', onclick: () => { queue.delete(q.uid); saveQueue(); renderDock(true); } }, '✕'),
      av, h('b', null, m.full_name.split(' ').slice(0, 2).join(' ')),
      h('small', null, desksMine.length > 1 && d ? `${d.name} · ${ago(q.at)}` : ago(q.at)));
    refs.push({ el, ring: r, uid: q.uid, desk: q.desk, answering: false });
    return el;
  });
  const chips = [...channels.map(c => tinted(h('button', { class: 'rd-chip', type: 'button', onclick: () => openPanel(c.id) }, h('i'), c.name), c.color || '#2f6fed')),
    ...desks.filter(d => !staffOf.has(d.id)).map(d => tinted(h('button', { class: 'rd-chip', type: 'button', onclick: () => openPanel(d.id) }, h('i'), d.name), d.color))];
  clear(dock.el,
    h('div', { class: 'rd-dock-head' },
      svgIcon(icons.radio),
      h('div', { class: 'rd-title' }, h('b', null, 'Bekleme Odası'), h('small', null, desksMine.map(d => d.name).join(' · '))),
      h('button', { class: 'rd-hbtn', type: 'button', title: 'Küçült', onclick: minimizeDock }, '—')),
    entries.length ? h('div', { class: 'rd-queue' }, ...cards)
      : h('div', { class: 'rd-dock-empty' }, 'Size telsizle seslenen olduğunda resmi burada belirir. Cevap vermek için resmine basılı tutun.'),
    dock.hint = entries.length ? h('div', { class: 'rd-hint live' }, dockHint()) : null,
    chips.length ? h('div', { class: 'rd-dock-chips' }, ...chips) : null);
  dock.refs = refs;
  renderDock();   // durum sınıfları
}
