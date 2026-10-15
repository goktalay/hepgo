// =====================================================================
// HEPGO HAREKÂT — hepgo_stub.js
// ---------------------------------------------------------------------
// GÖKTUNGU harekât arayüzü HEPGO'ya BİREBİR taşındı: js/*.js dosyaları bayt
// bayt değişmeden kopyalandı (KAYNAK.sha256). Paket, orijinal index.html'in
// yüklediği bazı modülleri İÇERMİYOR (radar_gorsel.js, prizma_ikon.js,
// angajman.js, surum.js, kullanici.js) ve kalan betikler bu modüllerin
// globallerini yer yer GUARD'SIZ okuyor. Bu dosya o globalleri tanımlar.
//
// YÜKLEME: index.html'de EN BAŞTA (Cesium.js'ten sonra, app_yolu.js'ten
// önce). Klasik <script>, ortak global kapsam; `var` ve function declaration
// kullanılır ki sözcüksel global aramada bulunsunlar.
//
// DİKKAT: `ws` BURADA TANIMLANMAZ. seri.js:7 `let ws = null` bildirir;
// hepgo_ws.js yalnız ATAR (`ws = sahteSoket`). Aynı kapsamda `var ws`
// bildirmek SyntaxError verir.
//
// Satır numaraları paketin kopyalandığı andaki GÖKTUNGU kaynağına aittir.
// =====================================================================

// ---------------------------------------------------------------------
// 1) Cesium Ion belirteci
// Hiçbir GÖKTUNGU dosyası Ion kullanmaz (harita.js:177 baseLayer verir,
// terrain ArcGIS'ten gelir). Varsayılan belirteç uyarısını ve olası Ion
// isteğini kesmek için boş verilir (HEPGO replay3d.js:25 ile aynı).
// harita.js viewer kurulumundan önce çalışmalıdır.
// ---------------------------------------------------------------------
(function () {
  try {
    if (typeof Cesium !== "undefined" && Cesium && Cesium.Ion) {
      Cesium.Ion.defaultAccessToken = "";
    }
  } catch (e) {}
})();

// ---------------------------------------------------------------------
// 2) GCS / radar merkezi (radar_gorsel.js)
// dronlar.js:738 dronMesafeM `if (!gcsKonum)` ile GUARD'SIZ okur; tanımsız
// kalırsa dronEtiketi → varlikGuncelle her pakette kırılır ve harita
// entity'si hiç oluşmaz (pakette de böyleydi).
// harita.js:262/298/322 (ayarlariUygula, konumum, KONUMA GİT) gcsGuncelle
// (lat, lon) fonksiyonunu korumasız çağırır. Merkez konumu dolu tutulur:
// dron etiketindeki mesafe harita merkezine göre hesaplanır (orijinalde
// radar/GCS konumuna göreydi) ve harita.js:1355 "tümünü sığdır" bu noktayı
// da kapsar (orijinal davranışla aynı).
// ---------------------------------------------------------------------
var gcsKonum = null;
function gcsGuncelle(lat, lon) {
  if (typeof lat === "number" && typeof lon === "number" &&
      isFinite(lat) && isFinite(lon)) {
    gcsKonum = { lat: lat, lon: lon };
  }
}

// ---------------------------------------------------------------------
// 3) Radar görseli (radar_gorsel.js)
// tema.js:29 `if (gcsVarlik && ...)` ve tema.js:32 `radarRenkUygula()`
// temaUygula içinde korumasızdır; tema değişiminde ReferenceError verirdi.
// radarIkonGuncelle typeof korumalı ama gcsVarlik null kaldığı için zaten
// çağrılmaz; bütünlük için no-op tanımlanır.
// seri.js:1336 `sonSeri = {...}` radar_gorsel.js için örtük global atar;
// burada açıkça bildirilir (seri.js strict değil, yine de temiz kalsın).
// ---------------------------------------------------------------------
var gcsVarlik = null;
var sonSeri = null;
function radarRenkUygula() {}
function radarIkonGuncelle() {}

// ---------------------------------------------------------------------
// 4) Angajman (angajman.js)
// dronlar.js:1132 tumDronlariTemizle `Object.keys(aktifAngajmanlar)`
// korumasız → tüm köprüler kapanınca ReferenceError ve bagGruplariDoldur
// atlanırdı. dronlar.js:2731/4941 'Angaje Ol' tıkı angajmanPopupAc çağırır;
// düğme hepgo_patch.js ile İŞLEMLER popup'ından kaldırılır, no-op yalnız
// güvenlik içindir.
// ---------------------------------------------------------------------
var aktifAngajmanlar = {};
function angajmanPopupAc() {
  try {
    console.debug("[HEPGO] angajmanPopupAc: angajman modülü HEPGO kapsamı dışında");
  } catch (e) {}
}

// ---------------------------------------------------------------------
// 5) Prizma ikon kipi (prizma_ikon.js pakette yok)
// dronlar.js:866 `typeof window.ikonPrizmaMi === "function" ?
// window.ikonPrizmaMi() : true` → varsayılan TRUE; window.PrizmaIkon da
// olmadığından entity'ye ne billboard ne elmas eklenir = GÖRÜNMEZ dron.
// false → billboard dalı (dronlar.js:900-908) elmasIkon ile çalışır.
// ---------------------------------------------------------------------
window.ikonPrizmaMi = function () { return false; };

// ---------------------------------------------------------------------
// 6) elmasIkon(renk) — billboard görseli
// dronlar.js:902 (entity oluşturma), dronlar.js:1023 (renk güncelleme) ve
// tema.js:24 (tema değişimi) çağırır; pakette tanımı yok. dronlar.js:20-28
// ucgenIkon deseniyle aynı yöntem: SVG data URL. 30x30 baklava (elmas),
// siyah kenar. Görsel GÖKTUNGU'nun prizma elmasının yeniden üretimidir.
// Not: dron_ekran_disi.js:60 `varliklar[sysid]._elmasRenk` okur; billboard
// dalında bu alan yazılmaz, yedek renk (#5cc8ff) kullanılır.
// ---------------------------------------------------------------------
function elmasIkon(renk) {
  var r = (typeof renk === "string" && renk) ? renk : "#5cc8ff";
  var svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 30 30">' +
      '<polygon points="15,1 29,15 15,29 1,15" fill="' + r + '" ' +
        'stroke="#000" stroke-width="1.5" stroke-linejoin="round"/>' +
    '</svg>';
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

// ---------------------------------------------------------------------
// 7) 3B ikon kipi: GÖKTUNGU varsayılanı (localStorage gcs_ikon_3d null → AÇIK).
// models/{ucak,quad,hexa,octo,tri,heli}.glb ikinci varlık paketiyle geldi
// (vendor/goktungu/VARLIK.sha256); harita_ikon_3d.js YOL = "models/" iframe
// sayfasına göre /static/ops/models/ olur. Daha önce kapalı başlatılan
// tarayıcılarda ("0") kullanıcı ayarına dokunulmaz.
// ---------------------------------------------------------------------

// ---------------------------------------------------------------------
// 8) Sürüm (surum.js)
// menubar.js:199-201/511 typeof korumalı (#yzHakkinda/#hkSurum HEPGO
// index'inde yok; bilgi amaçlı). iframe src'deki ?v= (HEPGO app.js sürümü,
// drone.js renderLive) okunur; hepgo_ws.js hello.v ile zenginleştirebilir.
// ---------------------------------------------------------------------
var GCS_SURUM = (function () {
  try {
    var v = new URLSearchParams(location.search).get("v");
    return "HEPGO" + (v ? " " + v : "");
  } catch (e) { return "HEPGO"; }
})();
var GCS_SURUM_TARIH = "";

// ---------------------------------------------------------------------
// 9) i18nGetir(anahtar) — arayuz.js:384/388 tam ekran düğmesi başlığı
// (typeof korumalı). D() i18n.js'te daha sonra tanımlanır; çağrı anında
// aranır, yoksa undefined döner ve arayuz.js TR yedeğine düşer.
// ---------------------------------------------------------------------
window.i18nGetir = function (anahtar) {
  try {
    var t = (typeof D === "function") ? D() : null;
    return t ? t[anahtar] : undefined;
  } catch (e) { return undefined; }
};

// ---------------------------------------------------------------------
// 10) Oturum (kullanici.js) — HEPGO oturumu çerezle sunucudadır.
// Kalan dosyalarda yalnız typeof korumalı okunur; güvenlik için tanımlı.
// SÖZLEŞME: hepgo_ws.js hello.me geldiğinde aynı nesneyi GÜNCELLER
// (yeniden atamaz): oturum.rol = me.can_command ? "pilot" : "izleyici";
// oturum.ad = me.name; oturum.id = me.id; oturum.can_command = !!me.can_command.
// ---------------------------------------------------------------------
var oturum = { rol: "pilot", ad: "", id: null, can_command: false };
window.oturum = oturum;
window.oturumYoneticiMi = function () { return oturum.rol === "yonetici"; };

// ---------------------------------------------------------------------
// 11) konsolaEkle(kaynak, mesaj, seviye) — uyari_merkezi.js:137 typeof
// korumalı çağırır; konsol.js konsolYaz'a (sonra yüklenir) bağlanır.
// ---------------------------------------------------------------------
window.konsolaEkle = function (kaynak, mesaj, seviye) {
  if (typeof konsolYaz === "function") konsolYaz(kaynak, mesaj, seviye);
};
