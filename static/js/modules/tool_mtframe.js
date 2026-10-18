// Araçlar › SQL Master / Notepad Master / Convert Master: masaüstü Master Tool uygulamalarının orijinal arayüzleri
// (static/mt/<uygulama>/ — renderer birebir, preload yerine bridge.js) aynı kökenli iframe'de tam yükseklikte açılır.
// Oturum HEPGO'nunkidir; uygulama verileri kullanıcı başına sunucuda saklanır (app/routers/tools_mt.py).
import { clear, h, pageHead } from '../ui.js';
import { btn, shell } from './tool_mt.js';

const APPS = {
  sql: { app: 'sqlmaster', title: 'SQL Master', sub: 'Çok veritabanlı SQL istemcisi — masaüstü sürümünün web karşılığı', url: '/static/mt/sqlmaster/renderer/main/index.html' },
  notepad: { app: 'notepadmaster', title: 'Notepad Master', sub: 'SSH, FTP ve sunucudaki klasörlerde kod editörü — masaüstü sürümünün web karşılığı', url: '/static/mt/notepadmaster/index.html' },
  convert: { app: 'convertmaster', title: 'Convert Master', sub: 'Resim, video ve ses dönüştürücü — masaüstü sürümünün web karşılığı', url: '/static/mt/convertmaster/index.html' },
};

export async function render(view) {
  const key = (location.hash.split('/')[2] || '').split('?')[0];
  const a = APPS[key] || APPS.sql;
  const frame = h('iframe', { class: 'mt-frame mt-app-frame', src: a.url, title: a.title, allow: 'clipboard-read; clipboard-write; fullscreen', loading: 'eager' });
  const bar = h('div', { class: 'mt-bar' },
    btn('Yeni sekmede aç', { cls: 'primary', onclick: () => window.open(a.url, '_blank', 'noopener') }),
    btn('Tam ekran', { onclick: () => { try { (frame.requestFullscreen || frame.webkitRequestFullscreen)?.call(frame); } catch { /* */ } } }),
    btn('Yeniden yükle', { onclick: () => { frame.src = a.url; } }),
    h('span', { class: 'mt-status' }, 'Verileriniz HEPGO hesabınızda saklanır'));
  clear(view, pageHead(a.title, { back: '#/tools', sub: a.sub }), shell(bar, frame));
}
