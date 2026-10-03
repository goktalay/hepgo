// Ayarlar (kullanıcı menüsü): kişisel tercihler. Sunucuda kullanıcıya bağlı saklanır (users.prefs.settings) ve her cihazda
// aynı uygulanır. Bölümler: Arayüz, Bildirimler, Sesler, Gizlilik, Pano, Hesap. Değişiklik anında uygulanır ve kaydedilir.
import { api } from '../api.js';
import { applySettings, deviceNotify, setDeviceNotify } from '../prefs.js';
import { ANIMATIONS, showScreensaver } from '../screensaver.js';
import { DEFAULTS, EVENTS, SOUND_NAMES, playSound } from '../sounds.js';
import { segIconByKey } from '../segicons.js';
import { disablePush, enablePush, pushState, pushSupport } from '../push.js';
import { CALL_BACKGROUNDS, CALL_BG_LABELS } from './voice.js';
import { MASCOT_LIST, mascotSvg, setMascot, applyMascotHidden } from './mascot.js';
import { avatar, clear, confirmDialog, field, fmtDateTime, h, modal, pageHead, segmented, t, toast, toastError } from '../ui.js';
import { setLang, getLang } from '../i18n.js';

// Mobilde (≤800px) Ayarlar iOS tarzı ana liste + alt-sayfa olur; görünüm genişliği değişince yeniden çizilir.
const SET_MQ = matchMedia('(max-width: 800px)');
let _setRedraw = null;
SET_MQ.addEventListener('change', () => { if (_setRedraw && location.hash.startsWith('#/settings')) _setRedraw(); });

export async function renderSettings(view, ctx, { changePassword, modules }, sub) {
  const cur = ctx.user.prefs?.settings || {};
  let theme0;
  try { theme0 = localStorage.getItem('caymaz.theme') || 'light'; } catch { theme0 = 'light'; }
  const s = {
    theme: cur.theme || theme0, scale: cur.scale || 1, compact: !!cur.compact, motion: !!cur.motion, start: cur.start || 'dashboard',
    lang: cur.lang || getLang() || 'tr',
    flash: cur.flash !== false, flashSec: cur.flashSec || 3, desktop: !!cur.desktop,
    sound: { on: true, volume: 0.7, map: {}, quiet: { on: false, from: '22:00', to: '08:00' }, ...(cur.sound || {}) },
    privacy: { hide_online: false, hide_read: false, hide_delivered: false, no_messages: false, ...(cur.privacy || {}) },
    screensaver: { on: false, after: 300, anim: 'globe', lock: true, ...(cur.screensaver || {}) },
    mascot: cur.mascot || 'kubbe',
    mascotStyle: cur.mascotStyle || 'samimi',
    dnd: { calls: false, messages: false, until: null, dur: 'always', ...(cur.dnd || {}) },
    muteNotif: Array.isArray(cur.muteNotif) ? cur.muteNotif : [],
    muteAlert: Array.isArray(cur.muteAlert) ? cur.muteAlert : [],
    toolbarAlign: cur.toolbarAlign || 'center',
    textCase: ['title', 'upper', 'lower'].includes(cur.textCase) ? cur.textCase : 'original',
    feedView: cur.feedView === 'map' ? 'map' : 'feed',
    feedFullMobile: !!cur.feedFullMobile,
    colors: (cur.colors && typeof cur.colors === 'object') ? { light: {}, dark: {}, ...cur.colors } : { light: {}, dark: {} },
    background: cur.background || '',
  };
  let timer;
  const save = (msg = 'Ayarlar kaydedildi') => {
    applySettings(s);
    try {   // giriş ekranı da aynı açılsın diye cihazda yansıt (tema/boyut gibi)
      localStorage.setItem('caymaz.toolbarAlign', s.toolbarAlign || 'center');
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
  const card = (title, sub, ...kids) => h('section', { class: 'card card-pad set-card' }, h('h3', null, title), sub ? h('p', { class: 'small muted' }, sub) : null, ...kids);

  // ---------- Arayüz
  const themeSeg = segmented([['light', 'Açık tema'], ['dark', 'Koyu tema'], ['system', 'Sisteme göre']], s.theme, v => { s.theme = v; save(); });
  // Dil: arayüz ve yazdırma şablonları seçilen dilde görünür. Şimdilik Türkçe + İngilizce.
  const langSeg = segmented([['tr', 'Türkçe'], ['en', 'English'], ['de', 'Deutsch'], ['fr', 'Français'], ['es', 'Español'], ['ar', 'العربية'], ['ru', 'Русский']], s.lang, v => { s.lang = v; setLang(v); save('Dil güncellendi'); });
  const scaleSeg = segmented([['0.9', 'Küçük'], ['1', 'Normal'], ['1.1', 'Büyük'], ['1.25', 'Çok büyük']], String(s.scale), v => { s.scale = Number(v); save(); });
  const startSel = h('select', { class: 'input' }, h('option', { value: 'dashboard' }, 'Kişisel pano'),
    modules.map(m => h('option', { value: m.key, selected: s.start === m.key }, m.title)));
  startSel.addEventListener('change', () => { s.start = startSel.value; save(); });
  const textCaseSeg = segmented([['original', 'Orijinal'], ['title', 'Yazım Düzeni'], ['upper', 'Tamamı Büyük'], ['lower', 'Tamamı Küçük']],
    s.textCase, v => { s.textCase = v; save('Metin biçimi güncellendi'); });

  // ---------- Görünüm & Renkler (MERKEZİ: üst bar, alt bar, footer, zemin — aktif temaya göre; modül içeriğine dokunulmaz)
  const alignSeg = segmented([['left', 'Sol'], ['center', 'Orta'], ['right', 'Sağ']], s.toolbarAlign || 'center', v => { s.toolbarAlign = v; save(); });
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
  const anims = h('div', { class: 'set-anims' });
  const drawAnims = () => clear(anims, ANIMATIONS.map(([k, t, d]) => h('button', { type: 'button', class: `set-anim ${s.screensaver.anim === k ? 'on' : ''}`,
    onclick: () => { s.screensaver.anim = k; save(); drawAnims(); } }, h('b', null, t), h('small', null, d))));
  drawAnims();

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
  const notifTypesBox = () => {
    const box = h('div', { class: 'set-types' }, h('div', { class: 'small muted' }, 'Yükleniyor…'));
    api.get('/api/notifications/types').then(d => {
      const rows = [h('h4', { class: 'set-sub' }, 'Bildirim türleri'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Almak istemediğiniz bildirimleri kapatın.')];
      if (!d.notifications.length) rows.push(h('p', { class: 'small muted' }, 'Size uygun bildirim türü yok.'));
      for (const t of d.notifications) rows.push(typeToggle(t.title, !s.muteNotif.includes(t.key), on => {
        s.muteNotif = s.muteNotif.filter(k => k !== t.key); if (!on) s.muteNotif.push(t.key); save('Bildirim tercihleri güncellendi');
      }));
      if (d.alerts.length) {
        rows.push(h('h4', { class: 'set-sub' }, 'Uyarı türleri'),
          h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Üretim / yazıcı uyarıları. Kritik güvenlik uyarıları kapatılamaz.'));
        for (const a of d.alerts) rows.push(typeToggle(a.title, !s.muteAlert.includes(a.key), on => {
          s.muteAlert = s.muteAlert.filter(k => k !== a.key); if (!on) s.muteAlert.push(a.key); save('Uyarı tercihleri güncellendi');
        }, a.critical, a.critical ? 'Kritik güvenlik uyarısı — kapatılamaz' : null));
      }
      clear(box, rows);
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

  // ---------- Rahatsız Etmeyin (arama / mesaj; süreli ya da sürekli)
  const dndUntil = dur => {
    if (dur === 'always') return null;
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
        line('Tema', 'Koyu tema gece ve karanlık ortam için; "Sisteme göre" cihazın ayarını izler', themeSeg),
        line('Yazı ve öğe boyutu', 'Sayfa içeriğini büyütür / küçültür', scaleSeg),
        toggle(s, 'compact', 'Sıkı görünüm', 'Kart ve tablo boşluklarını azaltır, ekrana daha çok bilgi sığar'),
        toggle(s, 'motion', 'Hareketleri azalt', 'Geçiş ve animasyonları kapatır'),
        line('Metin biçimi', 'Tüm görünen metinlerin yazımı (kodlar ve giriş alanları hariç)', textCaseSeg),
        line('Açılış sayfası', 'Giriş yapınca açılacak sayfa', startSel)) },
    { key: 'appearance', title: 'Görünüm & Renkler', desc: 'Üst/alt bar, footer, zemin renkleri; gövde arka planı; toolbar hizası', icon: 'card', body: appearanceBody },
    { key: 'notifications', title: 'Bildirimler', desc: 'Bildirim kutusu, masaüstü bildirimi', icon: 'bell',
      body: () => card('Bildirimler', 'Yeni uyarı, bildirim ya da mesaj geldiğinde nasıl haber verileceği.',
        toggle(s, 'flash', 'Sağ üstte bildirim kutusu', 'Yeni uyarı, bildirim ya da mesajda kısa süre görünen kutu'),
        line('Kutu görünme süresi', null, flashSel),
        h('h4', { class: 'set-sub' }, 'Bu cihaz'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'Masaüstü bildirimi her cihazda ayrı açılır ve o cihazın tarayıcı iznini gerektirir. Telefonunuzda ayrıca buradan açıp izin vermelisiniz.'),
        deviceDesk, deskState,
        pushBox(),
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
        h('div', { class: 'set-row' }, h('div', { class: 'grow' }, h('b', null, 'Animasyon'), h('small', null, 'Seçip "Önizle" ile deneyin'))),
        anims,
        h('div', { class: 'set-actions' }, h('button', { class: 'btn primary', type: 'button', onclick: () => showScreensaver(s.screensaver.anim, { preview: true }) }, '▶ Önizle'))) },
    { key: 'voice', title: 'Görüşme Ayarları', desc: 'Sesli görüşme arka planı', icon: 'phone',
      body: () => {
        const grid = h('div', { class: 'set-bg-grid' });
        const drawBg = () => clear(grid, Object.keys(CALL_BACKGROUNDS).map(k => h('button', {
          type: 'button', class: `set-bg ${(s.callBg || 'aurora') === k ? 'on' : ''}`, style: { background: CALL_BACKGROUNDS[k] },
          onclick: () => { s.callBg = k; save('Görüşme arka planı güncellendi'); drawBg(); } },
          h('span', { class: 'set-bg-name' }, CALL_BG_LABELS[k]), (s.callBg || 'aurora') === k ? h('span', { class: 'set-bg-on' }, '✓') : null)));
        drawBg();
        return card('Görüşme Ayarları', 'Sesli görüşme ekranının arka planını seçin. Gelen arama ve görüşme ekranında uygulanır.', grid);
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
    { key: 'mascot', title: 'Maskot', desc: 'Köşedeki yapay zeka asistanı karakteri', icon: 'card',
      body: () => {
        const grid = h('div', { class: 'set-mascot-grid' });
        const draw = () => clear(grid, MASCOT_LIST.map(m => h('button', {
          type: 'button', class: `set-mascot ${s.mascot === m.id ? 'on' : ''}`,
          onclick: () => { s.mascot = m.id; setMascot(m.id); save('Maskot değiştirildi'); draw(); } },
          h('span', { class: 'set-mascot-fig' }, mascotSvg(m.id)),
          h('b', null, m.name), h('small', null, m.desc),
          s.mascot === m.id ? h('span', { class: 'set-mascot-on' }, '✓') : null)));
        draw();
        const styleSel = h('select', { class: 'input' }, [['samimi', 'Samimi (varsayılan)'], ['ciddi', 'Ciddi ve profesyonel'],
          ['sakaci', 'Şakacı'], ['alayci', 'Alaycı (iğneleyici)'], ['coskulu', 'Coşkulu'], ['bilgic', 'Bilgiç / akademik']]
          .map(([v, l]) => h('option', { value: v, selected: s.mascotStyle === v }, l)));
        styleSel.addEventListener('change', () => { s.mascotStyle = styleSel.value; save('Konuşma tarzı güncellendi'); });
        const showChk = h('input', { type: 'checkbox', checked: !s.mascotOff });
        showChk.addEventListener('change', () => {
          s.mascotOff = !showChk.checked; applyMascotHidden(s.mascotOff); save(showChk.checked ? 'Maskot açıldı' : 'Maskot gizlendi');
        });
        return card('Maskot', 'Ekranın köşesinde duran, sürekli hareket eden ve tıklayınca yapay zekayla sohbet açan asistanınızı seçin. Maskotu köşede sürükleyerek istediğiniz yere taşıyabilirsiniz.',
          h('label', { class: 'set-toggle' }, showChk, h('span', null, h('b', null, 'Maskotu göster'), h('small', null, 'Köşedeki yapay zeka asistanını gösterir ya da gizler'))),
          h('h4', { class: 'set-sub' }, 'Karakter'),
          grid,
          h('h4', { class: 'set-sub' }, 'Konuşma tarzı'),
          line('Asistanın üslubu', 'Cevapların tonu bu seçime göre değişir', styleSel));
      } },
    { key: 'dnd', title: 'Rahatsız Etmeyin', desc: 'Aramalara / mesajlara süreli ya da sürekli kapan', icon: 'bell',
      body: () => {
        const status = h('div', { class: `set-dnd-status ${(s.dnd.calls || s.dnd.messages) ? 'on' : ''}` });
        const refresh = () => {
          const active = s.dnd.calls || s.dnd.messages;
          const ch = [s.dnd.calls ? 'aramalar' : null, s.dnd.messages ? 'mesajlar' : null].filter(Boolean).join(' ve ');
          status.className = `set-dnd-status ${active ? 'on' : ''}`;
          status.textContent = !active ? '🟢 Şu an herkese açıksınız.'
            : t('🔕 {ch} kapalı — {rest}', { ch: ch[0].toUpperCase() + ch.slice(1), rest: s.dnd.until ? 'bitiş: ' + fmtDateTime(s.dnd.until) : 'sürekli (siz açana kadar)' });
        };
        const onDnd = () => { s.dnd.until = (s.dnd.calls || s.dnd.messages) ? dndUntil(s.dnd.dur || 'always') : null; refresh(); };
        const durSel = h('select', { class: 'input' }, [['always', 'Sürekli (ben açana kadar)'], ['1', '1 saat'], ['2', '2 saat'],
          ['4', '4 saat'], ['today', 'Bugün gece yarısına kadar']].map(([v, l]) => h('option', { value: v, selected: (s.dnd.dur || 'always') === v }, l)));
        durSel.addEventListener('change', () => { s.dnd.dur = durSel.value; onDnd(); save('Rahatsız etmeyin güncellendi'); });
        refresh();
        return card('Rahatsız Etmeyin', 'Kendinizi aramalara ve/veya mesajlara kapatabilirsiniz. Süre seçebilir ya da sürekli kapalı kalabilirsiniz; süre dolunca otomatik açılır.',
          status,
          toggle(s.dnd, 'calls', 'Aramalara kapat', 'Kimse sizi sesli arayamaz; arayan “rahatsız etmeyin” uyarısı görür', onDnd),
          toggle(s.dnd, 'messages', 'Mesajlara kapat', 'Kimse size yeni mesaj gönderemez', onDnd),
          line('Süre', 'Kapalı kalma süresi; “Sürekli” seçilirse siz açana kadar', durSel)); } },
    { key: 'privacy', title: 'Gizlilik', desc: 'Çevrimiçi durumu, okundu / iletildi bilgisi, mesajlar', icon: 'lock',
      body: () => card('Gizlilik', 'Diğer kullanıcıların sizinle ilgili neler görebileceği.',
        toggle(s.privacy, 'hide_online', 'Çevrimiçi durumumu gizle', 'Aktif kullanıcılar listesinde ve mesajlaşmada görünmezsiniz (sistem yöneticisi hariç)'),
        h('h4', { class: 'set-sub' }, 'Mesaj bilgileri'),
        h('p', { class: 'small muted', style: { marginTop: '-4px' } }, 'WhatsApp’taki gibi: ✓ gönderildi · ✓✓ iletildi · mavi ✓✓ okundu. Bir bilgiyi kapatırsanız karşı taraflar onu sizden alamaz, siz de başkalarınınkini göremezsiniz.'),
        toggle(s.privacy, 'hide_read', 'Okundu bilgisini gönderme', 'Mesajı açtığınızda karşı tarafta mavi çift tik görünmez'),
        toggle(s.privacy, 'hide_delivered', 'İletildi bilgisini gönderme', 'Mesaj cihazınıza ulaştığında karşı tarafta gri çift tik görünmez'),
        h('h4', { class: 'set-sub' }, 'Diğer'),
        toggle(s.privacy, 'no_messages', 'Mesaj almayı kapat', 'Diğer kullanıcılar size yeni mesaj gönderemez')) },
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
    { key: 'account', title: 'Hesap', desc: 'Kullanıcı bilgileri, şifre, PIN', icon: 'person',
      body: () => card('Hesap', null,
        h('div', { class: 'set-account' }, avatar(ctx.user, 'lg'), h('div', null, h('b', null, ctx.user.full_name), h('div', { class: 'small muted' }, ctx.user.username))),
        h('dl', { class: 'sys-kv' }, h('dt', null, 'Roller'), h('dd', null, (ctx.user.master ? [...(ctx.user.real_roles || []), 'MASTER (tüm yetkiler)'] : ctx.user.roles).join(', ') || '—'),
          h('dt', null, 'Modüller'), h('dd', null, modules.map(m => m.title).join(', ') || '—')),
        h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: () => changePassword() }, 'Şifremi Değiştir')),
        h('h4', { class: 'set-sub' }, 'PIN ile giriş'),
        h('p', { class: 'small muted' }, 'Bu cihazda bir kez şifreyle giriş yaptıktan sonra giriş ekranında adınıza dokunup 4 haneli PIN ile girebilirsiniz.'),
        pinToggle,
        ctx.user.has_pin ? h('div', { class: 'set-actions left' }, h('button', { class: 'btn', type: 'button', onclick: () => pinModal(true) }, 'PIN\'i Değiştir')) : null) },
  ]).filter(x => x.key !== 'mascot' || ctx.user.ai);   // Claude API anahtarı yoksa maskot ayarı da gizli
  // Mobilde iOS Ayarlar gibi: gruplanmış renkli ikonlu satır listesi; kategoriye dokununca alt-sayfa açılır.
  const COLORS = { ui: '#0a84ff', notifications: '#ff3b30', sounds: '#ff2d55', screensaver: '#5856d6', voice: '#34c759',
    radio: '#ff9500', mascot: '#af52de', dnd: '#ff9f0a', privacy: '#8e8e93', dashboard: '#30b0c7', account: '#007aff' };
  const SECTIONS = [['ui', 'sounds', 'screensaver', 'mascot'], ['notifications', 'dnd', 'privacy'], ['voice', 'radio'], ['dashboard']];
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
