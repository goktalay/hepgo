"""Uçuş simülatörü §45 — UÇUŞ YIĞINI (otopilot) seçimi ve PX4 SITL (SIH) entegrasyonu. YALNIZ HEPGO.

SIMUMAV'a dışa aktarılmaz: tools/simumav_export.py çekirdek listesinde yoktur ve flightsim.py bu modülü `importlib` ile yalnız
`stack='px4'` istendiğinde yükler (SIMUMAV köprüsü yığın geçmez → her zaman ArduPilot). docs/ucus-simulatoru.md §45.

Yığın kataloğu (fizibilite, §45.1): ArduPilot (varsayılan, mevcut çekirdek) · PX4 (SIH, gerçek entegrasyon) · INAV / Paparazzi (planlandı) ·
Betaflight / Rotorflight (uygun değil). Ön yüz katalogdaki `status` ve `reason` ile kartları gri + "yakında" rozetli gösterir.

PX4 SITL tasarımı (ölçülmüş tuzaklar):
  P1. PX4 SITL MAVLink bağlantıları UDP'dir; GCS bağlantısı (18570+i) bir eş paket gönderene dek 127.0.0.1:14550'ye yollar — 14550 HEPGO'nun
      ilk oturumunun UDP köprü portudur (SIM_UDP_BASE) → sızıntı. Çözüm: örnek dizinindeki `hepgo/px4-rc.mavlink` PATH'te PX4'ün kendi
      betiğinden ÖNCE bulunur ve YALNIZ GCS bağlantısını, partneri baştan HEPGO'nun yerel UDP soketi olacak şekilde açar (-t 127.0.0.1 -o <port>);
      offboard / kamera / gimbal / SIH görüntü bağlantıları açılmaz (port çakışması yok).
  P2. rcS MAV_SYS_ID'yi örnek+1 yapar ve commander bunu yalnız başlarken okur → `hepgo/px4-rc.simulator` (commander'dan önce kaynaklanır)
      MAV_SYS_ID'yi HEPGO_SYSID'e (1) çeker, sonra PX4'ün kendi px4-rc.simulator'ını çağırır. Böylece Mission Planner/QGC hep sysid 1 görür.
  P3. Örnek numarası 70…99: /tmp/px4_lock-<i> kilidi boş olan ilk numara (başka oturumların / geliştiricilerin 0…69 örneklerine dokunulmaz).
  P4. Parametre deposu örnek çalışma dizininde (parameters.bson, parameters_backup.bson, dataman): temiz açılışta silinir (ArduPilot temiz=True
      eşleniği); "Sıfırla" (temiz=False) korur. Açılış parametreleri PX4_PARAM_<AD>=<değer> ortam değişkenleriyle (rcS, airframe'den önce).
  P5. Ev konumu PX4_HOME_LAT/LON/ALT (SIH_LOC_*); simülasyon hızı PX4_SIM_SPEED_FACTOR yalnız açılışta okunur (çalışırken değiştirilemez).
"""
import asyncio
import contextlib
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path

from . import drone_sitl, flightsim, flightsim_hub

# ======================================================================
# Yığın kataloğu (§45.1 fizibilite)
# ======================================================================
YIGIN_VARSAYILAN = 'ardupilot'
PX4_SURUM = 'v1.16.2'
PX4_TIPLER = ('multirotor', 'sabit_kanat', 'vtol')

YIGINLAR = (
    {'key': 'ardupilot', 'name': 'ArduPilot', 'rtos': 'ChibiOS', 'license': 'GPLv3', 'status': 'active', 'version': 'stable-4.7.2',
     'gcs': 'Mission Planner', 'params_ext': '.parm', 'types': list(drone_sitl.TIP_ESLEME),
     'desc': 'Varsayılan. Gerçek ArduCopter / ArduPlane / ArduRover SITL süreci; tüm simülatör özellikleri.'},
    {'key': 'px4', 'name': 'PX4', 'rtos': 'NuttX', 'license': 'BSD-3-Clause', 'status': 'active', 'version': PX4_SURUM,
     'gcs': 'QGroundControl', 'params_ext': '.params', 'types': list(PX4_TIPLER),
     'desc': 'PX4 SITL — SIH (Simulation-In-Hardware, Gazebo\'suz) fiziği: quadcopter X, sabit kanat, standart VTOL / tailsitter.'},
    {'key': 'inav', 'name': 'INAV', 'rtos': 'bare-metal STM32', 'license': 'GPLv3', 'status': 'planned', 'types': [],
     'reason': 'INAV SITL fizik içermez; X-Plane ya da RealFlight köprüsü ister. MAVLink çıkışı yalnız telemetri (komut/görev kısıtlı), '
               'yapılandırma MSP. HEPGO fiziğiyle X-Plane UDP köprüsü planlandı.'},
    {'key': 'paparazzi', 'name': 'Paparazzi UAV', 'rtos': 'ChibiOS', 'license': 'GPLv2+', 'status': 'planned', 'types': [],
     'reason': 'NPS simülatörü (JSBSim/OCaml araç zinciri) ve Ivy veri yolu + PPRZLINK protokolü; MAVLink yalnız ek modülle ve kısmi. '
               'Derleme zinciri ağır; planlandı.'},
    {'key': 'betaflight', 'name': 'Betaflight', 'rtos': 'bare-metal STM32', 'license': 'GPLv3', 'status': 'unsuitable', 'types': [],
     'reason': 'SITL yalnız Gazebo / RealFlight fizik köprüsüyle; GPS seyrüseferi, görev ve otomatik kipler yok (acro/angle yarış FC\'si); '
               'yapılandırma MSP, MAVLink yalnız tek yönlü telemetri. HEPGO\'nun görev/RTL akışlarına uymuyor.'},
    {'key': 'rotorflight', 'name': 'Rotorflight', 'rtos': 'bare-metal STM32', 'license': 'GPLv3', 'status': 'unsuitable', 'types': [],
     'reason': 'Betaflight türevi flybarless helikopter FC\'si; bakımı yapılan SITL hedefi ve helikopter fiziği yok, GPS seyrüseferi yok, MSP.'},
)

# PX4 SIH airframe'leri (ROMFS init.d-posix/airframes): tip → [(SYS_AUTOSTART, model, ad)] — ilki varsayılan
PX4_AIRFRAMES = {
    'multirotor': [(10040, 'sihsim_quadx', 'SIH Quadcopter X')],
    'sabit_kanat': [(10041, 'sihsim_airplane', 'SIH Sabit kanat (pist kalkışı)')],
    'vtol': [(10043, 'sihsim_standard_vtol', 'SIH Standart VTOL (4+1)'), (10042, 'sihsim_xvert', 'SIH Tailsitter (xvert)')],
}

# PX4 özel kipleri (px4_custom_mode.h): ad → (main, sub). custom_mode = main << 16 | sub << 24
PX4_MODLAR = {
    'MANUAL': (1, 0), 'ALTCTL': (2, 0), 'POSCTL': (3, 0), 'POSCTL.ORBIT': (3, 1),
    'AUTO.READY': (4, 1), 'AUTO.TAKEOFF': (4, 2), 'AUTO.LOITER': (4, 3), 'AUTO.MISSION': (4, 4), 'AUTO.RTL': (4, 5), 'AUTO.LAND': (4, 6),
    'AUTO.FOLLOW_TARGET': (4, 8), 'AUTO.PRECLAND': (4, 9), 'AUTO.VTOL_TAKEOFF': (4, 10),
    'ACRO': (5, 0), 'OFFBOARD': (6, 0), 'STABILIZED': (7, 0), 'TERMINATION': (10, 0),
}
# Uçuş çubuğunda gösterilen kipler (tip ailesine göre)
PX4_KIP_LISTESI = {
    'multirotor': ['STABILIZED', 'ALTCTL', 'POSCTL', 'ACRO', 'AUTO.TAKEOFF', 'AUTO.LOITER', 'AUTO.MISSION', 'AUTO.RTL', 'AUTO.LAND', 'OFFBOARD'],
    'sabit_kanat': ['MANUAL', 'STABILIZED', 'ACRO', 'ALTCTL', 'POSCTL', 'AUTO.TAKEOFF', 'AUTO.LOITER', 'AUTO.MISSION', 'AUTO.RTL', 'AUTO.LAND'],
    'vtol': ['MANUAL', 'STABILIZED', 'ALTCTL', 'POSCTL', 'AUTO.VTOL_TAKEOFF', 'AUTO.TAKEOFF', 'AUTO.LOITER', 'AUTO.MISSION', 'AUTO.RTL', 'AUTO.LAND'],
}
# ArduPilot kip adları (ön yüz kısayolları, harekât paneli, gamepad) → PX4 karşılığı; PX4 kısa adları da (QGC: Hold, Return, Mission)
KIP_TAKMA = {
    'GUIDED': 'AUTO.LOITER', 'LOITER': 'AUTO.LOITER', 'HOLD': 'AUTO.LOITER', 'CIRCLE': 'AUTO.LOITER', 'BRAKE': 'AUTO.LOITER',
    'AUTO': 'AUTO.MISSION', 'MISSION': 'AUTO.MISSION', 'RTL': 'AUTO.RTL', 'SMART_RTL': 'AUTO.RTL', 'QRTL': 'AUTO.RTL', 'RETURN': 'AUTO.RTL',
    'LAND': 'AUTO.LAND', 'QLAND': 'AUTO.LAND', 'TAKEOFF': 'AUTO.TAKEOFF', 'ALT_HOLD': 'ALTCTL', 'FBWB': 'ALTCTL', 'POSHOLD': 'POSCTL',
    'QHOVER': 'POSCTL', 'QLOITER': 'POSCTL', 'CRUISE': 'POSCTL', 'POSITION': 'POSCTL', 'ALTITUDE': 'ALTCTL', 'STABILIZE': 'STABILIZED',
    'QSTABILIZE': 'STABILIZED', 'FBWA': 'STABILIZED', 'QACRO': 'ACRO',
}

# PX4'te çalışan / çalışmayan simülatör özellikleri (ön yüz gri + gerekçe; §45.3)
OZELLIKLER = {
    'telemetry': (True, 'ATTITUDE, GLOBAL_POSITION_INT, VFR_HUD, SYS_STATUS, GPS_RAW_INT, HOME_POSITION standart MAVLink — 3B ve HUD aynı yoldan.'),
    'gcs': (True, 'UDP köprüsü aynı: QGroundControl önerilir (Mission Planner da bağlanır; PX4 parametre/kip ekranları QGC\'de tam).'),
    'arm': (True, 'MAV_CMD_COMPONENT_ARM_DISARM (ön uçuş denetimleriyle; EKF hazır olunca kabul edilir).'),
    'takeoff': (True, 'ARM + MAV_CMD_NAV_TAKEOFF (AMSL irtifa) → AUTO.TAKEOFF; sabit kanatta pist kalkışı (RWTO_TKOFF 1).'),
    'rtl': (True, 'MAV_CMD_NAV_RETURN_TO_LAUNCH → AUTO.RTL (iniş dâhil).'),
    'modes': (True, 'PX4 kipleri (custom_mode main/sub): POSCTL, ALTCTL, AUTO.MISSION, AUTO.RTL, AUTO.LAND, OFFBOARD…'),
    'rc': (True, 'Sanal kumanda MANUAL_CONTROL ile (COM_RC_IN_MODE 1; RC override yerine).'),
    'mission': (True, 'Harekât paneli görev yükleme/indirme PX4 görev protokolüyle (ev öğesi yok).'),
    'params_file': (True, 'QGC .params / düz AD DEĞER dosyası açılışta PX4_PARAM_* ile yüklenir.'),
    'power': (True, 'Yakıt/batarya göstergesi istemci+sunucu tarafında telemetriden hesaplanır.'),
    'targets': (True, 'Hedefler SITL\'den bağımsız (ADSB_VEHICLE MP/QGC\'ye).'),
    'gpws': (True, 'Uçuş uyarıları telemetriden; PX4 kip adları tanınır.'),
    'speed': (False, 'PX4 SIH simülasyon hızı yalnız açılışta (PX4_SIM_SPEED_FACTOR); uçuş sırasında değiştirilemez — sihirbazda seçilir.'),
    'wind': (False, 'PX4 v1.16 SIH fiziğinde rüzgâr parametresi yok (SIM_WIND_* ArduPilot\'a özgü); rüzgâr yalnız görsel/HUD.'),
    'motor_cut': (False, 'MOTOR_ESTOP (DO_AUX_FUNCTION 31) ArduPilot\'a özgü; PX4\'te kill switch yalnız RC/termination.'),
    'servo_trigger': (False, 'Servo tetik DO_SET_SERVO + SERVOn_FUNCTION ArduPilot\'a özgü; PX4 DO_SET_ACTUATOR eşlemesi planlandı.'),
    'launch': (False, 'Rampa / araç üstü / fırlatıcı kalkış dizileri ArduPlane parametrelerine bağlı; PX4\'te yalnız pist kalkışı.'),
    'terrain': (False, 'TERRAIN_REQUEST/DATA arazi sunumu ArduPilot\'a özgü; PX4 SIH düz zemin (ev irtifası araziden).'),
    'bin_log': (False, 'Kayıt PX4 ULog (.ulg) olarak örnek dizinine yazılır; Uçuş Logları .ulg yüklemesini henüz desteklemiyor.'),
    'saved_params': (False, 'Dron kaydının kalıcı parametreleri ArduPilot adlarıyla tutulur; PX4 oturumunda yüklenmez/kaydedilmez.'),
    'layout': (False, 'Kontrol düzeni / SITL modeli seçimi ArduPlane\'e özgü; PX4\'te airframe (SYS_AUTOSTART) belirler.'),
    'defend': (False, '"Yer kontrolünü koru" görevi INTERCEPTOR (ArduPlane tailsitter) akışıdır.'),
}
DESTEKSIZ_KOMUT = {'speed': 'speed', 'motor_cut': 'motor_cut', 'launch_aim': 'launch', 'servo_trigger': 'servo_trigger', 'servo_set': 'servo_trigger',
                   'defend': 'defend'}


def px4_klasoru():
    """PX4 kurulumu: HEPGO_PX4_DIR, yoksa SITL klasörünün `px4` alt dizini (PROD data/sitl/px4), yoksa kardeşi (DEV HEPGO_SITL_DIR=/opt/hepgo/sitl/bin
    → /opt/hepgo/sitl/px4)."""
    if os.environ.get('HEPGO_PX4_DIR'):
        return Path(os.environ['HEPGO_PX4_DIR'])
    ilk = drone_sitl.SITL_KLASORU / 'px4'
    for aday in (ilk, drone_sitl.SITL_KLASORU.parent / 'px4'):
        if (aday / 'bin' / 'px4').is_file():
            return aday
    return ilk


def px4_ikili():
    return px4_klasoru() / 'bin' / 'px4'


def px4_var():
    """PX4 SITL kurulumu hazır mı (bin/px4 + etc/init.d-posix/rcS)."""
    ik = px4_ikili()
    return ik.is_file() and os.access(ik, os.X_OK) and (px4_klasoru() / 'etc' / 'init.d-posix' / 'rcS').is_file()


def px4_surum():
    try:
        return (px4_klasoru() / 'VERSION').read_text(encoding='utf-8').strip()[:200]
    except OSError:
        return None


def katalog():
    """Ön yüz kataloğu (meta.stacks): PX4 `available` ikili kurulumuna göre; yoksa durum 'missing' + PROD kurulum notu."""
    out = []
    for y in YIGINLAR:
        d = {k: (list(v) if isinstance(v, list) else v) for k, v in y.items()}
        if d['key'] == 'px4':
            d['available'] = px4_var()
            d['build'] = px4_surum()
            if not d['available']:
                d['status'] = 'missing'
                d['reason'] = 'PX4 SITL ikilisi bu sunucuda kurulu değil (data/sitl/px4 — docs §45.6 kurulum).'
            d['airframes'] = {t: [{'id': a, 'model': m, 'name': n} for a, m, n in v] for t, v in PX4_AIRFRAMES.items()}
            d['features'] = {k: {'ok': ok, 'note': n} for k, (ok, n) in OZELLIKLER.items()}
        else:
            d['available'] = d['status'] == 'active'
        out.append(d)
    return out


# ======================================================================
# Kipler
# ======================================================================
def kip_coz(ad):
    """Kip adı (PX4 ya da ArduPilot takma adı) → PX4 kanonik adı; bilinmiyorsa ValueError."""
    a = str(ad or '').strip().upper()
    if a in PX4_MODLAR:
        return a
    if a in KIP_TAKMA:
        return KIP_TAKMA[a]
    if 'AUTO.' + a in PX4_MODLAR:
        return 'AUTO.' + a
    raise ValueError(f'Bilinmeyen PX4 uçuş kipi: {ad or "-"}')


def kip_kodla(ad):
    """PX4 kanonik adı → (base_mode, main, sub, custom_mode)."""
    main, sub = PX4_MODLAR[ad]
    return 1, main, sub, (main << 16) | (sub << 24)


def kip_adi(custom_mode):
    """HEARTBEAT.custom_mode → PX4 kip adı (bilinmeyen alt kip: 'AUTO.<n>')."""
    cm = int(custom_mode or 0)
    main, sub = (cm >> 16) & 0xFF, (cm >> 24) & 0xFF
    for ad, (m, s) in PX4_MODLAR.items():
        if m == main and (s == sub or (m != 4 and m != 3 and s == 0)):
            return ad
    if main == 3:
        return 'POSCTL'
    return f'AUTO.{sub}' if main == 4 else f'MODE{main}'


def kip_listesi(tip):
    return list(PX4_KIP_LISTESI.get(tip, PX4_KIP_LISTESI['multirotor']))


# ======================================================================
# Parametre dosyası (.params QGC / .parm ArduPilot / düz AD DEĞER)
# ======================================================================
PARAM_AD = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,15}$')
PARAM_METIN_AZAMI = 512 * 1024
PARAM_SAYI_AZAMI = 3000


def param_dosyasi_coz(metin):
    """Dosya metni → ([(AD, değer)], atlanan_satır). Biçimler: QGC .params (`sysid<TAB>compid<TAB>AD<TAB>değer<TAB>tip`), ArduPilot .parm
    (`AD değer` / `AD,değer`), `AD=değer`. # ve // yorumları atlanır. Aynı ad birden çok kez → son değer."""
    if metin is None:
        return [], 0
    if not isinstance(metin, str):
        raise ValueError('Parametre dosyası metin olmalı')
    if len(metin) > PARAM_METIN_AZAMI:
        raise ValueError('Parametre dosyası çok büyük (en çok 512 KB)')
    sonuc, atla = {}, 0
    for ham in metin.splitlines():
        s = ham.split('#', 1)[0].split('//', 1)[0].strip()
        if not s:
            continue
        parca = s.split('\t') if s.count('\t') >= 3 else re.split(r'[\s,=]+', s)
        parca = [p for p in parca if p != '']
        if len(parca) >= 5 and parca[0].isdigit() and parca[1].isdigit():   # QGC: sysid compid ad değer tip
            ad, deger = parca[2], parca[3]
        elif len(parca) >= 2:
            ad, deger = parca[0], parca[1]
        else:
            atla += 1
            continue
        try:
            v = float(deger)
        except ValueError:
            atla += 1
            continue
        if not PARAM_AD.match(ad) or not math.isfinite(v):
            atla += 1
            continue
        sonuc.pop(ad.upper(), None)
        sonuc[ad.upper()] = v
        if len(sonuc) > PARAM_SAYI_AZAMI:
            raise ValueError(f'Parametre dosyasında en çok {PARAM_SAYI_AZAMI} parametre olabilir')
    return list(sonuc.items()), atla


# PX4 tamsayı parametreleri PARAM_VALUE/PARAM_SET'te BAYT DÜZEYİNDE float'a gömülür (MAV_PROTOCOL_CAPABILITY_PARAM_ENCODE_BYTEWISE;
# ölçüldü: MAV_SYS_ID 1 → 1.4e-45). ArduPilot C-cast kullanır. Oturum içi çözümleme/kodlama burada; GCS'ye giden ham akış değişmez.
INT_TIPLERI = (1, 2, 3, 4, 5, 6)   # MAV_PARAM_TYPE_UINT8 … INT32


def param_coz(deger, ptype):
    if int(ptype or 0) in INT_TIPLERI:
        return float(struct.unpack('<i', struct.pack('<f', float(deger)))[0])
    return float(deger)


def param_kodla(deger, ptype):
    if int(ptype or 0) in INT_TIPLERI:
        return struct.unpack('<f', struct.pack('<i', int(round(float(deger)))))[0]
    return float(deger)


def deger_metni(v):
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 2 ** 31 else repr(v)


# ======================================================================
# Doğrulama (SimManager.ac)
# ======================================================================
def yigin_dogrula(stack, tip, cfg=None):
    """`stack` + `stack_cfg` {airframe?, params_text?, params_name?, speed?} → doğrulanmış sözlük. Hata ValueError (→ 400) / RuntimeError (→ 503)."""
    key = str(stack or YIGIN_VARSAYILAN).strip().lower()
    y = next((x for x in YIGINLAR if x['key'] == key), None)
    if y is None:
        raise ValueError(f'Bilinmeyen uçuş yığını: {stack}')
    if y['status'] != 'active':
        raise ValueError(f"{y['name']} yığını henüz desteklenmiyor: {y.get('reason') or ''}".strip())
    cfg = cfg if isinstance(cfg, dict) else {}
    params, atlanan = param_dosyasi_coz(cfg.get('params_text'))
    out = {'stack': key, 'name': y['name'], 'params': params, 'params_skipped': atlanan,
           'params_name': str(cfg.get('params_name') or '')[:120] or None}
    if key == 'ardupilot':
        return out
    if tip not in PX4_AIRFRAMES:
        raise ValueError(f"PX4 (SIH) bu dron tipini desteklemiyor: {tip} — desteklenen: {', '.join(PX4_TIPLER)}")
    secenek = PX4_AIRFRAMES[tip]
    af = cfg.get('airframe')
    if af in (None, ''):
        af = secenek[0][0]
    try:
        af = int(af)
    except (TypeError, ValueError):
        raise ValueError('stack_cfg.airframe SYS_AUTOSTART sayısı olmalı')
    hit = next((x for x in secenek if x[0] == af), None)
    if hit is None:
        raise ValueError(f"PX4 airframe {af} bu tip için yok (seçenekler: {', '.join(str(x[0]) for x in secenek)})")
    hiz = cfg.get('speed', 1)
    try:
        hiz = float(hiz if hiz is not None else 1)
    except (TypeError, ValueError):
        raise ValueError('stack_cfg.speed sayı olmalı')
    if hiz not in (0.5, 1.0, 2.0, 4.0):
        raise ValueError('stack_cfg.speed 0.5 | 1 | 2 | 4 olmalı (PX4_SIM_SPEED_FACTOR)')
    if not px4_var():
        raise RuntimeError(f'PX4 SITL ikilisi kurulu değil ({px4_ikili()}); docs/ucus-simulatoru.md §45.6')
    out.update(airframe=af, airframe_model=hit[1], airframe_name=hit[2], speed=hiz)
    return out


def ardupilot_parm_satirlari(yigin):
    """ArduPilot oturumunda yüklenen dosya → varsayilan.parm satırları (dron kaydının kalıcı parametrelerinden SONRA; ilk kalp atışında kayıtlılar
    yinelendiği için aynı adda kalıcı kayıt önceliklidir — kontrol düzeni §13.1 ile aynı kural)."""
    if not yigin or yigin.get('stack') != 'ardupilot' or not yigin.get('params'):
        return []
    return [f'# HEPGO yüklenen parametre dosyası: {yigin.get("params_name") or "-"}'] + [f'{a} {deger_metni(v)}' for a, v in yigin['params']]


# ======================================================================
# Süreç yönetimi
# ======================================================================
ORNEK_ARALIGI = range(70, 100)
MAV_PORT_BASI = 18600
HEPGO_SYSID = 1
_LOCK = '/tmp/px4_lock-{}'
# HEPGO varsayılan PX4 parametreleri (dosyadakiler bunların üstüne yazar)
# NAV_RCL_ACT 0 / COM_RCL_EXCEPT 7: sanal kumanda (MANUAL_CONTROL) kapatılınca ya da sekme arka plana düşünce "kumanda kaybı" failsafe'i
# (Hold → RTL) tetiklenmesin — ölçüldü: kalkışta sanal kumanda açıkken 5 sn Hold + RTL ile iniş. ArduPilot'ta RC override bırakılınca RC'ye döner.
PX4_TABAN = (('COM_RC_IN_MODE', 1), ('NAV_RCL_ACT', 0), ('COM_RCL_EXCEPT', 7), ('NAV_DLL_ACT', 0), ('COM_ARM_WO_GPS', 0), ('MAV_PROTO_VER', 2))

RC_MAVLINK = """#!/bin/sh
# HEPGO §45 (flightsim_px4 üretir): yalnız GCS bağlantısı, partner baştan HEPGO UDP soketi (14550'ye yayın yok; P1)
mavlink start -x -u $HEPGO_MAV_LOCAL -o $HEPGO_MAV_REMOTE -t 127.0.0.1 -r 4000000 -f
mavlink stream -r 50 -s GLOBAL_POSITION_INT -u $HEPGO_MAV_LOCAL
mavlink stream -r 50 -s ATTITUDE -u $HEPGO_MAV_LOCAL
mavlink stream -r 20 -s VFR_HUD -u $HEPGO_MAV_LOCAL
mavlink stream -r 20 -s SERVO_OUTPUT_RAW_0 -u $HEPGO_MAV_LOCAL
mavlink stream -r 10 -s RC_CHANNELS -u $HEPGO_MAV_LOCAL
mavlink stream -r 5 -s GPS_RAW_INT -u $HEPGO_MAV_LOCAL
mavlink stream -r 2 -s SYS_STATUS -u $HEPGO_MAV_LOCAL
"""
RC_SIMULATOR = """#!/bin/sh
# HEPGO §45 (flightsim_px4 üretir): commander başlamadan MAV_SYS_ID (P2), sonra PX4'ün kendi simülatör betiği
param set MAV_SYS_ID ${HEPGO_SYSID:-1}
. etc/init.d-posix/px4-rc.simulator
"""


def calisma_dizini(kimlik):
    return drone_sitl.calisma_dizini(kimlik) / 'px4'


def ulg_dosyalari(kimlik):
    d = calisma_dizini(kimlik) / 'log'
    if not d.is_dir():
        return []
    out = [f for f in d.rglob('*.ulg') if f.is_file()]
    out.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return out


def _ornek_bos(i):
    import fcntl
    try:
        fd = os.open(_LOCK.format(i), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _udp_bos(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


_ayrilan = set()


def ornek_sec(kullanilan=()):
    """(örnek, MAV yerel portu) — kilidi boş örnek + boş UDP portu."""
    mesgul = set(kullanilan) | {(v or {}).get('instance') for v in drone_sitl.YONETICI._bilgi.values()} | _ayrilan
    for i in ORNEK_ARALIGI:
        if i in mesgul or not _ornek_bos(i):
            continue
        port = MAV_PORT_BASI + (i - ORNEK_ARALIGI.start)
        if _udp_bos(port):
            return i, port
    return None, None


def baslat(kimlik, tip, yigin, lat, lon, irtifa, uzak_port, temiz=True, ulg=False, konsol=None):
    """PX4 SIH SITL sürecini başlatır ve drone_sitl.YONETICI'ye kaydeder (calisiyor_mu / durdur ortak). Dönüş: (bilgi, hata). Bloklar (~1,5 sn)."""
    kimlik = int(kimlik)
    konsol = konsol or (lambda *_: None)
    if drone_sitl.YONETICI.calisiyor_mu(kimlik):
        return drone_sitl.YONETICI.bilgi(kimlik), None
    if not px4_var():
        return None, f'PX4 SITL ikilisi kurulu değil ({px4_ikili()})'
    i, port = ornek_sec()
    if i is None:
        return None, 'Boş PX4 örneği / UDP portu bulunamadı (70…99)'
    _ayrilan.add(i)
    try:
        return _baslat(kimlik, tip, yigin, lat, lon, irtifa, uzak_port, temiz, ulg, konsol, i, port)
    finally:
        _ayrilan.discard(i)


def _baslat(kimlik, tip, yigin, lat, lon, irtifa, uzak_port, temiz, ulg, konsol, i, port):
    dizin = calisma_dizini(kimlik)
    try:
        dizin.mkdir(parents=True, exist_ok=True)
        if temiz:   # P4: parametre deposu + görev (dataman) + eski loglar
            for ad in ('parameters.bson', 'parameters_backup.bson', 'dataman'):
                (dizin / ad).unlink(missing_ok=True)
            shutil.rmtree(dizin / 'log', ignore_errors=True)
            shutil.rmtree(dizin / 'eeprom', ignore_errors=True)
        ek = dizin / 'hepgo'
        ek.mkdir(exist_ok=True)
        (ek / 'px4-rc.mavlink').write_text(RC_MAVLINK, encoding='utf-8')
        (ek / 'px4-rc.simulator').write_text(RC_SIMULATOR, encoding='utf-8')
    except OSError as e:
        return None, f'PX4 çalışma dizini hazırlanamadı: {e}'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PX4_', 'HEPGO_MAV_'))}
    env['PATH'] = f"{ek}:{env.get('PATH') or '/usr/bin:/bin'}"
    env.update(PX4_SYS_AUTOSTART=str(int(yigin['airframe'])), PX4_HOME_LAT=f'{float(lat):.7f}', PX4_HOME_LON=f'{float(lon):.7f}',
               PX4_HOME_ALT=f'{float(irtifa):.1f}', HEPGO_SYSID=str(HEPGO_SYSID), HEPGO_MAV_LOCAL=str(port), HEPGO_MAV_REMOTE=str(int(uzak_port)))
    if float(yigin.get('speed') or 1) != 1.0:
        env['PX4_SIM_SPEED_FACTOR'] = deger_metni(yigin['speed'])
    prm = dict(PX4_TABAN)
    prm['SDLOG_MODE'] = 0 if ulg else -1   # ULog: ARM→DISARM (rec.bin) ya da kapalı (disk)
    for a, v in yigin.get('params') or ():
        prm[a] = v   # dosya HEPGO tabanını ezer
    for a, v in prm.items():
        env[f'PX4_PARAM_{a}'] = deger_metni(v)
    komut = [str(px4_ikili()), '-d', '-i', str(i), str(px4_klasoru() / 'etc')]
    try:
        log = open(dizin / 'px4.log', 'w', encoding='utf-8')   # noqa: SIM115 — süreç ömrü boyunca
    except OSError:
        log = subprocess.DEVNULL
    try:
        p = subprocess.Popen(komut, cwd=str(dizin), env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return None, f'PX4 başlatılamadı: {e}'
    time.sleep(1.5)
    if p.poll() is not None:
        son = ''
        with contextlib.suppress(OSError):
            son = ' | '.join([s.strip() for s in (dizin / 'px4.log').read_text(errors='replace').splitlines() if s.strip()][-3:])
        return None, f'PX4 hemen sonlandı (çıkış kodu {p.returncode}).' + (f' Log: {son}' if son else '')
    bilgi = {'port': port, 'tip': tip, 'model': yigin.get('airframe_model'), 'dizin': str(dizin), 'pid': p.pid, 'sysid': HEPGO_SYSID,
             'lat': float(lat), 'lon': float(lon), 'ikili': str(px4_ikili()), 'stack': 'px4', 'instance': i, 'airframe': yigin['airframe']}
    drone_sitl.YONETICI.surec_kaydet(kimlik, p, bilgi)
    konsol(f'PX4 SITL başladı: {yigin.get("airframe_name")} (SYS_AUTOSTART {yigin["airframe"]}) örnek {i} udp:127.0.0.1:{port} (pid {p.pid})', 'basari')
    return bilgi, None


# ======================================================================
# UDP akışı (SimSession'ın TCP okuyucu/yazıcı arayüzü: read / write / is_closing / close)
# ======================================================================
class _Okuyucu:
    def __init__(self):
        self.q = asyncio.Queue()

    async def read(self, n=-1):   # noqa: ARG002 — StreamReader imzası
        return await self.q.get()


class _Yazici:
    def __init__(self):
        self.tr, self.hedef = None, None

    def write(self, data):
        if self.tr is not None and self.hedef is not None and not self.tr.is_closing():
            self.tr.sendto(data, self.hedef)

    def is_closing(self):
        return self.tr is None or self.tr.is_closing()

    def close(self):
        if self.tr is not None:
            self.tr.close()


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, ok, yz):
        self.ok, self.yz = ok, yz

    def datagram_received(self, data, addr):
        if self.yz.hedef is not None and addr[1] != self.yz.hedef[1]:
            return   # yalnız kendi PX4 örneğimiz
        self.ok.q.put_nowait(data)

    def connection_lost(self, exc):
        self.ok.q.put_nowait(b'')


async def udp_akisi(loop):
    """(okuyucu, yazıcı, yerel_port): 127.0.0.1'de geçici port; yazıcı hedefi PX4 başlayınca atanır."""
    ok, yz = _Okuyucu(), _Yazici()
    tr, _ = await loop.create_datagram_endpoint(lambda: _Proto(ok, yz), local_addr=('127.0.0.1', 0))
    yz.tr = tr
    return ok, yz, tr.get_extra_info('sockname')[1]


# ======================================================================
# Harekât paneli komutları (flightsim_hub.MavKomut PX4 uyarlaması)
# ======================================================================
class Px4MavKomut(flightsim_hub.MavKomut):
    def _modes(self):
        return {ad: kip_kodla(ad)[3] for ad in PX4_MODLAR}

    async def _set_mode(self, mode):
        try:
            ad = kip_coz(mode)
        except ValueError as e:
            raise RuntimeError(str(e))
        _, main, sub, _ = kip_kodla(ad)
        await self._cmd_long(176, (1, main, sub, 0, 0, 0, 0))
        return {'mode': ad}

    async def _goto(self, lat, lon, alt, speed):
        s = self.s
        home = (s.tele.get('home') or {}).get('alt')
        amsl = float(home if home is not None else s.tele.get('alt_msl') or 0) + float(alt)
        # MAV_CMD_DO_REPOSITION (192): PX4 AUTO.LOITER'a geçip hedefe gider (param2 bit0 kip değiştir)
        s._gonder(s.mav.command_int_encode(s.sysid, s.comp, 0, 192, 0, 0, float(speed or -1), 1, 0, float('nan'), int(lat * 1e7), int(lon * 1e7), amsl))
        return {'lat': lat, 'lon': lon, 'alt_rel_m': alt}

    async def _mission_upload(self, items, cruise_speed):
        s = self.s
        seq_items = [dict(i) for i in items]
        if cruise_speed:
            seq_items.insert(0, {'frame': 2, 'command': 178, 'param1': 1, 'param2': float(cruise_speed), 'param3': -1})
        off = len(seq_items) - len(items)
        self.mis_off = off
        n = len(seq_items)
        with s.bekleyici(('MISSION_REQUEST_INT', 'MISSION_REQUEST', 'MISSION_ACK')) as q:
            s._gonder(s.mav.mission_count_encode(s.sysid, s.comp, n, 0))
            while True:
                msg = await flightsim_hub._al(q, 5)
                if msg is None:
                    raise RuntimeError('Görev yükleme zaman aşımı')
                if msg.get_type() == 'MISSION_ACK':
                    if msg.type == 0:
                        return {'count': len(items), 'uploaded': n, 'offset': off}
                    raise RuntimeError(f'Dron görevi reddetti (MAV_MISSION_RESULT {msg.type})')
                if msg.seq >= n:
                    continue
                it = seq_items[msg.seq]
                s._gonder(s.mav.mission_item_int_encode(s.sysid, s.comp, msg.seq, int(it.get('frame', 6)), int(it.get('command', 16)), 1 if msg.seq == 0 else 0,
                                                        int(it.get('autocontinue', 1)), float(it.get('param1', 0)), float(it.get('param2', 0)),
                                                        float(it.get('param3', 0)), float(it.get('param4', 0)), int(it.get('x', 0)), int(it.get('y', 0)),
                                                        float(it.get('z', 0)), 0))

    async def _param_set(self, name, value, ptype):
        s = self.s
        ptype = int(ptype) if ptype else s.param_types.get(name)
        if not ptype:
            ptype = int((await self._param_get(name))['type'])
        with s.bekleyici(('PARAM_VALUE',), lambda m: str(m.param_id).rstrip('\x00') == name) as q:
            for _ in range(3):
                s._gonder(s.mav.param_set_encode(s.sysid, s.comp, name.encode(), param_kodla(value, ptype), ptype))
                v = await flightsim_hub._al(q, 2)
                if v is not None:
                    return {'name': name, 'value': v.param_value, 'type': v.param_type}
        raise RuntimeError('Parametre yazılamadı')

    async def execute(self, name, p):
        s = self.s
        p = p or {}
        if name == 'takeoff':
            await s.px4_kalkis(float(p.get('alt_rel_m') or 30))
            return {'ack': 0}
        if name == 'land':
            return await self._cmd_long(21, (0, 0, 0, float('nan'), float('nan'), float('nan'), float('nan')), 6)
        if name == 'rtl':
            return await self._cmd_long(20, (0, 0, 0, 0, 0, 0, 0), 6)
        if name == 'altitude_change':
            if not s.tele.get('lat'):
                raise RuntimeError('Konum bilinmiyor')
            return await self._goto(float(s.tele['lat']), float(s.tele['lon']), float(p['alt_rel_m']), None)
        if name == 'mission_set_current':
            s._gonder(s.mav.mission_set_current_encode(s.sysid, s.comp, int(p['seq']) + self.mis_off))
            return {'seq': int(p['seq'])}
        return await super().execute(name, p)


# ======================================================================
# Oturum
# ======================================================================
class Px4Session(flightsim.SimSession):
    """PX4 SIH SITL oturumu: ArduPilot SimSession'ının tüm yayın / UDP köprüsü / 3B / HUD / görev izleme / kayıt yolu aynen; farklar SITL açılışı
    (UDP akışı, PX4 süreci), ilk kalp atışı (ArduPilot PARAM_SET'leri yok), kip eşleme, kalkış/RTL/RC komutları ve desteklenmeyen komutların
    gerekçeli reddi (OZELLIKLER)."""

    def __init__(self, *a, yigin=None, **kw):
        super().__init__(*a, **kw)
        self.yigin = dict(yigin or {})
        self.ulg = bool(self.rec.get('bin'))
        self.rec = {'bin': False, 'ulg': self.ulg}   # .BIN akışı yok; ULog örnek dizinine
        self.param_izleyici = None                    # dron kaydının kalıcı (ArduPilot) parametreleri PX4'e yazılmaz
        self.sanal_montaj, self.hiz_olcegi = False, False
        self.montaj['virtual_mount'] = False
        self.arazi['serve'] = False
        self.komutcu = Px4MavKomut(self)
        self._kalkis_task = None
        self.speedup_istek = float(self.yigin.get('speed') or 1.0)
        self.guc.hiz_ayarla(self.speedup_istek)
        self.ulg_sonuc = None
        self._st_parca = {}   # STATUSTEXT.id → parçalar

    def to_dict(self, host=None):
        d = super().to_dict(host)
        d['stack'] = 'px4'
        d['stack_info'] = {'name': 'PX4', 'version': PX4_SURUM, 'build': px4_surum(), 'airframe': self.yigin.get('airframe'),
                           'airframe_model': self.yigin.get('airframe_model'), 'airframe_name': self.yigin.get('airframe_name'),
                           'speed': self.yigin.get('speed'), 'params_loaded': len(self.yigin.get('params') or ()),
                           'params_name': self.yigin.get('params_name'), 'gcs': 'QGroundControl',
                           'features': {k: {'ok': ok, 'note': n} for k, (ok, n) in OZELLIKLER.items()},
                           'ulog': self.ulg_sonuc}
        d['modes'] = kip_listesi(self.type)
        return d

    # ---- açılış ----
    async def _sitl_ac(self, temiz=True):
        if not flightsim.SITL_ENABLED:
            self.sitl['error'] = 'PX4 yığını gerçek SITL ister (HEPGO_SITL=0 sahte kipte yok)'
            self._olay(self.sitl['error'], 2)
            self._durum('HATA')
            return False
        loop = self.loop
        c = self.center
        y = self.yigin
        self._olay(f"PX4 SITL (SIH) başlatılıyor · {y.get('airframe_name')} (SYS_AUTOSTART {y.get('airframe')})"
                   + (f" · hız {y.get('speed'):g}×" if float(y.get('speed') or 1) != 1 else '') + f" · {c.get('name') or ''}", 6)
        ok, yz, yerel = await udp_akisi(loop)
        ev = self.ev_konumu()
        bilgi, err = await loop.run_in_executor(None, lambda: baslat(self.kimlik, self.type, y, ev['lat'], ev['lon'], c.get('alt') or flightsim.EV_IRTIFA,
                                                                     yerel, temiz=temiz, ulg=self.ulg, konsol=self._konsol))
        if not bilgi:
            yz.close()
            self.sitl['error'] = err or 'PX4 başlatılamadı'
            self._olay(self.sitl['error'], 2)
            self._durum('HATA')
            return False
        yz.hedef = ('127.0.0.1', int(bilgi['port']))
        self._tcp_r, self._tcp_w = ok, yz
        self.sitl.update(port=bilgi['port'], pid=bilgi['pid'], error=None, stack='px4', instance=bilgi['instance'])
        self._tcp_task = loop.create_task(self._tcp_okuyucu())
        self._gcs_heartbeat()   # PX4 GCS bağlantısına ilk paket
        if y.get('params'):
            self._olay(f"Parametre dosyası{' ' + y['params_name'] if y.get('params_name') else ''}: {len(y['params'])} parametre açılışta yüklendi (PX4_PARAM_*)"
                       + (f", {y['params_skipped']} satır atlandı" if y.get('params_skipped') else ''), 6)
        self._olay(f"PX4 bağlantısı: udp:127.0.0.1:{bilgi['port']} (örnek {bilgi['instance']}, sysid {HEPGO_SYSID}) — GCS için QGroundControl önerilir", 6)
        self._heartbeat_alindi = False
        self._durum('HAZIR')
        return True

    def _ilk_heartbeat(self):
        self._akis_iste()
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 512, 0, 242, 0, 0, 0, 0, 0, 0))   # HOME bir kez
        self._olay('PX4 kalp atışı alındı; veri akışı istendi (ATTITUDE/konum 50 Hz)', 6)
        if float(self.world.get('wind_ms') or 0) > 0:
            self._olay('PX4 SIH fiziğinde rüzgâr yok: seçilen rüzgâr yalnız görsel/HUD (SIM_WIND_* ArduPilot\'a özgü)', 4)
        if self._reset_bekliyor:
            self._reset_bekliyor = False
            self._kopru_kalp_durdur()
        self._olay(f'Ev irtifası {float(self.center.get("alt") or flightsim.EV_IRTIFA):.1f} m MSL (SIH_LOC_H0)', 6)
        if self.alt_not:
            self._olay(self.alt_not, 4)

    def _akis_iste(self, tam=True):
        self._akis_son = time.time()
        for msgid, us in ((30, 20000), (33, 20000), (74, 50000), (36, 50000), (65, 100000), (1, 500000), (24, 200000), (242, 5000000), (245, 1000000)):
            self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 511, 0, msgid, us, 0, 0, 0, 0, 0))

    def _ruzgar_yaz(self, d=None, yalniz_hiz=False):   # SIH'de rüzgâr yok: yalnız tele (HUD/görsel)
        self.tele['wind_spd'], self.tele['wind_dir'] = self.ruzgar_simdi()

    def _isle(self, m):
        t = m.get_type()
        if t == 'COMMAND_ACK' and m.command == 511:   # bazı akışları PX4 tanımaz: ArduPilot'taki REQUEST_DATA_STREAM'e düşüş yok
            if self._bekleyenler:
                self._dagit(m)
            return
        if t == 'COMMAND_ACK' and m.command == 400 and m.result not in (0, 5) and self._kalkis_task is not None and not self._kalkis_task.done():
            if self._bekleyenler:   # kalkış ARM'ı EKF hazır olana dek yineliyor: her ret satırı yerine PX4'ün kendi gerekçe metni yeter
                self._dagit(m)
            return
        if t == 'STATUSTEXT':   # PX4 uzun metni parçalar (STATUSTEXT.id + chunk_seq; parça 50 karakter) → tek satır
            metin = str(m.text).rstrip('\x00')
            pid = int(getattr(m, 'id', 0) or 0)
            if pid:
                parca = self._st_parca.setdefault(pid, [])
                parca.append(metin)
                if len(metin) >= 50 and len(parca) < 8:
                    return
                metin = ''.join(self._st_parca.pop(pid, parca))
            m.text = metin.strip()
        if t == 'PARAM_VALUE':   # bayt düzeyi tamsayı → gerçek değer (izleyiciler, params.param dökümü, harekât paneli)
            with contextlib.suppress(Exception):
                m.param_value = param_coz(m.param_value, m.param_type)
        super()._isle(m)
        if t == 'HEARTBEAT' and m.type not in (6, 18) and m.get_srcSystem() == self.sysid:
            self.tele['mode'] = kip_adi(m.custom_mode)

    async def _kopru_kalp(self):
        """§35 reset boşluğunda GCS'ye kalp atışı — PX4 otopilot kimliğiyle (MAV_AUTOPILOT_PX4 = 12)."""
        d = flightsim._dialect()
        enc = d.MAVLink(None, srcSystem=int(self.sysid or 1), srcComponent=int(self.comp or 1))
        vt = self.vtype if self.vtype is not None else flightsim._varsayilan_vtype(self.type)
        try:
            cm = kip_kodla(kip_coz(self.tele.get('mode') or 'AUTO.LOITER'))[3]
        except ValueError:
            cm = 0
        try:
            while self.state != 'KAPANDI' and not self._heartbeat_alindi:
                with contextlib.suppress(Exception):
                    self._gcs_gonder(enc.heartbeat_encode(vt, 12, 1, cm, d.MAV_STATE_BOOT).pack(enc))
                    enc.seq = (enc.seq + 1) % 256
                    self.kopru_kalp_sayac += 1
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    def _mod_gonder(self, mode):
        try:
            ad = kip_coz(mode)
        except ValueError as e:
            raise flightsim.SimHata('invalid', str(e))
        base, main, sub, _ = kip_kodla(ad)
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 176, 0, base, main, sub, 0, 0, 0, 0))
        return ad

    # ---- komutlar ----
    async def px4_kalkis(self, alt):
        """ARM (ön uçuş denetimleri/EKF hazır olana dek ≤ 25 sn yinelenir) → MAV_CMD_NAV_TAKEOFF (param7 AMSL = ev + alt). Sabit kanatta pist kalkışı."""
        te = self.tele
        if not te.get('armed'):
            bitis = time.time() + 25
            while time.time() < bitis and self.state == 'HAZIR' and not te.get('armed'):
                self._gonder(self.mav.command_long_encode(self.sysid, self.comp, 400, 0, 1, 0, 0, 0, 0, 0, 0))
                for _ in range(10):
                    await asyncio.sleep(0.1)
                    if te.get('armed'):
                        break
            if not te.get('armed'):
                raise RuntimeError('PX4 ARM edilemedi (ön uçuş denetimi; olay şeridindeki PX4 mesajlarına bakın)')
        home = (te.get('home') or {}).get('alt')
        amsl = float(home if home is not None else te.get('alt_msl') or 0) + float(alt)
        nan = float('nan')
        cmd = 84 if self.type == 'vtol' else 22   # VTOL: MAV_CMD_NAV_VTOL_TAKEOFF
        self._gonder(self.mav.command_long_encode(self.sysid, self.comp, cmd, 0, 0, 0, 0, nan, nan, nan, amsl))
        self._olay(f'PX4 kalkış: ARM + {"NAV_VTOL_TAKEOFF" if cmd == 84 else "NAV_TAKEOFF"} {alt:g} m (AMSL {amsl:.0f} m)', 6)
        return amsl

    async def _kalkis_gorevi(self, alt):
        try:
            if self.type == 'sabit_kanat':
                self._launch_yay('armed', alt=alt)
            await self.px4_kalkis(alt)
            if self.type == 'sabit_kanat':
                self._launch_yay('launch')
                bitis = time.time() + 90
                while time.time() < bitis and self.state == 'HAZIR' and float(self.tele.get('alt_rel') or 0) < 1:
                    await asyncio.sleep(0.1)
                if float(self.tele.get('alt_rel') or 0) >= 1:
                    self._launch_yay('released', speed_kmh=round(float(self.tele.get('groundspeed') or 0) * 3.6, 1))
        except asyncio.CancelledError:
            return
        except Exception as e:   # noqa: BLE001
            self._olay(f'Kalkış: {e}'[:200], 3)

    def _rc_gonder(self, ch):
        """RC kanalları (µs; ArduPilot AETR: 1 roll, 2 pitch, 3 gaz, 4 yaw) → MANUAL_CONTROL (x ileri, y sağ, z gaz 0…1000, r sapma). 8×0: gönderme."""
        if not any(ch):
            return False

        def eksen(v, ters=False):
            if not v:
                return 0
            k = max(-1000, min(1000, int(round((float(v) - 1500.0) * 2))))
            return -k if ters else k
        z = 500 if not ch[2] else max(0, min(1000, int(round(float(ch[2]) - 1000))))
        self._gonder(self.mav.manual_control_encode(self.sysid, eksen(ch[1], ters=True), eksen(ch[0]), z, eksen(ch[3]), 0))
        return True

    async def komut(self, name, params, kaynak=None):
        p = params if isinstance(params, dict) else {}
        if name in DESTEKSIZ_KOMUT and name in flightsim.KOMUTLAR:
            raise flightsim.SimHata('invalid', f'PX4\'te desteklenmiyor: {OZELLIKLER[DESTEKSIZ_KOMUT[name]][1]}')
        if name == 'wind':
            w = await self.ruzgar_degistir(p)
            self._olay('PX4 SIH: rüzgâr fiziği yok — yalnız görsel/HUD', 4)
            return {'ok': True, 'wind': w, 'physics': False}
        if name not in ('mode', 'takeoff', 'rtl', 'rc', 'arm', 'disarm'):
            return await super().komut(name, params, kaynak)
        self._kapi_denetle(name)
        if self.state != 'HAZIR':
            raise flightsim.SimHata('invalid', 'Oturum hazır değil')
        if not self._heartbeat_alindi:
            raise flightsim.SimHata('invalid', 'PX4 henüz kalp atışı göndermedi')
        enc, s, c = self.mav, self.sysid, self.comp
        if name == 'mode':
            return {'ok': True, 'mode': self._mod_gonder(p.get('mode'))}
        if name == 'arm':
            self._gonder(enc.command_long_encode(s, c, 400, 0, 1, 0, 0, 0, 0, 0, 0))
        elif name == 'disarm':
            self._gonder(enc.command_long_encode(s, c, 400, 0, 0, 0, 0, 0, 0, 0, 0))
        elif name == 'rtl':
            self._gonder(enc.command_long_encode(s, c, 20, 0, 0, 0, 0, 0, 0, 0, 0))
        elif name == 'rc':
            self._rc_gonder(flightsim._rc_dogrula(p.get('ch')))
        elif name == 'takeoff':
            alt = p.get('alt')
            if alt is None:
                alt = 50.0 if self.type == 'sabit_kanat' else 10.0
            if isinstance(alt, bool) or not isinstance(alt, (int, float)) or not (1 <= alt <= 1000):
                raise flightsim.SimHata('invalid', 'takeoff.alt 1…1000 m olmalı')
            if self._kalkis_task is not None and not self._kalkis_task.done():
                self._kalkis_task.cancel()
            self._kalkis_task = self.loop.create_task(self._kalkis_gorevi(float(alt)))
        return {'ok': True}

    async def rc(self, ch):
        now = time.time()
        if now - self._rc_son < flightsim.RC_HZ_MIN_ARALIK and any(ch or ()):
            return
        self._rc_son = now
        if any(ch or ()) and self.komut_kapisi is not None and self.komut_kapisi('rc'):
            return   # §33 karşılaşma kapısı (ArduPilot rc() ile aynı)
        if self.state == 'HAZIR' and self._heartbeat_alindi:
            self._rc_gonder(flightsim._rc_dogrula(ch))

    async def reset(self):
        if self._kalkis_task is not None and not self._kalkis_task.done():
            self._kalkis_task.cancel()
        await super().reset()

    async def _bin_kaydet(self, ara=False):
        """ULog (.ulg) Uçuş Logları'na henüz yüklenmez (§45.3): kapanışta en yeni dosyanın yolu olay şeridine + to_dict.stack_info.ulog."""
        if not self.ulg or ara:
            return
        try:
            fs = await asyncio.get_running_loop().run_in_executor(None, ulg_dosyalari, self.kimlik)
        except Exception:   # noqa: BLE001
            fs = []
        if fs:
            self.ulg_sonuc = {'path': str(fs[0]), 'size': fs[0].stat().st_size}
            self._olay(f'PX4 ULog kaydı: {fs[0].name} ({fs[0].stat().st_size // 1024} KB) — örnek dizininde; Uçuş Logları .ulg yüklemesi henüz yok', 6)
        else:
            self._olay('PX4 ULog kaydı yok (ARM süresi olmadı)', 6)

    async def _temizle(self):
        if self._kalkis_task is not None and not self._kalkis_task.done():
            self._kalkis_task.cancel()
        await super()._temizle()
