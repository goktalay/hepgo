// Araçlar › SSH Master (web): masaüstü renderer'ı (static/mt/sshmaster/) gömülü çerçevede
import { renderFrame } from './tool_mtframe.js';

export function render(view, params) {
  return renderFrame(view, 'sshmaster', params);
}
