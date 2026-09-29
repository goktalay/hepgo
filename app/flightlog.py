"""ArduPilot DataFlash (.bin / .log) uçuş logu analizi.

pymavlink ile log okunur; özet değerler, zaman serileri (grafikler için seyreltilmiş), uçuş izi,
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


def analyze(path):
    log = mavutil.mavlink_connection(str(path), zero_time_base=False)
    t0 = None
    s = {k: [] for k in ('alt', 'gs', 'as', 'volt', 'curr', 'vx', 'vy', 'vz', 'roll', 'droll', 'pitch', 'dpitch',
                         'sats', 'hdop', 'wind', 'thr')}
    track, gps_pts, pos_pts = [], [], []
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

    while True:
        m = log.recv_match(type=TYPES)
        if m is None:
            break
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
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v)) if v else None

    # Modlar
    names = _mode_names(firmware)
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
        'findings': _findings(summary, errors, msgs),
        'modes': mode_rows,
        'events': events[:MAX_MESSAGES],
        'errors': errors,
        'messages': msgs,
        'flying': [[_r(a), _r(b)] for a, b in flying],
        'track': _thin(track, MAX_TRACK),
        'series': {k: [[_r(t), _r(v, 2)] for t, v in _thin(vals, MAX_POINTS)] for k, vals in s.items()},
    }
    return result


def _findings(s, errors, msgs):
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
    yer hızı, hava hızı (m/s), gaz (%), batarya (V)]. Konum EKF'den (POS), yoksa GPS'ten alınır."""
    log = mavutil.mavlink_connection(str(path), zero_time_base=False)
    t0 = None
    cur = {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0, 'gs': None, 'as': None, 'thr': None, 'volt': None}
    pos = None            # (enlem, boylam, eve göre irtifa)
    gps_alt0 = None
    has_pos = False
    samples = []
    step = 1.0 / REPLAY_HZ
    next_t = 0.0
    while True:
        m = log.recv_match(type=['ATT', 'POS', 'GPS', 'CTUN', 'ARSP', 'BAT', 'CURR'])
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
        if pos and t >= next_t:
            samples.append([_r(t, 2), round(pos[0], 7), round(pos[1], 7), _r(pos[2], 1), _r(cur['roll'], 1),
                            _r(cur['pitch'], 1), _r(cur['yaw'], 1), _r(cur['gs'], 1), _r(cur['as'], 1),
                            _r(cur['thr'], 0), _r(cur['volt'], 2)])
            next_t = t + step
    if len(samples) < 2:
        raise ValueError('Logda 3B oynatma için konum verisi yok')
    samples = _thin(samples, REPLAY_MAX)
    return {'fields': ['t', 'lat', 'lng', 'alt', 'roll', 'pitch', 'yaw', 'gs', 'as', 'thr', 'volt'], 'samples': samples}
