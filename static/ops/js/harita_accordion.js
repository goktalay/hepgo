/* FAZ18-PANEL-ISKELET: IS 33 — HARITA AYARLARI ACCORDION
 * ------------------------------------------------------------------
 * Kullanici istegi: "harita ayarlarinda ozellik gruplama panellerini
 * acilir kapanir panellere cevir ki gereksizleri kapatayim, scroll
 * cikmasin."
 *
 * OLCUM: Harita Ayarlari penceresinde bes `.alt-bolum` grubu var ve
 * hepsi ayni anda acik. Pencere 82vh sinirina dayanip uzun bir scroll
 * uretiyor.
 *
 * TASARIM KARARLARI
 * 1. GRUP KIMLIGI: `.alt-baslik` icindeki `data-i18n` degeri kimlik
 *    olarak kullanilir. DOM sirasi (indeks) kullanilmaz; ileride grup
 *    eklenir/silinirse kayitli durumlar yanlis gruplara uygulanirdi.
 * 2. VARSAYILAN: yalniz ILK grup (Harita Kaynagi) acik. Kullanici
 *    bir seye dokunmadan once pencere kisa gorunur; asil sikayet
 *    buydu.
 * 3. KALICILIK: durum localStorage'da. Anahtar surum tasimaz;
 *    kullanici tercihi surum yukseltmesinde kaybolmamali.
 * 4. GEC BAGLAMA: pencere HTML'i statik oldugu icin DOMContentLoaded
 *    yeterli. Ancak betik `defer` olmadan yuklenirse gecikmeli olarak
 *    da denenir.
 */
(function () {
  "use strict";

  var ANAHTAR = "goktungu_harita_accordion";
  var HEDEF = "#haritaPopup .alt-bolum";

  function durumOku() {
    try {
      var h = localStorage.getItem(ANAHTAR);
      return h ? JSON.parse(h) : null;
    } catch (e) {
      return null;
    }
  }

  function durumYaz(d) {
    try {
      localStorage.setItem(ANAHTAR, JSON.stringify(d));
    } catch (e) {
      /* Depolama kotasi dolu veya gizli kip: sessizce gec.
         Accordion yine calisir, yalniz hatirlamaz. */
    }
  }

  function kimlik(bolum) {
    var b = bolum.querySelector(".alt-baslik [data-i18n]");
    if (b) return b.getAttribute("data-i18n");
    // Yedek: baslik metni. i18n ile degisebilir ama kimliksiz
    // kalmaktan iyidir.
    var h = bolum.querySelector(".alt-baslik");
    return h ? (h.textContent || "").trim().slice(0, 40) : null;
  }

  function kur() {
    var bolumler = document.querySelectorAll(HEDEF);
    if (!bolumler.length) return false;

    var kayit = durumOku();
    var ilk = true;

    bolumler.forEach(function (bolum) {
      var baslik = bolum.querySelector(".alt-baslik");
      var alan = bolum.querySelector(".alan");
      // Baslik veya govde yoksa accordion anlamsiz: dokunma.
      if (!baslik || !alan) return;

      var id = kimlik(bolum);

      // BASLANGIC DURUMU
      var kapali;
      if (kayit && id && Object.prototype.hasOwnProperty.call(kayit, id)) {
        kapali = !!kayit[id];
      } else {
        // Kayit yok: yalniz ilk grup acik.
        kapali = !ilk;
      }
      bolum.classList.toggle("kapali", kapali);
      ilk = false;

      // Erisilebilirlik: klavye ile de acilabilsin.
      baslik.setAttribute("role", "button");
      baslik.setAttribute("tabindex", "0");
      baslik.setAttribute("aria-expanded", kapali ? "false" : "true");

      function cevir() {
        var yeni = !bolum.classList.contains("kapali");
        bolum.classList.toggle("kapali", yeni);
        baslik.setAttribute("aria-expanded", yeni ? "false" : "true");
        if (!id) return;
        var d = durumOku() || {};
        d[id] = yeni;
        durumYaz(d);
      }

      baslik.addEventListener("click", cevir);
      baslik.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          cevir();
        }
      });
    });
    return true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      if (!kur()) setTimeout(kur, 400);
    });
  } else if (!kur()) {
    setTimeout(kur, 400);
  }
})();
