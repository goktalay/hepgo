/* =====================================================================
   POPUP TASIMA (v2.1.3)
   Tum popup pencereleri basliklarindan fare VEYA parmakla (dokunmatik)
   suruklenerek tasinabilir yapar ve konumlarini localStorage'da hatirlar
   (bolum_resize.js: pencereKonumKaydet / pencereKonumUygula).

   Kullanim:
     window.popupTasinabilirYap(popupEl, baslikEl, "anahtar")
   - baslikEl verilmezse popup icindeki .popup-baslik / .dk-pp-baslik /
     .dk-mp-baslik otomatik bulunur.
   - anahtar verilirse konum kaydedilir ve acilista geri yuklenir.
   ===================================================================== */
(function () {
  "use strict";

  // ------------------------------------------------------------------
  // EN USTE GETIRME (v2.2.0)
  // Tum yonetilen pencereler (yuzen-panel, bolum-popup, tasinabilir
  // popup'lar) icin ortak z-index sayaci. Pencereye/basligina her
  // tiklandiginda ve pencere her acildiginda en uste gecer.
  // Sayac 1201-2450 araliginda tutulur (ust bar 2500'un altinda kalir);
  // tasarsa tum yonetilen pencereler siraya gore normalize edilir.
  // ------------------------------------------------------------------
  const Z_TABAN = 1201, Z_TAVAN = 2450;

  // ------------------------------------------------------------------
  // MINIMUM UST KONUM (v2.4.24 — TEK KAYNAK)
  // Onceden sabit 48 idi (42px bar + 6px pay elle hesaplanmisti) ve
  // ayni sayi bolum_resize.js icinde de kopyalanmisti. Header yuksekligi
  // degistiginde bu sabitler kopar ve pencereler yanlis hizada baslar.
  // Artik deger CSS degiskenlerinden (--ust-bar-y + --pencere-pay)
  // canli okunur; header'i CSS'ten inceltmek yeterlidir.
  // ------------------------------------------------------------------
  function pxOku(ad, varsayilan) {
    try {
      const d = getComputedStyle(document.documentElement)
        .getPropertyValue(ad).trim();
      const s = parseFloat(d);
      return isNaN(s) ? varsayilan : s;
    } catch (e) { return varsayilan; }
  }

  function minTopHesapla() {
    // Once gercek bar yuksekligini olc (en guvenilir kaynak)
    const bar = document.getElementById("ustBar");
    let barY = 0;
    if (bar) {
      const r = bar.getBoundingClientRect();
      if (r.height > 0) barY = r.height;
    }
    if (!barY) barY = pxOku("--ust-bar-y", 32);
    return Math.round(barY + pxOku("--pencere-pay", 6));
  }

  let _minTop = null;
  function MIN_TOP_AL() {
    if (_minTop === null) _minTop = minTopHesapla();
    return _minTop;
  }
  // Tema degisimi / yeniden boyutlandirma sonrasi yeniden olc
  window.addEventListener("resize", function () { _minTop = null; });
  // Diger moduller (bolum_resize.js) ayni degeri buradan okur
  window.pencereMinTop = MIN_TOP_AL;

  // Pencere ekranda MIN_TOP_AL() uzerindeyse asagi it (acilis/gorunur olma ani)
  function minTopUygula(pop) {
    if (!pop || !pop.isConnected) return;
    const r = pop.getBoundingClientRect();
    if (r.height === 0 && r.width === 0) return; // gizli
    if (r.top < MIN_TOP_AL()) {
      const cs = getComputedStyle(pop);
      if (cs.position !== "fixed" && cs.position !== "absolute") {
        pop.style.position = "fixed";
      }
      if (cs.transform && cs.transform !== "none") pop.style.transform = "none";
      if (cs.bottom !== "auto") pop.style.bottom = "auto";
      pop.style.left = r.left + "px";
      pop.style.top = MIN_TOP_AL() + "px";
      pop.style.margin = "0";
    }
  }
  window.pencereMinTopUygula = minTopUygula;
  let zSayac = Z_TABAN;
  const zPencereler = new Set();

  function zNormalize() {
    // Mevcut siralamayi koruyarak z degerlerini tabandan yeniden dagit
    const sirali = Array.from(zPencereler)
      .filter(p => p.isConnected)
      .sort((a, b) => (parseInt(a.style.zIndex) || 0) -
                      (parseInt(b.style.zIndex) || 0));
    zSayac = Z_TABAN;
    sirali.forEach(p => { p.style.zIndex = ++zSayac; });
  }

  function enUsteGetir(pop) {
    if (!pop) return;
    // v2.4.28 - KAPSAYICI ICINDEKI PANEL YUKSELTILMEZ
    //
    // Bir panel dok kapsayicisina (sekme/bolme) alindiginda kendi
    // z-index'i anlamsizdir; yigin sirasini KAPSAYICI belirler. Buna
    // ragmen enUsteKur ile bagli pointerdown isleyicisi calismaya devam
    // ediyor ve panele artan bir z-index yaziyordu. Olcum (v2.4.27,
    // tarayici): panel z=1213, kapsayici tutamaci z=5 ->
    // elementFromPoint(tutamac merkezi) panel icerigini donduruyor,
    // yani birlesmis pencere fare ile BOYUTLANDIRILAMIYOR.
    //
    // Dogru davranis: panel yerine kapsayiciyi one getirmek. Bu ayrica
    // iki birlesmis pencere arasinda gecisi de dogrular (tiklanan
    // kapsayici one gelir).
    const kapsayici = pop._dokKap || pop._dokBolme;
    if (kapsayici && kapsayici !== pop && kapsayici.isConnected) {
      enUsteGetir(kapsayici);
      return;
    }
    zPencereler.add(pop);
    const mevcut = parseInt(pop.style.zIndex) || 0;
    if (mevcut === zSayac && mevcut >= Z_TABAN) return; // zaten en ustte
    if (zSayac >= Z_TAVAN) zNormalize();
    pop.style.zIndex = ++zSayac;
  }

  // Pencerenin herhangi bir yerine basilinca en uste getir (capture:
  // ic dugme handler'larindan once calisir, davranislarini bozmaz)
  function enUsteKur(pop) {
    if (!pop || pop._enUsteKuruldu) return;
    pop._enUsteKuruldu = true;
    zPencereler.add(pop);
    pop.addEventListener("pointerdown", () => enUsteGetir(pop), true);
  }

  window.pencereEnUsteGetir = enUsteGetir;
  window.pencereEnUsteKur = enUsteKur;

  function tasinabilirYap(pop, bas, anahtar) {
    if (!pop) return;
    enUsteKur(pop); // v2.2.0: tasinabilir her pencere z-yonetimine girer
    // IS56: dok modulu kaldirildi; asagidaki liste artik TEK ve
    // BIRINCIL kaynaktir (onceden `pencere_dok.js` ayni listeyi
    // `window.PENCERE_BASLIK_SECICI` olarak saglıyordu; iki liste
    // kaldirma oncesi birebir ayni oldugu olculdu).
    // `window.PENCERE_BASLIK_SECICI` okumasi KORUNDU: baska bir
    // modul ileride bu degiskeni tanimlarsa oncelik onda kalir.
    bas = bas || pop.querySelector(
      window.PENCERE_BASLIK_SECICI ||
      ".popup-baslik, .yuzen-baslik, .dk-pp-baslik, .dk-mp-baslik, " +
      ".modal-baslik, .kam-oniz-baslik, .kam-pencere-baslik, " +
      ".vd-baslik, .sg-baslik");
    if (!bas || bas._tasimaKuruldu) return;
    bas._tasimaKuruldu = true;

    // Dokunmatikte tarayicinin scroll/pan yapmasini engelle: pointermove
    // olaylarinin gelmesi icin sart.
    bas.style.touchAction = "none";
    if (!bas.style.cursor) bas.style.cursor = "move";

    let surukle = null;

    bas.addEventListener("pointerdown", (ev) => {
      // Basliktaki dugmeler (kapat vb.) ve form elemanlari tasima baslatmaz
      if (ev.target.closest("button, input, select, textarea, a")) return;
      const r = pop.getBoundingClientRect();
      // transform ile ortalanan popup'larda (or. dk-param-popup) once
      // transform'u kaldirip gercek konumu left/top'a sabitle;
      // perde (overlay) icindeki kutular da fixed konuma gecirilir
      const cs = getComputedStyle(pop);
      if (cs.position !== "fixed" && cs.position !== "absolute") {
        pop.style.position = "fixed";
      }
      if (cs.transform && cs.transform !== "none") {
        pop.style.transform = "none";
      }
      if (cs.right !== "auto") pop.style.right = "auto";
      if (cs.bottom !== "auto") pop.style.bottom = "auto";
      pop.style.left = r.left + "px";
      pop.style.top = r.top + "px";
      pop.style.margin = "0";
      surukle = { dx: ev.clientX - r.left, dy: ev.clientY - r.top };
      try { bas.setPointerCapture(ev.pointerId); } catch (e) {}
      ev.preventDefault();
    });

    bas.addEventListener("pointermove", (ev) => {
      if (!surukle) return;
      let x = ev.clientX - surukle.dx;
      let y = ev.clientY - surukle.dy;
      x = Math.max(0, Math.min(x, window.innerWidth - Math.min(pop.offsetWidth, 120)));
      y = Math.max(MIN_TOP_AL(), Math.min(y, window.innerHeight - 36));
      pop.style.left = x + "px";
      pop.style.top = y + "px";
    });

    const birak = (ev) => {
      if (!surukle) return;
      surukle = null;
      try { bas.releasePointerCapture(ev.pointerId); } catch (e) {}
      // IS56: dok (ic ice gecme) kaldirildi. Pencere artik hicbir
      // kapsayiciya girmez; birakma noktasi ne olursa olsun konum
      // dogrudan kaydedilir.
      if (anahtar &&
          typeof window.pencereKonumKaydet === "function") {
        window.pencereKonumKaydet(anahtar, pop, true);
      }
    };
    bas.addEventListener("pointerup", birak);
    bas.addEventListener("pointercancel", birak);

    // Kayitli konumu uygula (varsa)
    if (anahtar && typeof window.pencereKonumUygula === "function") {
      // v2.4.213: kayitli w/h varsa HER popup'ta uygulanir (bayrak
      // tasinabilirYap'tan sonra kuruluyorsa boyut geri yuklenmiyordu).
      if (window.pencereKonumUygula(anahtar, pop, true)) {
        const cs2 = getComputedStyle(pop);
        if (cs2.position !== "fixed" && cs2.position !== "absolute") {
          pop.style.position = "fixed";
        }
        pop.style.transform = "none";
        pop.style.margin = "0";
        // v2.3.3: eski kayitli konum ust bara denk gelebilir — asagi it
        const t = parseFloat(pop.style.top);
        if (!isNaN(t) && t < MIN_TOP_AL()) pop.style.top = MIN_TOP_AL() + "px";
      }
    }
  }

  // ------------------------------------------------------------------
  // POPUP BOYUTLANDIRMA (v2.1.7)
  // Sag-alt koseye tutamac ekler; fare VEYA parmakla surukleyerek
  // popup boyutlandirilir. Boyut, konumla ayni anahtar altinda
  // (gcs_pencere_konum) kaydedilir ve acilista geri yuklenir.
  // Onay popup'lari (onayPerde) HARIC tutulur.
  // ------------------------------------------------------------------
  function boyutlandirilabilirYap(pop, anahtar) {
    if (!pop || pop._boyutKuruldu) return;
    pop._boyutKuruldu = true;
    pop._boyutluKayit = true; // tasima kaydi da w/h ile yapilsin
    // Panel ailesi daha buyuk bir asgari alan isteyebilir. Kucuk
    // viewport'ta her zaman gorunur alan tercih edilir; pencere tasmaz.
    const tercih = pop._popupMinBoyut || {};
    const minBoyut = () => ({
      w: Math.min(Number(tercih.genislik) || 400,
                  Math.max(0, window.innerWidth - 10)),
      h: Math.min(Number(tercih.yukseklik) || 300,
                  Math.max(0, window.innerHeight - 10))
    });

    const tut = document.createElement("div");
    tut.className = "popup-boyut-tutamac";
    tut.title = "";
    // Tutamac absolute konumlanir; popup relative/fixed/absolute olmali
    const cs = getComputedStyle(pop);
    if (cs.position === "static") pop.style.position = "relative";
    pop.appendChild(tut);

    let boy = null;

    tut.addEventListener("pointerdown", (ev) => {
      const r = pop.getBoundingClientRect();
      // max-height/max-width kisitlarini kaldir; left/top sabitle ki
      // boyut degisince pencere yerinden oynamasin
      const csx = getComputedStyle(pop);
      if (csx.position !== "fixed" && csx.position !== "absolute") {
        pop.style.position = "fixed";
      }
      if (csx.transform && csx.transform !== "none") pop.style.transform = "none";
      pop.style.left = r.left + "px";
      pop.style.top = r.top + "px";
      pop.style.right = "auto";
      pop.style.bottom = "auto";
      pop.style.margin = "0";
      pop.style.maxWidth = "none";
      pop.style.maxHeight = "none";
      boy = { x: ev.clientX, y: ev.clientY, w: r.width, h: r.height };
      try { tut.setPointerCapture(ev.pointerId); } catch (e) {}
      ev.preventDefault();
      ev.stopPropagation();
    });

    tut.addEventListener("pointermove", (ev) => {
      if (!boy) return;
      let w = boy.w + (ev.clientX - boy.x);
      let h = boy.h + (ev.clientY - boy.y);
      /* IS51-RESIZE-ALT-SINIR: varsayilan 400x300; kalibrasyon gibi
         ayrik aileler kendi _popupMinBoyut degerini tanimlayabilir. */
      const alt = minBoyut();
      w = Math.max(alt.w, Math.min(w, window.innerWidth - 10));
      h = Math.max(alt.h, Math.min(h, window.innerHeight - 10));
      pop.style.width = w + "px";
      pop.style.height = h + "px";
    });

    const birakB = (ev) => {
      if (!boy) return;
      boy = null;
      try { tut.releasePointerCapture(ev.pointerId); } catch (e) {}
      if (anahtar && typeof window.pencereKonumKaydet === "function") {
        window.pencereKonumKaydet(anahtar, pop, true);
      }
    };
    tut.addEventListener("pointerup", birakB);
    tut.addEventListener("pointercancel", birakB);

    // Kayitli boyutu uygula (varsa)
    if (anahtar && typeof window.pencereKonumUygula === "function") {
      const k = (function () {
        try {
          return (JSON.parse(localStorage.getItem("gcs_pencere_konum") || "{}") || {})[anahtar];
        } catch (e) { return null; }
      })();
      if (k && typeof k.w === "number" && k.w > 100) {
        const alt = minBoyut();
        const w = Math.max(alt.w, Math.min(k.w, window.innerWidth - 10));
        pop.style.width = w + "px";
        if (typeof k.h === "number" && k.h > 80) {
          const h = Math.max(alt.h, Math.min(k.h, window.innerHeight - 10));
          pop.style.height = h + "px";
          pop.style.maxHeight = "none";
        }
        pop.style.maxWidth = "none";
      }
    }
  }

  window.popupBoyutlandirilabilirYap = boyutlandirilabilirYap;

  // Kayitli konumu popup her acilista yeniden uygulamak icin yardimci:
  // (statik popup'lar acilirken class degisir; konum stilde kalicidir,
  //  bu yuzden ek is gerekmez. Dinamik popup'lar icin acilista cagrilir.)
  window.popupTasinabilirYap = tasinabilirYap;

  // ------------------------------------------------------------------
  // STATIK POPUP'LAR (index.html'de tanimli): otomatik kurulum
  // Perde (overlay) modallarinda tasinan eleman icteki kutudur.
  // ------------------------------------------------------------------
  function statikKur() {
    // Dogrudan pencere olan popup'lar
    [
      "arayuzPopup", "haritaPopup", "lokasyonPopup",
      "gorevIzlemePopup", "kullaniciPopup", "yeniKulPopup",
      "aiSunucuPopup", "aiKisiPopup", "aiAracPopup",
      "aiKayitsizPopup", "aiGecmisPopup",
    ].forEach((id) => {
      const pop = document.getElementById(id);
      if (pop) {
        boyutlandirilabilirYap(pop, "pp_" + id);
        tasinabilirYap(pop, null, "pp_" + id);
      }
    });

    // Yuzen paneller (yzRadar, yzSeri, yzHakkinda vb.): tasima kendi
    // modulunde (arayuz.js) kurulu; burada yalniz resize eklenir.
    document.querySelectorAll(".yuzen-panel").forEach((pop) => {
      if (pop.id) boyutlandirilabilirYap(pop, "yz_" + pop.id);
    });

    // rotaNoktaPopup: tiklanan noktada acilir (dogru davranis) —
    // tasinabilir olsun ama konum HATIRLAMASIN.
    const rnp = document.getElementById("rotaNoktaPopup");
    if (rnp) tasinabilirYap(rnp, null, null);

    // Perde (overlay) modallari: icteki ilk kutu tasinir. Konum
    // hatirlama perdeli modallarda da uygulanir; kutu absolute konuma
    // gecirilir ki flex-ortalamadan bagimsiz dursun.
    [
      "bagEklePerde", "lokKaydetPerde", "rotaModalPerde",
      "kamModalPerde", "rotaDetayPerde", "gorevRotaPerde",
      "rotaParamPerde",           // v2.4.23: rota parametre duzenleme
    ].forEach((id) => {
      const perde = document.getElementById(id);
      if (!perde) return;
      const kutu = perde.firstElementChild;
      if (!kutu) return;
      const bas = kutu.querySelector(".popup-baslik, .modal-baslik");
      if (!bas || bas._tasimaKuruldu) return;
      // Kutu ilk aciliste perde ortalamasiyla acilir; surukleme
      // baslayinca veya kayitli konum varsa fixed konuma gecer.
      boyutlandirilabilirYap(kutu, "pp_" + id);
      tasinabilirYap(kutu, bas, "pp_" + id);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", statikKur);
  } else {
    statikKur();
  }

  // ------------------------------------------------------------------
  // EVRENSEL PENCERE YONETIMI (v2.3.1)
  // Tum popup turleri tek sistemde: hangi modulden acilirsa acilsin
  // (statik id'li, dinamik olusturulan, perde iceren) her pencere
  // z-yonetimine baglanir; ACILDIGI anda en uste gecer, tiklaninca
  // aktiflesir. MutationObserver ile yeni eklenen / gorunur olan
  // pencereler otomatik yakalanir - modul modul kancalamaya gerek yok.
  // ------------------------------------------------------------------
  const PENCERE_SECICI = [
    ".yuzen-panel", ".bolum-popup", ".dron-kart.ayrik",
    ".dk-mini-popup", ".dk-param-popup", ".dk-pencere",
    ".kam-pencere", ".gecmis-popup", ".sg-popup", ".ph-popup",
    ".ph-onizleme", ".um-popup", ".ry-popup", ".angi-popup",
    "#arayuzPopup", "#haritaPopup", "#lokasyonPopup",
    "#kullaniciPopup", "#yeniKulPopup", "#gorevIzlemePopup",
    "#rotaNoktaPopup", "#haritaAramaPopup", "#haritaMenu", "#profilMenu",
    "#aiSunucuPopup", "#aiKisiPopup", "#aiAracPopup",
    "#aiKayitsizPopup", "#aiGecmisPopup",
  ].join(", ");

  // v2.4.24: dok modulu ayni pencere evrenini kullanir (tek kaynak)
  window.PENCERE_SECICI = PENCERE_SECICI;

  function gorunurMu(el) {
    if (!el.isConnected) return false;
    const cs = getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden";
  }

  function pencereyiYonet(el) {
    enUsteKur(el);              // tiklaninca en uste
    const g = gorunurMu(el);
    el._sonGorunur = g;         // gorunurluk gecis takibi (dongu kirici)
    if (g) { enUsteGetir(el); minTopUygula(el); } // acilinca en uste + bar alti
  }

  function hepsiniTara(kok) {
    if (kok.nodeType !== 1) return;
    if (kok.matches && kok.matches(PENCERE_SECICI)) pencereyiYonet(kok);
    if (kok.querySelectorAll) {
      kok.querySelectorAll(PENCERE_SECICI).forEach(pencereyiYonet);
    }
  }

  function gozlemciKur() {
    hepsiniTara(document.body);
    const obs = new MutationObserver((kayitlar) => {
      for (const k of kayitlar) {
        if (k.type === "childList") {
          k.addedNodes.forEach((n) => hepsiniTara(n));
        } else if (k.type === "attributes") {
          const el = k.target;
          if (el.nodeType === 1 && el.matches &&
              el.matches(PENCERE_SECICI)) {
            // Yalnizca GIZLI -> GORUNUR gecisinde en uste getir.
            // (enUsteGetir zIndex yazar -> yeni attribute mutation
            // tetiklenir; gecis takibi olmadan sonsuz dongu olusur.)
            const g = gorunurMu(el);
            if (g && el._sonGorunur !== true) {
              enUsteKur(el);
              enUsteGetir(el);
              minTopUygula(el); // v2.3.3: acilan pencere ust bara girmesin
            }
            el._sonGorunur = g;
          }
        }
      }
    });
    obs.observe(document.body, {
      childList: true, subtree: true,
      attributes: true, attributeFilter: ["style", "class"],
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", gozlemciKur);
  } else {
    gozlemciKur();
  }
})();
