// FAZ18-IS27-28-30: ikon+metin dugmelerinde metin <span> icine
// sarildi. Sebep: dugme_birlik.css yalniz-ikon kurali
// `:has(> i):not(:has(> span))` bu dugmeleri 26px kareye
// zorluyordu ve metin tasiyordu. CSS EZILMEDI; sozlesmeye
// uyuldu. Yalniz-ikon dugmelere DOKUNULMADI.
// =================================================================
// GOKTUNGU - ARM CHECK (KALKIS HAZIRLIK DENETIMI)  [v2.4.19]
// - Dron kartinin en ustundeki "UCUSA HAZIR" rozetini gunceller
// - Rozete tiklaninca ARM CHECK panelini acar: sensor sagligi, EKF,
//   GPS, batarya, titresim, otopilot prearm sonucu + dronun bildirdigi
//   hata mesajlari (STATUSTEXT) ayri sekmede
// dronlar.js'deki dkMiniPopup* yardimcilarini kullanir (ortak scope).
// =================================================================

// Acik ARM CHECK panelleri: sysid -> {pop, ...}
var acPopuplar = {};

// ---------------------------------------------------------------
// KART USTU "UCUSA HAZIR" ROZETI
// ---------------------------------------------------------------
function dkHazirRozetTazele(rozet, d) {
  const t = D();
  const h = d.hazirlik || {};
  const bagli = !!d.baglanti;
  let sinif, ikon, metin, ipucu;

  if (!bagli) {
    sinif = "kopuk";
    ikon = "fa-plug-circle-xmark";
    metin = t.acKopuk || "BA\u011eLANTI YOK";
    ipucu = t.acKopukIpucu || "Telemetri ba\u011flant\u0131s\u0131 kesik";
  } else if (d.armed) {
    sinif = "ucusta";
    ikon = "fa-plane-up";
    metin = t.acUcusta || "ARM \u2014 U\u00c7U\u015eTA";
    ipucu = t.acUcustaIpucu ||
      "Ara\u00e7 ARM durumda; denetim ayr\u0131nt\u0131lar\u0131 i\u00e7in t\u0131klay\u0131n";
  } else if (h.hazir === true) {
    // v2.4.35: Ucusa hazir olan arac HER ZAMAN yesil zeminde gorunur.
    // Onceki surumde tek bir uyari maddesi bile rozeti turuncuya
    // ('hazir-uyari') cevirdigi icin kalkisa hazir dron "sorunlu"
    // izlenimi veriyordu. Uyari, kalkisi engellemeyen bilgidir:
    // engelleyen maddeler kritik sayilir ve hazir=false yapar.
    // Bu yuzden uyari artik ZEMIN RENGIYLE degil, rozetin sagindaki
    // kucuk uyari isaretiyle ve ipucu metniyle bildirilir.
    sinif = h.uyari > 0 ? "hazir hazir-uyarili" : "hazir";
    ikon = "fa-circle-check";
    metin = t.acHazir || "U\u00c7U\u015eA HAZIR";
    ipucu = h.uyari > 0
      ? (t.acHazirUyari || "Kalk\u0131\u015fa haz\u0131r, ancak uyar\u0131lar var")
      : (t.acHazirIpucu || "T\u00fcm kalk\u0131\u015f denetimleri ge\u00e7ti");
  } else if (h.hazir === false) {
    sinif = "hazir-degil";
    ikon = "fa-triangle-exclamation";
    metin = t.acHazirDegil || "HAZIR DE\u011e\u0130L";
    ipucu = h.sebep || (t.acHazirDegilIpucu ||
      "Kalk\u0131\u015f denetimlerinden en az biri ba\u015far\u0131s\u0131z");
  } else {
    sinif = "bilinmiyor";
    ikon = "fa-circle-question";
    metin = t.acBilinmiyor || "DURUM BEKLEN\u0130YOR";
    ipucu = t.acBilinmiyorIpucu ||
      "Ara\u00e7 hen\u00fcz durum bilgisi bildirmedi";
  }

  // v2.4.23: rozette YALNIZ durum metni kalir. Kritik/uyari sayaclari
  // kaldirildi (dugme %50 genislige indi); ayrintilar ARM CHECK
  // panelinde ve ipucu metninde sunulur.
  const sayacMetin = bagli && !d.armed
    ? ((h.kritik ? h.kritik + " \u2716" : "") +
       (h.kritik && h.uyari ? " " : "") +
       (h.uyari ? h.uyari + " \u26a0" : ""))
    : "";

  // v2.4.35: Yesil zeminde uyari varsa kucuk amber ucgen gosterilir.
  // Zemin rengi "ucabilir mi?" sorusunu, bu isaret "dikkat edilecek
  // birsey var mi?" sorusunu yanitlar; ikisi ayri bilgidir.
  const uyariIsareti = (h.hazir === true && h.uyari > 0)
    ? "<i class='fa-solid fa-triangle-exclamation dk-hazir-uyari-im'></i>"
    : "";

  const imza = sinif + "|" + metin + "|" + (uyariIsareti ? "u" : "");
  if (rozet._imza !== imza) {
    rozet._imza = imza;
    rozet.className = "dk-hazir-rozet " + sinif;
    rozet.innerHTML =
      "<i class='fa-solid " + ikon + " dk-hazir-ikon'></i>" +
      "<span class='dk-hazir-metin'>" + metin + "</span>" +
      uyariIsareti +
      "<i class='fa-solid fa-chevron-right dk-hazir-ok'></i>";
  }
  const tamIpucu = ipucu + (sayacMetin ? "  [" + sayacMetin + "]" : "") +
    " \u2014 " +
    (t.acRozetTikla || "ayr\u0131nt\u0131lar i\u00e7in t\u0131klay\u0131n");
  if (rozet.title !== tamIpucu) rozet.title = tamIpucu;

  // v2.4.36: ayni durumu KART BASLIGININ cerceve rengine de tasi.
  // Kartlar varsayilan olarak KATLI gelir; rozet govdenin icinde
  // oldugu icin kart kapaliyken hazirlik durumu hic gorunmuyordu.
  // Basligin cercevesi kapali kartta da gorundugu icin operator
  // panelleri acmadan tek bakista hangi aracin ucabilecegini gorur.
  // Durum siniflari rozetle AYNI (hazir / hazir-degil / ucusta /
  // kopuk / bilinmiyor) tutulur; boylece renk sozlugu tek yerde
  // tanimli kalir ve iki gosterge birbirinden ayrisamaz.
  dkBaslikDurumTazele(rozet, sinif, metin, ipucu);
}

// ---------------------------------------------------------------
// v2.4.36: KART BASLIGI DURUM CERCEVESI
// ---------------------------------------------------------------
// Rozetin hesapladigi durum sinifini basliga aktarir. Rozet kart
// govdesinin icinde oldugu icin bu fonksiyon basligi rozetten
// yukari dogru arar (kart kokune cikip .dron-kart-baslik bulur);
// boylece dronlar.js'de ayrica referans tasimaya gerek kalmaz ve
// kartin hem gomulu hem ayrik kipinde ayni sekilde calisir.
function dkBaslikDurumTazele(rozet, sinif, metin, ipucu) {
  if (!rozet) return;
  let baslik = rozet._baslikRef;
  if (!baslik || !baslik.isConnected) {
    const kok = rozet.closest(".dron-kart");
    if (!kok) return;
    baslik = kok.querySelector(".dron-kart-baslik");
    if (!baslik) return;
    rozet._baslikRef = baslik;
  }
  // "hazir hazir-uyarili" gibi bilesik siniflar bosluktan bolunur.
  const durumlar = String(sinif).split(/\s+/).filter(Boolean);
  const yeniImza = durumlar.join(" ");
  if (baslik._durumImza === yeniImza) return;
  // Onceki durum siniflarini temizle: baslikta takip-mor/kapali gibi
  // ILGISIZ siniflar da var, bu yuzden yalnizca bilinen durum
  // adlarini kaldiriyoruz (hepsini silmek katlama durumunu bozar).
  DK_BASLIK_DURUMLARI.forEach((s) => baslik.classList.remove("dkd-" + s));
  durumlar.forEach((s) => {
    if (DK_BASLIK_DURUMLARI.indexOf(s) >= 0) baslik.classList.add("dkd-" + s);
  });
  baslik._durumImza = yeniImza;
  // Kart kapaliyken baslikta ayri bir durum metni yoktur; cerceve
  // rengi sessiz bir gostergedir. Ipucu, rengin ne anlama geldigini
  // yazili olarak da verir (renk korlugu ve cok dronlu panellerde).
  const bIpucu = metin + " \u2014 " + ipucu;
  if (baslik.title !== bIpucu) baslik.title = bIpucu;
}

// Basliga uygulanabilen durum adlari (dkd- onekiyle sinifa cevrilir)
const DK_BASLIK_DURUMLARI = [
  "hazir", "hazir-uyarili", "hazir-degil", "ucusta", "kopuk", "bilinmiyor"
];

// ---------------------------------------------------------------
// ARM CHECK PANELI
// ---------------------------------------------------------------
function dkArmCheckPopupAc(sysid, anka) {
  const kimlik = "dkPopupArmCheck_" + sysid;
  const eski = dkPopupTekil(kimlik);
  if (eski) { dkArmCheckIste(sysid); return; }
  const t = D();

  const pop = document.createElement("div");
  pop.id = kimlik;
  pop.className = "dk-mini-popup ac-popup";
  dkMiniPopupBaslikKur(pop, (t.acBaslik || "ARM CHECK") + " \u2014 D" + sysid,
    null, "fa-clipboard-check");

  // Ozet seridi (buyuk durum bandi)
  const ozet = document.createElement("div");
  ozet.className = "ac-ozet bilinmiyor";
  ozet.innerHTML = "<i class='fa-solid fa-circle-question'></i>" +
    "<div class='ac-ozet-yazi'><strong>" +
    (t.acBilinmiyor || "DURUM BEKLEN\u0130YOR") + "</strong><span></span></div>";
  pop.appendChild(ozet);

  // Sekmeler: DENETIM | MESAJLAR | PARAMETRELER
  const sekmeBar = document.createElement("div");
  sekmeBar.className = "ac-sekme-bar";
  const sekmeler = [
    ["denetim", t.acSekmeDenetim || "Denetim", "fa-clipboard-check"],
    ["mesaj", t.acSekmeMesaj || "Mesajlar", "fa-comment-dots"],
    ["param", t.acSekmeParam || "Parametreler", "fa-sliders"],
  ];
  const sekmeEl = {};
  sekmeler.forEach(([id, ad, ikon], i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ac-sekme" + (i === 0 ? " aktif" : "");
    b.innerHTML = "<i class='fa-solid " + ikon + "'></i> " + ad +
      "<span class='ac-sekme-sayac'></span>";
    b.addEventListener("click", () => acSekmeSec(sysid, id));
    sekmeEl[id] = b;
    sekmeBar.appendChild(b);
  });
  pop.appendChild(sekmeBar);

  // Icerik alanlari
  const icerik = document.createElement("div");
  icerik.className = "ac-icerik";
  icerik.innerHTML = "<div class='ac-yukleniyor'>" +
    "<i class='fa-solid fa-spinner fa-spin'></i> " +
    (t.acYukleniyor || "Hazırlık raporu alınıyor...") + "</div>";
  pop.appendChild(icerik);

  // Alt bar: yenile + mesajlari temizle
  const altBar = document.createElement("div");
  altBar.className = "ac-alt-bar";
  const btnYenile = document.createElement("button");
  btnYenile.type = "button";
  btnYenile.className = "ac-alt-btn";
  btnYenile.innerHTML = "<i class='fa-solid fa-rotate'></i> " + "<span>" + (
    (t.acYenile || "YEN\u0130LE")) + "</span>";
  btnYenile.addEventListener("click", () => dkArmCheckIste(sysid));
  const btnTemizle = document.createElement("button");
  btnTemizle.type = "button";
  btnTemizle.className = "ac-alt-btn ac-alt-btn-ikincil";
  btnTemizle.innerHTML = "<i class='fa-solid fa-eraser'></i> " + "<span>" + (
    (t.acMesajTemizle || "MESAJLARI TEM\u0130ZLE")) + "</span>";
  btnTemizle.addEventListener("click", () => {
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({tip: "dron_mesaj_temizle",
                              sysid: Number(sysid)}));
  });
  altBar.appendChild(btnTemizle);
  altBar.appendChild(btnYenile);
  pop.appendChild(altBar);

  document.body.appendChild(pop);
  dkPopupOneGetirKur(pop);
  dkMiniPopupKonumla(pop, anka);

  acPopuplar[sysid] = { pop, ozet, icerik, sekmeEl, sekme: "denetim",
                        rapor: null, mesajlar: [] };
  dkArmCheckIste(sysid);

  // Panel acikken 3 sn'de bir tazele
  const zaman = setInterval(() => {
    if (!pop.isConnected) { clearInterval(zaman); delete acPopuplar[sysid];
                            return; }
    dkArmCheckIste(sysid);
  }, 3000);
}

function dkArmCheckIste(sysid) {
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({tip: "arm_check", sysid: Number(sysid)}));
}

function acSekmeSec(sysid, id) {
  const ac = acPopuplar[sysid];
  if (!ac) return;
  ac.sekme = id;
  Object.keys(ac.sekmeEl).forEach((k) =>
    ac.sekmeEl[k].classList.toggle("aktif", k === id));
  acIcerikCiz(sysid);
}

// ws.js -> arm_check_rapor
window.dkArmCheckRaporGeldi = function(m) {
  const ac = acPopuplar[m.sysid];
  if (!ac || !ac.pop.isConnected) { delete acPopuplar[m.sysid]; return; }
  ac.rapor = m;
  ac.mesajlar = m.mesajlar || [];
  acOzetCiz(m.sysid);
  acIcerikCiz(m.sysid);
};

// ws.js -> dron_mesaj_listesi (temizleme sonrasi)
window.dkDronMesajlariGeldi = function(sysid, mesajlar) {
  const ac = acPopuplar[sysid];
  if (!ac || !ac.pop.isConnected) return;
  ac.mesajlar = mesajlar || [];
  if (ac.rapor) ac.rapor.mesajlar = ac.mesajlar;
  acIcerikCiz(sysid);
};

function acOzetCiz(sysid) {
  const ac = acPopuplar[sysid];
  if (!ac || !ac.rapor) return;
  const t = D();
  const r = ac.rapor;
  const o = r.ozet || {};
  let sinif, ikon, bas, alt;
  if (r.armed) {
    sinif = "ucusta"; ikon = "fa-plane-up";
    bas = t.acUcusta || "ARM \u2014 U\u00c7U\u015eTA";
    alt = (t.acMod || "Mod") + ": " + (r.mod || "?");
  } else if (o.hazir === true) {
    // v2.4.35: kart rozetiyle TUTARLI olsun: hazir arac yesil zeminde
    // gorunur, uyari kenarlik + amber ucgenle bildirilir. Panel ile
    // rozet farkli renk gosterirse operator hangisine guvenecegini
    // bilemez.
    sinif = o.uyari > 0 ? "hazir hazir-uyarili" : "hazir";
    ikon = "fa-circle-check";
    bas = t.acHazir || "U\u00c7U\u015eA HAZIR";
    alt = o.uyari > 0
      ? (o.uyari + " " + (t.acUyariAdet || "uyar\u0131") +
         (o.sebep ? " \u2014 " + o.sebep : ""))
      : (t.acTumDenetimGecti || "T\u00fcm denetimler ge\u00e7ti");
  } else if (o.hazir === false) {
    sinif = "hazir-degil"; ikon = "fa-triangle-exclamation";
    bas = t.acHazirDegil || "HAZIR DE\u011e\u0130L";
    alt = (o.kritik || 0) + " " + (t.acKritikAdet || "kritik bulgu") +
      (o.sebep ? " \u2014 " + o.sebep : "");
  } else {
    sinif = "bilinmiyor"; ikon = "fa-circle-question";
    bas = t.acBilinmiyor || "DURUM BEKLEN\u0130YOR";
    alt = t.acBilinmiyorIpucu ||
      "Ara\u00e7 hen\u00fcz durum bilgisi bildirmedi";
  }
  ac.ozet.className = "ac-ozet " + sinif;
  ac.ozet.innerHTML = "<i class='fa-solid " + ikon + "'></i>" +
    "<div class='ac-ozet-yazi'><strong>" + bas + "</strong>" +
    "<span>" + alt + "</span></div>";
  // Sekme sayaclari
  const kritik = (o.kritik || 0) + (o.uyari || 0);
  const s1 = ac.sekmeEl.denetim.querySelector(".ac-sekme-sayac");
  if (s1) {
    s1.textContent = kritik ? String(kritik) : "";
    s1.className = "ac-sekme-sayac" + (o.kritik ? " kritik" : "");
  }
  const hataMesaj = (ac.mesajlar || []).filter((x) => x.sev <= 4).length;
  const s2 = ac.sekmeEl.mesaj.querySelector(".ac-sekme-sayac");
  if (s2) {
    s2.textContent = hataMesaj ? String(hataMesaj) : "";
    s2.className = "ac-sekme-sayac" + (hataMesaj ? " kritik" : "");
  }
}

const AC_GRUP_ADLARI = {
  prearm: ["acGrupPrearm", "Otopilot \u00d6n Kontrol\u00fc", "fa-shield-halved"],
  sensor: ["acGrupSensor", "Sens\u00f6r Sa\u011fl\u0131\u011f\u0131", "fa-microchip"],
  konum: ["acGrupKonum", "Konum \u00c7\u00f6z\u00fcm\u00fc", "fa-satellite"],
  guc: ["acGrupGuc", "G\u00fc\u00e7 Sistemi", "fa-battery-half"],
  rc: ["acGrupRc", "Kumanda", "fa-gamepad"],
};

const AC_DURUM_GORSEL = {
  tamam: ["fa-circle-check", "tamam"],
  uyari: ["fa-triangle-exclamation", "uyari"],
  hata: ["fa-circle-xmark", "hata"],
  bilinmiyor: ["fa-circle-minus", "bilinmiyor"],
};

function acIcerikCiz(sysid) {
  const ac = acPopuplar[sysid];
  if (!ac) return;
  const t = D();
  const r = ac.rapor;
  ac.icerik.innerHTML = "";
  if (!r) {
    ac.icerik.innerHTML = "<div class='ac-yukleniyor'>" +
      "<i class='fa-solid fa-spinner fa-spin'></i> " +
      (t.acYukleniyor || "Hazırlık raporu alınıyor...") + "</div>";
    return;
  }
  if (!r.bulundu) {
    ac.icerik.innerHTML = "<div class='ac-bos'>" +
      (t.acDronYok || "Dron telemetrisi yok.") + "</div>";
    return;
  }

  if (ac.sekme === "denetim") return acDenetimCiz(sysid);
  if (ac.sekme === "mesaj") return acMesajCiz(sysid);
  return acParamCiz(sysid);
}

function acDenetimCiz(sysid) {
  const ac = acPopuplar[sysid];
  const t = D();
  const maddeler = (ac.rapor.maddeler || []);
  // Gruplara ayir; her grup icinde hata > uyari > bilinmiyor > tamam
  const sira = { hata: 0, uyari: 1, bilinmiyor: 2, tamam: 3 };
  const gruplar = {};
  maddeler.forEach((m) => {
    (gruplar[m.grup] = gruplar[m.grup] || []).push(m);
  });
  Object.keys(AC_GRUP_ADLARI).forEach((g) => {
    const liste = gruplar[g];
    if (!liste || !liste.length) return;
    // v2.4.42: backend maddelere istege bagli `oncelik` verir (kucuk
    // deger one gelir; belirtilmeyen maddeler 50 sayilir). Oncelik
    // DURUM SIRASINDAN ONCE uygulanir: HOME maddesi (oncelik 0) durumu
    // "tamam" olsa bile grubun basinda kalir, boylece operator her
    // acilista ayni yerde bulur. Ayni oncelikteki maddeler eskiden
    // oldugu gibi hata > uyari > bilinmiyor > tamam sirasina girer.
    liste.sort((a, b) => {
      const oa = (a.oncelik === undefined || a.oncelik === null)
        ? 50 : Number(a.oncelik);
      const ob = (b.oncelik === undefined || b.oncelik === null)
        ? 50 : Number(b.oncelik);
      if (oa !== ob) return oa - ob;
      return (sira[a.durum] - sira[b.durum]);
    });
    const [anah, varsayilan, ikon] = AC_GRUP_ADLARI[g];
    const bas = document.createElement("div");
    bas.className = "ac-grup-bas";
    bas.innerHTML = "<i class='fa-solid " + ikon + "'></i> " +
      (t[anah] || varsayilan);
    ac.icerik.appendChild(bas);
    liste.forEach((m) => {
      const [dIkon, dSinif] = AC_DURUM_GORSEL[m.durum] ||
        AC_DURUM_GORSEL.bilinmiyor;
      const satir = document.createElement("div");
      satir.className = "ac-satir " + dSinif;
      satir.innerHTML =
        "<i class='fa-solid " + dIkon + " ac-satir-ikon'></i>" +
        "<div class='ac-satir-orta'>" +
        "<span class='ac-satir-ad'>" + acKacis(m.ad) + "</span>" +
        (m.mesaj ? "<span class='ac-satir-mesaj'>" + acKacis(m.mesaj) +
                   "</span>" : "") +
        "</div>" +
        "<span class='ac-satir-deger'>" + acKacis(m.deger || "") + "</span>";
      ac.icerik.appendChild(satir);
    });
  });
}

function acMesajCiz(sysid) {
  const ac = acPopuplar[sysid];
  const t = D();
  const liste = ac.mesajlar || [];
  if (!liste.length) {
    ac.icerik.innerHTML = "<div class='ac-bos'><i class='fa-solid " +
      "fa-comment-slash'></i> " +
      (t.acMesajYok || "Dron hen\u00fcz bir mesaj bildirmedi.") + "</div>";
    return;
  }
  // MAV_SEVERITY: 0 acil, 1 uyari(alert), 2 kritik, 3 hata, 4 uyari,
  // 5 dikkat, 6 bilgi, 7 hata ayiklama
  const sevBilgi = (s) => {
    if (s <= 2) return ["acil", "fa-circle-radiation",
                        t.acSevAcil || "AC\u0130L"];
    if (s === 3) return ["hata", "fa-circle-xmark", t.acSevHata || "HATA"];
    if (s === 4) return ["uyari", "fa-triangle-exclamation",
                         t.acSevUyari || "UYARI"];
    if (s === 5) return ["dikkat", "fa-circle-exclamation",
                         t.acSevDikkat || "D\u0130KKAT"];
    return ["bilgi", "fa-circle-info", t.acSevBilgi || "B\u0130LG\u0130"];
  };
  liste.forEach((m) => {
    const [sinif, ikon, etiket] = sevBilgi(Number(m.sev));
    const satir = document.createElement("div");
    satir.className = "ac-mesaj " + sinif;
    const saat = new Date((m.ts || 0) * 1000).toLocaleTimeString();
    satir.innerHTML =
      "<i class='fa-solid " + ikon + " ac-mesaj-ikon'></i>" +
      "<div class='ac-mesaj-orta'>" +
      "<span class='ac-mesaj-metin'>" + acKacis(m.metin || "") +
      (m.tekrar > 1 ? " <span class='ac-mesaj-tekrar'>\u00d7" +
                      m.tekrar + "</span>" : "") + "</span>" +
      "<span class='ac-mesaj-alt'>" + etiket + " \u00b7 " + saat +
      "</span></div>";
    ac.icerik.appendChild(satir);
  });
}

function acParamCiz(sysid) {
  const ac = acPopuplar[sysid];
  const t = D();
  const liste = ac.rapor.parametreler || [];
  if (!liste.length) {
    const kutu = document.createElement("div");
    kutu.className = "ac-bos";
    kutu.innerHTML = "<i class='fa-solid fa-circle-info'></i> " +
      (t.acParamYok ||
       "Parametre \u00f6nbelle\u011fi bo\u015f. Parametreler penceresinden " +
       "<b>T\u00dcM\u00dcN\u00dc AL</b> ile drondan okuyun.");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ac-alt-btn";
    btn.style.marginTop = "10px";
    btn.innerHTML = "<i class='fa-solid fa-sliders'></i> " + "<span>" + (
      (t.dkParametreler || "Parametreler")) + "</span>";
    btn.addEventListener("click", () => {
      if (typeof dkParamPopupAc === "function") dkParamPopupAc(sysid);
    });
    kutu.appendChild(document.createElement("br"));
    kutu.appendChild(btn);
    ac.icerik.appendChild(kutu);
    return;
  }
  const bas = document.createElement("div");
  bas.className = "ac-grup-bas";
  bas.innerHTML = "<i class='fa-solid fa-sliders'></i> " +
    (t.acParamBaslik || "Kalk\u0131\u015f Parametreleri");
  ac.icerik.appendChild(bas);
  liste.forEach((p) => {
    const satir = document.createElement("div");
    satir.className = "ac-param";
    // v2.4.19: sayisal degerin gercek anlami (values/bitmask metadata)
    const anlam = (typeof paramDegerAnlami === "function")
      ? paramDegerAnlami(p.ad, p.deger, sysid) : "";
    satir.innerHTML =
      "<div class='ac-param-sol'>" +
      "<span class='ac-param-ad'>" + acKacis(p.ad) + "</span>" +
      "<span class='ac-param-aciklama'>" + acKacis(p.aciklama || "") +
      "</span></div>" +
      "<div class='ac-param-sag'>" +
      "<span class='ac-param-deger'>" + acSayi(p.deger) + "</span>" +
      (anlam ? "<span class='ac-param-anlam'>" + acKacis(anlam) +
               "</span>" : "") + "</div>";
    satir.addEventListener("click", () => {
      if (typeof dkParamDuzenlePopup === "function") {
        // Parametre popup'i acik olmasa da duzenleme calisir
        if (typeof _paramPopupSysid !== "undefined" && !_paramPopupSysid)
          _paramPopupSysid = sysid;
        dkParamDuzenlePopup(sysid, p.ad, p.deger);
      }
    });
    ac.icerik.appendChild(satir);
  });
}

function acSayi(v) {
  const n = parseFloat(v);
  if (!isFinite(n)) return String(v);
  return String(Number(n.toFixed(4)));
}

function acKacis(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;");
}

window.dkArmCheckPopupAc = dkArmCheckPopupAc;
window.dkHazirRozetTazele = dkHazirRozetTazele;
window.dkBaslikDurumTazele = dkBaslikDurumTazele;
