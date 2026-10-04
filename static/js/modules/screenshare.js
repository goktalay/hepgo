// Ekranı Paylaş (paylaşan taraf) — HEPGO uygulaması için uzaktan destek.
// Uygulama ekranı rrweb ile birebir yansıtılır; izleyici imleçle yol gösterir, izin verilirse tıklama/kaydırma/yazma
// ile müdahale eder; ayrıca sesli/görüntülü konuşulabilir (WebRTC). Paylaşan kendi ekran boyutunu bildirir (mobil dâhil).
import { api } from '../api.js';
import { clear, confirmDialog, field, h, modal, toast, toastError } from '../ui.js';

let active = null;   // tek oturum

function loadRrweb() {
  return window.rrweb ? Promise.resolve(window.rrweb) : new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = '/static/vendor/rrweb/rrweb.min.js';
    s.onload = () => res(window.rrweb); s.onerror = () => rej(new Error('Ekran bileşeni yüklenemedi'));
    document.head.append(s);
  });
}

const wsUrl = (code) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/screen/${code}?role=host`;

export async function startScreenShare(ctx, opts = {}) {   // opts.onStarted(sess): paylaşım başlayınca (ör. canlı destek sohbetine link gönder)
  if (active) { active.panel?.classList.add('flash'); setTimeout(() => active.panel?.classList.remove('flash'), 600); return; }
  const pw = h('input', { class: 'input', type: 'text', placeholder: '(isteğe bağlı)' });
  const ctrlCb = h('input', { type: 'checkbox', checked: true });
  modal({
    title: 'Ekranı Paylaş',
    body: h('div', null,
      h('p', { class: 'small muted' }, 'Uygulama ekranınız bir link üzerinden karşı tarafa birebir yansır. Bağlanan kişi imleçle yol gösterir, izin verirseniz müdahale edebilir ve sizinle sesli/görüntülü konuşabilir.'),
      field('Link şifresi', pw),
      h('label', { class: 'set-toggle' }, ctrlCb, h('span', null, h('b', null, 'Müdahaleye izin ver'), h('small', null, 'Karşı taraf tıklayıp yazabilir. Kapalıysa yalnızca izler ve yol gösterir.')))),
    actions: [{ label: 'Vazgeç' }, { label: 'Paylaşımı Başlat', class: 'primary', onClick: () => begin(ctx, pw.value.trim(), ctrlCb.checked, opts) }],
  });
}

async function begin(ctx, password, control, opts = {}) {
  let rrweb, sess;
  try { rrweb = await loadRrweb(); } catch (e) { toastError(e); return; }
  try { sess = await api.post('/api/screen', { password, control }); } catch (e) { toastError(e); return; }
  try { await opts.onStarted?.(sess); } catch (e) { toastError(e); }
  const ws = new WebSocket(wsUrl(sess.code));
  const state = { code: sess.code, ws, stopRecord: null, pc: null, localStream: null, remoteAudio: null, viewers: 0, panel: null };
  active = state;

  const send = m => { try { if (ws.readyState === 1) ws.send(JSON.stringify(m)); } catch { /* */ } };
  const sendMeta = () => send({ t: 'meta', dims: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 } });

  ws.onopen = () => {
    sendMeta();
    state.stopRecord = rrweb.record({
      emit: ev => send({ t: 'dom', ev }),
      recordCanvas: false, collectFonts: false, inlineStylesheet: true, maskAllInputs: false,
      sampling: { mousemove: false, scroll: 150, input: 'last' },
    });
  };
  window.addEventListener('resize', sendMeta);

  // Uzaktan imleç (karşı tarafın gösterdiği yer)
  const remoteCursor = h('div', { class: 'ss-remote-cursor', hidden: true }, h('span', { class: 'ss-rc-dot' }), h('span', { class: 'ss-rc-name' }));
  document.body.append(remoteCursor);
  const showCursor = (x, y, name) => {
    remoteCursor.hidden = false;
    remoteCursor.style.left = `${x * window.innerWidth}px`; remoteCursor.style.top = `${y * window.innerHeight}px`;
    remoteCursor.querySelector('.ss-rc-name').textContent = name || 'Destek';
  };

  const applyControl = (c) => {
    const px = Math.round(c.x * window.innerWidth), py = Math.round(c.y * window.innerHeight);
    const el = document.elementFromPoint(px, py);
    showCursor(c.x, c.y, c.name);
    if (!el) return;
    if (c.a === 'click' || c.a === 'dblclick') {
      const opts = { bubbles: true, cancelable: true, clientX: px, clientY: py, view: window };
      el.dispatchEvent(new MouseEvent('mousedown', opts));
      el.dispatchEvent(new MouseEvent('mouseup', opts));
      el.dispatchEvent(new MouseEvent('click', opts));
      if (c.a === 'dblclick') el.dispatchEvent(new MouseEvent('dblclick', opts));
      if (el.focus) try { el.focus(); } catch { /* */ }
    } else if (c.a === 'scroll') {
      const sc = el.closest('.set-detail, .table-wrap, .modal, [style*="overflow"]') || window;
      (sc === window ? window : sc).scrollBy(0, c.dy || 0);
    } else if (c.a === 'key') {
      const t = document.activeElement;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        if (c.key === 'Backspace') t.value = (t.value || '').slice(0, -1);
        else if (c.key && c.key.length === 1) t.value = (t.value || '') + c.key;
        t.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
  };

  ws.onmessage = async (e) => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m.t === 'viewer_join') { state.viewers++; drawPanel(); try { rrweb.record.takeFullSnapshot?.(true); } catch { /* */ } sendMeta(); }
    else if (m.t === 'viewer_left') { state.viewers = Math.max(0, state.viewers - 1); drawPanel(); }
    else if (m.t === 'ctrl') applyControl(m);
    else if (m.t === 'cursor') showCursor(m.x, m.y, m.name);
    else if (m.t === 'full') { try { rrweb.record.takeFullSnapshot?.(true); } catch { /* */ } }
    else if (m.t === 'rtc') await onRtc(m);
  };
  ws.onclose = () => stop(true);

  // ---- Sesli / görüntülü (WebRTC) ----
  async function ensurePc() {
    if (state.pc) return state.pc;
    const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
    state.pc = pc;
    pc.onicecandidate = ev => { if (ev.candidate) send({ t: 'rtc', to: state.lastViewer, kind: 'ice', data: ev.candidate }); };
    pc.ontrack = ev => {
      if (!state.remoteAudio) { state.remoteAudio = h('audio', { autoplay: true }); document.body.append(state.remoteAudio); }
      state.remoteAudio.srcObject = ev.streams[0];
    };
    return pc;
  }
  async function startCall(withVideo) {
    try {
      state.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: withVideo });
    } catch (e) { toast('Mikrofon/kamera izni gerekli', 'err'); return; }
    const pc = await ensurePc();
    state.localStream.getTracks().forEach(tr => pc.addTrack(tr, state.localStream));
    const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
    send({ t: 'rtc', to: state.lastViewer, kind: 'offer', data: offer });
    state.calling = true; drawPanel();
  }
  async function onRtc(m) {
    state.lastViewer = m.from || state.lastViewer;
    const pc = await ensurePc();
    if (m.kind === 'offer') {
      await pc.setRemoteDescription(m.data);
      if (!state.localStream) { try { state.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false }); state.localStream.getTracks().forEach(tr => pc.addTrack(tr, state.localStream)); } catch { /* */ } }
      const ans = await pc.createAnswer(); await pc.setLocalDescription(ans);
      send({ t: 'rtc', to: m.from, kind: 'answer', data: ans }); state.calling = true; drawPanel();
    } else if (m.kind === 'answer') { await pc.setRemoteDescription(m.data); }
    else if (m.kind === 'ice') { try { await pc.addIceCandidate(m.data); } catch { /* */ } }
  }

  // ---- Panel ----
  function drawPanel() {
    if (!state.panel) {
      state.panel = h('div', { class: 'ss-panel' });
      document.body.append(state.panel);
    }
    const link = `${location.origin}/s/${state.code}`;
    clear(state.panel,
      h('div', { class: 'ss-live' }, h('span', { class: 'ss-dot' }), 'Ekran paylaşılıyor'),
      h('div', { class: 'ss-row' }, h('input', { class: 'input ss-link', value: link, readonly: true, onclick: e => e.target.select() }),
        h('button', { class: 'btn sm', type: 'button', onclick: () => { navigator.clipboard?.writeText(link); toast('Link kopyalandı'); } }, 'Kopyala')),
      h('div', { class: 'ss-info' }, `${state.viewers} izleyici`, state.calling ? ' · 🎙 konuşma açık' : ''),
      h('div', { class: 'ss-row' },
        state.calling ? null : h('button', { class: 'btn sm', type: 'button', onclick: () => startCall(false) }, '🎙 Sesli'),
        state.calling ? null : h('button', { class: 'btn sm', type: 'button', onclick: () => startCall(true) }, '🎥 Görüntülü'),
        h('button', { class: 'btn sm danger', type: 'button', onclick: () => stop() }, 'Paylaşımı Durdur')));
  }
  drawPanel();

  async function stop(silent) {
    if (active !== state) return;
    active = null;
    try { state.stopRecord?.(); } catch { /* */ }
    window.removeEventListener('resize', sendMeta);
    try { send({ t: 'ended' }); } catch { /* */ }
    try { state.localStream?.getTracks().forEach(t => t.stop()); } catch { /* */ }
    try { state.pc?.close(); } catch { /* */ }
    try { ws.close(); } catch { /* */ }
    remoteCursor.remove(); state.remoteAudio?.remove(); state.panel?.remove();
    if (!silent) { try { await api.post(`/api/screen/${state.code}/end`, {}); } catch { /* */ } toast('Ekran paylaşımı durduruldu'); }
  }
  state.stop = stop;
}
