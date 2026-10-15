// FAZ19-IS71-K3-DRONKAMERA-SOKUM: dron karti kamera bolumu cagrilari kaldirildi
// FAZ18-IS27-28-30: ikon+metin dugmelerinde metin <span> icine
// sarildi. Sebep: dugme_birlik.css yalniz-ikon kurali
// `:has(> i):not(:has(> span))` bu dugmeleri 26px kareye
// zorluyordu ve metin tasiyordu. CSS EZILMEDI; sozlesmeye
// uyuldu. Yalniz-ikon dugmelere DOKUNULMADI.
// =================================================================
// GOKTUNGU - DRON HARITA VARLIKLARI + DRON KARTLARI + KOMUTLAR
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).

// m/s degerinin yanina " (X km/h)" ekler; sayi degilse bos dondurur
function kmhEk(ms){
  return (typeof ms === "number" && isFinite(ms))
    ? " (" + (ms * 3.6).toFixed(1) + " km/h)" : "";
}
// =================================================================
// UCGEN IKON
// ---------------------------------------------------------------
function ucgenIkon(renk){
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44" viewBox="0 0 44 44">
       <polygon points="22,3 38,39 22,30 6,39"
                fill="${renk}" stroke="#000" stroke-width="2"
                stroke-linejoin="round"/>
     </svg>`;
  return "data:image/svg+xml;base64," + btoa(svg);
}

// Yon gosteren ok/ucgen ikon (burnu YUKARI = kuzey; billboard.rotation ile dondurulur)
function yonUcgenIkon(renk){
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
       <polygon points="20,2 34,36 20,28 6,36"
                fill="${renk}" fill-opacity="0.92" stroke="#000" stroke-width="2"
                stroke-linejoin="round"/>
     </svg>`;
  return "data:image/svg+xml;base64," + btoa(svg);
}

// Cesium billboard.rotation: radyan, saat yonu TERSINE pozitif (ekran uzayi).
// Heading (kuzeyden saat yonunde derece) icin negatifi alinir.
function headingRotasyon(headingDerece){
  return -Cesium.Math.toRadians(headingDerece || 0);
}

// Bir noktadan bearing yonunde m metre otelenmis koordinat (kucuk mesafe yaklastirmasi)
function bearingOffset(lat, lon, bearingDerece, mesafeM){
  const R = 6371000;
  const br = bearingDerece * Math.PI / 180;
  const dLat = (mesafeM * Math.cos(br)) / R * (180 / Math.PI);
  const dLon = (mesafeM * Math.sin(br)) / (R * Math.cos(lat * Math.PI / 180)) * (180 / Math.PI);
  return [lat + dLat, lon + dLon];
}

// Yon cizgisi uzunlugu: hizla orantili (dur haldeyken kisa, hizliyken uzun)
function yonCizgiUzunluk(hizMs){
  const h = Math.max(0, hizMs || 0);
  return Math.min(200, 40 + h * 12);   // 40 m taban, hiz basina +12 m, maks 200 m
}

// 3D model oryantasyonu: heading (kuzeyden CW), pitch (burun yukari +),
// roll (saga yatis +) derece cinsinden telemetriden gelir.
// glTF modelde burun -Z'de; Cesium glTF donusumunde bu +X (heading yonu) olur.
function dronOryantasyon(pos, headingDeg, pitchDeg, rollDeg){
  const hpr = new Cesium.HeadingPitchRoll(
    Cesium.Math.toRadians(headingDeg || 0),
    Cesium.Math.toRadians(pitchDeg || 0),
    Cesium.Math.toRadians(rollDeg || 0));
  return Cesium.Transforms.headingPitchRollQuaternion(pos, hpr);
}

// Tip basina renkler (harita ikonu + rozet ayni kaynagi kullanir)
const TIP_RENKLERI = {
  koyu: { INTERCEPTOR:"#35d0ff", KAMIKAZE:"#ff5d5d" },
  acik: { INTERCEPTOR:"#0077b6", KAMIKAZE:"#c22626" },
};
let aktifTema = "koyu";
function tipRengi(tip){
  return TIP_RENKLERI[aktifTema][tip]
      || (aktifTema === "koyu" ? "#9aa7b4" : "#5c6b7a");  // bilinmeyen tip
}
const varliklar = {};
// GRCOFF: dron UID ile bağlı ve aktif olan yerel kamera için yalnız görsel
// önizleme. Bu katman komut üretmez; tıklama ortak kamera izleme penceresini açar.
const dronKameraOnizlemeler = {}; // sysid -> DOM kapsayıcısı
let dronKameraOnizlemeKuruldu = false;
function dronKameraOnizlemeSil(sysid){
  const sid = String(sysid);
  const el = dronKameraOnizlemeler[sid];
  if (el) el.remove();
  delete dronKameraOnizlemeler[sid];
}
function dronKameraOnizlemeKonumla(){
  if (typeof viewer === "undefined" || !viewer || !viewer.scene) return;
  for (const [sid, el] of Object.entries(dronKameraOnizlemeler)){
    const ent = varliklar[sid];
    let pos = ent && ent.position;
    if (pos && typeof pos.getValue === "function") pos = pos.getValue(Cesium.JulianDate.now());
    if (!pos){ el.style.display = "none"; continue; }
    const p = Cesium.SceneTransforms.wgs84ToWindowCoordinates(viewer.scene, pos);
    const c = viewer.scene.canvas;
    if (!p || p.x < -120 || p.y < -100 || p.x > c.clientWidth + 120 ||
        p.y > c.clientHeight + 100){
      el.style.display = "none";
      continue;
    }
    el.style.display = "block";
    el.style.transform = "translate(" + Math.round(p.x + 24) + "px," +
      Math.round(p.y - 32) + "px)";
  }
}
function dronKameraOnizlemeKur(){
  if (dronKameraOnizlemeKuruldu || typeof viewer === "undefined" || !viewer || !viewer.scene) return;
  dronKameraOnizlemeKuruldu = true;
  viewer.scene.postRender.addEventListener(dronKameraOnizlemeKonumla);
}
function dronKameraOnizlemeTazele(d){
  const sid = String(d && d.sysid);
  const uid = String((d && (d.uid || d.dron_uid)) || "").trim();
  const kam = uid ? (window._kameralarSon || []).find((k) =>
    String((k && k.dron_uid) || "").trim() === uid) : null;
  const aktif = kam && typeof window.kameraIzlemeAktifMi === "function" &&
    window.kameraIzlemeAktifMi(kam.id);
  // v2.5.24: Harita küçük önizlemesi yalnız görüntü hedefi 'harita' iken
  // (tek konumda gösterim; yüzen/panel/tam ekran seçiliyse haritada çizilmez).
  // v2.4.222: goruntu konumu secenegi kalkti; oynayan kamera haritada DA gosterilir
  const haritaHedef = !!kam;
  if (!sid || !d || !d.baglanti || !kam || !aktif || !haritaHedef || !varliklar[sid]){
    dronKameraOnizlemeSil(sid);
    return;
  }
  const alan = document.getElementById("haritaAlan");
  if (!alan || typeof window.kameraOnizlemeUrl !== "function") return;
  let el = dronKameraOnizlemeler[sid];
  if (!el){
    el = document.createElement("button");
    el.type = "button";
    el.className = "dron-kamera-onizleme";
    el.title = "Canlı kamera görüntüsünü aç";
    const img = document.createElement("img");
    img.alt = "Dron kamerası canlı önizleme";
    img.decoding = "async";
    const etiket = document.createElement("span");
    etiket.textContent = "CANLI";
    el.append(img, etiket);
    el.title = "Çift tıklayın: yüzen panelde aç";
    el.addEventListener("click", (ev) => {
      // Kullanici istegi: harita onizlemesine TIKLAYINCA yuzen pencere acilir.
      ev.preventDefault();
      ev.stopPropagation();
      const kameraId = Number(el.dataset.kameraId);
      if (Number.isFinite(kameraId) && typeof window.kameraIzlemeAc === "function")
        window.kameraIzlemeAc(kameraId);
    });
    // v2.4.164: Kullanıcı isteği — haritadaki videoya ÇİFT TIK -> yüzen panel.
    el.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const kameraId = Number(el.dataset.kameraId);
      if (!Number.isFinite(kameraId)) return;
      if (typeof window.kameraGoruntuHedefiAyarla === "function")
        window.kameraGoruntuHedefiAyarla(kameraId, "yuzen");
      else if (typeof window.kameraIzlemeAc === "function")
        window.kameraIzlemeAc(kameraId);
    });
    alan.appendChild(el);
    dronKameraOnizlemeler[sid] = el;
  }
  const kameraId = Number(kam.id);
  if (Number(el.dataset.kameraId) !== kameraId){
    el.dataset.kameraId = String(kameraId);
    // URL yalnız uygulamanın kendi /kamera/<id> vekilidir.
    const im = el.querySelector("img");
    im.onerror = () => { el.classList.add("kam-hata"); el.setAttribute("data-kam-hata", (typeof D === "function" && D().kamBaglantiYok) || "BAĞLANTI YOK"); };
    im.onload = () => { el.classList.remove("kam-hata"); el.removeAttribute("data-kam-hata"); };
    im.src = window.kameraOnizlemeUrl(kameraId);
  }
  dronKameraOnizlemeKur();
  dronKameraOnizlemeKonumla();
}
window.dronKameraHaritaOnizlemeTazele = function(){
  Object.values(sonVeri).forEach((veri) => dronKameraOnizlemeTazele(veri));
  dronKameraOnizlemeKonumla();
};

// v2.5.24: Dron kartındaki kamera kontrol satırı. Drona bağlı (dron_uid)
// yerel kamera varsa: Kamera Başlat/Durdur + görüntü hedefi + Yapay Zeka
// Ayarları düğmeleri. Komut üretmez; yalnız yerel görüntü/AI arayüzüdür.
function dronBagliKamera(d){
  const uid = String((d && (d.uid || d.dron_uid)) || "").trim();
  if (!uid) return null;
  return (window._kameralarSon || []).find((k) =>
    String((k && k.dron_uid) || "").trim() === uid) || null;
}
function dronKartKameraSatirTazele(kart, d){
  const satir = kart && kart.kok && kart.kok._kameraSatir;
  if (!satir) return;
  const kam = dronBagliKamera(d);
  if (!kam){
    satir.classList.add("gizli");
    satir.innerHTML = "";
    kart._kamId = null;
    return;
  }
  satir.classList.remove("gizli");
  // Bağlı kamera değiştiyse satırı yeniden kur (odak sıçramasın diye
  // yalnız değişimde).
  if (kart._kamId !== kam.id){
    kart._kamId = kam.id;
    satir.innerHTML = "";
    const ad = document.createElement("span");
    ad.className = "dk-kam-ad";
    ad.innerHTML = "<i class='fa-solid fa-video'></i> " +
      String(kam.isim || ("#" + kam.id)).replace(/[<>&]/g, "");
    const play = document.createElement("button");
    play.type = "button";
    play.className = "dk-kam-play";
    play.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const oyn = typeof window.kameraIzlemeAktifMi === "function" &&
        window.kameraIzlemeAktifMi(kam.id);
      if (oyn && typeof window.kameraIzlemeDurdur === "function")
        window.kameraIzlemeDurdur(kam.id);
      else if (typeof window.kameraHaritadaOynat === "function")
        window.kameraHaritadaOynat(kam.id);
      setTimeout(() => dronKartKameraSatirDurum(kart, kam.id), 150);
    });
    // v2.4.158: Kontroller taşmasın diye görüntü hedefi + AI ayarları bir
    // "⋯" açılır menüsüne konur. Ad + Başlat görünür kalır.
    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.className = "dk-kam-menu-btn";
    menuBtn.title = "Kamera seçenekleri";
    menuBtn.innerHTML = "<i class='fa-solid fa-ellipsis-vertical'></i>";
    const menu = document.createElement("div");
    menu.className = "dk-kam-menu gizli";
    if (typeof window.kameraGoruntuHedefSecici === "function"){
      const gh = document.createElement("div");
      gh.className = "dk-kam-menu-satir";
      const et = document.createElement("span");
      et.className = "dk-kam-menu-etiket";
      et.textContent = "Görüntü konumu";
      gh.append(et, window.kameraGoruntuHedefSecici(kam.id));
      menu.appendChild(gh);
    }
    if (typeof window.kameraAiAyarButonu === "function"){
      const ai = document.createElement("div");
      ai.className = "dk-kam-menu-satir";
      const aiBtn = window.kameraAiAyarButonu(kam.id, "dk-kam-ai");
      // metinli göster
      aiBtn.innerHTML = "<i class='fa-solid fa-robot'></i><span>Yapay Zeka Ayarları</span>";
      aiBtn.classList.add("dk-kam-menu-ai");
      ai.appendChild(aiBtn);
      menu.appendChild(ai);
    }
    menuBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const acik = !menu.classList.contains("gizli");
      // diğer açık menüleri kapat
      document.querySelectorAll(".dk-kam-menu").forEach((m) => m.classList.add("gizli"));
      menu.classList.toggle("gizli", acik);
    });
    // dışarı tıklayınca kapan
    if (!kart._kamMenuKapat){
      kart._kamMenuKapat = (ev) => {
        if (!satir.contains(ev.target)) menu.classList.add("gizli");
      };
      document.addEventListener("click", kart._kamMenuKapat);
    }
    const sarmal = document.createElement("div");
    sarmal.className = "dk-kam-menu-sarmal";
    sarmal.append(menuBtn, menu);
    satir.append(ad, play, sarmal);
    kart._kamPlay = play;
  }
  dronKartKameraSatirDurum(kart, kam.id);
}
function dronKartKameraSatirDurum(kart, kamId){
  const play = kart && kart._kamPlay;
  if (!play) return;
  const oyn = typeof window.kameraIzlemeAktifMi === "function" &&
    window.kameraIzlemeAktifMi(kamId);
  play.classList.toggle("aktif", !!oyn);
  play.innerHTML = oyn
    ? "<i class='fa-solid fa-stop'></i><span>Durdur</span>"
    : "<i class='fa-solid fa-play'></i><span>Başlat</span>";
}
// Kamera listesi/oynatma değişince tüm kartların satırını tazele.
window.dronKartKameraTazeleTum = function(){
  Object.entries(dronKartlar || {}).forEach(([sid, kart]) => {
    const d = sonVeri[sid];
    if (d) dronKartKameraSatirTazele(kart, d);
  });
};
let ilkOdak = false;
const sonVeri = {};

// IS99: Drona bağlı Görüntü Köprüsü kamerasının son onaylı geçmiş karesi.
// Görüntü yalnız kısa ömürlü, imzalı App URL'sinden yüklenir; base64/ham kare
// WebSocket'e geri konulmaz. Ayrı Cesium billboard ana dron konumunu izler.
const dronGoruntuVarliklari = {};  // sysid -> Cesium Entity
const dronGoruntuSonKare = {};     // kalıcı dron uid/id -> kare metadata
const dronGoruntuUidSysid = new Map();
const dronGoruntuIdSysid = new Map();
const DRON_GORUNTU_TTL_MS = 6500;
const DRON_GORUNTU_SAYDAM =
  "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";

function dronGoruntuAnahtar(d){
  if (!d) return "";
  // Kalıcı DB ID ile canlı telemetri ID alanları aynı kimlik uzayı değildir.
  return String(d.uid || d.dron_uid || "").trim();
}

function dronGoruntuEslemeGuncelle(dronlar){
  dronGoruntuUidSysid.clear();
  dronGoruntuIdSysid.clear();
  const uidAday = new Map();
  const idAday = new Map();
  const sysidSayisi = new Map();
  for (const d of Array.isArray(dronlar) ? dronlar : []){
    const uid = String((d && d.uid) || "").trim();
    const did = String((d && d.id) || "").trim();
    const sidSayi = Number(d && d.sysid);
    if (!uid || !did || !Number.isInteger(sidSayi) || sidSayi < 1 || sidSayi > 255)
      continue;
    const sid = String(sidSayi);
    sysidSayisi.set(sid, (sysidSayisi.get(sid) || 0) + 1);
    if (!uidAday.has(uid)) uidAday.set(uid, []);
    if (!idAday.has(did)) idAday.set(did, []);
    uidAday.get(uid).push(sid);
    idAday.get(did).push(sid);
  }
  for (const [uid, sidler] of uidAday.entries()){
    if (sidler.length === 1 && sysidSayisi.get(sidler[0]) === 1)
      dronGoruntuUidSysid.set(uid, sidler[0]);
  }
  for (const [did, sidler] of idAday.entries()){
    if (sidler.length === 1 && sysidSayisi.get(sidler[0]) === 1)
      dronGoruntuIdSysid.set(did, sidler[0]);
  }
  const gorulen = new Set();
  for (const kare of Object.values(dronGoruntuSonKare)){
    const kid = String((kare && (kare.id || kare.ts)) || "");
    if (!kare || gorulen.has(kid)) continue;
    gorulen.add(kid);
    dronGoruntuKareIsle(kare);
  }
}
window.dronGoruntuEslemeGuncelle = dronGoruntuEslemeGuncelle;

function dronGoruntuSysidBul(kare){
  const uid = String((kare && kare.dron_uid) || "").trim();
  const adaylar = new Set();

  // IS109/2.4.138: Kalıcı PostgreSQL `dron_id` ile canlı telemetrideki
  // herhangi bir `id` alanı aynı kimlik uzayı değildir. Bu nedenle kamera
  // karesi yalnız donanımsal UID üzerinden eşlenir; ID veya paket SYSID'si
  // tek başına hiçbir zaman yetki vermez. UID yoksa kapalı davranılır.
  if (!uid) return "";
  if (dronGoruntuUidSysid.has(uid))
    adaylar.add(dronGoruntuUidSysid.get(uid));

  // Canlı paket SYSID'si ancak o SYSID'nin taze telemetri nesnesinde aynı
  // donanımsal UID açıkça varsa aday olabilir. Böylece başlangıç eşleme
  // yanıtı kaçsa bile akış çalışır; UID uyuşmazlığı veya eksikliği reddedilir.
  const paketSidSayi = Number(kare && kare.sysid);
  if (Number.isInteger(paketSidSayi) && paketSidSayi >= 1 && paketSidSayi <= 255){
    const paketSid = String(paketSidSayi);
    const canli = sonVeri[paketSid];
    const canliUid = String((canli && (canli.uid || canli.dron_uid)) || "").trim();
    if (canliUid && canliUid === uid) adaylar.add(paketSid);
  }

  for (const [sid, d] of Object.entries(sonVeri)){
    const duid = String((d && (d.uid || d.dron_uid)) || "").trim();
    if (duid && duid === uid) adaylar.add(String(sid));
  }
  return adaylar.size === 1 ? Array.from(adaylar)[0] : "";
}

function dronGoruntuKareYerelZamanla(kare){
  if (!kare || typeof kare !== "object") return kare;
  if (Number.isFinite(Number(kare._yerel_alim_ms))) return kare;
  const yasVar = kare.yas_ms !== null && kare.yas_ms !== undefined;
  const yas = yasVar ? Number(kare.yas_ms) : NaN;
  if (Number.isFinite(yas) && yas >= 0){
    kare._yerel_alim_ms = Date.now() - yas;
    return kare;
  }
  const alisVar = kare.alis_ts !== null && kare.alis_ts !== undefined;
  const alis = alisVar ? Number(kare.alis_ts) : NaN;
  const ts = Number(kare.ts);
  if (Number.isFinite(alis) && alis > 0)
    kare._yerel_alim_ms = alis * 1000;
  else if (Number.isFinite(ts) && ts > 0)
    kare._yerel_alim_ms = ts * 1000;
  return kare;
}

function dronGoruntuKareTazeMi(kare){
  const yerel = Number(kare && kare._yerel_alim_ms);
  if (Number.isFinite(yerel))
    return Date.now() - yerel <= DRON_GORUNTU_TTL_MS;
  const alisVar = kare && kare.alis_ts !== null && kare.alis_ts !== undefined;
  const alis = alisVar ? Number(kare.alis_ts) : NaN;
  if (Number.isFinite(alis) && alis > 0)
    return Math.abs(Date.now() - alis * 1000) <= DRON_GORUNTU_TTL_MS;
  const ts = Number(kare && kare.ts);
  return Number.isFinite(ts) && Math.abs(Date.now() - ts * 1000) <= DRON_GORUNTU_TTL_MS;
}

function dronGoruntuUrlCoz(url){
  const ham = String(url || "").trim();
  if (!ham) return "";
  try {
    // IS109/2.4.139: App iki güvenli dağıtım yolunda çalışır:
    //   https://app.goktungu.com/       -> /api/app/goruntu_kare
    //   https://goktungu.com/app/       -> /app/api/app/goruntu_kare
    // Sunucu kök-bağıl `/api/...` üretir. Yalnız `location.origin` tabanı
    // kullanmak ikinci dağıtımda isteği yanlışlıkla ana sitenin `/api/`
    // yoluna gönderip 404 üretiyordu. API parçası etkin App köküne bağlanır;
    // başka origin'e yönelen URL kapalı biçimde reddedilir.
    const altYol = /^\/app(?:\/|$)/.test(String(window.location.pathname || ""));
    const taban = new URL(altYol ? "/app/" : "/", window.location.origin);
    const cozulmus = new URL(ham.replace(/^\/+/, ""), taban);
    return cozulmus.origin === window.location.origin ? cozulmus.href : "";
  } catch (_e) {
    return "";
  }
}
window.dronGoruntuUrlCoz = dronGoruntuUrlCoz;

function dronGoruntuTuval(url, renk, tamam){
  const img = new Image();
  let bitti = false;
  const bitir = (sonuc) => {
    if (bitti) return;
    bitti = true;
    clearTimeout(zamanAsimi);
    img.onload = null;
    img.onerror = null;
    tamam(sonuc);
  };
  // Askıda kalan tek bir JPEG isteği sonraki 1 FPS karelerin tamamını
  // sonsuza kadar engellememeli. Süre dolunca kuyruk en yeni kareyle sürer.
  const zamanAsimi = setTimeout(() => bitir(null), 4500);
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = 96; c.height = 96;
    const x = c.getContext("2d");
    const tema = getComputedStyle(document.documentElement);
    const arka = tema.getPropertyValue("--panel").trim();
    if (arka) x.fillStyle = arka;
    x.fillRect(0, 0, 96, 96);
    const oran = Math.max(92 / img.naturalWidth, 92 / img.naturalHeight);
    const w = img.naturalWidth * oran, h = img.naturalHeight * oran;
    x.drawImage(img, (96 - w) / 2, (96 - h) / 2, w, h);
    const vurgu = tema.getPropertyValue("--interceptor").trim();
    if (renk || vurgu) x.strokeStyle = renk || vurgu;
    x.lineWidth = 4;
    x.strokeRect(2, 2, 92, 92);
    bitir(c);
  };
  img.onerror = () => bitir(null);
  const cozulmusUrl = dronGoruntuUrlCoz(url);
  if (!cozulmusUrl) {
    bitir(null);
    return;
  }
  img.src = cozulmusUrl;
}

function dronGoruntuKareIsle(kare){
  kare = dronGoruntuKareYerelZamanla(kare);
  if (!kare || !kare.url || !dronGoruntuKareTazeMi(kare)) return;
  const uid = String(kare.dron_uid || "").trim();
  // Güvenlik: harita eşlemesi donanımsal UID olmadan hiçbir zaman açılmaz.
  if (!uid) return;
  dronGoruntuSonKare[uid] = kare;
  const sid = dronGoruntuSysidBul(kare);
  if (!sid || !sonVeri[sid] || !window.gecerliKonumMu(
      sonVeri[sid].lat, sonVeri[sid].lon)) return;
  const d = sonVeri[sid];
  const yuk = Math.max(0, typeof d.alt_rel === "number" ? d.alt_rel : 0);
  const pos = Cesium.Cartesian3.fromDegrees(d.lon, d.lat, yuk);
  const renk = dronRengi(d.sysid);
  const kareId = String(kare.id || kare.ts || "");
  let e = dronGoruntuVarliklari[sid];
  if (!e){
    e = viewer.entities.add({
      id: "dron_goruntu_" + sid,
      position: pos,
      billboard: {
        image: DRON_GORUNTU_SAYDAM,
        width: 96, height: 96,
        pixelOffset: new Cesium.Cartesian2(72, -58),
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new Cesium.NearFarScalar(500, 1.0, 25000, 0.55),
      },
    });
    e._kareId = "";
    dronGoruntuVarliklari[sid] = e;
  }
  e.position = pos;
  e._kareTsMs = Number(kare._yerel_alim_ms || 0);
  if (e._kareId === kareId || e._kareYukleniyorId === kareId) return;
  // IS109/2.4.137: 1 FPS akışta her yeni kare önceki JPEG yüklenmeden
  // gelirse `_kareYukleniyorId` sürekli değişiyor ve tüm onload sonuçları
  // geçersiz kalıyordu; billboard saydam görüntüden hiç çıkamıyordu.
  // Dron başına tek istek yürütülür, yalnız en yeni bekleyen metadata tutulur.
  if (e._kareYukleniyorId){
    e._kareBekleyen = kare;
    return;
  }
  e._kareYukleniyorId = kareId;
  dronGoruntuTuval(kare.url, renk, (tuval) => {
    const guncel = dronGoruntuVarliklari[sid];
    if (!guncel || guncel._kareYukleniyorId !== kareId) return;
    guncel._kareYukleniyorId = "";
    if (tuval){
      guncel._kareId = kareId;
      guncel.billboard.image = tuval;
    }
    const bekleyen = guncel._kareBekleyen;
    guncel._kareBekleyen = null;
    if (bekleyen && String(bekleyen.id || bekleyen.ts || "") !== guncel._kareId &&
        dronGoruntuKareTazeMi(bekleyen))
      dronGoruntuKareIsle(bekleyen);
  });
}
window.dronGoruntuKareIsle = dronGoruntuKareIsle;

function dronGoruntuKonumGuncelle(d, pos){
  const sid = String(d.sysid);
  const e = dronGoruntuVarliklari[sid];
  if (e){
    if (Date.now() - Number(e._kareTsMs || 0) > DRON_GORUNTU_TTL_MS){
      dronGoruntuSil(sid);
    } else {
      e.position = pos;
    }
  }
  if (dronGoruntuVarliklari[sid]) return;
  const a = dronGoruntuAnahtar(d);
  let kare = a ? dronGoruntuSonKare[a] : null;
  if (!kare){
    const gorulen = new Set();
    for (const aday of Object.values(dronGoruntuSonKare)){
      const kid = String((aday && (aday.id || aday.ts)) || "");
      if (!aday || gorulen.has(kid)) continue;
      gorulen.add(kid);
      if (dronGoruntuSysidBul(aday) === sid){ kare = aday; break; }
    }
  }
  if (kare) dronGoruntuKareIsle(kare);
}

function dronGoruntuSil(sysid){
  const sid = String(sysid);
  if (dronGoruntuVarliklari[sid]){
    viewer.entities.remove(dronGoruntuVarliklari[sid]);
    delete dronGoruntuVarliklari[sid];
  }
}

// IS99: Geçmiş Yöneticisi oynatılırken uçuş zamanına en yakın, fakat
// gelecekten olmayan kamera karesi hareketli dron ikonuna bağlı ayrı bir
// Cesium billboardunda gösterilir. Kareler yalnız süreli imzalı URL'dir;
// JPEG WebSocket içine konulmaz.
const dronGoruntuGecmisDurum = {
  kareler: [], ucus: null, sonId: "", yama: false, varlik: null,
};

function dronGoruntuGecmisVarlik(pos){
  const d = dronGoruntuGecmisDurum;
  if (typeof _gecmisViewer === "undefined" || !_gecmisViewer) return null;
  let varMi = false;
  try { varMi = !!(d.varlik && _gecmisViewer.entities.contains(d.varlik)); }
  catch (_e) { varMi = false; }
  if (!varMi){
    let renk = dronTelemetriRengi();
    const dr = Array.isArray(_gecmisDronlar) && d.ucus
      ? _gecmisDronlar.find(x => x.anahtar === d.ucus.anahtar) : null;
    if (dr && dr.renk) renk = dr.renk;
    d.varlik = _gecmisViewer.entities.add({
      id: "gc_goruntu_kare",
      position: pos,
      billboard: {
        image: DRON_GORUNTU_SAYDAM,
        width: 96, height: 96,
        pixelOffset: new Cesium.Cartesian2(72, -58),
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new Cesium.NearFarScalar(500, 1.0, 25000, 0.55),
      },
      label: {
        text: "", font: "10px Consolas, monospace",
        fillColor: Cesium.Color.fromCssColorString(renk),
        showBackground: true,
        backgroundColor: Cesium.Color.BLACK.withAlpha(0.72),
        pixelOffset: new Cesium.Cartesian2(72, 0),
        verticalOrigin: Cesium.VerticalOrigin.TOP,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    d.varlik._kareId = "";
    d.varlik._kenarRenk = renk;
  }
  d.varlik.position = pos;
  d.varlik.show = true;
  return d.varlik;
}

function dronGoruntuGecmisKonum(idx){
  const d = dronGoruntuGecmisDurum;
  const noktalar = d.ucus && Array.isArray(d.ucus.noktalar) ? d.ucus.noktalar : [];
  if (!d.kareler.length || !noktalar.length){
    if (d.varlik) d.varlik.show = false;
    return;
  }
  const i = Math.max(0, Math.min(Number(idx) || 0, noktalar.length - 1));
  const nokta = noktalar[i];
  const hedefTs = Number(d.ucus.baslangic || 0) + Number(nokta[0] || 0);
  let lo = 0, hi = d.kareler.length - 1, sec = -1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1;
    if (Number(d.kareler[mid].ts || 0) <= hedefTs + 0.55){ sec = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  if (sec < 0){
    if (d.varlik) d.varlik.show = false;
    return;
  }
  const pos = Cesium.Cartesian3.fromDegrees(
    Number(nokta[2]), Number(nokta[1]), Math.max(0, Number(nokta[3]) || 0));
  const varlik = dronGoruntuGecmisVarlik(pos);
  if (!varlik) return;
  const kare = d.kareler[sec];
  const id = String(kare.id || kare.ts || "");
  const zaman = new Date(Number(kare.ts || 0) * 1000);
  varlik.label.text = "KAMERA • " + (isNaN(zaman.getTime()) ? "--:--:--" :
    zaman.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"}));
  if (varlik._kareId === id) return;
  varlik._kareId = id;
  d.sonId = id;
  dronGoruntuTuval(kare.url, varlik._kenarRenk, (tuval) => {
    const guncel = dronGoruntuGecmisDurum.varlik;
    if (tuval && guncel && guncel._kareId === id) guncel.billboard.image = tuval;
  });
}

window.dronGoruntuGecmisIsle = function(kareler, ucus){
  const d = dronGoruntuGecmisDurum;
  d.kareler = (Array.isArray(kareler) ? kareler : []).slice().sort(
    (a, b) => Number(a.ts || 0) - Number(b.ts || 0));
  d.ucus = ucus || null;
  d.sonId = "";
  d.varlik = null; // gcUcusCiz/gcHaritaTemizle önceki Cesium varlıklarını kaldırır.
  // Geçmiş modülü sayfa sonunda yüklenir. Fonksiyonu bir kez sararak
  // PLAY, slider ve programlı ilerlemenin hepsini aynı kare güncellemesine bağlarız.
  if (!d.yama && typeof window.gcOynaticiKonum === "function"){
    const asil = window.gcOynaticiKonum;
    window.gcOynaticiKonum = function(idx){
      const sonuc = asil.apply(this, arguments);
      dronGoruntuGecmisKonum(idx);
      return sonuc;
    };
    d.yama = true;
  }
  dronGoruntuGecmisKonum(0);
};

// Telemetri dronlari haritada RADAR HEDEFLERIYLE AYNI gorsel yapiyi kullanir
// (elmas ikon + ayni etiket duzeni + zemine kesikli dikey cizgi); tek fark MOR renk.
const DRON_TELEMETRI_RENK = { koyu: "#c07bff", acik: "#8a2be2" };
function dronTelemetriRengi(){ return DRON_TELEMETRI_RENK[aktifTema] || "#c07bff"; }

// Backend'den gelen kalici dron rengi (UID/ID eslesmeli); yoksa tema rengi
function dronRengi(sysid){
  const r = (window.dronRenkler || {})[String(sysid)];
  return r || dronTelemetriRengi();
}

// ---------------------------------------------------------------
// CANLI HAREKET IZI: dronun gecmis konumlarindan cizgi
// ---------------------------------------------------------------
const dronIzGecmisi = {};   // sysid -> [Cartesian3, ...]
const dronIzVarliklar = {}; // sysid -> polyline entity
const DRON_IZ_MAX_NOKTA = 2400;  // ~20 dk @ 2 Hz
const DRON_IZ_MIN_MESAFE = 1.0;  // m: bundan yakin ardisik noktalar eklenmez

function dronIzEkle(d, pos, renk){
  const sysid = d.sysid;
  if (!dronIzGecmisi[sysid]) dronIzGecmisi[sysid] = [];
  const dizi = dronIzGecmisi[sysid];
  // Ayni noktada beklerken cizgi sismesin
  if (dizi.length > 0){
    const son = dizi[dizi.length - 1];
    if (Cesium.Cartesian3.distance(son, pos) < DRON_IZ_MIN_MESAFE) return;
  }
  dizi.push(pos);
  if (dizi.length > DRON_IZ_MAX_NOKTA) dizi.shift();
  if (dizi.length < 2) return;
  const cRenk = Cesium.Color.fromCssColorString(renk).withAlpha(0.85);
  if (!dronIzVarliklar[sysid]){
    dronIzVarliklar[sysid] = viewer.entities.add({
      id: "dron_iz_" + sysid,
      polyline: {
        positions: new Cesium.CallbackProperty(() => dronIzGecmisi[sysid] || [], false),
        width: 1.5,   // IS160: iz cizgisi inceltildi (2.5 -> 1.5)
        material: cRenk,
        clampToGround: false,
      },
    });
  } else {
    dronIzVarliklar[sysid].polyline.material = cRenk;
  }
}

function dronIzSil(sysid){
  if (dronIzVarliklar[sysid]){
    viewer.entities.remove(dronIzVarliklar[sysid]);
    delete dronIzVarliklar[sysid];
  }
  delete dronIzGecmisi[sysid];
}

// GCS merkezine yatay mesafe (m) - radar MSF alaniyla ayni anlam
function dronMesafeM(lat, lon){
  if (!gcsKonum) return null;
  const R = 6371000, rad = Math.PI / 180;
  const dLat = (lat - gcsKonum.lat) * rad, dLon = (lon - gcsKonum.lon) * rad;
  const a = Math.sin(dLat/2)**2 +
    Math.cos(gcsKonum.lat*rad) * Math.cos(lat*rad) * Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// Radar hedef etiketiyle ayni bicimde dron etiketi uret
function dronEtiketi(d){
  const t = D();
  // Oncelik: kullanicinin verdigi isim (UID eslesmeli) > isim > tip > SYSID
  const ad = d.kullanici_isim || d.isim || d.tip || ("SYS" + d.sysid);
  const msf = dronMesafeM(d.lat, d.lon);
  const yuk = (typeof d.alt_rel === "number") ? d.alt_rel : d.alt_msl;
  const hiz = (typeof d.groundspeed === "number") ? d.groundspeed : 0;
  const yon = (typeof d.heading === "number") ? Math.round(d.heading) : "-";
  return "D" + d.sysid + " " + ad +
    "\n" + t.rhMesafe + ":" + (msf !== null ? Math.round(msf) : "-") + "m" +
    " " + t.rhYukseklik + ":" + Math.round(yuk || 0) + "m" +
    "\n" + t.rhHiz + ":" + hiz.toFixed(1) + "m/s (" + (hiz * 3.6).toFixed(1) + "km/h)" +
    " " + (t.rhAzimut || "AZM") + ":" + yon + "\u00b0";
}



// ---------------------------------------------------------------
// FAZ18-IS21B: KONUM DURUMU METNI
// `gecerliKonumMu` kapisi (satir ~196) gecersiz konumda sessizce
// `return` ediyordu: harita ikonu cizilmiyor ama kullaniciya SEBEP
// gosterilmiyordu. Faz 18 boyunca tekrarlanan "dron bagli ama ikon
// gelmiyor" sikayetinin teshis edilebilirligi bu yuzden yoktu.
//
// `gps_fix` ve `uydu` alanlari sunucudan zaten geliyor
// (goktungu/dron.py:542). Yeni sunucu alani gerekmez.
//
// MAVLink GPS_FIX_TYPE: 0=NO_GPS, 1=NO_FIX, 2=2D, 3=3D, 4=DGPS,
// 5=RTK_FLOAT, 6=RTK_FIXED.  0/1 -> konum cozumu YOK.
// ---------------------------------------------------------------
function dronKonumDurumu(d) {
  if (!d) return null;
  if (window.gecerliKonumMu(d.lat, d.lon)) return null;   // sorun yok
  const t = D();
  const fix = (typeof d.gps_fix === "number") ? d.gps_fix : -1;
  const uydu = (typeof d.uydu === "number" && d.uydu >= 0) ? d.uydu : null;
  if (fix >= 0 && fix <= 1) {
    // GPS henuz kilitlenmemis: uydu sayisi bilgilendirici.
    return (t.dkGpsBekleniyor || "GPS BEKLENİYOR") +
           (uydu !== null ? " (" + (t.dkUydu || "uydu") + ": " + uydu + ")" : "");
  }
  // GPS kilitli (fix >= 2) ama konum hala gecersiz: kestirim filtresi
  // henuz cozum uretmemis (SITL'de EKF origin verilmemis olabilir).
  return t.dkKonumYok || "KONUM YOK (EKF çözümü bekleniyor)";
}

// Baglanti kesilince 10 sn sonra silme zamanlayicilari
const dronSilmeTimer = {};

function varlikGuncelle(d){
  // Sol panel karti her durumda guncellenir (GPS fix olmasa bile)
  dronKartGuncelle(d);

  // Baglanti durumuna gore 10 sn silme mantigi (konumdan bagimsiz)
  if (d.baglanti) {
    if (dronSilmeTimer[d.sysid]) {
      clearTimeout(dronSilmeTimer[d.sysid]);
      delete dronSilmeTimer[d.sysid];
    }
  } else {
    if (!dronSilmeTimer[d.sysid]) {
      dronSilmeTimer[d.sysid] = setTimeout(() => {
        dronSil(d.sysid);
        delete dronSilmeTimer[d.sysid];
      }, 10000);
    }
  }

  // v2.4.42: HOME ikonu. Dronun KENDI konumundan bagimsizdir - arac
  // telemetri konumu vermese bile HOME bilinebilir, bu yuzden asagidaki
  // "gecerli konum sart" erken donusunden ONCE cagrilir.
  if (typeof window.dronHomeGuncelle === "function")
    window.dronHomeGuncelle(d);

  // Harita varligi icin gecerli konum sart
  if (!window.gecerliKonumMu(d.lat, d.lon)) {
    dronKameraOnizlemeSil(d.sysid);
    return;
  } /* FAZ18-IS29C */
  // v2.4.29: Yukseklik ZEMINE GORE (alt_rel) verilir ve konumlandirma
  // `heightReference: RELATIVE_TO_GROUND` ile yapilir. Onceki surumlerde
  // `fromDegrees(lon, lat, alt_rel)` ELIPSOID referansina yerlestiriyordu;
  // terrain acildiginda arazi yukseldigi icin (Ankara'da olculen deger
  // 787-962 m) ikon arazinin YUZLERCE METRE ALTINDA kaliyor ve kamera
  // dondukce perspektif projeksiyonunda kayiyordu (olculen kayma: kamera
  // acisina gore 263-8911 px). Ayrintili gerekce: js/prizma_ikon.js
  const yuk = Math.max(0, (typeof d.alt_rel === "number" ? d.alt_rel : 0));
  const pos = Cesium.Cartesian3.fromDegrees(d.lon, d.lat, yuk);
  dronGoruntuKonumGuncelle(d, pos);
  // Radar hedefleriyle AYNI gorsel: prizma + radar bicimli etiket + dikey cizgi
  // Renk: backend'den gelen kalici dron rengi (UID/ID eslesmeli)
  const renk = dronRengi(d.sysid);
  // Canli hareket izi (yalniz baglanti aktifken nokta eklenir)
  if (d.baglanti) dronIzEkle(d, pos, renk);
  const etiket = dronEtiketi(d);
  // Zemine kesikli dikey cizgi. v2.4.29: zemin ucu artik terrain'e oturur
  // (`clampToGround` ile alt uc araziye kenetlenir).
  const dikeyPoz = Cesium.Cartesian3.fromDegreesArrayHeights(
    [d.lon, d.lat, 0, d.lon, d.lat, yuk]);

  // Yon cizgisi: ikonun onunden heading yonunde uzanir (hizla orantili uzunluk)
  const hdg = (typeof d.heading === "number") ? d.heading : 0;
  const czUzun = yonCizgiUzunluk(d.groundspeed);
  const [yLat, yLon] = bearingOffset(d.lat, d.lon, hdg, czUzun);
  const yonPoz = Cesium.Cartesian3.fromDegreesArrayHeights(
    [d.lon, d.lat, yuk, yLon, yLat, yuk]);

  // v2.4.29: prizma ikon secenegi (varsayilan ACIK). Prizma gercek 3B
  // geometridir: dunya uzayinda doner, bu nedenle billboard'da gereken
  // kamera heading telafisi gerekmez.
  // v2.4.30: dron ikonu artik CIFT PIRAMIT (bipiramit / plumbob elmas).
  // v2.4.31: BASARIM — elmas artik ayri bir primitive DEGIL, entity'nin
  // `ellipsoid` ozelligidir (`slicePartitions:4` + `stackPartitions:2`
  // kare tabanli cift piramit verir). Ikon basina ayri cizim cagrisi
  // ortadan kalkti; ayrica `heightReference` Cesium tarafindan
  // yonetildigi icin terrain kaymasi elle zemin okumaya gerek kalmadan
  // onlenir. Renk dronun kalici rengidir.
  // `_bipiramit` alani geriye uyum icin korunur ve artik ENTITY'nin
  // kendisine isaret eder.
  const prizmaMod = (typeof window.ikonPrizmaMi === "function")
    ? window.ikonPrizmaMi() : true;
  const prizmaSecenek = { lat: d.lat, lon: d.lon, yuk: yuk, yon: hdg, renk: renk };

  if (!varliklar[d.sysid]) {
    const tanim = {
      id: "dron_" + d.sysid,
      position: pos,
      label: {
        // v2.4.202 (kullanici istegi): bilgi etiketi VARSAYILAN GIZLI;
        // fare ikonun uzerine gelince harita_hover.js acar.
        show: false,
        text: etiket,
        font: "bold 12px Consolas, monospace",
        fillColor: Cesium.Color.fromCssColorString(renk),
        style: Cesium.LabelStyle.FILL,
        showBackground: true,
        backgroundColor: Cesium.Color.BLACK.withAlpha(0.72),
        backgroundPadding: new Cesium.Cartesian2(7, 5),
        verticalOrigin: Cesium.VerticalOrigin.TOP,
        pixelOffset: new Cesium.Cartesian2(0, 18),
        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      polyline: {
        positions: dikeyPoz,
        width: 2,
        clampToGround: false,
        material: new Cesium.PolylineDashMaterialProperty({
          color: Cesium.Color.fromCssColorString(renk).withAlpha(0.9),
          dashLength: 12,
        }),
      },
    };
    if (!prizmaMod){
      tanim.billboard = {
        image: elmasIkon(renk),
        width: 30, height: 30,
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
    }
    if (prizmaMod && window.PrizmaIkon){
      // Elmas gosterimi entity TANIMINA girer; boylece entity tek
      // seferde tam halinde olusur (sonradan ozellik eklemek Cesium'da
      // gorsel bileseni yeniden kurdurur).
      tanim.ellipsoid = window.PrizmaIkon.elmasTanimi(prizmaSecenek);
      // FAZ18-IS7-IKON-MESAFE: ELMAS YALNIZ YAKIN GORUSTE.
      // Elmas METRE tabanlidir (radii 15/15/20.5), bu yuzden kamera
      // uzaklastikca kuculur. Olculen degerler (fovy 60, 1080 px):
      //   1500 m -> 18.7 px | 2500 m -> 11.2 px | 3000 m -> 9.4 px
      // Ilk dron odagi 3000 m oldugu icin (asagida flyTo) ikon
      // 9 piksellik bir lekeye duser ve arka planli etiket onu
      // gorsel olarak bastirir; kullaniciya "ikon yok" gibi gorunur.
      // Bu yuzden elmas yakin gorusle sinirlanir, uzakta yerini
      // asagidaki `point` alir (o PIKSEL tabanlidir).
      tanim.ellipsoid.distanceDisplayCondition =
        new Cesium.DistanceDisplayCondition(0, 2500);
      // Uzak gorus gosterimi: pixelSize PIKSEL cinsindendir ve
      // mesafeden BAGIMSIZDIR, bu nedenle her uzaklikta gorunur.
      // Gecis Cesium tarafinda yapilir -> her karede JS hesabi YOK,
      // v2.4.31 basarim kazanci korunur.
      tanim.point = {
        pixelSize: 14,
        color: Cesium.Color.fromCssColorString(renk),
        // Koyu cerceve: acik zemin ve uydu goruntusu uzerinde de
        // ayirt edilir kalmasini saglar.
        outlineColor: Cesium.Color.BLACK.withAlpha(0.85),
        outlineWidth: 2,
        // Elmasla AYNI yukseklik sozlesmesi (bkz. js/prizma_ikon.js).
        heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        distanceDisplayCondition:
          new Cesium.DistanceDisplayCondition(2500, 1.0e9),
        // Etiketle ayni davranis: arazi arkasinda kalsa da gorunur.
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      };
      tanim.position = window.PrizmaIkon.elmasKonumu(
        d.lat, d.lon, yuk, false, undefined);
      tanim.orientation = window.PrizmaIkon.elmasYonu(
        d.lat, d.lon, yuk, hdg, false, undefined);
    }
    varliklar[d.sysid] = viewer.entities.add(tanim);
    varliklar[d.sysid]._prizmaMod = prizmaMod;
    if (prizmaMod && window.PrizmaIkon){
      const v = varliklar[d.sysid];
      v._elmasRenk = renk;
      v._elmasAlfa = window.PrizmaIkon.ALFA;
      v._elmasZemine = false;
      v._bipiramit = v;      // geriye uyum: artik entity'nin kendisi
    }
    // Yon cizgisi ayri entity (ana entity'nin polyline'i dikey cizgi icin kullaniliyor)
    varliklar[d.sysid]._yonCizgi = viewer.entities.add({
      id: "dron_yon_" + d.sysid,
      polyline: {
        positions: yonPoz,
        width: 3,
        clampToGround: false,
        material: new Cesium.PolylineArrowMaterialProperty(
          Cesium.Color.fromCssColorString(renk).withAlpha(0.95)),
      },
    });
    // FAZ18-DRON-EKRAN-DISI: ILK DRON ODAGI DUZELTMESI.
    // Eskiden kosul yalnizca `!merkezVar` idi. FAZ18-IS5 pilot konum
    // yamasindan sonra genel `merkez_lat/lon` ayari da merkezVar'i
    // true yaptigi icin bu dal PRATIKTE HIC calismiyordu: bagli dron
    // gorunumun disinda kaliyor ve kullaniciya "ikon yok" gibi
    // gorunuyordu (olcum: dron 38.99/35.00, kamera 25.49/50.82).
    //
    // Yeni sozlesme: pilotun KENDI kayitli gorunumu varsa gorunum
    // korunur (kullanici tercihi ezilmez) -- bu durumda ekran kenari
    // gostergesi devreye girer (dron_ekran_disi.js). Pilotun hic
    // kaydi yoksa ilk bagli drona odaklanilir.
    var _pilotKaydi = false;
    try {
      _pilotKaydi = (typeof window.haritaPilotKaydiVar === "function")
        ? window.haritaPilotKaydiVar() : false;
    } catch (e) { _pilotKaydi = false; }
    if (!ilkOdak && !_pilotKaydi){
      ilkOdak = true;
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(d.lon, d.lat, 3000),
        duration: 2.0,
      });
    }
  } else {
    const e = varliklar[d.sysid];
    e.position = pos;
    e.label.text = etiket;
    e.polyline.positions = dikeyPoz;
    e.polyline.material = new Cesium.PolylineDashMaterialProperty({
      color: Cesium.Color.fromCssColorString(renk).withAlpha(0.9),
      dashLength: 12,
    });
    // Yon cizgisini guncelle
    if (e._yonCizgi){
      e._yonCizgi.polyline.positions = yonPoz;
      e._yonCizgi.polyline.material = new Cesium.PolylineArrowMaterialProperty(
        Cesium.Color.fromCssColorString(renk).withAlpha(d.baglanti ? 0.95 : 0.3));
    }
    // Baglanti kopuk: soluk goster (radar SUZULEN gibi) + renk tazele
    const alfa = d.baglanti ? 1.0 : 0.35;
    if (e.ellipsoid && window.PrizmaIkon){
      // v2.4.31: elmas her telemetri paketinde tazelenir (konum VE yon
      // degisir). Artik yalnizca ozellik atamalari yapilir; Matrix4
      // carpimi ve geometri yeniden uretimi YOKTUR. Renk yalnizca
      // gercekten degistiyse yazilir (gereksiz nesne ayirmayi onler).
      // DIKKAT: `e.position` bu dalda elmas konumu tarafindan yazilir;
      // yukaridaki `e.position = pos` atamasi merkez kaydirmasini
      // icermedigi icin uzerine yazilmasi GEREKLIDIR.
      window.PrizmaIkon.bpTazele(e, Object.assign({}, prizmaSecenek,
        { alfa: window.PrizmaIkon.ALFA * (d.baglanti ? 1.0 : 0.45) }));
    } else if (e.polygon){
      // Geriye uyum: eski prizma varliklari (kip gecisi oncesi)
      window.PrizmaIkon.tazele(e, prizmaSecenek);
      window.PrizmaIkon.alfaAyarla(e, renk, d.baglanti ? 1.0 : 0.45);
    } else if (e.billboard){
      e.billboard.image = elmasIkon(renk);
      e.billboard.color = Cesium.Color.WHITE.withAlpha(alfa);
    }
    // FAZ18-IS7-IKON-MESAFE: uzak gorus noktasi da tazelenir.
    // Renk dronun kalici rengidir; baglanti kopukken elmas ve
    // etiketle AYNI solma orani uygulanir (radar SUZULEN gibi).
    if (e.point){
      e.point.color = Cesium.Color.fromCssColorString(renk).withAlpha(alfa);
      e.point.outlineColor = Cesium.Color.BLACK.withAlpha(0.85 * alfa);
    }
    e.label.fillColor = Cesium.Color.fromCssColorString(renk).withAlpha(alfa);
  }
  // IS151: 3B ikon motoru. Acikken tipe gore ucak/multirotor rig'i kurulur
  // ve elmas (ellipsoid) gizlenir; kapaliyken rig silinip elmas geri gelir.
  try { dron3dUygula(d, varliklar[d.sysid], renk, hdg); } catch (eIk) {}
  dronKameraOnizlemeTazele(d);
}

// IS151: dronun 3B rig'ini kur/guncelle veya kapat
function dron3dUygula(d, e, renk, hdg){
  if (!e) return;
  const anaId = "dron_" + d.sysid + "__r3";
  const acik = (typeof window.ikon3dAcik === "function") ? window.ikon3dAcik() : false;
  if (acik && window.IkonMuh && window.IkonMuh.hazir()){
    // Eski gosterimi gizle: elmas billboard (varsayilan) VE/VEYA ellipsoid.
    if (e.billboard) e.billboard.show = false;
    if (e.ellipsoid) e.ellipsoid.show = false;
    window.IkonMuh.dron(anaId, {
      lat: d.lat, lon: d.lon, yuk: Math.max(0, (typeof d.alt_rel === "number" ? d.alt_rel : 0)),
      heading: (typeof d.heading === "number") ? d.heading : (hdg || 0),
      pitch: (typeof d.pitch === "number") ? d.pitch : 0,
      roll: (typeof d.roll === "number") ? d.roll : 0,
      renk: renk, aracTipi: d.arac_tipi,
    });
  } else {
    if (e.billboard) e.billboard.show = true;    // eski gosterimi geri getir
    if (e.ellipsoid) e.ellipsoid.show = true;
    if (window.IkonMuh) window.IkonMuh.sil(anaId);
  }
}

// IS151: 3B ikon kipi degisince tum dronlari yeniden ciz (aninda etki)
window.ikonModuTazele = function(){
  try {
    if (typeof sonVeri === "object" && sonVeri)
      for (const sid in sonVeri) if (sonVeri[sid]) varlikGuncelle(sonVeri[sid]);
  } catch (e) {}
  try { if (typeof window.eoIkon3dTazele === "function") window.eoIkon3dTazele(); } catch (e) {}
  try { if (typeof window.radarIkon3dTazele === "function") window.radarIkon3dTazele(); } catch (e) {}
};

function dronSil(sysid) {
  // Haritadan sil
  if (varliklar[sysid]) {
    if (varliklar[sysid]._yonCizgi) viewer.entities.remove(varliklar[sysid]._yonCizgi);
    // v2.4.31: elmas artik entity OZELLIGIDIR; entity kaldirilinca
    // kendiliginden gider. v2.4.30'daki acik primitive temizligi
    // gereksizlesti ve kaldirildi (o surumde atlanmasi sizintiya yol
    // aciyordu; artik boyle bir risk yoktur).
    viewer.entities.remove(varliklar[sysid]);
    delete varliklar[sysid];
  }
  // IS151: 3B rig'i de kaldir
  try { if (window.IkonMuh) window.IkonMuh.sil("dron_" + sysid + "__r3"); } catch (e) {}
  // Hareket izini ve drona bağlı küçük görüntü önizlemelerini de sil.
  dronIzSil(sysid);
  dronGoruntuSil(sysid);
  dronKameraOnizlemeSil(sysid);
  // v2.4.42: HOME ikonunu da kaldir (aksi halde dron listeden dustukten
  // sonra haritada sahipsiz bir ev bayragi kalirdi)
  if (typeof window.dronHomeSil === "function") window.dronHomeSil(sysid);
  // Sol panelden sil
  const kart = document.getElementById("dronKart_" + sysid);
  if (kart) kart.remove();
  // v2.4.249 (kullanici: ayni dron hem sanal dron kaydinda hem "Baglantisi
  // bilinmeyen"de, eski ACRO durumuyla): yuzen pencere acikken panelde
  // duran GOLGE satir (v2.4.224) ve varsa kayitli pencere konumu da
  // temizlenir; yalniz `#dronKart_<sysid>` silmek golgeyi birakiyordu.
  try {
    const k = dronKartlar[sysid];
    if (k && k.golge && k.golge.parentNode) k.golge.remove();
    if (k) { k.golge = null; k.golgeBaslik = null; }
  } catch (e) {}
  document.querySelectorAll('.dron-kart[data-sysid="' + sysid + '"], .dk-golge[data-sysid="' + sysid + '"]').forEach((el) => { try { el.remove(); } catch (e) {} });
  if (dronSilmeTimer[sysid]) { clearTimeout(dronSilmeTimer[sysid]); delete dronSilmeTimer[sysid]; }
  if (dronKartlar[sysid]) {
    // v2.4.2: kamera bolumu temizligi (video/proxy durdur)
    delete dronKartlar[sysid];
  }
  // Komut paneli artik sol panelin icinde, ekstra silmeye gerek yok
  // sonVeri'den sil
  delete sonVeri[sysid];
  // v2.4.33: bos durum notu artik her baglanti grubunun icinde
  if (typeof window.bagGruplariDoldur === "function")
    window.bagGruplariDoldur();
}

function tumDronlariTemizle() {
  // Tum dronlari haritadan ve sag panelden temizle
  for (const sysid of Object.keys(sonVeri)) {
    if (window._logDronAktif && window._logDronAktif[sysid]) continue;
    dronSil(parseInt(sysid));
  }
  // Silme zamanlayicilarini da iptal et
  for (const sysid of Object.keys(dronSilmeTimer)) {
    clearTimeout(dronSilmeTimer[sysid]);
    delete dronSilmeTimer[sysid];
  }
  // Aktif angajmanlari temizle
  for (const sid of Object.keys(aktifAngajmanlar)) delete aktifAngajmanlar[sid];
  // v2.4.33: bos durum notu artik her baglanti grubunun icinde
  if (typeof window.bagGruplariDoldur === "function")
    window.bagGruplariDoldur();
}

// ---------------------------------------------------------------
// SOL PANEL - DRON KARTLARI
// ---------------------------------------------------------------
const dronKartListesi = document.getElementById("dronKartListesi");
const dronKartlar = {};  // sysid -> {kok, icerik}

// v2.4.39: kart basligindaki ayir/yerlestir dugmesinin ikonu.
// Tek yerde tanimlanir: dugme uc noktada uretilir/tazelenir
// (olusturma + dronKartAyirToggle'in iki dali). Onceki surumlerde
// ikon uc yere ayri ayri gomuluydu ve degisiklik birini atlamaya
// acikti; sabit bunu yapisal olarak engeller.
const DK_KAPAT_IKON = "<i class='fa-solid fa-xmark'></i>";
// FAZ18-IS27-28-30: kart <-> pencere gecis dugmesinin ikonu artik
// DURUMA GORE degisir. Onceki surumde (v2.4.39) her iki durumda
// da carpi gosteriliyordu; kullanici buyult/kucult istedi.
// ISLEV DEGISMEDI - yalniz ikon. DK_KAPAT_IKON adi korundu.
// IS155: panel katla/ac dugmesi artik ac/kapa (chevron) ikonu.
//   acikken  -> yukari chevron (katla)
//   kapaliyken-> asagi chevron (ac)
const DK_BUYULT_IKON = "<i class='fa-solid fa-chevron-down'></i>";
const DK_KUCULT_IKON = "<i class='fa-solid fa-chevron-up'></i>";

function dronKartGuncelle(d) {
  try { if (window.telemetriKopruYayinla) window.telemetriKopruYayinla(d); } catch (e) {}
  let kart = dronKartlar[d.sysid];
  if (!kart) {
    // Yeni kart olustur
    const kok = document.createElement("div");
    kok.className = "dron-kart";
    kok.id = "dronKart_" + d.sysid;

    // Ayirt edici baslik: baglanti noktasi + D{sysid} | TIP/ISIM + menu + chevron
    const baslik = document.createElement("div");
    baslik.className = "dron-kart-baslik";
    const nokta = document.createElement("span");
    nokta.className = "dk-nokta";
    // Dron renk karesi (UID/ID eslesmeli kalici renk - haritadaki izle ayni)
    const renkKare = document.createElement("span");
    renkKare.className = "dk-renk-kare";
    const adSpan = document.createElement("span");
    adSpan.className = "dk-ad";
    // v2.4.32: baslik ozeti — irtifa + ucus kipi.
    // Kart KAPALIYKEN de gorunur; asil degeri budur. Kartlar
    // varsayilan olarak katlanmis geldigi icin operator paneli
    // acmadan irtifayi ve kipi gorur.
    const ozetSpan = document.createElement("span");
    ozetSpan.className = "dk-baslik-ozet";
    const ok = document.createElement("i");
    ok.className = "fa-solid fa-chevron-down dk-ok";
    // Ayir/yerlestir dugmesi: kart <-> tasinabilir popup gecisi
    // v2.4.39: IKON ARTIK CARPI (fa-xmark). Kullanici "dock panel
    // dugmesini paneli kapat dugmesine cevirelim, ikon carpi olsun,
    // BASTIGIMIZDA AYNI ISI YAPSIN" dedi -> islev DEGISMEDI, yalniz
    // ikon degisti. Bu bir "karti yok et" dugmesi DEGILDIR:
    //   panelde  -> karti ayirir (tasinabilir popup yapar)
    //   ayrikta  -> pencereyi kapatir, kart panele geri doner
    // Ikinci durum carpi ile dogal ortusur (pencere kapanir). Birinci
    // durumun anlami ipucu metninde (title) veriliyor; ikon iki durumda
    // da ayni kalir ki dugme yer degistirmis gibi gorunmesin.
    const btnAyir = document.createElement("button");
    btnAyir.className = "dk-ayir-btn";
    btnAyir.title = D().dkAyir;
    // FAZ18-IS27-28-30: panel icindeyken ikon BUYULT (ayri pencereye al)
    // v2.4.224 (kullanici istegi): panelde BUYULT dugmesi GORUNMEZ; karta
    // tiklamak yuzen paneli acar. Yuzen panelde bu dugme KAPAT'tir (carpi):
    // paneli kapatir, kart panele doner. Yaninda KUCULT: yalniz baslik kalir.
    btnAyir.innerHTML = DK_KAPAT_IKON;
    btnAyir.title = D().dkPencereKapat || "Pencereyi Kapat";
    btnAyir.addEventListener("click", (ev) => {
      ev.stopPropagation();
      dronKartAyirToggle(d.sysid);
    });
    const btnKucult = document.createElement("button");
    btnKucult.className = "dk-kucult-btn";
    btnKucult.title = D().dkYalnizBaslik || "Küçült (yalnız başlık)";
    btnKucult.innerHTML = DK_KUCULT_IKON;
    btnKucult.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const kucuk = kok.classList.toggle("dk-yalniz-baslik");
      btnKucult.innerHTML = kucuk ? DK_BUYULT_IKON : DK_KUCULT_IKON;
      btnKucult.title = kucuk ? (D().dkGeriBuyut || "Geri büyüt") : (D().dkYalnizBaslik || "Küçült (yalnız başlık)");
    });
    // Panel icinde basliga tiklamak yuzen paneli acar; zaten acik ise
    // (golge satir) pencere one alinir — bkz. dronKartAyirToggle.
    baslik.addEventListener("click", (ev) => {
      if (kok.classList.contains("ayrik")) return;
      if (ev.target.closest("button")) return;
      dronKartAyirToggle(d.sysid);
    });
    // v2.4.23: baslikteki uc nokta menu dugmesi KALDIRILDI.
    // Tum islemler kart icindeki "ISLEMLER" dugmesinden acilan
    // 3 sutunlu islem popup'inda toplanir (dkIslemlerPopupAc).
    // Joystick (manuel kontrol) anahtari - telemetri hucre stilinde
    const joyBtn = document.createElement("button");
    joyBtn.className = "dk-tel-hucre dk-hucre-btn dk-joy-btn";
    joyBtn.type = "button";
    joyBtn.title = D().dkManuelKontrol || "Manuel Kontrol (WASD + \u2191\u2193)";
    joyBtn.innerHTML = "<i class='fa-solid fa-gamepad'></i>" +
                       "<span class='dk-tel-deger dk-joy-durum'>" +
                       (D().dkKapaliEtiket || "KAPALI") + "</span>" +
                       "<span class='dk-tel-etiket'>" +
                       (D().dkJoyEtiket || "JOYSTICK") + "</span>";
    // Tiklama, telemetri kapsayicisinin surukle/tikla ayristirmasindan
    // data-islev="joystick" ile yonlendirilir (asagida atanir); boylece
    // dugme uzerinden de surukleyerek kaydirma calisir.
    baslik.appendChild(nokta);
    baslik.appendChild(adSpan);
    baslik.appendChild(ozetSpan);
    baslik.appendChild(btnKucult);
    baslik.appendChild(btnAyir);
    baslik.appendChild(ok);
    // FAZ18-IS27-28-30: KART KAPALI DOGAR. Kullanici "dron panelde
    // gorundugunde altindaki detaylar gorunmesin sadece header kismi
    // gorunsun" dedi. Baslik bilgisiz kalmaz: .dk-baslik-ozet ogesi
    // irtifa + ucus kipini gosterir (bkz. satir ~794 ozetSpan
    // guncellemesi), durum LED'i ve dron adi da baslikta.
    baslik.classList.add("kapali");
    // FAZ18-IS27-28-30: BASLIK TIKLAMA AC/KAPA KALDIRILDI.
    // Kullanici "dron panelde gorundugunde altindaki detaylar
    // gorunmesin sadece header kismi gorunsun, acilir kapanir olmasin"
    // dedi. Detaylara erisim yolu KAPANMIYOR: buyult dugmesi karti
    // ayri pencereye alir ve orada govde acilir (dronKartAyirToggle).
    // Ayrik moddaki CIFT TIK (kompakt gorunum) korundu - o davranis
    // panel ici kart icin gecerli degil.
    // v2.4.35: OK IKONU HER ZAMAN AC/KAPA YAPAR.
    // KUSUR: kart "ayrik" (tasinabilir popup) moda gecince yukaridaki
    // baslik click dinleyicisi erken cikiyordu (surukleme korunsun diye).
    // Ok ikonu basligin cocugu oldugu icin ona basmak da hicbir sey
    // yapmiyordu; ayrik modda katlama yalniz CIFT TIK ile ve farkli bir
    // mekanizmayla (kok.kompakt) mumkundu. Kullanici okun her iki modda
    // da paneli acip kapatmasini istiyor.
    // stopPropagation: basligin kendi click'i ikinci kez toggle etmesin.
    // FAZ18-IS27-28-30: OK IKONU AC/KAPA KALDIRILDI (ikon da gizlendi).
    // Panel ici kart artik acilir kapanir degil; ok ikonu islevsiz
    // kalacagi icin gorunurlukten cikarildi (CSS: .dk-ok display:none).
    // Ayrik moddaki kart icin kompakt gorunum CIFT TIK ile surer.
    // Ok ikonu uzerinde surukleme BASLAMAMALI: pointerdown yutulursa
    // click olayi hic olusmaz (asagida dronKartSurukleKur icinde
    // .dk-ok listeye eklendi), burada da guvence olarak durduruyoruz.
    ok.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); });
    ok.addEventListener("dblclick", (ev) => { ev.stopPropagation(); });
    // IS157: Ayrik (popup) modda basliga CIFT TIK artik COLLAPSE/EXPAND yapar
    // (yalniz baslik <-> tam panel). Eski "kompakt" gorunum yerine katla/ac
    // dugmesiyle (dk-yalniz-baslik) ayni davranis; ikon da senkronlanir.
    baslik.addEventListener("dblclick", (ev) => {
      if (!kok.classList.contains("ayrik")) return;
      ev.preventDefault(); ev.stopPropagation();
      const kucuk = kok.classList.toggle("dk-yalniz-baslik");
      if (kok._btnKucult) {
        kok._btnKucult.innerHTML = kucuk ? DK_BUYULT_IKON : DK_KUCULT_IKON;
        kok._btnKucult.title = kucuk ? (D().dkGeriBuyut || "Geri büyüt")
                                     : (D().dkYalnizBaslik || "Küçült (yalnız başlık)");
      }
    });
    // Ayrik moddayken basliktan surukleme
    dronKartSurukleKur(kok, baslik);
    kok._btnAyir = btnAyir;
    kok._btnKucult = btnKucult;

    // Govde = gostergeler + telemetri (dinamik) + aksiyon bari (SABIT)
    const govde = document.createElement("div");
    // FAZ18-IS27-28-30: govde gizli dogar (bkz. baslik.classList.add("kapali")).
    govde.className = "dron-kart-icerik gizli";
    // Renk gostergesi: icerik sol ust kosesinde (left:10px top:10px)
    renkKare.title = D().dkRenkIpucu || "Dron rengi (harita izi ile ayni)";
    // IS155: dron rengi karesi PFD ustunde bosluk yaratiyordu; gizlendi
    // (govde'ye eklenmez; referans korunur, renk atamasi zararsizdir).
    // Drona odaklan dugmesi: icerik sag ust kosesinde (renk karesinin simetrigi)
    const btnFokusKart = document.createElement("button");
    btnFokusKart.type = "button";
    btnFokusKart.className = "dk-fokus-btn";
    btnFokusKart.title = D().dkFokus || "Drona Fokuslan";
    btnFokusKart.innerHTML = "<i class='fa-solid fa-location-crosshairs'></i>";
    btnFokusKart.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      ev.stopPropagation(); ev.preventDefault();
      dronaGit(d.sysid);
    });
    // IS157: Fokus dugmesi kaldirildi (gereksiz) — GPS kutusuna tiklayinca
    // drona fokuslanilir. Buton olusturulur ama DOM'a EKLENMEZ (referans korunur).

    // --- v2.4.19: UCUSA HAZIR GOSTERGESI (kartin en ustu) ---
    // Tiklanirsa dronun bildirdigi hata/prearm mesajlari ayri panelde
    // listelenir (dkArmCheckPopupAc).
    // v2.4.23: rozet %50 genislik; yanina %50 genislikte ISLEMLER
    // dugmesi gelir. Rozette YALNIZ durum metni gosterilir (hata/uyari
    // sayaci kaldirildi; ayrintilar ARM CHECK panelinde).
    const hazirSatir = document.createElement("div");
    hazirSatir.className = "dk-ust-satir";
    const hazirRozet = document.createElement("button");
    hazirRozet.type = "button";
    hazirRozet.className = "dk-hazir-rozet bilinmiyor";
    // IS155: ikon/ok yok — yalniz durum metni (GPS/mod kutulari gibi sade)
    hazirRozet.innerHTML = "<span class='dk-hazir-metin'>—</span>";
    hazirRozet.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 && ev.pointerType === "mouse") return;
      ev.stopPropagation(); ev.preventDefault();
      if (typeof dkArmCheckPopupAc === "function")
        dkArmCheckPopupAc(d.sysid, {x: ev.clientX, y: ev.clientY});
    });
    const islemBtn = document.createElement("button");
    islemBtn.type = "button";
    islemBtn.className = "dk-islem-btn";
    islemBtn.title = D().dkIslemler || "\u0130\u015flemler";
    // IS155: ikon yok \u2014 yalniz metin
    islemBtn.innerHTML =
      "<span class='dk-islem-metin'>" +
      (D().dkIslemler || "\u0130\u015eLEMLER").toUpperCase() + "</span>";
    islemBtn.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 && ev.pointerType === "mouse") return;
      ev.stopPropagation(); ev.preventDefault();
      if (typeof window.dkIslemlerPopupAc === "function")
        window.dkIslemlerPopupAc(d.sysid, {x: ev.clientX, y: ev.clientY});
    });
    hazirSatir.appendChild(hazirRozet);
    hazirSatir.appendChild(islemBtn);
    govde.appendChild(hazirSatir);

    // --- UCUS GOSTERGELERI (jquery-flight-indicators) ---
    const gostergeler = dronGostergeleriOlustur(d.sysid);

    const telemetri = document.createElement("div");
    telemetri.className = "dk-telemetri";
    // Hucre tiklama + SURUKLE-KAYDIR (drag-to-scroll):
    // - pointerdown aninda hucre hedefi kaydedilir (innerHTML yenilenmesi
    //   "click" olayini kaybettirdigi icin click'e guvenilmez).
    // - Fare/parmak 6 px'ten fazla yatay hareket ederse SURUKLEME sayilir:
    //   kapsayici scrollLeft parmakla birlikte kaydirilir, tiklama iptal olur.
    // - Hareket esigi asilmadan birakilirsa TIKLAMA sayilir ve hucre islevi
    //   calisir. Boylece ayni alan hem kaydirilabilir hem tiklanabilir.
    telemetri.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 && ev.pointerType === "mouse") return; // yalniz sol tus
      const hucreEl = ev.target.closest(".dk-tel-hucre");
      ev.preventDefault();
      ev.stopPropagation();
      const islev = hucreEl ? hucreEl.dataset.islev : null;
      const basX = ev.clientX, basY = ev.clientY;
      const basScroll = telemetri.scrollLeft;
      let surukleme = false;
      const pid = ev.pointerId;

      function hareket(mv) {
        if (mv.pointerId !== pid) return;
        const dx = mv.clientX - basX;
        if (!surukleme && Math.abs(dx) > 6) {
          surukleme = true;
          telemetri.classList.add("surukleniyor");
          try { telemetri.setPointerCapture(pid); } catch(e) {}
        }
        if (surukleme) telemetri.scrollLeft = basScroll - dx;
      }
      function birak(uv) {
        if (uv.pointerId !== pid) return;
        telemetri.removeEventListener("pointermove", hareket);
        telemetri.removeEventListener("pointerup", birak);
        telemetri.removeEventListener("pointercancel", birak);
        telemetri.classList.remove("surukleniyor");
        try { telemetri.releasePointerCapture(pid); } catch(e) {}
        // Esik asilmadiysa tiklama olarak isle
        if (!surukleme && islev && uv.type === "pointerup") {
          dkTelHucreTikla(d.sysid, islev, {x: basX, y: basY});
        }
      }
      telemetri.addEventListener("pointermove", hareket);
      telemetri.addEventListener("pointerup", birak);
      telemetri.addEventListener("pointercancel", birak);
    });
    // MOUSE TEKERLEGI ile yatay kaydirma: izgara ustundeyken dikey
    // tekerlek hareketi (deltaY) yatay kaydirmaya cevrilir. Trackpad'in
    // dogal yatay hareketi (deltaX) oldugu gibi kullanilir. passive:false
    // + preventDefault ile sayfa/panel dikey kaymasi engellenir.
    telemetri.addEventListener("wheel", (ev) => {
      const delta = Math.abs(ev.deltaX) > Math.abs(ev.deltaY)
        ? ev.deltaX : ev.deltaY;
      if (!delta) return;
      if (telemetri.scrollWidth <= telemetri.clientWidth) return;
      ev.preventDefault();
      ev.stopPropagation();
      telemetri.scrollLeft += delta;
    }, { passive: false });

    // --- AKSIYON HUCRELERI: tip + Takeoff/Land + joystick + UDP ---
    // Ayri bir bar DEGIL: telemetri izgarasinin (IRT/HIZ/BAT/...) devaminda
    // ayni 2 satirli yatay akista yer alirlar. Dinamik telemetri hucreleri
    // telDinamik (display:contents) icine yazilir; boylece innerHTML
    // yenilenmesi kalici aksiyon hucrelerini silmez, grid akisi bozulmaz.
    const telDinamik = document.createElement("div");
    telDinamik.className = "dk-tel-dinamik";
    telemetri.appendChild(telDinamik);
    // Dron tipi ikonu (multikopter / sabit kanat / helikopter)
    const tipIkon = document.createElement("span");
    tipIkon.className = "dk-tel-hucre dk-hucre-btn dk-tip-ikon";
    tipIkon.innerHTML = "<i class='fa-solid fa-fan'></i>" +
      "<span class='dk-tel-deger dk-tip-ad'>\u2014</span>" +
      "<span class='dk-tel-etiket'>" + (D().dkTipEtiket || "T\u0130P") + "</span>";
    telemetri.appendChild(tipIkon);
    // Akilli Takeoff/Land dugmesi (v2.4.19: ARM -> Land, DISARM -> Takeoff)
    // Not: pointerdown dinleyicisi YOK — tiklamalar telemetri kapsayicisinin
    // surukle/tikla ayristirmasindan data-islev ile yonlendirilir; boylece
    // dugme uzerinden de surukleyerek kaydirma calisir.
    const btnTkLand = document.createElement("button");
    btnTkLand.type = "button";
    btnTkLand.className = "dk-tel-hucre dk-hucre-btn dk-tkland";
    btnTkLand.dataset.islev = "tkland";
    telemetri.appendChild(btnTkLand);
    // Joystick anahtari (basliktan buraya tasindi)
    joyBtn.dataset.islev = "joystick";
    telemetri.appendChild(joyBtn);
    // UDP export dugmesi (Mission Planner koprusu bilgisi)
    const udpBtn = document.createElement("button");
    udpBtn.type = "button";
    udpBtn.className = "dk-tel-hucre dk-hucre-btn dk-udp-btn";
    udpBtn.style.display = "none";
    udpBtn.dataset.islev = "udp";
    udpBtn.title = D().dkUdpRozetIpucu ||
      "MAVLink UDP yayini \u2014 Mission Planner bu porta baglanabilir";
    telemetri.appendChild(udpBtn);

    govde.appendChild(gostergeler.kutu);
    // IS156: ARM durumu, Islemler, GPS ve MOD artik PFD tuvaline CIZILI 4 kose
    // kutusudur (resize'da birlikte olceklenir, ayni stil). HTML overlay butonlari
    // KALDIRILDI. Tiklamalar canvas uzerinde hit-test ile yonlendirilir
    // (bkz. dronGostergeleriOlustur -> canvas 'click'). Eski satir gizlenir.
    try { if (hazirSatir && hazirSatir.parentNode) hazirSatir.remove(); } catch (eOv) {}
    govde.appendChild(telemetri);
    // v2.4.2: kartin en altina kamera secimi + gomulu izleme bolumu
    // v2.4.41: kart govdesinin EN SONUNA ince parametre yukleme seridi.
    // Baglantida tum parametreler otomatik yuklenirken ilerlemeyi
    // gosterir; okuma bitince kisa sure sonra solup gizlenir.
    const paramSerit = document.createElement("div");
    paramSerit.className = "dk-param-serit gizli";
    const paramSeritIc = document.createElement("div");
    paramSeritIc.className = "dk-param-serit-ic";
    paramSerit.appendChild(paramSeritIc);
    paramSerit.title = D().dkParamSeritIpucu ||
      "Parametre yükleme ilerlemesi";
    govde.appendChild(paramSerit);
    // v2.4.45: KART ALTINDA ACILIR KAPANIR HABERLESME KONSOLU
    // Kullanici istegi: "dronlarin iletisim konsol ciktilarini genel
    // konsola yazma, onun yerine dronun panelinin altinda acilir kapanir
    // bir konsol olsun ve tum iletisimi ciplak olarak orada gostersin."
    const konsolBolum = dkKonsolBolumuKur(d.sysid);
    // v2.5.24: Drona bağlı kamera kontrol satırı (kamera başlat/durdur +
    // görüntü hedefi + Yapay Zeka Ayarları). Bağlı kamera yoksa gizli.
    const kameraSatir = document.createElement("div");
    kameraSatir.className = "dk-kamera-satir gizli";
    govde.appendChild(kameraSatir);
    kok._kameraSatir = kameraSatir;
    govde.appendChild(konsolBolum.kok);
    kok.appendChild(baslik);
    kok.appendChild(govde);
    // v2.1.7: Yeni dron karti KAPALI (katlanmis) gelir; kullanici
    // basliga tiklayarak acar. Ayrik (popup) modda bu uygulanmaz.
    if (!kok.classList.contains("ayrik")) {
      baslik.classList.add("kapali");
      govde.classList.add("gizli");
    }
    // v2.4.35: ok ipucusu baslangic durumuna gore kurulur
    dkOkTazele(baslik, ok);
    // v2.4.32: Kart artik Baglanti Yoneticisi'ndeki grubun govdesine
    // yerlesir. Grup henuz cizilmemisse (baglanti listesi gelmediyse)
    // eski kaba dusulur; bir sonraki bagListeCiz() kartı grubuna tasir.
    // Kartlar ASLA yeniden uretilmez, yalnizca tasinir — boylece
    // ucus gostergeleri ve kart durumu korunur.
    if (!(typeof window.dronKartiGrubaYerlestir === "function" &&
          window.dronKartiGrubaYerlestir(d.sysid, kok)))
      dronKartListesi.appendChild(kok);
    kart = dronKartlar[d.sysid] = { kok, baslik, nokta, renkKare, adSpan, ozetSpan,
                                    telemetri,
                                    telDinamik, gosterge: gostergeler.api, govde,
                                    joyBtn, udpBtn, btnTkLand, tipIkon, btnFokusKart,
                                    hazirRozet, islemBtn,
                                    paramSerit, paramSeritIc,
                                    konsol: konsolBolum,
                                    kameraSatir: kameraSatir,
                                    gosDilTazele: gostergeler.dilTazele };
    // Gostergeler DOM'a eklendikten sonra baslatilir (jquery secici)
    gostergeler.baslat();
    // IS153: yuzen panel resize -> PFD'yi pencereyle olcekle + boyutu dron
    // bazinda kaydet. ResizeObserver kok boyutu her degistiginde tetiklenir.
    dronPanelResizeKur(d.sysid, kart);
  }

  // Baslik metni: kullanici ismi varsa onu goster, yoksa D{sysid} | TIP
  // Ad tiklanabilir: isim duzenleme popup'i acilir
  const gosterilecekIsim = d.kullanici_isim || d.tip || d.isim || D().dkDron(d.sysid);
  kart.adSpan.textContent = "D" + d.sysid + " | " + gosterilecekIsim;
  kart.adSpan.style.color = tipRengi(d.tip);
  // v2.1.1: Ad tiklanabilirligi kaldirildi - ayrik moddayken basliktan
  // panel tasima ad linkine takiliyordu. Isim duzenleme dron menusune tasindi.
  kart.nokta.style.background = d.baglanti ? "var(--iyi)" : "var(--kotu)";
  dronKartKameraSatirTazele(kart, d);
  // v2.4.41: dron bagli gorulur gorulmez tam parametre setini otomatik
  // yukle (istek tek kez gider; bkz. dkParamOtoYuklemeDene).
  if (d.baglanti) dkParamOtoYuklemeDene(d.sysid, d);
  else dkParamOtoSifirla(d.sysid);
  // v2.4.32: baslik ozeti — irtifa + ucus kipi.
  // d.mod varsayilani "?" (bos dize DEGIL); baslikta soru isareti
  // gostermek anlamsiz oldugu icin bu deger bos sayilir.
  if (kart.ozetSpan) {
    const irt = (typeof d.alt_rel === "number" && isFinite(d.alt_rel))
                ? d.alt_rel.toFixed(0) + " m" : "";
    const kip = (d.mod && d.mod !== "?") ? String(d.mod) : "";
    // FAZ18-IS21B: konum cozumu yoksa SEBEBI ozette gorunur.
    // Irtifa/kip yerine gecmez, YANINA eklenir; konum gelince kendini
    // gizler (kd === null).
    const kd = dronKonumDurumu(d);
    const yeniOzet = "<span class='dk-ozet-irt'>" + irt + "</span>" +
                     "<span class='dk-ozet-kip'>" + kip + "</span>" +
                     (kd ? "<span class='dk-ozet-konumsuz'>" + kd + "</span>" : "");
    if (kart.ozetSpan._sonOzet !== yeniOzet) {
      kart.ozetSpan._sonOzet = yeniOzet;
      kart.ozetSpan.innerHTML = yeniOzet;
    }
  }
  // Renk karesi: haritadaki ikon/iz rengiyle ayni kalici renk
  if (kart.renkKare) kart.renkKare.style.background = dronRengi(d.sysid);
  // v2.4.224: paneldeki golge satir basligi canli tutulur
  if (kart.golgeBaslik) dkGolgeTazele(kart);
  // Kalibrasyon popup'i aciksa pusula ilerlemesini isle
  if (typeof kalibTelemetriIsle === "function") kalibTelemetriIsle(d);
  // v2.4.2: dron-kamera bagini tazele (uid teslimi)
  // UDP MAVLink yayin dugmesi (aksiyon barinda)
  if (kart.udpBtn) {
    if (d.udp_port) {
      const rozetHtml = "<i class='fa-solid fa-tower-broadcast'></i>" +
                        "<span class='dk-tel-deger'>" + d.udp_port + "</span>" +
                        "<span class='dk-tel-etiket'>UDP</span>";
      if (kart.udpBtn._sonHtml !== rozetHtml) {
        kart.udpBtn._sonHtml = rozetHtml;
        kart.udpBtn.innerHTML = rozetHtml;
      }
      kart.udpBtn.style.display = "";
      kart.udpBtn._port = d.udp_port;
    } else {
      kart.udpBtn.style.display = "none";
      kart.udpBtn._port = null;
    }
  }
  // Dron tipi hucresi (multikopter / sabit kanat / helikopter)
  if (kart.tipIkon) {
    const tipBilgi = dkAracTipiBilgi(d);
    const tipAnahtar = tipBilgi.ikon + "|" + tipBilgi.ad;
    if (kart.tipIkon._sonTip !== tipAnahtar) {
      kart.tipIkon._sonTip = tipAnahtar;
      kart.tipIkon.innerHTML =
        "<i class='fa-solid " + tipBilgi.ikon + "' style='color:var(--interceptor)'></i>" +
        "<span class='dk-tel-deger dk-tip-ad'>" + tipBilgi.ad + "</span>" +
        "<span class='dk-tel-etiket'>" + (D().dkTipEtiket || "T\u0130P") + "</span>";
    }
    kart.tipIkon.title = tipBilgi.ad;
  }
  // v2.4.19: UCUSA HAZIR rozeti (kart en ustu) — sunucudan gelen
  // hazirlik ozeti ile guncellenir; tiklanirsa ARM CHECK paneli acilir.
  if (kart.hazirRozet) dkHazirRozetTazele(kart.hazirRozet, d);

  // v2.4.19: Akilli Takeoff/Land dugmesi ARM DURUMUNA bakar (irtifaya
  // DEGIL). DISARM ise irtifa ne olursa olsun TAKEOFF gosterilir; ARM
  // ise LAND gosterilir. Boylece irtifa telemetrisi gelmeyen/yanlis
  // gelen araclarda dugme kilitlenmez.
  if (kart.btnTkLand) {
    const havadaMi = !!d.armed;
    const tkT = D();
    const yeniIc = havadaMi
      ? "<i class='fa-solid fa-plane-arrival'></i>" +
        "<span class='dk-tel-deger'>" + (tkT.dkLand || "Land") + "</span>" +
        "<span class='dk-tel-etiket'>" + (tkT.dkKomut || "KOMUT") + "</span>"
      : "<i class='fa-solid fa-plane-departure'></i>" +
        "<span class='dk-tel-deger'>" + (tkT.dkTakeoff || "Takeoff") + "</span>" +
        "<span class='dk-tel-etiket'>" + (tkT.dkKomut || "KOMUT") + "</span>";
    if (kart.btnTkLand._sonHtml !== yeniIc) {
      kart.btnTkLand._sonHtml = yeniIc;
      kart.btnTkLand.innerHTML = yeniIc;
      kart.btnTkLand.classList.toggle("land", havadaMi);
      kart.btnTkLand.classList.toggle("takeoff", !havadaMi);
    }
    kart.btnTkLand._havada = havadaMi;
    kart.btnTkLand.disabled = !d.baglanti;
  }

  // Telemetri icerigini guncelle (komut bolumune dokunulmaz)
  const t = D();
  const sayi = (v, hane) => (typeof v === "number" && isFinite(v)) ? v.toFixed(hane) : "-";
  const fix = t.gpsFix[d.gps_fix] || "?";
  const pct = (typeof d.batarya_pct === "number" && d.batarya_pct >= 0) ? " (" + d.batarya_pct + "%)" : "";
  const armed = d.armed ? "<span style='color:var(--iyi)'>" + t.dkArmed + "</span>" : "<span style='color:var(--soluk)'>" + t.dkDisarm + "</span>";
  const baglanti = d.baglanti ? "<span style='color:var(--iyi)'>" + t.dkAktif + "</span>" : "<span style='color:var(--kotu)'>" + t.dkKopuk + "</span>";
  const konum = (typeof d.lat === "number" && isFinite(d.lat) && typeof d.lon === "number" && isFinite(d.lon))
    ? d.lat.toFixed(5) + ", " + d.lon.toFixed(5) : "-";

  // GORSEL TELEMETRI IZGARASI: 2x2 — buyuk ikon ustte, deger altta
  // (Detayli tum veriler menu > Telemetri popup'inda)
  const batV = sayi(d.batarya_v, 1);
  const batYuzde = (typeof d.batarya_pct === "number" && d.batarya_pct >= 0) ? d.batarya_pct : null;
  const batRenk = (batYuzde !== null && batYuzde <= 20) ? "var(--kotu)"
                : (batYuzde !== null && batYuzde <= 40) ? "var(--uyari)" : "var(--iyi)";
  const batIkon = (batYuzde === null) ? "fa-battery-half"
                : (batYuzde > 75) ? "fa-battery-full"
                : (batYuzde > 50) ? "fa-battery-three-quarters"
                : (batYuzde > 25) ? "fa-battery-half"
                : (batYuzde > 10) ? "fa-battery-quarter" : "fa-battery-empty";
  const gpsRenk = (d.gps_fix >= 3) ? "var(--iyi)" : (d.gps_fix === 2) ? "var(--uyari)" : "var(--kotu)";
  // Her hucre tiklanabilir dugmedir; data-islev tiklama yonlendirmesi icindir
  const hucre = (islev, ikon, ikonRenk, deger, etiket) =>
    "<div class='dk-tel-hucre' data-islev='" + islev + "' role='button' tabindex='0'>" +
      "<i class='fa-solid " + ikon + "' style='color:" + ikonRenk + "'></i>" +
      "<span class='dk-tel-deger'>" + deger + "</span>" +
      "<span class='dk-tel-etiket'>" + etiket + "</span>" +
    "</div>";
  const durumRenk = d.armed ? "var(--iyi)" : "var(--soluk)";
  const durumIkon = d.armed ? "fa-lock-open" : "fa-lock";
  const durumYazi = d.armed ? t.dkArmed : t.dkDisarm;
  const yeniHtml =
    hucre("irtifa", "fa-arrows-up-down", "var(--interceptor)", sayi(d.alt_rel, 1) + " m", t.dkIrt) +
    hucre("hiz", "fa-gauge-high", "var(--interceptor)",
      sayi(d.groundspeed, 1) + " m/s<br><small class='dk-kmh'>" +
      (typeof d.groundspeed === "number"
        ? (d.groundspeed * 3.6).toFixed(1) : "-") + " km/h</small>", t.dkHiz) +
    hucre("batarya", batIkon, batRenk, batV + " V" + (batYuzde !== null ? " \u00B7 " + batYuzde + "%" : ""), t.dkBat) +
    hucre("gps", "fa-satellite-dish", gpsRenk, fix + " \u00B7 " + (d.uydu != null ? d.uydu : "-"), t.dkGps) +
    hucre("durum", durumIkon, durumRenk, durumYazi, t.dkDurum) +
    hucre("mod", "fa-microchip", "var(--interceptor)", d.mod || "-", t.dkMod);
  // Yalniz icerik degistiyse DOM'u yeniden yaz — gereksiz yikimlar hover
  // durumunu bozar ve tiklama guvenilirligini dusurur
  const telHedef = kart.telDinamik || kart.telemetri;
  if (telHedef._sonHtml !== yeniHtml) {
    telHedef._sonHtml = yeniHtml;
    telHedef.innerHTML = yeniHtml;
  }

  // Baslik rengini baglanti durumuna gore ayarla
  kart.baslik.style.opacity = d.baglanti ? "1" : "0.5";

  // --- UCUS GOSTERGESINI BESLE (IS152: tek PFD canvas) ---
  if (kart.gosterge && typeof kart.gosterge.ciz === "function") {
    try { kart.gosterge.ciz(d); } catch (e) { /* PFD hazir degilse sessiz gec */ }
  }

  // --- TOOLBAR DUGME DURUMLARI (ayri Arm/Disarm, Takeoff/Land) ---
  const kok = kart.kok;
  const havada = d.armed && d.alt_rel > 1;
  if (kok._tb) {
    kok._tb.arm.disabled = !!d.armed;
    kok._tb.disarm.disabled = !d.armed;
    kok._tb.takeoff.disabled = havada;
    kok._tb.land.disabled = !havada;
    kok._tb.irtifa.disabled = !havada;
  }
}

// ---------------------------------------------------------------
// UCUS GOSTERGELERI (jquery-flight-indicators)
// ---------------------------------------------------------------
const GOSTERGE_BOYUT = 160;
const GOSTERGE_AYAR = { size: GOSTERGE_BOYUT, showBox: false,
                        img_directory: "lib/flightindicators/img/" };
// Gosterge turleri + i18n etiket anahtarlari (karusel sirasi)
const GOSTERGE_TANIM = [
  ["attitude",   "dkGosAtt"],
  ["heading",    "dkGosHdg"],
  ["altimeter",  "dkGosAlt"],
  ["airspeed",   "dkGosSpd"],
  ["variometer", "dkGosVar"],
];

// IS152: Dron paneli gostergesi artik TEK bir PFD canvas'i (Boeing tarzi cam
// kokpit — kullanicinin yukledigi tasarim, sag 3B ucak gorunumu HARIC).
// Eski jquery-flight-indicators karuseli (attitude/heading/altimeter/airspeed/
// variometer, ok+nokta gezinme) KALDIRILDI. Yeni PFD tum gostergeleri tek
// ekranda toplar: yapay ufuk, hiz seridi, irtifa seridi, dikey hiz, pusula.
function dronGostergeleriOlustur(sysid) {
  const dis = document.createElement("div");
  dis.className = "dk-gos-dis dk-pfd-dis";
  const canvas = document.createElement("canvas");
  canvas.className = "dk-pfd-canvas";
  canvas.id = "dkPfd_" + sysid;
  dis.appendChild(canvas);

  // Cift tik: bu dronun telemetrilerini AYRI PENCEREDE ac (2. monitor).
  // Sayfa: drontelemetri.html — pilota-ozel dizilim, BroadcastChannel ile beslenir.
  canvas.addEventListener("dblclick", function(ev){
    ev.preventDefault(); ev.stopPropagation();
    try {
      var kok = (typeof window.appYolu === "function")
        ? window.appYolu("/drontelemetri.html") : "drontelemetri.html";
      window.open(kok + "?sysid=" + encodeURIComponent(sysid),
                  "goktungu_telemetri_" + sysid,
                  "width=980,height=760");
    } catch (e) {}
  });

  let sonDurum = null;
  function ciz(d) {
    if (!window.PanelPFD || !d) return;
    sonDurum = window.PanelPFD.telemetriDurum(d);
    try { window.PanelPFD.ciz(canvas, sonDurum); } catch (e) { /* sessiz */ }
  }
  // IS155: GPS kutusuna tiklayinca drona fokuslan
  canvas.addEventListener("click", (ev) => {
    try {
      if (!window.PanelPFD || typeof window.PanelPFD.gpsKutuAlani !== "function") return;
      const kutu = window.PanelPFD.gpsKutuAlani();
      if (!kutu) return;
      const r = canvas.getBoundingClientRect();
      if (!r.width || !r.height) return;
      // Sanal tuval yuksekligi H=528 (bkz. panel_pfd.js)
      const sx = (ev.clientX - r.left) * 800 / r.width;
      const sy = (ev.clientY - r.top) * 528 / r.height;
      const ic = (kt) => kt && sx >= kt.x && sx <= kt.x + kt.w && sy >= kt.y && sy <= kt.y + kt.h;
      const P = window.PanelPFD;
      const al = (ad) => (typeof P[ad] === "function") ? P[ad]() : null;
      const nokta = { x: ev.clientX, y: ev.clientY };
      if (ic(kutu)) { if (typeof dronaGit === "function") dronaGit(sysid); return; }             // GPS -> fokus
      if (ic(al("modKutuAlani"))) { if (typeof dkModPopupAc === "function") dkModPopupAc(sysid, nokta); return; }
      if (ic(al("armKutuAlani"))) { if (typeof dkArmCheckPopupAc === "function") dkArmCheckPopupAc(sysid, nokta); return; }
      if (ic(al("islemKutuAlani"))) { if (typeof window.dkIslemlerPopupAc === "function") window.dkIslemlerPopupAc(sysid, nokta); return; }
    } catch (e) {}
  });
  function baslat() {
    // Canvas genisligi yerlesim tamamlaninca hazir olur; ilk cizimi ertele
    requestAnimationFrame(() => {
      if (sonDurum && window.PanelPFD) {
        try { window.PanelPFD.ciz(canvas, sonDurum); } catch (e) {}
      }
    });
  }
  function dilTazele() { /* PFD dilden bagimsizdir */ }
  // api.ciz(d): dronKartGuncelle her telemetri paketinde cagirir
  return { kutu: dis, api: { canvas: canvas, ciz: ciz }, baslat, dilTazele };
}

// ---------------------------------------------------------------
// IKONLU KOMUT TOOLBAR'I + MINI POPUP'LAR
// ---------------------------------------------------------------
function dkMiniPopupKapat() {
  document.querySelectorAll(".dk-mini-popup").forEach(p => p.remove());
}
// NOT: Mini popup'lar artik disari tiklamayla KAPANMAZ (tasinabilir pencere
// gibi davranir); basliktaki x dugmesiyle kapatilir.
// COKLU POPUP: Popup'lar birbirini KAPATMAZ - ayni anda birden fazla acik
// kalabilir (orn. GPS + Ayarlar). Ayni popup'in kopyasini onlemek icin her
// popup tekil bir kimlikle acilir: zaten acik ise one getirilir.
let dkPopupZSayac = 2500;
function dkPopupTekil(kimlik) {
  const eski = document.getElementById(kimlik);
  if (eski) {
    eski.style.zIndex = String(++dkPopupZSayac);
    return eski;   // zaten acik - one getirildi
  }
  return null;
}
function dkPopupOneGetirKur(pop) {
  // Herhangi bir yerine basilinca en one gelsin
  pop.addEventListener("pointerdown", () => {
    pop.style.zIndex = String(++dkPopupZSayac);
  });
  pop.style.zIndex = String(++dkPopupZSayac);
}

// Ortak: mini popup basligi olustur (metin + kapatma dugmesi) ve
// basliktan surukleyerek tasinabilir yap
// v2.4.32: 4. parametre `ikon` EKLENDI (istege bagli, ornek "fa-sliders").
// Geriye donuk uyum: 13 mevcut cagri 3 parametreyle calismaya devam eder,
// ikon verilmeyen basliklar eskisi gibi ikonsuz uretilir.
// Ikon + metin, standart pencere basligiyla ayni yapida TEK span icinde
// sarilir; ortak CSS kurali (.dk-mp-baslik > span:first-child) bu yapiyi
// bekler, aksi halde metin kisaltma (ellipsis) calismaz.
function dkMiniPopupBaslikKur(pop, baslikYazi, konumAnahtar, ikon) {
  const bas = document.createElement("div");
  bas.className = "dk-mp-baslik";
  const yazi = document.createElement("span");
  yazi.className = "dk-mp-baslik-yazi";
  if (ikon) {
    const ik = document.createElement("i");
    ik.className = "fa-solid " + ikon;
    yazi.appendChild(ik);
    const mt = document.createElement("span");
    mt.textContent = baslikYazi;
    yazi.appendChild(mt);
  } else {
    yazi.textContent = baslikYazi;
  }
  const kapat = document.createElement("button");
  kapat.type = "button";
  kapat.className = "dk-mp-kapat";
  kapat.title = D().kapat || ((typeof aktifDil !== "undefined" && aktifDil === "en") ? "Close" : "Kapat");
  kapat.setAttribute("aria-label", kapat.title);
  kapat.innerHTML = "<i class='fa-solid fa-xmark'></i>";
  // Baslik surukleme jesti X'e ulasimi engellemesin. Pencerenin kendi
  // temizleme kancasi varsa (kalibrasyon mesaj akisi gibi) once onu calistir.
  kapat.addEventListener("pointerdown", (ev) => { ev.stopPropagation(); });
  kapat.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (typeof pop.kapat === "function") pop.kapat(); else pop.remove();
  });
  bas.appendChild(yazi);
  bas.appendChild(kapat);
  pop.appendChild(bas);
  // Basliktan surukleme (pointer events - dron karti ayrik moduyla ayni desen)
  let surukle = null;
  bas.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".dk-mp-kapat")) return;
    const rect = pop.getBoundingClientRect();
    surukle = { dx: ev.clientX - rect.left, dy: ev.clientY - rect.top };
    bas.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  bas.addEventListener("pointermove", (ev) => {
    if (!surukle) return;
    let x = ev.clientX - surukle.dx;
    let y = ev.clientY - surukle.dy;
    x = Math.max(0, Math.min(x, window.innerWidth - pop.offsetWidth));
    y = Math.max(0, Math.min(y, window.innerHeight - 32));
    pop.style.left = x + "px";
    pop.style.top = y + "px";
  });
  const birak = (ev) => {
    if (!surukle) return;
    surukle = null;
    try { bas.releasePointerCapture(ev.pointerId); } catch (e) {}
    // Konumu kalici kaydet (anahtar verildiyse)
    if (konumAnahtar && typeof window.pencereKonumKaydet === "function") {
      window.pencereKonumKaydet(konumAnahtar, pop);
    }
  };
  bas.addEventListener("pointerup", birak);
  bas.addEventListener("pointercancel", birak);
  // Kayitli konum varsa DOM'a eklendikten sonra uygula.
  //
  // v2.4.52: EKRAN DISI KAYIT KURTARMA (tek nokta).
  // Bu yardimci tum panel ailelerinin ortak gecididir (dron_*, kam_*,
  // dkam_*, yz_*, istasyon2, kayitliDronlar). Kayitli konum gorunur
  // alanin tamamen disindaysa (ekran duzeni degismis, ikinci ekran
  // cikarilmis ya da eski surumdeki transform kusuru bozuk deger
  // yazmis) kayit SILINIR ve panel CSS varsayilaninda acilir.
  // Aksi halde panelin baslik cubugu erisilemez olur: ne suruklenebilir
  // ne kapatilabilir (kapatma dugmesi de baslikta).
  if (konumAnahtar && typeof window.pencereKonumUygula === "function") {
    setTimeout(() => {
      const gecerli = (typeof window.pencereKonumGecerliMi === "function")
        ? window.pencereKonumGecerliMi(konumAnahtar,
                                       pop.offsetWidth, pop.offsetHeight)
        : true;
      if (!gecerli) {
        if (typeof window.pencereKonumSil === "function")
          window.pencereKonumSil(konumAnahtar);
        return;   // CSS varsayilaninda birak
      }
      window.pencereKonumUygula(konumAnahtar, pop, !!pop._boyutluKayit);
    }, 0);
  }

  // v2.4.52: BOYUTLANDIRMA KANCASI (tek nokta).
  // popup_tasima.js icindeki statikKur() yalniz index.html'de TANIMLI
  // panellere ve .yuzen-panel sinifina resize tutamaci kuruyor. JS ile
  // calisma aninda uretilen dk-mini-popup panelleri (Program Ayarlari,
  // GCCDUAL, dron/kamera panelleri, Kayitli Dronlar...) o listenin
  // disinda kaliyordu: icerik buyudukce panel sabit CSS genisliginde
  // sikisip kaliyor, kullanici genisletemiyordu.
  //
  // Kanca burada kurulur cunku bu yardimci TUM dk-mini-popup
  // ailelerinin ortak gecididir; tek tek panellere eklemek 18 cagri
  // yerine dokunmak demekti (v2.4.51'de genis degisiklik yeni kusur
  // urettigi icin kacinildi).
  //
  // Boyut, konumla AYNI anahtar altinda saklanir; bu yuzden
  // _boyutluKayit isareti konum kaydetme yollarindan ONCE kurulmalidir
  // (yukaridaki pencereKonumUygula cagrisi da bu isarete bakar).
  if (konumAnahtar && typeof window.popupBoyutlandirilabilirYap === "function") {
    window.popupBoyutlandirilabilirYap(pop, konumAnahtar);
  }
  return bas;
}

// Ortak: popup'i ekranda konumlandir. anka bir DOM elemani ({getBoundingClientRect})
// veya {x, y} mouse konumu olabilir.
function dkMiniPopupKonumla(pop, anka) {
  const popW = pop.offsetWidth || 222;
  const popH = pop.offsetHeight || 160;
  let sol, ust;
  if (anka && typeof anka.x === "number" && typeof anka.y === "number") {
    sol = anka.x; ust = anka.y;
  } else if (anka && typeof anka.getBoundingClientRect === "function") {
    const r = anka.getBoundingClientRect();
    sol = r.left; ust = r.bottom + 4;
  } else {
    sol = (window.innerWidth - popW) / 2; ust = (window.innerHeight - popH) / 2;
  }
  if (sol + popW > window.innerWidth - 8) sol = window.innerWidth - popW - 8;
  if (sol < 8) sol = 8;
  if (ust + popH > window.innerHeight - 8) ust = Math.max(8, window.innerHeight - popH - 8);
  if (ust < 8) ust = 8;
  pop.style.left = sol + "px";
  pop.style.top = ust + "px";
}

// ---------------------------------------------------------------
// ARAC TIPI IKONU (HEARTBEAT MAV_TYPE -> ikon + ad)
// ---------------------------------------------------------------
function dkAracTipiBilgi(d) {
  const t = D();
  const mt = Number((d && d.arac_tipi) || 0);
  if (mt === 1)
    return { ikon: "fa-plane-up", ad: t.fsPlane || "Sabit Kanat" };
  if (mt === 4)
    return { ikon: "fa-helicopter", ad: t.fsHeli || "Helikopter" };
  if ([19, 20, 21, 22, 23, 24, 25].includes(mt))
    return { ikon: "fa-jet-fighter-up", ad: "VTOL" };
  return { ikon: "fa-fan", ad: t.fsKopter || "Multikopter" };
}

// ---------------------------------------------------------------
// AKILLI TAKEOFF/LAND DUGMESI (kart aksiyon barinda)
// v2.4.19: ARM ise Land onayi; DISARM ise Takeoff irtifa popup'i
// (onceki surumlerde alt_rel > 3 m esigi kullaniliyordu)
// ---------------------------------------------------------------
function dkTakeoffLandTikla(sysid, btn, fare) {
  const t = D();
  if (btn._havada) {
    onayIste(onayMetni("onayLand"),
      () => dronKomutGonder(sysid, "land"));
  } else {
    dkSliderPopup(fare, t.dkTakeoffIrtifa, [
      { ad: "irtifa", etiket: t.dkTakeoffIrtifa, min: 2, max: 200,
        adim: 1, deger: 10, birim: "m", hane: 0 },
    ], t.dkTakeoff || "Takeoff", (v) =>
      // v2.4.41: irtifa secildikten sonra basit onay kutusu YERINE
      // zorunlu kalkis kontrol listesi acilir. Liste tamamlandiginda
      // kayit + takeoff komutu SUNUCUDA tek islemde yapilir; boylece
      // "kayit yoksa kalkis yok" garantisi tek yerde saglanir.
      // Ust uste iki onay (onayIste + liste) pilotu yorardi, bu yuzden
      // eski onay adimi kaldirildi — liste zaten cok daha guclu bir onay.
      dkTakeoffKontrolListesi(sysid, v.irtifa, fare));
  }
}

// ---------------------------------------------------------------
// v2.4.41: Kalkis kontrol listesini ac (iki takeoff girisinin ortak
// halkasi). kalkis_kontrol.js yuklenmemisse eski davranisa duser ki
// tek bir dosya eksikliginde takeoff tumden kilitlenmesin.
// ---------------------------------------------------------------
function dkTakeoffKontrolListesi(sysid, irtifa, fare) {
  if (typeof window.kalkisKontrolAc === "function") {
    window.kalkisKontrolAc(sysid, irtifa, fare);
    return;
  }
  onayIste(onayMetni("onayTakeoff", {irtifa: irtifa}),
    () => dronKomutGonder(sysid, "takeoff", irtifa));
}

// ---------------------------------------------------------------
// UDP MAVLINK YAYIN BILGI POPUP'I (Mission Planner koprusu)
// ---------------------------------------------------------------
function dkUdpBilgiPopup(anka, sysid) {
  if (dkPopupTekil("dkPopupUdp_" + sysid)) return;
  const t = D();
  const d = sonVeri[sysid] || {};
  const port = d.udp_port || "—";
  const pop = document.createElement("div");
  pop.id = "dkPopupUdp_" + sysid;
  pop.className = "dk-mini-popup";
  dkMiniPopupBaslikKur(pop, (t.dkUdpBaslik || "MAVLink UDP Yayini"),
    null, "fa-tower-broadcast");
  const satir = (etiket, deger) => {
    const s = document.createElement("div");
    s.className = "dk-mp-satir";
    s.innerHTML = "<span class='dk-mp-etiket'>" + etiket + "</span>" +
                  "<span class='dk-mp-deger' style='user-select:text'>" + deger + "</span>";
    pop.appendChild(s);
  };
  satir("Port", "<b style='color:var(--iyi)'>" + port + "</b>");
  satir("Protokol", "UDP (MAVLink)");
  // v2.4.39: window.location.hostname YANLIS adres uretiyordu. Tarayiciyi
  // 127.0.0.1 uzerinden acan kullanici, agdaki baska bir bilgisayara
  // verecegi adres olarak "127.0.0.1" goruyordu; loopback ise o makineden
  // asla erisilemez. Sunucu artik gercek LAN adresini bildiriyor (udp_ip);
  // yalnizca o yoksa tarayicinin adresine dusulur.
  const lan = d.udp_ip || "";
  const tarayici = window.location.hostname || "";
  const gosterIp = lan || (tarayici && !/^(127\.|localhost$)/.test(tarayici)
                           ? tarayici : "");
  satir("IP", gosterIp
    ? "<b>" + gosterIp + "</b>"
    : "<span style='color:var(--uyari)'>" +
      (t.dkUdpIpYok || "tespit edilemedi") + "</span>");
  const acik = document.createElement("div");
  acik.style.cssText = "font-size:11px;opacity:.75;padding:6px 10px;line-height:1.5;max-width:260px";
  if (gosterIp) {
    acik.innerHTML = (t.dkUdpAciklama ||
      "Mission Planner: Connect \u2192 UDPCl \u2192 host ve port asagidaki gibi. Ayni agdaki her bilgisayardan baglanilabilir; iki program ayni anda calisabilir.") +
      "<div style='margin-top:6px;font-family:monospace;user-select:text;" +
      "background:rgba(255,255,255,.06);padding:4px 6px;border-radius:4px'>" +
      gosterIp + ":" + port + "</div>";
  } else {
    acik.textContent = t.dkUdpIpYokAcik ||
      "Ag adresi tespit edilemedi. Bu bilgisayarin IP adresini isletim sisteminden ogrenip Mission Planner'da host olarak girin; port yukaridaki degerdir.";
  }
  pop.appendChild(acik);
  pop.style.position = "fixed";
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, anka);
}

// Dron isim ve yerel Goruntu Koprusu kamera bagi duzenleme popup'i
function dkGoruntuKameraToast(basarili, mesaj) {
  if (typeof window.uyariToastGoster !== "function") return;
  window.uyariToastGoster({
    baslik: basarili ? "KAMERA BAĞI GÜNCELLENDİ" : "KAMERA BAĞI KURULAMADI",
    mesaj: mesaj || (basarili ? "Seçim Görüntü Köprüsü'ne uygulandı." : "İşlem reddedildi."),
    seviye: basarili ? "bilgi" : "uyari", sure: 6500,
  });
}

function dkGoruntuKameraSecenekleri(pop, istenenKamera) {
  const kopruSel = pop && pop._gkKopru;
  const kameraSel = pop && pop._gkKamera;
  if (!kopruSel || !kameraSel) return;
  const oid = Number(kopruSel.value || 0);
  const kopru = (pop._gkKopruler || []).find(k => Number(k.ornek_id) === oid);
  kameraSel.replaceChildren();
  const bos = document.createElement("option");
  bos.value = "";
  bos.textContent = "Kamera bağlama";
  kameraSel.appendChild(bos);
  for (const kam of (kopru && kopru.kameralar) || []) {
    const secenek = document.createElement("option");
    secenek.value = String(kam.id);
    const durum = kam.canli ? "canlı" : "çevrimdışı";
    const kal = kam.kalibre ? "kalibre" : "kalibrasyonsuz";
    secenek.textContent = `${kam.isim} · ${durum} · ${kal}`;
    secenek.disabled = !kam.etkin;
    kameraSel.appendChild(secenek);
  }
  kameraSel.disabled = !kopru || !kopru.cevrimici;
  if (istenenKamera && Array.from(kameraSel.options).some(
      o => o.value === String(istenenKamera))) {
    kameraSel.value = String(istenenKamera);
  } else {
    kameraSel.value = "";
  }
}

window.dkGoruntuKameraKaynaklariIsle = function (m) {
  const sysid = Number(m && m.istek_sysid);
  const pop = document.getElementById("dkPopupIsim_" + sysid);
  if (!pop || !pop._gkKopru || !pop._gkKamera) return;
  const durum = pop._gkDurum;
  if (!m.basarili) {
    durum.textContent = m.hata || "Görüntü Köprüsü kamera listesi alınamadı.";
    pop._gkKopru.disabled = true;
    pop._gkKamera.disabled = true;
    return;
  }
  pop._gkKopruler = Array.isArray(m.kopruler) ? m.kopruler : [];
  pop._gkKopru.replaceChildren();
  const bos = document.createElement("option");
  bos.value = "";
  bos.textContent = "Görüntü Köprüsü seçin";
  pop._gkKopru.appendChild(bos);
  for (const kopru of pop._gkKopruler) {
    const secenek = document.createElement("option");
    secenek.value = String(kopru.ornek_id);
    secenek.textContent = `${kopru.ad} · ${(kopru.kameralar || []).length} kamera`;
    secenek.disabled = !kopru.cevrimici;
    pop._gkKopru.appendChild(secenek);
  }
  const uid = String(pop._gkDronUid || "");
  let mevcut = null;
  for (const kopru of pop._gkKopruler) {
    for (const kamera of kopru.kameralar || []) {
      if (uid && String(kamera.kaynak_dron_id || "") === uid) {
        mevcut = {ornek_id: Number(kopru.ornek_id), kamera_id: Number(kamera.id)};
        break;
      }
    }
    if (mevcut) break;
  }
  pop._gkMevcut = mevcut;
  if (mevcut) {
    pop._gkKopru.value = String(mevcut.ornek_id);
    dkGoruntuKameraSecenekleri(pop, mevcut.kamera_id);
    durum.textContent = "Bu drona bağlı yerel kamera gösteriliyor.";
  } else {
    pop._gkKopru.value = "";
    dkGoruntuKameraSecenekleri(pop, null);
    durum.textContent = pop._gkKopruler.length
      ? "İsterseniz bu dron için yerel görüntü kaynağı seçin."
      : "Firma kapsamında çevrimiçi Görüntü Köprüsü yok.";
  }
};

window.dkGoruntuKameraBagSonucIsle = function (m) {
  const sysid = Number(m && m.istek_sysid);
  const pop = document.getElementById("dkPopupIsim_" + sysid);
  if (m && m.basarili) {
    dkGoruntuKameraToast(true, "Dron ve yerel kamera bağı kaydedildi.");
    if (pop) pop.remove();
    return;
  }
  dkGoruntuKameraToast(false, (m && m.hata) || "Kamera bağı reddedildi.");
  if (pop && pop._gkKaydet) {
    pop._gkKaydet.disabled = false;
    pop._gkKaydet.innerHTML = "<i class='fa-solid fa-check'></i> <span>KAYDET</span>";
    if (pop._gkIptal) pop._gkIptal.disabled = false;
  }
};

function dkIsimDuzenlePopup(anka, sysid) {
  if (dkPopupTekil("dkPopupIsim_" + sysid)) return;
  const t = D();
  const d = sonVeri[sysid];
  const dronUid = String((d && d.uid) || "");
  const pop = document.createElement("div");
  pop.id = "dkPopupIsim_" + sysid;
  pop.className = "dk-mini-popup dk-dron-duzenle-popup";
  pop._gkDronUid = dronUid;
  pop._gkKopruler = [];
  dkMiniPopupBaslikKur(pop, t.dkDuzenle || "Dronu Düzenle",
    "dronIsimDuzenle", "fa-pen");

  const govde = document.createElement("div");
  govde.className = "dk-dron-duzenle-govde";

  const uidSatir = document.createElement("div");
  uidSatir.className = "dk-mp-satir dk-dron-duzenle-uid";
  const uidEtiket = document.createElement("span");
  uidEtiket.className = "dk-mp-etiket";
  uidEtiket.textContent = "UID";
  const uidDeger = document.createElement("span");
  uidDeger.className = "dk-mp-deger";
  uidDeger.textContent = dronUid || "—";
  uidSatir.append(uidEtiket, uidDeger);
  govde.appendChild(uidSatir);

  const isimAlan = document.createElement("label");
  isimAlan.className = "dk-dron-duzenle-alan";
  const isimEtiket = document.createElement("span");
  isimEtiket.className = "dk-mp-etiket";
  isimEtiket.textContent = t.dkIsimEtiket || "İsim";
  const isimInput = document.createElement("input");
  isimInput.type = "text";
  isimInput.className = "dk-mp-input";
  isimInput.value = (d && d.kullanici_isim) ? d.kullanici_isim : (dronUid || "D" + sysid);
  isimInput.placeholder = dronUid || "D" + sysid;
  isimAlan.append(isimEtiket, isimInput);
  govde.appendChild(isimAlan);
  // v2.4.202 (kullanici istegi): dronun harita rengi secilebilir.
  const renkAlan = document.createElement("label");
  renkAlan.className = "dk-dron-duzenle-alan";
  const renkEtiket = document.createElement("span");
  renkEtiket.className = "dk-mp-etiket";
  renkEtiket.textContent = t.dkRenkEtiket || "Harita rengi";
  const renkInput = document.createElement("input");
  renkInput.type = "color";
  renkInput.className = "dk-mp-input dk-renk-sec";
  const _ilkRenk = (typeof dronRengi === "function") ? dronRengi(sysid) : "#5cc8ff";
  renkInput.value = /^#[0-9a-fA-F]{6}$/.test(_ilkRenk || "") ? _ilkRenk : "#5cc8ff";
  renkInput.dataset.ilk = renkInput.value;
  renkAlan.append(renkEtiket, renkInput);
  govde.appendChild(renkAlan);

  const kaynakBolum = document.createElement("section");
  kaynakBolum.className = "dk-dron-duzenle-kaynak";
  const kameraBaslik = document.createElement("div");
  kameraBaslik.className = "dk-dron-duzenle-bolum-baslik";
  kameraBaslik.textContent = "YEREL GÖRÜNTÜ KAYNAĞI";
  kaynakBolum.appendChild(kameraBaslik);

  const kopruAlan = document.createElement("label");
  kopruAlan.className = "dk-dron-duzenle-alan";
  const kopruEtiket = document.createElement("span");
  kopruEtiket.className = "dk-mp-etiket";
  kopruEtiket.textContent = "Görüntü Köprüsü";
  const kopruSel = document.createElement("select");
  kopruSel.className = "dk-mp-input";
  kopruSel.disabled = true;
  const yukleniyor = document.createElement("option");
  yukleniyor.value = "";
  yukleniyor.textContent = "Görüntü Köprüleri yükleniyor…";
  kopruSel.appendChild(yukleniyor);
  kopruAlan.append(kopruEtiket, kopruSel);
  kaynakBolum.appendChild(kopruAlan);

  const kameraAlan = document.createElement("label");
  kameraAlan.className = "dk-dron-duzenle-alan";
  const kameraEtiket = document.createElement("span");
  kameraEtiket.className = "dk-mp-etiket";
  kameraEtiket.textContent = "Kamera";
  const kameraSel = document.createElement("select");
  kameraSel.className = "dk-mp-input";
  kameraSel.disabled = true;
  const kameraBos = document.createElement("option");
  kameraBos.value = "";
  kameraBos.textContent = "Önce Görüntü Köprüsü seçin";
  kameraSel.appendChild(kameraBos);
  kameraAlan.append(kameraEtiket, kameraSel);
  kaynakBolum.appendChild(kameraAlan);

  const durum = document.createElement("div");
  durum.className = "dk-dron-duzenle-durum";
  durum.textContent = "Kamera listesi yalnız metadata olarak merkezden alınıyor; görüntü merkeze taşınmaz.";
  kaynakBolum.appendChild(durum);
  govde.appendChild(kaynakBolum);
  pop.appendChild(govde);

  pop._gkKopru = kopruSel;
  pop._gkKamera = kameraSel;
  pop._gkDurum = durum;
  kopruSel.addEventListener("change", () => dkGoruntuKameraSecenekleri(pop, null));

  const alt = document.createElement("div");
  alt.className = "dk-dron-duzenle-alt";
  const iptal = document.createElement("button");
  iptal.type = "button";
  iptal.className = "dk-dron-duzenle-iptal";
  iptal.innerHTML = "<i class='fa-solid fa-xmark'></i> <span>" +
    (t.iptal || "İPTAL") + "</span>";
  iptal.addEventListener("click", () => pop.remove());

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dk-mp-gonder dk-dron-duzenle-kaydet";
  btn.innerHTML = "<i class='fa-solid fa-check'></i> <span>" +
    (t.dkKaydet || "KAYDET") + "</span>";
  pop._gkKaydet = btn;
  pop._gkIptal = iptal;
  btn.addEventListener("click", () => {
    const yeniIsim = isimInput.value.trim();
    if (yeniIsim && ws && ws.readyState === 1) {
      ws.send(JSON.stringify({tip: "dron_isim_kaydet", sysid: sysid, isim: yeniIsim}));
      if (d) d.kullanici_isim = yeniIsim;
    }
    const yeniRenk = String(renkInput.value || "").toLowerCase();
    if (yeniRenk && yeniRenk !== renkInput.dataset.ilk && ws && ws.readyState === 1) {
      ws.send(JSON.stringify({tip: "dron_renk_kaydet", sysid: sysid, renk: yeniRenk}));
      if (!window.dronRenkler) window.dronRenkler = {};
      window.dronRenkler[String(sysid)] = yeniRenk;
    }
    const mevcut = pop._gkMevcut;
    const oid = Number(kopruSel.value || 0);
    const kid = Number(kameraSel.value || 0);
    const degisti = (mevcut && (!kid || mevcut.ornek_id !== oid || mevcut.kamera_id !== kid)) ||
                    (!mevcut && oid > 0 && kid > 0);
    if (!degisti) {
      pop.remove();
      return;
    }
    if (!ws || ws.readyState !== 1) {
      durum.textContent = "Sunucu bağlantısı yok; kamera bağı kaydedilemedi.";
      return;
    }
    const hedefOid = kid ? oid : mevcut.ornek_id;
    const hedefKid = kid ? kid : mevcut.kamera_id;
    btn.disabled = true;
    iptal.disabled = true;
    btn.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> <span>KAYDEDİLİYOR</span>";
    ws.send(JSON.stringify({
      tip: "goruntu_kamera_dron_bagla", ornek_id: hedefOid,
      kamera_id: hedefKid, dron_uid: kid ? dronUid : "",
      istek_sysid: sysid,
    }));
  });
  alt.append(iptal, btn);
  pop.appendChild(alt);
  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, anka);
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({tip: "goruntu_kamera_kaynaklari",
      istek_sysid: sysid, dron_uid: dronUid}));
  } else {
    durum.textContent = "Sunucu bağlantısı yok; Görüntü Köprüsü listesi alınamadı.";
  }
  setTimeout(() => isimInput.select(), 50);
}

// =================================================================
// DRON-DRON TAKIP SISTEMI
// - Menu > "Takip Et": hedef dron secimi + irtifa farki + mesafe
//   (-100..+100 m) popup'i; backend'e takip_baslat gonderir.
// - Aktif takipte: takip edilen + takip eden kartlar alt alta
//   tasinir, basliklarina MOR kalin cizgi (CSS .takip-mor) eklenir.
// - Takip edilen VEYA takip eden dronun menusunde "Takibi Iptal Et".
// =================================================================
let dronTakipler = [];   // [{takipci_sysid, hedef_sysid, irtifa_fark, mesafe}]

function dronTakipBul(sysid) {
  // Bu sysid'nin dahil oldugu takip kaydini dondur (takipci veya hedef)
  sysid = Number(sysid);
  for (const tk of dronTakipler) {
    if (tk.takipci_sysid === sysid || tk.hedef_sysid === sysid) return tk;
  }
  return null;
}

window.dronTakipDurumIsle = function (takipler) {
  const yeni = JSON.stringify(takipler || []);
  if (yeni === JSON.stringify(dronTakipler)) return;   // degisiklik yok
  dronTakipler = takipler || [];
  dronTakipGorunumTazele();
};

function dronTakipGorunumTazele() {
  // 1) Tum kartlardan mor cizgiyi kaldir
  for (const sid of Object.keys(dronKartlar)) {
    const kart = dronKartlar[sid];
    if (kart && kart.baslik) kart.baslik.classList.remove("takip-mor");
  }
  // 2) Aktif takipler: mor cizgi + kartlari alt alta getir
  for (const tk of dronTakipler) {
    const hedefKart = dronKartlar[tk.hedef_sysid];
    const takipciKart = dronKartlar[tk.takipci_sysid];
    if (hedefKart && hedefKart.baslik)
      hedefKart.baslik.classList.add("takip-mor");
    if (takipciKart && takipciKart.baslik)
      takipciKart.baslik.classList.add("takip-mor");
    // Kart tasima: yalniz her iki kart da panel icindeyken (ayrik degil)
    if (hedefKart && takipciKart &&
        !hedefKart.kok.classList.contains("ayrik") &&
        !takipciKart.kok.classList.contains("ayrik") &&
        hedefKart.kok.parentNode === dronKartListesi &&
        takipciKart.kok.parentNode === dronKartListesi) {
      // Takipci karti hedef kartin hemen ardina yerlestir
      if (hedefKart.kok.nextSibling !== takipciKart.kok) {
        dronKartListesi.insertBefore(takipciKart.kok,
                                     hedefKart.kok.nextSibling);
      }
    }
  }
}

// Takip Et popup'i: hedef dron secimi + irtifa farki + mesafe sliderlari
function dkTakipPopupAc(anka, takipciSysid) {
  const kimlik = "dkPopupTakip_" + takipciSysid;
  if (dkPopupTekil(kimlik)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = kimlik;
  pop.className = "dk-mini-popup";
  dkMiniPopupBaslikKur(pop, t.dkTakipEt || "Takip Et",
    null, "fa-people-arrows");
  dkPopupOneGetirKur(pop);

  // Hedef dron secimi (kendisi haric, bagli dronlar)
  const hedefSatir = document.createElement("div");
  hedefSatir.className = "dk-mp-satir";
  const hedefEtiket = document.createElement("span");
  hedefEtiket.className = "dk-mp-etiket";
  hedefEtiket.textContent = t.dkTakipHedefSec || "Takip Edilecek Dron";
  hedefSatir.appendChild(hedefEtiket);
  pop.appendChild(hedefSatir);

  const sec = document.createElement("select");
  sec.className = "dk-mp-input";
  let adayVar = false;
  for (const sid of Object.keys(sonVeri)) {
    const nsid = Number(sid);
    if (nsid === Number(takipciSysid)) continue;
    const dd = sonVeri[sid];
    if (!dd || !dd.baglanti) continue;
    const opt = document.createElement("option");
    opt.value = String(nsid);
    const ad = dd.kullanici_isim || dd.isim || dd.tip || ("SYS" + nsid);
    opt.textContent = "D" + nsid + " | " + ad;
    sec.appendChild(opt);
    adayVar = true;
  }
  if (!adayVar) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = t.dkTakipYok || "Uygun dron yok";
    sec.appendChild(opt);
  }
  pop.appendChild(sec);

  // Slider yardimcisi: etiket + deger + range (-100..+100)
  function sliderSatir(etiketYazi, varsayilan) {
    const satir = document.createElement("div");
    satir.className = "dk-mp-satir";
    const etiket = document.createElement("span");
    etiket.className = "dk-mp-etiket";
    etiket.textContent = etiketYazi;
    const deger = document.createElement("span");
    deger.className = "dk-mp-deger";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = -100; slider.max = 100; slider.step = 1;
    slider.value = varsayilan;
    const guncelle = () => {
      const v = parseFloat(slider.value);
      deger.textContent = (v > 0 ? "+" : "") + v.toFixed(0) + " m";
    };
    slider.addEventListener("input", guncelle);
    guncelle();
    satir.appendChild(etiket);
    satir.appendChild(deger);
    pop.appendChild(satir);
    pop.appendChild(slider);
    return slider;
  }
  const irtifaSlider = sliderSatir(t.dkTakipIrtifaFark || "\u0130rtifa Fark\u0131", 0);
  const mesafeSlider = sliderSatir(t.dkTakipMesafe || "Takip Mesafesi", 20);

  // Mesafe aciklamasi (+ geride / - onde)
  const not = document.createElement("div");
  not.className = "dk-mp-satir";
  not.innerHTML = "<span class='dk-mp-etiket' style='font-size:10px;opacity:0.7'>" +
    (t.dkTakipNot || "+ mesafe: geride, - mesafe: \u00f6nde u\u00e7ar") + "</span>";
  pop.appendChild(not);

  // TAKIP ET dugmesi
  const btn = document.createElement("button");
  btn.className = "dk-mp-gonder";
  btn.innerHTML = "<i class='fa-solid fa-people-arrows'></i> " + "<span>" + (
    (t.dkTakipBaslat || "TAK\u0130B\u0130 BA\u015eLAT")) + "</span>";
  btn.addEventListener("click", () => {
    const hedef = parseInt(sec.value, 10);
    if (!hedef) return;
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({
        tip: "takip_baslat",
        takipci_sysid: Number(takipciSysid),
        hedef_sysid: hedef,
        irtifa_fark: parseFloat(irtifaSlider.value),
        mesafe: parseFloat(mesafeSlider.value),
      }));
    }
    pop.remove();
  });
  pop.appendChild(btn);

  pop.style.position = "fixed";
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, anka);
}

// Slider'li mini popup: baslik + slider + deger + GONDER dugmesi
function dkSliderPopup(anka, baslikYazi, ayarlar, gonderYazi, gonderCb) {
  // Tekil kimlik: ayni baslikli slider popup'in kopyasini onle
  const kimlik = "dkPopupSlider_" + baslikYazi.replace(/[^a-zA-Z0-9]/g, "_");
  if (dkPopupTekil(kimlik)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = kimlik;
  pop.className = "dk-mini-popup";
  dkMiniPopupBaslikKur(pop, baslikYazi, null, "fa-sliders");
  dkPopupOneGetirKur(pop);

  const girdiler = [];
  for (const a of ayarlar) {
    const satir = document.createElement("div");
    satir.className = "dk-mp-satir";
    const etiket = document.createElement("span");
    etiket.className = "dk-mp-etiket";
    etiket.textContent = a.etiket;
    const deger = document.createElement("span");
    deger.className = "dk-mp-deger";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = a.min; slider.max = a.max;
    slider.step = a.adim;
    // v2.4.38: a.deger null/undefined ise DEGER BILINMIYOR demektir.
    // Eskiden cagiran taraf uydurma bir varsayilan veriyordu; kullanici
    // bunu dronun mevcut ayari sanip UYGULA'ya basinca ayari farkinda
    // olmadan degistirebiliyordu. Artik bos gelir, gonderilmez.
    const bosMu = (a.deger === null || a.deger === undefined ||
                   !isFinite(Number(a.deger)));
    slider.value = bosMu ? a.min : a.deger;
    let dokunuldu = !bosMu;
    if (bosMu) satir.classList.add("dk-mp-bos");
    const guncelle = () => {
      if (!dokunuldu) {
        deger.textContent = t.dkParamDegerYok || "—";
        deger.classList.add("dk-mp-deger-yok");
        return;
      }
      deger.classList.remove("dk-mp-deger-yok");
      let yazi = parseFloat(slider.value).toFixed(a.hane) + " " + a.birim;
      if (a.birim === "m/s")
        yazi += " (" + (parseFloat(slider.value) * 3.6).toFixed(1) + " km/h)";
      deger.textContent = yazi;
    };
    slider.addEventListener("input", () => {
      // Bos alan kullanici tarafindan oynatilinca aktiflesir
      dokunuldu = true;
      satir.classList.remove("dk-mp-bos");
      guncelle();
    });
    guncelle();
    satir.appendChild(etiket);
    satir.appendChild(deger);
    pop.appendChild(satir);
    pop.appendChild(slider);
    girdiler.push({ ad: a.ad, slider,
                    dokunulduMu: () => dokunuldu });
  }

  const btn = document.createElement("button");
  btn.className = "dk-mp-gonder";
  btn.innerHTML = "<i class='fa-solid fa-check'></i> " + "<span>" + ( gonderYazi) + "</span>";
  btn.addEventListener("click", () => {
    const degerler = {};
    // v2.4.38: dokunulmamis bos alan GONDERILMEZ. Bilinmeyen bir degeri
    // slider'in alt sinirina cekip drona yazmak, ayari sessizce bozardi.
    for (const g of girdiler) {
      if (!g.dokunulduMu || g.dokunulduMu())
        degerler[g.ad] = parseFloat(g.slider.value);
    }
    gonderCb(degerler);
    pop.remove();
  });
  pop.appendChild(btn);

  // Konumlandir: body'ye fixed eklenir ki kartin overflow:hidden
  // kurallari popup'i kirpmasin. anka {x,y} mouse konumu da olabilir.
  pop.style.position = "fixed";
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, anka);
}

function dronKomutToolbarOlustur(sysid, kok) {
  const t = D();
  const bar = document.createElement("div");
  bar.className = "dk-toolbar";

  function dugme(ikon, tip, tooltip, cb) {
    const b = document.createElement("button");
    b.className = "dk-tb-btn " + tip;
    b.title = tooltip;
    b.innerHTML = "<i class='fa-solid " + ikon + "'></i>";
    b.addEventListener("click", (ev) => { ev.stopPropagation(); cb(b); });
    bar.appendChild(b);
    return b;
  }


  // ---------------------------------------------------------------
  // v2.5.0: ARM SECIMI (normal / zorla)
  // ---------------------------------------------------------------
  // Zorla arm, ucus denetleyicisinin arm oncesi guvenlik
  // denetimlerini ATLATIR (param2 = 21196). Bu yuzden iki adimli
  // sunulur: once secim, zorla secilirse IKINCI ve daha sert onay.
  //
  // onayIste(mesaj, onOnay, onIptal) imzasi ikinci eylem dugmesi
  // desteklemedigi ve alti dosya tarafindan kullanildigi icin
  // secim ayri hafif bir pencerede yapilir.
  function dkArmSecimAc(sysid, capa) {
    const t = D();
    const eski = document.getElementById("dkArmSecim");
    if (eski) eski.remove();

    const perde = document.createElement("div");
    perde.id = "dkArmSecim";
    perde.className = "dk-arm-perde";

    const kart = document.createElement("div");
    kart.className = "dk-arm-kart";

    const bas = document.createElement("div");
    bas.className = "dk-arm-baslik";
    bas.textContent = t.dkArmSecimBaslik || "ARM";
    kart.appendChild(bas);

    const not = document.createElement("div");
    not.className = "dk-arm-not";
    not.textContent = t.dkArmSecimNot ||
      "Arm bicimini secin.";
    kart.appendChild(not);

    function secenek(etiket, aciklama, tehlikeli, cb) {
      const b = document.createElement("button");
      b.className = "dk-arm-sec" + (tehlikeli ? " tehlikeli" : "");
      const e = document.createElement("span");
      e.className = "dk-arm-sec-et";
      e.textContent = etiket;
      const a = document.createElement("span");
      a.className = "dk-arm-sec-ac";
      a.textContent = aciklama;
      b.appendChild(e); b.appendChild(a);
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        perde.remove();
        cb();
      });
      kart.appendChild(b);
      return b;
    }

    // Normal arm: mevcut davranis, degismedi
    secenek(t.dkArmNormal || "Normal arm",
      t.dkArmNormalAc || "Ucus denetleyicisinin denetimleri uygulanir.",
      false,
      () => onayIste(onayMetni("onayArm"),
        () => dronKomutGonder(sysid, "arm")));

    // Zorla arm: IKINCI onay
    secenek(t.dkArmZorla || "Zorla arm",
      t.dkArmZorlaAc || "Denetimler atlatilir.",
      true,
      () => onayIste(t.dkArmZorlaOnay ||
        "Arm oncesi guvenlik denetimleri ATLATILACAK. " +
        "Aracin ucusa hazir oldugunu kendiniz dogruladiniz mi?",
        () => dronKomutGonder(sysid, "arm_zorla")));

    const iptal = document.createElement("button");
    iptal.className = "dk-arm-iptal";
    iptal.textContent = t.onayIptalBtn || t.dkParamIptal || "IPTAL";
    iptal.addEventListener("click", (ev) => {
      ev.stopPropagation(); perde.remove();
    });
    kart.appendChild(iptal);

    perde.appendChild(kart);
    perde.addEventListener("click", (ev) => {
      if (ev.target === perde) perde.remove();
    });
    document.body.appendChild(perde);

    // Capa ogesi verildiyse yaninda ac, yoksa ortada
    if (capa && capa.getBoundingClientRect) {
      const r = capa.getBoundingClientRect();
      kart.style.position = "fixed";
      kart.style.left = Math.max(8, Math.min(
        window.innerWidth - 300, r.left)) + "px";
      kart.style.top = Math.max(8, Math.min(
        window.innerHeight - 240, r.bottom + 6)) + "px";
    }
    return perde;
  }
  window.dkArmSecimAc = dkArmSecimAc;

  // v2.5.0: arm dugmesi artik bicim secimi acar (normal / zorla)
  const btnArm = dugme("fa-lock-open", "arm", t.dkArm,
    (b) => dkArmSecimAc(sysid, b));
  const btnDisarm = dugme("fa-lock", "disarm", t.dkDisarmBtn,
    () => onayIste(onayMetni("onayDisarm"),
      () => dronKomutGonder(sysid, "disarm")));

  const btnTakeoff = dugme("fa-plane-departure", "takeoff", t.dkTakeoff, (b) => {
    dkSliderPopup(b, D().dkTakeoffIrtifa, [
      { ad: "irtifa", etiket: D().dkTakeoffIrtifa, min: 2, max: 200,
        adim: 1, deger: 10, birim: "m", hane: 0 },
    ], D().dkTakeoff.toUpperCase(), (v) =>
      // v2.4.41: bu ikinci takeoff girisi de ayni zorunlu kontrol
      // listesinden gecer (bkz. dkTakeoffKontrolListesi)
      dkTakeoffKontrolListesi(sysid, v.irtifa, b));
  });

  const btnLand = dugme("fa-plane-arrival", "land", t.dkLand,
    () => onayIste(onayMetni("onayLand"),
      () => dronKomutGonder(sysid, "land")));

  const btnIrtifa = dugme("fa-arrows-up-down", "altitude", t.dkIrtifaDegistir, (b) => {
    const dd = sonVeri[sysid];
    const mevcut = (dd && dd.alt_rel > 1) ? Math.round(dd.alt_rel) : 10;
    dkSliderPopup(b, D().dkHedefIrtifa, [
      { ad: "irtifa", etiket: D().dkHedefIrtifa, min: 2, max: 500,
        adim: 1, deger: mevcut, birim: "m", hane: 0 },
    ], D().dkGonder, (v) =>
      dronKomutGonder(sysid, "altitude_change", v.irtifa));
  });

  const btnRth = dugme("fa-house", "rtl", t.dkRth,
    () => onayIste(onayMetni("onayRtl"),
      () => dronKomutGonder(sysid, "rtl")));

  // v2.4.20: "Rotaya Gonder" -> "Rotayi Yukle" (yalnizca yukleme)
  const btnGorev = dugme("fa-cloud-arrow-up", "gorev",
      t.dkRotayiYukle || t.dkRotayaGonder, () => {
    if (typeof window.gorevRotaSecimAc === "function")
      window.gorevRotaSecimAc(sysid);
  });

  const btnFokus = dugme("fa-location-crosshairs", "fokus", t.dkFokus,
    () => dronaGit(sysid));

  const btnAyar = dugme("fa-gear", "ayar", t.dkAyar, (b) => {
    dronAyarPopupAc(b, sysid);
  });

  // --- PARAMETRE LISTESI DUGMESI ---
  const btnParam = dugme("fa-sliders", "param", t.dkParametreler || "Parametreler",
    () => dkParamPopupAc(sysid));

  // --- DRON DUZENLE (isim verme) DUGMESI ---
  const btnDuzenle = dugme("fa-pen", "duzenle", t.dkDuzenle || "Dronu D\u00fczenle", (b) => {
    dkIsimDuzenlePopup(b, sysid);
  });

  const btnAngaje = dugme("fa-tower-broadcast", "angaje",
    t.angTelemetriSecenek || "Telemetri ile Angajman",
    () => angajmanPopupAc("dron", sysid));

  kok._tb = { arm: btnArm, disarm: btnDisarm, takeoff: btnTakeoff,
              land: btnLand, irtifa: btnIrtifa, rth: btnRth,
              gorev: btnGorev, fokus: btnFokus, ayar: btnAyar,
              param: btnParam, duzenle: btnDuzenle, angaje: btnAngaje };
  return bar;
}

// ---------------------------------------------------------------
// KARTI TASINABILIR POPUP'A AYIRMA / GERI YERLESTIRME
// ---------------------------------------------------------------
// IS153: yuzen dron panelinin boyutunu dron bazinda sakla/uygula
const DP_BOYUT_ON = "gcs_dpanel_boyut_";
function dronPanelBoyutKaydet(sysid, kok) {
  try {
    if (!kok.classList.contains("ayrik")) return;
    if (kok.classList.contains("dk-yalniz-baslik")) return;
    const r = kok.getBoundingClientRect();
    const w = Math.round(r.width);
    if (w < 240) return;
    // IS159: yalniz genislik saklanir (yukseklik icerige gore otomatik)
    localStorage.setItem(DP_BOYUT_ON + sysid, JSON.stringify({ w: w }));
  } catch (e) {}
}
function dronPanelBoyutUygula(sysid, kok) {
  try {
    const s = JSON.parse(localStorage.getItem(DP_BOYUT_ON + sysid) || "null");
    if (s && s.w) {
      kok.style.width = s.w + "px";   // IS159: yalniz genislik; yukseklik otomatik
      kok.style.height = "";
    }
  } catch (e) {}
}
function dronPanelResizeKur(sysid, kart) {
  if (typeof ResizeObserver === "undefined" || kart._resizeGozlemci) return;
  let zam = null;
  const ro = new ResizeObserver(() => {
    const kok = kart.kok;
    if (!kok.classList.contains("ayrik")) return;
    // Uçuş göstergesini (PFD) pencere boyutuna göre ANINDA yeniden çiz
    const d = sonVeri[sysid];
    if (d && kart.gosterge && typeof kart.gosterge.ciz === "function") {
      try { kart.gosterge.ciz(d); } catch (e) {}
    }
    clearTimeout(zam);
    zam = setTimeout(() => dronPanelBoyutKaydet(sysid, kok), 400);
  });
  ro.observe(kart.kok);
  kart._resizeGozlemci = ro;
}

function dronKartAyirToggle(sysid) {
  const kart = dronKartlar[sysid];
  if (!kart) return;
  const kok = kart.kok;
  const t = D();
  if (kok.classList.contains("ayrik")) {
    // GERI YERLESTIR: panele geri don (kompakt gorunum de sifirlanir)
    kok.classList.remove("ayrik");
    kok.classList.remove("kompakt");
    kok.classList.remove("dk-yalniz-baslik");
    if (kok._btnKucult) kok._btnKucult.innerHTML = DK_KUCULT_IKON;
    kok.style.left = ""; kok.style.top = "";
    kok.style.width = ""; kok.style.height = "";   // IS153: panelde sabit boyut
    // v2.4.224: panelde duran golge satirin yerine kart geri konur.
    if (kart.golge && kart.golge.parentNode) {
      kart.golge.replaceWith(kok);
    } else if (!(typeof window.dronKartiGrubaYerlestir === "function" &&
          window.dronKartiGrubaYerlestir(sysid, kok)))
      dronKartListesi.appendChild(kok);
    kart.golge = null; kart.golgeBaslik = null;
    // FAZ18-IS27-28-30: panele donen kart KAPALI duruma alinir.
    // Onceki surum yalniz `ayrik`/`kompakt` siniflarini kaldiriyordu,
    // kart panele ACIK donuyordu; bu, "panel icinde yalniz baslik
    // gorunsun" sozlesmesini ihlal ediyordu.
    kart.baslik.classList.add("kapali");
    kart.govde.classList.add("gizli");
    if (kok._btnAyir) {
      // v2.4.224: ikon her iki durumda da KAPAT (carpi); panelde CSS gizler.
      kok._btnAyir.title = t.dkPencereKapat || t.dkAyir;
      kok._btnAyir.innerHTML = DK_KAPAT_IKON;
    }
    // v2.4.35: ok ipucusu (kart geri yerlesirken kapali/acik degismis olabilir)
    dkOkTazele(kart.baslik, kok.querySelector(".dk-ok"));
  } else {
    // AYIR: tasinabilir popup yap (mevcut ekran konumunda ac)
    const rect = kok.getBoundingClientRect();
    // v2.4.224 (kullanici istegi): kart LISTEDEN CIKMAZ — yerine yalniz
    // basligi tasiyan GOLGE satir konur; tiklaninca acik pencere one alinir.
    if (kok.parentNode) {
      const golge = document.createElement("div");
      golge.className = "dron-kart dk-golge";
      golge.dataset.sysid = String(sysid);
      const gb = kart.baslik.cloneNode(true);
      gb.querySelectorAll(".dk-ayir-btn, .dk-kucult-btn, .dk-ok").forEach((x) => x.remove());
      gb.classList.add("kapali");
      golge.appendChild(gb);
      golge.addEventListener("click", () => {
        if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(kok);
        kok.classList.add("dk-vurgu"); setTimeout(() => kok.classList.remove("dk-vurgu"), 600);
      });
      kok.parentNode.insertBefore(golge, kok);
      kart.golge = golge; kart.golgeBaslik = gb;
    }
    kok.classList.add("ayrik");
    // Govde kapali ise ac (popup'ta icerik gorunmeli)
    kart.baslik.classList.remove("kapali");
    kart.govde.classList.remove("gizli");
    document.body.appendChild(kok);
    // Kayitli konum varsa oradan ac; yoksa mevcut ekran konumunda
    if (!(typeof window.pencereKonumUygula === "function" &&
          window.pencereKonumUygula("dron_" + sysid, kok))) {
      kok.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 356)) + "px";
      kok.style.top = Math.max(8, Math.min(rect.top, window.innerHeight - 200)) + "px";
    }
    dronPanelBoyutUygula(sysid, kok);   // IS153: kayitli boyut varsa uygula
    kok.dataset.sysid = String(sysid);
    // v2.2.0: ayrilan kart en uste acilir; tiklaninca da en uste gelir
    if (typeof window.pencereEnUsteKur === "function") window.pencereEnUsteKur(kok);
    if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(kok);
    if (kok._btnAyir) {
      // v2.4.224: yuzen panelde KAPAT (carpi) — paneli kapatir, kart panele doner.
      kok._btnAyir.title = t.dkPencereKapat || t.dkYerlestir;
      kok._btnAyir.innerHTML = DK_KAPAT_IKON;
    }
    // v2.4.35: ayrilan kart acik gelir; ok ipucusu buna gore
    dkOkTazele(kart.baslik, kok.querySelector(".dk-ok"));
  }
  // v2.4.33: ayri Dronlar paneli kaldirildi; bos durum notu artik
  // her baglanti grubunun kendi govdesinde yasiyor.
  if (typeof window.bagGruplariDoldur === "function")
    window.bagGruplariDoldur();
}

// v2.4.35: ok ikonunun ipucu metnini duruma gore tazele.
// IKON YONU BURADA DEGISTIRILMEZ: donusu CSS yapiyor
// (.dron-kart-baslik.kapali .dk-ok { transform: rotate(-90deg) }).
// Burada ayrica fa-chevron-down -> fa-chevron-right degistirilseydi
// iki etki ust uste binerdi: saga bakan ikon bir de -90 dondurulup
// YUKARI bakardi. Yalniz baslik (ipucu) guncellenir.
// v2.4.224: yuzen pencere acikken panelde kalan golge satirin basligini
// gercek basliktan kopyalar (durum sinifi, LED, ad, ozet, renk karesi).
function dkGolgeTazele(kart) {
  const gb = kart.golgeBaslik;
  if (!gb) return;
  gb.className = kart.baslik.className.replace(/\bkapali\b/g, "").trim() + " kapali";
  const kaynak = kart.baslik, hedef = gb;
  const cift = [[".dk-nokta", "style"], [".dk-renk-kare", "style"], [".dk-ad", "text"], [".dk-baslik-ozet", "html"]];
  for (const [sec, tur] of cift) {
    const a = kaynak.querySelector(sec), b = hedef.querySelector(sec);
    if (!a || !b) continue;
    if (tur === "style") b.setAttribute("style", a.getAttribute("style") || "");
    else if (tur === "text") { b.textContent = a.textContent; b.setAttribute("style", a.getAttribute("style") || ""); }
    else if (b.innerHTML !== a.innerHTML) b.innerHTML = a.innerHTML;
  }
}

function dkOkTazele(baslik, ok) {
  if (!ok) return;
  const kapali = baslik.classList.contains("kapali");
  const t = D();
  ok.title = kapali ? (t.dkPaneliAc || "Paneli a\u00e7")
                    : (t.dkPaneliKapat || "Paneli kapat");
}

// =================================================================
// v2.4.45: DRON BASINA HABERLESME KONSOLU
// Kullanici istegi: dronun MAVLink/komut/STATUSTEXT satirlari genel
// konsolu kirletmesin; her dronun KENDI panelinin altinda acilir
// kapanir bir konsolda CIPLAK olarak gorunsun.
//
// Tasarim kararlari:
//  - Tampon backend'de (dron.py, 200 satir/dron) tutulur. Panel kapali
//    hatta arayuz hic acilmamis olsa bile satirlar birikir; kullanici
//    konsolu ilk actiginda gecmis HAZIR gelir (bir kez istenir).
//  - Satirlar DOM'da da sinirlanir (DK_KONSOL_DOM_LIMIT); uzun ucusta
//    binlerce dugum birikip sayfayi yavaslatmasin.
//  - Otomatik kaydirma yalniz kullanici EN ALTTAYSA yapilir; yukari
//    kaydirip bir satiri okuyan kullaniciyi zorla asagi atmak, bu
//    konsolun tek isini (hata ayiklama) imkansiz kilardi.
//  - Ayni metin ust uste gelirse backend `tekrar` sayacini artirir;
//    arayuz mevcut satirin sonuna "xN" rozeti basar, yeni satir
//    EKLEMEZ. Boylece "link kayip" gibi saniyede bir tekrarlayan
//    uyarilar konsolu bogmaz.
// =================================================================
const DK_KONSOL_DOM_LIMIT = 400;
const DK_KONSOL_SEV_SINIF = {
  bilgi: "dk-kons-bilgi", basari: "dk-kons-basari",
  uyari: "dk-kons-uyari", hata: "dk-kons-hata"
};

function dkKonsolBolumuKur(sysid) {
  const t = D();
  const kok = document.createElement("div");
  kok.className = "dk-konsol";

  // --- Basligi (tiklanabilir seritt) ---
  const bas = document.createElement("div");
  bas.className = "dk-konsol-bas kapali";
  const ok = document.createElement("i");
  ok.className = "fa-solid fa-chevron-down dk-konsol-ok";
  const ikon = document.createElement("i");
  ikon.className = "fa-solid fa-terminal dk-konsol-ikon";
  const ad = document.createElement("span");
  ad.className = "dk-konsol-ad";
  ad.textContent = t.dkKonsolBaslik || "Haberleşme konsolu";
  const sayac = document.createElement("span");
  sayac.className = "dk-konsol-sayac";
  sayac.textContent = "0";
  bas.appendChild(ok); bas.appendChild(ikon);
  bas.appendChild(ad); bas.appendChild(sayac);

  // --- Araclar (durdur / temizle) ---
  const araclar = document.createElement("span");
  araclar.className = "dk-konsol-araclar";
  const btnDur = document.createElement("button");
  btnDur.type = "button";
  btnDur.className = "dk-konsol-btn";
  btnDur.innerHTML = '<i class="fa-solid fa-pause"></i>';
  btnDur.title = t.dkKonsolDurdur || "Akışı duraklat";
  const btnTemiz = document.createElement("button");
  btnTemiz.type = "button";
  btnTemiz.className = "dk-konsol-btn";
  btnTemiz.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
  btnTemiz.title = t.dkKonsolTemizle || "Konsolu temizle";
  araclar.appendChild(btnDur); araclar.appendChild(btnTemiz);
  bas.appendChild(araclar);

  // --- Govde (satirlar) ---
  const govde = document.createElement("div");
  govde.className = "dk-konsol-govde gizli";

  kok.appendChild(bas); kok.appendChild(govde);

  const api = {
    kok, bas, govde, ad, sayac, ok, btnDur, btnTemiz,
    acik: false, duraklat: false, gecmisIstendi: false,
    adet: 0, sonMetin: null, sonSatirEl: null
  };

  // Baslik tiklaninca ac/kapa. Araclara tiklama basligi tetiklemez.
  bas.addEventListener("click", (e) => {
    if (e.target.closest(".dk-konsol-araclar")) return;
    dkKonsolAcKapa(sysid);
  });
  btnDur.addEventListener("click", (e) => {
    e.stopPropagation();
    api.duraklat = !api.duraklat;
    btnDur.innerHTML = api.duraklat
      ? '<i class="fa-solid fa-play"></i>'
      : '<i class="fa-solid fa-pause"></i>';
    btnDur.classList.toggle("etkin", api.duraklat);
    const tt = D();
    btnDur.title = api.duraklat
      ? (tt.dkKonsolSurdur || "Akışı sürdür")
      : (tt.dkKonsolDurdur || "Akışı duraklat");
  });
  btnTemiz.addEventListener("click", (e) => {
    e.stopPropagation();
    if (typeof ws !== "undefined" && ws && ws.readyState === 1)
      ws.send(JSON.stringify({tip: "dron_konsol_temizle", sysid: sysid}));
    govde.innerHTML = "";
    api.adet = 0; api.sonMetin = null; api.sonSatirEl = null;
    sayac.textContent = "0";
  });
  return api;
}

function dkKonsolAcKapa(sysid) {
  const kart = dronKartlar[sysid];
  if (!kart || !kart.konsol) return;
  const k = kart.konsol;
  k.acik = !k.acik;
  k.bas.classList.toggle("kapali", !k.acik);
  k.govde.classList.toggle("gizli", !k.acik);
  k.ok.style.transform = k.acik ? "" : "rotate(-90deg)";
  if (k.acik) {
    // Gecmis YALNIZ bir kez istenir; sonrasinda canli akis surer.
    if (!k.gecmisIstendi &&
        typeof ws !== "undefined" && ws && ws.readyState === 1) {
      k.gecmisIstendi = true;
      ws.send(JSON.stringify({tip: "dron_konsol_gecmis", sysid: sysid}));
    }
    k.govde.scrollTop = k.govde.scrollHeight;
  }
}

// Tek satiri DOM'a basar. `yeni=false` gelen kayit, ayni metnin
// TEKRARIDIR: yeni satir eklenmez, mevcut satirin rozeti guncellenir.
// FAZ18-IS27-28-30: konsol zaman damgasi bicimleyici.
// Epoch saniye -> yerel "HH:MM:SS". Gecersiz/eksik degerde BOS dize
// doner; `new Date(0)` 1970'i verip konsolda "03:00:00" gosterecegi
// icin sifir da gecersiz sayilir (yanlis bilgi gostermek, bos
// gostermekten kotudur). Zaten dize gelen eski kayitlar oldugu gibi
// gecirilir.
function dkKonsolSaat(ts) {
  if (ts === null || ts === undefined || ts === "") return "";
  if (typeof ts === "string") {
    const s = Number(ts);
    if (!isFinite(s) || s <= 0) return ts;   // bicimli dize: oldugu gibi
    ts = s;
  }
  if (typeof ts !== "number" || !isFinite(ts) || ts <= 0) return "";
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return "";
  const iki = (n) => String(n).padStart(2, "0");
  return iki(d.getHours()) + ":" + iki(d.getMinutes()) + ":" +
         iki(d.getSeconds());
}
function dkKonsolSatirBas(k, s) {
  if (s && s.yeni === false && k.sonSatirEl &&
      k.sonMetin === (s.etiket + "\u0000" + s.metin)) {
    let roz = k.sonSatirEl.querySelector(".dk-kons-tekrar");
    if (!roz) {
      roz = document.createElement("span");
      roz.className = "dk-kons-tekrar";
      k.sonSatirEl.appendChild(roz);
    }
    roz.textContent = "×" + (s.tekrar || 2);
    return;
  }
  const el = document.createElement("div");
  el.className = "dk-kons-satir " +
    (DK_KONSOL_SEV_SINIF[s.sev] || DK_KONSOL_SEV_SINIF.bilgi);
  const zs = document.createElement("span");
  zs.className = "dk-kons-ts";
  // FAZ18-IS27-28-30: ham epoch yerine yerel HH:MM:SS.
  // Sunucu (dron.py konsol_ekle) `ts` alanini time.time() ile
  // epoch float uretir; bicimleme ARAYUZDE yapilir cunku (a)
  // epoch istemcinin YEREL saat dilimine cevrilmeli, sunucu
  // bicimlendirirse UTC sabitlenir ve Ankara icin 3 saat sapar,
  // (b) dron.py tekrar tespitinde ts sayisal karsilastiriliyor.
  // Desen konsol.js:80-88 ile AYNI (alan adi farkli: orada s.t).
  zs.textContent = dkKonsolSaat(s.ts);
  const es = document.createElement("span");
  es.className = "dk-kons-etiket";
  es.textContent = s.etiket || "";
  const ms = document.createElement("span");
  ms.className = "dk-kons-metin";
  ms.textContent = s.metin || "";
  el.appendChild(zs); el.appendChild(es); el.appendChild(ms);
  if (s.tekrar && s.tekrar > 1) {
    const roz = document.createElement("span");
    roz.className = "dk-kons-tekrar";
    roz.textContent = "×" + s.tekrar;
    el.appendChild(roz);
  }
  k.govde.appendChild(el);
  k.sonSatirEl = el;
  k.sonMetin = (s.etiket || "") + "\u0000" + (s.metin || "");
  k.adet++;
  while (k.govde.childElementCount > DK_KONSOL_DOM_LIMIT)
    k.govde.removeChild(k.govde.firstElementChild);
}

// ws.js -> {"tip":"dron_konsol_satir","sysid":N,"satir":{...}}
function dronKonsolSatir(m) {
  const kart = dronKartlar[m.sysid];
  if (!kart || !kart.konsol) return;
  const k = kart.konsol;
  k.sayac.textContent = String(Math.min(k.adet + 1, 9999));
  if (k.duraklat) return;
  // Konsol hic acilmadiysa DOM'a yazmaya gerek yok: kullanici actiginda
  // gecmis tek istekte gelir. Boylece 10 dron x 200 satir bosuna
  // DOM dugumu uretmez.
  if (!k.gecmisIstendi) return;
  const dipte = (k.govde.scrollHeight - k.govde.scrollTop -
                 k.govde.clientHeight) < 24;
  dkKonsolSatirBas(k, m.satir || {});
  if (dipte) k.govde.scrollTop = k.govde.scrollHeight;
}

// ws.js -> {"tip":"dron_konsol_gecmis","sysid":N,"satirlar":[...]}
function dronKonsolGecmis(m) {
  const kart = dronKartlar[m.sysid];
  if (!kart || !kart.konsol) return;
  const k = kart.konsol;
  k.govde.innerHTML = "";
  k.adet = 0; k.sonMetin = null; k.sonSatirEl = null;
  (m.satirlar || []).forEach((s) => dkKonsolSatirBas(k, s));
  k.sayac.textContent = String(k.adet);
  k.govde.scrollTop = k.govde.scrollHeight;
}

// Dil degisiminde konsol basligi ve ipuclarini tazele
function dkKonsolDilTazele() {
  const t = D();
  Object.values(dronKartlar).forEach((kart) => {
    const k = kart && kart.konsol;
    if (!k) return;
    k.ad.textContent = t.dkKonsolBaslik || "Haberleşme konsolu";
    k.btnTemiz.title = t.dkKonsolTemizle || "Konsolu temizle";
    k.btnDur.title = k.duraklat
      ? (t.dkKonsolSurdur || "Akışı sürdür")
      : (t.dkKonsolDurdur || "Akışı duraklat");
  });
}
window.dronKonsolSatir = dronKonsolSatir;
window.dronKonsolGecmis = dronKonsolGecmis;
window.dkKonsolDilTazele = dkKonsolDilTazele;

// v2.4.35: katlanan ayrik kart ekran altinda kalmasin
function dkAyrikKonumDuzelt(kok) {
  const y = parseFloat(kok.style.top) || 0;
  const enFazla = window.innerHeight - 40;
  if (y > enFazla) kok.style.top = Math.max(0, enFazla) + "px";
}

// =================================================================
// v2.4.35: AYRIK DRON KARTLARI ICIN MIKNATIS
// Kullanici birden fazla dronun basligi KAPALIYKEN kartlarin
// birbirine yapismasini istedi. widget.js'teki mantik uyarlandi
// ama kayit Map'i widget'lara ozel oldugu icin adaylar DOM'dan
// toplaniyor.
// Yapisma adayligi sarti: HEM tasinan HEM hedef kartin basligi
// kapali olmali. Acik kartlar yanlislikla yapismaz; acik kart
// yuksek oldugu icin yapisma kullaniciya rastgele gelirdi.
// =================================================================
const DK_MIK_ESIK = 18; // px — widget.js ile ayni

function dkKutu(el) {
  return {
    sol: parseFloat(el.style.left) || 0,
    ust: parseFloat(el.style.top) || 0,
    gen: el.offsetWidth,
    yuk: el.offsetHeight
  };
}

// Tasinan kart icin en yakin yapisma noktasini bul
function dkYapismaBul(tasinan, kutu) {
  const adaylar = document.querySelectorAll(".dron-kart.ayrik");
  let enIyi = null;
  adaylar.forEach((ad) => {
    if (ad === tasinan) return;
    const b = ad.querySelector(".dron-kart-baslik");
    if (!b || !b.classList.contains("kapali")) return; // hedef acik
    const h = dkKutu(ad);
    const sag = kutu.sol + kutu.gen, alt = kutu.ust + kutu.yuk;
    const hSag = h.sol + h.gen, hAlt = h.ust + h.yuk;
    // Dikey ortusme (yatay yapisma icin) ve yatay ortusme (dikey icin)
    const dikeyOrtusme = Math.min(alt, hAlt) - Math.max(kutu.ust, h.ust);
    const yatayOrtusme = Math.min(sag, hSag) - Math.max(kutu.sol, h.sol);
    const dene = (dSol, dUst, uzaklik) => {
      if (uzaklik > DK_MIK_ESIK) return;
      if (!enIyi || uzaklik < enIyi.uzaklik)
        enIyi = { dSol, dUst, uzaklik, hedef: ad };
    };
    if (dikeyOrtusme > 0) {
      // Tasinanin solu, hedefin sagina yapissin
      dene(hSag, h.ust, Math.abs(kutu.sol - hSag) + Math.abs(kutu.ust - h.ust) * 0.01);
      // Tasinanin sagi, hedefin soluna
      dene(h.sol - kutu.gen, h.ust,
           Math.abs(sag - h.sol) + Math.abs(kutu.ust - h.ust) * 0.01);
    }
    if (yatayOrtusme > 0) {
      // Tasinanin ustu, hedefin altina
      dene(h.sol, hAlt, Math.abs(kutu.ust - hAlt) + Math.abs(kutu.sol - h.sol) * 0.01);
      // Tasinanin alti, hedefin ustune
      dene(h.sol, h.ust - kutu.yuk,
           Math.abs(alt - h.ust) + Math.abs(kutu.sol - h.sol) * 0.01);
    }
  });
  return enIyi;
}

// Ayrik karti basliktan surukleme (pointer events)
function dronKartSurukleKur(kok, baslik) {
  let surukle = null;
  baslik.addEventListener("pointerdown", (ev) => {
    if (!kok.classList.contains("ayrik")) return;
    // v2.4.35: .dk-ok eklendi. Eklenmezse oka basildiginda surukleme
    // baslar, pointerdown preventDefault edildigi icin click olayi
    // hic olusmaz ve ok ile ac/kapa yine calismaz.
    if (ev.target.closest(".dk-ayir-btn") || ev.target.closest(".dk-kucult-btn") || ev.target.closest(".dk-menu-btn") ||
        ev.target.closest(".dk-joy-btn") || ev.target.closest(".dk-ok")) return;
    const rect = kok.getBoundingClientRect();
    surukle = { dx: ev.clientX - rect.left, dy: ev.clientY - rect.top };
    baslik.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  baslik.addEventListener("pointermove", (ev) => {
    if (!surukle) return;
    let x = ev.clientX - surukle.dx;
    let y = ev.clientY - surukle.dy;
    // Ekran sinirlari icinde tut
    x = Math.max(0, Math.min(x, window.innerWidth - kok.offsetWidth));
    y = Math.max(0, Math.min(y, window.innerHeight - 40));
    // v2.4.35: yalniz basligi KAPALI kartlar miknatislanir
    if (baslik.classList.contains("kapali")) {
      const yap = dkYapismaBul(kok, { sol: x, ust: y,
                                      gen: kok.offsetWidth, yuk: kok.offsetHeight });
      if (yap) {
        x = yap.dSol; y = yap.dUst;
        kok.classList.add("dk-yapisiyor");
      } else {
        kok.classList.remove("dk-yapisiyor");
      }
    }
    kok.style.left = x + "px";
    kok.style.top = y + "px";
  });
  const birak = (ev) => {
    if (!surukle) return;
    surukle = null;
    kok.classList.remove("dk-yapisiyor");
    try { baslik.releasePointerCapture(ev.pointerId); } catch (e) {}
    // Konumu kalici kaydet
    if (kok.dataset.sysid && typeof window.pencereKonumKaydet === "function") {
      window.pencereKonumKaydet("dron_" + kok.dataset.sysid, kok);
    }
  };
  baslik.addEventListener("pointerup", birak);
  baslik.addEventListener("pointercancel", birak);
}

// ---------------------------------------------------------------
// DRON AYARLARI POPUP'I
//
// v2.4.38 DEGISIKLIGI (kullanici istegi):
// Eskiden panel her acilista `param_ara` ile DRONDAN okuyordu ve 2.5
// saniye icinde yanit gelmezse UYDURMA varsayilanlarla aciliyordu
// (yukselme 2.5 / alcalma 1.5 / hareket 5 m/s / RTL 15 m). Iki zarari
// vardi:
//   1) Parametreler bir kez cekilmis olsa bile agdan yeniden isteniyordu.
//   2) Yanit gecikirse panel dronun GERCEK ayarini degil varsayilani
//      gosteriyordu; kullanici bunu mevcut ayar sanip UYGULA'ya basinca
//      ayari farkinda olmadan degistirebiliyordu.
//
// Artik yalnizca ONBELLEKTEN okunur: `param_tumu` + `taze:false`
// (sunucu.py yalnizca DB onbellegini okur, drona istek gondermez).
// Onbellek yoksa alanlar BOS gelir ve bos alan GONDERILMEZ. Drondan
// taze okuma isteyen kullanici Parametreler ekranindaki TUMUNU AL'i
// kullanir - tek dogruluk kaynagi orasidir.
// ---------------------------------------------------------------
let dronAyarParamBekleyen = null; // {sysid, ac, zamanlayici}

// v2.4.13: Interceptor profili - hiz girisleri ust siniri.
// MAVLink'ten hiz parametresi okunursa ust sinir ona gore genisler
// (okunan deger fallback'i asarsa); okunamazsa 300 km/h = 83.3 m/s.
const HIZ_MAKS_MS = 83.3;
function hizUstSinir(okunan) {
  const o = Number(okunan);
  return (isFinite(o) && o > HIZ_MAKS_MS) ? Math.ceil(o) : HIZ_MAKS_MS;
}

// v2.4.38: onbellekten okunan parametre seti (sysid -> {ad: deger})
// Parametreler ekrani TUMUNU AL yaptiginda ya da bu panel onbellek
// okudugunda dolar. Bos kalirsa panel alanlari bos acar.
//
// NOT: `let` ile tanimlanirsa degisken window uzerinde GORUNMEZ (klasik
// script semantigi; olcup dogruladim). O durumda bu dosya disindan
// `window.dronAyarParamOnbellek` yazan her kod AYRI bir nesne olusturur
// ve buradaki onbellek bos kalirdi. Tek nesne olmasi icin dogrudan
// window uzerinde tutulur.
// `const` ile bir kez yakalamak YETMEZ: dis kod `window.dronAyar
// ParamOnbellek = {...}` diyerek nesneyi TUMDEN degistirebilir; o an
// yakalanan referans oksuz kalir. Bu yuzden her erisim window uzerinden
// yapilir - asagidaki islev tek okuma noktasidir.
window.dronAyarParamOnbellek = window.dronAyarParamOnbellek || {};
function dronAyarOnbellek() {
  if (!window.dronAyarParamOnbellek ||
      typeof window.dronAyarParamOnbellek !== "object")
    window.dronAyarParamOnbellek = {};
  return window.dronAyarParamOnbellek;
}

// v2.4.38: ham ArduPilot setinden UI degerlerini turetir.
// Eksik parametre icin null doner (uydurma varsayilan YOK).
function dronAyarUiDegerler(p) {
  const sayi = (x) => {
    const n = Number(x);
    return (x === undefined || x === null || !isFinite(n)) ? null : n;
  };
  const bol = (x, k) => {
    const n = sayi(x);
    return n === null ? null : n / k;
  };
  const sinirla = (x, min, max) =>
    x === null ? null : Math.min(max, Math.max(min, x));
  const yuk = bol(p.WPNAV_SPEED_UP, 100);
  const alc = bol(p.WPNAV_SPEED_DN, 100);
  const har = bol(p.WPNAV_SPEED, 100);
  const rtl = bol(p.RTL_ALT, 100);
  return {
    yukselme_hizi: sinirla(yuk, 0.5, hizUstSinir(yuk)),
    alcalma_hizi:  sinirla(alc, 0.5, hizUstSinir(alc)),
    hareket_hizi:  sinirla(har, 0.5, hizUstSinir(har)),
    rtl_irtifa:    sinirla(rtl, 2, 200),
  };
}
window.dronAyarUiDegerler = dronAyarUiDegerler;

function dronAyarPopupAc(anka, sysid) {
  const t = D();
  // v2.4.38: uydurma varsayilan YOK. Onbellekte olmayan alan null kalir,
  // panelde "—" gorunur ve UYGULA'da GONDERILMEZ.
  const bos = { yukselme_hizi: null, alcalma_hizi: null,
                hareket_hizi: null, rtl_irtifa: null };
  const ac = (v) => {
    dkSliderPopup(anka, t.dkAyar, [
      { ad: "yukselme_hizi", etiket: t.dkYukselmeHizi, min: 0.5,
        max: hizUstSinir(v.yukselme_hizi),
        adim: 0.5, deger: v.yukselme_hizi, birim: "m/s", hane: 1 },
      { ad: "alcalma_hizi", etiket: t.dkAlcalmaHizi, min: 0.5,
        max: hizUstSinir(v.alcalma_hizi),
        adim: 0.5, deger: v.alcalma_hizi, birim: "m/s", hane: 1 },
      { ad: "hareket_hizi", etiket: t.dkHareketHizi, min: 0.5,
        max: hizUstSinir(v.hareket_hizi),
        adim: 0.5, deger: v.hareket_hizi, birim: "m/s", hane: 1 },
      { ad: "rtl_irtifa", etiket: t.dkRtlIrtifa, min: 2, max: 200,
        adim: 1, deger: v.rtl_irtifa, birim: "m", hane: 0 },
    ], t.dkUygula, (dv) => {
      const adlar = Object.keys(dv);
      if (!adlar.length) {
        // Hicbir alan doldurulmadi: sessizce hicbir sey gonderme
        if (typeof konsolYaz === "function")
          konsolYaz("PARAM", t.dkAyarBosGonderim ||
            "Deger girilmedi - drona hicbir parametre gonderilmedi.",
            "uyari");
        return;
      }
      for (const ad of adlar) dronParamGonder(sysid, ad, dv[ad]);
    });
  };

  // 1) Bellekte onbellek varsa DOGRUDAN ac - ag istegi YOK
  const bellek = dronAyarOnbellek()[sysid];
  if (bellek) { ac(dronAyarUiDegerler(bellek)); return; }

  // 2) Parametreler ekrani bu dron icin tam set cektiyse onu kullan.
  //    NOT: `_paramTumSet` / `_paramPopupSysid` bu dosyada DAHA ASAGIDA
  //    `let` ile tanimli. `let` hoisting yapmadigi icin (TDZ) dogrudan
  //    ya da `typeof` ile erismek, bu islev tanimdan ONCE cagrilirsa
  //    ReferenceError firlatir - olcup dogruladim. `window.` uzerinden
  //    okumak her iki durumda da guvenlidir.
  const tumSet = window._paramTumSet;
  if (tumSet && typeof tumSet === "object" &&
      window._paramPopupSysid === sysid && ("WPNAV_SPEED" in tumSet)) {
    dronAyarOnbellek()[sysid] = tumSet;
    ac(dronAyarUiDegerler(tumSet));
    return;
  }

  // 3) Sunucudaki DB onbellegini iste (taze:false -> drona GITMEZ).
  //    Onbellek bossa bos liste doner ve panel bos alanlarla acilir.
  if (!ws || ws.readyState !== 1) { ac(bos); return; }
  dronAyarParamBekleyen = { sysid: sysid, ac: ac };
  dronAyarParamBekleyen.zamanlayici = setTimeout(() => {
    if (dronAyarParamBekleyen) {
      const b = dronAyarParamBekleyen; dronAyarParamBekleyen = null;
      b.ac(bos);   // varsayilan DEGIL, bos
    }
  }, 1500);
  ws.send(JSON.stringify({ tip: "param_tumu", sysid: sysid,
                           taze: false }));
}

// ws.js param_listesi yanitini buraya da iletir
//
// v2.4.38: Onbellek yaniti TEK PARCADA gelir (param_tumu + taze:false).
// Eskiden iki ayri `param_ara` yanitinin birikmesi beklendigi icin
// eksik parametre halinde islev sessizce donuyor ve panel zamanlayici
// dolana kadar acilmiyordu. Artik gelen set NE ISE onunla acilir;
// eksik alanlar bos gorunur.
function dronAyarParamGeldi(sysid, parametreler) {
  const p = parametreler || {};
  // Onbellegi her durumda tazele (panel kapali olsa da isine yarar)
  if (Object.keys(p).length) {
    dronAyarOnbellek()[sysid] =
      Object.assign({}, dronAyarOnbellek()[sysid] || {}, p);
  }
  if (!dronAyarParamBekleyen || dronAyarParamBekleyen.sysid !== sysid) return;
  const b = dronAyarParamBekleyen;
  dronAyarParamBekleyen = null;
  clearTimeout(b.zamanlayici);
  b.ac(dronAyarUiDegerler(dronAyarOnbellek()[sysid] || {}));
}
window.dronAyarParamGeldi = dronAyarParamGeldi;

// v2.4.38: parametre yazildiginda onbellegi de tazele; boylece panel
// bir daha acildiginda YENI degeri gosterir (eski surumde panel her
// acilista varsayilani gosterdigi icin "kaydetmemis" izlenimi olusuyordu).
function dronAyarOnbellekGuncelle(sysid, paramAd, hamDeger) {
  const n = Number(hamDeger);
  if (!paramAd || !isFinite(n)) return;
  const ob = dronAyarOnbellek();
  if (!ob[sysid]) ob[sysid] = {};
  ob[sysid][paramAd] = n;
}
window.dronAyarOnbellekGuncelle = dronAyarOnbellekGuncelle;

function dronParamGonder(sysid, ad, deger) {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ tip: "dron_komut", sysid: sysid,
                             aksiyon: "param", ad: ad, deger: deger }));
  }
}

function dronKomutGonder(sysid, aksiyon, irtifa) {
  if (ws && ws.readyState === 1) {
    const mesaj = {tip: "dron_komut", sysid: sysid, aksiyon: aksiyon};
    if (typeof irtifa === "number" && isFinite(irtifa)) mesaj.irtifa = irtifa;
    ws.send(JSON.stringify(mesaj));
  }
}

/* FAZ18-DRON-EKRAN-DISI: dronaGit ekran disi gostergesinden de cagrilir. */
function dronaGit(sysid){
  const d = sonVeri[sysid];
  if (d && d.lat !== null){
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(d.lon, d.lat, 1500),
      duration: 1.2,
    });
  }
}

// ---------------------------------------------------------------

// ---------------------------------------------------------------
// PARAMETRE ARAMA / DUZENLEME POPUP'I
// ---------------------------------------------------------------
// v2.4.38: `let` ile tanimlanan global window uzerinde GORUNMEZ; bu iki
// deger dronAyarPopupAc icinden de okundugu icin window'a baglanir.
// (Kaynak tek: asagidaki atamalar bu ozellikleri gunceller.)
let _paramPopupSysid = null;
let _paramPopupEl = null;
window._paramPopupSysid = null;
window._paramTumSet = null;

// ---------------------------------------------------------------
// DETAYLI CANLI TELEMETRI POPUP'I (menu > Telemetri)
// Tasinabilir mini popup icinde tum telemetri alanlari 500 ms'de bir tazelenir
// ---------------------------------------------------------------
function dkTelemetriPopupAc(sysid, fare) {
  if (dkPopupTekil("dkPopupTel_" + sysid)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = "dkPopupTel_" + sysid;
  pop.className = "dk-mini-popup dk-telemetri-popup";
  dkPopupOneGetirKur(pop);
  const dAd = (sonVeri[sysid] && (sonVeri[sysid].kullanici_isim || sonVeri[sysid].tip)) || ("D" + sysid);
  dkMiniPopupBaslikKur(pop, (t.dkTelemetri || "Telemetri") + " \u2014 D" + sysid + " " + dAd, "pp_dkTelemetri", "fa-wave-square");

  const govde = document.createElement("div");
  govde.className = "dk-telpop-govde";
  pop.appendChild(govde);

  const sayi = (v, hane) => (typeof v === "number" && isFinite(v)) ? v.toFixed(hane) : "-";
  function tazele() {
    const d = sonVeri[sysid];
    if (!d) { govde.innerHTML = "<div class='dk-telpop-yok'>" + (t.dkKopuk || "KOPUK") + "</div>"; return; }
    const fix = t.gpsFix[d.gps_fix] || "?";
    const armed = d.armed ? "<span style='color:var(--iyi)'>" + t.dkArmed + "</span>"
                          : "<span style='color:var(--soluk)'>" + t.dkDisarm + "</span>";
    const baglanti = d.baglanti ? "<span style='color:var(--iyi)'>" + t.dkAktif + "</span>"
                                : "<span style='color:var(--kotu)'>" + t.dkKopuk + "</span>";
    const konum = (typeof d.lat === "number" && isFinite(d.lat) && typeof d.lon === "number" && isFinite(d.lon))
      ? d.lat.toFixed(6) + ", " + d.lon.toFixed(6) : "-";
    const pct = (typeof d.batarya_pct === "number" && d.batarya_pct >= 0) ? " (" + d.batarya_pct + "%)" : "";
    const satir = (etiket, deger) =>
      "<div class='dk-telpop-satir'><span class='dk-telpop-etiket'>" + etiket + "</span><span class='dk-telpop-deger'>" + deger + "</span></div>";
    govde.innerHTML =
      satir(t.dkDurum, armed) +
      satir(t.dkLink, baglanti) +
      satir(t.dkMod, d.mod || "-") +
      satir("UID", d.uid || "\u2014") +
      satir(t.dkKonum, konum) +
      satir(t.dkIrt + " (rel)", sayi(d.alt_rel, 1) + " m") +
      satir(t.dkIrt + " (MSL)", sayi(d.alt_msl, 1) + " m") +
      satir(t.dkHiz + " (GS)", sayi(d.groundspeed, 1) + " m/s" + kmhEk(d.groundspeed)) +
      satir(t.dkHiz + " (AS)", sayi(d.airspeed, 1) + " m/s" + kmhEk(d.airspeed)) +
      satir(t.dkTelDikeyHiz || "Dikey H\u0131z", sayi(d.vz, 1) + " m/s" + kmhEk(d.vz)) +
      satir(t.dkYon, (typeof d.heading === "number" ? Math.round(d.heading) : "-") + "\u00B0") +
      satir("Roll / Pitch", sayi(d.roll, 1) + "\u00B0 / " + sayi(d.pitch, 1) + "\u00B0") +
      satir(t.dkBat, sayi(d.batarya_v, 1) + " V" + pct) +
      satir(t.dkTelAkim || "Ak\u0131m", sayi(d.batarya_a, 1) + " A") +
      satir(t.dkGps, fix + " (" + (d.uydu != null ? d.uydu : "-") + " " + t.dkUydu + ")") +
      satir("HDOP", sayi(d.hdop, 2)) +
      satir(t.dkTelSistem || "Sistem", "SYSID " + sysid);
  }
  tazele();
  const zamanlayici = setInterval(() => {
    // Popup DOM'dan kalktiysa zamanlayiciyi durdur
    if (!document.body.contains(pop)) { clearInterval(zamanlayici); return; }
    tazele();
  }, 500);

  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, fare);
}

// ---------------------------------------------------------------
// TELEMETRI HUCRE TIKLAMA YONLENDIRMESI
// Her hucre islevsel dugmedir: ilgili popup/komut acilir.
// ---------------------------------------------------------------
function dkTelHucreTikla(sysid, islev, fare) {
  const t = D();
  const d = sonVeri[sysid];
  switch (islev) {
    case "irtifa": {
      const mevcut = (d && d.alt_rel > 1) ? Math.round(d.alt_rel) : 10;
      dkSliderPopup(fare, t.dkHedefIrtifa, [
        { ad: "irtifa", etiket: t.dkHedefIrtifa, min: 2, max: 500,
          adim: 1, deger: mevcut, birim: "m", hane: 0 },
      ], t.dkGonder, (v) =>
        dronKomutGonder(sysid, "altitude_change", v.irtifa));
      break;
    }
    case "hiz": {
      dronAyarPopupAc(fare, sysid);
      break;
    }
    case "durum": {
      // ARM ise DISARM, DISARM ise ARM - onayli
      if (d && d.armed)
        onayIste(onayMetni("onayDisarm"), () => dronKomutGonder(sysid, "disarm"));
      else
        // v2.5.0: ikinci arm girisi de bicim secimi sunar
        dkArmSecimAc(sysid, null);
      break;
    }
    case "mod":
      dkModPopupAc(sysid, fare);
      break;
    case "gps":
      dkGpsPopupAc(sysid, fare);
      break;
    case "batarya":
      dkBatPopupAc(sysid, fare);
      break;
    case "tkland": {
      // Akilli Takeoff/Land hucresi (telemetri izgarasinin devaminda)
      const kart = dronKartlar[sysid];
      if (kart && kart.btnTkLand && !kart.btnTkLand.disabled)
        dkTakeoffLandTikla(sysid, kart.btnTkLand, fare);
      break;
    }
    case "joystick":
      manuelAnahtarToggle(sysid);
      break;
    case "udp":
      dkUdpBilgiPopup(fare, sysid);
      break;
  }
}

// ---------------------------------------------------------------
// MOD SECIM POPUP'I (telemetri Mod hucresi)
// Arac tipine gore (kopter / sabit kanat / helikopter) dogru mod
// listesi gosterilir. Backend'deki MOD_HARITASI* ile ayni listeler.
// ---------------------------------------------------------------
const DK_MODLAR = {
  kopter: [
    [0, "STABILIZE"], [2, "ALT_HOLD"], [3, "AUTO"], [4, "GUIDED"],
    [5, "LOITER"], [6, "RTL"], [9, "LAND"], [16, "POSHOLD"], [17, "BRAKE"],
  ],
  plane: [
    [0, "MANUAL"], [1, "CIRCLE"], [2, "STABILIZE"], [5, "FBWA"],
    [6, "FBWB"], [7, "CRUISE"], [10, "AUTO"], [11, "RTL"],
    [12, "LOITER"], [15, "GUIDED"], [17, "QSTABILIZE"], [19, "QHOVER"],
    [20, "QLOITER"], [21, "QLAND"], [22, "QRTL"],
  ],
  heli: [
    [0, "STABILIZE"], [1, "ACRO"], [2, "ALT_HOLD"], [3, "AUTO"],
    [4, "GUIDED"], [5, "LOITER"], [6, "RTL"], [9, "LAND"], [16, "POSHOLD"],
  ],
};

function dkModListesi(sysid) {
  // Arac kategorisi: failsafe_kalib.js'deki algilamayla ortak
  let kat = "kopter";
  if (typeof fsAracKategori === "function") {
    kat = fsAracKategori(sysid);
  } else {
    const d = sonVeri[sysid] || {};
    const t = Number(d.arac_tipi || 0);
    if (t === 1 || (t >= 19 && t <= 25)) kat = "plane";
    else if (t === 4) kat = "heli";
  }
  return DK_MODLAR[kat] || DK_MODLAR.kopter;
}

function dkModPopupAc(sysid, fare) {
  if (dkPopupTekil("dkPopupMod_" + sysid)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = "dkPopupMod_" + sysid;
  pop.className = "dk-mini-popup dk-mod-popup";
  dkMiniPopupBaslikKur(pop, (t.dkModSec || "Mod Se\u00e7") + " \u2014 D" + sysid, "pp_dkModSec", "fa-list-check");

  const izgara = document.createElement("div");
  izgara.className = "dk-mod-izgara";
  pop.appendChild(izgara);

  function ciz() {
    const d = sonVeri[sysid];
    const aktifMod = (d && d.mod) || "";
    izgara.innerHTML = "";
    for (const [no, ad] of dkModListesi(sysid)) {
      const btn = document.createElement("button");
      btn.className = "dk-mod-btn" + (aktifMod === ad ? " aktif" : "");
      btn.textContent = ad;
      btn.addEventListener("click", () => {
        if (aktifMod === ad) return;
        dronKomutGonder(sysid, "set_mode", no);
      });
      izgara.appendChild(btn);
    }
  }
  ciz();
  // Aktif mod vurgusunu canli tut
  const zamanlayici = setInterval(() => {
    if (!document.body.contains(pop)) { clearInterval(zamanlayici); return; }
    ciz();
  }, 500);

  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, fare);
}

// ---------------------------------------------------------------
// CANLI GPS POPUP'I (telemetri GPS hucresi)
// ---------------------------------------------------------------
function dkGpsPopupAc(sysid, fare) {
  if (dkPopupTekil("dkPopupGps_" + sysid)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = "dkPopupGps_" + sysid;
  pop.className = "dk-mini-popup dk-telemetri-popup";
  dkMiniPopupBaslikKur(pop, "GPS \u2014 D" + sysid, "pp_dkGps", "fa-satellite");

  const govde = document.createElement("div");
  govde.className = "dk-telpop-govde";
  pop.appendChild(govde);

  const sayi = (v, hane) => (typeof v === "number" && isFinite(v)) ? v.toFixed(hane) : "-";
  const satir = (etiket, deger) =>
    "<div class='dk-telpop-satir'><span class='dk-telpop-etiket'>" + etiket + "</span><span class='dk-telpop-deger'>" + deger + "</span></div>";
  function tazele() {
    const d = sonVeri[sysid];
    if (!d) { govde.innerHTML = "<div class='dk-telpop-yok'>" + (t.dkKopuk || "KOPUK") + "</div>"; return; }
    const fix = t.gpsFix[d.gps_fix] || "?";
    const fixRenk = (d.gps_fix >= 3) ? "var(--iyi)" : (d.gps_fix === 2) ? "var(--uyari)" : "var(--kotu)";
    govde.innerHTML =
      satir(t.dkGpsFixTipi || "Fix Tipi", "<span style='color:" + fixRenk + "'>" + fix + "</span>") +
      satir(t.dkUyduSayisi || "Uydu Say\u0131s\u0131", (d.uydu != null ? d.uydu : "-")) +
      satir("HDOP", sayi(d.hdop, 2)) +
      satir("VDOP", sayi(d.vdop, 2)) +
      satir(t.dkEnlem || "Enlem", (typeof d.lat === "number" && isFinite(d.lat)) ? d.lat.toFixed(7) + "\u00B0" : "-") +
      satir(t.dkBoylam || "Boylam", (typeof d.lon === "number" && isFinite(d.lon)) ? d.lon.toFixed(7) + "\u00B0" : "-") +
      satir(t.dkGpsIrtifa || "GPS \u0130rtifas\u0131", sayi(d.gps_alt, 1) + " m") +
      satir(t.dkIrt + " (MSL)", sayi(d.alt_msl, 1) + " m") +
      satir(t.dkIrt + " (rel)", sayi(d.alt_rel, 1) + " m") +
      satir(t.dkGpsHiz || "GPS H\u0131z\u0131", sayi(d.gps_hiz, 1) + " m/s" + kmhEk(d.gps_hiz)) +
      satir(t.dkGpsRota || "GPS Rotas\u0131 (COG)", sayi(d.gps_rota, 1) + "\u00B0") +
      satir(t.dkYon, (typeof d.heading === "number" ? Math.round(d.heading) : "-") + "\u00B0");
  }
  tazele();
  const zamanlayici = setInterval(() => {
    if (!document.body.contains(pop)) { clearInterval(zamanlayici); return; }
    tazele();
  }, 500);

  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, fare);
}

// ---------------------------------------------------------------
// CANLI BATARYA POPUP'I (telemetri Batarya hucresi)
// ---------------------------------------------------------------
function dkBatPopupAc(sysid, fare) {
  if (dkPopupTekil("dkPopupBat_" + sysid)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = "dkPopupBat_" + sysid;
  pop.className = "dk-mini-popup dk-telemetri-popup";
  dkMiniPopupBaslikKur(pop, (t.dkBat || "Batarya") + " \u2014 D" + sysid, "pp_dkBatarya", "fa-battery-half");

  const govde = document.createElement("div");
  govde.className = "dk-telpop-govde";
  pop.appendChild(govde);

  const sayi = (v, hane) => (typeof v === "number" && isFinite(v)) ? v.toFixed(hane) : "-";
  const satir = (etiket, deger) =>
    "<div class='dk-telpop-satir'><span class='dk-telpop-etiket'>" + etiket + "</span><span class='dk-telpop-deger'>" + deger + "</span></div>";
  function tazele() {
    const d = sonVeri[sysid];
    if (!d) { govde.innerHTML = "<div class='dk-telpop-yok'>" + (t.dkKopuk || "KOPUK") + "</div>"; return; }
    const pctVar = (typeof d.batarya_pct === "number" && d.batarya_pct >= 0);
    const pctRenk = pctVar ? (d.batarya_pct <= 20 ? "var(--kotu)" : d.batarya_pct <= 40 ? "var(--uyari)" : "var(--iyi)") : "var(--soluk)";
    // Guc = V * A (ikisi de gecerliyse)
    const guc = (typeof d.batarya_v === "number" && typeof d.batarya_a === "number" &&
                 isFinite(d.batarya_v) && isFinite(d.batarya_a))
      ? (d.batarya_v * d.batarya_a).toFixed(1) + " W" : "-";
    const kalan = (typeof d.batarya_kalan_sn === "number" && d.batarya_kalan_sn > 0)
      ? Math.floor(d.batarya_kalan_sn / 60) + ":" + String(d.batarya_kalan_sn % 60).padStart(2, "0") : "-";
    govde.innerHTML =
      satir(t.dkBatSeviye || "Seviye", pctVar ? "<span style='color:" + pctRenk + "'>" + d.batarya_pct + "%</span>" : "-") +
      satir(t.dkBatVoltaj || "Voltaj", sayi(d.batarya_v, 2) + " V") +
      satir(t.dkTelAkim || "Ak\u0131m", sayi(d.batarya_a, 1) + " A") +
      satir(t.dkBatGuc || "Anl\u0131k G\u00fc\u00e7", guc) +
      satir(t.dkBatTuketim || "T\u00fcketilen", (typeof d.batarya_mah === "number" ? Math.round(d.batarya_mah) + " mAh" : "-")) +
      satir(t.dkBatEnerji || "Enerji", sayi(d.batarya_wh, 1) + " Wh") +
      satir(t.dkBatHucre || "H\u00fccre Say\u0131s\u0131", (d.batarya_hucre != null ? d.batarya_hucre + "S" : "-")) +
      satir(t.dkBatHucreMin || "H\u00fccre Min/Max",
            (d.batarya_hucre_min != null ? sayi(d.batarya_hucre_min, 2) + " / " + sayi(d.batarya_hucre_max, 2) + " V" : "-")) +
      satir(t.dkBatSicaklik || "S\u0131cakl\u0131k", (typeof d.batarya_sicaklik === "number" ? sayi(d.batarya_sicaklik, 1) + " \u00B0C" : "-")) +
      satir(t.dkBatKalan || "Tahmini Kalan S\u00fcre", kalan);
  }
  tazele();
  const zamanlayici = setInterval(() => {
    if (!document.body.contains(pop)) { clearInterval(zamanlayici); return; }
    tazele();
  }, 500);

  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, fare);
}

// =================================================================
// LOG YONETIMI - dataflash log listesi + indirme popup'i
// ws.js: log_listesi / log_ilerleme / log_indirildi mesajlarini
// window.dkLog* islevlerine yonlendirir.
// =================================================================
let _logPopupEl = null;
let _logPopupSysid = null;
// v2.4.23: liste + siralama + surmekte olan indirme durumu
let _logListe = [];            // [{id, boyut, zaman}]
let _logSiraAlan = "id";       // "id" | "zaman" | "boyut"
let _logSiraArtan = false;     // varsayilan: en yeni / en buyuk ustte
let _logIndirilen = null;      // null | {sysid, logId}

function dkLogPopupAc(sysid) {
  dkLogPopupKapat();
  _logPopupSysid = sysid;
  const t = D();
  const pop = document.createElement("div");
  pop.className = "dk-param-popup dk-log-popup";
  pop.id = "dkLogPopup";
  _logPopupEl = pop;

  const bas = document.createElement("div");
  bas.className = "dk-pp-baslik";
  bas.innerHTML = "<i class='fa-solid fa-file-lines'></i> " +
    (t.dkLogYonetimi || "LOG Y\u00d6NET\u0130M\u0130") +
    " <span style='opacity:0.6;font-size:11px'>(D" + sysid + ")</span>";
  pop.appendChild(bas);

  const durum = document.createElement("div");
  durum.className = "dk-log-durum";
  durum.innerHTML =
    "<div class='dk-log-durum-satir'>" +
    "<span class='dk-log-durum-metin' id='dkLogDurumMetin'>" +
    (t.dkLogOkunuyor || "Log klas\u00f6r\u00fc okunuyor...") + "</span>" +
    "<button class='dk-log-durdur-btn' id='dkLogDurdurBtn' " +
    "style='display:none'><i class='fa-solid fa-stop'></i><span>" +
    (t.dkLogDurdur || "Durdur") + "</span></button></div>" +
    "<div class='dk-log-bar'><div class='dk-log-bar-dolu belirsiz' id='dkLogBar'></div></div>";
  pop.appendChild(durum);

  const durdurBtn = durum.querySelector("#dkLogDurdurBtn");
  durdurBtn.addEventListener("click", dkLogIndirmeDurdur);

  // v2.4.23: siralanabilir tablo basligi (sabit, listenin ustunde)
  const basSatir = document.createElement("div");
  basSatir.className = "dk-log-tablo-basi";
  basSatir.id = "dkLogTabloBasi";
  [["id", t.dkLogKolonAd || "LOG", "dk-log-th-ad"],
   ["zaman", t.dkLogKolonTarih || "TAR\u0130H", "dk-log-th-tarih"],
   ["boyut", t.dkLogKolonBoyut || "BOYUT", "dk-log-th-boyut"]]
    .forEach(([alan, etiket, sinif]) => {
      const th = document.createElement("button");
      th.className = "dk-log-th " + sinif;
      th.dataset.alan = alan;
      th.title = t.dkLogSiralaIpucu || "S\u0131ralamak i\u00e7in t\u0131klay\u0131n";
      th.innerHTML = "<span>" + etiket + "</span>" +
        "<i class='fa-solid fa-sort dk-log-ok'></i>";
      th.addEventListener("click", () => dkLogSirala(alan));
      basSatir.appendChild(th);
    });
  const thIslem = document.createElement("span");
  thIslem.className = "dk-log-th-islem";
  thIslem.textContent = t.dkLogKolonIslem || "\u0130\u015eLEM";
  basSatir.appendChild(thIslem);
  basSatir.style.display = "none";   // liste gelince gorunur
  pop.appendChild(basSatir);

  const sonucDiv = document.createElement("div");
  sonucDiv.className = "dk-pp-sonuc";
  sonucDiv.id = "dkLogSonuc";
  pop.appendChild(sonucDiv);

  const tlogDiv = document.createElement("div");
  tlogDiv.className = "dk-tlog-bolum";
  tlogDiv.innerHTML = "<div class='dk-tlog-bas'><i class='fa-solid fa-satellite-dish'></i> " +
    (t.dkTlogBaslik || "TELEMETR\u0130 KAYITLARI (.tlog)") +
    "</div><div class='dk-tlog-liste' id='dkTlogListe'>" +
    (t.dkYukleniyor || "Y\u00fckleniyor\u2026") + "</div>";
  pop.appendChild(tlogDiv);

  const kapatBtn = document.createElement("button");
  kapatBtn.className = "dk-pp-kapat";
  kapatBtn.innerHTML = "<i class='fa-solid fa-xmark'></i>";
  kapatBtn.addEventListener("click", dkLogPopupKapat);
  pop.appendChild(kapatBtn);
  document.body.appendChild(pop);
  if (typeof window.popupBoyutlandirilabilirYap === "function")
    window.popupBoyutlandirilabilirYap(pop, "pp_dkLogPopup");
  if (typeof window.popupTasinabilirYap === "function")
    window.popupTasinabilirYap(pop, bas, "pp_dkLogPopup");

  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({tip: "log_listesi", sysid: sysid}));
    ws.send(JSON.stringify({tip: "tlog_listesi"}));
  } else {
    dkLogDurumYaz(t.dkLogBaglantiYok || "Sunucu ba\u011flant\u0131s\u0131 yok.", false);
  }
}

function dkLogPopupKapat() {
  // Popup kapanirken surmekte olan indirme varsa durdur
  if (_logIndirilen) dkLogIndirmeDurdur();
  if (_logPopupEl) { _logPopupEl.remove(); _logPopupEl = null; }
  _logPopupSysid = null;
  _logListe = [];
  _logIndirilen = null;
}

function dkLogDurumYaz(metin, barGoster, oran) {
  const m = document.getElementById("dkLogDurumMetin");
  const b = document.getElementById("dkLogBar");
  if (m) m.textContent = metin;
  if (b) {
    const kap = b.parentElement;
    if (barGoster === false) { if (kap) kap.style.display = "none"; return; }
    if (kap) kap.style.display = "";
    if (typeof oran === "number") {
      b.classList.remove("belirsiz");
      b.style.width = Math.max(0, Math.min(100, oran * 100)).toFixed(1) + "%";
    } else {
      b.classList.add("belirsiz");
      b.style.width = "";
    }
  }
}

function dkLogBoyutYaz(b) {
  if (typeof b !== "number" || b <= 0) return "-";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / (1024 * 1024)).toFixed(2) + " MB";
}

// v2.4.23: log zamani LOG_ENTRY.time_utc alanindan gelir (backend adi
// "zaman_utc"). GPS kilidi olmadan yazilan loglarda 0 gelir -> "—".
function dkLogTarihYaz(zaman) {
  const t = D();
  if (!zaman || zaman <= 0) return t.dkLogTarihYok || "\u2014";
  try {
    const d = new Date(zaman * 1000);
    const ik = (n) => String(n).padStart(2, "0");
    return ik(d.getDate()) + "." + ik(d.getMonth() + 1) + "." +
           d.getFullYear() + " " + ik(d.getHours()) + ":" +
           ik(d.getMinutes());
  } catch (e) { return t.dkLogTarihYok || "\u2014"; }
}

function dkLogSirala(alan) {
  if (_logSiraAlan === alan) _logSiraArtan = !_logSiraArtan;
  else { _logSiraAlan = alan; _logSiraArtan = false; }
  dkLogTabloCiz();
}

function dkLogTabloCiz() {
  const t = D();
  const sonucDiv = document.getElementById("dkLogSonuc");
  const basSatir = document.getElementById("dkLogTabloBasi");
  if (!sonucDiv) return;
  if (basSatir) {
    basSatir.style.display = _logListe.length ? "" : "none";
    basSatir.querySelectorAll(".dk-log-th").forEach((th) => {
      const ok = th.querySelector(".dk-log-ok");
      const aktif = th.dataset.alan === _logSiraAlan;
      th.classList.toggle("aktif", aktif);
      if (ok) ok.className = "fa-solid dk-log-ok " + (aktif
        ? (_logSiraArtan ? "fa-sort-up" : "fa-sort-down")
        : "fa-sort");
    });
  }
  const sirali = _logListe.slice().sort((a, b) => {
    const x = a[_logSiraAlan] || 0, y = b[_logSiraAlan] || 0;
    return _logSiraArtan ? (x - y) : (y - x);
  });
  sonucDiv.innerHTML = "";
  const tablo = document.createElement("div");
  tablo.className = "dk-pp-tablo";
  for (const lg of sirali) {
    const satir = document.createElement("div");
    satir.className = "dk-pp-satir dk-log-satir";
    satir.dataset.logId = lg.id;
    if (_logIndirilen && _logIndirilen.logId === lg.id)
      satir.classList.add("indiriliyor");
    satir.innerHTML =
      "<span class='dk-log-ad'>LOG " + lg.id + "</span>" +
      "<span class='dk-log-tarih'>" + dkLogTarihYaz(lg.zaman) + "</span>" +
      "<span class='dk-log-boyut'>" + dkLogBoyutYaz(lg.boyut) + "</span>";
    const btn = document.createElement("button");
    btn.className = "dk-log-indir-btn";
    if (_logIndirilen) {
      if (_logIndirilen.logId === lg.id) {
        btn.classList.add("durdur");
        btn.innerHTML = "<i class='fa-solid fa-stop'></i> " + "<span>" + (
          (t.dkLogDurdur || "Durdur")) + "</span>";
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          dkLogIndirmeDurdur();
        });
      } else {
        btn.disabled = true;
        btn.innerHTML = "<i class='fa-solid fa-download'></i> " + "<span>" + (
          (t.dkLogIndir || "\u0130ndir")) + "</span>";
      }
    } else {
      btn.innerHTML = "<i class='fa-solid fa-download'></i> " + "<span>" + (
        (t.dkLogIndir || "\u0130ndir")) + "</span>";
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        dkLogIndirBaslat(_logPopupSysid, lg.id, lg.boyut);
      });
    }
    satir.appendChild(btn);
    tablo.appendChild(satir);
  }
  sonucDiv.appendChild(tablo);
}

function dkLogListesiGeldi(sysid, loglar, hata) {
  if (sysid !== _logPopupSysid) return;
  const t = D();
  const sonucDiv = document.getElementById("dkLogSonuc");
  if (!sonucDiv) return;
  if (hata) {
    dkLogDurumYaz(t.dkLogHata || "Log listesi al\u0131namad\u0131.", false);
    return;
  }
  if (!loglar || loglar.length === 0) {
    dkLogDurumYaz(t.dkLogYok || "Dronda kay\u0131tl\u0131 log yok.", false);
    return;
  }
  // Backend alan adi "zaman_utc"; eski surumlerde "utc" olabilir
  _logListe = loglar.map((lg) => ({
    id: Number(lg.id) || 0,
    boyut: Number(lg.boyut) || 0,
    zaman: Number(lg.zaman_utc !== undefined ? lg.zaman_utc : lg.utc) || 0,
  }));
  dkLogDurumYaz((t.dkLogAdet || "{n} log dosyas\u0131 bulundu.")
    .replace("{n}", _logListe.length), false);
  dkLogTabloCiz();
}

function dkLogIndirBaslat(sysid, logId, boyut) {
  const t = D();
  if (!ws || ws.readyState !== 1) {
    dkLogDurumYaz(t.dkLogBaglantiYok || "Sunucu ba\u011flant\u0131s\u0131 yok.", false);
    return;
  }
  _logIndirilen = {sysid: sysid, logId: logId};
  dkLogTabloCiz();
  dkLogDurdurGoster(true);
  dkLogDurumYaz((t.dkLogIndiriliyor || "LOG {id} indiriliyor...")
    .replace("{id}", logId), true, 0);
  ws.send(JSON.stringify({tip: "log_indir", sysid: sysid,
                          log_id: logId, boyut: boyut}));
}

// v2.4.23: indirmeyi kullanici istegiyle durdur
function dkLogIndirmeDurdur() {
  if (!_logIndirilen) return;
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({tip: "log_indir_iptal",
                            sysid: _logIndirilen.sysid}));
  }
  dkLogDurdurGoster(false);
}

function dkLogDurdurGoster(goster) {
  const b = document.getElementById("dkLogDurdurBtn");
  if (b) b.style.display = goster ? "" : "none";
}

function dkLogIlerleme(sysid, logId, alinan, toplam) {
  if (sysid !== _logPopupSysid) return;
  const t = D();
  const oran = (toplam > 0) ? (alinan / toplam) : null;
  dkLogDurumYaz(
    (t.dkLogIndiriliyor || "LOG {id} indiriliyor...").replace("{id}", logId) +
    " (" + dkLogBoyutYaz(alinan) + " / " + dkLogBoyutYaz(toplam) + ")",
    true, oran);
}

function dkLogIndirildi(sysid, logId, dosya, basari, hata, iptal) {
  if (sysid !== _logPopupSysid) return;
  const t = D();
  _logIndirilen = null;
  dkLogDurdurGoster(false);
  dkLogTabloCiz();
  if (iptal) {
    dkLogDurumYaz((t.dkLogIptalEdildi ||
      "LOG {id} indirmesi durduruldu.").replace("{id}", logId), false);
    return;
  }
  if (!basari || !dosya) {
    dkLogDurumYaz((t.dkLogIndirmeHata || "LOG {id} indirilemedi.").replace("{id}", logId) +
      (hata ? " (" + hata + ")" : ""), false);
    return;
  }
  // Backend logu HTTP kokune kaydetti; dogrudan dosya URL'inden indirt
  const a = document.createElement("a");
  a.href = dosya;
  a.download = "D" + sysid + "_LOG_" + logId + ".bin";
  document.body.appendChild(a);
  a.click();
  a.remove();
  dkLogDurumYaz((t.dkLogTamam || "LOG {id} indirildi.").replace("{id}", logId), false);
}

window.dkLogListesiGeldi = dkLogListesiGeldi;
window.dkLogIlerleme = dkLogIlerleme;
window.dkLogIndirildi = dkLogIndirildi;
window.dkLogIndirmeDurdur = dkLogIndirmeDurdur;

// v2.4.15: tam parametre seti (yerel arama + tree grid icin bellekte)
let _paramTumSet = {};
let _paramAcikGruplar = new Set();

function dkParamPopupAc(sysid) {
  dkParamPopupKapat();
  _paramPopupSysid = sysid;
  _paramTumSet = {};
  // v2.4.38: hiz paneli bu iki degeri window uzerinden okur (bkz. 1900)
  window._paramPopupSysid = sysid;
  window._paramTumSet = _paramTumSet;
  _paramAcikGruplar = new Set();
  const t = D();
  const pop = document.createElement("div");
  pop.className = "dk-param-popup";
  pop.id = "dkParamPopup";
  _paramPopupEl = pop;

  // Baslik
  const bas = document.createElement("div");
  bas.className = "dk-pp-baslik";
  bas.innerHTML = "<i class='fa-solid fa-sliders'></i> " + (t.dkParametreler || "PARAMETRELER") +
    " <span style='opacity:0.6;font-size:11px'>(D" + sysid + ")</span>";
  pop.appendChild(bas);

  // Arama satiri (v2.4.15: yerel anlik filtre + yenile dugmesi)
  const aramaBar = document.createElement("div");
  aramaBar.className = "dk-pp-arama";
  const aramaInput = document.createElement("input");
  aramaInput.type = "text";
  aramaInput.className = "dk-pp-input";
  aramaInput.placeholder = t.dkParamAra || "Parametre adı ara...";
  aramaInput.id = "dkParamAraInput";
  aramaInput.addEventListener("input", () => dkParamTreeCiz());
  // v2.4.17: TUMUNU AL — drondan taze tam okuma (belirgin dugme)
  const tumAlBtn = document.createElement("button");
  tumAlBtn.className = "dk-pp-btn-bul dk-pp-btn-tumal";
  tumAlBtn.id = "dkParamTumAlBtn";
  tumAlBtn.innerHTML = "<i class='fa-solid fa-download'></i> " + "<span>" + ( (t.dkParamTumAl || "TÜMÜNÜ AL")) + "</span>";
  tumAlBtn.title = t.dkParamTumAlIpucu || "Tüm parametreleri drondan yeniden oku";
  tumAlBtn.addEventListener("click", () => dkParamTumunuIste(sysid, true));
  const yenileBtn = document.createElement("button");
  yenileBtn.className = "dk-pp-btn-bul";
  yenileBtn.id = "dkParamYenileBtn";
  yenileBtn.innerHTML = "<i class='fa-solid fa-rotate'></i> " + "<span>" + ( (t.dkParamYenile || "YENİLE")) + "</span>";
  yenileBtn.title = t.dkParamYenileIpucu || "Drondan yeniden oku";
  yenileBtn.addEventListener("click", () => dkParamTumunuIste(sysid, true));
  aramaBar.appendChild(aramaInput);
  aramaBar.appendChild(tumAlBtn);
  aramaBar.appendChild(yenileBtn);
  pop.appendChild(aramaBar);

  // Ilerleme cubugu (v2.4.15)
  const progDiv = document.createElement("div");
  progDiv.className = "dk-pp-progress";
  progDiv.id = "dkParamProgress";
  progDiv.innerHTML =
    "<div class='dk-pp-progress-bar'><div class='dk-pp-progress-dolgu' id='dkParamProgressDolgu'></div></div>" +
    "<span class='dk-pp-progress-metin' id='dkParamProgressMetin'></span>";
  progDiv.style.display = "none";
  pop.appendChild(progDiv);

  // Sonuc alani (tree grid)
  const sonucDiv = document.createElement("div");
  sonucDiv.className = "dk-pp-sonuc";
  sonucDiv.id = "dkParamSonuc";
  pop.appendChild(sonucDiv);

  // Kapat dugmesi
  const kapatBtn = document.createElement("button");
  kapatBtn.className = "dk-pp-kapat";
  kapatBtn.innerHTML = "<i class='fa-solid fa-xmark'></i>";
  kapatBtn.addEventListener("click", dkParamPopupKapat);
  pop.appendChild(kapatBtn);

  document.body.appendChild(pop);
  if (typeof window.popupBoyutlandirilabilirYap === "function")
    window.popupBoyutlandirilabilirYap(pop, "pp_dkParamPopup");
  if (typeof window.popupTasinabilirYap === "function")
    window.popupTasinabilirYap(pop, bas, "pp_dkParamPopup");
  setTimeout(() => aramaInput.focus(), 50);

  // v2.4.17: acilista once kayitli set (onbellek) istenir — varsa aninda
  // gosterilir, drondan okuma yapilmaz. TUMUNU AL taze okuma yapar.
  dkParamTumunuIste(sysid, false);
}

function dkParamPopupKapat() {
  if (_paramPopupEl) { _paramPopupEl.remove(); _paramPopupEl = null; }
  _paramPopupSysid = null;
  window._paramPopupSysid = null;
  // NOT: _paramTumSet BILINCLI olarak silinmez. Parametreler ekrani
  // kapatilsa bile cekilen tam set hiz panelinin isine yarar; onbellek
  // bir sonraki TUMUNU AL'a kadar gecerli kalir.
}

// v2.4.15: drondan tum parametreleri iste (ilerleme olaylariyla)
// v2.4.17: taze=false -> once sunucu onbellegi (kayitli set aninda gelir);
//          taze=true  -> drondan zorunlu tam okuma + onbellek guncelleme
function dkParamTumunuIste(sysid, taze) {
  const t = D();
  const sonucDiv = document.getElementById("dkParamSonuc");
  if (sonucDiv)
    sonucDiv.innerHTML = "<span style='opacity:0.5'>" +
      (t.dkParamOkunuyor || "Parametreler okunuyor...") + "</span>";
  const yenileBtn = document.getElementById("dkParamYenileBtn");
  if (yenileBtn) yenileBtn.disabled = true;
  const tumAlBtn = document.getElementById("dkParamTumAlBtn");
  if (tumAlBtn) tumAlBtn.disabled = true;
  dkParamIlerleme(sysid, 0, 0);
  const progDiv = document.getElementById("dkParamProgress");
  if (progDiv) progDiv.style.display = "";
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({tip: "param_tumu", sysid: sysid,
                            taze: !!taze}));
}

// ---------------------------------------------------------------
// v2.4.41: OTOMATIK TAM PARAMETRE YUKLEME + KART ALTI INCE SERIT
// sysid -> "bekliyor" | "taze" | "bitti"
// Ayni dron icin istek TEK KEZ yapilir; telemetri saniyede birkac kez
// geldigi icin bu bekci olmadan sunucuya yuzlerce istek giderdi.
// ---------------------------------------------------------------
var _paramOtoIstenen = {};

// Kart altindaki ince seridi tazele.
// bitti=true -> %100 yap, yesile cevir, kisa sure sonra solup gizle.
function dkParamSeritTazele(sysid, alinan, toplam, bitti) {
  const kart = dronKartlar[sysid];
  if (!kart || !kart.paramSerit) return;
  const serit = kart.paramSerit, ic = kart.paramSeritIc;
  if (serit._solmaZaman) {
    clearTimeout(serit._solmaZaman);
    serit._solmaZaman = null;
  }
  serit.classList.remove("gizli", "solyor");
  if (bitti) {
    ic.style.width = "100%";
    serit.classList.add("bitti");
    serit._solmaZaman = setTimeout(() => {
      serit.classList.add("solyor");
      serit._solmaZaman = setTimeout(() => {
        serit.classList.add("gizli");
        serit.classList.remove("solyor", "bitti");
        ic.style.width = "0%";
        serit._solmaZaman = null;
      }, 600);
    }, 1400);
    return;
  }
  serit.classList.remove("bitti");
  const yuzde = toplam > 0
    ? Math.min(100, Math.round(alinan * 100 / toplam)) : 0;
  ic.style.width = yuzde + "%";
}

// Otomatik parametre istegi (popup'i ETKILEMEZ).
// dkParamTumunuIste popup DOM'unu da yonettigi icin ayri tutulur;
// aksi halde popup kapaliyken getElementById cagrilari bosa gider ve
// _paramPopupSysid degismedigi icin cevap islenmezdi.
function dkParamOtoIste(sysid, taze) {
  if (!(ws && ws.readyState === 1)) return;
  dkParamSeritTazele(sysid, 0, 0, false);
  ws.send(JSON.stringify({tip: "param_tumu", sysid: Number(sysid),
                          taze: !!taze}));
}

// Dron ilk kez bagli gorulunce tam parametre setini otomatik yukle.
// dronKartTazele'den her telemetri paketinde cagrilir.
function dkParamOtoYuklemeDene(sysid, d) {
  if (!d || !d.baglanti) return;
  if (_paramOtoIstenen[sysid]) return;
  const onbellek = (typeof dronAyarOnbellek === "function")
    ? dronAyarOnbellek()[sysid] : null;
  if (onbellek && Object.keys(onbellek).length > 50) {
    // Bu oturumda zaten yuklenmis; serit hic gosterilmez
    _paramOtoIstenen[sysid] = "bitti";
    return;
  }
  _paramOtoIstenen[sysid] = "bekliyor";
  dkParamOtoIste(sysid, false);
}

// Baglanti kopunca bayrak sifirlanir ki yeniden baglandiginda
// parametreler tekrar yuklenebilsin (arac degismis olabilir).
function dkParamOtoSifirla(sysid) {
  delete _paramOtoIstenen[sysid];
}

// v2.4.15: okuma ilerleme olayi (ws.js'ten)
// v2.4.41: ilerleme artik IKI hedefi besler — parametre popup'i (acikse)
// ve dron kartinin altindaki ince serit (her zaman). Onceki surumde ilk
// satirdaki popup kilidi popup kapaliyken ilerlemeyi TAMAMEN eliyordu;
// otomatik yukleme gorunmez kalirdi.
function dkParamIlerleme(sysid, alinan, toplam) {
  dkParamSeritTazele(sysid, alinan, toplam, false);
  if (sysid !== _paramPopupSysid) return;
  const dolgu = document.getElementById("dkParamProgressDolgu");
  const metin = document.getElementById("dkParamProgressMetin");
  const progDiv = document.getElementById("dkParamProgress");
  if (progDiv) progDiv.style.display = "";
  const yuzde = toplam > 0 ? Math.min(100, Math.round(alinan * 100 / toplam)) : 0;
  if (dolgu) dolgu.style.width = yuzde + "%";
  if (metin) metin.textContent = toplam > 0 ?
    (alinan + " / " + toplam + "  (%" + yuzde + ")") : (alinan + " ...");
}

function dkParamListesiGeldi(sysid, parametreler, hata, kaynak, okumaTs) {
  // v2.4.41: onbellek yazimi ve kart seridi popup'tan BAGIMSIZ yapilir.
  // Otomatik yukleme popup kapaliyken calistigi icin bu blok eskiden
  // hic isletilmiyordu; parametreler onbellege girmedigi surece kalkis
  // kontrol listesinin parametre tabanli maddeleri de olusmazdi.
  const gelenSet = parametreler || {};
  const gelenAdet = Object.keys(gelenSet).length;
  if (typeof dronAyarOnbellek === "function" && gelenAdet) {
    dronAyarOnbellek()[sysid] =
      Object.assign({}, dronAyarOnbellek()[sysid] || {}, gelenSet);
  }
  dkParamSeritTazele(sysid, gelenAdet, gelenAdet, true);
  if (_paramOtoIstenen[sysid] === "bekliyor") {
    // Onbellek bos dondu -> drondan taze okuma tek kez denenir
    if (!gelenAdet && !hata) {
      _paramOtoIstenen[sysid] = "taze";
      dkParamOtoIste(sysid, true);
    } else {
      _paramOtoIstenen[sysid] = "bitti";
    }
  } else if (_paramOtoIstenen[sysid] === "taze") {
    _paramOtoIstenen[sysid] = "bitti";
  }
  if (sysid !== _paramPopupSysid) return;
  const sonucDiv = document.getElementById("dkParamSonuc");
  if (!sonucDiv) return;
  const t = D();
  // v2.4.15: tam set bellekte tutulur, tree grid cizilir
  _paramTumSet = gelenSet;
  window._paramTumSet = _paramTumSet;
  const yenileBtn = document.getElementById("dkParamYenileBtn");
  if (yenileBtn) yenileBtn.disabled = false;
  const tumAlBtn = document.getElementById("dkParamTumAlBtn");
  if (tumAlBtn) tumAlBtn.disabled = false;
  const progDiv = document.getElementById("dkParamProgress");
  const adet = Object.keys(_paramTumSet).length;
  if (progDiv) {
    // Okuma bitti: cubugu doldur, ozet metni birak
    const dolgu = document.getElementById("dkParamProgressDolgu");
    const metin = document.getElementById("dkParamProgressMetin");
    if (dolgu) dolgu.style.width = adet > 0 ? "100%" : "0%";
    if (metin) {
      // v2.4.17: kaynak etiketi — kayitli (tarih) / drondan okundu
      let ozet = adet > 0 ? (adet + " " + (t.dkParamAdet || "parametre")) : "";
      if (adet > 0 && kaynak === "cache" && okumaTs) {
        const trh = new Date(okumaTs * 1000);
        ozet += " · " + (t.dkParamKayitli || "kayıtlı") + ": " +
          trh.toLocaleDateString() + " " +
          trh.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
      } else if (adet > 0 && kaynak === "dron") {
        ozet += " · " + (t.dkParamDrondan || "drondan okundu");
      }
      metin.textContent = ozet;
    }
  }
  // v2.4.16: backend hata mesaji — kirmizi uyari + cozum onerileri
  if (adet === 0 && hata) {
    sonucDiv.innerHTML =
      "<div class='dk-pp-hata'><i class='fa-solid fa-triangle-exclamation'></i> " +
      hata + "<br><span style='opacity:0.65;font-size:11px'>" +
      (t.dkParamHataIpucu ||
       "Telemetri linkinin \u00e7ift y\u00f6nl\u00fc oldu\u011fundan emin olun " +
       "(GCS\u2192dron y\u00f6n\u00fc a\u00e7\u0131k olmal\u0131). " +
       "YEN\u0130LE ile tekrar deneyebilirsiniz.") + "</span></div>";
    return;
  }
  if (adet === 0) {
    // v2.4.17: kayitli set yok — kullaniciyi TUMUNU AL'a yonlendir
    sonucDiv.innerHTML = "<span style='opacity:0.5'>" +
      (t.dkParamKayitYok ||
       "Kayıtlı parametre yok. <b>TÜMÜNÜ AL</b> ile drondan okuyun.") +
      "</span>";
    return;
  }
  dkParamTreeCiz();
}

// v2.4.15: parametre grubu (onek) — ad'in ilk '_' oncesi parcasi
function dkParamGrupAdi(ad) {
  const i = ad.indexOf("_");
  return i > 0 ? ad.slice(0, i) : ad;
}

// v2.4.15: tree grid cizimi (yerel arama filtresiyle)
function dkParamTreeCiz() {
  const sonucDiv = document.getElementById("dkParamSonuc");
  if (!sonucDiv) return;
  const t = D();
  const sysid = _paramPopupSysid;
  const aramaEl = document.getElementById("dkParamAraInput");
  const filtre = aramaEl ? aramaEl.value.trim().toUpperCase() : "";
  const keys = Object.keys(_paramTumSet).sort();
  if (keys.length === 0) return;

  // Gruplara ayir (filtre uygulanmis)
  const gruplar = {};   // grupAd -> [paramAd]
  for (const ad of keys) {
    if (filtre && ad.toUpperCase().indexOf(filtre) === -1) continue;
    const g = dkParamGrupAdi(ad);
    (gruplar[g] = gruplar[g] || []).push(ad);
  }
  const grupAdlari = Object.keys(gruplar).sort();
  sonucDiv.innerHTML = "";
  if (grupAdlari.length === 0) {
    sonucDiv.innerHTML = "<span style='opacity:0.5'>" +
      (t.dkParamYok || "Parametre bulunamadı.") + "</span>";
    return;
  }
  const tablo = document.createElement("div");
  tablo.className = "dk-pp-tablo";
  for (const g of grupAdlari) {
    const uyeler = gruplar[g];
    // Filtre varken eslesen gruplar otomatik acik
    const acik = filtre ? true : _paramAcikGruplar.has(g);
    const grupSatir = document.createElement("div");
    grupSatir.className = "dk-pp-grup" + (acik ? " acik" : "");
    grupSatir.innerHTML =
      "<i class='fa-solid fa-chevron-" + (acik ? "down" : "right") + "'></i> " +
      "<span class='dk-pp-grup-ad'>" + g + "</span>" +
      "<span class='dk-pp-grup-adet'>" + uyeler.length + "</span>";
    grupSatir.addEventListener("click", () => {
      if (_paramAcikGruplar.has(g)) _paramAcikGruplar.delete(g);
      else _paramAcikGruplar.add(g);
      dkParamTreeCiz();
    });
    tablo.appendChild(grupSatir);
    if (!acik) continue;
    for (const ad of uyeler) {
      const satir = document.createElement("div");
      satir.className = "dk-pp-satir dk-pp-satir-agac";
      const aciklama = dkParamAciklamaGetir(ad);
      // v2.4.19: sayisal degerin gercek anlami (values/bitmask metadata)
      const anlam = paramDegerAnlami(ad, _paramTumSet[ad], sysid);
      const anlamKisa = anlam.length > 42 ? anlam.slice(0, 40) + "\u2026" : anlam;
      satir.innerHTML =
        "<span class='dk-pp-ad'>" + ad + "</span>" +
        "<span class='dk-pp-aciklama' title=\"" + aciklama.replace(/"/g, "&quot;") + "\">" + aciklama + "</span>" +
        "<span class='dk-pp-val'>" +
        parseFloat(_paramTumSet[ad]).toFixed(4).replace(/\.?0+$/, "") +
        (anlamKisa ? "<span class='dk-pp-val-anlam' title=\"" +
          anlam.replace(/"/g, "&quot;") + "\">" +
          anlamKisa.replace(/</g, "&lt;") + "</span>" : "") +
        "</span>";
      satir.addEventListener("click", () => {
        dkParamDuzenlePopup(sysid, ad, _paramTumSet[ad]);
      });
      tablo.appendChild(satir);
    }
  }
  sonucDiv.appendChild(tablo);
}

// v2.4.15: parametre metadata (min/max/inc/birim) — param_meta.js
function dkParamMetaGetir(paramAd) {
  if (typeof PARAM_META !== "undefined" && PARAM_META[paramAd])
    return PARAM_META[paramAd];
  return null;
}

// Secili dile gore parametre aciklamasi dondurur.
// TR secili ise param_aciklama_tr.js (Turkce ceviri), degilse EN kaynagi.
function dkParamAciklamaGetir(paramAd) {
  const trAktif = (typeof aktifDil === "undefined") || aktifDil !== "en";
  if (trAktif && typeof PARAM_ACIKLAMA_TR !== "undefined" && PARAM_ACIKLAMA_TR[paramAd])
    return PARAM_ACIKLAMA_TR[paramAd];
  if (typeof PARAM_ACIKLAMA !== "undefined" && PARAM_ACIKLAMA[paramAd])
    return PARAM_ACIKLAMA[paramAd];
  return "";
}

// ---------------------------------------------------------------
// v2.4.19: PARAMETRE DEGER SECENEKLERI (ArduPilot metadata)
// Mission Planner gibi sayisal degerin gercek anlamini gosterir.
// param_secenek.js: PARAM_SECENEK.{ortak,kopter,plane}[AD] =
//   { v: {"0":"Disabled", ...} }  -> values (combo box)
//   { b: {"0":"BitAdi", ...} }    -> bitmask (onay kutulari)
// Arac tipine gore once kopter/plane katmani, sonra ortak katman.
// ---------------------------------------------------------------
function paramSecenekGetir(paramAd, sysid) {
  if (typeof PARAM_SECENEK === "undefined" || !paramAd) return null;
  const kat = (typeof fsAracKategori === "function" && sysid)
    ? fsAracKategori(sysid) : "kopter";
  const oncelik = (kat === "plane") ? "plane" : "kopter";
  const ad = String(paramAd).toUpperCase();
  return (PARAM_SECENEK[oncelik] && PARAM_SECENEK[oncelik][ad]) ||
         (PARAM_SECENEK.ortak && PARAM_SECENEK.ortak[ad]) || null;
}

// Sayisal degerin okunabilir anlami ("3" -> "Auto").
// Bitmask ise ayarli bit adlari virgulle birlestirilir.
function paramDegerAnlami(paramAd, deger, sysid) {
  const sec = paramSecenekGetir(paramAd, sysid);
  if (!sec) return "";
  const n = parseFloat(deger);
  if (sec.v) {
    // Tam eslesme (tamsayi) veya ondalikli anahtar ("0.8" gibi)
    const anahtarlar = [String(Number(n)), String(deger),
                        (isFinite(n) ? n.toFixed(1) : "")];
    for (const a of anahtarlar) if (a && sec.v[a] !== undefined) return sec.v[a];
    return "";
  }
  if (sec.b) {
    if (!isFinite(n)) return "";
    const mask = Math.round(n);
    if (mask === 0) return D().dkParamBitYok || "Hi\u00e7biri";
    const adlar = [];
    Object.keys(sec.b).forEach((bit) => {
      const b = parseInt(bit, 10);
      if (b >= 0 && b < 32 && (mask & (1 << b))) adlar.push(sec.b[bit]);
    });
    return adlar.length ? adlar.join(", ") : "";
  }
  return "";
}

function dkParamDuzenlePopup(sysid, paramAd, mevcutDeger) {
  const t = D();
  // Mevcut popup icerigini gizle degil, ustune overlay ac
  const overlay = document.createElement("div");
  overlay.className = "dk-pp-overlay";
  overlay.id = "dkParamDuzenleOverlay";
  // FAZ18-IS4-PARAM-KUTU: ortu artik parametre penceresinin ICINE
  // degil govdeye eklenir; boylece liste arkada gorunur kalir ve kutu
  // bagimsiz bir acilir kutu gibi davranir (tasinabilir, Esc ile
  // kapanir, kapatma dugmesi tasir).
  overlay.dataset.faz18 = "is4";

  const kutu = document.createElement("div");
  kutu.className = "dk-pp-duzenle-kutu";

  const baslik = document.createElement("div");
  baslik.className = "dk-pp-baslik";
  baslik.classList.add("dk-pp-duzenle-baslik");
  const baslikAd = document.createElement("span");
  baslikAd.className = "dk-pp-duzenle-baslik-ad";
  baslikAd.textContent = paramAd;
  baslik.appendChild(baslikAd);
  // FAZ18-IS4-PARAM-KUTU: kapatma dugmesi. Onceden kutunun tek cikisi
  // IPTAL dugmesiydi; kullanici kapatma (X) arayip bulamiyordu.
  const btnKapat = document.createElement("button");
  btnKapat.type = "button";
  btnKapat.className = "dk-pp-duzenle-kapat";
  btnKapat.innerHTML = "<i class='fa-solid fa-xmark'></i>";
  btnKapat.title = (t.dkParamKutuKapat || "Kapat");
  btnKapat.setAttribute("aria-label", btnKapat.title);
  baslik.appendChild(btnKapat);
  kutu.appendChild(baslik);

  // BUYUK FONTLU ACIKLAMA (secili dilde; TR ise Turkce ceviri)
  const aciklama = dkParamAciklamaGetir(paramAd);
  if (aciklama) {
    const acikDiv = document.createElement("div");
    acikDiv.className = "dk-pp-duzenle-aciklama";
    acikDiv.textContent = aciklama;
    kutu.appendChild(acikDiv);
  }

  // v2.4.19: deger secenekleri (combo box / bitmask) metadata
  const secenek = paramSecenekGetir(paramAd, sysid);
  const secDegerler = (secenek && secenek.v) ? secenek.v : null;
  const secBitler = (secenek && secenek.b) ? secenek.b : null;

  const mevcutSatir = document.createElement("div");
  mevcutSatir.className = "dk-pp-mevcut";
  const mevcutAnlam = paramDegerAnlami(paramAd, mevcutDeger, sysid);
  mevcutSatir.innerHTML = (t.dkParamMevcut || "Mevcut") + ": <strong>" +
    parseFloat(mevcutDeger).toFixed(4).replace(/\.?0+$/, "") + "</strong>" +
    (mevcutAnlam ? " <span class='dk-pp-mevcut-anlam'>— " +
      mevcutAnlam.replace(/</g, "&lt;") + "</span>" : "");
  kutu.appendChild(mevcutSatir);

  // v2.4.15: min/maks/artis/birim bilgisi (ArduPilot parametre metadata)
  const meta = dkParamMetaGetir(paramAd);
  let aralikDiv = null;
  if (meta && (meta.min !== undefined || meta.max !== undefined ||
               meta.inc !== undefined || meta.unit)) {
    aralikDiv = document.createElement("div");
    aralikDiv.className = "dk-pp-aralik";
    const parcalar = [];
    if (meta.min !== undefined)
      parcalar.push("<span>" + (t.dkParamMin || "Min") + ": <strong>" + meta.min + "</strong></span>");
    if (meta.max !== undefined)
      parcalar.push("<span>" + (t.dkParamMaks || "Maks") + ": <strong>" + meta.max + "</strong></span>");
    if (meta.inc !== undefined)
      parcalar.push("<span>" + (t.dkParamArtis || "Artış") + ": <strong>" + meta.inc + "</strong></span>");
    if (meta.unit)
      parcalar.push("<span>" + (t.dkParamBirim || "Birim") + ": <strong>" + meta.unit + "</strong></span>");
    aralikDiv.innerHTML = "<i class='fa-solid fa-ruler-horizontal'></i> " + parcalar.join(" &nbsp;·&nbsp; ") +
      (meta.enum ? " <span class='dk-pp-aralik-enum'>(" + (t.dkParamSecenek || "seçenek kodları") + ")</span>" : "");
    kutu.appendChild(aralikDiv);
  }

  const input = document.createElement("input");
  input.type = "number";
  input.step = "any";
  // v2.4.19: arama kutusu da dk-pp-input sinifini kullaniyor; duzenleme
  // alanini ayirt etmek icin ikinci sinif eklenir (secici cakismasi).
  input.className = "dk-pp-input dk-pp-duzenle-input";
  input.value = parseFloat(mevcutDeger);
  input.placeholder = t.dkParamYeniDeger || "Yeni değer";
  if (meta) {
    if (meta.min !== undefined) input.min = meta.min;
    if (meta.max !== undefined) input.max = meta.max;
    if (meta.inc !== undefined) input.step = meta.inc;
  }

  // -----------------------------------------------------------
  // v2.4.19: SECIM LISTESI (values) — Mission Planner combo box
  // Sayisal deger + anlami birlikte gosterilir. Listede olmayan bir
  // deger yaziliysa "Özel değer" secenegi eklenir; ayrica ELLE
  // GIRIŞ anahtariyla sayisal alan da kullanilabilir.
  // -----------------------------------------------------------
  let secim = null, bitKutulari = null, elleAnahtar = null;
  const mevcutSayi = parseFloat(mevcutDeger);

  if (secDegerler) {
    secim = document.createElement("select");
    secim.className = "dk-pp-secim";
    const anahtarlar = Object.keys(secDegerler).sort(
      (a, b) => parseFloat(a) - parseFloat(b));
    let eslesti = false;
    anahtarlar.forEach((k) => {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k + "  —  " + secDegerler[k];
      if (isFinite(mevcutSayi) && parseFloat(k) === mevcutSayi) {
        o.selected = true; eslesti = true;
      }
      secim.appendChild(o);
    });
    if (!eslesti && isFinite(mevcutSayi)) {
      const o = document.createElement("option");
      o.value = String(mevcutSayi);
      o.textContent = mevcutSayi + "  —  " +
        (t.dkParamOzelDeger || "özel değer (listede yok)");
      o.selected = true;
      secim.insertBefore(o, secim.firstChild);
    }
    secim.addEventListener("change", () => { input.value = secim.value; });
    kutu.appendChild(secim);
  }

  // -----------------------------------------------------------
  // v2.4.19: BITMASK — her bit icin onay kutusu
  // -----------------------------------------------------------
  if (secBitler) {
    bitKutulari = [];
    const kap = document.createElement("div");
    kap.className = "dk-pp-bitmask";
    const mask0 = isFinite(mevcutSayi) ? Math.round(mevcutSayi) : 0;
    const bitler = Object.keys(secBitler)
      .map((b) => parseInt(b, 10))
      .filter((b) => b >= 0 && b < 32)
      .sort((a, b) => a - b);
    const maskHesapla = () => {
      let m = 0;
      bitKutulari.forEach((cb) => {
        if (cb.checked) m |= (1 << Number(cb.dataset.bit));
      });
      input.value = m;
      if (typeof aralikKontrol === "function") aralikKontrol();
      const oz = kap.querySelector(".dk-pp-bitmask-ozet");
      if (oz) oz.textContent = (t.dkParamDegerToplam || "Toplam değer") +
        ": " + m;
    };
    bitler.forEach((b) => {
      const et = document.createElement("label");
      et.className = "dk-pp-bit";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.dataset.bit = String(b);
      cb.checked = !!(mask0 & (1 << b));
      cb.addEventListener("change", maskHesapla);
      bitKutulari.push(cb);
      const ad = document.createElement("span");
      ad.className = "dk-pp-bit-ad";
      ad.textContent = secBitler[String(b)];
      const no = document.createElement("span");
      no.className = "dk-pp-bit-no";
      no.textContent = "b" + b + " (" + (1 << b) + ")";
      et.appendChild(cb); et.appendChild(ad); et.appendChild(no);
      kap.appendChild(et);
    });
    const ozet = document.createElement("div");
    ozet.className = "dk-pp-bitmask-ozet";
    ozet.textContent = (t.dkParamDegerToplam || "Toplam değer") +
      ": " + mask0;
    kap.appendChild(ozet);
    kutu.appendChild(kap);
  }

  // Secim/bitmask varsa sayisal alan varsayilan olarak gizlenir;
  // "Elle değer gir" anahtariyla acilir (uzman kullanim).
  if (secDegerler || secBitler) {
    elleAnahtar = document.createElement("label");
    elleAnahtar.className = "dk-pp-elle-anahtar";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    const yazi = document.createElement("span");
    yazi.textContent = t.dkParamElleGir || "Ham sayısal değer gir";
    elleAnahtar.appendChild(cb); elleAnahtar.appendChild(yazi);
    input.style.display = "none";
    cb.addEventListener("change", () => {
      input.style.display = cb.checked ? "" : "none";
      if (secim) secim.disabled = cb.checked;
      if (bitKutulari) bitKutulari.forEach((x) => x.disabled = cb.checked);
      if (cb.checked) setTimeout(() => input.select(), 30);
    });
    kutu.appendChild(elleAnahtar);
  }
  kutu.appendChild(input);

  // v2.4.15: aralik disi deger uyarisi (yazma engellenmez — bilincli
  // kullanici asabilir; sadece gorsel uyari)
  const uyariDiv = document.createElement("div");
  uyariDiv.className = "dk-pp-aralik-uyari";
  uyariDiv.style.display = "none";
  kutu.appendChild(uyariDiv);
  function aralikKontrol() {
    if (!meta) return;
    const v = parseFloat(input.value);
    let mesaj = "";
    if (!isNaN(v)) {
      if (meta.min !== undefined && v < meta.min)
        mesaj = (t.dkParamAltinda || "Değer önerilen minimumun altında") + " (" + meta.min + ")";
      else if (meta.max !== undefined && v > meta.max)
        mesaj = (t.dkParamUstunde || "Değer önerilen maksimumun üstünde") + " (" + meta.max + ")";
    }
    if (mesaj) {
      uyariDiv.innerHTML = "<i class='fa-solid fa-triangle-exclamation'></i> " + mesaj;
      uyariDiv.style.display = "";
      input.classList.add("dk-pp-input-uyari");
    } else {
      uyariDiv.style.display = "none";
      input.classList.remove("dk-pp-input-uyari");
    }
  }
  input.addEventListener("input", aralikKontrol);
  aralikKontrol();

  // v2.4.19: sayisal alan elle degistirildiginde secim listesini ve
  // bitmask kutularini senkronla (tutarsiz gorunum olmasin)
  input.addEventListener("input", () => {
    const v = parseFloat(input.value);
    if (!isFinite(v)) return;
    if (secim) {
      const uy = Array.from(secim.options)
        .find((o) => parseFloat(o.value) === v);
      if (uy) secim.value = uy.value;
    }
    if (bitKutulari) {
      const m = Math.round(v);
      bitKutulari.forEach((cb) => {
        cb.checked = !!(m & (1 << Number(cb.dataset.bit)));
      });
      const oz = kutu.querySelector(".dk-pp-bitmask-ozet");
      if (oz) oz.textContent = (t.dkParamDegerToplam || "Toplam değer") +
        ": " + m;
    }
  });

  const btnBar = document.createElement("div");
  btnBar.className = "dk-pp-btn-bar";

  const btnKaydet = document.createElement("button");
  btnKaydet.className = "dk-pp-btn-kaydet";
  btnKaydet.innerHTML = "<i class='fa-solid fa-check'></i> " + "<span>" + ( (t.dkKaydet || "KAYDET")) + "</span>";
  btnKaydet.addEventListener("click", () => {
    const yeniDeger = parseFloat(input.value);
    if (isNaN(yeniDeger)) return;
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({tip: "param_yaz", sysid: sysid, ad: paramAd, deger: yeniDeger}));
    }
    // v2.4.15: bellekteki tam seti de guncelle (tree yeniden cizimde dogru olsun)
    if (_paramTumSet && paramAd in _paramTumSet) _paramTumSet[paramAd] = yeniDeger;
    // v2.4.38: hiz paneli onbellegi de tazelenir - iki ekran ayni degeri
    // gosterir (kullanicinin bildirdigi tutarsizligin diger yonu).
    dronAyarOnbellekGuncelle(sysid, paramAd, yeniDeger);
    duzenleKapat();
  });

  const btnIptal = document.createElement("button");
  btnIptal.className = "dk-pp-btn-iptal";
  btnIptal.innerHTML = "<i class='fa-solid fa-xmark'></i> " + "<span>" + ( (t.dkParamIptal || "İPTAL")) + "</span>";
  // FAZ18-IS4-PARAM-KUTU: kapatma tek islevde toplandi. Uc cikis yolu
  // (X, IPTAL, Esc) ayni yerden gecer; boylece Esc dinleyicisi de
  // kaldirilir ve govdede birikmez.
  function duzenleKapat() {
    try { document.removeEventListener("keydown", kacisDinle, true); }
    catch (e) {}
    overlay.remove();
  }
  function kacisDinle(ev) {
    if (ev.key !== "Escape") return;
    // Ortu govdede oldugu icin baska pencereler de Esc bekleyebilir;
    // olay yalniz bu kutu ekrandayken tuketilir.
    if (!overlay.isConnected) {
      document.removeEventListener("keydown", kacisDinle, true);
      return;
    }
    ev.stopPropagation();
    ev.preventDefault();
    duzenleKapat();
  }
  document.addEventListener("keydown", kacisDinle, true);
  btnKapat.addEventListener("click", duzenleKapat);
  btnIptal.addEventListener("click", duzenleKapat);

  btnBar.appendChild(btnIptal);
  btnBar.appendChild(btnKaydet);
  kutu.appendChild(btnBar);
  overlay.appendChild(kutu);

  // FAZ18-IS4-PARAM-KUTU: her zaman govdeye eklenir. Onceden liste
  // yolunda `_paramPopupEl` icine, ARM denetimi yolunda govdeye
  // ekleniyordu; ayni kutu iki farkli davranis gosteriyordu. Tek yola
  // indirildi.
  document.body.appendChild(overlay);
  // Kutu tasinabilir yapilir (pencere evreninin kendi surukleme
  // altyapisi kullanilir; basliktaki dugmeler surukleme baslatmaz).
  if (typeof window.popupTasinabilirYap === "function") {
    try { window.popupTasinabilirYap(kutu, baslik, "ppd_param_duzenle"); }
    catch (e) {}
  }
  // Secim listesi varsa odak listeye, yoksa sayisal alana
  setTimeout(() => {
    if (secim) secim.focus();
    else if (!secBitler) input.select();
  }, 50);
}

function dkParamYazildi(sysid, ad, deger, basari) {
  // v2.4.38: Hiz panelinin (dron ayarlari) onbellegi de tazelenir ve
  // sonuc kullaniciya bildirilir. Bu blok Parametreler popup'i KAPALI
  // olsa da calisir; asagidaki erken cikis yalnizca liste cizimini
  // atlar. Eskiden bu islev basta `_paramPopupSysid` kontrolune
  // dusuyordu, dolayisiyla hiz panelinden yapilan yazmalarda hicbir
  // geri bildirim gorunmuyordu.
  if (basari) dronAyarOnbellekGuncelle(sysid, ad, deger);
  if (typeof konsolYaz === "function") {
    const t0 = D();
    if (basari)
      konsolYaz("PARAM", (t0.dkParamYazildiBildirim ||
        "Parametre yazildi") + ": " + ad + " = " +
        parseFloat(deger).toFixed(4).replace(/\.?0+$/, ""), "basari");
    else
      konsolYaz("PARAM", (t0.dkParamYazilamadiBildirim ||
        "Parametre yazilamadi") + ": " + ad, "hata");
  }
  if (sysid !== _paramPopupSysid) return;
  // Listedeki degeri guncelle
  const sonucDiv = document.getElementById("dkParamSonuc");
  if (!sonucDiv) return;
  const satirlar = sonucDiv.querySelectorAll(".dk-pp-satir");
  for (const s of satirlar) {
    const adEl = s.querySelector(".dk-pp-ad");
    if (adEl && adEl.textContent === ad) {
      const valEl = s.querySelector(".dk-pp-val");
      if (valEl) {
        // v2.4.19: deger + anlami birlikte tazelenir
        const anlam = (typeof paramDegerAnlami === "function")
          ? paramDegerAnlami(ad, deger, sysid) : "";
        const kisa = anlam.length > 42 ? anlam.slice(0, 40) + "\u2026" : anlam;
        valEl.innerHTML =
          parseFloat(deger).toFixed(4).replace(/\.?0+$/, "") +
          (kisa ? "<span class='dk-pp-val-anlam' title=\"" +
            anlam.replace(/"/g, "&quot;") + "\">" +
            kisa.replace(/</g, "&lt;") + "</span>" : "");
      }
      s.style.borderLeft = basari ? "3px solid #4caf50" : "3px solid #f44336";
      setTimeout(() => s.style.borderLeft = "", 2000);
      break;
    }
  }
}

// =================================================================
// v2.4.23: ISLEMLER POPUP'I (dron kartindaki ISLEMLER dugmesi)
// Eski basliktaki uc nokta menusu (dronMenuAc) kaldirildi; tum
// komutlar burada 3 sutunlu buyuk dugmeler halinde sunulur.
// Harita uzerinde drona sol tiklama da bu popup'i acar (tek arayuz);
// eski dronMenuAc/dronMenuKapat tamamen kaldirildi.
// =================================================================
function dkIslemlerPopupAc(sysid, fare) {
  const kimlik = "dkPopupIslemler_" + sysid;
  if (dkPopupTekil(kimlik)) return;
  const t = D();
  const pop = document.createElement("div");
  pop.id = kimlik;
  pop.className = "dk-mini-popup dk-islem-popup";
  dkMiniPopupBaslikKur(
    pop, (t.dkIslemler || "\u0130\u015flemler") + " \u2014 D" + sysid,
    "pp_dkIslemler_" + sysid, "fa-sliders");

  const izgara = document.createElement("div");
  izgara.className = "dk-islem-izgara";
  pop.appendChild(izgara);

  // v2.5.0: GRUP BASLIGI — izgarada tum sutunlari kaplayan ayirici.
  // Gerekce: menu on bes dugmeden yirmi dorde cikti; duz izgarada
  // operator aradigi komutu tarayarak buluyordu.
  function grupAc(metin) {
    const b = document.createElement("div");
    b.className = "dk-islem-grup";
    b.textContent = metin;
    izgara.appendChild(b);
    return b;
  }
  // Buyuk dugme uretici: 3 sutunlu izgarada tek hucre
  function dugme(ikon, metin, cb, tehlikeli) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "dk-islem-hucre" + (tehlikeli ? " tehlikeli" : "");
    el.innerHTML =
      "<i class='fa-solid " + ikon + " dk-islem-hucre-ikon'></i>" +
      "<span class='dk-islem-hucre-metin'>" + metin + "</span>";
    el.title = metin;
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const fk = {x: ev.clientX, y: ev.clientY};
      pop.remove();          // islem secildi, popup kapanir
      cb(fk);
    });
    izgara.appendChild(el);
    return el;
  }

  // --- UCUS KOMUTLARI ---
  grupAc(t.dkGrupUcus || "U\u00c7U\u015e KOMUTLARI");
  dugme("fa-house", t.dkRth || "Return Home",
    () => onayIste(onayMetni("onayRtl"),
      () => dronKomutGonder(sysid, "rtl")), true);
  // v2.4.42: HOME'u aracin ANLIK konumuna ayarla. Koordinat GONDERILMEZ;
  // sunucu param1=1 ile otopilotun kendi konumunu kullanmasini ister.
  // Haritadan konum secmek icin SHIFT + sol tik kullanilir.
  // "tehlikeli" isaretlenir: RTL ve failsafe donus noktasini kalici
  // olarak degistirir.
  dugme("fa-house-flag", t.dkHomeAyarla || "HOME Ayarla",
    () => onayIste(onayMetni("onayHomeMevcut", {sysid: sysid}),
      () => {
        if (ws && ws.readyState === 1)
          ws.send(JSON.stringify({
            tip: "dron_komut", sysid: Number(sysid),
            aksiyon: "set_home"}));
      }), true);
  dugme("fa-cloud-arrow-up",
    t.dkRotayiYukle || t.dkRotayaGonder || "Rotay\u0131 Y\u00fckle", () => {
      if (typeof window.gorevRotaSecimAc === "function")
        window.gorevRotaSecimAc(sysid);
    });
  // v2.4.41: Gorev izleme paneli kapatildiysa buradan geri cagrilir.
  // Yalniz drona ait bir gorev kaydi varsa gosterilir; aksi halde
  // dugme bos bir panel acardi.
  if (typeof window.gorevIzlenebilirMi === "function" &&
      window.gorevIzlenebilirMi(sysid)) {
    dugme("fa-paper-plane", t.dkGorevIzle || "Görev İzle", () => {
      if (typeof window.gorevIzlemeGeriAc === "function")
        window.gorevIzlemeGeriAc(sysid);
    });
  }
  dugme("fa-crosshairs", t.angAngajeOl || "Angaje Ol",
    () => angajmanPopupAc("dron", sysid));
  dugme("fa-satellite-dish", t.angiBaslik || "Angajman \u0130zle", () => {
    if (typeof window.angajmanIzleAcKapat === "function")
      window.angajmanIzleAcKapat();
  });
  // Dron-dron takip: aktifse iptal, degilse baslatma popup'i
  const aktifTakip = dronTakipBul(sysid);
  if (aktifTakip) {
    dugme("fa-ban", t.dkTakipIptal || "Takibi \u0130ptal Et", () => {
      if (ws && ws.readyState === 1)
        ws.send(JSON.stringify({tip: "takip_iptal", sysid: Number(sysid)}));
    }, true);
  } else {
    dugme("fa-people-arrows", t.dkTakipEt || "Takip Et",
      (fk) => dkTakipPopupAc(fk, sysid));
  }
  // --- IZLEME / KAYIT ---
  grupAc(t.dkGrupIzleme || "\u0130ZLEME VE KAYIT");
  dugme("fa-wave-square", t.dkTelemetri || "Telemetri",
    (fk) => dkTelemetriPopupAc(sysid, fk));
  dugme("fa-clock-rotate-left", t.dkHistory || "History", () => {
    if (typeof window.dronGecmisAc === "function")
      window.dronGecmisAc(sysid);
  });
  dugme("fa-file-arrow-down", t.dkLogYonetimi || "Log Y\u00f6netimi",
    () => dkLogPopupAc(sysid));
  // --- DENETIM / AYAR ---
  grupAc(t.dkGrupDenetim || "DENET\u0130M VE AYAR");
  dugme("fa-clipboard-check", t.acBaslik || "Arm Check", (fk) => {
    if (typeof dkArmCheckPopupAc === "function")
      dkArmCheckPopupAc(sysid, fk);
  });
  dugme("fa-shield-halved", t.dkFailsafe || "Failsafe", (fk) => {
    if (typeof dkFailsafePopupAc === "function")
      dkFailsafePopupAc(fk, sysid);
  });
  dugme("fa-sliders", t.dkParametreler || "Parametreler",
    () => dkParamPopupAc(sysid));

  // --- BAKIM VE KALIBRASYON (v2.5.0) ---
  // Bu grup arac hazirlik islerini tasir: pervane dondurme, algilayici
  // kalibrasyonu, ilk ayar parametreleri, yakinlik algilayicisi ve
  // yeniden baslatma. Hepsi YERDE yapilir; ucus komutlarindan ayri
  // tutulmasinin gerekcesi budur.
  grupAc(t.dkGrupBakim || "BAKIM VE KAL\u0130BRASYON");
  // Kalibrasyon: v2.5.0 secim izgarasi (yedi tur, her biri ayri
  // pencerede canli mesaj akisi ve gorsel anlatimla acilir).
  dugme("fa-screwdriver-wrench", t.dkKalibrasyon || "Kalibrasyon", (fk) => {
    if (typeof window.dbKalibSecimAc === "function")
      window.dbKalibSecimAc(fk, sysid);
    else if (typeof dkKalibPopupAc === "function")
      dkKalibPopupAc(fk, sysid);   // geri uyumluluk
  });
  dugme("fa-fan", t.dkMotorTest || "Motor Testi", (fk) => {
    if (typeof window.dbMotorTestAc === "function")
      window.dbMotorTestAc(fk, sysid);
  }, true);
  dugme("fa-gauge-high", t.dkIlkAyar || "\u0130lk Ayar", (fk) => {
    if (typeof window.dbIlkAyarAc === "function")
      window.dbIlkAyarAc(fk, sysid);
  }, true);
  dugme("fa-shield-virus", t.dkYakinlik || "Yak\u0131nl\u0131k Alg\u0131lay\u0131c\u0131s\u0131",
    (fk) => {
      if (typeof window.dpxYakinlikAc === "function")
        window.dpxYakinlikAc(fk, sysid);
    });
  dugme("fa-power-off", t.dkReboot || "Yeniden Ba\u015flat", () => {
    if (typeof window.dbRebootIste === "function")
      window.dbRebootIste(sysid);
  }, true);

  // --- TANIM ---
  grupAc(t.dkGrupTanim || "TANIM");
  dugme("fa-pen", t.dkAdDegistir || "Ad\u0131n\u0131 De\u011fi\u015ftir",
    (fk) => dkIsimDuzenlePopup(fk, sysid));

  pop.style.position = "fixed";
  dkPopupOneGetirKur(pop);
  document.body.appendChild(pop);
  dkMiniPopupKonumla(pop, fare);
}
window.dkIslemlerPopupAc = dkIslemlerPopupAc;

// ---------------------------------------------------------------
// v2.4.23: eski DRON ACILIR MENUSU (dropdown) kaldirildi.
// Yerine dkIslemlerPopupAc (3 sutunlu buyuk dugmeler) kullanilir.
// ---------------------------------------------------------------

// Haritada dron entity'sine sol tik ile menu ac
(function() {
  // Ekran konumunda dron entity'si var mi? (drillPick: ust uste binen
  // billboard/label/polyline katmanlarinin hepsine bakar - hedefler.js
  // cift-tik deseniyle ayni yaklasim)
  function ekrandaDronBul(ekranPoz) {
    let secilen = [];
    try { secilen = viewer.scene.drillPick(ekranPoz, 8) || []; } catch (e) { return null; }
    for (const p of secilen) {
      const ent = p && p.id;
      if (!ent) continue;
      // 1) Entity referans karsilastirmasi (en guvenilir yol)
      for (const sid of Object.keys(varliklar)) {
        if (varliklar[sid] === ent) return parseInt(sid, 10);
      }
      // 2) Yedek: id string kontrolu (dron_ ve dron_yon_ oneklerini destekle)
      if (typeof ent.id === "string" && ent.id.startsWith("dron_")) {
        return parseInt(ent.id.replace("dron_yon_", "").replace("dron_", ""), 10);
      }
    }
    return null;
  }

  // Dron panelini (yuzen kart) haritadan ac: kart panelde ise ayir
  // (yuzen yap), zaten yuzen ise yalniz one getir (kapatma!).
  function dronPaneliHaritadanAc(sysid) {
    try {
      var kart = (typeof dronKartlar === "object" && dronKartlar) ? dronKartlar[sysid] : null;
      if (!kart || !kart.kok) {
        if (typeof window.dkIslemlerPopupAc === "function")
          window.dkIslemlerPopupAc(sysid, {});
        return;
      }
      var kok = kart.kok;
      if (kok.classList.contains("ayrik")) {
        if (typeof window.pencereEnUsteGetir === "function") window.pencereEnUsteGetir(kok);
        kok.classList.add("dk-vurgu");
        setTimeout(function(){ kok.classList.remove("dk-vurgu"); }, 600);
      } else if (typeof dronKartAyirToggle === "function") {
        dronKartAyirToggle(sysid);
      }
    } catch (e) { /* sessiz */ }
  }

  function dronTikIsle(clientX, clientY) {
    const canvas = viewer.scene.canvas;
    const rect = canvas.getBoundingClientRect();
    const ekranPoz = new Cesium.Cartesian2(clientX - rect.left, clientY - rect.top);
    const sysid = ekrandaDronBul(ekranPoz);
    if (sysid && sonVeri[sysid]) {
      // Kullanici istegi (2026-09): harita dron ikonuna tiklayinca ISLEMLER
      // popup'i DEGIL, DRON PANELI (yuzen kart) acilir. Kart panelde ise
      // ayrilip yuzen panele alinir; zaten yuzen (ayrik) ise one getirilir.
      dronPaneliHaritadanAc(sysid);
      return true;
    }
    return false;
  }

  function kurHaritaDronTik() {
    const kap = document.getElementById("cesiumContainer");
    if (!kap || typeof viewer === "undefined" || !viewer || !viewer.scene) {
      setTimeout(kurHaritaDronTik, 500); return;
    }
    // Viewer'in default LEFT_CLICK handler'ini kaldir (entity secim/takip
    // davranisi bizim menumuzle yarismasIn)
    try {
      viewer.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_CLICK);
    } catch(e) {}
    // DOM click dinleyicisi: Cesium ScreenSpaceEventHandler bazi
    // surum/tarayici kombinasyonlarinda tetiklenmeyebiliyor; harita_menu.js
    // ile ayni desen kullanildi (container uzerinde dogrudan DOM click).
    // Modifiyerli tiklar diger modullere ait: CTRL=dron gonder, ALT=konum kaydet.
    kap.addEventListener("click", (e) => {
      if (e.ctrlKey || e.altKey || e.shiftKey) return;
      // Rota duzenleme modundayken karisma
      if (window.__rotaDuzenlemeAktif && window.__rotaDuzenlemeAktif()) return;
      // v2.1.3: Cetvel modunda sade tiklamalar cetvele aittir
      if (window.__cetvelAktif && window.__cetvelAktif()) return;
      if (dronTikIsle(e.clientX, e.clientY)) return;
      // Dron degilse: radar hedefi mi? (hedefler.js'deki menuyu ac)
      if (typeof window.hedefHaritaTikIsle === "function")
        window.hedefHaritaTikIsle(e.clientX, e.clientY);
    });
  }
  kurHaritaDronTik();

  // ===============================================================
  // MANUEL KONTROL (WASD + ok tuslari + fiziksel joystick)
  // ---------------------------------------------------------------
  // - Kart basligindaki joystick anahtari acik olan TUM dronlar ayni
  //   eksen komutlariyla es zamanli hareket eder (backend cogullar).
  // - W/S: ileri/geri, A/D: yaw sola/saga DON, ArrowUp/ArrowDown: yuksel/alcal
  // - Q/E: sola/saga yanal kayma (strafe)
  // - Eksenler 5 Hz'de WS ile backend'e gider; backend 10 Hz MAVLink
  //   hiz komutuna cevirir. Fiziksel joystick backend'de okunur.
  // ===============================================================
  const manuelAktif = new Set();   // sysid'ler (backend onayli)
  let manuelJoystickVar = false;
  const manuelTuslar = {};         // code -> true (basili)
  let manuelTimer = null;

  function manuelAnahtarToggle(sysid) {
    const acik = !manuelAktif.has(sysid);
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ tip: "manuel_anahtar", sysid, acik }));
    }
    // Iyimser guncelleme (backend manuel_durum ile teyit eder)
    if (acik) manuelAktif.add(sysid); else manuelAktif.delete(sysid);
    manuelGorunumTazele();
    manuelDonguAyarla();
  }

  window.manuelDurumIsle = function (m) {
    manuelAktif.clear();
    for (const s of (m.aktif || [])) manuelAktif.add(s);
    manuelJoystickVar = !!m.joystick;
    manuelGorunumTazele();
    manuelDonguAyarla();
  };

  function manuelGorunumTazele() {
    const t = D();
    for (const sysid of Object.keys(dronKartlar)) {
      const kart = dronKartlar[sysid];
      if (!kart || !kart.joyBtn) continue;
      const acik = manuelAktif.has(Number(sysid));
      kart.joyBtn.classList.toggle("acik", acik);
      const durumEl = kart.joyBtn.querySelector(".dk-joy-durum");
      if (durumEl) durumEl.textContent = acik
        ? (t.dkAcikEtiket || "A\u00c7IK")
        : (t.dkKapaliEtiket || "KAPALI");
    }
  }

  // Tus yakalama: input/textarea odaktayken karisma
  function manuelHedefTus(ev) {
    const a = document.activeElement;
    if (a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA" ||
              a.isContentEditable)) return false;
    return ["KeyW","KeyA","KeyS","KeyD","KeyQ","KeyE",
            "ArrowUp","ArrowDown"].includes(ev.code);
  }
  document.addEventListener("keydown", (ev) => {
    if (manuelAktif.size === 0 || !manuelHedefTus(ev)) return;
    ev.preventDefault();
    if (!manuelTuslar[ev.code]) {
      manuelTuslar[ev.code] = true;
      manuelEksenGonder();   // ilk basista aninda gonder
    }
  });
  document.addEventListener("keyup", (ev) => {
    if (!manuelTuslar[ev.code]) return;
    delete manuelTuslar[ev.code];
    manuelEksenGonder();
  });
  window.addEventListener("blur", () => {
    // Pencere odagi kaybolursa tum tuslari birak (guvenlik)
    for (const k of Object.keys(manuelTuslar)) delete manuelTuslar[k];
    manuelEksenGonder();
  });

  // ---------------------------------------------------------------
  // TARAYICI JOYSTICK'I (Gamepad API)
  // - GCS'yi kullandiginiz bilgisayara takili joystick tarayicidan
  //   okunur; klavye eksenleriyle toplanip ayni WS mesajiyla gider.
  // - Not: Taraycilar guvenlik geregi joystick'i ancak bir tusuna
  //   basilinca/oynatilinca gorur (gamepadconnected olayi).
  // ---------------------------------------------------------------
  let gpIndex = -1;          // aktif gamepad index
  let gpBildirildi = false;
  // v2.4.50: SABIT OLU BOLGE (0.12) KALDIRILDI.
  //
  // Eski davranis: burada `Math.abs(v) < 0.12 ? 0 : v` uygulanip
  // sunucuya ISLENMIS deger gonderiliyordu. Iki ciddi sonucu vardi:
  //  1) Merkezi 0.13 kaymis bir cubuk esigi asiyor ve yaw ekseninde
  //     SUREKLI donme komutu uretiyordu (kullanicinin bildirdigi
  //     "joystick ortadayken dron kendi etrafinda donuyor" belirtisi).
  //  2) Kayma arayuzde maskelendigi icin sunucu gercek merkezi HIC
  //     goremiyor, dolayisiyla kalibrasyon imkansiz hale geliyordu.
  // Artik HAM deger gonderilir; olu bolge, merkez duzeltmesi ve pilot
  // tercihi (ters cevirme) sunucuda TEK yerde uygulanir.
  function gpEksenOku() {
    if (gpIndex < 0) return null;
    const gps = (navigator.getGamepads && navigator.getGamepads()) || [];
    const gp = gps[gpIndex];
    if (!gp || !gp.connected) return null;
    const n = gp.axes.length;
    // Standart gamepad duzeni: 0=sol X (yanal), 1=sol Y (ileri/geri),
    // 2=sag X (yaw), 3=sag Y (irtifa). 2-3 eksenli joysticklerde
    // eldeki eksenler sirayla kullanilir.
    // Y eksenlerinin isaret cevrimi DONANIM gercegidir (asagi = pozitif),
    // pilot tercihi degil; bu yuzden burada kalir.
    return {
      vy:  n > 0 ? gp.axes[0] : 0,     // sag+ yanal
      vx:  n > 1 ? -gp.axes[1] : 0,    // ileri+ (Y ters)
      yaw: n > 2 ? gp.axes[2] : 0,     // sag+ don
      vz:  n > 3 ? -gp.axes[3] : 0,    // yukari+ (Y ters)
    };
  }

  window.addEventListener("gamepadconnected", (e) => {
    gpIndex = e.gamepad.index;
    if (!gpBildirildi && typeof konsolYaz === "function") {
      konsolYaz("MANUEL", "Joystick algilandi (tarayici): " + e.gamepad.id, "basari");
      gpBildirildi = true;
    }
    manuelDonguAyarla();
  });
  window.addEventListener("gamepaddisconnected", (e) => {
    if (e.gamepad.index === gpIndex) {
      gpIndex = -1;
      if (typeof konsolYaz === "function")
        konsolYaz("MANUEL", "Joystick baglantisi kesildi (tarayici).");
      manuelEksenGonder();
    }
  });

  function manuelEksenGonder() {
    if (!ws || ws.readyState !== 1) return;
    let vx = (manuelTuslar["KeyW"] ? 1 : 0) + (manuelTuslar["KeyS"] ? -1 : 0);
    let vy = (manuelTuslar["KeyE"] ? 1 : 0) + (manuelTuslar["KeyQ"] ? -1 : 0);
    let vz = (manuelTuslar["ArrowUp"] ? 1 : 0) + (manuelTuslar["ArrowDown"] ? -1 : 0);
    let yaw = (manuelTuslar["KeyD"] ? 1 : 0) + (manuelTuslar["KeyA"] ? -1 : 0);
    // v2.4.50: Joystick eksenleri KLAVYEYE EKLENMEZ, `ham` alaninda
    // ayri gonderilir. Sebep: pilot tercihi (ters cevirme, olu bolge,
    // merkez) yalniz FIZIKSEL cubuga uygulanmalidir. Klavyeyle
    // toplanip gonderilse, "ileri eksenini ters cevir" ayari W tusunu
    // da tersine cevirir ve pilot W'ye basinca dron GERI gider.
    const g = gpEksenOku();
    const mesaj = { tip: "manuel_eksen", vx, vy, vz, yaw };
    if (g) mesaj.ham = g;
    ws.send(JSON.stringify(mesaj));
  }

  function manuelDonguAyarla() {
    // Anahtar acikken eksenleri periyodik gonder; joystick varsa 20 Hz
    // (surekli okuma gerekir), yalniz klavyede 5 Hz yeterli.
    if (manuelAktif.size > 0 && manuelTimer === null) {
      manuelTimer = setInterval(() => {
        if (gpIndex >= 0 || Object.keys(manuelTuslar).length > 0)
          manuelEksenGonder();
      }, 50);
    } else if (manuelAktif.size === 0 && manuelTimer !== null) {
      clearInterval(manuelTimer);
      manuelTimer = null;
    }
  }

  // Sayfa yuklenince mevcut durumu iste (yeniden baglanmada senkron)
  window.addEventListener("load", () => {
    setTimeout(() => {
      if (ws && ws.readyState === 1)
        ws.send(JSON.stringify({ tip: "manuel_durum" }));
    }, 1500);
  });

  window.manuelAnahtarToggle = manuelAnahtarToggle;
})();

// FAZ18-DRON-EKRAN-DISI: ekran disi gosterge tiklamasi icin disa acilir.
window.dronaGit = dronaGit;

/* FAZ18-IS2B-IKON-METIN-SPAN */

// ================================================================
// 2026-09: TELEMETRI PENCERESI KOPRUSU (drontelemetri.html, 2. monitor)
// Ayri pencere kendi WS/auth kurmaz; ana pencere BroadcastChannel ile
// telemetriyi yeniden yayinlar ve pilota-ozel dizilim get/save'i WS'e
// role eder. Yalniz bir dinleyici pencere varken yayin yapilir (ping).
// ================================================================
(function(){
  var K = null;
  try { if (typeof BroadcastChannel !== "undefined") K = new BroadcastChannel("goktungu-telemetri"); }
  catch (e) { K = null; }
  if (!K) return;
  var sonPing = 0;
  function wsGonder(obj){
    try { if (typeof ws !== "undefined" && ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
    catch (e) {}
  }
  window.telemetriKopruYayinla = function(d){
    if (!d || (Date.now() - sonPing) > 15000) return;
    try { K.postMessage({t:"telemetri", sysid:d.sysid, d:d}); } catch (e) {}
  };
  window.telemetriDizilimGeldi = function(m){
    try { K.postMessage({t:"dizilim", dizilim:(m && m.dizilim) || []}); } catch (e) {}
  };
  // Gece/gunduz temasini telemetri pencerelerine yansit (kaynaktan
  // bagimsiz: data-tema niteligini izle). Ana app tema degistirince
  // ikinci monitordeki drontelemetri.html de gecer.
  function temaOku(){ try { return document.documentElement.getAttribute("data-tema") === "acik" ? "acik" : "koyu"; } catch (e) { return "koyu"; } }
  function temaYayinla(){ try { K.postMessage({t:"tema", tema:temaOku()}); } catch (e) {} }
  try { new MutationObserver(temaYayinla).observe(document.documentElement, {attributes:true, attributeFilter:["data-tema"]}); } catch (e) {}
  K.onmessage = function(ev){
    var m = ev.data || {};
    if (m.t === "tw_ping") { sonPing = Date.now(); temaYayinla(); }
    else if (m.t === "tw_dizilim_iste") { wsGonder({tip:"telemetri_dizilim"}); }
    else if (m.t === "tw_dizilim_yaz") { wsGonder({tip:"telemetri_dizilim_yaz", dizilim:(m.dizilim || [])}); }
  };
})();

// 2026-09: Telemetri (.tlog) kayit listesi — Log Yonetimi popup bolumu.
window.dkTlogListesiGeldi = function(m){
  var el = document.getElementById("dkTlogListe"); if (!el) return;
  var kayitlar = (m && m.kayitlar) || [];
  if (!kayitlar.length){ el.textContent = (D().dkTlogYok || "Kay\u0131t yok."); return; }
  el.innerHTML = "";
  kayitlar.forEach(function(r){
    var url = (typeof window.appYolu === "function") ? window.appYolu(r.url) : r.url;
    var boyut = (r.boyut > 1048576) ? (r.boyut/1048576).toFixed(1)+" MB"
                                    : Math.round(r.boyut/1024)+" KB";
    var tarih = "";
    try { tarih = new Date(r.zaman*1000).toLocaleString(); } catch(e){}
    var satir = document.createElement("div"); satir.className = "dk-tlog-satir";
    var bilgi = document.createElement("div"); bilgi.className = "dk-tlog-bilgi";
    bilgi.innerHTML = "<span class='dk-tlog-ad' title='"+r.ad+"'>"+r.ad+"</span>" +
      "<span class='dk-tlog-meta'>"+tarih+" \u00b7 "+boyut+"</span>";
    satir.appendChild(bilgi);
    var a = document.createElement("a"); a.className = "dk-tlog-indir";
    a.href = url; a.download = r.ad; a.title = (D().dkIndir || "\u0130ndir");
    a.innerHTML = "<i class='fa-solid fa-download'></i>";
    satir.appendChild(a);
    var sil = document.createElement("button"); sil.className = "dk-tlog-sil";
    sil.title = (D().dkSil || "Sil"); sil.innerHTML = "<i class='fa-solid fa-trash'></i>";
    sil.addEventListener("click", function(){
      if (ws && ws.readyState === 1){
        ws.send(JSON.stringify({tip:"tlog_sil", ad:r.ad}));
        setTimeout(function(){ ws.send(JSON.stringify({tip:"tlog_listesi"})); }, 250);
      }
    });
    satir.appendChild(sil);
    el.appendChild(satir);
  });
};
