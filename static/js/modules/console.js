// Araçlar › Terminal — yalnızca MASTER. Uygulamaya kendi kullanıcı adı/şifresiyle giren sistem sahibi,
// yerel makinede gerçek bir kabuk (bash) çalıştırır. WebSocket /ws/console üzerinden PTY'ye bağlanır.
import { clear, h, onLeave, pageHead } from '../ui.js';

const XT = '/static/vendor/xterm/';
let libsP = null;
function loadLibs() {
  if (libsP) return libsP;
  libsP = new Promise((res, rej) => {
    if (!document.querySelector('link[data-xterm]')) {
      const css = document.createElement('link');
      css.rel = 'stylesheet'; css.href = XT + 'xterm.min.css'; css.setAttribute('data-xterm', '1');
      document.head.appendChild(css);
    }
    const add = (src, ok) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = () => rej(new Error('xterm yüklenemedi')); document.head.appendChild(s); };
    if (window.Terminal) return res();
    add(XT + 'xterm.min.js', () => add(XT + 'xterm-addon-fit.min.js', () => res()));
  });
  return libsP;
}

export async function render(view, params, ctx) {
  if (!ctx.user.master) { clear(view, h('div', { class: 'card empty' }, 'Bu araç yalnızca sistem sahibine (MASTER) açıktır.')); return; }
  return openTerminal(view, { title: 'Terminal', back: '#/tools', sub: 'Sistem sahibi · yerel makinede kabuk', wsUrl: '/ws/console' });
}

// Ortak xterm + WebSocket terminali (yerel kabuk ve SSH aynı mekanizmayı kullanır). wsUrl'e bağlanır, PTY'yi gösterir.
export async function openTerminal(view, { title, back, sub, wsUrl }) {
  const host = h('div', { class: 'term-host' });
  const status = h('span', { class: 'term-status small muted' }, 'Bağlanıyor…');
  clear(view,
    pageHead(title, { back, sub, right: status }),
    h('div', { class: 'card term-card' }, host));

  try { await loadLibs(); } catch (e) { status.textContent = 'xterm yüklenemedi'; return; }

  const term = new window.Terminal({
    cursorBlink: true, fontSize: 13.5, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    theme: { background: '#0b1020', foreground: '#e6eefb', cursor: '#6fb6ff' }, scrollback: 5000,
  });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(host);
  try { fit.fit(); } catch { /* */ }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}${wsUrl}`);
  let alive = true;
  const sendResize = () => { try { fit.fit(); ws.readyState === 1 && ws.send(JSON.stringify({ t: 'r', c: term.cols, r: term.rows })); } catch { /* */ } };

  ws.onopen = () => { status.textContent = 'Bağlı'; status.className = 'term-status small'; sendResize(); term.focus(); };
  ws.onmessage = e => term.write(e.data);
  ws.onclose = () => { alive = false; status.textContent = 'Bağlantı kapandı'; status.className = 'term-status small muted'; term.write('\r\n\x1b[90m[bağlantı kapandı]\x1b[0m\r\n'); };
  ws.onerror = () => { status.textContent = 'Bağlantı hatası'; };
  term.onData(d => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: 'i', d })); });
  term.onResize(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: 'r', c: term.cols, r: term.rows })); });

  const onWin = () => sendResize();
  window.addEventListener('resize', onWin);

  // Sayfadan çıkınca bağlantıyı + kabuğu kapat
  onLeave(() => { alive = false; window.removeEventListener('resize', onWin); try { ws.close(); } catch { /* */ } try { term.dispose(); } catch { /* */ } });
  setTimeout(sendResize, 150);
}
