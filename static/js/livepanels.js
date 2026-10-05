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
