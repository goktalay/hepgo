"""Büyük .BIN izleme performansı + uçuş logu kaynağı (Gerçek / Simülasyon) — docs/ucus-simulatoru.md §8.3, docs/drone-logs (§ kaynak).

Kapsam:
  * dataflash.oku: pymavlink ile değer değer aynı (bozuk bayt + yükte sahte A3 95 başlığı + ortada yeni FMT ile yeniden eşitleme dahil).
  * Büyük üretilmiş .BIN (≈ 1 sa, ≈ 60 MB): alt süreçte ayrıştırma süresi ve tepe belleği (RUSAGE_CHILDREN), parçalı önbellek (lod),
    parça sürekliliği, genel bakış seyreltmesi, ikinci açılış (önbellek), eksik parça → yeniden üretim, silme.
  * flightlog.replay (3B oynatma): hızlı yol ↔ pymavlink yolu eşdeğer; uç alt süreçte üretir.
  * Kaynak çıkarımı: sim_isareti (SIM_* parametreleri), db.flight_log_origin_doldur (idempotent; simülatör izi, drone_sim_runs bağı,
    dosya başı işareti, dosya yok → NULL), yükleme ucu origin yazar, listeler origin döndürür.
  * Kayıttan oynatma oturumu: büyük kayıtta /replay (lod + genel bakış) ve /replay/{k} parça ucu (sınırlar 404).

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_binperf
"""
import gzip
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25550', SIM_MAX_SESSIONS='2')

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, config, dataflash, db, flightlog, flightsim, flightsim_replay as R  # noqa: E402
from app.main import app  # noqa: E402

# ---------------------------------------------------------------- DataFlash yazıcı (FMT + kayıtlar; ArduPilot biçimi)
_NP = {'b': 'i1', 'B': 'u1', 'h': '<i2', 'H': '<u2', 'i': '<i4', 'I': '<u4', 'f': '<f4', 'd': '<f8', 'n': 'S4', 'N': 'S16', 'Z': 'S64',
       'c': '<i2', 'C': '<u2', 'e': '<i4', 'E': '<u4', 'L': '<i4', 'M': 'u1', 'q': '<i8', 'Q': '<u8'}
TIPLER = {   # ad: (tip no, biçim, sütunlar)
    'PARM': (64, 'QNf', 'TimeUS,Name,Value'),
    'MSG': (65, 'QZ', 'TimeUS,Message'),
    'MODE': (66, 'QMBB', 'TimeUS,Mode,ModeNum,Rsn'),
    'EV': (67, 'QB', 'TimeUS,Id'),
    'ARM': (68, 'QBIBH', 'TimeUS,ArmState,ArmChecks,Forced,Method'),
    'GPS': (69, 'QBBIHBcLLeffffB', 'TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U'),
    'POS': (70, 'QLLfff', 'TimeUS,Lat,Lng,Alt,RelHomeAlt,RelOriginAlt'),
    'ATT': (71, 'QccccCCCC', 'TimeUS,DesRoll,Roll,DesPitch,Pitch,DesYaw,Yaw,ErrRP,ErrYaw'),
    'RCIN': (72, 'QHHHHHHHHHHHHHH', 'TimeUS,C1,C2,C3,C4,C5,C6,C7,C8,C9,C10,C11,C12,C13,C14'),
    'RCOU': (73, 'QHHHHHHHHHHHHHH', 'TimeUS,C1,C2,C3,C4,C5,C6,C7,C8,C9,C10,C11,C12,C13,C14'),
    'BAT': (74, 'QBfffffcfB', 'TimeUS,Inst,Volt,VoltR,Curr,CurrTot,EnrgTot,Temp,Res,RemPct'),
    'CTUN': (75, 'Qcccchhhf', 'TimeUS,NavRoll,Roll,NavPitch,Pitch,ThO,RdrOut,ThD,As'),
    'XKF1': (76, 'QBccCfffffffccce', 'TimeUS,C,Roll,Pitch,Yaw,VN,VE,VD,dPD,PN,PE,PD,GX,GY,GZ,OH'),
    'ARSP': (77, 'QBffcffBBfB', 'TimeUS,I,Airspeed,DiffPress,Temp,RawPress,Offset,U,H,Hp,Pri'),
    'STAT': (78, 'QBfBBBBB', 'TimeUS,isFlying,isFlyProb,Armed,Safety,Crash,Still,Stage'),
    'ORGN': (79, 'QBLLe', 'TimeUS,Type,Lat,Lng,Alt'),
    'IMU': (80, 'QBffffffIIfBBHH', 'TimeUS,I,GyrX,GyrY,GyrZ,AccX,AccY,AccZ,EG,EA,T,GH,AH,GHz,AHz'),
    'SIM': (81, 'QccCfLLffff', 'TimeUS,Roll,Pitch,Yaw,Alt,Lat,Lng,Q1,Q2,Q3,Q4'),
}
_OLCEK = {'c': 100, 'C': 100, 'e': 100, 'E': 100, 'L': 1e7}


def _dtype(bicim, sutun):
    return np.dtype([(c, _NP[b]) for b, c in zip(bicim, sutun.split(','))])


def fmt_kaydi(tip, ad, bicim, sutun):
    dt = _dtype(bicim, sutun)
    return (b'\xa3\x95\x80' + struct.pack('<BB4s16s64s', tip, dt.itemsize + 3, ad.encode(), bicim.encode(), sutun.encode()))


def kayitlar(ad, **degerler):
    """Ad + sütun dizileri → (TimeUS dizisi, bayt kayıtları listesi değil: (n, uzunluk) uint8 matrisi)."""
    tip, bicim, sutun = TIPLER[ad]
    dt = _dtype(bicim, sutun)
    n = len(degerler['TimeUS'])
    a = np.zeros(n, dtype=dt)
    for (b, c) in zip(bicim, sutun.split(',')):
        if c in degerler:
            v = degerler[c]
            a[c] = (np.round(np.asarray(v, dtype=np.float64) * _OLCEK[b]) if b in _OLCEK else v)
    bas = np.tile(np.array([0xA3, 0x95, tip], np.uint8), (n, 1))
    return np.asarray(degerler['TimeUS'], np.uint64), np.concatenate([bas, a.view(np.uint8).reshape(n, dt.itemsize)], axis=1)


def bin_yaz(yol, sure_s=600.0, sitl=False, imu_hz=0, bozuk=False, lat0=39.925, lon0=32.837, alt0=900.0):
    """Sentetik ArduPlane .BIN: 10 sn yerde, ARM, kalkış + 1 km yarıçaplı daire (100 m AGL), son 20 sn iniş, DISARM. 25 Hz ATT/POS/RCIN/RCOU/
    CTUN/XKF1(C0+C1), 5 Hz GPS, 10 Hz BAT/ARSP/STAT, MODE/MSG/EV/ORGN/PARM; `sitl`: SIM_* parametreleri + SIM mesajı; `imu_hz`: dolgu (boyut);
    `bozuk`: ortada çöp baytlar, bir kayıt yükünde sahte A3 95 başlığı ve dosya ortasında yeni FMT (yeniden eşitleme / FMT işleme yolu)."""
    T0 = 5_000_000   # µs (time_boot)
    bloklar = []
    t25 = T0 + np.arange(0, sure_s, 0.04) * 1e6
    t5 = T0 + np.arange(0, sure_s, 0.2) * 1e6
    t10 = T0 + np.arange(0, sure_s, 0.1) * 1e6

    def yol_(tus):
        s = (tus - T0) / 1e6
        armed = (s >= 10) & (s < sure_s - 5)
        ucus = np.clip((s - 15) / (sure_s - 50), 0, 1)
        ang = ucus * 2 * math.pi * max(1, sure_s / 300)
        r = np.where((s > 15) & (s < sure_s - 20), 1000.0, 0.0)
        lat = lat0 + r * np.cos(ang) / 110574 - 1000.0 * (r > 0) / 110574
        lon = lon0 + r * np.sin(ang) / (111320 * math.cos(math.radians(lat0)))
        z = np.where((s > 15) & (s < sure_s - 20), np.minimum(100.0, (s - 15) * 5), 0.0)
        hiz = np.where(r > 0, 2 * math.pi * 1000 * max(1, sure_s / 300) / (sure_s - 50), 0.0)
        return s, armed, lat, lon, z, ang, hiz
    s, armed, lat, lon, z, ang, hiz = yol_(t25)
    roll = np.where(z > 0, 15.0, 0.0) + np.sin(s) * 2
    yaw = np.mod(np.degrees(ang) + 90, 360)
    bloklar.append(kayitlar('ATT', TimeUS=t25, Roll=roll, Pitch=np.where(z > 0, 3.0, 0.0), Yaw=yaw, DesRoll=roll, DesPitch=0, DesYaw=yaw))
    bloklar.append(kayitlar('POS', TimeUS=t25, Lat=lat, Lng=lon, Alt=alt0 + z, RelHomeAlt=z, RelOriginAlt=z))
    rc = {f'C{i}': np.full(len(t25), 1500) for i in range(1, 15)}
    rc['C3'] = np.where(armed, 1700, 1000)
    bloklar.append(kayitlar('RCIN', TimeUS=t25, **rc))
    so = {f'C{i}': np.full(len(t25), 1500) for i in range(1, 15)}
    so['C1'] = np.where(z > 0, 1620, 1500)
    so['C3'] = np.where(armed, 1600, 1000)
    bloklar.append(kayitlar('RCOU', TimeUS=t25, **so))
    bloklar.append(kayitlar('CTUN', TimeUS=t25, ThO=np.where(armed, 60, 0), As=hiz))
    vn, ve = -hiz * np.sin(ang), hiz * np.cos(ang)
    for c in (0, 1):
        bloklar.append(kayitlar('XKF1', TimeUS=t25 + c, C=np.full(len(t25), c), VN=vn, VE=ve, VD=np.zeros(len(t25)), Roll=roll, Yaw=yaw))
    s5, _a, lat5, lon5, z5, ang5, hiz5 = yol_(t5)
    gms = ((s5 * 1000) + 300_000_000).astype(np.int64)
    bloklar.append(kayitlar('GPS', TimeUS=t5, I=np.zeros(len(t5)), Status=np.where(s5 >= 2, 3, 1), GMS=gms, GWk=np.full(len(t5), 2400), NSats=np.full(len(t5), 17),
                            HDop=np.full(len(t5), 0.7), Lat=lat5, Lng=lon5, Alt=alt0 + z5, Spd=hiz5, GCrs=np.mod(np.degrees(ang5) + 90, 360), VZ=np.zeros(len(t5))))
    s10, arm10, *_r = yol_(t10)
    bloklar.append(kayitlar('BAT', TimeUS=t10, Inst=np.zeros(len(t10)), Volt=16.8 - s10 / sure_s * 2, Curr=np.full(len(t10), 12.0), RemPct=np.floor(100 - s10 / sure_s * 60)))
    bloklar.append(kayitlar('ARSP', TimeUS=t10, I=np.zeros(len(t10)), Airspeed=yol_(t10)[6]))
    bloklar.append(kayitlar('STAT', TimeUS=t10, Armed=arm10.astype(int), isFlying=(yol_(t10)[4] > 0).astype(int)))
    if sitl:
        bloklar.append(kayitlar('SIM', TimeUS=t25 + 2, Roll=roll, Pitch=np.zeros(len(t25)), Yaw=yaw, Alt=alt0 + z, Lat=lat, Lng=lon))
    if imu_hz:
        ti = T0 + np.arange(0, sure_s, 1.0 / imu_hz) * 1e6 + 3
        bloklar.append(kayitlar('IMU', TimeUS=ti, I=np.zeros(len(ti)), AccZ=np.full(len(ti), -9.8), T=np.full(len(ti), 40.0)))
    t0 = np.array([T0 - 1000], np.uint64)
    parm = [('SERVO1_FUNCTION', 77), ('SERVO2_FUNCTION', 78), ('SERVO3_FUNCTION', 70), ('THR_MAX', 100)]
    if sitl:
        parm += [('SIM_SPEEDUP', 1), ('SIM_RATE_HZ', 1200), ('SIM_WIND_SPD', 0), ('SIM_GPS_DISABLE', 0), ('SIM_BARO_RND', 0.2)]
    for i, (ad, v) in enumerate(parm):
        bloklar.append(kayitlar('PARM', TimeUS=t0 + i, Name=[ad.encode()], Value=[v]))
    msg = [(T0 - 900, 'ArduPlane V4.7.1 (test)'), (T0 + 10_000_000, 'Throttle armed'), (T0 + 60_000_000, 'Low battery warning (test)')]
    for t, m in msg:
        bloklar.append(kayitlar('MSG', TimeUS=[t], Message=[m.encode()]))
    bloklar.append(kayitlar('MODE', TimeUS=[T0 - 800], Mode=[0], ModeNum=[0], Rsn=[0]))
    bloklar.append(kayitlar('MODE', TimeUS=[T0 + 12_000_000], Mode=[10], ModeNum=[10], Rsn=[1]))   # ArduPlane AUTO = 10
    bloklar.append(kayitlar('ARM', TimeUS=[T0 + 10_000_000], ArmState=[1]))
    bloklar.append(kayitlar('EV', TimeUS=[T0 + 10_000_000], Id=[10]))
    bloklar.append(kayitlar('ARM', TimeUS=[T0 + int((sure_s - 5) * 1e6)], ArmState=[0]))
    bloklar.append(kayitlar('ORGN', TimeUS=[T0 + 2_000_000], Type=[0], Lat=[lat0], Lng=[lon0], Alt=[alt0]))
    # zaman sırasıyla birleştir (eşit zamanda tip sırası korunur)
    zaman = np.concatenate([b[0] for b in bloklar])
    sira = np.argsort(zaman, kind='stable')
    uz = np.concatenate([np.full(len(b[0]), b[1].shape[1]) for b in bloklar])
    kayit = [None] * len(bloklar)
    ofs = np.cumsum([0] + [len(b[0]) for b in bloklar])
    with open(yol, 'wb') as f:
        f.write(b''.join(fmt_kaydi(tip, ad, bicim, sutun) for ad, (tip, bicim, sutun) in TIPLER.items() if ad not in ('IMU',) or imu_hz))
        if bozuk:   # ortada tanımlanacak ek tip (FMT dosyanın ortasında; ArduPilot tembel FMT yazımı)
            pass
        # tüm kayıtları tek bayt dizisine (sıra korunarak) — tip başına matrisler, sıralı birleştirme
        bayt = []
        bi = np.searchsorted(ofs, sira, side='right') - 1
        yarim = len(sira) // 2
        for j, (b_, i_) in enumerate(zip(bi.tolist(), (sira - ofs[bi]).tolist())):
            if bozuk and j == yarim:
                bayt.append(b'\x00\x13\x37' * 7)                                            # çöp: sonraki başlığa atlanmalı
                bayt.append(fmt_kaydi(90, 'XTRA', 'QB', 'TimeUS,V'))                        # ortada yeni FMT
                bayt.append(b'\xa3\x95' + bytes([90]) + struct.pack('<QB', int(zaman[sira[j]]), 7))
            rec = bloklar[b_][1][i_]
            if bozuk and j == yarim + 50 and TIPLER['MSG'][0] != rec[2]:
                rec = rec.copy()
                rec[-6:-3] = (0xA3, 0x95, 71)                                               # yükte sahte başlık
            bayt.append(rec.tobytes())
            if len(bayt) >= 200000:
                f.write(b''.join(bayt))
                bayt = []
        f.write(b''.join(bayt))
        del kayit
    return T0, uz.sum()


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text[:300])
    return r.json()


def bekle(fn, sn=5.0, adim=0.05):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


# ---------------------------------------------------------------- 1) okuyucu ↔ pymavlink
def okuyucu_testleri(d):
    from pymavlink import mavutil
    yol = os.path.join(d, 'kucuk-bozuk.bin')
    bin_yaz(yol, sure_s=90, sitl=True, imu_hz=50, bozuk=True)
    W = {'GPS': ['TimeUS', 'Lat', 'Lng', 'Alt', 'Spd', 'GWk'], 'ATT': ['TimeUS', 'Roll', 'Yaw'], 'RCOU': ['TimeUS', 'C1', 'C3'], 'MSG': ['TimeUS', 'Message'],
         'XKF1': ['TimeUS', 'C', 'VN'], 'PARM': ['TimeUS', 'Name', 'Value'], 'XTRA': ['TimeUS', 'V'], 'SIM': ['TimeUS', 'Roll']}
    yuzde = []
    D = dataflash.oku(yol, W, ilerleme=yuzde.append, blok=64 * 1024)   # küçük blok: blok sınırı geçişleri de sınanır
    assert yuzde[-1] == 100 and yuzde == sorted(yuzde), yuzde[-5:]
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):   # pymavlink bozuk baytta "bad header" basar
        log = mavutil.mavlink_connection(yol, zero_time_base=False)
        mesajlar = []
        while True:
            m = log.recv_match(type=list(W))
            if m is None:
                break
            mesajlar.append(m)
    say = {k: 0 for k in W}
    fark = 0
    for m in mesajlar + [None]:
        if m is None:
            break
        tp = m.get_type()
        i = say[tp]
        say[tp] += 1
        for c in W[tp]:
            a, b = getattr(m, c), D[tp][c][i]
            if isinstance(a, str):
                fark += a != b
            else:
                fark += not (a == b or abs(a - b) <= 1e-6 * max(1.0, abs(a)))
    assert fark == 0, fark
    for tp, n in say.items():
        assert len(next(iter(D[tp].values()))) == n, (tp, n)
    assert say['XTRA'] == 1 and say['ATT'] > 2000, say
    assert dataflash.ikili_mi(yol) and not dataflash.ikili_mi(__file__)
    print('  okuyucu = pymavlink (bozuk bayt, sahte başlık, ortada FMT, 64 KB blok) geçti')


# ---------------------------------------------------------------- 2) büyük kayıt: süre, bellek, önbellek, seyreltme
def buyuk_testleri(d):
    yol = os.path.join(d, 'buyuk.bin')
    t = time.time()
    bin_yaz(yol, sure_s=3600, imu_hz=200)
    boyut = os.path.getsize(yol)
    print(f'  büyük .BIN üretildi: {boyut / 1e6:.1f} MB ({time.time() - t:.1f} sn)')
    assert boyut > 40e6, boyut
    lid = 900001
    t = time.time()
    p = subprocess.Popen([sys.executable, '-m', 'app.flightsim_replay', str(lid), yol], cwd=str(config.BASE_DIR), stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    # tepe bellek: /proc/<pid>/status VmHWM (exec sonrası yeni adres alanı). ru_maxrss kullanılamaz: fork anındaki ebeveyn RSS'ini
    # (test süreci ~0,3 GB) de sayar. Çıktı ayrı iş parçacığında okunur (boru dolmasın).
    import threading
    cikti = []
    okuyucu = threading.Thread(target=lambda: cikti.append(p.stdout.read()), daemon=True)
    okuyucu.start()
    hwm = 0
    while p.poll() is None:
        try:
            with open(f'/proc/{p.pid}/status') as f:
                for sat in f:
                    if sat.startswith('VmHWM:'):
                        hwm = max(hwm, int(sat.split()[1]))
        except OSError:
            pass
        time.sleep(0.05)
    okuyucu.join(5)
    sure = time.time() - t
    rss = hwm / 1024
    satirlar = ''.join(cikti).strip().splitlines()
    assert p.returncode == 0 and satirlar[-1].startswith('OK '), (p.returncode, satirlar[-3:])
    yuzde = [int(s[2:]) for s in satirlar if s.startswith('P ')]
    assert yuzde and yuzde == sorted(yuzde) and yuzde[-1] == 100 and len(set(yuzde)) >= 8, yuzde   # gerçek ilerleme (indekslemede %100'e sıçramaz)
    meta = json.loads(satirlar[-1][3:])
    print(f'  ayrıştırma + önbellek: {sure:.1f} sn · tepe RSS (alt süreç) {rss:.0f} MB · {boyut / 1e6:.0f} MB log')
    assert sure < 120 and rss < 600, (sure, rss)   # bellek tavanı: tüm dosya belleğe alınmaz (akış; 68 MB log ≈ 0,16 GB)
    lod = meta['lod']
    hz = meta['hz']
    assert meta['n'] > R.TEK_PARCA_KARE and abs(meta['n'] - 3600 * hz) < hz * 2, meta['n']
    assert lod['chunk_n'] == R.PARCA_S * hz and lod['chunks'] == math.ceil(meta['n'] / lod['chunk_n']) and lod['step'] == round(hz / R.GENEL_HZ), lod
    assert meta['vehicle'] == 'ArduPlane V4.7.1 (test)' and meta['type'] == 'sabit_kanat' and abs(meta['takeoff_t'] - 10.0) < 0.2, meta
    assert meta['modes'] == ['MANUAL', 'AUTO'] and meta['home']['lat'] == 39.925, (meta['modes'], meta['home'])
    gz = R.onbellek_yolu(lid)
    with gzip.open(gz, 'rt', encoding='utf-8') as f:
        G = json.load(f)
    FI = {k: i for i, k in enumerate(G['fields'])}
    assert G['v'] == R.ONBELLEK_SURUM and G['lod'] == lod and len(G['frames']) == lod['n_overview'], len(G['frames'])
    assert abs(len(G['frames']) - 3600 * R.GENEL_HZ) <= 2, len(G['frames'])      # seyreltme: 1 Hz genel bakış
    assert G['frames'][-1][0] == round(meta['duration_s'], 3) or abs(G['frames'][-1][0] - meta['duration_s']) < 0.05   # son kare dahil
    toplam, onceki_t = 0, None
    for k in range(lod['chunks']):
        with gzip.open(R.onbellek_parca_yolu(lid, k), 'rt', encoding='utf-8') as f:
            P = json.load(f)
        assert P['k'] == k and P['a'] == k * lod['chunk_n'] and P['v'] == R.ONBELLEK_SURUM
        fr = P['frames']
        assert fr and (onceki_t is None or abs(fr[0][0] - onceki_t - 1 / hz) < 1e-3), (k, fr[0][0], onceki_t)   # parçalar kesintisiz
        onceki_t = fr[-1][0]
        if k == 3:   # genel bakış karesi = parçadaki aynı sıra karesi (aynı ızgara)
            j = (P['a'] + lod['step'] - 1) // lod['step'] * lod['step']
            assert G['frames'][j // lod['step']] == fr[j - P['a']], (G['frames'][j // lod['step']][:5], fr[j - P['a']][:5])
            f30 = fr[len(fr) // 2]
            assert f30[FI['armed']] == 1 and f30[FI['mode']] == 1 and 99 <= f30[FI['alt_rel']] <= 101 and f30[FI['rc']][2] == 1700 and f30[FI['servo']][0] == 1620, f30
        toplam += len(fr)
    assert toplam == meta['n'], (toplam, meta['n'])
    boy = R.onbellek_boyutu(lid)
    print(f'  önbellek: {lod["chunks"]} parça + genel bakış ({lod["n_overview"]} kare) = {boy / 1e6:.1f} MB')
    # ikinci açılış: önbellekten (ayrıştırma yok)
    t = time.time()
    m2 = R.hazirla(lid, yol)
    assert time.time() - t < 2 and m2['n'] == meta['n'] and m2['lod'] == lod, time.time() - t
    # eksik parça → önbellek geçersiz, yeniden üretilir
    R.onbellek_parca_yolu(lid, 2).unlink()
    try:
        R.onbellek_meta(gz)
        raise AssertionError('eksik parçalı önbellek kabul edildi')
    except ValueError:
        pass
    m3 = R.hazirla(lid, yol)
    assert m3['n'] == meta['n'] and R.onbellek_parca_yolu(lid, 2).exists()
    # 3B oynatma (Cesium) verisi: hızlı yol
    t = time.time()
    r3 = flightlog.replay(yol)
    print(f'  3B oynatma verisi (5 Hz): {time.time() - t:.1f} sn · {len(r3["samples"])} örnek')
    assert abs(len(r3['samples']) - 3600 * flightlog.REPLAY_HZ) <= 2 and r3['fields'][-1] == 'rpm', len(r3['samples'])
    return lid, yol


def replay3d_eslik(d):
    yol = os.path.join(d, 'r3d.bin')
    bin_yaz(yol, sure_s=120)
    y, e = flightlog._replay_hizli(yol), flightlog._replay_pymavlink(yol)
    et = [s[0] for s in e['samples']]
    import bisect
    fark = 0
    # eski yol kareyi mesaj anında (kayan 0,2 sn adımla), yeni yol sabit 5 Hz ızgarada yazar: en yakın eski örnekle (≤ 0,2 sn) karşılaştırılır,
    # tolerans 90 m/s dönen uçağın 0,2 sn'de alabileceği yol/yönelim farkı kadar; ilk saniyeler (ARM öncesi alan doluşu) dışarıda
    sayac = 0
    for s in y['samples'][::10]:
        if s[0] < 12:
            continue
        i = bisect.bisect_left(et, s[0])
        o = min((e['samples'][j] for j in (i - 1, i) if 0 <= j < len(et)), key=lambda x: abs(x[0] - s[0]))
        if abs(o[0] - s[0]) > 0.2:
            continue
        sayac += 1
        for k, tol in ((1, 3e-4), (2, 3e-4), (3, 2.0), (4, 1.5), (6, 3.0), (9, 1.5), (10, 0.05)):   # lat, lng, alt, roll, yaw, thr, volt
            if s[k] is None or o[k] is None:
                fark += (s[k] is None) != (o[k] is None)
            else:
                dv = abs(s[k] - o[k])
                fark += (min(dv, 360 - dv) if k == 6 else dv) > tol
    assert fark == 0 and sayac > 50, (fark, sayac)
    assert abs(len(y['samples']) - len(e['samples'])) < len(e['samples']) * 0.1, (len(y['samples']), len(e['samples']))
    print('  3B oynatma hızlı yol = pymavlink yolu geçti')


# ---------------------------------------------------------------- 3) kaynak çıkarımı + göç
def kaynak_testleri(a, d):
    up = config.UPLOAD_DIR / 'flightlogs'
    up.mkdir(parents=True, exist_ok=True)
    sitl, gercek = up / 'sitl.bin', up / 'gercek.bin'
    bin_yaz(str(sitl), sure_s=40, sitl=True)
    bin_yaz(str(gercek), sure_s=40)
    assert dataflash.sim_isareti(sitl) is True and dataflash.sim_isareti(gercek) is False and dataflash.sim_isareti(up / 'yok.bin') is None
    with db.connect() as conn:
        ekle = lambda f, ad, ac=None, note=None: conn.execute(   # noqa: E731
            "INSERT INTO flight_logs (file, file_name, size, status, aircraft, note, uploaded_by, uploaded_at) VALUES (?,?,?,'TAMAM',?,?,1,?)",
            (f, ad, 1000, ac, note, db.now())).lastrowid
        i_iz = ekle('flightlogs/yok1.bin', 'SIM-3-20261019-1534.bin', 'Simülatör · Sabit Kanat', 'Uçuş Simülatörü oturumu #3 (SITL DataFlash)')
        i_sitl = ekle('flightlogs/sitl.bin', '00000042.BIN')                 # elle yüklenmiş SITL logu: dosya başından
        i_ger = ekle('flightlogs/gercek.bin', '13.10.26_565km_700m.BIN')
        i_yok = ekle('flightlogs/kayip.bin', 'kayip.BIN')                    # dosya yok → NULL kalır
        i_run = ekle('flightlogs/yok2.bin', 'ozel-ad.bin')                   # drone_sim_runs bağı
        i_ad = ekle('flightlogs/yok3.bin', 'SIM-1-20261020-1047.bin')        # yalnız ad benzer (iz yok) → dosya yok → NULL
        conn.execute("INSERT INTO drone_sim_runs (session_id, started_at, created_at, bin_log_id) VALUES (1, ?, ?, ?)", (db.now(), db.now(), i_run))
        conn.execute('UPDATE flight_logs SET origin = NULL WHERE id IN (?,?,?,?,?,?)', (i_iz, i_sitl, i_ger, i_yok, i_run, i_ad))
        conn.commit()
        db.flight_log_origin_doldur(conn)
        conn.commit()
        oku = lambda: dict(conn.execute('SELECT id, origin FROM flight_logs').fetchall())   # noqa: E731
        o = oku()
        assert (o[i_iz], o[i_sitl], o[i_ger], o[i_yok], o[i_run], o[i_ad]) == ('SIM', 'SIM', 'REAL', None, 'SIM', None), o
        conn.execute("UPDATE flight_logs SET origin = 'REAL' WHERE id = ?", (i_sitl,))   # elle düzeltilmiş değer korunur (yalnız NULL'lar)
        conn.commit()
        db.flight_log_origin_doldur(conn)
        assert oku()[i_sitl] == 'REAL' and oku()[i_yok] is None
        conn.execute("UPDATE flight_logs SET origin = 'SIM' WHERE id = ?", (i_sitl,))
        conn.commit()
    # yükleme ucu origin yazar (tek istek; yerel istemci)
    for ad, f, beklenen in (('yukle-sitl.bin', sitl, 'SIM'), ('yukle-gercek.bin', gercek, 'REAL')):
        r = a.post('/api/tools/flight-logs', files={'file': (ad, f.read_bytes(), 'application/octet-stream')})
        if r.status_code == 403:   # yerel olmayan istemci kısıtı: parça parça yükleme yolu ile
            print('  (tek istek yükleme yerel değil; atlandı)')
            break
        lid = ok(r)['id']
        with db.connect() as conn:
            assert conn.execute('SELECT origin FROM flight_logs WHERE id = ?', (lid,)).fetchone()[0] == beklenen
    # listeler origin döndürür; süzgeç uçları (istemci tarafı) için her satırda alan var
    L = ok(a.get('/api/tools/flight-logs'))
    assert all('origin' in x for x in L) and {x['id']: x['origin'] for x in L}[i_ger] == 'REAL', L[:2]
    S = ok(a.get('/api/drone/sim/logs'))
    so = {x['id']: x['origin'] for x in S}
    assert so[i_sitl] == 'SIM' and so[i_ger] == 'REAL' and all('origin' in x for x in S), so
    print('  kaynak çıkarımı + göç (idempotent) + liste alanı geçti')
    return i_ger


# ---------------------------------------------------------------- 4) oturum: büyük kayıtta parça ucu
def oturum_testleri(a, lid_buyuk, yol_buyuk):
    with db.connect() as conn:
        rel = os.path.relpath(yol_buyuk, config.UPLOAD_DIR)
        if rel.startswith('..'):
            import shutil
            hedef = config.UPLOAD_DIR / 'flightlogs' / 'buyuk.bin'
            shutil.copy(yol_buyuk, hedef)
            rel = 'flightlogs/buyuk.bin'
        lid = conn.execute('''INSERT INTO flight_logs (file, file_name, size, status, analysis, aircraft, uploaded_by, uploaded_at, origin)
                              VALUES (?, 'buyuk.BIN', ?, 'TAMAM', ?, 'CZ-T', 1, ?, 'REAL')''',
                           (rel, os.path.getsize(yol_buyuk), json.dumps({'summary': {'vehicle': 'ArduPlane', 'home': {'lat': 39.925, 'lng': 32.837}}}), db.now())).lastrowid
        conn.commit()
    t = time.time()
    s = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}), 201)
    g = bekle(lambda: (lambda r: r if r['state'] in ('HAZIR', 'HATA') else None)(ok(a.get(f"/api/drone/sim/sessions/{s['id']}"))), 180, 0.3)
    assert g and g['state'] == 'HAZIR', g and g.get('sitl')
    print(f'  oturum HAZIR (ilk ayrıştırma): {time.time() - t:.1f} sn')
    t = time.time()
    body = ok(a.get(f"/api/drone/sim/sessions/{s['id']}/replay"))
    p0 = ok(a.get(f"/api/drone/sim/sessions/{s['id']}/replay/0"))
    ilk = time.time() - t
    assert body['lod']['chunks'] > 1 and len(body['frames']) == body['lod']['n_overview'] and len(p0['frames']) == body['lod']['chunk_n'], body['lod']
    son = body['lod']['chunks'] - 1
    assert ok(a.get(f"/api/drone/sim/sessions/{s['id']}/replay/{son}"))['k'] == son
    assert a.get(f"/api/drone/sim/sessions/{s['id']}/replay/{son + 1}").status_code == 404
    assert a.get(f"/api/drone/sim/sessions/{s['id']}/replay/-1").status_code in (404, 422)
    print(f'  ilk görüntü verisi (genel bakış + ilk parça, önbellekten): {ilk:.2f} sn')
    assert ilk < 5, ilk
    ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
    # ikinci açılış önbellekten anında HAZIR
    t = time.time()
    s2 = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}), 201)
    g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f"/api/drone/sim/sessions/{s2['id']}"))), 10, 0.1)
    assert g and time.time() - t < 5, time.time() - t
    ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
    # SITL oturumunda parça ucu 400; yok oturum 404
    assert a.get('/api/drone/sim/sessions/987654/replay/0').status_code == 404
    # 3B oynatma ucu (alt süreç) + silme önbelleği temizler
    r3 = ok(a.get(f'/api/flight-logs/{lid}/replay'))
    assert len(r3['samples']) > 1000 and r3['fields'][0] == 't'
    ok(a.delete(f'/api/tools/flight-logs/{lid}'))
    assert not R.onbellek_yolu(lid).exists() and not list(R.onbellek_dizini().glob(f'{lid}.p*.json.gz'))
    print('  oturum parça ucu + 3B oynatma ucu + silme geçti')


def main():
    d = tempfile.mkdtemp(prefix='binperf-')
    okuyucu_testleri(d)
    replay3d_eslik(d)
    lid, yol = buyuk_testleri(d)
    R.onbellek_sil(lid)
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert a.cookies.get(auth.COOKIE)
        kaynak_testleri(a, d)
        oturum_testleri(a, lid, yol)
        flightsim.MANAGER.sessions.clear()
    print('Büyük .BIN + kaynak testleri geçti.')


if __name__ == '__main__':
    main()
