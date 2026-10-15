// =================================================================
// GOKTUNGU - UYGULAMA KOK YOLU (v2.4.229)
// KOK NEDEN (GRCON, www.goktungu.com/app/): merkez sunucu yalniz `/app/...`
// isteklerini GCS surecine vekil eder (ek_app_vekil: `/app/js/ws.js` ->
// `/js/ws.js`). Istemci kodunun MUTLAK yolla yaptigi cagrilar
// (`/api/istemci/kamera_oturum`, `/kamera/<id>`, `/api/app/sirket_logo`)
// merkeze gidiyor ve 404 aliyordu: kamera oturumu acilmiyor, canli goruntu
// ve sirket logosu gelmiyordu. Yerel kurulumda (kok `/`) onek bostur.
// dronlar.js'deki `altYol` deseniyle ayni; tek yerde tanimlanir.
// =================================================================
(function () {
  var altYol = /^\/app(?:\/|$)/.test(String(window.location.pathname || ""));
  window.appYolu = function (yol) {
    yol = String(yol || "");
    if (!altYol || !yol.startsWith("/") || yol.startsWith("/app/")) return yol;
    return "/app" + yol;
  };
  window.appKok = altYol ? "/app" : "";
})();
