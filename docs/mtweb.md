# mtweb — Mastertool web uygulamaları

Mastertool hesabıyla (mastertool.download) giriş yapan kullanıcılara masaüstü uygulamaların web sürümleri:
**Notepad Master**, **Convert Master** (aşama 1) ve **SSH Master**, **FTP Masters**, **SQL Master** + Notepad'in SSH/FTP uzak
klasörleri (aşama 2). HEPGO'da "Araçlar" altında çalışan aynı ön yüz (`static/mt/<app>/`) ve aynı arka uç (`app/routers/tools_*.py`)
KOPYALANMADAN ayrı bir ASGI servisinde (`app/mtweb/`) çalışır.

Dosyalar kullanıcının kendi alanındadır. Aşama 2 uygulamaları sunucudan kullanıcının kendi sunucularına bağlantı açar; her dış
bağlantı **guard.py** (SSRF koruması, oran ve eşzamanlılık sınırı, denetim) üzerinden geçer — bkz. §Dış bağlantılar. Convert'in
konuşma/OCR model indirme uçları kapalıdır (403).

## Mimari

```
tarayıcı ──► Cloudflare ──► cloudflared ──┬─ ^/(web|static/mt|api/tools|ws/tools)(/|$) ──► unix:/run/hepgo/mtweb.sock  (hepgo-mtweb)
                                          └─ diğer her şey ───────────────────────► hesap servisi (127.0.0.1:8095)
hepgo-mtweb ── GET /api/mt/me (Cookie: sm_session) ──► hesap servisi (MTWEB_ACCOUNT_URL)
```

| Dosya | Görev |
|---|---|
| `app/mtweb/config.py` | Ortam; **ilk** içe aktarılır: `CAYMAZ_DATA_DIR`/`CAYMAZ_DB`'yi mtweb veri dizinine zorlar (HEPGO `data/` seçilirse açılmaz) |
| `app/mtweb/main.py` | FastAPI uygulaması: güvenlik ara katmanı, sayfalar, HEPGO araç router'larının dahil edilmesi |
| `app/mtweb/auth.py` | Hesap servisi istemcisi (60 sn önbellek), Origin denetimi, oran sınırı |
| `app/mtweb/quota.py` | Alan/dosya/yükleme kotaları, Convert iş kapısı, SQLite koruması; HEPGO router kancalarını kurar (`install()`) |
| `app/mtweb/guard.py` | Dış bağlantı koruması: `resolve_target` (NET kancası: SSRF + oran + denetim), `acquire` (eşzamanlı oturum) |
| `app/mtweb/db.py` | Küçük şema: `users`, `tools_mt_store`, `app_kv`, `audit_logs`, `mtweb_audit` (+ `host`, `rip`, `port`, `result`) |
| `static/mt/common/mtweb.js`, `mtweb.css` | Üst şerit, site dili, oturum düşünce girişe yönlendirme, bilgi sayfası metinleri |

**Kullanıcı:** `tools_common.tools_user` bağımlılığı `app.dependency_overrides` ile Mastertool kullanıcısına çevrilir. mtweb
DB'sinde her hesap kimliğine (`mt_id`) bir `users` satırı açılır; araç kodu bu yerel `id` ile çalışır
(`DATA_DIR/tools/<app>/<id>/…`).

**HEPGO'daki küçük kancalar** (varsayılanları HEPGO davranışını değiştirmez):

| Modül | Kanca |
|---|---|
| `tools_common` | `BRAND` (alan etiketi; mtweb'de "Mastertool"); `NET_GUARD(host, port, uid, app, kind)` → doğrulanmış IP (`net_target` / `net_socket`); `CONN_GATE(uid, app)` → release (`conn_slot`); `WS_USER(ws)` (WebSocket kimliği); `NetDenied` |
| `tools_ssh` | `KNOWN_HOSTS(uid)` (kullanıcı başına known_hosts); `connect_client` kanca varken hazır soketle bağlanır; indirme kotası (`job['space']`) |
| `tools_ftp` | `POOL_MAX` (site başına aktarım bağlantısı); `harden_ftp` (PASV IP'si yok sayılır, PASV portu denetlenir, PORT kapalı) |
| `tools_sql` | `APP_DB_READONLY` (False → caymaz.db istisnası yok), `ALLOW_SSH_AGENT`, `SQLITE_GUARD`, `EXPORT_MAX`, `ROW_LIMIT_MAX`, `PUBLIC_PATH`; PG `hostaddr` / MySQL hazır soket |
| `tools_notepad` | `ALLOW_REMOTE` (mtweb'de True; bağlantılar NET kancasından geçer), `REMOTE_GUARD`, `WRITE_GUARD` (kota; çalışma kopyası dahil), `PUBLIC_PATH` |
| `tools_mt` | `UPLOAD_GUARD` (parça parça kota; H:\ yüklemesi ve SSH/FTP indirmeleri de), `space_check`, `safe_segment` / `safe_join` (uzak / istemci adı yerel alandan kaçamaz), `MAX_UPLOAD` |
| `tools_convert` | `JOB_GATE` (eşzamanlılık/giriş boyutu/kota), `FFMPEG_PREFIX` (nice), `FFMPEG_THREADS`, `FFMPEG_TIMEOUT`, `MAX_CONCURRENCY` |
| `static/mt/common/hepgo.js` | `window.MTWEB` varsa: `MT.web`, dil (site dili → tarayıcı → en), "Dosyalarınız" etiketi |
| `static/mt/{notepadmaster,convertmaster,sqlmaster}/bridge.js` | `MT.web` varsa çıkış Mastertool hesabından, "web" bağlantıları mastertool.download'a |
| `static/mt/mtcore.js` (SSH/FTP) | `window.MTWEB` varsa: dil site dilinden, 401 → girişe yönlendirme, çıkış Mastertool hesabından |
| `static/mt/notepadmaster/app.js` | `MT.web.remote === false` → SSH/FTP türleri devre dışı, varsayılan tür "Lokal klasör" |

## Yollar

| Yol | Açıklama |
|---|---|
| `/web/` | Host'a göre: notepadmaster.com → `/web/notepadmaster/`, convertmaster.app → `/web/convertmaster/`, mastertool.download → `/uygulamalar`, diğerleri → `/` |
| `/web/notepadmaster/`, `/web/convertmaster/` (+ `project.html`) | Uygulama (oturum gerekir). Sunucu HTML'e `/web/config.js?app=…`, `mtweb.js`, `mtweb.css` ekler |
| `/web/sshmaster/` (+ `terminal.html?ids=…`), `/web/ftpmaster/` (+ `site.html?id=…`) | SSH Master, FTP Masters (sayfalar `config.PAGES`) |
| `/web/sqlmaster/` → `/web/sqlmaster/renderer/main/` (+ `renderer/conn/conn.html?id=…`) | SQL Master |
| `/web/config.js` | `window.MTWEB` (kullanıcı adı, uygulama, bağlantılar, `remote: true`; `no-store`) |
| `/web/mtcore.js`, `/web/vendor/xterm/*` | SSH/FTP köprü çekirdeği, terminal (xterm.js; sayfadaki `/static/vendor/xterm` yolu yeniden yazılır) |
| `/web/common/*`, `/web/<app>/*`, `/static/mt/*` | Ön yüz dosyaları (oturumsuz; kod herkese açık). Çıplak `/static/mt/**/*.html` → `/web/<app>/` |
| `/ws/tools/ssh`, `/ws/tools/ftp?id=…` | WebSocket (Origin == Host, Mastertool oturumu, boşta 30 dk / en çok 8 sa) |
| `/web/healthz` | Sağlık |
| `/api/tools/mt/account` | mtweb'e özgü hesap durumu |
| `/api/tools/mt/{notepadmaster,convertmaster}/fs/{list,mkdir,upload,download,delete,rename,usage}` | Kullanıcının dosya alanı |
| `/api/tools/mt/sqlmaster/fs/*` | SQL Master dosya alanı (SQLite dosyaları) |
| `/api/tools/mt/{sshmaster,ftpmaster}/{boot,invoke,files/upload,files/download}` | SSH/FTP Master deposu, IPC kanalları, H:\ alanı |
| `/api/tools/{notepad,convert,sql}/*`, `/api/tools/ssh/status`, `/api/tools/ftp/caps` | HEPGO uçları — beyaz liste; **403**: `convert/{speech,ocr}/download` |
| diğer `/api/*` | 404 (VOLFAI ve HEPGO'nun geri kalanı bu serviste yok) |

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
2. **Kotalar** (ortamla değişir, bkz. aşağı): kullanıcı başına dosya alanı (tüm uygulama dizinleri — files, converted, keys, SQLite, H:\\,
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
5. **Acil anahtar:** `MTWEB_DISABLED_APPS=convertmaster,sshmaster,ftpmaster,sqlmaster,…` → uygulamanın API'si 403, sayfası 503 bilgi
   sayfası, WebSocket'i reddedilir, süren oturumları yeni dış bağlantı açamaz (guard). `notepadmaster` kapalıysa uzak klasörler de kapalı.
6. **Denetim:** `mtweb_audit` (zaman, kullanıcı, uygulama, işlem, boyut, istemci IP, kısa teknik not). İçerik yazılmaz.
   İşlemler: `session`, `ws`, her yazma isteği (`notepad/proj/save`, `mt/convertmaster/fs/upload`, …), indirmeler, `convert`,
   reddedilenler (`csrf`, `blocked`, `quota`, `rate`), dış bağlantılar (`net`: `host`, `rip` = çözülen IP, `port`, `result` =
   `ok` | `dns` | `denied:private|self|port|host|rate|disabled`). Parola / komut / sorgu / dosya içeriği YAZILMAZ. 90 günden eskiler
   saatlik temizlenir.

## Dış bağlantılar (aşama 2: SSH Master · FTP Masters · SQL Master · Notepad uzak klasör)

HEPGO'da kancalar kapalıdır (firmalar LAN cihazlarına bağlanır; davranış değişmez). mtweb'de `quota.install()` kurar:

1. **SSRF** — `guard.resolve_target(host, port)`: ad DNS ile çözülür; adreslerden **biri bile** global değilse (loopback, özel,
   link-local / 169.254.169.254, CGNAT 100.64/10, çoklu yayın, ayrılmış, belirsiz, ULA / site-local v6, IPv4-mapped / 6to4 /
   Teredo / NAT64 içindeki özel adres) ya da sunucunun kendi adresiyse (`MTWEB_BLOCK_IPS`, vars. 178.157.10.114 — IP ya da CIDR —
   + yerel arabirim adresleri) ret. Port 25/465/587 + `MTWEB_BLOCK_PORTS` ret. **Bağlantı doğrulanan IP'ye yapılır** (DNS yeniden
   bağlama yok): paramiko'ya önceden açılmış soket (SSH Master, FTP Masters SFTP, Notepad SFTP, SQL SSH tüneli), ftplib'e IP;
   FTP veri kanalı PASV yanıtındaki IP yerine kontrol bağlantısının IP'sine (`trust_server_pasv_ipv4_address=False`; PASV portu da
   denetlenir), aktif kip (PORT/EPRT) kapalı; PostgreSQL `hostaddr` (host yalnız TLS adı), MySQL `defer_connect` + hazır soket
   (iptal bağlantısı da). MSSQL/DuckDB sürücüsü yok. `MTWEB_ALLOW_PRIVATE=1` YALNIZ testte özel adreslere izin verir
   (engel listesi ve port engeli yine geçerli).
2. **SSH:** yalnız kabuk + SFTP kanalı; port yönlendirme / tünel / ajan / X11 istenmez (`allow_agent=False`, `look_for_keys=False`).
   known_hosts kullanıcı başına (`DATA_DIR/tools/ssh_known_hosts.d/<uid>`), kayıtlı parmak iziyle çelişen anahtar reddedilir.
   SQL'in SSH tünelinde ajan kimliği kapalı; önce SSH sunucusu, sonra **tünel hedefi** yerelde doğrulanır ve hedef IP olarak istenir.
3. **SQLite** yalnız kullanıcı alanında (`DATA_DIR/tools/sqlmaster/<uid>/files`); `caymaz.db` (uygulama DB) istisnası kapalı.
   Yetkilendirici: `ATTACH`, `VACUUM INTO` (içte ATTACH), `DETACH`, TEMP nesneleri, `load_extension` / `readfile` / `writefile`,
   tehlikeli PRAGMA'lar (`max_page_count`, `writable_schema`, `mmap_size`, …) reddedilir. Sayfa tavanı = kalan alan kotası (bellek
   içi: `MTWEB_SQL_MEMORY_MB`); ifade süresi `MTWEB_SQL_TIMEOUT_S`. Sorgu başına `MTWEB_SQL_ROW_LIMIT` satır; dışa aktarma
   ≤ `MTWEB_UPLOAD_MB`. Ağaçtaki dosya yolu arayüze kullanıcının göreli yolu olarak gider.
4. **WebSocket** (`WsGate`, saf ASGI): `Origin` zorunlu ve host:port'u `Host` ile aynı olmalı; uygulama kapalıysa ret; istemci IP
   başına `MTWEB_WS_PER_IP`; istemciden `MTWEB_WS_IDLE_S` (30 dk) ileti gelmezse ya da `MTWEB_WS_MAX_S` (8 sa) dolunca 4408 ile
   kapanır (oturumlar ve SSH/FTP bağlantıları bırakılır). Kimlik `tools_common.WS_USER` = Mastertool oturumu (doğrulanmış hesap).
   SQL ve Notepad uzak oturumları (HTTP) aynı sürelerle süpürücüde kapanır; Notepad klasör seçicisi 15 dk.
5. **Kotalar:** kullanıcı başına uygulama başına eşzamanlı bağlantı oturumu `MTWEB_NET_USER_SESSIONS` (4: SSH bölmesi, FTP site
   penceresi, SQL bağlantı penceresi, Notepad uzak bağlantısı), genel `MTWEB_NET_SESSIONS` (300); FTP sitesi başına aktarım
   bağlantısı `MTWEB_FTP_POOL` (2); bağlantı denemesi kullanıcı `MTWEB_NET_ATTEMPTS_USER` (30) / istemci IP `MTWEB_NET_ATTEMPTS_IP`
   (60) / `MTWEB_NET_WINDOW_S` (600 sn). Aktarımlar alan kotasına sayılır: SSH/FTP indirmeleri ve H:\ yüklemeleri parça parça
   denetlenir (aşımda yarım dosya silinir), Notepad çalışma kopyası, SQLite dosyaları.
6. **Parolalar** Fernet ile (`enc:`; anahtar `DATA_DIR/tools/mt_secret.key`, 0600) saklanır; arayüze yalnız `hasPassword` gider.
7. **Ad güvenliği:** uzak sunucudan ya da istemciden gelen dosya adları (`..`, `/`, `\`, NUL) yerel alana yazılmadan reddedilir.

Kalan bilinen sınırlar: SQL editöründe `PRAGMA database_list` sunucudaki dosya yolunu gösterebilir (yalnız kullanıcının kendi
dosyası; ağaç göreli yol gösterir). Kullanıcının kendi uzak sunucusundaki işlemler (komutlar, uzak dosyalar, uzak SQL) o sunucunun
yetkisindedir.

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
| `MTWEB_BLOCK_IPS` | `178.157.10.114` | Sunucunun kendi adresleri (virgüllü IP / CIDR); yerel arabirim adresleri ayrıca otomatik |
| `MTWEB_BLOCK_PORTS` | — | 25/465/587'ye ek engelli portlar |
| `MTWEB_ALLOW_PRIVATE` | 0 | YALNIZ TEST: özel / yerel adreslere izin |
| `MTWEB_NET_USER_SESSIONS` / `MTWEB_NET_SESSIONS` | 4 / 300 | Eşzamanlı bağlantı oturumu (kullanıcı·uygulama / genel) |
| `MTWEB_NET_ATTEMPTS_USER` / `MTWEB_NET_ATTEMPTS_IP` / `MTWEB_NET_WINDOW_S` | 30 / 60 / 600 | Bağlantı denemesi oranı |
| `MTWEB_WS_IDLE_S` / `MTWEB_WS_MAX_S` / `MTWEB_WS_PER_IP` | 1800 / 28800 / 32 | WebSocket ömrü ve IP başına sayısı |
| `MTWEB_FTP_POOL` | 2 | FTP sitesi başına aktarım bağlantısı |
| `MTWEB_SQL_ROW_LIMIT` / `MTWEB_SQL_TIMEOUT_S` / `MTWEB_SQL_MEMORY_MB` | 50000 / 60 / 64 | SQL Master sınırları |
| `MTWEB_ALL_APPS_URL` / `MTWEB_DOWNLOAD_URL` | mastertool.download/uygulamalar / `/#indir` | Şerit bağlantıları |

## Dağıtım (PROD — onaysız yapılmaz)

1. `install -d -o hepgo -g hepgo -m 750 /opt/hepgo/mtweb-data`; isteğe bağlı `/opt/hepgo/mtweb-data/.env` (640 root:hepgo).
2. Kod HEPGO deposundan çalışır (`/opt/hepgo/fabrika-yonetim`, aynı `.venv`). `deploy/mtweb/hepgo-mtweb.service` →
   `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now hepgo-mtweb`.
3. `deploy/mtweb/cloudflared-ingress.yml` parçasını cloudflared `ingress:` listesine hesap servisi kurallarının ÜSTÜNE ekleyin
   (yol deseni `ws/tools` içerir), `systemctl restart cloudflared`.
4. Dışarıdan doğrulama: `curl -I https://mastertool.download/web/healthz` → 200; `/web/notepadmaster/`, `/web/sshmaster/` oturumsuz
   → 302 `/giris?next=…`; `/api/tools/ssh/status` oturumsuz → 401; `/api/tools/volfai/profile` → 404; `wss://…/ws/tools/ssh`
   yabancı Origin ile → ret.
5. Aşama 2 güncellemesi: servis birimi (`TasksMax=2048`) yeniden kopyalanır, `systemctl daemon-reload && systemctl restart
   hepgo-mtweb`; mevcut `mtweb.db`'ye denetim sütunları açılışta kendiliğinden eklenir.

## Testler

- `.venv/bin/python -m tests.test_mtweb` — kimlik 302/401/403, önbellek ve yalnız `sm_session` iletimi, Origin/Referer reddi,
  Notepad uzak bağlantısının SSRF korumasından geçmesi, beyaz liste (SSH/FTP/SQL açık, diğerleri 404), kotalar (yükleme, alan, Notepad kaydı, gövde, dosya sayısı, Convert giriş
  boyutu, oran sınırı), yol kaçışı (../, mutlak, sembolik bağ), kullanıcı yalıtımı, devre dışı uygulama, /web/ yönlendirmeleri,
  bilgi sayfaları, başlıklar, 500'de sızıntı yok, denetim günlüğü (içerik yok, 90 gün).
- `.venv/bin/python -m tests.test_mtweb_net` — aşama 2: SSRF (127.0.0.1, 10.x, 169.254.169.254, ::1, ::ffff:127.0.0.1, CGNAT,
  ULA, 6to4/NAT64, özel IP'ye çözen ad, karışık DNS, 178.157.10.114, yerel arabirim, port 25/465/587), her araçta guard (SSH,
  FTP/FTPS/SFTP, PG/MySQL — hostaddr / hazır soket, SQL SSH tüneli + ajan reddi + hedef, Notepad), FTP PASV IP'si yok sayılır +
  engelli PASV portu + PORT kapalı, WS Origin reddi / oturumsuz / boşta kapanış, eşzamanlılık + genel tavan + deneme oranı (kullanıcı,
  IP), acil anahtar, SQLite (ATTACH / VACUUM INTO / load_extension / TEMP / PRAGMA reddi, caymaz.db/mtweb.db istisnası yok, sayfa
  tavanı, süre sınırı, göreli yol), Fernet + 0600 anahtar, known_hosts kullanıcı başına, denetim (parola/komut/sorgu yok), HEPGO'da
  kancalar kapalı (ayrı süreç); yerel paramiko SSH sunucusunda WS ile komut çıktısı, SFTP listesi/indirme + kota, 5. oturum reddi,
  FTP Masters (SFTP) site listesi, `../` adı reddi.
- `tests/mtweb_fake_mt.py` — sahte hesap servisi; `tests/mtweb_sshd.py` — yerel paramiko SSH/SFTP test sunucusu;
  `tests/mtweb_ftpd.py` — küçük pasif FTP test sunucusu (PASV'de istenen IP'yi ilan eder).
- Uçtan uca: `LD_LIBRARY_PATH=… CHROMIUM_PATH=… .venv/bin/python -m tests.mtweb_e2e` — servis (`MTWEB_ALLOW_PRIVATE=1`) + sahte hesap
  + yerel SSH/FTP sunucuları; Playwright ile Notepad'de dosya oluştur/kaydet, Convert'te png→jpg, SSH Master terminalinde komut
  çıktısı, FTP Masters site listesi (PASV IP'si yok sayılır), SQL Master'da SQLite sorgusu; CSP ihlali yok; görüntüler
  `/tmp/mtweb-shots2`.
- HEPGO tarafı değişmedi: `CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_web`.
