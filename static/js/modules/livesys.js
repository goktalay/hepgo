// Yönetim › Canlı Sistem: tamamen grafiklerden oluşan izleme ekranı (büyük ekranda açık bırakılır).
// Sol: Merkez Sunucu (CPU, RAM, ağ ↓/↑). Sağ: ASUS GX10 fabrika ajanı (CPU, RAM, GPU, ağ ↓/↑).
// Veri: /api/system/live (sysstat saniyelik tarih; fabrika ajanın sysstat'ından, 2 sn önbellek). Pencere: son 5 dakika.
import { api } from '../api.js';
import { clear, every, h, pageHead, toastError } from '../ui.js';
import { loadChart } from './reports.js';
import { FA } from '../fa-icons.js';

const WINDOW = 300;   // saniye (5 dk)
const C = { cpu: '#60a5fa', ram: '#a78bfa', gpu: '#f472b6', down: '#34d399', up: '#fbbf24' };
const mbit = bps => (bps == null ? '—' : bps * 8 >= 1e6 ? `${(bps * 8 / 1e6).toFixed(1)} Mbit/s` : `${Math.round(bps * 8 / 1e3)} kbit/s`);
const pct = v => (v == null ? '—' : `%${Math.round(v)}`);
const gb = b => (b == null ? '—' : `${(b / 1073741824).toFixed(1)} GB`);

export async function render(view, ctx, tabs) {
  let Chart;
  try { Chart = await loadChart(); } catch (err) { return toastError(err); }
  const page = h('div', { class: 'ls-page' });
  const fsBtn = h('button', { class: 'btn sm ls-fs', type: 'button', title: 'Tam ekran', html: `${FA.expand} Tam ekran` });
  fsBtn.addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen?.(); else page.requestFullscreen?.().catch(() => {}); });
  document.addEventListener('fullscreenchange', () => { fsBtn.innerHTML = document.fullscreenElement ? `${FA.compress} Çık` : `${FA.expand} Tam ekran`; });
  clear(view, pageHead('Yönetim', { back: '#/', sub: 'Canlı Sistem · saniyelik · son 5 dakika', tabs, right: fsBtn }), page);

  // ---- grafik kartı: başlık + büyük değer + çizgi grafik (dolgu gradyanlı)
  function chartCard(title, series, { unit = '%', max = 100, color = C.cpu } = {}) {
    const canvas = h('canvas');
    const big = h('div', { class: 'ls-big' }, '—');
    const sub = h('div', { class: 'ls-sub' }, '');
    const el = h('div', { class: 'ls-card' }, h('div', { class: 'ls-head' }, h('span', { class: 'ls-title' }, title), big), h('div', { class: 'ls-canvas' }, canvas), sub);
    const grad = (ctx2, col) => { const g = ctx2.createLinearGradient(0, 0, 0, 160); g.addColorStop(0, col + '66'); g.addColorStop(1, col + '00'); return g; };
    const chart = new Chart(canvas, {
      type: 'line',
      data: { labels: [], datasets: series.map(sr => ({ label: sr.label, data: [], borderColor: sr.color, backgroundColor: c => grad(c.chart.ctx, sr.color), borderWidth: 2, pointRadius: 0, tension: 0.35, fill: true })) },
      options: {
        animation: false, responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: series.length > 1, labels: { color: '#9aa4b5', boxWidth: 10, font: { size: 11 } } }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { min: 0, max: max || undefined, grid: { color: 'rgba(255,255,255,.06)' }, ticks: { color: '#7c8698', font: { size: 10 }, maxTicksLimit: 4, callback: v => (unit === '%' ? `${v}%` : `${v}`) } },
        },
      },
    });
    return { el, chart, big, sub };
  }
  const hostCol = (title, icon, sub) => h('section', { class: 'ls-host' }, h('div', { class: 'ls-host-h' }, h('span', { class: 'ls-ic', html: icon }), h('b', null, title), h('span', { class: 'ls-host-sub' }, sub)));

  const mk = () => ({
    cpu: chartCard('İşlemci', [{ label: 'CPU', color: C.cpu }], { color: C.cpu }),
    ram: chartCard('Bellek', [{ label: 'RAM', color: C.ram }], { color: C.ram }),
    gpu: chartCard('Ekran kartı', [{ label: 'GPU', color: C.gpu }], { color: C.gpu }),
    net: chartCard('Ağ trafiği', [{ label: 'İndirme ↓', color: C.down }, { label: 'Yükleme ↑', color: C.up }], { unit: 'Mbit/s', max: null }),
  });
  const central = mk(), factory = mk();
  const colC = hostCol('Merkez Sunucu', FA.server, 'HEPGO uygulama sunucusu');
  const colF = hostCol('ASUS GX10', FA.microchip, 'Fabrika ajanı · NVR / yüz tanıma');
  const unavailable = h('div', { class: 'ls-unavail', hidden: true }, 'Fabrika ajanına ulaşılamıyor');
  colC.append(central.cpu.el, central.ram.el, central.net.el);
  colF.append(unavailable, factory.cpu.el, factory.ram.el, factory.gpu.el, factory.net.el);
  page.append(h('div', { class: 'ls-grid' }, colC, colF));

  // ---- veri akışı: tarih noktaları birikir, pencere 5 dk
  const hist = { central: [], factory: [] };
  let sinceC = 0, sinceF = 0;
  const push = (key, points) => { if (!points?.length) return; const arr = hist[key]; arr.push(...points); const cut = (arr[arr.length - 1].t || 0) - WINDOW; hist[key] = arr.filter(p => (p.t || 0) >= cut); };
  const paint = (set, arr, snap) => {
    const labels = arr.map(p => p.t);
    const upd = (card, keyFn, bigText, subText) => { card.chart.data.labels = labels; card.chart.data.datasets.forEach((ds, i) => { ds.data = arr.map(p => keyFn(p, i)); }); card.chart.update('none'); card.big.textContent = bigText; card.sub.textContent = subText; };
    const last = arr[arr.length - 1] || {};
    upd(set.cpu, p => p.cpu, pct(last.cpu), snap?.cpus ? `${snap.cpus} çekirdek` : '');
    upd(set.ram, p => p.ram, pct(last.ram), snap?.ram_total ? `${gb(snap.ram_used)} / ${gb(snap.ram_total)}` : '');
    if (set.gpu.el.isConnected) { upd(set.gpu, p => p.gpu, pct(last.gpu), snap?.gpu_name ? `${snap.gpu_name}${snap.gpu_temp != null ? ` · ${snap.gpu_temp}°C` : ''}` : 'GPU yok'); set.gpu.el.hidden = !snap?.gpu_name; }
    upd(set.net, (p, i) => (i === 0 ? p.rx : p.tx) == null ? null : +((i === 0 ? p.rx : p.tx) * 8 / 1e6).toFixed(3),
      `↓ ${mbit(last.rx)} · ↑ ${mbit(last.tx)}`, snap?.net_rx_total != null ? `Toplam ↓ ${gb(snap.net_rx_total)} · ↑ ${gb(snap.net_tx_total)}` : (last.rx == null ? 'Ağ verisi için ajan güncellemesi gerekir' : ''));
  };
  let busy = false;
  async function tick() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const d = await api.get(`/api/system/live?since=${sinceC}&factory_since=${sinceF}`);
      push('central', d.central?.history); if (hist.central.length) sinceC = hist.central[hist.central.length - 1].t;
      paint(central, hist.central, d.central);
      if (d.factory) {
        unavailable.hidden = !d.factory.unavailable; if (d.factory.unavailable) unavailable.textContent = `Fabrika ajanına ulaşılamıyor: ${d.factory.unavailable}`;
        push('factory', d.factory.history); if (hist.factory.length) sinceF = hist.factory[hist.factory.length - 1].t;
        paint(factory, hist.factory, d.factory);
      } else { colF.hidden = true; }
    } catch (err) { unavailable.hidden = false; unavailable.textContent = err.message; }
    finally { busy = false; }
  }
  await tick();
  every(1000, tick);
}
