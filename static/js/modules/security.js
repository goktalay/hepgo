// Güvenlik (fabrika girişi): gelen aracın plakası kaydedilir; parktaki araçlar plaka kartı olarak görünür, karta
// tıklanınca "çıkış yaptı" denir. Giriş / çıkış kayıtları ayrı sekmede. Kameralar ve tanımlanamayan yüzler de burada.
import { api } from '../api.js';
import {
  clear, confirmDialog, every, field, fmtDate, fmtDateTime, fmtDuration, h, modal, moduleToolbar, pageHead, secondsBetween, secondsSince, segmented, statStrip,
  toast, toastError, periodFilter
} from '../ui.js';
import { renderCameras } from './cameras.js';
import { renderFaces } from './faces.js';

const TABS = [['', 'Araçlar'], ['log', 'Giriş / Çıkış Kayıtları'], ['building', 'Bina Kontrol'], ['cameras', 'Kameralar'], ['faces', 'Tanımlanamayan Kişiler']];

export async function render(view, params, ctx) {
  const tab = TABS.some(t => t[0] === params[0]) ? params[0] || '' : '';
  const nav = segmented(TABS, tab, v => { location.hash = v ? `#/security/${v}` : '#/security'; }, { tabs: true });
  const body = h('div');
  // Araçlar sekmesinde yeni giriş düğmesi başlığın sağında (popup)
  const addBtn = h('button', { class: 'btn primary', type: 'button' }, '+ Yeni Araç Girişi');
  clear(view, pageHead('Güvenlik', { back: '#/', sub: 'Araç giriş/çıkış ve kameralar', tabs: nav }),
    moduleToolbar(tab === '' ? addBtn : null), body);
  if (tab === 'log') return renderLog(body);
  if (tab === 'building') return renderBuilding(body);
  if (tab === 'cameras') return renderCameras(body, ctx, params.slice(1));
  if (tab === 'faces') return renderFaces(body, ctx);
  return renderVehicles(body, addBtn);
}

// Türk plakası görünümü: solda mavi TR şeridi
export const plateEl = (plate, cls = '') => h('span', { class: `tr-plate ${cls}` }, h('i', null, 'TR'), h('b', null, plate));

async function renderVehicles(body, addBtn) {
  const grid = h('div', { class: 'veh-grid' });
  let list = [];
  const draw = () => clear(grid, list.length ? list.map(v => h('div', { class: 'card veh-card' },
    plateEl(v.plate),
    h('div', { class: 'veh-time' }, `Giriş ${fmtDateTime(v.entered_at)}`),
    h('div', { class: 'veh-dur' }, `${fmtDuration(secondsSince(v.entered_at))} içeride`),
    v.note ? h('div', { class: 'small muted' }, v.note) : null,
    v.visit_code ? h('span', { class: 'badge blue' }, `Misafir ${v.visit_code}`) : null,
    h('div', { class: 'veh-acts' },
      v.visit_code ? null : h('button', { class: 'btn sm', type: 'button', title: 'Hatalı plakayı düzelt', onclick: () => vehicleForm(v) }, '✎ Düzelt'),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => exit(v) }, 'Çıkış Yaptı →'))))
    : h('div', { class: 'card empty' }, 'İçeride kayıtlı araç yok. Gelen araç için sağ üstteki "Yeni Araç Girişi"ni kullanın.'));
  const load = async () => { list = await api.get('/api/security/vehicles'); draw(); };
  async function exit(v) {
    if (!await confirmDialog('Araç çıkışı', `${v.plate} çıkış yaptı mı?`, { okLabel: 'Çıkış Yaptı' })) return;
    try {
      await api.post(`/api/security/vehicles/${v.id}/exit`);
      toast(`${v.plate} çıkış yaptı`);
      await load();
    } catch (err) { toastError(err); }
  }
  // Yeni araç girişi (v yok) ya da hatalı plakayı düzeltme (v verili) — çıkış yapmadan. Enter ile kaydedilir.
  function vehicleForm(v) {
    const edit = !!v;
    const plate = h('input', { class: 'input plate-input', value: edit ? v.plate : '', placeholder: '34 ABC 123', autocomplete: 'off',
      autocapitalize: 'characters', spellcheck: false, 'aria-label': 'Plaka', style: { width: '100%' } });
    const note = h('input', { class: 'input', value: edit ? (v.note || '') : '', placeholder: 'Not (isteğe bağlı): sürücü, firma…' });
    const submit = async () => {
      if (edit) { const r = await api.put(`/api/security/vehicles/${v.id}`, { plate: plate.value, note: note.value }); toast(`Plaka güncellendi: ${r.plate}`); }
      else { const r = await api.post('/api/security/vehicles', { plate: plate.value, note: note.value }); toast(`${r.plate} giriş yaptı`); }
      await load();
    };
    const m = modal({
      title: edit ? 'Plakayı Düzelt' : 'Yeni Araç Girişi',
      body: h('div', null, field(edit ? 'Plaka' : 'Gelen aracın plakası', plate), field('Not', note)),
      actions: [{ label: 'Vazgeç' }, { label: edit ? 'Kaydet' : 'Giriş Kaydet', class: 'primary', onClick: submit }],
    });
    for (const el of [plate, note]) {
      el.addEventListener('keydown', async e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        try { await submit(); m.close(); } catch (err) { toastError(err); }
      });
    }
    plate.focus();
  }
  addBtn.onclick = () => vehicleForm(null);
  clear(body, grid);
  await load();
  every(15000, () => load().catch(() => {}));
}

async function renderLog(body) {
  const period = periodFilter('securityLog', () => load().catch(toastError), { title: 'Giriş tarihi' });
  const q = h('input', { class: 'input', type: 'search', placeholder: 'Plaka ara…', style: { width: '180px' } });
  const stats = statStrip();
  const out = h('div');
  let rows = [];
  const load = async () => {
    rows = await api.get(`/api/security/log?${period.qs()}&q=${encodeURIComponent(q.value)}`);
    stats.set([
      { label: 'Giriş', value: rows.length },
      { label: 'Çıkış', value: rows.filter(r => r.exited_at).length },
      { label: 'Hâlâ içeride', value: rows.filter(r => !r.exited_at).length, tone: 'ok' },
    ]);
    clear(out, rows.length ? h('div', { class: 'card' }, h('div', { class: 'table-wrap' }, h('table', null,
      h('thead', null, h('tr', null, ['Plaka', 'Giriş', 'Kaydeden', 'Çıkış', 'Kaydeden', 'Süre', 'Not', 'Misafir'].map(t => h('th', null, t)))),
      h('tbody', null, rows.map(r => h('tr', null,
        h('td', null, plateEl(r.plate, 'sm')),
        h('td', null, fmtDateTime(r.entered_at)), h('td', { class: 'muted' }, r.entered_by_name || '—'),
        h('td', null, r.exited_at ? fmtDateTime(r.exited_at) : h('span', { class: 'badge green' }, 'İçeride')),
        h('td', { class: 'muted' }, r.exited_by_name || '—'),
        h('td', null, fmtDuration(r.exited_at ? secondsBetween(r.entered_at, r.exited_at) : secondsSince(r.entered_at))),
        h('td', { class: 'small' }, r.note || '—'),
        h('td', null, r.visit_code || '—')))))))
      : h('div', { class: 'card empty' }, 'Bu aralıkta kayıt yok'));
  };
  const csv = h('button', { class: 'btn', type: 'button', onclick: () => {
    const cell = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [['Plaka', 'Giriş', 'Giriş kaydeden', 'Çıkış', 'Çıkış kaydeden', 'Not', 'Misafir kaydı'].map(cell).join(';'),
      ...rows.map(r => [r.plate, fmtDateTime(r.entered_at), r.entered_by_name, r.exited_at ? fmtDateTime(r.exited_at) : 'İçeride',
        r.exited_by_name, r.note, r.visit_code].map(cell).join(';'))];
    const a = h('a', { href: URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })),
      download: `arac-giris-cikis-${period.range().date_from || "tum"}_${period.range().date_to || ""}.csv` });
    document.body.append(a); a.click(); a.remove();
  } }, 'Excel (CSV) indir');
  q.addEventListener('input', () => load().catch(toastError));
  clear(body, h('div', { class: 'filters' }, period.el, q, h('span', { class: 'spacer' }), csv), stats, out);
  await load();
}

// ---------- Bina Kontrol: günlük bina turu; başlat → GPS rotası kaydı → bitir; bitenlerde harita (çizgi) ----------
let patrol = null;   // o an bu oturumda süren tur: { id, watch, lastPost, startedAt }
const bToday = () => new Date().toLocaleDateString('sv');
const bHM = iso => (iso ? new Date(iso).toLocaleTimeString('tr', { hour: '2-digit', minute: '2-digit' }) : '');
const svgNode = markup => { const t = document.createElement('template'); t.innerHTML = markup.trim(); return t.content.firstElementChild; };

async function renderBuilding(body) {
  let day = bToday();
  const dateInput = h('input', { type: 'date', class: 'input', value: day });
  dateInput.addEventListener('change', () => { day = dateInput.value || bToday(); load(); });
  const label = h('b', { class: 'cl-day' });
  const shift = n => { const d = new Date(day + 'T00:00'); d.setDate(d.getDate() + n); day = d.toLocaleDateString('sv'); dateInput.value = day; load(); };
  const bar = h('div', { class: 'cl-bar' },
    h('button', { class: 'btn', type: 'button', title: 'Önceki gün', onclick: () => shift(-1) }, '‹'), dateInput,
    h('button', { class: 'btn', type: 'button', title: 'Sonraki gün', onclick: () => shift(1) }, '›'),
    h('button', { class: 'btn', type: 'button', onclick: () => { day = bToday(); dateInput.value = day; load(); } }, 'Bugün'),
    h('span', { class: 'spacer' }),
    day === bToday() ? h('button', { class: 'btn primary', type: 'button', onclick: () => startPatrol(day, null) }, '+ Kontrol Başlat') : null, label);
  const active = h('div');
  const list = h('div', { class: 'cl-list' });

  const elapsedText = () => (patrol ? fmtDuration(Math.floor((Date.now() - patrol.startedAt) / 1000)) : '');

  function drawActive() {
    if (!patrol) { clear(active); return; }
    clear(active, h('div', { class: 'bc-active' },
      h('span', { class: 'bc-rec-dot' }),
      h('div', { class: 'grow' }, h('b', null, 'Bina turu kaydediliyor…'),
        h('div', { class: 'small' }, `${patrol.posted || 0} konum · ${elapsedText()}`)),
      h('button', { class: 'btn', type: 'button', onclick: () => bcNotes(patrol.id, 'tur') }, '📝 Sorun/Not'),
      h('button', { class: 'btn danger', type: 'button', onclick: () => finishPatrol() }, 'Turu Bitir · ' + elapsedText())));
  }

  // Süren turun "Bitir" düğmelerindeki sayacı (hem banner hem satır) her saniye güncelle
  function updateStopBtns() {
    document.querySelectorAll('.bc-stop-live').forEach(b => { b.textContent = 'Bitir · ' + elapsedText(); });
  }

  // Konum takibi: watchPosition son konumu tutar; 1 sn'de bir sunucuya kaydeder
  function startTracking() {
    if (!navigator.geolocation) return;
    patrol.watch = navigator.geolocation.watchPosition(
      pos => { patrol.lastPos = { lat: pos.coords.latitude, lng: pos.coords.longitude, acc: pos.coords.accuracy }; },
      err => { toast('Konum alınamadı: ' + (err.message || 'izin verilmedi'), 'err'); },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 });
    patrol.timer = setInterval(() => {
      if (patrol && patrol.lastPos && Date.now() - patrol.lastPost >= 1000) {
        patrol.lastPost = Date.now();
        const p = patrol.lastPos;
        api.post(`/api/security/building/${patrol.id}/point`, { lat: p.lat, lng: p.lng, acc: p.acc })
          .then(() => { patrol.posted++; }).catch(() => {});
      }
      drawActive(); updateStopBtns();
    }, 1000);
  }

  async function load() {
    label.textContent = fmtDate(day);
    let d;
    try { d = await api.get(`/api/security/building?date=${day}`); } catch (err) { return clear(body, h('div', { class: 'card empty' }, err.message)); }
    const now = new Date().toTimeString().slice(0, 5);
    const rows = d.checks.map(c => {
      const due = c.status === 'BEKLIYOR' && day === bToday() && c.slot && c.slot <= now;
      const acts = [];
      if (c.status === 'BEKLIYOR') acts.push(h('button', { class: `btn sm ${due && !patrol ? 'primary' : ''}`, type: 'button', disabled: !!patrol, title: patrol ? 'Süren bir kontrol var; önce onu bitirin' : '', onclick: () => startPatrol(day, c.slot) }, 'Başlat'));
      else if (c.status === 'DEVAM') acts.push(h('button', { class: 'btn sm danger bc-stop-live', type: 'button', onclick: () => finishPatrol(c.id) }, 'Bitir · ' + elapsedText()));
      else { acts.push(h('span', { class: 'small muted' }, `${c.points} konum`)); if (c.points) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => openTrack(c.id) }, '🗺 Harita')); }
      if (c.id) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => bcNotes(c.id, c.slot || bHM(c.started_at)) }, `📝 Sorun/Not${c.notes ? ` (${c.notes})` : ''}`));
      return h('div', { class: `bc-item ${c.status === 'BITTI' ? 'done' : ''} ${due ? 'due' : ''}` },
        h('div', { class: 'bc-slot' }, c.slot || '—'),
        h('div', { class: 'grow' },
          h('b', null, c.status === 'BITTI' ? 'Kontrol yapıldı' : c.status === 'DEVAM' ? 'Kontrol sürüyor' : (due ? 'Kontrol zamanı geldi' : 'Planlı kontrol')),
          h('div', { class: 'small muted' }, c.started_at ? `${bHM(c.started_at)}${c.finished_at ? ' – ' + bHM(c.finished_at) : ''}${c.started_by_name ? ' · ' + c.started_by_name : ''}` : 'Bu saatte bina turu atılacak')),
        h('div', { class: 'bc-acts' }, acts));
    });
    clear(list, rows.length ? rows : h('div', { class: 'card empty' }, 'Bugün için planlı kontrol yok. Saatleri Program Ayarları › Modül Ayarları › Güvenlik’ten ekleyin ya da “Kontrol Başlat” deyin.'));
    // Sayfa yenilense / program yeniden başlasa bile süren turu sunucudan geri yükle: Bitir düğmesi aktif olur
    const ongoing = d.checks.find(c => c.status === 'DEVAM');
    if (ongoing && !patrol) resumePatrol(ongoing);
    else drawActive();
  }

  function resumePatrol(c) {
    patrol = { id: c.id, startedAt: new Date(c.started_at).getTime() || Date.now(), posted: c.points || 0, lastPost: 0, lastPos: null };
    startTracking();
    drawActive();
  }

  async function startPatrol(d, slot) {
    if (patrol) { toast('Zaten süren bir kontrol var; önce onu bitirin', 'err'); return; }
    if (!navigator.geolocation) { toast('Bu cihaz konum (GPS) desteklemiyor', 'err'); return; }
    let r;
    try { r = await api.post('/api/security/building/start', { date: d, slot }); } catch (err) { return toastError(err); }
    patrol = { id: r.id, startedAt: Date.now(), posted: 0, lastPost: 0, lastPos: null };
    startTracking();
    toast('Bina turu başladı · telefonla binanın etrafını dolaşın');
    load();
  }
  async function finishPatrol(id) {
    id = id || (patrol && patrol.id);
    if (!id) return;
    if (patrol) {
      try { navigator.geolocation.clearWatch(patrol.watch); } catch { /* */ }
      clearInterval(patrol.timer);
      patrol = null;
    }
    try { await api.post(`/api/security/building/${id}/finish`, {}); toast('Bina turu bitti', 'success'); } catch (err) { toastError(err); }
    load();
  }
  async function openTrack(cid) {
    let d;
    try { d = await api.get(`/api/security/building/${cid}/track`); } catch (err) { return toastError(err); }
    modal({ title: `Bina turu · ${d.slot || bHM(d.started_at)}`, wide: true,
      body: h('div', null,
        h('p', { class: 'small muted', style: { marginTop: 0 } }, `${bHM(d.started_at)} – ${bHM(d.finished_at)} · ${d.started_by_name || ''} · ${d.points.length} konum`),
        trackMap(d.points)),
      actions: [{ label: 'Kapat' }] });
  }
  function trackMap(points) {
    if (!points.length) return h('div', { class: 'card empty' }, 'Konum kaydı yok (GPS izni verilmemiş olabilir).');
    const W = 580, H = 380, pad = 26;
    const las = points.map(p => p.lat), lns = points.map(p => p.lng);
    const minLa = Math.min(...las), maxLa = Math.max(...las), minLn = Math.min(...lns), maxLn = Math.max(...lns);
    const spanLa = (maxLa - minLa) || 1e-6, spanLn = (maxLn - minLn) || 1e-6;
    const s = Math.min((W - 2 * pad) / spanLn, (H - 2 * pad) / spanLa);
    const cx = (W - spanLn * s) / 2, cy = (H - spanLa * s) / 2;
    const X = ln => cx + (ln - minLn) * s, Y = la => H - cy - (la - minLa) * s;
    const dPath = points.map((p, i) => `${i ? 'L' : 'M'}${X(p.lng).toFixed(1)} ${Y(p.lat).toFixed(1)}`).join(' ');
    const a = points[0], b = points[points.length - 1];
    return svgNode(`<svg viewBox="0 0 ${W} ${H}" class="bc-map" role="img" aria-label="Devriye rotası">
      <rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="#eef3fb"/>
      <path d="${dPath}" fill="none" stroke="#2563eb" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${X(a.lng).toFixed(1)}" cy="${Y(a.lat).toFixed(1)}" r="7" fill="#16a34a"/>
      <circle cx="${X(b.lng).toFixed(1)}" cy="${Y(b.lat).toFixed(1)}" r="7" fill="#dc2626"/>
      <text x="14" y="${H - 12}" fill="#64748b" font-size="12" font-family="sans-serif">● Başlangıç (yeşil) · ● Bitiş (kırmızı)</text></svg>`);
  }

  async function bcNotes(cid, lbl) {
    const nlist = h('div', { class: 'dz-notes' });
    const ta = h('textarea', { class: 'input', rows: 2, placeholder: 'Tespit edilen sorun / açıklama…' });
    const draw = async () => {
      let ns; try { ns = await api.get(`/api/security/building/${cid}/notes`); } catch { return; }
      clear(nlist, ns.length ? ns.map(n => h('div', { class: 'dz-note-row' }, h('div', { class: 'grow' }, h('div', null, n.note),
        h('div', { class: 'small muted' }, `${fmtDateTime(n.created_at)} · ${n.by_name || ''}`)))) : h('div', { class: 'muted' }, 'Henüz not yok.'));
    };
    const add = async () => { if (!ta.value.trim()) return; try { await api.post(`/api/security/building/${cid}/note`, { note: ta.value }); ta.value = ''; draw(); load(); } catch (err) { toastError(err); } };
    draw();
    modal({ title: `Bina turu · ${lbl} · Sorun / Notlar`, wide: true,
      body: h('div', null, nlist, h('div', { class: 'cl-set-add', style: { marginTop: '10px' } }, ta, h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle'))),
      actions: [{ label: 'Kapat' }] });
  }

  clear(body, bar, active, list);
  load();
}
