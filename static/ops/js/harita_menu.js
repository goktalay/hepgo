// =================================================================
// GOKTUNGU - HARITA TIK MENUSU (dron listesi)
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).
// -----------------------------------------------------------------
// IKI KIP tek menu DOM'unu paylasir (#haritaMenu):
//   CTRL  + sol tik -> "BURAYA GIT"   : secilen dron o koordinata gider
//   SHIFT + sol tik -> "HOME AYARLA"  : secilen dronun HOME noktasi olur
//
// Ikinci bir menu penceresi YAZILMADI: iki akis da "koordinat sec ->
// dron sec -> komut gonder" seklinde ayni oldugu icin ayri DOM tutmak
// stil ve konumlandirma mantigini ikiye bolerdi.
// =================================================================
(function(){
  const menu = document.getElementById("haritaMenu");
  const menuKoord = document.getElementById("menuKoordinat");
  const menuListe = document.getElementById("menuDronListesi");
  if (!menu || !menuKoord || !menuListe) return;

  let menuHedefLat = 0, menuHedefLon = 0;
  // Aktif kip: "goto" (CTRL) | "home" (SHIFT)
  let menuKip = "goto";
  // Baslik ikonu kipe gore degisir; baslik elemani DOM'da sabittir.
  const baslikEl = menu.querySelector(".harita-menu-baslik");

  // Menu disina tiklaninca kapat
  function menuKapat(){ menu.classList.add("popup-gizli"); }
  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target)) menuKapat();
  });

  // Ekran konumundan cografi koordinat hesapla (harita uzerinde degilse null)
  function ekrandanKoordinat(x, y){
    if (typeof viewer === "undefined" || !viewer) return null;
    const cartesian = viewer.camera.pickEllipsoid(
      new Cesium.Cartesian2(x, y), viewer.scene.globe.ellipsoid);
    if (!cartesian) return null;
    const carto = Cesium.Cartographic.fromCartesian(cartesian);
    return {
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude)
    };
  }
  // Diger bloklarin da kullanabilmesi icin disari ac
  window.__ekrandanKoordinat = ekrandanKoordinat;

  // ---------------------------------------------------------------
  // Cizim/duzenleme modlari SHIFT tikini kendileri kullanabilir
  // ---------------------------------------------------------------
  // Olculdu (v2.4.42): rotalar.js, koridor.js ve serbest_form.js harita
  // tiklamalarinda yalniz ALT/CTRL'yi disliyor, SHIFT'i DISLAMIYOR.
  // Yani bu modlar acikken SHIFT + tik hem rota noktasi ekler hem HOME
  // menusu acardi. Cozum olarak o modullere shift dislamasi EKLENMEDI
  // (o zaman "SHIFT'e basili tutup cizim yapiyorum" senaryosunda nokta
  // sessizce kaybolurdu); yerine HOME menusu bu modlarda ACILMAZ.
  function cizimModuAktif(){
    if (window.__rotaDuzenlemeAktif && window.__rotaDuzenlemeAktif())
      return true;
    if (window.__cetvelAktif && window.__cetvelAktif()) return true;
    try {
      if (window.__koridorDurum && window.__koridorDurum().aktif)
        return true;
    } catch(_){ /* modul yuklu degilse yok say */ }
    try {
      if (window.__serbestFormDurum && window.__serbestFormDurum().aktif)
        return true;
    } catch(_){ /* modul yuklu degilse yok say */ }
    return false;
  }

  // ---------------------------------------------------------------
  // Menuyu doldur ve goster
  // ---------------------------------------------------------------
  function menuAc(kip, k, clientX, clientY){
    const t = (typeof D === "function") ? D() : {};
    menuKip = kip;
    menuHedefLat = k.lat; menuHedefLon = k.lon;

    // Bagli dronlari listele
    const bagliDronlar = Object.values(sonVeri).filter(dd => dd.baglanti);
    if (bagliDronlar.length === 0) return false;

    // Baslik: koordinat + kip etiketi. Kip etiketi olmadan iki akis
    // gorsel olarak ayni gorunur ve operator yanlis komut gonderebilir.
    const kipEtiket = (kip === "home")
      ? (t.hmHomeBaslik || "HOME AYARLA")
      : (t.hmGotoBaslik || "BURAYA G\u0130T");
    const kipIkon = (kip === "home") ? "fa-house-flag" : "fa-location-dot";
    if (baslikEl){
      baslikEl.innerHTML =
        "<i class='fa-solid " + kipIkon + "'></i> " +
        "<span class='hm-kip'>" + kipEtiket + "</span> " +
        "<span id='menuKoordinat'>" +
        k.lat.toFixed(5) + ", " + k.lon.toFixed(5) + "</span>";
    }
    menu.classList.toggle("hm-home-kip", kip === "home");

    menuListe.innerHTML = "";
    bagliDronlar.forEach(dd => {
      const item = document.createElement("div");
      item.className = "harita-menu-item";
      const nokta = document.createElement("span");
      nokta.className = "hm-nokta";
      nokta.style.background = dd.armed ? "var(--iyi)" : "var(--soluk)";
      const ad = document.createElement("span");
      ad.textContent = "D" + dd.sysid + " | " + (dd.tip || dd.isim || "DRON");
      ad.style.color = tipRengi(dd.tip);
      item.appendChild(nokta);
      item.appendChild(ad);
      // HOME kipinde dronun mevcut HOME durumu satirda gosterilir:
      // operator hangi araca HOME atandigini menude gorur.
      if (kip === "home"){
        const im = document.createElement("span");
        im.className = "hm-home-im";
        const varMi = (dd.home_lat !== null && dd.home_lat !== undefined &&
                       dd.home_lon !== null && dd.home_lon !== undefined);
        im.innerHTML = varMi
          ? "<i class='fa-solid fa-house-flag'></i>"
          : "<i class='fa-solid fa-triangle-exclamation'></i>";
        im.title = varMi
          ? (t.hmHomeVar || "HOME atanm\u0131\u015f \u2014 \u00fczerine yaz\u0131lacak")
          : (t.hmHomeYok || "HOME atanmam\u0131\u015f");
        im.classList.toggle("yok", !varMi);
        item.appendChild(im);
      }
      item.addEventListener("click", () => {
        if (kip === "home") homeAyarla(dd);
        else gotoGonder(dd);
      });
      menuListe.appendChild(item);
    });

    // Menuyu tiklanan noktada goster (ekran disina tasmasin)
    const mw = 240, mh = 40 + bagliDronlar.length * 34;
    menu.style.left = Math.min(clientX, window.innerWidth - mw - 8) + "px";
    menu.style.top = Math.min(clientY, window.innerHeight - mh - 8) + "px";
    menu.classList.remove("popup-gizli");
    return true;
  }

  function gotoGonder(dd){
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({
        tip: "dron_komut", sysid: dd.sysid, aksiyon: "goto",
        lat: menuHedefLat, lon: menuHedefLon
      }));
    }
    menuKapat();
  }

  // HOME ayarlama UCUS GUVENLIGINI dogrudan etkiler: RTL ve failsafe bu
  // noktaya doner. Bu yuzden ARM/DISARM/RTL ile ayni kaydirmali onay
  // istenir; yanlislikla tiklanan bir menu ogesi donus noktasini
  // sessizce tasiyamaz.
  function homeAyarla(dd){
    // Koordinatlar onay penceresi acilmadan ONCE yerel degiskene alinir:
    // menuKapat() sonrasi kullanici baska bir yere tiklarsa
    // menuHedefLat/Lon degisebilir ve onay verildiginde YANLIS konum
    // gonderilirdi.
    const lat = menuHedefLat, lon = menuHedefLon;
    const sysid = dd.sysid;
    menuKapat();
    const metin = (typeof onayMetni === "function")
      ? onayMetni("onayHomeKonum", {
          sysid: sysid, lat: lat.toFixed(5), lon: lon.toFixed(5) })
      : ("D" + sysid + " arac\u0131n\u0131n HOME noktas\u0131 " +
         lat.toFixed(5) + ", " + lon.toFixed(5) + " konumuna " +
         "ayarlanacak.");
    const gonder = () => {
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify({
          tip: "dron_komut", sysid: sysid, aksiyon: "set_home",
          lat: lat, lon: lon
        }));
      }
    };
    if (typeof onayIste === "function") onayIste(metin, gonder);
    else gonder();
  }

  // NOT: Cesium'un KeyboardEventModifier'li setInputAction'i bazi
  // tarayici/surumlerde tetiklenmiyor. Bu nedenle dogrudan DOM 'click'
  // olayini canvas konteyneri uzerinde dinliyoruz - e.ctrlKey guvenilirdir.
  function ctrlTikKur(){
    const kap = document.getElementById("cesiumContainer");
    if (!kap || typeof viewer === "undefined" || !viewer){
      setTimeout(ctrlTikKur, 500); return;
    }
    // v2.1.1: Dokunmatik cihaz destegi - son pointer'in dokunma olup
    // olmadigini izle. Parmakla tiklamada CTRL beklenmez (tablette
    // fiziksel klavye yoktur).
    let sonPointerDokunma = false;
    kap.addEventListener("pointerdown", (e) => {
      sonPointerDokunma = (e.pointerType === "touch" || e.pointerType === "pen");
    }, true);
    kap.addEventListener("click", (e) => {
      const dokunma = sonPointerDokunma ||
        (e.pointerType === "touch") ||
        (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents);

      // ---- Kip secimi ----
      // v2.4.42: SHIFT + sol tik HOME kipini acar. SHIFT once denetlenir
      // cunku CTRL+SHIFT birlikte basiliysa HOME kipi kazanir: CTRL
      // "goto" gibi tekrarlanabilir bir komut, HOME ise kalici bir
      // ayar; belirsizlikte daha acik niyetli olan (SHIFT) secilir.
      let kip = null;
      if (dokunma){
        if (e.altKey) return;   // ALT konum kaydetme her modda korunur
        // Dokunmatikta SHIFT yoktur; parmakla tiklama "goto" demektir.
        kip = e.shiftKey ? "home" : "goto";
      } else {
        if (e.altKey) return;   // ALT konum kaydetme icin
        if (e.shiftKey) kip = "home";
        else if (e.ctrlKey) kip = "goto";
        else return;            // ciplak tiklama bu modulun isi degil
      }

      if (kip === "home"){
        // Cizim/olcum modlari SHIFT tikini kendileri kullanir
        if (cizimModuAktif()) return;
      } else {
        // Rota duzenleme modunda CTRL, nokta tasima icin kullanilir
        if (window.__rotaDuzenlemeAktif && window.__rotaDuzenlemeAktif())
          return;
        // v2.1.1: Cetvel modunda sade tiklamalar cetvele aittir
        if (window.__cetvelAktif && window.__cetvelAktif() && !e.ctrlKey)
          return;
      }

      e.preventDefault(); e.stopPropagation();
      const r = kap.getBoundingClientRect();
      const k = ekrandanKoordinat(e.clientX - r.left, e.clientY - r.top);
      if (!k) return;
      menuAc(kip, k, e.clientX, e.clientY);
    }, true);  // capture: Cesium'un kendi handler'larindan once yakala
  }
  ctrlTikKur();
})();

// ---------------------------------------------------------------
