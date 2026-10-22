"""Uçuş Simülatörü §45 — UÇUŞ YIĞINI / PX4 birim testleri (SITL'siz): yığın kataloğu (durumlar, gerekçe), PX4 kip eşleme (custom_mode main/sub ↔ ad,
ArduPilot takma adları), komut eşleme (DO_SET_MODE, NAV_RETURN_TO_LAUNCH, ARM, NAV_TAKEOFF AMSL / VTOL_TAKEOFF, MANUAL_CONTROL), desteklenmeyen
komutların gerekçeli reddi, parametre dosyası ayrıştırma (.params QGC / .parm / AD=değer), PX4 bayt düzeyi tamsayı parametre kodlaması, parçalı
STATUSTEXT birleştirme, yığın doğrulama (tip / airframe / hız / planlanan yığın), ArduPilot .parm satırları, SimManager.ac yığınsız yolda
flightsim_px4'ü HİÇ yüklemiyor (SIMUMAV), SIMUMAV dışa aktarımına girmiyor (app/flightsim_px4.py · static/js/modules/ucus_yigini.js), drone_sitl
süreç kaydı.

Çalıştırma: .venv/bin/python -m tests.test_flightsim_px4
"""
import asyncio
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='px4-unit-'), HEPGO_SITL='0', SIM_UDP_BASE='26350', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')

from pymavlink.dialects.v20 import ardupilotmega as D  # noqa: E402

from app import drone_sitl, flightsim  # noqa: E402

KOK = Path(__file__).resolve().parents[1]


def yigin_yuklenmeden():
    """SIMUMAV / ArduPilot yolu: flightsim içe aktarılınca ve yığınsız ac doğrulamasında flightsim_px4 yüklenmez."""
    assert 'app.flightsim_px4' not in sys.modules, 'flightsim_px4 erken yüklendi'
    sm = flightsim.SimManager()
    try:   # geçersiz merkez → 400; yığın verilmediği için modül yüklenmemeli
        asyncio.run(sm.ac('multirotor', {}, None, {'id': 1, 'name': 'x'}))
    except flightsim.SimHata as e:
        assert e.kod == 'invalid'
    assert 'app.flightsim_px4' not in sys.modules, 'yığınsız ac flightsim_px4 yükledi'
    src = (KOK / 'app' / 'flightsim.py').read_text(encoding='utf-8')
    assert 'from . import flightsim_px4' not in src and 'import flightsim_px4' not in src, 'flightsim.py statik import (SIMUMAV zincirine girer)'
    print('  yığınsız yol: flightsim_px4 yüklenmedi ✓')


def disa_aktarim():
    spec = importlib.util.spec_from_file_location('simumav_export', KOK / 'tools' / 'simumav_export.py')
    sx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sx)
    rapor = sx.Rapor()
    secilen = {p.relative_to(KOK).as_posix() for p in sx.coz(KOK, rapor, False)}
    assert 'app/flightsim.py' in secilen and 'static/js/modules/flightsim.js' in secilen
    for yol in ('app/flightsim_px4.py', 'static/js/modules/ucus_yigini.js', 'app/routers/flightsim.py'):
        assert yol not in secilen, f'SIMUMAV dışa aktarımına girdi: {yol}'
    assert not any('ucus_yigini' in u or 'flightsim_px4' in u for u in rapor.uyarilar + rapor.notlar), rapor.uyarilar
    print(f'  SIMUMAV dışa aktarımı: {len(secilen)} dosya, yığın modülleri yok ✓')


def katalog_testleri(px):
    k = {x['key']: x for x in px.katalog()}
    assert list(k) == ['ardupilot', 'px4', 'inav', 'paparazzi', 'betaflight', 'rotorflight']
    assert k['ardupilot']['status'] == 'active' and k['ardupilot']['available']
    for a in ('inav', 'paparazzi', 'betaflight', 'rotorflight'):
        assert k[a]['status'] in ('planned', 'unsuitable') and len(k[a]['reason']) > 40 and not k[a]['available'], k[a]
    p = k['px4']
    assert p['status'] in ('active', 'missing') and p['airframes']['multirotor'][0]['id'] == 10040 and p['features']['speed']['ok'] is False
    assert p['license'] == 'BSD-3-Clause' and k['ardupilot']['license'] == 'GPLv3'
    print(f"  katalog: px4 {p['status']} ✓")


def kip_testleri(px):
    for ad, (main, sub) in px.PX4_MODLAR.items():
        base, m2, s2, cm = px.kip_kodla(ad)
        assert (base, m2, s2) == (1, main, sub) and cm == (main << 16) | (sub << 24)
        assert px.kip_adi(cm) == ad, (ad, px.kip_adi(cm))
    assert px.kip_adi(0x03040000) == 'AUTO.LOITER' and px.kip_adi(3 << 16) == 'POSCTL' and px.kip_adi((4 << 16) | (12 << 24)) == 'AUTO.12'
    for a, b in (('guided', 'AUTO.LOITER'), ('RTL', 'AUTO.RTL'), ('AUTO', 'AUTO.MISSION'), ('LAND', 'AUTO.LAND'), ('ALT_HOLD', 'ALTCTL'),
                 ('POSHOLD', 'POSCTL'), ('STABILIZE', 'STABILIZED'), ('mission', 'AUTO.MISSION'), ('auto.rtl', 'AUTO.RTL'), ('QLAND', 'AUTO.LAND')):
        assert px.kip_coz(a) == b, (a, px.kip_coz(a))
    try:
        px.kip_coz('FLIP')
        raise AssertionError('FLIP kabul edildi')
    except ValueError:
        pass
    assert 'AUTO.VTOL_TAKEOFF' in px.kip_listesi('vtol') and 'OFFBOARD' in px.kip_listesi('multirotor')
    print('  kip eşleme ✓')


def param_testleri(px):
    metin = ('# QGC\n1\t1\tMPC_XY_VEL_MAX\t12.5\t9\n1\t1\tCOM_ARM_WO_GPS\t1\t6\n'
             'WPNAV_SPEED 500 # yorum\nRTL_ALT,30\nX=1e2\nBAD LINE\n2bad 3\nTOO_LONG_PARAMETER_NAME 1\nNAN_P nan\nWPNAV_SPEED 600\n')
    p, atla = px.param_dosyasi_coz(metin)
    d = dict(p)
    assert d == {'MPC_XY_VEL_MAX': 12.5, 'COM_ARM_WO_GPS': 1.0, 'WPNAV_SPEED': 600.0, 'RTL_ALT': 30.0, 'X': 100.0}, d
    assert list(d)[-1] == 'WPNAV_SPEED' and atla == 4, (list(d), atla)
    assert px.param_dosyasi_coz(None) == ([], 0) and px.param_dosyasi_coz('') == ([], 0)
    try:
        px.param_dosyasi_coz('A 1\n' * 200000)
        raise AssertionError('büyük dosya kabul edildi')
    except ValueError:
        pass
    assert px.deger_metni(3.0) == '3' and px.deger_metni(0.25) == '0.25' and px.deger_metni(-1) == '-1'
    for v, t in ((1, 6), (4001, 6), (-1, 6), (255, 1), (12.5, 9)):
        assert px.param_coz(px.param_kodla(v, t), t) == float(v)
    assert px.param_kodla(1, 6) < 1e-40 and px.param_kodla(12.5, 9) == 12.5
    print('  parametre dosyası + bayt düzeyi kodlama ✓')


def dogrulama_testleri(px):
    y = px.yigin_dogrula(None, 'helikopter', None)
    assert y['stack'] == 'ardupilot' and y['params'] == []
    y = px.yigin_dogrula('ArduPilot', 'sabit_kanat', {'params_text': 'ARSPD_FBW_MIN 12\n', 'params_name': 'caymaz.parm'})
    satir = px.ardupilot_parm_satirlari(y)
    assert satir[0].startswith('# HEPGO') and satir[1:] == ['ARSPD_FBW_MIN 12'], satir
    for stack, tip, cfg in (('inav', 'multirotor', None), ('yok', 'multirotor', None), ('px4', 'helikopter', None), ('px4', 'rover', None),
                            ('px4', 'multirotor', {'airframe': 10041}), ('px4', 'multirotor', {'airframe': 'x'}), ('px4', 'multirotor', {'speed': 3})):
        try:
            px.yigin_dogrula(stack, tip, cfg)
            raise AssertionError(f'kabul edildi: {stack} {tip} {cfg}')
        except ValueError:
            pass
    eski = os.environ.get('HEPGO_PX4_DIR')
    os.environ['HEPGO_PX4_DIR'] = tempfile.mkdtemp()   # kurulum yok → RuntimeError (503)
    try:
        try:
            px.yigin_dogrula('px4', 'multirotor', None)
            raise AssertionError('kurulumsuz PX4 kabul edildi')
        except RuntimeError:
            pass
        sm = flightsim.SimManager()
        try:
            asyncio.run(sm.ac('multirotor', {'lat': 39.9, 'lon': 32.8}, None, {'id': 1, 'name': 'x'}, stack='px4'))
            raise AssertionError('kurulumsuz PX4 oturumu açıldı')
        except flightsim.SimHata as e:
            assert e.kod == 'sitl', e.kod
        try:
            asyncio.run(sm.ac('helikopter', {'lat': 39.9, 'lon': 32.8}, None, {'id': 1, 'name': 'x'}, stack='px4'))
            raise AssertionError('PX4 helikopter açıldı')
        except flightsim.SimHata as e:
            assert e.kod == 'invalid', e.kod
    finally:
        if eski is None:
            os.environ.pop('HEPGO_PX4_DIR', None)
        else:
            os.environ['HEPGO_PX4_DIR'] = eski
    print('  yığın doğrulama ✓')


class _Kayit:
    def __init__(self):
        self.msgs = []

    def __call__(self, m):
        self.msgs.append(m)
        return True


def oturum(px, tip='multirotor'):
    yig = {'stack': 'px4', 'airframe': px.PX4_AIRFRAMES[tip][0][0], 'airframe_model': 'm', 'airframe_name': 'n', 'speed': 2.0, 'params': [('A', 1.0)]}
    s = px.Px4Session(1, tip, {'id': 1, 'name': 'M', 'lat': 39.925, 'lon': 32.837, 'alt': 900.0}, flightsim.world_dogrula({}), {'id': 1, 'name': 'x'},
                      flightsim.SimManager(), rec={'bin': True}, yigin=yig)
    s.state, s._heartbeat_alindi, s.sysid, s.comp = 'HAZIR', True, 1, 1
    s._gonder = _Kayit()
    return s


def komut_testleri(px):
    s = oturum(px)
    d = s.to_dict()
    assert d['stack'] == 'px4' and d['stack_info']['speed'] == 2.0 and d['stack_info']['params_loaded'] == 1 and 'AUTO.RTL' in d['modes']
    assert d['rec'] == {'bin': False, 'ulg': True, 'bin_log': None, 'bins_reset': None} or (d['rec']['bin'] is False and d['rec']['ulg'] is True), d['rec']
    assert s.guc.speedup == 2.0 and s.param_izleyici is None and s.arazi['serve'] is False

    async def calis():
        g = s._gonder.msgs
        r = await s.komut('mode', {'mode': 'RTL'})
        assert r['mode'] == 'AUTO.RTL' and g[-1].command == 176 and (g[-1].param1, g[-1].param2, g[-1].param3) == (1, 4, 5), g[-1]
        await s.komut('mode', {'mode': 'POSCTL'})
        assert (g[-1].param2, g[-1].param3) == (3, 0)
        await s.komut('rtl', {})
        assert g[-1].command == 20
        await s.komut('arm', {})
        assert g[-1].command == 400 and g[-1].param1 == 1 and g[-1].param2 == 0   # PX4: zorla ARM yok (ön uçuş denetimi geçerli)
        await s.komut('disarm', {})
        assert g[-1].command == 400 and g[-1].param1 == 0
        await s.komut('rc', {'ch': [2000, 1000, 1500, 1250, 0, 0, 0, 0]})
        m = g[-1]
        assert m.get_type() == 'MANUAL_CONTROL' and (m.x, m.y, m.z, m.r) == (1000, 1000, 500, -500), (m.x, m.y, m.z, m.r)
        n = len(g)
        await s.komut('rc', {'ch': [0] * 8})   # serbest bırakma: MANUAL_CONTROL gönderilmez
        assert len(g) == n
        for ad, prm in (('speed', {'factor': 2}), ('motor_cut', {'on': True}), ('launch_aim', {}), ('servo_set', {'ch': 9, 'pwm': 1900}), ('defend', {'action': 'next'})):
            try:
                await s.komut(ad, prm)
                raise AssertionError(f'{ad} kabul edildi')
            except flightsim.SimHata as e:
                assert e.kod == 'invalid' and 'PX4' in str(e), str(e)
        try:
            await s.komut('mode', {'mode': 'FLIP'})
            raise AssertionError('FLIP')
        except flightsim.SimHata:
            pass
        w = await s.komut('wind', {'ms': 4, 'dir': 45})
        assert w['physics'] is False and s.tele['wind_spd'] == 4
        # kalkış: ARM'lı + ev irtifası 900 → NAV_TAKEOFF param7 = 915 (AMSL); VTOL'da NAV_VTOL_TAKEOFF (84)
        s.tele.update(armed=True, home={'lat': 39.925, 'lon': 32.837, 'alt': 900.0})
        amsl = await s.px4_kalkis(15)
        assert amsl == 915 and g[-1].command == 22 and g[-1].param7 == 915 and math.isnan(g[-1].param5)
        v = oturum(px, 'vtol')
        v.tele.update(armed=True, home={'lat': 0, 'lon': 0, 'alt': 100.0})
        await v.px4_kalkis(20)
        assert v._gonder.msgs[-1].command == 84 and v._gonder.msgs[-1].param7 == 120
    asyncio.run(calis())
    print('  komut eşleme ✓')


def isle_testleri(px):
    s = oturum(px)
    s._kalkis_task = None
    enc = D.MAVLink(None, srcSystem=1, srcComponent=1)

    def gel(m):
        buf = m.pack(enc)
        for x in s.parser.parse_buffer(buf) or []:
            s._isle(x)
    gel(enc.heartbeat_encode(2, 12, 0x9D, (4 << 16) | (5 << 24), 4))
    assert s.tele['mode'] == 'AUTO.RTL' and s.tele['armed'], s.tele['mode']
    gel(enc.param_value_encode(b'MAV_SYS_ID', px.param_kodla(1, 6), 6, 900, 3))
    assert s.param_son['MAV_SYS_ID'] == 1.0, s.param_son
    olaylar = []
    s._olay = lambda t, sev=6: olaylar.append(t)
    gel(enc.statustext_encode(4, b'Arming denied: Resolve system health failures firs', 7, 0))
    assert not olaylar
    gel(enc.statustext_encode(4, b't\t', 7, 1))
    assert olaylar == ['Arming denied: Resolve system health failures first'], olaylar
    gel(enc.command_ack_encode(511, 3))
    assert not s._smi_red   # PX4: akış isteği reddi ArduPilot REQUEST_DATA_STREAM düşüşünü tetiklemez
    print('  mesaj işleme (kip, bayt düzeyi parametre, parçalı metin, 511) ✓')


def surec_kaydi():
    p = subprocess.Popen(['sleep', '30'])
    drone_sitl.YONETICI.surec_kaydet(424242, p, {'port': 1, 'stack': 'px4', 'instance': 99})
    assert drone_sitl.YONETICI.calisiyor_mu(424242) and drone_sitl.YONETICI.bilgi(424242)['instance'] == 99
    assert drone_sitl.YONETICI.durdur(424242) and p.poll() is not None and not drone_sitl.YONETICI.calisiyor_mu(424242)
    print('  drone_sitl süreç kaydı ✓')


def main():
    yigin_yuklenmeden()
    disa_aktarim()
    from app import flightsim_px4 as px
    katalog_testleri(px)
    kip_testleri(px)
    param_testleri(px)
    dogrulama_testleri(px)
    komut_testleri(px)
    isle_testleri(px)
    surec_kaydi()
    print('test_flightsim_px4: TAMAM')


if __name__ == '__main__':
    main()
