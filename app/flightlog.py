"""ArduPilot DataFlash (.bin / .log) ve MAVLink telemetri kaydı (.tlog) uçuş logu analizi.

İkili .BIN hızlı akış okuyucuyla (dataflash; sonuç pymavlink yoluyla birebir aynı — docs/ucus-simulatoru.md §8.4), metin .log
pymavlink ile, .tlog app/tlog.py ile (MAVLink → aynı şema; §8.6) okunur; analiz sunucuda alt süreçte çalışır (flight_analysis). Özet değerler, zaman serileri (grafikler için seyreltilmiş), uçuş izi,
modlar, olaylar/hatalar ve otomatik değerlendirme bulguları JSON olarak döner. Alan adları ArduPilot
sürümüne göre değiştiğinden (ör. BAT.RemPct, VIBE.Clip / Clip0..2, XKF2 / NKF2) okuma toleranslıdır.
"""
import math
import re
from datetime import datetime, timezone

from pymavlink import mavutil

MAX_POINTS = 700          # grafik başına nokta
MAX_TRACK = 1500          # uçuş izi noktası
MAX_MESSAGES = 200

TYPES = ['MSG', 'MODE', 'GPS', 'POS', 'BAT', 'CURR', 'BARO', 'CTUN', 'ARSP', 'ATT', 'VIBE', 'ERR', 'EV',
         'XKF2', 'NKF2', 'STAT', 'ARM', 'ORGN', 'PARM']

# ArduPilot LogErrorSubsystem
ERR_SUBSYS = {
    1: 'Ana sistem', 2: 'Radyo', 3: 'Pusula', 4: 'Optik akış', 5: 'Radyo failsafe', 6: 'Batarya failsafe',
    7: 'GPS failsafe', 8: 'GCS failsafe', 9: 'Çit (fence) failsafe', 10: 'Uçuş modu', 11: 'GPS',
    12: 'Çarpma algılama', 13: 'Flip', 14: 'Autotune', 15: 'Paraşüt', 16: 'EKF kontrol', 17: 'EKF failsafe',
    18: 'Barometre', 19: 'İşlemci', 20: 'ADSB failsafe', 21: 'Arazi verisi', 22: 'Navigasyon',
    23: 'Arazi failsafe', 24: 'EKF birincil değişimi', 25: 'İtki kaybı', 26: 'Sensör failsafe',
    27: 'Sızıntı failsafe', 28: 'Pilot girdisi', 29: 'Titreşim failsafe', 30: 'Dahili hata',
    31: 'Ölü hesap failsafe',
}
# ArduPilot LogEvent
EV_TEXT = {
    10: 'Motorlar kurmaya alındı (ARM)', 11: 'Motorlar devre dışı (DISARM)', 15: 'Otomatik ARM',
    17: 'İniş algılandı (olası)', 18: 'İniş tamamlandı', 19: 'GPS kaybedildi', 25: 'Ev konumu ayarlandı',
    28: 'Havada', 30: 'Autotune başladı', 31: 'Autotune kapatıldı', 33: 'Autotune başarılı', 34: 'Autotune başarısız',
    38: 'Trim kaydedildi', 41: 'Çit (fence) etkin', 42: 'Çit (fence) devre dışı', 49: 'Paraşüt devre dışı',
    50: 'Paraşüt etkin', 51: 'Paraşüt açıldı', 52: 'İniş takımı açıldı', 53: 'İniş takımı toplandı',
    54: 'Motor acil durdurma', 55: 'Motor acil durdurma kaldırıldı', 56: 'Motor kilidi (interlock) kapalı',
    57: 'Motor kilidi (interlock) açık', 60: 'EKF irtifa sıfırlama', 61: 'İniş pilot tarafından iptal edildi',
    62: 'EKF yön (yaw) sıfırlama', 63: 'ADSB kaçınma etkin', 64: 'ADSB kaçınma devre dışı',
    67: 'Birincil GPS değişti',
}
ARM_TEXT = {1: 'Motorlar kurmaya alındı (ARM)', 0: 'Motorlar devre dışı (DISARM)'}
WARN_RE = re.compile(r'failsafe|crash|error|fail(ed|ure)?\b|warning|\bbad\b|\blost\b|glitch|emergency|critical|'
                     r'prearm|unhealthy|breach|low batt|battery low|\bestop', re.I)


def _haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _thin(points, limit):
    if len(points) <= limit:
        return points
    step = len(points) / limit
    out = [points[int(i * step)] for i in range(limit)]
    out.append(points[-1])
    return out


def _num(v):
    return None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v


def _r(v, n=1):
    return None if v is None else round(v, n)


def _mode_names(firmware):
    fw = (firmware or '').lower()
    if 'plane' in fw:
        mapping = mavutil.mode_mapping_apm
    elif 'copter' in fw or 'heli' in fw:
        mapping = mavutil.mode_mapping_acm
    elif 'rover' in fw:
        mapping = mavutil.mode_mapping_rover
    elif 'sub' in fw:
        mapping = mavutil.mode_mapping_sub
    else:
        mapping = mavutil.mode_mapping_apm
    if not mapping:
        return {}
    # pymavlink sürümüne göre eşleme numara→ad ya da ad→numara olabilir
    return dict(mapping) if isinstance(next(iter(mapping)), int) else {v: k for k, v in mapping.items()}


def _intervals(flags):
    """[(t, bool)] → [(başlangıç, bitiş)] True aralıkları."""
    out, start = [], None
    for t, on in flags:
        if on and start is None:
            start = t
        elif not on and start is not None:
            out.append((start, t))
            start = None
    if start is not None and flags:
        out.append((start, flags[-1][0]))
    return out


def _in(intervals, t):
    return any(a <= t <= b for a, b in intervals)


def analyze(path, ilerleme=None):
    """Uçuş logu analizi. İkili DataFlash (.BIN) → akış okuyucu (dataflash, numpy; 700 MB'lık logda ~10 sn / ~0,4 GB);
    metin .log → pymavlink (iki yolun sonucu BİREBİR aynıdır; tests/test_binanalyze); MAVLink telemetri kaydı (.tlog; Mission Planner /
    QGroundControl) → app/tlog.py (MAVLink mesajlarından aynı şemaya eşleme). `ilerleme(yüzde)` 0…100.
    Sunucuda ALT SÜREÇTE çalıştırılır (flight_analysis; `python -m app.flightlog analyze`)."""
    from . import dataflash
    if str(path).lower().endswith('.tlog'):
        from . import tlog
        return tlog.analiz(path, ilerleme)
    if dataflash.ikili_mi(path):
        return _analyze_hizli(path, ilerleme)
    return _analyze_pymavlink(path, ilerleme)


def _analyze_pymavlink(path, ilerleme=None):
    log = mavutil.mavlink_connection(str(path), zero_time_base=False)
    t0 = None
    s = {k: [] for k in ('alt', 'gs', 'as', 'volt', 'curr', 'vx', 'vy', 'vz', 'roll', 'droll', 'pitch', 'dpitch',
                         'sats', 'hdop', 'wind', 'thr')}
    gps_pts, pos_pts = [], []
    firmware = board = None
    msgs, modes, events, errors = [], [], [], []
    arm_flags, stat_flags = [], []
    bat = {'first': None, 'last': None, 'min_v': None, 'max_a': 0.0, 'mah': None, 'wh': None, 'pct': None}
    clips = {}
    wind_dirs = []
    origin = None
    params = 0
    gps_time_ref = None   # (log saniyesi, unix zamanı)
    count = 0

    say = 0
    while True:
        m = log.recv_match(type=TYPES)
        if m is None:
            break
        say += 1
        if ilerleme and say % 20000 == 0:
            ilerleme(min(99, int(getattr(log, 'percent', 0) or 0)))
        tp = m.get_type()
        if tp == 'PARM':
            params += 1
            continue
        tus = getattr(m, 'TimeUS', None)
        if tus is None:
            tms = getattr(m, 'TimeMS', None)
            if tms is None:
                continue
            tus = tms * 1000
        t = tus / 1e6
        if t0 is None:
            t0 = t
        t -= t0
        count += 1

        if tp == 'MSG':
            text = str(m.Message)
            if firmware is None and text.startswith(('ArduPlane', 'ArduCopter', 'ArduRover', 'ArduSub', 'ArduHeli',
                                                     'Blimp', 'AntennaTracker')):
                firmware = text
            elif board is None and ' ' in text and any(text.startswith(b) for b in (
                    'Pixhawk', 'CubeOrange', 'CubeBlack', 'CubePurple', 'CubeYellow', 'Matek', 'fmuv', 'PX4v',
                    'Durandal', 'KakuteH', 'SpeedyBee', 'Holybro', 'MicoAir', 'mRo', 'Pixracer', 'omnibus')):
                board = text.split(' ')[0]
            if len(msgs) < MAX_MESSAGES:
                msgs.append({'t': _r(t), 'text': text, 'warn': bool(WARN_RE.search(text))})
        elif tp == 'MODE':
            modes.append((t, getattr(m, 'ModeNum', getattr(m, 'Mode', None)), getattr(m, 'Rsn', None)))
        elif tp == 'GPS':
            if getattr(m, 'I', 0) not in (0, None):
                continue
            st = getattr(m, 'Status', 0)
            if st >= 3:
                gps_pts.append((t, m.Lat, m.Lng, m.Spd))
                s['gs'].append([t, m.Spd])
                if gps_time_ref is None and getattr(m, 'GWk', 0) > 0:
                    unix = 315964800 + m.GWk * 604800 + m.GMS / 1000.0 - 18   # GPS→UTC (18 sn artık saniye)
                    gps_time_ref = (t, unix)
            s['sats'].append([t, getattr(m, 'NSats', 0)])
            s['hdop'].append([t, getattr(m, 'HDop', 0)])
        elif tp == 'POS':
            rel = _num(getattr(m, 'RelHomeAlt', None))
            pos_pts.append((t, m.Lat, m.Lng, rel))
            if rel is not None:
                s['alt'].append([t, rel])
        elif tp in ('BAT', 'CURR'):
            if getattr(m, 'Inst', getattr(m, 'Instance', 0)) not in (0, None):
                continue
            v, a = _num(getattr(m, 'Volt', None)), _num(getattr(m, 'Curr', None))
            if v is None or v <= 0.5:
                continue
            s['volt'].append([t, v])
            if a is not None:
                s['curr'].append([t, a])
                bat['max_a'] = max(bat['max_a'], a)
            bat['first'] = bat['first'] or v
            bat['last'] = v
            bat['min_v'] = v if bat['min_v'] is None else min(bat['min_v'], v)
            bat['mah'] = _num(getattr(m, 'CurrTot', None))
            e = _num(getattr(m, 'EnrgTot', None))
            bat['wh'] = e if e is not None else bat['wh']
            pct = getattr(m, 'RemPct', None)
            bat['pct'] = pct if pct is not None else bat['pct']
        elif tp == 'BARO' and not pos_pts:
            if getattr(m, 'I', 0) in (0, None):
                s['alt'].append([t, m.Alt])
        elif tp == 'ARSP':
            if getattr(m, 'I', 0) in (0, None):
                s['as'].append([t, m.Airspeed])
        elif tp == 'CTUN':
            thr = getattr(m, 'ThO', None)
            if thr is None:
                thr = getattr(m, 'ThrOut', None)
                thr = thr / 100.0 if thr is not None and thr > 1.5 else thr
            if thr is not None:
                s['thr'].append([t, thr * 100 if thr <= 1.5 else thr])
            aspd = _num(getattr(m, 'As', None))
            if aspd is not None and 'ARSP' not in log.messages:
                s['as'].append([t, aspd])
        elif tp == 'ATT':
            s['roll'].append([t, m.Roll])
            s['pitch'].append([t, m.Pitch])
            s['droll'].append([t, m.DesRoll])
            s['dpitch'].append([t, m.DesPitch])
        elif tp == 'VIBE':
            if getattr(m, 'IMU', 0) not in (0, None):
                continue
            s['vx'].append([t, m.VibeX])
            s['vy'].append([t, m.VibeY])
            s['vz'].append([t, m.VibeZ])
            for f in ('Clip', 'Clip0', 'Clip1', 'Clip2'):
                if hasattr(m, f):
                    clips[f] = getattr(m, f)
        elif tp in ('XKF2', 'NKF2'):
            if getattr(m, 'C', 0) != 0:
                continue
            vn, ve = m.VWN, m.VWE
            s['wind'].append([t, math.hypot(vn, ve)])
            wind_dirs.append((vn, ve))
        elif tp == 'ERR':
            errors.append({'t': _r(t), 'subsys': m.Subsys, 'code': m.ECode,
                           'text': ERR_SUBSYS.get(m.Subsys, f'Alt sistem {m.Subsys}'),
                           'resolved': m.ECode == 0})
        elif tp == 'EV':
            events.append({'t': _r(t), 'id': m.Id, 'text': EV_TEXT.get(m.Id, f'Olay #{m.Id}')})
            if m.Id in (10, 11):
                arm_flags.append((t, m.Id == 10))
        elif tp == 'ARM':
            arm_flags.append((t, bool(m.ArmState)))
        elif tp == 'STAT':
            stat_flags.append((t, bool(getattr(m, 'isFlying', 0))))
        elif tp == 'ORGN':
            if getattr(m, 'Type', 0) == 0 and origin is None:
                origin = (m.Lat, m.Lng, m.Alt)

    if t0 is None or count == 0:
        raise ValueError('Logda okunabilir uçuş verisi bulunamadı')
    return _sonuclandir(s, gps_pts, pos_pts, firmware, board, msgs, modes, events, errors, arm_flags, stat_flags, bat, clips,
                        wind_dirs, origin, params, gps_time_ref)


def _sonuclandir(s, gps_pts, pos_pts, firmware, board, msgs, modes, events, errors, arm_flags, stat_flags, bat, clips,
                 wind_dirs, origin, params, gps_time_ref, mod_adlari=None, takip=None, kaynak=None):
    """Toplanan ham dizilerden özet + bulgular + seyreltilmiş seriler (metin .log ve .tlog ortak; app/tlog.py).
    `mod_adlari`: numara → ad (verilmezse firmware'den); `takip`: (yatış farkları, yunuslama farkları) — tlog'da istenen/gerçekleşen
    tutum farklı hızlarda gelir, zamana göre eşlenmiş farklar dışarıda hesaplanır; `kaynak`: 'tlog' → bulgularda ERR yerine STATUSTEXT önemi."""
    track = []
    duration = max((v[-1][0] for v in s.values() if v), default=0)
    if gps_pts:
        duration = max(duration, gps_pts[-1][0])

    # Kurma (ARM) aralıkları; log kurulu başladıysa (ilk kayıt DISARM) başlangıç kurulu kabul edilir.
    arm_flags.sort()
    if arm_flags and not arm_flags[0][1]:
        arm_flags.insert(0, (0.0, True))
    armed = _intervals(arm_flags + [(duration, arm_flags[-1][1])] if arm_flags else [])

    # Uçuş aralıkları: STAT.isFlying (Plane) varsa o; yoksa kurulu iken irtifa/hız sezgisi.
    if stat_flags:
        flying = _intervals(stat_flags + [(duration, stat_flags[-1][1])])
    else:
        rel_by_t = [(p[0], p[3]) for p in pos_pts if p[3] is not None]
        gs_by_t = {round(p[0], 1): p[3] for p in gps_pts}
        flags = []
        for tt, rel in rel_by_t:
            on = (rel > 2.0 or (gs_by_t.get(round(tt, 1)) or 0) > 4.0) and (not armed or _in(armed, tt))
            flags.append((tt, on))
        flying = [iv for iv in _intervals(flags) if iv[1] - iv[0] > 3]
    flight_s = sum(b - a for a, b in flying)
    armed_s = sum(b - a for a, b in armed)
    in_air = (lambda tt: _in(flying, tt)) if flying else (lambda tt: True)

    # Konum: ev = ORGN ya da ilk geçerli GPS
    home = origin or ((gps_pts[0][1], gps_pts[0][2], None) if gps_pts else None)
    distance = 0.0
    max_home = 0.0
    prev = None
    for tt, lat, lng, _spd in gps_pts:
        if in_air(tt):
            if prev:
                d = _haversine(prev, (lat, lng))
                if d < 500:        # GPS sıçramalarını mesafeye katma
                    distance += d
            prev = (lat, lng)
            if home:
                max_home = max(max_home, _haversine(home, (lat, lng)))
        track.append([round(lat, 7), round(lng, 7), 1 if in_air(tt) else 0])
    if not track and pos_pts:
        track = [[round(p[1], 7), round(p[2], 7), 1 if in_air(p[0]) else 0] for p in pos_pts]

    def stat(key, fn, only_air=True):
        vals = [v for tt, v in s[key] if v is not None and (not only_air or in_air(tt))]
        return fn(vals) if vals else None

    mean = lambda v: sum(v) / len(v)
    # Dikey hız: gürültüyü azaltmak için ~1 sn'lik pencerelerle
    climb = []
    alt = s['alt']
    j = 0
    for i in range(1, len(alt)):
        while alt[i][0] - alt[j][0] > 1.0:
            j += 1
        if j and in_air(alt[i][0]):
            k = j - 1
            climb.append((alt[i][1] - alt[k][1]) / (alt[i][0] - alt[k][0]))
    track_err = lambda des, act: [a[1] - d[1] for d, a in zip(s[des], s[act]) if in_air(a[0])]
    if takip is not None:
        track_err = lambda des, act: [e for tt, e in takip[0 if des == 'droll' else 1] if in_air(tt)]
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v)) if v else None

    # Modlar
    names = mod_adlari if mod_adlari is not None else _mode_names(firmware)
    mode_rows = []
    for i, (tt, num, rsn) in enumerate(modes):
        end = modes[i + 1][0] if i + 1 < len(modes) else duration
        mode_rows.append({'t': _r(tt), 'name': names.get(num, f'Mod {num}'), 'dur': _r(end - tt), 'reason': rsn})

    # Rüzgâr yönü (esilen yön, derece)
    wind_dir = None
    if wind_dirs and (stat('wind', mean) or 0) >= 0.5:
        vn = mean([w[0] for w in wind_dirs])
        ve = mean([w[1] for w in wind_dirs])
        wind_dir = round((math.degrees(math.atan2(-ve, -vn)) + 360) % 360)

    takeoff = flying[0][0] if flying else None
    landing = flying[-1][1] if flying else None
    to_utc = None
    if gps_time_ref:
        to_utc = lambda tt: datetime.fromtimestamp(gps_time_ref[1] + (tt - gps_time_ref[0]), timezone.utc).isoformat()

    summary = {
        'firmware': firmware, 'board': board, 'params': params,
        'vehicle': (firmware or 'Bilinmiyor').split(' ')[0],
        'start_utc': to_utc(0) if to_utc else None,
        'takeoff_utc': to_utc(takeoff) if to_utc and takeoff is not None else None,
        'landing_utc': to_utc(landing) if to_utc and landing is not None else None,
        'takeoff_t': _r(takeoff), 'landing_t': _r(landing),
        'duration_s': _r(duration), 'armed_s': _r(armed_s), 'flight_s': _r(flight_s), 'flights': len(flying),
        'distance_m': round(distance), 'max_home_m': round(max_home),
        'home': {'lat': home[0], 'lng': home[1], 'alt': home[2]} if home else None,
        'alt_max': _r(stat('alt', max)), 'alt_avg': _r(stat('alt', mean)),
        'gs_max': _r(stat('gs', max)), 'gs_avg': _r(stat('gs', mean)),
        'as_max': _r(stat('as', max)), 'as_avg': _r(stat('as', mean)),
        'climb_max': _r(max(climb) if climb else None), 'sink_max': _r(-min(climb) if climb else None),
        'roll_max': _r(stat('roll', lambda v: max(abs(x) for x in v))),
        'pitch_max': _r(stat('pitch', lambda v: max(abs(x) for x in v))),
        'roll_err_rms': _r(rms(track_err('droll', 'roll'))), 'pitch_err_rms': _r(rms(track_err('dpitch', 'pitch'))),
        'thr_avg': _r(stat('thr', mean)),
        'bat_start_v': _r(bat['first'], 2), 'bat_end_v': _r(bat['last'], 2), 'bat_min_v': _r(bat['min_v'], 2),
        'bat_max_a': _r(bat['max_a']), 'bat_avg_a': _r(stat('curr', mean)),
        'bat_used_mah': _r(bat['mah'], 0), 'bat_used_wh': _r(bat['wh']), 'bat_end_pct': bat['pct'],
        'sats_min': stat('sats', min), 'sats_avg': _r(stat('sats', mean)), 'hdop_max': _r(stat('hdop', max), 2),
        'vibe_max': [_r(stat(k, max, False)) for k in ('vx', 'vy', 'vz')],
        'clips': sum(clips.values()) if clips else 0,
        'wind_avg': _r(stat('wind', mean)), 'wind_max': _r(stat('wind', max)), 'wind_dir': wind_dir,
    }

    result = {
        'summary': summary,
        'findings': _findings(summary, errors, msgs, kaynak),
        'modes': mode_rows,
        'events': events[:MAX_MESSAGES],
        'errors': errors,
        'messages': msgs,
        'flying': [[_r(a), _r(b)] for a, b in flying],
        'track': _thin(track, MAX_TRACK),
        'series': {k: [[_r(t), _r(v, 2)] for t, v in _thin(vals, MAX_POINTS)] for k, vals in s.items()},
    }
    return result


# ---------- Hızlı analiz (ikili DataFlash; dataflash akış okuyucusu) ----------
# _analyze_pymavlink ile BİREBİR aynı sonuç (aynı JSON; tests/test_binanalyze): değerler pymavlink ile bit bit aynı okunur
# (dataflash.oku kesin=True), tipler arası dosya sırası gereken yerlerde (BAT+CURR, XKF2+NKF2, POS'tan önceki BARO, t0) '_ofs' kullanılır,
# toplamlar/en büyük-en küçükler Python listeleri üzerinde aynı sırayla hesaplanır (numpy ikili toplamı / SIMD sin-hypot farkı olmasın).
_HIZLI_SUTUN = {
    'MSG': ['Message'], 'MODE': ['ModeNum', 'Mode', 'Rsn'],
    'GPS': ['I', 'Status', 'Lat', 'Lng', 'Spd', 'GWk', 'GMS', 'NSats', 'HDop'],
    'POS': ['Lat', 'Lng', 'RelHomeAlt'],
    'BAT': ['Inst', 'Instance', 'Volt', 'Curr', 'CurrTot', 'EnrgTot', 'RemPct'],
    'CURR': ['Inst', 'Instance', 'Volt', 'Curr', 'CurrTot', 'EnrgTot', 'RemPct'],
    'BARO': ['I', 'Alt'], 'CTUN': ['ThO', 'ThrOut', 'As'], 'ARSP': ['I', 'Airspeed'],
    'ATT': ['Roll', 'Pitch', 'DesRoll', 'DesPitch'],
    'VIBE': ['IMU', 'VibeX', 'VibeY', 'VibeZ', 'Clip', 'Clip0', 'Clip1', 'Clip2'],
    'XKF2': ['C', 'VWN', 'VWE'], 'NKF2': ['C', 'VWN', 'VWE'],
    'ERR': ['Subsys', 'ECode'], 'EV': ['Id'], 'ARM': ['ArmState'], 'STAT': ['isFlying'],
    'ORGN': ['Type', 'Lat', 'Lng', 'Alt'], 'PARM': [],
}
_SERI = ('alt', 'gs', 'as', 'volt', 'curr', 'vx', 'vy', 'vz', 'roll', 'droll', 'pitch', 'dpitch', 'sats', 'hdop', 'wind', 'thr')


def _thin_idx(n, limit):
    """_thin ile aynı seçim, indeks olarak."""
    if n <= limit:
        return list(range(n))
    step = n / limit
    out = [int(i * step) for i in range(limit)]
    out.append(n - 1)
    return out


def _analyze_hizli(path, ilerleme=None):
    import numpy as np
    from . import dataflash
    istek = {tp: ([] if tp == 'PARM' else ['TimeUS', 'TimeMS']) + c for tp, c in _HIZLI_SUTUN.items()}
    D = dataflash.oku(str(path), istek, ilerleme=(lambda y: ilerleme(int(y * 0.9))) if ilerleme else None, kesin=True, ofs=True,
                       tanimsizda_dur=True)
    if ilerleme:
        ilerleme(90)
    BOS = np.empty(0)

    def sutun(tp, ad, maske=None):
        """Zorunlu alan (pymavlink'te m.<ad>): yoksa ve kullanılacak satır varsa AttributeError (eski yol gibi)."""
        c = D[tp]
        if ad in c:
            return c[ad]
        if maske is None or np.any(maske):
            raise AttributeError(ad)
        return np.zeros(len(c['_ofs']))

    def ya(tp, ad, vars_=0):
        """getattr(m, ad, vars_) karşılığı (vars_ sabit, tamsayı)."""
        c = D[tp]
        return c[ad] if ad in c else np.full(len(c['_ofs']), vars_, dtype=np.int64)

    def sifir_mi(tp, ad):
        """getattr(m, ad, 0) in (0, None) karşılığı (NaN dolgu → hayır)."""
        c = D[tp]
        return (c[ad] == 0) if ad in c else np.ones(len(c['_ofs']), bool)

    params = len(D['PARM']['_ofs']) if 'PARM' in D else 0
    T = {}
    ilk = None
    count = 0
    for tp, c in D.items():
        if tp == 'PARM' or not len(c['_ofs']):
            continue
        if 'TimeUS' in c:
            tus = c['TimeUS']
        elif 'TimeMS' in c:
            tus = c['TimeMS'] * 1000
        else:
            continue
        T[tp] = tus.astype(np.float64) / 1e6
        count += len(tus)
        if ilk is None or c['_ofs'][0] < ilk[0]:
            ilk = (int(c['_ofs'][0]), float(T[tp][0]))
    if ilk is None or count == 0:
        raise ValueError('Logda okunabilir uçuş verisi bulunamadı')
    t0 = ilk[1]
    for tp in T:
        T[tp] = T[tp] - t0

    s = {k: (BOS, BOS) for k in _SERI}
    firmware = board = None
    msgs, modes, events, errors = [], [], [], []
    arm_flags, stat_flags = [], []
    bat = {'first': None, 'last': None, 'min_v': None, 'max_a': 0.0, 'mah': None, 'wh': None, 'pct': None}
    clips = {}
    origin = None
    gps_time_ref = None

    # MSG (sürüm / kart, ilk 200 mesaj)
    if 'MSG' in T:
        for t, text in zip(T['MSG'].tolist(), sutun('MSG', 'Message')):
            text = str(text)
            if firmware is None and text.startswith(('ArduPlane', 'ArduCopter', 'ArduRover', 'ArduSub', 'ArduHeli',
                                                     'Blimp', 'AntennaTracker')):
                firmware = text
            elif board is None and ' ' in text and any(text.startswith(b) for b in (
                    'Pixhawk', 'CubeOrange', 'CubeBlack', 'CubePurple', 'CubeYellow', 'Matek', 'fmuv', 'PX4v',
                    'Durandal', 'KakuteH', 'SpeedyBee', 'Holybro', 'MicoAir', 'mRo', 'Pixracer', 'omnibus')):
                board = text.split(' ')[0]
            if len(msgs) < MAX_MESSAGES:
                msgs.append({'t': _r(t), 'text': text, 'warn': bool(WARN_RE.search(text))})
    if 'MODE' in T:
        c = D['MODE']
        num = c['ModeNum'] if 'ModeNum' in c else c.get('Mode')
        num = num.tolist() if num is not None else [None] * len(T['MODE'])
        rsn = c['Rsn'].tolist() if 'Rsn' in c else [None] * len(T['MODE'])
        modes = list(zip(T['MODE'].tolist(), num, rsn))

    # GPS (birincil alıcı, I = 0)
    gt = glat = glng = gspd = BOS
    if 'GPS' in T:
        tg = T['GPS']
        keep = sifir_mi('GPS', 'I')
        ok3 = keep & (ya('GPS', 'Status') >= 3)
        gt, glat, glng, gspd = tg[ok3], sutun('GPS', 'Lat', ok3)[ok3], sutun('GPS', 'Lng', ok3)[ok3], sutun('GPS', 'Spd', ok3)[ok3]
        s['gs'] = (gt, gspd)
        gwk = ya('GPS', 'GWk')[ok3]
        ix = np.flatnonzero(gwk > 0)
        if len(ix):
            i = int(ix[0])
            wk = gwk[i].item()
            gms = sutun('GPS', 'GMS', ok3)[ok3][i].item()
            gps_time_ref = (gt[i].item(), 315964800 + wk * 604800 + gms / 1000.0 - 18)
        s['sats'] = (tg[keep], ya('GPS', 'NSats')[keep])
        s['hdop'] = (tg[keep], ya('GPS', 'HDop')[keep])
    # POS (EKF konumu) + POS'tan önceki BARO irtifası
    pt = plat = plng = prel = BOS
    prel_ok = np.zeros(0, bool)
    alt_t, alt_v = [], []
    ilk_pos = None
    if 'POS' in T:
        c = D['POS']
        pt, plat, plng = T['POS'], sutun('POS', 'Lat'), sutun('POS', 'Lng')
        if 'RelHomeAlt' in c:
            prel = c['RelHomeAlt']
            prel_ok = np.isfinite(prel)
        else:
            prel = np.full(len(pt), np.nan)
            prel_ok = np.zeros(len(pt), bool)
        ilk_pos = int(c['_ofs'][0])
    if 'BARO' in T:
        m = sifir_mi('BARO', 'I')
        if ilk_pos is not None:
            m &= D['BARO']['_ofs'] < ilk_pos
        alt_t.append(T['BARO'][m])
        alt_v.append(sutun('BARO', 'Alt', m)[m])
    if 'POS' in T:
        alt_t.append(pt[prel_ok])
        alt_v.append(prel[prel_ok])
    if alt_t:
        s['alt'] = (np.concatenate(alt_t), np.concatenate(alt_v))
    # Hava hızı: ARSP; logda hiç ARSP yoksa CTUN.As
    if 'ARSP' in T:
        m = sifir_mi('ARSP', 'I')
        s['as'] = (T['ARSP'][m], sutun('ARSP', 'Airspeed', m)[m])
    if 'CTUN' in T:
        c, tc = D['CTUN'], T['CTUN']
        if 'ThO' in c:
            v = c['ThO']
            s['thr'] = (tc, np.where(v <= 1.5, v * 100, v))
        elif 'ThrOut' in c:
            v = c['ThrOut']
            if v.dtype.kind == 'f':
                v2 = np.where(v > 1.5, v / 100.0, v)
                s['thr'] = (tc, np.where(v2 <= 1.5, v2 * 100, v2))
            else:   # tamsayı ThrOut: eski yoldaki int/float karışımı birebir
                out = []
                for x in v.tolist():
                    x = x / 100.0 if x > 1.5 else x
                    out.append(x * 100 if x <= 1.5 else x)
                arr = np.empty(len(out), dtype=object)
                arr[:] = out
                s['thr'] = (tc, arr)
        if 'ARSP' not in D and 'As' in c:
            m = np.isfinite(c['As'])
            s['as'] = (tc[m], c['As'][m])
    if 'ATT' in T:
        ta = T['ATT']
        s['roll'], s['pitch'] = (ta, sutun('ATT', 'Roll')), (ta, sutun('ATT', 'Pitch'))
        s['droll'], s['dpitch'] = (ta, sutun('ATT', 'DesRoll')), (ta, sutun('ATT', 'DesPitch'))
    if 'VIBE' in T:
        m = sifir_mi('VIBE', 'IMU')
        tv = T['VIBE'][m]
        s['vx'], s['vy'], s['vz'] = ((tv, sutun('VIBE', k, m)[m]) for k in ('VibeX', 'VibeY', 'VibeZ'))
        if np.any(m):
            son = int(np.flatnonzero(m)[-1])
            for f in ('Clip', 'Clip0', 'Clip1', 'Clip2'):
                if f in D['VIBE']:
                    clips[f] = D['VIBE'][f][son].item()

    def birlestir(tipler, alanlar):
        """Birden çok tipin satırları dosya sırasıyla: (t, {alan: (değerler, var_mı)})."""
        parca = [tp for tp in tipler if tp in T]
        if not parca:
            return None, None
        ofs = np.concatenate([D[tp]['_ofs'] for tp in parca])
        sira = np.argsort(ofs, kind='stable')
        tt = np.concatenate([T[tp] for tp in parca])[sira]
        out = {}
        for a in alanlar:
            if all(a in D[tp] for tp in parca):
                out[a] = (np.concatenate([D[tp][a] for tp in parca])[sira], None)
            else:
                v = np.concatenate([D[tp][a].astype(np.float64) if a in D[tp] else np.full(len(T[tp]), np.nan) for tp in parca])[sira]
                var = np.concatenate([np.full(len(T[tp]), a in D[tp]) for tp in parca])[sira]
                out[a] = (v, var)
        return tt, out

    # Rüzgâr (XKF2 / NKF2, çekirdek C = 0)
    wind_vn = wind_ve = []
    tw, W = birlestir(('XKF2', 'NKF2'), ('C', 'VWN', 'VWE'))
    if tw is not None:
        cv, cvar = W['C']
        m = (cv == 0) if cvar is None else np.where(cvar, cv == 0, True)
        if np.any(m) and (W['VWN'][1] is not None or W['VWE'][1] is not None) and not (
                (W['VWN'][1] is None or W['VWN'][1][m].all()) and (W['VWE'][1] is None or W['VWE'][1][m].all())):
            raise AttributeError('VWN')
        wind_vn, wind_ve = W['VWN'][0][m].tolist(), W['VWE'][0][m].tolist()
        s['wind'] = (tw[m], np.array([math.hypot(a, b) for a, b in zip(wind_vn, wind_ve)], dtype=np.float64))
    wind_dirs = bool(wind_vn)
    # Batarya (BAT / eski CURR; birincil örnek)
    tb, B = birlestir(('BAT', 'CURR'), ('Inst', 'Instance', 'Volt', 'Curr', 'CurrTot', 'EnrgTot', 'RemPct'))
    if tb is not None:
        n = len(tb)
        inst = np.zeros(n)
        for a in ('Instance', 'Inst'):   # getattr(m, 'Inst', getattr(m, 'Instance', 0))
            v, var = B[a]
            inst = np.where(np.ones(n, bool) if var is None else var, v, inst)
        keep = inst == 0
        v, var = B['Volt']
        keep &= np.isfinite(v) & (v > 0.5) & (True if var is None else var)
        if np.any(keep):
            V = v[keep]
            s['volt'] = (tb[keep], V)
            a, avar = B['Curr']
            am = keep & np.isfinite(a) & (True if avar is None else avar)
            s['curr'] = (tb[am], a[am])
            bat['max_a'] = max([0.0] + a[am].tolist())
            vl = V.tolist()
            bat['first'], bat['last'], bat['min_v'] = vl[0], vl[-1], min(vl)
            son = int(np.flatnonzero(keep)[-1])
            ct, ctvar = B['CurrTot']
            bat['mah'] = _num(ct[son].item()) if (ctvar is None or ctvar[son]) else None
            et, etvar = B['EnrgTot']
            em = keep & np.isfinite(et) & (True if etvar is None else etvar)
            if np.any(em):
                bat['wh'] = et[int(np.flatnonzero(em)[-1])].item()
            rp, rpvar = B['RemPct']
            if rpvar is None:
                bat['pct'] = rp[son].item()
            else:
                pm = keep & rpvar
                if np.any(pm):
                    bat['pct'] = rp[int(np.flatnonzero(pm)[-1])].item()
    if 'ERR' in T:
        for t, sub, code in zip(T['ERR'].tolist(), sutun('ERR', 'Subsys').tolist(), sutun('ERR', 'ECode').tolist()):
            errors.append({'t': _r(t), 'subsys': sub, 'code': code, 'text': ERR_SUBSYS.get(sub, f'Alt sistem {sub}'), 'resolved': code == 0})
    if 'EV' in T:
        for t, i in zip(T['EV'].tolist(), sutun('EV', 'Id').tolist()):
            events.append({'t': _r(t), 'id': i, 'text': EV_TEXT.get(i, f'Olay #{i}')})
            if i in (10, 11):
                arm_flags.append((t, i == 10))
    if 'ARM' in T:
        arm_flags += [(t, bool(a)) for t, a in zip(T['ARM'].tolist(), sutun('ARM', 'ArmState').tolist())]
    if 'STAT' in T:
        stat_flags = [(t, bool(f)) for t, f in zip(T['STAT'].tolist(), ya('STAT', 'isFlying').tolist())]
    if 'ORGN' in T:
        m = np.flatnonzero(ya('ORGN', 'Type') == 0)
        if len(m):
            i = int(m[0])
            origin = tuple(sutun('ORGN', k)[i].item() for k in ('Lat', 'Lng', 'Alt'))
    if ilerleme:
        ilerleme(94)

    duration = max((v[0][-1].item() for v in s.values() if len(v[0])), default=0)
    if len(gt):
        duration = max(duration, gt[-1].item())

    arm_flags.sort()
    if arm_flags and not arm_flags[0][1]:
        arm_flags.insert(0, (0.0, True))
    armed = _intervals(arm_flags + [(duration, arm_flags[-1][1])] if arm_flags else [])

    gtl = gt.tolist()
    if stat_flags:
        flying = _intervals(stat_flags + [(duration, stat_flags[-1][1])])
    else:
        gs_by_t = {round(t, 1): v for t, v in zip(gtl, gspd.tolist())}
        flags = []
        for tt, rel in zip(pt[prel_ok].tolist(), prel[prel_ok].tolist()):
            on = (rel > 2.0 or (gs_by_t.get(round(tt, 1)) or 0) > 4.0) and (not armed or _in(armed, tt))
            flags.append((tt, on))
        flying = [iv for iv in _intervals(flags) if iv[1] - iv[0] > 3]
    flight_s = sum(b - a for a, b in flying)
    armed_s = sum(b - a for a, b in armed)

    def air(tarr):
        if not flying:
            return np.ones(len(tarr), bool)
        m = np.zeros(len(tarr), bool)
        for a, b in flying:
            m |= (tarr >= a) & (tarr <= b)
        return m

    home = origin or ((glat[0].item(), glng[0].item(), None) if len(gt) else None)
    distance = 0.0
    max_home = 0.0
    prev = None
    ga = air(gt).tolist()
    glatl, glngl = glat.tolist(), glng.tolist()
    for lat, lng, ia in zip(glatl, glngl, ga):
        if ia:
            if prev:
                d = _haversine(prev, (lat, lng))
                if d < 500:
                    distance += d
            prev = (lat, lng)
            if home:
                max_home = max(max_home, _haversine(home, (lat, lng)))
    if len(gt):
        track = [[round(glatl[i], 7), round(glngl[i], 7), 1 if ga[i] else 0] for i in _thin_idx(len(gt), MAX_TRACK)]
    elif len(pt):
        pa = air(pt)
        track = [[round(plat[i].item(), 7), round(plng[i].item(), 7), 1 if pa[i] else 0] for i in _thin_idx(len(pt), MAX_TRACK)]
    else:
        track = []

    def stat(key, fn, only_air=True):
        tt, vv = s[key]
        if not len(tt):
            return None
        vals = (vv[air(tt)] if only_air else vv).tolist()
        return fn(vals) if vals else None

    mean = lambda v: sum(v) / len(v)
    climb = []
    at, av = s['alt'][0].tolist(), s['alt'][1].tolist()
    aa = air(s['alt'][0]).tolist()
    j = 0
    for i in range(1, len(at)):
        while at[i] - at[j] > 1.0:
            j += 1
        if j and aa[i]:
            k = j - 1
            climb.append((av[i] - av[k]) / (at[i] - at[k]))

    def track_err(des, act):
        vd, (ta_, va) = s[des][1], s[act]
        n = min(len(vd), len(va))
        m = air(ta_[:n])
        return (va[:n][m] - vd[:n][m]).tolist()
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v)) if v else None

    names = _mode_names(firmware)
    mode_rows = []
    for i, (tt, num, rsn) in enumerate(modes):
        end = modes[i + 1][0] if i + 1 < len(modes) else duration
        mode_rows.append({'t': _r(tt), 'name': names.get(num, f'Mod {num}'), 'dur': _r(end - tt), 'reason': rsn})

    wind_dir = None
    if wind_dirs and (stat('wind', mean) or 0) >= 0.5:
        vn = mean(wind_vn)
        ve = mean(wind_ve)
        wind_dir = round((math.degrees(math.atan2(-ve, -vn)) + 360) % 360)

    takeoff = flying[0][0] if flying else None
    landing = flying[-1][1] if flying else None
    to_utc = None
    if gps_time_ref:
        to_utc = lambda tt: datetime.fromtimestamp(gps_time_ref[1] + (tt - gps_time_ref[0]), timezone.utc).isoformat()

    summary = {
        'firmware': firmware, 'board': board, 'params': params,
        'vehicle': (firmware or 'Bilinmiyor').split(' ')[0],
        'start_utc': to_utc(0) if to_utc else None,
        'takeoff_utc': to_utc(takeoff) if to_utc and takeoff is not None else None,
        'landing_utc': to_utc(landing) if to_utc and landing is not None else None,
        'takeoff_t': _r(takeoff), 'landing_t': _r(landing),
        'duration_s': _r(duration), 'armed_s': _r(armed_s), 'flight_s': _r(flight_s), 'flights': len(flying),
        'distance_m': round(distance), 'max_home_m': round(max_home),
        'home': {'lat': home[0], 'lng': home[1], 'alt': home[2]} if home else None,
        'alt_max': _r(stat('alt', max)), 'alt_avg': _r(stat('alt', mean)),
        'gs_max': _r(stat('gs', max)), 'gs_avg': _r(stat('gs', mean)),
        'as_max': _r(stat('as', max)), 'as_avg': _r(stat('as', mean)),
        'climb_max': _r(max(climb) if climb else None), 'sink_max': _r(-min(climb) if climb else None),
        'roll_max': _r(stat('roll', lambda v: max(abs(x) for x in v))),
        'pitch_max': _r(stat('pitch', lambda v: max(abs(x) for x in v))),
        'roll_err_rms': _r(rms(track_err('droll', 'roll'))), 'pitch_err_rms': _r(rms(track_err('dpitch', 'pitch'))),
        'thr_avg': _r(stat('thr', mean)),
        'bat_start_v': _r(bat['first'], 2), 'bat_end_v': _r(bat['last'], 2), 'bat_min_v': _r(bat['min_v'], 2),
        'bat_max_a': _r(bat['max_a']), 'bat_avg_a': _r(stat('curr', mean)),
        'bat_used_mah': _r(bat['mah'], 0), 'bat_used_wh': _r(bat['wh']), 'bat_end_pct': bat['pct'],
        'sats_min': stat('sats', min), 'sats_avg': _r(stat('sats', mean)), 'hdop_max': _r(stat('hdop', max), 2),
        'vibe_max': [_r(stat(k, max, False)) for k in ('vx', 'vy', 'vz')],
        'clips': sum(clips.values()) if clips else 0,
        'wind_avg': _r(stat('wind', mean)), 'wind_max': _r(stat('wind', max)), 'wind_dir': wind_dir,
    }

    def seri(k):
        tt, vv = s[k]
        if not len(tt):
            return []
        idx = _thin_idx(len(tt), MAX_POINTS)
        return [[_r(a), _r(b, 2)] for a, b in zip(tt[idx].tolist(), vv[idx].tolist())]

    result = {
        'summary': summary,
        'findings': _findings(summary, errors, msgs),
        'modes': mode_rows,
        'events': events[:MAX_MESSAGES],
        'errors': errors,
        'messages': msgs,
        'flying': [[_r(a), _r(b)] for a, b in flying],
        'track': track,
        'series': {k: seri(k) for k in _SERI},
    }
    if ilerleme:
        ilerleme(100)
    return result


def _findings(s, errors, msgs, kaynak=None):
    out = []

    def add(level, title, detail):
        out.append({'level': level, 'title': title, 'detail': detail})

    vmax = max((v for v in s['vibe_max'] if v is not None), default=None)
    if vmax is not None:
        if vmax > 60:
            add('bad', 'Titreşim çok yüksek', f'En yüksek titreşim {vmax} m/s² (sınır 60). Motor/pervane dengesi ve uçuş kartı montajı kontrol edilmeli.')
        elif vmax > 30:
            add('warn', 'Titreşim yüksek', f'En yüksek titreşim {vmax} m/s² (önerilen < 30).')
        else:
            add('ok', 'Titreşim normal', f'En yüksek titreşim {vmax} m/s².')
    if s['clips']:
        add('bad' if s['clips'] > 100 else 'warn', 'İvmeölçer doygunluğu (clipping)',
            f'Toplam {s["clips"]} doygunluk sayıldı. Titreşim sönümleyicileri kontrol edilmeli.')

    if s['sats_min'] is not None:
        if s['sats_min'] < 6:
            add('bad', 'GPS uydu sayısı düşük', f'Uçuşta en az {s["sats_min"]} uydu görüldü (önerilen ≥ 8).')
        elif s['sats_min'] < 8:
            add('warn', 'GPS uydu sayısı sınırda', f'Uçuşta en az {s["sats_min"]} uydu görüldü.')
        else:
            add('ok', 'GPS alımı iyi', f'En az {s["sats_min"]}, ortalama {s["sats_avg"]} uydu.')
    if s['hdop_max'] is not None and s['hdop_max'] > 2:
        add('warn', 'GPS hassasiyeti düşük', f'En yüksek HDop {s["hdop_max"]} (önerilen < 2).')

    if s['bat_end_pct'] is not None:
        if s['bat_end_pct'] < 10:
            add('bad', 'Batarya kritik seviyede bitti', f'Uçuş sonu kalan kapasite %{s["bat_end_pct"]}.')
        elif s['bat_end_pct'] < 25:
            add('warn', 'Batarya düşük seviyede bitti', f'Uçuş sonu kalan kapasite %{s["bat_end_pct"]}.')
        else:
            add('ok', 'Batarya yeterli', f'Uçuş sonu kalan kapasite %{s["bat_end_pct"]}.')
    if s['bat_start_v'] and s['bat_min_v']:
        sag = (s['bat_start_v'] - s['bat_min_v']) / s['bat_start_v'] * 100
        if sag > 25:
            add('warn', 'Batarya voltaj düşümü yüksek', f'Voltaj {s["bat_start_v"]} V → en düşük {s["bat_min_v"]} V (%{sag:.0f} düşüş).')

    flew = bool(s['flight_s'])
    if flew and s['roll_err_rms'] is not None and s['roll_err_rms'] > 5:
        add('warn', 'Yatış (roll) takibi zayıf', f'İstenen ve gerçekleşen yatış farkı RMS {s["roll_err_rms"]}°. PID ayarı gözden geçirilmeli.')
    if flew and s['pitch_err_rms'] is not None and s['pitch_err_rms'] > 5:
        add('warn', 'Yunuslama (pitch) takibi zayıf', f'İstenen ve gerçekleşen yunuslama farkı RMS {s["pitch_err_rms"]}°.')
    if s['roll_max'] is not None and s['roll_max'] > 60:
        add('warn', 'Aşırı yatış açısı', f'En yüksek yatış {s["roll_max"]}°.')

    if kaynak == 'tlog':
        # Telemetri kaydında DataFlash ERR kaydı yoktur; otopilotun yer istasyonuna gönderdiği STATUSTEXT önem derecesine bakılır
        # (0 acil · 1 alarm · 2 kritik · 3 hata).
        kritik = [m for m in msgs if m.get('sev') is not None and m['sev'] <= 3]
        for m in kritik[:15]:
            add('bad' if m['sev'] <= 2 else 'warn', f'Sistem mesajı: {m["text"]}', f'{_clock(m["t"])} anında (önem {m["sev"]}).')
        if not kritik:
            add('ok', 'Kritik sistem mesajı yok', 'Telemetri kaydında (.tlog) ERR kaydı bulunmaz; hata/kritik önemde STATUSTEXT mesajı görülmedi.')
    else:
        open_errors = [e for e in errors if not e['resolved']]
        for e in open_errors[:15]:
            level = 'bad' if e['subsys'] in (5, 6, 7, 8, 12, 16, 17, 25, 26, 29, 30, 31) else 'warn'
            add(level, f'Hata: {e["text"]}', f'{_clock(e["t"])} anında kod {e["code"]}.')
        if not open_errors:
            add('ok', 'Kayıtlı sistem hatası yok', 'ERR kaydı bulunmadı veya tüm hatalar giderildi.')

    warn_msgs = [m for m in msgs if m['warn']]
    if warn_msgs:
        add('warn', 'Uyarı mesajları', f'{len(warn_msgs)} uyarı içerikli sistem mesajı var (ör. "{warn_msgs[0]["text"]}").')
    if s['flight_s'] == 0:
        add('warn', 'Uçuş algılanmadı', 'Logda havada geçen süre bulunamadı; yer testi veya eksik log olabilir.')
    order = {'bad': 0, 'warn': 1, 'ok': 2}
    return sorted(out, key=lambda f: order[f['level']])


def _clock(t):
    t = int(t or 0)
    return f'{t // 60:02d}:{t % 60:02d}'


# ---------- 3B oynatma verisi ----------
REPLAY_HZ = 5            # saniyede örnek
REPLAY_MAX = 40000       # en fazla örnek (çok uzun uçuşlarda aralık büyütülür)


def replay(path):
    """Cesium 3B oynatma için zaman serisi: [t, enlem, boylam, eve göre irtifa (m), roll, pitch, yaw (derece),
    yer hızı, hava hızı (m/s), gaz (%), batarya (V), devir]. Konum EKF'den (POS), yoksa GPS'ten alınır.
    İkili DataFlash'ta hızlı akış okuyucu (dataflash; 700 MB'lık logda ~8 sn / ~0,3 GB), aksi (metin .log) pymavlink."""
    from . import dataflash
    if str(path).lower().endswith('.tlog'):   # MAVLink telemetri kaydı (app/tlog.py)
        from . import tlog
        return tlog.replay(path)
    if dataflash.ikili_mi(path):
        return _replay_hizli(path)
    return _replay_pymavlink(path)


def _replay_hizli(path):
    import numpy as np
    from . import dataflash
    D = dataflash.oku(str(path), {
        'ATT': ['TimeUS', 'TimeMS', 'Roll', 'Pitch', 'Yaw'], 'POS': ['TimeUS', 'Lat', 'Lng', 'RelHomeAlt'],
        'GPS': ['TimeUS', 'TimeMS', 'I', 'Instance', 'Status', 'Lat', 'Lng', 'Alt', 'Spd'], 'CTUN': ['TimeUS', 'TimeMS', 'ThO', 'ThrOut', 'As'],
        'ARSP': ['TimeUS', 'I', 'Airspeed'], 'BAT': ['TimeUS', 'Inst', 'Instance', 'Volt'], 'CURR': ['TimeUS', 'TimeMS', 'Inst', 'Instance', 'Volt'],
        'RPM': ['TimeUS', 'I', 'RPM', 'rpm1']})
    Z = {k: dataflash.zaman(v) for k, v in D.items()}
    Z = {k: v for k, v in Z.items() if v is not None and len(v)}
    if not Z:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    t0 = min(float(v[0]) for v in Z.values())
    Z = {k: v - t0 for k, v in Z.items()}

    def orn0(c):
        for k in ('I', 'Inst', 'Instance'):
            if k in c:
                return np.isnan(c[k]) | (c[k] == 0)
        return None

    def tut(z, v, g):
        if z is None or not len(z):
            return np.full(len(g), np.nan)
        i = np.searchsorted(z, g, side='right') - 1
        out = np.asarray(v, dtype=np.float64)[np.maximum(i, 0)]
        out[i < 0] = np.nan
        return out
    pos, gps = D.get('POS'), D.get('GPS')
    zp = zg = None
    if pos is not None and 'RelHomeAlt' in pos:
        m = (pos['Lat'] != 0) & (pos['Lng'] != 0) & ~np.isnan(pos['RelHomeAlt'])
        zp = Z['POS'][m] if m.any() else None
        if zp is not None:
            pos = {k: v[m] for k, v in pos.items()}
    if gps is not None:
        m = orn0(gps)
        m = (m if m is not None else np.ones(len(Z['GPS']), bool)) & ((gps['Status'] >= 3) if 'Status' in gps else True)
        if np.any(m):
            gps = {k: v[m] for k, v in gps.items()}
            zg = Z['GPS'][m]
    ilk = [float(z[0]) for z in (zp, zg) if z is not None]
    if not ilk:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    son = max(float(v[-1]) for v in Z.values())
    g = np.arange(min(ilk), son + 1e-9, 1.0 / REPLAY_HZ)
    if len(g) < 2:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    lat = np.full(len(g), np.nan); lng = np.full(len(g), np.nan); alt = np.full(len(g), np.nan)
    if zg is not None:   # GPS: eve göre irtifa = Alt − ilk GPS irtifası (POS gelene kadar)
        lat, lng = tut(zg, gps['Lat'], g), tut(zg, gps['Lng'], g)
        alt = tut(zg, gps['Alt'] - gps['Alt'][0], g) if 'Alt' in gps else alt
    if zp is not None:
        s_ = g >= zp[0]
        lat[s_], lng[s_], alt[s_] = tut(zp, pos['Lat'], g)[s_], tut(zp, pos['Lng'], g)[s_], tut(zp, pos['RelHomeAlt'], g)[s_]
    att = D.get('ATT')
    roll, pitch, yaw = ((tut(Z['ATT'], att[k], g) for k in ('Roll', 'Pitch', 'Yaw')) if att else (np.zeros(len(g)),) * 3)
    gs = tut(zg, gps['Spd'], g) if zg is not None and 'Spd' in gps else np.full(len(g), np.nan)
    ctun, arsp = D.get('CTUN'), D.get('ARSP')
    if arsp is not None:
        m = orn0(arsp)
        m = m if m is not None else np.ones(len(Z['ARSP']), bool)
        as_ = tut(Z['ARSP'][m], arsp['Airspeed'][m], g)
    elif ctun is not None and 'As' in ctun:
        as_ = tut(Z['CTUN'], ctun['As'], g)
    else:
        as_ = np.full(len(g), np.nan)
    thr = np.full(len(g), np.nan)
    if ctun is not None and ('ThO' in ctun or 'ThrOut' in ctun):
        v = (ctun['ThO'] if 'ThO' in ctun else ctun['ThrOut']).astype(np.float64)
        thr = tut(Z['CTUN'], np.where(v <= 1.5, v * 100, v), g)
    volt = np.full(len(g), np.nan)
    for ad in ('BAT', 'CURR'):
        b = D.get(ad)
        if b is not None and 'Volt' in b:
            m = orn0(b)
            m = (m if m is not None else np.ones(len(Z[ad]), bool)) & (b['Volt'] > 0.5)
            volt = tut(Z[ad][m], b['Volt'][m], g)
            break
    rpm = np.full(len(g), np.nan)
    r = D.get('RPM')
    if r is not None:
        k = 'RPM' if 'RPM' in r else ('rpm1' if 'rpm1' in r else None)
        if k:
            m = orn0(r)
            m = m if m is not None else np.ones(len(Z['RPM']), bool)
            rpm = tut(Z['RPM'][m], r[k][m], g)
    ok = ~np.isnan(lat)
    cols = [np.round(g, 2), np.round(lat, 7), np.round(lng, 7), np.round(alt, 1), np.round(roll, 1), np.round(pitch, 1), np.round(yaw, 1),
            np.round(gs, 1), np.round(as_, 1), np.round(thr, 0), np.round(volt, 2), np.round(rpm, 0)]
    idx = np.flatnonzero(ok)
    if len(idx) > REPLAY_MAX:   # _thin ile aynı seçim
        idx = np.concatenate([idx[(np.arange(REPLAY_MAX) * (len(idx) / REPLAY_MAX)).astype(np.int64)], idx[-1:]])
    lst = []
    for c in cols:
        v = c[idx].tolist()
        lst.append([None if x != x else x for x in v])
    samples = [list(x) for x in zip(*lst)]
    if len(samples) < 2:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    return {'fields': ['t', 'lat', 'lng', 'alt', 'roll', 'pitch', 'yaw', 'gs', 'as', 'thr', 'volt', 'rpm'], 'samples': samples}


def _replay_pymavlink(path):
    log = mavutil.mavlink_connection(str(path), zero_time_base=False)
    t0 = None
    cur = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'gs': None, 'as': None, 'thr': None, 'volt': None, 'rpm': None}
    pos = None            # (enlem, boylam, eve göre irtifa)
    gps_alt0 = None
    has_pos = False
    samples = []
    step = 1.0 / REPLAY_HZ
    next_t = 0.0
    while True:
        m = log.recv_match(type=['ATT', 'POS', 'GPS', 'CTUN', 'ARSP', 'BAT', 'CURR', 'RPM'])
        if m is None:
            break
        tus = getattr(m, 'TimeUS', None)
        if tus is None:
            tms = getattr(m, 'TimeMS', None)
            if tms is None:
                continue
            tus = tms * 1000
        t = tus / 1e6
        if t0 is None:
            t0 = t
        t -= t0
        tp = m.get_type()
        if tp == 'ATT':
            cur['roll'], cur['pitch'], cur['yaw'] = m.Roll, m.Pitch, m.Yaw
        elif tp == 'POS':
            rel = _num(getattr(m, 'RelHomeAlt', None))
            if m.Lat and m.Lng and rel is not None:
                pos, has_pos = (m.Lat, m.Lng, rel), True
        elif tp == 'GPS':
            if getattr(m, 'I', 0) not in (0, None) or getattr(m, 'Status', 0) < 3:
                continue
            cur['gs'] = m.Spd
            if not has_pos:
                gps_alt0 = m.Alt if gps_alt0 is None else gps_alt0
                pos = (m.Lat, m.Lng, m.Alt - gps_alt0)
        elif tp == 'ARSP':
            if getattr(m, 'I', 0) in (0, None):
                cur['as'] = m.Airspeed
        elif tp == 'CTUN':
            thr = getattr(m, 'ThO', None)
            if thr is None:
                thr = getattr(m, 'ThrOut', None)
            if thr is not None:
                cur['thr'] = thr * 100 if thr <= 1.5 else thr
            if cur['as'] is None:
                cur['as'] = _num(getattr(m, 'As', None))
        elif tp in ('BAT', 'CURR'):
            v = _num(getattr(m, 'Volt', None))
            if getattr(m, 'Inst', getattr(m, 'Instance', 0)) in (0, None) and v and v > 0.5:
                cur['volt'] = v
        elif tp == 'RPM':   # motor devri (sensör bağlıysa; yoksa 0 gelir → istemci gaz değerine düşer)
            if getattr(m, 'I', 0) in (0, None):
                cur['rpm'] = _num(getattr(m, 'RPM', getattr(m, 'rpm1', None)))
        if pos and t >= next_t:
            samples.append([_r(t, 2), round(pos[0], 7), round(pos[1], 7), _r(pos[2], 1), _r(cur['roll'], 1),
                            _r(cur['pitch'], 1), _r(cur['yaw'], 1), _r(cur['gs'], 1), _r(cur['as'], 1),
                            _r(cur['thr'], 0), _r(cur['volt'], 2), _r(cur['rpm'], 0)])
            next_t = t + step
    if len(samples) < 2:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    samples = _thin(samples, REPLAY_MAX)
    return {'fields': ['t', 'lat', 'lng', 'alt', 'roll', 'pitch', 'yaw', 'gs', 'as', 'thr', 'volt', 'rpm'], 'samples': samples}


def _alt_surec_kisitla(ebeveyn=None):
    """Analiz alt süreci: düşük öncelik (nice), bellek tavanı (RLIMIT_AS), ebeveyn ölünce SIGKILL (PR_SET_PDEATHSIG).
    Değerler ortamdan: FLIGHTLOG_ANALIZ_NICE, FLIGHTLOG_ANALIZ_BELLEK_MB (flight_analysis bunları geçirir)."""
    import os
    try:
        n = int(os.environ.get('FLIGHTLOG_ANALIZ_NICE', '10') or 10)
        if n > 0:
            os.nice(n)
    except (OSError, ValueError):
        pass
    try:
        mb = int(os.environ.get('FLIGHTLOG_ANALIZ_BELLEK_MB', '0') or 0)
        if mb > 0:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (mb * 1024 * 1024, mb * 1024 * 1024))
    except (OSError, ValueError, ImportError):
        pass
    try:
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGKILL)   # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass
    if ebeveyn and os.getppid() != ebeveyn:   # ebeveyn prctl'den önce öldüyse
        os._exit(3)


def _main(argv):
    """Alt süreç:
      `python -m app.flightlog replay <log> <çıktı.json>` — 3B oynatma verisi;
      `python -m app.flightlog analyze <log> <çıktı.json> [ebeveyn pid]` — uçuş logu analizi (flight_analysis kuyruğu); ilerleme stdout'a
      `P <yüzde>` satırları.
    Çıktı atomik yazılır. Çıkış 0 = tamam (`OK`); hata stdout'ta `ERR <mesaj>`. (Ayrıştırma sunucu sürecinin olay döngüsünü ve belleğini
    meşgul etmesin.)"""
    import json
    import os
    import sys
    if len(argv) not in (3, 4) or argv[0] not in ('replay', 'analyze'):
        print('ERR kullanım: replay|analyze <log> <çıktı> [ebeveyn pid]', flush=True)
        sys.exit(2)
    try:
        if argv[0] == 'analyze':
            _alt_surec_kisitla(int(argv[3]) if len(argv) == 4 else None)
            son = [-1]

            def ilerleme(y):
                if y != son[0]:
                    son[0] = y
                    print(f'P {y}', flush=True)
            data = analyze(argv[1], ilerleme)
        else:
            data = replay(argv[1])
    except MemoryError:
        print('ERR Analiz bellek sınırını aştı (FLIGHTLOG_ANALIZ_BELLEK_MB)', flush=True)
        sys.exit(1)
    except Exception as e:   # noqa: BLE001
        print(f'ERR {e}'[:300].replace('\n', ' '), flush=True)
        sys.exit(1)
    tmp = argv[2] + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        if argv[0] == 'analyze':
            json.dump(data, f, ensure_ascii=False)
        else:
            json.dump(data, f, separators=(',', ':'))
    os.replace(tmp, argv[2])
    print('OK', flush=True)


if __name__ == '__main__':
    import sys as _sys
    _main(_sys.argv[1:])
