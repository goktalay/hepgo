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
{"seed": 12345, "size_m": 4000, "tree_density": 0.3, "mountain_height": 300, "mountain_count": 4, "building_count": 40,
 "runway": true, "runway_heading": 0, "water": 0.1, "time": "day|dusk|night", "wind_ms": 3, "wind_dir": 270, "fog": 0.2}
```
Sunucu rüzgârı SITL'e yazar: `SIM_WIND_SPD`, `SIM_WIND_DIR`.

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
3. Dünya: kaydırıcılar/seçimler (yukarıdaki `world`), "Rastgele tohum", önizleme (küçük 3B). 4. Başlat → oturum ekranı.
Açık oturum varsa liste: devam et / bitir. 8 dil (i18n.*.js; sözlük dosyaları modül olarak `node --check` ile denetlenir).

## 7. Testler
- `tests/test_flightsim.py`: meta (tipler, merkezler), oturum açma/limit/kapama (SITL yoksa 503), komut yetkisi (salt okuyan 403),
  WS hello/tele (SITL olmadan `HEPGO_SITL=0` ile sahte telemetri üreticisi), UDP köprüsü (yerel soket ile ham bayt gidiş-dönüş, GCS kilidi).
- Kayıttan oynatma (§8): pymavlink ile yazılan küçük .tlog → ayrıştırıcı (kare sayısı, ev = ilk ARM, mod adı, olaylar), `GET /logs`
  yetki kesişimi, `POST /sessions {mode:'replay'}` → HAZIR, `GET /sessions/{id}/replay` gzip JSON, WS'te `tele` yok, `cmd` yalnız `reset`.

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
