"""Uçuş Simülatörü §48 — KARIŞTIRMA (GPS karıştırma / aldatma benzetimi; app/flightsim_jam.py).

- saf: `dogrula` (alan birleştirme, sınırlar, 400 nedenleri), `surukle` (ivme rampası, hedefte durma, anında sıçrama, yön değişiminde süreklilik),
  `ofset_derece`, sahte oturum yığınıyla `Karistirma` (SITL'e yazılan SIM_GPS1_* değerleri, değişmeyeni yazmama, gerçek konum kipi giriş / çıkış,
  süre bitişi, Sıfırla, özet).
- HEPGO API uçtan uca (sahte kinematik HEPGO_SITL=0): `cmd jam` 400'leri, WS `jam` çerçevesi, tele.jam / nav_* / gps_fix, süre bitişi, Sıfırla, özet.
- PX4 ve SIMUMAV: kapalı (OZELLIKLER / SIM_KOMUT / desteksiz()).

Gerçek SITL davranışı (EKF tepkisi) için: tests/jam_sitl_olcum.py (elle; SITL ikilisi gerekir).

Çalıştırma: .venv/bin/python -m tests.test_flightsim_jam
"""
import math
import os
import tempfile
import types

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25950', SIM_MAX_SESSIONS='2', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import flightsim, flightsim_px4  # noqa: E402
from app import flightsim_jam as J  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, bekle, ok, ws_bekle  # noqa: E402

MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}


def hata(p, onceki=None):
    try:
        J.dogrula(p, onceki)
    except J.KaristirmaHata as e:
        return str(e)
    return None


def saf_testler():
    # ---- dogrula ----
    c = J.dogrula({'gps': 'heavy'})
    assert c == {'gps': 'heavy', 'spoof': {'on': False, **J.SPOOF_VARSAYILAN}, 'dur_s': 0}, c
    c2 = J.dogrula({'spoof': {'on': True, 'dir': 360, 'speed': 3}, 'dur_s': 59.6}, c)
    assert c2['gps'] == 'heavy' and c2['spoof'] == {'on': True, 'dir': 0.0, 'speed': 3.0, 'max_m': 200.0} and c2['dur_s'] == 60, c2
    c3 = J.dogrula({'spoof': {'on': False}}, c2)   # kapatırken ayarlar korunur
    assert c3['spoof'] == {'on': False, 'dir': 0.0, 'speed': 3.0, 'max_m': 200.0} and c3['dur_s'] == 60
    c4 = J.dogrula({'off': True}, c2)
    assert c4['gps'] == 'off' and not c4['spoof']['on'] and c4['spoof']['speed'] == 3.0 and c4['dur_s'] == 0
    for bad in (None, [], {}, {'x': 1}, {'off': False}, {'off': 1}, {'gps': 'max'}, {'gps': 1}, {'spoof': True}, {'spoof': {}}, {'spoof': {'on': 1}},
                {'spoof': {'on': True, 'dir': -1}}, {'spoof': {'on': True, 'dir': 361}}, {'spoof': {'on': True, 'speed': 51}},
                {'spoof': {'on': True, 'speed': '2'}}, {'spoof': {'on': True, 'speed': True}}, {'spoof': {'on': True, 'max_m': 0.5}},
                {'spoof': {'on': True, 'max_m': 5001}}, {'spoof': {'on': True, 'max_m': float('nan')}}, {'dur_s': -1}, {'dur_s': 3601}, {'dur_s': '5'}):
        assert hata(bad), bad
    assert J.ayar_metni(c2) == 'GPS karıştırma ağır · GPS aldatma 0° yönünde 3 m/s ile 200 m · 60 sn', J.ayar_metni(c2)
    assert J.ayar_metni(J.dogrula({'spoof': {'on': True, 'speed': 0, 'max_m': 50, 'dir': 45}})) == 'GPS aldatma 45° yönünde anında 50 m'
    assert J.ayar_metni(c4) == 'kapalı'

    # ---- ofset_derece / fark_m ----
    x, y = J.ofset_derece(110.574, 0, 40.0)
    assert abs(x - 0.001) < 1e-12 and y == 0
    x, y = J.ofset_derece(0, 100.0, 60.0)
    assert abs(y - 100.0 / (111320.0 * 0.5)) < 1e-9
    assert abs(J.fark_m(40.0, 32.0, 40.0 + 0.001, 32.0) - 110.574) < 1e-6

    # ---- surukle: ivme rampası, hedefte durma ----
    cfg = {'dir': 90.0, 'speed': 2.0, 'max_m': 30.0}
    ok_, od, v = 0.0, 0.0, 0.0
    hizlar, t = [], 0.0
    for _ in range(400):
        onceki_v = v
        ok_, od, v, vk, vd = J.surukle(ok_, od, v, cfg, 0.2)
        t += 0.2
        hizlar.append(v)
        assert v - onceki_v <= J.IVME * 0.2 + 1e-9, (v, onceki_v)        # ivme sınırı
        assert od <= 30.0 + 1e-9 and abs(ok_) < 1e-6                       # aşmaz, yalnız doğuya
        assert abs(math.hypot(vk, vd) - v) < 1e-9 and (v == 0 or vd > 0)   # hız vektörü yön boyunca
        if od >= 30.0 - 1e-6:
            break
    assert abs(od - 30.0) < 0.06 and max(hizlar) == 2.0 and hizlar[0] == 0.1, (od, max(hizlar), hizlar[0])
    assert 17 < t < 25, t   # 30 m: 4 sn hızlanma + ~11 sn seyir + ~4 sn yavaşlama
    ok_, od, v, vk, vd = J.surukle(ok_, od, v, cfg, 0.2)
    assert (od, v, vk, vd) == (30.0, 0.0, 0.0, 0.0) or abs(od - 30.0) < 1e-9 and v == 0   # yerleşti: hız sıfır
    # anında sıçrama
    assert J.surukle(0, 0, 0, {'dir': 180.0, 'speed': 0.0, 'max_m': 80.0}, 0.2)[:3] == (-80.0, J.surukle(0, 0, 0, {'dir': 180.0, 'speed': 0.0, 'max_m': 80.0}, 0.2)[1], 0.0)
    # yön değişimi: ofset sıçramaz, yeni hedefe sürüklenir
    k1, d1, v1, _, _ = J.surukle(0.0, 30.0, 0.0, {'dir': 0.0, 'speed': 5.0, 'max_m': 30.0}, 0.2)
    assert abs(d1 - 30.0) < 0.1 and 0 < k1 < 0.1, (k1, d1)

    # ---- Karistirma: sahte oturum yığını (SITL'e bağlı gibi; yazılan parametreler toplanır) ----
    yazilan, gonderilen, yayin, olaylar = [], [], [], []
    mav = types.SimpleNamespace(command_long_encode=lambda *a: a)
    s = types.SimpleNamespace(sahte=None, tele={'lat': 40.0, 'lon': 32.0, 'tbm': 1000}, _heartbeat_alindi=True, sysid=1, comp=1, _smi_red=False, mav=mav,
                              _param_set=lambda c: yazilan.extend(c), _gonder=lambda m: gonderilen.append(m) or True, _yay=yayin.append,
                              _olay=lambda t, sev=6: olaylar.append((t, sev)), oturum_param_unut=lambda *a: None)
    j = J.Karistirma(s)
    assert j.durum()['on'] is False and j.durum()['supported'] and j.durum()['sim'] == 'sitl' and j.ozet() is None and not j.gercek_kip
    j.kalp_atisi()
    assert dict(yazilan) == dict(J.KAPALI_PARAMLARI)
    yazilan.clear()
    j.adim(1200)   # kapalıyken hiçbir şey yazılmaz
    assert not yazilan and 'jam' not in s.tele

    def kos(p):
        return asyncio.run(j.komut(p))

    r = kos({'spoof': {'on': True, 'dir': 90, 'speed': 2, 'max_m': 20}})
    assert r['ok'] and r['jam']['on'] and r['jam']['spoof']['on'] and r['jam']['real'] is True and r['jam']['left_s'] is None
    assert gonderilen[-1][2:6] == (511, 0, J.SIMSTATE_ID, J.SIMSTATE_HIZLI_US), gonderilen   # SIMSTATE 50 Hz istendi
    assert yayin[-1]['t'] == 'jam' and yayin[-1]['reason'] == 'cmd' and olaylar[-1][1] == 4 and 'aldatma 90°' in olaylar[-1][0]
    assert not yazilan   # ofset 0, seviye kapalı: değişen parametre yok
    assert not j.gercek_kip   # SIMSTATE henüz gelmedi
    j.simstate(types.SimpleNamespace(lat=400000000, lng=320000000))
    assert j.gercek_kip and s.tele['lat'] == 40.0 and s.tele['tbm_pos'] == 1000
    tbm = 2000
    j.adim(tbm)   # taban
    for _ in range(200):
        tbm += 200
        s.tele['tbm'] = tbm
        j.adim(tbm)
    son = {}
    for ad, v_ in yazilan:
        son[ad] = v_
    assert abs(son['SIM_GPS1_GLTCH_Y'] - 20.0 / (111320.0 * math.cos(math.radians(40.0)))) < 1e-9 and abs(son.get('SIM_GPS1_GLTCH_X', 0.0)) < 1e-9, son
    assert son['SIM_GPS1_VERR_Y'] == 0.0 and max(v_ for ad, v_ in yazilan if ad == 'SIM_GPS1_VERR_Y') == 2.0   # sürüklenirken 2 m/s, varınca 0
    assert s.tele['jam'] == {'gps': 'off', 'spoof': True, 'off_m': 20.0, 'left_s': None}, s.tele['jam']
    n = len(yazilan)
    for _ in range(20):
        tbm += 200
        j.adim(tbm)
    assert len(yazilan) == n   # yerleşince yeniden yazılmaz
    # EKF aldatılmış konumu izler: nav_err ≈ ofset
    j.ekf_konum(40.0, 32.0 + son['SIM_GPS1_GLTCH_Y'])
    assert abs(s.tele['nav_err'] - 20.0) < 0.1 and s.tele['nav_lon'] > 32.0
    # seviye değişimi: ağır → JAM 1; tam → ENABLE 0 (aldatma ayarı korunur)
    yazilan.clear()
    kos({'gps': 'heavy'})
    assert ('SIM_GPS1_JAM', 1.0) in yazilan and j.cfg['spoof']['on']
    yazilan.clear()
    kos({'gps': 'full'})
    assert ('SIM_GPS1_JAM', 0.0) in yazilan and ('SIM_GPS1_ENABLE', 0.0) in yazilan
    # hafif: az uydu + kötü doğruluk + gezinen ofset (aldatma kapalı)
    yazilan.clear()
    kos({'gps': 'light', 'spoof': {'on': False}})
    assert ('SIM_GPS1_ENABLE', 1.0) in yazilan and ('SIM_GPS1_NUMSATS', J.HAFIF_UYDU) in yazilan and ('SIM_GPS1_ACC', J.HAFIF_DOGRULUK) in yazilan
    assert ('SIM_GPS1_GLTCH_Y', 0.0) in yazilan   # aldatma kapandı: ofset anında sıfır
    yazilan.clear()
    gez = []
    for _ in range(300):
        tbm += 200
        j.adim(tbm)
        gez.append(math.hypot(j.gk, j.gd))
    assert 0.5 < sum(gez) / len(gez) < 8 and max(gez) < 20 and any(ad == 'SIM_GPS1_GLTCH_X' for ad, _ in yazilan), (sum(gez) / len(gez), max(gez))
    assert s.tele['jam']['off_m'] == 0.0   # off_m yalnız aldatma ofseti
    # süre: simülasyon saniyesi; dolunca kendiliğinden kapanır, parametreler geri alınır
    yazilan.clear()
    kos({'gps': 'heavy', 'dur_s': 3})
    assert j.durum()['left_s'] == 3.0
    for _ in range(14):
        tbm += 200
        j.adim(tbm)
    assert j.on and 0 < j.durum()['left_s'] <= 0.6, j.durum()
    for _ in range(4):
        tbm += 200
        j.adim(tbm)
    assert not j.on and yayin[-1]['reason'] == 'timeout' and 'süresi doldu' in olaylar[-1][0] and 'jam' not in s.tele
    assert j._son['SIM_GPS1_JAM'] == 0.0 and j._son['SIM_GPS1_ENABLE'] == 1.0 and j._son['SIM_GPS1_NUMSATS'] == 18.0 and j._son['SIM_GPS1_GLTCH_X'] == 0.0
    # toparlanma: EKF uzaktayken gerçek konum kipi sürer; yaklaşınca (YAKIN_S) biter ve SIMSTATE 10 Hz'e döner
    assert j._gercek and j.gercek_kip
    j.ekf_konum(40.001, 32.0)
    for _ in range(20):
        tbm += 200
        j.adim(tbm)
    assert j._gercek and s.tele['nav_err'] > 100
    j.ekf_konum(40.0, 32.0)
    for _ in range(int(J.YAKIN_S * 5) + 2):
        tbm += 200
        j.adim(tbm)
    assert not j._gercek and yayin[-1]['reason'] == 'settled' and gonderilen[-1][4:6] == (J.SIMSTATE_ID, J.SIMSTATE_NORMAL_US)
    assert not any(k in s.tele for k in ('nav_lat', 'nav_lon', 'nav_err', 'jam'))
    # EKF hiç toparlanmazsa GERCEK_AZAMI_S sonra yine biter
    kos({'gps': 'full'})
    kos({'off': True})
    assert olaylar[-1] == ('Karıştırma kapatıldı', 6) and j._gercek
    j.ekf_konum(40.01, 32.0)
    for _ in range(int(J.GERCEK_AZAMI_S * 5) + 3):
        tbm += 200
        j.adim(tbm)
    assert not j._gercek
    oz = j.ozet()
    assert oz['count'] == 2 and oz['sim'] == 'sitl' and set(oz['gps_s']) == {'light', 'heavy'} and abs(oz['gps_s']['light'] - 60.0) < 0.5, oz
    assert abs(oz['max_off_m'] - 20.0) < 0.1 and oz['spoof_s'] > 40 and oz['max_nav_err'] > 1000, oz
    # Sıfırla: açıkken → kapanır + 'reset' çerçevesi; saat geri giderse adım tabanı yeniden kurulur
    kos({'spoof': {'on': True, 'speed': 0, 'max_m': 50, 'dir': 180}})
    assert abs(j.ok + 50.0) < 1e-9 and abs(j._son['SIM_GPS1_GLTCH_X'] + 50.0 / J.M_ENLEM) < 1e-12   # anında sıçrama
    j.sifirla()
    assert not j.on and not j._gercek and j.g_lat is None and yayin[-1]['reason'] == 'reset' and j._son == {}
    j.adim(100)
    # desteksiz
    j.desteksiz('yok')
    assert j.durum() == {'supported': False, 'reason': 'yok'}
    try:
        kos({'gps': 'heavy'})
        raise AssertionError('desteksiz oturumda komut kabul edildi')
    except J.KaristirmaHata as e:
        assert str(e) == 'yok'
    yazilan.clear()
    j.kalp_atisi()
    assert not yazilan   # desteksiz oturumda SITL parametrelerine dokunulmaz
    print('  saf katman geçti')


def api_testleri():
    S = '/api/drone/sim/sessions'
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Karıştırma Sahası', **MERKEZ}))
        s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        sid = s['id']
        assert s['jam']['supported'] and s['jam']['on'] is False and s['jam']['sim'] == 'fake' and s['jam']['spoof']['on'] is False, s['jam']
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
        C = f'{S}/{sid}/cmd'
        for bad in ({}, {'gps': 'x'}, {'off': False}, {'spoof': {'on': 'evet'}}, {'spoof': {'on': True, 'speed': 99}}, {'dur_s': 99999}, {'gps': 'heavy', 'dur_s': None}):
            assert a.post(C, json={'name': 'jam', 'params': bad}).status_code == 400, bad
        sess = flightsim.MANAGER.sessions[sid]
        with a.websocket_connect(f'/ws/drone/sim/{sid}') as ws:
            assert ws_bekle(ws, lambda m: m['t'] == 'hello')
            m = ws_bekle(ws, lambda m: m['t'] == 'tele', 5)
            assert m and 'jam' not in m and 'nav_lat' not in m and m['gps_fix'] == 6
            r = ok(a.post(C, json={'name': 'jam', 'params': {'gps': 'full', 'spoof': {'on': True, 'dir': 0, 'speed': 0, 'max_m': 150}, 'dur_s': 2}}))
            assert r['ok'] and r['jam']['on'] and r['jam']['gps'] == 'full' and r['jam']['off_m'] == 150.0 and r['jam']['real'] is False, r
            ev = ws_bekle(ws, lambda m: m['t'] == 'jam', 3)
            assert ev and ev['reason'] == 'cmd' and ev['on'] and ev['dur_s'] == 2 and ev['sim'] == 'fake', ev
            m = ws_bekle(ws, lambda m: m['t'] == 'tele' and m.get('jam'), 3)
            assert m['jam']['gps'] == 'full' and m['jam']['spoof'] is True and m['gps_fix'] == 1 and m['sats'] == 0, m
            assert abs(m['nav_err'] - 150.0) < 0.2 and abs((m['nav_lat'] - m['lat']) * J.M_ENLEM - 150.0) < 0.5 and abs(m['nav_lon'] - m['lon']) < 1e-7, m
            assert ok(a.get(f'{S}/{sid}'))['jam']['on']   # yeniden bağlanan istemci
            # süre (2 simülasyon saniyesi) dolunca kendiliğinden kapanır
            ev = ws_bekle(ws, lambda m: m['t'] == 'jam' and m['reason'] == 'timeout', 6)
            assert ev and ev['on'] is False and ev['gps'] == 'off' and ev['spoof']['on'] is False and ev['spoof']['max_m'] == 150.0, ev
            m = ws_bekle(ws, lambda m: m['t'] == 'tele' and 'jam' not in m, 3)
            assert m and 'nav_lat' not in m and m['gps_fix'] == 6 and m['sats'] == 18, m
            # WS komutu: hafif seviye
            import json
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'jam', 'params': {'gps': 'light'}, 'rid': 'j1'}))
            ev = ws_bekle(ws, lambda m: m['t'] == 'jam' and m['on'], 3)
            assert ev and ev['gps'] == 'light' and ev['dur_s'] == 0 and ev['left_s'] is None, ev
            m = ws_bekle(ws, lambda m: m['t'] == 'tele' and m.get('jam') and m.get('nav_err', 0) > 0, 5)
            assert m and m['gps_fix'] == 3 and m['sats'] == 6 and m['jam']['off_m'] == 0.0, m
            # Sıfırla → kapanır
            ok(a.post(C, json={'name': 'reset', 'params': {}}))
            ev = ws_bekle(ws, lambda m: m['t'] == 'jam' and m['reason'] == 'reset', 5)
            assert ev and ev['on'] is False, ev
        assert sess.jam.on is False
        sm = ok(a.get(f'{S}/{sid}/summary'))
        assert sm['jam']['count'] == 2 and sm['jam']['sim'] == 'fake' and sm['jam']['max_off_m'] == 150.0 and sm['jam']['gps_s'].get('full', 0) >= 1.5, sm['jam']
        # hiç açılmamış oturumda özet bölümü yok
        ok(a.delete(f'{S}/{sid}'))
        s2 = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)
        assert bekle(lambda: ok(a.get(f"{S}/{s2['id']}"))['state'] == 'HAZIR')
        assert ok(a.get(f"{S}/{s2['id']}/summary"))['jam'] is None
        ok(a.delete(f"{S}/{s2['id']}"))
    print('  API uçtan uca geçti')


def kapsam_testleri():
    assert 'jam' in flightsim.KOMUTLAR
    assert flightsim_px4.OZELLIKLER['jam'][0] is False and flightsim_px4.DESTEKSIZ_KOMUT['jam'] == 'jam'
    from app.simumav.routers import fly as sfly
    from app.simumav import bridge
    assert 'jam' not in sfly.SIM_KOMUT and {'wind', 'arm', 'reset'} <= sfly.SIM_KOMUT
    import inspect
    assert inspect.getsource(bridge).count('s.jam.desteksiz(KARISTIRMA_YOK)') == 2
    from tools import simumav_export
    assert 'app/flightsim_jam.py' in simumav_export.PY_CEKIRDEK
    assert all(ad.startswith('SIM_GPS1_') for ad, _ in J.KAPALI_PARAMLARI)
    from app import drone_params
    assert all(drone_params.haric_mi(ad) for ad, _ in J.KAPALI_PARAMLARI)   # dron kaydına kalıcı yazılmaz
    print('  kapsam (PX4 / SIMUMAV / kalıcılık) geçti')


def main():
    saf_testler()
    api_testleri()
    kapsam_testleri()
    print('test_flightsim_jam: TAMAM')


if __name__ == '__main__':
    main()
