// =================================================================
// GOKTUNGU - TEMA (koyu / acik)
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).
// =================================================================
// TEMA (koyu / acik) - arayuz + harita altligi + ikon renkleri
// ---------------------------------------------------------------
const btnKoyu = document.getElementById("btnKoyu");
const btnAcik = document.getElementById("btnAcik");

function temaUygula(tema, kaydet){
  if (tema !== "koyu" && tema !== "acik") return;
  if (tema !== aktifTema){
    aktifTema = tema;
    // Harita altligini tazele (secili kaynak korunur)
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.add(haritaKatmani());
    // Mevcut dron ikonlarini yeni renklerle tazele
    // (yon gosteren ucgen ikon + kalici dron rengi)
    for (const sysid in varliklar){
      const rnk = (typeof dronRengi === "function")
        ? dronRengi(sysid) : dronTelemetriRengi();
      if (varliklar[sysid].billboard)
        varliklar[sysid].billboard.image = elmasIkon(rnk);
      varliklar[sysid].label.fillColor = Cesium.Color.fromCssColorString(rnk);
    }
    // v2.4.30: prizma kipinde `billboard` yoktur; radarIkonGuncelle
    // her iki kipi de dogru ele alir (bkz. radar_gorsel.js).
    if (gcsVarlik && typeof radarIkonGuncelle === "function"){
      radarIkonGuncelle();
    }
    radarRenkUygula();
    // v2.4.42: HOME ikonlari da dronun renginden turer; tema degisince
    // canvas gorseli yeniden uretilmelidir (renk onbellekli).
    if (typeof window.dronHomeTazele === "function")
      window.dronHomeTazele();
    // FAZ18-IS23-LOK-IKON: lokasyon ikonlari da canvas'ta uretilir
    if (typeof window.lokasyonIkonTazele === "function")
      window.lokasyonIkonTazele();
  }
  // Arayuz
  document.documentElement.dataset.tema = (tema === "acik") ? "acik" : "";
  if (tema === "koyu") delete document.documentElement.dataset.tema;
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString(
    getComputedStyle(document.documentElement)
      .getPropertyValue("--dunya").trim() || "#0b0e11");
  btnKoyu.classList.toggle("secili", tema === "koyu");
  btnAcik.classList.toggle("secili", tema === "acik");
  // Kalici yap
  if (kaydet && ws && ws.readyState === 1){
    ws.send(JSON.stringify({tip:"tema", tema:tema}));
  }
}

btnKoyu.addEventListener("click", () => temaUygula("koyu", true));
btnAcik.addEventListener("click", () => temaUygula("acik", true));

/* ---- URUN LOGOSU ----
   v2.12.4: FIRMA LOGOSU DONGUSU KALDIRILDI.
   Onceki surumde "Program Hakkinda" penceresindeki logoya CTRL +
   tiklamayla firma logolari arasinda donuluyordu:
       TURKBEY -> VEILOX -> NOVIXAIR -> TURKBEY
   Marka gecisiyle firma logosu kullanimi tamamen kaldirildi; artik
   yalnizca GOKTUNGU urun logosu gosterilir.  Firma adi yalnizca
   sahiplik (telif) satirinda gecer.

   `gcs_logo` yerel saklama anahtari TEMIZLENIR: donguden kalan secim
   ("VEILOX" / "NOVIXAIR") tarayicida duruyor olabilir ve temizlenmezse
   ileride bu anahtari okuyan bir kod eski firma logosunu geri
   yazabilirdi.

   Tema uyumu: logo iki temada da okunur olmalidir.  `goktungu.webp`
   koyu tema icin (acik yazi), `goktungu_acik.webp` acik tema icin
   (koyu yazi) uretildi; secim asagida yapilir. */
(function(){
  const img = document.getElementById("sirketLogo");
  if (!img) return;
  try { localStorage.removeItem("gcs_logo"); } catch(e){}

  function logoSec(){
    const acik = document.documentElement
      .getAttribute("data-tema") === "acik";
    const yol = acik ? "goktungu_acik.webp" : "goktungu.webp";
    if (!img.src.endsWith(yol)) img.src = yol;
    img.alt = "GÖKTUNGU Komuta Kontrol";
  }
  logoSec();
  // Tema degisimi `data-tema` niteligi uzerinden yapiliyor; nitelik
  // izlenerek logo da birlikte degisir.
  new MutationObserver(logoSec).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-tema"] });
})();
// ---------------------------------------------------------------
// 2.4.237: FIRMA LOGOSU (Turkbey Teknoloji A.S.) — tema uyumu.
// Kullanici yeni logoyu yukledi (siyah cizgi, seffaf zemin). Koyu
// temada beyaz surum (`logo.png`), acik temada siyah surum
// (`logo_acik.png`) kullanilir; aksi halde koyu zeminde gorunmezdi.
// Kurumun merkezden gelen kendi logosu (sirket.js logoAta) bu
// secimin UZERINE yazar; burada yalniz varsayilan dosyalar degisir.
// ---------------------------------------------------------------
(function(){
  function firmaLogoSec(){
    const acik = document.documentElement.getAttribute("data-tema") === "acik";
    const yol = acik ? "logo_acik.png" : "logo.png";
    const diger = acik ? "logo.png" : "logo_acik.png";
    document.querySelectorAll("#logo, .giris-logo, #btnGokkubbeyeGit img").forEach(el => {
      const src = el.getAttribute("src") || "";
      // Yalniz varsayilan firma logosu degistirilir; merkezden atanmis
      // kurum logosu (data-sk-varsayilan-logo dolu) korunur.
      if (src === diger || src === "/" + diger) el.setAttribute("src", yol);
    });
  }
  firmaLogoSec();
  new MutationObserver(firmaLogoSec).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-tema"] });
})();
// ---------------------------------------------------------------
