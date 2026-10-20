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
| `GET /meta` | `{types:[{key,name,binary}], centers:[{id,name,lat,lon,alt,location_name}], world_defaults, limits:{max_sessions,max_minutes}, host, google3d:{enabled}}` — `host`: Mission Planner'a verilecek adres (`SIM_PUBLIC_HOST` env, yoksa istek Host başlığının ana makinesi); `google3d.enabled`: `GOOGLE_MAPS_API_KEY` tanımlı (§10) |
| `GET /g3d-key` | `{key}` — Google Map Tiles API anahtarı (§10); `Cache-Control: no-store`; kip kapalıysa 404; salt okuyan izleyici de alır (karoları çizmek için) |
| `GET /sessions` | Kiracının açık oturumları `[session]` |
| `POST /sessions` | `{type, center_id, world, model?, drone_id?, rec?, power?}` → `session` (201). `model`: `{id, orient?}` ya da kimlik dizgesi (§12; eksikse tipin varsayılanı; eski `airframe: caymaz|delta` → `builtin:…` eşlenir). `power` (§23): `{max_speed_ms, fuel_l, fuel_km_per_l, elec_cells, elec_mah, elec_w}` — eksikler dron kaydı önerisi → tip varsayılanı. Hatalar: 400 `invalid`, 409 `limit`, 503 `sitl` (ikili/port yok) |
| `/models…` | Görsel model kütüphanesi (§12): liste, yükleme, tasarım dosyasından ekleme, GLB/küçük resim PUT-GET, yönelim, silme |
| `GET /sessions/{id}` | `session` |
| `DELETE /sessions/{id}` | durdurur (SITL kapanır, UDP kapanır) → `{ok}` |
| `POST /sessions/{id}/cmd` | `{name, params}`; name ∈ `arm` (force), `disarm`, `mode` (`params.mode` ArduPilot mod adı), `takeoff` (`params.alt`; sabit kanatta yönteme göre dizi + WS `launch` olayları, §13), `rtl`, `reset` (SITL'i aynı ayarlarla yeniden başlatır), `crash` (ön yüz çarpışma: zorla disarm + olay), `set_home`, `rc` (`params.ch` 8 kanal 1000–2000, RC_CHANNELS_OVERRIDE; ileride Gamepad), `speed` (`params.factor` 1 \| 2 \| 4 \| 8 → SITL `SIM_SPEEDUP` canlı, §23) → `{ok}` |
| `GET /power-defaults?type&drone_id` | §23 sihirbaz "Güç ve yakıt": `{type, defaults, suggested, from_drone, limits, stock_max_ms, thr_mul, thr_scale_supported, speedups}` |
| `GET /drones` | sihirbaz dron kaydı listesi; her satırda `power` (dron kaydındaki güç/yakıt önerisi, §23) |
| `GET/PUT /api/drone/drones/{id}/sim-power` | dron kaydı güç/yakıt seçenekleri (`drone_sitl_options`: max_speed_ms, fuel_l, fuel_km_per_l_last, elec_cells, elec_mah, elec_w_last; PUT yalnız gönderilen alanlar, `null` siler; §23) |

`session` = `{id, type, model:{id,name,source,type,orient,glb_url,thumb_url,has_prop,ready}, airframe, center:{id,name,lat,lon,alt}, world,
state: 'BASLIYOR'|'HAZIR'|'HATA'|'KAPANDI', udp_port, host, created_at, owner:{id,name}, gcs:{connected:bool, addr:"ip:port"|null, since}, sitl:{pid, port, error}}`
(`airframe` geriye uyum: dahili `builtin:caymaz`/`builtin:delta` için uçak tiplerinde `caymaz`/`delta`, aksi `null`).

`world` (ön yüz üretir, sunucu doğrular ve saklar; deterministik):
```json
{"mode": "procedural|real|google3d", "seed": 12345, "size_m": 4000, "tree_density": 0.3, "mountain_height": 300, "mountain_count": 4,
 "building_count": 40, "runway": true, "runway_heading": 0, "water": 0.1, "time": "day|dusk|night", "wind_ms": 3, "wind_dir": 270, "fog": 0.2,
 "launch": {"method": "wheels|ramp|vehicle", "angle_deg": 15, "release_kmh": 70}}
```
`launch`: sabit kanat kalkış yöntemi (§13; `session.launch` aşama ile döner).
Sunucu rüzgârı SITL'e yazar: `SIM_WIND_SPD`, `SIM_WIND_DIR`. `mode: "real"` (§9) ve `"google3d"` (§10): merkez irtifası (`center.alt`) boşsa SITL ev irtifası
terrarium karosundan (`sim_terrain.ev_irtifa`, 12 sn üst sınır; alınamazsa `EV_IRTIFA`) alınır ve `session.center.alt` olarak döner.
`google3d` yalnız `GOOGLE_MAPS_API_KEY` tanımlıyken kabul edilir (aksi hâlde 400 `invalid`).

## 3. WebSocket (`/ws/drone/sim/{id}`, oturum çerezi; drone_hub `_ws_user` kalıbı)
- Bağlanınca `{t:'hello', session}`; yetkisiz `{t:'error',error:'auth'}` + 4403; oturum yoksa 4404.
- `{t:'tele', ts, tbm, tbm_pos, lat, lon, alt_msl, alt_rel, roll, pitch, yaw (rad), rs, ps, ys (rad/s; ATTITUDE roll/pitch/yawspeed), vn, ve, vd (m/s),
  airspeed, groundspeed, heading (deg), climb, mode, armed, gps_fix, sats, batt_v, batt_pct, throttle (%), rc:[8 kanal], home:{lat,lon,alt},
  gcs_connected, gcs_addr}` — **olay güdümlü**: gerçek SITL'de her ATTITUDE / GLOBAL_POSITION_INT geldiğinde (50 Hz tavan; 250 ms sessizlikte
  bekçi yayını), sahte kipte 50 Hz. `ts` sunucu alım zamanı (Unix sn, 3 ondalık), `tbm` SITL `time_boot_ms` (sahte: oturum ms); `tbm_pos` konum
  alanlarının damgası (son GLOBAL_POSITION_INT `time_boot_ms`; kare ATTITUDE'da yayınlandığından yönelimle farklı zamanlıdır — istemci iki
  alanı ayrı zaman çizgilerinde enterpole eder, §5; sahte kipte `tbm` ile aynı). Sayılar
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
- Dron: görsel model `session.model` (§12 kütüphanesi; `setType(type, model)`): dahili `builtin:caymaz` → `static/models/caymaz-sim.glb`
  (CAYMAZ V3 STEP montajından `tools/step2glb.js` ile; kanat açıklığı 3,03 m, arkadan itişli, `prop` düğümü döner; KHR_mesh_quantization,
  ~1,5 MB), `builtin:delta` → prosedürel delta uçan kanat (2,2 m, elevonlar).
- **Kontrol yüzeyleri (Caymaz GLB + delta + kütüphane GLB'si; ortak katman `updateCtrl`)**: STEP montajındaki arka kenar parçaları FL1/FR1
  (dış, X 911…1450 mm) → `elevon_l`/`elevon_r`, FL2/FR2 (iç, X 370…908 mm) → `flap_l`/`flap_r` gövdeyle birleştirilmez; her biri ayrı GLB düğümü,
  düğüm orijini = menteşe pivotu (yüzeyin kanada bakan ön kenarının ortası, Z ortası; glTF m: elevon_l [1,147, −0,004, −0,962], flap_l [0,674, −0,001,
  −0,959], elevon_r [−1,146, −0,004, −0,962], flap_r [−0,676, −0,001, −0,962]; kord 0,138 m, açıklık 0,539 m), yerel X = menteşe ekseni (ön kenar
  köşelerinin PCA'sı; düz arka kenar → gövde Y'ye dik), `extras {surface, side, hinge:'x', te_down:-1}` (yerel X etrafında negatif dönüş arka kenarı
  aşağı indirir). Kuyruk/rudder parçası montajda yok (uçan kanat); eklenirse `CTRL_PARTS` satırı (rudder_l/r, dikey menteşe). Kütüphane GLB'lerinde de
  `elevon|flap|aileron|elevator|rudder[_l|_r]` adlı düğümler aynı katmanla oynar. **Kaynak önceliği**: `tele.servo` (SERVO_OUTPUT_RAW 1…8 µs; sunucu
  `MESAJ_ARALIKLARI` ile 20 Hz ister; ArduPlane SERVO1 aileron, SERVO2 elevator, SERVO4 rudder, flap SERVO5/6 — `tele.servo_fn` verilirse işlev
  kodlarına (4/19/21/2/3/77/78) göre), yoksa `tele.rc` (sahte kip, kayıt). **Eşleme** (ArduPilot SERVOn_MIN/TRIM/MAX 1100/1500/1900): ±400 µs → ±1;
  aileron + = sağa yatış (sağ yüzey arka kenar yukarı, sol aşağı), elevator + = burun yukarı (arka kenar yukarı), rudder + = sağa; uçan kanatta elevon
  L = e − a, R = e + a (ArduPlane `channel_function_mixer`; SITL zaten karışımı verir, servo_fn 77/78 ise doğrudan); açılar elevon/aileron/elevator/rudder
  ±25°, flap 0…+35° yalnız aşağı (1100 → 0 %, 1900 → 100 %; işlev atanmamış kanal da 1100 verir → 0). Servo hızı 400°/s (60°/0,15 s) + 40 ms
  1. derece gecikme; disarm → nötr. **Flap**: TAKEOFF'ta `TKOFF_FLAP_PCNT`, LAND'de `LAND_FLAP_PERCNT` SERVOn_FUNCTION 2/3 atanmış kanala SITL'den
  yansır; flap kanalı dinlenmede / servo yoksa moddan öykünür (TAKEOFF %50, LAND/QLAND %100). Teşhis: `sim.ctrlState()` → {source, armed, mode, servo,
  rc, inputs, surfaces[{name, deg (arka kenar aşağı +), tgt}]}; `window.__fsSim` (`?netsim=delay0`). `builtin:quad` 60 cm / `builtin:hexa` 90 cm /
  `builtin:heli` 1,5 m prosedürel (gövde, kollar, motorlar, iniş takımı, gimbal; pervaneler gaz ile döner, yüksek devirde bulanık disk). VTOL = gövde + 4 dikey
  pervane. Kütüphane modeli (tasarım/yüklenen) → GLB fetch + yönelim matrisi + ölçek + `drone.ground` sınır kutusu altından (§12). Seyir ışıkları (sol kırmızı / sağ yeşil / kuyruk beyaz strobe, gece halo), yalnız dron gölge düşürür. Yönelim: roll/pitch/yaw →
  quaternion (NED→ENU dönüşümü dikkat). `caymaz.gltf` (eski basit model) yalnız Cesium oynatma/canlı izlemede (replay3d.js) kullanılır.
- Kameralar (tuşlar 1–5, **C** döngü; seçim `localStorage fs.cam` ile oturumlar/kayıtlar arası kalıcı): **Takip** (3. şahıs, OrbitControls hedefi dron),
  **FPV** (`pilot`; pilot gözü — burna sabit, gövdeyle döner, ufuk yatar, OSD; §22), **Gimbal kamerası** (`fpv`; burun, gimbal pitch ↑↓/tekerlek, askeri HUD §10),
  **Serbest** (WASD + fare), **Yer** (merkezden, dronu izler). Çarpışma: `z < h(x,y) + 0.3` ya da bina kutusuyla kesişme ve hız > 1 m/s
  → kırmızı "ÇARPIŞMA" bandı + `cmd crash`; oturum "Sıfırla" ile yeniden başlar.
- HUD (3B üstünde, sağ): mod, arm, yükseklik (AGL/MSL), hava/yer hızı, dikey hız, yön, GPS/uydu, batarya, gaz, RC çubukları, rüzgâr;
  **Mission Planner bağlantısı** (`UDP <host>:<port>`, "Bağlı (ip)" / "Bekleniyor"; Kopyala; kısa talimat) harekât panelinin MISSION PLANNER
  bölümünde; panel kapalı/FPV'de sol altta koyu yüzen kutu (§14).
- Performans: 60 fps hedef; arazi 256×256 ızgara, LOD yok (gerçek kipte ek 192×192 "uzak arazi" halkası, §9); ağaç ≤ 20.000 örnek.
- Sis / görüş uzaklığı (`skyAndLights(size, horizon)`): prosedürelde `Fog(size·0,12 … size·(1,6 − 1,25·fog))` (dünya kenarında biter). Gerçek arazi
  ve Google 3B kipinde ufuk dünya boyutuna değil **görüş uzaklığına** bağlıdır: `far = horizon·(1,25 − fog)` (`horizon` = uzak arazi yarıçapı 24 km /
  Google 30 km; fog 0,2 → 25 km, fog 1 → 6 km; fog 0 → sis yok), `near = 0,12·far`. Eski formül 4 km dünyada sisi 5,4 km'de kapatıyordu → 20 km'deki
  dağlar iki kipte de hiç görünmüyordu ("dağlar gerçek yüksekliklerini göstermiyor" geri bildiriminin kök nedeni; §9/§11). Kamera `far` 60 km.
- Akıcılık (`static/js/modules/flightsim_interp.js`, `createTimeline`): **uyarlanır gecikme tamponlu enterpolasyon**. Zaman ekseni KAYNAK
  zamanıdır (`tbm`; yoksa `ts`/alım): oynatma başı (`play`, kaynak ms) her render karesinde geçen gerçek süre × hız oranı kadar ilerler; hedefi
  "son kare − hedef gecikme"dir ve ona yalnız hız oranıyla (±%6; hatanın 400 ms EMA'sı) yaklaşır → saat ofseti kestirimi yok, SITL saat sapması ve
  ağ jitter'ı ileri-geri sıçrama üretmez (|hata| > 1 s ya da `tbm` 1 s'den çok geri gidince yeniden senkron). **Hedef gecikme** = 60 ms + 3 × jitter
  (EMA; jitter = |alım aralığı − kaynak aralığı|), en az 2 kaynak kare aralığı ve 1,5 render karesi, 60…300 ms, saniyede ±10 ms (HUD net satırı:
  `net: 48 Hz · jitter 3 ms · tampon 72 ms`, DR = ölü hesapta). **Konum ve yönelim ayrı zaman çizgileri**: `tbm_pos` (GLOBAL_POSITION_INT) ve
  `tbm` (ATTITUDE) — sunucu karesi iki mesajı farklı damgalarla birleştirir; tek çizgide konum ±20 ms ileri-geri giderdi (30 m/s'de 0,6 m). Kareler
  kaynak zamanına göre **sıralı** eklenir (sırası bozulan kare yerine oturur). Tampon biterse ölü hesap (hız + gövde açısal hızları `rs/ps/ys`, en çok
  300 ms); ölü hesaptan gerçek kareye dönüşte ve her beklenmedik sıçramada fark 130 ms içinde **yumuşak kapanır** (konum lerp, yönelim slerp —
  "atlama" yok; > 60 m / > 100° teleport doğrudan). Kare hızından bağımsız (rAF gerçek süresi, kırpılmamış; pervaneler/tekerlekler de kırpılmamış
  süreyle döner, 2π'ye sarılır). Takip kamerası hedefi kritik sönümlü yayla izler (ω = 2π·1.5; 1/120 s alt adımlarla, düşük kare hızında kararlı).
  Teşhis: `#/drone/sim/<id>?netsim=jitter30,loss5,delay40` gelen kareleri delay + U(0, 2·jitter) ms gecikmeyle (sıra bozulabilir) iletir, %loss
  düşürür ve `window.__fsSim` verir (`netStats()`: hz, jitter, delay, deadReckoning, drEnters, drPerMin, snaps; `motionStats(reset)`: ardışık
  render kareleri arası yönelim farkı ° — ortalama/maks, "jerk" = ardışık farkların farkı, konum farkı, DR giriş/kare sayısı). Tarihçe: canlı
  sunucuda (Cloudflare tüneli, jitter ≈ 24 ms) sabit 80 ms tampon + "en küçük alım−kaynak farkı" ofseti tamponu boşaltıp sık ölü hesaba düşürüyor,
  DR → gerçek kare geçişi sert atlıyordu ("sürekli titriyor"; FPV'de tüm sahne) — `tests/test_flightsim_interp.mjs` eski/yeni karşılaştırması.
- Sanal kumanda (alt çubuk 🎮, yazma izni): iki yarı saydam çubuk (sol gaz/yaw, sağ pitch/roll; Mode 2; dokunmatik + fare) + klavye
  (W/S gaz, A/D yaw, ↑↓ pitch, ←→ roll — yaylı dönüş; Q/E ch5 mod anahtarı 1000/1500/2000; Boşluk gaz 1500). Kopterde gaz çubuğu merkeze
  yaylı (askı), uçakta tutmalı. 20 Hz `{t:'rc', ch}` yalnız açıkken; kapatınca / sayfadan çıkınca tek sefer 8×0. Açıkken 3B'nin WASD/ok
  tuşları kilitlenir (kamera 1–4 çalışır); HUD RC çubukları 1–5 yerel değerleri gösterir (mor). Yön uzlaşımı (gerçek SITL ile ölçüldü):
  sol çubuk EN ÜST → ch3 2000 (SITL RC_CHANNELS 2000, FBWA'da SERVO3 1900, HUD Gaz %100), EN ALT → 1000 (%0); W gazı artırır. Uçakta
  çubuk yerde/disarm'da altta (1000) başlar; kumanda **uçuş sırasında** (armed) açılırsa `throttle0` = telemetri gazı → çubuk o gazda başlar
  (ArduPlane TAKEOFF/AUTO gazı RC'den bağımsız verir: çubuk altta iken HUD %100 "ters" görünmesin, FBWA'ya geçişte gaz aniden kesilmesin).
  Elevon yönü (SITL ölçümü): ch2=2000 → SERVO2 1835 → uçuşta pitch −4°→+19° (burun yukarı) → elevon `deg` −20,9 = arka kenar YUKARI
  (Caymaz GLB `te_down` −1 ve delta +1 tutarlı); roll sağa: sol elevon +25 (TE aşağı), sağ −22,7 (TE yukarı). Kalkışta flaplar AŞAĞI (+17,5°,
  `TKOFF_FLAP_PCNT` 50) — ArduPlane uzlaşımı, ters değil.

## 6. Kurulum sihirbazı — adım adım (`flightsim.js wizardModal`; saf mantık `flightsim_wizard.js`, görsel girişler `fs_inputs.js`)
Kullanıcı isteği (birebir): "HEPGO'da yeni simülasyonu başlattığımızda çok karışık görünüyor; onun yerine sihirbaz ile yapalım, aşama aşama girsin." ·
"Yeni özellik sihirbazında basit inputları daha görsel hale getirelim; mesela sayısal girişleri slider şeklinde çevirelim."

**Düzen.** "Yeni Simülasyon Başlat" penceresi (sabit yükseklik, adım değişince zıplamaz): üstte yapışkan bant — **Kip** kapsülü (Canlı simülasyon /
Kayıttan oynat) + **ilerleme şeridi** (numaralı adımlar; geçilmiş ve geçerli olan yeşil ✓, geçilmiş ama sonradan geçersizleşen kırmızı !, geçerli adım
mavi halkalı; altında ilerleme çizgisi). Şeritte geri adımlara her zaman, ileri adımlara yalnız aradaki adımlar geçerliyse tıklanır (`canGoto`). Gövde:
solda adım başlığı ("Adım 2 / 8", başlık, isteğe bağlı rozeti, tek satır açıklama) + yalnız o adımın alanları; sağda **3B önizleme** (Araç / Uçuş logu /
Dünya / Kalkış adımlarında görünür; diğerlerinde gizlenir ama yaşar — model küçük resimleri ve hedef kartı önizlemeleri aynı WebGL bağlamını kullanır).
Altbilgi: **İptal et** · gerekçe metni · **‹ Geri** · **İleri ›** (son adımda **▶ Başlat** / kayıtta **▶ Oynat**). Klavye: **Enter = İleri** (son adımda
Başlat; metin alanı/seçim/bağlantı/altbilgi/şerit ve sayı kutularında değil — sayı kutusunda Enter değeri uygular), **Esc = kapat** (sayı kutusunda
önce düzenlemeyi geri alır). ≤ 860 px (telefon/dar tablet): tek sütun, önizleme içeriğin altında, şeritte yalnız geçerli adımın adı, düğmeler tam
genişlik ve gerekçe kendi satırında; 860–1100 px önizleme sütunu 320 px.

**Adımlar (sıra ve gerekçe).** Canlı: **1 Araç** (tip kartları · dron kaydı · görsel model · kontrol düzeni [yalnız sabit kanat]) → **2 Dünya ve konum**
(merkez listesi + dünya kipi/kaydırıcılar + önizleme) → **3 Kalkış** (yalnız kalkış seçeneği olan tiplerde; bugün sabit kanat) → **4 Güç ve yakıt** →
**5 Kamera** → **6 Hedefler** (isteğe bağlı) → **7 Yer kontrol** (isteğe bağlı) → **8 Kayıt ve özet**. Gerekçe: araç her şeyi belirler (hangi adımların
görüneceği, güç varsayılanları, kamera önerisi dron kaydından, model → kontrol düzeni) → dünya pist yönünü ve kalkış noktasını kurar, kalkış düzeneği o
pistte önizlenir → güç bütçesi araç + kalkıştan sonra → kamera, hedefler ve yer kontrol uçuşun "görev" katmanı (isteğe bağlı olanlar sonda, atlanabilir)
→ son adımda kayıt seçenekleri ve özet. Kayıttan oynat: **Uçuş logu** (+ model) → **Dünya ve konum** → **Kalkış** (log aracı sabit kanatsa) →
**Kamera** → **Kayıt ve özet** (güç/hedef/yer kontrol kayıttan gelir). Tip/kip değişince adım listesi yeniden hesaplanır (`wizardSteps`); kaybolan
adımdaysanız en yakın önceki adıma geçilir (`reconcileStep`); kip değişince ilk adıma dönülür.

**Doğrulama.** `valid(adım)`: Uçuş logu (erişim yok / yükleniyor / seçilmedi), Dünya (canlıda merkez yok → "Bir merkez seçin." ya da merkez yoksa
Rotalar › Merkezler yönlendirmesi), Hedefler (`targetsSec.error()`), Yer kontrol (`siteSec.error()`), Özet (yazma izni yok). Geçersiz adımda İleri pasif,
gerekçe altbilgide kırmızı; son adımda ilk geçersiz adım "Adım: gerekçe" olarak yazılır ve Başlat pasif. Başlat'taki eski denetimler (log/merkez/hedef/saha)
korunur; hata olursa ilgili adıma dönülür. Alan değişimleri (tıklama/girdi) şeridi ve altbilgiyi kare başına bir kez yeniler.

**Özet adımı.** Görünür her adım için kart (numara, başlık, **Düzenle** → o adıma atlar): Araç (tip, model, kontrol düzeni, dron kaydı) · Uçuş logu
(dosya, araç, süre, model) · Dünya (merkez + koordinat, kip + boyut, saat, rüzgâr, sis, pist) · Kalkış (`launchLabel`) · Güç (azami hız, yakıt L · km/L,
batarya S · mAh · W) · Kamera türü · Hedefler (sayı, modeller, önleme yarıçapı) · Yer kontrol (saha, görev). Geçersiz adımın kartı kırmızı çerçeveli.
Altında §17/§19 **Kayıt** kutusu (ekran kaydı › paylaş · .bin; anahtar görünümlü onay kutuları) ve oturum sınırı notu.

**Görsel girişler (`fs_inputs.js numSlider`).** Her sayısal alan: etiket + sağda **düzenlenebilir değer kutusu** (virgül kabul; Enter/odak kaybı uygular,
Esc geri alır, ↑/↓ adım, Shift ×10) + birim, altında **dolu izli kaydırıcı**. Değer her zaman [min, max]'a kırpılır ve adıma oturtulur — sınırlar eskisiyle
aynı (sunucuya giden değerler ve sunucu doğrulaması değişmedi). Geniş aralıklar **logaritmik** (konum ↔ log(v + o); 0 içeren aralıklarda kaydırma `o`;
kaydırıcıdan gelen değer 2 anlamlı basamağa "güzel" yuvarlanır): yakıt 0–500 L, tüketim 0,5–500 km/L, kapasite 100–200 000 mAh, saatlik tüketim 0–2000 W,
hedef irtifası 10–3000 m, yörünge çapı 50–5000 m. Doğrusal: azami hız 5–150 m/s, hücre 1–16 S (tam sayı), dünya boyutu, ağaç/su/sis (% olarak gösterilir,
sunucuya 0–1), dağ yüksekliği/sayısı, bina sayısı, rüzgâr hızı/yönü, pist yönü, iniş dairesi, fırlatma açısı 10–30°, bırakma hızı 40–110 km/h, hedef hızı
(km/h, azami = modelin azami hızı), merkez doğu/kuzey ofseti, önleme yarıçapı 5–200 m. Seçimler kart (tip, kalkış, kontrol düzeni, merkez, kamera, saha)
ya da segment (dünya kipi, saat, hedef yönü); aç/kapat alanları HEPGO'nun genel anahtar görünümü. Yer kontrol bölümü (§26) zaten kaydırıcı + sayı
kutusuydu (SIMUMAV ile ortak modül; dokunulmadı).

**§27 INTERCEPTOR'da** Kalkış adımı fırlatıcı kartlarıdır (4'lü / 8'li / yerden tekli / el fırlatıcısı; 2×2 ızgara, açıklama metni tipe göre `launchStepDesc`;
dolu hücre `loaded4`/`loaded8` → `loaded`, el fırlatıcısında nişan yönü/açısı; önizleme düzeneğin çevresinde döner). **Kalkış seçenekleri veriden.** `flightsim_wizard.js LAUNCH_OPTIONS` = `[{ key, types, name, desc, params, icon, note? }]` (bugün `wheels` / `ramp` /
`vehicle`, `types: ['sabit_kanat']`, ad/açıklama `flightsim_launch.LAUNCH_METHODS`'tan) + `LAUNCH_PARAM_DEFS` (`angle_deg`, `release_kmh`: etiket, min,
max, adım, birim). Kalkış adımı `launchOptionsFor(tip)` boş değilse görünür; kartlar ve görünen ayar kaydırıcıları bu listeden üretilir; tip değişince
seçili yöntem o tipte yoksa ilk seçeneğe geçer (`normLaunchMethod`). **Yeni fırlatıcı eklemek** (ör. INTERCEPTOR 4'lü / 8'li fırlatıcı, yerden tekli, el
aparatı): `LAUNCH_OPTIONS`'a satır (`types: ['interceptor']`), gerekiyorsa `LAUNCH_PARAM_DEFS`'e ayar, `flightsim.js LAUNCH_ICON`'a simge; sunucu
`world.launch` doğrulaması ve 3B düzenek ayrıca.

**Son seçimler.** Mevcut hatırlamalar aynen: kamera türü/paleti (`createCamPrefs`), kayıt seçenekleri (`recPrefs`), yer kontrol sahası (`fs.site.*`).
Ek: Başlat'ta (canlı) **tip, merkez ve kalkış yöntemi/ayarları** `caymaz.fs.wz.last`a yazılır, sonraki açılışta önerilir (bilinmeyen tip/merkez ya da
sınır dışı değer yok sayılır). Oturum başlatma isteği gövdesi DEĞİŞMEDİ (`mode, type, center_id, world{…, launch}, model, drone_id, rec, power, layout,
camera, targets, site, defend` / kayıtta `mode, log_id, world, model, camera`).

**Test kancası.** `window.__fsWz` → `{ goto(adım) (doğrulamasız), steps, step }` (görsel betikler: `tests/wizard_shots_hepgo.py`,
`gcs_shots_hepgo.py`, `tgthud_shots_hepgo.py`, `icept_shots_hepgo.py`). `#/drone/sim?new=1` pencereyi açık getirir.

Başlat → **ön hazırlık kartı** (§8: sunucu HAZIR + kareler + dünya verisi) → oturum ekranı. Açık oturum varsa liste: devam et / bitir; "Yarım kayıt" ve
"Kayıtlarım" kutuları (§17). 7 dil (i18n.*.js; sözlük dosyaları modül olarak `node --check` ile denetlenir).

## 7. Testler
- `node tests/test_flightsim_wizard.mjs` (tarayıcısız, §6): adım listesi (kip/tip; kopterde Kalkış yok, kayıtta Güç/Hedef/Yer kontrol yok), veriden kalkış
  seçenekleri (yeni fırlatıcı eklenince adım açılır), `canGoto`/`reconcileStep`/`createStepper` (İleri doğrulamaya bağlı, şerit durumları), `fs_inputs`
  (sayı ayrıştırma — virgül, adım/sınır oturtma, logaritmik ölçek gidiş-dönüş, 0 içeren log aralığı, değer kutusu uygulama). Görsel + uçtan uca:
  `./.venv/bin/python -m tests.wizard_shots_hepgo` → `/tmp/wizard-shots` (açık/koyu × masaüstü/tablet/mobil, her adım; sihirbazdan gerçek Başlat ve gövde denetimi).
- `node tests/test_flightsim_interp.mjs` (tarayıcısız; vendor three.module): telemetri zaman çizgisi (§5) — sentetik 50 Hz sabit kanat dairesi
  (ATTITUDE/GLOBAL_POSITION_INT farklı damgalı), ağ bozulması (jitter 30/60 ms, %5/%10 kayıp, sırası bozuk teslim, SITL saati %3 yavaş), 60/25
  fps sanal rAF; eski algoritma (9e639ef) aynı arayüzle karşılaştırılır: yeni jerk ≤ 0,02°, DR ≤ 2/dk, maks adım < 4× ideal, yarım karede konum
  jerk < eski/2, sıralı ekleme, saat sıfırlama. Sonuç (jitter 30 + %5 kayıp, 60 fps): jerk 0,053° → 0,0009°, maks adım 0,44° → 0,14°, konum jerk
  0,23 m → 0,0006 m; kötü tünel (60 ms, %10): DR 92/dk → 0.
- `tests/test_flightsim.py`: meta (tipler, merkezler), oturum açma/limit/kapama (SITL yoksa 503), komut yetkisi (salt okuyan 403),
  WS hello/tele (SITL olmadan `HEPGO_SITL=0` ile sahte telemetri üreticisi), UDP köprüsü (yerel soket ile ham bayt gidiş-dönüş, GCS kilidi).
- Kayıttan oynatma (§8): pymavlink ile yazılan küçük .tlog → ayrıştırıcı (kare sayısı, ev = ilk ARM, mod adı, olaylar), `GET /logs`
  yetki kesişimi, `POST /sessions {mode:'replay'}` → HAZIR, `GET /sessions/{id}/replay` gzip JSON, WS'te `tele` yok, `cmd` yalnız `reset`;
  oturum açılır açılmaz `center` analiz özetindeki ev (kök neden testi), `world.mode:'real'` kabul, HAZIR'da `center` = ayrıştırılan ev.
- Kayıt saklama (§17 `rec_sakla_testleri`): `finish {share:false}` → feed'e paylaşım yok, `kept`; `GET /rec/mine` listesi; `GET /rec/{id}/file`
  indirme (salt okuyan 403, bilinmeyen 404); `pending`'e düşmez; `temizle` 24 saat kuralını saklanana uygulamaz (KEEP_S aşımında siler);
  `POST /rec/{id}/share` → feed paylaşımı (saklanan metin), listeden düşer; sil.
- .bin uçuş logu (§19 `bin_testleri`): `drone_sitl.parm_metni` (LOG_BACKEND_TYPE 1 / LOG_DISARMED 0 / LOG_FILE_DSRMROT 1; kapalıyken 0), `rec`
  doğrulama, `session.rec`, sahte .BIN dosyalarıyla (`MANAGER.sahte_bin_dosyalari`) kapanış → `flight_logs` satırı (aircraft "Simülatör · Multikopter",
  pilot sahip, location merkez, dosya `UPLOAD_DIR/flightlogs/`), DELETE yanıtı `bin`, analiz kuyruğu, boyut sınırı (`error`, dosya silinir), dosya yok → null.

- Kalıcı parametreler (§20 `param_testleri`): dron kaydıyla oturum → hub `param_set` → kayıt (hepgo, kullanıcı); UDP PARAM_SET + sahte SITL
  PARAM_VALUE yankısı → kayıt (mp); hariç tutulanlar kaydedilmez; tabandan farklı → sitl; parm içeriği; reset sonrası PARAM_SET yazımı; yükleme
  yankısı yeniden kaydetmez; export/import/sil/sıfırla; salt okuyan 403; dron kaydı seçilmeyen oturumda `tracked:false`.
- Görsel model kütüphanesi (§12, `model_testleri`): dahili liste (tip filtresi, VTOL adları), yükleme (küçük GLB zarfı / STEP / geçersiz uzantı),
  GLB PUT (başlık denetimi, 413), küçük resim PUT-GET (PNG; dahili VTOL varyantı), yönelim doğrulama (aynı eksen 400), oturumda model (bilinmeyen /
  tip uyumsuz / GLB'siz 400; oturuma özel yönelim kütüphaneyi değiştirmez), geriye uyumlu `airframe`, yetki (salt okuyan 403; `design` modülsüz
  `design-files` 403), tasarım sürümünden ekleme (tek kayıt; silmede özgün dosya kalır), kayıt kipinde model.
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
  type, flight_s, duration_s, takeoff_utc, start_utc, home_lat, home_lon, cached, source, origin}]` (`origin` SIM | REAL — §19) · `POST /sessions {mode:'replay', log_id, world}` →
  `session` (201; 400 log yok/yetkisiz/analiz bitmemiş/biçim; 409 limit) · `GET /sessions/{id}/replay` → gzip JSON kareler
  (`Content-Encoding: gzip`; 409 HAZIR değilken; 400 SITL oturumu için).
- **session eklemeleri:** `mode: 'sitl'|'replay'`; replay'de `udp_port=null`, `center = {id:null, name:file_name, lat, lon, alt}` (ev),
  `type` firmware'den (ArduPlane → sabit_kanat, heli → helikopter, diğer → multirotor), `replay: {log_id, file_name, size, progress (%),
  frames, duration_s, home:{lat,lon,alt}, hz, takeoff_t, start_utc, vehicle, aircraft, pilot, modes}`. Durumlar: BASLIYOR (ayrıştırma;
  `progress` DFReader ilerlemesi, WS `state` ile yayınlanır) → HAZIR → KAPANDI; hata → HATA (`sitl.error`).
  `center` oturum açılır açılmaz **analiz özetindeki ev** (`flight_logs.analysis.summary.home.lat/lng/alt`) ile dolu gelir; HAZIR'da ayrıştırma sonucu
  (ilk ARM konumu, kalkış anı irtifası) üzerine yazar ve WS `state` iletisi `center` alanını da taşır.
- **Dünya yüklenmiyordu — kök neden (düzeltildi):** ön yüz `renderSession` dünyayı `session.center.lat ?? session.replay.home.lat` ile kuruyordu;
  oturum BASLIYOR'ken (ayrıştırma sürüyor) ikisi de null → `origin (0,0)` (Gine Körfezi) ile `/terrain?lat=0&lon=0` / Google karoları yükleniyor ya da
  düşüyordu ve HAZIR'da merkez yeniden konumlanmıyordu; önbellekli loglarda bile `hash` ayrıştırma bitmeden değiştiği için aynı yol izleniyordu. Düzeltme
  üç katlı: (1) sunucu `center`'ı analiz özetinden ön doldurur (yukarıda); (2) ön yüz merkez bilinmiyorsa 3B kurulumunu HAZIR'a erteler (`buildSim`),
  HAZIR'da merkez/irtifa değiştiyse `sim.setOrigin` ile dünyayı kaydın kalkış noktasına taşır (`syncOrigin`; olay şeridinde not), dünya boyutunu uçuşa
  göre büyütür (`fitWorldSize`); (3) **ön hazırlık kartı** oturum ekranına geçmeden sunucunun HAZIR olmasını bekler (aşağıda).
- **Ön hazırlık kartı (sihirbaz `prepareSession`):** Oynat/Başlat → `POST /sessions` → modal kart, adımlar: **Log ayrıştırılıyor %** (ReplaySession
  `progress`; `GET /sessions/{id}` 600 ms yoklama; canlıda "SITL başlatılıyor… N sn") → **Kareler indiriliyor** (`GET /sessions/{id}/replay`; veri
  `REPLAY_STASH` ile oturum ekranına devredilir, yeniden çekilmez) → **Dünya hazırlanıyor** (sihirbaz önizleme örneği `preview.setOrigin(ev, world, alt)`
  ile kaydın kalkış noktasına taşınır: `/terrain` + yükseklik/uydu karoları + `/osm` indirilir — sunucu disk ve tarayıcı önbelleği ısınır; Google 3B'de kök
  tileset havuzda kalır (§11) — ilerleme `onProgress` → yüzde; prosedürelde anında) → "Her şey hazır olunca oturum ekranı açılır" → `location.hash`.
  **İptal** (ya da hata sonrası Kapat) oturumu kapatır (`DELETE`), ekran paylaşımı akışını ve tam ekranı bırakır. Canlı SITL oturumunda da aynı kart
  (SITL HAZIR + dünya verisi). Replay dünyası boyutu: uçuşun evden en uzak noktasının 2,4 katı (500 m'ye yuvarlı, ≤ 20 km).
- **Ayrıştırma (sunucu, bir kez, iş parçacığında):** `.bin/.log` → `mavutil.mavlink_connection` (DFReader): GPS (Lat/Lng/Alt MSL,
  Spd, GCrs, VZ, Status, NSats, GWk/GMS → `start_utc`), POS (EKF konumu; varsa GPS'e tercih), ATT (Roll/Pitch/Yaw ° → rad; `hdg`),
  RCIN (C1–C8), BAT/CURR (Volt, RemPct; Inst 0), MODE (ModeNum → firmware mod adı), ARM/EV 10–11 (ARM/DISARM; ilk ARM = ev + `takeoff_t`),
  EV 25 / ORGN (ev yedeği), MSG (olaylar; uyarı ifadeleri sev 4), NKF1/XKF1 (VN/VE/VD; yoksa GPS Spd/GCrs), CTUN (ThO/ThrOut → gaz %, As),
  ARSP. `.tlog` → `mavutil.mavlogfile` (8 bayt BE µs + çerçeve; `_timestamp`): HEARTBEAT (araç; armed, mod adı), GLOBAL_POSITION_INT,
  ATTITUDE, RC_CHANNELS(_RAW), SERVO_OUTPUT_RAW, SYS_STATUS, VFR_HUD, GPS_RAW_INT, STATUSTEXT, HOME_POSITION, PARAM_VALUE. Yeniden örnekleme:
  sample-and-hold, `SIM_REPLAY_HZ` (25); 150.000 kareyi aşarsa seyreltme. `alt_rel = alt_msl − home.alt`.
- **Ayrıştırma (v5, ikili DataFlash):** yukarıdaki pymavlink yolu artık yalnız metin `.log` içindir; ikili `.bin` (ilk baytlar `A3 95`)
  `app/dataflash.py` akış okuyucusu + numpy ile sütunlu ayrıştırılır ve sabit `SIM_REPLAY_HZ` ızgarasına sample-and-hold yeniden örneklenir
  (`flightsim_replay._bin_hizli`; kare anlamı aynı, seyreltme yok). Ayrıntı ve ölçümler §8.3.
- **Önbellek (v3):** `DATA_DIR/sim_replay/<log_id>.json.gz` = `{v:3, hz, fields, frames, modes, events:[{t,text,sev}], duration_s, home,
  takeoff_t, start_utc, vehicle, type, n, source, servo_fn}`; `fields` = `[t, lat, lon, alt_msl, alt_rel, roll, pitch, yaw, vn, ve, vd, gs, as, hdg,
  thr, mode, armed, batt_v, batt_pct, sats, fix, rc, servo]` (rc ve servo 8'li iç dizi). Sürüm uyuşmazsa yeniden üretilir (v2 önbellekler ilk açılışta
  otomatik); log silinince (`DELETE /api/tools/flight-logs/{id}`) önbellek de silinir. Örnek: 253 MB ArduPlane .bin (97 dk) → 37 sn, 112k kare.
- **Kontrol yüzeyleri kayıtta çalışmıyordu — kök neden (düzeltildi, v3):** kareler yalnız RC **girişini** (`rc` = RCIN / RC_CHANNELS) taşıyordu; 3B
  `ctrlInputs` servo yoksa `rc`den türetir, ama gerçek uçuşta (AUTO/TAKEOFF/FBWA) kumanda ortada durur ve yüzeyleri otopilotun **servo çıkışı** oynatır;
  SITL kaydında RC girişi hiç yoksa `rc` null → hiçbir yüzey oynamaz; flap zaten yalnız moddan türetiliyordu (TAKEOFF/LAND). Şimdi DataFlash **RCOU
  C1…C8** / tlog **SERVO_OUTPUT_RAW servo1…8_raw** → kare `servo` (µs; `tele.servo` ile canlıdaki yol: servo_fn eşlemesi, flap kanalı 2/3, elevon 77/78)
  ve **PARM/PARAM_VALUE `SERVOn_FUNCTION`** → önbellek `servo_fn` (oynatıcı `tele.servo_fn`e koyar). Örnek .bin: `servo_fn = [78, 77, 70, 61, 0, 0, 0, 0]`
  (elevon R/L, gaz) → elevonlar servo çıkışıyla oynar; `sim.ctrlState().source === 'servo'`.
- **Kalkış yöntemi kayıtta (§13):** seçili logun aracı sabit kanat (ArduPlane) ise sihirbazda **Kalkış yöntemi** kartları (tekerlekli / rampa+açı /
  araç+hız) log listesinin altında görünür (kopter logunda gizli); `world.launch` kayıt oturumuna da gönderilir, sunucu doğrular (400) ve `session.launch`
  (`phase` hep null; `launch_normalize` log tipine göre, kopter → wheels) döner. Sunucu `launch` olayı YAYMAZ: aşamalar ön yüzde log karelerinden türetilir
  (`flightsim_launch.js replayLaunchTimeline/replayLaunchPhaseAt`): her ARM segmenti için `arm` (armed 0→1) → **armed** (uçak kızakta/kasada, düzenek
  uçağın log konumuna demirlenir), ilk hareket (yer hızı > 2 m/s ya da ARM anına göre AGL artışı > 0,5 m) → **launch**, bırakma (rampa: yer hızı ≥ 8 m/s
  ya da AGL artışı > 3 m; araç: yer hızı ≥ %95 bırakma hızı ya da AGL > 3 m; tekerlekli: AGL > 1 m) → **released**; uçuş sonu DISARM'da released kalır;
  hareketsiz segmentin (kalkış öncesi kalibrasyon ARM'ı) DISARM'ı → idle (düzenek başa). Oynatıcı zamanına göre uygulanır: her karede `applyReplayLaunch(t)`
  (değişimde `sim.setLaunchPhase`, panel, olay şeridi — aynı §13 metinleri), atlama/Baştan'da `snap` (geri sarmada düzenek `idle`a döner, released ofset sönümü
  kurulmaz: uçak doğrudan log konumunda). Kızak kilidi canlıdaki gibi: released'a dek uçak kızakta, sonra log konumu. Ses efektleri (§16: pşşt, kızak, araç
  motoru) `sim.launchPhase` üzerinden kayıtta da çalışır. Test: `node tests/test_flightsim_launch.mjs`.
- **WS:** `hello`/`state`(+`replay`)/`event`/`end`; `tele` YOK. İstemci `cmd` yalnız `reset` (diğerleri `res ok:false`); `reset` tüm
  izleyicilere `{t:'replay', action:'reset'}` yayınlar (ön yüz "Baştan"). `rc` yoksayılır.
- **Ön yüz (`flightsim.js`):** aynı sahne (`flightsim3d.js`; `origin` = ev, çarpışma denetimi kapalı), "● Kayıt" rozeti, kayıt
  bilgisi kutusu (MP kutusu yerine), oynatma çubuğu: ▶/❚❚ (boşluk), ⏮ Baştan, hız 0.5×/1×/2×/4×/8×, zaman kaydırıcısı (uyarı/hata
  olayları ve ilk ARM işaretli), `mm:ss / mm:ss` + kayıt saati; ←/→ 5 sn (Shift 30 sn). Kareler arası doğrusal enterpolasyon (açılar en
  kısa yol; 5 sn'den uzun boşlukta tutma), HUD/RC/mod/arm karelerden, olay şeridi MSG/STATUSTEXT'ten log zamanıyla (atlamada son 8 olay).
  Başlangıç: ilk ARM − 5 sn, otomatik oynatır. `?mock=1`: sahte log listesi + 2 dk sahte kare (kalkış, daire, iniş).

### 8.3 Uzun kayıtlar (3+ saat, ~700 MB .BIN) — akış ayrıştırma, parçalı önbellek, LOD oynatma
Kullanıcı bildirimi: "Sistemde 3 saatlik gerçek bir uçuşun bin dosyası var, onu izlemek için açmaya çalıştığımda kilitleniyor."
- **Kök neden (ölçüldü, PROD log #6 `13.10.26_565km_700m.BIN`, 754 MB, 4 sa 41 dk, ~19 M mesaj):** pymavlink `DFReader_binary` dosyayı mmap'leyip
  Cython indeksleyiciyle **her** mesajın ofsetini Python listelerine yazar (~1,6 GB RSS), ilerleme geri çağrısı yalnız bu 3 sn'lik indeksleme
  sırasında çalışır (çubuk %100'e sıçrayıp kalır), sonra istenen ~5 M mesaj tek tek Python nesnesine çözülür: kayıttan oynatma alt süreci
  **155 sn / 2,6 GB**, Uçuş Logu Analizi › 3B izleme ucu (`/api/flight-logs/{id}/replay`) **67 sn / 1,6 GB — istek içinde iş parçacığında, GIL
  tutarak** (sunucu olay döngüsü dakikalarca ağırlaşıyor, proxy zaman aşımı). Ardından tarayıcı 150 k karelik ~30 MB JSON'u tek seferde
  ayrıştırıyordu. PROD'da kullanıcı log #6'yı açıp 27 sn sonra kapatmış (drone_sim_runs #11); büyük logların hiçbirinin önbelleği yoktu.
- **Akış okuyucu (`app/dataflash.py`):** dosya 16 MB bloklarla sırayla okunur; bloktaki `A3 95` aday başlıkları numpy ile (iki uint16 hizası)
  bulunur, her adayın ardılı (konum + FMT uzunluğu) eşlenir, mesaj zinciri **gelen-derece soyma + ardıl doğrulaması** ile vektörel çıkarılır
  (yüklerdeki sahte başlıklar elenir); FMT, tanımsız tip, bozuk bayt (sonraki başlığa atlama — pymavlink kuralı) ve blok sınırı tam (mesaj mesaj)
  yolda işlenir, 4000 sakin mesajdan sonra hızlı yola dönülür. Yalnız istenen tip/sütunlar yapılı dtype görünümüyle toplu çözülür (float32 / zaman,
  enlem-boylam float64). Değerler pymavlink ile birebir (testte bozuk bayt + sahte başlık + ortada FMT ile değer değer karşılaştırılır).
  İlerleme okunan bayta göre gerçek yüzde. `sim_isareti(path)`: dosyanın ilk 4 MB'ında `SIM_*` parametresi → SITL logu (§19 kaynak).
- **Önbellek v5:** kısa kayıt (≤ `SIM_REPLAY_TEK_PARCA` = 45.000 kare, 25 Hz'de 30 dk) eskisi gibi tek `<id>.json.gz` (tüm kareler).
  Uzun kayıtta önce **zaman parçaları** `<id>.p<k>.json.gz` = `{v, k, a (ilk kare sırası), frames}` (`PARCA_S` = 120 sn × 25 Hz = 3000 kare, tam hız),
  sonra meta `<id>.json.gz`: `frames` = **1 Hz genel bakış** (`GENEL_HZ`; ızgaranın her `step`'inci karesi + son kare) ve
  `lod: {chunk_s, chunks, chunk_n, step, n_overview}`; `n` tam kare sayısı. Meta en son yazılır (varlığı = tamamlanmış önbellek); parça eksikse
  önbellek geçersiz sayılır ve yeniden üretilir. Parça JSON'u alt süreçte `SIM_REPLAY_ISCI` (4) fork'lu işçiyle üretilir (JSON GIL'e bağlı).
  Silme: `onbellek_sil` (meta + parçalar; log silinince).
- **Uçlar:** `GET /sessions/{id}/replay` (meta + genel bakış; kısa kayıtta tüm kareler) · **`GET /sessions/{id}/replay/{k}`** (k. parça; gzip olduğu gibi;
  404 aralık dışı, 409 HAZIR değil) — CAYSIM'de de aynı yol (`/api/caysim/v1/sessions/{id}/replay/{k}`; docs/caysim-api.md §7).
- **Oynatıcı (`createReplayPlayer`, flightsim.js):** `lod` varsa t anının parçası `be.replayChunk` ile istenir; gelene kadar genel bakış enterpolasyonla
  oynar (donma yok; oynatma çubuğunda "Ayrıntı yükleniyor…" rozeti), parçanın %60'ı geçilince sıradaki önceden çekilir, parça sonunda bir sonrakinin
  ilk karesiyle enterpolasyon; bellekte en çok 8 parça. Atlama (kaydırıcı) yalnız o parçayı çeker. `fitWorldSize`, kalkış zaman çizelgesi ve §23 güç
  yeniden kurulumu genel bakış karelerini kullanır.
- **3B izleme (Cesium, `/api/flight-logs/{id}/replay`):** `flightlog.replay` ikili logda aynı okuyucuyla 5 Hz ızgara (≤ 40.000 örnek); üretim
  **alt süreçte** (`python -m app.flightlog replay <log> <çıktı>`; aynı log için eşzamanlı istekler tek üretim — `_REPLAY_KILIT`), sonuç eskisi gibi
  `<log>.replay.json`. Yakıt hesabı da aynı yolu kullanır.
- **Ölçümler (DEV, Xeon E5-2697A; PROD log #6 kopyası, 754 MB):**

  | | Önce | Sonra |
  |---|---|---|
  | Kayıttan oynatma ayrıştırma + önbellek | 155 sn · 2,6 GB RSS · ilerleme %100'de takılı | **13–19 sn** (okuma ~9 sn + 141 parça yazımı ~4 sn) · ~0,43 GB · gerçek ilerleme |
  | Önbellek | 6,1 MB gz (150 k kare seyreltilmiş, ~8,9 Hz) | 14,3 MB (421.861 kare tam 25 Hz, 141 parça) + 0,8 MB genel bakış |
  | Tarayıcıya ilk yük | ~30 MB JSON (150 k kare) | 0,8 MB gz genel bakış + ~0,1 MB gz parça; ilk görüntü < 1 sn (önbellekten) |
  | 3B izleme (Cesium) verisi | 67 sn · 1,6 GB · istek iş parçacığında (GIL) | **6,6 sn** · 0,2 GB · alt süreç |
  | İkinci açılış | — | 0,2 sn (meta) |
- **Testler:** `tests/test_binperf.py` (okuyucu = pymavlink, 1 saatlik üretilmiş 68 MB .BIN: süre/bellek/ilerleme, parça sürekliliği, genel bakış seyreltmesi,
  eksik parça → yeniden üretim, 3B hızlı yol eşdeğerliği, oturum parça ucu, kaynak çıkarımı ve göç).

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
| `GET /api/drone/sim/terrain?lat&lon&size_m` | `{z, tiles:[{x,y}], img_z, img_tiles:[{x,y}], elev_url_template, img_url_template, home_elev, bbox, size_m, far:false, attribution}`; `home_elev` merkez karosundan (alınamazsa null); 400 geçersiz parametre |
| `GET /api/drone/sim/terrain?lat&lon&far=1[&size_m]` | **Uzak arazi planı** (ufuk): kenar 24–64 km (varsayılan 48), yükseklik **z 10** (2×2…3×3 karo, ≈ 110 m/px), uydu **z 12** (≤ 64 karo, ≈ 30 m/px), `far:true`; `home_elev` yine z 13 merkez karosundan (ana planla aynı referans, önbellekten) |
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

**Uzak arazi halkası (ufuktaki dağlar):** ana dünya `size_m` (1–12 km) dışında arazi yoktu → 4 km dünyada 20 km'deki dağlar hiç yoktu, üstelik sis
5,4 km'de kapanıyordu (§5). Oturum ekranında (önizlemede değil; kamera ufku görmez) `loadRealTerrain(…, withFar=true)` OSM ile **paralel**
`/terrain?far=1` planını yükler (`loadMosaic` ortak yükleyici; yükseklik z 10 + uydu z 12, ≈ 1–2 MB) ve `buildReal` 192×192 ızgaralı 48 km'lik
`uzak-arazi` örgüsü kurar: yükseklikler **ana arazi ile aynı h0 referansı** (ikisi de terrarium MSL; merkez 0), ana kare içinde ana arazinin 2 m
altında saklı, kenardan 1,5 km dışarıya dek ana kenar değeriyle `smoothstep` karışımı (dikişsiz), sonrası tamamen z 10 verisi; aynı gece/akşam
renk çarpanı; uzak kenar sisle (fog ufku 24 km·(1,25 − fog)) kaybolur. `terrainHeight(x, y)` ana kare dışında uzak araziden örnekler (serbest
kamera zemin kısıtı, rota çubukları, çarpışma). Alınamazsa (ağ/502) sessizce yok sayılır (`console.warn`), ana dünya etkilenmez; `terrainInfo.farSize`.
**Yükseklik ölçeği doğrulaması (Ankara):** terrarium verisi z birimi metre, ölçekleme/abartı yok; sunucu profili (z 10 ↔ z 13 farkı ≤ 8 m):
ev 907,9 m MSL; K 18 km 1358 m; GD 16/18/20 km 1532/1664/1649 m; 20 km içinde en yüksek nokta **Elmadağ 1859 m MSL** (39,8029/32,9893; 18,7 km
GD) → eve göre **+951 m**; 3B'de `terrainHeight` aynı noktada aynı değeri verir (e2e `/tmp/flsim/terr/e2e_terr.py` profili, aşağıda).

Ölçümler (DEV, Ankara 39.925/32.837, 4 km): `/terrain` soğuk 1.1 sn (merkez karosu + plan), sıcak 0.15 sn; yükseklik 4 karo 2.4 sn → 0.15 sn;
uydu 90 karo (z16, 2 MB) 12.5 sn → 2.6 sn; `/osm` soğuk 46 sn (Overpass; 7996 bina, 242 orman, 31 su; 1.3 MB sade JSON), sıcak 1 sn.
Tarayıcıda önizleme/oturum dünyası sıcak önbellekle 3–9 sn (yazılım WebGL).

**EV İRTİFASI KURALI (`SimManager.ac`; 18 Ekim düzeltmesi).** Gerçek arazi ve Google 3B kiplerinde SITL ev irtifası **her zaman** `sim_terrain.ev_irtifa`
(terrarium z13 bilineer, MSL) ile kurulur; merkez kaydındaki `alt` bu kiplerde **kullanılmaz** ve `session.center.alt_entered` olarak saklanır
(`center.alt` = kullanılan değer). Kayıtlı değer araziden `EV_FARK_UYARI` (15 m) fazla sapıyorsa sihirbazın merkez kartında uyarı ("Kayıtlı irtifa
1500 m, arazi 742 m — arazi kullanılacak"; `/terrain home_elev`) ve oturum olay şeridine not (`alt_not`, SITL açılışında). Arazi alınamazsa kayıtlı
değer / `EV_IRTIFA` ile sürer ve uyarı düşer. Prosedürel kipte kayıtlı `alt` aynen (0/boş → `EV_IRTIFA`), arazi sunumu zaten kapalı → uyumsuzluk yok.
KÖK NEDEN (PROD, 18 Ekim): merkezler `Ankara 39.3775/34.2904 alt 0` ve `Bedesten 39.8565/33.3998 alt 1500` kayıtlıyken arazi sunumu açıldı → SITL yüzeyi
terrarium'dan (≈ 1000 / 742 m) öğreniyor ama ev irtifası kullanıcının girdiği 0 / 1500 m ile kuruluyordu → uçak yerin ~1000 m altında / ~760 m üstünde
doğuyor, fizik "takla" atıyordu (drone_sim_runs #1–2 `carpisma`). Doğrulama (gerçek arduplane, rampa, gerçek arazi): yerde `alt_rel` 0±1, `terrain_agl`
0±2, 60 sn pitch/roll < 5° (`tools/flightsim_ev_irtifa_dogrula.py`). Kalkış yöntemleri etkilenmez.

**SITL arazi sunumu (sunucu GCS gibi; §18 ayrıntı).** Gerçek arazi ve Google 3B kiplerinde sunucu SITL'in `TERRAIN_REQUEST`'lerine **aynı terrarium
karolarından** (z 13, bilineer `sim_terrain.yukseklik`; ev irtifası `ev_irtifa` ile aynı kaynak, EGM96 MSL) `TERRAIN_DATA` yanıtlar → SITL fiziği
gerçek topoğrafyayı görür (Mission Planner gerekmez). `sim_terrain.terrain_bloklari(lat_e7, lon_e7, spacing, mask)` ArduPilot blok düzenini üretir
(28×32 nokta = 7 kuzey × 8 doğu adet 4×4 parça; `gridbit = kuzey_parça·8 + doğu_parça`, `data[i]` → kuzey `i//4`, doğu `i%4`; konum `konum_ofset` =
`Location::offset`); çözülmüş karolar bellekte LRU (`COZ_LIMIT` 48 ≈ 10 MB); 56 parça (896 örnek) soğuk 0,14 sn, sıcak 0,02 sn.

## 10. Askeri tarz FPV HUD (`static/js/modules/flightsim_hud.js`)
Kamera kipi **Gimbal kamerası (3; kod adı `fpv`, eski adı "Dron kamerası")** seçilince 3B'nin üstünde tam ekran şeffaf bir canvas katmanı (`.fs-mhud`, canvas 2D, devicePixelRatio,
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

## 11. Google 3B — Photorealistic 3D Tiles (`world.mode = "google3d"`; ön yüz `static/js/modules/flightsim_g3d.js`)
Kullanıcı sihirbazın Dünya adımında **Google 3B (fotogerçekçi)** seçer (seçenek yalnız `meta.google3d.enabled` ise görünür): merkezin çevresi
Google'ın fotogerçekçi 3B karolarıyla (binalar, ağaçlar, arazi tek örgü) kurulur. Prosedürel ayarlardan yalnız **saat / sis / rüzgâr / pist**
geçerlidir (`tree_density`, `building_count`, `mountain_*`, `water`, `seed` gizlenir; prosedürel/OSM binalar, ağaçlar, su ve uydu arazi kapalı —
karolarla çakışmasın). Pist varsayılan **kapalı**; açılırsa merkezde ince asfalt şerit (18 m) yüzeye (z = 0) oturur.

**Neden yalnız 3D Tiles:** Google Maps'in 2B arazi/uydu karoları ve Elevation API yalnız Google haritası üzerinde gösterilebilir (ToS) →
kullanılmaz. Photorealistic 3D Tiles üçüncü taraf 3B sahnede çizilebilir; koşullar: **atıf zorunlu**, **sunucu tarafı önbellekleme yok**
(tarayıcı doğrudan Google'dan çeker), Google logosu görünür. Ev irtifası için Google Elevation API değil açık veri (`sim_terrain.ev_irtifa`) kullanılır.

### Kurulum
1. Google Cloud Console → proje → **Map Tiles API** etkinleştir (Photorealistic 3D Tiles bu API'nin parçası). Faturalandırma hesabı gerekir.
2. **API anahtarı** oluştur → *Application restrictions: HTTP referrers* → `https://gokkubbe.hepgo.com/*` (ve varsa DEV adresi);
   *API restrictions:* yalnız Map Tiles API. Anahtar tarayıcıya verildiği için referrer kısıtı **şarttır**.
3. `.env` → `GOOGLE_MAPS_API_KEY=AIza…` → servis yeniden başlatılır. `GET /api/drone/sim/meta` → `google3d.enabled: true`.
4. Ücret: Map Tiles API'de 3D Tiles **kök tileset isteği** (`root.json`) başına ücretlendirilir (alt karolar ve oturum belirteci ücretsiz;
   fiyat SKU "Photorealistic 3D Tiles", aylık ücretsiz kota vardır — güncel değerler Google fiyat sayfasında). Ön yüz aynı merkez için
   kök tileset'i **bir kez** ister: sihirbazda kaydırıcı değişimleri karoları yeniden yüklemez (yalnız saat/pist yeniden uygulanır); merkez
   değişince ve oturum ekranı açılınca yeni kök isteği gider. Kota/anahtar hatasında kip prosedürele düşer (aşağıda).

### Uçlar ve akış
| Parça | Davranış |
|---|---|
| `GET /meta` | `google3d: {enabled}` (`flightsim.google3d_etkin()` = `GOOGLE_MAPS_API_KEY` boş değil) |
| `GET /g3d-key` | `{key}`, `Cache-Control: no-store`; `require_module('drone.sim')` (salt okuyan izleyici de alır); kip kapalıysa 404. Anahtar yalnız dünya kurulurken istenir |
| `POST /sessions {world.mode:'google3d'}` | `world_dogrula` kabul eder; kip kapalıyken 400 `invalid` ("GOOGLE_MAPS_API_KEY"); merkez `alt` boşsa ev irtifası `sim_terrain.ev_irtifa` (real ile aynı) |
| Tarayıcı → Google | `https://tile.googleapis.com/v1/3dtiles/root.json?key=…` → oturum belirteci (`session=`) ile `.glb` karoları (Draco). CSP: `connect-src https:` zaten açıktı; Draco çözücü blob: worker (`worker-src blob:` mevcut) + wasm (`script-src 'unsafe-eval'` mevcut). **Tek CSP eki:** `connect-src … blob:` — GLTFLoader'ın ImageBitmapLoader'ı glb içindeki dokuları `fetch(blob:)` ile okur; yoksa karolar dokusuz (gri) kalır |

### Ön yüz (`flightsim_g3d.js`; `flightsim3d.js` yalnız kanca)
- Kütüphane: **NASA-AMMOS `3d-tiles-renderer` 0.5.3** (MIT) → `static/vendor/three/3DTilesRenderer.js` (tek ES modülü, esbuild;
  `tools/build-3dtiles.sh` ile üretilir; three import'ları `./three.module.min.js`, `./GLTFLoader.js`, `./BufferGeometryUtils.js`, `./Pass.js`
  yerel vendor yollarına çevrilir), `LICENSE-3d-tiles-renderer`. Draco: `static/vendor/three/DRACOLoader.js` + `draco/` (decoder js/wasm/wrapper).
  Eklentiler: `GoogleCloudAuthPlugin` (anahtar, oturum belirteci, atıf toplama, `logoUrl`), `GLTFExtensionsPlugin` (Draco), `TileCompressionPlugin`.
- Kurulum: `TilesRenderer`; `errorTarget` 16 (önizleme 36), `maxDepth` ∞, LRU 250–350 MB (önizleme 80–120 MB); her karede
  `setResolutionFromRenderer` + `update()`. Kök tileset `load-root-tileset` ile hazır; `load-error` (tile null) ya da 25 sn zaman aşımı →
  hata (`describeError`: HTTP 400/403 "anahtar geçersiz, Map Tiles API kapalı ya da HTTP referrer kısıtı", 429 kota, ağ/CSP) → `onFallback`
  → **prosedürele düşer**, ekranda "Google 3B verisi alınamadı: … → prosedürele düşüldü" (olay şeridi + toast; sihirbazda bilgi satırı).
- **ECEF → yerel ENU:** `Ellipsoid.getEastNorthUpFrame(lat, lon, h)` (X doğu, Y kuzey, Z yukarı → ECEF) matrisinin tersi `tiles.group`'a
  (decompose) uygulanır — sahnemiz Z-up ENU olduğundan ek döndürme yok (`enuMatrix`; `tests/test_g3d_enu.mjs`: merkez → (0,0,0), 100 m
  kuzey → +Y, doğu → +X, yukarı → +Z). `h` = ev irtifası (merkez `alt`, boşsa `/terrain` `home_elev`, o da yoksa 0). Sahnenin `toLocal`'ı
  düz-dünya yaklaşıklığıdır (1° = 110574 m); Ankara'da meridyen yarıçapı %0,4 farklı → 2 km'de ≈ 8 m kayma (real kipiyle aynı).
- **Yer ofseti (`groundOffset`):** karolar elipsoid yüksekliğinde, ev irtifası MSL (Türkiye'de geoid farkı ~30–40 m) → merkeze aşağı ışın
  (`tiles.raycast`, `firstHitOnly`) ile yüzey z'si ölçülür ve grup z kaydırılır (yüzey z = 0). Dron kalkmadan (armed ∧ hız > 1 m/s değil)
  her 400 ms yenilenir (ince LOD geldikçe), kalkışta dondurulur. Olay şeridine yazılan ofset **toplam** değerdir ve karolar dolunca ya da ilk
  düzeltmeden 3 sn sonra bir kez yazılır (ilk ölçüm kaba kök karodadır: Ankara'da −1204 m görülüp sonra −33 m'ye oturuyordu; teşhis `sim.g3dOffset`).
  `g3d.heightFine(x, y)` önbelleksiz tam-nokta ışını: kalkış düzeneğinin temas noktaları (±3 m) aynı 25 m hücreye düştüğünden eğim için gerekir.
- **Yükseklik/çarpışma:** `terrainHeight(x, y)` → `g3d.height`: 25 m hücreli önbellek, aşağı ışın; karo yüklenince/boşalınca ve ofset
  değişince geçersiz; karo yoksa komşu hücre, yoksa 0. Çarpışma mevcut mantıkla (bina çatıları karoda olduğu için doğal gelir); pist
  çizilmese de `runway_heading` boyunca 1200×40 m sanal şerit kalkış/iniş koşusu için muaf. Kalkış düzeneği (§13) `g3d.surfaceAt(x, y, fineErr)`
  ile karo yüzeyine oturur: önbelleksiz tam-nokta ışını **yalnız karo grubuna** (`tiles.raycast` → `activeTiles` sahneleri; uçak/düzenek/kamera
  yardımcıları denenmez) atılır ve ölçüm `{z, fine, err, leaf}` döner — `err` çarpılan karonun `geometricError`'ı (`load-model` olayındaki `tile`
  sahneye eşlenir; havuzdan gelen karolar `activeTiles` taramasıyla), `fine` = `err ≤ fineErr` (2 m) ya da yaprak karo. Kaba/kök karo ölçümü
  (ilk saniyelerde −280 m görülmüştü) `fine=false` ile düzeneğe hiç uygulanmaz (§13 yüzey kilidi).
- **Uzak dağlar:** 3D Tiles LOD küreseldir; `errorTarget 16`, `maxDepth ∞`, LRU 350 MB ve kamera `far` 60 km uzak karoları **engellemez**
  (dünya boyutu kırpması yoktur — `size_m` yalnız pist/sis içindi). Ufuktaki dağların görünmemesinin kök nedeni sis formülüydü (4 km dünyada
  5,4 km'de kapanıyordu); artık `skyAndLights(size, 30 km)` → fog 0,2'de 31 km görüş (§5). Uzak bölge için kaba karolar (az bellek) doğal gelir.
- **Havuz:** aynı merkez için `TilesRenderer` sihirbaz önizlemesi ile oturum ekranı arasında paylaşılır (`POOL`; `dispose` askıya alır,
  10 dk sonra atar) → kök tileset isteği oturum başına **1** (ölçüm: önizleme + oturum + kalkış = 1 root, ~1000 glb, 0 hata).
- DEV ölçümü (Ankara, gerçek anahtar, Referer `gokkubbe.hepgo.com`): önizleme ilk karolar 1,5–7 sn (yazılım WebGL), oturum dünyası < 1 sn
  (havuz), yer ofseti −32,7 m (elipsoid ↔ MSL geoid farkı), atıf "Google · Airbus". Anahtar referrer kısıtlı: `127.0.0.1`'den Referer'siz
  istek 403 → "HTTP 403 (anahtar geçersiz, Map Tiles API kapalı ya da HTTP referrer kısıtı) → prosedürele düşüldü".
- Malzeme: Google glb'lerinde normal yok → karo malzemeleri `MeshBasicMaterial`a çevrilir (doku rengi doğrudan; Google dokuları zaten
  gölgeli; Lambert normalsiz geometride siyah çizer, normal hesaplanınca da dokuyu "yanık" gösterir). Gece/akşam renk çarpanı real kipiyle
  aynı (`0x4c5670` gece, `0xe8b898` akşam). Gölge isteğe bağlı (`createFlightSim3D` `opts.g3dShadows`: `computeVertexNormals` + Lambert +
  `receiveShadow`; varsayılan kapalı). Sis `skyAndLights` ile.
- **Atıf (ToS):** oturumda sol altta (MP kutusu üstü) Google logosu (`static/img/google-logo.png`) + `tiles.getAttributions()` metni
  (görünür karoların `asset.copyright` değerleri: "Google · Data SIO, NOAA… · …"), 300 ms'de bir güncellenir, yüklerken "yükleniyor %";
  önizlemede logo sol altta, metin bilgi satırında. Yükleme ilerlemesi (`tiles.loadProgress`) oturumda ilk dolumda `.fs-msg`, sihirbazda şerit.
- `?mock=1`: sahte meta `google3d.enabled=true`, sahte anahtar → Google 400/403 → hata yolu denenir (Playwright: sihirbaz + oturum ekranında
  "prosedürele düşüldü" metni, ekran görüntüleri). Gerçek anahtarla deneme DEV'de yapılmadı (anahtar yok).

## 12. Görsel model kütüphanesi (`app/flightsim_models.py`, `static/js/modules/flightsim_models.js`; tablo `drone_sim_models`)
Kullanıcı sihirbazda dron tipini seçince, tipin altındaki **Model** bölümünde sistemde yüklü 3B gövdelerden görsel olarak seçer: küçük resimli
kart ızgarası (ad, kaynak rozeti Dahili / Tasarım / Yüklenen, boyut, Hazır / Dönüştürülüyor / GLB bekliyor), seçili kart vurgulu, sağdaki canlı
3B önizleme seçilen modelle döner. Kayıt kipinde de (log tipine göre) seçilir.

**Kaynaklar.** (a) **Dahili** — kodda sabit (`flightsim_models.BUILTIN`, kimlik `builtin:<ad>`), her tip için her zaman var: sabit kanat
`builtin:caymaz` (Caymaz V3 GLB) + `builtin:delta` + **`builtin:talon`** (Talon V-kuyruk; aşağıda); multirotor `builtin:quad`; hexarotor `builtin:hexa`;
helikopter `builtin:heli`; VTOL `builtin:caymaz` / `builtin:delta` ("VTOL-Caymaz V3", "VTOL-Delta kanat"; 4 dikey motor eklenir). Varsayılanlar
`VARSAYILAN`. Her dahili modelin **`layout`** alanı (§13.1 kontrol düzeni: caymaz/delta `elevon`, talon `vtail`) ve isteğe bağlı **`orient`**
alanı vardır (`builtin_api` döndürür; yönelimli dahili GLB'ler — talon — ön yüzde kütüphane modeli gibi `buildLibrary` ile yüklenir, `BUILTIN_GLB`
yedek tablosu dize ile gelen kimliği de karşılar). Yüklenen/tasarım modellerinde `layout` null'dur; sihirbaz düzeni 3B'ye yüklenen yüzey düğüm
adlarından tahmin eder (`sim.ctrlLayout()`: ruddervator → vtail, elevon → elevon, aileron/elevator/rudder → classic).

**Talon V-kuyruk (`static/models/talon-vtail.glb` = `static/simumav/models/talon_vtail.glb`, 44 KB, 3 108 üçgen).** Kaynak arandı
(Gazebo Fuel API 503, Poly Pizza API anahtar istiyor, PX4-SITL_gazebo-classic / ArduPilot Gazebo depolarında V-kuyruklu model yok) →
**prosedürel üretim, dış kaynak yok** (`tools/simumav_models_build.py --talon`, trimesh): X-UAV Talon ölçüleri (açıklık 1,72 m, uzunluk 1,10 m),
eliptik kesit loft'u gövde (turuncu burun kapağı `accent`, kabin camı), kambur profilli uzun kanat (3° dihedral, turuncu uçlar), ince kuyruk bumu,
**V-kuyruk 37°**, gövde arkasında tek **itici** pervane (`propeller` düğümü, YZ düzlemi). Kontrol yüzeyi düğümleri menteşe çizgisinde:
`aileron_l/r` (açıklığın 0,45–0,82 m'si, kordun arka %26'sı), `ruddervator_l/r` (kordun arka %45'i); düğüm yerel çerçevesi flightsim3d
varsayımıyla uyumlu (yerel X = menteşe ekseni sola, yerel Y = yüzey üst normali, −Z = kord → `te_down = −1`, extras gerekmez). glTF çerçevesi
SIMUMAV standardı (burun +X, yukarı +Y, sağ +Z; `orient {forward:'+x', up:'+y'}`). Lisans satırı `static/simumav/models/LICENSES.md`
(HEPGO üretimi, paketle serbestçe dağıtılır). (b) **Tasarım** —
Endüstriyel Tasarım modülündeki sürüm dosyaları (`design_drawing_versions` .step/.stp/.glb/.gltf/.obj; `GET /models/design-files`, yalnız `design`
modülü olan kullanıcı); "Sistemdeki dosyalardan ekle" → `POST /models/from-design {version_id, type, name?}` → tablo kaydı (`source='design'`,
`source_ref`; dosya kopyalanmaz, UPLOAD_DIR'den okunur; aynı sürüm+tip tek kayıt). (c) **Yükleme** — `POST /models` (multipart `file`, `type`,
`name?`; .glb/.gltf/.step/.stp/.obj; ≤ 50 MB; yazma izni) → `DATA_DIR/sim_models/<id>/orijinal.<ext>` (`source='upload'`); GLB ise aynı anda hazır.

**Tablo `drone_sim_models`:** `id, name, source (upload|design), source_ref, type, file_path (upload: DATA_DIR göreli · design: UPLOAD_DIR göreli),
glb_path, thumb_path (DATA_DIR göreli), orient_json, has_prop, created_by, created_at` (`CREATE TABLE IF NOT EXISTS`, drone tabloları gibi tenant
sütunu yok). Dosya yolları yalnız kimlikten türetilir; kimlik tam sayı ya da `builtin:[a-z0-9_]+` (`kimlik_coz`; yol gezinmesi yok).

**Uçlar** (okuma `require_module('drone.sim')`; POST/PUT/DELETE yazma izni):
| Uç | Davranış |
|---|---|
| `GET /models?type=` | `{models:[{id, name, source, type, types, thumb_url, glb_url, file_url, format (glb|gltf|step|obj|procedural), size, ready, orient, has_prop, desc, file_name, created_*}], defaults, can_write, design_allowed, limits}` |
| `GET /models/design-files` | tasarım 3B sürüm dosyaları `[{id, version, file_name, size, drawing_name, project_name, model_id}]` (design modülsüz 403) |
| `POST /models` · `POST /models/from-design` | yükleme / tasarımdan ekleme → model (201); uzantı/boyut/tip → 400, 413 |
| `GET /models/{id}` · `PUT /models/{id}` · `DELETE /models/{id}` | tekil; `{name, type, orient, has_prop}` güncelle (dahili 400); sil (kayıt + `sim_models/<id>/`; tasarımın aslı kalır) |
| `GET /models/{id}/file` | özgün dosya (tarayıcı dönüşümü için) |
| `GET/PUT /models/{id}/glb` | GLB; PUT ham gövde (`glTF` başlığı, ≤ 50 MB) → `model.glb`, `ready=true` |
| `GET/PUT /models/{id}/thumb[?type=]` | 320×240 PNG (≤ 2 MB); dahili için `static/models/thumbs/<ad>-<tip>.png` yoksa `DATA_DIR/sim_models/builtin/<ad>-<tip>.png` (ilk kullanıcı üretir) |

**STEP → GLB tarayıcıda** (PROD'da node/occt yok; `tools/step2glb.js` yalnız dahili Caymaz GLB'si için geliştirme aracı): kullanıcı kütüphanede
hazır olmayan (`ready=false`) bir modeli seçince `flightsim_models.convertToGlb`: dosya `GET /models/{id}/file` → STEP ise `step3d.parseStep`
(mevcut `step-worker.js` module worker, occt wasm; `params` ile mm + mutlak lineer sapma) kademeli sapma 1,5 → 3 → 6 → 12 → 25 mm, üçgen sayısı
≤ ~100k olunca durur → mesh'ler renge göre birleştirilir (`BufferGeometryUtils.mergeGeometries`, renkler korunur), mm → m → `GLTFExporter`
(three r170, `static/vendor/three/GLTFExporter.js`) binary → `PUT /models/{id}/glb`. OBJ → `OBJLoader` (vendor) → GLB; GLTF → `GLTFLoader` → GLB;
GLB olduğu gibi. Kartta ilerleme çubuğu (indirme / çözümleme / birleştirme / yazma / yükleme %). Salt okuyan kullanıcı hazır olmayan modeli
seçemez (uyarı). Sonraki kullanıcılar sunucudaki GLB'yi alır.

**Küçük resimler:** `flightsim3d.snapshotModel(type, model)` modeli ayrı bir sahnede (açık arka plan, 3/4 açı) `WebGLRenderTarget`'a çizer →
PNG Blob → `PUT /models/{id}/thumb` (dahili için `?type=`); sihirbaz açılışında ve seçimde eksikler sırayla üretilir (yazma izni varsa);
yoksa kartta "Önizleme hazırlanıyor…" yer tutucu. Yönelim kaydedilince küçük resim yenilenir.

**Yönelim (`orient`, yüklenen/tasarım modelleri):** `{forward, up (±x/±y/±z, dik), scale (birim → m), offset [x,y,z] m, prop:{mode: none|tail|nose|manual,
pos, r}}` (`orient_dogrula`; STEP varsayılanı `+y/+z` — CAD Z yukarı, GLB/OBJ `+z/+y`). Panel: burun/yukarı ekseni seçimleri, 90° Yaw/Pitch/Roll
düğmeleri, ölçek ya da kanat açıklığı / çapraz uzunluk girilerek otomatik ölçek (önizlemenin sınır kutusu genişliğinden), konum ofseti, pervane:
modelde `prop|propeller|rotor|pervane` adlı düğüm varsa en ince sınır kutusu ekseni etrafında döndürülür (`has_prop`), yoksa prosedürel pervane
(kuyruk/burun: sınır kutusu arka/ön ucu; elle konum). Değişiklik canlı önizlemeye uygulanır (`setType`), **Kaydet** → `PUT /models/{id}`; oturum
açarken gönderilen `model.orient` oturuma özeldir (kütüphane kaydını değiştirmez). `flightsim3d.buildLibrary`: GLB → `R = [f×u, f, u]ᵀ` dönüşü +
ölçek + ofset; `drone.ground` sınır kutusu altından; seyir ışıkları kanat uçlarına.

**Doğrulama (DEV, Playwright SwiftShader):** sihirbaz kart ızgarası + küçük resimler üretildi, PROD'daki CAYMAZ V3 STEP'i (16,9 MB) tasarım
sürümü olarak eklendi → tarayıcıda GLB'ye dönüştürüldü → yönelim paneli (kanat açıklığı 3,03 m → ölçek) → yüklenen modelle oturum (takip/FPV).

## 13. Sabit kanat kalkış yöntemi (`world.launch`; `static/js/modules/flightsim_launch.js`)
Kullanıcı sihirbazda **Sabit Kanat** seçince tip kartlarının altında **Kalkış yöntemi** kartları açılır (VTOL/kopterde bölüm gizli; dikey kalkış):
**Tekerlekli kalkış** · **Fırlatma rampası** (parametre: fırlatma açısı 10–30°, varsayılan 15°) · **Araç üstü kalkış** (parametre: bırakma hızı
40–110 km/h, varsayılan 70; araç tipi pickup). Seçim `world.launch = {method: 'wheels'|'ramp'|'vehicle', angle_deg, release_kmh}` olarak gönderilir;
sunucu doğrular (`launch_dogrula`; aralık dışı/bilinmeyen → 400 `invalid`), `WORLD_DEFAULTS.launch` ile eksikler dolar, üç dünya kipinde de geçerlidir.
Sabit kanat dışı tiplerde `method` `wheels` olarak normalize edilir (`launch_normalize`). `session.launch = {method, angle_deg, release_kmh, phase}`
(`phase`: null | armed | launch | released — geç katılan izleyici düzeneği doğru aşamada görür). **Kayıttan oynatmada da sorulur** (sabit kanat log):
düzenek sahnede, aşamalar logdan türetilir — bkz. §8 "Kalkış yöntemi kayıtta".

**SITL araştırması (gerçek ikili arduplane 4.7.2, pymavlink):** `--model plane-catapult` **vardır** (SIM_Plane `-catapult` son eki: `launch_accel`
15 m/s², `launch_time` 2 sn **sabit kodlu**; `SIM_LAUNCH*` türü parametre yok, fırlatma pitch'i parametresi yok). Tetik: **servo 7 çıkışı > 1700**
(`MAV_CMD_DO_SET_SERVO 7 1900`; `SERVO7_FUNCTION 0`). Ölçüm: `TKOFF_THR_MINACC 8` ile tetikten 0,1 sn sonra "Armed AUTO, xaccel = 8.7 m/s/s" →
"Triggered AUTO", 1 sn'de yer hızı 24 m/s, 3 sn'de 60 m AGL. Mevcut TKOFF parametreleri: `TKOFF_THR_MINACC/DELAY/MINSPD/MAX/MAX_T/SLEW/IDLE`,
`TKOFF_ROTATE_SPD`, `TKOFF_LVL_PITCH/LVL_ALT`, `TKOFF_GND_PITCH`, `TKOFF_FLAP_PCNT`, `TKOFF_TDRAG_ELEV/SPD1`, `TKOFF_ACCEL_CNT`, `TKOFF_ALT/DIST`,
`ARSPD_USE` (SITL varsayılanı 0; dokunulmaz).

| Yöntem | SITL modeli | Parametreler (`launch_parametreleri`; ilk kalp atışında ve `cmd takeoff`ta `TKOFF_ALT` ile) | `cmd takeoff` dizisi (`_kalkis_dizisi`) |
|---|---|---|---|
| wheels | `plane` | `TKOFF_THR_MINACC 0`, `TKOFF_THR_MINSPD 0`, `TKOFF_ROTATE_SPD 12`, `TKOFF_LVL_PITCH 15` | mode TAKEOFF + ARM → `armed` → `launch` (pist koşusu) → AGL ≥ 1 m → `released` |
| ramp | **`plane-catapult`** (`drone_sitl.YONETICI.baslat(..., model=)` geçersizleştirmesi; TIP_ESLEME değişmez) | `TKOFF_THR_MINACC 8`, `TKOFF_THR_DELAY 2`, `TKOFF_THR_MINSPD 0`, `TKOFF_ROTATE_SPD 0`, `TKOFF_LVL_PITCH = açı`, `SERVO7_FUNCTION 0` | mode TAKEOFF + ARM → `armed` → 1,2 sn → `DO_SET_SERVO 7 1900` + `launch {angle_deg}` → yer hızı ≥ 8 m/s ya da AGL ≥ 2 → `released {speed_kmh}`; 2,5 sn sonra servo 1100 (tetik sıfırlanır) |
| vehicle | `plane` | `TKOFF_THR_MINACC 0`, `TKOFF_THR_MINSPD 0`, **`TKOFF_ROTATE_SPD = bırakma hızı (m/s)`**, `TKOFF_LVL_PITCH 15` | mode TAKEOFF + ARM → `armed` → `launch {release_kmh}` (araç sürüyor) → yer hızı ≥ %95 bırakma hızı ya da AGL ≥ 3 → `released {speed_kmh}` |

WS olayı: `{t:'launch', method, phase:'armed'|'launch'|'released', ts, alt? | angle_deg? | release_kmh? | speed_kmh?}` (olay şeridi metinleri ön yüzde,
çevrili); `reset` aşamayı sıfırlar (dizi iptal).

**Yerde kayma — kök neden ve düzeltme (arduplane 4.7.2 SITL, pymavlink ile ölçüldü; kaynak Plane-4.7.2 `SIM_Plane.cpp`, `SIM_Aircraft.cpp`,
`ServoModel.cpp`, `SIM_GPS.cpp`):** kayma **fiziksel**, GPS/EKF gürültüsü değil. Disarm, gaz 0, rüzgâr 0 iken 60 sn'de SIMSTATE (gerçek fizik)
**235,8 m** kuzeye (burun yönü), GPS_RAW_INT 235,1 m, GLOBAL_POSITION_INT (EKF) 236,5 m, hız sabit 3,97 m/s; rüzgâr 3 m/s 270° ve `plane-catapult`
modelinde aynı. Neden: SITL `ServoModel::filter_range` gaz kanalını **sabit 1000–2000 µs** aralığına eşler ((pwm−1000)/1000); ArduPlane disarm'da
(ARMING_REQUIRE 1) gaz çıkışını `SERVO3_MIN = SERVO3_TRIM = 1100` (varsayılan; SERVO_OUTPUT_RAW ile görüldü) yapar → SITL **%10 itki**
(plane: thrust_scale 28 N → 2,8 N ≈ 1,4 m/s²); `SIM_Plane` yer sürtünmesi yalnız `accel.x −= 0,3·v` → denge hızı ≈ 4 m/s. `SIM_GND_BEHAV`
plane modelinde okunmaz (yalnız `add_twist_forces` çağıran modeller; ölçüm: 1/2'de de 117 m / 30 sn); `SIM_ENGINE_MUL` etkisiz; `ARMING_REQUIRE 2`
(0 PWM → −%100 itki, FWD_ONLY sıfırlar) durdurur ama hileli. **Düzeltme:** `PLANE_YER_PARAMLARI` = `SERVO3_MIN 1000`, `SERVO3_TRIM 1000`
(`launch_parametreleri` her yöntemde; ilk kalp atışında ve `cmd takeoff`ta yazılır) → disarm'da itki 0 → 60 sn'de SIMSTATE/GPS **0,000 m**, EKF
0,014 m (rüzgâr 0 ve 3 m/s; plane ve plane-catapult). Uçuşta gaz eşlemesi SITL'in varsaydığı 1000–2000 ile birebir örtüşür; dünya rüzgârı
(`SIM_WIND_SPD/DIR`) değişmeden uçuşta etkin kalır (rüzgâr kaymaya katkı yapmıyordu).

**GPS / RTK:** SITL u-blox arka ucu (`SIM_GPS1_TYPE 1`) PVT `flags = carrsoln fixed` yazar → ArduPilot **zaten RTK Fixed (fix_type 6)** bildirir
(GPS_RAW_INT fix 6 ölçüldü) ve yatay konuma gürültü eklemez (`SIM_GPS1_NOISE` yalnız irtifa sinüsü, `SIM_GPS1_ACC` yalnız raporlanan doğruluk,
`VERR` hız hatası). `GPS_RTK_PARAMLARI` tüm tiplerde ilk kalp atışında yazılır: `SIM_GPS1_ACC 0.02`, `SIM_GPS1_NUMSATS 18`, `NOISE/VERR_XYZ/GLTCH_XYZ/
DRFTALT 0` (adlar ikilide `param_request_list` ile doğrulandı). Sahte kip de `gps_fix 6, sats 18` verir. Askeri HUD GPS satırı fix türünü yazar
(`RTK` / `RTK FLT` / `DGPS` / `3D` / `2D`); web HUD'daki (`flightsim.js`) "3D" metni ayrı iş (öneri: aynı eşleme).

**3B:** düzenek (rampa römorku / pickup) pist başında **sabittir**: demir bir kez atılır (`rig.needsAnchor` → `anchor(p, terrainHeight)`), yalnız SITL
konumu > 2 m sıçrarsa (reset / set_home) yeniden oturtulur; araç `launch` aşamasında SITL yer koşusunu taşıdığı için her kare izler (`rig.tracking`).
**Yüzeye oturma:** düzenek `z = 0` varsayımıyla değil, altındaki yüzeye göre durur — 4 temas noktası (tekerlekler; rampa ±0,95/±1,3 m, pickup
±0,92/−1,6…1,85 m × ölçek) `rigSurf(x, y)` ile örneklenir → yükseklik (ortalama) + eğim (ön/arka → pitch, sağ/sol → roll, ≤ 20°; `surfaceFit`;
Euler `ZXY`: yerel roll, pitch, sonra pist yönü); eğimden doğan kızak XY kayması ikinci geçişte düzeltilir (SITL uçağı kızakta kalır).
`rig.resurface(rigSurf, offset)` her 500 ms yeniden örnekler ve hedefe 0,25 sn'de yumuşak yaklaşır; uçak kızakta düzenekle birlikte (`planeQuat` =
düzeneğin dünya yönelimi × rampa eğimi).
*Örnek kaynağı (`flightsim3d.js rigSurf`):* **Google 3B** → `g3d.surfaceAt` (§11; ışın yalnız karo grubuna; `{z, fine, err}`; karo yoksa `fine=false`,
yedek `dem = 0`: merkez yüzeyi `groundOffset` ile 0'a oturur) · **gerçek arazi** → arazi **örgüsüne** ışın (`terrain.mesh`, yalnız o nesne; ızgara
bilineer interpolasyonu ile görünen üçgenler arasındaki fark giderilir), örgü dışında `terrain.height` · **prosedürel** → analitik `terrain.height`
(her zaman ince).
*Yüzey kilidi (`flightsim_launch.js surfaceLock`, saf; `RIG_FINE_ERR` 2 m, `RIG_LOCK_DELTA` 0,35 m):* Google'da aşağı ışın önce **kaba** karoya
çarpar (kök/ara LOD, onlarca m hata), ince karo sonra gelir ve LOD kamera ile kabalaşıp incelebilir. Eski "|h| > 8 m → 0" eşiği eğimli/dağlık
merkezlerde gerçek yükseklikleri de atıyordu (düzenek `z = 0`'da yüzeyin üstünde/içinde) ve her LOD değişiminde düzenek oynuyordu — **kök neden**.
Artık: (1) 4 nokta da ince (`geometricError ≤ 2 m` ya da yaprak karo) ve kilit yoksa değerler alınır ve **kilitlenir**; (2) kilitliyken 4 nokta ince
→ nokta başına |Δ| ≤ 0,35 m küçük düzeltme uygulanır, daha büyük sıçrama (LOD kabalaşması, başka karo) **yok sayılır**; (3) herhangi bir nokta ince
değilse önceki kabul edilmiş değerler **korunur** (kilit düşmez; hiç değer yoksa ince olanlar alınır, kaba olanlar `dem` ile dolar — kök karo asla
kullanılmaz); (4) daha ince karo gelirse (`err` küçüldü) **yeniden kilitlenir**; (5) `groundOffset` değişirse saklı değerler aynı miktarda kayar.
Yeni demirde (`anchor`) kilit sıfırlanır. Testler: `node tests/test_flightsim_launch.mjs` (surfaceLock/surfaceFit 6 test).
Teşhis: `sim.rigState()` → `{phase, surface:{z, pitch_deg, roll_deg}, x, y}`; **`window.__fsRig()`** (her oturumda) → `{h, target, pitch, roll, fine,
geomErr, locked, lockErr, accepted[4], samples[4]:{z, fine, err, dem}, event (init|lock|relock|adjust|ignore|hold), locks, ignored, holds, fits, offset,
google, real, mesh, g3dOffset, g3dLoading, shownZ, rel}`; **`?rigdiag=1`** sahnenin sol üstünde canlı kutu (`.fs-rigdiag`, 500 ms).
*Doğrulama (DEV, gerçek Google anahtarı, Playwright SwiftShader; `/tmp/flsim/rigsurf/e2e_rig.py`, `?rigdiag=1` + `__fsRig()` saniyede bir):*
Bedesten (39,8565/33,3998; eğimli) rampa: t = 3/10 sn karo yok → `hold` (h 0, kaba değer uygulanmadı), t ≈ 25 sn ilk ince ölçüm → **kilit**
(yaprak karo, geometricError 4,01 m; 4 nokta −0,27/−0,02/0,37/0,68 m → h 0,19 m, pitch 5,9°, roll −3,4°), son 30 sn'de |Δh| = **0,009 m**,
yoksayılan 0, 638 glb, 0 hata; Fırlat → `released` sönümü 2,1 sn'de başladı, gösterilen z hiçbir karede düşmedi (4,85 → 15,9 → 29 m).
Prosedürel (Ankara) regresyon yok: h 0, kilit anında, |Δh| 0. Diğer merkezler (TRTEST, Ankara düz; araç; gerçek arazi) aynı betikle koşulur.
Uçak `released`'a dek kızağa kilitlidir (SITL konumu yok sayılır). **`released` geçişi (ofset sönümü):** eski 0,3–0,6 sn'lik düz lerp uçağı
SITL'in henüz yerdeki (z ≈ 0, hızlanıyor) konumuna indiriyordu — "rampadan çıkarken rampanın altına inip oradan yükseliyor". Artık `released`
anında kızak ucu (3B konum + yönelim) ile SITL konumu/yönelimi arasındaki fark ölçülür (`rel.off`, `rel.dq = q_kızak · q_SITL⁻¹`) ve uçağa eklenir;
yatay ofset ve yönelim farkı `k = min(1 − smooth(0…3 sn), 1 − smooth(AGL 4,5…15 m))` ile 3 sn'de ya da AGL 15 m'de sıfıra iner; **dikey ofset
yalnız uçağın kendi tırmanışıyla erir** (`kz` azalması ≤ v_z·dt/off_z → gösterilen z hiçbir karede düşmez; 6 sn'den sonra her durumda 1 sn'de
kapanır). Uçak rampa ucundan çıkıp doğal tırmanır, asla rampa/kasa altına inmez; araçta aynı mantık (kasa kızağı yüksekliği). Teşhis:
`sim.releaseBlend()` → `{t, kz, off}`, `sim.shownZ()` (gösterilen z, alt_rel ölçeği). SITL tarafında ek parametre gerekmedi (`plane-catapult`'ta
fırlatma pitch'i parametresi yok; `TKOFF_LVL_PITCH` = açı zaten yazılıyor). **Yerde kilit:**
disarm + AGL < 1 m + yer hızı < 0,5 m/s iken gösterilen konum dondurulur (EKF'nin cm'lik gezinmesi görünmez; `groundLocked`; kilit z'si
altındaki yüzeyden aşağı olmaz → tekerlekli uçak eğimli gerçek yüzeye gömülmez), ARM/hareketle 0,4 sn'de
SITL konumuna döner, > 1,5 m sıçrama kilidi yeniden oturtur. Mission Planner haritasıyla tutarlılık: SITL artık kaymadığından haritadaki uçak ile 3B'deki
düzenek/uçak aynı noktadadır (EKF ↔ SIMSTATE farkı 1–2 cm). Araç üstünde SITL'in doğrudan karşılığı yoktur: SITL'de uçak TAKEOFF yer koşusunu kendisi yapar (gaz açık),
`TKOFF_ROTATE_SPD` bırakma hızına eşit olduğundan uçak o hıza dek yerde kalır; 3B'de pickup bu yer koşusu boyunca uçağın altında (uçakla aynı hızda)
gider, uçak kasa kızağında yükseltilmiş gösterilir, `released` ile kasa ofseti sönümlenerek SITL konumuna geçer (aşağı inmez) ve araç 4 m/s² ile
frenleyip durur (pist dışına da sürer; yüzey oturması 500 ms'de bir yeniden örneklenir). Sahte kinematik (`HEPGO_SITL=0`) ve `?mock=1` üç yöntemi de taklit eder (rampa: 1,2 sn bekleme + 0,5 sn'de 22 m/s;
araç: 2,5 m/s² ivme, bırakma hızında kalkış; tekerlekli: 4 m/s², 12 m/s'de kalkış).

**3B (`flightsim_launch.js`, `flightsim3d.js` `setLaunch(cfg)` / `setLaunchPhase(p)`):**
- *Tekerlekli:* `addLandingGear` — burun (çatallı) + 2 ana tekerlek, çatallar; yarıçap kanat açıklığından (≈ %4,5, 6–25 cm); modelde `gear|wheel|teker|landing`
  adlı düğüm varsa eklenmez (Caymaz GLB'de yok → eklenir). Tekerlekler AGL < 1,5 m iken yer hızıyla döner; geri çekme yok.
- *Rampa:* `createLaunchRig('ramp')` — 4 tekerlekli römork şasisi (çeki demiri, 4 ayak), azimut tablası (Z ekseni, halka), eğim pivotu (X ekseni, açı =
  `angle_deg`), 6 m çift ray + traversler + uç tamponu, rayın altında pnömatik fırlatma tüpü + piston, şasiden raya eğim silindiri (sarı gövde + krom
  piston), basınç tüpü + kompresör/valf kutusu + ikaz lambası (gece yanar), kızak (ray pabuçları, yastıklı destekler; `attach` noktası). Uçak kızağa
  oturur (pitch = açı, pist yönü). "Fırlat": kızak 6 m'yi 0,5 sn'de sabit ivmeyle alır (çıkış hızı 2L/t = 24 m/s ≈ 86 km/h, bilgi satırında), ray sonunda
  `released` → uçak kızak ucu ofsetiyle SITL'i izler, ofset 3 sn / AGL 15 m'de sönümlenir (yukarıda); kızak 1 sn sonra sönümleyiciyle geri döner.
  Dizi dışı hareket (hız > 8 m/s ya da AGL > 3 m) düzeneği kendiliğinden serbest bırakır.
- *Araç:* `createLaunchRig('vehicle')` — pickup: şasi, 4 tekerlek (jant + cıvatalar; dönerler), kaput, ızgara, krom tamponlar, kabin (eğik ön cam, yan/arka
  camlar, aynalar), kasa (taban, yanlar, arka kapak), kasa kızağı (A-destekler + yastıklar; `attach`), farlar/stoplar (gece yanar), tepe lambası.
  Başlangıçta kızak pist merkezinde (uçak = SITL evi). `launch`: araç SITL uçağını taşır; `released`: fren.
- Düzenek pist yönüne döner, dron gibi `MODEL_SCALE` ile büyütülür, gölge düşürür; sihirbaz önizlemesinde de görünür (açı canlı). **Yer** kamerası (4)
  düzenek varsa onun yanından bakar. Dünya yeniden kurulunca (saat/pist yönü) düzenek yeniden kurulur.
- `setLaunchPhase(p, snap)`: hedef aşama mevcut aşamadan ÖNCE ise (kayıt geri sarma / Baştan) önce `idle` (kızak/araç başa); `snap` released ofset sönümünü
  (`rel`) kurmaz. Canlıda `snap` kullanılmaz.

**Oturum ekranı:** üst şeritte yöntem rozeti ("Rampa 20°" / "Araç 70 km/h" / "Tekerlekli"), sağ panelde "Kalkış" satırı, **Kalkış** düğmesi
yönteme göre "Fırlat" / "Aracı sür" / "Kalkış" (modal ipucu yönteme göre), olay şeridinde aşamalar (FIRLATMA, BIRAKILDI · 68 km/h, …), askeri HUD sol
alt bloğunda `LAUNCH RAMP 20° · 86 km/h` / `LAUNCH VEH · 70 km/h` / `LAUNCH RWY` satırı. 6 dil.

**E2E ölçümü (gerçek SITL arduplane, Ankara, rampa 15° / araç 70 km/h, gerçek arazi ve Google 3B gerçek anahtar + Referer; `/tmp/flsim/terr/e2e_terr.py`,
görüntüler `/tmp/flsim/terr/shots/`):** `released` sunucudan rampada komuttan 2,1 sn, araçta 3,8 sn sonra (31–33 km/h / 67 km/h). Tarayıcı içi rAF kaydı
(gösterilen z `shownZ` ↔ SITL z, dikey katsayı `kz`): rampa-gerçek arazi `4,96 (kızak ucu) → 10,5 (SITL 5,9; kz 0,95) → 19,5 (16,8) → 40,0 (39,1) → 60,1`,
rampa-Google `4,94 → 5,10 → 17,0 → 49,0 → 56,5`, araç-gerçek `4,65 (kasa) → 9,0 → 10,5 → 25,1 → 44,0` — **hiçbir karede düşüş yok** (eski kodda uçak
0,6 sn'de z≈0'a iniyordu); 20 sn'de AGL 60 m, çarpışma yok. Düzenek: gerçek arazide merkez düzleştirmesi içinde z 0 / 0°; Google 3B'de rampa
`z −0,03 m, pitch 0,70°, roll 0,01°`; araç ilk kaba karoda `z −3,4 m, pitch −0,96°` iken 12 sn'de (ince karolar) `z 0,007 m, pitch 0,28°, roll 0,18°`
— kullanıcıdaki "haritanın üzerinde uçuyor" izlenimi bu ilk kaba-karo yüksekliğiydi (yeniden örnekleme ile kendiliğinden oturur). Kaba kök karo
ilk 2,5 sn'de −280 m ölçtürebildiğinden Google'da |h| > 8 m örnek yok sayılır (`rigSurf`; düzenek merkezden ≤ 20 m uzakta, gerçek fark birkaç m).
Google toplam yer ofseti −32,7…−33,3 m (olay şeridine artık bu yazılır). Not: yazılım WebGL'de (4–8 fps) `released` ekran görüntüleri çekim gecikmesiyle ~60 m'de yakalanır;
anlık kanıt zaman serisidir.

**Testler (`kalkis_testleri`):** `world.launch` 400'leri (yöntem, açı 5/31, hız 30/120, nesne değil, bool), varsayılanlar, VTOL normalizasyonu,
parametre setleri (ramp/vehicle/wheels; her birinde `SERVO3_MIN/TRIM 1000`; `GPS_RTK_PARAMLARI` doğruluk ≤ 5 cm, ≥ 12 uydu, hata alanları 0),
sahte kipte yerde kilit (takeoff öncesi 0,6 sn: konum sabit, yer hızı 0, `gps_fix 6`), sahte kipte üç yöntemle `cmd takeoff` → WS `armed → launch → released` (rampa: launch 1,0–2,5 sn sonra,
fırlatma anında uçak duruyor, released ≥ 26 km/h; araç: released hızı 60 km/h ±%10; tekerlekli: AGL ≥ 1), `session.launch.phase`, reset sonrası null.

### 13.1 Kontrol düzeni — Aileron + Elevatör (T-kuyruk) · Elevon (delta kanat) · V-kuyruk (ruddervator) (`session.layout`; `flightsim.LAYOUT_PARAMLARI`, `static/js/modules/flightsim_airframe.js`)
Kullanıcı isteği: "Aileron + Elevatör (T-kuyruk) · Elevon (delta kanat) · V-kuyruk ayrımı … Caymaz delta elevon kontrol ediyor, onu da tanıtalım".
Sihirbazda **Sabit Kanat** seçilince Kalkış yöntemi kartlarının altında **Kontrol düzeni** kartları açılır (`.fs-layout[data-layout]`; kayıt
kipinde ve diğer tiplerde gizli); bilgi satırı SITL modelini ve parametre setini yazar. **Model seçilince modelin düzeni seçilir** (Caymaz /
Delta → Elevon, Talon → V-kuyruk; yüklenen GLB'de yüzey düğüm adlarından), kullanıcı sonra kartlardan değiştirebilir; model kartlarında düzen
rozeti ("Elevon · Önerilen" seçili düzene uyanlarda yeşil, listede öne alınır). Oturum gövdesi `layout: classic | elevon | vtail` (eksikse
modelin düzeni → `classic`; VTOL/kopterde null; bilinmeyen değer 400). Oturum nesnesi: `layout` (istenen), `layout_effective` (SITL'de
fiilen uçan), `layout_sitl_model` (`plane[-elevon|-vtail][-catapult]`), `layout_skipped` (kalıcı kayıt yüzünden yazılmayanlar). Üst şeritte
rozet (etkin ≠ istenen ise sarı), sağ HUD'da "Düzen" satırı, Simülasyon Kayıtları tablosunda **Detaylı → "Düzen sütunu"** (Kalkış'tan sonra;
`drone_sim_runs.layout` = etkin düzen), özet raporda "Kontrol düzeni · SITL modeli" satırı (`summary.session.layout*`).

**Parametre setleri (`LAYOUT_PARAMLARI`; ArduPlane 4.7 `SRV_Channel.h` kodları: 4 Aileron · 19 Elevator · 21 Rudder · 77 ElevonLeft · 78 ElevonRight ·
79 VTailLeft · 80 VTailRight) — oturum BAŞLANGIÇ setidir ama dron yapılandırması sayılır (FLAP_PARAMLARI gibi): kalıcı kayıtta olan ad yazılmaz,
kullanıcı MP/panelden değiştirirse kalıcı kaydedilir; `varsayilan.parm`'a da yazılır (SITL ilk andan doğru) ve ilk kalp atışında PARAM_SET yinelenir:**

| Düzen | SERVO1 | SERVO2 | SERVO4 | REVERSED (1/2/4) | MIXING_GAIN | SITL modeli |
|---|---|---|---|---|---|---|
| classic | 4 aileron | 19 elevator | 21 rudder | 0 / 0 / 0 | — | `plane` |
| elevon | **78** elevon R | **77** elevon L | 0 (rudder yok) | **1 / 1** / 0 | 0,5 | **`plane-elevon`** |
| vtail | 4 aileron | **80** V-kuyruk R | **79** V-kuyruk L | 0 / **1** / 0 | 0,5 | **`plane-vtail`** |

*Gerekçe.* Karışım ArduPlane içindedir (`SRV_Channels::channel_function_mixer`, kazanç `MIXING_GAIN` varsayılan 0,5 = doymaz: elevon L = g(e − a),
R = g(e + a); V-kuyruk L = g(e + r), R = g(e − r); + = arka kenar yukarı). **SITL fiziği (`SIM_Plane.cpp`) kanal sabitlidir** ve karışımı geri
çözer: `-elevon` son eki kanal 1/2'yi elevon çifti (aileron = (ch2−ch1)/2, elevator = −(ch2+ch1)/2), `-vtail` kanal 2/4'ü ruddervator çifti
(elevator = (ch4−ch2)/2, rudder = (ch4+ch2)/2) olarak okur; düz `plane` 1 aileron / 2 elevator / 4 rudder. Bu yüzden düzen ↔ SITL modeli birlikte
seçilir ve setler **ArduPilot'un kendi SITL kurulumlarıdır** (`Tools/autotest/default_params/plane-elevons.parm`: SERVO1 78, SERVO2 77,
SERVO1/2_REVERSED 1; `plane-vtail.parm`: SERVO2 80, SERVO4 79, SERVO2_REVERSED 1 — Plane-4.7.2 etiketinden doğrulandı). REVERSED burada karışım
işaretini SITL fiziğinin beklediği yöne çevirir; kalıcı kayıtta `SERVOn_REVERSED` yoksa `SIM_SRV_REV` maskesine girmez (stok davranış = autotest).
**Elevon düzeni kararı:** eski §20.1 notu "77/78 yazılmamalı" düz `plane` modeli içindi; düzen seçimiyle SITL modeli de `-elevon` olduğundan artık
gerçek ArduPlane elevon kurulumu (77/78 + MIXING_GAIN) kullanılır. **Kalıcı kayıt önceliği:** CAYMAZ'ın PROD kaydı 4/19 ise (dron 5) Elevon seçilse
de kalıcı değerler yazılmaz; SITL model son eki **etkin** fonksiyonlardan türetilir (`layout_etkin_fn`: ArduPlane varsayılanı ← düzen seti ← kalıcı
kayıt; `sitl_model_eki`: {1,2} = {77,78} → `-elevon`, {2,4} = {79,80} → `-vtail`, aksi düz — çift başka kanaldaysa fizik göremez) → düz `plane` ile
açılır, eski davranış birebir korunur; konsola sarı not "Kontrol düzeni Elevon: dronun kalıcı kaydı öncelikli (SERVO1_FUNCTION, …) → SITL fiilen
Aileron + Elevatör kurulumuyla uçuyor (model plane)". Oturum sırasında MP'den fonksiyon değiştirilse SITL modeli değişmez (yeni oturumda).
Rampa ile birleşir: `plane-vtail-catapult` (SIM_Plane son ekleri `strstr` ile; constructor `plane` ön ekiyle eşleşir).

**3B (`flightsim_airframe.js`, saf; `flightsim3d.js updateCtrl` buradan beslenir):** `CTRL_RE` artık `ruddervator` düğümlerini de tanır.
`controlInputs({servo, fn, rev, rc, mode, armed})`: SERVO_OUTPUT_RAW → **mantıksal** çıkış (`logicalOutputs`: SERVOn_REVERSED kanalında işaret
geri çevrilir — gerçek uçakta ters monteli servo PWM'i geri çevirir, yüzey mantıksal yöne gider; sunucu `tele.servo_rev` SERVO1..8_REVERSED
PARAM_VALUE'dan) → işlev kodlarıyla eksenler: 4/19/21 doğrudan; 77/78 ve 79/80 çiftleri **doğrudan yüzey çıkışı** olarak alınır ve eksenler
geri çözülür (e = (L+R)/2, a = (R−L)/2 ya da r = (L−R)/2). `surfaceTarget(surface, side, o)` düğüm adına göre (° arka kenar aşağı +): aileron
±a, elevator −e, rudder +r, elevon L −(e−a) / R −(e+a), **ruddervator L −(e+r) / R −(e−r)**, flap +f. Böylece düğüm adı düzenden farklı modelde de
(Caymaz + V-kuyruk düzeni, Talon + klasik düzen) yüzeyler tutarlı oynar: V-kuyrukta sağa sapma komutunda **sol ruddervator arka kenarı yukarı,
sağ aşağı**; burun yukarıda ikisi yukarı. Teşhis: `window.__fsCtrl()` (= `sim.ctrlState()`: servo, servoFn, servoRev, layout, inputs
{ail, ele, rud, flap, elevonL/R, vtailL/R}, surfaces[{name, deg, tgt}]), `window.__fsTele()` (son kare), `sim.ctrlLayout()`.

**SIMUMAV:** `drones.airframe` sütunu (init'te `ALTER TABLE` ile eklenir; `bridge.AIRFRAMES`, `airframe_dogrula`, `drone_airframe`: sütun → katalog
modelinin `airframe` → classic; yalnız plane/interceptor), `POST/PUT /api/hangar {airframe}` (422 bilinmeyen; model değişip düzen gönderilmezse
yeni modelin düzeni), `drone_api().airframe`, katalog modellerinde `airframe` (`GLB_MODELS`: talon_vtail vtail, rc_cessna/believer/jet classic,
zephyr elevon; `PROC_MODELS` interceptor elevon; dahili `layout`), `glb:talon_vtail` kataloğa eklendi (`MODEL_ESLEME → builtin:talon`),
uçuş açılışı `MANAGER.ac(..., layout=drone_airframe(drone))`, `flights.snapshot.drone.airframe`. Ön yüz: hangar sihirbazı model adımında
sabit kanat ailesinde "Kontrol düzeni" kartları (`.airframe-card`, modelin düzeni rozetli; `draft.airframe`), hangar kartı/alt yazısında düzen
etiketi; `fly/wizard.js` `AIRFRAMES/airframeOf/airframeForModel/airframeLabel/needsAirframe` (dron bilgi satırında düzen); i18n `airframe.*` 7 dil.

**Doğrulama (GERÇEK SITL arduplane 4.7.2 yamalı `/opt/hepgo/sitl/bin`, Playwright headless shell + SwiftShader; `/tmp/flsim/airframe/e2e_airframe.py`,
port 8740, görüntüler `/tmp/flsim/airframe/*.png`, ölçüm `olcum.json`; tele roll/pitch radyan → derece):** dört oturum, tekerlekli kalkış 60 m
(ARM'siz Kalkış komutu), 60 sn:
| Senaryo | SITL modeli (`varsayilan.parm` satırları) | Kalkış / 60 sn | FBWA + sanal kumanda (ilk tepki 0,35 s; 3B hedef ° arka kenar aşağı +) |
|---|---|---|---|
| vtail (Talon) | `plane-vtail` · SERVO1 4 · SERVO2 80 · SERVO4 79 · SERVO2_REVERSED 1 | launch 1,1 s → released 3,2 s; AGL 58–62 m; TAKEOFF sonrası loiter bankası 45° (ROLL_LIMIT), takla yok | **sağa rudder (ch4 1900)**: servo2 1764 (R, REVERSED → mantıksal −0,63), servo4 1623 (L +0,37) → **ruddervator_l −9,1° (arka kenar YUKARI), ruddervator_r +15,8° (AŞAĞI)**, yaw −137° → −111° (sağa) · sağa yatış: aileron_l +6,6° / aileron_r −6,6°, roll 1° → 49° · burun aşağı (ch2 1100): ruddervator'lar ikisi +2,8° → +7,8°, pitch 72° → 40° |
| elevon (Caymaz) | `plane-elevon` · SERVO1 78 · SERVO2 77 · SERVO4 0 · REVERSED 1/1/0 · MIXING_GAIN 0,5 | aynı; AGL 58–62 m; takla yok | sağa yatış: elevon_l +5,7° (aşağı) / elevon_r −1,6° (yukarı), roll 0° → 41° · burun aşağı: elevonlar +2,1° → +9,6°, pitch 71° → 40° · rudder komutu etkisiz (SERVO4 0) |
| classic (Caymaz, 3B elevonlar eksenlerden) | `plane` · 4 / 19 / 21 · REVERSED 0 | aynı; AGL 59–61 m | sağa yatış: roll 1° → 50°, elevon_l +7,8° / elevon_r −3,4° (e ± a) · burun aşağı: pitch 50° → 6° · sağa rudder (ch4 1896 → rud +1): yaw −126° → −93° |
| kalici (dron kaydı SERVO1/2_FUNCTION 4/19 + SERVO1_REVERSED 1, düzen Elevon) | **`plane`** (kalıcı öncelikli); parm: 4/19 + REVERSED 1/0 + düzen setinden SERVO4 0 / MIXING_GAIN | 45 sn kararlı; AGL 59–61 m | konsol (sarı): "Kontrol düzeni Elevon (delta kanat): dronun kalıcı kaydı öncelikli (SERVO1_FUNCTION, SERVO2_FUNCTION, SERVO1_REVERSED, SERVO2_REVERSED) → SITL fiilen Aileron + Elevatör (T-kuyruk) kurulumuyla uçuyor (model plane); yazılan: SERVO4_FUNCTION 0, SERVO4_REVERSED 0, MIXING_GAIN 0.5"; oturum `layout elevon / layout_effective classic / layout_sitl_model plane` |
Konsol notu (bilgi) diğerlerinde: "Kontrol düzeni V-kuyruk (ruddervator): SITL modeli plane-vtail · yazılan SERVO1_FUNCTION 4, SERVO2_FUNCTION 80, …".
3B `servo_fn [4, 80, –, 79, 3, 3]` / `servo_rev [0, 1, –, 0]` telemetriyle geldi; Talon yüzey düğümleri `aileron_r/l`, `ruddervator_r/l`. Sihirbaz:
Sabit Kanat → düzen Elevon (Caymaz varsayılan), Talon kartı seçilince düzen V-kuyruk + model rozetleri ("Elevon · Önerilen" → "V-kuyruk · Önerilen"),
dönen önizleme Talon (wizard-0*.png); konsol hatası yok. Not: `ctrlState()` girişleri son kareden taze hesaplar (düşük fps'te kare gecikmesi
servo ile eşleşmiyordu).

**Testler:** `node tests/test_flightsim_airframe.mjs` (9: setler, CTRL_RE, layoutForModel, logicalOutputs, klasik/elevon/V-kuyruk girişleri ve
yüzey hedefleri, flap, easeSurface), `tests.test_flightsim duzen_testleri` (400, model → düzen, setler = autotest, kalıcı öncelik/etkin
düzen/son ek, `builtin:talon` kütüphane + GLB, oturum alanları, WS `servo_fn/servo_rev`, dron kaydı 4/19 → etkin classic + `plane`),
`tests.test_simumav` (katalog airframe, hangar POST/PUT/422, kopterde null), `tests/test_simumav_fly.mjs`, `tests.test_simumav_models`.

## 14. Harekât paneli: YERLİ panel (`app/flightsim_hub.py`, `static/js/modules/flightsim_panel.js`; iframe YOK)
Kullanıcı kararı: "Uçuşun verilerini ve yönetimsel işlemlerini canlı uçuşta kullandığımız panel ile yapalım" → önce GÖKTUNGU harekât ekranı
(`static/ops`) şeffaf iframe'le gömüldü; canlıda (Chrome, koyu tema) Panel açılınca ekran BEMBEYAZ oldu. İkinci karar (birebir): "sistem HTML değil mi?
neden komple bir objeye ihtiyaç duyuyorsun; gerekiyorsa aynı görünümde mevcut altyapı üzerine bir panel yarat" → iframe tamamen kaldırıldı; panel
simülatör sayfasının kendi HTML/JS'idir (ui.js `h()`, `.fs-hud` dili). `static/ops`, `hepgo.css`, `hepgo_ws.js`, `hepgo_patch.js` sim-kipi
eklerinden (`?sim=`, `html[data-hepgo-sim]`, haritasız sahte Cesium, `hepgo_sim.js`, `hepgo_nomap.js`) arındırıldı — görev kipi (`?task=`) c1de8a2
öncesi hâlindedir.

**Beyaz ekranın kök nedeni (kanıtlı).** HEPGO koyu teması `html[data-theme="dark"] { color-scheme: dark }` (app.css) tanımlar; `<iframe>` öğesi
`color-scheme`'i üst belgeden MİRAS alır (dark), GÖKTUNGU iç belgesi (`static/ops/index.html`) hiçbir `color-scheme`/meta bildirmez (normal/light).
Chromium, iframe öğesinin ve gömülü belgenin kullanılan renk şeması uyuşmazsa iframe'i (şeffaf isteyen CSS'e rağmen) OPAK tuvalle — beyaz —
çizer (CSS Color Adjust: "If the embedded document's used color scheme differs from the embedder's, the canvas is rendered opaque"). Testler açık
temada koştuğundan (data-theme yok → normal = normal) görülmedi; kullanıcı koyu temada. Ölçüm (Playwright, eski kod f95e95a, sahte kip, 1400×840,
beyaz = RGB ≥ 250): açık tema %4,8 (sahne), koyu tema %49,7 (iframe opak); iç belgeye `color-scheme: dark` ya da iframe'e `color-scheme: normal`
verilince %0,13. Yerli panelde iframe olmadığından kartlar her temada koyu yarı saydamdır (koyu temada ölçüm %0,13).

**Mimari — oturum = hub'da sanal köprü (değişmedi).** `SimSession.run()` UDP portu açılınca `flightsim_hub.attach` ile `drone_hub.SIMS`'e `SimBridge`
kaydeder: `bridge_id = -(9000+N)`; SITL mesajları `SimBridge.feed_msgs → drone_hub._feed_msgs` (DroneState, STATUSTEXT → event + konsol, COMMAND_ACK
→ KOMUT satırları); sahte kipte kinematikten MAVLink çerçeveleri üretilir (`_sahte_hub_cerceve`). Komutlar hub işleyicisinden (`send_command →
_single_command / _start_sequence → _dispatch → SimSession.hub_komut → MavKomut` asenkron pymavlink; sahte kipte `_sahte_hub_komut`): GÖKTUNGU kalkış
akışı (GUIDED teyit → ARM teyit → NAV_TAKEOFF; sabit kanatta TKOFF_ALT + TAKEOFF modu + ARM), rota başlat/duraklat/sürdür/iptal, goto, altitude_change,
set_home, mission_upload/download/clear/set_current, param_*, arm_check; `reboot` reddedilir. Yetki: `/ws/drone/live` `field.live` ya da `drone.sim`
ile açılır; `watch{sim_id}` ile izleyici yalnız oturum köprüsünü görür (`sim_only`); komut yetkisi `drone.sim` YAZMA izni (`SimBridge.can_command`).
`GET /sessions/{id}/live`, `session.hub/drone/route`, WS `/ws/drone/sim` `{t:'route', points}` aynen (panel ve testler kullanır).

**Ön yüz — `flightsim_panel.js` `createOpsPanel(stage, {sid, session, type, modes, launch, canWrite, hub, getSim, cmdSim, onReset, onToggle})`.**
Kullanıcı geri bildirimi (birebir): "panel güzel ama amatörce görünüyor, paneller arasına boşluk koymuşsun; tek bir panel olacak, duruma göre
küçülüp büyüyecek; orijinal CSS yapısına birebir uy" → ayrı yüzen kartlar KALKTI; panel GÖKTUNGU harekât ekranının **DRON KARTI**'nın
(`static/ops/css/stil.css` `.dron-kart.ayrik`, `hepgo.css`) birebir taşınmış TEK gövdesidir. Kurallar `.fs-pn` altına kapsamlı kopyalandı
(app.css; her kuralın yanında kaynak sınıf): kart `.fs-pn-kart` = `.dron-kart.ayrik` (zemin `--panel-arka` rgba(11,14,17,.94), 1 px `--cizgi`
#1e2630, 6 px köşe, 0 8px 32px gölge; 400 px — hepgo.css; <1100 px 340 px; <760 px tam genişlik), GÖKTUNGU koyu tema değişkenleri `--gt-*`
olarak `.fs-pn` üzerinde (HEPGO açık/koyu temasından bağımsız: kart her temada koyu; beyaz piksel koyu temada %0,13). Kapsayıcı `.fs-pn` tam
alan, `pointer-events: none` (fare/tekerlek 3B'ye), kart `pointer-events: auto`. Kart sağ üstte; **başlık şeridinden sürüklenir**; `max-height`
= alan (sanal kumanda açıkken çubukların üstü); içerik taşarsa gövde kart İÇİNDE kaydırılır (başlık sabit) — panel içeriğe göre küçülüp büyür.
- **BAŞLIK ŞERİDİ** (`.dron-kart-baslik`: 10 px dolgu, 600, `--dugme-arka` zemin, alt çizgi): durum LED'i (`.dk-nokta`: yeşil hazır / sarı
  başlıyor / kırmızı hata / mor kayıt-sahte) · dron adı (`.dk-ad`; Dron Envanteri kaydı ya da "Simülatör #N") · özet (`.dk-baslik-ozet`: irtifa +
  kip) · ARMED/DISARMED ve HUB rozetleri (hepgo.css `.hk-bagla` kapsülü: 22 px, 11 px; bağlı yeşil / kuruluyor sarı / yetki yok kırmızı) ·
  **küçült** (`.dk-kucult-btn`: yalnız başlık şeridi kalır, `.dk-yalniz-baslik`; localStorage `fs.panel.min`). Mission Planner durumu
  MISSION PLANNER bölümünün başlık rozetinde ve GPS karosu alt yazısında ("· MP").
- **MISSION PLANNER bölümü** (İŞLEMLER ile HABERLEŞME arasında; kullanıcı: "alttaki Mission Planner bağlantı panelinde beyaz düğmeler var, onlar da
  uygun renkte olacak ve panel içine collapse şekilde yerleşecek"): UDP adres (mono, seçilebilir) · **Kopyala** (panelin koyu düğmesi `.fs-pn-btn`;
  `.btn` beyaz düğme panelde yok) · kısa gri talimat; durum rozeti ("Bekleniyor" / "Bağlı ip:port", `.fs-pn-rozet`) bölüm **başlığında** → katlıyken
  de okunur. GCS bağlı değilken açık, bağlanınca kendiliğinden katlanır; kullanıcı elle katlar/açarsa tercihi kalır (`fs.panel.fold.mp`; "Yerleşimi
  sıfırla" otomatiğe döndürür). Panel kapalıyken (sade görünüm) ya da FPV'de **aynı DOM** (`placeMp`) sol altta koyu yüzen kutuya (`.fs-mp.fs-pn-yuzen`)
  taşınır; panel görünürken sol altta MP kutusu YOK. `setGcs(on, addr)` tek yerden günceller (flightsim.js yalnız iletir). Kayıt kipinde MP yok.
- **Kaydırma çubukları** (kullanıcı: "scroll ince ve panele uygun renkte"): gövde, konsol ve panel içindeki her kaydırılan öğe 6 px, ray panel
  zemini (`--gt-panel-arka`), tutamaç koyu gri yarı saydam yuvarlak (`.fs-pn ::-webkit-scrollbar*`); Firefox `scrollbar-width: thin` +
  `scrollbar-color` yalnız `@supports not selector(::-webkit-scrollbar)` içinde (Chromium'da `scrollbar-width` tanımlanırsa `::-webkit-scrollbar`
  yok sayılır). Panel kökü ve yüzen kutu `color-scheme: dark` (select/number yerleşik açılır listeleri koyu; `option` zemin/metin panel renkleri).
- **GÖVDE** (`.dron-kart-icerik`: 10 px dolgu, Consolas/mono 12 px). Üst satır (`.dk-ust-satir`): **UÇUŞA HAZIR rozeti** (`.dk-hazir-rozet`:
  "DISARMED · UÇUŞA HAZIR" yeşil / "ARMED · UÇUŞTA" mavi / "DISARMED · PREARM UYARISI" amber / "SITL HATASI" kırmızı / "SAHTE VERİ", "KAYITTAN
  OYNATMA" gri; tıkla → ARM onay penceresi [Zorla] / DISARM onayı) + **İŞLEMLER** düğmesi (`.dk-islem-btn`; İŞLEMLER bölümünü açar/kapar; GÖKTUNGU'da
  bu düğme İŞLEMLER popup'ını açar). Bölümler tek gövdede, ARALARINDA BOŞLUK YOK (ince `--cizgi`); her bölüm `.dk-konsol-bas` tarzı başlık
  şeridinden katlanır (ok döner; `fs.panel.fold`):
  - **UÇUŞ GÖSTERGESİ (PFD)**: canvas 2D (`.dk-pfd-canvas`: zemin/kenarlık yok, 8 px köşe; genişlik × 0,47) — mavi gök / kahverengi yer suni ufuk
    (roll ile döner, pitch ile kayar; ±25°, 5° merdiven), roll yayı + sarı işaretçi, sarı uçak sembolü, sol yer hızı bandı (IAS küçük), sağ AGL
    bandı (MSL), ufuk alanı köşeleri: mod / ARMED / GPS / VS (dikey hız) / BAT; alt yön şeridi (N/E/S/W, ev yönü yeşil üçgen, sayısal heading);
    AUTO'da WP n/m · mesafe. Yönelim 3B'nin render ettiği enterpolasyonlu pozdan (`sim.getPose()`), diğer değerler tele'den; rAF ile kart
    görünürken çizilir (gizli/katlı/küçük/FPV'de çizilmez — tuval ölçüsüz).
  - **TELEMETRİ** 4×2 karo (`.dk-tel-hucre`: ikon 20 px [satır içi SVG; GÖKTUNGU'daki Font Awesome anlamları], Consolas 12 px kalın değer, 9 px
    büyük harf etiket; 6 px aralık, rgba(0,0,0,.18) zemin, 5 px köşe): İRTİFA (m / MSL), HIZ (m/s / km/h), BATARYA (% / V; <%25 amber), GPS
    (fix · uydu; 3D+ yeşil / 2D amber / yok kırmızı); DURUM (kilit ikonu; tıklanır: ARM/DISARM), MOD (tıklanır: `.dk-mod-popup` 3 sütun
    `.dk-mod-btn` menüsü — panel köküne eklenir), TİP, KOMUT (Kalkış / Fırlat / Aracı sür yeşil; havada İniş amber — `.dk-tkland`).
  - **İŞLEMLER** (varsayılan katlı; `.dk-islem-izgara` 3 sütun, `.dk-islem-grup` grup başlıkları, `.dk-islem-hucre` 74 px ikon+metin hücreleri):
    UÇUŞ: Kalkış · İniş · RTL · Ev konumu; HEDEF: irtifa girişi (`.dk-irtifa`) + İrtifa (altitude_change) · Hedefe git (lat/lon/alt penceresi;
    goto); ROTA: Dron Yönetimi › Rotalar listesi (`GET /api/drone/routes`; oturum merkezininkiler önce) → Yükle (`routes/{id}/mission` → hub
    `mission_upload{items, cruise_speed}` → `{t:'route'}` → 3B çizgi + "SITL'de n rota noktası") · Başlat (`mission_start{rota}`) · Duraklat
    (`mission_pause{davranis:'bekle'}`) · Sürdür (`mission_resume`) · İptal (`mission_cancel`; tehlikeli kırmızı); SİM: ↺ Sıfırla (simülatör
    `reset`), Yerleşimi sıfırla. Yetki yoksa hücreler pasif ve nedeni yazılır (yazma izni / hub bağlantısı / hub komut yetkisi / oturum hazır değil).
  - **HABERLEŞME** konsolu (`.dk-konsol`: kart altında, katlanır; `.dk-konsol-bas` başlık: ok · ikon · ad · satır sayacı · temizle; `.dk-konsol-govde`
    #0b0f14 zemin, 10,5 px mono, en çok 168 px, kaydırılır): satırlar `saat ETİKET metin` (KOMUT/ROTA/SİM/STATUS/HUB; sev → renk). Alt ortadaki
    ayrı KONSOL kutusu KALKTI (tek konsol, kart içinde). Kaynaklar: hub `console` çerçeveleri (STATUS etiketi atlanır) + simülatörün kendi
    olayları (`addEvent` → `ops.log`; STATUSTEXT'ler sim WS `event` olarak 'STATUS' etiketiyle) → her satır bir kez. Panel açıkken eski olay
    şeridi (`.fs-events`) gizlidir.
**Kalkış penceresi**: hedef irtifa + GÖKTUNGU kalkış kontrol listesi (6 zorunlu madde, "Hepsini onayla"); eksik madde varsa gönderilmez. Kopter/VTOL/
helikopter: hub `takeoff{alt_rel_m, kontrol:[{sira, anahtar, soru, grup, cevap, zorunlu, kaynak}]}` → sunucu `drone_takeoff_checks` kaydı + kalkış
akışı ("Kontrol listesi onaylandı (kayıt #k), takeoff a m" konsol satırı). Sabit kanat (§13 fırlatma düzeneği: tekerlekli/rampa/araç): simülatör
yolu `cmdSim('takeoff', {alt})` (rampa kızağı / pickup / pist koşusu sim'de yürür; onay satırı konsola yazılır).
**Veri/komut yolu — tek yol**: telemetri (PFD/karolar/rozetler) simülatörün `/ws/drone/sim` tele'sinden (`ops.update(t)`, 50 Hz; karolar 10 Hz,
PFD rAF). Hub durumu/konsol/komut sonuçları için panel KENDİ `/ws/drone/live` soketini açar (`{t:'watch', sim_id}` → hello [`me.can_command`,
`bridges[].drones` ilk durum] / status [mission_count, mission_seq, wp_dist, prearm] / console / bridge / res; ping 10 sn, üstel yeniden bağlanma,
4403 kalıcı). Komutlar `{t:'cmd', rid, bridge_id: -(9000+N), sysid: 1, name, params}` → `res{rid, ok, result|error}`; zaman aşımı hepgo_ws.js ile
aynı (mission_upload/start 65 sn, bileşik 35 sn, diğer 12 sn); hata → konsol + toast. Simülatöre özgü iki komut sim WS/REST yolundan gider:
`reset` ve sabit kanat `takeoff` (düzenek). Kayıt (replay) ve sahte (`?mock=1`) kiplerinde hub yoktur (`hub:false`): İŞLEMLER kartı yok, DURUM/MOD/
KOMUT karoları pasif; PFD/telemetri/konsol çalışır.
**Davranış.** Alt çubuk **Panel** düğmesi / **P** → kart gizli (sade görünüm: eski `.fs-hud` + `.fs-cmds` + olay şeridi); tercih localStorage
`fs.ops.on`. Gimbal kamerası (3, `fpv`) ve FPV (2, `pilot`): `.fs-fpv` → kart gizli; gimbal kamerasında askeri HUD (H), FPV'de OSD (O) kalır (§22). Kart başlık şeridinden sürüklenir (`fs.panel.col` {x, y, r};
yeniden boyutlanmada sağ kenara göre uygulanır), bölüm katlama `fs.panel.fold` (İŞLEMLER varsayılan katlı), küçült `fs.panel.min`;
**Yerleşimi sıfırla** hepsini siler. Sanal kumanda (`.rc-on`): kart kısalır (çubukların üstünde kalır). Alt çubuk sarınca `--fs-bar-h`
ResizeObserver ile güncellenir. ÇARPIŞMA bandı kartın üstünde (z 9). Tuşlar (1–4, H, P, WASD/ok) sayfanın kendi dinleyicilerinde; form alanı
odaklıyken yok sayılır.
**Tam ekran (⛶).** Kullanıcı: "tam ekrandayken mesaj pencereleri arkada kalıyor, mesela takeoff yüksekliği görünmüyor" — neden: tam ekran
`.fs-stage`'e uygulanıyordu; ui.js `modal()`/`toast()`, mod menüsü ve ses menüsü gibi body'ye eklenen öğeler tam ekran ÖĞESİNİN DIŞINDA kalır ve
tarayıcı onları çizmez. Çözüm: tam ekran **belgeye** uygulanır (`document.documentElement.requestFullscreen()`; flightsim.js); `fullscreenchange`
(ve düğme `then`) → `body.fs-full` + `.fs-stage.fs-full`: app.css `body.fs-full` HEPGO üst başlığı/alt barı gizler (app.js `immersive`
kalıbıyla aynı), `main#view.ops-view` ekrana sabitlenir; kalkış penceresi, ARM onayı, mod menüsü, bildirimler ve ses menüsü sahnenin üstünde görünür
(modal z 7000). Escape / ⛶ ile çıkınca sınıflar kalkar, düzen eski hâline döner.
**Dosyalar.** `static/js/modules/flightsim_panel.js` (tek kart; PFD/hub/komut yolu değişmedi); `flightsim.js` (import, `createOpsPanel(stage, …)`,
`addEvent(text, sev, at, tag)` → `ops.log`, `updateHud → ops.update`, `setState/setGcs/setRoute/setLaunchPhase/setFpv`, dispose; tam ekran
belgeye + `fs-full`); `static/css/app.css` (`.fs-pn*` GÖKTUNGU dron kartı kuralları, `body.fs-full`); i18n 6 dil (`i18n.en.extra2/de/fr/es/ru/ar.js`).
Arka uç değişmedi. Kaynak tasarım: `static/ops/css/stil.css` (`.dron-kart*`, `.dk-*`), `static/ops/css/hepgo.css`.

**Testler.** `tests/test_flightsim.py hub_testleri` (hub kaydı, `/live`, `watch{sim_id}`, status, arm, set_mode, kalkış akışı, mission_upload →
route, AUTO, mission_cancel, rtl, arm_check, reboot reddi, montaj yetkisi, kapanış) değişmeden yeşil. Tarayıcı doğrulaması (Playwright, SwiftShader,
sahte kip; `/tmp/flsim/p2/p1_panel.py`): TEK kart (`.fs-pn-kart` 1 adet; eski `.fs-pn-card/.fs-pn-col/.fs-pn-con` yok), sağ üstte 400 px, zemin
rgba(11,14,17,.94), 6 px köşe, başlık zemini #141a21, gövde Consolas/mono, bölümler [pfd, tiles, ops(katlı), con], 8 karo, konsol kart içinde; beyaz
piksel oranı açık tema %4,8 (sahne), koyu tema %0,13; fare ile döndürme boş alanda çalışır, kart üstünde pointerdown tuvale ulaşmaz; tam ekran:
kodda yalnız `document.documentElement.requestFullscreen` (sahneye değil), ⛶ → `document.fullscreenElement` = HTML, `body.fs-full` +
`.fs-stage.fs-full` (headless shell `fullscreenchange` olayı üretmez, çıkış tamamlanmaz → düzen CSS sınıfıyla doğrulandı): sahne 0,0 × görünüm
alanı, üst başlık gizli; kalkış penceresi (irtifa alanı + kontrol listesi), ARM penceresi, mod menüsü (8 mod), bildirim sahnenin ÜSTÜNDE
(`elementFromPoint` modal/menü/toast içinde; modal-back body'de, z 7000); PFD başlığından katlama (588 → 407 px) ve geri; İŞLEMLER düğmesi → bölüm
açılır, kart 613 px (max-height sınırı), gövde kaydırılır; küçült → 44 px yalnız başlık, geri büyüt; UÇUŞA HAZIR rozeti → ARM penceresi → ARMED ·
UÇUŞTA; MOD karosu → GUIDED; KOMUT karosu → kalkış penceresi → 25 m → tırmanış 23,8 m, konsol satırları kart içinde ("Kontrol listesi onaylandı
(kayıt #2), takeoff 25 m … TAKEOFF komutu iletildi"); başlıktan sürükleme → `fs.panel.col` → Yerleşimi sıfırla; dar 1000×700 (kart 340 px, alan
içinde), mobil 600×800 (kart = alan − 24 px); koyu tema. Görüntüler `/tmp/flsim/p2/shots/p1-*.png`.

**Sınırlar / açık kalanlar.** 3B sahnede yere tıklayarak hedef seçme yok (Hedefe git koordinatla; `flightsim3d` yer kesişimi eklenince bağlanır).
Kayıttan oynatma kareleri hub'a verilmez (komut kartı yok). Mission Planner'dan (UDP) yüklenen görevler 3B rotaya yansımaz (yalnız hub
`mission_upload`). GÖKTUNGU'nun ARM CHECK raporu/parametre düzenleyici/Bağlantı Yöneticisi panelde yok (hub `arm_check`/`param_*` uçları hazır).
Dar görünümde (<1100 px, 700 px yükseklik) sütun kaydırılır (başlık sabit). Kalkış kontrol listesi maddeleri sabittir (GÖKTUNGU'nun
kalkis_kontrol.js listesi değil; aynı kayıt tablosu).

## 15. CAYSIM masaüstü istemcisi (`app/caysim.py`, `app/routers/caysim.py`; sözleşme **docs/caysim-api.md**)
CAYSIM, Unreal Engine 5 + Cesium for Unreal ile yüksek gerçekçilikli görselleştirme istemcisidir (ayrı depo `goktalay/caysim`); **kendi fiziğini
çalıştırmaz** — SITL, Mission Planner köprüsü, komutlar ve 50 Hz telemetri HEPGO'da kalır. İstemci, Dron Köprüsü kalıbındaki **istemci kodu**
(`<domain>/<key>`, tablo `drone_sim_clients`, anahtar `cameras.encrypt` ile şifreli, bir kez gösterilir) ile `Authorization: Bearer <key>` kullanarak
`/api/caysim/v1` (hello/marka/merkezler/tipler/modeller/dünya/arazi vekili/loglar/oturumlar/cmd/mavlink) ve `/ws/caysim/v1/sessions/{id}`
(web WS ile aynı `hello/tele/event/state/end/res`; `cmd/rc/ping`) uçlarına bağlanır. Oturum açma (`routers/flightsim.oturum_ac`) ve WS döngüsü
(`ws_dongu`) web ile ortaktır; istemcinin açtığı oturum `session.client:{id,name}` taşır ve sihirbazdaki açık oturum listesinde **CAYSIM** rozetiyle
görünür. Yönetim: sihirbaz sayfasındaki "CAYSIM istemcileri" kartı (`static/js/modules/flightsim_clients.js`; `GET/POST /api/drone/sim/clients`,
`PUT`, `POST /{id}/rekey`, `DELETE`; `GET` anahtar döndürmez). Güvenlik: sabit-zamanlı anahtar karşılaştırma, IP başına 10 başarısız/dk (429 / 4429),
yalnız aktif istemci, CORS yok (OPTIONS 204). Testler `tests/test_caysim.py`. Alan adları, birimler ve Unreal (ESU, Y ters) dönüşüm notları belgede.

## 16. Motor sesi (`static/js/modules/flightsim_audio.js`; Web Audio API, tamamen sentezlenmiş — ses dosyası yok)
- **Tipe göre ses modeli** (`AUDIO_MODELS`, SITL tipi; görsel model sesi değiştirmez): **multirotor/hexarotor** 4/6 motor, her motor hafif farklı
  oranlı (`MOTOR_RATIOS`) testere dalga + 2× kare (ESC) + bant geçiren pervane uğultusu; pala geçiş frekansı 150 Hz (gaz 0) → 600 Hz (gaz 100), batarya < %30'da
  %4'e kadar düşer; disarm = sessiz. **helikopter** ana rotor "wop-wop" (20–30 Hz LFO ile genlik modülasyonlu alçak gürültü + harmonik), türbin ıslığı
  900–1500 Hz, kuyruk rotoru (×5,5). **sabit_kanat** (delta/caymaz aynı) benzinli tek silindirli iki zamanlı: devir 1500 (rölanti) → 7500 d/dk,
  ateşleme f = devir/60 × silindir (25 → 125 Hz) testere + alt harmonik kare + egzoz gürültüsü (lowpass gazla açılır) + 2 pala pervane; armed + gaz 0 = rölanti,
  disarm sessiz.
- **ARM sesi (kullanıcı isteği: "ARM olduğunda motor çalışıp ses çıksın")** — `spinStep(cur, armed, dt, kind)` 0…1 motor durumu, kazanç ve devir bununla
  çarpılır: ARM geçişinde devir 0 → rölanti rampası **kopter 0,6 sn** (ESC başlatma; rölanti kazancı `COPTER_IDLE` 0,3 — belirgin vızıltı, pala geçişi
  150 Hz × 0,35 → 150 Hz), **helikopter 3 sn** rotor sarmalı (LFO 3 → 20 Hz, türbin ile), **sabit kanat 0,8 sn marş** ("cranking": testere 80–120 Hz +
  bant geçiren gürültü `starter/starterN`, ateşleme rölantinin altından çıkar) sonra rölanti; **DISARM'da 1 sn'de sönme** (`SPIN_DOWN`). Canlıda ve kayıtta
  aynı yol (replay kareleri `armed` taşır; ARM anında ses başlar); Bitir/dispose → duruş. Önceki davranış: kazanç ARM'da anında 0,22'ye sıçrıyor, DISARM'da
  anında kesiliyordu (rampa yok). Test: `node tests/test_flightsim_audio.mjs` ("ARM rampası", "ARM sesi grafikte"). **vtol** kopter + uçak, karışım hava hızına göre (5 → 20 m/s). **Kalkış yöntemi** (§13): rampa `launch` → pnömatik "pşşt" (bant
  geçiren gürültü patlaması), `released` → kızak çarpması (80 Hz vuruş); araç → pickup V8 motoru (800 → 4500 d/dk yer hızıyla), `released` → fren
  gıcırtısı, rölantiye düşer ve susar. Aşama `sim.launchPhase` getter'ından okunur (flightsim.js'e ek bağlantı yok).
- **Kaynak**: `tele.throttle`, `armed`, `airspeed/groundspeed` (rüzgâr/uğultu), `rs/ps/ys` (±%1,5 titreme), `batt_pct`. Devir gazı üstel yumuşatmayla izler
  (`smoothFollow`: yukarı τ 0,35 sn, aşağı 0,7 sn — motor ataleti). Kayıttan oynatma kareleri aynı biçim → çalışır; hız ≥ 2× → susar.
- **Uzaysal**: tek `PannerNode` (equalpower, inverse, `refDistance` 15 m, rolloff 1): dinleyici = 3B kamera (`sim.cameraPose()`: konum + ileri/üst, ENU),
  kaynak = dron (`sim.position()`); takip/serbest/yer kameralarında 1/r. **FPV** → kaynak dinleyicide (kokpit), lowpass 900 Hz boğukluk + hızla artan rüzgâr
  gürültüsü (40 m/s'de tam). Doppler küçük (radyal hız, ±%5 sınır). **Çarpışma** (crash bandı görünür → `getCrashed`): kısa patlama + motor grubu 0,08 sn'de
  durur; "Sıfırla" ile döner.
- **Aç/kapa**: alt çubukta 🔊/🔇 (`.fs-audio-btn`, başlık "Motor sesi aç/kapa (M)"), **M** tuşu (yazı alanı odaklı değilken), ▾ ile açılır menü (ses düzeyi 0–100,
  sağ tık da açar). Tercih `localStorage` `fs.audio.on` (varsayılan AÇIK) ve `fs.audio.vol` (70; algısal eğri ^1,6). Tarayıcı autoplay kuralı: AudioContext ilk
  kullanıcı etkileşiminde (pointerdown/keydown) kurulur ve `resume` edilir; o ana dek sessiz, düğmede turuncu nokta ("etkileşim bekleniyor") ve menüde ipucu.
  Sekme gizlenince susar (`visibilitychange`), sayfadan çıkınca kapanır (`dispose`: dinleyiciler kalkar, bağlam `close`).
- **Performans**: tek AudioContext; osilatör/gürültü düğümleri bir kez kurulur (yalnız tipin grubu; vtol ikisi); her güncelleme (≤ 25 Hz) yalnız
  `setTargetAtTime`; sessizken parametre sürülmez. CSP: Web Audio ağ isteği yapmaz (`media-src` gerekmez).
- **Testler**: `node tests/test_flightsim_audio.mjs` — saf katman (tip→devir→frekans, yumuşatma, mesafe kazancı, FPV, Doppler, tercihler) + sahte Web Audio
  düğümleriyle grafik (tek bağlam/düğüm sabitliği, kopter/heli/uçak/vtol parametreleri, uzaysal, aç/kapa, 2× sessiz, kilit, rampa/araç/çarpışma efektleri,
  dispose, ≤ 25 Hz işleme). Tarayıcı (Playwright, sahte kip): düğme/M/menü/localStorage/FPV ve sayfadan çıkış; konsol hatası yok.

## 17. Ekran kaydı → Şirketten Haberler (`app/flightsim_rec.py`, `static/js/modules/flightsim_record.js`)
Kullanıcı isteği: "Başlat dediğim andan itibaren ekranı video olarak kaydetsin, ses ile birlikte; Bitir dediğim anda videoyu Şirketten Haberler bölümüne,
kullanıcı kimse onun kullanıcısıyla paylaşım olarak yüklesin." + "Başlat dediğim anda otomatik tam ekran açılsın."
- **Otomatik tam ekran**: sihirbazda **Başlat / Oynat** tıklaması içinde (kullanıcı etkinleştirmesi) `document.documentElement.requestFullscreen()`
  (`enterFullscreen`; mevcut §14 kalıbı: belgeye, sahneye değil; oturum ekranı açılınca `onFullChange` → `body.fs-full` + `.fs-stage.fs-full`). Tarayıcı
  reddederse sessizce geçilir. Oturum açılamazsa (400/409/503) tam ekrandan çıkılır. **Bitir**'de `exitFullscreen` (kayıt yüklendikten sonra, oturum kapanmadan önce).
- **Kayıt kaynağı — karar**: (a) **`getDisplayMedia`** tercih: gerçek ekran (harekât paneli / HUD / pencereler dahil), sistem sesi seçeneği; izin kutusu Başlat
  tıklamasında **bir kez** (tam ekran isteğiyle aynı etkinleştirme içinde, oturum açılmadan önce; `preferCurrentTab`, `selfBrowserSurface:'include'`,
  `systemAudio:'include'`). Alınan akış `stashStream` ile oturum ekranına taşınır. (b) **Yedek**: kullanıcı reddederse / API yoksa (headless, eski tarayıcı) →
  3B tuval + askeri HUD tuvali birleşik 720p tuvale çizilir (`sim.addFrameHook`: render SONRASI aynı rAF turunda `drawImage`; `preserveDrawingBuffer`
  gerekmez) → `canvas.captureStream(30)`; bilgi verilir ("panel kayda girmez"). html2canvas benzeri DOM birleşimi uygulanmadı (pahalı; (a) zaten DOM'u kapsar).
  Kullanıcı ekran paylaşımını tarayıcı çubuğundan durdurursa kayıt orada kesilir (olay şeridinde uyarı), Bitir'de kısmi video paylaşılır.
- **Ses**: motor sesi (§16) `audio.captureStream()` — master çıkışına bağlı `MediaStreamAudioDestinationNode` (kullanıcının duyduğu gibi; ses kapalıysa sessiz) +
  ekran paylaşımı sistem sesi varsa o (o zaman motor kaynağı eklenmez: aynı ses iki kez girmez) + isteğe bağlı mikrofon (`fs.rec.mic`, varsayılan kapalı;
  localStorage) — ayrı bir karışım `AudioContext`inde tek ses parçasına birleşir.
- **Biçim**: `MediaRecorder` mime sırası `video/webm;codecs=vp9,opus` → vp8,opus → h264,opus → webm → `video/mp4` (Safari); 1280×720 hedef, 2,5 Mb/s video,
  128 kb/s ses; `timeslice` 10 sn. Rozet: üst şeritte kırmızı **● KAYIT 03:21** (`.fs-rec-badge`; yükleme bekleyen varsa ↑), alt çubukta **⏺ Kayıt** anahtarı
  (`.fs-rec-btn`, **R** tuşu). Tercih `fs.rec.on` (varsayılan AÇIK; kapalıysa Başlat'ta izin istenmez, kayıt yapılmaz). Oturum sırasında kapatma → pencere:
  "Durdur ve paylaş" / "Sil" / Vazgeç; açma → tıklama içinde ekran paylaşımı izni, yoksa yedek.
- **Akıtma** (parçalar bitmeden değil, oturum boyunca): `POST /api/drone/sim/sessions/{id}/rec/start {mime}` → `{rec_id, max_bytes, chunk_max, ext}`;
  `PUT /api/drone/sim/rec/{rec_id}/chunk?seq=N` (ham gövde, ≤ 8 MB; istemci büyük parçaları diler) sunucu `DATA_DIR/sim_rec/<rec_id>.<ext>`'e ekler —
  sıralı `seq`: tekrar (= son) yok sayılır (idempotent), atlama 409 ("beklenen N"), parça sınırı 413; `PUT …/thumb` (PNG ≤ 2 MB; istemci 2. sn'de 3B/birleşik
  tuvalden 320 px kare); `POST …/finish {duration_s, mime, text?}` → dosya `UPLOAD_DIR/feed/<token>.<ext>`'e (+ `.png` küçük resim) taşınır, `feed_posts`'a
  **oturum sahibi** adına (`kind USER`, `media [{type:'video', path, thumb}]`) paylaşım açılır, `_announce` ile anlık/push bildirimi; dönüş
  `{post_id, path, thumb, text, link:'#/home'}`. Metin: istemci kendi dilinde `text` gönderir ("Uçuş Simülatörü kaydı · <tip> · <merkez> · <yöntem> · <süre> ·
  <tarih>", `tr()`); boşsa sunucu Türkçe üretir (`flightsim_rec.metin`). `DELETE …/rec/{rec_id}` siler. Ağ hatasında parça 5 kez üstel beklemeyle yinelenir.
- **Boyut sınırı**: `SIM_REC_MAX_MB` (varsayılan 1024, en çok 2048); aşan parça 413 → kayıt sunucuda `full`, istemci kaydı durdurur ve uyarır; şimdiye kadarki
  kısım Bitir'de paylaşılır. İndirme yedeği için parçalar tarayıcı belleğinde ≤ 600 MB tutulur (yükleme hatasında "Dosyayı indir").
- **Yarım kayıt**: sayfa kapanır / ağ kopar / Bitir'siz çıkılırsa meta (`<rec_id>.json`) ve veri sunucuda **24 saat** kalır (`temizle`: start/pending çağrılarında).
  `GET /api/drone/sim/rec/pending` → kullanıcının (sahip ya da başlatan) oturumu kapanmış, bitmemiş kayıtları; sihirbazda **"Yarım kayıt (n)"** kutusu
  (`pendingCard`): **Paylaş** (finish) / **Sil**. Geri okuyla çıkışta kuyruktaki parçalar arka planda akıtılmaya devam eder (aynı belge; fetch sürer).
- **Yetki**: `require_module('drone.sim')` yöntemden yazma izni ister (POST/PUT/DELETE) → kayıt uçları yazma izni; ayrıca modül `basla` oturum sahibi ya da yazma
  izni, parça/bitir/sil başlatan ya da sahip ya da yazma izni denetler. Paylaşım **yalnız oturum sahibi** adına (sahip silinmişse bitiren adına). Sahte kipte
  (`?mock=1`) ve salt okuyan izleyicide kayıtçı kurulmaz.
- **Bitir akışı** (`flightsim.js endSession`): onay → `rec.finishWithDialog()` (son parça → kuyruk boşalır: "Kayıt yükleniyor… %" çubuğu → finish →
  "✓ Şirketten Haberler'e paylaşıldı" + **Paylaşımı aç** (`#/home`) / hata → "Kayıt yüklenemedi" + **Dosyayı indir**) → tam ekrandan çık → `DELETE /sessions/{id}`.
- **Testler**: `tests/test_flightsim.py rec_testleri` — start (403 salt okuyan, 404 oturum), chunk (sıra/tekrar/atlama 409/kötü kimlik 404/parça 413), thumb 415,
  pending (oturum açıkken boş; kapanınca listede; başkası görmez), finish → `feed_posts` (sahip, media video+thumb, dosyalar taşındı, meta silindi, medya sunulur),
  yazma izinli başka kullanıcı → yine sahip adına + istemci metni + mp4 uzantısı, boyut sınırı (413 → full → 409), boş kayıt 400, silme, 24 saat temizliği.
  Playwright (headless shell, `getDisplayMedia` yok → yedek yol): Başlat → rozet "KAYIT 00:1x" → sunucuda parça → Bitir → yükleme → paylaşıldı → `#/home`'da
  video kartı; ffmpeg ile webm süresi/ses parçası/5. sn kare parlaklığı; kayıt kapalı → rozet yok; Bitir'siz çıkış → yarım kayıt kutusu → Sil.
- **Sınırlar**: headless'ta gerçek ekran paylaşımı sınanamaz (kullanıcı tarayıcısında kutu çıkar); yedek yolda DOM paneli kayda girmez; Safari'de mp4 ve
  `getDisplayMedia` davranışı tarayıcıya bağlı; `fullscreenchange` olayı bazı gömülü tarayıcılarda gelmez (sınıf oturum ekranı açılınca da uygulanır).
- **Kayıt seçenekleri (kullanıcı isteği: "kayıt işini seçenekli yapalım: girişte sorsun")** — sihirbazda Başlat'ın üstünde **Kayıt** kutusu (`recOptionsBox`,
  `flightsim_record.js`), tercihler localStorage: ☐ **Ekran kaydı al (video)** (`fs.rec.on`, varsayılan açık; kapalıysa Başlat'ta ekran paylaşımı izni
  istenmez, alt çubuk anahtarı aynı tercihi okur) › girintili ☐ **Şirketten Haberler'de paylaş** (`fs.rec.share`, varsayılan açık; yalnız video açıkken) ·
  ☐ **Uçuş logunu (.bin) kaydet** (`fs.rec.bin`, varsayılan açık; yalnız canlı SITL — §19). Paylaşım kapalıysa Bitir'de `finish {share:false}` → dosya
  `DATA_DIR/sim_rec`'te **saklanır** (`state: 'kept'`, `SIM_REC_KEEP_DAYS` = 30 gün), pencere "✓ Video sunucuda saklandı" + **Videoyu indir** + "Şirketten
  Haberler'de paylaş"; sihirbazda **"Kayıtlarım (n)"** kutusu (`myRecsCard`): İndir / Paylaş / Sil. Uçlar: `POST /rec/{id}/finish {share:false}` →
  `{kept:true, rec_id, size, text, file}`; `GET /rec/mine` → `{items:[{id, text, size, seconds, kept_at, type, center, mode, ext, mime, thumb, file_name}],
  keep_days}`; `GET /rec/{id}/file` (attachment; sahip/başlatan/yazma izni); `POST /rec/{id}/share` → finish (saklanan metin/süre). `pending` saklananları
  listelemez; `temizle` saklananlara 24 saat yerine KEEP_S uygular.

## 18. (ayrılmış) Görev çizimi / çarpışma / rapor — ayrı dal (flightsim_mission.js, flightsim_report.js)

## 19. Uçuş logu (.bin) kaydı — SITL DataFlash → Uçuş Logları (`app/flightsim_bin.py`, `drone_sitl.parm_metni`)
Kullanıcı isteği: "Simülasyon sonunda tüm veri, aynı dronun içinde kaydettiğimiz .bin dosyası formatında uçuşu kaydetsin, bu da seçenekli olsun."
- **Seçenek:** sihirbaz Kayıt kutusu ☐ "Uçuş logunu (.bin) kaydet" → `POST /sessions {rec:{bin:true}}` (yalnız `mode:'sitl'`); `session.rec = {bin, bin_log}`.
- **SITL parametreleri** (`varsayilan.parm`, `parm_metni(sysid, log_bin)`): `bin:true` → `LOG_BACKEND_TYPE 1` (dosya), `LOG_DISARMED 0` (yalnız armed
  süre yazılır), `LOG_FILE_DSRMROT 1` (disarm'da dosya kapanır/döner); kapalıyken `LOG_BACKEND_TYPE 0` (GÖKTUNGU: tek sanal dron 43 GB .BIN üretmişti).
  Dosyalar SITL çalışma dizininde `DATA_DIR/sitl_calisma/<kimlik>/logs/*.BIN`; `baslat` önceki artıkları siler (`bin_temizle`).
- **Kapanış (`SimSession._temizle`):** `_bin_kapat` — armed ise zorla disarm (MAV_CMD_COMPONENT_ARM_DISARM 0/21196) + 1,5 sn bekleme (dosya kapanır) →
  TCP/UDP kapanır → SITL durur → `_bin_kaydet`: `drone_sitl.bin_dosyalari` (büyükten küçüğe) → `flightsim_bin.kaydet`: en büyük .BIN
  `UPLOAD_DIR/flightlogs/<rastgele>.bin`'e taşınır, `flight_logs` satırı (file_name **`SIM-<oturum>-<YYYYMMDD-HHMM>.bin`**, aircraft "Simülatör · <tip>
  [· <dron kodu>]", pilot = oturum sahibi, location = merkez adı, note "Uçuş Simülatörü oturumu #N (SITL DataFlash)", task yok), iz kaydı,
  `flight_analysis.start` (analiz kuyruğu) → TAMAM olunca Araçlar › Uçuş Logu Analizi ve sihirbazın Kayıttan oynat listesinde görünür; kalan .BIN'ler
  silinir. `< 1 KB` (yalnız başlık, armed süre yok) → kaydedilmez (null). Sonuç `DELETE /sessions/{id}` yanıtında `bin: {log_id, file_name, size} |
  {error} | null` ve olay şeridinde; ön yüz Bitir'de toast ("Uçuş logu kaydedildi: … — analiz bitince …"). Sunucu kapanışında (`sunucu_kapaniyor`) ve
  boşta/süre kapanışlarında da kaydedilir. `kapat()` bekleme süresi 30 sn.
- **Kaynak (Gerçek / Simülasyon):** `flight_logs.origin` = `SIM` | `REAL` (NULL: dosya okunamadı). Bu kayıt yolu `SIM` yazar; elle yükleme
  (`/api/tools/flight-logs`, saha uçuşu) ve dron köprüsü dosyanın başındaki SITL işaretine bakar (`dataflash.sim_isareti`: ArduPilot yalnız SITL
  derlemesinde `SIM_*` parametrelerini yazar). Mevcut satırlar uygulama açılışında doldurulur (`db.flight_log_origin_doldur`, idempotent, yalnız
  NULL'lar): `drone_sim_runs.bin_log_id` bağı ya da bu yolun izi (ad `SIM-<n>-<tarih>.bin` + aircraft "Simülatör · …"/not) → SIM; kalanlar dosya
  başı işaretiyle. Araçlar › Uçuş Logu Analizi tablosunda **Kaynak** sütunu (uçak simgeli yeşil Gerçek / ekran simgeli mor Simülasyon; `static/js/modules/flightlog_origin.js`), süzgeç (Tüm kaynaklar / Gerçek uçuş /
  Simülasyon) ve başlığa tıklayarak sıralama (Log dosyası, Kaynak, Uçuş tarihi, Havada, Yükleyen); eski "Kaynak" (Araçlar / Saha görevi) sütunu
  **Bağlam** oldu. Simülatör sihirbazının "Kayıttan oynat" listesinde her satırda kaynak rozeti, **Kaynak** süzgeci (Tümü / Gerçek / Simülasyon),
  sıralama (yeni/eski, uçuş süresi, boyut, kaynak, ad) ve "N gerçek · M simülasyon" sayacı; seçimler tercihte saklanır.
- **Boyut/disk:** `SIM_BIN_MAX_MB` (varsayılan 500) — aşan dosya kaydedilmez (`error`, uyarı) ve silinir; oturum süresi `SIM_MAX_MINUTES` (120) ve
  LOG_DISARMED 0 ile boyut sınırlı kalır (ArduCopter ≈ 1–2 MB/dk). Sahte kip (`HEPGO_SITL=0`): `MANAGER.sahte_bin_dosyalari` test kancası.
- **Doğrulama (DEV, gerçek SITL):** `/tmp/flsim/rp2/rp2_e2e.py` — bin:true oturum → arm + takeoff → Bitir → `SIM-…bin` Uçuş Logları'nda (analiz TAMAM)
  → Kayıttan oynat listesinde → gerçek arazi kipinde oynat → dünya yüklü (olay şeridi "Gerçek arazi · yükseklik …", atıf görünür).

## 20. Kalıcı parametreler — dron kaydı seçili oturumlar (`app/drone_params.py`; tablo `drone_sitl_params`; ayrıntı docs/dron-kopru-protokolu.md)
Kullanıcı isteği: "sanal dron ile yaptığımız uçuşlar esnasında, gerek sistemden gerekse Mission Planner üzerinde bir parametre değiştirdiğimizde
kalıcı olarak kaydetsin; aynı dronu tekrar kullandığımızda eski parametreler ile gelsin."
- Sihirbazda **dron kaydı** seçildiyse (`drone_id`) oturum `drone_params.Izleyici(drone_id)` taşır; `session.params = {tracked, loaded, saved}`
  (`to_dict`/hello). Dron kaydı seçilmemiş oturumda izleme yok (`tracked:false`).
- **Kayıt:** harekât paneli `param_set` (hub) → yankı → `hepgo`; Mission Planner PARAM_SET (UDP ham geçer, `_udp_geldi` → `gcs_bayt` niyet) →
  SITL PARAM_VALUE yankısı (`_isle` → `_param_value_gozlendi`) → `mp`; niyetsiz fark → `sitl`. Her kayıt olay şeridine düşer: "Parametre kalıcı
  kaydedildi: WP_RADIUS = 123 (Mission Planner)". Oturumun kendi yazdığı SIM_WIND_*/SIM_GPS1_*/TKOFF_*/RC/SERVO3 seti, akış hızları (MAVn_*/SRn_*)
  ve STAT_/LOG_/*_TOTAL/MAV_SYSID hariçtir (`haric_mi`).
- **Yükleme:** `_sitl_ac` → `_kayitli_oku` → `drone_sitl.YONETICI.baslat(..., ekstra_parm=…)` (varsayilan.parm sonu) → `_ilk_heartbeat` içinde
  `_kayitli_yaz` (PARAM_SET, kayıtlı ptype; oturum parametrelerinden ÖNCE → oturum ayarları son söz) → olay "N kayıtlı parametre yüklendi (D-0001)".
  `reset` aynı yolu izler. Sahte kip: `_sahte_hub_komut param_set` sahte yankı üretir; sahte SITL'den gelen baytlarda yalnız PARAM_VALUE aranır.
- **UI:** Dron Yönetimi › Dron Envanteri › sanal dron detayı "Kayıtlı parametreler (N)" kartı (drone.js; flightsim.js'e dokunulmadı).
- **Flaplar (yalnız `sabit_kanat`; `FLAP_PARAMLARI`):** ilk kalp atışında `SERVO5_FUNCTION 3`, `SERVO6_FUNCTION 3` (flap_auto), `TKOFF_FLAP_PCNT 50`,
  `LAND_FLAP_PERCNT 100` yazılır → ArduPlane kalkış/inişte flapları kendisi açar. Dron yapılandırması sayılır: kullanıcı MP/panelden değiştirirse
  kalıcı kaydedilir (`drone_params.HARIC_DEGIL` TKOFF_ ön ekini aşar) ve dronun kaydında olan ad oturum başlangıcında YAZILMAZ (`flap_parametreleri`).
  `tele.servo_fn` = SERVO1..8_FUNCTION (PARAM_VALUE'dan; None = bilinmiyor) — 3B model flap/aileron eşlemesi için.
- **Testler:** `tests/test_flightsim.py param_testleri` ve `tests/test_drone.py param_izleme_testleri` (§7). Gerçek SITL doğrulaması:
  `/tmp/flsim/pr/dogrula.py` — sabit kanat oturumu (dron kaydıyla) → pymavlink `udpout` (MP gibi) `PARAM_SET WP_RADIUS 123` → kayıt `mp`;
  hub `param_set RTL_RADIUS 777` → `hepgo`; kapat → yeniden aç → `params.loaded 2`, varsayilan.parm'da satırlar, `PARAM_REQUEST_READ` → 123 / 777;
  yükleme yankıları `updated_at` değiştirmez; dron sayfası ekran görüntüsü.

### 20.1 Donanım montaj parametreleri — `SERVOn_REVERSED` sanal uçakta aynen uygulanır (SITL yaması `SIM_SRV_REV`; `drone_params.montaj_mi`, `srv_rev_mask`, `sitl_kayitlari`; `drone_sitl.sanal_montaj_destegi`; `tools/sitl/`)
Kullanıcı bildirimi (Gökkubbe canlı, dron 5 CAYMAZ): "Caymaz parametrelerinde kanat servolarının yerleşimi dolayısıyla SERVO1_REVERSED=1,
SERVO2_REVERSED=0 kullanıyoruz; bu şekilde düzenlediğimizde uçak simülasyonda düzgün uçmuyor." Kesin karar: "Bizim uçağın SERVO1_REVERSED=1 iken,
SERVO2 normalken (0) düzgün uçması lazım" — sanal uçak gerçek uçağın servo **montajını** da taklit eder; ilk çözüm (SITL'e nötr 0 yazmak,
`sim_apply_servo_reverse` seçeneği) kullanıcı tarafından reddedildi ve KALDIRILDI.
- **Kök neden.** Gerçek uçakta `SERVOn_REVERSED` servo montaj yönünü düzeltir (servo ters takılıysa PWM ters çevrilir, yüzey doğru yöne gider).
  Stok ArduPilot SITL fiziği (`SIM_Plane`) servo PWM'ini doğrudan yüzey açısına çevirir — sanal montaj hep "düz" — bu yüzden REVERSED=1 sanal
  uçakta yüzeyi gerçekten ters çalıştırır: pozitif geri besleme → çırpınma/takla (ölçüm: 1/0 + maske 0 → 12. sn'de "SIM Hit ground").
- **Çözüm: HEPGO SITL yaması** (`tools/sitl/0001-sim-srv-rev.patch`, `tools/sitl/README.md`; ArduPilot `Plane-4.7.2` = fb773567 üstüne).
  Yeni SITL parametresi **`SIM_SRV_REV`** (int32 bit maskesi, bit n-1 = SERVOn ters monteli). `SIM_Aircraft::update_model` girişinde
  (`apply_servo_reverse_mask`) maskedeki kanalların PWM'i 1500 µs ekseninde yansıtılır (`pwm' = 3000 − pwm`; PWM 0 dokunulmaz) → ArduPlane'in
  REVERSED=1 ile ters çevirdiği sinyali sanal montaj geri çevirir; net yüzey hareketi gerçek uçakla aynı. Tüm modeller (plane, copter, quadplane,
  heli) kapsanır; maske 0 → eski davranış birebir. İkililer `/opt/hepgo/sitl/bin` (DEV; eski resmi ikililer `bin-4.7.2-orig/`), PROD
  `/opt/hepgo/caymazbuild/data/sitl`; `.sha256` + `.version` (`…+hepgo-sim-srv-rev`).
- **Sınıf:** `MONTAJ_DESENI` = `SERVO1..16_REVERSED` (`montaj_mi`, `montaj_kanal`). **`RCn_REVERSED` bilerek dışarıda:** RC girişleri kumanda
  tarafıdır; SITL'de sanal kumanda / Mission Planner joystick aynı gerçek kumanda yönüyle çalışmalı → olduğu gibi gider. `SERVOn_FUNCTION/MIN/MAX/TRIM`
  de montaj değildir.
- **Motor (ESC) kanalları.** ArduCopter motor çıkışını ham yazar (`AP_Motors::rc_write → SRV_Channels::set_output_pwm`; REVERSED **uygulanmaz**) →
  gerçek araçta etkisiz olan REVERSED fizikte ters çevrilse çok rotorlu düşerdi. `srv_rev_mask(rows, tip)`: kayıtlı `SERVOn_FUNCTION` motor kodu
  (33–40, 82–85, 120–139) ya da kayıt yokken araç tipinin varsayılan motor kanalı (`VARSAYILAN_MOTOR_KANALLARI`: multirotor/hexarotor 1–8, vtol 5–8;
  helikopterde yok — swash/kuyruk trimmed/scaled yazılır, REVERSED etkili) ise bit **konmaz**; `motor_skipped` listesi + bilgi olayı "motor (ESC)
  kanalında servo ters çevirme etkisizdir … bit konmadı". Uçak gazı (70) scaled → bit konur (gerçekle aynı).
- **Davranış (yamalı ikili; `drone_sitl.sanal_montaj_destegi(tip)` ikilide `\0SRV_REV\0` imzasını arar, önbellekli).**
  (1) Kayıt ve `.param` dışa aktarımı gerçek değeri taşır; export başına `#NOTE: … montaj parametresi — gerçek uçak değeri; sanal uçakta aynen
  uygulanır (SIM_SRV_REV)` yorum satırı. (2) Açılışta `sitl_kayitlari(rows, True, tip)`: satırlar **aynen** + sonuna `SIM_SRV_REV = srv_rev_mask`
  (0 dahil — eeprom'da kalan eski maske silinsin; INT32) → varsayilan.parm (`parm_satirlari`; SIM_SRV_REV hariç listesinde olsa da yazılır) + ilk
  kalp atışı `_kayitli_yaz` PARAM_SET. Bilgi olayı "SERVO1_REVERSED: sanal uçakta servo montajı da ters (SIM_SRV_REV = 1) — gerçek uçakla aynı
  davranış". `SIM_SRV_REV` kalıcı kayda **girmez** (`HARIC_ADLAR`; MP yazarsa da kaydedilmez). (3) Oturum **sırasında** MP/panelden SERVOn_REVERSED
  değişirse izleyici kaydeder ve `_montaj_degisti` → `srv_rev_mask(yukle(), tip)` → `srv_rev_yaz(mask)` (SimSession `_srv_rev_yaz` / SitlDrone
  `_srv_rev_yaz`: PARAM_SET SIM_SRV_REV) → sanal montaj anında güncellenir; bilgi olayı "SERVO3_REVERSED = 1: sanal uçakta servo montajı güncellendi
  (SIM_SRV_REV = 5)". (4) Oturum özeti `params`: `virtual_mount`, `srv_rev_mask` (yazılan), `srv_rev_sitl` (SITL PARAM_VALUE'dan gözlenen; eski
  ikilide None), `mount_reversed`, `mount_neutral`, `motor_skipped`. (5) Dron detay "Kayıtlı parametreler" kartı: yeşil rozet **"montaj (sanal uçakta
  aynen uygulanır)"**; liste yanıtı `mount {virtual_mount, srv_rev_mask, motor_skipped, badge, note}`.
- **Eski (resmi) ikili — geri düşüş.** `sanal_montaj_destegi` False → `sitl_kayitlari(rows, False)`: montaj satırları **0**'a çekilir, SIM_SRV_REV
  yazılmaz; sarı olay "SERVO1_REVERSED: **SITL ikilisi sanal montaj desteklemiyor; servo ters çevirme nötr uygulandı** (SITL'e 0 yazıldı; kayıt ve
  .param dışa aktarımı gerçek değeri korur)"; oturum içi REVERSED≠0 kaydında `Izleyici.montaj_uyarisi` (bu oturumda SITL'de etkili, yeni oturumda 0);
  kartta turuncu rozet "montaj (simülasyonda nötr)" + `mount.note`. İkili yoksa `indir` resmi sürümü çeker → bu yol.
- **CAYMAZ elevon kurulumu SITL'de.** (Güncel: §13.1 kontrol düzeni.) Düz `plane` / `plane-catapult` modeli kanal 1'i aileron, kanal 2'yi elevator
  okur → 4/19 o modelde doğru kurulumdur; 77/78 yalnız `plane-elevon` modelinde doğru uçar. §13.1 ile Elevon düzeni seçilince SITL **`plane-elevon`**
  ile açılır ve ArduPlane'in kendi elevon kurulumu (SERVO1 78 / SERVO2 77 / REVERSED 1/1 / MIXING_GAIN 0,5) yazılır; dronun **kalıcı kaydında**
  SERVO1/2_FUNCTION varsa (PROD dron 5: 4/19) kalıcı değer öncelikli, son ek etkin fonksiyonlardan türetilir → düz `plane`, eski davranış aynen.
- **Ölçüm (gerçek SITL, yamalı arduplane/arducopter 4.7.2, `tools/sitl/dogrula_srv_rev.py`, tekerlekli kalkış 50 m, CAYMAZ FUNCTION 4/19):**
  (a) SERVO1_REVERSED=1 / SERVO2=0, SIM_SRV_REV=1 → 60 sn kararlı (takla yok, irtifa 50 m tutuldu); (b) 0/0, SIM_SRV_REV=0 → kararlı (eski davranış);
  (c) 1/0 ama MP ile SIM_SRV_REV=0 zorlandı (stok davranış) → takla + "SIM Hit ground" (kontrol); (d) copter SERVO1_REVERSED=1 → motor kanalı, bit yok →
  kalkış kararlı; (d2) copter'da MP ile SIM_SRV_REV=1 zorlandı → motor1 fizikte ters → kararsız (yama copter'da da etkili). Sayısal özetler commit
  mesajında. (e) resmi ikili (`bin-4.7.2-orig`) ile 1/0 → nötr geri düşüş, kararlı, sarı uyarı.
- **Testler:** `param_testleri` montaj bloğu — montaj_mi/montaj_kanal/srv_rev_mask (tip ve motor dışlaması), haric_mi(SIM_SRV_REV), `sitl_kayitlari`
  True/False bilgi sözlükleri, `montaj_olayi` metinleri, export NOTE, `sanal_montaj_destegi` monkeypatch ile iki yol (reset → parm/PARAM_SET içerikleri,
  INT32 tipi, olaylar, `params` alanları, SITL yankısı → `srv_rev_sitl`), oturum içi MP değişikliği → anında SIM_SRV_REV PARAM_SET, izleyici geri çağrısı.

## 18. Görev çizimi, iniş dairesi, çarpışma kaydı ve özet rapor (`app/flightsim_mission.py`, `static/js/modules/flightsim_mission.js`, `static/js/modules/flightsim_report.js`; tablo `drone_sim_events`)
Kullanıcı isteği (birebir): "1. Dron üzerine Mission Planner üzerinden ya da kendi sistemimizden bir görev yüklersek haritaya şık bir şekilde çizsin.
2. Görevin son adımında daire içinde H çizsin, dairenin çapını girişte parametre olarak girelim. 3. Topoğrafyadan ya da bir durumdan dolayı dron
çarpışırsa bunu tespit edip çarpışma koordinatını kaydedelim. 4. Görev yüklü ise son koordinatı da kaydetsin. 5. Simülasyon sonunda bir özet rapor
sunalım. 6. Temel uçuş bilgileri ile görev bitiş noktası ile çarpışma noktası arasındaki mesafeyi/sapmayı metre olarak kırmızı gösterelim. 7. Bu
sayede güvenlik önlemi alabilelim." Ek istek: "Simülasyon esnasında Mission Planner üzerinden bir görev yüklenirse anlık olarak bildirim gelsin ve
haritaya çizsin."

**Görev izleme (sunucu; `GorevIzleyici`, her `SimSession.gorev`).** Görev iki kaynaktan gelir:
- **HEPGO paneli**: `hub_komut mission_upload` → `SimSession._rota_ayarla(points, source='hepgo', total=uploaded)`.
- **Mission Planner (UDP)**: MP'nin yüklemesi köprüden ham geçer; sunucu SITL→MP akışını ayrıştırırken **SITL'in MP'ye yolladığı `MISSION_ACK`**'ı
  (hedef bileşen bizim 191 değil) yakalar → 0,4 sn sonra görevi SITL'den **kendisi indirir** (`MavKomut.mission_download`, bekleyici kalıbı) →
  `_rota_ayarla(points, source='mp', total=count)`. `MISSION_CLEAR_ALL` da ACK verir → indirme boş → çizim kalkar. Yedek tetik: `MISSION_CURRENT.total`
  son yükleme/indirme sonrası ilk gözlenen değerden (referans) farklılaşırsa indirilir (ACK kaçmışsa); ArduPilot sayımı bizim `uploaded` ile birebir
  olmayabildiğinden mutlak sayı karşılaştırılmaz. Transfer sürerken (`MISSION_REQUEST(_INT)` görüldükten sonra 3 sn; hub görev komutları `transfer()`)
  ve indirmeden sonra 3 sn bu tetik bastırılır (ArduPilot yükleme sırasında total'ı yeni sayıya çeker → eski kod çoklu indirme/toast üretiyordu).
  Ölçüm (gerçek SITL arduplane, pymavlink udpout "Mission Planner gibi" 3 WP): MISSION_ACK → 3B çizim **0,51 s**, temizleme → çizim kalktı 0,95 s; tek
  indirme, tek toast, tek olay satırı.
- Rota noktalarının `seq` değeri **SITL seq**'idir (`rota_noktalari(items, offset)`: HEPGO yüklemesinde ev/hız öğesi ofseti, indirilen listede ev atlandığı
  için 1) → `MISSION_CURRENT.seq` ile birebir eşleşir; `MISSION_CURRENT.seq` değişimi `{t:'mission_cur', seq, total}` yayınıdır (3B'de aktif bacak).
- Yayın: `{t:'route', points:[{seq, cmd, lat, lon, alt, alt_rel, frame}], source:'hepgo'|'mp', home, current, end, landing_circle_m}`; `session.route` +
  `session.mission` (aynı ek alanlar; hello/to_dict). Olay şeridi: "Mission Planner'dan görev yüklendi: N nokta" / "… görev temizlendi" / "HEPGO panelinden
  görev yüklendi: N nokta" (`event`, severity 6) → ön yüzde MP kaynaklıysa **toast** (3 sn içinde aynı metin tekrar etmez) + olay şeridi + panel konsolu.
- **Görev bitiş noktası** (`gorev_bitis`): son konumlu öğe LAND (21) → o konum (AGL 0), RTL (20) → ev, aksi son WP. `mission_end` olayı olarak kaydedilir;
  görev değişince aynı satır güncellenir (satır kimliği oturum belleğinde).

**3B çizim (`flightsim_mission.js createMissionLayer`; `flightsim3d.js setMission/setMissionCurrent`, `setRoute` geriye uyum).** Yarı saydam **tüp** bacaklar
(gelecek amber, geçilen soluk yeşil, aktif parlak beyaz-sarı + hale, daha kalın) + merkez çizgisi; her bacağın yere projeksiyonu **kesikli gölge çizgisi**
(24 alt parça, arazi profilini izler) + her WP'den zemine dikey çubuk; WP küreleri + **billboard etiket** (`seq · alt m`, `sizeAttenuation:false` → uzaktan
okunur; aktif sarı kenar, geçilen yeşil); ikonlar: TAKEOFF koni ↑ (yeşil), LAND ters koni (mor), RTL oktahedron (mor; son WP'den eve mor kesikli hat),
LOITER halka. Ev: yeşil disk + "H". İrtifa: frame 3/6 göreli (ev zemini = ev konumunun yerel arazi yüksekliği), frame 0/5 MSL → ev irtifasıyla göreliye.
`setWorld` sonrası yeniden çizilir (yüzey değişti). Teşhis: `__fsSim.mission`, `__fsSim.missionObjects`.

**İniş dairesi.** `world.landing_circle_m` (10–200, varsayılan 30; `_WORLD_SINIR`, sihirbaz kaydırıcısı "İniş dairesi çapı") → görevin bitiş noktasında yere oturan
daire: CanvasTexture düzlem (beyaz+sarı **kesikli halka**, iç çember, ortada kalın **H**) + ince kenar torusu; 4 örnek noktadan eğime oturur (`terrainHeight`),
su seviyesinin altına inmez; gece (`world.time = night`) daha parlak doku + `PointLight`. Uçak/kopter ayrımı yok.

**Çarpışma kaydı — SITL fiziği asıl kaynak (sahte çarpışma düzeltmesi).** Kullanıcı geri bildirimi: "Bazen çarpışma olmamasına rağmen çarpışma oldu
gibi hata veriyor" (yerde ve "bayağı yüksekte de"). PROD kanıtı (oturum 9, Bedesten 1500 m, sabit kanat MANUAL): 17 `crash` satırının 16'sı
`reason: sitl`, hepsi **"SIM Hit ground at 0,2–4,3 m/s"**, 18:49–18:51 arasında dakikada 8 kayıt; alt_rel −2…+15 m (SITL'in SRTM arazisi ev
irtifasından farklı: uçak eğimli arazide yerde). Oturum 5/7/8'de aynı metinler (1–2,5 m/s). Kök nedenler:
1. `"SIM Hit ground at %f m/s"` ArduPilot **SITL fizik motorunun** (SIM_Aircraft::update_dynamics) havadan yere **her** temasta yazdığı bilgi satırıdır;
   sayı **düşey hız**tır (velocity_ef.z). Yerde taksi zıplaması, iniş, disarm sonrası sürüklenme, yerde titreşim → 1 sn'den uzun aralıkla tekrarlanır.
   Eski kod her "hit ground" metnini çarpışma sayıyordu; 5 sn tekilleştirme aralığı dışındaki her mesaj yeni kayıt + ÇARPIŞMA bandı (WS `crash`) oluyordu.
2. 3B `checkCollision` (Google 3B / gerçek arazi) tek karede `z < h + 0,3` ile tetikleniyor ve **zorla disarm** ediyordu; Google karo yüzeyi ile SITL'in
   SRTM arazisi birkaç m farklı olabilir (oturum 9 id 84: `terrain`, 33 m/s, SITL alt_rel −4,6 m — SITL'de yerde değil), karo yüklenmesi/komşu hücre/0
   değerleri, uzak halka geçişi, düzenek/yerde kilit anları sahte tetikleyebiliyordu (oturum 8: TAKEOFF koşusunda `terrain` 21,6 m/s).
3. ArduPlane yazılımsal tespiti ("Crash: Disarming", "Crash detected"; `CRASH_DETECT`, `is_flying` sezgisi) fiziksel temas değildir; eski eşleme çarpışma
   sayıyordu (PROD'da görülmedi; CRASH_DETECT varsayılanı 0).

Yeni kural (`app/flightsim_mission.py`):
- `statustext_sinifla(txt)` → `('sitl_hit', düşey hız)` ("hit ground at X"), `('autopilot_detect', None)` ("crash" içeren; "crash check"/"crash_dump"
  hariç), `(None, None)`.
- `sitl_temas(vz)`: 3B arazi **adayı** bekliyorsa teyit → `crash` sebep `terrain` (hız = 3B yer hızı ∨ vz, `sitl_vz`, `sitl_text`); son çarpışma
  CARPISMA_TEKIL_S (**30 sn**) içindeyse metin ilk kayda eklenir (yeni satır yok); aksi hâlde yalnız **vz ≥ SITL_HIT_HIZ_MIN (3 m/s)** ve araç
  yerde-durağan değilken (`alt_rel < 1 m ∧ yer hızı < 3 m/s` değil) `crash` sebep **`sitl_hit`**. Diğer temaslar (taksi, normal iniş 0,5–1,5 m/s,
  yerde zıplama) **yok sayılır**. Her çarpışma kaydı `SimSession.zorla_disarm()` (sahte: kinematik sıfırlanır; SITL: 400/21196) + kırmızı olay.
- `otopilot_tespit`: çarpışma DEĞİL → sarı olay "Otopilot çarpışma tespiti (ArduPlane yazılımsal): … — çarpışma kaydı yapılmadı" (severity 4),
  `drone_sim_events` **`type='warning'`** (`reason: autopilot_detect`), WS `{t:'warn', kind:'autopilot_detect', text}`; 30 sn tekil. Rapor
  `autopilot_detect_count`; `crash_count`'a girmez. Ayrıca sabit kanatta oturum başında **`CRASH_DETECT 0`** (PLANE_YER_PARAMLARI; oturum parametresi →
  dron kaydına kalıcı yazılmaz).
- `ucboyut_bildirim(kind, speed)` (`cmd crash`): **bina/su kesin** (SITL bina bilmez) ve sahte kipte her tür kesin → kayıt + disarm, yanıt
  `{crash: true}`; gerçek SITL'de **arazi ADAYDIR**: `ADAY_TEYIT_S` (3 sn) içinde SITL "Hit ground" gelirse `terrain` kaydı, gelmezse düşer + sarı olay
  "3B arazi teması (… m/s) SITL fiziğiyle doğrulanmadı — çarpışma sayılmadı"; yanıt `{crash: false, pending: true}`. Disarm yalnız kesin kayıtta.
- `reason` değerleri: `terrain` | `water` | `building` | `sitl_hit` | `manual` (eski satırlarda `sitl`); `warning` satırında `autopilot_detect`.

3B algısı (`flightsim3d.js checkCollision(now, dt)`): **histerezis** — COLL_HOLD_S 0,4 sn boyunca sürekli `z < h + 0,3` (bina 0,1 sn); hız >
COLL_SPEED_MIN 2 m/s; devre dışı: disarm, düzenek taşıyor (idle/armed/launch), `released` sönümü (`rel.on`), yerde kilit (`gLock.on`), ARM'dan sonraki
COLL_ARM_GRACE_MS 3 sn; arazi yüksekliği bir karede COLL_JUMP_M 20 m'den fazla değişirse kare atlanır (karo yüklenmesi / uzak halka geçişi); Google
3B'de dronun altında yüklü karo yoksa (`g3d.hasSurface` → `height()` komşu hücre/0 verir) arazi/su örneği yok sayılır; gerçek arazide ana kare dışı
(uzak halka, kaba) arazi/su denetlenmez; bina AABB her yerde. Tespitten sonra COLL_COOLDOWN_MS 4 sn yeniden denetim yok (sunucu adayı düşürürse
yeniden tespit edilebilir). `onCollision({kind, z, x, y, alt, dz, speed})`. Teşhis: `__fsSim.collisionState()` → `{z, h, dz, below, kind, skipped,
checks, noTile, grounded, rel, rig}` (e2e her 250 ms örnekler).

Ön yüz (`flightsim.js`): **ÇARPIŞMA bandı yalnız sunucunun kesin `crash` çerçevesiyle** açılır (`showCrash(reason, speed)`: "ÇARPIŞMA · <neden> · <hız>
m/s · Sıfırla…"; neden `CRASH_KIND`: arazi/su/bina/**SITL yer teması**). 3B tespiti `cmd crash {kind, speed, dz}` gönderir; arazi için bilgi satırı
"3B arazi teması algılandı (… m/s) — SITL fizik teyidi bekleniyor". `warn` çerçevesi → sarı olay satırı, bant yok. Mock kipte 3B tespiti doğrudan bant.
Salt okuyan izleyicinin 3B algısı sunucuya gitmez. Rapor `REASON.sitl_hit` = "SITL yer teması (fizik)".

**SITL arazi verisi bulgusu.** ArduPilot SITL fiziği araziyi (SRTM `terrain/*.DAT`) yalnız veri varsa kullanır; veriyi SITL internetten indirmez, **GCS**
(Mission Planner/MAVProxy terrain modülü) `TERRAIN_REQUEST`→`TERRAIN_DATA` ile yollar. PROD'da MP bağlı oturumlar sonrası `sitl_calisma/*/terrain/N39E03x.DAT`
var (oturum 9'da alt_rel −2…+15 m ile "hit ground": SITL arazi üstünde); DEV e2e'de (MP yok) `TERRAIN_REPORT.terrain_height = 0`, fizik **düz zemin**
(ev irtifası) → Google 3B tepeleri uçağın 70–130 m üstünde kalır; eski kodda bu "yüksekte çarpışma" + zorla disarm demekti, yeni kodda aday teyitsiz
düşer. Sunucu `TERRAIN_REPORT` → `tele.terrain_agl` (yalnız `loaded > 0 ∧ terrain_height ≠ 0`) + `tele.terrain_h` (SITL'in bulunduğu noktadaki arazi
yüksekliği, m MSL); 3B'de `|(z − h) − terrain_agl| > COLL_AGL_DISAGREE_M (30 m)` ise örnek kaba karodandır → o karede arazi/su denetimi yok.

**SITL arazi sunumu — sunucu GCS gibi `TERRAIN_DATA` yollar (`SimSession._terrain_istek`, `sim_terrain.terrain_bloklari`).** Gerçek arazi ve Google 3B
kiplerinde (`TERRAIN_KIPLER`; prosedürelde kapalı — yükseklik istemcide üretilir, sunucu bilmez; sahte kipte `HEPGO_SITL=0` etkisiz; `SIM_TERRAIN_SERVE=0`
tamamen kapatır) `_isle` SITL'in `TERRAIN_REQUEST`'ini (blok SW köşesi lat/lon 1e7, `grid_spacing`, 56 bit `mask`) alır → iş parçacığında
(`run_in_executor`; karo indirme bloklayabilir) `sim_terrain.terrain_bloklari` → olay döngüsünde her istenen parça için `TERRAIN_DATA(lat, lon, spacing,
gridbit, data[16] int16 m)`; aynı anda tek iş, iş sürerken gelen **son** istek sıraya alınır (SITL yanıtlanmayan parçaları zaten yeniden ister). Yükseklik
kaynağı hatasında parça atlanır (SITL yeniden ister), sayaç + 60 sn'de en çok bir sarı olay. Yükseklik = ev irtifasıyla **aynı terrarium z13 karoları**
(bilineer, EGM96 MSL ≈ ArduPilot SRTM MSL; birim tutarlı) → SITL zemini (`home_alt + h(loc) − h(home)`) ev noktasında `center.alt`'a oturur. Oturum
başında (ilk kalp atışı) `TERRAIN_PARAMLARI` = **TERRAIN_ENABLE 1, TERRAIN_SPACING 100** (oturum parametresi → `drone_params.oturum_adlari` hariç listesi;
kalıcı kayda girmez); **TERRAIN_FOLLOW'a dokunulmaz** (0; kullanıcı MP'den açabilir; kalkış/iniş/RTL davranışı değişmez). Mission Planner bağlıyken MP de
aynı isteklere `TERRAIN_DATA` yollar: SITL son geleni yazar; MP'nin SRTM'i ile terrarium farkı 1–3 m (kabul). SITL arazi önbelleği `sitl_calisma/<kimlik>/terrain/N39E033.DAT`
(1°×1° başına seyrek dosya; görünür 2,7 MB, disk 24 KB) **oturumlar arası kalır** → aynı bölgede yeni oturum istek atmaz (`drone_sitl.terrain_temizle`:
toplam disk kullanımı `SITL_TERRAIN_DAT_MB` (64) aşılırsa en eski erişilenler silinir). Oturum özeti `GET /sessions/{id}` → `terrain: {serve, requests, blocks,
skipped, errors, last_ts, report:{lat, lon, spacing, terrain_height, current_height, pending, loaded, ts}}` (son `TERRAIN_REPORT`). Olay: "Arazi verisi:
SITL'in arazi istekleri gerçek yükseklik verisinden (terrarium z13) yanıtlanıyor…".
**Ölçüm** (gerçek SITL arduplane, gerçek arazi kipi, Bedesten alt'sız merkez → ev 741,8 m MSL; `/tmp/flsim/ts/e2e_ts.py 0|1`, 3B'li `e2e_ts3b.py`):
- ÖNCE (`SIM_TERRAIN_SERVE=0`): `TERRAIN_REPORT loaded 0 / pending 672`, `terrain_height 0`, `.DAT` 0 bayt; GUIDED 315°, 3,2 km, 80 m AGL → uçak 976 m'lik
  tepenin **191,5 m içinden** geçti (alt_msl − terrarium en düşük −191,5 m), temas/çarpışma yok, 200 sn sonunda hâlâ armed.
- SONRA (`=1`): ilk kalp atışından 4,7 sn sonra `loaded 56`, 28 sn'de **`loaded 504 / pending 0`** (14 istek, 560 parça, 0 atlanan); SITL `terrain_height`
  741,7 ↔ terrarium bilineer 741,5 (**fark 0,2 m**); uçuşta SITL `terrain_agl` ↔ `alt_msl − terrarium` farkı ≤ 2 m. Aynı GUIDED uçuş: 37 sn'de yamaçta
  **"SIM Hit ground at 5,67 m/s"** → `crash sitl_hit` 12,65 m/s, alt_msl **831,0 m ↔ terrarium 831,9 m**, alt_rel 89 m (ev üstünde — gerçek yamaç).
- SONRA + 3B açık (Playwright, gerçek arazi): 3B `z − h` ile SITL AGL **medyan fark 1,7 m**; 3B arazi adayı → SITL teyidi → `crash terrain` 11,2 m/s,
  ÇARPIŞMA bandı "Arazi ile temas · 11.2 m/s"; alt_msl 830,7 ↔ terrarium 831–834 m; sayfa hatası 0 (`/tmp/flsim/ts/ts-3b-carpma.png`).
- Önbellek: dolu `.DAT` ile yeni oturum → **0 istek**, 504 blok diskten 14 sn'de (SITL'in kendi disk IO temposu).
Not: `tele.terrain_h` HUD'da gösterilmiyor (isteğe bağlı küçük "arazi AGL/yükseklik" göstergesi `flightsim.js` tarafında yapılabilir). Testler
`tests/test_flightsim.py terrain_birim_testleri` (konum_ofset, bilineer, 56 parça/gridbit/4×4 düzeni, maske, int16 kırpma, kaynak hatası → atlama) ve
`arazi_sunum_testleri` (sahte kipte serve False; `_isle(TERRAIN_REQUEST)` → `TERRAIN_DATA` lat/lon/spacing yankı + gridbit sırası; sıraya alma; kaynak
hatası → skipped + sarı olay; `TERRAIN_REPORT` → tele/özet; prosedürelde kapalı; TERRAIN_* hariç listesinde, TERRAIN_FOLLOW değil).

**Ölçüm** (gerçek SITL arduplane + Google 3B gerçek karolar, Playwright swiftshader, `/tmp/flsim/cr/e2e_cr.py`, port 8796, Bedesten 1500 m, tekerlekli):
- ÖNCE (PROD oturum 9): 18:49:26–18:51:16 arasında **17 crash satırı** (16 `sitl` "SIM Hit ground at 0,2–4,3 m/s", 1 `terrain` 33 m/s), her biri kırmızı bant.
- SONRA A) MANUAL armed yerde 60 sn + gaz %30 60 sn: crash **0**, uyarı 0, bant yok; 3B z−h: yerde −0,1…−2,6 m, `checks` 11 (hız kapısı), kaba kök karo
  örnekleri (`noTile` 18, ilk 10 sn'de h −651 m) atlandı.
- B) TAKEOFF 120 m + CRUISE 110 sn (~2,3 km): crash **0**, bant yok; 3B 225 denetim, 6 atlanan kare, 22 kare `z < h+0,3` (Google tepesi, SITL düz zemin) →
  2 arazi adayı → SITL teyidi yok → düştü (sarı olay ×2, sayaçlı), disarm YOK (eski kod: crash + disarm).
- C) MANUAL tam gaz burun aşağı: **1 crash** `sitl_hit` 18,5 m/s (SITL "Hit ground at 11,19 m/s" düşey), zorla disarm, bant "ÇARPIŞMA · SITL yer teması ·
  18.5 m/s"; sonraki 8 sn'de sürüklenme temasları yeni satır üretmedi (30 sn tekil). Sayfa hatası 0. Testler `tests/test_flightsim.py carpisma_siniflama_testleri`: sınıflandırma; PROD metinleri yerde → 0 kayıt; normal iniş → 0; sert
temas havada → `sitl_hit` + disarm; 30 sn tekil; ArduPlane tespiti → `warning` + sarı olay; 3B arazi adayı teyitli → `terrain` tek kayıt; teyitsiz →
düşer + sarı olay; bina kesin; sahte kip arazi kesin; REST `cmd crash building` → `{crash:true}`; summary `crash_count`/`autopilot_detect_count`.

**Özet rapor.** `GET /sessions/{id}/summary` → sunucu 1 Hz izden (`_dongu` → `tik()`; ≤ 7400 örnek) hesaplar: `{session:{type, type_name, model, drone, center,
world_mode, world_time, launch, landing_circle_m, wind}, flight:{start_ts, end_ts, duration_s, air_s (armed ∧ AGL>1), max_agl, max_msl, max_speed, dist_m
(armed, <500 m sıçramalar hariç), arm_count, modes, last_mode, batt{first/last v,pct}, last_pos, home}, mission:{source, count, completed (seq < en yüksek
MISSION_CURRENT), end, points, current, total}|null, crash, crash_count, deviation:{from:'crash'|'last', dist_m, dz_m, in_circle (≤ çap/2)}|null,
safety:{code: crash_deviation|crash_no_mission|in_circle|out_of_circle|no_mission, dist_m, reason}, safety_note (TR), track:[[t,lat,lon,alt_rel]…≤600]}`;
`summary` olayı olarak `drone_sim_events`'e yazılır (oturum başına tek satır, güncellenir; dönen `id`). Oturum **her nedenle** kapanırken de yazılır
(`_temizle` → `kapanis()`; Bitir'de üretilmiş rapor varsa yalnız `ended_at/end_reason/duration_s` güncellenir — kullanıcının gördüğü rapor korunur).
`GET /reports?limit=20&mine=0|1` → `{items:[{id, session_id, owner, created_at, type_name, center, duration_s, max_agl, dist_m, crash, deviation_m, in_circle,
mission, safety_code}]}`; `GET /reports/{id}` → rapor; `POST /reports/{id}/share {text?}` → Şirketten Haberler metin paylaşımı (rapor sahibi adına; yazma izni;
`text` istemcinin dilinde, boşsa `rapor_metni` TR) + `_announce`.
Ön yüz (`flightsim_report.js`): Bitir akışı = onay → kayıt yüklemesi (§17) → **rapor modalı** (tam ekranda; belge tam ekran olduğu için görünür) → tam ekrandan
çık → `DELETE`. Modal: özet karoları (süre, havada, en yüksek AGL/hız, mesafe, ARM) · temel uçuş bilgileri · görev bilgisi · **ÇARPIŞMA** bölümü (kırmızı:
koordinat, irtifa, zaman, hız, mod, neden, hedef WP) · **SAPMA** kartı (çarpışma ↔ bitiş noktası: büyük KIRMIZI yazı, yatay m + yükseklik farkı; çarpışma
yoksa son konum ↔ bitiş noktası: iniş dairesi içinde yeşil, dışında turuncu) · güvenlik notu (`safety.code` ile kendi dilinde) · **2B mini harita** (canvas: ızgara,
rota + WP numaraları, dron izi mavi, ev H yeşil, bitiş H beyaz, iniş dairesi kesikli, çarpışma kırmızı X + bitişe kesikli hat, ölçek çubuğu, kuzey oku).
Düğmeler: "Raporu Şirketten Haberler'e ekle" (yazma izni; pencere açık kalır, düğme "✓ Paylaşıldı"), "PDF / Yazdır" (`window.print`; `body.fs-rp-printing` +
`@media print` yalnız pencereyi basar), "Devam". Sihirbazda **"Son simülasyon raporları"** kutusu (`reportsCard`, `GET /reports`) → aynı modal. Sahte kipte
(`?mock=1`) rapor tarayıcıda basit üretilir; geçmiş yok. CSS: `.fs-rp*` (app.css sonu).

**Tablo** `drone_sim_events(id, session_id, owner_id, type 'crash'|'warning'|'mission_end'|'summary', lat, lon, alt_msl, alt_rel, t, speed, mode, detail JSON, created_at)`
(`CREATE IF NOT EXISTS`). `session_id` sunucu yeniden başlayınca 1'den başlar; güncellemeler satır kimliğiyle yapılır (çakışma yok).

**İzleyici kuyruğu**: tele dışı (`route`, `crash`, `event`, `state`, `mission_cur`, …) çerçeveler dolu kuyrukta en eski **tele**'nin yerini alır (`_kuyruga(onemli)`)
— yavaş izleyicide tekil olaylar düşmez (eski davranışta 50 Hz tele crash çerçevesini düşürüyordu).

**Testler** (`tests/test_flightsim.py gorev_rapor_testleri`): birim (`mesafe_m`, `gorev_bitis`, `rota_noktalari offset`), `landing_circle_m` doğrulama/meta, MP
yüklemesi algılama (sahte kipte `_isle(MISSION_ACK hedef 190)` → route `source:'mp'` + olay; bize gelen ACK tetiklemez), `MISSION_CURRENT` → `mission_cur`,
`mission_end` satırı + güncelleme, kalkış → `cmd crash` → `crash` çerçevesi + satır (sebep, hedef WP, sapma), SITL metni tekilleştirme, summary (istatistikler,
sapma = haversine, güvenlik notu, tek satır), reports listesi/tek rapor/404, yetki (salt okuyan görür, paylaşamaz 403; `mine=1`), paylaşım → `feed_posts` (sahip
adına, TR metin / istemci metni), kapanışta `ended_at`, çarpışmasız görev (son konum ↔ bitiş, iniş dairesi içinde). E2E (`/tmp/flsim/ms/e2e_ms.py`, gerçek SITL
arduplane, port 8789): HEPGO rotası → 3B görüntü (`ms-01`, iniş dairesi `ms-02`), pymavlink udpout MP yüklemesi → gecikme 0,51 s + toast (`ms-03`), temizleme,
kalkış → crash → Bitir → rapor modalı (`ms-05/06`, kırmızı sapma 457,5 m) → paylaşım → sihirbaz rapor listesi (`ms-07/08`).

**Sınırlar / açık**: MP yüklemesi algısı SITL'in ACK'ına dayanır (MP'nin paketleri ayrıştırılmaz; UDP→TCP ham geçer); ArduPilot MISSION_CURRENT.total farkı yedek
tetiği 3 sn sakinlik ister. Çarpışma koordinatı telemetrinin son karesidir (50 Hz; ≤ 20 ms). Sahte kipte (HEPGO_SITL=0) MISSION_CURRENT.total tetiği kapalıdır.
PDF üretimi tarayıcı yazdırma diyaloğuyla (sunucu PDF yok). Rapor paylaşımı metindir (video kaydına yorum olarak eklenmez).

## 21. Simülasyon Kayıtları — tablo, "Yeni Simülasyon Başlat" penceresi, her şeyin kaydı (`app/flightsim_runs.py`, `static/js/modules/flightsim_runs.js`; tablo `drone_sim_runs`)
Kullanıcı isteği (birebir): "Yapılan uçuşların kayıtları Simülasyon altında tablo şeklinde olsun; tarihe göre, konuma göre ve benzeri seçim
yapabilelim; Yeni Simülasyon düğmesi olsun; bu simülasyon ekranındaki seçenekler ayrı bir box ile açılsın, header'ında 'Yeni Simülasyon Başlat'
desin, footer'da 'Başlat' ve 'İptal et' düğmesi olsun; başlattığında standart simülasyon başlasın; simülasyon bitince kaydetsin ama sadece
simülasyonu değil her şeyi kaydetsin: bin dosyasını, son parametreleri, içine script yüklediysek onu da. Sonra kayıtları oynatabilelim; ama sadece
master kullanıcısı script ve parametreleri download edebilsin, bu düğmeler yalnız master kullanıcısına görünsün."

**Tablo `drone_sim_runs`** (`CREATE IF NOT EXISTS`, app/db.py): `id, session_id, session_kimlik (KIMLIK_TABANI+id; replay NULL), owner_id/owner_name,
drone_id/drone_code, type, model_id/model_name, center_id/center_name, lat, lon, world JSON, launch JSON, started_at, ended_at, duration_s,
mode 'sitl'|'replay', result 'tamam'|'carpisma'|'hata', end_reason, crash_count, summary_event_id → drone_sim_events(summary), bin_log_id →
flight_logs (§19), source_log_id → flight_logs (kayıttan oynatma kaynağı), video_rec_id (flightsim_rec kimliği), video_post_id (feed_posts),
video_path (UPLOAD_DIR göreli feed/…), params_path/params_count (DATA_DIR göreli `sim_runs/<id>/params.param`), scripts_path/scripts_count
(`sim_runs/<id>/scripts.zip`), created_at`; indeks started_at / owner_id / center_id.

**Kapanışta kayıt (`SimSession._temizle`, `ReplaySession._temizle` → `flightsim_runs.kaydet`, iş parçacığı).** Sıra: (1) `_param_dokumu` —
gerçek SITL'de, ilk kalp atışı alınmışsa ve bilinen liste `param_count`'un %95'inden azsa `PARAM_REQUEST_LIST` gönderilir, PARAM_VALUE'lar
`param_son`a dolar (`_param_value_gozlendi`; en çok `SIM_PARAM_DUMP_S` = 6 sn, %95 gelince erken); Mission Planner açılışta listeyi çekmişse
istenmez. (2) `_bin_kapat` → özet (`gorev.kapanis`, summary satırı) → TCP/UDP → SITL durur → `_bin_kaydet` (§19). (3) `kaydet(s)`: satır INSERT
(ilişkiler: `gorev.summary_id`, `bin_sonuc.log_id`, `s.video` ya da `flightsim_rec.oturum_kaydi(sid)` → bitirilmemiş/saklanan kaydın rec_id'si),
**SON PARAMETRELER** = `param_son` ∪ kalıcı izleyici tabanı (`drone_params.Izleyici.taban`) ∪ sahte kip `_sahte_params` → Mission Planner
`.param` biçimi (`drone_params.param_metni`, `#NOTE: HEPGO Uçuş Simülatörü oturum #N · tip · merkez · tarih · N parametre`), **SCRIPTLER** =
SITL çalışma dizini (`drone_sitl.calisma_dizini(kimlik)`; SITL kökü = cwd: `terrain/`, `logs/` orada) altındaki `scripts/` (ArduPilot Lua
`SCR_ENABLE`) ve `APM/scripts/` (Mission Planner MAVFTP'nin gösterdiği yol; SITL posix dosya sistemi cwd'ye göre çözer) içeriği varsa
`scripts.zip` (≤ 50 MB); UPDATE params/scripts yolları. `result`: `sitl.error` → hata, `crash_count>0` → carpisma, aksi tamam. Olay şeridi
"Simülasyon kaydedildi: #id · N parametre [· M script]"; WS `end` çerçevesine `run {id, params_count, scripts_count}` eklenir. Kayıttan oynatma
oturumu da kaydedilir (mode replay, source_log_id, parametre/script yok). Sunucu kapanışı / boşta / süre kapanışları da kaydeder.
**Video bağı:** `POST /rec/{id}/finish` (share true/false) ve `/share` → `flightsim_runs.video_bagla(sid, rec_id, post_id, path)`: oturum açıksa
`s.video` (kapanışta satıra), kapanmışsa aynı rec_id ya da aynı session_id'li son satır güncellenir (yarım kayıt sonradan paylaşımı dahil).

**REST (`/api/drone/sim/runs`; okuma `drone.sim`):** `GET /runs?from&to&center_id&type&owner_id&result&mode&q&sort&page` → `{items, total,
page, pages, per_page:25, facets:{centers[{id,name,n}], owners[{id,name,n}], types[]}}`; `sort` ∈ started_at | owner | type | center |
duration_s | result | mode (başında `-` azalan; ikincil anahtar id aynı yön); `q` merkez/kullanıcı/model/dron kodu/log adı LIKE ya da oturum no;
`from/to` `YYYY-MM-DD` (started_at günü); geçersiz sayı 400. Satır alanları + `bin_status/bin_file_name`, `source_file_name`, `has_params/
has_scripts/has_video/has_summary`, `play_log_id` (bin_log_id analizi TAMAM, yoksa source_log_id TAMAM), `can_delete`. `GET /runs/{id}`;
`GET /runs/{id}/params` ve `GET /runs/{id}/scripts` **yalnız MASTER** (`user.master`; aksi 403; `Content-Disposition` SIM-<oturum>-<tarih>-
params.param / scripts.zip); `GET /runs/{id}/bin` (.bin dosyası, drone.sim okuma izniyle; uçuş logu yetkisi gerekmez); `GET /runs/{id}/video[?dl=1]`
(paylaşılmışsa `UPLOAD_DIR/feed/…`, değilse `sim_rec/<rec>.webm`); `DELETE /runs/{id}` (sahip ya da yazma izni; satır + `sim_runs/<id>/`
silinir — özet, .bin, video kendi yerlerinde kalır; iz kaydı). Dosya yolları yalnız satır kimliğinden türetilir ve DB'deki göreli yol beklenenle
karşılaştırılır (yol gezinmesi yok).

**Ön yüz (`flightsim.js renderWizard` → sayfa; `wizardModal` → pencere; `flightsim_runs.js runsTable`).** Geri bildirim (birebir): "alt alta üç yapı
var, bunları bir tab ile gösterelim: Simülasyon Kayıtları / Açık Oturumlar / CAYSIM İstemcileri; çok fazla filtre: tarihi 'son 1 gün, 1 hafta, 1 ay'
yapalım; Tarih ile 'Detaylı' düğmesi aynı kapsülde, Detaylı'ya tıklayınca küçük bir box açılsın; her satırda Oynat/Rapor/Video bir kapsülde; sadece
master'da kırmızı 'Download' düğmesi, tıklayınca combobox neyi indirecekse listelesin." Sayfa: üst satır (sınır notu + **"+ Yeni Simülasyon"** düğmesi;
yazma izni yoksa pasif) · **üç sekme** (`simTabBar`, HEPGO `.seg.seg-tabs` kalıbı + sayaç rozeti `.fs-tab-n`; 0 iken gizli): **Simülasyon Kayıtları**
(varsayılan) · **Açık Oturumlar** (rozet = `GET /sessions` sayısı; devam et / bitir listesi; §17 yarım kayıt şeridi `pendingCard` listenin altında —
ikisi de "bitmemiş iş") · **CAYSIM İstemcileri** (rozet = istemci sayısı, `clientsCard({ onCount })`). Seçim `#/drone/sim?tab=runs|open|clients` ile
gelir ya da `localStorage caymaz.fs.tab` ile hatırlanır (hash'e yazılmaz; yeniden çizim yok). Pencere kapanışında açık oturum rozeti yenilenir.
Sahte kipte (`?mock=1`) kayıt ve istemci sekmeleri "Sahte veri kipinde … yok." notu gösterir.
Tablo (HEPGO `.table-wrap > table.table` kalıbı): tarih/saat (+ `#oturum · kapanış nedeni`), kullanıcı, dron tipi/model (kayıt rozeti), merkez/konum
(+ koordinat), dünya kipi, kalkış yöntemi (sabit kanat), süre, sonuç rozeti (**ÇARPIŞMA** kırmızı `×n` / Tamam yeşil / Hata turuncu; çarpışma
satırı `row-alert`), ekler (SVG simgeler: video, .bin [analiz sürüyorsa sarı], parametre, script — emoji yok), işlemler: **kapsül** (`.pill-group
.fs-runs-rowpill`) **Oynat** (`play_log_id` ∧ yazma izni; pasifse soluk; pencereyi kayıttan oynat kipinde o log seçili açar → dünya seçimi → Başlat →
mevcut replay akışı) · **Rapor** (`showReport`; `has_summary` yoksa pasif) · **Video** (yalnız `has_video`; modal `<video>` + İndir); **yalnız
`ctx.user.master`**: kırmızı **Download ▾** düğmesi → açılır menü (`popover`, body'ye fixed; dışarı tıklama / Escape / kaydırma kapatır): "Uçuş logu
(.bin)" · "Parametreler (.param)" · "Script arşivi (.zip)" · "Video (.webm)" · "Rapor (yazdır)" (`<a download>`; olmayanlar pasif). Master olmayanda
Download YOK — .bin indirme yalnız Download menüsünde; master olmayan .bin'i Oynat ile kullanır. **Sil** küçük simge, kapsülün sağında (`can_delete`;
onay). ≤1560 px'te Download + Sil kapsülün altına sağa hizalı sarar. **Filtre çubuğu** tek satır: kapsül **Son 1 gün · 1 hafta (varsayılan) · 1 ay ·
Tümü** (`from` = bugün − n gün, `to` boş) + aynı kapsülde **Detaylı** (aktif ayrıntı filtresi sayısı rozeti) → açılır kutu (`.fs-runs-detail-box`):
tarih aralığı (iki `date`; dolu ise dönem `custom`, kapsülde seçili dönem yok), merkez / tip / kullanıcı (facet listeleri, sayılarla), sonuç, kaynak
(canlı / kayıt), arama; **Uygula** (değerler o ana kadar bekler) / **Temizle** (hepsi sıfır, 1 hafta). Sağda kayıt sayısı; boş durumda "Tüm kayıtları
göster". Sıralama sütun başlığından (▲/▼); 25'li sayfalama (‹ Sayfa p / n ›).
**Pencere** (`ui.js modal`, `wide` + `.fs-wizard-modal` 1240 px, sabit yükseklik): başlık **"Yeni Simülasyon Başlat"**, gövde = **adım adım sihirbaz** (§6:
kip + ilerleme şeridi, adım içeriği, 3B önizleme); altbilgi **"İptal et"** · gerekçe · **‹ Geri** / **İleri ›** / son adımda **"▶ Başlat"** (primary; kayıt kipinde
"▶ Oynat"). Başlat → mevcut akış: tam ekran + ekran paylaşımı izni → `POST /sessions` →
pencere gizlenir, **hazırlık kartı** (§8 `prepareSession`, sihirbaz önizlemesiyle dünya ön yüklemesi) → `location.hash` oturum ekranı
(hashchange pencereyi kapatır → önizleme serbest). Hata/iptal → pencere geri gelir. Pencere kapanışı → açık oturumlar, yarım kayıt, tablo
yenilenir. `#/drone/sim?new=1` pencereyi açık getirir (testler). Sahte kipte (`?mock=1`) tablo yok.

**Testler** (`tests/test_flightsim.py runs_testleri`): önceki testlerin oturumları listede (replay satırı `source_log_id`, çarpışmalı oturum
`carpisma`), sabit kanat oturumu: sahte SITL PARAM_VALUE (`param_son`, `_param_count`), sahte param_set, `scripts/hello.lua` + `APM/scripts/mp.lua`,
ekran kaydı (start/chunk/finish share:false → `s.video`), summary → kapat → satır alanları (ilişkiler, world/launch JSON, model, konum,
params_count ≥ 3, scripts_count 2, video_rec_id) + `params.param` içeriği (`WP_RADIUS,90`, `ARSPD_FBW_MIN,12.5`, `RTL_ALT,100`); MASTER:
admin/salt okuyan 403 → `config.MASTER_USERNAMES` ile 200 (.param metni, zip içeriği) → yine 403; video (saklanan dosya, `?dl=1` attachment);
filtreler (type, center_id+owner_id+result+mode, mode replay, q merkez/oturum no/yok, from/to, sıralama artan/azalan/duration/type, page 99 →
düzeltme, 400'ler), facets; kapanış sonrası paylaşım → `video_post_id/video_path` + feed dosyasından video; silme (salt okuyan 403; satır + dizin
gider, özet ve paylaşım kalır); `rec.bin` oturumu + sahte .BIN → `bin_log_id`, `/bin` indirme, `q=SIM-`, analiz HATA → `play_log_id` null.
Playwright (`/tmp/flsim/rn/e2e_rn.py`, port 8797, headless shell): tablo (filtre, sıralama), pencere (başlık/altbilgi), Başlat → oturum, master /
master olmayan kullanıcıda Parametreler-Script düğme görünürlüğü.

**Sınırlar / açık**: parametre dökümü SITL kapanmadan en çok 6 sn bekler; MP bağlanmamış ve döküm yarım kalmışsa `.param` o ana kadar görülen
değerleri içerir (eksik olabilir). Script arşivi yalnız SITL çalışma dizininden (`scripts/`, `APM/scripts/`); MAVFTP'nin başka bir kök göstermesi
hâlinde dizin adı `flightsim_runs.SCRIPT_DIZINLERI`'ne eklenir. Kayıt satırı silinirken video/özet/.bin silinmez (kendi yüzeylerinden silinir).
Oynat yalnız analizi TAMAM .bin'li kayıtlarda etkindir (kayıt seçeneği kapalı oturumlar oynatılamaz).

## 22. FPV kipi — pilot gözü kamerası (`pilot`; `static/js/modules/flightsim_fpv_osd.js`, 3B `flightsim3d.js`)
Kullanıcı isteği: mevcut "Dron kamerası" aslında **gimbal/görev kamerası**ydı (eğim ok tuşu/tekerlek, askeri HUD, FOV 78, ufuk sabit); yanına **gerçek FPV**
(pilot gözü: kamera burna sabit, gövdeyle yatar) istendi. Eski kipin kod adı `fpv` **değişmedi** (CSS `.fs-fpv`, ses, testler); yalnız etiketi
"Gimbal kamerası" oldu (i18n anahtarı `Dron kamerası` → `Gimbal kamerası`, 6 dil). Yeni kipin kod adı `pilot`, etiketi "FPV".

| Tuş | Kod | Etiket | Kamera | Üst katman | Panel |
|---|---|---|---|---|---|
| 1 | `follow` | Takip | OrbitControls, kritik sönümlü yay | — | görünür |
| 2 | `pilot` | **FPV** | burun + küçük ileri ofset, gövdeyle döner (roll/pitch/yaw tam, **ufuk yatar**), gimbal yok, FOV **120°** (90–150, tekerlek ±5), near **0,05** | **OSD** (`.fs-osd`, O) | kart gizli (`.fs-fpv`), sanal kumanda çubukları görünür |
| 3 | `fpv` | Gimbal kamerası | burun, gimbal ↑↓/tekerlek (−90…+30), ufuk sabit, FOV 78 | askeri HUD (`.fs-mhud`, H) | kart gizli |
| 4 | `free` | Serbest | WASD/QE + fare | — | görünür |
| 5 | `ground` | Yer | merkezden izler, teleobjektif | — | görünür |

**C** kamera döngüsü (`nextCameraMode`: 1→2→3→4→5→1); seçim `localStorage fs.cam` (oturum/kayıt arası kalıcı; `createFlightSim3D opts.camera`).
Sanal kumanda açıkken 1–5/C çalışır (C `RC_KEYS` dışında).

- **3B (`flightsim3d.js`)**: `pilot` kipinde kamera konumu = gösterilen gövde konumu (kilit/düzenek dahil `drone.group`) + gövde çerçevesinde
  `(0, nose + back, up)`; **"Pervane/burun görünür"** (`fs.fpv.nose`, varsayılan açık) → `back = −0,08·yarıçap`, `up = 0,05·yarıçap + 0,03` (kopterde birkaç
  cm: pervane uçları kadrajın kenarında; Caymaz'da ~30 cm geride: gövde ucu altta); kapalı → `+0,02·yarıçap` ileri. Yönelim `drone.group.quaternion × X(90°)`.
  **Son işleme** (yalnız `pilot`): sahne → `WebGLRenderTarget` (MSAA 4) → tam ekran quad `ShaderMaterial`: hafif **barrel/balıkgözü** (`uv' = c + d·(1 + k·r²)·s`,
  k 0,12, s köşeleri kadrajda tutar — siyah köşe yok) + **vinyet** (0,28) + analog kipte **doygunluk ×1,35, kontrast 1,08, R↑/B↓** kayması. Ek maliyet tek
  tam ekran geçiş; diğer kiplerde doğrudan render (maliyet yok). `EffectComposer` vendor'da yok, kendi quad'ı (OrthographicCamera + PlaneGeometry 2×2).
  **PiP**: eski "FPV'de sağ üstte takip kamerası" (fs.fpv.pip, 20 fps) **§22.4 genel kamera PiP'ine** dönüştü (her kipte, sürüklenebilir; FPV'de gimbal
  kamerasını gösterir; eski anahtar `fs.fpv.pip=0` ilk açılışta PiP'i kapalı başlatır). Gölgelendirici artık `flightsim_camera.js CAM_FRAG` (§22.3).
  Dışa: `setPilotFov/getPilotFov`, `setFpvAnalog`, `setFpvNose`, `setPip/getPip`, `pipRect()`, `pipStats()`; `opts.camera/pilotFov/fpvAnalog/fpvNose`,
  `onPilotFov`. `wheel`: `fpv` → gimbal ±3°, `pilot` → FOV ±5° (`fs.fpv.fov`). `dispose` render hedeflerini/materyalleri bırakır.
- **OSD (`createFpvOsd(stage, ctx, {tr})`)**: askeri HUD'dan ayrı dosya/katman; Betaflight/analog tarzı — beyaz monospace (500/700), ince siyah kontur
  (`strokeText`), metin ölçümü yok. Yalnız `camMode === 'pilot'` iken çizilir (kendi rAF'ı; diğer kiplerde canvas gizli, döngü durur); açıkken
  `.fs-stage.fs-osd-on` (sağ veri paneli ve ÇARPIŞMA bandı gizli — OSD kapsar). **Alanlar**: üst sol **mod** + **ARM/DISARM**; üst orta **FLY mm:ss**
  (canlı: oturum başı `t0`; kayıt: log zamanı `t.t`, altında "▸ REPLAY") — gezinti kapsülünün altına yerleşir (`.fs-nav` ölçülür); üst sağ **FOV** (PiP sağ
  üstteyse altına iner; PiP çerçevesi/etiketi artık PiP'in kendi OSD'sinde, §22.4); orta küçük artı + **yatan yapay ufuk** (`horizonLine`: odak `f = (H/2)/tan(fov/2)`, burun yukarı → ufuk aşağı `f·tan(pitch)`,
  sağa yatış → sağ uç yukarı; ±10/20° kısa çentikler, ufukla döner; merkezde boşluk); sol **hız km/h** (büyük), sağ **AGL m** (yoksa MSL) + dikey hız ▲/▼;
  alt sol **pil V + % + çubuk + hücre (nS)** (`battPct`: `tele.batt_pct` varsa o, yoksa gerilimden 3,5→0 %…4,2→100 %/hücre; MP/kayıt bilgisi kutusunun
  üstüne çıkar, sanal kumanda açıkken satırlar çubukların üstüne); alt orta **RSSI** (`tele.rssi` yoksa "RSSI --"; SITL'de sabit %99 YOK) + **SAT n fix** +
  lat/lon; alt sağ **HOME mesafe + EVE OKU** (`homeVector`: ENU düz dünya; ok `relBearing = kerteriz − yön`, gövde yönüne göre döner; `tele.home`
  GPS evi; kayıtta `data.home`); **uyarılar** merkez altında kırmızı yanıp söner (`osdWarnings`): ÇARPIŞMA, DÜŞÜK PİL (< %25), ALÇAK (armed, AGL < 10 m,
  yer hızı > 3 m/s), RSSI DÜŞÜK (< 30). **O** OSD aç/kapa (`fs.osd.on`). Yönelim 3B'nin render ettiği `sim.getPose()` (enterpolasyonlu).
- **Analog efekt** (`fs.fpv.analog`, varsayılan KAPALI): OSD katmanında tarama çizgisi deseni (1×3 px, bir kez) + rastgele yatay kayma/parazit şeritleri ve
  benekler, yoğunluk `analogNoise(rssi, evMesafesi)` (RSSI varsa %60'ın altında doğrusal 0→1; yoksa eve uzaklıkla 3 km'de 0,6); renk doygunluğu 3B
  gölgelendiricisinde (`sim.setFpvAnalog`).
- **Alt çubuk**: FPV'de tek kapsül **"FPV 120° ▾"** (`.fs-fpv-ctl`, ses menüsü kalıbı `.fs-audio-menu`): OSD · Analog efekt ·
  Pervane/burun görünür (onay kutuları) + FOV kaydırıcısı (90–150) + ipucu; dışarı tıklama kapatır. Gimbal kamerasında eski "Gimbal −10°" etiketi + HUD düğmesi.
  Kayıt kipinde oynatma çubuğuyla birlikte tek satıra sığar (1360 px'te alt çubuk 57 px).
- **Ses (§16)**: `fpvParams(airspeed, mode)` — `pilot`: süzgeç açık (20 kHz), master **×1,3** (`PILOT_BOOST`), rüzgâr `min(hız/35, 1)·0,8` (frekans
  350 + 45·hız), kaynak dinleyicide; `fpv`: eski (900 Hz, 0,5); diğer kipler boost 1, rüzgâr 0.
- **Kayıt/oynatma (§8)**: aynı 3B örneği → FPV ve OSD kayıtta da seçilir (kareler `tele` biçiminde; süre log zamanı). **Ekran kaydı (§17)**:
  `getDisplayMedia` ekranı yakalar (OSD DOM üstünde → kayda girer); yedek yolda birleşik tuvale `.fs-mhud` ve `.fs-osd` (`getOsdCanvas`) de çizilir.
  Kayıt başlatmak kamerayı değiştirmez.
- **Sahte kip teşhisi**: `#/drone/sim/mock-1?mock=1&bank=20` → sahte seyir dönüşü yarıçapı `V²/(g·tan 20°)` (kopterde de yatış) — FPV görüntüleri için;
  `netsim=delay0` ile `window.__fsSim` (`getCamera/getPilotFov/getPip/pipStats`).
- **Performans**: OSD çizimi ≈ **1,1 ms/kare** (SwiftShader, 1360×820; `canvas.__osd.stats()`); PiP 20 fps'e sınırlı (`pipStats().renders`); son işleme tek
  geçiş. Yazılım WebGL'de (headless shell) rAF kare süresi takip 490 ms / FPV 760 ms / FPV+PiP 850 ms — SwiftShader'a özgü; gerçek GPU'da 60 fps hedef.
- **Testler**: `node tests/test_flightsim_fpv.mjs` (12): kip sırası/etiket/döngü, FOV/PiP sabitleri, eve vektör/ok açısı, ufuk çizgisi (pitch/roll/FOV),
  pil yüzdesi/hücre, uyarılar, analog parazit, saat, tercihler (localStorage), ses `pilot` (saf + sahte grafik). Mevcut `test_flightsim_audio.mjs` (27),
  `test_flightsim_launch.mjs` (5) ve `tests.test_flightsim` geçer. Playwright (`/tmp/flsim/fpv/fpv_shots.py`, port 8990, HEPGO_SITL=0, sahte kip; görüntüler
  `/tmp/flsim/fpv/shots/`): etiket sırası, FPV (OSD görünür, HUD/panel gizli, roll ≈ 18°, PiP), tekerlek FOV 110/150 sınır, menü (analog/PiP, dışarı tık),
  sanal kumanda FPV'de görünür, O, C döngüsü, gimbal kamerası HUD çalışır, yenileme sonrası kamera FPV kalır (fs.cam), tam ekran, kayıtta FPV + HUD;
  konsol hatası yok.


### 22.3 Kamera türü — gündüz / termal / gece görüşü (`static/js/modules/flightsim_camera.js`; sunucu enum `flightsim.KAMERA_TURLERI`)
Kullanıcı isteği: "simülasyona girişte kamera türünü sorsun: gündüz kamerası, termal kamera, gece görüşü". Tür **araç üstü kameralara** uygulanır:
gimbal kamerası (`fpv`) ve FPV (`pilot`) — gerçek dronlarda termal/gece FPV kameraları da var ve gece sahnesinde FPV'yi ancak gece görüşüyle uçurmak
mümkün; **takip/serbest/yer** dış gözlemci kameraları her zaman gündüz renklidir (`camFxApplies`). PiP araç kamerasını gösteriyorsa onda da uygulanır.

- **Gölgelendirici `CAM_FRAG`** (tek tam ekran geçiş; eski FPV post'unun yerini aldı — balıkgözü/vinyet/analog aynen): `camType` 0 gündüz (değişmez),
  **1 termal**: 3 örnekli yumuşatılmış parlaklık × `thermalGain` (gece 3,6 · alacakaranlık 1,7 · gündüz 1 — termal aydınlatmadan bağımsız) → AGC `pow(clamp((l − 0,03)·1,5), 0,85)` → palet **beyaz-sıcak / siyah-sıcak / ironbow**
  (siyah→mor→kırmızı→turuncu→sarı→beyaz), ±%2,5 zamansal gürültü, hafif köşe kararması, **640 px yatay düşük çözünürlük** (PiP'te yok — zaten küçük);
  **2 gece görüşü**: parlaklık × kazanç (`nightGain`: gece 7 · alacakaranlık 3,4 · gündüz 2 — yoğunlaştırıcı gündüz doyar), 16 örnekli **halo**
  (eşik 0,8 üstü parlaklık: seyir ışıkları, gece pencereleri, farlar), tanecik (±0,085), **yeşil fosfor** (parlakta beyaza kayar), dairesel **tüp vinyeti**.
  Ana görüntüde post yalnız `pilot` ya da (`fpv` ve tür ≠ gündüz) iken; aksi doğrudan render (maliyet yok).
- **Isı ipuçları (termal)**: render öncesi sıcak nesnelerin malzemesi geçici olarak ısı düzeyinde düz renk (`MeshBasicMaterial`, 20 kademe önbellekli)
  ile değiştirilir, render sonrası geri alınır: **dron gövdesi 0,74, pervane/motor 0,9**, kalkış düzeneği (rampa/**pickup aracı**) 0,58, **su 0,05**
  (`userData.heat`; prosedürel/gerçek arazi su örgüleri `heatWorld`); gökyüzü ve sis rengi soğuk koyu (0,07); seyir ışığı sprite'ları gizlenir. Liste
  saniyede bir yeniden toplanır. Arazi/bina/ağaç: sahne parlaklığı (güneşli asfalt ılık, ağaç/gölge serin). Sahnede insan modeli yok (SIMUMAV elden atış
  pilot figürü ayrı kaplama tuvalindedir — termal geçirmez; bilinen sınır).
- **Seçim ve kalıcılık**: oturum gövdesi `camera: 'day'|'thermal'|'night'` (sunucu `kamera_dogrula`: boş → day, başka değer **400**); `session.camera`;
  uçuş içinde **T** (döngü), **Shift+T** (termal paleti; termal değilse termale geçer), alt çubukta **"📷 Tür ▾"** menüsü (tür · palet · PiP aç/boyut ·
  ipucu). Değişim canlı oturumda **`camera` komutu** ile sunucuya (KOMUTLAR; HAZIR beklemez, SITL'e gitmez; kayıttan oynatma oturumu da kabul eder) →
  kapanışta **`drone_sim_runs.camera`** (son tür). Tercih `localStorage fs.cam.type` / `fs.cam.palette`; dron başına `fs.cam.byDrone`.
  `GET /api/drone/sim/drones` her kayda **`camera`** (o dronun son simülasyon kaydındaki tür) ekler → sihirbaz varsayılanı.
- **Kayıttan oynatma**: `ReplaySession` kaydın canlı oturumundaki türü (`drone_sim_runs.camera`, `bin_log_id` eşleşmesi) okur → aynı türle açılır; dış
  .bin ise sihirbazda seçilen tür (`ac_replay(camera=…)`), o da yoksa gündüz. `to_dict().camera` her zaman dolu.
- **Ekran kaydı (§17)**: askeri HUD ve FPV OSD katmanları PiP dikdörtgenini temizler (yazılar PiP'in üstüne binmez); tür efekti ve PiP görüntüsü 3B tuvalin içindedir → birleşik kayıt tuvaline kendiliğinden girer; PiP OSD tuvali `getOverlays`
  ile PiP dikdörtgenine ölçekli eklenir.

### 22.4 Kamera PiP'i — sürüklenebilir, çift tık → gimbal (`createCameraPip`; 3B `setPipRect / swapPip / getPipSource`)
- **Kaynak** (`pipSourceFor`): ana kip gimbal değilse PiP **gimbal kamerası** (tür efekti + yakınlaştırma); ana kip gimbal ise **önceki ana kip** (takip:
  kullanıcının yörünge ofseti `lastFollowOff` korunur; FPV: balıkgözü dahil; serbest/yer PiP'te gösterilmez → takip). **Çift tık / çift dokunma**
  (`pipSwapTarget`; ≤ 320 ms, ≤ 24 px — kendi algılamamız, tarayıcı dblclick'i bastırılır) ya da ⇄ düğmesi / Enter: ana kip gimbal değilse **gimbal**,
  gimbalse PiP'teki kipe döner (yer değiştirme). Takipten çıkıp dönünce bakış açısı korunur.
- **Tek WebGL bağlamı**: PiP ikinci bağlam AÇMAZ (SIMUMAV `__smGl ≤ 1`). Ayrı `PerspectiveCamera` → küçük `WebGLRenderTarget` (CSS boyutu ×
  min(dpr, 1,5) × **0,75**) → her karede aynı `CAM_FRAG` ile `setViewport/setScissor` kopyası. Yenileme `pipInterval`: **30 fps**, ortalama kare > 22 ms
  ise **15 fps** (yarı hız); gölge haritası PiP geçişinde yenilenmez; Google 3B karoları ana kameraya göre yüklüdür (PiP için ayrı LOD güncellemesi yok).
  Sekme gizliyken rAF durur → PiP de durur. `pipStats()` → `{renders, blits, interval, frameMs, rt}`.
- **Pencere (DOM)**: `.fs-pip` saydam çerçeve (görüntü altta, tuvalde) + OSD tuvali (köşe parantezleri, `● TERMAL · WH`, kaynak `GİMBAL/TAKİP/FPV`,
  `GMB −30°`, `×2.0`, gimbalde merkez artı; ~6 Hz, değişince çizilir) + üzerine gelince araç düğmeleri (⇄ · S/M/L · ×) + köşe tutamacı (boyut).
  Fare/dokunmatik/kalem **pointer olaylarıyla sürüklenir** (`touch-action: none`); bırakınca köşe yuvasına **56 px** içindeyse **köşeye yapışır**
  (`pipSnap`), değilse serbest konum oran olarak saklanır (pencere boyutu değişince orantılı). Varsayılan **sağ alt** (kullanıcı isteği; sağdaki veri paneli / harekât kartı otomatik atlanır) (kadranlar alt ortada, veri paneli ve harekât
  kartı sağda; alt çubuk + atıf satırının üstünde, üstte gezinti kapsülünün altında); sağ köşeye taşınırsa görünür harekât kartının solunda kalır
  ve sol taraftayken yüzen Mission Planner / kayıt bilgisi kutusunun üstünde kalır (`pipObstacleInsets`; kart açılıp kapanınca/kip değişince yeniden
  yerleşir). z-index 7: askeri HUD / FPV OSD katmanlarının üstünde. Boyut **S 208 / M 288 / L 400** px (16:9; dar ekranda genişliğin
  %46'sı, geniş ekranda %34'ü). Tercih `localStorage fs.cam.pip` `{on, size, corner, fx, fy}`. **V** gizle/göster; PiP gimbal gösterirken üstünde
  **tekerlek = yakınlaştırma**. `prefers-reduced-motion`: yapışma/boyut geçiş animasyonu yok.
- **Gimbal yakınlaştırma** 1–8× (`+`/`−`, Shift+tekerlek, PiP üstünde tekerlek): FOV = 2·atan(tan 39° / z) (`gimbalZoomFov`; ana görünüm ve PiP).

### 22.5 Sihirbaz "Kamera" kartı
"Yeni Simülasyon Başlat" penceresinde **4. Kamera** (kayıt kipinde 3.): üç kart, her birinde **önizleme** — prosedürel küçük sahne (gökyüzü, tepeler,
yol, göl, ağaçlar, ev + yanan pencere, araç (sıcak motor/tekerlek), insan, dron) renk ve ısı katmanı olarak 2B tuvale çizilir ve **aynı formüllerle**
(`camFxPixel`, 1024 girişli tablo) işlenir — ek WebGL bağlamı yok (≈ 5 / 65 / 430 ms SwiftShader'da, açılışta bir kez). Termal seçiliyken palet seçici.
Varsayılan: dron kaydının son türü → bu dron için yerel son seçim → son tercih → gündüz. Seçim `be.create({camera})`.
- **Testler**: `node tests/test_flightsim_camera.mjs` (18: tür/palet, kipler, PiP kaynağı + çift tık dizisi, yenileme aralığı, yakınlaştırma FOV, boyut/
  yerleşim/yapışma/serbest oran, çift dokunma, tercihler + eski anahtar göçü, gölgelendirici sözleşmesi, camFxPixel paletleri, SIMUMAV camera_pick +
  7 dil anahtarları); `tests.test_flightsim kamera_testleri` (enum 400/422, oturum alanı, `camera` komutu, kayıt satırı, /drones önerisi, kayıttan
  oynatma türü). Görsel: `/tmp/campip-e2e/shots.py` (HEPGO sahte kip + SIMUMAV dev giriş; görüntüler `/tmp/campip-shots`).

## 23. Güç ve yakıt — azami hız, simülasyon hızı, yakıt ve elektronik batarya (`app/flightsim_power.py`, `static/js/modules/flightsim_power.js`; SITL yaması `SIM_PLN_THR_MUL` `tools/sitl/0002-sim-pln-thr-mul.patch`; tablo `drone_sitl_options`, `drone_sim_runs.power…`)
Kullanıcı isteği (özet): **(2)** "CAYMAZ'da 222cc karbüratörlü motor var; sim'de hız yarı yarıya düşük kalıyor; tam gazda 45 m/s olmalı. Sihirbazda Azami
hız alanı (dron kaydından; CAYMAZ 45)." **(3)** "Oturum içinde 1×/2×/4×/8× simülasyon hızı → SIM_SPEEDUP canlı; telemetri/kayıt/.bin/replay SITL zamanıyla
tutarlı; video gerçek zaman." **(4)** "Yakıt (L) ve tüketim (km/L); her kamera kipinde yakıt göstergesi; biterse yalnız kırmızı uyarı, uçuş sürer; raporda mesafe,
harcanan yakıt, ölçülen km/L → dron kaydına." **(5)** "Elektronik batarya: hücre, mAh, saatlik W; her kipte gösterge; sonunda ortalama W drona yazılır; HUD'daki
pil alanı artık bu bataryayı göstersin." Tüm göstergeler kayıttan oynatmada da görünsün; sihirbazda "Güç ve yakıt" bölümü (CAYMAZ varsayılanları 45 m/s, 5 L,
25 km/L, 4S 10000 mAh 30 W); Simülasyon Kayıtları tablosunda yakıt/batarya sütunları (Detaylı kipte).

### 23.1 Azami hız — SITL fiziği ve ArduPilot sınırları
**Araştırma (ArduPilot Plane-4.7.2 kaynağı, `libraries/SITL/SIM_Plane.cpp`):** `plane` modelinde itki = gaz (0…1) × `thrust_scale`, `thrust_scale = m·g /
hover_throttle` = 2 kg · 9,81 / 0,7 = **28 N**; sürükleme = ½ρV²S·(c_drag_p + CL²/(π·e·AR)) (S 0,45 m², b 1,88 m, c_drag_p 0,1, e 0,9; `default_coefficients`).
Seviye uçuşta T = D çözümü: **tam gaz ≈ 31,8 m/s** (`flightsim_power.plane_tam_gaz_hizi`). Stok SITL'de bu hızı değiştiren **parametre yok**: `SIM_ENGINE_MUL`
yalnız `SIM_ENGINE_FAIL` maskesindeki motorlara uygulanır ve plane modelinde hiç okunmaz; `-jet/-heavy` son ekleri kütleyi değiştirir (hız 102 m/s "jet" 22 kg);
JSON katsayı dosyası (`plane:model.json`) aerodinamiği değiştirir ama uçuş karakterini de bozar (c_drag_p). Kullanıcı tarafında ise hız ayrıca ArduPlane'in
`AIRSPEED_MAX` (varsayılan 22 m/s; FBWB/CRUISE/AUTO hedef üst sınırı, TECS) ve `THR_MAX` sınırlarıyla kesilir — "yarı yarıya düşük" gözlemi bu ikisinin
bileşimidir (otomatik gaz modlarında 22 m/s hedefi + stok fizik 31,8 m/s tavanı).

**Çözüm (iki katman):**
1. **SITL yaması `SIM_PLN_THR_MUL`** (`tools/sitl/0002-sim-pln-thr-mul.patch`, 0001 üstüne; `SITL::var_info3` idx 3, float, varsayılan 1): `SIM_Plane::calculate_forces`
   itkiyi `thrust_scale × mul` ile ölçekler; gürültü terimi ölçeksiz gaz oranıyla hesaplanır; diğer modeller (copter, quadplane'in rotorları) etkilenmez (quadplane
   ileri itkisi plane modeli olduğundan etkilenir). Tam gaz seviye hızı √mul ile ölçeklenir → `thr_mul_icin(v) = D(v) / T(1)`: **45 m/s → 1,993**. İkili desteği
   `drone_sitl.hiz_olcegi_destegi` (dosyada `\0PLN_THR_MUL\0` imzası; `sanal_montaj_destegi` kalıbı). Yamalı ikililer: `/opt/hepgo/sitl/bin-new`
   (`.version`: `…+hepgo-sim-srv-rev+pln-thr-mul (fb773567 + 0001 + 0002)`); PROD'a yerleştirme kullanıcı onayıyla (README).
2. **ArduPilot parametreleri** (ilk kalp atışında, kayıtlılardan SONRA; `SimSession._hiz_yaz` → `flightsim_power.hiz_parametreleri`): `AIRSPEED_MAX = v`,
   `AIRSPEED_CRUISE = v × oran` (oran = dronun kayıtlı `AIRSPEED_CRUISE/AIRSPEED_MAX`; yoksa ArduPlane varsayılanı 12/22 → 45 için 24,5; kayıtlı `AIRSPEED_MIN`'in
   altına inmez), `THR_MAX 100`, yamalı ikilide `SIM_PLN_THR_MUL`. Yankılar `param_izleyici.yukleme_isaretle` ile kalıcı kayda GİRMEZ (oturum ayarı; kullanıcı
   sonra MP/panelden değiştirirse kaydedilir). `SIM_PLN_THR_MUL` `drone_params.HARIC_ADLAR`'da. Uçak tiplerinde azami hız yoksa bile `SIM_PLN_THR_MUL 1`
   yazılır (eeprom'da önceki oturumdan kalan çarpan silinsin). Yamasız ikilide sarı olay: "SITL ikilisi itki ölçeği desteklemiyor; azami hız yalnız ArduPilot
   sınırlarına uygulandı (stok fizik tam gazda ≈ 32 m/s verir)". Kopterlerde `max_speed_ms` yok sayılır (null).
`session.speed_scale = {supported, thr_mul, thr_mul_sitl (PARAM_VALUE'dan gözlenen), stock_ms}`.

### 23.2 Simülasyon hızı (`cmd speed {factor}` → `SIM_SPEEDUP`)
Panel "Sim" grubunda ve üst çubukta (nav) **1×/2×/4×/8×** kapsülü (`createSpeedPill`; yazma izni; seçili düğme `tele.speedup` ile eşitlenir — SITL'in
bildirdiği PARAM_VALUE). Gerçek SITL'de `PARAM_SET SIM_SPEEDUP` canlı; sahte kipte kinematik adımı `dt × speedup` (saat `sure_ms` hızlı akar). `reset`
sonrası yeni SITL'e seçili hız yeniden yazılır (`speedup_istek`). Zaman tutarlılığı: telemetri `tbm` (SITL time_boot_ms) hızlı akar → istemci enterpolasyonu
(§5 `net.clock` kaynak saat/gerçek zaman oranı) ve yakıt/batarya entegrasyonu SITL zamanını izler; `.bin` DataFlash zaten SITL saatiyle → kayıttan oynatma süresi
simülasyon süresidir; ekran kaydı (video) gerçek zamandadır. WS `tele` yayını hızlandırılmış kipte **duvar saatinde 50 Hz tavanında** kalır (`_tele_yay`:
`TELE_TBM_KAPI` SITL ms kapısı 4×'te 200 Hz yayına dönerdi). **Not:** Mission Planner da aynı SITL'e bağlıdır; MP de hızlandırılmış uçuşu görür (MP'nin
HUD saati SITL zamanı kadar hızlı akar) — olay şeridinde belirtilir. Rapor/kayıt: `power.speedup = {max, changes, last}`, `drone_sim_runs.speedup_max`,
tabloda sonuç rozetinin yanında "4×".

### 23.3 Yakıt ve elektronik batarya modeli (`flightsim_power.GucDurumu` ↔ `createPowerSim`)
- **Yakıt** (yalnız armed): `L/dk = (v_km/h ÷ 60) ÷ (km/L) × (0,5 + 0,5·gaz)` — mesafe tabanlı + gaz kolu ağırlıklı (gaz %100'de 2×, %0'da ½). Kalan menzil =
  kalan L × km/L. `fuel_l = 0` → gösterge yok (elektrikli; kopter varsayılanı). Ölçülen km/L = kat edilen km ÷ harcanan L (≥ 0,3 km ve ≥ 0,02 L).
- **Elektronik batarya** (telemetri aktığı sürece; SITL'in `SIM_BATT`/`SYS_STATUS` pili DEĞİL): Wh = mAh/1000 × hücre × 3,7; harcama = W × saat + servo
  aktivitesi (Σ|Δpwm| µs × 0,0005 J; 1000 µs tam sapma 0,5 J). Anlık W = son 30 sn kayan pencere → kalan süre = kalan Wh ÷ W. Gösterge gerilimi kestirimi
  hücre × (3,5 + 0,7·kalan oran). Ortalama W = harcanan Wh ÷ saat (≥ 60 s).
- **Zaman kaynağı** SITL `time_boot_ms` (speedup'ta hızlı; `reset`te saat sıfırlanır → `sifirla_zaman`, seviyeler korunur: tank/batarya değişmedi); > 5 sn boşluk
  entegre edilmez. Sahte kipte kinematik saati.
- **Bitiş:** yalnız uyarı — kırmızı olay (severity 2 "YAKIT BİTTİ — … simülasyon sürüyor" / "ELEKTRONİK BATARYA BİTTİ — …") + WS `{t:'warn', kind:'fuel_empty'|'elec_empty'}`
  (ön yüz toast); `tele.fuel.empty` / `tele.elec.empty`; HUD/OSD/panel kırmızı; uçuş ve SITL etkilenmez.
- **Yayın:** her `tele` karesine `fuel: {l, pct, lpm, range_km, empty} | null`, `elec: {wh, pct, w, min_left, cells, v, empty} | null`, `speedup`;
  `session.power` (ayarlar), `session.power_state` (anlık). **Göstergeler:** sağ HUD "Batarya" satırı elektronik bataryayı (yoksa SITL pili) ve "Yakıt" satırı
  (L · % · menzil); harekât paneli BATARYA karosu (%, V, kalan süre, nS) + yeni **YAKIT** karosu; gimbal HUD (`flightsim_hud.js`) `BAT 16.2V 61% 120min` +
  `FUEL 4.14L 83% 104km` + uyarı kutuları (BATARYA BİTTİ / YAKIT BİTTİ / DÜŞÜK YAKIT); FPV OSD (`flightsim_fpv_osd.js` `osdBattery/osdFuelText/osdWarnings`)
  pil bloğu + yakıt satırı + çubuklar + uyarılar (DÜŞÜK YAKIT < 20 %, YAKIT BİTTİ, DÜŞÜK PİL < 25 %, BATARYA BİTTİ). Serbest/yer kameralarında sağ HUD ve panel.
- **Kayıttan oynatma ve sahte kip:** sunucu yakıt alanı üretmez; `ReplaySession.power` = kaydın canlı oturumundaki ayarlar (`drone_sim_runs.power.settings`,
  `bin_log_id` = log; dış .bin'de null → gösterge yok). Ön yüz `createPowerSim(session.power)` ile karelerden (yer hızı, gaz, armed, servo) oynatıcı zamanıyla aynı
  modeli hesaplar; atlama/baştan → `rebuild(data, t)` (≤ 4 Hz örnekleme ile baştan o ana entegre). Sahte kip (`?mock=1`) aynı yol (`tele.ts`).
- **Özet/kayıt/dron:** `summary.power = {settings, dist_m, time_s, armed_s, max_speed_seen, fuel{start_l, used_l, left_l, pct, km_per_l, empty_t}, elec{wh_cap,
  wh_used, wh_left, pct, w_avg, empty_t, cells, mah, w_set}, speedup{max, changes, last}}`; rapor modalında **"⚡ Güç ve yakıt"** bölümü (karolar: mesafe,
  harcanan yakıt, ölçülen km/L, batarya Wh, ortalama W; bitiş anları kırmızı) ve paylaşım metninde satır (`rapor_metni` / `powerLines`). `drone_sim_runs`:
  `power` JSON + `fuel_used_l, fuel_km_per_l, elec_wh, elec_w_avg, speedup_max` (ALTER ile eklenir); tabloda Detaylı kutusundaki **"Yakıt / batarya sütunları"**
  onayı (`localStorage fs.runs.power`) Sonuç'tan sonra iki sütun açar. Kapanışta geçerli ölçümler dron kaydına yazılır (`flightsim_runs.kaydet` →
  `drone_params.secenek_yaz`: `fuel_km_per_l_last`, `elec_w_last`) + olay "Dron kaydına yazıldı (sonraki simülasyonda önerilir): …".

### 23.4 Sihirbaz "Güç ve yakıt" ve dron kaydı
Kart (`createPowerSection`; Dünya'dan sonra, Kayıt'tan önce; kayıt kipinde gizli): iki sütun **Motor** (Azami hız m/s — yalnız uçak; Yakıt L; Tüketim km/L) ·
**Elektronik batarya** (Hücre sayısı S; Kapasite mAh; Saatlik tüketim W); bilgi satırı (azami hız km/h + stok SITL, yakıt menzili, batarya Wh ≈ dk); yamasız ikilide sarı
not. Değerler `GET /power-defaults?type&drone_id` ile gelir: dron kaydındaki seçenekler (`drone_sitl_options`: `max_speed_ms, fuel_l, fuel_km_per_l_last, elec_cells,
elec_mah, elec_w_last`) "dron kaydından" rozetiyle, yoksa tip varsayılanı (CAYMAZ / kopter yakıtsız). Tip ya da dron kaydı değişince yenilenir; kullanıcı yazınca
rozet kalkar. Başlat → `power` gövdesi. Dron kaydı uçları `GET/PUT /api/drone/drones/{id}/sim-power` (PUT yalnız gönderilenler; `null` siler; sınır dışı 400;
yazma `drone.drones`). `GET /api/drone/sim/drones` satırlarına `power` önerisi eklendi.

### 23.5 Doğrulama
- `tests/test_flightsim.py guc_testleri`: saf model (31,85 m/s stok; 45 → 1,993; hız parametreleri/oran; L/dk; Wh; servo J; eşikler), `dogrula` (sınırlar, kopter),
  `GucDurumu` sentetik 60 sn (0,05 L tank 34,7 sn'de biter; mesafe/süre; özet; reset), `power-defaults`, `sim-power` GET/PUT (403/400/404, null siler), `/drones`
  önerisi, start gövdesi (400/422), sahte oturumda `speed` (400'ler; 8× → `tele.speedup`, SITL saati gerçek zamandan hızlı), küçük tank/batarya → `warn fuel_empty/
  elec_empty` + kırmızı olaylar, uçuş sürer; summary/run satırı alanları; ölçümler dron kaydına → sonraki öneri; sabit kanatta `_hiz_yaz` sahte SITL'e AIRSPEED_MAX/
  CRUISE/THR_MAX (yükleme işareti), itki ölçeği yok → `SIM_PLN_THR_MUL` yazılmaz + sarı olay.
- `node tests/test_flightsim_power.mjs` (15): JS saf model (sunucuyla birebir sayılar), `createPowerSim` adım/bitiş/rebuild, metinler, OSD pil/yakıt alanları ve
  uyarılar, hız kapsülü. `test_flightsim_fpv.mjs` (12) geçer (osdWarnings imzası genişletildi).
- Gerçek SITL (`tools/sitl/dogrula_guc.py <ikili dizini> hiz,speedup,yakit`; sunucu betikten PID ile açılır/kapanır): ölçümler aşağıda.
**Ölçüm (gerçek SITL arduplane 4.7.2, prosedürel dünya, rüzgâr 0, tekerlekli kalkış 120 m, FBWA + RC gaz %100, pitch nötr, 70 sn; `/tmp/flsim/guc/`):**
- ÖNCE — yamasız ikili (`/opt/hepgo/sitl/bin`, yalnız 0001): SITL `AIRSPEED_MAX 45, AIRSPEED_CRUISE 24.5, THR_MAX 100`, `SIM_PLN_THR_MUL` yok (sarı olay);
  tam gazda **yer hızı 32,7 m/s, hava hızı 29,4 m/s** (stok fizik tavanı ≈ 31,8; hafif tırmanış) — kullanıcının "yarı yarıya düşük" gözlemi.
- SONRA — yamalı ikili (`bin-new`, 0001 + 0002): `SIM_PLN_THR_MUL 1.9931` yazıldı/okundu; tam gazda **yer hızı 47,6 m/s (son 25 sn ort.; en yüksek 48,0), hava hızı
  41,9 m/s**, ~4 m/s tırmanışta → hedef 45 m/s **±%10 içinde** (yer +5,8 %, hava −6,9 %). Uçuş kararlı (FBWA, 523 m AGL'ye tırmandı).
- Simülasyon hızı 4× (`cmd speed 4` → `SIM_SPEEDUP 4` PARAM_VALUE yankısı, `session.speedup 4`): ARM'den SITL saatinde **120 sn → gerçek 30,0 sn (oran 4,00)**;
  WS tele yayını duvar saatinde 50 Hz tavanında. `.bin` kaydı 6,0 MB, analiz `flight_s 123,0 / duration_s 123,3` (SITL zamanı), kayıttan oynatma oturumu
  `duration_s 123,26 · 1849 kare` ve `session.power` kaydın ayarlarıyla doldu (göstergeler karelerden). Rapor `power.speedup {max 4, changes 2}`,
  `power.armed_s 121,3` (sim) ↔ `flight.duration_s 42` (gerçek; rapor süresi duvar saatidir — simülasyon süreleri `power` altındadır).
- Yakıt/batarya (0,15 L @ 10 km/L; 1S 300 mAh @ 60 W; 4×): REST `power_state` 3 sn'de bir — yakıt 90 % → 65 → 43 → 24 → 3 → **0 (empty)**, menzil 1,35 km → 0;
  batarya 71 % → 53 → 35 → 16 → **0 (empty)**, anlık W 60–76 (servo katkısı). Özet: `fuel.empty_t 69,4 s`, `elec.empty_t 66,5 s` (sim), harcanan 0,15 L, mesafe 2,3 km →
  ölçülen **15,35 km/L**, ortalama **49,1 W**; kırmızı olaylar + `warn` çerçeveleri; `crash` kaydı yok, uçuş kapanışa dek armed sürdü (power.time_s 81,3 ↔ armed_s 72,3 —
  fark kalkış öncesi). Kapanışta dron kaydına `fuel_km_per_l_last 15,35`, `elec_w_last 49,1` yazıldı; sonraki `power-defaults` bunları önerdi; `drone_sim_runs`
  satırı `fuel_used_l 0,15 · fuel_km_per_l 15,35 · elec_wh 1,11 · elec_w_avg 49,1 · speedup_max 4`.

### 23.6 Güç paneli — otomobil tarzı analog kadranlar (`createPowerGauges`; CSS `.fs-gauges`)
Kullanıcı geri bildirimi (1): "Yakıt ve batarya göstergeleri görünmüyor; çok şık bir şekilde göstergeler görünsün" → her kamera kipinde, panelden
bağımsız güç paneli. Geri bildirim (2): "Göstergeler resimdeki gibi olsun, tam ortada altta olsun, bu şıklıkta olsun" (referans: otomobil gösterge paneli —
açık düz kadranlar, ince çentikli ölçek, siyah ibre, kırmızı/mavi uç bölgeleri, kadran altında dijital değer) → **yeniden tasarım**:
- **Yerleşim:** takip/serbest/yer kiplerinde alt çubuğun hemen üstünde (`bottom: var(--fs-bar-h) + 8 px`), **yatayda tam ortada** (`left 50 %` +
  `translateX(−50 %)`), harekât panelinden bağımsız; panel açıkken panelin solundaki boş alanın ortasında (`.fs-ops:not(.fs-fpv)` → `left: (100 % − 412 px) / 2`).
  Sanal kumanda açıkken (`rc-on`) %86 küçülüp klavye ipucu şeridinin üstüne kayar (çubuklar kenarlarda; panel + kumanda → sol çubuğun üstüne). Tam ekranda aynı.
  Boyut: büyük 150 px (HIZ · MOTOR), küçük 110 px (YAKIT · BATARYA); ≥ 1800 px ölçek 1,2; ≤ 1300 px 0,9; ≤ 760 px **iki satır** (hız + motor üstte,
  yakıt + batarya altta; ölçek 0,8). FPV OSD (`fs-osd-on`) ve gimbal HUD (`fs-mhud-on`) kendi çubuklarını çizer → kadranlar gizli (değişmedi).
- **Dört kadran** (`.fs-gauge[data-g=fuel|speed|engine|elec]`, SVG viewBox 100×100, **240° süpürme** −120° … +120°): **YAKIT** (ibre 0…1, E ¼ ½ ¾ F,
  boş uç 0…⅛ kırmızı, pompa ikonu, dijital `4.90 L`, altında `≈ 116 km · %98`), **HIZ** (yer hızı km/h; ölçek 0 … `niceScaleMax(azami × 1,2)` —
  CAYMAZ 45 m/s = 162 km/h → 0…200 adım 50; azami üstü kırmızı bölge; dijital `134` + `KM/H`; uçakta `IAS 120`; **uyarı üçgeni** yanıp söner: çarpışma
  bandı, aşırı hız (> azami × 1,02) ya da stall (uçak, armed, > 10 m AGL, IAS < azami × 0,25); kopterde 0…100, bölge yok), **MOTOR** (gaz kolu 0…100 %,
  kırmızı ≥ 90; dijital `72` + `% GAZ`; SITL `rpm` gelirse ×1000 RPM ölçeği), **BATARYA** (0…100 %, düşük uç 0…15 kırmızı, üst uç 90…100 mavi, pil
  ikonu, dijital `%99`, altında `16.8 V · ≈ 5 sa 14 dk`; SITL pili yedeğinde "SITL pili"). Yakıt 0 L (elektrikli) → yakıt kadranı yerine mavi **ELEKTRİK**
  rozeti (`.no-fuel::before`); batarya yoksa gizli; ikisi de yoksa kapsayıcı gizli.
- **Görünüm temaya göre** (`--fsg-*` değişkenleri; sabit renk yok): açık temada beyaz/açık gri yüzey (`#f7f8fa`), ince dış halka, ana/ara çentikler,
  gri rakamlar, **siyah ibre** + koyu merkez pimi, koyu dijital; `html[data-theme=dark]` → antrasit yüzey (`#2a2f3a`), açık çentik/rakam/ibre/dijital.
  Kırmızı/mavi bölge yayları iki temada aynı. İbre **rAF ile yumuşatılır** (`easeNeedle`: üstel yaklaşım τ 0,22 sn, 0,04° altında oturur; DOM yazımı
  ≤ 10 Hz, ibre aradaki kareleri doldurur). Seviye `gaugeLevel` (yeşil ≥ 30 · sarı < 30 · kırmızı < 15): sarıda dijital turuncu, kritikte kadran yüzeyi
  **kırmızı nabız** + dijital kırmızı; bitince kadranın üstünde **YAKIT BİTTİ / BATARYA BİTTİ** rozeti.
- **Tıklama:** kadran grubuna tıklayınca `.fs-power-pop` ayrıntı kutusu kadranların üstünde ortada açılır (Başlangıç / Tüketim ayarı / Harcanan / Anlık /
  Ölçülen / Mesafe · süre; kayıt-sahte kipte `createPowerSim.summary()`, canlıda `createPowerAcc`). Sağ HUD "Yakıt" satırı kadran görünürken gizli, panel
  YAKIT karosu kalır. Kayıttan oynatmada aynı kadranlar (atlamada `gauges.reset()`).
- **Saf yardımcılar** (`flightsim_power.js`): `needleAngle(v, min, max, sweep)`, `niceScaleMax(vmax, factor)` (adım 1/2/2,5/5/10/20 × 10ⁿ, 4–6 ana bölme),
  `scaleTicks(max, step, minor)`, `zoneArc(from, to, min, max)`, `arcPath(a0, a1, r)`, `easeNeedle(cur, target, dt, tau)`, `speedGauge(t, settings, {plane,
  collision})`, `engineGauge(t, {rpmMax})`, `dashModels(t, settings, opts)`; eski `fuelGauge`/`elecGauge` modelleri `angle` alanı kazandı, `gaugeArc` (270°)
  OSD/HUD çubukları için korunur.
- **Doğrulama:** `node tests/test_flightsim_power.mjs` (29: +6 ibre açısı, ölçek, çentik, bölge/yay yolu, yumuşatma, hız-motor-dashModels). Playwright
  sahte kip (`/tmp/flsim/gauge2/e2e_gauge2.py`, port 8731, görüntüler `/tmp/flsim/gauge2/g2-*.png`): takip panel açık/kapalı, ayrıntı, FPV, gimbal,
  serbest, sanal kumanda (panel açık/kapalı), tam ekran, 1280/1920/390 px, sarı → kırmızı → bitti, **açık tema** (panel/sade/ayrıntı/kumanda/kritik) ve
  **koyu tema** ayrı, kayıttan oynatma.

## 24. Hedefler — dairesel yörüngede sürekli uçan kinematik hedefler (`app/flightsim_targets.py`, `static/js/modules/flightsim_targets.js`, sihirbaz `flightsim_targets_ui.js`)
Kullanıcı isteği: "Uçuşa geçeceğimizde Hedefler diye bir bölüm ekle; sistemdeki dron türleri gelsin ve seçelim, hedefin uçacağı irtifa gelsin, dairesel bir yörüngede
uçsun ve bizden yörüngenin çapını sorsun. Simülasyona girdiğimizde havada sürekli uçan seçtiğimiz hedef olsun."

**Sihirbaz** (canlı kip; isteğe bağlı kart "◎ Hedefler"): en çok 8 hedef; her biri model (meta `targets.models`: hedef modelleri `tgt:*` + sistemdeki dron türlerinin
dahili modelleri `builtin:*`), irtifa (m, ev noktasına göre), yörünge çapı (m), hız (km/h; varsayılan modelin seyir hızı, üst sınır modelin azami hızı), yön (saat yönü /
tersi), yörünge merkezi (uçuş merkezinden doğu/kuzey ofset, m); ortak **önleme yarıçapı** (5–200 m, varsayılan 25). Kart altında tur süresi ve yatış açısı; sihirbaz
önizlemesinde yörüngeler ve modeller çizilir. Oturum gövdesi `targets: {items:[{model, alt_m, diameter_m, speed_ms?, dir?, east_m?, north_m?, phase_deg?, name?}], radius_m}`
(liste de kabul). Sunucu doğrulaması (`dogrula`, 400): bilinmeyen model, irtifa 10–3000, çap 50–5000, hız 1…azami, ofset ±20 km, > 8 öğe, yarıçap; ad temizlenir;
modelin görsel bilgisi (glb_url, orient, kind, model_name) öğeye gömülür → oturum yanıtı, kayıt ve kayıttan oynatma katalogdan bağımsız.

**Kinematik** (sunucu `durum` = istemci `targetState`, birebir; vektör testi): zaman t = SITL `time_boot_ms`/1000 (sahte kipte kinematik saati) → simülasyon hızı
hedefleri de hızlandırır, istemci hedefi dronun enterpolasyon oynatma başıyla (`timeline.play`) çizer (aynı gecikme), kayıtta `tt = t0 + kare t` (.bin TimeUS; önbellek v4
`t0`) aynı yörüngeyi yeniden üretir. R = çap/2, ω = v/R; cw θ = θ0 − ωt, ccw θ = θ0 + ωt; yön hız vektöründen, yatış atan(v²/Rg) (cw sağa). Yerel ENU flightsim3d ile aynı.

**3B** (`flightsim3d.setTargets`): modeller ×2,5 (dron gibi), yatış + yön, pervaneler döner (bulanık disk), ekran boyutlu etiket (ad, uzaklık, bağıl irtifa; yarıçap içinde
sarı), kesikli kırmızı yörünge çizgisi, önlemede genişleyen halka (`flashTarget`), sol üstte **radar** (burun yukarı, menzil basamağı en uzak hedefe göre). Tüm kamera
kiplerinde ve PiP'te görünür; `targetsInfo()` teşhis. Gimbal/FPV kiplerinde HUD/OSD sembolojisi (§24.5) etiketlerin yerini alır.

**Önleme** (`HedefIzleyici`; istemci eşleniği `createInterceptTracker`): ARM'lı dron bir hedefe yarıçap içine girince önleme (geçiş başına bir; çıkış 1,5×R histerezisi);
WS `{t:'target', kind:'intercept', i, name, dist_m, n, first, after_s, tt, state}` + olay şeridi "ÖNLEME · ad · m · ilk önleme N sn" (sev 5) + toast. Özet raporda
"◎ Hedefler" bölümü: önlenen hedef/toplam, toplam önleme, ilk önleme süresi (ilk ARM'dan), hedef başına yarıçap içi süre ve en yakın geçiş, **puan** (hedef başına ilk
önleme 1000 − 5·sn (≥ 200), her ek geçiş +100, ≤ 5 m +150) ve rozetler (ilk önleme, hızlı avcı ≤ 60 sn, as = tüm hedefler, yakın geçiş, avcı ≥ 5). Kayıt:
`drone_sim_runs.targets` (JSON {config, result}) + `intercept_count` (göç: ALTER; SIMUMAV shim şeması da). Kayıttan oynatmada hedefler kaydın canlı oturumundan
(bin_log_id) gelir, önlemeler istemcide yeniden hesaplanır.

**Mission Planner:** hedefler GCS'ye `ADSB_VEHICLE` olarak 2 Hz yayınlanır (kaynak sysid 1 / comp 156 MAV_COMP_ID_ADSB; ICAO 0xE0C000+i, çağrı adı `TGT<n>`, geometrik
irtifa MSL, yön/hız, SIMULATED bayrağı; yalnız GCS'ye — SITL'e gitmez) → MP haritasında trafik olarak görünür (gerçek SITL ile ölçüldü: ICAO 14729216, TGT1, 980 m).

**Hedef modelleri** (static/simumav/models, LICENSES.md; tools/icept_models_build.py): Switchblade 300 `tgt_sw300` (0,94 MB; seyir 101, atılım 161 km/h — AeroVironment
veri sayfası), ZALA Lancet-3 `tgt_lancet` (0,45 MB; seyir 80–110 → 110, dalış 300), Altius-600M `tgt_altius` (0,25 MB; kullanıcının ZIP'indeki FBX three.js FBXLoader ile;
seyir ~60 / azami ~90 km/h — kaynaklar tutarsız: bazıları knot verir, kullanıcı değeri alındı), Octopus-100 `tgt_octopus` (1,10 MB; normatif azami 300 (geliştirilmiş 360),
seyir kaynakta yok → 200 km/h seçildi: elektrikli pervaneli önleyicilerde seyir/azami ≈ 0,6–0,7). Dahili modellerin hedef hızları `BUILTIN_HIZ`.

### 24.4 Sihirbazda hedefin 3B önizlemesi (`static/js/modules/flightsim_tgtview.js`; `flightsim3d.createModelViewer`)
Kullanıcı isteği: "Simülasyonda seçilen hedefi girmeden önce 3 boyutlu olarak görelim." Her hedef kartında (HEPGO "◎ Hedefler", SIMUMAV HEDEFLER adımı) seçili modelin
dönen 3B görüntüsü: fareyle sürükle → döndür, tekerlek → yakınlaştır (0,4–4×), çift tık → sıfırla; etkileşimden 2,5 sn sonra kendiliğinden döner. Tuvalin altında
ölçek çubuğu (40–110 px'e sığan 5 cm…50 m adımı; `niceScale`) ve zemin ızgarası adımı (10 cm / 25 cm / 50 cm / 1 m — modelin boyuna göre); altında model adı,
seyir/azami hız ve **gerçek boyut** (sınır kutusu x × y × z m, ×1; uçuşta modeller ×2,5 çizilir — görünürlük).
- **Tek WebGL bağlamı:** kartlar 2B tuvaldir. Görüntü 3B katmanın model görüntüleyicisinden kopyalanır: aynı renderer'da ayrı küçük sahne (ışıklar + ızgara) →
  render hedefi (MSAA) → `readRenderTargetPixels` → `putImageData`. HEPGO'da sihirbazın dünya önizlemesinin (preview sim) renderer'ı paylaşılır; SIMUMAV hedef
  adımında başka 3B sahne olmadığından tek bir **stüdyo** bağlamı açılır (`createFlightSim3D(div, null, {studio: true})`: dünya/dron/kare döngüsü kurulmaz, tuval
  gizli) ve adımdan çıkınca / BAŞLA'da / sayfa değişiminde kapatılır. Sim dispose'u görüntüleyicileri de temizler.
- **Kare bütçesi:** tur başına (~30 fps) EN ÇOK BİR kart çizilir: etkileşimdeki kart çoğu turda, diğer görünür kartlar sırayla (IntersectionObserver; DOM'dan düşen
  kart bırakılır). Modeller anahtar başına bir kez kurulur (`buildTargetModel`; GLB hatasında delta yedeği). Kartlar yeniden çizildiğinde önizleme öğesi hedef nesnesine
  bağlı (WeakMap) taşınır — yön/sayı değişiminde görüntü sıfırlanmaz.

### 24.5 F-16 tarzı hedef sembolojisi — gimbal HUD'u ve FPV OSD'si (`static/js/modules/flightsim_tgthud.js`)
Kullanıcı isteği: "Uçarken gimbal ve FPV modundayken aynı F-16 uçaklarında olduğu gibi hedefler prizma şeklinde görünsün, HUD'un ortasından hedefe doğru çizgi
çizilsin, hedef ekrandan çıkarsa hedefin yönüne doğru tarif etsin."
- **Veri:** `sim.targetsHud()` SON render edilen ana kameranın pozunu (konum, ileri/sağ/yukarı, tan(FOV/2), en-boy; FPV'de CAM_FRAG balıkgözü `k/scale`) ve her hedefin
  **yönlendirilmiş sınır kutusunun 8 köşesini** (gövde çerçevesindeki kutu × gövde matrisi; yatış/yön dahil) dünya uzayında verir + hız, uzaklık, ΔH, yarıçap içi,
  önleme olayından sonraki 2 sn (`flash`). HUD (`flightsim_hud.js`, gimbal 'fpv') ve OSD (`flightsim_fpv_osd.js`, FPV 'pilot') her karede `ctx.targets()` ile okur,
  saf `symbology()` ekran pikseline çözer, `drawSymbology()` kendi 2B tuvaline çizer (DOM yok; HUD/OSD tuvalleri ekran kaydına girer → kayıtta ve kayıttan oynatmada da görünür).
- **İzdüşüm:** kamera uzayı xc = d·sağ, yc = d·yukarı, zf = d·ileri; ekran = 0,5 + xc/(zf·tan·en-boy)/2, 0,5 − yc/(zf·tan)/2. FPV'de görünen nokta balıkgözü tersiyle
  (`barrelScreen`: q = d·(1 + k·|d|²)·scale sabit nokta yinelemesi) — prizma görüntüdeki hedefin üstüne oturur.
- **Prizma:** 8 köşenin izdüşümünden 12 kenarlı tel kafes (perspektif; hedef döndükçe biçimi değişir). Uzakta küçülür; **en küçük boyut** 22 px × ölçek — merkez
  etrafında büyütülür (biçim korunur). Kilitsiz hedefte üstte numara, altta menzil.
- **Kilit (TD kutusu):** varsayılan **oto = en yakın hedef**; **Tab / Shift+Tab** sıradaki/önceki hedefe kilitlenir (i sırası, döngü; kilitli hedef düşerse oto).
  Kilitli hedefte prizmayı saran kare TD kutusu (en az 34 px, **dolgulu köşeler**) + veri bloğu: `T<n> <ad>`, menzil (m/km) + kapanma hızı `Vc ±m/s`
  (−d·(v_hedef − v_dron)/|d|), `ΔH ±m`. HUD ipucu satırına "· Tab: hedef" eklenir.
- **Target Locator Line (TLL):** boresight'tan (HUD W işareti / OSD merkez işareti) kilitli hedefe; TD kutusunun kenarında biter (boresight kutunun içindeyse çizilmez).
- **Ekran dışı:** hedef ekran dışında ya da kameranın arkasındaysa ekran merkezli elipsin kenarında (HUD: başlık şeridinin altında, alt çubuğun üstünde) dışa bakan
  ok + numara; kilitli hedefte dolu ok, TLL oka uzanır, yanında **sapma açısı** (boresight'tan °, 0–180) + menzil. Yön **bölmeden** (xc, −yc) alınır → arka yarım
  kürede de doğru taraf (ndc bölümü arkada işareti çevirirdi; test). Tam arkadaki hedef: aşağı ok.
- **Önleme:** hedef önleme yarıçapı içindeyse (ya da önleme olayından sonraki 2 sn) prizma ve TD kutusu yanıp söner, kutunun altında **"ÖNLEME"** (İng. INTERCEPT)
  ibaresi (ekran dışındaysa ok etiketinin altında).
- **Renk:** HUD rengi (yeşil/beyaz/amber; Shift+H) ya da OSD beyazı + siyah dış çizgi → termal/gece görüşü görüntüsünde de okunur. Araç kameralarında HUD/OSD
  sembolojiyi çizerken (son 3 sn) sahnedeki ad/uzaklık etiketleri gizlenir (tekrar etmesin); takip/serbest/yer kiplerinde etiketler sürer. PiP OSD'sine eklenmedi
  (küçük pencerede okunmaz; ana görüntü sembolojiyi taşır).
- **Maliyet:** hedef başına 9 nokta izdüşümü + ≤ 30 çizgi; DOM ölçümü yok. Teşhis: `.fs-mhud.__hud.targets()` / `.fs-osd.__osd.targets()` (kilit, ok açıları),
  `sim.targetLock`, `sim.cycleTarget(±1)`.
- **Testler:** `node tests/test_flightsim_tgthud.mjs` (izdüşüm, balıkgözü tersi, ekran dışı yön — arka yarım küre, elips kenarı, en küçük boyut, Vc, TLL kutu girişi,
  hedef seçimi, symbology bütünü, çizim duman testi; önizleme ölçek çubuğu). Görsel: `tests/tgthud_shots_hepgo.py`, `tests/tgthud_shots_simumav.py` → /tmp/tgthud-shots.

## 25. INTERCEPTOR — 4 pervaneli tailsitter (`app/flightsim_icept.py`; `drone_sitl.TIP_ESLEME['interceptor']`)
Kullanıcı isteği: "4 pervane ile dikey kalkıp havada yatay hareket ediyor, o yüzden 400 km/h hızlara çıkabiliyor; ayrı bir tür olarak INTERCEPTOR altında ekle."

**SITL:** ArduPlane 4.7.2 (yamalı) `--model quadplane-copter_tailsitter` (SIM_QuadPlane: "+" quad, kuvvetler ROTATION_PITCH_270; yerde kuyruk üstünde). Parametre seti
ArduPilot autotest `quadplane.parm` + `quadplane-copter_tailsitter.parm` + HEPGO ekleri, `varsayilan.parm`'a tip satırları olarak (`drone_sitl.tip_parm_satirlari`; kayıtlı
parametrelerden önce) + ilk kalp atışında `OTURUM_PARAMLARI`. **Tuzaklar (ölçüldü):** (1) autotest setinde `Q_TAILSIT_ENABLE` yok — ArduPlane MOTMX'ten kendisi açınca
VTOL görünümü kurulmuyor, kontrolcü motorları doyuruyor (M3 1150 / M4 1950 µs), araç **hiç kalkmıyor**; `Q_TAILSIT_ENABLE 1` açıkça yazılır. (2) RTL_ALTITUDE 20 +
AIRSPEED_CRUISE 60 (12/22 oranı) ile 110 m/s'den RTL'de TECS gazı keser → motor itkisi (copter tailsitter'da kontrol otoritesi) düşer, irtifa salınır, uçak yere vurdu
("SIM Hit ground 12,5 / 7,9 m/s"); "Airspeed sensor re-enabled" anında ani dalış. Kararlı set: RTL_ALTITUDE 100, AIRSPEED_CRUISE = 0,8 × azami, TRIM_THROTTLE 55,
ROLL_LIMIT_DEG 45, ARSPD_OPTIONS 0, THR_MIN 0 (THR_MIN 10 askıda servo3 itkisini × SIM_PLN_THR_MUL büyütüp QRTL'de sürekli tırmandırdı), Q_RTL_MODE 1.

**Kalkış/iniş:** `cmd takeoff` → GUIDED + ARM + NAV_TAKEOFF (VTOL kalkışı; ARM'dan hemen sonra "Already flying" reddi görülürse 3 sn'de bir yinelenir); pist/rampa yok
(fırlatıcı seçilmezse `launch.method` wheels: pad'den düzeneksiz; **§27 fırlatıcılar**: 4'lü / 8'li kutu, yerden tekli tüp, el fırlatıcısı + nişangâh). Yatay uçuş FBWA/FBWB/CRUISE/AUTO (geçiş ~1–5 sn), dönüş RTL → eve yaklaşınca QRTL (VTOL yaklaşma)
→ dikey iniş. Kipler: QHOVER, QLOITER, GUIDED, FBWA, FBWB, CRUISE, AUTO, LOITER, RTL, QRTL, QLAND.

**Azami hız** (`flightsim_power.thr_mul_tip`): yatayda itki = dörtlü motorlar + SIM_Plane itkisi (SERVO3; HEPGO yaması SIM_PLN_THR_MUL yalnız bunu ölçekler — tailsitter'da
**etkili**, ölçüldü). CRUISE seviye uçuş (75 m AGL, rüzgâr 0) uyumu v² = 2756 + 1572·mul → 400 km/h için mul ≈ 6,10. Varsayılan güç (INTERCEPTOR_VARSAYILAN): 111,1 m/s,
yakıt yok, 6S 8000 mAh 40 W.

**SITL ölçümleri** (DEV, yamalı arduplane 4.7.2, Ankara 900 m; `/tmp/icept-sitl/exp.py` doğrudan + `tools/sitl/dogrula_icept.py` HEPGO sunucusu üzerinden):
| Ölçüm | Sonuç |
|---|---|
| Yerde gövde (SIMSTATE) | pitch 90,0° (kuyruk üstünde) |
| Dikey kalkış 0 → 75 m (GUIDED NAV_TAKEOFF 80) | 18,7 sn (≈ 4 m/s), yatay hız ≤ 0,14 m/s, gövde pitch ort. 87,8°; ATTITUDE (VTOL görünümü) pitch −2° |
| Yatay geçiş (CRUISE) | gövde pitch < 30°'ye 4,6 sn |
| SIM_PLN_THR_MUL 1 / 4 / 7 / 10 | ~70 (FBWA, tırmanışta) / 95,1 / 117,3 m/s (CRUISE seviye) / 167 m/s (FBWA, 42 m/s tırmanışta) |
| mul 6,099 (400 km/h hedefi), CRUISE gaz %100, 60–70 sn | **108,8–111,3 m/s ort. (392–401 km/h)**, en yüksek 117,5 m/s; irtifa 79–112 m; gövde pitch −4…−8° |
| RTL (kararlı set) | 290 sn: RTL → QRTL, VTOL geçişinde ~280 m tırmanarak yavaşlar, dikey iniş (gövde pitch ort. 80°), disarm, çarpışma yok |
| Hedef ADSB | GCS'de ADSB_VEHICLE (TGT1, comp 156, 980 m MSL, 30,6 m/s) |

**Telemetri / 3B:** ArduPlane ATTITUDE'ı Q kiplerinde ve geçişte "VTOL görünümü"yle yollar (askıda pitch ≈ 0; `quadplane.show_vtol_view`). HUD/OSD bunu kullanır; 3B gövde
SITL'in gerçek yönelimi `tele.att_body` (SIMSTATE, aynı EXTRA1 tikinde — INTERCEPTOR'da `tele` yayını SIMSTATE'te) ile çizilir (`flightsim_interp` push). Gimbal/FPV
kameraları ve `getPose` askıda gövde · Rx(−90°·h) "VTOL görünümü" çerçevesini kullanır (h = burun yükselişi 30°→70°). Yerde `drone.ground` = −bbox.min.y (kuyruk).
Kayıttan oynatma: .bin `SIM` mesajı → kare `body` alanı (önbellek v4); tip `drone_sim_runs.type` (firmware adı ArduPlane der). Ses: 4 elektrik motoru (kopter modeli).
Sahte kinematik: dikey tırmanış (yatay hız 0, gövde burun yukarı), hedef irtifada yatay daire.

**Modeller** (dahili `builtin:icept_x4|p1sun|sting`; GLB'ler SIMUMAV ile ortak, HEPGO `/static/simumav/models/` yolundan yükler — kopya yok; GLB yüklenemezse prosedürel
`buildIcept`): `icept_x4` (kullanıcının STEP montajı, `tools/step_mapped2glb.py` saf Python FACETED_BREP + MAPPED_ITEM → 17 düğüm; gerçek ölçü 0,252 m; 0,60 MB),
`p1sun` (0,448 m; 0,63 MB), `sting` (0,45 m kabulü; pervaneler bağlantısız bileşenlerden ayrıldı; 1,92 MB). Pervaneler `prop_N` (göbek orijinli, gövde ekseni etrafında).
Tümü burun +X, yukarı +Y, metre; ≤ 55 k üçgen, doku ≤ 1024².

**Testler:** `tests.test_flightsim` `hedef_icept_testleri` (kinematik vektörleri, doğrulama 400'leri, izleyici histerezis/ARM/sıfırlama, puan, ADSB alanları, parm sırası,
itki uyumu, sahte INTERCEPTOR oturumu att_body/dikey tırmanış, WS `target` + olay, GCS ADSB_VEHICLE, runs.targets/intercept_count, replay tipi + hedefler, meta/modeller);
`node tests/test_flightsim_targets.mjs` (Python vektörleriyle birebir, izleyici, puan, doğrulama, radar); `tests.test_step2glb`; `tests.test_simumav_icept`.
Görsel: `tests/icept_shots_hepgo.py` (gerçek SITL), `tests/icept_shots_simumav.py` → /tmp/icept-shots.

## 26. Yer Kontrol Merkezi — istasyon + EO/radar kulesi, radar/EO ekranları ve "Yer kontrolünü koru" görevi (`app/flightsim_gcs.py`, `static/js/modules/flightsim_gcs*.js`)
Kullanıcı isteği (özet): rampanın / kalkış aracının yakınında isteğe bağlı **yer kontrol istasyonu** ve **EO + radar taşıyan kule**; radar 360° sürekli döner (kapsama
20 km), EO yakınlaştırma menzili 5 km. Uçuş öncesi RADAR / YER KONTROL İSTASYONU / ELEKTRO-OPTİK var/yok + menziller. Uçuşta **sol altta radar ekranı**, hemen
yanında **EO ekranı**; ayrı ayrı aç/kapa. Radar: 3B harita üzerinde dron + hedefler **prizma ikon**, dönen tarama hüzmesi, kapsama halkası; kapsama dışı hedef
görünmez; seçilen hedefi EO izler. Görev **"Yer kontrolünü koru"**: tamamen manuel; istasyonun yanında 10 interceptor (§25); dalgalar hâlinde rastgele mesafe/
yükseklikten hedefler istasyona dalar; önlenemeyen hedef istasyona çarparsa hasar; görev sonu başarı raporu.

**Sihirbaz** (canlı kip; "◈ Yer Kontrol Merkezi" kartı, `createSiteSection`): üç geçiş kartı (Radar · Yer kontrol istasyonu · Elektro-Optik; radar kapsama 1–50 km,
vars. 20; EO görüş menzili 0,5–15 km, vars. 5; kaydırıcı + sayı), şematik (kuzey yukarı: pist, kalkış, istasyon, kule, raf; radar/EO halkaları), **Görev senaryosu**:
Serbest uçuş · Yer kontrolünü koru (yalnız INTERCEPTOR; zorluk Kolay/Normal/Zor, dalga 1–10, interceptor 1–20 (vars. 10), önleme yarıçapı 10–100 m (vars. 30),
hazırlık 15–300 sn (vars. 45), tohum + "yeni tohum"). Görev seçiliyken istasyon zorunlu (kilitli kart). Son seçim `localStorage fs.site.wiz`.
Oturum gövdesi `site: {station, radar, radar_km, eo, eo_km}` (oturum yanıtında **`site`** — `gcs` anahtarı Mission Planner bağlantısıdır), `defend: {seed?, waves?,
interceptors?, difficulty?, radius_m?, prep_s?}`. Sunucu doğrulaması (`gcs_dogrula`, `savunma_dogrula` → 400): bilinmeyen alan, bool olmayan bayrak, aralık dışı/NaN
menzil, tam sayı olmayan dalga/interceptor, bilinmeyen zorluk, tohum 0…2³¹−1; görev INTERCEPTOR dışında 400. Tohum yoksa sunucu üretir. Meta `site` (sınırlar).

**Yerleşim** (`yerlesim(pist yönü)` = istemci `siteLayout`; yerel ENU, merkez = pad/rampa/araç başlangıcı; f ileri, r sağ): istasyon (−40 f, +55 r), kule (−40, +85),
interceptor rafı (−14, +34); hepsi pist yönüne döner. §27: kutu fırlatıcı seçiliyse raf yerine ⌈n / hücre⌉ kutu ev noktasında yan yana (raf yok); tüp/el fırlatıcısında raf yedek deposu. Prosedürel dünyada saha çevresinde ağaç yok (`opts.site`); gerçek/Google 3B'de gerçek nesnelerle çakışabilir.

**3B modeller** (`flightsim_gcs3d.js`, prosedürel, ağ isteği yok; `userData.heat` termal ipucu): **istasyon** — 20 ft askerî shelter (nervürler, köşe dökümleri, kapı,
pencere bandı, klima ünitesi + fan), çatıda uydu çanağı ve ekipman kutusu, teleskopik anten direği + kırbaç antenler, jeneratör + egzoz, beton taban (konteyner ılık
0,5, klima 0,72, jeneratör 0,86); **kule** — 18 m kafes (4 ayak, 6 kuşak çapraz bağ, merdiven), platform + korkuluk, elektronik kabini, tepede **dönen radar**
(panel dizisi, `SWEEP_S` = 4 sn/tur, ekrandaki hüzmeyle aynı açı) + ikaz lambası, platform köşesinde direk üstünde **EO top kulesi** (pan/tilt; seçili hedefe 90°/sn
dönüş hızı sınırıyla döner, hedef yoksa yavaş tarar); **raf** — beton pad + 10 yuva (sarı işaret), yuvalarda dronun kendi modeli (tailsitter, kuyruk üstünde, soğuk
0,38), konuşlandırılan interceptor sayısı kadar eksilir. Görevde isabet: turuncu parlama + sağlık düştükçe yoğunlaşan duman.

**Radar ekranı** (aynı WebGL bağlamı; PiP kalıbı — İKİNCİ BAĞLAM YOK): kule merkezli eğik (52°, kuzey yukarı) kamera; (1) sahne (arazi/bina/su; sis kapalı, hedef
etiketleri ve görev çizimi gizli, gölge güncellenmez) küçük render hedefine 8 fps (yavaş karede 4) → (2) taktik ton gölgelendiricisi (`TINT_FRAG`: yeşil-lacivert ton,
vinyet, tarama çizgisi) ile viewport/scissor kopyası → (3) AYRI radar sahnesi aynı kamerayla derinlik temizlenerek her karede: kapsama halkası + 3 kesikli ara halka
+ 12 yön çentiği, **dönen tarama hüzmesi** (8 dilimli sönen yelpaze + parlak ön kenar), **prizma ikonlar** (`buildRadarPrism`: yön gösteren üçgen prizma + beyaz kenar;
ekran boyutu sabit ~13–19 px; yere iniş çubuğu = irtifa; kendi dron camgöbeği, görev tehditleri kırmızı, §24 yörünge hedefleri turuncu, seçili sarı + nabız halkası;
parlaklık hüzme geçişinden sonra söner — `sweepGlow`). **Kapsama dışındaki hedef çizilmez** (`radarCovers`, kuleye yatay uzaklık ≤ kapsama). Ekran menzili
otomatik (`autoRadarRange`: kapsamadaki en uzak nesne %15 payla, basamaklar 1/2/5/10/20/50 km ≤ kapsama) ya da − / OTO / + ile sabit. 2B katman (`radarInfo()`):
halka etiketleri, N, kule, hedef numarası + irtifa, seçili hedefin adı, "n hedef / TEMAS YOK", hüzme açısı. **Tıklama** → en yakın ikon (≤ 22 px) → `lockTarget(i)`
(§24.5 Tab kilidiyle aynı durum; HUD TD kutusu da o hedefe geçer); boşluğa tıklama kilidi bırakır. Açıkken §24 küçük hedef radarı (sol üst) gizlenir (birleşik).

**EO ekranı**: kamera EO topunun merkezinden (0,9 m ileri, near 1 m; kule gövdesi bu geçişte gizli) seçili hedefe; oto yakınlaştırma `eoZoom` (hedef dikey kadrajın
~%40'ı; FOV 48°…0,35° → ×1…×137, yumuşak); **menzil dışı** (eğik mesafe > EO menzili) → geniş açı + parazit + "MENZİL DIŞI · r > 5 km"; hedef yokken "HEDEF
SEÇİLMEDİ" + yavaş tarama; dönüş sürerken "YÖNLENİYOR". Kamera türü gündüz / termal / gece (◐ düğmesi; §22.3 `CAM_FRAG`, kendi türü — `setCamUniforms(…, typeOverride)`;
tercih `fs.site.eoType`), 15 fps (yavaş karede 7,5). OSD: köşe parantezleri, nişangâh, iz kutusu, `İZ · n ad`, AZ / EL / MZL, FOV. Teşhis `eoInfo()`.

**Yerleşim (DOM, `createSiteScreens`)**: sol altta dok (alt çubuğun 10 px üstü; sanal kumandada çubukların üstü) — [görev şeridi] + [RADAR | EO] (304×204; < 1280 px
268×182; < 900 px 230×158). Başlıkta simge + metin + düğmeler (menzil / tür / ×). Alt çubukta **Radar (Y)**, **EO (U)** (SVG simgeli; tercih `fs.site`). Dok
açıkken: MP / kayıt bilgisi kutusu ve Google atfı dokun üstüne çıkar (`--fs-site-top`), güç kadranları ve olay şeridi dokun sağındaki boşluğun ortasına kayar
(`--fs-site-r`; panel açıkken ×0,68), PiP dok engelini tanır (`pipObstacleInsets`), askeri HUD / FPV OSD sol alt satırları dokun üstüne çıkar.

**"Yer kontrolünü koru"** (`SavunmaGorevi`; istemci eşleniği `createDefendTracker`, kayıtta `defendStateAt`):
- **Plan** (`savunma_plani` = `defendPlan`, **mulberry32** — Python/JS bit düzeyinde aynı; vektör testi): dalga w başı = hazırlık + w·aralık (kolay 90 / normal 70 /
  zor 55 sn), tehdit sayısı min(8, n0 + w) (n0 1/2/3), dalga içi doğuşlar 8–16 / 5–12 / 3–9 sn arayla; model Switchblade 300 · Lancet-3 · Altius-600M · Octopus-100;
  kerteriz 0–360°, uzaklık 2,5–4,5 / 3–6 / 3,5–8 km (her dalga +%4), irtifa 120–350 / 150–450 / 150–600 m, dalış açısı 25–50°, seyir hızı model seyir × zorluk
  (0,85/1/1,15) × (1 + 0,05w) (≤ azami), dalış hızı azami × min(1, 0,85 + 0,05w); hasar 15 / 35 / 25 / 20 (istasyon 100). En çok 60 tehdit.
- **Kinematik** (`tehdit_durum` = `threatState`): seyir sabit irtifada istasyona doğru → dalış başlangıcından (yatay h/tan(dalış)) istasyon çatısına (2,6 m) düz
  çizgi; çarpma anı t_impact. Önlenen tehdit istemcide balistik + takla ile düşer (`fallState`, ≤ 8 sn).
- **Önleme**: ARM'lı interceptor tehdide `radius_m` içine girerse önleme (tehdit yok olur; olay: istasyona uzaklık, önleme süresi, interceptor no). **Sızma**:
  t ≥ t_impact → sağlık − hasar. **Bitiş**: sağlık 0 (başarısız) ya da tüm tehditler çözüldü (sağlık ≥ %50 → başarılı, aksi başarısız).
- **Görev saati**: tm = taban + tbm/1000 (SITL saati; simülasyon hızıyla hızlanır). SITL yeniden başlayınca (tbm geri) taban önceki bölümün son saatini ekler →
  saat kesintisiz; yeniden açılış sürerken senaryo bekler (adil, deterministik).
- **İnterceptor değişimi — karar**: aynı SITL aracı aynı oturumda **yeniden konuşlandırılır** (`cmd defend {action:'next'}` ya da görevde "Sıfırla" → mevcut
  `reset` yolu: SITL aynı ayarlarla yeniden başlar, araç pad'de kuyruk üstünde doğar; MP aynı adreste, WS/kayıt sürer). Gerekçe: 10 ayrı SITL ya da oturum yenileme
  bellek/CPU/port/MP bağlantısı/kayıt bölünmesi açısından ağır ve kırılgan; reset yolu zaten test edilmiş. Yalnız **ARM edilmiş** interceptor harcanır; raf boşsa
  400 "İnterceptor kalmadı". Yeni araç için güç durumu taze (batarya dolu; simülasyon hızı korunur). Çarpışma (`zorla_disarm`) ya da batarya bitişi →
  WS `down` + kırmızı olay + şeritte yanıp sönen "▶ Sıradaki interceptor (N)".
- **WS** `{t:'defend', kind: wave|spawn|kill|leak|down|next|end, …, tt (görev saati), state}`; `state` = `{t, base, health, wave, waves, icept{total, used, lost, down},
  remaining, killed[[k, t]], leaked[[k, t]], spawned, total, ended}`; oturum/hello `defend: {config, plan (görsel bilgiyle), station, state}`.
- **Puan / rütbe** (`savunma_puan` = `scoreDefend`): önleme başına 300 + istasyona uzaklık/10 (≤ 400) + max(0, 200 − önleme süresi); sızma −250; sağlık ×10;
  kullanılmayan interceptor ×100; başarı +1000; ≥ 0. İsabet = önlenen / doğan; rütbe 0,65·isabet + 0,35·sağlık/100 → Er · Onbaşı · Çavuş · Teğmen · Yüzbaşı ·
  Binbaşı · Albay.
- **Uçuşta**: şerit (YER KONTROLÜNÜ KORU · DALGA w/n · Hazırlık / Sonraki dalga mm:ss · İSTASYON sağlık çubuğu · INTERCEPTOR rafı (kullanılmış / aktif / düşmüş /
  hazır) · ✓ Önlenen · ✗ Sızan · ◎ Aktif tehdit · ▶ Sıradaki interceptor (N)), ortada bant (DALGA n · m TEHDİT, TEHDİT ÖNLENDİ, İSTASYON VURULDU −d,
  INTERCEPTOR KAYBEDİLDİ, GÖREV BAŞARILI/BAŞARISIZ), olay şeridi; tehditler sahnede (modeller tembel kurulur), HUD/OSD prizmalarında ve radarda; Tab / radar
  tıklaması ile kilit → EO izler.
- **Görev sonu raporu** (`defendReportBody`; bitişte otomatik pencere + "Bitir"): sonuç, tohum/zorluk, rütbe nişanı, puan; karolar (önlenen/doğan, kaçan, istasyon
  sağlığı, kullanılan interceptor, isabet, ortalama/en hızlı önleme, ulaşılan dalga); zaman çizelgesi (sağlık basamakları, önleme ▲, sızma ▼, dalga başları);
  önleme tablosu. Özet rapor (`/summary`, Bitir modalı, `/reports`) `site` + `defend` taşır; metin paylaşımına satır eklenir.
- **Kayıt**: `drone_sim_runs.targets` JSON'una `site` + `defend {config, result}` eklenir (**DB göçü yok**). Kayıttan oynatma (`ReplaySession._site_dict`): canlı
  oturumun pist yönüyle yerleşim, plan tohumdan yeniden üretilir, şerit ve olaylar kayıt saatiyle sonuçtan (ilk SITL bölümü; yeniden konuşlandırma sonrası
  bölümler ayrı .bin'dedir).

**Testler**: `tests.test_flightsim gcs_testleri` (doğrulama 400'leri, yerleşim, radar/EO, mulberry32 vektörleri, plan determinizmi/sınırları, kinematik, önleme/sızma/
bitiş, konuşlandırma + görev saati tabanı, puan/rütbe, sahte kipte oturum: site/defend alanları, WS wave/leak/end (`t` çerçeve türü korunur, kayıt zamanı `tt`),
`defend next`, reset = konuşlandırma, özet, `drone_sim_runs.targets`, kayıttan oynatma, meta); `node tests/test_flightsim_gcs.mjs` (12; Python vektörleri birebir).
Görsel: `tests/gcs_shots_hepgo.py` (→ /tmp/gcs-shots/hepgo-*.png; `GCS_REAL=1 HEPGO_SITL_DIR=/opt/hepgo/sitl/bin` gerçek SITL).
**Sınırlar**: tek SITL aracı (aynı anda tek interceptor); sahte kipte (HEPGO_SITL=0) dron sabit dairede uçar (önleme kendiliğinden olabilir); `?mock=1` istemci
kipi sahayı/görevi kurmaz; görüş hattı (arazi örtmesi) hesaplanmaz; radar terrain'i yüklü dünyayı gösterir (prosedürel dünya dışı koyu zemin).

## 27. INTERCEPTOR fırlatıcıları — 4'lü / 8'li kutu, yerden tekli tüp, el fırlatıcısı + nişangâh ekranı (`static/js/modules/flightsim_launcher*.js`, `flightsim_scope_ui.js`, `app/flightsim_launcher.py`)
Kullanıcı isteği (birebir): "INTERCEPTOR içinde fırlatıcı olarak 4'lü, 8'li, yerden tekli, pilot elindeki bir silah benzeri aparattan çıkmalı; eğer böyle bir aparatı
seçerse aparatın üstünde küçük bir ekran olmalı, ekranda havaya doğru havadaki hedefleri görmeli."

**Yöntemler** (`world.launch.method`; yalnız INTERCEPTOR'da etkin, sabit kanat §13 yöntemleri değişmedi): `pod4` (2×2 dikey hücreli kutu) · `pod8` (4×2) · `tube`
(üç ayaklı sehpada tek dikey tüp) · `handheld` (pilotun omzundaki silah benzeri el fırlatıcısı + nişan biriminin üstünde küçük EKRAN). Ek alanlar: `loaded` (dolu
hücre 1…hücre; görevsiz uçuşta), `aim_az_deg` (0…360, gerçek kuzeyden) ve `aim_el_deg` (10…85°) — el fırlatıcısı nişanı. `method` yoksa / `wheels` ise
INTERCEPTOR eskisi gibi pad'den düzeneksiz kalkar (eski gövdeler ve CAYSIM aynen).
- **Sunucu doğrulaması** (`launch_dogrula` + `flightsim_launcher.ek_alanlar`; 400 `invalid`): bilinmeyen yöntem, `loaded` tam sayı değil / 1…hücre dışında, `aim_*`
  sınır dışı ya da sayı değil (bool/dize). Fırlatıcı yönteminde eksikler varsayılanla dolar (`loaded` = hücre sayısı, nişan 0° / 55°); sabit kanat gövdesi
  değişmedi (alan verilmedikçe çıktı aynı). `launch_normalize`: sabit kanat yalnız wheels/ramp/vehicle, INTERCEPTOR yalnız fırlatıcılar (yoksa `wheels`), diğer
  tipler `wheels`; fırlatıcı olmayan yöntemde fırlatıcı alanları atılır. `cmd takeoff {alt, aim?: {az_deg, el_deg}}` (aim yalnız sınır denetimi; el fırlatıcısında
  oturumun nişanını günceller → WS `launch` olayı nişanı taşır, geç katılan izleyici `session.launch`tan görür).
- **SIMUMAV** (`bridge.launch_dogrula`, `routers/fly.py LaunchIn`): aynı yöntemler + `loaded` (1…8; hücre sınırı köprüde), `aim_az_deg` 0…360, `aim_el_deg` 10…85 —
  yalnız SINIRLAR, dron tipi zorlaması yok (çekirdek `launch_normalize` tipe göre ayıklar). `flights.launch` metin sütunu yöntem adını saklar (CHECK yok → **DB
  göçü gerekmez**), `snapshot.launch` tam nesne. Sihirbaz: INTERCEPTOR'da "Kalkış yöntemi" adımı fırlatıcı kartlarına dönüşür (ayrı durum `ilaunch`; sabit kanat
  `launch` durumu etkilenmez), adımda düzenek önizlemesi döner.

**Kalkış dizisi** (`SimSession._icept_kalkis`; gerçek SITL ArduPlane 4.7.2 `quadplane-copter_tailsitter`): GUIDED + ARM → WS `launch{phase:'armed'}` → NAV_TAKEOFF
→ `launch` (kapak açıldı; görevde `cell` = ateşlenen hücre sırası) → AGL ≥ 1,5 m `released`. Kutu/tüp: dikey NAV_TAKEOFF hedef irtifaya (askıda bekler).
El fırlatıcısı: NAV_TAKEOFF **8 m** → **QHOVER + RC yaw ile VTOL görünümü yönü nişan azimutuna** (|hata| < 6°; en çok 7 sn) → GUIDED + **MAV_CMD_DO_REPOSITION**
nişan noktasına (`aim_noktasi` = istemci `aimWaypoint`, vektör testli: nişan ışınında 500 m yol, irtifa 30…350 m, yatay ≥ 120 m) → ArduPlane sabit kanada
geçer ve nişan doğrultusunda uçar, noktada loiter. *Gerekçe (ölçüldü):* tailsitter askıda iken geçiş, ATTITUDE'daki "VTOL görünümü" yönünde olur (bu oturumda
askı yönü 49°); doğrudan DO_REPOSITION ile 120° nişanda çıkış kerterizi 48,9° (71° sapma) ölçüldü. GUIDED askıda `MAV_CMD_CONDITION_YAW` etkisiz (yön
değişmedi); Euler/SIMSTATE yaw burun yukarı (pitch ≈ 90°) iken anlamsız sıçrar, doğru ölçüt ATTITUDE yaw'ıdır. QHOVER'da RC yaw ~50°/sn döndürür, gaz orta
irtifayı tutar (20 m ± 0,2). Sahte kinematik (`HEPGO_SITL=0`) nişan ışını boyunca tırmanır (yatay hız = tırmanma / tan(el), gövde nişan açısında).

**Gerçek SITL ölçümleri** (DEV, yamalı arduplane 4.7.2, Ankara 900 m, rüzgâr 0; `tools/sitl/dogrula_launcher.py` HEPGO sunucusu + pymavlink GCS):
| Senaryo | Sonuç |
|---|---|
| 4'lü fırlatıcı, takeoff 50 m | `launch` 1,6 sn · `released` 3,7 sn; 45 m'ye 12,7 sn; tırmanışta azami yatay hız **0,15 m/s**, gövde pitch ort. 87,9°; yatay kayma 0,7 m; askıda irtifa **50,0–50,2 m**; ARM sürdü, çarpışma yok |
| El fırlatıcısı, nişan az 120° / el 30° | `released` 3,2 sn; QHOVER yön hizalama → GUIDED; evden 40 m uzaklaşmada **çıkış kerterizi 112,0° (sapma 8°)**, 10,2 sn; t = 15 sn 93,7 m/s, 209 m; nişan noktasına en yakın 58 m; noktada loiter (irtifa 250 m'ye oturur); ARM sürdü, çarpışma yok |
| (düzeltme öncesi) aynı nişan, doğrudan DO_REPOSITION | çıkış kerterizi 48,9° (askı yönü), sapma 71° → hizalama eklendi |

**Hücre envanteri** (saf `cellStates`): durumlar `spent` (ateşlendi; kapak açık, dip isli, LED kırmızı) · `active` (sıradaki; kapak açık, dron hücrede, LED amber —
ARM'da yanıp söner, çıkınca kırmızı) · `loaded` (dolu; kapak kapalı, LED yeşil) · `empty` (yüklenmemiş; açık, kırmızı). Ateşleme sırası: fırlatıcı 0'ın hücreleri
(arka sıra soldan sağa, sonra ön sıra), sonra fırlatıcı 1 … Ön yüzde dil bağımsız sayaç plakası (▮▮▯▯ `2/4`). Görevsiz uçuşta `loaded` dolu hücre, etkin hücre
ilk hücre (her "Sıfırla"da aynı hücreye yeniden oturur).
**"Yer kontrolünü koru" ile envanter — tasarım ve gerekçe:** görevin interceptor sayısı (1–20) TEK envanterdir; fırlatıcı sayısı türetilir. Kutularda
**⌈n / hücre⌉ kutu** yan yana kurulur (`bankLayout`; sıra merkezi = SITL evi), son kutu kısmen dolu, **10'lu raf kurulmaz** (`rackCountFor` = 0); etkin hücre =
`icept.used` (§26 sayaç; "Sıradaki interceptor" → sonraki hücre, WS `defend next` ile `launcherUi.sync`). Tüp ve el fırlatıcısında fırlatıcı tektir, raf
**yedek deposu** olarak kalır (sayım §26 ile aynı). *Neden:* (1) görev puanı/raporu ve sunucu mantığı (`SavunmaGorevi.icept`) değişmeden kalır — fırlatıcı yalnız
görsel envanter katmanıdır; (2) SITL aracı her konuşlandırmada AYNI ev noktasında yeniden doğar (§26 kararı); hücreler arası mesafe görsel bir ofsettir ve
`released` ofset sönümüyle (§13: yatay 3 sn / AGL 15 m) kapanır — her hücre için ayrı ev (SITL'i yeni konumla yeniden başlatma) MP bağlantısı/kayıt bölünmesi
açısından gereksiz yük; sıra ev noktasında ortalandığından en uzak hücre 20 interceptor/4'lü için ~10 m (ölçekli) kayar; (3) kutu sayısı envanterden türediği için
"dolu hücre" ile görev sayısı çelişemez (görevde sihirbazın dolu hücre ayarı yok sayılır, kartta not).

**3B** (`flightsim_launcher3d.js createIceptRig`; `flightsim_launch.createLaunchRig` ile aynı arayüz — anchor/needsAnchor/resurface/update/setPhase/carrying —
+ `carryPose`, `setInventory`, `setAim`, `scopePose`, `screenPose`, `focus`). Ölçüler dronun GERÇEK boyutundan (`cellDims(fit)`: hücre iç genişliği açıklığın
~%112'si, derinlik boyun %92'si — burun ağız hizasında; tüp yarıçapı açıklığın ~%60'ı) ve dron gibi ×MODEL_SCALE.
- *Kutu:* kızaklı kaide + ayaklar + forklift cepleri, nervürlü dış duvarlar, hücre ızgarası (iç bölmeler), üst çerçeve, köşe kaldırma halkaları, sarı-siyah ikaz
  şeridi, kablo kutusu; her hücrede arka kenardan menteşeli kapak (X nervürlü, ikaz bandı; 0,6 sn'de 110° açılır), LED, hücre dibi. *Tüp:* üç ayaklı sehpa,
  taban bileziği, çift cidarlı tüp + bilezikler + boyuna nervürler, menteşeli kapak, kontrol kutusu + LED. *El:* pilot (bot, diz koruyucu, kalça/kemer, gövde,
  yelek + cepler, telsiz, sırt çantası, boyun, baş, kask + gözlük) ve omzunda sekizgen tüp (bilezikler, ağız bileziği, kırılabilir ağız kapağı — sarı X kesimli, fırlatmada
  parçalanır —, ikaz şeridi, omuz yastığı, tabanca kabzası + tetik korkuluğu, ön kabza) + tüpün solunda, gözün önünde **nişan birimi** (lens, düğmeler, LED, güneşlik) ve göze bakan **EKRAN**. Pilot nişan azimutuna
  döner, tüp yükselişe kalkar (dik nişanda gövde hafif geriye), kollar iki parçalı (basit IK: dirsek aşağı/dışa) ellere yeniden kurulur.
- *Dron düzenekteyken:* burun ekseni hücre/tüp ekseni, kuyruk tabanda (`carryPose`: yuva + burun × `drone.ground`); `launch` aşamasında SITL tırmanışı kadar
  eksen boyunca çıkar; `released` → §13 ofset sönümü (gösterilen z düşmez). Fırlatma anı: ağızda turuncu parlama (0,3 sn) + 18 duman sprite'ı (sürtünmeli
  yayılım, ılık yükselme); el fırlatıcısında yarısı **arka uçtan geri tepme dumanı**, tüp 0,3 sn geri teper. Termal: pilot 0,9 (sıcak), ekran 0,7, kutu 0,45.
- *Sihirbaz önizlemesi:* Kalkış adımında kamera düzeneğin çevresinde tur atar (`setPreviewFocus('rig')`; §13 rampa/araç da yakından görünür).

**Nişangâh** (yalnız el fırlatıcısı; TEK WebGL bağlamı — İKİNCİ BAĞLAM YOK): `flightsim3d renderScope` lensten nişan yönüne (az, el; yuvarlanma yok; FOV 40° /
zoom ×1·2·4·8) küçük render hedefine çizer (düzenek ve tüpteki dron gizli; hedef etiket sprite'ları ve görev çizimi gizli). Aynı doku (1) aparatın **3B ekranına**
(MeshBasic harita; ana kamera aparata < 80 m iken 6 fps) ve (2) **NİŞANGÂH penceresi** açıksa viewport/scissor kopyasıyla ana tuvale (20 fps; yavaş karede 10)
gider. 3B ekranın sembol katmanı 2B tuvalde → CanvasTexture: F-16 tarzı semboloji (§24.5 `symbology/drawSymbology`: prizma, TD kutusu, menzil · Vc · ΔH, ekran
dışı hedefe kenar oku + sapma açısı), artı, AZ/EL, zoom ve hedef sayısı. Kilit: elle (Tab / radar) yoksa **nişan çizgisine en yakın hedef** (en küçük sapma).
- *Pencere* (`flightsim_scope_ui.js createLauncherUi`; HEPGO + SIMUMAV ortak): sürüklenebilir (başlıktan; konum `fs.scope.pos`), varsayılan solda küçük hedef
  radarının altı; 2B katman: köşe çerçeve, azimut şeridi (10° çentik, 30°'de N/E/S/W ya da sayı), yükseliş ölçeği, mil-dot artı, semboloji, okuma
  (`AZ 123° EL 45° ×2`), hedef sayısı, durum (HAZIR / ARM / ATEŞLENDİ). Alt bant: ◀▲▼▶ basılı tutulan nişan düğmeleri (sanal kumanda / dokunmatik), ipucu,
  **▲ Fırlat** (konağın kalkış penceresi; `takeoffExtra()` nişanı `cmd takeoff`a ekler). Alt çubukta **⌖ Nişangâh (G)**; tercih `fs.scope.on`. §17 ekran
  kaydında görüntü (ana tuvalde) ve 2B semboloji katmanı (`overlay()`, PiP OSD kalıbı) birlikte kaydedilir.
- *Nişan alma:* pencerede sürükle (fare-bakış; px → derece FOV'a göre), **I/K** yükseliş · **J/L** yön (50°/sn, 35°/sn; Shift ×¼), **Z** / tekerlek zoom, **H** /
  ⌖ / çift tık "hedefe yönel" (kilitli ya da en yakın hedefe `aimAt`), **Tab** hedef kilidi (§24.5). Nişan 3B'de pilotu/tüpü anında döndürür.
- Teşhis: `sim.launcherInfo()` → `{method, phase, aim, inventory{total, used, launchers, loaded, spent, empty, active}, cells, puffs, scope, scopeRenders, zoom,
  screen{x,y,z,nx,ny,nz}}`, `sim.scopeHud()`, `sim.rigFocus`, `sim.getAim()/setAim()/aimAtTarget()`, `sim.setScopeZoom()`.

**Kayıt / kayıttan oynatma:** `drone_sim_runs.launch` (mevcut JSON sütunu) yöntem + `loaded` + nişanı saklar (**DB göçü yok**). Kayıttan oynatmada istekte fırlatıcı
seçilmediyse canlı oturumunki kullanılır (`ReplaySession`); log listesi (`/api/drone/sim/logs`) simülatör kaydının tipini (`interceptor`) ve `sim_launch`'ı verir →
sihirbaz kayıt kipinde Kalkış adımında fırlatıcı kartlarını açar ve kayıttaki fırlatıcıyı önerir. Aşamalar logdan (`replayLaunchTimeline`: ilk hareket → `launch`,
AGL > 1,5 m → `released`).

**Testler:** `node tests/test_flightsim_launcher.mjs` (13: yöntem listeleri, nişan normalize/vektör, nişan noktası — Python vektörleri birebir, aimAt, nişan adımı/
sürükleme, hücre yerleşimi, envanter durumları, görev kutu/raf sayısı, nişangâh izdüşümü, semboloji (göğe bakarken hedef kutusu / arkadaki hedefe ok), azimut
şeridi, etiket + kayıt aşamaları); `tests.test_flightsim firlatici_testleri` (doğrulama 400'leri, normalizasyon, aim vektörleri, sahte kipte pod4/el aşamaları +
nişan yönünde tırmanış, aim 400'leri, runs.launch, kayıttan oynatma + log listesi, görevde hücre sırası); `node tests/test_flightsim_wizard.mjs`;
`node tests/test_simumav_fly.mjs` (ilaunch); `tests.test_simumav_icept` (422'ler, flights.launch, WS takeoff{aim} aşamaları, pod8 loaded).
Görsel: `tests/launcher_shots_hepgo.py` (→ /tmp/launcher-shots; `LAUNCHER_REAL=1 HEPGO_SITL_DIR=…` gerçek SITL; `SHOTS=wizard,pod4,tube,hand,defend`).
**Sınırlar:** SITL'de hücre/tüp fiziği yok (araç her zaman ev noktasında yerde, kuyruk üstünde doğar; düzenek görseldir); el fırlatıcısında SITL 8 m dikey + yön
hizalama (~1–3 sn) sonra sabit kanada geçer — 3B'de tüpten nişan açısıyla çıkış ofset sönümüyle SITL yoluna bağlanır; nişan noktasında 90+ m/s ile loiter geniş
dairedir (pilot devralır); `?mock=1` istemci kipi aşamaları zamanlayıcıyla taklit eder.
