// FAZ18-IS27-28-30: ikon+metin dugmelerinde metin <span> icine
// sarildi. Sebep: dugme_birlik.css yalniz-ikon kurali
// `:has(> i):not(:has(> span))` bu dugmeleri 26px kareye
// zorluyordu ve metin tasiyordu. CSS EZILMEDI; sozlesmeye
// uyuldu. Yalniz-ikon dugmelere DOKUNULMADI.
// =================================================================
// GOKTUNGU v2.5.0 - YAKINLIK ALGILAYICISI (PROXIMITY)
// -----------------------------------------------------------------
// Kullanici sartnamesi (FAZ11_proximity_tasarim.md):
//   1. Pencerenin ortasinda UC BOYUTLU dron govdesi
//   2. Govdenin cevresinde ALTI yon dugmesi (on/arka/sol/sag/alt/ust)
//      — dugmeler govdenin ilgili yuzunde konumlanir, salt liste DEGIL
//   3. Govde fare/dokunma ile dondurulebilir
//   4. Yon dugmesine tiklayinca o yonun penceresi acilir
//   5. Yapilandirma gecerliyse haritada dron ikonunun cevresinde
//      YALNIZ acik yonlerde 3B kalkan gorunur, uzerinde menzil metresi
//
// 3B govde: CSS 3B donusumu (Cesium/WebGL DEGIL). Neden: pencere icinde
// ikinci bir WebGL baglami acmak harita basarimini dusurur.
//
// PARAMETRE GERILIMI (olculdu, FAZ11_kalkan_tasarim.md):
// ArduPilot'ta YON BASINA parametre YOKTUR; parametreler ALGILAYICI
// basinadir (PRXn_TYPE / PRXn_ORIENT / PRXn_MIN / PRXn_MAX).
// Bu yuzden yon penceresi:
//   - o yonun CANLI olcumunu gosterir (prx_yonler[orientation])
//   - o yone BAKAN algilayicinin parametrelerini duzenletir
//   - eslesen algilayici yoksa uydurma deger GOSTERMEZ
// =================================================================
(function () {
  "use strict";

  // ---------------------------------------------------------------
  // YON SOZLESMESI (MAVLink MAV_SENSOR_ORIENTATION)
  // ---------------------------------------------------------------
  // Arayuzde ALTI yon gosterilir (kullanici sartnamesi). Ara yonler
  // (45/135/225/315) haritada cizilir ama govde secicide yer almaz —
  // aksi halde alti dugme yerine on dugme olur ve secici okunmaz.
  const YONLER = [
    { k: 0,  ad: "\u00d6n",        adEn: "Front", ikon: "fa-arrow-up",
      yuz: "on",   bearing: 0 },
    { k: 4,  ad: "Arka",           adEn: "Rear",  ikon: "fa-arrow-down",
      yuz: "arka", bearing: 180 },
    { k: 6,  ad: "Sol",            adEn: "Left",  ikon: "fa-arrow-left",
      yuz: "sol",  bearing: 270 },
    { k: 2,  ad: "Sa\u011f",       adEn: "Right", ikon: "fa-arrow-right",
      yuz: "sag",  bearing: 90 },
    { k: 25, ad: "\u00dcst",       adEn: "Up",    ikon: "fa-arrow-up",
      yuz: "ust",  bearing: null, dikey: 1 },
    { k: 24, ad: "Alt",            adEn: "Down",  ikon: "fa-arrow-down",
      yuz: "alt",  bearing: null, dikey: -1 }
  ];
  // Haritada cizilecek TUM yonler (ara yonler dahil)
  const HARITA_YONLER = {
    0:  { bearing: 0,   dikey: 0 },
    1:  { bearing: 45,  dikey: 0 },
    2:  { bearing: 90,  dikey: 0 },
    3:  { bearing: 135, dikey: 0 },
    4:  { bearing: 180, dikey: 0 },
    5:  { bearing: 225, dikey: 0 },
    6:  { bearing: 270, dikey: 0 },
    7:  { bearing: 315, dikey: 0 },
    24: { bearing: 0,   dikey: -1 },
    25: { bearing: 0,   dikey: 1 }
  };
  // PRXn_ORIENT degeri -> MAVLink orientation. ArduPilot'ta PRXn_ORIENT
  // 0=ileri, 1=sag, ... seklinde SEKIZ yon alir; ayni MAV_SENSOR_
  // ORIENTATION olcegini kullanir. Alt/ust icin ORIENT yoktur
  // (asagi bakan algilayici PRXn_TYPE ile ayarlanir, yonu sabittir).
  const ALGILAYICI_SAYISI = 4;   // PRX1..PRX4 (ArduPilot 4.5+)

  function sozluk() { return (typeof D === "function") ? D() : {}; }
  function enMi() {
    return (typeof aktifDil !== "undefined" && aktifDil === "EN");
  }
  function yonAdi(y) { return enMi() ? y.adEn : y.ad; }
  function wsGonder(n) {
    if (typeof ws !== "undefined" && ws && ws.readyState === 1) {
      ws.send(JSON.stringify(n)); return true;
    }
    return false;
  }
  function dronVeri(sysid) {
    if (typeof sonVeri !== "undefined" && sonVeri) return sonVeri[sysid] || null;
    return null;
  }
  function onbellek(sysid) {
    const o = window.dronAyarParamOnbellek || {};
    return o[sysid] || {};
  }

  // ===============================================================
  // 1. ANA PENCERE — 3B GOVDE SECICI
  // ===============================================================
  const acikPencereler = {};   // sysid -> {pop, timer}

  function yakinlikAc(fare, sysid) {
    const t = sozluk();
    if (dkPopupTekil("dpxAna_" + sysid)) return;
    const pop = document.createElement("div");
    pop.id = "dpxAna_" + sysid;
    pop.className = "dk-mini-popup dpx-pencere";
    dkMiniPopupBaslikKur(pop,
      (t.dpxBaslik || "YAKINLIK ALGILAYICISI") + " \u2014 D" + sysid,
      null, "fa-shield-halved");

    const govde = document.createElement("div");
    govde.className = "dpx-govde";
    pop.appendChild(govde);

    // --- Durum seridi: kac yon acik, son olcum ani
    const durum = document.createElement("div");
    durum.className = "dpx-durum";
    govde.appendChild(durum);

    // --- 3B sahne
    const sahne = document.createElement("div");
    sahne.className = "dpx-sahne";
    const kutu = document.createElement("div");
    kutu.className = "dpx-kutu";
    sahne.appendChild(kutu);
    govde.appendChild(sahne);

    // Govde: alti yuzlu kutu + dort kol (multikopter silueti)
    kutu.innerHTML =
      "<div class='dpx-yuz dpx-y-on'></div>" +
      "<div class='dpx-yuz dpx-y-arka'></div>" +
      "<div class='dpx-yuz dpx-y-sol'></div>" +
      "<div class='dpx-yuz dpx-y-sag'></div>" +
      "<div class='dpx-yuz dpx-y-ust'></div>" +
      "<div class='dpx-yuz dpx-y-alt'></div>" +
      "<div class='dpx-kol dpx-k1'><div class='dpx-pervane'></div></div>" +
      "<div class='dpx-kol dpx-k2'><div class='dpx-pervane'></div></div>" +
      "<div class='dpx-kol dpx-k3'><div class='dpx-pervane'></div></div>" +
      "<div class='dpx-kol dpx-k4'><div class='dpx-pervane'></div></div>" +
      "<div class='dpx-burun'><i class='fa-solid fa-caret-up'></i></div>";

    // Alti yon dugmesi — kutunun ilgili yuzunde konumlanir
    const dugmeler = {};
    for (const y of YONLER) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "dpx-yon dpx-yon-" + y.yuz;
      b.dataset.yon = String(y.k);
      b.innerHTML =
        "<i class='fa-solid " + y.ikon + " dpx-yon-ikon'></i>" +
        "<span class='dpx-yon-ad'></span>" +
        "<span class='dpx-yon-deg'>\u2014</span>";
      b.querySelector(".dpx-yon-ad").textContent = yonAdi(y);
      b.title = yonAdi(y);
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        yonPenceresiAc({ x: ev.clientX, y: ev.clientY }, sysid, y);
      });
      kutu.appendChild(b);
      dugmeler[y.k] = b;
    }

    // --- Dondurme (fare + dokunma)
    let donX = -22, donY = 34, surukluyor = false, bx = 0, by = 0;
    function uygula() {
      kutu.style.transform =
        "rotateX(" + donX + "deg) rotateY(" + donY + "deg)";
    }
    uygula();
    function basla(cx, cy) { surukluyor = true; bx = cx; by = cy; sahne.classList.add("suruklu"); }
    function hareket(cx, cy) {
      if (!surukluyor) return;
      donY += (cx - bx) * 0.55;
      donX -= (cy - by) * 0.55;
      donX = Math.max(-88, Math.min(88, donX));
      bx = cx; by = cy;
      uygula();
    }
    function bitir() { surukluyor = false; sahne.classList.remove("suruklu"); }
    sahne.addEventListener("pointerdown", (e) => {
      // Yon dugmesine basildiysa dondurme baslatma
      if (e.target.closest(".dpx-yon")) return;
      basla(e.clientX, e.clientY);
      e.preventDefault();
    });
    window.addEventListener("pointermove", (e) => hareket(e.clientX, e.clientY));
    window.addEventListener("pointerup", bitir);
    window.addEventListener("pointercancel", bitir);

    // Sifirla dugmesi
    const araclar = document.createElement("div");
    araclar.className = "dpx-araclar";
    const btnSifir = document.createElement("button");
    btnSifir.type = "button";
    btnSifir.className = "dpx-arac-btn";
    btnSifir.innerHTML = "<i class='fa-solid fa-rotate-left'></i> " + "<span>" + (
      (t.dpxSifirla || "G\u00f6r\u00fcn\u00fcm\u00fc s\u0131f\u0131rla")) + "</span>";
    btnSifir.addEventListener("click", () => {
      donX = -22; donY = 34; uygula();
    });
    araclar.appendChild(btnSifir);
    // Harita kalkani ac/kapat
    const btnKalkan = document.createElement("button");
    btnKalkan.type = "button";
    btnKalkan.className = "dpx-arac-btn";
    function kalkanYazi() {
      return "<i class='fa-solid fa-shield-halved'></i> " +
        (kalkanEtkin(sysid)
          ? (t.dpxKalkanKapat || "Harita kalkan\u0131: A\u00c7IK")
          : (t.dpxKalkanAc || "Harita kalkan\u0131: KAPALI"));
    }
    btnKalkan.innerHTML = kalkanYazi();
    btnKalkan.classList.toggle("etkin", kalkanEtkin(sysid));
    btnKalkan.addEventListener("click", () => {
      kalkanAyarla(sysid, !kalkanEtkin(sysid));
      btnKalkan.innerHTML = kalkanYazi();
      btnKalkan.classList.toggle("etkin", kalkanEtkin(sysid));
    });
    araclar.appendChild(btnKalkan);
    govde.appendChild(araclar);

    // --- Algilayici ozeti
    const ozet = document.createElement("div");
    ozet.className = "dpx-ozet";
    govde.appendChild(ozet);

    pop.style.position = "fixed";
    dkPopupOneGetirKur(pop);
    document.body.appendChild(pop);
    dkMiniPopupKonumla(pop, fare);

    // Parametreleri onbellekten iste (taze:false — drona istek ATMAZ)
    wsGonder({ tip: "param_tumu", sysid: Number(sysid), taze: false });

    // Canli guncelleme
    const timer = setInterval(() => {
      if (!pop.isConnected) {
        clearInterval(timer);
        delete acikPencereler[sysid];
        return;
      }
      const d = dronVeri(sysid);
      const yonler = (d && d.prx_yonler) || {};
      let acik = 0;
      for (const y of YONLER) {
        const b = dugmeler[y.k];
        const o = yonler[String(y.k)];
        const degEl = b.querySelector(".dpx-yon-deg");
        if (o && typeof o.mesafe === "number") {
          acik++;
          degEl.textContent = o.mesafe.toFixed(2) + " m";
          b.classList.add("acik");
          // Yakinlik derecesi: min sinira yaklastikca kirmizi
          const mn = (typeof o.min === "number" && o.min > 0) ? o.min : 0.2;
          const mx = (typeof o.max === "number" && o.max > 0) ? o.max : 8;
          const oran = Math.max(0, Math.min(1, (o.mesafe - mn) / Math.max(0.01, mx - mn)));
          b.classList.toggle("tehlike", oran < 0.25);
          b.classList.toggle("uyari", oran >= 0.25 && oran < 0.55);
        } else {
          degEl.textContent = "\u2014";
          b.classList.remove("acik", "tehlike", "uyari");
        }
      }
      // Ara yonler de sayilsin (haritada cizilir)
      let toplamAcik = Object.keys(yonler).length;
      const yas = (d && d.prx_ts) ? (Date.now() / 1000 - Number(d.prx_ts)) : null;
      durum.textContent = "";
      const rozet = document.createElement("span");
      rozet.className = "dpx-rozet " + (toplamAcik ? "iyi" : "bos");
      rozet.textContent = toplamAcik
        ? (t.dpxAcikYon || "Etkin y\u00f6n") + ": " + toplamAcik
        : (t.dpxVeriYok || "Yak\u0131nl\u0131k verisi gelmiyor");
      durum.appendChild(rozet);
      if (yas !== null && yas < 3600) {
        const s = document.createElement("span");
        s.className = "dpx-yas" + (yas > 3 ? " bayat" : "");
        s.textContent = (t.dpxSonOlcum || "son \u00f6l\u00e7\u00fcm") + ": " +
          (yas < 1 ? "<1" : Math.round(yas)) + " s";
        durum.appendChild(s);
      }
      ozetCiz(ozet, sysid);
    }, 500);
    acikPencereler[sysid] = { pop: pop, timer: timer };
  }

  // Algilayici ozeti: PRX1..PRX4 tipleri ve yonleri
  function ozetCiz(kap, sysid) {
    const t = sozluk();
    const p = onbellek(sysid);
    if (!Object.keys(p).length) {
      if (kap.dataset.bos === "1") return;
      kap.dataset.bos = "1";
      kap.textContent = "";
      const u = document.createElement("div");
      u.className = "dpx-ozet-uyari";
      u.textContent = t.dpxParamYok ||
        "Algilayici parametreleri \u00f6nbellekte yok. Parametreler " +
        "ekran\u0131ndan T\u00dcM\u00dcN\u00dc AL yap\u0131n.";
      kap.appendChild(u);
      return;
    }
    // Degismediyse yeniden cizme (her 500 ms DOM yenilemesi gereksiz)
    const imza = algilayiciImza(p);
    if (kap.dataset.imza === imza) return;
    kap.dataset.imza = imza;
    kap.dataset.bos = "0";
    kap.textContent = "";
    const bas = document.createElement("div");
    bas.className = "dpx-ozet-bas";
    bas.textContent = t.dpxAlgilayicilar || "ALGILAYICILAR";
    kap.appendChild(bas);
    let varMi = false;
    for (let i = 1; i <= ALGILAYICI_SAYISI; i++) {
      const tip = p["PRX" + i + "_TYPE"];
      if (tip === undefined || Number(tip) === 0) continue;
      varMi = true;
      const s = document.createElement("div");
      s.className = "dpx-ozet-sat";
      const ad = document.createElement("span");
      ad.className = "dpx-ozet-ad";
      ad.textContent = "PRX" + i;
      const bilgi = document.createElement("span");
      bilgi.className = "dpx-ozet-bilgi";
      const parcalar = [(t.dpxTip || "tip") + " " + Number(tip)];
      const orient = p["PRX" + i + "_ORIENT"];
      if (orient !== undefined) {
        parcalar.push((t.dpxYon || "y\u00f6n") + " " + Number(orient));
      }
      const mn = p["PRX" + i + "_MIN"], mx = p["PRX" + i + "_MAX"];
      if (mn !== undefined && mx !== undefined) {
        parcalar.push(Number(mn) + "\u2013" + Number(mx) + " m");
      }
      bilgi.textContent = parcalar.join(" \u00b7 ");
      s.appendChild(ad); s.appendChild(bilgi);
      kap.appendChild(s);
    }
    if (!varMi) {
      const u = document.createElement("div");
      u.className = "dpx-ozet-uyari";
      u.textContent = t.dpxAlgilayiciYok ||
        "Hi\u00e7bir yak\u0131nl\u0131k algilayicisi yap\u0131land\u0131r\u0131lmam\u0131\u015f " +
        "(PRXn_TYPE = 0). Y\u00f6ne t\u0131klay\u0131p ekleyebilirsiniz.";
      kap.appendChild(u);
    }
    // Genel kacinma ayarlari
    const av = p["AVOID_ENABLE"], am = p["AVOID_MARGIN"];
    if (av !== undefined || am !== undefined) {
      const s = document.createElement("div");
      s.className = "dpx-ozet-sat";
      const ad = document.createElement("span");
      ad.className = "dpx-ozet-ad";
      ad.textContent = t.dpxKacinma || "Ka\u00e7\u0131nma";
      const bilgi = document.createElement("span");
      bilgi.className = "dpx-ozet-bilgi";
      const pr = [];
      if (av !== undefined) {
        pr.push(Number(av) === 0
          ? (t.dpxKapali || "kapal\u0131")
          : (t.dpxAcikDurum || "a\u00e7\u0131k") + " (" + Number(av) + ")");
      }
      if (am !== undefined) pr.push((t.dpxMarj || "marj") + " " + Number(am) + " m");
      bilgi.textContent = pr.join(" \u00b7 ");
      s.appendChild(ad); s.appendChild(bilgi);
      kap.appendChild(s);
    }
  }
  function algilayiciImza(p) {
    const par = [];
    for (let i = 1; i <= ALGILAYICI_SAYISI; i++) {
      par.push(p["PRX" + i + "_TYPE"], p["PRX" + i + "_ORIENT"],
               p["PRX" + i + "_MIN"], p["PRX" + i + "_MAX"]);
    }
    par.push(p["AVOID_ENABLE"], p["AVOID_MARGIN"]);
    return par.join("|");
  }

  // ===============================================================
  // 2. YON PENCERESI
  // ---------------------------------------------------------------
  // Iki bolum:
  //   A) O yonun CANLI olcumu
  //   B) O yone BAKAN algilayicinin parametreleri
  // Eslesen algilayici yoksa uydurma deger GOSTERILMEZ.
  // ===============================================================
  function yonPenceresiAc(fare, sysid, y) {
    const t = sozluk();
    const kimlik = "dpxYon_" + y.k + "_" + sysid;
    if (dkPopupTekil(kimlik)) return;
    const pop = document.createElement("div");
    pop.id = kimlik;
    pop.className = "dk-mini-popup dpx-yon-pencere";
    dkMiniPopupBaslikKur(pop,
      yonAdi(y).toUpperCase() + " \u2014 D" + sysid, null, y.ikon);
    const govde = document.createElement("div");
    govde.className = "dpx-yon-govde";
    pop.appendChild(govde);

    // --- A) CANLI OLCUM
    const olcBas = document.createElement("div");
    olcBas.className = "dpx-bolum-bas";
    olcBas.textContent = t.dpxCanliOlcum || "CANLI \u00d6L\u00c7\u00dcM";
    govde.appendChild(olcBas);
    const olcum = document.createElement("div");
    olcum.className = "dpx-olcum";
    govde.appendChild(olcum);

    // --- B) PARAMETRELER
    const parBas = document.createElement("div");
    parBas.className = "dpx-bolum-bas";
    parBas.textContent = t.dpxParametreler || "BU Y\u00d6NE BAKAN ALGILAYICI";
    govde.appendChild(parBas);
    const paramKap = document.createElement("div");
    paramKap.className = "dpx-param";
    govde.appendChild(paramKap);

    pop.style.position = "fixed";
    dkPopupOneGetirKur(pop);
    document.body.appendChild(pop);
    dkMiniPopupKonumla(pop, fare);

    let paramImza = "";
    const timer = setInterval(() => {
      if (!pop.isConnected) { clearInterval(timer); return; }
      olcumCiz(olcum, sysid, y);
      const p = onbellek(sysid);
      const imza = algilayiciImza(p) + "|" + Object.keys(p).length;
      if (imza !== paramImza) {
        paramImza = imza;
        paramCiz(paramKap, sysid, y, p);
      }
    }, 400);
    olcumCiz(olcum, sysid, y);
    paramCiz(paramKap, sysid, y, onbellek(sysid));
  }

  function olcumCiz(kap, sysid, y) {
    const t = sozluk();
    const d = dronVeri(sysid);
    const o = (d && d.prx_yonler) ? d.prx_yonler[String(y.k)] : null;
    if (!o) {
      if (kap.dataset.bos === "1") return;
      kap.dataset.bos = "1";
      kap.textContent = "";
      const b = document.createElement("div");
      b.className = "dpx-olcum-bos";
      b.textContent = t.dpxOlcumYok ||
        "Bu y\u00f6nden \u00f6l\u00e7\u00fcm gelmiyor. Algilayici kapal\u0131 " +
        "olabilir ya da menzil d\u0131\u015f\u0131nda engel yok.";
      kap.appendChild(b);
      return;
    }
    kap.dataset.bos = "0";
    const mn = (typeof o.min === "number" && o.min > 0) ? o.min : null;
    const mx = (typeof o.max === "number" && o.max > 0) ? o.max : null;
    // Buyuk mesafe gostergesi + menzil cubugu
    if (!kap.querySelector(".dpx-buyuk")) {
      kap.textContent = "";
      kap.innerHTML =
        "<div class='dpx-buyuk'><span class='dpx-buyuk-deg'>—</span>" +
        "  <span class='dpx-buyuk-br'>m</span></div>" +
        "<div class='dpx-menzil'><div class='dpx-menzil-cub'>" +
        "  <div class='dpx-menzil-dolgu'></div>" +
        "  <div class='dpx-menzil-imle'></div></div>" +
        "  <div class='dpx-menzil-et'><span data-mn>—</span>" +
        "    <span data-mx>—</span></div></div>" +
        "<div class='dpx-olcum-alt'><span data-yas>—</span></div>";
    }
    const degEl = kap.querySelector(".dpx-buyuk-deg");
    degEl.textContent = o.mesafe.toFixed(2);
    // Renk: min sinira yakinlik
    let sinif = "dpx-buyuk-deg";
    if (mn !== null && mx !== null) {
      const oran = Math.max(0, Math.min(1, (o.mesafe - mn) / Math.max(0.01, mx - mn)));
      if (oran < 0.25) sinif += " tehlike";
      else if (oran < 0.55) sinif += " uyari";
      else sinif += " iyi";
      const dolgu = kap.querySelector(".dpx-menzil-dolgu");
      const imle = kap.querySelector(".dpx-menzil-imle");
      dolgu.style.width = (oran * 100) + "%";
      dolgu.className = "dpx-menzil-dolgu" +
        (oran < 0.25 ? " tehlike" : (oran < 0.55 ? " uyari" : " iyi"));
      imle.style.left = (oran * 100) + "%";
      kap.querySelector("[data-mn]").textContent = mn.toFixed(2) + " m";
      kap.querySelector("[data-mx]").textContent = mx.toFixed(2) + " m";
    }
    degEl.className = sinif;
    const yas = o.ts ? (Date.now() / 1000 - Number(o.ts)) : null;
    kap.querySelector("[data-yas]").textContent = (yas === null)
      ? ""
      : (t.dpxSonOlcum || "son \u00f6l\u00e7\u00fcm") + ": " +
        (yas < 1 ? "<1" : Math.round(yas)) + " s";
  }

  // O yone bakan algilayiciyi bul. Alt/ust yonler icin ORIENT
  // eslesmesi yapilmaz (ArduPilot'ta asagi bakan algilayici ayri
  // parametre ailesinde: RNGFNDn). Bu durumda bilgilendirme gosterilir.
  function yoneBakanAlgilayici(p, y) {
    if (y.dikey) return null;
    for (let i = 1; i <= ALGILAYICI_SAYISI; i++) {
      const tip = p["PRX" + i + "_TYPE"];
      if (tip === undefined || Number(tip) === 0) continue;
      const orient = p["PRX" + i + "_ORIENT"];
      // ORIENT tanimsizsa algilayici COK YONLU olabilir (360 lidar);
      // bu durumda tum yatay yonleri kapsar.
      if (orient === undefined) return { no: i, cokYonlu: true };
      if (Number(orient) === y.k) return { no: i, cokYonlu: false };
    }
    // Cok yonlu algilayici (360 lidar) tum yatay yonleri kapsar
    for (let i = 1; i <= ALGILAYICI_SAYISI; i++) {
      const tip = Number(p["PRX" + i + "_TYPE"] || 0);
      // ArduPilot 360 derece lidar tipleri: 1(LightWareSF40C),
      // 2(MAVLink), 3(TeraRangerTower), 4(RangeFinder), 5(RPLidarA2),
      // 6(TeraRangerTowerEvo), 7(SF45B), 10(SITL), 13(Cygbot)
      if ([1, 3, 5, 6, 7, 10, 13].indexOf(tip) >= 0) {
        return { no: i, cokYonlu: true };
      }
    }
    return null;
  }

  function paramCiz(kap, sysid, y, p) {
    const t = sozluk();
    kap.textContent = "";
    if (!Object.keys(p).length) {
      const u = document.createElement("div");
      u.className = "dpx-param-uyari";
      u.textContent = t.dpxParamYok ||
        "Algilayici parametreleri \u00f6nbellekte yok. Parametreler " +
        "ekran\u0131ndan T\u00dcM\u00dcN\u00dc AL yap\u0131n.";
      kap.appendChild(u);
      return;
    }
    if (y.dikey) {
      const u = document.createElement("div");
      u.className = "dpx-param-uyari";
      u.textContent = (y.k === 24)
        ? (t.dpxAltNot ||
           "A\u015fa\u011f\u0131 bakan \u00f6l\u00e7\u00fcm RNGFND (mesafe " +
           "\u00f6l\u00e7er) ailesinde yap\u0131land\u0131r\u0131l\u0131r; " +
           "yak\u0131nl\u0131k parametresi almaz.")
        : (t.dpxUstNot ||
           "Yukar\u0131 bakan \u00f6l\u00e7\u00fcm RNGFND ailesinde " +
           "yap\u0131land\u0131r\u0131l\u0131r; yak\u0131nl\u0131k parametresi almaz.");
      kap.appendChild(u);
      // Yine de genel kacinma ayarlarini gosterelim
      genelKacinma(kap, sysid, p);
      return;
    }
    const alg = yoneBakanAlgilayici(p, y);
    if (!alg) {
      const u = document.createElement("div");
      u.className = "dpx-param-uyari";
      u.textContent = t.dpxYoneBakanYok ||
        "Bu y\u00f6ne bakan algilayici yap\u0131land\u0131r\u0131lmam\u0131\u015f.";
      kap.appendChild(u);
      // Ekleme yonlendirmesi: bos PRXn yuvasi bul
      let bos = 0;
      for (let i = 1; i <= ALGILAYICI_SAYISI; i++) {
        const tip = p["PRX" + i + "_TYPE"];
        if (tip === undefined || Number(tip) === 0) { bos = i; break; }
      }
      if (bos) {
        const yol = document.createElement("div");
        yol.className = "dpx-param-yol";
        yol.textContent = (t.dpxBosYuva ||
          "Bo\u015f yuva: PRX{n}. Algilayici tipini Parametreler " +
          "ekran\u0131ndan yaz\u0131n.").replace("{n}", String(bos));
        kap.appendChild(yol);
      }
      genelKacinma(kap, sysid, p);
      return;
    }
    const bas = document.createElement("div");
    bas.className = "dpx-param-bas";
    bas.textContent = "PRX" + alg.no +
      (alg.cokYonlu
        ? " \u2014 " + (t.dpxCokYonlu || "\u00e7ok y\u00f6nl\u00fc (360\u00b0)")
        : "");
    kap.appendChild(bas);
    if (alg.cokYonlu) {
      const n = document.createElement("div");
      n.className = "dpx-param-not";
      n.textContent = t.dpxCokYonluNot ||
        "Bu algilayici t\u00fcm yatay y\u00f6nleri kapsar; " +
        "a\u015fa\u011f\u0131daki ayarlar b\u00fct\u00fcn y\u00f6nleri etkiler.";
      kap.appendChild(n);
    }
    // Duzenlenebilir alanlar
    paramAlan(kap, sysid, "PRX" + alg.no + "_TYPE",
      t.dpxAlanTip || "Algilayici tipi", p, 0, 100, 1);
    if (!alg.cokYonlu) {
      paramAlan(kap, sysid, "PRX" + alg.no + "_ORIENT",
        t.dpxAlanYon || "Y\u00f6n (orientation)", p, 0, 25, 1);
    }
    paramAlan(kap, sysid, "PRX" + alg.no + "_MIN",
      t.dpxAlanMin || "En yak\u0131n (m)", p, 0, 50, 0.05);
    paramAlan(kap, sysid, "PRX" + alg.no + "_MAX",
      t.dpxAlanMax || "En uzak (m)", p, 0, 200, 0.1);
    paramAlan(kap, sysid, "PRX" + alg.no + "_YAW_CORR",
      t.dpxAlanYaw || "Y\u00f6n d\u00fczeltmesi (\u00b0)", p, -180, 180, 1);
    genelKacinma(kap, sysid, p);
  }

  function genelKacinma(kap, sysid, p) {
    const t = sozluk();
    const bas = document.createElement("div");
    bas.className = "dpx-param-bas";
    bas.textContent = t.dpxGenelKacinma || "GENEL KA\u00c7INMA";
    kap.appendChild(bas);
    paramAlan(kap, sysid, "AVOID_ENABLE",
      t.dpxAlanKacinma || "Ka\u00e7\u0131nma (bit maskesi)", p, 0, 7, 1);
    paramAlan(kap, sysid, "AVOID_MARGIN",
      t.dpxAlanMarj || "G\u00fcvenlik marj\u0131 (m)", p, 0, 50, 0.5);
    paramAlan(kap, sysid, "PRX_FILT",
      t.dpxAlanSuzgec || "S\u00fczge\u00e7 (Hz)", p, 0, 20, 0.5);
  }

  // Tek parametre satiri: mevcut deger + yazma. Onbellekte yoksa
  // UYDURMA VARSAYILAN GOSTERILMEZ (v2.4.38 tuzagi).
  function paramAlan(kap, sysid, ad, etiket, p, min, max, adim) {
    const t = sozluk();
    const mevcut = p[ad];
    const sat = document.createElement("div");
    sat.className = "dpx-alan";
    const et = document.createElement("span");
    et.className = "dpx-alan-et";
    et.textContent = etiket;
    const kod = document.createElement("span");
    kod.className = "dpx-alan-kod";
    kod.textContent = ad;
    const gir = document.createElement("input");
    gir.type = "number";
    gir.className = "dpx-alan-gir";
    gir.min = String(min); gir.max = String(max); gir.step = String(adim);
    if (mevcut === undefined || mevcut === null) {
      gir.value = "";
      gir.placeholder = t.dpxOnbellekYok || "\u00f6nbellekte yok";
      gir.classList.add("bos");
    } else {
      gir.value = String(Number(mevcut));
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dpx-alan-btn";
    btn.innerHTML = "<i class='fa-solid fa-pen-to-square'></i>";
    btn.title = t.dpxYaz || "Araca yaz";
    btn.addEventListener("click", () => {
      const v = Number(gir.value);
      if (gir.value === "" || !isFinite(v)) return;
      onayIste(
        (t.dpxYazOnay || "{ad} = {v} olarak araca yaz\u0131ls\u0131n m\u0131?")
          .replace("{ad}", ad).replace("{v}", String(v)),
        () => {
          wsGonder({ tip: "param_yaz", sysid: Number(sysid),
                     ad: ad, deger: v });
          btn.classList.add("gonderildi");
          setTimeout(() => btn.classList.remove("gonderildi"), 1500);
        });
    });
    const sol = document.createElement("div");
    sol.className = "dpx-alan-sol";
    sol.appendChild(et); sol.appendChild(kod);
    sat.appendChild(sol); sat.appendChild(gir); sat.appendChild(btn);
    kap.appendChild(sat);
  }

  // ===============================================================
  // 3. HARITA KALKANI
  // ---------------------------------------------------------------
  // Yalniz ACIK yonlerde 3B kabuk cizilir, uzerinde menzil metresi.
  // Etkinlik dron basina; varsayilan KAPALI (harita kalabaligini
  // operator kararina birakiyoruz).
  // ===============================================================
  const KALKAN_ANAHTAR = "gcs_prx_kalkan";
  let kalkanDurum = null;

  function kalkanDurumYukle() {
    if (kalkanDurum) return kalkanDurum;
    try {
      const s = localStorage.getItem(KALKAN_ANAHTAR);
      kalkanDurum = s ? JSON.parse(s) : {};
    } catch (e) { kalkanDurum = {}; }
    if (typeof kalkanDurum !== "object" || !kalkanDurum) kalkanDurum = {};
    return kalkanDurum;
  }
  function kalkanEtkin(sysid) {
    return !!kalkanDurumYukle()[String(sysid)];
  }
  function kalkanAyarla(sysid, deger) {
    const d = kalkanDurumYukle();
    if (deger) d[String(sysid)] = 1; else delete d[String(sysid)];
    try { localStorage.setItem(KALKAN_ANAHTAR, JSON.stringify(d)); }
    catch (e) { /* kota dolu olabilir; bellekte tutulur */ }
    if (!deger) kalkanTemizle(sysid);
  }

  function kalkanTemizle(sysid) {
    if (typeof varliklar === "undefined" || !varliklar[sysid]) return;
    const liste = varliklar[sysid]._prxKalkan;
    if (!liste) return;
    for (const e of liste) {
      try { viewer.entities.remove(e); } catch (err) { /* zaten yok */ }
    }
    varliklar[sysid]._prxKalkan = null;
  }

  // varlikGuncelle sonrasi cagrilir (dronlar.js yamasi)
  function kalkanGuncelle(d) {
    if (typeof viewer === "undefined" || !viewer) return;
    if (typeof varliklar === "undefined") return;
    const sysid = d.sysid;
    const varlik = varliklar[sysid];
    if (!varlik) return;
    if (!kalkanEtkin(sysid)) { kalkanTemizle(sysid); return; }
    const yonler = d.prx_yonler;
    if (!yonler || !Object.keys(yonler).length) {
      kalkanTemizle(sysid);
      return;
    }
    // Bayat veri (5 s) kalkan gostermez — olmayan engeli gostermek
    // operatoru yanlis yonlendirir.
    if (d.prx_ts && (Date.now() / 1000 - Number(d.prx_ts)) > 5) {
      kalkanTemizle(sysid);
      return;
    }
    if (d.lat === null || d.lon === null) { kalkanTemizle(sysid); return; }
    const yuk = Math.max(0, (typeof d.alt_rel === "number" ? d.alt_rel : 0));
    const hdg = (typeof d.heading === "number") ? d.heading : 0;
    const renk = (typeof dronRengi === "function")
      ? dronRengi(sysid) : "#35d0ff";

    // Mevcut kalkanlari yon anahtarina gore eslestir
    if (!varlik._prxKalkan) varlik._prxKalkan = [];
    const eskiler = {};
    for (const e of varlik._prxKalkan) {
      if (e && e._prxYon !== undefined) eskiler[e._prxYon] = e;
    }
    const yeniListe = [];
    const kullanilan = {};

    for (const anahtar of Object.keys(yonler)) {
      const o = yonler[anahtar];
      if (!o || typeof o.mesafe !== "number") continue;
      const tanim = HARITA_YONLER[anahtar];
      if (!tanim) continue;
      const mesafe = Math.max(0.15, o.mesafe);
      // Kabuk merkezi: yonde mesafe/2 kadar otelenmis
      let lat = d.lat, lon = d.lon, z = yuk;
      if (tanim.dikey === 0) {
        const brg = (hdg + tanim.bearing) % 360;
        const [nlat, nlon] = bearingOffset(d.lat, d.lon, brg, mesafe / 2);
        lat = nlat; lon = nlon;
      } else {
        z = Math.max(0, yuk + tanim.dikey * (mesafe / 2));
      }
      const pos = Cesium.Cartesian3.fromDegrees(lon, lat, z);
      // Yassi mercek: yon eksenine dik genis, yon ekseninde ince
      const r = Math.max(0.4, mesafe * 0.34);
      const kalinlik = Math.max(0.12, mesafe * 0.09);
      const radii = (tanim.dikey === 0)
        ? new Cesium.Cartesian3(kalinlik, r, r)
        : new Cesium.Cartesian3(r, r, kalinlik);
      // Yakinlik derecesine gore renk: min sinira yaklastikca kirmizi
      const mn = (typeof o.min === "number" && o.min > 0) ? o.min : 0.2;
      const mx = (typeof o.max === "number" && o.max > 0) ? o.max : 8;
      const oran = Math.max(0, Math.min(1,
        (o.mesafe - mn) / Math.max(0.01, mx - mn)));
      const kabukRenk = (oran < 0.25)
        ? Cesium.Color.fromCssColorString("#ff5d5d")
        : (oran < 0.55
            ? Cesium.Color.fromCssColorString("#f2b24a")
            : Cesium.Color.fromCssColorString(renk));
      const etiketMetin = o.mesafe.toFixed(2) + " m";
      const oryantasyon = (tanim.dikey === 0)
        ? dronOryantasyon(pos, (hdg + tanim.bearing) % 360, 0, 0)
        : dronOryantasyon(pos, hdg, 0, 0);

      let e = eskiler[anahtar];
      if (e) {
        e.position = pos;
        e.orientation = oryantasyon;
        e.ellipsoid.radii = radii;
        e.ellipsoid.material = kabukRenk.withAlpha(0.22);
        e.ellipsoid.outlineColor = kabukRenk.withAlpha(0.75);
        e.label.text = etiketMetin;
        e.label.fillColor = kabukRenk;
        kullanilan[anahtar] = true;
        yeniListe.push(e);
        continue;
      }
      e = viewer.entities.add({
        id: "dron_prx_" + sysid + "_" + anahtar,
        position: pos,
        orientation: oryantasyon,
        ellipsoid: {
          radii: radii,
          material: kabukRenk.withAlpha(0.22),
          outline: true,
          outlineColor: kabukRenk.withAlpha(0.75),
          outlineWidth: 1,
          slicePartitions: 16,
          stackPartitions: 10,
          heightReference: Cesium.HeightReference.NONE
        },
        label: {
          text: etiketMetin,
          font: "600 11px 'IBM Plex Mono', monospace",
          fillColor: kabukRenk,
          outlineColor: Cesium.Color.BLACK.withAlpha(0.85),
          outlineWidth: 2.5,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -6),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          scaleByDistance: new Cesium.NearFarScalar(50, 1.0, 3000, 0.5)
        }
      });
      e._prxYon = anahtar;
      kullanilan[anahtar] = true;
      yeniListe.push(e);
    }
    // Artik olmayan yonlerin kalkanlarini kaldir
    for (const anahtar of Object.keys(eskiler)) {
      if (!kullanilan[anahtar]) {
        try { viewer.entities.remove(eskiler[anahtar]); }
        catch (err) { /* zaten yok */ }
      }
    }
    varlik._prxKalkan = yeniListe;
  }

  // ===============================================================
  // DISA ACILAN ARAYUZ
  // ===============================================================
  window.dpxYakinlikAc = yakinlikAc;
  window.dpxKalkanGuncelle = kalkanGuncelle;
  window.dpxKalkanTemizle = kalkanTemizle;
  window.dpxKalkanEtkin = kalkanEtkin;
  window.dpxKalkanAyarla = kalkanAyarla;
})();
