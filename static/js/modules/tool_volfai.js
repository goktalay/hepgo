// Araçlar › VOLFAI: mastertool.download'da yayındaki oyun, tam yükseklikte iframe (tam ekran izinli) + "Yeni pencerede aç".
import { clear, h, pageHead } from '../ui.js';
import { btn, shell } from './tool_mt.js';

export const VOLFAI_URL = 'https://mastertool.download/oyunlar/volfai/';

export async function render(view) {
  const frame = h('iframe', { class: 'mt-frame', src: VOLFAI_URL, allow: 'fullscreen; gamepad; autoplay', allowfullscreen: true, title: 'VOLFAI', loading: 'eager' });
  const bar = h('div', { class: 'mt-bar' },
    btn('Yeni pencerede aç', { cls: 'primary', onclick: () => window.open(VOLFAI_URL, '_blank', 'noopener') }),
    btn('Tam ekran', { onclick: () => { try { (frame.requestFullscreen || frame.webkitRequestFullscreen)?.call(frame); } catch { /* */ } } }),
    btn('Yeniden yükle', { onclick: () => { frame.src = VOLFAI_URL; } }),
    h('span', { class: 'mt-status' }, VOLFAI_URL));
  clear(view,
    pageHead('VOLFAI', { back: '#/tools', sub: 'Master Tool oyunu — tarayıcıda' }),
    shell(bar, frame));
}
