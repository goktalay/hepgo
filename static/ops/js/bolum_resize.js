// ================================================================
// BOLUM RESIZE + PENCERE KONUM KALICILIGI
// - Sol panel: TESPIT / TAKIP bolumleri arasi dikey tutamac
// - Sag panel: DRONLAR / KAMERALAR / ROTALAR bolumleri arasi tutamaclar
// - Tum bolum boyutlari localStorage'da kalici (gcs_bolum_boyut)
// - Tasinabilir pencere konumlari icin ortak kayit sistemi
//   (gcs_pencere_konum): yuzen paneller, ayrik dron kartlari,
//   kamera pencereleri
// ================================================================
(function () {
  "use strict";

  // ----------------------------------------------------------------
  // 1) BOLUM RESIZE (dikey, ayni panel icindeki komsu bolumler)
  // ----------------------------------------------------------------
  const BOYUT_KEY = "gcs_bolum_boyut";

  function boyutlariOku() {
    try { return JSON.parse(localStorage.getItem(BOYUT_KEY) || "{}") || {}; }
    catch (e) { return {}; }
  }
  function boyutlariYaz(obj) {
    try { localStorage.setItem(BOYUT_KEY, JSON.stringify(obj)); } catch (e) {}
  }

  // Bolum tanimlari: her panel icin sirali bolum id listesi.
  // Tutamac, ardisik iki bolum ARASINA yerlestirilir; surukleme bu iki
  // bolumun flex-grow degerlerini degistirir (toplam sabit kalir).
  const PANELLER = [
    // v2.4.227: sol dock bolumleri kaldirildi
    // v2.4.33: dronlarIcerik KALDIRILDI (dron kartlari artik Baglanti
    // Yoneticisi grubunun icinde). Listede kalirsa ciftBul() olmayan
    // bir bolumu arar; zararsiz ama gereksiz.
    { bolumler: ["kameralarIcerik", "rotalarIcerik"] }
  ];

  function flexGrowAl(el) {
    const v = parseFloat(getComputedStyle(el).flexGrow);
    return isFinite(v) && v > 0 ? v : 1;
  }

  function kayitliBoyutlariUygula() {
    const kayit = boyutlariOku();
    PANELLER.forEach((p) => {
      p.bolumler.forEach((id) => {
        const el = document.getElementById(id);
        if (el && typeof kayit[id] === "number" && kayit[id] > 0.05) {
          el.style.flex = kayit[id] + " 1 0";
          el.style.minHeight = "0";
        }
      });
    });
  }

  // Bir bolum gercekten CIZILMIS mi? (kapali/gizli bolumler resize
  // hesabina KATILMAMALI)
  //
  // v2.4.25 ONEMLI: `offsetParent === null` testi BURADA CALISMAZ.
  // Olcum: bolum popup'lari `position: fixed`. Fixed bir ata
  // offsetParent zincirini kendisinde kestigi icin, popup KAPALI olsa
  // bile icindeki bolumun offsetParent degeri `<DIV bolum-popup>`
  // olarak doner (null degil). Bu yuzden eski test hep "gorunur"
  // diyordu ve tutamaclar hicbir zaman gizlenmiyordu.
  // Yerine gercek cizim testi: getClientRects().length.
  function gorunurBolum(el) {
    if (!el) return false;
    // Chromium'da en guvenilir test; yok ise geri donus yolu kullanilir
    if (typeof el.checkVisibility === "function") {
      if (!el.checkVisibility({ contentVisibilityAuto: true,
                                opacityProperty: true,
                                visibilityProperty: true })) return false;
    } else {
      const st = getComputedStyle(el);
      if (st.display === "none" || st.visibility === "hidden") return false;
    }
    // Hic cizilmemis eleman (kapali popup icinde) rect uretmez
    if (el.getClientRects().length === 0) return false;
    if (el.getBoundingClientRect().height < 8) return false;
    // Kapsayici popup varsa o da gercekten acik olmali
    const pp = el.closest(".bolum-popup");
    if (pp) {
      if (typeof pp.checkVisibility === "function" && !pp.checkVisibility())
        return false;
      if (pp.getClientRects().length === 0) return false;
    }
    return true;
  }

  // ---- v2.4.25: DINAMIK KOMSU BULMA ----
  // Olculen kusur: tutamac kurulum aninda sabit iki elemana kilitleniyordu
  // (`tutamacOlustur(ust, alt)`). Bolumler kapatilip acilabildigi icin, ara
  // bolum kapaliysa tutamac GORUNMEZ bir bolume flex atiyordu ve kullanici
  // "sadece alttaki panel boyutlaniyor" olarak goruyordu.
  // Cozum: cifti surukleme aninda, gorunur bolumler arasindan sec.
  // Iki bolum ancak AYNI GOVDE elemaninin cocuklariysa birbirini
  // boyutlandirabilir. v2.1.7c'de her bolum kendi ayri popup'ina
  // tasindi (olcum: hedefListeIcerik -> #bolumPopup_tespit,
  // takipListeIcerik -> #bolumPopup_takip). Ortak ebeveyni olmayan
  // iki bolume flex-grow atamak hicbir gorsel etki uretmez veya
  // yanlis pencereyi boyutlar -> kullanicinin "sadece alttaki panele
  // resize yapiyor" sikayeti.
  function ciftBul(tut, ustEl, altEl, bolumIdler) {
    const gov = tut.parentElement;
    if (!gov) return null;

    // Tutamacla AYNI govdede yasayan, cizilmis bolumleri DOM sirasinda al
    const ayniGovde = (bolumIdler || [])
      .map(id => document.getElementById(id))
      .filter(el => el && el.parentElement === gov && gorunurBolum(el))
      .sort((a, b) => a.getBoundingClientRect().top -
                      b.getBoundingClientRect().top);

    if (ayniGovde.length < 2) return null;   // paylasilacak gercek cift yok

    // Dogal cift hala ayni govdede ve cizilmisse onu koru
    if (ayniGovde.includes(ustEl) && ayniGovde.includes(altEl))
      return [ustEl, altEl];

    // Aksi halde tutamacin konumuna gore en yakin ust/alt ikiliyi sec
    const tutY = tut.getBoundingClientRect().top;
    let ust = null, alt = null;
    for (const el of ayniGovde) {
      const r = el.getBoundingClientRect();
      if (r.top + r.height / 2 <= tutY) ust = el;
      else if (!alt) alt = el;
    }
    if (!ust) { ust = ayniGovde[0]; alt = ayniGovde[1]; }
    else if (!alt) { alt = ayniGovde[ayniGovde.length - 1];
                     ust = ayniGovde[ayniGovde.length - 2]; }
    if (!ust || !alt || ust === alt) return null;
    return [ust, alt];
  }

  function tutamacOlustur(ustEl, altEl, bolumIdler) {
    const tut = document.createElement("div");
    tut.className = "bolum-tutamac";
    // v2.4.34: bu dosyada `T()` HIC TANIMLI DEGILDI. `typeof` korumasi
    // yuzunden hata firlatmiyor, sessizce Turkce yedege dusuyordu; bu
    // nedenle ipucu EN arayuzde de Turkce kaliyordu. Sozluge dogru
    // erisim `D()`; `bolumTutamacIpucu` anahtari TR/EN'de zaten mevcut.
    tut.title = ((typeof D === "function") ? D().bolumTutamacIpucu : "")
      || "S\u00fcr\u00fckleyerek b\u00f6l\u00fcm y\u00fcksekli\u011fini ayarlay\u0131n";
    const cizgi = document.createElement("div");
    cizgi.className = "bolum-tutamac-cizgi";
    tut.appendChild(cizgi);

    let surukle = null;
    tut.addEventListener("pointerdown", (e) => {
      // Cifti SURUKLEME ANINDA sec (gizli bolumler atlanir)
      const cift = ciftBul(tut, ustEl, altEl, bolumIdler);
      if (!cift) return;                 // boyutlandirilacak gorunur cift yok
      const [uEl, aEl] = cift;
      const rUst = uEl.getBoundingClientRect();
      const rAlt = aEl.getBoundingClientRect();
      surukle = {
        y0: e.clientY,
        ustEl: uEl,
        altEl: aEl,
        hUst: rUst.height,
        hAlt: rAlt.height,
        gUst: flexGrowAl(uEl),
        gAlt: flexGrowAl(aEl)
      };
      tut.setPointerCapture(e.pointerId);
      tut.classList.add("aktif");
      document.body.style.cursor = "row-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    tut.addEventListener("pointermove", (e) => {
      if (!surukle) return;
      const d = e.clientY - surukle.y0;
      const MIN = 60; // bolum minimum piksel yuksekligi
      let hUst = surukle.hUst + d;
      let hAlt = surukle.hAlt - d;
      if (hUst < MIN) { hAlt -= (MIN - hUst); hUst = MIN; }
      if (hAlt < MIN) { hUst -= (MIN - hAlt); hAlt = MIN; }
      if (hUst < MIN) return;
      // flex-grow oranlarini piksel oranindan hesapla:
      // toplam grow sabit kalir, iki bolum arasinda paylasilir
      const toplamGrow = surukle.gUst + surukle.gAlt;
      const toplamPx = surukle.hUst + surukle.hAlt;
      if (toplamPx <= 0) return;
      const gUst = toplamGrow * (hUst / toplamPx);
      const gAlt = toplamGrow - gUst;
      surukle.ustEl.style.flex = gUst.toFixed(4) + " 1 0";
      surukle.altEl.style.flex = gAlt.toFixed(4) + " 1 0";
      surukle.ustEl.style.minHeight = "0";
      surukle.altEl.style.minHeight = "0";
    });
    function birak(e) {
      if (!surukle) return;
      const uEl = surukle.ustEl, aEl = surukle.altEl;
      surukle = null;
      tut.classList.remove("aktif");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try { tut.releasePointerCapture(e.pointerId); } catch (err) {}
      // Kaydet (surukleme aninda secilen gercek cift)
      const kayit = boyutlariOku();
      if (uEl && aEl) {
        kayit[uEl.id] = flexGrowAl(uEl);
        kayit[aEl.id] = flexGrowAl(aEl);
        boyutlariYaz(kayit);
      }
    }
    tut.addEventListener("pointerup", birak);
    tut.addEventListener("pointercancel", birak);
    // Cift tiklama: varsayilana don (iki bolumu esitle)
    tut.addEventListener("dblclick", () => {
      // Tum bolumleri varsayilana dondur (gorunur olanlar esitlenir)
      (bolumIdler || []).forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.flex = "";
      });
      const kayit = boyutlariOku();
      (bolumIdler || []).forEach(id => { delete kayit[id]; });
      boyutlariYaz(kayit);
    });
    return tut;
  }

  // ---- v2.4.25: SAHIPSIZ TUTAMAC GIZLEME ----
  // Olculen kusur: v2.1.7c'de tum bolumler POPUP'a tasindi, ancak
  // bolum-tutamac elemanlari DOM'da kaldi. Olcum: 3 tutamac gorunur,
  // ikisi ayni y=473 konumunda ust uste. Bu tutamaclar hicbir gorunur
  // bolumu ayirmiyor; kullanici bunlari surukleyince ya hicbir sey
  // olmuyor ya da yanlis bolum boyutlaniyor ("sadece alttaki panel
  // boyutlaniyor" sikayeti).
  // Cozum: boyutlandirilacak gorunur komsu cifti yoksa tutamaci gizle.
  const _tutamaclar = [];

  function tutamacGorunurlukTazele() {
    _tutamaclar.forEach((kayit) => {
      const cift = ciftBul(kayit.tut, kayit.ust, kayit.alt, kayit.idler);
      // Cift yok -> tutamac islevsiz -> gizle
      kayit.tut.style.display = cift ? "" : "none";
    });
  }
  window.bolumTutamacTazele = tutamacGorunurlukTazele;

  function tutamaclariKur() {
    PANELLER.forEach((p) => {
      for (let i = 0; i < p.bolumler.length - 1; i++) {
        const ust = document.getElementById(p.bolumler[i]);
        const alt = document.getElementById(p.bolumler[i + 1]);
        if (!ust || !alt) continue;
        const tut = tutamacOlustur(ust, alt, p.bolumler);
        // Tutamaci ust bolumun hemen ardina yerlestir
        // (alt bolumun basligi/toolbari varsa onun ustunde durur)
        ust.parentNode.insertBefore(tut, ust.nextSibling);
        _tutamaclar.push({ tut, ust, alt, idler: p.bolumler });
      }
    });
    tutamacGorunurlukTazele();

    // Bolumler popup'a ayrilip geri takilabilir. MutationObserver
    // KULLANILMIYOR: harita/telemetri saniyede yuzlerce DOM guncellemesi
    // yapiyor, subtree gozlemi ucus sirasinda gereksiz yuk olur.
    // Yerine bolum popup API'sine hedefli kanca takilir.
    function kancaTak(adi) {
      const asil = window[adi];
      if (typeof asil !== "function" || asil._btzKanca) return;
      const sarmal = function () {
        const s = asil.apply(this, arguments);
        clearTimeout(window._btzZ);
        window._btzZ = setTimeout(tutamacGorunurlukTazele, 80);
        return s;
      };
      sarmal._btzKanca = true;
      window[adi] = sarmal;
    }
    const KANCA_ADLARI = ["bolumPopupUygula", "bolumPopupAyir",
                          "bolumGorunumAyarla", "bolumPaneleTak"];
    KANCA_ADLARI.forEach(kancaTak);
    // bolum_resize.js, bolum_popup.js/menubar.js'ten ONCE yuklenir
    // (index.html 1486 < 1489 < 1535). Kancalar DOMContentLoaded'da
    // takilir, o an hepsi tanimli olmali; ancak modul kurulum sirasi
    // garanti degil - gecikmeli olarak bir kez daha dene.
    setTimeout(() => KANCA_ADLARI.forEach(kancaTak), 400);
    setTimeout(() => { KANCA_ADLARI.forEach(kancaTak);
                       tutamacGorunurlukTazele(); }, 1500);

    window.addEventListener("resize", () => {
      clearTimeout(window._btzZ);
      window._btzZ = setTimeout(tutamacGorunurlukTazele, 150);
    });
  }

  // ----------------------------------------------------------------
  // 2) PENCERE KONUM KALICILIGI (ortak API)
  // ----------------------------------------------------------------
  const KONUM_KEY = "gcs_pencere_konum";

  function konumlariOku() {
    try { return JSON.parse(localStorage.getItem(KONUM_KEY) || "{}") || {}; }
    catch (e) { return {}; }
  }
  function konumlariYaz(obj) {
    try { localStorage.setItem(KONUM_KEY, JSON.stringify(obj)); } catch (e) {}
  }

  // Konumu kaydet: anahtar benzersiz pencere kimligi (or. "yz_yzSeri",
  // "dron_1", "kam_2"). Boyut da verilirse kaydedilir.
  window.pencereKonumKaydet = function (anahtar, el, boyutlu) {
    if (!anahtar || !el) return;
    const r = el.getBoundingClientRect();
    const kayit = konumlariOku();
    const k = { l: Math.round(r.left), t: Math.round(r.top) };
    if (boyutlu) { k.w = Math.round(r.width); k.h = Math.round(r.height); }
    kayit[anahtar] = k;
    konumlariYaz(kayit);
  };

  // Kayitli konumu uygula; uygulanirsa true doner.
  // Ekran disina tasan kayitlar gorunur alana cekilir.
  //
  // v2.4.52 - IKI KUSUR DUZELTILDI:
  //
  // 1) TRANSFORM CAKISMASI: bazi paneller CSS'te
  //      left:50%; top:50%; transform:translate(-50%,-50%)
  //    ile ortalanir (or. .i2-popup = Yer Kontrol Istasyonu Dual).
  //    Burada yalniz left/top yazilirsa transform YERINDE KALIR ve
  //    panel (left - genislik/2, top - yukseklik/2) noktasina kayar.
  //    720px genislikte bu 360px sola kayma demektir: kullanici
  //    paneli ekran disinda gorur, baslik cubugu solda kaldigi icin
  //    tutup geri cekemez, kapatma dugmesine de ulasamaz.
  //    Cozum: konum yazilirken transform mutlaka sifirlanir.
  //
  // 2) SOL SINIR -200 IDI: panelin baslik cubugu ekran disinda
  //    kalabiliyordu. Suruklenecek tek yer baslik cubugu oldugu icin
  //    kurtarma yolu kapaniyordu. Artik panelin en az TUTULABILIR
  //    kadari (varsayilan 120px) gorunur alanda kalir.
  window.pencereKonumUygula = function (anahtar, el, boyutlu) {
    if (!anahtar || !el) return false;
    const k = konumlariOku()[anahtar];
    if (!k || typeof k.l !== "number" || typeof k.t !== "number") return false;
    const maxL = Math.max(0, window.innerWidth - 80);
    const maxT = Math.max(0, window.innerHeight - 60);
    // v2.4.24: 48 sabiti kaldirildi. Ust bar alti sinir artik
    // popup_tasima.js icindeki tek kaynaktan (CSS degiskenleri +
    // gercek bar olcumu) okunur. Header incelince otomatik uyar.
    const minT = (typeof window.pencereMinTop === "function")
      ? window.pencereMinTop() : 48;
    // v2.4.52: transform'u sifirla — yoksa CSS ortalamasi ile
    // left/top toplanip panel ekran disina kayar.
    const cs = getComputedStyle(el);
    if (cs.transform && cs.transform !== "none") el.style.transform = "none";
    // v2.4.52: sol sinir. Panelin en az TUTULABILIR kadari iceride
    // kalmali; aksi halde baslik cubugu erisilemez olur.
    const TUTULABILIR = 120;
    const minL = Math.min(0, TUTULABILIR - (el.offsetWidth || 200));
    el.style.left = Math.min(Math.max(k.l, minL), maxL) + "px";
    el.style.top = Math.min(Math.max(k.t, minT), maxT) + "px";
    el.style.right = "auto";
    if (boyutlu && typeof k.w === "number" && k.w > 100) {
      el.style.width = k.w + "px";
      if (typeof k.h === "number" && k.h > 80) el.style.height = k.h + "px";
    }
    return true;
  };

  // v2.4.52 - EKRAN DISI KAYIT KURTARMA
  // Kayitli konum gorunur alanin TAMAMEN disindaysa (or. ekran
  // duzeni degisti, ikinci ekran cikarildi, ya da eski surumdeki
  // transform kusuru bozuk deger yazdi) kaydi YOK SAY ve paneli
  // CSS varsayilaninda (genelde ortada) birak.
  // Bu, kullanicinin localStorage'i elle temizlemesini gereksiz kilar.
  window.pencereKonumGecerliMi = function (anahtar, genislik, yukseklik) {
    const k = konumlariOku()[anahtar];
    if (!k || typeof k.l !== "number" || typeof k.t !== "number") return false;
    const g = genislik || 200, y = yukseklik || 120;
    const TUTULABILIR = 120;   // en az bu kadari iceride olmali
    const BASLIK = 40;         // baslik cubugu yuksekligi
    // Sag/alt kenardan tamamen cikmis mi?
    if (k.l > window.innerWidth - TUTULABILIR) return false;
    if (k.t > window.innerHeight - BASLIK) return false;
    // Sol/ust kenardan tutulamayacak kadar cikmis mi?
    if (k.l + g < TUTULABILIR) return false;
    if (k.t + y < BASLIK) return false;
    // Baslik cubugu ust barin altinda kaliyor mu?
    const minT = (typeof window.pencereMinTop === "function")
      ? window.pencereMinTop() : 48;
    if (k.t < minT - BASLIK) return false;
    return true;
  };

  window.pencereKonumSil = function (anahtar) {
    const kayit = konumlariOku();
    delete kayit[anahtar];
    konumlariYaz(kayit);
  };

  // ----------------------------------------------------------------
  // Kurulum
  // ----------------------------------------------------------------
  function kur() {
    kayitliBoyutlariUygula();
    tutamaclariKur();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", kur);
  } else {
    kur();
  }
})();
