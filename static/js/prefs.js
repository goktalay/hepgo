// Kullanıcı ayarlarını uygular (Ayarlar sayfası yazar; users.prefs.settings). Tema ve yazı boyutu ayrıca cihazda saklanır ki
// giriş ekranı da aynı açılsın.
import { setScreensaver } from './screensaver.js';
import { setSoundSettings } from './sounds.js';

let current = {};
let currentUser = null;
const media = matchMedia('(prefers-color-scheme: dark)');

export const settings = () => current;

function applyTheme() {
  const t = current.theme || 'light';
  const dark = t === 'dark' || (t === 'system' && media.matches);
  if (dark) document.documentElement.dataset.theme = 'dark'; else delete document.documentElement.dataset.theme;
  try { localStorage.setItem('caymaz.theme', t); } catch { /* gizli pencere */ }
  applyUiCustom();   // tema değişince kişisel renkler + toolbar hizası yeniden uygulanır
}
media.addEventListener?.('change', () => { if (current.theme === 'system') applyTheme(); });

// Kişiselleştirilebilir MERKEZİ arayüz değişkenleri (aktif temaya göre): üst bar, alt bar (başlık bandı), footer, body zemini, vurgu.
// "Renksiz" bar = 'var(--bg)' (body zeminiyle aynı). Modüllerin kendi içeriğine dokunulmaz.
const UI_VARS = { header: '--header-bg', band: '--head-band', footer: '--footer-bg', bg: '--bg', accent: '--primary' };
export function activeThemeKey() {
  const t = current.theme || 'light';
  return (t === 'dark' || (t === 'system' && media.matches)) ? 'dark' : 'light';
}
export function applyUiCustom() {
  const root = document.documentElement;
  let align = current.toolbarAlign;
  if (!align) { try { align = localStorage.getItem('caymaz.toolbarAlign'); } catch { /* */ } }
  root.dataset.toolbarAlign = ['left', 'center', 'right'].includes(align) ? align : 'center';
  let colors = current.colors;
  if (!colors) { try { colors = JSON.parse(localStorage.getItem('caymaz.uiColors') || 'null'); } catch { /* */ } }
  const c = (colors && colors[activeThemeKey()]) || {};
  for (const [k, varName] of Object.entries(UI_VARS)) {
    if (c[k]) root.style.setProperty(varName, c[k]); else root.style.removeProperty(varName);
  }
  // vurgu rengi değişince, üzerine gelince koyulaşan ton da ona göre
  if (c.accent) root.style.setProperty('--primary-hover', c.accent); else root.style.removeProperty('--primary-hover');
  // Gövde (orta alan) arka plan deseni/animasyonu — merkezi; CSS html[data-bg="..."] ile çizilir
  let bg = current.background;
  if (bg == null) { try { bg = localStorage.getItem('caymaz.uiBg') || ''; } catch { bg = ''; } }
  if (bg) root.dataset.bg = bg; else delete root.dataset.bg;
}

// Masaüstü bildirimi CİHAZ-BAZLIDIR (senkron değil): her cihazda ayrı açılır ve o cihazın tarayıcı izni gerekir.
export const deviceNotify = () => { try { return localStorage.getItem('caymaz.desktopNotify') === '1'; } catch { return false; } };
export function setDeviceNotify(on) { try { on ? localStorage.setItem('caymaz.desktopNotify', '1') : localStorage.removeItem('caymaz.desktopNotify'); } catch { /* */ } if (current) current.desktop = !!on; }

export function applySettings(s, user) {
  current = s || {};
  current.desktop = deviceNotify();   // senkron ayardan değil, bu cihazın yerel tercihinden
  if (user !== undefined) currentUser = user;
  if (!current.theme) {   // eski cihaz tercihi (başlıktaki tema düğmesi) varsa korunur
    try { current.theme = localStorage.getItem('caymaz.theme') || 'light'; } catch { current.theme = 'light'; }
  }
  applyTheme();
  const root = document.documentElement;
  root.style.setProperty('--ui-scale', String(current.scale || 1));
  root.classList.toggle('ui-scaled', (current.scale || 1) !== 1);
  root.classList.toggle('reduce-motion', !!current.motion);
  root.classList.toggle('compact', !!current.compact);
  setSoundSettings(current.sound);
  setScreensaver(current.screensaver, currentUser);
}

// Masaüstü bildirimi: sekme arka plandayken (ayar açıksa ve izin verildiyse)
export function desktopNotify(title, body, onClick) {
  if (!current.desktop || !document.hidden || !('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const n = new Notification(title, { body, icon: '/static/img/logo-mark.png', tag: `${title}:${body}` });
    n.onclick = () => { window.focus(); onClick?.(); n.close(); };
  } catch { /* bazı tarayıcılar yalnızca service worker ile izin verir */ }
}

export const flashMs = () => (current.flashSec || 3) * 1000;
export const flashOn = () => current.flash !== false;
