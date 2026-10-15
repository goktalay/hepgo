// ============================================================
// GOKTUNGU GCS — PRIZMA IKON VE ARAZI YUKSEKLIK REFERANSI
// v2.4.30
//
// AMAC
// ----
// 1) Arazi yuksekligi (terrain) ACIK iken ikonlarin kaymasini onlemek
// 2) Ikonlari uc boyutlu prizma bicimine gecirmek (%80 opaklik)
// 3) (v2.4.30) Dron ve hedef ikonlarini CIFT PIRAMIT (bipiramit / elmas,
//    "plumbob") bicimine gecirmek; radar/GCS prizmasini kisaltmak
//
// KAYMA SORUNUNUN KOK NEDENI
// --------------------------
// Onceki surumlerde ikonlar `Cartesian3.fromDegrees(lon, lat, yuk)` ile
// ELIPSOID referansina yerlestiriliyordu. Terrain kapaliyken zemin =
// elipsoid yuzeyi oldugundan bu dogru sonuc verir. Terrain acildiginda
// arazi yukselir (Ankara'da olculen deger: 787-962 m) ancak ikonun
// konumu elipsoid yuksekliginde kalir; yani ikon arazinin YUZLERCE
// METRE ALTINDA durur.
//
// `disableDepthTestDistance: POSITIVE_INFINITY` derinlik testini
// kapattigi icin ikon arazinin arkasinda olmasina karsin cizilmeye
// devam eder. Kamera dondukce arazinin altindaki nokta perspektif
// projeksiyonunda farkli ekran konumuna dustugu icin kullanici bunu
// "ikonun kaymasi" olarak gorur.
//
// OLCUM (v2.4.28, Ankara Sincan, kamera 3 km uzakta, egim -20):
//   heading   0 -> kayma  263 px
//   heading  45 -> kayma  359 px
//   heading  90 -> kayma 8911 px
//   heading 315 -> kayma  359 px
//   kayma degisimi: 8648 px
// Kayma miktari kamera acisina gore degistigi icin bu bir PROJEKSIYON
// hatasidir; sabit bir gorsel ofsetle duzeltilemez.
//
// COZUM
// -----
// `heightReference` kullanilir. Cesium zemin yuksekligini terrain
// kafesinden kendisi okur ve kafes cozunurluk degistirdikce konumu
// KENDILIGINDEN tazeler. Elle `globe.getHeight()` toplanmasi yeterli
// DEGILDIR: terrain saglayicisi sayfa acilisindan saniyeler sonra
// eszamansiz olarak degisir (olculdu) ve o ana kadar olusturulmus
// ikonlar yanlis yukseklikte kalirdi.
//
//   Dron         (alt_rel, zemine gore)   -> RELATIVE_TO_GROUND
//   Radar hedefi (yukseklik, zemine gore) -> RELATIVE_TO_GROUND
//   Radar/GCS    (sabit 0)                -> CLAMP_TO_GROUND
//
// ============================================================
// v2.4.30 — IKI AYRI IKON BICIMI
// ============================================================
//
// A) BIPIRAMIT (dron ve hedefler) — "plumbob"
// -------------------------------------------
// Kullanicinin istedigi bicim: ust ve alt tepe noktalari olan, ortada
// en genis, dikey eksende uzun bir ELMAS.
//
//            ^  ust tepe
//           /|\
//          / | \
//         /  |  \
//        <---+--->   orta kusak (en genis kesit)
//         \  |  /
//          \ | /
//           \|/
//            v  alt tepe
//
// Bu bicim `PolygonGraphics` + `extrudedHeight` ile URETILEMEZ: ekstrude
// poligon PRIZMATIKTIR (taban kesiti yukseklik boyunca sabittir), tepe
// noktasina daralamaz.
//
// v2.4.30'da bicim ayri bir `Cesium.Primitive` ile uretilmisti; bu
// yaklasim gorsel olarak dogru ancak BASARIM ACISINDAN PAHALIYDI
// (ikon basina ayri cizim cagrisi). v2.4.31'de gosterim
// `EllipsoidGraphics` uzerine tasindi: `slicePartitions:4` +
// `stackPartitions:2` verilen bir ellipsoid geometrik olarak KARE
// TABANLI CIFT PIRAMITTIR, yani ayni bicim entity ozelligi olarak ve
// cok daha dusuk maliyetle elde edilir. Ayrintili gerekce asagidaki
// "B) BIPIRAMIT" bolumunde.
//
// Yon gosterimi: orta kusagin kose sayisi 4'tur ve kusaktaki koselerden
// BIRI hareket yonune bakar; boylece elmasin genis eksenlerinden biri
// dogrudan burun yonunu gosterir. Ust tepe alt tepeden daha uzundur
// (referans gorseldeki oran) ve elmas dikey olarak asimetriktir.
//
// B) KISALTILMIS OK PRIZMASI (radar / GCS istasyonu)
// --------------------------------------------------
// Radar istasyonu ZEMINDE durur ve bakis yonunu gostermesi gerekir; bu
// nedenle bicim korunur ancak v2.4.29'da 22 m olan dikey kalinlik
// kullanici geri bildirimi uzerine 8 m'ye dusurulur (%64 kisalma) ve
// yatay olcek 48 m -> 30 m yapilir.
//
// Prizmalar `disableDepthTestDistance` KULLANAMAZ (bu ozellik yalnizca
// billboard ve label icindir). Bu bir kazanctir: geometri arazinin
// arkasinda kaldiginda dogru bicimde gizlenir, yani kayma sorunu ikinci
// bir yoldan da onlenmis olur.
// ============================================================

// Kullanicinin istedigi opaklik: %80 (cok az seffaf)
const PRIZMA_ALFA = 0.8;

// ------------------------------------------------------------
// YUKSEKLIK REFERANSI
// ------------------------------------------------------------

// Zemine gore yukseklikte duran ogeler (dron, radar hedefi).
// Terrain kapaliyken zemin = elipsoid oldugundan davranis degismez.
function yukReferansiZemineGore(){
  return Cesium.HeightReference.RELATIVE_TO_GROUND;
}

// Tam zemine oturan ogeler (radar/GCS istasyonu).
function yukReferansiZemine(){
  return Cesium.HeightReference.CLAMP_TO_GROUND;
}

// Terrain'in gercekten yuklu olup olmadigini soyler.
// Kucultulmus Cesium paketinde sinif ADLARI korunmadigi icin
// (EllipsoidTerrainProvider -> "VV") tur adina GUVENILMEZ;
// `availability` alani yalnizca gercek terrain saglayicilarinda vardir.
function terrainYuklu(){
  try {
    return !!(viewer && viewer.terrainProvider && viewer.terrainProvider.availability);
  } catch (e) { return false; }
}

// Bir noktanin zemin yuksekligi (m). Terrain yuklu degilse 0.
function zeminYuksekligi(lat, lon){
  try {
    const h = viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(lon, lat));
    return (typeof h === "number" && isFinite(h)) ? h : 0;
  } catch (e) { return 0; }
}

// ------------------------------------------------------------
// YARDIMCI: azimut + mesafe -> yeni koordinat
// ------------------------------------------------------------
function _prizmaOfset(lat, lon, azimutDer, mesafeM){
  const R = 6378137.0;
  const az = Cesium.Math.toRadians(azimutDer);
  const f1 = Cesium.Math.toRadians(lat);
  const l1 = Cesium.Math.toRadians(lon);
  const dr = mesafeM / R;
  const f2 = Math.asin(Math.sin(f1) * Math.cos(dr) +
                       Math.cos(f1) * Math.sin(dr) * Math.cos(az));
  const l2 = l1 + Math.atan2(Math.sin(az) * Math.sin(dr) * Math.cos(f1),
                             Math.cos(dr) - Math.sin(f1) * Math.sin(f2));
  return [Cesium.Math.toDegrees(f2), Cesium.Math.toDegrees(l2)];
}

// ============================================================
// A) OK PRIZMASI (radar / GCS) — ekstrude poligon
// ============================================================
// Ikon, burnu bakis yonunu gosteren DORT KOSELI OK (dart) prizmasidir:
//
//        burun (yon)
//           /\
//          /  \
//         /    \        <- taban: burun, sol kanat, kuyruk, sag kanat
//        /  /\  \
//       / /    \ \
//      sol      sag
//         kuyruk (ice girintili)

function prizmaKoseleri(lat, lon, yonDer, olcek){
  const burunUz = olcek;            // burun mesafesi
  const kuyrukUz = olcek * 0.55;    // kuyruk mesafesi
  const kanatUz = olcek * 0.62;     // yan aciklik

  const [bLat, bLon] = _prizmaOfset(lat, lon, yonDer, burunUz);
  const [sLat, sLon] = _prizmaOfset(lat, lon, yonDer + 143, kanatUz);
  const [gLat, gLon] = _prizmaOfset(lat, lon, yonDer - 143, kanatUz);
  const [kLat, kLon] = _prizmaOfset(lat, lon, yonDer + 180, kuyrukUz * 0.35);

  // Saat yonunun TERSI sirada (Cesium disari bakan normal bekler)
  return [bLon, bLat, sLon, sLat, kLon, kLat, gLon, gLat];
}

// v2.4.30: radar/GCS prizmasi KISALTILDI (kullanici geri bildirimi)
//   yatay yarim uzunluk : 48 m -> 30 m
//   dikey kalinlik      : 22 m ->  8 m
const PRIZMA_OLCEK_M = 30;      // yon dogrultusunda yarim uzunluk
const PRIZMA_KALINLIK_M = 8;    // prizmanin dikey kalinligi

// Bir prizma entity tanimi uretir (radar/GCS ve prizma kipi disi yedek).
// secenek: {lat, lon, yuk, yon, renk, zemine, olcek, kalinlik}
function prizmaTanimi(secenek){
  const { lat, lon, yuk, yon, renk } = secenek;
  const zemine = !!secenek.zemine;
  const olcek = secenek.olcek || PRIZMA_OLCEK_M;
  const kalinlik = secenek.kalinlik || PRIZMA_KALINLIK_M;
  const c = Cesium.Color.fromCssColorString(renk).withAlpha(PRIZMA_ALFA);

  const koseler = prizmaKoseleri(lat, lon, (typeof yon === "number" ? yon : 0), olcek);
  const hier = new Cesium.PolygonHierarchy(
    Cesium.Cartesian3.fromDegreesArray(koseler));

  const tanim = {
    hierarchy: hier,
    material: c,
    outline: true,
    outlineColor: Cesium.Color.fromCssColorString(renk).withAlpha(0.95),
    outlineWidth: 2,
    perPositionHeight: false,
    heightReference: zemine ? yukReferansiZemine() : yukReferansiZemineGore(),
    extrudedHeightReference: zemine ? yukReferansiZemine() : yukReferansiZemineGore(),
  };
  if (zemine){
    tanim.height = 0;
    tanim.extrudedHeight = kalinlik;
  } else {
    const y = Math.max(0, yuk || 0);
    tanim.height = Math.max(0, y - kalinlik / 2);
    tanim.extrudedHeight = Math.max(0, y - kalinlik / 2) + kalinlik;
  }
  return tanim;
}

function prizmaTazele(entity, secenek){
  if (!entity || !entity.polygon) return;
  const t = prizmaTanimi(secenek);
  entity.polygon.hierarchy = t.hierarchy;
  entity.polygon.material = t.material;
  entity.polygon.outlineColor = t.outlineColor;
  entity.polygon.height = t.height;
  entity.polygon.extrudedHeight = t.extrudedHeight;
  entity.polygon.heightReference = t.heightReference;
  entity.polygon.extrudedHeightReference = t.extrudedHeightReference;
}

function prizmaAlfaAyarla(entity, renk, carpan){
  if (!entity || !entity.polygon) return;
  const a = PRIZMA_ALFA * (typeof carpan === "number" ? carpan : 1);
  entity.polygon.material = Cesium.Color.fromCssColorString(renk).withAlpha(a);
  entity.polygon.outlineColor =
    Cesium.Color.fromCssColorString(renk).withAlpha(Math.min(1, a + 0.15));
}

// ============================================================
// B) BIPIRAMIT (dron / hedef) — "plumbob" elmas
// ============================================================
// v2.4.31 — BASARIM ICIN YENIDEN YAZILDI
// ------------------------------------------------------------
// v2.4.30'da bipiramit her ikon icin AYRI bir `Cesium.Primitive`
// olarak kuruluyordu. Kullanici bildirimi: "3 boyuta gecince
// bilgisayar cok yavasliyor". Olculen maliyet kalemleri:
//
//   - Ikon basina 1 primitive  -> ikon basina AYRI cizim cagrisi
//     (draw call); Cesium primitive'leri toplu isleyemez
//   - `asynchronous:false`     -> geometri derlemesi ANA IS PARCACIGINDA
//   - `translucent:true`       -> her karede derinlik siralamasi
//   - `bpTazele` her paket      -> Matrix4 carpimi + nesne ayirma
//   - Bunlarin TAMAMI zaten var olan entity (label + 2 polyline)
//     maliyetinin USTUNE biniyordu
//
// Toplu primitive (tek primitive icinde N `GeometryInstance`) COZUM
// DEGILDIR: toplu primitive'in `modelMatrix`'i TEKTIR, ornek basina
// donusum guncellenemez. Her ikon bagimsiz hareket ettigi icin her
// telemetri paketinde tum toplu geometrinin yeniden uretilmesi
// gerekirdi; bu daha pahalidir.
//
// SECILEN COZUM: `EllipsoidGraphics` ile OKTAHEDRAL elmas
// ------------------------------------------------------------
// Kilit icgoru: `slicePartitions: 4` ve `stackPartitions: 2` verilen
// bir ellipsoid, geometrik olarak KARE TABANLI CIFT PIRAMITTIR — yani
// istenen plumbob biciminin YAKLASIMI DEGIL, birebir kendisidir
// (8 ucgen yuzey, ust ve alt tepe, ortada en genis kare kesit).
// Fark yalnizca uretim yolundadir: primitive yerine ENTITY OZELLIGI.
//
// Kazanclar:
//   - Ek primitive YOK; entity'nin icine girer, Cesium entity
//     geometrilerini kendi toplu isleme hattinda birlestirir
//   - `heightReference` DESTEKLENIR -> zemin yuksekligini Cesium okur;
//     v2.4.30'daki elle `globe.getHeight()` toplama ve onun getirdigi
//     "bir sonraki pakette duzelir" gecikmesi ORTADAN KALKAR
//   - Entity silinince KENDILIGINDEN kalkar; sizinti onlemi gereksiz
//   - Renk guncellemesi tek atama; `getGeometryInstanceAttributes` yok
//   - Konum guncellemesi `position` atamasi; Matrix4 carpimi yok
//
// Yon gosterimi entity'nin var olan `orientation` alani ile verilir
// (`Transforms.headingPitchRollQuaternion`). Geometri dunya uzayinda
// doner; kamera acisi telafisi gerekmez.
//
// Dikey asimetri: ellipsoid merkeze gore SIMETRIKTIR, bu nedenle
// v2.4.30'daki "ust tepe alt tepeden uzun" asimetrisi dogrudan
// verilemez. Ayni gorsel etki merkez yuksekligi kaydirilarak elde
// edilir: elmasin merkezi telemetri yuksekliginin `BP_MERKEZ_KAY_M`
// kadar USTUNE alinir; boylece govdenin buyuk kismi konumun uzerinde
// kalir ve referans gorseldeki oran korunur.
//
// NOT: Asagidaki BP_* sabitleri v2.4.30 API'siyle uyum icin korunur;
// yeni gosterimde yaricap/yukseklik `BP_YARICAP_M` ve
// `BP_UST_M + BP_ALT_M` uzerinden turetilir.
// ORAN (v2.4.31b duzeltmesi): ilk denemede radii=(11,11,20.5) verilmisti;
// dikey yaricap yatayin ~1.9 kati oldugu icin siluet plumbob yerine UZUN
// bir kristal/mermi gibi gorunuyordu (sinav sayfasi ekran goruntusuyle
// dogrulandi). Referans plumbob'da genislik : yukseklik ~ 1 : 1.35'tir.
// Bu yuzden yatay yaricap genisletilir ve dikey kisaltilir.
const BP_YARICAP_M   = 15;   // yatay yari genislik (kare kesit yaricapi)
const BP_UST_M       = 24;   // (v2.4.30 uyumu) ust yari yukseklik
const BP_ALT_M       = 16;   // (v2.4.30 uyumu) alt yari yukseklik
const BP_KUSAK_KOSE  = 4;    // kesit kose sayisi = slicePartitions
// Dikey katman sayisi = stackPartitions. CESIUM ASGARI 3 SARTI KOYAR
// (worker icindeki EllipsoidGeometry kopyasinda dogrulanir); 3'un
// altina DUSURULMEMELIDIR, aksi halde cizim dongusu durur.
const BP_KATMAN      = 3;

// Elmasin toplam dikey yari uzunlugu ve merkez kaydirmasi.
// Toplam boy v2.4.30 ile ayni tutulur (26 + 15 = 41 m), boylece
// haritadaki gorsel olcek degismez.
const BP_DIKEY_YARI_M  = (BP_UST_M + BP_ALT_M) / 2;   // 20.5 m
const BP_MERKEZ_KAY_M  = (BP_UST_M - BP_ALT_M) / 2;   // 5.5 m (yukari)
// ------------------------------------------------------------
// ELMAS (OKTAHEDRAL) IKON — entity ozelligi olarak
// ------------------------------------------------------------
// Bir `EllipsoidGraphics` tanimi uretir. `slicePartitions:4` +
// `stackPartitions:2` kombinasyonu KARE TABANLI CIFT PIRAMIT
// (oktahedron) verir; yani istenen plumbob bicimi.
//
// `outline` KULLANILMAZ: ellipsoid ana hatti Cesium'da ayri bir
// geometri olarak cizilir ve cizim cagrisi sayisini iki katina
// cikarir. Yuzey golgelendirmesi zaten yuzleri ayirt ettirdigi icin
// ana hat gorsel olarak da gereksizdir.
//
// secenek: {yuk, renk, zemine, olcekCarpan, alfa}
function elmasTanimi(secenek){
  const k = (typeof secenek.olcekCarpan === "number" && secenek.olcekCarpan > 0)
    ? secenek.olcekCarpan : 1;
  const alfa = (typeof secenek.alfa === "number") ? secenek.alfa : PRIZMA_ALFA;
  const r = BP_YARICAP_M * k;
  const h = BP_DIKEY_YARI_M * k;

  return {
    // radii: yatayda dar, dikeyde uzun -> elmas silueti
    radii: new Cesium.Cartesian3(r, r, h),
    material: Cesium.Color.fromCssColorString(secenek.renk).withAlpha(alfa),
    // Kose sayisini asgaride tutar: 4 dilim x 3 katman.
    // ONEMLI — `stackPartitions` EN AZ 3 OLMALIDIR. Cesium'un worker
    // icindeki `EllipsoidGeometry` kopyasi (Workers/chunk-*.js) su
    // dogrulamayi uygular:
    //     if (a < 3) throw new DeveloperError(
    //       "options.stackPartitions cannot be less than three.");
    // Deger 2 verildiginde hata ENTITY EKLENIRKEN DEGIL, geometrinin
    // worker'da derlendigi CIZIM KARESINDE atilir ve Cesium'un cizim
    // dongusunu TAMAMEN DURDURUR ("Rendering has stopped"). Boyle bir
    // durumda ikonlar cizilmez, sahne donar ve FPS cakilir; belirti
    // yaniltici bicimde "basarim sorunu" gibi gorunur.
    // Ana is parcacigindaki `Cesium.EllipsoidGeometry` bu denetimi
    // TASIMAZ; bu yuzden ana is parcaciginda yapilan sinav yanlis
    // olarak "gecti" der. Dogrulama gercek cizim karesinde yapilmali.
    // 3 katman: iki tepe + iki ara kusak -> ustte ve altta daralan
    // cift piramit (plumbob) silueti; 24 ucgen, hala cok hafif.
    slicePartitions: BP_KUSAK_KOSE,
    stackPartitions: BP_KATMAN,
    outline: false,
    // Zemin referansi: Cesium terrain kafesinden kendisi okur ve kafes
    // cozunurluk degistirdikce KENDILIGINDEN tazeler. v2.4.30'daki elle
    // `globe.getHeight()` toplama ve onun getirdigi gecikme kalkti.
    heightReference: secenek.zemine
      ? yukReferansiZemine() : yukReferansiZemineGore(),
  };
}

// Elmasin merkez konumu. Ellipsoid merkeze gore simetrik oldugu icin
// dikey asimetri merkez kaydirmasiyla saglanir (bkz. BP_MERKEZ_KAY_M).
// Yukseklik ELIPSOID degeri degildir: `heightReference` zemine gore
// yorumlandigi icin telemetri yuksekligi dogrudan verilir.
function elmasKonumu(lat, lon, yuk, zemine, olcekCarpan){
  const k = (typeof olcekCarpan === "number" && olcekCarpan > 0) ? olcekCarpan : 1;
  const kay = BP_MERKEZ_KAY_M * k;
  const taban = zemine ? 0 : Math.max(0, yuk || 0);
  return Cesium.Cartesian3.fromDegrees(lon, lat, taban + kay);
}

// Elmasin yon dogrultusu. Kesit koselerinden biri burun yonune bakar.
// `headingPitchRollQuaternion` ENU cercevesinde calisir; azimut saat
// yonunde oldugu icin isaret cevrilmez (Cesium heading zaten CW+).
function elmasYonu(lat, lon, yuk, yonDer, zemine, olcekCarpan){
  const merkez = elmasKonumu(lat, lon, yuk, zemine, olcekCarpan);
  const hpr = new Cesium.HeadingPitchRoll(
    Cesium.Math.toRadians(yonDer || 0), 0, 0);
  return Cesium.Transforms.headingPitchRollQuaternion(merkez, hpr);
}

// ------------------------------------------------------------
// v2.4.30 API UYUMLULUK KATMANI
// ------------------------------------------------------------
// v2.4.30'da bipiramit AYRI bir primitive'di ve cagiranlar
// `bpOlustur/bpTazele/bpAlfaAyarla/bpSil` kullaniyordu. v2.4.31'de
// gosterim entity ozelligine tasindigi icin bu fonksiyonlar artik
// ENTITY uzerinde calisir. Imzalar korunur ki cagiran dosyalarda
// (dronlar.js, hedefler.js) genis capli degisiklik gerekmesin.
//
// `bpOlustur` artik primitive DONDURMEZ; entity'ye `ellipsoid`
// ozelligini yazar ve entity'nin kendisini dondurur. Boylece
// cagiranin `_bipiramit` alani entity'ye isaret eder ve var olan
// null denetimleri gecerliligini korur.

// Entity'ye elmas gosterimini uygular.
// secenek: {entity, lat, lon, yuk, yon, renk, zemine, olcekCarpan, alfa}
function elmasUygula(entity, secenek){
  if (!entity) return null;
  const zemine = !!secenek.zemine;
  entity.ellipsoid = elmasTanimi(secenek);
  entity.position = elmasKonumu(secenek.lat, secenek.lon, secenek.yuk,
                                zemine, secenek.olcekCarpan);
  entity.orientation = elmasYonu(secenek.lat, secenek.lon, secenek.yuk,
                                 secenek.yon, zemine, secenek.olcekCarpan);
  entity._elmasRenk = secenek.renk;
  entity._elmasAlfa = (typeof secenek.alfa === "number") ? secenek.alfa : PRIZMA_ALFA;
  entity._elmasZemine = zemine;
  entity._elmasOlcek = secenek.olcekCarpan;
  return entity;
}

// v2.4.30 uyumu: cagiranlar `bpOlustur(secenek)` bicimini kullanir ve
// donen degeri `_bipiramit` alanina yazar. Entity `secenek.entity`
// icinde gelmelidir; gelmezse islem yapilamaz (sessizce null doner,
// telemetri zinciri KESILMEZ).
function bipiramitOlustur(secenek){
  if (!secenek || !secenek.entity) return null;
  return elmasUygula(secenek.entity, secenek);
}

// Konum / yon / renk tazeler. Artik yalnizca ozellik atamalari yapar;
// Matrix4 carpimi ve geometri yeniden uretimi YOKTUR.
function bipiramitTazele(entity, secenek){
  if (!entity || !entity.ellipsoid) return entity;
  try {
    const zemine = (typeof secenek.zemine === "boolean")
      ? secenek.zemine : !!entity._elmasZemine;
    const olcek = (typeof secenek.olcekCarpan === "number")
      ? secenek.olcekCarpan : entity._elmasOlcek;

    entity.position = elmasKonumu(secenek.lat, secenek.lon, secenek.yuk,
                                  zemine, olcek);
    entity.orientation = elmasYonu(secenek.lat, secenek.lon, secenek.yuk,
                                   secenek.yon, zemine, olcek);

    const alfa = (typeof secenek.alfa === "number") ? secenek.alfa : entity._elmasAlfa;
    const renk = secenek.renk || entity._elmasRenk;
    // Renk yalnizca DEGISTIYSE yazilir: her pakette yeni `Color` nesnesi
    // ayirmak gereksiz cop uretir.
    if (renk !== entity._elmasRenk || alfa !== entity._elmasAlfa){
      entity.ellipsoid.material =
        Cesium.Color.fromCssColorString(renk).withAlpha(alfa);
      entity._elmasRenk = renk;
      entity._elmasAlfa = alfa;
    }
  } catch (e){
    // Tazeleme basarisiz olursa gorsel eski konumda kalir; telemetri
    // zinciri KESILMEZ (v2.4.30 dayaniklilik ilkesi korunur).
    console.warn("Elmas ikon tazeleme hatasi:", e);
  }
  return entity;
}

// Opaklik carpani uygular (baglanti kopmasi / suzulen hedef).
function bipiramitAlfaAyarla(entity, renk, carpan){
  if (!entity || !entity.ellipsoid) return;
  const a = PRIZMA_ALFA * (typeof carpan === "number" ? carpan : 1);
  try {
    const r = renk || entity._elmasRenk || "#ffffff";
    entity.ellipsoid.material = Cesium.Color.fromCssColorString(r).withAlpha(a);
    entity._elmasAlfa = a;
    entity._elmasRenk = r;
  } catch (e){ /* gorsel ayrinti: kritik degil */ }
}

// Elmas gosterimini kaldirir.
// v2.4.31: elmas artik entity OZELLIGIDIR; entity silinince
// kendiliginden kalkar. Bu fonksiyon yalnizca entity yasarken
// gosterimin kaldirilmasi gerektiginde (kip gecisi) is yapar.
// Cagiranlarda var olan `bpSil` cagrilari zararsizdir.
function bipiramitSil(entity){
  if (!entity) return;
  try {
    if (entity.ellipsoid) entity.ellipsoid = undefined;
  } catch (e){ /* zaten kaldirilmis */ }
}

// ------------------------------------------------------------
// KIP ANAHTARI (Harita Ayarlari > Prizma Ikonlar)
// ------------------------------------------------------------
// Varsayilan ACIK. Kayitli deger yoksa prizma/bipiramit kullanilir.
// FAZ18-PRIZMA-KALDIR: kip anahtari kaldirildi. Prizma artik TEK
// gorunumdur; degistirilemez. Degisken korunur cunku dosya
// icinde okunan yerler vardir, ancak DAIMA true.
const _prizmaAcik = true;
// Eski kayit temizligi: bir tarayicida "0" yazili kalmissa,
// anahtar artik gorunmese de duz simge cizilmeye devam
// ederdi. Bu, v2.4.70'te `gcs_logo` anahtarinda olculen
// sinif kusurun aynisidir; kayit bir kez silinir.
try { localStorage.removeItem("gcs_prizma_ikon"); }
catch (e) { /* gizli kip / kota: onemsiz */ }

function ikonPrizmaMi(){ return false; }  // FAZ18-PRIZMA-KALDIR

// Kip degistiginde var olan varliklar YENIDEN OLUSTURULMALIDIR:
// bir entity'nin `billboard` alani `ellipsoid`e donusturulemez (Cesium
// gorsel bileseni yerinde degistirmez). En guvenli yol ilgili varlik
// sozluklerini bosaltip cizim dongusunun yeniden uretmesini beklemektir.
// v2.4.31: elmas artik entity ozelligi oldugu icin `bipiramitSil`
// cagrisi sart degildir (entity ile birlikte gider); yine de kip
// gecisinde acik davranis icin korunur.
// FAZ18-PRIZMA-KALDIR: `prizmaKipiUygula` ve `prizmaKur`
// KALDIRILDI. Kip degistiren bir arayuz ogesi artik yoktur,
// dolayisiyla varliklari yikip yeniden cizdirmeye de gerek
// kalmamistir. Geometri govdesi (koseler / tanim / tazele /
// alfaAyarla) yukarida OLDUGU GIBI korunmustur.
//
// Disa acilan `kipUygula` yerine, cagiran eski kod catlamasin
// diye etkisiz bir islev birakilir: prizma zaten tek kiptir.
function prizmaKipiUygula(){ /* FAZ18-PRIZMA-KALDIR: etkisiz */ }

// ------------------------------------------------------------
// DISA ACILAN ARAYUZ
// ------------------------------------------------------------
window.ikonPrizmaMi = ikonPrizmaMi;
window.PrizmaIkon = {
  ALFA: PRIZMA_ALFA,
  OLCEK_M: PRIZMA_OLCEK_M,
  KALINLIK_M: PRIZMA_KALINLIK_M,
  zemineGore: yukReferansiZemineGore,
  zemine: yukReferansiZemine,
  terrainYuklu: terrainYuklu,
  zeminYuksekligi: zeminYuksekligi,
  // Ok prizmasi (radar / GCS)
  koseler: prizmaKoseleri,
  tanim: prizmaTanimi,
  tazele: prizmaTazele,
  alfaAyarla: prizmaAlfaAyarla,
  // Elmas / plumbob (dron / hedef) — v2.4.31: entity ozelligi
  BP_YARICAP_M: BP_YARICAP_M,
  BP_UST_M: BP_UST_M,
  BP_ALT_M: BP_ALT_M,
  BP_DIKEY_YARI_M: BP_DIKEY_YARI_M,
  BP_MERKEZ_KAY_M: BP_MERKEZ_KAY_M,
  // Yeni, dogrudan arayuz
  elmasTanimi: elmasTanimi,
  elmasKonumu: elmasKonumu,
  elmasYonu: elmasYonu,
  elmasUygula: elmasUygula,
  // v2.4.30 uyumlu adlar (cagiranlar degismeden calisir)
  bpOlustur: bipiramitOlustur,
  bpTazele: bipiramitTazele,
  bpAlfaAyarla: bipiramitAlfaAyarla,
  bpSil: bipiramitSil,
  // Kip
  kipMi: ikonPrizmaMi,
  kipUygula: prizmaKipiUygula,
};
