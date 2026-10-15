// =================================================================
// HEPGO - GOKTUNGU HAREKAT ARAYUZU DAVRANIS YAMALARI (hepgo_patch.js)
// -----------------------------------------------------------------
// YUKLEME YERI (ZORUNLU): js/menubar.js ve js/uyari_merkezi.js'ten SONRA,
// js/hepgo_ws.js'ten ONCE. Karo URL on-yamasi icin ayrica
// js/hepgo_patch_pre.js harita.js'ten ONCE yuklenmelidir (bu dosya pre
// yuklenmemisse yedek yolu dener; bkz. Bolum 6).
//
// ILKE: GOKTUNGU js/css dosyalari BAYT BAYT degismez. Tum uyarlama bu
// dosyadaki calisma zamani yamalariyla yapilir. Her yama try/catch ile
// yalitilir ve hangi kaynak satirini neden yamaladigi yorumlanir.
//
// Klasik <script>; ortak global kapsam. `var` / function declaration
// kullanilir. `ws` adi burada BILDIRILMEZ (seri.js:7 `let ws`);
// gercek/sahte soketi hepgo_ws.js atar.
//
// DISA ACIK SOZLESME (window.*):
//   HEPGO_OZ            yetenek bayraklari (pre tanimlar; eksikse burada)
//   dkArmSecimAc        dronlar.js:2586 yerel tanimin global kopyasi
//   dkIslemlerPopupAc   dronlar.js:4863 sarmalayicisi (dugme budama)
//   dronGecmisAc        History -> HEPGO #/field/drones[/<id>]
//   hepgoNav(hash)      parent.postMessage({t:'ops-nav', hash})
//   hepgoTemaSenkron()  parent data-theme -> temaUygula
//   hepgoMetinleriUygula()  HEPGO baslik/menu metinlerini yeniden yazar
//   hepgoDronIdBul(sysid)   HEPGO_ENVANTER'den dron id (hepgo_ws.js
//                           kendi surumunu tanimlarsa o kullanilir)
// =================================================================
(function () {
  "use strict";

  // ---------------------------------------------------------------
  // 0. ORTAK YARDIMCILAR
  // ---------------------------------------------------------------
  function uyar(ad, e) {
    try { console.warn("[hepgo_patch] " + ad + ":", e); } catch (e2) {}
  }
  // Her yamayi yalitir: biri patlarsa digerleri calisir.
  function guvenli(ad, fn) {
    try { return fn(); } catch (e) { uyar(ad, e); return undefined; }
  }
  function sozluk() {
    try { return (typeof D === "function") ? (D() || {}) : {}; } catch (e) { return {}; }
  }
  function parentVarMi() {
    try { return !!(window.parent && window.parent !== window); } catch (e) { return false; }
  }
  // HEPGO SPA'ya mesaj (ayni koken; drone.js renderLive onMsg e.origin
  // denetimi yapar, bu yuzden hedef koken location.origin'dir).
  function parentGonder(mesaj) {
    if (!parentVarMi()) return false;
    try { window.parent.postMessage(mesaj, window.location.origin); return true; } catch (e) { uyar("postMessage", e); return false; }
  }
  // HEPGO icinde gezinme. iframe disinda (dogrudan acilmis sayfa) yeni
  // sekmede HEPGO SPA'yi acar; mevcut harekat ekrani kaybolmaz.
  function hepgoNav(hash) {
    if (typeof hash !== "string" || hash.indexOf("#/") !== 0) return;
    if (parentGonder({ t: "ops-nav", hash: hash })) return;
    try { window.open("/" + hash, "_blank", "noopener"); } catch (e) { uyar("hepgoNav", e); }
  }
  window.hepgoNav = hepgoNav;

  function el(etiket, sinif, nitelikler) {
    var e = document.createElement(etiket);
    if (sinif) e.className = sinif;
    if (nitelikler) {
      for (var k in nitelikler) {
        if (Object.prototype.hasOwnProperty.call(nitelikler, k)) e.setAttribute(k, nitelikler[k]);
      }
    }
    return e;
  }

  // ---------------------------------------------------------------
  // 1. HEPGO_OZ (yetenek bayraklari) - pre yuklenmemisse varsayilanlar.
  //    Bayraklar hepgo_ws.js tarafindan hello.caps ile acilir; buradaki
  //    yamalar bayraklari CAGRI ANINDA okur (yukleme aninda degil).
  // ---------------------------------------------------------------
  guvenli("HEPGO_OZ", function () {
    var vars = { param: false, bakim: false, log: false, set_home: false,
                 arm_zorla: false, konsol_sunucu: false, arm_check_sunucu: false };
    var oz = (window.HEPGO_OZ && typeof window.HEPGO_OZ === "object") ? window.HEPGO_OZ : {};
    for (var k in vars) {
      if (Object.prototype.hasOwnProperty.call(vars, k) && typeof oz[k] === "undefined") oz[k] = vars[k];
    }
    window.HEPGO_OZ = oz;
  });
  function ozAcik(ad) {
    try { return !!(window.HEPGO_OZ && window.HEPGO_OZ[ad]); } catch (e) { return false; }
  }

  // ---------------------------------------------------------------
  // 2. EMNIYET KEMERI: hepgo_stub.js yuklenmemis veya eksikse, pakette
  //    TANIMSIZ olan ve korumasiz okunan globaller icin asgari yedekler.
  //    Yalniz `typeof === "undefined"` ise tanimlanir; stub'in tanimlari
  //    ASLA ezilmez. Kaynak noktalar:
  //      gcsKonum            dronlar.js:738 dronMesafeM (her telemetride)
  //      gcsVarlik           tema.js:29
  //      radarRenkUygula     tema.js:32 (korumasiz cagri)
  //      radarIkonGuncelle   tema.js:29-30 (typeof korumali ama birlikte)
  //      aktifAngajmanlar    dronlar.js:1131 tumDronlariTemizle
  //      angajmanPopupAc     dronlar.js:4941 (dugme zaten budanir)
  //      ikonPrizmaMi        dronlar.js:866 (yoksa prizma=true -> ikon yok)
  //      elmasIkon           dronlar.js:902/1023, tema.js:24
  //      i18nGetir           arayuz.js:384/388 tam ekran ipucu
  //      oturum              rol bilgisi (hepgo_ws.js hello.me ile gunceller)
  // ---------------------------------------------------------------
  guvenli("emniyet-kemeri", function () {
    if (typeof gcsKonum === "undefined") window.gcsKonum = null;
    if (typeof gcsVarlik === "undefined") window.gcsVarlik = null;
    if (typeof radarRenkUygula === "undefined") window.radarRenkUygula = function () {};
    if (typeof radarIkonGuncelle === "undefined") window.radarIkonGuncelle = function () {};
    if (typeof aktifAngajmanlar === "undefined") window.aktifAngajmanlar = {};
    if (typeof angajmanPopupAc === "undefined") window.angajmanPopupAc = function () {};
    if (typeof window.ikonPrizmaMi !== "function") window.ikonPrizmaMi = function () { return false; };
    if (typeof elmasIkon === "undefined") {
      // dronlar.js:20-28 ucgenIkon deseni: SVG data URL (30x30 elmas)
      window.elmasIkon = function (renk) {
        var r = String(renk || "#5cc8ff");
        var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='30' height='30' viewBox='0 0 30 30'>" +
          "<polygon points='15,1 29,15 15,29 1,15' fill='" + r + "' stroke='#000' stroke-width='1.5'/></svg>";
        return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
      };
    }
    if (typeof window.i18nGetir !== "function") {
      window.i18nGetir = function (k) { return sozluk()[k]; };
    }
    if (typeof oturum === "undefined") window.oturum = { rol: "izleyici" };
    if (typeof window.oturumYoneticiMi !== "function") window.oturumYoneticiMi = function () { return false; };
  });

  // ---------------------------------------------------------------
  // 3. window.dkArmSecimAc - dronlar.js:2586-2668 GOVDESININ KOPYASI
  //    NEDEN: Orijinal tanim, hic cagrilmayan dronKomutToolbarOlustur
  //    (dronlar.js:2560) ICINDE yereldir; satir 2669'daki
  //    `window.dkArmSecimAc = dkArmSecimAc` de hic calismaz. Durum
  //    karosundaki ARM tiki (dronlar.js:3554 `dkArmSecimAc(sysid, null)`)
  //    sozcuksel arama ile global nesneye ulasir -> bu kopya bulunur.
  //    FARK: 'Zorla arm' secenegi (arm {force:true}) sunucu/kopru
  //    destegi gelene dek HEPGO_OZ.arm_zorla kapaliyken GIZLIDIR.
  //    dronlar.js guncellenirse bu kopya elle senkronlanmali.
  // ---------------------------------------------------------------
  guvenli("dkArmSecimAc", function () {
    function onayla(mesaj, onOnay) {
      if (typeof window.onayIste === "function") return window.onayIste(mesaj, onOnay);
      if (window.confirm(mesaj)) onOnay();
    }
    function onayMetniAl(anahtar) {
      if (typeof window.onayMetni === "function") {
        try { return window.onayMetni(anahtar); } catch (e) {}
      }
      return sozluk()[anahtar] || anahtar;
    }
    function komut(sysid, aksiyon) {
      if (typeof dronKomutGonder === "function") dronKomutGonder(sysid, aksiyon);
      else uyar("dkArmSecimAc", "dronKomutGonder tanimsiz");
    }

    function dkArmSecimAc(sysid, capa) {
      var t = sozluk();
      var eski = document.getElementById("dkArmSecim");
      if (eski) eski.remove();

      var perde = document.createElement("div");
      perde.id = "dkArmSecim";
      perde.className = "dk-arm-perde";

      var kart = document.createElement("div");
      kart.className = "dk-arm-kart";

      var bas = document.createElement("div");
      bas.className = "dk-arm-baslik";
      bas.textContent = t.dkArmSecimBaslik || "ARM";
      kart.appendChild(bas);

      var not = document.createElement("div");
      not.className = "dk-arm-not";
      not.textContent = t.dkArmSecimNot || "Arm bicimini secin.";
      kart.appendChild(not);

      function secenek(etiket, aciklama, tehlikeli, cb) {
        var b = document.createElement("button");
        b.className = "dk-arm-sec" + (tehlikeli ? " tehlikeli" : "");
        var e = document.createElement("span");
        e.className = "dk-arm-sec-et";
        e.textContent = etiket;
        var a = document.createElement("span");
        a.className = "dk-arm-sec-ac";
        a.textContent = aciklama;
        b.appendChild(e); b.appendChild(a);
        b.addEventListener("click", function (ev) {
          ev.stopPropagation();
          perde.remove();
          cb();
        });
        kart.appendChild(b);
        return b;
      }

      // Normal arm: mevcut davranis, degismedi
      secenek(t.dkArmNormal || "Normal arm",
        t.dkArmNormalAc || "Ucus denetleyicisinin denetimleri uygulanir.",
        false,
        function () { onayla(onayMetniAl("onayArm"), function () { komut(sysid, "arm"); }); });

      // Zorla arm: IKINCI onay - yalniz sunucu/kopru destegi acikken
      if (ozAcik("arm_zorla")) {
        secenek(t.dkArmZorla || "Zorla arm",
          t.dkArmZorlaAc || "Denetimler atlatilir.",
          true,
          function () {
            onayla(t.dkArmZorlaOnay ||
              "Arm oncesi guvenlik denetimleri ATLATILACAK. " +
              "Aracin ucusa hazir oldugunu kendiniz dogruladiniz mi?",
              function () { komut(sysid, "arm_zorla"); });
          });
      }

      var iptal = document.createElement("button");
      iptal.className = "dk-arm-iptal";
      iptal.textContent = t.onayIptalBtn || t.dkParamIptal || "IPTAL";
      iptal.addEventListener("click", function (ev) {
        ev.stopPropagation(); perde.remove();
      });
      kart.appendChild(iptal);

      perde.appendChild(kart);
      perde.addEventListener("click", function (ev) {
        if (ev.target === perde) perde.remove();
      });
      document.body.appendChild(perde);

      // Capa ogesi verildiyse yaninda ac, yoksa ortada
      if (capa && capa.getBoundingClientRect) {
        var r = capa.getBoundingClientRect();
        kart.style.position = "fixed";
        kart.style.left = Math.max(8, Math.min(window.innerWidth - 300, r.left)) + "px";
        kart.style.top = Math.max(8, Math.min(window.innerHeight - 240, r.bottom + 6)) + "px";
      }
      return perde;
    }
    window.dkArmSecimAc = dkArmSecimAc;
  });

  // ---------------------------------------------------------------
  // 4. dkIslemlerPopupAc SARMALAYICISI - dronlar.js:4863-5021
  //    Orijinal popup'i kurar; ardindan #dkPopupIslemler_<sysid> icindeki
  //    .dk-islem-hucre dugmelerinden (dronlar.js:4896 `el.title = metin`)
  //    kapsam disi ve sunucu destegi olmayanlari title eslesmesiyle
  //    kaldirir. Bos kalan grup basliklari (.dk-islem-grup) da silinir.
  //    Cagri noktalari (dronlar.js:1350 kart, 1753 PFD, 5058 harita)
  //    window.dkIslemlerPopupAc okur; 4863 function declaration global
  //    nesne ozelligi oldugu icin asagidaki atama ayni bagi degistirir.
  //    Kapsam disi (her zaman): Angaje Ol (angajmanPopupAc tanimsiz ->
  //    tikta ReferenceError), Angajman Izle, Takip Et / Takibi Iptal Et
  //    (suru). Bayraga bagli: HEPGO_OZ.param -> Failsafe, Parametreler,
  //    Yakinlik; .bakim -> Kalibrasyon, Motor Testi, Ilk Ayar, Yeniden
  //    Baslat; .log -> Log Yonetimi; .set_home -> HOME Ayarla.
  //    i18n anahtarlari (i18n.js TR 389-578 / EN 2687-2867) ve dronlar.js
  //    yedek metinleri birlikte eslenir; metin degisse bile dugme geri
  //    gelir, zarar vermez (typeof korumali, islevsiz).
  // ---------------------------------------------------------------
  guvenli("dkIslemlerPopupAc", function () {
    if (typeof window.dkIslemlerPopupAc !== "function") return;
    var orijinal = window.dkIslemlerPopupAc;
    if (orijinal.__hepgoSarmal) return;

    function gizlenecekler() {
      var t = sozluk();
      var liste = [
        t.angAngajeOl, "Angaje Ol", "Engage",
        t.angiBaslik, "Angajman İzle", "ANGAJMAN İZLE", "ENGAGEMENT MONITOR",
        t.dkTakipEt, "Takip Et", "Follow",
        t.dkTakipIptal, "Takibi İptal Et", "Cancel Follow"
      ];
      if (!ozAcik("param")) {
        liste.push(t.dkFailsafe, "Failsafe",
          t.dkParametreler, "Parametreler", "Parameters",
          t.dkYakinlik, "Yakınlık Algılayıcısı", "Proximity Sensor");
      }
      if (!ozAcik("bakim")) {
        liste.push(t.dkKalibrasyon, "Kalibrasyon", "Calibration",
          t.dkMotorTest, "Motor Testi", "Motor Test",
          t.dkIlkAyar, "İlk Ayar", "Initial Setup",
          t.dkReboot, "Yeniden Başlat", "Reboot");
      }
      if (!ozAcik("log")) liste.push(t.dkLogYonetimi, "Log Yönetimi", "Log Management");
      if (!ozAcik("set_home")) liste.push(t.dkHomeAyarla, "HOME Ayarla", "Set HOME");
      var kume = {};
      for (var i = 0; i < liste.length; i++) {
        if (typeof liste[i] === "string" && liste[i]) kume[liste[i]] = true;
      }
      return kume;
    }

    function buda(pop) {
      var kume = gizlenecekler();
      var hucreler = pop.querySelectorAll(".dk-islem-hucre");
      for (var i = 0; i < hucreler.length; i++) {
        var b = hucreler[i];
        var baslik = b.getAttribute("title") || "";
        var metinEl = b.querySelector(".dk-islem-hucre-metin");
        var metin = metinEl ? (metinEl.textContent || "") : "";
        if (kume[baslik] || kume[metin]) b.remove();
      }
      // Bos kalan grup basliklari: sonraki basliga kadar hucre yoksa sil
      var gruplar = pop.querySelectorAll(".dk-islem-grup");
      for (var g = 0; g < gruplar.length; g++) {
        var grup = gruplar[g];
        var dolu = false;
        var s = grup.nextElementSibling;
        while (s && !s.classList.contains("dk-islem-grup")) {
          if (s.classList.contains("dk-islem-hucre")) { dolu = true; break; }
          s = s.nextElementSibling;
        }
        if (!dolu) grup.remove();
      }
    }

    function sarili(sysid, fare) {
      var sonuc = orijinal.apply(this, arguments);
      try {
        var pop = document.getElementById("dkPopupIslemler_" + sysid);
        if (pop) buda(pop);
      } catch (e) { uyar("dkIslemlerPopupAc/buda", e); }
      return sonuc;
    }
    sarili.__hepgoSarmal = true;
    sarili.__orijinal = orijinal;
    window.dkIslemlerPopupAc = sarili;
  });

  // ---------------------------------------------------------------
  // 5. window.dronGecmisAc -> HEPGO Dron Envanteri
  //    gecmis.js yuklenmez; dronlar.js:4961 History dugmesi ve
  //    menubar.js:111 (#mbDronGecmis varsa) typeof korumali olarak bunu
  //    cagirir. Dron id biliniyorsa #/field/drones/<id>, yoksa liste.
  //    HEPGO_ENVANTER sozlesmesi (hepgo_ws.js): anahtar "<bridge_id>:<sysid>"
  //    -> {code, name, id}. hepgo_ws.js kendi window.hepgoDronIdBul'unu
  //    tanimlarsa (sanal sysid cevirimi vb.) o tercih edilir.
  // ---------------------------------------------------------------
  guvenli("dronGecmisAc", function () {
    function dronIdBul(sysid) {
      if (sysid == null || sysid === "") return null;
      var env = window.HEPGO_ENVANTER;
      if (!env || typeof env !== "object") return null;
      var hedef = String(sysid);
      var adaylar = [];
      var anahtarlar = Object.keys(env);
      for (var i = 0; i < anahtarlar.length; i++) {
        var k = anahtarlar[i];
        var parca = k.split(":");
        if (parca.length >= 2 && parca[parca.length - 1] === hedef && env[k] && env[k].id != null) {
          adaylar.push(env[k].id);
        }
      }
      if (!adaylar.length && env[hedef] && env[hedef].id != null) adaylar.push(env[hedef].id);
      // Birden fazla kopruden ayni sysid: belirsiz -> genel liste
      return adaylar.length === 1 ? adaylar[0] : null;
    }
    if (typeof window.hepgoDronIdBul !== "function") window.hepgoDronIdBul = dronIdBul;

    window.dronGecmisAc = function (sysid) {
      var id = null;
      try { id = window.hepgoDronIdBul(sysid); } catch (e) { id = null; }
      hepgoNav(id != null ? "#/field/drones/" + encodeURIComponent(String(id)) : "#/field/drones");
    };
  });

  // ---------------------------------------------------------------
  // 6. HARITA KARO YOLU (harita.js:29 goktunguYol, 36-150 HARITA_KAYNAKLARI,
  //    173 haritaKatmani, 177 viewer, 342-366 haritaKaynakUygula/combobox)
  //    Asil is hepgo_patch_pre.js'te (harita.js'ten once erisimci). Burada:
  //    (a) pre yuklenmemisse YEDEK: goktunguYol'u simdi sar ve taban
  //        katmanini yeniden kur (ilk katman 404'lu vekil yoluyla kuruldu);
  //    (b) #selHaritaKaynak'tan google*/bing seceneklerini kaldir (vekil
  //        ve lisans yok -> karo 404); secili kaynak bunlardan biriyse esri;
  //    (c) dogrudan sablonu olmayan diger kaynaklari da kaldir.
  // ---------------------------------------------------------------
  guvenli("harita-karo", function () {
    var KARO_YEDEK = {
      esri: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      esri_sokak: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      esri_topo: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
      osm: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      otm: "https://tile.opentopomap.org/{z}/{x}/{y}.png",
      carto_acik: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
      carto_koyu: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    };
    if (typeof window.hepgoKaroUrl !== "function") {
      window.hepgoKaroUrl = function (kaynak) { return KARO_YEDEK[kaynak] || null; };
    }
    if (typeof window.hepgoKaroKaynaklari !== "function") {
      window.hepgoKaroKaynaklari = function () { return Object.keys(KARO_YEDEK); };
    }

    var mevcut = window.goktunguYol;
    var preVar = !!(typeof mevcut === "function" && mevcut.__hepgoSarmal);
    if (!preVar) {
      // (a) YEDEK: pre yuklenmemis. Duz sarmala; ilk katman vekil yoluyla
      // kurulmus oldugu icin taban katmanini yeniden kur.
      var orijinal = (typeof mevcut === "function") ? mevcut : null;
      function hepgoGoktunguYolYedek(parca) {
        var p = String(parca == null ? "" : parca);
        while (p.charAt(0) === "/") p = p.slice(1);
        var m = /^tile\/([A-Za-z0-9_]+)\/(.+)$/.exec(p);
        if (m) {
          var sablon = window.hepgoKaroUrl(m[1]);
          if (sablon) {
            if (/^\{z\}\/\{x\}\/\{y\}\/?$/.test(m[2])) return sablon;
            var n = /^(\d+)\/(\d+)\/(\d+)(?:\.[A-Za-z0-9]+)?$/.exec(m[2]);
            if (n) return sablon.replace("{z}", n[1]).replace("{x}", n[2]).replace("{y}", n[3]);
          }
        }
        if (orijinal) return orijinal(parca);
        return (window.GOKTUNGU_TABAN || "/") + p;
      }
      hepgoGoktunguYolYedek.__hepgoSarmal = true;
      hepgoGoktunguYolYedek.__orijinal = orijinal;
      try {
        // harita.js:29 duz atama yapmis olabilir; erisimci varsa setter calisir
        Object.defineProperty(window, "goktunguYol", {
          configurable: true, enumerable: true, writable: true, value: hepgoGoktunguYolYedek
        });
      } catch (e) { window.goktunguYol = hepgoGoktunguYolYedek; }
      uyar("harita-karo", "hepgo_patch_pre.js yuklenmemis; taban katmani yeniden kuruluyor");
      try {
        var v = (typeof window.__haritaViewerAl === "function") ? window.__haritaViewerAl() : null;
        if (v && v.imageryLayers && typeof haritaKatmani === "function") {
          v.imageryLayers.removeAll();
          v.imageryLayers.add(haritaKatmani());
        }
      } catch (e) { uyar("harita-karo/katman", e); }
    }

    // (b)+(c) combobox budama ve secili kaynak duzeltmesi
    var sel = document.getElementById("selHaritaKaynak");
    var kalanlar = [];
    if (sel) {
      var ops = Array.prototype.slice.call(sel.options || []);
      for (var i = 0; i < ops.length; i++) {
        var deger = ops[i].value || "";
        var dogrudanVar = !!window.hepgoKaroUrl(deger);
        var yasak = /^google/.test(deger) || deger === "bing";
        if (yasak || !dogrudanVar) ops[i].remove();
        else kalanlar.push(deger);
      }
    }
    var secili = null;
    try { secili = (typeof window.haritaKaynakAdi === "function") ? window.haritaKaynakAdi() : null; } catch (e) {}
    if (secili && !window.hepgoKaroUrl(secili) && typeof window.haritaKaynakUygula === "function") {
      var hedef = window.hepgoKaroUrl("esri") ? "esri" : (kalanlar[0] || "esri");
      try { window.haritaKaynakUygula(hedef, true); } catch (e) { uyar("harita-karo/kaynak", e); }
    }
    if (sel && secili && window.hepgoKaroUrl(secili) && sel.value !== secili) {
      try { sel.value = secili; } catch (e) {}
    }
  });

  // ---------------------------------------------------------------
  // 7. HEPGO METINLERI (i18n.js DILLER sozlugu + applyLanguage 4584)
  //    #yzSeri basligi 'BAGLANTI YONETICISI' (data-i18n=panelSeri,
  //    index.html:741) -> 'DRONLAR / KOPRULER'; #bagToolbarLabel
  //    (index.html:748, data-i18n=bagToolbarLabel) -> 'KOPRU'.
  //    Yontem: DILLER.TR/EN nesnelerine HEPGO anahtarlari eklenir ve
  //    elemanlarin data-i18n niteligi bu anahtarlara cevrilir; boylece
  //    applyLanguage'in [data-i18n] dongusu (4592-4595) dil degisiminde
  //    dogru metni kendisi yazar (seri.js bu etiketleri yazmaz).
  //    Emniyet: DILLER erisilemezse applyLanguage sarmalanir ve metinler
  //    her dil uygulamasindan sonra yeniden yazilir.
  // ---------------------------------------------------------------
  var HEPGO_METIN = {
    hepgoPanelSeri:     { TR: "DRONLAR / KÖPRÜLER", EN: "DRONES / BRIDGES" },
    hepgoBagToolbar:    { TR: "KÖPRÜ",               EN: "BRIDGE" },
    hepgoDronYonetimi:  { TR: "Dron Yönetimi",          EN: "Drone Management" },
    hepgoMbEnvanter:    { TR: "Dron envanteri (HEPGO)",       EN: "Drone inventory (HEPGO)" },
    hepgoMbRotalar:     { TR: "Rotalar (HEPGO)",              EN: "Routes (HEPGO)" },
    hepgoMbKopruler:    { TR: "Dron köprüleri (HEPGO)", EN: "Drone bridges (HEPGO)" }
  };
  function aktifDilAdi() {
    try { if (typeof aktifDil === "string" && (aktifDil === "TR" || aktifDil === "EN")) return aktifDil; } catch (e) {}
    return "TR";
  }
  function hepgoMetin(anahtar) {
    var m = HEPGO_METIN[anahtar];
    if (!m) return "";
    return m[aktifDilAdi()] || m.TR;
  }
  var sozlukEklendi = guvenli("sozluk-ekle", function () {
    if (typeof DILLER === "undefined" || !DILLER || !DILLER.TR || !DILLER.EN) return false;
    for (var k in HEPGO_METIN) {
      if (!Object.prototype.hasOwnProperty.call(HEPGO_METIN, k)) continue;
      DILLER.TR[k] = HEPGO_METIN[k].TR;
      DILLER.EN[k] = HEPGO_METIN[k].EN;
    }
    return true;
  }) === true;

  function hepgoMetinleriUygula() {
    var hedefler = [
      { sec: "#yzSeri [data-i18n='panelSeri'], #yzSeri [data-i18n='hepgoPanelSeri']", anahtar: "hepgoPanelSeri" },
      { sec: "#bagToolbarLabel", anahtar: "hepgoBagToolbar" }
    ];
    for (var i = 0; i < hedefler.length; i++) {
      var liste = document.querySelectorAll(hedefler[i].sec);
      for (var j = 0; j < liste.length; j++) {
        var e = liste[j];
        if (sozlukEklendi) e.setAttribute("data-i18n", hedefler[i].anahtar);
        e.textContent = hepgoMetin(hedefler[i].anahtar);
      }
    }
    // Menubar'a eklenen HEPGO ogeleri (Bolum 9) - sozluk yoksa elle
    var ogeler = document.querySelectorAll("[data-hepgo-i18n]");
    for (var m = 0; m < ogeler.length; m++) {
      ogeler[m].textContent = hepgoMetin(ogeler[m].getAttribute("data-hepgo-i18n"));
    }
  }
  window.hepgoMetinleriUygula = hepgoMetinleriUygula;

  guvenli("applyLanguage-sarmal", function () {
    if (typeof applyLanguage !== "function") return;
    var orijinal = applyLanguage;
    if (orijinal.__hepgoSarmal) return;
    function sarili(dil, kaydet) {
      var sonuc = orijinal.apply(this, arguments);
      try { hepgoMetinleriUygula(); } catch (e) { uyar("applyLanguage/metin", e); }
      return sonuc;
    }
    sarili.__hepgoSarmal = true;
    sarili.__orijinal = orijinal;
    // i18n.js:4584 function declaration -> global nesne ozelligi; atama
    // ayni bagi degistirir, i18n.js:4750-4751 dil dugmeleri ve
    // hepgo_ws.js'in applyLanguage(aktifDil,false) cagrisi sarmali gorur.
    window.applyLanguage = sarili;
  });

  // ---------------------------------------------------------------
  // 8. TEMA SENKRONU (tema.js:11 temaUygula; HEPGO prefs.js:15
  //    documentElement.dataset.theme = 'dark' | nitelik yok)
  //    Ayni koken: parent.document okunabilir. 'dark' -> 'koyu', aksi
  //    'acik'. Parent'ta data-theme degisimi MutationObserver ile izlenir.
  //    temaUygula stub eksikligiyle yarim kalirsa (tema.js:29/32)
  //    data-tema niteligi (tema.js:42-43) burada ayrica garanti edilir.
  // ---------------------------------------------------------------
  function parentTema() {
    try {
      if (!parentVarMi()) return null;
      var de = window.parent.document.documentElement;
      return (de.getAttribute("data-theme") === "dark") ? "koyu" : "acik";
    } catch (e) { return null; }
  }
  function temaUygulaGuvenli(tema) {
    if (tema !== "koyu" && tema !== "acik") return;
    try {
      if (typeof temaUygula === "function") temaUygula(tema, false);
    } catch (e) { uyar("temaUygula", e); }
    try {
      if (tema === "acik") document.documentElement.dataset.tema = "acik";
      else delete document.documentElement.dataset.tema;
      var bK = document.getElementById("btnKoyu"), bA = document.getElementById("btnAcik");
      if (bK) bK.classList.toggle("secili", tema === "koyu");
      if (bA) bA.classList.toggle("secili", tema === "acik");
    } catch (e) {}
  }
  function hepgoTemaSenkron() {
    var t = parentTema();
    if (t) temaUygulaGuvenli(t);
    return t;
  }
  window.hepgoTemaSenkron = hepgoTemaSenkron;
  guvenli("tema-senkron", function () {
    if (!parentVarMi()) return;
    hepgoTemaSenkron();
    var de = window.parent.document.documentElement;
    var son = parentTema();
    var obs = new MutationObserver(function () {
      var t = parentTema();
      if (t && t !== son) { son = t; temaUygulaGuvenli(t); }
    });
    obs.observe(de, { attributes: true, attributeFilter: ["data-theme", "class"] });
    // iframe kaldirilinca (HEPGO sayfa degisimi) parent'taki gozlemci sokulur; aksi halde closure iframe realm'ini (Cesium) sizdirir
    window.addEventListener("pagehide", function () { try { obs.disconnect(); } catch (e) {} }, { once: true });
  });

  // ---------------------------------------------------------------
  // 9. MENUBAR: HEPGO baglantilari (menubar.js IIFE yuklenmis; yeni
  //    ogeler kendi tiklama dinleyicisini tasir, menuyu window.menubarKapat
  //    (menubar.js:21) ile kapatir). index.html:84-93 #mbDronlar flyout'u
  //    (.mb-alt-menu) icine: Dron envanteri / Rotalar / Dron kopruleri;
  //    #menubar basina '< Dron Yonetimi' ust duzey girisi (dropdown'suz
  //    .mb-item; tiki dogrudan HEPGO'ya gider).
  // ---------------------------------------------------------------
  guvenli("menubar", function () {
    var menubar = document.getElementById("menubar");
    if (!menubar) return;

    function kapat() {
      try { if (typeof window.menubarKapat === "function") window.menubarKapat(); } catch (e) {}
    }
    function oge(id, ikon, anahtar, hash) {
      var o = el("div", "mb-oge", { id: id });
      var i = el("i", "fa-solid " + ikon);
      var sp = el("span", null, { "data-hepgo-i18n": anahtar });
      if (sozlukEklendi) sp.setAttribute("data-i18n", anahtar);
      sp.textContent = hepgoMetin(anahtar);
      o.appendChild(i); o.appendChild(sp);
      o.addEventListener("click", function (e) {
        e.stopPropagation();
        kapat();
        hepgoNav(hash);
      });
      return o;
    }

    // Ust duzey '< Dron Yonetimi' girisi (en basta)
    if (!document.getElementById("mbHepgoGeri")) {
      var item = el("div", "mb-item", { id: "mbHepgoGeri" });
      var etiket = el("span", "mb-etiket", { title: "HEPGO Dron Yönetimi" });
      etiket.appendChild(document.createTextNode("◀ "));
      var sp = el("span", null, { "data-hepgo-i18n": "hepgoDronYonetimi" });
      if (sozlukEklendi) sp.setAttribute("data-i18n", "hepgoDronYonetimi");
      sp.textContent = hepgoMetin("hepgoDronYonetimi");
      etiket.appendChild(sp);
      item.appendChild(etiket);
      etiket.addEventListener("click", function (e) {
        e.stopPropagation();
        kapat();
        hepgoNav("#/field/drones");
      });
      menubar.insertBefore(item, menubar.firstChild);
    }

    // Dronlar flyout'una HEPGO sayfalari
    var hedef = menubar.querySelector("#mbDronlar .mb-alt-menu") ||
                menubar.querySelector("#mbCihazlar .mb-dropdown") ||
                menubar.querySelector(".mb-item .mb-dropdown");
    if (hedef && !document.getElementById("mbHepgoEnvanter")) {
      hedef.appendChild(el("div", "mb-ayrac"));
      hedef.appendChild(oge("mbHepgoEnvanter", "fa-list", "hepgoMbEnvanter", "#/field/drones"));
      hedef.appendChild(oge("mbHepgoRotalar", "fa-route", "hepgoMbRotalar", "#/field/routes"));
      hedef.appendChild(oge("mbHepgoKopruler", "fa-diagram-project", "hepgoMbKopruler", "#/field/bridges"));
    }
  });

  // Statik basliklari simdi uygula (applyLanguage henuz cagrilmadi;
  // hepgo_ws.js sonunda cagiracak, sarmal yeniden uygular).
  guvenli("metinler", hepgoMetinleriUygula);

  // ---------------------------------------------------------------
  // 10. TAM EKRAN (arayuz.js:370-415 #btnTamEkran)
  //     arayuz.js document.documentElement.requestFullscreen() cagirir;
  //     iframe allow="fullscreen" oldugu icin (drone.js renderLive) bu
  //     iframe'i tam ekran yapar ve HEPGO basligi gorunmez -> DOKUNULMAZ.
  //     YEDEK: document.fullscreenEnabled false ise (izin/API yok) tik
  //     yakalama asamasinda kesilir, parent'a {t:'ops-fullscreen', on}
  //     gonderilir (drone.js:523-526 body.ops-full + parent fullscreen);
  //     ikon/ipucu ve window.bolumTamEkranModu (bolum_popup.js:285)
  //     yerelde guncellenir. Parent ESC ile ciktiysa fullscreenchange
  //     ile geri senkronlanir.
  // ---------------------------------------------------------------
  guvenli("tam-ekran", function () {
    var btn = document.getElementById("btnTamEkran");
    if (!btn) return;
    var apiVar = !!(document.fullscreenEnabled || document.webkitFullscreenEnabled);
    if (apiVar || !parentVarMi()) return;   // yerli davranis yeterli / parent yok

    var acik = false;
    function ikonGuncelle() {
      var i = btn.querySelector("i");
      if (i) {
        i.classList.toggle("fa-expand", !acik);
        i.classList.toggle("fa-compress", acik);
      }
      var t = sozluk();
      btn.title = acik ? (t.btnTamEkranKapat || "Tam Ekrandan Çık")
                       : (t.ipTamEkran || t.btnTamEkran || "Tam Ekran");
    }
    function uygula(on, yalnizYerel) {
      acik = !!on;
      if (!yalnizYerel) parentGonder({ t: "ops-fullscreen", on: acik });
      try {
        if (typeof window.bolumTamEkranModu === "function") window.bolumTamEkranModu(acik);
      } catch (e) { uyar("bolumTamEkranModu", e); }
      ikonGuncelle();
      try {
        var v = (typeof window.__haritaViewerAl === "function") ? window.__haritaViewerAl() : null;
        if (v && typeof v.resize === "function") setTimeout(function () { v.resize(); }, 50);
      } catch (e) {}
    }
    // Yakalama asamasi: arayuz.js'in hedef dinleyicisinden once calisir;
    // stopPropagation ile requestFullscreen denemesi (reddedilir) engellenir.
    document.addEventListener("click", function (e) {
      var hedef = e.target;
      if (!hedef || !(hedef === btn || btn.contains(hedef))) return;
      e.stopPropagation();
      e.preventDefault();
      uygula(!acik);
    }, true);
    try {
      var fsFn = function () {
        var pf = window.parent.document.fullscreenElement;
        if (!pf && acik) uygula(false, true);
      };
      window.parent.document.addEventListener("fullscreenchange", fsFn);
      window.addEventListener("pagehide", function () { try { window.parent.document.removeEventListener("fullscreenchange", fsFn); } catch (e) {} }, { once: true });
    } catch (e) {}
    ikonGuncelle();
  });

  // ---------------------------------------------------------------
  // 11. DIGER GUVENLI YAMALAR (kaynak taramasi)
  // ---------------------------------------------------------------
  // 11a. menubar.js:108-123 #mbDronGecmis -> dronGecmisAc() (Bolum 5)
  //      zaten HEPGO'ya yonlenir; index'te kalmissa 'Gecmis modulu
  //      yuklenemedi' toast'i cikmaz. Ek is gerekmez.
  // 11b. dronlar.js:1981-1982 window.kalkisKontrolAc TANIMLANMAZ ->
  //      onayIste(onayTakeoff) yedegi (kalkis_kontrol.js yuklenmez).
  // 11c. #bagEklePerde / #btnYeni* (seri.js:1399-1434 guard'siz) DOM'da
  //      kalir, hepgo.css gizler; burada ek is yok.
  // 11d. Kart kamera satiri, radar, M50, EO kancalari: dronlar.js typeof
  //      korumali; TANIMLANMAZ (bos kalir).
  // 11e. harita.js:329-330 ayar_kaydet ve tema.js:50 tema mesajlari sahte
  //      ws'de yutulur (hepgo_ws.js). Burada ek is yok.
  // 11f. Yakalanmamis hata gorunurlugu: ilk calistirma taramasi
  //      (plan adim 8) tarayici konsoluna dayanir; operatore toast ile
  //      gurultu verilmez. Yalniz ReferenceError'lar console.error ile
  //      [hepgo_patch] onekiyle isaretlenir ki kaynak satiri hizla bulunsun.
  guvenli("hata-isaret", function () {
    window.addEventListener("error", function (ev) {
      try {
        var hata = ev && ev.error;
        if (hata && hata.name === "ReferenceError") {
          console.error("[hepgo_patch] ReferenceError:", hata.message,
            "@", (ev.filename || "?") + ":" + (ev.lineno || "?"));
        }
      } catch (e) {}
    });
  });
})();
