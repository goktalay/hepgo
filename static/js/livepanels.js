// Fabrika CANLI TEST panelleri — yüzen, sürüklenebilir, cihazı (kamera/mikrofon) açıp-kapatan küçük paneller.
//   (68) Yüz Tanıma canlı test: kamera + yüz çerçevesi + bulunan kişinin adı.
//   (69) Sesten Yazıya canlı: mikrofon + ses dalga grafiği + canlı metin.
//   (70) Konuşmacı Tanıma: mikrofon + dalga grafiği + eğitilmiş sesle kişi adı/resmi ya da "Tanımsız Kişi".
// Ortak altyapı: floatPanel() (sürüklenebilir yüzen kart) + waveform() (Web Audio canlı dalga).
// Panel kapatılınca onClose çağrılır → ilgili cihaz (getUserMedia akışı) durdurulur.
import { api } from './api.js';
import { h } from './ui.js';

let _styled = false;
function injectStyle() {
  if (_styled || document.getElementById('livepanel-style')) { _styled = true; return; }
  _styled = true;
  const st = document.createElement('style');
  st.id = 'livepanel-style';
  st.textContent = `
  .lp-panel{position:fixed;z-index:1200;width:380px;max-width:calc(100vw - 24px);background:var(--card,#fff);
    border:1px solid var(--line,#e5e7eb);border-radius:14px;box-shadow:0 18px 48px rgba(15,23,42,.30);overflow:hidden;
    font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
  .lp-head{display:flex;align-items:center;gap:10px;padding:10px 12px;cursor:grab;user-select:none;
    background:linear-gradient(135deg,#1e293b,#334155);color:#fff}
  .lp-head:active{cursor:grabbing}
  .lp-head-txt{flex:1;min-width:0}
  .lp-title{font-weight:600;font-size:14px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lp-sub{font-size:11px;opacity:.75;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .lp-x{border:none;background:rgba(255,255,255,.14);color:#fff;width:26px;height:26px;border-radius:7px;cursor:pointer;
    font-size:13px;line-height:1;flex:0 0 auto}
  .lp-x:hover{background:rgba(255,255,255,.28)}
  .lp-body{padding:12px}
  .lp-stage{position:relative;border-radius:10px;overflow:hidden;background:#0b1220;aspect-ratio:4/3}
  .lp-video{width:100%;display:block}
  .lp-overlay{position:absolute;inset:0;pointer-events:none}
  .lp-status{margin-top:9px;font-size:12px;color:var(--muted,#64748b);min-height:16px}
  .lp-status.err{color:#dc2626}
  .lp-status.ok{color:#16a34a}
  .lp-wave{width:100%;height:68px;display:block;background:#0b1220;border-radius:10px}
  .lp-transcript{margin-top:9px;font-size:14px;line-height:1.5;color:var(--fg,#0f172a);max-height:150px;overflow:auto;
    background:var(--bg2,#f8fafc);border:1px solid var(--line,#e5e7eb);border-radius:10px;padding:9px 11px;min-height:46px;white-space:pre-wrap}
  .lp-transcript .lp-partial{color:var(--muted,#94a3b8)}
  .lp-speaker{display:flex;align-items:center;gap:12px;margin-top:10px;padding:10px;border-radius:12px;
    background:var(--bg2,#f8fafc);border:1px solid var(--line,#e5e7eb)}
  .lp-speaker img{width:54px;height:54px;border-radius:50%;object-fit:cover;background:#e2e8f0;flex:0 0 auto}
  .lp-speaker .lp-sp-ph{width:54px;height:54px;border-radius:50%;background:#e2e8f0;display:flex;align-items:center;
    justify-content:center;font-size:24px;color:#94a3b8;flex:0 0 auto}
  .lp-sp-name{font-weight:600;font-size:15px}
  .lp-sp-meta{font-size:12px;color:var(--muted,#64748b)}
  .lp-face-ring{width:230px;height:230px;border-radius:50%;margin:4px auto 2px;padding:9px;box-sizing:border-box;
    background:conic-gradient(#22c55e 0deg,#334155 0deg);transition:background .25s}
  .lp-circ{width:100%;height:100%;border-radius:50%;overflow:hidden;background:#0b1220;position:relative}
  .lp-circ video{width:100%;height:100%;object-fit:cover;display:block;transform:scaleX(-1)}
  .lp-face-prompt{text-align:center;font-size:13px;color:var(--muted,#64748b);margin-top:6px;min-height:18px}
  .lp-dirs{display:flex;justify-content:center;gap:10px;margin-top:6px}
  .lp-dir{width:26px;height:26px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:13px;
    background:var(--bg2,#f1f5f9);color:#94a3b8}
  .lp-dir.done{background:#22c55e;color:#fff}
  .lp-prompt-box{font-size:16px;line-height:1.7;background:var(--bg2,#f8fafc);border:1px solid var(--line,#e5e7eb);
    border-radius:10px;padding:11px 13px;margin-top:4px}
  .lp-prompt-box .w{color:var(--muted,#94a3b8);transition:color .2s}
  .lp-prompt-box .w.ok{color:#16a34a;font-weight:600}
  `;
  document.head.append(st);
}

// ---- Sürüklenebilir yüzen kart. Dönüş: { el, body, setSub, close }. onClose: panel kapanınca (✕ ya da close()).
export function floatPanel({ title, sub = '', width = 380, onClose } = {}) {
  injectStyle();
  const subEl = h('div', { class: 'lp-sub' }, sub);
  const x = h('button', { class: 'lp-x', type: 'button', title: 'Kapat', 'aria-label': 'Kapat' }, '✕');
  const head = h('div', { class: 'lp-head' }, h('div', { class: 'lp-head-txt' }, h('div', { class: 'lp-title' }, title), subEl), x);
  const body = h('div', { class: 'lp-body' });
  const el = h('div', { class: 'lp-panel' }, head, body);
  el.style.width = `${width}px`;
  document.body.append(el);
  el.style.left = `${Math.max(12, window.innerWidth - width - 26)}px`;
  el.style.top = '86px';

  let closed = false;
  const close = () => { if (closed) return; closed = true; el.remove(); try { onClose && onClose(); } catch { /* yut */ } };
  x.addEventListener('click', close);
  head.addEventListener('mousedown', e => {
    if (e.target === x) return;
    e.preventDefault();
    const r = el.getBoundingClientRect(), ox = e.clientX - r.left, oy = e.clientY - r.top;
    const mm = ev => {
      el.style.left = `${Math.max(0, Math.min(ev.clientX - ox, window.innerWidth - 40))}px`;
      el.style.top = `${Math.max(0, Math.min(ev.clientY - oy, window.innerHeight - 40))}px`;
    };
    const mu = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); };
    window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu);
  });
  return { el, body, setSub: t => { subEl.textContent = t || ''; }, close };
}

function roundRect(c, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  c.beginPath(); c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
}

// ============================================================ (68) YÜZ TANIMA CANLI TEST
export async function openFaceTest() {
  injectStyle();
  const video = h('video', { class: 'lp-video', autoplay: '', playsinline: '' });
  video.muted = true;
  const overlay = h('canvas', { class: 'lp-overlay' });
  const status = h('div', { class: 'lp-status' }, 'Kamera başlatılıyor…');
  const panel = floatPanel({ title: 'Yüz Tanıma · Canlı Test', sub: 'Eğitilmiş yüzlerle eşleştirme', width: 380, onClose: stop });
  panel.body.append(h('div', { class: 'lp-stage' }, video, overlay), status);

  const ctx = overlay.getContext('2d');
  const grab = document.createElement('canvas');
  let stream = null, timer = null, busy = false, stopped = false;

  function stop() {
    stopped = true;
    if (timer) { clearInterval(timer); timer = null; }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  }
  const nameOf = f => f.user_name || f.person_name || f.family_name || f.visitor_name || null;

  function draw(res) {
    overlay.width = video.clientWidth; overlay.height = video.clientHeight;
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!res || !res.w) return;
    const sx = overlay.width / res.w, sy = overlay.height / res.h;
    ctx.textBaseline = 'middle';
    for (const f of res.faces || []) {
      const [bx, by, bw, bh] = f.box;
      const X = bx * sx, Y = by * sy, W = bw * sx, H = bh * sy;
      const nm = nameOf(f);
      const col = nm ? '#22c55e' : '#f59e0b';
      ctx.lineWidth = 3; ctx.strokeStyle = col;
      roundRect(ctx, X, Y, W, H, 9); ctx.stroke();
      const label = nm ? (f.score ? `${nm} · %${Math.round(f.score * 100)}` : nm) : 'Tanımsız Kişi';
      ctx.font = '600 13px system-ui, sans-serif';
      const tw = ctx.measureText(label).width + 14;
      const ty = Math.min(Y + H + 3, overlay.height - 22);
      ctx.fillStyle = col; roundRect(ctx, X, ty, tw, 21, 6); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.fillText(label, X + 7, ty + 11);
    }
  }

  async function tick() {
    if (stopped || busy) return;
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return;
    const scale = Math.min(1, 480 / vw);
    grab.width = Math.round(vw * scale); grab.height = Math.round(vh * scale);
    grab.getContext('2d').drawImage(video, 0, 0, grab.width, grab.height);
    const jpg = grab.toDataURL('image/jpeg', 0.72).split(',')[1];
    busy = true;
    try {
      const res = await api.post('/api/faces/recognize-frame', { jpg });
      if (stopped) return;
      draw(res);
      const n = (res.faces || []).length;
      const known = (res.faces || []).filter(nameOf).length;
      status.textContent = n ? `${n} yüz · ${known} tanındı` : 'Yüz aranıyor…';
      status.className = 'lp-status' + (n && known ? ' ok' : '');
    } catch (err) {
      if (!stopped) { status.textContent = 'Tanıma hatası: ' + ((err && err.message) || 'bağlantı'); status.className = 'lp-status err'; }
    } finally { busy = false; }
  }

  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false });
    video.srcObject = stream;
    await video.play().catch(() => {});
    status.textContent = 'Yüz aranıyor…';
    timer = setInterval(tick, 700);
  } catch (err) {
    status.textContent = 'Kamera açılamadı: ' + ((err && err.message) || err);
    status.className = 'lp-status err';
  }
  return panel;
}

// ---- Ortak ses altyapısı (69/70): mikrofon akışı + canlı dalga çizimi + parçalı (segment) kayıt döngüsü.
const _MR_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
function _mrType() {
  const t = (window.MediaRecorder && _MR_TYPES.find(x => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(x))) || '';
  return { type: t, ext: t.includes('ogg') ? 'ogg' : t.includes('mp4') ? 'm4a' : 'webm' };
}
async function _startMic() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = ac.createAnalyser(); analyser.fftSize = 1024;
  ac.createMediaStreamSource(stream).connect(analyser);
  return { stream, ac, analyser };
}
// Osiloskop çizimi; isStopped()=true olunca durur. Dönüş: stopDraw().
function _waveLoop(canvas, analyser, color, isStopped) {
  const ctx = canvas.getContext('2d');
  const data = new Uint8Array(analyser.fftSize);
  let raf = 0;
  const draw = () => {
    if (isStopped()) return;
    const W = canvas.clientWidth || 360, H = canvas.clientHeight || 68;
    if (canvas.width !== W) canvas.width = W;
    if (canvas.height !== H) canvas.height = H;
    analyser.getByteTimeDomainData(data);
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.beginPath();
    const step = W / data.length;
    for (let i = 0; i < data.length; i++) {
      const y = (data[i] / 255) * H, x = i * step;
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    }
    ctx.stroke();
    raf = requestAnimationFrame(draw);
  };
  raf = requestAnimationFrame(draw);
  return () => cancelAnimationFrame(raf);
}
// Sürekli mikrofonu ~segMs'lik bağımsız kayıt dosyalarına böler → her birini onBlob(blob, ext) ile yollar.
// (whisper akış değil; kısa parçalar hâlinde çeviri/eşleştirme yapılır.) Dönüş: stopSeg().
function _segmentLoop(stream, onBlob, segMs, isStopped) {
  const { type, ext } = _mrType();
  let mr = null, timer = 0;
  const startSeg = () => {
    if (isStopped() || !stream) return;
    const chunks = [];
    mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    mr.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    mr.onstop = () => {
      const blob = new Blob(chunks, { type: type || 'audio/webm' });
      if (!isStopped()) startSeg();                 // bir sonraki parçayı hemen başlat (boşluğu azalt)
      if (blob.size >= 1400) onBlob(blob, ext);     // çok küçük/sessiz parçayı atla
    };
    try { mr.start(); } catch { return; }
    timer = setTimeout(() => { try { if (mr && mr.state !== 'inactive') mr.stop(); } catch { /* yut */ } }, segMs);
  };
  startSeg();
  return () => { clearTimeout(timer); try { if (mr && mr.state !== 'inactive') mr.stop(); } catch { /* yut */ } };
}

// ============================================================ (69) SESTEN YAZIYA CANLI
export async function openSpeechToText() {
  injectStyle();
  const wave = h('canvas', { class: 'lp-wave' });
  const status = h('div', { class: 'lp-status' }, 'Mikrofon başlatılıyor…');
  const transcript = h('div', { class: 'lp-transcript' }, 'Konuşmaya başlayın…');
  const panel = floatPanel({ title: 'Sesten Yazıya · Canlı', sub: 'Mikrofon açık · konuşun, metne çevrilir', width: 410, onClose: stop });
  panel.body.append(wave, status, transcript);

  let stream = null, ac = null, analyser = null, stopDraw = null, stopSeg = null, stopped = false, finalText = '', pending = 0;
  function stop() {
    stopped = true;
    if (stopSeg) stopSeg();
    if (stopDraw) stopDraw();
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    try { ac && ac.close(); } catch { /* yut */ }
    ac = null;
  }
  const render = () => { transcript.textContent = finalText || (pending ? '…' : 'Konuşmaya başlayın…'); transcript.scrollTop = transcript.scrollHeight; };

  async function onBlob(blob, ext) {
    if (stopped) return;
    pending++; status.textContent = 'Çevriliyor…'; status.className = 'lp-status';
    try {
      const fd = new FormData(); fd.append('file', blob, `stt.${ext}`); fd.append('lang', 'tr');
      const r = await api.post('/api/system/dictate', fd);
      const txt = ((r && r.text) || '').trim();
      if (txt && !stopped) { finalText += (finalText ? ' ' : '') + txt; render(); }
    } catch (err) {
      if (!stopped) { status.textContent = 'Çeviri hatası: ' + ((err && err.message) || 'bağlantı'); status.className = 'lp-status err'; }
    } finally {
      pending = Math.max(0, pending - 1);
      if (!stopped && status.className !== 'lp-status err') { status.textContent = 'Dinleniyor…'; status.className = 'lp-status ok'; }
    }
  }

  try {
    ({ stream, ac, analyser } = await _startMic());
    stopDraw = _waveLoop(wave, analyser, '#38bdf8', () => stopped);
    stopSeg = _segmentLoop(stream, onBlob, 4500, () => stopped);
    status.textContent = 'Dinleniyor…'; status.className = 'lp-status ok';
  } catch (err) {
    status.textContent = 'Mikrofon açılamadı: ' + ((err && err.message) || err); status.className = 'lp-status err';
  }
  return panel;
}

// ============================================================ (70) KONUŞMACI TANIMA CANLI
export async function openSpeakerId() {
  injectStyle();
  const wave = h('canvas', { class: 'lp-wave' });
  const status = h('div', { class: 'lp-status' }, 'Mikrofon başlatılıyor…');
  const ph = h('div', { class: 'lp-sp-ph' }, '🎤');
  const nameEl = h('div', { class: 'lp-sp-name' }, '—');
  const metaEl = h('div', { class: 'lp-sp-meta' }, 'Konuşan bekleniyor');
  const card = h('div', { class: 'lp-speaker' }, ph, h('div', null, nameEl, metaEl));
  const panel = floatPanel({ title: 'Konuşmacı Tanıma · Canlı', sub: 'Eğitilmiş seslerle eşleştirme', width: 410, onClose: stop });
  panel.body.append(wave, status, card);

  let stream = null, ac = null, analyser = null, stopDraw = null, stopSeg = null, stopped = false, busy = false;
  function stop() {
    stopped = true;
    if (stopSeg) stopSeg();
    if (stopDraw) stopDraw();
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    try { ac && ac.close(); } catch { /* yut */ }
    ac = null;
  }
  function showPhoto(path) {
    if (path) {
      const img = h('img');
      img.src = `/api/files/${path}`;
      img.onerror = () => { card.replaceChild(ph, card.firstChild); };
      if (card.firstChild !== img) card.replaceChild(img, card.firstChild);
    } else if (card.firstChild !== ph) {
      card.replaceChild(ph, card.firstChild);
    }
  }
  async function onBlob(blob, ext) {
    if (stopped || busy) return;
    busy = true;
    try {
      const fd = new FormData(); fd.append('file', blob, `spk.${ext}`);
      const r = await api.post('/api/voice/identify-clip', fd);
      if (stopped) return;
      if (r && r.no_profiles) {
        status.textContent = 'Kayıtlı ses profili yok (önce ses eğitimi gerekir)'; status.className = 'lp-status err';
        nameEl.textContent = '—'; metaEl.textContent = 'Eğitilmiş ses yok'; showPhoto(null);
      } else if (r && r.matched) {
        nameEl.textContent = r.name || 'Kişi';
        metaEl.textContent = r.score != null ? `eşleşme %${Math.round(r.score * 100)}` : 'tanındı';
        showPhoto(r.photo);
        status.textContent = 'Tanındı'; status.className = 'lp-status ok';
      } else {
        nameEl.textContent = 'Tanımsız Kişi';
        metaEl.textContent = (r && r.short) ? 'çok kısa konuşma' : (r && r.score != null ? `en yakın %${Math.round(r.score * 100)}` : 'eşleşme yok');
        showPhoto(null);
        status.textContent = 'Dinleniyor…'; status.className = 'lp-status';
      }
    } catch (err) {
      if (!stopped) { status.textContent = 'Tanıma hatası: ' + ((err && err.message) || 'bağlantı'); status.className = 'lp-status err'; }
    } finally { busy = false; }
  }

  try {
    ({ stream, ac, analyser } = await _startMic());
    stopDraw = _waveLoop(wave, analyser, '#a78bfa', () => stopped);
    stopSeg = _segmentLoop(stream, onBlob, 4000, () => stopped);
    status.textContent = 'Dinleniyor…'; status.className = 'lp-status ok';
  } catch (err) {
    status.textContent = 'Mikrofon açılamadı: ' + ((err && err.message) || err); status.className = 'lp-status err';
  }
  return panel;
}

// ============================================================ YÜZ TANIMA EĞİTİMİ (iPhone Face ID tarzı)
// subject: {subject_type:'user'|'person'|'family', user_id?, person_id?, family_id?, name, onDone}
// Kamera açılır; başınızı çevirdikçe kafa açısı (yaw/pitch) kutularını kapsar, halka dolar; her kabul edilen
// karede sunucuya kare gönderilir, en büyük yüz embedding+kırpık olarak kişiye eğitim izi kaydedilir (sıkıştırılmış).
const _BUCKETS = ['center', 'left', 'right', 'up', 'down'];
const _NEED = 2;   // kutu başına hedef örnek
function _poseBucket(yaw, pitch) {
  if (pitch < -0.25) return 'up';
  if (pitch > 0.32) return 'down';
  if (yaw < -0.28) return 'left';
  if (yaw > 0.28) return 'right';
  return 'center';
}
export async function openFaceEnroll(subject) {
  injectStyle();
  const video = h('video', { autoplay: '', playsinline: '' }); video.muted = true;
  const ring = h('div', { class: 'lp-face-ring' }, h('div', { class: 'lp-circ' }, video));
  const prompt = h('div', { class: 'lp-face-prompt' }, 'Kamera başlatılıyor…');
  const dirIcons = { center: '●', left: '◀', right: '▶', up: '▲', down: '▼' };
  const dirs = {};
  const dirRow = h('div', { class: 'lp-dirs' }, _BUCKETS.map(b => (dirs[b] = h('div', { class: 'lp-dir', title: b }, dirIcons[b]))));
  const status = h('div', { class: 'lp-status' }, '');
  const panel = floatPanel({ title: 'Yüz Tanıma Eğitimi', sub: subject.name || '', width: 300, onClose: stop });
  panel.body.append(ring, dirRow, prompt, status);

  const grab = document.createElement('canvas');
  const counts = { center: 0, left: 0, right: 0, up: 0, down: 0 };
  let stream = null, timer = null, busy = false, stopped = false, added = 0, done = false;

  function stop() {
    stopped = true;
    if (timer) { clearInterval(timer); timer = null; }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  }
  function progress() { return _BUCKETS.reduce((s, b) => s + Math.min(counts[b], _NEED), 0) / (_NEED * _BUCKETS.length); }
  function refresh() {
    const p = progress();
    ring.style.background = `conic-gradient(#22c55e ${p * 360}deg, #334155 0deg)`;
    _BUCKETS.forEach(b => dirs[b].classList.toggle('done', counts[b] >= _NEED));
    const need = _BUCKETS.find(b => counts[b] < _NEED);
    prompt.textContent = done ? '✓ Eğitim tamamlandı' : need
      ? ({ center: 'Yüzünüzü ekrana karşı tutun', left: 'Başınızı yavaşça SOLA çevirin', right: 'Başınızı yavaşça SAĞA çevirin', up: 'Başınızı hafifçe YUKARI kaldırın', down: 'Başınızı hafifçe AŞAĞI eğin' })[need]
      : 'Birkaç saniye daha…';
    status.textContent = `${added} resim eklendi · %${Math.round(p * 100)}`;
  }
  async function tick() {
    if (stopped || busy || done) return;
    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return;
    const scale = Math.min(1, 480 / vw);
    grab.width = Math.round(vw * scale); grab.height = Math.round(vh * scale);
    grab.getContext('2d').drawImage(video, 0, 0, grab.width, grab.height);
    const jpg = grab.toDataURL('image/jpeg', 0.72).split(',')[1];
    busy = true;
    try {
      const r = await api.post('/api/faces/enroll-frame', { jpg, subject_type: subject.subject_type,
        user_id: subject.user_id || null, person_id: subject.person_id || null, family_id: subject.family_id || null });
      if (stopped) return;
      if (r && r.found) {
        const b = _poseBucket(r.yaw || 0, r.pitch || 0);
        if (r.added && counts[b] < _NEED) { counts[b]++; added++; }
        else if (r.added) { added++; }
        refresh();
        if (!done && _BUCKETS.every(x => counts[x] >= _NEED)) {
          done = true; refresh();
          setTimeout(() => { stop(); toast(`Yüz eğitimi tamamlandı · ${added} resim eklendi`, 'success'); try { subject.onDone && subject.onDone(); } catch { /* */ } panel.close(); }, 700);
        }
      } else if (!done) { prompt.textContent = 'Yüz görünmüyor — kameraya bakın'; }
    } catch (err) {
      if (!stopped) { status.textContent = 'Hata: ' + ((err && err.message) || 'bağlantı'); status.className = 'lp-status err'; }
    } finally { busy = false; }
  }

  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false });
    video.srcObject = stream;
    await video.play().catch(() => {});
    refresh();
    timer = setInterval(tick, 550);
  } catch (err) {
    prompt.textContent = 'Kamera açılamadı: ' + ((err && err.message) || err); status.className = 'lp-status err';
  }
  return panel;
}

// ============================================================ SES TANIMA EĞİTİMİ (rehberli metin okuma)
// opts: {user_id, name, onDone}. Metni okutur; söyledikçe kelimeler yeşile döner; tamamlanınca kayıt kişiye atanır.
const _ENROLL_PROMPT = 'Bugün hava çok güzel, işe zamanında geldim ve bütün görevlerimi eksiksiz tamamladım.';
function _norm(s) { return (s || '').toLocaleLowerCase('tr').replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim(); }
export async function openVoiceEnroll(opts) {
  injectStyle();
  const words = _ENROLL_PROMPT.split(' ');
  const wEls = words.map(w => h('span', { class: 'w' }, w));
  const box = h('div', { class: 'lp-prompt-box' }, wEls.flatMap((e, i) => i ? [' ', e] : [e]));
  const wave = h('canvas', { class: 'lp-wave' });
  const status = h('div', { class: 'lp-status' }, 'Mikrofon başlatılıyor…');
  const finishBtn = h('button', { class: 'btn primary sm', type: 'button', disabled: true, style: { marginTop: '8px' } }, 'Kaydı kişiye ata');
  const panel = floatPanel({ title: 'Ses Tanıma Eğitimi', sub: opts.name || '', width: 430, onClose: stop });
  panel.body.append(h('div', { class: 'small muted', style: { marginBottom: '6px' } }, 'Aşağıdaki cümleyi doğal bir sesle okuyun:'), box, wave, status, h('div', { style: { textAlign: 'right' } }, finishBtn));

  let stream = null, ac = null, analyser = null, stopDraw = null, stopSeg = null, fullRec = null, chunks = [], stopped = false, matched = 0, finalizing = false;
  const promptNorm = words.map(_norm);
  const { type: mrType } = _mrType();

  function stop() {
    stopped = true;
    if (stopSeg) stopSeg();
    if (stopDraw) stopDraw();
    try { if (fullRec && fullRec.state !== 'inactive') fullRec.stop(); } catch { /* */ }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    try { ac && ac.close(); } catch { /* */ }
    ac = null;
  }
  function applyMatch(transcript) {
    const toks = _norm(transcript).split(' ').filter(Boolean);
    let p = matched, ti = 0;
    while (p < promptNorm.length && ti < toks.length) {
      const target = promptNorm[p], tok = toks[ti];
      if (tok === target || (tok.length > 2 && (target.startsWith(tok) || tok.startsWith(target)))) { p++; ti++; }
      else ti++;
    }
    if (p > matched) { matched = p; for (let i = 0; i < matched; i++) wEls[i].classList.add('ok'); }
    const ratio = matched / promptNorm.length;
    finishBtn.disabled = ratio < 0.6 || finalizing;
    if (ratio >= 0.6) { status.textContent = `%${Math.round(ratio * 100)} okundu — bitirebilirsiniz`; status.className = 'lp-status ok'; }
    if (ratio >= 0.95 && !finalizing) finalize();
  }
  async function onBlob(blob, ext) {
    if (stopped || finalizing) return;
    try {
      const fd = new FormData(); fd.append('file', blob, `stt.${ext}`); fd.append('lang', 'tr');
      const r = await api.post('/api/system/dictate', fd);
      if (!stopped && r && r.text) applyMatch(words.slice(0, matched).join(' ') + ' ' + r.text);
    } catch { /* parça atlandı */ }
  }
  async function finalize() {
    if (finalizing || stopped) return;
    finalizing = true; finishBtn.disabled = true;
    status.textContent = 'Ses kaydı kişiye atanıyor…'; status.className = 'lp-status';
    if (stopSeg) stopSeg();
    // tam kaydı durdur → blob → enroll
    const blob = await new Promise(res => {
      if (!fullRec || fullRec.state === 'inactive') return res(new Blob(chunks, { type: mrType || 'audio/webm' }));
      fullRec.onstop = () => res(new Blob(chunks, { type: mrType || 'audio/webm' }));
      try { fullRec.stop(); } catch { res(new Blob(chunks, { type: mrType || 'audio/webm' })); }
    });
    try {
      const ext = mrType.includes('ogg') ? 'ogg' : mrType.includes('mp4') ? 'm4a' : 'webm';
      const fd = new FormData(); fd.append('file', blob, `enroll.${ext}`);
      const r = await api.post(`/api/voice/person/${opts.user_id}/enroll`, fd);
      toast(`Ses kaydı atandı · profil ${r.samples} örnek`, 'success');
      stop(); try { opts.onDone && opts.onDone(); } catch { /* */ } panel.close();
    } catch (err) {
      finalizing = false; status.textContent = 'Atama hatası: ' + ((err && err.message) || 'bağlantı'); status.className = 'lp-status err';
    }
  }
  finishBtn.addEventListener('click', finalize);

  try {
    ({ stream, ac, analyser } = await _startMic());
    stopDraw = _waveLoop(wave, analyser, '#34d399', () => stopped);
    fullRec = new MediaRecorder(stream, mrType ? { mimeType: mrType } : undefined);
    fullRec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    fullRec.start();
    stopSeg = _segmentLoop(stream, onBlob, 3500, () => stopped);
    status.textContent = 'Okumaya başlayın…'; status.className = 'lp-status ok';
  } catch (err) {
    status.textContent = 'Mikrofon açılamadı: ' + ((err && err.message) || err); status.className = 'lp-status err';
  }
  return panel;
}
