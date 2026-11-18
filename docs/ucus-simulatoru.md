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
| `/presets…` | §27 Kayıtlı Simülasyonlar: liste, pilotlar, oluştur/güncelle/sil, `POST /presets/{id}/start` (kayıtlı gövdeyle oturum) |
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
- **§31 (güncel):** arazi 6 oktav fbm + alan bükme + çok-fraktal sırt gürültüsü, yükseklik/eğime göre doku karışımı, ufuk halkası, gökyüzü kubbesi, bulut,
  hava durumu, ağaç türleri + LOD, kasaba/bina cephesi, rüzgâr tulumu/akış çizgileri — ayrıntı §31; aşağıdaki iki satır ilk sürümün tanımıdır.
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
- Performans: 60 fps hedef (§31: orta düzey dizüstünde ≥ 45 fps); prosedürel arazi 320×320 + 128×128 ufuk halkası, gerçek kipte 256×256 + 192×192 "uzak arazi" halkası (§9); ağaç ≤ 20.000 örnek, parçalı InstancedMesh + LOD (§31).
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
Altbilgi: **İptal et** · gerekçe metni · **‹ Geri** · **İleri ›** (son adımda **Kaydet** + yanıp sönen **Uç** — §27 / kayıtta **▶ Oynat**). Klavye: **Enter = İleri** (son adımda
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
- §27 Kayıtlı Simülasyonlar: `node tests/test_flightsim_saved.mjs`, `tests.test_flightsim preset_testleri`, görsel `./.venv/bin/python -m tests.saved_shots_hepgo` (ayrıntı §27).
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
Kullanıcı sihirbazda **Kip › Kayıttan oynat** seçer: **simülatörün kendi kayıtları** (flight_logs; analizi TAMAM; `.bin` / `.log`
DataFlash ya da `.tlog` MAVLink; saha görevi logları ve bağımsız gerçek loglar listelenmez — §8.5) listelenir (ad, tarih, dron, pilot, konum, görev kodu, süre, boyut; arama), biri seçilir, dünya
ayarlanır, **Oynat**. Kontrol kullanıcıda değildir: SITL ve UDP açılmaz, komut düğmeleri yoktur; kayıt 3B dünyada aynen oynatılır.
- **Yetki:** oturum `drone.sim` yazma izni; simülatör kayıtları `drone.sim` erişimiyle görünür (`meta.replay.logs_allowed=true`); gerçek loglar
  ("Simüle et" girişi, `?id=`) flightlogs yetkisiyle kesişir (`tools` → tüm loglar, `field` → yalnız göreve bağlı loglar; `meta.replay.real_allowed`).
- **Uçlar:** `GET /api/drone/sim/logs?q=&id=` → `[{id, file_name, ext, size, uploaded_at, aircraft, pilot, location, task_code, vehicle,
  type, flight_s, duration_s, takeoff_utc, start_utc, home_lat, home_lon, cached, source, origin, sim}]` (`origin` SIM | REAL — §19; `sim` simülatör
  kaydı mı; `id` yoksa yalnız `sim=true` satırlar) · `POST /runs/{id}/replay` (§8.5, kaydı doğrudan izle) · `POST /sessions {mode:'replay', log_id, world}` →
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

### 8.4 Uçuş logu ANALİZİ — hızlı okuyucu + alt süreç + kuyruk (`app/flightlog.py` `analyze`, `app/flight_analysis.py`)
Kalan sorun (§8.3 sonrası): .BIN/.tlog **yüklenince** çalışan analiz (Araçlar › Uçuş Logu Analizi, saha uçuşu logu, dron köprüsü, §19 simülatör
kaydı — hepsi `flight_analysis.start`) pymavlink ile **sunucu sürecinin içinde** (iş parçacığı, GIL) çalışıyordu: 754 MB'lık logda 134 sn,
sunucu RSS 2,5 GB, API gecikmesi ortalama 0,4 sn / en çok 3,3 sn (aynı makinede 7 firma servisi).
- **Hızlı analiz (`flightlog._analyze_hizli`):** ikili DataFlash'ta `dataflash.oku(kesin=True, ofs=True, tanimsizda_dur=True)`; metin `.log`
  pymavlink'te kalır (`.tlog` → §8.6) (`_analyze_pymavlink`, eski kod aynen — yalnız ilerleme geri çağrısı eklendi). Sonuç eski analizle **BİREBİR aynı JSON**:
  - `kesin`: değerler pymavlink ile bit bit aynı — tamsayı biçimler int64 (Python int → JSON'da `21`, `21.0` değil; `M` işaretli), `f/g/d` float64,
    `c/C/e/E/L` = float(ham) / 100 ya da 1e7 (pymavlink bölme sırası). Metinler pymavlink gibi önce tüm alan çözülür (UTF-8, olmazsa ISO-8859-1)
    sonra NUL'da kesilir (`_metin`; NUL sonrası çöp UTF-8 değilse tüm metin ISO-8859-1).
  - `ofs`: '_ofs' (mesajın dosya konumu) — tipler arası sıra gereken yerler: t0 (ilk mesaj), BAT+CURR ve XKF2+NKF2 birleştirme, POS'tan
    önceki BARO irtifası. `'ARSP' in log.messages` pymavlink'te indeksleme sırasında dolar → "logda hiç ARSP yoksa CTUN.As".
  - `tanimsizda_dur`: pymavlink indeksleyicisi (init_arrays / dfindexer) FMT'si görülmemiş tipli geçerli bir `A3 95` başlığında **okumayı bitirir**
    ("unknown msg type" → break); analiz de orada biter (3B oynatma okuyucusu varsayılanda toleranslı kalır: 1 bayt ilerler).
  - Ortalama/RMS Python `sum` ile aynı sırada, en büyük/en küçük Python `max/min` ile (ilk eşit eleman, NaN davranışı), `math.hypot` /
    haversine Python'da (numpy ikili toplam ve SIMD sin/hypot son bit farkı olmasın); seyreltme `_thin` ile aynı indeksler.
- **Alt süreç (`python -m app.flightlog analyze <log> <çıktı.json> <ebeveyn pid>`):** `nice` (FLIGHTLOG_ANALIZ_NICE, 10), bellek tavanı
  `RLIMIT_AS` (FLIGHTLOG_ANALIZ_BELLEK_MB, 3072; aşılırsa MemoryError → HATA "Analiz bellek sınırını aştı"), BLAS tek iş parçacığı,
  `PR_SET_PDEATHSIG` (sunucu ölürse çocuk da ölür; yetim süreç kalmaz). İlerleme stdout'ta `P <yüzde>` (okuma 0–90, hesap 90–100), hata
  `ERR <mesaj>`, çıktı atomik yazılır (`<log>.analiz.json`, sunucu okuyup siler).
- **Kuyruk (`flight_analysis`):** `start(id)` yalnız kuyruğa ekler (istek beklemez); FLIGHTLOG_ANALIZ_PARALEL (1) kalıcı işçi iş parçacığı
  alt süreçleri çalıştırır. `flight_logs.progress` (yeni sütun; 0…100, NULL = sırada) en çok saniyede bir yazılır; `durum()` bellekteki
  ilerleme + kuyruk sırası → `GET /api/tools/flight-logs` ve `GET /api/flight-logs/{id}` yanıtlarında `progress`, `queue`. Zaman aşımı
  FLIGHTLOG_ANALIZ_ZAMAN_ASIMI_S (3600) → süreç öldürülür, HATA. Durumlar: ISLENIYOR → TAMAM | HATA (hurda/görev tamamlama yan etkileri aynı).
- **Yeniden başlatma:** `resume_pending` (açılış) ISLENIYOR'daki her kaydın `progress`'ini NULL yapar ve **baştan** kuyruğa alır (yarım çıktı
  dosyası üzerine yazılır); ISLENIYOR'da takılı kayıt kalmaz.
- **Arayüz (`tools.js`):** liste Durum sütununda ilerleme çubuğu (`analysisProgress`) ya da "Sırada (n.)"; analiz sürerken liste 2 sn'de bir
  tazelenir. Rapor sayfası ISLENIYOR iken ilerleme çubuklu kart, 1,5 sn'de bir güncellenir, bitince rapor kendiliğinden açılır.
- **Ölçümler (DEV; PROD log #6 kopyası `13.10.26_565km_700m.BIN`, 754 MB; sunucu ayrı süreçte, analiz sırasında 0,2 sn'de bir API isteği):**

  | | Önce (iş parçacığı, pymavlink) | Sonra (alt süreç, akış okuyucu) |
  |---|---|---|
  | Analiz süresi | 134,5 sn (bağımsız: 122 sn) | **9,9 sn** (bağımsız: 9,1–9,5 sn) |
  | Sunucu süreci tepe RSS | 2.497 MB | **204 MB** (boşta 152 MB) |
  | Analiz süreci tepe RSS | — (sunucunun içinde) | 484–506 MB (ayrı süreç, nice 10) |
  | API gecikmesi analiz sırasında (ort. / en çok) | 376 ms / 3.349 ms | **35 ms / 277 ms** |
  | Sonuç | — | eski analizle birebir aynı JSON |

  Diğer gerçek loglar (eski → yeni, hepsi birebir aynı): 491 MB 85,6 → 5,9 sn · 439 MB 72,3 → 4,4 sn · 275 MB 48,0 → 2,8 sn · 253 MB 43,7 → 3,4 sn ·
  SITL kayıtları 253 MB 44,4 → 2,4 sn, 4,0 → 0,5 sn.
- **Testler:** `tests/test_binanalyze.py` (eşdeğerlik: gerçek örnek + 3 sentetik varyant — Plane/eski Copter/ThrOut tamsayı, bozuk bayt, sahte
  başlık, ortada FMT, tanımsız tip; isteğe bağlı gerçek loglar `BINANALYZE_GERCEK=yol1:yol2`; CLI ilerleme/nice/RLIMIT_AS/PDEATHSIG/bellek;
  kuyruk + ilerleme API; yeniden başlatma; bozuk dosya / zaman aşımı / bellek tavanı → HATA). Görsel: `tests/binanalyze_shots.py`
  (yükleme → rapor sayfasında ilerleme → listede ilerleme + "Sırada (1.)" → rapor; `BINANALYZE_KOD=<eski worktree> BINANALYZE_GORSEL=0` ile "önce" ölçümü).

### 8.5 Kayıttan oynatma girişleri — kaydı doğrudan izle · yalnız simülatör kayıtları · "Simüle et"
Kullanıcı isteği: *"Bir oturumu kaydediyorum, sonra tekrar izlemek için Başlat dediğimde tekrar tekrar rampasını falan soruyor. Direkt izlemeye
geçmesi ve o oturumda hangi ayarlarla uçtuysak o ayarlarla getirmesi gerekir. Saha görevlerinin logları burada görünmemeli, hatta yeni simülasyonda
bile görünmemeli. Saha yönetiminde uçuşun yanında 'Simüle et' diye bir düğmeye bastığımda o zaman sorsun — atmosferi, rampayı falan."*

Üç giriş, tek ReplaySession:
1. **Simülasyon kaydını izle (sihirbazsız)** — Simülasyon Kayıtları tablosu (§21) ve Kayıtlı Simülasyonlar uçuş kartı (§28) **Oynat** →
   `POST /api/drone/sim/runs/{id}/replay` (201 → `session` + `run_id`). Sunucu (`flightsim_runs.oynatma_ayarlari`) satırın KAYDEDİLMİŞ ayarlarını
   kurar: `world` (dünya kipi, saat, hava, rüzgâr/esinti/türbülans, sis, pist yönü, tohum, boyut) + kalkış (`world.launch`, yoksa `launch` sütunu;
   `phase` atılır — rampa açı/yön, fırlatıcı, dolu hücre, nişan), görsel model (`model_id`; silinmiş/tip uyumsuz → tipin varsayılanı), kamera türü
   (`camera`). Hedefler (§24), yer kontrol sahası + görev (§26) ve güç (§23) ReplaySession'da zaten kaydın canlı oturumundan (`bin_log_id`) gelir.
   Eksik/eski alan varsayılanla dolar; artık geçersiz değer (ör. Google 3B anahtarı kaldırıldı) → gerçek arazi, olmazsa yalnız kalkış, en son
   varsayılan dünya (kayıt her durumda açılır). Ön yüz (`flightsim.js directReplay`) tıklama içinde tam ekran + (kayıt açıksa) ekran paylaşımı izni →
   aynı **ön hazırlık kartı** (`prepareSessionCard`, modül düzeyine taşındı; önizlemesiz: log ayrıştırma % → kareler → oturum ekranı dünyayı kurar).
   Gösterge tasarımı kullanıcının kalıcı tercihidir (`fs.gauge.theme`). Yetki: `drone.sim` yazma + (sahip ∨ MASTER ∨ yazma izni); log yetkisi
   `log_izinli` (simülatör kaydı → `drone.sim` yeter). Hatalar: 404 kayıt yok · 409 oynatılabilir log yok (.bin kaydı kapalıydı / analiz sürüyor)
   ya da oturum sınırı · 403 yetki.
2. **Yeni Simülasyon › Kayıttan oynat** listesi YALNIZ simülatör kayıtları: `flightsim_replay.SIM_LOG_SQL` =
   `task_id IS NULL AND flight_id IS NULL AND (origin = 'SIM' OR id ∈ drone_sim_runs.bin_log_id)`. Saha görevine (`task_id`) ya da saha uçuşuna
   (`flight_id`) bağlı loglar kaynağı SIM olsa bile listelenmez. Ön yüz de süzer (`flightsim_wizard.isSimLog / simLogsOnly`; sahte kip aynı). Kaynak
   (Tümü/Gerçek/Simülasyon) süzgeci kaldırıldı; boş listede "Saha Yönetimi / Uçuş Logu Analizi › Simüle et" yönlendirmesi.
   **Karar — bağımsız gerçek loglar (Araçlar › Uçuş Logu Analizi'ne elle yüklenen, görevsiz):** onlar da simülatör listesinden çıkarıldı. Gerekçe:
   kullanıcı simülatör listesini "simülatörün kendi kayıtları" olarak istiyor; gerçek uçuşun yeniden canlandırılması atmosfer/rampa sorusu
   gerektirir — bu da "Simüle et" yolunun işi. İki yol ayrık: simülatör kaydı → doğrudan izle; gerçek log → "Simüle et" (sorulur). Uçuş Logu
   Analizi listesinde de **Simüle et** düğmesi var, gerçek loga erişim kaybolmaz.
   CAYSIM `GET /api/caysim/v1/logs` sözleşmesi değişmez (`loglari_listele(..., hepsi=True)`: tüm oynatılabilir loglar, sahibin yetkisiyle).
3. **"Simüle et"** — Saha Yönetimi › görev › Uçuş Yönetimi tablosunda logu TAMAM olan her uçuşun yanında ve Uçuş Logu Analizi listesinde (yalnız
   `drone.sim`/`drone` yazma izni olana) → `#/drone/sim?simulate=<log>`. Sihirbaz kayıttan oynat kipinde **log sabit** açılır (`preset.pinned`;
   kip seçimi yerine "Simüle et" bandı; başlık "Uçuşu simüle et"; log `GET /logs?id=` ile — gerçek logda flightlogs yetkisi), loglar gelince
   **Dünya** adımına geçer (`wizardStartStep`): atmosfer (dünya kipi, saat, hava, rüzgâr) → kalkış/rampa (sabit kanat/INTERCEPTOR) → kamera →
   özet → ▶ Oynat. Log adımı geri dönülebilir (görsel model seçimi orada). `?simulate` adresten silinir (yenilemede pencere tekrar açılmaz).
- **Testler:** `tests/test_flightsim.py` `oynatma_girisleri_testleri` (liste süzgeci: SIM görevsiz ✓, bin'i simülasyon kaydı olan kaynaksız ✓,
  saha görevi ✗, saha uçuşu ✗; `?id=` admin ✓ / flightlogs yetkisiz ✗; montaj (okuma) simülatör kayıtlarını görür; `/runs/{id}/replay`
  404/409/403, dünya-hava-rüzgâr-sis-tohum-pist-rampa açı/yön-kamera-model korunur, Google 3B kapalı → gerçek arazi, eski satır → varsayılan +
  `launch` sütunu); `replay_testleri` güncellendi (bağımsız gerçek log listede yok, `?id=` ile var). Node: `tests/test_flightsim_wizard.mjs`
  (`isSimLog/simLogsOnly`, `simulateParam`, `simulateHref`, `wizardStartStep`). Görsel: `tests/replayfix_shots_hepgo.py` → `/tmp/replayfix-shots`.

### 8.6 MAVLink telemetri kaydı (.tlog) — Uçuş Logları'na yükleme ve analiz (`app/tlog.py`)
Mission Planner / QGroundControl'ün kaydettiği `.tlog` (her paket: 8 bayt big-endian µs zaman damgası + MAVLink v1 `0xFE` / v2 `0xFD`
çerçevesi) `.bin` / `.log` gibi yüklenir ve analiz edilir. Boyut sınırı, yerel ağ kuralı, parça parça yükleme ve analiz kuyruğu `.bin` ile aynı.
- **Yükleme:** `files.KINDS['flightlogs']` `.tlog` içerir; ön yüz giriş noktaları (Araçlar › Uçuş Logu Analizi `tools.js`, saha uçuşu
  `flight.js`, saha görevi uçuş penceresi `field.js`) `accept` + metinler. **İçerik doğrulaması** (`routers/flightlogs._store` →
  `tlog.dogrula`; ilk 2 MB): pymavlink'siz ham çerçeve tarayıcısı (`tlog.tara`; bir çerçeve, ardından gelen de geçerli başlangıçsa kabul).
  Değilse **400** + dosya silinir, kayıt açılmaz: boş · metin ("…ikili MAVLink telemetri kaydı olmalı") · DataFlash başlığı `A3 95`
  ("…`.bin` uzantısıyla yükleyin") · MAVLink çerçevesi yok · çerçeve var ama zaman damgası yok (ham akış). Bazı köprü kayıtlarında
  damgasız çerçeveler araya karışır (örn. `/tmp/flsim/ornek/ornek.tlog`): kabul edilir, zaman ekseni pymavlink'in damga taramasıyla.
- **Araç seçimi (`tlog.arac_sec`):** tüm dosyadaki HEARTBEAT sayımı; sysid 255, GCS / eş bilgisayar / gimbal / kamera / ADSB / … MAV_TYPE'ları
  ve `MAV_AUTOPILOT_INVALID` sayılmaz; en çok HEARTBEAT'li sysid'nin en çok HEARTBEAT'li bileşeni. Yalnız o (sysid, compid) okunur
  (STATUSTEXT aynı sysid'nin her bileşeninden). Diğerleri `summary.other_systems`.
- **Analiz (`flightlog.analyze` → `tlog.analiz`):** `flightlog._sonuclandir` (metin `.log` yoluyla ortak son işlem; `.bin` sonuçları değişmedi —
  `test_binanalyze` eşdeğerliği) ile **aynı JSON şeması**; ön yüz rapor/grafik/harita/3B değişmeden çalışır. Eşleme:

  | Rapor | MAVLink |
  |---|---|
  | iz / mesafe / ev | GPS_RAW_INT (fix ≥ 3; yoksa GLOBAL_POSITION_INT) · ev HOME_POSITION, yoksa ilk konum |
  | irtifa (eve göre) | GLOBAL_POSITION_INT.relative_alt; yoksa VFR_HUD.alt − ev irtifası |
  | yer / hava hızı, gaz | VFR_HUD groundspeed (yoksa GPS vel) / airspeed (**yalnız** SYS_STATUS sensör bit 16 varsa; yoksa tahmindir, gösterilmez) / throttle |
  | tutum, istenen tutum | ATTITUDE (rad → °) · NAV_CONTROLLER_OUTPUT nav_roll/nav_pitch; takip hatası her NAV anında en son ATTITUDE ile |
  | batarya | SYS_STATUS voltage/current/remaining · BATTERY_STATUS id 0 current_consumed (mAh), energy_consumed (hJ → Wh), hücre toplamı (SYS_STATUS yoksa) |
  | GPS | GPS_RAW_INT satellites_visible, eph/100 (HDop) |
  | titreşim / doygunluk | VIBRATION vibration_x/y/z, clipping_0..2 (birikimli, son değer) |
  | rüzgâr | WIND speed / direction (geldiği yön) |
  | modlar | HEARTBEAT custom_mode değişimi; ad `_mode_names(yazılım ya da MAV_TYPE → ArduXxx)`; PX4: `interpret_px4_mode` |
  | ARM/DISARM | HEARTBEAT base_mode bit 7 geçişleri → olay 10/11 (kayıt kurulu başladıysa başlangıç kurulu) |
  | havada aralıkları | EXTENDED_SYS_STATE.landed_state (2/3/4); yoksa kurulu iken irtifa > 2 m ya da yer hızı > 4 m/s (≤ 3 sn atılır) |
  | mesajlar, yazılım, kart | STATUSTEXT (önem ≤ 4 ya da uyarı kalıbı → uyarı; `sev`), "ArduXxx V…" / kart adı; yoksa AUTOPILOT_VERSION; parametre sayısı PARAM_VALUE |
  | zaman | yer istasyonu damgası (`_timestamp`; t0 = aracın ilk mesajı; bozuk damgalar atlanır) → start/takeoff/landing UTC |

  Ek alanlar: `summary.source = 'tlog'`, `sysid`, `compid`, `mav_type`, `other_systems`, `missing` (boş kalan bölümler: seri anahtarları
  `alt/gs/as/volt/curr/vx/roll/droll/sats/hdop/wind/thr` + `errors` (DataFlash ERR/EV telemetride **hiç yok**), `energy`, `track`,
  `messages`, `modes`). Bulgularda ERR yerine STATUSTEXT önemi: 0–2 → Kritik, 3 → Dikkat, yoksa "Kritik sistem mesajı yok".
  **Telemetride hiç olmayan:** ERR alt sistem/kod kayıtları, EV olayları (ARM/DISARM dışında), ORGN (EKF orijini), STAT.isFlying, ham IMU
  yüksek hızlı veri; hız çözünürlüğü yer istasyonu akış oranıyla sınırlı (genelde 1–10 Hz).
- **Ön yüz:** listede / rapor araç çubuğunda / saha uçuş kartında biçim rozeti (`tools.logFormatBadge`: BIN mavi · LOG gri · TLOG mor);
  raporda tlog notu (kaynak + "bu kayıtta bulunmayan: …"), "Log biçimi" satırı (sysid, diğer sistemler), boş grafiklerde "Telemetri kaydında
  (.tlog) bu veri yok" (`lineChart`/`trackMap` `empty`). **3B oynatma** (`/api/flight-logs/{id}/replay` → `flightlog.replay` → `tlog.replay`,
  aynı alanlar; devir RPM / ESC_TELEMETRY_1_TO_4) ve Uçuş Simülatörü kayıttan oynatma (§8, `flightsim_replay._tlog_ayristir`) yüklenen tlog ile çalışır.
- **Testler:** `tests/test_tlog.py` (doğrulama kabul/ret, araç seçimi çok sysid/GCS/gimbal, şema = .bin, makul değerler, EXTENDED_SYS_STATE,
  bozuk bayt + yarım paket, MAVLink1, eksik veri, replay, CLI alt süreç, HTTP tek istek + parça parça, 400'ler). Görsel uçtan uca:
  `tests/tlog_e2e.py` (yükle → analiz TAMAM → liste rozeti + rapor + harita + 3B ekran görüntüleri → `/tmp/tlog-shots`).

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
  900–1500 Hz, kuyruk rotoru (×5,5). **sabit_kanat** (delta/caymaz aynı) **CAYMAZ 220 cc benzinli tek silindirli iki zamanlı** (eski "uğultu" sentezi
  yerine, kullanıcı isteği): devir **2200 (rölanti) → 7600 d/dk** gazla eşlenir, hava hızı pervaneyi boşaltır (+%4'e kadar; `twoStrokeRpm`), devir gecikmeli
  (`TWO_STROKE_TAU` yukarı 0,45 / aşağı 0,9 sn); ateşleme **f = devir/60** (iki zamanlıda her devir bir ateşleme; 36,7 → 126,7 Hz; `firingHz(rpm, cyl, stroke)`).
  Katmanlar (`twoStrokeParams` saf eşleme): dar darbe dizisi (`PeriodicWave`, %12 doluluk, 40 harmonik — `pulseCoeffs`) + f/2 alt harmonik (rölantide
  belirgin) → gazla açılan lowpass; **egzoz "pat-pat"**: geniş bantlı gürültü × ateşleme darbesi (AM: darbe osilatörü gürültü kazancını sürer) → **egzoz
  rezonansı** bandpass (Q 3, 215 → 450 Hz) + kuru yol; **hafif rastgele zamanlama** (her güncellemede ±35 cent'e kadar detune; rölantide daha çok);
  **mekanik tıkırtı** (3,4 kHz bant gürültüsü × aynı darbe); **pervane** 2 pala sinüs + pala geçişi hışırtısı (gaz + hava hızı). Motor tipi
  `createEngineAudio(stage, { engine })` ('fuel' | 'electric'; SIMUMAV hangar `power.engine`): `isTwoStroke(model, engine)` = sabit kanat / VTOL,
  `stroke: 2` ve elektrik değil; elektrikli sabit kanat ve `stroke`suz modeller (SIMUMAV jet) eski sentezi (testere + kare + lowpass egzoz + pervane) kullanır;
  HEPGO motor tipi vermez → sabit kanat iki zamanlı. Kopter/heli/rover sesleri değişmedi. Armed + gaz 0 = rölanti, disarm sessiz.
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
  `flight_analysis.start` (analiz kuyruğu, alt süreç — §8.4) → TAMAM olunca Araçlar › Uçuş Logu Analizi ve sihirbazın Kayıttan oynat listesinde görünür; kalan .BIN'ler
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

**REST (`/api/drone/sim/runs`; okuma `drone.sim`):** `GET /runs?from&to&center_id&type&owner_id&result&mode&q&sort&page[&preset=free|<id>&per_page]` (§27) → `{items, total,
page, pages, per_page:25, facets:{centers[{id,name,n}], owners[{id,name,n}], types[]}}`; `sort` ∈ started_at | owner | type | center |
duration_s | result | mode (başında `-` azalan; ikincil anahtar id aynı yön); `q` merkez/kullanıcı/model/dron kodu/log adı LIKE ya da oturum no;
`from/to` `YYYY-MM-DD` (started_at günü); geçersiz sayı 400. Satır alanları + `bin_status/bin_file_name`, `source_file_name`, `has_params/
has_scripts/has_video/has_summary`, `play_log_id` (bin_log_id analizi TAMAM, yoksa source_log_id TAMAM), `can_delete`. `GET /runs/{id}`;
`GET /runs/{id}/params` ve `GET /runs/{id}/scripts` **yalnız MASTER** (`user.master`; aksi 403; `Content-Disposition` SIM-<oturum>-<tarih>-
params.param / scripts.zip); `GET /runs/{id}/bin` (.bin dosyası, drone.sim okuma izniyle; uçuş logu yetkisi gerekmez); `POST /runs/{id}/replay` (§8.5: kaydedilen ayarlarla doğrudan izleme oturumu; yazma izni); `GET /runs/{id}/video[?dl=1]`
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
.fs-runs-rowpill`) **Oynat** (`play_log_id` ∧ yazma izni; pasifse soluk; §8.5: sihirbaz AÇILMAZ — `POST /runs/{id}/replay` kaydın kaydedilmiş ayarlarıyla
oturum açar → hazırlık kartı → izleme) · **Rapor** (`showReport`; `has_summary` yoksa pasif) · **Video** (yalnız `has_video`; modal `<video>` + İndir); **yalnız
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
  uçuş içinde **T** (döngü), **Shift+T** (termal paleti; termal değilse termale geçer), alt çubukta görünüm kapsülünün sağ yarısı **"📷 Tür ▾"** menüsü (§36) (tür · palet · PiP aç/boyut ·
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
- **Düzeltme — araç yerdeyken PiP'in alt yarısı düz mavi.** İki kök neden: (1) prosedürel dünyanın **su düzlemi tek dörtgendi** (~19 km, iki üçgen);
  kamera zemine çok yakınken (yerdeki sabit kanadın gimbali z ≈ 0,3 m) yakın düzlemle kırpılan dev üçgenin derinliği bozuluyor, arazinin ~1,5 m
  altındaki su **küçük render hedeflerinde** (PiP 81×46, 160×90, 256×144 …) pistin/arazinin üstüne çiziliyordu — çözünürlüğe bağlı olduğu için dpr /
  ön ayar / PiP ölçeği değişince görünüp kayboluyordu (ana görünümde nadiren). Su düzlemi artık ≤ ~500 m hücrelere bölünür (8–64 bölüm), pist asfaltı
  ≤ 50 m dilimlere. (2) Gimbal kamerasının **sabit 0,5 m yakın düzlemi** 0,3 m altındaki zemini kesiyordu (aşağı bakınca boşluk): `vehCamNear` →
  near = clamp(0,35·AGL, 0,05, 0,5) (AGL: arazi yüksekliği; araç yere yakınsa gövde altı da aday — Google 3B'de DEM hücresi karo yüzeyinden sapabilir);
  ana gimbal görünümü ve PiP aynı kural; prosedürel/gerçek arazide kamera zeminin 0,1 m altına inmez. Uçuşta (AGL ≥ 1,5 m) 0,5 aynen.
  Regresyon: `./.venv/bin/python -m tests.pip_shots_hepgo` (teşhis `pipPose()` + `pipProbe()`: PiP hedefinin alt yarısı aynı kameranın 4× başvuru
  çizimiyle karşılaştırılır; araç tipi × dpr 1/1,5/2 × ön ayar × gündüz/termal/gece × gimbal açısı; kareler /tmp/fixes-shots/pip-*.png).

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
dönüş hızı sınırıyla döner, hedef yoksa SON YÖNDE sabit kalır — §30.2); **raf** — beton pad + 10 yuva (sarı işaret), yuvalarda dronun kendi modeli (tailsitter, kuyruk üstünde, soğuk
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
SEÇİLMEDİ" (başlık son yönde sabit; tarama YOK — §30.2), fare tekerleği zoom / basılı sürükle pan-tilt (§30.2); dönüş sürerken "YÖNLENİYOR". Kamera türü gündüz / termal / gece (◐ düğmesi; §22.3 `CAM_FRAG`, kendi türü — `setCamUniforms(…, typeOverride)`;
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
kipi sahayı/görevi kurmaz; görüş hattı (arazi örtmesi) hesaplanmaz; radar yüklü dünyanın altına düz altlık çizer (§30.1: gerçek/Google'da uydu karosu, prosedürelde arazi paleti) — dünya kenarı ve yüklenmemiş karo boşluğu dolu.

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
## 28. Kayıtlı Simülasyonlar — Uç / Kaydet, pilot ataması, azami süre-menzil, üç sütunlu ekran (`app/flightsim_presets.py`, `app/routers/flightsim_presets.py`, `static/js/modules/flightsim_saved.js`, saf `flightsim_presets.js`; tablo `drone_sim_presets`, `drone_sim_runs.preset_id`)
Kullanıcı isteği (özet): **(4)** "Simülasyonlarda başlatmak zorunlu olmasın: tasarlayan yönetici pilot atayabilsin — sihirbazda pilot yetkisi olan kişilerden
(kendisi de seçilebilir) pilot seçimi." **(5)** "Sihirbazın son adımında 'Uç' düğmesi yanıp sönsün, yanında 'Kaydet'." **(6)** "Kaydet ayarları kaydeder; Uçuş
Simülatörü altında 'Kayıtlı Simülasyonlar': atanan pilot bunu defalarca, farklı zamanlarda çalıştırabilir, her seferinde yeniden ayar yapmaz." **(7)** "Kaydederken
isim sorulur (benzersiz; açıklama isteğe bağlı)." **(8)** "Kartta Başlat / Düzenle / Sil." **(9)** "Başlat → bu ayarlarla doğrudan başlar (sihirbaz atlanır; yalnız
onay/özet ve geri sayım)." **(11)** "Sihirbazın sonunda benzin, elektrik, azami hız vb. değerlere göre azami uçuş süresi ve azami menzil (yakıt ve batarya ayrı,
sınırlayan vurgulu)." **(12)** "Alt modül ekranı: en solda kayıtlı sihirbaz kartları, en başta 'Serbest Uçuş'; seçilince ortada o ayarlarla yapılan uçuşlar kart
olarak; uçuş kartı seçilince sağda özet ve üstte uçulan model 3B olarak sürekli dönerek." **Yetki kararı (kullanıcı)**: başlatmayı atanan pilot ve tasarlayan yapar,
diğer pilotlar yalnız görür; düzenle/sil tasarlayan ve yönetici (ADMIN); atanan pilota bildirim.

**Tablo `drone_sim_presets`** (`CREATE IF NOT EXISTS`, app/db.py): `id, name, description, settings JSON, type, center_id, created_by, pilot_id, created_at, updated_at,
deleted_at` + indeks pilot_id. `settings` = **oturum başlatma gövdesinin aynısı** (`POST /sessions`, mode sitl; alanlar `flightsim_presets.ALANLAR` = type, center_id,
world{…, launch}, model, drone_id, rec, power, camera, layout, targets, site, defend — mode/log_id/airframe atılır). Kaydederken **başlatmadaki doğrulayıcılardan**
geçer (`ayar_dogrula`: tip, etkin merkez, `flightsim_models.coz`, aktif dron kaydı, `kamera_dogrula`, `flightsim_power.dogrula`, `layout_dogrula`, `flightsim_targets.
dogrula`, `gcs_dogrula`/`savunma_dogrula`, `world_dogrula`; oturum AÇILMAZ, limit/SITL denetimi başlatırken) ama **normalize edilmeden** saklanır (başlatırken yeniden
doğrulanır; sonradan değişen varsayılanlar uygulanır). Silme **yumuşak** (`deleted_at`). **Göç** (idempotent): `drone_sim_runs.preset_id INTEGER REFERENCES
drone_sim_presets(id) ON DELETE SET NULL` + `ix_drone_sim_runs_preset`. Oturuma `s.preset_id` işlenir → kapanışta `flightsim_runs._oturum_alanlari` satıra yazar
(serbest sihirbaz ve kayıttan oynatma NULL).

**Ad benzersizliği**: silinmemişler arasında; baş/son/ardışık boşluk ve büyük/küçük harf (Türkçe İ/I dahil, NFC) duyarsız (`ad_anahtari` ↔ JS `nameKey`); ≤ 80
karakter; açıklama ≤ 500. Çakışma → 409 (pencerede kırmızı uyarı, Kaydet pasif; sunucu 409'u da aynı yere yazılır). Silinmiş kaydın adı yeniden kullanılabilir.

**Pilotlar** (`GET /presets/pilots`): etkin kullanıcılardan Uçuş Simülatörü'nde **yazma** izni olanlar (Rol Yönetimi `rbac.writable` ∋ `drone.sim`; PILOT rolü
`drone` modülünden miras alır) ya da MASTER — oturum açıp uçurabilmek yazma ister; PILOT rolündekiler önce (`pilot: true`), kendisi `(ben)` ile seçilebilir. Salt
okuyan/yetkisiz kullanıcı atanamaz (400). Pilot atanmazsa (NULL) tasarlayan uçar.

**Yetki** (`baslatabilir` / `duzenleyebilir`; satırda `can_start`, `can_edit`, `mine`): Başlat = `pilot_id` ya da `created_by` (MASTER her zaman); Düzenle/Sil =
`created_by` ya da ADMIN rolü / MASTER. Liste herkese (drone.sim okuma). Yazma uçları ayrıca `drone.sim` yazma izni ister (salt okuyan 403).

**Bildirim**: atamada (oluştur; düzenlemede yalnız pilot DEĞİŞİNCE; kendine atamada değil) anlık push `push.send` (`Size bir simülasyon atandı`, gövde `ad · tasarlayan`,
url `/app#/drone/sim?tab=saved&preset=<id>`); zil türü **`sim-assigned`** (`notifications.sim_assigned`; `push: False` — tarama ikinci kez atmaz): bana atanan,
başkasının tasarladığı, silinmemiş ve **henüz benim uçmadığım** kayıtlar → ilk uçuşla kendiliğinden düşer. Grup "Dron Yönetimi".

**REST (`/api/drone/sim/presets`)**: `GET` → liste (son güncellenen önce; satır + `settings` + ad alanları `created_by_name/pilot_name/center_name` + `run_count`,
`last_run_at` + `can_start/can_edit/mine` + **`budget`** = `menzil_sure`) · `GET /pilots` · `GET /{id}` · `POST {name, description?, pilot_id?, settings}` → 201 ·
`PUT /{id}` (aynı gövde; 403/404/409/400) · `DELETE /{id}` (yumuşak) · `POST /{id}/start {rec?}` → 201 `session` + `preset {id, name}` (oturum açma çekirdeği
`routers.flightsim.oturum_ac` kayıtlı gövdeyle; `rec` verilirse yalnız .bin seçimi uçanınki; hatalar başlatma ucuyla aynı 400/409/503; yetkisiz 403). İz kaydı
(audit) oluştur/güncelle/sil. **Kayıtlar** `GET /runs?preset=free|<id>&per_page≤100`: `free` = `preset_id` yok ya da kayıt silinmiş; satırda `preset_name`,
`preset_deleted_at`.

**Azami uçuş süresi / menzil** (`flightsim_power.menzil_sure` ↔ `flightsim_power.js flightBudget`; sayılar birebir, yuvarlama `floor(x·10ⁿ + 0,5)/10ⁿ`): §23 modeli
SEYİR koşulunda çözülür — uçakta seyir hızı = azami × AIRSPEED_CRUISE oranı (`hiz_parametreleri` ile aynı 12/22; INTERCEPTOR 0,8 = `flightsim_icept.CRUISE_ORAN`),
seyir gazı = (v_seyir/v_azami)² (sürükleme ∝ V², tam gaz = azami hız); kopterde 10 m/s (WPNAV_SPEED), gaz 0,5 (askı). **Yakıt**: menzil = L × km/L ÷ (0,5 + 0,5·gaz),
süre = menzil ÷ v_seyir (`yakit_lpm`'in tersi). **Batarya**: süre = Wh ÷ W (servo ek yükü hariç), menzil = süre × v_seyir. **Sınırlayan** = süresi kısa olan kaynak;
azami hızda (gaz 1) aynı hesap `*_max`. CAYMAZ varsayılanı (45 m/s, 5 L @ 25 km/L, 4S 10000 mAh 30 W): seyir 88 km/h, gaz %30 → yakıt **2 sa 11 dk / 193 km**
(sınırlayan), batarya 4 sa 56 dk / 436 km; azami hızda 46 dk / 125 km. Yakıt ve batarya kapalıysa hesap yok.

**Sihirbaz** (§6; `flightsim.js wizardModal`): son adımda (canlı kip) altbilgi **Kaydet** + **Uç** — Uç birincil, **nabız animasyonu** (`fsFlyPulse` 1,4 s parlaklık +
genişleyen halka `fsFlyRing`; `prefers-reduced-motion: reduce` → animasyon yok, sabit 3 px halka), "Bu ayarlarla şimdi uç (kaydetmeden)" — davranış eski
Başlat'ın aynısı (kayıttan oynat kipinde "▶ Oynat", Kaydet yok). Özet adımının üstünde **azami süre/menzil kutusu** (iki büyük sayı + Kaynak/Süre/Menzil/Azami
hızda tablosu; sınırlayan satır turuncu + "Sınırlayan" rozeti; model notu) ve **Pilot ataması** seçimi (yazma izni varsa). **Kaydet** → ad penceresi (ad, açıklama,
"Atanacak pilot"; canlı benzersizlik uyarısı; Enter = Kaydet, Esc yalnız bu pencereyi kapatır) → `POST /presets` → sihirbaz kapanır, sayfa "Kayıtlı Simülasyonlar"
sekmesinde yeni kayıt seçili açılır. Gövde `sitlBody()` = Uç'un gövdesiyle aynı (`presetBodyFromSession`). **Düzenle** (`preset.edit`): sihirbaz kayıtlı ayarlarla
açılır — tip/merkez/dünya (+ tohum, kalkış)/dron kaydı/kontrol düzeni başlangıç durumundan; model `picker.prefer`; güç `powerSec.set` (öneriden SONRA); kamera kartı;
hedefler `targetsSec.set({items, radius_m})`; saha `createSiteSection({initial})` (kayıtta yoksa kapalı); .bin `recOpts.setBin` — Uç gizli, **Kaydet (güncelle)**
birincil, ad penceresi önceden dolu → `PUT`. Başlık "Kayıtlı simülasyonu düzenle: <ad>". Kayıtlı ayar varken `fs.wz.last` önerisi kullanılmaz/yazılmaz.
**Başlat** (`preset.quick`): aynı pencere yalnız özet adımıyla (kip/şerit, Geri, Düzenle düğmeleri, Kaydet gizli), başlıkta kayıt adı + açıklama + pilot/tasarlayan,
azami süre/menzil, kayıt seçenekleri (ekran kaydı/.bin uçanın tercihi) → **Uç** → tam ekran + ekran paylaşımı izni (kullanıcı etkinleştirmesi içinde) → **3-2-1 geri
sayım** (`countdown`; tam ekran örtü, İptal/Esc → geri alınır) → `POST /presets/{id}/start` → mevcut hazırlık kartı (§8) → oturum ekranı. Merkez/model sonradan
silindiyse özet kartı kırmızı + Uç pasif (gerekçe altbilgide).

**Ekran (§21 sayfası; ilk sekme "Kayıtlı Simülasyonlar", tercih `fs.tab2`; `?tab=saved&preset=free|<id>`)** — `savedScreen` üç sütun (≥ 1280 px: 250–300 px ·
esnek · 300–380 px): **(1) sol** "Simülasyonlar" başlığı + sayı + "+ Yeni" (sihirbaz); en üstte **Serbest Uçuş** kartı (yeşil simge, serbest uçuş sayısı), altında
kayıtlı simülasyon kartları: ad, tip · merkez, açıklama (2 satır), pilot (bana atanmışsa vurgulu) + tasarlayan, **azami süre · menzil** çipi (sınırlayan kaynak simgesi;
ipucu "yakıt/batarya sınırlar"), uçuş sayısı rozeti, başkası bana atadıysa üstte "Size atandı" rozeti; **▶ Başlat** (`can_start` değilse pasif + gerekçe ipucu) ·
Düzenle / Sil simgeleri (`can_edit`; Sil onaylı — uçuşlar silinmez). **(2) orta** seçimin uçuşları kart ızgarası (`GET /runs?preset=…&per_page=30`, "Daha fazla
göster"): tarih-saat, sonuç rozeti (çarpışma kartı kırmızı sol kenar), kullanıcı · tip · model, süre · merkez · hız (4×) · ek simgeleri (video/.bin/rapor); serbestte
silinmiş kayıttan uçuşlar "silinmiş kayıt" rozetiyle; "Tablo görünümü" → Simülasyon Kayıtları sekmesi (filtreli tablo aynen). **(3) sağ** üstte **dönen 3B model**
(uçuşun `model_id`'si; kütüphane modeli `GET /models/{id}` ile GLB + yönelim; kayıt seçiliyken kaydın modeli), altında özet: tarih + sonuç, kullanıcı · oturum no ·
kayıt adı, **karolar** (`runFacts`: süre, mesafe, sonuç, çarpışma, önleme n/hedef, yakıt L · km/L [bitti → kırmızı], batarya Wh · W, en yüksek hız, simülasyon hızı,
kapanış), ayrıntı listesi (merkez, dünya, kalkış, kamera, dron kaydı, bitiş) ve işlemler: **Oynat** (§8.5 doğrudan izleme, sihirbazsız) **· Rapor · Video** (+ MASTER **Download ▾** — `runDownloadMenu`,
tabloyla ortak) · Sil. Kayıtlı simülasyon seçili ve uçuş seçili değilken sağda kaydın özeti: model, açıklama, azami süre/menzil kutusu (dar), pilot/tasarlayan/
merkez/dünya/kalkış/kamera/hedefler/uçuş sayısı, Başlat/Düzenle. Serbest Uçuş seçilince en yeni uçuş seçili gelir. **Tek WebGL bağlamı**: dönen model flightsim3d
**stüdyo** kipiyle (`createFlightSim3D(…, {studio: true})` → yalnız `createModelViewer`; dünya/kare döngüsü yok), görüntü 2B tuvale kopyalanır (§24.4 kalıbı;
≤ 30 fps; görünmezken/sekme gizliyken çizim yok; sürükle → döndür; reduced-motion'da yavaş). Sihirbaz açılırken stüdyo bağlamı **bırakılır** (`suspend3d`;
sihirbaz önizlemesi kendi bağlamını kurar), kapanınca yeniden kurulur; sayfadan çıkınca dispose. **Düzen**: ≤ 1280 px sol sütun iki satır boyu, uçuşlar ve özet sağda
alt alta (uçuş seçilince özete kaydırılır); ≤ 760 px tek sütun. CSS modülde (`ensureSavedCss`, HEPGO tema değişkenleri; açık/koyu). Sahte kipte (`?mock=1`) ekran
"Sahte veri kipinde … yok" notu, Kaydet pasif.

**Testler**: `tests.test_flightsim preset_testleri` — saf hesap (CAYMAZ/kopter/INTERCEPTOR/sınırlayan/yok; `ICEPT_SEYIR_ORAN` = `CRUISE_ORAN`, seyir =
`hiz_parametreleri` AIRSPEED_CRUISE; yarım yukarı yuvarlama), pilot listesi (PILOT önce, kendisi, salt okuyan/yetkisiz yok), doğrulama 400'leri (merkez, tip, güç,
dünya, kamera, düzen, model, replay, dron kaydı, hedef; oturum açılmaz), ad (boş/uzun/çakışma: boşluk + Türkçe harf), salt okuyan 403, oluştur (alanlar, budget,
push yükü), kendine atama bildirimsiz, zil `sim_assigned` (modülsüz kullanıcıya düşmez), diğer pilot/ADMIN/eski pilot yetkileri, pilot başlatır → oturum alanları
(dünya tohumu, kalkış, güç, kamera, düzen) → kapanışta `preset_id` + zil düşer, tasarlayan başlatır, serbest oturum `preset_id` NULL, `?preset=` süzgeci
(+ 400, per_page tavanı), `run_count`, düzenle (409, pilot değişince tek bildirim, 400, ADMIN), yumuşak sil (404'ler, serbestte "silinmiş", ad yeniden kullanılır).
`node tests/test_flightsim_saved.mjs` (10: flightBudget sayıları sunucuyla aynı, budgetView, ad kuralları, gövde alanları, runFacts). Görsel + uçtan uca:
`./.venv/bin/python -m tests.saved_shots_hepgo` → `/tmp/saved-shots` (sihirbaz son adımı açık/koyu + mobil, ad çakışması/sorma, Esc yalnız ad penceresi, kaydedilen
seçili; üç sütun açık/koyu × masaüstü/tablet/mobil + dönen model piksel denetimi; Düzenle → önceden dolu → güncelle; pilot girişi: "Size atandı", başkasının
kaydında Başlat pasif, hızlı başlat özeti, geri sayım, oturum, uçuş kayda bağlı; zil; Sil).
**Sınırlar**: geri sayım oturum ekranındaki giriş geri sayımından (uçuş içi ayarlar dalı) bağımsızdır — ikisi birlikte gelirse biri kaldırılabilir. Kayıtlı ayardaki
model/merkez/dron kaydı sonradan silinirse başlatma 400 verir (kart Düzenle ile onarılır). Atama bildirimi tarama tabanlı zil + anlık push'tur; e-posta yok.
## 29. Uçuş arayüzü kişiselleştirme — kumanda hassasiyeti, giriş sekansı, gösterge tasarımı, taşınabilir radar/EO pencereleri (HEPGO + SIMUMAV ortak)
Kullanıcı istekleri: "sanal joystick hassasiyeti değiştirilebilsin", "radar ve EO pencerelerinin yeri ve boyutu değiştirilebilsin", "ortadaki göstergeler için
farklı tasarım seçenekleri", "tüm başlatmalarda kamera 100 m yüksekten baksın, 3‑2‑1 geri sayım ve dıt dıt dıt sesi". Dört özellik de istemci tarafıdır
(sunucuya yeni alan gitmez); tercihler tarayıcıda (localStorage) kalıcıdır. Modüller `flightsim*.js` kalıbıyla SIMUMAV dışa aktarımına kendiliğinden girer.

### 27.1 Sanal kumanda hassasiyeti (`static/js/modules/flightsim_rcfeel.js`)
- **Eğri** (eksen başına: roll, pitch, yaw, gaz): ölü bölge % 0–20 (merkezde tepkisiz; dışarısı 0…1'e yeniden ölçeklenir) → expo % 0–90
  (`y = (1−e)·x + e·x³`; merkezde yumuşak, uçta tam) → hassasiyet (oran) % 30–100 (tam çubukta azami çıkış). `shapeAxis` tek fonksiyon, monoton.
- **Uygulandığı yer:** kumandanın ÇIKIŞI (kanal PWM'i) — HEPGO `virtualRC({ shape })`, SIMUMAV `rc.js channelsOf(ax, ch5, shape)`. Böylece sanal çubuk ve
  klavye (WASD/oklar) aynı eğriden geçer; ileride gamepad eklenirse aynı `shape` kullanılır (şu an uçuşta gamepad girişi yok). Çubuk topuzu ham konumu
  gösterir. **Uçakta gaz doğrusal** kalır (tutmalı gaz kolu, −1 = rölanti; eğri gaz ekseninde yalnız kopter ailesinde — merkez = askı).
- **Hazır ayarlar:** Hassas (oran 70, expo 45, ölü 4), Normal (varsayılan; 100/20/3, yaw 90/20/4), Çevik (100/0/2); elle değişince "Özel".
  "Roll ve pitch birlikte" (varsayılan açık) iki ekseni birlikte değiştirir. "Varsayılan" sıfırlar.
- **Arayüz:** alt çubukta 🎮 Sanal kumanda'nın yanında ⚙ (kaydırıcı simgesi) düğmesi → küçük açılır panel (hazır ayarlar, eksen sekmeleri, üç kaydırıcı,
  canlı eğri önizlemesi: doğrusal kesikli çizgi, ölü bölge sarı, uç noktası). Değişiklik anında kumandaya uygulanır. Kalıcı: `fs.rc.feel`. Sihirbazda ayar yok.
- Metinler: HEPGO Türkçe anahtar; SIMUMAV `rcfeel.*` (7 dil).

#### 27.1.1 Kumanda modu — Mode 1–4 (`static/js/modules/flightsim_stickmode.js`)
RC vericilerdeki gibi hangi çubuğun hangi ekseni sürdüğü seçilir (⚙ Hassasiyet panelinin ve fiziksel kumanda panelinin üstünde M1–M4; tercih `localStorage fs.rc.mode`, varsayılan Mode 2; değişim `fs-stickmode` olayıyla iki panel ve açık oturum anında eşitlenir).

| Mod | Sol çubuk (X / Y) | Sağ çubuk (X / Y) |
|---|---|---|
| 1 | yaw / pitch | roll / gaz |
| 2 | yaw / gaz | roll / pitch |
| 3 | roll / pitch | yaw / gaz |
| 4 | roll / gaz | yaw / pitch |

- Sanal çubuklar ve klavye (WASD = sol çubuk, oklar = sağ çubuk) moda göre eşlenir: Mode 3'te A/D roll, ←/→ yaw olur. Uçakta gaz hangi çubuktaysa orada tutmalıdır. Çubuk etiketleri ve klavye ipucu anında güncellenir.
- Standart gamepad: eksen ataması herhangi bir modun varsayılanıysa seçili modun varsayılanına çekilir (`applyStickModeToPad`); elle (Algıla) yapılan atama korunur. RC vericide mod donanımdadır, eksen ataması değişmez.
- Kara aracında (§31) mod uygulanmaz. HEPGO `flightsim.js virtualRC` ve SIMUMAV `fly/rc.js virtualRC` aynı `STICK_MAP`'i kullanır (`stickMode()` girdisi). Test: `node tests/test_flightsim_stickmode.mjs`.

### 27.2 Giriş sekansı — 100 m bakış + 3‑2‑1 geri sayım (`static/js/modules/flightsim_intro.js`, 3B `flightsim3d.js playIntro/endIntro`)
- **Ne zaman:** her oturumda bir kez, 3B dünya kurulmuş + perde (`.fs-msg`) kalkmış + oturum HAZIR iken (HEPGO canlı, sahte ve kayıttan oynatma; SIMUMAV
  her uçuş). SIMUMAV sihirbazının eski BAŞLA geri sayımı (`COUNTDOWN_S`) bununla birleştirildi: sihirbazda artık yalnız "Hazır ol…" perdesi var, sayım sahnede.
- **Kamera:** kamera kipi DEĞİŞMEZ. Her karede normal kip hesaplanır, ardından poz `introPose(u)` ile ezilir ve render SONRASI geri yüklenir (takip
  kamerasının yörünge ofseti, serbest kameranın konumu bozulmaz). Yol: hedefin (dronun çizilen konumu / kalkış noktası) 100 m üstünden ve 80 m uzağından,
  bitiş yönünden 110° geride başlayan spiral; yükseklik ve yarıçap quintic yumuşak eğriyle iner, sonunda normal kipin kamera ofsetine (takipte yörünge ofseti,
  diğer kiplerde takip ofseti) varır. Sekans (3 sn sayım + 0,7 sn "BAŞLA") bitince 1,4 sn'de son seçilen kipe yumuşak geçiş (konum lerp + yönelim slerp + FOV).
  Sekans sırasında FPV/termal son işleme, OSD/askerî HUD ve kamera PiP'i gizlenir.
- **Ekran:** üst-ortada büyük 3 / 2 / 1 / BAŞLA (pop animasyonu), ilerleme halkası, altında merkez/parkur adı ve "Atla (Boşluk / tıkla)". Boşluk, Enter, Esc ya
  da tıklama sekansı keser (kamera 0,6 sn'de normale döner).
- **Ses:** "dıt dıt dıt" (880 Hz, 0,11 sn kare + oktav sinüs) ve sonda farklı ve uzun "diiit" (1320 Hz, 0,55 sn) — Web Audio, ayrı kısa ömürlü bağlam.
  Ses tercihine uyulur: HEPGO `fs.audio.on`/`fs.audio.vol` (motor sesi düğmesi), SIMUMAV Ayarlar › Ses (`sfx.config()`). Kapalıysa bip çalmaz.
- Teşhis: `window.__fsIntroHold = t` (sn) overlay'i ve kamerayı o anda sabitler (görsel betikler: yavaş yazılım WebGL'de kare almak için).

### 27.3 Gösterge tasarımı — alt ortadaki kadranlar (`static/js/modules/flightsim_gtheme.js`; `createPowerGauges` `data-gtheme`)
| Anahtar | Ad | Görünüm |
|---|---|---|
| `classic` | Klasik otomobil | §23.6 (HEPGO açık/koyu; SIMUMAV oyun teması `.sm-game`) — varsayılan |
| `cockpit` | Uçak kokpiti | siyah kadran, kalın koyu çerçeve, beyaz ibre/çentik/rakam, kokpit yazı tipi (B612/DIN benzeri); gece (koyu tema) amber arka aydınlatma |
| `glass` | Dijital cam kokpit | MFD karoları: etiket, büyük sayısal değer + birim, seviye şeridi (ibre doluluğu `--f`, seviyeye göre yeşil/sarı/kırmızı); açık temada beyaz karo |
| `minimal` | Minimal / şeffaf | zeminsiz ince halkalar, yalnız ana çentikler, ince beyaz ibre, gölgeli yazılar (HUD uyumlu); koyu temada açık yeşil ton |
| `military` | Retro askerî | zeytin yeşili gövde, fosfor yeşili parlayan rakam/ibre, monospace |
- Seçim kalıcıdır (`fs.gauge.theme`); geçersiz değer `classic`'e düşer (`normGaugeTheme` — enum doğrulaması; sunucuya gitmez).
- **Sihirbaz:** HEPGO "Kamera" adımının altında "Gösterge tasarımı" bölümü (önizlemeli kartlar: gökyüzü/arazi zemininde iki kadran ya da üç MFD karosu;
  gün/gece temasına göre önizleme), özet satırı "Gösterge tasarımı". SIMUMAV "Pilot" adımında kamera kartlarının altında (oyun teması önizlemesi).
- **Uçuşta:** kadranlara tıklayınca açılan ayrıntı kutusunun altında "TASARIM" satırı; **G** tuşu temalar arasında döner; değişim olay şeridine yazılır.
- Kurallar tema özniteliğiyle `.fs-stage .fs-gauges[data-gtheme=…]` (HEPGO app.css ve SIMUMAV power.css'in önünde); JS bir kez `<style id="fs-gtheme-css">` ekler.

### 27.4 Taşınabilir / boyutlandırılabilir radar ve EO pencereleri (`flightsim_gcs_ui.js createSiteScreens` + saf `flightsim_dock.js`)
- Varsayılan yerleşim §26 (sol alt dok). **Başlık çubuğundan sürükle** (fare, dokunmatik, kalem — pointer olayları, `touch-action: none`) → pencere yüzen
  olur (sahne içinde mutlak konum). **Sağ alt köşe tutamacı** → boyut; **en/boy oranı korunur** (radar ölçekli harita, EO kamera görüntüsü — serbest oran
  görüntüyü gererdi). En küçük 190 px; en büyük sahne genişliğinin %60'ı ve yüksekliğe sığan.
- **Bırakınca:** kenarlara ≤ 28 px yaklaşınca yapışma (köşelere iki eksende); sonra engellerden kaçınma — kamera PiP'i, alt ortadaki kadranlar (ve SIMUMAV hız
  kadranı), Mission Planner kutusu, harekât kartı / yüzen panel, sanal kumanda çubukları, hassasiyet paneli, dolu dok ve diğer yüzen pencere (8 px boşluk):
  çakışan engellerin dört yanına itilmiş adaylar genişlik öncelikli (4 tur) aranır, sınır içinde ve çakışmasız en yakın aday seçilir. Sınırlar: üst gezinti
  şeridinin altı, alt çubuğun üstü. PiP de yüzen pencereleri sol taraf engeli sayar (`pipObstacleInsets`).
- **Kalıcı:** `fs.site.win` = `{radar, eo}` her biri ekran boyutuna ORANLI `{fx, fy, fw, sx, sy}`; `sx/sy` yapışılan kenar — ekran boyutu değişince yapışık kenar
  yapışık kalır (sağ alttaki pencere sağ altta), yapışmayan eksende oran korunur. Bozuk kayıt yok sayılır (`normWin`).
- **Varsayılana dön:** başlıktaki ⟲ (yalnız yüzen pencerede görünür) ya da başlığa çift tık → iki pencere de doka döner.
- **Render:** görüntü yine tek paylaşılan WebGL renderer'da viewport/scissor kopyası (§26); `sync()` her tikte ve sürükleme sırasında her harekette yeni
  dikdörtgeni `sim.setRadarRect/setEoRect`'e verir, render hedefi (`rv.rt/ev.rt`) yeni piksel boyutunda yeniden kurulur. Dok tamamen boşalınca kadran/olay
  şeridi kaydırması (`--fs-site-r`) sıfırlanır ve PiP yeniden yerleşir.

### 27.5 Testler ve görsel doğrulama
- `tests/test_flightsim_flyui.mjs` (node): eğri (tek/monoton/uçlar/ölü bölge/expo), normFeel sınırları, uçakta doğrusal gaz, hazır ayar tanıma, kalıcılık;
  SIMUMAV `channelsOf` eğrili/eğrisiz; pencere boyutu (oran, sınırlar, tutamaç), kırpma, yapışma, engelden kaçınma (kalabalık ekran dâhil), oranlı kayıt ve
  ekran boyutu değişimi; tema enum/döngü/kalıcılık/önizleme SVG/metinler; giriş yolu (100 m başlangıç, bitiş ofseti, monoton iniş, spiral açı), geri sayım
  durumları, bip planı, ses tercihi.
- Görsel: `tests/flyui_shots_hepgo.py`, `tests/flyui_shots_simumav.py` → `/tmp/flyui-shots/` (sihirbaz gösterge kartları açık/koyu, giriş sekansı kareleri,
  hassasiyet paneli, radar/EO taşınmış + büyütülmüş + yeniden yükleme sonrası + sıfırlama, 5 tema × açık/koyu).

## 30. Radar/EO tam görüntü, EO elle kumanda, alt bant uçuş denetimi, çarpışma efekti (HEPGO + SIMUMAV ortak)
Kullanıcı bildirimleri (Google 3B, Ankara, elevon + rampa): radar ve EO ekranında harita "yarım" (bir kısmı siyah); EO'da tekerlek zoom ve basılı sürükle
pan/tilt istenir; EO kendiliğinden dönmesin; alt bantta tüm kamera kiplerinden mod değiştirme; DISARM'da sabit kanat düşmesin, süzülsün; çarpışma efekti
ve daha yüksek darbe sesi; "PREARM: check mag field" uyarısı; sanal kumanda hassasiyeti düğmesi fark edilmiyor.

### 30.1 Radar / EO / PiP / nişangâh "yarım" görüntü — kök neden ve düzeltme
- **Kök neden (Google 3B):** 3DTilesRenderer karo seçimini (frustum + LOD) yalnız `setCamera` ile kaydedilmiş kameralara göre yapar; oturumda yalnız ANA kamera
  kayıtlıydı. Radar (kule merkezli 20 km eğik bakış), EO (kuleden hedefe), kamera PiP'i (§22.4) ve nişangâh (§27) aynı sahneyi başka kameralarla render
  hedefine çizer → ana kameranın görmediği bölgelerde karo YÜKLENMEZ / gizlenir → görüntünün o kısmı siyah (sahne arka planı).
- **Düzeltme:** `flightsim_g3d.setAuxCameras([{cam, w, h}])` — etkin ikincil kameralar her karede kendi render hedefi çözünürlüğüyle (`tiles.setResolution`)
  karo yükleyicisine eklenir, kapanan silinir (`deleteCamera`); karo kümesi tüm kameraların birleşimi, LOD gereken en ince. `flightsim3d.auxCameras()`: PiP açık,
  radar/EO dikdörtgeni var, nişangâh penceresi açıkken. Teşhis `siteStats().aux`. Yeni WebGL bağlamı YOK (tek renderer kuralı). Küçük render hedefleri
  (≈ 240×160) kaba LOD ister → ek karo yükü düşük.
- **Dünya kenarı (gerçek arazi 4–20 km + 48 km uzak halka, prosedürel 4 km):** radar kapsaması 50 km'ye dek → kenar ötesi boştu. **Radar altlığı**: kule
  merkezli ±2,5·kapsama karesi, YALNIZ radar geçişinde görünür, derinlik testi/yazımı kapalı + en düşük renderOrder (önce çizilir; arazi/karo üstüne yazar).
  Doku: gerçek/Google dünyada uydu karoları (`/api/drone/sim/tile/img` vekili, eksen başına ≤ 8 karo — saf `flightsim_gcs.underlayPlan/underlayUV`; Ankara
  20 km → z 11), prosedürelde (ya da karo alınamazsa) arazi paletinde tohumlu gürültü. Teşhis `siteStats().underlay` (`proc` | `img z11 49/49`).

### 30.2 EO elle kumanda (`flightsim_gcs_ui.js` EO gövdesi + 3B `eoWheel / eoPinch / eoDrag / eoFollow`; saf `eoWheelFov / eoPinchFov / eoDragLook / eoAimMode`)
- **Zoom:** fare tekerleği (üstel: FOV · e^(0,0016·deltaY); her konumda aynı oransal adım, 48°…0,35° = ×1…×137), dokunmatikte iki parmak sıkıştırma. Elle zoom
  izlemedeki oto yakınlaştırmayı geçersiz kılar; yumuşak geçiş. Elle zoomda optik pus da azalır.
- **Pan/tilt:** EO GÖRÜNTÜSÜNE basılı tut + sürükle (fare, dokunmatik tek parmak, kalem): "tut ve sürükle" — görüntüdeki nokta imleçle kayar; hassasiyet zooma
  göre (1 px = FOV / görüntü yüksekliği); el −60…+85°. Pencere YALNIZ başlık çubuğundan taşınır (gövde sürüklemesi kamerayı çevirir).
- **Takip:** elle pan/tilt hedef takibini bırakır (OSD "ELLE · n ad"); başlıkta sarı **◎ TAKİP** düğmesi, EO'ya çift tık ya da yeni hedef seçimi (Tab / radar
  tıklaması) takibe + oto zooma döndürür. **Hedef yokken başlık son yönde sabit** (eski 8°/sn kendiliğinden tarama kaldırıldı; ilk yön pist yönü).

### 30.3 Alt bant uçuş denetimi (`static/js/modules/flightsim_fltbar.js`; HEPGO `flightsim.js`, SIMUMAV `fly/session.js`)
- **Mod seçici** (alt bant, harekât paneli açıkken de ve tüm kamera kiplerinde): etkin mod renkli rozet (Q kipleri mor, AUTO/GUIDED yeşil, RTL/LAND sarı);
  tıkla ya da **F** → mod ızgarası (ok tuşları + Enter, Esc). Liste araç ailesine göre (`flightModesFor`): sabit kanat MANUAL, STABILIZE, ACRO, FBWA, FBWB,
  CRUISE, TAKEOFF, AUTO, LOITER, CIRCLE, GUIDED, RTL; VTOL + "Dikey (Q)" grubu QSTABILIZE, QHOVER, QLOITER, QACRO, QLAND, QRTL; INTERCEPTOR (tailsitter) yatay
  + Q; kopter STABILIZE, ALT_HOLD, LOITER, POSHOLD, ACRO, GUIDED, AUTO, BRAKE, CIRCLE, RTL, SMART_RTL, LAND. Komut harekât panelinin `mode` komutu (sunucu
  pymavlink mod eşlemesiyle doğrular). Eski `.fs-cmds` içindeki ARM düğmesi ve mod `<select>`'i buraya taşındı (Kalkış/RTL yerinde).
- **DISARM düğmesi** (**X**; saf `disarmAction(kind, tele)`): disarm'lı → ARM; yerde → DISARM; **havada sabit kanat** (ve yatay kipte VTOL/INTERCEPTOR) →
  **motor kes** (`motor_cut {on:true}` — §30.4): motor durur, uçak süzülür, kumanda yüzeyleri çalışır; düğme **MOTOR VER** olur, sahnede sarı "MOTOR KESİK ·
  SÜZÜLÜYOR" bandı; **havada kopter / askıdaki VTOL** → onay penceresi ("araç DÜŞER") sonra gerçek DISARM. Havada = irtifa > 3 m ya da hız > 6 m/s.
- **Kumanda hassasiyeti** (§27.1) düğmesi artık açık etiketli: kaydırıcı simgesi + "Hassasiyet" (< 900 px yalnız simge + title); sanal kumanda kapalıyken de
  görünür (klavye de aynı eğriden geçer).
- Metinler: HEPGO Türkçe anahtar (6 dil kataloğu), SIMUMAV `flt.*` (7 dil).

### 30.4 DISARM / motor kesme — ArduPlane davranışı ve sunucu komutu (`app/flightsim.py` `motor_cut`, `_motor_kes`)
- **Kök neden ("DISARM'da direkt düşüyor"):** gerçek ArduPlane 4.7.2 SITL'de havada zorla disarm (400, 21196) uçağı aslında düşürmez — yüzeyler stabilize
  etmeye devam eder, fizik süzülür (vz ≈ 1,2 m/s) — ama ArduPlane disarm'lıyken **HOME'u o anki konuma taşır** (home 900 → 1047 m): `alt_rel` 0,7 sn'de
  145 → −11 m'ye "düşer" (HUD/AGL/çarpışma görüntüsü), `alt_msl` doğru kalır; yeniden ARM'da HOME geri gelmez (RTL disarm noktasına döner). Sunucu
  disarm'ı çarpışma saymaz. Bu yüzden havada sabit kanat için DISARM yerine motor kesme kullanılır.
- **Seçilen yöntem:** `MAV_CMD_DO_AUX_FUNCTION` (218), RC seçeneği 31 **MOTOR_ESTOP** — HIGH keser, LOW geri verir. Tüm kiplerde (MANUAL/TAKEOFF dahil)
  SERVO3 = 1000 µs; ARM, HOME ve irtifa korunur; yüzeyler çalışır; parametre yazmaz. (THR_MAX=0 MANUAL'de motoru kesmez — elendi.)
- **Komut:** `{name:'motor_cut', params:{on:true|false}}` → `{ok:true, motor_cut}`; `on` bool değilse 400; aynı değer idempotent; kopter tiplerinde 400 (UI
  orada onaylı gerçek DISARM kullanır). WS `tele` ve oturum `to_dict`'te **`motor_cut`** (bool); kesikken `tele.throttle` 0 (yakıt tüketmez). Olay şeridi:
  "MOTOR KESİLDİ — süzülüyor" / "Motor geri verildi". Motoru geri verenler: `motor_cut {on:false}`, `arm`, `takeoff`, `reset` (interceptor konuşlandırma
  dahil), çarpışma (`zorla_disarm`). Araç 218'i reddederse bayrak geri alınır. SIMUMAV `SIM_KOMUT = set(KOMUTLAR)` ile kendiliğinden kabul eder.
- **Sahte kip:** itki yok, L/D 10, 12 m/s; RC1 yatışı (≤ 45°) koordineli dönüş; 100 m'den ≈ 84 sn / ≈ 1 km; motor geri verilince daireye ışınlanmadan döner.
  Sahte kipte havada disarm edilen uçak da artık süzülür (eskiden havada donardı).
- **Ölçüm (gerçek SITL, stok `plane` modeli, rüzgâr 0, kesmeden sonra 20–40 sn ortalaması; rulo = 6 sn RC1 1850):**

| Yol | Kip | Batış | Hava hızı | L/D | 100 m → yer | Rulo yanıtı |
|---|---|---|---|---|---|---|
| zorla disarm | FBWA | 1,20 m/s | 7,8 m/s | 7,2 | 82 sn / 699 m | Δhdg 163°, yatış 27° (alt_rel bozulur) |
| e-stop | FBWA | 1,15 | 7,6 | 7,2 | 86 sn / 712 m | 144°, 24° |
| e-stop | FBWB | 1,14 | 7,5 | 7,2 | 82 sn / 666 m | 134°, 23° |
| e-stop | CRUISE | 1,14 | 7,5 | 7,2 | 86 sn / 711 m | 132°, 23° |
| e-stop | AUTO | 1,12 | 7,5 | 7,3 | 82 sn / 683 m | 142°, 16° |
| e-stop | RTL | 1,19 | 7,5 | 6,9 | 84 sn / 700 m | 96°, 14° |
| e-stop | MANUAL | — | — | — | stabilizasyon yok | tam aileron spiral dalış (pilota bağlı) |

  Otomatik gazlı kiplerde TECS irtifa tutmaya çalışır, elevatör doyar → ~7,5 m/s'de stall sınırında fügoid salınımlı süzülme (stok SITL modelinin motorsuz
  L/D'si ≈ 7). VTOL/INTERCEPTOR'da e-stop VTOL motorlarını da durdurur — askıda (Q kipi) UI onaylı DISARM ister.

### 30.4.1 PreArm "Check mag field (xy diff:338>100)" — kök neden
- Konum/declination değil: dron kaydı seçilen oturumlarda **gerçek uçağın kalıcı parametre kaydındaki pusula kalibrasyonu** (`COMPASS_OFS*`, `COMPASS_USE2/3=0`,
  `COMPASS_DEC` + `AUTODEC=0`, `COMPASS_ORIENT`) SITL'in ideal sanal pusulasına uygulanıyordu → Ankara'da birebir "xy diff:276–327>100"; temiz SITL'de yok.
- Düzeltme (`app/drone_params.py`): `COMPASS_*`, `AHRS_ORIENTATION`, `INS_ACC*OFFS_/SCAL_`, `INS_ACC*/GYR*_ID` SITL'e YAZILMAZ (varsayılan .parm ve
  PARAM_SET), kayıtta ve .param dışa aktarımında korunur; açılışta olay satırı ("N sensör kalibrasyonu/yönelimi parametresi … simülasyonda uygulanmadı");
  SITL'in ürettiği sensör değerleri gerçek kaydın üstüne yazılmaz. `ARMING_CHECK`'e dokunulmadı. Ankara, 41 K 29 D, 37 K 35 D'de uyarı yok (heading 0,3°).

### 30.5 Çarpışma efekti ve darbe sesi (`static/js/modules/flightsim_crashfx.js`, `flightsim_audio.js impactParams`)
- Çarpışma bandı açıldığında (sunucunun kesin `crash` çerçevesi) `sim.crashFx({speed})`: dronun çizilen konumunda **beyaz flaş** (≈ 0,2–0,4 sn, DOM katmanı),
  **ateş topu** (toplamalı sprite'lar; büyür, yükselir, söner), **toz bulutu** (yavaş yayılan kahverengi sprite'lar, 3,5–6,5 sn), **kıvılcım/enkaz** (≤ 200 nokta,
  balistik + sürüklenme, zemine iner), **kor** (küçük, 6–14 sn; `userData.heat = 1` → TERMAL kamerada sıcak nokta; ateş topu/kıvılcım toplamalı = parlak = sıcak),
  **kamera sarsıntısı** (üstel sönen çok frekanslı öteleme + yuvarlanma; render sonrası geri yüklenir — takip/serbest kamera pozu bozulmaz). Şiddet çarpma
  hızıyla (`crashFxParams`: 3 m/s → 0,2…0,3; ≥ 40 m/s → 1), boyut model çapıyla (×0,4…×2; 1 m'lik dronda dev ateş topu yok). Sıfırla → temizlenir.
  Teşhis: `crashFxInfo()`, `window.__fsCrashHold = t` (efekti t. saniyede sabitler — yazılım WebGL görsel betikleri).
- **Ses:** ayrı "darbe" yolu (master'dan bağımsız, ses düzeyi × `IMPACT_BOOST` 2,2 → kompresör → çıkış): alçak "bum" (frekansı düşen sinüs + alt üçgen),
  kapanan lowpass enkaz gürültüsü, highpass kıvılcım çıtırtısı; şiddet çarpma hızıyla (`impactParams`). Ses kapalıysa (tercih / sekme gizli) çalmaz.
- Ek: kapanmış AudioContext'i ikinci kez kapatma reddi yakalandı (giriş bip'i, motor sesi — konsolda "Cannot close a closed AudioContext").

### 30.6 Testler ve görsel doğrulama
- `tests.test_flightsim` `motor_cut_birim_testleri`, `motor_cut_testleri`, `sensor_param_testleri`.
- `node tests/test_flightsim_simfix.mjs` (tekerlek/sıkıştırma/sürükleme, nişan kipi, altlık planı + UV, çarpışma parametreleri/sarsıntı/flaş/kıvılcım, mod listeleri,
  `disarmAction`, metinler); `tests/test_flightsim_audio.mjs` darbe sesi.
- Görsel: `SIMFIX_WORLD=procedural|real|google3d ./.venv/bin/python -m tests.simfix_shots_hepgo` → `/tmp/simfix-shots/` (radar/EO tam görüntü + boş piksel oranı,
  EO izleme/zoom/pan, radar 5/20 km, PiP, çarpışma flaş/ateş topu/toz/termal EO, mod menüsü, motor kesme süzülmesi, panel açıkken bant).

## 31. KARA ARACI — ArduRover (`rover`; `drone_sitl.TIP_ESLEME['rover']`, `static/js/modules/flightsim_rover*.js`; HEPGO + SIMUMAV ortak)

Kullanıcı isteği: "Araçlara rover yani kara araçlarını da ekleyelim."

**SITL.** Tip `rover` → ikili `ardurover` (resmi **Rover stable-4.7.2**, yamasız; `drone_sitl.indir` kalıbıyla `firmware.ardupilot.org/Rover/stable-4.7.2/SITL_x86_64_linux_gnu/ardurover`).
DEV: `/opt/hepgo/sitl/bin/ardurover` (sha256 `f453fd8217b9d798c873e5c424e139a2a3597b52e31658f76b2c177b523391af`, 6 845 664 bayt). PROD: HEPGO `HEPGO_SITL_DIR`
(`/opt/hepgo/caymazbuild/data/sitl`) — ikili yoksa ilk rover oturumunda kendiliğinden indirilir (aynı sha). SIM_SRV_REV / SIM_PLN_THR_MUL yamaları rover'da
gerekmez (sanal montaj nötr yol; azami hız uçak tiplerinde).
- Sürüş biçimi `drive`: `ackermann` → `--model rover` (ön teker direksiyonu; SERVO1 26 GroundSteering, SERVO3 70 Throttle) · `skid` → `--model rover-skid`
  (paletli / diferansiyel; SERVO1 73 ThrottleLeft, SERVO3 74 ThrottleRight). Oturum gövdesinde isteğe bağlı; yoksa görsel modelin `drive`'ı (dahili 4×4 →
  ackermann, paletli UGV / teslimat robotu → skid). Bilinmeyen değer 400. `to_dict`: `ground: true`, `drive`.
- `varsayilan.parm`: ArduPilot `Tools/autotest/default_params/rover.parm` özü (CRUISE_SPEED 5, CRUISE_THROTTLE 30, ATC_SPEED_P 0,1, ATC_STR_RAT_FF 0,75,
  WP_RADIUS 3, WP_SPEED 5, RC1/RC3 ve SERVO1/SERVO3 1000–2000, BATT_MONITOR 4) + skid'de `rover-skid.parm` (CRUISE 3 m/s @ %75, 73/74). Kayıtlı parametreler sonra.
- Kalp atışı MAV_TYPE_GROUND_ROVER (10) → kip doğrulaması pymavlink rover eşlemesi: MANUAL, ACRO, STEERING, HOLD, LOITER, FOLLOW, SIMPLE, AUTO, RTL,
  SMART_RTL, GUIDED (+ LEARNING, INITIALISING). Başlangıç MANUAL.
- **Kalkış yok**: `cmd takeoff` 400 ("Kara aracında kalkış yok…"), hub `takeoff` reddedilir, hub `land` → HOLD. `motor_cut` 400. DISARM her zaman yerde.
- RC: RC1 direksiyon, RC3 gaz — **1500 = dur**, 2000 tam ileri, 1000 tam geri (fren). Sanal kumanda: sol çubuk dikey gaz (yaylı), sağ çubuk yatay direksiyon;
  W/S ↑↓ gaz, A/D ←→ direksiyon, Boşluk dur (`flightsim_rover.roverRcChannels`; RC2/RC4 0 = dokunma).
- Konum isteyen kipler (AUTO / RTL / GUIDED / LOITER) EKF GPS'i kullanmaya başlayana dek (ölçüm: kalp atışından ≈ 30 sn sonra "EKF3 IMU0 is using GPS")
  reddedilir ("Flight mode change failed"); MANUAL hemen çalışır.
- Sahte kip (HEPGO_SITL=0) `SahteKinematik._surus`: SIM_Rover sabitleri (Ackermann azami 20 m/s, 35° teker, 1,8 m dönüş çapı; skid 4 m/s, 140°/sn),
  RTL eve sürüp HOLD'a geçer, otomatik kiplerde merkez çevresinde tur; `tele.servo` ArduRover çıkışı taklidi.
- Güç: `ROVER_VARSAYILAN` elektrikli (yakıt 0 L; 4S 16000 mAh 60 W; içten yanmalı araç için L / km/L girilir), azami hız yok; menzil hesabı seyir 5 m/s @ gaz 0,3,
  azami 20 m/s (`menzil_sure` / JS `flightBudget` birebir).
- Kayıtlı simülasyon alanları (`ALANLAR` / `PRESET_FIELDS`) `drive` içerir. Replay: ArduRover logu → tip `rover`. Hedef kataloğu kara araçlarını içermez.

**Modeller** (`tools/rover_models_build.py`, prosedürel GLB; `static/simumav/models/rover_{4x4,ugv,bot}.glb`; LICENSES.md): `builtin:rover_4x4` Keşif 4×4
(2,2 m, Ackermann; `steer_fl/fr` → `wheel_fl/fr`, `wheel_rl/rr`), `builtin:rover_ugv` Paletli UGV (2,5 m; `track_l/r`, `wheel_l1..7`/`wheel_r1..7`),
`builtin:rover_bot` Teslimat robotu (0,78 m, 6 teker). Kök düğüm extras: `drive`, `wheelbase`, `track`, `cockpit` (sürücü gözü), `sensor` (gimbal) noktaları.

**3B** (`flightsim3d.js` + `flightsim_rover3d.js` + saf `flightsim_rover.js`):
- Kara aracı **gerçek boyutta** (×1; uçaklar ×2,5). SITL'den yalnız yatay konum ve yön alınır; **yükseklik + eğim + yatış 3B zeminden**: 4 temas noktası
  (dingil × iz) ≈ 16 Hz örneklenir — Google 3B `g3d.surfaceAt(x, y, err, top)` (ışın aracın 4 m üstünden: ağaç tacı / köprü sayılmaz; kaba karo → önceki değer),
  gerçek arazi örgüsüne ışın, prosedürelde analitik yükseklik. Köşe yükseklikleri süspansiyon yayından (`createSuspension`, 3,2 Hz) geçer, `roverGroundFit`
  düzlemi z + eğim + yatışı verir; köşe sıkışması teker düğümlerine ofset olur.
- Tekerler yer hızıyla döner (sol/sağ ayrı — skid/palet), Ackermann ön tekerleri servo çıkışından (yoksa bisiklet modeli δ = atan(L·ω/v)) iç/dış
  Ackermann açısıyla döner; hız > 1,5 m/s'de arka tekerlerden toz izi (`setRoverDust`).
- Kameralar: **takip** = kovalama (araç dönünce bakış açısı da döner; zemine gömülmez), **2 FPV = KOKPİT** (sürücü gözü, 80°, balıkgözü yok, gövdeyle eğilir),
  **3 gimbal** = sensör başlığı, serbest, yer. Çarpışma: arazi teması çarpışma değil; bina ve derin su (> 0,6 m) çarpışmadır.
- Gösterge (`flightsim_rover_hud.js`; createMilHud / createFpvOsd rover oturumunda bunu döndürür): hız km/h + vites (P/N/D/R), direksiyon yayı, GAZ/FREN
  çubukları, pusula şeridi + EV yönü, **irtifa yerine EĞİM / YATIŞ** inklinometresi (> 25° / 20° "DEVRİLME RİSKİ"), kip/ARM, batarya/yakıt, EV mesafesi.
  Teşhis: `window.__fsSim.roverState()`.
- Alt bant mod seçici `FLIGHT_MODES.rover`; harekât paneli "SÜRÜŞ GÖSTERGESİ" (km/h + eğim bandı), Kalkış yerine "Dur (HOLD)".

**Sihirbaz**: Araç adımında "Kara Aracı" kartı; Kalkış ve kontrol düzeni adımları yok; Sürüş biçimi kartları (Ackermann / Paletli-diferansiyel; varsayılan
modelin); güç adımı rover varsayılanları; hedefler / yer kontrol isteğe bağlı ("Yer kontrolünü koru" yalnız INTERCEPTOR). CAYSIM `GET /types` `rover` içerir,
oturum gövdesi `drive` kabul eder. SIMUMAV: docs/simumav.md §15.

**Ölçüm (gerçek ArduRover 4.7.2 SITL, `tools/sitl/dogrula_rover.py`; Mission Planner yerine pymavlink UDP ile 3 noktalı ≈ 60 m görev):**

| | Ackermann (`rover`) | Skid (`rover-skid`) |
|---|---|---|
| kalp atışı / EKF GPS | 3,0 sn / 32 sn | 3,0 sn / 32 sn |
| ARM (MANUAL) | 1,0 sn | 1,0 sn |
| MANUAL düz, RC3 1800 (%60) 8 sn | azami 11,1 m/s, 65,9 m | azami 2,3 m/s, 17,2 m |
| MANUAL dönüş (RC1 2000) 6 sn | yön hızı ≤ 370°/sn (SIM_Rover 1,8 m dönüş çapı), servo [2000, –, 1680] | yerinde dönüş ≤ 206°/sn, servo sol 2000 / sağ 1265 |
| HOLD ile durma | 6,2 sn | 0,6 sn |
| AUTO 3 WP (MP yüklemesi ACK 0; 3B rota 3 nokta) | 12,4 / 24,2 / 35,9 sn; en yakın 2,6 / 3,4 / 3,7 m; ort. 3,8 m/s | 16,2 / 33,1 / 51,3 sn; 1,6 / 1,6 / 3,5 m; ort. 2,7 m/s |
| RTL eve varış | 12,2 sn, 2,5 m (kip RTL'de kalır, araç durur) | 10,8 sn, 2,6 m |
| takeoff / motor_cut | 400 / 400 | 400 / 400 |
## 32. Gerçekçi dünya, hava durumu, rüzgâr fiziği ve göstergeleri, rampa yön/açı arayüzü (HEPGO + SIMUMAV ortak)
Kullanıcı isteği (özet): Google olmayan dünyada (prosedürel + gerçek arazi) binalar/ağaçlar/dağlar gerçekçi değil → gerçekçi arazi, ağaç, bina, gökyüzü, gölge,
su; atmosfer seçenekleri (yağmur, kar, sis, bulutlu, açık, fırtına); rüzgâr dronlara GERÇEKTEN etki etsin (SITL ölçümü), türbülans ve esinti; 3B rüzgâr
tulumu + HUD rüzgâr göstergesi (baş/yan/kuyruk); rüzgâr akış çizgileri; rampaya tıklayınca yön/açı arayüzü (ARM öncesi, SITL'e uygulanır).

**Modüller.** Saf kurallar `static/js/modules/flightsim_weather.js` (three.js'siz; `tests/test_flightsim_worldfx.mjs`), çizim
`static/js/modules/flightsim_worldfx.js` (`createWorldFx(T, {renderer, scene, preview})` — flightsim3d.js içinden, TEK WebGL bağlamı; ek bağlam/tuval yok,
mercek damlaları DOM 2B tuvali), DOM göstergeler `static/js/modules/flightsim_windui.js` (`createWindGauge`, `createRampPanel`; HEPGO Türkçe anahtar,
SIMUMAV `wfx.*` anahtarları — `makeWfxT(tr, keyed)`, fltbar kalıbı; stiller modülde tek `<style>`). Sunucu `app/flightsim.py` (`WEATHER`, `esinti_carpani`,
`ruzgar_vektoru`, `ruzgar_dogrula`, `rampa_aim_dogrula`, `kalkis_yonu`, `SimSession.ruzgar_degistir / rampa_ayarla / _esinti_adim`, `SahteKinematik` rüzgâr),
`app/drone_sitl.py baslat(..., yon=)`, SIMUMAV `app/simumav/bridge.py _world` (+ `FOG_HAVA`, `WEATHER_CEKIRDEK`), `routers/fly.py guvenlik_komut`.

### 31.1 Dünya gerçekçiliği (`flightsim_worldfx.js`; prosedürel + gerçek arazi; Google 3B'de gök/sis/yağış/tulum/akış çizgileri)
- **Arazi (prosedürel, `makeTerrain`)**: 6 oktav fbm (lacunarity 2,03) + alan bükme (kıvrımlı vadiler) + dağlık bölgede (fbm maskesi) çok-fraktal **sırt**
  gürültüsü (keskin tepe hatları, erozyon benzeri dereler). Izgara 320×320 (önizleme 160); `height(x, y)` her noktada tanımlı → **ufuk halkası**
  (dünya genişliğinin 8 katı, 128×128; ana karenin içinde 2 m altta saklı, dikişsiz) — dağlar dünya kenarında bitmez; sis ufku `size·3` (halkayı aşmaz).
- **Zemin malzemesi** (`patchGround`, MeshStandard + onBeforeCompile): prosedürelde yükseklik/eğime göre **çim** (iki ton + mezo/makro gürültü lekeleri) /
  **toprak** lekeleri / **kaya** (eğim > ~0,3 ve yüksek kesimler; katman şeritleri) / doğal **kar** (dağ ≥ 150 m ise yüksekliğin %74'ü üstü, düz yüzeyler) /
  su kıyısında **kum**; iki ölçekli (7,5 m + 31 m) prosedürel ayrıntı dokusu + **normal haritası** (canvas'ta üretilir, tekrarlanabilir; 250–2200 m'de söner).
  Gerçek arazide uydu dokusu üstüne aynı ayrıntı + normal. **Hava**: kar örtüsü (`snowCover`, düz yüzeyler beyazlar, gürültülü sınır), ıslaklık (`wet`:
  koyulaşma × 0,56 + pürüzlülük 0,22 → güneşte parlama); yollar da ıslanır (`patchWet`).
- **Gökyüzü** (kameraya bağlı kubbe, uzak düzlemde): ufuk/zenit gradyanı, güneş diski + Mie parıltısı, **güneş konumu saat ön ayarına göre**
  (`sunPosition`: gündüz 52°/150°, akşam 4°/252°, gece ay 28°), gece yıldızlar + ay, bulutlulukta kapalı gök, fırtınada **şimşek** (5–16 sn'de bir çakma;
  hemi ışık + gök). Sis rengi = pusa çekilmiş ufuk rengi → atmosferik saçılım dikişsiz; ışıklar (güneş/hemi/ortam) saat + hava ile.
- **Bulut katmanı**: tek düzlem (90 km), gölgelendiricide 2 katman fbm; örtü hava ön ayarından, rüzgârla kayar (×2,5 irtifa), güneş yönüne göre gölgeli,
  uzakta sise karışır/söner, kamera katmana 60 m'den yakınken saydamlaşır; taban arazi + 700…900 m (≥ 1500 m).
- **Su** (gölgelendirici; prosedürel düzlem + OSM su çokgenleri): Fresnel gökyüzü yansıması, 3 katman hareketli dalga normali (uzakta düzleşir — piksel
  altı parıltı yok), güneş parlaması, yağmurda halka dalgacıkları. Termalde soğuk (heatWorld).
- **Ağaçlar**: iki tür — iğne yapraklı (gövde + 3 katmanlı koni, uçta açık/tabanda koyu köşe rengi) ve geniş yapraklı (gövde + 3 bozulmuş ikosahedron
  topak); tür biyom gürültüsü + yükseklikle (yükseklerde iğne yapraklı). **Parçalı InstancedMesh** (~450 m hücre × tür; parça başına frustum ve gölge
  kutusu ayıklaması) + **LOD**: kameradan ~520 m'ye dek 3B model, ötesinde çapraz düzlem **impostor** (canvas atlası, alphaTest); 5 Hz güncellenir.
  **Rüzgârda salınım**: köşe gölgelendiricisinde tepe yer değiştirmesi (yükseklik², rüzgâr yönü + küçük daire; ağaç başına faz). Kar havasında taçlar açılır.
- **Binalar (prosedürel + gerçek kipte "ek bina")**: **kasabalar** — merkezden 520 m+ düz alanlarda (180 m'de ≤ 25 m fark) sokak ızgarası (66 m blok, 8 m
  asfalt + iki yanda kaldırım şeridi; araziye serili şerit geometrisi), türler merkezden uzaklıkla: **kule** (cam cephe, 36–82 m), **apartman** (3–9 kat,
  çatı üniteleri), **müstakil ev** (1–2 kat, **beşik çatı** kiremit/antrasit), kenarda **sanayi**; kalan kota kırsalda ev/ahır. Cephe gölgelendiricisi
  (`patchFacade`): kat (3–3,6 m) / bölme ızgarasında **pencereler** (türüne göre oran), cam gök yansıması rengi + düşük pürüzlülük, zemin kat bandı,
  korniş, taban koyulaşması; **gece rastgele ışıklı pencereler** (sıcak, emissive). OSM binaları (gerçek kip) aynı gölgelendiriciyle (öznitelik `aFac` =
  çevre boyunca u, taban üstü v, çatı; `aBld` = tür/tohum/yükseklik) — eski çatı köşesi ışık noktaları kalktı. Çarpışma AABB'leri döndürülmüş taban sınırından.
- **Gölgeler**: güneş gölge kutusu dronun çevresinde ±90 m (2048², normalBias), binalar, yakın ağaç parçaları, tulum ve düzenek gölge düşürür.
- **Performans** (orta düzey dizüstü ≥ 45 fps hedefi): instancing (ağaç/bina/çatı), parça frustum ayıklaması, ağaç LOD, impostor, gökyüzü tek kubbe,
  yağış ve akış çizgileri GPU'da (CPU'da parçacık güncellemesi yok), dokular canvas'ta bir kez (paylaşılan program önbellek anahtarları). Ölçüm §31.7.

### 31.2 Hava durumu (`world.weather`; sihirbaz Dünya adımı)
`clear | cloudy | rain | snow | fog | storm` (Açık hava · Bulutlu · Yağmurlu · Karlı · Sisli · Fırtınalı). Ön ayarlar `WEATHER_PRESETS` (bulut örtüsü, yağmur/kar
yoğunluğu, ıslaklık, kar örtüsü, ışık çarpanı, görüş çarpanı, pus, şimşek). **Görüş**: `fogRange(fog, weather, {size|horizon})` — "açık"ta eski formülle
birebir aynı (geri uyum), diğerlerinde sis uzaklığı × `vis` (sis ≤ 900 m). **Yağış**: kameraya bağlı 60–70 m'lik hacimde GPU parçacıkları — yağmur çizgi
(14 000 × yoğunluk; düşüş 9–12 m/s), kar tanesi (9 000; 1,1 m/s + salınım), rüzgârla sürüklenir (yatay hız = rüzgâr vektörü). **FPV/gimbal'da mercek
damlaları** (yağmur/fırtına; DOM tuvali, ≤ 26 damla, büyük damla akar). Sihirbaz: Dünya adımında hava segmenti (simgeli), özet kartında "Hava durumu".
**Google 3B**: gök kubbesi, sis, yağış, bulut, tulum, akış çizgileri aynen; karolar havaya göre koyulaşır (`g3d.setWeatherLight`). Termal kamerada gök/bulut/
yağış/akış çizgileri gizlenir (gök soğuk). **SIMUMAV**: parkur hava durumu (`bridge.WEATHER` clear/cloudy/rain/fog/snow) → `world.weather` birebir
(`worldFromTrack` + `bridge._world`); görüşü hava kıstığından parkurun sis değeri yalnız hafif pus (`FOG_HAVA`, çift kısma yok); parkur düzenleyicisine
**kar** eklendi.

### 31.3 Rüzgâr fiziği — SITL (`SIM_WIND_SPD/DIR/TURB`), esinti, uçuşta rüzgâr; sahte kinematik
- **Doğrulama**: SITL'e rüzgâr ZATEN yazılıyordu (`_ruzgar_yaz`, ilk kalp atışında `SIM_WIND_SPD = wind_ms`, `SIM_WIND_DIR = wind_dir`; SIM_WIND_DIR =
  rüzgârın GELDİĞİ yön). Artık + `SIM_WIND_TURB = wind_turb` (ArduPilot SITL rastgele türbülansı, m/s). `SIM_WIND_*` kalıcı parametre kaydına girmez
  (`drone_params.HARIC_ONEKLER`).
- **Esinti** (`world.wind_gust`, 0–20 m/s): sunucu `_dongu` 1 Hz'de `SIM_WIND_SPD = wind_ms + wind_gust · g(t)` yazar; `g(t) = esinti_carpani(t)` (üç
  uyumsuz sinüs, kare; JS `gustFactor` ile birebir — iki test aynı tabloyu doğrular), t = SITL saati (`tbm`). `tele.wind_spd / wind_dir` anlık değer
  (tulum, gösterge, akış çizgileri bunu kullanır; yoksa istemci aynı formülle hesaplar).
- **Uçuşta rüzgâr** — `cmd wind {ms?, dir?, gust?, turb?}` (KOMUTLAR; verilmeyen alan korunur; sınırlar world ile aynı): dünya güncellenir, SITL'e
  PARAM_SET, olay şeridi, WS `{t:'wind', wind_ms, wind_dir, wind_gust, wind_turb}`. HEPGO rüzgâr göstergesinde ✎ (yazma izni). **SIMUMAV'ta kapalı**
  (`guvenlik_komut`: "Rüzgâr parkur ayarıdır"; adil skor) — parkurun rüzgârı + esintisi (`track.wind.gust` artık çekirdeğe gidiyor) uygulanır.
- **Sahte kinematik** (`HEPGO_SITL=0`): `ruzgar_ayarla(ms, yön, esinti, türbülans)`; dairede yer izi korunur (ArduPilot loiter gibi), **yer hızı = iz boyu
  rüzgâr + √(V² − yan²)** (hava hızı sabit V), burun hava hızı yönünde (**yengeç açısı**), kopter rüzgâra karşı eğilir (~1°/m/s, ≤ 25°), türbülansta
  yönelim salınımı, süzülmede hava kütlesiyle sürüklenme, tekerlekli kalkışta baş rüzgârı döndürme yer hızını düşürür; `airspeed` artık gerçek hava hızı
  (eski `+ rüzgâr·0,3` hilesi kalktı).
- **Gerçek SITL ölçümü** (`tests/wind_sitl_olcum.py`; ArduPilot 4.7.2 SITL, HEPGO oturum kodu üzerinden — `wind` komutu, esinti döngüsü, `launch_aim`):

| Senaryo (rüzgâr 270°'den) | Ölçüm |
|---|---|
| Kopter, rüzgâr 0 | LOITER ort. eğim 1,5° · ALT_HOLD'da (konum tutma yok) 15 sn sürüklenme **0,9 m** |
| Kopter, rüzgâr 8 m/s (`wind` komutuyla uçuşta) | LOITER ort. eğim **10,7°** (rüzgâra karşı yatar, konum tutar) · ALT_HOLD 15 sn sürüklenme **57,4 m doğuya** (rüzgâr yönü) |
| Kopter, esinti 5 + 5 m/s | `tele.wind_spd` 5,0…8,1 m/s (SITL `SIM_WIND_SPD` PARAM_VALUE ile teyitli) |
| Uçak LOITER, rüzgâr 0 | yer hızı 30,5…34,7 (aralık 4,3) · hava hızı 30,7 ± 1,1 m/s |
| Uçak LOITER, rüzgâr 8 m/s | yer hızı **22,2…42,6 (aralık 20,4 ≈ 2×8 + temel)** · hava hızı 30,0 ± 1,7 m/s |
| Uçak LOITER, rüzgâr 8 + türbülans 3 | yer hızı 23,4…46,7 (aralık 23,3) · hava hızı 32,7 ± **1,9** m/s (oynaklık artar) |
| Rampa azimut 120° (oturum açılışı) | SITL ilk yön **120,0°** (`--home …,120`) |
| `launch_aim` 210° / 20° | `redeploy: true`, 3,1 sn'de HAZIR, `TKOFF_LVL_PITCH 20`; fırlatma yer izi kerterizi **209,0°** |
| `launch_aim` yalnız açı 25° | `redeploy: false`, `TKOFF_LVL_PITCH 25` (yeniden başlatma yok) |

Sonuç: rüzgâr önceden de SITL'e yazılıyordu ve fiziksel olarak etkiliydi (doğrulandı); eksik olan türbülans/esinti, uçuşta değiştirme, ev yönü ve
göstergelerdi. Not: yeniden konuşlandırmadan hemen sonra `tele.heading` ilk kalp atışına dek eski değeri gösterebilir (ölçümde 120°), fırlatma yönü doğrudur.

### 31.4 Rüzgâr göstergeleri — 3B rüzgâr tulumu + HUD (`createWindGauge`)
- **Tulum** (`createWindsock`): 6,5 m direk + çember + 5 bölmeli turuncu/beyaz koni (×1,6 görünürlük), pistin yanında (merkezden 60 m ileride, pist
  kenarından 24 m dışarıda; pist yoksa kalkış noktasının 28/28 m'si), yüzeye oturur (Google'da 1 Hz). **Rüzgârın estiği yöne döner**, hızla şişer
  (`sockState`: 15 kt ≈ 7,7 m/s'de tam açık, 0'da %12; sarkma 78°→0°), hız/esintiyle dalgalanır; gölge düşürür.
- **HUD göstergesi** (sahne sol üst; HEPGO + SIMUMAV): pusula (kuzey işareti uçağa göre döner, burun yukarı), mavi ok rüzgârın **akış** yönü, `7.2 m/s
  300° BKB · Esinti +3.0`, **baş/yan/kuyruk bileşenleri** uçağın burnuna göre (`windComponents`: head = V·cos(geliş − burun), cross = V·sin(…)):
  "Baş 5.2 · Yan 2.9 sağdan" — kuyruk > 1 m/s kırmızı, yan > 6 m/s sarı (kalkış/iniş uyarısı). 〰 düğmesi akış çizgileri (kalıcı tercih: HEPGO
  `caymaz.fs.windStreaks`, SIMUMAV `sm.windStreaks`); ✎ (HEPGO, yazma izni) hız/yön/esinti/türbülans kaydırıcıları → `wind` komutu. HEPGO sağ HUD'daki
  eski "Rüzgâr" satırı korunur.
- **Sihirbaz Kalkış adımında öneri** (`takeoffAdvice`): kalkış yönü (rampa azimutu / pist yönü) için baş/yan/kuyruk metni; kuyruk > 1 ya da yan > 6 m/s
  ise uyarı rengi; yön rüzgârdan ≥ 15° saparsa **"Rüzgâra karşı çevir (X°)"** düğmesi (rampada azimutu, diğerlerinde pist yönünü rüzgârın geldiği yöne,
  5°'ye yuvarlı, çevirir — önizleme anında döner).

### 31.5 Rüzgâr akış çizgileri (`STREAK_*`; aç/kapa)
Uçak çevresinde (kamera uzaklığına göre 30–120 m küp) 60–420 yarı saydam çizgi; konumlar GPU'da rüzgâr vektörüyle **gerçek hızda** taşınır (sarmalı
hacim), uzunluk 1,5–14 m, saydamlık 0,12–0,55 ve sayı rüzgâr hızıyla (`streakParams`), merkezden uzaklıkla ve kuyruğa doğru söner; 0,3 m/s altında
kapalı. `sim.setWindStreaks(bool)` / `opts.windStreaks`.

### 31.6 Rampa yön/açı arayüzü (`createRampPanel`; `cmd launch_aim`)
- **Tıklama**: 3B'de rampaya (ya da üstündeki uçağa) kısa tıklama (≤ 6 px, ≤ 450 ms; `pickRig` ışını) → `opts.onRigClick` → panel (sağ üst): pusula
  (sürükle) + **yön (azimut 0–359°)** kaydırıcısı, **açı 10–30°** (0,5° adım; sunucu `launch_dogrula` sınırları) + yan görünüş, rüzgâr satırı (o yön için
  baş/yan/kuyruk), **"Rüzgâra karşı çevir"**, Vazgeç / **Uygula**. Değişiklik 3B'de **anında** önizlenir (`sim.setRampAim` düzeneği yeniden kurar — eğim
  silindiri geometrisi açıya bağlı); Vazgeç eski değere döner. Yalnız **kalkıştan önce** (DISARM, AGL < 1 m, düzenek `idle`; `rampEditable`) — sonra kilitli.
- **SITL'e uygulama — gerekçe**: rampa yönü SITL'de uçağın **ev/burun yönüdür**. ArduPlane'de yerdeki uçağın yönünü değiştiren parametre/komut yok;
  `SIM_OPOS_HDG` yalnız `--home` VERİLMEDİĞİNDE açılışta okunur (biz `--home lat,lon,alt,yön` veriyoruz). Bu yüzden: **açı** → `TKOFF_LVL_PITCH` PARAM_SET
  (yeniden başlatma yok; `_kalkis_dizisi` zaten her kalkışta yazar); **yön** → oturum **aynı ayarlarla yeniden konuşlandırılır** (`reset()`: SITL `--home …,yön`
  ile yeniden başlar — §26 "Sıfırla" ile aynı yol; ~5 sn; görev/güç/parametreler korunur). Sahte kipte kinematiğin kalkış yönü anında değişir.
- **Ev yönü düzeltmesi**: önceden SITL her zaman `--home …,0` ile açılıyordu — pist yönü ≠ 0 iken 3B pist/rampa bir yöne, SITL uçağı kuzeye bakıyordu.
  Artık sabit kanatta ev yönü `kalkis_yonu()` = rampa azimutu (varsa) ya da pist yönü (tekerlekli/araç da pist boyunca koşar); diğer tiplerde 0 (değişmedi).
- **Sözleşme**: `world.launch.azimuth_deg` (isteğe bağlı, 0–359,99; yalnız rampada anlamlı; sihirbazın Kalkış adımında "Rampa yönü (azimut)" kaydırıcısı,
  varsayılan pist yönü). `cmd launch_aim {azimuth_deg?, angle_deg?}` → `{ok, launch, heading, redeploy}`; 400: rampalı sabit kanat değil / ARM'lı / havada /
  kalkış dizisi sürüyor / sınır dışı. WS `{t:'launch_cfg', launch, redeploy}` (tüm izleyiciler düzeneği günceller). SIMUMAV'ta da açık (oyun WS yolu
  `SIM_KOMUT`).

### 31.7 Testler, görsel doğrulama ve performans
- `node tests/test_flightsim_worldfx.mjs` (hava ön ayarları + sunucu/SIMUMAV listeleri, görüş formülü geri uyumu, yağış, güneş, rüzgâr vektörü/bileşenleri,
  kalkış önerisi, esinti tablosu Python ile aynı, tulum/akış çizgileri, rampa sınırları/değişiklik/kilit, gösterge metinleri, SIMUMAV `wfx.*` 7 dil).
- `tests.test_flightsim` `ruzgar_hava_testleri` (doğrulama 400'leri, esinti tablosu, `kalkis_yonu`, sahte kinematik: daire yer hızı aralığı ≈ 2×rüzgâr,
  hava hızı sabit, yengeç ≈ 30°, kopter eğimi, türbülans, süzülme sürüklenmesi, esinti aralığı; oturumda `wind` komutu + WS `wind` + tele, `launch_aim` +
  WS `launch_cfg` + kalkış kerterizi = azimut + ARM sonrası 400); `tests.test_simumav` (parkur hava → world.weather/wind_gust/FOG_HAVA, `wind` engeli).
- Görsel: `./.venv/bin/python -m tests.worldfx_shots_hepgo` (`WFX_WORLD=procedural|real`, `WFX_ONLY=day,dusk,night,rain,snow,fog,storm,cloudy,wind,ramp,fly`;
  önce/sonra: aynı betik `git archive` kopyasında `WFX_PREFIX=before`) ve `tests.worldfx_shots_simumav` → `/tmp/worldfx-shots/`.

**Performans ölçümü (bu ortam).** GPU'suz geliştirme sunucusunda yalnız SwiftShader (yazılım WebGL, 1440×900) var: aynı oturum/bakış noktasında kare hızı
önce 0,3–0,5 fps → sonra 0,1–0,3 fps (yazılım rasterleştiricide ~1,5–2× maliyet; gerçek GPU'da ölçülemedi). Sahne bütçesi (4 km prosedürel, 120 bina,
ağaç %40): ağaç ~8 000 örnek / ~200 parça, yakın (3B) parça 12–15, gölge kutusu ±90 m; yağmur 14 000 çizgi (fırtına 18 000), kar 9 000 nokta (GPU);
akış çizgileri ≤ 420. Orta düzey dizüstü GPU'da (Iris Xe / GTX 1650 sınıfı) hedef ≥ 45 fps — doğrulama için `window.__fsSim.fxInfo()` (çizim çağrısı,
üçgen, parça/LOD sayısı, sis aralığı) ve tarayıcı FPS ölçeri; gerekirse ilk ayar düğmeleri: `MAX_TREES`, LOD uzaklığı (`updateTreeLod` 520 m), gölge
haritası (2048), yağış sayısı (`precipParams quality`).

## 33. ÇOK OYUNCULU KARŞILAŞMA — halka yarışı (HEPGO aşama 1; çekirdek SIMUMAV aşama 2 ile ortak)

Kullanıcı isteği: "HEPGO'da **Yeni Karşılaşma** butonu: Yeni Simülasyon ile aynı özellikler, yalnız **radar, elektro-optik ve yer kontrol yok**; sihirbaz
sonunda Başlat/Kaydet değil **Davet et** bölümü (solda davet edilmeyenler, sağda edilenler), İleri → yalnız **Başlat**. Başlat → **bekleme salonu**;
davetliler **bildirime basıp** salona gelir; **herkes gelince başlar**; herkes **aynı haritada farklı noktada**; havada **farklı yüksekliklerde halkalar**
(oyundan önce **minimum/maksimum yükseklik, halka sayısı**); takeoff verip halkalardan geçen; **ilk bitiren birinci, oyun biter**; **herkeste sonuç ekranı**."

### 33.1 Dosyalar ve katmanlar
| Katman | Dosya | Not |
|---|---|---|
| **Saf çekirdek** (platformdan bağımsız) | `app/flightsim_match_core.py` | halka ayarı/üretimi, başlangıç noktaları, geçiş tespiti, durum makinesi, sıralama — DB/ağ/asyncio YOK; zaman dışarıdan |
| HEPGO çalışma zamanı | `app/flightsim_match.py` | `MatchManager` / `MatchRuntime`: oyuncu SITL oturumları, tele kancası, komut kapısı, WS yayını, `drone_sim_matches`, davet push'u |
| HEPGO REST + WS | `app/routers/flightsim_match.py` | `/api/drone/sim/matches…`, `/ws/drone/match/{id}` |
| Simülatör çekirdeği eklemeleri | `app/flightsim.py`, `app/routers/flightsim.py`, `app/flightsim_runs.py` | `start` / `match_id` / `tele_kanca` / `komut_kapisi`, ayrı SITL tavanı, sahibi dışında komut 403, `drone_sim_runs.match_id` |
| Bildirim | `app/notifications.py` `sim-match-invite` | zil (5 sn yoklama); anlık push oluşturma anında (`push=False`, çift olmasın) |
| Ön yüz saf | `static/js/modules/flightsim_match.js` | sınırlar/varsayılanlar, davet listesi bölme, saat eşitleme, geri sayım evresi, geometri, canlı sıralama |
| Ön yüz 3B | `static/js/modules/flightsim_match3d.js` | numaralı halkalar (sıradaki yeşil nabız, geçilen soluk, sonrakiler turuncu, yön oku) + diğer oyuncular (renkli gövde + isim) |
| Ön yüz DOM | `static/js/modules/flightsim_match_ui.js` | sihirbaz Halkalar / Davet et, bekleme salonu, oturum katmanı (şerit, sıralama, bekleme/geri sayım, sonuç), Karşılaşmalar sekmesi |
| Sihirbaz | `static/js/modules/flightsim_wizard.js` (`wizardSteps({match})`, `stepDefFor`), `flightsim.js` (`wizardModal({match:true})`) | |

### 33.2 Akış ve durumlar
`LOBI → HAZIRLIK → GERI_SAYIM → YARIS → BITTI` (+ `IPTAL`). Kullanıcının dört durumuna **HAZIRLIK** eklendi: SITL'ler boşta lobide beklemesin diye
oyuncu simülatörleri **herkes geldiğinde** açılır (kaynak), istemciler 3B dünyayı kurar.
1. **Sihirbaz** (Uçuş Simülatörü ana ekranı › "+ Yeni Karşılaşma", Yeni Simülasyon'un solunda): Araç (kara aracı yok — halkalar havada; **dron kaydı yok**)
   → Dünya ve konum → Kalkış (sabit kanat / fırlatıcı) → Güç ve yakıt → Kamera → **Halkalar** → **Davet et** → **Özet ve başlat** (yalnız ▶ Başlat;
   Kaydet / Uç / kayıt seçenekleri / pilot ataması yok). **Hedefler** de karşılaşmada yoktur (yarışa odak; dikkat dağıtan kinematik hedefler ve önleme
   sayımı anlamsız). Halkalar adımı: halka sayısı (1–30), minimum/maksimum yükseklik (5–400 m, merkez zemininden), halka çapı (4–80 m), parkur yarıçapı
   (80–3000 m), süre sınırı (2–60 dk), parkur tohumu (🎲) — sağda sunucu önizlemesi (`POST /rings-preview`, aynı tohum = aynı parkur) kuş bakışı + yükseklik
   profili. Varsayılanlar tip sınıfına göre: dikey (kopter/heli/VTOL/INTERCEPTOR) 8 halka 15–60 m Ø12 R220; sabit kanat 8 halka 40–140 m Ø36 R700.
   Davet et: Uçuş Simülatörü **yazma** izni olan etkin kullanıcılar (`flightsim_presets.pilotlar`, siz hariç); iki liste — tık seç (Ctrl çoklu),
   çift tık taşı, ›/» ekle, ‹/« çıkar, sürükle-bırak, arama; en az 1, en çok 7 davetli (8 oyuncu, kurucu dahil).
2. **Başlat** → `POST /api/drone/sim/matches` → **LOBI** (kurucu "geldi"); davetlilere anlık push (`url /app#/drone/sim/match/{id}`) + zilde "Karşılaşma
   daveti › Bekleme salonuna katılın". Kurucu **bekleme salonuna** (`#/drone/sim/match/{id}`) geçer.
3. **Bekleme salonu**: oyuncular (renk, çevrimiçi noktası = salon WS'ine bağlı, durum rozeti Bekleniyor / Geldi / Hazırlanıyor / Hazır / Ayrıldı /
   Çıkarıldı / Düştü), ayarlar + parkur çizimi, sohbet. Davetli bildirimden gelince sayfa **kendiliğinden katılır** (`POST /join`). Kurucu: oyuncu çıkar (✕),
   **iptal**, **"Gelmeyenler olmadan başlat"** (yalnız ≥ 2 oyuncu gelmiş ve `LOBI_ZORLA_S` = 60 sn geçmişse; varsayılan HERKESİ bekler — kullanıcı "tüm
   kullanıcılar geldiğinde" dedi). Davetli: Ayrıl (= daveti reddet). Lobi 30 dk içinde başlamazsa IPTAL `zaman_asimi`. Kurucu lobide ayrılırsa IPTAL.
4. **Tüm davetliler geldi** (ya da çıkarıldı / düştü) ve ≥ 2 oyuncu → **HAZIRLIK**: her oyuncuya kendi **SITL oturumu** açılır (ortak ayarlar: tip, dünya,
   model, güç, düzen, kamera; `rec.bin` kapalı) — **aynı merkez/dünya, farklı başlangıç noktası** (`SimSession.start` → SITL `--home` ve sahte kinematik).
   Salon sayfası oyuncuyu oturum ekranına götürür (`#/drone/sim/{sid}?match={id}`). 3B dünya kurulunca istemci WS `ready` gönderir; oturum HAZIR + ready
   → oyuncu **hazır**. 150 sn'de hazır olmayan düşer; < 2 oyuncu kalırsa IPTAL.
5. **Herkes hazır** → **GERI_SAYIM**: `start_at = now + 6 sn` (sunucu saati; istemciler WS `pong.now` ile saat farkını en küçük gidiş-dönüş örneğiyle
   kestirir). Son 3 sn'de §29 giriş sekansı (100 m bakış + 3‑2‑1 + "dıt dıt") — herkeste aynı anda "BAŞLA". Bu sürede ve öncesinde **komut kapısı**
   ARM / kalkış / görev başlatmayı (web, CAYSIM, harekât paneli) ve sanal kumanda RC'sini (çubukla ARM olmasın) reddeder: "Yarış henüz başlamadı".
6. **YARIS**: kalkış serbest. Halka geçişi **sunucuda doğrulanır** (oyuncu oturumunun `tele_kanca`sı; gerçek SITL'de her ATTITUDE/konum karesi):
   ardışık iki konum halka düzlemini **doğru yönde** (−→+) keser ve kesişim **halka yarıçapı içinde** ise geçiş; yalnız **sıradaki** halka denetlenir;
   ters yön (WS `wrong_way` uyarısı) ve dışından geçiş sayılmaz; tek adımda > 250 m sıçrama (Sıfırla/ışınlanma) yok sayılır. 10 Hz `pos` çerçeveleri
   diğer oyuncuları 3B'de taşır (≈150 ms gecikmeli ara değer; çarpışma yok, yalnız görsel). Çarpışan oyuncu Sıfırla ile başlangıca döner, ilerlemesi kalır.
7. **İlk tüm halkaları bitiren** → **BITTI** (`birinci_bitirdi`); süre sınırı dolarsa `sure` (birinci en çok ilerleyen). Herkese WS `result` →
   **sonuç ekranı** (oturum ekranında katman + salon sayfasında tablo). Oyuncu oturumları 8 sn sonra kapanır (`drone_sim_runs.match_id` ile kayıt);
   oturum ekranındaki "Oturum sona erdi" perdesi karşılaşma kapanışında gösterilmez (sonuç kalır).

### 33.3 Halkalar, başlangıç noktaları, sıralama (çekirdek)
- **Halka üretimi** (`halkalar_uret(ayar, merkez)`, `random.Random(seed)`): yükseklikler [min, max]'a eşit adımla (uçlar dahil) dağıtılıp karıştırılır →
  hepsi farklı yükseklikte; yatayda merkez çevresinde dolanan parkur (açı adımı 360/n ±%30, yön rastgele, uzaklık 0,45R…R). Halka düzlemi dikey,
  **normali bir önceki halkadan bu halkaya** (ilk halkada başlangıçların ağırlık merkezinden = merkez) → sırayla uçan doğru yönde keser. Alanlar:
  `{i, lat, lon, x, y (merkez ENU m), agl_m, alt_msl (= merkez zemini + agl), yaw_deg, nx, ny, radius_m}`.
- **Başlangıç noktaları** (`baslangic_noktalari(n, tip, pist_yonu, ayrik=40, hedef)`): dikey kalkanlar merkez çevresinde eşit aralıklı çember (komşular
  ≥ 40 m), burun ilk halkaya; sabit kanat pist yönüne **dik şeritlerde** 40 m arayla, hepsi pist yönünde (rampa yönteminde rampa azimutu `kalkis_yonu`).
  Tüm oyuncuların SITL ev irtifası merkezinkidir (aynı `alt_rel` ölçeği; ≤ birkaç yüz m'de arazi farkı ihmal — gerçek arazi kipinde çok eğimli sahada
  sınır).
- **Sıralama**: bitirenler bitiş süresiyle; bitirmeyenler geçtiği halka sayısı (çok → önde), eşitlikte sıradaki halkaya 3B mesafe (az → önde);
  ayrılanlar yarışanlardan sonra, çıkarılan/düşen/gelmeyenler sonda. Sonuç satırı: sıra, süre, halka x/n, sıradakine mesafe, azami yer hızı, çarpışma
  sayısı (oturumun `gorev.crashes`), durum.

### 33.4 REST / WS sözleşmesi (HEPGO)
- `GET /api/drone/sim/matches/meta` → `{users[{id, full_name, username, pilot}], limits{players_max, invite_min, count, alt_m, diameter_m, radius_m,
  time_limit_min, defaults{dikey, ucak}, types, countdown_s, force_after_s}, capacity{max, used}, can_create}`.
- `POST /rings-preview {type, center_id, rings}` → `{cfg, rings}` · `GET ''` son karşılaşmalarım (oyuncusu olduklarım) · `POST '' {settings, rings, invite[]}`
  → 201 anlık görüntü (settings yalnız `type, center_id, world, model, power, layout, camera, drive`; `site/defend/targets/drone_id/rec` yok sayılır;
  oturum gövdesiyle AYNI doğrulayıcılar `flightsim_presets.ayar_dogrula`) · 400 geçersiz / izinsiz davetli · 403 yazma izni yok · 409 kapasite.
- `GET /{id}` (yalnız oyuncular; bellekte değilse DB satırı) · `POST /{id}/join | /leave | /kick {user_id} | /start | /cancel` (409 çakışma, 403 kurucu değil).
- WS `/ws/drone/match/{id}` (oturum çerezi; oyuncu değilse 4403): sunucu → `hello {match, me, chat}`, `match {match}` (her değişimde anlık görüntü; `now`
  sunucu saati), `player`, `state`, `countdown {start_at}`, `pos {ts, p[{id, lat, lon, alt_msl, alt_rel, yaw, roll, pitch, gs, armed, rings, next, dist}]}`
  (10 Hz), `ring {id, i, total, elapsed_s}`, `finish {id, elapsed_s}`, `wrong_way {id, i}`, `result {result}`, `chat {id, name, text}`, `pong {now}`;
  istemci → `ping`, `ready`, `chat {text}`.
- Oyuncu oturumu (`/api/drone/sim/sessions/{sid}`): `match_id`, `start`; **yalnız sahibi** komut verir (REST 403, WS salt izleme).

### 33.5 Kaynak sınırları ve kalıcılık
- Oyuncu tavanı 8 (kurucu dahil). Karşılaşma SITL'leri **ayrı tavanla** sayılır: `SIM_MATCH_MAX_SESSIONS` (varsayılan 8) — normal `SIM_MAX_SESSIONS`'ı
  tüketmez; oluşturmada bitmemiş karşılaşmaların aktif oyuncuları + yeni oyuncular tavanı aşarsa 409. Bitince/iptalde oturumlar kapanır.
- **DB göçü**: yeni tablo `drone_sim_matches` (id, host_id, state, reason, settings, rings_cfg, rings, players, result, winner_id, created_at, started_at,
  ended_at) + `drone_sim_runs.match_id` (+ indeks) — `db.init` içinde (CREATE IF NOT EXISTS / ALTER ADD COLUMN; geri alınması gerekmez).
- Durum makinesi bellektedir; satır her durum değişiminde güncellenir. Sunucu yeniden başlarsa bitmemiş satırlar ilk erişimde `IPTAL
  sunucu_yeniden_basladi`; kapanışta (lifespan) süren karşılaşmalar `sunucu_kapaniyor`. Biten karşılaşma 15 dk bellekte (canlı WS/GET), sonra DB'den.
- Uçuş Simülatörü ana ekranında **Karşılaşmalar** sekmesi (rozet: süren karşılaşma sayısı): durum, kurucu, araç, oyuncular, kazanan, tarih → Salona git / Sonuç.

### 33.6 SIMUMAV aşama 2 için yeniden kullanım
- Sunucu: `flightsim_match_core` doğrudan (Karsilasma, halkalar_uret, baslangic_noktalari, HalkaIzleyici, siralama, halka_ayar_dogrula); oturum açma
  `flightsim.MANAGER.ac(..., start=, match_id=)`, `SimSession.tele_kanca` / `komut_kapisi` kancaları. `flightsim_match.MatchRuntime` HEPGO'ya bağlı
  kısımları (oturum açma `routers.flightsim.oturum_ac`, `db`, push, kullanıcı adları) ayrık; SIMUMAV kendi davet kodu/şifre/salon akışını ve DB'sini
  yazıp çekirdeği + kancaları kullanır (davet kodu/linki, e-posta → kurucunun ürettiği şifre → salon; Uç bölümünde Çok oyunculu / Tek oyunculu).
- Ön yüz: `flightsim_match.js` (saf) ve `flightsim_match3d.js` (yalnız flightsim3d nesnesinin `three/scene/toLocal/homeAlt/addFrameHook` alanları)
  doğrudan; `flightsim_match_ui.js` HEPGO DOM'udur (SIMUMAV kendi arayüzünü yazar; `ringsSvg`, `resultsBody` örnek alınabilir).
- **Gerçekleşti (SIMUMAV aşama 2)**: docs/simumav.md §18 — `app/simumav/match.py` + `routers/match.py` (davet kodu + scrypt şifre + lobi, çekirdek
  `Karsilasma` BAŞLAT'ta kurulur), ön yüz `static/simumav/app/fly/match*.js`. Ortak çekirdek ve ön yüz modülleri DEĞİŞTİRİLMEDİ; HEPGO'ya etkisi yok.

### 33.7 Testler ve görsel doğrulama
- `.venv/bin/python -m tests.test_flightsim_match`: saf çekirdek (halka ayarı sınırları, min/max/sayı, deterministik tohum, normaller; başlangıç noktası
  ayrıklığı ve pist şeritleri; geçiş doğru/ters yön, dışından, sıra dışı, sıçrama; sıralama; durum makinesi: davet, katılım, hazırlık, geri sayım, yarış,
  ilk bitiren → BİTTİ, süre sınırı, iptal, çıkarma, zorla başlatma, hazırlık zaman aşımı, lobi zaman aşımı) + HEPGO API uçtan uca (sahte kinematik +
  `tests/match_bot.py` rota pilotu: davet/yetki, zil + push, farklı başlangıçlar, komut kapısı, başkasının aracı 403, WS ready → countdown → YARIS,
  halka olayları 1‑2‑3, birinci, iki WS'de sonuç, `drone_sim_runs.match_id`, kapasite 409, iptal / ret / çıkarma).
- **Gerçek SITL**: `.venv/bin/python -m tests.match_sitl_e2e` — iki ArduCopter SITL (ev konumları 40 m ayrık), geri sayımda ARM 400, YARIS'ta
  ARM + kalkış + GUIDED goto ile 2 halka → sunucu tele kancası halka 1‑2'yi sayar, birinci → sonuç, SITL'ler kapanır (≈ 2 dk). Bu sırada bulunan
  hata düzeltildi: eşzamanlı açılan oyuncu SITL'leri aynı port bloğunu seçiyordu (`drone_sitl.SitlYoneticisi._ayrilan`: açılıştaki bloklar ayrılır).
- `node tests/test_flightsim_match.mjs` (saf ön yüz: doğrulama, davet listesi, saat, geri sayım, geometri, sıralama, sihirbaz adımları).
- Görsel: `./.venv/bin/python -m tests.match_shots_hepgo` → `/tmp/match-shots/` — iki tarayıcı bağlamı (kurucu + davetli) + tarayıcısız üçüncü oyuncu:
  sihirbaz Halkalar ve Davet et (iki liste), özet (yalnız Başlat), salon (bekleniyor → geldi), zil bildirimi → salon, hazırlık bekleme katmanı,
  geri sayım, yarışta halkalar + diğer oyuncular, iki tarafta sonuç, Karşılaşmalar sekmesi.
## 34. Servo tetik — servo kanalı komutu → gecikme → çarpma → özet (`app/flightsim_servotrig.py`, `static/js/modules/flightsim_servotrig.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: "Simülasyon ortamında altta bir Servo kanalı seçme olsun, yanında PWM değeri olsun, gecikme milisaniye cinsinden olsun, Dinle düğmesi
olsun. Dinle'ye basarsa o servo kanalından gelen PWM değerini dinlesin ve komut gelirse gecikme süresini bekleyip sanki dağa ya da bir nesneye çarpmış gibi
hareket edip simülasyonu bitirip özet ekranı gelsin. Son özette de bu işlemin kaç metrede çalıştığını görebilelim."

**Alt bant (tüm kamera kipleri; sanal kumanda / harekât paneli açıkken de).** Bantta yalnız TEK servo simgeli **Dinle** düğmesi (`.fs-srv-btn`;
satır içi girişler §36'da kalktı). Basınca düğmenin ÜSTÜNDE yukarı açılan panel (`.fs-srv-pop`: başlık "Servo tetik" + ×) aşağıdaki girişleri ve
**Dinlemeye başla** düğmesini (`.fs-srv-act`) taşır; başlayınca panel KAPANIR, bant düğmesi kırmızı yanıp söner ve **Dinleniyor** yazar (gecikme
sürerken **Tetiklendi**, çarpmada **ÇARPMA**). Dinlerken düğmeye basınca panel yine açılır: değerler kilitli, canlı PWM görünür, eylem **Dinlemeyi
durdur**. Panel dışına tıklama / **Esc** kapatır (Esc yakalama evresinde: oturumdan çıkış kısayoluna gitmez); dar ekranda panel görüntü alanına
kaydırılır. Panel içeriği: kanal seçici S1–S16 (etiket dronun `SERVOn_FUNCTION`
işleviyle: "9 · RCIN9 / Yük" — RCINn, Gripper, Parachute, CameraTrigger, Sprayer, Winch, ScriptN "yük" sayılır), koşul `≥` / `≤` / `=` (eşitte
± tolerans satırı), PWM eşiği (µs, 800–2200), gecikme (ms, 0–60000), **Canlı PWM**: dinlerken yanıp sönen kırmızı nokta + kanalın anlık PWM'i
(`tele.servo16`; koşul sağlanınca sarı), tetikte turuncu hızlı nokta, çarpmada "ÇARPMA". Dinleme komutları, tercihler ve dron kaydı önerisi aynen.
Tetik gelince sahnede kırmızı bant "SERVO TETİK · S9 1900 µs — 1500 ms sonra çarpma · AGL 80 m · evden 111 m". Kanal adları sunucunun ilk kalp atışında
istediği `SERVO1…16_FUNCTION` değerlerinden (WS `{t:'servo_trigger', phase:'fn', fn}`). Tercih kalıcı: `localStorage fs.srvtrig` + dron başına
`fs.srvtrig.byDrone`; sunucu da Dinle'de dron kaydına yazar (`drone_sitl_options srvtrig_ch/pwm/cmp/tol/delay_ms`) → sonraki oturumda
`session.servo_trigger.suggest` (öncelik: dron başına yerel > dron kaydı önerisi > son genel tercih > varsayılan S9 ≥ 1900 µs, 1500 ms).

**Sunucu (tetik mantığı burada — istemci kapalı / yavaş olsa da güvenilir).**
- Komut `servo_trigger {on, ch 1…16, pwm 800…2200, cmp 'ge'|'le'|'eq', tol 1…500 (vars. 50), delay_ms 0…60000}`; `on:false` dinlemeyi (ve bekleyen
  çarpmayı) bırakır. Kaynak: SITL `SERVO_OUTPUT_RAW` (port 0; `servo9…16_raw` MAVLink2 uzantı alanları) → `tele.servo16`. Yardımcı komut
  `servo_set {ch, pwm}`: gerçek SITL'de `MAV_CMD_DO_SET_SERVO` (Mission Planner "Servo/Relay" sekmesinin gönderdiği komut), sahte kipte sanal çıkış
  (test/otomasyon; ön yüzde düğmesi yok). İkisi de `KOMUTLAR`'da (SIMUMAV `SIM_KOMUT` aynı listeyi kullanır).
- **Kenar tetikli**: dinleme açıldıktan sonraki ilk geçerli örnek TABANDIR; koşul ancak "sağlanmıyor → sağlanıyor" geçişinde tetikler. Dinle'ye
  basıldığında kanal zaten koşuldaysa (ör. ≥ 1100 ve kanal 1500'de) olay şeridine "zaten koşulda; yeni komut bekleniyor" yazılır, tetik olmaz.
  Gerekçe: istek "komut gelirse" diyor; seviye tetiği Dinle anında çarpma üretirdi. PWM 0 / 65535 (kanal çıkış vermiyor; SITL’de SERVO9_FUNCTION 0) "koşul sağlanmıyor" sayılır → Mission Planner DO_SET_SERVO 9 1900 ile 0 → 1900 geçişi tetiktir (SITL’de ölçüldü). `reset` bekleyen çarpmayı
  iptal eder, dinleme sürer (taban yeniden alınır).
- **Gecikme SİMÜLASYON zamanıyla** (SITL `time_boot_ms`; tetik zamanı `SERVO_OUTPUT_RAW.time_usec`). SIM_SPEEDUP 4× iken 1500 ms gecikme ~375 ms gerçek
  zamanda dolar. Gerekçe: gecikme fiziksel bir süreyi (yük bırakma, sigorta, paraşüt açılımı) taklit eder ve araç da sim zamanında hareket eder → çarpma
  konumu simülasyon hızından bağımsızdır. SITL saati ilerlemezse duvar saati bekçisi (gecikme × 2 + 5 sn) çarpmayı yine üretir (`hit.watchdog`).
- **Çarpma**: araç o anki konum/hız/yönüyle "çarpmış" sayılır — `GorevIzleyici.carpisma('servo_trigger', max(hava, yer hızı))` (drone_sim_events
  `crash`, WS `crash` → ön yüz çarpışma bandı + crashfx patlama/toz/kıvılcım + darbe sesi §30), zorla disarm (sahte kipte yalnız disarm), `end_reason =
  'servo_trigger'`, **3B donar** (sonraki `tele` yayınlanmaz; araç çarpma pozunda kalır, SITL fiziği düşüşü sürdürse de görünmez), SITL'e
  STATUSTEXT `SERVO TRIG …` / `SERVO HIT …` (ArduPilot GCS metnini DataFlash `MSG` olarak yazar → .bin kayıttan oynatmada olay şeridinde).
  WS `{t:'servo_trigger', phase:'pending'|'fired', trigger, hit, …}`.
- **Bitiş**: ön yüz `fired`ten 2,5 sn sonra (efekt görünsün) Bitir akışını ONAYSIZ çalıştırır: ekran kaydı → özet raporu (`GET /summary`) → kapat
  (SIMUMAV `endFlight({auto})` → `/api/fly/{id}/stop` → uçuş özeti). İzleyici kalmazsa 5 sn (`BOS_KAPANIS_S`) sonra, rapor açık kalsa da en geç
  300 sn (`AZAMI_BEKLEME_S`) sonra sunucu kapatır (`end_reason servo_trigger`; özet + `drone_sim_runs` kapanışta yazılır; SIMUMAV sonucu `crash`).

**Özet ve kayıt.** `summary.servo_trigger` = {ch, fn, fn_name, payload, pwm, cmp, tol, delay_ms, seen_pwm, phase, time_base:'sim', trigger, hit};
`trigger`/`hit` anlık görüntüsü: tbm, lat/lon, alt_msl, alt_rel, **agl** (TERRAIN_REPORT varsa arazi üstü `agl_src:'terrain'`, yoksa ev seviyesine
göre `'home'`), **dist_home_m** (evden yatay), airspeed, groundspeed, heading, climb, mode, **flight_s** (ilk ARM'dan bu yana sim saniyesi), pwm;
`hit.delay_sim_ms` / `delay_wall_ms`. Rapor (`flightsim_report.js` → `servoSection`): "⚡ Servo tetik" kartı — tetik/çarpma AGL ve evden mesafe
karoları, kanal/koşul/görülen PWM/gecikme (istenen + ölçülen sim + gerçek), iki sütunda tetik anı (komutun geldiği an) ve çarpma anı; mini haritada
turuncu ▲ tetik, kırmızı ✱ çarpma; paylaşım metninde satırlar. `drone_sim_runs.servo_trig` (JSON kısa özet: ch, fn, pwm, cmp, delay_ms, trig_agl,
trig_msl, trig_dist_m, hit_agl, hit_dist_m, fired; kullanılmadıysa NULL — eski/SIMUMAV çekirdek DB'sinde sütun yoksa yazılmaz, `shim/db.py`
göçü ekler) → Simülasyon Kayıtları sonuç sütununda ve Kayıtlı Simülasyonlar uçuş kartında turuncu rozet "⚡ S9 · 80 m" (tetik AGL; ipucunda evden
mesafe ve gecikme).

**Mission Planner uyumu.** Kanal Mission Planner'dan tetiklenebilir: Servo/Relay sekmesi ya da görevdeki `DO_SET_SERVO` (183) öğesi, RC geçişli
kanallar (`SERVOn_FUNCTION = 51…66 RCINn` → RC override / joystick), Lua betiği. Sunucu yalnız SITL'in gerçek servo çıkışını izler; komutun kaynağı
önemsizdir. Gerçek SITL ölçümü: `tools/sitl/dogrula_servotrig.py` (pymavlink GCS = Mission Planner yerine, UDP portundan `DO_SET_SERVO 9 1900`).

**Gerçek SITL ölçümü (ArduPilot 4.7.2, `/opt/hepgo/sitl/bin`; 21.10.2026).** SERVO9_FUNCTION 0 iken SITL kanal 9'u **0 µs** bildirir; GCS'den
`DO_SET_SERVO 9 1900` → COMMAND_ACK 0, 50 ms içinde `servo9_raw` 1900 (MAVLink2 uzantı alanı geliyor) → kenar (0 = koşul sağlanmıyor).
| | Kopter 1× (GUIDED askı 40 m) | Sabit kanat 4× (seyir ~33 m/s) |
|---|---|---|
| tetik anı | AGL 40,0 m · evden 0 m · uçuş 22,0 sn | AGL 72,4 m · evden 451,5 m · uçuş 17,3 sn |
| çarpma anı | AGL 39,9 m · evden 0 m · sim gecikme 1500 ms / gerçek 1502 ms | AGL 68,7 m · evden 469,0 m · sim 1501 ms / gerçek **372 ms** |
| GCS GLOBAL_POSITION_INT ile fark (aynı time_boot_ms) | konum 0,0 m · irtifa 0,02–0,03 m | konum 1,45 m · irtifa 0,07–0,17 m |
| kapanış | izleyicisiz 5,7 sn sonra sunucu; run `carpisma` / `servo_trigger` | 5,2 sn; aynı |
.bin `MSG`: `GCS:SERVO TRIG S9 1900us AGL 72m D 452m`, `GCS:SERVO HIT S9 AGL 69m D 469m` (ArduPilot GCS STATUSTEXT'i kaydediyor → kayıttan
oynatma olay şeridinde görünür). Uçakta 1,45 m fark: anlık görüntünün tbm'i SERVO_OUTPUT_RAW / ATTITUDE zamanıdır, konum ise son alınan GLOBAL_POSITION_INT (bir örnek ≈ 40 ms geride; 36 m/s × 0,04 s ≈ 1,4 m).

**Testler.** `tests.test_flightsim` `servo_tetik_birim_testleri` (doğrulama, koşul, kenar, sim zamanı gecikme, anlık görüntüler, 9–16 uzantı alanları,
işlev adları, iptal/reset, kısa özet) + `servo_tetik_testleri` (uçtan uca sahte kip: 400'ler, KOMUTLAR/SIM_KOMUT, zaten-koşulda uyarısı, 4× hızda
gecikme, `crash` reason, donma, özet, izleyicisiz sunucu kapanışı, drone_sim_runs + liste JSON, dron kaydı önerisi); `node tests/test_flightsim_servotrig.mjs`
(saf katman + HEPGO 6 dil + SIMUMAV 7 dil `srv.*`); görsel `./.venv/bin/python -m tests.servotrig_shots_hepgo` → `/tmp/servotrig-shots/`.

## 35. "Sıfırla" parametre/script korunumu, ağır çekim (0,25× / 0,5×), "Kamera yok", uçuş kartında onaylı Sıfırla (HEPGO + SIMUMAV ortak)

**Sıfırla korunumu.** `SimSession._sitl_ac(temiz)`: oturum BAŞINDA `temiz=True` (eeprom.bin + `scripts/` + `APM/scripts/` silinir — önceki oturumdan
parametre/script sızıntısı yok; elevon AIRSPEED_MIN olayı kuralı korunur, artık scriptler de; önceki oturumun scriptleri yeni oturumun `scripts.zip`
kaydına da girmiyordu → girmez). `reset()` (komut `reset`, §26 interceptor değişimi, §31 rampa yönü) `temiz=False` açar: eeprom.bin (parametreler +
görev/fence/rally) ve script dizinleri yeni SITL sürecinde aynen durur; 3B rota (`route`) artık reset'te temizlenmez (görev SITL'de yüklü kalır).
Oturumun ilk kalp atışında yazdığı set (RC/GPS-RTK/düzen §13.1/flap/hız §23/kalkış/arazi) eeprom'daki kullanıcı değerini ezeceği için kullanıcının
oturumda yazdıkları ayrıca tutulur: `oturum_paramlari` (Mission Planner PARAM_SET — UDP baytlarından `_gcs_param_ayikla`; panel `param_set` —
`hub_komut`) → reset sonrası ilk kalp atışında oturum setinden SONRA yeniden yazılır (`_oturum_paramlari_yaz`; kalıcı izleyici yankıları
`yukleme_isaretle` ile yeniden kaydetmez). Yazılmayanlar `OTURUM_PARAM_HARIC_*`: MAV_SYSID/SYSID_THISMAV (yeni SITL aynı sysid 1), FORMAT_VERSION,
*_TOTAL, STAT_*, SIM_SRV_REV (kayıtlı SERVOn_REVERSED'den üretilir), SIM_PLN_THR_MUL (oturum azami hızından). HEPGO'nun kendi komutu aynı
parametreyi yeniden belirlerse MP'nin eski değeri unutulur (`speed` → SIM_SPEEDUP, `wind` → SIM_WIND_*, `launch_aim` açı → TKOFF_LVL_PITCH).
SIM_SPEEDUP reset sonrası her zaman `speedup_istek` ile yazılır (1× dahil; eeprom'daki değer değil).

**Uçuş logu (.BIN) ve Sıfırla.** "Uçuş logunu kaydet" açıksa `reset()` SITL durduktan hemen sonra o ana kadarki .BIN'i `_bin_kaydet(ara=True)` ile ayrı bir Uçuş Logu olarak kaydeder (not: "sıfırlama #N öncesi"; `rec.bin_logs_reset`). Yeni SITL `logs/*.BIN`'i sildiği için önceden bu log kayboluyordu. Kapanışta yeni .BIN yoksa son ara log oturumun logu (`bin_log`) sayılır; varsa kapanış logunun notu "sıfırlama #N sonrası" olur.

**Mission Planner reset'te kopmaz.** UDP soketi ve portu oturum boyunca aynı; GCS kilidi (`gcs_addr`) reset'te sıfırlanmaz (MP 1 Hz kalp atışıyla
tazeler). SITL yokken (~2–4 sn) `_kopru_kalp`: MP'ye aynı sysid/compid ve araç tipiyle 1 Hz HEARTBEAT (MAV_STATE_BOOT) + bir STATUSTEXT
"HEPGO: SITL yeniden baslatiliyor"; yeni SITL'in ilk kalp atışında biter. Ölçüm (gerçek SITL, pymavlink MP taklidi): en uzun araç kalp atışı boşluğu
≈ 2,0 sn, reset sonrası PARAM_VALUE/ATTITUDE/görev aynı UDP'den akar. MP'nin önbelleğindeki parametre listesi yenilenmez (değerler zaten korunduğu için gerekmez).

**Ağır çekim.** `flightsim_power.SPEEDUPS = (0.25, 0.5, 1, 2, 4, 8)`; ArduPilot SITL SIM_SPEEDUP float kabul eder (ölçüldü: 0,25× → time_boot_ms/duvar
0,25; 0,5× → 0,50). Yavaşta SITL akışı duvar saatinde azalır (50 Hz SITL → 0,25×'te ~12,5 Hz); 3B enterpolasyonu kaynak saat oranını zaten izler
(0,05…5). Yakıt/batarya simülasyon zamanıyla; `GucDurumu.speedup_min` → özet `speedup.min` (rapor: "simülasyon hızı en az"). Seçiciler (HEPGO üst çubuk +
panel `createSpeedPill`, SIMUMAV sihirbaz/kapsül) `0.25×` `0.5×` etiketleriyle; `.fs-speed-pill.slow`. SIMUMAV `speedup_dogrula` 0,25/0,5 kabul eder
(MAX_SPEEDUP yalnız üst sınır), başlangıç hızı ≠ 1 ise bekçi yazar.

**Kamera yok (`camera: 'none'`).** `KAMERA_TURLERI` + 'none' (DB `drone_sim_runs.camera`, kayıtlı ön ayar `settings.camera`, SIMUMAV shim sütunu TEXT —
göç yok). Ön yüz `flightsim_camera.js`: `CAMERA_CHOICES` (türler + none), `isCamChoice/normCamChoice/isNoCam`; görüntü türü (`normCamType`) none → gündüz.
Sihirbaz kartı "Kamera yok" (üstü çizili kamera simgesi), 📷 menüsünde seçenek (PiP satırı gizli, V etkisiz). none iken `createCameraPip` HİÇ kurulmaz
(seçilince kaldırılır, başka türe geçilince kurulur), 3B `renderPip` çağrılmaz, gimbal ('fpv') kipine geçilmez (C döngüsü atlar, 3 tuşu/düğmesi yok;
gimbaldeyken none seçilirse önceki kipe döner), `swapPip` null. HEPGO + SIMUMAV (`camera_pick.js` CAMERA_KEYS; `camera.none*` 7 dil).

**Uçuş kartında Sıfırla.** Harekât kartı (`flightsim_panel.js`, HEPGO + SIMUMAV ortak) başlığında ↺ düğmesi + İŞLEMLER "↺ Sıfırla" artık onay
soruyor; HEPGO "Açık Oturumlar" satırında "↺ Sıfırla" (kayıttan oynatmada yok). Yetki mevcut komut kuralı: `drone.sim` yazma izni (karşılaşmada
yalnız kendi aracı — `mac_yazabilir`); komut `POST /api/drone/sim/sessions/{id}/cmd {name:'reset'}`.

**Testler.** `tests.test_flightsim_resetkeep` (GERÇEK SITL, ~3 dk: copter — MP PARAM_SET + script + görev korunumu, 0,25×/0,5× ölçümü, MP kalp
atışı boşluğu, yeni oturumun temiz başlaması; ArduPlane elevon — düzen parametreleri + SIM_SRV_REV korunur, MP'nin MIXING_GAIN'i geri yazılır);
`node tests/test_flightsim_camera.mjs` (none), `tests/test_flightsim_power.mjs` (seçici), `tests/test_simumav_fly.mjs`.

## 36. Alt bant kapsülleri — görünüm + kamera, Panel + ses, servo "Dinle" (HEPGO + SIMUMAV ortak)
Kullanıcı isteği (ekran görüntüleri 174–176): alt bant kalabalık; servo girişleri tek düğmeye, Panel ile ses tek kapsüle, görünüm düğmeleri ile kamera
seçimi tek kapsüle. Yalnız sunum değişti; komutlar, tercihler ve kısayollar aynı.
- **Görünüm + kamera türü TEK kapsül** (`flightsim_camera.js createCameraCtl({views: CAMERA_MODES, onView})`, `.fs-cam-ctl.fs-viewcam`): sol yarı
  görünüm düğmesi `.fs-view-btn` (👁 + kısayol numarası + aktif görünümün adı, ör. "1 Takip ▾") → açılır liste `.fs-view-menu` (Takip / FPV / Gimbal
  kamerası / Serbest / Yer; numaralı, ↑↓ gezinme, Esc kapatır); sağ yarı kamera türü "📷 Kamera yok ▾" (eski menü). 1–5 ve C kısayolları 3B modülünde
  kalır; `onCameraChange` → `camCtl.setView(mode)` düğme metnini günceller. §35 kuralı: kamera yokken "Gimbal kamerası" listede **devre dışı**
  ("Kamera yok" notuyla; `viewDisabled`). Eski ayrı `[data-cam]` düğmeleri kalktı.
- **Panel + ses TEK kapsül** (`.fs-ops-snd`): `opsBtn` kapsülün içinde; `createEngineAudio` 🔊 ▾ kapsülünü `.fs-ops-btn`'in yanına ekler (iç kapsül
  çerçevesiz, ince ayraç). §17 ⏺ Kayıt anahtarı kapsülün ARDINA (`flightsim_record.js` önce `.fs-ops-snd`); §26 Radar/EO ve §27 Nişangâh grupları da
  `opsSnd.nextSibling`'e.
- **Servo tetik**: §34'teki tek düğme + yukarı açılan panel.
- Kapsül CSS'i JS ile enjekte (`ensureBarCss` `#fs-bar-css`, servo `#fs-srv-css`) → HEPGO `app.css` ile SIMUMAV `fly-sim.css` ayrışmaz. Kara aracı
  (§31) aynı kapsüller; kayıttan oynatmada servo yok (görünüm + kamera, Panel + ses, oynatma çubuğu); karşılaşmada (§33) bant değişmez. 1600 px'te bant
  tek satır (önce iki satırdı), 900 px'te iki satır, taşma yok.
- Metinler: HEPGO 6 dil ("Dinleniyor", "Dinlemeye başla", "Görünüm"…), SIMUMAV `srv.*` (listening, start, stop_l, live, ch, cmp, tol, delay, close,
  btn_t, trig) ve `camera.view*` (7 dil; `camera_pick.js CAM_TEXT_KEYS`).
- **Testler.** `node tests/test_flightsim_servotrig.mjs` (düğme/eylem metni aşamaya göre), `node tests/test_flightsim_camera.mjs` (görünüm etiketi,
  gimbal devre dışı, iki istemcinin bant kurgusu); görsel `./.venv/bin/python -m tests.fltbar_shots_hepgo` / `tests.fltbar_shots_simumav`
  (/tmp/fltbar-shots: 1600 / 1280 / 900 px, liste ve panel açık, dinleme, tetik → özet, rover, replay, İngilizce; taşma denetimi).

- **Sığdırma (düzeltme, `flightsim_fltbar.js fitFlightBar(bar, {stage})`; HEPGO `flightsim.js`, SIMUMAV `fly/session.js`).** 1280–1440 px'te
  bant iki satıra kayıyordu (gimbal görünümünde 1440'ta bile). Bant ve doğrudan çocukları ResizeObserver ile izlenir; tek satıra sığmıyorsa (ya da bir
  kapsül sağ kenarı / oynatma çubuğu kutusunu aşıyorsa) `data-fit` kademesi artar: **1** boşluk/iç boşluk küçülür, gimbal etiketinin ipucu
  ("(↑↓ / tekerlek)", `setGimbalLabel` → title'da tam metin) ve görünüm kısayol numarası gizlenir; **2** ikincil etiketler simgeye iner (Sanal kumanda,
  Hassasiyet, Kumanda, Kayıt, Mod, kamera türü, Sıfırla); **3** Dinle ve görünüm adı da simge, yazı 12,5 px; hâlâ taşıyorsa oynatma çubuğu kendi satırına
  (`data-fit-wrap`). Gizlenen etiketin düğmesi `aria-label` + `title` taşır. ≥ 1280 px TR/EN/DE tek satır; 1024–1279 px en çok iki satır; mobil
  (§39 `.fs-mob`) hiç sıkıştırılmaz. Test: `node tests/test_flightsim_flyui.mjs` (`pickFitLevel`, `setGimbalLabel`), görsel
  `./.venv/bin/python -m tests.fltfit_shots_hepgo` (çok rotorlu gimbal, sabit kanat, rover, replay; panel açık/kapalı; 1600…1024; mobil;
  `FLTFIT_LANG=en|de`) ve `tests.fltfit_shots_simumav` (TR/EN/DE; /tmp/fixes-shots/fltfit-*.png).

## 37. Sanal kumanda varsayılan açık + fiziksel kumanda (Gamepad API) (`static/js/modules/flightsim_gamepad.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: "Tüm simülasyonlarda sanal kumanda açık gelsin. Tarayıcıya takılan fiziksel kumanda / joystick tanınsın ve aracı RC olarak kontrol etsin."
- **Varsayılan açık**: yazma izni olan canlı oturumda (karşılaşma §33 dahil) sanal kumanda kendiliğinden açılır; kullanıcı 🎮 ile kapatırsa tercih
  hatırlanır (HEPGO `localStorage caymaz.fs.rc.on = '0'`, SIMUMAV `sm.rcOn = false`); ilk açılış / yeni kullanıcıda açık. Kayıttan oynatmada kumanda yok.
  Otomatik açılışta kopterde gaz kanalı (ch3) ilk gaz girdisine (W/S, Boşluk, sol çubuk, fiziksel kumanda gazı) dek **0 = dokunma** gönderilir
  (`virtualRC lazyThr`): yerde 1500 µs gaz override'ı ARM ön denetimini ("Throttle too high") bozmasın; uçakta gaz zaten 1000 (rölanti). Sahne,
  kumandadan sonra kurulursa klavye kilidi (`setKeyboardLock`) sahne hazır olunca uygulanır.
- **Fiziksel kumanda**: `navigator.getGamepads()` + `gamepadconnected/disconnected`; bağlanınca tost + olay şeridi, alt bantta 🎮 Sanal kumanda / ⚙
  kapsülünde **Kumanda** simgesi (`.fs-pad-btn`; kol oynarken yeşil). Sanal kumanda kapalıysa açılır. Kumanda 20 Hz yoklanır ve durumu sanal kumandanın
  20 Hz tick'ine `pad()` olarak girer — aynı `{t:'rc', ch}` yolu, aynı §27.1 eğrisi, Mode 2 (sol çubuk gaz / sapma, sağ yunuslama / yatış); kara
  aracında sol dikey gaz + sağ yatay direksiyon (`roverRcChannels`). Öncelik: kollar nötr dışındaysa ya da son 1,5 sn'de oynatıldıysa kumanda yazar;
  dokunulan sanal çubuk o tarafta kazanır; kumanda nötr ve hareketsizken klavye / sanal çubuk çalışır. Uçakta standart gamepad'in yaylı gaz kolu
  HIZ olarak (klavye W/S gibi tutmalı); RC vericide mutlak.
- **Eşleme** (profil başına, `fs.pad.cfg`): `standard` (W3C standart eşleme; Xbox / PS / çoğu USB gamepad): eksen 0/1 sol X/Y, 2/3 sağ X/Y (Y ters),
  ölü bölge %8, düğme 9 Start = ARM, 8 Back = DISARM (güvenli: `fltBar.act()` — sabit kanatta havada motor kesme, kopterde onaylı), 5 RB / 4 LB =
  sonraki / önceki mod, 12 / 13 yön = ch5 ±. `rc` (eşleme '' — EdgeTX / OpenTX / Radiomaster USB joystick): X kanatçık, Y irtifa (ters), Z gaz, Rx
  istikamet, ölü bölge %3, düğme ataması yok. Panel: ölü bölge, eksen başına dizin + Ters (canlı çubuk), düğme başına dizin (basılınca yeşil),
  Varsayılana dön. SIMUMAV menüsündeki gamepad gezinmesi (`menu/index.js`) yalnız menü sayfasında yoklar; uçuş ekranıyla çakışmaz.
- **Kumanda girdisi hassasiyeti** (panelde "Kumanda girdisi hassasiyeti"; `fs.pad.cfg` profil başına `scale` + `sens.{thr,yaw,pitch,roll}.{rate,expo}`;
  eski kayıt / eksik alan → %100 / expo 0 = kimlik, davranış değişmez): ölü bölgeden ve ters çevirmeden SONRA `padCurve`: expo
  `y = (1−e)·x + e·x³` (%0–80; merkezde yumuşak, uçta tam) → × eksen ölçeği (%25–150) × genel ölçek (%25–150) → ±1 kırpma (>%100: tam çıkışa daha
  kısa kolda ulaşılır). Genel ölçek tutum eksenlerine (sapma / yunuslama / yatış; kara aracında direksiyon) uygulanır, **gaza uygulanmaz** (RC "rate"
  geleneği: askı / rölanti noktası kaymaz); gazın yalnız kendi eksen ölçeği + expo'su vardır. Gaz kipleri korunur: kopter / kara aracı simetrik
  (merkez = askı / dur); uçak + standart gamepad yaylı kol → eğri HIZA uygulanır; uçak + RC verici MUTLAK tek yönlü → `padThrAbs` eğriyi
  rölanti…tam (0…1) aralığında uygular, rölanti (−1 → 1000 µs) her ayarda ulaşılır (`state().thrAbs`, `virtualRC` uçakta bunu kullanır).
  Kara aracında sekmeler yalnız Gaz + Direksiyon (`vehicle: 'rover'`), genel ölçek gizli.
  **§27.1 ⚙ Hassasiyet ile ilişki — iki katman, çakışmaz**: bu ayar YALNIZ fiziksel kumandanın kolunu, eksen değeri sanal kumandaya yazılmadan
  önce şekillendirir (girdi katmanı); ⚙ Hassasiyet (`fs.rc.feel`) sanal çubuk, klavye ve kumanda için ORTAK çıkış eğrisidir (kanal PWM'i). Panelde
  ayrı başlık ("Kumanda girdisi hassasiyeti") + açıklama; SVG önizlemede mavi = kumanda girdi eğrisi, kesikli turuncu = ⚙ ile birlikte
  (`feelShape` = oturumun `rcShape`'i; ⚙ değişince `refreshCurve()`), kesikli gri = doğrusal; sarı nokta + "giriş → çıkış" canlı.
- **Canlı gösterge + Algıla** (panel açıkken `requestAnimationFrame` döngüsü `padFrame`; panel kapalıyken döngü yok, kontrol yoklaması 20 Hz
  `setInterval` ile ayrı): basılı düğmenin satırı + numara rozeti yeşil halka / parıltı ile PARLAR (bırakınca kısa geçişle söner; "Canlı" şeridinde
  tüm düğme rozetleri), oynatılan eksenin satırı hafif mavi parlar + çubuk (eğrili çıkış) + beyaz işaret (ham giriş), eksen sekmesi de parlar.
  Satır başına **Algıla**: düğmede "Düğmeye basın…" → atama başlarken basılı olmayan ilk basılan düğme anında atanır (aynı düğme başka eylemdeyse o
  eylem boşa düşer); eksende "Kolu yukarı / sağa itin…" → tabandan ≥ 0,5 oynatılan en büyük eksen (`padLearnAxis`; ham değer azaldıysa Ters),
  aynı eksen başka satırdaysa boşa düşer. Atanan satır sarı onay parlaması; atama sırasında ve düğme bırakılana dek o basış eylem TETİKLEMEZ
  (`muted`); Esc önce atamayı bırakır. `prefers-reduced-motion` → geçiş / nabız yok. Mobilde (≤ 760 px) panel ☰ menüsünün dışına (tam ekran öğesi
  ya da body) taşınır, ekrana sığan sabit katman (`.fs-pad-pop.mob`).
- **Testler**: `node tests/test_flightsim_gamepad.mjs` (ölü bölge, eşleme + ters çevirme, ayar kalıcılığı, düğme kenarları, hassasiyet / expo /
  ölçek / kırpma / sınırlar, eski kayıt uyumu, gazda genel ölçek yok, uçak mutlak gazı, eksen algılama, sahte gamepad ile RC kanalları, dokunma
  önceliği, uçak gaz hızı, kara aracı, lazyThr, 6 + 7 dil), `node tests/test_simumav_rc.mjs`. Görsel: `RCPAD_TARGET=hepgo|simumav
  ./.venv/bin/python -m tests.padcfg_shots` (panel, basılı düğme parlaması, eğri önizleme, Algıla, rAF yalnız açıkken, RC'ye yansıma; masaüstü +
  390×844 mobil → `/tmp/padcfg-shots`).

## 38. Kumanda açıkken göstergeler ince ilerleme çubukları (`flightsim_gtheme.js` CSS; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: sanal ya da fiziksel kumanda aktifken ortadaki yuvarlak kadranlar çubukların arasında yer kaplamasın. `.fs-stage.rc-on` iken
(sanal kumanda açık; fiziksel kumanda §37 de bu yoldan) `.fs-gauges` alt ortada TEK kutu: her gösterge bir satır — etiket (HIZ / MOTOR / YAKIT /
BATARYA) · doluluk çubuğu (`.fs-gauge-bar` `--f` = kadran ibresi doluluğu `gaugeFrac`) · değer + birim; hız ve motor üstte. Renkler seçili temadan
(cam kokpit `--gl-*`, diğerleri `--fsg-*`; askerî yeşil parıltı; düşük sarı, kritik / boş kırmızı); "Göstergesiz" temada hiç görünmez. Kutu 300 px
(dar ekranda `100% − 24 px`), çubukların ortasında (`bottom: 104px`); ≤ 1180 px'te sanal çubuklar kenarlara alınır (arada yer kalsın), ≤ 600 px'te
kutu çubukların üstüne çıkar. Kumanda kapanınca kadranlar aynen döner (yalnız CSS; DOM ve güncelleme aynı). Ayrıntı kutusu (tıklayınca) çalışır.
Görsel: `RCPAD_TARGET=hepgo|simumav ./.venv/bin/python -m tests.rcpad_shots` → `/tmp/fltbar-shots/rcpad-*` (önce: `rcpad-once-*`).

## 39. Mobil: üst şerit + alt bant ☰ menüsünde (`static/js/modules/flightsim_mobile.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: telefonda simülasyon ekranında üst başlık ve alt bant varsayılan gizli; şık tek bir yüzen düğme ile açılır menü.
- Ortam sorgusu `MOBILE_MQ`: `(max-width: 820px)` ya da dokunmatik (`pointer: coarse`) + genişlik ≤ 1024 px ya da yükseklik ≤ 500 px (yatay telefon).
  Eşleşince `.fs-stage.fs-mob` + `body.fs-mob`: `.fs-nav` ve `.fs-bar` gizli, HEPGO uygulama başlığı / alt çubuğu gizli, sahne tüm ekranı kaplar,
  `--fs-bar-h: 0` (panel, kadran, PiP yerleşimleri). Masaüstü değişmez.
- Sol üstte `.fs-mob-btn` (46 px, cam görünüm; `env(safe-area-inset-*)` çentik payı): ☰ → menü açık (✕): üst şerit üstte kapsül (Geri, başlık, durum,
  hız, tam ekran), alt bant altta çekmece (40 px dokunma hedefleri, alt güvenli alan payı); arka plan karartılır. Tekrar basınca, arka plana
  dokununca ya da Esc ile kapanır. Bant içindeki açılır menüler (görünüm, servo paneli, mod, ses) çekmecenin üstünde açılır. Rüzgâr göstergesi
  düğmenin altına iner. Metinler "Menü" / "Menüyü kapat" (HEPGO 6 dil, SIMUMAV `mob.*` 7 dil).
- Görsel (Chromium mobil emülasyonu: `is_mobile` + `has_touch`, iPhone UA; WebKit kurulu değil): 390×844, 412×915, yatay 844×390 — kapalı / açık,
  taşma denetimi (`tests.rcpad_shots`).

## 40. Hedefli uçuşta BOŞLUK ile kilit + ANGAJMAN (`static/js/modules/flightsim_engage.js`; sunucu `app/flightsim_targets.HedefIzleyici`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: hedefli uçuşta bir hedefin TD kutusu ekrandayken Boşluk o hedefe kilit açsın, tekrar Boşluk bıraksın; kilitle angajman başlasın
(HUD'da kilit sembolü, süre, mesafe, kapanma hızı, hedef açısı), hedef önlenince "ANGAJMAN BAŞARILI", kilit bırakılınca ya da hedef 3 sn'den uzun
görüş dışında kalınca "ANGAJMAN KESİLDİ"; sunucuda kayıt + özet raporda liste; kayıttan oynatmada görünsün; fiziksel kumandada atanabilir düğme.
**Kapsam:** yalnız simülasyon içi oyun mekaniği (HUD kilidi, süre, sonuç, puan). Araca otonom yönelme / güdüm / takip komutu YOKTUR — pilot
aracı kendisi uçurur; kilit yalnız göstergeyi ve puanlamayı etkiler.

- **Görünürlük = §24.5 sembolojisinin kutusu ekranda** (`symbology()` → öğe `on`): son render edilen ana kameranın pozuyla hesaplanır, kamera kipi
  fark etmez. Gimbal/FPV kiplerinde HUD/OSD TD kutusunu zaten çizer; takip/serbest/yer kiplerinde (ya da HUD kapalıyken) modülün kaplama tuvali
  (`.fs-eng-cv`) aday ya da kilitli hedefin TD kutusunu + "Boşluk: kilit" ipucunu çizer (HUD/OSD son 1,5 sn'de çizdiyse kaplama çizmez —
  `targetsHud({peek:true}).hudFresh`; `peek` sahne etiketlerini gizlemez).
- **Boşluk** (pencere yakalama evresinde dinlenir; yalnız canlı + yazma izni + hedefli oturum): kilitliyse → bırak; değilse aday = HUD'un TD
  kutusundaki hedef (oto en yakın ya da Tab seçimi) ekrandaysa o, değilse ekranda görünen hedeflerden boresight'a (ekran merkezi) en yakını →
  `cmd engage {action:'lock', i}`. Aday yoksa: sanal kumanda kapalıysa kısa ipucu "Kilit için bir hedefin kutusu ekranda olmalı", **açıksa Boşluk
  eski davranışına** (kopterde gaz orta, kara aracında dur) geçer. Kumanda ipucu satırına hedefli oturumda "Boşluk: hedef kutusu ekrandayken
  kilit / angajman" eklenir; HUD/OSD ipucu "Tab: hedef · Boşluk: kilit". Kayıttan oynatmada Boşluk oynat/duraklat kalır. Angajman sürerken Tab ve
  radar tıklaması kilidi değiştirmez (`flightsim3d` `tg.eng`).
- **Fiziksel kumanda** (§37): `PAD_ACTIONS` + `lock` (standart eşlemede düğme 0 = A / ✕; RC verici profilinde atanmamış); eşleme panelinde
  "Hedef kilidi (angajman)" satırı; basınca Boşluk ile aynı (`engage.toggle()`).
- **Sunucu (otoriter):** `HedefIzleyici.kilit_ac(i)` → angajman başlar (başka hedefe kilit varken önce `switched` ile kesilir), `kilit_birak(sebep)`
  (`released` | `lost`); her telemetri adımında kilitli hedefe en yakın mesafe güncellenir; **kilitli hedef önlenince** (mevcut önleme yarıçapı,
  §24) angajman `success` (`reason: intercept`, `end_dist_m`), önleme olayına `locked: true`; Sıfırla (SITL saati geri) etkin angajmanı `reset`
  ile keser. Görüş dışı süresini istemci ölçer (`ENGAGE_LOST_MS` 3000; kamera sunucuda yok) → `release {reason:'lost'}`. Zaman = SITL saati
  (`t0` tt saniyesi, `start_s` ilk ARM'dan, `dur_s`). WS `{t:'engage', kind: start | success | cut, i, name, t0, start_s, dur_s, start_dist_m,
  min_dist_m, result?, reason?, state}`; oturum yanıtı/hello `engagement` (etkin angajman; yeniden bağlanan istemci için). SITL'e STATUSTEXT
  `ENGAGE T1 LOCK | OK 7.8s | CUT lost` (ArduPilot DataFlash MSG → .bin kayıttan oynatma şeridinde de görünür; Mission Planner mesajlarında).
  Komut doğrulaması 400: hedefsiz oturum, `i` tam sayı değil / bilinmeyen, `action`/`reason` geçersiz. SIMUMAV aynı çekirdek komutu (`KOMUTLAR`).
- **Puan:** kilitli angajmanla önleme bonusu **+250** (hedef başına bir kez; `HedefIzleyici.ozet().items[].locked_hits`, `flightsim_targets.js
  ENGAGE_BONUS` aynı kural). Özet: `targets.engagements[{i, name, t0, start_s, dur_s, start_dist_m, min_dist_m, end_dist_m?, result: success |
  cut | active, reason}]` (≤ 200), `engaged_hits`; `drone_sim_runs.targets.result` içinde kalıcı (göç yok — JSON alanı).
- **HUD:** tgthud `data.eng` → kilitli hedefin TD kutusu **çift çerçeve** + üstte "KİLİT" (ekran dışındaysa ok bloğunda). Angajman paneli
  (`.fs-eng`, üst orta, her kipte): "◆ KİLİT · ANGAJMAN · T1 ad", süre, mesafe, Vc (±m/s, yaklaşma +), açı (burun yönünden yatay sapma, R/L°),
  ΔH; görüş dışıyken "GÖRÜŞ DIŞI 2.1 sn" geri sayımı; başarıda 2,5 sn yeşil "ANGAJMAN BAŞARILI · ad · 7.8 s". Olay şeridi (ön yüz kendi dilinde):
  "ANGAJMAN · ad", "ANGAJMAN BAŞARILI · ad · süre", "ANGAJMAN KESİLDİ · ad · süre · sebep". Sesler: kilit çift bip, başarı üçlü, kesilme alçalan
  (Web Audio; dosya yok).
- **Kayıttan oynatma:** oynatma oturumu `engagements` (kaydın `drone_sim_runs.targets.result.engagements`, `bin_log_id` eşleşmesi) → istemci kare
  `tt`'siyle eşler (`engagementAt` / `engagementEvents`): kilit + panel + olay satırları; atlamada sıfırlanır.
- **Rapor:** HEPGO özet raporu "◎ Hedefler" bölümünde "◆ Angajmanlar n/m" tablosu (hedef, başlangıç, süre, sonuç, en yakın) + bonus notu;
  SIMUMAV uçuş özeti hedef kartında aynı satırlar (`eng.*`).
- **Metinler:** HEPGO 6 dil (Türkçe anahtar), SIMUMAV 7 dil (`eng.*`, `pad.act_lock`, HUD'un Türkçe anahtarları "KİLİT", "Boşluk: kilit").
- **Testler:** `node tests/test_flightsim_engage.mjs` (aday seçimi, Boşluk kararı, 3 sn sayacı, açı/Vc, oynatma eşlemesi, rapor satırları, puan,
  tgthud kilit sembolü, 6 + 7 dil, bağlama, gamepad); `.venv/bin/python -m tests.test_flightsim_engage` (izleyici + API uçtan uca sahte kip +
  kalıcı kayıt). Görsel: `./.venv/bin/python -m tests.engage_shots` → `/tmp/dogfight-shots/engage-*.png` (takipte aday, kilit + panel, gimbal
  HUD'unda çift çerçeve, başarı, raporda liste, kutu yokken ipucu).

## 41. Karşılaşmada "İT DALAŞI" türü — 2 kişilik kovala / kaç (`app/flightsim_match_core.py` `ItDalasi`; ön yüz `static/js/modules/flightsim_dogfight.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: mevcut karşılaşmaya (§33 halka yarışı) tür seçimi "Halka yarışı | İt dalaşı". İt dalaşı tam 2 oyuncu; roller KOVALAYAN / KAÇAN
(kurucu seçer ya da rastgele; rövanşta roller değişir); aynı irtifada, ayarlanabilir mesafe, kaçan önde başlar; kovalayan kaçanı menzil + burun konisi
içinde gereken süre kesintisiz tutarsa ANGAJE → kovalayan kazanır; süre biterse kaçan; alan dışına çıkan / yere çarpan kaybeder; sunucu otoriter.
**Kapsam:** yalnız oyun mekaniği (HUD, kazanan, puan). Araca otonom yönelme / güdüm / takip komutu YOKTUR — iki pilot da aracını kendisi uçurur.

### 41.1 Çekirdek (saf; `flightsim_match_core.py`)
- **Ayar** `it_ayar_dogrula(r, tip)` (MacHata `invalid`): `distance_m` 300–1500 (başlangıç mesafesi), `alt_m` 20–400 (başlangıç irtifası, merkez
  zemininden), `time_limit_min` 2–10 (tam sayı), `range_m` 50–400 (angajman menzili), `cone_deg` 15–45 (kovalayanın burnundan ±), `hold_s` 2–5
  (kesintisiz tutma), `area_radius_m` 300–5000 (merkezden yatay alan sınırı; ≥ mesafe/2 + 150; verilmezse sınıf varsayılanı mesafeye göre büyür),
  `roles` `random` | `host_chaser` | `host_evader`, `seed`. Varsayılanlar: dikey (kopter/heli/VTOL/INTERCEPTOR) 400 m · 40 m · 5 dk · 120 m · ±30° ·
  3 s · R 800; sabit kanat 1000 m · 120 m · 6 dk · 300 m · ±25° · 3 s · R 3000. `vclass` (dikey | ucak) ayara gömülür.
- **Roller** HAZIRLIK'a geçişte (`_roller_ata`): kurucunun seçimi ya da tohumlu rastgele (aynı tohum = aynı roller). `Oyuncu.rol`, anlık görüntüde
  `players[].role` ve `dogfight.roles`.
- **Başlangıç** `it_baslangiclari(ayar, tip, pist_yonu)`: iki araç merkezden geçen ortak hatta `distance_m` ayrık, ikisi de hat yönüne bakar →
  kaçan önde, kovalayan arkada. Hat yönü sabit kanatta pist yönü (kalkış koridoru), dikeyde tohumdan. SITL'de araçlar yerden kalkar: "aynı irtifada"
  koşulu **kalkış koruması** ile sağlanır — iki araç da `alt_m`'nin %80'ine çıkana ya da `KORUMA_S` (60 sn) dolana dek angajman sayılmaz (HUD
  "KALKIŞ KORUMASI — 32 m'ye çıkın"; olay `guard_off`).
- **Angajman** `ItDalasi.konum(rol, x, y, z, heading, pitch, t)` (her iki oyuncunun telemetrisi; örnekler arası en çok 2 sn fark): görüş hattı d
  (kovalayan → kaçan), burun vektörü (`burun`: sabit kanatta yön + yunuslama; dikey kalkanlarda gövde eğimi burun değildir → yalnız yön), açı
  `koni_acisi`; `dist ≤ range_m` ve `açı ≤ cone_deg` ve koruma kalktı → koni içinde; tutma süresi ardışık örnekler arası dt (≤ 0,5 s) toplanır,
  koniden çıkınca SIFIRLANIR (kesintisiz). `tutma ≥ hold_s` → `engage` → kovalayan kazanır (`angaje`). Olaylar `lock_on` / `lock_off` (kaçana uyarı
  için), `guard_off`, `area` (yatay uzaklık > `area_radius_m` → o rol kaybeder, `alan_disi`). İstatistik: en uzun tutma, en yakın mesafe, koni süresi.
- **Karsilasma** (`tur='dogfight'`): tam 2 oyuncu (oluşturmada denetim); `tik`: GERI_SAYIM → YARIS'ta `ItDalasi`; süre dolunca kaçan kazanır
  (`sure`); `carpti(uid)` (platformun kesin çarpışma kaydı) → çarpan kaybeder (`carpti`); yarışta rakip ayrılır / düşerse kalan kazanır
  (`rakip_ayrildi`). `konum(..., heading, pitch)` it dalaşında `_it_konum`'a gider. Sonuç `{kind:'dogfight', winner, reason, duration_s,
  standings (kazanan önce, role), dogfight {engage_s, max_hold_s, min_dist_m, need_s, roles}}`; `dict()` ek alanları `kind`, `dogfight` (HUD ölçüleri).
  Halka yarışı davranışı değişmedi (`kind: 'rings'`).

### 41.2 HEPGO çalışma zamanı / REST / DB
- `POST /api/drone/sim/matches {settings, kind: 'rings' | 'dogfight', rings?, dogfight?, invite}`: it dalaşında tam 1 davetli (400), ayar 400.
  Meta `limits.kinds`, `limits.dogfight {sınırlar, roles, guard_s, defaults}`. Liste satırında `kind`. `POST /{id}/rematch` (kurucu, BITTI, it dalaşı):
  aynı ayarlar, roller ters (`host_chaser` ↔ `host_evader`), rakip davet edilir; eski salona WS `{t:'rematch', id}`.
- `MatchRuntime`: başlangıç noktaları rol başına; tele kancası `heading` + `pitch`'i çekirdeğe verir; `gorev.crashes` artışı → `k.carpti`; `pos`
  çerçevesine `df {roles, dist, off_deg, rel_alt, bearing_deg, in_cone, hold_s, need_s, guard, max_hold_s, min_dist_m}`; komut kapısı
  `KAPI_KOMUTLARI` + `reset`: it dalaşında geri sayım/yarışta Sıfırla reddi ("İt dalaşında Sıfırla yok"; başlangıca ışınlanma kaçış olmasın; halka
  yarışında serbest). WS `{t:'dogfight', kind: guard_off | lock_on | lock_off | engaged | area | crash, id?, held_s?}`. Davet push metni türe göre.
- **DB göçü (HEPGO `app/db.py`, idempotent):** `drone_sim_matches.kind TEXT NOT NULL DEFAULT 'rings'` + `game_cfg TEXT` (`PRAGMA table_info`
  denetimiyle `ALTER TABLE … ADD COLUMN`, yalnız yoksa; eski satırlar 'rings'). İt dalaşında `rings_cfg = '{}'`, ayar `game_cfg`'de; GET/liste
  `rings_cfg` alanında it dalaşı ayarını döndürür (istemci için tek alan).

### 41.3 Arayüz
- **Sihirbaz** "Tür ve kurallar" adımı (eski "Halkalar"; `flightsim_wizard.js` başlığı): üstte iki kart "◎ Halka yarışı" | "✈ İt dalaşı"; it
  dalaşında kaydırıcılar (mesafe, irtifa, süre, menzil, koni, tutma, alan) + roller seçimi + kurallar metni + şema (`dfSvg`: alan dairesi, K arkada /
  Ç önde, kovalayanın koni kaması, mesafe). Davet adımı it dalaşında tam 1 davetli (`setMax(1)`); özet satırları türe göre.
- **Salon**: ayarlarda tür + kurallar özeti + rolüm (atanınca rozet), oyuncu listesinde rol rozetleri, şema; bitmiş it dalaşında kurucuya "Rövanş
  (roller değişir)", rakibe gelen bildirimle "Rövanş" bağlantısı.
- **Yarış ekranı HUD'u** (`createDogfightHud`, `.fs-df-cv` + `.fs-df-bar` + `.fs-df-alert`; sıralama tablosu ve halka şeridi gizlenir): rakip
  işaretçisi (TD kutusu benzeri kare + merkez elmas; kovalayanda sarı, koni içinde kırmızı; kaçanda mavi), ekran dışında kenar oku + mesafe
  (`opponentMarker`: tgthud izdüşümü + `sim.cameraView()`); **kovalayanda** kutunun çevresinde dolan angajman halkası (tutma / gereken) ve şeritte
  "KONİ İÇİNDE 1.4/3.0 s" | "KONİ DIŞI 34° / 25°" | "MENZİL DIŞI 220 / 150 m"; **kaçanda** koni içindeyken yanıp sönen "⚠ KİLİTLENİYOR!" + dolan
  çubuk + uyarı sesi (çift bip, ~0,45 sn'de bir). Şerit: rol rozeti (KOVALAYAN kırmızı / KAÇAN mavi), kalan süre, mesafe, rakibin bağıl irtifası
  (↑/↓), kalkış koruması, alan sınırına %85'te "ALAN SINIRI! d / R m". 3B'de rakip §33 oyuncu katmanıyla (renkli gövde + isim) görünür.
- **Sonuç**: kazanan + "KAZANDINIZ / KAYBETTİNİZ", sebep (angaje / süre — kaçan kazandı / alan dışı / çarptı / rakip ayrıldı), angajman süresi, en
  uzun tutma / gereken, en yakın mesafe; tablo: rol, oyuncu, sonuç, azami hız, çarpışma. Karşılaşmalar sekmesinde "Karşılaşma türü" sütunu.
- **Metinler**: `DF_TEXTS` (HEPGO Türkçe anahtar, 6 dil; SIMUMAV `df.*` 7 dil).

### 41.4 Testler ve görsel doğrulama
- `.venv/bin/python -m tests.test_flightsim_match`: `it_dalasi_testleri` (ayar sınırları, başlangıç hattı / kaçan önde / deterministik, burun ve koni
  açısı (uçakta yunuslama, kopterde yok), koruma, kesintisiz tutma + kesinti sıfırlama, menzil dışı, bayat örnek, alan dışı, roller (kurucu / rastgele
  iki yöne / tohum), kazanan: angaje / süre → kaçan / alan dışı / çarpma / rakip ayrıldı, halka yarışı etkilenmez) + `it_dalasi_api` (sahte kinematik
  `tests/match_bot.it_pilotu`: kaçan düz uçar, kovalayan 90 m gerisinden ona dönük → ANGAJE; 400'ler, roller, başlangıç mesafesi, Sıfırla kapısı,
  `pos.df`, `dogfight` olayları, sonuç iki WS'de, DB kind/game_cfg, liste türü, rövanşta roller ters).
- `.venv/bin/python -m tests.test_simumav_match`: `it_dalasi` (SIMUMAV: önizleme iki başlangıç, oyuncu 2'ye sabit, davet özetinde tür, roller,
  Sıfırla kapısı, ANGAJE, DB v4 göçü kind/game_cfg, geçmişte tür).
- `node tests/test_flightsim_dogfight.mjs` (sınırlar çekirdekle aynı, doğrulama, rol/kalan süre/koni durumu, sonuç satırları, işaretçi, şema, 6 + 7
  dil, bağlama). Görsel: `./.venv/bin/python -m tests.dogfight_shots` → `/tmp/dogfight-shots/df-*.png` (tür seçimi, salon, kovalayan HUD'u, kaçan
  uyarısı, sonuç, salonda rövanş, Karşılaşmalar sekmesinde tür); SIMUMAV: `./.venv/bin/python -m tests.simumav_dogfight_shots` → `df-sm-*.png`
  (sihirbaz tür seçimi + şema, davet 2 oyuncu, salon). Not: görsel betikte tutma süresi görüntü alınırken geçici büyütülür (`20.5/120.0 s`).

## 42. UÇUŞ UYARI SİSTEMİ — sesli + görsel GPWS / stall / bank angle / master caution (`static/js/modules/flightsim_gpws.js` saf + `flightsim_gpws_ui.js` arayüz/ses; sunucu `app/flightsim_gpws.py`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: "uçakta IMU ya da gyro saçmalarsa hem sesli hem görsel uyarı görünür, benzerini yapalım, oyuncu hata yapmaya çekinsin; açılıp
kapanabilir olsun." Gerçek uçaklardaki GPWS / EGPWS ("PULL UP", "TERRAIN", "SINK RATE", "TOO LOW", "DON'T SINK"), stall uyarısı (stick shaker),
"BANK ANGLE", master warning / master caution mantığı simülatöre taşındı; uyarılar uçuş özetine ve "uçuş disiplini" puanına yansır.

### 42.1 Değerlendirici (saf; istemcide, kayıttan oynatmada da aynı)
- **Girdi** (`teleInput(tele, ctx)`): canlı `tele` ya da kayıt karesi (aynı alan adları) → {t (SITL saati `tbm`; kayıtta kare zamanı), armed, mode,
  AGL, ileri bakış AGL'si, dikey hız, yer/hava hızı, roll/pitch (°), açısal hız (rs/ps/ys → °/s), batarya (§23 elektrik modeli öncelikli, yoksa SITL
  `batt_pct`), yakıt (§23), GPS fix, `sens_bad`, `ekf`, `vibe`, rüzgâr, motor kesik, kalkış aşaması, evden mesafe, bağlantı yaşı, çarpışma}.
  **AGL 3B araziden** (`sim.position()` − `sim.terrainHeight`; prosedürel dünyada SITL arazisi yok); yoksa `terrain_agl`, o da yoksa `alt_rel`.
  İleri bakış: hız vektörüyle `look` (kopter 4 sn, uçak 8 sn) sonrası ve yarısındaki konumun arazisine göre AGL (arazi yükselmesi + alçalma birlikte).
- **Yeni tele alanları** (gerçek SITL; `app/flightsim.py _isle`): `sens_bad` = SYS_STATUS mevcut ∧ etkin ∧ ¬sağlıklı sensör bitleri;
  `ekf` = EKF_STATUS_REPORT hız / yatay konum / dikey konum / pusula varyanslarının en büyüğü; `vibe` (m/s², VIBRATION x/y/z en büyüğü) + `clip`.
  Ölçüm (gerçek ArduCopter SITL): düz uçuşta `sens_bad = 0x200000` (AHRS biti "sağlıksız") → IMU maskesi yalnız jiroskop (1) + ivmeölçer (2).
- **Araç sınıfı** (`vehicleClass`): copter (multirotor/hexarotor/fpv) · heli · plane (sabit kanat) · vtol · icept (INTERCEPTOR) · rover. VTOL ve
  INTERCEPTOR Q kiplerinde (QHOVER…) kopter eşikleri, diğer kiplerde uçak eşikleri (`modeKind`). Kara aracında uçuş uyarıları yok; STALL yalnız kanatlıda.
- **Uyarılar ve eşikler** (sens = Normal; "açıkken" sütunu histerezis — uyarı açıkken gevşeyen eşik; tetik gecikmesi varsayılan 0,3 sn):

| Kod | Seviye | Kopter | Uçak (sabit kanat / VTOL-FW / INTERCEPTOR-FW) | Not |
|---|---|---|---|---|
| PULL UP | WARNING | AGL < 80 m, kapanma > 2,5 m/s, çarpmaya kalan < 3,5 sn (açıkken ×1,3) | AGL < 300, kapanma > 4, < 5 sn | kapanma = max(alçalma, ileri bakış AGL kaybı / look) |
| TERRAIN | WARNING | kaynak arazi yükselmesi, < 7 sn | < 10 sn | LAND / RTL·AUTO son yaklaşmada yok |
| STALL | WARNING | — | hava hızı < 9 m/s (açıkken 10,35) ya da pitch > 15° ve < 11,7 m/s; AGL > 3 | ses: stick shaker |
| GYRO / IMU FAULT | WARNING | gyro/ivme sağlık biti · EKF ≥ 0,8 · \|p\|,\|q\| > 400°/s 0,4 sn · \|r\| > 200°/s 2 sn · tutum sıçraması | \|r\| > 120°/s 3 sn | ACRO/FLIP/AUTOTUNE'da hareket kuralları yok; sıçrama 3 sn mandallı |
| ENGINE OUT | WARNING | havadayken DISARM + düşüş (> 1,5 m/s, AGL > 3, 8 sn içinde) | havada motor kesik (`motor_cut`) | tetik 0,5 sn |
| OVERSPEED | WARNING | yer hızı > 22 m/s | hava hızı > 38 (INTERCEPTOR 70, heli 30) | §23 azami hız ayarı varsa × 1,08 |
| BANK ANGLE | WARNING | \|roll\| > 35° (ayar 20–60) | > 45° (ayar 30–70) | açıkken −5° |
| PITCH | WARNING | \|pitch\| > 35° | burun yukarı > 30° / aşağı > 25° | kalkışta yok |
| SINK RATE | WARNING | alçalma > 6 m/s (AGL < 240) ya da alçalma kaynaklı < 7 sn | > 12 m/s ya da < 10 sn | |
| BATTERY CRITICAL | WARNING | < %10 ya da §23 batarya bitti | aynı | tetik 1 sn |
| FUEL | WARNING | §23 yakıt < %5 ya da bitti | aynı | |
| GPS LOST | WARNING | bir kez 3B fix görüldükten sonra fix < 3 (1 sn) | aynı | |
| GEOFENCE | WARNING | evden mesafe > HEPGO dünya yarı boyutu (`world.size_m/2`) · SIMUMAV parkur yarıçapı | aynı | |
| TOO LOW | CAUTION | (tepe AGL > 15) AGL < 4 m ve yer hızı > 8 | (tepe > 60) AGL < 30 ve > 12 m/s | iniş dışında |
| DON'T SINK | CAUTION | havalanmadan sonraki 60 sn'de, AGL < 40, tepeden > 6 m kayıp, alçalıyor | AGL < 200, > 15 m kayıp | |
| EKF VARIANCE | CAUTION | 0,5 ≤ EKF < 0,8 | aynı | |
| VIBRATION | CAUTION | > 30 m/s² (açıkken 25) | aynı | |
| BATTERY LOW / FUEL LOW | CAUTION | < %25 / < %20 | aynı | |
| HIGH WIND | CAUTION | rüzgâr > 12 m/s (2 sn) | > 15 m/s | |
| LINK LOST | CAUTION | canlıda telemetri > 1,5 sn gelmezse (1 sn gecikme; gizli sekmede ölçülmez) | aynı | |

- **Hassasiyet** Düşük / Normal / Yüksek: çarpma süresi eşikleri ve TOO LOW irtifası × 0,75 / 1 / 1,3, sert alçalma eşiği ÷ aynı oran.
- **Evre bastırma:** ARM'sız uyarı yok (yalnız ENGINE OUT'un "havada DISARM" kuralı); kalkışta (havalanmadan önce + havalanmadan sonra kopter 3 sn
  / uçak 8 sn, rampa/fırlatıcı `armed`/`launch` aşaması, TAKEOFF kipi) arazi / alçalma / stall / pitch / TOO LOW yok; LAND / QLAND her zaman, RTL /
  QRTL / SMART_RTL / AUTO ise AGL < 25 m (uçak 60) ve evden < 60 m (uçak 400) son yaklaşmada TERRAIN / TOO LOW / DON'T SINK yok; çarpışmada hepsi susar.
- **Durum makinesi** (kod başına): ham koşul `onDelay` kadar sürünce AÇILIR; koşul 1 sn yoksa ve en az 2,5 sn gösterildiyse KAPANIR (bölüm =
  {code, level, t0, start_s (ilk ARM'dan), dur_s}). Zaman 0,5 sn'den fazla geri giderse (Sıfırla, kayıtta geri atlama) açık bölümler kapanır ve
  bellek sıfırlanır. Öncelik sırası tablodaki gibi (WARNING'ler hep CAUTION'ların üstünde); birincil uyarı büyük kutuda, diğerleri çip.
- **Onay (MASTER):** o anki uyarılar onaylanır → ses susar, koşul sürerse görsel sabit kalır (yanıp sönmez); kapanıp yeniden açılan ya da yeni bir
  uyarı yine çalar. Seviye bazlı (MASTER WARNING yalnız kırmızıları, MASTER CAUTION yalnız sarıları). Kısayol **B**; kutuya tıklama hepsini onaylar.

### 42.2 Görsel ve ses (`flightsim_gpws_ui.js`)
- **Kutu** ekranın ortasının üstünde (%27; mobilde %20, küçük yazı): kırmızı "WARNING · PULL UP" / sarı "CAUTION · TOO LOW", onaylanmamışken yanıp
  söner; iki yanında **MASTER WARNING / MASTER CAUTION** lambaları (o seviyede uyarı yoksa gizli; onaylanmamışken yanıp söner); altında diğer etkin
  uyarılar (en çok 3 çip). WARNING'de ekran kenarında kırmızı **vinyet** (onaylanmamışken nabız). `prefers-reduced-motion` yavaşlatır.
- **FPV (pilot) ve gimbal (fpv) kipleri:** OSD / askeri HUD açıksa büyük kutu gizlenir; aynı metni OSD (merkezin üstünde OSD yazısı) ve HUD (çerçeveli
  kutu) kendisi çizer (`osdCtx.gpws` / `hudCtx.gpws` → `osdText()`); MASTER lambası ve vinyet kalır. Ekran kaydında HUD/OSD tuvali kayda girer.
- **Ses** (Web Audio, dosya yok; motor sesinin master kazancından geçen ayrı yol `audio.alertBus()` → ses düzeyi, 🔇, sekme gizli, ≥ 2× oynatma ile
  susar, ekran kaydına girer): PULL UP / TERRAIN / SINK RATE → "whoop whoop" (yükselen iki süpürme), diğer WARNING'ler → iki tonlu alarm, STALL →
  stick shaker (18 Hz çıngırak), CAUTION → çift çan. Tondan sonra **konuşma** (speechSynthesis): havacılık geleneği İngilizce ("Pull up", "Bank angle,
  bank angle", "Stall, stall"…); ayarda "Uyarı dili: Arayüz dili" seçilirse metin ve konuşma sitenin dilinde (Türkçe "YUKARI ÇEK" …). speechSynthesis
  yoksa yalnız ton. WARNING onaylanana dek ~3,6 sn'de bir yinelenir; CAUTION bir kez. Genel ses kapalıysa uyarı sesi de yok, görsel kalır.
- **Aç/kapa:** ses kapsülü (🔊 ▾) menüsünde "Uçuş uyarıları: Kapalı · Yalnız görsel · Görsel + ses" + ⚙ alt panel (uyarı dili, hassasiyet, araç
  tipine göre yatış eşiği kaydırıcısı, tür tür aç/kapa — araçta geçersiz türler soluk —, "▶ Dene" sırayla PULL UP / BANK ANGLE / STALL / TOO LOW
  gösterir/çalar). Sihirbazın son adımında ("Kayıt ve özet") aynı seçici. Tercih: HEPGO `localStorage fs.gpws`, SIMUMAV `sm.gpws`
  ({mode, lang, sens, bank_copter, bank_plane, off[]}); **varsayılan Görsel + ses AÇIK**. Kayıtlı simülasyon (preset) ayarına eklenmedi (tercih
  kullanıcıya ait, uçuşlar arasında hatırlanır).

### 42.3 Kayıt, sunucu, rapor, puan
- **Olay şeridi:** açılan uyarı "WARNING · PULL UP" (kırmızı) / "CAUTION · TOO LOW" (sarı), etiket `UYARI` (panel konsolu).
- **Sunucu** (`cmd gpws`, REST ve WS; SITL'e gitmez): {events: [{code, level, t0, start_s, dur_s}] (≤ 50), cfg?: {mode, off}}. İstemci açılışta ayarı,
  sonra biten bölümleri ~1,5 sn toplu gönderir; Bitir'de `flush()` açık bölümleri kapatıp gönderir (özetten önce). Doğrulama 400: bilinmeyen kod,
  seviye uyuşmazlığı, sayı dışı / negatif süre, > 50 öğe, geçersiz mod. Tekilleştirme (kod, t0 0,1 sn) — birden çok yazma izinli sekme çift saymaz;
  oturum başına ≤ 500 bölüm. Kayıttan oynatmada gönderilmez.
- **Özet** (`summary.alerts`; `flightsim_gpws.ozetle` = JS `summarizeAlerts`): {mode, off, events (≤ 200), by_code {code: {level, n, total_s, first_s}},
  warnings, cautions, total_s, score, grade}. **Uçuş disiplini** = 100 − Σ ceza; WARNING bölümü 6 + 1,5 × sn (en çok 20), CAUTION 2 + 0,5 × sn (en çok
  8); not A ≥ 90 · B ≥ 75 · C ≥ 60 · D ≥ 40 · F. Uyarılar kapalıysa puan yok. Bildirim hiç gelmediyse (eski istemci) `alerts` alanı yok.
- **DB göçü (idempotent, `app/db.py init`):** `drone_sim_runs.alerts TEXT` (özet JSON) + `alert_score INTEGER`; SIMUMAV çekirdek DB'si
  `app/simumav/shim/db.py RUN_EK_SUTUNLAR` (aynı iki sütun). Kapanışta Bitir'de üretilmiş özet satırının `alerts`'ı da son bölümlerle güncellenir.
- **Rapor:** HEPGO özet raporu "⚠ Uçuş uyarıları · Uçuş disiplini 72/100 · C" bölümü (kırmızı / sarı adet, toplam uyarı süresi, puan karoları +
  tür başına adet / toplam süre / ilk görülme tablosu; uyarısız uçuşta "Uyarısız uçuş — kusursuz disiplin."); rapor metni (paylaşım) satırı;
  Simülasyon Kayıtları kartında "Uçuş disiplini 72/100".
- **Karşılaşma** (§33/§41): oyuncu oturumu aynı oturum ekranı → uyarılar ve puan aynen. **Kayıttan oynatma:** kareler aynı değerlendiriciden
  geçer (görsel + olay şeridi; atlamada sıfırlanır; ses ≥ 2× hızda yok).

### 42.4 Testler ve görsel doğrulama
- `node tests/test_flightsim_gpws.mjs` (25): her uyarının tetik/temizlenmesi, histerezis, tetik gecikmesi + en kısa gösterim, evre bastırma, öncelik,
  araç tipine göre eşik (kopter/uçak/VTOL Q/kara aracı), onay, zaman geri gitmesi, kapalı mod / tür kapatma, özet + puan, ayarlar, telemetri
  dönüşümü, metinler, 6 + 7 dil, bağlama, sunucu kod listesi.
- `.venv/bin/python -m tests.test_flightsim_gpws`: saf kayıt (doğrulama, tekilleştirme, tavanlar) + puanın JS ile eşitliği (node) + HEPGO API uçtan uca
  (400'ler, WS komutu, özet, kapanışta drone_sim_runs.alerts/alert_score + özet satırı) + SIMUMAV shim/köprü/dışa aktarma.
- **Gerçek SITL:** `HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_flightsim_gpws_sitl` (~1,5 dk): ArduCopter kalkış 70 m →
  ALT_HOLD'da tam sağ yatış (ANGLE_MAX 30° → eşik 25°) → STABILIZE gaz kesik serbest düşüş → toparlama; tele kareleri istemci değerlendiricisinden
  geçer: yerde/kalkışta/askıda yanlış alarm yok, BANK ANGLE ve PULL UP (+ SINK RATE, DON'T SINK) açılır, IMU yanlış alarmı yok; özet puan eşit.
- Görsel: `./.venv/bin/python -m tests.gpws_shots_hepgo` → `/tmp/gpws-shots/hep-*.png` (PULL UP, onaylı, TOO LOW, gimbal HUD, FPV OSD, ses menüsü,
  ayar paneli, rapor, sihirbaz, mobil); `./.venv/bin/python -m tests.gpws_shots_simumav` → `sm-*.png`.

## 43. Grafik kalite ayarları — ön ayarlar, otomatik/uyarlamalı kademe, son işlem (`flightsim_gfx.js` + `flightsim_gfx3d.js` + `flightsim_gfx_ui.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: güçlü bilgisayarı olan görsel kaliteyi artırabilsin, zayıf olan düşürebilsin. TEK paylaşılan WebGL renderer korunur (ikinci bağlam
yok); değişiklikler simülasyonu yeniden başlatmadan canlı uygulanır.

### 43.1 Ön ayarlar (`GFX_PRESETS`, saf `resolveGfx(pref, caps, {level, scaleMul})`)
| Alan | Düşük | Orta | Yüksek (= §43 öncesi + son işlem) | Ultra |
|---|---|---|---|---|
| Çözünürlük ölçeği × dpr (tavan / piksel bütçesi) | 0,75 (≤ 1 / 1,3 MP) | 1 (≤ 1,5 / 2,6 MP) | 1 (≤ 2 / 5 MP) | 1,5 süper örnekleme (≤ 3 / 8,3 MP) |
| Kenar yumuşatma | kapalı | MSAA 4× | MSAA 4× | MSAA 8× (desteklenmezse 4×) |
| Gölge haritası / kapsam (± m) / tür | yok | 1024 / 70 / PCF | 2048 / 90 / PCF yumuşak | 4096 / 140 → kameraya göre 2,2×'e dek (yakın keskin + uzak geniş), arazi de gölge düşürür |
| Görüş / sis uzaklığı | 0,6× | 0,85× | 1× | 1,3× |
| Arazi ızgarası (prosedürel / ufuk / gerçek / uzak) | 192 / 64 / 192 / 128 | 256 / 96 / 256 / 160 | 320 / 128 / 256 / 192 | 448 / 192 / 384 / 256 |
| Ağaç yoğunluğu / 3B ağaç LOD | 0,35× / 300 m | 0,65× / 420 m | 1× / 520 m | 1,25× / 800 m |
| Anizotropik filtre / uydu atlası | 2× / 2048 | 4× / 4096 | 8× / 4096 | 16× / 8192 (MAX_TEXTURE_SIZE ≥ 8192) |
| Su / yağış parçacığı | basit / %35 | normal / %60 | normal / %100 | ayrıntılı / %100 |
| Son işlem | yok | yok | ACES + bloom 0,35 + SSAO (yarım çöz.) + vinyet + renk | ACES + bloom 0,45 + SSAO (tam, 16 örnek) + vinyet + renk |
| PiP / radar / EO / nişangâh çözünürlüğü, PiP hızı | 0,5× · 15 fps | 0,75× · 20 fps | 1× · 30 fps | 1,25× · 30 fps |
| Kare hızı sınırı | 30 | 60 | 60 | sınırsız (ekran yenilemesi) |
| Google 3B karo hata eşiği / önbellek | 28 px / 200 MB | 20 / 300 | 14 / 400 | 8 / 600 |
- **Özel**: tabanı o anki kademe olan ince ayar (`normCustom`: alan başına sınır/izinli değer — `GFX_LIMITS`, enumlar). `GFX_LEGACY` (opts.gfx
  verilmeyen çağıranlar: sihirbaz önizlemesi, stüdyo) = Yüksek, son işlemsiz → eski görüntü birebir.
- **Kalıcı tercih** `{preset, base, custom, dynRes, fpsCounter, fpsCap, bgThrottle, autoLevel}`: HEPGO `localStorage fs.gfx`, SIMUMAV `sm.gfx`.

### 43.2 Otomatik + uyarlamalı kip
- **İlk kademe** (`autoLevel(dev)`): GPU adı (`WEBGL_debug_renderer_info`, sahnenin kendi bağlamından — `sim.gfxCaps.gpu`), dpr, `hardwareConcurrency`,
  `deviceMemory`, mobil. Yazılım WebGL (SwiftShader/llvmpipe) → Düşük (üst sınır Düşük); zayıf tümleşik (Intel HD 5xx, eski Mali/Adreno) → Düşük; Iris
  Xe / Radeon Graphics / bilinmeyen → Orta; ayrık (GTX/RTX/RX/Arc/Apple M) → Yüksek; üst sınıf (RTX x070+, RX 6800+, M Pro/Max) + ≥ 8 çekirdek + 8 GB →
  Ultra; mobil en çok Orta (bellek ≤ 3 GB / ≤ 4 çekirdek → Düşük); dpr ≥ 2,5 tümleşik ekran bir kademe aşağı. Uyarlamalı kip en çok bir kademe yukarı
  çıkabilir (`max`). Kademe kalıcı tercihe `autoLevel` olarak yazılır (sonraki açılışta tuval antialias'ı ve ilk piksel oranı doğru).
- **Uyarlamalı** (`createAdaptive`, 0,5 sn'de bir `sim.gfxStats().fps`): FPS < 40 (kare sınırı 30 ise 24) **5 sn** sürerse önce ölçek 1 → 0,85 → 0,7,
  sonra bir kademe aşağı; FPS ≥ 57 (sınır 30 ise 28) **12 sn** sürerse ölçek geri, sonra bir kademe yukarı. Histerezis: her değişiklikten sonra 6 sn
  bekleme; inilen kademeye dönüş 30 sn kilitli, aynı kademeden tekrar inilirse kilit iki katı (≤ 10 dk) → titreme yok. Yeni ayarın ilk 4 sn'si ve
  pencere odakta değilken ölçülmez. Kullanıcı elle ön ayar seçince uyarlamalı kip kapanır. Otomatikte kare sınırı 60.
- **Dinamik çözünürlük** (ayrı kutu, `createDynRes`): her ön ayarda; ölçeği 0,05 adımla 0,5…1 arasında hedef FPS'e (50) yaklaştırır (çok düşükte
  çift adım). Açıkken uyarlamalı kip ölçek adımlarını atlar (yalnız kademe).

### 43.3 3B uygulaması (`flightsim3d.js setGraphics(params)` — canlı)
- **Piksel oranı** `pixelRatioFor` (ölçek × dpr, tavan, bütçe ≥ 0,5) her `resize`'da; **ekran kaydı** sürerken (`flightsim_record.js` durum →
  `sim.setRecordFloor(true)`) taban = kayıt hedefi 1280×720'yi karşılayan oran (dpr'yi aşmaz) → düşük ölçek kaydı bulanıklaştırmaz; kayıt sırasında
  arka plan kısması da yok. Kayıt birleşik tuvali (720p) değişmedi; kayıttan oynatma aynı ayarlarla çalışır (enterpolasyon gerçek zamanla).
- **Kenar yumuşatma**: tuval `antialias`'ı yalnız açılışta seçilebilir (bağlam özelliği): ön ayar MSAA ≤ 4× ve son işlem/FXAA yoksa yerel MSAA; değilse
  son işlem hattının WebGL2 çok örnekli hedefi (4×/8×). FXAA son geçişte. Açılışta yerel MSAA ile açılmış tuvalde "kapalı" seçimi yeniden açılışa dek
  yerel MSAA'yı kaldıramaz.
- **Son işlem hattı** (`createGfxPipeline`; EffectComposer yerel kopyada olmadığından kendi küçük hattımız, aynı renderer): sahne → HalfFloat HDR hedef
  (MSAA; SSAO'da derinlik dokusu) → SSAO (derinlikten görünüm uzayı konum + normal, spiral 8/16 örnek, 150–400 m arası söner, derinliğe duyarlı
  bulanıklaştırma) → bloom (parlak geçiş ½ + 3 mip Gauss) → son geçiş: AO × renk + bloom → ACES Filmic (koyu tonlarda doğrusal korunur: sahne ton
  eşlemesiz ayarlı, ACES "toe"su ağaçları siyaha yakın gösteriyordu) → renk derecelendirme (doygunluk/kontrast/sıcaklık) → vinyet → (FXAA) → sRGB.
  Yalnız dış gözlemci kiplerinde (takip/serbest/yer + gündüz gimbal); FPV balıkgözü ve termal/gece görüşü geçişi (§22.3) kendi hattında (örnek
  sayısı ön ayardan).
- **Gölge**: harita boyutu/tür değişince harita + malzemeler (`needsUpdate`) yeniden; kapsam `setShadowBox` (Ultra'da her kare kamera–odak uzaklığına
  göre ±140…±308 m; güneş uzaklığı kapsamla büyür); bina/ağaç gölge düşürme `objCast`, arazi `terrainCast` (`applyCast`, dünya her kurulduğunda).
- **Görüş/sis + yağış**: `skyAndLights` son argümanlarıyla yeniden (sis uzaklığı çarpanı, prosedürel ufuk halkası sınırı korunur; `precipParams`
  kalitesi). **Su**: `wfx.U.waterQ` (0 iki oktav, yağmur halkası yok · 1 üç oktav · 2 dört oktav + 3 km'ye dek dalga). **Anizotropi**: sahnedeki
  mipmapli dokular + zemin ayrıntı dokuları (render hedefi dokularına dokunulmaz). **Ağaç LOD** mesafesi `updateTreeLod(…, gfx.treeLod)`.
- **Arazi ayrıntısı / bitki yoğunluğu / doku çözünürlüğü** ızgara ve örnek sayısını değiştirir → dünya 700 ms sonra **sessizce** yeniden kurulur
  (`buildWorld(W, quiet)`: ilerleme/olay iletisi yok; aynı tohum → binalar/çarpışma kutuları aynı, ağaç sayısı değişir; görev çizimi ve §26 saha yeniden
  oturur; Google 3B'de yok). Gerçek arazide atlas boyutu değişirse karolar yeniden alınır (`realCache` anahtarında atlas).
- **PiP / radar / EO / nişangâh**: render hedefi çözünürlüğü × `pipScale`, PiP aralığı ≥ 1000/`pipFps`, radar/EO aralığı × (30 / pipFps).
- **Kare hızı sınırı** (`frameGate`, 30/60/sınırsız; sürüklenmesiz zamanlama) + **arka planda kısma** (pencere `blur` → 20 fps; `focus`'ta geri).
  Atlanan rAF turunda hiçbir şey yapılmaz; dt gerçek geçen süreden.
- **Google 3B** (`flightsim_g3d.js setQuality({errorTarget, cacheMB})`): karo hata eşiği (maximumScreenSpaceError eşleniği) + LRU önbellek; çözünürlük
  ölçeği `setResolutionFromRenderer` ile LOD'a doğrudan yansır; görüş mesafesi sis ufku çarpanıyla.
- **İstatistik**: `renderer.info.autoReset = false`, kare başında sıfırlanır → `gfxStats().calls/tris` karenin toplamı (PiP, radar, son işlem dahil;
  `fxInfo` da artık karenin toplamını verir). `gfxStats().fps` son 2 sn'nin kare aralığından (saniyede < 1 kare de ölçülür). `getGraphics()` uygulanan
  ayar + tampon boyutu + hat bilgisi; `gfxCaps` (maxSamples, maxAniso, maxTex, halfFloat, nativeAA, gpu).

### 43.4 Arayüz (`flightsim_gfx_ui.js`)
- **Alt bant**: Panel/ses kapsülünde (`.fs-ops-snd`) simge düğme `.fs-gfx-btn` (monitör simgesi + kademe harfi: D/O/Y/U, Otomatikte "A·O"; ayrıntı
  `title`'da) → yukarı açılan menü `.fs-gfx-menu`: ön ayar seçici (Otomatik/Düşük/Orta/Yüksek/Ultra/Özel), Otomatikte "şu an …" + ölçek, canlı FPS /
  çizim çağrısı / üçgen / tampon çözünürlüğü, kare hızı sınırı (30/60/Sınırsız), Dinamik çözünürlük, Köşede FPS sayacı (`.fs-gfx-fps`, üst orta;
  < 40 sarı, < 24 kırmızı), Arka planda kıs, "Ayrıntılı ayarlar (Özel)" kaydırıcıları (ölçek, AA, gölge, gölge mesafesi, görüş, arazi, bitki, doku
  filtresi, su, yağış, son işlem, bloom, SSAO, PiP çözünürlüğü/hızı, Google karo eşiği), "Ön ayara dön". Mobilde Yüksek/Ultra (ya da bu tabanlı Özel)
  seçilince pil/ısınma uyarısı. Kademe değişimleri olay şeridine ("Grafik: kare hızı düşük → Orta").
- **Sihirbaz**: HEPGO özet adımında (`summaryBox` altında) ve SIMUMAV son adımda ("Pilot ve kayıt", gösterge tasarımının altında) `createGfxPicker`
  — aynı kalıcı tercih. Metinler `GFX_TEXTS` (HEPGO Türkçe anahtar, 6 dil; SIMUMAV `gfx.*` 7 dil).

### 43.5 Testler ve görsel doğrulama
- `node tests/test_flightsim_gfx.mjs` (20 test): ön ayar → parametre (monotonluk, Yüksek = eski sabitler, yetenek kırpması), Özel normalleştirme,
  tercih (fs.gfx / sm.gfx), piksel oranı (bütçe, kayıt tabanı), kare sınırı kapısı, otomatik kademe kuralları (yazılım/zayıf/tümleşik/ayrık/üst
  sınıf/mobil/yüksek dpr), uyarlamalı histerezis (önce ölçek, bekleme, dönüş kilidi iki katı, titreşen FPS'te değişiklik yok, sınır 30), dinamik
  çözünürlük, metinler 6 + 7 dil, bağlama (tek renderer, oturum/sihirbaz/kayıt).
- Görsel: `./.venv/bin/python -m tests.gfx_shots_hepgo` → `/tmp/gfx-shots/hepgo-{drone,town}-{low,medium,high,ultra}.png`, `hepgo-menu*.png`,
  `hepgo-auto-counter.png` + yazılım WebGL göreli ölçüm tablosu; SIMUMAV `./.venv/bin/python -m tests.gfx_shots_simumav` → `sm-follow-*.png`,
  `sm-menu-tr.png`, `sm-wizard-picker.png`.
- Yazılım WebGL (SwiftShader, 1280×720, prosedürel dünya, kasaba bakışı) göreli ölçüm — mutlak FPS anlamsız, oranlar anlamlı:

  | Ön ayar | kare/sn | çizim çağrısı | üçgen | tampon | MSAA | son işlem | gölge |
  |---|---|---|---|---|---|---|---|
  | Düşük | 0,83 | 186 | 288 k | 960×460 @0,75 | — | — | yok |
  | Orta | 0,33 | 228 | 615 k | 1280×614 @1 | 4 | — | 1024 |
  | Yüksek | 0,33 | 242 | 962 k | 1280×614 @1 | 4 | SSAO ½ + bloom | 2048 |
  | Ultra | 0,17 | 251 | 2,22 M | 1920×921 @1,5 | 4 (yazılım GL azami 4) | SSAO tam + bloom | 4096 |
- **Sınırlar**: gerçek kademeli gölge haritası (CSM) yok — Ultra'da tek 4096 harita kamera uzaklığına göre büyüyen kapsamla (yakın + uzak);
  SMAA yok (MSAA 8× / FXAA); su yansıması düzlemsel yansıma değil (Fresnel gök yansıması, kalite oktav/mesafe); FPV balıkgözü ve termal/gece
  görüşünde son işlem (ACES/bloom/SSAO) uygulanmaz; bina sayısı oyun dünyasıdır (çarpışma) — yalnız ağaç yoğunluğu ölçeklenir; tuval antialias'ı
  açılışta sabittir.

## 44. Karşılaşmada YAPAY ZEKÂ PİLOT (bot oyuncu) + karşılaşma OYUN EFEKTLERİ (`app/flightsim_match_bot.py` + `flightsim_match_core.BOT_*`; ön yüz `static/js/modules/flightsim_sfx.js`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: karşılaşma kurulumunda "Yapay zekâ pilot ekle" (Kolay / Normal / Zor; isim + renk; halka yarışında birden çok bot, it dalaşında tek
rakip — kişi tek başına bota karşı oynayabilsin), bot gerçek oyuncu gibi KENDİ SITL'inde (aynı fizik) uçsun; ayrıca "kat edilen seviye ve alınan
puanlarda ses efekti çıksın". **Kapsam:** bot yalnız OYUN İÇİ rakip davranışıdır — "hedefe doğru yönel + seviye gecikmesi + dönüş oranı sınırı";
gerçek güdüm/önleme yasası (orantılı seyrüsefer vb.) KULLANILMAZ. §41'deki "araca güdüm/takip komutu yok" kuralı insan oyuncular içindir.

### 44.1 Seviye tablosu (TEK tablo: `flightsim_match_core.BOT_SEVIYE`; test `tests.test_flightsim_match_bot`)
| Alan | Kolay | Normal | Zor | Anlam |
|---|---|---|---|---|
| `hiz` | 0,55 | 0,75 | 0,95 | sınıf azamisine oran (dikey 16 m/s, uçak 30 m/s hava hızı; uçakta en az 15 m/s) |
| `gecikme_s` | 1,5 | 0,7 | 0,25 | tepki gecikmesi: halka geçişinden sonra eski yönde sürer; it dalaşında rakibi bu kadar eski görür |
| `donus_dps` | 45 | 75 | 120 | komut yönünün dönüş oranı sınırı (°/sn) — Kolay geniş döner |
| `sapma` / `iska` | 0,45 / 0,15 | 0,22 / 0,03 | 0,06 / 0 | halka merkezinden kaçıklık (yarıçapa oran) / ıskalama olasılığı (ilk denemede; sonra geri dönüp yeniden dener) |
| `giris_aci` | 30° | 40° | 50° | düz girişe geçiş konisi (uçakta ×0,6) |
| `on_donus` | — | — | ✓ | halkaya çok yaklaşınca sıradaki halkanın yaklaşma noktasına önceden döner (giriş açısı optimizasyonu) |
| `tahmin_hata_m` | 30 | 12 | 3 | it dalaşı: rakip konum tahmin hatası (yavaş değişen) |
| `onculuk` | 0,15 | 0,45 | 0,8 | kovalarken öngörü karışımı (0 = doğrudan rakibe, 1 = tahmini ileri konuma) |
| `manevra_s` / `manevra_aci` / `rastgele` | 7 / 45° / 0 | 4,5 / 70° / 0,5 | 2,8 / 95° / 1 | kaçış zikzakı aralığı / büyüklüğü / öngörülemezlik (Kolay hep sağ-sol-sağ) |
| `irtifa_oyunu` / `alan_esik` / `zemin_pay` | — / 0,9 / 0,75 | ✓ / 0,8 / 1 | ✓ / 0,72 / 1 | kaçarken irtifa değişimi / alan sınırına bu oranda içeri dönüş / güvenli irtifa çarpanı (dikey 8 m, uçak 35 m) |
Adlar `AI-Şahin, AI-Kartal, AI-Doğan, AI-Atmaca, AI-Kerkenez, AI-Albatros, AI-Akbaba` (HEPGO "AI-Şahin (Zor)"; SIMUMAV ad + 7 dilli rozet),
renkler `BOT_RENKLERI`. Sahte kinematikte ortalama süre (5 halka, 3 tohum): kopter Zor 90 sn < Normal 102 < Kolay 133; sabit kanat 136 < 166 < 231.

### 44.2 Çekirdek ve pilot
- `Karsilasma(..., botlar=[(uid<0, ad, seviye, renk)])`: bot "geldi" (hazır sayılır; davetli beklenmez); `bot_ekle(kurucu, seviye, now)` LOBI'de
  (oyuncu sınırı 8, it dalaşında rakip varsa 409), `cikar` LOBI'de botu listeden siler, `lobi_denetle` (yalnız botlarla kurulunca hemen HAZIRLIK).
  `insanlar()` boşalınca HAZIRLIK/GERI_SAYIM'da IPTAL, YARIS'ta BITTI `oyuncu_kalmadi` (it dalaşında insan ayrılırsa bot kazanır `rakip_ayrildi`).
  Oyuncu dict'inde `is_bot`, `level`, `color`. Kazanan bot olabilir (negatif kimlik).
- `BotPilot` (saf): `halka_adim(t, ben, halkalar, sıra)` — halkanın önündeki yaklaşma noktası (dikey 22 m; uçakta v²'yle uzar, dönüş yarıçapı içinde
  geriye kayar), yanal koni içindeyse halkadan düz geçiş; arkadaysa yandan dolaşır (ters yönde içinden geçmez); düzlemi sayılmadan geçerse yeni
  deneme. `it_adim(t, ben, rakip, rol, ayar)` — KOVALAYAN: gecikmeli + hatalı rakip görüşü, öngörü karışımı, yakında hızını rakibe uydurur;
  KAÇAN: rakipten uzaklaşan yön ± seviye manevrası, rakip menzile yaklaşınca usta kaçan düz kaçar, alan sınırında sınır boyunca kıvrılır. Her ikisi
  `_guvenli` ile alan sınırı içinde ve güvenli irtifanın üstünde hedef seçer. Çıktı `{vx, vy, vz (ENU m/s), hedef (x, y, z), hiz, yaw_deg}`.
- `BotSurucu` (asyncio, HEPGO + SIMUMAV): YARIS'a kadar bekler (komut kapısı); sonra kopterde GUIDED + ARM (EKF/GPS hazır olana dek yineler) +
  kalkış (halka yarışında ilk halkanın yüksekliği, it dalaşında `alt_m`; sabit kanatta kalkış dizisi), irtifaya varınca 5 Hz komut.
  `SimSession.bot_yonlendir`: kopter (ve sahte kinematik) `SET_POSITION_TARGET_LOCAL_NED` hız + yön (ArduCopter 3 sn yenilenmeyen hız komutunda
  durur), uçak ailesi GUIDED hedef noktası (`MISSION_ITEM_INT` current=2, göreli irtifa, en az 250 m ileri uzatılmış) + `DO_CHANGE_SPEED`.
  `bot_hazirla`: gerçek kopterde `WPNAV_SPEED` seviyenin hızına (cm/s) — GUIDED hız tavanı. Sahte kinematiğe `bot_hiz` (6 m/s² ivme sınırı).
- Bot oturumu: sahibi bot kimliği (`owner.id < 0`, `s.bot = {uid, level}`) → insanın REST/WS komutu 403 (`mac_yazabilir`); **uçuş kaydı
  (`drone_sim_runs`) yazılmaz**, `.bin` yok; karşılaşma SITL tavanına sayılır (HEPGO `SIM_MATCH_MAX_SESSIONS`, SIMUMAV `MAX_FLIGHTS` + `MAC_REZERV`).
  Karşılaşma bitince / insan ayrılınca sürücü durur, oturum `KAPANIS_GECIKME_S` sonra kapanır.

### 44.3 HEPGO
- `POST /api/drone/sim/matches {…, invite: [], bots: [{level}]}` — davet + bot ≥ 1, ≤ 7; it dalaşında toplam tam 1 rakip (400). Kapasite
  yetmezse 409 "… her yapay zekâ pilot da kendi simülatörünü kullanır (n bot)". Yalnız botlarla kurulursa davet bildirimi yok, hemen HAZIRLIK.
  `POST /{id}/bot {level}` (kurucu, LOBI; kapasite 409); bot çıkarma `/kick {user_id: <negatif>}`. Meta `limits.bot {levels, names, colors, default}`.
- **DB göçü (`app/db.py`, idempotent):** `drone_sim_matches.bots INTEGER NOT NULL DEFAULT 0` (PRAGMA denetimiyle ALTER). Oyuncu satırları
  `players` JSON'unda `is_bot`, `level`, `color`; bot kazanırsa `winner_id` NULL (users FK) — kazanan `result.winner`'da (negatif); GET/liste
  `winner` alanı sonuçtan.
- Arayüz (`flightsim_match_ui.js`): Davet et adımında "🤖 Yapay zekâ pilot ekle" kutusu (seviye Kolay/Normal/Zor + Ekle; çipler ✕; sayaç davet +
  bot; it dalaşında tek rakip), özet satırında bot adları; salonda bot satırı 🤖 + "AI · Zor" rozeti (çevrimiçi sayılır), kurucuya ✕ (onaysız) ve
  LOBI'de "Yapay zekâ pilot ekle" satırı; 3B'de botlar diğer oyuncular gibi (kendi renkleri, "AI-…" etiketi); sonuç tablosunda AI rozeti.

### 44.4 SIMUMAV
- Salonda kurucu boş yerde "🤖 Kolay / Normal / Zor" ile bot ekler (`POST /api/match/{id}/bot`), ✕ ile kaldırır (yasak listesine girmez). BAŞLAT'ta
  botlar da yuva sayılır (429 mesajında "(n yapay zekâ pilot dahil)"). Bot oturumu `bridge.bot_ucusu_ac` (kurucunun dronu/parkuru/parametreleri;
  flights satırı ve MP köprüsü yok).
- **"Yapay zekâya karşı"** (Uç › Çok oyunculu altında): `#/fly/ai` sihirbazı Dron → Parkur → (Kalkış) → Tür ve kurallar → **Yapay zekâ** (seviye,
  rakip sayısı; it dalaşında rol "Roller" seçiminden) → BAŞLAT → `POST /api/match/ai {…, level, bots}` (rastgele şifre, botlar, hemen BAŞLAT) →
  salon → yarış ekranı.
- **DB v5 (idempotent):** `match_players` yeniden kurulur — `user_id`'deki users FK'si kalkar (bot kimlikleri negatif), `is_bot`, `level` eklenir,
  satırlar taşınır, kullanıcı silme temizliği `tr_match_players_user_sil` tetikleyicisiyle. `matches.winner_id` bot kimliği olabilir.

### 44.5 Oyun efektleri (`flightsim_sfx.js`; Web Audio sentezi, ses dosyası/lisans yok)
| Olay | Ses | Nerede |
|---|---|---|
| halka geçişi | yükselen "ding" (C5'ten sıra arttıkça tam ton, ≤ 2 oktav) | kendi halkam |
| son halka / bitiş | fanfar (C5-E5-G5-C6) | kendi son halkam |
| sıralama değişimi | öne geçince whoosh + ding, geride kalınca alçak ton (≥ 1,2 sn aralık) | halka olaylarında canlı sıra |
| ters yön | testere kayması | `wrong_way` |
| angajman | kovalayan koni içindeyken dolum oranıyla yükselen, sıklaşan ton | it dalaşı HUD'u (`createDogfightHud({sfx})`) |
| zafer / yenilgi | jingle / alçalan dört nota | sonuç ekranı |
| puan | sonuç ekranında "Puanınız" sayacı tıklamalarla artar, sonunda "coin"; §24 önleme ve §40 angajman başarısında "coin"; §42 rapor kartında disiplin puanı sayacı | |
Geri sayım 3‑2‑1‑BAŞLA bipleri mevcut §29 giriş sekansıdır (birleştirildi; ikinci kez çalınmaz). Puan (gösterim): halka yarışı halka başına 100,
bitirene 250 + sıra bonusu (150/100/50); it dalaşı kazanana 1000 + kovalayanın en uzun tutması × 100 (≤ 500).
- Ses yolu: motor sesinin master kazancı (`audio.alertBus` bağlamı) → ses kapsülü 🔊/🔇 + düzey, gizli sekme, hızlı oynatma susturmaları ve ekran
  kaydı kapsanır; salonda/raporda yedek bağlam (`fs.audio.*`). **Uçuş uyarıları önceliklidir:** §42 uyarısı çalarken önemsiz efektler (angajman
  tonu, tıklama, sıralama, sayım) hiç çalmaz, diğerleri ×0,3. simfocus yalnız sistem seslerini bastırır (oyun efektleri sahnenin parçası).
- Ayar: ses kapsülü menüsünde "Oyun efektleri [Efekt kapalı | Efekt açık] + düzey" (HEPGO `fs.sfx`, SIMUMAV `sm.sfx`; varsayılan açık / 80).

### 44.6 Testler ve görsel doğrulama
- `.venv/bin/python -m tests.test_flightsim_match_bot` (saf): seviye tablosu tekdüzeliği, ad/renk, halka hedefi (yaklaşma → geçiş, arkadan
  dolaşma, Zor önceden dönüş, kaçıklık sıralaması, ıskalama + yeniden deneme, tepki gecikmesi), kovala/kaç (öngörü, gecikme, uzaklaşma, Kolay
  düzeni, alan + zemin), Karsilasma botları (ekle/çıkar, sınırlar, insan ayrılınca bitiş, it dalaşında bot kazanır), SAHTE KİNEMATİKLE yarış
  (kopter + uçak, Zor < Normal < Kolay) ve it dalaşı (kovalayan Zor daha hızlı angaje eder; kaçan alanda ve yerden yüksekte kalır).
- `tests.test_flightsim_match` `bot_api`: doğrulama 400'leri, kapasite 409, yalnız bot → HAZIRLIK, bot oturumuna insan komutu 403, BOT KAZANIR
  (winner_id NULL, players.is_bot, bot uçuş kaydı yok), İNSAN KAZANIR, it dalaşında kovalayan bot angaje eder, salonda bot ekle/çıkar.
- `tests.test_simumav_match` `yapay_zeka`: salonda ekle/çıkar/dolu, 429 mesajı, hızlı başlat (bot uçuşu yok), bot kazanır (DB is_bot/level,
  geçmişte kazanan adı), insan kazanır; v4 → v5 göçü (satırlar korunur, FK kalktı).
- `node tests/test_flightsim_sfx.mjs`: plan/perde/sıra/sayaç, tercih ve kazanç (uyarı önceliği), sahte Web Audio ile çalma, bot yardımcıları
  (ad, rozet, renk, rakip doğrulaması, sıra, puan, çekirdek sabitleriyle aynı), SIMUMAV `#/fly/ai` + `aiBody`, metinler HEPGO 6 + SIMUMAV 7 dil.
- **Gerçek SITL**: `.venv/bin/python -m tests.match_bot_sitl` — kurucu + Zor kopter botu (ArduCopter SITL): bot GUIDED + ARM (EKF hazır olana
  dek ~35 sn yineler) + kalkış, 3 halkanın üçünü de geçti (55 / 73 / 98 sn) ve kazandı; SITL süreçleri PID ile denetlenir.
- Görsel: `./.venv/bin/python -m tests.aibot_shots_hepgo` ve `tests.simumav_aibot_shots` → `/tmp/aibot-shots/{hepgo,sm}-*.png`.
- **Sınırlar**: uçak/VTOL/INTERCEPTOR botu gerçek SITL'de GUIDED hedef noktasıyla uçar (dönüş oranı ArduPlane'in L1'i belirler; seviye farkı hız,
  kaçıklık ve gecikmeyle) — gerçek SITL doğrulaması kopterle yapıldı; VTOL kalkışı genel `takeoff` yolundadır. Bot çarpışma kaçınması yalnız zemin
  (güvenli irtifa) ve alan sınırıdır — binalar/arazi engeli gözetilmez. Kolay ara sıra alan sınırını zorlayabilir. Puan gösterim içindir (DB'de yok).

## 45. UÇUŞ YIĞINI (otopilot) seçimi — ArduPilot · PX4 SIH (`app/flightsim_px4.py` + `static/js/modules/ucus_yigini.js`; **YALNIZ HEPGO**)

Sihirbazın Araç adımında "Uçuş yığını": dron SITL olarak hangi uçuş yazılımıyla uçacak. Varsayılan **ArduPilot** (mevcut çekirdek, değişmez).
**SIMUMAV'da görünmez**: `meta.stacks` yalnız HEPGO `/api/drone/sim/meta`'da; `ucus_yigini.js` `tools/simumav_export.py` `JS_DISLANAN`'da;
`flightsim.py` `flightsim_px4`'ü `importlib` ile yalnız `stack` verilince yükler (göreli import zincirine girmez; SIMUMAV köprüsü yığın geçmez →
çekirdek ArduPilot yolunda birebir aynı çalışır). Testler: `tests/test_flightsim_px4.py` (birim + dışa aktarım), `tests/test_ucus_yigini.mjs`,
`tests/test_flightsim_px4_sitl.py` (gerçek PX4 SIH uçtan uca), görseller `tests/stacks_shots_hepgo.py` → `/tmp/stacks-shots`.

### 45.1 Fizibilite

| Yığın | RTOS / lisans | SITL / fizik | MAVLink / HEPGO köprüsü | Derleme | Karar |
|---|---|---|---|---|---|
| **ArduPilot** | ChibiOS · GPLv3 | Yerleşik SITL fiziği (copter/plane/rover/heli/quadplane) | Tam (MP) | Hazır ikili 4.7.2 (+HEPGO yamaları) | **Varsayılan** |
| **PX4** | NuttX · BSD-3 | **SIH** (Simulation-In-Hardware, Gazebo'suz; quad X, sabit kanat, tailsitter, standart VTOL) | Tam MAVLink (UDP); QGC önerilir, MP bağlanır | `make px4_sitl_default` (cmake+ninja, ~10 dk, 4,9 MB strip) | **Entegre** |
| INAV | bare-metal STM32 · GPLv3 | SITL var ama fizik **yok**: X-Plane / RealFlight köprüsü ister | Yalnız telemetri; komut/görev kısıtlı, yapılandırma MSP | make SITL | **Planlandı** (HEPGO fiziğiyle X-Plane UDP köprüsü gerekir) |
| Betaflight | bare-metal STM32 · GPLv3 | SITL yalnız Gazebo/RealFlight köprüsüyle | MSP; MAVLink tek yönlü telemetri; GPS seyrüseferi/görev/otomatik kip yok | make SITL | **Uygun değil** (görev/RTL akışlarına uymaz) |
| Paparazzi | ChibiOS · GPLv2+ | NPS (JSBSim/OCaml araç zinciri) | Ivy bus + PPRZLINK; MAVLink ek modülle kısmi | Ağır (OCaml, JSBSim) | **Planlandı** |
| Rotorflight | bare-metal STM32 · GPLv3 | Betaflight türevi; bakımı yapılan SITL ve helikopter fiziği yok | MSP | — | **Uygun değil** |

Lisans etkisi: tüm yığınlar **ayrı süreç** olarak çalıştırılır (bağlama/link yok) → HEPGO koduna copyleft yayılmaz. GPL ikilileri üçüncü kişilere
dağıtılırsa kaynak sunma yükümlülüğü (ArduPilot zaten böyle); PX4 BSD-3 yalnız lisans/telif bildirimini korumayı ister (`data/sitl/px4/LICENSE`).

### 45.2 PX4 SITL süreci (`flightsim_px4.baslat`)

- Kurulum: `HEPGO_PX4_DIR` > `<SITL klasörü>/px4` (PROD `data/sitl/px4`) > SITL klasörünün kardeşi (DEV `HEPGO_SITL_DIR=/opt/hepgo/sitl/bin` → `/opt/hepgo/sitl/px4`).
  İçerik: `bin/px4` (+ `px4-*` sembolik bağlar, `px4-alias.sh`), `etc/` (ROMFS), `LICENSE`, `VERSION`, `SOURCE.txt`, `px4.sha256`.
- Komut: `bin/px4 -d -i <örnek> <kurulum>/etc`, çalışma dizini `sitl_calisma/<kimlik>/px4` (parameters.bson, dataman, log/*.ulg, px4.log).
- Örnek 70…99 (`/tmp/px4_lock-<i>` kilidi boş olan ilki; başka oturumların 0…69 örneklerine dokunulmaz); MAVLink yerel portu 18600+(i−70).
- **Tuzak P1 (14550 sızıntısı)**: PX4'ün GCS bağlantısı eş gelmeden 127.0.0.1:14550'ye yollar = HEPGO'nun ilk oturum UDP portu. Örnek dizinindeki
  `hepgo/px4-rc.mavlink` PATH'te PX4'ün kendisinden önce bulunur; yalnız GCS bağlantısını, partneri baştan HEPGO'nun yerel UDP soketi olarak açar
  (`-t 127.0.0.1 -o <port>`); offboard/kamera/gimbal/SIH görüntü bağlantıları açılmaz. Ölçüldü: 14550'ye tek paket gitmiyor.
- **Tuzak P2 (sysid)**: rcS `MAV_SYS_ID = örnek+1` yazar, commander bunu yalnız başlarken okur → `hepgo/px4-rc.simulator` commander'dan önce
  `MAV_SYS_ID 1` yapar, sonra PX4'ün kendi simülatör betiğini çağırır. MP/QGC her zaman sysid 1 görür.
- Ev: `PX4_HOME_LAT/LON/ALT` (SIH_LOC_*; ev irtifası §9 kuralıyla araziden). Airframe: `PX4_SYS_AUTOSTART` (10040 quad X · 10041 sabit kanat ·
  10043 standart VTOL · 10042 tailsitter). Hız: `PX4_SIM_SPEED_FACTOR` (0,5/1/2/4; **yalnız açılışta**).
- Parametreler: `PX4_PARAM_<AD>=<değer>` (rcS, airframe'den önce): HEPGO tabanı `COM_RC_IN_MODE 1, NAV_RCL_ACT 0, COM_RCL_EXCEPT 7, NAV_DLL_ACT 0,
  COM_ARM_WO_GPS 0, MAV_PROTO_VER 2, SDLOG_MODE 0|-1` (ULog yalnız "Uçuş logunu kaydet" açıkken), üstüne yüklenen dosya. NAV_RCL_ACT 0: sanal kumanda
  kapanınca "kumanda kaybı" failsafe'i (Hold → RTL) tetiklenmesin (ölçüldü).
- Temiz başlangıç (ArduPilot `temiz=True` eşleniği): parameters.bson, parameters_backup.bson, dataman, log/ silinir; "Sıfırla" korur.
- Süreç `drone_sitl.YONETICI.surec_kaydet` ile ortak yöneticide: `calisiyor_mu`, `durdur` (SIGTERM → 5 sn → KILL), `artiklari_temizle` (cwd kökte).
- Oturum bağlantısı UDP (`udp_akisi`: SimSession'ın TCP okuyucu/yazıcı arayüzü) → GCS köprüsü (UDP 14550+), 3B, HUD, harekât paneli aynı yoldan.

### 45.3 Oturum katmanı (`Px4Session(SimSession)`) — PX4'te çalışan / çalışmayan

Çalışan: telemetri (ATTITUDE, GLOBAL_POSITION_INT, VFR_HUD, SYS_STATUS, GPS_RAW_INT, SERVO_OUTPUT_RAW, HOME_POSITION; SET_MESSAGE_INTERVAL 50 Hz) ·
GCS köprüsü (QGC önerisi panelde "QGROUNDCONTROL / MP") · ARM/DISARM (ön uçuş denetimli, zorla değil) · kalkış (ARM, EKF hazır olana dek ≤ 25 sn
yinelenir → `MAV_CMD_NAV_TAKEOFF` param7 **AMSL** = ev + irtifa; VTOL `NAV_VTOL_TAKEOFF` 84; sabit kanat pist kalkışı RWTO) · RTL (`NAV_RETURN_TO_LAUNCH`,
kopter/VTOL iniş + disarm) · kipler (`DO_SET_MODE` base 1, main/sub; HEARTBEAT custom_mode → `AUTO.LOITER` vb.; ArduPilot adları takma ad olarak:
GUIDED/LOITER → AUTO.LOITER, AUTO → AUTO.MISSION, RTL → AUTO.RTL, LAND → AUTO.LAND, ALT_HOLD → ALTCTL, POSHOLD → POSCTL, STABILIZE → STABILIZED) ·
sanal kumanda (`MANUAL_CONTROL`: x = −(ch2−1500)·2, y = (ch1−1500)·2, z = ch3−1000, r = (ch4−1500)·2; 8×0 → gönderilmez) · harekât paneli
(Px4MavKomut: kip, kalkış, iniş 21, RTL 20, goto DO_REPOSITION AMSL, görev yükleme ev öğesiz) · parametre dosyası · yakıt/batarya göstergesi ·
hedefler · uçuş uyarıları (PX4 kip adları GPWS'te iniş/RTL sayılır) · PX4 bayt düzeyi tamsayı parametreleri çözülür (`param_coz/param_kodla`) ·
parçalı STATUSTEXT tek satır.

Çalışmayan (arayüzde gri + gerekçe, komutlar 400 "PX4'te desteklenmiyor: …"): uçuşta simülasyon hızı (yalnız açılışta), rüzgâr fiziği (SIH v1.16'da
rüzgâr parametresi yok; yalnız görsel/HUD), motor kesme (MOTOR_ESTOP ArduPilot'a özgü; uçuş çubuğu PX4'te havada onaylı DISARM), servo tetik
(DO_SET_SERVO), rampa/araç/fırlatıcı kalkışları (yalnız pist), arazi sunumu (TERRAIN_DATA), `.bin` → Uçuş Logları (PX4 ULog `.ulg` örnek dizinine
yazılır; kapanışta yol olay şeridinde — **Uçuş Logları'na .ulg yükleme henüz yok**), dron kaydının kalıcı (ArduPilot) parametreleri, kontrol düzeni,
"Yer kontrolünü koru" ve karşılaşma (§33).

### 45.4 REST / sihirbaz

- `POST /api/drone/sim/sessions` ek alanlar: `stack` (`ardupilot` | `px4`), `stack_cfg` `{airframe?, speed?, params_text?, params_name?}`.
  Hatalar: planlanan/uygun olmayan yığın, PX4'te desteklenmeyen tip (heli/hexa/rover/INTERCEPTOR), yanlış airframe, hız → 400; PX4 kurulumu yok → 503.
- Parametre dosyası: QGC `.params` (`sysid⇥compid⇥AD⇥değer⇥tip`), ArduPilot `.parm` (`AD değer` / `AD,değer`), `AD=değer`; # ve // yorum; ≤ 512 KB,
  ≤ 3000 parametre. ArduPilot'ta `varsayilan.parm` sonuna (aynı adda dron kaydının kalıcı değeri önceliklidir — §13.1 kuralı), PX4'te `PX4_PARAM_*`.
- Oturum `to_dict`: `stack: 'px4'`, `stack_info` (airframe, hız, yüklenen parametre sayısı, özellik listesi, ULog), `modes` (uçuş çubuğu listesi).
- Kayıtlı simülasyonlar (§27) `stack`/`stack_cfg`'yi saklar. Sihirbaz: PX4'te kalkış adımı yalnız pist, kontrol düzeni gizli; özet satırı "Uçuş yığını".

### 45.5 Görsel ve test

`tests/stacks_shots_hepgo.py` (gerçek PX4): 01 yığın kartları · 02 PX4 kopter yapılandırması · 03 helikopter uyarısı · 04 VTOL airframe ·
05 özet · 06 PX4 ile uçuş · 07 PX4 kip listesi. `tests/test_flightsim_px4_sitl.py`: kopter/sabit kanat/VTOL — HAZIR, GCS taklidi UDP heartbeat ↔
PX4 HEARTBEAT (autopilot 12), ARM+kalkış, tele alanları, takma ad kip, desteklenmeyen komut 400, RTL (iniş+disarm), Sıfırla, kapanış.

### 45.6 PROD kurulumu (kullanıcı onayıyla)

DEV'de derlenen kurulum `/opt/hepgo/sitl/px4` (5,6 MB: bin 4,9 MB strip + etc 0,8 MB). PROD'da SITL klasörü `data/sitl` olduğundan hedef
`/opt/hepgo/caymazbuild/data/sitl/px4`:
1. `tar -C /opt/hepgo/sitl -czf /tmp/px4-sitl-v1.16.2.tgz px4` (sembolik bağlar korunur) → PROD'a kopyala, `sha256sum` karşılaştır.
2. PROD: `tar -C /opt/hepgo/caymazbuild/data/sitl -xzf …` · sahiplik servis kullanıcısı (`--chown` kök dizine UYGULANMAZ; yalnız `px4/` alt ağacı).
3. Bağımlılık yalnız glibc/libstdc++ (Ubuntu 24.04 derlemesi; PROD aynı sürüm olmalı) — `data/sitl/px4/bin/px4 -h` ile denetle.
4. Kod dağıtımı (`app/flightsim_px4.py` vd.) + servis yeniden başlatma; `/api/drone/sim/meta` `stacks[px4].available = true`.

## 46. Sahnede YER PİLOTU — RC kumandalı tam boy figür + "Pilot gözü" (`static/js/modules/flightsim_pilot.js`; HEPGO + SIMUMAV ortak, varsayılan KAPALI)
- `createFlightSim3D(…, {pilot: {look, build?}})` ya da `sim.setPilot(look | null, build?)`; HEPGO oturumu açmaz (SIMUMAV açar: docs/simumav.md §28).
  `build(T, look, {lod})` enjekte edilir (sözleşme modül başında; verilmezse `buildSimplePilot` — basit kasklı figür). Kemikler: torso / head / stickL / stickR.
- Ev = ilk telemetrideki araç konumu (karşılaşmada oyuncunun kendi kalkış noktası), yön = aracın yönü (telemetri yoksa pist); `placePilot` 8 m geride + 3 m
  solda, eve dönük; disarm + yerde + > 25 m sıçramada yeniden demirlenir. Diğer pilotlar: `sim.setPilots([{id, look, home | x/y, yaw, target}], build?)`.
- Kare başına (`pilotFrame`): bakış (gövde %35 ±34°, baş ±63°, ±60°'yi aşınca ayaklar 0,6 rad/s döner; yunuslama −20…+69°), nefes (4 sn), ağırlık
  aktarma (7 sn), çubuklar (`setPilotSticks` 400 ms taze; yoksa `tele.rc` → `sticksFromRc`, Mod 2), yüzey yüksekliği 1 Hz (Google 3B).
- Grafik (§43): Düşük → `lod: low` + gölgesiz; diğerlerinde `mid` + gölge al/düşür. Termal: ılık (heatRoots). Aynı çizici/sahne (ek bağlam yok).
- Kamera: `setCamera('pilot_eye')` → Yer kipi + `groundView: 'pilot'` (omuz üstü `shoulderCam`, teleobjektif FOV); tuş 6 ya da Yer'de tekrar 5;
  `onCameraChange(mode, {groundView})`; `CAMERA_MODES` değişmedi (HEPGO 1–5). Teşhis: `sim.pilotInfo()`, `sim.getGroundView()`.
- `flightsim_match3d.ghostPos(id)`: hayalet aracın konumu (karşılaşmada diğer pilotların bakışı). Test: `node tests/test_flightsim_pilot.mjs`.

## 47. HAZIR FPV PARKURLARI + FPV PARKUR YARIŞI + TEK KİŞİLİK KARŞILAŞMA (zaman denemesi, hayalet) (`app/flightsim_fpv.py`; HEPGO + SIMUMAV ortak)
Kullanıcı isteği: "FPV için hazır parkurlar ve karşılaşmalar + karşılaşmalarda tek kişilik oynama". Farklı mekanlarda kodla üretilen 3B sahne +
parkur tanımı (kapı/engel sırası, konum, yön, boyut; başlangıç/bitiş; tur; zorluk), tek kişilik zaman denemesi (tur/sektör süreleri, en iyi tur,
kaçırılan kapı cezası, kişisel rekor, HAYALET), parkur başına skor tablosu, çok oyunculu "FPV parkur yarışı" (+ yapay zekâ pilot), mevcut
karşılaşmaların tek oyuncuyla başlatılabilmesi. Kullanıcının paylaştığı referanslar (sivil FPV simülatörleri; Liftoff / Uncrashed / FPV Logic
tarzı): rafineri boru koridorları, çayır tepesinde ahşap ev iskeleti (pencere/kapı boşluklarında neon kapılar, sıradaki yeşil, sonrakiler
pembe/mor, başlangıçta yerde parlayan halka, altta iki çubuk-konumu göstergesi), yarım kalmış beton bina (kat kat pencere geçişi, sıradaki kapıya
ince yönlendirme çizgisi). **KAPSAM:** yalnız spor/yarış ve beceri parkuru — hedefe dalış/çarpma, araç/insan/yapı hedefi vurma ya da "patlayıcı /
kamikaze" eğitim senaryosu YOKTUR (eklenmedi).

### 47.1 Parkurlar (kodla üretilir, deterministik; `PARKURLAR` → `parkur(cid)`)
| id | Ad | Mekan | Zorluk | Tur | Bir tur (m) | Kapı | Öne çıkan |
|---|---|---|---|---|---|---|---|
| `hangar` | Kapalı Hangar | kapalı depo/hangar 60×36 m, tavan 9 m | 2 Orta | 3 | 171,5 | 9 | raf sıraları, tavan makasları, alçak kanal borusu altından geçiş, bölme duvarında kapı aralığı (pencere kapı), iki katlı merdiven kapı |
| `forest` | Çam Ormanı | orman | 3 Zor | 2 | 297,0 | 9 | ~190 ağaç (yarış hattından ≥ 4,8 m), devrik gövde (dal) altından geçiş, açıklıkta bayrak dönüşü |
| `city` | Yarı Yıkık Şehir | şehir / yarı yıkık yapılar | 4 Çok zor | 2 | 229,2 | 9 | binanın batı penceresinden girip doğu penceresinden çıkış, sokak aralığı, yaya köprüsü altı, bayrak |
| `stadium` | Gece Stadyumu | stadyum | 2 Orta | 3 | 298,8 | 13 | klasik kapılar, tünel (8 m, şişme), bayraklar, dalış kapısı (7 m iskele), merdiven kapı, 4 slalom direği |
| `refinery` | Rafineri | endüstriyel tesis | 4 Çok zor | 2 | 314,3 | 10 | boru köprüsü altından alçak geçiş (iki yönde), sarı korkuluklu ızgara yürüyüş yolu, tanklar, konteyner koridoru, 42 m baca etrafında tam tur |
| `canyon` | Kanyon Geçidi | kanyon / dağ geçidi | 5 Uzman | 1 | 293,9 | 9 | iki paralel dar vadi, kaya kemeri, dar boğaz, şelale perdesinin arkasından geçiş |
| `woodframe` | Tepedeki Ahşap Ev İskeleti | çayır tepesi (sis + dağ manzarası) | 3 Zor | 3 | 135,7 | 9 | ön kapıdan içeri, pencerelerden dışarı, üst kat penceresinden içeri/dışarı — neon kapılar yapının boşluklarında |
| `concrete` | Yarım Beton Bina | inşaat alanı | 4 Çok zor | 2 | 177,7 | 10 | kolon ızgarası, zemin/2./3. kat pencereleri, merdiven boşluğundan aşağı DALIŞ, küçük pencereden çıkış |
Engel/kapı türleri: kapı (`gate` kare/dikdörtgen, `circle` daire), `window` (yapı boşluğu; neon çerçeve boşluğa oturur), `dive` (YATAY, yukarıdan
aşağı), `ladder` (üst üste, ters yönlerde), `tunnel` (kontrol noktası tünel ortası), `flag` (direğin belirtilen yanından — `side` — dönüş),
`slalom` (sırayla sağ/sol), `start` (başlangıç/bitiş). Tanım (JSON-uyumlu sözlük): `{id, venue, name, difficulty, laps, par_lap_s, bot_vmax,
start{x, y, yaw, cols, gap}, env{time, fog, sky, ground, light, size, ceiling?, canyon?, hill?}, gates[{kind, x, y, z (ZEMİNDEN), yaw (geçiş yönü),
w, h | r, frame, sector_end, via?, via_lap?, side?, pole?, label?, a?}], obstacles[ilkel], decor[ilkel], line, length_m, gate_count, sectors}`.
Koordinatlar karşılaşma merkezine göre yerel ENU (x doğu, y kuzey). İlkeller: `box` (taban z, w sağ ekseni, d ileri ekseni, yaw; `holes` +
`axis` 'y' → kutu boyunca açık pencere/kapı/tünel/raf aralığı, 'z' → döşeme boşluğu), `cyl`, `sph`, `pipe` (kapsül), `torus` (daire kapı
çerçevesi). Çerçeveli kapıların çerçeve + ayakları `kapi_engelleri` ile `vis: false` çarpışma ilkeli olarak eklenir (görseli istemci neon çizer).
Varlıklar tamamen prosedüreldir (dış model/doku yok).

### 47.2 Geçiş, tur/sektör, ceza, çarpışma (`ParkurIzleyici`)
- **Kontrol noktaları** `kontrol_noktalari(cfg, merkez)`: `[S/F] + (kapı 1…m−1 + S/F) × tur` (S/F ilk geçişi = "holeshot", tur 0); her biri §33 halka
  alanlarıyla uyumlu (`i, x, y, alt_msl, lat, lon, yaw_deg, nx, ny, radius_m`) + `gate, lap, sector, sector_end, kind, z, nz, w, h, shape, line`.
  Karşılaşmanın `rings` alanı budur (eski istemciler halka gibi görür).
- **Geçiş**: ardışık iki konum kapı düzlemini −→+ (geçiş yönünde) keser ve kesişim noktası açıklık içindeyse (dikdörtgen |u| ≤ w/2, |v| ≤ h/2; daire
  √(u²+v²) ≤ r; dalış kapısında düzlem yatay, normal (0, 0, −1)); ters yön → `wrong_way`; tek adımda > 250 m sıçrama yok sayılır.
- **Kaçırılan kapı**: sıradaki kapıdan en çok 2 (`ILERI_BAKIS`) ilerideki kapı geçilirse aradakiler `miss` (+ `miss_penalty_s`, varsayılan 3 sn).
- **Tur / sektör**: S/F her geçişte tur süresi (`lap {lap, s, best}`); sektör sınırı `sector_end` kapıları + S/F (`sector {lap, sector, s, best}`);
  en iyi tur / sektör izlenir; ara süreler (`splits`, kontrol noktası başına t − t0) hayalet farkı için.
- **Çarpışma** (§18 çarpışma kuralının parkur ayarı): dron yarıçapı 0,25 m şişirilmiş ilkellerle doğru parçası örneklemesi (0,35 m) + ızgara kaba
  eleme; temas başlangıcı sayılır (aynı temas ve 1 sn içinde yeni sayım yok). Kural (`crash_rule`): **`penalty`** (varsayılan; + `crash_penalty_s`,
  varsayılan 2 sn, araç devam eder) · **`reset`** (sunucu oyuncu oturumuna Sıfırla → başlangıca döner, ilerleme korunur — halka yarışındaki gibi; süre
  işlemeye devam eder) · **`continue`** (yalnız sayılır). SITL engelleri bilmez; çarpışma sunucu çekirdeğinde (oyun kuralı) hesaplanır.
- Toplam süre = son S/F − yarış başlangıcı + ceza; sıralama ceza dahil süreyle. Hayalet örnekleri 10 Hz (`t, x, y, z, yaw, roll, pitch`).

### 47.3 Yarış hattı, doğrulama, yapay zekâ pilot
- `yaris_hatti(c)`: her kapı için önceki kapının çıkışı → `via` ara noktaları → giriş (normal boyunca 3 m önce; tünelde `a`) → merkez → çıkış (dalışta
  yukarıdan girer, aşağıdan çıkar). Bir tur uzunluğu = `length_m`.
- `parkur_dogrula(c)` (testlerde 8 parkurun hepsi boş liste döndürür): her kapı açıklığı engelsiz (içten 0,3 m pay, düzlemin ±0,4 m'sinde 3×3×3 örnek),
  yarış hattı tüm engellerden ≥ 0,45 m (dron yarıçapı dahil) ve zeminden ≥ 0,8 m, ilk kapı başlangıç/bitiş, 8 başlangıç noktası engelsiz; ayrıca kapı
  merkezleri başka kapı çerçevesinin içinde değil.
- **Bot** (`BotPilot.parkur_adim`): sıradaki kontrol noktasının `line` parçasında en yakın izdüşümden L = 2,5 + 0,35·v m ileri bakış noktasına 3B hız
  komutu (`_komut3`: yatay dönüş oranı seviye × 2,5, dikey ±3,5/3 m/s); hız = parkurun `bot_vmax` × seviye oranı (Kolay 0,58, Normal 0,79, Zor 1,0),
  öngörülü dönüş sınırı v ≤ √(ivme·R) (R = L / 2 sin(θ/2), θ: L ve 2L ilerideki doğrultu farkı; ivme sahte 6, gerçek ArduCopter GUIDED 3 m/s²),
  kapıya 6 m'den yakında %80; kapı merkezinden seviye kaçıklığı (açıklığın yarısı × sapma × 0,45). Kapının düzlemini açıklığın yakınından sayılmadan
  geçerse (ya da hattın sonunu aşarsa) eksendeki çıkış noktasına, oradan girişe döner ve yeniden dener. Kalkış irtifası = başlangıç kapısının yüksekliği;
  sahte kinematikte kalkış sırasında yerinde tırmanma hız komutu (sahte aracın "havada daire" davranışı alçak irtifada devreye girmesin; gerçek
  ArduCopter'a gönderilmez — yerdeyken hız hedefi GUIDED kalkışını iptal eder). Sahte kinematikte (6 m/s² ivme) 8 parkurun hepsinde üç seviye de hiç
  kapı kaçırmadan, çarpmadan bitirir; Zor < Normal < Kolay (`tests.test_flightsim_fpvcourse`, sn): hangar 89,3 / 110,4 / 150,8 · orman 84,5 / 104,4 /
  140,5 · şehir 69,9 / 85,8 / 115,4 · stadyum 123,6 / 147,3 / 194,7 · rafineri 89,1 / 107,8 / 143,9 · kanyon 39,2 / 48,0 / 64,3 · ahşap ev 76,1 /
  92,7 / 127,7 · beton bina 66,7 / 80,8 / 110,9.
- **Gerçek SITL** (`.venv/bin/python -m tests.fpvcourse_sitl`, ≈ 100 sn): kurucu + Zor kopter botu (ArduCopter SITL), stadyum, 1 tur, çarpma kuralı
  `continue`: bot GUIDED + ARM (EKF hazır olana dek ~30 sn yineler) + 2,4 m kalkış, S/F → kapı → TÜNEL (2 temas, geçti) → bayrak → DALIŞ kapısı →
  merdiven kapı: 6 kontrol noktası sırayla geçildi, kaçırma yok (betik ≥ 3 ister; sonra iptal eder). SITL süreçleri PID ile denetlenir.

### 47.4 Karşılaşma çekirdeği (`flightsim_match_core`)
- Tür `TUR_FPV = 'fpv'` (`TURLER` rings | dogfight | fpv). Ayar `flightsim_fpv.fpv_ayar_dogrula(r, tip)`: `{course_id, laps 1–10, crash_rule,
  crash_penalty_s 0–30, miss_penalty_s 0–30, time_limit_min 2–30, seed}`; yalnız çok rotorlu (`multirotor | hexarotor | helikopter`).
  Dünya (`dunya_ayari`): prosedürel, DÜZ merkez (pist/bina/ağaç/su yok), saat ve sis parkurdan, kapalı mekanda rüzgâr 0, `world.fpv_course = cid`
  (`flightsim.world_dogrula` kabul eder; istemci parkur sahnesini kurar).
- YARIS'ta her oyuncuya `ParkurIzleyici`; olaylar WS'e: `ring {lap, gate, pen_s}`, `lap`, `sector`, `miss`, `hit {rule, mat, pen_s}`, `reset`,
  `finish {total_s, pen_s}`; `pos` satırlarında `lap`, `pen`; oyuncu satırında `fpv` özeti, `pen_s`, `lap`; ilerleme (`rings`) kaçırılanlar dahil.
- **Bitiş**: herkes bitirince `hepsi_bitirdi` (tek kişilikte `tamamlandi`); ilk bitirenden sonra diğerlerine `SON_CAGRI_S` = 30 sn (`son_cagri`);
  süre sınırı (`sure`). Kazanan ceza dahil en kısa süre. Sonuçta `kind: 'fpv'`, `fpv {course_id, laps, crash_rule}`, `solo`.
- **Tek kişilik** (tüm türlerde `min_oyuncu`: it dalaşı 2, diğerleri 1): davetli ve bot olmadan kurulan karşılaşma (`tek_kurulum`) hemen HAZIRLIK →
  geri sayım → yarış (zaman denemesi); halka yarışında ilk/tek bitiren → BITTI. Davetliyle kurulup herkes ayrılırsa kendiliğinden tek kişilik
  BAŞLAMAZ (eskisi gibi iptal); kurucu "Gelmeyenler olmadan başlat" derse (60 sn sonra) yalnız kendisiyle başlar. HAZIRLIK / GERI_SAYIM'da biri
  düşerse kalan oyuncu(lar)la sürer. Sonuçta `solo: true`.

### 47.5 HEPGO çalışma zamanı, REST, DB
- `POST /api/drone/sim/matches {settings, kind: 'fpv', fpv: {...}, invite: [], bots: []}` (davet+bot boş → tek kişilik; it dalaşı 400). Sunucu
  `settings.world`'ü parkurun dünyasıyla değiştirir. Başlangıç noktaları parkurun başlangıç pedi ızgarası (`parkur_baslangiclari`: `cols` sütun,
  `gap` m, satırlar 2,5 m geride). `reset` olayında oyuncu oturumuna `reset` komutu. Meta: `limits.fpv {types, laps, crash_rules, penalty_s,
  time_limit_min, courses, defaults}`, `limits.min_players`.
- **Katalog / skor / hayalet** (`fpv_router`, yetki `drone.sim`): `GET /api/drone/sim/fpv/courses` (özet + firma rekoru + benim en iyim + koşu sayısı)
  · `GET /fpv/courses/{cid}?laps=` (tam tanım + firma içi skor tablosu: kullanıcı başına en iyi, aynı tur sayısı) · `GET /fpv/courses/{cid}/ghost?laps=&user_id=`
  (kişisel rekor hayaleti; `user_id` ile firma içi başka pilotun en iyisi).
- **Kayıt**: BITTI'de (sonuç olayı yayından önce) bitiren her İNSAN oyuncu için `drone_fpv_records` satırı (süre ceza dahil, en iyi tur, tur/sektör
  süreleri, ara süreler, kaçırma/çarpma/ceza, çarpma kuralı, hayalet, solo); sonuç satırına `pb_prev` (önceki kişisel en iyi) ve `new_pb`.
- **DB göçü (idempotent; `app/db.py` SCHEMA `CREATE TABLE IF NOT EXISTS`)**: `drone_fpv_records (id, course_id, user_id → users CASCADE, match_id →
  drone_sim_matches SET NULL, type, laps, time_s, best_lap_s, lap_times, sectors, splits, misses, hits, penalty_s, crash_rule, ghost, solo,
  created_at)` + indeksler `(course_id, laps, time_s)`, `(user_id, course_id)`. FPV karşılaşmasında ayar `drone_sim_matches.game_cfg` (it dalaşı
  gibi; `rings_cfg = '{}'`), `kind = 'fpv'`, `rings` = kontrol noktaları.

### 47.6 Hayalet (ghost) kaydı
`hayalet_kodla(ornekler)` → `'g1.' + base64url(...)`: önce örnek sayısı, sonra her örnek için 7 alanın bir öncekine farkı zigzag varint olarak —
t·100 (10 ms), x/y/z·50 (2 cm), yaw/roll/pitch·500 (2 mrad); yaw farkı en kısa yay (mod 3142), çözücü yaw'ı tam sayı uzayında mod 3142 ile
[−π, π)'ye indirir (sarmalar birikmez). 10 Hz × 60 sn ≈ 5,6 kB. JS çözücüsü `flightsim_fpvcourse.js decodeGhost` (birebir; node testi).

### 47.7 Ön yüz (HEPGO; ortak modüller SIMUMAV'da da kullanılır)
- **`flightsim_fpvcourse.js`** (saf, node testli): `decodeGhost` (Python `hayalet_coz` ile birebir), `ghostPoseAt`, `ghostDelta`, `fmtLap`/`fmtDelta`,
  `sectorClass` (mor genel en iyi / yeşil kişisel en iyi / sarı yavaş), `sectorTimesFromSplits`, kapı eksenleri/geçişi (Python ile aynı), başlangıç
  ızgarası, ilerleme (`gateStates`: next / soon / soon2 / done), galeri kartı + kuş bakışı SVG (`courseSvg`), çubuk konumu (`stickPositions`, mod-2),
  tercihler (`fs.fpv.sticks`, `fs.fpv.ghost`), tek kişilik doğrulama (`opponentsErrorSolo`, `soloAllowed`), `FPV_TEXTS` (127 `fpv.*` anahtarı).
- **`flightsim_fpvcourse3d.js`** `createFpvCourseLayer(sim, course, {checkpoints, quality, guide})`: tek sahne/çizici (flightsim3d), mekan atmosferi
  (`envAtmosphere`: hangar içi sıcak tavan lambaları, sisli altın saat, gece stadyum projektörleri, kanyon, puslu şehir; §43 kademesine göre sis/gölge/
  dekor), delikli kutular delik çevresi parçalarına bölünür (`splitBoxHoles`), aynı geometri+malzeme INSTANCING; NEON kapılar — sıradaki YEŞİL
  (nabız), sonraki 1–2 PEMBE/MOR, geçilenler sönük; başlangıçta yerde parlayan yeşil halka; sıradakine ince kılavuz çizgi; bayrak/slalom direkleri ve
  dönüş oku, tünel, yatay dalış kapısı, merdiven kapı; hayalet dron (yarı saydam, yarış saatiyle). API `setProgress / setGhost / update / flash /
  setQuality / setGuide / info / stats / dispose`. Ölçüm (Yüksek, 1440×794): sahne 99–130 çizim çağrısı; katmanın kendi payı 5,7 k (hangar) … 33 k
  (orman) üçgen, 4–14 InstancedMesh.
- **`flightsim_fpvcourse_hud.js`** `createFpvCourseHud(stage, …)`: tur x/y, anlık tur, en iyi tur, sektör kutuları, hayalete göre ± fark, ceza,
  kaçırma/çarpma bildirimi, sıradaki kapı çerçevesi/kenar oku + mesafe (FPV OSD açıkken de), altta iki ÇUBUK-KONUMU göstergesi (aç/kapa).
- **Ses** (`flightsim_sfx.js`): `lap`, `sector_best`, `pb` (kişisel rekor fanfarı), `miss`, `hit`, `ghost_ahead`, `ghost_behind`.
- **Arayüz** (`flightsim_fpvcourse_ui.js`, `flightsim_match_ui.js`, `flightsim.js`): Yeni Karşılaşma "Tür ve kurallar"da üçüncü kart "FPV parkur yarışı"
  + Hazır parkurlar galerisi (önizleme, mekan, uzunluk, kapı, zorluk, rekor/en iyim) + tur/çarpma kuralı/ceza/süre; Davet adımında "Tek başına (zaman
  denemesi)"; Yeni Simülasyon'da "Hazır FPV parkurları" kartı → zaman denemesi; oturumda FPV katmanı + HUD + hayalet (match3d halkaları FPV'de kapalı);
  sonuç: "Zaman denemesi sonucu" (süre, turlar, sektör tablosu, kaçırma/çarpma/ceza, KİŞİSEL REKOR rozeti + önceki rekorla fark, skor tablosundaki yer);
  Karşılaşmalar sekmesinde "FPV parkur" türü + "Tek kişilik" rozeti; tek kişilik halka yarışı sonucu "Tamamlandı". Metinler 6 dil.
- Testler: `node tests/test_flightsim_fpvcourse.mjs` (18). Görseller `./.venv/bin/python -m tests.fpvcourse_shots_hepgo [mekan…]` →
  `/tmp/fpvcourse-shots/` (8 mekan × FPV + takip, galeri, Yeni Simülasyon kartı, tek kişilik davet/özet, HUD + hayalet, sonuç, Karşılaşmalar).
- **Bayram 3B süsleri ile uyum** (ana daldan birleşen `flightsim_holiday3d.js`): parkur katmanı `sim.setDecorKeepouts('fpvcourse', fpvKeepouts(course))`
  ile parkur alanını (env.size'ı kapsayan daire), her kapı/direği ve başlangıç pedini süs yerleşiminden çıkarır (dispose'da kaldırır); `flightsim_match3d`
  `setPlayers` oyuncuların kalkış noktalarını (`players[].start`) `'match-starts'` anahtarıyla bildirir (HEPGO + SIMUMAV; tüm karşılaşma türleri).

## 48. KARIŞTIRMA — GPS karıştırma (jamming) ve GPS aldatma (spoofing) benzetimi (`app/flightsim_jam.py` + `static/js/modules/flightsim_jam.js`; **YALNIZ HEPGO**)
Kullanıcı isteği: "Hepgo içinde simülasyon ekranında karıştırma diye bir bölüm olmalı, istersek spoofing ve gps jamming etkisini simüle etmemiz
gerekiyor." Oturum ekranı alt bandında **Karıştırma** düğmesi; istenildiğinde açılır, elle ya da süre dolunca kapanır.

**Yalnız simülasyon.** Etki, o oturumun ArduPilot SITL sürecindeki GPS benzetimi parametreleriyle (`SIM_GPS1_*`) üretilir; radyo yayını ya da
gerçek alıcıya yönelik hiçbir şey yoktur. Otopilot (EKF3, arıza korumaları) parametrelerin ürettiği bozuk GPS'e gerçek donanımdaki gibi tepki verir.

### 48.1 Komut ve durum
- `cmd jam {gps?, spoof?, dur_s?}` ya da `{off: true}` (REST `/api/drone/sim/sessions/{sid}/cmd` ve WS `cmd`); dönüş `{ok, jam: durum}`.
  Verilmeyen alan önceki ayarı korur; etkin hiçbir şey kalmazsa kapanır.
  - `gps`: `'off'` | `'light'` | `'heavy'` | `'full'`.
  - `spoof`: `{on, dir 0…360° (0 = kuzey, 90 = doğu), speed 0…50 m/s (0 = anında sıçrama), max_m 1…5000 m}`.
  - `dur_s`: 0…3600; 0 = elle kapatılana dek, > 0 = bu kadar **simülasyon** saniyesi sonra kendiliğinden kapanır (hız çarpanıyla uyumlu).
- `durum`: `{supported, on, gps, spoof: {on, dir, speed, max_m}, dur_s, left_s, off_m, nav_err, real, sim: 'sitl' | 'fake', limits}`;
  desteklenmeyen oturumda `{supported: false, reason}`. Oturum yanıtında `session.jam` (düğme `supported` ile görünür).
- WS çerçevesi `{t: 'jam', ts, reason, …durum}`; `reason`: `cmd` (komut), `timeout` (süre doldu), `reset` (Sıfırla), `settled` (kapanış sonrası
  seyrüsefer gerçek konuma döndü).
- Telemetri (etkinken ve toparlanırken): `tele.jam = {gps, spoof, off_m, left_s}`, `tele.nav_lat / nav_lon` (otopilotun sandığı konum),
  `tele.nav_err` (m).
- Olay günlüğü: `Karıştırma: <ayar>`, `Karıştırma kapatıldı`, `Karıştırma süresi doldu — kapatıldı`; ön yüz `settled` çerçevesinde
  "GPS toparlandı — seyrüsefer gerçek konuma döndü" olayını ekler.
- Özet raporu `summary.jam = {count, gps_s: {light, heavy, full}, spoof_s, max_off_m, max_nav_err, sim}` (hiç açılmadıysa `null`).

### 48.2 Seviyeler ve SITL parametreleri
| Ayar | Parametreler | Benzetilen etki |
|---|---|---|
| Hafif | `SIM_GPS1_NUMSATS 6`, `SIM_GPS1_ACC 5`, `SIM_GPS1_GLTCH_X/Y` Gauss–Markov gezinme (σ 2,5 m, τ 4 sn) | uydu sayısı düşer, konum gürültülenir |
| Ağır | `SIM_GPS1_JAM 1` | kilit aralıklı düşer, konum savrulur |
| Tam | `SIM_GPS1_ENABLE 0` | alıcı susar |
| Aldatma | `SIM_GPS1_GLTCH_X/Y` (ofset, derece) + `SIM_GPS1_VERR_X/Y` (sürükleme hızı, NED m/s) | bildirilen konum `dir` yönünde `speed` ile uzaklaşır, `max_m`'de durur |

- Aldatmada konum ofseti ve hız hatası birlikte yazılır (konum ve hız birbirini tutar); hız `IVME` 0,5 m/s² ile rampalanır, hedefe yaklaşırken
  aynı ivmeyle yavaşlar. Ani hız basamağını EKF reddeder; yumuşak başlangıçta sürüklenmeyi izler.
- Adım simülasyon zamanıyladır (`ADIM_MS` 200; SITL GPS'i 5 Hz); parametre yalnız değeri değiştiğinde yazılır.
- Kapanışta ve oturumun ilk kalp atışında `KAPALI_PARAMLARI` yazılır (eeprom "Sıfırla"da korunduğundan `SIM_GPS1_JAM` / `ENABLE` açıkça geri
  alınır). "Sıfırla" karıştırmayı kapatır.

### 48.3 Gerçek konum kipi
Karıştırma etkinken ve kapandıktan sonra EKF gerçek konuma dönene dek (`YAKIN_M` 3 m altında `YAKIN_S` 2 sn; en geç `GERCEK_AZAMI_S` 90 sn)
`tele.lat/lon` SITL fiziğinin **gerçek** konumudur (`SIMSTATE`, 50 Hz istenir); otopilotun sandığı konum `nav_lat/nav_lon`'dadır. 3B sahne,
çarpışma, hedefler ve görev izleme aracın gerçekte olduğu yeri kullanır. Mission Planner ve harekât paneli MAVLink'i ham aldığından otopilotun
aldatılmış konumunu görür (sahadaki yer istasyonu gibi). İrtifa ve hız alanları EKF'ten kalır. DataFlash `.bin` kaydındaki konum da EKF
konumudur: Kayıttan oynat ve Uçuş Logları analizi aldatılmış izi gösterir.

### 48.4 Ölçüm (gerçek SITL, ArduCopter stable-4.7.2; `tests/jam_sitl_olcum.py`; GUIDED askı 25 m, rüzgâr 0)
| Senaryo | Gözlenen |
|---|---|
| Aldatma doğu 90°, 2 m/s, 60 m (45 sn) | EKF sahte GPS'i izler, araç gerçekte BATIYA kayar (18 sn'de 31 m). Sapma ≈ 44–50 m'de "GPS Glitch or Compass error" + "EKF3 lane switch"; ~9 sn sonra EKF sahte konuma sıçrar, "Glitch cleared". Kip GUIDED kalır. Seyrüsefer hatası 60 m. |
| Aldatma kapanışı | ~9 sn EKF eski konumda (hata 60 m), sonra EKF sıfırlanır → hata 0; araç kaydığı yerde (−35 m) kalır. `settled` kapanıştan 12 sn sonra. |
| Hafif, 30 sn süreli | fix 3D, 6 uydu; seyrüsefer hatası 0,1–1,8 m; uçuş sürer. Süre dolunca kendiliğinden kapanır (`timeout`), uydu 18'e döner. |
| Ağır (24 sn) | fix 1 ↔ 6, uydu 3 ↔ 18; ~3 sn'de "EKF variance" → "EKF Failsafe: changed to Land Mode"; seyrüsefer hatası 29 m'ye kadar. Kapanınca ~12 sn'de yakınsar. |
| Tam (15 sn) | fix yok, 3 uydu; ~6 sn'de EKF arıza koruması → LAND; hata yavaş büyür (12 sn'de 5,6 m). Kapanınca "EKF3 IMU0 is using GPS". |

Özet (aynı koşu): `{count: 4, gps_s: {light: 30, heavy: 24, full: 15}, spoof_s: 45, max_off_m: 60, max_nav_err: 60.2, sim: 'sitl'}`.

### 48.5 Ön yüz (`flightsim_jam.js`)
- Saf katman (node testli): `GPS_LEVELS`, `LIMITS`, `DEFAULT_CFG`, `normalizeCfg`, `isActive`, `cmdBody`, `cfgText`, `jamBtnKey`, `bannerText`,
  `mergeTele`, `jamReportLines`, `jamSection`, `JAM_TEXTS` / `makeJamT`.
- `createJam({tr, cmd, onEvent, session, stage, storage})` → `{el, banner, update(t), onFrame(m), open, close, isOpen, dispose}`.
  - Alt bantta **Karıştırma** düğmesi (etkinken kırmızı, nabız, "Karıştırılıyor"; toparlanırken turuncu "Toparlanıyor").
  - Panel: GPS karıştırma seviyesi (Kapalı / Hafif / Ağır / Tam + açıklama), GPS aldatma anahtarı, sürükleme yönü (° + dönen ok), sürükleme hızı,
    azami sapma, süre; **Başlat** (etkinken **Uygula**) ve **Durdur**; canlı satır (sapma, seyrüsefer hatası, kalan süre). Esc ya da dışarı
    tıklama kapatır; boş ayarla Başlat uyarı olayı verir. Son ayar `localStorage fs.jam`.
  - Sahne bandı: `KARIŞTIRMA · GPS ZAYIF | GPS KESİNTİLİ | GPS YOK · GPS ALDATMA` + sapma / seyrüsefer hatası / kalan süre; toparlanırken turuncu
    "GPS TOPARLANIYOR". Dar ekranda tek satıra kısalır; mobil çekmecede panel açıkken üst gezinme bandı gizlenir.
- `flightsim.js`: yalnız yazma yetkisi olan, kayıttan oynatma olmayan ve `session.jam.supported` oturumda kurulur; WS `jam` çerçevesi `onFrame`'e,
  telemetri `update`'e gider. `flightsim_report.js`: özet raporunda "Karıştırma" kartı (sayı, GPS karıştırma süresi, GPS aldatma süresi, en büyük
  sahte konum sapması, en büyük seyrüsefer hatası, seviye başına süre) ve metin dökümü satırları. Metinler 6 dil.

### 48.6 Kapsam ve sınırlar
- Yalnız ArduPilot SITL oturumları. PX4 SIH'de karşılığı yok (`OZELLIKLER['jam']`), SIMUMAV oturumlarında kapalı (`SIM_KOMUT` dışı; köprü
  `desteksiz`). `flightsim_jam.js` rapor modülü içe aktardığı için SIMUMAV paketine kopyalanır, düğme orada görünmez.
- Sahte kinematik (SITL'siz; DEV varsayılanı) kipte fiziksel etki yoktur: yalnız göstergeler (fix / uydu, sapma) taklit edilir; panelde ve
  raporda bu not gösterilir, seyrüsefer hatası kutusu çıkmaz.
- Yalnız GPS. Kumanda / telemetri bağlantısı karıştırması, karıştırıcının konumuna bağlı etki alanı ve pusula bozulması yok.

### 48.7 Testler
- `./.venv/bin/python -m tests.test_flightsim_jam` (doğrulama, sürükleme, süre, sahte kip, özet, PX4 / SIMUMAV kapalılığı).
- `node tests/test_flightsim_jam.mjs` (11: saf katman, 6 dil eksik denetimi, bağlanış denetimleri).
- Gerçek SITL ölçümü: `PYTHONPATH=. .venv/bin/python tests/jam_sitl_olcum.py` (≈ 5 dk; `HEPGO_SITL_DIR`).
- Görseller: `./.venv/bin/python -m tests.jam_shots_hepgo` → `/tmp/jam-shots/` (düğme, panel, etkin bant, dar ekran, rapor kartı).
