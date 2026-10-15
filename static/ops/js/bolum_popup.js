/* =====================================================================
   BOLUM POPUP (v2.1.7c)
   Sol/sag paneller TAMAMEN KALDIRILDI: tum bolumler (TESPIT, TAKIP,
   DRONLAR, KAMERALAR, ROTALAR) her zaman tasinabilir +
   boyutlandirilabilir POPUP olarak calisir.

   - Acilista tum acik bolumler otomatik popup olarak olusturulur.
   - Icerik DOM'u popup'a TASINIR (event listener'lar korunur).
   - Popup konum/boyutu gcs_pencere_konum (bp_<ad>, boyutlu) icinde.
   - Menuden bolum ac/kapa popup'i gosterir/gizler
     (menubar.js panelUygula bu modulun bolumPopupUygula'sini cagirir).
   ===================================================================== */
(function () {
  "use strict";

  const MOD_KEY = "gcs_bolum_mod";

  // Bolum tanimlari: menubar.js PANEL_BOLUM ile ayni adlar.
  // bas: toolbar/baslik elemani, icer: icerik elemani, taraf: sol/sag
  const BOLUMLER = {
    // v2.4.227: tespit/takip sol bolumleri kaldirildi (radar yonetim penceresi)
    // v2.4.33: ayri DRONLAR bolumu KALDIRILDI. Dron kartlari artik
    // Baglanti Yoneticisi grubunun icinde yasiyor. Kayit silinmezse
    // popupOlustur() olmayan ogeleri arar; sessizce null doner ama
    // menu ogesi hicbir sey yapmadigi icin kafa karistirir.
    // FAZ18-IS35: `pbaslik` = pencere basligi i18n anahtari.
    // Ust bara `.tb-etiket` gelen bolumlerde popup basligi ust bar
    // metnini KOPYALAMAZ; ayri bir metin kullanir (baslik yinelemesi).
    kameralar: { taraf: "sag", bas: "kameralarToolbar", icer: "kameralarIcerik", pbaslik: "bpBaslikKameralar" },
    rotalar:   { taraf: "sag", bas: "rotalarToolbar",   icer: "rotalarIcerik", pbaslik: "bpBaslikRotalar" },
  };

  // v2.1.7c: paneller kaldirildi - her bolum DAIMA popup modunda
  let modlar = {};
  for (const ad in BOLUMLER) modlar[ad] = "popup";
  try { localStorage.removeItem(MOD_KEY); } catch (e) {}

  function modKaydet() { /* v2.1.7c: kalici mod yok, hep popup */ }

  // Her bolum icin runtime durumu: {popup, yerTutucu, btnAyir}
  const durum = {};

  /* IS53-SOZLUK-COZUM-V1
     OLCULEN KUSUR: bu islev sozlugu `SOZLUK[AKTIF_DIL]` adiyla
     ariyordu. Chromium olcumu: `typeof SOZLUK` -> "undefined",
     `typeof AKTIF_DIL` -> "undefined". Bu adlar sistemde HIC
     tanimli degil; gercek adlar i18n.js icinde `DILLER` ve
     `aktifDil`. `typeof` korumasi yuzunden hata ATILMIYOR,
     islev sessizce {} donduruyor ve cagiran taraftaki
     `|| t.pbaslik` yedegi ANAHTAR ADINI ekrana basiyordu
     (kullanici ekraninda "bpBaslikRotalar" / "bpBaslikKameralar").

     `DILLER` ve `aktifDil` en dis kapsamda const/let ile
     tanimli oldugu icin `window` uzerine YAZILMAZ (olculdu:
     window.DILLER === undefined). Bu yuzden once islev
     bildirimi olan `window.D` denenir (olculdu: function),
     sonra ortak kapsamdaki ciplak adlara dusulur. Her adim
     ayri korumali; hicbiri cokme uretmez. */
  function D() {
    try {
      if (typeof window.D === "function" && window.D !== D) {
        return window.D() || {};
      }
    } catch (e) {}
    try {
      if (typeof DILLER !== "undefined") {
        var dil = (typeof aktifDil !== "undefined") ? aktifDil : "TR";
        return DILLER[dil] || DILLER.TR || {};
      }
    } catch (e) {}
    return {};
  }

  // ------------------------------------------------------------------
  // Popup olusturma / kapama
  // ------------------------------------------------------------------
  function popupOlustur(ad) {
    const t = BOLUMLER[ad];
    const bas = document.getElementById(t.bas);
    const icer = document.getElementById(t.icer);
    if (!bas || !icer) return null;

    const pop = document.createElement("div");
    pop.className = "bolum-popup";
    pop.id = "bolumPopup_" + ad;

    // Baslik cubugu: bolum basligindaki ikon+metni kopyala
    const pBas = document.createElement("div");
    pBas.className = "popup-baslik bolum-popup-baslik";
    const kaynakBaslik = bas.querySelector(".tb-baslik") || bas;
    const span = document.createElement("span");
    span.className = "bolum-popup-ad";
    // FAZ18-IS35: pencere basligi ust bar etiketinden BAGIMSIZ yazilir.
    if (t.pbaslik) {
      const pm = document.createElement("span");
      pm.setAttribute("data-i18n", t.pbaslik);
      pm.textContent = D()[t.pbaslik] || t.pbaslik;
      span.appendChild(pm);
    } else {
    // Yalnizca ikon + metin kopyala (h2 kaynaginda ayir dugmesi de var, o gelmesin)
    const kIkon = kaynakBaslik.querySelector("i.fa-solid");
    const kMetin = kaynakBaslik.querySelector("span[data-i18n]");
    if (kIkon) span.appendChild(kIkon.cloneNode(true));
    if (kMetin) span.appendChild(kMetin.cloneNode(true));
    if (!kIkon && !kMetin) span.textContent = kaynakBaslik.textContent.trim();
    }
    pBas.appendChild(span);
    const bosluk = document.createElement("span");
    bosluk.style.flex = "1";
    pBas.appendChild(bosluk);
    // v2.1.7c: "Panele Yerlestir" kaldirildi (panel yok, hep popup)
    // Kapat dugmesi: bolumu tamamen gizler (menu toggle ile ayni etki)
    const btnKapat = document.createElement("button");
    btnKapat.className = "bolum-popup-btn";
    /* IS53-SOZLUK-COZUM-V1: ipucu metni `data-i18n-title` ile de
       isaretlenir; boylece dil degisince applyLanguage nitelik
       dongusu bunu da tazeler (olculdu: i18n.js icinde
       [data-i18n-title] dongusu var, bu dugme kapsam disiydi). */
    btnKapat.setAttribute("data-i18n-title", "bpKapat");
    btnKapat.title = D().bpKapat || "Kapat";
    btnKapat.innerHTML = "<i class='fa-solid fa-xmark'></i>";
    btnKapat.addEventListener("click", (e) => {
      e.stopPropagation();
      // Menudeki toggle ile ayni yoldan kapat (durum kaydi menubar'da)
      if (typeof window.bolumGorunumAyarla === "function") {
        window.bolumGorunumAyarla(ad, false);
      } else {
        pop.style.display = "none";
      }
    });
    pBas.appendChild(btnKapat);
    pop.appendChild(pBas);

    // Icerik kabi: toolbar (dugmeleriyle) + icerik TASINIR
    const govde = document.createElement("div");
    govde.className = "bolum-popup-govde";
    pop.appendChild(govde);

    document.body.appendChild(pop);

    // v2.1.7c: kayitli konum yoksa akilli varsayilan yerlesim -
    // sol bolumler ekranin soluna, sag bolumler sagina kaskad dizilir
    let kayitliVar = false;
    try {
      const k = JSON.parse(localStorage.getItem("gcs_pencere_konum") || "{}");
      kayitliVar = !!(k && k["bp_" + ad]);
    } catch (e) {}
    if (!kayitliVar) {
      const sira = Object.keys(BOLUMLER)
        .filter((x) => BOLUMLER[x].taraf === t.taraf).indexOf(ad);
      const y = 60 + sira * 46;
      pop.style.top = y + "px";
      if (t.taraf === "sol") {
        pop.style.left = (14 + sira * 26) + "px";
      } else {
        pop.style.left = "auto";
        pop.style.right = (14 + sira * 26) + "px";
      }
    }

    // Tasima + konum/boyut kalicilik
    if (typeof window.popupTasinabilirYap === "function") {
      window.popupTasinabilirYap(pop, pBas, "bp_" + ad);
    }
    if (typeof window.popupBoyutlandirilabilirYap === "function") {
      window.popupBoyutlandirilabilirYap(pop, "bp_" + ad);
    }
    return { pop, govde };
  }

  // Bolumu popup'a ayir
  function popupaAyir(ad, kaydet) {
    const t = BOLUMLER[ad];
    const bas = document.getElementById(t.bas);
    const icer = document.getElementById(t.icer);
    if (!bas || !icer) return;
    let d = durum[ad];
    if (d && d.popup) {
      d.popup.style.display = "";
      // v2.2.0: yeniden acilan bolum en uste gelir
      if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(d.popup);
      return;
    }

    // DOM'daki yerlerini yer tutucularla isaretle (geri donus icin)
    const yt1 = document.createComment("bp_" + ad + "_bas");
    const yt2 = document.createComment("bp_" + ad + "_icer");
    bas.parentNode.insertBefore(yt1, bas);
    icer.parentNode.insertBefore(yt2, icer);

    const o = popupOlustur(ad);
    if (!o) return;
    // Toolbar'i ve icerigi popup govdesine tasi (listener'lar korunur)
    o.govde.appendChild(bas);
    o.govde.appendChild(icer);
    // Panel gorunumunde gizlenmis olabilir (menu toggle) - popup'ta goster
    bas.style.display = "";
    icer.style.display = "";
    bas.classList.add("bolum-popup-icinde");
    // Islevsel dugmesi olmayan basliklar (or. takip h2) popup icinde tamamen gizli:
    // baslik metni zaten popup baslik cubugunda gosteriliyor (cift baslik onlemi)
    const islevselDugme = bas.querySelector(
      "button:not(.bolum-ayir-btn):not(.dk-menu-btn), .dk-menu-btn"
    );
    if (!islevselDugme) bas.classList.add("bp-bos-baslik");

    durum[ad] = { popup: o.pop, ytBas: yt1, ytIcer: yt2 };
    modlar[ad] = "popup";
    if (kaydet !== false) modKaydet();
    panelGorunurlukTazele();
  }

  // v2.1.7c: paneleTak kaldirildi - geri uyumluluk icin no-op
  function paneleTak(ad) { /* panel yok */ }

  // ------------------------------------------------------------------
  // Panel gorunurlugu: v2.1.7c'de sol/sag paneller her zaman gizli
  // (tum bolumler popup'ta yasar).
  // ------------------------------------------------------------------
  function panelGorunurlukTazele() {
    document.body.classList.add("sol-panel-gizli", "sag-panel-gizli");
    const solTut = document.getElementById("solTutamac");
    const sagTut = document.getElementById("sagTutamac");
    if (solTut) solTut.style.display = "none";
    if (sagTut) sagTut.style.display = "none";
    try { if (typeof viewer !== "undefined" && viewer) viewer.resize(); } catch (e) {}
  }

  // ------------------------------------------------------------------
  // Menu ac/kapa entegrasyonu: menubar.js panelUygula her calistiginda
  // cagirir. Bolum "acik" ve mod "popup" ise popup'i goster; "kapali"
  // ise popup'i gizle.
  // ------------------------------------------------------------------
  function bolumPopupUygula(gorunum) {
    for (const ad in BOLUMLER) {
      const acik = gorunum[ad] !== false;
      if (modlar[ad] === "popup") {
        if (acik) {
          if (!durum[ad]) popupaAyir(ad, false);
          else {
            durum[ad].popup.style.display = "";
            // v2.2.0: menuden acilan bolum en uste gelir
            if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(durum[ad].popup);
          }
          // menubar panelUygula bas/icer display'ini degistirmis olabilir;
          // popup icindeyken daima gorunur olmalilar
          const t = BOLUMLER[ad];
          const bas = document.getElementById(t.bas);
          const icer = document.getElementById(t.icer);
          if (bas) bas.style.display = "";
          if (icer) icer.style.display = "";
        } else if (durum[ad]) {
          durum[ad].popup.style.display = "none";
        }
      }
    }
    panelGorunurlukTazele();
  }

  // ------------------------------------------------------------------
  // Kurulum: tum acik bolumleri popup olarak olustur
  // ------------------------------------------------------------------
  function kur() {
    const gorunum = (typeof window.panelGorunumDurum === "function")
      ? window.panelGorunumDurum() : {};
    for (const ad in BOLUMLER) {
      if (gorunum[ad] !== false) popupaAyir(ad, false);
    }
    panelGorunurlukTazele();
  }

  // ------------------------------------------------------------------
  // TAM EKRAN MODU (v2.1.7c): bolumler zaten popup'ta; yalnizca
  // gosterge sinifi degisir (barlarin %80 yuzer stili CSS'te).
  // ------------------------------------------------------------------
  function tamEkranModu(acik) {
    document.body.classList.toggle("tam-ekran-modu", !!acik);
    panelGorunurlukTazele();
  }

  window.bolumPopupUygula = bolumPopupUygula;
  window.bolumPopupAyir = popupaAyir;
  window.bolumPaneleTak = paneleTak;
  window.bolumPanelGorunurlukTazele = panelGorunurlukTazele;
  window.bolumTamEkranModu = tamEkranModu;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", kur);
  } else {
    kur();
  }
})();
