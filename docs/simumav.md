# SIMUMAV — bağımsız dron simülasyon oyunu (simumav.com)

HEPGO Uçuş Simülatörü çekirdeğinin (SITL + Google 3B/gerçek arazi + dron paneli + görev/çarpışma/.bin/replay)
HEPGO'dan **bağımsız**, **mastertool.download hesap yapısıyla** çalışan, **oyun görünümünde** sürümü.
Bu belge ajanlar arasındaki sözleşmedir: veri modeli, REST yüzeyi, dizin yerleşimi, yayın. Değişiklik yapan
ajan bu dosyayı da günceller.

## 1. Mimari kararlar

- **Aynı depo, ayrı uygulama.** `app/simumav/` paketi ayrı bir ASGI uygulamasıdır (`app.simumav.main:app`).
  HEPGO'nun `app.main` uygulaması İÇE AKTARILMAZ. Simülasyon çekirdeği (`app/flightsim.py`, `flightsim_hub.py`,
  `flightsim_mission.py`, `flightsim_rec.py`, `flightsim_bin.py`, `flightsim_replay.py`, `flightsim_runs.py`,
  `sim_terrain.py`, `drone_sitl.py`, `drone_params.py`, `flightsim_models.py`) **değiştirilmeden** yeniden kullanılır;
  HEPGO'ya özgü bağımlılıkları (kullanıcı/yetki/DB) `app/simumav/bridge.py` adaptörüyle sağlanır.
- **Kimlik: mastertool.download hesap servisi**, uygulama kodu **`sv`** (`sm` SSH Master'a ait, ÇAKIŞIR) (`central/sshmaster_server/sshm/main.py`
  `GAMES['sv'] = {'name': 'SIMUMAV', 'slug': 'simumav', 'icon': 'simumav', 'site': 'https://simumav.com'}`).
  Kayıt/giriş/şifre sıfırlama uçları zaten genel: `POST /api/sv/auth/prelogin|register|login|logout|forgot|reset/{tok}`
  (VOLFAI `vf` ile aynı akış: istemci PBKDF2 `computeAuthHash`, bkz. `static/mt/volfai/js/account.js` eski sürümü
  `/tmp/volfai/src/js/account.js`). Kullanıcı profili: `sv_profiles(user_id, profile JSON, updated_at)` (vf_profiles kalıbı)
  — yalnız hesap servisinde görünen özet (pilot adı, toplam uçuş, saat) için; asıl oyun verisi simumav DB'de.
- **SIMUMAV oturumu:** tarayıcı önce hesap servisine (`https://mastertool.download/api/sv/auth/login`, CORS: Origin
  `https://simumav.com` izinli) giriş yapar, dönen belirteci `POST /api/session` ile simumav'a verir; simumav belirteci
  hesap servisinde `GET /api/sv/account` (Bearer) ile doğrular, kullanıcıyı `users` tablosuna eşler (mt_user_id, email,
  display_name) ve **kendi HttpOnly çerezini** (`smsid`, 30 gün, Secure, SameSite=Lax) açar. Çıkış ikisini de kapatır.
  Geliştirmede `SIMUMAV_DEV_LOGIN=1` iken `POST /api/session {dev_user:'ad'}` hesap servisine gitmeden oturum açar.
- **Veri:** `SIMUMAV_DATA_DIR` (PROD `/opt/hepgo/simumav-data`, DEV `/tmp/simumav-data`), DB `simumav.db` (sqlite,
  WAL), dosyalar `files/` (bin, video, modeller, önizlemeler). Tablolar §3.
- **Yayın:** systemd `hepgo-simumav` (User=hepgo, `SIMUMAV_UDS=/run/hepgo/simumav.sock`, WorkingDirectory
  `/opt/hepgo/caymazbuild`, ExecStart `run-simumav.sh`), cloudflared ingress `simumav.com` + `www.simumav.com` →
  `unix:/run/hepgo/simumav.sock`. DNS: Cloudflare'da CNAME `simumav.com`/`www` → `294f79b9-1cf7-4cbc-b806-a7f70a1e0404.cfargotunnel.com`
  (proxied) — **kullanıcı panelden ekler**. Google Maps anahtarı referrer listesine `simumav.com` **kullanıcı ekler**.
- **Çevre:** `.env` ortak (`/opt/hepgo/caymazbuild/.env`: GOOGLE_MAPS_API_KEY, SIMUMAV_SECRET, SIMUMAV_MT_URL=
  https://mastertool.download, SIMUMAV_MT_INTERNAL=http://127.0.0.1:8095 — sunucu-sunucu doğrulama iç adresten).
- **Mission Planner bağlantısı:** uçuş başına **TCP** dinleyici (`SIMUMAV_MP_PORT_BASE=15600`, 15600–15999), yalnız
  ilk bağlanan istemcinin IP'si kilitlenir (sonraki farklı IP'ler reddedilir), uçuş bitince kapanır; arayüzde
  `tcp:<sunucu>:<port>` gösterilir. UDP açılmaz.

## 2. Dizin yerleşimi

```
app/simumav/            main.py (ASGI, static mount, CSP), config.py, db.py (şema+migrasyon), auth.py (hesap servisi
                        istemcisi + çerez), bridge.py (flightsim çekirdeği adaptörü: SimSession yaşam döngüsü, MP TCP,
                        kayıt → flights), routers/{session,hangar,crew,tracks,missions,fly,ops,settings}.py
run-simumav.sh          run.sh kalıbı (UDS ya da port 8600)
deploy/simumav/         hepgo-simumav.service, cloudflared-ingress.yml (eklenecek parça)
static/simumav/site/    tanıtım sitesi (index.html + css/js/img; çok dilli; register/login)
static/simumav/app/     oyun arayüzü (index.html, app.js, modüller hangar/crew/tracks/missions/fly/ops/settings,
                        ui/transition.js, i18n/*.json, theme.css)
static/simumav/brand/   ikon (SVG kaynak + 32/64/180/512 PNG), og görseli, modül ikonları
static/simumav/vendor → three.js ve xterm vb. için HEPGO `static/vendor` aynen kullanılır (mount: /vendor → static/vendor)
static/simumav/sim/  → HEPGO simülatör ön yüz modülleri (`static/js/modules/flightsim*.js`, `flightsim_g3d.js`, `replay3d.js`)
                        aynen yeniden kullanılır (mount: /sim → static/js/modules); `api.js` yerine `static/simumav/app/simapi.js`
                        (aynı dışa aktarımlar: get/post/put/del/ws/upload) — modüller `./api.js` import ettiği için
                        `/sim/api.js` yolu simumav uygulamasında `simapi.js`'e yönlendirilir (route ile).
tests/test_simumav.py   REST + oturum + bridge (SITL yok) · tests/test_simumav_ui.mjs
```

## 3. Veri modeli (sqlite; tüm tablolarda `user_id` → users.id, `created_at/updated_at` ISO)

- `users(id, mt_user_id UNIQUE, email, display_name, avatar, lang 'tr', theme 'dark', settings JSON, last_login)`
- `pilots(id, user_id, name, character TEXT ('p01'…'p10'; 'p01' = pilot şapkalı erkek), is_default 0/1, flights INT, hours REAL)`
  — kayıtta otomatik `p01` + ad = hesap adı, is_default=1.
- `drones(id, user_id, name, type ('multirotor'|'plane'|'heli'|'fpv'|'interceptor'|'vtol'), model_key (flightsim_models
  anahtarı ya da 'proc:<şablon>'), params JSON (SITL parametre farkları; interceptor: ARSPD_FBW_MAX 170 m/s ≈ 600 km/h,
  THR_MAX 100, hızlı rate PID'ler), color, preview (dönen 3B için GLB yolu), is_default)`
  — kayıtta otomatik **1 hazır FPV dron** (`type 'fpv'`, model 'proc:quad250', ad "FPV-1").
- `tracks(id, user_id, name, lat, lon, alt_mode 'terrain', radius_m, wind {speed_ms, dir_deg, gust}, time_of_day, weather,
  world_mode ('real'|'google3d'|'procedural' — HEPGO'daki üç kip: Gerçek arazi / Google 3B / Prosedürel; varsayılan 'google3d'),
  world JSON (HEPGO WORLD_DEFAULTS alanları: size_m, trees_pct, extra_buildings, fog_pct, runway_deg, runway, time_of_day),
  gates JSON (FPV HALKALARI: [{i, lat, lon, agl_m, yaw_deg, radius_m, kind:'ring'|'gate'}] ≤ 50; yarıçap 1–20 m; parkur yarıçapı
  içinde; yalnız 3B kiplerde çizilir — her üç kip de 3B'dir), preview_png, is_default)`
  — kayıtta otomatik **TRTEST** (TR TEST Kalecik: lat 40.0990, lon 33.4101; ajan doğrular), is_default=1.
- `missions(id, user_id, track_id, name, kind ('corridor'|'free'|'spray'|'fpv_flags'|'fpv_gates'|'survey'), — `fpv_gates`: parkurun halkalarını sırayla geçme (plan: {order:[gate i…], laps}), plan JSON (waypoint'ler +
  tür parametreleri; HEPGO flightsim_mission ile uyumlu `route` biçimi), preview_png)`
- `flights(id, user_id, pilot_id, drone_id, track_id, mission_id NULL, launch ('wheels'|'ramp'|'vehicle'|'hand'), started_at,
  ended_at, duration_s, result ('ok'|'crash'|'abort'), summary JSON (flightsim_mission summary), bin_path, video_path,
  params_path, mp_port, replay_cache)` — Operasyon modülünün kaynağı.
- `sim_runs_link(flight_id, sim_id)` — çalışan SimSession eşlemesi (bellekte de tutulur).

## 4. REST yüzeyi (`/api/...`; JSON; hata `{detail:{error,message}}`; oturum zorunlu — `session` hariç)

- `POST /api/session {token}` | `{dev_user}` → `{user}`; `GET /api/session` → `{user, pilots_count, ...}`; `DELETE /api/session`
- `GET/PUT /api/settings` → `{lang, theme, sound, analog_fpv, ...}`
- `GET /api/hangar` → `{drones:[…]}`; `POST /api/hangar {name,type,model_key,params?,color}`; `PUT/DELETE /api/hangar/{id}`;
  `GET /api/hangar/catalog` → `{types:[{key,label,models:[{key,label,glb,thumb,defaults}]}]}` (flightsim_models + proc şablonları)
- `GET /api/crew`; `POST /api/crew {name, character}`; `PUT/DELETE /api/crew/{id}`; `GET /api/crew/characters` → 10 karakter
  `{key, label, gender, svg}`
- `GET /api/tracks`; `POST /api/tracks {name,lat,lon,radius_m,wind,time_of_day,weather}`; `PUT/DELETE /api/tracks/{id}`;
  `GET /api/tracks/{id}/preview.png`
- `GET /api/missions`; `POST /api/missions {track_id,name,kind,plan}`; `PUT/DELETE /api/missions/{id}`
- `POST /api/fly/start {drone_id, pilot_id, track_id, mission_id?, launch, record:{video,bin}}` → `{flight_id, sim_id, mp:{host,port,proto:'tcp'}, ws}`
  `GET /api/fly/{flight_id}` durum; `POST /api/fly/{flight_id}/stop`; `WS /ws/fly/{sim_id}` (HEPGO `/ws/drone/live` ile aynı
  mesaj biçimi; flightsim_panel.js değişmeden çalışır)
- `GET /api/ops` → `{flights:[… + track.preview_png, drone.preview, pilot]}`; `GET /api/ops/{id}` (summary, replay hazır mı);
  `GET /api/ops/{id}/replay` (flightsim_replay çıktısı; .bin'den); `GET /api/ops/{id}/bin` indirme; `DELETE /api/ops/{id}`
- `GET /api/meta` → `{maps_key, version, mt_url, lang_list}`

## 5. Oyun arayüzü ilkeleri

- Tam ekran "oyun" kabuğu: web sayfası değil; üst bant yok, sol altta küçük kullanıcı çipi, sağ üstte ayarlar dişlisi.
  Ana menü: 6 büyük kart (Hangar · Mürettebat · Parkur · Görevler · Uç · Operasyon) 3B/parallax arka plan üzerinde; kartlar
  hover'da yükselir; geçişler sahne geçişi gibi (perde/ışık süpürme, 350–600 ms, `prefers-reduced-motion` saygılı).
- Hangar: ortada dönen 3B model (three.js, HEPGO vendor), "+" devasa düğme → tür kartları yarış oyunu araç seçimi gibi
  yatay kaydırma + ok tuşları; isim ver → kaydet → hangara iner (animasyon).
- Mürettebat: 10 karakter (SVG, p01 pilot şapkalı erkek, en az 4 kadın) kart; seçim + isim.
- Parkur: TRTEST hazır; yeni parkur: konum (Google harita tıkla / ara), **dünya kipi 3 seçenek** (Gerçek arazi · Google 3B ·
  Prosedürel — HEPGO sihirbazındaki "Dünya" adımının oyun görünümlü karşılığı: dünya boyutu, ağaç sıklığı, ek bina, sis, rüzgâr
  hızı/yönü, pist yönü/pist, saat Gündüz/Akşam/Gece), **FPV halkaları editörü**: harita/3B önizleme üstünde tıklayarak halka ekle
  (sıra numarası, yükseklik AGL, yön, yarıçap, tür halka/kapı; sürükle-taşı, sil), halkalar 3B önizlemede çizilir; kart üstünde
  dönen mini 3B arazi (gerçek arazi karosu + uydu dokusu) + halkalar.
- Uç: parkurun halkaları sahnede çizilir (neon halka/kapı, sıradaki halka vurgulu, geçilen yeşil), geçiş algılama (dron merkezi
  halka düzleminden yarıçap içinde geçti), OSD/HUD'da sıradaki halka oku + mesafe + tur sayacı + süre; uçuş özetine halka
  istatistiği (geçilen/kaçırılan, en iyi tur).
- Görevler: "+" → parkur seç (kartlar) → isim → tam ekran Cesium (HEPGO routes.js'teki Cesium kullanımıyla aynı kaynak)
  üstünde görev araçları: koridor, serbest, ilaçlama dilimleme, FPV bayrak, tarama. `plan` HEPGO görev biçimi.
- Uç: sihirbaz (dron → parkur → kalkış yöntemi [sabit kanatta: rampa/araç/tekerlek/**elden atış**] → görev opsiyonel →
  BAŞLA) → mevcut HEPGO simülasyon sahnesi + dron paneli + HUD/FPV birebir; MP TCP bilgisi panelde.
- Operasyon: büyük kartlar (parkur görseli + dronun dönen 3B'si + tarih + pilot); tıkla → replay (HEPGO replay dünyası).
- Ayarlar: tema (koyu/açık/otomatik), dil (tr, en, de, fr, es, ru, ar), ses, FPV analog efekt, hesap bilgisi, çıkış.
- Dil dosyaları `static/simumav/app/i18n/<lang>.json`; tanıtım sitesi de aynı dilleri destekler.

## 7. Güvenlik (BAĞLAYICI — sistem tüm dünyaya açık olacak, kötü niyetli kullanıcı varsayılır)

- **Tam yalıtım:** ayrı süreç, ayrı DATA_DIR, ayrı DB. HEPGO ERP veritabanına/dosyalarına HİÇBİR erişim yok; `app.main`,
  `app.db`, HEPGO `config.DATA_DIR` içe aktarılmaz. flightsim çekirdeğine verilen yollar yalnız SIMUMAV_DATA_DIR altındadır.
  SITL süreçleri `hepgo` kullanıcısıyla, çalışma dizini uçuş başına geçici klasör, bitince silinir.
- **Kimlik:** belirteç yalnız sunucu-sunucu doğrulanır (iç adres 127.0.0.1:8095); e-posta doğrulanmamış hesap oyuna giremez
  (`verified` alanı). Çerez `HttpOnly; Secure; SameSite=Lax`; oturum kimliği 32 bayt rastgele, DB'de hash'li; 30 gün + boşta 7 gün.
  Her durum değiştiren istekte `Origin`/`Sec-Fetch-Site` denetimi (CSRF). WS açılışında çerez doğrulanır, uçuş sahibi değilse kapanır.
- **Girdi:** tüm gövdeler pydantic; dize uzunlukları (ad ≤ 40, açıklama ≤ 500), sayısal aralıklar (lat/lon, radius 200–5000 m,
  rüzgâr 0–30 m/s), enum'lar sıkı. `params` yalnız **beyaz liste** parametre adları (drone_params hariç listesi + izin verilen
  ARSPD_*/THR_*/TKOFF_*/PTCH_*/RLL_*/WP_*/… listesi) ve sayısal aralık; Lua/script, SERIAL*, LOG_*, SYSID*, BRD_*, dosya yolu
  içeren hiçbir parametre kabul edilmez. Görev planı ≤ 500 nokta, parkur yarıçapı içinde. Dosya adları/yolları kullanıcıdan
  alınmaz; indirmeler yalnız DB'deki yollardan, `files_root` dışına çıkış reddedilir. Yükleme yok (v1).
- **Kaynak kotaları:** kullanıcı başına aynı anda 1 uçuş; uçuş süresi ≤ 45 dk (otomatik durdurma); sunucu genel eşzamanlı
  uçuş sınırı `SIMUMAV_MAX_FLIGHTS` (varsayılan 6) — dolu ise "bekleme odası" yanıtı (429 + tahmini süre). Hangar ≤ 20 dron,
  mürettebat ≤ 20 pilot, parkur ≤ 20, görev ≤ 50, saklanan uçuş ≤ 100 (en eskisi silinir; .bin ≤ 50 MB, video ≤ 300 MB).
  Disk kotası kullanıcı başına 1 GB.
- **Oran sınırlama:** IP + kullanıcı bazlı (bellek içi token bucket): `/api/session` 10/dk/IP, yazma uçları 60/dk/kullanıcı,
  okuma 300/dk, WS mesaj 100/sn; aşımda 429. Hesap servisindeki login/register oran sınırı korunur.
- **MP TCP:** rastgele port (aralıktan), ilk bağlanan IP kilidi, aynı anda tek bağlantı, 60 sn bağlanılmazsa kapanır, uçuş
  bitince kapanır; MAVLink akışı yalnız o uçuşun SITL'ine. Portlar güvenlik duvarında yalnız aralık olarak açık.
- **Başlıklar/CSP:** `default-src 'self'; script-src 'self' https://maps.googleapis.com https://*.cesium.com; connect-src 'self'
  https://mastertool.download https://maps.googleapis.com https://*.googleapis.com https://*.cesium.com https://*.arcgisonline.com
  https://*.amazonaws.com wss://simumav.com; img-src 'self' data: blob: https:; frame-ancestors 'none'; object-src 'none'`,
  `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`. Inline script yok.
- **Günlük/denetim:** oturum açma/kapama, uçuş başlat/durdur, kota/oran aşımı, reddedilen parametre/plan → `audit` tablosu
  (IP, user, olay, ayrıntı); hata yanıtları iç ayrıntı sızdırmaz (traceback yok, genel mesaj). Google anahtarı yalnız
  `/api/meta` ile oturumlu kullanıcıya verilir (referrer kısıtı Cloudflare tarafında ek koruma değildir — kullanıcı anahtar
  kısıtına simumav.com ekler).
- **Hesap servisi tarafı:** `sv` için CORS yalnız `https://simumav.com`; register'da e-posta doğrulama zorunlu; `sv_profiles`
  yazımı yalnız simumav sunucusundan (paylaşılan gizli `SIMUMAV_MT_SHARED_SECRET` başlığı) ya da kullanıcı Bearer'ı ile.
- **Bağımlılıklar:** three.js/xterm vendor'dan (CDN yok); Cesium ve Google yalnız resmi alanlar. `npm`/pip yeni paket gerekirse
  raporda belirtilir, kurulmaz.

## 6. Yayın ve doğrulama

1. `deploy/simumav/hepgo-simumav.service` kopyala → `systemctl enable --now hepgo-simumav`; `.env`'e SIMUMAV_* ekle.
2. cloudflared `config.yml` ingress'e `simumav.com`, `www.simumav.com` → `unix:/run/hepgo/simumav.sock`; `systemctl restart cloudflared`.
3. Kullanıcı: Cloudflare DNS CNAME (tünel) + Google anahtarı referrer `simumav.com`.
4. Hesap servisi: `GAMES['sv']` + `sv_profiles` tablosu + CORS Origin `https://simumav.com` → hepgo-sshmasters restart;
   mastertool.download › Oyunlar listesinde SIMUMAV (ikon `static/brand/simumav.svg|png`, tanıtım bağlantısı simumav.com).
5. Dışarıdan: `https://simumav.com/` tanıtım 200, `/app` oturumsuz → tanıtım/giriş; `/api/meta` 200; MP TCP portu dış IP'den
   yalnız kilitli IP ile.

### 6.1 Yayın akışı (HEPGO → goktalay/simumav → mastertool.download → sunucu)

- **Kaynak HEPGO deposudur.** `tools/simumav_export.py [--dest ~/mt-work/simumav] [--version X.Y.Z] [--dry-run]` SIMUMAV çalışır
  ağacını üretir: manifest (`app/simumav/**`, flightsim çekirdeği, `static/simumav/**`, `static/js/modules/flightsim*.js`
  + `replay3d.js` + `flightsim_g3d.js`, `static/vendor/three|xterm/**`, `run-simumav.sh`, `deploy/simumav/**`, `docs/simumav.md`,
  `tests/test_simumav*`) + AST ile çözülen `from . import` zinciri + JS göreli import zinciri (+ `/vendor/<ad>/` başvuruları).
  `app/main`, `app/db`, `app/config`, `app/feed`, `app/drone_hub`, `app/flightlog`, `app/flight_analysis` gibi HEPGO'ya özgü
  modüller zincirde çıkarsa **UYARI verilir ve kopyalanmaz** — çekirdek bunları `app/simumav/bridge.py` ile (ör. `sys.modules`
  enjeksiyonu ya da çekirdekte `try: from . import db` yedekleri) almalıdır. `./api.js` kopyalanmaz (`simapi.js`, §2).
  Üretilenler: `requirements.txt` (yalnız gerçekten import edilen üçüncü parti paketler, HEPGO sürüm kısıtlarıyla; uvicorn her
  zaman), `VERSION`, `README.md`, `.gitignore`. Hedefte `.git`, `.github`, `scripts`, `CHANGELOG.md` korunur, geri kalanı silinir.
  Test: `tests/test_simumav_export.py`.
- **goktalay/simumav** (main): `git tag vX.Y.Z && git push origin vX.Y.Z` → `.github/workflows/release.yml` (ubuntu, python 3.12):
  pip, pyflakes + `node --check`, `python -m tests.test_simumav` (SITL yok), `simumav-X.Y.Z.tar.gz` (deterministik tar; `.github`,
  `scripts`, `dist`, `.venv`, `.env*` hariç; `VERSION` içinde) + `.sha256`, ≤ 95 MB denetimi, GitHub Release (softprops v2),
  `scripts/upload-mastertool.sh` → hesap servisi. `ci.yml` her push/PR'da pyflakes + node --check + testler.
- **Sunucu (root):** `deploy/simumav/hepgo-simumav-deploy.path` `data/releases/sv/latest` değişimini izler →
  `hepgo-simumav-deploy.service` → `deploy/simumav/deploy.sh`: sha256 → gzip/yol/symlink denetimi → `/opt/hepgo/simumav.new`
  → `.venv` (requirements hash değiştiyse pip) → `simumav.prev` yedeği → `rsync -a --delete --exclude .venv --exclude .env`
  → `chown -R root:root` → `systemctl restart hepgo-simumav` → `curl --unix-socket /run/hepgo/simumav.sock http://x/api/meta`
  200 değilse **önceki sürüme geri döner**. Günlük `/var/log/hepgo-simumav-deploy.log`. `.env` (`/opt/hepgo/simumav/.env`,
  `EnvironmentFile`) hiç dokunulmaz. Ayrıntı `deploy/simumav/README.md`.

### 6.2 Hesap servisi ucu: `POST /api/sv/web-releases` (çekirdek ajanı yazar; sözleşme bağlayıcı)

- Kimlik: `X-Release-Key` başlığı; `settings.RELEASE_KEYS['sv'] = os.environ.get('SIMUMAV_RELEASE_KEY', '')`;
  `hmac.compare_digest`; anahtar tanımsız ya da uyuşmuyorsa 403 (`_release_auth` kalıbı; merkez oturumu da geçerli).
- Form (multipart): `version` (zorunlu; `VERSION_RE`, baştaki `v` atılır → aksi 422 `invalid_version`), `package` (zorunlu;
  dosya ≤ **95 MB** → aksi 422 `too_large`/413; ilk 2 bayt `1f 8b` gzip imzası → aksi 422 `not_gzip`), `sha256` (zorunlu; hex 64;
  sunucuda hesaplananla eşleşmeli → aksi 422 `bad_sha256`).
- İçerik denetimi (`tarfile`, açılmaz, yalnız listelenir): her üye adı normalize edilir; mutlak yol, `..` bileşeni, sembolik/sert
  bağ (`issym()/islnk()`), aygıt/fifo üyesi → 422 `unsafe_archive`. Kökte (`VERSION` ya da `./VERSION` ya da tek kök klasör
  altında) `VERSION` üyesi okunur ve `version` ile eşleşmeli → aksi 422 `version_mismatch`. `requirements.txt` ve `run-simumav.sh`
  yoksa 422 `incomplete`.
- Aynı sürüm varsa **409 `exists`** (dosya ve DB kaydı dokunulmaz). Kayıt: `data/releases/sv/<v>/simumav-<v>.tar.gz` +
  `simumav-<v>.tar.gz.sha256` (`<sha>  simumav-<v>.tar.gz` biçimi) — hepgo kullanıcısı 0644; `web_releases(id, app, version,
  file, size, sha256, created_at, created_by)` tablosu (INSERT; `UNIQUE(app, version)`); son olarak `data/releases/sv/latest`
  dosyasına `<v>\n` **atomik** yazılır (`latest.tmp` + `os.replace`) — path unit bunu izler. Hata halinde sürüm klasörü silinir,
  `latest` değişmez.
- Yanıt 201 `{ok, version, sha256, size}`. `GET /api/sv/web-releases/latest` → `{version, sha256, size, created_at}` (açık; dışarıdan
  doğrulama için). Oran sınırı: anahtarlı uçta 10/dk/IP.
- İsteğe bağlı parçalı uç `POST /api/sv/web-releases/{version}/part` (`file, part, parts, sha256`; `/api/{a}/releases/{version}/{kind}`
  kalıbı; son parçada yukarıdaki denetimlerin tümü). `scripts/upload-mastertool.sh` paket > 90 MB ise bunu kullanır; v1'de paket
  küçük kalmalı (vendor three ~2 MB, xterm ~0.3 MB), uç yoksa büyük paket yüklemesi başarısız olur.
