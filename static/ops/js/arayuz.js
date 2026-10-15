// =================================================================
// GOKTUNGU - ACCORDION + ALT-ORTA PANEL + RESIZE TUTAMACLARI + ARAYUZ AYARLARI POPUP
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).
// =================================================================
"use strict";

// ---------------------------------------------------------------
// YUZEN PANELLER: toolbar dugmesinin hizasinda acilir; basliktan
// suruklenerek tasinabilir. Tasinan panel, kullanici kapatana kadar
// kendi konumunda kalir (resize'da otomatik hizalanmaz).
// ---------------------------------------------------------------
(function(){
  // Panel, kendi toolbar dugmesinin dikey hizasinda, yan panelin hemen
  // yaninda acilir (sol toolbar -> panelin sag kenari yaninda,
  // sag toolbar -> panelin sol kenari yaninda).
  function konumla(panelId){
    const panel = document.getElementById(panelId);
    const btn = document.querySelector('.tb-btn[data-yuzen="' + panelId + '"]');
    if (!panel) return;
    // Dugme yoksa veya gizliyse (menubar'a tasinan ogeler): ekran ust-ortasina ac
    const gizli = !btn || !btn.offsetParent;
    if (gizli) {
      panel.style.top = "60px";
      panel.style.right = "auto";
      panel.style.left = "50%";
      panel.style.transform = "translateX(-50%)";
      return;
    }
    panel.style.transform = "";
    const br = btn.getBoundingClientRect();
    const top = Math.max(46, Math.round(br.top));
    panel.style.top = top + "px";
    if (panelId === "yzRadar" || panelId === "yzFiltre" || panelId === "yzIz" ||
        panelId === "yzSinif" || panelId === "yzKayit") {
      // Sol taraf: dugmenin sag kenarinin hemen yaninda
      panel.style.left = Math.round(br.right + 10) + "px";
      panel.style.right = "auto";
    } else {
      // Sag taraf: dugmenin sol kenarinin hemen yaninda
      panel.style.right = Math.round(window.innerWidth - br.left + 10) + "px";
      panel.style.left = "auto";
    }
  }

  function panelAc(panelId, btn){
    const panel = document.getElementById(panelId);
    if (!panel) return;
    // Kayitli konum varsa oradan ac; yoksa dugme hizasinda basla
    // v2.4.213 KOK NEDEN (kullanici: "tum paneller son boyut ve konumda
    // acilsin"): boyut kaydediliyor (popup_tasima resize tutamaci) ama
    // acilista YALNIZ konum uygulaniyordu. Artik w/h de geri yuklenir.
    if (typeof window.pencereKonumUygula === "function" &&
        window.pencereKonumUygula("yz_" + panelId, panel, true)) {
      panel.dataset.tasindi = "1";
    } else {
      panel.dataset.tasindi = "";
      konumla(panelId);
    }
    panel.classList.remove("yuzen-gizli");
    // v2.2.0: acilan panel her zaman en uste gelir
    if (typeof window.pencereEnUsteKur === "function") window.pencereEnUsteKur(panel);
    if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(panel);
    if (btn) btn.classList.add("acik");
  }
  // v2.4.181: diger modullerin (ornegin kameralar.js'in M50 dugmesi)
  // dinamik olarak eklenen dugmelerden ayni yuzen panel ac/getir
  // davranisini tetikleyebilmesi icin disari acilir.
  window.yuzenPanelAc = function (panelId){ panelAc(panelId, null); };

  function panelKapat(panelId){
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.add("yuzen-gizli");
    const btn = document.querySelector('.tb-btn[data-yuzen="' + panelId + '"]');
    if (btn) btn.classList.remove("acik");
  }

  // Toolbar dugmeleri: toggle
  document.querySelectorAll(".tb-btn[data-yuzen]").forEach(btn => {
    btn.addEventListener("click", () => {
      const panelId = btn.dataset.yuzen;
      const panel = document.getElementById(panelId);
      if (!panel) return;
      if (panel.classList.contains("yuzen-gizli")) panelAc(panelId, btn);
      else panelKapat(panelId);
    });
  });

  // Acilir menu icindeki yuzen panel item'lari
  document.querySelectorAll(".dk-menu-item[data-yuzen]").forEach(item => {
    item.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const panelId = item.dataset.yuzen;
      const panel = document.getElementById(panelId);
      if (!panel) return;
      // Menu'yu kapat
      const dd = item.closest(".dk-menu-dropdown");
      if (dd) dd.classList.remove("acik");
      if (panel.classList.contains("yuzen-gizli")) panelAc(panelId, null);
      else panelKapat(panelId);
    });
  });

  // Menubar icindeki yuzen panel ogeleri
  document.querySelectorAll(".mb-oge[data-yuzen]").forEach(item => {
    item.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const panelId = item.dataset.yuzen;
      const panel = document.getElementById(panelId);
      if (!panel) return;
      const mi = item.closest(".mb-item");
      if (mi) mi.classList.remove("acik");
      if (panel.classList.contains("yuzen-gizli")) panelAc(panelId, null);
      else panelKapat(panelId);
    });
  });

  // Hedef menu tetik dugmesi
  const hedefMenuBtn = document.getElementById("tbHedefMenu");
  const hedefMenuDD = document.getElementById("hedefMenuDropdown");
  if (hedefMenuBtn && hedefMenuDD) {
    hedefMenuBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      document.querySelectorAll(".dk-menu-dropdown.acik").forEach(m => { if (m !== hedefMenuDD) m.classList.remove("acik"); });
      const acilacak = !hedefMenuDD.classList.contains("acik");
      hedefMenuDD.classList.toggle("acik");
      if (acilacak) {
        const r = hedefMenuBtn.getBoundingClientRect();
        let top = r.bottom + 4;
        let left = r.left;
        // Ekran dışına taşmasını engelle
        hedefMenuDD.style.top = top + "px";
        hedefMenuDD.style.left = left + "px";
        const mr = hedefMenuDD.getBoundingClientRect();
        if (mr.right > window.innerWidth) left = window.innerWidth - mr.width - 8;
        if (mr.bottom > window.innerHeight) top = r.top - mr.height - 4;
        hedefMenuDD.style.top = top + "px";
        hedefMenuDD.style.left = left + "px";
      }
    });
    document.addEventListener("click", (ev) => {
      if (!hedefMenuDD.contains(ev.target) && ev.target !== hedefMenuBtn && !hedefMenuBtn.contains(ev.target))
        hedefMenuDD.classList.remove("acik");
    });
  }

  // Kapatma dugmeleri
  document.querySelectorAll(".yuzen-kapat[data-yuzen]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      panelKapat(btn.dataset.yuzen);
    });
  });

  // Pencere boyutu veya yan panel genisligi degisince acik panelleri
  // dugme hizasina gore yeniden konumlandir (kullanicinin tasidigi
  // paneller kendi konumunda birakilir)
  function acikPanelleriKonumla(){
    document.querySelectorAll(".yuzen-panel:not(.yuzen-gizli)").forEach(p => {
      if (p.dataset.tasindi !== "1") konumla(p.id);
    });
  }
  window.addEventListener("resize", acikPanelleriKonumla);
  // Yan panel resize tutamaclari da tetiklesin diye global erisim
  window.yuzenPanelleriKonumla = acikPanelleriKonumla;

  // -------------------------------------------------------------
  // BASLIKTAN SURUKLEYEREK TASIMA
  // -------------------------------------------------------------
  document.querySelectorAll(".yuzen-panel").forEach(panel => {
    // v2.2.0: panele/basligina tiklaninca en uste getir
    if (typeof window.pencereEnUsteKur === "function") window.pencereEnUsteKur(panel);
    const baslik = panel.querySelector(".yuzen-baslik");
    if (!baslik) return;
    let surukle = null;

    baslik.addEventListener("pointerdown", (e) => {
      // Kapatma dugmesi veya baslik icindeki etkilesimli ogeler haric
      if (e.target.closest("button, input, select, a")) return;
      const pr = panel.getBoundingClientRect();
      // Transform'lu (ortalanmis) panel: gercek konumu sabitleyip transform'u kaldir
      if (panel.style.transform) {
        panel.style.left = Math.round(pr.left) + "px";
        panel.style.top = Math.round(pr.top) + "px";
        panel.style.right = "auto";
        panel.style.transform = "";
      }
      surukle = { dx: e.clientX - pr.left, dy: e.clientY - pr.top };
      baslik.setPointerCapture(e.pointerId);
      panel.classList.add("surukleniyor");
      e.preventDefault();
    });

    baslik.addEventListener("pointermove", (e) => {
      if (!surukle) return;
      const pr = panel.getBoundingClientRect();
      // Ekran sinirlari icinde tut (baslik her zaman erisilir kalsin)
      const maxX = window.innerWidth - 60;
      const maxY = window.innerHeight - 40;
      const x = Math.min(Math.max(e.clientX - surukle.dx, 60 - pr.width), maxX);
      const y = Math.min(Math.max(e.clientY - surukle.dy, 0), maxY);
      panel.style.left = Math.round(x) + "px";
      panel.style.top  = Math.round(y) + "px";
      panel.style.right = "auto";
      panel.dataset.tasindi = "1";
    });

    function birak(e){
      if (!surukle) return;
      surukle = null;
      panel.classList.remove("surukleniyor");
      try { baslik.releasePointerCapture(e.pointerId); } catch(err){}
      // IS56: dok kancasi kaldirildi — ic ice gecme davranisi yok.
      // Konumu kalici kaydet
      if (panel.dataset.tasindi === "1" &&
          typeof window.pencereKonumKaydet === "function") {
        // v2.4.213: tasima kaydi boyutu SILMESIN (w/h ile birlikte yazilir)
        window.pencereKonumKaydet("yz_" + panel.id, panel, true);
      }
    }
    baslik.addEventListener("pointerup", birak);
    baslik.addEventListener("pointercancel", birak);
  });

  // Eski surukleme konumu kayitlarini temizle (artik kullanilmiyor)
  try { localStorage.removeItem("gcs_yuzen_konum"); } catch(e){}
})();

// ---------------------------------------------------------------
// ALT-ORTA PANEL (KONSOL + GRAFIK): acilir/kapanir, durum kalici
// ---------------------------------------------------------------
(function(){
  const panel = document.getElementById("altOrtaPanel");
  const baslik = document.getElementById("altOrtaBaslik");
  if (!panel || !baslik) return;
  const KEY = "gcs_alt_orta";
  try { if (localStorage.getItem(KEY) === "kapali") panel.classList.add("kapali"); } catch(e){}
  baslik.addEventListener("click", () => {
    panel.classList.toggle("kapali");
    try { localStorage.setItem(KEY, panel.classList.contains("kapali") ? "kapali" : "acik"); } catch(e){}
    if (!panel.classList.contains("kapali") && typeof grafikCiz === "function") {
      setTimeout(grafikCiz, 50);
    }
  });
})();

// ---------------------------------------------------------------
// PANEL RESIZE TUTAMACLARI
// ---------------------------------------------------------------
(function(){
  const SOL_KEY = "gcs_sol_gen";
  const SAG_KEY = "gcs_sag_gen";
  const MIN_GEN = 200;
  const MAX_GEN = 600;
  const solPanel = document.getElementById("solPanel");
  const sagPanel = document.getElementById("sagPanel");
  const solTutamac = document.getElementById("solTutamac");
  const sagTutamac = document.getElementById("sagTutamac");

  // Kayitli genislikleri uygula
  function yukle(){
    try {
      const sg = parseInt(localStorage.getItem(SOL_KEY));
      if (sg >= MIN_GEN && sg <= MAX_GEN) {
        solPanel.style.flex = "0 0 " + sg + "px";
        solPanel.style.width = sg + "px";
      }
      const sag = parseInt(localStorage.getItem(SAG_KEY));
      if (sag >= MIN_GEN && sag <= MAX_GEN) {
        sagPanel.style.flex = "0 0 " + sag + "px";
        sagPanel.style.width = sag + "px";
      }
    } catch(e){}
  }
  yukle();

  function baslat(tutamac, panel, yonSol){
    let surukleniyor = false;
    tutamac.addEventListener("mousedown", (e) => {
      e.preventDefault();
      surukleniyor = true;
      tutamac.classList.add("aktif");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const surukle = (ev) => {
        if (!surukleniyor) return;
        let gen;
        if (yonSol) {
          gen = ev.clientX - solPanel.getBoundingClientRect().left;
        } else {
          gen = window.innerWidth - ev.clientX - sagTutamac.getBoundingClientRect().width;
        }
        gen = Math.max(MIN_GEN, Math.min(MAX_GEN, gen));
        panel.style.flex = "0 0 " + gen + "px";
        panel.style.width = gen + "px";
        panel.style.transition = "none";
        // Acik popup panelleri dugme hizasina gore yeniden konumlandir
        if (typeof window.yuzenPanelleriKonumla === "function") window.yuzenPanelleriKonumla();
      };
      const birak = () => {
        surukleniyor = false;
        tutamac.classList.remove("aktif");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        panel.style.transition = "";
        // Kaydet
        const gen = parseInt(panel.style.width);
        try {
          localStorage.setItem(yonSol ? SOL_KEY : SAG_KEY, gen);
        } catch(e){}
        document.removeEventListener("mousemove", surukle);
        document.removeEventListener("mouseup", birak);
      };
      document.addEventListener("mousemove", surukle);
      document.addEventListener("mouseup", birak);
    });
  }

  if (solTutamac && solPanel) baslat(solTutamac, solPanel, true);
  if (sagTutamac && sagPanel) baslat(sagTutamac, sagPanel, false);
})();

// ---------------------------------------------------------------
// ---------------------------------------------------------------
// ARAYUZ AYARLARI POPUP TOGGLE
// ---------------------------------------------------------------
(function(){
  const btn = document.getElementById("btnArayuzAyar");
  const popup = document.getElementById("arayuzPopup");
  const kapat = document.getElementById("btnPopupKapat");
  if (!btn || !popup) return;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    popup.classList.toggle("popup-gizli");
  });
  if (kapat) kapat.addEventListener("click", () => popup.classList.add("popup-gizli"));
  // Disariya tiklaninca kapat
  document.addEventListener("click", (e) => {
    if (!popup.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
      popup.classList.add("popup-gizli");
    }
  });
})();

// ---------------------------------------------------------------
// HARITA AYARLARI POPUP TOGGLE
// ---------------------------------------------------------------
(function(){
  const btn = document.getElementById("btnHaritaAyar");
  const popup = document.getElementById("haritaPopup");
  const kapat = document.getElementById("btnHaritaPopupKapat");
  if (!btn || !popup) return;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    popup.classList.toggle("popup-gizli");
  });
  if (kapat) kapat.addEventListener("click", () => popup.classList.add("popup-gizli"));
  // Disariya tiklaninca kapat
  document.addEventListener("click", (e) => {
    if (!popup.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
      popup.classList.add("popup-gizli");
    }
  });
})();

// ---------------------------------------------------------------
// TAM EKRAN DUGMESI (ust bar en sag)
// ---------------------------------------------------------------
(function(){
  const btn = document.getElementById("btnTamEkran");
  if (!btn) return;
  const ikon = btn.querySelector("i");

  function tamEkranda(){
    return !!(document.fullscreenElement || document.webkitFullscreenElement);
  }

  function ikonGuncelle(){
    if (!ikon) return;
    if (tamEkranda()) {
      ikon.classList.remove("fa-expand");
      ikon.classList.add("fa-compress");
      btn.title = (typeof i18nGetir === "function" && i18nGetir("btnTamEkranKapat")) || "Tam Ekrandan \u00c7\u0131k";
    } else {
      ikon.classList.remove("fa-compress");
      ikon.classList.add("fa-expand");
      btn.title = (typeof i18nGetir === "function" && i18nGetir("btnTamEkran")) || "Tam Ekran";
    }
  }

  btn.addEventListener("click", () => {
    if (tamEkranda()) {
      if (document.exitFullscreen) document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
    } else {
      const el = document.documentElement;
      if (el.requestFullscreen) el.requestFullscreen();
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    }
  });

  function tamEkranDegisti(){
    ikonGuncelle();
    // v2.1.7b: tam ekranda sol/sag paneller gizlenir, acik bolumler
    // tasinabilir popup'a donusur; cikista eski yerlerine doner
    if (typeof window.bolumTamEkranModu === "function") {
      window.bolumTamEkranModu(tamEkranda());
    }
  }

  document.addEventListener("fullscreenchange", tamEkranDegisti);
  document.addEventListener("webkitfullscreenchange", tamEkranDegisti);
  ikonGuncelle();
})();
