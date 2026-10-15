// =====================================================================
// UYARI_MERKEZI.JS - MERKEZI UYARI SISTEMI (v2.1.7)
// ---------------------------------------------------------------------
// - Sistemin urettigi uyarilar (ozellikle izin reddi) sunucuda pilot
//   bazinda birikir.
// - Ust barda profil ikonunun yaninda can ikonu + okunmamis sayisi.
// - Cana tiklayinca: uyari listesi popup'i acilir ve TUM uyarilar
//   okundu sayilir (rozet sifirlanir).
// - Profil menusundeki "Uyarılar" ogesi de ayni listeyi acar.
// =====================================================================
"use strict";

let _umOkunmamis = 0;      // okunmamis uyari sayisi
let _umPopup = null;       // acik uyari listesi popup'u

const _umBtn = document.getElementById("btnUyarilar");
const _umRozet = document.getElementById("uyariRozet");
const _umPmRozet = document.getElementById("pmUyariRozet");

// ---------------------------------------------------------------
// Rozet guncelleme
// ---------------------------------------------------------------
function uyariRozetGuncelle(sayi) {
  _umOkunmamis = Math.max(0, sayi | 0);
  const txt = _umOkunmamis > 99 ? "99+" : String(_umOkunmamis);
  for (const r of [_umRozet, _umPmRozet]) {
    if (!r) continue;
    r.textContent = txt;
    r.style.display = _umOkunmamis > 0 ? "inline-flex" : "none";
  }
}

// Oturum acilinca cani goster (kullanici.js oturumArayuzuKur cagirir)
window.uyariMerkeziOturum = function (okunmamis) {
  if (_umBtn) _umBtn.style.display = "";
  uyariRozetGuncelle(okunmamis || 0);
};

window.uyariMerkeziCikis = function () {
  if (_umBtn) _umBtn.style.display = "none";
  uyariRozetGuncelle(0);
  uyariListesiKapat();
};

// ---------------------------------------------------------------
// WS mesajlari (ws.js yonlendirir)
// ---------------------------------------------------------------
// ---------------------------------------------------------------
// v2.1.7c: TOAST BILDIRIMI - uyari olusur olusmaz ekranin en
// saginda belirir, birkac saniye sonra otomatik kaybolur
// ---------------------------------------------------------------
const UM_TOAST_SURE = 5000;        // ms - uyari/bilgi ekranda kalma suresi
const UM_TOAST_SURE_HATA = 9000;   // ms - v2.4.33: hatalar daha uzun kalir

// v2.4.33: seviye -> ikon/baslik/CSS sinifi eslemesi.
// Onceki surumde her bildirim ayni sari ucgen ikonuyla "UYARI" olarak
// cikiyordu; hata ile bilgi ayirt edilemiyordu.
const UM_TOAST_TIP = {
  hata:   { sinif: "tip-hata",   ikon: "fa-circle-exclamation",   bas: "HATA" },
  uyari:  { sinif: "tip-uyari",  ikon: "fa-triangle-exclamation", bas: "UYARI" },
  basari: { sinif: "tip-basari", ikon: "fa-circle-check",         bas: "TAMAM" },
  bilgi:  { sinif: "tip-bilgi",  ikon: "fa-circle-info",          bas: "BILGI" },
};

function uyariToastGoster(uyari) {
  let kap = document.getElementById("umToastKap");
  if (!kap) {
    kap = document.createElement("div");
    kap.id = "umToastKap";
    document.body.appendChild(kap);
  }
  const t = D();
  const sev = (uyari && uyari.seviye) || "uyari";
  const tip = UM_TOAST_TIP[sev] || UM_TOAST_TIP.uyari;
  const el = document.createElement("div");
  el.className = "um-toast " + tip.sinif;
  const kat = (uyari && uyari.kategori) || "sistem";
  el.innerHTML =
    "<i class='fa-solid " + tip.ikon + "'></i>" +
    "<div class='um-toast-icerik'>" +
    "<div class='um-toast-baslik'></div>" +
    "<div class='um-toast-mesaj'></div></div>" +
    "<button class='um-toast-kapat'><i class='fa-solid fa-xmark'></i></button>";
  // Baslik: seviye etiketi + kaynak alt sistem (ornek "HATA \u00b7 KOMUT")
  const sevAd = (sev === "hata" ? (t.umToastHata || tip.bas)
              : sev === "basari" ? (t.umToastBasari || tip.bas)
              : sev === "bilgi" ? (t.umToastBilgi || tip.bas)
              : (t.umToastBaslik || tip.bas));
  el.querySelector(".um-toast-baslik").textContent =
    sevAd + " \u00b7 " + String(kat).toUpperCase();
  el.querySelector(".um-toast-mesaj").textContent =
    (uyari && uyari.mesaj) || "";
  const kaldir = () => {
    el.classList.add("um-toast-cikis");
    setTimeout(() => el.remove(), 320);
  };
  el.querySelector(".um-toast-kapat").addEventListener("click", (e) => {
    e.stopPropagation();
    kaldir();
  });
  // Tiklaninca uyari listesini ac
  el.addEventListener("click", (e) => {
    if (e.target.closest(".um-toast-kapat")) return;
    kaldir();
    try { uyariListesiAc(); } catch (err) {}
  });
  kap.appendChild(el);
  // En fazla 4 toast ust uste; eskileri at
  while (kap.children.length > 4) kap.firstChild.remove();

  // v2.4.33: sure seviyeye gore. Hata bildirimleri daha uzun kalir
  // (takeoff reddi gibi gerekce metinleri okunacak kadar surmeli).
  const sure = (sev === "hata") ? UM_TOAST_SURE_HATA : UM_TOAST_SURE;
  // v2.4.33: fare bildirimin uzerindeyken sayac durur; ayrilinca
  // yeniden baslar. Uzun gerekce metinleri okunurken kaybolmasin.
  let zaman = setTimeout(kaldir, sure);
  el.addEventListener("mouseenter", () => { clearTimeout(zaman); });
  el.addEventListener("mouseleave", () => {
    clearTimeout(zaman);
    zaman = setTimeout(kaldir, 1800);
  });
}
window.uyariToastGoster = uyariToastGoster;

// Yeni uyari geldi (izin reddi vb.)
window.uyariYeniIsle = function (m) {
  if (typeof m.okunmamis === "number") uyariRozetGuncelle(m.okunmamis);
  else uyariRozetGuncelle(_umOkunmamis + 1);
  // Kisa sure can ikonunu salla
  if (_umBtn) {
    _umBtn.classList.add("uyari-salla");
    setTimeout(() => _umBtn.classList.remove("uyari-salla"), 900);
  }
  // v2.1.7c: sag kenarda toast bildirimi goster
  if (m.uyari) uyariToastGoster(m.uyari);
  // Konsol paneline de dus (varsa)
  if (m.uyari && typeof window.konsolaEkle === "function") {
    try { window.konsolaEkle("UYARI", m.uyari.mesaj, "uyari"); } catch (e) {}
  }
};

// Uyari listesi cevabi
window.uyariListesiIsle = function (m) {
  // Pilot Hakkında modulu acik ise ona da ver
  if (typeof window.pilotUyariListeIsle === "function")
    window.pilotUyariListeIsle(m);
  if (!_umPopup) return;
  const t = D();
  const kutu = _umPopup.querySelector(".um-liste");
  if (!kutu) return;
  const liste = m.uyarilar || [];
  kutu.innerHTML = "";
  if (liste.length === 0) {
    kutu.innerHTML = "<div class='ph-liste-bos'>" +
      (t.phUyariBos || "Uyarı yok") + "</div>";
    return;
  }
  for (const u of liste) {
    const el = document.createElement("div");
    el.className = "um-uyari" + (u.okundu ? "" : " okunmamis");
    const dt = new Date((u.ts || 0) * 1000);
    el.innerHTML =
      "<i class='fa-solid fa-triangle-exclamation'></i>" +
      "<div class='um-govde'>" +
        "<div class='um-mesaj'>" + umKacir(u.mesaj || "") + "</div>" +
        "<div class='um-zaman'>" + dt.toLocaleDateString() + " " +
          dt.toTimeString().slice(0, 8) + "</div>" +
      "</div>";
    kutu.appendChild(el);
  }
};

function umKacir(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ---------------------------------------------------------------
// Uyari listesi popup'u
// ---------------------------------------------------------------
function uyariListesiAc() {
  if (_umPopup) { uyariListesiKapat(); return; }
  const t = D();
  const pop = document.createElement("div");
  pop.className = "um-popup";
  _umPopup = pop;
  const bas = document.createElement("div");
  bas.className = "popup-baslik";
  bas.innerHTML =
    "<span><i class='fa-solid fa-bell'></i> " +
    (t.umBaslik || "UYARILAR") + "</span>" +
    "<button class='popup-kapat' id='umKapat'><i class='fa-solid fa-xmark'></i></button>";
  pop.appendChild(bas);
  const liste = document.createElement("div");
  liste.className = "um-liste";
  liste.innerHTML = "<div class='ph-liste-bos'>" +
    (t.phYukleniyor || "Yükleniyor...") + "</div>";
  pop.appendChild(liste);
  document.body.appendChild(pop);
  // Can ikonunun altina hizala
  const r = (_umBtn || document.getElementById("profilKutu"))
    .getBoundingClientRect();
  pop.style.top = (r.bottom + 6) + "px";
  pop.style.left = Math.max(10, Math.min(r.right - pop.offsetWidth,
    window.innerWidth - pop.offsetWidth - 10)) + "px";
  if (window.popupTasinabilirYap) popupTasinabilirYap(pop, bas, "pp_uyariListe");
  if (window.popupBoyutlandirilabilirYap)
    popupBoyutlandirilabilirYap(pop, "pp_uyariListe", { minW: 320, minH: 240 });
  document.getElementById("umKapat").addEventListener("click", uyariListesiKapat);

  // Listeyi iste + tumunu okundu isaretle (rozet sifirlanir)
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ tip: "uyari_listesi" }));
    ws.send(JSON.stringify({ tip: "uyari_okundu" }));
  }
  uyariRozetGuncelle(0);
}

function uyariListesiKapat() {
  if (_umPopup) { _umPopup.remove(); _umPopup = null; }
}

// Dis tiklamada kapat
document.addEventListener("click", (e) => {
  if (_umPopup && !_umPopup.contains(e.target) &&
      !(_umBtn && _umBtn.contains(e.target))) {
    uyariListesiKapat();
  }
});

// ---------------------------------------------------------------
// Baglantilar
// ---------------------------------------------------------------
if (_umBtn) _umBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  uyariListesiAc();
});

(function () {
  const oge = document.getElementById("pmUyarilar");
  if (oge) oge.addEventListener("click", (e) => {
    e.stopPropagation();
    document.getElementById("profilMenu").classList.add("popup-gizli");
    uyariListesiAc();
  });
})();
