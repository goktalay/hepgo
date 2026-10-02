// Alt durum çubuğu: aktif kullanıcı, sunucu diski, CPU/GPU ve RAM (1 sn'de bir, son 60 sn grafik).
// Her bilgi, bilgisayarda üzerine gelince, tablette dokununca yukarı açılan kapatılabilir bir ayrıntı kutucuğu açar.
import { api } from './api.js';
import { openChat } from './chat.js';
import { playEvent } from './sounds.js';
import { avatar, clear, h } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';
const W = 120, H = 26, N = 60;
let timer;

const gb = b => (b >= 1e12 ? `${(b / 1e12).toFixed(2)} TB` : `${Math.round(b / 1e9)} GB`);
const pct = v => (v == null ? '—' : `%${Math.round(v)}`);

function sparkline(series, w = W, hh = H, n = N) {
  // series: [{ cls }] — her biri bir çizgi; set(values[][]) ile güncellenir
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hh}`);
  svg.setAttribute('class', w === W ? 'sb-spark' : 'sb-bigspark');
  svg.setAttribute('preserveAspectRatio', 'none');
  const lines = series.map(s => {
    const area = document.createElementNS(NS, 'path');
    area.setAttribute('class', `sb-area ${s.cls}`);
    const line = document.createElementNS(NS, 'polyline');
    line.setAttribute('class', `sb-line ${s.cls}`);
    svg.append(area, line);
    return { area, line };
  });
  svg.set = values => values.forEach((vals, i) => {
    const pts = vals.map((v, j) => [w - (vals.length - 1 - j) * (w / (n - 1)), hh - 1 - (Math.max(0, Math.min(100, v ?? 0)) / 100) * (hh - 2)]);
    const str = pts.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
    lines[i].line.setAttribute('points', str);
    lines[i].area.setAttribute('d', pts.length ? `M${pts[0][0]},${hh} L${str.replaceAll(' ', ' L')} L${pts[pts.length - 1][0]},${hh}Z` : '');
  });
  return svg;
}

export function statusBar() {
  let since = 0, history = [], long = [], busy = false, last = null, online = null;
  const users = h('b', null, '—');
  const diskFill = h('span', { class: 'sb-disk-fill' });
  const diskText = h('span', { class: 'sb-val' }, '—');
  const cpuVal = h('b', { class: 'sb-cpu' }, '—');
  const gpuVal = h('b', { class: 'sb-gpu' }, '—');
  const ramVal = h('b', { class: 'sb-ram' }, '—');
  const cpuSpark = sparkline([{ cls: 'cpu' }, { cls: 'gpu' }]);
  const ramSpark = sparkline([{ cls: 'ram' }]);
  const diskBox = h('span', { class: 'sb-item sb-disk' }, h('span', { class: 'sb-label' }, 'Disk'),
    h('span', { class: 'sb-disk-bar' }, diskFill), diskText);
  const cpuBox = h('span', { class: 'sb-item' }, h('span', { class: 'sb-label' }, 'CPU'), cpuVal,
    h('span', { class: 'sb-label' }, 'GPU'), gpuVal, cpuSpark);
  const ramBox = h('span', { class: 'sb-item' }, h('span', { class: 'sb-label' }, 'RAM'), ramVal, ramSpark);

  const bar = h('div', { class: 'statusbar' },
    h('span', { class: 'sb-item sb-users', title: 'Son 2 dakikada sistemde işlem yapan kullanıcılar' },
      h('span', { class: 'sb-dot' }), h('span', { class: 'sb-label' }, 'Aktif kullanıcı'), users),
    diskBox, cpuBox, ramBox);

  let mounted = false;
  const tick = async () => {
    if (bar.isConnected) mounted = true;
    else if (mounted) { clearInterval(timer); return; }   // kabuk yeniden çizildi / oturum kapandı
    if (document.hidden) return;   // sekme arka plandayken sorgulama
    if (busy) return;   // yavaş bağlantıda istekler üst üste binmesin
    let s;
    busy = true;
    try { s = await api.get(`/api/system/status?since=${since}`); } catch { return; } finally { busy = false; }
    if (s.build) window.dispatchEvent(new CustomEvent('caymaz:build', { detail: s.build }));   // sürüm değişimini bildir
    users.textContent = s.active_users;
    // Kullanıcı girdi / ayrıldı sesi (ilk okumada çalmaz)
    const ids = new Set(s.online_ids || []);
    if (online) {
      if ([...ids].some(i => !online.has(i))) playEvent('online');
      else if ([...online].some(i => !ids.has(i))) playEvent('offline');
    }
    online = ids;
    if (s.disk_total) {
      const used = s.disk_used / s.disk_total * 100;
      diskFill.style.width = `${used.toFixed(1)}%`;
      diskFill.classList.toggle('warn', used >= 80);
      diskFill.classList.toggle('bad', used >= 92);
      diskText.textContent = `${gb(s.disk_used)} dolu · ${gb(s.disk_free)} boş`;
    }
    last = s;
    long = long.concat(s.history).slice(-300);
    history = long.slice(-N);
    if (history.length) since = history[history.length - 1].t;
    cpuVal.textContent = pct(s.cpu);
    gpuVal.textContent = pct(s.gpu);
    ramVal.textContent = pct(s.ram_total ? s.ram_used / s.ram_total * 100 : null);
    cpuSpark.set([history.map(p => p.cpu), history.map(p => p.gpu)]);
    ramSpark.set([history.map(p => p.ram)]);
    if (openPop?.live) openPop.live();
  };

  // ---------- ayrıntı kutucukları
  const hover = matchMedia('(hover: hover) and (pointer: fine)').matches;
  let openPop = null, closeTimer;
  const close = () => { if (openPop) { openPop.el.remove(); openPop.item.classList.remove('open'); openPop = null; } };
  const kv = rows => h('dl', { class: 'sbp-kv' }, rows.filter(Boolean).map(([k, v]) => [h('dt', null, k), h('dd', null, v)]).flat());
  const ago = sec => (sec < 60 ? 'şimdi' : `${Math.round(sec / 60)} dk önce`);
  const upt = sec => { const d = Math.floor(sec / 86400), hr = Math.floor((sec % 86400) / 3600); return d ? `${d} gün ${hr} sa` : `${hr} sa ${Math.floor((sec % 3600) / 60)} dk`; };
  const KINDS = { camfaces: 'Kamera yüz kayıtları', cargo: 'Kargo fotoğrafları', documents: 'Evraklar', errors: 'Hata fotoğrafları', flightlogs: 'Uçuş logları',
    logos: 'Firma logoları', videos: 'Uçuş videoları', avatars: 'Profil fotoğrafları' };
  const size = b => (b >= 1e9 ? gb(b) : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);

  const POPS = {
    users: { title: 'Aktif kullanıcılar', async fill(body) {
      const d = await api.get('/api/system/details?what=users');
      clear(body, h('div', { class: 'sbp-sub' }, `${d.users.length} kişi çevrimiçi · bugün ${d.logins_today} kişi giriş yaptı · mesajlaşmak için kişiye tıklayın`),
        d.users.length ? h('ul', { class: 'sbp-users' }, d.users.map(u => h('li', d.me === u.id ? null : {
          class: 'chat-able', title: `${u.full_name} ile mesajlaş`, onclick: () => { close(); openChat(u); } }, avatar(u, 'sm'),
          h('div', { class: 'grow' }, h('b', null, u.full_name, d.me === u.id ? h('span', { class: 'muted' }, ' (siz)') : null),
            h('small', null, u.page ? `${u.page} · ${ago(u.seconds_ago)}` : `${u.roles.join(', ') || '—'} · ${ago(u.seconds_ago)}`)),
          d.me === u.id ? null : h('span', { class: 'sbp-chat', 'aria-hidden': 'true' }, '💬'))))
          : h('div', { class: 'sbp-sub' }, 'Şu an kimse yok'));
    } },
    disk: { title: 'Sunucu diski', async fill(body) {
      const d = await api.get('/api/system/details?what=disk');
      const used = d.disk_total ? 100 * d.disk_used / d.disk_total : 0;
      clear(body, h('div', { class: 'sbp-big' }, h('b', null, `%${used.toFixed(1)}`), h('span', null, 'dolu')),
        h('div', { class: 'sbp-disk' }, h('i', { class: used >= 92 ? 'bad' : used >= 80 ? 'warn' : '', style: { width: `${used}%` } })),
        kv([['Dolu', gb(d.disk_used)], ['Boş', gb(d.disk_free)], ['Toplam', gb(d.disk_total)],
          d.db_size != null ? ['Veritabanı', size(d.db_size)] : null, d.uploads_total != null ? ['Yüklenen dosyalar', size(d.uploads_total)] : null,
          d.backups_size != null ? ['Yedekler', size(d.backups_size)] : null]),
        d.uploads ? h('div', { class: 'sbp-bars' }, d.uploads.filter(k => k.size).sort((a, b) => b.size - a.size).map(k => h('div', null,
          h('span', null, KINDS[k.kind] || k.kind), h('b', null, size(k.size)), h('i', { style: { width: `${Math.max(1, 100 * k.size / (d.uploads_total || 1))}%` } })))) : null);
    } },
    cpu: { title: 'İşlemci ve ekran kartı', wide: true, async fill(body) {
      const d = await api.get('/api/system/details?what=server');
      const chart = sparkline([{ cls: 'cpu' }, { cls: 'gpu' }], 360, 110, 300);
      const vals = h('div', { class: 'sbp-now' });
      clear(body, vals, chart, h('div', { class: 'sbp-axis' }, h('span', null, '5 dk önce'), h('span', null, 'şimdi')),
        kv([['Çekirdek', d.cpus], ['Yük (1/5/15 dk)', d.load.map(x => x.toFixed(2)).join(' / ')], d.gpu_name ? ['Ekran kartı', d.gpu_name] : null,
          d.gpu_temp != null ? ['GPU sıcaklığı', `${d.gpu_temp} °C`] : null, d.uptime_s ? ['Sunucu açık', upt(d.uptime_s)] : null]));
      return () => {
        chart.set([long.map(p => p.cpu), long.map(p => p.gpu)]);
        const avg = k => (long.length ? Math.round(long.reduce((a, p) => a + (p[k] || 0), 0) / long.length) : 0);
        const max = k => Math.round(Math.max(0, ...long.map(p => p[k] || 0)));
        clear(vals, h('div', { class: 'cpu' }, h('span', null, 'CPU'), h('b', null, pct(last?.cpu)), h('small', null, `ort. %${avg('cpu')} · en yüksek %${max('cpu')}`)),
          h('div', { class: 'gpu' }, h('span', null, 'GPU'), h('b', null, pct(last?.gpu)), h('small', null, `ort. %${avg('gpu')} · en yüksek %${max('gpu')}`)));
      };
    } },
    ram: { title: 'Bellek (RAM)', wide: true, async fill(body) {
      const chart = sparkline([{ cls: 'ram' }], 360, 110, 300);
      const vals = h('div', { class: 'sbp-now' });
      clear(body, vals, chart, h('div', { class: 'sbp-axis' }, h('span', null, '5 dk önce'), h('span', null, 'şimdi')));
      return () => {
        chart.set([long.map(p => p.ram)]);
        const s = last || {};
        clear(vals, h('div', { class: 'ram' }, h('span', null, 'Kullanılan'), h('b', null, s.ram_total ? gb(s.ram_used) : '—'),
          h('small', null, s.ram_total ? `%${Math.round(100 * s.ram_used / s.ram_total)} · toplam ${gb(s.ram_total)}` : '')),
        h('div', null, h('span', null, 'Boş'), h('b', null, s.ram_total ? gb(s.ram_total - s.ram_used) : '—'),
          h('small', null, `5 dk en yüksek %${Math.round(Math.max(0, ...long.map(p => p.ram || 0)))}`)));
      };
    } },
  };

  const open = async (key, item) => {
    if (openPop?.key === key) return;
    close();
    const p = POPS[key];
    const body = h('div', { class: 'sbp-body' }, h('div', { class: 'sbp-sub' }, 'Yükleniyor…'));
    const el = h('div', { class: `sb-pop ${p.wide ? 'wide' : ''}`, role: 'dialog', onclick: e => e.stopPropagation(),
      onmouseenter: () => clearTimeout(closeTimer), onmouseleave: () => { if (hover && !openPop?.pinned) closeTimer = setTimeout(close, 300); } },
    h('div', { class: 'sbp-head' }, h('b', null, p.title), h('button', { type: 'button', class: 'sbp-x', title: 'Kapat', onclick: close }, '×')), body);
    document.body.append(el);   // durum çubuğu dar ekranda taşanı gizler; kutucuk sayfanın üstünde durur
    const r = item.getBoundingClientRect(), br = bar.getBoundingClientRect();
    el.style.bottom = `${innerHeight - br.top + 8}px`;
    el.style.right = `${Math.max(8, Math.min(innerWidth - r.right - 10, innerWidth - el.offsetWidth - 8))}px`;
    item.classList.add('open');
    openPop = { key, el, item, pinned: !hover };
    try { const live = await p.fill(body); if (openPop?.key === key && live) { openPop.live = live; live(); } } catch { clear(body, h('div', { class: 'sbp-sub' }, 'Bilgi alınamadı')); }
  };
  [[bar.querySelector('.sb-users'), 'users'], [diskBox, 'disk'], [cpuBox, 'cpu'], [ramBox, 'ram']].forEach(([item, key]) => {
    item.classList.add('sb-hot');
    item.removeAttribute('title');
    item.addEventListener('click', e => {   // dokununca / tıklayınca açık kalır (sabitlenir); tekrar dokununca kapanır
      e.stopPropagation();
      if (openPop?.key === key && openPop.pinned) { close(); return; }
      open(key, item);
      if (openPop) openPop.pinned = true;
    });
    if (hover) {
      item.addEventListener('mouseenter', () => { clearTimeout(closeTimer); if (!openPop?.pinned || openPop.key === key) open(key, item); });
      item.addEventListener('mouseleave', () => { if (!openPop?.pinned) closeTimer = setTimeout(close, 300); });
    }
  });
  document.addEventListener('click', () => close());
  addEventListener('hashchange', () => close());
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  clearInterval(timer);
  timer = setInterval(tick, 1000);
  tick();
  return bar;
}

export function stopStatusBar() { clearInterval(timer); }
