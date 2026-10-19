# mtweb — Mastertool web uygulamaları

Mastertool hesabıyla (mastertool.download) giriş yapan kullanıcılara masaüstü uygulamaların web sürümleri:
**Notepad Master** ve **Convert Master**. HEPGO'da "Araçlar" altında çalışan aynı ön yüz (`static/mt/<app>/`) ve aynı arka uç
(`app/routers/tools_notepad.py`, `tools_convert.py`, `tools_mt.py`) KOPYALANMADAN ayrı bir ASGI servisinde (`app/mtweb/`) çalışır.

Bu serviste kullanıcı **yalnız kendi dosya alanında** çalışır; sunucudan dışarıya ağ bağlantısı açılmaz:
Notepad'in SSH/FTP/uzak klasör özellikleri ve Convert'in konuşma/OCR model indirme uçları kapalıdır (403; arayüzde seçenekler
"Bu özellik masaüstü sürümünde" notuyla devre dışı). SSH Master, FTP Masters, SQL Master sayfaları "Web sürümü yakında" bilgi
sayfası gösterir.

## Mimari

```
tarayıcı ──► Cloudflare ──► cloudflared ──┬─ ^/(web|static/mt|api/tools)(/|$) ──► unix:/run/hepgo/mtweb.sock  (hepgo-mtweb)
                                          └─ diğer her şey ───────────────────────► hesap servisi (127.0.0.1:8095)
hepgo-mtweb ── GET /api/mt/me (Cookie: sm_session) ──► hesap servisi (MTWEB_ACCOUNT_URL)
```

| Dosya | Görev |
|---|---|
| `app/mtweb/config.py` | Ortam; **ilk** içe aktarılır: `CAYMAZ_DATA_DIR`/`CAYMAZ_DB`'yi mtweb veri dizinine zorlar (HEPGO `data/` seçilirse açılmaz) |
| `app/mtweb/main.py` | FastAPI uygulaması: güvenlik ara katmanı, sayfalar, HEPGO araç router'larının dahil edilmesi |
| `app/mtweb/auth.py` | Hesap servisi istemcisi (60 sn önbellek), Origin denetimi, oran sınırı |
| `app/mtweb/quota.py` | Alan/dosya/yükleme kotaları, Convert iş kapısı; HEPGO router kancalarını kurar (`install()`) |
| `app/mtweb/db.py` | Küçük şema: `users`, `tools_mt_store`, `app_kv`, `audit_logs`, `mtweb_audit` |
| `static/mt/common/mtweb.js`, `mtweb.css` | Üst şerit, site dili, oturum düşünce girişe yönlendirme, bilgi sayfası metinleri |

**Kullanıcı:** `tools_common.tools_user` bağımlılığı `app.dependency_overrides` ile Mastertool kullanıcısına çevrilir. mtweb
DB'sinde her hesap kimliğine (`mt_id`) bir `users` satırı açılır; araç kodu bu yerel `id` ile çalışır
(`DATA_DIR/tools/<app>/<id>/…`).

**HEPGO'daki küçük kancalar** (varsayılanları HEPGO davranışını değiştirmez):

| Modül | Kanca |
|---|---|
| `tools_common` | `BRAND` (alan etiketi; mtweb'de "Mastertool") |
| `tools_notepad` | `ALLOW_REMOTE` (False → `create_remote` SSH/FTP açmaz), `REMOTE_GUARD`, `WRITE_GUARD` (kota), `PUBLIC_PATH` (çalışma kopyası yolu arayüze göreli gider) |
| `tools_mt` | `UPLOAD_GUARD` (parça parça kota), `MAX_UPLOAD` hata metni dinamik |
| `tools_convert` | `JOB_GATE` (eşzamanlılık/giriş boyutu/kota), `FFMPEG_PREFIX` (nice), `FFMPEG_THREADS`, `FFMPEG_TIMEOUT`, `MAX_CONCURRENCY` |
| `static/mt/common/hepgo.js` | `window.MTWEB` varsa: `MT.web`, dil (site dili → tarayıcı → en), "Dosyalarınız" etiketi |
| `static/mt/{notepadmaster,convertmaster}/bridge.js` | `MT.web` varsa çıkış Mastertool hesabından, "web" bağlantıları mastertool.download'a |
| `static/mt/notepadmaster/app.js` | `MT.web.remote === false` → SSH/FTP türleri devre dışı, varsayılan tür "Lokal klasör" |

## Yollar

| Yol | Açıklama |
|---|---|
| `/web/` | Host'a göre: notepadmaster.com → `/web/notepadmaster/`, convertmaster.app → `/web/convertmaster/`, mastertool.download → `/uygulamalar`, diğerleri → `/` |
| `/web/notepadmaster/`, `/web/convertmaster/` (+ `project.html`) | Uygulama (oturum gerekir). Sunucu HTML'e `/web/config.js?app=…`, `../common/mtweb.js`, `../common/mtweb.css` ekler |
| `/web/sshmaster/`, `/web/ftpmaster/`, `/web/sqlmaster/` | "Web sürümü yakında — masaüstü sürümünü indirin" (indir → `/#indir`) |
| `/web/config.js` | `window.MTWEB` (kullanıcı adı, uygulama, bağlantılar; `no-store`) |
| `/web/common/*`, `/web/<app>/*`, `/static/mt/*` | Ön yüz dosyaları (oturumsuz; kod herkese açık). Çıplak `/static/mt/**/*.html` → `/web/<app>/` |
| `/web/healthz` | Sağlık |
| `/api/tools/mt/account` | mtweb'e özgü hesap durumu |
| `/api/tools/mt/{notepadmaster,convertmaster}/fs/{list,mkdir,upload,download,delete,rename,usage}` | Kullanıcının dosya alanı |
| `/api/tools/notepad/*`, `/api/tools/convert/*` | HEPGO uçları — beyaz liste; **403**: `notepad/browse/*`, `notepad/keys/*`, `convert/{speech,ocr}/download`, uzak türde `notepad/conn/save`, `notepad/conn/test` |
| diğer `/api/*` | 404 (SSH/FTP/SQL/VOLFAI uçları ve HEPGO'nun geri kalanı bu serviste yok) |

**Üst şerit** (tam sayfada; aynı kökenli iframe içinde — proje pencereleri — gizli): uygulama simgesi/adı, "Masaüstü sürümünü indir"
(`/#indir`), "Tüm uygulamalar" (https://mastertool.download/uygulamalar), kullanıcı adı, Çıkış (`POST /api/mt/auth/logout`,
başlık `x-sshm: 1`, hesap servisine gider). Dil: `localStorage['mt-lang']` (site dili, kit.js) → `navigator.languages` → en.

## Kimlik

- Hesap servisinin web oturum çerezi `sm_session` (httponly, host-only). mtweb yalnız bu çerezi
  `GET {MTWEB_ACCOUNT_URL}/api/mt/me` isteğine `Cookie: sm_session=<tok>` olarak iletir → `{user:{id,email,name,verified}}`.
  401/403 → oturum yok. Sonuç 60 sn önbellekte (anahtar belirtecin SHA-256 özeti). Servis ulaşılamazsa 503.
- Oturumsuz HTML → `302 /giris?next=<göreli yol>`; API → 401 (ön yüz girişe yönlendirir).
- Yalnız doğrulanmış (`verified`) hesaplar; değilse 403.
- Not: çerez host-only olduğundan ürün sitelerinde (notepadmaster.com …) mtweb'in çalışması için hesap servisinin o host'ta da
  `sm_session` vermesi gerekir. Hesap sayfası (`hesap.js`) giriş sonrası dönüşte bugün `sonra` parametresini ve
  `/indir|/hesabim|/oyunlar` beyaz listesini kullanır; `/web/…` dönüşü için hesap servisinde `next` ve `/web/` eklenmelidir.

## Güvenlik

1. **Köken (CSRF):** `POST/PUT/PATCH/DELETE` isteklerinde `Origin` (yoksa `Referer`) host:port'u isteğin `Host`'u ile aynı
   olmalı; değilse 403 (kimlik denetiminden önce). `Origin: null` reddedilir.
2. **Kotalar** (ortamla değişir, bkz. aşağı): kullanıcı başına dosya alanı (iki uygulamanın tüm dizinleri — files, converted,
   cache, work — toplamı) 200 MB; tek yükleme 100 MB (ara katman `Content-Length` ön denetimi + akış sırasında parça parça);
   girdi (dosya+klasör) sayısı 5000; yükleme dışı istek gövdesi 60 MB; `Content-Length`'siz parçalı gövde 411.
   Convert: kullanıcı başına 1, genel 2 eşzamanlı iş; giriş ≤ 200 MB; ffmpeg `nice -n 15`, `-threads 2`, 600 sn süre sınırı;
   Pillow piksel tavanı 80 MP; iş sonunda alan kotası aşılırsa çıktı silinir. Oran sınırı: kullanıcı başına okuma 1200/dk,
   yazma 300/dk (IP başına 3 katı) → 429 + `Retry-After`.
3. **Yol kaçışı:** tüm dosya yolları `tools_mt.norm_rel` + `resolve` ile kullanıcı köküne sıkıştırılır (`..`, mutlak yol);
   sembolik bağ hedefi kökün dışındaysa 400. Notepad oturumu ayrıca proje kökü dışına çıkamaz. Testli.
4. **Başlıklar:** CSP `default-src 'self'; script-src 'self'` (inline/eval yok — Monaco AMD yükleyici + worker ile çalışır;
   uçtan uca testte CSP ihlali sıfır), `style-src 'self' 'unsafe-inline'` (Monaco/arayüz stil öznitelikleri), `worker-src 'self'
   blob:`, `connect-src 'self'`, `frame-ancestors 'self'`; `X-Content-Type-Options: nosniff`, `Referrer-Policy`,
   `X-Frame-Options: SAMEORIGIN`, COOP; `/api/` ve HTML `no-store`. Hata yanıtları iç ayrıntı sızdırmaz (500 → genel mesaj,
   ayrıntı günlüğe); çalışma kopyası yolları arayüze göreli gider.
5. **Acil anahtar:** `MTWEB_DISABLED_APPS=convertmaster,…` → uygulamanın API'si 403, sayfası 503 bilgi sayfası.
6. **Denetim:** `mtweb_audit` (zaman, kullanıcı, uygulama, işlem, boyut, istemci IP, kısa teknik not). İçerik yazılmaz.
   İşlemler: `session`, her yazma isteği (`notepad/proj/save`, `mt/convertmaster/fs/upload`, …), indirmeler, `convert`,
   reddedilenler (`csrf`, `blocked`, `quota`, `rate`). 90 günden eskiler saatlik temizlenir.

## Ortam değişkenleri

| Değişken | Varsayılan | |
|---|---|---|
| `MTWEB_DATA_DIR` / `CAYMAZ_DATA_DIR` | `data/mtweb` | Veri dizini (DB `mtweb.db`, `tools/`); HEPGO `data/` olamaz |
| `CAYMAZ_ENV_FILE` | `<veri>/.env` | `MTWEB_*` değerleri buradan da okunur |
| `MTWEB_ACCOUNT_URL` | `http://127.0.0.1:8095` | Hesap servisi (iç adres) |
| `MTWEB_ACCOUNT_CACHE_S` | 60 | Oturum önbelleği |
| `MTWEB_DISABLED_APPS` | — | Acil anahtar |
| `MTWEB_SPACE_MB` / `MTWEB_UPLOAD_MB` / `MTWEB_MAX_FILES` / `MTWEB_BODY_MB` | 200 / 100 / 5000 / 60 | Kotalar |
| `MTWEB_CONVERT_USER_JOBS` / `MTWEB_CONVERT_JOBS` | 1 / 2 | Eşzamanlı Convert işi |
| `MTWEB_CONVERT_INPUT_MB` / `MTWEB_CONVERT_TIMEOUT_S` / `MTWEB_CONVERT_THREADS` / `MTWEB_CONVERT_NICE` | 200 / 600 / 2 / 15 | Dönüştürücü sınırları |
| `MTWEB_IMAGE_MAX_MPX` | 80 | Pillow piksel tavanı |
| `MTWEB_RATE_READ` / `MTWEB_RATE_WRITE` | 1200 / 300 | Dakikalık istek |
| `MTWEB_AUDIT_DAYS` | 90 | Denetim saklama |
| `MTWEB_ALL_APPS_URL` / `MTWEB_DOWNLOAD_URL` | mastertool.download/uygulamalar / `/#indir` | Şerit bağlantıları |

## Dağıtım (PROD — onaysız yapılmaz)

1. `install -d -o hepgo -g hepgo -m 750 /opt/hepgo/mtweb-data`; isteğe bağlı `/opt/hepgo/mtweb-data/.env` (640 root:hepgo).
2. Kod HEPGO deposundan çalışır (`/opt/hepgo/fabrika-yonetim`, aynı `.venv`). `deploy/mtweb/hepgo-mtweb.service` →
   `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now hepgo-mtweb`.
3. `deploy/mtweb/cloudflared-ingress.yml` parçasını cloudflared `ingress:` listesine hesap servisi kurallarının ÜSTÜNE ekleyin,
   `systemctl restart cloudflared`.
4. Dışarıdan doğrulama: `curl -I https://mastertool.download/web/healthz` → 200; `/web/notepadmaster/` oturumsuz → 302 `/giris?next=…`;
   `/api/tools/ssh/status` → 404.

## Testler

- `.venv/bin/python -m tests.test_mtweb` — kimlik 302/401/403, önbellek ve yalnız `sm_session` iletimi, Origin/Referer reddi,
  uzak özellik uçları 403 ve diğer araç uçları 404, kotalar (yükleme, alan, Notepad kaydı, gövde, dosya sayısı, Convert giriş
  boyutu, oran sınırı), yol kaçışı (../, mutlak, sembolik bağ), kullanıcı yalıtımı, devre dışı uygulama, /web/ yönlendirmeleri,
  bilgi sayfaları, başlıklar, 500'de sızıntı yok, denetim günlüğü (içerik yok, 90 gün).
- `tests/mtweb_fake_mt.py` — sahte hesap servisi.
- Uçtan uca: `LD_LIBRARY_PATH=… CHROMIUM_PATH=… .venv/bin/python -m tests.mtweb_e2e` — servis + sahte hesap yerel portta,
  Playwright ile Notepad'de dosya oluştur/kaydet, Convert'te png→jpg, bilgi sayfası; CSP ihlali yok; görüntüler `/tmp/mtweb-shots`.
- HEPGO tarafı değişmedi: `CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_web`.
