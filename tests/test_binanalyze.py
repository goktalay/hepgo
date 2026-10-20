"""Uçuş logu analizi: hızlı akış okuyucu + alt süreç + kuyruk (docs/ucus-simulatoru.md §8.4).

Kapsam:
  * Eşdeğerlik: flightlog._analyze_hizli (dataflash, numpy) ↔ flightlog._analyze_pymavlink (eski yol) — JSON metni BİREBİR aynı.
    Örnekler: tests/data/arduplane-sample.bin (gerçek, küçük) + üç sentetik .BIN varyantı (Plane: STAT/ARSP/XKF2 C0-C1/BAT Inst 0-1/
    GPS I 0-1/VIBE IMU 0-1/POS'tan önce BARO/NaN RelHomeAlt/ERR/EV/ARM/ORGN/Türkçe + NUL sonrası çöplü MSG/bozuk bayt/yükte sahte başlık/
    ortada FMT/tanımsız tip; eski Copter: STAT yok → irtifa/hız sezgisi, ARSP yok → CTUN.As, NKF2 (C yok), eski VIBE Clip0-2, CURR (TimeMS),
    GPS I yok, MODE yalnız Mode; ThrOut tamsayı → int/float karışık seri) + isteğe bağlı gerçek büyük loglar (BINANALYZE_GERCEK=yol1:yol2).
  * Alt süreç: CLI `python -m app.flightlog analyze` ilerleme satırları (artan, 100'de biter), nice / RLIMIT_AS, ebeveyn ölünce çocuk ölür
    (PDEATHSIG), tepe bellek (VmHWM).
  * Kuyruk: yükleme ucu hemen döner (analiz beklenmez); FLIGHTLOG_ANALIZ_PARALEL=1 → aynı anda tek alt süreç, diğerleri sırada
    (liste/ayrıntı ucunda queue / progress), hepsi TAMAM; ilerleme API'de görünür.
  * Yeniden başlatma kurtarması: ISLENIYOR'da (progress 57, yarım çıktı dosyası) kalan kayıt resume_pending ile baştan analiz edilir.
  * Hatalar: bozuk dosya → HATA; zaman aşımı → HATA; bellek tavanı → HATA (takılı kalmaz).

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_binanalyze
"""
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', FLIGHTLOG_ANALIZ_PARALEL='1', FLIGHTLOG_ANALIZ_NICE='7', FLIGHTLOG_ANALIZ_BELLEK_MB='3072')

import contextlib  # noqa: E402
import io  # noqa: E402

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, flight_analysis, flightlog  # noqa: E402
from app.main import app  # noqa: E402

ORNEK = os.path.join(os.path.dirname(__file__), 'data', 'arduplane-sample.bin')

# ---------------------------------------------------------------- DataFlash yazıcı (vektörel; değişken uzunluklu kayıtlar zaman sırasıyla)
_NP = {'b': 'i1', 'B': 'u1', 'h': '<i2', 'H': '<u2', 'i': '<i4', 'I': '<u4', 'f': '<f4', 'd': '<f8', 'n': 'S4', 'N': 'S16', 'Z': 'S64',
       'c': '<i2', 'C': '<u2', 'e': '<i4', 'E': '<u4', 'L': '<i4', 'M': 'u1', 'q': '<i8', 'Q': '<u8'}
_OLCEK = {'c': 100, 'C': 100, 'e': 100, 'E': 100, 'L': 1e7}


class Yazici:
    def __init__(self):
        self.tipler = {}      # ad → (no, biçim, sütunlar, dtype)
        self.parcalar = []    # (zaman µs dizisi, (n, L) uint8)

    def tip(self, no, ad, bicim, sutun):
        dt = np.dtype([(c, _NP[b]) for b, c in zip(bicim, sutun.split(','))])
        self.tipler[ad] = (no, bicim, sutun, dt)

    def fmt(self, ad):
        no, bicim, sutun, dt = self.tipler[ad]
        return b'\xa3\x95\x80' + struct.pack('<BB4s16s64s', no, dt.itemsize + 3, ad.encode(), bicim.encode(), sutun.encode())

    def ekle(self, ad, zaman, **deg):
        no, bicim, sutun, dt = self.tipler[ad]
        zaman = np.atleast_1d(np.asarray(zaman, dtype=np.float64))
        n = len(zaman)
        a = np.zeros(n, dtype=dt)
        for b, c in zip(bicim, sutun.split(',')):
            if c in ('TimeUS', 'TimeMS'):
                a[c] = np.round(zaman / (1000 if c == 'TimeMS' else 1))
            elif c in deg:
                v = deg[c]
                a[c] = np.round(np.asarray(v, dtype=np.float64) * _OLCEK[b]) if b in _OLCEK else v
        bas = np.tile(np.array([0xA3, 0x95, no], np.uint8), (n, 1))
        self.parcalar.append((zaman, np.concatenate([bas, a.view(np.uint8).reshape(n, dt.itemsize)], axis=1)))

    def yaz(self, yol, bozuk=False):
        zaman = np.concatenate([p[0] for p in self.parcalar])
        uz = np.concatenate([np.full(len(p[0]), p[1].shape[1], np.int64) for p in self.parcalar])
        sira = np.argsort(zaman, kind='stable')
        ofs = np.zeros(len(sira) + 1, np.int64)
        ofs[1:] = np.cumsum(uz[sira])
        konum = np.empty(len(sira), np.int64)
        konum[sira] = ofs[:-1]
        out = np.zeros(int(ofs[-1]), np.uint8)
        i = 0
        for _z, mat in self.parcalar:   # her tipin kayıtları kendi konumlarına (dağıtma)
            n, L = mat.shape
            out[(konum[i:i + n])[:, None] + np.arange(L)] = mat
            i += n
        govde = out.tobytes()
        if bozuk:   # ortada: çöp bayt + yeni FMT (XTRA) + bir kaydın yükünde sahte A3 95 başlığı; %90'da tanımsız tipli başlık
            n = len(sira)
            orta = int(ofs[n // 2])
            ek = (b'\x00\x13\x37' * 7 + self.fmt('XTRA') +
                  b'\xa3\x95' + bytes([self.tipler['XTRA'][0]]) + struct.pack('<QB', int(zaman[sira[n // 2]]), 7))
            govde = govde[:orta] + ek + govde[orta:]
            g = bytearray(govde)
            p = int(ofs[n // 2 + 40]) + len(ek) + int(uz[sira[n // 2 + 40]]) - 6
            g[p:p + 3] = b'\xa3\x95' + bytes([self.tipler['ATT'][0]])
            # pymavlink indeksleyicisi tanımsız tipte okumayı BİTİRİR (sonrası analize girmez); hızlı yol da aynı (tanimsizda_dur)
            q = int(ofs[int(n * 0.9)]) + len(ek)
            govde = bytes(g[:q]) + b'\xa3\x95\xfe\x01\x02' + bytes(g[q:])
        with open(yol, 'wb') as f:
            f.write(b''.join(self.fmt(ad) for ad in self.tipler if ad != 'XTRA'))
            f.write(govde)
        return os.path.getsize(yol)


T0 = 5_000_000


def _yol(s, sure):
    """Kalkış 20. sn, iniş sure-25. sn; 800 m yarıçaplı daire, 120 m AGL."""
    hava = (s > 20) & (s < sure - 25)
    ang = np.clip((s - 20) / max(1.0, sure - 45), 0, 1) * 2 * math.pi * max(1, sure / 400)
    r = np.where(hava, 800.0, 0.0)
    lat = 39.9 + r * np.cos(ang) / 110574
    lng = 32.8 + r * np.sin(ang) / 85000
    z = np.where(hava, np.minimum(120.0, (s - 20) * 4), 0.0)
    hiz = np.where(hava, 22.0 + np.sin(s / 7) * 3, 0.0)
    return hava, lat, lng, z, hiz, ang


def sentetik(yol, varyant='plane', sure=300.0, hz=25, bozuk=True):
    w = Yazici()
    w.tip(64, 'PARM', 'QNf', 'TimeUS,Name,Value')
    w.tip(65, 'MSG', 'QZ', 'TimeUS,Message')
    w.tip(67, 'EV', 'QB', 'TimeUS,Id')
    w.tip(69, 'ERR', 'QBB', 'TimeUS,Subsys,ECode')
    w.tip(90, 'XTRA', 'QB', 'TimeUS,V')
    w.tip(71, 'ATT', 'QccccCCCC', 'TimeUS,DesRoll,Roll,DesPitch,Pitch,DesYaw,Yaw,ErrRP,ErrYaw')
    w.tip(70, 'POS', 'QLLfff', 'TimeUS,Lat,Lng,Alt,RelHomeAlt,RelOriginAlt')
    w.tip(72, 'BARO', 'QBffcfIffB', 'TimeUS,I,Alt,Press,Temp,CRt,SMS,Offset,GndTemp,Health')
    rng = np.random.default_rng(7)
    tH = T0 + np.arange(0, sure, 1.0 / hz) * 1e6
    s = (tH - T0) / 1e6
    hava, lat, lng, z, hiz, ang = _yol(s, sure)
    roll = np.where(hava, 18.0, 0.0) + np.sin(s) * 3 + rng.normal(0, 0.7, len(s))
    w.ekle('ATT', tH + 1, DesRoll=np.round(roll + rng.normal(0, 2, len(s)), 2), Roll=roll, DesPitch=np.where(hava, 4.0, 0.0),
           Pitch=np.where(hava, 3.0, 0.0) + rng.normal(0, 1, len(s)), Yaw=np.mod(np.degrees(ang) + 90, 360))
    pos_bas = s >= 6.0                                                         # POS 6. sn'de başlar (öncesi BARO irtifası)
    rel = z + rng.normal(0, 0.3, len(s))
    rel[(np.arange(len(s)) % 997) == 13] = np.nan                              # arada NaN RelHomeAlt
    w.ekle('POS', tH[pos_bas] + 2, Lat=lat[pos_bas], Lng=lng[pos_bas], Alt=900 + z[pos_bas], RelHomeAlt=rel[pos_bas], RelOriginAlt=z[pos_bas])
    t10 = T0 + np.arange(0, sure, 0.1) * 1e6
    s10 = (t10 - T0) / 1e6
    h10, *_ = _yol(s10, sure)
    for i in (0, 1):
        w.ekle('BARO', t10 + 3 + i, I=np.full(len(t10), i), Alt=_yol(s10, sure)[3] + rng.normal(0, 0.5, len(s10)) + 50 * i)
    t5 = T0 + np.arange(0, sure, 0.2) * 1e6
    s5 = (t5 - T0) / 1e6
    _h5, lat5, lng5, z5, hiz5, ang5 = _yol(s5, sure)
    gps_ek = {'GMS': ((s5 * 1000) + 302_400_000).astype(np.int64), 'GWk': np.where(s5 > 4, 2420, 0), 'NSats': np.where(s5 > 60, 19, 9),
              'HDop': np.where(s5 > 100, 0.65, 2.4), 'Lat': lat5, 'Lng': lng5, 'Alt': 900 + z5, 'Spd': hiz5, 'GCrs': np.mod(np.degrees(ang5) + 90, 360)}
    parm = [('THR_MAX', 100), ('ARSPD_USE', 1)]
    if varyant in ('plane', 'throut'):
        w.tip(66, 'MODE', 'QMBB', 'TimeUS,Mode,ModeNum,Rsn')
        w.tip(68, 'ARM', 'QBIBH', 'TimeUS,ArmState,ArmChecks,Forced,Method')
        w.tip(73, 'GPS', 'QBBIHBcLLeffffB', 'TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U')
        w.tip(74, 'BAT', 'QBfffffcfB', 'TimeUS,Inst,Volt,VoltR,Curr,CurrTot,EnrgTot,Temp,Res,RemPct')
        w.tip(76, 'XKF2', 'QBfffffff', 'TimeUS,C,AX,AY,AZ,VWN,VWE,MN,ME')
        w.tip(77, 'ARSP', 'QBffcffBBfB', 'TimeUS,I,Airspeed,DiffPress,Temp,RawPress,Offset,U,H,Hp,Pri')
        w.tip(78, 'STAT', 'QBfBBBBB', 'TimeUS,isFlying,isFlyProb,Armed,Safety,Crash,Still,Stage')
        w.tip(79, 'ORGN', 'QBLLe', 'TimeUS,Type,Lat,Lng,Alt')
        w.tip(80, 'VIBE', 'QBfffI', 'TimeUS,IMU,VibeX,VibeY,VibeZ,Clip')
        for i in (0, 1):
            w.ekle('GPS', t5 + 4 + i, I=np.full(len(t5), i), Status=np.where(s5 >= 3, 3 + i, 1), **gps_ek)
            w.ekle('BAT', t10 + 5 + i, Inst=np.full(len(t10), i), Volt=np.where(s10 < 1, 0.2, 16.8 - s10 / sure * 2.5 + i),
                   Curr=np.where(h10, 14.0 + np.sin(s10), 1.2), CurrTot=s10 * 3.1, EnrgTot=np.where(s10 > 2, s10 * 0.05, np.nan),
                   RemPct=np.floor(100 - s10 / sure * 70))
            w.ekle('XKF2', tH + 6 + i, C=np.full(len(tH), i), VWN=-3 + np.sin(s / 30), VWE=2.5 + rng.normal(0, 0.2, len(s)))
            w.ekle('VIBE', t10 + 7 + i, IMU=np.full(len(t10), i), VibeX=12 + rng.random(len(t10)) * 9, VibeY=10 + rng.random(len(t10)) * 8,
                   VibeZ=20 + rng.random(len(t10)) * 25, Clip=np.cumsum(rng.random(len(t10)) < 0.01))
        w.ekle('ARSP', t10 + 8, I=np.zeros(len(t10)), Airspeed=np.where(h10, 24 + np.sin(s10), 0.4))
        w.ekle('STAT', t10 + 9, isFlying=h10.astype(int), Armed=np.ones(len(t10)))
        w.ekle('ORGN', [T0 + 1_500_000, T0 + 2_000_000], Type=[1, 0], Lat=[39.8, 39.9], Lng=[32.7, 32.8], Alt=[850, 900.25])
        w.ekle('MODE', [T0 - 800, T0 + 30_000_000, T0 + 200_000_000], Mode=[0, 10, 11], ModeNum=[0, 10, 11], Rsn=[0, 1, 2])
        w.ekle('ARM', [T0 + 15_000_000, T0 + (sure - 10) * 1e6], ArmState=[1, 0])
        firm, kart = 'ArduPlane V4.7.1 (test)', 'Pixhawk6C 003A0021 32315112 34323837'
        if varyant == 'throut':   # eski Copter CTUN: ThrOut tamsayı (0/1 → int, 50+ → float)
            w.tip(75, 'CTUN', 'Qhhf', 'TimeUS,ThrIn,ThrOut,As')
            w.ekle('CTUN', tH + 10, ThrOut=np.where(hava, 40 + (np.arange(len(s)) % 50), np.arange(len(s)) % 2), As=hiz)
        else:
            w.tip(75, 'CTUN', 'Qccccfffh', 'TimeUS,NavRoll,Roll,NavPitch,Pitch,ThO,ThD,As,RdrOut')
            w.ekle('CTUN', tH + 10, ThO=np.where(hava, 55 + np.sin(s) * 10, np.where(s > 15, 1.2, 0.0)), As=hiz)
    else:   # eski Copter
        w.tip(66, 'MODE', 'QM', 'TimeUS,Mode')
        w.tip(73, 'GPS', 'QBIHBcLLeffffB', 'TimeUS,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U')
        w.tip(74, 'CURR', 'IfffH', 'TimeMS,Volt,Curr,CurrTot,Vcc')
        w.tip(76, 'NKF2', 'Qffffff', 'TimeUS,AX,AY,AZ,VWN,VWE,MN')
        w.tip(80, 'VIBE', 'QfffIII', 'TimeUS,VibeX,VibeY,VibeZ,Clip0,Clip1,Clip2')
        w.tip(75, 'CTUN', 'Qffffh', 'TimeUS,ThI,ThO,DAlt,As,N')
        w.ekle('GPS', t5 + 4, Status=np.where(s5 >= 3, 3, 1), **gps_ek)
        w.ekle('CURR', t10 + 5, Volt=12.6 - s10 / sure * 1.5, Curr=np.where(h10, 22.0, 0.8), CurrTot=s10 * 6.2)
        w.ekle('NKF2', tH + 6, VWN=0.2 + rng.normal(0, 0.05, len(s)), VWE=0.1 + rng.normal(0, 0.05, len(s)))
        w.ekle('VIBE', t10 + 7, VibeX=35 + rng.random(len(t10)) * 40, VibeY=8 + rng.random(len(t10)), VibeZ=9 + rng.random(len(t10)),
               Clip0=np.cumsum(rng.random(len(t10)) < 0.05), Clip1=np.zeros(len(t10)), Clip2=np.full(len(t10), 3))
        w.ekle('CTUN', tH + 10, ThO=np.where(hava, 0.45 + np.sin(s) * 0.05, 0.0), As=np.where(s > 50, np.nan, hiz))
        w.ekle('MODE', [T0 - 800, T0 + 40_000_000], Mode=[0, 5])
        firm, kart = 'ArduCopter V3.6.12 (test)', 'fmuv3 00320033 35365115 30313733'
    msj = [(T0 - 900, firm), (T0 - 850, kart), (T0 + 15_000_000, 'Throttle armed'),
           (T0 + 70_000_000, 'Uçuş modu değişti: ğüşıöç'.encode() + b'\x00\xff\xfe cop'),        # NUL sonrası UTF-8 olmayan çöp → ISO-8859-1
           (T0 + 80_000_000, b'Bad AHRS \x00'), (T0 + 90_000_000, 'EKF failsafe cleared')]
    for t, m in msj:
        w.ekle('MSG', [t], Message=[m if isinstance(m, bytes) else m.encode()])
    for i, (ad, v) in enumerate(parm):
        w.ekle('PARM', [T0 - 1000 + i], Name=[ad.encode()], Value=[v])
    w.ekle('EV', [T0 + 15_000_000, T0 + 21_000_000, T0 + 30_000_000, T0 + (sure - 10) * 1e6], Id=[10, 28, 99, 11])
    w.ekle('ERR', [T0 + 50_000_000, T0 + 52_000_000, T0 + 60_000_000], Subsys=[11, 11, 77], ECode=[2, 0, 1])
    return w.yaz(yol, bozuk=bozuk)


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text[:300])
    return r.json()


def bekle(fn, sn=10.0, adim=0.05):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


@contextlib.contextmanager
def _sessiz():
    """pymavlink indeksleyicisi (C) bozuk baytta doğrudan 1/2 numaralı dosyalara yazar: tanımlayıcı düzeyinde sustur."""
    sys.stdout.flush()
    sys.stderr.flush()
    yedek = [os.dup(1), os.dup(2)]
    bos = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(bos, 1)
        os.dup2(bos, 2)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        os.dup2(yedek[0], 1)
        os.dup2(yedek[1], 2)
        for f in yedek + [bos]:
            os.close(f)


def _esit(yol):
    with _sessiz():
        eski = flightlog._analyze_pymavlink(yol)
    yeni = flightlog._analyze_hizli(yol)
    a, b = json.dumps(eski, ensure_ascii=False), json.dumps(yeni, ensure_ascii=False)
    if a != b:
        fark = [k for k in eski if json.dumps(eski[k]) != json.dumps(yeni.get(k))]
        ozet = [k for k in eski['summary'] if json.dumps(eski['summary'][k]) != json.dumps(yeni['summary'].get(k))]
        raise AssertionError(f'{yol}: hızlı ≠ pymavlink; farklı alanlar {fark}, özet {ozet}')
    return eski


# ---------------------------------------------------------------- 1) eşdeğerlik
def esdegerlik_testleri(d):
    r = _esit(ORNEK)
    assert r['summary']['vehicle'] and r['series'], r['summary']
    print('  arduplane-sample.bin: hızlı = pymavlink')
    for varyant, sure in (('plane', 420.0), ('copter', 300.0), ('throut', 200.0)):
        yol = os.path.join(d, f'sentetik-{varyant}.bin')
        sentetik(yol, varyant, sure=sure)
        r = _esit(yol)
        s = r['summary']
        if varyant == 'plane':
            assert s['flight_s'] > 0 and s['as_max'] and s['wind_dir'] is not None and s['clips'] and s['bat_end_pct'] is not None, s
            assert s['firmware'].startswith('ArduPlane') and s['board'] == 'Pixhawk6C' and s['home']['alt'] == 900.25, s
            assert any(m['text'].startswith('UÃ§uÅ\x9f') for m in r['messages']), r['messages']   # pymavlink: tümü ISO-8859-1
            assert len(r['errors']) == 3 and any(e['resolved'] for e in r['errors']) and r['modes'], r['errors']
        elif varyant == 'copter':
            assert s['flight_s'] > 0 and s['as_max'] is not None and s['bat_used_mah'] is not None and s['clips'] > 0, s
            assert s['firmware'].startswith('ArduCopter') and s['board'] == 'fmuv3' and r['modes'][-1]['name'], s
        else:
            thr = [v for _t, v in r['series']['thr']]
            assert any(isinstance(v, int) for v in thr) and any(isinstance(v, float) for v in thr), thr[:10]
        print(f'  sentetik {varyant} ({os.path.getsize(yol) / 1e6:.1f} MB): hızlı = pymavlink')
    for yol in [p for p in os.environ.get('BINANALYZE_GERCEK', '').split(':') if p and os.path.isfile(p)]:
        t = time.time()
        _esit(yol)
        print(f'  gerçek {os.path.basename(yol)} ({os.path.getsize(yol) / 1e6:.0f} MB): hızlı = pymavlink ({time.time() - t:.0f} sn)')


# ---------------------------------------------------------------- 2) alt süreç CLI: ilerleme, nice, RLIMIT_AS, PDEATHSIG, bellek
def _vmhwm(pid):
    try:
        with open(f'/proc/{pid}/status') as f:
            for sat in f:
                if sat.startswith('VmHWM:'):
                    return int(sat.split()[1]) * 1024
    except OSError:
        pass
    return 0


def alt_surec_testleri(d):
    yol = os.path.join(d, 'buyuk.bin')
    t = time.time()
    boyut = sentetik(yol, 'plane', sure=3 * 3600.0, hz=25, bozuk=False)
    print(f'  büyük sentetik .BIN: {boyut / 1e6:.0f} MB ({time.time() - t:.1f} sn)')
    cikti = os.path.join(d, 'buyuk.json')
    env = dict(os.environ, FLIGHTLOG_ANALIZ_NICE='9', FLIGHTLOG_ANALIZ_BELLEK_MB='2048')
    t = time.time()
    p = subprocess.Popen([sys.executable, '-m', 'app.flightlog', 'analyze', yol, cikti, str(os.getpid())], cwd=str(config.BASE_DIR),
                         env=env, stdout=subprocess.PIPE, text=True)
    yuzde, hwm, nice, limit = [], 0, None, None
    for sat in p.stdout:
        if sat.startswith('P '):
            yuzde.append(int(sat[2:]))
            hwm = max(hwm, _vmhwm(p.pid))
            if nice is None:
                try:
                    nice = int(open(f'/proc/{p.pid}/stat').read().rsplit(')', 1)[1].split()[16])
                    limit = [x for x in open(f'/proc/{p.pid}/limits') if x.startswith('Max address space')][0].split()[3]
                except (OSError, IndexError, ValueError):
                    pass
        elif sat.strip() == 'OK':
            hwm = max(hwm, _vmhwm(p.pid))
    p.wait()
    sure = time.time() - t
    assert p.returncode == 0 and os.path.exists(cikti), p.returncode
    assert yuzde == sorted(yuzde) and yuzde[-1] == 100 and len(yuzde) >= 5, yuzde   # 16 MB blok başına + son işlem
    assert nice == 9 and limit == str(2048 * 1024 * 1024), (nice, limit)
    r = json.load(open(cikti))
    assert r['summary']['flight_s'] > 3 * 3600 - 100, r['summary']['flight_s']
    print(f'  CLI analiz: {sure:.1f} sn, tepe bellek {hwm / 1e6:.0f} MB, nice {nice}, RLIMIT_AS {int(limit) >> 20} MB, ilerleme {len(yuzde)} adım')
    assert hwm < 900e6, hwm
    # ebeveyn ölünce çocuk da ölür (PDEATHSIG) — sunucu çökerse yetim analiz süreci kalmaz
    ara = subprocess.Popen([sys.executable, '-c', 'import os, subprocess, sys, time\n'
                            'p = subprocess.Popen([sys.executable, "-m", "app.flightlog", "analyze", sys.argv[1], sys.argv[2], str(os.getpid())])\n'
                            'print(p.pid, flush=True)\ntime.sleep(60)\n', yol, os.path.join(d, 'yetim.json')],
                           cwd=str(config.BASE_DIR), stdout=subprocess.PIPE, text=True)
    cocuk = int(ara.stdout.readline())
    time.sleep(0.8)
    ara.kill()
    ara.wait()

    def oldu():
        try:
            with open(f'/proc/{cocuk}/stat') as f:
                return f.read().rsplit(')', 1)[1].split()[0] == 'Z'
        except OSError:
            return True
    assert bekle(oldu, 5), 'ebeveyn öldükten sonra analiz süreci yaşıyor'
    print('  ebeveyn ölünce analiz süreci de sonlanıyor (PDEATHSIG)')
    return yol


# ---------------------------------------------------------------- 3) kuyruk, ilerleme API, yeniden başlatma, hatalar
def _durum(lid):
    with db.connect() as conn:
        return db.row(conn.execute('SELECT status, progress, error, analysis FROM flight_logs WHERE id = ?', (lid,)))


def _ekle(yol, ad):
    hedef = config.UPLOAD_DIR / 'flightlogs'
    hedef.mkdir(parents=True, exist_ok=True)
    shutil.copy(yol, hedef / ad)
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO flight_logs (file, file_name, size, uploaded_by, uploaded_at) VALUES (?, ?, ?, 1, ?)",
                           (f'flightlogs/{ad}', ad, os.path.getsize(yol), db.now()))
        return cur.lastrowid


def kuyruk_testleri(a, d, buyuk):
    assert flight_analysis.PARALEL == 1
    # yükleme ucu analizi beklemez
    with open(buyuk, 'rb') as f:
        veri = f.read()
    t = time.time()
    r = a.post('/api/tools/flight-logs', files={'file': ('buyuk.bin', veri, 'application/octet-stream')})
    lid1 = ok(r)['id']
    gecen = time.time() - t
    assert _durum(lid1)['status'] == 'ISLENIYOR', _durum(lid1)
    lid2 = ok(a.post('/api/tools/flight-logs', files={'file': ('ornek.bin', open(ORNEK, 'rb').read(), 'application/octet-stream')}))['id']
    lid3 = ok(a.post('/api/tools/flight-logs', files={'file': ('bozuk.bin', b'bu bir log degil' * 500, 'application/octet-stream')}))['id']
    print(f'  yükleme ucu {len(veri) / 1e6:.0f} MB için {gecen:.2f} sn içinde döndü (analiz kuyrukta)')
    gorulen_pct, en_cok = set(), 0
    sira_goruldu = False
    bitis = time.time() + 120
    while time.time() < bitis:
        L = {x['id']: x for x in ok(a.get('/api/tools/flight-logs'))}
        calisan = [x for x in L.values() if x['status'] == 'ISLENIYOR' and x['progress'] is not None]
        en_cok = max(en_cok, len(flight_analysis.durum()) and sum(1 for v in flight_analysis.durum().values() if v['queue'] is None))
        if L[lid1]['status'] == 'ISLENIYOR' and L[lid1]['progress'] is not None:
            gorulen_pct.add(L[lid1]['progress'])
            if L[lid2]['status'] == 'ISLENIYOR':
                assert L[lid2]['progress'] is None and L[lid2]['queue'] == 1 and L[lid3]['queue'] == 2, (L[lid2], L[lid3])
                sira_goruldu = True
        assert len(calisan) <= 1, calisan
        if all(L[i]['status'] != 'ISLENIYOR' for i in (lid1, lid2, lid3)):
            break
        time.sleep(0.1)
    d1, d2, d3 = _durum(lid1), _durum(lid2), _durum(lid3)
    assert d1['status'] == 'TAMAM' and d2['status'] == 'TAMAM' and d3['status'] == 'HATA', (d1['status'], d2['status'], d3)
    assert d1['progress'] is None and 'Log çözümlenemedi' in d3['error'], d3
    assert sira_goruldu and len(gorulen_pct) >= 2 and en_cok <= 1, (sira_goruldu, gorulen_pct, en_cok)
    with _sessiz():
        assert json.loads(d2['analysis']) == json.loads(json.dumps(flightlog._analyze_pymavlink(ORNEK), ensure_ascii=False))
    g = ok(a.get(f'/api/flight-logs/{lid1}'))
    assert g['status'] == 'TAMAM' and g['analysis']['summary']['flight_s'] > 0 and 'progress' in g and 'queue' in g
    print(f'  kuyruk: aynı anda en çok 1 analiz, sıradakiler queue 1/2, ilerleme API\'de {sorted(gorulen_pct)[:6]}… görüldü; bozuk → HATA')
    assert not list((config.UPLOAD_DIR / 'flightlogs').glob('*.analiz.json*')), 'geçici çıktı dosyası kaldı'

    # yeniden başlatma: ISLENIYOR'da (progress 57) kalmış kayıt + yarım çıktı dosyası → baştan analiz
    lid = _ekle(ORNEK, 'yarim.bin')
    with db.connect() as conn:
        conn.execute("UPDATE flight_logs SET progress = 57 WHERE id = ?", (lid,))
    (config.UPLOAD_DIR / 'flightlogs' / 'yarim.bin.analiz.json').write_text('{"yarim": ')
    flight_analysis.resume_pending()
    st = bekle(lambda: _durum(lid)['status'] != 'ISLENIYOR' and _durum(lid), 30)
    assert st['status'] == 'TAMAM' and st['progress'] is None and json.loads(st['analysis']) == json.loads(d2['analysis']), st['status']
    print('  yeniden başlatma: ISLENIYOR (progress 57) kayıt baştan analiz edildi → TAMAM')

    # zaman aşımı ve bellek tavanı → HATA (ISLENIYOR'da takılmaz)
    eski = flight_analysis.ZAMAN_ASIMI_S
    flight_analysis.ZAMAN_ASIMI_S = 0.5
    try:
        lid = _ekle(buyuk, 'asim.bin')
        flight_analysis.start(lid)
        st = bekle(lambda: _durum(lid)['status'] != 'ISLENIYOR' and _durum(lid), 30)
        assert st['status'] == 'HATA' and 'zaman aşımı' in st['error'], st
    finally:
        flight_analysis.ZAMAN_ASIMI_S = eski
    eski = flight_analysis.BELLEK_MB
    flight_analysis.BELLEK_MB = 120
    try:
        lid = _ekle(buyuk, 'bellek.bin')
        flight_analysis.start(lid)
        st = bekle(lambda: _durum(lid)['status'] != 'ISLENIYOR' and _durum(lid), 60)
        assert st['status'] == 'HATA', st
    finally:
        flight_analysis.BELLEK_MB = eski
    print(f'  zaman aşımı → HATA; bellek tavanı (120 MB) → HATA ("{st["error"][:70]}")')


def main():
    d = tempfile.mkdtemp(prefix='binanalyze-')
    try:
        print('Uçuş logu analizi (hızlı okuyucu + alt süreç + kuyruk)')
        esdegerlik_testleri(d)
        buyuk = alt_surec_testleri(d)
        with TestClient(app, base_url='https://testserver') as a:
            ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
            kuyruk_testleri(a, d, buyuk)
        print('TÜM TESTLER GEÇTİ')
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(os.environ['CAYMAZ_DATA_DIR'], ignore_errors=True)


if __name__ == '__main__':
    main()
