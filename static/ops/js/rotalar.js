// =================================================================
// GOKTUNGU - ROTA PLANLAMA (sag panel ROTALAR bolumu + harita duzenleme)
// Bu dosya klasik script'tir; yukleme sirasi index.html'e baglidir.
// Backend: goktungu/rotalar.py + sunucu.py WS komutlari
//   giden : {tip:"rota_kaydet"|"rota_sil"|"rota_listele", ...}
//   gelen : {tip:"rota_listesi", rotalar:[...], yeni_id?}
// =================================================================
(function(){
  // --- DOM referanslari ---
  const listeKutu   = document.getElementById("rotaListesi");
  const yokKutu     = document.getElementById("rotaYokKutu");
  const btnYeni     = document.getElementById("tbYeniRota");
  // FAZ18-IS35-ROTALAR: ust bara tasinan rota tipi dugmeleri.
  // Her biri ILGILI MENU OGESININ .click() tetikleyicisini cagirir;
  // rota olusturma mantigi kopyalanmaz (tek tetikleyici yolu).
  [["tbSpiralRota", "mbSpiralRota"],
   ["tbDilimliRota", "mbSerbestForm"],
   ["tbKoridorRota", "mbKoridorRota"],
   ["tbRotaYukle", "mbRotaYukle"]].forEach(function(c){
    const btn = document.getElementById(c[0]);
    const mnu = document.getElementById(c[1]);
    if (!btn) { console.warn("[FAZ18-IS35-ROTALAR] ust bar dugmesi yok:", c[0]); return; }
    if (!mnu) { console.warn("[FAZ18-IS35-ROTALAR] menu ogesi yok:", c[1]); return; }
    btn.addEventListener("click", function(e){ e.stopPropagation(); mnu.click(); });
  });
  // Yeni rota modali
  const modalPerde  = document.getElementById("rotaModalPerde");
  const inpAd       = document.getElementById("rotaAd");
  const inpIrtifa   = document.getElementById("rotaIrtifa");
  const inpHiz      = document.getElementById("rotaHiz");
  const lblIrtifa   = document.getElementById("rotaIrtifaDeger");
  const lblHiz      = document.getElementById("rotaHizDeger");
  const lblHata     = document.getElementById("rotaHata");
  // Nokta popup'i
  const noktaPopup  = document.getElementById("rotaNoktaPopup");
  const noktaNo     = document.getElementById("rotaNoktaNo");
  const noktaKoord  = document.getElementById("rotaNoktaKoord");
  const inpNIrtifa  = document.getElementById("noktaIrtifa");
  const inpNHiz     = document.getElementById("noktaHiz");
  const lblNIrtifa  = document.getElementById("noktaIrtifaDeger");
  const lblNHiz     = document.getElementById("noktaHizDeger");
  // Detay popup'i
  const detayPerde  = document.getElementById("rotaDetayPerde");
  const detayBaslik = document.getElementById("rotaDetayBaslik");
  const detayOzet   = document.getElementById("rotaDetayOzet");
  const detayListe  = document.getElementById("rotaNoktaListesi");
  // Mod gostergesi
  const rozet       = document.getElementById("rotaRozet");
  const rozetMetin  = document.getElementById("rotaRozetMetin");
  const haritaAlan  = document.getElementById("haritaAlan");
  if (!listeKutu || !btnYeni) return;

  // --- Durum ---
  let rotalar = [];              // sunucudan gelen guncel liste
  let detayRotaId = null;        // detay popup'inda acik rota
  // Duzenleme modu durumu
  let duzenleme = null;          // null | {id, isim, irtifa, hiz, noktalar[], bekleyen}
  let popupModu = "ekle";        // "ekle" (yeni nokta) | "duzenle" (mevcut nokta)
  let duzenlenenIdx = -1;        // popupModu=duzenle iken noktalar[] indeksi
  let surukleme = null;          // null | {idx} - CTRL ile nokta tasima
  // v2.4.23: parametre popup'inda onizlenen rota id'si (kayitli
  // cizimi gizlenir, onizleme katmani cizilir)
  let onizlemeAktifId = null;
  // Cesium ciziimleri: rotaId -> entity[]  (duzenleme icin "duzenleme" anahtari)
  const cizimler = {};

  // --- Renkler ---
  const R_START  = "#16a34a";    // yesil
  const R_FINISH = "#dc2626";    // kirmizi
  const R_ARA    = "#d97706";    // turuncu
  const R_CIZGI  = "#3b82f6";    // mavi rota cizgisi
  const R_DIKEY  = "#93c5fd";    // acik mavi dikey cizgi

  function t(){ return (typeof D === "function") ? D() : {}; }

  // ---------------------------------------------------------------
  // WS yardimcisi
  // ---------------------------------------------------------------
  function wsGonder(m){
    if (typeof ws !== "undefined" && ws && ws.readyState === 1)
      ws.send(JSON.stringify(m));
  }

  // ---------------------------------------------------------------
  // HARITA CIZIMI
  // ---------------------------------------------------------------
  function pinDataUrl(renk){
    // Kucuk daire isaretci (billboard) - canvas ile uret
    const c = document.createElement("canvas");
    c.width = 24; c.height = 24;
    const g = c.getContext("2d");
    g.beginPath(); g.arc(12, 12, 9, 0, Math.PI * 2);
    g.fillStyle = renk; g.fill();
    g.lineWidth = 2.5; g.strokeStyle = "#ffffff"; g.stroke();
    return c.toDataURL();
  }
  const PIN = { start: pinDataUrl(R_START), finish: pinDataUrl(R_FINISH),
                ara: pinDataUrl(R_ARA) };

  function cizimSil(anahtar){
    (cizimler[anahtar] || []).forEach(e => {
      try { viewer.entities.remove(e); } catch(_){}
    });
    delete cizimler[anahtar];
  }

  // v2.4.35: SILIK KIP. Dron goreve basladiginda (asama "gorevde" veya
  // "duraklatildi") rota haritada tam parlaklikta durmaya devam ederse
  // ucan aracin izini ve canli telemetriyi bastiriyor. Bu kipte rota
  // gorunur kalir ama geri plana cekilir:
  //   - cizgi incelir ve seffaflasir
  //   - nokta etiketleri (START/FINISH/numara) cizilmez
  //   - mesafe etiketleri ve donus daireleri cizilmez (gorsel gurultu)
  // Rota tamamen kaldirilmaz; operator gorev hattini yine gorur.
  const SILIK_CIZGI_ALPHA = 0.28;
  const SILIK_PIN_ALPHA   = 0.35;

  function rotaCiz(anahtar, noktalar, etiketler, silik){
    // etiketler: {start, finish} metinleri (i18n)
    // silik: true ise geri plan kipinde cizilir (v2.4.35)
    cizimSil(anahtar);
    if (typeof viewer === "undefined" || !viewer || !noktalar.length) return;
    const ent = [];
    // v2.4.5: cift tiklama ile duzenleme icin rota id'sini isle
    const rotaId = (anahtar.indexOf("rota_") === 0)
      ? parseInt(anahtar.slice(5), 10) : null;
    // Noktalar arasi rota cizgisi (irtifada)
    if (noktalar.length >= 2){
      const dizi = [];
      noktalar.forEach(n => dizi.push(n.lon, n.lat, n.irtifa));
      ent.push(viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(dizi),
          width: silik ? 1.6 : 3,
          material: silik
            ? Cesium.Color.fromCssColorString(R_CIZGI)
                .withAlpha(SILIK_CIZGI_ALPHA)
            : Cesium.Color.fromCssColorString(R_CIZGI),
          arcType: Cesium.ArcType.GEODESIC,
        }
      }));
    }
    noktalar.forEach((n, i) => {
      const son = i === noktalar.length - 1;
      const tipAd = (i === 0) ? "start" : (son && noktalar.length > 1 ? "finish" : "ara");
      const poz = Cesium.Cartesian3.fromDegrees(n.lon, n.lat, n.irtifa);
      // Noktadan yere ince dikey cizgi (silik kipte daha soluk)
      ent.push(viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(
            [n.lon, n.lat, 0, n.lon, n.lat, n.irtifa]),
          width: 1.2,
          material: Cesium.Color.fromCssColorString(R_DIKEY)
            .withAlpha(silik ? 0.22 : 0.85),
        }
      }));
      // Isaretci + etiket
      let metin = String(i + 1);
      if (tipAd === "start")  metin = etiketler.start  || "START";
      if (tipAd === "finish") metin = etiketler.finish || "FINISH";
      const tanim = {
        position: poz,
        billboard: {
          image: PIN[tipAd], verticalOrigin: Cesium.VerticalOrigin.CENTER,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      };
      if (silik){
        // Silik kipte pin kucultulur ve seffaflastirilir; etiket hic
        // cizilmez (ucan dronun kendi etiketiyle cakismasin)
        tanim.billboard.scale = 0.7;
        tanim.billboard.color =
          Cesium.Color.WHITE.withAlpha(SILIK_PIN_ALPHA);
      } else {
        tanim.label = {
          text: metin, font: F_NOKTA,
          fillColor: Cesium.Color.WHITE,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          outlineColor: Cesium.Color.BLACK, outlineWidth: CIZGI_KALIN,
          pixelOffset: new Cesium.Cartesian2(0, -20),
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        };
      }
      const isaretci = viewer.entities.add(tanim);
      // Duzenleme katmaninda isaretciye nokta indeksi isle
      // (mevcut nokta tiklama / surukleme icin)
      if (anahtar === "duzenleme") isaretci._rotaNoktaIdx = i;
      ent.push(isaretci);
    });
    if (!silik){
      // v2.4.21: noktalar arasi mesafe etiketleri
      araMesafeCiz(ent, noktalar);
      // v2.4.21: sabit kanat ise donus daireleri
      donusDaireCiz(ent, noktalar);
    }
    // v2.4.5: tum rota entity'lerine rota id'sini isle
    if (rotaId !== null && !isNaN(rotaId))
      ent.forEach(e => { e._rotaId = rotaId; });
    cizimler[anahtar] = ent;
  }

  // ---------------------------------------------------------------
  // v2.4.21: NOKTALAR ARASI MESAFE (harita etiketi)
  // Iki nokta arasindaki 3B mesafe, bacagin orta noktasinda gosterilir.
  // ---------------------------------------------------------------
  const R_MESAFE = "#38bdf8";     // acik mavi mesafe etiketi
  const R_DAIRE  = "#f59e0b";     // amber donus dairesi

  // v2.4.64: Harita etiketi font boyutlari.
  //
  // NEDEN TEK YERDE: mesafe/yariçap/nokta etiketleri ayni haritada
  // yan yana durur. Boyutlar dagilmis halde tutulursa biri
  // buyutuldugunde digerleri geride kalir ve harita dengesiz gorunur.
  //
  // 11px -> 15px: kullanici sahada "gorunmuyor" bildirdi. Cesium
  // etiketleri arazi dokusu uzerinde okunur olmak zorundadir; disari
  // cizgi (outlineWidth) de 3'ten 4'e cikarildi, cunku yazi
  // buyudukce ince cizgi kontrasti tasiyamaz.
  const F_MESAFE = "700 15px Consolas, monospace";   // bacak mesafesi
  const F_YARICAP = "700 13px Consolas, monospace";  // donus yariçapi
  const F_NOKTA  = "700 13px Consolas, monospace";   // nokta numarasi
  const CIZGI_KALIN = 4;

  function yatayMesafe(a, b){
    // Haversine (m)
    const R = 6371000;
    const f1 = a.lat * Math.PI / 180, f2 = b.lat * Math.PI / 180;
    const df = f2 - f1;
    const dl = (b.lon - a.lon) * Math.PI / 180;
    const h = Math.sin(df / 2) ** 2 +
              Math.cos(f1) * Math.cos(f2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function bacakMesafe(a, b){
    // 3B: yatay + irtifa farki
    const yat = yatayMesafe(a, b);
    const dz = (Number(b.irtifa) || 0) - (Number(a.irtifa) || 0);
    return Math.sqrt(yat * yat + dz * dz);
  }

  function araMesafeCiz(ent, noktalar){
    if (typeof viewer === "undefined" || !viewer) return;
    if (!noktalar || noktalar.length < 2) return;
    for (let i = 0; i < noktalar.length - 1; i++){
      const a = noktalar[i], b = noktalar[i + 1];
      const d = bacakMesafe(a, b);
      if (!isFinite(d) || d < 1) continue;
      // Bacagin orta noktasi (kucuk aralikta dogrusal enterpolasyon yeterli)
      const oLat = (a.lat + b.lat) / 2;
      const oLon = (a.lon + b.lon) / 2;
      const oAlt = ((Number(a.irtifa) || 0) + (Number(b.irtifa) || 0)) / 2;
      ent.push(viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(oLon, oLat, oAlt),
        label: {
          text: mesafeMetni(d),
          font: F_MESAFE,
          fillColor: Cesium.Color.fromCssColorString(R_MESAFE),
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          outlineColor: Cesium.Color.BLACK, outlineWidth: CIZGI_KALIN,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          // Font 11 -> 15px buyudugu icin kaydirma da artirildi;
          // aksi halde etiket bacak cizgisinin uzerine biner.
          pixelOffset: new Cesium.Cartesian2(0, -6),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          // Cok uzaktan bakildiginda etiket yigilmasini onle
          distanceDisplayCondition:
            new Cesium.DistanceDisplayCondition(0, 250000),
        }
      }));
    }
  }

  // ---------------------------------------------------------------
  // v2.4.21: SABIT KANAT DONUS DAIRESI
  // Ara noktalarda ucagin fiziksel olarak cizecegi donus yayi,
  // parametrelerden hesaplanan minimum donus yariçapi ile gosterilir.
  //   R = V^2 / (g * tan(phi))
  //   V   : kruvaziyer hiz  (AIRSPEED_CRUISE | TRIM_ARSPD_CM/100 | nokta.hiz)
  //   phi : maks yatis acisi (ROLL_LIMIT_DEG | LIM_ROLL_CD/100)
  // WP_LOITER_RAD tanimliysa ayrica loiter dairesi cizilir.
  // ---------------------------------------------------------------
  let ucusParam = {};          // sysid -> {ad: deger}
  let ucusParamIstek = {};     // sysid -> son istek ts (tekrari onle)

  function hedefSysid(){
    // Rota hangi drona yuklenecek: gorev modulundeki aktif dron,
    // yoksa secili/tek dron.
    if (typeof window.gorevAktifSysid === "function"){
      const s = window.gorevAktifSysid();
      if (s) return Number(s);
    }
    if (typeof sonVeri === "object" && sonVeri){
      const idler = Object.keys(sonVeri).filter(
        s => sonVeri[s] && sonVeri[s].baglanti);
      if (idler.length === 1) return Number(idler[0]);
      // Cok dron: donus dairesi icin ilk sabit kanatli araci kullan
      for (const s of idler){
        const tp = Number((sonVeri[s] || {}).arac_tipi || 0);
        if (tp === 1 || (tp >= 19 && tp <= 25)) return Number(s);
      }
    }
    return null;
  }

  function sabitKanatMi(sysid){
    if (!sysid) return false;
    if (typeof fsAracKategori === "function")
      return fsAracKategori(sysid) === "plane";
    const d = (typeof sonVeri === "object" && sonVeri) ? (sonVeri[sysid] || {}) : {};
    const tp = Number(d.arac_tipi || 0);
    return tp === 1 || (tp >= 19 && tp <= 25);
  }

  function ucusParamIste(sysid){
    const simdi = Date.now();
    if ((ucusParamIstek[sysid] || 0) + 30000 > simdi) return;
    ucusParamIstek[sysid] = simdi;
    wsGonder({tip: "rota_ucus_param", sysid: Number(sysid)});
  }

  // ws.js -> rota_ucus_param yanitini buraya iletir
  window.rotaUcusParamIsle = function(m){
    if (!m || !m.sysid) return;
    ucusParam[m.sysid] = m.parametreler || {};
    tumRotalariCiz();
    duzenlemeCiz();
  };

  function donusYaricap(sysid, noktaHiz){
    // Donus: {r_m, kaynak, hiz, yatis} veya null
    const p = ucusParam[sysid] || {};
    let phi = null;
    if (isFinite(p.ROLL_LIMIT_DEG)) phi = Number(p.ROLL_LIMIT_DEG);
    else if (isFinite(p.LIM_ROLL_CD)) phi = Number(p.LIM_ROLL_CD) / 100;
    if (!phi || phi <= 0 || phi >= 89) phi = 45;   // ArduPlane varsayilani
    let v = null;
    if (isFinite(p.AIRSPEED_CRUISE) && Number(p.AIRSPEED_CRUISE) > 0)
      v = Number(p.AIRSPEED_CRUISE);
    else if (isFinite(p.TRIM_ARSPD_CM) && Number(p.TRIM_ARSPD_CM) > 0)
      v = Number(p.TRIM_ARSPD_CM) / 100;
    else if (isFinite(noktaHiz) && Number(noktaHiz) > 0)
      v = Number(noktaHiz);
    if (!v || v <= 0) return null;
    const g = 9.80665;
    const r = (v * v) / (g * Math.tan(phi * Math.PI / 180));
    if (!isFinite(r) || r <= 0) return null;
    return {r_m: r, hiz: v, yatis: phi};
  }

  function daireNoktalari(lat, lon, r_m, n){
    // Merkez cevresinde n parcali daire (derece dizisi)
    const dizi = [];
    const dLat = r_m / 111320;
    const dLon = r_m / (111320 * Math.cos(lat * Math.PI / 180) || 1);
    for (let i = 0; i <= n; i++){
      const a = (i / n) * 2 * Math.PI;
      dizi.push(lon + dLon * Math.cos(a), lat + dLat * Math.sin(a));
    }
    return dizi;
  }

  function donusDaireCiz(ent, noktalar){
    if (typeof viewer === "undefined" || !viewer) return;
    if (!noktalar || noktalar.length < 3) return;
    const sysid = hedefSysid();
    if (!sysid || !sabitKanatMi(sysid)) return;
    if (!ucusParam[sysid]){ ucusParamIste(sysid); return; }
    const p = ucusParam[sysid];
    // Ara noktalarda (ilk ve son haric) donus dairesi
    for (let i = 1; i < noktalar.length - 1; i++){
      const n = noktalar[i];
      const don = donusYaricap(sysid, n.hiz);
      if (!don) continue;
      const alt = Number(n.irtifa) || 0;
      // Donus yariçapi dairesi: nokta cevresinde ucagin
      // fiziksel olarak sigabilecegi en kucuk donus
      ent.push(viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(
            daireNoktalari(n.lat, n.lon, don.r_m, 72).reduce(
              (acc, v, idx, arr) => {
                if (idx % 2 === 0) acc.push(v, arr[idx + 1], alt);
                return acc;
              }, [])),
          width: 1.6,
          material: new Cesium.PolylineDashMaterialProperty({
            color: Cesium.Color.fromCssColorString(R_DAIRE).withAlpha(0.9),
            dashLength: 12,
          }),
          arcType: Cesium.ArcType.GEODESIC,
        }
      }));
      // Yariçap etiketi
      ent.push(viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(n.lon, n.lat, alt),
        label: {
          text: "R " + Math.round(don.r_m) + " m",
          font: F_YARICAP,
          fillColor: Cesium.Color.fromCssColorString(R_DAIRE),
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          outlineColor: Cesium.Color.BLACK, outlineWidth: CIZGI_KALIN,
          pixelOffset: new Cesium.Cartesian2(0, 16),
          verticalOrigin: Cesium.VerticalOrigin.TOP,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          distanceDisplayCondition:
            new Cesium.DistanceDisplayCondition(0, 250000),
        }
      }));
    }
    // Son noktada loiter dairesi (WP_LOITER_RAD)
    const lr = Number(p.WP_LOITER_RAD);
    if (isFinite(lr) && Math.abs(lr) >= 10){
      const son = noktalar[noktalar.length - 1];
      const alt = Number(son.irtifa) || 0;
      ent.push(viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(
            daireNoktalari(son.lat, son.lon, Math.abs(lr), 72).reduce(
              (acc, v, idx, arr) => {
                if (idx % 2 === 0) acc.push(v, arr[idx + 1], alt);
                return acc;
              }, [])),
          width: 1.4,
          material: Cesium.Color.fromCssColorString(R_DAIRE).withAlpha(0.55),
          arcType: Cesium.ArcType.GEODESIC,
        }
      }));
    }
  }

  // v2.4.35: bir rotanin gorev durumu. GorevYoneticisi telemetri ile
  // asamayi yayinlar; burada rota_id -> asama eslemesi kurulur.
  //   "gorevde" / "duraklatildi" -> SILIK ciz (arac hatti izliyor)
  //   "tamamlandi" / kayit yok    -> normal ciz veya kullanici gorunur
  //                                  ayarina uy
  // Not: gorev bitince/iptalde rotayi haritadan DUSURMEK icin
  // gorev.js sunucuya rota_kaydet{gorunur:false} gonderir; burada
  // yalnizca silik/normal ayrimi yapilir.
  function rotaGorevAsamasi(rotaId){
    const paket = (typeof window.gorevDurumPaketi === "function")
      ? window.gorevDurumPaketi() : null;
    if (!paket) return null;
    let bulunan = null;
    Object.keys(paket).forEach(sysid => {
      const g = paket[sysid];
      if (g && g.rota_id === rotaId) bulunan = g.asama || null;
    });
    return bulunan;
  }

  function tumRotalariCiz(){
    // Kayitli rotalar: gorunur olanlari ciz, digerlerini kaldir
    const et = { start: t().rotaBaslangic || "START",
                 finish: t().rotaBitis || "FINISH" };
    const gecerli = new Set();
    rotalar.forEach(r => {
      const anahtar = "rota_" + r.id;
      gecerli.add(anahtar);
      // Duzenlemede olan rota kayitli halinden cizilmez (duzenleme katmani cizer)
      if (duzenleme && duzenleme.id === r.id){ cizimSil(anahtar); return; }
      // v2.4.23: parametre popup'inda onizlenen rota da atlanir
      if (onizlemeAktifId !== null && onizlemeAktifId === r.id){
        cizimSil(anahtar); return;
      }
      if (r.gorunur){
        // v2.4.35: gorev ucusta ise rota geri plana cekilir
        const asama = rotaGorevAsamasi(r.id);
        const silik = (asama === "gorevde" || asama === "duraklatildi");
        rotaCiz(anahtar, r.noktalar || [], et, silik);
      }
      else cizimSil(anahtar);
    });
    // Silinen rotalarin cizimlerini temizle
    Object.keys(cizimler).forEach(a => {
      if (a.indexOf("rota_") === 0 && !gecerli.has(a)) cizimSil(a);
    });
  }

  function duzenlemeCiz(){
    if (!duzenleme) { cizimSil("duzenleme"); return; }
    const et = { start: t().rotaBaslangic || "START",
                 finish: t().rotaBitis || "FINISH" };
    const noktalar = duzenleme.noktalar.slice();
    if (duzenleme.bekleyen) noktalar.push(duzenleme.bekleyen);
    rotaCiz("duzenleme", noktalar, et);
  }

  // ---------------------------------------------------------------
  // MESAFE (liste gosterimi icin format)
  // ---------------------------------------------------------------
  function mesafeMetni(m){
    if (m === undefined || m === null) return "";
    return (m >= 1000) ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";
  }

  // ---------------------------------------------------------------
  // ROTA LISTESI (sag panel)
  // ---------------------------------------------------------------
  function listeCiz(){
    listeKutu.innerHTML = "";
    if (yokKutu) yokKutu.style.display = rotalar.length ? "none" : "";
    rotalar.forEach(r => {
      const satir = document.createElement("div");
      satir.className = "rota-satir";
      const ikon = document.createElement("i");
      ikon.className = "fa-solid fa-route rota-ikon";
      const ad = document.createElement("span");
      ad.className = "rota-ad"; ad.textContent = r.isim; ad.title = r.isim;
      const mesafe = document.createElement("span");
      mesafe.className = "rota-mesafe";
      mesafe.textContent = mesafeMetni(r.mesafe_m);
      const goz = document.createElement("button");
      goz.className = "rota-goz" + (r.gorunur ? "" : " kapali");
      goz.title = t().rotaGosterGizle || "Göster / Gizle";
      goz.innerHTML = '<i class="fa-solid ' +
        (r.gorunur ? "fa-eye" : "fa-eye-slash") + '"></i>';
      goz.addEventListener("click", (e) => {
        e.stopPropagation();
        wsGonder({tip: "rota_kaydet", id: r.id, gorunur: !r.gorunur});
      });
      satir.appendChild(ikon); satir.appendChild(ad);
      satir.appendChild(mesafe); satir.appendChild(goz);
      satir.addEventListener("click", () => detayAc(r.id));
      listeKutu.appendChild(satir);
    });
  }

  // ---------------------------------------------------------------
  // DETAY POPUP'I (nokta listesi + sil / duzenle)
  // ---------------------------------------------------------------
  function detayAc(id){
    const r = rotalar.find(x => x.id === id);
    if (!r) return;
    detayRotaId = id;
    detayBaslik.textContent = r.isim;
    detayOzet.textContent =
      (r.noktalar || []).length + " " + (t().rotaNoktaSayisi || "nokta") +
      "  |  " + (t().rotaToplam || "Toplam") + ": " + mesafeMetni(r.mesafe_m);
    detayListe.innerHTML = "";
    (r.noktalar || []).forEach((n, i) => {
      const son = i === r.noktalar.length - 1;
      const satir = document.createElement("div");
      satir.className = "rota-nokta-satir";
      const no = document.createElement("span");
      no.className = "rn-no" +
        (i === 0 ? " start" : (son && r.noktalar.length > 1 ? " finish" : ""));
      no.textContent = i + 1;
      const koord = document.createElement("span");
      koord.className = "rn-koord";
      koord.textContent = n.lat.toFixed(5) + ", " + n.lon.toFixed(5);
      const param = document.createElement("span");
      param.className = "rn-param";
      // v2.4.23: nokta yonelim acisi varsa gosterilir (yoksa OTO)
      let ek = "";
      if (n.aci !== undefined && n.aci !== null && Number(n.aci) >= 0)
        ek = " | " + Math.round(Number(n.aci)) + "\u00b0";
      param.textContent = n.irtifa + " m | " + n.hiz + " m/s" + ek;
      satir.appendChild(no); satir.appendChild(koord); satir.appendChild(param);
      detayListe.appendChild(satir);
    });
    detayPerde.classList.remove("popup-gizli");
  }
  function detayKapat(){
    detayPerde.classList.add("popup-gizli");
    detayRotaId = null;
  }
  document.getElementById("btnRotaDetayKapat")
    .addEventListener("click", detayKapat);
  document.getElementById("btnRotaDetayIptal")
    .addEventListener("click", detayKapat);
  detayPerde.addEventListener("click", (e) => {
    if (e.target === detayPerde) detayKapat();
  });
  document.getElementById("btnRotaSil").addEventListener("click", () => {
    if (detayRotaId === null) return;
    const r = rotalar.find(x => x.id === detayRotaId);
    onayIste(onayMetni("onayRotaSil", {ad: (r && r.isim) || detayRotaId}), () => {
      if (detayRotaId === null) return;
      wsGonder({tip: "rota_sil", id: detayRotaId});
      detayKapat();
    });
  });
  document.getElementById("btnRotaDuzenle").addEventListener("click", () => {
    const r = rotalar.find(x => x.id === detayRotaId);
    detayKapat();
    if (!r) return;
    // v2.4.23: serbest form rotalari kendi cizim popup'inda acilir
    if (r.meta && r.meta.tur === "serbest_form" &&
        typeof window.serbestFormDuzenle === "function"){
      window.serbestFormDuzenle(r);
      return;
    }
    // v2.4.40: koridor gorevleri de kendi popup'inda acilir. Genel
    // nokta editoru merkez hatti bilmedigi icin koridoru bozar:
    // noktalar SOL/SAG kenar taramasidir, merkez hat meta'dadir.
    if (r.meta && r.meta.tur === "koridor" &&
        typeof window.koridorDuzenle === "function"){
      window.koridorDuzenle(r);
      return;
    }
    duzenlemeBaslat({
      id: r.id, isim: r.isim,
      irtifa: r.irtifa_varsayilan, hiz: r.hiz_varsayilan,
      noktalar: (r.noktalar || []).map(n => Object.assign({}, n)),
    });
  });

  // v2.4.23: PARAMETRELERI DEGISTIR - noktalari yeniden cizmeden
  // irtifa / hiz / yonelim acisi (ve serbest formda aralik + yon)
  // duzenleme popup'ini acar.
  const btnParam = document.getElementById("btnRotaParam");
  if (btnParam){
    btnParam.addEventListener("click", () => {
      const r = rotalar.find(x => x.id === detayRotaId);
      if (!r) return;
      detayKapat();
      if (typeof window.rotaParamAc === "function") window.rotaParamAc(r);
    });
  }

  // ---------------------------------------------------------------
  // PARAMETRE ONIZLEMESI (v2.4.23)
  // rota_param.js duzenleme sirasinda cagirir: degistirilen
  // irtifa/hiz degerleri haritada canli gorunsun. Kayitli rotanin
  // cizimi gecici olarak gizlenir, onizleme katmani cizilir.
  // ---------------------------------------------------------------
  window.rotaOnizlemeCiz = function(rotaId, noktalar){
    onizlemeAktifId = (rotaId === undefined) ? null : rotaId;
    if (onizlemeAktifId !== null) cizimSil("rota_" + onizlemeAktifId);
    const et = { start: t().rotaBaslangic || "START",
                 finish: t().rotaBitis || "FINISH" };
    rotaCiz("param_onizleme", (noktalar || []).map(
      n => Object.assign({}, n)), et);
  };
  window.rotaOnizlemeTemizle = function(){
    cizimSil("param_onizleme");
    onizlemeAktifId = null;
    tumRotalariCiz();
  };

  // ---------------------------------------------------------------
  // YENI ROTA MODALI
  // ---------------------------------------------------------------
  function modalAc(){
    inpAd.value = "";
    lblHata.textContent = "";
    sliderTazele();
    modalPerde.classList.remove("popup-gizli");
    setTimeout(() => inpAd.focus(), 60);
  }
  function modalKapat(){ modalPerde.classList.add("popup-gizli"); }
  function sliderTazele(){
    lblIrtifa.textContent = inpIrtifa.value + " m";
    lblHiz.textContent = parseFloat(inpHiz.value).toFixed(1) + " m/s (" +
      (parseFloat(inpHiz.value) * 3.6).toFixed(1) + " km/h)";
  }
  inpIrtifa.addEventListener("input", sliderTazele);
  inpHiz.addEventListener("input", sliderTazele);
  btnYeni.addEventListener("click", modalAc);
  document.getElementById("btnRotaModalKapat")
    .addEventListener("click", modalKapat);
  document.getElementById("btnRotaIptal").addEventListener("click", modalKapat);
  modalPerde.addEventListener("click", (e) => {
    if (e.target === modalPerde) modalKapat();
  });
  document.getElementById("btnRotaKaydet").addEventListener("click", () => {
    const isim = inpAd.value.trim();
    if (!isim){
      lblHata.textContent = t().rotaHataAd || "Rota adı boş olamaz.";
      return;
    }
    modalKapat();
    duzenlemeBaslat({
      id: null, isim: isim,
      irtifa: parseFloat(inpIrtifa.value),
      hiz: parseFloat(inpHiz.value),
      noktalar: [],
    });
  });
  inpAd.addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btnRotaKaydet").click();
  });

  // ---------------------------------------------------------------
  // DUZENLEME MODU
  // ---------------------------------------------------------------
  function duzenlemeBaslat(d){
    duzenleme = d;
    duzenleme.bekleyen = null;
    rozetMetin.textContent = (t().rotaRozetMetin ||
      "ROTA DÜZENLEME MODU — haritaya tıklayarak nokta ekleyin");
    rozet.style.display = "";
    haritaAlan.classList.add("rota-duzenleme");
    tumRotalariCiz();   // duzenlenen rotanin kayitli cizimini kaldirir
    duzenlemeCiz();
  }

  function duzenlemeBitir(kaydet){
    if (!duzenleme) return;
    if (kaydet){
      if (duzenleme.id === null){
        wsGonder({tip: "rota_kaydet", isim: duzenleme.isim,
                  irtifa: duzenleme.irtifa, hiz: duzenleme.hiz,
                  noktalar: duzenleme.noktalar});
      } else {
        wsGonder({tip: "rota_kaydet", id: duzenleme.id,
                  noktalar: duzenleme.noktalar});
      }
    }
    duzenleme = null;
    noktaPopupKapat(false);
    rozet.style.display = "none";
    haritaAlan.classList.remove("rota-duzenleme");
    cizimSil("duzenleme");
    tumRotalariCiz();
  }

  // ESC ile moddan cik (kaydederek, mevcut noktalarla)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && duzenleme &&
        noktaPopup.classList.contains("popup-gizli")){
      duzenlemeBitir(true);
    }
  });

  // ---------------------------------------------------------------
  // NOKTA POPUP'I (duzenleme modunda harita tiklamasi)
  // ---------------------------------------------------------------
  function noktaSliderTazele(){
    lblNIrtifa.textContent = inpNIrtifa.value + " m";
    lblNHiz.textContent = parseFloat(inpNHiz.value).toFixed(1) + " m/s (" +
      (parseFloat(inpNHiz.value) * 3.6).toFixed(1) + " km/h)";
    // Bekleyen / duzenlenen noktanin cizimini canli guncelle
    if (duzenleme && popupModu === "ekle" && duzenleme.bekleyen){
      duzenleme.bekleyen.irtifa = parseFloat(inpNIrtifa.value);
      duzenleme.bekleyen.hiz = parseFloat(inpNHiz.value);
      duzenlemeCiz();
    } else if (duzenleme && popupModu === "duzenle" &&
               duzenleme.noktalar[duzenlenenIdx]){
      duzenleme.noktalar[duzenlenenIdx].irtifa = parseFloat(inpNIrtifa.value);
      duzenleme.noktalar[duzenlenenIdx].hiz = parseFloat(inpNHiz.value);
      duzenlemeCiz();
    }
  }
  inpNIrtifa.addEventListener("input", noktaSliderTazele);
  inpNHiz.addEventListener("input", noktaSliderTazele);

  function popupDugmeleriAyarla(){
    // ekle: YENI NOKTA gorunur; duzenle: GUNCELLE + NOKTAYI SIL gorunur
    document.getElementById("btnNoktaEkle").style.display =
      (popupModu === "ekle") ? "" : "none";
    document.getElementById("btnNoktaGuncelle").style.display =
      (popupModu === "duzenle") ? "" : "none";
    document.getElementById("btnNoktaSil").style.display =
      (popupModu === "duzenle") ? "" : "none";
    document.getElementById("btnRotaSonlandir").style.display =
      (popupModu === "ekle") ? "" : "none";
  }

  function noktaPopupAc(ekranX, ekranY){
    if (!duzenleme || !duzenleme.bekleyen) return;
    popupModu = "ekle"; duzenlenenIdx = -1;
    popupDugmeleriAyarla();
    noktaNo.textContent = "#" + (duzenleme.noktalar.length + 1);
    noktaKoord.textContent = duzenleme.bekleyen.lat.toFixed(6) + ", " +
                             duzenleme.bekleyen.lon.toFixed(6);
    inpNIrtifa.value = duzenleme.bekleyen.irtifa;
    inpNHiz.value = duzenleme.bekleyen.hiz;
    lblNIrtifa.textContent = inpNIrtifa.value + " m";
    lblNHiz.textContent = parseFloat(inpNHiz.value).toFixed(1) + " m/s";
    // Ekran disina tasmasin
    const pw = 290, ph = 320;
    noktaPopup.style.left =
      Math.min(ekranX + 12, window.innerWidth - pw - 8) + "px";
    noktaPopup.style.top =
      Math.min(ekranY + 12, window.innerHeight - ph - 8) + "px";
    noktaPopup.classList.remove("popup-gizli");
  }

  // Mevcut noktayi duzenleme popup'i (ayni pencere, "duzenle" modu)
  function noktaDuzenlePopupAc(idx, ekranX, ekranY){
    if (!duzenleme || !duzenleme.noktalar[idx]) return;
    const n = duzenleme.noktalar[idx];
    popupModu = "duzenle"; duzenlenenIdx = idx;
    popupDugmeleriAyarla();
    noktaNo.textContent = "#" + (idx + 1);
    noktaKoord.textContent = n.lat.toFixed(6) + ", " + n.lon.toFixed(6);
    inpNIrtifa.value = n.irtifa;
    inpNHiz.value = n.hiz;
    lblNIrtifa.textContent = inpNIrtifa.value + " m";
    lblNHiz.textContent = parseFloat(inpNHiz.value).toFixed(1) + " m/s";
    const pw = 290, ph = 320;
    noktaPopup.style.left =
      Math.min(ekranX + 12, window.innerWidth - pw - 8) + "px";
    noktaPopup.style.top =
      Math.min(ekranY + 12, window.innerHeight - ph - 8) + "px";
    noktaPopup.classList.remove("popup-gizli");
  }

  function noktaPopupKapat(noktayiKaldir){
    if (noktayiKaldir && duzenleme && popupModu === "ekle"){
      duzenleme.bekleyen = null;
      duzenlemeCiz();
    }
    popupModu = "ekle"; duzenlenenIdx = -1;
    noktaPopup.classList.add("popup-gizli");
  }

  // IPTAL: bekleyen noktayi kaldir + popup kapat
  document.getElementById("btnNoktaIptal")
    .addEventListener("click", () => noktaPopupKapat(true));
  document.getElementById("btnRotaNoktaKapat")
    .addEventListener("click", () => noktaPopupKapat(true));
  // YENI NOKTA: bekleyeni kalici noktaya cevir, popup kapat, moda devam
  document.getElementById("btnNoktaEkle").addEventListener("click", () => {
    if (!duzenleme || !duzenleme.bekleyen) return;
    duzenleme.bekleyen.irtifa = parseFloat(inpNIrtifa.value);
    duzenleme.bekleyen.hiz = parseFloat(inpNHiz.value);
    duzenleme.noktalar.push(duzenleme.bekleyen);
    duzenleme.bekleyen = null;
    duzenlemeCiz();
    noktaPopupKapat(false);
  });
  // GUNCELLE (duzenle modu): slider degerleri zaten anlik islendi; kapat
  document.getElementById("btnNoktaGuncelle").addEventListener("click", () => {
    if (!duzenleme || popupModu !== "duzenle") return;
    const n = duzenleme.noktalar[duzenlenenIdx];
    if (n){
      n.irtifa = parseFloat(inpNIrtifa.value);
      n.hiz = parseFloat(inpNHiz.value);
    }
    duzenlemeCiz();
    noktaPopupKapat(false);
  });
  // NOKTAYI SIL (duzenle modu): noktayi rotadan cikar
  document.getElementById("btnNoktaSil").addEventListener("click", () => {
    if (!duzenleme || popupModu !== "duzenle") return;
    onayIste(onayMetni("onayNoktaSil"), () => {
      if (!duzenleme || popupModu !== "duzenle") return;
      if (duzenlenenIdx >= 0) duzenleme.noktalar.splice(duzenlenenIdx, 1);
      duzenlemeCiz();
      noktaPopupKapat(false);
    });
  });
  // ROTAYI SONLANDIR: bekleyen varsa onu da ekle, kaydet ve moddan cik
  document.getElementById("btnRotaSonlandir").addEventListener("click", () => {
    if (duzenleme && duzenleme.bekleyen){
      duzenleme.bekleyen.irtifa = parseFloat(inpNIrtifa.value);
      duzenleme.bekleyen.hiz = parseFloat(inpNHiz.value);
      duzenleme.noktalar.push(duzenleme.bekleyen);
      duzenleme.bekleyen = null;
    }
    noktaPopupKapat(false);
    duzenlemeBitir(true);
  });

  // ---------------------------------------------------------------
  // HARITA TIKLAMASI (duzenleme modu aktifken)
  // ---------------------------------------------------------------
  // Ekran konumundaki duzenleme-katmani nokta indeksini bul (pick)
  function noktaIdxBul(ekranX, ekranY){
    try {
      const secilen = viewer.scene.drillPick(
        new Cesium.Cartesian2(ekranX, ekranY), 8);
      for (const p of secilen){
        const ent = p && p.id;
        if (ent && typeof ent._rotaNoktaIdx === "number")
          return ent._rotaNoktaIdx;
      }
    } catch(_){}
    return -1;
  }

  function tikKur(){
    const kap = document.getElementById("cesiumContainer");
    if (!kap || typeof viewer === "undefined" || !viewer){
      setTimeout(tikKur, 500); return;
    }

    // --- CTRL + surukleme: mevcut noktayi tasima ---
    // NOT: Cesium kamera kontrolu PointerEvent dinler (pointerdown/move/up).
    // mousedown ile dinlemek gercek farede Cesium'un CTRL+drag (tilt)
    // davranisiyla yarisir ve kaybeder. Bu yuzden pointer olaylarini
    // CAPTURE fazinda, Cesium'un canvas isleyicisinden ONCE yakalayip
    // stopImmediatePropagation ile kesiyoruz.
    function sarukleBirak(){
      if (!surukleme) return;
      surukleme = null;
      try {
        viewer.scene.screenSpaceCameraController.enableInputs = true;
      } catch(_){}
      kap.style.cursor = "";
      // Konum degisikligi duzenleme.noktalar'da zaten islendi;
      // rota sonlandirilinca sunucuya kaydedilir
    }

    kap.addEventListener("pointerdown", (e) => {
      if (!duzenleme || !e.ctrlKey || e.altKey || e.button !== 0) return;
      const r = kap.getBoundingClientRect();
      const idx = noktaIdxBul(e.clientX - r.left, e.clientY - r.top);
      if (idx < 0) return;
      // Cesium'un pointerdown isleyicisine ulasmadan kes
      e.preventDefault();
      e.stopImmediatePropagation();
      e.stopPropagation();
      surukleme = {idx: idx, pointerId: e.pointerId};
      noktaPopupKapat(false);
      // Kamera hareketini kilitle
      viewer.scene.screenSpaceCameraController.enableInputs = false;
      kap.style.cursor = "grabbing";
      // Imlec canvas disina ciksa da olaylari almaya devam et
      try { kap.setPointerCapture(e.pointerId); } catch(_){}
    }, true);

    kap.addEventListener("pointermove", (e) => {
      if (!duzenleme){
        if (kap.style.cursor === "copy") kap.style.cursor = "";
        return;
      }
      if (surukleme){
        // Cesium'a gitmesin (kamera kilitli olsa da temiz olsun)
        e.preventDefault();
        e.stopImmediatePropagation();
        e.stopPropagation();
        // Nokta tasiniyor: imlec altindaki koordinata tasi
        const r = kap.getBoundingClientRect();
        const k = (typeof window.__ekrandanKoordinat === "function")
          ? window.__ekrandanKoordinat(e.clientX - r.left, e.clientY - r.top)
          : null;
        if (!k) return;
        const n = duzenleme.noktalar[surukleme.idx];
        if (n){ n.lat = k.lat; n.lon = k.lon; duzenlemeCiz(); }
        return;
      }
      // CTRL basiliyken nokta ustunde 'tasinabilir' imleci goster
      if (e.ctrlKey){
        const r = kap.getBoundingClientRect();
        const idx = noktaIdxBul(e.clientX - r.left, e.clientY - r.top);
        kap.style.cursor = (idx >= 0) ? "grab" : "";
      } else if (kap.style.cursor === "grab"){
        kap.style.cursor = "";
      }
    }, true);

    kap.addEventListener("pointerup", (e) => {
      if (!surukleme) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      e.stopPropagation();
      try { kap.releasePointerCapture(e.pointerId); } catch(_){}
      sarukleBirak();
    }, true);

    // Guvenlik agi: pointer iptal olursa veya capture kaybolursa birak
    kap.addEventListener("pointercancel", sarukleBirak, true);
    kap.addEventListener("lostpointercapture", () => {
      if (surukleme) sarukleBirak();
    }, true);
    // Eski tarayici / kenar durumlar icin dokuman mouseup yedegi
    document.addEventListener("mouseup", () => {
      if (surukleme) sarukleBirak();
    }, true);

    kap.addEventListener("click", (e) => {
      if (!duzenleme) return;
      if (e.altKey) return;                // ALT konum kaydetme icin
      // Surukleme sonrasi gelen click'i yut
      if (e.ctrlKey){ e.preventDefault(); e.stopPropagation(); return; }
      e.preventDefault(); e.stopPropagation();
      const r = kap.getBoundingClientRect();
      // Mevcut noktaya tiklama: duzenleme popup'i ac
      const idx = noktaIdxBul(e.clientX - r.left, e.clientY - r.top);
      if (idx >= 0){
        duzenleme.bekleyen = null;
        duzenlemeCiz();
        noktaDuzenlePopupAc(idx, e.clientX, e.clientY);
        return;
      }
      // Bos alana tiklama: yeni nokta ekleme akisi
      const k = (typeof window.__ekrandanKoordinat === "function")
        ? window.__ekrandanKoordinat(e.clientX - r.left, e.clientY - r.top)
        : null;
      if (!k) return;
      // v2.2.0: spiral modu bekliyorsa ilk tiklama merkezi belirler
      if (typeof window.__rotaSpiralTikla === "function" &&
          window.__rotaSpiralTikla(k)) return;
      duzenleme.bekleyen = {
        lat: k.lat, lon: k.lon,
        irtifa: duzenleme.irtifa, hiz: duzenleme.hiz,
      };
      duzenlemeCiz();
      noktaPopupAc(e.clientX, e.clientY);
    }, true);   // capture: Cesium handler'larindan once
  }
  tikKur();

  // Diger moduller icin: rota duzenleme modu aktif mi?
  window.__rotaDuzenlemeAktif = function(){ return !!duzenleme; };

  // ---------------------------------------------------------------
  // DIS VERI YUKLEME (v2.2.0 - rota_tipleri.js kancalari)
  // ---------------------------------------------------------------
  // Ice aktarilan (Mission Planner / QGC) rotayi duzenleme moduna yukler;
  // kullanici gozden gecirir, ESC ile kaydeder.
  window.rotaDisVeriYukle = function(v){
    if (duzenleme) duzenlemeBitir(true);   // acik duzenleme varsa kaydet
    duzenlemeBaslat({
      id: null, isim: v.isim,
      irtifa: v.irtifa, hiz: v.hiz,
      noktalar: (v.noktalar || []).map(n => Object.assign({}, n)),
    });
    // Ilk noktaya odaklan
    const n0 = v.noktalar && v.noktalar[0];
    if (n0 && typeof viewer !== "undefined"){
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(n0.lon, n0.lat, 4000),
        duration: 1.4,
      });
    }
  };

  // SPIRAL MODU: duzenleme moduna girer ama ilk harita tiklamasi nokta
  // eklemek yerine spiral merkezini belirler ve tum noktalari uretir.
  let spiralBekleyen = null;   // null | {isim, parametreler, uret}
  window.rotaSpiralModuBaslat = function(s){
    if (duzenleme) duzenlemeBitir(true);
    spiralBekleyen = s;
    duzenlemeBaslat({
      id: null, isim: s.isim,
      irtifa: s.parametreler.basYuk, hiz: s.parametreler.hiz,
      noktalar: [],
    });
    rozetMetin.textContent = (t().rotaSpiralRozet ||
      "SPİRAL ROTA — haritada başlangıç (merkez) noktasını tıklayın");
  };
  // Spiral merkezi tiklamasi: tikKur click handler'i cagirir (asagida)
  window.__rotaSpiralTikla = function(k){
    if (!spiralBekleyen || !duzenleme) return false;
    const s = spiralBekleyen;
    spiralBekleyen = null;
    duzenleme.noktalar = s.uret(k.lat, k.lon);
    duzenleme.bekleyen = null;
    // v2.3.0: spiral uretildigi anda otomatik kaydet ve moddan cik
    duzenlemeBitir(true);
    return true;
  };
  window.__rotaSpiralBekliyor = function(){ return !!spiralBekleyen; };

  // ---------------------------------------------------------------
  // SUNUCU MESAJI GIRISI (ws.js cagirir)
  // ---------------------------------------------------------------
  window.rotaListesiIsle = function(m){
    rotalar = m.rotalar || [];
    listeCiz();
    tumRotalariCiz();
  };

  // Gorev modulu icin: guncel rota listesini dondur
  window.rotaVerileri = function(){ return rotalar; };

  // v2.4.21: harita cizimini yeniden uret (hedef arac degistiginde
  // donus daireleri icin gorev.js cagirir)
  window.rotaCizimTazele = function(){
    tumRotalariCiz();
    duzenlemeCiz();
  };

  // Menubar: TUM ROTALARI AC/KAPAT - hepsi gorunurse gizler, degilse gosterir
  window.tumRotalariAcKapat = function(){
    if (!rotalar.length) return;
    const hepsiGorunur = rotalar.every(r => r.gorunur);
    const yeni = !hepsiGorunur;
    rotalar.forEach(r => {
      if (!!r.gorunur !== yeni)
        wsGonder({tip: "rota_kaydet", id: r.id, gorunur: yeni});
    });
  };

  // Dil degisince liste ve rozet metnini tazele
  window.rotaDilTazele = function(){
    listeCiz();
    if (duzenleme) rozetMetin.textContent = (t().rotaRozetMetin || "");
    tumRotalariCiz();
    duzenlemeCiz();
  };
})();
