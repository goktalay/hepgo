// =================================================================
// GOKTUNGU v2.5.0 - DRON BAKIM ARAYUZU
// -----------------------------------------------------------------
// Bu dosya dron paneline eklenen bakim yeteneklerini tasir:
//   1. Motor testi penceresi
//   2. Ilk ayar (Initial Tune) penceresi
//   3. Reboot islemi
//   4. Kalibrasyon SECIM izgarasi + YEDI ayri kalibrasyon penceresi
//      (her biri canli mesaj akisi ve gorsel anlatim tasir)
//
// Yakinlik algilayicisi ayri dosyada: js/dron_yakinlik.js
//
// SOZLESMELER (olculdu, OLCUM_faz11_arayuz.md):
//   - Pencere kurulumu: dkPopupTekil / dkMiniPopupBaslikKur /
//     dkPopupOneGetirKur / dkMiniPopupKonumla
//   - Motor testi istegi: test tipi alani "tip_no" (WS mesaj tipi "tip"
//     icin ayrilmis)
//   - kalib_mesajlari istegi -> "kalib_mesaj_listesi" yaniti
//   - ilk_ayar_ongoru istegi -> "ilk_ayar_ongorusu" yaniti
//   - Sabit renk YASAK: yalniz CSS degiskenleri
//   - ws.js bu dosyadan SONRA yuklenir; window.*Isle isleyicileri
//     burada tanimlanir
// =================================================================
(function () {
  "use strict";

  // ---------------------------------------------------------------
  // ORTAK YARDIMCILAR
  // ---------------------------------------------------------------
  function sozluk() {
    return (typeof D === "function") ? D() : {};
  }
  function wsGonder(nesne) {
    if (typeof ws !== "undefined" && ws && ws.readyState === 1) {
      ws.send(JSON.stringify(nesne));
      return true;
    }
    return false;
  }
  // Dronun son telemetri paketi (arm durumu vb. icin)
  function dronVeri(sysid) {
    if (typeof sonVeri !== "undefined" && sonVeri) return sonVeri[sysid] || null;
    return null;
  }
  function armliMi(sysid) {
    const d = dronVeri(sysid);
    return !!(d && d.armed);
  }
  // Pencere iskeleti: baslik + govde dondurur.
  // Kalibrasyonlar farkli pencerelerdir ancak ayni konum/boyut sozlesmesini
  // kullanir: ekran ortasinda, erisilebilir boyutta acilir; kullanicinin
  // tasima ve resize tercihi kalibrasyon turu + dron icin kalici saklanir.
  function pencere(kimlik, baslikYazi, ikon, fare, ekSinif) {
    if (dkPopupTekil(kimlik)) return null;
    const pop = document.createElement("div");
    pop.id = kimlik;
    pop.className = "dk-mini-popup " + (ekSinif || "");
    const kalibrasyonMu = /(^|\\s)db-kalib(?:-|\\s|$)/.test(String(ekSinif || ""));
    const konumAnahtar = kalibrasyonMu ? "pp_kalib_" + kimlik : null;
    if (kalibrasyonMu) {
      // Kucuk ekranlarda viewport'u asmayacak sekilde resize alt siniri.
      pop._popupMinBoyut = { genislik: 500, yukseklik: 400 };
    }
    // Ortak X dugmesi bu kancayi cagirir; akisi olan pencerelerde timer
    // DOM denetimini beklemeden aninda temizlenir.
    pop.kapat = () => kalibPencereKapat(kimlik, pop);
    dkMiniPopupBaslikKur(pop, baslikYazi, konumAnahtar, ikon);
    const govde = document.createElement("div");
    govde.className = "db-govde";
    pop.appendChild(govde);
    pop.style.position = "fixed";
    dkPopupOneGetirKur(pop);
    document.body.appendChild(pop);
    // Kalibrasyonlar fare konumunda kenara sikismak yerine merkezde acilir.
    dkMiniPopupKonumla(pop, kalibrasyonMu ? null : fare);
    return { pop: pop, govde: govde, kapat: pop.kapat };
  }
  // Etiketli sayi girisi
  function sayiGirisi(kap, etiket, deger, min, max, adim, ipucu) {
    const sar = document.createElement("label");
    sar.className = "db-alan";
    const et = document.createElement("span");
    et.className = "db-alan-et";
    et.textContent = etiket;
    const gir = document.createElement("input");
    gir.type = "number";
    gir.className = "db-alan-gir";
    gir.value = String(deger);
    if (min !== undefined) gir.min = String(min);
    if (max !== undefined) gir.max = String(max);
    if (adim !== undefined) gir.step = String(adim);
    sar.appendChild(et);
    sar.appendChild(gir);
    if (ipucu) {
      const ip = document.createElement("span");
      ip.className = "db-alan-ipucu";
      ip.textContent = ipucu;
      sar.appendChild(ip);
    }
    kap.appendChild(sar);
    return gir;
  }
  function dugmeKur(kap, yazi, ikon, tur, cb) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "db-btn" + (tur ? " " + tur : "");
    // FAZ18-IS27-ONARIM: metin <span> icine alinir (dugme birligi
    // sozlesmesi). Ikon KOSULLU oldugu icin ikonsuz durumda
    // dugme yalniz-metin olur ve yalniz-ikon kuralindan
    // etkilenmez; span sarmasi o durumda da zararsizdir.
    b.innerHTML = (ikon ? "<i class='fa-solid " + ikon + "'></i> " : "")
                  + "<span>" + yazi + "</span>";
    b.addEventListener("click", cb);
    kap.appendChild(b);
    return b;
  }
  // Kirmizi uyari seridi
  function uyariSeridi(kap, metin) {
    const u = document.createElement("div");
    u.className = "db-uyari";
    u.innerHTML = "<i class='fa-solid fa-triangle-exclamation'></i> <span></span>";
    u.querySelector("span").textContent = metin;
    kap.appendChild(u);
    return u;
  }
  function notSeridi(kap, metin) {
    const n = document.createElement("div");
    n.className = "db-not";
    n.innerHTML = "<i class='fa-solid fa-circle-info'></i> <span></span>";
    n.querySelector("span").textContent = metin;
    kap.appendChild(n);
    return n;
  }

  // ===============================================================
  // 1. CANLI MESAJ AKISI (tum kalibrasyon pencerelerinde ortak)
  // ---------------------------------------------------------------
  // Arka uc `kalib_mesajlari` ucu oturum baslangicindan SONRAKI
  // STATUSTEXT satirlarini dondurur. Pencere acik oldugu surece
  // 700 ms'de bir cekilir.
  //
  // NEDEN AYRI BILESEN: kullanici "tum kalibrasyon mesajlarini ve
  // degerlerini gostersin" dedi. Mevcut sistemde bu mesajlar yalniz
  // genel konsola gidiyordu ve kalibrasyon yapan operator onlari
  // pencereden ayrilmadan goremiyordu.
  // ===============================================================
  const kalibAkislar = {};   // kimlik -> {sysid, liste, timer, pop}

  function kalibPencereKapat(kimlik, pop) {
    if (pop && pop._kalibKapatiliyor) return;
    if (pop) pop._kalibKapatiliyor = true;
    const akis = kalibAkislar[kimlik];
    if (akis) {
      clearInterval(akis.timer);
      delete kalibAkislar[kimlik];
    }
    // Kalibrasyona ozel canli gorsel/zamanlayici varsa, DOM kaldirilmadan
    // once derhal temizlenir. X, Escape ve alt Kapat ayni yolu kullanir.
    try {
      if (pop && typeof pop._kalibTemizle === "function") pop._kalibTemizle();
    } catch (e) {}
    if (pop && pop.isConnected) pop.remove();
  }

  function mesajAkisiKur(kap, sysid, kimlik) {
    const t = sozluk();
    const bas = document.createElement("div");
    bas.className = "db-akis-bas";
    bas.textContent = t.dbMesajAkisi || "MESAJ AKI\u015eI";
    kap.appendChild(bas);
    const liste = document.createElement("div");
    liste.className = "db-akis";
    liste.innerHTML = "<div class='db-akis-bos'>" +
      (t.dbAkisBekleniyor || "Kalibrasyon ba\u015flat\u0131ld\u0131\u011f\u0131nda " +
       "arac\u0131n g\u00f6nderdi\u011fi mesajlar burada g\u00f6r\u00fcn\u00fcr.") +
      "</div>";
    kap.appendChild(liste);
    const kayit = { sysid: sysid, liste: liste, timer: null };
    kalibAkislar[kimlik] = kayit;
    kayit.timer = setInterval(() => {
      if (!liste.isConnected) {
        clearInterval(kayit.timer);
        delete kalibAkislar[kimlik];
        return;
      }
      wsGonder({ tip: "kalib_mesajlari", sysid: Number(sysid) });
    }, 700);
    // Ilk istek hemen
    wsGonder({ tip: "kalib_mesajlari", sysid: Number(sysid) });
    return liste;
  }

  // Mesaj listesini ciz. sev: MAVLink severity (0-7); 0-3 kritik.
  function akisCiz(liste, mesajlar) {
    const t = sozluk();
    if (!mesajlar || !mesajlar.length) {
      liste.innerHTML = "<div class='db-akis-bos'>" +
        (t.dbAkisBos || "Hen\u00fcz mesaj yok.") + "</div>";
      return;
    }
    liste.textContent = "";
    for (const m of mesajlar) {
      const sat = document.createElement("div");
      const sev = Number(m.sev);
      let sinif = "db-akis-sat";
      if (sev <= 3) sinif += " kritik";
      else if (sev === 4) sinif += " uyari";
      else sinif += " bilgi";
      sat.className = sinif;
      const saat = document.createElement("span");
      saat.className = "db-akis-saat";
      try {
        saat.textContent = new Date(Number(m.ts) * 1000)
          .toLocaleTimeString("tr-TR", { hour12: false });
      } catch (e) { saat.textContent = ""; }
      const metin = document.createElement("span");
      metin.className = "db-akis-metin";
      metin.textContent = String(m.metin || "");
      sat.appendChild(saat);
      sat.appendChild(metin);
      if (Number(m.tekrar) > 1) {
        const tk = document.createElement("span");
        tk.className = "db-akis-tekrar";
        tk.textContent = "x" + m.tekrar;
        sat.appendChild(tk);
      }
      liste.appendChild(sat);
    }
  }

  // ws.js -> bu isleyici
  window.kalibMesajListesiIsle = function (m) {
    const sysid = Number(m.sysid);
    for (const kimlik of Object.keys(kalibAkislar)) {
      const k = kalibAkislar[kimlik];
      if (k.sysid !== sysid) continue;
      if (!k.liste.isConnected) {
        clearInterval(k.timer);
        delete kalibAkislar[kimlik];
        continue;
      }
      akisCiz(k.liste, m.mesajlar);
    }
  };

  // ===============================================================
  // 2. KALIBRASYON SECIM IZGARASI
  // ---------------------------------------------------------------
  // Eski dkKalibPopupAc tek pencerede alti karti alt alta diziyordu.
  // Kullanici her kalibrasyonun AYRI pencerede, mesaj ve degerleriyle,
  // gorsel anlatimla acilmasini istedi. Bu izgara yalniz secim yapar.
  // ===============================================================
  function kalibSecimAc(fare, sysid) {
    const t = sozluk();
    const p = pencere("dbKalibSecim_" + sysid,
      (t.kalibBaslik || "KAL\u0130BRASYON") + " \u2014 D" + sysid,
      "fa-screwdriver-wrench", fare, "db-kalib-secim");
    if (!p) return;
    const izgara = document.createElement("div");
    izgara.className = "db-secim-izgara";
    p.govde.appendChild(izgara);

    const kat = (typeof fsAracKategori === "function")
      ? fsAracKategori(sysid) : "copter";

    function hucre(ikon, metin, cb, tehlikeli) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "db-secim-hucre" + (tehlikeli ? " tehlikeli" : "");
      el.innerHTML = "<i class='fa-solid " + ikon + " db-secim-ikon'></i>" +
        "<span class='db-secim-metin'></span>";
      el.querySelector(".db-secim-metin").textContent = metin;
      el.title = metin;
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const fk = { x: ev.clientX, y: ev.clientY };
        p.kapat();
        cb(fk);
      });
      izgara.appendChild(el);
    }

    hucre("fa-rotate", t.kalibGyro || "Jiroskop",
      (fk) => kalibGyroAc(fk, sysid));
    hucre("fa-gauge", t.kalibBaro || "Barometre",
      (fk) => kalibBaroAc(fk, sysid));
    hucre("fa-cube", t.kalibIvme || "\u0130vme\u00f6l\u00e7er",
      (fk) => kalibIvmeAc(fk, sysid));
    hucre("fa-ruler-horizontal", t.kalibLevel || "Seviye",
      (fk) => kalibLevelAc(fk, sysid));
    hucre("fa-compass", t.kalibPusula || "Pusula",
      (fk) => kalibPusulaAc(fk, sysid));
    hucre("fa-gamepad", t.kalibRadyo || "Radyo (RC)",
      (fk) => kalibRadyoAc(fk, sysid));
    // ESC yalniz kopter/heli (sabit kanatta anlamsiz)
    if (kat !== "plane") {
      hucre("fa-bolt", t.kalibEsc || "ESC",
        (fk) => kalibEscAc(fk, sysid), true);
    }
    notSeridi(p.govde, t.dbKalibSecimNot ||
      "Her kalibrasyon kendi penceresinde a\u00e7\u0131l\u0131r; " +
      "arac\u0131n g\u00f6nderdi\u011fi t\u00fcm mesajlar orada g\u00f6r\u00fcn\u00fcr.");
  }

  // ---------------------------------------------------------------
  // ORTAK KALIBRASYON PENCERESI ISKELETI
  // ---------------------------------------------------------------
  // gorselCiz(kap) -> gorsel anlatim bileseni (istege bagli)
  // dugmeler: [{yazi, ikon, tur, onay, aksiyon}]
  function kalibPencere(fare, sysid, ayar) {
    const t = sozluk();
    const kimlik = "dbKalib_" + ayar.anahtar + "_" + sysid;
    const p = pencere(kimlik, ayar.baslik + " \u2014 D" + sysid,
      ayar.ikon, fare, "db-kalib-pencere");
    if (!p) return null;

    if (ayar.uyari) uyariSeridi(p.govde, ayar.uyari);

    const acik = document.createElement("div");
    acik.className = "db-kalib-acik";
    acik.textContent = ayar.aciklama;
    p.govde.appendChild(acik);

    if (typeof ayar.gorselCiz === "function") {
      const gk = document.createElement("div");
      gk.className = "db-gorsel";
      p.govde.appendChild(gk);
      ayar.gorselCiz(gk, sysid, p);
    }

    const btnKutu = document.createElement("div");
    btnKutu.className = "db-btnler";
    p.govde.appendChild(btnKutu);
    for (const d of (ayar.dugmeler || [])) {
      dugmeKur(btnKutu, d.yazi, d.ikon, d.tur, () => {
        // `gonder` verilmisse ozel gonderim (or. ivme yon onayi ayri
        // WS ucu kullanir; komut_gonder imzasi yon kodu tasimiyor).
        const isle = (typeof d.gonder === "function")
          ? () => d.gonder(sysid)
          : () => wsGonder({ tip: "dron_komut", sysid: Number(sysid),
                             aksiyon: d.aksiyon });
        if (d.onay) onayIste(d.onay, isle); else isle();
      });
    }

    // Basliktaki X'e ek olarak, uzun mesaj akisinda erisilebilir kalan
    // ikincil kapatma yolu. Escape de ayni temiz kapatma yolunu kullanir.
    dugmeKur(btnKutu, t.kapat || "Kapat", "fa-xmark", "", () => p.kapat());
    p.pop.tabIndex = -1;
    p.pop.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        p.kapat();
      }
    });
    p.pop.focus({ preventScroll: true });

    mesajAkisiKur(p.govde, sysid, kimlik);
    return p;
  }

  // ---------------------------------------------------------------
  // 2a. JIROSKOP
  // ---------------------------------------------------------------
  function kalibGyroAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "gyro", ikon: "fa-rotate",
      baslik: t.kalibGyro || "Jiroskop",
      aciklama: t.kalibGyroAcik ||
        "Dron sabit ve hareketsizken yap\u0131l\u0131r. Birka\u00e7 saniye s\u00fcrer.",
      gorselCiz: gorselSabitArac,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibGyroOnay ||
          "Gyro kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? Dron sabit durmal\u0131.",
        aksiyon: "kalib_gyro"
      }]
    });
  }
  // Gorsel: sabit duran arac + titresim yok isareti
  function gorselSabitArac(kap) {
    const t = sozluk();
    kap.innerHTML =
      "<div class='db-sema db-sema-sabit'>" +
      "  <div class='db-sema-zemin'></div>" +
      "  <div class='db-sema-arac'>" +
      "    <div class='db-sema-govde'></div>" +
      "    <div class='db-sema-kol k1'></div><div class='db-sema-kol k2'></div>" +
      "    <div class='db-sema-kol k3'></div><div class='db-sema-kol k4'></div>" +
      "  </div>" +
      "  <div class='db-sema-etiket'></div>" +
      "</div>";
    kap.querySelector(".db-sema-etiket").textContent =
      t.dbSemaSabit || "Ara\u00e7 d\u00fcz zeminde, tamamen hareketsiz";
  }

  // ---------------------------------------------------------------
  // 2b. BAROMETRE
  // ---------------------------------------------------------------
  function kalibBaroAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "baro", ikon: "fa-gauge",
      baslik: t.kalibBaro || "Barometre",
      aciklama: t.kalibBaroAcik ||
        "Yer bas\u0131nc\u0131n\u0131 s\u0131f\u0131rlar. Dron yerdeyken yap\u0131l\u0131r.",
      gorselCiz: gorselBaro,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibBaroOnay ||
          "Barometre kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131?",
        aksiyon: "kalib_baro"
      }]
    });
  }
  // Gorsel: yer basinci sifirlama + canli yukseklik okumasi
  function gorselBaro(kap, sysid, pencereBilgi) {
    const t = sozluk();
    kap.innerHTML =
      "<div class='db-sema db-sema-baro'>" +
      "  <div class='db-sema-zemin'></div>" +
      "  <div class='db-sema-arac'><div class='db-sema-govde'></div></div>" +
      "  <div class='db-sema-ok'><i class='fa-solid fa-arrows-down-to-line'></i></div>" +
      "  <div class='db-olcum'><span class='db-olcum-et'></span>" +
      "    <span class='db-olcum-deg' data-alt>—</span></div>" +
      "</div>";
    kap.querySelector(".db-olcum-et").textContent =
      t.dbBaroYuk || "\u00d6l\u00e7\u00fclen y\u00fckseklik";
    const alan = kap.querySelector("[data-alt]");
    const timer = setInterval(() => {
      if (!alan.isConnected) { clearInterval(timer); return; }
      const d = dronVeri(sysid);
      const v = d && typeof d.alt_rel === "number" ? d.alt_rel : null;
      alan.textContent = (v === null) ? "\u2014" : v.toFixed(2) + " m";
      // Kalibrasyon sonrasi sifira YAKIN olmali
      alan.className = "db-olcum-deg" +
        (v === null ? "" : (Math.abs(v) <= 0.5 ? " iyi" : " uyari"));
    }, 500);
    if (pencereBilgi && pencereBilgi.pop) {
      pencereBilgi.pop._kalibTemizle = () => clearInterval(timer);
    }
  }

  // ---------------------------------------------------------------
  // 2c. IVMEOLCER (6 YON) — gorsel anlatim en onemli burada
  // ---------------------------------------------------------------
  // ArduPilot alti yon sirasi (olculmus sozlesme):
  //   level, left, right, nosedown, noseup, back
  // Arac her yone cevrildiginde STATUSTEXT "place vehicle <yon>" gelir;
  // pencere bu metni ayristirip SIRADAKI yonu vurgular.
  // MAVLink ACCELCAL_VEHICLE_POS enum kodlari pymavlink'ten DOGRUDAN
  // olculdu: LEVEL=1 LEFT=2 RIGHT=3 NOSEDOWN=4 NOSEUP=5 BACK=6
  // Sira ArduPilot'un istedigi sirayla ayni.
  const IVME_YONLER = [
    { anahtar: "level",    kod: 1, ad: "D\u00fcz (level)",       adEn: "Level",      ikon: "fa-square" },
    { anahtar: "left",     kod: 2, ad: "Sol yan\u0131na",        adEn: "Left side",  ikon: "fa-arrow-left" },
    { anahtar: "right",    kod: 3, ad: "Sa\u011f yan\u0131na",   adEn: "Right side", ikon: "fa-arrow-right" },
    { anahtar: "nosedown", kod: 4, ad: "Burun a\u015fa\u011f\u0131", adEn: "Nose down", ikon: "fa-arrow-down" },
    { anahtar: "noseup",   kod: 5, ad: "Burun yukar\u0131",      adEn: "Nose up",    ikon: "fa-arrow-up" },
    { anahtar: "back",     kod: 6, ad: "S\u0131rt\u0131 \u00fcst\u00fc", adEn: "On its back", ikon: "fa-rotate" }
  ];
  // Aracin sirada istedigi yon; mesaj akisindan turetilir.
  // Turetilemezse 1 (level) — kalibrasyon her zaman level ile baslar.
  const ivmeSiradakiKod = {};

  function kalibIvmeAc(fare, sysid) {
    const t = sozluk();
    const p = kalibPencere(fare, sysid, {
      anahtar: "ivme", ikon: "fa-cube",
      baslik: t.kalibIvme || "\u0130vme\u00f6l\u00e7er (6 y\u00f6n)",
      aciklama: t.kalibIvmeAcik6 ||
        "Ara\u00e7 s\u0131rayla alt\u0131 y\u00f6ne \u00e7evrilir. Her y\u00f6nde " +
        "sabit tutup ONAYLA'ya bas\u0131n; s\u0131radaki y\u00f6n vurgulan\u0131r.",
      gorselCiz: gorselIvmeYonler,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibIvmeOnay ||
          "\u0130vme\u00f6l\u00e7er kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131?",
        aksiyon: "kalib_ivme"
      }, {
        yazi: t.kalibIvmeOnayla || "Bu Y\u00f6n\u00fc Onayla",
        ikon: "fa-check", tur: "iyi",
        // Ayri WS ucu: komut_gonder imzasi yon kodu tasiyamiyor
        // (dokuz cagri yeri var, imza korunuyor).
        gonder: function (sid) {
          wsGonder({ tip: "ivme_yon_onay", sysid: Number(sid),
                     yon_kod: ivmeSiradakiKod[sid] || 1 });
        }
      }]
    });
    if (!p) return;
  }

  // Gorsel: alti yon rozeti; sirada olan vurgulanir, tamamlananlar
  // yesil onay isareti alir. Durum mesaj akisindan turetilir.
  function gorselIvmeYonler(kap, sysid) {
    const t = sozluk();
    const en = (typeof aktifDil !== "undefined" && aktifDil === "EN");
    const izgara = document.createElement("div");
    izgara.className = "db-ivme-izgara";
    for (const y of IVME_YONLER) {
      const h = document.createElement("div");
      h.className = "db-ivme-hucre";
      h.dataset.yon = y.anahtar;
      h.innerHTML =
        "<i class='fa-solid " + y.ikon + " db-ivme-ikon'></i>" +
        "<span class='db-ivme-ad'></span>" +
        "<i class='fa-solid fa-check db-ivme-tik'></i>";
      h.querySelector(".db-ivme-ad").textContent = en ? y.adEn : y.ad;
      izgara.appendChild(h);
    }
    kap.appendChild(izgara);
    const durum = document.createElement("div");
    durum.className = "db-ivme-durum";
    durum.textContent = t.dbIvmeBekle ||
      "Ba\u015flat'a bas\u0131n; ara\u00e7 hangi y\u00f6n\u00fc istiyorsa burada g\u00f6r\u00fcn\u00fcr.";
    kap.appendChild(durum);
    // Mesaj akisindan sıradaki yonu turet
    kap._ivmeGuncelle = function (mesajlar) {
      if (!mesajlar || !mesajlar.length) return;
      // En yeni ustte; "place vehicle <yon>" iceren ILK satiri bul
      let sirada = null;
      for (const m of mesajlar) {
        const s = String(m.metin || "").toLowerCase();
        if (s.indexOf("place vehicle") < 0) continue;
        for (const y of IVME_YONLER) {
          if (s.indexOf(y.anahtar) >= 0) { sirada = y.anahtar; break; }
          // ArduPilot "nose down"/"nose up" bosluklu da yazabilir
          if (y.anahtar === "nosedown" && s.indexOf("nose down") >= 0) { sirada = y.anahtar; break; }
          if (y.anahtar === "noseup" && s.indexOf("nose up") >= 0) { sirada = y.anahtar; break; }
        }
        if (sirada) break;
      }
      if (!sirada) return;
      const dizin = IVME_YONLER.findIndex((y) => y.anahtar === sirada);
      for (let i = 0; i < IVME_YONLER.length; i++) {
        const h = izgara.querySelector("[data-yon='" + IVME_YONLER[i].anahtar + "']");
        if (!h) continue;
        h.classList.toggle("sirada", i === dizin);
        h.classList.toggle("tamam", i < dizin);
      }
      const ad = en ? IVME_YONLER[dizin].adEn : IVME_YONLER[dizin].ad;
      durum.textContent = (t.dbIvmeSirada || "S\u0131radaki y\u00f6n") + ": " + ad;
      // Onay dugmesi bu yon kodunu gonderecek
      ivmeSiradakiKod[sysid] = IVME_YONLER[dizin].kod;
    };
    // Akis cizimi sonrasi cagrilmasi icin kaydet
    ivmeGorselKap[sysid] = kap;
  }
  const ivmeGorselKap = {};

  // ---------------------------------------------------------------
  // 2d. SEVIYE (LEVEL TRIM)
  // ---------------------------------------------------------------
  function kalibLevelAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "level", ikon: "fa-ruler-horizontal",
      baslik: t.kalibLevel || "Seviye (Level Trim)",
      aciklama: t.kalibLevelAcik ||
        "Dron d\u00fcz bir zemindeyken ufuk s\u0131f\u0131rlamas\u0131 yapar.",
      gorselCiz: gorselUfuk,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibLevelOnay ||
          "Seviye kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? Dron d\u00fcz zeminde olmal\u0131.",
        aksiyon: "kalib_level"
      }]
    });
  }
  // Gorsel: canli roll/pitch ufuk gostergesi. Kalibrasyon sonrasi
  // ikisi de sifira yakin olmali; bu yuzden CANLI deger gosterilir.
  function gorselUfuk(kap, sysid) {
    const t = sozluk();
    kap.innerHTML =
      "<div class='db-ufuk'>" +
      "  <div class='db-ufuk-kutu'><div class='db-ufuk-cizgi'></div>" +
      "    <div class='db-ufuk-merkez'></div></div>" +
      "  <div class='db-olcum-cift'>" +
      "    <div><span class='db-olcum-et'>Roll</span>" +
      "      <span class='db-olcum-deg' data-roll>—</span></div>" +
      "    <div><span class='db-olcum-et'>Pitch</span>" +
      "      <span class='db-olcum-deg' data-pitch>—</span></div>" +
      "  </div>" +
      "</div>";
    const cizgi = kap.querySelector(".db-ufuk-cizgi");
    const rEl = kap.querySelector("[data-roll]");
    const pEl = kap.querySelector("[data-pitch]");
    const timer = setInterval(() => {
      if (!cizgi.isConnected) { clearInterval(timer); return; }
      const d = dronVeri(sysid);
      const r = d && typeof d.roll === "number" ? d.roll : null;
      const pt = d && typeof d.pitch === "number" ? d.pitch : null;
      if (r === null || pt === null) {
        rEl.textContent = "\u2014"; pEl.textContent = "\u2014";
        return;
      }
      // roll/pitch derece cinsinden gelir (olculmus: hazirlik_ozeti
      // ayni alanlari derece olarak okuyor)
      cizgi.style.transform = "rotate(" + (-r) + "deg) translateY(" +
        (pt * 1.6) + "px)";
      rEl.textContent = r.toFixed(1) + "\u00b0";
      pEl.textContent = pt.toFixed(1) + "\u00b0";
      rEl.className = "db-olcum-deg" + (Math.abs(r) <= 1.5 ? " iyi" : " uyari");
      pEl.className = "db-olcum-deg" + (Math.abs(pt) <= 1.5 ? " iyi" : " uyari");
    }, 300);
  }

  // ---------------------------------------------------------------
  // 2e. PUSULA (MANYETOMETRE) — ilerleme + rapor degerleri
  // ---------------------------------------------------------------
  function kalibPusulaAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "pusula", ikon: "fa-compass",
      baslik: t.kalibPusula || "Pusula (Manyetometre)",
      aciklama: t.kalibPusulaAcik ||
        "Ba\u015flat\u0131nca dronu t\u00fcm eksenlerde d\u00f6nd\u00fcr\u00fcn. " +
        "\u0130lerleme ve sonu\u00e7 de\u011ferleri a\u015fa\u011f\u0131da g\u00f6r\u00fcn\u00fcr.",
      gorselCiz: gorselPusula,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibPusulaOnay ||
          "Pusula kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131?",
        aksiyon: "kalib_pusula_baslat"
      }, {
        yazi: t.kalibKabul || "Kabul", ikon: "fa-check", tur: "iyi",
        aksiyon: "kalib_pusula_kabul"
      }, {
        yazi: t.kalibIptalBtn || "\u0130ptal", ikon: "fa-xmark", tur: "kotu",
        aksiyon: "kalib_pusula_iptal"
      }]
    });
  }
  // Gorsel: donme yonu animasyonu + ilerleme cubugu + RAPOR DEGERLERI
  // (fitness, ofsetler). Kullanici "degerlerini de gostersin" dedi.
  function gorselPusula(kap, sysid) {
    const t = sozluk();
    kap.innerHTML =
      "<div class='db-pusula'>" +
      "  <div class='db-pusula-kure'>" +
      "    <div class='db-pusula-halka h1'></div>" +
      "    <div class='db-pusula-halka h2'></div>" +
      "    <div class='db-pusula-halka h3'></div>" +
      "    <i class='fa-solid fa-drone db-pusula-arac'></i>" +
      "  </div>" +
      "  <div class='db-bar-kutu'><div class='db-bar'></div>" +
      "    <span class='db-bar-yazi'></span></div>" +
      "  <div class='db-rapor' data-rapor></div>" +
      "</div>";
    const bar = kap.querySelector(".db-bar");
    const barYazi = kap.querySelector(".db-bar-yazi");
    const rapor = kap.querySelector("[data-rapor]");
    const timer = setInterval(() => {
      if (!bar.isConnected) { clearInterval(timer); return; }
      const d = dronVeri(sysid);
      if (!d) return;
      const durum = d.magkal_durum || "";
      const pct = Math.max(0, Math.min(100, Number(d.magkal_pct) || 0));
      if (durum === "suruyor") {
        bar.style.width = pct + "%";
        bar.className = "db-bar suruyor";
        barYazi.textContent = (t.kalibSuruyor || "S\u00fcr\u00fcyor") + " %" + pct;
      } else if (durum === "basarili") {
        bar.style.width = "100%";
        bar.className = "db-bar iyi";
        barYazi.textContent = t.kalibBasarili || "BA\u015eARILI";
      } else if (durum === "basarisiz") {
        bar.style.width = "100%";
        bar.className = "db-bar kotu";
        barYazi.textContent = t.kalibBasarisiz || "BA\u015eARISIZ";
      } else {
        bar.style.width = "0";
        barYazi.textContent = "";
      }
      raporCiz(rapor, d.magkal_rapor);
    }, 400);
  }
  // Pusula raporunun TAM degerleri (arka uc magkal_rapor'da tutuyor)
  function raporCiz(kap, r) {
    const t = sozluk();
    if (!r || typeof r !== "object") { kap.textContent = ""; return; }
    const satirlar = [
      [t.dbMagFitness || "Uyum hatas\u0131 (fitness)",
       (typeof r.fitness === "number") ? r.fitness.toFixed(2) + " mT" : "\u2014",
       (typeof r.fitness === "number") ? (r.fitness < 16 ? "iyi" : (r.fitness < 32 ? "uyari" : "kotu")) : ""],
      [t.dbMagOfsX || "Ofset X", saySay(r.ofs_x), ""],
      [t.dbMagOfsY || "Ofset Y", saySay(r.ofs_y), ""],
      [t.dbMagOfsZ || "Ofset Z", saySay(r.ofs_z), ""],
      [t.dbMagPusula || "Pusula no", (r.pusula_no !== undefined && r.pusula_no !== null) ? String(r.pusula_no) : "\u2014", ""]
    ];
    kap.textContent = "";
    for (const [ad, deg, sinif] of satirlar) {
      const s = document.createElement("div");
      s.className = "db-rapor-sat";
      const a = document.createElement("span");
      a.className = "db-rapor-ad";
      a.textContent = ad;
      const v = document.createElement("span");
      v.className = "db-rapor-deg" + (sinif ? " " + sinif : "");
      v.textContent = deg;
      s.appendChild(a); s.appendChild(v);
      kap.appendChild(s);
    }
  }
  function saySay(x) {
    const n = Number(x);
    return isFinite(n) ? n.toFixed(1) : "\u2014";
  }

  // ---------------------------------------------------------------
  // 2f. RADYO (RC) KALIBRASYONU — canli PWM cubuklari
  // ---------------------------------------------------------------
  function kalibRadyoAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "radyo", ikon: "fa-gamepad",
      baslik: t.kalibRadyo || "Radyo (RC) Kalibrasyonu",
      aciklama: t.kalibRadyoAcik ||
        "Ba\u015flat\u0131n ve t\u00fcm kumanda kollar\u0131n\u0131 u\u00e7 noktalar\u0131na " +
        "getirin. Anl\u0131k PWM de\u011ferleri a\u015fa\u011f\u0131da g\u00f6r\u00fcn\u00fcr.",
      gorselCiz: gorselRadyo,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
        onay: t.kalibRadyoOnay ||
          "Radyo kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? " +
          "Pervaneleri \u00e7\u0131kar\u0131n.",
        aksiyon: "kalib_radyo"
      }]
    });
  }
  // Gorsel: sekiz kanal PWM cubugu, min/max izleri
  function gorselRadyo(kap, sysid) {
    const t = sozluk();
    const izgara = document.createElement("div");
    izgara.className = "db-rc-izgara";
    const cubuklar = [];
    for (let i = 1; i <= 8; i++) {
      const s = document.createElement("div");
      s.className = "db-rc-sat";
      s.innerHTML =
        "<span class='db-rc-ad'>CH" + i + "</span>" +
        "<div class='db-rc-kutu'><div class='db-rc-dolgu'></div>" +
        "  <div class='db-rc-iz min'></div><div class='db-rc-iz max'></div></div>" +
        "<span class='db-rc-deg'>—</span>";
      izgara.appendChild(s);
      cubuklar.push({
        dolgu: s.querySelector(".db-rc-dolgu"),
        deg: s.querySelector(".db-rc-deg"),
        izMin: s.querySelector(".db-rc-iz.min"),
        izMax: s.querySelector(".db-rc-iz.max"),
        min: 2200, max: 800
      });
    }
    kap.appendChild(izgara);
    notSeridi(kap, t.dbRcNot ||
      "Kollar\u0131 u\u00e7 noktalara getirdik\u00e7e min/max izleri geni\u015fler.");
    const timer = setInterval(() => {
      if (!izgara.isConnected) { clearInterval(timer); return; }
      const d = dronVeri(sysid);
      const rc = d && d.rc_kanallar;
      if (!rc) return;
      for (let i = 0; i < 8; i++) {
        const v = Number(rc[i]);
        const c = cubuklar[i];
        if (!isFinite(v) || v <= 0) { c.deg.textContent = "\u2014"; continue; }
        if (v < c.min) c.min = v;
        if (v > c.max) c.max = v;
        // 1000-2000 aralik olcegi
        const oran = Math.max(0, Math.min(1, (v - 1000) / 1000));
        c.dolgu.style.width = (oran * 100) + "%";
        c.deg.textContent = String(Math.round(v));
        c.izMin.style.left = (Math.max(0, Math.min(1, (c.min - 1000) / 1000)) * 100) + "%";
        c.izMax.style.left = (Math.max(0, Math.min(1, (c.max - 1000) / 1000)) * 100) + "%";
      }
    }, 200);
  }

  // ---------------------------------------------------------------
  // 2g. ESC KALIBRASYONU (tehlikeli)
  // ---------------------------------------------------------------
  function kalibEscAc(fare, sysid) {
    const t = sozluk();
    kalibPencere(fare, sysid, {
      anahtar: "esc", ikon: "fa-bolt",
      baslik: t.kalibEsc || "ESC Kalibrasyonu",
      uyari: t.kalibEscUyari ||
        "PERVANELER\u0130 MUTLAKA \u00c7IKARIN. Motorlar tam g\u00fc\u00e7te d\u00f6nebilir.",
      aciklama: t.kalibEscAcik ||
        "Sonraki a\u00e7\u0131l\u0131\u015fta ESC kalibrasyon modu etkinle\u015fir. " +
        "Ard\u0131ndan pili tak\u0131p ESC'lerin sesli onay\u0131n\u0131 bekleyin.",
      gorselCiz: gorselEsc,
      dugmeler: [{
        yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-triangle-exclamation",
        tur: "kotu",
        onay: t.kalibEscOnay ||
          "ESC kalibrasyonu ayarlans\u0131n m\u0131? PERVANELER\u0130 MUTLAKA \u00c7IKARIN!",
        aksiyon: "kalib_esc"
      }]
    });
  }
  function gorselEsc(kap) {
    const t = sozluk();
    kap.innerHTML =
      "<div class='db-esc-adim'>" +
      "  <div class='db-esc-sat'><span class='db-esc-no'>1</span>" +
      "    <span class='db-esc-metin'></span></div>" +
      "  <div class='db-esc-sat'><span class='db-esc-no'>2</span>" +
      "    <span class='db-esc-metin'></span></div>" +
      "  <div class='db-esc-sat'><span class='db-esc-no'>3</span>" +
      "    <span class='db-esc-metin'></span></div>" +
      "  <div class='db-esc-sat'><span class='db-esc-no'>4</span>" +
      "    <span class='db-esc-metin'></span></div>" +
      "</div>";
    const metinler = [
      t.dbEsc1 || "Pervaneleri \u00e7\u0131kar\u0131n ve pili s\u00f6k\u00fcn.",
      t.dbEsc2 || "BA\u015eLAT'a bas\u0131n (kalibrasyon modu i\u015faretlenir).",
      t.dbEsc3 || "Pili tak\u0131n; ESC'ler s\u0131rayla bip sesi verir.",
      t.dbEsc4 || "Bipler bitince pili s\u00f6k\u00fcn; kalibrasyon tamamd\u0131r."
    ];
    const satlar = kap.querySelectorAll(".db-esc-metin");
    for (let i = 0; i < satlar.length; i++) satlar[i].textContent = metinler[i];
  }

  // ===============================================================
  // 3. MOTOR TESTI PENCERESI
  // ---------------------------------------------------------------
  // Guvenlik: arm durumu SUREKLI izlenir; armli iken dugmeler kilitli.
  // Arka uc de reddediyor (cift kapi — biri asilirsa oteki tutar).
  // ===============================================================
  function motorTestAc(fare, sysid) {
    const t = sozluk();
    const p = pencere("dbMotorTest_" + sysid,
      (t.dbMotorTest || "MOTOR TEST\u0130") + " \u2014 D" + sysid,
      "fa-fan", fare, "db-motor-pencere");
    if (!p) return;

    uyariSeridi(p.govde, t.dbMotorUyari ||
      "PERVANELER\u0130 \u00c7IKARIN. Motorlar bu testte d\u00f6ner.");

    const alanlar = document.createElement("div");
    alanlar.className = "db-alanlar";
    p.govde.appendChild(alanlar);

    const gMotor = sayiGirisi(alanlar, t.dbMotorSira || "Motor s\u0131ras\u0131",
      1, 1, 12, 1, t.dbMotorSiraIpucu || "1-12 (\u00e7\u0131k\u0131\u015f s\u0131ras\u0131)");

    // Test tipi secimi
    const tipSar = document.createElement("label");
    tipSar.className = "db-alan";
    const tipEt = document.createElement("span");
    tipEt.className = "db-alan-et";
    tipEt.textContent = t.dbMotorTip || "Test tipi";
    const tipSec = document.createElement("select");
    tipSec.className = "db-alan-gir";
    const tipler = [
      { v: "0", ad: t.dbMotorTipYuzde || "Y\u00fczde (%)" },
      { v: "1", ad: t.dbMotorTipPwm || "PWM (\u00b5s)" },
      { v: "2", ad: t.dbMotorTipPilot || "Pilot gaz\u0131" }
    ];
    for (const x of tipler) {
      const o = document.createElement("option");
      o.value = x.v; o.textContent = x.ad;
      tipSec.appendChild(o);
    }
    tipSar.appendChild(tipEt); tipSar.appendChild(tipSec);
    alanlar.appendChild(tipSar);

    const gDeger = sayiGirisi(alanlar, t.dbMotorDeger || "De\u011fer",
      5, 0, 100, 1, t.dbMotorDegerIpucu ||
      "Y\u00fczde kipinde 0-100 aras\u0131; g\u00fcvenli ba\u015flang\u0131\u00e7 %5");
    const gSure = sayiGirisi(alanlar, t.dbMotorSure || "S\u00fcre (s)",
      2, 0.5, 10, 0.5, t.dbMotorSureIpucu || "En \u00e7ok 10 saniye");

    // Sirayla tumu
    const siraSar = document.createElement("label");
    siraSar.className = "db-alan db-alan-onay";
    const siraKutu = document.createElement("input");
    siraKutu.type = "checkbox";
    const siraEt = document.createElement("span");
    siraEt.textContent = t.dbMotorSirayla ||
      "T\u00fcm motorlar\u0131 s\u0131rayla test et";
    siraSar.appendChild(siraKutu); siraSar.appendChild(siraEt);
    alanlar.appendChild(siraSar);

    const gAdet = sayiGirisi(alanlar, t.dbMotorAdet || "Motor say\u0131s\u0131",
      4, 1, 12, 1, t.dbMotorAdetIpucu ||
      "S\u0131rayla testte ka\u00e7 motor denenecek");
    gAdet.closest(".db-alan").style.display = "none";
    siraKutu.addEventListener("change", () => {
      gAdet.closest(".db-alan").style.display = siraKutu.checked ? "" : "none";
      gMotor.closest(".db-alan").style.display = siraKutu.checked ? "none" : "";
    });

    // Deger ust siniri test tipine gore degisir
    tipSec.addEventListener("change", () => {
      if (tipSec.value === "1") {
        gDeger.min = "1000"; gDeger.max = "2000";
        if (Number(gDeger.value) < 1000) gDeger.value = "1100";
      } else {
        gDeger.min = "0"; gDeger.max = "100";
        if (Number(gDeger.value) > 100) gDeger.value = "5";
      }
    });

    const btnKutu = document.createElement("div");
    btnKutu.className = "db-btnler";
    p.govde.appendChild(btnKutu);

    const btnBaslat = dugmeKur(btnKutu, t.dbMotorBaslat || "Testi Ba\u015flat",
      "fa-play", "kotu", () => {
        const motor = siraKutu.checked ? 1 : Number(gMotor.value);
        const govde = {
          tip: "motor_test", sysid: Number(sysid),
          motor: motor, tip_no: Number(tipSec.value),
          deger: Number(gDeger.value), sure: Number(gSure.value),
          adet: siraKutu.checked ? Number(gAdet.value) : 0,
          sira: siraKutu.checked ? 1 : 0
        };
        onayIste(
          (t.dbMotorOnay || "Motor testi ba\u015flat\u0131ls\u0131n m\u0131? " +
           "PERVANELER \u00c7IKARILMI\u015e OLMALI!"),
          () => wsGonder(govde));
      });
    const btnDur = dugmeKur(btnKutu, t.dbMotorDurdur || "DURDUR",
      "fa-stop", "acil", () => {
        wsGonder({ tip: "motor_test_dur", sysid: Number(sysid) });
      });
    btnDur.classList.add("db-btn-genis");

    const sonuc = document.createElement("div");
    sonuc.className = "db-sonuc";
    sonuc.dataset.motorSonuc = String(sysid);
    p.govde.appendChild(sonuc);

    // Arm kilidi: armli iken baslatma kilitli
    const kilit = document.createElement("div");
    kilit.className = "db-kilit";
    kilit.innerHTML = "<i class='fa-solid fa-lock'></i> <span></span>";
    kilit.querySelector("span").textContent = t.dbMotorArmliKilit ||
      "Ara\u00e7 ARM edilmi\u015f. Motor testi yaln\u0131z DISARM durumda yap\u0131l\u0131r.";
    p.govde.appendChild(kilit);
    const timer = setInterval(() => {
      if (!kilit.isConnected) { clearInterval(timer); return; }
      const armli = armliMi(sysid);
      kilit.style.display = armli ? "" : "none";
      btnBaslat.disabled = armli;
    }, 400);
    kilit.style.display = armliMi(sysid) ? "" : "none";
    btnBaslat.disabled = armliMi(sysid);
  }

  window.motorTestSonucIsle = function (m) {
    const kap = document.querySelector(
      "[data-motor-sonuc='" + Number(m.sysid) + "']");
    if (!kap) return;
    const t = sozluk();
    kap.className = "db-sonuc " + (m.basari ? "iyi" : "kotu");
    let metin = m.basari
      ? (m.durduruldu ? (t.dbMotorDurduruldu || "Test durduruldu.")
                      : (t.dbMotorBasladi || "Test ba\u015flad\u0131."))
      : (m.sebep || (t.dbMotorRed || "Test reddedildi."));
    kap.textContent = metin;
  };

  // ===============================================================
  // 4. ILK AYAR (INITIAL TUNE) PENCERESI
  // ---------------------------------------------------------------
  // Mission Planner "Initial Tune Parameters" karsiligi.
  // Iki girdi (pervane capi, hucre sayisi) -> ongoru tablosu -> onay
  // -> yazma. Ongoru DOGRUDAN YAZILMAZ.
  // ===============================================================
  const ilkAyarPencereler = {};   // sysid -> {tablo, sonuc, ongoru}

  function ilkAyarAc(fare, sysid) {
    const t = sozluk();
    const p = pencere("dbIlkAyar_" + sysid,
      (t.dbIlkAyar || "\u0130LK AYAR PARAMETRELER\u0130") + " \u2014 D" + sysid,
      "fa-wand-magic-sparkles", fare, "db-ilkayar-pencere");
    if (!p) return;

    notSeridi(p.govde, t.dbIlkAyarNot ||
      "De\u011ferler ArduPilot'un \u00f6nerdi\u011fi ba\u015flang\u0131\u00e7 " +
      "ayarlar\u0131d\u0131r. Ayar u\u00e7u\u015fu i\u00e7in ba\u015flang\u0131\u00e7 " +
      "noktas\u0131d\u0131r, son de\u011ferler de\u011fildir.");

    const alanlar = document.createElement("div");
    alanlar.className = "db-alanlar db-alanlar-yatay";
    p.govde.appendChild(alanlar);
    const gCap = sayiGirisi(alanlar, t.dbIlkAyarCap || "Pervane \u00e7ap\u0131 (in\u00e7)",
      10, 3, 60, 0.5);
    const gHucre = sayiGirisi(alanlar, t.dbIlkAyarHucre || "Pil h\u00fccre (S)",
      4, 2, 14, 1);

    const btnKutu = document.createElement("div");
    btnKutu.className = "db-btnler";
    p.govde.appendChild(btnKutu);
    dugmeKur(btnKutu, t.dbIlkAyarHesap || "\u00d6ng\u00f6r\u00fc Hesapla",
      "fa-calculator", "", () => {
        wsGonder({
          tip: "ilk_ayar_ongoru", sysid: Number(sysid),
          cap_inc: Number(gCap.value), hucre: Number(gHucre.value)
        });
      });

    const tablo = document.createElement("div");
    tablo.className = "db-tablo";
    p.govde.appendChild(tablo);
    const notlar = document.createElement("div");
    notlar.className = "db-notlar";
    p.govde.appendChild(notlar);

    // Mission Planner esitligi: multimetre ile olculen gercek paket
    // voltaji girilir; sunucu canli telemetri ve BATT_VOLT_MULT ile yeni
    // carpani hesaplar. ARM durumunda hem UI hem sunucu islemi reddeder.
    const voltajBolum = document.createElement("section");
    voltajBolum.className = "db-batarya-kalib";
    const voltajBaslik = document.createElement("h4");
    voltajBaslik.textContent = t.dbVoltajKalib || "BATARYA VOLTAJ KALIBRASYONU";
    voltajBolum.appendChild(voltajBaslik);
    const voltajAciklama = document.createElement("p");
    voltajAciklama.textContent = t.dbVoltajKalibNot ||
      "Araç DISARM durumundayken multimetre ile ölçülen gerçek paket voltajını girin. Çarpan, canlı telemetri ile hesaplanır.";
    voltajBolum.appendChild(voltajAciklama);
    const voltajAlan = document.createElement("div");
    voltajAlan.className = "db-alanlar db-alanlar-yatay";
    voltajBolum.appendChild(voltajAlan);
    const gGercekVoltaj = sayiGirisi(voltajAlan,
      t.dbGercekVoltaj || "Gerçek voltaj (V)", 0, 5, 80, 0.01);
    const canliVoltaj = document.createElement("div");
    canliVoltaj.className = "db-voltaj-canli";
    voltajAlan.appendChild(canliVoltaj);
    const voltajBtnler = document.createElement("div");
    voltajBtnler.className = "db-btnler";
    voltajBolum.appendChild(voltajBtnler);
    const btnVoltaj = dugmeKur(voltajBtnler,
      t.dbVoltajKalibUygula || "Çarpanı Hesapla ve Yaz", "fa-battery-half", "", () => {
        onayIste(t.dbVoltajKalibOnay ||
          "BATT_VOLT_MULT değeri ölçülen gerçek voltaja göre güncellenecek. Araç DISARM durumda olmalıdır. Onaylıyor musunuz?",
          () => wsGonder({ tip: "voltaj_kalibrasyon", sysid: Number(sysid),
                           gercek_voltaj: Number(gGercekVoltaj.value) }));
      });
    const voltajSonuc = document.createElement("div");
    voltajSonuc.className = "db-sonuc";
    voltajBolum.appendChild(voltajSonuc);
    p.govde.appendChild(voltajBolum);
    const voltajTimer = setInterval(() => {
      if (!canliVoltaj.isConnected) { clearInterval(voltajTimer); return; }
      const d = dronVeri(sysid);
      const v = d && Number(d.batarya_v);
      const armli = armliMi(sysid);
      canliVoltaj.textContent = isFinite(v) && v > 0
        ? ((t.dbCanliVoltaj || "Canlı telemetri") + ": " + v.toFixed(2) + " V")
        : (t.dbCanliVoltajYok || "Canlı batarya verisi bekleniyor");
      btnVoltaj.disabled = armli || !(isFinite(v) && v > 0);
    }, 400);
    p.pop._kalibTemizle = () => clearInterval(voltajTimer);

    const uygulaKutu = document.createElement("div");
    uygulaKutu.className = "db-btnler";
    p.govde.appendChild(uygulaKutu);
    const btnUygula = dugmeKur(uygulaKutu,
      t.dbIlkAyarUygula || "Araca Yaz", "fa-upload", "kotu", () => {
        const kayit = ilkAyarPencereler[sysid];
        if (!kayit || !kayit.ongoru) return;
        onayIste(
          (t.dbIlkAyarOnay ||
           "\u00d6ng\u00f6r\u00fclen de\u011ferler araca YAZILACAK. " +
           "Mevcut ayar de\u011ferleri de\u011fi\u015fecek. Onaylan\u0131yor mu?"),
          () => wsGonder({
            tip: "ilk_ayar_uygula", sysid: Number(sysid),
            parametreler: kayit.ongoru
          }));
      });
    btnUygula.disabled = true;

    const sonuc = document.createElement("div");
    sonuc.className = "db-sonuc";
    p.govde.appendChild(sonuc);

    ilkAyarPencereler[sysid] = {
      tablo: tablo, notlar: notlar, sonuc: sonuc,
      btnUygula: btnUygula, ongoru: null, pop: p.pop,
      voltajSonuc: voltajSonuc, gGercekVoltaj: gGercekVoltaj
    };
  }

  window.ilkAyarOngorusuIsle = function (m) {
    const kayit = ilkAyarPencereler[Number(m.sysid)];
    if (!kayit || !kayit.pop.isConnected) return;
    const t = sozluk();
    if (!m.basari) {
      kayit.tablo.textContent = "";
      kayit.notlar.textContent = "";
      kayit.sonuc.className = "db-sonuc kotu";
      kayit.sonuc.textContent = m.sebep || (t.dbIlkAyarHata || "Hesap yap\u0131lamad\u0131.");
      kayit.btnUygula.disabled = true;
      kayit.ongoru = null;
      return;
    }
    kayit.ongoru = m.parametreler || {};
    kayit.sonuc.className = "db-sonuc";
    kayit.sonuc.textContent = "";
    // Tablo: parametre, onerilen, aracin mevcut degeri
    const onbellek = (window.dronAyarParamOnbellek || {})[Number(m.sysid)] || {};
    kayit.tablo.textContent = "";
    const bas = document.createElement("div");
    bas.className = "db-tablo-sat db-tablo-bas";
    bas.innerHTML = "<span></span><span></span><span></span>";
    const basHucre = bas.querySelectorAll("span");
    basHucre[0].textContent = t.dbTabloParam || "Parametre";
    basHucre[1].textContent = t.dbTabloOneri || "\u00d6nerilen";
    basHucre[2].textContent = t.dbTabloMevcut || "Mevcut";
    kayit.tablo.appendChild(bas);
    const adlar = Object.keys(kayit.ongoru).sort();
    for (const ad of adlar) {
      const s = document.createElement("div");
      s.className = "db-tablo-sat";
      const a = document.createElement("span");
      a.className = "db-tablo-ad";
      a.textContent = ad;
      const o = document.createElement("span");
      o.className = "db-tablo-oneri";
      o.textContent = bicimle(kayit.ongoru[ad]);
      const v = document.createElement("span");
      v.className = "db-tablo-mevcut";
      const mev = onbellek[ad];
      if (mev === undefined || mev === null) {
        v.textContent = "\u2014";
        v.classList.add("bos");
      } else {
        v.textContent = bicimle(mev);
        // Fark varsa vurgula
        if (Math.abs(Number(mev) - Number(kayit.ongoru[ad])) > 1e-4)
          v.classList.add("farkli");
      }
      s.appendChild(a); s.appendChild(o); s.appendChild(v);
      kayit.tablo.appendChild(s);
    }
    // Notlar
    kayit.notlar.textContent = "";
    for (const n of (m.notlar || [])) {
      const d = document.createElement("div");
      d.className = "db-notlar-sat";
      d.textContent = n;
      kayit.notlar.appendChild(d);
    }
    if (!adlar.length) {
      kayit.btnUygula.disabled = true;
    } else {
      kayit.btnUygula.disabled = false;
      // Mevcut deger yoksa uyari: onbellek bos
      if (!Object.keys(onbellek).length) {
        const u = document.createElement("div");
        u.className = "db-notlar-sat uyari";
        u.textContent = t.dbIlkAyarOnbellekBos ||
          "Arac\u0131n mevcut de\u011ferleri \u00f6nbellekte yok. " +
          "Parametreler ekran\u0131ndan T\u00dcM\u00dcN\u00dc AL yap\u0131n.";
        kayit.notlar.appendChild(u);
      }
    }
  };

  function bicimle(x) {
    const n = Number(x);
    if (!isFinite(n)) return String(x);
    if (Math.abs(n - Math.round(n)) < 1e-9) return String(Math.round(n));
    return n.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }

  window.ilkAyarSonucIsle = function (m) {
    const kayit = ilkAyarPencereler[Number(m.sysid)];
    if (!kayit || !kayit.pop.isConnected) return;
    const t = sozluk();
    const hatalar = m.hatalar || [];
    const yazilan = Number(m.yazilan) || 0;
    kayit.sonuc.className = "db-sonuc " + (hatalar.length ? "uyari" : "iyi");
    let metin = (t.dbIlkAyarYazilan || "Yaz\u0131lan parametre") + ": " + yazilan;
    if (hatalar.length) metin += " \u2014 " + hatalar.join("; ");
    kayit.sonuc.textContent = metin;
  };

  window.voltajKalibrasyonSonucIsle = function (m) {
    const kayit = ilkAyarPencereler[Number(m.sysid)];
    if (!kayit || !kayit.pop.isConnected || !kayit.voltajSonuc) return;
    const t = sozluk();
    if (!m.basari) {
      kayit.voltajSonuc.className = "db-sonuc kotu";
      kayit.voltajSonuc.textContent = m.sebep ||
        (t.dbVoltajKalibHata || "Voltaj kalibrasyonu uygulanamadı.");
      return;
    }
    kayit.voltajSonuc.className = "db-sonuc iyi";
    kayit.voltajSonuc.textContent = (t.dbVoltajKalibTamam || "BATT_VOLT_MULT güncellendi") +
      ": " + bicimle(m.mevcut_carpan) + " → " + bicimle(m.yeni_carpan) +
      " (" + bicimle(m.okunan_voltaj) + " V → " + bicimle(m.gercek_voltaj) + " V)";
  };

  // ===============================================================
  // 5. REBOOT
  // ---------------------------------------------------------------
  function rebootIste(sysid) {
    const t = sozluk();
    if (armliMi(sysid)) {
      if (typeof window.hataBildir === "function")
        window.hataBildir(t.dbRebootArmli ||
          "Ara\u00e7 ARM edilmi\u015f. Reboot yaln\u0131z DISARM durumda yap\u0131l\u0131r.");
      else
        alert(t.dbRebootArmli ||
          "Ara\u00e7 ARM edilmi\u015f. Reboot yaln\u0131z DISARM durumda yap\u0131l\u0131r.");
      return;
    }
    onayIste(
      (t.dbRebootOnay ||
       "U\u00e7u\u015f kontrolc\u00fcs\u00fc yeniden ba\u015flat\u0131ls\u0131n m\u0131? " +
       "Telemetri ba\u011flant\u0131s\u0131 ge\u00e7ici olarak kesilir."),
      () => wsGonder({ tip: "dron_komut", sysid: Number(sysid),
                       aksiyon: "reboot" }));
  }

  // ===============================================================
  // DISA ACILAN ARAYUZ
  // ===============================================================
  // v2.5.0: ivme yon onayi yaniti. Arka uc aralik disi yon kodunu
  // araca GONDERMEZ ve sebebi dondurur; bu yanit gosterilmezse
  // operator kalibrasyonun neden ilerlemedigini anlayamaz.
  window.ivmeYonOnaySonucIsle = function (m) {
    const kap = ivmeGorselKap[m.sysid];
    if (!kap) return;
    const durum = kap.querySelector(".db-ivme-durum");
    if (!durum) return;
    const t = sozluk();
    if (m.basari) {
      // Basarili onaydan sonra arac sonraki yonu STATUSTEXT ile bildirir;
      // izgara mesaj akisiyla guncellenir. Burada yalniz onay yazilir.
      durum.textContent = (t.dbIvmeOnaylandi || "Y\u00f6n onayland\u0131") +
        " \u2014 " + (t.dbIvmeSonrakiBekle ||
        "ara\u00e7 s\u0131radaki y\u00f6n\u00fc bildirecek");
    } else {
      durum.textContent = (t.dbIvmeOnayHata || "Onay g\u00f6nderilemedi") +
        ": " + (m.sebep || "");
    }
  };

  window.dbKalibSecimAc = kalibSecimAc;
  window.dbMotorTestAc = motorTestAc;
  window.dbIlkAyarAc = ilkAyarAc;
  window.dbRebootIste = rebootIste;
  // Ivme gorseli mesaj akisindan beslenir
  window.dbIvmeAkisIsle = function (sysid, mesajlar) {
    const kap = ivmeGorselKap[sysid];
    if (kap && kap.isConnected && typeof kap._ivmeGuncelle === "function")
      kap._ivmeGuncelle(mesajlar);
  };
})();
