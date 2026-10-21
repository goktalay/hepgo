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
from tests.match_bot import rota_pilotu  # noqa: E402

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
    assert hata_kodu(core.Karsilasma, 1, (10, 'Kurucu'), [], {}, cfg, MERKEZ, 0, H) == 'invalid'   # en az bir davetli
    assert hata_kodu(core.Karsilasma, 1, (10, 'Kurucu'), [(10, 'Kendisi')], {}, cfg, MERKEZ, 0, H) == 'invalid'   # kendini davet sayılmaz
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
    ev = k3.tik(3 + core.HAZIRLIK_ZAMAN_ASIMI_S + 1)   # 20 hazırlanamadı → düşer → < 2 oyuncu → IPTAL
    assert k3.oyuncu(20).durum == core.DUSTU and k3.durum == core.IPTAL and k3.neden == 'oyuncu_kalmadi', ev
    k4 = core.Karsilasma(4, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k4.ayril(10, 5)[0]['state'] == core.IPTAL and k4.neden == 'kurucu_ayrildi'
    k5 = core.Karsilasma(5, (10, 'K'), [(20, 'A'), (30, 'B')], {}, cfg, MERKEZ, 0.0, H)
    k5.katil(20, 1)
    assert hata_kodu(k5.zorla_baslat, 10, 30) == 'conflict'
    ev = k5.zorla_baslat(10, core.LOBI_ZORLA_S)
    assert k5.oyuncu(30).durum == core.DUSTU and k5.oyuncu(30).dusme_nedeni == 'gelmedi' and k5.durum == core.HAZIRLIK, ev
    k6 = core.Karsilasma(6, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k6.ayril(20, 1)[-1]['state'] == core.IPTAL   # tek davetli reddetti → kurucu yalnız → iptal
    k7 = core.Karsilasma(7, (10, 'K'), [(20, 'A')], {}, cfg, MERKEZ, 0.0, H)
    assert k7.tik(core.LOBI_ZAMAN_ASIMI_S + 1)[0]['state'] == core.IPTAL and k7.neden == 'zaman_asimi'
    assert k7.iptal(99999) == []   # son durumdan çıkılmaz
    print('  durum makinesi geçti')


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
            assert a.post(M, json={'settings': ayar, 'rings': halka, 'invite': []}).status_code == 400
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
            with db.connect() as conn:
                runs = db.rows(conn.execute('SELECT owner_id, match_id FROM drone_sim_runs WHERE match_id = ?', (mid,)))
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
            print('  API uçtan uca geçti (karşılaşma', mid, ')')
    finally:
        push.send = eski_send
        core.GERI_SAYIM_S = core_geri
        flightsim_match.KAPANIS_GECIKME_S = eski_kapanis


def main():
    halka_testleri()
    baslangic_testleri()
    gecis_testleri()
    siralama_testi()
    durum_makinesi_testleri()
    api_testleri()
    print('test_flightsim_match: TAMAM')


if __name__ == '__main__':
    main()
