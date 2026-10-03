// Kameralar (Sistem Yönetimi — yalnızca sistem yöneticisi, NVR entegrasyonu aktifse görünür):
// Kameralar (NVR kanalları/ONVIF), Yüz Tanıma (eğitim + olaylar) ve Tanımlanmayan Kişiler bir arada.
import { clear, h, moduleToolbar, pageHead, segmented } from '../ui.js';
import { renderCameras } from './cameras.js';
import { renderFaces } from './faces.js';
import { renderFaceRec } from './facerec.js';

const TABS = [['', 'Kameralar'], ['facerec', 'Yüz Tanıma'], ['unknown', 'Tanımlanmayan Kişiler']];

export async function render(view, params, ctx) {
  const tab = TABS.some(x => x[0] === params[0]) ? params[0] || '' : '';
  const nav = segmented(TABS, tab, v => { location.hash = v ? `#/cameras/${v}` : '#/cameras'; }, { tabs: true });
  const body = h('div');
  clear(view, pageHead('Kameralar', { back: '#/', sub: 'Kameralar, yüz tanıma ve tanımlanmayan kişiler', tabs: nav }),
    moduleToolbar(), body);
  if (tab === 'facerec') return renderFaceRec(body, ctx, params.slice(1));
  if (tab === 'unknown') return renderFaces(body, ctx);
  return renderCameras(body, ctx, params);   // Kameralar: alt sekmesini (İzleme/Liste) params[0]'dan okur
}
