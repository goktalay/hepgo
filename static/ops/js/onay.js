// =================================================================
// GOKTUNGU - ONAY DIYALOGU (QGC tarzi KAYDIRMALI onay)
// Kullanim (degismedi):
//   onayIste("Mesaj metni", () => { ...onaylandi... });
//   onayIste("Mesaj", onOnay, onIptal);
// i18n yardimcisi:
//   onayMetni("onayKameraSil", {ad: "Kamera 1"}) -> sablondaki
//   {ad} yer tutuculari doldurulur.
// Onay, dugme yerine tutamacin saga kaydirilmasiyla verilir
// (yanlislikla onay verilmesini engeller). Iptal: dugme / Esc / perde.
// =================================================================
(function () {
  "use strict";

  let perde, kutu, mesajEl, btnHayir, ray, tutamac, rayMetin;
  let aktifOnay = null, aktifIptal = null;
  // Surukleme durumu
  let surukluyor = false, basX = 0, konumPx = 0, maxPx = 0, onaylandi = false;

  function kur() {
    if (perde) return;
    perde = document.createElement("div");
    perde.id = "onayPerde";
    perde.className = "popup-gizli";
    perde.innerHTML =
      '<div id="onayKutu">' +
      '  <div class="onay-baslik">' +
      '    <i class="fa-solid fa-triangle-exclamation"></i>' +
      '    <span id="onayBaslikMetin"></span>' +
      '  </div>' +
      '  <div id="onayMesaj"></div>' +
      '  <div class="onay-kaydir-ray" id="onayRay">' +
      '    <div class="onay-kaydir-dolgu" id="onayDolgu"></div>' +
      '    <span class="onay-kaydir-metin" id="onayRayMetin"></span>' +
      '    <div class="onay-kaydir-tutamac" id="onayTutamac">' +
      '      <i class="fa-solid fa-angles-right"></i>' +
      '    </div>' +
      '  </div>' +
      '  <div class="onay-dugme-satir">' +
      '    <button id="btnOnayHayir"></button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(perde);
    kutu = document.getElementById("onayKutu");
    mesajEl = document.getElementById("onayMesaj");
    btnHayir = document.getElementById("btnOnayHayir");
    ray = document.getElementById("onayRay");
    tutamac = document.getElementById("onayTutamac");
    rayMetin = document.getElementById("onayRayMetin");

    btnHayir.addEventListener("click", iptalEt);
    perde.addEventListener("click", (e) => {
      if (e.target === perde) iptalEt();
    });
    document.addEventListener("keydown", (e) => {
      if (perde.classList.contains("popup-gizli")) return;
      if (e.key === "Escape") { e.preventDefault(); iptalEt(); }
      // NOT: Enter ile onay bilerek KALDIRILDI — onay yalnizca kaydirma ile verilir.
    });

    // --- Kaydirma (pointer events: fare + dokunmatik) ---
    tutamac.addEventListener("pointerdown", (e) => {
      if (onaylandi) return;
      surukluyor = true;
      basX = e.clientX - konumPx;
      tutamac.setPointerCapture(e.pointerId);
      tutamac.classList.add("tutuluyor");
      e.preventDefault();
    });
    tutamac.addEventListener("pointermove", (e) => {
      if (!surukluyor || onaylandi) return;
      maxPx = ray.clientWidth - tutamac.offsetWidth - 8; // 4px kenar paylari
      konumPx = Math.max(0, Math.min(maxPx, e.clientX - basX));
      uygulaKonum(false);
      if (konumPx >= maxPx * 0.94) onayla();
    });
    function birak(e) {
      if (!surukluyor || onaylandi) { surukluyor = false; return; }
      surukluyor = false;
      tutamac.classList.remove("tutuluyor");
      // Yeterince kaydirilmadi: yaylanarak basa don
      konumPx = 0;
      uygulaKonum(true);
    }
    tutamac.addEventListener("pointerup", birak);
    tutamac.addEventListener("pointercancel", birak);
  }

  function uygulaKonum(animasyonlu) {
    tutamac.style.transition = animasyonlu ? "left .25s cubic-bezier(.2,.9,.3,1.2)" : "none";
    tutamac.style.left = (4 + konumPx) + "px";
    const dolgu = document.getElementById("onayDolgu");
    if (dolgu) {
      dolgu.style.transition = animasyonlu ? "width .25s ease" : "none";
      dolgu.style.width = (4 + konumPx + tutamac.offsetWidth / 2) + "px";
    }
    // Metin, tutamac yaklastikca solsun
    if (rayMetin && maxPx > 0) {
      rayMetin.style.opacity = String(Math.max(0.15, 1 - (konumPx / maxPx) * 1.3));
    }
  }

  function onayla() {
    if (onaylandi) return;
    onaylandi = true;
    surukluyor = false;
    konumPx = maxPx;
    uygulaKonum(true);
    ray.classList.add("onaylandi");
    const t = (typeof D === "function") ? D() : {};
    if (rayMetin) { rayMetin.textContent = t.onayOnaylandi || "ONAYLANDI"; rayMetin.style.opacity = "1"; }
    // Kisa gorsel geri bildirim sonrasi kapat + callback
    setTimeout(() => {
      const cb = aktifOnay;
      kapat();
      if (typeof cb === "function") cb();
    }, 280);
  }

  function iptalEt() {
    const cb = aktifIptal;
    kapat();
    if (typeof cb === "function") cb();
  }

  function kapat() {
    aktifOnay = null; aktifIptal = null;
    perde.classList.add("popup-gizli");
  }

  function sifirla() {
    onaylandi = false; surukluyor = false; konumPx = 0; maxPx = 0;
    ray.classList.remove("onaylandi");
    tutamac.classList.remove("tutuluyor");
    tutamac.style.transition = "none";
    tutamac.style.left = "4px";
    const dolgu = document.getElementById("onayDolgu");
    if (dolgu) { dolgu.style.transition = "none"; dolgu.style.width = "0px"; }
    if (rayMetin) rayMetin.style.opacity = "1";
  }

  // mesaj: gosterilecek metin; onOnay: kaydirinca; onIptal: iptalde (istege bagli)
  window.onayIste = function (mesaj, onOnay, onIptal) {
    kur();
    const t = (typeof D === "function") ? D() : {};
    document.getElementById("onayBaslikMetin").textContent =
      t.onayBaslik || "ONAY GEREKİYOR";
    btnHayir.textContent = t.onayIptalBtn || t.onayHayir || "İPTAL";
    rayMetin.textContent = t.onaySurukle || "ONAYLAMAK İÇİN KAYDIRIN";
    mesajEl.textContent = mesaj;
    aktifOnay = onOnay || null;
    aktifIptal = onIptal || null;
    sifirla();
    perde.classList.remove("popup-gizli");
    btnHayir.focus();
  };

  // i18n anahtarindan sablonlu mesaj uret: {ad} vb. yer tutucular dolar
  window.onayMetni = function (anahtar, degerler) {
    const t = (typeof D === "function") ? D() : {};
    let m = t[anahtar] || anahtar;
    if (degerler) {
      for (const k of Object.keys(degerler)) {
        m = m.split("{" + k + "}").join(String(degerler[k]));
      }
    }
    return m;
  };
})();
