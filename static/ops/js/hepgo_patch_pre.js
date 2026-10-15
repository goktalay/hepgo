// =================================================================
// HEPGO - GOKTUNGU HAREKAT ARAYUZU ON-YAMASI (hepgo_patch_pre.js)
// -----------------------------------------------------------------
// YUKLEME YERI (ZORUNLU): js/harita.js'ten ONCE. Onerilen konum:
// js/hepgo_stub.js'ten hemen sonra, js/app_yolu.js'ten once. Bu dosya
// baska hicbir GOKTUNGU dosyasina bagimli degildir; harita.js'ten once
// yuklenmek disinda sira kosulu yoktur.
//
// NEDEN AYRI BIR "ON" DOSYA GEREKTI:
//   harita.js:29   window.goktunguYol = function (parca) {...}
//   harita.js:36+  HARITA_KAYNAKLARI[*].yap = () => new Cesium.UrlTemplate
//                  ImageryProvider({ url: goktunguYol("tile/esri/{z}/{x}/{y}") })
//   harita.js:177  const viewer = new Cesium.Viewer("cesiumContainer",
//                  { baseLayer: haritaKatmani() })   <- yap() BURADA cagrilir
// Yani ilk taban katmani harita.js YUKLENIRKEN kurulur ve karo URL'si
// GOKTUNGU'nun cevrimdisi karo vekili ("<taban>/tile/<kaynak>/...") olur.
// HEPGO'da bu vekil yoktur (/static/ops/tile/... -> 404, harita bos).
// harita.js'ten SONRA sarmalamak ilk katmani kacirir; harita.js'ten
// once duz atama yapmak ise satir 29 tarafindan ezilir. Cozum: window
// uzerinde `goktunguYol` icin ERISIMCI (getter/setter) ozelligi kurmak.
// harita.js:29'un atamasi setter'a duser, orijinal islev saklanir ve
// getter her zaman HEPGO sarmalayicisini dondurur. Sozcuksel
// `goktunguYol(...)` cagrilari global nesne ozelligine cozumlendigi
// icin dronlar/harita dosyalari DEGISMEDEN dogru URL'yi alir.
//
// Klasik <script>; ortak global kapsam. `var` / function declaration.
// `ws` adi burada BILDIRILMEZ (seri.js:7 `let ws`).
// =================================================================
(function () {
  "use strict";

  // ---------------------------------------------------------------
  // Dogrudan saglayici karo sablonlari (Cesium UrlTemplateImageryProvider
  // yer tutuculari {z}/{x}/{y}). DIKKAT: ArcGIS servisleri {z}/{y}/{x}
  // sirasini kullanir. google*/bing kaynaklari lisans ve vekil
  // gerektirdigi icin burada YOKTUR; hepgo_patch.js bunlari
  // #selHaritaKaynak'tan kaldirir.
  // Terrain (harita.js:410-412) zaten dogrudan ArcGIS WorldElevation3D
  // URL'sine gider; dokunulmaz.
  // ---------------------------------------------------------------
  var KARO_SABLON = {
    esri: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    esri_sokak: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    esri_topo: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    osm: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    otm: "https://tile.opentopomap.org/{z}/{x}/{y}.png",
    carto_acik: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    carto_koyu: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
  };

  // Disa acik yardimcilar (hepgo_patch.js ve hepgo_ws.js kullanabilir)
  window.hepgoKaroUrl = function (kaynak) {
    return KARO_SABLON[kaynak] || null;
  };
  window.hepgoKaroKaynaklari = function () {
    return Object.keys(KARO_SABLON);
  };

  // "tile/<kaynak>/{z}/{x}/{y}" -> dogrudan saglayici sablonu.
  // Sayisal koordinat verilmisse ("tile/osm/5/17/11") sablona yerlestirir.
  // Eslesme yoksa null (cagiran orijinal yola duser).
  function karoYoluCevir(p) {
    var m = /^tile\/([A-Za-z0-9_]+)\/(.+)$/.exec(p);
    if (!m) return null;
    var sablon = KARO_SABLON[m[1]];
    if (!sablon) return null;
    var kalan = m[2];
    if (/^\{z\}\/\{x\}\/\{y\}\/?$/.test(kalan)) return sablon;
    var n = /^(\d+)\/(\d+)\/(\d+)(?:\.[A-Za-z0-9]+)?$/.exec(kalan);
    if (n) {
      return sablon.replace("{z}", n[1]).replace("{x}", n[2]).replace("{y}", n[3]);
    }
    return null;
  }
  window.hepgoKaroYoluCevir = karoYoluCevir;

  // Orijinal goktunguYol'u (harita.js:29) saran islev uretici.
  function sarmala(orijinal) {
    function hepgoGoktunguYol(parca) {
      var p = String(parca == null ? "" : parca);
      while (p.charAt(0) === "/") p = p.slice(1);
      var dogrudan = karoYoluCevir(p);
      if (dogrudan) return dogrudan;
      if (typeof orijinal === "function") return orijinal(parca);
      // harita.js henuz yuklenmemisse orijinalin davranisini taklit et
      // (harita.js:16 GOKTUNGU_TABAN: sayfanin bulundugu dizin).
      var taban = window.GOKTUNGU_TABAN;
      if (typeof taban !== "string" || !taban) {
        try {
          taban = String(window.location.pathname || "/").replace(/[^/]*$/, "");
          if (!taban || taban.charAt(0) !== "/") taban = "/";
          if (taban.charAt(taban.length - 1) !== "/") taban += "/";
        } catch (e) { taban = "/"; }
      }
      return taban + p;
    }
    hepgoGoktunguYol.__hepgoSarmal = true;
    hepgoGoktunguYol.__orijinal = orijinal || null;
    return hepgoGoktunguYol;
  }

  try {
    var mevcut = (typeof window.goktunguYol === "function") ? window.goktunguYol : null;
    if (mevcut && mevcut.__hepgoSarmal) return;   // iki kez yuklenmis; dokunma
    var sarili = sarmala(mevcut);
    Object.defineProperty(window, "goktunguYol", {
      configurable: true,
      enumerable: true,
      get: function () { return sarili; },
      // harita.js:29 buraya duser: orijinal saklanir, sarmalayici kalir.
      set: function (fn) {
        if (fn && fn.__hepgoSarmal) { sarili = fn; return; }
        sarili = sarmala(typeof fn === "function" ? fn : null);
      }
    });
  } catch (e) {
    // Erisimci kurulamazsa (beklenmez) hepgo_patch.js harita.js'ten sonra
    // duz sarmalama + taban katmani yeniden kurma yoluna duser.
    try { console.warn("[hepgo_patch_pre] goktunguYol erisimcisi kurulamadi:", e); } catch (e2) {}
  }

  // ---------------------------------------------------------------
  // HEPGO yetenek bayraklari (varsayilan: hepsi kapali). hepgo_ws.js
  // sunucu hello.caps listesine gore acar; hepgo_patch.js dugmeleri
  // gizlerken CAGRI ANINDA okur. Burada yalniz eksikse tanimlanir.
  // ---------------------------------------------------------------
  var OZ_VARSAYILAN = {
    param: false,            // param_list/param_set -> Parametreler, Failsafe, Yakinlik
    bakim: false,            // calib/motor_test/reboot -> Kalibrasyon, Motor Testi, Ilk Ayar, Yeniden Baslat
    log: false,              // log_listesi/log_indir -> Log Yonetimi
    set_home: false,         // set_home -> HOME Ayarla + SHIFT+tik
    arm_zorla: false,        // arm {force:true} -> Zorla arm secenegi
    konsol_sunucu: false,    // console/console_hist/console_clear
    arm_check_sunucu: false  // yerel 'arm_check' komutu
  };
  var oz = window.HEPGO_OZ;
  if (!oz || typeof oz !== "object") oz = {};
  for (var k in OZ_VARSAYILAN) {
    if (Object.prototype.hasOwnProperty.call(OZ_VARSAYILAN, k) && typeof oz[k] === "undefined") {
      oz[k] = OZ_VARSAYILAN[k];
    }
  }
  window.HEPGO_OZ = oz;
})();
