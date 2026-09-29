// Ayarlar (kullanıcı menüsü): kişisel tercihler. Sunucuda kullanıcıya bağlı saklanır (users.prefs.settings) ve her cihazda
// aynı uygulanır. Bölümler: Arayüz, Bildirimler, Sesler, Gizlilik, Pano, Hesap. Değişiklik anında uygulanır ve kaydedilir.
import { api } from '../api.js';
import { applySettings } from '../prefs.js';
import { ANIMATIONS, showScreensaver } from '../screensaver.js';
import { DEFAULTS, EVENTS, SOUND_NAMES, playSound } from '../sounds.js';
import { segIconByKey } from '../segicons.js';
import { avatar, clear, confirmDialog, field, h, modal, pageHead, segmented, toast } from '../ui.js';

export async function renderSettings(view, ctx, { changePassword, modules }, sub) {
  const cur = ctx.user.prefs?.settings || {};
  let theme0;
  try { theme0 = localStorage.getItem('caymaz.theme') || 'light'; } catch { theme0 = 'light'; }
  const s = {
    theme: cur.theme || theme0, scale: cur.scale || 1, compact: !!cur.compact, motion: !!cur.motion, start: cur.start || 'dashboard',
    flash: cur.flash !== false, flashSec: cur.flashSec || 3, desktop: !!cur.desktop,
    sound: { on: true, volume: 0.7, map: {}, quiet: { on: false, from: '22:00', to: '08:00' }, ...(cur.sound || {}) },
    privacy: { hide_online: false, hide_read: false, no_messages: false, ...(cur.privacy || {}) },
    screensaver: { on: false, after: 300, anim: 'globe', lock: true, ...(cur.screensaver || {}) },
  };
  let timer;
  const save = (msg = 'Ayarlar kaydedildi') => {
    applySettings(s);
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
  const scaleSeg = segmented([['0.9', 'Küçük'], ['1', 'Normal'], ['1.1', 'Büyük'], ['1.25', 'Çok büyük']], String(s.scale), v => { s.scale = Number(v); save(); });
  const startSel = h('select', { class: 'input' }, h('option', { value: 'dashboard' }, 'Kişisel pano'),
    modules.map(m => h('option', { value: m.key, selected: s.start === m.key }, m.title)));
  startSel.addEventListener('change', () => { s.start = startSel.value; save(); });

  // ---------- Bildirimler
  const flashSel = h('select', { class: 'input' }, [3, 5, 8, 12].map(n => h('option', { value: n, selected: s.flashSec === n }, `${n} saniye`)));
  flashSel.addEventListener('change', () => { s.flashSec = Number(flashSel.value); save(); });
  const deskState = h('small', { class: 'set-state' });
  const syncDesk = () => {
    const p = 'Notification' in window ? Notification.permission : 'unsupported';
    deskState.textContent = p === 'granted' ? 'Tarayıcı izni verildi' : p === 'denied' ? 'Tarayıcı izni reddedilmiş (tarayıcı ayarlarından açın)'
      : p === 'unsupported' ? 'Bu tarayıcı desteklemiyor' : 'İzin istenecek';
  };
  syncDesk();

  // ---------- Sesler
  const vol = h('input', { type: 'range', min: 0, max: 100, step: 5, value: Math.round(s.sound.volume * 100), class: 'set-range' });
  const volTxt = h('b', null, `%${vol.value}`);
  vol.addEventListener('input', () => { volTxt.textContent = `%${vol.value}`; });
  vol.addEventListener('change', () => { s.sound.volume = vol.value / 100; save(); playSound(s.sound.map.notification || DEFAULTS.notification, s.sound.volume); });
  const rows = h('div', { class: 'set-sounds' });
  for (const [key, label, desc] of EVENTS) {
    const sel = h('select', { class: 'input' }, SOUND_NAMES.map(n => h('option', { value: n, selected: (s.sound.map[key] || DEFAULTS[key]) === n },
      n === DEFAULTS[key] ? `${n} (varsayılan)` : n)));
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

  // ---------- Sol: ayar grupları, sağ: seçilen grubun ayrıntısı (#/settings/<grup>)
  const GROUPS = [
    { key: 'ui', title: 'Arayüz', desc: 'Tema, boyut, görünüm, açılış sayfası', icon: 'card',
      body: () => card('Arayüz', 'Uygulamanın görünümü ve açılış sayfası.',
        line('Tema', 'Koyu tema gece ve karanlık ortam için; "Sisteme göre" cihazın ayarını izler', themeSeg),
        line('Yazı ve öğe boyutu', 'Sayfa içeriğini büyütür / küçültür', scaleSeg),
        toggle(s, 'compact', 'Sıkı görünüm', 'Kart ve tablo boşluklarını azaltır, ekrana daha çok bilgi sığar'),
        toggle(s, 'motion', 'Hareketleri azalt', 'Geçiş ve animasyonları kapatır'),
        line('Açılış sayfası', 'Giriş yapınca açılacak sayfa', startSel)) },
    { key: 'notifications', title: 'Bildirimler', desc: 'Bildirim kutusu, masaüstü bildirimi', icon: 'bell',
      body: () => card('Bildirimler', 'Yeni uyarı, bildirim ya da mesaj geldiğinde nasıl haber verileceği.',
        toggle(s, 'flash', 'Sağ üstte bildirim kutusu', 'Yeni uyarı, bildirim ya da mesajda kısa süre görünen kutu'),
        line('Kutu görünme süresi', null, flashSel),
        toggle(s, 'desktop', 'Masaüstü bildirimi', 'Sekme arka plandayken işletim sisteminin bildirimiyle haber ver', async cb => {
          if (cb.checked && 'Notification' in window && Notification.permission === 'default') await Notification.requestPermission();
          if (cb.checked && (!('Notification' in window) || Notification.permission !== 'granted')) { cb.checked = false; s.desktop = false; }
          syncDesk();
        }), deskState) },
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
    { key: 'privacy', title: 'Gizlilik', desc: 'Çevrimiçi durumu, okundu bilgisi, mesajlar', icon: 'lock',
      body: () => card('Gizlilik', 'Diğer kullanıcıların sizinle ilgili neler görebileceği.',
        toggle(s.privacy, 'hide_online', 'Çevrimiçi durumumu gizle', 'Aktif kullanıcılar listesinde ve mesajlaşmada görünmezsiniz (sistem yöneticisi hariç)'),
        toggle(s.privacy, 'hide_read', 'Okundu bilgisi gönderme', 'Mesajlarda mavi çift tik gönderilmez; siz de başkalarınınkini görmezsiniz'),
        toggle(s.privacy, 'no_messages', 'Mesaj almayı kapat', 'Diğer kullanıcılar size yeni mesaj gönderemez')) },
    { key: 'dashboard', title: 'Pano', desc: 'Ana sayfa kutucukları', icon: 'grid',
      body: () => card('Pano', 'Ana sayfadaki kutucuk düzeniniz. Kutucukları ana sayfada "Panoyu Düzenle" ile değiştirebilirsiniz.',
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
        h('dl', { class: 'sys-kv' }, h('dt', null, 'Roller'), h('dd', null, ctx.user.roles.join(', ') || '—'),
          h('dt', null, 'Modüller'), h('dd', null, modules.map(m => m.title).join(', ') || '—')),
        h('div', { class: 'set-actions left' }, h('button', { class: 'btn primary', type: 'button', onclick: () => changePassword() }, 'Şifremi Değiştir')),
        h('h4', { class: 'set-sub' }, 'PIN ile giriş'),
        h('p', { class: 'small muted' }, 'Bu cihazda bir kez şifreyle giriş yaptıktan sonra giriş ekranında adınıza dokunup 4 haneli PIN ile girebilirsiniz.'),
        pinToggle,
        ctx.user.has_pin ? h('div', { class: 'set-actions left' }, h('button', { class: 'btn', type: 'button', onclick: () => pinModal(true) }, 'PIN\'i Değiştir')) : null) },
  ];
  const g = GROUPS.find(x => x.key === sub) || GROUPS[0];
  clear(view,
    pageHead('Ayarlar', { back: '#/', sub: 'Kişisel tercihleriniz · değişiklikler hemen uygulanır ve hesabınıza kaydedilir' }),
    h('div', { class: 'set-layout' },
      h('nav', { class: 'card set-nav' }, GROUPS.map(x => h('a', { href: `#/settings/${x.key}`, class: x === g ? 'on' : '' },
        h('span', { class: 'set-ico' }, segIconByKey(x.icon)), h('span', null, h('b', null, x.title), h('small', null, x.desc))))),
      h('div', { class: 'set-detail' }, g.body())));
}
