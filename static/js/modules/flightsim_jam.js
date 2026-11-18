// Uçuş Simülatörü — KARIŞTIRMA (docs/ucus-simulatoru.md §48; yalnız HEPGO oturum ekranı, ArduPilot oturumları). Alt bantta "Karıştırma" düğmesi;
// basınca düğmenin üstünde yukarı açılan panel: GPS karıştırma seviyesi (Kapalı / Hafif / Ağır / Tam), GPS aldatma (aç/kapa + sürükleme yönü ° +
// hız m/s + azami sapma m), süre (sn; 0 = elle kapatılana kadar) ve Başlat / Uygula / Durdur. Etkinken düğme kırmızı yanıp söner ve sahnenin üstünde
// "KARIŞTIRMA" bandı görünür (seviye · sahte konum sapması · seyrüsefer hatası · kalan süre). Benzetim SUNUCUDADIR (app/flightsim_jam.py: SITL'in
// SIM_GPS1_* parametreleri; ekranda araç GERÇEK konumunda çizilir, otopilotun sandığı konum tele.nav_lat / nav_lon) — ön yüz yalnız `jam` komutunu
// yollar ve `{t:'jam', reason, …durum}` çerçeveleri ile tele.jam / tele.nav_err alanlarını gösterir. Olay şeridi metinleri sunucudan gelir.
// Tercih kalıcı (localStorage fs.jam). Düğme yalnız session.jam.supported iken oluşturulur (PX4 / SIMUMAV oturumlarında yok).
// Saf katman (node testi tests/test_flightsim_jam.mjs): JAM_TEXTS, makeJamT, GPS_LEVELS, LIMITS, DEFAULT_CFG, normalizeCfg, isActive, cmdBody,
//   cfgText, jamBtnKey, bannerText, mergeTele, jamReportLines.
// createJam({ tr, keyed, cmd(name, params) → Promise, onEvent(text, sev), session, stage, storage }) →
//   { el, banner, update(tele), onFrame(m), open(), close(), isOpen, dispose(), get state }  ·  jamSection(sum, tr, h) → rapor bölümü (flightsim_report.js)

export const GPS_LEVELS = ['off', 'light', 'heavy', 'full'];
export const LIMITS = { dir: [0, 360], speed: [0, 50], max_m: [1, 5000], dur_s: [0, 3600] };
export const DEFAULT_CFG = { gps: 'off', spoof: { on: false, dir: 90, speed: 2, max_m: 200 }, dur_s: 0 };

export const JAM_TEXTS = [
  ['jam.title', 'Karıştırma'],
  ['jam.title_t', 'Karıştırma: GPS karıştırma (jamming) ve GPS aldatma (spoofing) etkisini simülasyonda dener'],
  ['jam.btn_t', 'Karıştırma: GPS karıştırma seviyesi, GPS aldatma (yön, hız, azami sapma) ve süre ayarı; başlat / durdur'],
  ['jam.gps', 'GPS karıştırma'], ['jam.off', 'Kapalı'], ['jam.light', 'Hafif'], ['jam.heavy', 'Ağır'], ['jam.full', 'Tam'],
  ['jam.off_t', 'GPS karıştırma yok'],
  ['jam.light_t', 'Hafif: uydu sayısı düşer, konum gürültülenir; uçuş sürer'],
  ['jam.heavy_t', 'Ağır: GPS kilidi aralıklı kaybolur, konum savrulur; otopilot arıza korumasına (iniş) geçebilir'],
  ['jam.full_t', 'Tam: GPS sinyali yok; otopilot konumunu yitirir, arıza koruması devreye girer'],
  ['jam.spoof', 'GPS aldatma'],
  ['jam.spoof_t', 'GPS aldatma: alıcıya sahte konum verilir; otopilot kendini sürüklenen konumda sanar, araç gerçekte ters yöne kayar'],
  ['jam.dir', 'Sürükleme yönü'], ['jam.dir_t', 'Sahte konumun sürüklendiği yön (°; 0 = kuzey, 90 = doğu)'],
  ['jam.speed', 'Sürükleme hızı'], ['jam.speed_t', 'Sürükleme hızı (m/s; 0 = anında sıçrama)'],
  ['jam.max', 'Azami sapma'], ['jam.max_t', 'Sahte konumun gerçek konumdan en çok uzaklaşacağı mesafe (m)'],
  ['jam.dur', 'Süre'], ['jam.dur_t', 'Süre (sn; 0 = elle kapatılana kadar)'], ['jam.forever', 'süresiz'], ['jam.sec', 'sn'],
  ['jam.start', 'Başlat'], ['jam.apply', 'Uygula'], ['jam.stop', 'Durdur'], ['jam.close', 'Kapat'],
  ['jam.active', 'Karıştırılıyor'], ['jam.recovering', 'Toparlanıyor'],
  ['jam.fake_note', 'Bu oturum SITL\'siz çalışıyor: yalnız göstergeler etkilenir'],
  ['jam.nothing', 'Önce bir GPS karıştırma seviyesi seçin ya da GPS aldatmayı açın'],
  ['jam.banner', 'KARIŞTIRMA'], ['jam.b_spoof', 'GPS ALDATMA'], ['jam.b_recover', 'GPS TOPARLANIYOR'],
  ['jam.b_light', 'GPS ZAYIF'], ['jam.b_heavy', 'GPS KESİNTİLİ'], ['jam.b_full', 'GPS YOK'],
  ['jam.b_off', 'sahte konum sapması {m} m'], ['jam.b_err', 'seyrüsefer hatası {m} m'], ['jam.b_left', 'kalan {s} sn'],
  ['jam.b_fake', 'yalnız göstergeler'],
  ['jam.ev_settled', 'GPS toparlandı — seyrüsefer gerçek konuma döndü'],
  ['jam.err', 'Karıştırma: {e}'],
];
const TXT = Object.fromEntries(JAM_TEXTS);
const fill = (s, p) => (p ? String(s).replace(/\{(\w+)\}/g, (m, k) => (p[k] != null ? String(p[k]) : m)) : String(s));
/** HEPGO (keyed=false) Türkçe metni anahtar verir; keyed=true ise `jam.*` anahtarını, yoksa Türkçe. */
export const makeJamT = (tr, keyed = false) => (k, p) => {
  const tx = TXT[k] ?? k;
  if (!tr) return fill(tx, p);
  if (!keyed) return tr(tx, p);
  const r = tr(k, p);
  return r && r !== k ? r : fill(tx, p);
};

const clampNum = (v, [a, b], d, step = 1) => {
  const n = Number(v);
  if (v === '' || v == null || !Number.isFinite(n)) return d;
  return Math.min(b, Math.max(a, Math.round(n / step) * step));
};
/** Ayar sözlüğü → sunucu sınırlarına kırpılmış {gps, spoof: {on, dir, speed, max_m}, dur_s}. */
export function normalizeCfg(c = {}) {
  const sp = c?.spoof || {}, d = DEFAULT_CFG.spoof;
  return {
    gps: GPS_LEVELS.includes(c?.gps) ? c.gps : 'off',
    spoof: { on: !!sp.on, dir: clampNum(sp.dir, LIMITS.dir, d.dir) % 360, speed: Number(clampNum(sp.speed, LIMITS.speed, d.speed, 0.1).toFixed(1)),
      max_m: clampNum(sp.max_m, LIMITS.max_m, d.max_m) },
    dur_s: clampNum(c?.dur_s, LIMITS.dur_s, 0),
  };
}
export const isActive = c => !!c && (c.gps !== 'off' && c.gps != null || !!c.spoof?.on);
/** `jam` komutunun gövdesi (etkin olmayan ayar → null: gönderilmez). */
export function cmdBody(c) {
  const n = normalizeCfg(c);
  return isActive(n) ? { gps: n.gps, spoof: { ...n.spoof }, dur_s: n.dur_s } : null;
}
const f1 = v => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(1));
const f0 = v => (v == null || !Number.isFinite(Number(v)) ? '—' : String(Math.round(Number(v))));
/** Kısa ayar metni: "GPS karıştırma: Ağır · GPS aldatma 90° · 2 m/s · 200 m · 30 sn". */
export function cfgText(c, T = k => TXT[k] ?? k) {
  const n = normalizeCfg(c), p = [];
  if (n.gps !== 'off') p.push(`${T('jam.gps')}: ${T(`jam.${n.gps}`)}`);
  if (n.spoof.on) p.push(`${T('jam.spoof')} ${n.spoof.dir}° · ${n.spoof.speed} m/s · ${n.spoof.max_m} m`);
  if (p.length && n.dur_s) p.push(`${n.dur_s} ${T('jam.sec')}`);
  return p.join(' · ') || T('jam.off');
}
/** Alt bant düğmesinin metin anahtarı: boşta "Karıştırma", etkinken "Karıştırılıyor", kapandıktan sonra EKF toparlanırken "Toparlanıyor". */
export const jamBtnKey = st => (st?.on ? 'jam.active' : st?.real ? 'jam.recovering' : 'jam.title');
/** Sahne üstü bandı: {main, sub, recover} ya da null (band gizli). */
export function bannerText(st, T = (k, p) => fill(TXT[k] ?? k, p)) {
  if (!st?.supported) return null;
  const err = st.nav_err != null ? T('jam.b_err', { m: f1(st.nav_err) }) : null;
  if (!st.on) return st.real ? { main: T('jam.b_recover'), sub: err || '', recover: true } : null;
  const sp = st.spoof?.on, main = [T('jam.banner')];
  if (st.gps && st.gps !== 'off') main.push(T(`jam.b_${st.gps}`));
  if (sp) main.push(T('jam.b_spoof'));
  const sub = [sp ? T('jam.b_off', { m: f1(st.off_m) }) : null, st.sim === 'fake' ? T('jam.b_fake') : err, st.left_s != null ? T('jam.b_left', { s: Math.ceil(Number(st.left_s)) }) : null];
  return { main: main.join(' · '), sub: sub.filter(Boolean).join(' · '), recover: false };
}
/** Telemetriden canlı alanlar (tele.jam = {gps, spoof, off_m, left_s}; tele.nav_err) durum sözlüğüne işlenir. */
export function mergeTele(st, t) {
  if (!st?.supported || !t) return st;
  const j = t.jam, out = { ...st };
  if (j) { out.off_m = j.off_m ?? out.off_m; out.left_s = j.left_s ?? null; }
  if (st.on || st.real) out.nav_err = t.nav_err ?? (st.sim === 'fake' ? null : out.nav_err);
  return out;
}

const LEVEL_LABEL = { light: 'hafif', heavy: 'ağır', full: 'tam' };
/** Rapor metni satırı (paylaşım metni): oturumda karıştırma hiç açılmadıysa []. */
export function jamReportLines(sum, tr = fill) {
  const J = sum?.jam; if (!J?.count) return [];
  const p = [tr('{n} kez', { n: J.count })];
  const g = Object.entries(J.gps_s || {}).filter(([k, v]) => LEVEL_LABEL[k] && v > 0).map(([k, v]) => `${tr(LEVEL_LABEL[k])} ${f0(v)} ${tr('sn')}`);
  if (g.length) p.push(`${tr('GPS karıştırma')} ${g.join(', ')}`);
  if (J.spoof_s > 0) p.push(`${tr('GPS aldatma')} ${f0(J.spoof_s)} ${tr('sn')} (${tr('en büyük sapma')} ${f1(J.max_off_m)} m)`);
  if (J.sim === 'fake') p.push(tr('yalnız göstergeler'));
  else if (J.max_nav_err > 0) p.push(`${tr('en büyük seyrüsefer hatası')} ${f1(J.max_nav_err)} m`);
  return [`${tr('Karıştırma')}: ${p.join(' · ')}`];
}
/** Rapor bölümü (flightsim_report.js reportBody içinden; h = ui.js h). */
export function jamSection(sum, tr, h) {
  const J = sum?.jam; if (!J?.count) return null;
  ensureCss();
  const tile = (label, value, unit, cls = '') => h('div', { class: `fs-rp-tile ${cls}` }, h('b', null, value, unit ? h('i', null, unit) : null), h('span', null, label));
  const kv = (k, v) => h('div', { class: 'fs-rp-kv' }, h('span', null, k), h('b', null, v));
  const gs = J.gps_s || {}, gTot = Object.values(gs).reduce((a, v) => a + (Number(v) || 0), 0), fake = J.sim === 'fake';
  const lv = Object.entries(gs).filter(([k, v]) => LEVEL_LABEL[k] && v > 0).map(([k, v]) => `${tr(LEVEL_LABEL[k])} ${f0(v)} ${tr('sn')}`).join(' · ');
  return h('div', { class: 'fs-rp-sec fs-rp-jam' }, h('h4', null, '📡 ', tr('Karıştırma')),
    h('div', { class: 'fs-rp-tiles fs-rp-jam-tiles' },
      tile(tr('Karıştırma sayısı'), String(J.count), ''),
      tile(tr('GPS karıştırma süresi'), f0(gTot), tr('sn'), gTot > 0 ? 'orange' : ''),
      tile(tr('GPS aldatma süresi'), f0(J.spoof_s), tr('sn'), J.spoof_s > 0 ? 'orange' : ''),
      tile(tr('En büyük sahte konum sapması'), f1(J.max_off_m), 'm'),
      fake ? null : tile(tr('En büyük seyrüsefer hatası'), f1(J.max_nav_err), 'm', J.max_nav_err > 0 ? 'red' : '')),
    lv ? kv(tr('Seviye başına süre'), lv) : null,
    h('div', { class: 'small muted' }, fake ? tr('Bu oturum SITL\'siz çalıştı: karıştırma yalnız göstergeleri etkiledi')
      : tr('Seyrüsefer hatası: otopilotun sandığı konum ile aracın gerçek konumu arasındaki yatay mesafe')));
}

// ---------------- alt bant bileşeni ----------------
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const CSS = `
.fs-jam{display:inline-flex;align-items:center;position:relative}
.fs-jam-btn{display:inline-flex;align-items:center;gap:6px;font-weight:700}
.fs-jam-btn svg{flex:none;opacity:.9}
.fs-bar .fs-jam[data-state=on] .fs-jam-btn{background:#dc2626;border-color:#dc2626;color:#fff;animation:fs-jam-pulse 1s ease-in-out infinite}
.fs-bar .fs-jam[data-state=recover] .fs-jam-btn{background:#b45309;border-color:#b45309;color:#fff}
@keyframes fs-jam-pulse{0%,100%{background:#dc2626;box-shadow:0 0 0 0 rgba(239,68,68,.65)}50%{background:#7f1d1d;box-shadow:0 0 0 6px rgba(239,68,68,0)}}
@media (prefers-reduced-motion:reduce){.fs-bar .fs-jam .fs-jam-btn{animation:none!important}}
.fs-jam-pop{position:absolute;bottom:calc(100% + 10px);left:0;z-index:40;width:max-content;min-width:288px;max-width:min(92vw,360px);padding:10px 12px 12px;border-radius:12px;
  background:rgba(14,20,30,.97);color:#e6edf3;border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 44px rgba(0,0,0,.55);backdrop-filter:blur(6px);display:grid;gap:8px;font-size:12px}
.fs-jam-pop[hidden]{display:none}
.fs-jam-pop::after{content:'';position:absolute;left:var(--fs-jam-arrow,28px);bottom:-6px;width:10px;height:10px;background:inherit;border-right:1px solid rgba(255,255,255,.14);border-bottom:1px solid rgba(255,255,255,.14);transform:rotate(45deg)}
.fs-jam-pop h6{margin:0;display:flex;align-items:center;gap:8px;font:800 10.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;opacity:.8}
.fs-jam-pop h6 span{flex:1}
.fs-jam-pop .fs-jam-x{border:0;background:transparent;color:inherit;opacity:.7;cursor:pointer;font-size:16px;line-height:1;padding:0 2px}
.fs-jam-pop .fs-jam-x:hover{opacity:1}
.fs-jam-sec{display:grid;gap:6px;padding-top:8px;border-top:1px solid rgba(255,255,255,.1)}
.fs-jam-sec>b{font:700 12px/1.2 system-ui,sans-serif}
.fs-jam-seg{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.fs-jam-seg button{height:30px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);color:#e6edf3;font:600 12px/1 system-ui,sans-serif;cursor:pointer;padding:0 6px}
.fs-jam-seg button:hover{background:rgba(255,255,255,.13)}
.fs-jam-seg button[aria-pressed=true]{background:#1f6feb;border-color:#1f6feb;color:#fff}
.fs-jam-seg button[aria-pressed=true]:not([data-v=off]){background:#dc2626;border-color:#dc2626}
.fs-jam-hint{opacity:.7;font-size:11px;line-height:1.35;min-height:2.7em}
.fs-jam-sw{display:flex;align-items:center;gap:8px;cursor:pointer;font:700 12px/1.2 system-ui,sans-serif}
.fs-jam-sw input{width:16px;height:16px;accent-color:#dc2626;margin:0}
.fs-jam-row{display:grid;grid-template-columns:104px 1fr;align-items:center;gap:8px}
.fs-jam-row[hidden]{display:none}
.fs-jam-row>span{opacity:.75}
.fs-jam-row>div{display:flex;align-items:center;gap:6px;min-width:0}
.fs-jam-pop input[type=number]{height:30px;width:84px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.07);color:#e6edf3;font:600 12.5px/1 system-ui,sans-serif;padding:0 8px;min-width:0;text-align:right;font-variant-numeric:tabular-nums}
.fs-jam-pop i{font-style:normal;opacity:.6;font-size:11px}
.fs-jam-arrow{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;border:1px solid rgba(255,255,255,.2);opacity:1!important;font-size:13px!important;transition:transform .15s}
.fs-jam-live{font:700 12px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;color:#fca5a5}
.fs-jam-live[hidden],.fs-jam-note[hidden]{display:none}
.fs-jam-note{padding:6px 8px;border-radius:8px;background:rgba(245,158,11,.14);border:1px solid rgba(245,158,11,.4);color:#fde68a;font-size:11px;line-height:1.35}
.fs-jam-acts{display:flex;gap:6px}
.fs-jam-act{flex:1;height:34px;border-radius:9px;border:1px solid #1f6feb;background:#1f6feb;color:#fff;font:700 13px/1 system-ui,sans-serif;cursor:pointer}
.fs-jam-act:hover{filter:brightness(1.1)}
.fs-jam-act.stop{background:#dc2626;border-color:#dc2626}
.fs-jam-act[hidden]{display:none}
.fs-jam-act:disabled{opacity:.55;cursor:default}
.fs-bar:has(.fs-jam-pop:not([hidden])){z-index:9}
.fs-jam-banner{position:absolute;left:50%;top:104px;transform:translateX(-50%);z-index:8;pointer-events:none;display:flex;flex-direction:column;align-items:center;gap:2px;width:max-content;max-width:92%;text-align:center;
  padding:7px 16px;border-radius:10px;background:rgba(60,8,8,.86);border:1px solid rgba(248,113,113,.8);color:#fecaca;font:800 14px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.fs-jam-banner.recover{background:rgba(60,34,6,.86);border-color:rgba(251,191,36,.75);color:#fde68a}
.fs-jam-banner small{font:600 11px/1.2 system-ui,sans-serif;letter-spacing:0;color:#fee2e2}
.fs-jam-banner.recover small{color:#fef3c7}
.fs-jam-banner small:empty{display:none}
.fs-jam-banner[hidden]{display:none}
.fs-srv-banner:not([hidden])~.fs-jam-banner{top:156px}
@media (max-width:640px){.fs-jam-banner{font-size:11px;letter-spacing:.02em;padding:6px 10px;max-width:calc(100% - 16px)}.fs-jam-banner span,.fs-jam-banner small{max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.fs-stage.fs-mob-open:has(.fs-jam-pop:not([hidden])) .fs-nav{display:none!important}
.fs-rp-jam-tiles .fs-rp-tile.red b{color:#dc2626}
`;
function ensureCss() {
  if (typeof document === 'undefined' || document.getElementById('fs-jam-css')) return;
  const s = document.createElement('style'); s.id = 'fs-jam-css'; s.textContent = CSS; document.head.appendChild(s);
}

const PREF = 'fs.jam';
const readJson = (st, k) => { try { return JSON.parse(st?.getItem(k) || 'null'); } catch { return null; } };
// Yayın simgesi (anten + çapraz çizgi: bozulan sinyal); düğmede metnin solunda
const JAM_ICON_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 13v8"/><circle cx="12" cy="11" r="1.6"/><path d="M8.2 14.8a5.4 5.4 0 0 1 0-7.6M15.8 7.2a5.4 5.4 0 0 1 0 7.6M5.4 17.6a9.4 9.4 0 0 1 0-13.2M18.6 4.4a9.4 9.4 0 0 1 0 13.2"/><path d="M3 3l18 18"/></svg>';

// Alt bantta "Karıştırma" düğmesi; basınca düğmenin ÜSTÜNDE yukarı açılan panel. Etkinken ayarlar değiştirilebilir ("Uygula"); "Durdur" kapatır.
// Başlat / Uygula sonrası panel kapanır (durum sahne üstü bandında izlenir). Dışarı tıklama / Esc kapatır.
export function createJam({ tr, keyed = false, cmd, onEvent = () => {}, session = null, stage = null, storage = (typeof localStorage !== 'undefined' ? localStorage : null), btnClass = 'btn sm' } = {}) {
  ensureCss();
  const T = makeJamT(tr, keyed);
  let st = { supported: true, on: false, real: false, sim: 'sitl', off_m: 0, left_s: null, nav_err: null, ...(session?.jam || {}) };
  let cfg = normalizeCfg(st.on ? st : readJson(storage, PREF) || DEFAULT_CFG);   // sayfa yenilendi / ikinci izleyici: sunucudaki etkin ayar
  let busy = false;
  const keys = inp => inp.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });   // rakamlar kamera kısayollarına gitmesin
  const seg = el('div', { class: 'fs-jam-seg', role: 'group', 'aria-label': T('jam.gps') },
    GPS_LEVELS.map(v => el('button', { type: 'button', 'data-v': v, title: T(`jam.${v}_t`), onclick: e => { e.stopPropagation(); cfg.gps = v; save(); paint(); } }, T(`jam.${v}`))));
  const hint = el('div', { class: 'fs-jam-hint' });
  const spoofChk = el('input', { type: 'checkbox', class: 'fs-jam-spoof', onchange: () => { cfg.spoof.on = spoofChk.checked; save(); paint(); } });
  const num = (cls, lim, title, get, set, step = 1) => {
    const inp = el('input', { class: cls, type: 'number', min: lim[0], max: lim[1], step, title, 'aria-label': title,
      onchange: () => { set(inp.value); cfg = normalizeCfg(cfg); inp.value = String(get()); save(); paint(); } });
    keys(inp);
    return inp;
  };
  const dirInp = num('fs-jam-dir', LIMITS.dir, T('jam.dir_t'), () => cfg.spoof.dir, v => { cfg.spoof.dir = v; });
  const speedInp = num('fs-jam-speed', LIMITS.speed, T('jam.speed_t'), () => cfg.spoof.speed, v => { cfg.spoof.speed = v; }, 0.1);
  const maxInp = num('fs-jam-max', LIMITS.max_m, T('jam.max_t'), () => cfg.spoof.max_m, v => { cfg.spoof.max_m = v; });
  const durInp = num('fs-jam-dur', LIMITS.dur_s, T('jam.dur_t'), () => cfg.dur_s, v => { cfg.dur_s = v; });
  const arrow = el('i', { class: 'fs-jam-arrow', 'aria-hidden': 'true' }, '↑');
  const durNote = el('i');
  const row = (label, title, ...kids) => el('label', { class: 'fs-jam-row', title }, el('span', null, label), el('div', null, kids));
  const spoofRows = [row(T('jam.dir'), T('jam.dir_t'), dirInp, el('i', null, '°'), arrow), row(T('jam.speed'), T('jam.speed_t'), speedInp, el('i', null, 'm/s')),
    row(T('jam.max'), T('jam.max_t'), maxInp, el('i', null, 'm'))];
  const live = el('div', { class: 'fs-jam-live', hidden: true });
  const note = el('div', { class: 'fs-jam-note', hidden: st.sim !== 'fake' }, T('jam.fake_note'));
  const btnTxt = el('span', { class: 'fs-jam-btn-txt' }, T('jam.title'));
  const btnIco = el('span', { class: 'fs-jam-ico', 'aria-hidden': 'true' }); btnIco.innerHTML = JAM_ICON_SVG;
  const btn = el('button', { class: `${btnClass} fs-jam-btn`, type: 'button', title: T('jam.btn_t'), 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    onclick: e => { e.stopPropagation(); setOpen(pop.hidden); } }, btnIco, btnTxt);
  const startBtn = el('button', { class: 'fs-jam-act fs-jam-start', type: 'button', onclick: e => { e.stopPropagation(); send(true); } }, T('jam.start'));
  const stopBtn = el('button', { class: 'fs-jam-act stop fs-jam-stop', type: 'button', hidden: true, onclick: e => { e.stopPropagation(); send(false); } }, T('jam.stop'));
  const pop = el('div', { class: 'fs-jam-pop', role: 'dialog', 'aria-label': T('jam.title'), hidden: true },
    el('h6', null, btnIco.cloneNode(true), el('span', null, T('jam.title')), el('button', { class: 'fs-jam-x', type: 'button', title: T('jam.close'), 'aria-label': T('jam.close'), onclick: e => { e.stopPropagation(); setOpen(false); } }, '×')),
    note,
    el('div', { class: 'fs-jam-sec' }, el('b', null, T('jam.gps')), seg, hint),
    el('div', { class: 'fs-jam-sec' }, el('label', { class: 'fs-jam-sw', title: T('jam.spoof_t') }, spoofChk, T('jam.spoof')), spoofRows),
    el('div', { class: 'fs-jam-sec' }, row(T('jam.dur'), T('jam.dur_t'), durInp, el('i', null, T('jam.sec')), durNote), live),
    el('div', { class: 'fs-jam-acts' }, startBtn, stopBtn));
  const root = el('div', { class: 'pill-group fs-jam', title: T('jam.title_t'), 'data-state': 'off' }, btn, pop);
  pop.addEventListener('click', e => e.stopPropagation());
  // Panel taşmasın (dar ekran): açılınca görüntü alanına sığacak biçimde yatay kaydır; ok düğmenin ortasını gösterir
  function place() {
    pop.style.left = '0px';
    if (typeof window === 'undefined' || !pop.getBoundingClientRect) return;
    const r = pop.getBoundingClientRect(), W = window.innerWidth || document.documentElement.clientWidth || 0, b = btn.getBoundingClientRect();
    let dx = 0;
    if (r.right > W - 8) dx = W - 8 - r.right;
    if (r.left + dx < 8) dx = 8 - r.left;
    pop.style.left = `${Math.round(dx)}px`;
    pop.style.setProperty('--fs-jam-arrow', `${Math.round(Math.min(Math.max(b.left + b.width / 2 - (r.left + dx) - 5, 12), r.width - 22))}px`);
  }
  function setOpen(v) {
    pop.hidden = !v; btn.setAttribute('aria-expanded', v ? 'true' : 'false');
    if (v) { paint(); place(); }
  }
  const banner = el('div', { class: 'fs-jam-banner', role: 'status', hidden: true }, el('span'), el('small'));
  stage?.append(banner);
  function save() { try { storage?.setItem(PREF, JSON.stringify(normalizeCfg(cfg))); } catch { /* depolama kapalı */ } }
  async function send(on) {
    if (busy) return;
    cfg = normalizeCfg({ ...cfg, spoof: { ...cfg.spoof, dir: dirInp.value, speed: speedInp.value, max_m: maxInp.value }, dur_s: durInp.value });
    save();
    const body = on ? cmdBody(cfg) : { off: true };
    if (!body) { onEvent(T('jam.nothing'), 'warning'); paint(); return; }
    busy = true; paint();
    try {
      const r = await cmd('jam', body);
      const j = r?.jam || r?.result?.jam;
      if (j) st = { ...st, ...j };
      if (on) setOpen(false);   // başladı: panel kapanır, durum sahne üstü bandında
    } catch (e) { onEvent(T('jam.err', { e: e?.message || String(e) }), 'error'); }
    busy = false; paint();
  }
  function paint() {
    root.dataset.state = st.on ? 'on' : st.real ? 'recover' : 'off';
    const act = typeof document !== 'undefined' ? document.activeElement : null;   // yazılan değer telemetri boyamasıyla ezilmesin
    for (const b of seg.children) b.setAttribute('aria-pressed', b.dataset.v === cfg.gps ? 'true' : 'false');
    hint.textContent = T(`jam.${cfg.gps}_t`);
    spoofChk.checked = !!cfg.spoof.on;
    for (const r of spoofRows) r.hidden = !cfg.spoof.on;
    if (act !== dirInp) dirInp.value = String(cfg.spoof.dir);
    if (act !== speedInp) speedInp.value = String(cfg.spoof.speed);
    if (act !== maxInp) maxInp.value = String(cfg.spoof.max_m);
    if (act !== durInp) durInp.value = String(cfg.dur_s);
    arrow.style.transform = `rotate(${cfg.spoof.dir}deg)`;
    durNote.textContent = cfg.dur_s ? '' : T('jam.forever');
    btnTxt.textContent = T(jamBtnKey(st));
    btn.classList.toggle('on', !!st.on);
    btn.title = st.on ? `${T('jam.active')}: ${cfgText(st, T)}` : T('jam.btn_t');
    startBtn.textContent = T(st.on ? 'jam.apply' : 'jam.start');
    startBtn.disabled = busy; stopBtn.disabled = busy; stopBtn.hidden = !st.on;
    note.hidden = st.sim !== 'fake';
    const b = bannerText(st, T);
    banner.hidden = !b;
    banner.classList.toggle('recover', !!b?.recover);
    if (b) { banner.firstChild.textContent = b.main; banner.lastChild.textContent = b.sub; }
    live.hidden = !b;
    if (b) live.textContent = b.sub || b.main;
  }
  // Panel dışına tıklama / Esc kapatır (Esc yakalama evresinde: oturumdan çıkış kısayoluna gitmez)
  const onDoc = e => { if (!pop.hidden && !root.contains(e.target)) setOpen(false); };
  const onEsc = e => { if (e.key === 'Escape' && !pop.hidden) { setOpen(false); e.preventDefault(); e.stopPropagation(); } };
  if (typeof document !== 'undefined') document.addEventListener('pointerdown', onDoc, true);
  if (typeof window !== 'undefined') window.addEventListener('keydown', onEsc, true);
  paint();
  return {
    el: root, banner,
    get state() { return { ...st }; }, get cfg() { return normalizeCfg(cfg); },
    update(t) { if (!st.on && !st.real) return; const n = mergeTele(st, t); if (n !== st) { st = n; paint(); } },   // boştayken telemetriyle boyama yok
    /** WS `{t:'jam', reason, …durum}` çerçevesi (komut / süre doldu / sıfırla / EKF toparlandı). */
    onFrame(m) {
      const { t: _t, ts: _ts, reason, ...d } = m || {};
      st = { ...st, ...d };
      if (st.on && reason === 'cmd') cfg = normalizeCfg(st);   // başka izleyici / sekme ayarı değiştirdi: panel aynı ayarı göstersin
      if (reason === 'settled') onEvent(T('jam.ev_settled'), 'info');   // sunucu bu geçişte olay yollamaz
      paint();
      return st;
    },
    open: () => setOpen(true), close: () => setOpen(false), get isOpen() { return !pop.hidden; },
    dispose() { document.removeEventListener('pointerdown', onDoc, true); window.removeEventListener('keydown', onEsc, true); root.remove(); banner.remove(); },
  };
}
