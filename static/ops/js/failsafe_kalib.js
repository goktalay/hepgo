// FAZ18-IS27-28-30: ikon+metin dugmelerinde metin <span> icine
// sarildi. Sebep: dugme_birlik.css yalniz-ikon kurali
// `:has(> i):not(:has(> span))` bu dugmeleri 26px kareye
// zorluyordu ve metin tasiyordu. CSS EZILMEDI; sozlesmeye
// uyuldu. Yalniz-ikon dugmelere DOKUNULMADI.
// =================================================================
// GOKTUNGU - FAILSAFE POPUP + KALIBRASYON POPUP
// Dron menusunden acilir. dronlar.js'deki dkMiniPopup* yardimcilarini
// ve ws param_ara/param_yaz akisini kullanir (klasik script, ortak scope).
// =================================================================

// ---------------------------------------------------------------
// ARAC TIPI ALGILAMA (HEARTBEAT MAV_TYPE -> kategori)
// 1=sabit kanat, 2=quad, 13=hexa, 14=octo, 15=tri, 4=heli,
// 19/20=VTOL... Kategoriler: "kopter", "heli", "plane"
// ---------------------------------------------------------------
function fsAracKategori(sysid) {
  const d = sonVeri[sysid] || {};
  const t = Number(d.arac_tipi || 0);
  if (t === 1) return "plane";                       // sabit kanat
  if (t === 4) return "heli";                        // helikopter
  if ([19, 20, 21, 22, 23, 24, 25].includes(t)) return "plane"; // VTOL -> plane FS
  return "kopter";                                   // quad/hexa/octo/tri/coax
}
function fsAracEtiket(kat) {
  const t = D();
  return kat === "plane" ? (t.fsPlane || "Sabit Kanat")
       : kat === "heli" ? (t.fsHeli || "Helikopter")
       : (t.fsKopter || "Multikopter");
}

// ---------------------------------------------------------------
// FAILSAFE PARAMETRE TANIMLARI
// Her kayit: ad, etiketAnahtari, grup, tip ("secim"|"sayi"), secenekler
// (secim icin deger->etiket), min/max/adim/birim (sayi icin)
// Kaynak: ArduPilot Copter 4.x / Plane 4.x failsafe dokumantasyonu
// ---------------------------------------------------------------
var FS_TANIMLAR = {
  kopter: [
    // --- Radyo (RC) failsafe ---
    { ad: "FS_THR_ENABLE", grup: "radyo", tip: "secim", etk: "fsRcAksiyon",
      sec: {0: "fsSecKapali", 1: "fsSecRtl", 2: "fsSecLandDevam",
            3: "fsSecLand", 4: "fsSecSmartRtl", 5: "fsSecSmartRtlLand",
            6: "fsSecBrakeLand"} },
    { ad: "FS_THR_VALUE", grup: "radyo", tip: "sayi", etk: "fsRcEsik",
      min: 910, max: 1100, adim: 1, birim: "PWM" },
    // --- Batarya failsafe ---
    { ad: "BATT_LOW_VOLT", grup: "batarya", tip: "sayi", etk: "fsBatDusukV",
      min: 0, max: 60, adim: 0.1, birim: "V" },
    { ad: "BATT_FS_LOW_ACT", grup: "batarya", tip: "secim", etk: "fsBatDusukAks",
      sec: {0: "fsSecYok", 1: "fsSecLand", 2: "fsSecRtl", 3: "fsSecSmartRtl",
            4: "fsSecSmartRtlLand", 5: "fsSecTerminate", 6: "fsSecAuto"} },
    { ad: "BATT_CRT_VOLT", grup: "batarya", tip: "sayi", etk: "fsBatKritikV",
      min: 0, max: 60, adim: 0.1, birim: "V" },
    { ad: "BATT_FS_CRT_ACT", grup: "batarya", tip: "secim", etk: "fsBatKritikAks",
      sec: {0: "fsSecYok", 1: "fsSecLand", 2: "fsSecRtl", 3: "fsSecSmartRtl",
            4: "fsSecSmartRtlLand", 5: "fsSecTerminate", 6: "fsSecAuto"} },
    { ad: "BATT_LOW_MAH", grup: "batarya", tip: "sayi", etk: "fsBatDusukMah",
      min: 0, max: 100000, adim: 50, birim: "mAh" },
    // --- GCS failsafe ---
    { ad: "FS_GCS_ENABLE", grup: "gcs", tip: "secim", etk: "fsGcsAksiyon",
      sec: {0: "fsSecKapali", 1: "fsSecRtl", 2: "fsSecLandDevam",
            3: "fsSecSmartRtl", 4: "fsSecSmartRtlLand", 5: "fsSecLand",
            6: "fsSecBrakeLand"} },
    { ad: "FS_GCS_TIMEOUT", grup: "gcs", tip: "sayi", etk: "fsGcsSure",
      min: 1, max: 120, adim: 1, birim: "s" },
    // --- EKF / diger ---
    { ad: "FS_EKF_ACTION", grup: "diger", tip: "secim", etk: "fsEkfAksiyon",
      sec: {1: "fsSecLand", 2: "fsSecAltHold", 3: "fsSecLandGps"} },
    { ad: "FS_EKF_THRESH", grup: "diger", tip: "secim", etk: "fsEkfEsik",
      sec: {"0.6": "fsSecSiki", "0.8": "fsSecVarsayilan", "1.0": "fsSecGevsek"} },
    { ad: "FS_CRASH_CHECK", grup: "diger", tip: "secim", etk: "fsCrash",
      sec: {0: "fsSecKapali", 1: "fsSecAcik"} },
    { ad: "FS_VIBE_ENABLE", grup: "diger", tip: "secim", etk: "fsVibe",
      sec: {0: "fsSecKapali", 1: "fsSecAcik"} },
    { ad: "FS_DR_ENABLE", grup: "diger", tip: "secim", etk: "fsDr",
      sec: {0: "fsSecKapali", 1: "fsSecAcik"} },
    { ad: "RTL_ALT", grup: "diger", tip: "sayi", etk: "fsRtlAlt",
      min: 30, max: 300000, adim: 50, birim: "cm" },
  ],
  plane: [
    // --- Radyo (throttle) failsafe ---
    { ad: "THR_FAILSAFE", grup: "radyo", tip: "secim", etk: "fsRcAksiyon",
      sec: {0: "fsSecKapali", 1: "fsSecAcik", 2: "fsSecYalnizAlgila"} },
    { ad: "THR_FS_VALUE", grup: "radyo", tip: "sayi", etk: "fsRcEsik",
      min: 900, max: 1100, adim: 1, birim: "PWM" },
    { ad: "FS_SHORT_ACTN", grup: "radyo", tip: "secim", etk: "fsKisaAksiyon",
      sec: {0: "fsSecCircleDevam", 1: "fsSecCircle", 2: "fsSecFbwa",
            3: "fsSecDisable", 4: "fsSecFbwb"} },
    { ad: "FS_SHORT_TIMEOUT", grup: "radyo", tip: "sayi", etk: "fsKisaSure",
      min: 1, max: 100, adim: 0.5, birim: "s" },
    { ad: "FS_LONG_ACTN", grup: "radyo", tip: "secim", etk: "fsUzunAksiyon",
      sec: {0: "fsSecDevam", 1: "fsSecRtl", 2: "fsSecGlide", 3: "fsSecParasut"} },
    { ad: "FS_LONG_TIMEOUT", grup: "radyo", tip: "sayi", etk: "fsUzunSure",
      min: 1, max: 300, adim: 0.5, birim: "s" },
    // --- Batarya failsafe ---
    { ad: "BATT_LOW_VOLT", grup: "batarya", tip: "sayi", etk: "fsBatDusukV",
      min: 0, max: 60, adim: 0.1, birim: "V" },
    { ad: "BATT_FS_LOW_ACT", grup: "batarya", tip: "secim", etk: "fsBatDusukAks",
      sec: {0: "fsSecYok", 1: "fsSecRtl", 2: "fsSecLand", 3: "fsSecTerminate",
            4: "fsSecQLand", 6: "fsSecLoiterAlcal"} },
    { ad: "BATT_CRT_VOLT", grup: "batarya", tip: "sayi", etk: "fsBatKritikV",
      min: 0, max: 60, adim: 0.1, birim: "V" },
    { ad: "BATT_FS_CRT_ACT", grup: "batarya", tip: "secim", etk: "fsBatKritikAks",
      sec: {0: "fsSecYok", 1: "fsSecRtl", 2: "fsSecLand", 3: "fsSecTerminate",
            4: "fsSecQLand", 5: "fsSecParasut", 6: "fsSecLoiterAlcal"} },
    { ad: "BATT_LOW_MAH", grup: "batarya", tip: "sayi", etk: "fsBatDusukMah",
      min: 0, max: 100000, adim: 50, birim: "mAh" },
    // --- GCS failsafe ---
    { ad: "FS_GCS_ENABL", grup: "gcs", tip: "secim", etk: "fsGcsAksiyon",
      sec: {0: "fsSecKapali", 1: "fsSecAcik", 2: "fsSecHeartbeatRc",
            3: "fsSecHeartbeatRcAuto"} },
    // --- Diger ---
    { ad: "FS_EKF_THRESH", grup: "diger", tip: "secim", etk: "fsEkfEsik",
      sec: {"0.6": "fsSecSiki", "0.8": "fsSecVarsayilan", "1.0": "fsSecGevsek"} },
    { ad: "RTL_ALTITUDE", grup: "diger", tip: "sayi", etk: "fsRtlAltM",
      min: 0, max: 1000, adim: 5, birim: "m" },
  ],
};
// Helikopter: Copter tabani + rotor hizi kaybi eylemleri farklidir
FS_TANIMLAR.heli = FS_TANIMLAR.kopter;

var FS_GRUPLAR = [
  { id: "radyo", etk: "fsGrupRadyo", ikon: "fa-tower-broadcast" },
  { id: "batarya", etk: "fsGrupBatarya", ikon: "fa-battery-half" },
  { id: "gcs", etk: "fsGrupGcs", ikon: "fa-satellite-dish" },
  { id: "diger", etk: "fsGrupDiger", ikon: "fa-shield-halved" },
];

// Acik failsafe popup'larinin durumlari (sysid -> {pop, alanlar, ...})
var fsPopuplar = {};

// ---------------------------------------------------------------
// FAILSAFE POPUP
// ---------------------------------------------------------------
function dkFailsafePopupAc(anka, sysid) {
  if (dkPopupTekil("dkPopupFailsafe_" + sysid)) return;
  const t = D();
  const kat = fsAracKategori(sysid);
  const tanimlar = FS_TANIMLAR[kat];

  const pop = document.createElement("div");
  pop.id = "dkPopupFailsafe_" + sysid;
  pop.className = "dk-mini-popup fs-popup";
  dkMiniPopupBaslikKur(pop, (t.fsBaslik || "FAILSAFE") + " \u2014 D" + sysid,
    null, "fa-shield-halved");
  pop.addEventListener("remove", () => { delete fsPopuplar[sysid]; });

  // Arac tipi rozeti
  const tipSatir = document.createElement("div");
  tipSatir.className = "fs-tip-satir";
  tipSatir.innerHTML =
    "<i class='fa-solid " + (kat === "plane" ? "fa-plane" :
      kat === "heli" ? "fa-helicopter" : "fa-fan") + "'></i>" +
    "<span>" + fsAracEtiket(kat) + "</span>" +
    "<span class='fs-tip-not'>" + (t.fsTipNot || "Parametre seti ara\u00e7 tipine g\u00f6re") + "</span>";
  pop.appendChild(tipSatir);

  // Icerik: gruplu parametre listesi (once yukleniyor gosterilir)
  const icerik = document.createElement("div");
  icerik.className = "fs-icerik";
  icerik.innerHTML = "<div class='fs-yukleniyor'><i class='fa-solid fa-spinner fa-spin'></i> " +
    (t.fsYukleniyor || "Parametreler drondan okunuyor...") + "</div>";
  pop.appendChild(icerik);

  // Alt bilgi notu
  const not = document.createElement("div");
  not.className = "fs-alt-not";
  not.innerHTML = "<i class='fa-solid fa-circle-info'></i> " +
    (t.fsNot || "De\u011fer de\u011fi\u015fiklikleri an\u0131nda drona yaz\u0131l\u0131r.");
  pop.appendChild(not);

  document.body.appendChild(pop);
  dkPopupOneGetirKur(pop);
  dkMiniPopupKonumla(pop, anka);

  fsPopuplar[sysid] = { pop, icerik, kat, tanimlar, degerler: null,
                        bekleyen: {} };

  // Parametreleri iste (bos filtre = tumu; 5 sn surebilir)
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({tip: "param_ara", sysid: Number(sysid), filtre: ""}));
}

// Param listesi geldiginde (ws.js yonlendirir)
window.dkFailsafeParamGeldi = function(sysid, parametreler) {
  const fs = fsPopuplar[sysid];
  if (!fs || !fs.pop.isConnected) { delete fsPopuplar[sysid]; return; }
  fs.degerler = parametreler;
  fsIcerikCiz(sysid);
};

// Param yazma sonucu geldiginde: ilgili alana basari/hata isle
window.dkFailsafeParamYazildi = function(sysid, ad, deger, basari) {
  const fs = fsPopuplar[sysid];
  if (!fs || !fs.pop.isConnected) return;
  const alan = fs.pop.querySelector("[data-fsparam='" + ad + "']");
  if (!alan) return;
  alan.classList.remove("fs-bekliyor");
  alan.classList.add(basari ? "fs-tamam" : "fs-hata");
  setTimeout(() => alan.classList.remove("fs-tamam", "fs-hata"), 1800);
};

function fsIcerikCiz(sysid) {
  const t = D();
  const fs = fsPopuplar[sysid];
  if (!fs) return;
  const p = fs.degerler || {};
  fs.icerik.innerHTML = "";

  for (const grup of FS_GRUPLAR) {
    const uyeler = fs.tanimlar.filter(x => x.grup === grup.id &&
                                           p[x.ad] !== undefined);
    if (!uyeler.length) continue;
    const gEl = document.createElement("div");
    gEl.className = "fs-grup";
    gEl.innerHTML = "<div class='fs-grup-baslik'><i class='fa-solid " +
      grup.ikon + "'></i><span>" + (t[grup.etk] || grup.id.toUpperCase()) +
      "</span></div>";
    for (const tanim of uyeler) {
      gEl.appendChild(fsAlanOlustur(sysid, tanim, p[tanim.ad]));
    }
    fs.icerik.appendChild(gEl);
  }
  if (!fs.icerik.children.length) {
    fs.icerik.innerHTML = "<div class='fs-yukleniyor'>" +
      (t.fsParamYok || "Failsafe parametresi okunamad\u0131.") + "</div>";
  }
}

function fsAlanOlustur(sysid, tanim, deger) {
  const t = D();
  const satir = document.createElement("div");
  satir.className = "fs-satir";
  satir.dataset.fsparam = tanim.ad;

  const etiket = document.createElement("div");
  etiket.className = "fs-etiket";
  etiket.innerHTML = "<span>" + (t[tanim.etk] || tanim.ad) + "</span>" +
    "<code>" + tanim.ad + "</code>";
  satir.appendChild(etiket);

  const kontrol = document.createElement("div");
  kontrol.className = "fs-kontrol";

  function yaz(yeni) {
    satir.classList.add("fs-bekliyor");
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({tip: "param_yaz", sysid: Number(sysid),
                              ad: tanim.ad, deger: yeni}));
  }

  if (tanim.tip === "secim") {
    const sel = document.createElement("select");
    sel.className = "fs-select";
    let eslesti = false;
    for (const [v, etk] of Object.entries(tanim.sec)) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = t[etk] || etk;
      if (Math.abs(parseFloat(v) - deger) < 0.001) {
        opt.selected = true; eslesti = true;
      }
      sel.appendChild(opt);
    }
    if (!eslesti) {
      // Listede olmayan mevcut deger: ekle ve sec
      const opt = document.createElement("option");
      opt.value = String(deger);
      opt.textContent = String(deger);
      opt.selected = true;
      sel.appendChild(opt);
    }
    sel.addEventListener("change", () => yaz(parseFloat(sel.value)));
    kontrol.appendChild(sel);
  } else {
    const giris = document.createElement("input");
    giris.type = "number";
    giris.className = "fs-sayi";
    giris.min = tanim.min; giris.max = tanim.max; giris.step = tanim.adim;
    // Ondalikli adimda yuvarlama gosterimi
    giris.value = (tanim.adim < 1) ? (+deger).toFixed(1) : Math.round(+deger);
    giris.addEventListener("change", () => {
      let v = parseFloat(String(giris.value).replace(",", "."));
      if (!Number.isFinite(v)) return;
      v = Math.max(tanim.min, Math.min(tanim.max, v));
      giris.value = (tanim.adim < 1) ? v.toFixed(1) : Math.round(v);
      yaz(v);
    });
    kontrol.appendChild(giris);
    if (tanim.birim) {
      const birim = document.createElement("span");
      birim.className = "fs-birim";
      birim.textContent = tanim.birim;
      kontrol.appendChild(birim);
    }
  }
  satir.appendChild(kontrol);
  return satir;
}

// ---------------------------------------------------------------
// KALIBRASYON POPUP
// ---------------------------------------------------------------
var kalibPopuplar = {};   // sysid -> {pop, pusulaBar, pusulaDurum}

function dkKalibPopupAc(anka, sysid) {
  if (dkPopupTekil("dkPopupKalib_" + sysid)) return;
  const t = D();
  const kat = fsAracKategori(sysid);

  const pop = document.createElement("div");
  pop.id = "dkPopupKalib_" + sysid;
  pop.className = "dk-mini-popup kalib-popup";
  dkMiniPopupBaslikKur(pop, (t.kalibBaslik || "KAL\u0130BRASYON") + " \u2014 D" + sysid,
    null, "fa-screwdriver-wrench");

  const govde = document.createElement("div");
  govde.className = "kalib-govde";

  // Kalibrasyon kartlari: ikon, baslik, aciklama, dugme(ler)
  function kart(ikon, baslikYazi, aciklama, dugmeler, uyari) {
    const k = document.createElement("div");
    k.className = "kalib-kart" + (uyari ? " kalib-uyari" : "");
    const solIkon = "<div class='kalib-ikon'><i class='fa-solid " + ikon + "'></i></div>";
    let sag = "<div class='kalib-metin'><div class='kalib-ad'>" + baslikYazi +
      "</div><div class='kalib-acik'>" + aciklama + "</div></div>";
    k.innerHTML = solIkon + sag;
    const btnKutu = document.createElement("div");
    btnKutu.className = "kalib-btnler";
    for (const dg of dugmeler) {
      const b = document.createElement("button");
      b.className = "kalib-btn" + (dg.tur ? " " + dg.tur : "");
      // FAZ18-IS27-ONARIM: uclu islec KORUNUR; metin her iki dalda
      // ayri ayri <span> icine alinir. Onceki yama islecin
      // `?` ve `:` parcalarini ayirip soz dizimini bozmustu.
      b.innerHTML = dg.ikon
        ? "<i class='fa-solid " + dg.ikon + "'></i> "
          + "<span>" + dg.yazi + "</span>"
        : "<span>" + dg.yazi + "</span>";
      b.addEventListener("click", dg.cb);
      btnKutu.appendChild(b);
    }
    k.appendChild(btnKutu);
    govde.appendChild(k);
    return k;
  }

  function komut(aksiyon) {
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({tip: "dron_komut", sysid: Number(sysid),
                              aksiyon: aksiyon}));
  }

  // --- Gyro ---
  kart("fa-rotate", t.kalibGyro || "Gyro (Jiroskop)",
    t.kalibGyroAcik || "Dron sabit ve hareketsizken yap\u0131l\u0131r. Birka\u00e7 saniye s\u00fcrer.",
    [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
      cb: () => onayIste(t.kalibGyroOnay || "Gyro kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? Dron sabit durmal\u0131.",
        () => komut("kalib_gyro"))}]);

  // --- Barometre ---
  kart("fa-gauge", t.kalibBaro || "Barometre",
    t.kalibBaroAcik || "Yer bas\u0131nc\u0131n\u0131 s\u0131f\u0131rlar. Dron yerdeyken yap\u0131l\u0131r.",
    [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
      cb: () => onayIste(t.kalibBaroOnay || "Barometre kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131?",
        () => komut("kalib_baro"))}]);

  // --- Ivmeolcer ---
  kart("fa-cube", t.kalibIvme || "\u0130vme\u00f6l\u00e7er (3D)",
    t.kalibIvmeAcik || "6 y\u00f6nl\u00fc kalibrasyon: Mission Planner benzeri ad\u0131mlar konsoldan izlenir. Dronu s\u0131rayla her y\u00fcz\u00fcne \u00e7evirin.",
    [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
      cb: () => onayIste(t.kalibIvmeOnay || "\u0130vme\u00f6l\u00e7er kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? Y\u00f6nlendirmeler konsola gelir.",
        () => komut("kalib_ivme"))}]);

  // --- Seviye (Level) ---
  kart("fa-ruler-horizontal", t.kalibLevel || "Seviye (Level Trim)",
    t.kalibLevelAcik || "Dron d\u00fcz bir zemindeyken ufuk s\u0131f\u0131rlamas\u0131 yapar.",
    [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
      cb: () => onayIste(t.kalibLevelOnay || "Seviye kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131? Dron d\u00fcz zeminde olmal\u0131.",
        () => komut("kalib_level"))}]);

  // --- Pusula (ilerleme cubuklu) ---
  const pusulaKart = kart("fa-compass", t.kalibPusula || "Pusula (Manyetometre)",
    t.kalibPusulaAcik || "Ba\u015flat\u0131nca dronu havada t\u00fcm eksenlerde d\u00f6nd\u00fcr\u00fcn. \u0130lerleme a\u015fa\u011f\u0131da g\u00f6r\u00fcn\u00fcr.",
    [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-play",
      cb: () => onayIste(t.kalibPusulaOnay || "Pusula kalibrasyonu ba\u015flat\u0131ls\u0131n m\u0131?",
        () => komut("kalib_pusula_baslat"))},
     {yazi: t.kalibKabul || "Kabul", ikon: "fa-check", tur: "iyi",
      cb: () => komut("kalib_pusula_kabul")},
     {yazi: t.kalibIptalBtn || "\u0130ptal", ikon: "fa-xmark", tur: "kotu",
      cb: () => komut("kalib_pusula_iptal")}]);
  // Ilerleme cubugu
  const barKutu = document.createElement("div");
  barKutu.className = "kalib-bar-kutu";
  const bar = document.createElement("div");
  bar.className = "kalib-bar";
  barKutu.appendChild(bar);
  const barYazi = document.createElement("span");
  barYazi.className = "kalib-bar-yazi";
  barYazi.textContent = "";
  barKutu.appendChild(barYazi);
  pusulaKart.appendChild(barKutu);

  // --- ESC (yalniz kopter/heli; tehlikeli) ---
  if (kat !== "plane") {
    kart("fa-bolt", t.kalibEsc || "ESC Kalibrasyonu",
      t.kalibEscAcik || "D\u0130KKAT: Pervaneler \u00e7\u0131kar\u0131lm\u0131\u015f olmal\u0131! Sonraki a\u00e7\u0131l\u0131\u015fta ESC kalibrasyon modu etkinle\u015fir.",
      [{yazi: t.kalibBaslat || "Ba\u015flat", ikon: "fa-triangle-exclamation", tur: "kotu",
        cb: () => onayIste(t.kalibEscOnay || "ESC kalibrasyonu ayarlans\u0131n m\u0131? PERVANELER\u0130 MUTLAKA \u00c7IKARIN!",
          () => komut("kalib_esc"))}], true);
  }

  // Alt not: mesajlar konsola gelir
  const not = document.createElement("div");
  not.className = "fs-alt-not";
  not.innerHTML = "<i class='fa-solid fa-circle-info'></i> " +
    (t.kalibNot || "Kalibrasyon durum mesajlar\u0131 alttaki konsolda g\u00f6r\u00fcn\u00fcr.");

  pop.appendChild(govde);
  pop.appendChild(not);
  document.body.appendChild(pop);
  dkPopupOneGetirKur(pop);
  dkMiniPopupKonumla(pop, anka);

  kalibPopuplar[sysid] = { pop, bar, barYazi };
}

// Pusula kalibrasyon ilerlemesini telemetriden isle (dronlar.js
// varlikGuncelle her telemetri paketinde cagirir)
function kalibTelemetriIsle(d) {
  const kp = kalibPopuplar[d.sysid];
  if (!kp) return;
  if (!kp.pop.isConnected) { delete kalibPopuplar[d.sysid]; return; }
  const t = D();
  if (d.magkal_durum === "suruyor") {
    const pct = Math.max(0, Math.min(100, d.magkal_pct || 0));
    kp.bar.style.width = pct + "%";
    kp.bar.style.background = "var(--interceptor)";
    kp.barYazi.textContent = (t.kalibSuruyor || "S\u00fcr\u00fcyor") + " %" + pct;
  } else if (d.magkal_durum === "basarili") {
    kp.bar.style.width = "100%";
    kp.bar.style.background = "var(--iyi)";
    kp.barYazi.textContent = t.kalibBasarili || "BA\u015eARILI";
  } else if (d.magkal_durum === "basarisiz") {
    kp.bar.style.width = "100%";
    kp.bar.style.background = "var(--kotu)";
    kp.barYazi.textContent = t.kalibBasarisiz || "BA\u015eARISIZ";
  }
}
