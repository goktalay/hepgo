"""Uçuş Simülatörü §33 — ÇOK OYUNCULU KARŞILAŞMA: saf çekirdek (halka ayarı/üretimi min-max-sayı, başlangıç noktaları, geçiş tespiti doğru/ters
yön ve dışından, sıralı ilerleme, sıçrama, sıralama, durum makinesi: davet, tüm katılınca hazırlık, hazır → geri sayım → yarış, ilk bitiren →
BİTTİ, süre sınırı, iptal, çıkarma, zorla başlatma, hazırlık zaman aşımı) + HEPGO API uçtan uca (sahte kinematik HEPGO_SITL=0): davet listesi /
yetki, bildirim (zil + push), oyuncu oturumları farklı başlangıç noktalarında, komut kapısı, başkasının aracı 403, WS hazır → geri sayım → yarış,
rota pilotuyla halka geçişleri → birinci → sonuç (iki WS'de), kapanışta drone_sim_runs.match_id, kaynak tavanı, iptal.

Çalıştırma: .venv/bin/python -m tests.test_flightsim_match
"""
import json
import math
import os
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25750', SIM_MAX_SESSIONS='2', SIM_MATCH_MAX_SESSIONS='6', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, flightsim, flightsim_match  # noqa: E402
from app import flightsim_match_core as core  # noqa: E402
from app.main import app  # noqa: E402
from tests.match_bot import it_pilotu, rota_pilotu  # noqa: E402

MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}


def hata_kodu(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except core.MacHata as e:
        return e.kod
    return None


# ================================================================ saf çekirdek
def halka_testleri():
    v = core.halka_ayar_dogrula(None, 'multirotor')
    assert v['count'] == 8 and v['min_alt_m'] == 15 and v['max_alt_m'] == 60 and v['diameter_m'] == 12 and v['radius_m'] == 220, v
    u = core.halka_ayar_dogrula({}, 'sabit_kanat')
    assert u['diameter_m'] == 36 and u['radius_m'] == 700 and u['min_alt_m'] == 40, u
    assert hata_kodu(core.halka_ayar_dogrula, {}, 'rover') == 'invalid'   # kara aracı yok
    assert hata_kodu(core.halka_ayar_dogrula, {'min_alt_m': 80, 'max_alt_m': 40}, 'multirotor') == 'invalid'
    for bad in ({'count': 0}, {'count': 31}, {'count': 2.5}, {'min_alt_m': 2}, {'max_alt_m': 500}, {'diameter_m': 1}, {'count': True}, {'count': '5'}, {'time_limit_min': 1}):
        assert hata_kodu(core.halka_ayar_dogrula, bad, 'multirotor') == 'invalid', bad
    for n, lo, hi in ((1, 20, 20), (2, 10, 100), (8, 15, 60), (30, 5, 400)):
        cfg = core.halka_ayar_dogrula({'count': n, 'min_alt_m': lo, 'max_alt_m': hi, 'seed': 77}, 'multirotor')
        H = core.halkalar_uret(cfg, MERKEZ)
        assert len(H) == n and [h['i'] for h in H] == list(range(1, n + 1)), H
        alts = [h['agl_m'] for h in H]
        assert all(lo - 1e-6 <= a <= hi + 1e-6 for a in alts), alts
        if n > 1:
            assert abs(min(alts) - lo) < 0.06 and abs(max(alts) - hi) < 0.06 and len(set(alts)) == (n if hi > lo else 1), alts   # eşit adım: uçlar dahil, hepsi farklı
        for h in H:
            r = math.hypot(h['x'], h['y'])
            assert 0.45 * cfg['radius_m'] - 0.01 <= r <= cfg['radius_m'] + 0.01, (r, h)
            assert abs(math.hypot(h['nx'], h['ny']) - 1) < 1e-3 and h['radius_m'] == cfg['diameter_m'] / 2 and abs(h['alt_msl'] - (900 + h['agl_m'])) < 0.01, h
            x, y = core.enu(MERKEZ['lat'], MERKEZ['lon'], h['lat'], h['lon'])
            assert abs(x - h['x']) < 0.05 and abs(y - h['y']) < 0.05, (x, y, h)
        # normal: önceki halkadan (ilk halkada merkezden) bu halkaya
        onceki = (0.0, 0.0)
        for h in H:
            d = (h['x'] - onceki[0], h['y'] - onceki[1])
            L = math.hypot(*d)
            assert abs(d[0] / L - h['nx']) < 1e-3 and abs(d[1] / L - h['ny']) < 1e-3, h
            onceki = (h['x'], h['y'])
    cfg = core.halka_ayar_dogrula({'seed': 5}, 'multirotor')
    assert core.halkalar_uret(cfg, MERKEZ) == core.halkalar_uret(cfg, MERKEZ)   # deterministik
    assert core.halkalar_uret(cfg, MERKEZ) != core.halkalar_uret({**cfg, 'seed': 6}, MERKEZ)
    print('  halka ayarı / üretimi geçti')


def baslangic_testleri():
    for n in range(2, 9):
        P = core.baslangic_noktalari(n, 'multirotor', hedef=(100, 0))
        assert len(P) == n
        dmin = min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(P) for b in P[i + 1:])
        assert dmin >= core.AYRIK_M - 0.05, (n, dmin)
        assert all(abs(math.hypot(p[0], p[1]) - math.hypot(P[0][0], P[0][1])) < 0.01 for p in P)   # çember
        for x, y, yaw in P:   # burun ilk halkaya
            assert abs(((math.degrees(math.atan2(100 - x, -y)) - yaw) + 180) % 360 - 180) < 0.2, (x, y, yaw)
    for hdg in (0, 90, 135):
        P = core.baslangic_noktalari(4, 'sabit_kanat', hdg)
        assert all(p[2] == hdg for p in P)
        for a, b in zip(P, P[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            assert abs(math.hypot(dx, dy) - core.AYRIK_M) < 0.05
            fx, fy = math.sin(math.radians(hdg)), math.cos(math.radians(hdg))
            assert abs(dx * fx + dy * fy) < 0.05, (hdg, dx, dy)   # pist yönüne dik şeritler
    print('  başlangıç noktaları geçti')


def gecis_testleri():
    h = {'i': 1, 'x': 0.0, 'y': 100.0, 'alt_msl': 950.0, 'nx': 0.0, 'ny': 1.0, 'radius_m': 6.0}
    assert core.halka_kesisim((0, 90, 950), (0, 110, 950), h) == ('ileri', 0.0)
    yon, d = core.halka_kesisim((3, 90, 952), (3, 110, 952), h)
    assert yon == 'ileri' and abs(d - math.hypot(3, 2)) < 1e-9
    assert core.halka_kesisim((0, 110, 950), (0, 90, 950), h)[0] == 'ters'
    assert core.halka_kesisim((0, 80, 950), (0, 95, 950), h) == (None, None)   # düzleme varmadı
    yon, d = core.halka_kesisim((10, 90, 950), (10, 110, 950), h)
    assert yon == 'ileri' and d == 10   # dışından
    H = [h, {'i': 2, 'x': 100.0, 'y': 100.0, 'alt_msl': 960.0, 'nx': 1.0, 'ny': 0.0, 'radius_m': 6.0}]
    iz = core.HalkaIzleyici(H)
    assert iz.konum(100 - 10, 100, 960, 1.0) == [] and iz.konum(100 + 10, 100, 960, 1.1) == []   # 2. halka sıra dışı: sayılmaz
    assert iz.konum(10, 90, 950, 2) == [] and iz.konum(10, 110, 950, 3) == [] and iz.sira == 0   # dışından
    assert iz.konum(0, 110, 950, 4) == [] and iz.konum(0, 90, 950, 5) == [{'kind': 'wrong_way', 'i': 1}] and iz.sira == 0   # ters yön
    assert iz.konum(0, 99, 951, 6) == [] and iz.konum(0, 101, 951, 7) == [{'kind': 'ring', 'i': 1, 't': 7}] and iz.sira == 1
    assert abs(iz.mesafe - math.dist((0, 101, 951), (100, 100, 960))) < 1e-6
    iz.konum(99, 100, 960, 8)
    assert iz.konum(99 + core.SICRAMA_M + 5, 100, 960, 9) == [] and iz.sira == 1   # sıçrama (reset) sayılmaz
    iz.konum(99, 100, 960, 10)
    ev = iz.konum(101, 100, 960, 11)
    assert ev == [{'kind': 'ring', 'i': 2, 't': 11}, {'kind': 'finish', 't': 11}] and iz.bitti and iz.bitis_t == 11, ev
    assert iz.konum(99, 100, 960, 12) == [] and iz.mesafe == 0
    print('  geçiş tespiti geçti')


def siralama_testi():
    p = lambda i, st, r, d=None, fin=False, ft=None: {'id': i, 'status': st, 'rings': r, 'dist_next_m': d, 'finished': fin, 'finish_t': ft}   # noqa: E731
    S = core.siralama([p(1, 'hazir', 3, 50), p(2, 'hazir', 8, None, True, 130.0), p(3, 'hazir', 3, 20), p(4, 'ayrildi', 6, 5), p(5, 'dustu', 0),
                       p(6, 'hazir', 8, None, True, 125.5), p(7, 'hazir', 5, 300)], baslangic_t=100.0)
    assert [x['id'] for x in S] == [6, 2, 7, 3, 1, 4, 5], [x['id'] for x in S]
    assert S[0]['rank'] == 1 and S[0]['time_s'] == 25.5 and S[1]['time_s'] == 30.0 and S[2]['time_s'] is None
    print('  sıralama geçti')


def durum_makinesi_testleri():
    cfg = core.halka_ayar_dogrula({'count': 2, 'seed': 3}, 'multirotor')
    H = core.halkalar_uret(cfg, MERKEZ)
    # §47 tek kişilik: davetli/bot yok → kurulur, lobi denetimi hemen HAZIRLIK; tek oyuncu hazır → geri sayım → yarış → bitirince BITTI
    ks = core.Karsilasma(1, (10, 'Kurucu'), [], {}, cfg, MERKEZ, 0, H)
    assert ks.durum == core.LOBI and ks.tek_kurulum
    assert ks.lobi_denetle(1)[-1]['state'] == core.HAZIRLIK
    assert ks.hazir(10, 2)[-1]['t'] == 'countdown' and ks.durum == core.GERI_SAYIM
    ks.tik(2 + core.GERI_SAYIM_S)
    assert ks.durum == core.YARIS
    ev, tt = [], ks.baslangic_t
    for hh in H:
        for f in (-4, 4):
            tt += 5
            ev = ks.konum(10, *core.latlon(MERKEZ['lat'], MERKEZ['lon'], hh['x'] + hh['nx'] * f, hh['y'] + hh['ny'] * f), hh['alt_msl'], tt)
    assert ks.durum == core.BITTI and ks.kazanan == 10 and ev[-1]['result']['solo'] is True and ev[-1]['result']['standings'][0]['time_s'] is not None, ev
    assert hata_kodu(core.Karsilasma, 1, (10, 'Kurucu'), [], {}, core.it_ayar_dogrula({}, 'multirotor'), MERKEZ, 0, [], tur='dogfight') == 'invalid'   # it dalaşı tam 2
    assert core.Karsilasma(1, (10, 'Kurucu'), [(10, 'Kendisi')], {}, cfg, MERKEZ, 0, H).tek_kurulum   # kendini davet sayılmaz (→ tek kişilik)
    assert hata_kodu(core.Karsilasma, 1, (10, 'K'), [(i, f'O{i}') for i in range(20, 28)], {}, cfg, MERKEZ, 0, H) == 'limit'   # 9 oyuncu
    k = core.Karsilasma(1, (10, 'Kurucu'), [(20, 'Ayşe'), (30, 'Mehmet')], {'type': 'multirotor'}, cfg, MERKEZ, 1000.0, H)
    assert k.durum == core.LOBI and k.oyuncu(10).durum == core.GELDI and k.oyuncu(20).durum == core.DAVETLI
    assert hata_kodu(k.katil, 99, 1001) == 'forbidden'
    ev = k.katil(20, 1001)
    assert ev == [{'t': 'player', 'id': 20, 'status': 'geldi'}] and k.durum == core.LOBI
    assert k.katil(20, 1002) == []   # yeniden bağlanma
    assert not k.zorla_baslatilabilir(1002) and k.zorla_baslatilabilir(1000 + core.LOBI_ZORLA_S)
    assert hata_kodu(k.zorla_baslat, 20, 1000 + core.LOBI_ZORLA_S) == 'forbidden'
    ev = k.katil(30, 1003)   # son davetli geldi → HAZIRLIK
    assert k.durum == core.HAZIRLIK and ev[-1]['state'] == core.HAZIRLIK and [o.sira_no for o in k.oyuncular.values()] == [0, 1, 2]
    assert all(o.durum == core.HAZIRLANIYOR for o in k.oyuncular.values())
    assert hata_kodu(k.katil, 30, 1004) is None   # aynı oyuncu: olay yok
    k.hazir(10, 1005); k.hazir(20, 1006)
    assert k.durum == core.HAZIRLIK
    ev = k.hazir(30, 1007)
    assert k.durum == core.GERI_SAYIM and ev[-1] == {'t': 'countdown', 'start_at': 1007 + core.GERI_SAYIM_S, 'ts': 1007}, ev
    assert k.konum(10, H[0]['lat'], H[0]['lon'], H[0]['alt_msl'], 1008) == []   # yarış başlamadan işlenmez
    assert k.tik(1007 + core.GERI_SAYIM_S - 0.01) == [] and k.durum == core.GERI_SAYIM
    assert k.tik(1007 + core.GERI_SAYIM_S)[0]['state'] == core.YARIS
    t0 = k.baslangic_t

    def gec(uid, h, t):
        a = core.latlon(MERKEZ['lat'], MERKEZ['lon'], h['x'] - h['nx'] * 5, h['y'] - h['ny'] * 5)
        b = core.latlon(MERKEZ['lat'], MERKEZ['lon'], h['x'] + h['nx'] * 5, h['y'] + h['ny'] * 5)
        return k.konum(uid, *a, h['alt_msl'], t, hiz=14) + k.konum(uid, *b, h['alt_msl'], t + 0.1, hiz=18.5)
    ev = gec(20, H[0], t0 + 10)
    assert [e['t'] for e in ev] == ['ring'] and ev[0]['i'] == 1 and ev[0]['elapsed_s'] == 10.1, ev
    gec(30, H[0], t0 + 11)
    ev = gec(20, H[1], t0 + 20)
    assert [e['t'] for e in ev] == ['ring', 'finish', 'state', 'result'], ev
    assert k.durum == core.BITTI and k.kazanan == 20 and k.neden == 'birinci_bitirdi'
    r = ev[-1]['result']
    assert [s['id'] for s in r['standings']] == [20, 30, 10] and r['standings'][0]['time_s'] == 20.1 and r['standings'][0]['max_speed_ms'] == 18.5, r
    assert r['standings'][1]['rings'] == 1 and r['standings'][2]['rings'] == 0 and r['winner'] == 20 and r['total'] == 2
    assert gec(30, H[1], t0 + 30) == [] and k.durum == core.BITTI   # bittikten sonra işlenmez

    # süre sınırı → BITTI, birinci en çok ilerleyen
    k2 = core.Karsilasma(2, (10, 'K'), [(20, 'A')], {}, {**cfg, 'time_limit_min': 2}, MERKEZ, 0.0, H)
    k2.katil(20, 1); k2.hazir(10, 2); k2.hazir(20, 3); k2.tik(3 + core.GERI_SAYIM_S)
    assert k2.durum == core.YARIS
    h = H[0]
    k2.konum(10, *core.latlon(MERKEZ['lat'], MERKEZ['lon'], h['x'] - h['nx'] * 4, h['y'] - h['ny'] * 4), h['alt_msl'], 20)
    k2.konum(10, *core.latlon(MERKEZ['lat'], MERKEZ['lon'], h['x'] + h['nx'] * 4, h['y'] + h['ny'] * 4), h['alt_msl'], 21)
    assert k2.tik(k2.baslangic_t + 119) == []
    ev = k2.tik(k2.baslangic_t + 120)
    assert k2.durum == core.BITTI and k2.neden == 'sure' and k2.kazanan == 10 and ev[-1]['result']['standings'][0]['id'] == 10, ev

    # iptal / kurucu ayrılması / çıkarma / zorla başlatma / hazırlık zaman aşımı
    k3 = core.Karsilasma(3, (10, 'K'), [(20, 'A'), (30, 'B')], {}, cfg, MERKEZ, 0.0, H)
    assert hata_kodu(k3.cikar, 20, 30, 1) == 'forbidden'
    k3.cikar(10, 30, 1)
    assert k3.oyuncu(30).durum == core.CIKARILDI and k3.durum == core.LOBI
    assert hata_kodu(k3.katil, 30, 2) == 'forbidden'
    k3.katil(20, 3)
    assert k3.durum == core.HAZIRLIK and len(k3.aktifler()) == 2
    k3.hazir(10, 4)
    ev = k3.tik(3 + core.HAZIRLIK_ZAMAN_ASIMI_S + 1)   # 20 hazırlanamadı → düşer → §47 kalan tek oyuncu (hazır) zaman denemesiyle sürer
    assert k3.oyuncu(20).durum == core.DUSTU and k3.durum == core.GERI_SAYIM, ev
    k3b = core.Karsilasma(31, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    k3b.katil(20, 1)
    ev = k3b.tik(1 + core.HAZIRLIK_ZAMAN_ASIMI_S + 1)   # kimse hazır değil → ikisi de düşer → IPTAL
    assert k3b.durum == core.IPTAL and k3b.neden == 'oyuncu_kalmadi', ev
    k4 = core.Karsilasma(4, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k4.ayril(10, 5)[0]['state'] == core.IPTAL and k4.neden == 'kurucu_ayrildi'
    k5 = core.Karsilasma(5, (10, 'K'), [(20, 'A'), (30, 'B')], {}, cfg, MERKEZ, 0.0, H)
    k5.katil(20, 1)
    assert hata_kodu(k5.zorla_baslat, 10, 30) == 'conflict'
    ev = k5.zorla_baslat(10, core.LOBI_ZORLA_S)
    assert k5.oyuncu(30).durum == core.DUSTU and k5.oyuncu(30).dusme_nedeni == 'gelmedi' and k5.durum == core.HAZIRLIK, ev
    k6 = core.Karsilasma(6, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k6.ayril(20, 1)[-1]['state'] == core.IPTAL   # tek davetli reddetti → kurucu yalnız → iptal (kendiliğinden tek kişilik başlamaz)
    k6b = core.Karsilasma(61, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k6b.zorla_baslatilabilir(core.LOBI_ZORLA_S)   # §47 kurucu yalnız gelmişse de "gelmeyenler olmadan başlat" → tek kişilik
    ev = k6b.zorla_baslat(10, core.LOBI_ZORLA_S)
    assert k6b.durum == core.HAZIRLIK and len(k6b.aktifler()) == 1, ev
    k7 = core.Karsilasma(7, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k7.tik(core.LOBI_ZAMAN_ASIMI_S + 1)[0]['state'] == core.IPTAL and k7.neden == 'zaman_asimi'
    assert k7.iptal(99999) == []   # son durumdan çıkılmaz
    print('  durum makinesi geçti')


def it_dalasi_testleri():
    """§41 it dalaşı: ayar doğrulama, başlangıç noktaları, koni/menzil/kesintisiz süre, kazanan (angaje / süre / alan dışı / çarpma / rakip ayrıldı),
    kalkış koruması, roller, sonuç."""
    v = core.it_ayar_dogrula(None, 'multirotor')
    assert v['type'] == 'dogfight' and v['distance_m'] == 400 and v['range_m'] == 120 and v['cone_deg'] == 30 and v['hold_s'] == 3 and v['roles'] == 'random' and v['vclass'] == 'dikey', v
    u = core.it_ayar_dogrula({}, 'sabit_kanat')
    assert u['distance_m'] == 1000 and u['alt_m'] == 120 and u['vclass'] == 'ucak' and u['area_radius_m'] == 3000, u
    assert core.it_ayar_dogrula({'distance_m': 1500}, 'multirotor')['area_radius_m'] == 1150   # varsayılan alan mesafeye göre büyür
    for bad in ({'distance_m': 200}, {'distance_m': 1600}, {'time_limit_min': 1}, {'time_limit_min': 11}, {'time_limit_min': 2.5}, {'range_m': 40},
                {'range_m': 500}, {'cone_deg': 10}, {'cone_deg': 50}, {'hold_s': 1}, {'hold_s': 6}, {'area_radius_m': 200}, {'roles': 'x'},
                {'distance_m': 1400, 'area_radius_m': 800}, {'alt_m': 5}, {'distance_m': '500'}, {'hold_s': True}):
        assert hata_kodu(core.it_ayar_dogrula, bad, 'multirotor') == 'invalid', bad
    assert hata_kodu(core.it_ayar_dogrula, {}, 'rover') == 'invalid'
    # başlangıç: aynı hat, mesafe kadar ayrık, kaçan önde (bakış yönünde), ikisi aynı yöne bakar
    for tip, pist in (('multirotor', 0), ('sabit_kanat', 75)):
        cfg = core.it_ayar_dogrula({'distance_m': 600, 'seed': 9}, tip)
        P = core.it_baslangiclari(cfg, tip, pist)
        c, e = P['chaser'], P['evader']
        assert abs(math.dist(c[:2], e[:2]) - 600) < 0.05 and c[2] == e[2], P
        h = math.radians(c[2])
        assert (e[0] - c[0]) * math.sin(h) + (e[1] - c[1]) * math.cos(h) > 599, 'kaçan önde'
        if tip == 'sabit_kanat':
            assert c[2] == 75.0
    assert core.it_baslangiclari(cfg, 'multirotor') == core.it_baslangiclari(cfg, 'multirotor')   # deterministik
    # koni açısı / burun
    assert abs(core.koni_acisi(core.burun(0, 0, 'dikey'), (0, 100, 0))) < 1e-9
    assert abs(core.koni_acisi(core.burun(90, 0, 'dikey'), (0, 100, 0)) - 90) < 1e-9
    assert abs(core.koni_acisi(core.burun(0, math.radians(30), 'ucak'), (0, 100, 100 * math.tan(math.radians(30))))) < 1e-6   # uçakta yunuslama dahil
    assert abs(core.koni_acisi(core.burun(0, math.radians(30), 'dikey'), (0, 100, 0))) < 1e-9   # kopterde gövde eğimi yok sayılır

    # ItDalasi saf: koruma → koni içinde kesintisiz tutma → angaje; koniden çıkınca sıfırlanır
    a = core.it_ayar_dogrula({'range_m': 150, 'cone_deg': 20, 'hold_s': 3, 'alt_m': 40, 'seed': 1}, 'multirotor')
    iz = core.ItDalasi(a, 0.0)
    ev = iz.konum('chaser', 0, 0, 10, 0, 0, 1.0) + iz.konum('evader', 0, 100, 10, 0, 0, 1.0)
    assert iz.koruma and ev == [] and iz.durum()['dist'] == 100   # irtifa düşük: koruma (angajman sayılmaz)
    for k in range(10):
        iz.konum('chaser', 0, 0, 10, 0, 0, 1.1 + k * 0.1); iz.konum('evader', 0, 100, 10, 0, 0, 1.1 + k * 0.1)
    assert iz.tutma == 0 and not iz.koni_ici
    ev = iz.konum('chaser', 0, 0, 40, 0, 0, 3.0) + iz.konum('evader', 0, 100, 40, 0, 0, 3.0)
    assert {'kind': 'guard_off'} in ev and {'kind': 'lock_on'} in ev and not iz.koruma, ev
    t = 3.0
    for _ in range(20):                                  # 2 sn tut
        t += 0.1; iz.konum('chaser', 0, 0, 40, 0, 0, t); iz.konum('evader', 0, 100, 40, 0, 0, t)
    assert 1.9 <= iz.tutma <= 2.1 and iz.koni_ici, iz.tutma
    ev = iz.konum('chaser', 0, 0, 40, 30, 0, t + 0.1)    # burun 30° saptı (> 20°) → kesinti, sayaç sıfır
    assert ev and ev[0]['kind'] == 'lock_off' and iz.tutma == 0
    t += 0.1
    for _ in range(25):
        t += 0.1; iz.konum('chaser', 0, 0, 40, 0, 0, t); iz.konum('evader', 0, 100, 40, 0, 0, t)
    assert not iz.bitti and iz.tutma < 3
    ev = []
    for _ in range(8):
        t += 0.1; ev += iz.konum('chaser', 0, 0, 40, 0, 0, t) + iz.konum('evader', 0, 100, 40, 0, 0, t)
    eng = [e for e in ev if e['kind'] == 'engage']
    assert eng and eng[0]['held_s'] >= 3 and iz.bitti and iz.durum()['max_hold_s'] >= 3, ev
    # menzil dışı (koni içinde ama 200 m) sayılmaz; koruma en geç KORUMA_S sonra kalkar; bayat örnek (> 2 sn fark) hesaplanmaz
    iz2 = core.ItDalasi(a, 0.0)
    for k in range(80):
        tt = 61.0 + k * 0.1; iz2.konum('chaser', 0, 0, 10, 0, 0, tt); iz2.konum('evader', 0, 200, 10, 0, 0, tt)
    assert not iz2.bitti and iz2.tutma == 0 and not iz2.koruma
    iz3 = core.ItDalasi(a, 0.0)
    iz3.konum('chaser', 0, 0, 40, 0, 0, 1.0); iz3.konum('evader', 0, 50, 40, 0, 0, 10.0)
    assert iz3.durum()['dist'] is None
    # alan dışı
    iz4 = core.ItDalasi(a, 0.0)
    assert iz4.konum('evader', a['area_radius_m'] + 1, 0, 40, 0, 0, 1.0) == [{'kind': 'area', 'role': 'evader'}] and iz4.bitti

    # Karsilasma: tam 2 oyuncu, roller, kazanan
    def kur(roles='host_chaser', seed=5, now=0.0, **kw):
        cfg = core.it_ayar_dogrula({'roles': roles, 'seed': seed, 'range_m': 150, 'cone_deg': 25, 'hold_s': 2, 'alt_m': 30, 'time_limit_min': 2, **kw}, 'multirotor')
        k = core.Karsilasma(11, (10, 'Kurucu'), [(20, 'Rakip')], {'type': 'multirotor'}, cfg, MERKEZ, now, [], tur='dogfight')
        k.katil(20, now + 1); k.hazir(10, now + 2); k.hazir(20, now + 3); k.tik(now + 3 + core.GERI_SAYIM_S)
        assert k.durum == core.YARIS and k.it is not None
        return k
    assert hata_kodu(core.Karsilasma, 1, (10, 'K'), [(20, 'A'), (30, 'B')], {}, core.it_ayar_dogrula({}, 'multirotor'), MERKEZ, 0, [], tur='dogfight') == 'invalid'
    assert hata_kodu(core.Karsilasma, 1, (10, 'K'), [(20, 'A')], {}, {}, MERKEZ, 0, [], tur='x') == 'invalid'
    k = kur('host_chaser')
    assert k.oyuncu(10).rol == 'chaser' and k.oyuncu(20).rol == 'evader' and k.dict(0)['kind'] == 'dogfight' and k.dict(0)['dogfight']['roles'] == {'10': 'chaser', '20': 'evader'}
    assert kur('host_evader').oyuncu(10).rol == 'evader'
    rs = {kur('random', seed=sd).oyuncu(10).rol for sd in range(1, 30)}
    assert rs == {'chaser', 'evader'}, 'rastgele roller iki yöne de düşer'
    assert kur('random', seed=7).oyuncu(10).rol == kur('random', seed=7).oyuncu(10).rol   # tohum = aynı roller

    def poz(k, uid, x, y, z, hdg, t):
        lat, lon = core.latlon(MERKEZ['lat'], MERKEZ['lon'], x, y)
        return k.konum(uid, lat, lon, MERKEZ['alt'] + z, t, hiz=15, heading=hdg, pitch=0)
    # (a) kovalayan tutar → ANGAJE → kovalayan kazanır
    t0 = k.baslangic_t
    t = t0
    ev = []
    for _ in range(40):
        t += 0.1
        ev += poz(k, 10, 0, 0, 35, 0, t) + poz(k, 20, 0, 90, 35, 0, t)
        if k.durum == core.BITTI:
            break
    assert k.durum == core.BITTI and k.kazanan == 10 and k.neden == 'angaje', (k.durum, k.neden)
    kinds = [e.get('kind') for e in ev if e['t'] == 'dogfight']
    assert kinds[:2] == ['guard_off', 'lock_on'] and 'engaged' in kinds, kinds
    r = [e for e in ev if e['t'] == 'result'][0]['result']
    assert r['kind'] == 'dogfight' and r['winner'] == 10 and r['dogfight']['engage_s'] >= 2 and abs(r['dogfight']['min_dist_m'] - 90) < 0.5 and r['standings'][0]['id'] == 10 and r['standings'][0]['role'] == 'chaser', r
    assert poz(k, 10, 0, 0, 35, 0, t + 1) == []   # bittikten sonra işlenmez
    # (b) süre biter → kaçan kazanır
    k = kur('host_evader')
    poz(k, 10, 0, 0, 35, 0, k.baslangic_t + 1)
    poz(k, 20, 0, 500, 35, 0, k.baslangic_t + 1)
    assert k.tik(k.baslangic_t + 119) == []
    ev = k.tik(k.baslangic_t + 120)
    assert k.durum == core.BITTI and k.neden == 'sure' and k.kazanan == 10 and ev[-1]['result']['winner'] == 10, ev   # 10 kaçan
    # (c) alan dışına çıkan kaybeder
    k = kur('host_chaser', area_radius_m=600)
    ev = poz(k, 20, 0, 650, 35, 0, k.baslangic_t + 5)
    assert k.durum == core.BITTI and k.neden == 'alan_disi' and k.kazanan == 10 and any(e['t'] == 'dogfight' and e['kind'] == 'area' and e['id'] == 20 for e in ev), ev
    # (d) çarpan kaybeder
    k = kur('host_chaser')
    ev = k.carpti(10, k.baslangic_t + 4)
    assert k.durum == core.BITTI and k.neden == 'carpti' and k.kazanan == 20, ev
    assert kur('host_chaser').carpti(99, 1) == []
    # (e) rakip ayrılır → kalan kazanır
    k = kur('host_chaser')
    k.ayril(20, k.baslangic_t + 3)
    assert k.durum == core.BITTI and k.neden == 'rakip_ayrildi' and k.kazanan == 10
    # halka yarışında carpti etkisiz; anlık görüntüde tür
    cfgh = core.halka_ayar_dogrula({'count': 2, 'seed': 3}, 'multirotor')
    kh = core.Karsilasma(12, (10, 'K'), [(20, 'A')], {}, cfgh, MERKEZ, 0.0, core.halkalar_uret(cfgh, MERKEZ))
    assert kh.carpti(10, 1) == [] and kh.dict(0)['kind'] == 'rings' and kh.dict(0)['dogfight'] is None
    print('  it dalaşı çekirdeği geçti')


# ================================================================ HEPGO API uçtan uca (sahte kinematik)
def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


class Kullanici:
    """Tek TestClient (tek olay döngüsü: karşılaşma görevi, oturumlar ve WS aynı döngüde) üzerinde kullanıcı başına çerez başlığı."""

    def __init__(self, c, u, p):
        c.cookies.clear()
        ok(c.post('/api/auth/login', json={'username': u, 'password': p}))
        self.tok = c.cookies.get(auth.COOKIE)
        c.cookies.clear()
        self.c = c

    def _h(self, kw):
        kw.setdefault('headers', {})['cookie'] = f'{auth.COOKIE}={self.tok}'
        return kw

    def get(self, url, **kw):
        return self.c.get(url, **self._h(kw))

    def post(self, url, **kw):
        return self.c.post(url, **self._h(kw))

    def put(self, url, **kw):
        return self.c.put(url, **self._h(kw))

    def delete(self, url, **kw):
        return self.c.delete(url, **self._h(kw))

    def websocket_connect(self, url, **kw):
        return self.c.websocket_connect(url, **self._h(kw))


def bekle(fn, sn=8.0, adim=0.05):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def ws_bekle(ws, kosul, sn=10.0, biriktir=None):
    bitis = time.time() + sn
    while time.time() < bitis:
        m = json.loads(ws.receive_text())
        if biriktir is not None:
            biriktir.append(m)
        if kosul(m):
            return m
    return None


def api_testleri():
    from app import db, notifications, push
    gonderilen = []
    eski_send = push.send
    push.send = lambda ids, payload, ttl=300: gonderilen.append((sorted(ids), payload))
    core_geri = core.GERI_SAYIM_S
    core.GERI_SAYIM_S = 1.0
    eski_kapanis = flightsim_match.KAPANIS_GECIKME_S
    flightsim_match.KAPANIS_GECIKME_S = 0.3
    M = '/api/drone/sim/matches'
    try:
        with TestClient(app, base_url='https://testserver') as tc:
            a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
            c1 = ok(a.post('/api/drone/centers', json={'name': 'Yarış Sahası', 'lat': MERKEZ['lat'], 'lon': MERKEZ['lon'], 'alt': 900}))
            for u, ad in (('ayse', 'Ayşe Pilot'), ('mehmet', 'Mehmet Pilot')):
                ok(a.post('/api/users', json={'username': u, 'full_name': ad, 'roles': [auth.PILOT], 'password': 'sifre-1234'}))
            ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
            ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'},
                     json={'changes': [{'node': 'drone.sim', 'cap': 'open', 'value': True}, {'node': 'drone.sim', 'cap': 'read', 'value': True}]}))
            p1, p2, mon = Kullanici(tc, 'ayse', 'sifre-1234'), Kullanici(tc, 'mehmet', 'sifre-1234'), Kullanici(tc, 'montaj', 'sifre-1234')
            me = {n: ok(c.get('/api/auth/me'))['id'] for n, c in (('admin', a), ('ayse', p1), ('mehmet', p2), ('montaj', mon))}

            # --- meta: davet edilebilir kullanıcılar (yazma izni olanlar; kendisi hariç; salt okuyan yok) ---
            m = ok(a.get(f'{M}/meta'))
            ids = {u['id'] for u in m['users']}
            assert me['ayse'] in ids and me['mehmet'] in ids and me['admin'] not in ids and me['montaj'] not in ids, m['users']
            assert m['limits']['players_max'] == 8 and 'rover' not in m['limits']['types'] and m['capacity'] == {'max': 6, 'used': 0} and m['can_create'], m
            assert ok(mon.get(f'{M}/meta'))['can_create'] is False
            pv = ok(a.post(f'{M}/rings-preview', json={'type': 'multirotor', 'center_id': c1['id'], 'rings': {'count': 5, 'min_alt_m': 20, 'max_alt_m': 50, 'seed': 9}}))
            assert len(pv['rings']) == 5 and pv['rings'] == ok(a.post(f'{M}/rings-preview', json={'type': 'multirotor', 'center_id': c1['id'], 'rings': {'count': 5, 'min_alt_m': 20, 'max_alt_m': 50, 'seed': 9}}))['rings']
            assert a.post(f'{M}/rings-preview', json={'type': 'multirotor', 'center_id': c1['id'], 'rings': {'min_alt_m': 90, 'max_alt_m': 20}}).status_code == 400

            # --- oluşturma doğrulaması ---
            ayar = {'type': 'multirotor', 'center_id': c1['id'], 'world': {'mode': 'procedural', 'seed': 4}, 'camera': 'day',
                    'site': {'radar': True, 'station': True, 'eo': True}, 'targets': [{'model': 'x'}], 'drone_id': 999}   # yer kontrol / hedef / dron kaydı yok sayılır
            halka = {'count': 3, 'min_alt_m': 20, 'max_alt_m': 40, 'diameter_m': 10, 'radius_m': 150, 'seed': 11}
            # (§47: davetsiz/botsuz = tek kişilik zaman denemesi — fpv_api'de denenir)
            assert a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['montaj']]}).status_code == 400   # simülatör yazma izni yok
            assert a.post(M, json={'settings': {**ayar, 'type': 'rover'}, 'rings': halka, 'invite': [me['ayse']]}).status_code == 400
            assert a.post(M, json={'settings': {**ayar, 'center_id': 9999}, 'rings': halka, 'invite': [me['ayse']]}).status_code == 400
            assert mon.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse']]}).status_code == 403
            eski_tavan = flightsim.MATCH_MAX_SESSIONS
            flightsim.MATCH_MAX_SESSIONS = 2
            assert a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse'], me['mehmet']]}).status_code == 409   # kaynak tavanı (3 > 2)
            flightsim.MATCH_MAX_SESSIONS = eski_tavan

            mt = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse'], me['mehmet']]}), 201)
            mid = mt['id']
            assert mt['state'] == 'LOBI' and len(mt['rings']) == 3 and mt['host_id'] == me['admin'], mt
            assert set(mt['settings']) <= {'type', 'center_id', 'world', 'model', 'power', 'layout', 'camera', 'drive'} and 'site' not in mt['settings'], mt['settings']
            st = {p['id']: p['status'] for p in mt['players']}
            assert st == {me['admin']: 'geldi', me['ayse']: 'davetli', me['mehmet']: 'davetli'}, st
            assert gonderilen and gonderilen[-1][0] == sorted([me['ayse'], me['mehmet']]) and gonderilen[-1][1]['url'] == f'/app#/drone/sim/match/{mid}', gonderilen
            with db.connect() as conn:
                u = db.row(conn.execute('SELECT * FROM users WHERE id = ?', (me['ayse'],)))
                assert db.row(conn.execute('SELECT state FROM drone_sim_matches WHERE id = ?', (mid,)))['state'] == 'LOBI'
            zil = ok(p1.get('/api/notifications'))
            it = next((x for x in zil['items'] if x['key'] == 'sim-match-invite'), None)
            assert it and it['href'] == f'#/drone/sim/match/{mid}' and it['count'] == 1, zil
            assert mon.get(f'{M}/{mid}').status_code == 403   # oyuncu değil
            assert ok(p1.get(f'{M}/{mid}'))['id'] == mid
            assert any(x['id'] == mid for x in ok(p2.get(M))) and not any(x['id'] == mid for x in ok(mon.get(M)))
            assert p1.post(f'{M}/{mid}/start').status_code == 403 and p1.post(f'{M}/{mid}/cancel').status_code == 403
            assert a.post(f'{M}/{mid}/start').status_code == 409   # gelmeyen var ama süre dolmadı / 2 oyuncu yok

            with p1.websocket_connect(f'/ws/drone/match/{mid}') as w1, a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
                h1 = ws_bekle(w1, lambda m: m['t'] == 'hello')
                assert h1['me'] == me['ayse'] and h1['match']['id'] == mid
                ws_bekle(wa, lambda m: m['t'] == 'hello')
                with mon.websocket_connect(f'/ws/drone/match/{mid}') as wm:
                    assert json.loads(wm.receive_text())['error'] == 'forbidden'
                # sohbet
                w1.send_text(json.dumps({'t': 'chat', 'text': 'Selam!'}))
                cm = ws_bekle(wa, lambda m: m['t'] == 'chat')
                assert cm['text'] == 'Selam!' and cm['id'] == me['ayse']
                # davetliler gelir → HAZIRLIK → oyuncu oturumları
                assert ok(p1.post(f'{M}/{mid}/join'))['state'] == 'LOBI'
                zil = ok(p1.get('/api/notifications'))
                assert not any(x['key'] == 'sim-match-invite' for x in zil['items'])   # geldi → zil düşer
                assert ok(p2.post(f'{M}/{mid}/join'))['state'] == 'HAZIRLIK'
                ws_bekle(wa, lambda m: m['t'] == 'state' and m['state'] == 'HAZIRLIK')
                d = bekle(lambda: (lambda x: x if all(p['session_id'] for p in x['players']) else None)(ok(a.get(f'{M}/{mid}'))))
                assert d, d
                sids = {p['id']: p['session_id'] for p in d['players']}
                ss = {u: flightsim.MANAGER.get(sid) for u, sid in sids.items()}
                assert all(s is not None and s.match_id == mid for s in ss.values())
                assert len({(round(s.start['lat'], 6), round(s.start['lon'], 6)) for s in ss.values()}) == 3   # farklı başlangıç
                for s in ss.values():
                    assert s.center['id'] == c1['id'] and s.world['seed'] == 4 and s.gcs is None and s.hedefler is None   # aynı dünya, yer kontrol yok
                pts = [core.enu(MERKEZ['lat'], MERKEZ['lon'], s.start['lat'], s.start['lon']) for s in ss.values()]
                assert min(math.dist(p, q) for i, p in enumerate(pts) for q in pts[i + 1:]) >= core.AYRIK_M - 0.1, pts
                assert all(bekle(lambda s=s: s.state == 'HAZIR') for s in ss.values())
                sahte0 = ss[me['ayse']].sahte
                assert abs(sahte0.lat0 - ss[me['ayse']].start['lat']) < 1e-9   # sahte kinematik başlangıçta
                # normal oturum sınırı karşılaşma oturumlarından etkilenmez
                n1 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}), 201)
                ok(a.delete(f"/api/drone/sim/sessions/{n1['id']}"))
                # komut kapısı + başkasının aracı
                sa = sids[me['ayse']]
                r = p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'takeoff', 'params': {'alt': 20}})
                assert r.status_code == 400 and 'başlamadı' in r.text, r.text
                assert p2.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'mode', 'params': {'mode': 'GUIDED'}}).status_code == 403
                ok(p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'mode', 'params': {'mode': 'GUIDED'}}))   # kip serbest
                with p2.websocket_connect(f'/ws/drone/match/{mid}') as w2:
                    ws_bekle(w2, lambda m: m['t'] == 'hello')
                    for w in (w1, w2, wa):
                        w.send_text(json.dumps({'t': 'ready'}))
                    cd = ws_bekle(w2, lambda m: m['t'] == 'countdown')
                    assert cd and cd['start_at'] > time.time() - 0.5, cd
                    assert p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'arm'}).status_code == 400   # geri sayımda da kapalı
                    ws_bekle(w2, lambda m: m['t'] == 'state' and m['state'] == 'YARIS', sn=5)
                    ok(p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'takeoff', 'params': {'alt': 20}}))   # yarışta serbest
                    pos = ws_bekle(w2, lambda m: m['t'] == 'pos' and len(m['p']) == 3)
                    assert pos and {'id', 'lat', 'lon', 'alt_msl', 'yaw', 'rings', 'next', 'dist'} <= set(pos['p'][0]), pos
                    # rota pilotları: Ayşe tüm parkur (hızlı), Mehmet yalnız 1. halka
                    rings = d['rings']
                    rota_pilotu(ss[me['ayse']], rings, MERKEZ, hiz=120.0)
                    rota_pilotu(ss[me['mehmet']], rings, MERKEZ, hiz=60.0, kadar=1)
                    gorulen = []
                    res = ws_bekle(w2, lambda m: m['t'] == 'result', sn=25, biriktir=gorulen)
                    assert res, [m['t'] for m in gorulen][-20:]
                    rs = res['result']
                    assert rs['winner'] == me['ayse'] and rs['reason'] == 'birinci_bitirdi' and rs['standings'][0]['id'] == me['ayse'] and rs['standings'][0]['rings'] == 3, rs
                    assert rs['standings'][0]['time_s'] > 0 and rs['standings'][0]['max_speed_ms'] > 50, rs['standings'][0]
                    ringev = [m for m in gorulen if m['t'] == 'ring' and m['id'] == me['ayse']]
                    assert [m['i'] for m in ringev] == [1, 2, 3], ringev
                    fin = [m for m in gorulen if m['t'] == 'finish']
                    assert fin and fin[0]['id'] == me['ayse']
                    assert ws_bekle(w1, lambda m: m['t'] == 'result')['result']['winner'] == me['ayse']   # diğer istemcide de sonuç
                    ix = {s['id']: s for s in rs['standings']}
                    assert ix[me['admin']]['rank'] == 3 and ix[me['admin']]['rings'] == 0 and ix[me['mehmet']]['rank'] == 2, rs['standings']
                    # kapanış: oturumlar kapanır, drone_sim_runs.match_id
                    assert bekle(lambda: all(flightsim.MANAGER.get(s) is None for s in sids.values()), sn=15)
            def _runs():   # uçuş kayıtları oturum kapanışında arka planda yazılır (önceden zamanlamaya bağlı kırılgan)
                with db.connect() as conn:
                    return db.rows(conn.execute('SELECT owner_id, match_id FROM drone_sim_runs WHERE match_id = ?', (mid,)))
            runs = bekle(lambda: (lambda r: r if len(r) >= 3 else None)(_runs()), sn=15) or _runs()
            with db.connect() as conn:
                row = db.row(conn.execute('SELECT * FROM drone_sim_matches WHERE id = ?', (mid,)))
            assert sorted(r['owner_id'] for r in runs) == sorted(me[n] for n in ('admin', 'ayse', 'mehmet')), runs
            assert row['state'] == 'BITTI' and row['winner_id'] == me['ayse'] and json.loads(row['result'])['winner'] == me['ayse'] and row['started_at'] and row['ended_at'], dict(row)
            g = ok(p2.get(f'{M}/{mid}'))
            assert g['state'] == 'BITTI'
            assert ok(p1.post(f'{M}/{mid}/join'))['state'] == 'BITTI'   # zaten gelmiş oyuncu: değişiklik yok

            # --- iptal: kurucu iptal eder; davet düşer ---
            m2 = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse']]}), 201)
            assert any(x['key'] == 'sim-match-invite' for x in ok(p1.get('/api/notifications'))['items'])
            assert ok(a.post(f"{M}/{m2['id']}/cancel"))['state'] == 'IPTAL'
            assert not any(x['key'] == 'sim-match-invite' for x in ok(p1.get('/api/notifications'))['items'])
            assert p1.post(f"{M}/{m2['id']}/join").status_code == 409
            # davetli reddeder (leave) → kurucu yalnız → iptal
            m3 = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse']]}), 201)
            r3 = ok(p1.post(f"{M}/{m3['id']}/leave"))
            assert r3['state'] == 'IPTAL' and r3['reason'] == 'oyuncu_kalmadi', r3
            # kurucu oyuncu çıkarır → kalan hepsi gelmiş → HAZIRLIK
            m4 = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse'], me['mehmet']]}), 201)
            ok(p1.post(f"{M}/{m4['id']}/join"))
            assert p1.post(f"{M}/{m4['id']}/kick", json={'user_id': me['mehmet']}).status_code == 403
            assert ok(a.post(f"{M}/{m4['id']}/kick", json={'user_id': me['mehmet']}))['state'] == 'HAZIRLIK'
            assert ok(a.post(f"{M}/{m4['id']}/cancel"))['state'] == 'IPTAL'
            assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=10)
            it_dalasi_api(a, p1, me, ayar, M)
            bot_api(a, p1, me, ayar, M)
            fpv_api(a, p1, me, ayar, M)
            print('  API uçtan uca geçti (karşılaşma', mid, ')')
    finally:
        push.send = eski_send
        core.GERI_SAYIM_S = core_geri
        flightsim_match.KAPANIS_GECIKME_S = eski_kapanis


def it_dalasi_api(a, p1, me, ayar, M):
    """§41 HEPGO API: tür doğrulaması, tam 2 oyuncu, roller, başlangıçta mesafe (kaçan önde), Sıfırla kapısı, sahte kinematikle kovalayan kaçanı
    koni içinde tutar → ANGAJE → kovalayan kazanır; pos `df` alanı; sonuç + DB (kind, game_cfg); geçmiş listesinde tür; rövanşta roller değişir."""
    from app import db
    df = {'distance_m': 400, 'alt_m': 30, 'range_m': 150, 'cone_deg': 25, 'hold_s': 2, 'time_limit_min': 3, 'roles': 'host_chaser'}
    assert a.post(M, json={'settings': ayar, 'kind': 'dogfight', 'dogfight': df, 'invite': [me['ayse'], me['mehmet']]}).status_code == 400   # tam 2 oyuncu
    assert a.post(M, json={'settings': ayar, 'kind': 'dogfight', 'dogfight': {**df, 'cone_deg': 80}, 'invite': [me['ayse']]}).status_code == 400
    assert a.post(M, json={'settings': ayar, 'kind': 'yaris', 'invite': [me['ayse']]}).status_code == 400
    meta = ok(a.get(f'{M}/meta'))
    assert meta['limits']['kinds'] == ['rings', 'dogfight', 'fpv'] and meta['limits']['dogfight']['cone_deg'] == [15.0, 45.0], meta['limits'].get('dogfight')
    m = ok(a.post(M, json={'settings': ayar, 'kind': 'dogfight', 'dogfight': df, 'invite': [me['ayse']]}), 201)
    mid = m['id']
    assert m['kind'] == 'dogfight' and m['rings'] == [] and m['rings_cfg']['range_m'] == 150, m
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT kind, game_cfg, rings_cfg FROM drone_sim_matches WHERE id = ?', (mid,)))
    assert row['kind'] == 'dogfight' and json.loads(row['game_cfg'])['cone_deg'] == 25 and row['rings_cfg'] == '{}', dict(row)
    with p1.websocket_connect(f'/ws/drone/match/{mid}') as w1, a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
        ws_bekle(w1, lambda x: x['t'] == 'hello')
        ok(p1.post(f'{M}/{mid}/join'))
        st = ws_bekle(wa, lambda x: x['t'] == 'match' and x['match']['state'] == 'HAZIRLIK')['match']
        roles = {p['id']: p['role'] for p in st['players']}
        assert roles == {me['admin']: 'chaser', me['ayse']: 'evader'}, roles
        d = bekle(lambda: (lambda x: x if all(p['session_id'] for p in x['players']) else None)(ok(a.get(f'{M}/{mid}'))))
        sids = {p['id']: p['session_id'] for p in d['players']}
        ss = {u: flightsim.MANAGER.get(sid) for u, sid in sids.items()}
        assert all(bekle(lambda s=s: s.state == 'HAZIR') for s in ss.values())
        P = core.it_baslangiclari(d['rings_cfg'], 'multirotor')
        pc = core.enu(MERKEZ['lat'], MERKEZ['lon'], ss[me['admin']].start['lat'], ss[me['admin']].start['lon'])
        pe = core.enu(MERKEZ['lat'], MERKEZ['lon'], ss[me['ayse']].start['lat'], ss[me['ayse']].start['lon'])
        assert abs(math.dist(pc, pe) - 400) < 1 and math.dist(pc, P['chaser'][:2]) < 0.5 and math.dist(pe, P['evader'][:2]) < 0.5, (pc, pe, P)
        for w in (w1, wa):
            w.send_text(json.dumps({'t': 'ready'}))
        ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=8)
        sa = sids[me['ayse']]
        r = p1.post(f'/api/drone/sim/sessions/{sa}/cmd', json={'name': 'reset'})
        assert r.status_code == 400 and 'Sıfırla' in r.text, r.text   # it dalaşında ışınlanma yok
        yon = P['evader'][2]
        kac = it_pilotu(ss[me['ayse']], MERKEZ, yon, P['evader'][:2], hiz=8.0, alt=30.0)
        it_pilotu(ss[me['admin']], MERKEZ, yon, P['chaser'][:2], gecikme_m=90.0, takip=kac)
        gorulen = []
        res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=30, biriktir=gorulen)
        assert res, [x['t'] for x in gorulen][-15:]
        rs = res['result']
        assert rs['kind'] == 'dogfight' and rs['winner'] == me['admin'] and rs['reason'] == 'angaje' and rs['dogfight']['engage_s'] >= 2 and rs['dogfight']['min_dist_m'] <= 91, rs
        dfs = [x['df'] for x in gorulen if x['t'] == 'pos' and x.get('df')]
        assert dfs and any(x['in_cone'] for x in dfs) and any(x['guard'] for x in dfs) and dfs[-1]['roles'] == {str(me['admin']): 'chaser', str(me['ayse']): 'evader'}, dfs[-3:]
        kinds = [x['kind'] for x in gorulen if x['t'] == 'dogfight']
        assert 'guard_off' in kinds and 'lock_on' in kinds and 'engaged' in kinds, kinds
        assert ws_bekle(w1, lambda x: x['t'] == 'result')['result']['winner'] == me['admin']
        # rövanş: yalnız kurucu; roller değişir; eski salona bildirim
        assert p1.post(f'{M}/{mid}/rematch').status_code == 403
        assert bekle(lambda: all(flightsim.MANAGER.get(s) is None for s in sids.values()), sn=15)
        rm = ok(a.post(f'{M}/{mid}/rematch'), 201)
        assert rm['kind'] == 'dogfight' and rm['rings_cfg']['roles'] == 'host_evader' and rm['id'] != mid, rm
        assert ws_bekle(w1, lambda x: x['t'] == 'rematch')['id'] == rm['id']
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT state, reason, winner_id, kind FROM drone_sim_matches WHERE id = ?', (mid,)))
    assert row['state'] == 'BITTI' and row['reason'] == 'angaje' and row['winner_id'] == me['admin'] and row['kind'] == 'dogfight', dict(row)
    gecmis = {x['id']: x for x in ok(p1.get(M))}
    assert gecmis[mid]['kind'] == 'dogfight' and gecmis[mid]['rings_cfg']['hold_s'] == 2, gecmis[mid]
    ok(p1.post(f"{M}/{rm['id']}/join"))   # rövanş: roller ters
    st = ok(a.get(f"{M}/{rm['id']}"))
    assert {p['id']: p['role'] for p in st['players']} == {me['admin']: 'evader', me['ayse']: 'chaser'}, st['players']
    assert ok(a.post(f"{M}/{rm['id']}/cancel"))['state'] == 'IPTAL'
    assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=10)
    print('  it dalaşı API geçti (karşılaşma', mid, ')')


def _bot_mac(a, M, govde):
    """§44: oluştur → (yalnız botlarla hemen HAZIRLIK) → oturumlar HAZIR. Dönüş (karşılaşma, {uid: oturum})."""
    m = ok(a.post(M, json=govde), 201)
    d = bekle(lambda: (lambda x: x if x['state'] == 'HAZIRLIK' and all(p['session_id'] for p in x['players']) else None)(ok(a.get(f"{M}/{m['id']}"))), sn=15)
    assert d, ok(a.get(f"{M}/{m['id']}"))
    ss = {p['id']: flightsim.MANAGER.get(p['session_id']) for p in d['players']}
    assert all(bekle(lambda s=s: s is not None and s.state == 'HAZIR') for s in ss.values())
    return d, ss


def fpv_api(a, p1, me, ayar, M):
    """§47 HAZIR FPV PARKURLARI + TEK KİŞİLİK (HEPGO, sahte kinematik): meta/katalog, doğrulama 400'leri (sabit kanat, bilinmeyen parkur, kural),
    tek kişilik FPV (davet/bot yok → hemen HAZIRLIK; dünya parkurdan) → yarış hattından tam tur → tamamlandi + kişisel rekor + drone_fpv_records
    (hayalet çözülür) + skor tablosu + hayalet API; çarpma kuralı 'reset' → Sıfırla; FPV + Zor bot (bot parkuru izler, kaydı yok); tek kişilik halka
    yarışı (hemen HAZIRLIK)."""
    from app import db
    from app import flightsim_fpv as F
    from tests.match_bot import fpv_pilotu
    eski_son = core.SON_CAGRI_S
    core.SON_CAGRI_S = 3.0
    try:
        meta = ok(a.get(f'{M}/meta'))
        assert meta['limits']['min_players'] == {'rings': 1, 'dogfight': 2, 'fpv': 1} and len(meta['limits']['fpv']['courses']) == 8
        cs = ok(a.get('/api/drone/sim/fpv/courses'))
        assert [c['id'] for c in cs['courses']] == list(F.PARKUR_IDLER) and cs['courses'][0]['record'] is None
        assert a.get('/api/drone/sim/fpv/courses/yok').status_code == 404 and a.get('/api/drone/sim/fpv/courses/hangar/ghost').status_code == 404
        assert ok(a.get('/api/drone/sim/fpv/courses/hangar'))['course']['obstacles']
        fpv = {'course_id': 'woodframe', 'laps': 1}
        assert a.post(M, json={'settings': {**ayar, 'type': 'sabit_kanat'}, 'kind': 'fpv', 'fpv': fpv, 'invite': []}).status_code == 400
        assert a.post(M, json={'settings': ayar, 'kind': 'fpv', 'fpv': {'course_id': 'yok'}, 'invite': []}).status_code == 400
        assert a.post(M, json={'settings': ayar, 'kind': 'fpv', 'fpv': {**fpv, 'crash_rule': 'x'}, 'invite': []}).status_code == 400
        assert a.post(M, json={'settings': ayar, 'kind': 'dogfight', 'invite': []}).status_code == 400   # it dalaşı tek kişilik olamaz
        m = F.parkur('woodframe')['gate_count']

        def kosu(hiz, cfg=fpv):
            d, ss = _bot_mac(a, M, {'settings': ayar, 'kind': 'fpv', 'fpv': cfg, 'invite': [], 'bots': []})
            mid = d['id']
            s = ss[me['admin']]
            assert d['kind'] == 'fpv' and len(d['players']) == 1 and len(d['rings']) == 1 + m * cfg['laps'] and s.world.get('fpv_course') == 'woodframe', d.keys()
            assert s.world['mode'] == 'procedural' and s.world['runway'] is False and s.world['building_count'] == 0
            with a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
                ws_bekle(wa, lambda x: x['t'] == 'hello')
                wa.send_text(json.dumps({'t': 'ready'}))
                ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
                fpv_pilotu(s, d['rings'], d['center'], hiz=hiz)
                gor = []
                res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=60, biriktir=gor)
                assert res, [x['t'] for x in gor][-20:]
                tip = [x['t'] for x in gor]
                assert tip.count('ring') == len(d['rings']) and 'lap' in tip and 'sector' in tip and 'hit' not in tip and 'miss' not in tip, tip
                assert bekle(lambda: flightsim.MANAGER.get(s.id) is None, sn=15)
            return mid, res['result']
        mid1, r1 = kosu(14.0)
        st = r1['standings'][0]
        assert r1['solo'] and r1['reason'] == 'tamamlandi' and r1['winner'] == me['admin'] and st['new_pb'] and st['pb_prev'] is None, r1
        with db.connect() as conn:
            rec = db.row(conn.execute('SELECT * FROM drone_fpv_records WHERE match_id = ?', (mid1,)))
            row = db.row(conn.execute('SELECT kind, game_cfg, rings_cfg FROM drone_sim_matches WHERE id = ?', (mid1,)))
        assert rec and rec['user_id'] == me['admin'] and rec['solo'] == 1 and abs(rec['time_s'] - st['time_s']) < 0.01 and rec['type'] == 'multirotor', rec
        assert row['kind'] == 'fpv' and json.loads(row['game_cfg'])['course_id'] == 'woodframe' and row['rings_cfg'] == '{}'
        assert len(F.hayalet_coz(rec['ghost'])) > 30
        mid2, r2 = kosu(10.0)
        assert r2['standings'][0]['new_pb'] is False and abs(r2['standings'][0]['pb_prev'] - st['time_s']) < 0.01
        lb = ok(a.get('/api/drone/sim/fpv/courses/woodframe?laps=1'))
        assert len(lb['leaderboard']) == 1 and lb['leaderboard'][0]['user_id'] == me['admin'] and abs(lb['my_best']['time_s'] - st['time_s']) < 0.01, lb
        gh = ok(a.get('/api/drone/sim/fpv/courses/woodframe/ghost?laps=1'))
        assert gh['ghost'].startswith('g1.') and len(gh['splits']) == 1 + m and abs(gh['time_s'] - st['time_s']) < 0.01
        assert ok(p1.get(f"/api/drone/sim/fpv/courses/woodframe/ghost?laps=1&user_id={me['admin']}"))['user_id'] == me['admin']   # firma içi skor hayaleti
        g = ok(a.get(f'{M}/{mid1}'))
        assert g['kind'] == 'fpv' and g['rings_cfg']['course_id'] == 'woodframe' and g['result']['solo']
        lst = ok(a.get(M))
        assert lst[0]['kind'] == 'fpv' and len(lst[0]['players']) == 1
        # çarpma kuralı 'reset': engel teması → oturum Sıfırla (başlangıca döner)
        d, ss = _bot_mac(a, M, {'settings': ayar, 'kind': 'fpv', 'fpv': {**fpv, 'crash_rule': 'reset'}, 'invite': []})
        s = ss[me['admin']]
        with a.websocket_connect(f"/ws/drone/match/{d['id']}") as wa:
            ws_bekle(wa, lambda x: x['t'] == 'hello')
            wa.send_text(json.dumps({'t': 'ready'}))
            ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
            k = s.sahte
            mer = d['center']
            st_ = {'p': [-12.0, 0.0, 2.0]}

            def adim(dt):   # batıdan eve doğru: x −12 → +12, y 0, z 2 (dikmelere/duvara çarpar)
                k.sure_ms += dt * 1000
                k.armed, k.mode = True, 'GUIDED'
                st_['p'][0] += 6.0 * dt
                k.lat, k.lon = core.latlon(mer['lat'], mer['lon'], st_['p'][0], st_['p'][1])
                k.alt_rel = st_['p'][2]
            k.adim = adim
            hit = ws_bekle(wa, lambda x: x['t'] == 'hit', sn=10)
            assert hit and hit['rule'] == 'reset' and hit['id'] == me['admin'], hit
            assert ws_bekle(wa, lambda x: x['t'] == 'reset', sn=3)
            ok(a.post(f"{M}/{d['id']}/cancel"))
        assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
        # FPV + Zor bot: insan hızlı → kazanır; bot kapıları izler; bot kaydı yazılmaz
        d, ss = _bot_mac(a, M, {'settings': ayar, 'kind': 'fpv', 'fpv': fpv, 'invite': [], 'bots': [{'level': 'hard'}]})
        bot = next(p for p in d['players'] if p['is_bot'])
        with a.websocket_connect(f"/ws/drone/match/{d['id']}") as wa:
            ws_bekle(wa, lambda x: x['t'] == 'hello')
            wa.send_text(json.dumps({'t': 'ready'}))
            ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
            fpv_pilotu(ss[me['admin']], d['rings'], d['center'], hiz=25.0)
            res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=90)
            assert res and res['result']['winner'] == me['admin'] and not res['result']['solo'], res
            br = next(p for p in res['result']['standings'] if p['id'] == bot['id'])
            assert br['rings'] >= 2, br
        assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
        with db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM drone_fpv_records WHERE user_id < 0').fetchone()[0] == 0
        # tek kişilik halka yarışı: hemen HAZIRLIK
        halka = {'count': 2, 'min_alt_m': 10, 'max_alt_m': 16, 'diameter_m': 14, 'radius_m': 80, 'seed': 5}
        d, ss = _bot_mac(a, M, {'settings': ayar, 'rings': halka, 'invite': []})
        assert len(d['players']) == 1 and d['kind'] == 'rings'
        ok(a.post(f"{M}/{d['id']}/cancel"))
        assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
    finally:
        core.SON_CAGRI_S = eski_son
    print('  FPV parkurları + tek kişilik API geçti')


def bot_api(a, p1, me, ayar, M):
    """§44 YAPAY ZEKÂ PİLOT (sahte kinematik, uçtan uca): doğrulama, yalnız botla kurulum → hemen HAZIRLIK, bot kendi SITL'inde (sahibi bot →
    insan komutu 403, uçuş kaydı yok), bot hazır sayılır, YARIS'ta kendisi ARM + kalkış + halkalar → BOT KAZANIR (winner_id NULL, players.is_bot);
    insan hızlı uçarsa İNSAN KAZANIR; it dalaşında kovalayan bot (Zor) → ANGAJE; salonda bot ekle/çıkar; kapasite 409."""
    from app import db
    halka = {'count': 2, 'min_alt_m': 10, 'max_alt_m': 16, 'diameter_m': 14, 'radius_m': 80, 'seed': 5}
    meta = ok(a.get(f'{M}/meta'))
    assert meta['limits']['bot']['levels'] == ['easy', 'normal', 'hard'], meta['limits'].get('bot')
    assert a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [], 'bots': [{'level': 'uzman'}]}).status_code == 400
    assert a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [], 'bots': ['hard'] * 8}).status_code == 400
    assert a.post(M, json={'settings': ayar, 'kind': 'dogfight', 'invite': [me['ayse']], 'bots': ['hard']}).status_code == 400   # it dalaşı: tek rakip
    eski = flightsim.MATCH_MAX_SESSIONS
    flightsim.MATCH_MAX_SESSIONS = 2
    r = a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [], 'bots': ['easy', 'easy']})
    assert r.status_code == 409 and 'yapay zekâ' in r.text, r.text
    flightsim.MATCH_MAX_SESSIONS = eski

    # --- 1) yalnız bot rakip; insan uçmaz → bot kazanır ---
    d, ss = _bot_mac(a, M, {'settings': ayar, 'rings': halka, 'invite': [], 'bots': [{'level': 'hard'}]})
    mid = d['id']
    bot = next(p for p in d['players'] if p['is_bot'])
    assert bot['id'] < 0 and bot['level'] == 'hard' and bot['name'] == 'AI-Şahin (Zor)' and bot['color'], bot
    sb = ss[bot['id']]
    assert sb.bot == {'uid': bot['id'], 'level': 'hard'} and sb.owner['id'] == bot['id']
    assert a.post(f"/api/drone/sim/sessions/{sb.id}/cmd", json={'name': 'mode', 'params': {'mode': 'GUIDED'}}).status_code == 403   # botun aracı insana kapalı
    with a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
        ws_bekle(wa, lambda x: x['t'] == 'hello')
        wa.send_text(json.dumps({'t': 'ready'}))   # bot için ready gerekmez (oturum HAZIR → hazır)
        ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
        assert bekle(lambda: sb.sahte.armed, sn=5), 'bot ARM etmedi'
        gorulen = []
        res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=120, biriktir=gorulen)
        assert res, ([x for x in gorulen if x['t'] == 'ring'], sb.tele.get('alt_rel'))
        rs = res['result']
        assert rs['winner'] == bot['id'] and rs['reason'] == 'birinci_bitirdi' and rs['standings'][0]['is_bot'] and rs['standings'][0]['level'] == 'hard', rs
        assert [x['i'] for x in gorulen if x['t'] == 'ring' and x['id'] == bot['id']] == [1, 2]
        assert bekle(lambda: all(flightsim.MANAGER.get(s.id) is None for s in ss.values()), sn=15)
    def satir():
        with db.connect() as conn:
            r = db.row(conn.execute('SELECT * FROM drone_sim_matches WHERE id = ?', (mid,)))
            return r if r['state'] == 'BITTI' else None
    row = bekle(satir, sn=5)
    with db.connect() as conn:
        runs = db.rows(conn.execute('SELECT owner_id FROM drone_sim_runs WHERE match_id = ?', (mid,)))
    assert row['state'] == 'BITTI' and row['winner_id'] is None and row['bots'] == 1 and json.loads(row['result'])['winner'] == bot['id'], dict(row)
    pl = {p['id']: p for p in json.loads(row['players'])}
    assert pl[bot['id']]['is_bot'] and pl[bot['id']]['level'] == 'hard' and not pl[me['admin']]['is_bot'], pl
    assert [r['owner_id'] for r in runs] == [me['admin']], runs   # bot oturumu uçuş kaydı yazmaz
    g = ok(a.get(f'{M}/{mid}'))
    assert g['winner'] == bot['id']
    print('  bot kazandı (karşılaşma', mid, ')')

    # --- 2) insan hızlı uçar → insan kazanır (bot Kolay) ---
    d, ss = _bot_mac(a, M, {'settings': ayar, 'rings': halka, 'invite': [], 'bots': ['easy']})
    mid = d['id']
    bot = next(p for p in d['players'] if p['is_bot'])
    with a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
        ws_bekle(wa, lambda x: x['t'] == 'hello')
        wa.send_text(json.dumps({'t': 'ready'}))
        ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
        rota_pilotu(ss[me['admin']], d['rings'], MERKEZ, hiz=40.0)
        res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=40)
        assert res and res['result']['winner'] == me['admin'] and res['result']['standings'][1]['id'] == bot['id'], res
    def kazanan_db():
        with db.connect() as conn:
            return db.row(conn.execute('SELECT winner_id FROM drone_sim_matches WHERE id = ?', (mid,)))['winner_id'] == me['admin']
    assert bekle(kazanan_db, sn=5)
    assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
    print('  insan kazandı (karşılaşma', mid, ')')

    # --- 3) it dalaşı: kovalayan bot (Zor) insan kaçanı angaje eder ---
    df = {'distance_m': 300, 'alt_m': 25, 'range_m': 150, 'cone_deg': 30, 'hold_s': 2, 'time_limit_min': 3, 'area_radius_m': 800, 'roles': 'host_evader'}
    d, ss = _bot_mac(a, M, {'settings': ayar, 'kind': 'dogfight', 'dogfight': df, 'invite': [], 'bots': ['hard']})
    mid = d['id']
    roles = {p['id']: p['role'] for p in d['players']}
    bot = next(p for p in d['players'] if p['is_bot'])
    assert roles == {me['admin']: 'evader', bot['id']: 'chaser'}, roles
    P = core.it_baslangiclari(d['rings_cfg'], 'multirotor')
    with a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
        ws_bekle(wa, lambda x: x['t'] == 'hello')
        wa.send_text(json.dumps({'t': 'ready'}))
        ws_bekle(wa, lambda x: x['t'] == 'state' and x['state'] == 'YARIS', sn=10)
        it_pilotu(ss[me['admin']], MERKEZ, P['evader'][2], P['evader'][:2], hiz=3.0, alt=25.0)
        gorulen = []
        res = ws_bekle(wa, lambda x: x['t'] == 'result', sn=120, biriktir=gorulen)
        assert res, [x.get('df') for x in gorulen if x['t'] == 'pos'][-2:]
        rs = res['result']
        assert rs['winner'] == bot['id'] and rs['reason'] == 'angaje', rs
    assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
    print('  it dalaşı bot angaje etti (karşılaşma', mid, ')')

    # --- 4) salonda bot ekle / çıkar (davetli beklenirken) ---
    m = ok(a.post(M, json={'settings': ayar, 'rings': halka, 'invite': [me['ayse']]}), 201)
    assert p1.post(f"{M}/{m['id']}/bot", json={'level': 'normal'}).status_code == 403   # yalnız kurucu
    m2 = ok(a.post(f"{M}/{m['id']}/bot", json={'level': 'normal'}))
    b = next(p for p in m2['players'] if p['is_bot'])
    assert b['status'] == 'geldi' and b['level'] == 'normal' and m2['state'] == 'LOBI', m2['players']
    m3 = ok(a.post(f"{M}/{m['id']}/kick", json={'user_id': b['id']}))
    assert not any(p['is_bot'] for p in m3['players']) and m3['state'] == 'LOBI', m3
    ok(a.post(f"{M}/{m['id']}/bot", json={'level': 'easy'}))
    m4 = ok(p1.post(f"{M}/{m['id']}/join"))   # davetli geldi → HAZIRLIK (insan + bot)
    assert m4['state'] == 'HAZIRLIK' and len(m4['players']) == 3, m4
    assert ok(a.post(f"{M}/{m['id']}/cancel"))['state'] == 'IPTAL'
    assert bekle(lambda: flightsim.MANAGER.acik_sayisi(match=True) == 0, sn=15)
    print('  bot API geçti')


def main():
    halka_testleri()
    baslangic_testleri()
    gecis_testleri()
    siralama_testi()
    durum_makinesi_testleri()
    it_dalasi_testleri()
    api_testleri()
    print('test_flightsim_match: TAMAM')


if __name__ == '__main__':
    main()
