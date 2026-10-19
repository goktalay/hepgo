# SSH Master hesap ve senkronizasyon servisi (sshmasters.com)

Sözleşme: `docs/sshmaster-api.md` (v2). Tanıtım sitesi + hesap sayfaları (`static/`), hesap/oturum/kütüphane/indirme/sürüm uçları (`sshm/main.py`).
Düz şifre sunucuya hiç gelmez (istemci PBKDF2 → auth_hash); bağlantı kütüphanesi uçtan uca şifrelidir.

Canlı: `/opt/hepgo/sshmaster` (hepgo kullanıcısı), systemd `hepgo-sshmasters` (`deploy/hepgo-sshmasters.service`, 127.0.0.1:8095),
Cloudflare tüneli `sshmasters.com` + `www` → `http://127.0.0.1:8095`. Veri `data/sshm.db` + `data/releases/<sürüm>/`.
`.env` (sunucuda üretilir, repoda yok): `SSHM_SALT_KEY`, `SSHM_RELEASE_KEY`, `SSHM_DATA_DIR`. SMTP (register@hepgo.com) ve Merkez iç
anahtarı `/opt/hepgo/veilox/.env`'den okunur. Yönetim: HEPGO Merkez › SSH Master (`app/routers/sshmaster_admin.py`).

Dağıtım: `rsync -rlc --delete --exclude=__pycache__ central/sshmaster_server/{sshm,static} hepgo-new:/opt/hepgo/sshmaster/` →
`chown -R hepgo:hepgo /opt/hepgo/sshmaster` → `systemctl restart hepgo-sshmasters`.
Testler: `cd central/sshmaster_server && ../../.venv/bin/python -m tests.test_sshm`; Merkez vekilleri: `.venv/bin/python -m tests.test_sshmaster_admin`.

## Mastertool (v2: SSH Master + FTP Masters tek hesap)
- Uygulamalar: `sm` (SSH Master, `/api/sm` — v2 sözleşmesi aynen), `fm` (FTP Masters, `/api/fm` — docs/ftpmasters-api.md),
  portal web hesabı `/api/mt`. Siteler Host'a göre: `mastertool.download` (portal), `sshmasters.com`, `ftpmasters.com` (static/<site>/).
- Veritabanı aynı (`data/sshm.db`); v1 şeması ilk açılışta yerinde taşınır (kütüphane / sürüm / indirme / oturum → `sm`, `user_apps`).
- Ortam: `FTPM_RELEASE_KEY` (FTP Masters CI), `MT_PORTAL_LIVE=1` (DNS + tünel hazır olunca: ürün sitelerinin hesap sayfaları ve
  e-posta bağlantıları portala), `MT_PUBLIC_URL`, `FTPM_PUBLIC_URL`, `MT_SMTP_HOST/PORT/USER/PASS` + `MT_MAIL_FROM`
  (yoksa VEILOX_SMTP_* ile register@hepgo.com), `MT_MERKEZ_UDS` (vars. /run/hepgo/merkez.sock — destek talepleri Merkez'e).
- Testler: `../../.venv/bin/python -m tests.test_sshm` (v1 uyumu) ve `-m tests.test_mastertool`.
- Oyunlar (`main.GAMES`, kod `vf` = VOLFAI, HTML5): kimlik uçları `/api/vf/auth/*` (web oturumu `client:'web'` → çerez; lisans / kütüphane /
  sürüm yok), profil `GET|PUT /api/vf/profile` (kullanıcı başına tek JSON, ≤ 64 KB, tablo `vf_profiles`). Oyun `mastertool.download/oyunlar/volfai/`
  altından sunulur: dosyalar DEPODA DEĞİL (goktalay/Volfia `release/*`: `index.html, manifest.webmanifest, sw.js, css/, js/, icons/`) —
  dağıtımda `static/mt/oyunlar/volfai/` içine kopyalanır (`.gitignore`); tanıtım sayfası `static/mt/oyunlar/volfai/tanitim/` depodan gelir.
  Katalogda (`/api/mt/apps?v=<Master Tool sürümü>`) `kind:'web'` kaydı yalnız v ≥ 1.2.0 isteyene verilir (eski istemciler kind'i tanımaz).
- Site kiti `static/kit.js` + `kit.css` (hepgo.com'daki `central/veilox_server/static/exp2/kit.js` ile BİREBİR aynı dosya — değişince ikisini birlikte güncelleyin):
  dönen vektör dünya (Natural Earth 110m kara noktaları, kamu malı), gece/gündüz, 8 dil (tr kaynak; `static/i18n/<site>.<dil>.json`, Arapça sağdan sola).
  Sayfa metni değişirse çeviri anahtarları da değişir: yeni/eskimiş metinleri sözlüklere ekleyin (anahtar = Türkçe metin).

## Web sürümleri, site içi giriş ve Master Tool web başlatıcısı
- **Web sürümleri** ayrı servis (mtweb): her Mastertool hostunda `/web/sshmaster/`, `/web/ftpmaster/`, `/web/sqlmaster/`, `/web/notepadmaster/`,
  `/web/convertmaster/` (`main.WEB_APPS`). Cloudflare tüneli `^/(web|static/mt|api/tools|ws/tools)(/|$)` yollarını mtweb'e verir; mtweb aynı hosttaki
  `sm_session` çerezini `GET /api/mt/me` ile doğrular, oturum yoksa `302 /giris?next=/web/<app>/`. Bu serviste `/web/*` yalnız YEDEK
  (yerel çalıştırma: oturumsuz → giriş akışı, portalda `/web/` → `/uygulamalar`, oturumlu → 503 "şu an kullanılamıyor"). Araçların (IP Tools …) web sürümü yok.
- **Site içi giriş / kayıt**: `/giris`, `/kayit`, `/sifremi-unuttum` her ürün sitesinde YERİNDE çalışır (MT_PORTAL_LIVE=1 iken de; "Mastertool hesabı ile"
  rozeti). Hesabım, doğrulama ve şifre sıfırlama portalda kalır. Dönüş `?next=` → `safe_next` (yalnız `/` ile başlayan, `//` ile başlamayan, ters bölü /
  boşluk / denetim karakteri içermeyen göreli yol; yoksa ürün sitesinde `/web/<app>/`) → `hesap.html` `data-next`. Ürün sitesinden kayıtta doğrulama
  bağlantısı `?app=<site>` taşır; doğrulama sonrası Hesabım "<uygulama> web'de aç" (yalnız `SITE_URLS` adresi) gösterir. Çerez host'a özeldir: portalda
  açılan oturum ürün sitesinde geçmez (orada yeniden giriş).
- **Başlıkta oturum**: `static/mtsite.js` + `mtsite.css` (ürün siteleri + portal ana sayfası) `GET /api/<site>/session` (oturumsuz da 200, `{user:null}`)
  ile Giriş / Kayıt ol ↔ ad + "Web'de aç" + Çıkış. Ürün ana sayfalarında birincil "Web'de aç", ikincil "İndir (.exe)" ve "Tarayıcıda ya da masaüstünde" bölümü.
- **`mastertool.download/uygulamalar`** (`static/uygulamalar.{html,js,css}`): masaüstü Master Tool ana ekranının (mastertool/src/renderer) web karşılığı —
  aynı kutucuklar, bölümler (Uygulamalar / Araçlar / Oyunlar / Master Tool), hesap rozeti, bağlam menüsü; web sürümleri aynı sayfada sekmede (iframe, YALNIZ
  aynı köken `/web/<slug>/` ve `/oyunlar/<slug>/`), ayrıca yeni sekmede; `#sshmaster` ile doğrudan açılır. Katalog `GET /api/mt/apps?web=1`
  (her kayda `web` yolu, çerez oturumunda kişiye özel `download_url`, oyunlar her zaman; `web` parametresiz yanıt masaüstü için değişmedi). Oturum yoksa
  sayfa içinde giriş / kayıt. Sözlük `mt` + `hesap` (`data-dicts`).
- Güvenlik: hesap sayfaları ve başlatıcı `ACCOUNT_CSP` / `LAUNCHER_CSP` (satır içi betik yok, `frame-src 'self'`, `frame-ancestors 'self'`);
  robots.txt `Disallow: /web/` (portalda ayrıca `/uygulamalar`), site haritasına girmez.
