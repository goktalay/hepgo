// Ekran paylaşımı izleyici (bağımsız /s/{code} sayfası). rrweb ile canlı yansıma + imleç/kontrol + sesli-görüntülü.
const code = location.pathname.split('/').filter(Boolean).pop();
const $ = id => document.getElementById(id);
const api = async (path, opts) => {
  const r = await fetch(path, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, ...opts });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || 'Hata');
  return d;
};

let replayer = null, hostDims = null, ws = null, canControl = false, myName = 'İzleyici';
let pc = null, localStream = null;

// ---- Kapı: bilgi + şifre ----
(async () => {
  try {
    const info = await api(`/api/screen/${code}`);
    if (!info.ok) { $('gate-title').textContent = 'Oturum bulunamadı'; $('gate-sub').textContent = 'Bağlantı sona ermiş olabilir.'; $('g-join').style.display = 'none'; return; }
    $('host-name').textContent = info.host_name || 'Paylaşan';
    if (info.needs_password) $('pw-wrap').style.display = 'block';
  } catch { /* */ }
})();

$('g-join').onclick = async () => {
  $('g-err').textContent = '';
  myName = ($('g-name').value || '').trim() || 'İzleyici';
  try {
    const r = await api(`/api/screen/${code}/auth`, { method: 'POST', body: JSON.stringify({ password: $('g-pw').value || '', name: myName }) });
    canControl = !!r.control;
    $('gate').style.display = 'none'; $('app').style.display = 'flex';
    $('host-name').textContent = r.host_name || 'Paylaşan';
    connect(r.viewer_token);
  } catch (e) { $('g-err').textContent = e.message; }
};

function connect(vt) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/screen/${code}?role=viewer&vt=${encodeURIComponent(vt)}&name=${encodeURIComponent(myName)}`);
  const send = m => { try { if (ws.readyState === 1) ws.send(JSON.stringify(m)); } catch { /* */ } };
  ws.onopen = () => { $('status').textContent = 'bağlandı'; send({ t: 'rtc', kind: 'hello' }); send({ t: 'full' }); };
  ws.onclose = () => { $('status').textContent = 'bağlantı kapandı'; $('live-dot').classList.add('sv-off'); };
  ws.onmessage = async (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m.t === 'dom') feed(m.ev);
    else if (m.t === 'meta') { hostDims = m.dims; layout(); }
    else if (m.t === 'ready') { canControl = !!m.control; $('status').textContent = m.host_online ? 'canlı' : 'paylaşan bekleniyor…'; setupOverlay(send); }
    else if (m.t === 'host_online') $('status').textContent = 'canlı';
    else if (m.t === 'host_offline') { $('status').textContent = 'paylaşan ayrıldı'; $('live-dot').classList.add('sv-off'); }
    else if (m.t === 'ended') { $('status').textContent = 'paylaşım sona erdi'; $('live-dot').classList.add('sv-off'); }
    else if (m.t === 'rtc') await onRtc(m, send);
  };

  // ---- WebRTC: sesli/görüntülü ----
  async function ensurePc() {
    if (pc) return pc;
    pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
    pc.onicecandidate = ev => { if (ev.candidate) send({ t: 'rtc', kind: 'ice', data: ev.candidate }); };
    pc.ontrack = ev => {
      const track = ev.track;
      if (track.kind === 'video') { $('remote-cam').style.display = 'block'; $('remote-cam').srcObject = ev.streams[0]; }
      else { $('remote-audio').srcObject = ev.streams[0]; }
    };
    return pc;
  }
  async function startCall(withVideo) {
    try { localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: withVideo }); }
    catch { $('status').textContent = 'mikrofon/kamera izni gerekli'; return; }
    const p = await ensurePc();
    localStream.getTracks().forEach(tr => p.addTrack(tr, localStream));
    const offer = await p.createOffer(); await p.setLocalDescription(offer);
    send({ t: 'rtc', kind: 'offer', data: offer });
    $('btn-call').textContent = '🎙 Açık';
  }
  async function onRtc(m, send2) {
    const p = await ensurePc();
    if (m.kind === 'offer') {
      await p.setRemoteDescription(m.data);
      if (!localStream) { try { localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false }); localStream.getTracks().forEach(tr => p.addTrack(tr, localStream)); } catch { /* */ } }
      const ans = await p.createAnswer(); await p.setLocalDescription(ans); send({ t: 'rtc', kind: 'answer', data: ans });
    } else if (m.kind === 'answer') { await p.setRemoteDescription(m.data); }
    else if (m.kind === 'ice') { try { await p.addIceCandidate(m.data); } catch { /* */ } }
  }
  $('btn-call').onclick = () => startCall(false);
  $('btn-cam').style.display = ''; $('btn-cam').onclick = () => startCall(true);
}

// ---- rrweb canlı replay ----
function feed(ev) {
  if (!replayer) {
    replayer = new rrweb.Replayer([ev], { liveMode: true, root: $('stage'), mouseTail: false, UNSAFE_replayCanvas: false, insertStyleRules: [] });
    replayer.startLive();
    layout();
  } else {
    replayer.addEvent(ev);
  }
}

function layout() {
  const wrap = $('stage-wrap'), scaler = $('scaler');
  const hw = hostDims?.w || replayer?.iframe?.contentDocument?.documentElement?.clientWidth || 1280;
  const hh = hostDims?.h || 720;
  const iframe = replayer?.iframe;
  if (iframe) { iframe.style.width = hw + 'px'; iframe.style.height = hh + 'px'; iframe.style.border = '0'; }
  scaler.style.width = hw + 'px'; scaler.style.height = hh + 'px';
  const scale = Math.min(wrap.clientWidth / hw, wrap.clientHeight / hh, 1);
  scaler.style.transform = `scale(${scale})`;
  scaler.dataset.scale = scale;
}
window.addEventListener('resize', layout);

// ---- Kontrol / imleç ----
function setupOverlay(send) {
  const ov = $('overlay');
  ov.classList.toggle('readonly', !canControl);
  $('hint').textContent = canControl ? 'Tıklayarak / yazarak müdahale edebilir, imleçle yol gösterebilirsiniz.' : 'Yalnızca izliyorsunuz — imleçle yol gösterebilirsiniz.';
  const norm = e => {
    const r = ov.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) };
  };
  let lastMove = 0;
  ov.addEventListener('mousemove', e => { const now = Date.now(); if (now - lastMove < 60) return; lastMove = now; const n = norm(e); send({ t: 'cursor', x: n.x, y: n.y, name: myName }); });
  ov.addEventListener('click', e => { if (!canControl) return; const n = norm(e); send({ t: 'ctrl', a: 'click', x: n.x, y: n.y, name: myName }); });
  ov.addEventListener('dblclick', e => { if (!canControl) return; const n = norm(e); send({ t: 'ctrl', a: 'dblclick', x: n.x, y: n.y, name: myName }); });
  ov.addEventListener('wheel', e => { if (!canControl) return; e.preventDefault(); const n = norm(e); send({ t: 'ctrl', a: 'scroll', x: n.x, y: n.y, dy: e.deltaY }); }, { passive: false });
  window.addEventListener('keydown', e => {
    if (!canControl || $('gate').style.display !== 'none') return;
    if (e.key.length === 1 || e.key === 'Backspace' || e.key === 'Enter') send({ t: 'ctrl', a: 'key', key: e.key });
  });
}
