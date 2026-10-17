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
- `{t:'tele', ts, tbm, lat, lon, alt_msl, alt_rel, roll, pitch, yaw (rad), rs, ps, ys (rad/s; ATTITUDE roll/pitch/yawspeed), vn, ve, vd (m/s),
  airspeed, groundspeed, heading (deg), climb, mode, armed, gps_fix, sats, batt_v, batt_pct, throttle (%), rc:[8 kanal], home:{lat,lon,alt},
  gcs_connected, gcs_addr}` — **olay güdümlü**: gerçek SITL'de her ATTITUDE / GLOBAL_POSITION_INT geldiğinde (50 Hz tavan; 250 ms sessizlikte
  bekçi yayını), sahte kipte 50 Hz. `ts` sunucu alım zamanı (Unix sn, 3 ondalık), `tbm` SITL `time_boot_ms` (sahte: oturum ms). Sayılar
  yuvarlanır (açılar 4, hızlar 2–3 ondalık) — JSON küçük kalır.
- `{t:'event', text, severity}` (STATUSTEXT ve köprü olayları), `{t:'state', state}`, `{t:'end', reason}`.
- İstemciden: `{t:'ping'}`, `{t:'cmd', name, params, rid?}` (REST `cmd` ile aynı), `{t:'rc', ch:[…]}` (≈20 Hz; ~40 Hz üstü atılır, yanıt yok;
  `ch` 8×0 = override serbest bırakma — hız sınırına takılmaz, her zaman iletilir; tek kanalda 0 = o kanala dokunma).
- Sunucu eklemeleri (arka uç v1): `hello.can_command` (bu kullanıcı `drone.sim` yazma iznine sahip mi); her `cmd`'ye `{t:'res', name, rid, ok, error?}`
  (yazma izni yoksa `ok:false`); `{t:'pong'}`. `tele.ts` Unix saniyesi (float); `roll/pitch/yaw` rad, `heading` derece, `rc` 8 tam sayı (1000–2000),
  `home` null olabilir (SITL HOME_POSITION gelmeden), `batt_v`/`batt_pct`/`sats` null olabilir, `mode` ArduPilot mod adı (ilk kalp atışına dek null).

## 4. MAVLink köprüsü (sunucu; `app/flightsim.py`)
- Oturum kimliği SITL yöneticisinde `9000 + N` (saha görevlerinin sanal dronlarıyla çakışmaz). `drone_sitl.YONETICI.baslat(kimlik, tip, lat, lon,
  sysid=1, irtifa=center.alt veya 100)`; SERIAL0 TCP'ye bağlanır ve **bağlantıyı açık tutar** (kapanınca SITL çıkar — Tuzak F).
- UDP sunucu: `0.0.0.0:<port>`; port `SIM_UDP_BASE` (varsayılan 14550) ile `SIM_UDP_BASE+99` arasında boş olan. İlk paket gönderen
  adres **GCS** olarak kilitlenir (`gcs.addr`); 30 sn sessizlikte kilit kalkar. Ham baytlar iki yönlü iletilir (TCP↔UDP); sunucu TCP
  akışını ayrıca pymavlink ile ayrıştırıp telemetriyi üretir (GLOBAL_POSITION_INT, ATTITUDE, VFR_HUD, HEARTBEAT, SYS_STATUS, GPS_RAW_INT,
  RC_CHANNELS, STATUSTEXT, HOME_POSITION). Açılışta `REQUEST_DATA_STREAM` 10 Hz (ALL) **+** `MAV_CMD_SET_MESSAGE_INTERVAL`: ATTITUDE,
  GLOBAL_POSITION_INT, LOCAL_POSITION_NED 20 ms; VFR_HUD 50 ms; RC_CHANNELS 100 ms; HOME_POSITION 5 sn. **ArduCopter 4.7** kabul eder (tam
  50 Hz); **ArduPlane** 20 ms'yi reddeder (COMMAND_ACK 511 → MAV_RESULT 2) → sunucu akış bazlı `REQUEST_DATA_STREAM`'e geçer (EXTRA1 50,
  POSITION 50, EXTRA2 20, RC_CHANNELS 10 Hz; plane ≈ 40–52 Hz, boş tikler olabilir). Mission Planner bağlanınca kendi akış istekleriyle
  ezebilir → istekler her 3 sn yenilenir (`AKIS_YENILE_S`). Yayın kapısı SITL `time_boot_ms` ile (≥ 18 ms): TCP parçasında birlikte gelen
  ardışık kareler düşmez. DEV ölçümü (gerçek SITL, 5 sn): kopter 50.0 Hz / 20.0 ms / jitter 2.9 ms; uçak 40.0 Hz / 25.0 ms / p95 40 ms.
- Sanal kumanda (RC_CHANNELS_OVERRIDE): kaynak sysid 255 = `SYSID_MYGCS` (ArduPilot yalnız bu kaynaktan override kabul eder; comp 191).
  İlk kalp atışında `SIM_RC_FAIL 0`, `FS_THR_ENABLE 0` (kopter), `THR_FAILSAFE 0` (uçak), `RC_OVERRIDE_TIME 3` yazılır: override kesilince
  RC failsafe akışı bozmaz. Mission Planner joystick de override gönderirse son gelen kazanır (ön yüz uyarı gösterir).
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
- Dron: sabit kanat / VTOL gövdesi `airframe` (oturum alanı; `caymaz` varsayılan | `delta`): `caymaz` → `static/models/caymaz-sim.glb`
  (CAYMAZ V3 STEP montajından `tools/step2glb.js` ile; kanat açıklığı 3,03 m, arkadan itişli, `prop` düğümü döner; KHR_mesh_quantization,
  ~1,5 MB), `delta` → prosedürel delta uçan kanat (2,2 m, elevonlar RC ch1/ch2 ile). Multikopter 60 cm / hexa 90 cm / helikopter 1,5 m
  prosedürel (gövde, kollar, motorlar, iniş takımı, gimbal; pervaneler gaz ile döner, yüksek devirde bulanık disk). VTOL = gövde + 4 dikey
  pervane. Seyir ışıkları (sol kırmızı / sağ yeşil / kuyruk beyaz strobe, gece halo), yalnız dron gölge düşürür. Yönelim: roll/pitch/yaw →
  quaternion (NED→ENU dönüşümü dikkat). `caymaz.gltf` (eski basit model) yalnız Cesium oynatma/canlı izlemede (replay3d.js) kullanılır.
- Kameralar (tuşlar 1–4): **Takip** (3. şahıs, OrbitControls hedefi dron), **Dron kamerası** (FPV, burun; gimbal pitch ↑↓),
  **Serbest** (WASD + fare), **Yer** (merkezden, dronu izler). Çarpışma: `z < h(x,y) + 0.3` ya da bina kutusuyla kesişme ve hız > 1 m/s
  → kırmızı "ÇARPIŞMA" bandı + `cmd crash`; oturum "Sıfırla" ile yeniden başlar.
- HUD (3B üstünde, sağ): mod, arm, yükseklik (AGL/MSL), hava/yer hızı, dikey hız, yön, GPS/uydu, batarya, gaz, RC çubukları, rüzgâr;
  sol alt: **Mission Planner bağlantısı**: `UDP <host>:<port>`, "Bağlı (ip)" / "Bekleniyor"; Kopyala; kısa talimat (Mission Planner › UDP › port).
- Performans: 60 fps hedef; arazi 256×256 ızgara, LOD yok; ağaç ≤ 20.000 örnek.
- Akıcılık: **gecikme tamponlu enterpolasyon** — her `tele` karesi kaynak zamanıyla (`ts`) tamponlanır; kaynak saati istemci saatine
  "en küçük alım−kaynak farkı" ofsetiyle eşlenir (ağ jitter'ı zaman çizgisinden düşer); render zamanı = şimdi − 80 ms; iki kare arası konum
  lineer, yönelim slerp; tampon biterse ölü hesap (hız + gövde açısal hızları `rs/ps/ys`, en çok 300 ms). Kare hızından bağımsız (rAF delta);
  pervaneler delta-zamanla döner. Takip kamerası hedefi kritik sönümlü yayla izler (ω = 2π·1.5). HUD altında `net: 48 Hz · jitter 3 ms`
  (`sim.netStats()`; DR = ölü hesapta).
- Sanal kumanda (alt çubuk 🎮, yazma izni): iki yarı saydam çubuk (sol gaz/yaw, sağ pitch/roll; Mode 2; dokunmatik + fare) + klavye
  (W/S gaz, A/D yaw, ↑↓ pitch, ←→ roll — yaylı dönüş; Q/E ch5 mod anahtarı 1000/1500/2000; Boşluk gaz 1500). Kopterde gaz çubuğu merkeze
  yaylı (askı), uçakta tutmalı. 20 Hz `{t:'rc', ch}` yalnız açıkken; kapatınca / sayfadan çıkınca tek sefer 8×0. Açıkken 3B'nin WASD/ok
  tuşları kilitlenir (kamera 1–4 çalışır); HUD RC çubukları 1–5 yerel değerleri gösterir (mor).

## 6. Kurulum sihirbazı (`flightsim.js`)
1. Dron tipi kartları (SITL `TIP_ESLEME` anahtarları). 2. Merkez seçimi (liste; ad, konum adı, koordinat; merkez yoksa Rotalar'a bağlantı).
3. Dünya: kip (Gerçek arazi / Prosedürel, §8), kaydırıcılar/seçimler (yukarıdaki `world`), "Rastgele tohum", önizleme (küçük 3B; gerçek
kipte yükleme şeridi + özet). 4. Başlat → oturum ekranı.
Açık oturum varsa liste: devam et / bitir. 8 dil (i18n.*.js; sözlük dosyaları modül olarak `node --check` ile denetlenir).

## 7. Testler
- `tests/test_flightsim.py`: meta (tipler, merkezler), oturum açma/limit/kapama (SITL yoksa 503), komut yetkisi (salt okuyan 403),
  WS hello/tele (SITL olmadan `HEPGO_SITL=0` ile sahte telemetri üreticisi), UDP köprüsü (yerel soket ile ham bayt gidiş-dönüş, GCS kilidi).
- Kayıttan oynatma (§8): pymavlink ile yazılan küçük .tlog → ayrıştırıcı (kare sayısı, ev = ilk ARM, mod adı, olaylar), `GET /logs`
  yetki kesişimi, `POST /sessions {mode:'replay'}` → HAZIR, `GET /sessions/{id}/replay` gzip JSON, WS'te `tele` yok, `cmd` yalnız `reset`.

- Gerçek topoğrafya (ağsız, `sim_terrain.FETCH` sahte): terrarium çözme (Pillow ile üretilen küçük PNG, saf çözücü), Web Mercator gidiş-dönüş,
  bina yüksekliği kuralları, OSM sadeleştirme (way/relation outer, kapalı halka, 2 noktalı pist), `/terrain` planı (z seçimi, karo sayıları,
  `home_elev`), `/tile` (önbellek vuruşu, içerik türü, 404 sınırları, 503/502 kaynak hataları, LRU boyut sınırı), `/osm` (7 gün önbellek,
  bayat yenileme, yedek Overpass, 503), yetki (modülsüz 403), `world.mode` doğrulama ve gerçek kipte ev irtifası.

## 8. Kayıttan oynatma (`mode: 'replay'`; `app/flightsim_replay.py`)
Kullanıcı sihirbazda **Kip › Kayıttan oynat** seçer: sisteme yüklenmiş uçuş logları (flight_logs; analizi TAMAM; `.bin` / `.log`
DataFlash ya da `.tlog` MAVLink) listelenir (ad, tarih, dron, pilot, konum, görev kodu, süre, boyut; arama), biri seçilir, dünya
ayarlanır, **Oynat**. Kontrol kullanıcıda değildir: SITL ve UDP açılmaz, komut düğmeleri yoktur; kayıt 3B dünyada aynen oynatılır.
- **Yetki:** oturum `drone.sim` yazma izni; log listesi flightlogs yetkisiyle kesişir (`tools` → tüm loglar, `field` → yalnız göreve
  bağlı loglar; ikisi de yoksa boş liste, `meta.replay.logs_allowed=false`).
- **Uçlar:** `GET /api/drone/sim/logs?q=` → `[{id, file_name, ext, size, uploaded_at, aircraft, pilot, location, task_code, vehicle,
  type, flight_s, duration_s, takeoff_utc, start_utc, home_lat, home_lon, cached}]` · `POST /sessions {mode:'replay', log_id, world}` →
  `session` (201; 400 log yok/yetkisiz/analiz bitmemiş/biçim; 409 limit) · `GET /sessions/{id}/replay` → gzip JSON kareler
  (`Content-Encoding: gzip`; 409 HAZIR değilken; 400 SITL oturumu için).
- **session eklemeleri:** `mode: 'sitl'|'replay'`; replay'de `udp_port=null`, `center = {id:null, name:file_name, lat, lon, alt}` (ev),
  `type` firmware'den (ArduPlane → sabit_kanat, heli → helikopter, diğer → multirotor), `replay: {log_id, file_name, size, progress (%),
  frames, duration_s, home:{lat,lon,alt}, hz, takeoff_t, start_utc, vehicle, aircraft, pilot, modes}`. Durumlar: BASLIYOR (ayrıştırma;
  `progress` DFReader ilerlemesi, WS `state` ile yayınlanır) → HAZIR → KAPANDI; hata → HATA (`sitl.error`).
- **Ayrıştırma (sunucu, bir kez, iş parçacığında):** `.bin/.log` → `mavutil.mavlink_connection` (DFReader): GPS (Lat/Lng/Alt MSL,
  Spd, GCrs, VZ, Status, NSats, GWk/GMS → `start_utc`), POS (EKF konumu; varsa GPS'e tercih), ATT (Roll/Pitch/Yaw ° → rad; `hdg`),
  RCIN (C1–C8), BAT/CURR (Volt, RemPct; Inst 0), MODE (ModeNum → firmware mod adı), ARM/EV 10–11 (ARM/DISARM; ilk ARM = ev + `takeoff_t`),
  EV 25 / ORGN (ev yedeği), MSG (olaylar; uyarı ifadeleri sev 4), NKF1/XKF1 (VN/VE/VD; yoksa GPS Spd/GCrs), CTUN (ThO/ThrOut → gaz %, As),
  ARSP. `.tlog` → `mavutil.mavlogfile` (8 bayt BE µs + çerçeve; `_timestamp`): HEARTBEAT (araç; armed, mod adı), GLOBAL_POSITION_INT,
  ATTITUDE, RC_CHANNELS(_RAW), SYS_STATUS, VFR_HUD, GPS_RAW_INT, STATUSTEXT, HOME_POSITION. Yeniden örnekleme: sample-and-hold,
  `SIM_REPLAY_HZ` (25); 150.000 kareyi aşarsa seyreltme. `alt_rel = alt_msl − home.alt`.
- **Önbellek:** `DATA_DIR/sim_replay/<log_id>.json.gz` = `{v:1, hz, fields, frames, modes, events:[{t,text,sev}], duration_s, home,
  takeoff_t, start_utc, vehicle, type, n, source}`; `fields` = `[t, lat, lon, alt_msl, alt_rel, roll, pitch, yaw, vn, ve, vd, gs, as, hdg,
  thr, mode, armed, batt_v, batt_pct, sats, fix, rc]` (rc 8'li iç dizi). Sürüm uyuşmazsa yeniden üretilir; log silinince
  (`DELETE /api/tools/flight-logs/{id}`) önbellek de silinir. Örnek: 253 MB ArduPlane .bin (97 dk) → 27 sn, 111k kare, 2,4 MB gz.
- **WS:** `hello`/`state`(+`replay`)/`event`/`end`; `tele` YOK. İstemci `cmd` yalnız `reset` (diğerleri `res ok:false`); `reset` tüm
  izleyicilere `{t:'replay', action:'reset'}` yayınlar (ön yüz "Baştan"). `rc` yoksayılır.
- **Ön yüz (`flightsim.js`):** aynı sahne (`flightsim3d.js`; `origin` = ev, çarpışma denetimi kapalı), "● Kayıt" rozeti, kayıt
  bilgisi kutusu (MP kutusu yerine), oynatma çubuğu: ▶/❚❚ (boşluk), ⏮ Baştan, hız 0.5×/1×/2×/4×/8×, zaman kaydırıcısı (uyarı/hata
  olayları ve ilk ARM işaretli), `mm:ss / mm:ss` + kayıt saati; ←/→ 5 sn (Shift 30 sn). Kareler arası doğrusal enterpolasyon (açılar en
  kısa yol; 5 sn'den uzun boşlukta tutma), HUD/RC/mod/arm karelerden, olay şeridi MSG/STATUSTEXT'ten log zamanıyla (atlamada son 8 olay).
  Başlangıç: ilk ARM − 5 sn, otomatik oynatır. `?mock=1`: sahte log listesi + 2 dk sahte kare (kalkış, daire, iniş).
## 9. Gerçek topoğrafya (`world.mode = "real"`; `app/sim_terrain.py`, ön yüz `loadRealTerrain`)
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

## 10. Askeri tarz FPV HUD (`static/js/modules/flightsim_hud.js`)
Kamera kipi **Dron kamerası (2)** seçilince 3B'nin üstünde tam ekran şeffaf bir canvas katmanı (`.fs-mhud`, canvas 2D, devicePixelRatio,
her rAF) açılır; diğer kiplerde kapanır ve çizim döngüsü durur. Açıkken sahnede `fs-mhud-on` sınıfı: sağdaki uçuş veri paneli ve ÇARPIŞMA
bandı gizlenir (HUD kapsar). **H** aç/kapa (kapatınca panel geri gelir), **Shift+H** renk (yeşil fosfor `#9cff6a` → beyaz → amber);
alt çubukta FPV'de görünen "HUD" düğmesi; tercihler `localStorage` (`fs.mhud.on`, `fs.mhud.color`). Tüm çizgiler/metinler ince siyah dış
çizgili (okunabilirlik), monospace; metin ölçümü yok (hizalama `textAlign`); yerleşim ölçümleri (alt çubuk, Mission Planner/kayıt kutusu
yüksekliği) 30 karede bir. Ölçüm (SwiftShader, 1360×820): ≈1.7 ms/kare çizim.
- **Öğeler:** suni ufuk + pitch merdiveni (±90°, 5° adım; pozitif düz / negatif kesikli; roll ile döner; zenit ●/nadir ✕; klipsli),
  roll yayı (±60°, çentikler 10/20/30/45/60, gökyüzü işaretçisi üçgen, "R 6°"), boresight (W), uçuş yolu vektörü (vn/ve/vd: iz−yön sapması,
  uçuş yolu açısı; daire + kanatçık + kuyruk; ≥ 1 m/s; ekran kenarında kesikli halka), heading şeridi (±35°, 5° çizgi, 10° sayı, N/E/S/W,
  merkez üçgen + "248" kutusu, ev yönü **H** işareti, rüzgâr oku + hız/yön), sol hava hızı bandı (±20 m/s; kutu m/s, altında km/h; üstte
  "IAS m/s", altta "GS"), sağ irtifa bandı (AGL ±60 m; kutu; "MSL 1207"; altta radar irtifa "R 157"), dikey hız çubuğu (±10 m/s karekök
  ölçek + sayı), sol alt (mod, ARM/SAFE, G ≈ 1/cos(roll) yalnız uçak + armed + hava hızı > 5, THR % çubuk, BAT V/%, GPS/SAT), sağ alt
  (UTC "14:34:01 Z", T+ oturum süresi — kayıtta log zamanı, lat/lon 5 ondalık, "HOME 473 m 175°", "GMB −10°", tuş ipucu), üst sağ
  (● REC yanıp söner — kayıtta "REC ▸ PLAY", "CAM 1 · EO", "FOV 78°"), köşe çerçeveleri, merkez hedef kutusu (görsel; hedefleme yok).
- **Veri:** `createMilHud(stage, ctx, { tr })`; `hud.update(tele)` flightsim.js'teki her `tele` / replay karesi (aynı biçim); `ctx` getter'lı:
  `pose` (3B'nin render ettiği enterpolasyonlu yönelim `sim.getPose()` → {roll, pitch, yaw} rad; yoksa tele), `gimbalDeg`, `camMode`,
  `collision`, `world` (rüzgâr), `session`, `t0`, `replay`, `fov`. Kamera ekseni = pitch + gimbal; ppd = H / fov.
- **Uyarılar** (üst orta, kırmızı kutular; dolgu yanıp söner, metin hep okunur): **ÇARPIŞMA** (ctx.collision), **RC YOK** (SITL kipi,
  armed, rc boş/0), **BATARYA** (< %25), **GCS KESİLDİ** (SITL kipi, daha önce bağlanmış GCS `gcs_connected:false`), **ALÇAK** (armed,
  AGL < 60 m, yer hızı > 3 m/s; "R" değeri de kırmızı yanıp söner). Sahte sensör gürültüsü, vinyet, tarama çizgisi yok.
- **i18n:** uyarı metinleri ve ipuçları `tr()`; ARM/SAFE/HOME/REC/CAM/AGL/MSL/IAS/GS/THR/BAT/GPS/GMB sabit (askeri jargon). Doğrulama:
  `?mock=1` + Playwright (`/tmp/flsim/hud_shots.py`): yerde, tırmanış + ALÇAK, yatış, gimbal, renkler, H kapatma, 900×600, kayıt kipi.
