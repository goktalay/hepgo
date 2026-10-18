// Araçlar › VOLFAI: oyun HEPGO'nun kendi static'inde (static/mt/volfai/, goktalay/Volfia birebir; hesap katmanı HEPGO oturumu).
// Aynı-origin iframe (CSP frame-ancestors 'self' izinli; engellenen dış origin'di), tam yükseklik, tam ekran + "Yeni pencerede aç".
import { clear, h, pageHead } from '../ui.js';
import { btn, shell } from './tool_mt.js';

export const VOLFAI_URL = '/static/mt/volfai/index.html';

export async function render(view) {
  const frame = h('iframe', { class: 'mt-frame', src: VOLFAI_URL, allow: 'fullscreen; gamepad; autoplay', allowfullscreen: true, title: 'VOLFAI', loading: 'eager' });
  const bar = h('div', { class: 'mt-bar' },
    btn('Yeni pencerede aç', { cls: 'primary', onclick: () => window.open(VOLFAI_URL, '_blank', 'noopener') }),
    btn('Tam ekran', { onclick: () => { try { (frame.requestFullscreen || frame.webkitRequestFullscreen)?.call(frame); } catch { /* */ } } }),
    btn('Yeniden yükle', { onclick: () => { frame.src = VOLFAI_URL; } }),
    h('span', { class: 'mt-status' }, 'İlerleme, HEPCOIN ve hangar HEPGO hesabınızda saklanır'));
  clear(view,
    pageHead('VOLFAI', { back: '#/tools', sub: 'Volfied’in dokunmatik yeniden yapımı — HEPGO içinde' }),
    shell(bar, frame));
}
