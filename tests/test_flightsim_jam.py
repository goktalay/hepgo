"""Uçuş Simülatörü §48 / §49 — KARIŞTIRMA (GPS karıştırma / aldatma, kumanda / telemetri bağlantısı, karıştırıcı bölgesi; app/flightsim_jam.py).

- saf: `dogrula` (alan birleştirme, sınırlar, 400 nedenleri), `surukle` (ivme rampası, hedefte durma, anında sıçrama, yön değişiminde süreklilik),
  `ofset_derece`, sahte oturum yığınıyla `Karistirma` (SITL'e yazılan SIM_GPS1_* değerleri, değişmeyeni yazmama, gerçek konum kipi giriş / çıkış,
  süre bitişi, Sıfırla, özet).
- HEPGO API uçtan uca (sahte kinematik HEPGO_SITL=0): `cmd jam` 400'leri, WS `jam` çerçevesi, tele.jam / nav_* / gps_fix, süre bitişi, Sıfırla, özet.
- §49 saf: kumanda (SIM_RC_FAIL + RC arıza koruması sırası), telemetri bayrağı, bölge (giriş / çıkış histerezisi, dışarıdayken parametre yazmama),
  kopterde FS_EKF_ACTION yaz / geri al (kalıcı izleyiciye bildirim), "gaz ortada" kuralı. API: RC iletmeme, komut 409, hub reddi, bölge.
- PX4 ve SIMUMAV: kapalı (OZELLIKLER / SIM_KOMUT / desteksiz()).

Gerçek SITL davranışı (EKF tepkisi) için: tests/jam_sitl_olcum.py (elle; SITL ikilisi gerekir).

Çalıştırma: .venv/bin/python -m tests.test_flightsim_jam
"""
import math
import os
import tempfile
import time
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
    assert c == {'gps': 'heavy', 'spoof': {'on': False, **J.SPOOF_VARSAYILAN}, 'dur_s': 0, 'rc': False, 'tlm': False,
                 'zone': {'on': False, 'lat': None, 'lon': None, 'r_m': J.BOLGE_R_VARSAYILAN}, 'fs': 'althold'}, c
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
    # §49 bağlantı / bölge / tepki alanları
    b = J.dogrula({'rc': True, 'tlm': True, 'zone': {'on': True, 'lat': 40.00000004, 'lon': 32.5, 'r_m': 250.04}, 'fs': 'none', 'dur_s': 30})
    assert b['rc'] is True and b['tlm'] is True and b['zone'] == {'on': True, 'lat': 40.0, 'lon': 32.5, 'r_m': 250.0} and b['fs'] == 'none' and b['gps'] == 'off'
    assert J.ayar_metni(b) == 'kumanda bağlantısı kesik · telemetri bağlantısı kesik · bölge 250 m yarıçap · 30 sn', J.ayar_metni(b)
    b2 = J.dogrula({'zone': {'on': False}}, b)   # bölge kapanır: merkez / yarıçap korunur; yeniden açarken merkez gerekmez
    assert b2['zone'] == {'on': False, 'lat': 40.0, 'lon': 32.5, 'r_m': 250.0} and b2['rc'] and J.dogrula({'zone': {'on': True}}, b2)['zone']['on']
    b3 = J.dogrula({'off': True}, b)   # kapat: etkiler ve bölge kapanır, merkez / yarıçap / tepki korunur
    assert (b3['rc'], b3['tlm'], b3['zone']['on'], b3['zone']['r_m'], b3['fs'], b3['dur_s']) == (False, False, False, 250.0, 'none', 0)
    assert J.ayar_metni(J.dogrula({'zone': {'on': True, 'lat': 1, 'lon': 1}})) == 'kapalı'   # bölge tek başına etki değildir
    for bad in ({'rc': 1}, {'rc': 'full'}, {'tlm': None}, {'zone': True}, {'zone': {}}, {'zone': {'on': 1}}, {'zone': {'on': True}}, {'zone': {'on': True, 'lat': 40}},
                {'zone': {'on': True, 'lat': 91, 'lon': 0}}, {'zone': {'on': True, 'lat': 0, 'lon': 181}}, {'zone': {'on': True, 'lat': '40', 'lon': 32}},
                {'zone': {'on': True, 'lat': 40, 'lon': 32, 'r_m': 9}}, {'zone': {'on': True, 'lat': 40, 'lon': 32, 'r_m': 20001}},
                {'zone': {'on': False, 'lat': 40}}, {'fs': 'rtl'}, {'fs': 2}):
        assert hata(bad), bad

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
    mav = types.SimpleNamespace(command_long_encode=lambda *a: a, rc_channels_override_encode=lambda *a: ('RC',) + a)
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
    assert s.tele['jam'] == {'gps': 'off', 'spoof': True, 'off_m': 20.0, 'left_s': None, 'rc': False, 'tlm': False, 'active': True}, s.tele['jam']
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


def baglanti_testleri():
    """§49: kumanda / telemetri bağlantısı, karıştırıcı bölgesi, kopterde GPS kaybı tepkisi (FS_EKF_ACTION) ve "gaz ortada" kuralı."""
    yazilan, gonderilen, yayin, olaylar, isaret = [], [], [], [], []
    mav = types.SimpleNamespace(command_long_encode=lambda *a: a, rc_channels_override_encode=lambda *a: ('RC',) + a)
    s = types.SimpleNamespace(sahte=None, tele={'lat': 40.0, 'lon': 32.0, 'tbm': 1000}, _heartbeat_alindi=True, sysid=1, comp=1, _smi_red=False, mav=mav,
                              _param_set=lambda c: yazilan.extend(c), _gonder=lambda m: gonderilen.append(m) or True, _yay=yayin.append,
                              _olay=lambda t, sev=6: olaylar.append((t, sev)), oturum_param_unut=lambda *a: None, _rc_son=0.0,
                              oturum_paramlari={}, param_son={}, kayitli_params=[],
                              param_izleyici=types.SimpleNamespace(yukleme_isaretle=lambda adlar: isaret.extend(adlar)))
    j = J.Karistirma(s, kopter=True)
    d = j.durum()
    assert d['fs'] == 'althold' and d['rc'] is False and d['tlm'] is False and d['active'] is False and d['thr_mid'] is False, d
    assert d['zone'] == {'on': False, 'lat': None, 'lon': None, 'r_m': J.BOLGE_R_VARSAYILAN, 'inside': None, 'dist_m': None} and d['limits']['r_m'] == [J.BOLGE_R_MIN, J.BOLGE_R_MAX]
    assert J.Karistirma(s).durum()['fs'] is None   # uçak / kara aracı: tepki seçimi yok

    def kos(p):
        return asyncio.run(j.komut(p))

    def rc_gonderilen():
        return [m for m in gonderilen if m[0] == 'RC']

    tbm = [1000]

    def ilerle(n=1):
        for _ in range(n):
            tbm[0] += 200
            s.tele['tbm'] = tbm[0]
            j.adim(tbm[0])

    # ---- kumanda: arıza koruması etkinleşir + SIM_RC_FAIL 1, override BIRAKILMAZ (8×0 araca SITL'in iç kumandasını okutur);
    #      dönüşte önce çerçeveler akar, SIM_RC_FAIL 0 SONRA yazılır ----
    assert J.RC_GECIS_S > 0
    J.RC_GECIS_S = 0.0                                        # testte bekleme yok: sıranın ikinci yarısı bir sonraki adımda
    j.kalp_atisi()
    yazilan.clear()
    n = len(rc_gonderilen())
    r = kos({'rc': True})
    assert r['jam']['on'] and r['jam']['active'] and r['jam']['rc'] is True and j.rc_kesik and not j.tlm_kesik and not j.gps_kurulu
    assert yazilan == [('FS_THR_ENABLE', 1.0), ('THR_FAILSAFE', 1.0), ('SIM_RC_FAIL', 1.0)], yazilan   # GPS'e ve FS_EKF_ACTION'a dokunulmaz
    assert len(rc_gonderilen()) == n and j._rc_gecis is None                                             # araca RC çerçevesi gitmez
    assert 'kumanda bağlantısı kesik' in olaylar[-1][0] and s.tele['jam']['rc'] is True and s.tele['jam']['active'] is True
    ilerle(11)
    assert len(rc_gonderilen()) == n
    yazilan.clear()
    kos({'rc': False})
    assert not yazilan and j._rc_gecis is not None and not j.on and olaylar[-1][0] == 'Karıştırma kapatıldı', yazilan
    j._rc_gecis_adim()
    assert yazilan == [('SIM_RC_FAIL', 0.0), ('FS_THR_ENABLE', 0.0), ('THR_FAILSAFE', 0.0)], yazilan
    # bekleme dolmadan yeniden kesilirse bekleyen "darbe yok kalkar" yazımı iptal olur
    J.RC_GECIS_S = 60.0
    kos({'rc': True})
    kos({'rc': False})
    assert j._rc_gecis is not None
    kos({'rc': True})
    assert j._rc_gecis is None and yazilan[-1] == ('SIM_RC_FAIL', 1.0)
    J.RC_GECIS_S = 0.0
    kos({'rc': False})
    yazilan.clear()
    ilerle(1)                                                 # sıranın ikinci yarısı telemetri adımında işlenir
    assert yazilan[0] == ('SIM_RC_FAIL', 0.0) and j._rc_gecis is None and len(rc_gonderilen()) == n, yazilan
    # arıza koruması değeri: oturumda yazılan → dron kaydı → fabrika (1)
    s.kayitli_params = [{'name': 'FS_THR_ENABLE', 'value': 3}]
    s.oturum_paramlari = {'THR_FAILSAFE': (2.0, 2)}
    yazilan.clear()
    kos({'rc': True})
    assert yazilan == [('FS_THR_ENABLE', 3.0), ('THR_FAILSAFE', 2.0), ('SIM_RC_FAIL', 1.0)], yazilan
    yazilan.clear()
    kos({'off': True})
    j._rc_gecis_adim()
    assert yazilan[-3:] == [('SIM_RC_FAIL', 0.0), ('FS_THR_ENABLE', 0.0), ('THR_FAILSAFE', 2.0)], yazilan   # oturum değeri geri gelir; kayıt değeri oturum varsayılanına (0)
    s.kayitli_params, s.oturum_paramlari = [], {}

    # ---- telemetri: yalnız bayrak (kesme işini SimSession yapar); süre dolunca kapanır ----
    yazilan.clear()
    r = kos({'tlm': True, 'dur_s': 2})
    assert j.tlm_kesik and r['jam']['tlm'] and not yazilan and 'telemetri bağlantısı kesik · 2 sn' in olaylar[-1][0]
    ilerle(13)
    assert not j.tlm_kesik and not j.on and yayin[-1]['reason'] == 'timeout'

    # ---- kopter + GPS: FS_EKF_ACTION seçilen tepkiye; izleyiciye "bizim yazımımız" bildirilir; toparlanınca eski değer ----
    yazilan.clear()
    isaret.clear()
    kos({'gps': 'full'})
    assert ('FS_EKF_ACTION', 2.0) in yazilan and isaret == ['FS_EKF_ACTION'] and j._fs_eski == J.FS_EKF_FABRIKA and j._gaz_orta
    kos({'fs': 'none'})
    assert yazilan[-1] == ('FS_EKF_ACTION', 0.0) and j._fs_eski == J.FS_EKF_FABRIKA and j.durum()['fs'] == 'none'
    kos({'fs': 'land'})
    assert yazilan[-1] == ('FS_EKF_ACTION', 1.0)
    kos({'fs': 'althold'})
    # gaz ortada: ALT_HOLD + ARM + tarayıcıdan kumanda yok → gaz kanalı 1500 (diğer kanallar serbest)
    j.simstate(types.SimpleNamespace(lat=400000000, lng=320000000))
    n = len(rc_gonderilen())
    ilerle(3)
    assert len(rc_gonderilen()) == n and not j.durum()['thr_mid']   # henüz GUIDED / disarm
    s.tele.update(armed=True, mode='ALT_HOLD')
    ilerle(2)
    assert rc_gonderilen()[-1] == ('RC', 1, 1, 0, 0, J.GAZ_ORTA_PWM, 0, 0, 0, 0, 0) and len(rc_gonderilen()) == n + 2
    assert j.durum()['thr_mid'] and yayin[-1]['reason'] == 'thr' and 'gaz çubuğu ortada' in olaylar[-1][0]
    # sanal kumanda açık ama gaz çubuğuna dokunulmamış (gaz kanalı 0): sunucu AYRI çerçeve göndermez, tarayıcı çerçevesindeki boş gaz
    # kanalını 1500 ile doldurur (iki override kaynağı birbirinin kanallarını bırakmasın) — kural SÜRER
    s._rc_son = time.time()
    n = len(rc_gonderilen())
    ilerle(2)
    assert len(rc_gonderilen()) == n and j.durum()['thr_mid']
    assert j.rc_gaz([1500, 1500, 0, 1500, 1500, 0, 0, 0]) == [1500, 1500, J.GAZ_ORTA_PWM, 1500, 1500, 0, 0, 0] and j._rc_gaz_t == 0.0
    assert j.rc_gaz([0] * 8) == [0] * 8                       # "kumandayı bırak" çerçevesi olduğu gibi geçer
    s.tele['mode'] = 'GUIDED'
    assert j.rc_gaz([1500, 1500, 0, 1500, 1500, 0, 0, 0])[2] == 0   # ALT_HOLD dışında dokunulmaz
    s.tele['mode'] = 'ALT_HOLD'
    s.tele['armed'] = False
    assert j.rc_gaz([1500, 1500, 0, 1500, 1500, 0, 0, 0])[2] == 0   # disarm'da dokunulmaz
    s.tele['armed'] = True
    # pilot gaz çubuğunu oynatınca devralır: kanal olduğu gibi geçer, kural bırakılır; serbest bırakma GÖNDERİLMEZ (pilotun değerleri geçerli)
    assert j.rc_gaz([1500, 1500, 1320, 1500, 1500, 0, 0, 0])[2] == 1320 and j._rc_gaz_t > 0
    s._rc_son = time.time()
    ilerle(1)
    assert len(rc_gonderilen()) == n and not j.durum()['thr_mid'] and yayin[-1]['reason'] == 'thr'
    # pilot gazı bırakır (1 sn gaz girdisi yok) → yeniden gaz ortada; kumanda da kapanınca sunucu kendi çerçevesini gönderir
    j._rc_gaz_t = 0.0
    ilerle(1)
    assert len(rc_gonderilen()) == n and j.durum()['thr_mid']
    s._rc_son = 0.0
    ilerle(1)
    assert len(rc_gonderilen()) == n + 1 and rc_gonderilen()[-1][3:] == (0, 0, J.GAZ_ORTA_PWM, 0, 0, 0, 0, 0) and j.durum()['thr_mid']
    # kumanda da karıştırılırsa gaz çerçevesi kesilir (alıcıda darbe yok: aracın RC arıza koruması); bırakma çerçevesi de gitmez
    n = len(rc_gonderilen())
    kos({'rc': True})
    assert len(rc_gonderilen()) == n and not j.durum()['thr_mid']
    ilerle(3)
    assert len(rc_gonderilen()) == n
    kos({'rc': False})
    ilerle(1)
    assert j.durum()['thr_mid']
    # karıştırma kapanır: araç ALT_HOLD'da kalır (otopilot kendiliğinden dönmez) → gaz ortada SÜRER; kip değişince bırakılır
    yazilan.clear()
    kos({'off': True})
    j.ekf_konum(40.0, 32.0)
    ilerle(int(J.YAKIN_S * 5) + 3)
    assert yayin[-1]['reason'] in ('settled', 'thr') and not j._gercek and ('FS_EKF_ACTION', J.FS_EKF_FABRIKA) in yazilan and j._fs_eski is None
    n = len(rc_gonderilen())
    ilerle(2)
    assert len(rc_gonderilen()) == n + 2 and j._gaz_orta and 'jam' not in s.tele
    s.tele['mode'] = 'LOITER'
    ilerle(1)
    assert rc_gonderilen()[-1][3:] == (0,) * 8 and not j._gaz_orta and not j.durum()['thr_mid']
    n = len(rc_gonderilen())
    ilerle(3)
    assert len(rc_gonderilen()) == n
    # eski değer kaynağı: oturumda yazılan → SITL'den gözlenen → dron kaydı → fabrika; karıştırma sürerken Mission Planner yazarsa o değer geri gelir
    s.param_son = {'FS_EKF_ACTION': 3.0}
    kos({'gps': 'heavy'})
    assert j._fs_eski == 3.0
    s.oturum_paramlari = {'FS_EKF_ACTION': (5.0, 2)}
    yazilan.clear()
    j.sifirla()
    assert not j.on and j._fs_eski == 3.0 and not yazilan   # "Sıfırla": SITL yeniden açılıyor — geri yazım ilk kalp atışında
    j.kalp_atisi()
    assert ('FS_EKF_ACTION', 5.0) in yazilan and j._fs_eski is None
    s.oturum_paramlari, s.param_son = {}, {}
    # varsayılan tepki dron kaydından (kullanıcı seçmediyse): 0 → yalnız bildir · 1 / 3 → iniş · 2 → irtifa tut
    j2 = J.Karistirma(s, kopter=True)
    for v, bek in ((0, 'none'), (1, 'land'), (3, 'land'), (2, 'althold')):
        s.kayitli_params = [{'name': 'FS_EKF_ACTION', 'value': v}]
        j2.kalp_atisi()
        assert j2.durum()['fs'] == bek, (v, j2.durum()['fs'])
    asyncio.run(j2.komut({'fs': 'althold'}))
    s.kayitli_params = [{'name': 'FS_EKF_ACTION', 'value': 1}]
    j2.kalp_atisi()
    assert j2.durum()['fs'] == 'althold'   # panelden seçildiyse kayıt ezmez
    s.kayitli_params = []

    # ---- bölge: dışarıdayken kurulu ama etkisiz; girince uygulanır; çıkış histerezisli ----
    s.tele.update(armed=False, mode='GUIDED')
    j = J.Karistirma(s, kopter=True)
    j.kalp_atisi()
    dlon = 500.0 / (J.M_BOYLAM * math.cos(math.radians(40.0)))   # merkez 500 m doğuda
    yazilan.clear()
    yayin.clear()
    r = kos({'gps': 'full', 'rc': True, 'tlm': True, 'spoof': {'on': True, 'dir': 0, 'speed': 0, 'max_m': 80}, 'zone': {'on': True, 'lat': 40.0, 'lon': 32.0 + dlon, 'r_m': 100}})
    d = r['jam']
    assert d['on'] and d['active'] is False and d['zone']['inside'] is False and abs(d['zone']['dist_m'] - 500.0) < 0.5 and d['off_m'] == 0.0, d
    assert not (j.rc_kesik or j.tlm_kesik) and j.gps_etkin == 'off' and not j.spoof_etkin
    assert yazilan[0] == ('FS_EKF_ACTION', 2.0) and dict(yazilan[1:]) == dict(J.SEVIYE_PARAMLARI['off']), yazilan   # bölge dışında yalnız tepki hazırlanır; GPS / kumanda sağlam
    n_yaz = len(yazilan)
    assert 'dışarıda' in olaylar[-1][0] and s.tele['jam']['active'] is False and s.tele['jam']['inside'] is False
    j.simstate(types.SimpleNamespace(lat=400000000, lng=320000000))
    ilerle(5)
    assert len(yazilan) == n_yaz and j.ozet()['gps_s'] == {} and 'rc_s' not in j.ozet()   # dışarıda süre sayılmaz
    # içeri: gerçek konum (SIMSTATE) merkeze 90 m
    j.simstate(types.SimpleNamespace(lat=400000000, lng=int(round((32.0 + dlon * 410 / 500) * 1e7))))
    yazilan.clear()
    ilerle(1)
    assert j.aktif and j.rc_kesik and j.tlm_kesik and j.gps_etkin == 'full' and yayin[-1]['reason'] == 'zone' and yayin[-1]['zone']['inside'] is True
    adlar = [ad for ad, _ in yazilan]
    assert ('SIM_GPS1_ENABLE', 0.0) in yazilan and adlar[-1] == 'SIM_RC_FAIL' and 'SIM_GPS1_GLTCH_X' in adlar and abs(j.ok - 80.0) < 1e-9, yazilan
    assert 'bölgesine girildi' in olaylar[-1][0] and 'bölge' not in olaylar[-1][0].split('—')[1] and s.tele['jam']['active'] and s.tele['jam']['inside']
    # histerezis: r·1.03'te içeride kalır, r·1.06'da çıkar → her şey geri
    j.simstate(types.SimpleNamespace(lat=400000000, lng=int(round((32.0 + dlon * 397 / 500) * 1e7))))
    ilerle(1)
    assert j.aktif and abs(s.tele['jam']['dist_m'] - 103.0) < 0.5
    j.simstate(types.SimpleNamespace(lat=400000000, lng=int(round((32.0 + dlon * 394 / 500) * 1e7))))
    yazilan.clear()
    ilerle(1)
    assert not j.aktif and j.on and not (j.rc_kesik or j.tlm_kesik) and yayin[-1]['reason'] == 'zone' and 'çıkıldı' in olaylar[-1][0]
    j._rc_gecis_adim()
    assert ('SIM_GPS1_ENABLE', 1.0) in yazilan and ('SIM_RC_FAIL', 0.0) in yazilan and ('SIM_GPS1_GLTCH_X', 0.0) in yazilan and j.ok == 0.0, yazilan
    oz = j.ozet()
    assert oz['zone'] == {'lat': 40.0, 'lon': round(32.0 + dlon, 7), 'r_m': 100.0, 'entries': 1} and 0 < oz['rc_s'] <= 0.6 and oz['rc_s'] == oz['tlm_s'] == oz['gps_s']['full'], oz
    # araç içerideyken kurulursa hemen uygulanır; bölge kapatılınca her yerde etkiler
    j.simstate(types.SimpleNamespace(lat=400000000, lng=int(round((32.0 + dlon) * 1e7))))
    r = kos({'zone': {'on': True, 'lat': 40.0, 'lon': 32.0 + dlon, 'r_m': 50}})
    assert r['jam']['active'] and r['jam']['zone']['inside'] and r['jam']['zone']['dist_m'] < 1 and 'içeride' in olaylar[-1][0] and j.ozet()['zone']['entries'] == 2
    j.simstate(types.SimpleNamespace(lat=400000000, lng=320000000))
    ilerle(1)
    assert not j.aktif
    r = kos({'zone': {'on': False}})
    assert r['jam']['active'] and r['jam']['zone']['inside'] is None and j.tlm_kesik and 'inside' not in s.tele['jam']
    kos({'off': True})
    assert not (j.on or j.rc_kesik or j.tlm_kesik)
    print('  §49 bağlantı / bölge / tepki katmanı geçti')


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
        # ---- §49 (sahte kinematik): kumanda iletilmez, yer istasyonu komutları 409, harekât paneli reddi, bölge ----
        assert s['jam']['fs'] == 'althold' and s['jam']['rc'] is False and s['jam']['zone']['on'] is False and s['jam']['active'] is False
        for bad in ({'rc': 'full'}, {'tlm': 1}, {'zone': {'on': True}}, {'zone': {'on': True, 'lat': 40, 'lon': 32, 'r_m': 1}}, {'fs': 'rtl'}):
            assert a.post(C, json={'name': 'jam', 'params': bad}).status_code == 400, bad
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
        ok(a.post(C, json={'name': 'rc', 'params': {'ch': [1500, 1500, 1700, 1500, 0, 0, 0, 0]}}))
        assert sess.sahte.rc[2] == 1700
        r = ok(a.post(C, json={'name': 'jam', 'params': {'rc': True}}))
        assert r['jam']['rc'] and r['jam']['active'] and sess.jam.rc_kesik and sess.sahte.rc[2] != 1700   # override bırakıldı
        r = ok(a.post(C, json={'name': 'rc', 'params': {'ch': [1500, 1500, 1900, 1500, 0, 0, 0, 0]}}))
        assert r == {'ok': True, 'jammed': True} and sess.sahte.rc[2] != 1900
        ok(a.post(C, json={'name': 'arm', 'params': {}}))   # kumanda kesikken yer istasyonu komutları geçer
        r = ok(a.post(C, json={'name': 'jam', 'params': {'rc': False, 'tlm': True}}))
        assert r['jam']['tlm'] and sess.jam.tlm_kesik and not sess.jam.rc_kesik
        for name, prm in (('disarm', {}), ('mode', {'mode': 'LOITER'}), ('takeoff', {'alt': 20}), ('rtl', {}), ('set_home', {}), ('servo_set', {'ch': 9, 'pwm': 1500})):
            rr = a.post(C, json={'name': name, 'params': prm})
            assert rr.status_code == 409 and 'Telemetri bağlantısı karıştırılıyor' in rr.text, (name, rr.status_code, rr.text)
        ok(a.post(C, json={'name': 'rc', 'params': {'ch': [1500, 1500, 1800, 1500, 0, 0, 0, 0]}}))   # kumanda ayrı bağlantı: geçer
        assert sess.sahte.rc[2] == 1800 and sess.tele['armed']
        ok(a.post(C, json={'name': 'speed', 'params': {'factor': 1}}))                               # simülasyon denetimi etkilenmez
        hr = asyncio.run(sess.hub_komut('arm', {}))
        assert hr == {'ok': False, 'error': J.TLM_RET}, hr
        assert asyncio.run(sess.hub_komut('link_open', {}))['ok']
        # bölge: uzakta → kurulu ama etkisiz (komutlar geçer); aracın üstünde → etkin
        te = sess.tele
        r = ok(a.post(C, json={'name': 'jam', 'params': {'gps': 'full', 'zone': {'on': True, 'lat': te['lat'] + 0.02, 'lon': te['lon'], 'r_m': 200}}}))
        assert r['jam']['on'] and r['jam']['active'] is False and r['jam']['zone']['inside'] is False and abs(r['jam']['zone']['dist_m'] - 0.02 * J.M_ENLEM) < 5, r['jam']
        assert not sess.jam.tlm_kesik
        ok(a.post(C, json={'name': 'disarm', 'params': {}}))
        assert bekle(lambda: sess.tele.get('jam', {}).get('active') is False and sess.tele['gps_fix'] == 6)
        r = ok(a.post(C, json={'name': 'jam', 'params': {'zone': {'on': True, 'lat': te['lat'], 'lon': te['lon'], 'r_m': 200}}}))
        assert r['jam']['active'] and r['jam']['zone']['inside'] is True and sess.jam.tlm_kesik
        assert bekle(lambda: sess.tele['gps_fix'] == 1 and sess.tele['jam']['inside'] is True)
        assert a.post(C, json={'name': 'arm', 'params': {}}).status_code == 409
        r = ok(a.post(C, json={'name': 'jam', 'params': {'off': True}}))
        assert r['jam']['on'] is False and r['jam']['zone']['on'] is False and r['jam']['zone']['r_m'] == 200.0
        ok(a.post(C, json={'name': 'arm', 'params': {}}))
        ok(a.post(C, json={'name': 'disarm', 'params': {}}))
        sm = ok(a.get(f'{S}/{sid}/summary'))
        assert sm['jam']['count'] == 3 and sm['jam']['zone']['entries'] == 1 and sm['jam']['zone']['r_m'] == 200.0 and sm['jam'].get('tlm_s', 0) >= 0, sm['jam']
        assert sm['jam']['sim'] == 'fake' and sm['jam']['max_off_m'] == 150.0 and sm['jam']['gps_s'].get('full', 0) >= 1.5, sm['jam']
        # hiç açılmamış oturumda özet bölümü yok
        ok(a.delete(f'{S}/{sid}'))
        s2 = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)
        assert s2['jam']['supported'] and s2['jam']['fs'] is None   # GPS kaybı tepkisi seçimi yalnız kopterde
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
    baglanti_testleri()
    api_testleri()
    kapsam_testleri()
    print('test_flightsim_jam: TAMAM')


if __name__ == '__main__':
    main()
