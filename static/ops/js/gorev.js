// =================================================================
// GOKTUNGU - DRON ROTA GOREVI ("Rotayi Yukle")
// Dron toolbar'indaki Rotayi Yukle dugmesi -> rota secim popup'i ->
// rota izleme popup'i.
// v2.4.20: YUKLEME ve BASLATMA ayrildi.
//   ROTAYI YUKLE  -> gorevi yalnizca drona yukler (ilerleme cubugu)
//   ROTAYI BASLAT -> yuklenmis gorevi baslatir (ARM + AUTO + START)
// Backend: goktungu/gorev.py + sunucu.py WS komutlari
//   giden : {tip:"rota_tek_goster"|"gorev_yukle"|"gorev_baslat"|
//            "gorev_durdur"|"gorev_devam"|"gorev_iptal", ...}
//   gelen : telemetri.gorev_durum {sysid:{rota_id,rota_isim,asama,
//            toplam_nokta,wp_harita,toplam_oge,yuklenen_oge,yuzde}},
//           dronlar[i].mission_seq, gorev_yukle_sonuc,
//           gorev_baslat_sonuc
// =================================================================
(function(){
  const secPerde   = document.getElementById("gorevRotaPerde");
  const secListe   = document.getElementById("gorevRotaListe");
  const secYok     = document.getElementById("gorevRotaYok");
  const secDronAd  = document.getElementById("gorevRotaDronAd");
  const btnSecKapat= document.getElementById("btnGorevRotaKapat");
  const izPopup    = document.getElementById("gorevIzlemePopup");
  const izBaslik   = document.getElementById("gorevIzlemeBaslik");
  const izRozet    = document.getElementById("gorevDurumRozet");
  const izToplam   = document.getElementById("gorevToplamNokta");
  const izMevcut   = document.getElementById("gorevMevcutNokta");
  const izMesafe   = document.getElementById("gorevMesafe");
  const izSure     = document.getElementById("gorevSure");
  const btnYukle   = document.getElementById("btnGorevYukle");
  const btnBaslat  = document.getElementById("btnGorevBaslat");
  const ykSatir    = document.getElementById("gorevYuklemeSatir");
  const ykCubuk    = document.getElementById("gorevYuklemeCubuk");
  const ykYuzde    = document.getElementById("gorevYuklemeYuzde");
  const ykEtiket   = document.getElementById("gorevYuklemeEtiket");
  const ykAlt      = document.getElementById("gorevYuklemeAlt");
  // v2.4.41: GOREV TAMAMLANMA (ucus ilerlemesi) cubugu
  const ucSatir    = document.getElementById("gorevUcusSatir");
  const ucCubuk    = document.getElementById("gorevUcusCubuk");
  const ucYuzde    = document.getElementById("gorevUcusYuzde");
  const ucEtiket   = document.getElementById("gorevUcusEtiket");
  const ucAlt      = document.getElementById("gorevUcusAlt");
  const btnDurdur  = document.getElementById("btnGorevDurdur");
  const btnDevam   = document.getElementById("btnGorevDevam");
  const btnIptal   = document.getElementById("btnGorevIptal");
  const btnIzKapat = document.getElementById("btnGorevIzlemeKapat");
  // v2.4.35: durdurma davranisi + surdurme
  const ddAyar     = document.getElementById("gorevDurdurmaAyar");
  const ddKilit    = document.getElementById("gorevDurdurmaKilit");
  const sdSatir    = document.getElementById("gorevSurdurSatir");
  const sdMetin    = document.getElementById("gorevSurdurMetin");
  const btnSurdur  = document.getElementById("btnGorevSurdur");
  if (!secPerde || !izPopup) return;

  function t(){ return (typeof D === "function") ? D() : {}; }
  function wsGonder(m){
    if (typeof ws !== "undefined" && ws && ws.readyState === 1)
      ws.send(JSON.stringify(m));
  }

  // --- Durum ---
  let aktifSysid = null;    // izleme popup'inin bagli oldugu dron
  let aktifRota  = null;    // secilen rota nesnesi (kopya)
  let sonGorevDurum = {};   // telemetriden gelen gorev_durum paketi
  let sonMissionSeq = {};   // sysid -> mission_seq (telemetriden)
  // v2.4.145: Görev başlangıcında araç türünü güvenilir telemetri
  // paketinden okuruz; performans testi yalnız sabit kanatta görünür.
  let sonDronlar = {};      // sysid -> son telemetri özeti
  // v2.4.35: "tamamlandi" asamasi eklendi
  // hazir | yukleniyor | yuklendi | gorevde | duraklatildi |
  // tamamlandi | hata | iptal
  let yerelAsama = "hazir";
  // v2.4.35: sunucudan gelen surdurulebilir gorev paketi
  let sonSurdurulebilir = {};

  // v2.4.35: gorev durdurulunca ne yapilacagi. Gorev YUKLENIRKEN
  // sunucuya gonderilir ve gorev boyunca sunucu tarafinda saklanir.
  function durdurmaDavranisi(){
    const s = izPopup.querySelector(
      'input[name="gorevDurdurmaDavranisi"]:checked');
    return (s && s.value === "basa_don") ? "basa_don" : "bekle";
  }

  function durdurmaDavranisiUygula(deger){
    const s = izPopup.querySelector(
      'input[name="gorevDurdurmaDavranisi"][value="' +
      (deger === "basa_don" ? "basa_don" : "bekle") + '"]');
    if (s) s.checked = true;
  }

  // ---------------------------------------------------------------
  // Yardimcilar: mesafe / sure
  // ---------------------------------------------------------------
  function mesafeMetni(m){
    if (m === undefined || m === null) return "-";
    return (m >= 1000) ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";
  }

  function rotaSuresi(r){
    // Segment bazli: segment mesafesi / hedef noktanin hizi (m/s)
    const n = r.noktalar || [];
    if (n.length < 2) return 0;
    const R = 6371000;
    let sure = 0;
    for (let i = 1; i < n.length; i++){
      const a = n[i-1], b = n[i];
      const dLat = (b.lat - a.lat) * Math.PI / 180;
      const dLon = (b.lon - a.lon) * Math.PI / 180;
      const s = Math.sin(dLat/2)**2 +
        Math.cos(a.lat*Math.PI/180) * Math.cos(b.lat*Math.PI/180) *
        Math.sin(dLon/2)**2;
      const mesafe = 2 * R * Math.asin(Math.sqrt(s));
      const hiz = Math.max(0.5, parseFloat(b.hiz) || parseFloat(r.hiz_varsayilan) || 5);
      sure += mesafe / hiz;
    }
    return sure;
  }

  function sureMetni(sn){
    if (!sn || sn <= 0) return "-";
    sn = Math.round(sn);
    const dk = Math.floor(sn / 60), s = sn % 60;
    return (dk > 0 ? dk + " dk " : "") + s + " sn";
  }

  // ---------------------------------------------------------------
  // ROTA SECIM POPUP'I
  // ---------------------------------------------------------------
  function secimAc(sysid){
    aktifSysid = sysid;
    const dd = (typeof sonVeri !== "undefined") ? sonVeri[sysid] : null;
    secDronAd.textContent = dd ? dd.isim : ("DRON-" + sysid);
    secimListeCiz();
    secPerde.classList.remove("popup-gizli");
    // v2.4.21: hedef arac belli oldu -> sabit kanat donus dairelerini
    // parametrelere gore yeniden ciz
    if (typeof window.rotaCizimTazele === "function")
      window.rotaCizimTazele();
  }

  function secimListeCiz(){
    const rotalar = (typeof window.rotaVerileri === "function")
      ? window.rotaVerileri() : [];
    secListe.innerHTML = "";
    secYok.style.display = rotalar.length ? "none" : "";
    rotalar.forEach(r => {
      const satir = document.createElement("div");
      satir.className = "gorev-rota-satir";
      const ikon = document.createElement("i");
      ikon.className = "fa-solid fa-route";
      const ad = document.createElement("span");
      ad.className = "grs-ad"; ad.textContent = r.isim; ad.title = r.isim;
      const bilgi = document.createElement("span");
      bilgi.className = "grs-bilgi";
      bilgi.textContent = mesafeMetni(r.mesafe_m) + " · " +
        sureMetni(rotaSuresi(r));
      satir.appendChild(ikon); satir.appendChild(ad);
      satir.appendChild(bilgi);
      satir.addEventListener("click", () => rotaSecildi(r));
      secListe.appendChild(satir);
    });
  }

  function secimKapat(){ secPerde.classList.add("popup-gizli"); }
  btnSecKapat.addEventListener("click", secimKapat);
  secPerde.addEventListener("click", (e) => {
    if (e.target === secPerde) secimKapat();
  });

  // ---------------------------------------------------------------
  // ROTA SECILDI -> haritada tek goster + izleme popup'i
  // ---------------------------------------------------------------
  function rotaSecildi(r){
    aktifRota = r;
    yerelAsama = "hazir";
    // Diger tum rotalari gizle, yalniz bunu goster
    wsGonder({tip: "rota_tek_goster", id: r.id});
    // Haritayi rotaya odakla
    if (typeof viewer !== "undefined" && viewer && r.noktalar &&
        r.noktalar.length){
      let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
      r.noktalar.forEach(n => {
        minLat = Math.min(minLat, n.lat); maxLat = Math.max(maxLat, n.lat);
        minLon = Math.min(minLon, n.lon); maxLon = Math.max(maxLon, n.lon);
      });
      const pay = 0.004;
      try {
        viewer.camera.flyTo({
          destination: Cesium.Rectangle.fromDegrees(
            minLon - pay, minLat - pay, maxLon + pay, maxLat + pay),
          duration: 1.2,
        });
      } catch(_){}
    }
    secimKapat();
    izlemeAc();
  }

  // ---------------------------------------------------------------
  // IZLEME POPUP'I
  // ---------------------------------------------------------------
  function izlemeAc(){
    izlemeTazele();
    izPopup.classList.remove("popup-gizli");
  }

  function izlemeKapat(){
    izPopup.classList.add("popup-gizli");
    aktifRota = null; aktifSysid = null; yerelAsama = "hazir";
  }

  // v2.4.20: yukleme ilerleme cubugu
  function ilerlemeTazele(asama){
    if (!ykSatir) return;
    const dil = t();
    const g = sonGorevDurum[String(aktifSysid)];
    const ayniRota = !!(g && aktifRota && g.rota_id === aktifRota.id);
    if (asama !== "yukleniyor" && asama !== "yuklendi"){
      ykSatir.classList.add("popup-gizli");
      return;
    }
    ykSatir.classList.remove("popup-gizli");
    let yuzde = 0, yuklenen = 0, toplam = 0;
    if (ayniRota){
      yuzde    = (typeof g.yuzde === "number") ? g.yuzde : 0;
      yuklenen = g.yuklenen_oge || 0;
      toplam   = g.toplam_oge || 0;
    }
    if (asama === "yuklendi") yuzde = 100;
    ykCubuk.style.width = Math.max(0, Math.min(100, yuzde)) + "%";
    ykCubuk.classList.toggle("tamam", asama === "yuklendi");
    ykYuzde.textContent = Math.round(yuzde) + "%";
    ykEtiket.textContent = (asama === "yuklendi")
      ? (dil.gorevYuklemeTamam || "GÖREV DRONA YÜKLENDİ")
      : (dil.gorevYuklemeEtiket || "GÖREV YÜKLENİYOR");
    if (toplam > 0){
      const sablon = dil.gorevYuklemeOge || "{yuklenen} / {toplam} görev ögesi";
      ykAlt.textContent = sablon
        .replace("{yuklenen}", (asama === "yuklendi") ? toplam : yuklenen)
        .replace("{toplam}", toplam);
    } else {
      ykAlt.textContent = dil.gorevYuklemeHazirlik ||
        "Görev ögeleri hazırlanıyor...";
    }
  }

  // v2.4.41: GOREV TAMAMLANMA (ucus) ilerleme cubugu.
  // Yukleme cubugundan AYRI: bu, gorevin ne kadarinin UCULDUGUNU
  // gosterir. Sunucu `gorev_yuzde` alanini uculan en yuksek WP'ye gore
  // uretir (gorev.py::durum_paketi) ve gorev bitmeden 100 gostermez.
  function ucusIlerlemeTazele(asama){
    if (!ucSatir) return;
    const dil = t();
    const g = sonGorevDurum[String(aktifSysid)];
    const ayniRota = !!(g && aktifRota && g.rota_id === aktifRota.id);
    // Yalniz gorev fiilen ucarken/duraklatilmisken veya tamamlaninca
    // gosterilir. "yuklendi" asamasinda henuz ucus yok -> gizli.
    const gorunur = (asama === "gorevde" || asama === "duraklatildi" ||
                     asama === "tamamlandi");
    if (!gorunur){
      ucSatir.classList.add("popup-gizli");
      return;
    }
    ucSatir.classList.remove("popup-gizli");
    let yuzde = 0;
    if (ayniRota && typeof g.gorev_yuzde === "number")
      yuzde = g.gorev_yuzde;
    if (asama === "tamamlandi") yuzde = 100;
    yuzde = Math.max(0, Math.min(100, yuzde));
    ucCubuk.style.width = yuzde + "%";
    ucCubuk.classList.toggle("tamam", asama === "tamamlandi");
    ucYuzde.textContent = Math.round(yuzde) + "%";
    ucEtiket.textContent = (asama === "tamamlandi")
      ? (dil.gorevUcusTamam || "GÖREV TAMAMLANDI")
      : (dil.gorevUcusEtiket || "GÖREV TAMAMLANMA");
    // Alt metin: uculan nokta / toplam nokta.
    // en_yuksek_seq bir MISSION ogesi indeksidir; kullanicinin gordugu
    // NOKTA numarasina wp_harita ile cevrilir (takeoff/hiz ogeleri WP
    // degildir, bu yuzden dogrudan sayi olarak gosterilemez).
    const toplamNokta = (aktifRota && (aktifRota.noktalar || []).length) ||
      (ayniRota ? (g.toplam_nokta || 0) : 0);
    let uculanNokta = null;
    if (ayniRota){
      const seq = Number(g.en_yuksek_seq);
      const wp = g.wp_harita || {};
      if (isFinite(seq) && seq > 0){
        if (wp[String(seq)] !== undefined) uculanNokta = wp[String(seq)];
        else {
          // seq bir WP degil: seq'ten KUCUK-ESIT en buyuk WP anahtari
          let enBuyuk = null;
          Object.keys(wp).forEach(s => {
            const si = parseInt(s, 10);
            if (si <= seq && (enBuyuk === null || si > enBuyuk)) enBuyuk = si;
          });
          if (enBuyuk !== null) uculanNokta = wp[String(enBuyuk)];
        }
      }
    }
    if (asama === "tamamlandi" && toplamNokta) uculanNokta = toplamNokta;
    if (uculanNokta !== null && uculanNokta !== undefined && toplamNokta){
      const sablon = dil.gorevUcusNokta ||
        "{nokta} / {toplam} nokta uçuldu";
      ucAlt.textContent = sablon
        .replace("{nokta}", uculanNokta)
        .replace("{toplam}", toplamNokta);
    } else {
      ucAlt.textContent = dil.gorevUcusBekleniyor ||
        "İlk noktaya gidiliyor...";
    }
  }
  btnIzKapat.addEventListener("click", izlemeKapat);

  function asamaBul(){
    // Sunucu durumu varsa ve bu rotaya aitse onu esas al
    const g = sonGorevDurum[String(aktifSysid)];
    if (g && aktifRota && g.rota_id === aktifRota.id) return g.asama;
    return yerelAsama;
  }

  function mevcutNokta(){
    const g = sonGorevDurum[String(aktifSysid)];
    if (!g || !aktifRota || g.rota_id !== aktifRota.id) return "-";
    const seq = sonMissionSeq[aktifSysid];
    if (seq === undefined || seq < 0) return "-";
    const wp = g.wp_harita || {};
    // seq bir WP ise dogrudan; degilse (takeoff/hiz) bir sonraki WP
    if (wp[String(seq)] !== undefined) return wp[String(seq)];
    let enYakin = null;
    Object.keys(wp).forEach(s => {
      const si = parseInt(s, 10);
      if (si >= seq && (enYakin === null || si < enYakin)) enYakin = si;
    });
    return (enYakin !== null) ? wp[String(enYakin)] : "-";
  }

  function izlemeTazele(){
    if (!aktifRota || izPopup.classList.contains("popup-gizli")) return;
    const dil = t();
    // v2.4.41 DUZELTME: `g` bu kapsamda TANIMSIZDI (v2.4.35'ten beri).
    // Asagidaki durdurma-davranisi senkronu her tazelemede
    // "ReferenceError: g is not defined" atiyordu; ws.js cagriyi guvenli
    // sarmalayiciyla yaptigi icin hata yutuluyor ve fonksiyonun GERI
    // KALANI hic calismiyordu. Sonuc: surdurmeTazele() ve
    // ilerlemeTazele() hic cagrilmiyordu -> "kaldigi yerden devam et"
    // satiri gorunmuyor ve yukleme cubugu guncellenmiyordu.
    const g = sonGorevDurum[String(aktifSysid)];
    const dd = (typeof sonVeri !== "undefined") ? sonVeri[aktifSysid] : null;
    const profil = (g && g.performans_test) || null;
    const sitlDalisEtiketi = (profil &&
      profil.tur === "sitl_dalis_simulasyonu")
      ? " · SITL DALIŞ " + Number(profil.aci_derece || 0).toFixed(1) +
        "° / " + Number(profil.hedef_hiz_ms || 0).toFixed(1) + " m/s"
      : "";
    izBaslik.textContent = (dd ? dd.isim : "DRON-" + aktifSysid) +
      " → " + aktifRota.isim + sitlDalisEtiketi;
    izToplam.textContent = (aktifRota.noktalar || []).length;
    izMevcut.textContent = mevcutNokta();
    izMesafe.textContent = mesafeMetni(aktifRota.mesafe_m);
    izSure.textContent = sureMetni(rotaSuresi(aktifRota));
    // Asama rozeti + dugme durumlari
    const asama = asamaBul();
    const rozetler = {
      hazir:        [dil.gorevDurumBekliyor || "HAZIR", "bekliyor"],
      yukleniyor:   [dil.gorevDurumYukleniyor || "YÜKLENİYOR...", "yukleniyor"],
      yuklendi:     [dil.gorevDurumYuklendi || "YÜKLENDİ", "yuklendi"],
      gorevde:      [dil.gorevDurumGorevde || "GÖREVDE", "gorevde"],
      duraklatildi: [dil.gorevDurumDuraklatildi || "DURAKLATILDI", "duraklat"],
      // v2.4.35: gorev son noktaya varinca
      tamamlandi:   [dil.gorevDurumTamamlandi || "GÖREV TAMAMLANDI",
                     "tamamlandi"],
      hata:         [dil.gorevDurumHata || "HATA", "hata"],
      iptal:        [dil.gorevDurumIptal || "İPTAL EDİLDİ", "iptal"],
    };
    const [metin, sinif] = rozetler[asama] || rozetler.hazir;
    izRozet.textContent = metin;
    izRozet.className = "gorev-rozet " + sinif;
    // v2.4.20: ROTAYI YUKLE - yalnizca yukleme yapilmiyorken ve gorev
    // ucmuyorken aktif (yeniden yukleme icin 'yuklendi' de aktif kalir)
    if (btnYukle)
      btnYukle.disabled = (asama === "yukleniyor" || asama === "gorevde" ||
                           asama === "duraklatildi");
    // ROTAYI BASLAT - yalnizca gorev drona YUKLENDIYSE aktif
    btnBaslat.disabled = (asama !== "yuklendi");
    // Sunucu 'hata' bildirdiyse yerel asamayi sifirla ki tekrar denenebilsin
    if (asama === "hata") yerelAsama = "hazir";
    btnDurdur.disabled = (asama !== "gorevde");
    btnDevam.disabled  = (asama !== "duraklatildi");
    // v2.4.18: GOREV IPTAL - gorev yuklenirken/yuklendiyse/ucarken aktif
    if (btnIptal)
      btnIptal.disabled = !(asama === "yukleniyor" || asama === "yuklendi" ||
                            asama === "gorevde" || asama === "duraklatildi");
    // v2.4.35: durdurma davranisi yalnizca gorev henuz yuklenmemisken
    // secilebilir. Gorev drondayken degistirmek arayuz ile sunucudaki
    // kaydi ayirir: kullanici RTL sanir, sunucu BRAKE uygular.
    if (ddAyar){
      const kilitli = (asama === "yukleniyor" || asama === "yuklendi" ||
                       asama === "gorevde" || asama === "duraklatildi");
      ddAyar.classList.toggle("kilitli", kilitli);
      izPopup.querySelectorAll('input[name="gorevDurdurmaDavranisi"]')
        .forEach(r => { r.disabled = kilitli; });
      if (ddKilit) ddKilit.classList.toggle("popup-gizli", !kilitli);
      // Sunucudaki gecerli deger arayuze yansisin (yeniden baglanma,
      // sayfa yenileme veya baska bir pilotun yuklemesi sonrasi)
      if (g && aktifRota && g.rota_id === aktifRota.id &&
          g.durdurma_davranisi)
        durdurmaDavranisiUygula(g.durdurma_davranisi);
    }
    surdurmeTazele(asama);
    ilerlemeTazele(asama);
    // v2.4.41: gorev tamamlanma (ucus) cubugu
    ucusIlerlemeTazele(asama);
  }

  // v2.4.35: yarim kalmis gorev onerisi. Sunucu yalnizca dron
  // cevrimici VE aktif gorev kaydi yokken onerir; batarya degisimi
  // sonrasi bu satir gorunur.
  function surdurmeTazele(asama){
    if (!sdSatir) return;
    const s = sonSurdurulebilir[String(aktifSysid)];
    const uygun = !!(s && asama !== "gorevde" && asama !== "yukleniyor" &&
                     asama !== "duraklatildi");
    sdSatir.classList.toggle("popup-gizli", !uygun);
    if (!uygun || !sdMetin) return;
    const dil = t();
    const sablon = dil.gorevSurdurBilgi ||
      "{rota}: {nokta}. noktada kaldı — kaldığı yerden sürdürülebilir";
    sdMetin.textContent = sablon
      .replace("{rota}", s.rota_isim || ("#" + s.rota_id))
      .replace("{nokta}", (s.nokta === undefined || s.nokta === null)
        ? "?" : s.nokta);
  }

  // v2.4.20: ROTAYI YUKLE - gorevi YALNIZCA drona yukler, ucus baslamaz
  if (btnYukle) btnYukle.addEventListener("click", () => {
    if (!aktifRota || aktifSysid === null) return;
    const dil = t();
    const nokta = (aktifRota.noktalar || []).length;
    const soru = (typeof onayMetni === "function")
      ? onayMetni("onayGorevYukle", {
          dron: aktifSysid,
          rota: aktifRota.isim || aktifRota.id,
          nokta: nokta
        })
      : (dil.onayGorevYukle || "Rota drona yuklensin mi?");
    const uygula = () => {
      if (!aktifRota || aktifSysid === null) return;
      yerelAsama = "yukleniyor";
      // Onceki durumu temizle ki ilerleme sifirdan baslasin
      delete sonGorevDurum[String(aktifSysid)];
      if (ykCubuk){ ykCubuk.style.width = "0%";
        ykCubuk.classList.remove("tamam"); }
      wsGonder({tip: "gorev_yukle", sysid: aktifSysid,
                rota_id: aktifRota.id,
                // v2.4.35: gorev durdurulunca ne yapilacagi
                durdurma_davranisi: durdurmaDavranisi()});
      izlemeTazele();
    };
    if (typeof onayIste === "function") onayIste(soru, uygula);
    else uygula();
  });

  function sabitKanatMi(sysid){
    const d = sonDronlar[String(sysid)] || {};
    return Number(d.arac_tipi || 0) === 1; // MAV_TYPE_FIXED_WING
  }

  function sanalSabitKanatMi(sysid){
    // UI yalnız canlı telemetrisi gelen ve sanal bağlantı kaydıyla eşleşen
    // sabit kanada senaryo sorar. Bu yalnız görünürlük kolaylığıdır; kesin
    // süreç/type denetimi her zaman backend'deki SitlYoneticisi'ndedir.
    const d = sonDronlar[String(sysid)] || {};
    if (Number(d.arac_tipi || 0) !== 1 || !d.cevrimici || !d.baglanti_id)
      return false;
    const kayitlar = (typeof bagKayitlar !== "undefined" &&
      Array.isArray(bagKayitlar)) ? bagKayitlar : [];
    return kayitlar.some(b => String(b.id) === String(d.baglanti_id) &&
      String(b.tur || "") === "sanal");
  }

  function sitlDalisSor(sysid, devam){
    if (!sanalSabitKanatMi(sysid)) { devam(null); return; }
    const d = t();
    const etkin = window.confirm(d.sitlDalisSor ||
      "Bu yalnız sanal sabit kanat görevi için dalış simülasyonu çalıştırılsın mı?\n\n" +
      "Senaryo yalnız aktif ArduPlane SITL sürecine yüklenir; gerçek araçta görünmez ve uygulanmaz.");
    if (!etkin) { devam(null); return; }
    const aciHam = window.prompt(d.sitlDalisAci ||
      "Dalış açısı (derece, 10 ile 35):", "15");
    if (aciHam === null) { devam(null); return; }
    const hizHam = window.prompt(d.sitlDalisHiz ||
      "Hedef hız (m/s, 10 ile 25):", "15");
    if (hizHam === null) { devam(null); return; }
    const baslangicHam = window.prompt(d.sitlDalisBaslangicIrtifa ||
      "Dalış başlangıç irtifası (m, 40 ile 120):", "80");
    if (baslangicHam === null) { devam(null); return; }
    const cikisHam = window.prompt(d.sitlDalisCikisIrtifa ||
      "Çıkış irtifası (m, 15 ile 80):", "30");
    if (cikisHam === null) { devam(null); return; }
    const aci = Number(aciHam), hiz = Number(hizHam);
    const baslangic = Number(baslangicHam), cikis = Number(cikisHam);
    if (!Number.isFinite(aci) || !Number.isFinite(hiz) ||
        !Number.isFinite(baslangic) || !Number.isFinite(cikis) ||
        aci < 10 || aci > 35 || hiz < 10 || hiz > 25 ||
        baslangic < 40 || baslangic > 120 || cikis < 15 || cikis > 80 ||
        baslangic < cikis + 20){
      window.alert(d.sitlDalisGecersiz ||
        "Geçersiz SITL dalış değeri. Açı 10…35°, hız 10…25 m/s, başlangıç 40…120 m, çıkış 15…80 m ve irtifa farkı en az 20 m olmalıdır.");
      devam(null); return;
    }
    const onay = window.confirm(d.sitlDalisSonOnay ||
      "SITL dalış simülasyonu başlatılsın mı?\n\n" +
      "Plan: " + aci.toFixed(1) + "° / " + hiz.toFixed(1) + " m/s\n" +
      "İrtifa: " + baslangic.toFixed(1) + " m → " + cikis.toFixed(1) + " m\n\n" +
      "Sadece aktif sanal ArduPlane'de waypoint ve hız profili yüklenir. Telemetri 1 Hz kaydedilir; gerçek araçta bu komut reddedilir.");
    devam(onay ? {etkin: true, aci_derece: aci, hedef_hiz_ms: hiz,
      baslangic_irtifa_m: baslangic, cikis_irtifa_m: cikis} : null);
  }

  function performansTestiSor(sysid, devam){
    // Test, araç kontrolcüsüne gaz/pitch/emniyet komutu GONDERMEZ.
    // Yalnız planlanan açı/hızı gerçek telemetri kaydına iliştirir.
    if (!sabitKanatMi(sysid)) { devam(null); return; }
    const d = t();
    const etkin = window.confirm(d.performansTestiSor ||
      "Bu sabit kanat görevi için terminal yaklaşım performans kaydı oluşturulsun mu?\n\n" +
      "Bu seçenek uçuş komutu, gaz veya güvenlik parametresi değiştirmez; yalnız telemetri analizi kaydeder.");
    if (!etkin) { devam(null); return; }
    const aciHam = window.prompt(d.performansTestiAci ||
      "Planlanan terminal yaklaşım açısı (derece, -25 ile -5):", "-10");
    if (aciHam === null) { devam(null); return; }
    const hizHam = window.prompt(d.performansTestiHiz ||
      "Planlanan hedef hava hızı (m/s, 8 ile 30):", "15");
    if (hizHam === null) { devam(null); return; }
    const aci = Number(aciHam), hiz = Number(hizHam);
    if (!Number.isFinite(aci) || !Number.isFinite(hiz) ||
        aci < -25 || aci > -5 || hiz < 8 || hiz > 30){
      window.alert(d.performansTestiGecersiz ||
        "Geçersiz performans testi değeri. Açı -25…-5°, hız 8…30 m/s olmalıdır.");
      devam(null); return;
    }
    const onay = window.confirm(d.performansTestiSonOnay ||
      "Performans testi kaydı başlatılsın mı?\n\n" +
      "Plan: " + aci.toFixed(1) + "° / " + hiz.toFixed(1) + " m/s\n" +
      "Telemetri 1 Hz kaydedilir. Uçuş kontrol komutları ve güvenlik sınırları değiştirilmez.");
    devam(onay ? {etkin: true, aci_derece: aci, hedef_hiz_ms: hiz} : null);
  }

  // v2.4.20: ROTAYI BASLAT - drona yuklenmis gorevi baslatir
  btnBaslat.addEventListener("click", () => {
    if (!aktifRota || aktifSysid === null) return;
    // Takeoff irtifasi = rotanin ilk noktasinin irtifasi (backend ile ayni kural, min 2 m)
    const ilkNokta = (aktifRota.noktalar && aktifRota.noktalar[0]) || null;
    const tkIrtifa = Math.max(2, (ilkNokta && typeof ilkNokta.irtifa === "number") ? ilkNokta.irtifa : 2);
    // v2.4.252 (IS150): eski SITL dalis / performans testi deneme sorularinin
    // (sitlDalisSor / performansTestiSor) tetiklenmesi kaldirildi. Gorev tek
    // onayla dogrudan baslar; arta kalan sorular kullaniciyi yordu.
    onayIste(onayMetni("onayGorevBaslat", {rota: aktifRota.isim || aktifRota.id, irtifa: tkIrtifa}), () => {
      if (!aktifRota || aktifSysid === null) return;
      yerelAsama = "gorevde";
      wsGonder({tip: "gorev_baslat", sysid: aktifSysid});
      izlemeTazele();
    });
  });

  btnDurdur.addEventListener("click", () => {
    if (aktifSysid === null) return;
    yerelAsama = "duraklatildi";
    wsGonder({tip: "gorev_durdur", sysid: aktifSysid});
    izlemeTazele();
  });

  btnDevam.addEventListener("click", () => {
    if (aktifSysid === null) return;
    yerelAsama = "gorevde";
    wsGonder({tip: "gorev_devam", sysid: aktifSysid});
    izlemeTazele();
  });

  // v2.4.35: KALDIGI YERDEN DEVAM ET - batarya degisimi sonrasi yarim
  // kalmis gorevi surdurur. Arac HAVADA AUTO moduna alinacagi icin
  // onay istenir.
  if (btnSurdur) btnSurdur.addEventListener("click", () => {
    if (aktifSysid === null) return;
    const s = sonSurdurulebilir[String(aktifSysid)];
    if (!s) return;
    const dil = t();
    const soru = (typeof onayMetni === "function")
      ? onayMetni("onayGorevSurdur", {
          dron: aktifSysid,
          rota: s.rota_isim || ("#" + s.rota_id),
          nokta: (s.nokta === undefined || s.nokta === null) ? "?" : s.nokta
        })
      : (dil.onayGorevSurdur ||
         "Görev kaldığı noktadan sürdürülsün mü?");
    const uygula = () => {
      if (aktifSysid === null) return;
      yerelAsama = "gorevde";
      wsGonder({tip: "gorev_surdur", sysid: aktifSysid});
      izlemeTazele();
    };
    if (typeof onayIste === "function") onayIste(soru, uygula);
    else uygula();
  });

  // v2.4.18: GOREV IPTAL - gorevi tamamen sonlandirir (dron BRAKE/LOITER
  // moduna alinir, drondaki mission listesi temizlenir)
  if (btnIptal) btnIptal.addEventListener("click", () => {
    if (aktifSysid === null) return;
    const dil = t();
    const soru = (typeof onayMetni === "function")
      ? onayMetni("onayGorevIptal", {
          dron: aktifSysid,
          rota: aktifRota ? (aktifRota.isim || aktifRota.id) : "-"
        })
      : (dil.onayGorevIptal || "Gorev iptal edilsin mi?");
    const uygula = () => {
      if (aktifSysid === null) return;
      wsGonder({tip: "gorev_iptal", sysid: aktifSysid});
      yerelAsama = "hazir";
      // Sunucu durumunu da temizle ki rozet aninda HAZIR'a donsun
      delete sonGorevDurum[String(aktifSysid)];
      izlemeTazele();
    };
    if (typeof onayIste === "function") onayIste(soru, uygula);
    else uygula();
  });

  // ---------------------------------------------------------------
  // DISA ACIK API
  // ---------------------------------------------------------------
  // Dron toolbar'indan cagrilir (dronlar.js)
  window.gorevRotaSecimAc = secimAc;
  // v2.4.21: harita rota cizimi (donus dairesi) hedef araci bilmek ister
  window.gorevAktifSysid = function(){ return aktifSysid; };

  // v2.4.35: harita rota cizimi (rotalar.js) hangi rotanin ucusta
  // oldugunu bilmek ister. Gorev asamasi "gorevde"/"duraklatildi" olan
  // rota haritada silik cizilir.
  window.gorevDurumPaketi = function(){ return sonGorevDurum; };

  // v2.4.35: gorev asamasi degistiginde harita cizimini tazele.
  // Her telemetri paketinde yeniden cizmek pahalidir (rotaCiz her
  // cagrida tum entity'leri silip kurar); yalniz asama gercekten
  // degistiginde tetiklenir.
  let sonAsamaImzasi = "";
  function haritaCizimGerekliMi(){
    const parcalar = [];
    Object.keys(sonGorevDurum).sort().forEach(sysid => {
      const g = sonGorevDurum[sysid];
      if (g) parcalar.push(sysid + ":" + g.rota_id + ":" + g.asama);
    });
    const imza = parcalar.join("|");
    if (imza === sonAsamaImzasi) return false;
    sonAsamaImzasi = imza;
    return true;
  }

  // ---------------------------------------------------------------
  // v2.4.41: IZLEME PANELINI GERI AC
  // Pilot gorevi yukledikten sonra paneli kapatabilir. Islemler
  // panelindeki "Gorev Izle" ogesi ve kumandadan AUTO'ya gecis bu
  // fonksiyonu kullanir.
  // ---------------------------------------------------------------
  function aktifGorevRotasi(sysid){
    const g = sonGorevDurum[String(sysid)];
    if (!g) return null;
    const rotalar = (typeof window.rotaVerileri === "function")
      ? window.rotaVerileri() : [];
    const bulunan = rotalar.find(r => r.id === g.rota_id);
    if (bulunan) return bulunan;
    // Rota listesi henuz gelmediyse (ya da rota silindiyse) vekil nesne:
    // izleme paneli rota adi/nokta sayisi icin sunucu paketine dusebilir.
    // `noktalar` BOS kalir; toplam nokta sunucunun toplam_nokta alanindan
    // okunur (ucusIlerlemeTazele bunu zaten dikkate alir).
    return {id: g.rota_id, isim: g.rota_isim || ("#" + g.rota_id),
            noktalar: [], mesafe_m: null, _vekil: true};
  }

  function izlemeGeriAc(sysid){
    if (sysid === undefined || sysid === null) return false;
    const r = aktifGorevRotasi(sysid);
    if (!r) return false;
    aktifSysid = Number(sysid);
    aktifRota = r;
    const g = sonGorevDurum[String(sysid)];
    yerelAsama = (g && g.asama) ? g.asama : "hazir";
    izlemeAc();
    return true;
  }

  // v2.4.41: Islemler paneli bu ogeyi yalniz izlenecek bir gorev varsa
  // gostersin diye sorar.
  function izlenebilirMi(sysid){
    return !!sonGorevDurum[String(sysid)];
  }

  window.gorevIzlemeGeriAc = izlemeGeriAc;
  window.gorevIzlenebilirMi = izlenebilirMi;

  // v2.4.41: kumandadan AUTO moduna gecis tespiti.
  // GECIS KENARI kullanilir (seviye degil): mod AUTO OLMAYAN bir
  // degerden AUTO'ya dondugu AN bir kez tetiklenir. Seviye kullanmak
  // ("mod AUTO ise ac") paneli kapatilamaz hale getirirdi; her telemetri
  // paketinde yeniden acilirdi.
  let sonMod = {};
  function autoGecisDenetle(dronlar){
    (dronlar || []).forEach(d => {
      const sysid = d.sysid;
      const mod = String(d.mod || "").toUpperCase();
      const onceki = sonMod[sysid];
      sonMod[sysid] = mod;
      if (onceki === undefined) return;      // ilk gorulme: kenar yok
      if (mod !== "AUTO" || onceki === "AUTO") return;
      // AUTO'ya GECILDI. Izlenecek bir gorev kaydi yoksa panel acmak
      // anlamsiz olur (bos panel gosterirdi).
      if (!izlenebilirMi(sysid)) return;
      // Panel zaten aciksa ve AYNI drona bagliysa dokunma.
      const acik = !izPopup.classList.contains("popup-gizli");
      if (acik && String(aktifSysid) === String(sysid)) return;
      izlemeGeriAc(sysid);
    });
  }

  // ws.js telemetri isleyicisinden cagrilir
  window.gorevTelemetriIsle = function(m){
    sonGorevDurum = m.gorev_durum || {};
    // v2.4.35: batarya degisimi sonrasi yarim kalmis gorevler
    sonSurdurulebilir = m.gorev_surdurulebilir || {};
    (m.dronlar || []).forEach(d => {
      sonDronlar[String(d.sysid)] = d;
      if (d.mission_seq !== undefined)
        sonMissionSeq[d.sysid] = d.mission_seq;
    });
    // v2.4.41: kumandadan AUTO'ya gecerse gorev panelini otomatik ac.
    // sonGorevDurum GUNCELLENDIKTEN SONRA cagrilir: aksi halde AUTO
    // gecisi ile gorev kaydinin gelmesi ayni pakette olursa
    // izlenebilirMi() eski durumu okur ve panel acilmaz.
    autoGecisDenetle(m.dronlar);
    // v2.4.35: asama degistiyse haritayi yeniden ciz (silik/normal)
    if (haritaCizimGerekliMi() &&
        typeof window.rotaCizimTazele === "function")
      window.rotaCizimTazele();
    izlemeTazele();
  };

  // v2.4.20: sunucudan gelen yukleme/baslatma sonucu
  window.gorevKomutSonucIsle = function(m){
    if (!m || m.sysid === undefined) return;
    if (String(m.sysid) !== String(aktifSysid)){ izlemeTazele(); return; }
    if (!m.basari){
      // Basarisiz: yerel asamayi geri al ki dugmeler kilitlenmesin
      if (m.tip === "gorev_yukle_sonuc") yerelAsama = "hata";
      else if (m.tip === "gorev_baslat_sonuc")
        yerelAsama = (m.bilgi === "gorev_yok") ? "hazir" : "yuklendi";
      // v2.4.35: mod gecisi telemetriden dogrulanamadi. Ornek: sabit
      // kanatta BRAKE yok, LOITER da reddedildi. Arac AUTO'da gorevi
      // UCMAYA DEVAM ediyor demektir; "duraklatildi" gostermek yanlis
      // guvence olur, asamayi geri aliyoruz.
      else if (m.tip === "gorev_durdur_sonuc") yerelAsama = "gorevde";
      else if (m.tip === "gorev_devam_sonuc") yerelAsama = "duraklatildi";
      else if (m.tip === "gorev_surdur_sonuc") yerelAsama = "hazir";
      if (m.hata && typeof window.uyariToastGoster === "function"){
        const dil = t();
        window.uyariToastGoster({
          baslik: dil.gorevKomutHataBaslik || "GÖREV KOMUTU BAŞARISIZ",
          mesaj: m.hata, seviye: "hata", sure: 8000
        });
      }
    }
    izlemeTazele();
  };

  // v2.4.18: sunucudan gelen gorev iptal sonucu
  window.gorevIptalSonucIsle = function(m){
    if (!m || m.sysid === undefined) return;
    if (m.basari){
      delete sonGorevDurum[String(m.sysid)];
      if (String(m.sysid) === String(aktifSysid)) yerelAsama = "hazir";
    }
    izlemeTazele();
  };

  // Dil degisince acik popup'lari tazele
  window.gorevDilTazele = function(){
    if (!secPerde.classList.contains("popup-gizli")) secimListeCiz();
    izlemeTazele();
  };
})();
