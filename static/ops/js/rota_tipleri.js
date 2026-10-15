// =================================================================
// GOKTUNGU - ROTA TIPLERI ve ROTA YUKLE (v2.2.0)
// - ROTA YUKLE: Mission Planner (.waypoints, QGC WPL 110) ve
//   QGroundControl (.plan, JSON) gorev dosyalarini ice aktarir;
//   noktalar {lat, lon, irtifa, hiz} modeline indirgenir ve mevcut
//   duzenleme moduna yuklenir (kullanici gozden gecirip ESC ile kaydeder).
// - SPIRAL ROTA: parametre popup'i (nokta sayisi, cap, baslangic/bitis
//   yuksekligi, hiz, dron tipi) -> harita duzenleme modu -> ilk tiklama
//   spiral merkezini belirler ve noktalar otomatik uretilir.
//   Sabit kanat: tirmanma egimi siniri gozetilir; tur basina yukselme
//   asilirsa tur sayisi (dolayisiyla nokta basamaklari) otomatik artar.
// Bu dosya klasik script'tir; rotalar.js'ten SONRA yuklenmelidir.
// Entegrasyon: window.rotaDisVeriYukle / window.rotaSpiralModuBaslat
// (rotalar.js v2.2.0'da disa acilan kancalar).
// =================================================================
(function(){
  "use strict";

  function t(){ return (typeof D === "function") ? D() : {}; }
  function konsol(m){
    if (typeof konsolYaz === "function") konsolYaz(m);
    else console.log(m);
  }

  // ---------------------------------------------------------------
  // 1) ROTA YUKLE (Mission Planner .waypoints / QGC .plan)
  // ---------------------------------------------------------------
  // MAV_CMD sabitleri: konum tasiyan komutlar rota noktasina donusur
  const KONUMLU_KOMUTLAR = new Set([
    16,  // MAV_CMD_NAV_WAYPOINT
    17,  // NAV_LOITER_UNLIM
    18,  // NAV_LOITER_TURNS
    19,  // NAV_LOITER_TIME
    21,  // NAV_LAND
    22,  // NAV_TAKEOFF
    31,  // NAV_LOITER_TO_ALT
    82,  // NAV_SPLINE_WAYPOINT
  ]);

  // Mission Planner / ArduPilot .waypoints (QGC WPL 110):
  // idx\tcurrent\tframe\tcommand\tp1\tp2\tp3\tp4\tlat\tlon\talt\tautocontinue
  function waypointsParse(metin){
    const satirlar = metin.split(/\r?\n/);
    if (!satirlar.length || !/^QGC\s+WPL\s+\d+/i.test(satirlar[0].trim()))
      return { hata: "format" };
    const noktalar = [];
    let hizVarsayilan = null;
    for (let i = 1; i < satirlar.length; i++){
      const s = satirlar[i].trim();
      if (!s) continue;
      const p = s.split(/\t|\s+/);
      if (p.length < 12) continue;
      const cmd = parseInt(p[3]);
      const lat = parseFloat(p[8]);
      const lon = parseFloat(p[9]);
      const alt = parseFloat(p[10]);
      // DO_CHANGE_SPEED (178): p2 hiz (m/s)
      if (cmd === 178){
        const h = parseFloat(p[5]);
        if (isFinite(h) && h > 0) hizVarsayilan = h;
        continue;
      }
      if (!KONUMLU_KOMUTLAR.has(cmd)) continue;
      // Home satiri (idx 0) genelde frame 0/abs ve gorev disi: atla
      if (parseInt(p[0]) === 0) continue;
      if (!isFinite(lat) || !isFinite(lon)) continue;
      if (Math.abs(lat) < 1e-9 && Math.abs(lon) < 1e-9) continue;
      noktalar.push({ lat: lat, lon: lon,
                      irtifa: isFinite(alt) ? Math.round(alt) : 100,
                      hiz: null });
    }
    return { noktalar, hizVarsayilan };
  }

  // QGroundControl .plan (JSON): mission.items[].params[4..6] = lat,lon,alt
  function planParse(metin){
    let js;
    try { js = JSON.parse(metin); } catch(e){ return { hata: "format" }; }
    const gorev = js && js.mission;
    if (!gorev || !Array.isArray(gorev.items)) return { hata: "format" };
    const noktalar = [];
    let hizVarsayilan = (typeof gorev.cruiseSpeed === "number" && gorev.cruiseSpeed > 0)
      ? gorev.cruiseSpeed : null;
    function ekle(item){
      const cmd = item.command;
      const par = item.params || [];
      if (cmd === 178){
        const h = parseFloat(par[1]);
        if (isFinite(h) && h > 0) hizVarsayilan = h;
        return;
      }
      if (!KONUMLU_KOMUTLAR.has(cmd)) return;
      const lat = parseFloat(par[4]);
      const lon = parseFloat(par[5]);
      const alt = parseFloat(par[6]);
      if (!isFinite(lat) || !isFinite(lon)) return;
      if (Math.abs(lat) < 1e-9 && Math.abs(lon) < 1e-9) return;
      noktalar.push({ lat: lat, lon: lon,
                      irtifa: isFinite(alt) ? Math.round(alt) : 100,
                      hiz: null });
    }
    for (const item of gorev.items){
      if (item && item.type === "ComplexItem" &&
          Array.isArray(item.TransectStyleComplexItem &&
                        item.TransectStyleComplexItem.Items)){
        item.TransectStyleComplexItem.Items.forEach(ekle);
      } else if (item) {
        ekle(item);
      }
    }
    return { noktalar, hizVarsayilan };
  }

  function dosyaIsle(dosya){
    const okuyucu = new FileReader();
    okuyucu.onload = () => {
      const metin = String(okuyucu.result || "");
      const ad = (dosya.name || "").toLowerCase();
      let sonuc;
      if (ad.endsWith(".plan")) sonuc = planParse(metin);
      else if (ad.endsWith(".waypoints") || ad.endsWith(".mission") || ad.endsWith(".txt"))
        sonuc = waypointsParse(metin);
      else {
        // Uzanti belirsiz: icerikten tahmin et
        sonuc = metin.trimStart().startsWith("{")
          ? planParse(metin) : waypointsParse(metin);
      }
      if (sonuc.hata || !sonuc.noktalar || !sonuc.noktalar.length){
        konsol("[ROTA] Dosya okunamadi veya konumlu gorev noktasi yok: " + dosya.name);
        if (typeof uyariGoster === "function")
          uyariGoster(t().rotaYukleHata ||
            "Dosya okunamadı: geçerli Mission Planner (.waypoints) veya QGC (.plan) görevi bulunamadı.");
        else alert(t().rotaYukleHata ||
            "Dosya okunamadı: geçerli görev noktası bulunamadı.");
        return;
      }
      const hiz = sonuc.hizVarsayilan || 10;
      // Noktasal hizlar dosyada yoksa varsayilan hiz atanir
      sonuc.noktalar.forEach(n => { if (!n.hiz) n.hiz = hiz; });
      const ortIrtifa = Math.round(sonuc.noktalar.reduce((a, n) => a + n.irtifa, 0) /
                                   sonuc.noktalar.length);
      const isim = (dosya.name || "Yuklenen Rota").replace(/\.(waypoints|plan|mission|txt)$/i, "")
                    .slice(0, 60);
      if (typeof window.rotaDisVeriYukle === "function"){
        window.rotaDisVeriYukle({
          isim: isim, irtifa: ortIrtifa, hiz: hiz, noktalar: sonuc.noktalar,
        });
        konsol("[ROTA] '" + dosya.name + "' ice aktarildi: " +
               sonuc.noktalar.length + " nokta. Duzenleme modunda — ESC ile kaydedin.");
      }
    };
    okuyucu.readAsText(dosya);
  }

  const dosyaGiris = document.getElementById("rotaDosyaGiris");
  const mbYukle = document.getElementById("mbRotaYukle");
  if (dosyaGiris && mbYukle){
    mbYukle.addEventListener("click", (e) => {
      e.stopPropagation();
      // Menuyu kapat
      const mi = mbYukle.closest(".mb-item");
      if (mi) mi.classList.remove("acik");
      dosyaGiris.value = "";
      dosyaGiris.click();
    });
    dosyaGiris.addEventListener("change", () => {
      if (dosyaGiris.files && dosyaGiris.files[0]) dosyaIsle(dosyaGiris.files[0]);
    });
  }

  // ---------------------------------------------------------------
  // 2) SPIRAL ROTA
  // ---------------------------------------------------------------
  const perde   = document.getElementById("spiralModalPerde");
  if (!perde) return;
  const inpAd   = document.getElementById("spiralAd");
  const selTip  = document.getElementById("spiralDronTip");
  const inpN    = document.getElementById("spiralNokta");
  const inpCap  = document.getElementById("spiralCap");
  const inpBas  = document.getElementById("spiralBasYuk");
  const inpBit  = document.getElementById("spiralBitYuk");
  const inpHiz  = document.getElementById("spiralHiz");
  const lblN    = document.getElementById("spiralNoktaDeger");
  const lblCap  = document.getElementById("spiralCapDeger");
  const lblBas  = document.getElementById("spiralBasYukDeger");
  const lblBit  = document.getElementById("spiralBitYukDeger");
  const lblHiz  = document.getElementById("spiralHizDeger");
  const lblBilgi= document.getElementById("spiralBilgi");
  const lblHata = document.getElementById("spiralHata");

  // Dron tipi profilleri: sabit kanat icin maksimum tirmanma egimi
  // (yukseklik / yatay mesafe). Tipik kucuk sabit kanat IHA'larda surekli
  // tirmanista guvenli deger ~%8-10; kopterde pratikte sinirsiz kabul edilir.
  const TIP_PROFIL = {
    kopter: { egimMax: Infinity, minNoktaAraM: 5 },
    sabit:  { egimMax: 0.10,     minNoktaAraM: 60 },
  };

  // Spiral hesabi: verilen parametrelerle gereken tur sayisi ve gercek
  // nokta dagilimini hesaplar. Cap sabit oldugu icin uretim "dairesel
  // helis"tir: noktalar cember uzerinde esit aci adimlariyla ilerler,
  // irtifa lineer artar. Sabit kanatta tur basina yukselme siniri:
  //   dh_tur_max = cevre * egimMax
  function spiralHesapla(p){
    const r = Math.max(10, p.cap / 2);
    const cevre = 2 * Math.PI * r;
    const dH = p.bitYuk - p.basYuk;          // toplam yukselme (isaretli)
    const profil = TIP_PROFIL[p.tip] || TIP_PROFIL.kopter;
    // Gerekli minimum tur sayisi (sabit kanat egim siniri)
    let tur = 1;
    if (isFinite(profil.egimMax) && Math.abs(dH) > 0){
      tur = Math.max(1, Math.ceil(Math.abs(dH) / (cevre * profil.egimMax)));
    }
    // Nokta sayisi: kullanicinin istedigi; ancak nokta arasi yay mesafesi
    // profil minimumunun altina duserse nokta sayisi kirpilir
    let n = p.nokta;
    const toplamYay = cevre * tur;
    const maxNokta = Math.max(6, Math.floor(toplamYay / profil.minNoktaAraM));
    if (n > maxNokta) n = maxNokta;
    // Nokta basina yukselme ve aci adimi
    const dhNokta = dH / (n - 1);
    const aciAdim = (2 * Math.PI * tur) / (n - 1);
    const egim = (Math.abs(dH) > 0 && toplamYay > 0) ? Math.abs(dH) / toplamYay : 0;
    return { r, cevre, tur, n, dhNokta, aciAdim, egim,
             egimMax: profil.egimMax, toplamYay };
  }

  function bilgiTazele(){
    const p = parametreleriAl();
    const h = spiralHesapla(p);
    const d = t();
    const satirlar = [];
    satirlar.push((d.spiralBilgiTur || "Tur sayısı") + ": " + h.tur +
                  "   " + (d.spiralBilgiNokta || "Kullanılacak nokta") + ": " + h.n);
    satirlar.push((d.spiralBilgiYay || "Toplam yay") + ": " +
                  (h.toplamYay / 1000).toFixed(2) + " km   " +
                  (d.spiralBilgiEgim || "Tırmanma eğimi") + ": %" +
                  (h.egim * 100).toFixed(1));
    if (p.tip === "sabit" && isFinite(h.egimMax)){
      satirlar.push((d.spiralBilgiSabit ||
        "Sabit kanat: eğim %" ) + (h.egimMax * 100).toFixed(0) +
        (d.spiralBilgiSabit2 || " sınırına göre tur sayısı otomatik ayarlanır."));
    }
    if (h.n !== p.nokta){
      satirlar.push((d.spiralBilgiKirp ||
        "Not: nokta aralığı çok sıklaştığı için nokta sayısı ") + h.n +
        (d.spiralBilgiKirp2 || "'e düşürüldü."));
    }
    lblBilgi.textContent = satirlar.join("\n");
  }

  function parametreleriAl(){
    return {
      tip: selTip.value,
      nokta: parseInt(inpN.value),
      cap: parseFloat(inpCap.value),
      basYuk: parseFloat(inpBas.value),
      bitYuk: parseFloat(inpBit.value),
      hiz: parseFloat(inpHiz.value),
    };
  }

  function sliderTazele(){
    lblN.textContent = inpN.value;
    lblCap.textContent = inpCap.value + " m";
    lblBas.textContent = inpBas.value + " m";
    lblBit.textContent = inpBit.value + " m";
    lblHiz.textContent = parseFloat(inpHiz.value).toFixed(1) + " m/s (" +
      (parseFloat(inpHiz.value) * 3.6).toFixed(1) + " km/h)";
    bilgiTazele();
  }
  [inpN, inpCap, inpBas, inpBit, inpHiz].forEach(el =>
    el.addEventListener("input", sliderTazele));
  selTip.addEventListener("change", sliderTazele);

  function modalAc(){
    inpAd.value = "";
    lblHata.textContent = "";
    sliderTazele();
    perde.classList.remove("popup-gizli");
    setTimeout(() => inpAd.focus(), 60);
  }
  function modalKapat(){ perde.classList.add("popup-gizli"); }
  document.getElementById("btnSpiralModalKapat").addEventListener("click", modalKapat);
  document.getElementById("btnSpiralIptal").addEventListener("click", modalKapat);
  perde.addEventListener("click", (e) => { if (e.target === perde) modalKapat(); });

  const mbSpiral = document.getElementById("mbSpiralRota");
  if (mbSpiral){
    mbSpiral.addEventListener("click", (e) => {
      e.stopPropagation();
      const mi = mbSpiral.closest(".mb-item");
      if (mi) mi.classList.remove("acik");
      // Menu kapanma yarisini onlemek icin sonraki tick'te ac
      setTimeout(modalAc, 0);
    });
  }

  // Merkez (lat0, lon0) etrafinda dairesel helis noktalari uret.
  // Ilk nokta merkezden R uzaklikta, kuzey yonunde baslar.
  function spiralNoktalariUret(lat0, lon0, p){
    const h = spiralHesapla(p);
    const rad = Math.PI / 180;
    const R_DUNYA = 6371000;
    const noktalar = [];
    for (let i = 0; i < h.n; i++){
      const aci = i * h.aciAdim;                 // radyan, kuzeyden CW
      const kuzey = h.r * Math.cos(aci);
      const dogu  = h.r * Math.sin(aci);
      const lat = lat0 + (kuzey / R_DUNYA) / rad;
      const lon = lon0 + (dogu / (R_DUNYA * Math.cos(lat0 * rad))) / rad;
      const irtifa = Math.round(p.basYuk + h.dhNokta * i);
      noktalar.push({ lat: lat, lon: lon, irtifa: irtifa, hiz: p.hiz });
    }
    return noktalar;
  }

  document.getElementById("btnSpiralEkle").addEventListener("click", () => {
    const isim = inpAd.value.trim();
    if (!isim){
      lblHata.textContent = t().rotaHataAd || "Rota adı boş olamaz.";
      return;
    }
    const p = parametreleriAl();
    modalKapat();
    if (typeof window.rotaSpiralModuBaslat === "function"){
      window.rotaSpiralModuBaslat({
        isim: isim,
        parametreler: p,
        uret: (lat, lon) => spiralNoktalariUret(lat, lon, p),
      });
    }
  });
  inpAd.addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btnSpiralEkle").click();
  });
})();
