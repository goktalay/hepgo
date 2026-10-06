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
        var url = ev && ev.notification && ev.notification.data && ev.notification.data.url;
        if (url) { try { location.href = url; } catch (e) {} }
      });
      await Push.register();
    } catch (e) { /* ses yok, sessiz geç */ }
  }

  // ---------------------------------------------------------------- KONUM (arkaplanda periyodik gönderim)
  var lastSent = 0;
  async function initGeo() {
    var Geo = P.Geolocation;
    if (!Geo) return;
    try {
      var perm = await Geo.requestPermissions();
      if (perm.location !== 'granted' && perm.coarseLocation !== 'granted') return;
      Geo.watchPosition({ enableHighAccuracy: true, timeout: 20000, maximumAge: 10000 }, function (pos) {
        if (!pos || !pos.coords) return;
        var now = Date.now();
        if (now - lastSent < 30000) return;   // en çok 30 sn'de bir gönder (pil/veri tasarrufu)
        lastSent = now;
        post('/api/location/ping', { lat: pos.coords.latitude, lng: pos.coords.longitude, acc: pos.coords.accuracy,
          at: new Date(pos.timestamp || now).toISOString(), platform: platform });
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

  function start() { polish(); initNet(); initPush(); initGeo(); }
  if (document.readyState === 'complete' || document.readyState === 'interactive') start();
  else document.addEventListener('DOMContentLoaded', start);
})();
