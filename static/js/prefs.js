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
}
media.addEventListener?.('change', () => { if (current.theme === 'system') applyTheme(); });

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
