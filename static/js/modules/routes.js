// Rotalar — Dron Yönetimi › Rotalar sekmesi (#/field/routes[/id]). drone.js `routes` sayfasında bu modülü dinamik yükler:
//   import('./routes.js').then(mod => mod.render(view, ctx, m, head, params))
// Yerleşim: solda 320 px dar sütun, altlı üstlü üç panel (Rota Merkezleri / Rotalar / seçili rotanın Adımları); sağda ekranı
// kaplayan Cesium harita (replay3d.js loadCesium/createViewer). Rota seçilince ya da yeni rota eklenince harita DÜZENLEME
// modunda açılır: haritaya tıklayınca nokta eklenir, nokta sol basılı sürüklenerek taşınır, sağ tık noktayı siler; sağ üstteki
// "Kaydet" tüm ara noktaları PUT ile yazar ve düzenleme modundan çıkar. GÖKTUNGU static/ops/js/rotalar.js mantığı (tikKur,
// sarukleBirak, rotaCiz, noktaPopupAc, duzenlemeBaslat/Bitir) HEPGO ESM kalıbında yeniden yazıldı; GÖKTUNGU dosyalarına dokunulmaz.
// REST: GET/POST/PUT/DELETE /api/drone/centers[/id], /api/drone/routes[/id] (waypoints: lat, lon, alt, action, hold_s, note),
// GET /api/drone/routes/{id}/mission. Stil: static/css/routes.css (bu modül <link> ile bir kez ekler).
import { api } from '../api.js';
import { clear, confirmDialog, field, h, modal, onLeave, toast, toastError, t as tr } from '../ui.js';
import { createViewer, loadCesium } from './replay3d.js';

const CSS_HREF = '/static/css/routes.css';
// Eylem renkleri: önizleme ve GÖKTUNGU ile aynı dil (yeşil kalkış, mavi ara nokta, mor bekleme, turuncu eve dön, kırmızı iniş)
const COLORS = { takeoff: '#22c55e', waypoint: '#2563eb', loiter: '#8b5cf6', rtl: '#f59e0b', land: '#ef4444' };
const SEL_LINE = '#ffcc33';      // seçili rota çizgisi (sarı)
const CENTER_PIN = '#0ea5e9';    // merkez işaretçisi
const EARTH_R = 6371000;

const num = (v, d = 0) => (v == null || v === '' || Number.isNaN(Number(v)) ? null : Number(Number(v).toFixed(d)));
const inp = (value, attrs = {}) => h('input', { class: 'input', value: value ?? '', ...attrs });
const sel = (options, value, { empty } = {}) => h('select', { class: 'input' },
  empty != null ? h('option', { value: '' }, empty) : null,
  options.map(([k, label]) => h('option', { value: k, selected: String(k) === String(value ?? '') }, label)));
const check = (label, on) => { const cb = h('input', { type: 'checkbox', checked: !!on }); return [h('label', { class: 'check' }, cb, label), cb]; };
const copyWps = list => (list || []).map(w => ({ lat: w.lat, lon: w.lon, alt: w.alt ?? null, action: w.action || 'waypoint', hold_s: w.hold_s ?? null, note: w.note || null }));
const haversine = (a, b) => {
  const p1 = a.lat * Math.PI / 180, p2 = b.lat * Math.PI / 180, dp = p2 - p1, dl = (b.lon - a.lon) * Math.PI / 180;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.min(1, Math.sqrt(x)));
};
const copy = async (txt, what = 'Kopyalandı') => { try { await navigator.clipboard.writeText(txt); toast(what); } catch { toast('Kopyalanamadı; metni elle seçin', 'err'); } };

// Stil dosyası bir kez eklenir (app.js'in ?v= sürüm eki ile önbellek kırma)
function ensureCss() {
  if (document.head.querySelector('link[data-routes-css]')) return;
  const ver = (document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/) || [])[1] || '';
  document.head.append(h('link', { rel: 'stylesheet', href: `${CSS_HREF}${ver ? `?v=${encodeURIComponent(ver)}` : ''}`, 'data-routes-css': '1' }));
}

// Daire işaretçi (billboard resmi): eylem rengi dolgu, beyaz kenar, ortada metin (nokta numarası ya da "H"); vurgulu nokta beyaz halkalı.
// Retina için 2x çizilir, billboard width/height ile gerçek boyuta indirilir.
const pinCache = new Map();
function pin(color, text, size = 26, ring = false) {
  const key = `${color}|${text}|${size}|${ring}`;
  if (pinCache.has(key)) return pinCache.get(key);
  const s = size + (ring ? 10 : 0);
  const c = document.createElement('canvas');
  c.width = c.height = s * 2;
  const g = c.getContext('2d');
  g.scale(2, 2);
  const cx = s / 2;
  if (ring) { g.beginPath(); g.arc(cx, cx, size / 2 + 3.5, 0, Math.PI * 2); g.lineWidth = 2.5; g.strokeStyle = 'rgba(255,255,255,.95)'; g.stroke(); }
  g.beginPath(); g.arc(cx, cx, size / 2 - 1.5, 0, Math.PI * 2); g.fillStyle = color; g.fill(); g.lineWidth = 2; g.strokeStyle = '#ffffff'; g.stroke();
  g.fillStyle = '#ffffff'; g.font = `700 ${String(text).length > 2 ? 10 : 12}px sans-serif`; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(String(text), cx, cx + 0.5);
  const out = { url: c.toDataURL(), size: s };
  pinCache.set(key, out);
  return out;
}

export async function render(view, ctx, m, head, params) {
  ensureCss();
  // ---------- durum ----------
  const S = {
    centers: [], routes: [], detail: {},   // detail[id] = GET /routes/{id} (waypoints dahil; updated_at ile tazelenir)
    selCenter: null,                        // merkez filtresi (null = tümü)
    sel: null, wps: [],                     // seçili rota ve düzenlenen ara nokta kopyası
    editing: false, dirty: false, hi: -1,   // düzenleme modu, kaydedilmemiş değişiklik, vurgulu nokta
    pick: null,                             // { c, draft } → merkez konumu haritadan seçiliyor
  };
  let Cesium = null, viewer = null, destroyed = false;
  let baseEnts = [], selEnts = [], ptEnts = [];   // harita varlıkları: merkezler + diğer rotalar / seçili rota / nokta başına { pin, stick }
  let C = null;                                   // Cesium renk sabitleri (kütüphane yüklenince)

  // ---------- iskelet ----------
  const centerCount = h('span', { class: 'rt-count' }), routeCount = h('span', { class: 'rt-count' }), stepCount = h('span', { class: 'rt-count' });
  const centerList = h('div', { class: 'rt-list' }), routeList = h('div', { class: 'rt-list' }), stepList = h('div', { class: 'rt-list' });
  const routeSearch = h('input', { class: 'input rt-search', type: 'search', placeholder: 'Rota ara…' });
  const stepFoot = h('div', { class: 'rt-foot small muted' });
  const stepTitle = h('h3', null, 'Adımlar');
  const iconBtn = (txt, title, fn, disabled = false) => h('button', { class: 'btn sm ghost rt-ib', type: 'button', title, disabled, onclick: fn }, txt);
  const panel = (titleEl, countEl, actions, ...body) => h('div', { class: 'card rt-panel' },
    h('div', { class: 'rt-panel-head' }, titleEl, countEl, h('span', { class: 'spacer' }), actions), ...body);
  const holder = h('div', { class: 'rt-map-holder' });
  const tools = h('div', { class: 'rt-tools' });
  const mapBtns = h('div', { class: 'rt-mapbtns' });
  const badge = h('div', { class: 'rt-badge', hidden: true });
  const msg = h('div', { class: 'rt-msg' }, '3B harita yükleniyor…');
  const pop = h('div', { class: 'rt-pop', hidden: true });
  const mapBox = h('div', { class: 'rt-map' }, holder, msg, mapBtns, tools, badge, pop);
  const side = h('div', { class: 'rt-side' },
    panel(h('h3', null, 'Rota Merkezleri'), centerCount, iconBtn('＋', 'Yeni merkez', () => centerForm(null, null)), centerList),
    panel(h('h3', null, 'Rotalar'), routeCount, iconBtn('＋', 'Yeni rota', () => routeForm(null)), routeSearch, routeList),
    panel(stepTitle, stepCount, h('span', { class: 'rt-acts on' },
      iconBtn('＋', 'Merkez konumunu nokta olarak ekle', () => addCenterPoint('waypoint')),
      iconBtn('⤴', 'Eve dön (RTL) noktası ekle', () => addCenterPoint('rtl'))), stepList, stepFoot));
  const wrap = h('div', { class: 'rt-wrap' }, side, mapBox);
  clear(view, head('Rotalar · rota merkezleri, ara noktalar ve harita üzerinde rota tasarımı'), wrap);

  // Harita yüksekliği = görünür alan (kaydırma kutusunun kalan yüksekliği); telefonda CSS tek sütuna geçer, yükseklik sabitlenmez
  const fit = () => {
    if (!wrap.isConnected) return;
    if (window.matchMedia('(max-width: 960px)').matches) { wrap.style.height = ''; return; }
    const sc = view.closest('.scroller');
    const scRect = sc ? sc.getBoundingClientRect() : { top: 0, height: window.innerHeight };
    const off = wrap.getBoundingClientRect().top - scRect.top + (sc ? sc.scrollTop : 0);
    wrap.style.height = `${Math.max(480, Math.round(scRect.height - off - 20))}px`;
  };
  fit();
  window.addEventListener('resize', fit);
  const ro = window.ResizeObserver ? new ResizeObserver(() => fit()) : null;
  ro?.observe(view.closest('.scroller') || document.body);
  onLeave(() => { destroyed = true; window.removeEventListener('resize', fit); ro?.disconnect(); });

  // ---------- veri ----------
  const ensureDetail = async (id, force = false) => {
    const r = S.routes.find(x => x.id === id);
    const d = S.detail[id];
    if (!force && d && (!r || d.updated_at === r.updated_at)) return d;
    S.detail[id] = await api.get(`/api/drone/routes/${id}`);
    return S.detail[id];
  };
  const reload = async () => {
    const [centers, routes] = await Promise.all([api.get('/api/drone/centers'), api.get('/api/drone/routes')]);
    if (destroyed) return;
    S.centers = centers; S.routes = routes;
    const ids = new Set(routes.map(r => r.id));
    for (const id of Object.keys(S.detail)) if (!ids.has(Number(id))) delete S.detail[id];
    await Promise.all(routes.map(r => ensureDetail(r.id)));   // tüm rotalar haritada soluk çizilir; önbellek updated_at ile tazelenir
    if (destroyed) return;
    if (S.sel) {
      const d = S.detail[S.sel.id];
      if (!d) { S.sel = null; S.wps = []; S.editing = false; S.dirty = false; S.hi = -1; closePop(); }
      else { S.sel = d; if (!S.dirty) S.wps = copyWps(d.waypoints); }
    }
    if (S.selCenter != null && !centers.some(c => c.id === S.selCenter)) S.selCenter = null;
    drawAll();
  };

  // ---------- sol paneller ----------
  const centerOf = r => (r?.center_id != null ? S.centers.find(c => c.id === r.center_id) : null);
  const drawCenters = () => {
    centerCount.textContent = S.centers.length;
    clear(centerList,
      h('div', { class: `rt-row ${S.selCenter == null ? 'on' : ''}`, onclick: () => { S.selCenter = null; drawCenters(); drawRoutes(); drawBase(); } },
        h('span', { class: 'rt-ic all' }, 'T'),
        h('div', { class: 'grow' }, h('b', null, 'Tüm merkezler'), h('div', { class: 'small muted' }, tr('{n} rota', { n: S.routes.length })))),
      S.centers.map(c => h('div', { class: `rt-row ${S.selCenter === c.id ? 'on' : ''} ${c.active ? '' : 'off'}`, onclick: () => selectCenter(c) },
        h('span', { class: 'rt-ic' }, 'H'),
        h('div', { class: 'grow' }, h('b', null, c.name),
          h('div', { class: 'small muted mono' }, `${Number(c.lat).toFixed(5)}, ${Number(c.lon).toFixed(5)}${c.alt != null ? ` · ${c.alt} m` : ''}`)),
        h('span', { class: 'badge blue', title: 'Rota sayısı' }, c.route_count),
        h('span', { class: 'rt-acts' },
          iconBtn('✎', 'Düzenle', e => { e.stopPropagation(); centerForm(c, null); }),
          iconBtn('✕', 'Sil', async e => {
            e.stopPropagation();
            if (!await confirmDialog('Merkezi sil', tr('{name} silinsin mi? Rotalar kalır, merkez bağı kalkar.', { name: c.name }), { okLabel: 'Sil', danger: true })) return;
            await api.del(`/api/drone/centers/${c.id}`); toast('Merkez silindi'); await reload();
          })))),
      S.centers.length ? null : h('div', { class: 'rt-empty' }, 'Merkez yok. Merkez, rotaların referans noktasıdır (pist / kalkış alanı); "+" ile ekleyin.'));
  };
  const visibleRoutes = () => {
    const q = routeSearch.value.trim().toLocaleLowerCase('tr');
    return S.routes.filter(r => (S.selCenter == null || r.center_id === S.selCenter) && (!q || `${r.name} ${r.center_name || ''} ${r.kind_text || ''}`.toLocaleLowerCase('tr').includes(q)));
  };
  const drawRoutes = () => {
    const list = visibleRoutes();
    routeCount.textContent = S.selCenter == null && !routeSearch.value ? S.routes.length : `${list.length}/${S.routes.length}`;
    clear(routeList, list.map(r => h('div', { class: `rt-row ${S.sel?.id === r.id ? 'on' : ''} ${r.active ? '' : 'off'}`, onclick: () => selectRoute(r.id).catch(toastError) },
      h('span', { class: `rt-ic r ${S.sel?.id === r.id ? 'sel' : ''}`, title: 'Nokta sayısı' }, S.sel?.id === r.id ? S.wps.length : r.wp_count),
      h('div', { class: 'grow' }, h('b', null, r.name),
        h('div', { class: 'small muted' }, [r.center_name || 'merkez yok', r.kind_text, r.cruise_alt != null ? `${r.cruise_alt} m` : null].filter(Boolean).join(' · '))),
      r.active ? null : h('span', { class: 'badge gray' }, 'Pasif'),
      h('span', { class: 'rt-acts' },
        iconBtn('✎', 'Rota bilgileri', e => { e.stopPropagation(); routeForm(r); }),
        iconBtn('✕', 'Sil', async e => {
          e.stopPropagation();
          if (!await confirmDialog('Rotayı sil', tr('{name} silinsin mi?', { name: r.name }), { okLabel: 'Sil', danger: true })) return;
          await api.del(`/api/drone/routes/${r.id}`); toast('Rota silindi');
          if (S.sel?.id === r.id) { S.sel = null; S.wps = []; S.editing = false; S.dirty = false; S.hi = -1; closePop(); }
          await reload();
        })))),
      list.length ? null : h('div', { class: 'rt-empty' }, S.routes.length ? 'Filtreye uyan rota yok' : 'Henüz rota yok. "+" ile rota ekleyin; harita düzenleme modunda açılır.'));
  };
  const altText = w => (w.alt != null ? `${w.alt} m` : (S.sel?.cruise_alt != null ? tr('seyir {n} m', { n: S.sel.cruise_alt }) : 'seyir'));
  const drawSteps = () => {
    stepTitle.textContent = S.sel ? `Adımlar · ${S.sel.name}` : 'Adımlar';
    stepCount.textContent = S.sel ? S.wps.length : '';
    side.querySelectorAll('.rt-acts.on .rt-ib').forEach(b => { b.disabled = !S.editing; });
    if (!S.sel) { clear(stepList, h('div', { class: 'rt-empty' }, 'Listeden rota seçin; harita düzenleme modunda açılır.')); stepFoot.textContent = ''; return; }
    clear(stepList, S.wps.map((w, i) => h('div', { class: `rt-step ${S.hi === i ? 'hi' : ''}`, onclick: () => highlight(i) },
      h('span', { class: 'rt-no', style: { background: COLORS[w.action] || COLORS.waypoint } }, i + 1),
      h('div', { class: 'grow' }, h('b', null, m.wp_actions?.[w.action] || w.action),
        h('div', { class: 'small muted' }, [altText(w), w.hold_s ? `${w.hold_s} sn` : null, w.note].filter(Boolean).join(' · '))),
      h('span', { class: 'rt-acts' },
        iconBtn('↑', 'Yukarı', e => { e.stopPropagation(); moveWp(i, -1); }, !S.editing || i === 0),
        iconBtn('↓', 'Aşağı', e => { e.stopPropagation(); moveWp(i, 1); }, !S.editing || i === S.wps.length - 1),
        iconBtn('✎', 'Düzenle', e => { e.stopPropagation(); highlight(i); openPop(i); }, !S.editing),
        iconBtn('✕', 'Sil', e => { e.stopPropagation(); removeWp(i); }, !S.editing)))),
      S.wps.length ? null : h('div', { class: 'rt-empty' }, S.editing ? 'Haritaya tıklayarak nokta ekleyin.' : 'Ara nokta yok. "Düzenle" ile haritadan ekleyin.'));
    let total = 0;
    for (let i = 1; i < S.wps.length; i++) total += haversine(S.wps[i - 1], S.wps[i]);
    if (S.sel.kind === 'loop' && S.wps.length > 2) total += haversine(S.wps[S.wps.length - 1], S.wps[0]);
    const spd = num(S.sel.cruise_speed, 1);
    stepFoot.textContent = `${S.wps.length} nokta · ${(total / 1000).toFixed(2)} km${spd ? ` · ~${Math.round(total / spd / 60)} dk @ ${spd} m/s` : ''}`;
    if (S.hi >= 0) stepList.children[S.hi]?.scrollIntoView?.({ block: 'nearest' });
  };
  routeSearch.addEventListener('input', drawRoutes);

  // ---------- harita üstü araçlar ----------
  const drawTools = () => {
    clear(tools,
      S.editing
        ? [h('button', { class: 'btn sm primary', type: 'button', onclick: () => save().catch(toastError) }, 'Kaydet'),
          h('button', { class: 'btn sm', type: 'button', onclick: () => cancelEdit().catch(toastError) }, 'Vazgeç')]
        : [S.sel ? h('button', { class: 'btn sm primary', type: 'button', onclick: startEdit }, 'Düzenle') : null,
          S.sel ? h('button', { class: 'btn sm', type: 'button', onclick: () => missionModal().catch(toastError) }, 'MAVLink görevi') : null,
          S.sel && m.can?.command ? h('button', { class: 'btn sm', type: 'button', onclick: () => uploadModal().catch(toastError) }, 'Drona yükle') : null],
      S.dirty ? h('span', { class: 'rt-dirty' }, 'Kaydedilmedi') : null);
    clear(mapBtns,
      h('button', { class: 'btn sm', type: 'button', title: S.sel ? 'Rotaya sığdır' : 'Tümünü göster', onclick: () => (S.sel ? fitToRoute() : fitAll()) }, '⤢'),
      h('button', { class: 'btn sm', type: 'button', title: 'Merkeze git', onclick: () => { const c = centerOf(S.sel) || S.centers.find(x => x.id === S.selCenter) || S.centers[0]; if (c) flyTo(c.lat, c.lon); else toast('Merkez yok'); } }, 'H'));
  };
  const drawBadge = () => {
    mapBox.classList.toggle('editing', S.editing);
    mapBox.classList.toggle('picking', !!S.pick);
    if (S.pick) {
      badge.hidden = false;
      clear(badge, 'Merkez konumu için haritaya tıklayın', h('button', { class: 'btn sm', type: 'button', onclick: cancelPick }, 'Vazgeç'));
    } else if (S.editing) {
      badge.hidden = false;
      clear(badge, 'DÜZENLEME · tıkla: nokta ekle · sürükle: taşı · sağ tık: sil');
    } else badge.hidden = true;
  };
  const drawAll = () => { drawCenters(); drawRoutes(); drawSteps(); drawTools(); drawBadge(); drawBase(); drawSel(); };

  // ---------- seçim / düzenleme modu (duzenlemeBaslat / duzenlemeBitir karşılığı) ----------
  const markDirty = () => { S.dirty = true; drawTools(); };
  // Kaydedilmemiş değişiklik varken başka işe geçiş: Kaydet / Kaydetme / Vazgeç
  const leaveEditing = () => new Promise(resolve => {
    if (!S.editing || !S.dirty) return resolve(true);
    let done = false;
    const fin = v => { done = true; resolve(v); };
    modal({
      title: 'Kaydedilmemiş değişiklik',
      body: h('p', { style: { margin: 0 } }, tr('{name} rotasında kaydedilmemiş nokta değişiklikleri var.', { name: S.sel.name })),
      onClose: () => { if (!done) resolve(false); },
      actions: [{ label: 'Vazgeç' }, { label: 'Kaydetme', class: 'danger', onClick: () => fin(true) },
        { label: 'Kaydet', class: 'primary', onClick: async () => { await save(); fin(true); } }],
    });
  });
  const selectRoute = async (id, { edit = true } = {}) => {
    if (S.sel?.id === id) { if (edit && !S.editing) startEdit(); return; }
    if (!await leaveEditing()) return;
    const d = await ensureDetail(id);
    S.sel = d; S.wps = copyWps(d.waypoints); S.hi = -1; S.dirty = false; S.editing = edit;
    closePop();
    drawRoutes(); drawSteps(); drawTools(); drawBadge(); drawBase(); drawSel();
    fitToRoute();
  };
  const selectCenter = c => {
    S.selCenter = S.selCenter === c.id ? null : c.id;
    drawCenters(); drawRoutes(); drawBase();
    if (S.selCenter != null) flyTo(c.lat, c.lon);
  };
  const startEdit = () => { if (!S.sel) return; S.editing = true; drawSteps(); drawTools(); drawBadge(); };
  const save = async () => {
    const r = S.sel;
    if (!r) return;
    if (S.wps.some(w => w.lat == null || w.lon == null)) throw new Error('Her ara noktanın enlem ve boylamı dolu olmalı');
    const body = {
      name: r.name, center_id: r.center_id ?? null, kind: r.kind, cruise_alt: r.cruise_alt ?? null, cruise_speed: r.cruise_speed ?? null, note: r.note ?? null, active: !!r.active,
      waypoints: S.wps.map(w => ({ lat: num(w.lat, 7), lon: num(w.lon, 7), alt: num(w.alt, 1), action: w.action, hold_s: num(w.hold_s, 1), note: w.note || null })),
    };
    await api.put(`/api/drone/routes/${r.id}`, body);
    S.dirty = false; S.editing = false; closePop();
    drawTools(); drawBadge(); drawSteps();   // anında düzenleme görünümünden çık; listeler yeniden yükleme ile tazelenir
    delete S.detail[r.id];   // kaydedilen rota yeniden okunur (updated_at saniye hassasiyetinde; önbelleğe güvenilmez)
    toast('Rota kaydedildi');
    await reload();
  };
  const cancelEdit = async () => {
    if (!S.sel) return;
    if (S.dirty && !await confirmDialog('Değişiklikleri at', 'Kaydedilmemiş nokta değişiklikleri atılsın ve rota sunucudan yeniden yüklensin mi?', { okLabel: 'Değişiklikleri at', danger: true })) return;
    S.dirty = false; S.editing = false; S.hi = -1; closePop();
    delete S.detail[S.sel.id];
    await reload();
  };

  // ---------- ara nokta işlemleri ----------
  const addPoint = (lat, lon, at) => {
    if (!S.sel) { toast('Önce bir rota seçin', 'err'); return; }
    if (!S.editing) startEdit();
    S.wps.push({ lat: num(lat, 7), lon: num(lon, 7), alt: null, action: S.wps.length ? 'waypoint' : 'takeoff', hold_s: null, note: null });
    S.hi = S.wps.length - 1; S.dirty = true;
    drawSel(); drawSteps(); drawTools(); drawRoutes();
    if (at) openPop(S.hi, at);
  };
  const addCenterPoint = action => {
    if (!S.sel || !S.editing) return;
    const c = centerOf(S.sel);
    if (!c) return toast('Rotanın merkezi yok; rota bilgilerinden merkez seçin', 'err');
    S.wps.push({ lat: c.lat, lon: c.lon, alt: null, action, hold_s: null, note: action === 'rtl' ? null : 'Merkez' });
    S.hi = S.wps.length - 1; S.dirty = true;
    drawSel(); drawSteps(); drawTools(); drawRoutes();
  };
  const removeWp = i => {
    if (!S.editing || !S.wps[i]) return;
    S.wps.splice(i, 1);
    S.hi = Math.min(S.hi, S.wps.length - 1); S.dirty = true;
    closePop(); drawSel(); drawSteps(); drawTools(); drawRoutes();
  };
  const moveWp = (i, d) => {
    const j = i + d;
    if (!S.editing || !S.wps[i] || !S.wps[j]) return;
    [S.wps[i], S.wps[j]] = [S.wps[j], S.wps[i]];
    S.hi = j; S.dirty = true;
    closePop(); drawSel(); drawSteps(); drawTools();
  };
  const highlight = i => { S.hi = i; drawSel(); drawSteps(); };

  // Nokta penceresi (noktaPopupAc karşılığı): irtifa / eylem / bekleme / not; değişiklik anında haritaya işlenir
  const openPop = (i, at) => {
    const w = S.wps[i];
    if (!w || !S.editing) return;
    const alt = inp(w.alt, { type: 'number', step: 'any', placeholder: S.sel.cruise_alt != null ? `seyir ${S.sel.cruise_alt}` : 'seyir irtifası' });
    const act = sel(Object.entries(m.wp_actions || {}), w.action);
    const hold = inp(w.hold_s, { type: 'number', step: 'any', min: 0, placeholder: '0' });
    const note = inp(w.note, { maxlength: 200, placeholder: 'Not' });
    const upd = () => { w.alt = num(alt.value, 1); w.action = act.value; w.hold_s = num(hold.value, 1); w.note = note.value.trim() || null; S.dirty = true; drawSel(); drawSteps(); drawTools(); };
    [alt, act, hold, note].forEach(el => el.addEventListener('change', upd));
    clear(pop,
      h('div', { class: 'rt-pop-head' }, h('b', null, `#${i + 1}`), h('span', { class: 'mono small muted' }, `${Number(w.lat).toFixed(6)}, ${Number(w.lon).toFixed(6)}`),
        h('button', { class: 'x-btn', type: 'button', 'aria-label': 'Kapat', onclick: closePop }, '×')),
      h('div', { class: 'row' }, field('İrtifa (m, göreli)', alt), field('Eylem', act)),
      h('div', { class: 'row' }, field('Bekleme (sn)', hold), field('Not', note)),
      h('div', { class: 'rt-pop-foot' }, h('button', { class: 'btn sm danger', type: 'button', onclick: () => removeWp(i) }, 'Noktayı sil'), h('span', { class: 'spacer' }),
        h('button', { class: 'btn sm primary', type: 'button', onclick: closePop }, 'Tamam')));
    pop.hidden = false;
    const W = mapBox.clientWidth, H = mapBox.clientHeight, pw = 300, ph = pop.offsetHeight || 200;
    const [x, y] = at || [W - pw - 16, H - ph - 56];
    pop.style.left = `${Math.max(8, Math.min(x + 14, W - pw - 8))}px`;
    pop.style.top = `${Math.max(8, Math.min(y + 14, H - ph - 8))}px`;
  };
  function closePop() { pop.hidden = true; }

  // Merkez konumunu haritadan seçme modu: form değerleri saklanır, tıklanan konumla form yeniden açılır
  const startPick = (c, draft) => { S.pick = { c, draft }; closePop(); drawBadge(); };
  function cancelPick() { if (!S.pick) return; const { c, draft } = S.pick; S.pick = null; drawBadge(); centerForm(c, draft); }
  const finishPick = k => { if (!S.pick) return; const { c, draft } = S.pick; S.pick = null; drawBadge(); centerForm(c, { ...draft, lat: k.lat, lon: k.lon }); };

  // ---------- Cesium harita ----------
  const toPos = (lat, lon, alt = 0) => Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat), alt);
  const wpAlt = (w, r = S.sel) => (w.alt != null ? Number(w.alt) : r?.cruise_alt != null ? Number(r.cruise_alt) : 100);
  const removeEnts = arr => { if (viewer) for (const e of arr) viewer.entities.remove(e); arr.length = 0; };
  const labelOpts = (text, dy, origin) => ({
    text, font: '12px sans-serif', fillColor: C.white, outlineColor: C.black, outlineWidth: 3, style: Cesium.LabelStyle.FILL_AND_OUTLINE,
    pixelOffset: new Cesium.Cartesian2(0, dy), verticalOrigin: origin, disableDepthTestDistance: Number.POSITIVE_INFINITY,
  });
  // Merkezler (H işaretçi + ad) ve seçili olmayan rotalar (soluk çizgi; merkez filtresi dışındakiler daha soluk)
  function drawBase() {
    if (!viewer) return;
    removeEnts(baseEnts);
    for (const c of S.centers) {
      const p = pin(CENTER_PIN, 'H', 28);
      baseEnts.push(viewer.entities.add({
        position: toPos(c.lat, c.lon, 0),
        billboard: { image: p.url, width: p.size, height: p.size, verticalOrigin: Cesium.VerticalOrigin.CENTER, disableDepthTestDistance: Number.POSITIVE_INFINITY },
        label: labelOpts(c.name, 18, Cesium.VerticalOrigin.TOP),
      }));
    }
    for (const r of S.routes) {
      if (S.sel && r.id === S.sel.id) continue;
      const d = S.detail[r.id];
      if (!d || d.waypoints.length < 2) continue;
      const pts = d.waypoints.map(w => toPos(w.lat, w.lon, wpAlt(w, d)));
      if (r.kind === 'loop') pts.push(pts[0]);
      const dim = S.selCenter != null && r.center_id !== S.selCenter;
      baseEnts.push(viewer.entities.add({ polyline: { positions: pts, width: 2, material: dim ? C.dimmer : C.dim, arcType: Cesium.ArcType.GEODESIC } }));
    }
  }
  // Seçili rota: kalın sarı çizgi (CallbackProperty — sürüklemede kendiliğinden güncellenir), numaralı eylem renkli noktalar,
  // noktadan yere ince dikey çizgi; vurgulu nokta halkalı ve etiketli (rotaCiz karşılığı)
  function drawSel() {
    if (!viewer) return;
    removeEnts(selEnts); ptEnts = [];
    if (!S.sel) return;
    const r = S.sel;
    const positions = new Cesium.CallbackProperty(() => {
      const p = S.wps.filter(w => w.lat != null && w.lon != null).map(w => toPos(w.lat, w.lon, wpAlt(w)));
      if (r.kind === 'loop' && p.length > 2) p.push(p[0]);
      return p;
    }, false);
    const material = r.kind === 'survey' ? new Cesium.PolylineDashMaterialProperty({ color: C.sel, dashLength: 16 }) : C.sel;
    selEnts.push(viewer.entities.add({ polyline: { positions, width: 4, material, arcType: Cesium.ArcType.GEODESIC } }));
    S.wps.forEach((w, i) => { if (w.lat != null && w.lon != null) addPtEnt(i); });
  }
  function addPtEnt(i) {
    const w = S.wps[i];
    const pos = toPos(w.lat, w.lon, wpAlt(w));
    const hi = S.hi === i;
    const p = pin(COLORS[w.action] || COLORS.waypoint, i + 1, 26, hi);
    const stick = viewer.entities.add({ polyline: { positions: [toPos(w.lat, w.lon, 0), pos], width: 1.2, material: C.stick } });
    const ent = viewer.entities.add({
      id: `rtpt:${i}`, position: pos,
      billboard: { image: p.url, width: p.size, height: p.size, verticalOrigin: Cesium.VerticalOrigin.CENTER, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      label: hi ? labelOpts(`#${i + 1} · ${altText(w)} · ${m.wp_actions?.[w.action] || w.action}`, -20, Cesium.VerticalOrigin.BOTTOM) : undefined,
    });
    selEnts.push(stick, ent);
    ptEnts[i] = { ent, stick };
  }
  // Sürüklenen noktanın konumunu yerinde güncelle (tam yeniden çizim yok)
  const movePtEnt = i => {
    const w = S.wps[i], e = ptEnts[i];
    if (!e) return;
    const pos = toPos(w.lat, w.lon, wpAlt(w));
    e.ent.position = pos;
    e.stick.polyline.positions = [toPos(w.lat, w.lon, 0), pos];
  };
  // Ekran konumu → nokta indeksi (drillPick) ve → coğrafi koordinat (pickEllipsoid; arazi modeli yok)
  const pickIdx = (x, y) => {
    try {
      for (const p of viewer.scene.drillPick(new Cesium.Cartesian2(x, y), 6)) {
        const id = p?.id?.id;
        if (typeof id === 'string' && id.startsWith('rtpt:')) return Number(id.slice(5));
      }
    } catch { /* sahne hazır değil */ }
    return -1;
  };
  const toLatLon = (x, y) => {
    const cart = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(x, y), viewer.scene.globe.ellipsoid);
    if (!cart) return null;
    const c = Cesium.Cartographic.fromCartesian(cart);
    return { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) };
  };
  function flyTo(lat, lon, height = 2500) {
    if (!viewer) return;
    viewer.camera.flyTo({ destination: toPos(lat, lon, height), duration: 1.2 });
  }
  const fitPts = pts => {
    if (!viewer || !pts.length) return;
    if (pts.length === 1) return flyTo(pts[0].lat, pts[0].lon);
    const bs = Cesium.BoundingSphere.fromPoints(pts.map(p => toPos(p.lat, p.lon, 0)));
    // Neredeyse dik bakış (eğik bakışta alt kenardaki noktalar kadraj dışında kalıyordu); mesafe yarıçapın 3 katı
    viewer.camera.flyToBoundingSphere(bs, { duration: 1.2, offset: new Cesium.HeadingPitchRange(0, -Math.PI / 2.15, Math.max(bs.radius * 3, 800)) });
  };
  function fitToRoute() {
    if (!S.sel) return fitAll();
    const pts = S.wps.filter(w => w.lat != null && w.lon != null);
    if (pts.length) return fitPts(pts);
    const c = centerOf(S.sel);
    if (c) flyTo(c.lat, c.lon); else fitAll();
  }
  function fitAll() {
    if (!viewer) return;
    const pts = [...S.centers, ...Object.values(S.detail).flatMap(d => d.waypoints)].filter(p => p.lat != null && p.lon != null);
    if (pts.length) fitPts(pts);
    else viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(35.0, 39.0, 1800000), duration: 0 });   // veri yok: Türkiye genel görünümü
  }

  // Girdi (tikKur / sarukleBirak karşılığı): Cesium kamera denetimi PointerEvent dinler; nokta üstünde başlayan sol basışı
  // CAPTURE fazında, Cesium'un canvas işleyicisinden önce yakalayıp stopImmediatePropagation ile keseriz → nokta sürüklenir,
  // kamera kilitlenir. Boş alanda sol tık nokta ekler (kamera döndürme sonrası gelen click, basış konumuna göre yutulur);
  // nokta üstünde kısa basış pencereyi açar; sağ tık noktayı siler. Merkez seçme modunda tıklama formu doldurur.
  function installInput() {
    let drag = null, down = null, lastDragEnd = 0, lastHover = 0;
    const xy = e => { const r = holder.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    const stop = e => { e.preventDefault(); e.stopImmediatePropagation(); e.stopPropagation(); };
    const endDrag = () => {
      if (!drag) return;
      try { holder.releasePointerCapture(drag.pid); } catch { /* yakalama yoksa */ }
      const moved = drag.moved;
      drag = null; lastDragEnd = Date.now();
      viewer.scene.screenSpaceCameraController.enableInputs = true;
      holder.classList.remove('dragging');
      if (moved) { S.dirty = true; drawSteps(); drawTools(); }
    };
    holder.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const [x, y] = xy(e);
      down = { x, y };
      if (!S.editing || S.pick) return;
      const idx = pickIdx(x, y);
      if (idx < 0) return;
      stop(e);
      drag = { idx, pid: e.pointerId, moved: false };
      closePop();
      viewer.scene.screenSpaceCameraController.enableInputs = false;
      holder.classList.add('dragging');
      try { holder.setPointerCapture(e.pointerId); } catch { /* desteklenmiyorsa olaylar yine canvas'tan gelir */ }
    }, true);
    holder.addEventListener('pointermove', e => {
      if (!drag) {
        if (S.editing && !S.pick && Date.now() - lastHover > 80) { lastHover = Date.now(); const [x, y] = xy(e); holder.classList.toggle('over-pt', pickIdx(x, y) >= 0); }
        return;
      }
      stop(e);
      const [x, y] = xy(e);
      const k = toLatLon(x, y), w = S.wps[drag.idx];
      if (!k || !w) return;
      w.lat = num(k.lat, 7); w.lon = num(k.lon, 7); drag.moved = true;
      movePtEnt(drag.idx);
    }, true);
    holder.addEventListener('pointerup', e => {
      if (!drag) return;
      stop(e);
      const { idx, moved } = drag;
      endDrag();
      if (!moved) { highlight(idx); openPop(idx, xy(e)); }
    }, true);
    holder.addEventListener('pointercancel', endDrag, true);
    holder.addEventListener('lostpointercapture', () => { if (drag) endDrag(); }, true);
    holder.addEventListener('click', e => {
      if (!viewer || e.button !== 0) return;
      const [x, y] = xy(e);
      const moved = down && Math.hypot(x - down.x, y - down.y) > 5;   // kamera döndürme sonrası click: nokta ekleme
      down = null;
      if (S.pick) { stop(e); if (moved) return; const k = toLatLon(x, y); if (k) finishPick(k); return; }
      if (!S.editing) return;
      stop(e);
      if (moved || Date.now() - lastDragEnd < 250 || pickIdx(x, y) >= 0) return;
      const k = toLatLon(x, y);
      if (k) addPoint(k.lat, k.lon, [x, y]);
    }, true);
    holder.addEventListener('contextmenu', e => {
      if (!viewer || !S.editing || S.pick) return;
      const [x, y] = xy(e);
      const idx = pickIdx(x, y);
      if (idx < 0) return;
      stop(e);
      removeWp(idx);
    }, true);
  }
  const initMap = async () => {
    try { Cesium = await loadCesium(); } catch (err) { msg.textContent = err.message; msg.classList.add('err'); return; }
    if (destroyed) return;
    try {
      viewer = createViewer(Cesium, holder, { fullscreen: false });
    } catch (err) {
      msg.textContent = `3B harita başlatılamadı: ${err.message}`; msg.classList.add('err'); return;
    }
    C = {
      white: Cesium.Color.WHITE, black: Cesium.Color.BLACK,
      sel: Cesium.Color.fromCssColorString(SEL_LINE),
      dim: Cesium.Color.WHITE.withAlpha(0.4), dimmer: Cesium.Color.WHITE.withAlpha(0.15),
      stick: Cesium.Color.fromCssColorString('#93c5fd').withAlpha(0.85),
    };
    msg.hidden = true;
    onLeave(() => { if (viewer && !viewer.isDestroyed()) viewer.destroy(); viewer = null; });
    installInput();
    drawBase(); drawSel();
    if (S.sel) fitToRoute(); else fitAll();
  };

  // ---------- formlar ----------
  async function centerForm(c, draft) {
    const locations = await api.get('/api/field/locations').catch(() => []);
    const v = draft || c || {};
    const name = inp(v.name, { placeholder: 'Örn. Ankara pist', maxlength: 120 });
    const lat = inp(v.lat != null ? num(v.lat, 7) : '', { type: 'number', step: 'any', placeholder: '39.9' });
    const lon = inp(v.lon != null ? num(v.lon, 7) : '', { type: 'number', step: 'any', placeholder: '32.8' });
    const alt = inp(v.alt, { type: 'number', step: 'any', placeholder: 'm (deniz seviyesi)' });
    const loc = sel(locations.map(l => [l.id, l.name]), v.location_id, { empty: 'Görev yeri bağlanmadı' });
    const note = h('textarea', { class: 'input', rows: 2 }, v.note || '');
    const [activeEl, active] = check('Aktif', v.active == null ? true : !!v.active);
    const collect = () => ({ name: name.value.trim(), lat: num(lat.value, 7), lon: num(lon.value, 7), alt: num(alt.value, 1), location_id: num(loc.value), note: note.value.trim() || null, active: active.checked });
    const geoBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => {
      if (!navigator.geolocation) return toast('Bu cihazda konum servisi yok', 'err');
      navigator.geolocation.getCurrentPosition(p => { lat.value = p.coords.latitude.toFixed(6); lon.value = p.coords.longitude.toFixed(6); if (p.coords.altitude != null) alt.value = Math.round(p.coords.altitude); toast('Konum alındı'); },
        () => toast('Konum alınamadı', 'err'), { enableHighAccuracy: true, timeout: 10000 });
    } }, 'Bulunduğum konumu kullan');
    modal({
      title: c ? 'Merkez bilgileri' : 'Yeni Rota Merkezi',
      body: h('div', null, field('Merkez adı', name), h('div', { class: 'row' }, field('Enlem', lat), field('Boylam', lon)),
        h('div', { class: 'row' }, field('İrtifa (m)', alt), field('Görev yeri', loc)), geoBtn, field('Not', note), activeEl),
      actions: [{ label: 'Vazgeç' }, { label: 'Haritadan seç', onClick: () => { startPick(c, collect()); } }, {
        label: c ? 'Kaydet' : 'Ekle', class: 'primary', onClick: async () => {
          const body = collect();
          if (!body.name) throw new Error('Merkez adı gerekli');
          if (body.lat == null || body.lon == null) throw new Error('Enlem ve boylam gerekli; "Haritadan seç" ile de işaretleyebilirsiniz');
          if (c) await api.put(`/api/drone/centers/${c.id}`, body); else await api.post('/api/drone/centers', body);
          toast(c ? 'Merkez güncellendi' : 'Merkez eklendi');
          await reload();
        },
      }],
    });
  }
  // Rota bilgileri (ad, merkez, tür, seyir irtifası / hızı, not, aktif). Yeni rota: POST → seçilir → düzenleme modu açılır.
  // Düzenlenen rota seçiliyse mevcut (kaydedilmemiş olabilir) noktalar da PUT ile yazılır; değilse sunucudaki noktalar korunur.
  function routeForm(r) {
    const name = inp(r?.name, { placeholder: 'Örn. Devriye 1', maxlength: 120 });
    const center = sel(S.centers.filter(c => c.active || c.id === r?.center_id).map(c => [c.id, c.name]), r ? r.center_id : S.selCenter, { empty: 'Merkez seçilmedi' });
    const kind = sel(Object.entries(m.route_kinds || {}), r?.kind || 'line');
    const cAlt = inp(r?.cruise_alt, { type: 'number', step: 'any', placeholder: '100' });
    const cSpd = inp(r?.cruise_speed, { type: 'number', step: 'any', placeholder: 'm/s' });
    const note = h('textarea', { class: 'input', rows: 2 }, r?.note || '');
    const [activeEl, active] = check('Aktif', r ? !!r.active : true);
    modal({
      title: r ? tr('{name} · rota bilgileri', { name: r.name }) : 'Yeni Rota',
      body: h('div', null, field('Rota adı', name), h('div', { class: 'row' }, field('Merkez', center), field('Tür', kind)),
        h('div', { class: 'row' }, field('Seyir irtifası (m, göreli)', cAlt, 'İrtifası boş noktalar bu değeri alır'), field('Seyir hızı (m/s)', cSpd)),
        field('Not', note), activeEl,
        r ? null : h('p', { class: 'small muted' }, 'Oluşturulunca harita düzenleme modunda açılır: tıklayarak nokta ekleyin, sürükleyerek taşıyın, sağ tıkla silin; sağ üstten kaydedin.')),
      actions: [{ label: 'Vazgeç' }, {
        label: r ? 'Kaydet' : 'Oluştur ve düzenle', class: 'primary', onClick: async () => {
          if (!name.value.trim()) throw new Error('Rota adı gerekli');
          const base = { name: name.value.trim(), center_id: num(center.value), kind: kind.value, cruise_alt: num(cAlt.value, 1), cruise_speed: num(cSpd.value, 1), note: note.value.trim() || null, active: active.checked };
          const c = S.centers.find(x => x.id === base.center_id);
          if (r) {
            const wps = S.sel?.id === r.id ? S.wps : (S.detail[r.id]?.waypoints || (await ensureDetail(r.id)).waypoints);
            await api.put(`/api/drone/routes/${r.id}`, { ...base, waypoints: copyWps(wps).map(w => ({ ...w, lat: num(w.lat, 7), lon: num(w.lon, 7), alt: num(w.alt, 1), hold_s: num(w.hold_s, 1) })) });
            if (S.sel?.id === r.id) { S.dirty = false; delete S.detail[r.id]; }
            toast('Rota güncellendi');
            await reload();
          } else {
            if (!await leaveEditing()) return true;
            const out = await api.post('/api/drone/routes', { ...base, waypoints: c ? [{ lat: c.lat, lon: c.lon, alt: null, action: 'takeoff', hold_s: null, note: null }] : [] });
            toast('Rota oluşturuldu; haritadan nokta ekleyin');
            S.sel = null; S.dirty = false;
            await reload();
            await selectRoute(out.id);
          }
        },
      }],
    });
  }
  const missionModal = async () => {
    if (S.dirty) await save();
    const ms = await api.get(`/api/drone/routes/${S.sel.id}/mission`);
    const txt = JSON.stringify(ms.items, null, 1);
    modal({
      title: 'MAVLink görevi (MISSION_ITEM_INT)', wide: true,
      body: h('div', null, h('p', { class: 'small muted' }, tr('{n} öğe · çerçeve GLOBAL_RELATIVE_ALT_INT · köprüye mission_upload komutuyla gönderilir.', { n: ms.items.length })),
        h('pre', { style: { maxHeight: '50vh', overflow: 'auto', fontSize: '12px' } }, txt)),
      actions: [{ label: 'Kapat' }, { label: 'JSON kopyala', class: 'primary', onClick: async () => { await copy(txt, 'Görev JSON kopyalandı'); return true; } }],
    });
  };
  const uploadModal = async () => {
    if (S.dirty) await save();
    const bridges = (await api.get('/api/drone/bridges').catch(() => [])).filter(b => b.online);
    if (!bridges.length) throw new Error('Çevrimiçi köprü yok; görev yüklemek için pilot cihazındaki köprü bağlı olmalı');
    const bsel = sel(bridges.map(b => [b.id, b.name]), bridges[0].id);
    const sysid = inp(1, { type: 'number', min: 1, max: 255 });
    const rid = S.sel.id;
    modal({
      title: 'Görevi drona yükle',
      body: h('div', null, h('div', { class: 'row' }, field('Köprü', bsel), field('MAVLink sysid', sysid)),
        h('p', { class: 'small muted' }, 'Rota, köprü üzerinden drona MAVLink görevi olarak yüklenir (uçuş başlamaz; mod AUTO yapılınca izlenir). İşlem Pilot rolü ve Canlı Uçuş yazma yetkisi ister; kayda geçer.')),
      actions: [{ label: 'Vazgeç' }, { label: 'Yükle', class: 'primary', onClick: async () => {
        const ms = await api.get(`/api/drone/routes/${rid}/mission`);
        const res = await api.post('/api/drone/live/cmd', { bridge_id: num(bsel.value), sysid: num(sysid.value) || 1, name: 'mission_upload', params: { items: ms.items, cruise_speed: ms.cruise_speed } });
        if (!res.ok) throw new Error(res.error || 'Köprü görevi kabul etmedi');
        toast('Görev drona yüklendi');
      } }],
    });
  };

  // ---------- klavye: Esc pencere/seçme modunu kapatır; Delete vurgulu noktayı siler ----------
  const onKey = e => {
    if (e.target?.closest?.('input, select, textarea, .modal-back')) return;
    if (e.key === 'Escape') { if (!pop.hidden) closePop(); else if (S.pick) cancelPick(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && S.editing && S.hi >= 0) { e.preventDefault(); removeWp(S.hi); }
  };
  document.addEventListener('keydown', onKey);
  onLeave(() => document.removeEventListener('keydown', onKey));

  // Test ve hata ayıklama kancası (Browserless betiği harita tıklamasını buradan simüle eder); sayfadan çıkınca kaldırılır
  window.__rt = {
    addPoint: (lat, lon) => addPoint(lat, lon),
    select: (id, opts) => selectRoute(id, opts),
    save: () => save(),
    state: () => ({ sel: S.sel?.id ?? null, editing: S.editing, dirty: S.dirty, hi: S.hi, selCenter: S.selCenter, wps: copyWps(S.wps), centers: S.centers.length, routes: S.routes.length }),
    viewer: () => viewer,
  };
  onLeave(() => { delete window.__rt; });

  // ---------- başlat ----------
  drawTools(); drawBadge(); drawSteps();
  try {
    await reload();
  } catch (err) {
    clear(view, head('Rotalar'), h('div', { class: 'card empty' }, err.message || 'Rotalar yüklenemedi'));
    return;
  }
  const wantId = Number(params?.[1]);
  if (wantId && S.routes.some(r => r.id === wantId)) await selectRoute(wantId).catch(toastError);   // #/field/routes/<id> doğrudan bağlantı
  initMap().catch(err => { msg.textContent = err.message; msg.classList.add('err'); });
}
