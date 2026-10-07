// Canlı Konum (MASTER) — kullanıcıların en son konumlarını harita üzerinde fotoğraflarıyla gösterir.
// Veri: GET /api/location/latest (yalnız master/admin/güvenlik/İK). Google Haritalar anahtarı yoksa liste yedeğine düşer.
import { api, fileUrl } from '../api.js';
import { clear, h, onLeave, pageHead, t, toastError } from '../ui.js';
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
const freshClass = iso => {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  return s < 300 ? 'fresh' : s < 3600 ? 'warm' : 'stale';   // 5 dk / 1 saat
};

// Avatar baloncuğu (fotoğraf ya da baş harf) — hem haritada hem listede
function avatarEl(p, cls = '') {
  const el = h('div', { class: `um-av ${freshClass(p.at)} ${cls}`, title: p.full_name });
  if (p.photo) el.style.backgroundImage = `url('${fileUrl(p.photo, 128)}')`;
  else { el.textContent = initials(p.full_name); el.classList.add('noimg'); }
  return el;
}

export async function render(view, params, ctx) {
  const allowed = ctx.user.master || (ctx.user.roles || []).some(r => ['admin', 'security', 'hr'].includes(r));
  if (!allowed) { clear(view, h('div', { class: 'card empty' }, 'Bu modül yalnızca yetkili rollere açıktır.')); return; }

  clear(view, pageHead('Canlı Konum', 'Personelin en son bildirilen konumu (mobil uygulama, açık rıza ile)'));
  const mapBox = h('div', { class: 'um-map' });
  const sideList = h('div', { class: 'um-list' });
  const wrap = h('div', { class: 'card um-wrap' }, mapBox, sideList);
  view.append(wrap);

  let people = [];
  let maps = null, map = null, overlays = [], AvatarOverlay = null, timer = null, firstFit = true;

  const load = async () => {
    try {
      const d = await api.get('/api/location/latest');
      people = d.people || [];
    } catch (e) { toastError(e); return; }
    draw();
  };

  const focus = p => {
    if (map && p.lat != null) { map.panTo({ lat: p.lat, lng: p.lng }); map.setZoom(Math.max(map.getZoom() || 0, 15)); }
  };

  const drawList = () => {
    clear(sideList, h('div', { class: 'um-list-h' }, h('b', null, t('{n} kişi', { n: people.length })),
      h('span', { class: 'small muted' }, 'Son konum')));
    if (!people.length) { sideList.append(h('div', { class: 'empty small muted' }, 'Henüz konum verisi yok')); return; }
    people.forEach(p => {
      const row = h('button', { type: 'button', class: 'um-row' }, avatarEl(p, 'sm'),
        h('div', { class: 'um-row-main' }, h('b', null, p.full_name || 'Kişi'),
          h('span', { class: 'small muted' }, `${ago(p.at)}${p.accuracy ? ` · ±${Math.round(p.accuracy)} m` : ''}`)),
        p.lat != null ? h('span', { class: 'um-open', title: 'Google Haritalar' }) : null);
      row.addEventListener('click', () => focus(p));
      sideList.append(row);
    });
  };

  const drawMarkers = () => {
    if (!map) return;
    overlays.forEach(o => o.setMap(null));
    overlays = [];
    const bounds = new maps.LatLngBounds();
    let n = 0;
    for (const p of people) {
      if (p.lat == null || p.lng == null) continue;
      const pos = new maps.LatLng(p.lat, p.lng);
      bounds.extend(pos); n++;
      const pin = h('div', { class: 'um-pin' }, avatarEl(p), h('span', { class: 'um-pin-name' }, (p.full_name || '').split(' ')[0]));
      const info = new maps.InfoWindow({ content: h('div', { class: 'um-info' },
        h('b', null, p.full_name || 'Kişi'),
        h('div', { class: 'small muted' }, `${ago(p.at)}${p.accuracy ? ` · ±${Math.round(p.accuracy)} m` : ''}`),
        h('a', { href: `https://www.google.com/maps?q=${p.lat},${p.lng}`, target: '_blank', rel: 'noopener', class: 'small' }, 'Google Haritalar ↗')) });
      pin.addEventListener('click', () => { info.setPosition(pos); info.open(map); });
      const ov = new AvatarOverlay(pos, pin);
      ov.setMap(map);
      overlays.push(ov);
    }
    if (n && firstFit) { map.fitBounds(bounds, 60); if (n === 1) map.setZoom(15); firstFit = false; }
  };

  const draw = () => { drawList(); drawMarkers(); };

  maps = await loadMaps().catch(() => null);
  if (!maps) {
    // Yedek: harita anahtarı yok → yalnız liste + Google Haritalar bağlantıları
    mapBox.classList.add('um-nokey');
    mapBox.append(h('div', { class: 'empty' },
      h('div', { class: 'um-nokey-ic' }, '🗺️'),
      h('p', null, 'Harita için Google Haritalar anahtarı gerekli.'),
      h('p', { class: 'small muted' }, 'Program Ayarları › Entegrasyonlar › Google Haritalar')));
    await load();
    timer = setInterval(load, 20000);
    onLeave(() => clearInterval(timer));
    return;
  }

  // Fotoğraflı işaretçi için HTML tabanlı OverlayView
  AvatarOverlay = class extends maps.OverlayView {
    constructor(pos, el) { super(); this.pos = pos; this.el = el; }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.el); }
    draw() { const pr = this.getProjection(); if (!pr) return; const pt = pr.fromLatLngToDivPixel(this.pos); if (pt) { this.el.style.left = pt.x + 'px'; this.el.style.top = pt.y + 'px'; } }
    onRemove() { this.el.remove(); }
  };
  map = new maps.Map(mapBox, { mapTypeId: 'roadmap', mapTypeControl: true, streetViewControl: false, fullscreenControl: true, zoom: 6, center: { lat: 39.0, lng: 35.0 } });

  await load();
  timer = setInterval(load, 20000);   // 20 sn'de bir tazele
  onLeave(() => { clearInterval(timer); overlays.forEach(o => o.setMap(null)); });
}
