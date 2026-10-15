/* ============================================================
   FAZ18-DRON-EKRAN-DISI - Ekran disi dron gostergesi
   ------------------------------------------------------------
   NEDEN: Bagli bir dron haritada tam saglam cizilir, ancak
   kullanicinin kayitli gorunumu baska bir bolgedeyse ikon
   gorus alaninin disinda kalir ve kullaniciya "ikon yok" gibi
   gorunur. Olculen ornek: dron 38.99/35.00, kamera 25.49/50.82
   (1.900 km ayrik).

   COZUM: Kullanicinin gorunumunu EZMEDEN, ekranin kenarinda
   dronun yonunu gosteren bir ok + mesafe etiketi cizilir
   (radar/GCS standardi). Tiklanirsa o drona odaklanilir.
   Ayrica bir dron ilk kez telemetri verdiginde ve gorus
   alaninin disindaysa tek seferlik bilgi bildirimi cikar.
   ============================================================ */
(function () {
  "use strict";

  var KAP_ID = "dronEkranDisiKap";
  var KENAR = 46;          // ekran kenarindan ic bosluk (px)
  var TAZELE_MS = 250;     // gosterge tazeleme araligi
  var _duyurulan = {};     // sysid -> true (tek seferlik toast)
  var _zaman = null;

  function C() { return window.Cesium; }

  function viewerAl() {
    try {
      return window.__haritaViewerAl ? window.__haritaViewerAl() : null;
    } catch (e) { return null; }
  }

  function D() {
    try {
      if (typeof window.D === "function") return window.D() || {};
    } catch (e) {}
    return {};
  }

  function kap() {
    var k = document.getElementById(KAP_ID);
    if (!k) {
      k = document.createElement("div");
      k.id = KAP_ID;
      var cc = document.getElementById("cesiumContainer") || document.body;
      cc.appendChild(k);
    }
    return k;
  }

  /* Metre cinsinden mesafeyi okunur metne cevirir. */
  function mesafeMetni(m) {
    if (!isFinite(m)) return "";
    if (m >= 1000) return (m / 1000).toFixed(m >= 10000 ? 0 : 1) + " km";
    return Math.round(m) + " m";
  }

  /* Dronun rengini dronlar.js ile ayni kaynaktan alir. */
  function dronRengi(sysid) {
    try {
      if (window.varliklar && window.varliklar[sysid] &&
          window.varliklar[sysid]._elmasRenk)
        return window.varliklar[sysid]._elmasRenk;
    } catch (e) {}
    return "#5cc8ff";
  }

  /* Kamera ile hedef arasindaki yer mesafesi (m). */
  function yerMesafesi(v, lat, lon) {
    try {
      var Cs = C();
      var kp = v.camera.positionCartographic;
      var g = new Cs.EllipsoidGeodesic(
        Cs.Cartographic.fromDegrees(
          kp.longitude * 180 / Math.PI, kp.latitude * 180 / Math.PI),
        Cs.Cartographic.fromDegrees(lon, lat));
      return g.surfaceDistance;
    } catch (e) { return NaN; }
  }

  /* Hedefin ekran koordinatini dondurur; gorunmuyorsa null. */
  function ekranNoktasi(v, lat, lon, yuk) {
    try {
      var Cs = C();
      var kart = Cs.Cartesian3.fromDegrees(lon, lat, yuk || 0);
      var p = Cs.SceneTransforms.wgs84ToWindowCoordinates(v.scene, kart);
      return p || null;
    } catch (e) { return null; }
  }

  /* Bir gostergeyi (ok + etiket) olusturur ya da tazeler. */
  function gostergeCiz(sysid, aci, mesafe, renk, etiket) {
    var k = kap();
    var id = "dronEkranDisi_" + sysid;
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("button");
      el.id = id;
      el.type = "button";
      el.className = "dron-ekran-disi";
      el.innerHTML =
        "<i class='fa-solid fa-location-arrow dron-ed-ok'></i>" +
        "<span class='dron-ed-ad'></span>" +
        "<span class='dron-ed-mesafe'></span>";
      el.addEventListener("click", function () {
        try {
          if (typeof window.dronaGit === "function") window.dronaGit(sysid);
        } catch (e) {}
      });
      k.appendChild(el);
    }
    el.querySelector(".dron-ed-ad").textContent = etiket;
    el.querySelector(".dron-ed-mesafe").textContent = mesafeMetni(mesafe);
    el.style.borderColor = renk;
    el.style.color = renk;
    var ok = el.querySelector(".dron-ed-ok");
    // fa-location-arrow varsayilan olarak kuzeydogu (45 derece) bakar
    ok.style.transform = "rotate(" + (aci - 45) + "deg)";
    var t = D();
    el.title = (t.dronEkranDisiIpucu || "Odaklanmak icin tikla") +
               " \u00b7 " + etiket;
    return el;
  }

  /* Gostergeyi ekran kenarina, hedefin yonune gore yerlestirir. */
  function yerlestir(el, cx, cy, hx, hy, gen, yuk) {
    var dx = hx - cx, dy = hy - cy;
    var uz = Math.sqrt(dx * dx + dy * dy) || 1;
    dx /= uz; dy /= uz;
    // Kenar dikdortgeni ile isin kesisimi
    var yx = (gen / 2 - KENAR), yy = (yuk / 2 - KENAR);
    var t = Math.min(
      Math.abs(dx) > 1e-6 ? yx / Math.abs(dx) : Infinity,
      Math.abs(dy) > 1e-6 ? yy / Math.abs(dy) : Infinity);
    if (!isFinite(t)) t = 0;
    var px = cx + dx * t, py = cy + dy * t;
    el.style.left = Math.round(px) + "px";
    el.style.top = Math.round(py) + "px";
    // Ok acisi: ekran duzleminde hedefin yonu
    return Math.atan2(dy, dx) * 180 / Math.PI;
  }

  function kaldir(sysid) {
    var el = document.getElementById("dronEkranDisi_" + sysid);
    if (el) el.remove();
  }

  /* Tek seferlik "dron bagli ama ekran disinda" bildirimi. */
  function duyur(sysid, mesafe) {
    if (_duyurulan[sysid]) return;
    _duyurulan[sysid] = true;
    var t = D();
    if (typeof window.uyariToastGoster !== "function") return;
    var ad = "D" + sysid;
    var m = (typeof t.dronEkranDisiMesaj === "function")
      ? t.dronEkranDisiMesaj(ad, mesafeMetni(mesafe))
      : (ad + " bagli, gorunum disinda (" + mesafeMetni(mesafe) +
         "). Odaklanmak icin kenardaki oka tiklayin.");
    try {
      window.uyariToastGoster({
        baslik: t.dronEkranDisiBaslik || "DRON GORUNUM DISINDA",
        mesaj: m, seviye: "bilgi", kategori: "dron", sure: 7000,
      });
    } catch (e) {}
  }

  function tazele() {
    var v = viewerAl();
    if (!v || !window.sonVeri) return;
    var cc = document.getElementById("cesiumContainer");
    if (!cc) return;
    var gen = cc.clientWidth, yuk = cc.clientHeight;
    if (!gen || !yuk) return;
    var cx = gen / 2, cy = yuk / 2;

    var sidler;
    try { sidler = Object.keys(window.sonVeri); } catch (e) { return; }

    for (var i = 0; i < sidler.length; i++) {
      var sid = sidler[i];
      var d = window.sonVeri[sid];
      if (!d || typeof d.lat !== "number" || typeof d.lon !== "number" ||
          (d.lat === 0 && d.lon === 0)) { kaldir(sid); continue; }
      // Baglantisi kopuk dron icin gosterge tutulmaz
      if (d.baglanti === false) { kaldir(sid); continue; }

      var p = ekranNoktasi(v, d.lat, d.lon, d.irtifa || d.alt || 0);
      var icerde = p && p.x >= 0 && p.x <= gen && p.y >= 0 && p.y <= yuk;
      if (icerde) { kaldir(sid); continue; }

      var mes = yerMesafesi(v, d.lat, d.lon);
      // Ekran disi ama projeksiyon basarisizsa (dunyanin arkasi):
      // yon hesabi icin kaba bir dogrultu kullanilir.
      var hx, hy;
      if (p) { hx = p.x; hy = p.y; }
      else {
        var Cs = C();
        var kp = v.camera.positionCartographic;
        var dlon = d.lon - kp.longitude * 180 / Math.PI;
        var dlat = d.lat - kp.latitude * 180 / Math.PI;
        hx = cx + dlon * 1000; hy = cy - dlat * 1000;
      }
      var el = gostergeCiz(sid, 0, mes, dronRengi(sid), "D" + sid);
      var aci = yerlestir(el, cx, cy, hx, hy, gen, yuk);
      el.querySelector(".dron-ed-ok").style.transform =
        "rotate(" + (aci + 45) + "deg)";
      duyur(sid, mes);
    }
  }

  function basla() {
    if (_zaman) return;
    _zaman = setInterval(function () {
      try { tazele(); } catch (e) {}
    }, TAZELE_MS);
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", basla);
  else basla();

  // Pilot degisiminde duyuru gecmisi sifirlanir: yeni oturumda
  // kullanici yeniden bilgilendirilmeli.
  window.dronEkranDisiSifirla = function () { _duyurulan = {}; };
})();
