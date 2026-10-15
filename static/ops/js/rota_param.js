// =================================================================
// GOKTUNGU - ROTA PARAMETRE DUZENLEME (v2.4.23)
// Kayitli bir rotanin UCUS PARAMETRELERINI (irtifa, hiz, yonelim
// acisi) rota noktalarini yeniden cizmeye gerek kalmadan duzenler.
//
// Erisim yollari:
//   1) Rota detay popup'i > "PARAMETRELERI DEGISTIR" dugmesi
//   2) Harita uzerinde rotaya CIFT TIK (serbest form olmayan rotalar;
//      serbest form cift tikta kendi cizim popup'ini acar)
//
// Rota tipine gore davranis:
//   - serbest_form : ALAN TARAMA GEOMETRISI bolumu de gorunur
//     (aralik + yon). Bu iki deger degisirse zigzag rota
//     serbest_form.js'teki uretici ile YENIDEN URETILIR; irtifa/hiz/
//     aci tum noktalara uygulanir.
//   - diger tipler : toplu (tum noktalar) ve nokta bazli
//     irtifa / hiz / aci duzenlemesi.
//
// Kayit: mevcut "rota_kaydet" WS komutu (id + noktalar [+ irtifa,
// hiz, meta]) kullanilir; yeni backend komutu gerekmez.
// Bu dosya klasik script'tir; serbest_form.js'ten SONRA yuklenir.
// =================================================================
(function(){
  "use strict";

  const perde   = document.getElementById("rotaParamPerde");
  if (!perde) return;
  const kutu    = document.getElementById("rotaParamKutu");
  const lblAd   = document.getElementById("rpRotaAd");
  const geoBol  = document.getElementById("rpGeoBolum");
  const inpAralik = document.getElementById("rpAralik");
  const inpYon    = document.getElementById("rpYon");
  const geoBilgi  = document.getElementById("rpGeoBilgi");
  const acIrtifa  = document.getElementById("rpTopluIrtifaAc");
  const acHiz     = document.getElementById("rpTopluHizAc");
  const acAci     = document.getElementById("rpTopluAciAc");
  const inpTIrtifa = document.getElementById("rpTopluIrtifa");
  const inpTHiz    = document.getElementById("rpTopluHiz");
  const selAciMod  = document.getElementById("rpTopluAciMod");
  const inpTAci    = document.getElementById("rpTopluAci");
  const birimAci   = document.getElementById("rpTopluAciBirim");
  const tabloEl    = document.getElementById("rpNoktaTablo");
  const noktaSayi  = document.getElementById("rpNoktaSayi");
  const hataEl     = document.getElementById("rpHata");

  // --- Durum ---
  let rota = null;        // duzenlenen rotanin kopyasi
  let noktalar = [];      // {lat, lon, irtifa, hiz, aci?}
  let serbestMi = false;

  function t(){ return (typeof D === "function") ? D() : {}; }
  function s(k, y){ const d = t(); return d[k] || y; }

  function wsGonder(m){
    if (typeof ws !== "undefined" && ws && ws.readyState === 1)
      ws.send(JSON.stringify(m));
  }
  function konsol(m){
    if (typeof konsolYaz === "function") konsolYaz("ROTA", m);
  }

  // ---------------------------------------------------------------
  // YARDIMCILAR
  // ---------------------------------------------------------------
  function say(v, varsayilan){
    const x = parseFloat(v);
    return isFinite(x) ? x : varsayilan;
  }
  function sinirla(v, alt, ust){
    return Math.max(alt, Math.min(ust, v));
  }
  // Nokta acisini metne cevir: -1 / tanimsiz -> "OTO"
  function aciMetni(a){
    if (a === undefined || a === null || a === "" || Number(a) < 0)
      return s("rpAciOtoKisa", "OTO");
    return Math.round(Number(a)) + "\u00b0";
  }

  // Ardisik iki nokta arasindaki pusula acisi (0=kuzey, saat yonu)
  function kerteriz(a, b){
    const f1 = a.lat * Math.PI / 180, f2 = b.lat * Math.PI / 180;
    const dl = (b.lon - a.lon) * Math.PI / 180;
    const y = Math.sin(dl) * Math.cos(f2);
    const x = Math.cos(f1) * Math.sin(f2) -
              Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  // ---------------------------------------------------------------
  // NOKTA TABLOSU
  // ---------------------------------------------------------------
  function tabloCiz(){
    tabloEl.innerHTML = "";
    noktaSayi.textContent =
      "(" + noktalar.length + " " + s("rotaNoktaSayisi", "nokta") + ")";
    noktalar.forEach((n, i) => {
      const satir = document.createElement("div");
      satir.className = "rp-tr";

      const no = document.createElement("span");
      no.className = "rp-td-no" +
        (i === 0 ? " start" : (i === noktalar.length - 1 &&
                               noktalar.length > 1 ? " finish" : ""));
      no.textContent = i + 1;

      const koord = document.createElement("span");
      koord.className = "rp-td-koord";
      koord.textContent = n.lat.toFixed(5) + ", " + n.lon.toFixed(5);

      // Irtifa
      const cIrt = document.createElement("span");
      cIrt.className = "rp-td-val";
      const iIrt = document.createElement("input");
      iIrt.type = "number"; iIrt.min = "1"; iIrt.max = "2000"; iIrt.step = "1";
      iIrt.value = n.irtifa;
      iIrt.addEventListener("input", () => {
        n.irtifa = sinirla(say(iIrt.value, n.irtifa), 1, 2000);
        onizlemeTazele();
      });
      cIrt.appendChild(iIrt);

      // Hiz
      const cHiz = document.createElement("span");
      cHiz.className = "rp-td-val";
      const iHiz = document.createElement("input");
      iHiz.type = "number"; iHiz.min = "0.5"; iHiz.max = "83.3"; iHiz.step = "0.5";
      iHiz.value = n.hiz;
      iHiz.addEventListener("input", () => {
        n.hiz = sinirla(say(iHiz.value, n.hiz), 0.5, 83.3);
        onizlemeTazele();
      });
      cHiz.appendChild(iHiz);

      // Aci: bos birakilirsa OTO
      const cAci = document.createElement("span");
      cAci.className = "rp-td-val";
      const iAci = document.createElement("input");
      iAci.type = "number"; iAci.min = "0"; iAci.max = "359"; iAci.step = "1";
      iAci.placeholder = s("rpAciOtoKisa", "OTO");
      iAci.title = s("rpAciIpucu",
        "Bo\u015f = otomatik (rota y\u00f6n\u00fc). 0-359 = sabit pusula a\u00e7\u0131s\u0131.");
      iAci.value = (n.aci === undefined || n.aci === null ||
                    Number(n.aci) < 0) ? "" : Math.round(Number(n.aci));
      iAci.addEventListener("input", () => {
        const v = iAci.value.trim();
        if (v === ""){ delete n.aci; }
        else n.aci = ((say(v, 0) % 360) + 360) % 360;
        onizlemeTazele();
      });
      cAci.appendChild(iAci);

      satir.appendChild(no); satir.appendChild(koord);
      satir.appendChild(cIrt); satir.appendChild(cHiz); satir.appendChild(cAci);
      tabloEl.appendChild(satir);
    });
  }

  // Harita onizlemesi: duzenlenen degerler haritada canli gorunsun
  function onizlemeTazele(){
    if (typeof window.rotaOnizlemeCiz === "function")
      window.rotaOnizlemeCiz(rota ? rota.id : null, noktalar);
  }

  // ---------------------------------------------------------------
  // SERBEST FORM: geometri degisince rota yeniden uret
  // ---------------------------------------------------------------
  function geoBilgiTazele(){
    if (!serbestMi) return;
    geoBilgi.textContent =
      s("rpGeoBilgi",
        "Aral\u0131k veya a\u00e7\u0131 de\u011fi\u015firse tarama rotas\u0131 " +
        "yeniden \u00fcretilir.") +
      "  (" + noktalar.length + " " + s("rotaNoktaSayisi", "nokta") + ")";
  }

  function serbestYenidenUret(){
    if (!serbestMi) return false;
    if (typeof window.serbestFormRotaUret !== "function") return false;
    const koseler = (rota.meta && rota.meta.koseler) || [];
    if (koseler.length < 3) return false;
    const aralik = sinirla(say(inpAralik.value, 10), 1, 500);
    const yon = ((say(inpYon.value, 0) % 360) + 360) % 360;
    const yeni = window.serbestFormRotaUret(koseler, aralik, yon);
    if (!yeni || yeni.length < 2) return false;
    // Onceki noktalarin ortalama irtifa/hiz/aci degerlerini koru
    const eskiIrt = noktalar.length ? noktalar[0].irtifa
                                    : (rota.irtifa_varsayilan || 20);
    const eskiHiz = noktalar.length ? noktalar[0].hiz
                                    : (rota.hiz_varsayilan || 5);
    const eskiAci = (noktalar.length && noktalar[0].aci !== undefined)
      ? noktalar[0].aci : undefined;
    noktalar = yeni.map(p => {
      const n = {lat: p.lat, lon: p.lon, irtifa: eskiIrt, hiz: eskiHiz};
      if (eskiAci !== undefined) n.aci = eskiAci;
      return n;
    });
    tabloCiz();
    geoBilgiTazele();
    onizlemeTazele();
    return true;
  }

  // ---------------------------------------------------------------
  // TOPLU UYGULAMA
  // ---------------------------------------------------------------
  function topluKilitTazele(){
    inpTIrtifa.disabled = !acIrtifa.checked;
    inpTHiz.disabled = !acHiz.checked;
    selAciMod.disabled = !acAci.checked;
    const sabit = acAci.checked && selAciMod.value === "sabit";
    inpTAci.disabled = !sabit;
    inpTAci.style.display = sabit ? "" : "none";
    birimAci.style.display = sabit ? "" : "none";
  }
  [acIrtifa, acHiz, acAci].forEach(el =>
    el.addEventListener("change", topluKilitTazele));
  selAciMod.addEventListener("change", topluKilitTazele);

  function topluUygula(){
    if (!noktalar.length) return;
    let sayac = 0;
    if (acIrtifa.checked){
      const v = sinirla(say(inpTIrtifa.value, 0), 1, 2000);
      noktalar.forEach(n => { n.irtifa = v; });
      sayac++;
    }
    if (acHiz.checked){
      const v = sinirla(say(inpTHiz.value, 0), 0.5, 83.3);
      noktalar.forEach(n => { n.hiz = v; });
      sayac++;
    }
    if (acAci.checked){
      if (selAciMod.value === "sabit"){
        const v = ((say(inpTAci.value, 0) % 360) + 360) % 360;
        noktalar.forEach(n => { n.aci = v; });
      } else {
        // Otomatik: aci alanini kaldir (ArduPilot rota yonune baksin)
        noktalar.forEach(n => { delete n.aci; });
      }
      sayac++;
    }
    if (!sayac){
      hataEl.textContent = s("rpHataSecim",
        "Uygulanacak en az bir alan se\u00e7in.");
      return;
    }
    hataEl.textContent = "";
    tabloCiz();
    onizlemeTazele();
  }
  document.getElementById("btnRpTopluUygula")
    .addEventListener("click", topluUygula);

  // Serbest form geometri girisleri: degisince rotayi yeniden uret
  [inpAralik, inpYon].forEach(el => {
    el.addEventListener("change", () => {
      if (!serbestYenidenUret())
        hataEl.textContent = s("rpHataUretim",
          "Tarama rotas\u0131 yeniden \u00fcretilemedi " +
          "(alan k\u00f6\u015feleri eksik).");
      else hataEl.textContent = "";
    });
  });

  // ---------------------------------------------------------------
  // AC / KAPAT
  // ---------------------------------------------------------------
  function ac(rotaVerisi){
    if (!rotaVerisi) return;
    rota = rotaVerisi;
    noktalar = (rotaVerisi.noktalar || []).map(n => Object.assign({}, n));
    serbestMi = !!(rotaVerisi.meta && rotaVerisi.meta.tur === "serbest_form" &&
                   (rotaVerisi.meta.koseler || []).length >= 3);
    lblAd.textContent = rotaVerisi.isim ? "\u2014 " + rotaVerisi.isim : "";
    hataEl.textContent = "";

    // Serbest form geometri bolumu
    geoBol.style.display = serbestMi ? "" : "none";
    if (serbestMi){
      inpAralik.value = isFinite(rotaVerisi.meta.aralik)
        ? rotaVerisi.meta.aralik : 10;
      inpYon.value = isFinite(rotaVerisi.meta.yon) ? rotaVerisi.meta.yon : 0;
      geoBilgiTazele();
    }

    // Toplu alanlar: mevcut degerlerden onerilen baslangic
    const n0 = noktalar[0] || {};
    inpTIrtifa.value = isFinite(n0.irtifa) ? n0.irtifa
      : (rotaVerisi.irtifa_varsayilan || 50);
    inpTHiz.value = isFinite(n0.hiz) ? n0.hiz
      : (rotaVerisi.hiz_varsayilan || 10);
    // Tum noktalarda ayni sabit aci varsa "sabit" secili gelsin
    const aciDegerler = noktalar.map(n =>
      (n.aci === undefined || n.aci === null || Number(n.aci) < 0)
        ? null : Number(n.aci));
    const hepsiAyniSabit = aciDegerler.length > 0 &&
      aciDegerler.every(a => a !== null && a === aciDegerler[0]);
    selAciMod.value = hepsiAyniSabit ? "sabit" : "oto";
    inpTAci.value = hepsiAyniSabit ? Math.round(aciDegerler[0]) : 0;
    acIrtifa.checked = false; acHiz.checked = false; acAci.checked = false;
    topluKilitTazele();

    tabloCiz();
    perde.classList.remove("popup-gizli");
    // Rotayi haritada gorunur yap ki degisiklikler izlenebilsin
    if (!rotaVerisi.gorunur)
      wsGonder({tip: "rota_kaydet", id: rotaVerisi.id, gorunur: true});
    onizlemeTazele();
  }

  function kapat(){
    perde.classList.add("popup-gizli");
    rota = null; noktalar = []; serbestMi = false;
    if (typeof window.rotaOnizlemeTemizle === "function")
      window.rotaOnizlemeTemizle();
  }

  document.getElementById("btnRpKapat").addEventListener("click", kapat);
  document.getElementById("btnRpIptal").addEventListener("click", kapat);
  perde.addEventListener("click", (e) => { if (e.target === perde) kapat(); });

  // ---------------------------------------------------------------
  // KAYDET
  // ---------------------------------------------------------------
  document.getElementById("btnRpKaydet").addEventListener("click", () => {
    if (!rota || !noktalar.length) { kapat(); return; }
    const mesaj = {
      tip: "rota_kaydet", id: rota.id,
      noktalar: noktalar,
      // Rota varsayilanlarini ilk noktaya gore tazele (yeni gorevler
      // ve TAKEOFF irtifasi bu degerleri kullanir)
      irtifa: noktalar[0].irtifa,
      hiz: noktalar[0].hiz,
    };
    if (serbestMi){
      mesaj.meta = Object.assign({}, rota.meta, {
        aralik: sinirla(say(inpAralik.value, 10), 1, 500),
        yon: ((say(inpYon.value, 0) % 360) + 360) % 360,
      });
    } else if (rota.meta && rota.meta.tur === "koridor"){
      // v2.4.40: koridor meta'si (merkez hat, genislik, tur sayisi)
      // burada DEGISTIRILMEZ ama aynen geri yazilir. Aksi halde bu
      // ekrandan irtifa/hiz degistirmek meta'yi bosaltir ve rota bir
      // daha koridor popup'inda acilamaz.
      mesaj.meta = Object.assign({}, rota.meta);
    }
    wsGonder(mesaj);
    konsol("'" + (rota.isim || "#" + rota.id) + "' " +
           s("rpKonsolKaydet", "rota parametreleri g\u00fcncellendi") +
           " (" + noktalar.length + " " + s("rotaNoktaSayisi", "nokta") + ")");
    kapat();
  });

  // ---------------------------------------------------------------
  // DIS ERISIM
  // ---------------------------------------------------------------
  // rotalar.js (detay popup dugmesi) ve harita cift tiklamasi cagirir
  window.rotaParamAc = ac;
  window.rotaParamKapat = kapat;
  window.__rotaParamAcikMi = function(){ return !!rota; };
  window.__rotaParamDurum = function(){
    return {acik: !!rota, id: rota ? rota.id : null,
            serbest: serbestMi, noktalar: noktalar.slice()};
  };
})();
