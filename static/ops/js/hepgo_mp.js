// =================================================================
// HEPGO - CANLI UCUS › MISSION PLANNER AKTARIMI (hepgo_mp.js)
// -----------------------------------------------------------------
// YUKLEME YERI: hepgo_ws.js'ten SONRA (FLIGHTS, KOPRU_OF, GOREV_ID,
// hwFetch, hwToast globalleri ve hepgo_patch.js'in dkIslemlerPopupAc
// sarmalayicisi hazir olmali). GOKTUNGU dosyalari degismez.
//
// Sunucu: app/drone_mprelay.py + routers/field.py
//   GET    /api/field/tasks/<gorev>/mp-relays        acik aktarimlar (3 sn'de bir; kart rozeti)
//   GET    /api/field/flights/<ucus>/mp-relay        tek ucusun durumu (pencere acikken 2 sn'de bir)
//   POST   /api/field/flights/<ucus>/mp-relay        ac {pair_sysid?}
//   DELETE /api/field/flights/<ucus>/mp-relay        kapat
//   POST   /api/field/flights/<ucus>/mp-relay/reset-ip
// Arayuz: dron karti › ISLEMLER › "Mission Planner" (yeni grup) ve
// aktarim acikken kart basliginda (baglanti cipinin solunda) "MP" dugmesi (yesil: MP bagli,
// sari: bekleniyor). Pencere: adres (UDPCl) + Kopyala, bagli MP IP'si,
// son paket, sayaclar, Kapat, IP kilidini sifirla, MP adimlari.
// Dil: HEPGO dili (parent <html lang>) — 7 dil (tr/en/de/fr/es/ru/ar).
// =================================================================
(function () {
  "use strict";

  var SOZ = {
    "Mission Planner": {},
    "MISSION PLANNER": {},
    "Mission Planner aktarımı": { en: "Mission Planner relay", de: "Mission-Planner-Weiterleitung", fr: "Relais Mission Planner", es: "Retransmisión a Mission Planner", ru: "Ретрансляция в Mission Planner", ar: "ترحيل Mission Planner" },
    "Kapalı": { en: "Off", de: "Aus", fr: "Désactivé", es: "Desactivado", ru: "Выключено", ar: "مغلق" },
    "Açık · MP bekleniyor": { en: "On · waiting for MP", de: "An · warte auf MP", fr: "Actif · en attente de MP", es: "Activo · esperando MP", ru: "Включено · ожидание MP", ar: "مفتوح · بانتظار MP" },
    "Açık · MP bağlı": { en: "On · MP connected", de: "An · MP verbunden", fr: "Actif · MP connecté", es: "Activo · MP conectado", ru: "Включено · MP подключён", ar: "مفتوح · MP متصل" },
    "Mission Planner bağlantısı aç": { en: "Open Mission Planner link", de: "Mission-Planner-Verbindung öffnen", fr: "Ouvrir la liaison Mission Planner", es: "Abrir enlace de Mission Planner", ru: "Открыть подключение Mission Planner", ar: "فتح اتصال Mission Planner" },
    "Kapat": { en: "Close", de: "Schließen", fr: "Fermer", es: "Cerrar", ru: "Закрыть", ar: "إغلاق" },
    "IP kilidini sıfırla": { en: "Reset IP lock", de: "IP-Sperre zurücksetzen", fr: "Réinitialiser le verrou IP", es: "Restablecer bloqueo de IP", ru: "Сбросить привязку IP", ar: "إعادة تعيين قفل IP" },
    "Kopyala": { en: "Copy", de: "Kopieren", fr: "Copier", es: "Copiar", ru: "Копировать", ar: "نسخ" },
    "Kopyalandı": { en: "Copied", de: "Kopiert", fr: "Copié", es: "Copiado", ru: "Скопировано", ar: "تم النسخ" },
    "Adres": { en: "Address", de: "Adresse", fr: "Adresse", es: "Dirección", ru: "Адрес", ar: "العنوان" },
    "Bağlı MP": { en: "Connected MP", de: "Verbundener MP", fr: "MP connecté", es: "MP conectado", ru: "Подключённый MP", ar: "MP المتصل" },
    "Son paket": { en: "Last packet", de: "Letztes Paket", fr: "Dernier paquet", es: "Último paquete", ru: "Последний пакет", ar: "آخر حزمة" },
    "Paketler": { en: "Packets", de: "Pakete", fr: "Paquets", es: "Paquetes", ru: "Пакеты", ar: "الحزم" },
    "Reddedilen": { en: "Rejected", de: "Abgewiesen", fr: "Rejetés", es: "Rechazados", ru: "Отклонено", ar: "مرفوض" },
    "Açan": { en: "Opened by", de: "Geöffnet von", fr: "Ouvert par", es: "Abierto por", ru: "Открыл", ar: "فتحه" },
    "Kapanma": { en: "Auto close", de: "Auto-Schließen", fr: "Fermeture auto", es: "Cierre automático", ru: "Автозакрытие", ar: "إغلاق تلقائي" },
    "bekleniyor": { en: "waiting", de: "wartet", fr: "en attente", es: "esperando", ru: "ожидание", ar: "قيد الانتظار" },
    "sn önce": { en: "s ago", de: "s her", fr: "s", es: "s", ru: "с назад", ar: "ث مضت" },
    "dk hareketsizlikte": { en: "min of inactivity", de: "Min. Inaktivität", fr: "min d'inactivité", es: "min de inactividad", ru: "мин бездействия", ar: "دقيقة خمول" },
    "Eşleştirme sysid (isteğe bağlı)": { en: "Pairing sysid (optional)", de: "Kopplungs-Sysid (optional)", fr: "Sysid d'appairage (facultatif)", es: "Sysid de emparejamiento (opcional)", ru: "Sysid для привязки (необязательно)", ar: "sysid للاقتران (اختياري)" },
    "Köprü bağlı değil": { en: "Bridge offline", de: "Bridge offline", fr: "Pont hors ligne", es: "Puente desconectado", ru: "Мост не в сети", ar: "الجسر غير متصل" },
    "Köprüyü güncelleyin": { en: "Update the bridge", de: "Bridge aktualisieren", fr: "Mettez à jour le pont", es: "Actualice el puente", ru: "Обновите мост", ar: "حدّث الجسر" },
    "Yetkiniz yok (yalnız izleme)": { en: "No permission (view only)", de: "Keine Berechtigung (nur Ansicht)", fr: "Pas d'autorisation (lecture seule)", es: "Sin permiso (solo lectura)", ru: "Нет прав (только просмотр)", ar: "لا صلاحية (عرض فقط)" },
    "Bu uçuşa köprü atanmadı": { en: "No bridge assigned to this flight", de: "Diesem Flug ist keine Bridge zugeordnet", fr: "Aucun pont affecté à ce vol", es: "No hay puente asignado a este vuelo", ru: "Этому полёту не назначен мост", ar: "لم يُعيَّن جسر لهذه الرحلة" },
    "MP adımları": { en: "Mission Planner steps", de: "Schritte in Mission Planner", fr: "Étapes Mission Planner", es: "Pasos en Mission Planner", ru: "Шаги в Mission Planner", ar: "خطوات Mission Planner" },
    "Sağ üstte bağlantı türünü UDPCl seçin, Connect'e basın.": { en: "Top right: choose link type UDPCl and press Connect.", de: "Oben rechts Verbindungstyp UDPCl wählen und Connect drücken.", fr: "En haut à droite : choisissez UDPCl puis Connect.", es: "Arriba a la derecha: elija UDPCl y pulse Connect.", ru: "Справа вверху выберите тип UDPCl и нажмите Connect.", ar: "أعلى اليمين: اختر UDPCl ثم اضغط Connect." },
    "Sunucu adresini ve portu girin (yukarıdaki adres).": { en: "Enter the server address and port (address above).", de: "Server-Adresse und Port eingeben (Adresse oben).", fr: "Saisissez l'adresse et le port du serveur (ci-dessus).", es: "Introduzca la dirección y el puerto del servidor (arriba).", ru: "Введите адрес и порт сервера (адрес выше).", ar: "أدخل عنوان الخادم والمنفذ (العنوان أعلاه)." },
    "İlk bağlanan bilgisayarın IP'si kilitlenir; başka bilgisayardan bağlanmak için kilidi sıfırlayın.": { en: "The first connecting computer's IP is locked; reset the lock to connect from another computer.", de: "Die IP des ersten verbundenen Rechners wird gesperrt; für einen anderen Rechner Sperre zurücksetzen.", fr: "L'IP du premier ordinateur connecté est verrouillée ; réinitialisez pour en changer.", es: "Se bloquea la IP del primer equipo conectado; restablezca el bloqueo para usar otro.", ru: "IP первого подключившегося компьютера закрепляется; для другого компьютера сбросьте привязку.", ar: "يُقفل عنوان IP لأول حاسوب يتصل؛ أعد تعيين القفل للاتصال من حاسوب آخر." },
    "HEPGO ve Mission Planner aynı anda komut verebilir; MP komutları konsolda \"Mission Planner:\" satırıyla görünür.": { en: "HEPGO and Mission Planner can both command at once; MP commands appear in the console as \"Mission Planner:\" lines.", de: "HEPGO und Mission Planner können gleichzeitig steuern; MP-Befehle erscheinen in der Konsole als „Mission Planner:“-Zeilen.", fr: "HEPGO et Mission Planner peuvent commander en même temps ; les commandes MP apparaissent dans la console (« Mission Planner: »).", es: "HEPGO y Mission Planner pueden enviar órdenes a la vez; las de MP aparecen en la consola como «Mission Planner:».", ru: "HEPGO и Mission Planner могут управлять одновременно; команды MP видны в консоли строками «Mission Planner:».", ar: "يمكن لـ HEPGO وMission Planner إرسال الأوامر معًا؛ تظهر أوامر MP في وحدة التحكم بسطر \"Mission Planner:\"." },
    "Mission Planner aktarımı kapatılsın mı?": { en: "Close the Mission Planner relay?", de: "Mission-Planner-Weiterleitung schließen?", fr: "Fermer le relais Mission Planner ?", es: "¿Cerrar la retransmisión a Mission Planner?", ru: "Закрыть ретрансляцию в Mission Planner?", ar: "هل تريد إغلاق ترحيل Mission Planner؟" },
    "Hata": { en: "Error", de: "Fehler", fr: "Erreur", es: "Error", ru: "Ошибка", ar: "خطأ" }
  };
  function dil() {
    try {
      var l = String((window.parent && window.parent !== window ? window.parent.document : document).documentElement.getAttribute("lang") || "").toLowerCase().slice(0, 2);
      return l || "tr";
    } catch (e) { return "tr"; }
  }
  function T(s) {
    var d = dil();
    if (d === "tr") return s;
    var g = SOZ[s];
    return (g && g[d]) || (g && g.en) || s;
  }

  function stilEkle() {
    if (document.getElementById("hepgoMpStil")) return;
    var st = document.createElement("style");
    st.id = "hepgoMpStil";
    st.textContent =
      ".hepgo-mp-pop{width:330px;max-width:94vw}" +
      ".hepgo-mp-govde{display:flex;flex-direction:column;gap:6px;padding-top:8px;font-size:11.5px}" +
      ".hepgo-mp-rozet{display:inline-block;padding:2px 8px;border-radius:10px;font-weight:700;font-size:10.5px;letter-spacing:.4px}" +
      ".hepgo-mp-rozet.kapali{background:rgba(150,150,150,.18);color:#aab}" +
      ".hepgo-mp-rozet.bekliyor{background:rgba(255,190,60,.18);color:#ffc65a}" +
      ".hepgo-mp-rozet.bagli{background:rgba(60,200,110,.18);color:#5fdc8f}" +
      ".hepgo-mp-adres{display:flex;gap:6px;align-items:center}" +
      ".hepgo-mp-adres code{flex:1;min-width:0;padding:5px 7px;border:1px solid var(--cizgi,#444);border-radius:4px;font-family:monospace;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;user-select:all}" +
      ".hepgo-mp-kv{display:grid;grid-template-columns:auto 1fr;gap:3px 10px}" +
      ".hepgo-mp-kv>span:nth-child(odd){opacity:.7}" +
      ".hepgo-mp-kv>span:nth-child(even){font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
      ".hepgo-mp-dugmeler{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}" +
      ".hepgo-mp-dugmeler button,.hepgo-mp-adres button{padding:5px 10px;border-radius:4px;border:1px solid rgba(90,170,255,.45);background:rgba(90,170,255,.12);color:#9fcaff;cursor:pointer;font-size:11px;font-weight:700}" +
      ".hepgo-mp-dugmeler button.tehlikeli{border-color:rgba(255,90,90,.5);background:rgba(255,90,90,.12);color:#ff9d9d}" +
      ".hepgo-mp-dugmeler button:disabled{opacity:.45;cursor:default}" +
      ".hepgo-mp-not{opacity:.75;font-size:10.5px;line-height:1.4}" +
      ".hepgo-mp-not ol{margin:2px 0 0 16px;padding:0}" +
      ".hepgo-mp-hata{color:#ff9d9d}" +
      ".hepgo-mp-kart-btn{flex:0 0 auto;margin:0 4px;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;line-height:1.4;cursor:pointer;white-space:nowrap;border:1px solid rgba(255,190,60,.5);background:rgba(255,190,60,.12);color:#ffc65a}" +
      ".hepgo-mp-kart-btn.bagli{border-color:rgba(60,200,110,.55);background:rgba(60,200,110,.14);color:#5fdc8f}";
    document.head.appendChild(st);
  }

  // ---- uçuş / köprü eşlemesi (hepgo_ws.js globalleri) ----
  function hedef(g) {
    try { return (typeof KOPRU_OF !== "undefined" && KOPRU_OF) ? KOPRU_OF[Number(g)] : null; } catch (e) { return null; }
  }
  function ucusBul(g) {
    var h = hedef(g);
    var liste = [];
    try { liste = (typeof FLIGHTS !== "undefined" && FLIGHTS) ? FLIGHTS : []; } catch (e) {}
    if (!h || !(Number(h.bridge_id) > 0)) return null;
    var aday = null;
    for (var i = 0; i < liste.length; i++) {
      var f = liste[i];
      if (Number(f.bridge_id) !== Number(h.bridge_id) || f.protocol === "sanal") continue;
      if (Number(f.sysid) === Number(h.sysid)) return f;
      if (f.sysid === null || f.sysid === undefined) aday = aday || f;
    }
    return aday;
  }
  function gorevId() { try { return (typeof GOREV_ID !== "undefined") ? GOREV_ID : null; } catch (e) { return null; } }
  function fetchJson(url, secenek) {
    if (typeof hwFetch === "function") return hwFetch(url, secenek);
    return fetch(url, Object.assign({ credentials: "same-origin" }, secenek || {})).then(function (y) { return y.json(); });
  }
  function bildir(m, sev) { if (typeof hwToast === "function") hwToast(m, sev || "bilgi", "MP"); }
  function onay(m, cb) {
    if (typeof onayIste === "function") { try { onayIste(m, cb); return; } catch (e) {} }
    if (window.confirm(m)) cb();
  }
  function kopyala(metin) {
    var bitti = function () { bildir(T("Kopyalandı") + ": " + metin, "basari"); };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(metin).then(bitti, function () { yedekKopya(metin); bitti(); }); return; }
    } catch (e) {}
    yedekKopya(metin); bitti();
  }
  function yedekKopya(metin) {
    var ta = document.createElement("textarea");
    ta.value = metin; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    ta.remove();
  }
  function el(etiket, sinif, metin) {
    var e = document.createElement(etiket);
    if (sinif) e.className = sinif;
    if (metin !== undefined && metin !== null) e.textContent = metin;
    return e;
  }

  // ---- durum özeti (görev geneli; kart rozeti) ----
  var OZET = {};   // flight_id → info
  function ozetYenile() {
    var gid = gorevId();
    if (!gid) return;
    fetchJson("/api/field/tasks/" + gid + "/mp-relays").then(function (r) {
      var yeni = {};
      (r && r.items || []).forEach(function (x) { yeni[x.flight_id] = x; });
      OZET = yeni;
      kartRozetleri();
    }).catch(function () {});
  }
  function kartRozetleri() {
    var kartlar = document.querySelectorAll("[id^='dronKart_']");
    for (var i = 0; i < kartlar.length; i++) {
      var kart = kartlar[i];
      var g = Number(kart.id.slice(9));
      var f = ucusBul(g);
      var info = f ? OZET[f.id] : null;
      var bas = kart.querySelector(".dron-kart-baslik");
      var btn = kart.querySelector(".hepgo-mp-kart-btn");
      if (!info || !bas) {
        if (btn) btn.remove();
        continue;
      }
      if (!btn) {
        btn = el("button", "hepgo-mp-kart-btn", "MP");
        btn.type = "button";
        (function (gg, b) {
          var durdur = function (ev) { ev.stopPropagation(); };   // başlık tıklaması kartı küçültmesin
          b.addEventListener("click", durdur);
          b.addEventListener("pointerup", durdur);
          b.addEventListener("pointerdown", function (ev) {
            if (ev.button !== 0 && ev.pointerType === "mouse") return;
            ev.stopPropagation(); ev.preventDefault();
            mpPencereAc(gg, { x: ev.clientX, y: ev.clientY });
          });
        })(g, btn);
        var bagla = bas.querySelector(".hk-bagla");
        if (bagla) bas.insertBefore(btn, bagla); else bas.appendChild(btn);
      }
      btn.classList.toggle("bagli", !!info.connected);
      btn.textContent = info.connected ? "MP \u25cf" : "MP \u25cb";
      btn.title = T("Mission Planner aktarımı") + " · " + (info.address || "") + " · " + (info.connected ? T("Açık · MP bağlı") + " " + (info.locked_ip || "") : T("Açık · MP bekleniyor"));
    }
  }

  // ---- pencere ----
  function sure(sn) {
    if (sn === null || sn === undefined) return "—";
    return (sn < 1 ? "<1" : Math.round(sn)) + " " + T("sn önce");
  }
  function mpPencereAc(g, fare) {
    stilEkle();
    var kimlik = "dkPopupMp_" + g;
    if (typeof dkPopupTekil === "function" && dkPopupTekil(kimlik)) return;
    var f = ucusBul(g);
    var pop = el("div", "dk-mini-popup hepgo-mp-pop");
    pop.id = kimlik;
    var baslik = "MISSION PLANNER — D" + g;   // büyük harf elle: başlık CSS uppercase tr dilinde "MİSSİON" yapar
    if (typeof dkMiniPopupBaslikKur === "function") dkMiniPopupBaslikKur(pop, baslik, "pp_dkMp_" + g, "fa-tower-broadcast");
    else pop.appendChild(el("div", "dk-mp-baslik", baslik));
    var govde = el("div", "hepgo-mp-govde");
    pop.appendChild(govde);
    var zaman = null, son = null, mesgul = false;

    function kapat() {
      if (zaman) clearInterval(zaman);
      pop.remove();
    }
    pop.kapat = kapat;

    function hataGoster(e) {
      bildir(T("Hata") + ": " + (e && e.message || e), "hata");
    }
    function islem(yontem, yol, govdeVeri) {
      if (!f || mesgul) return;
      mesgul = true;
      var url = "/api/field/flights/" + f.id + "/mp-relay" + (yol || "");
      fetchJson(url, { method: yontem, body: govdeVeri }).then(function (r) { son = r; ciz(); ozetYenile(); })
        .catch(hataGoster).then(function () { mesgul = false; ciz(); });
    }
    function yukle() {
      if (!f || !document.body.contains(pop)) { if (zaman) clearInterval(zaman); return; }
      fetchJson("/api/field/flights/" + f.id + "/mp-relay").then(function (r) { son = r; ciz(); })
        .catch(function (e) { son = { hata: e && e.message || String(e) }; ciz(); });
    }
    function ciz() {
      while (govde.firstChild) govde.removeChild(govde.firstChild);
      if (!f) { govde.appendChild(el("div", "hepgo-mp-hata", T("Bu uçuşa köprü atanmadı"))); return; }
      if (!son) { govde.appendChild(el("div", "hepgo-mp-not", "…")); return; }
      if (son.hata) { govde.appendChild(el("div", "hepgo-mp-hata", son.hata)); return; }
      var r = son;
      var durum = !r.active ? "kapali" : (r.connected ? "bagli" : "bekliyor");
      var ust = el("div");
      ust.appendChild(el("span", "hepgo-mp-rozet " + durum, durum === "kapali" ? T("Kapalı") : durum === "bagli" ? T("Açık · MP bağlı") : T("Açık · MP bekleniyor")));
      govde.appendChild(ust);
      if (r.active) {
        var adres = el("div", "hepgo-mp-adres");
        adres.appendChild(el("span", null, "UDPCl"));
        var kod = el("code", null, r.address || ("?:" + r.port));
        adres.appendChild(kod);
        var kb = el("button", null, T("Kopyala"));
        kb.type = "button";
        kb.addEventListener("click", function () { kopyala(r.address || ""); });
        adres.appendChild(kb);
        govde.appendChild(adres);
        var kv = el("div", "hepgo-mp-kv");
        var ekle = function (k, v) { kv.appendChild(el("span", null, k)); var s = el("span", null, v); s.title = v; kv.appendChild(s); };
        ekle(T("Bağlı MP"), r.locked_ip ? (r.peer || r.locked_ip) : T("bekleniyor"));
        ekle(T("Son paket"), sure(r.last_rx_ago));
        ekle(T("Paketler"), "MP→ " + r.rx_packets + " · →MP " + r.tx_packets);
        var dr = r.dropped || {};
        ekle(T("Reddedilen"), "IP " + (dr.ip || 0) + " · " + (dr.invalid || 0) + " · " + (dr.rate || 0) + " · " + (dr.offline || 0));
        ekle(T("Açan"), (r.opened_by || "—") + (r.pair_sysid ? " · sysid " + r.pair_sysid : ""));
        ekle(T("Kapanma"), Math.round((r.idle_timeout_s || 1800) / 60) + " " + T("dk hareketsizlikte"));
        govde.appendChild(kv);
      } else if (!r.bridge_online) {
        govde.appendChild(el("div", "hepgo-mp-not", T("Köprü bağlı değil")));
      } else if (r.bridge_supported === false) {
        govde.appendChild(el("div", "hepgo-mp-hata", T("Köprüyü güncelleyin") + " (Linux ≥" + r.min_versions.linux + " / Windows ≥" + r.min_versions.windows + ") · " + (r.bridge_ver || "?")));
      }
      var db = el("div", "hepgo-mp-dugmeler");
      if (!r.can_manage) {
        govde.appendChild(el("div", "hepgo-mp-not", T("Yetkiniz yok (yalnız izleme)")));
      } else if (!r.active) {
        var sysGir = el("input");
        sysGir.type = "number"; sysGir.min = "1"; sysGir.max = "255"; sysGir.placeholder = "255";
        sysGir.style.width = "64px";
        sysGir.title = T("Eşleştirme sysid (isteğe bağlı)");
        var ac = el("button", null, T("Mission Planner bağlantısı aç"));
        ac.type = "button";
        ac.disabled = mesgul || !r.available || !r.bridge_online || r.bridge_supported === false;
        ac.addEventListener("click", function () {
          var v = parseInt(sysGir.value, 10);
          islem("POST", "", (v >= 1 && v <= 255) ? { pair_sysid: v } : {});
        });
        db.appendChild(ac);
        var et = el("label", "hepgo-mp-not", T("Eşleştirme sysid (isteğe bağlı)") + " ");
        et.appendChild(sysGir);
        govde.appendChild(db);
        govde.appendChild(et);
      } else {
        var sif = el("button", null, T("IP kilidini sıfırla"));
        sif.type = "button"; sif.disabled = mesgul || !r.locked_ip;
        sif.addEventListener("click", function () { islem("POST", "/reset-ip"); });
        var kp = el("button", "tehlikeli", T("Kapat"));
        kp.type = "button"; kp.disabled = mesgul;
        kp.addEventListener("click", function () { onay(T("Mission Planner aktarımı kapatılsın mı?"), function () { islem("DELETE", ""); }); });
        db.appendChild(sif); db.appendChild(kp);
        govde.appendChild(db);
      }
      var not = el("div", "hepgo-mp-not");
      not.appendChild(el("b", null, T("MP adımları")));
      var ol = el("ol");
      [T("Sağ üstte bağlantı türünü UDPCl seçin, Connect'e basın."), T("Sunucu adresini ve portu girin (yukarıdaki adres)."),
        T("İlk bağlanan bilgisayarın IP'si kilitlenir; başka bilgisayardan bağlanmak için kilidi sıfırlayın."),
        T("HEPGO ve Mission Planner aynı anda komut verebilir; MP komutları konsolda \"Mission Planner:\" satırıyla görünür.")]
        .forEach(function (s) { ol.appendChild(el("li", null, s)); });
      not.appendChild(ol);
      govde.appendChild(not);
    }

    pop.style.position = "fixed";
    if (typeof dkPopupOneGetirKur === "function") dkPopupOneGetirKur(pop);
    document.body.appendChild(pop);
    if (typeof dkMiniPopupKonumla === "function") dkMiniPopupKonumla(pop, fare || {});
    ciz();
    yukle();
    zaman = setInterval(yukle, 2000);
  }
  window.hepgoMpPencereAc = mpPencereAc;

  // ---- İŞLEMLER penceresine "Mission Planner" grubu ----
  function islemlereEkle() {
    if (typeof window.dkIslemlerPopupAc !== "function" || window.dkIslemlerPopupAc.__hepgoMp) return;
    var onceki = window.dkIslemlerPopupAc;
    var sarili = function (sysid, fare) {
      var sonuc = onceki.apply(this, arguments);
      try {
        var pop = document.getElementById("dkPopupIslemler_" + sysid);
        var izgara = pop ? pop.querySelector(".dk-islem-izgara") : null;
        if (izgara && ucusBul(sysid) && !izgara.querySelector(".hepgo-mp-hucre")) {
          var grup = el("div", "dk-islem-grup", "MISSION PLANNER");   // büyük harf elle: CSS uppercase tr'de "MİSSİON" yapar
          izgara.appendChild(grup);
          var b = el("button", "dk-islem-hucre hepgo-mp-hucre");
          b.type = "button";
          b.innerHTML = "<i class='fa-solid fa-tower-broadcast dk-islem-hucre-ikon'></i><span class='dk-islem-hucre-metin'></span>";
          b.querySelector(".dk-islem-hucre-metin").textContent = "Mission Planner";
          b.title = T("Mission Planner aktarımı") + " (UDPCl)";
          b.addEventListener("click", function (ev) {
            ev.stopPropagation();
            var fk = { x: ev.clientX, y: ev.clientY };
            pop.remove();
            mpPencereAc(sysid, fk);
          });
          izgara.appendChild(b);
        }
      } catch (e) { try { console.warn("[hepgo_mp] islemler:", e); } catch (e2) {} }
      return sonuc;
    };
    sarili.__hepgoMp = true;
    sarili.__hepgoSarmal = true;
    sarili.__orijinal = onceki;
    window.dkIslemlerPopupAc = sarili;
  }

  islemlereEkle();
  if (gorevId()) {
    setTimeout(ozetYenile, 1500);
    setInterval(ozetYenile, 3000);
  }
})();
