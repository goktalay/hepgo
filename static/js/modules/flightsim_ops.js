// Uçuş Simülatörü — Canlı Uçuş harekât paneli (static/ops) entegrasyonu (docs/ucus-simulatoru.md §14).
// Oturum ekranında 3B dünyanın yanında GÖKTUNGU harekât arayüzü bir iframe olarak açılır: /static/ops/index.html?sim=<oturum>.
// Panel kendi /ws/drone/live soketiyle hub'a bağlanır ({t:'watch', sim_id}); telemetri, komutlar (ARM/DISARM, mod, kalkış, RTL, iniş,
// hedefe git, rota yükle/başlat/durdur/iptal), ARM CHECK, konsol ve Cesium haritası Canlı Uçuş'takiyle birebir aynı kod yolundan çalışır.
// Bu modül yalnız yerleşimi yönetir: iframe, "Sade görünüm" anahtarı (panel kapalı → eski HUD + alt çubuk komutları), FPV kamerasında
// panelin gizlenmesi (.fs-fpv; askeri HUD kalır) ve iframe → parent gezinme mesajı ({t:'ops-nav', hash}). Tercih localStorage fs.ops.on.
import { h } from '../ui.js';

const KEY = 'fs.ops.on';

export function createOpsPanel(stage, { sid, enabled = true } = {}) {
  const ver = (document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/) || [])[1] || '';
  const src = `/static/ops/index.html?sim=${encodeURIComponent(sid)}${ver ? `&v=${encodeURIComponent(ver)}` : ''}`;
  let on = enabled && (localStorage.getItem(KEY) ?? '1') !== '0';
  const frame = h('iframe', { class: 'fs-ops-frame', src: on ? src : 'about:blank', allow: 'geolocation', title: 'Harekât paneli' });
  stage.append(frame);
  const apply = () => {
    stage.classList.toggle('fs-ops', on);
    frame.hidden = !on;
    if (on && frame.getAttribute('src') !== src) frame.setAttribute('src', src);   // ilk açılışta yüklenir; kapatınca soket kapanmasın diye yüklü kalır
  };
  apply();
  const onMsg = e => {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || !e.data || typeof e.data !== 'object') return;
    if (e.data.t === 'ops-nav' && typeof e.data.hash === 'string' && e.data.hash.startsWith('#/')) location.hash = e.data.hash;
  };
  window.addEventListener('message', onMsg);
  return {
    el: frame,
    get enabled() { return on; },
    toggle(v) { on = v == null ? !on : !!v; try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* */ } apply(); return on; },
    setFpv(fpv) { stage.classList.toggle('fs-fpv', !!fpv); },   // Dron kamerası: panel gizli, 3B tam alan; askeri HUD aynen
    dispose() { window.removeEventListener('message', onMsg); frame.remove(); stage.classList.remove('fs-ops', 'fs-fpv'); },
  };
}
