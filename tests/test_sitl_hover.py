"""Gerçek ArduCopter SITL askı salınımı: HEPGO varsayilan.parm (drone_sitl.parm_metni) ile 10 m'de ALT_HOLD askı, sanal kumanda gibi
RC_CHANNELS_OVERRIDE nötr akışı, 10 sn ATTITUDE (50 Hz) → yatış/yunuslama std ve tepe değeri, açısal hız eşik altında olmalı.
Kök neden (düzeltildi): `--model +` / `hexa` fiziği ARTI dizilişte iken ArduCopter FRAME_TYPE varsayılanı 1 (X) idi → karıştırıcı kaymış
motorlara komut veriyor, askıda ~16 Hz ±2° salınım (açısal hız ±2 rad/s). Düzeltme: drone_sitl.CERCEVE_PARM (FRAME_TYPE 0 / hexa FRAME_CLASS 2).
Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_sitl_hover
"""
import faulthandler
import math
import os
import statistics
import tempfile
import threading
import time
faulthandler.dump_traceback_later(300, exit=True)
os.environ.setdefault('CAYMAZ_DATA_DIR', tempfile.mkdtemp())
from pymavlink import mavutil  # noqa: E402
from app import drone_params, drone_sitl  # noqa: E402

STD_ESIK = 0.3     # derece (düzeltme öncesi ~1,1–0,3; sonrası ~0,02)
TEPE_ESIK = 1.0    # derece (öncesi ~2; sonrası ~0,2)
HIZ_ESIK = 0.3     # rad/s (öncesi ~2,4; sonrası ~0,01)


def parm_kontrol():
    pm = drone_sitl.parm_metni(1, False, ['FRAME_TYPE 1', 'FRAME_CLASS 3'], 'multirotor', None).splitlines()
    assert pm[-2:] == ['FRAME_CLASS 1', 'FRAME_TYPE 0'], pm   # kayıtlı X çerçeve sanal + fiziği ezmez
    pm = drone_sitl.parm_metni(1, False, None, 'hexarotor', None).splitlines()
    assert pm[-2:] == ['FRAME_CLASS 2', 'FRAME_TYPE 0'], pm
    assert 'FRAME_TYPE' not in drone_sitl.parm_metni(1, False, None, 'vtol', 'quadplane')   # plane: Q_FRAME_* ayrı (quadplane x ↔ Q_FRAME_TYPE 1 zaten uyumlu)
    sitl, _ = drone_params.sitl_kayitlari([{'name': 'FRAME_TYPE', 'value': 1}, {'name': 'ATC_RAT_RLL_P', 'value': 0.2}], True, 'multirotor')
    assert [r['name'] for r in sitl if r['name'] != drone_params.SIM_SRV_REV] == ['ATC_RAT_RLL_P'], sitl
    sitl, _ = drone_params.sitl_kayitlari([{'name': 'FRAME_TYPE', 'value': 1}], True, 'sabit_kanat')
    assert any(r['name'] == 'FRAME_TYPE' for r in sitl), sitl


def aski_olc(yon, kimlik, tip):
    port, hata = yon.baslat(kimlik, tip, 39.9, 32.8, 1, temiz=True)
    assert port, hata
    try:
        m = mavutil.mavlink_connection(f'tcp:127.0.0.1:{port}', source_system=255)
        m.wait_heartbeat(timeout=30)
        m.mav.request_data_stream_send(1, 1, mavutil.mavlink.MAV_DATA_STREAM_ALL, 50, 1)

        def rc(thr=1500):   # sanal kumanda nötr (§37 varsayılan açık)
            m.mav.rc_channels_override_send(1, 1, 1500, 1500, thr, 1500, 0, 0, 0, 0)
        t0 = time.time()
        while True:
            assert time.time() - t0 < 90, f'{tip}: ARM olmadı'
            rc(1000)
            m.set_mode('GUIDED')
            m.arducopter_arm()
            hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
            if hb and hb.base_mode & 128:
                break
            time.sleep(1)
        m.mav.command_long_send(1, 1, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, 10)
        t0 = time.time()
        while time.time() - t0 < 30:
            rc()
            g = m.recv_match(type='GLOBAL_POSITION_INT', blocking=True, timeout=1)
            if g and g.relative_alt > 9500:
                break
        m.set_mode('ALT_HOLD')
        t0 = time.time()
        while time.time() - t0 < 5:
            rc()
            m.recv_match(blocking=True, timeout=0.05)
        r, p, w = [], [], []
        t0 = time.time()
        while time.time() - t0 < 10:
            rc()
            a = m.recv_match(type='ATTITUDE', blocking=True, timeout=0.1)
            if a:
                r.append(math.degrees(a.roll))
                p.append(math.degrees(a.pitch))
                w.append(max(abs(a.rollspeed), abs(a.pitchspeed)))
        assert len(r) > 200, (tip, len(r))
        return {'tip': tip, 'n': len(r), 'roll_std': statistics.pstdev(r), 'roll_tepe': max(map(abs, r)),
                'pitch_std': statistics.pstdev(p), 'pitch_tepe': max(map(abs, p)), 'hiz_tepe': max(w)}
    finally:
        yon.durdur(kimlik)


def main():
    parm_kontrol()
    yon = drone_sitl.SitlYoneticisi()
    sonuc = {}

    def calis(kimlik, tip):
        try:
            sonuc[tip] = aski_olc(yon, kimlik, tip)
        except BaseException as e:   # noqa: BLE001
            sonuc[tip] = e
    th = [threading.Thread(target=calis, args=(990001 + i, tip)) for i, tip in enumerate(('multirotor', 'hexarotor'))]
    for t in th:
        t.start()
        time.sleep(3)   # port bloğu ayrımı
    for t in th:
        t.join()
    for tip, s in sonuc.items():
        if isinstance(s, BaseException):
            raise s
        print(f"{tip:10s} n={s['n']} yatış std={s['roll_std']:.3f}° tepe={s['roll_tepe']:.2f}° | yunuslama std={s['pitch_std']:.3f}° "
              f"tepe={s['pitch_tepe']:.2f}° | açısal hız tepe={s['hiz_tepe']:.3f} rad/s")
        assert s['roll_std'] < STD_ESIK and s['pitch_std'] < STD_ESIK, s
        assert s['roll_tepe'] < TEPE_ESIK and s['pitch_tepe'] < TEPE_ESIK, s
        assert s['hiz_tepe'] < HIZ_ESIK, s
    print('test_sitl_hover: TAMAM')


if __name__ == '__main__':
    main()
