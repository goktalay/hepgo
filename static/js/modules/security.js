// Güvenlik (fabrika girişi): gelen aracın plakası kaydedilir; parktaki araçlar plaka kartı olarak görünür, karta
// tıklanınca "çıkış yaptı" denir. Giriş / çıkış kayıtları ayrı sekmede. Kameralar ve tanımlanamayan yüzler de burada.
import { api } from '../api.js';
import { loadMaps } from '../maps.js';
import {
  clear, confirmDialog, every, field, fmtDate, fmtDateTime, fmtDuration, h, modal, moduleToolbar, onLeave, pageHead, secondsBetween, secondsSince, segmented, statStrip,
  t, toast, toastError, periodFilter
} from '../ui.js';
const TABS = [['', 'Araçlar'], ['personnel', 'Görevde / İzinde'], ['log', 'Giriş / Çıkış Kayıtları'], ['building', 'Bina Kontrol'], ['scan', 'Çıkış Kontrol']];

// jsQR (QR okuma yedeği) yalnızca tarayıcı sekmesi açılınca tembel yüklenir
let _jsqrLib = null;
function loadJsQR() {
  return _jsqrLib ??= new Promise((resolve, reject) => {
    if (window.jsQR) return resolve(window.jsQR);
    const s = document.createElement('script');
    s.src = '/static/vendor/jsqr/jsQR.js';
    s.onload = () => (window.jsQR ? resolve(window.jsQR) : reject(new Error('QR okuyucu yüklenemedi')));
    s.onerror = () => { _jsqrLib = null; reject(new Error('QR okuyucu yüklenemedi')); };
    document.head.append(s);
  });
}

export async function render(view, params, ctx) {
  const tab = TABS.some(t => t[0] === params[0]) ? params[0] || '' : '';
  const nav = segmented(TABS, tab, v => { location.hash = v ? `#/security/${v}` : '#/security'; }, { tabs: true });
  const body = h('div');
  // Araçlar sekmesinde yeni giriş düğmesi başlığın sağında (popup)
  const addBtn = h('button', { class: 'btn primary', type: 'button' }, '+ Yeni Araç Girişi');
  clear(view, pageHead('Güvenlik', { back: '#/', sub: 'Araç giriş/çıkış, bina kontrol', tabs: nav }),
    moduleToolbar(tab === '' ? addBtn : null), body);
  if (tab === 'personnel') return renderPersonnel(body);
  if (tab === 'log') return renderLog(body);
  if (tab === 'building') return renderBuilding(body);
  if (tab === 'scan') return renderScan(body);
  return renderVehicles(body, addBtn);
}

// Türk plakası görünümü: solda mavi TR şeridi
export const plateEl = (plate, cls = '') => h('span', { class: `tr-plate ${cls}` }, h('i', null, 'TR'), h('b', null, plate));

async function renderVehicles(body, addBtn) {
  const grid = h('div', { class: 'veh-grid' });
  let list = [];
  const draw = () => clear(grid, list.length ? list.map(v => h('div', { class: 'card veh-card' },
    plateEl(v.plate),
    h('div', { class: 'veh-time' }, t('Giriş {d}', { d: fmtDateTime(v.entered_at) })),
    h('div', { class: 'veh-dur' }, t('{d} içeride', { d: fmtDuration(secondsSince(v.entered_at)) })),
    v.note ? h('div', { class: 'small muted' }, v.note) : null,
    v.visit_code ? h('span', { class: 'badge blue' }, t('Misafir {code}', { code: v.visit_code })) : null,
    h('div', { class: 'veh-acts' },
      v.visit_code ? null : h('button', { class: 'btn sm', type: 'button', title: 'Hatalı plakayı düzelt', onclick: () => vehicleForm(v) }, '✎ Düzelt'),
      h('button', { class: 'btn sm primary', type: 'button', onclick: () => exit(v) }, 'Çıkış Yaptı →'))))
    : h('div', { class: 'card empty' }, 'İçeride kayıtlı araç yok. Gelen araç için sağ üstteki "Yeni Araç Girişi"ni kullanın.'));
  const load = async () => { list = await api.get('/api/security/vehicles'); draw(); };
  async function exit(v) {
    if (!await confirmDialog('Araç çıkışı', t('{plate} çıkış yaptı mı?', { plate: v.plate }), { okLabel: 'Çıkış Yaptı' })) return;
    try {
      await api.post(`/api/security/vehicles/${v.id}/exit`);
      toast(t('{plate} çıkış yaptı', { plate: v.plate }));
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
      if (edit) { const r = await api.put(`/api/security/vehicles/${v.id}`, { plate: plate.value, note: note.value }); toast(t('Plaka güncellendi: {plate}', { plate: r.plate })); }
      else { const r = await api.post('/api/security/vehicles', { plate: plate.value, note: note.value }); toast(t('{plate} giriş yaptı', { plate: r.plate })); }
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

// Görevde / İzinde: güvenliğin çıkışta görmesi için şu an görevde (araç/görev grupları) ve bugün izinli personel.
async function renderPersonnel(body) {
  clear(body, h('div', { class: 'empty' }, 'Yükleniyor…'));
  let d;
  try { d = await api.get('/api/security/personnel'); } catch (e) { clear(body, h('div', { class: 'card empty' }, e.message)); return; }
  // Görevdeki araç/görev grupları: kart başında plaka, altında personel(ler), ne kadardır dışarıda + "Giriş Yaptı"
  const dutyCard = g => {
    const since = () => (g.depart_at ? fmtDuration(secondsSince(g.depart_at)) : '—');
    const enter = h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
      if (!await confirmDialog('Giriş Yaptı', t('{plate} grubu fabrikaya giriş yaptı mı? Araç içeri alınacak.',
        { plate: g.vehicle_plate || 'Araçsız' }), { okLabel: 'Giriş Yaptı' })) return;
      try {
        const r = await api.post(`/api/security/duty/${g.id}/return`, {});
        toast(r.vehicle_entered ? t('{plate} içeri alındı', { plate: r.vehicle_plate }) : 'Giriş kaydedildi');
        await renderPersonnel(body);
      } catch (err) { toastError(err); }
    } }, 'Giriş Yaptı');
    return h('div', { class: 'card card-pad sec-duty-card' },
      h('div', { class: 'sec-duty-head' },
        g.vehicle_plate ? plateEl(g.vehicle_plate, 'sm') : h('span', { class: 'small muted' }, 'Araçsız / kendi aracı'),
        g.source === 'field' ? h('span', { class: 'badge blue' }, 'Saha') : null,
        h('span', { style: { flex: 1 } }),
        h('span', { class: 'small muted' }, since() + ' dışarıda'), enter),
      h('div', { class: 'sec-duty-people' }, (g.people || []).map(p => h('div', { class: 'small' },
        h('b', null, p.name), p.title ? h('span', { class: 'muted' }, ' · ' + p.title) : null))),
      g.destination ? h('div', { class: 'small muted' }, g.destination
        + (g.return_at ? ' · ' + t('tahmini dönüş {d}', { d: (g.return_at || '').slice(0, 10) }) : '')) : null);
  };
  const leaveList = (title, items, rowFn, empty) => h('div', { class: 'card card-pad sec-plist' },
    h('h3', null, title),
    items.length ? h('ul', { class: 'sec-plist-ul' }, items.map(rowFn)) : h('div', { class: 'small muted' }, empty));
  const admins = d.admins_outside || [];
  clear(body,
    leaveList(t('Dışarıdaki yöneticiler ({n})', { n: admins.length }), admins, x => h('li', null,
      h('b', null, x.name), ' ', h('span', { class: 'small muted' }, t('çıkış {d}', { d: fmtDateTime(x.exited_at) }) + ' · ' + fmtDuration(secondsSince(x.exited_at)) + ' dışarıda'), ' ',
      h('button', { class: 'btn sm', type: 'button', onclick: async () => {
        if (!await confirmDialog('Döndü', t('{name} fabrikaya döndü mü?', { name: x.name }), { okLabel: 'Döndü' })) return;
        try { await api.post(`/api/security/admin-exit/${x.id}/return`, {}); toast('Dönüş kaydedildi'); await renderPersonnel(body); } catch (err) { toastError(err); }
      } }, 'Döndü')), 'Dışarıda yönetici yok'),
    h('div', { class: 'card card-pad sec-plist' },
      h('h3', null, t('Görevde ({n})', { n: d.on_duty.length })),
      d.on_duty.length ? h('div', { class: 'sec-duty-list' }, d.on_duty.map(dutyCard)) : h('div', { class: 'small muted' }, 'Şu an görevde personel yok')),
    leaveList(t('İzinde ({n})', { n: d.on_leave.length }), d.on_leave, x => h('li', null,
      h('b', null, x.name), ' ', h('span', { class: 'small muted' }, [x.title, x.kind === 'UCRETSIZ' ? 'ücretsiz izin' : 'izinli'].filter(Boolean).join(' · ')),
      h('span', { class: 'small muted' }, ' · ' + t('{d} tarihine kadar', { d: (x.end_date || '').slice(0, 10) }))), 'Bugün izinli personel yok'));
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
      { icon: 'security', label: 'Giriş', value: rows.length },
      { icon: 'person', label: 'Çıkış', value: rows.filter(r => r.exited_at).length },
      { icon: 'users', label: 'Hâlâ içeride', value: rows.filter(r => !r.exited_at).length, tone: 'ok' },
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
  const list = h('div', { class: 'cl-list bc-list' });
  const active = h('aside', { class: 'bc-side' });
  const wrap = h('div', { class: 'bc-wrap' }, list, active);

  const elapsedText = () => (patrol ? fmtDuration(Math.floor((Date.now() - patrol.startedAt) / 1000)) : '');

  let elapEl = null, posEl = null;
  // Devam eden tur sağ panelde: başlama saati + canlı süre + canlı harita + Bitir. Bittiğinde panel gizlenir, liste tam ekran.
  function drawActive() {
    if (!patrol) { clear(active); active.dataset.pid = ''; wrap.classList.remove('has-active'); return; }
    wrap.classList.add('has-active');
    if (active.dataset.pid === String(patrol.id)) { tickActive(); return; }   // panel kurulu → haritayı koru, sadece güncelle
    active.dataset.pid = String(patrol.id);
    elapEl = h('b', { class: 'bc-elapsed' }, elapsedText());
    posEl = h('span', null, '');
    const mapWrap = h('div', { class: 'bc-live-map' });
    const startedDiff = patrol.day && patrol.day !== bToday() ? ' · ' + fmtDate(patrol.day) : '';
    clear(active,
      h('div', { class: 'bc-side-head' }, h('span', { class: 'bc-rec-dot' }), h('b', null, 'Bina turu sürüyor')),
      h('div', { class: 'bc-side-info' },
        h('div', { class: 'bc-side-row' }, h('span', { class: 'small muted' }, 'Başlama saati'), h('b', null, bHM(patrol.startedAt) + startedDiff)),
        h('div', { class: 'bc-side-row' }, h('span', { class: 'small muted' }, 'Geçen süre'), elapEl),
        h('div', { class: 'bc-side-row' }, h('span', { class: 'small muted' }, 'Kayıtlı konum'), posEl)),
      mapWrap,
      h('div', { class: 'bc-side-acts' },
        h('button', { class: 'btn', type: 'button', onclick: () => bcNotes(patrol.id, 'tur') }, '📝 Sorun / Not'),
        h('button', { class: 'btn danger btn-lg bc-finish', type: 'button', onclick: () => finishPatrol() }, 'Turu Bitir')));
    buildLiveMap(mapWrap);
    tickActive();
  }
  function tickActive() {
    if (!patrol) return;
    if (elapEl) elapEl.textContent = elapsedText();
    if (posEl) posEl.textContent = t('{n} nokta', { n: patrol.posted || 0 });
    updateLiveMap();
  }
  // Canlı harita: tur boyunca kaydedilen noktalarla polyline; son nokta kırmızı işaretle merkezlenir. Anahtar yoksa SVG.
  function buildLiveMap(container) {
    patrol.livePath = patrol.livePath || [];
    clear(container, h('div', { class: 'small muted', style: { padding: '12px' } }, 'Harita yükleniyor…'));
    loadMaps().then(maps => {
      if (!patrol) return;
      if (!maps) { renderLiveSvg(container); return; }
      const mapEl = h('div', { class: 'bc-gmap' });
      clear(container, mapEl);
      const start = patrol.livePath[patrol.livePath.length - 1] || patrol.lastPos || { lat: 39, lng: 35 };
      patrol.liveMap = new maps.Map(mapEl, { mapTypeId: 'terrain', center: { lat: start.lat, lng: start.lng }, zoom: 18, mapTypeControl: true, streetViewControl: false, fullscreenControl: true, gestureHandling: 'cooperative' });
      patrol.livePoly = new maps.Polyline({ path: patrol.livePath.map(p => ({ lat: p.lat, lng: p.lng })), map: patrol.liveMap, strokeColor: '#2563eb', strokeWeight: 4, strokeOpacity: 0.9 });
      patrol.liveMarker = new maps.Marker({ position: { lat: start.lat, lng: start.lng }, map: patrol.liveMap, title: 'Şu an', icon: { path: maps.SymbolPath.CIRCLE, scale: 7, fillColor: '#dc2626', fillOpacity: 1, strokeColor: '#fff', strokeWeight: 2 } });
      updateLiveMap();
    }).catch(() => renderLiveSvg(container));
  }
  function updateLiveMap() {
    if (!patrol) return;
    const path = (patrol.livePath || []).map(p => ({ lat: p.lat, lng: p.lng }));
    if (patrol.livePoly) {
      patrol.livePoly.setPath(path);
      const last = path[path.length - 1] || patrol.lastPos;
      if (last && patrol.liveMarker) { patrol.liveMarker.setPosition(last); if (patrol.liveMap) patrol.liveMap.panTo(last); }
    } else if (patrol._svgWrap) {
      renderLiveSvg(patrol._svgWrap);
    }
  }
  function renderLiveSvg(container) {
    patrol._svgWrap = container;
    const pts = patrol.livePath || [];
    clear(container, pts.length ? trackSvg(pts) : h('div', { class: 'small muted', style: { padding: '14px' } }, 'Konum bekleniyor…'));
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
          .then(() => { patrol.posted++; (patrol.livePath = patrol.livePath || []).push({ lat: p.lat, lng: p.lng }); }).catch(() => {});
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
      else { acts.push(h('span', { class: 'small muted' }, t('{n} konum', { n: c.points }))); if (c.points) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => openTrack(c.id) }, '🗺 Harita')); }
      if (c.id) acts.push(h('button', { class: 'btn sm', type: 'button', onclick: () => bcNotes(c.id, c.slot || bHM(c.started_at)) }, t('📝 Sorun/Not{extra}', { extra: c.notes ? ` (${c.notes})` : '' })));
      return h('div', { class: `bc-item ${c.status === 'BITTI' ? 'done' : ''} ${due ? 'due' : ''}` },
        h('div', { class: 'bc-slot' }, c.slot || '—'),
        h('div', { class: 'grow' },
          h('b', null, c.status === 'BITTI' ? 'Kontrol yapıldı' : c.status === 'DEVAM' ? 'Kontrol sürüyor' : (due ? 'Kontrol zamanı geldi' : 'Planlı kontrol')),
          h('div', { class: 'small muted' }, c.started_at ? `${bHM(c.started_at)}${c.finished_at ? ' – ' + bHM(c.finished_at) : ''}${c.started_by_name ? ' · ' + c.started_by_name : ''}` : 'Bu saatte bina turu atılacak')),
        h('div', { class: 'bc-acts' }, acts));
    });
    clear(list, rows.length ? rows : h('div', { class: 'card empty' }, 'Bugün için planlı kontrol yok. Saatleri Program Ayarları › Modül Ayarları › Güvenlik’ten ekleyin ya da “Kontrol Başlat” deyin.'));
    // Süren turu TARİHTEN BAĞIMSIZ geri yükle (sistem kapansa / gün değişse bile Bitir aktif kalsın)
    checkActive();
  }

  async function checkActive() {
    if (patrol) { drawActive(); return; }
    let a;
    try { a = await api.get('/api/security/building/active'); } catch { return drawActive(); }
    if (a.check) resumePatrol(a.check);
    else drawActive();
  }

  async function resumePatrol(c) {
    patrol = { id: c.id, day: c.day, startedAt: new Date(c.started_at).getTime() || Date.now(), posted: c.points || 0, lastPost: 0, lastPos: null, livePath: [] };
    try { const tr = await api.get(`/api/security/building/${c.id}/track`); patrol.livePath = (tr.points || []).map(p => ({ lat: p.lat, lng: p.lng })); } catch { /* */ }
    if (!patrol) return;
    startTracking();
    drawActive();
  }

  async function startPatrol(d, slot) {
    if (patrol) { toast('Zaten süren bir kontrol var; önce onu bitirin', 'err'); return; }
    if (!navigator.geolocation) { toast('Bu cihaz konum (GPS) desteklemiyor', 'err'); return; }
    let r;
    try { r = await api.post('/api/security/building/start', { date: d, slot }); } catch (err) { return toastError(err); }
    patrol = { id: r.id, day: d, startedAt: Date.now(), posted: 0, lastPost: 0, lastPos: null, livePath: [] };
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
    modal({ title: t('Bina turu · {slot}', { slot: d.slot || bHM(d.started_at) }), wide: true,
      body: h('div', null,
        h('p', { class: 'small muted', style: { marginTop: 0 } }, t('{a} – {b} · {by} · {n} konum', { a: bHM(d.started_at), b: bHM(d.finished_at), by: d.started_by_name || '', n: d.points.length })),
        trackMap(d.points)),
      actions: [{ label: 'Kapat' }] });
  }
  function trackMap(points) {
    if (!points.length) return h('div', { class: 'card empty' }, 'Konum kaydı yok (GPS izni verilmemiş olabilir).');
    // Google Haritalar (terrain) üzerinde rota; anahtar yoksa / yüklenemezse SVG'ye düşülür.
    const wrap = h('div', { class: 'bc-map-wrap' }, trackSvg(points));
    loadMaps().then(maps => {
      if (!maps) return;   // anahtar yok → SVG kalır
      const mapEl = h('div', { class: 'bc-gmap' });
      clear(wrap, mapEl);
      const bounds = new maps.LatLngBounds();
      points.forEach(p => bounds.extend({ lat: p.lat, lng: p.lng }));
      const map = new maps.Map(mapEl, { mapTypeId: 'terrain', mapTypeControl: true, streetViewControl: false,
        fullscreenControl: true, gestureHandling: 'cooperative' });
      map.fitBounds(bounds, 40);
      if (points.length === 1) map.setZoom(19);
      new maps.Polyline({ path: points.map(p => ({ lat: p.lat, lng: p.lng })), map, strokeColor: '#2563eb', strokeWeight: 4, strokeOpacity: 0.9 });
      const a = points[0], b = points[points.length - 1];
      new maps.Marker({ position: { lat: a.lat, lng: a.lng }, map, title: 'Başlangıç',
        icon: { path: maps.SymbolPath.CIRCLE, scale: 7, fillColor: '#16a34a', fillOpacity: 1, strokeColor: '#fff', strokeWeight: 2 } });
      new maps.Marker({ position: { lat: b.lat, lng: b.lng }, map, title: 'Bitiş',
        icon: { path: maps.SymbolPath.CIRCLE, scale: 7, fillColor: '#dc2626', fillOpacity: 1, strokeColor: '#fff', strokeWeight: 2 } });
    }).catch(() => { /* anahtar/yükleme hatası → SVG kalır */ });
    return wrap;
  }

  function trackSvg(points) {
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
    modal({ title: t('Bina turu · {lbl} · Sorun / Notlar', { lbl }), wide: true,
      body: h('div', null, nlist, h('div', { class: 'cl-set-add', style: { marginTop: '10px' } }, ta, h('button', { class: 'btn primary', type: 'button', onclick: add }, 'Ekle'))),
      actions: [{ label: 'Kapat' }] });
  }

  clear(body, bar, wrap);
  load();
}

// ---------- Çıkış Kontrol: personelin onaylı izin/görev QR'ı kamerayla okunur, çıkışa izin verilir ----------
async function renderScan(body) {
  const video = h('video', { class: 'sec-video', autoplay: true, playsinline: true, muted: true });
  const frame = h('div', { class: 'sec-cam' }, video, h('div', { class: 'sec-reticle' }));
  const result = h('div', { class: 'sec-scan' }, h('div', { class: 'sec-scan-idle' }, 'Kamerayı QR koda doğrultun'));
  const toggle = h('button', { class: 'btn', type: 'button' }, 'Kamerayı Durdur');
  const manual = h('input', { class: 'input', type: 'text', placeholder: 'QR okunamadıysa kodu elle yazın', autocomplete: 'off' });
  const manualBtn = h('button', { class: 'btn primary', type: 'button' }, 'Doğrula');

  let stream = null, raf = null, running = false, detector = null, canvas = null, g = null;
  let lastCode = '', lastAt = 0, busy = false;

  const stopCam = () => {
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    try { stream?.getTracks().forEach(tr => tr.stop()); } catch { /* */ }
    stream = null;
    video.srcObject = null;
  };
  onLeave(stopCam);   // sayfadan çıkınca kamerayı serbest bırak

  async function startCam() {
    if (!navigator.mediaDevices?.getUserMedia) { toast('Bu tarayıcı kamerayı desteklemiyor', 'err'); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    } catch (err) { toastError(new Error('Kameraya erişilemedi: ' + (err.message || 'izin verilmedi'))); return; }
    video.srcObject = stream;
    await video.play().catch(() => {});
    running = true;
    frame.classList.remove('off');
    toggle.textContent = 'Kamerayı Durdur';
    if (window.BarcodeDetector) { try { detector = new BarcodeDetector({ formats: ['qr_code'] }); } catch { detector = null; } }
    if (!detector) {
      await loadJsQR().catch(() => toast('QR okuyucu yüklenemedi; kodu elle girebilirsiniz', 'err'));
      canvas = document.createElement('canvas');
      g = canvas.getContext('2d', { willReadFrequently: true });
    }
    scanLoop();
  }

  async function scanLoop() {
    if (!running) return;
    let code = null;
    try {
      if (detector) {
        const found = await detector.detect(video);
        if (found && found.length) code = found[0].rawValue;
      } else if (window.jsQR && video.videoWidth) {
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        g.drawImage(video, 0, 0, canvas.width, canvas.height);
        const img = g.getImageData(0, 0, canvas.width, canvas.height);
        const r = window.jsQR(img.data, img.width, img.height);
        if (r) code = r.data;
      }
    } catch { /* kare okunamadı; sonrakinde yeniden dene */ }
    if (code) onCode(code);
    raf = requestAnimationFrame(scanLoop);
  }

  // Aynı kodu ~3 sn içinde yeniden sorma; bir doğrulama sürerken yenisini başlatma
  function onCode(code) {
    const now = Date.now();
    if (busy || (code === lastCode && now - lastAt < 3000)) return;
    lastCode = code; lastAt = now;
    verify(code);
  }

  async function verify(token) {
    if (!token) return;
    busy = true;
    try { showResult(await api.post('/api/security/verify-pass', { token })); }
    catch (err) { showResult({ allow: false, reason: err.message }); }
    finally { setTimeout(() => { busy = false; }, 1200); }
  }

  function beep(ok) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ac = new Ctx();
      const o = ac.createOscillator(), gain = ac.createGain();
      o.frequency.value = ok ? 880 : 220;
      o.connect(gain); gain.connect(ac.destination);
      gain.gain.setValueAtTime(0.15, ac.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.25);
      o.start(); o.stop(ac.currentTime + 0.26);
      setTimeout(() => { try { ac.close(); } catch { /* */ } }, 400);
    } catch { /* ses zorunlu değil */ }
  }

  function showResult(r) {
    if (r.allow) {
      const d = r.dates || {};
      const line = r.type === 'duty'
        ? `${r.destination || ''} · ${fmtDateTime(d.depart)}${d.return ? ' → ' + fmtDateTime(d.return) : ''}`
        : `${fmtDate(d.start)} – ${fmtDate(d.end)}`;
      result.className = 'sec-scan sec-scan-ok';
      clear(result,
        h('div', { class: 'sec-scan-big' }, '✓ ONAYLI ÇIKIŞ'),
        h('div', { class: 'sec-scan-name' }, r.name || ''),
        r.title ? h('div', { class: 'sec-scan-sub' }, r.title) : null,
        h('div', { class: 'sec-scan-tag' }, r.type === 'duty' ? 'Görev formu' : r.type === 'admin' ? 'Sistem yöneticisi' : 'İzin'),
        r.type === 'admin' ? h('div', { class: 'sec-scan-dates' }, r.returned ? 'Döndü — giriş kaydedildi' : 'Çıkış kaydedildi (sebep gerekmez)') : h('div', { class: 'sec-scan-dates' }, line));
      beep(true);
    } else {
      result.className = 'sec-scan sec-scan-bad';
      clear(result,
        h('div', { class: 'sec-scan-big' }, '✕ ÇIKIŞ YOK'),
        h('div', { class: 'sec-scan-sub' }, r.reason || 'Geçersiz veya süresi dolmuş'),
        h('div', { class: 'sec-scan-note' }, 'Çıkış için onaylı izin/görev formu gerekir.'));
      beep(false);
    }
  }

  toggle.addEventListener('click', () => {
    if (running) { stopCam(); frame.classList.add('off'); toggle.textContent = 'Kamerayı Başlat'; }
    else startCam();
  });
  manualBtn.addEventListener('click', () => { const v = manual.value.trim(); if (v) verify(v); });
  manual.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const v = manual.value.trim(); if (v) verify(v); } });

  clear(body,
    h('div', { class: 'sec-scan-wrap' },
      frame,
      h('div', { class: 'sec-scan-tools' }, toggle),
      result,
      h('div', { class: 'sec-scan-manual' }, manual, manualBtn)));
  startCam();
}
