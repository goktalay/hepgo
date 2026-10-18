// Araçlar › Master Tool web sürümleri: masaüstü uygulamanın renderer'ı (static/mt/<app>/) aynı-origin iframe ile
// Araçlar alanına tam yükseklikte gömülür. Oturum HEPGO çerezidir; köprü (static/mt/mtcore.js + bridge.js) preload yerine geçer.
// Rotalar: #/tools/ssh → index.html · #/tools/ssh/term/<id,id> → terminal.html?ids= · #/tools/ftp/site/<id> → site.html?id=
import { clear, h, pageHead } from '../ui.js';

const APPS = {
  sshmaster: { title: 'SSH Master', sub: 'Masaüstü SSH Master ile aynı arayüz — bağlantılar HEPGO hesabınızda saklanır', routes: { term: (p) => `terminal.html?ids=${encodeURIComponent(p)}` } },
  ftpmaster: { title: 'FTP Masters', sub: 'Masaüstü FTP Masters ile aynı arayüz — siteler HEPGO hesabınızda saklanır', routes: { site: (p) => `site.html?id=${encodeURIComponent(p)}` } },
};

export function renderFrame(view, app, params) {
  const def = APPS[app];
  const route = def.routes[params[0]];
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
