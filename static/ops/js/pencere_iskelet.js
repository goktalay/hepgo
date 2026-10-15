/* IS50-PENCERE-ISKELET-V2
 * ===================================================================
 * PENCERE ISKELETI — Kaydet/Iptal dugmelerini pencerenin altina sabitler
 * ===================================================================
 *
 * OLCULEN SORUN
 * -------------
 * index.html icinde 4 pencerede dugme satiri, kaydirilan govdenin
 * ICINDE yer aliyor:
 *
 *   <div id="bagEkleKutu">
 *     <div class="popup-baslik">...</div>
 *     <div class="lok-kaydet-icerik">      <- kaydirilan govde
 *        ...form alanlari...
 *        <div class="lok-dugme-satir">     <- DUGMELER BURADA (yanlis)
 *     </div>
 *   </div>
 *
 * Form uzayip govde kaydirilmaya baslayinca dugmeler de icerikle
 * birlikte kayiyor ve ekran disina cikiyor.
 *
 * Salt CSS ile cozulemez: bir oge, kaydirilan kabin cocuguyken
 * o kabin disinda sabit kalamaz. `position:sticky` denendi ve
 * gorsel denetimde basarisiz oldu (OLCUM 13).
 *
 * COZUM
 * -----
 * Dugme satirini calisma aninda govdeden alip kutunun DOGRUDAN
 * cocugu yapmak. Boylece uc katmanli duzen olusur ve CSS tarafi
 * (.pencere-iskelet) dogru calisir.
 *
 * TASARIM KARARLARI
 * -----------------
 * - Idempotent: ayni pencere birden cok kez islenmez.
 * - Pasif: hedef bulunamazsa sessizce atlanir, hicbir seyi bozmaz.
 * - Gec baglanan pencereler icin MutationObserver ile izlenir
 *   (bazi pencereler JS ile sonradan uretiliyor olabilir).
 * - Orijinal sinif adlari KORUNUR; yalnizca isaretleyici sinif
 *   eklenir. Boylece mevcut JS seciciler (querySelector) bozulmaz.
 */
(function () {
  'use strict';

  var ISLENDI = 'pencere-iskelet';

  /* Islenecek pencereler: kutu kimligi -> govde secicisi */
  var HEDEFLER = [
    { kutu: 'bagEkleKutu',     govde: '.lok-kaydet-icerik' },
    { kutu: 'lokKaydetKutu',   govde: '.lok-kaydet-icerik' },
    { kutu: 'kamModalKutu',    govde: '.lok-kaydet-icerik' },
    { kutu: 'spiralModalKutu', govde: '.lok-kaydet-icerik' }
  ];

  /* Dugme satiri olarak kabul edilen sinif adlari */
  var DUGME_SINIFLARI = ['lok-dugme-satir', 'rp-dugmeler', 'modal-dugmeler'];

  /* Hata satiri kimlikleri — dugmelerin hemen ustunde sabitlenir */
  var HATA_KIMLIKLERI = ['bagEkleHata', 'lokHata', 'kamHata', 'spiralHata'];

  function dugmeSatiriBul(govde) {
    for (var i = 0; i < DUGME_SINIFLARI.length; i++) {
      /* Yalnizca govdenin DOGRUDAN cocuklari arasinda ara.
         Ic ice formlarda yanlis ogeyi tasimamak icin onemli. */
      var cocuklar = govde.children;
      for (var j = 0; j < cocuklar.length; j++) {
        if (cocuklar[j].classList &&
            cocuklar[j].classList.contains(DUGME_SINIFLARI[i])) {
          return cocuklar[j];
        }
      }
    }
    return null;
  }

  function hataSatiriBul(govde) {
    for (var i = 0; i < HATA_KIMLIKLERI.length; i++) {
      var o = govde.querySelector('#' + HATA_KIMLIKLERI[i]);
      /* Yalnizca dogrudan cocuk olanlari tasi */
      if (o && o.parentElement === govde) { return o; }
    }
    return null;
  }

  function pencereIsle(tanim) {
    var kutu = document.getElementById(tanim.kutu);
    if (!kutu) { return false; }
    if (kutu.classList.contains(ISLENDI)) { return false; }  /* idempotent */

    var govde = kutu.querySelector(tanim.govde);
    if (!govde || govde.parentElement !== kutu) { return false; }

    var dugme = dugmeSatiriBul(govde);
    if (!dugme) { return false; }

    var hata = hataSatiriBul(govde);

    /* Tasima: hata satiri once, dugme satiri sonra; ikisi de
       kutunun sonuna eklenir. appendChild ayni ogeyi tasir,
       kopyalamaz — olay dinleyicileri korunur. */
    if (hata) {
      hata.classList.add('pencere-hata-serit');
      kutu.appendChild(hata);
    }
    dugme.classList.add('pencere-dugme-serit');
    kutu.appendChild(dugme);

    govde.classList.add('pencere-govde');
    kutu.classList.add(ISLENDI);
    return true;
  }

  function tumunuIsle() {
    var sayac = 0;
    for (var i = 0; i < HEDEFLER.length; i++) {
      if (pencereIsle(HEDEFLER[i])) { sayac++; }
    }
    return sayac;
  }

  function baslat() {
    tumunuIsle();

    /* Bazi pencereler DOM'a sonradan eklenebilir. Govde degisimlerini
       izleyip yeni gelenleri de isle. Islenmis pencereler idempotent
       kontrol sayesinde tekrar islenmez. */
    if (typeof MutationObserver === 'function' && document.body) {
      var gozlemci = new MutationObserver(function () { tumunuIsle(); });
      gozlemci.observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', baslat);
  } else {
    baslat();
  }

  /* Sinav ve tani icin disa ac */
  window.PencereIskelet = { isle: tumunuIsle, isaret: 'IS50-PENCERE-ISKELET-V2' };
})();
