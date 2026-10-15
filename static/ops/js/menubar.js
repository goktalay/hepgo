// =====================================================================
// MENUBAR.JS - Ust bar klasik menu cubugu
// Radar / Dronlar / Kameralar / Rotalar / Goktungu Uygulamasi
// Menu ogeleri mevcut islevlere delege eder (gizli dugmeler / global fn).
// =====================================================================
(function(){
  "use strict";

  const menubar = document.getElementById("menubar");
  if (!menubar) return;
  const items = [...menubar.querySelectorAll(".mb-item")];
  let acikItem = null;

  function kapat(){
    if (acikItem){ acikItem.classList.remove("acik"); acikItem = null; }
    // Ic-ice (flyout) alt menuleri de kapat.
    menubar.querySelectorAll(".mb-alt.acik-alt")
      .forEach(a => a.classList.remove("acik-alt"));
  }
  // v2.4.29: widget menu ogeleri de menuyu kapatabilmeli
  window.menubarKapat = kapat;
  function ac(item){
    if (acikItem === item) return;
    kapat();
    item.classList.add("acik");
    acikItem = item;
  }

  items.forEach(item => {
    const etiket = item.querySelector(".mb-etiket");
    etiket.addEventListener("click", (e) => {
      e.stopPropagation();
      if (acikItem === item) kapat();
      else ac(item);
    });
    // Bir menu acikken hover ile digerine gecis (klasik menu davranisi)
    etiket.addEventListener("mouseenter", () => {
      if (acikItem && acikItem !== item) ac(item);
    });
  });
  document.addEventListener("click", kapat);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") kapat();
  });

  // Herhangi bir menu ogesine tiklaninca menu kapansin
  menubar.querySelectorAll(".mb-oge").forEach(oge => {
    // FLYOUT EBEVEYNI (.mb-alt-bas): menuyu KAPATMAZ, alt menuyu acar.
    if (oge.classList.contains("mb-alt-bas")) return;
    oge.addEventListener("click", () => {
      // data-yuzen ogelerini arayuz.js kendi dinleyicisiyle isler;
      // burada yalnizca menuyu kapatiyoruz (islev calistiktan sonra).
      setTimeout(kapat, 0);
    });
  });

  // IC-ICE (FLYOUT) ALT MENU: Cihazlar/Sistem altindaki Radar/Dronlar vb.
  // Dokunmatik cihazlarda (tablet) hover yerine TIKLA ile acilir/kapanir.
  menubar.querySelectorAll(".mb-alt-bas").forEach(bas => {
    bas.addEventListener("click", (e) => {
      e.stopPropagation();
      const alt = bas.closest(".mb-alt");
      if (!alt) return;
      const acikMi = alt.classList.contains("acik-alt");
      // Ayni dropdown icindeki diger flyout'lari kapat (tek acik kalsin).
      const dd = alt.closest(".mb-dropdown");
      if (dd) dd.querySelectorAll(".mb-alt.acik-alt").forEach(a => {
        if (a !== alt) a.classList.remove("acik-alt");
      });
      alt.classList.toggle("acik-alt", !acikMi);
      // Ekran sagina tasarsa sola ac.
      if (!acikMi) {
        alt.classList.remove("sola");
        const menu = alt.querySelector(".mb-alt-menu");
        if (menu) {
          const r = menu.getBoundingClientRect();
          if (r.right > window.innerWidth - 4) alt.classList.add("sola");
        }
      }
    });
  });

  // -------------------------------------------------------------------
  // Delegasyon yardimcisi: gizli dugmeye tikla
  // -------------------------------------------------------------------
  function tikla(id){
    const el = document.getElementById(id);
    if (el) el.click();
  }
  function bagla(ogeId, fn){
    const el = document.getElementById(ogeId);
    if (el) el.addEventListener("click", fn);
  }

  // RADAR --------------------------------------------------------------
  bagla("mbTumTakibiBirak", () => {
    if (typeof tumTakibiBirak === "function") tumTakibiBirak();
  });

  // DRONLAR ------------------------------------------------------------
  // FAZ18_IS6_GECMIS_BAG: "Gecmis Yonetimi" menusu calismiyordu.
  // KOK NEDEN: `tbDronGecmis` ogesi hicbir yerde tanimli degil (bir
  // yeniden duzenlemede kaldirilmis, menu bagi kaldirilmamis).
  // tikla() icindeki `if (el)` korumasi yuzunden menuye basinca
  // sessizce hicbir sey olmuyordu.
  // COZUM: once eski dugme denenir (ileride geri eklenirse davranis
  // korunur), yoksa gecmis paneli DOGRUDAN acilir.
  bagla("mbDronGecmis", () => {
    const eskiBtn = document.getElementById("tbDronGecmis");
    if (eskiBtn) { eskiBtn.click(); return; }
    if (typeof window.dronGecmisAc === "function") {
      window.dronGecmisAc();
      return;
    }
    // gecmis.js yuklenmemisse kullanici karanlikta kalmasin
    if (typeof window.uyariToastGoster === "function") {
      window.uyariToastGoster({
        kategori: "DRON",
        mesaj: "Gecmis modulu yuklenemedi.",
        seviye: "hata",
      });
    }
  });
  // v2.4.42: Kayitli Dronlar paneli. Modul yuklenmemisse sessizce gecilir
  // (paketleme sirasinda dosya eksik kalirsa menu tiklanmasi hata
  // atmasin; ayni yedekli desen mbSuruUcus'ta da kullaniliyor).
  bagla("mbKayitliDronlar", () => {
    if (typeof window.kayitliDronlarAc === "function")
      window.kayitliDronlarAc();
  });
  bagla("mbSuruUcus", () => {
    if (typeof window.suruKurulumAc === "function") window.suruKurulumAc();
  });
  // v2.4.44: Yer Istasyonu 2 (ESP32-S3 kontrol paneli)
  bagla("mbIstasyon2", () => {
    if (typeof window.istasyon2Ac === "function") window.istasyon2Ac();
  });

  // FAZ19-IS71-K2-JS-SOKUM: KAMERALAR menu baglari kaldirildi.
  // Video/AI katmani sistemden cikarildi; ayri altyapida
  // yeniden kurgulanacak. Arsiv: /opt/goktungu/arsiv/

  // v2.4.33: Ucus Duvari IKINCI EKRAN icin tasarlandi; bu yuzden mevcut
  // sekmeyi degistirmek yerine YENI SEKMEDE acilir (video duvarindan
  // farkli davranis bilinclidir - kullanici haritayi kaybetmemeli).
  bagla("mbUcusDuvari", () => { window.open("/flight", "_blank"); });

  // ROTALAR ------------------------------------------------------------
  bagla("mbYeniRota", () => tikla("tbYeniRota"));
  bagla("mbTumRota", () => {
    if (typeof tumRotalariAcKapat === "function") tumRotalariAcKapat();
  });

  // GOKTUNGU (uygulama menusu) ---------------------------------------------
  // NOT: Bu ogeler dogrudan tikla("btn...") ile delege edilemez: ilgili
  // popup'larin document uzerinde "disari tiklaninca kapat" dinleyicileri
  // vardir ve ayni tiklama olayi bubbling ile document'a ulasinca popup
  // acilir acilmaz kapaniyordu. Cozum: olayin document'a ulasmasini kesip
  // gizli dugmeye tiklamayi bir sonraki tick'te yapmak.
  function guvenliTikla(ogeId, btnId, oncesi){
    const el = document.getElementById(ogeId);
    if (!el) return;
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      kapat();
      if (typeof oncesi === "function") oncesi();
      setTimeout(() => tikla(btnId), 0);
    });
  }
  // YARDIM > Program Hakkinda: acilis data-yuzen mekanizmasiyla yapilir
  // (arayuz.js .mb-oge[data-yuzen] dinleyicisi); burada yalnizca surum
  // bilgisini popup'a yazariz.
  /* Yardim Merkezi: merkez sunucudaki /yardim/ sayfasini ayri sekmede acar. */
  const mbYrdMerkez = document.getElementById("mbYardimMerkez");
  if (mbYrdMerkez) {
    mbYrdMerkez.addEventListener("click", () => {
      window.open(
        (typeof window.destekAdresi === "function"
          ? window.destekAdresi("") : "/yardim/"),
        "_blank", "noopener");
      if (typeof menubarKapat === "function") menubarKapat();
    });
  }
  // YARDIM > Guncellemeleri Denetle: uygulama ici dosya tabanli guncelleme
  // penceresini acar ve taze bir surum denetimi baslatir (js/guncelleme.js).
  const mbGunc = document.getElementById("mbGuncelleme");
  if (mbGunc) {
    mbGunc.addEventListener("click", () => {
      if (typeof menubarKapat === "function") menubarKapat();
      if (typeof window.guncellemeKapaliMi === "function" && window.guncellemeKapaliMi()) return;
      if (typeof window.guncellemePenceresiAc === "function")
        window.guncellemePenceresiAc();
    });
  }
  const mbHak = document.getElementById("mbHakkinda");
  if (mbHak){
    mbHak.addEventListener("click", () => {
      const srm = document.getElementById("hkSurum");
      if (srm && typeof GCS_SURUM !== "undefined")
        srm.textContent = GCS_SURUM +
          (typeof GCS_SURUM_TARIH !== "undefined" ? " (" + GCS_SURUM_TARIH + ")" : "");
    });
  }

  guvenliTikla("mbProgramAyar", "btnProgramAyar");
  guvenliTikla("mbLokasyonlar", "btnLokasyonlar");
  guvenliTikla("mbHaritaAyar", "btnHaritaAyar");
  guvenliTikla("mbArayuzAyar", "btnArayuzAyar");

  // v2.4.65 TEK KAPI: Kullanici Yonetimi bu arayuzden KALDIRILDI.
  // Uyelik ve rol islemleri kurumsal panelde (/company/) yapilir;
  // boylece kayit merkez tablosuna gider (girisin dogrulandigi yer) ve
  // pilot koltuk siniri atlanamaz. Profil menusunde bunun yerine
  // "Kurumsal Panel" baglantisi bulunur.
  const pmKurumsal = document.getElementById("pmKurumsalPanel");
  if (pmKurumsal){
    pmKurumsal.addEventListener("click", (e) => {
      e.stopPropagation();
      document.getElementById("profilMenu").classList.add("popup-gizli");
      window.open("/company/", "_blank", "noopener");
    });
  }

  // =====================================================================
  // PANEL AC/KAPAT (menulerden panel bolumlerini goster/gizle)
  // Durum localStorage'da saklanir (gcs_panel_gorunum).
  // 3 sag bolum de kapaliysa sag panel + tutamaci tamamen gizlenir;
  // 2 sol bolum de kapaliysa sol panel + tutamaci gizlenir.
  // =====================================================================
  const PANEL_BOLUM = {
    // v2.4.227 (kullanici istegi): Tespit/Takip sol dock bolumleri KALDIRILDI.
    // v2.4.33: ayri DRONLAR bolumu kaldirildi (kartlar Baglanti
    // Yoneticisi icinde). Kayit silindi; yoksa panelUygula() olmayan
    // ogeleri arar ve menu ogesi hicbir seyi degistirmez.
    // GRCOFF-IS1: Kamera popup'inin çarpı düğmesi ortak görünürlük
    // durumunu kapatır. Bu kayıt olmazsa kapatma isteği sessizce yok
    // sayılır ve Kamera paneli açık kalır.
    kameralar: { taraf: "sag", eller: ["kameralarToolbar", "kameralarIcerik"] },
    rotalar:   { taraf: "sag", eller: ["rotalarToolbar", "rotalarIcerik"] },
  };
  let panelDurum = { kameralar:true, rotalar:true };
  try {
    const k = JSON.parse(localStorage.getItem("gcs_panel_gorunum") || "{}");
    for (const ad in panelDurum) if (typeof k[ad] === "boolean") panelDurum[ad] = k[ad];
  } catch(e){}

  function panelUygula(){
    for (const ad in PANEL_BOLUM){
      const acikMi = panelDurum[ad];
      PANEL_BOLUM[ad].eller.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = acikMi ? "" : "none";
      });
      const oge = document.querySelector('.mb-panel-toggle[data-panel="' + ad + '"]');
      if (oge) oge.classList.toggle("pasif", !acikMi);
    }
    // Bolum popup modulu varsa taraf gizleme + popup gosterimi ona
    // devredilir (popup'a ayrilan bolumler panelde "yok" sayilir).
    if (typeof window.bolumPopupUygula === "function") {
      window.bolumPopupUygula(panelDurum);
    } else {
      // Sol taraf: 2 bolum de kapaliysa paneli tamamen gizle
      const solAcik = panelDurum.tespit || panelDurum.takip;
      document.body.classList.toggle("sol-panel-gizli", !solAcik);
      const solTut = document.getElementById("solTutamac");
      if (solTut) solTut.style.display = solAcik ? "" : "none";
      // Sag taraf: 3 bolum de kapaliysa paneli tamamen gizle
      // v2.4.33: panelDurum.dronlar kaldirildi (ayri DRONLAR bolumu yok)
      const sagAcik = panelDurum.kameralar || panelDurum.rotalar;
      document.body.classList.toggle("sag-panel-gizli", !sagAcik);
      const sagTut = document.getElementById("sagTutamac");
      if (sagTut) sagTut.style.display = sagAcik ? "" : "none";
    }
    // Harita yerlesimi degisti - Cesium canvas boyutunu tazele
    try { if (typeof viewer !== "undefined" && viewer) viewer.resize(); } catch(e){}
  }
  // Bolum popup modulunun kullandigi ortak API'ler
  window.panelGorunumDurum = function(){ return Object.assign({}, panelDurum); };
  window.bolumGorunumAyarla = function(ad, acik){
    if (!(ad in panelDurum)) return;
    panelDurum[ad] = !!acik;
    panelKaydet();
    panelUygula();
  };
  function panelKaydet(){
    try { localStorage.setItem("gcs_panel_gorunum", JSON.stringify(panelDurum)); } catch(e){}
  }
  document.querySelectorAll(".mb-panel-toggle").forEach(oge => {
    oge.addEventListener("click", (e) => {
      e.stopPropagation();
      const ad = oge.dataset.panel;
      if (!(ad in panelDurum)) return;
      panelDurum[ad] = !panelDurum[ad];
      panelKaydet();
      panelUygula();
      kapat();
    });
  });
  panelUygula();

  // =====================================================================
  // POPUP ACAN MENU OGELERINDE CHECK ISARETI (v2.3.1)
  // .mb-popup-toggle ogeleri: hedef popup ACIKSA tik gorunur.
  // - data-yuzen: yuzen panel 'yuzen-gizli' degilse acik
  // - data-popup-hedef: hedef eleman DOM'da var ve gorunurse acik
  // Menu her acildiginda / uzerine gelindiginde durum tazelenir.
  // =====================================================================
  function popupAcikMi(oge){
    const yz = oge.dataset.yuzen;
    if (yz){
      const p = document.getElementById(yz);
      return !!(p && !p.classList.contains("yuzen-gizli"));
    }
    const hedefId = oge.dataset.popupHedef;
    if (hedefId){
      const p = document.getElementById(hedefId);
      if (!p || !p.isConnected) return false;
      if (p.classList.contains("popup-gizli")) return false;
      const cs = getComputedStyle(p);
      return cs.display !== "none" && cs.visibility !== "hidden";
    }
    return false;
  }
  function popupTikleriGuncelle(){
    document.querySelectorAll(".mb-popup-toggle").forEach(oge => {
      oge.classList.toggle("pasif", !popupAcikMi(oge));
    });
  }
  window.popupTikleriGuncelle = popupTikleriGuncelle;
  items.forEach(it => {
    it.addEventListener("pointerenter", popupTikleriGuncelle);
    it.addEventListener("click", popupTikleriGuncelle);
  });
  popupTikleriGuncelle();

  // =====================================================================
  // ALT TUSU MENU NAVIGASYONU + HIZLANDIRICI HARFLER (Office tarzi)
  // - ALT'a bas-birak: menubar odak modu (hizlandirici harfler altciz.)
  // - ALT modunda / ALT+harf: data-hizli eslesen menuyu ac
  // - Menu acikken harf: eslesen ogeyi calistir
  // - Ok tuslari: sol/sag menuler arasi, yukari/asagi ogeler arasi
  // - Enter: odakli ogeyi calistir; ESC: cik
  // =====================================================================
  function harfNorm(s){
    if (!s) return "";
    return s.toLocaleLowerCase("tr").replace("\u0131","i"); // i/ı esle
  }
  // Hizlandirici harfleri etikette <u> ile isaretle (i18n her calistiginda
  // metin yenilenir; bu yuzden her cagrida yeniden sarilir)
  function hizlandiriciIsaretle(){
    // Menu etiketleri
    items.forEach(it => {
      const h = it.dataset.hizli; if (!h) return;
      const sp = it.querySelector(".mb-etiket"); if (!sp) return;
      altCiz(sp, h);
    });
    // Menu ogeleri
    menubar.querySelectorAll(".mb-oge[data-hizli]").forEach(oge => {
      const sp = oge.querySelector("span[data-i18n], span:last-child");
      if (sp) altCiz(sp, oge.dataset.hizli);
    });
  }
  function altCiz(span, harf){
    const metin = span.textContent;
    if (!metin) return;
    const hn = harfNorm(harf);
    let idx = -1;
    for (let i = 0; i < metin.length; i++){
      if (harfNorm(metin[i]) === hn){ idx = i; break; }
    }
    if (idx < 0){ span.innerHTML = ""; span.textContent = metin; return; }
    span.innerHTML = "";
    span.appendChild(document.createTextNode(metin.slice(0, idx)));
    const u = document.createElement("u");
    u.className = "mb-hizli";
    u.textContent = metin[idx];
    span.appendChild(u);
    span.appendChild(document.createTextNode(metin.slice(idx + 1)));
  }
  hizlandiriciIsaretle();

  let altModu = false;
  let odakOge = null; // acik dropdown icindeki odakli .mb-oge

  function altModuAyarla(acik){
    altModu = acik;
    menubar.classList.toggle("alt-aktif", acik);
    if (!acik){ odakTemizle(); }
  }
  function odakTemizle(){
    if (odakOge){ odakOge.classList.remove("odak"); odakOge = null; }
  }
  function odakVer(oge){
    odakTemizle();
    if (oge){ oge.classList.add("odak"); odakOge = oge; }
  }
  function acikOgeler(){
    if (!acikItem) return [];
    return [...acikItem.querySelectorAll(".mb-oge")].filter(o => o.offsetParent !== null);
  }
  function menuyuAcVeIsaretle(item){
    hizlandiriciIsaretle(); // i18n degismis olabilir
    ac(item);
    odakTemizle();
  }
  function ogeCalistir(oge){
    altModuAyarla(false);
    oge.click();
    // data-yuzen ogeleri arayuz.js dinleyicisi isler; menu kapatma da orada
    setTimeout(kapat, 0);
  }

  document.addEventListener("keydown", (e) => {
    // Girdi alanlarinda karisma
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;

    // ALT+harf: dogrudan menu ac (alt modu gerekmez)
    if (e.altKey && e.key.length === 1 && e.key !== " "){
      const hn = harfNorm(e.key);
      const item = items.find(it => harfNorm(it.dataset.hizli || "") === hn);
      if (item){
        e.preventDefault();
        altModuAyarla(true);
        menuyuAcVeIsaretle(item);
        return;
      }
    }

    // Yalniz ALT bas-birak toggle'i keyup'ta islenir; burada tekrarli ALT'i yut
    if (e.key === "Alt" && !e.repeat){ e.preventDefault(); return; }

    if (!altModu && !acikItem) return;

    if (e.key === "Escape"){
      altModuAyarla(false);
      kapat();
      return;
    }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight"){
      e.preventDefault();
      const gorunur = items.filter(it => it.offsetParent !== null);
      let i = acikItem ? gorunur.indexOf(acikItem) : -1;
      if (i < 0) i = 0;
      else i = (i + (e.key === "ArrowRight" ? 1 : -1) + gorunur.length) % gorunur.length;
      menuyuAcVeIsaretle(gorunur[i]);
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp"){
      if (!acikItem && altModu){
        // Alt modunda menu acilmadan ok: ilk menuyu ac
        const gorunur = items.filter(it => it.offsetParent !== null);
        if (gorunur.length) menuyuAcVeIsaretle(gorunur[0]);
      }
      const liste = acikOgeler();
      if (!liste.length) return;
      e.preventDefault();
      let i = odakOge ? liste.indexOf(odakOge) : -1;
      i = (i + (e.key === "ArrowDown" ? 1 : -1) + liste.length + (i < 0 && e.key === "ArrowUp" ? 1 : 0)) % liste.length;
      odakVer(liste[i]);
      return;
    }
    if (e.key === "Enter" && odakOge){
      e.preventDefault();
      ogeCalistir(odakOge);
      return;
    }
    // Harf hizlandiricilari
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey){
      const hn = harfNorm(e.key);
      if (acikItem){
        const oge = acikOgeler().find(o => harfNorm(o.dataset.hizli || "") === hn);
        if (oge){ e.preventDefault(); ogeCalistir(oge); return; }
      }
      if (altModu){
        const item = items.find(it => harfNorm(it.dataset.hizli || "") === hn);
        if (item){ e.preventDefault(); menuyuAcVeIsaretle(item); return; }
      }
    }
  });

  // ALT bas-birak: odak modunu ac/kapat (tarayici varsayilanini engelle)
  let altBasildi = false;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Alt") altBasildi = true;
    else altBasildi = false; // ALT+kombinasyon: bas-birak toggle olmasin
  }, true);
  document.addEventListener("keyup", (e) => {
    if (e.key !== "Alt") return;
    e.preventDefault();
    if (altBasildi){
      if (altModu || acikItem){ altModuAyarla(false); kapat(); }
      else altModuAyarla(true);
    }
    altBasildi = false;
  });
  // Fare ile menu acilirsa hizlandiricilari tazele
  items.forEach(it => {
    const et = it.querySelector(".mb-etiket");
    if (et) et.addEventListener("mouseenter", hizlandiriciIsaretle);
  });
})();

// =====================================================================
// EK MODUL v2.0.0 - Hakkinda surumu + ALT tusu menu navigasyonu
// =====================================================================
(function(){
  "use strict";
  function surumYaz(){
    const s = document.getElementById("hkSurum");
    if (s && typeof GCS_SURUM !== "undefined") s.textContent = GCS_SURUM;
  }
  surumYaz();
  document.addEventListener("DOMContentLoaded", surumYaz);

  const menubar = document.getElementById("menubar");
  if (!menubar) return;
  const items = [...menubar.querySelectorAll(".mb-item")];
  let altModu = false;
  let odakIdx = -1;
  let ogeIdx = -1;

  function harfIsaretle(el){
    const harf = (el.dataset.hizli || "").toLocaleLowerCase("tr");
    if (!harf) return;
    const hedef = el.classList.contains("mb-item")
      ? (el.querySelector(".mb-etiket span") || el.querySelector(".mb-etiket"))
      : (el.querySelector("span[data-i18n]") || el);
    if (!hedef || hedef.querySelector(".hz-harf")) return;
    const metin = hedef.textContent;
    const i = metin.toLocaleLowerCase("tr").indexOf(harf);
    if (i < 0) return;
    hedef.innerHTML = metin.slice(0, i) +
      '<span class="hz-harf">' + metin[i] + "</span>" + metin.slice(i + 1);
  }
  function tumHarfleriIsaretle(){
    menubar.querySelectorAll("[data-hizli]").forEach(harfIsaretle);
  }
  setTimeout(tumHarfleriIsaretle, 300);

  function acikMenu(){ return menubar.querySelector(".mb-item.acik"); }
  function menuKapatTum(){
    menubar.querySelectorAll(".mb-item.acik").forEach(m => m.classList.remove("acik"));
  }
  function odakTemizle(){
    menubar.querySelectorAll(".klavye-odak").forEach(e => e.classList.remove("klavye-odak"));
  }
  function altCik(){
    altModu = false; odakIdx = -1; ogeIdx = -1;
    document.body.classList.remove("alt-aktif");
    odakTemizle();
  }
  function menuyuOdakla(idx){
    odakIdx = ((idx % items.length) + items.length) % items.length;
    ogeIdx = -1;
    odakTemizle();
    menuKapatTum();
    items[odakIdx].classList.add("klavye-odak");
  }
  function menuyuAc(idx){
    menuyuOdakla(idx);
    items[odakIdx].classList.add("acik");
  }
  function acikOgeler(){
    const m = acikMenu();
    if (!m) return [];
    return [...m.querySelectorAll(".mb-oge")];
  }
  function ogeOdakla(delta){
    const ogeler = acikOgeler();
    if (!ogeler.length) return;
    ogeIdx = ((ogeIdx + delta) % ogeler.length + ogeler.length) % ogeler.length;
    odakTemizle();
    if (items[odakIdx]) items[odakIdx].classList.add("klavye-odak");
    ogeler[ogeIdx].classList.add("klavye-odak");
    ogeler[ogeIdx].scrollIntoView({ block: "nearest" });
  }

  document.addEventListener("keydown", (e) => {
    const t = document.activeElement;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
      if (e.key !== "Escape") return;
    }
    if (e.key === "Alt" && !e.repeat){
      e.preventDefault();
      if (altModu) { altCik(); menuKapatTum(); }
      else {
        altModu = true;
        document.body.classList.add("alt-aktif");
        if (odakIdx < 0) menuyuOdakla(0);
      }
      return;
    }
    if (e.altKey && e.key.length === 1){
      const h = e.key.toLocaleLowerCase("tr");
      const hedef = items.find(m => (m.dataset.hizli || "").toLocaleLowerCase("tr") === h);
      if (hedef){
        e.preventDefault();
        altModu = true;
        document.body.classList.add("alt-aktif");
        menuyuAc(items.indexOf(hedef));
        return;
      }
    }
    if (!altModu) return;
    switch (e.key){
      case "Escape": {
        const m = acikMenu();
        if (m) {
          menuKapatTum(); ogeIdx = -1; odakTemizle();
          if (items[odakIdx]) items[odakIdx].classList.add("klavye-odak");
        }
        else altCik();
        e.preventDefault();
        return;
      }
      case "ArrowLeft":  e.preventDefault(); acikMenu() ? menuyuAc(odakIdx - 1) : menuyuOdakla(odakIdx - 1); return;
      case "ArrowRight": e.preventDefault(); acikMenu() ? menuyuAc(odakIdx + 1) : menuyuOdakla(odakIdx + 1); return;
      case "ArrowDown":  e.preventDefault(); if (!acikMenu() && items[odakIdx]) items[odakIdx].classList.add("acik"); ogeOdakla(+1); return;
      case "ArrowUp":    e.preventDefault(); if (!acikMenu() && items[odakIdx]) items[odakIdx].classList.add("acik"); ogeOdakla(-1); return;
      case "Enter": {
        e.preventDefault();
        const ogeler = acikOgeler();
        if (acikMenu() && ogeIdx >= 0 && ogeler[ogeIdx]) { ogeler[ogeIdx].click(); altCik(); }
        else if (!acikMenu() && odakIdx >= 0 && items[odakIdx]) { items[odakIdx].classList.add("acik"); }
        return;
      }
      default: {
        if (e.key.length === 1 && acikMenu()){
          const h = e.key.toLocaleLowerCase("tr");
          const oge = acikOgeler().find(o => (o.dataset.hizli || "").toLocaleLowerCase("tr") === h);
          if (oge){ e.preventDefault(); oge.click(); altCik(); }
        }
      }
    }
  });
  document.addEventListener("mousedown", () => { if (altModu) altCik(); }, true);
})();
