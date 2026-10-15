// =================================================================
// GÖKTUNGU — HARİTA ÜSTÜ ÇEVRİMİÇİ CİHAZ LİSTESİ (v2.4.220)
// -----------------------------------------------------------------
// Kullanıcı isteği: "Haritanın üzerinde en sağda alt alta sistemdeki tüm
// online cihazlar birer label olarak görünsün … hafif şeffaf olsun,
// üzerine gelip tıklayınca haritada o objeye zoom yapsın, cihaz offline
// olduğunda listeden çıksın".
//
// Kaynaklar (hepsi zaten istemcide olan veriler):
//   dron   : telemetri `dronlar` (window.dronlarSon; baglanti=true olanlar)
//   M50/EO : window.eoListesiOku() (m50_durum.bagli olanlar; konum varsa)
//   kamera : window._kameralarSon + telemetri `kamera_canli` (kare üreten)
// Zoom: dron → `dron_<sysid>` varlığı; M50 → `eo_<id>` varlığı; kamera →
// kendi lat/lon'u, yoksa bağlı lokasyonun varlığı (`lokasyon_<id>`).
// =================================================================
"use strict";
(function haritaCevrimici(){
  const T = () => (typeof D === "function" ? D() : {}) || {};
  let kap = null;
  let kameraCanli = new Set();
  let sonImza = "";

  window.haritaKameraCanliIsle = function(liste){
    kameraCanli = new Set((Array.isArray(liste) ? liste : []).map(Number));
  };

  function kapKur(){
    if (kap && document.body.contains(kap)) return kap;
    const harita = document.getElementById("cesiumContainer");
    if (!harita) return null;
    kap = document.createElement("div");
    kap.id = "haritaCevrimici";
    kap.className = "hc-liste";
    (harita.parentElement || document.body).appendChild(kap);
    return kap;
  }

  function ucus(entity, lat, lon, yuk){
    if (typeof viewer === "undefined" || !viewer) return;
    try {
      if (entity){
        viewer.flyTo(entity, { duration: 1.2, offset: new Cesium.HeadingPitchRange(0, -Cesium.Math.PI_OVER_FOUR, 900) });
        return;
      }
      if (Number.isFinite(lat) && Number.isFinite(lon))
        viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, Math.max(600, (yuk || 0) + 600)), duration: 1.2 });
    } catch (e) {}
  }

  function topla(){
    const t = T();
    const ogeler = [];
    // Dronlar
    for (const d of (window.dronlarSon || [])){
      if (!d || !d.baglanti) continue;
      const ad = d.kullanici_isim || d.isim || d.tip || ("SYS" + d.sysid);
      ogeler.push({ anahtar: "dron_" + d.sysid, tur: "dron", ikon: "fa-plane-up", ad,
        tik: () => ucus((typeof viewer !== "undefined" && viewer) ? viewer.entities.getById("dron_" + d.sysid) : null, d.lat, d.lon, d.yuk || d.alt) });
    }
    // M50 / EO
    const eo = (typeof window.eoListesiOku === "function") ? window.eoListesiOku() : [];
    for (const c of eo){
      const dd = (c && c.m50_durum) || {};
      if (!dd.bagli) continue;
      const k = c.konum && typeof c.konum === "object" ? c.konum : null;
      ogeler.push({ anahtar: "eo_" + c.eo_id, tur: "m50", ikon: "fa-binoculars", ad: c.isim || ("M50 " + c.eo_id),
        tik: () => {
          const ent = (typeof viewer !== "undefined" && viewer) ? viewer.entities.getById("eo_" + c.eo_id) : null;
          ucus(ent, k ? Number(k.lat) : NaN, k ? Number(k.lon) : NaN, 0);
        } });
    }
    // Kameralar (M50 kayıtları EO altında sayılır)
    for (const kam of (window._kameralarSon || [])){
      if (!kam || String(kam.protokol || "").toLowerCase() === "m50") continue;
      if (!kameraCanli.has(Number(kam.id))) continue;
      ogeler.push({ anahtar: "kam_" + kam.id, tur: "kamera", ikon: "fa-video", ad: kam.isim || ("#" + kam.id),
        tik: () => {
          const lat = Number(kam.lat), lon = Number(kam.lon);
          if (Number.isFinite(lat) && Number.isFinite(lon) && (lat || lon)) { ucus(null, lat, lon, 0); return; }
          const ent = (kam.lokasyon_id && typeof viewer !== "undefined" && viewer) ? viewer.entities.getById("lokasyon_" + kam.lokasyon_id) : null;
          if (ent) ucus(ent);
          else if (typeof window.kameraGoruntuHedefiAyarla === "function") window.kameraGoruntuHedefiAyarla(kam.id, "yuzen");
        } });
    }
    return ogeler;
  }

  function ciz(){
    const k = kapKur();
    if (!k) return;
    const t = T();
    const ogeler = topla();
    const imza = ogeler.map(o => o.anahtar + ":" + o.ad).join("|");
    if (imza === sonImza) return;
    sonImza = imza;
    k.innerHTML = "";
    if (!ogeler.length){ k.classList.add("bos"); return; }
    k.classList.remove("bos");
    const bas = document.createElement("div"); bas.className = "hc-baslik";
    bas.textContent = (t.hcBaslik || "ÇEVRİMİÇİ") + " · " + ogeler.length;
    k.appendChild(bas);
    for (const o of ogeler){
      const el = document.createElement("button"); el.type = "button"; el.className = "hc-oge hc-" + o.tur;
      el.innerHTML = "<i class='fa-solid " + o.ikon + "'></i><span></span>";
      el.querySelector("span").textContent = o.ad;
      el.title = (t.hcZoomIpucu || "Haritada göster") + ": " + o.ad;
      el.addEventListener("click", ev => { ev.stopPropagation(); o.tik(); });
      k.appendChild(el);
    }
  }

  // Telemetri ~her saniye; ucuz imza kıyası ile yalnız değişince çizilir
  setInterval(() => { try { ciz(); } catch (e) {} }, 1000);
})();
