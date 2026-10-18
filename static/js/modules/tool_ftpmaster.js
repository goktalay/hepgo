// Araçlar › FTP Masters (web): masaüstü renderer'ı (static/mt/ftpmaster/) gömülü çerçevede
import { renderFrame } from './tool_mtframe.js';

export function render(view, params) {
  return renderFrame(view, 'ftpmaster', params);
}
