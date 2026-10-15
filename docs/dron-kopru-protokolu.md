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

Tarayıcı ↔ sunucu (`/ws/drone/live`, oturum çerezi): ← `hello{v,caps,me,bridges[]}` · `status{bridge_id,sysid,state(+ready)}` ·
`bridge{bridge_id,online,info|status}` · `event{bridge_id,sysid,text,severity,ts}` · `res{rid,ok,result,error}` ·
`console{bridge_id,sysid,ts,tag,text,sev,repeat,fresh}` · `console_hist{sysid,lines[]}` · `params{bridge_id,sysid,items[[name,value,index,count,type]],count,cached}` ·
`param_cache{sysid,params{name:[value,index,count,type]}}` · `log{bridge_id,flight_log_id,name}` · `pong`
→ `ping` · `cmd{rid,bridge_id,sysid,name,params}` · `watch{bridge_id|null}` · `console_hist{bridge_id,sysid}` · `console_clear{…}` (komut yetkisi) · `param_cache{bridge_id,sysid}`

## v1.1 (isteğe bağlı; köprü `auth`/`pair` çerçevesinde `caps:[…]` bildirir, sunucu `hello.caps` ile tarayıcıya açar)

Tanınan caps: `set_home`, `param`, `arm_force`, `reboot`, `mission_set_current`, `altitude_change` (ayrıca yer tutucu `bakim`, `log` — v1.2).
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
