// =====================================================================
// HEPGO HAREKÂT — hepgo_sim.js (§14 Uçuş Simülatörü: kartlar 3B dünyanın üstünde yüzer)
// ---------------------------------------------------------------------
// Simülatör oturumunda (?sim=) bu sayfa, üst penceredeki 3B tuvalin TAMAMINI kaplayan ŞEFFAF bir iframe'dir
// (flightsim_ops.js). Ayrı bir panel/pencere yoktur: dron kartı (başlık rozetleri + PFD + telemetri karoları + İŞLEMLER)
// sağ üstte, KONSOL alt ortada yüzen HUD kartlarıdır (hepgo.css html[data-hepgo-sim]). Bu betik iframe tarafındaki
// davranışları ekler; GÖKTUNGU dosyalarına dokunulmaz:
//   1. Olay kapısı: iframe üst pencerede normalde pointer-events:none'dır (3B döndürme/yakınlaştırma çalışır); üst pencere
//      imleç görünür bir öğenin üstündeyken iframe'e .fs-ops-hit verir. Burada imleç BOŞ alana (html/body/harita kabı) gelince
//      sınıf geri kaldırılır — basılı/sürükleme sırasında kaldırılmaz (kart başlığından sürükleme, kaydırma).
//   2. Odak ve tuşlar: karta tıklanınca odak üst pencereye geri alınır ({t:'ops-focus'}); form alanı (input/select/textarea)
//      odaklı değilse yakalanan keydown/keyup üst pencereye sentetik KeyboardEvent olarak iletilir (1–4 kamera, H HUD, P kartlar,
//      WASD/ok tuşları sanal kumanda). Escape iletilmez (popup/onay kapatır).
//   3. Konsol kutusunun (#altOrtaPanel) üst kenarı üst pencereye bildirilir ({t:'ops-layout', con}) → olay şeridi onun üstüne çıkar.
//   4. Üst pencere durumu ({t:'fs-state', rc}) → html[data-fs-rc]: sanal kumanda açıkken konsol ipucu şeridinin üstüne çıkar, kart kısalır.
//   5. Kart yerleşimi: hepgo_patch.js sim kipinde kartı SAĞ ÜSTE dizer; başlığından sürüklenince konum (sağ kenara göre) + genişlik
//      localStorage hepgo_sim_kart'ta saklanır, açılışta uygulanır. Sol araç grubuna "Yerleşimi sıfırla" düğmesi (#btnYerlesimSifirla).
// YÜKLEME: index.html'de hepgo_ws.js'den sonra; görev kipinde (?task=) hiçbir şey yapmaz.
// =====================================================================
(function () {
  var q; try { q = new URLSearchParams(location.search); } catch (e) { q = null; }
  if (!q || q.get("task") || !(parseInt(q.get("sim"), 10) > 0)) return;
  var html = document.documentElement, fr = null, P = null;
  try { fr = window.frameElement; } catch (e) { fr = null; }
  try { P = (window.parent && window.parent !== window) ? window.parent : null; } catch (e) { P = null; }
  function gonder(m) { try { if (P) P.postMessage(m, location.origin); } catch (e) {} }
  var BOS = { anaAlan: 1, haritaAlan: 1, cesiumContainer: 1, hepgoGizliCapalar: 1 };
  function bos(el) { return !el || el === html || el === document.body || BOS[el.id] === 1; }
  function duzenlenebilir(el) { return !!el && !!el.tagName && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable === true); }
  var en = false;
  try { var pl = (P && P.document.documentElement.lang) || html.lang || "tr"; en = !/^tr/i.test(pl); } catch (e) {}
  function T(tr, enn) { return en ? enn : tr; }

  // ---- 1. Olay kapısı ----
  var basili = false;
  function kapiKapat() { if (fr) { try { fr.classList.remove("fs-ops-hit"); return; } catch (e) {} } gonder({ t: "ops-hit", hit: false }); }
  document.addEventListener("pointerdown", function (e) { basili = !bos(e.target); if (!basili) kapiKapat(); }, true);
  document.addEventListener("pointermove", function (e) { if (!basili && bos(e.target)) kapiKapat(); }, true);
  function birak(e) {
    var vardi = basili; basili = false;
    if (bos(e.target)) kapiKapat();
    // karta/düğmeye tıklandıysa odak üst pencereye (klavye kısayolları orada); form alanlarında kalır
    if (vardi && !duzenlenebilir(e.target) && !duzenlenebilir(document.activeElement)) setTimeout(function () { gonder({ t: "ops-focus" }); }, 0);
  }
  window.addEventListener("pointerup", birak, true);
  window.addEventListener("pointercancel", birak, true);
  window.addEventListener("blur", function () { basili = false; });

  // ---- 2. Tuş iletimi ----
  function tusIlet(e) {
    if (!P || e.key === "Escape") return;
    if (duzenlenebilir(e.target) || duzenlenebilir(document.activeElement)) return;
    try {
      var ev = new P.KeyboardEvent(e.type, { key: e.key, code: e.code, keyCode: e.keyCode, which: e.which, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey,
        altKey: e.altKey, metaKey: e.metaKey, repeat: e.repeat, bubbles: true, cancelable: true });
      P.dispatchEvent(ev);
      if (ev.defaultPrevented) e.preventDefault();
    } catch (err) {}
  }
  document.addEventListener("keydown", tusIlet, true);
  document.addEventListener("keyup", tusIlet, true);

  // ---- 3. Konsol kutusu üst kenarı → üst pencere ----
  var kon = document.getElementById("altOrtaPanel"), sonCon = -1;
  function konBildir() {
    var v = 0;
    if (kon && getComputedStyle(kon).display !== "none") { var r = kon.getBoundingClientRect(); v = Math.max(0, Math.round(window.innerHeight - r.top)); }
    if (v !== sonCon) { sonCon = v; gonder({ t: "ops-layout", con: v }); }
  }
  if (kon) {
    try { new ResizeObserver(konBildir).observe(kon); } catch (e) {}
    try { new MutationObserver(konBildir).observe(kon, { attributes: true, attributeFilter: ["class", "style"] }); } catch (e) {}
  }
  window.addEventListener("resize", konBildir);
  setTimeout(konBildir, 0);

  // ---- 4. Üst pencere durumu ----
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin || !e.data || e.data.t !== "fs-state") return;
    if (e.data.rc) html.dataset.fsRc = "1"; else delete html.dataset.fsRc;
    konBildir();
    if (window.hepgoKartDiz) window.hepgoKartDiz();
  });

  // ---- 5. Kart konumu (localStorage) + Yerleşimi sıfırla ----
  var KEY = "hepgo_sim_kart";
  function kartlar() { return Array.prototype.slice.call(document.querySelectorAll("body > .dron-kart.ayrik")); }
  function kayit() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  window.hepgoSimKartBirakildi = function (kok) {   // hepgo_patch.js birak() sonunda
    try {
      if (kok.dataset.hepgoSerbest !== "1") { localStorage.removeItem(KEY); return; }
      var r = kok.getBoundingClientRect();
      localStorage.setItem(KEY, JSON.stringify({ r: Math.round(window.innerWidth - r.right), y: Math.round(r.top), w: Math.round(r.width) }));
    } catch (e) {}
  };
  window.hepgoSimKartYukle = function (kok) {   // hepgo_patch.js hepgoKartHazirla içinde ve resize'da
    var k = kayit();
    if (!k || typeof k.r !== "number" || typeof k.y !== "number") return false;
    if (k.w > 0) kok.style.width = k.w + "px";
    var w = kok.offsetWidth || k.w || 400;
    kok.dataset.hepgoSerbest = "1";
    kok.style.left = Math.max(0, Math.min(window.innerWidth - k.r - w, window.innerWidth - w)) + "px";
    kok.style.top = Math.max(0, Math.min(k.y, window.innerHeight - 40)) + "px";
    return true;
  };
  window.addEventListener("resize", function () { if (kayit()) kartlar().forEach(function (k) { if (!k._hepgoSurukleniyor) window.hepgoSimKartYukle(k); }); });
  function sifirla() {
    try { localStorage.removeItem(KEY); localStorage.setItem("gcs_alt_orta", "acik"); } catch (e) {}
    kartlar().forEach(function (k) { delete k.dataset.hepgoSerbest; k.style.width = ""; k.classList.remove("dk-yalniz-baslik"); });
    if (kon) kon.classList.remove("kapali");
    if (window.hepgoKartDiz) window.hepgoKartDiz();
  }
  function dugmeEkle() {
    var grup = document.getElementById("haritaAracGrubu");
    if (!grup || document.getElementById("btnYerlesimSifirla")) return;
    var b = document.createElement("button");
    b.id = "btnYerlesimSifirla"; b.type = "button";
    b.title = T("Yerleşimi sıfırla (kart sağ üste, konsol alt ortaya)", "Reset layout (card top right, console bottom centre)");
    b.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i>';
    b.addEventListener("click", function (e) { e.stopPropagation(); sifirla(); });
    grup.appendChild(b);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", dugmeEkle); else dugmeEkle();
  window.hepgoSimYerlesimSifirla = sifirla;
})();
