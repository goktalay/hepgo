# CAYSIM / Simumav (UE5) — yol haritası API eki (simumav.com sunucusu)

Bu dosya `~/mt-work/caysim/docs/caysim-api.md`'ye eklenecek bölümdür (CAYSIM ajanı kendi deposuna taşır). Kaynak sözleşme: HEPGO deposu
`docs/simumav.md` §30 (kod buna birebir uyar). Yol haritası: `~/mt-work/caysim/docs/yol-haritasi.md`.

> Bu uçlar **simumav.com** (`app/simumav`) sunucusundadır — HEPGO `/api/caysim/v1` yüzeyi DEĞİL. UE istemcisi bunları "girişli (bulut)" kipte kullanır.

## A. Bağlantı, kimlik, hata biçimi

- Taban: `https://simumav.com` (geliştirme: `http://127.0.0.1:8600`, `SIMUMAV_DEV_LOGIN=1` iken `POST /api/session {dev_user}`).
- Giriş: Mastertool (mastertool.download) belirteci → `POST /api/session {token}` → `Set-Cookie: smsid=…` (HttpOnly). İstemci çerezi saklar ve her istekte
  `Cookie: smsid=<değer>` gönderir. 30 gün / 7 gün boşta geçerli. `GET /api/session` aynı gövde; `DELETE /api/session` çıkış.
- **CSRF**: POST/PUT/DELETE isteklerinde `Origin: https://simumav.com` başlığı ZORUNLU (yoksa 403 `csrf`). Okuma isteklerinde gerekmez.
- Oran: yazma 60/dk/kullanıcı, okuma 300/dk; aşımda 429 `rate_limited` + `Retry-After`.
- Hata: `{"detail": {"error": "<kod>", "message": "<Türkçe metin>", …ek alanlar}}`; doğrulama 422 `invalid` (`fields` listesi). Başkasının kaydı = 404.
- Zaman damgaları yerel ISO (`2026-10-24T10:27:14`); kimlikler tamsayı.

## B. Oyun türleri — Uçuş › Oyun türü

`GET /api/modes?lang=tr` →
```json
{"modes":[{"id":"rings","label":"Halka toplama","labels":{"tr":"…","en":"…"},"engine":"match","match_kind":"rings","mission_kind":null,
  "defend":false,"multiplayer":true,"players":[1,8],"types":["multirotor","fpv","plane","interceptor","heli","vtol"],"requires":{},
  "ai":{"single":0,"recommended":2,"max":7,"kind":"pilot"},"scoring":[{"key":"ring","points":"…"}],"engagement":null}, …],
 "engagement_rule":"hud_lock_only","mail_enabled":true}
```
| id | Motor | Başlatma | Çok oyunculu | Tek oyunculuda AI |
|---|---|---|---|---|
| `free` Serbest uçuş | fly | `POST /api/fly/start {…, mode:'free'}` | yok | 0 |
| `rings` Halka toplama | match | `POST /api/match/solo {mode:'rings', kind?:'rings'|'fpv'}` (tek) · `POST /api/match {mode:'rings', …}` (çok) · `/api/match/ai` | evet (≤ 8) | 0 (isteğe bağlı AI) |
| `cargo_drop` Yük bırakma | fly | `fly/start {mode:'cargo_drop'}` (önerilen eklenti: gripper) | yok | 0 |
| `spraying` Tarla ilaçlama | fly | `fly/start {mode:'spraying', mission_id? (kind spray)}` (eklenti: sprayer; kopter/heli) | yok | 0 |
| `dogfight` İt dalaşı | match | tek: `POST /api/match/ai {mode:'dogfight'}` (1 AI otomatik) · çok: `POST /api/match {mode:'dogfight', max_players:2}` | evet (2) | 1 |
| `facility_defense` Kritik tesis savunma | fly | `fly/start {mode:'facility_defense', defend?:{waves, difficulty…}}` — yalnız INTERCEPTOR | yok | gelen hedef dronlar (sunucu) |
| `ship_defense` Gemi savunma | fly | aynı (+ istemci gemi sahnesi; parkurda su) | yok | gelen hedef dronlar |

- `GET /api/modes/{id}/ai?players=1&waves=3` → `{"mode","kind":"pilot"|"target_drone","count":n,"auto":bool}` — UE "Tek oyunculu" seçince bu sayıda AI ekler
  (karşılaşma türlerinde `/api/match/ai` `bots` alanını vermezse sunucu da aynı öneriyi kullanır).
- Yanlış motor (ör. `fly/start mode:'rings'`) / araç tipi uymuyor → 422. `mode` ile `kind` çelişkisi 422.
- **Angajman kuralı (bağlayıcı)**: savunma ve it dalaşı puanı yalnız oyuncunun HUD kilidi (Boşluk / kumanda `lock`) + temas/yakın geçiş sayımıdır;
  UE'de otonom güdüm, otomatik nişan ya da hedefe kendiliğinden yönelme UYGULANMAZ.
- Karşılaşma anlık görüntüsünde (`GET /api/match/{id}`, WS `match`) yeni alanlar: `mode`, `max_vehicles` (insan + AI araç tavanı).

## C. Çok oyunculu — e-posta daveti + arkadaşlardan seçme

Akış (kurucu): `POST /api/match {drone_id, track_id, password, max_players, mode}` → 201 `{id, code, …}` (mevcut davet kodu + şifre akışı aynen sürer) →
`POST /api/match/{id}/invites {"emails":["a@b.com"], "friend_ids":[12]}` →
```json
{"invites":[{"id":5,"match_id":3,"email":"a***@b***.com","state":"pending","mail":"queued|sent|disabled|failed","created_at":"…","expires_at":"…",
  "link":"https://simumav.com/app/#/match/invite/<32 karakter>"}],
 "skipped":[{"email":"…","reason":"self|duplicate|recipient_limit"}],"mail_enabled":true,
 "limits":{"per_request":25,"per_match":50,"daily":100,"ttl_h":24}}
```
- İstediği kadar davet: tek istekte ≤ 25, karşılaşma başına ≤ 50 (409 `invite_limit`), 24 saatte ≤ 100 (429 `invite_daily`), 10 istek / 10 dk.
- `mail_enabled:false` ise e-posta GİTMEZ; UE `link`'i kurucuya "Bağlantıyı kopyala / paylaş" olarak göstermeli.
- `GET /api/match/{id}/invites` (kurucu: durum listesi, `link` yok) · `DELETE /api/match/{id}/invites/{iid}` (geri al).
- AI ekleme: salonda `POST /api/match/{id}/bot {level: easy|normal|hard}` — insan sınırına sayılmaz; tavan `max_vehicles` (sunucu SITL tavanı, 409 `full`).
- Davetler yalnız salonda (`LOBI`); karşılaşma başlayınca bekleyen davetler `expired`.

Akış (davetli, oyun içi): `GET /api/invites` (periyodik, ör. 30 sn ya da menü açılışında) →
```json
{"invites":[{"id":5,"match_id":3,"state":"pending","inviter":{"name":"Ali","email":"al***@gm***.com"},"mode":"rings","kind":"rings",
  "track":"TRTEST","drone":{"name":"FPV-1","type":"fpv"},"max_players":3,"created_at":"…","expires_at":"…"}],"count":1}
```
→ `POST /api/invites/{id}/accept` → karşılaşma anlık görüntüsü (şifresiz lobiye girer; sonra mevcut `WS /ws/match/{id}` akışı) ·
`POST /api/invites/{id}/decline {"block":false}` (`block:true` = bu kişiden davet alma; `GET/DELETE /api/invites/blocks[/{uid}]`).

Akış (e-posta bağlantısı / derin bağlantı): bağlantı `…/app/#/match/invite/<tok>`. UE bir URL işleyicisi kaydederse (`simumav://invite/<tok>` önerisi; web bağlantısı
tarayıcıda açılır) belirteçle: `GET /api/invites/t/{tok}` (OTURUMSUZ: `state, inviter (maskeli), mode, kind, track, max_players, expires_at, email_hint,
login_url, register_url, download_url, requires_login`) → giriş → `POST /api/invites/t/{tok}/accept`. Davet alıcının e-postasına bağlıdır: başka hesap
403 `wrong_account`; durum hataları 409 `accepted|declined|expired|revoked`; geçersiz belirteç 404. Ret oturumsuz da: `POST /api/invites/t/{tok}/decline`.

Gizlilik: yanıtlar e-postayı her zaman maskeli verir (`mk***@gm***.com`); kurucuya alıcının hesabı olup olmadığı söylenmez.

## D. Arkadaşlarım — Pilot menüsü

`GET /api/friends` →
```json
{"friends":[{"user_id":12,"name":"Berk","email":"be***@gm***.com","avatar":{…3B avatar…},"played_count":4,"last_played_at":"…",
  "auto":true,"friend":false,"added_at":null}]}
```
- `auto`: birlikte (başlamış ya da bitmiş) karşılaşmaya girilmiş; `friend`: elle eklenmiş. Sıra son oynama/eklenme tarihine göre.
- `POST /api/friends {"user_id":12}` (yalnız birlikte uçulmuş) ya da `{"email":"x@y.com"}` (günde 20; yoksa 404) → 201 arkadaş kaydı.
- `DELETE /api/friends/{user_id}` (otomatik olan gizlenir). Davet ekranında "Arkadaşlarımdan seç" → `friend_ids`.

## E. Pilot seviyesi, XP, madalyalar — Mürettebat / Pilot

- `GET /api/crew/levels` → `{max_level:100, curve:[100 değer; curve[L-1] = L'ye ulaşmak için toplam XP], formula, medals:[{id, level, label{tr,en}}],
  daily_cap:3000, import_cap, min_air_s:10, sources{…}}`. Eğri: `round(100 × (L−1)^1.8)`. Madalyalar: 5 `wings_bronze`, 10 `wings_silver`, 25 `wings_gold`,
  50 `wings_platinum`, 75 `wings_diamond`, 100 `wings_legend`.
- `GET /api/crew` pilot kayıtlarında: `level, level_verified, xp, xp_verified, xp_unverified, level_xp, next_level_xp (son seviyede null), progress (0–1), medals:[id]`.
- `GET /api/crew/{pid}/level` → yukarıdakiler + `medals:[{id, level, label, earned, verified}]` + `events` (son 20 XP kaydı: `source flight|match|import, ref_id,
  xp, verified, parts{…}, mode, capped, created_at`). Uçuş sonu ekranında "Kazanılan XP" = ilgili uçuşun `events` satırı (ya da `GET /api/crew/{pid}/flights`
  `xp` alanı). XP uçuş kapanışında sunucuda yazılır; karşılaşma bileşeni karşılaşma BITTI olduktan sonra (birkaç saniye) eklenir — UE sonuç ekranından
  2–3 sn sonra `level`'ı yeniden çekmeli.
- XP kaynakları (yalnız sunucu verisi; UE kendi hesaplamaz, yalnız gösterir): hava süresi, mesafe, §42 uyarı disiplini, yumuşak iniş, görev tamamlama,
  savunma/hedef puanı, yük bırakma servo tetik + isabet, ilaçlama oranı, karşılaşma halka/sıra/galibiyet. UE'nin bildirdiği sayımlar (`stop.gates`) XP'ye girmez.
- **Misafir (yerel SITL) kipi**: UE XP'yi yerelde tutar (önerilen kayıt `{xp, at ISO, mode, duration_s}` listesi, aynı formülle tahmini). Hesaba bağlanınca isteğe bağlı:
  `POST /api/crew/{pid}/xp/import {"entries":[{"xp":120,"at":"2026-10-20T12:00:00","mode":"free","duration_s":300}]}` (≤ 200 kayıt, kayıt başına ≤ 1000, 5/sa) →
  `{imported, skipped, remaining_cap, …seviye alanları}`. Aktarılan XP `verified:false` olarak AYRI işaretlenir, toplamı en çok seviye 10 eşiği (`import_cap`);
  UE arayüzde doğrulanmamış XP'yi farklı renkte göstermeli; `level_verified` ve madalya `verified` alanı yalnız sunucu XP'sidir. Aktarılan kayıtlar yerelde silinmeli
  (tekrar aktarılırsa sınır zaten dolu).

## F. Önceki uçuşlarım

`GET /api/crew/{pid}/flights?limit=30&offset=0&mode=free` → `{pilot_id, flights:[{id, started_at, ended_at, duration_s, result, mode, xp, active, has_bin, has_replay,
track{…}, drone{…preview}, pilot, mission, match_id, …}], total, stats{flights, flight_s, crashes}}`. Ayrıntı/replay/indirme mevcut uçlar: `GET /api/ops/{id}`,
`/api/ops/{id}/replay`, `/api/ops/{id}/bin`, `/api/ops/{id}/params`. Liste ayrıca `GET /api/ops?pilot_id=`.

## G. Hangar — Mission Planner'dan bağlanılabilen kalıcı dronlar

- Dron kayıtları (`GET /api/hangar`) artık `equipment` taşır:
```json
{"camera":"day|night|thermal|multispectral",
 "addons":{"sprayer":{"tank_l":10,"width_m":4,"pump_rate":10},"gripper":{"payload_kg":1},"parachute":{"alt_min_m":10}},
 "livery":{"pattern":"solid|stripe|split|camo|checker","color2":"#00ff00","callsign":"TR-01","decals":[{"id":7,"slot":"top","scale":1.2,"rot":0}]},
 "max_alt_m":120}
```
  Eklenmeyen eklenti anahtarı yoktur. `POST /api/hangar {name, type, model_key, color, params?, power?, airframe?, equipment?}` · `PUT /api/hangar/{id} {…, equipment?}`
  (tam nesne gönderin; doğrulama 422). Sihirbaz adımları: tip → model (`GET /api/hangar/catalog`) → azami hız (`power.max_speed_ms`) / `equipment.max_alt_m` +
  `params` (beyaz liste) → kamera → eklentiler → ad/renk/görünüm. `GET /api/hangar/equipment` seçenek listeleri + sınırlar + her eklentinin SITL parametreleri.
- Eklenti tip uygunluğu: sprayer yalnız `multirotor|fpv|heli`; gripper tüm tipler; parachute havadakiler. SITL karşılığı (sunucu uçuş açılışında yazar):
  sprayer `SPRAY_ENABLE=1, SERVO9_FUNCTION=22, SERVO10_FUNCTION=23, SPRAY_PUMP_RATE` · gripper `GRIP_ENABLE=1, GRIP_TYPE=1, SERVO11_FUNCTION=28` ·
  parachute `CHUTE_ENABLED=1, CHUTE_TYPE=10, SERVO12_FUNCTION=27, CHUTE_ALT_MIN`. **Misafir (yerel Windows SITL) kipinde UE aynı parametreleri kendisi yazmalı**
  (aynı tablo). Kullanıcı ince ayarı `SPRAY_*`, `GRIP_*`, `CHUTE_*` beyaz listede.
- Kamera: fly/start `camera` verilmezse dronun kamerası (multispectral sunucuda `day` olarak koşar; UE çok bantlı görünümü kendisi üretir).
- **Kalıcı parametreler**: uçuşta Mission Planner'dan (TCP, `mp.host:port`) yazılan parametreler uçuş sonunda dronun `params` kaydına geçer (beyaz liste, ≤ 60);
  sonraki uçuş aynı değerlerle açılır.
- **Lua script'leri**: `GET /api/hangar/{did}/scripts` → `{scripts:[{id, name, size, sha256, enabled, run_on_server}], max, run_on_server}` · `POST {name:"x.lua", content, enabled}`
  (≤ 8, ≤ 64 KB, ad `[a-z0-9_-]{1,40}.lua`; 409 `exists`/`quota`, 413) · `GET/PUT/DELETE /api/hangar/{did}/scripts/{sid}` · `GET …/{sid}/download`.
  Sunucu SITL'inde çalıştırılmaz (`run_on_server:false`); UE misafir kipinde yerel SITL'e (`SCR_ENABLE=1` + scripts klasörü) kendi sorumluluğunda yükleyebilir.
- **Logo / çıkartma**: `POST /api/hangar/{did}/decals {"image":"data:image/png;base64,…","kind":"logo|sticker"}` (PNG/JPEG/WebP ≤ 1 MB; sunucu ≤ 1024 px PNG'ye
  yeniden kodlar; 20/sa; dron başına 6) → `{id, width, height, size, url:"/api/hangar/decals/<tok>.png"}` · `GET /api/hangar/{did}/decals` · `DELETE …/{iid}`.
  Görsel URL'si oturumsuz okunur (karşılaşmada diğer oyuncuların istemcisi de indirir). Görünüme `livery.decals[].id` ile bağlanır.

## H. Yeni hata kodları

`wrong_account` (403), `invite_limit` (409), `invite_daily` (429), `accepted|declined|expired|revoked` (409, davet durumu), `exists` (409 script), `quota` (409),
`too_large` (413), `full` (409, araç tavanı).
