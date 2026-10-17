// =====================================================================
// HEPGO HAREKÂT — hepgo_nomap.js (§14 Uçuş Simülatörü: haritasız panel)
// ---------------------------------------------------------------------
// Simülatör oturumunda (?sim=) harekât paneli 3B dünyanın üstünde bir katmandır; Cesium haritasına gerek yoktur (rota 3B'de
// çizilir). index.html'deki yükleyici bu kipte Cesium.js/widgets.css'i HİÇ ÇEKMEZ (karo/Google/Esri isteği yok, bellek/CPU
// tasarrufu) ve bu dosyayı yükler. GÖKTUNGU betikleri (harita.js:177 `new Cesium.Viewer`, dronlar.js entity'leri, rotalar.js …)
// bayt bayt kopya olduğundan Cesium'u guard'sız kullanır: burada evrensel bir SAHTE Cesium verilir — her özellik/çağrı/`new`
// yine aynı türden "her şeyi yutan" bir Proxy döndürür (sayıya 0, metne "", yinelemede boş, JSON'da {}, `then` yok). Böylece
// harita kodu çalışır ama hiçbir şey çizmez; dron kartı, PFD, İŞLEMLER, telemetri karoları ve konsol aynen dolar.
// Ayrıca sol araç grubuna "Haritayı göster / gizle" anahtarı eklenir (localStorage hepgo_sim_harita = "1" → Cesium yüklenir).
// YÜKLEME: index.html yükleyicisi, sim kipinde Cesium yerine (hepgo_stub.js'ten önce); haritalı kipte de yüklenir ama Cesium
// tanımlıysa sahteye dokunmaz, yalnız anahtarı ekler.
// =====================================================================
(function () {
  var q; try { q = new URLSearchParams(location.search); } catch (e) { q = null; }
  var simKipi = !!q && !q.get("task") && parseInt(q.get("sim"), 10) > 0;
  var nomap = typeof window.Cesium === "undefined";
  if (nomap) {
    try { document.documentElement.dataset.hepgoNomap = "1"; } catch (e) {}
    var OZEL = {};
    OZEL.then = undefined;                              // await/Promise.resolve sahteyi thenable sanmasın
    OZEL.toJSON = undefined;
    OZEL.valueOf = function () { return 0; };
    OZEL.toString = function () { return ""; };
    OZEL.length = 0;
    OZEL.isDestroyed = function () { return false; };
    OZEL[Symbol.toPrimitive] = function (hint) { return hint === "number" ? 0 : ""; };
    OZEL[Symbol.iterator] = function () { return { next: function () { return { done: true, value: undefined }; } }; };
    OZEL[Symbol.toStringTag] = "CesiumSahte";
    var handler = {
      get: function (t, k) { if (Object.prototype.hasOwnProperty.call(OZEL, k)) return OZEL[k]; return sahte(); },
      set: function () { return true; },
      has: function () { return true; },
      deleteProperty: function () { return true; },
      apply: function () { return sahte(); },
      construct: function () { return sahte(); },
      ownKeys: function () { return []; },
      getOwnPropertyDescriptor: function () { return undefined; },
      defineProperty: function () { return true; },
      getPrototypeOf: function () { return Function.prototype; },
    };
    function hedef() {}
    function sahte() { return new Proxy(hedef, handler); }
    window.Cesium = sahte();
    window.HEPGO_NOMAP = true;
  }
  if (!simKipi) return;
  // "Haritayı göster / gizle" anahtarı (sol harita araç grubu); yeniden yükleme ile uygulanır (betik seti sayfa açılışında seçilir)
  function anahtarEkle() {
    var grup = document.getElementById("haritaAracGrubu");
    if (!grup || document.getElementById("btnHaritaGoster")) return;
    var en = false;
    try { var pl = (window.parent && window.parent !== window && window.parent.document.documentElement.lang) || document.documentElement.lang || "tr"; en = !/^tr/i.test(pl); } catch (e) {}
    var b = document.createElement("button");
    b.id = "btnHaritaGoster"; b.type = "button";
    b.title = nomap ? (en ? "Show map (Cesium is loaded; the page reloads)" : "Haritayı göster (Cesium yüklenir; sayfa yenilenir)")
                    : (en ? "Hide map (lighter panel; the page reloads)" : "Haritayı gizle (hafif panel; sayfa yenilenir)");
    b.innerHTML = '<i class="fa-solid ' + (nomap ? "fa-map" : "fa-map-location-dot") + '"></i>';
    if (!nomap) b.classList.add("acik");
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      try { localStorage.setItem("hepgo_sim_harita", nomap ? "1" : "0"); } catch (err) {}
      location.reload();
    });
    grup.appendChild(b);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", anahtarEkle); else anahtarEkle();
})();
