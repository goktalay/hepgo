# CAYSIM istemci API'si — sözleşme v1 (HEPGO ↔ CAYSIM)

**CAYSIM**, HEPGO Uçuş Simülatörü'nün (docs/ucus-simulatoru.md) yüksek gerçekçilikli masaüstü görselleştirme istemcisidir
(Unreal Engine 5 + Cesium for Unreal; ayrı depo `goktalay/caysim`). CAYSIM **kendi fiziğini çalıştırmaz**: ArduPilot SITL süreci,
Mission Planner UDP köprüsü, komut yürütme ve 50 Hz telemetri üretimi **HEPGO sunucusunda** kalır. CAYSIM, HEPGO'ya bir **istemci kodu**
ile bağlanır (Dron Köprüsü kalıbı; docs/dron-kopru-protokolu.md) ve şirket kimliğini (ad/logo), merkezleri, model kütüphanesini, dünya
ayarlarını, oturumları, telemetriyi, komutları ve RC'yi HEPGO'dan alır/verir.

Sunucu tarafı: `app/caysim.py` (istemci kayıtları, anahtar, hız sınırı), `app/routers/caysim.py` (REST `/api/caysim/v1`, WS
`/ws/caysim/v1/sessions/{id}`, yönetim uçları `/api/drone/sim/clients`), tablo `drone_sim_clients`. Bu belge CAYSIM oturumuna
verilecek tek kaynaktır; **kod bu belgeye birebir uyar** (uyumsuzluk = hata).

---

## 0. Hızlı başlangıç (istemci yazarı için)

1. HEPGO'da **Dron Yönetimi › Uçuş Simülatörü › CAYSIM istemcileri › İstemci ekle** → ekranda **bir kez** gösterilen istemci kodu:
   **`<domain>/<key>`** (ör. `caymaz.app/hV3k…43 karakter`). Kullanıcı bu kodu CAYSIM'e yapıştırır.
2. CAYSIM kodu **ilk `/` konumundan** ikiye böler: `domain` → taban adres `https://<domain>` ve `wss://<domain>`; `key` → Bearer anahtar.
   Anahtar `[A-Za-z0-9_-]{43}` (secrets.token_urlsafe(32)); CAYSIM yalnız yerelde şifreli saklar, günlüğe yazmaz.
3. `GET https://<domain>/api/caysim/v1/hello` (`Authorization: Bearer <key>`, `X-Caysim-Host`, `X-Caysim-Ver`, `X-Caysim-Platform`
   başlıkları) → şirket adı/logo, yetenekler, limitler, Google 3B var mı. 401 → kod yanlış; 403 → istemci pasif.
4. `GET /centers`, `GET /types`, `GET /models?type=…`, `GET /world-defaults` → kurulum ekranı.
5. `POST /sessions` → oturum (`id`). `wss://<domain>/ws/caysim/v1/sessions/<id>?key=<key>` → `hello` + 50 Hz `tele`.
6. Komut: WS `{t:'cmd', name, params, rid}` ya da `POST /sessions/{id}/cmd`. RC: WS `{t:'rc', ch:[8]}` (≤ 40 Hz).
7. Bitince `DELETE /sessions/{id}` (ya da WS kapanır; oturum izleyicisiz 10 dk sonra kendiliğinden kapanır).

---

## 1. Kimlik doğrulama ve güvenlik

- **İstemci kaydı**: tablo `drone_sim_clients` (ad, platform, sahip kullanıcı, anahtar şifreli `key_enc` — `cameras.encrypt`; `GET`
  anahtarı asla döndürmez, yalnız `has_key`). Kod yalnız oluşturma ve **Kodu yenile** (`rekey`) yanıtında düz görünür; `rekey` eski anahtarı
  anında geçersiz kılar ve açık WS bağlantılarını `4403` ile kapatır.
- **REST**: her istekte `Authorization: Bearer <key>` başlığı. Anahtar **sabit-zamanlı** karşılaştırılır (`hmac.compare_digest`), yalnız
  **aktif** istemciler (`active=1`) kabul edilir.
- **WS**: `?key=<key>` sorgu parametresi **ya da** bağlantıdan sonra ilk metin çerçevesi `{"t":"auth","key":"…"}` (15 sn içinde; yoksa 4400).
- **Hız sınırı** (köprüdeki gibi): IP başına **10 başarısız kimlik denemesi / 60 sn** → REST `429 rate_limited`, WS `4429`. Başarılı
  denemeler sayılmaz. Başarısız = anahtar yok/yanlış/pasif istemci.
- **Yetki modeli**: istemci, kaydı oluşturan şirkete (tenant) ve kaydın **sahibine** (`owner_id`; verilmezse oluşturan) bağlıdır. İstemcinin
  açtığı oturumun `owner` alanı bu kullanıcıdır; kayıttan oynatma loglarına erişim bu kullanıcının `flightlogs` yetkisiyle sınırlanır.
  İstemci, HEPGO web'den açılan oturumları da **görür ve komut verebilir** (`can_command:true` — simülatör, tek şirket içi araçtır).
- **CORS yok**: masaüstü istemci tarayıcı değildir; `Origin`'e bakılmaz, CORS başlığı dönülmez. Gelen `OPTIONS` isteği **204** ile yanıtlanır
  (gövdesiz).
- Tüm yanıtlar JSON (`application/json; charset=utf-8`), istisnalar: `/brand/logo` (resim), `/models/{id}/glb` (`model/gltf-binary`),
  `/models/{id}/thumb` (PNG), `/tile/...` (PNG/JPEG), `/sessions/{id}/replay` (gzip JSON).

### 1.1 Hata biçimi

Her REST hatası: HTTP durum kodu + gövde `{"detail": {"error": "<kod>", "message": "<insan okunur Türkçe metin>"}}`.

| HTTP | `error` | Anlamı |
|---|---|---|
| 400 | `invalid` | geçersiz gövde/parametre (ör. bilinmeyen tip, dünya sınırı dışı, bilinmeyen komut) |
| 401 | `auth` | `Authorization` yok / anahtar yanlış |
| 403 | `client_inactive` | istemci kaydı pasif |
| 403 | `forbidden` | sahibin yetkisi yok (ör. kayıttan oynatma logu) |
| 404 | `not_found` | oturum / model / merkez / log yok; Google 3B kapalıyken `/g3d-key` |
| 409 | `limit` | eşzamanlı oturum sınırı (`limits.max_sessions`) ya da kayıt henüz hazır değil (`/replay`) |
| 413 | `too_large` | gövde sınırı |
| 422 | `invalid` | FastAPI doğrulama hatası (`detail` listesi FastAPI biçiminde kalır — yalnız bu durumda `detail` nesne değil listedir) |
| 429 | `rate_limited` | IP başına başarısız kimlik sınırı |
| 503 | `sitl` | SITL ikilisi/portu yok, arazi kaynağı kapalı (`message` açıklar) |

---

## 2. REST uçları (`/api/caysim/v1`, Bearer)

| Uç | Yanıt / Davranış |
|---|---|
| `GET /hello` | §2.1. İstemci bilgisi başlıklarla ya da sorguyla alınır ve kayda yazılır (`host`, `client_ver`, `platform`, `last_seen`, `status='CEVRIMICI'`). |
| `GET /brand/logo` | Şirket logosu (PNG/JPEG/WebP/SVG; `Content-Type` dosyaya göre). Yüklü logo yoksa kurulum logosu, o da yoksa `static/img/logo.png`. Kimlik gerekir. |
| `GET /centers` | `{centers:[{id, name, lat, lon, alt, location_name}]}` — aktif rota merkezleri (Dron Yönetimi › Rotalar › Merkezler). `alt` m MSL ya da null. |
| `GET /types` | `{types:[{key, name, binary}]}` — `key` ∈ `multirotor, hexarotor, helikopter, sabit_kanat, vtol`; `binary`: SITL ikilisi sunucuda var (yoksa oturum açılışında indirilir, 503 olabilir). |
| `GET /models?type=` | `{models:[model], defaults:{type: builtin_id}}` — görsel model kütüphanesi (web ile aynı nesne: `{id, name, source (builtin|upload|design), type, types, format, size, ready, orient, has_prop, desc, thumb_url, glb_url}`). `thumb_url`/`glb_url` **CAYSIM yollarına çevrilmiştir** (`/api/caysim/v1/models/{id}/thumb`, `/glb`). `ready=false` → GLB henüz tarayıcıda üretilmemiş; CAYSIM bu modeli gösteremez (tipin dahili modeline düşer). |
| `GET /models/{id}/glb` | GLB ikilisi (`model/gltf-binary`). Dahili prosedürel modellerin (quad/hexa/heli/delta) GLB'si yoktur → 404; CAYSIM kendi varsayılan gövdesini kullanır. `builtin:caymaz` GLB olarak **vardır**. |
| `GET /models/{id}/thumb?type=` | 320×240 PNG (yoksa 404). |
| `GET /world-defaults` | `{world_defaults, limits:{size_m:[500,20000], tree_density:[0,1], …}, modes:['procedural','real','google3d'], times:['day','dusk','night']}` (§4). |
| `GET /terrain?lat&lon&size_m` | Gerçek arazi karo planı (web ile aynı; `{z, img_z, tiles, img_tiles, elev_url_template, img_url_template, home_elev, attribution, size_m}`); karo URL şablonları CAYSIM yollarıyla (`/api/caysim/v1/tile/{kind}/{z}/{x}/{y}`). |
| `GET /tile/{kind}/{z}/{x}/{y}` | `kind` ∈ `elev` (Terrarium PNG, AWS), `img` (Esri World Imagery JPEG). Sunucu önbellekler. |
| `GET /osm?lat&lon&size_m` | OSM sadeleştirilmiş nesneler `{buildings:[{poly:[[lat,lon]…], h}], forests, water, runways:[{poly, heading, width}]}`. |
| `GET /g3d-key` | `{key}` Google Map Tiles API anahtarı (`Cache-Control: no-store`); sunucuda tanımlı değilse 404. CAYSIM, Cesium'da Google Photorealistic 3D Tiles için kullanabilir (anahtarın HTTP referrer kısıtı varsa masaüstünden çalışmayabilir — `hello.google3d.enabled` bilgilendirir; CAYSIM kendi Cesium ion/Google anahtarını da kullanabilir). |
| `GET /logs?q=` | `{logs:[{id, file_name, size, aircraft, pilot, location, uploaded_at, task_code, type, vehicle, …}]}` kayıttan oynatılabilir uçuş logları (sahibin yetkisiyle). |
| `GET /sessions` | `{sessions:[session]}` — şirketin **tüm** açık oturumları (web + CAYSIM). |
| `POST /sessions` | §2.2 → `session` (201). |
| `GET /sessions/{id}` | `session` |
| `DELETE /sessions/{id}` | kapatır (SITL + UDP kapanır; izleyicilere `end`) → `{ok:true}` |
| `POST /sessions/{id}/cmd` | `{name, params}` (§5) → `{ok:true}`; hata 400 `invalid` |
| `GET /sessions/{id}/replay` | Kayıttan oynatma kareleri: gzip JSON (`Content-Encoding: gzip`), §7. Oturum `replay` değilse 400; hazır değilse 409. |
| `GET /sessions/{id}/mavlink` | `{host, udp_port, gcs_locked, gcs_addr, note}` — ham MAVLink isteyen istemci için SITL UDP kapısı (§8). |
| `OPTIONS *` | 204 |

### 2.1 `GET /hello`

İstek başlıkları (isteğe bağlı; sorgu parametresi `?host=&client_ver=&platform=` de kabul edilir, başlık öncelikli):
`X-Caysim-Host` (≤120, bilgisayar adı), `X-Caysim-Ver` (≤40, ör. `0.3.1`), `X-Caysim-Platform` (`windows|linux|macos|other`).

```json
{
  "v": 1,
  "server_time": "2026-10-17T14:03:22",
  "client": {"id": 3, "name": "Simülatör PC-1", "owner": {"id": 7, "name": "Muhammed Kaderoğlu"}},
  "company": {"name": "GÖKKUBBE Teknoloji", "legal_name": "Gökkubbe Teknoloji A.Ş.", "logo_url": "/api/caysim/v1/brand/logo", "primary_color": null},
  "caps": ["sessions", "cmd", "rc", "tele50", "models", "terrain", "osm", "replay", "mavlink_udp", "google3d"],
  "limits": {"max_sessions": 2, "max_minutes": 120, "rc_hz": 40, "tele_hz": 50},
  "host": "caymaz.app",
  "google3d": {"enabled": false},
  "sitl": {"enabled": true},
  "ws_url": "/ws/caysim/v1/sessions/{id}"
}
```
- `server_time` ISO-8601 yerel sunucu saati (saniye). `host`: SITL UDP için Mission Planner'a/CAYSIM'e verilecek ana makine (`SIM_PUBLIC_HOST`
  env; yoksa isteğin Host başlığı). `caps`: `google3d` yalnız anahtar tanımlıysa; `sitl.enabled=false` yalnız test kipi (sahte kinematik).
- `company.primary_color`: tema rengi (hex) tanımlıysa, yoksa `null`. `logo_url` göreli yoldur; `https://<domain>` ile birleştirilir ve Bearer ister.

### 2.2 `POST /sessions`

Gövde web ile aynı (docs/ucus-simulatoru.md §2):
```json
{"mode": "sitl", "type": "sabit_kanat", "center_id": 1,
 "world": {"mode": "procedural", "seed": 12345, "size_m": 4000, "time": "day", "wind_ms": 3, "wind_dir": 270, "fog": 0.2, "runway": true},
 "model": {"id": "builtin:caymaz", "orient": null}}
```
- `mode`: `sitl` (varsayılan; `type` + `center_id` zorunlu) ya da `replay` (`log_id` zorunlu; `type`/`center_id` log'dan).
- `model`: `{id, orient?}` ya da kimlik dizgesi; eksikse tipin varsayılanı. Eski `airframe: caymaz|delta` de kabul edilir.
- `world` eksik alanlar varsayılanla dolar; sunucu doğrular (sınırlar §4). `google3d` yalnız sunucuda anahtar varsa.
- Sunucu oturuma `client:{id,name}` ve `client_owned:true` işler; `owner` = istemci kaydının sahibi. Web ekranında bu oturum **CAYSIM** rozetiyle görünür.
- Hatalar: 400 `invalid`, 409 `limit`, 503 `sitl`.

`session` nesnesi:
```json
{"id": 12, "mode": "sitl", "type": "sabit_kanat", "airframe": "caymaz",
 "model": {"id": "builtin:caymaz", "name": "Caymaz V3", "source": "builtin", "type": "sabit_kanat", "orient": null, "glb_url": "/api/caysim/v1/models/builtin:caymaz/glb", "thumb_url": "...", "has_prop": true, "ready": true},
 "center": {"id": 1, "name": "Test Merkezi", "lat": 39.925, "lon": 32.837, "alt": 900.0},
 "world": {"mode": "procedural", "seed": 12345, "size_m": 4000, "...": "..."},
 "state": "BASLIYOR", "udp_port": 14550, "host": "caymaz.app", "created_at": "2026-10-17T14:05:01",
 "owner": {"id": 7, "name": "Muhammed Kaderoğlu"},
 "client": {"id": 3, "name": "Simülatör PC-1"},
 "gcs": {"connected": false, "addr": null, "since": null},
 "sitl": {"pid": 12345, "port": 5760, "error": null},
 "replay": null}
```
- `state`: `BASLIYOR` (SITL açılıyor, 10–45 sn; EKF/GPS) → `HAZIR` → (`HATA` | `KAPANDI`). Komutlar yalnız `HAZIR`'da (reset her zaman).
- `center.alt` m MSL: SITL ev irtifası. `real`/`google3d` dünyada merkez irtifası boşsa açık yükseklik verisinden alınır.
- `client` web'den açılan oturumlarda `null`. `udp_port`/`host`: Mission Planner ya da CAYSIM'in ham MAVLink kapısı (§8).

---

## 3. WebSocket `/ws/caysim/v1/sessions/{id}`

Bağlantı: `wss://<domain>/ws/caysim/v1/sessions/<id>?key=<key>`. Sorguda `key` yoksa ilk çerçeve `{"t":"auth","key":"…"}` (15 sn).

**Kapanış kodları**: `4400` kimlik yok/zaman aşımı · `4403` anahtar yanlış / istemci pasif / rekey · `4404` oturum yok · `4429` hız sınırı ·
`1000` oturum kapandı (`end` çerçevesinden sonra).

### 3.1 Sunucu → istemci
| `t` | Alanlar | Not |
|---|---|---|
| `hello` | `{session, can_command: true, v: 1, server_time}` | ilk çerçeve (kimlik sonrası) |
| `tele` | §6 | 50 Hz tavan; olay güdümlü (her ATTITUDE) |
| `event` | `{text, severity (0..7 MAV_SEVERITY), ts}` | STATUSTEXT + köprü olayları (ör. "GCS bağlandı", "ÇARPIŞMA") |
| `state` | `{state, replay?}` | `BASLIYOR|HAZIR|HATA|KAPANDI`; replay'de ilerleme `replay.progress` |
| `end` | `{reason}` | `kapatildi` · `sure_doldu` · `bosta` · `sunucu_kapaniyor` · `hata`; ardından 1000 ile kapanış |
| `res` | `{name, rid, ok, error?}` | her `cmd`'ye yanıt (`rid` istemcinin verdiği) |
| `pong` | `{}` | `ping`e |
| `replay` | `{action:'reset', by}` | kayıttan oynatma sıfırlandı (tüm izleyicilere) |
| `error` | `{error:'auth'|'not_found'|'rate_limited'|'timeout'}` | kapanış öncesi tek çerçeve |

`launch` çerçevesi v1'de **gönderilmez** (ayrılmış ad; ileride el fırlatma/katapult animasyon tetiği için).

### 3.2 İstemci → sunucu
| `t` | Alanlar | Not |
|---|---|---|
| `auth` | `{key}` | yalnız sorguda `key` yoksa; ilk çerçeve |
| `cmd` | `{name, params?, rid?}` | §5 komut seti; yanıt `res` |
| `rc` | `{ch:[8 tam sayı]}` | 1000–2000, `0` = kanala dokunma; **≤ 40 Hz** (fazlası sessizce atılır, yanıt yok). `[0]*8` = override serbest bırakma (sınırlanmaz) |
| `ping` | `{}` | 10–30 sn'de bir önerilir; yanıt `pong`. Sunucu ping göndermez, boşta zaman aşımı uygulamaz |

### 3.3 Bağlantı kopma / yeniden bağlanma
- Kopma → **üstel geri çekilme** 0,5 → 1 → 2 → 4 → 8 → 10 sn (tavan 10 sn), her denemede `GET /sessions/{id}` ile oturumun hâlâ var olduğu
  doğrulanabilir (404 → oturum bitmiş, ekranda "oturum kapandı"). `4403`/`4404`/`4429` kalıcıdır: yeniden deneme yapılmaz (4429'da 60 sn bekle).
- Yeniden bağlanınca `hello.session.state` okunur; `HAZIR` değilse `state` beklenir. Telemetri akışı kendiliğinden başlar.
- RC gönderen istemci bağlantı kopunca otopilotun `RC_OVERRIDE_TIME`=3 sn sonra override'ı bıraktığını bilmeli (SITL'de RC failsafe kapalı).
- **Gecikme hedefi**: sunucu→istemci `tele` için uçtan uca ≤ 60 ms (LAN'da ~5–20 ms). `tele.ts` (sunucu Unix sn) ile yerel saat farkı istemci
  tarafında EMA ile izlenir; kareler `tbm` (SITL ms) ile sıralanır — `tbm` geri gidiyorsa SITL `reset` olmuştur (sayaç sıfırlanır).
- İzleyicisiz oturum (WS yok + GCS yok) 10 dk sonra, süre sınırı (`limits.max_minutes`) dolunca her hâlde kapanır → `end`.

---

## 4. Dünya (`world`) sözleşmesi

```json
{"mode": "procedural|real|google3d", "seed": 12345, "size_m": 4000, "tree_density": 0.3, "mountain_height": 300, "mountain_count": 4,
 "building_count": 40, "runway": true, "runway_heading": 0, "water": 0.1, "time": "day|dusk|night", "wind_ms": 3, "wind_dir": 270, "fog": 0.2}
```
Sınırlar: `seed 0…2³¹−1`, `size_m 500…20000`, `tree_density 0…1`, `mountain_height 0…3000`, `mountain_count 0…50`, `building_count 0…500`,
`runway_heading 0…359.99` (derece, gerçek kuzeyden saat yönü), `water 0…1`, `wind_ms 0…30`, `wind_dir 0…359.99` (rüzgârın **geldiği** yön, derece),
`fog 0…1`. Sunucu rüzgârı SITL'e yazar (`SIM_WIND_SPD`, `SIM_WIND_DIR`). CAYSIM için anlamı:
- `procedural`: deterministik dünya — CAYSIM, `seed`'den aynı sahneyi üretmek **zorunda değildir**; kendi dünyasını (Cesium World Terrain + OSM
  binaları) kullanabilir, `runway`/`runway_heading` için merkezde sanal pist çizmesi beklenir (pist merkezde, `runway_heading` yönünde, 1,2 km × 30 m).
- `real`: HEPGO vekili (`/terrain`, `/tile`, `/osm`) ya da Cesium World Terrain + Bing/Esri uydu. Ev irtifası `session.center.alt`.
- `google3d`: Google Photorealistic 3D Tiles (Cesium for Unreal `CesiumGoogleMapTiles` / `/g3d-key`).
- `time` ışık: `day` 13:00, `dusk` 19:30, `night` 23:00 yerel; `fog` 0→yok, 1→200 m görüş.

---

## 5. Komut seti (`cmd.name` / `POST /sessions/{id}/cmd`)

| name | params | Etki |
|---|---|---|
| `arm` | — | MAV_CMD_COMPONENT_ARM_DISARM 1 (force 21196) |
| `disarm` | — | aynı, 0 (force) |
| `mode` | `{mode}` ArduPilot mod ADI büyük harf (`GUIDED`, `LOITER`, `AUTO`, `RTL`, `FBWA`, `TAKEOFF`, …) | DO_SET_MODE |
| `takeoff` | `{alt}` m göreli 1…1000 (kopter varsayılan 10, uçak 50) | kopter: GUIDED + NAV_TAKEOFF; uçak: NAV_TAKEOFF |
| `rtl` | — | NAV_RETURN_TO_LAUNCH |
| `set_home` | `{lat?, lon?, alt?}` | DO_SET_HOME (boşsa mevcut konum) |
| `rc` | `{ch:[8]}` | RC_CHANNELS_OVERRIDE (WS `rc` ile aynı) |
| `reset` | — | SITL'i aynı ayarlarla yeniden başlatır (`state` BASLIYOR→HAZIR; `tbm` sıfırlanır) |
| `crash` | — | istemci çarpışma algıladı: zorla disarm + `event` severity 2 ("ÇARPIŞMA") |

Kayıttan oynatma oturumunda yalnız `reset` (diğerleri 400). Yanıt `{ok:true}`; sunucu MAVLink COMMAND_ACK beklemez (ArduPilot yanıtı
telemetride görünür: `armed`, `mode`). **Çarpışma algılama CAYSIM'in işidir** (Unreal fizik/çarpışma hacmi ↔ arazi/binalar) → `crash`.

---

## 6. Telemetri (`tele`) — koordinat ve birim sözleşmesi

```json
{"t":"tele","ts":1760709802.123,"tbm":48320,
 "lat":39.925012,"lon":32.837455,"alt_msl":934.2,"alt_rel":34.2,
 "roll":0.0123,"pitch":-0.0456,"yaw":1.5708,"rs":0.001,"ps":-0.002,"ys":0.0,
 "vn":12.1,"ve":0.4,"vd":-0.8,"airspeed":13.2,"groundspeed":12.1,"heading":90.0,"climb":0.8,
 "mode":"FBWA","armed":true,"gps_fix":3,"sats":10,"batt_v":12.4,"batt_pct":87,"throttle":55.0,
 "rc":[1500,1500,1650,1500,1800,1500,1500,1500],"home":{"lat":39.925,"lon":32.837,"alt":900.0},
 "gcs_connected":false,"gcs_addr":null}
```
| Alan | Tip / birim | Açıklama |
|---|---|---|
| `ts` | float, Unix **saniye** (3 ondalık) | sunucu alım zamanı |
| `tbm` | int, **ms** | SITL `time_boot_ms`; kare sıralama/interpolasyon için kullanın |
| `lat`, `lon` | float, **derece** (WGS-84) | |
| `alt_msl` | float, **m** | deniz seviyesinden (GLOBAL_POSITION_INT.alt) |
| `alt_rel` | float, m | ev konumuna göre |
| `roll`, `pitch`, `yaw` | float, **radyan**, **NED** gövde açıları | ATTITUDE; `yaw` 0 = kuzey, +π/2 = doğu (saat yönü, yukarıdan) |
| `rs`, `ps`, `ys` | rad/s | roll/pitch/yaw açısal hızları (gövde) |
| `vn`, `ve`, `vd` | m/s, NED | kuzey / doğu / **aşağı** (pozitif alçalma) |
| `airspeed`, `groundspeed` | m/s | VFR_HUD |
| `heading` | derece 0…359 | VFR_HUD heading |
| `climb` | m/s (pozitif yukarı) | |
| `mode` | string \| null | ArduPilot mod adı (ilk kalp atışına dek null) |
| `armed` | bool | |
| `gps_fix`, `sats` | int \| null | |
| `batt_v`, `batt_pct` | float \| null | |
| `throttle` | 0…100 | |
| `rc` | 8 int | RC_CHANNELS 1…8 (µs; 0 = yok) |
| `home` | `{lat,lon,alt}` \| null | HOME_POSITION gelmeden null |
| `gcs_connected`, `gcs_addr` | bool, "ip:port" | Mission Planner UDP kilidi |

Yayın olay güdümlüdür: gerçek SITL'de her ATTITUDE (≈50 Hz; iki kare arası en az 18 ms SITL zamanı), SITL sessizse en az 4 Hz bekçi karesi.
Ardışık `tbm` farkı ≈ 20 ms. CAYSIM 50 Hz kareleri Unreal kare hızına (60–144 Hz) **interpolasyon + küçük dead-reckoning** ile taşımalıdır
(`vn/ve/vd` ve `rs/ps/ys` ile 1 kare ileri ekstrapolasyon; 100 ms'den eski veride dondur).

### 6.1 Unreal / Cesium dönüşüm notları
- **Georeference**: `CesiumGeoreference` origin = `session.center` (`lat, lon, alt`). Cesium for Unreal'ın georeferanslı Unreal çerçevesi
  **ESU**'dur (East-South-Up): Unreal **Z-yukarı, sol el**, `+X = Doğu`, `+Y = Güney` (= −Kuzey), `+Z = Yukarı`, birim cm. HEPGO'nun kendi
  web istemcisi (three.js) sağ el **ENU** kullanır (`x=east, y=north, z=up`); Unreal'a geçişte **Y ters çevrilir** (`y_unreal = −north`).
  Pratik yol: konumu elle dönüştürmeyin — `CesiumGlobeAnchor` bileşenine `lat/lon/yükseklik` yazın (`MoveToLongitudeLatitudeHeight`,
  yükseklik için §6.1 ofset kuralı); yönelimi ve hızı aşağıdaki kurallarla verin.
- **Yönelim (NED → Unreal, kesin kural)**: MAVLink `roll/pitch/yaw` NED gövde açılarıdır (sağ el; yaw 0 = kuzey, saat yönü pozitif).
  Unreal `FRotator(Pitch, Yaw, Roll)` derece; yaw 0 = +X (= Doğu), yukarıdan bakışta saat yönü pozitif (+X → +Y = Doğu → Güney) — yani
  **pusula yönü ile aynı yönde döner**, işaret değişmez, yalnız 90° kayma vardır:
  `Rotator.Yaw = deg(yaw) − 90` · `Rotator.Pitch = deg(pitch)` (burun yukarı pozitif, iki tarafta da) · `Rotator.Roll = deg(roll)` (sağ kanat
  aşağı pozitif, iki tarafta da). Globe anchor'da `AdjustOrientationForGlobeWhenMoving` açık kalsın (yerel teğet düzlem yönelimi).
  Tek seferlik sağlama: telemetride `heading≈90` iken araç +X'e (Doğu), `heading≈0` iken −Y'ye (Kuzey) bakmalı; `vd<0` (tırmanış) iken Z artmalı.
- **Hız (NED → Unreal)**: `(vn, ve, vd)` → Unreal `(X, Y, Z) = (ve, −vn, −vd) × 100` cm/s (interpolasyon/ekstrapolasyon için).
- **Konum farkı (yerel yaklaşım, ≤ 20 km)**: `east = (lon − lon0)·cos(lat0)·R·π/180`, `north = (lat − lat0)·R·π/180` (R = 6 378 137 m) →
  Unreal `(east, −north, alt − alt0) × 100`. Hassas konum için Globe anchor'ı tercih edin.
- **Ölçek**: Unreal birimi cm → tüm metreleri ×100. İrtifa `alt_msl` (elipsoid değil **MSL**): Cesium yüksekliği WGS-84 elipsoidine göre ister;
  fark (geoid ondülasyonu, Türkiye'de ~+25…+40 m) için `session.center.alt` (MSL, SITL ev irtifası) ile Cesium World Terrain'in merkezdeki
  `SampleHeightMostDetailed` sonucu arasındaki farkı **ilk kalkışa dek** ofset olarak alın (`terrain_ofset = cesium_h − center.alt`) ve her kareye ekleyin;
  böylece araç yerde iken Cesium zemininde durur. (HEPGO web Google 3B kipinde aynı yöntem kullanılır — docs/ucus-simulatoru.md §11.)
- **Model**: `/models/{id}/glb` GLB'si Y-yukarı sağ el (glTF); `model.orient` `{forward, up, scale, offset, prop}` yüklenen modellerde
  kullanıcının seçtiği yönelimdir — `forward` burun ekseni, `up` üst ekseni (`±x/±y/±z`), `scale` birim→m, `offset` m. Dahili model GLB yoksa
  CAYSIM kendi varlığını kullanır (tipe göre: quad/hexa/heli/plane/vtol).
- **Kamera**: web'deki kipler `follow` (arkadan takip), `fpv` (gövde kamerası, HUD), `orbit`, `ground` (yer kamerası, merkezden); CAYSIM serbesttir.

---

## 7. Kayıttan oynatma (`mode:'replay'`)

`POST /sessions {mode:'replay', log_id, world?, model?}` → oturum; sunucu logu ayrıştırır (`state` BASLIYOR → HAZIR; `state.replay.progress` %).
HAZIR olunca `GET /sessions/{id}/replay` → gzip JSON `{hz: 25, frames:[[t, lat, lon, alt_msl, alt_rel, roll, pitch, yaw, vn, ve, vd, mode, armed, …]], home, duration_s, takeoff_t, modes}`
(alan sırası web ile birebir — docs/ucus-simulatoru.md §8). WS'te replay oturumu `tele` **yaymaz**; oynatma istemcide yürür (web gibi); `reset`
komutu izleyicilere `{t:'replay', action:'reset'}` yayar (senkron sıfırlama).

---

## 8. Ham MAVLink (isteğe bağlı) — `GET /sessions/{id}/mavlink`

`{"host":"caymaz.app","udp_port":14550,"gcs_locked":false,"gcs_addr":null,"note":"İlk paket gönderen adres GCS olarak kilitlenir; 30 sn sessizlikte kilit kalkar."}`
CAYSIM, Mission Planner gibi `udp://host:udp_port`'a MAVLink paketi gönderip ham akışı alabilir (SITL SERIAL0 ↔ UDP köprüsü). **GCS kilidi**:
oturumda **tek** UDP GCS olur; CAYSIM bağlanırsa Mission Planner bağlanamaz (ve tersi). Bu yüzden varsayılan yol WS `tele`'dir; ham MAVLink yalnız
istemci kendi GCS'si olmak istiyorsa kullanılır. Komut vermek için WS/REST `cmd` yeterlidir (kilit gerekmez).

---

## 9. Yönetim uçları (HEPGO web, oturum çerezi; `drone.sim` yazma izni)

| Uç | Davranış |
|---|---|
| `GET /api/drone/sim/clients` | `{clients:[{id, name, platform, owner_id, owner_name, host, client_ver, status, last_seen, note, active, has_key, online, sessions, created_at, updated_at}]}` — **anahtar dönmez** |
| `POST /api/drone/sim/clients` | `{name, platform?, owner_id?, note?}` → `{id, code}` (code = `<domain>/<key>`, yalnız bu yanıtta) |
| `POST /api/drone/sim/clients/{id}/rekey` | → `{key, code}`; eski anahtar geçersiz, açık WS'ler 4403 |
| `PUT /api/drone/sim/clients/{id}` | `{name?, platform?, owner_id?, note?, active?}` → `{ok}` |
| `DELETE /api/drone/sim/clients/{id}` | siler; açık WS'ler 4403; istemcinin açtığı oturumlar **kapanmaz** (owner'a kalır) |

`domain` = Entegrasyonlar'daki ortak domain (`agentkeys.domain`) varsa o, yoksa isteğin Host başlığı. `status`: `CEVRIMICI` (son 90 sn içinde
hello/WS) · `CEVRIMDISI`; `online`: şu an açık WS var.

---

## 10. Sürümleme
`v:1` — alan **eklenebilir** (istemci bilinmeyen alanları yok sayar); alan silme/anlam değişikliği `v:2` ve yeni yol (`/api/caysim/v2`) gerektirir.
CAYSIM `hello.v` ≠ 1 ise kullanıcıyı uyarır. HEPGO testleri: `tests/test_caysim.py`.
