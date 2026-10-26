# Dron köprüsü protokolü (HEPGO ↔ GÖKTUNGU köprüleri)

Sunucu: `app/drone_hub.py` (`/ws/drone/bridge` köprü, `/ws/drone/live` tarayıcı). Köprü istemcileri (Android/Python) GÖKTUNGU
tarafında geliştirilir; bu belge iki tarafın ortak sözleşmesidir. Taşıma: JSON metin çerçeveleri + ham MAVLink ikili çerçeveler.

## v1 (DONDURULDU — Ekim 2026)

Köprü → sunucu (metin): `{v:1,t:'auth',key,host,platform,bridge_ver,caps?}` · `{v:1,t:'pair',code,…}` · `{t:'ping'}` ·
`{t:'res',rid,ok,result|error}` · `{t:'log_begin',name,size,sha256,flight_id?,task_id?}` · `{t:'log_end'}` · `{t:'event',sysid,text,severity}`
Köprü → sunucu (ikili): ham MAVLink v1/v2 çerçeveleri; `log_begin` sonrası `.bin` parçaları (≤ 1 MB).
Sunucu → köprü: `{t:'auth_ok',v,bridge_id,name,server_time,session_id,key?}` · `{t:'auth_err',code}` · `{t:'pong'}` ·
`{t:'cmd',rid,sysid,name,params}` · `{t:'log_ready'}` · `{t:'log_ack',flight_log_id}` · `{t:'log_err',error}`
Kapanış kodları: 4400 kimlik yok/zaman aşımı · 4403 anahtar/kod yanlış · 4409 aynı köprü ikinci bağlantı (eskisi kapatılır) · 4429 hız sınırı.
Komutlar (name/params): `arm` · `disarm` · `set_mode{mode}` · `takeoff{alt_rel_m}` · `land` · `rtl` · `goto{lat,lon,alt_rel_m,speed_mps?}` ·
`mission_upload{items[MISSION_ITEM_INT],cruise_speed?}` · `mission_download` · `disconnect` (sunucu tarafı).
Sunucu-yalnız (köprüye gitmez): `arm_check` → `res.result` ARM CHECK raporu.

Çerçeve ayrıntıları (köprü yazarları için):
- İlk metin çerçevesi bağlantıdan sonra 15 sn içinde gelmeli (yoksa 4400). `pair` kodu büyük/küçük harf duyarsız; `auth_ok.key` yalnız `pair`'de ve
  bir kez döner — köprü saklar, sonraki bağlantılarda `auth` kullanır. host ≤120, platform ≤40, bridge_ver ≤40 karakter. IP başına 10 başarısız
  kimlik/dk → 4429. Aynı anahtarla ikinci bağlantı: ESKİ bağlantı 4409 ile kapanır, yenisi kalır (köprü çevrimdışı sayılmaz).
- Sunucu köprüye hiç ikili çerçeve göndermez (yalnız JSON). Köprüden gelen ikili çerçeveler ham MAVLink'tir; ancak `log_begin` … `log_end`
  arasında gelen HER ikili çerçeve .bin parçası sayılır — aktarım sırasında MAVLink gönderilmez.
- `mission_upload.params = {items:[…], cruise_speed?}`; `items` alanları MISSION_ITEM_INT ile birebir: `{seq, frame (6=GLOBAL_RELATIVE_ALT_INT;
  DO_JUMP için 2), command (16 WAYPOINT, 19 LOITER_TIME, 20 RTL, 21 LAND, 22 TAKEOFF, 177 DO_JUMP), current, autocontinue, param1..param4,
  x (lat×1e7), y (lon×1e7), z (m, göreli), mission_type:0}`. MISSION_COUNT/REQUEST/ITEM/ACK el sıkışmasını köprü yürütür;
  `mission_download` → `res.result.items` aynı şema.
- `set_mode.params.mode` ArduPilot mod ADI (büyük harf); köprü HEARTBEAT.type'a göre mavutil mode_mapping ile custom_mode'a çevirir.
- `log_begin`: name `.bin`/`.log` ile bitmeli (≤120 kr), size ≤ 2 GB; sunucu `{t:'log_ready',name}` döner; parçalar düz akış (offset/sıra yok,
  ≤ 1 MB önerilir); `log_end` sonrası boyut/sha256 uyuşmazsa `log_err`; size aşılınca anında `log_err` + iptal. flight_id/task_id isteğe bağlı
  (HEPGO saha görevi uçuş kaydı; yoksa köprü oturumunun bağlamı).
- `ping` köprüden gelir, yanıt `{t:'pong',server_time}`; sunucu ping göndermez, 20–30 sn'de bir önerilir. Sunucu tarafı boşta zaman aşımı yok.
- `event.severity` MAV_SEVERITY 0..7; tarayıcıya `ts`'siz geçer (STATUSTEXT olaylarında sunucu `ts` ekler).
- `res`: `{t:'res', rid, ok, result?, error?}`; sunucu 10 sn bekler — `mission_upload`, `mission_download` ve `log_list` için 60 sn (öğe başına
  MISSION_REQUEST_INT turu telsizde 0,2–1 sn sürer). Köprü `res`'i el sıkışma tamamlanınca döner; ara ilerleme isteğe bağlı `event` ile.
  `disconnect` köprüye gönderilmez (sunucu kapatır, close 1000).

Tarayıcı ↔ sunucu (`/ws/drone/live`, oturum çerezi): ← `hello{v,caps,me,bridges[],task?,flights?}` · `status{bridge_id,sysid,state(+ready)}` ·
`bridge{bridge_id,online,info|status}` · `event{bridge_id,sysid,text,severity,ts}` · `res{rid,ok,result,error}` ·
`console{bridge_id,sysid,ts,tag,text,sev,repeat,fresh}` · `console_hist{sysid,lines[]}` · `params{bridge_id,sysid,items[[name,value,index,count,type]],count,cached}` ·
`param_cache{sysid,params{name:[value,index,count,type]}}` · `log{bridge_id,flight_log_id,name}` · `pong`
→ `ping` · `cmd{rid,bridge_id,sysid,name,params}` · `watch{task_id}` | `watch{bridge_id|null}` · `console_hist{bridge_id,sysid}` · `console_clear{…}` (komut yetkisi) · `param_cache{bridge_id,sysid}`

### Köprü kodu (Faz 1 — köprünün şirkete bağlanması)

Dron Köprüleri'nde köprü oluşturulunca (`POST /api/drone/bridges` → `{id, code}`) ya da "Kodu yenile" (`POST /bridges/{id}/rekey` →
`{key, code}`) ile bir KÖPRÜ KODU üretilir ve YALNIZ BİR KEZ gösterilir. Biçim: **`<domain>/<key>`**
- `domain`: Entegrasyonlar'daki ortak domain (`agentkeys.domain`) varsa o, yoksa isteğin Host başlığı (şemasız, port'suz) — ör. `caymaz.app`.
- `key`: `drone_hub.issue_key` ile üretilen kalıcı anahtar (`secrets.token_urlsafe(32)`, 43 karakter, `[A-Za-z0-9_-]`); sunucuda şifreli saklanır.
Köprü yazılımı kodu ilk `/` konumundan ikiye böler: `wss://<domain>/ws/drone/bridge` adresine bağlanır ve v1 `auth` çerçevesinde `key`
gönderir → köprü kodu üreten şirkete (tenant) ve köprü kaydının sahibine (owner; verilmezse oluşturan kullanıcı) bağlanmış olur
(Entegrasyonlar'daki ajan API anahtarı kalıbı). Eşleştirme (6 haneli `pair` kodu, 10 dk) akışı ikincil olarak kalır; `rekey` eski anahtarı
ve eski kodu anında geçersiz kılar. `GET /bridges` satırları anahtarı/kodu ya da ipucunu DÖNDÜRMEZ (yalnız `has_key`).

### Görev bağlamı (Faz 1 — Canlı Uçuş yalnız saha görevinden)

- Bağlantı bilgisi (köprü, MAVLink sysid, köprünün drona yerel bağlantısı `link`) DRON KAYDINDA DEĞİL, saha görevindeki UÇUŞTA tutulur
  (`field_flights.bridge_id / sysid / link`; `PUT /api/field/flights/{id}`). `GET /api/field/tasks/{id}/live` → `{task, flights[], can_command}`;
  `flights[]: {id, order_id, drone_id, label (kuyruk no | dron kodu), name, protocol ('mavlink'|'sanal'|'dji'), sysid, bridge_id, bridge_name,
  bridge_online, link {type,host?,port?,serial?,baud?}, sim_bridge_id (sanal dronda -drone_id)}`.
- Tarayıcı `{t:'watch', task_id}` gönderir: izleyici görevle sınırlanır — hello/status/bridge/event/console yalnız görevin uçuşlarına bağlı
  köprülerden ve görevin sanal dronlarından gelir; `hello` yanıtı `task{id,code,status,location_name,lat,lon}` ve `flights[]` (live ile aynı)
  taşır, `bridges[]` yalnız bu köprüleri içerir. Uçuş eklenince/kaldırılınca/bağlantısı değişince sunucu izleyicilere yeni bir `hello` gönderir.
  `{t:'watch', bridge_id|null}` eski davranışıyla korunur.
- SANAL DRON (`protocol='sanal'`) = GERÇEK ArduPilot SITL süreci (GÖKTUNGU birebir; app/drone_sitl.py). Görev izlenince hub
  arducopter/arduplane SITL'i başlatır (sürüm sabit: stable-4.7.2, ikili ilk kullanımda `data/sitl/`e indirilir, sha256 kaydedilir;
  model dron kaydının model metninden: varsayılan çok rotorlu '+', 'hexa', 'heli', 'plane', 'quadplane'), `--base-port` 15670'ten
  10'luk boş blok, `--defaults` varsayilan.parm (FRAME_CLASS 1, FS_GCS_ENABLE 0, MAV_SYSID, ARMING_SKIPCHK 16, LOG_BACKEND_TYPE 0,
  LOG_DISARMED 0), çalışma dizini `<veri>/sitl_calisma/<drone_id>`. Hub SERIAL0'a Hepgo Dron Köprüsü çekirdeğiyle (kopru_core.MavLink)
  bağlanır: ham MAVLink gerçek köprüdeki gibi işlenir, komutlar aynı yürütücüden geçer (kinematik, ARM denetimleri, modlar, görev
  davranışı gerçek firmware'den). `bridge_id = -drone_id`, `info.sim = info.sitl = true`, sysid = uçuşun sysid'si || 1. SITL açılışı
  ~10–45 sn (EKF/GPS); bu sürede ARM reddedilir. İstemci kapanınca SITL kendini kapatır; izleyen kalmayınca 10 dk sonra, görev
  kapanınca hemen durur. Sunucu açılışında önceki süreçten kalan SITL'ler (bu kiracının çalışma kökü) temizlenir.
  `HEPGO_SITL=0` yalnız testler için eski sunucu içi kinematik simülatörü seçer.

### Sanal dron kalıcı parametreleri (`app/drone_params.py`; tablo `drone_sitl_params(drone_id, name, value, ptype, updated_at, updated_by, source)`)
Kullanıcı isteği: sanal dronla uçuşta HEPGO'dan ya da Mission Planner'dan değiştirilen parametre kalıcı olsun; aynı dron tekrar kullanılınca
eski parametrelerle gelsin. Hem saha görevinin sanal dronu (`SitlDrone`, drone_id) hem simülatör oturumu (`SimSession`, sihirbazda dron kaydı
seçildiyse) aynı `drone_params.Izleyici`yi kullanır:
- **İzleme:** SITL'den gelen her PARAM_VALUE bilinen değerle karşılaştırılır. (a) `param_set` komutu (`send_command` → `hepgo_set` niyeti) →
  yankı gelince kayıt `source='hepgo'` + kullanıcı. (b) Mission Planner PARAM_SET: UDP'den ham geçer, izleyici baytları ayrıca ayrıştırıp niyeti
  not eder (`gcs_bayt`) → SITL yankısı → `source='mp'`. (c) Niyet yokken tabandan farklı değer → `source='sitl'` — yalnız ilk TAM parametre
  listesi (param_count'un %90'ı görüldü; MP bağlanınca çeker) alındıktan sonra. Taban = SITL'den ilk görülen değer; açılışta HEPGO'nun yazdığı
  kayıtlıların yankıları (`yukleme_isaretle`) yalnız tabana işlenir. Niyet yalnız hedef değerle eşleşen yankıda tüketilir (köprü çekirdeği tip için
  önce PARAM_REQUEST_READ yapar; o eski değerli yankı niyeti düşürmez), 30 sn'de zaman aşımına uğrar.
- **Hariç (hiç kaydedilmez):** ön ekler `STAT_ LOG_ SIM_WIND_ SIM_GPS1_ TKOFF_ MAV1_ MAV2_ MAV3_ SR0_ SR1_ SR2_ SR3_ INS_GYROFFS_ INS_GYR2OFFS_
  INS_GYR3OFFS_` (MAVn_/SRn_: akış hızları — REQUEST_DATA_STREAM bunları değiştirir; INS_GYR*OFFS_: açılış gyro kalibrasyonu — gerçek SITL'de sahte
  "sitl" kaydı üretiyordu); adlar `MIS_TOTAL FENCE_TOTAL RALLY_TOTAL FORMAT_VERSION SYSID_THISMAV MAV_SYSID SIM_SPEEDUP SIM_RC_FAIL FS_THR_ENABLE
  THR_FAILSAFE RC_OVERRIDE_TIME SERVO3_MIN SERVO3_TRIM TKOFF_THR_MINACC BARO1_GND_PRESS BARO2_GND_PRESS BARO3_GND_PRESS GND_ABS_PRESS ARSPD_OFFSET
  ARSPD2_OFFSET` (açılış/ARM yer basıncı ve hava hızı kalibrasyonu) ve simülatör
  oturumunun kalp atışında yazdığı set (`flightsim.RC_PARAMLAR / GPS_RTK_PARAMLARI / PLANE_YER_PARAMLARI / launch_parametreleri`, ör. `SERVO7_FUNCTION`;
  `drone_params.oturum_adlari`). Diğer `SIM_*` (ör. SIM_BATT_VOLTAGE) kaydedilir. `GET …/sitl-params` yanıtı `excluded{prefixes,names}` döner.
- **Yükleme:** SITL açılışında kayıtlılar `varsayilan.parm` sonuna (`parm_metni(..., ekstra)`: HEPGO varsayılanlarından SONRA, aynı ad varsa son
  satır geçerli) yazılır; ayrıca ilk kalp atışında (hub: ilk DroneState; simülatör: `_ilk_heartbeat`, oturum parametrelerinden ÖNCE) PARAM_SET ile
  yeniden yazılır — eeprom.bin'deki eski değer defaults dosyasını ezebilir. Olay şeridi/konsol: "N kayıtlı parametre yüklendi [(k yazılamadı)]".
- **REST (`routers/drone.py`, yetki `drone.drones`: GET okuma, DELETE/POST yazma; yalnız `protocol='sanal'`, aksi 400):**
  `GET /api/drone/drones/{id}/sitl-params` → `{items[{name,value,ptype,source,source_text,updated_at,updated_by,updated_by_name}],count,excluded,can_write}` ·
  `DELETE …/sitl-params` (tümünü sıfırla, `{deleted}`) · `DELETE …/sitl-params/{name}` · `POST …/sitl-params/import {text}` (.param: `AD,DEĞER` /
  `AD DEĞER` / sekme; `#` yorum; hariç ve bozuk satırlar atlanır → `{imported,skipped[],skipped_count,count}`; ≤ 2 MB, ≤ 2000 parametre) ·
  `GET …/sitl-params/export` → `text/plain` `.param` (`#NOTE:` başlığı + `AD,DEĞER`), `Content-Disposition: attachment; filename="D-0001.param"`.
  Dron detayı (drone.js, sanal dron) "Kayıtlı parametreler (N)" kartı: arama, tek tek sil, Tümünü sıfırla (onaylı), Dışa/İçe aktar.
  Çalışan SITL silme/içe aktarmadan etkilenmez; değişiklik sonraki açılışta uygulanır. Dron silinince kayıtlar da silinir (ON DELETE CASCADE).

## v1.1 (isteğe bağlı; köprü `auth`/`pair` çerçevesinde `caps:[…]` bildirir, sunucu `hello.caps` ile tarayıcıya açar)

Tanınan caps: `set_home`, `param`, `arm_force`, `reboot`, `mission_set_current`, `altitude_change`, `link`, `mission_start`, `mission_clear` (ayrıca yer tutucu `bakim`, `log` — v1.2).
- cap `link` — köprünün drona yerel bağlantısını sunucudan açma/kapama (uçuşun Bağlantı ayarı; harekât ekranı Bağlantı Yöneticisi "Bağlan"/"Kes"):
  `link_open{type:'serial'|'tcp'|'udp', host?, port?, serial?, baud?, sysid?}` — serial → `serial` (port adı) + `baud`; tcp/udp → `host` + `port`.
  Köprü bağlantıyı kurar, MAVLink akışını başlatır ve `res` döner (`res.error`: açılamadı sebebi). `link_close` → bağlantıyı kapatır. Köprü
  `link` bildirmezse düğmeler görünmez; köprü yerel ayarıyla kendisi bağlanır (v1 davranışı).
- `set_home{lat?,lon?,alt?}` — boşsa MAV_CMD_DO_SET_HOME param1=1 (mevcut konum), doluysa param1=0 + konum.
- `param_list` — PARAM_REQUEST_LIST; PARAM_VALUE'lar ham MAVLink ile zaten sunucuya akar, sunucu önbelleğe alır ve 200 ms'de bir toplu `params` yayınlar.
- `param_get{name}` — PARAM_REQUEST_READ. `param_set{name,value,type?}` — PARAM_SET; `type` MAV_PARAM_TYPE (1..10); verilmezse tarayıcı
  önbellekten ekler, köprü de kendi öğrendiği PARAM_VALUE tipini kullanır; ikisi de yoksa `res.error='type_unknown'`.
- `arm{force:true}` — MAV_CMD_COMPONENT_ARM_DISARM param2=21196 (yalnız ArduPilot; PX4'te `res.error`).
- `reboot` — MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN param1=1; yalnız disarmed, aksi hâlde `res.error='armed'`.
- `mission_set_current{seq}` — MISSION_SET_CURRENT.
- `mission_clear` — MISSION_CLEAR_ALL (MISSION_ACK beklenir). Görev iptalinde sunucu gönderir (AUTO'ya dönülse bile eski görev uçulmaz).
- `mission_upload` sonucu `result.offset` = başa eklenen öğe sayısı (ev + varsa hız); istemci araç sırasını (MISSION_CURRENT) buna göre çevirir.
- `mission_start` — MAV_CMD_MISSION_START (300), parametresiz. Sunucu bunu yalnız "rota başlat" akışının sonunda (GUIDED → ARM → AUTO) gönderir;
  köprü bildirmezse sunucu AUTO ile yetinir.

### Sunucu-içi kalkış ve rota başlatma akışı (GÖKTUNGU dron.py / gorev.py birebir; köprüye yeni komut gerekmez)
Tarayıcının `cmd{name:'takeoff', params{alt_rel_m, kontrol?}}` isteği köprüye tek komut olarak GİTMEZ; hub şu adımları v1 komutlarıyla yürütür
(teyit telemetriden: HEARTBEAT mod adı ve armed bayrağı; tek deneme, yeniden deneme yok):
1. irtifa 1…500 m (yoksa 10). Aynı dron için akış sürüyorsa red: "Kalkış hazırlık akışı zaten sürüyor; tekrar komut gönderilmedi."
2. `kontrol` (kalkış kontrol listesi maddeleri) varsa önce sunucuda `drone_takeoff_checks`'e yazılır; zorunlu maddelerin hepsi EVET değilse ya da
   kayıt yazılamazsa takeoff GÖNDERİLMEZ. Pilot ve zaman sunucuda damgalanır. Yanıt bu noktada döner (`result.kontrol_id`); akış arka planda sürer.
3. `set_mode{mode:'GUIDED'}` → mod 4 sn içinde GUIDED görünmezse "GUIDED modu teyit edilmedi; takeoff gönderilmedi."
4. ARM değilse `arm` (zorlamasız) → 6 sn içinde armed görünmezse "ARM teyidi alınamadı; takeoff gönderilmedi. Pre-arm uyarılarını kontrol edin."
5. `takeoff{alt_rel_m}` → "TAKEOFF komutu iletildi: N m". Her adım dron konsoluna düşer.
`cmd{name:'mission_start'}` (rota başlat): ARM değilse GUIDED → 0,3 sn → `arm` → 5 sn armed teyidi; sonra `set_mode AUTO` → 0,3 sn →
(köprü bildirdiyse) `mission_start`. NAV_TAKEOFF gönderilmez: `GET /api/drone/routes/{id}/mission` rotanın başına TAKEOFF öğesi ekler
(irtifa ilk noktanınki, en az 2 m; ilk nokta zaten 'takeoff' ise eklenmez; yanıtta `auto_takeoff:true`). Yanıt akış bitince döner.
Sunucu-içi diğer GÖKTUNGU kuralları (dron.py / gorev.py birebir; köprüye v1 komutlarıyla gider, metinler dron konsoluna düşer):
- `disarm` her zaman `force` (param2=21196); `reboot` araç ARM'dayken reddedilir; `set_home{lat,lon}` irtifası = alt − alt_rel
  (telemetri yoksa reddedilir); `goto{lat,lon}` irtifasız gelirse son takeoff/altitude_change hedefi (yoksa mevcut irtifa) kullanılır;
  `altitude_change{alt_rel_m}` = GUIDED + mevcut konumda goto (hedef hafızaya alınır); land/rtl/disarm hedefi siler.
- `mission_pause{davranis:'bekle'|'basa_don'}`: BRAKE (2,5 sn mod teyidi, olmazsa LOITER) | RTL; `mission_resume`: AUTO (teyitli);
  `mission_cancel{rota}`: BRAKE/LOITER + `mission_clear`; `mission_resume_at{seq,rota,toplam_oge}`: mission_set_current → (DISARM ise
  GUIDED → ARM → 5 sn teyit) → AUTO → mission_start. Doğrulanamayan mod geçişinde `ok:false` (aşama değişmez).
- COMMAND_ACK: kullanıcı komutları (22, 21, 20, 400, 176, 252, 178, 192, 16, 300, 241, 246) için kabul → "<KOMUT> kabul edildi";
  red → "[sysid] <KOMUT> BAŞARISIZ: <gerekçe> (<son PreArm metni, 15 sn içinde>)" dron konsoluna ve `{t:'konsol'}` genel konsola.
SABİT KANAT (HEARTBEAT type 1; sanal ve gerçek tüm sabit kanatlar — GÖKTUNGU'da yoktu): takeoff = `param_set{TKOFF_ALT=irtifa (≤200 m), type 9}`
(köprü 'param' bildirmiyorsa ya da yazma reddedilirse dronun kayıtlı TKOFF_ALT'ı kullanılır, uyarı yazılır) → `set_mode TAKEOFF` → 4 sn mod
teyidi → (ARM değilse) `arm` → 6 sn teyit. NAV_TAKEOFF gönderilmez (ArduPlane GUIDED'da reddeder, uçak yerde ARM'lı kalır — SITL'de ölçüldü).
Rota başlat sabit kanatta da çalışır (rotanın başındaki TAKEOFF öğesi AUTO'da uçulur). VTOL (type 19–25) çok rotorlu akışını kullanır.
- **Ev öğesi köprünün işidir (ZORUNLU):** `mission_upload.items` HEPGO öğeleridir ve 0. öğe ev konumu DEĞİLDİR (rota görevlerinde 0. öğe
  otomatik TAKEOFF'tur). ArduPilot 0. sıradaki öğeyi ev konumu sayıp uçmadığı için köprü başa bir ev öğesi (command 16, frame 0, aracın
  konumu) EKLER; isteğe bağlı `cruise_speed` için hemen ardından DO_CHANGE_SPEED (178) ekleyebilir. Eklenen öğe sayısı kadar `DO_JUMP` (177)
  `param1` ve `mission_set_current.seq` hedefi kaydırılır; `mission_download` sonucunda bu öğeler çıkarılıp HEPGO sırasına geri çevrilir.
  Öğeleri olduğu gibi gönderen köprüde rotanın ilk öğesi (kalkış) ev konumu sanılır ve kalkış yapılmaz.
- `altitude_change{alt_rel_m}` — Copter GUIDED: SET_POSITION_TARGET_LOCAL_NED yalnız z (type_mask); Plane: MAV_CMD_DO_CHANGE_ALTITUDE (köprü HEARTBEAT.type'a göre seçer).

## v1.2 (TASLAK — GÖKTUNGU dron.py şemaları, adlar korunur ki dron_bakim.js / Log Yönetimi penceresi değişmeden çalışsın)

### cap `bakim`
- `kalib_gyro`, `kalib_baro`, `kalib_ivme`, `kalib_level`, `kalib_esc`, `kalib_radyo` — params yok; hepsi MAV_CMD_PREFLIGHT_CALIBRATION (241),
  p1..p7: gyro (1,0,0,0,0,0,0) · baro (0,0,1,0,0,0,0) · ivme 3B (0,0,0,0,1,0,0) · level trim (0,0,0,0,2,0,0) · esc (0,0,0,0,0,0,3) (**pervanesiz**) ·
  radyo (0,0,0,1,0,0,0) (ArduPilot'ta RC kalibrasyon işaretçisi; asıl iş RC_MIN/RC_MAX param yazımı).
- `kalib_pusula_baslat` → MAV_CMD_DO_START_MAG_CAL (42424), tüm pusulalar (p1 bitmask 0). `kalib_pusula_kabul` → DO_ACCEPT_MAG_CAL (42425).
  `kalib_pusula_iptal` → DO_CANCEL_MAG_CAL (42426). İlerleme/rapor ham MAVLink ile gelir: MAG_CAL_PROGRESS (completion_pct) ve MAG_CAL_REPORT
  (fitness, ofs_x/y/z, diag_x/y/z, offdiag_x/y/z, cal_status) → sunucu `state.magkal_pct`, `magkal_durum`, `magkal_rapor` (GÖKTUNGU alan adları);
  yeni pusula oturumunda eski rapor sıfırlanır.
- Kalibrasyon oturumu: her `kalib_*` komutunda sunucu `state.kalib={tur,bas}` açar; Kalibrasyon penceresi yalnız bu andan sonraki STATUSTEXT
  satırlarını gösterir (GÖKTUNGU'daki `kalib_mesajlari` yoklaması yerine zaman damgası filtresi).
- `motor_test{motor:int(1..N, ArduPilot motor sırası), tip_no:int(0=yüzde,1=PWM,2=pass-through), deger:number(=5), sure_s:number(=2), adet:int(=0), sira:int(=0)}`
  → MAV_CMD_DO_MOTOR_TEST (209) p1=motor p2=tip_no p3=deger p4=sure_s p5=adet p6=sira. `motor_test_dur{motor}` → aynı komut sure=0.
  (Alan adı `tip_no` — GÖKTUNGU WS gövdesinde `tip` mesaj tipi olduğu için; `params.tip_no` olarak kalır.)

### cap `log`
- `log_list` → LOG_REQUEST_LIST; `res.result.items=[{id,size,time_utc}]`.
- `log_fetch{id}` → köprü LOG_REQUEST_DATA ile çeker, ardından v1 `log_begin`/parçalar/`log_end` akışıyla sunucuya gönderir.
- `log_erase` → LOG_ERASE.

Uygulama sırası: sunucu (CMD_NAMES + state alanları + kalib oturumu) → tarayıcı köprüsü (hepgo_ws.js: dron_bakim.js / Log Yönetimi tipleri) →
GÖKTUNGU köprüsü (kullanıcı onayıyla).

## v1.3 — Görüntü köprüsü (cap `video`; Dron Yönetimi › Kameralar)

Sunucu: `app/drone_video.py` (`/ws/drone/video` köprü, `/ws/drone/video/watch` tarayıcı), REST `app/routers/drone.py`; köprü çekirdeği
`bridge/dron_koprusu/goruntu_core.py` (Linux/Jetson servisi `bridge/dron_koprusu_linux/hepgo_kopru.py` kullanır). Görüntü telemetriden AYRI ikinci
bir WebSocket'tir (büyük ikili parçalar MAVLink/komut gecikmesini etkilemesin); köprü yine yalnız DIŞA DOĞRU bağlanır (NAT / 4G arkası).

**Kamera kaydı (siteden):** tablo `drone_cameras {id, name, drone_id?, bridge_id?, kind 'rtsp'|'rtp', url (rtsp://host:port/yol, kimliksiz), username,
password_enc (cameras.encrypt), transport 'tcp'|'udp', rtp_port, codec 'h264'|'h265', payload_type (96–127), sdp?, fps (0 = kaynak; 5/10/15/20/25/30),
width?/height? (çift, 160×120…3840×2160), bitrate_kbps? (100–20000), active, note}`. Parola yanıtlarda/izleyiciye ASLA dönmez (`has_password`); yalnız
köprüye `video_cfg` içinde gider. Görev bağlamı `field_task_cameras {task_id, camera_id, bridge_id?, drone_id?}`: görev AÇIKKEN (BASLANGIC/GOREVDE)
`bridge_id` doluysa kameranın kayıtlı köprüsü yerine o köprü kullanılır (**etkin köprü**, `drone_video.EFF_BRIDGE`); `drone_id` HUD telemetrisinin dronudur.
`drone_bridges.caps` köprünün son bildirdiği yetenekleri saklar (çevrimdışıyken de "Görüntü köprüsü" rozeti).

**Köprü → sunucu (`/ws/drone/video`):** ilk metin çerçevesi telemetriyle aynı: `{v:1,t:'auth',key,host,platform,bridge_ver,caps:['video',…]}`
(15 sn; yanlış anahtar → `{t:'auth_err',code:4403}` + kapanış 4403; aynı anahtarla ikinci görüntü bağlantısı eskisini 4409 ile kapatır; IP hız sınırı 4429).
Sonra: `{t:'ping'}` · `{t:'vstate',camera_id,state,detail,mime?}` (state: `basliyor|canli|kare_yok|hata|h265|bekliyor|durdu`) ·
`{t:'stat',camera_id,kbps,fps,codec,copy,src_fps,mime}` (2 sn'de bir) · `{t:'snap_err',camera_id,rid,error}`.
İkili çerçeve: `[tür:1][camera_id:4 big-endian][yük]` — tür **1** init (ftyp+moov), **2** anahtar kareyle başlayan parça (moof+mdat; öncesinde
styp/sidx/prft olabilir), **3** ara parça, **4** JPEG anlık görüntü. Tek çerçeve ≤ 4 MB. Köprüde tanımlı olmayan `camera_id` yok sayılır.
Parçalı MP4: `-movflags frag_keyframe+empty_moov+default_base_moof -frag_duration 500000` (anahtar kare + 0,5 sn); anahtar/ara ayrımı köprüde trun/tfhd
`sample_is_non_sync_sample` bayrağından yapılır.

**Sunucu → köprü:** `{t:'auth_ok',v,bridge_id,name,server_time,cameras:[cfg…]}` · `{t:'video_cfg',cameras:[cfg…]}` (kamera/görev ataması değişince ve
30 sn'lik eşitlemede liste değiştiyse) · `{t:'want',camera_id,on}` (ilk izleyici → on:true; son izleyici gidince 20 sn sonra on:false) ·
`{t:'snap',camera_id,rid}` · `{t:'pong'}`. Sunucu köprüye ikili çerçeve göndermez.
`cfg = {id,name,kind,url,username,password,transport,rtp_port,codec,payload_type,sdp,fps,width,height,bitrate_kbps}`. `cameras` anahtarı YOKSA (eski
sunucu) köprü yerel conf'taki `[kamera.N]` bölümlerini kullanır (yedek).

**Köprü davranışı (goruntu_core):** izleyici yokken kaynak açılmaz (4G bant tasarrufu; conf `surekli = evet` ile sürekli). Kaynak ffprobe ile yoklanır;
H.264 + FPS kaynak/aynı (±0,6) + ölçek yok → **yeniden kodlamadan** `ffmpeg -c:v copy`. Aksi hâlde yeniden kodlama: Jetson'da GStreamer
`rtspsrc|udpsrc → depay → parse → nvv4l2decoder → nvvidconv → videorate → nvv4l2h264enc (bitrate, iframeinterval = 2×FPS, insert-sps-pps)` →
H.264 bayt akışı → `ffmpeg -f h264 -c copy` fMP4; donanım kodlayıcı yoksa ffmpeg `libx264 -preset ultrafast -tune zerolatency` (ya da conf
`kodlayici = x264enc`). H.265 kaynak: conf `h265 = uyar` → hvc1 olarak kopyalanır + `vstate h265` uyarısı; `h265 = yeniden_kodla` → H.264.
RTP: SDP verilmezse `m=video <port> RTP/AVP <pt>` + `a=rtpmap:<pt> H264|H265/90000` üretilir. NOFRAME_S (10 sn) parça gelmezse `kare_yok` + süreç
yeniden başlatılır (2→30 sn artan bekleme). Gönderim kuyruğu kamera başına 4 MB: ağ yavaşsa parçalar atlanır, sonraki anahtar parçadan devam edilir.
Anlık görüntü: yayın açıksa önbellekteki init + son anahtar parçadan (kaynağa ikinci bağlantı yok — RTP portu meşgul olsa da), değilse kaynaktan tek kare.
RTSP kimliği URL'ye yalnız köprü sürecinde eklenir; günlükte `rtsp://kullanıcı:***@` olarak gizlenir.

**Sunucu dağıtımı:** kamera başına son init + son GOP önbelleği (≤ 6 MB); yeni izleyici init + anahtar parçadan başlayan GOP'u hemen alır. İzleyici
kuyruğu ≤ 3 MB: aşılınca parçalar atlanır ve izleyici sonraki anahtar parçadan devam eder (yavaş izleyici diğerlerini/köprüyü bekletmez). Kamera başına
≤ 20 izleyici (4429).

**Tarayıcı (`/ws/drone/video/watch?camera_id=N`, oturum çerezi):** yetki `drone.cameras`, `field.live` ya da `drone.drones` okuma (yoksa
`{t:'error',error:'auth'}` + 4403; kamera yok/pasif 4404). ← `{t:'hello',camera{id,name,kind,codec,fps},bridge_online,state,detail,mime,stat}` ·
`{t:'init',mime}` + ikili `[1][init]` · ikili `[2|3][parça]` · `{t:'state',state,detail,mime}` · `{t:'stat',kbps,fps,…,age}` · `{t:'pong',age}`;
→ `{t:'ping'}`. Oynatıcı (static/js/modules/drone_camera.js) MSE `sequence` kipinde ekler, canlı ucu korur (gecikme > 1 sn → 1,1×; > 2,5 sn → uca atla),
10 sn'den eski tamponu siler; MSE yok / kodek desteklenmiyor (H.265) → 2 sn'de bir JPEG.

**REST:** `GET/POST /api/drone/cameras`, `GET/PUT/DELETE /api/drone/cameras/{id}` (PUT `password`: null = koru, metin = değiştir; `password_clear`),
`POST /cameras/{id}/active {active}`, `GET /cameras/{id}/snapshot.jpg` (503: köprü çevrim dışı / zaman aşımı / köprü hatası) — yetki `drone.cameras`
(GET okuma, diğerleri yazma; anlık görüntü görüntüleme yetkisiyle). `GET /api/drone/camera-list?task_id=&drone_id=` (kısa liste, adres yok).
Canlı Uçuş: `GET /api/drone/tasks/{görev}/cameras` → `{assigned[…, task_bridge_id, hud_drone_id, hud], available[], bridges[], drones[{drone_id,label,
bridge_id,sysid}], can_edit}`; `PUT …/cameras/{kamera} {bridge_id?, drone_id?}` (gönderilmeyen alan korunur; dron görevin uçuşlarında olmalı; aynı
köprüde aynı RTP portu reddedilir); `DELETE …/cameras/{kamera}` — görev üyesi ya da saha yöneticisi + `field.live` (yazma için yazma izni).
`GET /api/drone/bridge-app`: işletim sistemi başına (windows / linux-arm64 / linux) o sistemin dosyası olan EN YÜKSEK sürüm klasörü; dosya satırında `version`.

## v1.4 — Mission Planner aktarımı (cap `mp_relay`; Canlı Uçuş › dron kartı › İŞLEMLER › Mission Planner)

Amaç: köprü üzerinden gelen GERÇEK dron bağlantısına HEPGO'nun yanında aynı anda **Mission Planner** ile de bağlanmak (kullanıcı isteği:
"köprü üstünden gelen bağlantıda dışarıya UDP (MP 'UDPCl') bağlantı versin"). Simülatördeki UDP köprüsünün (docs/ucus-simulatoru.md §4) canlı
karşılığı. Sunucu: `app/drone_mprelay.py`; REST `app/routers/field.py`; harekât arayüzü `static/ops/js/hepgo_mp.js`; Dron Yönetimi › dron detayı
"Mission Planner aktarımı" kartı (`static/js/modules/drone.js mpRelayCard`).

**Köprü → sunucu:** `auth.caps` içinde `mp_relay` (Linux/Jetson ≥ **1.1.6**, Windows ≥ **1.1.0** — `kopru_core.VERSION`). Bildirmeyen köprü için
aktarım açılamaz (409 "Köprüyü güncelleyin (Linux ≥1.1.6 / Windows ≥1.1.0)"). Drondan gelen ham çerçeveler v1'deki gibi ikili gelir (değişiklik yok).

**Sunucu → köprü (YENİ ikili çerçeve türü `raw_up`):** `[0x01][ham MAVLink v1/v2 baytları]` — Mission Planner'ın gönderdiği datagram aynen.
Köprü yükü dron bağlantısına (seri/UDP/TCP; `MavLink.write_raw`) olduğu gibi yazar. Denetimler (köprü): yük ≤ 4096 bayt, ilk bayt 0xFE/0xFD,
≤ 400 paket/sn ve ≤ 256 KB/sn (jeton kovası; aşan atılır, `raw_drop`), dron bağlantısı yoksa atılır (`raw_nolink`). Bilinmeyen ikili tür (ilk bayt
≠ 0x01) yok sayılır (ileri uyum). v1.0–v1.3 köprüleri sunucudan ikili çerçeve almaz (sunucu yalnız `mp_relay` bildirene gönderir).

**Sunucu davranışı (uçuş = görev + dron başına, isteğe bağlı):**
- Aç: `LIVE_MP_UDP_BASE` … `+LIVE_MP_UDP_COUNT-1` (varsayılan **14700–14799**; simülatörün `SIM_UDP_BASE` 14550–14649 aralığıyla çakışmaz) arasında
  boş UDP portu `0.0.0.0`'a bağlanır. Mission Planner adresi: `LIVE_MP_PUBLIC_HOST` → `SIM_PUBLIC_HOST` → istek Host'u. Kiracılar ayrı süreçtir:
  port bağlama işletim sisteminde tekil olduğundan bir kiracının portu diğerine verilemez (dolu port atlanır).
- MP → köprü: datagram ≤ 2048 bayt + MAVLink sihirli baytı; **IP kilidi** yalnız geçerli bir GCS HEARTBEAT'i (MAV_TYPE_GCS=6) içeren datagramla
  kurulur (isteğe bağlı `pair_sysid`: yalnız o sistem kimliğinden — MP varsayılanı 255; tek kullanımlık, sıfırlamada yeniden gerekir). Kilitten sonra
  yalnız kilitli IP (kaynak portu değişebilir) iletilir; diğer IP'ler sayılır, IP başına bir kez denetim kaydı + konsol uyarısı. ≤ 300 paket/sn, ≤ 256 KB/sn.
- Köprü → MP: köprüden gelen ham çerçeve MP'nin son adresine. Uçuşun `sysid`'i belliyse ve köprüde başka dron da görülüyorsa yalnız o sysid'in
  çerçeveleri (pymavlink `get_msgbuf`) gider; tek dronlu köprüde ham bayt aynen (tanınmayan mesajlar dahil).
- Kapanma: Kapat; **30 dk** MP paketi gelmezse (`LIVE_MP_IDLE_MIN`); görev BASLANGIC/GOREVDE dışına çıkınca (30 sn'de bir denetim); köprü 120 sn'den
  uzun çevrimdışı kalınca; uçuşun köprüsü/sysid'i değişince ya da uçuş görevden kaldırılınca. Kısa köprü kopmalarında aktarım açık kalır (MP paketleri
  `dropped.offline` sayılır).
- Denetim günlüğü (`audit_logs`, entity `field_flight`): "Mission Planner aktarımı açıldı" (açan, port, eşleştirme) · "…: MP bağlandı" (IP:port) ·
  "…: kilit dışı IP reddedildi" · "…: IP kilidi sıfırlandı" · "Mission Planner aktarımı kapandı" (neden, paket sayaçları, kilit IP'si).
- HEPGO ile birlikte çalışma: köprü ve MP aynı GCS kimliğini (255/190) kullanabilir; ArduPilot ikisine de yanıt verir, telemetri ikisine de akar.
  MP'den gelen ARM/DISARM, mod (COMMAND_LONG 176 / SET_MODE), kalkış/iniş/RTL, görev başlat, reboot, motor testi → dron konsoluna (etiket `MP`) ve
  genel konsola "D<sysid> Mission Planner: …" (uyarı); görev yükleme (MISSION_COUNT), temizleme, set_current, Fly To Here, PARAM_SET → dron konsolu.
  MP yinelemeleri (ACK gelene dek) tek satırdır. HEPGO kalkış/görev akışı sürerken MP komutu gelirse satıra "DİKKAT: … komutlar çakışabilir" eklenir.
- Parametreler: MP `PARAM_SET` niyeti not edilir; dronun `PARAM_VALUE` yankısı hedef değerle gelince dron kaydına (`drone_sitl_params`, kaynak `mp`)
  yazılır (`drone_params.Izleyici(gercek=True)`: niyetsiz araç değişiklikleri ve sanal montaj işlemi yok). Aktarım açıkken HEPGO panelinden yapılan
  `param_set` de aynı kayda (kaynak `hepgo`) girer. Kayıtlar Dron Yönetimi › dron detayı "Kayıtlı parametreler" kartında (MAVLink dronlarda da) görünür.

**REST (oturum çerezi):**
- `GET /api/field/flights/{uçuş}/mp-relay` → `{active, flight_id, task_id, bridge_id, sysid, protocol, available, bridge_online, bridge_ver,
  bridge_supported, update_hint, min_versions{linux,windows}, host, port_range[a,b], idle_timeout_s, can_manage}` + açıkken `{port, address 'host:port',
  opened_at, opened_by, pair_sysid, locked_ip, peer, connected (son MP paketi < 10 sn), last_rx, last_rx_ago, last_tx, rx_packets, rx_bytes,
  tx_packets, tx_bytes, dropped{ip,rate,invalid,offline}, closes_in_s, params_saved}`. Yetki: `field.live` okuma + görev üyesi / saha yöneticisi.
- `POST …/mp-relay {pair_sysid?}` (aç; açıksa aynısını döner) · `DELETE …/mp-relay` (kapat) · `POST …/mp-relay/reset-ip` — ayrıca
  `drone_mprelay.can_manage`: Canlı Uçuş komut yetkisi (field.live yazma + Pilot/Yönetici) ya da `drone.drones` yazma + Pilot/Sistem Yöneticisi.
  Hatalar: 400 sanal dron / köprüsüz uçuş / görev açık değil / pair_sysid aralığı; 403 yetki; 409 köprü çevrimdışı / eski köprü / boş port yok.
- `GET /api/field/tasks/{görev}/mp-relays` → `{items:[info…], can_manage}` (harekât ekranı kart rozeti).
- `hello.bridges[].mp_relays`: köprünün açık aktarımlarının uçuş kimlikleri.

**Köprüde YEREL Mission Planner (internet gerekmez; varsayılan kapalı):** Linux conf `[baglanti] mp_udp = 0.0.0.0:14550` (dinle: ağdaki MP › UDPCl ›
<köprü IP'si>:14550; ilk paket gönderen adres kilitlenir, 30 sn sessizlikte kalkar) ya da `mp_udp = 192.168.1.50:14550` (gönder: o bilgisayardaki MP
› UDP 14550 dinler; yalnız o IP'den gelen kabul edilir); önek de verilebilir (`dinle:` / `gonder:`). Komutlar: `sudo hepgo-kopru mp-ac <ip:port>`,
`sudo hepgo-kopru mp-kapat`, `hepgo-kopru durum` (yerel MP satırı + sayaçlar). Windows uygulaması: "Yerel Mission Planner" alanı ya da
`--mp-udp`. Yerel MP trafiği de aynı denetimlerden (boyut, sihirli bayt, hız) geçer; HEPGO aktarımıyla aynı anda çalışabilir.
