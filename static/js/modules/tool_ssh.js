// Araçlar › SSH Master (web): xterm.js + WebSocket /ws/tools/ssh → sunucuda sistem ssh istemcisi (PTY).
// Bağlantı bilgileri yalnız bu sayfanın belleğinde; profil kaydı (localStorage) parolasız. Çoklu sekme, yeniden boyutlama, kopyala/yapıştır.
import { api } from '../api.js';
import { clear, h, onLeave, pageHead, toast, toastError } from '../ui.js';
import { btn, inp, lab, loadCss, loadScript, profiles, sel, setStatus, shell, status } from './tool_mt.js';

const XT = '/static/vendor/xterm/';
async function loadXterm() {
  loadCss(XT + 'xterm.min.css', 'xterm');
  if (!window.Terminal) await loadScript(XT + 'xterm.min.js');
  if (!window.FitAddon) await loadScript(XT + 'xterm-addon-fit.min.js');
}

const PROF = profiles('mt.ssh.profiles');

export async function render(view, params, ctx) {
  const tabsBar = h('div', { class: 'mt-tabs' });
  const termArea = h('div', { class: 'mt-term' });
  const st = status('Bağlı değil');
  const sessions = [];
  let active = null;

  // --- Bağlan formu ---
  const host = inp({ cls: 'w-m', placeholder: 'sunucu.example.com', autocomplete: 'off' });
  const port = inp({ cls: 'w-s', type: 'number', value: '22', min: 1, max: 65535 });
  const user = inp({ cls: 'w-m', placeholder: 'kullanıcı', autocomplete: 'off' });
  const mode = sel([['password', 'Parola'], ['key', 'Özel anahtar']], 'password');
  const pass = inp({ cls: 'w-m', type: 'password', placeholder: 'parola', autocomplete: 'new-password' });
  const key = h('textarea', { class: 'mt-area', placeholder: '-----BEGIN OPENSSH PRIVATE KEY----- …', style: { display: 'none', minHeight: '60px', width: '320px' } });
  mode.addEventListener('change', () => { const k = mode.value === 'key'; key.style.display = k ? '' : 'none'; pass.placeholder = k ? 'anahtar parolası (varsa)' : 'parola'; });
  const profSel = sel([['', '— Profil —']], '');
  const refreshProfiles = () => { clear(profSel, h('option', { value: '' }, '— Profil —'), PROF.list().map(p => h('option', { value: p.name }, p.name))); };
  refreshProfiles();
  profSel.addEventListener('change', () => {
    const p = PROF.list().find(x => x.name === profSel.value);
    if (!p) return;
    host.value = p.host; port.value = p.port; user.value = p.username; mode.value = p.mode || 'password'; mode.dispatchEvent(new Event('change'));
    pass.focus();
  });
  const saveProf = () => {
    if (!host.value.trim() || !user.value.trim()) return toastError(new Error('Sunucu ve kullanıcı girin'));
    PROF.save({ name: `${user.value.trim()}@${host.value.trim()}:${port.value}`, host: host.value.trim(), port: Number(port.value) || 22, username: user.value.trim(), mode: mode.value });
    refreshProfiles(); toast('Profil kaydedildi (parolasız)');
  };
  const delProf = () => { if (profSel.value) { PROF.remove(profSel.value); refreshProfiles(); toast('Profil silindi'); } };

  const connect = async () => {
    const hv = host.value.trim(), uv = user.value.trim();
    if (!hv || !uv) return toastError(new Error('Sunucu ve kullanıcı girin'));
    if (mode.value === 'key' && !key.value.trim()) return toastError(new Error('Özel anahtarı yapıştırın'));
    await openSession({ host: hv, port: Number(port.value) || 22, username: uv, password: pass.value, key: mode.value === 'key' ? key.value : '' });
    pass.value = '';
  };
  host.addEventListener('keydown', e => e.key === 'Enter' && connect());
  pass.addEventListener('keydown', e => e.key === 'Enter' && connect());

  const form = h('div', { class: 'mt-form' },
    lab('Profil', profSel), lab('Sunucu', host), lab('Port', port), lab('Kullanıcı', user), lab('Kimlik', mode), lab('Parola', pass), lab('Anahtar', key),
    btn('Bağlan', { cls: 'primary', onclick: connect }),
    btn('Profili kaydet', { onclick: saveProf, title: 'Parola kaydedilmez' }),
    btn('Profili sil', { cls: 'sm', onclick: delProf }));

  // --- Sekmeler ---
  const drawTabs = () => {
    clear(tabsBar, sessions.map(s => h('button', { class: `mt-tab ${s === active ? 'on' : ''}`, type: 'button', onclick: () => show(s) },
      h('span', { class: `dot ${s.state}` }), s.label,
      h('span', { class: 'x', title: 'Kapat', onclick: e => { e.stopPropagation(); closeSession(s); } }, '×'))),
    sessions.length ? h('span', { class: 'mt-bar right' },
      btn('Kopyala', { cls: 'sm', onclick: () => copySel(), title: 'Seçili metni kopyala (Ctrl+Shift+C)' }),
      btn('Yapıştır', { cls: 'sm', onclick: () => paste(), title: 'Panodan yapıştır (Ctrl+Shift+V)' }),
      btn('Temizle', { cls: 'sm', onclick: () => active?.term.clear() })) : null);
  };
  const show = s => {
    active = s;
    sessions.forEach(x => { x.el.style.display = x === s ? '' : 'none'; });
    drawTabs();
    setStatus(st, s.state === 'ok' ? `Bağlı: ${s.label}` : s.state === 'err' ? `Kapandı: ${s.label}` : 'Bağlanıyor…', s.state);
    setTimeout(() => { try { s.fit.fit(); s.term.focus(); } catch { /* */ } }, 30);
  };
  const copySel = async () => {
    const sTxt = active?.term.getSelection();
    if (!sTxt) return toast('Seçili metin yok');
    try { await navigator.clipboard.writeText(sTxt); toast('Kopyalandı'); } catch { toastError(new Error('Pano erişimi yok')); }
  };
  const paste = async () => {
    try { const txt = await navigator.clipboard.readText(); if (txt && active?.ws.readyState === 1) active.ws.send(JSON.stringify({ t: 'i', d: txt })); } catch { toastError(new Error('Pano okunamadı; Ctrl+Shift+V deneyin')); }
  };
  const closeSession = s => {
    try { s.ws.close(); } catch { /* */ }
    try { s.term.dispose(); } catch { /* */ }
    s.el.remove();
    const i = sessions.indexOf(s); if (i >= 0) sessions.splice(i, 1);
    if (active === s) { active = null; sessions.length ? show(sessions[Math.max(0, i - 1)]) : (drawTabs(), setStatus(st, 'Bağlı değil')); }
    else drawTabs();
  };

  async function openSession(c) {
    try { await loadXterm(); } catch (e) { return toastError(e); }
    const el = h('div', { style: { height: '100%' } });
    termArea.append(el);
    const term = new window.Terminal({
      cursorBlink: true, fontSize: 13.5, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', scrollback: 8000,
      theme: { background: '#0b1020', foreground: '#e6eefb', cursor: '#6fb6ff', selectionBackground: 'rgba(59,130,246,.4)' },
    });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(el);
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/tools/ssh`);
    const s = { label: `${c.username}@${c.host}`, term, fit, ws, el, state: '' };
    sessions.push(s);
    show(s);
    try { fit.fit(); } catch { /* */ }
    ws.onopen = () => {
      ws.send(JSON.stringify({ t: 'connect', host: c.host, port: c.port, username: c.username, password: c.password, key: c.key, rows: term.rows, cols: term.cols }));
      term.focus();
    };
    let gotData = false;
    ws.onmessage = e => {
      term.write(e.data);
      if (!gotData) { gotData = true; }
      if (s.state !== 'ok' && !/\x1b\[31m/.test(e.data) && !/bağlanılıyor/.test(e.data)) { s.state = 'ok'; if (active === s) show(s); else drawTabs(); }
    };
    ws.onclose = () => { s.state = 'err'; term.write('\r\n\x1b[90m[bağlantı kapandı]\x1b[0m\r\n'); if (active === s) show(s); else drawTabs(); };
    ws.onerror = () => { s.state = 'err'; drawTabs(); };
    term.onData(d => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: 'i', d })); });
    term.onResize(({ cols, rows }) => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: 'r', c: cols, r: rows })); });
    // Kopyala/yapıştır kısayolları (Ctrl+Shift+C / Ctrl+Shift+V); seçim varken Ctrl+C kopyalar
    term.attachCustomKeyEventHandler(ev => {
      if (ev.type !== 'keydown') return true;
      if (ev.ctrlKey && ev.shiftKey && ev.code === 'KeyC') { copySel(); return false; }
      if (ev.ctrlKey && ev.shiftKey && ev.code === 'KeyV') { paste(); return false; }
      if (ev.ctrlKey && !ev.shiftKey && ev.code === 'KeyC' && term.hasSelection()) { copySel(); term.clearSelection(); return false; }
      return true;
    });
  }

  // Yeniden boyutlama: pencere + kabuk gözlemcisi
  const onWin = () => { try { active?.fit.fit(); } catch { /* */ } };
  window.addEventListener('resize', onWin);
  const ro = new ResizeObserver(onWin);
  ro.observe(termArea);
  onLeave(() => { window.removeEventListener('resize', onWin); ro.disconnect(); sessions.slice().forEach(s => { try { s.ws.close(); } catch { /* */ } try { s.term.dispose(); } catch { /* */ } }); });

  clear(view,
    pageHead('SSH Master', { back: '#/tools', sub: 'Tarayıcıdan SSH — çoklu sekme, kopyala/yapıştır', right: st }),
    shell(form, tabsBar, termArea, h('div', { class: 'small muted' }, 'Parola ve anahtar yalnız bu bağlantı için kullanılır; sunucuya ya da veritabanına kaydedilmez. İlk bağlantıda sunucu anahtarı kabul edilir, sonradan değişirse reddedilir.')));
  try {
    const r = await api.get('/api/tools/ssh/status');
    if (!r.available) setStatus(st, 'Sunucuda ssh istemcisi yok', 'err');
  } catch (e) { toastError(e); }
}
