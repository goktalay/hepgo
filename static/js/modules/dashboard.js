// Kişisel pano (ana sayfa): herkesin kendine göre düzenlediği kutucuklar. Kutucuklar sunucudan (yetkiye göre) gelir;
// düzen (sıra, genişlik, ayar) kullanıcıya özel sunucuda saklanır (user_prefs: dashboard). "Panoyu Düzenle" ile kutucuk
// eklenir, çıkarılır, taşınır, genişliği (1/3, 2/3, tam) ve ayarı (saat biçimi, hava durumu konumu) değiştirilir.
import { api } from '../api.js';
import { icons } from '../icons.js';
import { PRINTER_STATES, orderBadge, queuePlate } from '../status.js';
import { clear, field, fmtDateTime, h, modal, onLeave, progressBar, segmented, svgIcon, t, toastError } from '../ui.js';
import { LEVELS } from './announcements.js';
import { chartConfig, loadChart, theme } from './reports.js';

const MULTI = new Set(['clock', 'weather']);   // birden çok eklenebilen (ör. iki şehir)
const PRINTER_COLORS = { YAZDIRIYOR: '#3b82f6', HAZIR: '#22c55e', TAMAMLANDI: '#a855f7', DURAKLADI: '#f59e0b', HATA: '#ef4444', CEVRIMDISI: '#6b7280' };

export async function renderDashboard(view, ctx, modules) {
  const [avail, saved] = await Promise.all([api.get('/api/dashboard/widgets'), api.get('/api/me/prefs/dashboard').catch(() => ({}))]);
  const byKey = Object.fromEntries(avail.map(w => [w.key, w]));
  let layout;
  try { layout = JSON.parse(saved.value || 'null'); } catch { layout = null; }
  if (!Array.isArray(layout)) layout = avail.filter(w => w.default).sort((a, b) => a.default - b.default).map(w => ({ k: w.key, s: w.size }));
  layout = layout.filter(it => byKey[it.k]);
  let editing = false;
  let data = {};
  const charts = [];
  const timers = [];
  onLeave(() => { charts.forEach(c => c.destroy()); timers.forEach(clearInterval); });
  const grid = h('div', { class: 'db-grid' });
  const editBtn = h('button', { class: 'btn', type: 'button', onclick: () => { editing = !editing; draw(); } });
  const save = () => api.put('/api/me/prefs/dashboard', { value: JSON.stringify(layout) }).catch(() => {});

  const loadData = async () => {
    const keys = [...new Set(layout.map(it => it.k))].filter(k => !['clock', 'weather', 'modules'].includes(k));
    data = keys.length ? await api.get(`/api/dashboard/data?keys=${keys.join(',')}`) : {};
  };

  function draw() {
    charts.splice(0).forEach(c => c.destroy());
    timers.splice(0).forEach(clearInterval);
    editBtn.textContent = editing ? 'Düzenlemeyi Bitir' : 'Panoyu Düzenle';
    grid.classList.toggle('editing', editing);
    clear(grid, layout.map((it, i) => tile(it, i)),
      editing ? h('button', { class: 'db-add', type: 'button', onclick: addWidget }, h('span', null, '+'), 'Kutucuk Ekle') : null,
      !layout.length && !editing ? h('div', { class: 'card empty db-empty' }, 'Panonuz boş. "Panoyu Düzenle" ile kutucuk ekleyin.') : null);
  }

  function tile(it, i) {
    const w = byKey[it.k];
    const body = h('div', { class: 'db-body' });
    const tools = editing ? h('div', { class: 'db-tools' },
      h('button', { type: 'button', title: 'Sola / yukarı taşı', disabled: i === 0, onclick: () => move(i, -1) }, '←'),
      h('button', { type: 'button', title: 'Sağa / aşağı taşı', disabled: i === layout.length - 1, onclick: () => move(i, 1) }, '→'),
      h('button', { type: 'button', title: 'Genişlik', onclick: () => { it.s = (it.s % 3) + 1; save(); draw(); } }, ['⅓', '⅔', '▭'][it.s - 1]),
      MULTI.has(it.k) ? h('button', { type: 'button', title: 'Ayarlar', onclick: () => settings(it) }, '⚙') : null,
      h('button', { type: 'button', class: 'danger', title: 'Kaldır', onclick: () => { layout.splice(i, 1); save(); draw(); } }, '✕')) : null;
    const el = h('section', { class: `card db-tile s${it.s || 1} w-${it.k}` },
      h('div', { class: 'db-head' }, h('h3', null, it.k === 'weather' && it.o?.name ? t('Hava durumu · {name}', { name: it.o.name }) : w.title), tools), body);
    try { fill(it, body); } catch (err) { clear(body, h('div', { class: 'empty small' }, err.message)); }
    return el;
  }

  const move = (i, d) => { const [x] = layout.splice(i, 1); layout.splice(i + d, 0, x); save(); draw(); };

  function addWidget() {
    const used = new Set(layout.map(it => it.k));
    const list = avail.filter(w => MULTI.has(w.key) || !used.has(w.key));
    const m = modal({
      title: 'Kutucuk Ekle', wide: true,
      body: list.length ? h('div', { class: 'db-pick' }, list.map(w => h('button', { type: 'button', class: 'db-pick-item', onclick: async () => {
        layout.push({ k: w.key, s: w.size });
        save();
        m.close();
        await loadData().catch(() => {});
        draw();
        if (MULTI.has(w.key)) settings(layout[layout.length - 1]);
      } }, h('b', null, w.title), h('span', null, w.desc)))) : h('div', { class: 'empty' }, 'Eklenebilecek başka kutucuk yok'),
      actions: [{ label: 'Kapat' }],
    });
  }

  function settings(it) {
    if (it.k === 'clock') {
      let style = it.o?.style || 'digital';
      modal({ title: 'Saat', body: h('div', null, field('Görünüm', segmented([['digital', 'Dijital'], ['analog', 'Analog']], style, v => { style = v; }))),
        actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: () => { it.o = { ...it.o, style }; save(); draw(); } }] });
      return;
    }
    // Hava durumu: bulunduğum konum (tarayıcı izni) ya da şehir arama
    const q = h('input', { class: 'input', type: 'search', placeholder: 'Şehir ya da ilçe ara… (ör. Kalecik)' });
    const results = h('div', { class: 'pick-list' });
    const m = modal({ title: 'Hava durumu konumu', body: h('div', null,
      h('button', { class: 'btn', type: 'button', style: { marginBottom: '12px' }, onclick: () => { it.o = { mode: 'auto' }; save(); m.close(); draw(); } },
        '📍 Bulunduğum konumu kullan'),
      field('Ya da şehir seçin', q), results), actions: [{ label: 'Kapat' }] });
    let timer;
    q.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (q.value.trim().length < 2) { clear(results); return; }
        try {
          const r = await (await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q.value.trim())}&count=8&language=tr&format=json`)).json();
          clear(results, (r.results || []).map(c => h('button', { class: 'pick', type: 'button', onclick: () => {
            it.o = { mode: 'city', name: c.name, lat: c.latitude, lon: c.longitude }; save(); m.close(); draw();
          } }, h('div', { class: 'grow' }, h('b', null, c.name), h('span', { class: 'small muted' }, [c.admin1, c.country].filter(Boolean).join(', '))))));
        } catch { clear(results, h('div', { class: 'empty small' }, 'Şehir araması yapılamadı (internet bağlantısı?)')); }
      }, 300);
    });
    q.focus();
  }

  // ---------- kutucuk içerikleri
  function fill(it, body) {
    const d = data[it.k] || {};
    const list = (items, row, empty) => clear(body, items?.length ? h('ul', { class: 'db-list' }, items.map(row)) : h('div', { class: 'db-none' }, empty));
    const kpis = arr => clear(body, h('div', { class: 'db-kpis' }, arr.map(k => h(k.href ? 'a' : 'div', { class: `db-kpi ${k.tone || ''}`, href: k.href },
      h('b', null, k.value ?? '—'), h('span', null, k.label), k.sub ? h('small', null, k.sub) : null))));
    switch (it.k) {
      case 'clock': return clock(body, it.o?.style || 'digital');
      case 'weather': return weather(body, it.o || { mode: 'auto' });
      case 'modules': return clear(body, h('div', { class: 'db-modules' }, modules.map(m => h('a', { href: `#/${m.key}`, class: m.tone ? `tone-${m.tone}` : '' },
        h('span', { class: 'ico' }, svgIcon(icons[m.key])), h('span', null, m.title)))));
      case 'announcements': return list(d.items, a => h('li', null, h('a', { href: `#/announcements/${a.id}` },
        h('span', { class: `badge ${(LEVELS[a.level] || LEVELS.BILGI)[0]}` }, (LEVELS[a.level] || LEVELS.BILGI)[1]), ' ', h('b', null, a.title)),
      h('small', null, fmtDateTime(a.created_at))), 'Yeni duyuru yok');
      case 'notifications': return list(d.items, n => h('li', null, h('a', { href: n.href }, h('span', { class: 'db-n' }, n.count), n.title),
        n.detail ? h('small', null, n.detail) : null), 'Bekleyen bildiriminiz yok');
      case 'alerts': return list(d.items, a => h('li', { class: a.critical ? 'crit' : '' }, h('a', { href: `#/alerts/${a.key}` }, h('span', { class: `db-n ${a.level}` }, a.count), a.title)),
        'Uyarı yok');
      case 'calendar': return list(d.items, e => h('li', { class: e.kind === 'TOPLANTI' ? 'db-meeting' : '' },
        h('a', { href: e.href || '#/calendar' }, h('span', { class: 'db-time' }, fmtDateTime(e.at).replace(/\.\d{4}/, '')), e.title),
        e.kind === 'TOPLANTI' ? h('small', null, e.live ? h('span', { class: 'badge green' }, 'Devam ediyor') : 'Toplantı',
          e.pending ? [' · ', h('span', { class: 'badge yellow' }, 'Yanıt bekliyor')] : null, e.location ? ` · ${e.location}` : '')
          : h('small', null, e.kind === 'HATIRLATMA' ? 'Hatırlatma' : 'Randevu')), 'Yaklaşan randevu ya da toplantı yok');
      case 'my_cargo': return list(d.items, k => h('li', null, h('a', { href: '#/my-cargo' }, h('b', null, k.carrier || 'Kargo'), k.description ? ` · ${k.description}` : ''),
        h('small', null, fmtDateTime(k.created_at))), 'Bekleyen kargonuz yok');
      case 'my_calls': return list(d.items, c => h('li', null, h('a', { href: '#/my-calls' }, h('b', null, c.caller_name),
        c.subject ? ` · ${c.subject}` : c.caller_company ? ` · ${c.caller_company}` : ''), c.callback ? h('span', { class: 'badge red' }, 'Geri ara') : null,
      h('small', null, fmtDateTime(c.created_at))), 'Bekleyen aramanız yok');
      case 'my_guests': return list(d.items, g => h('li', null, h('a', { href: '#/my-guests' }, h('b', null, g.names || g.code), g.purpose ? ` · ${g.purpose}` : ''),
        h('small', null, g.left_at ? 'çıktı' : 'içeride')), 'Bugün misafiriniz yok');
      case 'kpi_printers': {
        const tot = d.total || 1;
        return clear(body, h('div', { class: 'db-pbar' }, Object.entries(d.states || {}).map(([k, v]) =>
          h('i', { style: { width: `${100 * v / tot}%`, background: PRINTER_COLORS[k] || '#9ca3af' }, title: `${PRINTER_STATES[k]?.label || k}: ${v}` }))),
        h('div', { class: 'db-legend' }, Object.entries(d.states || {}).map(([k, v]) => h('a', { href: '#/printers' },
          h('i', { style: { background: PRINTER_COLORS[k] || '#9ca3af' } }), `${PRINTER_STATES[k]?.label || k} `, h('b', null, v)))));
      }
      case 'chart_production': {
        const canvas = h('canvas');
        clear(body, h('div', { class: 'db-chart' }, canvas));
        loadChart().then(Chart => charts.push(new Chart(canvas, chartConfig({ type: 'combo', labels: d.labels || [],
          datasets: [{ label: 'Depoya teslim', data: d.done || [] }, { label: 'Hata', data: d.err || [], line: true }] }, theme(), true)))).catch(() => {});
        return;
      }
      case 'forecast': return clear(body, h('div', { class: 'db-kpis' }, (d.kpis || []).map(k => h('div', { class: `db-kpi ${k.tone || ''}` }, h('b', null, k.value), h('span', null, k.label), k.sub ? h('small', null, k.sub) : null))),
        h('ul', { class: 'db-list' }, (d.rows || []).map(r => h('li', null, h('a', { href: '#/reports/kapasite-tahmin' }, h('b', null, r.code), ` · ${r.prog}`), h('small', null, r.eta_t)))));
      case 'recent_orders': return list(d.items, o => h('li', { class: 'db-order' }, h('a', { href: `#/orders/${o.id}` }, h('b', null, o.code), ' ', orderBadge(o)),
        o.queue_no ? queuePlate(o.queue_no) : h('small', null, o.product_name), h('span', { class: 'db-mini' }, progressBar(o.progress))), 'Sipariş yok');
      default:
        if (d.kpis) return kpis(d.kpis);
        if (d.error) return clear(body, h('div', { class: 'db-none' }, d.error));
        return clear(body, h('div', { class: 'db-none' }, '—'));
    }
  }

  // Saat: dijital ya da analog (SVG), saniyede bir güncellenir
  function clock(body, style) {
    const days = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
    const week = t => { const d = new Date(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate())); const n = d.getUTCDay() || 7; d.setUTCDate(d.getUTCDate() + 4 - n);
      return Math.ceil(((d - new Date(Date.UTC(d.getUTCFullYear(), 0, 1))) / 864e5 + 1) / 7); };
    const dateEl = h('div', { class: 'db-date' });
    if (style === 'analog') {
      const NS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', '0 0 200 200');
      svg.setAttribute('class', 'db-analog');
      const el = (tag, a) => { const e = document.createElementNS(NS, tag); Object.entries(a).forEach(([k, v]) => e.setAttribute(k, v)); svg.append(e); return e; };
      el('circle', { cx: 100, cy: 100, r: 94, class: 'face' });
      for (let i = 0; i < 60; i++) {
        const a = i * Math.PI / 30, big = i % 5 === 0;
        el('line', { x1: 100 + Math.sin(a) * (big ? 78 : 84), y1: 100 - Math.cos(a) * (big ? 78 : 84), x2: 100 + Math.sin(a) * 90, y2: 100 - Math.cos(a) * 90, class: big ? 'tick big' : 'tick' });
      }
      const hh = el('line', { x1: 100, y1: 100, x2: 100, y2: 52, class: 'hand h' });
      const mm = el('line', { x1: 100, y1: 100, x2: 100, y2: 30, class: 'hand m' });
      const ss = el('line', { x1: 100, y1: 114, x2: 100, y2: 24, class: 'hand s' });
      el('circle', { cx: 100, cy: 100, r: 5, class: 'pin' });
      const tick = () => {
        const now = new Date();
        const s = now.getSeconds(), m = now.getMinutes() + s / 60, hr = (now.getHours() % 12) + m / 60;
        hh.setAttribute('transform', `rotate(${hr * 30} 100 100)`);
        mm.setAttribute('transform', `rotate(${m * 6} 100 100)`);
        ss.setAttribute('transform', `rotate(${s * 6} 100 100)`);
        dateEl.textContent = t('{d}, {date} · {w}. hafta', { d: days[now.getDay()], date: now.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' }), w: week(now) });
      };
      tick();
      timers.push(setInterval(tick, 1000));
      return clear(body, h('div', { class: 'db-clock analog' }, svg, dateEl));
    }
    // Nokta vuruşlu (LED matris) dijital saat: her rakam 5×7 nokta; sönük noktalar da hafifçe görünür, iki nokta yanıp söner
    const hhmm = dotMatrix(5), sec = dotMatrix(2);
    const time = h('div', { class: 'db-dots' }, hhmm.el, h('div', { class: 'db-dots-sec' }, sec.el));
    const tick = () => {
      const now = new Date();
      const p2 = n => String(n).padStart(2, '0');
      hhmm.set(`${p2(now.getHours())}${now.getSeconds() % 2 ? ' ' : ':'}${p2(now.getMinutes())}`);
      sec.set(p2(now.getSeconds()));
      dateEl.textContent = t('{d}, {date} · {w}. hafta', { d: days[now.getDay()], date: now.toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' }), w: week(now) });
    };
    tick();
    timers.push(setInterval(tick, 1000));
    return clear(body, h('div', { class: 'db-clock dotted' }, time, dateEl));
  }

  // Hava durumu (Open-Meteo, anahtar gerektirmez): anlık + 4 günlük
  async function weather(body, o) {
    clear(body, h('div', { class: 'db-none' }, 'Hava durumu alınıyor…'));
    let lat = o.lat, lon = o.lon, name = o.name;
    if (o.mode !== 'city') {
      try {
        const pos = await new Promise((res, rej) => navigator.geolocation ? navigator.geolocation.getCurrentPosition(res, rej, { timeout: 8000, maximumAge: 600000 }) : rej(new Error('')));
        lat = pos.coords.latitude; lon = pos.coords.longitude; name = 'Konumunuz';
      } catch {
        clear(body, h('div', { class: 'db-none' }, 'Konum izni verilmedi. ', h('button', { class: 'btn sm', type: 'button', onclick: () => {
          const it = layout.find(x => x.k === 'weather' && (!x.o || x.o.mode !== 'city')); if (it) settings(it);
        } }, 'Şehir seçin')));
        return;
      }
    }
    try {
      const r = await (await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code,is_day&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset&timezone=auto&forecast_days=1`)).json();
      const c = r.current, d = r.daily;
      const [, text] = wmo(c.weather_code, c.is_day);
      const hm = s => (s || '').slice(11, 16);
      const dirs = ['K', 'KD', 'D', 'GD', 'G', 'GB', 'B', 'KB'];
      const stat = (ic, label, val) => h('div', { class: 'wx-stat' }, svgEl(WX_MINI[ic]), h('span', null, label), h('b', null, val));
      clear(body, h('div', { class: `wx wx-${wxTheme(c.weather_code, c.is_day)}` },
        h('div', { class: 'wx-hero' },
          h('div', { class: 'wx-main' },
            h('div', { class: 'wx-place' }, name || 'Konum'),
            h('div', { class: 'wx-temp' }, `${Math.round(c.temperature_2m)}`, h('sup', null, '°C')),
            h('div', { class: 'wx-cond' }, text),
            h('div', { class: 'wx-hl' }, t('En yüksek {a}° · En düşük {b}°', { a: Math.round(d.temperature_2m_max[0]), b: Math.round(d.temperature_2m_min[0]) }))),
          h('div', { class: 'wx-art' }, svgEl(wxIcon(c.weather_code, c.is_day)))),
        h('div', { class: 'wx-stats' },
          stat('feel', 'Hissedilen', `${Math.round(c.apparent_temperature)}°`),
          stat('drop', 'Nem', `%${c.relative_humidity_2m}`),
          stat('wind', 'Rüzgâr', `${Math.round(c.wind_speed_10m)} km/sa ${dirs[Math.round((c.wind_direction_10m || 0) / 45) % 8]}`),
          stat('sun', 'Güneş doğuş · batış', `${hm(d.sunrise?.[0])} · ${hm(d.sunset?.[0])}`)),
        h('div', { class: 'db-wsrc' }, 'Open-Meteo')));
    } catch { clear(body, h('div', { class: 'db-none' }, 'Hava durumu alınamadı (internet bağlantısı?)')); }
  }

  await loadData().catch(err => toastError(err));
  const hour = new Date().getHours();
  const greet = hour < 6 ? 'İyi geceler' : hour < 12 ? 'Günaydın' : hour < 18 ? 'İyi günler' : 'İyi akşamlar';
  clear(view, h('div', { class: 'db-headline' },
    h('div', null, h('h1', null, `${greet}, ${ctx.user.full_name.split(' ')[0]}`), h('p', { class: 'muted' }, 'Kişisel panonuz · kutucukları dilediğiniz gibi düzenleyebilirsiniz')),
    editBtn), grid);
  draw();
  timers.push(setInterval(async () => { if (!editing && !document.querySelector('.modal-back')) { await loadData().catch(() => {}); draw(); } }, 60000));
}

// 5×7 nokta matris karakterleri (her satır 5 bit); ':' ve ' ' 3 sütun genişliğinde
const FONT = {
  0: ['01110', '10001', '10011', '10101', '11001', '10001', '01110'], 1: ['00100', '01100', '00100', '00100', '00100', '00100', '01110'],
  2: ['01110', '10001', '00001', '00010', '00100', '01000', '11111'], 3: ['11111', '00010', '00100', '00010', '00001', '10001', '01110'],
  4: ['00010', '00110', '01010', '10010', '11111', '00010', '00010'], 5: ['11111', '10000', '11110', '00001', '00001', '10001', '01110'],
  6: ['00110', '01000', '10000', '11110', '10001', '10001', '01110'], 7: ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
  8: ['01110', '10001', '10001', '01110', '10001', '10001', '01110'], 9: ['01110', '10001', '10001', '01111', '00001', '00010', '01100'],
  ':': ['000', '000', '010', '000', '010', '000', '000'], ' ': ['000', '000', '000', '000', '000', '000', '000'],
};
function dotMatrix(chars) {
  const NS = 'http://www.w3.org/2000/svg';
  const widths = chars === 5 ? [5, 5, 3, 5, 5] : Array(chars).fill(5);
  const gap = 1, cols = widths.reduce((a, w) => a + w, 0) + gap * (chars - 1);
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${cols * 10} 70`);
  svg.setAttribute('class', 'db-matrix');
  const cells = [];
  let x0 = 0;
  widths.forEach(w => {
    const grid = [];
    for (let r = 0; r < 7; r++) for (let c = 0; c < w; c++) {
      const d = document.createElementNS(NS, 'circle');
      d.setAttribute('cx', (x0 + c) * 10 + 5); d.setAttribute('cy', r * 10 + 5); d.setAttribute('r', 3.9);
      svg.append(d);
      grid.push(d);
    }
    cells.push({ w, grid });
    x0 += w + gap;
  });
  return {
    el: svg,
    set(text) {
      [...text].forEach((ch, i) => {
        const g = FONT[ch] || FONT[' '], cell = cells[i];
        if (!cell) return;
        cell.grid.forEach((d, k) => {
          const r = Math.floor(k / cell.w), c = k % cell.w;
          const col = cell.w === 3 && g[0].length === 5 ? c + 1 : c;
          d.classList.toggle('on', (g[r] || '')[col] === '1');
        });
      });
    },
  };
}

// WMO hava kodu → simge, Türkçe metin
function wmo(code, day = 1) {
  const sun = day ? '☀️' : '🌙';
  const m = {
    0: [sun, 'Açık'], 1: [day ? '🌤️' : '🌙', 'Az bulutlu'], 2: ['⛅', 'Parçalı bulutlu'], 3: ['☁️', 'Kapalı'], 45: ['🌫️', 'Sisli'], 48: ['🌫️', 'Kırağılı sis'],
    51: ['🌦️', 'Hafif çisenti'], 53: ['🌦️', 'Çisenti'], 55: ['🌧️', 'Yoğun çisenti'], 61: ['🌦️', 'Hafif yağmur'], 63: ['🌧️', 'Yağmur'], 65: ['🌧️', 'Kuvvetli yağmur'],
    66: ['🌧️', 'Donan yağmur'], 67: ['🌧️', 'Donan yağmur'], 71: ['🌨️', 'Hafif kar'], 73: ['🌨️', 'Kar'], 75: ['❄️', 'Yoğun kar'], 77: ['🌨️', 'Kar taneleri'],
    80: ['🌦️', 'Sağanak'], 81: ['🌧️', 'Sağanak'], 82: ['⛈️', 'Kuvvetli sağanak'], 85: ['🌨️', 'Kar sağanağı'], 86: ['❄️', 'Yoğun kar sağanağı'],
    95: ['⛈️', 'Gök gürültülü fırtına'], 96: ['⛈️', 'Dolu ile fırtına'], 99: ['⛈️', 'Dolu ile fırtına'],
  };
  return m[code] || ['🌡️', '—'];
}


// ---------- Hava durumu çizimleri (SVG): durum + gece/gündüz; zemin teması
const WX_SUN = '<circle cx="32" cy="32" r="11" fill="#fbbf24"/><g stroke="#fbbf24" stroke-width="3" stroke-linecap="round">' +
  [0, 45, 90, 135, 180, 225, 270, 315].map(a => `<line x1="32" y1="9" x2="32" y2="14" transform="rotate(${a} 32 32)"/>`).join('') + '</g>';
const WX_MOON = '<path d="M38 12a18 18 0 1 0 14 26A15 15 0 0 1 38 12z" fill="#e2e8f0"/>';
const WX_CLOUD = (x = 0, y = 0, c = '#f8fafc') => `<path transform="translate(${x} ${y})" d="M20 46h26a10 10 0 0 0 0-20 14 14 0 0 0-27-3A11 11 0 0 0 20 46z" fill="${c}" stroke="rgba(15,23,42,.12)" stroke-width="1"/>`;
const WX_RAIN = '<g stroke="#60a5fa" stroke-width="3" stroke-linecap="round"><line x1="24" y1="50" x2="21" y2="58"/><line x1="33" y1="50" x2="30" y2="58"/><line x1="42" y1="50" x2="39" y2="58"/></g>';
const WX_SNOW = '<g fill="#e0f2fe"><circle cx="23" cy="54" r="2.5"/><circle cx="33" cy="57" r="2.5"/><circle cx="43" cy="54" r="2.5"/></g>';
const WX_BOLT = '<path d="M34 46l-6 10h6l-3 8 9-12h-6l4-6z" fill="#facc15"/>';
const WX_FOG = '<g stroke="#cbd5e1" stroke-width="3" stroke-linecap="round"><line x1="14" y1="50" x2="50" y2="50"/><line x1="18" y1="56" x2="46" y2="56"/></g>';
function wxIcon(code, day = 1) {
  const sky = day ? WX_SUN : WX_MOON;
  let body;
  if (code === 0) body = sky;
  else if (code <= 2) body = `<g transform="translate(-8 -8) scale(.85)">${sky}</g>${WX_CLOUD(4, 4)}`;
  else if (code === 3) body = `${WX_CLOUD(-6, -6, '#cbd5e1')}${WX_CLOUD(4, 2)}`;
  else if (code === 45 || code === 48) body = `${WX_CLOUD(0, -6, '#e2e8f0')}${WX_FOG}`;
  else if (code >= 95) body = `${WX_CLOUD(0, -6, '#94a3b8')}${WX_BOLT}`;
  else if ((code >= 71 && code <= 77) || code === 85 || code === 86) body = `${WX_CLOUD(0, -6)}${WX_SNOW}`;
  else body = `${WX_CLOUD(0, -6, '#cbd5e1')}${WX_RAIN}`;
  return `<svg viewBox="0 0 64 64" aria-hidden="true">${body}</svg>`;
}
function wxTheme(code, day) {
  if (!day) return 'night';
  if (code >= 95) return 'storm';
  if (code >= 51) return 'rain';
  if (code === 3 || code === 45 || code === 48) return 'cloudy';
  return 'clear';
}
const WX_MINI = {
  feel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/></svg>',
  drop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/></svg>',
  wind: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 5v3M5.6 9.6l2 2M18.4 9.6l-2 2"/></svg>',
};
function svgEl(markup) {
  const w = document.createElement('span');
  w.className = 'wx-svg';
  w.innerHTML = markup;
  return w;
}
