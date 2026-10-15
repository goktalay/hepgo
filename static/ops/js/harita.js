// =================================================================
// GOKTUNGU - CESIUM VIEWER + HARITA KATMANI + MERKEZ KONUM + HARITA KAYNAGI SECIMI
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).
// =================================================================
// CESIUM - WebSocket'ten ve seri durumdan tamamen bagimsiz kurulur,
// bu sayede baglanti hatasi olsa da harita her zaman gorunur.
// ---------------------------------------------------------------
// v2.4.53 TABAN YOL: GCS hem kok dizinde (yerel kurulum,
// http://127.0.0.1:8000/) hem de alt yolda (merkez, https://.../app/)
// sunulabilir. Karo ve varlik istekleri MUTLAKA sayfanin bulundugu dizine
// gore kurulmalidir; kok yol ("/tile/...") varsayimi alt yolda 404 uretir
// ve harita BOS gorunur (radar halkalari ve atif metni gorundugu icin
// "harita calisiyor" yanilsamasi yaratir).
// GOKTUNGU_TABAN ornek degerler: "/" (yerel), "/app/" (merkez).
window.GOKTUNGU_TABAN = (function () {
  try {
    var y = window.location.pathname || "/";
    var d = y.replace(/[^/]*$/, "");   // son bileseni (index.html) at
    if (!d || d.charAt(0) !== "/") d = "/";
    if (d.charAt(d.length - 1) !== "/") d += "/";
    return d;
  } catch (e) {
    return "/";
  }
})();

// Goreli varlik yolu uretir: goktunguYol("tile/esri/{z}/{x}/{y}")
window.goktunguYol = function (parca) {
  var p = String(parca == null ? "" : parca);
  while (p.charAt(0) === "/") p = p.slice(1);
  return window.GOKTUNGU_TABAN + p;
};

// Harita altligi: coklu kaynak destegi (secim localStorage'da saklanir)
const HARITA_KAYNAKLARI = {
  esri: {
    ad: "ESRI Uydu",
    atif: "\u00a9 Esri \u00b7 Maxar \u00b7 Earthstar Geographics",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/esri/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 Esri, Maxar, Earthstar Geographics",
    }),
  },
  esri_sokak: {
    ad: "ESRI Sokak",
    atif: "\u00a9 Esri \u00b7 HERE \u00b7 Garmin",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/esri_sokak/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 Esri, HERE, Garmin",
    }),
  },
  esri_topo: {
    ad: "ESRI Topografik",
    atif: "\u00a9 Esri \u00b7 HERE \u00b7 Garmin \u00b7 FAO \u00b7 USGS",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/esri_topo/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 Esri, HERE, Garmin, FAO, USGS",
    }),
  },
  google: {
    ad: "Google Uydu",
    atif: "\u00a9 Google",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/google/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 20,
      credit: "\u00a9 Google",
    }),
  },
  google_hibrit: {
    ad: "Google Hibrit (Uydu+Yol)",
    atif: "\u00a9 Google",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/google_hibrit/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 20,
      credit: "\u00a9 Google",
    }),
  },
  google_yol: {
    // v2.4.34: Turkce tanimlayici iceren katmanlar `adAnahtar` tasir;
    // `katmanAdi()` bunu sozlukten cozer, yoksa `ad` alanina duser.
    adAnahtar: "hkGoogleYol",
    ad: "Google Yol Haritas\u0131",
    atif: "\u00a9 Google",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/google_yol/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 20,
      credit: "\u00a9 Google",
    }),
  },
  google_arazi: {
    ad: "Google Arazi",
    atif: "\u00a9 Google",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/google_arazi/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 20,
      credit: "\u00a9 Google",
    }),
  },
  bing: {
    ad: "Bing Uydu",
    atif: "\u00a9 Microsoft Bing Maps",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/bing/{z}/{x}/{y}"),  // offline cache proxy (quadkey backend'de)
      maximumLevel: 19,
      credit: "\u00a9 Microsoft Bing Maps",
    }),
  },
  osm: {
    ad: "OpenStreetMap",
    atifAnahtar: "hkOsmAtif",
    atif: "\u00a9 OpenStreetMap katk\u0131da bulunanlar",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/osm/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 OpenStreetMap contributors",
    }),
  },
  otm: {
    ad: "OpenTopoMap",
    atif: "\u00a9 OpenTopoMap (CC-BY-SA) \u00b7 OSM",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/otm/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 17,
      credit: "\u00a9 OpenTopoMap (CC-BY-SA), OpenStreetMap contributors",
    }),
  },
  carto_acik: {
    adAnahtar: "hkCartoAcik",
    ad: "CartoDB A\u00e7\u0131k",
    atif: "\u00a9 CARTO \u00b7 OSM",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/carto_acik/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 CARTO, OpenStreetMap contributors",
    }),
  },
  carto_koyu: {
    ad: "CartoDB Koyu",
    atif: "\u00a9 CARTO \u00b7 OSM",
    yap: () => new Cesium.UrlTemplateImageryProvider({
      url: goktunguYol("tile/carto_koyu/{z}/{x}/{y}"),  // offline cache proxy
      maximumLevel: 19,
      credit: "\u00a9 CARTO, OpenStreetMap contributors",
    }),
  },
};

let haritaKaynak = localStorage.getItem("gcs_harita_kaynak") || "esri";
if (!HARITA_KAYNAKLARI[haritaKaynak]) haritaKaynak = "esri";

// v2.4.34: KATMAN ADI VE ATIF SOZLUKTEN COZULUR
// Marka adlari ("ESRI Uydu", "Bing Uydu") ceviri gerektirmez; yalniz
// Turkce tanimlayici tasiyan katmanlar `adAnahtar`/`atifAnahtar` icerir.
// Dil degisiminde `haritaKatmanAdlariTazele()` combobox'i yeniden yazar.
function katmanAdi(anahtar){
  const k = HARITA_KAYNAKLARI[anahtar];
  if (!k) return anahtar;
  const t = (typeof D === "function") ? D() : {};
  return (k.adAnahtar && t[k.adAnahtar]) || k.ad || anahtar;
}
function katmanAtif(anahtar){
  const k = HARITA_KAYNAKLARI[anahtar];
  if (!k) return "";
  const t = (typeof D === "function") ? D() : {};
  return (k.atifAnahtar && t[k.atifAnahtar]) || k.atif || "";
}
window.katmanAdi = katmanAdi;

function haritaKatmani(){
  return new Cesium.ImageryLayer(HARITA_KAYNAKLARI[haritaKaynak].yap());
}

const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: haritaKatmani(),
  baseLayerPicker:false, geocoder:false, timeline:false, animation:false,
  homeButton:false, sceneModePicker:false, navigationHelpButton:false,
  fullscreenButton:false, selectionIndicator:false, infoBox:false,
});
viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0b0e11");
viewer.camera.setView({
  destination: Cesium.Cartesian3.fromDegrees(35.0, 39.0, 1500000)
});

// ---------------------------------------------------------------
// MERKEZ KONUM
// Oncelik: 1) ayar dosyasindaki kayit  2) bilgisayarin konumu
// "KONUMA GIT" elle girilen degeri hem uygular hem dosyaya kaydeder.
// ---------------------------------------------------------------
const latGiris    = document.getElementById("latGiris");
const lonGiris    = document.getElementById("lonGiris");
const btnKonumaGit= document.getElementById("btnKonumaGit");
const konumKaynak = document.getElementById("konumKaynak");

let merkezVar = false;       // haritanin bir merkezi belirlendi mi
let ayarlarGeldi = false;    // sunucudan ilk ayar mesaji islendi mi

function sayiOku(giris){
  // Turkce klavyede virgul yazilabilir -> noktaya cevir
  const v = parseFloat(giris.value.trim().replace(",", "."));
  return Number.isFinite(v) ? v : null;
}

function merkezeGit(lat, lon, yukseklik){
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(lon, lat, yukseklik || 14000),
    duration: 1.5,
  });
}
/* ---- FAZ18-IS5-PILOT-KONUM: viewer/merkezeGit koprusu -------------------------------
   `viewer` ve `merkezeGit` bu dosyanin modul kapsamindadir; pilot bazli
   konum katmani ayri bir dosyada yasadigi icin ikisine erisebilmek
   gerekir. window'a DOGRUDAN viewer koymak yerine okuyucu islev
   veriyoruz: dis kod viewer'i degistiremez, yalniz okur.
   ----------------------------------------------------------------- */
window.__haritaViewerAl = function(){ return viewer; };
window.__haritaMerkezeGit = function(lat, lon, yuk){
  try { merkezeGit(lat, lon, yuk); } catch (e) {}
};

function ayarlariUygula(a){
  const ilkSefer = !ayarlarGeldi;
  ayarlarGeldi = true;
  if (a.tema) temaUygula(a.tema, false);
  // v2.4.65: MERKEZ UYGULAMA LISANSI ozeti.
  //
  // SIRA KRITIK: lisans ozeti radar ve GCCDUAL kararlarindan ONCE
  // kurulmalidir. Ikisi de `lisansUstSinir()` okur; ozet henuz
  // gelmemisse sinir "yok" sayilir ve yetkisiz modul bir an gorunur,
  // ardindan gizlenir. Bu titreme kullaniciya "menu bir an geldi sonra
  // kayboldu" olarak yansir ve kusur gibi algilanir.
  if (typeof window.lisansOzetiSunucudan === "function")
    window.lisansOzetiSunucudan(a.lisans || null);
  // v2.1.8: C20 RADAR arayuzu sunucu ayarindan gelir (yalnizca yonetici
  // degistirebilir) ve tum istemcilerde ayni gorunum uygulanir.
  if (typeof window.radarAyarSunucudan === "function")
    window.radarAyarSunucudan(a);
  // v2.4.45: GCCDUAL (Yer Kontrol Istasyonu Dual) arayuz anahtari da
  // sunucu ayarindan gelir; radar ile ayni desen.
  if (typeof window.istasyon2AyarSunucudan === "function")
    window.istasyon2AyarSunucudan(a);
  // v2.4.53: MERKEZ SUNUCU ayarlari (acik/adres/eposta). Sifre ASLA
  // yayilmaz; sunucu yalnizca `merkez_sifre_var` bayragini gonderir.
  // MERKEZ baglanti turu dugmesi de bu ayara gore gorunur/gizlenir.
  if (typeof window.merkezAyarSunucudan === "function"){
    window.merkezAyarSunucudan(a);
    if (typeof window.merkezTurDugmeTazele === "function")
      window.merkezTurDugmeTazele();
  }
  // v2.4.41: sirket bilgileri (antetli ucus raporunun ve arayuz
  // unvaninin kaynagi). Ayarlar her istemciye duyuruldugu icin
  // sirket bilgisi de burada dagitilir.
  if (typeof window.sirketAyarGeldi === "function")
    window.sirketAyarGeldi(a.sirket || null);
  // v2.4.43: kayitli angajman ongoru ayarlari. Angajman penceresi
  // acildiginda son secim hatirlanir; kullanici her seferinde yeniden
  // isaretlemek zorunda kalmaz.
  if (a.angajman && typeof a.angajman === "object")
    window.angajmanAyar = Object.assign({}, window.angajmanAyar || {}, a.angajman);
  if (typeof a.merkez_lat === "number" && typeof a.merkez_lon === "number"){
    latGiris.value = a.merkez_lat.toFixed(6);
    lonGiris.value = a.merkez_lon.toFixed(6);
    konumKaynak.textContent = D().konumKaynakDosya;
    gcsGuncelle(a.merkez_lat, a.merkez_lon);
    if (!merkezVar){
      merkezVar = true;
      // FAZ18-IS5-PILOT-KONUM: PILOT KAYDI GENEL AYARI EZER.
      // Genel `merkez_lat/merkez_lon` ayari bagli TUM istemcilere
      // duyuruluyor (sunucu.py `ayar_kaydet` -> `_duyur`). Eskiden bu
      // duyuru her istemcinin haritasini zorla oraya uçuruyordu; bir
      // pilotun konum degisikligi digerinin gorunumunu eziyordu.
      // Artik pilotun KENDI kayitli gorunumu varsa bu uçus atlanir.
      // Ayarin radar merkezi islevi etkilenmez: alan yine islenir,
      // yalniz kamera hareketi pilotun tercihine birakilir.
      var _pilotKaydiVar = false;
      try {
        _pilotKaydiVar = (typeof window.haritaPilotKaydiVar === "function")
          ? window.haritaPilotKaydiVar() : false;
      } catch (e) { _pilotKaydiVar = false; }
      if (!_pilotKaydiVar) merkezeGit(a.merkez_lat, a.merkez_lon);
    }
  } else if (ilkSefer){
    bilgisayarKonumuAl();
  }
}

function bilgisayarKonumuAl(){
  const t = D();
  if (!("geolocation" in navigator)){
    konumKaynak.textContent = t.konumDesteklemiyor;
    return;
  }
  konumKaynak.textContent = t.konumAliniyor;
  navigator.geolocation.getCurrentPosition(
    (poz) => {
      const lat = poz.coords.latitude, lon = poz.coords.longitude;
      latGiris.value = lat.toFixed(6);
      lonGiris.value = lon.toFixed(6);
      konumKaynak.textContent = t.konumKaynakPC(Math.round(poz.coords.accuracy));
      gcsGuncelle(lat, lon);
      if (!merkezVar){
        merkezVar = true;
        merkezeGit(lat, lon);
      }
    },
    (hata) => {
      konumKaynak.textContent = D().konumAlinamadi(hata.message);
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

btnKonumaGit.addEventListener("click", () => {
  const lat = sayiOku(latGiris);
  const lon = sayiOku(lonGiris);
  const t = D();
  if (lat === null || lon === null ||
      lat < -90 || lat > 90 || lon < -180 || lon > 180){
    konumKaynak.textContent = t.konumGecersiz;
    return;
  }
  merkezVar = true;
  merkezeGit(lat, lon);
  gcsGuncelle(lat, lon);
  konumKaynak.textContent = t.konumKaynakElle;
  if (ws && ws.readyState === 1){
    ws.send(JSON.stringify({tip:"ayar_kaydet", lat:lat, lon:lon}));
  }
});

// Panel ac/kapat dugmeleri kaldirildi (paneller her zaman acik)

// ---------------------------------------------------------------
// HARITA KAYNAGI SECIMI (HARITA AYARLARI popup - combobox)
// ---------------------------------------------------------------
const haritaAtif = document.getElementById("haritaAtif");
const selHaritaKaynak = document.getElementById("selHaritaKaynak");

function haritaKaynakUygula(kaynak, kaydet){
  if (!HARITA_KAYNAKLARI[kaynak]) return;
  if (kaynak !== haritaKaynak){
    haritaKaynak = kaynak;
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.add(haritaKatmani());
  }
  if (selHaritaKaynak && selHaritaKaynak.value !== kaynak)
    selHaritaKaynak.value = kaynak;
  if (haritaAtif) haritaAtif.textContent = katmanAtif(kaynak);
  if (kaydet) localStorage.setItem("gcs_harita_kaynak", kaynak);
}

// Combobox'i kaynak listesiyle doldur ve degisimi dinle
if (selHaritaKaynak){
  for (const [anahtar, k] of Object.entries(HARITA_KAYNAKLARI)){
    const opt = document.createElement("option");
    opt.value = anahtar;
    opt.textContent = katmanAdi(anahtar);
    selHaritaKaynak.appendChild(opt);
  }
  selHaritaKaynak.value = haritaKaynak;
  selHaritaKaynak.addEventListener("change",
    () => haritaKaynakUygula(selHaritaKaynak.value, true));
}
if (haritaAtif) haritaAtif.textContent = katmanAtif(haritaKaynak);

// v2.4.44: Yer Istasyonu 2 P8 dugmesi harita kaynagini SIRAYLA degistirir.
// Combobox olayini taklit etmek yerine ayni islev cagrilir; boylece atif
// metni, localStorage kaydi ve katman degisimi tek yerde kalir.
window.haritaKaynakUygula = haritaKaynakUygula;
window.haritaKaynakListesi = () => Object.keys(HARITA_KAYNAKLARI);
window.haritaKaynakAdi = () => haritaKaynak;
window.haritaKaynakSirala = function (yon) {
  const liste = Object.keys(HARITA_KAYNAKLARI);
  if (!liste.length) return "";
  let i = liste.indexOf(haritaKaynak);
  if (i < 0) i = 0;
  i = (i + (yon === -1 ? -1 : 1) + liste.length) % liste.length;
  haritaKaynakUygula(liste[i], true);
  return liste[i];
};

// v2.4.34: dil degisiminde katman adlari ve atif yeniden yazilir.
// `applyLanguage` bu islevi cagirir (i18n.js sonundaki tazeleme kancasi).
function haritaKatmanAdlariTazele(){
  if (selHaritaKaynak){
    for (const opt of selHaritaKaynak.options){
      opt.textContent = katmanAdi(opt.value);
    }
  }
  if (haritaAtif) haritaAtif.textContent = katmanAtif(haritaKaynak);
}
window.haritaKatmanAdlariTazele = haritaKatmanAdlariTazele;

// ---------------------------------------------------------------
// TERRAIN (arazi yuksekligi) AC/KAPAT (HARITA AYARLARI bolumu)
// ArcGIS World Elevation servisi kullanilir (Ion token GEREKTIRMEZ).
// Kapali: duz elipsoit (varsayilan, daha az bant genisligi).
// ---------------------------------------------------------------
let terrainAcik = localStorage.getItem("gcs_terrain_acik") === "1";
let _terrainYukleniyor = false;

async function terrainUygula(acik, kaydet){
  if (_terrainYukleniyor) return;
  _terrainYukleniyor = true;
  try {
    if (acik){
      const tp = await Cesium.ArcGISTiledElevationTerrainProvider.fromUrl(
        "https://elevation3d.arcgis.com/arcgis/rest/services/" +
        "WorldElevation3D/Terrain3D/ImageServer");
      viewer.terrainProvider = tp;
      terrainAcik = true;
    } else {
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
      terrainAcik = false;
    }
    if (kaydet) localStorage.setItem("gcs_terrain_acik", terrainAcik ? "1" : "0");
  } catch (e) {
    console.warn("Terrain yuklenemedi:", e);
    viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    terrainAcik = false;
  } finally {
    _terrainYukleniyor = false;
    terrainBtnTazele();
  }
}

function terrainBtnTazele(){
  const b = document.getElementById("btnTerrain");
  if (!b) return;
  const t = (typeof D === "function") ? D() : {};
  b.classList.toggle("secili", terrainAcik);
  b.innerHTML = "<i class='fa-solid fa-mountain'></i> " +
    (terrainAcik ? (t.lblTerrainAcik || "A\u00c7IK")
                 : (t.lblTerrainKapali || "KAPALI"));
}
window.terrainBtnTazele = terrainBtnTazele;  // dil degisiminde tazelenir

(function terrainKur(){
  const b = document.getElementById("btnTerrain");
  if (b) b.addEventListener("click", () => terrainUygula(!terrainAcik, true));
  terrainBtnTazele();
  if (terrainAcik) terrainUygula(true, false);
})();

// ---------------------------------------------------------------

// ---------------------------------------------------------------
// CESIUM GORUNTU / PERFORMANS AYARLARI (HARITA AYARLARI popup)
// Her ayar localStorage'da saklanir ve acilista uygulanir.
// ---------------------------------------------------------------
(function cesiumAyarKur(){
  const sc = viewer.scene;

  // Ayar tanimlari: [elemanId, lsAnahtar, varsayilan, uygulaFn]
  const anahtarlar = [
    ["chkFxaa", "gcs_czm_fxaa", true,
      (v) => { if (sc.postProcessStages && sc.postProcessStages.fxaa)
                 sc.postProcessStages.fxaa.enabled = v; }],
    ["chkAtmosfer", "gcs_czm_atmosfer", true,
      (v) => { if (sc.skyAtmosphere) sc.skyAtmosphere.show = v;
               sc.globe.showGroundAtmosphere = v; }],
    ["chkSis", "gcs_czm_sis", true,
      (v) => { sc.fog.enabled = v; }],
    ["chkAydinlatma", "gcs_czm_aydinlatma", false,
      (v) => { sc.globe.enableLighting = v; }],
    ["chkSuEfekti", "gcs_czm_su", true,
      (v) => { sc.globe.showWaterEffect = v; }],
    ["chkFps", "gcs_czm_fps", false,
      (v) => { sc.debugShowFramesPerSecond = v; }],
  ];

  for (const [id, ls, vars, uygula] of anahtarlar){
    const el = document.getElementById(id);
    const kayit = localStorage.getItem(ls);
    const deger = (kayit === null) ? vars : (kayit === "1");
    try { uygula(deger); } catch(e){ console.warn("Cesium ayar:", id, e); }
    if (!el) continue;
    el.checked = deger;
    el.addEventListener("change", () => {
      try { uygula(el.checked); } catch(e){ console.warn("Cesium ayar:", id, e); }
      localStorage.setItem(ls, el.checked ? "1" : "0");
    });
  }

  // MSAA (1/2/4/8)
  const selMsaa = document.getElementById("selMsaa");
  const msaaKayit = parseInt(localStorage.getItem("gcs_czm_msaa") || "1", 10);
  const msaa = [1,2,4,8].includes(msaaKayit) ? msaaKayit : 1;
  try { sc.msaaSamples = msaa; } catch(e){}
  if (selMsaa){
    selMsaa.value = String(msaa);
    selMsaa.addEventListener("change", () => {
      const v = parseInt(selMsaa.value, 10) || 1;
      try { sc.msaaSamples = v; } catch(e){}
      localStorage.setItem("gcs_czm_msaa", String(v));
    });
  }

  // Cozunurluk olcegi (0.5 - 2.0)
  const rngCoz = document.getElementById("rngCozunurluk");
  const lblCoz = document.getElementById("lblCozunurlukDeger");
  let coz = parseFloat(localStorage.getItem("gcs_czm_cozunurluk") || "1");
  if (!Number.isFinite(coz) || coz < 0.5 || coz > 2) coz = 1;
  viewer.resolutionScale = coz;
  function cozYaz(){ if (lblCoz) lblCoz.textContent = coz.toFixed(2) + "x"; }
  cozYaz();
  if (rngCoz){
    rngCoz.value = String(coz);
    rngCoz.addEventListener("input", () => {
      coz = parseFloat(rngCoz.value) || 1;
      viewer.resolutionScale = coz;
      cozYaz();
      localStorage.setItem("gcs_czm_cozunurluk", String(coz));
    });
  }

  // Arazi abartmasi (1 - 5x) - Cesium 1.111+ verticalExaggeration
  const rngAb = document.getElementById("rngAbartma");
  const lblAb = document.getElementById("lblAbartmaDeger");
  const abDestek = ("verticalExaggeration" in sc);
  let ab = parseFloat(localStorage.getItem("gcs_czm_abartma") || "1");
  if (!Number.isFinite(ab) || ab < 1 || ab > 5) ab = 1;
  if (abDestek) sc.verticalExaggeration = ab;
  function abYaz(){ if (lblAb) lblAb.textContent = ab.toFixed(1) + "x"; }
  abYaz();
  if (rngAb){
    if (!abDestek){
      rngAb.disabled = true;
    } else {
      rngAb.value = String(ab);
      rngAb.addEventListener("input", () => {
        ab = parseFloat(rngAb.value) || 1;
        sc.verticalExaggeration = ab;
        abYaz();
        localStorage.setItem("gcs_czm_abartma", String(ab));
      });
    }
  }
})();

// ---------------------------------------------------------------
// HARITA UZERINDE YER ARAMA (OSM Nominatim + koordinat girisi)
// "39.92, 32.85" gibi koordinat ya da yer adi yazilabilir.
// ---------------------------------------------------------------
(function haritaAramaKur(){
  const kutu = document.getElementById("haritaAramaKutu");
  const giris = document.getElementById("haritaAramaGiris");
  const sonuclar = document.getElementById("haritaAramaSonuclar");
  const btnTemizle = document.getElementById("btnAramaTemizle");
  if (!kutu || !giris || !sonuclar) return;

  // v2.1.7c: Arama artik popup icinde; arac grubundaki dugmeyle acilir
  const aramaPopup = document.getElementById("haritaAramaPopup");
  const btnArama = document.getElementById("btnHaritaArama");
  const btnPopupKapat = document.getElementById("btnAramaPopupKapat");
  const popupBaslik = document.getElementById("haritaAramaPopupBaslik");

  function aramaPopupAc(){
    if (!aramaPopup) return;
    aramaPopup.classList.remove("popup-gizli");
    if (btnArama) btnArama.classList.add("aktif");
    setTimeout(() => giris.focus(), 60);
  }
  function aramaPopupKapat(){
    if (!aramaPopup) return;
    aramaPopup.classList.add("popup-gizli");
    if (btnArama) btnArama.classList.remove("aktif");
    sonuclariGizle();
  }
  if (btnArama){
    btnArama.addEventListener("click", (e) => {
      e.stopPropagation();
      if (aramaPopup && aramaPopup.classList.contains("popup-gizli")) aramaPopupAc();
      else aramaPopupKapat();
    });
  }
  if (btnPopupKapat) btnPopupKapat.addEventListener("click", aramaPopupKapat);
  // Tasinabilirlik (konum kalici: gcs_pencere_konum / arama_popup)
  if (aramaPopup && popupBaslik && typeof window.popupTasinabilirYap === "function"){
    window.popupTasinabilirYap(aramaPopup, popupBaslik, "arama_popup");
  }

  let zamanlayici = null;
  let pinEntity = null;
  let pinZaman = null;

  function pinKoy(lat, lon, ad){
    pinKaldir();
    pinEntity = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: 12,
        color: Cesium.Color.fromCssColorString("#e8b93f"),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: ad || "",
        font: "12px Consolas, monospace",
        fillColor: Cesium.Color.WHITE,
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString("#1a2028").withAlpha(0.85),
        pixelOffset: new Cesium.Cartesian2(0, -22),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    // 20 sn sonra pini otomatik kaldir
    pinZaman = setTimeout(pinKaldir, 20000);
  }

  function pinKaldir(){
    if (pinZaman){ clearTimeout(pinZaman); pinZaman = null; }
    if (pinEntity){ viewer.entities.remove(pinEntity); pinEntity = null; }
  }

  function git(lat, lon, ad, yakinlik){
    sonuclariGizle();
    merkezeGit(lat, lon, yakinlik || 6000);
    pinKoy(lat, lon, ad);
  }

  function sonuclariGizle(){ sonuclar.classList.add("popup-gizli"); }

  function sonuclariGoster(liste){
    sonuclar.innerHTML = "";
    const t = (typeof D === "function") ? D() : {};
    if (!liste.length){
      const bos = document.createElement("div");
      bos.className = "hrt-arama-bos";
      bos.textContent = t.aramaSonucYok || "Sonu\u00e7 bulunamad\u0131";
      sonuclar.appendChild(bos);
    } else {
      for (const s of liste){
        const el = document.createElement("div");
        el.className = "hrt-arama-sonuc";
        el.innerHTML = "<i class='fa-solid fa-location-dot'></i><span></span>";
        el.querySelector("span").textContent = s.ad;
        el.addEventListener("click", () => {
          giris.value = s.ad;
          git(s.lat, s.lon, s.ad, s.yakinlik);
        });
        sonuclar.appendChild(el);
      }
    }
    sonuclar.classList.remove("popup-gizli");
  }

  function koordinatDene(metin){
    // "39.925, 32.837" / "39.925 32.837" / TR virgul ondalik destegi yok
    // (virgul ayirici olarak kullanilir); nokta ondalikli iki sayi aranir
    const m = metin.trim().match(
      /^(-?\d{1,2}(?:\.\d+)?)[\s,;]+(-?\d{1,3}(?:\.\d+)?)$/);
    if (!m) return null;
    const lat = parseFloat(m[1]), lon = parseFloat(m[2]);
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
    return { lat, lon };
  }

  async function ara(metin){
    const koord = koordinatDene(metin);
    if (koord){
      sonuclariGoster([{
        ad: koord.lat.toFixed(6) + ", " + koord.lon.toFixed(6),
        lat: koord.lat, lon: koord.lon, yakinlik: 4000,
      }]);
      return;
    }
    try {
      const dil = (typeof aktifDil !== "undefined" && aktifDil === "EN") ? "en" : "tr";
      const url = "https://nominatim.openstreetmap.org/search?format=json&limit=7" +
        "&accept-language=" + dil + "&q=" + encodeURIComponent(metin);
      const yanit = await fetch(url, { headers: { "Accept": "application/json" } });
      const veri = await yanit.json();
      const liste = (veri || []).map(v => {
        // boundingbox'tan uygun ucus yuksekligi kestir
        let yakinlik = 8000;
        if (v.boundingbox && v.boundingbox.length === 4){
          const dLat = Math.abs(parseFloat(v.boundingbox[1]) - parseFloat(v.boundingbox[0]));
          yakinlik = Math.max(2000, Math.min(1500000, dLat * 111000 * 2.2));
        }
        return {
          ad: v.display_name,
          lat: parseFloat(v.lat),
          lon: parseFloat(v.lon),
          yakinlik,
        };
      });
      sonuclariGoster(liste);
    } catch(e){
      console.warn("Arama hatasi:", e);
      sonuclariGoster([]);
    }
  }

  giris.addEventListener("input", () => {
    if (btnTemizle) btnTemizle.style.display = giris.value ? "" : "none";
    if (zamanlayici) clearTimeout(zamanlayici);
    const metin = giris.value.trim();
    if (metin.length < 3){ sonuclariGizle(); return; }
    zamanlayici = setTimeout(() => ara(metin), 450);
  });

  giris.addEventListener("keydown", (e) => {
    if (e.key === "Enter"){
      e.preventDefault();
      if (zamanlayici) clearTimeout(zamanlayici);
      const metin = giris.value.trim();
      if (metin.length >= 3) ara(metin);
    } else if (e.key === "Escape"){
      sonuclariGizle();
      giris.blur();
    }
  });

  if (btnTemizle){
    btnTemizle.addEventListener("click", () => {
      giris.value = "";
      btnTemizle.style.display = "none";
      sonuclariGizle();
      pinKaldir();
    });
  }

  // Disariya tiklaninca sonuc listesini kapat (popup disina tiklamada)
  document.addEventListener("click", (e) => {
    const kap = aramaPopup || kutu;
    if (!kap.contains(e.target) &&
        !(btnArama && btnArama.contains(e.target))) sonuclariGizle();
  });
})();

/* ============================================================
   v2.4.33: DURUM CUBUGU — HARITA ONBELLEK BOYUTU
   ------------------------------------------------------------
   Kullanici istegi: "Durum cubuguna harita cache'inin boyutunu
   yaz, harita degistikce yuklendikce son boyutu yaz."

   NEDEN AYRI IIFE?
   Asagidaki "Offline harita cache yonetimi" blogu ilk satirinda
   `if (!bilgiEl) return;` ile cikar — `#hrtCacheBilgi` ogesi
   Harita Ayarlari PENCERESININ icindedir. O pencere DOM'da yoksa
   (veya ileride kaldirilirsa) blok tumuyle iptal olur ve durum
   cubugu gostergesi de olurdu. Bu yuzden durum cubugu yazici
   islevi BAGIMSIZ bir blokta tanimlanir.

   Gosterge sunucudan gelen `tile_cache_ozet` iletisiyle beslenir;
   istemci periyodik SORGU YAPMAZ (bkz. tile_cache.py yorumlari:
   tam disk taramasi telemetriyi bloklar).
   ============================================================ */
(function(){
  const el = document.getElementById("hrtCacheDurum");
  if (!el) return;

  function boyutKisa(b){
    // Durum cubugu dar; ondalik basamak sayisi buyukluk arttikca
    // azaltilir ki metin genisligi sabit kalsin ve komsu ogeleri
    // itmesin.
    if (b >= 1073741824) return (b / 1073741824).toFixed(2) + " GB";
    if (b >= 1048576)    return (b / 1048576).toFixed(1) + " MB";
    if (b >= 1024)       return (b / 1024).toFixed(0) + " KB";
    return b + " B";
  }

  // Son yazilan degeri hatirla: ayni deger tekrar gelirse DOM'a
  // dokunulmaz (yayin 2 sn'de bir gelir; gereksiz reflow olmasin).
  let sonMetin = "";

  // Son gelen ozet: dil degisiminde ayni veriyi yeni dilde yazmak icin
  let sonOzet = null;

  window.hrtCacheDurumYaz = function(m){
    if (!m) return;
    sonOzet = m;
    const t = (typeof D === "function") ? D() : {};
    const etiket = t.durumHrtCache || "HAR\u0130TA";
    let metin;
    if (m.hazir === false){
      // Ilk tam olcum arka planda suruyor
      metin = etiket + ": " + (t.durumHrtCacheOlculuyor || "\u00f6l\u00e7\u00fcl\u00fcyor...");
      el.classList.add("hrt-cache-olculuyor");
    } else {
      const adet = m.adet || 0;
      metin = etiket + ": " + boyutKisa(m.boyut || 0) +
              " \u00b7 " + adet.toLocaleString("tr-TR") + " " +
              (t.durumHrtCacheKaro || "karo");
      el.classList.remove("hrt-cache-olculuyor");
    }
    if (metin === sonMetin) return;
    sonMetin = metin;
    el.textContent = metin;
    // Yeni karo indiginde kisa bir vurgu: kullanici "yuklendikce
    // guncelleniyor" oldugunu gorsel olarak anlar.
    el.classList.remove("hrt-cache-taze");
    // reflow zorla ki animasyon yeniden baslasin
    void el.offsetWidth;
    el.classList.add("hrt-cache-taze");
  };

  // Dil degisince mevcut degeri yeni dilde yaz (metin ceviri icerir).
  // `sonMetin` sifirlanir; aksi halde metin ayni sayilari tasidigi
  // icin "degismedi" sayilip eski dilde kalirdi.
  window.hrtCacheDurumDilTazele = function(){
    sonMetin = "";
    if (sonOzet) window.hrtCacheDurumYaz(sonOzet);
  };
})();

/* ================= v2.1.0: Offline harita cache yonetimi ================= */
(function(){
  const bilgiEl = document.getElementById("hrtCacheBilgi");
  const btnYenile = document.getElementById("btnHrtCacheYenile");
  const btnTemizle = document.getElementById("btnHrtCacheTemizle");
  const btnIndir = document.getElementById("btnHrtCacheIndir");
  const btnIptal = document.getElementById("btnHrtCacheIptal");
  const selZ1 = document.getElementById("selHrtCacheZ1");
  const selZ2 = document.getElementById("selHrtCacheZ2");
  const prog = document.getElementById("hrtCacheProg");
  const progIc = document.getElementById("hrtCacheProgIc");
  const progYazi = document.getElementById("hrtCacheProgYazi");
  if (!bilgiEl) return;

  // Zoom secenekleri 3-19
  for (let z = 3; z <= 19; z++){
    const o1 = document.createElement("option");
    o1.value = z; o1.textContent = z; selZ1.appendChild(o1);
    const o2 = document.createElement("option");
    o2.value = z; o2.textContent = z; selZ2.appendChild(o2);
  }
  selZ1.value = "10"; selZ2.value = "16";
  // FAZ18-IS31: indirme baslangic ani (kalan sure hesabi icin)
  let indirmeBasAn = 0;

  function boyutYazi(b){
    if (b >= 1073741824) return (b/1073741824).toFixed(2) + " GB";
    if (b >= 1048576) return (b/1048576).toFixed(1) + " MB";
    if (b >= 1024) return (b/1024).toFixed(0) + " KB";
    return b + " B";
  }
  function komut(o){
    if (typeof wsGonder === "function"){ wsGonder(o); return true; }
    if (window.ws && window.ws.readyState === 1){
      window.ws.send(JSON.stringify(o)); return true;
    }
    return false;
  }
  function bilgiIste(){ komut({tip: "tile_cache_bilgi"}); }

  window.hrtCacheBilgiGeldi = function(m){
    if (!bilgiEl) return;
    const adet = m.adet || 0, boyut = m.boyut || 0;
    bilgiEl.innerHTML = "<b>" + adet.toLocaleString("tr-TR") +
      "</b> karo &middot; <b>" + boyutYazi(boyut) + "</b>";
    // v2.3.0: kaynak bazinda onbellek dagilim tablosu
    const detayEl = document.getElementById("hrtCacheDetay");
    if (detayEl){
      const kaynaklar = m.kaynaklar || {};
      const adlar = Object.keys(kaynaklar);
      if (!adlar.length){
        detayEl.innerHTML = "";
        detayEl.style.display = "none";
      } else {
        const t = (typeof D === "function") ? D() : {};
        let h = "<table class='hrt-cache-tablo'><thead><tr><th>" +
          (t.hrtCacheKaynak || "Kaynak") + "</th><th>" +
          (t.hrtCacheKaro || "Karo") + "</th><th>" +
          (t.hrtCacheBoyut || "Boyut") + "</th><th>Zoom</th><th>" +
          (t.hrtCacheSon || "Son indirme") + "</th></tr></thead><tbody>";
        adlar.forEach((ad) => {
          const k = kaynaklar[ad] || {};
          // v2.4.34: katman adi sozlukten cozulur (katmanAdi)
          const etiket = (HARITA_KAYNAKLARI[ad]
                          ? katmanAdi(ad) : null) || k.etiket || ad;
          const zoom = (k.zoom_min != null && k.zoom_max != null)
            ? (k.zoom_min === k.zoom_max ? String(k.zoom_min)
               : k.zoom_min + "\u2013" + k.zoom_max) : "-";
          const son = k.son_indirme
            ? new Date(k.son_indirme * 1000).toLocaleString("tr-TR",
                {day: "2-digit", month: "2-digit", year: "2-digit",
                 hour: "2-digit", minute: "2-digit"}) : "-";
          h += "<tr><td>" + etiket + "</td><td>" +
            (k.adet || 0).toLocaleString("tr-TR") + "</td><td>" +
            boyutYazi(k.boyut || 0) + "</td><td>" + zoom +
            "</td><td>" + son + "</td></tr>";
        });
        h += "</tbody></table>";
        detayEl.innerHTML = h;
        detayEl.style.display = "";
      }
    }
    /* FAZ18-IS31-KALICILIK: indirme surerken panel kapatilip
       yeniden acilirsa cubuk bos gorunuyordu. `tile_cache_bilgi`
       yaniti `indirme` alanini zaten tasiyor; buradan yuzde ve
       sayilar geri kurulur. */
    const ind = m.indirme || {};
    indirmeDurum(!!ind.aktif);
    if (ind.aktif && (ind.toplam || 0) > 0){
      if (!indirmeBasAn) indirmeBasAn = Date.now();
      const y = Math.min(100, Math.round((ind.inen || 0) * 100 / ind.toplam));
      progIc.style.width = y + "%";
      progYazi.textContent = (ind.inen || 0).toLocaleString("tr-TR") +
        " / " + ind.toplam.toLocaleString("tr-TR") + " karo (%" + y + ")";
    }
  };
  /* FAZ18-IS31-ILERLEME: kalan sure ve hiz gostergesi.
     Sunucu artik her 5 karoda VE en az saniyede bir bildirim
     yapiyor (eskiden 20 karoda birdi -> cubuk donmus goruntusu). */
  window.hrtCacheIlerleme = function(m){
    if (m.iptal){ indirmeDurum(false); bilgiIste(); return; }
    const inen = m.inen || 0, toplam = m.toplam || 0, hata = m.hata || 0;
    indirmeDurum(true);
    if (!indirmeBasAn) indirmeBasAn = Date.now();
    const yuzde = toplam > 0 ? Math.min(100, Math.round(inen*100/toplam)) : 0;
    progIc.style.width = yuzde + "%";
    let ek = "";
    const gecen = (Date.now() - indirmeBasAn) / 1000;
    if (inen > 0 && gecen > 2 && inen < toplam){
      const hiz = inen / gecen;
      const kalan = Math.round((toplam - inen) / Math.max(hiz, 0.1));
      ek = " · " + sureYazi(kalan) + " kaldı · " +
           hiz.toFixed(1) + "/sn";
    }
    progYazi.textContent = inen.toLocaleString("tr-TR") + " / " +
      toplam.toLocaleString("tr-TR") + " karo (%" + yuzde + ")" +
      (hata ? " · " + hata + " hata" : "") + ek;
    if (toplam > 0 && inen >= toplam){
      indirmeBasAn = 0;
      setTimeout(() => { indirmeDurum(false); bilgiIste(); }, 800);
    }
  };
  function indirmeDurum(aktif){
    prog.classList.toggle("aktif", aktif);
    progYazi.classList.toggle("aktif", aktif);
    btnIndir.style.display = aktif ? "none" : "";
    btnIptal.style.display = aktif ? "" : "none";
    btnIndir.disabled = aktif;
  }
  btnYenile && btnYenile.addEventListener("click", bilgiIste);
  btnTemizle && btnTemizle.addEventListener("click", () => {
    komut({tip: "tile_cache_temizle"});
  });
  btnIptal && btnIptal.addEventListener("click", () => {
    komut({tip: "tile_cache_iptal"});
  });
  /* FAZ18-IS31-ONOLCUM: iki asamali indirme
     -------------------------------------------------------------
     OLCUM: eski surumde dugmeye basmak dogrudan indirmeyi
     baslatiyordu. Kullanici z10-16 varsayilaniyla Ankara sehrini
     secince 20.563 karo (olculen hizla 69 dakika) istiyordu ve
     bunu hicbir yerde goremiyordu; ilerleme cubugu saatlerce
     donmus gorunuyordu.
     COZUM: dugme artik ONCE sunucudan on olcum ister. Yanit
     gelince karo sayisi, tahmini sure ve disk boyutu ile onay
     penceresi acilir. Ust sinir asilmissa indirme hic
     baslatilmaz. */
  let bekleyenIstek = null;      // on olcum yanitini bekleyen istek

  function sureYazi(sn){
    if (sn < 60) return sn + " sn";
    if (sn < 3600) return Math.round(sn / 60) + " dk";
    const s = Math.floor(sn / 3600), d = Math.round((sn % 3600) / 60);
    return s + " sa" + (d ? " " + d + " dk" : "");
  }

  window.hrtCacheOnOlcum = function(m){
    const t = (typeof D === "function") ? D() : {};
    const istek = bekleyenIstek;
    bekleyenIstek = null;
    if (!istek) return;
    const adet = (m.toplam || 0).toLocaleString("tr-TR");
    if (m.asildi){
      alert((t.hrtCacheSinirAsildi ||
        "Se\u00e7ilen b\u00f6lge \u00e7ok geni\u015f: {adet} karo. " +
        "Üst s\u0131n\u0131r {sinir} karo. L\u00fctfen zoom " +
        "aral\u0131\u011f\u0131n\u0131 daralt\u0131n veya haritada " +
        "daha yak\u0131na gelin.")
        .replace("{adet}", adet)
        .replace("{sinir}", (m.sinir || 0).toLocaleString("tr-TR")));
      return;
    }
    const soru = (t.hrtCacheOnay ||
      "{adet} karo indirilecek.\nTahmini s\u00fcre: {sure}\n" +
      "Tahmini disk: {boyut}\n\nS\u00fcrd\u00fcr\u00fclsün m\u00fc?")
      .replace("{adet}", adet)
      .replace("{sure}", sureYazi(m.saniye || 0))
      .replace("{boyut}", boyutYazi(m.bayt || 0));
    if (!confirm(soru)) return;
    komut(istek);
    indirmeDurum(true);
    progIc.style.width = "0%";
    progYazi.textContent = (t.hrtCacheBasliyor || "Ba\u015flat\u0131l\u0131yor...");
    indirmeBasAn = Date.now();
  };

  btnIndir && btnIndir.addEventListener("click", () => {
    let z1 = parseInt(selZ1.value, 10), z2 = parseInt(selZ2.value, 10);
    if (z1 > z2){ const t = z1; z1 = z2; z2 = t; }
    // Cesium gorunen dikdortgen
    let rect = null;
    try { rect = viewer.camera.computeViewRectangle(); } catch(e){}
    if (!rect){
      alert(D().hrtGorunumAlinamadi ||
            "Harita g\u00f6r\u00fcn\u00fcm\u00fc al\u0131namad\u0131"); return;
    }
    const CM = Cesium.Math;
    const ortak = {kaynak: haritaKaynak,
           lat1: CM.toDegrees(rect.south), lon1: CM.toDegrees(rect.west),
           lat2: CM.toDegrees(rect.north), lon2: CM.toDegrees(rect.east),
           z1: z1, z2: z2};
    // Indirme istegini sakla; onay sonrasi gonderilecek.
    bekleyenIstek = Object.assign({tip: "tile_cache_indir"}, ortak);
    progYazi.textContent = (D().hrtCacheOlculuyor ||
                            "Hesaplan\u0131yor...");
    komut(Object.assign({tip: "tile_cache_on_olcum"}, ortak));
  });
  // Popup her acildiginda guncel bilgi iste
  const btnHaritaAyar = document.getElementById("btnHaritaAyar");
  document.addEventListener("click", (e) => {
    const p = document.getElementById("haritaPopup");
    if (p && !p.classList.contains("popup-gizli") &&
        (e.target.closest("#btnHaritaAyar") ||
         e.target.closest('[data-yuzen="haritaPopup"]')))
      setTimeout(bilgiIste, 150);
  });
  // WS baglaninca ilk bilgi
  setTimeout(bilgiIste, 2500);
})();

/* ================= v2.1.1: CETVEL (mesafe olcum araci) =================
   - btnCetvel'e tiklaninca cetvel modu acilir (dugme mavi, imlec crosshair).
   - Modda her harita tiklamasi yeni nokta ekler; ardisik noktalar arasina
     cizgi cizilir ve segmentin ortasinda mesafe (m/km) etiketi gosterilir.
   - Birden fazla nokta varsa son noktada TOPLAM mesafe etiketi de bulunur.
   - Dugmeye tekrar tiklaninca mod kapanir ve tum cizimler silinir.
   - CTRL/ALT kombinasyonlari cetvel modunda da eski islevlerine gider
     (cetvel yalniz sade sol tiki kullanir). */
(function(){
  const btn = document.getElementById("btnCetvel");
  const alan = document.getElementById("haritaAlan");
  if (!btn) return;

  let aktif = false;
  let noktalar = [];      // Cartesian3 listesi
  let varliklar = [];     // eklenen Cesium entity'leri
  let toplamM = 0;

  function metreYazi(m){
    if (m >= 1000) return (m/1000).toFixed(2) + " km";
    return Math.round(m).toLocaleString("tr-TR") + " m";
  }

  // Iki nokta arasi jeodezik mesafe (metre)
  function mesafeM(c1, c2){
    const g1 = Cesium.Cartographic.fromCartesian(c1);
    const g2 = Cesium.Cartographic.fromCartesian(c2);
    const geo = new Cesium.EllipsoidGeodesic(g1, g2);
    return geo.surfaceDistance;
  }

  function noktaEkle(cartesian){
    noktalar.push(cartesian);
    // Nokta isareti
    varliklar.push(viewer.entities.add({
      position: cartesian,
      point: {
        pixelSize: 8, color: Cesium.Color.fromCssColorString("#2563eb"),
        outlineColor: Cesium.Color.WHITE, outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      }
    }));
    const n = noktalar.length;
    if (n >= 2){
      const onceki = noktalar[n-2];
      const seg = mesafeM(onceki, cartesian);
      toplamM += seg;
      // Segment cizgisi
      varliklar.push(viewer.entities.add({
        polyline: {
          positions: [onceki, cartesian],
          width: 3, clampToGround: true,
          material: new Cesium.PolylineDashMaterialProperty({
            color: Cesium.Color.fromCssColorString("#3b82f6"), dashLength: 12
          })
        }
      }));
      // Segment ortasina mesafe etiketi
      const orta = Cesium.Cartesian3.midpoint(onceki, cartesian, new Cesium.Cartesian3());
      varliklar.push(viewer.entities.add({
        position: orta,
        label: {
          text: metreYazi(seg),
          font: "bold 13px Consolas, monospace",
          fillColor: Cesium.Color.WHITE,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString("#2563eb").withAlpha(0.85),
          backgroundPadding: new Cesium.Cartesian2(6, 4),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -8),
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        }
      }));
      // 3+ noktada son noktaya TOPLAM etiketi (oncekini kaldir)
      if (window.__cetvelToplamEnt){
        viewer.entities.remove(window.__cetvelToplamEnt);
        const i = varliklar.indexOf(window.__cetvelToplamEnt);
        if (i >= 0) varliklar.splice(i, 1);
        window.__cetvelToplamEnt = null;
      }
      if (n >= 3){
        window.__cetvelToplamEnt = viewer.entities.add({
          position: cartesian,
          label: {
            text: "TOPLAM: " + metreYazi(toplamM),
            font: "bold 12px Consolas, monospace",
            fillColor: Cesium.Color.WHITE,
            showBackground: true,
            backgroundColor: Cesium.Color.fromCssColorString("#111827").withAlpha(0.88),
            backgroundPadding: new Cesium.Cartesian2(6, 4),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            verticalOrigin: Cesium.VerticalOrigin.TOP,
            pixelOffset: new Cesium.Cartesian2(0, 12),
            disableDepthTestDistance: Number.POSITIVE_INFINITY
          }
        });
        varliklar.push(window.__cetvelToplamEnt);
      }
    }
  }

  function temizle(){
    varliklar.forEach(e => { try { viewer.entities.remove(e); } catch(_){} });
    varliklar = []; noktalar = []; toplamM = 0;
    window.__cetvelToplamEnt = null;
  }

  function modKur(){
    const kap = document.getElementById("cesiumContainer");
    if (!kap || typeof viewer === "undefined" || !viewer || !viewer.scene){
      setTimeout(modKur, 500); return;
    }
    // NOT: Cesium ScreenSpaceEventHandler bu projede bazi surum/tarayici
    // kombinasyonlarinda tetiklenmiyor (bkz. dronlar.js kurHaritaDronTik).
    // Projenin kanitlanmis deseni kullanildi: container uzerinde DOM click.
    kap.addEventListener("click", (e) => {
      if (!aktif) return;
      if (e.ctrlKey || e.altKey || e.shiftKey) return; // modifiyeli tiklar diger modullere ait
      const r = kap.getBoundingClientRect();
      const cartesian = viewer.camera.pickEllipsoid(
        new Cesium.Cartesian2(e.clientX - r.left, e.clientY - r.top),
        viewer.scene.globe.ellipsoid);
      if (cartesian) noktaEkle(cartesian);
    });
  }
  modKur();

  // Cetvel modu disaridan kapatilabilsin (or. rota duzenleme baslarken)
  window.__cetvelAktif = () => aktif;
  window.__cetvelKapat = function(){
    if (!aktif) return;
    aktif = false;
    btn.classList.remove("aktif");
    if (alan) alan.classList.remove("cetvel-modu");
    temizle();
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (aktif){ window.__cetvelKapat(); return; }
    aktif = true;
    btn.classList.add("aktif");
    if (alan) alan.classList.add("cetvel-modu");
  });
})();

/* ================= v2.4.39: window.haritaMerkezi() ===================
   Haritanin O ANKI merkezini {lat, lon} olarak dondurur; hesaplanamazsa
   null. Bu yardimci harita katmaninda tanimlanir cunku viewer'in sahibi
   burasidir; SANAL dron olusturma (seri.js) ve hava/konum widget'lari
   ayni tanimi paylasmalidir.

   Yontem: ekran ortasindan yere isin atilir (globe.pick). Bu, egik
   kamerada dogru sonuc verir; kamera konumu egik bakista yerdeki merkezden
   uzaga duser. Isin yere degmezse (ufuk gorunumu, arazi yuklenmemis)
   kamera konumuna dusulur. */
(function(){
  window.haritaMerkezi = function(){
    try {
      if (typeof viewer === "undefined" || !viewer || !viewer.scene) return null;
      const C = window.Cesium;
      if (!C) return null;
      const sahne = viewer.scene;
      try {
        const kanvas = sahne.canvas;
        const orta = new C.Cartesian2(kanvas.clientWidth / 2,
                                      kanvas.clientHeight / 2);
        const isin = viewer.camera.getPickRay(orta);
        if (isin){
          const nokta = sahne.globe.pick(isin, sahne);
          if (nokta){
            const k = C.Cartographic.fromCartesian(nokta);
            if (k) return {
              lat: C.Math.toDegrees(k.latitude),
              lon: C.Math.toDegrees(k.longitude),
            };
          }
        }
      } catch(e){}
      const kk = viewer.camera.positionCartographic;
      if (kk) return {
        lat: C.Math.toDegrees(kk.latitude),
        lon: C.Math.toDegrees(kk.longitude),
      };
    } catch(e){}
    return null;
  };
})();

/* ================= v2.1.1: Statusbar ZOOM gostergesi =================
   Kamera yuksekliginden web-mercator karo zoom seviyesi turetilir ve
   alt durum cubugundaki #zoomDurum alanina yazilir. */
(function(){
  const el = document.getElementById("zoomDurum");
  if (!el) return;

  function zoomHesapla(){
    try {
      const h = viewer.camera.positionCartographic.height;
      if (!isFinite(h) || h <= 0) return null;
      // Yaklasik esdeger karo zoom'u: z ~ log2(cevre / (yukseklik * 2))
      // 40075016 m: ekvator cevresi. Pratikte tile cache araligina (3-19) sinirla.
      let z = Math.log2(40075016.686 / Math.max(h, 1)) + 1.5;
      z = Math.max(0, Math.min(21, Math.round(z)));
      return { z: z, h: h };
    } catch(e){ return null; }
  }

  function yukseklikYazi(h){
    if (h >= 1000) return (h/1000).toFixed(h >= 100000 ? 0 : 1) + " km";
    return Math.round(h) + " m";
  }

  let sonYazi = "";
  function guncelle(){
    const v = zoomHesapla();
    if (!v){ return; }
    const yazi = "ZOOM: " + v.z + " (" + yukseklikYazi(v.h) + ")";
    if (yazi !== sonYazi){ sonYazi = yazi; el.textContent = yazi; }
  }

  function kur(){
    if (typeof viewer === "undefined" || !viewer){ setTimeout(kur, 500); return; }
    viewer.camera.changed.addEventListener(guncelle);
    // camera.changed her kucuk degisimde tetiklenmeyebilir; ilk deger + emniyet
    guncelle();
    setInterval(guncelle, 1000);
  }
  kur();
})();

/* ============ v2.4.34: TUMUNU SIGDIR + KONUMUMA GIT ============
   Kullanici istegi: "haritada cetvel dugmesinin altina haritadaki aktif
   tum bilesenleri bir arada gormemi ve fokuslamami saglayan bir dugme
   koyalim... tek bir nokta varsa da sadece o noktaya fokuslansin. ayni
   soldaki dugmelerin altina birde kullanicinin konumuna gidecek bir
   dugme koyalim."

   TASARIM KARARLARI

   1) Koordinatlar `viewer.entities` taranarak DEGIL, veri kaynaklarindan
      toplanir. Entity taramasi cazip gorunur ama guvenilmez: kapsama
      halkalari, kubbe tel kafesi, iz polyline'lari ve cetvel cizimleri de
      entity'dir. Kubbe yaricapi on binlerce metre olabildigi icin
      kapsama geometrisi sinirlari sisirir ve "tumunu sigdir" dronu
      goremeyecek kadar uzaklasir. Bu yuzden yalnizca ANLAMLI varliklarin
      konumu okunur:
        - `sonVeri`            (dronlar; ws.js her telemetri paketinde tazeler)
        - `sonRadarHedefler`   (radar izleri)
        - `gcsKonum`           (radar/GCS merkezi)
        - `window._lokasyonlarSon` (lokasyon ikonlari)
        - `window._kameralarSon`   (lokasyona bagli olmayan kameralar)

   2) Bu globaller `let`/`const` ile tepe duzeyde tanimlidir ve sayfa
      klasik `<script>` ile yuklendigi icin ayni kapsamda gorunur. Ancak
      modul yuklenme sirasi degisirse `undefined` olabilirler; her erisim
      `typeof` ile korunur. Dron ucuran bir arayuzde bir dugmenin
      ReferenceError ile sessizce olmesi kabul edilemez.

   3) Tek nokta durumu ayri ele alinir: `flyToBoundingSphere` sifir
      yaricapli kureye ucamaz (kamera hedefin icine girer). Tek nokta
      varsa dogrudan o noktanin ustune belirli bir yuksekliten ucar.
*/
(function(){
  const btnSigdir = document.getElementById("btnTumunuSigdir");
  const btnKonum  = document.getElementById("btnKonumuma");

  // Tek nokta odaklanmasinda kamera yuksekligi (m)
  const TEK_NOKTA_YUKSEKLIK = 2500;
  // Cok noktali sigdirmada kureyi buyutme carpani: varliklar kenara
  // yapismasin, cerceve icinde nefes payi kalsin.
  const KURE_PAYI = 1.6;
  // Cok yakin varliklarda kure yaricapi metrelerle olculur; kamera
  // yerin icine girmesin diye alt sinir.
  const MIN_YARICAP_M = 400;

  function toast(baslik, mesaj, seviye){
    if (typeof window.uyariToastGoster === "function"){
      // uyariToastGoster NESNE alir (imza dogrulandi).
      window.uyariToastGoster({
        baslik: baslik, mesaj: mesaj, seviye: seviye || "bilgi", sure: 4000,
      });
    }
  }

  function sayiMi(x){ return typeof x === "number" && isFinite(x); }

  /* Haritadaki anlamli varliklarin koordinatlarini toplar.
     Donus: [{lon, lat, yuk}] */
  function noktalariTopla(){
    const nk = [];
    const ekle = (lon, lat, yuk) => {
      if (!sayiMi(lat) || !sayiMi(lon)) return;
      if (lat === 0 && lon === 0) return;      // gecersiz GPS kilidi
      if (lat < -90 || lat > 90) return;
      if (lon < -180 || lon > 180) return;
      nk.push({ lon: lon, lat: lat, yuk: sayiMi(yuk) ? Math.max(0, yuk) : 0 });
    };

    // --- Dronlar ---
    try {
      if (typeof sonVeri === "object" && sonVeri){
        for (const sid of Object.keys(sonVeri)){
          const d = sonVeri[sid];
          if (d) ekle(d.lon, d.lat, d.irtifa || d.alt || 0);
        }
      }
    } catch(_){}

    // --- Radar hedefleri ---
    try {
      if (typeof sonRadarHedefler !== "undefined" &&
          Array.isArray(sonRadarHedefler)){
        for (const h of sonRadarHedefler) if (h) ekle(h.lon, h.lat, h.yukseklik);
      }
    } catch(_){}

    // --- Radar / GCS merkezi ---
    try {
      if (typeof gcsKonum === "object" && gcsKonum)
        ekle(gcsKonum.lon, gcsKonum.lat, 0);
    } catch(_){}

    // --- Lokasyonlar ---
    try {
      for (const l of (window._lokasyonlarSon || [])) if (l) ekle(l.lon, l.lat, 0);
    } catch(_){}

    // --- Lokasyona bagli OLMAYAN kameralar (kendi koordinati olanlar) ---
    try {
      for (const k of (window._kameralarSon || []))
        if (k && !k.lokasyon_id) ekle(k.lon, k.lat, 0);
    } catch(_){}

    return nk;
  }

  /* Nokta kumesini kapsayan kureye ucar. */
  function tumunuSigdir(){
    const t = (typeof D === "function") ? D() : {};
    const nk = noktalariTopla();

    if (!nk.length){
      toast(t.sigdirBaslik || "T\u00fcm\u00fcn\u00fc s\u0131\u011fd\u0131r",
            t.sigdirVarlikYok ||
              "Haritada odaklanacak bile\u015fen yok.",
            "uyari");
      return;
    }

    // Tek nokta: kure yerine dogrudan ustune uc.
    if (nk.length === 1){
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(
          nk[0].lon, nk[0].lat, nk[0].yuk + TEK_NOKTA_YUKSEKLIK),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
        duration: 1.4,
      });
      toast(t.sigdirBaslik || "T\u00fcm\u00fcn\u00fc s\u0131\u011fd\u0131r",
            (t.sigdirTekNokta ||
              "Tek bile\u015fen bulundu; ona odaklan\u0131ld\u0131."), "bilgi");
      return;
    }

    // Cok nokta: kapsayan kure. Cesium kureyi kendisi hesaplar; boylece
    // dateline (180. meridyen) ve kutup durumlari da dogru calisir.
    const kartezyenler = nk.map(p =>
      Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.yuk));
    const kure = Cesium.BoundingSphere.fromPoints(kartezyenler);
    kure.radius = Math.max(kure.radius * KURE_PAYI, MIN_YARICAP_M);

    viewer.camera.flyToBoundingSphere(kure, {
      duration: 1.6,
      // Tepeden bakis: iki uzak sehirdeki varlik ayni cerceveye girsin.
      offset: new Cesium.HeadingPitchRange(
        0, Cesium.Math.toRadians(-75), 0),
    });

    toast(t.sigdirBaslik || "T\u00fcm\u00fcn\u00fc s\u0131\u011fd\u0131r",
          (t.sigdirSonuc ? t.sigdirSonuc(nk.length)
                         : (nk.length + " bile\u015fen g\u00f6r\u00fcn\u00fcme al\u0131nd\u0131.")),
          "bilgi");
  }

  /* Tarayici konumuna ucar. */
  let konumIsteniyor = false;
  function konumumaGit(){
    const t = (typeof D === "function") ? D() : {};
    if (konumIsteniyor) return;

    if (!navigator.geolocation){
      toast(t.konumumaBaslik || "Konumuma git",
            t.konumumaDesteklenmiyor ||
              "Taray\u0131c\u0131 konum servisini desteklemiyor.", "hata");
      return;
    }

    konumIsteniyor = true;
    btnKonum.classList.add("arac-bekliyor");

    navigator.geolocation.getCurrentPosition(
      (poz) => {
        konumIsteniyor = false;
        btnKonum.classList.remove("arac-bekliyor");
        const lat = poz.coords.latitude, lon = poz.coords.longitude;
        // Konum dogrulugu (m) kamera yuksekligini belirler: 5 m hassas
        // konumda yakin, 5 km hassasiyette uzaktan bak.
        const dogruluk = sayiMi(poz.coords.accuracy) ? poz.coords.accuracy : 100;
        const yuk = Math.min(Math.max(dogruluk * 12, 800), 200000);
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, yuk),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
          duration: 1.4,
        });
        toast(t.konumumaBaslik || "Konumuma git",
              (t.konumumaSonuc
                ? t.konumumaSonuc(lat.toFixed(5), lon.toFixed(5),
                                  Math.round(dogruluk))
                : ("Konum: " + lat.toFixed(5) + ", " + lon.toFixed(5) +
                   " (\u00b1" + Math.round(dogruluk) + " m)")),
              "bilgi");
      },
      (hata) => {
        konumIsteniyor = false;
        btnKonum.classList.remove("arac-bekliyor");
        // Gerekce ONEMLI: kullanici izni reddettiyse tekrar denemek
        // bosunadir; tarayici ayarindan degistirmesi gerekir.
        let mesaj;
        if (hata && hata.code === 1){
          mesaj = t.konumumaIzinYok ||
            "Konum izni verilmedi. Taray\u0131c\u0131 adres \u00e7ubu\u011fundaki " +
            "kilit simgesinden konum iznini a\u00e7\u0131n.";
        } else if (hata && hata.code === 2){
          mesaj = t.konumumaAlinamadi ||
            "Konum al\u0131namad\u0131 (konum servisi kapal\u0131 olabilir).";
        } else if (hata && hata.code === 3){
          mesaj = t.konumumaZamanAsimi ||
            "Konum isteginde zaman a\u015f\u0131m\u0131.";
        } else {
          mesaj = (hata && hata.message) ? hata.message
                : (t.konumumaAlinamadi || "Konum al\u0131namad\u0131.");
        }
        toast(t.konumumaBaslik || "Konumuma git", mesaj, "hata");
      },
      // HTTP uzerinden calisan kurulumlarda (kullanicinin lokal makinesi
      // http://127.0.0.1:8000) Chrome localhost'u guvenli sayar; LAN IP'si
      // ile acilirsa konum reddedilebilir. Hata mesaji bunu aciklar.
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 }
    );
  }

  if (btnSigdir) btnSigdir.addEventListener("click", tumunuSigdir);
  if (btnKonum)  btnKonum.addEventListener("click", konumumaGit);

  // Dis kullanim (menu/klavye kisayolu eklenirse)
  window.haritaTumunuSigdir = tumunuSigdir;
  window.haritaKonumumaGit  = konumumaGit;
})();

/* ---- FAZ18-IS29C: ortak konum dogrulamasi ---- */
/* SITL/telemetri baslangicta (0,0) yayinlar = "null island" (Gine Korfezi).
   Sayisal olarak gecerli oldugu icin null denetimlerinden gecer ve
   varlik/HOME/hedef oraya kurulur; mesafe 2000+ km cikar.
   OLCUT: lat===0 VE lon===0 ise reddet.
   Yalniz birinin sifir olmasi MESRUDUR (ekvator / Greenwich uzeri ucus). */
window.gecerliKonumMu = function (lat, lon) {
  if (lat === null || lat === undefined) return false;
  if (lon === null || lon === undefined) return false;
  var a = Number(lat), o = Number(lon);
  if (!isFinite(a) || !isFinite(o)) return false;
  if (a === 0 && o === 0) return false;            /* null island */
  if (a < -90 || a > 90) return false;
  if (o < -180 || o > 180) return false;
  return true;
};
/* ---- FAZ18-IS29C sonu ---- */
