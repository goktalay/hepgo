// =================================================================
// HEPGO - GÖKTUNGU harekât arayüzü köprüsü (ws.js'in YERİNE yüklenir)
// -----------------------------------------------------------------
// GÖKTUNGU betikleri (dronlar.js, seri.js, gorev.js, rotalar.js, arm_check.js …)
// DEĞİŞTİRİLMEDEN kullanılır. Bu dosya iki dünya arasındaki çeviricidir:
//   * GÖREV BAĞLAMI (Faz 1, kullanıcı kararı 5): sayfa ?task=<id> ile açılır.
//     GET /api/field/tasks/<id>/live → FLIGHTS (görevin uçakları/dronları, köprü ve
//     link bilgisiyle); soket açılınca {t:'watch', task_id} gönderilir, sunucu
//     hello{task, flights, bridges} ile yalnız görevin köprülerini/sanal dronlarını
//     yayınlar. ?task yoksa harita + bilgi kutusu (serbest uçuş YOK).
//   * Gerçek soket: HEPGO /ws/drone/live (app/drone_hub.py; çerez oturumu).
//     Gelen: hello / status / bridge / event / res / console / console_hist /
//     param / log / pong / error. Giden: ping / watch / cmd / console_hist / console_clear.
//   * Sahte soket: seri.js'te bildirilen `let ws` değişkenine ATANIR (burada
//     yeniden bildirilmez). GÖKTUNGU modülleri ws.send(JSON) ile "tip" tabanlı
//     mesaj gönderir; CEVIR tablosu bunları HEPGO komutlarına / REST çağrılarına
//     çevirir, kapsam dışı tipler YUT ile sessizce düşürülür.
//   * Telemetri: sunucudan 10 Hz gelen status paketleri DURUM tamponunda
//     toplanır; 200 ms'de bir GÖKTUNGU biçiminde tek `telemetri` paketi
//     üretilir ve buradaki sade telemetriIsle ile dağıtılır.
//   * Bağlantı Yöneticisi (seri.js): gruplar görevin UÇUŞLARIDIR (id "f<flight_id>"):
//     her uçuş için köprü satırı (bridge_name, çevrimiçi/çevrimdışı) ve altında dron
//     kartı. seri.js'in Play/Stop düğmeleri "Bağlan/Kes" olarak kullanılır:
//     baglanti_baslat → cmd link_open{link + sysid}, baglanti_durdur → link_close.
//     Sanal dron (protocol 'sanal'): sunucu içi köprü bridge_id = -drone_id, otomatik bağlı.
//   * Rotalar: harekât ekranında listelenmez (kullanıcı kararı 4); yalnız göreve
//     yüklenen rota (gorev.js rota_tek_goster / gorev_yukle) haritada çizilir.
// Klasik <script>; ortak global kapsam. Üst düzeyde yalnız `var` ve function
// declaration kullanılır (GÖKTUNGU dosyalarının const/let bildirimleriyle
// çakışmamak için). Yükleme sırası: seri.js → … → hepgo_patch.js → hepgo_ws.js.
// =================================================================

var wsDurum = document.getElementById("wsDurum");   // alt bar WS göstergesi (ws.js:8 karşılığı)

// Sunucu yetenek bayrakları (hepgo_patch.js tanımlamış olabilir; hello.caps ile güncellenir)
window.HEPGO_OZ = window.HEPGO_OZ || {
  param: false, bakim: false, log: false, set_home: false, arm_zorla: false,
  konsol_sunucu: false, arm_check_sunucu: false, altitude_change: false, mission_set_current: false
};
// hello.caps anahtarı → HEPGO_OZ bayrağı (birden fazla anahtar aynı bayrağı açabilir)
var HEPGO_CAPS_ESLEM = {
  console: "konsol_sunucu", arm_check: "arm_check_sunucu", set_home: "set_home", param: "param",
  log: "log", bakim: "bakim", reboot: "bakim", arm_force: "arm_zorla", altitude_change: "altitude_change",
  mission_set_current: "mission_set_current"
};
window.HEPGO_YETKI = false;          // hello.me.can_command

// ---------------- Tamponlar ----------------
var DURUM = {};          // uid (bridge_id:sysid) → {bridge_id, sysid, gorunen, state, alindi(ms)}
var KOPRULER = {};       // bridge_id(str) → {bridge_id, name, host, platform, bridge_ver, online, sira, caps}
var FLIGHTS = [];        // GET /api/field/tasks/<id>/live → flights: {id, order_id, drone_id, label, name, protocol, sysid, bridge_id,
                         //   bridge_name, bridge_online, link {type, host?, port?, serial?, baud?}, sim_bridge_id (sanal: -drone_id)}
var GOREV_ID = (function(){   // iframe ?task=<id> (drone.js renderLive); yoksa null → bilgi kutusu, soket açılmaz
  try { const n = parseInt(new URLSearchParams(location.search).get("task"), 10); return (n > 0) ? n : null; } catch (e) { return null; }
})();
var GOREV_BILGI = null;  // {id, code, status, location_name, lat?, lon?} (REST live → hello.task ile güncellenir)
var LINK_DURUM = {};     // flight id → "aciliyor" | "acik" (link_open gönderildi / kabul edildi; telemetri gelene dek "bağlanıyor")
var LINK_ZAMAN = {};     // flight id → ms (link_open kabul zamanı; LINK_TELEMETRI_SN içinde telemetri gelmezse düşer)
var LINK_TELEMETRI_SN = 30;
var ROTA_GORUNUR = {};   // rota id(str) → true: haritada çizilir (yalnız göreve yüklenen rota; bellek içi, kalıcı değil)
var KONSOL_TAMPON = {};  // görünen sysid → [satir] (son 200; sunucu konsolu yoksa)
var MESAJ_TAMPON = {};   // görünen sysid → [{ts, metin, sev, tekrar}] (ARM CHECK mesajlar sekmesi, istemci raporu)
var UYARI_TAMPON = [];   // uyarı merkezi listesi için yerel olaylar [{mesaj, ts, okundu}]
var BEKLEYEN = {};       // rid → {tip, sysid(görünen), gercek, bridge_id, name, params, ekler, timer}
var GOREV = {};          // görünen sysid → gorev_durum paketi (gorev.js sözleşmesi)
var PARAM_ONBELLEK = {}; // görünen sysid → {AD: deger} ({t:'param'} akışından)
var ROTALAR = [];        // GÖKTUNGU biçiminde rota listesi (rotalar.js rotaListesiIsle)
var GORUNEN = {};        // uid → görünen sysid (çakışmada sanal)
var KOPRU_OF = {};       // görünen sysid → {bridge_id, sysid, uid}
var KOPRU_SIRA_SAYAC = 0;
var ridSayac = 0;
var gercekWs = null, yenidenZaman = null, pingZaman = null, yetkiYok = false, ilkHello = true;
var sonPaketBos = false, cakismaBildirildi = {}, toastSon = {};

// ---------------- Küçük yardımcılar ----------------
function hwT(tr, en){ return (typeof aktifDil !== "undefined" && aktifDil === "EN") ? en : tr; }
function hwToast(mesaj, seviye, kategori){
  const anahtar = (kategori || "") + "|" + mesaj;
  const simdi = Date.now();
  if (toastSon[anahtar] && simdi - toastSon[anahtar] < 8000) return;   // aynı bildirim 8 sn'de bir
  toastSon[anahtar] = simdi;
  if (typeof window.uyariToastGoster === "function")
    try { window.uyariToastGoster({mesaj: mesaj, seviye: seviye || "uyari", kategori: kategori || "HEPGO"}); } catch (e) {}
}
// Genel konsol (#konsolKutu) satırı; konsol.js konsolYaz ile aynı DOM deseni ama TOAST ÜRETMEZ
// (toast kararı çağıran yerde verilir; aksi halde aynı olay iki kez bildirilir).
function hwKonsol(kaynak, mesaj, seviye){
  const kutu = document.getElementById("konsolKutu");
  if (!kutu) return;
  const altta = (kutu.scrollTop + kutu.clientHeight) >= (kutu.scrollHeight - 24);
  const d = new Date(), iki = (n) => String(n).padStart(2, "0");
  const sat = document.createElement("span");
  sat.className = "k-satir k-" + (seviye || "bilgi");
  const z = document.createElement("span"); z.className = "k-zaman";
  z.textContent = iki(d.getHours()) + ":" + iki(d.getMinutes()) + ":" + iki(d.getSeconds()) + " ";
  const k = document.createElement("span"); k.className = "k-kaynak"; k.textContent = "[" + kaynak + "] ";
  sat.appendChild(z); sat.appendChild(k); sat.appendChild(document.createTextNode(mesaj));
  kutu.appendChild(sat);
  while (kutu.childElementCount > 200) kutu.removeChild(kutu.firstElementChild);
  if (altta) kutu.scrollTop = kutu.scrollHeight;
}
function hwYerel(anahtar, varsayilan){
  try { const v = localStorage.getItem(anahtar); return v === null ? varsayilan : JSON.parse(v); } catch (e) { return varsayilan; }
}
function hwYerelYaz(anahtar, deger){ try { localStorage.setItem(anahtar, JSON.stringify(deger)); } catch (e) {} }
function hwSev(severity){   // MAV_SEVERITY 0-7 → GÖKTUNGU konsol seviyesi
  const s = Number(severity);
  return s <= 3 ? "hata" : s === 4 ? "uyari" : s === 5 ? "basari" : "bilgi";
}
async function hwFetch(url, secenek){
  const o = Object.assign({credentials: "same-origin", headers: {}}, secenek || {});
  if (o.body !== undefined && typeof o.body !== "string"){ o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
  const y = await fetch(url, o);
  let veri = null;
  try { veri = await y.json(); } catch (e) { veri = null; }
  if (!y.ok){
    const det = veri && (veri.detail || veri.error);   // FastAPI 422: detail dizi [{loc, msg}] → okunur metin
    const metin = Array.isArray(det) ? det.map(x => ((x.loc || []).slice(1).join(".") + ": " + x.msg)).join("; ") : det;
    const hata = new Error(metin || (y.status + " " + y.statusText));
    hata.status = y.status;
    throw hata;
  }
  return veri;
}
function hwUid(bridgeId, sysid){ return String(bridgeId) + ":" + String(sysid); }
// HTML kaçışı: arm_check.js acOzetCiz ozet.sebep / mod alanlarını innerHTML ile basar (STATUSTEXT ham metin olabilir)
function hwKacis(s){ return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
// Sunucu/istemci ARM CHECK raporunu GÖKTUNGU arm_check.js biçimine getirir: aciklama→deger, bilinmeyen grup→sensor, kaçış
function armRaporNormalize(rapor){
  if (!rapor || typeof rapor !== "object") return rapor;
  if (rapor.ozet && typeof rapor.ozet === "object") rapor.ozet.sebep = rapor.ozet.sebep == null ? null : hwKacis(rapor.ozet.sebep);
  rapor.mod = hwKacis(rapor.mod);
  (Array.isArray(rapor.maddeler) ? rapor.maddeler : []).forEach(x => {
    if (!x.deger && !x.mesaj && x.aciklama) x.deger = x.aciklama;
    if (["prearm", "sensor", "konum", "guc", "rc"].indexOf(x.grup) < 0) x.grup = "sensor";
  });
  return rapor;
}

// ---------------- Sysid çakışması: görünen (sanal) sysid ----------------
// GÖKTUNGU kimlikleri yalnız sysid'e dayanır (dron_<sysid>, #dronKart_<sysid>). İki köprüde aynı
// sysid görülürse ikinci köprünün dronuna sysid + 100 × köprü sırası verilir; komutta geri çevrilir.
var CAKISMA_OFSET = {};   // bridge_id → 1, 2, … (çakışması görülen köprülerin sırası; ilk çakışan köprü +100)
function cakismaOfseti(bridgeId){
  const bid = String(bridgeId);
  if (!CAKISMA_OFSET[bid]) CAKISMA_OFSET[bid] = Object.keys(CAKISMA_OFSET).length + 1;
  return CAKISMA_OFSET[bid];
}
function gorunenSysid(bridgeId, sysid){
  const uid = hwUid(bridgeId, sysid);
  if (GORUNEN[uid] !== undefined) return GORUNEN[uid];
  let g = Number(sysid);
  const sahip = KOPRU_OF[g];
  if (sahip && String(sahip.bridge_id) !== String(bridgeId)){
    g = Number(sysid) + 100 * cakismaOfseti(bridgeId);
    while (KOPRU_OF[g]) g += 100;
    if (!cakismaBildirildi[uid]){
      cakismaBildirildi[uid] = true;
      const ad = (KOPRULER[String(bridgeId)] || {}).name || ("köprü " + bridgeId);
      hwToast(hwT("Aynı sysid (" + sysid + ") birden fazla köprüde görüldü; " + ad + " dronu D" + g + " olarak gösteriliyor",
                  "Duplicate sysid (" + sysid + ") across bridges; " + ad + " drone shown as D" + g), "uyari", "DRON");
    }
  }
  GORUNEN[uid] = g;
  KOPRU_OF[g] = {bridge_id: Number(bridgeId), sysid: Number(sysid), uid: uid};
  return g;
}

// ---------------- Görev bağlamı: uçuşlar (dron adı, grup, köprü, link) ----------------
function hwVar(v){ return v !== null && v !== undefined; }
function ucusYukle(){   // REST: görevin uçuşları; 403/404 → hepgoBaslat bilgi kutusu gösterir
  return hwFetch("/api/field/tasks/" + GOREV_ID + "/live").then(y => {
    if (y && y.task) gorevBilgiAyarla(y.task);
    ucuslariAyarla(y && y.flights);
    if (y && typeof y.can_command === "boolean") window.HEPGO_YETKI = y.can_command;   // hello.me.can_command gelince yenilenir
    return y;
  });
}
function ucuslariAyarla(liste){
  FLIGHTS = Array.isArray(liste) ? liste : [];
  window.HEPGO_ENVANTER = {};   // hepgo_patch.js dronGecmisAc yedeği: '<bridge_id>:<sysid>' → {code, name, id}
  for (const f of FLIGHTS){
    const bid = (f.protocol === "sanal") ? f.sim_bridge_id : f.bridge_id;
    if (hwVar(bid) && hwVar(f.drone_id)) window.HEPGO_ENVANTER[bid + ":" + (hwVar(f.sysid) ? f.sysid : 1)] = {code: f.label, name: f.name, id: f.drone_id};
    // sanal dronun sunucu içi köprüsü: hello/status gelmeden listede görünsün (çevrimdışı; SimDrone watch ile başlar)
    if (f.protocol === "sanal" && hwVar(f.sim_bridge_id) && !KOPRULER[String(f.sim_bridge_id)])
      kopruKaydet({bridge_id: f.sim_bridge_id, name: "Sanal · " + (f.label || f.name || f.drone_id)}, false);
  }
}
// (bridge_id, sysid) → uçuş. Sanal: bridge_id < 0 → sim_bridge_id. Gerçek: köprü + sysid tam eşleşme; sysid'siz tek uçuş yalnız
// köprüde o anda tek dron görünüyorsa eşlenir (iki dron aynı uçuşa düşmesin).
function ucusBul(bridgeId, sysid){
  const bid = Number(bridgeId), sid = Number(sysid);
  if (bid < 0) return FLIGHTS.find(f => Number(f.sim_bridge_id) === bid) || null;
  const tam = FLIGHTS.find(f => hwVar(f.bridge_id) && Number(f.bridge_id) === bid && hwVar(f.sysid) && Number(f.sysid) === sid);
  if (tam) return tam;
  const adaylar = FLIGHTS.filter(f => hwVar(f.bridge_id) && Number(f.bridge_id) === bid && !hwVar(f.sysid));
  const kopruDronSayisi = Object.keys(DURUM).filter(u => u.indexOf(String(bid) + ":") === 0).length;
  return (adaylar.length === 1 && kopruDronSayisi <= 1) ? adaylar[0] : null;
}
function ucusGrupId(f){ return "f" + f.id; }                       // seri.js bağlantı kaydı id'si (data-bag-govde / data-bag-grup)
function ucusGrupBul(id){ const m = /^f(\d+)$/.exec(String(id)); return m ? (FLIGHTS.find(f => Number(f.id) === Number(m[1])) || null) : null; }
function ucusEtiket(f){ return String(f.label || "") + (f.name ? (f.label ? " · " : "") + f.name : ""); }   // "KY-0007 · Caymaz C-1"
function ucusKopruAdi(f){
  if (f.protocol === "sanal") return "Sanal · " + (f.label || f.name || "");
  if (!hwVar(f.bridge_id)) return hwT("Köprü seçilmedi", "No bridge selected");
  const k = KOPRULER[String(f.bridge_id)];
  return f.bridge_name || (k && k.name) || ("Köprü " + f.bridge_id);
}
function ucusKopruOnline(f){
  const bid = (f.protocol === "sanal") ? f.sim_bridge_id : f.bridge_id;
  if (!hwVar(bid)) return false;
  const k = KOPRULER[String(bid)];
  if (k) return !!k.online;
  return (f.protocol === "sanal") ? false : !!f.bridge_online;   // hello gelmeden REST bilgisi
}
function ucusDronuVar(f){   // bu uçuşa eşlenen dron telemetride canlı mı (dCevir baglanti ile aynı 5 sn eşiği)
  for (const uid of Object.keys(DURUM)){
    const k = DURUM[uid], u = ucusBul(k.bridge_id, k.sysid);
    if (u && u.id === f.id){ const yas = hbYasSn(k); if (yas === null || yas < 5) return true; }
  }
  return false;
}
// seri.js durumları: kapali | baglaniyor | bagli | hata (bagListeCiz sarmalı metinleri HEPGO'ya göre yazar)
function ucusDurumu(f){
  const online = ucusKopruOnline(f);
  if (f.protocol === "sanal") return {durum: ucusDronuVar(f) ? "bagli" : (online ? "baglaniyor" : "kapali"), hata: ""};
  if (!hwVar(f.bridge_id) || !online) return {durum: "kapali", hata: ""};
  if (ucusDronuVar(f)){ delete LINK_ZAMAN[f.id]; return {durum: "bagli", hata: ""}; }
  if (LINK_DURUM[f.id] === "aciliyor") return {durum: "baglaniyor", hata: ""};
  if (LINK_DURUM[f.id] === "acik"){   // köprü link'i açtı, telemetri bekleniyor (spinner; tık → link_close ile vazgeç)
    if (LINK_ZAMAN[f.id] && Date.now() - LINK_ZAMAN[f.id] > LINK_TELEMETRI_SN * 1000){
      delete LINK_DURUM[f.id]; delete LINK_ZAMAN[f.id];
      hwToast(ucusEtiket(f) + ": " + hwT("bağlantı açıldı ama " + LINK_TELEMETRI_SN + " sn içinde telemetri gelmedi; adres/port/baud ve aracın gücünü denetleyin",
                                          "link opened but no telemetry within " + LINK_TELEMETRI_SN + " s; check address/port/baud and vehicle power"), "uyari", "KÖPRÜ");
      return {durum: "kapali", hata: ""};
    }
    return {durum: "baglaniyor", hata: ""};
  }
  return {durum: "kapali", hata: ""};
}
function ucusDurumlari(){ const d = {}; for (const f of FLIGHTS) d[ucusGrupId(f)] = ucusDurumu(f); return d; }
function linkOzet(f){   // köprü satırı alt metni (seri.js bagAltMetin: tur 'merkez' → host aynen yazılır)
  if (f.protocol === "sanal") return hwT("Sunucu içi sanal dron · otomatik bağlı", "Server-side virtual drone · auto-connected");
  const l = f.link;
  if (!l || !l.type) return hwT("Bağlantı seçilmedi (görev › Uçuş Yönetimi › Düzenle)", "No link selected (task › Flight Management › Edit)");
  const t = String(l.type).toLowerCase(), sys = hwVar(f.sysid) ? " · sysid " + f.sysid : "";
  if (t === "serial") return (l.serial || "?") + " @ " + (l.baud || 57600) + sys;
  return t.toUpperCase() + " " + (l.host ? l.host : "") + ":" + (hwVar(l.port) ? l.port : "?") + sys;
}
// görev dışı köprülerin mesajları düşürülür (sunucu filtresi watch'tan önce gelen ilk hello'da devrede olmayabilir)
function gorevKoprusuMu(bridgeId){
  const bid = Number(bridgeId);
  return FLIGHTS.some(f => (hwVar(f.bridge_id) && Number(f.bridge_id) === bid) || (hwVar(f.sim_bridge_id) && Number(f.sim_bridge_id) === bid));
}
function gorevBilgiAyarla(task){
  GOREV_BILGI = Object.assign({}, GOREV_BILGI || {}, task || {});
  const kod = GOREV_BILGI.code || ("#" + (GOREV_BILGI.id || GOREV_ID));
  try { document.title = "HEPGO HAREKÂT · " + kod; } catch (e) {}
  const rozet = document.getElementById("hepgoGorevRozet"), metin = document.getElementById("hepgoGorevRozetMetin");
  if (rozet && metin){
    metin.textContent = kod;
    if (GOREV_BILGI.location_name){ const k = document.createElement("small"); k.textContent = " · " + GOREV_BILGI.location_name; metin.appendChild(k); }
    rozet.style.display = "";
  }
}
// Görev yeri: kullanıcı harita merkezi kaydetmemişse kamera görev yerine uçar (gcsKonum: dron etiketi mesafe referansı)
function gorevHaritaMerkezi(){
  const t = GOREV_BILGI || {};
  if (typeof t.lat !== "number" || typeof t.lon !== "number") return;
  if (hwYerel("hepgo_ops_merkez", null)) return;
  try { if (typeof gcsGuncelle === "function") gcsGuncelle(t.lat, t.lon); } catch (e) {}
  try {
    if (typeof viewer !== "undefined" && viewer && typeof Cesium !== "undefined")
      viewer.camera.flyTo({destination: Cesium.Cartesian3.fromDegrees(t.lon, t.lat, 2500), duration: 1.2});
  } catch (e) {}
}
// Bilgi kutusu (index.html #hepgoBilgiKutu): görev bağlamı yok / yetki yok / görev bulunamadı
function bilgiKutuGoster(baslik, metin, dugme, hash){
  const kutu = document.getElementById("hepgoBilgiKutu");
  if (!kutu) return;
  const b = document.getElementById("hepgoBilgiBaslik"), m = document.getElementById("hepgoBilgiMetin"), d = document.getElementById("hepgoBilgiDugme");
  if (b) b.textContent = baslik;
  if (m) m.textContent = metin;
  if (d){
    if (dugme){ d.textContent = dugme; d.style.display = ""; d.onclick = () => { if (typeof window.hepgoNav === "function") window.hepgoNav(hash || "#/field"); }; }
    else d.style.display = "none";
  }
  kutu.style.display = "";
}
// hepgo_patch.js dronGecmisAc: görünen sysid → envanter dron id (sipariş uçağında yok → null → dron listesi)
window.hepgoDronIdBul = function(g){
  const h = KOPRU_OF[Number(g)];
  const f = h ? ucusBul(h.bridge_id, h.sysid) : null;
  return (f && hwVar(f.drone_id)) ? f.drone_id : null;
};
function renkTablosu(){ return hwYerel("hepgo_ops_renk", {}) || {}; }

// ---------------- HEPGO state → GÖKTUNGU d ----------------
function hbYasSn(k){
  const s = k.state || {};
  if (s.last_hb === null || s.last_hb === undefined) return null;
  const ref = (typeof s.updated === "number") ? s.updated : s.last_hb;
  return Math.max(0, ref - s.last_hb) + (Date.now() - k.alindi) / 1000;
}
function hazirlikHesapla(s){
  if (s.ready && typeof s.ready === "object")
    return {hazir: s.ready.hazir, uyari: s.ready.uyari || 0, sebep: s.ready.sebep || null};
  if (s.armed) return {hazir: undefined, uyari: 0, sebep: null};
  const sensors = s.sensors || {};
  const bozuk = Object.keys(sensors).filter(k => sensors[k] === "fail");
  const prearm = Array.isArray(s.prearm) ? s.prearm : [];
  const hazir = prearm.length === 0 && bozuk.length === 0 && typeof s.fix === "number" && s.fix >= 3;
  return {hazir: hazir, uyari: bozuk.length, sebep: prearm[0] || (bozuk.length ? bozuk[0] : (!(s.fix >= 3) ? "GPS fix yok" : null))};
}
function dCevir(k){
  const s = k.state || {}, b = KOPRULER[String(k.bridge_id)];
  const yas = hbYasSn(k);
  const f = ucusBul(k.bridge_id, k.sysid);               // dron etiketi uçuştan: "<kuyruk no | dron kodu> · <ad>"
  const ad = f ? ucusEtiket(f) : null;
  const uid = hwUid(k.bridge_id, k.sysid);
  const renk = renkTablosu()[uid];
  return {
    sysid: k.gorunen, gercek_sysid: k.sysid,
    baglanti: !!(b && b.online) && yas !== null && yas < 5,
    armed: !!s.armed, mod: (s.mode === null || s.mode === undefined) ? "" : String(s.mode),
    arac_tipi: s.type, tip: s.type_name || "", otopilot: s.autopilot,
    isim: ad || s.type_name || ("SYS" + k.sysid), kullanici_isim: ad || undefined,
    // baglanti_id = Bağlantı Yöneticisi grubu (uçuş); eşlenemeyen dron seri.js "BAĞLANTISI BİLİNMEYEN" grubuna düşer
    uid: uid, dron_uid: uid, baglanti_id: f ? ucusGrupId(f) : "", kopru_adi: f ? ucusKopruAdi(f) : (b ? b.name : ""),
    lat: s.lat, lon: s.lon, alt_rel: s.alt_rel, alt_msl: s.alt, irtifa: s.alt_rel, alt: s.alt_rel,   // dron_ekran_disi.js:187 irtifa||alt okur
    heading: (s.hdg === null || s.hdg === undefined) ? s.yaw : s.hdg,
    groundspeed: s.groundspeed, airspeed: s.airspeed, vz: s.vz, roll: s.roll, pitch: s.pitch, gaz: s.throttle, tirmanis: s.climb,
    gps_fix: s.fix, uydu: s.sats, hdop: s.hdop, vdop: null, gps_alt: null, gps_hiz: null, gps_rota: null,
    batarya_v: s.volt, batarya_a: s.curr, batarya_pct: s.batt_pct,
    home_lat: s.home_lat, home_lon: s.home_lon, home_alt: s.home_alt,
    mission_seq: s.mission_seq, mission_count: s.mission_count, hedef_mesafe: s.wp_dist,
    ucus: s.flight_s, ucus_sn: s.flight_s, kat_mesafe: s.dist_m, rpm: s.rpm, yuk: s.alt_rel,
    hazirlik: hazirlikHesapla(s), sensorler: s.sensors, ekf_flags: s.ekf_flags, prearm: s.prearm,
    renk: renk || undefined, son: s.updated
  };
}

// ---------------- Telemetri birleştirici (200 ms) ----------------
function telemetriPaketiUret(){
  const dronlar = [], simdi = Date.now();
  for (const uid of Object.keys(DURUM)){
    const k = DURUM[uid];
    const yas = hbYasSn(k);
    const sessiz = (yas === null) ? (simdi - k.alindi) / 1000 : yas;
    if (sessiz > 10){ delete DURUM[uid]; continue; }   // 10 sn'dir kalp atışı yok: listeden düş → dronSil
    dronlar.push(dCevir(k));
  }
  gorevDurumTazele(dronlar);
  const renkler = {}, tablo = renkTablosu();
  for (const d of dronlar) if (tablo[d.uid]) renkler[String(d.sysid)] = tablo[d.uid];
  // baglanti_durumlari: uçuş grubu bazlı (seri.js baglantiDurumlariIsle yalnız değişince yeniden çizer)
  return {tip: "telemetri", dronlar: dronlar, dron_renkler: renkler, baglanti_durumlari: ucusDurumlari(),
          gorev_durum: GOREV, gorev_surdurulebilir: {}};
}
function telemetriDongu(){
  const m = telemetriPaketiUret();
  const bos = m.dronlar.length === 0;
  if (bos && sonPaketBos && !(typeof sonVeri !== "undefined" && Object.keys(sonVeri).length)) return;
  sonPaketBos = bos;
  telemetriIsle(m);
}

// ws.js:68-205'in kapsam içi dalları (radar/m50/kamera/angajman/sürü/takip/kalkan yok)
var _telHataGorulen = new Set();
function _guvenli(ad, fn){
  try { fn(); }
  catch (e){
    const imza = ad + "|" + (e && e.message ? e.message : String(e));
    if (!_telHataGorulen.has(imza)){
      _telHataGorulen.add(imza);
      console.error("[TELEMETRI] '" + ad + "' alt sistemi hata verdi; diğer alt sistemler etkilenmeden sürdü:", e);
    }
  }
}
function telemetriIsle(m){
  _guvenli("baglanti_durumlari", () => {
    if (m.baglanti_durumlari && typeof baglantiDurumlariIsle === "function") baglantiDurumlariIsle(m.baglanti_durumlari);
  });
  _guvenli("dron_renkler", () => { if (m.dron_renkler) window.dronRenkler = m.dron_renkler; });
  const gelenDronlar = m.dronlar || [];
  window.dronlarSon = gelenDronlar;
  if (typeof sonVeri === "undefined") return;
  _guvenli("dron_temizle", () => {
    if (gelenDronlar.length === 0 && Object.keys(sonVeri).length > 0 && typeof tumDronlariTemizle === "function") tumDronlariTemizle();
  });
  for (const d of gelenDronlar){
    _guvenli("dron_" + d.sysid, () => { sonVeri[d.sysid] = d; varlikGuncelle(d); });
  }
  _guvenli("dron_kaybolan", () => {
    if (typeof dronSil !== "function") return;
    const gelen = new Set(gelenDronlar.map(d => String(d.sysid)));
    for (const sysid of Object.keys(sonVeri)){
      if (gelen.has(String(sysid))) continue;
      delete sonVeri[sysid];
      try { dronSil(parseInt(sysid, 10)); } catch (e) {}
    }
    if (typeof dronKartlar === "object" && dronKartlar){
      for (const sysid of Object.keys(dronKartlar))
        if (!gelen.has(String(sysid))) { try { dronSil(parseInt(sysid, 10)); } catch (e) {} }
    }
  });
  _guvenli("dron_baglanti_eslem", () => {
    if (typeof window.dronBaglantiEslemGuncelle === "function") window.dronBaglantiEslemGuncelle(gelenDronlar);
  });
  _guvenli("gorev_telemetri", () => {
    if (typeof window.gorevTelemetriIsle === "function") window.gorevTelemetriIsle(m);
  });
}

// ---------------- Bağlantı Yöneticisi (seri.js) için uçuş listesi ----------------
// seri.js baglantiListesiIsle → bagListeCiz: her kayıt için .bag-grup[data-bag-grup=id] + .bag-grup-govde[data-bag-govde=id]
// (dron kartları dCevir baglanti_id ile buraya yerleşir). Alanlar: id, isim (bag-ad), tur (bagTurEtiket + bag-tur-<tur>),
// host/port (bagAltMetin), kopru_ornek_id. tur 'merkez' seçildi: bagAltMetin b.host'u aynen yazar (bagMerkezOzet yüklü değil);
// rozet metni/sınıfı ve durum metinleri bagListeCiz sarmalında HEPGO'ya göre yeniden yazılır.
function baglantiListesiYayinla(){
  const baglantilar = FLIGHTS.map(f => ({id: ucusGrupId(f), isim: ucusKopruAdi(f), tur: "merkez", host: linkOzet(f), port: "", kopru_ornek_id: null}));
  if (typeof baglantiListesiIsle === "function")
    try { baglantiListesiIsle({tip: "baglanti_listesi", baglantilar: baglantilar, durumlar: ucusDurumlari()}); } catch (e) { console.error(e); }
}
// seri.js:915 bagListeCiz function declaration → global nesne özelliği; sözcüksel çağrılar (baglantiListesiIsle,
// baglantiDurumlariIsle, bagDilTazele) atamadan sonra sarmalı görür. Satır şablonu değişmez; yalnız HEPGO alanları yazılır:
// uçuş rozeti, tür rozeti (SANAL/SERİ/TCP/UDP/KÖPRÜ), durum metni (KÖPRÜ YOK / ÇEVRİMDIŞI / BAĞLANTI YOK / HAZIR) ve
// Bağlan/Kes düğmesinin görünürlüğü (data-hepgo-ps; hepgo.css).
(function bagListeCizSarmala(){
  if (typeof window.bagListeCiz !== "function" || window.bagListeCiz.__hepgoSarmal) return;
  const orijinal = window.bagListeCiz;
  function duzenle(){
    document.querySelectorAll("#bagListe .bag-grup[data-bag-grup]").forEach(grup => {
      const f = ucusGrupBul(grup.dataset.bagGrup);
      if (!f) return;
      const satir = grup.querySelector(":scope > .bag-satir");
      if (!satir) return;
      const s = ucusDurumu(f), online = ucusKopruOnline(f), sanal = f.protocol === "sanal";
      const link = (f.link && f.link.type) ? String(f.link.type).toLowerCase() : null;
      const ad = satir.querySelector(".bag-ad");
      if (ad && !satir.querySelector(".hepgo-ucus-rozet")){
        const r = document.createElement("span");
        r.className = "hepgo-ucus-rozet"; r.textContent = f.label || ("#" + f.id); r.title = ucusEtiket(f);
        ad.insertAdjacentElement("afterend", r);
      }
      const tur = satir.querySelector(".bag-tur");
      if (tur){
        const kod = sanal ? "sanal" : (link === "serial" ? "seri" : (link === "tcp" || link === "udp") ? link : "kopru");
        tur.className = "bag-tur bag-tur-" + kod;
        tur.textContent = kod === "sanal" ? "SANAL" : kod === "seri" ? "SERİ" : kod === "kopru" ? hwT("KÖPRÜ", "BRIDGE") : kod.toUpperCase();
      }
      const durum = satir.querySelector(".bag-durum");
      if (durum && s.durum === "kapali"){
        if (!sanal && !hwVar(f.bridge_id)) durum.textContent = hwT("KÖPRÜ YOK", "NO BRIDGE");
        else if (!online){
          durum.textContent = hwT("ÇEVRİMDIŞI", "OFFLINE"); durum.className = "bag-durum bd-hata";
          durum.title = hwT("Köprü sunucuya bağlı değil", "Bridge is not connected to the server");
        }
        else if (!sanal && !link) durum.textContent = hwT("BAĞLANTI YOK", "NO LINK");
        else durum.textContent = hwT("HAZIR", "READY");
      }
      const gizli = sanal || !online || !link;
      satir.dataset.hepgoPs = gizli ? "gizli" : "";
      const ps = satir.querySelector(".bag-btn.bag-play, .bag-btn.bag-stop, .bag-btn.bag-baglaniyor");
      if (ps && !gizli){
        ps.title = ps.classList.contains("bag-play")
          ? hwT("Bağlan: bağlantıyı köprüde aç (link_open)", "Connect: open the link on the bridge (link_open)")
          : hwT("Kes: bağlantıyı köprüde kapat (link_close)", "Disconnect: close the link on the bridge (link_close)");
      }
    });
  }
  function sarili(){
    const sonuc = orijinal.apply(this, arguments);
    try { duzenle(); } catch (e) { console.error("[HEPGO WS] bagListeCiz düzenlemesi", e); }
    return sonuc;
  }
  sarili.__hepgoSarmal = true; sarili.__orijinal = orijinal;
  window.bagListeCiz = sarili;
})();
function kopruKaydet(info, online){
  const bid = String(info.bridge_id);
  const eski = KOPRULER[bid];
  KOPRULER[bid] = {bridge_id: Number(info.bridge_id), name: info.name || (eski && eski.name) || ("Köprü " + bid),
                   host: info.host || (eski && eski.host) || "", platform: info.platform || (eski && eski.platform) || "",
                   bridge_ver: info.bridge_ver || (eski && eski.bridge_ver) || "", online: !!online,
                   sira: eski ? eski.sira : ++KOPRU_SIRA_SAYAC};
  const dronlar = info.drones || {};
  for (const sid of Object.keys(dronlar)) durumYukle(info.bridge_id, Number(sid), dronlar[sid]);
}
function durumYukle(bridgeId, sysid, state){
  const uid = hwUid(bridgeId, sysid);
  const g = gorunenSysid(bridgeId, sysid);
  DURUM[uid] = {bridge_id: Number(bridgeId), sysid: Number(sysid), gorunen: g, state: state || {}, alindi: Date.now()};
}
function kopruDurumlariniSil(bridgeId){
  for (const uid of Object.keys(DURUM)) if (uid.indexOf(String(bridgeId) + ":") === 0) delete DURUM[uid];
}

// ---------------- Dron kartı konsolu (yerel tampon) ----------------
function yerelKonsolSatir(g, satir){
  const liste = KONSOL_TAMPON[g] = KONSOL_TAMPON[g] || [];
  const son = liste[liste.length - 1];
  if (son && son.etiket === satir.etiket && son.metin === satir.metin){
    son.tekrar = (son.tekrar || 1) + 1; son.ts = satir.ts;
    satir = Object.assign({}, son, {yeni: false});
  } else {
    satir.tekrar = 1;
    liste.push(satir);
    while (liste.length > 200) liste.shift();
  }
  if (typeof window.dronKonsolSatir === "function") try { window.dronKonsolSatir({sysid: g, satir: satir}); } catch (e) {}
}
function mesajTamponEkle(g, text, severity, ts){
  const liste = MESAJ_TAMPON[g] = MESAJ_TAMPON[g] || [];
  const son = liste[liste.length - 1];
  if (son && son.metin === text && son.sev === severity){ son.tekrar++; son.ts = ts; }
  else { liste.push({ts: ts, metin: text, sev: severity, tekrar: 1}); while (liste.length > 50) liste.shift(); }
}

// ---------------- Gerçek soketten gelen mesajlar ----------------
function helloIsle(m){
  const me = m.me || {};
  window.HEPGO_YETKI = !!me.can_command;
  const rol = me.can_command ? "pilot" : "izleyici";
  if (typeof oturum !== "undefined" && oturum && typeof oturum === "object"){
    oturum.rol = rol; oturum.ad = me.name || ""; oturum.id = (me.id === undefined) ? null : me.id; oturum.can_command = !!me.can_command;
  } else window.oturum = {rol: rol, ad: me.name || "", id: (me.id === undefined) ? null : me.id, can_command: !!me.can_command};
  try { document.documentElement.dataset.hepgoRol = rol; } catch (e) {}   // hepgo.css izleyici kancası: komut düğmeleri soluk
  if (typeof window.oturumYoneticiMi !== "function") window.oturumYoneticiMi = function(){ return false; };
  // Yetenek bayrakları: sunucu caps (hello) + çevrimiçi köprülerin caps'i (v1.1; köprü auth çerçevesinde bildirir)
  SUNUCU_CAPS = Array.isArray(m.caps) ? m.caps.slice() : [];
  // Görev bağlamı: watch{task_id} yanıtı task + flights taşır (sunucudaki en güncel uçuş/köprü/link bilgisi)
  if (m.task && typeof m.task === "object") gorevBilgiAyarla(m.task);
  if (Array.isArray(m.flights)) ucuslariAyarla(m.flights);
  // Köprüler: hello'da olmayanlar çevrimdışı sayılır, dron durumları yeniden kurulur. Görev dışı köprüler düşürülür
  // (auth sonrası ilk hello watch'tan önce gelir ve filtresiz olabilir).
  for (const bid of Object.keys(KOPRULER)) KOPRULER[bid].online = false;
  const bridges = (Array.isArray(m.bridges) ? m.bridges : []).filter(b => gorevKoprusuMu(b.bridge_id));
  const canli = new Set(bridges.map(b => String(b.bridge_id)));
  for (const uid of Object.keys(DURUM)) if (!canli.has(uid.split(":")[0])) delete DURUM[uid];
  for (const b of bridges){ kopruKaydet(b, true); if (Array.isArray(b.caps) && KOPRULER[String(b.bridge_id)]) KOPRULER[String(b.bridge_id)].caps = b.caps.slice(); }
  capsUygula();
  baglantiListesiYayinla();
  if (ilkHello){
    ilkHello = false;
    if (typeof window.yuzenPanelAc === "function") try { window.yuzenPanelAc("yzSeri"); } catch (e) {}
    if (typeof window.hepgoYzSeriKonumla === "function") try { window.hepgoYzSeriKonumla(); } catch (e) {}
    hwKonsol("HEPGO", hwT("Canlı uçuş sunucusuna bağlandı", "Connected to live flight server") + (me.name ? " · " + me.name : "") +
             (me.can_command ? "" : " · " + hwT("izleyici (komut yetkisi yok)", "viewer (no command permission)")), "basari");
  }
}
function statusIsle(m){
  if (m.bridge_id === undefined || m.sysid === undefined) return;
  if (!KOPRULER[String(m.bridge_id)]){ kopruKaydet({bridge_id: m.bridge_id}, true); baglantiListesiYayinla(); }
  durumYukle(m.bridge_id, m.sysid, m.state);
}
var SUNUCU_CAPS = [];   // hello.caps (sunucu + o an bağlı köprüler)
function capsUygula(){
  const birlesik = new Set(SUNUCU_CAPS);
  for (const bid of Object.keys(KOPRULER)) if (KOPRULER[bid].online) (KOPRULER[bid].caps || []).forEach(c => birlesik.add(c));
  const yeni = {};
  for (const anahtar of Object.keys(HEPGO_CAPS_ESLEM)){
    const bayrak = HEPGO_CAPS_ESLEM[anahtar];
    yeni[bayrak] = !!yeni[bayrak] || birlesik.has(anahtar);
  }
  Object.assign(window.HEPGO_OZ, yeni);
}
function bridgeIsle(m){
  const bid = String(m.bridge_id);
  if (m.online){
    kopruKaydet(m.info || {bridge_id: m.bridge_id}, true);
    if (m.info && Array.isArray(m.info.caps) && KOPRULER[bid]) KOPRULER[bid].caps = m.info.caps.slice();
    hwKonsol("KÖPRÜ", (KOPRULER[bid].name) + " " + hwT("bağlandı", "connected"), "basari");
  } else {
    if (KOPRULER[bid]) KOPRULER[bid].online = false;
    kopruDurumlariniSil(bid);
    hwKonsol("KÖPRÜ", ((KOPRULER[bid] || {}).name || ("Köprü " + bid)) + " " + hwT("ayrıldı", "disconnected") + (m.status ? " (" + m.status + ")" : ""), "uyari");
  }
  capsUygula();   // köprü gelince/giderken v1.1 düğmeleri (HOME Ayarla, Parametreler…) açılır/kapanır
  baglantiListesiYayinla();
}
function eventIsle(m){
  if (m.sysid === null || m.sysid === undefined) return;
  const g = gorunenSysid(m.bridge_id, m.sysid);
  const text = String(m.text || ""), sev = hwSev(m.severity);
  const ts = (typeof m.ts === "number") ? m.ts : Date.now() / 1000;
  if (!window.HEPGO_OZ.konsol_sunucu) yerelKonsolSatir(g, {ts: ts, etiket: "STATUSTEXT", metin: text, sev: sev});
  hwKonsol("D" + g, text, sev);
  if (Number(m.severity) <= 3) hwToast(text, "hata", "D" + g);
  mesajTamponEkle(g, text, Number(m.severity), ts);
  if (Number(m.severity) <= 4){
    UYARI_TAMPON.push({mesaj: "D" + g + ": " + text, ts: ts, okundu: false});
    while (UYARI_TAMPON.length > 100) UYARI_TAMPON.shift();
  }
}
function consoleIsle(m){
  if (m.sysid === null || m.sysid === undefined) return;
  const g = gorunenSysid(m.bridge_id, m.sysid);
  if (typeof window.dronKonsolSatir === "function")
    try { window.dronKonsolSatir({sysid: g, satir: {ts: m.ts, etiket: m.tag, metin: m.text, sev: m.sev, tekrar: m.repeat, yeni: m.fresh}}); } catch (e) {}
}
function consoleHistIsle(m){
  const g = (m.bridge_id !== undefined && m.sysid !== null && m.sysid !== undefined) ? gorunenSysid(m.bridge_id, m.sysid) : Number(m.sysid);
  const satirlar = (m.lines || []).map(l => ({ts: l.ts, etiket: l.tag, metin: l.text, sev: l.sev, tekrar: l.repeat}));
  if (typeof window.dronKonsolGecmis === "function") try { window.dronKonsolGecmis({sysid: g, satirlar: satirlar}); } catch (e) {}
}
function paramIsle(m){   // sunucu param desteği geldiğinde: {t:'param', bridge_id, sysid, name, value, index, count}
  const g = gorunenSysid(m.bridge_id, m.sysid);
  const ob = PARAM_ONBELLEK[g] = PARAM_ONBELLEK[g] || {};
  if (m.name) ob[m.name] = m.value;
  const alinan = (typeof m.index === "number") ? m.index + 1 : Object.keys(ob).length, toplam = m.count || 0;
  if (typeof dkParamIlerleme === "function") try { dkParamIlerleme(g, alinan, toplam); } catch (e) {}
  if (toplam && alinan >= toplam) paramListesiYayinla(g, ob, "dron", Date.now() / 1000);
}
function paramsIsle(m){   // sunucu toplu PARAM_VALUE paketi (200 ms): items [[name, value, index, count, type]…]
  const g = gorunenSysid(m.bridge_id, m.sysid);
  const ob = PARAM_ONBELLEK[g] = PARAM_ONBELLEK[g] || {};
  let son = null;
  for (const it of (m.items || [])){ if (it && it[0]){ ob[it[0]] = it[1]; son = it; } }
  const toplam = (son && son[3]) || m.count || 0, alinan = Object.keys(ob).length;
  if (typeof dkParamIlerleme === "function") try { dkParamIlerleme(g, alinan, toplam); } catch (e) {}
  if (toplam && alinan >= toplam) paramListesiYayinla(g, ob, "dron", Date.now() / 1000);
}
function paramCacheIsle(m){   // sunucudaki PARAM_VALUE önbelleği: {name: [value, index, count, type]}
  const g = gorunenSysid(m.bridge_id, m.sysid);
  const ob = PARAM_ONBELLEK[g] = PARAM_ONBELLEK[g] || {};
  const p = m.params || {};
  Object.keys(p).forEach(k => { ob[k] = Array.isArray(p[k]) ? p[k][0] : p[k]; });
  paramListesiYayinla(g, ob, Object.keys(ob).length ? "cache" : "", null);
}
function paramListesiYayinla(g, parametreler, kaynak, okumaTs, hata){
  const p = parametreler || {};
  if (typeof dkParamListesiGeldi === "function") try { dkParamListesiGeldi(g, p, hata || null, kaynak || "", okumaTs || 0); } catch (e) {}
  if (typeof window.dkFailsafeParamGeldi === "function") try { window.dkFailsafeParamGeldi(g, p); } catch (e) {}
  if (typeof window.dronAyarParamGeldi === "function") try { window.dronAyarParamGeldi(g, p); } catch (e) {}
}
function logIsle(m){
  const metin = hwT("Uçuş logu alındı: ", "Flight log received: ") + (m.name || ("#" + m.flight_log_id));
  hwKonsol("LOG", metin, "basari");
  hwToast(metin, "basari", "LOG");
}

function resIsle(m){
  const b = BEKLEYEN[m.rid];
  if (!b) return;
  clearTimeout(b.timer);
  delete BEKLEYEN[m.rid];
  const ok = !!m.ok, hata = m.error || "";
  const kim = (b.ekler && b.ekler.etiket) ? b.ekler.etiket : ("D" + b.sysid);   // link_open/link_close: dron henüz yok, uçuş etiketi
  if (b.tip !== "arm_check"){
    if (ok){
      if (!window.HEPGO_OZ.konsol_sunucu) yerelKonsolSatir(b.sysid, {ts: Date.now() / 1000, etiket: "KOMUT", metin: b.name + ": " + hwT("kabul edildi", "accepted"), sev: "basari"});
      hwKonsol("KOMUT", kim + " " + b.name + ": " + hwT("kabul edildi", "accepted"), "basari");
    } else {
      if (!window.HEPGO_OZ.konsol_sunucu) yerelKonsolSatir(b.sysid, {ts: Date.now() / 1000, etiket: "KOMUT", metin: b.name + ": " + hata, sev: "hata"});
      hwKonsol("KOMUT", kim + " " + b.name + ": " + hata, "hata");
      // gorev_* hatalarını gorev.js kendi bildirimiyle gösterir (gorevKomutSonucIsle); burada ikinci toast üretilmez
      if (!/^gorev_/.test(b.tip) && b.tip !== "set_home") hwToast(kim + " " + b.name + ": " + hata, "hata", "KOMUT");   // set_home kendi toast'ını verir
    }
  }
  const t = (typeof D === "function") ? D() : {};
  switch (b.tip){
    case "arm_check": {
      const r = (ok && m.result && typeof m.result === "object") ? m.result : {bulundu: false};
      const rapor = armRaporNormalize(Object.assign({tip: "arm_check_rapor"}, r, {sysid: b.sysid}));
      if (!Array.isArray(rapor.mesajlar)) rapor.mesajlar = MESAJ_TAMPON[b.sysid] || [];
      if (typeof window.dkArmCheckRaporGeldi === "function") try { window.dkArmCheckRaporGeldi(rapor); } catch (e) {}
      break;
    }
    case "set_home": {
      const mevcut = !(b.params && typeof b.params.lat === "number");
      const metin = ok
        ? ("D" + b.sysid + " " + (mevcut ? (t.homeSonucMevcut || "HOME aracın mevcut konumuna ayarlandı") : (t.homeSonucKonum || "HOME seçilen konuma ayarlandı")))
        : ("D" + b.sysid + " " + (t.homeSonucHata || "HOME ayarlanamadı") + (hata ? ": " + hata : ""));
      hwToast(metin, ok ? "basari" : "hata", "komut");
      break;
    }
    case "param_set":
      if (typeof dkParamYazildi === "function") try { dkParamYazildi(b.sysid, b.ekler.ad, b.ekler.deger, ok); } catch (e) {}
      if (typeof window.dkFailsafeParamYazildi === "function") try { window.dkFailsafeParamYazildi(b.sysid, b.ekler.ad, b.ekler.deger, ok); } catch (e) {}
      if (ok){ (PARAM_ONBELLEK[b.sysid] = PARAM_ONBELLEK[b.sysid] || {})[b.ekler.ad] = b.ekler.deger; }
      break;
    case "param_list":
      if (!ok) paramListesiYayinla(b.sysid, PARAM_ONBELLEK[b.sysid] || {}, "cache", null, hata);
      break;
    case "gorev_yukle": case "gorev_baslat": case "gorev_durdur": case "gorev_devam": case "gorev_surdur": {
      const g = GOREV[b.sysid];
      if (g){
        if (ok){
          if (b.tip === "gorev_yukle"){ g.asama = "yuklendi"; g.yuklenen_oge = g.toplam_oge; g.yuzde = 100; }
        } else if (b.ekler && b.ekler.oncekiAsama !== undefined){
          g.asama = (b.tip === "gorev_yukle") ? "hata" : b.ekler.oncekiAsama;
        }
      }
      if (typeof window.gorevKomutSonucIsle === "function")
        try { window.gorevKomutSonucIsle({tip: b.tip + "_sonuc", sysid: b.sysid, basari: ok, hata: ok ? undefined : hata}); } catch (e) {}
      break;
    }
    case "gorev_iptal": {
      const rotaId = GOREV[b.sysid] ? GOREV[b.sysid].rota_id : null;
      if (ok){ delete GOREV[b.sysid]; rotaGorevdenDus(rotaId); }
      else if (GOREV[b.sysid] && b.ekler) GOREV[b.sysid].asama = b.ekler.oncekiAsama;
      if (typeof window.gorevIptalSonucIsle === "function") try { window.gorevIptalSonucIsle({sysid: b.sysid, basari: ok}); } catch (e) {}
      break;
    }
    case "link_open":   // Bağlantı Yöneticisi "Bağlan": köprü link'i açtı → telemetri gelince durum 'bagli' olur
      if (b.ekler && hwVar(b.ekler.flight_id)){
        if (ok){ LINK_DURUM[b.ekler.flight_id] = "acik"; LINK_ZAMAN[b.ekler.flight_id] = Date.now(); }
        else { delete LINK_DURUM[b.ekler.flight_id]; delete LINK_ZAMAN[b.ekler.flight_id]; }
        baglantiListesiYayinla();
      }
      if (ok) hwToast(kim + ": " + hwT("bağlantı köprüde açıldı", "link opened on the bridge"), "basari", "KÖPRÜ");
      break;
    case "link_close":
      if (b.ekler && hwVar(b.ekler.flight_id)){ delete LINK_DURUM[b.ekler.flight_id]; delete LINK_ZAMAN[b.ekler.flight_id]; baglantiListesiYayinla(); }
      if (ok) hwToast(kim + ": " + hwT("bağlantı kapatıldı", "link closed"), "bilgi", "KÖPRÜ");
      break;
    default: break;
  }
}
function bekleyenleriDusur(sebep){
  for (const rid of Object.keys(BEKLEYEN)) resIsle({rid: rid, ok: false, error: sebep});
}

function mesajIsle(m){
  // Görev dışı köprü (sunucu filtresi watch'tan önce devrede olmayabilir; res/hello köprüye bağlı değil)
  if (m.t !== "hello" && m.t !== "res" && hwVar(m.bridge_id) && !gorevKoprusuMu(m.bridge_id)) return;
  switch (m.t){
    case "hello": helloIsle(m); break;
    case "status": statusIsle(m); break;
    case "bridge": bridgeIsle(m); break;
    case "event": eventIsle(m); break;
    case "res": resIsle(m); break;
    case "console": consoleIsle(m); break;
    case "console_hist": consoleHistIsle(m); break;
    case "param": paramIsle(m); break;
    case "params": paramsIsle(m); break;
    case "param_cache": paramCacheIsle(m); break;
    case "log": logIsle(m); break;
    case "pong": break;
    case "error":
      if (m.error === "auth"){ yetkiYok = true; durumYaz("yetki"); }
      else hwToast(String(m.error || "Sunucu hatası"), "hata", "HEPGO");
      break;
    default: console.debug("[HEPGO WS] bilinmeyen mesaj", m.t); break;
  }
}

// ---------------- Gerçek soket ----------------
function durumYaz(durum){
  if (!wsDurum) return;
  const t = (typeof D === "function") ? D() : {};
  if (durum === "bagli"){ wsDurum.textContent = hwT("WS: bağlı", "WS: connected"); wsDurum.className = "f-iyi"; }
  else if (durum === "yetki"){ wsDurum.textContent = hwT("WS: yetki yok", "WS: not authorized"); wsDurum.className = "f-kotu"; }
  else if (durum === "gorevsiz"){ wsDurum.textContent = hwT("WS: görev bağlamı yok", "WS: no task context"); wsDurum.className = "f-uyari"; }
  else { wsDurum.textContent = t.wsKoptu || hwT("WS: koptu, tekrar deneniyor...", "WS: disconnected, retrying..."); wsDurum.className = "f-kotu"; }
}
function gercekWsAcik(){ return !!(gercekWs && gercekWs.readyState === 1); }
function yenidenPlanla(){
  if (yetkiYok || yenidenZaman) return;
  yenidenZaman = setTimeout(() => { yenidenZaman = null; wsBaglan(); }, 3000);
}
function wsBaglan(){
  if (yetkiYok) return;
  const url = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/drone/live";
  let s;
  try { s = new WebSocket(url); }
  catch (e){ durumYaz("koptu"); yenidenPlanla(); return; }
  gercekWs = s;
  s.onopen = () => {
    durumYaz("bagli");
    // İzleyici görevle sınırlanır: sunucu hello{task, flights, bridges} ile yanıtlar ve görevin sanal dronlarını başlatır
    if (GOREV_ID) try { s.send(JSON.stringify({t: "watch", task_id: GOREV_ID})); } catch (e) {}
    if (pingZaman) clearInterval(pingZaman);
    pingZaman = setInterval(() => { if (gercekWsAcik()) gercekWs.send(JSON.stringify({t: "ping"})); }, 20000);
  };
  s.onclose = (ev) => {
    if (pingZaman){ clearInterval(pingZaman); pingZaman = null; }
    if (gercekWs === s) gercekWs = null;
    bekleyenleriDusur(hwT("Sunucu bağlantısı koptu", "Server connection lost"));
    for (const bid of Object.keys(KOPRULER)) KOPRULER[bid].online = false;
    DURUM = {}; LINK_DURUM = {}; LINK_ZAMAN = {};
    baglantiListesiYayinla();
    if (ev && ev.code === 4403){ yetkiYok = true; durumYaz("yetki"); hwToast(hwT("Canlı Uçuş izleme yetkiniz yok", "No permission to view live flight"), "hata", "HEPGO"); return; }
    durumYaz("koptu");
    yenidenPlanla();
  };
  s.onerror = () => { try { s.close(); } catch (e) {} };
  s.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    try { mesajIsle(m); } catch (e) { console.error("[HEPGO WS] mesaj işlenemedi", m && m.t, e); }
  };
}

// ---------------- Komut gönderimi (tarayıcı → sunucu → köprü) ----------------
function cmdGonder(g, name, params, tip, ekler){
  const hedef = KOPRU_OF[g];
  if (!hedef){ hwToast(hwT("D" + g + " için köprü bulunamadı", "No bridge for D" + g), "hata", "KOMUT"); return null; }
  return cmdKopruye(hedef.bridge_id, hedef.sysid, g, name, params, tip, ekler);
}
function cmdKopruye(bridgeId, sysid, g, name, params, tip, ekler){
  if (!gercekWsAcik()){ hwToast(hwT("Sunucu bağlantısı yok", "No server connection"), "hata", "KOMUT"); return null; }
  if (!window.HEPGO_YETKI && name !== "arm_check"){
    hwToast(hwT("Komut yetkiniz yok (Canlı Uçuş yazma izni ve Pilot/Admin rolü gerekir)", "No command permission (write access and Pilot/Admin role required)"), "hata", "KOMUT");
    return null;
  }
  const rid = "h" + (++ridSayac) + "-" + Date.now().toString(36);
  const kayit = {tip: tip || name, sysid: g, gercek: Number(sysid), bridge_id: Number(bridgeId), name: name, params: params || {}, ekler: ekler || {}, zaman: Date.now()};
  // sunucu zaman aşımının (10 sn; mission_upload/mission_download/log_list 60 sn) üstünde: sunucunun hata metni önce gelsin
  const zamanAsimiSn = (name === "mission_upload" || name === "mission_download" || name === "log_list") ? 65 : 12;
  kayit.timer = setTimeout(() => resIsle({rid: rid, ok: false, error: hwT("yanıt alınamadı (" + zamanAsimiSn + " sn zaman aşımı)", "no response (" + zamanAsimiSn + " s timeout)")}), zamanAsimiSn * 1000);
  BEKLEYEN[rid] = kayit;
  gercekWs.send(JSON.stringify({t: "cmd", rid: rid, bridge_id: Number(bridgeId), sysid: Number(sysid), name: name, params: params || {}}));
  if (name !== "arm_check"){
    const ptxt = JSON.stringify(params || {});
    if (!window.HEPGO_OZ.konsol_sunucu) yerelKonsolSatir(g, {ts: Date.now() / 1000, etiket: "KOMUT", metin: name + (ptxt !== "{}" ? " " + ptxt : ""), sev: "bilgi"});
  }
  return rid;
}
function dronVeri(g){ return (typeof sonVeri !== "undefined" && sonVeri[g]) || null; }
function modAdi(g, no){   // DK_MODLAR (dronlar.js:3587) ters eşlemesi; kategori dkModListesi mantığı
  const d = dronVeri(g) || {};
  const tipNo = Number(d.arac_tipi || 0);
  const kat = (tipNo === 1 || (tipNo >= 19 && tipNo <= 25)) ? "plane" : (tipNo === 4 ? "heli" : "kopter");
  const liste = (typeof DK_MODLAR !== "undefined" && DK_MODLAR[kat]) ? DK_MODLAR[kat] : [];
  const e = liste.find(x => Number(x[0]) === Number(no));
  return e ? e[1] : null;
}
function desteklenmiyor(ne){
  hwToast(hwT(ne + ": sunucu/köprü bu komutu henüz desteklemiyor", ne + ": not supported by server/bridge yet"), "uyari", "KOMUT");
}

// {tip:'dron_komut', sysid, aksiyon, …} → HEPGO komutu
function dronKomutCevir(m){
  const g = Number(m.sysid), d = dronVeri(g) || {};
  switch (m.aksiyon){
    case "arm": return cmdGonder(g, "arm", {});
    case "arm_zorla":
      if (window.HEPGO_OZ.arm_zorla) return cmdGonder(g, "arm", {force: true});
      return desteklenmiyor(hwT("Zorla arm", "Force arm"));
    case "disarm": return cmdGonder(g, "disarm", {});
    case "takeoff": return cmdGonder(g, "takeoff", {alt_rel_m: Number(m.irtifa) || 10});
    case "land": return cmdGonder(g, "land", {});
    case "rtl": return cmdGonder(g, "rtl", {});
    case "set_mode": {
      const ad = modAdi(g, m.irtifa);
      if (!ad) return hwToast(hwT("Mod numarası çevrilemedi: " + m.irtifa, "Unknown mode number: " + m.irtifa), "hata", "KOMUT");
      return cmdGonder(g, "set_mode", {mode: ad});
    }
    case "altitude_change": {
      const hedef = Number(m.irtifa);
      if (window.HEPGO_OZ.altitude_change) return cmdGonder(g, "altitude_change", {alt_rel_m: hedef});
      if (String(d.mod || "").toUpperCase() !== "GUIDED")
        return hwToast(hwT("İrtifa değişikliği için aracı önce GUIDED moda alın", "Switch to GUIDED mode before changing altitude"), "uyari", "KOMUT");
      if (!window.gecerliKonumMu || !window.gecerliKonumMu(d.lat, d.lon))
        return hwToast(hwT("Aracın konumu bilinmiyor", "Vehicle position unknown"), "uyari", "KOMUT");
      return cmdGonder(g, "goto", {lat: d.lat, lon: d.lon, alt_rel_m: hedef});
    }
    case "goto":
      return cmdGonder(g, "goto", {lat: Number(m.lat), lon: Number(m.lon), alt_rel_m: Math.max(10, Number(d.alt_rel) || 50)});
    case "set_home": {
      if (!window.HEPGO_OZ.set_home) return desteklenmiyor(hwT("HOME ayarla", "Set HOME"));
      const p = (typeof m.lat === "number" && typeof m.lon === "number") ? {lat: m.lat, lon: m.lon} : {};
      return cmdGonder(g, "set_home", p, "set_home");
    }
    case "param": {   // hız karosu (m/s → cm/s; WPNAV_SPEED*, RTL_ALT cm)
      if (!window.HEPGO_OZ.param) return desteklenmiyor(hwT("Parametre yazma", "Parameter write"));
      const deger = Math.round(Number(m.deger) * 100);
      return cmdGonder(g, "param_set", {name: m.ad, value: deger}, "param_set", {ad: m.ad, deger: deger});
    }
    default:
      console.debug("[HEPGO WS] kapsam dışı dron_komut", m.aksiyon);
      return null;
  }
}

// ---------------- ARM CHECK (istemci raporu; sunucu desteği yoksa) ----------------
function armCheckIstemci(g){
  const d = dronVeri(g);
  if (!d){
    if (typeof window.dkArmCheckRaporGeldi === "function") window.dkArmCheckRaporGeldi({tip: "arm_check_rapor", sysid: g, bulundu: false});
    return;
  }
  const maddeler = [];
  (Array.isArray(d.prearm) ? d.prearm : []).forEach(m => maddeler.push({grup: "prearm", ad: m, durum: "hata", aciklama: "PreArm", oncelik: 1}));
  const sensorler = d.sensorler || {};
  Object.keys(sensorler).forEach(k => maddeler.push({grup: "sensor", ad: k, durum: sensorler[k] === "ok" ? "tamam" : "hata", aciklama: "SYS_STATUS", oncelik: 2}));
  const fix = d.gps_fix;
  maddeler.push({grup: "konum", ad: "GPS fix", durum: (fix === null || fix === undefined) ? "bilinmiyor" : fix >= 3 ? "tamam" : fix === 2 ? "uyari" : "hata",
                 deger: "fix " + (fix === null || fix === undefined ? "?" : fix) + " · " + (d.uydu === null || d.uydu === undefined ? "?" : d.uydu) + " uydu", oncelik: 1});
  if (typeof d.hdop === "number" && d.hdop > 2) maddeler.push({grup: "konum", ad: "HDOP", durum: "uyari", deger: String(d.hdop), oncelik: 3});
  maddeler.push({grup: "konum", ad: "HOME", durum: (d.home_lat !== null && d.home_lat !== undefined) ? "tamam" : "uyari",
                 mesaj: (d.home_lat !== null && d.home_lat !== undefined) ? "" : "HOME_POSITION gelmedi", oncelik: 0});
  const pct = d.batarya_pct;
  maddeler.push({grup: "guc", ad: "Batarya", durum: (d.batarya_v === null || d.batarya_v === undefined) ? "bilinmiyor" : (typeof pct === "number" && pct < 20) ? "hata" : (typeof pct === "number" && pct < 40) ? "uyari" : "tamam",
                 deger: (d.batarya_v !== null && d.batarya_v !== undefined ? d.batarya_v + " V" : "") + (typeof pct === "number" ? " · %" + pct : ""), oncelik: 1});
  maddeler.push({grup: "sensor", ad: "Kalp atışı", durum: d.baglanti ? "tamam" : "hata", deger: d.baglanti ? "Telemetri canlı" : "Kalp atışı yok", oncelik: 0});
  const kritik = maddeler.filter(x => x.durum === "hata").length, uyari = maddeler.filter(x => x.durum === "uyari").length;
  const ilkHata = maddeler.find(x => x.durum === "hata") || maddeler.find(x => x.durum === "uyari");
  if (typeof window.dkArmCheckRaporGeldi === "function")
    window.dkArmCheckRaporGeldi(armRaporNormalize({tip: "arm_check_rapor", sysid: g, bulundu: true, armed: !!d.armed, mod: d.mod,
      ozet: {hazir: kritik === 0, uyari: uyari, kritik: kritik, sebep: ilkHata ? ilkHata.ad : null},
      maddeler: maddeler, parametreler: [], mesajlar: MESAJ_TAMPON[g] || []}));
}

// ---------------- Görev (gorev.js) ↔ mission_upload / set_mode ----------------
function gorevDurumTazele(dronlar){
  for (const d of dronlar){
    const g = GOREV[d.sysid];
    if (!g) continue;
    if (g.asama === "gorevde" || g.asama === "duraklatildi"){
      if (d.armed) g.ucustu = true;
      if (typeof d.mission_seq === "number"){
        g.en_yuksek_seq = Math.max(g.en_yuksek_seq || 0, d.mission_seq);
        const sonSeq = Math.max(1, (g.toplam_oge || 1) - 1);
        g.gorev_yuzde = Math.min(99, Math.round(100 * g.en_yuksek_seq / sonSeq));
      }
      if (g.ucustu && !d.armed){ g.asama = "tamamlandi"; g.gorev_yuzde = 100; rotaGorevdenDus(g.rota_id); }
    }
  }
}
// Görev bitti/iptal: rota başka bir dronun açık görevinde değilse haritadan düşer (kullanıcı kararı 4)
function rotaGorevdenDus(rotaId){
  if (!hwVar(rotaId) || !ROTA_GORUNUR[String(rotaId)]) return;
  const kullanimda = Object.keys(GOREV).some(s => GOREV[s] && GOREV[s].rota_id === rotaId && GOREV[s].asama !== "tamamlandi" && GOREV[s].asama !== "iptal");
  if (kullanimda) return;
  rotaGorunurAyarla(rotaId, false);
  rotaListesiYayinla();
}
function gorevAsamaGec(g, yeniAsama){
  const kayit = GOREV[g];
  if (!kayit) return undefined;
  const onceki = kayit.asama;
  kayit.asama = yeniAsama;
  return onceki;
}
async function gorevYukle(m){
  const g = Number(m.sysid), rotaId = Number(m.rota_id);
  const rota = ROTALAR.find(r => r.id === rotaId);
  GOREV[g] = {rota_id: rotaId, rota_isim: rota ? rota.isim : ("#" + rotaId), asama: "yukleniyor", toplam_nokta: rota ? (rota.noktalar || []).length : 0,
              toplam_oge: 0, yuklenen_oge: 0, yuzde: 0, wp_harita: {}, durdurma_davranisi: m.durdurma_davranisi || "bekle", en_yuksek_seq: 0, gorev_yuzde: 0};
  rotaGorunurAyarla(rotaId, true);   // göreve yüklenen rota haritada çizilir (tek görünür rota kuralı)
  rotaListesiYayinla();
  let gorev;
  try { gorev = await hwFetch("/api/drone/routes/" + rotaId + "/mission"); }
  catch (e){
    GOREV[g].asama = "hata";
    if (typeof window.gorevKomutSonucIsle === "function") window.gorevKomutSonucIsle({tip: "gorev_yukle_sonuc", sysid: g, basari: false, hata: e.message});
    return;
  }
  const items = gorev.items || [];
  const wp = {}; let no = 0;
  items.forEach(it => { if ([16, 19, 20, 21, 22].indexOf(Number(it.command)) >= 0){ no++; wp[String(it.seq)] = no; } });
  Object.assign(GOREV[g], {toplam_oge: items.length, toplam_nokta: no || GOREV[g].toplam_nokta, wp_harita: wp});
  const rid = cmdGonder(g, "mission_upload", {items: items, cruise_speed: gorev.cruise_speed}, "gorev_yukle", {oncekiAsama: "hazir"});
  if (!rid){ GOREV[g].asama = "hata"; }
}
function gorevKomut(tip, m){
  const g = Number(m.sysid);
  if (!GOREV[g] && tip !== "gorev_iptal"){
    hwToast(hwT("Önce bir rota yükleyin", "Upload a route first"), "uyari", "GÖREV");
    if (typeof window.gorevKomutSonucIsle === "function") window.gorevKomutSonucIsle({tip: tip + "_sonuc", sysid: g, basari: false, hata: hwT("Yüklü görev yok", "No mission loaded"), bilgi: "gorev_yok"});
    return;
  }
  let onceki, rid = null;
  switch (tip){
    case "gorev_baslat":
      onceki = gorevAsamaGec(g, "gorevde");
      rid = cmdGonder(g, "set_mode", {mode: "AUTO"}, tip, {oncekiAsama: onceki});
      break;
    case "gorev_durdur":
      onceki = gorevAsamaGec(g, "duraklatildi");
      rid = cmdGonder(g, "set_mode", {mode: "LOITER"}, tip, {oncekiAsama: onceki});
      break;
    case "gorev_devam":
      onceki = gorevAsamaGec(g, "gorevde");
      rid = cmdGonder(g, "set_mode", {mode: "AUTO"}, tip, {oncekiAsama: onceki});
      break;
    case "gorev_surdur":
      if (!window.HEPGO_OZ.mission_set_current){
        desteklenmiyor(hwT("Kaldığı yerden sürdürme", "Resume from waypoint"));
        if (typeof window.gorevKomutSonucIsle === "function") window.gorevKomutSonucIsle({tip: "gorev_surdur_sonuc", sysid: g, basari: false, hata: hwT("Sunucu desteklemiyor", "Not supported by server")});
        return;
      }
      onceki = gorevAsamaGec(g, "gorevde");
      rid = cmdGonder(g, "mission_set_current", {seq: Number(m.seq) || 0}, tip, {oncekiAsama: onceki});
      break;
    case "gorev_iptal": {
      const kayit = GOREV[g];
      onceki = kayit ? gorevAsamaGec(g, "iptal") : undefined;
      const basaDon = kayit && kayit.durdurma_davranisi === "basa_don";
      rid = basaDon ? cmdGonder(g, "rtl", {}, tip, {oncekiAsama: onceki}) : cmdGonder(g, "set_mode", {mode: "LOITER"}, tip, {oncekiAsama: onceki});
      break;
    }
  }
  if (!rid && onceki !== undefined && GOREV[g]) GOREV[g].asama = onceki;   // gönderilemedi: aşamayı geri al
}

// ---------------- Rotalar (rotalar.js) ↔ REST /api/drone/routes ----------------
// Rotalar HEPGO › Rotalar sekmesinde yönetilir; harekât ekranında liste yok (#rotaListesi gizli çapa). rotalar.js
// tumRotalariCiz yalnız gorunur:true rotaları çizer; bu bayrak bellek içi ROTA_GORUNUR'dan gelir (göreve yüklenen rota).
function rotaMesafe(noktalar){
  let toplam = 0;
  for (let i = 1; i < noktalar.length; i++){
    const a = noktalar[i - 1], b = noktalar[i], rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
    const s = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
    toplam += 2 * 6371000 * Math.asin(Math.sqrt(s));
  }
  return toplam;
}
function rotaCevir(r){
  const irtifa = (r.cruise_alt === null || r.cruise_alt === undefined) ? 100 : Number(r.cruise_alt);
  const hiz = (r.cruise_speed === null || r.cruise_speed === undefined) ? 10 : Number(r.cruise_speed);
  const noktalar = (r.waypoints || []).map(w => ({lat: Number(w.lat), lon: Number(w.lon),
    irtifa: (w.alt === null || w.alt === undefined) ? irtifa : Number(w.alt), hiz: hiz, eylem: w.action, bekleme: w.hold_s}));
  return {id: r.id, isim: r.name, irtifa_varsayilan: irtifa, hiz_varsayilan: hiz, tur: r.kind, merkez: r.center_name || null,
          gorunur: !!ROTA_GORUNUR[String(r.id)], mesafe_m: rotaMesafe(noktalar), noktalar: noktalar};
}
function rotaListesiYayinla(yeniId){
  if (typeof window.rotaListesiIsle === "function")
    try { window.rotaListesiIsle({tip: "rota_listesi", rotalar: ROTALAR, yeni_id: yeniId}); } catch (e) { console.error(e); }
}
var rotaYetkiUyarildi = false;
async function rotaListesiYenile(yeniId){
  try {
    const liste = await hwFetch("/api/drone/routes");
    const tam = await Promise.all((liste || []).filter(r => r.active !== 0 && r.active !== false).map(r => hwFetch("/api/drone/routes/" + r.id)));
    ROTALAR = tam.map(rotaCevir);
  } catch (e){
    ROTALAR = [];
    if (!rotaYetkiUyarildi){ rotaYetkiUyarildi = true; hwKonsol("ROTA", hwT("Rota listesi alınamadı: ", "Route list unavailable: ") + e.message, "uyari"); }
  }
  rotaListesiYayinla(yeniId);
}
function rotaGorunurAyarla(id, gorunur){
  if (gorunur) ROTA_GORUNUR[String(id)] = true; else delete ROTA_GORUNUR[String(id)];
  const r = ROTALAR.find(x => x.id === Number(id));
  if (r) r.gorunur = !!gorunur;
}
var hizUyarildi = false;
async function rotaKaydet(m){
  try {
    if (m.id === null || m.id === undefined){          // yeni rota (rotalar.js:704, dosya/spiral yükleme)
      const noktalar = m.noktalar || [];
      const y = await hwFetch("/api/drone/routes", {method: "POST", body: {
        name: m.isim, kind: "line", cruise_alt: m.irtifa, cruise_speed: m.hiz,
        waypoints: noktalar.map(n => ({lat: n.lat, lon: n.lon, alt: (typeof n.irtifa === "number") ? n.irtifa : m.irtifa, action: "waypoint"}))}});
      rotaGorunurAyarla(y.id, true);
      await rotaListesiYenile(y.id);
      return;
    }
    if (!m.noktalar){                                    // yalnız görünürlük bayrağı (göz ikonu, tümünü aç/kapat, rota_param açılışı)
      if (m.gorunur !== undefined) rotaGorunurAyarla(m.id, m.gorunur);
      rotaListesiYayinla();
      return;
    }
    // nokta/parametre düzenleme: önce tam gövde, sonra PUT
    const r = await hwFetch("/api/drone/routes/" + m.id);
    const eski = r.waypoints || [], noktalar = m.noktalar || [];
    const ayniSayi = eski.length === noktalar.length;
    const hizlar = new Set(noktalar.map(n => n.hiz).filter(h => typeof h === "number"));
    if ((hizlar.size > 1 || noktalar.some(n => n.aci !== undefined && n.aci !== null && Number(n.aci) >= 0)) && !hizUyarildi){
      hizUyarildi = true;
      hwToast(hwT("Nokta başına hız/açı HEPGO rota şemasında saklanmaz; rota geneli hız ve irtifa kaydedildi", "Per-waypoint speed/angle is not stored in HEPGO routes; route-wide speed/altitude saved"), "uyari", "ROTA");
    }
    const govde = {name: r.name, center_id: r.center_id, kind: r.kind || "line",
      cruise_alt: (typeof m.irtifa === "number") ? m.irtifa : r.cruise_alt,
      cruise_speed: (typeof m.hiz === "number") ? m.hiz : (hizlar.size === 1 ? [...hizlar][0] : r.cruise_speed),
      note: r.note, active: r.active !== 0 && r.active !== false,
      waypoints: noktalar.map((n, i) => ({lat: n.lat, lon: n.lon, alt: (typeof n.irtifa === "number") ? n.irtifa : null,
        action: (ayniSayi && eski[i] && eski[i].action) || "waypoint", hold_s: (ayniSayi && eski[i]) ? eski[i].hold_s : null}))};
    await hwFetch("/api/drone/routes/" + m.id, {method: "PUT", body: govde});
    await rotaListesiYenile();
  } catch (e){
    hwToast(hwT("Rota kaydedilemedi: ", "Route could not be saved: ") + e.message, "hata", "ROTA");
    rotaListesiYayinla();
  }
}
async function rotaSil(m){
  try { await hwFetch("/api/drone/routes/" + m.id, {method: "DELETE"}); }
  catch (e){ hwToast(hwT("Rota silinemedi: ", "Route could not be deleted: ") + e.message, "hata", "ROTA"); }
  await rotaListesiYenile();
}
function rotaTekGoster(m){   // gorev.js:176 rota seçimi: yalnız seçilen rota görünür
  ROTA_GORUNUR = {};
  ROTA_GORUNUR[String(m.id)] = true;
  ROTALAR.forEach(r => { r.gorunur = (r.id === Number(m.id)); });
  rotaListesiYayinla();
}

// ---------------- Dron adı / rengi ----------------
async function dronIsimKaydet(m){
  const g = Number(m.sysid), hedef = KOPRU_OF[g];
  const f = hedef ? ucusBul(hedef.bridge_id, hedef.sysid) : null;
  if (!f){
    hwToast(hwT("Bu dron görevin uçuşlarıyla eşlenemedi; ad değiştirilemez", "Drone could not be matched to a mission flight; cannot rename"), "uyari", "DRON");
    return;
  }
  if (!hwVar(f.drone_id)){   // sipariş uçağı: etiket kuyruk no + ürün adıdır
    hwToast(hwT("Sipariş uçağının adı ürün ve kuyruk numarasından gelir; buradan değiştirilemez", "An order aircraft is named by product and tail number; it cannot be renamed here"), "uyari", "DRON");
    return;
  }
  try {
    const d = await hwFetch("/api/drone/drones/" + f.drone_id);
    // DroneIn (Faz 1): name, serial, model, protocol ('mavlink'|'sanal'|'dji'), order_id, pilot_id, status, note, active
    // (conn_*/bridge_id/sysid dron kaydında YOK; bağlantı uçuş düzeyinde)
    const govde = {name: m.isim, serial: d.serial, model: d.model, protocol: d.protocol || "mavlink",
      order_id: d.order_id, pilot_id: d.pilot_id, status: d.status || "AKTIF", note: d.note, active: d.active !== 0 && d.active !== false};
    await hwFetch("/api/drone/drones/" + f.drone_id, {method: "PUT", body: govde});
    f.name = m.isim;
    const sv = dronVeri(g);
    if (sv) sv.kullanici_isim = ucusEtiket(f);
    baglantiListesiYayinla();
    hwToast(hwT("Dron adı kaydedildi", "Drone name saved"), "basari", "DRON");
  } catch (e){ hwToast(hwT("Dron adı kaydedilemedi: ", "Drone name could not be saved: ") + e.message, "hata", "DRON"); }
}
function dronRenkKaydet(m){
  const g = Number(m.sysid), hedef = KOPRU_OF[g];
  if (!hedef) return;
  const tablo = renkTablosu();
  tablo[hedef.uid] = m.renk;
  hwYerelYaz("hepgo_ops_renk", tablo);
  if (!window.dronRenkler) window.dronRenkler = {};
  window.dronRenkler[String(g)] = m.renk;
}

// ---------------- CEVIR: GÖKTUNGU tip → işlev ----------------
var CEVIR = {
  dron_komut: dronKomutCevir,
  arm_check: (m) => {
    const g = Number(m.sysid);
    if (window.HEPGO_OZ.arm_check_sunucu && KOPRU_OF[g] && gercekWsAcik()) cmdGonder(g, "arm_check", {}, "arm_check");
    else armCheckIstemci(g);
  },
  dron_mesaj_temizle: (m) => {
    MESAJ_TAMPON[Number(m.sysid)] = [];
    if (typeof window.dkDronMesajlariGeldi === "function") window.dkDronMesajlariGeldi(Number(m.sysid), []);
  },
  dron_konsol_gecmis: (m) => {
    const g = Number(m.sysid), hedef = KOPRU_OF[g];
    if (window.HEPGO_OZ.konsol_sunucu && hedef && gercekWsAcik())
      gercekWs.send(JSON.stringify({t: "console_hist", bridge_id: hedef.bridge_id, sysid: hedef.sysid}));
    else if (typeof window.dronKonsolGecmis === "function")
      setTimeout(() => window.dronKonsolGecmis({sysid: g, satirlar: (KONSOL_TAMPON[g] || []).slice()}), 0);
  },
  dron_konsol_temizle: (m) => {
    const g = Number(m.sysid), hedef = KOPRU_OF[g];
    KONSOL_TAMPON[g] = [];
    if (window.HEPGO_OZ.konsol_sunucu && hedef && gercekWsAcik()){
      if (!window.HEPGO_YETKI){   // paylaşılan sunucu tamponunu yalnız komut yetkisi olanlar temizler; izleyici yalnız kendi görünümünü
        hwToast(hwT("Sunucu konsolunu yalnız komut yetkisi olanlar temizleyebilir; yerel görünüm temizlendi", "Only command-authorized users can clear the server console; local view cleared"), "uyari", "KONSOL");
        if (typeof window.dronKonsolGecmis === "function") setTimeout(() => window.dronKonsolGecmis({sysid: g, satirlar: []}), 0);
        return;
      }
      gercekWs.send(JSON.stringify({t: "console_clear", bridge_id: hedef.bridge_id, sysid: hedef.sysid}));
    }
  },
  param_tumu: (m) => {
    const g = Number(m.sysid);
    if (window.HEPGO_OZ.param && m.taze && KOPRU_OF[g]){ cmdGonder(g, "param_list", {}, "param_list"); return; }
    if (window.HEPGO_OZ.param && KOPRU_OF[g] && gercekWsAcik() && !Object.keys(PARAM_ONBELLEK[g] || {}).length){   // yerel önbellek boş: sunucudakini iste
      gercekWs.send(JSON.stringify({t: "param_cache", bridge_id: KOPRU_OF[g].bridge_id, sysid: KOPRU_OF[g].sysid})); return;
    }
    // sunucu param desteği yok ya da önbellek istendi: anında yerel yanıt (dk-param-serit 'bekliyor→bitti' olur ve söner)
    const ob = PARAM_ONBELLEK[g] || {};
    setTimeout(() => paramListesiYayinla(g, ob, "cache", null), 0);
  },
  param_ara: (m) => {
    const g = Number(m.sysid), ob = PARAM_ONBELLEK[g] || {};
    const f = String(m.filtre || "").toUpperCase();
    const secim = {};
    Object.keys(ob).forEach(k => { if (!f || k.indexOf(f) >= 0) secim[k] = ob[k]; });
    setTimeout(() => paramListesiYayinla(g, secim, "cache", null), 0);
  },
  param_yaz: (m) => {
    const g = Number(m.sysid);
    if (!window.HEPGO_OZ.param){
      desteklenmiyor(hwT("Parametre yazma", "Parameter write"));
      if (typeof dkParamYazildi === "function") try { dkParamYazildi(g, m.ad, m.deger, false); } catch (e) {}
      return;
    }
    cmdGonder(g, "param_set", {name: m.ad, value: m.deger}, "param_set", {ad: m.ad, deger: m.deger});
  },
  gorev_yukle: (m) => { gorevYukle(m); },
  gorev_baslat: (m) => gorevKomut("gorev_baslat", m),
  gorev_durdur: (m) => gorevKomut("gorev_durdur", m),
  gorev_devam: (m) => gorevKomut("gorev_devam", m),
  gorev_surdur: (m) => gorevKomut("gorev_surdur", m),
  gorev_iptal: (m) => gorevKomut("gorev_iptal", m),
  rota_tek_goster: rotaTekGoster,
  rota_listele: () => { rotaListesiYenile(); },
  rota_kaydet: (m) => { rotaKaydet(m); },
  rota_sil: (m) => { rotaSil(m); },
  rota_ucus_param: () => {},   // sabit kanat dönüş dairesi parametreleri: param desteği gelince PARAM_REQUEST_READ
  dron_isim_kaydet: (m) => { dronIsimKaydet(m); },
  dron_renk_kaydet: dronRenkKaydet,
  // Bağlantı Yöneticisi Play = "Bağlan": uçuşun link'i (seri/tcp/udp + sysid) köprüde açılır (v1.1 'link' cap: link_open)
  baglanti_baslat: (m) => {
    const f = ucusGrupBul(m.id);
    if (!f || f.protocol === "sanal") return;
    if (!ucusKopruOnline(f)){ hwToast(hwT("Köprü çevrimdışı: ", "Bridge offline: ") + ucusKopruAdi(f), "uyari", "KÖPRÜ"); return; }
    if (!f.link || !f.link.type){
      hwToast(hwT("Uçuşun bağlantısı seçilmemiş; görev › Uçuş Yönetimi › Düzenle › Bağlantı", "No link selected for this flight; task › Flight Management › Edit › Link"), "uyari", "KÖPRÜ");
      return;
    }
    const params = {type: f.link.type};
    ["host", "port", "serial", "baud"].forEach(k => { if (hwVar(f.link[k]) && f.link[k] !== "") params[k] = f.link[k]; });
    if (hwVar(f.sysid)) params.sysid = Number(f.sysid);
    const sysid = hwVar(f.sysid) ? Number(f.sysid) : 1;
    const rid = cmdKopruye(f.bridge_id, sysid, sysid, "link_open", params, "link_open", {flight_id: f.id, etiket: ucusEtiket(f)});
    if (rid){ LINK_DURUM[f.id] = "aciliyor"; baglantiListesiYayinla(); }
  },
  // Stop = "Kes": link_close (köprü oturumu kapanmaz, köprü bağlı kalır)
  baglanti_durdur: (m) => {
    const f = ucusGrupBul(m.id);
    if (!f || f.protocol === "sanal") return;
    const sysid = hwVar(f.sysid) ? Number(f.sysid) : 1;
    const gonder = () => {
      const rid = cmdKopruye(f.bridge_id, sysid, sysid, "link_close", {}, "link_close", {flight_id: f.id, etiket: ucusEtiket(f)});
      if (rid){ delete LINK_DURUM[f.id]; delete LINK_ZAMAN[f.id]; baglantiListesiYayinla(); }
    };
    const soru = hwT(ucusEtiket(f) + " bağlantısı köprüde kapatılsın mı? Telemetri kesilir.", "Close the " + ucusEtiket(f) + " link on the bridge? Telemetry will stop.");
    if (typeof onayIste === "function") onayIste(soru, gonder); else gonder();
  },
  ayar_kaydet: (m) => { if (typeof m.lat === "number" && typeof m.lon === "number") hwYerelYaz("hepgo_ops_merkez", {lat: m.lat, lon: m.lon}); },
  tema: (m) => { if (m.tema) hwYerelYaz("hepgo_ops_tema", m.tema); },
  uyari_listesi: () => {
    if (typeof window.uyariListesiIsle === "function")
      setTimeout(() => window.uyariListesiIsle({tip: "uyari_listesi", uyarilar: UYARI_TAMPON.slice().reverse()}), 0);
  },
  uyari_okundu: () => { UYARI_TAMPON.forEach(u => { u.okundu = true; }); },
  telemetri_dizilim: () => {
    if (typeof window.telemetriDizilimGeldi === "function")
      setTimeout(() => window.telemetriDizilimGeldi({tip: "telemetri_dizilim", dizilim: hwYerel("hepgo_ops_dizilim", [])}), 0);
  },
  telemetri_dizilim_yaz: (m) => { hwYerelYaz("hepgo_ops_dizilim", m.dizilim || []); }
};
// Kapsam dışı tipler: sessizce yutulur (düğmeleri hepgo.css/hepgo_patch.js gizler)
var YUT_LISTESI = new Set(["portlar", "baglanti_sil", "baglanti_ekle", "baglanti_guncelle", "kopru_liste", "sitl_indir", "kopruler_liste",
  "log_listesi", "tlog_listesi", "log_indir", "log_indir_iptal", "tlog_sil", "manuel_durum", "manuel_anahtar", "manuel_eksen",
  "takip_baslat", "takip_iptal", "kalkis_kontrol", "dron_gecmis_liste", "ucus_oku", "ucus_sil", "goruntu_kamera_kaynaklari",
  "goruntu_kamera_dron_bagla", "goruntu_son_kareler", "log_replay_hazirla", "makro_liste", "kalib_mesajlari", "motor_test", "motor_test_dur"]);
function YUT(m){
  if (!YUT_LISTESI.has(m.tip) && !/^(log_|makro_|kopru|kalib|ilk_ayar|voltaj_|ivme_|joystick_|goruntu_|istasyon2|ai_|kayit_|replay_|takipci_|filtre_|tile_)/.test(String(m.tip)))
    console.debug("[HEPGO WS] yutuldu:", m.tip, m);
}

// ---------------- Sahte soket: seri.js `let ws` değişkenine atanır ----------------
var SAHTE_WS = {
  get readyState(){ return gercekWsAcik() ? 1 : 0; },
  send: function(json){
    let m;
    try { m = (typeof json === "string") ? JSON.parse(json) : json; } catch (e) { return; }
    if (!m || typeof m !== "object") return;
    const fn = CEVIR[m.tip];
    try { if (fn) fn(m); else YUT(m); }
    catch (e){ console.error("[HEPGO WS] gönderim çevrilemedi", m.tip, e); }
  },
  close: function(){}
};
ws = SAHTE_WS;   // seri.js:7 `let ws = null` — yeniden bildirilmez, yalnız atanır
window.wsCanli = function(){ return SAHTE_WS; };
window.wsAcikMi = function(){ return gercekWsAcik(); };
// dronlar.js const'ları window'a yansıtılmaz; dron_ekran_disi.js window.sonVeri/varliklar okur
if (typeof sonVeri !== "undefined") window.sonVeri = sonVeri;
if (typeof varliklar !== "undefined") window.varliklar = varliklar;
window.dronRenkler = window.dronRenkler || {};
window.dronlarSon = window.dronlarSon || [];
// Dışa açık yardımcılar (hepgo_patch.js ve hata ayıklama için)
window.HEPGO_WS = {
  durum: () => DURUM, kopruler: () => KOPRULER, ucuslar: () => FLIGHTS, gorevId: () => GOREV_ID, gorevBilgi: () => GOREV_BILGI,
  linkDurum: () => LINK_DURUM, bekleyen: () => BEKLEYEN, gorev: () => GOREV, rotalar: () => ROTALAR, rotaGorunur: () => ROTA_GORUNUR,
  kopruOf: (g) => KOPRU_OF[g] || null, gorunenSysid: gorunenSysid, ucusBul: ucusBul, cmd: cmdGonder,
  rotaYenile: rotaListesiYenile, ucusYenile: ucusYukle, baglan: wsBaglan, gercek: () => gercekWs
};

// ---------------- Başlangıç (ws.js:895-898 karşılığı) ----------------
function parentTema(){
  try {
    if (window.parent && window.parent !== window){
      const th = window.parent.document.documentElement.dataset.theme;
      return th === "dark" ? "koyu" : "acik";
    }
  } catch (e) {}
  return hwYerel("hepgo_ops_tema", null);
}
(function hepgoBaslat(){
  // Dil HEPGO'dan (hepgo_patch.js hepgoDil: parent lang 'tr*' → TR, diğer → EN); kaydet=true gcs_dil'i de hizalar
  try {
    if (typeof applyLanguage === "function"){
      const dil = (typeof window.hepgoDil === "function") ? window.hepgoDil() : ((typeof aktifDil !== "undefined") ? aktifDil : "TR");
      applyLanguage(dil, true);
    }
  } catch (e) { console.error(e); }
  try {
    if (typeof ayarlariUygula === "function"){
      const ayar = {};
      const tema = parentTema();
      if (tema) ayar.tema = tema;
      const merkez = hwYerel("hepgo_ops_merkez", null);
      if (merkez && typeof merkez.lat === "number" && typeof merkez.lon === "number"){ ayar.merkez_lat = merkez.lat; ayar.merkez_lon = merkez.lon; }
      ayarlariUygula(ayar);
    }
  } catch (e) { console.error("[HEPGO WS] ayarlar uygulanamadı", e); }
  setInterval(telemetriDongu, 200);
  baglantiListesiYayinla();   // boş liste: "KAYITLI BAĞLANTI YOK" (uçuşlar gelince dolar)
  if (!GOREV_ID){
    // Serbest uçuş yok (kullanıcı kararı 5): soket açılmaz, harita + bilgi kutusu
    durumYaz("gorevsiz");
    bilgiKutuGoster(hwT("CANLI UÇUŞ", "LIVE FLIGHT"),
      hwT("Canlı Uçuş yalnız bir saha görevinden açılır: görev detayında Excel düğmesinin yanındaki \"Canlı Uçuş\" düğmesini kullanın. Görev dışı (serbest) uçuş izlenmez.",
          "Live Flight opens only from a field task: use the \"Live Flight\" button next to Excel in the task detail. Flights outside a task are not monitored."),
      hwT("Saha görevlerine git", "Go to field tasks"), "#/field");
    return;
  }
  rotaListesiYenile();
  ucusYukle().then(() => {
    baglantiListesiYayinla();
    gorevHaritaMerkezi();
    wsBaglan();
  }).catch(e => {
    const yetki = !!(e && e.status === 403), yok = !!(e && e.status === 404);
    durumYaz(yetki ? "yetki" : "koptu");
    bilgiKutuGoster(yetki ? hwT("YETKİ YOK", "NO PERMISSION") : yok ? hwT("GÖREV BULUNAMADI", "TASK NOT FOUND") : hwT("GÖREV YÜKLENEMEDİ", "TASK COULD NOT BE LOADED"),
      yetki ? hwT("Bu görevin canlı uçuşunu izlemek için görev üyesi ya da saha yöneticisi olmanız gerekir.", "You must be a task member or field manager to watch this task's live flight.")
            : ((e && e.message) || ""),
      hwT("Saha görevlerine git", "Go to field tasks"), "#/field");
  });
})();
