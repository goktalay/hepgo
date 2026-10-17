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
//   dronGecmisAc        History -> HEPGO #/drone/drones[/<id>]
//   hepgoNav(hash)      parent.postMessage({t:'ops-nav', hash})
//   hepgoTemaSenkron()  parent data-theme -> temaUygula
//   hepgoDil()          parent HEPGO dili -> "TR" | "EN" (applyLanguage)
//   hepgoMetinleriUygula()  HEPGO baslik metinlerini yeniden yazar
//   hepgoDronIdBul(sysid)   HEPGO_ENVANTER'den dron id (hepgo_ws.js
//                           kendi surumunu tanimlarsa o kullanilir)
//   hepgoYzSeriKonumla()    Baglanti Yoneticisi (#yzSeri) varsayilan konum
//
// FAZ 1 (Ekim 2026): GOKTUNGU ust bari (menubar) ve tam ekran dugmesi
// index.html'den KALDIRILDI (kullanici karari 2); buradaki menubar ve
// tam ekran yamalari da silindi. Tam ekran HEPGO'nun kendi dugmesiyle
// (parent data-immersive -> body.immersive) yapilir; dil/tema parent'tan.
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
  //      i18nGetir           arayuz.js:384/388 (tam ekran dugmesi kaldirildi; stub zararsiz)
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
  //    cagirir. Dron id biliniyorsa #/drone/drones/<id>, yoksa liste.
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
      hepgoNav(id != null ? "#/drone/drones/" + encodeURIComponent(String(id)) : "#/drone/drones");
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
    hepgoPanelSeri:     { TR: "GÖREV DRONLARI / KÖPRÜLER", EN: "MISSION DRONES / BRIDGES" },
    hepgoBagToolbar:    { TR: "KÖPRÜ",                      EN: "BRIDGE" },
    hepgoBtnBaglanti:   { TR: "Bağlantı yöneticisi (görevin dronları ve köprüleri)", EN: "Connection manager (mission drones and bridges)" }
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
    // HEPGO'nun eklediği ögeler: data-hepgo-i18n (metin) / data-hepgo-i18n-title (ipucu)
    var ogeler = document.querySelectorAll("[data-hepgo-i18n]");
    for (var m = 0; m < ogeler.length; m++) {
      ogeler[m].textContent = hepgoMetin(ogeler[m].getAttribute("data-hepgo-i18n"));
    }
    var ipuclari = document.querySelectorAll("[data-hepgo-i18n-title]");
    for (var n = 0; n < ipuclari.length; n++) {
      ipuclari[n].setAttribute("title", hepgoMetin(ipuclari[n].getAttribute("data-hepgo-i18n-title")));
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
  // 8. TEMA + DIL SENKRONU (kullanici karari 3: Arayuz Ayarlari yok;
  //    tema ve dil HEPGO'dan gelir)
  //    Tema: tema.js:11 temaUygula; HEPGO prefs.js documentElement.
  //    dataset.theme = 'dark' | nitelik yok. Ayni koken: parent.document
  //    okunabilir. 'dark' -> 'koyu', aksi 'acik'. temaUygula stub
  //    eksikligiyle yarim kalirsa (tema.js:29/32) data-tema niteligi
  //    (tema.js:42-43) burada ayrica garanti edilir.
  //    Dil: HEPGO i18n.js documentElement.lang = 'tr' | 'en' | 'de' | ...
  //    (localStorage 'caymaz.lang'). GOKTUNGU yalniz TR/EN bilir:
  //    'tr*' -> TR, diger her dil -> EN. applyLanguage(dil, true)
  //    gcs_dil'e de yazar; i18n.js:9 bir sonraki acilista ayni dille
  //    baslar (parent dili yine ustune uygulanir).
  //    Parent'ta data-theme / lang degisimi tek MutationObserver ile izlenir.
  // ---------------------------------------------------------------
  function parentTema() {
    try {
      if (!parentVarMi()) return null;
      var de = window.parent.document.documentElement;
      return (de.getAttribute("data-theme") === "dark") ? "koyu" : "acik";
    } catch (e) { return null; }
  }
  function parentDil() {
    try {
      if (!parentVarMi()) return null;
      var l = String(window.parent.document.documentElement.getAttribute("lang") || "").toLowerCase();
      if (!l) { try { l = String(window.parent.localStorage.getItem("caymaz.lang") || "").toLowerCase(); } catch (e2) {} }
      if (!l) return null;
      return (l.indexOf("tr") === 0) ? "TR" : "EN";
    } catch (e) { return null; }
  }
  function hepgoDil() {
    var d = parentDil();
    if (d) return d;
    try { if (typeof aktifDil === "string" && (aktifDil === "TR" || aktifDil === "EN")) return aktifDil; } catch (e) {}
    return "TR";
  }
  window.hepgoDil = hepgoDil;
  function dilUygulaGuvenli(dil) {
    if (dil !== "TR" && dil !== "EN") return;
    try { if (typeof applyLanguage === "function") applyLanguage(dil, true); } catch (e) { uyar("applyLanguage", e); }
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
  guvenli("tema-dil-senkron", function () {
    if (!parentVarMi()) return;
    hepgoTemaSenkron();
    // Dil ilk kez hepgo_ws.js hepgoBaslat'ta uygulanir (applyLanguage(hepgoDil(), true)); burada yalniz degisim izlenir.
    var de = window.parent.document.documentElement;
    var sonTema = parentTema(), sonDil = parentDil();
    var obs = new MutationObserver(function () {
      var t = parentTema();
      if (t && t !== sonTema) { sonTema = t; temaUygulaGuvenli(t); }
      var d = parentDil();
      if (d && d !== sonDil) { sonDil = d; dilUygulaGuvenli(d); }
    });
    obs.observe(de, { attributes: true, attributeFilter: ["data-theme", "class", "lang"] });
    // iframe kaldirilinca (HEPGO sayfa degisimi) parent'taki gozlemci sokulur; aksi halde closure iframe realm'ini (Cesium) sizdirir
    window.addEventListener("pagehide", function () { try { obs.disconnect(); } catch (e) {} }, { once: true });
  });

  // ---------------------------------------------------------------
  // 9. BAGLANTI YONETICISI DUGMESI (#btnBaglantiPanel, sol harita arac
  //    grubu). Menubar kaldirildigi icin #yzSeri'yi (gorevin dronlari ve
  //    koprulari) acip kapatan tek giris noktasi budur. Acma arayuz.js:69
  //    window.yuzenPanelAc ile (kayitli konum/boyut geri yuklenir;
  //    pencereKonumUygula). Kayitli konum yoksa arayuz.js:21-28 paneli
  //    ekran ust-ortasina koyar (tb-btn yok); HEPGO varsayilani SAG UST
  //    kosedir (GOKTUNGU'da dron kartlari sag paneldeydi; sol arac grubu
  //    ve Harita Ayarlari popup'iyla cakismaz). hepgo_ws.js ilk hello'da
  //    paneli acar ve ayni konum islevini (hepgoYzSeriKonumla) cagirir.
  //    Dugmenin .acik durumu panelin class degisimi izlenerek tutulur.
  // ---------------------------------------------------------------
  guvenli("baglanti-dugmesi", function () {
    var btn = document.getElementById("btnBaglantiPanel");
    var panel = document.getElementById("yzSeri");
    if (!panel) return;
    function acikMi() { return !panel.classList.contains("yuzen-gizli"); }
    function konumla() {
      // popup_tasima.js pencereKonumUygula kayitli konumu uyguladiysa (dataset.tasindi="1") dokunulmaz
      if (panel.dataset.tasindi === "1") return;
      panel.style.transform = "";
      panel.style.left = "auto";
      panel.style.right = "12px";
      panel.style.top = "12px";
    }
    window.hepgoYzSeriKonumla = konumla;
    function ac() {
      if (typeof window.yuzenPanelAc === "function") window.yuzenPanelAc("yzSeri");
      else panel.classList.remove("yuzen-gizli");
      konumla();
    }
    function kapat() { panel.classList.add("yuzen-gizli"); }
    if (!btn) return;
    btn.setAttribute("data-hepgo-i18n-title", "hepgoBtnBaglanti");
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (acikMi()) kapat(); else ac();
    });
    var obs = new MutationObserver(function () { btn.classList.toggle("acik", acikMi()); });
    obs.observe(panel, { attributes: true, attributeFilter: ["class"] });
    btn.classList.toggle("acik", acikMi());
  });

  // Statik basliklari simdi uygula (applyLanguage henuz cagrilmadi;
  // hepgo_ws.js sonunda cagiracak, sarmal yeniden uygular).
  guvenli("metinler", hepgoMetinleriUygula);

  // ---------------------------------------------------------------
  // 10. TAM EKRAN: GOKTUNGU #btnTamEkran KALDIRILDI (kullanici karari 2).
  //     HEPGO'nun kendi tam ekran dugmesi (app.js fullscreenButton)
  //     parent sayfadaki data-immersive ile ust basligi ve alt bari
  //     gizler (body.immersive); iframe kalan alani kaplar. Parent tam
  //     ekrana girip ciktiginda iframe yerlesimi degisir: Cesium canvas
  //     boyutu tazelenir (harita.js viewer resize). parent.document
  //     ayni koken; dinleyici pagehide'da sokulur.
  // ---------------------------------------------------------------
  guvenli("tam-ekran-resize", function () {
    if (!parentVarMi()) return;
    var fsFn = function () {
      try {
        var v = (typeof window.__haritaViewerAl === "function") ? window.__haritaViewerAl() : null;
        if (!v && typeof viewer !== "undefined") v = viewer;
        if (v && typeof v.resize === "function") setTimeout(function () { v.resize(); }, 60);
      } catch (e) {}
    };
    window.parent.document.addEventListener("fullscreenchange", fsFn);
    window.addEventListener("pagehide", function () { try { window.parent.document.removeEventListener("fullscreenchange", fsFn); } catch (e) {} }, { once: true });
  });

  // ---------------------------------------------------------------
  // 11. DIGER GUVENLI YAMALAR (kaynak taramasi)
  // ---------------------------------------------------------------
  // 11a. menubar.js:108-123 #mbDronGecmis -> dronGecmisAc() (Bolum 5)
  //      zaten HEPGO'ya yonlenir; index'te kalmissa 'Gecmis modulu
  //      yuklenemedi' toast'i cikmaz. Ek is gerekmez.
  // 11b. kalkis_kontrol.js YUKLENIR: Takeoff -> kalkisKontrolAc (zorunlu kontrol
  //      listesi) -> {tip:'kalkis_kontrol'} -> hepgo_ws.js -> sunucu tek islem.
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

  // ---------------------------------------------------------------
  // 12. ALT BAR "HARITA: n KB · n karo" SAYACI
  //     GOKTUNGU'da bu gosterge sunucunun tile_cache_ozet iletisiyle
  //     dolar (harita.js:756-812 hrtCacheDurumYaz). HEPGO'da karo
  //     vekili/onbellegi yok; karolar dogrudan saglayicidan gelir.
  //     Istemci tarafinda PerformanceObserver ile bu oturumda indirilen
  //     karo sayisi ve (Timing-Allow-Origin varsa gercek, yoksa ~24 KB
  //     tahmini) toplam boyut ayni gostergeye yazilir.
  // ---------------------------------------------------------------
  guvenli("harita-sayac", function () {
    if (!document.getElementById("hrtCacheDurum") || typeof PerformanceObserver !== "function") return;
    var adet = 0, boyut = 0, bilinen = 0, zaman = null;
    var KARO = /arcgisonline\.com|openstreetmap\.org|opentopomap\.org|cartocdn\.com/;
    function yaz() {
      if (zaman) return;
      zaman = setTimeout(function () {
        zaman = null;
        var b = bilinen > 0 ? Math.round(boyut * adet / bilinen) : adet * 24 * 1024;
        if (typeof window.hrtCacheDurumYaz === "function") window.hrtCacheDurumYaz({ hazir: true, adet: adet, boyut: b });
      }, 500);
    }
    var po = new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (e) {
        if (!KARO.test(e.name || "")) return;
        adet++;
        var b = e.transferSize || e.encodedBodySize || 0;
        if (b > 0) { boyut += b; bilinen++; }
      });
      yaz();
    });
    po.observe({ type: "resource", buffered: true });
    window.addEventListener("pagehide", function () { try { po.disconnect(); } catch (e) {} }, { once: true });
    yaz();
  });
})();

// =====================================================================
// HEPGO FAZ 1b (kullanıcı geri bildirimi, 15 Ekim 2026)
//  - Bağlantı Yöneticisi paneli yok (hepgo.css gizler).
//  - Görevin dronları solda alt alta, KATLI kart; kapatılamaz; mıknatıslı (sürükleyince
//    birbirine / sol sütuna yapışır), sütundan ayrılabilir, sütuna geri bırakılabilir.
//  - Kart başlığının en sağında "Bağlan" düğmesi: bağlantı atanmışsa adını yazar;
//    atanmamışsa kart gri.
//  - HEPGO tam ekranında üstte firma logosu + adı, altında görev tanımı, sağda tarih/saat.
// GÖKTUNGU dosyalarına dokunulmaz: dronKartSurukleKur (function declaration → global
// nesne özelliği) burada değiştirilir; kartlar dronKartAyirToggle ile yüzen kipe alınır.
// =====================================================================
(function hepgoFaz1b() {
  var SOL = 52, UST = 10, ARA = 2, ESIK = 18, sira = 0, cizZaman = null;
  function ustOfset() {
    // Tam ekranda üst bant haritanın üstünde yüzer (üstten 20px): sütun bandın altından başlar
    var b = document.getElementById("hepgoUstBar");
    if (document.body.classList.contains("hepgo-tam") && b && b.offsetHeight) return Math.round(b.getBoundingClientRect().bottom) + 8;
    return UST;
  }
  function kartlar() { return Array.prototype.slice.call(document.querySelectorAll("body > .dron-kart.ayrik")); }
  function sutun() {
    return kartlar().filter(function (k) { return k.dataset.hepgoSerbest !== "1"; })
      .sort(function (a, b) { return (+a.dataset.hepgoSira || 0) - (+b.dataset.hepgoSira || 0); });
  }
  function diz() {
    cizZaman = null;
    var y = ustOfset();
    sutun().forEach(function (k) {
      if (k._hepgoSurukleniyor) return;
      k.style.left = SOL + "px"; k.style.top = y + "px";
      y += k.offsetHeight + ARA;
    });
  }
  function dizPlanla() { if (!cizZaman) cizZaman = requestAnimationFrame(diz); }
  window.hepgoKartDiz = dizPlanla;
  var ro = (typeof ResizeObserver === "function") ? new ResizeObserver(dizPlanla) : null;
  window.addEventListener("resize", dizPlanla);
  // kart silinince (dronSil) sütun yeniden dizilir
  try { new MutationObserver(dizPlanla).observe(document.body, { childList: true }); } catch (e) {}

  // ---- Sürükleme + mıknatıs (GÖKTUNGU dronKartSurukleKur yerine) ----
  function yapis(tasinan, x, y) {
    var w = tasinan.offsetWidth, hgt = tasinan.offsetHeight, iyi = null;
    function dene(nx, ny, d) { if (d <= ESIK && (!iyi || d < iyi.d)) iyi = { x: nx, y: ny, d: d }; }
    dene(SOL, y, Math.abs(x - SOL));   // sol sütun kılavuzu
    kartlar().forEach(function (k) {
      if (k === tasinan) return;
      var r = k.getBoundingClientRect();
      var dikey = Math.min(y + hgt, r.bottom) - Math.max(y, r.top) > -ESIK;
      var yatay = Math.min(x + w, r.right) - Math.max(x, r.left) > -ESIK;
      if (yatay) {
        dene(r.left, r.bottom + ARA, Math.abs(y - r.bottom - ARA) + Math.abs(x - r.left) * 0.05);   // altına
        dene(r.left, r.top - hgt - ARA, Math.abs(y + hgt + ARA - r.top) + Math.abs(x - r.left) * 0.05);   // üstüne
      }
      if (dikey) {
        dene(r.right + ARA, r.top, Math.abs(x - r.right - ARA) + Math.abs(y - r.top) * 0.05);   // sağına
        dene(r.left - w - ARA, r.top, Math.abs(x + w + ARA - r.left) + Math.abs(y - r.top) * 0.05);   // soluna
      }
    });
    return iyi;
  }
  window.dronKartSurukleKur = function (kok, baslik) {
    var s = null;
    baslik.addEventListener("pointerdown", function (ev) {
      if (!kok.classList.contains("ayrik") || ev.button !== 0) return;
      if (ev.target.closest("button")) return;
      var r = kok.getBoundingClientRect();
      s = { dx: ev.clientX - r.left, dy: ev.clientY - r.top, x0: ev.clientX, y0: ev.clientY, oynadi: false };
      try { baslik.setPointerCapture(ev.pointerId); } catch (e) {}
    });
    baslik.addEventListener("pointermove", function (ev) {
      if (!s) return;
      if (!s.oynadi && Math.abs(ev.clientX - s.x0) + Math.abs(ev.clientY - s.y0) < 5) return;
      s.oynadi = true; kok._hepgoSurukleniyor = true; kok.dataset.hepgoSerbest = "1";
      var x = Math.max(0, Math.min(ev.clientX - s.dx, window.innerWidth - kok.offsetWidth));
      var y = Math.max(0, Math.min(ev.clientY - s.dy, window.innerHeight - 30));
      var yp = yapis(kok, x, y);
      if (yp) { x = yp.x; y = yp.y; }
      kok.classList.toggle("dk-yapisiyor", !!yp);
      kok.style.left = x + "px"; kok.style.top = y + "px";
      dizPlanla();
    });
    function birak(ev) {
      if (!s) return;
      var oynadi = s.oynadi; s = null; kok._hepgoSurukleniyor = false;
      kok.classList.remove("dk-yapisiyor");
      try { baslik.releasePointerCapture(ev.pointerId); } catch (e) {}
      if (!oynadi) return;
      var x = parseFloat(kok.style.left) || 0, y = parseFloat(kok.style.top) || 0;
      if (Math.abs(x - SOL) <= ESIK) {   // sol sütuna geri bırakıldı: dikey konumuna göre sıraya girer
        delete kok.dataset.hepgoSerbest;
        var liste = sutun().filter(function (k) { return k !== kok; });
        var yer = liste.length;
        for (var i = 0; i < liste.length; i++) { if (y < (parseFloat(liste[i].style.top) || 0) + liste[i].offsetHeight / 2) { yer = i; break; } }
        liste.splice(yer, 0, kok);
        liste.forEach(function (k, i) { k.dataset.hepgoSira = String(i + 1); });
        sira = Math.max(sira, liste.length);
      }
      dizPlanla();
    }
    baslik.addEventListener("pointerup", birak);
    baslik.addEventListener("pointercancel", birak);
  };

  // ---- Kart hazırlığı (hepgo_ws.js her telemetri paketinde çağırır) ----
  function dugmeGuncelle(kok) {
    var b = kok._hkBagla;
    if (!b || !window.hepgoUcus) return;
    var u = kok.dataset.hepgoUcus ? window.hepgoUcus.bilgi(kok.dataset.hepgoUcus) : null;
    var imza = u ? [u.atanmis, u.ad, u.durum, u.kopru_online, u.sanal].join("|") : "-";
    if (b._imza === imza) return;
    b._imza = imza;
    kok.classList.toggle("hk-baglantisiz", !!u && !u.atanmis);
    if (!u) { b.style.display = "none"; return; }
    b.style.display = "";
    b.className = "hk-bagla " + (u.sanal ? "sanal" : !u.atanmis ? "yok" : u.durum);
    var ikon = u.durum === "baglaniyor" ? "fa-circle-notch fa-spin" : u.durum === "bagli" ? "fa-link" : "fa-plug";
    var metin = u.atanmis ? u.ad : "";
    b.innerHTML = "<i class='fa-solid " + ikon + "'></i>" + (metin ? "<span></span>" : "");
    if (metin) b.querySelector("span").textContent = metin;
    b.title = u.sanal ? "Sanal dron: sunucu içi simülatör, otomatik bağlı"
      : !u.atanmis ? "Bağlantı atanmamış — görev › Uçuş Yönetimi › Düzenle › Bağlantı"
      : u.durum === "bagli" ? "Bağlı: " + u.ad + " (tıkla: bağlantıyı kes)"
      : u.durum === "baglaniyor" ? "Bağlanıyor… (tıkla: vazgeç)"
      : (u.kopru_online ? "Bağlan: " + u.ad : "Köprü çevrimdışı: " + u.ad);
  }
  window.hepgoKartHazirla = function (d) {
    var kart = (typeof dronKartlar === "object" && dronKartlar) ? dronKartlar[d.sysid] : null;
    if (!kart || !kart.kok) return;
    var kok = kart.kok;
    kok.dataset.hepgoUcus = (d.hepgo_ucus !== null && d.hepgo_ucus !== undefined) ? String(d.hepgo_ucus) : "";
    if (!kok.dataset.hepgoHazir) {
      kok.dataset.hepgoHazir = "1";
      if (!kok.classList.contains("ayrik") && typeof dronKartAyirToggle === "function") {
        try { dronKartAyirToggle(d.sysid); } catch (e) { console.error("[hepgo] kart ayrılamadı", e); }
      }
      if (!document.documentElement.dataset.hepgoSim) kok.classList.add("dk-yalniz-baslik");   // katlı başlar (yalnız başlık); §14 simülatörde açık
      try { if (kok._btnKucult) kok._btnKucult.innerHTML = DK_BUYULT_IKON; } catch (e) {}
      kok.dataset.hepgoSira = String(++sira);
      if (ro) ro.observe(kok);
      var b = document.createElement("button");
      b.type = "button"; b.className = "hk-bagla";
      b.addEventListener("pointerdown", function (e) { e.stopPropagation(); });
      b.addEventListener("dblclick", function (e) { e.stopPropagation(); });
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        var u = kok.dataset.hepgoUcus ? window.hepgoUcus.bilgi(kok.dataset.hepgoUcus) : null;
        if (!u || u.sanal) return;
        if (!u.atanmis) {
          if (typeof window.uyariToastGoster === "function")
            window.uyariToastGoster({ seviye: "uyari", kategori: "köprü", mesaj: u.etiket + ": bağlantı atanmamış. Saha görevi › Uçuş Yönetimi › Düzenle › Bağlantı panelinden köprü ve erişim ayarlarını seçin." });
          return;
        }
        if (u.durum === "kapali") window.hepgoUcus.baglan(u.id); else window.hepgoUcus.kes(u.id);
      });
      kart.baslik.appendChild(b);   // başlığın en sağı
      kok._hkBagla = b;
      dizPlanla();
    }
    dugmeGuncelle(kok);
  };

  // ---- HEPGO tam ekran üst bandı ----
  var meta = null, saatZaman = null;
  function ustBarDoldur() {
    var g = (window.hepgoUcus && window.hepgoUcus.gorev()) || {};
    // Saha görevinin açıklaması (note) üst bantta gösterilmez (kullanıcı isteği): kod · görev yeri · pilot
    var parcalar = [g.code, g.location_name].filter(function (x) { return x; });
    var gEl = document.getElementById("hepgoUstGorev");
    if (gEl) gEl.textContent = parcalar.join(" · ") + (g.pilot_name ? " · Pilot: " + g.pilot_name : "");
    if (meta) {
      var f = document.getElementById("hepgoUstFirma"), l = document.getElementById("hepgoUstLogo");
      if (f) f.textContent = meta.company || "";
      if (l && !l.getAttribute("src")) l.src = meta.logo_url || "/static/img/hepgo-logo.png";
    }
  }
  function saat() {
    var el = document.getElementById("hepgoUstSaat");
    if (!el) return;
    var d = new Date();
    el.innerHTML = "";
    var t = document.createElement("b"); t.textContent = d.toLocaleTimeString("tr-TR");
    var g = document.createElement("span"); g.textContent = d.toLocaleDateString("tr-TR", { day: "2-digit", month: "long", year: "numeric", weekday: "long" });
    el.appendChild(t); el.appendChild(g);
  }
  function tamGuncelle() {
    var tam = false;
    try { tam = !!(window.parent && window.parent !== window && window.parent.document.fullscreenElement); } catch (e) {}
    document.body.classList.toggle("hepgo-tam", tam);
    // GÖKTUNGU'nun kendi tam ekran kuralları (stil.css "TAM EKRAN MODU"): alt bar ve konsol harita üstünde yüzer
    document.body.classList.toggle("tam-ekran-modu", tam);
    if (tam) {
      if (!meta) fetch("/api/meta", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (m) { meta = m; ustBarDoldur(); }).catch(function () {});
      ustBarDoldur(); saat();
      if (!saatZaman) saatZaman = setInterval(function () { saat(); ustBarDoldur(); }, 1000);
    } else if (saatZaman) { clearInterval(saatZaman); saatZaman = null; }
    dizPlanla();
    try { var v = window.__haritaViewerAl && window.__haritaViewerAl(); if (v) setTimeout(function () { v.resize(); }, 60); } catch (e) {}
  }
  try {
    var pd = window.parent.document;
    pd.addEventListener("fullscreenchange", tamGuncelle);
    window.addEventListener("pagehide", function () { try { pd.removeEventListener("fullscreenchange", tamGuncelle); } catch (e) {} }, { once: true });
  } catch (e) {}
  tamGuncelle();
})();

// =====================================================================
// HEPGO: Sabit kanat mod listesine TAKEOFF (ArduPlane custom_mode 13). Karttaki Takeoff düğmesi sabit kanatta sunucuda
// TKOFF_ALT + TAKEOFF modu + ARM akışını yürütür (drone_hub._plane_takeoff); pilot modu listeden de seçebilsin.
// dronlar.js DK_MODLAR üst düzey const (ortak sözcüksel kapsam): dizi yerinde genişletilir, GÖKTUNGU dosyasına dokunulmaz.
// =====================================================================
(function hepgoPlaneTakeoffModu() {
  try {
    if (typeof DK_MODLAR === "undefined" || !Array.isArray(DK_MODLAR.plane)) return;
    if (DK_MODLAR.plane.some(function (m) { return Number(m[0]) === 13; })) return;
    var i = DK_MODLAR.plane.findIndex(function (m) { return Number(m[0]) > 13; });
    DK_MODLAR.plane.splice(i < 0 ? DK_MODLAR.plane.length : i, 0, [13, "TAKEOFF"]);
  } catch (e) { console.error("[hepgo_patch] TAKEOFF modu eklenemedi", e); }
})();
