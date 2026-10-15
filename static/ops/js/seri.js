// =================================================================
// GOKTUNGU - BAGLANTI YONETICISI (eski: DRON ALICISI / seri panel)
// Kayitli MAVLink baglantilari (seri / tcp / udp): listeleme,
// ekleme diyaloglari, play/stop dinleme kontrolu.
// NOT: `ws` globali bu dosyada tanimlidir; ws.js ve digerleri kullanir.
// =================================================================
let ws = null;
let seriBagli = false;   // en az bir baglanti "bagli" ise true (footer/GCS)

// --- Durum ---
let bagKayitlar = [];    // [{id, isim, tur, port, baud?, host?}]
let bagDurumlar = {};    // {id: {durum, hata}}
let bagEkleTur = "seri"; // acik diyalogdaki baglanti turu
let bagDuzenleId = null; // v2.4.12: duzenlenen kayit id (null = yeni)

// --- Elemanlar ---
const bagListe    = document.getElementById("bagListe");
const bagYok      = document.getElementById("bagYok");
const bagPerde    = document.getElementById("bagEklePerde");
const bagBaslik   = document.getElementById("bagEkleBaslik");
const bagAd       = document.getElementById("bagAd");
const bagPortSec  = document.getElementById("bagPortSec");
const bagPortElle = document.getElementById("bagPortElle");
const bagBaud     = document.getElementById("bagBaud");
const bagHost     = document.getElementById("bagHost");
const bagTcpPort  = document.getElementById("bagTcpPort");
const bagUdpPort  = document.getElementById("bagUdpPort");
const bagHata     = document.getElementById("bagEkleHata");
const bagUcusYazilimiAlan = document.getElementById("bagUcusYazilimiAlan");
const bagUcusYazilimi = document.getElementById("bagUcusYazilimi");
const bagUcusYazilimiAciklama = document.getElementById("bagUcusYazilimiAciklama");

// v2.4.142: DJI disinda secici HER baglanti turunde gorunur. MSP v1
// ilk surumu sadece fiziksel seri/VCP portu icin sinirlidir; UI kuralin
// aciklamasini yapar, sunucu ayni kombinasyonu bagimsiz olarak reddeder.
function bagUcusYazilimiGuncelle(tur, kayit){
  if (!bagUcusYazilimi || !bagUcusYazilimiAlan) return;
  const t = D();
  const dji = tur === "dji";
  const seri = tur === "seri";
  if (dji){
    bagUcusYazilimiAlan.style.display = "none";
    bagUcusYazilimi.value = "ardupilot";
    return;
  }
  bagUcusYazilimiAlan.style.display = "";
  const deger = String((kayit && kayit.ucus_yazilimi) ||
    (seri ? "otomatik" : "ardupilot")).toLowerCase();
  // Eski ya da bozuk kayit formu kapanmaz; eski kayitlar ArduPilot olarak
  // korunur. Yeni fiziksel seri kayitlarda RFD900/MAVLink/MSP algilamasi
  // varsayilandir; DJI disindaki dji degeri kayit hatasidir.
  bagUcusYazilimi.value = (seri && deger === "otomatik") ? "otomatik"
    : (deger === "betaflight" ? "betaflight" : "ardupilot");
  const bfSecenek = Array.from(bagUcusYazilimi.options)
    .find(o => o.value === "betaflight");
  const otoSecenek = Array.from(bagUcusYazilimi.options)
    .find(o => o.value === "otomatik");
  if (bfSecenek) bfSecenek.disabled = !seri;
  if (otoSecenek) otoSecenek.disabled = !seri;
  if (!seri && (bagUcusYazilimi.value === "betaflight" ||
                bagUcusYazilimi.value === "otomatik"))
    bagUcusYazilimi.value = "ardupilot";
  bagUcusYazilimi.disabled = !seri;
  if (bagUcusYazilimiAciklama){
    bagUcusYazilimiAciklama.textContent = seri
      ? (bagUcusYazilimi.value === "otomatik"
          ? (t.bagUcusOtomatikAciklama ||
             "RFD900 seri bağlantısında önce MAVLink Heartbeat dinlenir; bulunamazsa yalnız MSP API sürümü sorgulanır. Algılanan protokol dışındaki sürücü portu açmaz.")
          : (bagUcusYazilimi.value === "betaflight"
              ? (t.bagUcusBetaflightAciklama ||
                 "Betaflight yalnız MSP seri/VCP üzerinden salt-okunur tanılama ve telemetri sorguları yapar. Yazma, ARM, motor, RC, yeniden başlatma ve CLI kapalıdır.")
              : (t.bagUcusArduAciklama ||
                 "ArduPilot bağlantıları mevcut MAVLink işlevleriyle çalışır.")))
      : (t.bagUcusYalnizSeri ||
         "Betaflight MSP ilk sürümde yalnız seri/VCP bağlantısında desteklenir; bu bağlantı ArduPilot MAVLink olarak kaydedilir.");
  }
}

function bagUcusYazilimiDegisti(){
  if (!bagUcusYazilimi || bagEkleTur !== "seri") return;
  const t = D();
  if (bagUcusYazilimi.value === "betaflight"){
    // Yeni kayitta yaygin MSP varsayimi 115200'dur. Var olan kayitta
    // kullanicinin ayarladigi baud degeri dokunulmaz.
    if (bagDuzenleId == null && String(bagBaud.value) === "57600")
      bagBaud.value = "115200";
  }
  bagUcusYazilimiGuncelle(bagEkleTur, {
    ucus_yazilimi: bagUcusYazilimi.value
  });
}
// v2.4.55: baglantinin hangi KOPRU makinesinde kurulacagi secimi.
const bagKopruAlan = document.getElementById("bagKopruAlan");
const bagKopruSec  = document.getElementById("bagKopruSec");

// Merkezde mi calisiyoruz? Sunucu `kopru_liste` yanitinda bildirir.
// Baslangicta bilinmez kabul edilir; ilk yanitla kesinlesir.
let bagMerkezKipi = false;

// Kopru seciciyi doldurur. Yalniz CEVRIMICI kopruler listelenir:
// cevrimdisi bir makineye baglanti tanimlamak, pilotun play'e basip
// nedensiz hata almasi demektir.
// `secili` verilirse (duzenleme) o kopru onseçili gelir; kayitli kopru
// o an cevrimdisiysa listeye "(cevrimdisi)" etiketiyle EKLENIR, aksi
// halde kullanici yalnizca adi degistirmek isterken kaydin makinesini
// sessizce kaybederdi.
// v2.4.56: govde ORTAK hale getirildi. Ayni secim uc formda gerekiyor
// (baglanti, AI sunucusu, kamera); mantik kopyalanirsa biri duzeltilip
// digeri unutulur. `alan` gizlenecek sarmalayici, `sec` <select>.
window.kopruSeciciDoldur = function(alan, secEl, secili, urunSuzgeci){
  if (!secEl) return;
  const t = D();
  const sec = (secili == null) ? "" : String(secili);
  secEl.innerHTML = "";
  const acik = (bagKopruler || []).filter(k => k.cevrimici &&
    (typeof urunSuzgeci !== "function" || urunSuzgeci(k)));
  // 2.4.238 (kullanici istegi): yerel kipte (GRCOFF) de secici gorunur.
  // Varsayilan "Merkez baglantisi (bu bilgisayar)" = koprusuz; Destek >
  // Kopruler'de tanimli kopruler varsa onlar da secilebilir. Merkez
  // kipinde varsayilan secenek YOKTUR (kopru zorunlu).
  if (alan) alan.style.display = "";
  if (!bagMerkezKipi){
    const o0 = document.createElement("option");
    o0.value = "";
    o0.textContent = t.bagKopruYerel || "Merkez ba\u011flant\u0131s\u0131 (bu bilgisayar, k\u00f6pr\u00fcs\u00fcz)";
    secEl.appendChild(o0);
  } else if (!acik.length){
    const o = document.createElement("option");
    o.value = "";
    o.textContent = t.bagKopruYok || "\u00c7evrimi\u00e7i k\u00f6pr\u00fc yok";
    secEl.appendChild(o);
  }
  for (const k of acik){
    const o = document.createElement("option");
    o.value = String(k.ornek_id);
    const yer = k.ip ? (" \u2014 " + k.ip) : "";
    o.textContent = (k.ad || ("#" + k.ornek_id)) + yer;
    secEl.appendChild(o);
  }
  if (sec && !acik.some(k => String(k.ornek_id) === sec)){
    const eskiK = (bagKopruler || [])
      .find(k => String(k.ornek_id) === sec);
    const o = document.createElement("option");
    o.value = sec;
    o.textContent = (eskiK && eskiK.ad ? eskiK.ad : ("#" + sec)) +
      " \u2014 " + (t.bagKopruCevrimdisi || "\u00e7evrimd\u0131\u015f\u0131");
    secEl.appendChild(o);
  }
  if (sec) secEl.value = sec;
};

function bagKopruSeciciDoldur(secili){
  // Baglanti Yoneticisi (seri/tcp/udp/dji) telemetri koprusu ister;
  // GORUNTU koprusu (urun=video) telemetri iletisimi saglamaz, listede
  // gosterilmez (kullanici bildirimi 2026-09).
  window.kopruSeciciDoldur(bagKopruAlan, bagKopruSec, secili,
    (k) => String((k && k.urun) || "kopru").toLowerCase() !== "video");
}

// Kopru adini kimlikten cozer. AI/kamera gruplarinin basliginda
// kullanilir; liste bayatsa "#12" gibi kimlik gosterilir ki kayit
// gorunmez olmasin.
window.kopruAdCoz = function(ornekId){
  const k = (bagKopruler || [])
    .find(x => String(x.ornek_id) === String(ornekId));
  if (!k) return null;
  return k;
};

const fSeri = document.getElementById("fSeri");

// ---------------------------------------------------------------
// Seri port listesi (diyalogdaki dropdown)
// ---------------------------------------------------------------
function portlariDoldur(portlar){
  const onceki = bagPortSec.value;
  bagPortSec.innerHTML = "";
  if (!portlar || !portlar.length){
    const o = document.createElement("option");
    o.value = ""; o.textContent = D().portBulunamadi;
    bagPortSec.appendChild(o);
    return;
  }
  for (const p of portlar){
    const o = document.createElement("option");
    o.value = p.port;
    o.textContent = p.aciklama ? `${p.port} \u2014 ${p.aciklama}` : p.port;
    bagPortSec.appendChild(o);
  }
  if (onceki) bagPortSec.value = onceki;
}

// ---------------------------------------------------------------
// Ekleme diyalogu
// ---------------------------------------------------------------
function bagDialogAc(tur, kayit){
  // 2.4.240: merkezde yeni seri/tcp/udp/dji kaydi yalniz cevrimici kopru varken.
  if (!kayit && tur !== "sanal" && tur !== "merkez" &&
      typeof window.kopruYeniKayitIzni === "function" && !window.kopruYeniKayitIzni("baglanti")) return;
  bagEkleTur = tur;
  bagDuzenleId = kayit ? kayit.id : null;
  const t = D();
  const basliklar = {seri: t.bagYeniSeri, tcp: t.bagYeniTcp,
                     udp: t.bagYeniUdp, dji: t.bagYeniDji,
                     sanal: t.bagYeniSanal, merkez: t.bagYeniMerkez};
  const duzBasliklar = {seri: t.bagDuzenleSeri, tcp: t.bagDuzenleTcp,
                        udp: t.bagDuzenleUdp, dji: t.bagDuzenleDji,
                        sanal: t.bagDuzenleSanal,
                        merkez: t.bagDuzenleMerkez};
  bagBaslik.textContent = (kayit ? duzBasliklar[tur] : basliklar[tur])
                          || t.bagYeniSeri;
  document.querySelectorAll(".bag-tur-alan").forEach(el => {
    el.style.display = el.classList.contains("bag-tur-" + tur) ? "" : "none";
  });
  bagAd.value = kayit ? (kayit.isim || "") : "";
  bagPortElle.value = "";
  bagUcusYazilimiGuncelle(tur, kayit);
  // v2.4.37: onceki duzenlemede eklenmis gecici baud secenekleri temizlenir,
  // yoksa dialog her acilista listeye bir kopya daha birikir.
  Array.from(bagBaud.querySelectorAll("option[data-gecici]"))
       .forEach(o => o.remove());
  // v2.4.12: duzenleme modunda mevcut degerleri forma doldur
  if (kayit){
    if (tur === "seri"){
      bagPortElle.value = kayit.port || "";
      // v2.4.37: kayitli baud listede yoksa <select>.value ataması
      // SESSIZCE bosa duser ve form ilk secenegi (9600) gosterir; kullanici
      // farkinda olmadan kaydederse baglanti hizi bozulur. Bu yuzden
      // bilinmeyen deger listeye gecici secenek olarak eklenir. Boyle bir
      // deger, listenin daraltildigi eski surumlerden ya da elle duzenlenmis
      // veritabani kaydindan gelebilir.
      const baudStr = String(kayit.baud || 57600);
      if (!Array.from(bagBaud.options).some(o => o.value === baudStr)){
        const ek = document.createElement("option");
        ek.value = baudStr;
        ek.textContent = baudStr;
        ek.dataset.gecici = "1";
        bagBaud.appendChild(ek);
      }
      bagBaud.value = baudStr;
    } else if (tur === "tcp"){
      bagHost.value = kayit.host || "";
      bagTcpPort.value = kayit.port || "";
    } else if (tur === "dji"){
      document.getElementById("bagDjiPort").value = kayit.port || "8790";
    } else if (tur === "sanal"){
      // Duzenleme modunda kayitli tip/konum/adet forma yazilir. Bu dal
      // olmadan alanlar bos acilir ve kullanici yalnizca adi degistirmek
      // isterken konumu SIFIRLAR — v2.4.37'de baud alaninda duzelttigimiz
      // sessiz veri kaybinin aynisi.
      const p = bagSanalCoz(kayit);
      document.getElementById("bagSanalTip").value =
        (p && p.tip) || "multirotor";
      document.getElementById("bagSanalEnlem").value =
        (p && isFinite(p.lat)) ? p.lat.toFixed(6) : "";
      document.getElementById("bagSanalBoylam").value =
        (p && isFinite(p.lon)) ? p.lon.toFixed(6) : "";
      document.getElementById("bagSanalAdet").value = (p && p.adet) || 1;
    } else if (tur === "merkez"){
      // v2.4.53: duzenleme modunda sunucu listesi yine merkezden
      // tazelenir (asagida). Kayitli sunucu O AN kapali olabilir; bu
      // durumda listede yer almaz ve kullanici baska sunucu secmek
      // zorundadir. Kayitli sunucunun adi durum satirinda gosterilir,
      // yoksa kullanici neyi duzenledigini goremez.
      const p = (typeof bagMerkezCoz === "function")
        ? bagMerkezCoz(kayit) : null;
      if (p && p.uid && typeof merkezDurumYaz === "function")
        merkezDurumYaz((t.merkezKayitliSunucu || "Kayıtlı sunucu") +
                       ": " + (p.ad || p.uid), "uyari");
    } else {
      bagUdpPort.value = kayit.port || "";
    }
  }
  // v2.4.39: SANAL — konum alanlari haritanin O ANKI merkezinden
  // doldurulur. Kullanici "haritanin konumu neresi ise orada sanal dron
  // baslatsin" dedi; degerler yine de gorunur ve duzenlenebilir olmali,
  // yoksa dronun nerede dogacagi kullanici icin gorunmez olur.
  // v2.4.53: MERKEZ turunde liste her acilista merkezden tazelenir.
  // Onbellege alinmaz: "acik sunucu" bilgisi saniyeler icinde degisir
  // ve bayat liste kullaniciyi kapali bir sunucuyu secmeye goturur.
  if (tur === "merkez" && typeof merkezSunucuListesiYenile === "function")
    merkezSunucuListesiYenile();
  if (tur === "sanal" && !kayit){
    const m = bagHaritaMerkezi();
    document.getElementById("bagSanalEnlem").value = m ? m.lat.toFixed(6) : "";
    document.getElementById("bagSanalBoylam").value = m ? m.lon.toFixed(6) : "";
    if (!bagAd.value)
      bagAd.value = t.bagSanalVarsayilanAd || "Sanal Dron";
  }
  // v2.4.55: kopru secimi. `sanal` ve `merkez` turlerinde gizlenir:
  // sanal dron surecini merkez kendisi calistirir, `merkez` turu ise
  // hedef makineyi kendi alaninda zaten soruyor. Diger turlerde
  // (seri/tcp/udp/dji) baglanti bir SAHA makinesinde kurulur.
  const kopruGerek = (tur !== "sanal" && tur !== "merkez");
  if (kopruGerek){
    bagKopruSeciciDoldur(kayit ? kayit.kopru_ornek_id : null);
    // Liste bayat olabilir (kopru bu arada acilmis/kapanmis olabilir);
    // her acilista merkezden tazelenir. Yanit gelince secici yeniden
    // doldurulur (bagKopruListesiGuncelle icinde).
    if (typeof bagKopruListesiIste === "function") bagKopruListesiIste();
  } else if (bagKopruAlan){
    bagKopruAlan.style.display = "none";
  }
  bagHata.style.display = "none";
  bagPerde.classList.remove("popup-gizli");
  if (tur === "seri" && ws && ws.readyState === 1)
    ws.send(JSON.stringify({tip:"portlar"}));
  setTimeout(() => bagAd.focus(), 50);
  // FAZ18-SIHIRBAZ: SANAL turunde (yeni kayit) uc adimli
  // sihirbaz devreye girer. Sihirbaz mevcut girdileri
  // GIZLI TASIYICI olarak kullanir; bagKaydet() govdesi
  // degismedigi icin kaydetme sozlesmesi bozulmaz.
  if (typeof window.sitlSihirbazAc === "function"){
    try { window.sitlSihirbazAc(tur, kayit); }
    catch (e) {
      // FAZ18-IS34-KAPSAM: sihirbaz kusuru diyalogu dusurmez, ama
      // TAMAMEN sessiz de kalmaz. Sessiz yutma, sihirbazin panel
      // icine kuruldugu kusurunun gunlerce teshis edilememesine
      // yol acti.
      try { console.warn("[SITL-SIHIRBAZ] acilis kusuru:", e && e.message ? e.message : e); } catch (e2) {}
    }
  }
}

if (bagUcusYazilimi)
  bagUcusYazilimi.addEventListener("change", bagUcusYazilimiDegisti);

function bagDialogKapat(){
  bagPerde.classList.add("popup-gizli");
}

function bagEkleHataGoster(mesaj){
  bagHata.textContent = mesaj;
  bagHata.style.display = "block";
}

function bagKaydet(){
  if (!ws || ws.readyState !== 1) return;
  // FAZ18-SIHIRBAZ: sihirbaz `window.ws` uzerinden gonderir.
  try { window.ws = ws; } catch (e) {}
  const t = D();
  const isim = bagAd.value.trim();
  if (!isim){ bagEkleHataGoster(t.bagAdUyari); return; }
  const k = bagDuzenleId != null
    ? {tip:"baglanti_guncelle", id:bagDuzenleId, isim:isim}
    : {tip:"baglanti_ekle", isim:isim, tur:bagEkleTur};
  // DJI'de secici gizlidir ve sunucu `dji` degerini kendisi zorlar.
  // Diger tum turlerde alan gonderilir; desteklenmeyen Betaflight
  // kombinasyonlari yine de sunucuda reddedilir.
  if (bagEkleTur !== "dji" && bagUcusYazilimi)
    k.ucus_yazilimi = bagUcusYazilimi.value || "ardupilot";
  if (bagEkleTur === "seri"){
    const port = bagPortElle.value.trim() || bagPortSec.value;
    if (!port){ bagEkleHataGoster(t.portSecUyari); return; }
    k.port = port;
    k.baud = parseInt(bagBaud.value, 10) || 57600;
  } else if (bagEkleTur === "tcp"){
    const host = bagHost.value.trim();
    const port = parseInt(bagTcpPort.value, 10);
    if (!host){ bagEkleHataGoster(t.bagHostUyari); return; }
    if (!port || port < 1 || port > 65535){
      bagEkleHataGoster(t.bagPortUyari); return;
    }
    k.host = host; k.port = String(port);
  } else if (bagEkleTur === "dji"){
    const port = parseInt(document.getElementById("bagDjiPort").value, 10);
    if (!port || port < 1 || port > 65535){
      bagEkleHataGoster(t.bagPortUyari); return;
    }
    k.port = String(port);
  } else if (bagEkleTur === "sanal"){
    // v2.4.39: sanal dronun portu YOK; sunucu simulatoru dahili olarak
    // calistirir. Tasinan bilgi: dron tipi, adet ve baslangic konumu.
    const lat = parseFloat(document.getElementById("bagSanalEnlem").value);
    const lon = parseFloat(document.getElementById("bagSanalBoylam").value);
    if (!isFinite(lat) || lat < -90 || lat > 90 ||
        !isFinite(lon) || lon < -180 || lon > 180){
      bagEkleHataGoster(t.bagSanalKonumUyari ||
        "Ge\u00e7erli enlem/boylam girin."); return;
    }
    let adet = parseInt(document.getElementById("bagSanalAdet").value, 10);
    if (!adet || adet < 1) adet = 1;
    if (adet > 10) adet = 10;
    k.sanal_tip = document.getElementById("bagSanalTip").value;
    k.sanal_adet = adet;
    k.sanal_lat = lat;
    k.sanal_lon = lon;
  } else if (bagEkleTur === "merkez"){
    // v2.4.53: kullaniciya IP/port sorulmaz; tasinan bilgi merkezden
    // secilen sunucunun kimligidir.
    const alan = (typeof merkezKayitAlanlari === "function")
      ? merkezKayitAlanlari() : {hata: "merkez_baglanti.js yuklenmedi"};
    if (alan.hata){ bagEkleHataGoster(alan.hata); return; }
    k.merkez_uid = alan.merkez_uid;
    k.merkez_ad = alan.merkez_ad;
    k.merkez_firma = alan.merkez_firma;
  } else { // udp
    const port = parseInt(bagUdpPort.value, 10);
    if (!port || port < 1 || port > 65535){
      bagEkleHataGoster(t.bagPortUyari); return;
    }
    k.port = String(port);
  }
  // v2.4.55: baglantinin kurulacagi KOPRU makinesi. Merkez kipinde
  // ZORUNLUDUR: kopru secilmezse baglanti merkez sunucunun kendi
  // makinesinde acilmaya calisilir ve `127.0.0.1` gibi adresler orada
  // bos oldugu icin "Connection refused" verir. Kullanicinin bildirdigi
  // kusur tam olarak buydu.
  if (bagEkleTur !== "sanal" && bagEkleTur !== "merkez"){
    const kid = bagKopruSec ? String(bagKopruSec.value || "") : "";
    if (bagMerkezKipi && !kid){
      bagEkleHataGoster(t.bagKopruUyari ||
        "Ba\u011flant\u0131n\u0131n kurulaca\u011f\u0131 makineyi se\u00e7in.");
      return;
    }
    // Bos dize DEGIL null gonderilir: sunucu "" degerini de None'a
    // ceviriyor, ancak niyeti acikca tasimak sonraki okuyucu icin
    // daha az surpriz uretir.
    k.kopru_ornek_id = kid ? parseInt(kid, 10) : null;
  }
  // FAZ18-SIHIRBAZ: otomatik baslatma niyeti gonderiden
  // ONCE kurulur; kimlik tahmin edilmez, listede beliren
  // yeni kayit fark alinarak bulunur.
  if (bagEkleTur === "sanal" && bagDuzenleId == null &&
      typeof window.sitlSihirbazKaydediliyor === "function"){
    try { window.sitlSihirbazKaydediliyor(); } catch (e) {}
  }
  ws.send(JSON.stringify(k));
  bagDialogKapat();
}

// ---------------------------------------------------------------
// Baglanti listesi cizimi
// ---------------------------------------------------------------
function bagTurEtiket(tur){
  return {seri:"SER\u0130", tcp:"TCP", udp:"UDP", dji:"DJI",
          sanal:"SANAL", merkez:"MERKEZ"}[tur]
         || tur.toUpperCase();
}

function bagAltMetin(b){
  if (b.tur === "seri") return b.port + " @ " + (b.baud || 57600);
  if (b.tur === "tcp")  return b.host + ":" + b.port;
  if (b.tur === "dji")  return "DJI K\u00f6pr\u00fc TCP :" + b.port;
  // v2.4.39: sanal baglantinin portu yok; ayirt edici bilgi dron tipi
  // ve baslangic konumudur. Bunlar `host` alaninda saklanir (bkz.
  // baglantilar.py: sanal turu icin host = "tip|lat|lon|adet").
  if (b.tur === "sanal") return bagSanalOzet(b);
  // v2.4.53: merkez baglantisinin portu yoktur; ayirt edici bilgi
  // secilen sunucunun adi ve firmasidir (host = "uid|ad|firma").
  if (b.tur === "merkez")
    return (typeof bagMerkezOzet === "function")
      ? bagMerkezOzet(b) : (b.host || "Merkez");
  return "UDP :" + b.port;
}

// v2.4.142: Betaflight MSP verisi MAVLink telemetrisi değildir. Bu
// özet yalnız izinli, salt-okunur tanı alanlarını görüntüler; komut,
// arm, motor, RC ve yapılandırma denetimleri için arayüz üretmez.
function bagBetaflightOzet(b, s){
  const yazilim = String((s && s.algilanan_ucus_yazilimi) ||
    (b && b.ucus_yazilimi) || "").toLowerCase();
  if (yazilim !== "betaflight") return "";
  const t = D();
  const bilgi = (s && s.bilgi) || {};
  const parcalar = [t.bagBfSaltOkunur || "MSP · salt-okunur tanılama"];
  const varyant = bilgi["2"] || {};
  const surum = bilgi["3"] || {};
  const kart = bilgi["4"] || {};
  const tutum = bilgi["108"] || {};
  const batarya = bilgi["130"] || bilgi["110"] || {};
  if (varyant.fc_turu) parcalar.push(varyant.fc_turu);
  if (surum.fc_surumu) parcalar.push("v" + surum.fc_surumu);
  if (kart.kart) parcalar.push(kart.kart);
  if (tutum.tutum && isFinite(tutum.tutum.heading_deg))
    parcalar.push("HDG " + Math.round(tutum.tutum.heading_deg) + "°");
  if (isFinite(batarya.gerilim_v))
    parcalar.push(batarya.gerilim_v.toFixed(1) + " V");
  if (s && Number(s.yanit_sayisi) > 0)
    parcalar.push(String(s.yanit_sayisi) + " " +
                  (t.bagBfYanit || "yanıt"));
  if (s && s.hata) parcalar.push(s.hata);
  return parcalar.join(" · ");
}

function bagOtomatikAlgilamaOzetEkle(b, s, bilgi){
  if (String((b && b.ucus_yazilimi) || "").toLowerCase() !== "otomatik") return;
  const t = D();
  const protokol = String((s && s.algilanan_ucus_yazilimi) || "").toLowerCase();
  const satir = document.createElement("div");
  satir.className = "bag-alt bag-otomatik-algilama";
  if (protokol === "ardupilot" || protokol === "betaflight") {
    const ad = protokol === "ardupilot" ? "ArduPilot (MAVLink)" : "Betaflight (MSP)";
    const kanit = String((s && s.algilama_kaniti) || "").replace(/_/g, " ");
    satir.textContent = (t.bagOtomatikAlgilandi || "Otomatik algılandı") + ": " + ad +
      (kanit ? " · " + kanit : "");
  } else {
    satir.textContent = t.bagOtomatikBekliyor || "Otomatik protokol algılama başlatıldığında sonuç burada görünür.";
  }
  bilgi.appendChild(satir);
}

function bagBetaflightOzetEkle(b, s, bilgi){
  bagOtomatikAlgilamaOzetEkle(b, s, bilgi);
  const ozet = bagBetaflightOzet(b, s);
  if (!ozet) return;
  const satir = document.createElement("div");
  satir.className = "bag-alt bag-betaflight-ozet";
  satir.textContent = ozet;
  bilgi.appendChild(satir);
}

// v2.4.39: sanal baglanti kaydinin okunabilir ozeti.
function bagSanalOzet(b){
  const t = D();
  const p = bagSanalCoz(b);
  if (!p) return t.sanalTipMultirotor || "Sanal";
  const tipAd = {multirotor: t.sanalTipMultirotor || "Multirotor",
                 sabit_kanat: t.sanalTipSabitKanat || "Sabit Kanat",
                 interceptor: t.sanalTipInterceptor || "Interceptor"
                }[p.tip] || p.tip;
  const konum = (isFinite(p.lat) && isFinite(p.lon))
    ? (p.lat.toFixed(4) + ", " + p.lon.toFixed(4)) : "";
  const adet = p.adet > 1 ? (" \u00d7" + p.adet) : "";
  return tipAd + adet + (konum ? " \u2014 " + konum : "");
}

// "tip|lat|lon|adet" dizesini ayristirir. Bicim bozuksa null doner;
// cagirici varsayilana duser (kart yine de gorunur kalir).
function bagSanalCoz(b){
  const h = String((b && b.host) || "");
  if (!h) return null;
  const par = h.split("|");
  if (par.length < 3) return null;
  const lat = parseFloat(par[1]), lon = parseFloat(par[2]);
  const adet = parseInt(par[3], 10) || 1;
  return {tip: par[0] || "multirotor", lat: lat, lon: lon, adet: adet};
}

// v2.4.39: haritanin o anki merkezini dondurur ({lat, lon}) ya da null.
// Cesium viewer'a dogrudan bagimlilik kurulmaz: harita katmani kendi
// yardimcisini window uzerinde yayinliyorsa o kullanilir, yoksa MERKEZ
// KONUM panelindeki degerlere, en son da ayar dosyasi konumuna dusulur.
function bagHaritaMerkezi(){
  if (typeof window.haritaMerkezi === "function"){
    const m = window.haritaMerkezi();
    if (m && isFinite(m.lat) && isFinite(m.lon)) return m;
  }
  const eEl = document.getElementById("inpEnlem");
  const bEl = document.getElementById("inpBoylam");
  if (eEl && bEl){
    const lat = parseFloat(eEl.value), lon = parseFloat(bEl.value);
    if (isFinite(lat) && isFinite(lon)) return {lat: lat, lon: lon};
  }
  return null;
}

// ---------------------------------------------------------------
// v2.4.39: SITL ikilisi indirme akisi
//
// Sanal dron gercek bir ArduPilot SITL surecidir; ~30 MB'lik ikili
// dosyaya ihtiyac duyar. Bu dosya guncelleme paketine GOMULEMEZ
// (paket 100-300 KB olmak zorunda), bu yuzden kullanici istegiyle
// indirilir. Ikili yoksa sunucu "SITL ikilisi bulunamadi" hatasi
// dondurur; o hatayi celiskisiz bir eyleme cevirmek gerekir, yoksa
// kullanicinin elinde cozumu olmayan bir hata metni kalir.
// ---------------------------------------------------------------
function bagSitlIndirmeGerekli(hata){
  return /SITL ikilisi bulunamadi/i.test(String(hata || ""));
}

function bagSitlIndirDugmesiEkle(){
  if (document.getElementById("bagSitlIndirBtn")) return;
  const t = D();
  const btn = document.createElement("button");
  btn.id = "bagSitlIndirBtn";
  btn.className = "btn-kucuk";
  btn.style.cssText = "margin-top:8px";
  btn.textContent = t.bagSitlIndir || "SITL dosyas\u0131n\u0131 indir";
  btn.addEventListener("click", () => {
    if (!ws || ws.readyState !== 1) return;
    const tip = document.getElementById("bagSanalTip").value || "multirotor";
    btn.disabled = true;
    ws.send(JSON.stringify({tip: "sitl_indir", sanal_tip: tip}));
  });
  bagHata.appendChild(document.createElement("br"));
  bagHata.appendChild(btn);
}

// ws.js -> sitl_indirme mesajlarini karsilar.
window.sitlIndirmeDurum = function(m){
  const t = D();
  const btn = document.getElementById("bagSitlIndirBtn");
  if (m.durum === "basladi"){
    bagPerde.classList.remove("popup-gizli");
    bagEkleHataGoster(t.bagSitlIndiriliyor ||
      "SITL dosyas\u0131 indiriliyor (~30 MB), bekleyin\u2026");
    if (btn) btn.disabled = true;
    return;
  }
  if (m.durum === "bitti"){
    bagEkleHataGoster(t.bagSitlHazir ||
      "SITL dosyas\u0131 hazir. Sanal ba\u011flant\u0131y\u0131 ba\u015flat\u0131n.");
    if (btn) btn.remove();
    return;
  }
  // hata
  bagEkleHataGoster(m.hata || (t.bagSitlIndirHata || "SITL indirilemedi."));
  if (btn) btn.disabled = false;
};

// ---------------------------------------------------------------
// v2.4.32: BIRLESIK AGAC — baglanti + altinda dronlari
//
// Baglanti Yoneticisi artik dron kartlarinin da sahibidir. Her
// baglanti bir GRUP basligidir; o baglantidan gelen dronlarin
// kartlari grubun govdesinde yasar.
//
// KRITIK: bagListeCiz() her cagrisinda innerHTML sifirlanir. Dron
// kartlari YENIDEN URETILMEZ — appendChild mevcut DOM dugumunu
// TASIR. Boylece jquery-flight-indicators gostergeleri, kartin
// acik/kapali durumu, telemetri kaydirma konumu ve joystick durumu
// korunur. Kart yeniden uretilirse gostergeler kaybolur.
// ---------------------------------------------------------------

// Katlanmis grup kimlikleri. bagListeCiz() DOM'u her seferinde
// yeniden kurdugu icin katlama durumu DOM'da degil burada yasar,
// aksi halde her telemetri paketinde gruplar kendiliginden acilirdi.
const bagKatlanmis = new Set();

// baglanti_id gelmeyen dronlarin toplandigi yalitim grubu anahtari.
// Dron ucuran bir sistemde kartin panelden kaybolmasi kabul
// edilemez; eski sunucu, DJI yolu veya yaris durumunda kimlik
// bilinmese bile dron mutlaka gorunur kalir.
const BAG_BILINMEYEN = "__bilinmeyen__";
// v2.4.45: tum SANAL (SITL) kayitlarini barindiran tek ust grup anahtari
const BAG_SANAL = "__sanal__";
// v2.4.53 Faz 7: her KOPRU (saha makinesi) bir ust grup acar. Grup
// anahtari `__kopru__<ornek_id>` bicimindedir. Kullanici istegi:
// "dron baglanti yoneticisinde sisteme baglanan kullanicilarin
// uygulamalari altinda gruplanacak" + "bu gruplama ayni zamanda ai ve
// video icin de gecerli olacak".
const BAG_KOPRU_ONEK = "__kopru__";
function bagKopruAnahtar(ornekId){ return BAG_KOPRU_ONEK + String(ornekId); }
// Kopru servis seridi sirasi. FAZ19-IS73: video/AI katmani
// sistemden soküldu (kopru 1.7.9 artik 3 servis bildirir).
// Kalan servisler: Dron, GroundGCC, Radar. Sira panel sol
// menusuyle AYNI tutulur.
// Merkezden gelen kopru listesi: [{ornek_id, ad, ip, cevrimici,
// surum, platform, servisler:[{ad,durum,...}], ...}]
let bagKopruler = [];
// Kopru listesi periyodik tazelenir; zamanlayici tek olmalidir.
let bagKopruZaman = null;
const BAG_KOPRU_ARALIK_MS = 30000;

// Merkezden gelen kopru listesini uygula. Liste hem Baglanti
// Yoneticisi gruplarini hem de Radar / Yer Kontrol Istasyonu Dual
// menulerinin gorunurlugunu besler (Faz 8).
function bagKopruListesiGuncelle(m){
  const yeni = Array.isArray(m && m.kopruler) ? m.kopruler : [];
  const eski = JSON.stringify(bagKopruler);
  bagKopruler = yeni;
  // v2.4.55: merkez kipi sunucudan bildirilir (bkz. sunucu.py kopru_liste).
  if (m && typeof m.merkez_kipi === "boolean") bagMerkezKipi = m.merkez_kipi;
  if (m && m.hata)
    console.warn("[KOPRU] liste hatasi:", m.hata);
  // Diyalog ACIKKEN liste gelirse secici tazelenir; aksi halde
  // kullanici diyalogu acar, listeyi bos gorur ve kaydedemez.
  if (bagPerde && !bagPerde.classList.contains("popup-gizli") &&
      bagEkleTur !== "sanal" && bagEkleTur !== "merkez"){
    const secili = bagKopruSec ? (bagKopruSec.value || null) : null;
    bagKopruSeciciDoldur(secili);
  }
  if (JSON.stringify(bagKopruler) !== eski){
    bagListeCiz();
    bagOzetGuncelle();
  }
  // Menu gorunurlugu her yanitta degerlendirilir: liste ayni kalsa
  // bile menu baska bir sebeple (dil degisimi, panel yeniden cizimi)
  // sifirlanmis olabilir.
  if (typeof window.kopruServisMenuleriGuncelle === "function")
    window.kopruServisMenuleriGuncelle(bagKopruler, bagMerkezKipi);
  // v2.4.56: AI ve kamera panelleri de kopru gruplamasi kullanir.
  // Liste ayni kalsa bile cagrilir: panel yeni acilmis olabilir.
  _kopruDinleyicileriCagir();
}
window.bagKopruListesiGuncelle = bagKopruListesiGuncelle;

// ------------------------------------------------------------------
// v2.4.56 — ORTAK KOPRU ERISIMI
// Kopru listesi tek yerde tutulur (bu dosya), fakat artik UC panel
// kullanir: Baglanti Yoneticisi, AI Sunuculari ve Kameralar. Her panel
// kendi listesini merkezden ayrica istemez; ayni depoyu okur. Aksi
// halde uc ayri zamanlayici, uc ayri "kopru cevrimdisi oldu" gecikmesi
// ve birbiriyle celisen gorunumler olusur.
//
// KOPYA dondurur: cagiran panelin listeyi degistirmesi depoyu
// bozmamalidir.
window.kopruListesiAl = function(){
  return (bagKopruler || []).slice();
};

// Merkezde mi calisiyoruz. Kopru secimi ve gruplama YALNIZ merkezde
// anlamlidir; lokal kurulumda her sey programin kendi makinesindedir.
window.kopruMerkezKipiMi = function(){
  return !!bagMerkezKipi;
};
// 2.4.240 (kullanici: "GRCON'da yeni kayit girerken mutlaka kopru sorsun;
// sistemde cevrimici kopru yoksa yeni kayit ekrani hic acilmadan uyari
// versin; Radar, Elektro Optik, Dron, Kamera"): merkez kipinde yeni kayit
// formu yalniz en az bir CEVRIMICI kopru varken acilir. Yerel kipte (GRCOFF)
// kisit yok. Sanal dron istisnadir (cagiran taraf bu islevi cagirmaz).
window.kopruYeniKayitIzni = function(kategori){
  if (!bagMerkezKipi) return true;
  if ((bagKopruler || []).some(k => k && k.cevrimici)) return true;
  const t = D();
  if (typeof window.uyariToastGoster === "function")
    window.uyariToastGoster({baslik: t.kopruYokBaslik || "Çevrimiçi köprü yok",
                             mesaj: t.kopruYokUyari || "Yeni kayıt için önce bir köprü bağlanmalı.",
                             seviye: "uyari", sure: 6000, kategori: kategori || "kopru"});
  if (typeof bagKopruListesiIste === "function") bagKopruListesiIste();
  return false;
};

// Kopru listesi degistiginde haber verilecek dinleyiciler. AI ve kamera
// panelleri acikken kopru cevrimdisi olursa gorunumleri tazelenmelidir.
const _kopruDinleyiciler = [];
window.kopruListesiDinle = function(f){
  if (typeof f === "function") _kopruDinleyiciler.push(f);
};
function _kopruDinleyicileriCagir(){
  for (const f of _kopruDinleyiciler){
    // Bir dinleyicinin hatasi digerlerini engellememeli.
    try { f(); } catch(e){ console.warn("[KOPRU] dinleyici hatasi:", e); }
  }
}

// Kopru listesini merkezden ister. Yerel kurulumda sunucu bos liste
// dondurur; istek yine gonderilir (kosula bagli kod yolu olmasin).
function bagKopruListesiIste(){
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({tip: "kopru_liste"}));
}
window.bagKopruListesiIste = bagKopruListesiIste;

// Periyodik tazeleme. WS her yeniden baglandiginda cagrilir; ayni
// zamanlayicinin ikinci kez kurulmasi engellenir.
function bagKopruZamanlayiciKur(){
  if (bagKopruZaman !== null) return;
  bagKopruListesiIste();
  bagKopruZaman = setInterval(bagKopruListesiIste, BAG_KOPRU_ARALIK_MS);
}
window.bagKopruZamanlayiciKur = bagKopruZamanlayiciKur;

// Cikista: zamanlayici durur, liste bosalir, gruplar ve servis bagli
// menuler geri alinir. Cok kiracili /app/ icin ZORUNLU.
function bagKopruOturumBitti(){
  if (bagKopruZaman !== null){
    clearInterval(bagKopruZaman);
    bagKopruZaman = null;
  }
  if (bagKopruler.length){
    bagKopruler = [];
    bagListeCiz();
    bagOzetGuncelle();
  }
  // v2.4.55: bayrak da sifirlanir. Cok kiracili /app/ icinde bir
  // sonraki oturum ayni sekmede acilabilir; bayat bayrak, yerel
  // kurulumda kopru secimini gorunur yapardi.
  bagMerkezKipi = false;
  if (typeof window.kopruServisMenuleriGuncelle === "function")
    window.kopruServisMenuleriGuncelle([], false);
  _kopruDinleyicileriCagir();
}
window.bagKopruOturumBitti = bagKopruOturumBitti;

// sysid -> baglanti_id (ws.js her telemetri paketinde tazeler)
let dronBaglantiEslem = {};

function bagGrupKabi(anahtar){
  return bagListe.querySelector('[data-bag-govde="' + anahtar + '"]');
}

// Dron kartini ait oldugu grubun govdesine tasir. Kart hicbir
// gruba yerlestirilemezse (grup henuz cizilmemis) dokunulmaz;
// bir sonraki cizimde yerine oturur.
function dronKartiGrubaYerlestir(sysid, kok){
  if (!kok || kok.classList.contains("ayrik")) return false;
  // v2.4.33: sunucu kimligi bilmedigi dronlar icin BOS DIZE gonderir
  // (`""`), null degil. Bos dize `!= null` denetimini gecerdi ve
  // `bagGrupKabi("")` daima null dondurdugu icin kart hicbir gruba
  // yerlesemezdi. Bos dize de bilinmeyen sayilmalidir.
  const bidH = dronBaglantiEslem[String(sysid)];
  const bid = (bidH == null || String(bidH) === "") ? null : String(bidH);
  const kap = bagGrupKabi(bid !== null ? bid : BAG_BILINMEYEN)
              || bagGrupKabi(BAG_BILINMEYEN);
  if (!kap || kok.parentNode === kap) return !!kap;
  kap.appendChild(kok);
  return true;
}

// Tum kartlari gruplara dagit + grup dron sayilarini tazele
function bagGruplariDoldur(){
  if (typeof dronKartlar !== "object" || !dronKartlar) return;
  for (const sysid of Object.keys(dronKartlar)){
    const kart = dronKartlar[sysid];
    if (!kart || !kart.kok) continue;
    // v2.4.224: yuzen pencere acikken panelde GOLGE satir durur; grubuna o yerlesir
    const el = (kart.kok.classList.contains("ayrik") && kart.golge) ? kart.golge : kart.kok;
    dronKartiGrubaYerlestir(sysid, el);
  }
  // Bos gruplarin "dron yok" notunu ve sayaclarini guncelle
  bagListe.querySelectorAll("[data-bag-govde]").forEach(kap => {
    const adet = kap.querySelectorAll(":scope > .dron-kart").length;
    const bos = kap.querySelector(".bag-grup-bos");
    if (bos) bos.style.display = adet ? "none" : "";
    const grup = kap.closest(".bag-grup");
    const sayac = grup && grup.querySelector(".bag-dron-sayac");
    if (sayac){
      sayac.textContent = adet ? String(adet) : "";
      sayac.style.display = adet ? "" : "none";
      sayac.classList.toggle("dolu", adet > 0);
    }
    // Yalitim grubu yalniz icinde dron varsa gorunur
    if (kap.dataset.bagGovde === BAG_BILINMEYEN && grup)
      grup.style.display = adet ? "" : "none";
  });
  // v2.4.53 Faz 7: KOPRU ust gruplarinin sayaci da TOPLAMDIR (kartlar
  // alt kayit bloklarinin icindedir, ust govde `:scope > .dron-kart`
  // ile 0 gorur). Ayni sebeple ust govdenin "dron yok" notu gizlenir.
  bagListe.querySelectorAll(".bag-kopru-govde").forEach(kap => {
    const toplam = kap.querySelectorAll(".dron-kart").length;
    const grupK = kap.closest(".bag-grup");
    const sayacK = grupK && grupK.querySelector(":scope > .bag-satir "
                                                + ".bag-kopru-sayac");
    if (sayacK){
      sayacK.textContent = toplam ? String(toplam) : "";
      sayacK.style.display = toplam ? "" : "none";
      sayacK.classList.toggle("dolu", toplam > 0);
    }
    const bosK = kap.querySelector(":scope > .bag-grup-bos");
    if (bosK) bosK.style.display = "none";
  });
  // v2.4.45: SANAL ust grubunun sayaci ic govdelerin TOPLAMIDIR.
  // Yukaridaki dongu `:scope > .dron-kart` saydigi icin ust govde 0
  // gorur (kartlar alt bloklarin icindedir); toplam burada hesaplanir.
  const sanalGovde = bagGrupKabi(BAG_SANAL);
  if (sanalGovde){
    const toplam = sanalGovde.querySelectorAll(".dron-kart").length;
    const grupS = sanalGovde.closest(".bag-grup");
    const sayacS = grupS && grupS.querySelector(":scope > .bag-satir "
                                               + ".bag-sanal-sayac");
    if (sayacS){
      sayacS.textContent = toplam ? String(toplam) : "";
      sayacS.style.display = toplam ? "" : "none";
      sayacS.classList.toggle("dolu", toplam > 0);
    }
    // Ust govdenin kendi "dron yok" notu olmamalidir: icinde kayit
    // bloklari var, her blok kendi notunu tasir.
    const bosU = sanalGovde.querySelector(":scope > .bag-grup-bos");
    if (bosU) bosU.style.display = "none";
  }
}
window.bagGruplariDoldur = bagGruplariDoldur;
window.dronKartiGrubaYerlestir = dronKartiGrubaYerlestir;

// ws.js telemetri paketinden sysid -> baglanti_id eslemesini kurar.
// Eslem degistiyse (yeni dron, baglanti degisti) yeniden dagitilir.
function dronBaglantiEslemGuncelle(dronlar){
  const yeni = {};
  for (const d of (dronlar || [])){
    if (!d || d.sysid == null) continue;
    const b = d.baglanti_id;
    // Bos dize saklanmaz: yoklugu "bilinmeyen" anlamina gelir.
    if (b != null && String(b) !== "") yeni[String(d.sysid)] = String(b);
  }
  const degisti = JSON.stringify(yeni) !== JSON.stringify(dronBaglantiEslem);
  dronBaglantiEslem = yeni;
  // v2.4.33: eslem DEGISMESE de dagitim yapilir. Kart DOM'a yeni
  // eklenmis olabilir (dronKartGuncelle ilk cagrisi) ya da
  // bagListeCiz() gruplari yeniden kurmus olabilir; her iki durumda
  // eslem aynidir ama kartin yeniden yerlestirilmesi gerekir.
  bagGruplariDoldur();
  return degisti;
}
window.dronBaglantiEslemGuncelle = dronBaglantiEslemGuncelle;

// Play / Stop / Baglaniyor butonu. Kullanici istegi (2026-09): play'e
// basinca telemetri akisi kurulana kadar SPINNER doner; timeout/hata
// dusrse tekrar PLAY; akis baslarsa (bagli) STOP olur. Spinnere/stopa
// basmak baglantiyi durdurur (vazgec).
function bagPSButonKur(btnPS, s, b, t){
  const durum = (s && s.durum) || "kapali";
  if (durum === "baglaniyor"){
    btnPS.className = "bag-btn bag-baglaniyor";
    btnPS.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
    btnPS.title = t.bagDurdurBaslik;   // tiklayinca vazgec (durdur)
  } else if (durum === "bagli"){
    btnPS.className = "bag-btn bag-stop";
    btnPS.innerHTML = '<i class="fa-solid fa-stop"></i>';
    btnPS.title = t.bagDurdurBaslik;
  } else {
    btnPS.className = "bag-btn bag-play";
    btnPS.innerHTML = '<i class="fa-solid fa-play"></i>';
    btnPS.title = t.bagBaslatBaslik;
  }
  btnPS.addEventListener("click", () => {
    if (!ws || ws.readyState !== 1) return;
    const durdurMu = (durum === "bagli" || durum === "baglaniyor");
    ws.send(JSON.stringify({tip: durdurMu ? "baglanti_durdur"
                                          : "baglanti_baslat", id: b.id}));
  });
}

function bagListeCiz(){
  // FAZ18-SIHIRBAZ: sihirbaz yeni kaydi bulmak icin
  // kayit listesini okur. `bagKayitlar` dosya kapsamli
  // oldugu icin her cizimde window'a yansitilir.
  try { window.bagKayitlar = bagKayitlar; } catch (e) {}
  const t = D();
  // Kartlar yok edilmeden once govdeden cikarilir; innerHTML=""
  // onlari da silecegi icin gecici olarak panel disinda tutulur.
  const kartSaklama = document.createDocumentFragment();
  bagListe.querySelectorAll(".dron-kart").forEach(k => kartSaklama.appendChild(k));

  bagListe.innerHTML = "";
  bagYok.style.display = bagKayitlar.length ? "none" : "";

  // v2.4.45: SANAL kayitlar ayri ayri ust grup ACMAZ. Kullanici istegi:
  // "her sanal sunucu icin ayri bir grup acma, tek bir SANAL DRON
  // grubunun altinda olusturulan diger SITL dronlar gruplansin."
  // Sanal kayitlar tek `__sanal__` ust grubunun govdesine, kendi
  // alt satirlariyla cizilir. Kart dagitim mantigi DEGISMEZ: her
  // kaydin `[data-bag-govde=<id>]` kabi hala vardir, yalnizca DOM'da
  // ust grubun icindedir.
  const sanallar = bagKayitlar.filter(b => String(b.tur) === "sanal");
  let digerler = bagKayitlar.filter(b => String(b.tur) !== "sanal");

  // v2.4.232 (kullanici istegi): KOPRU GRUPLAMASI KALDIRILDI. Kayitlar
  // duz listelenir; her satirin EN SAGINDA bagli oldugu kopru rozeti
  // gosterilir (window.kopruRozetOlustur, kopruler_panel.js). Kopru
  // yonetimi Destek > Kopruler panelindedir.
  // Kopru gruplari EN USTTE: saha makineleri sistemin omurgasidir.
  // Ardindan kopruye bagli olmayan kayitlar, SANAL grubu ve sonda
  // zorunlu yalitim grubu gelir.
  const gruplar = [];
  for (const b of digerler) gruplar.push({kayit: b, anahtar: String(b.id)});
  if (sanallar.length)
    gruplar.push({kayit: null, anahtar: BAG_SANAL, sanallar: sanallar});
  gruplar.push({kayit: null, anahtar: BAG_BILINMEYEN});

  for (const g of gruplar){
    const b = g.kayit;

    // ---- SANAL DRON ust grubu ----
    if (g.anahtar === BAG_SANAL){
      bagSanalUstGrupCiz(g.sanallar, t);
      continue;
    }
    const bilinmeyen = (b === null);
    const s = bilinmeyen ? {durum:"kapali", hata:""}
                         : (bagDurumlar[String(b.id)] || {durum:"kapali", hata:""});
    const aktif = (s.durum === "bagli" || s.durum === "baglaniyor");

    const grup = document.createElement("div");
    grup.className = "bag-grup";
    grup.dataset.bagGrup = g.anahtar;

    const satir = document.createElement("div");
    satir.className = "bag-satir" + (bilinmeyen ? " bag-satir-bilinmeyen" : "");

    // Katlama oku (grup basligina tiklanarak da katlanir)
    const katOk = document.createElement("i");
    katOk.className = "fa-solid fa-chevron-down bag-kat-ok";
    satir.appendChild(katOk);

    if (bilinmeyen){
      const bilgi = document.createElement("div");
      bilgi.className = "bag-bilgi";
      const ust = document.createElement("div");
      ust.className = "bag-ust";
      const ad = document.createElement("span");
      ad.className = "bag-ad";
      ad.textContent = t.bagBilinmeyenGrup || "BA\u011eLANTISI B\u0130L\u0130NMEYEN";
      ust.appendChild(ad);
      bilgi.appendChild(ust);
      const sayacB = document.createElement("span");
      sayacB.className = "bag-dron-sayac";
      satir.appendChild(bilgi);
      satir.appendChild(sayacB);
      grup.appendChild(satir);
      grup.style.display = "none";   // icinde dron olmadikca gizli
      bagGrupGovdeEkle(grup, g.anahtar, t);
      bagKatlamaKur(grup, satir, katOk, g.anahtar);
      bagListe.appendChild(grup);
      continue;
    }

    const bilgi = document.createElement("div");
    bilgi.className = "bag-bilgi";
    const ust = document.createElement("div");
    ust.className = "bag-ust";
    const ad = document.createElement("span");
    ad.className = "bag-ad";
    ad.textContent = b.isim;
    const tur = document.createElement("span");
    tur.className = "bag-tur bag-tur-" + b.tur;
    tur.textContent = bagTurEtiket(b.tur);
    ust.appendChild(ad); ust.appendChild(tur);
    const alt = document.createElement("div");
    alt.className = "bag-alt";
    alt.textContent = bagAltMetin(b);
    bilgi.appendChild(ust); bilgi.appendChild(alt);
    bagBetaflightOzetEkle(b, s, bilgi);

    const durum = document.createElement("span");
    durum.className = "bag-durum bd-" + s.durum;
    const dMetin = {kapali: t.bagDurumKapali, baglaniyor: t.bagDurumBaglaniyor,
                    bagli: t.bagDurumBagli, hata: t.bagDurumHata};
    durum.textContent = dMetin[s.durum] || s.durum;
    if (s.durum === "hata" && s.hata) durum.title = s.hata;

    // Play / Stop
    const btnPS = document.createElement("button");
    bagPSButonKur(btnPS, s, b, t);

    // v2.4.12: Duzenle (kalem) — aktifken de kullanilabilir;
    // sunucu aktif baglantiyi guvenli sekilde yeniden baslatir
    const btnDuz = document.createElement("button");
    btnDuz.className = "bag-btn bag-duzenle";
    btnDuz.innerHTML = '<i class="fa-solid fa-pen"></i>';
    btnDuz.title = t.bagDuzenleBaslik;
    btnDuz.addEventListener("click", () => bagDialogAc(b.tur, b));

    // Sil (yalniz durmus baglantilar icin)
    const btnSil = document.createElement("button");
    btnSil.className = "bag-btn bag-sil";
    btnSil.innerHTML = '<i class="fa-solid fa-trash"></i>';
    btnSil.title = t.bagSilBaslik;
    btnSil.disabled = aktif;
    btnSil.addEventListener("click", () => {
      if (!ws || ws.readyState !== 1) return;
      onayIste(onayMetni("onayBaglantiSil", {ad: b.isim || b.id}), () => {
        if (!ws || ws.readyState !== 1) return;
        ws.send(JSON.stringify({tip:"baglanti_sil", id: b.id}));
      });
    });

    // Grup icindeki dron sayisi (baslikta rozet)
    const sayac = document.createElement("span");
    sayac.className = "bag-dron-sayac";

    satir.appendChild(bilgi);
    satir.appendChild(sayac);
    satir.appendChild(durum);
    satir.appendChild(btnPS);
    satir.appendChild(btnDuz);
    satir.appendChild(btnSil);
    // v2.4.239: baglanti diyagrami (ortak kucuk dugme, listenin sonunda)
    if (typeof window.diyagramDugmesi === "function") satir.appendChild(window.diyagramDugmesi("baglanti", b.id));
    // v2.4.232: en sagda bagli oldugu kopru (merkezde kopru_ornek_id dolu)
    if (b.kopru_ornek_id != null && typeof window.kopruRozetOlustur === "function"){
      const kr = window.kopruRozetOlustur(b.kopru_ornek_id);
      if (kr) satir.appendChild(kr);
    }
    grup.appendChild(satir);
    bagGrupGovdeEkle(grup, g.anahtar, t);
    bagKatlamaKur(grup, satir, katOk, g.anahtar);
    bagListe.appendChild(grup);
  }

  // Saklanan kartlari gruplara geri dagit
  bagGruplariDoldur();
  // Hicbir gruba giremeyen kart kalirsa (grup silinmis) yalitim
  // grubuna dusurulur; kart asla kaybolmaz.
  if (kartSaklama.childNodes.length){
    const kap = bagGrupKabi(BAG_BILINMEYEN);
    if (kap) kap.appendChild(kartSaklama);
    bagGruplariDoldur();
  }
}

// ---------------------------------------------------------------------
// v2.4.45: SANAL DRON ust grubu
// ---------------------------------------------------------------------
// Kullanici istegi: "her sanal sunucu icin ayri bir grup acma, tek bir
// SANAL DRON grubunun altinda olusturulan diger SITL dronlar
// gruplansin."
//
// Yapi:
//   .bag-grup[data-bag-grup=__sanal__]
//     .bag-satir.bag-satir-sanal          <- "SANAL DRON" basligi + sayac
//     .bag-grup-govde[data-bag-govde=__sanal__]
//       .bag-sanal-kayit                  <- her SITL kaydi
//         .bag-satir.bag-satir-alt        <- play/stop/duzenle/sil
//         .bag-grup-govde[data-bag-govde=<id>]   <- dron kartlari
//
// KRITIK: her kaydin `[data-bag-govde=<id>]` kabi KORUNUR. Boylece
// `dronKartiGrubaYerlestir()` ve `bagGruplariDoldur()` hic degismez;
// kartlar yine dogru kaydin altina oturur. Bu, gerileme riskini en
// aza indiren tercihtir.
function bagSanalUstGrupCiz(sanallar, t){
  const grup = document.createElement("div");
  grup.className = "bag-grup bag-grup-sanal";
  grup.dataset.bagGrup = BAG_SANAL;

  const satir = document.createElement("div");
  satir.className = "bag-satir bag-satir-sanal";

  const katOk = document.createElement("i");
  katOk.className = "fa-solid fa-chevron-down bag-kat-ok";
  satir.appendChild(katOk);

  const bilgi = document.createElement("div");
  bilgi.className = "bag-bilgi";
  const ust = document.createElement("div");
  ust.className = "bag-ust";
  const ad = document.createElement("span");
  ad.className = "bag-ad";
  ad.textContent = t.bagSanalGrup || "SANAL DRON";
  const tur = document.createElement("span");
  tur.className = "bag-tur bag-tur-sanal";
  tur.textContent = bagTurEtiket("sanal");
  ust.appendChild(ad); ust.appendChild(tur);
  const alt = document.createElement("div");
  alt.className = "bag-alt";
  // Kac kayit, kaci calisiyor — tek bakista ozet
  const calisan = sanallar.filter(x => {
    const d = (bagDurumlar[String(x.id)] || {}).durum;
    return d === "bagli" || d === "baglaniyor";
  }).length;
  alt.textContent = (t.bagSanalGrupAlt || "{n} kayit, {a} calisiyor")
    .replace("{n}", String(sanallar.length))
    .replace("{a}", String(calisan));
  bilgi.appendChild(ust); bilgi.appendChild(alt);

  const sayac = document.createElement("span");
  sayac.className = "bag-dron-sayac bag-sanal-sayac";

  satir.appendChild(bilgi);
  satir.appendChild(sayac);
  grup.appendChild(satir);

  // Ust govde: icinde her kayit icin bir alt blok
  const govde = document.createElement("div");
  govde.className = "bag-grup-govde bag-sanal-govde";
  govde.dataset.bagGovde = BAG_SANAL;

  for (const b of sanallar) govde.appendChild(bagSanalKayitBlogu(b, t));

  grup.appendChild(govde);
  if (bagKatlanmis.has(BAG_SANAL)){
    grup.classList.add("katlanmis");
    govde.style.display = "none";
  }
  bagKatlamaKur(grup, satir, katOk, BAG_SANAL);
  bagListe.appendChild(grup);
}

// Tek bir SANAL kaydin blogu: alt satir (dugmeler) + dron kartlari kabi
function bagSanalKayitBlogu(b, t){
  const s = bagDurumlar[String(b.id)] || {durum:"kapali", hata:""};
  const aktif = (s.durum === "bagli" || s.durum === "baglaniyor");

  const blok = document.createElement("div");
  blok.className = "bag-sanal-kayit";
  blok.dataset.bagKayit = String(b.id);

  const satir = document.createElement("div");
  satir.className = "bag-satir bag-satir-alt";

  const katOk = document.createElement("i");
  katOk.className = "fa-solid fa-chevron-down bag-kat-ok";
  satir.appendChild(katOk);

  const bilgi = document.createElement("div");
  bilgi.className = "bag-bilgi";
  const ust = document.createElement("div");
  ust.className = "bag-ust";
  const ad = document.createElement("span");
  ad.className = "bag-ad";
  ad.textContent = b.isim;
  ust.appendChild(ad);
  const alt = document.createElement("div");
  alt.className = "bag-alt";
  alt.textContent = bagAltMetin(b);
  bilgi.appendChild(ust); bilgi.appendChild(alt);
  bagBetaflightOzetEkle(b, s, bilgi);

  const durum = document.createElement("span");
  durum.className = "bag-durum bd-" + s.durum;
  const dMetin = {kapali: t.bagDurumKapali, baglaniyor: t.bagDurumBaglaniyor,
                  bagli: t.bagDurumBagli, hata: t.bagDurumHata};
  durum.textContent = dMetin[s.durum] || s.durum;
  if (s.durum === "hata" && s.hata) durum.title = s.hata;

  const btnPS = document.createElement("button");
  bagPSButonKur(btnPS, s, b, t);

  const btnDuz = document.createElement("button");
  btnDuz.className = "bag-btn bag-duzenle";
  btnDuz.innerHTML = '<i class="fa-solid fa-pen"></i>';
  btnDuz.title = t.bagDuzenleBaslik;
  btnDuz.addEventListener("click", () => bagDialogAc(b.tur, b));

  const btnSil = document.createElement("button");
  btnSil.className = "bag-btn bag-sil";
  btnSil.innerHTML = '<i class="fa-solid fa-trash"></i>';
  btnSil.title = t.bagSilBaslik;
  btnSil.disabled = aktif;
  btnSil.addEventListener("click", () => {
    if (!ws || ws.readyState !== 1) return;
    onayIste(onayMetni("onayBaglantiSil", {ad: b.isim || b.id}), () => {
      if (!ws || ws.readyState !== 1) return;
      ws.send(JSON.stringify({tip:"baglanti_sil", id: b.id}));
    });
  });

  const sayac = document.createElement("span");
  sayac.className = "bag-dron-sayac";

  satir.appendChild(bilgi);
  satir.appendChild(sayac);
  satir.appendChild(durum);
  satir.appendChild(btnPS);
  satir.appendChild(btnDuz);
  satir.appendChild(btnSil);
  blok.appendChild(satir);

  // Kart kabi: anahtar hala kaydin ID'si -> kart dagitimi degismez
  bagGrupGovdeEkle(blok, String(b.id), t);
  bagKatlamaKur(blok, satir, katOk, String(b.id));
  return blok;
}

// v2.4.232: `bagKopruUstGrupCiz` / `bagKopruServisSeridi` KALDIRILDI —
// kopru gruplamasi yok; kopru durumu Destek > Kopruler panelinde.
// Grup govdesi: dron kartlarinin yasadigi kap + "dron yok" notu
function bagGrupGovdeEkle(grup, anahtar, t){
  const govde = document.createElement("div");
  govde.className = "bag-grup-govde";
  govde.dataset.bagGovde = anahtar;
  // v2.4.33: duz metin yerine ESKI DRONLAR PANELI gorunumu:
  // ortada buyuk soluk ucak ikonu + altinda metin.
  const bos = document.createElement("div");
  bos.className = "bag-grup-bos";
  const bosIkon = document.createElement("i");
  bosIkon.className = "fa-solid fa-plane-up bag-grup-bos-ikon";
  const bosYazi = document.createElement("div");
  bosYazi.className = "bag-grup-bos-yazi";
  bosYazi.textContent = t.bagGrupDronYok || "BU BA\u011eLANTIDA DRON YOK";
  bos.appendChild(bosIkon);
  bos.appendChild(bosYazi);
  govde.appendChild(bos);
  grup.appendChild(govde);
  if (bagKatlanmis.has(anahtar)){
    grup.classList.add("katlanmis");
    govde.style.display = "none";
  }
}

// Baslik tiklamasi grubu katlar. Play/stop, duzenle ve sil
// dugmeleri katlamayi TETIKLEMEZ: bu dugmeler basligin cocugu
// oldugu icin tiklama basliga da ulasir; hedef denetimi sart.
function bagKatlamaKur(grup, satir, katOk, anahtar){
  satir.addEventListener("click", (ev) => {
    if (ev.target.closest(".bag-btn")) return;
    const govde = grup.querySelector(".bag-grup-govde");
    const katlandi = !grup.classList.contains("katlanmis");
    grup.classList.toggle("katlanmis", katlandi);
    if (govde) govde.style.display = katlandi ? "none" : "";
    if (katlandi) bagKatlanmis.add(anahtar);
    else bagKatlanmis.delete(anahtar);
  });
}

// WS'ten gelen kayit listesi (baglanti_listesi mesaji)
function baglantiListesiIsle(m){
  bagKayitlar = m.baglantilar || [];
  bagDurumlar = m.durumlar || {};
  bagListeCiz();
  bagOzetGuncelle();
  // FAZ18-SIHIRBAZ: sihirbaz kaydettiyse yeni sanal kaydi
  // otomatik baslatir (kullanici istegi: "kaydet deyince
  // sanal dron olussun, otomatik olarak play yapsin").
  if (typeof window.sitlSihirbazListeGeldi === "function"){
    try { window.sitlSihirbazListeGeldi(); } catch (e) {}
  }
}

// Telemetride gelen anlik durumlar (baglanti_durumlari alani)
function baglantiDurumlariIsle(durumlar){
  const eski = JSON.stringify(bagDurumlar);
  // Kayitli ama dinlenmeyenler "kapali" sayilir
  const yeni = {};
  for (const b of bagKayitlar){
    yeni[String(b.id)] = durumlar[String(b.id)] ||
                         {durum:"kapali", hata:""};
  }
  bagDurumlar = yeni;
  if (JSON.stringify(bagDurumlar) !== eski){
    bagListeCiz();
    bagOzetGuncelle();
  }
}

// ---------------------------------------------------------------
// Footer + GCS karti ozeti
// ---------------------------------------------------------------
function bagOzetGuncelle(){
  const t = D();
  let bagli = 0, baglaniyor = 0, hata = 0;
  for (const s of Object.values(bagDurumlar)){
    if (s.durum === "bagli") bagli++;
    else if (s.durum === "baglaniyor") baglaniyor++;
    else if (s.durum === "hata") hata++;
  }
  seriBagli = bagli > 0;

  if (bagli > 0){
    fSeri.textContent = t.fBagAktif(bagli);
    fSeri.className = "f-iyi";
  } else if (baglaniyor > 0){
    fSeri.textContent = t.fBagBaglaniyor(baglaniyor);
    fSeri.className = "f-uyari";
  } else if (hata > 0){
    fSeri.textContent = t.fBagHata(hata);
    fSeri.className = "f-kotu";
  } else {
    fSeri.textContent = t.fBagKapali;
    fSeri.className = "";
  }

  // v2.4.32: Panel basliginda aktif baglanti sayisi rozeti
  bagBaslikRozetTazele(bagli, baglaniyor, hata);

  // GCS karti / harita kutusu ozeti (radar_gorsel.js)
  sonSeri = {durum: (bagli > 0 ? "bagli" :
                     baglaniyor > 0 ? "baglaniyor" :
                     hata > 0 ? "hata" : "kapali"),
             port: t.fBagOzet(bagli), baud: "", hata: ""};
  if (typeof gcsKutuTazele === "function") gcsKutuTazele();
}

// ---------------------------------------------------------------
// v2.4.32: Panel baslik rozeti — "N AKTİF"
//
// Rozet baslik DOM'una bir kez enjekte edilir; her telemetri
// paketinde yeniden uretilmez. Kapatma dugmesinden ONCE eklenir,
// aksi halde "X" ile rozet yer degistirir ve baslik kayar.
// ---------------------------------------------------------------
function bagBaslikRozetTazele(bagli, baglaniyor, hata){
  const panel = document.getElementById("yzSeri");
  if (!panel) return;
  const baslik = panel.querySelector(".yuzen-baslik");
  if (!baslik) return;
  let rozet = baslik.querySelector(".bag-baslik-rozet");
  if (!rozet){
    rozet = document.createElement("span");
    rozet.className = "bag-baslik-rozet";
    const kapat = baslik.querySelector(".yuzen-kapat");
    if (kapat) baslik.insertBefore(rozet, kapat);
    else baslik.appendChild(rozet);
  }
  const t = D();
  let metin = "", sinif = "";
  // v2.4.34: `bagRozet*` anahtarlari artik TR/EN sozlukte ISLEV olarak
  // tanimlidir (sayiyi alip metni uretir). Onceden sozlukte YOKTU, bu
  // yuzden kod daima Turkce yedege dusuyor ve EN arayuzde "2 AKTIF"
  // goruluyordu. Kosullu bicim, sozlugu eski bir kurulumdan gelen
  // kullanici icin geriye donuk uyumlu tutmak amaciyla korunur.
  if (bagli > 0){
    metin = (t.bagRozetAktif ? t.bagRozetAktif(bagli)
                             : bagli + " AKT\u0130F");
    sinif = "rz-iyi";
  } else if (baglaniyor > 0){
    metin = (t.bagRozetBaglaniyor ? t.bagRozetBaglaniyor(baglaniyor)
                                  : baglaniyor + " BA\u011eLANIYOR");
    sinif = "rz-uyari";
  } else if (hata > 0){
    metin = (t.bagRozetHata ? t.bagRozetHata(hata)
                            : hata + " HATA");
    sinif = "rz-kotu";
  }
  rozet.textContent = metin;
  rozet.className = "bag-baslik-rozet " + sinif;
  rozet.style.display = metin ? "" : "none";
}

// Dil degisince listeyi ve ozeti tazele (i18n.js cagirir)
function bagDilTazele(){
  bagListeCiz();
  bagOzetGuncelle();
}

// ---------------------------------------------------------------
// Olay baglari
// ---------------------------------------------------------------
document.getElementById("btnYeniSeri").addEventListener("click",
  () => bagDialogAc("seri"));
document.getElementById("btnYeniTcp").addEventListener("click",
  () => bagDialogAc("tcp"));
document.getElementById("btnYeniUdp").addEventListener("click",
  () => bagDialogAc("udp"));
document.getElementById("btnYeniDji").addEventListener("click",
  () => bagDialogAc("dji"));
// v2.4.39: SANAL dron
document.getElementById("btnYeniSanal").addEventListener("click",
  () => bagDialogAc("sanal"));
// 2026-10: Log Dron — .bin DataFlash logu yukleyip simule et.
var _btnLogDron = document.getElementById("btnYeniLogDron");
if (_btnLogDron) _btnLogDron.addEventListener("click", function(){
  if (typeof window.logReplayAc === "function") window.logReplayAc();
});
document.getElementById("btnBagKaydet").addEventListener("click", bagKaydet);
document.getElementById("btnBagIptal").addEventListener("click",
  bagDialogKapat);
document.getElementById("btnBagKapat").addEventListener("click",
  bagDialogKapat);
document.getElementById("btnBagYenile").addEventListener("click", () => {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({tip:"portlar"}));
});
// v2.4.55: kopru listesini elle tazeleme. Kopru saniyeler icinde
// acilabilir; kullanici diyalogu kapatip acmak zorunda kalmamali.
(function(){
  const b = document.getElementById("btnBagKopruYenile");
  if (b) b.addEventListener("click", () => {
    if (typeof bagKopruListesiIste === "function") bagKopruListesiIste();
  });
})();
bagAd.addEventListener("keydown", (e) => {
  if (e.key === "Enter") bagKaydet();
});
// ---------------------------------------------------------------
