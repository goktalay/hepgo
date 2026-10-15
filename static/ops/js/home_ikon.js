// =================================================================
// GOKTUNGU v2.4.42 - HOME (kalkis/donus) NOKTASI HARITA IKONU
// -----------------------------------------------------------------
// Her dronun HOME noktasi haritada DRONUN RENGINDE bir ev isaretiyle
// gosterilir. Renk kaynagi `dronRengi(sysid)` (dronlar.js:87): dron
// ikonu, hareket izi ve etiket ile AYNI kaynak. Boylece operator hangi
// HOME'un hangi araca ait oldugunu renkten okur.
//
// Yukseklik: ikon `CLAMP_TO_GROUND` ile ARAZIYE KENETLENIR; telemetriden
// gelen `home_alt` (AMSL) KULLANILMAZ. Gerekce: elipsoid referansli
// yerlestirme terrain acikken ikonu arazinin yuzlerce metre altinda
// birakiyor ve kamera dondukce ekranda kaydiriyordu (v2.4.29'da olculdu,
// dronlar.js:188-196'daki not). HOME zeminde durdugu icin kenetleme
// hem dogru hem de arazi verisi kapali/acik farkindan bagimsizdir.
//
// Ikon canvas'ta cizilir: harici gorsel dosyasi YOK (saha kurulumlari
// internetsiz calisir).
// =================================================================
(function(){
  const homeVarliklar = {};        // sysid -> Cesium entity
  const ikonOnbellek = {};         // renk -> dataURL

  // Ev ikonu. Taban ikonun ALT KENARINA oturur; billboard
  // `verticalOrigin: BOTTOM` ile yerlestirildiginde evin tabani tam
  // olarak HOME koordinatina gelir.
  // IS162 (kullanici istegi): HOME ikonu artik DAIRE ICINDE "H" (standart
  // helipad/home sembolu). Daire dronun renginde; H beyaz. Siyah kenar her
  // altlikta okunurluk saglar.
  function homeIkonu(renk){
    if (ikonOnbellek[renk]) return ikonOnbellek[renk];
    const b = 48;
    const c = document.createElement("canvas");
    c.width = b; c.height = b;
    const x = c.getContext("2d");
    const cx = b / 2, cy = b / 2, r = b * 0.42;
    // dis daire: dron rengi dolgu + siyah kenar
    x.beginPath(); x.arc(cx, cy, r, 0, Math.PI * 2);
    x.fillStyle = renk; x.fill();
    x.lineWidth = 3; x.strokeStyle = "rgba(0,0,0,.85)"; x.stroke();
    // H harfi (beyaz, kalin)
    x.fillStyle = "#ffffff";
    x.font = "bold " + Math.round(b * 0.52) + "px Arial";
    x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText("H", cx, cy + b * 0.02);
    const url = c.toDataURL();
    ikonOnbellek[renk] = url;
    return url;
  }

  function renkAl(sysid){
    if (typeof dronRengi === "function") return dronRengi(sysid);
    return "#c07bff";
  }

  function guncelle(d){
    if (typeof viewer === "undefined" || !viewer || !d) return;
    const sysid = d.sysid;
    const hlat = d.home_lat, hlon = d.home_lon;
    // HOME bilinmiyorsa (otopilot bildirmedi veya atanmamis) ikon
    // SILINIR. Eski konumda bayrak birakmak, HOME'un hala orada
    // oldugu izlenimi verir ve operatoru yanlis yonlendirirdi.
    if (!window.gecerliKonumMu(hlat, hlon)){ /* FAZ18-IS29C */
      sil(sysid);
      return;
    }
    const renk = renkAl(sysid);
    const t = (typeof D === "function") ? D() : {};
    const etiket = (t.homeIkonEtiket || "HOME") + " D" + sysid;
    // Baglanti kopukken soluklastir - dron ikonuyla ayni gorsel dil
    const alfa = d.baglanti ? 1.0 : 0.4;

    let e = homeVarliklar[sysid];
    if (!e){
      e = viewer.entities.add({
        id: "dron_home_" + sysid,
        position: Cesium.Cartesian3.fromDegrees(hlon, hlat, 0),
        billboard: {
          image: homeIkonu(renk),
          width: 28, height: 28,
          verticalOrigin: Cesium.VerticalOrigin.CENTER,   // IS162: daire home noktasinda ortali
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          // dron ikonu HOME ile ayni konumdayken ustte kalsin: eyeOffset +z
          // gorus ekseni boyunca ekrana ICERI iter (ekran konumu kaymaz),
          // boylece HOME dron ikonunun ARKASINA cizilir.
          eyeOffset: new Cesium.Cartesian3(0.0, 0.0, 100.0),
          color: Cesium.Color.WHITE.withAlpha(alfa),
        },
        label: {
          text: etiket,
          font: "bold 10px Consolas, monospace",
          fillColor: Cesium.Color.fromCssColorString(renk),
          style: Cesium.LabelStyle.FILL,
          showBackground: true,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.7),
          backgroundPadding: new Cesium.Cartesian2(5, 3),
          verticalOrigin: Cesium.VerticalOrigin.TOP,
          pixelOffset: new Cesium.Cartesian2(0, 4),
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          // Uzaklasinca etiket kalabaligi yapmasin; ikon gorunur kalir
          distanceDisplayCondition:
            new Cesium.DistanceDisplayCondition(0, 40000),
        },
      });
      e._hLat = hlat; e._hLon = hlon; e._hRenk = renk;
      homeVarliklar[sysid] = e;
      return;
    }
    // Konum yalnizca GERCEKTEN degistiyse yazilir: HOME 5 saniyede bir
    // gelir ve genelde sabittir; her pakette Cartesian3 uretmek bosa
    // nesne ayirmadir.
    if (e._hLat !== hlat || e._hLon !== hlon){
      e.position = Cesium.Cartesian3.fromDegrees(hlon, hlat, 0);
      e._hLat = hlat; e._hLon = hlon;
    }
    if (e._hRenk !== renk){
      e.billboard.image = homeIkonu(renk);
      e.label.fillColor = Cesium.Color.fromCssColorString(renk);
      e._hRenk = renk;
    }
    e.billboard.color = Cesium.Color.WHITE.withAlpha(alfa);
    e.label.text = etiket;
  }

  function sil(sysid){
    const e = homeVarliklar[sysid];
    if (!e) return;
    try { viewer.entities.remove(e); } catch(_){ /* viewer kapanmis */ }
    delete homeVarliklar[sysid];
  }

  // Tema veya dil degisiminde ikon gorselini ve etiketi yeniden uret.
  // `sonVeri` (dronlar.js:79) son telemetriyi tutar; ikon yalnizca hala
  // veri gelen dronlar icin tazelenir, gerisi silinir.
  function tazele(){
    Object.keys(homeVarliklar).forEach((sysid) => {
      const d = (typeof sonVeri !== "undefined") ? sonVeri[sysid] : null;
      if (!d){ sil(sysid); return; }
      const e = homeVarliklar[sysid];
      if (e) e._hRenk = null;    // renk yeniden yazilmaya zorlanir
      guncelle(d);
    });
  }

  window.dronHomeGuncelle = guncelle;
  window.dronHomeSil = sil;
  window.dronHomeTazele = tazele;
})();
