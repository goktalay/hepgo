// =================================================================
// GOKTUNGU - KONSOL (backend log goruntuleme)
// Bu dosya index.html'den mekanik olarak ayrilmistir; yukleme sirasi
// index.html'deki <script> sirasina baglidir (klasik script, ortak scope).
// =================================================================
// KONSOL: backend geri bildirimleri (gcs_server konsol_log -> WS "konsol")
// Her pakette son 200 satirlik tampon gelir; 'no' alani ile yalniz
// yeni satirlar DOM'a eklenir. Kullanici yukari kaydirmadiysa otomatik
// olarak en alta kaydirilir.
// ---------------------------------------------------------------
let sonKonsolNo = 0;

// =================================================================
// v2.4.33: KONSOL -> BILDIRIM (TOAST) KOPRUSU
// -----------------------------------------------------------------
// KULLANICI ISTEGI: "programda her turlu hata bildirimlere uyari
// olarak dusecek ve ekranin sag kosesinde gorunecek. belirli bir
// sure sonra gizlenecek. ornegin drona takeoff dugmesine bastim ve
// takeoff olmadi, bunu sebebi ile bildirim verecek."
//
// TASARIM KARARI: Her hata yolunu tek tek toast cagrisiyla donatmak
// yerine, sunucunun konsol tamponundaki SEVIYE alanini kullaniyoruz.
// `KonsolLog.log(kaynak, mesaj, seviye)` seviyeyi zaten
// `bilgi|uyari|hata|basari` olarak tasiyor ve TUM alt sistemler
// (MAVLink STATUSTEXT, komut gonderimi, baglanti, parametre yazma,
// gorev yukleme, radar, kamera, AI) bu tek fonksiyondan geciyor.
// Dolayisiyla burada tek bir kanca, mevcut VE gelecekteki tum hata
// yollarini otomatik olarak yakalar.
//
// Toast'a YALNIZCA `hata` ve `uyari` seviyeleri gonderilir; `bilgi`
// ve `basari` satirlari konsolda kalir (aksi halde her telemetri
// satiri ekrani doldururdu).
const KONSOL_TOAST_SEVIYE = { hata: true, uyari: true };

// Ayni mesajin tekrar tekrar toast uretmesini onleyen kisa sureli
// bastirma penceresi. ArduPilot ayni PREARM metnini saniyede birkac
// kez yayinlayabilir; boyle bir akista ekran toast ile dolar.
const KONSOL_TOAST_BASTIR_MS = 8000;
const _konsolToastSon = new Map();   // "kaynak|mesaj" -> son gosterim ms

function konsolToastGonder(kaynak, mesaj, seviye){
  if (!KONSOL_TOAST_SEVIYE[seviye]) return;
  if (typeof window.uyariToastGoster !== "function") return;
  const anahtar = kaynak + "|" + mesaj;
  const simdi = Date.now();
  const onceki = _konsolToastSon.get(anahtar);
  if (onceki && (simdi - onceki) < KONSOL_TOAST_BASTIR_MS) return;
  _konsolToastSon.set(anahtar, simdi);
  // Harita buyumesini onle: 200 girdiden sonra en eskileri at
  if (_konsolToastSon.size > 200){
    const ilk = _konsolToastSon.keys().next().value;
    _konsolToastSon.delete(ilk);
  }
  try {
    window.uyariToastGoster({ kategori: kaynak, mesaj: mesaj, seviye: seviye });
  } catch (e){ /* bildirim gosterimi kritik degil, akisi kesmez */ }
}
window.konsolToastGonder = konsolToastGonder;

// v2.4.224: sayfa yenilenince sunucu 200 satirlik tamponu yeniden yollar;
// acilistaki uyarilar (orn. SITL) her yenilemede toast oluyordu. Zaman damgasi
// 30 sn'den eski satir "gecmis" sayilir: konsolda gorunur, bildirim uretmez.
function konsolGecmisMi(s){
  const t = Number(s && s.t) || 0;
  return t > 0 && (Date.now() / 1000 - t) > 30;
}
function konsolGuncelle(satirlar){
  const kutu = document.getElementById("konsolKutu");
  // v2.4.33: Konsol paneli KAPALI olsa bile bildirimler calismali.
  // Onceki surumde `if (!kutu) return;` erken cikisi, konsol
  // penceresi kapaliyken toast kopruunu de devre disi birakiyordu.
  if (!satirlar || !satirlar.length) return;
  if (!kutu){
    // DOM kutusu yok: yalnizca bildirim koprusunu isle
    for (const s of satirlar){
      if (s.no <= sonKonsolNo) continue;
      sonKonsolNo = s.no;
      if (konsolGecmisMi(s)) continue;
      konsolToastGonder(s.kaynak, s.mesaj, s.seviye || "bilgi");
    }
    return;
  }
  const altta = (kutu.scrollTop + kutu.clientHeight) >= (kutu.scrollHeight - 24);
  let eklendi = false;
  for (const s of satirlar){
    if (s.no <= sonKonsolNo) continue;
    sonKonsolNo = s.no;
    const d = new Date(s.t * 1000);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss2 = String(d.getSeconds()).padStart(2, "0");
    const sat = document.createElement("span");
    sat.className = "k-satir k-" + (s.seviye || "bilgi");
    const z = document.createElement("span");
    z.className = "k-zaman";
    z.textContent = hh + ":" + mm + ":" + ss2 + " ";
    const k = document.createElement("span");
    k.className = "k-kaynak";
    k.textContent = "[" + s.kaynak + "] ";
    sat.appendChild(z);
    sat.appendChild(k);
    sat.appendChild(document.createTextNode(s.mesaj));
    kutu.appendChild(sat);
    eklendi = true;
    // v2.4.33: hata/uyari seviyeli her satir sag ust kosede bildirim olur
    // v2.4.224 (kullanici: "ekrani her yeniledigimde ayni uyarilar"): sunucu
    // tamponundaki ESKI satirlar konsola yazilir ama bildirim OLMAZ.
    if (!konsolGecmisMi(s)) konsolToastGonder(s.kaynak, s.mesaj, s.seviye || "bilgi");
  }
  if (!eklendi) return;
  // DOM'da en fazla 200 satir tut
  while (kutu.childElementCount > 200) kutu.removeChild(kutu.firstElementChild);
  if (altta) kutu.scrollTop = kutu.scrollHeight;
}

// Yerel (frontend kaynakli) konsol satiri ekler - backend tamponundan
// bagimsizdir, ornegin tarayici joystick bildirimlerinde kullanilir.
function konsolYaz(kaynak, mesaj, seviye){
  // v2.4.33: yerel (arayuz kaynakli) hatalar da bildirime dusmeli.
  // Kutu yoksa bile bildirim gonderilir.
  konsolToastGonder(kaynak, mesaj, seviye || "bilgi");
  const kutu = document.getElementById("konsolKutu");
  if (!kutu) return;
  const altta = (kutu.scrollTop + kutu.clientHeight) >= (kutu.scrollHeight - 24);
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss2 = String(d.getSeconds()).padStart(2, "0");
  const sat = document.createElement("span");
  sat.className = "k-satir k-" + (seviye || "bilgi");
  const z = document.createElement("span");
  z.className = "k-zaman";
  z.textContent = hh + ":" + mm + ":" + ss2 + " ";
  const k = document.createElement("span");
  k.className = "k-kaynak";
  k.textContent = "[" + kaynak + "] ";
  sat.appendChild(z);
  sat.appendChild(k);
  sat.appendChild(document.createTextNode(mesaj));
  kutu.appendChild(sat);
  while (kutu.childElementCount > 200) kutu.removeChild(kutu.firstElementChild);
  if (altta) kutu.scrollTop = kutu.scrollHeight;
}

