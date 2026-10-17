// Uçuş Simülatörü — Canlı Uçuş harekât paneli (static/ops) entegrasyonu (docs/ucus-simulatoru.md §14).
// Oturum ekranında GÖKTUNGU harekât arayüzünün öğeleri (dron kartı: başlık rozetleri + PFD + telemetri karoları + İŞLEMLER; konsol) 3B dünyanın
// ÜSTÜNDE yüzen kartlar olarak durur — ayrı bir kutu/pencere YOKTUR. Teknik olarak /static/ops/index.html?sim=<oturum> iframe'i 3B tuvalin
// tamamını kaplar ve tamamen şeffaftır (iç belge de şeffaf: hepgo.css html[data-hepgo-sim]); yalnız kartlar görünür.
// Fare/tekerlek: iframe normalde pointer-events:none'dır → OrbitControls (döndürme/yakınlaştırma) çalışır. Her pointermove/pointerdown'da
// imlecin altındaki iframe öğesi sorulur (same-origin elementFromPoint); görünür bir öğe (kart, konsol, popup, toast) varsa .fs-ops-hit ile
// iframe olayları alır; iframe boş alanda (html/body/harita kabı) olayı görünce sınıfı kendisi kaldırır (hepgo_sim.js), sürükleme sırasında
// kaldırmaz. Klavye: iframe'e tıklanınca odak üst pencereye geri alınır (ops-focus) ve iframe'de yakalanan tuşlar (form alanı değilse)
// sentetik KeyboardEvent olarak buraya iletilir → 1–4, H, P, WASD ve sanal kumanda tuşları bozulmaz.
// Panel kendi /ws/drone/live soketiyle hub'a bağlanır ({t:'watch', sim_id}); telemetri, komutlar, ARM CHECK ve konsol Canlı Uçuş'takiyle
// birebir aynı kod yolundan çalışır. Bu modül yalnız yerleşimi yönetir: iframe, göster/gizle (alt çubuk "Panel" düğmesi, P tuşu; gizli = sade
// görünüm: eski HUD + alt çubuk komutları), FPV'de gizleme (.fs-fpv; askeri HUD kalır), alt çubuk yüksekliği (--fs-bar-h) ve konsol üst kenarı
// (--fs-con-h; olay şeridi onun üstüne çıkar), iframe'e sanal kumanda durumu ({t:'fs-state', rc}), iframe → parent mesajları
// ({t:'ops-nav', hash} gezinme · {t:'ops-layout', con} konsol kenarı · {t:'ops-focus'} odak · {t:'ops-hit', hit} olay kapısı). Tercih localStorage fs.ops.on.
import { h, t as tr } from '../ui.js';

const KEY = 'fs.ops.on';
const EMPTY_IDS = new Set(['anaAlan', 'haritaAlan', 'cesiumContainer', 'hepgoGizliCapalar']);   // iframe'de "boş alan" sayılan kaplar

export function createOpsPanel(stage, { sid, enabled = true, onToggle = null } = {}) {
  const ver = (document.querySelector('script[src*="app.js"]')?.src.match(/[?&]v=([^&]+)/) || [])[1] || '';
  const src = `/static/ops/index.html?sim=${encodeURIComponent(sid)}${ver ? `&v=${encodeURIComponent(ver)}` : ''}`;
  let on = enabled && (localStorage.getItem(KEY) ?? '1') !== '0';
  const frame = h('iframe', { class: 'fs-ops-frame', src: on ? src : 'about:blank', allow: 'geolocation', title: tr('Harekât paneli') });
  frame.id = 'fs-ops-frame';
  if (!stage.hasAttribute('tabindex')) stage.setAttribute('tabindex', '-1');   // odağı iframe'den geri almak için programatik odaklanabilir
  stage.classList.add('fs-ops-host');
  stage.append(frame);
  const fpv = () => stage.classList.contains('fs-fpv');
  const apply = () => {
    stage.classList.toggle('fs-ops', on);
    if (!on) frame.classList.remove('fs-ops-hit');
    if (on && frame.getAttribute('src') !== src) frame.setAttribute('src', src);   // ilk açılışta yüklenir; gizleyince soket kapanmasın diye yüklü kalır
  };
  apply();
  // Alt çubuk yüksekliği katmanın alt sınırı (çubuk sarınca yüksekliği değişir)
  const bar = stage.querySelector('.fs-bar');
  const setBarH = () => { if (bar) stage.style.setProperty('--fs-bar-h', `${bar.offsetHeight || 54}px`); };
  const ro = bar && typeof ResizeObserver === 'function' ? new ResizeObserver(setBarH) : null;
  ro?.observe(bar);
  setBarH();
  // İmlecin altında iframe'in görünür bir öğesi var mı? (iframe pointer-events:none iken olaylar buraya gelir; same-origin belgeye bakılır)
  const hitAt = (x, y) => {
    let d;
    try { d = frame.contentDocument; } catch { return false; }
    if (!d || !d.body) return false;
    const r = frame.getBoundingClientRect();
    if (x < r.left || y < r.top || x >= r.right || y >= r.bottom) return false;
    const el = d.elementFromPoint(x - r.left, y - r.top);
    return !!el && el !== d.documentElement && el !== d.body && !EMPTY_IDS.has(el.id);
  };
  const onPointer = e => {
    if (!on || fpv() || frame.classList.contains('fs-ops-hit')) return;
    if (hitAt(e.clientX, e.clientY)) frame.classList.add('fs-ops-hit');
  };
  // Sanal kumanda durumu iframe'e: konsol kutusu ipucu şeridinin/çubukların üstüne çıkar, kart kısalır (hepgo.css html[data-fs-rc])
  const postState = () => { try { frame.contentWindow?.postMessage({ t: 'fs-state', rc: stage.classList.contains('rc-on'), fpv: fpv(), on }, location.origin); } catch { /* */ } };
  const mo = typeof MutationObserver === 'function' ? new MutationObserver(postState) : null;
  mo?.observe(stage, { attributes: true, attributeFilter: ['class'] });
  frame.addEventListener('load', postState);
  const onMsg = e => {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || !e.data || typeof e.data !== 'object') return;
    const m = e.data;
    if (m.t === 'ops-nav' && typeof m.hash === 'string' && m.hash.startsWith('#/')) location.hash = m.hash;
    else if (m.t === 'ops-layout') stage.style.setProperty('--fs-con-h', `${Math.max(0, Math.round(Number(m.con) || 0))}px`);
    else if (m.t === 'ops-focus') { try { stage.focus({ preventScroll: true }); } catch { /* */ } }
    else if (m.t === 'ops-hit') frame.classList.toggle('fs-ops-hit', !!m.hit && on && !fpv());
  };
  // P tuşu: form alanlarında ve değiştirici tuşlarla değil; FPV'de kartlar zaten gizli (tuş yine tercihi değiştirir)
  const editable = el => el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
  const onKey = e => {
    if (e.ctrlKey || e.metaKey || e.altKey || editable(document.activeElement)) return;
    if (e.key === 'p' || e.key === 'P') { api.toggle(); e.preventDefault(); }
  };
  window.addEventListener('message', onMsg);
  window.addEventListener('keydown', onKey);
  stage.addEventListener('pointermove', onPointer, true);
  stage.addEventListener('pointerdown', onPointer, true);
  const api = {
    el: frame,
    get enabled() { return on; },
    toggle(v) { on = v == null ? !on : !!v; try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* */ } apply(); postState(); onToggle?.(on); return on; },
    setFpv(v) { stage.classList.toggle('fs-fpv', !!v); if (v) frame.classList.remove('fs-ops-hit'); },   // Dron kamerası: kartlar gizli, 3B tam alan; askeri HUD aynen
    hitAt,
    dispose() {
      window.removeEventListener('message', onMsg); window.removeEventListener('keydown', onKey);
      stage.removeEventListener('pointermove', onPointer, true); stage.removeEventListener('pointerdown', onPointer, true);
      ro?.disconnect(); mo?.disconnect(); frame.remove(); stage.classList.remove('fs-ops', 'fs-ops-host', 'fs-fpv');
    },
  };
  return api;
}
