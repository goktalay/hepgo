// TV / kiosk ekranı (#/tv/printers): şirketteki büyük monitörler için yazıcı odasının 3B hâli, tam ekran.
// Başlık, alt çubuk, bildirim, uyarı yok; kamera odada sürekli dolaşır (bkz. printers3d tour). Veri canlı (birkaç saniyede bir),
// ekran kapanmasın diye Wake Lock; imleç gizlenir; bağlantı koparsa kendini toparlar; yeni sürümde ve uzun çalışmada kendini yeniler.
import { api } from '../api.js';
import { PRINTER_STATES } from '../status.js';
import { clear, h } from '../ui.js';
import { STATE_COLORS, partOf, printerRoom } from './printers3d.js';

const hex = c => `#${c.toString(16).padStart(6, '0')}`;
const pad = n => String(n).padStart(2, '0');

export function renderTv(root, ctx) {
  document.title = 'Yazıcı Odası — Canlı';
  document.body.classList.add('tv-mode');
  if (!ctx.user.modules.includes('printers') && !ctx.user.modules.includes('production')) {
    clear(root, h('div', { class: 'kx-msg' }, 'Bu hesapta Yazıcı Yönetimi yetkisi yok. TV ekranı için yetkili bir hesapla giriş yapın.'));
    return;
  }
  const room = printerRoom({ canEdit: false, canOpen: false, reload: () => load() });
  const clock = h('div', { class: 'kx-clock' });
  const counts = h('div', { class: 'kx-counts' });
  const active = h('div', { class: 'kx-active' });
  const net = h('div', { class: 'kx-net', hidden: true }, 'Bağlantı bekleniyor…');
  const hint = h('div', { class: 'kx-hint' }, 'Tam ekran için ekrana tıklayın');
  const hud = h('div', { class: 'kx-hud' },
    h('div', { class: 'kx-brand' }, h('img', { src: '/static/img/logo.png', alt: '' }), h('div', null, h('b', null, 'Yazıcı Odası'), h('span', null, 'Canlı durum'))),
    clock, counts, active);
  clear(root, h('div', { class: 'kx' }, room.el, hud, net, hint));
  room.tour(true);

  // Saat
  const tick = () => {
    const d = new Date();
    clock.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  tick();
  setInterval(tick, 5000);

  // Canlı veri
  let fails = 0;
  async function load() {
    try {
      const list = await api.get('/api/printers');
      fails = 0; net.hidden = true;
      room.update(list);
      const by = {};
      for (const p of list) { const s = p.live_state || 'CEVRIMDISI'; by[s] = (by[s] || 0) + 1; }
      clear(counts, Object.keys(PRINTER_STATES).filter(k => by[k]).map(k =>
        h('span', { class: 'kx-c' }, h('i', { style: { background: hex(STATE_COLORS[k]) } }), h('b', null, by[k]), PRINTER_STATES[k].label)));
      const printing = list.filter(p => p.live_state === 'YAZDIRIYOR').sort((a, b) => (b.live_progress || 0) - (a.live_progress || 0)).slice(0, 6);
      clear(active, printing.map(p => h('div', { class: 'kx-job' },
        h('span', { class: 'kx-job-n' }, p.name), h('span', { class: 'kx-job-p' }, partOf(p) || (p.live_file || '').replace(/\.g?code$/i, '')),
        h('span', { class: 'kx-bar' }, h('i', { style: { width: `${Math.floor(p.live_progress || 0)}%` } })),
        h('b', null, `%${Math.floor(p.live_progress || 0)}`))));
    } catch {
      if (++fails >= 2) net.hidden = false;   // ağ / sunucu kesintisi: son görüntü kalır, yeniden denenir
    }
  }
  load();
  setInterval(load, 8000);

  // Yeni sürüm → kendini yenile; ayrıca 6 saatte bir (uzun süre açık kalan tarayıcıda bellek birikmesin)
  let build = null;
  setInterval(async () => {
    try {
      const s = await api.get('/api/system/status');
      if (build && s.build && s.build !== build) location.reload();
      build = s.build || build;
    } catch { /* bir sonrakinde */ }
  }, 120000);
  setTimeout(() => location.reload(), 6 * 3600 * 1000);

  // Ekran kapanmasın (destekleyen tarayıcılarda); sekme geri gelince yeniden iste
  let lock = null;
  const wake = async () => { try { lock = await navigator.wakeLock?.request('screen'); } catch { /* izin yok */ } };
  wake();
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') wake(); });

  // İmleç: 3 sn hareketsizlikte gizlenir. Tıklama: tam ekran (tarayıcı kullanıcı etkileşimi ister)
  let idle = null;
  const showCursor = () => { document.body.classList.remove('tv-nocursor'); clearTimeout(idle); idle = setTimeout(() => document.body.classList.add('tv-nocursor'), 3000); };
  addEventListener('mousemove', showCursor);
  showCursor();
  const goFull = () => { document.documentElement.requestFullscreen?.().catch(() => {}); };
  addEventListener('click', goFull);
  document.addEventListener('fullscreenchange', () => { hint.hidden = !!document.fullscreenElement; });
  setTimeout(() => { hint.classList.add('fade'); }, 8000);
  return lock;
}
