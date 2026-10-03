// Google Haritalar yükleyici: anahtar Program Ayarları › Entegrasyonlar › Google Haritalar'dan gelir (/api/meta).
// Anahtar yoksa harita kullanan ekranlar kendi yedek görünümüne (ör. SVG rota) düşer.
import { api } from './api.js';

let _metaP = null;
async function mapsKey() {
  if (!_metaP) _metaP = api.get('/api/meta').catch(() => ({}));
  return (await _metaP).maps_key || '';
}

let _loadP = null;
// Google Maps JS API'yi bir kez yükler; google.maps döndürür. Anahtar yoksa null.
export async function loadMaps() {
  const key = await mapsKey();
  if (!key) return null;
  if (window.google?.maps) return window.google.maps;
  if (!_loadP) {
    _loadP = new Promise((resolve, reject) => {
      const cb = `__gmaps_${Date.now()}`;
      window[cb] = () => { resolve(window.google.maps); delete window[cb]; };
      const s = document.createElement('script');
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&callback=${cb}`;
      s.async = true;
      s.onerror = () => { reject(new Error('Google Haritalar yüklenemedi')); _loadP = null; };
      document.head.append(s);
    });
  }
  return _loadP;
}

export async function hasMapsKey() {
  return !!(await mapsKey());
}
