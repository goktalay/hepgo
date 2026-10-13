// Canlı Konum (MASTER) — kullanıcıların en son konumlarını TAM EKRAN harita üzerinde fotoğraflarıyla gösterir.
// Veri: GET /api/location/latest (yalnız master/admin/güvenlik/İK). Konumu olmayan kullanıcı gösterilmez.
// Google Haritalar anahtarı yoksa liste yedeğine düşer.
import { api, fileUrl } from '../api.js';
import { clear, h, onLeave, t, toast, toastError } from '../ui.js';
import { loadMaps } from '../maps.js';

const initials = name => (name || '?').split(/\s+/).slice(0, 2).map(x => x[0] || '').join('').toLocaleUpperCase('tr');
const ago = iso => {
  if (!iso) return '—';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (isNaN(s)) return '—';
  if (s < 60) return 'az önce';
  if (s < 3600) return `${Math.floor(s / 60)} dk önce`;
  if (s < 86400) return `${Math.floor(s / 3600)} sa önce`;
  return `${Math.floor(s / 86400)} gün önce`;
};
// Çerçeve rengi = kullanıcının ONLINE durumu (last_seen): canlı<2dk yeşil, yakın zamanda<30dk turuncu, offline gri
const presence = lastSeen => {
  const s = lastSeen ? (Date.now() - new Date(lastSeen).getTime()) / 1000 : 1e12;
  if (isNaN(s)) return { cls: 'stale', label: 'Çevrimdışı' };
  if (s < 120) return { cls: 'fresh', label: 'Çevrimiçi' };
  if (s < 1800) return { cls: 'warm', label: 'Yakın zamanda' };
  return { cls: 'stale', label: 'Çevrimdışı' };
};
function avatarEl(p, cls = '') {
  const el = h('div', { class: `um-av ${presence(p.last_seen).cls} ${cls}`, title: p.full_name });
  if (p.photo) el.style.backgroundImage = `url('${fileUrl(p.photo, 128)}')`;
  else { el.textContent = initials(p.full_name); el.classList.add('noimg'); }
  return el;
}

export async function render(view, params, ctx) {
  const allowed = ctx.user.master || (ctx.user.roles || []).some(r => ['admin', 'security', 'hr'].includes(r));
  if (!allowed) { clear(view, h('div', { class: 'card empty' }, 'Bu modül yalnızca yetkili rollere açıktır.')); return; }

  clear(view);
  // Tam ekran harita katmanı (body'e; app kabuğunun üstünü de kaplar). onLeave ile temizlenir.
  const mapBox = h('div', { class: 'um-map' });
  const countChip = h('span', { class: 'um-count' }, '…');
  const back = h('button', { class: 'um-back', type: 'button', title: 'Geri', 'aria-label': 'Geri' }, '←');
  back.addEventListener('click', () => { if (history.length > 1) history.back(); else location.hash = '#/'; });
  const coBtn = h('button', { class: 'um-toggle on', type: 'button', title: 'Firma konumları' }, '🏢 Firmalar');
  const bar = h('div', { class: 'um-bar' }, back, h('b', { class: 'um-title' }, 'Canlı Konum'), h('span', { class: 'spacer' }), coBtn, countChip);
  const full = h('div', { class: 'um-full' }, mapBox, bar);
  document.body.appendChild(full);

  let maps = null, map = null, overlays = [], coOverlays = [], AvatarOverlay = null, timer = null, firstFit = true, showCo = true;
  const cleanup = () => { clearInterval(timer); [...overlays, ...coOverlays].forEach(o => { try { o.setMap(null); } catch (e) { /* */ } }); full.remove(); };
  onLeave(cleanup);

  const located = ps => (ps || []).filter(p => p.lat != null && p.lng != null);

  maps = await loadMaps().catch(() => null);
  if (!maps) {
    mapBox.classList.add('um-nokey');
    mapBox.append(h('div', { class: 'empty' }, h('div', { class: 'um-nokey-ic' }, '🗺️'),
      h('p', null, 'Harita için Google Haritalar anahtarı gerekli.'),
      h('p', { class: 'small muted' }, 'Program Ayarları › Entegrasyonlar › Google Haritalar')));
    // yine de kişileri say
    try { const d = await api.get('/api/location/latest'); countChip.textContent = t('{n} kişi', { n: located(d.people).length }); } catch (e) { /* */ }
    return;
  }

  AvatarOverlay = class extends maps.OverlayView {
    constructor(pos, el) { super(); this.pos = pos; this.el = el; }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.el); }
    draw() { const pr = this.getProjection(); if (!pr) return; const pt = pr.fromLatLngToDivPixel(this.pos); if (pt) { this.el.style.left = pt.x + 'px'; this.el.style.top = pt.y + 'px'; } }
    onRemove() { this.el.remove(); }
  };
  map = new maps.Map(mapBox, { mapTypeId: 'roadmap', mapTypeControl: false, streetViewControl: false, fullscreenControl: false, zoomControl: true, gestureHandling: 'greedy', zoom: 6, center: { lat: 39.0, lng: 35.0 } });

  const draw = people => {
    const ppl = located(people);
    countChip.textContent = t('{n} kişi', { n: ppl.length });
    overlays.forEach(o => o.setMap(null)); overlays = [];
    const bounds = new maps.LatLngBounds();
    for (const p of ppl) {
      const pos = new maps.LatLng(p.lat, p.lng); bounds.extend(pos);
      const web = p.platform === 'web';   // tarayıcıdan paylaşılan konum: kesik çerçeve + 'Web' etiketi (doğruluk daha düşük olabilir)
      const pin = h('div', { class: `um-pin ${web ? 'web' : ''}` }, avatarEl(p, web ? 'web' : ''), h('span', { class: 'um-pin-name' }, (p.full_name || '').split(' ')[0] + (web ? ' · Web' : '')));
      const pr = presence(p.last_seen);
      const info = new maps.InfoWindow({ content: h('div', { class: 'um-info' },
        h('b', null, p.full_name || 'Kişi'),
        h('div', { class: 'small' }, h('span', { class: `um-dot ${pr.cls}` }), pr.label),
        h('div', { class: 'small muted' }, `Konum: ${ago(p.at)}${p.accuracy ? ` · ±${Math.round(p.accuracy)} m` : ''} · ${p.platform === 'web' ? 'Web tarayıcı' : p.platform === 'ios' ? 'iOS App' : p.platform === 'android' ? 'Android App' : 'Uygulama'}`),
        h('a', { href: `https://www.google.com/maps?q=${p.lat},${p.lng}`, target: '_blank', rel: 'noopener', class: 'small' }, 'Google Haritalar ↗'),
        // Ev olarak kaydet: bu konum personelin 'Ev' adresine enlem/boylam olarak yazılır (İK › Adresler haritasında ev işareti)
        p.employee_id ? h('div', { style: { marginTop: '6px' } }, h('button', { class: 'btn sm', type: 'button', onclick: async e => {
          const btn = e.currentTarget; btn.disabled = true;
          try { const r = await api.post(`/api/hr/employees/${p.employee_id}/home-location`, { lat: p.lat, lng: p.lng }); toast(r.created ? 'Ev konumu kaydedildi (yeni Ev adresi açıldı)' : 'Ev konumu güncellendi'); btn.textContent = '🏠 Ev kaydedildi'; }
          catch (err) { toastError(err); btn.disabled = false; }
        } }, '🏠 Ev olarak kaydet')) : null) });
      pin.addEventListener('click', () => { info.setPosition(pos); info.open(map); });
      const ov = new AvatarOverlay(pos, pin); ov.setMap(map); overlays.push(ov);
    }
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
  const load = async () => { try { const d = await api.get('/api/location/latest'); draw(d.people); } catch (e) { toastError(e); } };
  await load();
  drawCompanies();
  timer = setInterval(load, 20000);
}
