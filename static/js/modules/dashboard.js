// Kişisel pano (ana sayfa): herkesin kendine göre düzenlediği kutucuklar. Kutucuklar sunucudan (yetkiye göre) gelir;
// düzen (sıra, genişlik, ayar) kullanıcıya özel sunucuda saklanır (user_prefs: dashboard). "Panoyu Düzenle" ile kutucuk
// eklenir, çıkarılır, taşınır, genişliği (1/3, 2/3, tam) ve ayarı (saat biçimi, hava durumu konumu) değiştirilir.
import { api, fileUrl } from '../api.js';
import { icons } from '../icons.js';
import { PRINTER_STATES, orderBadge, queuePlate } from '../status.js';
import { clear, confirmDialog, field, fmtDateTime, h, modal, onLeave, progressBar, segmented, svgIcon, t, toast, toastError } from '../ui.js';
import { LEVELS } from './announcements.js';
import { renderFeed } from './feed.js';
import { noteCard } from './notes.js';
import { getAlarms, saveAlarms, alarmForm, DAYS } from '../alarms.js';
import { chartConfig, loadChart, theme } from './reports.js';

const dbInitials = n => (n || '?').trim().split(/\s+/).slice(0, 2).map(x => x[0]).join('').toLocaleUpperCase('tr');
const dbAvatar = (name, photo, cls = '') => (photo
  ? h('img', { class: `db-av ${cls}`, src: fileUrl(photo, 64), alt: '', loading: 'lazy' })
  : h('span', { class: `db-av ph ${cls}` }, dbInitials(name)));
// Kişi durumu (kullanıcı id'si → görevde / izinde / çevrimiçi / çevrimdışı); avatar çerçevesinde gösterilir
const presenceOf = (id, d) => (d?.on_duty?.includes(id) ? 'duty' : d?.on_leave?.includes(id) ? 'leave' : d?.online?.includes(id) ? 'online' : 'off');
const ST_TITLE = { duty: 'Görevde', leave: 'İzinde', online: 'Çevrimiçi', off: 'Çevrimdışı' };
const dbAvatarSt = (name, photo, id, d, cls = '') => {
  const st = presenceOf(id, d);
  return h('span', { class: `db-avwrap st-${st}`, title: ST_TITLE[st] }, dbAvatar(name, photo, cls));
};

const MULTI = new Set(['clock', 'weather', 'world_clock', 'quick_directory']);   // birden çok eklenebilen / ayarlı
// GridStack (sürükle-bırak pano) — vendor'dan yüklenir (offline). 12 sütun; 1/3=4, 2/3=8, tam=12.
let gridLib;
function loadGridStack() {
  return gridLib ??= new Promise((resolve, reject) => {
    if (window.GridStack) return resolve(window.GridStack);
    if (!document.querySelector('link[data-gridstack]')) {
      const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/vendor/gridstack/gridstack.min.css'; l.dataset.gridstack = '1'; document.head.append(l);
    }
    const s = document.createElement('script'); s.src = '/static/vendor/gridstack/gridstack-all.js';
    s.onload = () => resolve(window.GridStack);
    s.onerror = () => { gridLib = null; reject(new Error('Pano bileşeni yüklenemedi')); };
    document.head.append(s);
  });
}
const DEF_H = { company_news: 6, chart_production: 5, kpi_production: 3, clock: 3, weather: 3, modules: 3, calendar: 5, birthdays: 4, forecast: 3, email: 5, world_clock: 3, my_messages: 5, my_meetings: 4, quick_directory: 4, notes: 5, alarm: 4, active_users: 4, files: 4, on_duty: 4, on_leave: 4, spotify: 6 };
const dbUid = () => Math.random().toString(36).slice(2, 9);
const PRINTER_COLORS = { YAZDIRIYOR: '#3b82f6', HAZIR: '#22c55e', TAMAMLANDI: '#a855f7', DURAKLADI: '#f59e0b', HATA: '#ef4444', CEVRIMDISI: '#6b7280', BAKIM: '#f59e0b' };
// Spotify kutucuğu ikonları (inline SVG; markadan bağımsız basit vektörler)
const spSvg = markup => { const t = document.createElement('template'); t.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${markup}</svg>`; return t.content.firstElementChild; };
const SP_PLAY = () => spSvg('<path d="M8 5v14l11-7z"/>');
const SP_PAUSE = () => spSvg('<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>');
const SP_ICON = d => spSvg(`<path d="${d}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`);
const SP_LOGO = () => { const t = document.createElement('template'); t.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#1DB954"/><g fill="none" stroke="#000" stroke-width="1.8" stroke-linecap="round"><path d="M6 9.5c4-1 8-.6 11 1"/><path d="M6.8 13c3.2-.8 6.4-.4 9 1.1"/><path d="M7.6 16.2c2.4-.6 4.9-.3 7 .9"/></g></svg>'; return t.content.firstElementChild; };

export async function renderDashboard(view, ctx, modules) {
  // Mobilde (ayar açıksa) pano yerine tam ekran Şirketten Haberler akışı (üst menü + alt bilgi kalır)
  if (ctx.user.prefs?.settings?.feedFullMobile && matchMedia('(max-width: 768px)').matches) {
    const box = h('div', { class: 'feed-full' });
    clear(view, box);
    try { renderFeed(box, ctx, { view: ctx.user.prefs?.settings?.feedView || 'feed' }); }
    catch (err) { clear(box, h('div', { class: 'card empty' }, err.message)); }
    return;
  }
  const [avail, saved, savedPresets] = await Promise.all([api.get('/api/dashboard/widgets'), api.get('/api/me/prefs/dashboard').catch(() => ({})), api.get('/api/me/prefs/dashboard_presets').catch(() => ({}))]);
  const byKey = Object.fromEntries(avail.map(w => [w.key, w]));
  const GridStack = await loadGridStack().catch(() => null);
  let layout;
  try { layout = JSON.parse(saved.value || 'null'); } catch { layout = null; }
  if (!Array.isArray(layout)) layout = avail.filter(w => w.default).map(w => ({ k: w.key }));
  // Eski {k,s} → {k,w}; id/boyut/yükseklik tamamla (GridStack 12 sütun: 1/3=4, 2/3=8, tam=12)
  layout = layout.filter(it => byKey[it.k]).map(it => ({
    id: it.id || dbUid(), k: it.k, o: it.o,
    w: it.w || (it.s ? it.s * 4 : 4), h: it.h || DEF_H[it.k] || 4, x: it.x, y: it.y }));
  for (const w of avail) if (w.fixed && !layout.some(it => it.k === w.key)) layout.unshift({ id: dbUid(), k: w.key, w: (w.size || 1) * 4, h: DEF_H[w.key] || 6 });

  // Düzeni kaydedilebilir biçime çevir / ham diziyi normalize et (ekli kutucuk/boyut tamamla) — Yerleşim ön-ayarları için
  const serializeLayout = arr => (arr || layout).map(it => ({ id: it.id, k: it.k, o: it.o, x: it.x, y: it.y, w: it.w, h: it.h }));
  const normalizeLayout = arr => {
    let ly = (Array.isArray(arr) ? arr : []).filter(it => byKey[it.k]).map(it => ({
      id: it.id || dbUid(), k: it.k, o: it.o,
      w: it.w || (it.s ? it.s * 4 : 4), h: it.h || DEF_H[it.k] || 4, x: it.x, y: it.y }));
    for (const w of avail) if (w.fixed && !ly.some(it => it.k === w.key)) ly.unshift({ id: dbUid(), k: w.key, w: (w.size || 1) * 4, h: DEF_H[w.key] || 6 });
    return ly;
  };
  // Kayıtlı yerleşim ön-ayarları (kullanıcıya özel, user_prefs: dashboard_presets)
  let presets = [];
  try { presets = JSON.parse(savedPresets.value || '[]'); if (!Array.isArray(presets)) presets = []; } catch { presets = []; }
  const savePresets = () => api.put('/api/me/prefs/dashboard_presets', { value: JSON.stringify(presets) }).catch(() => {});

  let editing = false, data = {}, grid = null;
  const charts = [], timers = [], bodies = {}, feeds = {}, headActs = {};   // feeds: company_news yeniden yükleyici; headActs: kutu başlık eylem slotu
  // Kutu başlığındaki eylem düğmeleri: 2+ ise tek kapsülde (pill), değilse tek düğme. Boşsa slot gizli (CSS :empty).
  const setActs = (acts, ...btns) => { const b = btns.flat().filter(Boolean); if (acts) clear(acts, b.length >= 2 ? h('div', { class: 'db-acts-pill' }, b) : b); };
  let refreshTimer = null;
  onLeave(() => { charts.forEach(c => c.destroy()); timers.forEach(clearInterval); clearInterval(refreshTimer); try { grid?.destroy(false); } catch { /* */ } });
  const gridEl = h('div', { class: 'grid-stack' });
  const editBtn = h('button', { class: 'btn', type: 'button', onclick: () => setEdit(!editing) }, 'Panoyu Düzenle');
  const addBtn = h('button', { class: 'btn', type: 'button', hidden: true, onclick: () => addWidget() }, '＋ Kutucuk Ekle');
  const presetsBtn = h('button', { class: 'btn', type: 'button', hidden: true, onclick: () => managePresets() }, '🗂 Yerleşimler');

  const loadData = async () => {
    const keys = [...new Set(layout.map(it => it.k))].filter(k => !['clock', 'weather', 'modules'].includes(k));
    data = keys.length ? await api.get(`/api/dashboard/data?keys=${keys.join(',')}`) : {};
  };

  function persist() {
    if (!grid) return;
    if (grid.getColumn && grid.getColumn() !== 12) return;   // mobil tek-sütun reflow'u kayıtlı 12-sütun düzenini bozmasın
    // Nesne kimliğini KORU: mevcut öğeleri yerinde güncelle (kutucuk içindeki closure'lar — ör. Takvim görünümü — geçerli kalsın)
    const byId = Object.fromEntries(layout.map(it => [String(it.id), it]));
    const order = [];
    for (const n of grid.save(false)) {
      const it = byId[String(n.id)];
      if (!it) continue;
      it.x = n.x; it.y = n.y; it.w = n.w; it.h = n.h;
      order.push(it);
    }
    layout = order;
    api.put('/api/me/prefs/dashboard', { value: JSON.stringify(serializeLayout()) }).catch(() => {});
  }

  function itemEl(it) {
    const w = byKey[it.k];
    const body = h('div', { class: 'db-body' });
    bodies[it.id] = body;
    const acts = h('div', { class: 'db-acts' });   // kutuya ait eylem düğmeleri: başlıkta en sağda (2+ ise tek kapsülde)
    headActs[it.id] = acts;
    const tools = h('div', { class: 'db-tools' },
      MULTI.has(it.k) ? h('button', { type: 'button', title: 'Ayarlar', onclick: () => settings(it) }, '⚙') : null,
      w.fixed ? null : h('button', { type: 'button', class: 'danger', title: 'Kaldır', onclick: () => removeItem(it) }, '✕'));
    const el = h('div', { class: 'grid-stack-item', 'gs-id': it.id, 'gs-w': it.w, 'gs-h': it.h },
      h('div', { class: `grid-stack-item-content card db-tile w-${it.k}` },
        h('div', { class: 'db-head' }, h('h3', null, it.k === 'weather' && it.o?.name ? t('Hava durumu · {name}', { name: it.o.name }) : w.title), acts, tools), body));
    if (it.x != null) el.setAttribute('gs-x', it.x);
    if (it.y != null) el.setAttribute('gs-y', it.y);
    // w.fixed: kaldırılamaz (✕ yok) ama boyutlandırılabilir — gs-no-resize konmaz
    if (it.k === 'company_news') {   // görünüm (Akış/Harita) Kişisel Ayarlar › Pano'dan seçilir
      try { feeds[it.id] = renderFeed(body, ctx, { view: ctx.user.prefs?.settings?.feedView || 'feed', headActions: acts })?.reload; }
      catch (err) { clear(body, h('div', { class: 'empty small' }, err.message)); }
    } else {
      try { fill(it, body, acts); } catch (err) { clear(body, h('div', { class: 'empty small' }, err.message)); }
    }
    return el;
  }

  function build() {
    charts.splice(0).forEach(c => c.destroy());
    timers.splice(0).forEach(clearInterval);
    if (grid) { try { grid.off('change added removed'); grid.destroy(false); } catch { /* */ } }
    clear(gridEl, layout.map(itemEl));
    if (!GridStack) return;
    // Mobilde (≤768px) tek sütun: her kutucuk tam genişlik. Masaüstünde 12 sütun.
    grid = GridStack.init({ column: 12, columnOpts: { breakpointForWindow: true, layout: 'list', breakpoints: [{ w: 768, c: 1 }] },
      cellHeight: 76, margin: 6, float: false, handle: '.db-head', staticGrid: !editing }, gridEl);
    grid.on('change added removed', persist);
  }

  function refill() {   // içeriği yenile (grid yapısına dokunmadan)
    charts.splice(0).forEach(c => c.destroy());
    timers.splice(0).forEach(clearInterval);
    for (const it of layout) {
      const b = bodies[it.id]; if (!b) continue;
      if (it.k === 'company_news') { feeds[it.id]?.(); continue; }   // kendi yükleyicisiyle tazelenir; fill() ile silinmesin
      try { fill(it, b, headActs[it.id]); } catch { /* */ }
    }
  }

  function setEdit(on) {
    editing = on;
    editBtn.textContent = on ? 'Düzenlemeyi Bitir' : 'Panoyu Düzenle';
    addBtn.hidden = !on;
    presetsBtn.hidden = !on;
    gridEl.classList.toggle('editing', on);
    grid?.setStatic(!on);
  }

  function removeItem(it) {
    const el = gridEl.querySelector(`.grid-stack-item[gs-id="${it.id}"]`);
    layout = layout.filter(x => x.id !== it.id);
    if (el && grid) grid.removeWidget(el); else build();
    persist();
  }

  // --- Yerleşim ön-ayarları: mevcut pano düzenini adlandırıp kaydet, sonra tek tıkla geri çağır ---
  async function applyPreset(p) {
    layout = normalizeLayout(p.layout || []);
    await loadData().catch(() => {});
    build(); persist();   // aktif düzen olarak da yaz
    toast(`“${p.name}” yerleşimi uygulandı`);
  }
  function managePresets() {
    const listEl = h('div', { class: 'db-preset-list' });
    const draw = () => clear(listEl, presets.length ? presets.map((p, i) => h('div', { class: 'db-preset-row' },
      h('div', { class: 'grow' }, h('b', null, p.name),
        h('small', { class: 'muted' }, ` · ${(p.layout || []).length} kutucuk${p.ts ? ' · ' + new Date(p.ts).toLocaleDateString('tr-TR') : ''}`)),
      h('button', { class: 'btn xs primary', type: 'button', onclick: () => { applyPreset(p); m.close(); } }, 'Çağır'),
      h('button', { class: 'btn xs', type: 'button', title: 'Üzerine kaydet', onclick: () => {
        p.layout = serializeLayout(); p.ts = Date.now(); savePresets(); draw(); toast(`“${p.name}” güncellendi`);
      } }, '↻'),
      h('button', { class: 'btn xs danger', type: 'button', title: 'Sil', onclick: async () => {
        if (await confirmDialog('Yerleşimi sil', `“${p.name}” silinsin mi?`, { okLabel: 'Sil', danger: true })) {
          presets.splice(i, 1); savePresets(); draw();
        }
      } }, '✕')))
      : h('div', { class: 'empty small' }, 'Henüz kayıtlı yerleşim yok. Mevcut düzeni aşağıdan kaydedin.'));
    draw();
    const nameInp = h('input', { class: 'input', type: 'text', maxlength: '40', placeholder: 'Yerleşim adı (ör. Üretim görünümü)' });
    const saveCur = () => {
      const nm = nameInp.value.trim();
      if (!nm) { toast('Bir ad girin'); nameInp.focus(); return; }
      const ex = presets.find(p => p.name.toLowerCase() === nm.toLowerCase());
      if (ex) { ex.layout = serializeLayout(); ex.ts = Date.now(); }
      else presets.push({ name: nm, ts: Date.now(), layout: serializeLayout() });
      savePresets(); nameInp.value = ''; draw(); toast(ex ? `“${nm}” güncellendi` : `“${nm}” kaydedildi`);
    };
    const m = modal({
      title: 'Pano Yerleşimleri', wide: true,
      body: h('div', null,
        h('p', { class: 'muted small' }, 'Mevcut pano düzenini kaydedip istediğiniz zaman geri çağırabilirsiniz.'),
        listEl,
        h('div', { class: 'db-preset-save' }, nameInp,
          h('button', { class: 'btn primary', type: 'button', onclick: saveCur }, '💾 Mevcut düzeni kaydet'))),
      actions: [{ label: 'Kapat' }],
    });
  }

  const GROUP_ORDER = ['Kişisel', 'Genel', 'Üretim', 'Depo & Stok', 'Saha', 'Ofis & Güvenlik', 'Sistem'];
  const pickClosed = () => { try { return new Set(JSON.parse(localStorage.getItem('db.pickClosed') || '[]')); } catch { return new Set(); } };
  const savePickClosed = s => { try { localStorage.setItem('db.pickClosed', JSON.stringify([...s])); } catch { /* */ } };
  function addWidget() {
    const used = new Set(layout.map(it => it.k));
    const list = avail.filter(w => MULTI.has(w.key) || !used.has(w.key));
    // Konuya göre grupla (sıralı); grup başlığına tıklayınca açılır/kapanır, durum cihazda hatırlanır
    const groups = new Map();
    for (const w of list) { const g = w.group || 'Genel'; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(w); }
    const order = [...groups.keys()].sort((a, b) => (GROUP_ORDER.indexOf(a) + 1 || 99) - (GROUP_ORDER.indexOf(b) + 1 || 99));
    const closed = pickClosed();
    const add = w => async () => {
      const it = { id: dbUid(), k: w.key, w: (w.size || 1) * 4, h: DEF_H[w.key] || 4 };
      layout.push(it); m.close();
      await loadData().catch(() => {}); build(); persist();
      if (MULTI.has(w.key)) settings(it);
    };
    const section = g => {
      const items = groups.get(g);
      const box = h('div', { class: `db-pick-grp ${closed.has(g) ? 'closed' : ''}` });
      const head = h('button', { type: 'button', class: 'db-pick-grp-h' },
        h('span', { class: 'grow' }, g), h('span', { class: 'db-pick-n' }, items.length), h('span', { class: 'db-pick-caret', 'aria-hidden': 'true' }));
      head.addEventListener('click', () => { const sh = box.classList.toggle('closed'); const s = pickClosed(); sh ? s.add(g) : s.delete(g); savePickClosed(s); });
      box.append(head, h('div', { class: 'db-pick-body' }, h('div', { class: 'db-pick' }, items.map(w =>
        h('button', { type: 'button', class: 'db-pick-item', onclick: add(w) }, h('b', null, w.title), h('span', null, w.desc))))));
      return box;
    };
    const m = modal({
      title: 'Kutucuk Ekle', wide: true,
      body: list.length ? h('div', { class: 'db-pick-groups' }, order.map(section)) : h('div', { class: 'empty' }, 'Eklenebilecek başka kutucuk yok'),
      actions: [{ label: 'Kapat' }],
    });
  }

  function settings(it) {
    if (it.k === 'clock') {
      let style = it.o?.style || 'digital';
      modal({ title: 'Saat', body: h('div', null, field('Görünüm', segmented([['digital', 'Dijital'], ['analog', 'Analog']], style, v => { style = v; }))),
        actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: () => { it.o = { ...it.o, style }; persist(); build(); } }] });
      return;
    }
    if (it.k === 'world_clock') {
      const cities = [...(it.o?.cities || [])];
      const listEl = h('div', { class: 'db-wc-edit' });
      const draw = () => clear(listEl, cities.length ? cities.map((c, i) => h('div', { class: 'db-wc-row' },
        h('span', { class: 'grow' }, h('b', null, c.name), h('small', { class: 'muted' }, ` · ${c.tz}`)),
        h('button', { class: 'btn xs', type: 'button', onclick: () => { cities.splice(i, 1); draw(); } }, 'Kaldır')))
        : h('div', { class: 'empty small' }, 'Henüz şehir eklenmedi'));
      draw();
      const q = h('input', { class: 'input', type: 'search', placeholder: 'Şehir ara… (ör. Londra, Tokyo)' });
      const res = h('div', { class: 'pick-list' });
      let timer;
      q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(async () => {
        if (q.value.trim().length < 2) { clear(res); return; }
        try {
          const r = await (await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q.value.trim())}&count=8&language=tr&format=json`)).json();
          clear(res, (r.results || []).map(c => h('button', { class: 'pick', type: 'button', onclick: () => {
            if (!cities.some(x => x.name === c.name && x.tz === c.timezone)) cities.push({ name: c.name, tz: c.timezone });
            q.value = ''; clear(res); draw();
          } }, h('div', { class: 'grow' }, h('b', null, c.name), h('span', { class: 'small muted' }, [c.admin1, c.country, c.timezone].filter(Boolean).join(' · '))))));
        } catch { clear(res, h('div', { class: 'empty small' }, 'Şehir araması yapılamadı (internet?)')); }
      }, 300); });
      modal({ title: 'Dünya Saati — şehirler', wide: true, body: h('div', null, listEl, field('Şehir ekle', q), res),
        actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: () => { it.o = { ...it.o, cities }; persist(); build(); } }] });
      return;
    }
    if (it.k === 'quick_directory') {
      const people = [...(it.o?.people || [])];
      const listEl = h('div', { class: 'db-wc-edit' });
      const draw = () => clear(listEl, people.length ? people.map((c, i) => h('div', { class: 'db-wc-row' },
        dbAvatar(c.name, c.photo), h('span', { class: 'grow' }, h('b', null, c.name), c.email ? h('small', { class: 'muted' }, ` · ${c.email}`) : null),
        h('button', { class: 'btn xs', type: 'button', onclick: () => { people.splice(i, 1); draw(); } }, 'Kaldır')))
        : h('div', { class: 'empty small' }, 'Henüz kişi eklenmedi'));
      draw();
      const q = h('input', { class: 'input', type: 'search', placeholder: 'Ad ya da e-posta ara…' });
      const res = h('div', { class: 'pick-list' });
      let all = null, timer;
      const search = async () => {
        if (!all) { try { all = await api.get('/api/people'); } catch { all = []; } }
        const term = q.value.trim().toLocaleLowerCase('tr');
        clear(res, all.filter(u => !people.some(x => x.id === u.id)
          && (!term || `${u.full_name} ${u.username || ''}`.toLocaleLowerCase('tr').includes(term))).slice(0, 20).map(u =>
          h('button', { class: 'pick', type: 'button', onclick: () => {
            people.push({ id: u.id, name: u.full_name, photo: u.photo, email: (u.username || '').includes('@') ? u.username : null }); q.value = ''; search(); draw();
          } }, dbAvatar(u.full_name, u.photo), h('div', { class: 'grow' }, h('b', null, u.full_name), u.username ? h('span', { class: 'small muted' }, u.username) : null))));
      };
      q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 200); });
      const m = modal({ title: 'Hızlı Rehber — kişiler', wide: true, body: h('div', null, listEl, field('Kişi ekle', q), res),
        actions: [{ label: 'Vazgeç' }, { label: 'Kaydet', class: 'primary', onClick: () => { it.o = { ...it.o, people }; persist(); build(); } }] });
      search();
      return;
    }
    // Hava durumu: bulunduğum konum (tarayıcı izni) ya da şehir arama
    const q = h('input', { class: 'input', type: 'search', placeholder: 'Şehir ya da ilçe ara… (ör. Kalecik)' });
    const results = h('div', { class: 'pick-list' });
    const m = modal({ title: 'Hava durumu konumu', body: h('div', null,
      h('button', { class: 'btn', type: 'button', style: { marginBottom: '12px' }, onclick: () => { it.o = { mode: 'auto' }; m.close(); build(); persist(); } },
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
            it.o = { mode: 'city', name: c.name, lat: c.latitude, lon: c.longitude }; m.close(); build(); persist();
          } }, h('div', { class: 'grow' }, h('b', null, c.name), h('span', { class: 'small muted' }, [c.admin1, c.country].filter(Boolean).join(', '))))));
        } catch { clear(results, h('div', { class: 'empty small' }, 'Şehir araması yapılamadı (internet bağlantısı?)')); }
      }, 300);
    });
    q.focus();
  }

  // ---------- kutucuk içerikleri
  function fill(it, body, acts) {
    if (acts) clear(acts);   // başlık eylem slotunu sıfırla (refill'de çoğalmasın); ilgili kutular yeniden doldurur
    const d = data[it.k] || {};
    const list = (items, row, empty) => clear(body, items?.length ? h('ul', { class: 'db-list' }, items.map(row)) : h('div', { class: 'db-none' }, empty));
    const kpis = arr => clear(body, h('div', { class: 'db-kpis' }, arr.map(k => h(k.href ? 'a' : 'div', { class: `db-kpi ${k.tone || ''}`, href: k.href },
      h('b', null, k.value ?? '—'), h('span', null, k.label), k.sub ? h('small', null, k.sub) : null))));
    switch (it.k) {
      case 'clock': return clock(body, it.o?.style || 'digital');
      case 'weather': return weather(body, it.o || { mode: 'auto' });
      case 'world_clock': return worldClock(body, it);
      case 'email': return clear(body, d.boxes === 0
        ? h('div', { class: 'db-none' }, h('span', null, 'Bağlı mail hesabınız yok. '), h('a', { href: '#/settings/mailboxes' }, 'Hesap bağla →'))
        : !d.items?.length ? h('div', { class: 'db-none' }, '✓ Okunmamış e-posta yok')
          : [h('div', { class: 'db-mailhead' }, h('b', null, `${d.count} okunmamış`), h('a', { class: 'small', href: '#/mail' }, 'Tümü →')),
            h('ul', { class: 'db-list db-maillist' }, d.items.map(mi => h('li', null,
              h('a', { href: `#/mail/${mi.box_id}/m/${mi.uid}/${encodeURIComponent(mi.folder || 'inbox')}` },
                h('span', { class: 'db-mail-from' }, mi.from || '(gönderen yok)'),
                h('span', { class: 'db-mail-subj' }, mi.subject || '(konu yok)')),
              h('small', null, mi.date ? fmtDateTime(mi.date).replace(/\.\d{4}/, '') : ''))))]);
      case 'my_messages': return clear(body, !d.items?.length ? h('div', { class: 'db-none' }, 'Henüz mesajınız yok')
        : h('ul', { class: 'db-list db-msglist' }, d.items.map(mi => h('li', { class: mi.unread ? 'unread' : '' },
          h('a', { href: `#/messages/u${mi.peer_id}` },
            dbAvatarSt(mi.name, mi.photo, mi.peer_id, d),
            h('span', { class: 'db-msg-main' }, h('b', null, mi.name), h('span', { class: 'db-msg-prev' }, mi.preview || '')),
            mi.unread ? h('span', { class: 'db-n' }, mi.unread) : h('small', null, mi.at ? fmtDateTime(mi.at).replace(/\.\d{4}/, '') : ''))))));
      case 'my_meetings': return clear(body, !d.items?.length ? h('div', { class: 'db-none' }, 'Aktif ya da bekleyen toplantı yok')
        : h('ul', { class: 'db-list db-meetlist' }, d.items.map(mt => h('li', null,
          h('a', { href: `#/meet/${mt.id}` },
            h('span', { class: 'db-meet-main' }, h('b', null, mt.title || 'Toplantı'),
              h('small', null, [mt.host_name, mt.participants ? `${mt.participants} katılımcı` : null].filter(Boolean).join(' · '))),
            mt.status === 'DEVAM' ? h('span', { class: 'badge green' }, '● Devam ediyor') : h('span', { class: 'badge' }, 'Bekliyor'))))));
      case 'notes': { dbNotes(body, acts); return; }
      case 'alarm': { dbAlarms(body, acts); return; }
      case 'spotify': { dbSpotify(body, acts, d); return; }
      case 'active_users': return clear(body, !d.items?.length ? h('div', { class: 'db-none' }, 'Çevrimiçi başka kullanıcı yok')
        : h('div', { class: 'db-users' }, d.items.map(u => { const b = h('button', { type: 'button', class: 'db-user', title: u.full_name }, dbAvatar(u.full_name, u.photo, 'lg'), h('span', { class: 'db-user-n' }, (u.full_name || '').split(' ')[0])); b.addEventListener('click', e => miniChat(u, e.currentTarget)); return b; })));
      case 'quick_directory': {
        const ppl = it.o?.people || [];
        return clear(body, !ppl.length ? h('div', { class: 'db-none' }, h('span', null, 'Kişi ekleyin: '), h('button', { class: 'link', type: 'button', onclick: () => settings(it) }, 'Ayarlar ⚙'))
          : h('ul', { class: 'db-list db-qdlist' }, ppl.map(c => h('li', null,
            h('a', { class: 'db-qd-main', href: `#/messages/u${c.id}`, title: 'Mesaj gönder' }, dbAvatarSt(c.name, c.photo, c.id, d), h('b', null, c.name)),
            h('span', { class: 'db-qd-acts' },
              h('a', { class: 'db-qd-ic', href: `#/messages/u${c.id}`, title: 'Mesaj' }, svgIcon(icons.chat)),
              h('button', { class: 'db-qd-ic', type: 'button', title: 'Sesli Arama',
                onclick: () => import('./voice.js').then(v => v.startCall([c.id], { [c.id]: c.name }, { [c.id]: c.photo })) }, svgIcon(icons.phone)),
              h('button', { class: 'db-qd-ic', type: 'button', title: 'Görüntülü Arama',
                onclick: () => import('./voice.js').then(v => v.startCall([c.id], { [c.id]: c.name }, { [c.id]: c.photo }, { video: true })) }, svgIcon(icons.videocam)))))));
      }
      case 'modules': return clear(body, h('div', { class: 'db-modules' }, modules.map(m => h('a', { href: `#/${m.key}`, class: m.tone ? `tone-${m.tone}` : '' },
        h('span', { class: 'ico' }, svgIcon(icons[m.key])), h('span', null, m.title)))));
      case 'announcements': return list(d.items, a => h('li', null, h('a', { href: `#/announcements/${a.id}` },
        h('span', { class: `badge ${(LEVELS[a.level] || LEVELS.BILGI)[0]}` }, (LEVELS[a.level] || LEVELS.BILGI)[1]), ' ', h('b', null, a.title)),
      h('small', null, fmtDateTime(a.created_at))), 'Yeni duyuru yok');
      case 'notifications': return list(d.items, n => h('li', null, h('a', { href: n.href }, h('span', { class: 'db-n' }, n.count), n.title),
        n.detail ? h('small', null, n.detail) : null), 'Bekleyen bildiriminiz yok');
      case 'alerts': return list(d.items, a => h('li', { class: a.critical ? 'crit' : '' }, h('a', { href: `#/alerts/${a.key}` }, h('span', { class: `db-n ${a.level}` }, a.count), a.title)),
        'Uyarı yok');
      case 'calendar': { dbCalendar(it, body, d.items || []); return; }
      case 'on_duty': { dbOnDuty(body, d.items || []); return; }
      case 'on_leave': return clear(body, (d.items || []).length
        ? h('ul', { class: 'db-list db-plist' }, d.items.map(x => h('li', { class: 'db-prow' },
          dbAvatar(x.name, x.photo, 'lg'),
          h('div', { class: 'db-prow-main' }, h('b', null, x.name),
            h('span', { class: 'db-prow-sub' }, [x.kind === 'UCRETSIZ' ? 'ücretsiz izin' : 'izinli', t('{d} tarihine kadar', { d: (x.end_date || '').slice(0, 10) })].filter(Boolean).join(' · '))))))
        : h('div', { class: 'db-none' }, 'Bugün izinli personel yok'));
      case 'birthdays': return list(d.items, b => h('li', { class: b.today ? 'db-bday-today' : '' },
        h('span', null, h('span', { class: 'db-bday-ico' }, '🎂'), h('b', null, b.name), b.age ? h('small', { class: 'muted' }, ` · ${b.age}`) : null),
        h('small', null, b.today ? '🎉 Bugün!' : (b.days === 1 ? 'Yarın' : t('{n} gün sonra', { n: b.days })) + ` · ${b.date.slice(8, 10)}.${b.date.slice(5, 7)}`)),
      'Yaklaşan doğum günü yok');
      case 'my_cargo': return list(d.items, k => h('li', null, h('a', { href: '#/my-cargo' }, h('b', null, k.carrier || 'Kargo'), k.description ? ` · ${k.description}` : ''),
        h('small', null, fmtDateTime(k.created_at))), 'Bekleyen kargonuz yok');
      case 'my_calls': return list(d.items, c => h('li', null, h('a', { href: '#/my-calls' }, h('b', null, c.caller_name),
        c.subject ? ` · ${c.subject}` : c.caller_company ? ` · ${c.caller_company}` : ''), c.callback ? h('span', { class: 'badge red' }, 'Geri ara') : null,
      h('small', null, fmtDateTime(c.created_at))), 'Bekleyen aramanız yok');
      case 'my_guests': return list(d.items, g => h('li', null, h('a', { href: '#/my-guests' }, h('b', null, g.names || g.code), g.purpose ? ` · ${g.purpose}` : ''),
        h('small', null, g.left_at ? 'çıktı' : 'içeride')), 'Bugün misafiriniz yok');
      case 'files': {
        const recent = d.recent || [];
        return clear(body,
          h('div', { class: 'db-mailhead' }, h('a', { class: 'small', href: '#/my-files' }, 'Dosyalarım →'),
            d.shared > 0 ? h('a', { class: 'db-n-link', href: '#/my-files/shared' }, svgIcon(icons.share), t('{n} paylaşılan', { n: d.shared })) : null),
          recent.length
            ? h('ul', { class: 'db-list' }, recent.map(f => h('li', null,
              h('a', { href: '#/my-files' }, svgIcon(icons.file), h('b', null, f.name)),
              h('small', null, fmtDateTime(f.updated_at).replace(/\.\d{4}/, '')))))
            : h('div', { class: 'db-none' }, 'Henüz dosyanız yok'));
      }
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
  // Takvimim: Liste / Gün / Hafta görünümleri (seçim kutucukta hatırlanır)
  function dbCalendar(it, body, items) {
    const view = it.o?.view || 'list';
    const evLine = e => h('li', { class: e.kind === 'TOPLANTI' ? 'db-meeting' : '' },
      h('a', { href: e.href || '#/calendar' }, h('span', { class: 'db-time' }, fmtDateTime(e.at).replace(/\.\d{4}/, '')), e.title),
      e.kind === 'TOPLANTI' ? h('small', null, e.live ? h('span', { class: 'badge green' }, 'Devam ediyor') : 'Toplantı',
        e.pending ? [' · ', h('span', { class: 'badge yellow' }, 'Yanıt bekliyor')] : null, e.location ? ` · ${e.location}` : '')
        : h('small', null, e.kind === 'HATIRLATMA' ? 'Hatırlatma' : 'Randevu'));
    const dayKey = at => (at || '').slice(0, 10);
    const timeOf = at => (at ? new Date(at).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }) : '');
    const today = new Date().toISOString().slice(0, 10);
    const tabs = segmented([['list', 'Liste'], ['day', 'Gün'], ['week', 'Hafta']], view, v => { it.o = { ...it.o, view: v }; persist(); dbCalendar(it, body, items); });
    let content;
    if (view === 'day') {
      const ev = items.filter(e => dayKey(e.at) === today);
      content = ev.length ? h('ul', { class: 'db-list db-cal-day' }, ev.map(e => h('li', { class: e.kind === 'TOPLANTI' ? 'db-meeting' : '' },
        h('a', { href: e.href || '#/calendar' }, h('span', { class: 'db-cal-time' }, timeOf(e.at)), h('b', null, e.title)),
        e.kind === 'TOPLANTI' && e.live ? h('span', { class: 'badge green' }, 'Devam ediyor') : null))) : h('div', { class: 'db-none' }, 'Bugün için kayıt yok');
    } else if (view === 'week') {
      const start = new Date(); const dow = (start.getDay() + 6) % 7; start.setDate(start.getDate() - dow); start.setHours(0, 0, 0, 0);
      const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d.toISOString().slice(0, 10); });
      const names = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
      const byDay = {}; items.forEach(e => { const k = dayKey(e.at); if (days.includes(k)) (byDay[k] ||= []).push(e); });
      content = h('div', { class: 'db-cal-week' }, days.map((dk, i) => h('div', { class: `db-cal-wd ${dk === today ? 'today' : ''}` },
        h('div', { class: 'db-cal-wd-h' }, h('b', null, names[i]), h('span', { class: 'muted' }, dk.slice(8) + '.' + dk.slice(5, 7))),
        (byDay[dk] || []).length ? h('ul', { class: 'db-list' }, byDay[dk].map(e => h('li', { class: e.kind === 'TOPLANTI' ? 'db-meeting' : '' },
          h('a', { href: e.href || '#/calendar' }, h('span', { class: 'db-cal-time' }, timeOf(e.at)), e.title)))) : h('div', { class: 'db-cal-empty' }, '—'))));
    } else {
      content = items.length ? h('ul', { class: 'db-list' }, items.map(evLine)) : h('div', { class: 'db-none' }, 'Yaklaşan randevu ya da toplantı yok');
    }
    clear(body, h('div', { class: 'db-cal-tabs' }, tabs), content);
  }

  // Hızlı (inline) sohbet: küçük açılır pencere; merkezi Mesajlar ekranına GİTMEDEN burada yazışılır
  let miniChatEl = null, miniTimer = null;
  function miniChat(peer, anchor) {
    if (miniChatEl && miniChatEl.dataset.uid === String(peer.id)) { miniChatEl.remove(); miniChatEl = null; clearInterval(miniTimer); return; }
    miniChatEl?.remove(); clearInterval(miniTimer);
    const me = ctx.user.id;
    const list = h('div', { class: 'mc-list' });
    const inp = h('textarea', { class: 'mc-inp', rows: 1, placeholder: 'Mesaj yazın…' });
    const sendBtn = h('button', { class: 'mc-send', type: 'button', title: 'Gönder' }, svgIcon(icons.send));
    let last = 0;
    const bubble = m => h('div', { class: `mc-msg ${m.from_id === me ? 'me' : ''}` }, h('span', null, m.body || (m.file_name || '📎 Dosya')));
    const addMsgs = ms => { const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 30; ms.forEach(m => { list.append(bubble(m)); last = Math.max(last, m.id); }); if (atBottom) list.scrollTop = list.scrollHeight; };
    const load = async () => { try { const r = await api.get(`/api/chat/${peer.id}`); const arr = r.items || []; clear(list, arr.map(bubble)); last = arr.length ? arr[arr.length - 1].id : 0; list.scrollTop = list.scrollHeight; } catch { clear(list, h('div', { class: 'db-none' }, 'Mesajlar yüklenemedi')); } };
    const poll = async () => { try { const r = await api.get(`/api/chat/${peer.id}?after=${last}`); if (r.items && r.items.length) addMsgs(r.items); } catch { /* */ } };
    const send = async () => { const v = inp.value.trim(); if (!v) return; inp.value = ''; inp.style.height = 'auto'; const fd = new FormData(); fd.append('body', v); try { const m = await api.post(`/api/chat/${peer.id}`, fd); addMsgs([m]); } catch (e) { toastError(e); inp.value = v; } };
    sendBtn.addEventListener('click', send);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
    inp.addEventListener('input', () => { inp.style.height = 'auto'; inp.style.height = Math.min(inp.scrollHeight, 90) + 'px'; });
    const close = h('button', { class: 'mc-x', type: 'button', title: 'Kapat' }, '×');
    close.addEventListener('click', () => { miniChatEl.remove(); miniChatEl = null; clearInterval(miniTimer); });
    const openFull = h('button', { class: 'mc-full', type: 'button', title: 'Tam ekran Mesajlar' }, '⤢');
    openFull.addEventListener('click', () => { location.hash = `#/messages/u${peer.id}`; });
    miniChatEl = h('div', { class: 'mini-chat', 'data-uid': String(peer.id) },
      h('div', { class: 'mc-head' }, dbAvatar(peer.full_name, peer.photo), h('b', { class: 'grow' }, peer.full_name), openFull, close),
      list, h('div', { class: 'mc-foot' }, inp, sendBtn));
    document.body.append(miniChatEl);
    load(); miniTimer = setInterval(poll, 3000);
    setTimeout(() => inp.focus(), 50);
  }
  onLeave(() => { miniChatEl?.remove(); clearInterval(miniTimer); });

  // Görevdeki personel: üstte başlık şeridinde plaka, gövdede solda personel(ler) + sağda ileri sayan sayaç, altta "dışarıda" şeridi
  function dbOnDuty(body, items) {
    if (!items.length) { clear(body, h('div', { class: 'db-none' }, 'Şu an görevde personel yok')); return; }
    const pad = n => String(n).padStart(2, '0');
    const elapsed = since => {
      const ms = Date.now() - new Date(since).getTime();
      if (isNaN(ms) || ms < 0) return '00:00:00';
      const s = Math.floor(ms / 1000);
      return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
    };
    // Görev (araç/misyon) bazında grupla: aynı görevdeki personel tek grupta, üstte plaka, sağda tek sayaç
    const groups = new Map();
    items.forEach(x => {
      if (!groups.has(x.id)) groups.set(x.id, { plate: x.vehicle_plate, since: x.depart_at, people: [] });
      groups.get(x.id).people.push(x);
    });
    const clocks = [];
    // Her görev TEK SATIR: en solda araç plakası, en sağda ileri sayan DİJİTAL sayaç.
    // Satıra tıklayınca altında o görevdeki personel(ler) açılır. Satır = üst-header rengi, içi (personel) beyaz.
    const blocks = [...groups.values()].map(g => {
      const tEl = h('b', { class: 'db-duty-digital' }, elapsed(g.since));
      clocks.push({ tEl, since: g.since });
      const row = h('button', { class: 'db-duty-row', type: 'button' },
        h('span', { class: `db-duty-plate${g.plate ? '' : ' noveh'}` }, g.plate || 'Araçsız'),
        h('span', { class: 'db-duty-n' }, String(g.people.length)),
        h('span', { class: 'db-duty-caret', 'aria-hidden': 'true' }),
        tEl);
      const people = h('div', { class: 'db-duty-people' }, g.people.map(p => h('div', { class: 'db-dutyp' },
        dbAvatar(p.name, p.photo, 'lg'), h('b', null, p.name))));
      const item = h('div', { class: 'db-duty-item' }, row, people);
      row.addEventListener('click', () => item.classList.toggle('open'));
      return item;
    });
    clear(body, h('div', { class: 'db-duty-rows' }, blocks));
    const tick = () => clocks.forEach(c => { c.tEl.textContent = elapsed(c.since); });
    timers.push(setInterval(tick, 1000));
  }

  function dbAlarms(body, acts) {
    const render = () => {
      const alarms = getAlarms().sort((a, b) => (a.time || '').localeCompare(b.time || ''));
      setActs(acts, h('button', { class: 'db-head-btn', type: 'button', onclick: () => alarmForm(null, render) }, '＋ Yeni alarm'));
      const dayLbl = ds => (!ds || !ds.length ? 'Her gün' : (ds.length === 7 ? 'Her gün' : DAYS.filter(([d]) => ds.includes(d)).map(([, l]) => l).join(' ')));
      clear(body, alarms.length ? h('ul', { class: 'db-list db-alarmlist' }, alarms.map(a => h('li', { class: a.enabled === false ? 'off' : '' },
        h('button', { class: 'alarm-toggle', type: 'button', title: a.enabled === false ? 'Aç' : 'Kapat',
          onclick: () => { a.enabled = a.enabled === false; const all = getAlarms().map(x => x.id === a.id ? a : x); saveAlarms(all); render(); } }, a.enabled === false ? '○' : '●'),
        h('button', { class: 'alarm-main', type: 'button', onclick: () => alarmForm(a, render) },
          h('b', null, a.time), h('span', { class: 'small muted' }, `${dayLbl(a.days)}${a.label ? ' · ' + a.label : ''}`)),
        h('button', { class: 'alarm-del', type: 'button', title: 'Sil', onclick: () => { saveAlarms(getAlarms().filter(x => x.id !== a.id)); render(); } }, '×'))))
        : h('div', { class: 'db-none' }, 'Alarm yok. “Yeni alarm” ekleyin.'));
    };
    render();
    const onCh = () => { if (body.isConnected) render(); else window.removeEventListener('caymaz:alarms-changed', onCh); };
    window.addEventListener('caymaz:alarms-changed', onCh);
  }

  // Spotify kutucuğu: anlık çalan parça (albüm kapağı, başlık, sanatçı, ilerleme) + oynatma kontrolü + çalma listeleri + arama.
  // Bağlı değilse “Spotify’a bağlan” önerisi. Anlık çalan ~5 sn'de bir yenilenir (görünürken; timers ile temizlenir).
  function dbSpotify(body, acts, d) {
    if (acts) clear(acts);
    if (!d.connected) {
      clear(body, h('div', { class: 'db-none db-sp-connect' },
        h('div', { class: 'db-sp-logo' }, SP_LOGO()),
        h('p', null, d.configured ? 'Spotify hesabınızı bağlayın; çalan parça ve kontroller burada görünür.'
          : 'Spotify bu sunucuda henüz ayarlanmadı.'),
        d.configured ? h('a', { class: 'btn primary sm', href: '#/settings/social' }, 'Spotify’a bağlan')
          : h('span', { class: 'small muted' }, 'Yönetici: Program Ayarları › Entegrasyonlar › Spotify')));
      return;
    }
    const art = h('img', { class: 'db-sp-art', alt: '', referrerpolicy: 'no-referrer' });
    const title = h('b', { class: 'db-sp-title' }, '—');
    const artist = h('span', { class: 'db-sp-artist muted' }, '');
    const bar = h('i', { class: 'db-sp-bar-fill' });
    const curT = h('span', { class: 'db-sp-t' }, '0:00');
    const durT = h('span', { class: 'db-sp-t' }, '0:00');
    const eq = h('div', { class: 'db-sp-eq' }, h('i'), h('i'), h('i'), h('i'));
    const fmt = ms => { const s = Math.max(0, Math.round((ms || 0) / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
    const playBtn = h('button', { class: 'db-sp-btn db-sp-play', type: 'button', title: 'Oynat / Duraklat' }, SP_PLAY());
    const act = async (fn) => { try { await fn(); setTimeout(poll, 350); } catch (e) { toastError(e); } };
    const prevBtn = h('button', { class: 'db-sp-btn', type: 'button', title: 'Önceki', onclick: () => act(() => api.post('/api/spotify/previous')) }, SP_ICON('M7 6v12M19 6l-9 6 9 6V6z'));
    const nextBtn = h('button', { class: 'db-sp-btn', type: 'button', title: 'Sonraki', onclick: () => act(() => api.post('/api/spotify/next')) }, SP_ICON('M17 6v12M5 6l9 6-9 6V6z'));
    let playing = false;
    playBtn.addEventListener('click', () => act(() => api.post(playing ? '/api/spotify/pause' : '/api/spotify/play')));
    const npWrap = h('div', { class: 'db-sp-np' },
      h('div', { class: 'db-sp-artwrap' }, art, eq),
      h('div', { class: 'db-sp-meta' }, title, artist,
        h('div', { class: 'db-sp-bar' }, curT, h('span', { class: 'db-sp-bar-track' }, bar), durT),
        h('div', { class: 'db-sp-ctrl' }, prevBtn, playBtn, nextBtn)));
    const note = h('div', { class: 'db-sp-note muted small' });
    // Çalma listeleri + arama (açılır-kapanır bölüm)
    const searchInp = h('input', { class: 'input sm', type: 'search', placeholder: 'Parça ya da çalma listesi ara…' });
    const results = h('div', { class: 'db-sp-results' });
    const playUri = uri => act(() => api.post('/api/spotify/play', { uri }));
    const rowTrack = tr => h('button', { class: 'db-sp-row', type: 'button', title: 'Çal', onclick: () => playUri(tr.uri) },
      tr.art ? h('img', { class: 'db-sp-row-art', src: tr.art, alt: '', referrerpolicy: 'no-referrer' }) : h('span', { class: 'db-sp-row-art ph' }, '♪'),
      h('span', { class: 'db-sp-row-main' }, h('b', null, tr.title || '—'), h('small', null, tr.artists || tr.owner || '')));
    const rowPl = pl => h('button', { class: 'db-sp-row', type: 'button', title: 'Çal', onclick: () => playUri(pl.uri) },
      pl.art ? h('img', { class: 'db-sp-row-art', src: pl.art, alt: '', referrerpolicy: 'no-referrer' }) : h('span', { class: 'db-sp-row-art ph' }, '≡'),
      h('span', { class: 'db-sp-row-main' }, h('b', null, pl.name || '—'), h('small', null, [pl.owner, pl.tracks != null ? `${pl.tracks} parça` : null].filter(Boolean).join(' · '))));
    let searchTimer;
    const showPlaylists = async () => {
      try { const r = await api.get('/api/spotify/playlists'); clear(results, r.items?.length ? r.items.map(rowPl) : h('div', { class: 'db-none small' }, 'Çalma listesi yok')); }
      catch (e) { clear(results, h('div', { class: 'db-none small' }, e.message)); }
    };
    searchInp.addEventListener('input', () => {
      clearTimeout(searchTimer);
      const q = searchInp.value.trim();
      if (!q) { showPlaylists(); return; }
      searchTimer = setTimeout(async () => {
        try {
          const r = await api.get(`/api/spotify/search?q=${encodeURIComponent(q)}`);
          const items = [...(r.tracks || []).map(rowTrack), ...(r.playlists || []).map(rowPl)];
          clear(results, items.length ? items : h('div', { class: 'db-none small' }, 'Sonuç yok'));
        } catch (e) { clear(results, h('div', { class: 'db-none small' }, e.message)); }
      }, 350);
    });
    clear(body, h('div', { class: 'db-sp' }, npWrap, note,
      h('div', { class: 'db-sp-search' }, searchInp), results));
    showPlaylists();
    const poll = async () => {
      let np;
      try { np = await api.get('/api/spotify/now-playing'); note.textContent = ''; }
      catch (e) { note.textContent = e.message || 'Spotify bilgisi alınamadı'; return; }
      if (!np || !np.playing) {
        playing = false; npWrap.classList.remove('on');
        title.textContent = 'Şu an bir şey çalmıyor'; artist.textContent = ''; art.removeAttribute('src');
        clear(playBtn, SP_PLAY()); bar.style.width = '0%'; curT.textContent = '0:00'; durT.textContent = '0:00';
        note.textContent = 'Spotify uygulamasını (telefon / bilgisayar / web) açıp bir şey çalın.';
        return;
      }
      playing = !!np.is_playing;
      npWrap.classList.toggle('on', playing);
      title.textContent = np.title || '—'; artist.textContent = np.artists || '';
      if (np.art) art.src = np.art; else art.removeAttribute('src');
      clear(playBtn, playing ? SP_PAUSE() : SP_PLAY());
      const pct = np.duration_ms ? Math.min(100, 100 * (np.progress_ms || 0) / np.duration_ms) : 0;
      bar.style.width = `${pct}%`; curT.textContent = fmt(np.progress_ms); durT.textContent = fmt(np.duration_ms);
    };
    poll();
    timers.push(setInterval(poll, 5000));
  }

  async function dbNotes(body, acts) {
    const addBtn = h('button', { class: 'db-head-btn', type: 'button', title: 'Yeni not' }, '＋ Yeni not');
    setActs(acts, addBtn);
    const grid = h('div', { class: 'db-note-grid' });
    clear(body, grid);
    const load = async () => {
      let notes = [];
      try { notes = await api.get('/api/notes'); } catch { clear(grid, h('div', { class: 'db-none' }, 'Notlar yüklenemedi')); return; }
      clear(grid, notes.length ? notes.map(n => noteCard(n, { onDelete: load, onChange: () => {} })) : h('div', { class: 'db-none' }, 'Not yok. “Yeni not” ekleyin.'));
    };
    addBtn.onclick = async () => { try { await api.post('/api/notes', { body: '', color: 'yellow' }); await load(); setTimeout(() => grid.querySelector('.note-txt')?.focus(), 30); } catch (e) { toastError(e); } };
    await load();
  }

  function worldClock(body, it) {
    const cities = it.o?.cities || [];
    if (!cities.length) return clear(body, h('div', { class: 'db-none' }, h('span', null, 'Şehir ekleyin: '),
      h('button', { class: 'link', type: 'button', onclick: () => settings(it) }, 'Ayarlar ⚙')));
    const cells = cities.map(c => {
      const tEl = h('b', { class: 'db-wc-time' });
      const dEl = h('small', { class: 'db-wc-sub' });
      return { c, el: h('div', { class: 'db-wc-cell' }, h('span', { class: 'db-wc-name' }, c.name), tEl, dEl), tEl, dEl };
    });
    const tick = () => {
      const now = new Date();
      for (const x of cells) {
        try {
          x.tEl.textContent = now.toLocaleTimeString('tr-TR', { timeZone: x.c.tz, hour: '2-digit', minute: '2-digit' });
          x.dEl.textContent = now.toLocaleDateString('tr-TR', { timeZone: x.c.tz, weekday: 'short', day: 'numeric', month: 'short' });
        } catch { x.tEl.textContent = '—'; x.dEl.textContent = x.c.tz; }
      }
    };
    tick(); timers.push(setInterval(tick, 1000));
    clear(body, h('div', { class: 'db-wc' }, cells.map(x => x.el)));
  }

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
    h('div', null, h('h1', null, `${greet}, ${ctx.user.full_name.split(' ')[0]}`), h('p', { class: 'muted' }, 'Kişisel panonuz · kutucukları sürükleyip boyutlandırabilirsiniz')),
    h('div', { style: { display: 'flex', gap: '8px' } }, addBtn, presetsBtn, editBtn)), gridEl);
  build();
  refreshTimer = setInterval(async () => { if (!editing && !document.querySelector('.modal-back')) { await loadData().catch(() => {}); refill(); } }, 60000);
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
