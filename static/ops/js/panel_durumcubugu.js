/* GOKTUNGU GCS — panel_durumcubugu.js
 * IS51-PANEL-DURUMCUBUGU-V1  (App 2.4.110)
 * ===================================================================
 * PANEL DURUM CUBUGU — her yonetim panelinin altinda ozet sayac
 * ===================================================================
 *
 * OLCULEN SORUN
 * -------------
 * On yonetim panelinin hicbirinde alt durum cubugu yoktu. Kullanici
 * "kac baglanti var", "kac kamera oynuyor", "kac kisi kayitli"
 * sorularini ancak listeyi elle sayarak yanitlayabiliyordu.
 *
 * COZUM
 * -----
 * Her panelin kabina, SON cocuk olarak bir `.panel-durum-cubugu`
 * seridi eklenir. Serit ikon + metin tasir. Sayilar DOM'dan okunur.
 *
 * NEDEN DOM TABANLI SAYIM
 * -----------------------
 * Sayac verilerini tutan diziler (kameralar, rotalar, sonKisiler,
 * kayitsizlar ...) modul ici IIFE kapsamindadir ve disariya
 * acilmamistir (yalniz `window._aiAraclarSon` istisna). Bu dizilere
 * erismek icin on ayri dosyayi degistirmek gerekirdi — yama yuzeyi
 * buyur, gerileme riski artar.
 *
 * DOM sayimi ise:
 *   - hicbir mevcut dosyaya dokunmaz (yalniz bu modul + CSS + 4 satir)
 *   - liste her yeniden cizildiginde MutationObserver ile yakalanir
 *   - kaynak veri ile gorunen liste arasinda fark olusamaz
 *
 * SAYIM TUZAKLARI (olcumde tespit edildi)
 * ---------------------------------------
 * 1. Bos durum ogesi `.bos-panel` sinifi tasir ve bazi panellerde
 *    `.ai-satir` sarmalayicisi icindedir. Sayimdan DUSULUR.
 * 2. AI Sunucular listesinde kopru baslik satirlari da `.ai-satir`
 *    benzeri gorunur; gercek sunucu satirlari `[data-ai-sunucu]`
 *    niteligi tasir. Sunucu sayimi bu nitelikle yapilir.
 * 3. Gecmis Yoneticisi'nde ucus listesi yalniz SECILI dron acikken
 *    cizilir; toplam ucus sayisi dron satirlarindaki `.gc-dron-sayi`
 *    rozetlerinin toplamidir.
 *
 * TASARIM KARARLARI
 * -----------------
 * - Idempotent: ayni panele ikinci serit eklenmez.
 * - Pasif: panel DOM'da yoksa sessizce atlanir.
 * - Gec baglanan paneller (Kameralar/Rotalar/Gecmis calisma aninda
 *   uretilir) MutationObserver ile yakalanir.
 * - Sayac guncellemesi requestAnimationFrame ile birlestirilir;
 *   liste cizimi sirasinda onlarca mutation tetiklense bile tek
 *   hesap yapilir.
 * - i18n: metinler `D()` sozlugunden okunur, yoksa Turkce yedege
 *   duser. Dil degisince `window.panelDurumTazele()` cagrilir.
 */
(function () {
  "use strict";

  var ISARET = "IS51-PANEL-DURUMCUBUGU-V1";
  var SERIT_SINIF = "panel-durum-cubugu";
  var ISLENDI = "pdc-islendi";

  /* ---------------------------------------------------------------
   * Sozluk erisimi — i18n.js yuklenmemis olabilir (bagimsiz sayfalar)
   * --------------------------------------------------------------- */
  function S(anahtar, yedek) {
    try {
      if (typeof D === "function") {
        var t = D();
        if (t && t[anahtar] !== undefined) return t[anahtar];
      }
    } catch (e) {}
    return yedek;
  }

  /* ---------------------------------------------------------------
   * Sayim yardimcilari
   * --------------------------------------------------------------- */

  /* Bos durum gostergesi mi? Sayimdan dusulur. */
  function bosMu(oge) {
    if (!oge || !oge.classList) return true;
    if (oge.classList.contains("bos-panel")) return true;
    /* Bos durum bazen `.ai-satir` sarmalayicisi icinde gelir */
    if (oge.querySelector && oge.querySelector(".bos-panel")) return true;
    return false;
  }

  /* Kap icinde secici ile eslesen, bos olmayan ogeleri sayar. */
  function say(kapSecici, satirSecici) {
    var kap = document.querySelector(kapSecici);
    if (!kap) return 0;
    var liste = kap.querySelectorAll(satirSecici);
    var n = 0;
    for (var i = 0; i < liste.length; i++) {
      if (!bosMu(liste[i])) n++;
    }
    return n;
  }

  /* Kosulsuz sayim (bos denetimi gereksiz oldugunda) */
  function sayHam(kapSecici, satirSecici) {
    var kap = document.querySelector(kapSecici);
    if (!kap) return 0;
    return kap.querySelectorAll(satirSecici).length;
  }

  /* ---------------------------------------------------------------
   * PANEL TANIMLARI
   *
   * kap    : statusbar'in eklenecegi pencere kabi (secici)
   * izle   : sayaci tetikleyecek liste kabi (secici) — yoksa `kap`
   * ikon   : Font Awesome sinifi (kullanici istegi: her panelde ikon)
   * metin  : () => string   statusbar metnini uretir
   * --------------------------------------------------------------- */
  var PANELLER = [
    /* 1) Baglanti Yoneticisi — "Bağlantı Sayısı : 0/0 (Toplam / Aktif)" */
    {
      ad: "baglanti",
      kap: "#yzSeri",
      izle: "#bagListe",
      ikon: "fa-solid fa-plug",
      metin: function () {
        var toplam = sayHam("#bagListe", ".bag-grup");
        var aktif = sayHam("#bagListe", ".bag-btn.bag-stop");
        return ciftDeger(S("sbBaglanti", "Bağlantı Sayısı"), toplam, aktif,
                         S("sbToplamAktif", "Toplam / Aktif"));
      }
    },

    /* 2) Gecmis Yoneticisi — "Uçuş Sayısı : 0/0 (Toplam / Filtreli)" */
    {
      ad: "gecmis",
      kap: ".gecmis-popup",
      izle: "#gcDronListe",
      ikon: "fa-solid fa-clock-rotate-left",
      metin: function () {
        /* Toplam: her dron satirindaki ucus rozetinin toplami.
           Ucus listesi yalniz secili dron acikken cizildigi icin
           `.gc-ucus` sayimi toplami VERMEZ. */
        var toplam = 0;
        var rozet = document.querySelectorAll("#gcDronListe .gc-dron-sayi");
        for (var i = 0; i < rozet.length; i++) {
          var v = parseInt(rozet[i].textContent, 10);
          if (!isNaN(v)) toplam += v;
        }
        /* Filtreli: filtre etkinse gorunen ucus satirlari, degilse toplam */
        var filtreVar = filtreAktifMi();
        var filtreli = filtreVar
          ? sayHam("#gcDronListe", ".gc-ucus")
          : toplam;
        return ciftDeger(S("sbUcus", "Uçuş Sayısı"), toplam, filtreli,
                         S("sbToplamFiltreli", "Toplam / Filtreli"));
      }
    },

    /* v2.4.198) Radarlar — "Radar Sayısı : 0/0 (Toplam / Bağlı)" */
    {
      ad: "radarlar",
      kap: "#yzRadarlar",
      izle: "#radarlarListe",
      ikon: "fa-solid fa-satellite-dish",
      metin: function () {
        var toplam = say("#radarlarListe", ".cl-satir");
        var bagli = sayHam("#radarlarListe", ".ra-nokta.d-bagli");
        return ciftDeger(S("sbRadar", "Radar Sayısı"), toplam, bagli,
                         S("sbToplamBagli", "Toplam / Bağlı"));
      }
    },
    /* v2.4.198) Elektro Optik Cihazları — "Elektro Optik Sayısı : 0/0" */
    {
      ad: "eo",
      kap: "#yzEoCihazlar",
      izle: "#eoCihazListe",
      ikon: "fa-solid fa-binoculars",
      metin: function () {
        var toplam = say("#eoCihazListe", ".cl-satir");
        var bagli = sayHam("#eoCihazListe", ".ra-nokta.d-bagli");
        return ciftDeger(S("sbEo", "Elektro Optik Sayısı"), toplam, bagli,
                         S("sbToplamBagli", "Toplam / Bağlı"));
      }
    },

    /* 3) Kameralar — "Kamera Sayısı : 0/0 (Toplam / Aktif)" */
    {
      ad: "kameralar",
      kap: "#bolumPopup_kameralar",
      izle: "#kameraListesi",
      ikon: "fa-solid fa-video",
      metin: function () {
        var toplam = say("#kameraListesi", ".kam-kart");
        /* Oynatilan kamerada dugme STOP durumundadir */
        var aktif = sayHam("#kameraListesi", ".kam-btn.kam-btn-stop");
        return ciftDeger(S("sbKamera", "Kamera Sayısı"), toplam, aktif,
                         S("sbToplamAktif", "Toplam / Aktif"));
      }
    },

    /* 4) Rotalar — "Rota Sayısı : 0" */
    {
      ad: "rotalar",
      kap: "#bolumPopup_rotalar",
      izle: "#rotaListesi",
      ikon: "fa-solid fa-route",
      metin: function () {
        return tekDeger(S("sbRota", "Rota Sayısı"),
                        say("#rotaListesi", ".rota-satir"));
      }
    },

    /* 5) Kayitli Lokasyonlar — "Lokasyon Sayısı : 0" */
    {
      ad: "lokasyonlar",
      kap: "#lokasyonPopup",
      izle: "#lokasyonListe",
      ikon: "fa-solid fa-location-dot",
      metin: function () {
        return tekDeger(S("sbLokasyon", "Lokasyon Sayısı"),
                        say("#lokasyonListe", ".lok-satir"));
      }
    },

    /* 6) AI Sunucular — "Sunucu Sayısı : 0/0 (Toplam / Aktif)" */
    {
      ad: "aisunucu",
      kap: "#aiSunucuPopup",
      izle: "#aiSunucuListe",
      ikon: "fa-solid fa-server",
      metin: function () {
        /* Gercek sunucu satirlari `data-ai-sunucu` tasir; kopru
           baslik satirlari (.ai-kopru-baslik) tasimaz. */
        var toplam = sayHam("#aiSunucuListe", "[data-ai-sunucu]");
        var aktif = sayHam("#aiSunucuListe",
                           "[data-ai-sunucu] .ai-led.cevrimici");
        return ciftDeger(S("sbSunucu", "Sunucu Sayısı"), toplam, aktif,
                         S("sbToplamAktif", "Toplam / Aktif"));
      }
    },

    /* 7) Kisiler — "Toplam Kişi Sayısı : 0, Toplam Yüz Sayısı : 0" */
    {
      ad: "aikisi",
      kap: "#aiKisiPopup",
      izle: "#aiKisiListe",
      ikon: "fa-solid fa-user-tag",
      metin: function () {
        var kisi = say("#aiKisiListe", ".ai-satir");
        var yuz = sayHam("#aiKisiListe", ".yuz-kut");
        return etiketDeger(S("sbKisiToplam", "Toplam Kişi Sayısı"), kisi) +
               ", " +
               etiketDeger(S("sbYuzToplam", "Toplam Yüz Sayısı"), yuz);
      }
    },

    /* 8) Araclar — "Toplam Araç Sayısı : 0" */
    {
      ad: "aiarac",
      kap: "#aiAracPopup",
      izle: "#aiAracListe",
      ikon: "fa-solid fa-car",
      metin: function () {
        return tekDeger(S("sbAracToplam", "Toplam Araç Sayısı"),
                        say("#aiAracListe", ".ai-satir"));
      }
    },

    /* 9) Kayitsiz Tespitler — "Toplam Tespit Sayısı : 0" */
    {
      ad: "aikayitsiz",
      kap: "#aiKayitsizPopup",
      izle: "#aiKayitsizListe",
      ikon: "fa-solid fa-circle-question",
      metin: function () {
        return tekDeger(S("sbTespitToplam", "Toplam Tespit Sayısı"),
                        say("#aiKayitsizListe", ".ai-tespit-satir"));
      }
    },

    /* 10) Tespit Gecmisi — "Toplam Tespit Sayısı : 0/0 (Toplam / Filtreli)" */
    {
      ad: "aigecmis",
      kap: "#aiGecmisPopup",
      izle: "#aiGecmisListe",
      ikon: "fa-solid fa-clock-rotate-left",
      metin: function () {
        /* Tespit gecmisi filtresi SUNUCU TARAFLIDIR: `gecmisAra()`
           filtreyi istege koyar, donen liste zaten filtrelidir.
           Bu yuzden istemcide filtresiz toplam BILINMEZ; gosterilen
           liste hem toplam hem filtreli degeri temsil eder. */
        var n = say("#aiGecmisListe", ".ai-tespit-satir");
        return ciftDeger(S("sbTespitToplam", "Toplam Tespit Sayısı"), n, n,
                         S("sbToplamFiltreli", "Toplam / Filtreli"));
      }
    }
  ];

  /* ---------------------------------------------------------------
   * Metin bicimleyicileri
   *
   * Kullanicinin verdigi bicim BIREBIR korunur:
   *   "Bağlantı Sayısı : 0/0 (Toplam / Aktif)"
   *   "Rota Sayısı : 0"
   * --------------------------------------------------------------- */
  function tekDeger(etiket, n) {
    return etiket + " : " + n;
  }
  function etiketDeger(etiket, n) {
    return etiket + " : " + n;
  }
  function ciftDeger(etiket, a, b, aciklama) {
    return etiket + " : " + a + "/" + b + " (" + aciklama + ")";
  }

  /* Gecmis Yoneticisi filtre cubugunda dolu alan var mi? */
  function filtreAktifMi() {
    var bar = document.getElementById("gcFiltreBar");
    if (!bar) return false;
    var alanlar = bar.querySelectorAll("select, input");
    for (var i = 0; i < alanlar.length; i++) {
      if (alanlar[i].value) return true;
    }
    return false;
  }

  /* ---------------------------------------------------------------
   * Serit uretimi ve enjeksiyonu
   * --------------------------------------------------------------- */
  function seritYap(tanim) {
    var serit = document.createElement("div");
    serit.className = SERIT_SINIF;
    serit.setAttribute("data-pdc", tanim.ad);

    var i = document.createElement("i");
    /* Sinif dizesi bosluklu: "fa-solid fa-plug" */
    String(tanim.ikon).trim().split(/\s+/).forEach(function (c) {
      if (c) i.classList.add(c);
    });
    serit.appendChild(i);

    var m = document.createElement("span");
    m.className = "pdc-metin";
    serit.appendChild(m);

    return serit;
  }

  /* Panele serit ekler. Zaten varsa hicbir sey yapmaz. */
  function panelIsle(tanim) {
    var kap = document.querySelector(tanim.kap);
    if (!kap) return false;
    if (kap.classList.contains(ISLENDI)) return false;

    var serit = seritYap(tanim);
    /* SON cocuk olarak eklenir. Kap flex-column oldugundan
       (veya CSS yamasi ile oyle yapildigindan) serit ALTA oturur. */
    kap.appendChild(serit);
    kap.classList.add(ISLENDI);
    return true;
  }

  /* ---------------------------------------------------------------
   * Sayac guncellemesi
   * --------------------------------------------------------------- */
  function seritTazele(tanim) {
    var kap = document.querySelector(tanim.kap);
    if (!kap) return;
    var serit = kap.querySelector(
      '.' + SERIT_SINIF + '[data-pdc="' + tanim.ad + '"]');
    if (!serit) return;
    var m = serit.querySelector(".pdc-metin");
    if (!m) return;
    var yeni;
    try {
      yeni = tanim.metin();
    } catch (e) {
      return;  /* Bir panelin hatasi digerlerini durdurmasin */
    }
    if (m.textContent !== yeni) m.textContent = yeni;
  }

  var beklemede = false;
  function tazeleIste() {
    if (beklemede) return;
    beklemede = true;
    var calistir = function () {
      beklemede = false;
      tumunuTazele();
    };
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(calistir);
    } else {
      setTimeout(calistir, 16);
    }
  }

  function tumunuTazele() {
    for (var i = 0; i < PANELLER.length; i++) {
      seritTazele(PANELLER[i]);
    }
  }

  function tumunuIsle() {
    var n = 0;
    for (var i = 0; i < PANELLER.length; i++) {
      if (panelIsle(PANELLER[i])) n++;
    }
    if (n) tazeleIste();
    return n;
  }

  /* ---------------------------------------------------------------
   * Baslatma
   * --------------------------------------------------------------- */
  function baslat() {
    tumunuIsle();
    tumunuTazele();

    if (typeof MutationObserver !== "function" || !document.body) return;

    /* Tek gozlemci: hem gec baglanan panelleri yakalar hem de
       liste degisimlerinde sayaci tazeler. Ayri ayri gozlemci
       yerine tek kok gozlemci kullanmak, panellerin calisma aninda
       DOM'a girip cikmasina karsi dayaniklidir. */
    var gozlemci = new MutationObserver(function (kayitlar) {
      /* Kendi urettigimiz serit degisiklikleri dongu yaratmasin */
      var ilgili = false;
      for (var i = 0; i < kayitlar.length; i++) {
        var hedef = kayitlar[i].target;
        if (hedef && hedef.closest &&
            hedef.closest("." + SERIT_SINIF)) continue;
        ilgili = true;
        break;
      }
      if (!ilgili) return;
      tumunuIsle();
      tazeleIste();
    });
    gozlemci.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", baslat);
  } else {
    baslat();
  }

  /* Dil degisiminde i18n.js bu islevi cagirir */
  window.panelDurumTazele = tumunuTazele;

  /* Sinav ve tani icin disa ac */
  window.PanelDurumCubugu = {
    isle: tumunuIsle,
    tazele: tumunuTazele,
    paneller: PANELLER,
    isaret: ISARET
  };
})();
