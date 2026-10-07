// HEPGO native köprüsü (Capacitor) — YALNIZ iOS/Android uygulama kabuğunda çalışır (window.Capacitor).
// Arayüz canlı web olarak kalır; bu dosya native PUSH kaydı (FCM/APNs) + KONUM gönderimi + ÇEVRİMDIŞI kaplaması ekler.
// Hosted Capacitor modunda yüklenir (app.js, native platform algılanınca <script> ile ekler). Normal tarayıcıda ÇALIŞMAZ.
(function () {
  var Cap = window.Capacitor;
  if (!Cap || !Cap.isNativePlatform || !Cap.isNativePlatform()) return;
  var P = Cap.Plugins || {};
  var platform = Cap.getPlatform ? Cap.getPlatform() : 'unknown';
  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).catch(function () {});
  }

  // ---------------------------------------------------------------- PUSH (Android=FCM, iOS=APNs)
  async function initPush() {
    var Push = P.PushNotifications;
    if (!Push) return;
    try {
      var perm = await Push.checkPermissions();
      if (perm.receive === 'prompt' || perm.receive === 'prompt-with-rationale') perm = await Push.requestPermissions();
      if (perm.receive !== 'granted') return;
      Push.addListener('registration', function (t) { post('/api/push/native-register', { platform: platform, token: t.value }); });
      Push.addListener('registrationError', function () {});
      Push.addListener('pushNotificationActionPerformed', function (ev) {
        // Bildirim yük'ündeki url DOĞRULANIR: yalnız AYNI KÖKEN bir yol/adres açılır (kötü amaçlı/bozuk yük
        // kimlik doğrulamalı WebView'i rastgele bir siteye yönlendirmesin). Aksi halde yok sayılır.
        var raw = ev && ev.notification && ev.notification.data && ev.notification.data.url;
        if (!raw) return;
        try {
          var u = new URL(raw, location.origin);
          if (u.origin === location.origin) location.href = u.href;
        } catch (e) { /* geçersiz url: yok say */ }
      });
      await Push.register();
    } catch (e) { /* ses yok, sessiz geç */ }
  }

  // ---------------------------------------------------------------- KONUM RIZASI (KVKK açık rıza)
  function consentDialog() {
    return new Promise(function (resolve) {
      var ov = document.createElement('div');
      ov.style.cssText = 'position:fixed;inset:0;z-index:2147483646;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(7,13,28,.6);backdrop-filter:blur(3px);font-family:system-ui,-apple-system,sans-serif';
      ov.innerHTML = '<div style="max-width:380px;width:100%;background:#fff;border-radius:16px;padding:22px;box-shadow:0 20px 60px rgba(7,13,28,.4)">'
        + '<div style="font-size:30px;text-align:center;margin-bottom:6px">📍</div>'
        + '<h2 style="margin:0 0 8px;font-size:18px;color:#0f172a;text-align:center">Konum takibine izin</h2>'
        + '<p style="margin:0 0 14px;font-size:13.5px;line-height:1.55;color:#475569">Çalışma saatlerinde iş süreçleri ve saha/güvenlik yönetimi için konumunuz uygulama tarafından kaydedilebilir. '
        + 'Bu KVKK kapsamında <b>açık rızanıza</b> bağlıdır; dilediğiniz zaman geri alabilirsiniz. Ayrıntı: Gizlilik Politikası.</p>'
        + '<div style="display:flex;gap:8px"><button id="hc-no" style="flex:1;padding:11px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;color:#334155;font:inherit;font-weight:600;cursor:pointer">Reddet</button>'
        + '<button id="hc-yes" style="flex:1;padding:11px;border-radius:10px;border:0;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;font:inherit;font-weight:600;cursor:pointer">Onaylıyorum</button></div></div>';
      document.body.appendChild(ov);
      ov.querySelector('#hc-yes').onclick = function () { ov.remove(); resolve(true); };
      ov.querySelector('#hc-no').onclick = function () { ov.remove(); resolve(false); };
    });
  }

  // ---------------------------------------------------------------- KONUM (arkaplanda periyodik gönderim)
  var lastSent = 0;
  function sendPing(lat, lng, acc, ts) {
    var now = Date.now();
    if (now - lastSent < 30000) return;   // en çok 30 sn'de bir gönder (pil/veri tasarrufu)
    lastSent = now;
    post('/api/location/ping', { lat: lat, lng: lng, acc: acc, at: new Date(ts || now).toISOString(), platform: platform });
  }
  async function initGeo() {
    var BG = P.BackgroundGeolocation;      // 7/24 arkaplan (foreground service) — varsa tercih edilir
    var Geo = P.Geolocation;               // yoksa ön plan izleyici
    if (!BG && !Geo) return;
    try {
      // KVKK açık rıza: sunucuda kayıtlı mı? Yoksa sor; reddedilirse konum ALINMAZ.
      var cs = await fetch('/api/location/consent', { credentials: 'include' }).then(function (r) { return r.json(); }).catch(function () { return {}; });
      var c = cs && cs.consent;
      if (!c) {
        var ok = await consentDialog();
        await post('/api/location/consent', { granted: ok });
        if (!ok) return;
      } else if (!c.granted) {
        return;   // daha önce reddetmiş
      }
      if (BG) {
        // Arkaplan izleyici: ekran kapalı/uygulama arkada iken de kalıcı bildirimle konum gönderir
        await BG.addWatcher({
          backgroundMessage: 'Çalışma saatlerinde konum takibi açık',
          backgroundTitle: 'HEPGO saha/güvenlik takibi',
          requestPermissions: true,
          stale: false,
          distanceFilter: 15,
        }, function (loc, err) {
          if (err) {
            if (err.code === 'NOT_AUTHORIZED') { /* kullanıcı reddetti; ayarlardan açabilir */ }
            return;
          }
          if (loc) sendPing(loc.latitude, loc.longitude, loc.accuracy, loc.time);
        });
        return;
      }
      // Yedek: ön plan izleyici (uygulama açıkken)
      var perm = await Geo.requestPermissions();
      if (perm.location !== 'granted' && perm.coarseLocation !== 'granted') return;
      Geo.watchPosition({ enableHighAccuracy: true, timeout: 20000, maximumAge: 10000 }, function (pos) {
        if (!pos || !pos.coords) return;
        sendPing(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, pos.timestamp);
      });
    } catch (e) { /* yut */ }
  }

  // ---------------------------------------------------------------- ÇEVRİMDIŞI KAPLAMASI (şık "yalnız çevrimiçi" ekranı)
  function overlay() {
    var el = document.getElementById('hepgo-offline');
    if (el) return el;
    el = document.createElement('iframe');
    el.id = 'hepgo-offline';
    el.src = '/static/offline.html';
    el.setAttribute('aria-hidden', 'true');
    el.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;border:0;z-index:2147483647;display:none;background:#0f1d3d';
    document.body.appendChild(el);
    return el;
  }
  function setOffline(off) {
    var el = overlay();
    if (off) { try { el.contentWindow.location.reload(); } catch (e) {} el.style.display = 'block'; }
    else { el.style.display = 'none'; }
  }
  async function initNet() {
    var Net = P.Network;
    if (!Net) return;
    try {
      var s = await Net.getStatus();
      setOffline(!s.connected);
      Net.addListener('networkStatusChange', function (st) { setOffline(!st.connected); });
    } catch (e) { /* yut */ }
  }

  // ---------------------------------------------------------------- Durum çubuğu / açılış ekranı (ufak dokunuşlar)
  // Durum çubuğunu (saat/ağ) üst header rengine uydur: overlay kapalı (içerik altına girmesin → fazla yükseklik olmaz),
  // zemin = header rengi, ikonlar zemin açıksa KOYU / koyuysa AÇIK (böylece görünür). Tema/sayfa değişince tazelenir.
  function rgbHex(m) { return '#' + m.slice(0, 3).map(function (x) { return ('0' + (Math.round(+x)).toString(16)).slice(-2); }).join(''); }
  function syncStatusBar() {
    var SB = P.StatusBar; if (!SB) return;
    try { SB.setOverlaysWebView && SB.setOverlaysWebView({ overlay: false }); } catch (e) {}
    try {
      var hdr = document.querySelector('.app-header');
      var bg = getComputedStyle(hdr || document.body).backgroundColor || '';
      var m = (bg.match(/\d+(?:\.\d+)?/g) || ['255', '255', '255']).map(Number);
      if (m.length >= 4 && m[3] === 0) m = [15, 29, 61];   // şeffafsa koyu varsay
      var lum = (0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2]) / 255;
      try { SB.setBackgroundColor && SB.setBackgroundColor({ color: rgbHex(m) }); } catch (e) {}
      try { SB.setStyle && SB.setStyle({ style: lum > 0.55 ? 'LIGHT' : 'DARK' }); } catch (e) {}   // LIGHT=koyu ikon
    } catch (e) {}
  }
  function polish() {
    syncStatusBar();
    try { P.SplashScreen && P.SplashScreen.hide && P.SplashScreen.hide(); } catch (e) {}
    try { addEventListener('hashchange', function () { setTimeout(syncStatusBar, 150); }); } catch (e) {}
    setTimeout(syncStatusBar, 500); setTimeout(syncStatusBar, 1800);   // tema/giriş sonrası yeniden
  }

  // ---------------------------------------------------------------- CİHAZ KÜNYESİ (giriş sonrası, yasal/teknik bilgiler)
  async function initDevice() {
    try { if (sessionStorage.getItem('hepgo.devsent') === '1') return; } catch (e) {}
    try {
      const Dev = P.Device;
      let info = {}, id = {};
      if (Dev) { try { info = await Dev.getInfo(); } catch (e) {} try { id = await Dev.getId(); } catch (e) {} }
      let app = {};
      if (P.App && P.App.getInfo) { try { app = await P.App.getInfo(); } catch (e) {} }
      const tz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return ''; } })();
      const body = {
        device_id: id.identifier || null,
        platform: info.platform || platform,
        model: info.model || null,
        manufacturer: info.manufacturer || null,
        os_version: [info.operatingSystem, info.osVersion].filter(Boolean).join(' ') || null,
        app_version: app.version || null,
        app_build: app.build || null,
        webview: info.webViewVersion || null,
        language: navigator.language || null,
        timezone: tz || null,
        screen: (screen && screen.width) ? `${screen.width}x${screen.height}@${window.devicePixelRatio || 1}` : null,
        ua: navigator.userAgent || null,
      };
      // Uç yalnız ERP (fabrika-yonetim) kökeninde + oturum varken 200 döner; değilse sessizce geçer
      const r = await fetch('/api/location/consent', { credentials: 'include' }).then(x => x.ok, () => false).catch(() => false);
      if (r === false) return;   // oturum yok / farklı köken → gönderme
      const res = await fetch('/api/device-info', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (res.ok) { try { sessionStorage.setItem('hepgo.devsent', '1'); } catch (e) {} }
    } catch (e) { /* yut */ }
  }

  // ---------------------------------------------------------------- İLK AÇILIŞ: tanıtım + izin ekranları (bir kez)
  const OB_KEY = 'hepgo.onboarded.v1';
  async function obGet() {
    try { if (P.Preferences) { const r = await P.Preferences.get({ key: OB_KEY }); return r && r.value === '1'; } } catch (e) {}
    try { return localStorage.getItem(OB_KEY) === '1'; } catch (e) { return false; }
  }
  async function obSet() {
    try { if (P.Preferences) await P.Preferences.set({ key: OB_KEY, value: '1' }); } catch (e) {}
    try { localStorage.setItem(OB_KEY, '1'); } catch (e) {}
  }
  const permApi = {
    notifCheck: async () => { try { return (await P.PushNotifications.checkPermissions()).receive; } catch (e) { return 'prompt'; } },
    notifReq: async () => { try { return (await P.PushNotifications.requestPermissions()).receive; } catch (e) { return 'denied'; } },
    geoCheck: async () => { try { return (await P.Geolocation.checkPermissions()).location; } catch (e) { return 'prompt'; } },
    geoReq: async () => { try { return (await P.Geolocation.requestPermissions()).location; } catch (e) { return 'denied'; } },
    camCheck: async () => { try { if (!navigator.permissions) return 'prompt'; const r = await navigator.permissions.query({ name: 'camera' }); return r.state === 'granted' ? 'granted' : r.state === 'denied' ? 'denied' : 'prompt'; } catch (e) { return 'prompt'; } },
    camReq: async () => { try { const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true }); s.getTracks().forEach(t => t.stop()); return 'granted'; } catch (e) { return 'denied'; } },
  };
  function obStyles() {
    if (document.getElementById('hepgo-ob-style')) return;
    const st = document.createElement('style'); st.id = 'hepgo-ob-style';
    st.textContent = `
      #hepgo-ob{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;color:#e8eefc;
        font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:radial-gradient(130% 150% at 0% 0%,#1e3a8a 0%,#0f1d3d 55%,#070d1c 100%);
        padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
      #hepgo-ob .ob-wrap{flex:1;display:flex;flex-direction:column;max-width:480px;width:100%;margin:0 auto;padding:24px}
      #hepgo-ob .ob-slides{flex:1;position:relative;overflow:hidden}
      #hepgo-ob .ob-s{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;opacity:0;transform:translateX(40px);transition:opacity .35s,transform .35s;pointer-events:none}
      #hepgo-ob .ob-s.on{opacity:1;transform:none;pointer-events:auto}
      #hepgo-ob .ob-ic{width:108px;height:108px;border-radius:26px;display:grid;place-items:center;font-size:52px;margin-bottom:20px;background:rgba(255,255,255,.06);box-shadow:0 16px 40px rgba(7,13,28,.5)}
      #hepgo-ob .ob-ic img{width:74px;height:74px;border-radius:18px}
      #hepgo-ob h2{font-size:23px;margin:0 0 10px}
      #hepgo-ob p{color:#aebbdc;margin:0 0 8px;line-height:1.6;font-size:15px;max-width:360px}
      #hepgo-ob .ob-why{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:14px 16px;margin:14px 0 6px;max-width:360px}
      #hepgo-ob .ob-why b{color:#dbe6ff}
      #hepgo-ob .ob-perm{margin-top:18px;min-width:190px;font:inherit;font-weight:600;font-size:15px;padding:13px 22px;border-radius:13px;border:0;cursor:pointer;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;box-shadow:0 10px 26px rgba(37,99,235,.35)}
      #hepgo-ob .ob-perm.granted{background:linear-gradient(135deg,#16a34a,#22c55e)}
      #hepgo-ob .ob-perm.denied{background:linear-gradient(135deg,#b45309,#d97706)}
      #hepgo-ob .ob-note{font-size:12.5px;color:#7f8db0;margin-top:12px;max-width:320px}
      #hepgo-ob .ob-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:14px}
      #hepgo-ob .ob-dots{display:flex;gap:7px}
      #hepgo-ob .ob-dots i{width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,.22);transition:background .2s,width .2s}
      #hepgo-ob .ob-dots i.on{background:#3b82f6;width:22px;border-radius:4px}
      #hepgo-ob .ob-btn{font:inherit;font-weight:600;padding:12px 22px;border-radius:12px;border:0;cursor:pointer;background:linear-gradient(135deg,#2563eb,#3b82f6);color:#fff;box-shadow:0 10px 26px rgba(37,99,235,.35)}
      #hepgo-ob .ob-skip{background:transparent;color:#7f8db0;padding:12px 6px;box-shadow:none}`;
    document.head.appendChild(st);
  }
  function initOnboarding() {
    return new Promise(async resolve => {
      if (await obGet()) return resolve();
      obStyles();
      const logo = location.origin + '/static/img/logo-mark.png?v=3';
      const STEPS = [
        { intro: true, icon: `<img src="${logo}" alt="">`, title: 'HEPGO\'ya hoş geldiniz', body: 'Fabrikanızı tek platformdan yönetin. Başlamadan önce birkaç izin isteyeceğiz; her birinin nedenini açıklayacağız.' },
        { key: 'notif', icon: '🔔', title: 'Bildirimler', why: 'Onay bekleyen işler, mesajlar, güvenlik ve üretim uyarıları anında size ulaşsın diye.', check: permApi.notifCheck, req: permApi.notifReq },
        { key: 'geo', icon: '📍', title: 'Konum', why: 'Çalışma saatlerinde saha ve güvenlik yönetimi için kullanılır. <b>KVKK açık rızanıza</b> bağlıdır; dilediğinizde geri alabilirsiniz. Sürekli takip için cihaz ayarından "Her zaman izin ver" gerekir.', check: permApi.geoCheck, req: permApi.geoReq },
        { key: 'cam', icon: '📷', title: 'Kamera ve Mikrofon', why: 'QR okuma, görüntülü/sesli görüşme ve belge/fotoğraf yükleme için gerekir. Yalnızca siz kullandığınızda erişilir.', check: permApi.camCheck, req: permApi.camReq },
        { done: true, icon: '✅', title: 'Her şey hazır', body: 'Artık giriş yapabilirsiniz. İzinleri daha sonra cihaz ayarlarından da değiştirebilirsiniz.' },
      ];
      const ov = document.createElement('div'); ov.id = 'hepgo-ob';
      const slides = document.createElement('div'); slides.className = 'ob-slides';
      const label = s => s === 'granted' ? '✓ İzinli' : s === 'denied' ? 'Ayarlardan izin verin' : 'İzin ver';
      const apply = (btn, s) => { btn.textContent = label(s); btn.classList.toggle('granted', s === 'granted'); btn.classList.toggle('denied', s === 'denied'); btn.disabled = s === 'granted'; };
      const els = STEPS.map(step => {
        const el = document.createElement('div'); el.className = 'ob-s';
        el.innerHTML = `<div class="ob-ic">${step.icon}</div><h2>${step.title}</h2>` +
          (step.body ? `<p>${step.body}</p>` : '') + (step.why ? `<div class="ob-why"><b>Neden?</b> ${step.why}</div>` : '');
        if (step.key) {
          const btn = document.createElement('button'); btn.className = 'ob-perm'; btn.type = 'button'; btn.textContent = 'İzin ver';
          btn.addEventListener('click', async () => { btn.disabled = true; btn.textContent = '…'; apply(btn, await step.req()); });
          step.check().then(s => { if (s && s !== 'yok') apply(btn, s); });
          el.appendChild(btn);
          const note = document.createElement('div'); note.className = 'ob-note'; note.textContent = 'İsterseniz "İleri" ile geçip izni sonra verebilirsiniz.'; el.appendChild(note);
          step._btn = btn;
        }
        slides.appendChild(el); return el;
      });
      const dots = document.createElement('div'); dots.className = 'ob-dots';
      STEPS.forEach(() => dots.appendChild(document.createElement('i')));
      const skip = document.createElement('button'); skip.className = 'ob-btn ob-skip'; skip.type = 'button'; skip.textContent = 'Atla';
      const next = document.createElement('button'); next.className = 'ob-btn'; next.type = 'button'; next.textContent = 'İleri';
      const foot = document.createElement('div'); foot.className = 'ob-foot'; foot.append(skip, dots, next);
      const wrap = document.createElement('div'); wrap.className = 'ob-wrap'; wrap.append(slides, foot);
      ov.appendChild(wrap); document.body.appendChild(ov);
      let idx = 0;
      const show = i => {
        idx = i;
        els.forEach((el, k) => el.classList.toggle('on', k === i));
        [...dots.children].forEach((d, k) => d.classList.toggle('on', k === i));
        next.textContent = STEPS[i].done ? 'Giriş yap' : 'İleri';
        skip.style.visibility = STEPS[i].done ? 'hidden' : 'visible';
        if (STEPS[i]._btn) STEPS[i].check().then(s => { if (s && s !== 'yok') apply(STEPS[i]._btn, s); });
      };
      const finish = async () => { await obSet(); ov.remove(); resolve(); };
      next.addEventListener('click', () => { if (idx >= STEPS.length - 1) finish(); else show(idx + 1); });
      skip.addEventListener('click', finish);
      show(0);
    });
  }

  async function start() {
    polish(); initNet();
    await initOnboarding();   // ilk açılışta tanıtım + izin ekranları (bir kez)
    initPush(); initGeo(); initDevice();
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive') start();
  else document.addEventListener('DOMContentLoaded', start);
})();
