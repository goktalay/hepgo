"""MAVLink telemetri kaydı (.tlog) — Uçuş Logları'na yükleme ve analiz (app/tlog.py; docs/ucus-simulatoru.md §8.6).

Kapsam:
  * İçerik doğrulama (tlog.dogrula): geçerli kayıt ✓; boş, metin, DataFlash (.BIN) başlığı, rastgele bayt, zaman damgasız ham MAVLink → anlaşılır hata.
  * Araç seçimi: GCS (255), gimbal bileşeni, MAV_AUTOPILOT_INVALID sayılmaz; birden çok sysid → en çok HEARTBEAT'li otopilot.
  * Analiz (flightlog.analyze → tlog.analiz): .bin analiziyle aynı şema (summary anahtarları, series anahtarları), makul değerler (süre,
    uçuş süresi, mesafe, irtifa, hız, modlar, ARM/DISARM, batarya, titreşim, rüzgâr, GPS, bulgular), EXTENDED_SYS_STATE'li uçuş aralığı,
    bozuk bayt / yarım kalmış son paket toleransı, summary.missing.
  * 3B oynatma (flightlog.replay) ve CLI alt süreç (`python -m app.flightlog analyze`).
  * HTTP: Araçlar › Uçuş Logu Analizi tek istek ve parça parça yükleme (.tlog kabul), bozuk .tlog → 400 + dosya silinir, .txt → 400,
    analiz TAMAM, rapor ucu summary.source = 'tlog', /replay ucu.

Çalıştırma: .venv/bin/python -m tests.test_tlog
"""
import json
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', FLIGHTLOG_ANALIZ_PARALEL='1')

from fastapi.testclient import TestClient  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as D  # noqa: E402

from app import config, flightlog, tlog  # noqa: E402
from app.main import app  # noqa: E402

T_ABS = 1_700_000_000.0
LAT0, LON0 = 39.925, 32.837


def tlog_yaz(yol, sure=60.0, ikinci_hb=5.0, ikinci_baskin=False, ext_state=False, cop=False, yarim=False, v1=False, arsp=True):
    """Sentetik .tlog (8 bayt BE µs + MAVLink çerçevesi). Araç 1 (ArduCopter, quad): 10 sn yerde, ARM, 10–15 tırmanış (30 m), 15–50 100 m
    yarıçaplı daire, 50–55 iniş, DISARM; STABILIZE → LOITER (t ≥ 20) → STABILIZE. Ayrıca: GCS (sysid 255, tip 6, autopilot 8), araç 1'in
    gimbal bileşeni (compid 154, tip 26) ve araç 2 (sysid 2, plane, başka konum; `ikinci_hb` sn'de bir HEARTBEAT — `ikinci_baskin` ise
    araç 1'den sık). `arsp`: SYS_STATUS'ta hava hızı sensörü (bit 16) var; `ext_state`: EXTENDED_SYS_STATE (landed_state); `cop`: ortalara rastgele bayt; `yarim`: son paket yarım; `v1`: MAVLink1."""
    if v1:
        from pymavlink.dialects.v10 import ardupilotmega as Dm
    else:
        Dm = D
    mav = Dm.MAVLink(None, srcSystem=1, srcComponent=1)
    gcs = Dm.MAVLink(None, srcSystem=255, srcComponent=190)
    gim = Dm.MAVLink(None, srcSystem=1, srcComponent=154)
    ar2 = Dm.MAVLink(None, srcSystem=2, srcComponent=1)
    rnd = random.Random(7)
    with open(yol, 'wb') as f:
        def yaz(kim, msg, t):
            f.write(struct.pack('>Q', int((T_ABS + t) * 1e6)))
            f.write(msg.pack(kim))
            kim.seq = (kim.seq + 1) % 256
        t = 0.0
        while t <= sure + 1e-9:
            armed = 10.0 <= t < 55.0
            mode = 5 if (armed and t >= 20) else 0
            if 15 <= t < 50 and armed:
                ang = (t - 15) / 35 * 2 * math.pi
                lat, lon, z = LAT0 + 100 * math.cos(ang) / 110574, LON0 + 100 * math.sin(ang) / (111320 * math.cos(math.radians(LAT0))), 30.0
                vn, ve = -100 * 2 * math.pi / 35 * math.sin(ang), 100 * 2 * math.pi / 35 * math.cos(ang)
            else:
                lat, lon, vn, ve = LAT0, LON0, 0.0, 0.0
                z = 30.0 * min(1, (t - 10) / 5) if armed and t < 50 else (30.0 * max(0, (55 - t) / 5) if armed else 0.0)
            gs = math.hypot(vn, ve)
            yaw = math.atan2(ve, vn) if gs else 0.0
            tam = abs(t - round(t)) < 1e-6
            if tam:   # 1 Hz
                yaz(mav, mav.heartbeat_encode(2, 3, (128 if armed else 0) | 1, mode, 4 if armed else 3), t)
                yaz(gcs, gcs.heartbeat_encode(6, 8, 0, 0, 0), t)
                yaz(gim, gim.heartbeat_encode(26, 8 if int(t) % 2 else 0, 0, 0, 0), t)
                if ikinci_baskin or int(t) % int(ikinci_hb) == 0:
                    for _ in range(3 if ikinci_baskin else 1):
                        yaz(ar2, ar2.heartbeat_encode(1, 3, 1, 10, 4), t)
                    yaz(ar2, ar2.global_position_int_encode(int(t * 1000), int(41.0 * 1e7), int(29.0 * 1e7), 150000, 50000, 1500, 0, 0, 0), t)
                yaz(mav, mav.sys_status_encode(0x10000 | 32 | (16 if arsp else 0), 0, 0, 500, 16200 - int(t * 10), 1200 if armed else 50, 95 - int(t // 10),
                                               0, 0, 0, 0, 0, 0), t)
                yaz(mav, mav.battery_status_encode(0, 0, 0, 2500, [16200 - int(t * 10)] + [65535] * 9, 1200 if armed else 50,
                                                   int(t * 10), int(t * 20), 95 - int(t // 10)), t)
                yaz(mav, mav.gps_raw_int_encode(int((T_ABS + t) * 1e6), 3, int(lat * 1e7), int(lon * 1e7), int((900 + z) * 1000), 80, 120,
                                                int(gs * 100), 0, 12 if t < 40 else 7), t)
                yaz(mav, mav.vibration_encode(int(t * 1e6), 12.0 + (20 if 30 <= t < 31 else 0), 9.0, 15.0, 0, int(t // 20), 0), t)
                yaz(mav, mav.wind_encode(270.0, 4.0, 0.0), t)   # batıdan esen 4 m/s
                if ext_state:
                    yaz(mav, mav.extended_sys_state_encode(0, 2 if 12 <= t < 52 else 1), t)
                if t == 0:
                    yaz(mav, mav.statustext_encode(6, b'ArduCopter V4.5.7 (test)'), t)
                    yaz(mav, mav.statustext_encode(6, b'CubeOrange 00330012 3436510A'), t)
                    yaz(mav, mav.home_position_encode(int(LAT0 * 1e7), int(LON0 * 1e7), 900000, 0, 0, 0, [1, 0, 0, 0], 0, 0, 0), t)
                    for i, ad in enumerate((b'ARMING_CHECK', b'BATT_MONITOR', b'SERVO1_FUNCTION')):
                        yaz(mav, mav.param_value_encode(ad, 1.0, 9, 3, i), t)
                    yaz(gcs, gcs.statustext_encode(6, b'GCS mesaji (sayilmaz)'), t)
                if t == 30:
                    yaz(mav, mav.statustext_encode(4, b'Low battery warning (test)'), t)
                if t == 45:
                    yaz(mav, mav.statustext_encode(2, b'EKF variance (test)'), t)
                if cop and t in (20.0, 40.0):
                    f.write(bytes(rnd.randrange(256) for _ in range(333)))
            yaz(mav, mav.global_position_int_encode(int(t * 1000), int(lat * 1e7), int(lon * 1e7), int((900 + z) * 1000), int(z * 1000),
                                                    int(vn * 100), int(ve * 100), 0, int((math.degrees(yaw) % 360) * 100)), t)
            yaz(mav, mav.attitude_encode(int(t * 1000), math.radians(10) if 15 <= t < 50 else 0.0, -0.05 if armed else 0.0, yaw, 0, 0, 0), t)
            if tam or abs(t * 2 - round(t * 2)) < 1e-6:   # 2 Hz istenen tutum
                yaz(mav, mav.nav_controller_output_encode(12.0 if 15 <= t < 50 else 0.0, 0.0, 0, 0, 0, 0, 0, 0), t)
            yaz(mav, mav.vfr_hud_encode(gs + 1, gs, int(math.degrees(yaw) % 360), 55 if armed else 0, 900 + z, 0.0), t)
            t = round(t + 0.2, 3)   # 5 Hz
        if yarim:
            f.write(struct.pack('>Q', int((T_ABS + t) * 1e6)) + mav.heartbeat_encode(2, 3, 1, 0, 3).pack(mav)[:7])


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text[:300])
    return r.json()


def bekle(fn, sn=30.0, adim=0.1):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def hata_bekle(yol, parca):
    try:
        tlog.dogrula(yol)
    except tlog.TlogHatasi as e:
        assert parca in str(e), (parca, str(e))
        return str(e)
    raise AssertionError(f'hata beklenirdi: {yol}')


def dogrulama_testleri(d):
    yol = os.path.join(d, 'iyi.tlog')
    tlog_yaz(yol)
    r = tlog.dogrula(yol)
    assert r['cerceve'] > 1000 and r['damgali'] == r['cerceve'] and r['atlanan'] == 0, r
    bos = os.path.join(d, 'bos.tlog')
    open(bos, 'wb').close()
    hata_bekle(bos, 'boş')
    metin = os.path.join(d, 'metin.tlog')
    with open(metin, 'w') as f:
        f.write('2026-10-21 12:00:00 Mission Planner log\n' * 400)
    hata_bekle(metin, 'metin')
    df = os.path.join(d, 'df.tlog')
    with open(df, 'wb') as f:
        f.write(b'\xa3\x95\x80' + bytes(200))
    hata_bekle(df, '.bin uzantısıyla')
    rast = os.path.join(d, 'rastgele.tlog')
    with open(rast, 'wb') as f:
        f.write(random.Random(1).randbytes(300_000))
    hata_bekle(rast, 'MAVLink telemetri kaydı (.tlog) değil')
    ham = os.path.join(d, 'ham.tlog')   # zaman damgasız ham MAVLink akışı
    mav = D.MAVLink(None, srcSystem=1, srcComponent=1)
    with open(ham, 'wb') as f:
        for i in range(200):
            f.write(mav.heartbeat_encode(2, 3, 0, 0, 3).pack(mav))
            f.write(mav.attitude_encode(i, 0, 0, 0, 0, 0, 0).pack(mav))
    hata_bekle(ham, 'zaman damgası yok')
    try:
        flightlog.analyze(rast)
        raise AssertionError('rastgele bayt analiz edilmemeli')
    except ValueError as e:
        assert 'MAVLink' in str(e), e
    print('  doğrulama: geçerli ✓; boş / metin / DataFlash / rastgele / damgasız ham → anlaşılır hata')


def arac_secimi_testleri(d):
    yol = os.path.join(d, 'cok.tlog')
    tlog_yaz(yol)
    r = tlog.tara(yol)
    sec = tlog.arac_sec(r['hb'])
    assert sec == (1, 1, 2, 3), sec   # GCS 255, gimbal (154) ve autopilot 8 sayılmaz; araç 2 daha az HEARTBEAT
    a = flightlog.analyze(yol)
    s = a['summary']
    assert s['sysid'] == 1 and s['compid'] == 1 and s['other_systems'] == [2, 255], s
    assert abs(s['home']['lat'] - LAT0) < 1e-6, s['home']   # araç 2'nin konumu (41, 29) karışmadı
    assert all(abs(p[0] - LAT0) < 0.01 for p in a['track']), a['track'][:3]
    assert not any('GCS' in m['text'] for m in a['messages']), a['messages']
    yol2 = os.path.join(d, 'baskin.tlog')   # araç 2 araç 1'den çok HEARTBEAT gönderiyor → o seçilir
    tlog_yaz(yol2, ikinci_baskin=True)
    a2 = flightlog.analyze(yol2)
    s2 = a2['summary']
    assert s2['sysid'] == 2 and s2['vehicle'] == 'ArduPlane' and abs(s2['home']['lat'] - 41.0) < 1e-6, s2
    assert a2['modes'][0]['name'] == 'AUTO', a2['modes']   # ArduPlane custom_mode 10 = AUTO
    # Uçuş Simülatörü kayıttan oynatma ayrıştırıcısı da aynı aracı seçer (gimbal HEARTBEAT'i mod/ARM sayılmaz)
    from app import flightsim_replay as R
    r1 = R._tlog_ayristir(yol, R.REPLAY_HZ)
    assert r1['modes'] == ['STABILIZE', 'LOITER'] and r1['vehicle'] == 'ArduCopter' and r1['home']['lat'] == LAT0 and r1['takeoff_t'] == 10.0, r1['modes']
    r2 = R._tlog_ayristir(yol2, R.REPLAY_HZ)
    assert r2['modes'] == ['AUTO'] and r2['vehicle'] == 'ArduPlane' and r2['home']['lat'] == 41.0, (r2['modes'], r2['home'])
    print('  araç seçimi: GCS/gimbal/invalid atlanır; çok sysid → en çok HEARTBEAT (1 ya da 2); simülatör ayrıştırıcısı aynı')


def analiz_testleri(d):
    yol = os.path.join(d, 'ucus.tlog')
    tlog_yaz(yol)
    a = flightlog.analyze(yol)
    s = a['summary']
    # .bin analiziyle aynı şema: tüm summary anahtarları + seri anahtarları
    bin_anahtar = {'firmware', 'board', 'params', 'vehicle', 'start_utc', 'takeoff_utc', 'landing_utc', 'takeoff_t', 'landing_t', 'duration_s',
                   'armed_s', 'flight_s', 'flights', 'distance_m', 'max_home_m', 'home', 'alt_max', 'alt_avg', 'gs_max', 'gs_avg', 'as_max',
                   'as_avg', 'climb_max', 'sink_max', 'roll_max', 'pitch_max', 'roll_err_rms', 'pitch_err_rms', 'thr_avg', 'bat_start_v',
                   'bat_end_v', 'bat_min_v', 'bat_max_a', 'bat_avg_a', 'bat_used_mah', 'bat_used_wh', 'bat_end_pct', 'sats_min', 'sats_avg',
                   'hdop_max', 'vibe_max', 'clips', 'wind_avg', 'wind_max', 'wind_dir'}
    assert bin_anahtar <= set(s), bin_anahtar - set(s)
    assert set(a) == {'summary', 'findings', 'modes', 'events', 'errors', 'messages', 'flying', 'track', 'series'}, set(a)
    assert set(a['series']) == set(flightlog._SERI), set(a['series'])
    assert s['source'] == 'tlog' and s['firmware'] == 'ArduCopter V4.5.7 (test)' and s['vehicle'] == 'ArduCopter' and s['board'] == 'CubeOrange', s
    assert s['params'] == 3 and s['start_utc'].startswith('2023-11-14T22:13:20'), (s['params'], s['start_utc'])
    assert 59.5 <= s['duration_s'] <= 60.5 and 44 <= s['armed_s'] <= 46, (s['duration_s'], s['armed_s'])
    assert s['flights'] == 1 and 43 <= s['flight_s'] <= 45.5, (s['flights'], s['flight_s'], a['flying'])
    assert 10 <= s['takeoff_t'] <= 11.5 and s['takeoff_utc'] and s['landing_utc'], (s['takeoff_t'], s['takeoff_utc'])
    assert 700 <= s['distance_m'] <= 900 and 95 <= s['max_home_m'] <= 105, (s['distance_m'], s['max_home_m'])
    assert s['home'] == {'lat': LAT0, 'lng': LON0, 'alt': 900.0}, s['home']
    assert s['alt_max'] == 30.0 and 17 <= s['gs_max'] <= 19 and 18 <= s['as_max'] <= 20, (s['alt_max'], s['gs_max'], s['as_max'])
    assert s['roll_max'] == 10.0 and s['roll_err_rms'] is not None and 1.5 <= s['roll_err_rms'] <= 2.5, (s['roll_max'], s['roll_err_rms'])
    assert s['thr_avg'] == 55.0, s['thr_avg']
    assert s['bat_start_v'] == 16.2 and s['bat_end_v'] == 15.6 and s['bat_min_v'] == 15.6 and s['bat_max_a'] == 12.0, s
    assert s['bat_used_mah'] == 600 and s['bat_used_wh'] == round(1200 * 100 / 3600, 1) and s['bat_end_pct'] == 89, s
    assert s['sats_min'] == 7 and s['hdop_max'] == 0.8, (s['sats_min'], s['hdop_max'])
    assert s['vibe_max'] == [32.0, 9.0, 15.0] and s['clips'] == 3, (s['vibe_max'], s['clips'])
    assert s['wind_avg'] == 4.0 and s['wind_dir'] == 270, (s['wind_avg'], s['wind_dir'])
    assert [m['name'] for m in a['modes']] == ['STABILIZE', 'LOITER', 'STABILIZE'], a['modes']
    assert [(e['id'], e['t']) for e in a['events']] == [(10, 10.0), (11, 55.0)], a['events']
    assert a['errors'] == [], a['errors']
    metin = {m['text']: m for m in a['messages']}
    assert metin['Low battery warning (test)']['warn'] and metin['EKF variance (test)']['sev'] == 2 and not metin['ArduCopter V4.5.7 (test)']['warn']
    bul = {f['title']: f['level'] for f in a['findings']}
    assert bul.get('Sistem mesajı: EKF variance (test)') == 'bad' and bul.get('Titreşim yüksek') == 'warn' \
        and bul.get('GPS uydu sayısı sınırda') == 'warn' and 'Kayıtlı sistem hatası yok' not in bul, bul
    assert s['missing'] == ['errors'], s['missing']
    assert len(a['track']) > 50 and any(p[2] == 1 for p in a['track']), a['track'][:3]

    # EXTENDED_SYS_STATE varsa uçuş aralığı ondan (12–52)
    yol2 = os.path.join(d, 'ext.tlog')
    tlog_yaz(yol2, ext_state=True, arsp=False)
    s2 = flightlog.analyze(yol2)['summary']
    assert s2['flights'] == 1 and 39.5 <= s2['flight_s'] <= 40.5 and s2['takeoff_t'] == 12.0, (s2['flight_s'], s2['takeoff_t'])
    assert s2['as_max'] is None and s2['missing'] == ['as', 'errors'], (s2['as_max'], s2['missing'])   # sensörsüz VFR_HUD.airspeed tahmindir

    # Bozuk bayt + yarım son paket: tolere edilir, değerler aynı kalır
    yol3 = os.path.join(d, 'bozuk.tlog')
    tlog_yaz(yol3, cop=True, yarim=True)
    s3 = flightlog.analyze(yol3)['summary']
    assert s3['flights'] == 1 and abs(s3['flight_s'] - s['flight_s']) <= 1 and s3['alt_max'] == 30.0, (s3['flight_s'], s3['alt_max'])

    # MAVLink1 çerçeveleri (0xFE)
    yol4 = os.path.join(d, 'v1.tlog')
    tlog_yaz(yol4, v1=True)
    with open(yol4, 'rb') as f:
        assert f.read(9)[8] == 0xFE
    s4 = flightlog.analyze(yol4)['summary']
    assert s4['sysid'] == 1 and s4['alt_max'] == 30.0 and s4['flights'] == 1, s4

    # Konum/titreşim/rüzgâr/batarya mesajı olmayan kayıt → boş seriler + missing; rapor şeması bozulmaz
    yol5 = os.path.join(d, 'az.tlog')
    mav = D.MAVLink(None, srcSystem=1, srcComponent=1)
    with open(yol5, 'wb') as f:
        for i in range(30):
            for msg in (mav.heartbeat_encode(1, 3, 1, 0, 3), mav.attitude_encode(i * 1000, 0.1, 0, 0, 0, 0, 0)):
                f.write(struct.pack('>Q', int((T_ABS + i) * 1e6)) + msg.pack(mav))
                mav.seq = (mav.seq + 1) % 256
    a5 = flightlog.analyze(yol5)
    s5 = a5['summary']
    assert s5['vehicle'] == 'ArduPlane' and s5['firmware'] is None and a5['track'] == [] and a5['modes'][0]['name'] == 'MANUAL', s5
    assert {'alt', 'gs', 'volt', 'vx', 'sats', 'wind', 'track', 'messages', 'energy', 'errors'} <= set(s5['missing']), s5['missing']
    assert s5['vibe_max'] == [None, None, None] and s5['bat_start_v'] is None and s5['roll_max'] == 5.7, s5
    json.dumps(a5)   # NaN/özel tip yok

    # 3B oynatma verisi
    rp = flightlog.replay(yol)
    assert rp['fields'][:4] == ['t', 'lat', 'lng', 'alt'] and 200 <= len(rp['samples']) <= 320, len(rp['samples'])
    orta = [x for x in rp['samples'] if 30 <= x[0] <= 31][0]
    assert orta[3] == 30.0 and orta[4] == 10.0 and orta[9] == 55 and orta[10] is not None, orta

    # CLI alt süreç (sunucunun kullandığı yol)
    cikti = os.path.join(d, 'cli.json')
    p = subprocess.run([sys.executable, '-m', 'app.flightlog', 'analyze', yol, cikti], capture_output=True, text=True, timeout=120,
                       cwd=str(config.BASE_DIR))
    satirlar = p.stdout.split()
    assert p.returncode == 0 and satirlar[-1] == 'OK' and 'P' in satirlar, p.stdout[-300:]
    with open(cikti, encoding='utf-8') as f:
        assert json.load(f)['summary']['flight_s'] == s['flight_s']
    print(f'  analiz: şema = .bin; süre {s["duration_s"]} sn, havada {s["flight_s"]} sn, {s["distance_m"]} m, maks {s["alt_max"]} m / '
          f'{s["gs_max"]} m/s; modlar, ARM/DISARM, batarya, titreşim, rüzgâr, GPS, bulgular; ext_state / bozuk / v1 / eksik veri; replay; CLI')


def http_testleri(a, d):
    yol = os.path.join(d, 'http.tlog')
    tlog_yaz(yol)
    veri = open(yol, 'rb').read()
    lid = ok(a.post('/api/tools/flight-logs', files={'file': ('ucus-kaydi.tlog', veri, 'application/octet-stream')},
                    data={'aircraft': 'CZ-TLOG'}))['id']
    # parça parça yükleme (büyük loglar)
    up = ok(a.post('/api/uploads', json={'kind': 'flightlogs', 'file_name': 'parca.TLOG', 'size': len(veri)}))
    ok(a.put(f'/api/uploads/{up["upload_id"]}?offset=0', content=veri))
    lid2 = ok(a.post('/api/tools/flight-logs/chunked', json={'upload_id': up['upload_id']}))['id']
    # bozuk .tlog → 400, dosya silinir, kayıt oluşmaz
    once = set(os.listdir(config.UPLOAD_DIR / 'flightlogs'))
    r = a.post('/api/tools/flight-logs', files={'file': ('sahte.tlog', b'merhaba dunya\n' * 300, 'application/octet-stream')})
    assert r.status_code == 400 and 'metin' in r.json()['detail'], r.text
    r = a.post('/api/tools/flight-logs', files={'file': ('df.tlog', b'\xa3\x95\x80' + bytes(500), 'application/octet-stream')})
    assert r.status_code == 400 and '.bin uzantısıyla' in r.json()['detail'], r.text
    assert set(os.listdir(config.UPLOAD_DIR / 'flightlogs')) == once, 'bozuk dosya silinmeliydi'
    r = a.post('/api/tools/flight-logs', files={'file': ('kayit.txt', veri, 'application/octet-stream')})
    assert r.status_code == 400 and 'Desteklenmeyen' in r.json()['detail'], r.text

    def bitti():
        L = {x['id']: x for x in ok(a.get('/api/tools/flight-logs'))}
        return L if all(L[i]['status'] != 'ISLENIYOR' for i in (lid, lid2)) else None
    L = bekle(bitti, 60)
    assert L and len(L) == 2, L
    for i in (lid, lid2):
        assert L[i]['status'] == 'TAMAM' and L[i]['vehicle'] == 'ArduCopter' and L[i]['flight_s'] > 30 and L[i]['file'].endswith('.tlog'), L[i]
    g = ok(a.get(f'/api/flight-logs/{lid}'))
    assert g['analysis']['summary']['source'] == 'tlog' and g['aircraft'] == 'CZ-TLOG' and g['origin'] == 'REAL', (g['origin'], g['analysis']['summary']['source'])
    rp = ok(a.get(f'/api/flight-logs/{lid}/replay'))
    assert len(rp['samples']) > 200, len(rp['samples'])
    print('  HTTP: tek istek + parça parça .tlog ✓ (TAMAM, source=tlog, replay); bozuk .tlog / DataFlash / .txt → 400, dosya silinir')
    return lid


def main():
    d = tempfile.mkdtemp(prefix='tlog-test-')
    try:
        print('MAVLink telemetri kaydı (.tlog) — yükleme ve analiz')
        dogrulama_testleri(d)
        arac_secimi_testleri(d)
        analiz_testleri(d)
        with TestClient(app, base_url='https://testserver') as a:
            ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
            http_testleri(a, d)
        print('TÜM TESTLER GEÇTİ')
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(os.environ['CAYMAZ_DATA_DIR'], ignore_errors=True)


if __name__ == '__main__':
    main()
