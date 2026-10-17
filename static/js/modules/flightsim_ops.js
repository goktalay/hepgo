// Uçuş Simülatörü — Canlı Uçuş harekât paneli (static/ops) entegrasyonu (docs/ucus-simulatoru.md §14).
// Oturum ekranında GÖKTUNGU harekât arayüzü 3B dünyanın ÜSTÜNDE, sağdan kayarak açılıp kapanan bir katman (iframe) olarak durur:
// /static/ops/index.html?sim=<oturum>. 3B tuval her zaman tam alanı kaplar; panel açıkken sağ ~440–520 px'i örter (alt çubuğa dek),
// kapalıyken yalnız sağ kenarda ince bir "PANEL" sekmesi kalır. Sim kipinde panel haritasız yüklenir (Cesium çekilmez; hepgo_nomap.js).
// Panel kendi /ws/drone/live soketiyle hub'a bağlanır ({t:'watch', sim_id}); telemetri, komutlar (ARM/DISARM, mod, kalkış, RTL, iniş,
// hedefe git, rota yükle/başlat/durdur/iptal), ARM CHECK ve konsol Canlı Uçuş'takiyle birebir aynı kod yolundan çalışır.
// Bu modül yalnız yerleşimi yönetir: iframe + sekme, aç/kapa (alt çubuk "Panel" düğmesi, sekme, P tuşu; kapalı = sade görünüm: eski HUD +
// alt çubuk komutları), FPV kamerasında panelin gizlenmesi (.fs-fpv; askeri HUD kalır), alt çubuk yüksekliğinin katmana aktarılması
// (--fs-bar-h) ve iframe → parent gezinme mesajı ({t:'ops-nav', hash}). Tercih localStorage fs.ops.on.
import { h, t as tr } from '../ui.js';

const KEY = 'fs.ops.on';

export function createOpsPanel(stage, { sid, enabled = true, onToggle = null } = {}) {
  const ver = (document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/) || [])[1] || '';
  const src = `/static/ops/index.html?sim=${encodeURIComponent(sid)}${ver ? `&v=${encodeURIComponent(ver)}` : ''}`;
  let on = enabled && (localStorage.getItem(KEY) ?? '1') !== '0';
  const frame = h('iframe', { class: 'fs-ops-frame', src: on ? src : 'about:blank', allow: 'geolocation', title: 'Harekât paneli' });
  const tab = h('button', { class: 'fs-ops-tab', type: 'button', title: tr('Harekât panelini aç/kapat (P)'), 'aria-controls': 'fs-ops-frame', onclick: () => api.toggle() },
    h('span', { class: 'fs-ops-tab-ico' }, '‹'), h('span', { class: 'fs-ops-tab-txt' }, 'PANEL'));
  frame.id = 'fs-ops-frame';
  stage.classList.add('fs-ops-host');
  stage.append(frame, tab);
  const apply = () => {
    stage.classList.toggle('fs-ops', on);
    tab.classList.toggle('on', on);
    tab.setAttribute('aria-expanded', on ? 'true' : 'false');
    tab.firstChild.textContent = on ? '›' : '‹';
    if (on && frame.getAttribute('src') !== src) frame.setAttribute('src', src);   // ilk açılışta yüklenir; kapatınca soket kapanmasın diye yüklü kalır
  };
  apply();
  // Alt çubuk yüksekliği katmanın alt sınırı (çubuk sarınca yüksekliği değişir)
  const bar = stage.querySelector('.fs-bar');
  const setBarH = () => { if (bar) stage.style.setProperty('--fs-bar-h', `${bar.offsetHeight || 54}px`); };
  const ro = bar && typeof ResizeObserver === 'function' ? new ResizeObserver(setBarH) : null;
  ro?.observe(bar);
  setBarH();
  const onMsg = e => {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || !e.data || typeof e.data !== 'object') return;
    if (e.data.t === 'ops-nav' && typeof e.data.hash === 'string' && e.data.hash.startsWith('#/')) location.hash = e.data.hash;
  };
  // P tuşu: form alanlarında ve değiştirici tuşlarla değil; FPV'de panel zaten gizli (tuş yine tercihi değiştirir)
  const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const onKey = e => {
    if (e.ctrlKey || e.metaKey || e.altKey || editable(document.activeElement)) return;
    if (e.key === 'p' || e.key === 'P') { api.toggle(); e.preventDefault(); }
  };
  window.addEventListener('message', onMsg);
  window.addEventListener('keydown', onKey);
  const api = {
    el: frame,
    get enabled() { return on; },
    toggle(v) { on = v == null ? !on : !!v; try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* */ } apply(); onToggle?.(on); return on; },
    setFpv(fpv) { stage.classList.toggle('fs-fpv', !!fpv); },   // Dron kamerası: panel ve sekme gizli, 3B tam alan; askeri HUD aynen
    dispose() { window.removeEventListener('message', onMsg); window.removeEventListener('keydown', onKey); ro?.disconnect(); frame.remove(); tab.remove(); stage.classList.remove('fs-ops', 'fs-ops-host', 'fs-fpv'); },
  };
  return api;
}
