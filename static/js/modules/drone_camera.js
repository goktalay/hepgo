// Dron Kameraları — tarayıcı tarafı (DOM): MSE oynatıcı, yeşil HUD, telemetri beslemesi, yüzen kamera pencereleri, ayrı pencere.
// Görüntü: /ws/drone/video/watch?camera_id=N (oturum çerezi) → {t:'hello'|'init'|'state'|'stat'} + ikili [tür][fMP4] (drone_camera_core.splitFrame).
// MSE 'sequence' kipinde eklenir (köprü yeniden başlayınca zaman damgası sıfırlansa da akış sürer); canlı uç liveEdge ile korunur; tampon
// 10 sn'den eskisi silinir. MSE yoksa / kodek desteklenmiyorsa (ör. H.265) JPEG anlık görüntü kipine düşülür (düşük bant, 2 sn'de bir).
// Yüzen pencereler (Canlı Uçuş): Uçuş Simülatörü radar/EO pencerelerinin SAF yerleşim kuralları (flightsim_dock.js) paylaşılır — başlıktan
// sürükle, sağ alt / sol alt köşe ve sağ / alt kenar tutamaçlarıyla en-boy oranı korunarak boyutlandır, bırakınca kenara yapış; yerleşim kamera
// başına localStorage 'dr.cam.win'. Başlığa ya da görüntüye ÇİFT TIK → kamera ayrı tarayıcı penceresinde (/static/kamera.html).
// HUD yalnız göstergedir (hedef güdümü / otonom angajman YOK): yön şeridi, irtifa, yer hızı, dikey hız, batarya, GPS, mod + ARM, konum, uçuş süresi,
// merkez artı, ufuk (roll/pitch), CANLI göstergesi, gecikme. HUD'daki seçiciyle kamera başka drona bağlanabilir (onDrone).
import { t } from '../i18n.js';
import { avoidRects, boundsOf, clampRect, resizeW, sizeFor, snapRect, toFrac } from './flightsim_dock.js';
import {
  ASPECT, HDR, HUD_KEY, latencyText, liveEdge, loadWins, placeWin, saveWin, splitFrame, T_INIT, trimRange, headingTicks, pitchLadder, hudFields,
} from './drone_camera_core.js';

const GREEN = '#3dff7a';
const STATE_TEXT = {
  baglaniyor: 'Bağlanıyor…', basliyor: 'Kaynak açılıyor…', canli: 'Canlı', kare_yok: 'Görüntü yok', hata: 'Kaynak hatası', h265: 'H.265 kaynak',
  kopru_cevrimdisi: 'Köprü çevrim dışı', bekliyor: 'Bekliyor', durdu: 'Yayın durdu', yetki: 'Yetki yok', durduruldu: 'Durduruldu',
};

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'title' || k === 'placeholder') e.setAttribute(k, t(String(v)));
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : t(String(c)));
  return e;
}

const CSS = `
.drc-player{position:relative;background:#05080b;overflow:hidden;width:100%;height:100%;min-height:80px;user-select:none}
.drc-player video,.drc-player img.drc-snap{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
.drc-player canvas.drc-hud{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.drc-st{position:absolute;left:50%;transform:translateX(-50%);bottom:6px;font:600 11px/1.3 ui-monospace,monospace;color:#d7e3ee;background:rgba(0,0,0,.55);padding:2px 7px;border-radius:6px;pointer-events:none;max-width:calc(100% - 16px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drc-st.warn{color:#ffd166}.drc-st.err{color:#ff8a7a}.drc-st.ok{color:${GREEN}}
.drc-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:12px;color:#c9d6e2;font:13px/1.4 system-ui,sans-serif;pointer-events:none}
.drc-tools{position:absolute;right:6px;top:6px;display:flex;gap:4px;z-index:3;opacity:0;transition:opacity .15s}
.drc-player:hover .drc-tools,.drc-tools:focus-within,.drc-player.nohud .drc-tools{opacity:1}
@media (hover:none){.drc-tools{opacity:1;top:auto;bottom:26px}}
.drc-play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;padding:10px 22px;border-radius:999px;border:1px solid rgba(74,222,128,.7);background:rgba(6,20,12,.75);color:#bbf7d0;font:600 15px system-ui,sans-serif;cursor:pointer}
.drc-play:hover{background:rgba(22,101,52,.85);color:#fff}
.drc-play[hidden]{display:none}
.drc-ico{width:13px;height:13px;vertical-align:-2px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.drc-tools button,.drc-tools select{font:600 11px/1 ui-monospace,monospace;background:rgba(0,0,0,.55);color:${GREEN};border:1px solid rgba(61,255,122,.45);border-radius:5px;padding:4px 6px;cursor:pointer}
.drc-tools select{max-width:140px}
.drc-tools button.off{color:#9fb0c3;border-color:rgba(159,176,195,.4)}
.drc-layer{position:absolute;inset:0;pointer-events:none;z-index:40}
.drc-win{position:absolute;pointer-events:auto;background:#0b1118;border:1px solid rgba(61,255,122,.35);border-radius:9px;box-shadow:0 10px 30px rgba(0,0,0,.45);display:flex;flex-direction:column;overflow:hidden}
.drc-win.settle{transition:left .18s,top .18s}
.drc-hd{height:${HDR}px;flex:none;display:flex;align-items:center;gap:6px;padding:0 6px 0 9px;background:linear-gradient(#142030,#0e1722);color:#dce8f2;font:600 12px/1 system-ui,sans-serif;cursor:move;touch-action:none}
.drc-hd .drc-t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.drc-hd .drc-dot{width:8px;height:8px;border-radius:50%;background:#6b7785;flex:none}.drc-hd .drc-dot.on{background:${GREEN};box-shadow:0 0 6px ${GREEN}}
.drc-hd button{background:none;border:0;color:#9fb0c3;font-size:14px;cursor:pointer;padding:2px 4px}.drc-hd button:hover{color:#fff}
.drc-bd{flex:1;min-height:0;position:relative}
.drc-grip{position:absolute;z-index:4;touch-action:none}
.drc-grip.br{right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize;background:linear-gradient(135deg,transparent 55%,rgba(61,255,122,.6) 56%,rgba(61,255,122,.6) 62%,transparent 63%,transparent 72%,rgba(61,255,122,.6) 73%,rgba(61,255,122,.6) 79%,transparent 80%)}
.drc-grip.bl{left:0;bottom:0;width:16px;height:16px;cursor:nesw-resize}
.drc-grip.r{right:0;top:${HDR}px;bottom:16px;width:6px;cursor:ew-resize}
.drc-grip.b{left:16px;right:16px;bottom:0;height:6px;cursor:ns-resize}
.drc-shield{position:fixed;inset:0;z-index:9999;cursor:move}
.drc-panel{position:absolute;right:12px;top:56px;width:min(380px,calc(100% - 24px));max-height:calc(100% - 80px);overflow:auto;pointer-events:auto;background:var(--panel,#fff);color:var(--fg,#111);border:1px solid var(--line,#ccd);border-radius:12px;box-shadow:0 12px 34px rgba(0,0,0,.35);padding:12px;z-index:45}
.drc-panel .drc-ph{margin:0 0 8px;font-size:14px;display:flex;align-items:center;gap:8px}
.drc-panel .drc-row{border:1px solid var(--line,#dde);border-radius:9px;padding:8px;margin-bottom:8px}
.drc-panel .drc-row b{font-size:13px}
.drc-panel label{display:block;font-size:11px;opacity:.75;margin:6px 0 2px}
.drc-panel select{width:100%}
.drc-fab{position:absolute;right:12px;top:12px;z-index:46;pointer-events:auto}
`;
export function ensureCamCss() {
  if (document.getElementById('drc-css')) return;
  document.head.append(el('style', { id: 'drc-css' }, CSS));
}
// simgeler (emoji yazı tipi olmayan sistemlerde de görünsün diye SVG)
const svg = d => { const w = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); w.setAttribute('viewBox', '0 0 24 24'); w.setAttribute('class', 'drc-ico'); w.innerHTML = d; return w; };
export const ICON = {
  cam: '<rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-3v10l-6-3z"/>',
  pop: '<path d="M14 3h7v7M21 3l-9 9M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
};
export const icon = k => svg(ICON[k]);
const wsUrl = path => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;

// ======================================================================
// Oynatıcı
// ======================================================================
/** createPlayer({cameraId, hud?, tools?, autostart?}) → {el, video, start(), pause(), stop(), onState(fn), state, lag}
 *  autostart=false: kullanıcı "▶ Başlat" demeden köprüden yayın istenmez; "■ Durdur" izleme bağlantısını kapatır → sunucu köprüye
 *  want:false gönderir, köprü kaynağı kapatır (yayın yalnız kullanıcı isteğiyle açık kalır). */
export function createPlayer({ cameraId, hud = false, getTelemetry = null, droneSelect = null, popout = null, lowBandwidth = false, autostart = true } = {}) {
  ensureCamCss();
  const video = el('video', { muted: true, playsinline: true, autoplay: true });
  video.muted = true;
  const snapImg = el('img', { class: 'drc-snap', hidden: true, alt: '' });
  const canvas = el('canvas', { class: 'drc-hud' });
  const st = el('div', { class: 'drc-st' }, t('Bağlanıyor…'));
  const msg = el('div', { class: 'drc-msg', hidden: true });
  let hudOn = hud && (localStorage.getItem(HUD_KEY) ?? '1') !== '0';
  const hudBtn = hud ? el('button', { type: 'button', class: hudOn ? '' : 'off', title: 'HUD aç/kapat', onclick: e => { e.stopPropagation(); hudOn = !hudOn; hudBtn.className = hudOn ? '' : 'off'; localStorage.setItem(HUD_KEY, hudOn ? '1' : '0'); } }, 'HUD') : null;
  const lowBtn = el('button', { type: 'button', class: lowBandwidth ? '' : 'off', title: 'Düşük bant: yalnız 2 sn\'de bir anlık görüntü (JPEG)', onclick: e => { e.stopPropagation(); setLow(!low); } }, 'JPEG');
  const popBtn = popout ? el('button', { type: 'button', title: 'Ayrı pencerede aç (çift tık)', onclick: e => { e.stopPropagation(); popout(); } }, icon('pop')) : null;
  const stopBtn = el('button', { type: 'button', title: 'Yayını durdur (köprü kaynağı kapatır)', onclick: e => { e.stopPropagation(); pause(); } }, '■');
  const playBtn = el('button', { type: 'button', class: 'drc-play', title: 'Yayını başlat', onclick: e => { e.stopPropagation(); start(); } }, '▶ ', t('Başlat'));
  const tools = el('div', { class: 'drc-tools' }, droneSelect, hudBtn, lowBtn, stopBtn, popBtn);
  const root = el('div', { class: `drc-player${hud ? '' : ' nohud'}` }, video, snapImg, canvas, msg, st, tools, playBtn);
  const S = { state: 'baglaniyor', detail: '', lag: null, age: null, stat: {}, mime: null, ws: null, ms: null, sb: null, q: [], closed: false, live: false,
    off: null, rtt: null, fts: null, fmap: [], fps: null, latency: null, latSrc: null, kbps: null, frames: 0 };   // ölçümler: tarayıcı FPS'i, köprü→ekran gecikmesi
  const listeners = new Set();
  let low = false, snapTimer = null, edgeTimer = null, retry = null, url = null, running = false, pingT = null, metT = null;
  let limitPm = 0;   // uydu video kısıtı (sunucu 4430 ile bildirir): canlı yok, dakikada limitPm kare

  const MS = window.ManagedMediaSource || window.MediaSource;
  const setState = (state, detail = '') => {
    S.state = state; S.detail = detail || '';
    const txt = t(STATE_TEXT[state] || state);
    st.textContent = `${txt}${S.detail ? ` · ${t(S.detail)}` : ''}`;
    st.className = `drc-st ${state === 'canli' ? 'ok' : ['kare_yok', 'h265', 'kopru_cevrimdisi'].includes(state) ? 'warn' : state === 'hata' ? 'err' : ''}`;
    listeners.forEach(fn => { try { fn(S); } catch { /* */ } });
  };
  const showMsg = text => { msg.hidden = !text; msg.textContent = text ? t(text) : ''; };

  function resetMse() {
    try { if (S.ms && S.ms.readyState === 'open') S.ms.endOfStream(); } catch { /* */ }
    S.sb = null; S.q = [];
    if (url) { URL.revokeObjectURL(url); url = null; }
    S.ms = null;
  }
  function startMse(mime) {
    resetMse();
    if (!MS || !mime || !MS.isTypeSupported(mime)) {
      showMsg(mime && /hvc1|hev1/.test(mime) ? 'Tarayıcınız H.265 görüntüyü oynatamıyor; kamerada H.264 seçin ya da köprü ayarında h265 = yeniden_kodla. Şimdilik JPEG anlık görüntü gösteriliyor.'
        : 'Bu tarayıcı canlı akışı (MSE) oynatamıyor; JPEG anlık görüntü gösteriliyor.');
      setLow(true, true);
      return;
    }
    showMsg('');
    const ms = new MS();
    S.ms = ms;
    if (window.ManagedMediaSource && MS === window.ManagedMediaSource) video.disableRemotePlayback = true;
    url = URL.createObjectURL(ms);
    video.src = url;
    ms.addEventListener('sourceopen', () => {
      if (S.ms !== ms) return;
      try {
        S.sb = ms.addSourceBuffer(mime);
        S.sb.mode = 'sequence';
        S.sb.addEventListener('updateend', () => {
          const f = S.fpend; S.fpend = null;
          if (f && S.sb?.buffered.length) f.end = S.sb.buffered.end(S.sb.buffered.length - 1);
          pump();
        });
        pump();
      } catch (e) { showMsg(`Oynatıcı açılamadı: ${e.message}`); }
    }, { once: true });
  }
  function pump() {
    const sb = S.sb;
    if (!sb || sb.updating || !S.q.length) return;
    const item = S.q.shift();
    const chunk = item.d || item;
    if (item.fts) {   // parçanın medya başlangıcı (sequence kipinde tampon sonuna eklenir) ↔ köprüden çıkış anı
      const b = sb.buffered, start = b.length ? b.end(b.length - 1) : 0;
      S.fmap.push({ start, end: null, fts: item.fts.ms, src: item.fts.src });
      if (S.fmap.length > 40) S.fmap.splice(0, S.fmap.length - 40);
      S.fpend = S.fmap[S.fmap.length - 1];
    } else S.fpend = null;
    try { sb.appendBuffer(chunk); } catch (e) {
      if (e.name === 'QuotaExceededError') {   // tampon dolu: eskisini sil, parçayı yeniden dene
        S.q.unshift(chunk);
        try { const b = sb.buffered; if (b.length) sb.remove(b.start(0), Math.max(b.start(0) + 1, video.currentTime - 2)); } catch { /* */ }
      }
    }
  }
  function edge() {
    const sb = S.sb;
    if (!sb || !video.buffered.length) return;
    const end = video.buffered.end(video.buffered.length - 1);
    const r = liveEdge(end, video.currentTime);
    S.lag = r.lag;
    if (r.seek != null) video.currentTime = r.seek;
    if (video.playbackRate !== r.rate) video.playbackRate = r.rate;
    if (video.paused) video.play().catch(() => {});
    const tr = trimRange(video.buffered.start(0), video.currentTime);
    if (tr && !sb.updating) { try { sb.remove(tr[0], tr[1]); } catch { /* */ } }
    if (S.state === 'canli') setState('canli', S.latency != null ? t('{ms} ms gecikme', { ms: Math.round(S.latency) }) : latencyText(S.lag, S.age, t));
  }
  function setLow(on, forced = false) {
    low = !!on;
    if (!running) { lowBtn.className = low ? '' : 'off'; return; }   // durdurulmuşken yalnız tercih değişir
    lowBtn.className = low ? '' : 'off';
    clearInterval(snapTimer); snapTimer = null;
    video.hidden = low; snapImg.hidden = !low;
    if (low) {
      const pull = () => { const i = new Image(); i.onload = () => { snapImg.src = i.src; }; i.src = `/api/drone/cameras/${cameraId}/snapshot.jpg?t=${Date.now()}`; };
      pull(); snapTimer = setInterval(pull, limitPm ? 60000 / limitPm : 2000);
      if (limitPm) showMsg(t('Uydu veri kısıtı: dakikada {n} kare', { n: limitPm }));
      if (!forced) closeWs();   // düşük bant: canlı akış kapatılır (köprü izleyici kalmayınca yayını durdurur)
    } else if (!forced) { showMsg(''); connect(); }
  }
  function closeWs() { const ws = S.ws; S.ws = null; if (ws) { ws.onclose = null; try { ws.close(); } catch { /* */ } } resetMse(); }
  function connect() {
    if (S.closed || low || !running) return;
    closeWs();
    setState('baglaniyor');
    const ws = new WebSocket(wsUrl(`/ws/drone/video/watch?camera_id=${encodeURIComponent(cameraId)}`));
    ws.binaryType = 'arraybuffer';
    S.ws = ws;
    ws.onmessage = ev => {
      if (typeof ev.data === 'string') {
        let m; try { m = JSON.parse(ev.data); } catch { return; }
        if (m.t === 'hello') { S.mime = m.mime || S.mime; setState(m.bridge_online ? (m.state || 'basliyor') : 'kopru_cevrimdisi', m.detail); }
        else if (m.t === 'init') { S.mime = m.mime || S.mime; startMse(S.mime || 'video/mp4; codecs="avc1.42E01E"'); }
        else if (m.t === 'state') { if (m.mime) S.mime = m.mime; setState(m.state, m.detail); }
        else if (m.t === 'stat') { S.stat = m; S.age = m.age; }
        else if (m.t === 'fts') S.fts = { ms: Number(m.ms), src: m.src || 'sunucu' };
        else if (m.t === 'pong') {   // saat eşitleme: sunucu − tarayıcı (ms), düşük RTT örnekleri ağırlıklı
          const now = Date.now(), rtt = now - Number(m.c);
          if (Number.isFinite(rtt) && rtt >= 0 && rtt < 10000 && Number.isFinite(Number(m.ms))) {
            const off = Number(m.ms) + rtt / 2 - now;
            if (S.off == null || rtt <= (S.rtt ?? rtt) * 1.5) { S.off = S.off == null ? off : S.off * 0.7 + off * 0.3; S.rtt = S.rtt == null ? rtt : Math.min(rtt, S.rtt * 1.05); }
          }
          if (m.age != null) S.age = m.age;
        }
        else if (m.t === 'error' && m.limit_pm) {   // uydu video kısıtı: canlı yerine dakikada N kare (JPEG düğmesi kilitli)
          limitPm = Number(m.limit_pm); lowBtn.disabled = true; lowBtn.title = t('Uydu veri kısıtı: dakikada {n} kare', { n: limitPm });
          setState('canli', t('Dakikada {n} kare', { n: limitPm })); setLow(true, true);
        } else if (m.t === 'error') { setState(m.error === 'auth' ? 'yetki' : 'hata', m.error === 'auth' ? '' : m.error); S.closed = m.error === 'auth'; }
        return;
      }
      const fr = splitFrame(ev.data);
      if (!fr) return;
      if (fr.type === T_INIT && !S.ms) startMse(S.mime || 'video/mp4; codecs="avc1.42E01E"');
      if (!S.ms) return;
      S.q.push({ d: fr.data.slice(), fts: fr.type === T_INIT ? null : S.fts });
      S.fts = null;
      S.bytes = (S.bytes || 0) + fr.data.length;
      if (S.q.length > 120) S.q.splice(0, S.q.length - 60);   // sekme arka planda: kuyruk taşmasın
      if (fr.type !== T_INIT && S.state !== 'canli' && S.state !== 'h265') setState('canli');
      pump();
    };
    let pings = 0;
    const ping = () => { if (S.ws === ws && ws.readyState === 1) { try { ws.send(JSON.stringify({ t: 'ping', c: Date.now() })); } catch { /* */ } } };
    ws.onopen = () => { ping(); const tick = () => { if (S.ws !== ws) return; ping(); pingT = setTimeout(tick, ++pings < 5 ? 2000 : 10000); }; pingT = setTimeout(tick, 1500); };
    ws.onclose = ev => {
      clearTimeout(pingT);
      if (S.ws !== ws) return;
      S.ws = null;
      if (S.closed || ev.code === 4403 || ev.code === 4404 || ev.code === 4430) { if (ev.code === 4404) setState('hata', 'Kamera bulunamadı ya da pasif'); return; }
      if (!running) return;
      setState('baglaniyor', 'Yeniden bağlanılıyor');
      retry = setTimeout(connect, 3000);
    };
  }
  // HUD çizimi
  let raf = 0;
  function drawHud() {
    raf = requestAnimationFrame(drawHud);
    const W = root.clientWidth, H = root.clientHeight;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
    const g = canvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    if (!hud || !hudOn || W < 120) return;
    drawHudFrame(g, W, H, hudFields(getTelemetry ? getTelemetry() : null, t), { live: S.state === 'canli', lag: S.lag, hasDrone: !!(getTelemetry && getTelemetry()) });
  }
  if (hud) raf = requestAnimationFrame(drawHud);
  edgeTimer = setInterval(edge, 500);
  root.addEventListener('dblclick', e => { if (popout && !e.target.closest('.drc-tools')) { e.preventDefault(); popout(); } });
  // ---- ölçümler: FPS (sunulan kare sayısı) ve gerçek gecikme (köprüden çıkış → ekranda gösterim; saatler ping/pong ile eşitlenir) ----
  let lastFrames = 0, lastT = performance.now(), lastBytes = 0;
  const countFrame = () => { S.frames++; if (running && 'requestVideoFrameCallback' in video) video.requestVideoFrameCallback(countFrame); };
  if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback(countFrame);
  function measure() {
    const now = performance.now(), dt = (now - lastT) / 1000;
    if (dt >= 0.9) {
      let frames = S.frames;
      if (!('requestVideoFrameCallback' in video) && video.getVideoPlaybackQuality) frames = video.getVideoPlaybackQuality().totalVideoFrames;
      S.fps = running && !low && S.state === 'canli' ? Math.max(0, (frames - lastFrames) / dt) : null;
      S.kbps = running ? Math.round(((S.bytes || 0) - lastBytes) * 8 / 1000 / dt) : null;
      lastFrames = frames; lastBytes = S.bytes || 0; lastT = now;
    }
    S.latency = null; S.latSrc = null;
    if (running && !low && S.off != null && S.fmap.length && !video.paused) {
      const cur = video.currentTime;
      let f = null;
      for (let i = S.fmap.length - 1; i >= 0; i--) if (S.fmap[i].start <= cur && S.fmap[i].end != null) { f = S.fmap[i]; break; }
      if (f) {
        const dur = Math.max(0, f.end - f.start) * 1000;          // parça süresi: kareler parça kapanınca köprüden çıkar
        const captured = f.fts - dur + (cur - f.start) * 1000;      // şu an gösterilen karenin köprüye giriş anı (yaklaşık)
        const lat = Date.now() + S.off - captured;
        if (lat > -500 && lat < 60000) { S.latency = Math.max(0, lat); S.latSrc = f.src; }
      }
    }
    listeners.forEach(fn => { try { fn(S); } catch { /* */ } });
  }
  metT = setInterval(measure, 500);
  function start() {
    if (S.closed || running) return;
    running = true; playBtn.hidden = true; stopBtn.hidden = false; showMsg('');
    if (low || lowBandwidth) { low = false; setLow(true); } else connect();
    if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback(countFrame);
  }
  function pause() {
    running = false; clearTimeout(retry); clearInterval(snapTimer); snapTimer = null; closeWs();
    video.removeAttribute('src'); snapImg.hidden = true; video.hidden = false;
    playBtn.hidden = false; stopBtn.hidden = true; S.live = false;
    S.fps = S.latency = S.kbps = null; S.fmap = [];
    setState('durduruldu', '');
  }
  if (lowBandwidth) { low = true; lowBtn.className = ''; }
  if (autostart) start(); else pause();
  return {
    el: root, video, get state() { return S; }, start, pause, get running() { return running; },
    onState: fn => { listeners.add(fn); return () => listeners.delete(fn); },
    snapshotBlob: () => new Promise(res => {   // gösterilen kareden PNG (Fotoğraf)
      const c = document.createElement('canvas'); c.width = video.videoWidth || 1280; c.height = video.videoHeight || 720;
      try { c.getContext('2d').drawImage(low ? snapImg : video, 0, 0, c.width, c.height); c.toBlob(b => res(b), 'image/png'); } catch { res(null); }
    }),
    setHud(on) { hudOn = !!on; if (hudBtn) hudBtn.className = hudOn ? '' : 'off'; },
    setLow,
    get low() { return low; },
    stop() { running = false; S.closed = true; clearTimeout(retry); clearTimeout(pingT); clearInterval(metT); clearInterval(edgeTimer); clearInterval(snapTimer); cancelAnimationFrame(raf); closeWs(); video.removeAttribute('src'); },
  };
}

// ======================================================================
// Yeşil HUD (askerî/EO görünümü — yalnız gösterge)
// ======================================================================
export function drawHudFrame(g, W, H, F, { live = false, lag = null, hasDrone = true } = {}) {
  const s = Math.max(0.7, Math.min(1.4, Math.min(W, H) / 360));
  const fs = Math.round(11 * s);
  g.save();
  g.strokeStyle = GREEN; g.fillStyle = GREEN; g.lineWidth = 1;
  g.font = `600 ${fs}px ui-monospace, SFMono-Regular, Menlo, monospace`;
  g.shadowColor = 'rgba(0,0,0,.85)'; g.shadowBlur = 3;
  const cx = W / 2, cy = H / 2;
  const txt = (x, y, str, align = 'left') => { g.textAlign = align; g.fillText(str, x, y); };
  // merkez artı
  const c = 14 * s;
  g.beginPath(); g.moveTo(cx - c * 2, cy); g.lineTo(cx - c * 0.6, cy); g.moveTo(cx + c * 0.6, cy); g.lineTo(cx + c * 2, cy);
  g.moveTo(cx, cy - c * 1.4); g.lineTo(cx, cy - c * 0.6); g.moveTo(cx, cy + c * 0.6); g.lineTo(cx, cy + c * 1.4); g.stroke();
  g.beginPath(); g.arc(cx, cy, 1.5, 0, Math.PI * 2); g.fill();
  // ufuk + eğim merdiveni (roll/pitch)
  if (hasDrone && F.roll != null && F.pitch != null) {
    g.save();
    g.beginPath(); g.rect(cx - W * 0.3, cy - H * 0.32, W * 0.6, H * 0.64); g.clip();
    g.translate(cx, cy); g.rotate(-F.roll * Math.PI / 180);
    for (const r of pitchLadder(F.pitch, { pxPerDeg: 5 * s, range: 20 })) {
      const half = r.horizon ? W * 0.28 : 34 * s;
      g.setLineDash(r.p < 0 ? [5 * s, 4 * s] : []);
      g.beginPath();
      if (r.horizon) { g.moveTo(-half, r.y); g.lineTo(-c * 2.6, r.y); g.moveTo(c * 2.6, r.y); g.lineTo(half, r.y); }
      else { g.moveTo(-half, r.y); g.lineTo(-half * 0.4, r.y); g.moveTo(half * 0.4, r.y); g.lineTo(half, r.y); }
      g.stroke();
      if (r.label) { txt(-half - 4, r.y + fs / 3, r.label, 'right'); txt(half + 4, r.y + fs / 3, r.label, 'left'); }
    }
    g.setLineDash([]);
    g.restore();
  }
  // yön şeridi (üst)
  const tw = Math.min(W * 0.6, 420 * s), ty = 18 * s + fs;
  if (F.hdg != null) {
    g.save(); g.beginPath(); g.rect(cx - tw / 2, ty - fs - 6, tw, fs + 22 * s); g.clip();
    for (const k of headingTicks(F.hdg, 90, 5)) {
      const x = cx + k.x * tw / 2;
      g.beginPath(); g.moveTo(x, ty + 2); g.lineTo(x, ty + (k.major ? 9 : 5) * s); g.stroke();
      if (k.label) txt(x, ty - 2, k.label, 'center');
    }
    g.restore();
    g.beginPath(); g.moveTo(cx, ty + 11 * s); g.lineTo(cx - 5 * s, ty + 17 * s); g.lineTo(cx + 5 * s, ty + 17 * s); g.closePath(); g.stroke();
    g.strokeRect(cx - 22 * s, ty + 19 * s, 44 * s, fs + 6); txt(cx, ty + 19 * s + fs + 1, String(Math.round(((F.hdg % 360) + 360) % 360)).padStart(3, '0'), 'center');
  }
  // sol: yer hızı + dikey hız · sağ: irtifa
  const boxY = cy - fs;
  g.strokeRect(14 * s, boxY - 4, 92 * s, fs + 10); txt(18 * s, boxY + fs, F.gs);
  txt(18 * s, boxY - 8, t('YER HIZI'));
  txt(18 * s, boxY + fs * 2 + 12, `VS ${F.vs}`);
  g.strokeRect(W - 106 * s, boxY - 4, 92 * s, fs + 10); txt(W - 18 * s, boxY + fs, F.alt, 'right');
  txt(W - 18 * s, boxY - 8, t('İRTİFA'), 'right');
  if (F.altMsl) txt(W - 18 * s, boxY + fs * 2 + 12, F.altMsl, 'right');
  // üst sol: mod + ARM · üst sağ: CANLI + gecikme
  txt(10 * s, 16 * s + fs, `${F.mode}`);
  g.fillStyle = F.armed ? '#ff5b4d' : GREEN; txt(10 * s, 16 * s + fs * 2 + 4, F.armed ? 'ARMED' : 'DISARMED'); g.fillStyle = GREEN;
  if (live) { g.fillStyle = '#ff3b30'; g.beginPath(); g.arc(W - 64 * s, 12 * s + fs * 0.65, 4 * s, 0, Math.PI * 2); g.fill(); g.fillStyle = GREEN; }
  txt(W - 10 * s, 16 * s + fs, live ? t('CANLI') : t('BEKLİYOR'), 'right');
  if (lag != null) txt(W - 10 * s, 16 * s + fs * 2 + 4, `${t('GECİKME')} ${lag.toFixed(1)}s`, 'right');
  // alt: batarya, GPS, süre, konum
  const by = H - 10 * s;
  g.fillStyle = F.battLow ? '#ffb020' : GREEN; txt(10 * s, by - fs - 4, `BAT ${F.batt}`); g.fillStyle = F.gpsBad ? '#ffb020' : GREEN;
  txt(10 * s, by, F.gps); g.fillStyle = GREEN;
  txt(W - 10 * s, by - fs - 4, `T+ ${F.time}`, 'right');
  txt(W - 10 * s, by, F.pos, 'right');
  if (!hasDrone) txt(cx, cy + 46 * s, t('HUD: bağlı dron telemetrisi yok'), 'center');
  // köşe çerçeveleri
  const L = 18 * s, m = 6 * s;
  for (const [x, y, dx, dy] of [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]]) {
    g.beginPath(); g.moveTo(x, y + dy * L); g.lineTo(x, y); g.lineTo(x + dx * L, y); g.stroke();
  }
  g.restore();
}

// ======================================================================
// Telemetri beslemesi (/ws/drone/live; görev bağlamı) — HUD için
// ======================================================================
export function createTelemetryFeed(taskId) {
  const states = new Map();   // `${bridge_id}:${sysid}` → state
  let ws = null, closed = false, timer = null;
  const open = () => {
    if (closed) return;
    ws = new WebSocket(wsUrl('/ws/drone/live'));
    ws.onopen = () => { if (taskId) ws.send(JSON.stringify({ t: 'watch', task_id: Number(taskId) })); };
    ws.onmessage = ev => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.t === 'status') states.set(`${m.bridge_id}:${m.sysid}`, m.state);
      else if (m.t === 'hello') for (const b of m.bridges || []) for (const [sid, st] of Object.entries(b.drones || {})) states.set(`${b.bridge_id}:${sid}`, st);
    };
    ws.onclose = () => { if (!closed) timer = setTimeout(open, 4000); };
  };
  open();
  return {
    get: (bridgeId, sysid) => (bridgeId == null ? null : states.get(`${bridgeId}:${sysid || 1}`) || null),
    close() { closed = true; clearTimeout(timer); try { ws?.close(); } catch { /* */ } },
  };
}

export function popoutUrl(camId, { taskId = null, droneId = null } = {}) {
  const q = new URLSearchParams({ camera: String(camId) });
  if (taskId) q.set('task', String(taskId));
  if (droneId) q.set('drone', String(droneId));
  return `/static/kamera.html?${q}`;
}
export function openPopout(camId, opts = {}) {
  const w = window.open(popoutUrl(camId, opts), `hepgo-kamera-${camId}`, 'popup=yes,width=960,height=580');
  w?.focus?.();
  return w;
}

// ======================================================================
// Yüzen kamera pencereleri (Canlı Uçuş)
// ======================================================================
/** createCameraWindows(stage, {taskId, getHud(camId) → state|null, droneOptions(camId) → {list, value, onChange}, onClose(camId)}) */
export function createCameraWindows(stage, { taskId = null, getHud = () => null, droneOptions = null, onClose = () => {}, onLayout = () => {} } = {}) {
  ensureCamCss();
  const layer = el('div', { class: 'drc-layer' });
  stage.append(layer);
  const wins = new Map();   // camId → {box, body, player, rect, cam}
  const store = window.localStorage;
  const bounds = () => { const W = layer.clientWidth || stage.clientWidth || 1200, H = layer.clientHeight || stage.clientHeight || 800; return { W, H, B: boundsOf(W, H, { top: 56 }) }; };
  const place = (w, r) => { w.rect = r; Object.assign(w.box.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` }); };
  const others = id => [...wins.entries()].filter(([k]) => k !== id).map(([, w]) => w.rect).filter(Boolean);

  function open(cam, opts = {}) {
    if (wins.has(cam.id)) { wins.get(cam.id).box.style.zIndex = String(Date.now() % 1e6); return wins.get(cam.id); }
    const title = el('span', { class: 'drc-t' }, cam.name);
    const dot = el('i', { class: 'drc-dot' });
    const popout = () => openPopout(cam.id, { taskId, droneId: cam.hud_drone_id });
    let dsel = null;
    if (droneOptions) {
      const o = droneOptions(cam);
      if (o && o.list.length) {
        dsel = el('select', { title: 'HUD: bağlı dron' }, el('option', { value: '' }, '— dron —'), ...o.list.map(d => el('option', { value: String(d.drone_id), selected: String(d.drone_id) === String(o.value ?? '') }, d.label)));
        dsel.addEventListener('change', e => { e.stopPropagation(); o.onChange(dsel.value ? Number(dsel.value) : null); });
        dsel.addEventListener('pointerdown', e => e.stopPropagation());
      }
    }
    const player = createPlayer({ cameraId: cam.id, hud: true, getTelemetry: () => getHud(cam.id), droneSelect: dsel, popout, autostart: !!opts.autostart });   // geri yüklenen pencere "▶ Başlat" bekler
    player.onState(s => { dot.className = `drc-dot${s.state === 'canli' ? ' on' : ''}`; });
    const close = el('button', { type: 'button', title: 'Kapat', onclick: e => { e.stopPropagation(); closeWin(cam.id); onClose(cam.id); } }, icon('x'));
    const pop = el('button', { type: 'button', title: 'Ayrı pencerede aç (çift tık)', onclick: e => { e.stopPropagation(); popout(); } }, icon('pop'));
    const hd = el('div', { class: 'drc-hd', title: 'Taşımak için sürükleyin · çift tık: ayrı pencere' }, dot, title, pop, close);
    const body = el('div', { class: 'drc-bd' }, player.el);
    const grips = ['br', 'bl', 'r', 'b'].map(k => el('i', { class: `drc-grip ${k}`, 'data-k': k, title: 'Boyutlandır (oran korunur)' }));
    const box = el('div', { class: 'drc-win', 'data-cam': String(cam.id) }, hd, body, ...grips);
    layer.append(box);
    const w = { box, body, player, cam, rect: null };
    wins.set(cam.id, w);
    const { W, H, B } = bounds();
    const saved = loadWins(store)[String(cam.id)];
    let r = placeWin(saved, wins.size - 1, W, H, { bounds: B });
    if (!saved) r = avoidRects(r, others(cam.id), B, 8, 4);
    place(w, r);
    hd.addEventListener('pointerdown', e => startDrag(w, e, null));
    hd.addEventListener('dblclick', e => { if (e.target.closest('button,select')) return; e.preventDefault(); popout(); });
    for (const gEl of grips) gEl.addEventListener('pointerdown', e => startDrag(w, e, gEl.dataset.k));
    box.addEventListener('pointerdown', () => { box.style.zIndex = String(Date.now() % 1e6); });
    return w;
  }
  function closeWin(id) {
    const w = wins.get(id);
    if (!w) return;
    w.player.stop(); w.box.remove(); wins.delete(id);
  }
  // sürükle / boyutlandır (oran korunur: resizeW + sizeFor); sürüklerken iframe olayları yutmasın diye kalkan
  let drag = null, shield = null;
  function startDrag(w, e, corner) {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    if (!corner && e.target.closest('button,select')) return;
    e.preventDefault(); e.stopPropagation();
    drag = { w, corner, sx: e.clientX, sy: e.clientY, r0: { ...w.rect }, id: e.pointerId };
    shield = el('div', { class: 'drc-shield', style: { cursor: corner ? getComputedStyle(e.target).cursor : 'move' } });
    document.body.append(shield);
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
  }
  function move(e) {
    const d = drag; if (!d || e.pointerId !== d.id) return;
    const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
    const { W, H, B } = bounds();
    let r;
    if (d.corner) {
      const ar = ASPECT, w0 = d.r0.w;
      const nw = d.corner === 'r' ? w0 + dx : d.corner === 'b' ? w0 + dy * ar : resizeW(w0, dx, dy, ar, d.corner === 'bl' ? 'bl' : 'br');
      const sz = sizeFor(nw, ar, { W, H, hdr: HDR, bounds: B });
      const x = d.corner === 'bl' ? d.r0.x + (d.r0.w - sz.w) : d.r0.x;
      r = clampRect({ x, y: d.r0.y, w: sz.w, h: sz.h }, B);
    } else r = clampRect({ ...d.r0, x: d.r0.x + dx, y: d.r0.y + dy }, B);
    d.last = r; place(d.w, r);
  }
  function end(e) {
    const d = drag; if (!d || (e && e.pointerId !== d.id)) return;
    drag = null; shield?.remove(); shield = null;
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end);
    if (!d.last) return;
    const { W, H, B } = bounds();
    let r = snapRect(d.last, B);
    const av = avoidRects(r, others(d.w.cam.id), B, 8, 4, 220);
    if (av.x !== r.x || av.y !== r.y) r = snapRect(av, B, 2);
    d.w.box.classList.add('settle'); setTimeout(() => d.w.box.classList.remove('settle'), 220);
    place(d.w, r);
    saveWin(store, d.w.cam.id, r, W, H);
    onLayout(d.w.cam.id, toFrac(r, W, H));
  }
  const relayout = () => {
    const { W, H, B } = bounds();
    const saved = loadWins(store);
    [...wins.values()].forEach((w, i) => place(w, saved[String(w.cam.id)] ? placeWin(saved[String(w.cam.id)], i, W, H, { bounds: B }) : clampRect(w.rect, B)));
  };
  window.addEventListener('resize', relayout);
  return {
    layer, open, close: closeWin, has: id => wins.has(id), ids: () => [...wins.keys()],
    resetLayout(id) { saveWin(store, id, null, 1, 1); const w = wins.get(id); if (w) { const { W, H, B } = bounds(); place(w, placeWin(null, 0, W, H, { bounds: B })); } },
    dispose() { window.removeEventListener('resize', relayout); for (const id of [...wins.keys()]) closeWin(id); layer.remove(); },
  };
}
