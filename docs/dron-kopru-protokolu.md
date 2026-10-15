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
- SANAL DRON (`protocol='sanal'`): sunucu içi simülatör; köprü gerekmez. `bridge_id = -drone_id` (negatif), `info.sim = true`, ad
  `Sanal · <dron kodu>`, sysid = uçuşun sysid'si || 1, HEARTBEAT tipi Quadrotor (ArduCopter modları). 5 Hz `status` üretir; komutlar aynı
  `cmd` çerçevesiyle gider (`bridge_id` negatif): arm/disarm, takeoff{alt_rel_m} (3 m/s), land (2 m/s), rtl (12 m/s, sonra iniş),
  goto{lat,lon,alt_rel_m} (12 m/s), set_mode{AUTO|LOITER|GUIDED|RTL|LAND|…}, mission_upload{items}/mission_download (MISSION_ITEM_INT
  şeması), mission_set_current, set_home, altitude_change, arm_check; link_open/link_close/disconnect `ok`. Batarya uçarken 0,03 %/sn düşer.
  Görevi izleyen kalmayınca 10 dk sonra, görev kapanınca/iptal olunca hemen durur (`bridge{online:false}`).

## v1.1 (isteğe bağlı; köprü `auth`/`pair` çerçevesinde `caps:[…]` bildirir, sunucu `hello.caps` ile tarayıcıya açar)

Tanınan caps: `set_home`, `param`, `arm_force`, `reboot`, `mission_set_current`, `altitude_change`, `link` (ayrıca yer tutucu `bakim`, `log` — v1.2).
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
