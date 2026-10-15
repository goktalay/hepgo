// ============================================================
// GOKTUNGU GCS — HARITA 3B IKON MOTORU (IS151)  [glTF model surumu]
// ------------------------------------------------------------
// AMAC (kullanici istegi):
//   1) Sabit kanat  -> 3B ucak; burun heading yonunde, pitch/roll uygulanir
//   2) Multirotor   -> arac tipine gore kol sayisi (quad/hexa/octo/tri/heli)
//   3) Her tipte    -> onunde kucuk yon ucgeni (modele gomulu)
//   4) Radar        -> surekli DONEN 3B anten (Cesium orientation ile)
//   5) Elektro-optik-> 3B gimbal + kamera; yon ucgeni
//
// NEDEN glTF MODEL (v2.4.254):
//   Cesium'un box/cylinder GEOMETRISI ekran boyutu tabanina sahip degildir;
//   uzak zoom'da bir kac piksele duser ve gorunmez olur (kullanici bildirdi).
//   glTF `model` ise `minimumPixelSize` ile HER zoom'da gorunur kalir (eski
//   billboard gibi). Modeller yerelde uretildi (models/*.glb), cevrimdisi
//   calisir, harici kaynak/CSP gerektirmez. Renk: model.color (MIX) ile drona
//   gore. Konum: heightReference RELATIVE_TO_GROUND -> terrain kaymasi Cesium'da.
// ============================================================
(function () {
  "use strict";

  var YOL = "models/";
  var MODELLER = {
    ucak: "ucak.glb", quad: "quad.glb", hexa: "hexa.glb", octo: "octo.glb",
    tri: "tri.glb", heli: "heli.glb", radar: "radar.glb", eo: "eo.glb",
  };
  var MIN_PIKSEL = 99;     // IS160: %50 buyutuldu (66 -> 99), her zoom'da gorunur
  var MODEL_OLCEK = 1.5;   // IS160: 3B model %50 buyuk (yakin gorusto)
  var MAKS_OLCEK = 6000;   // asiri yakinda devasa olmasin (metre)

  function viewerVar() {
    return (typeof viewer !== "undefined" && viewer && viewer.entities) ? viewer : null;
  }
  function cesiumVar() { return typeof Cesium !== "undefined"; }

  function renkNesne(r) {
    try { return Cesium.Color.fromCssColorString(r); }
    catch (e) { return Cesium.Color.WHITE; }
  }

  // arac_tipi (MAV_TYPE) -> model turu
  function tipCoz(aracTipi) {
    var mt = Number(aracTipi || 0);
    if (mt === 1) return "ucak";
    if (mt === 4) return "heli";
    if (mt === 2 || mt === 3) return "quad";
    if (mt === 13) return "hexa";
    if (mt === 14) return "octo";
    if (mt === 15) return "tri";
    if ([19, 20, 21, 22, 23, 24, 25].indexOf(mt) >= 0) return "ucak"; // VTOL
    return "quad";
  }

  var rigler = {};   // anaId -> {ent, tur, renk, poz:{lat,lon,yuk,h,p,r}, spin}

  function orient(kayit) {
    var p = kayit.poz;
    var pos = Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.yuk);
    var h = p.h;
    if (kayit.spin) h = (p.h || 0) + ((Date.now() / 1000) * kayit.spin);
    var hpr = new Cesium.HeadingPitchRoll(
      Cesium.Math.toRadians(h || 0),
      Cesium.Math.toRadians(p.p || 0),
      Cesium.Math.toRadians(p.r || 0));
    return Cesium.Transforms.headingPitchRollQuaternion(pos, hpr);
  }

  function kur(anaId, tur, renk) {
    var v = viewerVar(); if (!v) return null;
    var kayit = rigler[anaId];
    if (kayit && kayit.tur === tur) return kayit;   // model dogru
    if (kayit) { try { v.entities.remove(kayit.ent); } catch (e) {} }
    kayit = { tur: tur, renk: null, poz: { lat: 0, lon: 0, yuk: 0, h: 0, p: 0, r: 0 }, spin: 0, ent: null };
    var self = kayit;
    kayit.ent = v.entities.add({
      id: anaId,
      position: new Cesium.CallbackProperty(function () {
        var p = self.poz;
        return Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.yuk);
      }, false),
      orientation: new Cesium.CallbackProperty(function () {
        return orient(self);
      }, false),
      model: {
        uri: YOL + MODELLER[tur],
        scale: MODEL_OLCEK,
        minimumPixelSize: MIN_PIKSEL,
        maximumScale: MAKS_OLCEK,
        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        colorBlendMode: Cesium.ColorBlendMode.MIX,
        colorBlendAmount: 0.55,
        // arazi/nesne arkasinda kalsa bile gorunur (eski ikon davranisi)
        // (model icin ayri bir bayrak yok; distanceDisplayCondition YOK ki her
        //  mesafede gorunsun)
      },
    });
    rigler[anaId] = kayit;
    return kayit;
  }

  function uygula(anaId, tur, sec, spin) {
    if (!cesiumVar() || !viewerVar()) return null;
    var k = kur(anaId, tur, sec.renk);
    if (!k) return null;
    k.poz = {
      lat: sec.lat, lon: sec.lon,
      yuk: Math.max(0, sec.yuk || 0),
      h: (typeof sec.heading === "number") ? sec.heading : 0,
      p: (typeof sec.pitch === "number") ? sec.pitch : 0,
      r: (typeof sec.roll === "number") ? sec.roll : 0,
    };
    k.spin = spin || 0;
    if (k.renk !== sec.renk) {
      k.renk = sec.renk;
      try { k.ent.model.color = renkNesne(sec.renk); } catch (e) {}
    }
    return k;
  }

  var API = {
    hazir: function () { return cesiumVar() && !!viewerVar(); },
    dron: function (anaId, sec) { return uygula(anaId, tipCoz(sec.aracTipi), sec, 0); },
    radar: function (anaId, sec) {
      return uygula(anaId, "radar",
        { lat: sec.lat, lon: sec.lon, yuk: sec.yuk, heading: sec.heading || 0, renk: sec.renk },
        90);   // 90 derece/sn doner
    },
    eo: function (anaId, sec) {
      return uygula(anaId, "eo",
        { lat: sec.lat, lon: sec.lon, yuk: sec.yuk, heading: sec.azimut || 0, renk: sec.renk }, 0);
    },
    var: function (anaId) { return !!rigler[anaId]; },
    sil: function (anaId) {
      var k = rigler[anaId]; if (!k) return;
      try { viewerVar() && viewer.entities.remove(k.ent); } catch (e) {}
      delete rigler[anaId];
    },
    tumunuSil: function () { for (var id in rigler) if (rigler.hasOwnProperty(id)) this.sil(id); },
  };
  window.IkonMuh = API;

  // ---------------------------------------------------------------
  // TOGGLE: Harita Ayarlari > "3B ikonlar" (varsayilan ACIK)
  // ---------------------------------------------------------------
  var ANAHTAR = "gcs_ikon_3d";
  function acikMi() {
    var v = null;
    try { v = localStorage.getItem(ANAHTAR); } catch (e) {}
    return v === null ? true : v === "1";
  }
  window.ikon3dAcik = acikMi;
  window.ikon3dAyarla = function (deger) {
    try { localStorage.setItem(ANAHTAR, deger ? "1" : "0"); } catch (e) {}
    if (!deger) { try { API.tumunuSil(); } catch (e) {} }
    dugmeTazele();
    try { if (typeof window.ikonModuTazele === "function") window.ikonModuTazele(); } catch (e) {}
  };
  function dugmeTazele() {
    var b = document.getElementById("btn3dIkon");
    if (!b) return;
    var t = (typeof D === "function" ? D() : {}) || {};
    b.classList.toggle("secili", acikMi());
    var sp = b.querySelector("span");
    if (sp) sp.textContent = acikMi()
      ? (t.lblAcik || t.lblTerrainAcik || "AÇIK")
      : (t.lblKapali || "KAPALI");
  }
  window.ikon3dDugmeTazele = dugmeTazele;
  function dugmeKur() {
    var b = document.getElementById("btn3dIkon");
    if (!b) { setTimeout(dugmeKur, 500); return; }
    b.addEventListener("click", function () { window.ikon3dAyarla(!acikMi()); });
    dugmeTazele();
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", dugmeKur);
  else dugmeKur();
})();
