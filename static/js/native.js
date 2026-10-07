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
  function polish() {
    try { P.StatusBar && P.StatusBar.setStyle && P.StatusBar.setStyle({ style: 'DARK' }); } catch (e) {}
    try { P.SplashScreen && P.SplashScreen.hide && P.SplashScreen.hide(); } catch (e) {}
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

  function start() { polish(); initNet(); initPush(); initGeo(); initDevice(); }
  if (document.readyState === 'complete' || document.readyState === 'interactive') start();
  else document.addEventListener('DOMContentLoaded', start);
})();
