// Ayarlar (kullanıcı menüsü): kişisel tercihler. Sunucuda kullanıcıya bağlı saklanır (users.prefs.settings) ve her cihazda
// aynı uygulanır. Bölümler: Arayüz, Bildirimler, Sesler, Gizlilik, Pano, Hesap. Değişiklik anında uygulanır ve kaydedilir.
import { api, getUploadCfg, setUploadCfg } from '../api.js';
import { applySettings, deviceNotify, setDeviceNotify, toolbarAlignOf } from '../prefs.js';
import { ANIMATIONS, createAnimPreview, showScreensaver } from '../screensaver.js';
import { DEFAULTS, EVENTS, SOUND_NAMES, playSound } from '../sounds.js';
import { segIconByKey } from '../segicons.js';
import { disablePush, enablePush, pushState, pushSupport } from '../push.js';
import { CALL_BACKGROUNDS, CALL_BG_LABELS } from './voice.js';
import { MASCOT_LIST, mascotLivePreview, previewMascotSound, setMascot, setMascot3D, setMascotSound, applyMascotHidden, has3d } from './mascot.js';
import { avatar, clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, segmented, t, toast, toastError } from '../ui.js';
import { setLang, getLang } from '../i18n.js';
import { mailboxesSection, socialSection } from './mysettings.js';
import { faceSection } from './facesetup.js';

// Mobilde (≤800px) Ayarlar iOS tarzı ana liste + alt-sayfa olur; görünüm genişliği değişince yeniden çizilir.
const SET_MQ = matchMedia('(max-width: 800px)');
let _setRedraw = null;
SET_MQ.addEventListener('change', () => { if (_setRedraw && location.hash.startsWith('#/settings')) _setRedraw(); });
let _notifSel = null;   // Bildirimler › seçili modül (yeniden çizimde korunur)

const CHECK_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const reducedMotion = () => document.documentElement.classList.contains('reduce-motion') || matchMedia('(prefers-reduced-motion: reduce)').matches;

// Görsel seçici (erişilebilir radio grubu): her seçenek önizlemeli bir kart. Ok tuşları / Home / End ile gezinilir ve seçilir,
// Boşluk / Enter seçer; seçili kart vurgulu + onay işaretli. options: [{ key, label, sub?, preview: () => Node, extra?: Node }]
function visualRadio(label, options, value, onChange, cls = '') {
  const grp = h('div', { class: `vr-grid ${cls}`.trim(), role: 'radiogroup', 'aria-label': label });
  let cur = String(value);
  const items = options.map(o => {
    const el = h('div', { class: 'vr-opt', role: 'radio', tabindex: '-1', 'data-k': String(o.key) },
      h('span', { class: 'vr-prev', 'aria-hidden': 'true' }, o.preview()),
      h('span', { class: 'vr-lbl' }, h('b', null, o.label), o.sub ? h('small', null, o.sub) : null),
      h('span', { class: 'vr-check', 'aria-hidden': 'true', html: CHECK_SVG }),
      o.extra || null);
    el.addEventListener('click', e => { if (!e.target.closest('.vr-extra')) pick(String(o.key)); });
    return el;
  });
  const sync = () => {
    const any = items.some(el => el.dataset.k === cur);
    items.forEach((el, i) => {
      const on = el.dataset.k === cur;
      el.classList.toggle('on', on);
      el.setAttribute('aria-checked', on ? 'true' : 'false');
      el.tabIndex = (on || (!any && i === 0)) ? 0 : -1;
    });
  };
  const pick = (k, focus) => {
    const el = items.find(x => x.dataset.k === k);
    if (focus) el?.focus();
    if (k === cur) return;
    cur = k; sync(); onChange(k, el);
  };
  grp.addEventListener('keydown', e => {
    const el = e.target.closest('.vr-opt');
    if (!el || e.target !== el) return;   // kart içindeki düğmeler (ör. "Sesini dinle") kendi tuşlarını kullanır
    const i = items.indexOf(el), n = items.length;
    const go = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: n - 1 }[e.key];
    if (go != null) { e.preventDefault(); pick(items[(go + n) % n].dataset.k, true); }
    else if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); pick(el.dataset.k); }
  });
  grp.append(...items);
  sync();
  return grp;
}

// Tema önizlemesi: mini pencere (başlık çubuğu, yan menü, kart) — sabit açık / koyu renklerle; "Sisteme göre" yarı yarıya
const themeWin = mode => h('span', { class: `thp-win thp-${mode}` },
  h('span', { class: 'thp-bar' }, h('i'), h('i'), h('i')),
  h('span', { class: 'thp-body' },
    h('span', { class: 'thp-side' }, h('i', { class: 'on' }), h('i'), h('i'), h('i')),
    h('span', { class: 'thp-main' },
      h('span', { class: 'thp-card' }, h('i', { class: 't' }), h('i'), h('i', { class: 's' }), h('em')),
      h('span', { class: 'thp-card' }, h('i', { class: 't' }), h('i', { class: 's' })))));
const themePreview = k => k === 'system' ? h('span', { class: 'thp-split' }, themeWin('light'), themeWin('dark'), h('span', { class: 'thp-sys' }, 'A')) : themeWin(k);
// Yazı / öğe boyutu önizlemesi: "Aa" + satır + düğme GERÇEK ölçekte (sayfanın mevcut ölçeği bölünerek)
const scalePreview = v => {
  const el = h('span', { class: 'sp-prev' }, h('span', { class: 'sp-top' }, h('span', { class: 'sp-aa' }, 'Aa'), h('span', { class: 'sp-btn' }, 'Kaydet')),
    h('span', { class: 'sp-row' }, h('span', { class: 'sp-txt' }, 'Örnek metin satırı')));
  el.style.setProperty('--s', String(v));
  return el;
};

export async function renderSettings(view, ctx, { changePassword, modules }, sub0) {
  let [sub, subQuery = ''] = (sub0 || '').split('?');   // OAuth dönüşü: #/settings/mailboxes?msg=…
  const cur = ctx.user.prefs?.settings || {};
  let theme0;
  try { theme0 = localStorage.getItem('caymaz.theme') || 'light'; } catch { theme0 = 'light'; }
  const s = {
    theme: cur.theme || theme0, scale: cur.scale || 1, compact: !!cur.compact, motion: !!cur.motion, start: cur.start || 'dashboard',
    lang: cur.lang || getLang() || 'tr',
    flash: cur.flash !== false, flashSec: cur.flashSec || 3, desktop: !!cur.desktop,
    sound: { on: true, volume: 0.7, map: {}, quiet: { on: false, from: '22:00', to: '08:00' }, ...(cur.sound || {}) },
    privacy: { hide_online: false, hide_read: false, hide_delivered: false, no_messages: false, share_location_web: true, ...(cur.privacy || {}) },
    screensaver: { on: false, after: 300, anim: 'globe', lock: true, ...(cur.screensaver || {}) },
    mascot: cur.mascot || 'kubbe',
    mascotStyle: cur.mascotStyle || 'samimi',
    mascotOff: !!cur.mascotOff,           // başka bir ayar kaydedilince gizli maskot geri gelmesin
    mascot3d: cur.mascot3d !== false,
    mascotSound: !!cur.mascotSound,       // "Maskot sesli": her maskotun kendi sesi (varsayılan kapalı; anahtar adı geriye uyumlu)
    dnd: { calls: false, messages: false, until: null, dur: 'always', ...(cur.dnd || {}) },   // dur: always | 1 | 2 | 4 | today | offhours
    muteNotif: Array.isArray(cur.muteNotif) ? cur.muteNotif : [],
    muteAlert: Array.isArray(cur.muteAlert) ? cur.muteAlert : [],
    toolbarAlign: toolbarAlignOf(cur),
    toolbarAlignSet: !!cur.toolbarAlignSet,   // hiza yeni düzende açıkça seçildi mi (eski örtük 'center' varsayılan sayılır)
    textCase: ['title', 'upper', 'lower'].includes(cur.textCase) ? cur.textCase : 'original',
    feedView: cur.feedView === 'map' ? 'map' : 'feed',
    feedFullMobile: !!cur.feedFullMobile,
    colors: (cur.colors && typeof cur.colors === 'object') ? { light: {}, dark: {}, ...cur.colors } : { light: {}, dark: {} },
    background: cur.background || '',
    location_work_hours_only: !!cur.location_work_hours_only,   // mobil: mesai dışında konumu kapat
    holiday: { on: true, country: '', scene3d: true, ...(cur.holiday || {}) },   // bayram temaları (static/js/holiday.js; varsayılan açık, ülke '' = otomatik; scene3d: uçuş sahnesinde 3B süs)
  };
  let timer;
  const save = (msg = 'Ayarlar kaydedildi') => {
    applySettings(s);
    try {   // giriş ekranı da aynı açılsın diye cihazda yansıt (tema/boyut gibi)
      localStorage.setItem('caymaz.toolbarAlign2', s.toolbarAlign || 'right');
      localStorage.setItem('caymaz.uiColors', JSON.stringify(s.colors || {}));
      localStorage.setItem('caymaz.uiBg', s.background || '');
    } catch { /* gizli pencere */ }
    ctx.user.prefs = { ...ctx.user.prefs, settings: s };
    clearTimeout(timer);
    timer = setTimeout(() => api.put('/api/auth/prefs/settings', s).then(() => toast(msg)).catch(() => toast('Kaydedilemedi', 'err')), 400);
  };
  const toggle = (obj, key, label, hint, after) => {
    const cb = h('input', { type: 'checkbox', checked: !!obj[key] });
    cb.addEventListener('change', async () => { obj[key] = cb.checked; if (after) await after(cb); save(); });
    return h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, label), hint ? h('small', null, hint) : null));
  };
  const line = (label, hint, control) => h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, label), hint ? h('small', null, hint) : null), control);
  // Başlık + açıklama üstte, geniş denetim (görsel seçici) altta
  const block = (label, hint, control) => h('div', { class: 'set-block' }, h('div', { class: 'set-block-h' }, h('b', null, label), hint ? h('small', null, hint) : null), control);
  const card = (title, sub, ...kids) => h('section', { class: 'card card-pad set-card' }, h('h3', null, title), sub ? h('p', { class: 'small muted' }, sub) : null, ...kids);

  // ---------- Arayüz
  const themeSeg = visualRadio('Tema', [
    { key: 'light', label: 'Açık', sub: 'Aydınlık ortam için', preview: () => themePreview('light') },
    { key: 'dark', label: 'Koyu', sub: 'Gece ve karanlık ortam', preview: () => themePreview('dark') },
    { key: 'system', label: 'Sisteme göre', sub: 'Cihazın ayarını izler', preview: () => themePreview('system') },
  ], s.theme, v => { s.theme = v; save(); }, 'vr-theme');
  // Dil: arayüz ve yazdırma şablonları seçilen dilde görünür. Şimdilik Türkçe + İngilizce.
  const langSeg = segmented([['tr', 'Türkçe'], ['en', 'English'], ['de', 'Deutsch'], ['fr', 'Français'], ['es', 'Español'], ['ar', 'العربية'], ['ru', 'Русский']], s.lang, v => { s.lang = v; setLang(v); save('Dil güncellendi'); });
  const scaleSeg = visualRadio('Yazı ve öğe boyutu', [['0.9', 'Küçük'], ['1', 'Normal'], ['1.1', 'Büyük'], ['1.25', 'Çok büyük']]
    .map(([k, l]) => ({ key: k, label: l, sub: `%${Math.round(Number(k) * 100)}`, preview: () => scalePreview(k) })),
    String(s.scale), v => { s.scale = Number(v); save(); }, 'vr-scale');
  const startSel = h('select', { class: 'input' }, h('option', { value: 'dashboard' }, 'Kişisel pano'),
    modules.map(m => h('option', { value: m.key, selected: s.start === m.key }, m.title)));
  startSel.addEventListener('change', () => { s.start = startSel.value; save(); });
  const textCaseSeg = segmented([['original', 'Orijinal'], ['title', 'Yazım Düzeni'], ['upper', 'Tamamı Büyük'], ['lower', 'Tamamı Küçük']],
    s.textCase, v => { s.textCase = v; save('Metin biçimi güncellendi'); });

  // ---------- Görünüm & Renkler (MERKEZİ: üst bar, alt bar, footer, zemin — aktif temaya göre; modül içeriğine dokunulmaz)
  const alignSeg = segmented([['left', 'Sol'], ['center', 'Orta'], ['right', 'Sağ']], s.toolbarAlign || 'right', v => { s.toolbarAlign = v; s.toolbarAlignSet = true; save(); });
  const themeKeyNow = () => (s.theme === 'dark' || (s.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)) ? 'dark' : 'light';
  const DEFAULT_COLORS = {
    light: { header: '#edf0f5', band: '#f1f3f7', footer: '#ffffff', bg: '#f8f9fb', accent: '#1d4f91' },
    dark: { header: '#0b0f16', band: '#0d1118', footer: '#171e29', bg: '#0f141c', accent: '#4a8ae0' },
  };
  const COLOR_DEFS = [
    ['header', 'Üst bar', 'En üstteki logo/menü şeridi', true],
    ['band', 'Başlık bandı (alt bar)', 'Sayfa başlığının olduğu şerit', true],
    ['footer', 'Alt bilgi (footer)', 'En alttaki bilgi şeridi', true],
    ['bg', 'Sayfa zemini', 'İçerik alanının arka plan rengi', false],
    ['accent', 'Vurgu rengi', 'Düğmeler, bağlantılar ve seçili öğeler', false],
  ];
  const BG_PRESETS = [['', 'Yok'], ['soft', 'Yumuşak'], ['mesh', 'Mesh'], ['aurora', 'Aurora ✦'], ['waves', 'Dalga ✦'], ['dots', 'Nokta'], ['grid', 'Izgara']];
  function appearanceBody() {
    const tk = themeKeyNow();
    s.colors[tk] = s.colors[tk] || {};
    const resets = [];
    const rows = COLOR_DEFS.map(([key, label, hint, allowNone]) => {
      const cur0 = s.colors[tk][key];
      const def = DEFAULT_COLORS[tk][key];
      const none0 = cur0 === 'var(--bg)';
      const inp = h('input', { type: 'color', class: 'set-color', value: (cur0 && !none0) ? cur0 : def, disabled: none0 });
      inp.addEventListener('input', () => { s.colors[tk][key] = inp.value; save(); });
      let noneCb = null;
      if (allowNone) {
        noneCb = h('input', { type: 'checkbox', checked: none0 });
        noneCb.addEventListener('change', () => { if (noneCb.checked) { s.colors[tk][key] = 'var(--bg)'; inp.disabled = true; } else { delete s.colors[tk][key]; inp.disabled = false; } save(); });
      }
      resets.push(() => { delete s.colors[tk][key]; inp.value = def; inp.disabled = false; if (noneCb) noneCb.checked = false; });
      return h('div', { class: 'set-row' },
        h('div', { class: 'grow' }, h('b', null, label), hint ? h('small', null, hint) : null),
        h('div', { class: 'set-color-ctl' },
          allowNone ? h('label', { class: 'set-none' }, noneCb, 'Renksiz') : null, inp,
          h('button', { class: 'btn xs ghost', type: 'button', title: 'Varsayılan', onclick: () => { delete s.colors[tk][key]; inp.value = def; inp.disabled = false; if (noneCb) noneCb.checked = false; save(); } }, '↺')));
    });
    const bgGrid = h('div', { class: 'set-bg-grid' }, BG_PRESETS.map(([key, name]) => {
      const tile = h('button', { class: `set-bg-tile ${s.background === key ? 'on' : ''}`, type: 'button', 'data-p': key, title: name },
        h('span', { class: 'set-bg-name' }, name));
      tile.addEventListener('click', () => { s.background = key; save(); bgGrid.querySelectorAll('.set-bg-tile').forEach(t => t.classList.toggle('on', t.getAttribute('data-p') === key)); });
      return tile;
    }));
    const resetAll = h('button', { class: 'btn sm', type: 'button', onclick: () => { resets.forEach(f => f()); save('Renkler sıfırlandı'); } }, t('{theme} tema renklerini sıfırla', { theme: tk === 'dark' ? 'Koyu' : 'Açık' }));
    return card('Görünüm & Renkler',
      t('Renkler yalnızca ŞU AN AKTİF temayı ({theme}) etkiler. Diğer temayı düzenlemek için temayı değiştirip bu sayfaya dönün. Değişiklikler merkezidir; modüllerin kendi içeriğine dokunmaz.', { theme: tk === 'dark' ? 'Koyu' : 'Açık' }),
      line('Araç çubuğu hizası', 'Alt-modül işlem düğmelerinin (toolbar) yatay konumu', alignSeg),
      h('h4', { class: 'set-sub' }, 'Merkezi renkler'),
      ...rows,
      h('h4', { class: 'set-sub' }, 'Gövde arka planı'),
      h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Orta alana yumuşak bir desen. “✦” işaretliler hareketlidir (Hareketleri azalt açıksa durur).'),
      bgGrid,
      h('div', { class: 'set-actions' }, resetAll));
  }

  // ---------- Bayram temaları (docs/bayram-temalari.md): aç/kapa + ülke (Otomatik / liste) + Sistem Yöneticisi / MASTER için önizleme
  function holidayBody() {
    const wrap = h('div', null, card('Bayram temaları', null, h('div', { class: 'loading' }, 'Yükleniyor…')));
    const isAdmin = ctx.user.master || (ctx.user.roles || []).includes('Sistem Yöneticisi');
    Promise.all([import('../holiday.js'), import('./holiday_fx.js')]).then(async ([hm, fx]) => {
      let st = hm.holidayState();
      if (!st.me) { await hm.refreshHoliday(); st = hm.holidayState(); }
      const L = getLang() || 'tr';
      const refresh = () => hm.refreshHoliday();
      const codes = (st.me?.countries || []).map(c => [c, fx.countryName(c, L)]).sort((a, b) => a[1].localeCompare(b[1], L));
      const auto = st.me?.located || (st.detected?.source && st.detected.source !== 'setting' ? st.detected.country : fx.detectCountry({}).country);
      const SRC = { address: 'adresinizden', company: 'firma adreslerinden', timezone: 'saat diliminizden', language: 'tarayıcı dilinden', location: 'konumdan' };
      const autoSrc = st.me?.located ? SRC[st.me.located_source] || SRC.location : (st.detected?.source && st.detected.source !== 'setting' ? SRC[st.detected.source] : SRC.timezone);
      const sel = h('select', { class: 'input', 'aria-label': 'Ülke' },
        h('option', { value: '' }, auto ? t('Otomatik — {c} ({src})', { c: fx.countryName(auto, L), src: t(autoSrc) }) : 'Otomatik'),
        codes.map(([c, n]) => h('option', { value: c, selected: c === s.holiday.country }, n)));
      sel.addEventListener('change', () => { s.holiday.country = sel.value; save('Bayram ülkesi güncellendi'); refresh(); });
      const cb = h('input', { type: 'checkbox', checked: s.holiday.on !== false });
      const cb3 = h('input', { type: 'checkbox', checked: s.holiday.scene3d !== false, disabled: s.holiday.on === false });   // uçuş sahnesi 3B süsleri (flightsim_holiday3d.js)
      cb.addEventListener('change', () => { s.holiday.on = cb.checked; cb3.disabled = !cb.checked; save(cb.checked ? 'Bayram temaları açıldı' : 'Bayram temaları kapatıldı'); refresh(); });
      cb3.addEventListener('change', () => { s.holiday.scene3d = cb3.checked; save(cb3.checked ? 'Uçuş sahnesi bayram süsleri açıldı' : 'Uçuş sahnesi bayram süsleri kapatıldı'); });
      const cur0 = st.picked?.primary, nx = st.info?.next;
      const status = [cur0 && !cur0.preview ? t('Bugün: {n}', { n: cur0.name || fx.themeName(cur0.theme, L) }) : 'Bugün etkin bir bayram yok',
        nx ? t('Sıradaki: {n} · {d} gün sonra', { n: nx.name || fx.themeName(nx.theme, L), d: nx.in_days }) : null].filter(Boolean).join(' · ');
      let pvRow = null;
      if (isAdmin) {
        const pv = h('select', { class: 'input', 'aria-label': 'Temayı önizle' }, fx.THEMES.map(code => h('option', { value: code }, fx.themeName(code, L))));
        const go = h('button', { class: 'btn', type: 'button', onclick: () => {
          location.hash = '#/';
          setTimeout(() => hm.refreshHoliday({ preview: { themes: [pv.value], country: s.holiday.country || auto || null } }), 300);
        } }, 'Panoda önizle');
        pvRow = line('Temayı önizle', '20 temayı tarih beklemeden panoda görün (yalnız bu ekranda; kaydedilmez). Adres çubuğuna /?bayram=<tema> da yazılabilir.', h('div', { class: 'set-color-ctl' }, pv, go));
      }
      clear(wrap, card('Bayram temaları', 'Bayram ve resmî tatil günlerinde panoda hafif kutlama efektleri ve günde bir kez kutlama şeridi. Diğer sayfalarda ve Uçuş Simülatörü açıkken görünmez; “Hareketleri azalt” açıksa yalnız durağan köşe süsü çizilir.',
        h('label', { class: 'set-toggle' }, cb, h('span', null, h('b', null, 'Bayram temaları açık'), h('small', null, 'Kapatırsanız hiçbir bayram süslemesi gösterilmez'))),
        h('label', { class: 'set-toggle' }, cb3, h('span', null, h('b', null, 'Uçuş sahnesinde bayram süsleri'), h('small', null, 'Uçuşta ekran efekti gösterilmez; onun yerine 3B dünyada uçuşu engellemeyen süsler (koyunlar, fenerler, bayraklar …)'))),
        line('Ülke', 'Otomatik: girdiğiniz adres ya da firma konumu, yoksa saat diliminiz ve tarayıcı diliniz. Konum için internete sorgu yapılmaz.', sel),
        h('p', { class: 'small muted' }, status),
        pvRow,
        h('p', { class: 'small muted' }, 'Hicri takvime bağlı bayram tarihleri tahminidir; ülkeye göre bir gün kayabilir.')));
    }).catch(e => clear(wrap, h('div', { class: 'card empty' }, e.message)));
    return wrap;
  }

  // ---------- Bildirimler
  const flashSel = h('select', { class: 'input' }, [3, 5, 8, 12].map(n => h('option', { value: n, selected: s.flashSec === n }, t('{n} saniye', { n }))));
  flashSel.addEventListener('change', () => { s.flashSec = Number(flashSel.value); save(); });
  const deskState = h('small', { class: 'set-state' });
  const syncDesk = () => {
    const p = 'Notification' in window ? Notification.permission : 'unsupported';
    deskState.textContent = p === 'granted' ? '✓ Bu cihazda tarayıcı izni verildi' : p === 'denied' ? '✕ Bu cihazda izin reddedilmiş (tarayıcı ayarlarından açın)'
      : p === 'unsupported' ? 'Bu tarayıcı desteklemiyor' : 'Açınca bu cihazdan izin istenecek';
  };
  syncDesk();
  // Masaüstü bildirimi CİHAZ-BAZLI (localStorage): her cihazda ayrı açılır, o cihazın tarayıcı izni gerekir.
  const dcb = h('input', { type: 'checkbox', checked: deviceNotify() });
  dcb.addEventListener('change', async () => {
    if (dcb.checked) {
      if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission();
      if (!('Notification' in window) || Notification.permission !== 'granted') { dcb.checked = false; syncDesk(); toast('Bu cihazda tarayıcı bildirim izni verilmedi', 'err'); return; }
    }
    setDeviceNotify(dcb.checked); syncDesk();
    if (dcb.checked) toast('Bu cihazda masaüstü bildirimi açıldı');
  });
  const deviceDesk = h('label', { class: 'set-toggle' }, dcb, h('span', null, h('b', null, 'Masaüstü bildirimi (bu cihaz)'), h('small', null, 'Sekme arka plandayken işletim sistemi bildirimiyle haber verir')));

  // ---------- Sesler
  const vol = h('input', { type: 'range', min: 0, max: 100, step: 5, value: Math.round(s.sound.volume * 100), class: 'set-range' });
  const volTxt = h('b', null, `%${vol.value}`);
  vol.addEventListener('input', () => { volTxt.textContent = `%${vol.value}`; });
  vol.addEventListener('change', () => { s.sound.volume = vol.value / 100; save(); playSound(s.sound.map.notification || DEFAULTS.notification, s.sound.volume); });
  const rows = h('div', { class: 'set-sounds' });
  for (const [key, label, desc] of EVENTS) {
    const sel = h('select', { class: 'input' }, SOUND_NAMES.map(n => h('option', { value: n, selected: (s.sound.map[key] || DEFAULTS[key]) === n },
      n === DEFAULTS[key] ? t('{n} (varsayılan)', { n }) : n)));
    sel.addEventListener('change', () => { s.sound.map[key] = sel.value; save(); playSound(sel.value, s.sound.volume || 0.7); });
    rows.append(h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, label), h('small', null, desc)), sel,
      h('button', { class: 'btn set-play', type: 'button', title: 'Dinle', onclick: () => playSound(sel.value, s.sound.volume || 0.7) }, '▶')));
  }
  const soundOn = toggle(s.sound, 'on', 'Sesler açık', 'Uyarı, bildirim, kargo, mesaj vb. geldiğinde ses çal', () => rows.classList.toggle('off', !s.sound.on));
  rows.classList.toggle('off', !s.sound.on);
  const qFrom = h('input', { class: 'input', type: 'time', value: s.sound.quiet.from });
  const qTo = h('input', { class: 'input', type: 'time', value: s.sound.quiet.to });
  [qFrom, qTo].forEach(i => i.addEventListener('change', () => { s.sound.quiet.from = qFrom.value; s.sound.quiet.to = qTo.value; save(); }));
  const resetSounds = h('button', { class: 'btn', type: 'button', onclick: () => { s.sound.map = {}; save('Sesler varsayılana döndü'); renderSettings(view, ctx, { changePassword, modules }, 'sounds'); } }, 'Sesleri Varsayılana Döndür');

  // ---------- Bekleme ekranı
  const ssAfter = h('select', { class: 'input' }, [[30, '30 saniye'], [60, '1 dakika'], [120, '2 dakika'], [300, '5 dakika'], [600, '10 dakika'],
    [900, '15 dakika'], [1800, '30 dakika'], [3600, '1 saat']].map(([v, l]) => h('option', { value: v, selected: s.screensaver.after === v }, l)));
  ssAfter.addEventListener('change', () => { s.screensaver.after = Number(ssAfter.value); save(); });
  // Her karede o animasyonun CANLI küçük önizlemesi. Yalnız görünen kareler oynar (IntersectionObserver; aynı anda en çok
  // MAX_LIVE tanesi — en çok görüneni önce); "hareketleri azalt" açıksa tek durağan kare çizilir.
  const animsBox = () => {
    const MAX_LIVE = 6;
    const still = reducedMotion();
    const live = new Map();   // canvas → { ctl, ratio }
    const reconcile = () => {
      const vis = [...live.values()].filter(v => v.ratio > 0).sort((a, b) => b.ratio - a.ratio);
      const on = new Set(vis.slice(0, MAX_LIVE));
      live.forEach(v => (on.has(v) ? v.ctl.play() : v.ctl.pause()));
    };
    const io = still ? null : new IntersectionObserver(es => {
      for (const e of es) { const v = live.get(e.target); if (v) v.ratio = e.isIntersecting ? e.intersectionRatio : 0; }
      reconcile();
    }, { threshold: [0, 0.25, 0.5, 0.75, 1] });
    const prev = k => {
      const cv = h('canvas', { class: 'ss-prev-cv' });
      const box = h('span', { class: 'ss-prev' }, cv);
      requestAnimationFrame(() => {   // kare yerleşince boyut bilinsin
        const ctl = createAnimPreview(cv, k, { still });
        live.set(cv, { ctl, ratio: 0 });
        io?.observe(cv);
      });
      return box;
    };
    return visualRadio('Animasyon', ANIMATIONS.map(([k, tl, d]) => ({ key: k, label: tl, sub: d, preview: () => prev(k) })),
      s.screensaver.anim, v => { s.screensaver.anim = v; save(); }, 'vr-anims');
  };

  // ---------- PIN (Hesap)
  const pinCb = h('input', { type: 'checkbox', checked: !!ctx.user.has_pin });
  const pinToggle = h('label', { class: 'set-toggle' }, pinCb, h('span', null, h('b', null, 'PIN ile giriş açık'),
    h('small', null, ctx.user.has_pin ? 'Giriş ekranında PIN sorulur' : 'Kapalı: giriş ekranında şifre sorulur')));
  pinCb.addEventListener('change', () => { const want = pinCb.checked; pinCb.checked = !want; pinModal(want); });
  function pinModal(on) {
    const pw = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
    const p1 = h('input', { class: 'input pin-input', type: 'password', inputmode: 'numeric', maxlength: 4, pattern: '[0-9]*', autocomplete: 'off' });
    const p2 = h('input', { class: 'input pin-input', type: 'password', inputmode: 'numeric', maxlength: 4, pattern: '[0-9]*', autocomplete: 'off' });
    [p1, p2].forEach(i => i.addEventListener('input', () => { i.value = i.value.replace(/\D/g, '').slice(0, 4); }));
    modal({
      title: on ? (ctx.user.has_pin ? 'PIN\'i Değiştir' : 'PIN ile Girişi Aç') : 'PIN ile Girişi Kapat',
      body: h('div', null, field('Mevcut şifreniz', pw),
        on ? h('div', { class: 'row' }, field('Yeni PIN (4 rakam)', p1), field('PIN tekrar', p2)) : null,
        on ? h('p', { class: 'small muted' }, '1234, 0000 gibi kolay tahmin edilen PIN\'ler kabul edilmez. PIN 5 kez hatalı girilirse o cihazda yeniden şifre istenir.') : null),
      actions: [{ label: 'Vazgeç' }, { label: on ? 'Kaydet' : 'Kapat', class: on ? 'primary' : 'danger', onClick: async () => {
        if (on && p1.value !== p2.value) throw new Error('PIN\'ler aynı değil');
        const r = await api.put('/api/auth/pin', on ? { password: pw.value, pin: p1.value } : { password: pw.value });
        ctx.user.has_pin = r.has_pin;
        toast(r.has_pin ? 'PIN kaydedildi' : 'PIN ile giriş kapatıldı');
        renderSettings(view, ctx, { changePassword, modules }, 'account');
      } }],
    });
  }

  // ---------- Bildirim / uyarı türleri (kullanıcı istediğini kapatabilir)
  const typeToggle = (label, on, onChange, disabled, hint) => {
    const cb = h('input', { type: 'checkbox', checked: on, disabled });
    cb.addEventListener('change', () => onChange(cb.checked));
    return h('label', { class: `set-toggle ${disabled ? 'dim' : ''}` }, cb, h('span', null, h('b', null, label), hint ? h('small', null, hint) : null));
  };
  // Solda modül seçici (simge + ad + açık tür sayısı), sağda seçilen modülün türleri; mobilde üstte açılır seçici.
  const NOTIF_ICON = { 'Destek Merkezi': 'inbox', Telsiz: 'phone', Sistem: 'server', 'Yapay Zeka': 'chip', 'KVKK / Veri Koruma': 'lock',
    Depo: 'box', 'Satın Alma': 'money', Üretim: 'layers', 'İnsan Kaynakları': 'users', Duyurular: 'bell', 'Şirketten Haberler': 'globe',
    Sekreterya: 'guest', Aramalar: 'phone', Toplantılar: 'meeting', Mail: 'mailDot', Takvim: 'calendar', Mesajlar: 'message',
    'Evrak / İmza': 'edit', Yazıcılar: 'print', 'Saha Yönetimi': 'flag', 'Canlı Yayın': 'media', Sertifikalar: 'report',
    Sözleşmeler: 'note', Yapılacaklar: 'checkBox', Diğer: 'card' };
  const notifTypesBox = () => {
    const box = h('div', { class: 'set-types' }, h('div', { class: 'small muted' }, 'Yükleniyor…'));
    api.get('/api/notifications/types').then(d => {
      const head = [h('h4', { class: 'set-sub' }, 'Bildirim türleri'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Bir modül seçin; almak istemediğiniz bildirimleri kapatın.')];
      const mods = [];
      for (const x of d.notifications) {
        const g = x.group || 'Diğer';
        let m = mods.find(y => y.key === g);
        if (!m) { m = { key: g, title: g, icon: NOTIF_ICON[g] || 'bell', items: [] }; mods.push(m); }
        m.items.push(x);
      }
      if (d.alerts.length) mods.push({ key: '__alerts', title: 'Üretim / yazıcı uyarıları', icon: 'bolt', alert: true, items: d.alerts });
      if (!mods.length) { clear(box, head, h('p', { class: 'small muted' }, 'Size uygun bildirim türü yok.')); return; }
      const muted = m => (m.alert ? s.muteAlert : s.muteNotif);
      const isOn = (m, it) => !muted(m).includes(it.key);
      const setOn = (m, it, on) => {
        if (it.critical) return;
        const L = muted(m).filter(k => k !== it.key);
        if (!on) L.push(it.key);
        if (m.alert) s.muteAlert = L; else s.muteNotif = L;
      };
      const count = m => m.items.filter(it => isOn(m, it)).length;
      if (!mods.some(m => m.key === _notifSel)) _notifSel = mods[0].key;
      const list = h('div', { class: 'nt-list', role: 'tablist', 'aria-orientation': 'vertical', 'aria-label': 'Modüller' });
      const pick = h('select', { class: 'input nt-pick', 'aria-label': 'Modül' });
      const panel = h('div', { class: 'nt-panel', role: 'tabpanel', id: 'nt-panel' });
      const ico = m => h('span', { class: 'nt-ico', 'aria-hidden': 'true' }, segIconByKey(m.icon) || segIconByKey('bell'));
      const badge = m => {
        const n = count(m), all = m.items.length;
        return h('span', { class: `nt-badge ${n === 0 ? 'off' : n < all ? 'part' : ''}`, title: t('{n} / {all} tür açık', { n, all }) }, `${n}/${all}`);
      };
      const drawList = () => {
        clear(list, mods.map(m => {
          const on = m.key === _notifSel;
          return h('button', { type: 'button', class: `nt-mod ${on ? 'on' : ''}`, role: 'tab', 'aria-selected': on ? 'true' : 'false',
            'aria-controls': 'nt-panel', tabindex: on ? '0' : '-1', 'data-k': m.key, onclick: () => select(m.key) },
            ico(m), h('span', { class: 'nt-name' }, m.title), badge(m));
        }));
        clear(pick, mods.map(m => h('option', { value: m.key, selected: m.key === _notifSel }, `${t(m.title)} (${count(m)}/${m.items.length})`)));
      };
      const drawPanel = () => {
        const m = mods.find(x => x.key === _notifSel);
        const changeable = m.items.filter(it => !it.critical);
        const bulk = on => { changeable.forEach(it => setOn(m, it, on)); save(m.alert ? 'Uyarı tercihleri güncellendi' : 'Bildirim tercihleri güncellendi'); drawList(); drawPanel(); };
        clear(panel,
          h('div', { class: 'nt-head' }, ico(m),
            h('div', { class: 'grow' }, h('b', null, m.title),
              h('small', null, m.alert ? 'Üretim / yazıcı uyarıları. Kritik güvenlik uyarıları kapatılamaz.' : t('{n} bildirim türü', { n: m.items.length }))),
            changeable.length > 1 ? h('div', { class: 'nt-bulk' },
              h('button', { class: 'btn xs ghost', type: 'button', onclick: () => bulk(true) }, 'Tümünü aç'),
              h('button', { class: 'btn xs ghost', type: 'button', onclick: () => bulk(false) }, 'Tümünü kapat')) : null),
          m.items.map(it => typeToggle(it.title, isOn(m, it), on => {
            setOn(m, it, on); save(m.alert ? 'Uyarı tercihleri güncellendi' : 'Bildirim tercihleri güncellendi'); drawList();
          }, it.critical, it.critical ? 'Kritik güvenlik uyarısı — kapatılamaz' : null)));
      };
      const select = (k, focus) => {
        _notifSel = k; drawList(); drawPanel();
        if (focus) list.querySelector(`.nt-mod[data-k="${CSS.escape(k)}"]`)?.focus();
      };
      list.addEventListener('keydown', e => {
        const i = mods.findIndex(m => m.key === _notifSel), n = mods.length;
        const go = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: n - 1 }[e.key];
        if (go != null) { e.preventDefault(); select(mods[(go + n) % n].key, true); }
      });
      pick.addEventListener('change', () => select(pick.value));
      drawList(); drawPanel();
      clear(box, head, pick, h('div', { class: 'nt-wrap' }, list, panel));
    }).catch(() => clear(box, h('p', { class: 'small muted' }, 'Türler yüklenemedi')));
    return box;
  };

  // ---------- Arka plan bildirimleri (bu cihaz): uygulama kapalıyken arama / mesaj / telsiz / bildirim
  const pushBox = () => {
    const box = h('div', { class: 'set-push' });
    const draw = async () => {
      const sup = pushSupport(), st = await pushState().catch(() => 'off');
      const btn = (label, cls, fn) => h('button', { class: `btn ${cls}`, type: 'button', onclick: async e => {
        e.currentTarget.disabled = true;
        try { await fn(); } catch (err) { toastError(err); } finally { draw(); }
      } }, label);
      clear(box,
        h('h4', { class: 'set-sub' }, 'Arka plan bildirimleri (bu cihaz)'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } },
          'Uygulama kapalıyken, aşağıya indirildiğinde ya da ekran kilitliyken gelen arama, mesaj, telsiz ve bildirimler bu cihazda bildirim olarak görünür. Her cihazda ayrı açılır.'),
        !sup.ok ? h('p', { class: 'small warn-text' }, sup.why)
          : h('div', { class: 'set-push-row' },
            h('span', { class: `badge ${st === 'on' ? 'green' : 'gray'}` }, st === 'on' ? 'Bu cihazda açık' : 'Bu cihazda kapalı'),
            st === 'on'
              ? [btn('Deneme bildirimi gönder', '', async () => { await api.post('/api/push/test', {}); toast('Deneme bildirimi gönderildi — uygulamayı arka plana alıp bekleyin'); }),
                 btn('Kapat', 'ghost', async () => { await disablePush(); toast('Bu cihazda arka plan bildirimleri kapatıldı'); })]
              : btn('Bu cihazda aç', 'primary', async () => { await enablePush(); toast('Arka plan bildirimleri açıldı'); })));
    };
    draw();
    return box;
  };

  // Native uygulama (Capacitor): bildirimler işletim sistemi/FCM üzerinden; web-push ayarları yerine OS izin durumu gösterilir
  const nativeApp = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  const nativeNotifBox = () => {
    const box = h('div', { class: 'set-push' });
    const draw = async () => {
      let perm = 'prompt';
      try { const Pn = window.Capacitor.Plugins.PushNotifications; if (Pn) perm = (await Pn.checkPermissions()).receive; } catch (e) { /* */ }
      const askBtn = h('button', { class: 'btn primary', type: 'button', onclick: async e => {
        e.currentTarget.disabled = true;
        try { await window.Capacitor.Plugins.PushNotifications.requestPermissions(); } catch (err) { /* */ }
        draw();
      } }, 'İzin iste');
      clear(box,
        h('h4', { class: 'set-sub' }, 'Uygulama bildirimleri (bu cihaz)'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } },
          'HEPGO uygulaması; arama, mesaj, telsiz ve uyarı bildirimlerini doğrudan telefonun işletim sistemi üzerinden gösterir. Uygulama kapalı ya da ekran kilitliyken de gelir — ayrı bir "masaüstü bildirimi" ayarı gerekmez.'),
        h('div', { class: 'set-push-row' },
          h('span', { class: `badge ${perm === 'granted' ? 'green' : 'gray'}` },
            perm === 'granted' ? '✓ Bildirim izni verildi' : perm === 'denied' ? '✕ Bildirim izni kapalı' : 'İzin bekleniyor'),
          perm !== 'granted' ? askBtn : null),
        perm === 'denied' ? h('p', { class: 'small warn-text' }, 'Telefon Ayarlar › Uygulamalar › HEPGO › Bildirimler bölümünden açabilirsiniz.') : null);
    };
    draw();
    return box;
  };

  // ---------- Rahatsız Etmeyin (arama / mesaj; süreli ya da sürekli)
  const dndUntil = dur => {
    if (dur === 'always' || dur === 'offhours') return null;   // mesai sonrası: sunucu her an mesai saatine göre karar verir
    const d = new Date();
    if (dur === 'today') d.setHours(23, 59, 0, 0); else d.setHours(d.getHours() + Number(dur));
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`;
  };

  // ---------- Sol: ayar grupları, sağ: seçilen grubun ayrıntısı (#/settings/<grup>)
  const GROUPS = [].concat([
    { key: 'ui', title: 'Arayüz', desc: 'Tema, boyut, görünüm, açılış sayfası', icon: 'card',
      body: () => card('Arayüz', 'Uygulamanın görünümü ve açılış sayfası.',
        line('Dil', 'Arayüz ve yazdırma şablonlarının dili', langSeg),
        block('Tema', 'Koyu tema gece ve karanlık ortam için; "Sisteme göre" cihazın ayarını izler', themeSeg),
        block('Yazı ve öğe boyutu', 'Sayfa içeriğini büyütür / küçültür', scaleSeg),
        toggle(s, 'compact', 'Sıkı görünüm', 'Kart ve tablo boşluklarını azaltır, ekrana daha çok bilgi sığar'),
        toggle(s, 'motion', 'Hareketleri azalt', 'Geçiş ve animasyonları kapatır'),
        line('Metin biçimi', 'Tüm görünen metinlerin yazımı (kodlar ve giriş alanları hariç)', textCaseSeg),
        line('Açılış sayfası', 'Giriş yapınca açılacak sayfa', startSel)) },
    { key: 'holiday', title: 'Bayram temaları', desc: 'Bayram ve tatil günlerinde pano süslemeleri, ülke seçimi', icon: 'calendar', body: holidayBody },
    { key: 'appearance', title: 'Görünüm & Renkler', desc: 'Üst/alt bar, footer, zemin renkleri; gövde arka planı; toolbar hizası', icon: 'card', body: appearanceBody },
    { key: 'notifications', title: 'Bildirimler', desc: 'Bildirim kutusu, masaüstü bildirimi', icon: 'bell',
      body: () => card('Bildirimler', 'Yeni uyarı, bildirim ya da mesaj geldiğinde nasıl haber verileceği.',
        toggle(s, 'flash', 'Sağ üstte bildirim kutusu', 'Yeni uyarı, bildirim ya da mesajda kısa süre görünen kutu'),
        line('Kutu görünme süresi', null, flashSel),
        nativeApp ? nativeNotifBox() : [
          h('h4', { class: 'set-sub' }, 'Bu cihaz'),
          h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Masaüstü bildirimi her cihazda ayrı açılır ve o cihazın tarayıcı iznini gerektirir. Telefonunuzda ayrıca buradan açıp izin vermelisiniz.'),
          deviceDesk, deskState,
          pushBox(),
        ],
        notifTypesBox()) },
    { key: 'sounds', title: 'Sesler', desc: 'Olay sesleri, ses düzeyi, sessiz saatler', icon: 'bell2',
      body: () => card('Sesler', 'Her olay için ayrı ses seçin. Sesler tarayıcıda üretilir; sayfaya ilk dokunuştan sonra çalar.',
        h('div', { class: 'set-line' }, soundOn, h('span', { class: 'set-vol' }, '🔈', vol, '🔊', volTxt)),
        rows,
        h('div', { class: 'set-line top' }, toggle(s.sound.quiet, 'on', 'Sessiz saatler', 'Bu saatler arasında ses çalmaz'), h('span', { class: 'set-vol' }, qFrom, '–', qTo)),
        h('div', { class: 'set-actions' }, resetSounds)) },
    { key: 'screensaver', title: 'Bekleme ekranı', desc: 'Ekran koruyucu, süre, animasyon', icon: 'screen',
      body: () => card('Bekleme ekranı', 'Belirlenen süre boyunca dokunulmazsa tam ekran animasyon, saat ve tarih gösterilir; dokununca kapanır.',
        toggle(s.screensaver, 'on', 'Bekleme ekranı açık', 'Kullanılmadığında ekran koruyucuyu göster'),
        line('Bekleme süresi', 'Bu kadar süre dokunulmazsa açılır', ssAfter),
        toggle(s.screensaver, 'lock', 'Çıkarken şifre / PIN sor', ctx.user.has_pin
          ? 'Bekleme ekranından dönmek için PIN\'iniz istenir (PIN açık); istenirse şifreyle de açılır'
          : 'Bekleme ekranından dönmek için şifreniz istenir. PIN açarsanız (Hesap) PIN ile açılır'),
        block('Animasyon', 'Seçip "Önizle" ile tam ekranda deneyin', animsBox()),
        h('div', { class: 'set-actions' }, h('button', { class: 'btn primary', type: 'button', onclick: () => showScreensaver(s.screensaver.anim, { preview: true }) }, '▶ Önizle'))) },
    { key: 'voice', title: 'Görüşme Ayarları', desc: 'Sesli görüşme arka planı', icon: 'phone',
      body: () => {
        // Önizleme: seçilen arka plan üzerinde küçük bir görüşme ekranı (kişi, ad, kapat / aç düğmeleri)
        const callPrev = k => h('span', { class: 'cb-prev', style: { background: CALL_BACKGROUNDS[k] } },
          h('i', { class: 'cb-av' }), h('i', { class: 'cb-nm' }), h('span', { class: 'cb-btns' }, h('i', { class: 'cb-end' }), h('i', { class: 'cb-ok' })));
        const grid = visualRadio('Görüşme arka planı', Object.keys(CALL_BACKGROUNDS).map(k => ({ key: k, label: CALL_BG_LABELS[k], preview: () => callPrev(k) })),
          s.callBg || 'aurora', k => { s.callBg = k; save('Görüşme arka planı güncellendi'); }, 'vr-call');
        return card('Görüşme Ayarları', null,
          block('Arka plan', 'Sesli görüşme ekranının arka planı. Gelen arama ve görüşme ekranında uygulanır.', grid));
      } },
    { key: 'radio', title: 'Telsiz Kanallarım', desc: 'Kanal oluştur, kişi davet et, davetleri onayla', icon: 'bell2',
      body: () => {
        const wrap = h('div', null, card('Telsiz Kanallarım', null, h('div', { class: 'loading' }, 'Yükleniyor…')));
        const err = e => toast(e.message || 'İşlem yapılamadı', 'err');
        const refreshRadio = () => window.dispatchEvent(new Event('caymaz:radio-refresh'));
        const load = async () => {
          let d; try { d = await api.get('/api/radio/mine'); } catch (e) { clear(wrap, card('Telsiz Kanallarım', e.message)); return; }
          const dot = c => h('span', { class: 'sr-dot', style: { background: c } });
          const invites = d.invites.length ? card('Davetler', 'Sizi telsiz kanalına davet edenler. Onaylarsanız kanal telsiz menünüzde görünür.',
            ...d.invites.map(i => h('div', { class: 'sr-row invite' }, dot(i.color),
              h('div', { class: 'grow' }, h('b', null, i.name), h('small', null, t('{name} davet etti', { name: i.invited_by_name || 'Bir kullanıcı' }))),
              h('button', { class: 'btn primary xs', type: 'button', onclick: async () => { try { await api.post(`/api/radio/channels/${i.id}/accept`, {}); toast(t('“{name}” kanalına katıldınız', { name: i.name }), 'success'); refreshRadio(); load(); } catch (e) { err(e); } } }, 'Katıl'),
              h('button', { class: 'btn xs', type: 'button', onclick: async () => { try { await api.post(`/api/radio/channels/${i.id}/decline`, {}); toast('Davet reddedildi'); load(); } catch (e) { err(e); } } }, 'Reddet')))) : null;
          const owned = card('Kanallarım', 'Oluşturduğunuz kanallar. Eklediğiniz kişilere onay bildirimi gider; onaylayan kanala üye olur.',
            h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: () => editor(null, d) }, '+ Yeni kanal')),
            ...(d.owned.length ? d.owned.map(c => {
              const ok = c.people.filter(p => p.status === 'UYE'), wait = c.people.filter(p => p.status === 'DAVET');
              return h('div', { class: 'sr-row' }, dot(c.color),
                h('div', { class: 'grow' }, h('b', null, c.name),
                  h('small', null, t('{a} üye', { a: ok.length + 1 }) + (wait.length ? t(' · {n} onay bekliyor', { n: wait.length }) : '')),
                  h('div', { class: 'sr-avs' }, ...ok.map(p => h('span', { title: p.full_name }, avatar(p, 'sm'))),
                    ...wait.map(p => h('span', { class: 'wait', title: t('{name} · onay bekliyor', { name: p.full_name }) }, avatar(p, 'sm'))))),
                h('button', { class: 'btn xs', type: 'button', onclick: () => editor(c, d) }, 'Düzenle'),
                h('button', { class: 'btn xs danger', type: 'button', onclick: async () => {
                  if (!await confirmDialog('Kanalı sil', t('“{name}” telsiz kanalı silinsin mi? Tüm üyeler kanaldan çıkar.', { name: c.name }), { okLabel: 'Sil', danger: true })) return;
                  try { await api.del(`/api/radio/channels/${c.id}`); toast('Kanal silindi'); refreshRadio(); load(); } catch (e) { err(e); }
                } }, 'Sil'));
            }) : [h('p', { class: 'small muted' }, 'Henüz kanal oluşturmadınız.')]));
          const member = d.member.length ? card('Üyesi olduğum kanallar', null, ...d.member.map(c => h('div', { class: 'sr-row' }, dot(c.color),
            h('div', { class: 'grow' }, h('b', null, c.name), h('small', null, t('{owner} · {n} üye', { owner: c.owner_name || '—', n: c.member_count }))),
            h('button', { class: 'btn xs', type: 'button', onclick: async () => {
              if (!await confirmDialog('Kanaldan ayrıl', t('“{name}” kanalından ayrılmak istiyor musunuz?', { name: c.name }), { okLabel: 'Ayrıl' })) return;
              try { await api.post(`/api/radio/channels/${c.id}/leave`, {}); toast('Kanaldan ayrıldınız'); refreshRadio(); load(); } catch (e) { err(e); }
            } }, 'Ayrıl')))) : null;
          clear(wrap, invites, owned, member,
            h('p', { class: 'small muted' }, '“Tüm Şirket” kanalı ile Sekreterya / Güvenlik hatları herkeste sabittir.'));
        };
        const editor = (c, d) => {
          const name = h('input', { class: 'input', value: c?.name || '', placeholder: 'Örn: Vardiya ekibi, Depo, Proje X' });
          let color = c?.color || d.colors[0];
          const sw = h('div', { class: 'sr-sw' });
          const drawSw = () => clear(sw, d.colors.map(col => { const b = h('button', { type: 'button', class: col === color ? 'on' : '', title: col, onclick: () => { color = col; drawSw(); } }); b.style.background = col; return b; }));
          drawSw();
          const picked = new Set(c ? c.people.map(p => p.id) : []);
          const status = new Map(c ? c.people.map(p => [p.id, p.status]) : []);
          const q = h('input', { class: 'input', placeholder: 'Kişi ara…' });
          const list = h('div', { class: 'sr-users' });
          const cnt = h('small', { class: 'muted' });
          const drawUsers = () => {
            const f = q.value.trim().toLocaleLowerCase('tr');
            cnt.textContent = t('{n} kişi', { n: picked.size });
            clear(list, d.users.filter(u => !f || u.full_name.toLocaleLowerCase('tr').includes(f)).map(u => {
              const cb = h('input', { type: 'checkbox', checked: picked.has(u.id), onchange: e => { e.target.checked ? picked.add(u.id) : picked.delete(u.id); cnt.textContent = t('{n} kişi', { n: picked.size }); } });
              const st = status.get(u.id);
              return h('label', { class: 'sr-user' }, cb, avatar(u, 'sm'), h('span', { class: 'grow' }, u.full_name),
                st === 'DAVET' ? h('small', { class: 'sr-tag' }, 'onay bekliyor') : st === 'UYE' ? h('small', { class: 'sr-tag ok' }, 'üye') : null);
            }));
          };
          q.addEventListener('input', drawUsers); drawUsers();
          modal({
            title: c ? 'Kanalı düzenle' : 'Yeni telsiz kanalı', wide: true,
            body: h('div', null,
              h('label', { class: 'field' }, h('span', null, 'Kanal adı'), name),
              h('div', { class: 'field' }, h('span', null, 'Renk'), sw),
              h('div', { class: 'field' }, h('span', { class: 'sr-uh' }, 'Kişiler', cnt), q, list,
                h('small', { class: 'hint' }, 'Yeni eklediğiniz kişilere onay bildirimi gider; onaylayınca kanala üye olurlar.'))),
            actions: ['spacer', { label: 'İptal', onClick: () => {} }, {
              label: c ? 'Kaydet' : 'Oluştur ve davet et', class: 'primary',
              onClick: async () => {
                if (!name.value.trim()) throw new Error('Kanal adı girin');
                const body = { name: name.value.trim(), color, user_ids: [...picked] };
                if (c) await api.put(`/api/radio/channels/${c.id}`, body); else await api.post('/api/radio/channels', body);
                toast(c ? 'Kanal güncellendi' : 'Kanal oluşturuldu, davetler gönderildi', 'success'); refreshRadio(); load();
              },
            }],
          });
        };
        load();
        return wrap;
      } },
    { key: 'mailboxes', title: 'Mail Hesaplarım', desc: 'Gmail, Outlook / Microsoft 365, IMAP / Exchange, POP3', icon: 'inbox',
      body: () => { const q = subQuery; subQuery = ''; return mailboxesSection(q); } },
    { key: 'social', title: 'Sosyal Medya', desc: 'Hesaplarınızın paylaşımları Şirketten Haberler’de (yalnız size)', icon: 'globe', body: () => { const q = subQuery; subQuery = ''; return socialSection(q); } },
    { key: 'mascot', title: 'Maskot', desc: 'Köşedeki yapay zeka asistanı karakteri', icon: 'card',
      body: () => {
        // Kutucuklarda canlı (görünürken oynayan) maskot + "Sesini dinle" düğmesi
        const grid = h('div', { class: 'set-mascot-wrap' });
        const draw = () => clear(grid, visualRadio('Maskot', MASCOT_LIST.map(m => ({
          key: m.id, label: m.name, sub: m.desc,
          preview: () => mascotLivePreview(m.id, s.mascot3d !== false && has3d(m.id)),
          extra: h('button', { type: 'button', class: 'vr-extra set-mascot-play', title: 'Sesini dinle', 'aria-label': t('{n}: sesini dinle', { n: m.name }),
            onclick: e => { e.stopPropagation(); previewMascotSound(m.id); e.currentTarget.closest('.vr-opt')?.querySelector('.mascot-live')?.playTrick?.(); },
            html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9.5v5h4l5 4v-13l-5 4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/></svg>' }),
        })), s.mascot, (id, el) => { s.mascot = id; setMascot(id); save('Maskot değiştirildi'); el?.querySelector('.mascot-live')?.playTrick?.(); }, 'vr-mascot'));
        draw();
        const styleSel = h('select', { class: 'input' }, [['samimi', 'Samimi (varsayılan)'], ['ciddi', 'Ciddi ve profesyonel'],
          ['sakaci', 'Şakacı'], ['alayci', 'Alaycı (iğneleyici)'], ['coskulu', 'Coşkulu'], ['bilgic', 'Bilgiç / akademik']]
          .map(([v, l]) => h('option', { value: v, selected: s.mascotStyle === v }, l)));
        styleSel.addEventListener('change', () => { s.mascotStyle = styleSel.value; save('Konuşma tarzı güncellendi'); });
        const d3Chk = h('input', { type: 'checkbox', checked: s.mascot3d !== false });
        d3Chk.addEventListener('change', () => {
          s.mascot3d = d3Chk.checked; setMascot3D(d3Chk.checked); draw(); save(d3Chk.checked ? '3D maskot açıldı' : 'Klasik maskota dönüldü');
        });
        const showChk = h('input', { type: 'checkbox', checked: !s.mascotOff });
        showChk.addEventListener('change', () => {
          s.mascotOff = !showChk.checked; applyMascotHidden(s.mascotOff); save(showChk.checked ? 'Maskot açıldı' : 'Maskot gizlendi');
        });
        const soundChk = h('input', { type: 'checkbox', checked: !!s.mascotSound });
        soundChk.addEventListener('change', () => {
          s.mascotSound = soundChk.checked; setMascotSound(soundChk.checked); save(soundChk.checked ? 'Maskot sesi açıldı' : 'Maskot sesi kapatıldı');
        });
        return card('Maskot', 'Ekranın köşesinde duran, sürekli hareket eden ve tıklayınca yapay zekayla sohbet açan asistanınızı seçin. Maskotu köşede sürükleyerek istediğiniz yere taşıyabilirsiniz.',
          h('label', { class: 'set-toggle' }, showChk, h('span', null, h('b', null, 'Maskotu göster'), h('small', null, 'Köşedeki yapay zeka asistanını gösterir ya da gizler'))),
          h('label', { class: 'set-toggle' }, d3Chk, h('span', null, h('b', null, '3D maskot'), h('small', null, 'Üç boyutlu, canlı karakter (gözleri imleci izler, düşünür, konuşur). Kapalıysa klasik çizim; “Hareketleri azalt” açıkken de klasik çizim kullanılır.'))),
          h('label', { class: 'set-toggle' }, soundChk, h('span', null, h('b', null, 'Maskot sesli'), h('small', null, 'Maskot arada bir kendi sesini çıkarır (kedi miyavlar, robot bip-bop yapar…). Her karakterin sesini kutucuğundaki hoparlör düğmesiyle dinleyebilirsiniz.'))),
          h('h4', { class: 'set-sub' }, 'Karakter'),
          grid,
          h('h4', { class: 'set-sub' }, 'Konuşma tarzı'),
          line('Asistanın üslubu', 'Cevapların tonu bu seçime göre değişir', styleSel));
      } },
    { key: 'dnd', title: 'Rahatsız Etmeyin', desc: 'Aramalara / mesajlara süreli, sürekli ya da mesai sonrası kapan', icon: 'bell',
      body: () => {
        // "Mesai sonrası": mesai bitiminden ertesi mesai başlangıcına kadar (hafta sonu tüm gün). Sistemde mesai programı
        // (Program Ayarları › Mesai) kayıtlıysa o kullanılır; değilse / kullanıcı isterse kendi saatleri (varsayılan 08:30–18:00).
        // Sunucu da aynı kuralla bastırır (auth.dnd_state).
        s.dnd.work = { from: '08:30', to: '18:00', ...(s.dnd.work || {}) };
        let sched = null;   // /api/worktime/schedule → { defined, days, holidays }
        const hm = x => { const [a, b] = String(x || '0:0').split(':').map(Number); return (a || 0) * 60 + (b || 0); };
        const useSystem = () => !!sched?.defined && s.dnd.workSrc !== 'custom';
        const offNow = (now = new Date()) => {
          const cur = now.getHours() * 60 + now.getMinutes(), wd = now.getDay() || 7;   // 1=Pzt … 7=Paz
          if (useSystem()) {
            const p = n => String(n).padStart(2, '0');
            if ((sched.holidays || []).includes(`${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`)) return true;
            const day = sched.days[String(wd)];
            return !day?.on || !(hm(day.from) <= cur && cur < hm(day.to));
          }
          if (wd >= 6) return true;
          let a = hm(s.dnd.work.from), b = hm(s.dnd.work.to);
          if (a >= b) { a = hm('08:30'); b = hm('18:00'); }
          return !(a <= cur && cur < b);
        };
        const dayName = i => new Date(2024, 0, i).toLocaleDateString(getLang() || 'tr', { weekday: 'short' });   // 1 Ocak 2024 = Pazartesi
        const schedSummary = () => {
          const on = [1, 2, 3, 4, 5, 6, 7].filter(i => sched.days[String(i)]?.on);
          if (!on.length) return t('Mesai günü tanımlı değil');
          const same = on.every(i => sched.days[String(i)].from === sched.days[String(on[0])].from && sched.days[String(i)].to === sched.days[String(on[0])].to);
          const contiguous = on.every((d, k) => !k || d === on[k - 1] + 1);
          if (same) {
            const days = contiguous && on.length > 1 ? `${dayName(on[0])}–${dayName(on[on.length - 1])}` : on.map(dayName).join(', ');
            return `${days} ${sched.days[String(on[0])].from}–${sched.days[String(on[0])].to}`;
          }
          return on.map(i => `${dayName(i)} ${sched.days[String(i)].from}–${sched.days[String(i)].to}`).join(' · ');
        };
        const status = h('div', { class: 'set-dnd-status' });
        const refresh = () => {
          const active = s.dnd.calls || s.dnd.messages;
          const ch = [s.dnd.calls ? t('aramalar') : null, s.dnd.messages ? t('mesajlar') : null].filter(Boolean).join(t(' ve '));
          const Ch = ch ? ch[0].toLocaleUpperCase(getLang() || 'tr') + ch.slice(1) : '';
          const off = s.dnd.dur === 'offhours';
          const closedNow = active && (!off || offNow());
          status.className = `set-dnd-status ${closedNow ? 'on' : active ? 'wait' : ''}`;
          status.textContent = !active ? t('🟢 Şu an herkese açıksınız.')
            : off ? (closedNow ? t('🌙 {ch} mesai sonrası kapalı — şu an mesai dışı, kapalısınız.', { ch: Ch })
              : t('🕘 {ch} mesai sonrası kapanır — şu an mesai saati, açıksınız.', { ch: Ch }))
            : t('🔕 {ch} kapalı — {rest}', { ch: Ch, rest: s.dnd.until ? t('bitiş: {d}', { d: fmtDateTime(s.dnd.until) }) : t('sürekli (siz açana kadar)') });
        };
        const onDnd = () => { s.dnd.until = (s.dnd.calls || s.dnd.messages) ? dndUntil(s.dnd.dur || 'always') : null; refresh(); };
        const durSel = h('select', { class: 'input' }, [['always', 'Sürekli (ben açana kadar)'], ['1', '1 saat'], ['2', '2 saat'],
          ['4', '4 saat'], ['today', 'Bugün gece yarısına kadar'], ['offhours', 'Mesai sonrası']].map(([v, l]) => h('option', { value: v, selected: (s.dnd.dur || 'always') === v }, l)));
        const work = h('div', { class: 'set-dnd-work' });
        const drawWork = () => {
          work.hidden = s.dnd.dur !== 'offhours';
          if (work.hidden) return;
          const from = h('input', { class: 'input', type: 'time', value: s.dnd.work.from, 'aria-label': 'Mesai başlangıcı' });
          const to = h('input', { class: 'input', type: 'time', value: s.dnd.work.to, 'aria-label': 'Mesai bitişi' });
          [from, to].forEach(i => i.addEventListener('change', () => {
            if (!from.value || !to.value || hm(from.value) >= hm(to.value)) { toast('Mesai bitişi başlangıçtan sonra olmalı', 'err'); from.value = s.dnd.work.from; to.value = s.dnd.work.to; return; }
            s.dnd.work = { from: from.value, to: to.value }; refresh(); save('Mesai saatleri güncellendi');
          }));
          const custom = h('div', { class: 'set-line top' },
            h('span', { class: 'grow' }, h('b', null, 'Mesai saatlerim'), h('small', null, 'Hafta içi bu saatler dışında ve hafta sonu tüm gün kapalı kalırsınız.')),
            h('span', { class: 'set-vol' }, from, '–', to));
          clear(work,
            sched?.defined ? line('Mesai saatleri', 'Sistemdeki mesai programı ya da kendi saatleriniz',
              segmented([['system', 'Sistem mesai saatleri'], ['custom', 'Kendi saatlerim']], useSystem() ? 'system' : 'custom',
                v => { s.dnd.workSrc = v; drawWork(); refresh(); save('Rahatsız etmeyin güncellendi'); })) : null,
            useSystem()
              ? h('p', { class: 'small muted set-dnd-sum' }, t('Mesai: {s}. Bu saatler dışında, hafta sonu ve tatillerde tüm gün kapalı kalırsınız.', { s: schedSummary() }))
              : custom);
        };
        durSel.addEventListener('change', () => { s.dnd.dur = durSel.value; onDnd(); drawWork(); save('Rahatsız etmeyin güncellendi'); });
        api.get('/api/worktime/schedule').then(d => { sched = d; drawWork(); refresh(); }).catch(() => { sched = null; drawWork(); });
        drawWork();
        refresh();
        return card('Rahatsız Etmeyin', 'Kendinizi aramalara ve/veya mesajlara kapatabilirsiniz. Süre seçebilir, sürekli kapalı kalabilir ya da yalnız mesai sonrasında kapanabilirsiniz; süre dolunca otomatik açılır.',
          status,
          toggle(s.dnd, 'calls', 'Aramalara kapat', 'Kimse sizi sesli arayamaz; arayan “rahatsız etmeyin” uyarısı görür', onDnd),
          toggle(s.dnd, 'messages', 'Mesajlara kapat', 'Kimse size yeni mesaj gönderemez', onDnd),
          line('Süre', '“Sürekli”: siz açana kadar · “Mesai sonrası”: mesai bitiminden ertesi mesai başlangıcına, hafta sonu tüm gün', durSel),
          work); } },
    { key: 'privacy', title: 'Gizlilik', desc: 'Çevrimiçi durumu, okundu / iletildi bilgisi, mesajlar', icon: 'lock',
      body: () => card('Gizlilik', 'Diğer kullanıcıların sizinle ilgili neler görebileceği.',
        toggle(s.privacy, 'hide_online', 'Çevrimiçi durumumu gizle', 'Aktif kullanıcılar listesinde ve mesajlaşmada görünmezsiniz (sistem yöneticisi hariç)'),
        toggle(s.privacy, 'share_location_web', 'Web\'de konumumu paylaş', 'Tarayıcıdan girdiğinizde (HEPGO sekmesi açıkken) konumunuz Canlı Konum haritasına gönderilir; KVKK açık rızanız ve tarayıcı izniyle. Kapatınca durur.', async cb => { if (cb.checked) (await import('../weblocation.js')).initWebLocation(ctx, () => true); else (await import('../weblocation.js')).stopWebLocation(); }),
        h('h4', { class: 'set-sub' }, 'Mesaj bilgileri'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'WhatsApp’taki gibi: ✓ gönderildi · ✓✓ iletildi · mavi ✓✓ okundu. Bir bilgiyi kapatırsanız karşı taraflar onu sizden alamaz, siz de başkalarınınkini göremezsiniz.'),
        toggle(s.privacy, 'hide_read', 'Okundu bilgisini gönderme', 'Mesajı açtığınızda karşı tarafta mavi çift tik görünmez'),
        toggle(s.privacy, 'hide_delivered', 'İletildi bilgisini gönderme', 'Mesaj cihazınıza ulaştığında karşı tarafta gri çift tik görünmez'),
        h('h4', { class: 'set-sub' }, 'Diğer'),
        toggle(s.privacy, 'no_messages', 'Mesaj almayı kapat', 'Diğer kullanıcılar size yeni mesaj gönderemez'),
        toggle(s, 'location_work_hours_only', 'Mesai dışında konumu kapat', 'Mobil uygulamada: yalnızca mesai saatlerinde (ve size girilen fazla mesaide) konumunuz kaydedilir. Görevde / sahada olduğunuzda veya konumu her zaman açık bir rolde (ör. Güvenlik) iseniz konum yine takip edilir.')) },
    { key: 'mydata', title: 'Verilerim (KVKK)', desc: 'Verilerinizin kopyasını isteyin; silme / itiraz başvurusu', icon: 'lock',
      body: () => {
        const wrap = h('div', null);
        const KIND = { export: 'Verilerimin kopyasını istiyorum', delete: 'Verilerimin silinmesini istiyorum', object: 'İşlenmesine itiraz ediyorum' };
        const badge = st => h('span', { style: { marginLeft: '8px', fontSize: '12px', padding: '1px 8px', borderRadius: '10px', background: st === 'open' ? '#ffece0' : '#e6f7ec', color: st === 'open' ? '#c2410c' : '#1a7f37' } }, st === 'open' ? 'Açık' : 'Kapatıldı');
        const draw = async () => {
          let mine = [];
          try { mine = await api.get('/api/kvkk/my-requests'); } catch { /* ilk açılışta boş */ }
          const sel = h('select', { class: 'input' }, Object.entries(KIND).map(([k, v]) => h('option', { value: k }, v)));
          const note = h('textarea', { class: 'input', rows: 3, placeholder: 'Açıklama (isteğe bağlı)' });
          const send = h('button', { class: 'btn primary', type: 'button' }, 'Başvuru Gönder');
          send.addEventListener('click', async () => {
            send.disabled = true;
            try { await api.post('/api/kvkk/request', { kind: sel.value, note: note.value }); toast('Başvurunuz alındı, sistem yöneticinize iletildi', 'success'); note.value = ''; draw(); }
            catch (err) { toastError(err); } finally { send.disabled = false; }
          });
          clear(wrap,
            card('Verilerim (KVKK)', '6698 sayılı KVKK md. 11 kapsamında verilerinizin kopyasını isteyebilir, silinmesini ya da işlenmesine itiraz edebilirsiniz. Başvurunuz sistem yöneticinize iletilir ve kayıt altına alınır.',
              field('Talep türü', sel), field('Açıklama', note), h('div', { class: 'set-actions left' }, send)),
            card('Başvurularım', null, mine.length ? h('div', { class: 'ios-group' }, mine.map(r => h('div', { class: 'ios-row', style: { display: 'block' } },
              h('div', null, h('b', null, KIND[r.kind] || r.kind), badge(r.status)),
              h('div', { class: 'small muted' }, new Date(r.created_at).toLocaleString('tr') + (r.resolution ? ` · ${r.resolution}` : ''))))) : h('p', { class: 'muted' }, 'Henüz başvuru yok.')));
        };
        draw();
        return wrap;
      } },
    { key: 'dashboard', title: 'Pano', desc: 'Ana sayfa kutucukları, Şirketten Haberler görünümü', icon: 'grid',
      body: () => card('Pano', 'Ana sayfadaki kutucuk düzeniniz. Kutucukları ana sayfada "Panoyu Düzenle" ile değiştirebilirsiniz.',
        line('Şirketten Haberler görünümü', 'Pano kutucuğu akış olarak mı yoksa harita olarak mı açılsın',
          segmented([['feed', 'Akış'], ['map', 'Harita']], s.feedView, v => { s.feedView = v; save('Görünüm güncellendi'); })),
        toggle(s, 'feedFullMobile', 'Mobilde Şirketten Haberler tam ekran', 'Yalnızca telefonda: ana ekran, pano yerine tam ekran haber akışıyla açılır (üst menü ve alt bilgi kalır)'),
        h('div', { class: 'set-actions left' },
          h('a', { class: 'btn', href: '#/' }, 'Panoya Git'),
          h('button', { class: 'btn', type: 'button', onclick: async () => {
            if (!await confirmDialog('Panoyu sıfırla', 'Pano varsayılan düzene (Saat, Takvim, Duyurular, Üretim özeti, 14 gün üretim) döndürülsün mü?', { okLabel: 'Sıfırla' })) return;
            await api.put('/api/me/prefs/dashboard', { value: 'null' });
            toast('Pano varsayılana döndü');
          } }, 'Panoyu Varsayılana Döndür'))) },
    { key: 'upload', title: 'Yükleme', desc: 'Paralel yükleme sayısı ve en yüksek yükleme hızı (bu cihaz)', icon: 'card',
      body: () => {
        // Cihaz-bazlı (localStorage; api.js). Dosya Yöneticisi ve büyük-dosya yüklemeleri bu VARSAYILANLARI kullanır.
        const u = getUploadCfg();
        const concSel = h('select', { class: 'input' }, [1, 2, 3, 4, 5, 6].map(n => h('option', { value: n, selected: u.concurrency === n }, String(n))));
        concSel.addEventListener('change', () => { setUploadCfg({ concurrency: Number(concSel.value) }); toast('Yükleme ayarı kaydedildi'); });
        const speed = h('input', { class: 'input', type: 'number', min: '0', step: '64', value: String(u.rateKBps), style: { maxWidth: '160px' } });
        speed.addEventListener('change', () => { const v = Math.max(0, Number(speed.value) || 0); speed.value = String(v); setUploadCfg({ rateKBps: v }); toast(v ? t('Üst hız: {v} KB/sn', { v }) : 'Yükleme hızı sınırsız'); });
        return card('Yükleme', 'Bu cihazdan yapılan dosya yüklemeleri için varsayılanlar. Aynı anda birden çok dosya paralel yüklenir; toplam hız sınırını tüm yüklemeler paylaşır.',
          line('Paralel yükleme sayısı', 'Aynı anda en çok kaç dosya yüklensin (1–6)', concSel),
          line('Maksimum yükleme hızı (KB/sn, 0 = sınırsız)', 'Tüm yüklemelerin toplam üst hızı', speed),
          h('p', { class: 'small muted' }, 'Hızı sınırlamak, büyük bir toplu aktarımın tüm bağlantıyı doldurup fabrika cihazlarını (ör. saha ajanı) çevrimdışı bırakmasını önler. Yükleme penceresinden de aktarım sürerken değiştirebilirsiniz.')); } },
    { key: 'account', title: 'Hesap', desc: 'Kullanıcı bilgileri, şifre, PIN, yüz ile giriş', icon: 'person',
      body: () => card('Hesap', null,
        h('div', { class: 'set-account' }, avatar(ctx.user, 'lg'), h('div', null, h('b', null, ctx.user.full_name), h('div', { class: 'small muted' }, ctx.user.username))),
        h('dl', { class: 'sys-kv' }, h('dt', null, 'Roller'), h('dd', null, (ctx.user.master ? [...(ctx.user.real_roles || []), 'MASTER (tüm yetkiler)'] : ctx.user.roles).join(', ') || '—'),
          h('dt', null, 'Modüller'), h('dd', null, modules.map(m => m.title).join(', ') || '—')),
        h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: () => changePassword() }, 'Şifremi Değiştir')),
        h('h4', { class: 'set-sub' }, 'PIN ile giriş'),
        h('p', { class: 'small muted' }, 'Bu cihazda bir kez şifreyle giriş yaptıktan sonra giriş ekranında adınıza dokunup 4 haneli PIN ile girebilirsiniz.'),
        pinToggle,
        ctx.user.has_pin ? h('div', { class: 'set-actions left' }, h('button', { class: 'btn', type: 'button', onclick: () => pinModal(true) }, 'PIN\'i Değiştir')) : null,
        faceSection(ctx)) },   // Yüz ile giriş: tanıt / ikinci tarama / kip / sil (modules/facesetup.js)
  ]).filter(x => x.key !== 'mascot' || ctx.user.ai);   // Claude API anahtarı yoksa maskot ayarı da gizli
  // Mobilde iOS Ayarlar gibi: gruplanmış renkli ikonlu satır listesi; kategoriye dokununca alt-sayfa açılır.
  const COLORS = { ui: '#0a84ff', notifications: '#ff3b30', sounds: '#ff2d55', screensaver: '#5856d6', voice: '#34c759',
    radio: '#ff9500', holiday: '#ff9f0a', mailboxes: '#1d9bf0', social: '#ff2d55', mascot: '#af52de', dnd: '#ff9f0a', privacy: '#8e8e93', mydata: '#30d158', dashboard: '#30b0c7', upload: '#5ac8fa', account: '#007aff' };
  const SECTIONS = [['ui', 'holiday', 'sounds', 'screensaver', 'mascot'], ['notifications', 'dnd', 'privacy', 'mydata'], ['voice', 'radio'], ['mailboxes', 'social'], ['dashboard', 'upload']];
  const used = new Set([...SECTIONS.flat(), 'account']);   // hesap, en üstte iPhone tarzı kart olarak gösterilir
  const rest = GROUPS.filter(gr => !used.has(gr.key)).map(gr => gr.key);
  const allSections = rest.length ? [...SECTIONS, rest] : SECTIONS;
  const acc = GROUPS.find(gr => gr.key === 'account');
  const masterList = () => h('div', { class: 'set-ios' },
    acc ? h('a', { class: 'ios-account', href: '#/settings/account' },
      avatar(ctx.user, 'lg'),
      h('span', { class: 'ios-acc-info' }, h('b', null, ctx.user.full_name), h('small', null, ctx.user.email || ctx.user.username)),
      h('span', { class: 'ios-chev' })) : null,
    allSections.map(keys => {
      const rows = keys.map(k => GROUPS.find(gr => gr.key === k)).filter(Boolean);
      return rows.length ? h('div', { class: 'ios-group' }, rows.map(gr => h('a', { class: 'ios-row', href: `#/settings/${gr.key}` },
        h('span', { class: 'ios-ico', style: { background: COLORS[gr.key] || '#8e8e93' } }, segIconByKey(gr.icon)),
        h('span', { class: 'ios-label' }, h('b', null, gr.title), h('small', null, gr.desc)),
        h('span', { class: 'ios-chev' })))) : null;
    }).filter(Boolean));

  const SUBTITLE = 'Kişisel tercihleriniz · değişiklikler hemen uygulanır ve hesabınıza kaydedilir';
  const draw = () => {
    const g = GROUPS.find(x => x.key === sub) || GROUPS[0];
    if (SET_MQ.matches) {
      if (sub) clear(view, pageHead(g.title, { back: '#/settings', sub: g.desc }), h('div', { class: 'set-detail set-detail-solo' }, g.body()));
      else clear(view, masterList());   // mobil ana liste: başlık / geri / açıklama gösterilmez (iOS tarzı)
    } else {
      clear(view, pageHead('Kişisel Ayarlar', { back: '#/', sub: SUBTITLE }),
        h('div', { class: 'set-layout' },
          h('nav', { class: 'card set-nav' }, GROUPS.map(x => h('a', { href: `#/settings/${x.key}`, class: x === g ? 'on' : '' },
            h('span', { class: 'set-ico' }, segIconByKey(x.icon)), h('span', null, h('b', null, x.title), h('small', null, x.desc))))),
          h('div', { class: 'set-detail' }, g.body())));
    }
  };
  _setRedraw = draw;
  draw();
}
