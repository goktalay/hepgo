// Kişiler arası sesli görüşme (WebRTC istemcisi): WebSocket sinyalleşme + mesh peer bağlantıları + arama arayüzü.
// Ses akışı uçtan uca (peer-to-peer). Kayıt yalnızca tüm katılımcı onaylayınca; karışık sesi başlatan kaydeder,
// bitince yükler. Görüşmelerim: geçmiş + konuşmacı tanımalı transkript + özet.
import { api } from '../api.js';
import { avatar, clear, confirmDialog, fmtDateTime, fmtDuration, h, modal, pageHead, t, toast, toastError } from '../ui.js';
import { playEvent } from '../sounds.js';

const RTC = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }] };
let ws = null, ctx = null, backoff = 1000, pingTimer = null;
let ring = null;      // gelen arama {call_id, caller, kind, el}
let call = null;      // aktif görüşme durumu

// ---------- Görüşme arka planları (kullanıcı ayarından) ----------
export const CALL_BACKGROUNDS = {
  aurora: 'linear-gradient(140deg,#1e3a5f,#2d1b4e 55%,#0f172a)',
  ocean: 'linear-gradient(140deg,#0ea5e9,#1e40af 70%,#0c1445)',
  sunset: 'linear-gradient(140deg,#7c2d12,#be185d 55%,#4c1d95)',
  forest: 'linear-gradient(140deg,#065f46,#14532d 60%,#052e16)',
  charcoal: 'linear-gradient(140deg,#334155,#0f172a)',
  night: 'radial-gradient(circle at 50% 30%,#312e81,#0b1020 72%)',
};
export const CALL_BG_LABELS = { aurora: 'Aurora', ocean: 'Okyanus', sunset: 'Gün batımı', forest: 'Orman', charcoal: 'Antrasit', night: 'Gece' };
function callBg() { return CALL_BACKGROUNDS[ctx?.user?.prefs?.settings?.callBg] || CALL_BACKGROUNDS.aurora; }
// Telefon: tam ekran arama. Tablet / bilgisayar: sağ altta küçük kart.
const isPhone = () => matchMedia('(max-width: 820px)').matches;

// ---------- İkonlar (çağrı kontrolleri) ----------
const PHONE = '<path d="M6.6 10.8c1.4 2.8 3.8 5.2 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.2.4 2.4.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.2.2 2.4.6 3.6.1.4 0 .8-.2 1l-2.3 2.2z"/>';
const ICONS = {
  accept: `<g fill="currentColor">${PHONE}</g>`,
  decline: `<g fill="currentColor" transform="rotate(135 12 12)">${PHONE}</g>`,
  end: `<g fill="currentColor" transform="rotate(135 12 12)">${PHONE}</g>`,
  add: `<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 3v8M11 7h8"/><path fill="currentColor" stroke="none" d="M4.6 9.8c1.2 2.4 3.2 4.4 5.6 5.6l1.9-1.9c.3-.3.6-.3.9-.2 1 .3 2 .5 3 .5.5 0 .9.4.9.9V17c0 .5-.4.9-.9.9-8 0-14.5-6.5-14.5-14.5 0-.5.4-.9.9-.9h2.9c.5 0 .9.4.9.9 0 1 .2 2 .5 3 .1.3 0 .6-.2.9L4.6 9.8z"/></g>`,
  mic: `<g fill="currentColor"><rect x="9" y="3" width="6" height="11" rx="3"/><path fill="none" stroke="currentColor" stroke-width="2" d="M5 11a7 7 0 0 0 14 0M12 18v3"/></g>`,
  micOff: `<g fill="currentColor"><rect x="9" y="3" width="6" height="9" rx="3"/><path fill="none" stroke="currentColor" stroke-width="2" d="M5 11a7 7 0 0 0 11.3 5.5M19 11a7 7 0 0 1-.3 2M12 18v3"/></g><path stroke="currentColor" stroke-width="2" d="M4 3l16 16"/>`,
  record: '<circle cx="12" cy="12" r="6" fill="currentColor"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  video: '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="12" height="10" rx="2"/><path d="M15 10l5-3v10l-5-3z"/></g>',
  videoOff: '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 10l5-3v10l-5-3"/><path d="M3 7h9v10H3z"/><path d="M3 3l18 18"/></g>',
  flipCamera: '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="12" rx="2"/><circle cx="12" cy="13" r="2.4"/><path d="M8.5 7l1.2-2h4.6l1.2 2"/><path d="M15.5 13a3.5 3.5 0 0 1-5.6 2.8"/><path d="M8.5 13a3.5 3.5 0 0 1 5.6-2.8"/></g>',
  min: '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M6 14l6 5 6-5"/>',
  more: '<g fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></g>',
};
function iconSvg(name) {
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  g.setAttribute('viewBox', '0 0 24 24'); g.setAttribute('class', 'vc-ic'); g.innerHTML = ICONS[name] || '';
  return g;
}

// ---------- Ses: zil sesi (WebAudio) + konuşma grafiği ----------
let _actx = null;
function actx() {
  if (!_actx) { try { _actx = new (window.AudioContext || window.webkitAudioContext)(); } catch { return null; } }
  if (_actx.state === 'suspended') _actx.resume().catch(() => {});
  return _actx;
}
let ringTimer = null;
function ringBeat(kind) {
  const c = actx(); if (!c) return;
  const now = c.currentTime;
  const beat = (freq, off, dur, vol) => {
    const o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.value = freq; o.connect(g); g.connect(c.destination);
    g.gain.setValueAtTime(0.0001, now + off); g.gain.exponentialRampToValueAtTime(vol, now + off + 0.03);
    g.gain.setValueAtTime(vol, now + off + dur - 0.06); g.gain.exponentialRampToValueAtTime(0.0001, now + off + dur);
    o.start(now + off); o.stop(now + off + dur + 0.02);
  };
  if (kind === 'in') { beat(523, 0, 0.35, 0.2); beat(659, 0.4, 0.35, 0.2); }   // gelen: çift tonlu zil
  else beat(420, 0, 0.45, 0.06);   // giden: ringback
}
function startRing(kind) { stopRing(); ringBeat(kind); ringTimer = setInterval(() => ringBeat(kind), kind === 'in' ? 2200 : 3200); }
function stopRing() { if (ringTimer) { clearInterval(ringTimer); ringTimer = null; } }

function analyserFor(stream) {
  const c = actx(); if (!c || !stream) return null;
  try { const an = c.createAnalyser(); an.fftSize = 64; an.smoothingTimeConstant = 0.75; c.createMediaStreamSource(stream).connect(an); return an; }
  catch { return null; }
}
let rafId = null;
function startBars() {
  if (rafId) return;
  const tick = () => {
    if (!call || !ui) { rafId = null; return; }
    call.peers.forEach(p => drawRing(p.canvas, p.analyser, false));
    const lt = call.local?.getAudioTracks?.()[0];
    drawRing(ui.selfBars, call.localAnalyser, lt && !lt.enabled);
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}
function stopBars() { if (rafId) { cancelAnimationFrame(rafId); rafId = null; } }
// Dairesel ses görselleştirici: avatarın çevresine sarılı, konuşma yükseldikçe uzayan çubuklar.
function drawRing(cv, an, muted) {
  if (!cv) return;
  const g = cv.getContext('2d'); if (!g) return;
  const w = cv.width, hh = cv.height, cx = w / 2, cy = hh / 2;
  g.clearRect(0, 0, w, hh);
  const rMax = Math.min(cx, cy) - 3;
  const inner = rMax * 0.66;   // avatar kenarı ~ bu yarıçapta; çubuklar bunun DIŞINDA
  const n = 48;
  let data = null;
  if (an) { data = new Uint8Array(an.frequencyBinCount); an.getByteFrequencyData(data); }
  for (let i = 0; i < n; i++) {
    const v = (muted || !data) ? 0 : (data[i % data.length] || 0) / 255;
    const len = 3 + v * (rMax - inner - 3);
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const c = Math.cos(a), s = Math.sin(a);
    g.strokeStyle = `rgba(255,255,255,${0.45 + v * 0.55})`;
    g.lineWidth = 4; g.lineCap = 'round';
    g.beginPath(); g.moveTo(cx + c * inner, cy + s * inner); g.lineTo(cx + c * (inner + len), cy + s * (inner + len)); g.stroke();
  }
}

// ---------- WebSocket ----------
let everOpened = false;
const sendPresence = () => send({ t: 'presence', visible: document.visibilityState === 'visible' });   // görünürken telefon bildirimi gelmesin
export function connect(context) {
  ctx = context;
  everOpened = false;
  document.addEventListener('visibilitychange', sendPresence);
  open();
}
export function disconnect() {
  clearInterval(pingTimer);
  document.removeEventListener('visibilitychange', sendPresence);
  if (ws) { ws.onclose = null; try { ws.close(); } catch { /* */ } ws = null; }
  endLocal();
}
function open() {
  if (ws) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/voice`);
  ws.onopen = () => {
    backoff = 1000; clearInterval(pingTimer); pingTimer = setInterval(() => send({ t: 'ping' }), 25000);   // çevrimiçi kal (arka planda da)
    sendPresence();
    // yeniden bağlanınca: kopukken kaçan paylaşımları akış/bildirim tazelesin
    if (everOpened) window.dispatchEvent(new CustomEvent('caymaz:feed', { detail: { t: 'feed', resync: true } }));
    everOpened = true;
  };
  ws.onmessage = e => { try { handle(JSON.parse(e.data)); } catch { /* */ } };
  ws.onclose = () => { ws = null; clearInterval(pingTimer); setTimeout(open, backoff); backoff = Math.min(backoff * 2, 15000); };
  ws.onerror = () => { try { ws.close(); } catch { /* */ } };
}
function send(m) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); }

function handle(m) {
  switch (m.t) {
    case 'ring': return onRing(m);
    case 'calling': return onCalling(m);
    case 'joined': return onJoined(m);
    case 'peer_join': return onPeerJoin(m);
    case 'signal': return onSignal(m);
    case 'peer_left': return onPeerLeft(m);
    case 'rejected': return onRejected(m);
    case 'ended': return onEnded(m);
    case 'rec_request': return onRecRequest(m);
    case 'rec_consent': return onRecConsent(m);
    case 'rec_start': return onRecStart(m);
    case 'rec_stopped': return onRecStopped(m);
    case 'rec_denied': return onRecDenied(m);
    case 'feed': return window.dispatchEvent(new CustomEvent('caymaz:feed', { detail: m }));   // Şirketten Haberler: yeni paylaşım
    case 'live': return window.dispatchEvent(new CustomEvent('caymaz:live', { detail: m }));   // canlı yayın başladı / bitti
  }
}

// ---------- Arama başlatma ----------
export async function startCall(targetIds, names = {}, photos = {}, opts = {}) {
  if (call) { toast('Zaten bir görüşmedesiniz', 'err'); return; }
  targetIds = [...new Set(targetIds)].filter(Boolean);
  if (!targetIds.length) return;
  let video = !!opts.video && targetIds.length === 1;   // görüntülü arama yalnızca bire bir
  let stream;
  try { stream = await getMedia(video); }
  catch (e) {
    if (video) { try { stream = await getMedia(false); video = false; toast('Kameraya erişilemedi, sesli aranıyor', 'err'); } catch { toastError(new Error('Mikrofona erişilemedi (izin verildi mi?)')); return; } }
    else { toastError(new Error('Mikrofona erişilemedi (izin verildi mi?)')); return; }
  }
  send({ t: 'invite', to: targetIds, video });
  // call_id "calling" mesajıyla gelir; geçici arama ekranı
  call = { id: null, kind: targetIds.length > 1 ? 'grup' : 'bire_bir', video, peers: new Map(), local: stream,
    initiator: true, recording: false, isRecorder: false, names: { ...names }, photos: { ...photos } };
  call.localAnalyser = analyserFor(stream);
  showCallUI(video ? 'Görüntülü aranıyor…' : 'Aranıyor…');
  startRing('out');
}

// Ses (+ istenirse kamera) akışı al. Eko/uğultu önleme açık (yoksa karşı taraf kendi sesini yankı olarak duyar).
function getMedia(video) {
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  return navigator.mediaDevices.getUserMedia(video ? { audio, video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } } } : { audio });
}

export async function callPicker() {
  if (call) { toast('Zaten bir görüşmedesiniz', 'err'); return; }
  let users;
  try { users = await api.get('/api/voice/users'); } catch (err) { toastError(err); return; }
  const chosen = new Set();
  const list = h('div', { class: 'vc-picklist' });
  const draw = () => clear(list, users.map(u => pickRow(u, chosen, draw)));
  draw();
  modal({
    title: 'Sesli Görüşme Başlat',
    body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Birden fazla kişi seçerek grup görüşmesi yapabilirsiniz.'), list),
    actions: [{ label: 'Vazgeç' }, { label: 'Ara', class: 'primary', onClick: () => {
      if (!chosen.size) throw new Error('En az bir kişi seçin');
      const sel = users.filter(u => chosen.has(u.id));
      startCall([...chosen], Object.fromEntries(sel.map(u => [u.id, u.full_name])), Object.fromEntries(sel.map(u => [u.id, u.photo])));
    } }],
  });
}

// Kişi satırı: iOS tarzı sürgülü anahtar (checkbox yerine).
function pickRow(u, chosen, draw) {
  const on = chosen.has(u.id);
  return h('button', { class: `vc-pick ${on ? 'on' : ''}`, type: 'button', onclick: () => { on ? chosen.delete(u.id) : chosen.add(u.id); draw(); } },
    avatar(u, 'sm'), h('span', { class: 'grow' }, u.full_name),
    h('span', { class: `vc-dot ${u.online ? 'on' : ''}`, title: u.online ? 'Çevrimiçi' : 'Çevrimdışı' }),
    h('span', { class: `vc-switch ${on ? 'on' : ''}`, 'aria-hidden': 'true' }, h('span', { class: 'vc-switch-knob' })));
}

// ---------- Gelen arama (tam ekran, iPhone tarzı kaydırmalı aç/kapat) ----------
// Native (Capacitor) gelen arama tam-ekran bildirimi — uygulama arka planda/kilitliyken aramayı öne çıkarır
const nativeCall = () => { try { return (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform() && window.Capacitor.Plugins && window.Capacitor.Plugins.IncomingCall) || null; } catch { return null; } };

function onRing(m) {
  if (call || ring) { send({ t: 'reject', call_id: m.call_id }); return; }   // meşgul
  startRing('in');
  try { if (document.hidden) nativeCall()?.show({ name: (m.caller && m.caller.full_name) || 'Arama', video: !!m.video }); } catch { /* */ }
  const sub = m.kind === 'grup'
    ? t('Grup görüşmesi{extra}', { extra: m.members?.length ? ` · ${m.members.filter(Boolean).join(', ')}` : '' })
    : m.video ? 'Görüntülü görüşme · sizi arıyor…' : 'Sesli görüşme · sizi arıyor…';
  const reject = () => { send({ t: 'reject', call_id: m.call_id }); closeRing(); };
  const slider = makeSlider(() => accept(m), reject);
  const el = h('div', { class: `vc-ring ${isPhone() ? '' : 'compact'}`, style: { background: callBg() } },
    h('div', { class: 'vc-ring-top' },
      h('div', { class: 'vc-ring-sub' }, 'Gelen arama'),
      avatar(m.caller, 'huge'),
      h('div', { class: 'vc-ring-name' }, m.caller.full_name),
      h('div', { class: 'vc-ring-sub2' }, sub)),
    h('div', { class: 'vc-ring-bottom' }, slider,
      h('div', { class: 'vc-ring-btns' },
        h('button', { class: 'vc-rbtn reject', type: 'button', title: 'Reddet', onclick: reject }, iconSvg('decline')),
        h('button', { class: 'vc-rbtn accept', type: 'button', title: 'Kabul et', onclick: () => accept(m) }, iconSvg('accept')))));
  document.body.append(el);
  ring = { call_id: m.call_id, caller: m.caller, kind: m.kind, el };
}
function closeRing() { stopRing(); try { nativeCall()?.dismiss(); } catch { /* */ } if (ring) { ring.el.remove(); ring = null; } }

// iPhone tarzı kaydırma: ortadaki tutamağı sağa kaydır → aç, sola → kapat (fare ve dokunma).
function makeSlider(onAccept, onReject) {
  const knob = h('div', { class: 'vc-slide-knob' }, iconSvg('accept'));
  const hintR = h('span', { class: 'vc-slide-hint right' }, 'Açmak için kaydır →');
  const hintL = h('span', { class: 'vc-slide-hint left' }, '← Reddet');
  const track = h('div', { class: 'vc-slide' }, hintL, hintR, knob);
  let startX = 0, dx = 0, dragging = false, w = 0;
  const down = e => { dragging = true; startX = (e.touches ? e.touches[0].clientX : e.clientX); w = track.offsetWidth - knob.offsetWidth - 12; knob.style.transition = 'none'; e.preventDefault(); };
  const move = e => {
    if (!dragging) return;
    const x = (e.touches ? e.touches[0].clientX : e.clientX);
    dx = Math.max(-w / 2, Math.min(w / 2, x - startX));
    knob.style.transform = `translateX(${dx}px)`;
    knob.classList.toggle('go-accept', dx > w * 0.28);
    knob.classList.toggle('go-reject', dx < -w * 0.28);
  };
  const up = () => {
    if (!dragging) return; dragging = false;
    knob.style.transition = '';
    if (dx > w * 0.28) { onAccept(); return; }
    if (dx < -w * 0.28) { onReject(); return; }
    knob.style.transform = ''; dx = 0;
  };
  knob.addEventListener('mousedown', down); knob.addEventListener('touchstart', down, { passive: false });
  window.addEventListener('mousemove', move); window.addEventListener('touchmove', move, { passive: false });
  window.addEventListener('mouseup', up); window.addEventListener('touchend', up);
  return track;
}

async function accept(m) {
  stopRing();   // sesi HEMEN durdur (mikrofon izni/akış beklenirken zil çalmaya devam etmesin)
  let video = !!m.video;
  let stream;
  try { stream = await getMedia(video); }
  catch {
    if (video) { try { stream = await getMedia(false); video = false; toast('Kameraya erişilemedi, sesli katılıyorsunuz', 'err'); } catch { toastError(new Error('Mikrofona erişilemedi')); send({ t: 'reject', call_id: m.call_id }); closeRing(); return; } }
    else { toastError(new Error('Mikrofona erişilemedi')); send({ t: 'reject', call_id: m.call_id }); closeRing(); return; }
  }
  closeRing();
  call = { id: m.call_id, kind: m.kind, video, peers: new Map(), local: stream, initiator: false,
    recording: false, isRecorder: false, names: {}, photos: {} };
  call.localAnalyser = analyserFor(stream);
  if (m.caller) { call.names[m.caller.id] = m.caller.full_name; call.photos[m.caller.id] = m.caller.photo; }
  showCallUI('Bağlanıyor…');
  send({ t: 'accept', call_id: m.call_id });
}

// ---------- Arama durumu (sinyalleşme) ----------
function onCalling(m) {
  if (!call) return;
  call.id = m.call_id;
  for (const t of m.targets) { call.names[t.id] = t.name; if (t.photo) call.photos[t.id] = t.photo; }
  renderPeers();
  const offline = m.targets.filter(t => !t.online).map(t => t.name);
  setCallStatus(offline.length ? t('Aranıyor… ({names} çevrimdışı olabilir)', { names: offline.join(', ') }) : t('Aranıyor…'));
}
function onJoined(m) {   // ben yeni katıldım; mevcut üyeler bana offer gönderecek
  if (!call) return;
  call.id = m.call_id;
  for (const p of (m.peers || [])) { if (typeof p === 'object') { call.names[p.id] = p.name || call.names[p.id]; if (p.photo) call.photos[p.id] = p.photo; } }
  setCallStatus('Bağlanıyor…');
  renderPeers();
}
async function onPeerJoin(m) {   // yeni biri katıldı; ben mevcut üyeyim → ona offer başlatırım
  if (!call || call.id !== m.call_id) return;
  call.names[m.user_id] = m.name || call.names[m.user_id];
  if (m.photo) call.photos[m.user_id] = m.photo;
  const pc = makePeer(m.user_id);
  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    send({ t: 'signal', call_id: call.id, to: m.user_id, data: { sdp: pc.localDescription } });
  } catch (err) { console.warn('offer', err); }
  renderPeers();
}
async function onSignal(m) {
  if (!call || call.id !== m.call_id) return;
  let peer = call.peers.get(m.from);
  const pc = peer ? peer.pc : makePeer(m.from);
  const data = m.data || {};
  try {
    if (data.sdp) {
      await pc.setRemoteDescription(data.sdp);
      if (data.sdp.type === 'offer') {
        const ans = await pc.createAnswer();
        await pc.setLocalDescription(ans);
        send({ t: 'signal', call_id: call.id, to: m.from, data: { sdp: pc.localDescription } });
      }
    } else if (data.ice) {
      await pc.addIceCandidate(data.ice).catch(() => {});
    }
  } catch (err) { console.warn('signal', err); }
}
function onPeerLeft(m) {
  if (!call || call.id !== m.call_id) return;
  const p = call.peers.get(m.user_id);
  if (p) { try { p.pc.close(); } catch { /* */ } p.audio?.remove(); call.peers.delete(m.user_id); }
  renderPeers();
}
function onRejected(m) {
  if (!call || call.id !== m.call_id) return;
  const name = call.names[m.user_id] || 'Kişi';
  setCallStatus(t('{name} reddetti', { name }));
}
function onEnded(m) {
  if (ring && ring.call_id === m.call_id) return closeRing();
  if (call && call.id === m.call_id) endLocal(true);
}

function makePeer(uid) {
  const pc = new RTCPeerConnection(RTC);
  call.local.getTracks().forEach(t => pc.addTrack(t, call.local));
  // Görüntülü aramada medya elemanı <video> (sesi de çalar); sesli aramada gizli <audio>
  const media = call.video ? h('video', { class: 'vc-video', autoplay: true, playsinline: true }) : h('audio', { autoplay: true });
  const peer = { pc, audio: media, name: call.names[uid] };
  pc.ontrack = e => {
    media.srcObject = e.streams[0];
    peer.stream = e.streams[0];
    peer.analyser = analyserFor(e.streams[0]);
    e.streams[0].getVideoTracks().forEach(t => { t.onmute = t.onunmute = () => renderPeers(); });   // karşı taraf kamerasını aç/kapatınca
    renderPeers();
  };
  pc.onicecandidate = e => { if (e.candidate) send({ t: 'signal', call_id: call.id, to: uid, data: { ice: e.candidate } }); };
  pc.onconnectionstatechange = () => {   // her durum değişiminde arayüz güncellenir (Bağlanıyor→Bağlı)
    if (pc.connectionState === 'connected') { stopRing(); if (!call.startedAt) { call.startedAt = Date.now(); startTimer(); } }
    renderPeers();
  };
  if (!call.video) document.body.append(media);   // ses: gizli oynatıcı · video: renderPeers karoya yerleştirir
  call.peers.set(uid, peer);
  return pc;
}

// ---------- Arama arayüzü ----------
let ui = null, timerId = null;
function showCallUI(status) {
  ui = {};
  ui.title = h('div', { class: 'vc-ct-name' });
  ui.timer = h('div', { class: 'vc-ct-timer' }, status);
  ui.recBadge = h('span', { class: 'vc-rec', hidden: true }, h('span', { class: 'vc-rec-dot' }), 'Kaydediliyor');
  ui.stage = h('div', { class: 'vc-stage' });
  ui.selfBars = h('canvas', { class: 'vc-ring-viz', width: 66, height: 66 });
  ui.consent = h('div', { class: 'vc-consent', hidden: true });
  ui.muteBtn = ctlBtn('mic', 'Sesi kapat', toggleMute);
  ui.camBtn = call.video ? ctlBtn('video', 'Kamerayı kapat', toggleCam) : null;
  ui.flipBtn = call.video ? ctlBtn('flipCamera', 'Kamera değiştir (ön/arka)', flipCam) : null;
  ui.recBtn = ctlBtn('record', 'Görüşmeyi kaydet (onaylı)', onRecBtn);
  ui.endBtn = ctlBtn('end', 'Görüşmeyi bitir', hangup, 'end');
  if (call.video) { ui.selfVideo = h('video', { class: 'vc-selfvid', autoplay: true, muted: true, playsinline: true }); ui.selfVideo.srcObject = call.local; }
  const addBtn = h('button', { class: 'vc-top-btn', type: 'button', title: 'Görüşmeye kişi ekle', onclick: addPerson }, iconSvg('add'));
  const minBtn = h('button', { class: 'vc-top-btn', type: 'button', title: 'Küçült (görüşürken mesajlaş)', onclick: minimizeCall }, iconSvg('min'));
  // Küçültülmüş çubuk: konuşma sürerken uygulamayı kullanmak için; dokununca büyür
  ui.miniName = h('b'); ui.miniTimer = h('span', { class: 'vc-mini-timer' });
  ui.mini = h('div', { class: 'vc-mini' },
    h('span', { class: 'vc-mini-dot' }), h('div', { class: 'vc-mini-info' }, ui.miniName, ui.miniTimer),
    h('button', { class: 'vc-mini-end', type: 'button', title: 'Bitir', onclick: hangup }, iconSvg('end')));
  // Küçük çubuk sürüklenip ekranda taşınabilir; taşınmadan dokununca büyür
  let mdrag = null;
  ui.mini.addEventListener('pointerdown', e => {
    if (e.target.closest('.vc-mini-end') || (e.button != null && e.button !== 0)) return;
    const r = ui.el.getBoundingClientRect();
    mdrag = { dx: e.clientX - r.left, dy: e.clientY - r.top, x0: e.clientX, y0: e.clientY, moved: false };
    try { ui.mini.setPointerCapture(e.pointerId); } catch { /* */ }
  });
  ui.mini.addEventListener('pointermove', e => {
    if (!mdrag) return;
    if (!mdrag.moved && Math.hypot(e.clientX - mdrag.x0, e.clientY - mdrag.y0) < 6) return;
    mdrag.moved = true; ui.el.classList.add('dragging');
    applyMiniPos({ left: e.clientX - mdrag.dx, top: e.clientY - mdrag.dy });
  });
  const endMiniDrag = e => {
    if (!mdrag) return;
    const moved = mdrag.moved; mdrag = null; ui.el.classList.remove('dragging');
    try { ui.mini.releasePointerCapture(e.pointerId); } catch { /* */ }
    if (moved) { try { localStorage.setItem('caymaz.callMiniPos', JSON.stringify(miniPos)); } catch { /* */ } }
    else restoreCall();
  };
  ui.mini.addEventListener('pointerup', endMiniDrag);
  ui.mini.addEventListener('pointercancel', endMiniDrag);
  const selfBlock = call.video
    ? h('div', { class: 'vc-self vc-self-video' }, ui.selfVideo, h('span', { class: 'vc-self-label' }, 'Siz'))
    : h('div', { class: 'vc-self' }, h('div', { class: 'vc-self-av' }, ui.selfBars, avatar(ctx.user, 'sm')), h('span', { class: 'vc-self-label' }, 'Siz'));
  ui.el = h('div', { class: `vc-call ${isPhone() ? '' : 'compact'} ${call.video ? 'vc-has-video' : ''}`, style: { background: callBg() } },
    h('div', { class: 'vc-call-top' }, minBtn,
      h('div', { class: 'vc-ct-mid' }, ui.title, ui.timer, ui.recBadge), addBtn),
    ui.stage,
    ui.consent,
    selfBlock,
    h('div', { class: 'vc-controls' }, ui.muteBtn, ui.camBtn, ui.flipBtn, ui.recBtn, ui.endBtn),
    ui.mini);
  document.body.append(ui.el);
  if (!isPhone()) bigWindowDrag();
  window.addEventListener('beforeunload', beforeUnload);   // F5 / sekme kapatmada uyar
  renderPeers();
  startBars();
}
function ctlBtn(icon, title, onclick, cls = '') {
  const b = h('button', { class: `vc-ctl ${cls}`, type: 'button', title, onclick }, iconSvg(icon));
  b._icon = icon;
  return b;
}
function beforeUnload(e) { if (call) { e.preventDefault(); e.returnValue = 'Görüşme sürüyor; sayfadan ayrılırsanız görüşme kapanır.'; return e.returnValue; } }

function setCallStatus(t) { if (ui && !call?.startedAt) ui.timer.textContent = t; }
function startTimer() {
  if (timerId) return;
  const upd = () => {
    if (!call?.startedAt || !ui) return;
    const s = Math.floor((Date.now() - call.startedAt) / 1000);
    const t = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    ui.timer.textContent = t;
    if (ui.miniTimer) ui.miniTimer.textContent = t;
  };
  upd(); timerId = setInterval(upd, 1000);
}
function stopTimer() { if (timerId) { clearInterval(timerId); timerId = null; } }

function renderPeers() {
  if (!ui || !call) return;
  const ids = new Set([...call.peers.keys(), ...Object.keys(call.names).map(Number)]);
  ids.delete(ctx.user.id);
  const list = [...ids];
  ui.title.textContent = call.kind === 'grup'
    ? t('Grup · {n} kişi', { n: list.length }) : (call.names[list[0]] || (call.video ? t('Görüntülü görüşme') : t('Sesli görüşme')));
  if (ui.miniName) ui.miniName.textContent = ui.title.textContent;
  if (call.video) return renderVideoPeers(list);
  ui.stage.className = `vc-stage n${Math.min(list.length, 4)}`;
  if (!list.length) { clear(ui.stage, h('div', { class: 'vc-peer-empty' }, 'Katılım bekleniyor…')); return; }
  clear(ui.stage, list.map((uid, i) => {
    const p = call.peers.get(uid);
    const state = p ? p.pc.connectionState : 'ringing';
    const connected = state === 'connected';
    const sz = list.length === 1 ? 268 : 224;   // halka canvas boyutu (avatardan belirgin büyük → çubuklar çerçeve DIŞINDA)
    const canvas = h('canvas', { class: 'vc-ring-viz', width: sz, height: sz });
    if (p) p.canvas = canvas;
    return h('div', { class: `vc-tile ${connected ? 'on' : ''}` + (list.length === 3 && i === 0 ? ' lead' : ''), style: { animationDelay: `${i * 0.08}s` } },
      h('div', { class: 'vc-tile-av' }, canvas, avatar({ full_name: call.names[uid] || 'Kişi', photo: call.photos[uid] }, 'huge')),
      h('div', { class: 'vc-tile-name' }, call.names[uid] || 'Kişi'),
      h('div', { class: 'vc-tile-state' }, connected ? 'Bağlı' : state === 'ringing' ? 'Aranıyor…' : 'Bağlanıyor…'));
  }));
  if (list.some(uid => call.peers.get(uid)?.pc.connectionState === 'connected') && !call.startedAt) { call.startedAt = Date.now(); startTimer(); stopRing(); }
}
function toggleMute() {
  if (!call) return;
  const t = call.local.getAudioTracks()[0]; if (!t) return;
  t.enabled = !t.enabled;
  ui.muteBtn.classList.toggle('off', !t.enabled);
  ui.muteBtn.replaceChildren(iconSvg(t.enabled ? 'mic' : 'micOff'));
}
async function flipCam() {
  if (!call || !call.video) return;
  const cur = call.local.getVideoTracks()[0];
  const curFacing = (cur && cur.getSettings && cur.getSettings().facingMode) || call.facing || 'user';
  const next = curFacing === 'environment' ? 'user' : 'environment';
  try {
    const ns = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: next }, width: { ideal: 1280 }, height: { ideal: 720 } } });
    const nt = ns.getVideoTracks()[0];
    if (!nt) return;
    if (cur) nt.enabled = cur.enabled;
    call.peers.forEach(p => { const s = p.pc.getSenders().find(x => x.track && x.track.kind === 'video'); if (s) s.replaceTrack(nt).catch(() => {}); });
    if (cur) { try { call.local.removeTrack(cur); } catch { /* */ } cur.stop(); }
    call.local.addTrack(nt);
    call.facing = next;
    if (ui.selfVideo) ui.selfVideo.srcObject = call.local;
  } catch (e) { toast('Kamera değiştirilemedi', 'err'); }
}
function toggleCam() {
  if (!call) return;
  const t = call.local.getVideoTracks()[0]; if (!t) return;
  t.enabled = !t.enabled;
  if (ui.camBtn) { ui.camBtn.classList.toggle('off', !t.enabled); ui.camBtn.replaceChildren(iconSvg(t.enabled ? 'video' : 'videoOff')); ui.camBtn.title = t.enabled ? 'Kamerayı kapat' : 'Kamerayı aç'; }
  if (ui.el) ui.el.classList.toggle('vc-self-off', !t.enabled);
}

// Görüntülü arama karo düzeni: karşı tarafın videosu büyük, kamera kapalıysa avatar
function renderVideoPeers(list) {
  ui.stage.className = `vc-stage vc-vstage n${Math.min(list.length, 4)}`;
  if (!list.length) { clear(ui.stage, h('div', { class: 'vc-peer-empty' }, 'Katılım bekleniyor…')); return; }
  clear(ui.stage, list.map(uid => {
    const p = call.peers.get(uid);
    const state = p ? p.pc.connectionState : 'ringing';
    const connected = state === 'connected';
    const hasVideo = !!(p && p.stream && p.stream.getVideoTracks().some(t => t.readyState === 'live' && !t.muted));
    return h('div', { class: `vc-vtile ${connected ? 'on' : ''} ${hasVideo ? '' : 'novideo'}` },
      p ? p.audio : null,
      h('div', { class: 'vc-vtile-av' }, avatar({ full_name: call.names[uid] || 'Kişi', photo: call.photos[uid] }, 'huge')),
      h('div', { class: 'vc-vtile-foot' }, h('span', { class: 'vc-vtile-name' }, call.names[uid] || 'Kişi'),
        connected ? null : h('span', { class: 'vc-vtile-state' }, state === 'ringing' ? 'Aranıyor…' : 'Bağlanıyor…')));
  }));
  if (list.some(uid => call.peers.get(uid)?.pc.connectionState === 'connected') && !call.startedAt) { call.startedAt = Date.now(); startTimer(); stopRing(); }
}
async function addPerson() {
  if (!call) return;
  let users;
  try { users = await api.get('/api/voice/users'); } catch (err) { return toastError(err); }
  const already = new Set([ctx.user.id, ...call.peers.keys(), ...Object.keys(call.names).map(Number)]);
  users = users.filter(u => !already.has(u.id));
  if (!users.length) { toast('Eklenecek başka kişi yok', 'err'); return; }
  const chosen = new Set();
  const list = h('div', { class: 'vc-picklist' });
  const draw = () => clear(list, users.map(u => pickRow(u, chosen, draw)));
  draw();
  modal({
    title: 'Görüşmeye Kişi Ekle',
    body: h('div', null, h('p', { class: 'small muted', style: { marginTop: 0 } }, 'Seçtiğiniz kişiler bu görüşmeye davet edilir.'), list),
    actions: [{ label: 'Vazgeç' }, { label: 'Ekle', class: 'primary', onClick: () => {
      if (!chosen.size) throw new Error('En az bir kişi seçin');
      chosen.forEach(id => { const u = users.find(x => x.id === id); call.names[id] = u?.full_name; call.photos[id] = u?.photo; });
      call.kind = 'grup';
      send({ t: 'add', call_id: call.id, to: [...chosen] });
      renderPeers();
    } }],
  });
}
let miniPos = null;
function loadMiniPos() { try { return JSON.parse(localStorage.getItem('caymaz.callMiniPos') || 'null'); } catch { return null; } }
function applyMiniPos(p) {
  if (!ui) return;
  miniPos = p;
  const el = ui.el;
  if (!p || typeof p.left !== 'number') return;
  const w = el.offsetWidth || 220, hh = el.offsetHeight || 54;
  el.style.left = `${Math.min(Math.max(6, p.left), window.innerWidth - w - 6)}px`;
  el.style.top = `${Math.min(Math.max(6, p.top), window.innerHeight - hh - 6)}px`;
  el.style.right = 'auto'; el.style.bottom = 'auto';
}
// Bilgisayarda köşe penceresi: boş bir yerinden tutulup taşınır (konum hatırlanır), çift tıklayınca küçülür.
// Düğmeler, video ve kayıt onayı kutusu sürüklemeyi başlatmaz.
const BIG_POS = 'caymaz.callPos';
function placeWindow(el, p) {
  if (!el || !p || typeof p.left !== 'number') return;
  const w = el.offsetWidth || 340, hh = el.offsetHeight || 420;
  el.style.left = `${Math.min(Math.max(6, p.left), window.innerWidth - w - 6)}px`;
  el.style.top = `${Math.min(Math.max(6, p.top), window.innerHeight - hh - 6)}px`;
  el.style.right = 'auto'; el.style.bottom = 'auto';
}
function bigWindowDrag() {
  const el = ui.el;
  const skip = e => el.classList.contains('minimized') || !!e.target.closest('button, a, input, video, .vc-consent');
  let d = null;
  el.addEventListener('pointerdown', e => {
    if (skip(e) || (e.button != null && e.button !== 0)) return;
    const r = el.getBoundingClientRect();
    d = { dx: e.clientX - r.left, dy: e.clientY - r.top, x0: e.clientX, y0: e.clientY, moved: false, id: e.pointerId };
    try { el.setPointerCapture(e.pointerId); } catch { /* */ }   // hızlı çekişte imleç pencereden çıksa da olaylar gelsin
  });
  el.addEventListener('pointermove', e => {
    if (!d) return;
    if (!d.moved) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return;
      d.moved = true; el.classList.add('dragging');
    }
    placeWindow(el, { left: e.clientX - d.dx, top: e.clientY - d.dy });
  });
  const end = () => {
    if (!d) return;
    const moved = d.moved; d = null; el.classList.remove('dragging');
    if (moved) { try { localStorage.setItem(BIG_POS, JSON.stringify({ left: el.offsetLeft, top: el.offsetTop })); } catch { /* */ } }
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  el.addEventListener('dblclick', e => { if (!skip(e)) { e.preventDefault(); minimizeCall(); } });
  try { placeWindow(el, JSON.parse(localStorage.getItem(BIG_POS) || 'null')); } catch { /* */ }
}
function minimizeCall() { if (!ui) return; ui.el.classList.add('minimized'); const p = loadMiniPos(); if (p) applyMiniPos(p); }
function restoreCall() {
  if (!ui) return;
  ui.el.classList.remove('minimized');
  const s = ui.el.style; s.left = s.top = s.right = s.bottom = '';   // tam ekran/köşe CSS'i geri gelsin
  if (!isPhone()) { try { placeWindow(ui.el, JSON.parse(localStorage.getItem(BIG_POS) || 'null')); } catch { /* */ } }   // bilgisayarda taşındığı yere
}
function hangup() { if (call) { send({ t: 'end', call_id: call.id }); endLocal(true); } }

// ---------- Kayıt (onaylı) ----------
function onRecBtn() {
  if (!call) return;
  if (!call.recording) requestRecording();
  else if (call.recOwner) stopRecording();   // yalnızca kaydı başlatan durdurabilir
}
function requestRecording() {
  if (!call || call.recording) return;
  call.recOwner = true;   // bu kullanıcı kaydı başlatan
  send({ t: 'rec_request', call_id: call.id });
  setCallStatus('Kayıt için onay bekleniyor…');
}
function stopRecording() {
  if (!call || !call.recording || !call.recOwner) return;
  send({ t: 'rec_stop', call_id: call.id });   // herkese "kaydı durdur" yayınlanır
}
function onRecRequest(m) {
  if (!call || call.id !== m.call_id || call.recording) return;
  const answer = ok => { send({ t: 'rec_consent', call_id: call.id, ok }); ui.consent.hidden = true; clear(ui.consent); };
  clear(ui.consent, h('div', { class: 'vc-consent-card' },
    h('div', { class: 'vc-consent-title' }, h('b', null, m.by_name || 'Karşı taraf'), ' görüşmeyi kaydetmek istiyor'),
    h('div', { class: 'vc-consent-row' },
      h('button', { class: 'vc-consent-btn reject', type: 'button', title: 'Reddet', onclick: () => answer(false) }, iconSvg('decline')),
      h('div', { class: 'vc-consent-av' }, avatar({ full_name: m.by_name || '', photo: call.photos[m.by] }, 'lg')),
      h('button', { class: 'vc-consent-btn accept', type: 'button', title: 'Onayla', onclick: () => answer(true) }, iconSvg('accept'))),
    h('div', { class: 'vc-consent-hint' }, 'Solda reddet · sağda onayla')));
  ui.consent.hidden = false;
}
function onRecConsent(m) { /* bilgi amaçlı; rec_start gelince kayıt başlar */ }
function onRecDenied(m) { if (call) { setCallStatus('Kayıt reddedildi'); toast('Bir katılımcı kaydı reddetti', 'err'); } }
function onRecStart(m) {
  if (!call || call.id !== m.call_id) return;
  call.recording = true;
  ui.recBadge.hidden = false;
  ui.recBtn.classList.add('on');
  if (call.recOwner) { ui.recBtn.title = 'Kaydı durdur'; ui.recBtn.replaceChildren(iconSvg('stop')); }
  else { ui.recBtn.disabled = true; ui.recBtn.title = 'Görüşme kaydediliyor'; }
  startOwnRecorder();   // her katılımcı KENDİ mikrofonunu kaydeder (taze mikrofon akışı, iOS'ta güvenilir)
}
function onRecStopped(m) {
  if (!call || call.id !== m.call_id) return;
  const rec = call.recorder?.rec;
  if (rec && rec.state !== 'inactive') { try { rec.stop(); } catch { /* onstop yükler + akışı durdurur */ } }
  call.recorder = null; call.recording = false; call.recOwner = false;
  if (ui) {
    ui.recBadge.hidden = true;
    ui.recBtn.classList.remove('on'); ui.recBtn.disabled = false;
    ui.recBtn.title = 'Görüşmeyi kaydet (onaylı)'; ui.recBtn.replaceChildren(iconSvg('record'));
  }
  toast('Kayıt durduruldu, metne çevriliyor…', 'success');
}

async function startOwnRecorder() {
  if (call.recorder) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('Bu tarayıcı ses kaydını desteklemiyor', 'err'); return; }
  // Toplantı/bas-konuş ile aynı yöntem: KAYIT için TAZE bir mikrofon akışı al (WebRTC'ye bağlı akış iOS'ta boş kaydediyor).
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
  catch { toast('Kayıt için mikrofona erişilemedi', 'err'); return; }
  const mime = pickMime();
  let rec;
  try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); }
  catch (err) { stream.getTracks().forEach(t => t.stop()); console.warn('recorder', err); toast('Kayıt başlatılamadı', 'err'); return; }
  const chunks = [];
  rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
  rec.onstop = () => { stream.getTracks().forEach(t => t.stop()); uploadRecording(new Blob(chunks, { type: rec.mimeType || mime }), call?.id || lastCallId); };
  rec.start(1000);
  call.recorder = { rec, chunks, stream };
}
function pickMime() {
  for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/aac']) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}
async function uploadRecording(blob, cid) {
  cid = cid || call?.id || lastCallId;
  if (!cid || !blob || blob.size < 2000) return;
  const ext = (blob.type.includes('ogg') && 'ogg') || (blob.type.includes('mp4') && 'm4a') || 'webm';
  const fd = new FormData();
  fd.append('file', blob, `gorusme-${cid}.${ext}`);
  try {
    const r = await fetch(`/api/voice/calls/${cid}/recording`, { method: 'POST', body: fd, credentials: 'same-origin' });
    if (r.ok) toast('Görüşme kaydı yüklendi, metne çevriliyor…', 'success');
  } catch { /* sessiz */ }
}

// ---------- Bitiş / temizlik ----------
let lastCallId = null;
function endLocal(fromRemote) {
  stopRing();
  if (!call) { closeRing(); return; }
  lastCallId = call.id;
  const peer = [...Object.keys(call.names).map(Number), ...call.peers.keys()].find(id => id !== ctx.user.id);
  setTimeout(() => window.dispatchEvent(new CustomEvent('voice:callended', { detail: { peer, call_id: call ? call.id : lastCallId } })), 300);
  stopBars(); stopTimer();
  window.removeEventListener('beforeunload', beforeUnload);
  const rec = call.recorder?.rec;
  const finish = () => {
    call.peers.forEach(p => { try { p.pc.close(); } catch { /* */ } p.audio?.remove(); });
    try { call.local.getTracks().forEach(t => t.stop()); } catch { /* */ }
    if (ui) { ui.el.remove(); ui = null; }
    call = null;
  };
  if (rec && rec.state !== 'inactive') {
    const chunks = call.recorder.chunks, mime = rec.mimeType, cid = call.id, rstream = call.recorder.stream;
    rec.onstop = () => { try { rstream?.getTracks().forEach(t => t.stop()); } catch { /* */ } uploadRecording(new Blob(chunks, { type: mime }), cid); finish(); };
    try { rec.stop(); } catch { finish(); }
  } else finish();
  if (fromRemote) playEvent('offline');
}

// ---------- Görüşmelerim ----------
export async function renderHistory(view, params, context) {
  ctx = context;
  if (params[0]) return renderDetail(view, Number(params[0]));
  return _historyList(view);
}

// Görüşme detayı: ayrı (bağımsız) sayfa olarak da açılabilir (#/voice-call/{id}).
export async function renderCall(view, cid, context) {
  ctx = context;
  return renderDetail(view, cid);
}

async function _historyList(view) {
  let calls;
  try { calls = await api.get('/api/voice/calls'); } catch (err) { clear(view, h('div', { class: 'card empty' }, err.message)); return; }
  const outcome = c => (c.status === 'BITTI' ? ['Görüşüldü', 'green'] : c.status === 'KACIRILDI' ? ['Cevapsız', 'red'] : c.status === 'DEVAM' ? ['Sürüyor', 'blue'] : ['—', 'gray']);
  clear(view, pageHead('Görüşmelerim', { back: '#/', sub: 'Sesli görüşme geçmişi' }),
    h('div', { class: 'filters' }, h('div', { class: 'spacer' }), h('button', { class: 'btn primary', type: 'button', onclick: callPicker }, '📞 Yeni Görüşme')),
    calls.length ? h('div', { class: 'card table-wrap' }, h('table', { class: 'table' },
      h('thead', null, h('tr', null, h('th', null, 'Kişiler'), h('th', null, 'Yön'), h('th', null, 'Tarih'), h('th', null, 'Süre'), h('th', null, 'Durum'), h('th', null, 'Kayıt'))),
      h('tbody', null, calls.map(c => {
        const [lbl, tone] = outcome(c);
        const others = c.participants.filter(p => p.user_id !== ctx.user.id);
        return h('tr', { class: 'clickable', onclick: () => { location.hash = `#/voice-call/${c.id}`; } },
          h('td', null, h('div', { class: 'vc-row-people' }, others.slice(0, 4).map(p => avatar(p, 'sm')),
            h('span', null, others.map(p => p.full_name).join(', ') || '—'))),
          h('td', { class: 'small' }, c.initiator_id === ctx.user.id ? '→ Giden' : '← Gelen'),
          h('td', { class: 'small' }, fmtDateTime(c.started_at)),
          h('td', { class: 'small' }, c.seconds ? fmtDuration(c.seconds) : '—'),
          h('td', null, h('span', { class: `badge ${tone}` }, lbl)),
          h('td', null, c.recorded ? h('span', { class: 'badge blue' }, c.process_status === 'TAMAM' ? 'Metin var' : c.process_status === 'ISLENIYOR' ? 'İşleniyor' : 'Kayıt') : h('span', { class: 'muted' }, '—')));
      }))))
      : h('div', { class: 'card empty' }, 'Henüz görüşme yok. “Yeni Görüşme” ile arayabilirsiniz.'));
}

const mmss = s => `${String(Math.floor((s || 0) / 60)).padStart(2, '0')}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`;
let audioEl = null;

async function renderDetail(view, cid) {
  let c;
  try { c = await api.get(`/api/voice/calls/${cid}`); } catch (err) { clear(view, h('div', { class: 'card empty' }, err.message)); return; }
  const reload = () => renderDetail(view, cid);
  const others = c.participants.filter(p => p.user_id !== ctx.user.id);
  const head = h('div', { class: 'card card-pad' }, h('dl', { class: 'hr-kv' },
    h('dt', null, 'Kişiler'), h('dd', null, c.participants.map(p => p.full_name).join(', ')),
    h('dt', null, 'Başlangıç'), h('dd', null, fmtDateTime(c.started_at)),
    h('dt', null, 'Süre'), h('dd', null, c.seconds ? fmtDuration(c.seconds) : '—'),
    h('dt', null, 'Durum'), h('dd', null, c.status === 'BITTI' ? 'Görüşüldü' : c.status === 'KACIRILDI' ? 'Cevapsız' : c.status)));
  const parts = [head];

  // Kayıt oynatıcı
  audioEl = null;
  if (c.has_audio) {
    audioEl = h('audio', { class: 'vc-audio', controls: true, preload: 'metadata', src: `/api/voice/calls/${cid}/audio` });
    parts.push(h('div', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Kayıt'), audioEl));
  }
  if (c.summary) parts.push(h('div', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Özet'),
    h('div', { class: 'vc-summary pre' }, c.summary), h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Otomatik çıkarımsal özet (öne çıkan bölümler).')));

  if (c.recorded) {
    if (c.process_status === 'ISLENIYOR') parts.push(h('div', { class: 'card card-pad loading' }, 'Kayıt metne çevriliyor, konuşmacılar tanınıyor…'));
    else if (c.process_status === 'HATA') parts.push(h('div', { class: 'card empty' }, t('İşlenemedi: {err}', { err: c.process_error || '' })));
    else if (c.segments?.length) { parts.push(speakersCard(c, cid, reload)); parts.push(transcriptCard(c)); }
    else if (c.process_status === 'TAMAM') parts.push(h('div', { class: 'card empty' }, 'Kayıtta anlaşılır konuşma bulunamadı.'));
    else parts.push(h('div', { class: 'card empty' }, 'Kayıt onaylandı ama ses dosyası alınamadı (tarayıcı kaydı desteklemiyor olabilir).'));
  } else {
    parts.push(h('div', { class: 'card empty' }, 'Bu görüşme kaydedilmedi (kayıt tüm katılımcıların onayını gerektirir).'));
  }
  clear(view, pageHead('Görüşme Detayı', { back: '#/my-voice-calls', sub: others.map(p => p.full_name).join(', ') || 'Sesli görüşme' }), ...parts);
}

// Konuşmacılar: tanınanların adı gelir; tanınmayanlar "Kişi N" — arayüzden kişiye atanır (atayınca ses profili öğrenilir).
function speakersCard(c, cid, reload) {
  const opts = c.assignable || [];
  const row = sp => {
    const known = !!sp.user_id;
    const sel = h('select', { class: 'input vc-assign' },
      h('option', { value: '' }, known ? 'Atamayı kaldır' : 'Kişi seç…'),
      opts.map(u => h('option', { value: u.id, selected: u.id === sp.user_id }, u.full_name)));
    sel.addEventListener('change', async () => {
      try { await api.post(`/api/voice/calls/${cid}/speakers/${sp.id}/assign`, { user_id: sel.value ? Number(sel.value) : null }); toast('Konuşmacı güncellendi'); reload(); }
      catch (err) { toastError(err); }
    });
    return h('div', { class: 'vc-spk' },
      avatar({ full_name: sp.label, photo: (opts.find(u => u.id === sp.user_id) || {}).photo }, 'sm'),
      h('div', { class: 'vc-spk-info' },
        h('b', null, sp.label),
        h('small', { class: 'muted' }, t('{time} konuşma{how}', { time: mmss(sp.seconds), how: known ? (sp.auto ? t(' · otomatik tanındı') : t(' · elle atandı')) : t(' · tanınmadı') }))),
      sel);
  };
  return h('div', { class: 'card card-pad' },
    h('h3', { style: { marginTop: 0 } }, t('Konuşmacılar ({n})', { n: c.speakers.length })),
    h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Tanınmayan konuşmacıyı kişiye atayın; sistem o kişinin sesini öğrenir ve sonraki görüşmelerde tekrar sormaz.'),
    h('div', { class: 'vc-spk-list' }, c.speakers.map(row)));
}

function transcriptCard(c) {
  const seek = t => { if (audioEl) { try { audioEl.currentTime = t; audioEl.play().catch(() => {}); } catch { /* */ } } };
  return h('div', { class: 'card card-pad' }, h('h3', { style: { marginTop: 0 } }, 'Görüşme metni'),
    h('div', { class: 'vc-transcript' }, c.segments.map(s => h('div', { class: 'vc-seg' },
      h('button', { class: 'vc-seg-time', type: 'button', title: 'Kayıtta bu ana git', onclick: () => seek(s.t0) }, mmss(s.t0)),
      h('span', { class: 'vc-seg-who' }, s.speaker_label || 'Konuşmacı'),
      h('span', { class: 'vc-seg-text' }, s.text)))));
}
