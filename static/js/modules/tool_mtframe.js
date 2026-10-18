// Araçlar › Master Tool web sürümleri: masaüstü uygulamanın renderer'ı (static/mt/<app>/) aynı-origin iframe ile
// Araçlar alanına tam yükseklikte gömülür. Oturum HEPGO çerezidir; köprü preload yerine geçer
// (SSH/FTP: static/mt/mtcore.js + bridge.js · SQL/Notepad/Convert: static/mt/common/hepgo.js + bridge.js).
// İki kullanım biçimi:
//  - renderFrame(view, app, params): tool_sshmaster.js / tool_ftpmaster.js çağırır. Rotalar: #/tools/ssh → index.html ·
//    #/tools/ssh/term/<id,id> → terminal.html?ids= · #/tools/ftp/site/<id> → site.html?id=
//  - render(view): tools.js'de sql/notepad/convert satırları doğrudan bu modülü yükler; uygulama hash'ten (#/tools/<key>) seçilir.
import { clear, h, pageHead } from '../ui.js';
import { btn, shell } from './tool_mt.js';

// SSH Master / FTP Masters: IPC kalıbı, alt sayfa rotaları
const FRAME_APPS = {
  sshmaster: { title: 'SSH Master', sub: 'Masaüstü SSH Master ile aynı arayüz — bağlantılar HEPGO hesabınızda saklanır', routes: { term: (p) => `terminal.html?ids=${encodeURIComponent(p)}` } },
  ftpmaster: { title: 'FTP Masters', sub: 'Masaüstü FTP Masters ile aynı arayüz — siteler HEPGO hesabınızda saklanır', routes: { site: (p) => `site.html?id=${encodeURIComponent(p)}` } },
};

// SQL / Notepad / Convert Master: tek sayfa; pencereler uygulamanın kendi pencere yöneticisinde (iframe.mt-win)
const HASH_APPS = {
  sql: { app: 'sqlmaster', title: 'SQL Master', sub: 'Çok veritabanlı SQL istemcisi — masaüstü sürümünün web karşılığı', url: '/static/mt/sqlmaster/renderer/main/index.html' },
  notepad: { app: 'notepadmaster', title: 'Notepad Master', sub: 'SSH, FTP ve sunucudaki klasörlerde kod editörü — masaüstü sürümünün web karşılığı', url: '/static/mt/notepadmaster/index.html' },
  convert: { app: 'convertmaster', title: 'Convert Master', sub: 'Resim, video ve ses dönüştürücü — masaüstü sürümünün web karşılığı', url: '/static/mt/convertmaster/index.html' },
};

export function renderFrame(view, app, params) {
  const def = FRAME_APPS[app];
  const route = def.routes[(params || [])[0]];
  const page = route && params[1] ? route(params[1]) : 'index.html';
  const frame = h('iframe', {
    class: 'mt-frame', src: `/static/mt/${app}/${page}`, title: def.title,
    allow: 'clipboard-read; clipboard-write',
    style: { flex: '1 1 auto', width: '100%', minHeight: '480px', border: '1px solid var(--border)', borderRadius: '12px', background: '#0b0f17' },
  });
  // Araçlar başlık bandı korunur; altında renderer tam yükseklik (üst bant + alt bant + sayfa boşlukları düşülür)
  const wrap = h('div', { class: 'mt-frame-wrap', style: { display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px - 42px - 40px)', minHeight: '560px' } },
    pageHead(def.title, { back: '#/tools', sub: def.sub }), frame);
  clear(view, wrap);
}

export async function render(view) {
  const key = (location.hash.split('/')[2] || '').split('?')[0];
  const a = HASH_APPS[key] || HASH_APPS.sql;
  const frame = h('iframe', { class: 'mt-frame mt-app-frame', src: a.url, title: a.title, allow: 'clipboard-read; clipboard-write; fullscreen', loading: 'eager' });
  const bar = h('div', { class: 'mt-bar' },
    btn('Yeni sekmede aç', { cls: 'primary', onclick: () => window.open(a.url, '_blank', 'noopener') }),
    btn('Tam ekran', { onclick: () => { try { (frame.requestFullscreen || frame.webkitRequestFullscreen)?.call(frame); } catch { /* */ } } }),
    btn('Yeniden yükle', { onclick: () => { frame.src = a.url; } }),
    h('span', { class: 'mt-status' }, 'Verileriniz HEPGO hesabınızda saklanır'));
  clear(view, pageHead(a.title, { back: '#/tools', sub: a.sub }), shell(bar, frame));
}
