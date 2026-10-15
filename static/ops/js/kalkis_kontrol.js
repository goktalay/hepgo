// FAZ18-IS27-28-30: ikon+metin dugmelerinde metin <span> icine
// sarildi. Sebep: dugme_birlik.css yalniz-ikon kurali
// `:has(> i):not(:has(> span))` bu dugmeleri 26px kareye
// zorluyordu ve metin tasiyordu. CSS EZILMEDI; sozlesmeye
// uyuldu. Yalniz-ikon dugmelere DOKUNULMADI.
// =================================================================
// GOKTUNGU - KALKIS ONCESI KONTROL LISTESI  [v2.4.41]
// Pilot TAKEOFF verdiginde acilan zorunlu kontrol listesi.
//
// Tasarim kararlari (DURUM_2441.md V/K/Q bolumleri):
//  * UC KATMANLI madde uretimi:
//      1) Arac tipine ozel FIZIKSEL maddeler (pilotun elle dogruladigi)
//      2) Her arac icin ortak fiziksel maddeler
//      3) Parametrelerden turetilen KOSULLU maddeler (parasut, ilaclama,
//         geofence, RTL irtifasi, QuadPlane...)
//    Parametre onbellegi yoksa 3. katman EKLENMEZ (uydurma madde yok).
//  * Makinenin OLCEBILECEGI seyler pilota SORULMAZ (GPS fix, EKF,
//    batarya voltaji...). Bunlar ust banttaki salt-okunur "otomatik
//    dogrulama" ozetinde gosterilir. Pilota yalnizca makinenin
//    bilemeyecegi fiziksel kontroller sorulur.
//  * Cevap kontrolu UC durumlu ikili slider: notr / HAYIR(sol,kirmizi) /
//    EVET(sag,yesil). Notr baslangic "pilot bu maddeyi hic gormedi" ile
//    "pilot HAYIR dedi" ayrimini kayitta korur.
//  * TUM zorunlu maddeler EVET olmadan "TAKEOFF'U TAMAMLA" pasiftir.
//  * Kayit SUNUCUDA yapilir; tarih/saat ve pilot kimligi istemciden
//    ALINMAZ. Kayit yazilamazsa takeoff komutu GONDERILMEZ.
// dronlar.js'deki dkMiniPopup* yardimcilarini kullanir (ortak scope).
// =================================================================

// Acik kontrol listesi popuplari: sysid -> {pop, maddeler, ...}
var kkPopuplar = {};

// ---------------------------------------------------------------
// HTML kacisi (arm_check.js'teki acKacis window'a acilmadigi icin
// bagimsiz kopya)
// ---------------------------------------------------------------
function kkKacis(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------
// Parametre onbelleginden sayisal deger okuma
// dronAyarOnbellek() yapisi: {sysid: {PARAM_AD: deger, ...}}
// Deger nesne ({deger: x}) veya duz sayi olabilir; ikisi de desteklenir.
// ---------------------------------------------------------------
function kkParamDeger(paramSet, ad) {
  if (!paramSet) return null;
  let v = paramSet[ad];
  if (v == null) return null;
  if (typeof v === "object") v = (v.deger != null ? v.deger : v.value);
  const s = Number(v);
  return isFinite(s) ? s : null;
}

// ---------------------------------------------------------------
// MADDE URETIMI
// mt: MAV_TYPE (sonVeri[sysid].arac_tipi)
// paramSet: parametre onbellegi (yoksa null)
// Donen: [{anahtar, soru, grup, zorunlu, kaynak, not}]
// ---------------------------------------------------------------
function kkMaddeleriUret(mt, paramSet) {
  const t = D();
  const M = [];
  const ekle = (anahtar, varsayilanSoru, grup, kaynak, not) => {
    M.push({
      anahtar: anahtar,
      soru: t["kk_" + anahtar] || varsayilanSoru,
      grup: grup,
      zorunlu: true,
      kaynak: kaynak || "tip",
      not: not || "",
    });
  };

  // dkAracTipiBilgi ile ayni MAV_TYPE eslemesi kullanilir
  const tip = Number(mt) || 0;
  const sabitKanat = (tip === 1);
  const heli = (tip === 4);
  const vtol = (tip >= 19 && tip <= 25);
  // Q_ENABLE > 0 -> QuadPlane: MAV_TYPE sabit kanat gorunse bile
  // multirotor maddeleri de sorulmali
  const qEnable = kkParamDeger(paramSet, "Q_ENABLE");
  const quadPlane = (qEnable != null && qEnable > 0);
  // Multirotor maddeleri: cok rotorlu her arac + VTOL + QuadPlane
  const multi = (!sabitKanat && !heli) || vtol || quadPlane;

  // ---- GRUP 1: ARAC TIPINE OZEL FIZIKSEL KONTROLLER ----
  if (multi) {
    ekle("pervane_yon",
      "Pervane y\u00f6nleri ve s\u0131ralar\u0131 do\u011fru mu?",
      "arac", "tip");
    ekle("pervane_siki",
      "Pervaneler s\u0131k\u0131 ve hasars\u0131z m\u0131?", "arac", "tip");
    ekle("motor_yon",
      "Motor d\u00f6n\u00fc\u015f y\u00f6nleri test edildi mi?",
      "arac", "tip");
  }
  if (sabitKanat || vtol || quadPlane) {
    ekle("servo_kontrol",
      "Servolar (aileron / elevator / rudder) kontrol edildi mi?",
      "arac", "tip");
    ekle("yuzey_yon",
      "Kumanda y\u00fczeyleri do\u011fru y\u00f6nde hareket ediyor mu?",
      "arac", "tip");
    ekle("pitot",
      "Pitot / statik borusu a\u00e7\u0131k ve kapa\u011f\u0131 al\u0131nd\u0131 m\u0131?",
      "arac", "tip");
    ekle("kanat_pim",
      "Kanat ba\u011flant\u0131 pimleri ve emniyetleri tak\u0131l\u0131 m\u0131?",
      "arac", "tip");
    ekle("kalkis_duzeni",
      "F\u0131rlatma d\u00fczeni / pist haz\u0131r m\u0131?", "arac", "tip");
  }
  if (vtol || quadPlane) {
    ekle("gecis_teyit",
      "Ge\u00e7i\u015f (transition) irtifa ve h\u0131z\u0131 teyit edildi mi?",
      "arac", "tip");
  }
  if (heli) {
    ekle("rotor_kontrol",
      "Ana rotor ve kuyruk rotoru kontrol edildi mi?", "arac", "tip");
    ekle("swashplate",
      "Swashplate hareketi do\u011fru mu?", "arac", "tip");
    ekle("kavrama",
      "Kavrama (clutch) ve kay\u0131\u015f gerginli\u011fi uygun mu?",
      "arac", "tip");
  }

  // ---- GRUP 2: HER ARAC ICIN ORTAK ----
  ekle("batarya_bagli",
    "Batarya sa\u011flam, \u015farjl\u0131 ve emniyetli \u015fekilde ba\u011fl\u0131 m\u0131?",
    "genel", "genel");
  ekle("alan_temiz",
    "Kalk\u0131\u015f alan\u0131 ve pervane b\u00f6lgesi insanlardan ar\u0131nd\u0131r\u0131ld\u0131 m\u0131?",
    "genel", "genel");
  ekle("rc_menzil",
    "Kumanda ve telemetri ba\u011flant\u0131s\u0131 test edildi mi?",
    "genel", "genel");
  ekle("ucus_izni",
    "U\u00e7u\u015f izni ve hava sahas\u0131 durumu teyit edildi mi?",
    "genel", "genel");

  // ---- GRUP 3: PARAMETRELERDEN TURETILEN KOSULLU MADDELER ----
  // Parametre onbellegi yoksa bu katman TAMAMEN atlanir.
  if (paramSet) {
    const chute = kkParamDeger(paramSet, "CHUTE_ENABLED");
    if (chute === 1) {
      ekle("parasut",
        "Para\u015f\u00fct emniyet pimi \u00e7ekildi mi?", "param", "param");
    }
    const spray = kkParamDeger(paramSet, "SPRAY_ENABLE");
    if (spray === 1) {
      ekle("ilaclama",
        "\u0130la\u00e7lama pompas\u0131 ve tank kontrol edildi mi?",
        "param", "param");
    }
    const fence = kkParamDeger(paramSet, "FENCE_ENABLE");
    if (fence === 1) {
      ekle("geofence",
        "\u00c7it (geofence) s\u0131n\u0131rlar\u0131 g\u00f6rev alan\u0131n\u0131 kaps\u0131yor mu?",
        "param", "param");
    }
    const rtlAlt = kkParamDeger(paramSet, "RTL_ALT");
    if (rtlAlt != null && rtlAlt > 0) {
      // RTL_ALT santimetre cinsindendir (ArduPilot)
      const m = (rtlAlt / 100).toFixed(0);
      const madde = M[M.length] = {
        anahtar: "rtl_irtifa",
        soru: (t.kk_rtl_irtifa ||
          "RTL irtifas\u0131 engellerin \u00fczerinde mi?"),
        grup: "param",
        zorunlu: true,
        kaynak: "param",
        not: "RTL_ALT = " + m + " m",
      };
      void madde;
    }
  }
  return M;
}

// ---------------------------------------------------------------
// Grup basliklari
// ---------------------------------------------------------------
function kkGrupBaslik(grup, tipAd) {
  const t = D();
  if (grup === "arac")
    return (t.kkGrupArac || "ARA\u00c7 KONTROLLER\u0130") +
           (tipAd ? " \u2014 " + tipAd.toUpperCase() : "");
  if (grup === "param")
    return t.kkGrupParam ||
      "PARAMETRELERE G\u00d6RE EK KONTROLLER";
  return t.kkGrupGenel || "GENEL KONTROLLER";
}

function kkGrupIkon(grup) {
  if (grup === "arac") return "fa-helicopter-symbol";
  if (grup === "param") return "fa-sliders";
  return "fa-list-check";
}

// ---------------------------------------------------------------
// KONTROL LISTESI POPUP'I
// sysid: dron, irtifa: pilotun sectigi hedef irtifa (m)
// anka: konumlandirma icin fare olayi (opsiyonel)
// ---------------------------------------------------------------
function kalkisKontrolAc(sysid, irtifa, anka) {
  const kimlik = "dkPopupKalkisKontrol_" + sysid;
  const eski = dkPopupTekil(kimlik);
  if (eski) return;           // zaten acik
  const t = D();

  const d = (typeof sonVeri !== "undefined" && sonVeri[sysid]) || {};
  const tipBilgi = (typeof dkAracTipiBilgi === "function")
    ? dkAracTipiBilgi(d) : null;
  const tipAd = (tipBilgi && (tipBilgi.ad || tipBilgi.isim)) || "";
  const paramSet = (typeof dronAyarOnbellek === "function")
    ? (dronAyarOnbellek()[sysid] || null) : null;
  const maddeler = kkMaddeleriUret(d.arac_tipi, paramSet);

  const pop = document.createElement("div");
  pop.id = kimlik;
  pop.className = "dk-mini-popup kk-popup";
  dkMiniPopupBaslikKur(pop,
    (t.kkBaslik || "KALKI\u015e KONTROL L\u0130STES\u0130") + " \u2014 D" + sysid,
    null, "fa-clipboard-check");

  // ---- Otomatik dogrulama bandi (makine olcumu — salt okunur) ----
  // sonVeri[sysid].hazirlik sunucudan her telemetri paketinde geliyor;
  // ek WS istegi gerekmez.
  const h = d.hazirlik || {};
  const oto = document.createElement("div");
  let otoSinif = "bilinmiyor", otoIkon = "fa-circle-question";
  let otoBaslik = t.acBilinmiyor || "DURUM BEKLEN\u0130YOR";
  let otoAlt = "";
  if (h.hazir === true) {
    otoSinif = h.uyari > 0 ? "hazir-uyari" : "hazir";
    otoIkon = "fa-circle-check";
    otoBaslik = t.acHazir || "U\u00c7U\u015eA HAZIR";
    otoAlt = h.uyari > 0
      ? ((t.kkOtoUyari || "Otomatik denetim ge\u00e7ti, {n} uyar\u0131 var")
          .replace("{n}", h.uyari))
      : (t.kkOtoTamam || "T\u00fcm otomatik denetimler ge\u00e7ti");
  } else if (h.hazir === false) {
    otoSinif = "hazir-degil";
    otoIkon = "fa-triangle-exclamation";
    otoBaslik = t.acHazirDegil || "HAZIR DE\u011e\u0130L";
    otoAlt = h.sebep || (t.kkOtoKritik ||
      "Otomatik denetimlerden en az biri ba\u015far\u0131s\u0131z");
  }
  oto.className = "kk-oto " + otoSinif;
  oto.innerHTML = "<i class='fa-solid " + otoIkon + "'></i>" +
    "<div class='kk-oto-yazi'><strong>" + kkKacis(otoBaslik) +
    "</strong><span>" + kkKacis(otoAlt) + "</span></div>";
  pop.appendChild(oto);

  // ---- Hedef irtifa seridi ----
  const irtSatir = document.createElement("div");
  irtSatir.className = "kk-irtifa";
  irtSatir.innerHTML = "<span>" +
    kkKacis(t.kkHedefIrtifa || "HEDEF \u0130RT\u0130FA") + "</span><b>" +
    kkKacis(Number(irtifa).toFixed(0)) + " m</b>";
  pop.appendChild(irtSatir);

  // ---- Madde listesi ----
  const icerik = document.createElement("div");
  icerik.className = "kk-icerik";
  const satirlar = [];
  let sonGrup = null;
  maddeler.forEach((m, i) => {
    if (m.grup !== sonGrup) {
      sonGrup = m.grup;
      const bas = document.createElement("div");
      bas.className = "kk-grup-bas";
      bas.innerHTML = "<i class='fa-solid " + kkGrupIkon(m.grup) +
        "'></i> " + kkKacis(kkGrupBaslik(m.grup, tipAd));
      icerik.appendChild(bas);
    }
    const satir = document.createElement("div");
    satir.className = "kk-satir" + (m.zorunlu ? "" : " istege-bagli");
    const orta = document.createElement("div");
    orta.className = "kk-satir-orta";
    orta.innerHTML = "<div class='kk-satir-soru'>" + kkKacis(m.soru) +
      "</div>" + (m.not
        ? "<div class='kk-satir-not'>" + kkKacis(m.not) + "</div>" : "");
    satir.appendChild(orta);

    // Ikili slider: sol yari = HAYIR, sag yari = EVET
    const cevapKutu = document.createElement("div");
    cevapKutu.className = "kk-cevap";
    const tgl = document.createElement("button");
    tgl.type = "button";
    tgl.className = "kk-tgl";
    tgl.setAttribute("role", "switch");
    tgl.setAttribute("aria-checked", "mixed");
    tgl.setAttribute("aria-label", m.soru);
    const yazi = document.createElement("span");
    yazi.className = "kk-cevap-yazi";
    yazi.textContent = "\u2014";

    const durumUygula = (cevap) => {
      // cevap: true(EVET) | false(HAYIR) | null(notr)
      m.cevap = cevap;
      tgl.classList.remove("evet", "hayir");
      yazi.classList.remove("evet", "hayir");
      satir.classList.remove("evet", "hayir");
      if (cevap === true) {
        tgl.classList.add("evet"); yazi.classList.add("evet");
        satir.classList.add("evet");
        yazi.textContent = t.kkEvet || "EVET";
        tgl.setAttribute("aria-checked", "true");
      } else if (cevap === false) {
        tgl.classList.add("hayir"); yazi.classList.add("hayir");
        satir.classList.add("hayir");
        yazi.textContent = t.kkHayir || "HAYIR";
        tgl.setAttribute("aria-checked", "false");
      } else {
        yazi.textContent = "\u2014";
        tgl.setAttribute("aria-checked", "mixed");
      }
      kkDugmeTazele(sysid);
    };
    m.cevap = null;

    tgl.addEventListener("click", (ev) => {
      // Tiklama izin SOL yarisinda ise HAYIR, SAG yarisinda ise EVET.
      // Kullanicinin istegi birebir bu: "sola tiklarsa hayir kirmizi,
      // saga tiklarsa yesil evet".
      const r = tgl.getBoundingClientRect();
      const sag = (ev.clientX - r.left) > (r.width / 2);
      durumUygula(sag);
    });
    tgl.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft") { ev.preventDefault(); durumUygula(false); }
      else if (ev.key === "ArrowRight") { ev.preventDefault(); durumUygula(true); }
      else if (ev.key === " " || ev.key === "Enter") {
        ev.preventDefault(); durumUygula(m.cevap !== true);
      }
    });

    cevapKutu.appendChild(tgl);
    cevapKutu.appendChild(yazi);
    satir.appendChild(cevapKutu);
    icerik.appendChild(satir);
    satirlar.push({madde: m, satir, tgl, yazi, durumUygula});
    void i;
  });
  pop.appendChild(icerik);

  // ---- Alt bar ----
  const altBar = document.createElement("div");
  altBar.className = "kk-alt-bar";
  const sayac = document.createElement("div");
  sayac.className = "kk-sayac";
  const btnIptal = document.createElement("button");
  btnIptal.type = "button";
  btnIptal.className = "kk-btn kk-btn-iptal";
  btnIptal.innerHTML = "<i class='fa-solid fa-xmark'></i> " + "<span>" + (
    (t.kkIptal || "\u0130PTAL")) + "</span>";
  btnIptal.addEventListener("click", () => kalkisKontrolKapat(sysid));
  const btnTamam = document.createElement("button");
  btnTamam.type = "button";
  btnTamam.className = "kk-btn";
  btnTamam.disabled = true;
  btnTamam.innerHTML = "<i class='fa-solid fa-plane-departure'></i> " + "<span>" + (
    (t.kkTamamla || "TAKEOFF'U TAMAMLA")) + "</span>";
  btnTamam.addEventListener("click", () => kkGonder(sysid));
  altBar.appendChild(sayac);
  altBar.appendChild(btnIptal);
  altBar.appendChild(btnTamam);
  pop.appendChild(altBar);

  document.body.appendChild(pop);
  dkPopupOneGetirKur(pop);
  dkMiniPopupKonumla(pop, anka);

  kkPopuplar[sysid] = {
    pop, maddeler, satirlar, btnTamam, sayac,
    irtifa: Number(irtifa), gonderiliyor: false,
  };
  kkDugmeTazele(sysid);
}

// ---------------------------------------------------------------
// "TAKEOFF'U TAMAMLA" dugmesinin durumunu tazele
// TUM zorunlu maddeler EVET olmadan pasif kalir.
// ---------------------------------------------------------------
function kkDugmeTazele(sysid) {
  const P = kkPopuplar[sysid];
  if (!P) return;
  const t = D();
  const zorunlular = P.maddeler.filter(m => m.zorunlu);
  const evet = zorunlular.filter(m => m.cevap === true).length;
  const toplam = zorunlular.length;
  const tamam = (evet === toplam) && toplam > 0;
  P.btnTamam.disabled = !tamam || P.gonderiliyor;
  P.sayac.className = "kk-sayac" + (tamam ? " tamam" : "");
  P.sayac.textContent = (t.kkSayac || "{a} / {b} madde onayland\u0131")
    .replace("{a}", evet).replace("{b}", toplam);
}

// ---------------------------------------------------------------
// Kaydi ve takeoff komutunu SUNUCUYA gonder
// Sunucu once kaydi yazar, YAZAMAZSA takeoff GONDERMEZ.
// ---------------------------------------------------------------
function kkGonder(sysid) {
  const P = kkPopuplar[sysid];
  if (!P || P.gonderiliyor) return;
  if (!(ws && ws.readyState === 1)) {
    if (typeof window.uyariToastGoster === "function") {
      const t = D();
      window.uyariToastGoster({
        baslik: t.kkHataBaslik || "KALKI\u015e KAYDI BA\u015eARISIZ",
        mesaj: t.kkWsYok || "Sunucu ba\u011flant\u0131s\u0131 yok",
        seviye: "hata", sure: 8000,
      });
    }
    return;
  }
  P.gonderiliyor = true;
  kkDugmeTazele(sysid);
  const t = D();
  P.btnTamam.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> " + "<span>" + (
    (t.kkKaydediliyor || "KAYDEDIL\u0130YOR...")) + "</span>";
  ws.send(JSON.stringify({
    tip: "kalkis_kontrol",
    sysid: Number(sysid),
    irtifa: P.irtifa,
    maddeler: P.maddeler.map((m, i) => ({
      sira: i,
      anahtar: m.anahtar,
      soru: m.soru,
      grup: m.grup,
      cevap: m.cevap === true,
      zorunlu: !!m.zorunlu,
      kaynak: m.kaynak,
    })),
  }));
}

// ---------------------------------------------------------------
// Sunucu cevabi
// ---------------------------------------------------------------
window.kalkisKontrolSonucIsle = function (m) {
  const sysid = m && m.sysid;
  const P = kkPopuplar[sysid];
  const t = D();
  if (m && m.basari) {
    // Kayit yazildi ve takeoff komutu sunucu tarafinda gonderildi
    if (P) kalkisKontrolKapat(sysid);
    if (typeof window.uyariToastGoster === "function") {
      window.uyariToastGoster({
        baslik: t.kkKayitTamamBaslik || "KALKI\u015e KAYDI ALINDI",
        mesaj: (t.kkKayitTamam ||
          "Kontrol listesi kay\u0131t alt\u0131na al\u0131nd\u0131, kalk\u0131\u015f komutu " +
          "g\u00f6nderildi."),
        seviye: "bilgi", sure: 5000,
      });
    }
    return;
  }
  // Basarisiz: popup ACIK KALIR, pilot yeniden deneyebilir
  if (P) {
    P.gonderiliyor = false;
    P.btnTamam.innerHTML =
      "<i class='fa-solid fa-plane-departure'></i> " + "<span>" + (
      (t.kkTamamla || "TAKEOFF'U TAMAMLA")) + "</span>";
    kkDugmeTazele(sysid);
  }
  if (typeof window.uyariToastGoster === "function") {
    window.uyariToastGoster({
      baslik: t.kkHataBaslik || "KALKI\u015e KAYDI BA\u015eARISIZ",
      mesaj: (m && m.hata) || (t.kkHataGenel ||
        "Kay\u0131t yaz\u0131lamad\u0131; kalk\u0131\u015f komutu g\u00f6nderilmedi."),
      seviye: "hata", sure: 9000,
    });
  }
};

// ---------------------------------------------------------------
function kalkisKontrolKapat(sysid) {
  const P = kkPopuplar[sysid];
  if (!P) return;
  if (P.pop && P.pop.parentNode) P.pop.parentNode.removeChild(P.pop);
  delete kkPopuplar[sysid];
}

window.kalkisKontrolAc = kalkisKontrolAc;
window.kalkisKontrolKapat = kalkisKontrolKapat;
window.kkMaddeleriUret = kkMaddeleriUret;
