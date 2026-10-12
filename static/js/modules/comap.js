// Firma Haritası (Firmalar / Rehber / Harita): konumu bulunan firmalar tam ekran haritada logolarıyla.
// Veri: GET /api/companies/geo (Firma Yönetimi › "Konumları bul" ile doldurulur). Arama + müşteri/tedarikçi süzgeci;
// logoya tıklayınca ad, adres, kaynak ve firma kartı bağlantısı. Canlı Konum ekranıyla aynı katman/CSS (um-*).
import { api, fileUrl } from '../api.js';
import { loadMaps } from '../maps.js';
import { clear, h, onLeave, t, toastError } from '../ui.js';

export async function render(view, ctx, { base = '#/companies' } = {}) {
  clear(view);
  const mapBox = h('div', { class: 'um-map' });
  const countChip = h('span', { class: 'um-count' }, '…');
  const back = h('button', { class: 'um-back', type: 'button', title: 'Geri', 'aria-label': 'Geri' }, '←');
  back.addEventListener('click', () => { location.hash = base; });
  const q = h('input', { class: 'um-search', type: 'search', placeholder: 'Firma ara…', 'aria-label': 'Firma ara' });
  const kind = h('select', { class: 'um-select' }, h('option', { value: '' }, 'Tümü'), h('option', { value: 'c' }, 'Müşteri / diğer'), h('option', { value: 's' }, 'Tedarikçi'));
  const bar = h('div', { class: 'um-bar' }, back, h('b', { class: 'um-title' }, 'Firma Haritası'), q, kind, h('span', { class: 'spacer' }), countChip);
  const full = h('div', { class: 'um-full' }, mapBox, bar);
  document.body.appendChild(full);

  let overlays = [], cos = [], openInfo = null;
  const cleanup = () => { overlays.forEach(o => { try { o.setMap(null); } catch (e) { /* */ } }); full.remove(); };
  onLeave(cleanup);

  const maps = await loadMaps().catch(() => null);
  if (!maps) {
    mapBox.classList.add('um-nokey');
    mapBox.append(h('div', { class: 'empty' }, h('p', null, 'Harita için Google Haritalar anahtarı gerekli.'), h('p', { class: 'small muted' }, 'Program Ayarları › Entegrasyonlar › Google Haritalar')));
    return;
  }
  const Overlay = class extends maps.OverlayView {
    constructor(pos, el) { super(); this.pos = pos; this.el = el; }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.el); }
    draw() { const pr = this.getProjection(); if (!pr) return; const pt = pr.fromLatLngToDivPixel(this.pos); if (pt) { this.el.style.left = pt.x + 'px'; this.el.style.top = pt.y + 'px'; } }
    onRemove() { this.el.remove(); }
  };
  const map = new maps.Map(mapBox, { mapTypeId: 'roadmap', mapTypeControl: false, streetViewControl: false, fullscreenControl: false, zoomControl: true, gestureHandling: 'greedy', zoom: 6, center: { lat: 39.0, lng: 35.0 } });

  const norm = s => (s || '').toLocaleLowerCase('tr');
  const draw = (fit = false) => {
    overlays.forEach(o => o.setMap(null)); overlays = [];
    const needle = norm(q.value.trim());
    const list = cos.filter(c => (!kind.value || (kind.value === 's') === !!c.is_supplier) && (!needle || norm(c.name).includes(needle) || norm(c.address).includes(needle)));
    countChip.textContent = t('{n} firma', { n: list.length });
    const bounds = new maps.LatLngBounds();
    for (const c of list) {
      const pos = new maps.LatLng(c.lat, c.lng); bounds.extend(pos);
      const ini = (c.name || '?').split(/\s+/).slice(0, 2).map(s => s[0]).join('').toLocaleUpperCase('tr');
      const pin = h('div', { class: `um-copin ${c.is_supplier ? 'sup' : ''} ${c.geo_source === 'approx' ? 'approx' : ''}`, title: c.geo_source === 'approx' ? `${c.name} · yaklaşık konum (ilçe merkezi)` : c.name },
        c.logo ? h('img', { src: fileUrl(c.logo, 128), alt: '' }) : h('span', { class: 'um-coini' }, ini),
        h('span', { class: 'um-pin-name' }, (c.name || '').split(' ').slice(0, 2).join(' ')));
      const info = new maps.InfoWindow({ content: h('div', { class: 'um-info' }, h('b', null, c.name),
        c.address ? h('div', { class: 'small' }, c.address) : null,
        h('div', { class: 'small muted' }, `${c.geo_label || ''}${c.geo_source ? ` · ${c.geo_source === 'approx' ? 'yaklaşık' : c.geo_source}` : ''}`),
        h('a', { href: `${c.is_supplier ? '#/purchasing/suppliers' : '#/companies'}/${c.id}`, class: 'small' }, 'Firma kartı →'), ' · ',
        h('a', { href: `https://www.google.com/maps?q=${c.lat},${c.lng}`, target: '_blank', rel: 'noopener', class: 'small' }, 'Google Haritalar ↗')) });
      pin.addEventListener('click', () => { openInfo?.close(); info.setPosition(pos); info.open(map); openInfo = info; });
      const ov = new Overlay(pos, pin); ov.setMap(map); overlays.push(ov);
    }
    if (fit && list.length) { map.fitBounds(bounds, 70); if (list.length === 1) map.setZoom(14); }
  };
  q.addEventListener('input', () => draw(false));
  kind.addEventListener('change', () => draw(true));
  try { cos = await api.get('/api/companies/geo'); } catch (err) { toastError(err); return; }
  if (!cos.length) {
    mapBox.append(h('div', { class: 'um-empty' }, 'Konumu bulunan firma yok. Firma Yönetimi › "🌐 Konumları bul" ile başlatın.'));
  }
  draw(true);
}
