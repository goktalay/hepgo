// Canlı Konum (MASTER) — kullanıcıların en son konumlarını TAM EKRAN harita üzerinde fotoğraflarıyla gösterir.
// Veri: GET /api/location/latest (yalnız master/admin/güvenlik/İK). Konumu olmayan kullanıcı gösterilmez.
// "N kişi" etiketi → solda personel listesi (ad, son görülme, cihaz; arama). Kişi seçilince haritada yalnız o kişi vurgulanır,
// diğerleri soluklaşır ve GEÇMİŞ İZİ çizilir (GET /api/location/history: son 1 sa / 24 sa / 7 gün; çizgi + zaman damgalı noktalar,
// başlangıç/bitiş işaretleri). "Tümü" ile geri dönülür. Koyu temada harita karoları ve kişi kartı (InfoWindow) koyu.
// Google Haritalar anahtarı yoksa liste yedeğine düşer (panel + iz özeti metin olarak çalışır).
import { api, fileUrl } from '../api.js';
import { clear, fmtDateTime, h, onLeave, t, toast, toastError } from '../ui.js';
import { loadMaps } from '../maps.js';

const initials = name => (name || '?').split(/\s+/).slice(0, 2).map(x => x[0] || '').join('').toLocaleUpperCase('tr');
const ago = iso => {
  if (!iso) return '—';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (isNaN(s)) return '—';
  if (s < 60) return t('az önce');
  if (s < 3600) return t('{n} dk önce', { n: Math.floor(s / 60) });
  if (s < 86400) return t('{n} sa önce', { n: Math.floor(s / 3600) });
  return t('{n} gün önce', { n: Math.floor(s / 86400) });
};
// Çerçeve rengi = kullanıcının ONLINE durumu (last_seen): canlı<2dk yeşil, yakın zamanda<30dk turuncu, offline gri
const presence = lastSeen => {
  const s = lastSeen ? (Date.now() - new Date(lastSeen).getTime()) / 1000 : 1e12;
  if (isNaN(s)) return { cls: 'stale', label: 'Çevrimdışı' };
  if (s < 120) return { cls: 'fresh', label: 'Çevrimiçi' };
  if (s < 1800) return { cls: 'warm', label: 'Yakın zamanda' };
  return { cls: 'stale', label: 'Çevrimdışı' };
};
const platformLabel = p => (p === 'web' ? 'Web tarayıcı' : p === 'ios' ? 'iOS App' : p === 'android' ? 'Android App' : 'Uygulama');
function avatarEl(p, cls = '') {
  const el = h('div', { class: `um-av ${presence(p.last_seen).cls} ${cls}`, title: p.full_name });
  if (p.photo) el.style.backgroundImage = `url('${fileUrl(p.photo, 128)}')`;
  else { el.textContent = initials(p.full_name); el.classList.add('noimg'); }
  return el;
}
const isDark = () => document.documentElement.dataset.theme === 'dark';
// Google Haritalar koyu (gece) karo stili — koyu temada harita da koyu
const DARK_STYLE = [
  { elementType: 'geometry', stylers: [{ color: '#1d2634' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#1d2634' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#8fa0b8' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#3a4659' }] },
  { featureType: 'administrative.locality', elementType: 'labels.text.fill', stylers: [{ color: '#c9d4e5' }] },
  { featureType: 'poi', elementType: 'labels.text.fill', stylers: [{ color: '#8fa0b8' }] },
  { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#1f3a2a' }] },
  { featureType: 'poi.park', elementType: 'labels.text.fill', stylers: [{ color: '#6b9a7a' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#2c3747' }] },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: [{ color: '#1a222e' }] },
  { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#9aa8bd' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#4a5468' }] },
  { featureType: 'road.highway', elementType: 'geometry.stroke', stylers: [{ color: '#1a222e' }] },
  { featureType: 'road.highway', elementType: 'labels.text.fill', stylers: [{ color: '#d6deea' }] },
  { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#2c3747' }] },
  { featureType: 'transit.station', elementType: 'labels.text.fill', stylers: [{ color: '#9aa8bd' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0f1a2a' }] },
  { featureType: 'water', elementType: 'labels.text.fill', stylers: [{ color: '#4a6a8a' }] },
];
const RANGES = [[1, 'Son 1 saat'], [24, 'Son 24 saat'], [168, 'Son 7 gün']];

export async function render(view, params, ctx) {
  const allowed = ctx.user.master || (ctx.user.roles || []).some(r => ['admin', 'security', 'hr'].includes(r));
  if (!allowed) { clear(view, h('div', { class: 'card empty' }, 'Bu modül yalnızca yetkili rollere açıktır.')); return; }

  clear(view);
  // Tam ekran harita katmanı (body'e; app kabuğunun üstünü de kaplar). onLeave ile temizlenir.
  const mapBox = h('div', { class: 'um-map' });
  const countChip = h('button', { class: 'um-count', type: 'button', title: 'Personel listesi', 'aria-label': 'Personel listesi', 'aria-expanded': 'false' }, '…');
  const back = h('button', { class: 'um-back', type: 'button', title: 'Geri', 'aria-label': 'Geri' }, '←');
  back.addEventListener('click', () => { if (history.length > 1) history.back(); else location.hash = '#/'; });
  const coBtn = h('button', { class: 'um-toggle on', type: 'button', title: 'Firma konumları' }, '🏢 Firmalar');
  const bar = h('div', { class: 'um-bar' }, back, h('b', { class: 'um-title' }, 'Canlı Konum'), h('span', { class: 'spacer' }), coBtn, countChip);

  // ---- Sol panel: personel listesi + arama + (seçimde) zaman aralığı / Tümü
  const search = h('input', { class: 'um-search', type: 'search', placeholder: 'Ara…', 'aria-label': 'Personel ara' });
  const list = h('div', { class: 'um-list', role: 'listbox' });
  const allBtn = h('button', { class: 'um-all', type: 'button', hidden: true }, '← Tümü');
  const rangeBox = h('div', { class: 'um-range', role: 'group', hidden: true });
  const trailInfo = h('div', { class: 'um-trailinfo small', hidden: true });
  const panelClose = h('button', { class: 'um-pclose', type: 'button', title: 'Kapat', 'aria-label': 'Kapat' }, '✕');
  const panel = h('aside', { class: 'um-panel', 'aria-label': 'Personel listesi' },
    h('div', { class: 'um-phead' }, h('b', null, 'Personel'), h('span', { class: 'spacer' }), panelClose),
    search, allBtn, rangeBox, trailInfo, list);
  const full = h('div', { class: 'um-full' }, mapBox, bar, panel);
  document.body.appendChild(full);

  let maps = null, map = null, overlays = [], coOverlays = [], trail = [], AvatarOverlay = null, timer = null, firstFit = true, showCo = true;
  let people = [], selected = null, hours = 24, panelOpen = false, themeObs = null, pinByUid = new Map();
  const cleanup = () => { clearInterval(timer); themeObs?.disconnect(); [...overlays, ...coOverlays, ...trail].forEach(o => { try { o.setMap(null); } catch (e) { /* */ } }); full.remove(); };
  onLeave(cleanup);

  const located = ps => (ps || []).filter(p => p.lat != null && p.lng != null);
  const openPanel = on => { panelOpen = on; full.classList.toggle('um-panel-open', on); countChip.setAttribute('aria-expanded', on ? 'true' : 'false'); if (on) setTimeout(() => search.focus(), 50); };
  countChip.addEventListener('click', () => openPanel(!panelOpen));
  panelClose.addEventListener('click', () => openPanel(false));

  // Liste satırı: avatar + ad + son görülme (konum zamanı) + cihaz; seçili vurgulu
  const drawList = () => {
    const q = (search.value || '').trim().toLocaleLowerCase('tr');
    const ppl = located(people).filter(p => !q || (p.full_name || '').toLocaleLowerCase('tr').includes(q));
    clear(list, ppl.length ? ppl.map(p => {
      const pr = presence(p.last_seen);
      return h('button', { class: `um-row ${selected === p.user_id ? 'sel' : ''}`, type: 'button', role: 'option', 'aria-selected': selected === p.user_id ? 'true' : 'false',
        onclick: () => selectUser(selected === p.user_id ? null : p.user_id) },
        avatarEl(p, 'sm'),
        h('div', { class: 'um-rowmain' }, h('b', null, p.full_name || 'Kişi'),
          h('small', null, h('span', { class: `um-dot ${pr.cls}` }), `${t('Konum')}: ${ago(p.at)}`),
          h('small', { class: 'um-dev' }, platformLabel(p.platform), p.accuracy ? ` · ±${Math.round(p.accuracy)} m` : '')));
    }) : h('div', { class: 'um-empty small' }, q ? 'Eşleşen personel yok' : 'Konumu olan personel yok'));
  };
  search.addEventListener('input', drawList);

  // ---- Kişi seçimi: yalnız o kişi vurgulu, diğerleri soluk, geçmiş izi çizilir
  const clearTrail = () => { trail.forEach(o => { try { o.setMap(null); } catch (e) { /* */ } }); trail = []; };
  const drawRange = () => clear(rangeBox, RANGES.map(([hrs, label]) => h('button', { class: `um-rbtn ${hours === hrs ? 'on' : ''}`, type: 'button',
    onclick: () => { hours = hrs; drawRange(); loadTrail(); } }, label)));
  async function selectUser(uid) {
    selected = uid;
    allBtn.hidden = rangeBox.hidden = !uid;
    trailInfo.hidden = true;
    full.classList.toggle('um-sel', !!uid);
    drawList(); drawRange();
    applyDim();
    clearTrail();
    if (!uid) { if (map && located(people).length) fitAll(); return; }
    await loadTrail();
  }
  allBtn.addEventListener('click', () => selectUser(null));
  const applyDim = () => { for (const [uid, pin] of pinByUid) { pin.classList.toggle('dim', !!selected && uid !== selected); pin.classList.toggle('sel', !!selected && uid === selected); } };
  const fitAll = () => { const b = new maps.LatLngBounds(); located(people).forEach(p => b.extend(new maps.LatLng(p.lat, p.lng))); map.fitBounds(b, 64); if (located(people).length === 1) map.setZoom(15); };

  async function loadTrail() {
    if (!selected) return;
    const uid = selected;
    let d;
    try { d = await api.get(`/api/location/history?user_id=${uid}&hours=${hours}`); } catch (e) { toastError(e); return; }
    if (selected !== uid) return;   // bu arada başka kişi seçildi
    const pts = (d.points || []).filter(x => x.lat != null && x.lng != null);
    clearTrail();
    trailInfo.hidden = false;
    if (!pts.length) { trailInfo.textContent = t('Bu aralıkta konum geçmişi yok'); return; }
    trailInfo.replaceChildren(h('b', null, t('{n} nokta', { n: pts.length })), ' · ', h('span', null, `${fmtDateTime(pts[0].at)} → ${fmtDateTime(pts[pts.length - 1].at)}`));
    if (!map) return;
    const path = pts.map(x => new maps.LatLng(x.lat, x.lng));
    const dark = isDark();
    const line = new maps.Polyline({ path, geodesic: true, strokeColor: dark ? '#8bb8f5' : '#2563eb', strokeOpacity: .9, strokeWeight: 4, map });
    trail.push(line);
    // Zaman damgalı noktalar: en çok ~60 etiket (iz uzunsa seyreltilir); baş/son her zaman
    const step = Math.max(1, Math.ceil(pts.length / 60));
    pts.forEach((x, k) => {
      const first = k === 0, last = k === pts.length - 1;
      if (!first && !last && k % step) return;
      const el = h('div', { class: `um-tp ${first ? 'start' : ''} ${last ? 'end' : ''}`, title: `${fmtDateTime(x.at)}${x.accuracy ? ` · ±${Math.round(x.accuracy)} m` : ''}` },
        h('span', { class: 'um-tpdot' }), h('span', { class: 'um-tplbl' }, first ? `${t('Başlangıç')} · ${fmtDateTime(x.at)}` : last ? `${t('Bitiş')} · ${fmtDateTime(x.at)}` : fmtDateTime(x.at)));
      const ov = new AvatarOverlay(path[k], el); ov.setMap(map); trail.push(ov);
    });
    const b = new maps.LatLngBounds(); path.forEach(p => b.extend(p)); map.fitBounds(b, 80);
    if (pts.length === 1) map.setZoom(16);
  }

  maps = await loadMaps().catch(() => null);
  if (!maps) {
    mapBox.classList.add('um-nokey');
    mapBox.append(h('div', { class: 'empty' }, h('div', { class: 'um-nokey-ic' }, '🗺️'),
      h('p', null, 'Harita için Google Haritalar anahtarı gerekli.'),
      h('p', { class: 'small muted' }, 'Program Ayarları › Entegrasyonlar › Google Haritalar')));
    // yine de kişileri say ve listele (iz özeti metin olarak)
    try { const d = await api.get('/api/location/latest'); people = d.people || []; countChip.textContent = t('{n} kişi', { n: located(people).length }); drawList(); } catch (e) { /* */ }
    return;
  }

  AvatarOverlay = class extends maps.OverlayView {
    constructor(pos, el) { super(); this.pos = pos; this.el = el; }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.el); }
    draw() { const pr = this.getProjection(); if (!pr) return; const pt = pr.fromLatLngToDivPixel(this.pos); if (pt) { this.el.style.left = pt.x + 'px'; this.el.style.top = pt.y + 'px'; } }
    onRemove() { this.el.remove(); }
  };
  map = new maps.Map(mapBox, { mapTypeId: 'roadmap', mapTypeControl: false, streetViewControl: false, fullscreenControl: false, zoomControl: true, gestureHandling: 'greedy', zoom: 6, center: { lat: 39.0, lng: 35.0 },
    styles: isDark() ? DARK_STYLE : null, backgroundColor: isDark() ? '#0f141c' : undefined });
  // Tema değişince (Kişisel Ayarlar) karolar da değişsin
  themeObs = new MutationObserver(() => { try { map.setOptions({ styles: isDark() ? DARK_STYLE : null }); } catch (e) { /* */ } if (selected) loadTrail(); });
  themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  const draw = ppl0 => {
    people = ppl0 || [];
    const ppl = located(people);
    countChip.textContent = t('{n} kişi', { n: ppl.length });
    overlays.forEach(o => o.setMap(null)); overlays = []; pinByUid = new Map();
    const bounds = new maps.LatLngBounds();
    for (const p of ppl) {
      const pos = new maps.LatLng(p.lat, p.lng); bounds.extend(pos);
      const web = p.platform === 'web';   // tarayıcıdan paylaşılan konum: kesik çerçeve + 'Web' etiketi (doğruluk daha düşük olabilir)
      const pin = h('div', { class: `um-pin ${web ? 'web' : ''}` }, avatarEl(p, web ? 'web' : ''), h('span', { class: 'um-pin-name' }, (p.full_name || '').split(' ')[0] + (web ? ' · Web' : '')));
      pinByUid.set(p.user_id, pin);
      const pr = presence(p.last_seen);
      const info = new maps.InfoWindow({ content: h('div', { class: 'um-info' },
        h('b', null, p.full_name || 'Kişi'),
        h('div', { class: 'small' }, h('span', { class: `um-dot ${pr.cls}` }), pr.label),
        h('div', { class: 'small muted' }, `${t('Konum')}: ${ago(p.at)}${p.accuracy ? ` · ±${Math.round(p.accuracy)} m` : ''} · ${t(platformLabel(p.platform))}`),
        h('div', { class: 'um-info-links' },
          h('a', { href: 'javascript:void 0', class: 'small', onclick: e => { e.preventDefault(); info.close(); openPanel(true); selectUser(p.user_id); } }, '🕒 Geçmiş izi'), ' · ',
          h('a', { href: `https://www.google.com/maps?q=${p.lat},${p.lng}`, target: '_blank', rel: 'noopener', class: 'small' }, 'Google Haritalar ↗')),
        // Ev olarak kaydet: bu konum personelin 'Ev' adresine enlem/boylam olarak yazılır (İK › Adresler haritasında ev işareti)
        p.employee_id ? h('div', { style: { marginTop: '6px' } }, h('button', { class: 'btn sm', type: 'button', onclick: async e => {
          const btn = e.currentTarget; btn.disabled = true;
          try { const r = await api.post(`/api/hr/employees/${p.employee_id}/home-location`, { lat: p.lat, lng: p.lng }); toast(r.created ? 'Ev konumu kaydedildi (yeni Ev adresi açıldı)' : 'Ev konumu güncellendi'); btn.textContent = '🏠 Ev kaydedildi'; }
          catch (err) { toastError(err); btn.disabled = false; }
        } }, '🏠 Ev olarak kaydet')) : null) });
      pin.addEventListener('click', () => { info.setPosition(pos); info.open(map); });
      const ov = new AvatarOverlay(pos, pin); ov.setMap(map); overlays.push(ov);
    }
    applyDim();
    drawList();
    if (ppl.length && firstFit) { map.fitBounds(bounds, 64); if (ppl.length === 1) map.setZoom(15); firstFit = false; }
  };

  // Firma konumları: logo (yoksa baş harf) işaretçisi; tıklayınca ad + adres + kaynak
  const drawCompanies = async () => {
    coOverlays.forEach(o => o.setMap(null)); coOverlays = [];
    if (!showCo) return;
    let cos = [];
    try { cos = await api.get('/api/companies/geo'); } catch { return; }
    for (const c of cos) {
      const pos = new maps.LatLng(c.lat, c.lng);
      const ini = (c.name || '?').split(/\s+/).slice(0, 2).map(s => s[0]).join('').toLocaleUpperCase('tr');
      const pin = h('div', { class: `um-copin ${c.is_supplier ? 'sup' : ''} ${c.geo_source === 'approx' ? 'approx' : ''}`, title: c.geo_source === 'approx' ? 'Yaklaşık konum (ilçe merkezi)' : '' }, c.logo ? h('img', { src: fileUrl(c.logo, 128), alt: '' }) : h('span', { class: 'um-coini' }, ini), h('span', { class: 'um-pin-name' }, (c.name || '').split(' ').slice(0, 2).join(' ')));
      const info = new maps.InfoWindow({ content: h('div', { class: 'um-info' }, h('b', null, c.name), c.address ? h('div', { class: 'small' }, c.address) : null,
        h('div', { class: 'small muted' }, `${c.geo_label || ''}${c.geo_source ? ` · ${c.geo_source}` : ''}`),
        h('a', { href: `#/companies/${c.id}`, class: 'small' }, 'Firma kartı →'), ' · ', h('a', { href: `https://www.google.com/maps?q=${c.lat},${c.lng}`, target: '_blank', rel: 'noopener', class: 'small' }, 'Google Haritalar ↗')) });
      pin.addEventListener('click', () => { info.setPosition(pos); info.open(map); });
      const ov = new AvatarOverlay(pos, pin); ov.setMap(map); coOverlays.push(ov);
    }
  };
  coBtn.addEventListener('click', () => { showCo = !showCo; coBtn.classList.toggle('on', showCo); drawCompanies(); });
  const load = async () => { try { const d = await api.get('/api/location/latest'); draw(d.people); if (selected) loadTrail(); } catch (e) { toastError(e); } };
  await load();
  drawCompanies();
  timer = setInterval(load, 20000);
}
