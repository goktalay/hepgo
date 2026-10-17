# Uçuş Simülatörü — sözleşme v1 (HEPGO modülü `drone.sim`)

Amaç: Kullanıcı dron tipini (sabit kanat / multikopter / VTOL / hexa / helikopter) ve kayıtlı bir **merkezi** (Dron Yönetimi › Rotalar
› Merkezler, `drone_route_centers`) seçer, sanal dünyayı tanımlar (ağaç sıklığı, dağ yüksekliği, bina sayısı, pist, su, saat, rüzgar),
**Başlat** der: sunucuda gerçek bir **ArduPilot SITL** süreci (mevcut `app/drone_sitl.py` yöneticisi) kalkar, tarayıcıda **three.js**
ile 3B dünya açılır (dron dışarıdan görünür; "dron kamerası" görünümü de var), 3B'nin üstünde uçuş veri paneli (HUD) durur, sunucu
**0.0.0.0:<udp_port>** dinler: kullanıcı **Mission Planner**'ı bu adrese bağlar, USB kumandayı Mission Planner joystick ile kullanır ve
birebir uçar. HEPGO, SITL ile Mission Planner arasında MAVLink köprüsüdür ve telemetriyi WebSocket ile tarayıcıya yayınlar.

## 1. Yetki, kayıt, paket
- RBAC düğümü: `('drone.sim', 'Uçuş Simülatörü', 'Saha & Operasyon')` (`app/rbac.py` CATALOG; `drone` üst düğümünden miras; dron paketi
  görünürlüğü `auth.drone_visible` ile kendiliğinden). Router: `auth.require_module('drone.sim')` (okuma), oturum açma/komut = yazma izni.
- Ön yüz: `static/js/modules/drone.js` TABS'a `sim` sekmesi ("Uçuş Simülatörü", `#/drone/sim[/<oturum>]`), modül içeriği
  `static/js/modules/flightsim.js` (dinamik import). Uygulamalar ızgarası aramasında "Uçuş Simülatörü" kısayolu (app.js FEATURES).
- Kiracı başına en fazla `SIM_MAX_SESSIONS` (varsayılan 2) oturum; oturum süresi `SIM_MAX_MINUTES` (varsayılan 120).

## 2. REST (`/api/drone/sim`, JSON)
| Uç | Açıklama |
|---|---|
| `GET /meta` | `{types:[{key,name,binary}], centers:[{id,name,lat,lon,alt,location_name}], world_defaults, limits:{max_sessions,max_minutes}, host}` — `host`: Mission Planner'a verilecek adres (`SIM_PUBLIC_HOST` env, yoksa istek Host başlığının ana makinesi) |
| `GET /sessions` | Kiracının açık oturumları `[session]` |
| `POST /sessions` | `{type, center_id, world}` → `session` (201). Hatalar: 400 `invalid`, 409 `limit`, 503 `sitl` (ikili/port yok) |
| `GET /sessions/{id}` | `session` |
| `DELETE /sessions/{id}` | durdurur (SITL kapanır, UDP kapanır) → `{ok}` |
| `POST /sessions/{id}/cmd` | `{name, params}`; name ∈ `arm` (force), `disarm`, `mode` (`params.mode` ArduPilot mod adı), `takeoff` (`params.alt`), `rtl`, `reset` (SITL'i aynı ayarlarla yeniden başlatır), `crash` (ön yüz çarpışma: zorla disarm + olay), `set_home`, `rc` (`params.ch` 8 kanal 1000–2000, RC_CHANNELS_OVERRIDE; ileride Gamepad) → `{ok}` |

`session` = `{id, type, center:{id,name,lat,lon,alt}, world, state: 'BASLIYOR'|'HAZIR'|'HATA'|'KAPANDI', udp_port, host, created_at,
owner:{id,name}, gcs:{connected:bool, addr:"ip:port"|null, since}, sitl:{pid, port, error}}`

`world` (ön yüz üretir, sunucu doğrular ve saklar; deterministik):
```json
{"mode": "procedural|real", "seed": 12345, "size_m": 4000, "tree_density": 0.3, "mountain_height": 300, "mountain_count": 4,
 "building_count": 40, "runway": true, "runway_heading": 0, "water": 0.1, "time": "day|dusk|night", "wind_ms": 3, "wind_dir": 270, "fog": 0.2}
```
Sunucu rüzgârı SITL'e yazar: `SIM_WIND_SPD`, `SIM_WIND_DIR`. `mode: "real"` (§8): merkez irtifası (`center.alt`) boşsa SITL ev irtifası
terrarium karosundan (`sim_terrain.ev_irtifa`, 12 sn üst sınır; alınamazsa `EV_IRTIFA`) alınır ve `session.center.alt` olarak döner.

## 3. WebSocket (`/ws/drone/sim/{id}`, oturum çerezi; drone_hub `_ws_user` kalıbı)
- Bağlanınca `{t:'hello', session}`; yetkisiz `{t:'error',error:'auth'}` + 4403; oturum yoksa 4404.
- 20 Hz (ayarlanabilir) `{t:'tele', ts, lat, lon, alt_msl, alt_rel, roll, pitch, yaw (rad), vn, ve, vd (m/s), airspeed, groundspeed,
  heading (deg), climb, mode, armed, gps_fix, sats, batt_v, batt_pct, throttle (%), rc:[8 kanal], home:{lat,lon,alt}, gcs_connected, gcs_addr}`
- `{t:'event', text, severity}` (STATUSTEXT ve köprü olayları), `{t:'state', state}`, `{t:'end', reason}`.
- İstemciden: `{t:'ping'}`, `{t:'cmd', name, params, rid?}` (REST `cmd` ile aynı), `{t:'rc', ch:[…]}` (en çok 20 Hz; fazlası atılır, yanıt yok).
- Sunucu eklemeleri (arka uç v1): `hello.can_command` (bu kullanıcı `drone.sim` yazma iznine sahip mi); her `cmd`'ye `{t:'res', name, rid, ok, error?}`
  (yazma izni yoksa `ok:false`); `{t:'pong'}`. `tele.ts` Unix saniyesi (float); `roll/pitch/yaw` rad, `heading` derece, `rc` 8 tam sayı (1000–2000),
  `home` null olabilir (SITL HOME_POSITION gelmeden), `batt_v`/`batt_pct`/`sats` null olabilir, `mode` ArduPilot mod adı (ilk kalp atışına dek null).

## 4. MAVLink köprüsü (sunucu; `app/flightsim.py`)
- Oturum kimliği SITL yöneticisinde `9000 + N` (saha görevlerinin sanal dronlarıyla çakışmaz). `drone_sitl.YONETICI.baslat(kimlik, tip, lat, lon,
  sysid=1, irtifa=center.alt veya 100)`; SERIAL0 TCP'ye bağlanır ve **bağlantıyı açık tutar** (kapanınca SITL çıkar — Tuzak F).
- UDP sunucu: `0.0.0.0:<port>`; port `SIM_UDP_BASE` (varsayılan 14550) ile `SIM_UDP_BASE+99` arasında boş olan. İlk paket gönderen
  adres **GCS** olarak kilitlenir (`gcs.addr`); 30 sn sessizlikte kilit kalkar. Ham baytlar iki yönlü iletilir (TCP↔UDP); sunucu TCP
  akışını ayrıca pymavlink ile ayrıştırıp telemetriyi üretir (GLOBAL_POSITION_INT, ATTITUDE, VFR_HUD, HEARTBEAT, SYS_STATUS, GPS_RAW_INT,
  RC_CHANNELS, STATUSTEXT, HOME_POSITION). Açılışta `REQUEST_DATA_STREAM` 10 Hz (MP bağlanınca kendi isteklerini de gönderir).
- Güvenlik: port rastgele değil ama oturuma özel ve kısa ömürlü; GCS kilidi; oturum sahibi dışındaki kullanıcılar yalnız izler
  (yazma izni olanlar komut verebilir). MAVLink2 imzalama (Mission Planner destekler) ileride isteğe bağlı.
- Yaşam döngüsü: izleyici yok ve GCS yok → 10 dk sonra durdur; `SIM_MAX_MINUTES` dolunca durdur; uygulama açılışında artık SITL
  süreçleri temizlenir (`YONETICI.artiklari_temizle` zaten var); lifespan'de oturumlar kapatılır.

## 5. 3B dünya (tarayıcı; `static/js/modules/flightsim3d.js`, three.js r170 `static/vendor/three`)
- Yerel koordinat: ENU, merkez referanslı: `x = (lon − lon0)·111320·cos(lat0)`, `y = (lat − lat0)·110574`, `z = alt_rel` (pist seviyesi 0).
- Arazi: 2D simplex gürültü (tohumlu), 3 oktav; yükseklik `h(x,y) = mountain_height · n(x,y)` + merkez çevresinde 300 m yarıçapta
  düzleştirme (pist/kalkış alanı); su seviyesi `water` oranına göre; renkler yüksekliğe göre (çim → kaya → kar).
- Nesneler: ağaçlar (InstancedMesh, yoğunluk `tree_density`, su/pist/bina üzerinde değil), binalar (`building_count`, kutular, yükseklik
  rastgele 6–40 m, pistten uzak), pist (asfalt, çizgiler, `runway_heading`), gökyüzü (zaman: gün/akşam/gece; gece ışıklar), sis.
- Dron: sabit kanat `static/models/caymaz.gltf` (ölçek), multirotor/hexa basit geometri (kollar + dönen pervaneler, throttle ile hız),
  VTOL = uçak + 4 pervane. Yönelim: roll/pitch/yaw → quaternion (NED→ENU dönüşümü dikkat).
- Kameralar (tuşlar 1–4): **Takip** (3. şahıs, OrbitControls hedefi dron), **Dron kamerası** (FPV, burun; gimbal pitch ↑↓),
  **Serbest** (WASD + fare), **Yer** (merkezden, dronu izler). Çarpışma: `z < h(x,y) + 0.3` ya da bina kutusuyla kesişme ve hız > 1 m/s
  → kırmızı "ÇARPIŞMA" bandı + `cmd crash`; oturum "Sıfırla" ile yeniden başlar.
- HUD (3B üstünde, sağ): mod, arm, yükseklik (AGL/MSL), hava/yer hızı, dikey hız, yön, GPS/uydu, batarya, gaz, RC çubukları, rüzgâr;
  sol alt: **Mission Planner bağlantısı**: `UDP <host>:<port>`, "Bağlı (ip)" / "Bekleniyor"; Kopyala; kısa talimat (Mission Planner › UDP › port).
- Performans: 60 fps hedef; arazi 256×256 ızgara, LOD yok; ağaç ≤ 20.000 örnek; telemetri enterpolasyonu (20 Hz → kare).

## 6. Kurulum sihirbazı (`flightsim.js`)
1. Dron tipi kartları (SITL `TIP_ESLEME` anahtarları). 2. Merkez seçimi (liste; ad, konum adı, koordinat; merkez yoksa Rotalar'a bağlantı).
3. Dünya: kip (Gerçek arazi / Prosedürel, §8), kaydırıcılar/seçimler (yukarıdaki `world`), "Rastgele tohum", önizleme (küçük 3B; gerçek
kipte yükleme şeridi + özet). 4. Başlat → oturum ekranı.
Açık oturum varsa liste: devam et / bitir. 8 dil (i18n.*.js; sözlük dosyaları modül olarak `node --check` ile denetlenir).

## 7. Testler
- `tests/test_flightsim.py`: meta (tipler, merkezler), oturum açma/limit/kapama (SITL yoksa 503), komut yetkisi (salt okuyan 403),
  WS hello/tele (SITL olmadan `HEPGO_SITL=0` ile sahte telemetri üreticisi), UDP köprüsü (yerel soket ile ham bayt gidiş-dönüş, GCS kilidi).
- Gerçek topoğrafya (ağsız, `sim_terrain.FETCH` sahte): terrarium çözme (Pillow ile üretilen küçük PNG, saf çözücü), Web Mercator gidiş-dönüş,
  bina yüksekliği kuralları, OSM sadeleştirme (way/relation outer, kapalı halka, 2 noktalı pist), `/terrain` planı (z seçimi, karo sayıları,
  `home_elev`), `/tile` (önbellek vuruşu, içerik türü, 404 sınırları, 503/502 kaynak hataları, LRU boyut sınırı), `/osm` (7 gün önbellek,
  bayat yenileme, yedek Overpass, 503), yetki (modülsüz 403), `world.mode` doğrulama ve gerçek kipte ev irtifası.

## 8. Gerçek topoğrafya (`world.mode = "real"`; `app/sim_terrain.py`, ön yüz `loadRealTerrain`)
Kullanıcı sihirbazın Dünya adımında **Gerçek arazi / Prosedürel** seçer. Gerçek kipte seçili merkezin çevresi (kenar `size_m`, 1–12 km)
gerçek yükseklik + uydu doku + OpenStreetMap nesneleriyle kurulur; prosedürel ayarlar *özelleştirme* olarak kalır: `tree_density` OSM orman
alanlarındaki ağaç yoğunluğu ölçeği (0.3 ≈ 4000 ağaç/km²), `building_count` ek rastgele bina (0 = yalnız gerçek binalar; kip değişince
kendiliğinden 0/varsayılan), `runway`/`runway_heading` merkez pisti (çevresi düzleştirilir; pisti kesen OSM binaları kalkış alanı için
atlanır), `fog`/`time`/`wind_*` aynı; `seed`, `mountain_*`, `water` gizlenir (yalnız ek bina/ağaç yerleşiminde tohum).

Veri kaynakları (anahtar gerektirmez; URL'ler sunucuda sabit, SSRF yok; tarayıcı doğrudan çekmez — CSP `img-src/connect-src 'self'` yeter):
| Veri | Kaynak | Not |
|---|---|---|
| Yükseklik | AWS Terrain Tiles terrarium PNG `s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` | `h = R·256 + G + B/256 − 32768`; z=13 (≤ 6 km) / 12 |
| Uydu doku | Esri World Imagery `server.arcgisonline.com/.../World_Imagery/MapServer/tile/{z}/{y}/{x}` | z = yükseklik z + 3 (16/15); ekranda atıf "Esri, Maxar, Earthstar Geographics" |
| Binalar / orman / su / pist | Overpass `overpass-api.de/api/interpreter` (yedek `overpass.kumi.systems`) | `way/relation["building"]`, `landuse=forest`/`natural=wood`, `natural=water`, `aeroway=runway`, `out geom`; User-Agent zorunlu (yoksa 406) |

Vekil uçları (`require_module('drone.sim')`, GET; salt okuyan rol de kullanır):
| Uç | Yanıt |
|---|---|
| `GET /api/drone/sim/terrain?lat&lon&size_m` | `{z, tiles:[{x,y}], img_z, img_tiles:[{x,y}], elev_url_template, img_url_template, home_elev, bbox, size_m, attribution}`; `home_elev` merkez karosundan (alınamazsa null); 400 geçersiz parametre |
| `GET /api/drone/sim/tile/{elev\|img}/{z}/{x}/{y}` | PNG/JPEG baytları, `Cache-Control: private, max-age=86400`; disk önbelleği `DATA_DIR/sim_terrain/{kind}/{z}/{x}/{y}` (LRU, erişimde mtime; sınır `SIM_TERRAIN_CACHE_MB`, varsayılan 2048 → %85'e temizlenir); kaynak 10 sn zaman aşımı; 404 geçersiz tür/sınır, 502 kaynak HTTP hatası, 503 ulaşılamadı/zaman aşımı (hata önbelleğe yazılmaz) |
| `GET /api/drone/sim/osm?lat&lon&size_m` | `{buildings:[{poly:[[lat,lon]…], h}], forests:[poly], water:[poly], runways:[{poly, heading, width}], cached_at, bbox}`; bina `h`: `height` → `building:levels`×3 (+çatı katı) → deterministik 6–12 m; kapalı halkaların tekrarlı son noktası atılır; 7 gün önbellek `DATA_DIR/sim_terrain/osm/<sha1>.json`; Overpass 60 sn; 503 kaynak kapalı (iki sunucu da), 502 bozuk yanıt |

Ön yüz (`flightsim3d.js`): `/terrain` planı → yükseklik karoları canvas üzerinden Float32 mozaiğe (terrarium çözümü), `sample(x,y)` bilineer
(merkez yüksekliği 0; pist düzleştirmesi 300/600 m, pist kapalıysa 60/160 m) → `terrainHeight` ve çarpışma aynı; uydu karoları tek canvas
atlasında (≤ 4096 px, gerekirse ölçekli) `CanvasTexture` + UV Web Mercator'dan; gece/akşam malzeme renginde koyulaştırma + bina çatı ışıkları
(Points); OSM binalar `ShapeUtils.triangulateShape` çatı + duvar dörtgenleri tek `BufferGeometry` (8000 bina ≈ 1 sn), AABB çarpışma;
su çokgenleri `ShapeGeometry` (çarpışma: nokta-çokgen); ağaçlar orman çokgenlerinde (alan oranı kotası, bbox içinde örnekleme); OSM pistleri
ek asfalt şerit. Yükleme ilerlemesi (`onProgress`: plan/elev/img/osm/done) sihirbazda şerit + özet satırı ("yükseklik a…b m · ev h m MSL ·
N bina · N orman · N su · N pist"), oturumda `.fs-msg` ve olay şeridi; atıf `.fs-attrib` (sağ alt). Yükseklik alınamazsa (`/terrain` ya da
tüm karolar 502/503) `onFallback` → prosedürele düşer ve "Gerçek veri alınamadı, prosedürele düşüldü" uyarısı; OSM alınamazsa arazi gerçek kalır,
"OSM verisi alınamadı" uyarısı. Aynı merkez+boyut için yüklenen veri örnek içinde önbelleklenir (`setWorld` yalnız sahneyi yeniden kurar;
`setOrigin` merkez değişince yeniden yükler). Sihirbaz önizlemesi gerçek kipte aynı veriyle (uydu dokulu yükseklik + binalar) döner.

Ölçümler (DEV, Ankara 39.925/32.837, 4 km): `/terrain` soğuk 1.1 sn (merkez karosu + plan), sıcak 0.15 sn; yükseklik 4 karo 2.4 sn → 0.15 sn;
uydu 90 karo (z16, 2 MB) 12.5 sn → 2.6 sn; `/osm` soğuk 46 sn (Overpass; 7996 bina, 242 orman, 31 su; 1.3 MB sade JSON), sıcak 1 sn.
Tarayıcıda önizleme/oturum dünyası sıcak önbellekle 3–9 sn (yazılım WebGL).
