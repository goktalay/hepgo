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
| `POST /sessions` | `{type, center_id, world, model?}` → `session` (201). `model`: `{id, orient?}` ya da kimlik dizgesi (§12; eksikse tipin varsayılanı; eski `airframe: caymaz|delta` → `builtin:…` eşlenir). Hatalar: 400 `invalid`, 409 `limit`, 503 `sitl` (ikili/port yok) |
| `/models…` | Görsel model kütüphanesi (§12): liste, yükleme, tasarım dosyasından ekleme, GLB/küçük resim PUT-GET, yönelim, silme |
| `GET /sessions/{id}` | `session` |
| `DELETE /sessions/{id}` | durdurur (SITL kapanır, UDP kapanır) → `{ok}` |
| `POST /sessions/{id}/cmd` | `{name, params}`; name ∈ `arm` (force), `disarm`, `mode` (`params.mode` ArduPilot mod adı), `takeoff` (`params.alt`; sabit kanatta yönteme göre dizi + WS `launch` olayları, §13), `rtl`, `reset` (SITL'i aynı ayarlarla yeniden başlatır), `crash` (ön yüz çarpışma: zorla disarm + olay), `set_home`, `rc` (`params.ch` 8 kanal 1000–2000, RC_CHANNELS_OVERRIDE; ileride Gamepad) → `{ok}` |

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
- Kameralar (tuşlar 1–4): **Takip** (3. şahıs, OrbitControls hedefi dron), **Dron kamerası** (FPV, burun; gimbal pitch ↑↓),
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

## 6. Kurulum sihirbazı (`flightsim.js`)
1. Dron tipi kartları (SITL `TIP_ESLEME` anahtarları) + altında **Model** bölümü (§12: görsel kart ızgarası, yükleme, sistemdeki dosyalardan
ekleme, yönelim paneli; kayıt kipinde log listesinin altında, log tipine göre). 2. Merkez seçimi (liste; ad, konum adı, koordinat; merkez yoksa Rotalar'a bağlantı).
3. Dünya: kip (Gerçek arazi / Google 3B (fotogerçekçi; yalnız `meta.google3d.enabled`, §10) / Prosedürel, §9), kaydırıcılar/seçimler
(yukarıdaki `world`), "Rastgele tohum", önizleme (küçük 3B; gerçek kipte yükleme şeridi + özet; Google 3B'de karo yüzdesi + logo). 3b. **Kayıt** kutusu
(`recOptionsBox`, §17/§19; yalnız yazma izni): ☐ Ekran kaydı al (video) › ☐ Şirketten Haberler'de paylaş · ☐ Uçuş logunu (.bin) kaydet (yalnız canlı).
4. Başlat → **ön hazırlık kartı** (§8: sunucu HAZIR + kareler + dünya verisi) → oturum ekranı.
Açık oturum varsa liste: devam et / bitir; "Yarım kayıt" ve "Kayıtlarım" kutuları (§17). 8 dil (i18n.*.js; sözlük dosyaları modül olarak `node --check` ile denetlenir).

## 7. Testler
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
  type, flight_s, duration_s, takeoff_utc, start_utc, home_lat, home_lon, cached}]` · `POST /sessions {mode:'replay', log_id, world}` →
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
  çizilmese de `runway_heading` boyunca 1200×40 m sanal şerit kalkış/iniş koşusu için muaf. Kalkış düzeneği (§13) aynı `terrainHeight` ile
  karo yüzeyine oturur ve karolar yüklendikçe (500 ms'de bir yeniden örnekleme) ince LOD yüzeyine iner — "rampa haritanın üzerinde uçuyor"
  izleniminin kök nedeni düzeneğin `z = 0` varsayımıyla eğimli/ofsetli karo yüzeyinin üstünde ya da içinde durmasıydı.
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
`builtin:caymaz` (Caymaz V3 GLB) + `builtin:delta`; multirotor `builtin:quad`; hexarotor `builtin:hexa`; helikopter `builtin:heli`; VTOL
`builtin:caymaz` / `builtin:delta` ("VTOL-Caymaz V3", "VTOL-Delta kanat"; 4 dikey motor eklenir). Varsayılanlar `VARSAYILAN`. (b) **Tasarım** —
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
±0,92/−1,6…1,85 m × ölçek) `terrainHeight` ile örneklenir (gerçek arazi ızgarası / Google 3B karo ışını) → yükseklik (ortalama) + eğim (ön/arka →
pitch, sağ/sol → roll, ≤ 20°; Euler `ZXY`: yerel roll, pitch, sonra pist yönü); eğimden doğan kızak XY kayması ikinci geçişte düzeltilir (SITL uçağı
kızakta kalır). `rig.resurface(terrainHeight)` her 500 ms yeniden örnekler ve hedefe 0,25 sn'de yumuşak yaklaşır → Google 3B'de karolar yüklendikçe
(kaba → ince LOD, `groundOffset` değişimi) düzenek zıplamadan yüzeye iner; uçak kızakta düzenekle birlikte (`planeQuat` = düzeneğin dünya
yönelimi × rampa eğimi). Teşhis: `sim.rigState()` → `{phase, surface:{z, pitch_deg, roll_deg}, x, y}`.
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
`fs.ops.on`. Dron kamerası (2/FPV): `.fs-fpv` → kart gizli, askeri HUD (H) kalır. Kart başlık şeridinden sürüklenir (`fs.panel.col` {x, y, r};
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
düşer. Sunucu `TERRAIN_REPORT` → `tele.terrain_agl` (yalnız `loaded > 0 ∧ terrain_height ≠ 0`); 3B'de `|(z − h) − terrain_agl| > COLL_AGL_DISAGREE_M
(30 m)` ise örnek kaba karodandır → o karede arazi/su denetimi yok. Açık iş: HEPGO'nun `TERRAIN_REQUEST`'e `sim_terrain` vekilinden `TERRAIN_DATA` ile
yanıt vermesi (SITL fiziği MP olmadan da gerçek araziyi görür).

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

**Ön yüz (`flightsim.js renderWizard` → sayfa; `wizardModal` → pencere; `flightsim_runs.js runsTable`).** Sayfa: üst satır (sınır notu + **"+ Yeni
Simülasyon"** düğmesi; yazma izni yoksa pasif) · açık oturumlar şeridi (devam et / bitir) · yarım kayıt şeridi (`pendingCard`, §17) · **"Simülasyon
Kayıtları"** kartı · CAYSIM istemcileri kartı. Eski "Kayıtlarım" ve "Son simülasyon raporları" kartları tabloya taşındı (Video / Rapor düğmeleri).
Tablo (HEPGO `.table-wrap > table.table` kalıbı): tarih/saat (+ `#oturum · kapanış nedeni`), kullanıcı, dron tipi/model (kayıt rozeti), merkez/konum
(+ koordinat), dünya kipi, kalkış yöntemi (sabit kanat), süre, sonuç rozeti (**ÇARPIŞMA** kırmızı `×n` / Tamam yeşil / Hata turuncu; çarpışma
satırı `row-alert`), ekler (SVG simgeler: video, .bin [analiz sürüyorsa sarı], parametre, script — emoji yok), işlemler: **Oynat** (`play_log_id`
∧ yazma izni; pencereyi kayıttan oynat kipinde o log seçili açar → dünya seçimi → Başlat → mevcut replay akışı), **Rapor** (`showReport`),
**Video** (modal `<video>` + İndir), **.bin** (indir), **Parametreler** / **Script** (yalnız `ctx.user.master`; `<a download>`), **Sil**
(`can_delete`; onay). Filtreler: tarih aralığı (iki `date`), merkez / tip / kullanıcı (facet açılır listeleri, sayılarla), sonuç, kaynak (canlı /
kayıt), arama (250 ms gecikmeli), Temizle; sıralama sütun başlığından (▲/▼); 25'li sayfalama (‹ Sayfa p / n ›). Boş durum metni.
**Pencere** (`ui.js modal`, `wide` + `.fs-wizard-modal` 1240 px, gövde kaydırılabilir): başlık **"Yeni Simülasyon Başlat"**, gövde = Kip · 1 Dron tipi
(+ kalkış yöntemi + model) · 2 Merkez (+ dron kaydı) · 1 Uçuş logu (kayıt kipi) · 3 Dünya (+ 3B önizleme) · Kayıt seçenekleri · not; altbilgi
**"İptal et"** + **"▶ Başlat"** (primary; kayıt kipinde "▶ Oynat"). Başlat → mevcut akış: tam ekran + ekran paylaşımı izni → `POST /sessions` →
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
