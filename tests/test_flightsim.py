"""Uçuş Simülatörü (drone.sim) — sözleşme §7: meta, oturum aç/limit/kapat, komut yetkisi (salt okuyan 403), WS hello/tele (50 Hz sahte akış, rc override + serbest bırakma paketi),
UDP köprüsü (sahte "SITL" TCP sunucusu ile ham bayt gidiş-dönüş, GCS kilidi). SITL yok: HEPGO_SITL=0 sahte kinematik.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_flightsim
"""
import json
import math
import os
import socket
import struct
import tempfile
import threading
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='24550', SIM_MAX_SESSIONS='2')

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app import auth, flightsim, sim_terrain  # noqa: E402
from app.main import app  # noqa: E402


# ---------------------------------------------------------------- gerçek topoğrafya vekili (ağsız: FETCH sahte)
def terrarium_png(taban=900.0, egim=0.5):
    """256×256 terrarium karosu: h(x) = taban + x·egim (satırdan bağımsız). Pillow ile üretilir."""
    import io
    from PIL import Image
    im = Image.new('RGB', (256, 256))
    px = im.load()
    for y in range(256):
        for x in range(256):
            v = int(round((taban + x * egim + 32768) * 256))
            px[x, y] = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


OVERPASS_ORNEK = {'elements': [
    {'type': 'way', 'id': 1, 'tags': {'building': 'yes', 'height': '12 m'}, 'geometry': [{'lat': 39.925, 'lon': 32.837}, {'lat': 39.9251, 'lon': 32.837}, {'lat': 39.9251, 'lon': 32.8371}, {'lat': 39.925, 'lon': 32.837}]},
    {'type': 'way', 'id': 2, 'tags': {'building': 'apartments', 'building:levels': '5'}, 'geometry': [{'lat': 39.926, 'lon': 32.838}, {'lat': 39.9261, 'lon': 32.838}, {'lat': 39.9261, 'lon': 32.8381}]},
    {'type': 'way', 'id': 3, 'tags': {'building': 'house'}, 'geometry': [{'lat': 39.927, 'lon': 32.839}, {'lat': 39.9271, 'lon': 32.839}, {'lat': 39.9271, 'lon': 32.8391}]},
    {'type': 'way', 'id': 4, 'tags': {'building': 'yes'}, 'geometry': [{'lat': 39.927, 'lon': 32.839}, {'lat': 39.9271, 'lon': 32.839}]},   # 2 nokta: atlanır
    {'type': 'relation', 'id': 5, 'tags': {'building': 'yes', 'height': '30'}, 'members': [
        {'type': 'way', 'role': 'outer', 'geometry': [{'lat': 39.93, 'lon': 32.84}, {'lat': 39.931, 'lon': 32.84}, {'lat': 39.931, 'lon': 32.841}, {'lat': 39.93, 'lon': 32.84}]},
        {'type': 'way', 'role': 'inner', 'geometry': [{'lat': 39.9302, 'lon': 32.8402}, {'lat': 39.9305, 'lon': 32.8402}, {'lat': 39.9305, 'lon': 32.8405}]}]},
    {'type': 'way', 'id': 6, 'tags': {'landuse': 'forest'}, 'geometry': [{'lat': 39.92, 'lon': 32.83}, {'lat': 39.921, 'lon': 32.83}, {'lat': 39.921, 'lon': 32.831}]},
    {'type': 'way', 'id': 7, 'tags': {'natural': 'wood'}, 'geometry': [{'lat': 39.92, 'lon': 32.84}, {'lat': 39.921, 'lon': 32.84}, {'lat': 39.921, 'lon': 32.841}]},
    {'type': 'way', 'id': 8, 'tags': {'natural': 'water'}, 'geometry': [{'lat': 39.91, 'lon': 32.83}, {'lat': 39.911, 'lon': 32.83}, {'lat': 39.911, 'lon': 32.831}]},
    {'type': 'way', 'id': 9, 'tags': {'aeroway': 'runway', 'width': '45'}, 'geometry': [{'lat': 39.90, 'lon': 32.85}, {'lat': 39.91, 'lon': 32.85}]},
    {'type': 'node', 'id': 10, 'tags': {'building': 'yes'}, 'lat': 39.9, 'lon': 32.8},   # geometri yok: atlanır
]}


class SahteFetch:
    """sim_terrain.FETCH yerine: URL'e göre terrarium PNG / sahte JPEG / Overpass JSON; çağrı sayar; istenirse hata üretir."""

    def __init__(self):
        self.cagri = []
        self.hata = None          # KaynakHata örneği: bir sonraki çağrıda fırlatılır (hata_say kez)
        self.hata_say = 1
        self.png = terrarium_png()

    def __call__(self, url, timeout=10.0, data=None):
        self.cagri.append((url, timeout, data))
        if self.hata is not None:
            e = self.hata
            self.hata_say -= 1
            if self.hata_say <= 0:
                self.hata, self.hata_say = None, 1
            raise e
        if url.startswith('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/'):
            assert timeout == sim_terrain.TIMEOUT and data is None
            return self.png
        if url.startswith('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/'):
            return b'\xff\xd8\xff\xe0SAHTE-JPEG'
        if url in sim_terrain.OVERPASS_URLS:
            assert data and 'way["building"]' in data['data'] and 'out geom' in data['data'] and timeout == sim_terrain.OSM_TIMEOUT
            return json.dumps(OVERPASS_ORNEK).encode()
        raise AssertionError(f'beklenmeyen URL: {url}')


def terrain_birim_testleri():
    # terrarium çözme (saf PNG çözücü): h = taban + x·egim
    png = terrarium_png(900.0, 0.5)
    assert sim_terrain.terrarium_yukseklik(png, 0, 0) == 900.0 and sim_terrain.terrarium_yukseklik(png, 100, 7) == 950.0
    assert sim_terrain.terrarium_yukseklik(png, 255, 255) == 1027.5 and sim_terrain.terrarium_yukseklik(png, 999, -4) == 1027.5   # kenar kırpma
    # Web Mercator gidiş-dönüş
    fx, fy = sim_terrain.lonlat_karo(32.837, 39.925, 13)
    lon, lat = sim_terrain.karo_lonlat(fx, fy, 13)
    assert abs(lon - 32.837) < 1e-9 and abs(lat - 39.925) < 1e-9 and int(fx) == 4843 and int(fy) == 3103, (fx, fy)
    # bina yüksekliği kuralları
    assert sim_terrain.bina_yuksekligi({'height': '12 m'}) == 12.0 and sim_terrain.bina_yuksekligi({'height': '40 ft'}) == 12.2
    assert sim_terrain.bina_yuksekligi({'building:levels': '5'}) == 15.0 and sim_terrain.bina_yuksekligi({'building:levels': '5', 'roof:levels': '1'}) == 16.0
    assert all(6 <= sim_terrain.bina_yuksekligi({}, i) <= 12 for i in range(50)) and sim_terrain.bina_yuksekligi({}, 7) == sim_terrain.bina_yuksekligi({}, 7)
    assert sim_terrain.bina_yuksekligi({'height': 'yüksek'}, 3) == sim_terrain.bina_yuksekligi({}, 3)
    # OSM sadeleştirme
    sade = sim_terrain.osm_sadelestir(OVERPASS_ORNEK)
    assert [b['h'] for b in sade['buildings']] == [12.0, 15.0, sim_terrain.bina_yuksekligi({}, 3), 30.0], sade['buildings']
    assert sade['buildings'][0]['poly'] == [[39.925, 32.837], [39.9251, 32.837], [39.9251, 32.8371]]   # kapalı halkanın tekrarlı son noktası atılır
    assert len(sade['buildings'][3]['poly']) == 3   # relation: yalnız outer; kapalı halka açılır
    assert len(sade['forests']) == 2 and len(sade['water']) == 1 and len(sade['runways']) == 1
    assert sade['runways'][0]['heading'] == 0.0 and sade['runways'][0]['width'] == 45.0
    assert sim_terrain.osm_sadelestir({}) == {'buildings': [], 'forests': [], 'water': [], 'runways': []}
    # karo planı: z seçimi ve karo sayıları
    sahte = SahteFetch()
    sim_terrain.FETCH = sahte
    try:
        p = sim_terrain.terrain_plani(39.925, 32.837, 4000)
        assert p['z'] == 13 and p['img_z'] == 16 and len(p['tiles']) == 4 and 80 <= len(p['img_tiles']) <= 110, (len(p['tiles']), len(p['img_tiles']))
        assert p['elev_url_template'] == '/api/drone/sim/tile/elev/{z}/{x}/{y}' and p['attribution']['img'] == 'Esri, Maxar, Earthstar Geographics'
        assert p['home_elev'] == sim_terrain.ev_irtifa(39.925, 32.837) and 900 <= p['home_elev'] <= 1027.5, p['home_elev']
        assert sim_terrain.terrain_plani(39.925, 32.837, 8000)['z'] == 12 and sim_terrain.terrain_plani(39.925, 32.837, 50)['size_m'] == sim_terrain.SIZE_MIN
        # ev irtifası karoları: z13 (iki plan + ev_irtifa aynı karo → tek indirme, önbellek) ve z12 (8 km planı) → toplam 2 kaynak çağrısı
        assert [c[0].split('terrarium/')[1] for c in sahte.cagri] == ['13/4843/3103.png', '12/2421/1551.png'], sahte.cagri
        # uzak arazi planı (?far=1; §9): 48 km varsayılan, yükseklik z 10 (2×2…3×3 karo), uydu z 12 (≤ 64 karo), ev irtifası yine z13 karosundan (önbellekte → yeni çağrı yok)
        n0 = len(sahte.cagri)
        f = sim_terrain.terrain_plani(39.925, 32.837, None, uzak=True)
        assert f['far'] is True and f['z'] == 10 and f['img_z'] == 12 and f['size_m'] == 48000 and 4 <= len(f['tiles']) <= 9 and 36 <= len(f['img_tiles']) <= 64, (f['z'], len(f['tiles']), len(f['img_tiles']))
        assert f['home_elev'] == p['home_elev'] and len(sahte.cagri) == n0, 'uzak plan ev irtifasını z13 önbellekli karodan okur'
        assert sim_terrain.terrain_plani(39.925, 32.837, 5000, uzak=True)['size_m'] == sim_terrain.UZAK_SIZE_MIN and sim_terrain.terrain_plani(39.925, 32.837, 99999, uzak=True)['size_m'] == sim_terrain.UZAK_SIZE_MAX
        assert p['far'] is False and sim_terrain.terrain_plani(39.925, 32.837, None)['size_m'] == 4000
        # kaynak kapalı → home_elev null (plan yine döner)
        sim_terrain.karo_yolu('elev', 13, 4843, 3103).unlink()
        sahte.hata = sim_terrain.KaynakHata(503, 'kapalı')
        assert sim_terrain.terrain_plani(39.925, 32.837, 4000)['home_elev'] is None
        for bad in [(91, 0, 4000), (0, 181, 4000), ('x', 0, 4000)]:
            try:
                sim_terrain.parametre_dogrula(*bad)
                raise AssertionError(bad)
            except ValueError:
                pass
        # --- ArduPilot arazi protokolü (§18): TERRAIN_REQUEST (blok SW köşesi, spacing, 56 bit maske) → TERRAIN_DATA parçaları ---
        sahte.hata = None
        la, lo = sim_terrain.konum_ofset(39.925, 32.837, 1000, 1000)   # Location::offset: 1 km kuzey/doğu
        assert abs(la - 39.925 - 0.0089832) < 1e-6 and abs(lo - 32.837 - 0.0089832 / math.cos(math.radians(39.925 + 0.0044916))) < 1e-6, (la, lo)
        h_ev = sim_terrain.yukseklik(39.925, 32.837)   # bilineer; sahte karo h = 900 + x·0,5 (piksel sütunu) → doğuya artar, kuzeye sabit
        assert 900 <= h_ev <= 1027.5 and abs(h_ev - sim_terrain.ev_irtifa(39.925, 32.837)) < 0.6, (h_ev, sim_terrain.ev_irtifa(39.925, 32.837))
        assert sim_terrain.yukseklik(39.925, 32.837 + 0.001) > h_ev and abs(sim_terrain.yukseklik(39.925 + 0.001, 32.837) - h_ev) < 1e-6
        assert sim_terrain.BLOK_BIT == 56 and sim_terrain.PARCA == 4 and (sim_terrain.BLOK_MUL_X, sim_terrain.BLOK_MUL_Y) == (7, 8)
        lat7, lon7 = int(39.925e7), int(32.837e7)
        bl, atl = sim_terrain.terrain_bloklari(lat7, lon7, 100, (1 << 56) - 1)
        assert atl == 0 and [b for b, _ in bl] == list(range(56)) and all(len(d) == 16 and all(isinstance(v, int) for v in d) for _, d in bl), (atl, len(bl))
        d0 = dict(bl)[0]
        assert d0[0] == int(round(h_ev)), (d0[0], h_ev)                                   # SW köşe = istek konumu
        assert d0[4] == d0[0] and d0[8] == d0[0] and d0[12] == d0[0], d0                   # data[i]: i//4 kuzey adımı (sahte karoda sabit), i%4 doğu adımı
        assert 2 <= d0[1] - d0[0] <= 5 and d0[3] > d0[2] > d0[1], d0                     # 100 m doğu ≈ +3,5 m (0,5 m/px, ≈ 14 m/px)
        # gridbit = kuzey_parça·8 + doğu_parça: bit 1 → 400 m doğu (≈ +14 m), bit 8 → 400 m kuzey (sahte karoda aynı değer)
        d1, d8 = dict(bl)[1], dict(bl)[8]
        assert 10 <= d1[0] - d0[0] <= 18 and d8[0] == d0[0], (d1[0], d8[0], d0[0])
        bl2, _ = sim_terrain.terrain_bloklari(lat7, lon7, 100, 0b101)
        assert [b for b, _ in bl2] == [0, 2] and dict(bl2)[0] == d0, bl2                 # yalnız maskedeki parçalar
        assert sim_terrain.terrain_bloklari(lat7, lon7, 0, 7) == ([], 0)
        bl3, atl3 = sim_terrain.terrain_bloklari(lat7, lon7, 100, 0b11, yukseklik_fn=lambda la_, lo_: 1e6 if lo_ > 32.8371 else -1e6)   # int16 kırpma
        assert atl3 == 0 and dict(bl3)[0][0] == -32768 and dict(bl3)[1][0] == 32767, bl3
        sayac = {'n': 0}

        def hatali(la_, lo_):
            sayac['n'] += 1
            if sayac['n'] % 2 == 0:
                raise sim_terrain.KaynakHata(503, 'kapalı')
            return 500.0
        bl4, atl4 = sim_terrain.terrain_bloklari(lat7, lon7, 100, 0b111, yukseklik_fn=hatali)
        assert atl4 == 3 and bl4 == [], (bl4, atl4)                                      # kaynak hatası → parça atlanır (SITL yeniden ister)
        assert sim_terrain.terrain_bloklari(lat7, lon7, 100, 1, yukseklik_fn=lambda la_, lo_: 123.4) == ([(0, [123] * 16)], 0)
    finally:
        sim_terrain.FETCH = sim_terrain._fetch
    print('  sim_terrain birim testleri geçti')


def arazi_sunum_testleri(a, c_altsiz):
    """§18 arazi sunumu (oturum yolu, sahte kipte): gerçek arazi kipinde `terrain` özeti; SITL_ENABLED=0 → serve False; sunum açılınca `_isle(TERRAIN_REQUEST)`
    → iş parçacığında sim_terrain → TERRAIN_DATA (lat/lon/spacing yankı, gridbit, int16) `_gonder`; TERRAIN_REPORT → tele.terrain_agl/terrain_h + rapor;
    prosedürel kipte kapalı; TERRAIN_ENABLE/SPACING oturum parametresi (drone_params hariç)."""
    from app import drone_params
    sahte = SahteFetch()
    sim_terrain.FETCH = sahte
    try:
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c_altsiz['id'], 'world': {'mode': 'real'}}), 201)
        sid = s['id']
        assert s['terrain'] == {'serve': False, 'requests': 0, 'blocks': 0, 'skipped': 0, 'errors': 0, 'last_ts': None, 'report': None}, s['terrain']   # sahte kip: sunum yok
        ses = flightsim.MANAGER.get(sid)
        assert bekle(lambda: ses.state == 'HAZIR' or None)
        assert flightsim.TERRAIN_PARAMLARI == (('TERRAIN_ENABLE', 1.0), ('TERRAIN_SPACING', 100.0)) and flightsim.TERRAIN_KIPLER == ('real', 'google3d')
        assert all(drone_params.haric_mi(ad) for ad, _ in flightsim.TERRAIN_PARAMLARI) and not drone_params.haric_mi('TERRAIN_FOLLOW')
        d = flightsim._dialect()
        ayristir = d.MAVLink(None)
        arac = d.MAVLink(None, srcSystem=ses.sysid, srcComponent=1)
        gond = []
        ses._gonder = lambda msg: gond.append(msg) or True
        req = lambda mask: next(iter(ayristir.parse_buffer(arac.terrain_request_encode(int(39.925e7), int(32.837e7), 100, mask).pack(arac)) or []))   # noqa: E731
        ses._isle(req((1 << 56) - 1))   # sunum kapalı: sayaç bile artmaz
        time.sleep(0.3)
        assert gond == [] and ses.arazi['requests'] == 0
        ses.arazi['serve'] = True   # gerçek SITL kipi gibi
        ses._isle(req((1 << 54) | 0b101))   # bit 0, 2, 54
        assert bekle(lambda: ses.arazi['blocks'] == 3 or None), ses.arazi
        assert ses.arazi['requests'] == 1 and ses.arazi['skipped'] == 0 and ses.arazi['errors'] == 0 and ses.arazi['last_ts'], ses.arazi
        assert [m.get_type() for m in gond] == ['TERRAIN_DATA'] * 3 and [m.gridbit for m in gond] == [0, 2, 54], gond
        m0 = gond[0]
        assert (m0.lat, m0.lon, m0.grid_spacing) == (int(39.925e7), int(32.837e7), 100) and len(m0.data) == 16 and m0.data[0] == int(round(sim_terrain.yukseklik(39.925, 32.837))), m0
        bl, _ = sim_terrain.terrain_bloklari(int(39.925e7), int(32.837e7), 100, 1 << 54)
        assert list(gond[2].data) == bl[0][1]
        # iş sürerken gelen istekler: son istek sıraya alınır (ilk bitince işlenir); SITL yanıtlanmayan parçaları yeniden ister
        gond.clear()
        ses._isle(req(0b1)); ses._isle(req(0b10)); ses._isle(req(0b100))
        assert bekle(lambda: (ses.arazi['requests'] == 4 and ses._arazi_is.done() and ses._arazi_sonraki is None) or None), (ses.arazi, ses._arazi_sonraki)
        time.sleep(0.2)
        assert 1 <= len(gond) <= 3 and gond[0].gridbit == 0 and gond[-1].gridbit in (0, 2), [m.gridbit for m in gond]
        # kaynak hatası: parça atlanır, sayaç + tek sarı olay (önbellekler boşaltılır ki kaynak gerçekten sorulsun)
        gond.clear()
        olaylar = []
        ses._olay = lambda t, sev=6: olaylar.append((t, sev))
        sahte.hata, sahte.hata_say = sim_terrain.KaynakHata(503, 'kapalı'), 99
        sim_terrain._coz.clear()
        for p in sim_terrain.CACHE_DIR.glob('elev/13/*/*.png'):
            p.unlink()
        ses._isle(req(0b11))
        assert bekle(lambda: ses.arazi['skipped'] == 2 or None), ses.arazi
        assert gond == [] and ses.arazi['blocks'] >= 4 and any('Arazi verisi' in t and sev == 4 for t, sev in olaylar), (ses.arazi, olaylar)
        sahte.hata = None
        # TERRAIN_REPORT → tele + özet (loaded > 0 ve terrain_height ≠ 0 iken AGL)
        rep = next(iter(ayristir.parse_buffer(arac.terrain_report_encode(int(39.925e7), int(32.837e7), 100, 912.5, 37.2, 3, 12).pack(arac)) or []))
        ses._isle(rep)
        assert ses.tele['terrain_agl'] == 37.2 and ses.tele['terrain_h'] == 912.5, ses.tele
        g = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
        assert g['terrain']['report'] == {'lat': 39.925, 'lon': 32.837, 'spacing': 100, 'terrain_height': 912.5, 'current_height': 37.2, 'pending': 3, 'loaded': 12, 'ts': g['terrain']['report']['ts']}, g['terrain']
        assert g['terrain']['requests'] == 5 and g['terrain']['blocks'] >= 4 and g['terrain']['skipped'] == 2, g['terrain']
        rep0 = next(iter(ayristir.parse_buffer(arac.terrain_report_encode(int(39.925e7), int(32.837e7), 100, 0.0, 0.0, 56, 0).pack(arac)) or []))
        ses._isle(rep0)
        assert ses.tele['terrain_agl'] is None and ses.tele['terrain_h'] is None
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        # prosedürel kip: sunum kapalı (gerçek SITL'de de)
        s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c_altsiz['id'], 'world': {'mode': 'procedural'}}), 201)
        assert s2['terrain']['serve'] is False
        ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
    finally:
        sim_terrain.FETCH = sim_terrain._fetch
    print('  arazi sunumu (TERRAIN_REQUEST → TERRAIN_DATA) testleri geçti')


def vekil_testleri(a, mon, c_altsiz):
    """REST vekil uçları: /terrain, /tile (önbellek, LRU boyut, hata kodları), /osm (7 gün önbellek); yetki; gerçek kipte ev irtifası."""
    sahte = SahteFetch()
    sim_terrain.FETCH = sahte
    try:
        p = ok(a.get('/api/drone/sim/terrain', params={'lat': 39.925, 'lon': 32.837, 'size_m': 4000}))
        assert p['z'] == 13 and p['home_elev'] is not None and p['tiles'] and p['img_tiles']
        assert a.get('/api/drone/sim/terrain', params={'lat': 99, 'lon': 32.837}).status_code == 400
        assert a.get('/api/drone/sim/terrain', params={'lon': 32.837}).status_code == 422
        f = ok(a.get('/api/drone/sim/terrain', params={'lat': 39.925, 'lon': 32.837, 'far': 1}))   # uzak arazi planı (§9)
        assert f['far'] is True and f['z'] == 10 and f['img_z'] == 12 and f['size_m'] == 48000 and f['home_elev'] == p['home_elev'], (f['z'], f['size_m'])
        # karo: ilk istek kaynaktan, ikincisi önbellekten; içerik türü
        t = p['tiles'][0]
        n0 = len(sahte.cagri)
        url = f"/api/drone/sim/tile/elev/{p['z']}/{t['x']}/{t['y']}"
        r = a.get(url)
        assert r.status_code == 200 and r.headers['content-type'].startswith('image/png') and r.content == sahte.png and 'max-age=86400' in r.headers['cache-control'], r.headers
        r2 = a.get(url)
        assert r2.status_code == 200 and r2.content == sahte.png
        assert len(sahte.cagri) == n0 + (0 if (t['x'], t['y']) == (4843, 3103) else 1), 'ikinci istek önbellekten gelmeli'
        r = a.get(f"/api/drone/sim/tile/img/{p['img_z']}/{p['img_tiles'][0]['x']}/{p['img_tiles'][0]['y']}")
        assert r.status_code == 200 and r.headers['content-type'].startswith('image/jpeg') and r.content.startswith(b'\xff\xd8')
        assert 'World_Imagery/MapServer/tile/16/' in sahte.cagri[-1][0] and sahte.cagri[-1][0].endswith(f"/{p['img_tiles'][0]['y']}/{p['img_tiles'][0]['x']}"), sahte.cagri[-1]   # {z}/{y}/{x} sırası
        # geçersiz tür / sınır dışı → 404; URL sabit (SSRF yok): kind yalnız elev|img
        assert a.get('/api/drone/sim/tile/http/13/1/1').status_code == 404
        assert a.get('/api/drone/sim/tile/elev/13/99999/1').status_code == 404
        assert a.get('/api/drone/sim/tile/elev/25/1/1').status_code == 404
        # kaynak hataları: 503 (ulaşılamadı/zaman aşımı) ve 502 (HTTP hatası)
        sahte.hata = sim_terrain.KaynakHata(503, 'Kaynak zaman aşımı')
        r = a.get('/api/drone/sim/tile/elev/12/2421/1540')
        assert r.status_code == 503 and 'zaman aşımı' in r.text, (r.status_code, r.text)
        sahte.hata = sim_terrain.KaynakHata(502, 'Kaynak 404 döndü')
        assert a.get('/api/drone/sim/tile/elev/12/2421/1541').status_code == 502
        assert a.get('/api/drone/sim/tile/elev/12/2421/1541').status_code == 200   # hata önbelleğe yazılmadı; sonraki deneme başarılı
        # LRU: sınır düşürülünce eski karolar silinir, toplam sınırın altına iner
        eski_limit = sim_terrain.CACHE_LIMIT
        sim_terrain.CACHE_LIMIT = len(sahte.png) * 2 + 10
        try:
            for i in range(4):
                assert a.get(f'/api/drone/sim/tile/elev/12/2400/{1500 + i}').status_code == 200
            kalan = [pth for pth in sim_terrain.CACHE_DIR.rglob('*') if pth.is_file()]
            assert sum(pth.stat().st_size for pth in kalan) <= sim_terrain.CACHE_LIMIT, [str(k) for k in kalan]
            assert sim_terrain.karo_yolu('elev', 12, 2400, 1503).is_file() and not sim_terrain.karo_yolu('elev', 12, 2400, 1500).is_file()
        finally:
            sim_terrain.CACHE_LIMIT = eski_limit
        assert sim_terrain.onbellek_ozeti()['limit'] == eski_limit
        # OSM: sadeleştirilmiş JSON; ikinci istek önbellekten (7 gün); bayat önbellek yenilenir
        n0 = len(sahte.cagri)
        o = ok(a.get('/api/drone/sim/osm', params={'lat': 39.925, 'lon': 32.837, 'size_m': 4000}))
        assert len(o['buildings']) == 4 and o['buildings'][0] == {'poly': [[39.925, 32.837], [39.9251, 32.837], [39.9251, 32.8371]], 'h': 12.0}, o['buildings'][0]
        assert len(o['forests']) == 2 and len(o['water']) == 1 and o['runways'][0]['heading'] == 0.0 and o['cached_at'] and o['bbox']['south'] < 39.925 < o['bbox']['north']
        assert len(sahte.cagri) == n0 + 1 and sahte.cagri[-1][0] == sim_terrain.OVERPASS_URL
        o2 = ok(a.get('/api/drone/sim/osm', params={'lat': 39.925, 'lon': 32.837, 'size_m': 4000}))
        assert o2 == o and len(sahte.cagri) == n0 + 1, 'OSM ikinci istek önbellekten gelmeli'
        yol = sim_terrain.osm_yolu(39.925, 32.837, 4000)
        os.utime(yol, (time.time() - sim_terrain.OSM_TTL - 5, time.time() - sim_terrain.OSM_TTL - 5))
        ok(a.get('/api/drone/sim/osm', params={'lat': 39.925, 'lon': 32.837, 'size_m': 4000}))
        assert len(sahte.cagri) == n0 + 2, 'bayat OSM önbelleği yenilenmeli'
        # OSM kaynağı kapalı → 503 (ön yüz uyarı gösterir); bozuk yanıt → 502
        sahte.hata, sahte.hata_say = sim_terrain.KaynakHata(503, 'Kaynağa ulaşılamadı: ConnectError'), 2   # iki Overpass sunucusu da kapalı
        n1 = len(sahte.cagri)
        r = a.get('/api/drone/sim/osm', params={'lat': 40.1, 'lon': 33.0, 'size_m': 3000})
        assert r.status_code == 503 and 'ulaşılamadı' in r.text, (r.status_code, r.text)
        assert [c[0] for c in sahte.cagri[n1:]] == list(sim_terrain.OVERPASS_URLS), sahte.cagri[n1:]   # yedek de denendi
        sahte.hata = sim_terrain.KaynakHata(503, 'ilk kapalı')   # yalnız ilki kapalı → yedekten 200
        assert a.get('/api/drone/sim/osm', params={'lat': 40.2, 'lon': 33.0, 'size_m': 3000}).status_code == 200 and sahte.cagri[-1][0] == sim_terrain.OVERPASS_URLS[1]
        assert a.get('/api/drone/sim/osm', params={'lat': 40.1, 'lon': 33.0, 'size_m': 50}).status_code == 200   # size_m alt sınıra kırpılır
        # yetki: salt okuyan GET yapabilir; modülsüz 403
        assert mon.get('/api/drone/sim/terrain', params={'lat': 39.925, 'lon': 32.837}).status_code == 200
        assert mon.get(f"/api/drone/sim/tile/elev/{p['z']}/{t['x']}/{t['y']}").status_code == 200
        # world.mode doğrulama + gerçek kipte merkez irtifası boşsa SITL ev irtifası = terrarium (home_elev)
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c_altsiz['id'], 'world': {'mode': 'uydu'}}).status_code == 400
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c_altsiz['id'], 'world': {'mode': 'real', 'building_count': 0}}), 201)
        assert s['world']['mode'] == 'real' and s['center']['alt'] == sim_terrain.ev_irtifa(39.925, 32.837) and 900 <= s['center']['alt'] <= 1027.5, s['center']
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c_altsiz['id'], 'world': {'mode': 'procedural'}}), 201)
        assert s['center']['alt'] is None and s['center']['alt_entered'] is None and s['world']['mode'] == 'procedural'   # prosedürel: dokunulmaz
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        # §9 EV İRTİFASI KURALI: gerçek arazi kipinde merkez kaydındaki `alt` (1500 m; PROD "Bedesten" vakası) KULLANILMAZ → SITL ev irtifası
        # terrarium (≈ 900–1027 m); girilen değer `alt_entered`; fark > 15 m → oturum notu (olay şeridi). Prosedürelde kayıtlı değer aynen kullanılır.
        c_yanlis = ok(a.post('/api/drone/centers', json={'name': 'Yanlış İrtifalı Merkez', 'lat': 39.925, 'lon': 32.837, 'alt': 1500}))
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c_yanlis['id'], 'world': {'mode': 'real', 'building_count': 0}}), 201)
        h_ev = sim_terrain.ev_irtifa(39.925, 32.837)
        assert s['center']['alt'] == h_ev and s['center']['alt_entered'] == 1500.0 and abs(h_ev - 1500) > flightsim.EV_FARK_UYARI, s['center']
        ses = flightsim.MANAGER.get(s['id'])
        assert ses.alt_not and '1500 m' in ses.alt_not and f'{h_ev:.0f} m' in ses.alt_not and 'arazi' in ses.alt_not, ses.alt_not
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c_yanlis['id'], 'world': {'mode': 'procedural'}}), 201)
        assert s['center']['alt'] == 1500.0 and s['center']['alt_entered'] == 1500.0 and flightsim.MANAGER.get(s['id']).alt_not is None, s['center']
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        ok(a.delete(f"/api/drone/centers/{c_yanlis['id']}"))
        # --- Google 3B kipi (§10): anahtar yokken kapalı (meta, 404, oturum 400); anahtar varsa meta açık, /g3d-key no-store, oturum açılır,
        #     ev irtifası yine açık veriden (Google Elevation API kullanılmaz); salt okuyan izleyici de anahtarı alır (karoları görmeli)
        eski_key = flightsim.GOOGLE_KEY
        try:
            flightsim.GOOGLE_KEY = ''
            assert ok(a.get('/api/drone/sim/meta'))['google3d'] == {'enabled': False}
            assert a.get('/api/drone/sim/g3d-key').status_code == 404
            r = a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c_altsiz['id'], 'world': {'mode': 'google3d'}})
            assert r.status_code == 400 and 'GOOGLE_MAPS_API_KEY' in r.text, (r.status_code, r.text)
            try:
                flightsim.world_dogrula({'mode': 'google3d'})
                raise AssertionError('kapalıyken world_dogrula geçmemeli')
            except flightsim.SimHata as e:
                assert e.kod == 'invalid'
            flightsim.GOOGLE_KEY = 'AIza-test-anahtar'
            assert flightsim.world_dogrula({'mode': 'google3d', 'runway': False})['mode'] == 'google3d'
            assert ok(a.get('/api/drone/sim/meta'))['google3d'] == {'enabled': True}
            r = a.get('/api/drone/sim/g3d-key')
            assert r.status_code == 200 and r.json() == {'key': 'AIza-test-anahtar'} and r.headers['cache-control'] == 'no-store', (r.headers, r.text)
            assert mon.get('/api/drone/sim/g3d-key').status_code == 200   # salt okuyan: izlerken karoları çizmek için anahtar gerekir
            s = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c_altsiz['id'], 'world': {'mode': 'google3d', 'runway': False}}), 201)
            assert s['world']['mode'] == 'google3d' and s['world']['runway'] is False and s['center']['alt'] == sim_terrain.ev_irtifa(39.925, 32.837), s
            ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        finally:
            flightsim.GOOGLE_KEY = eski_key
    finally:
        sim_terrain.FETCH = sim_terrain._fetch
    print('  vekil (terrain/tile/osm) testleri geçti')

TELE_ALANLARI = {'rs', 'ps', 'ys', 'tbm', 'tbm_pos', 'ts', 'lat', 'lon', 'alt_msl', 'alt_rel', 'roll', 'pitch', 'yaw', 'vn', 've', 'vd', 'airspeed', 'groundspeed', 'heading', 'climb',
                 'mode', 'armed', 'gps_fix', 'sats', 'batt_v', 'batt_pct', 'throttle', 'rc', 'home', 'gcs_connected', 'gcs_addr', 'servo'}


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))
    return c.cookies.get(auth.COOKIE)


def bekle(fn, sn=5.0, adim=0.05):
    bitis = time.time() + sn
    while time.time() < bitis:
        v = fn()
        if v:
            return v
        time.sleep(adim)
    return fn()


def ws_bekle(ws, kosul, sn=3.0):
    """WS'den kosul(msg) doğru olan ilk mesajı döndürür (uykusuz: 50 Hz tele kuyruğunu geriden takip etmez)."""
    bitis = time.time() + sn
    while time.time() < bitis:
        m = json.loads(ws.receive_text())
        if kosul(m):
            return m
    return None


def udp_al(sk, beklenen, port):
    """GCS soketinden beklenen ham baytı alır; sahte otopilotun 1 Hz MAVLink HEARTBEAT paketlerini (msgid 0) atlar."""
    bitis = time.time() + 3
    hb = 0
    while time.time() < bitis:
        data, addr = sk.recvfrom(4096)
        assert addr[1] == port, addr
        if data[:1] == b'\xfd' and len(data) == 21 and data[7:10] == b'\x00\x00\x00':
            hb += 1
            continue
        return data, hb
    raise AssertionError(f'{beklenen!r} gelmedi')


def close_code(ws):
    try:
        ws.receive_text()
    except WebSocketDisconnect as e:
        return e.code
    return None


class SahteSitl:
    """Sahte "SITL" SERIAL0: TCP dinler, gelen baytları biriktirir, istenirse istemciye bayt yazar."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.baglar = []          # açık istemci bağlantıları (kapanan oturumunki listeden düşer)
        self.alinan = bytearray()
        self.kilit = threading.Lock()
        threading.Thread(target=self._kabul, daemon=True).start()

    def _kabul(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with self.kilit:
                self.baglar.append(c)
            threading.Thread(target=self._oku, args=(c,), daemon=True).start()

    def _oku(self, c):
        while True:
            try:
                d = c.recv(4096)
            except OSError:
                d = b''
            if not d:
                with self.kilit:
                    if c in self.baglar:
                        self.baglar.remove(c)
                return
            with self.kilit:
                self.alinan += d

    def yaz(self, data):
        with self.kilit:
            baglar = list(self.baglar)
        assert len(baglar) == 1, f'tek canlı SITL bağlantısı beklenir: {len(baglar)}'
        baglar[0].sendall(data)

    def kapat(self):
        try:
            self.srv.close()
        except OSError:
            pass


def tlog_yaz(yol, lat0=39.925, lon0=32.837, alt0=900.0, sure=60.0):
    """pymavlink ile küçük bir .tlog (8 bayt big-endian µs zaman damgası + MAVLink2 çerçevesi): 10 sn yerde (disarmed), ARM, 40 sn daire
    uçuşu (STABILIZE → LOITER), iniş, DISARM. Döner: (ilk ARM zamanı, ARM anındaki konum)."""
    from pymavlink.dialects.v20 import ardupilotmega as D
    mav = D.MAVLink(None, srcSystem=1, srcComponent=1)
    t_abs = 1_700_000_000.0
    arm_t, arm_pos = None, None
    with open(yol, 'wb') as f:
        def yaz(msg, t):
            f.write(struct.pack('>Q', int(t * 1e6)))
            f.write(msg.pack(mav))
            mav.seq = (mav.seq + 1) % 256
        t = 0.0
        while t <= sure:
            armed = 10.0 <= t < 55.0
            if armed and arm_t is None:
                arm_t = t
            mode = 5 if (armed and t >= 20) else 0   # ArduCopter LOITER=5 · STABILIZE=0
            if 15 <= t < 50 and armed:   # 10–15 dikey tırmanış (yerinde), sonra 100 m yarıçaplı daire
                ang = (t - 15) / 35 * 2 * math.pi
                r = 100.0
                lat, lon, z = lat0 + r * math.cos(ang) / 110574, lon0 + r * math.sin(ang) / (111320 * math.cos(math.radians(lat0))), 30.0
                vn, ve = -r * 2 * math.pi / 35 * math.sin(ang), r * 2 * math.pi / 35 * math.cos(ang)
            else:
                lat, lon, z, vn, ve = lat0, lon0, (30.0 * min(1, (t - 10) / 5) if armed and t < 50 else 0.0), 0.0, 0.0
            if armed and arm_pos is None:
                arm_pos = (lat, lon)
            yaw = math.atan2(ve, vn) if (vn or ve) else 0.0
            if abs(t - round(t)) < 1e-6:   # 1 Hz
                yaz(mav.heartbeat_encode(2, 3, (128 if armed else 0) | 1, mode, 4), t_abs + t)   # MAV_TYPE_QUADROTOR, ARDUPILOTMEGA; CUSTOM_MODE bayrağı
                yaz(mav.sys_status_encode(0, 0, 0, 500, 16200 - int(t * 10), 1200, 95 - int(t // 10), 0, 0, 0, 0, 0, 0), t_abs + t)
                yaz(mav.gps_raw_int_encode(int((t_abs + t) * 1e6), 3, int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), 120, 80, 0, 0, 12), t_abs + t)
                if t == 0:
                    yaz(mav.statustext_encode(6, b'ArduCopter V4.5.7 (test)'), t_abs + t)
                if t == 10:
                    yaz(mav.statustext_encode(6, b'Arming motors'), t_abs + t)
                if t == 30:
                    yaz(mav.statustext_encode(4, b'Low battery warning (test)'), t_abs + t)
            yaz(mav.global_position_int_encode(int(t * 1000), int(lat * 1e7), int(lon * 1e7), int((alt0 + z) * 1000), int(z * 1000),
                                               int(vn * 100), int(ve * 100), 0, int((math.degrees(yaw) % 360) * 100)), t_abs + t)
            yaz(mav.attitude_encode(int(t * 1000), 0.1 if armed else 0.0, -0.05 if armed else 0.0, yaw, 0, 0, 0), t_abs + t)
            yaz(mav.rc_channels_encode(int(t * 1000), 8, 1500, 1500, 1600 if armed else 1000, 1500, 1800, 1000, 1000, 1500, *([0] * 10), 200), t_abs + t)
            # servo ÇIKIŞI (3B kontrol yüzeyleri; §8 servo alanı): armed'da aileron +120 µs, gaz 1600, flap kanalı (SERVO5) t ≥ 50'de 1900 (iniş flapı)
            yaz(mav.servo_output_raw_encode(int(t * 1000), 0, 1620 if armed else 1500, 1480, 1600 if armed else 1000, 1500, 1900 if (armed and t >= 50) else 1100, 1100, 0, 0), t_abs + t)
            if t == 0:
                yaz(mav.param_value_encode(b'SERVO5_FUNCTION', 3.0, 9, 1000, 5), t_abs + t)   # servo_fn[4] = 3 (flap_auto)
                yaz(mav.param_value_encode(b'SERVO12_FUNCTION', 4.0, 9, 1000, 12), t_abs + t)   # 8 kanal dışı: yoksayılır
            yaz(mav.vfr_hud_encode(math.hypot(vn, ve) + 1, math.hypot(vn, ve), int(math.degrees(yaw) % 360), 55 if armed else 0, alt0 + z, 0.0), t_abs + t)
            t = round(t + 0.2, 3)   # 5 Hz
    return arm_t, arm_pos


def replay_testleri(a, c1, mon_token_login):
    """§8: ayrıştırıcı birim testi (.tlog) + /logs yetki kesişimi + replay oturumu + gzip kare ucu + WS (tele yok, cmd yalnız reset)."""
    import gzip
    from app import config, flightsim_replay as R
    yol = config.UPLOAD_DIR / 'flightlogs'
    yol.mkdir(parents=True, exist_ok=True)
    tl = yol / 'test-kayit.tlog'
    arm_t, arm_pos = tlog_yaz(tl)
    # --- ayrıştırıcı ---
    d = R.ayristir(tl)
    assert d['hz'] == R.REPLAY_HZ and d['fields'] == R.FIELDS and d['source'] == 'tlog' and d['type'] == 'multirotor' and d['vehicle'] == 'ArduCopter', (d['hz'], d['type'], d['vehicle'])
    assert 55 <= d['duration_s'] <= 60.5 and 5 * 55 <= d['n'] <= R.REPLAY_HZ * 61, (d['duration_s'], d['n'])   # 5 Hz kaynak → en çok 5 kare/sn tutulur
    assert abs(d['takeoff_t'] - arm_t) < 0.3 and abs(d['home']['lat'] - arm_pos[0]) < 1e-6 and abs(d['home']['lon'] - arm_pos[1]) < 1e-6 and abs(d['home']['alt'] - 900) < 0.01, (d['takeoff_t'], d['home'])
    assert d['modes'] == ['STABILIZE', 'LOITER'], d['modes']
    metinler = [e['text'] for e in d['events']]
    assert 'Mod: STABILIZE' in metinler and 'Mod: LOITER' in metinler and 'ARM — motorlar kuruldu' in metinler and 'DISARM — motorlar devre dışı' in metinler and 'Arming motors' in metinler, metinler
    uyari = next(e for e in d['events'] if 'Low battery' in e['text'])
    assert uyari['sev'] == 4 and 29.9 <= uyari['t'] <= 30.1, uyari
    FI = {k: i for i, k in enumerate(d['fields'])}
    assert d['frames'][0][FI['rc']] is None   # ilk konum karesi RC'den önce (sample-and-hold: henüz bilinmeyen alan None)
    k0, k30 = next(f for f in d['frames'] if f[FI['rc']]), next(f for f in d['frames'] if f[FI['t']] >= 30)
    assert k0[FI['armed']] == 0 and k0[FI['alt_rel']] == 0 and k0[FI['rc']][2] == 1000 and k0[FI['sats']] == 12 and k0[FI['fix']] == 3, k0
    assert k30[FI['armed']] == 1 and 29 <= k30[FI['alt_rel']] <= 31 and k30[FI['mode']] == 1 and k30[FI['rc']][2] == 1600 and 17 <= k30[FI['gs']] <= 18.5 and k30[FI['thr']] == 55, k30
    # §8 servo alanı (önbellek v3): SERVO_OUTPUT_RAW → servo[8]; SERVOn_FUNCTION → servo_fn (yalnız 1…8)
    assert R.ONBELLEK_SURUM >= 3 and 'servo' in FI and d['servo_fn'] == [None, None, None, None, 3, None, None, None], d['servo_fn']
    assert k0[FI['servo']] == [1500, 1480, 1000, 1500, 1100, 1100, 0, 0] and k30[FI['servo']] == [1620, 1480, 1600, 1500, 1100, 1100, 0, 0], (k0[FI['servo']], k30[FI['servo']])
    k52 = next(f for f in d['frames'] if f[FI['t']] >= 52)
    assert k52[FI['servo']][4] == 1900, k52[FI['servo']]   # iniş flapı
    # eski sürüm önbelleği yeniden üretilir
    eski = R.onbellek_yolu(777001)
    with gzip.open(eski, 'wt', encoding='utf-8') as f:
        json.dump({**d, 'v': 2}, f)
    try:
        R.onbellek_meta(eski)
        raise AssertionError('eski önbellek kabul edildi')
    except ValueError:
        pass
    assert R.hazirla(777001, tl)['v'] == R.ONBELLEK_SURUM and R.onbellek_meta(eski)['v'] == R.ONBELLEK_SURUM
    eski.unlink()
    assert d['start_utc'].startswith('2023-11-14T22:13:20'), d['start_utc']
    # --- flight_logs kaydı (analiz TAMAM) ---
    from app import db
    with db.connect() as conn:
        cur = conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, analysis, aircraft, pilot, location, uploaded_by, uploaded_at)
                              VALUES (NULL, ?, ?, ?, 'TAMAM', ?, 'CZ-TEST', 'Test Pilot', 'Akyurt', 1, ?)''',
                           ('flightlogs/test-kayit.tlog', 'test-kayit.tlog', tl.stat().st_size,
                            json.dumps({'summary': {'vehicle': 'ArduCopter', 'flight_s': 40, 'duration_s': 60, 'home': {'lat': 39.925, 'lng': 32.837}}}), db.now()))
        lid = cur.lastrowid
        conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, uploaded_by, uploaded_at) VALUES (NULL, 'flightlogs/yarim.bin', 'yarim.bin', 10, 'ISLENIYOR', 1, ?)''', (db.now(),))
        conn.commit()
    # --- /logs: §8.5 varsayılan liste YALNIZ simülatör kayıtları — bağımsız gerçek log (Araçlar) listelenmez; `?id=` ("Simüle et") o logu verir
    #     (admin tools yetkili); analizi bitmemiş listelenmez; arama ---
    m = ok(a.get('/api/drone/sim/meta'))
    assert m['replay']['logs_allowed'] is True and m['replay']['real_allowed'] is True and m['replay']['hz'] == R.REPLAY_HZ and '.tlog' in m['replay']['formats'], m['replay']
    assert ok(a.get('/api/drone/sim/logs')) == [], 'gerçek log simülatör listesinde görünmemeli (§8.5)'
    logs = ok(a.get('/api/drone/sim/logs', params={'id': lid}))
    assert [l['id'] for l in logs] == [lid] and logs[0]['ext'] == 'tlog' and logs[0]['type'] == 'multirotor' and logs[0]['cached'] is False and logs[0]['aircraft'] == 'CZ-TEST' and logs[0]['sim'] is False, logs
    assert ok(a.get('/api/drone/sim/logs', params={'id': lid, 'q': 'cz-test'})) and ok(a.get('/api/drone/sim/logs', params={'id': lid, 'q': 'yokboyle'})) == []
    assert ok(a.get('/api/drone/sim/logs', params={'id': lid + 1})) == []   # ISLENIYOR
    # montaj: drone.sim var; Araçlar (tools) rolden kapatılır, Saha (field) zaten yok → log listesi boş, oturum açamaz (yazma yok → 403)
    ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'}, json={'changes': [{'node': 'tools', 'cap': 'open', 'value': False}]}))
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    assert not ({'tools', 'field'} & set(ok(mon.get('/api/auth/me'))['modules'])), ok(mon.get('/api/auth/me'))['modules']
    mm_ = ok(mon.get('/api/drone/sim/meta'))['replay']
    assert mm_['logs_allowed'] is True and mm_['real_allowed'] is False and ok(mon.get('/api/drone/sim/logs')) == [] and ok(mon.get('/api/drone/sim/logs', params={'id': lid})) == [], mm_
    assert mon.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}).status_code == 403
    # --- oturum: doğrulama ---
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay'}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': 99999}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid + 1}).status_code == 400   # ISLENIYOR
    assert a.post('/api/drone/sim/sessions', json={'mode': 'ucur', 'log_id': lid}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'sitl'}).status_code == 400   # type/center_id yok
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'time': 'gece'}}).status_code == 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'launch': {'method': 'mancinik'}}}).status_code == 400   # §13 kayıtta da doğrulanır
    # görsel model (§12): kayıt kipinde de kütüphaneden seçilir; log tipi (multirotor) ile uyumsuz model 400
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'model': {'id': 'builtin:caymaz'}}).status_code == 400
    s = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'seed': 3, 'time': 'night', 'launch': {'method': 'ramp', 'angle_deg': 20}}, 'model': 'builtin:quad'}), 201)
    assert s['mode'] == 'replay' and s['udp_port'] is None and s['type'] == 'multirotor' and s['replay']['log_id'] == lid and s['replay']['file_name'] == 'test-kayit.tlog', s
    # §8/§13: kalkış yöntemi kayıt oturumunda kabul edilir (world.launch) ve session.launch döner; log kopter → yöntem wheels'a normalize, phase hep None
    assert s['world']['launch'] == {'method': 'ramp', 'angle_deg': 20.0, 'release_kmh': 70} and s['launch'] == {'method': 'wheels', 'angle_deg': 20.0, 'release_kmh': 70, 'phase': None}, (s['world']['launch'], s['launch'])
    assert R.ReplaySession.__init__ and flightsim.launch_normalize('sabit_kanat', s['world']['launch'])['method'] == 'ramp'   # ArduPlane logunda rampa korunur
    assert s['model']['id'] == 'builtin:quad' and s['model']['source'] == 'builtin' and s['model']['ready'] is True, s['model']
    assert s['world']['time'] == 'night' and s['gcs'] == {'connected': False, 'addr': None, 'since': None} and s['state'] in ('BASLIYOR', 'HAZIR'), s
    # §8 kök neden: merkez (kalkış noktası) ayrıştırma bitmeden de analiz özetinden bilinir → ön yüz dünyayı (0,0)'da kurmaz
    assert s['center']['lat'] == 39.925 and s['center']['lon'] == 32.837 and s['center']['name'] == 'test-kayit.tlog', s['center']
    sid = s['id']
    g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f'/api/drone/sim/sessions/{sid}'))), 10)
    assert g and g['replay']['frames'] == d['n'] and g['replay']['duration_s'] == d['duration_s'] and g['replay']['home'] == d['home'] and g['replay']['progress'] == 100, g and g['replay']
    assert g['center']['lat'] == d['home']['lat'] and g['center']['alt'] == d['home']['alt'] and g['replay']['modes'] == ['STABILIZE', 'LOITER'] and g['replay']['takeoff_t'] == d['takeoff_t'], g['center']
    assert R.onbellek_yolu(lid).exists() and ok(a.get('/api/drone/sim/logs', params={'id': lid}))[0]['cached'] is True
    # --- kareler (gzip JSON) ---
    r = a.get(f'/api/drone/sim/sessions/{sid}/replay')
    assert r.status_code == 200 and r.headers.get('content-type', '').startswith('application/json'), (r.status_code, r.headers)
    body = r.json()   # httpx Content-Encoding: gzip açar
    assert body['v'] == R.ONBELLEK_SURUM and body['n'] == d['n'] and len(body['frames']) == d['n'] and body['fields'] == R.FIELDS and body['home'] == d['home'] and len(body['events']) == len(d['events']), (body['n'], len(body['frames']))
    with gzip.open(R.onbellek_yolu(lid), 'rt', encoding='utf-8') as f:
        assert json.load(f)['n'] == d['n']
    # --- komutlar: yalnız reset; SITL komutları 400 ---
    assert a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm'}).status_code == 400
    assert a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'rc', 'params': {'ch': [1500] * 8}}).status_code == 400
    ok(a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'reset'}))
    # --- WS: hello (mode replay) · tele gelmez · cmd reset → res ok + replay reset yayını · cmd arm → ok:false ---
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hh = json.loads(ws.receive_text())
        assert hh['t'] == 'hello' and hh['session']['mode'] == 'replay' and hh['session']['state'] == 'HAZIR' and hh['session']['replay']['frames'] == d['n'] and hh['session']['launch']['phase'] is None, hh
        ws.send_text(json.dumps({'t': 'rc', 'ch': [1500] * 8}))
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'r1'}))
        gor = {}
        bitis = time.time() + 3
        while time.time() < bitis and not ({'res', 'replay'} <= set(gor)):
            mm = json.loads(ws.receive_text())
            assert mm['t'] != 'tele', 'kayıt oturumunda tele yayını olmamalı'
            gor[mm['t']] = mm
        assert gor['res']['ok'] is True and gor['res']['rid'] == 'r1' and gor['replay']['action'] == 'reset', gor
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'arm', 'rid': 'r2'}))
        mm = bekle(lambda: (lambda x: x if x['t'] == 'res' and x.get('rid') == 'r2' else None)(json.loads(ws.receive_text())), 3)
        assert mm and mm['ok'] is False and 'reset' in mm['error'], mm
        # kapat → end
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        mm = bekle(lambda: (lambda x: x if x['t'] == 'end' else None)(json.loads(ws.receive_text())), 3)
        assert mm and mm['reason'] == 'kapatildi', mm
    assert a.get(f'/api/drone/sim/sessions/{sid}/replay').status_code == 404
    # SITL oturumunda /replay 400; önbellekli ikinci açılış anında HAZIR
    s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s2['mode'] == 'sitl' and a.get(f"/api/drone/sim/sessions/{s2['id']}/replay").status_code == 400
    s3 = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid, 'world': {'mode': 'real', 'size_m': 3000}}), 201)   # gerçek arazi kipi kayıtta da kabul edilir
    assert s3['world']['mode'] == 'real' and s3['center']['lat'] == 39.925, s3
    g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f"/api/drone/sim/sessions/{s3['id']}"))), 5)
    assert g and g['replay']['frames'] == d['n'] and g['center']['lat'] == d['home']['lat'] and g['center']['alt'] == d['home']['alt']
    assert a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': lid}).status_code == 409   # limit sayımına dahil
    ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}")); ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
    # bozuk dosya → HATA (sitl.error), /replay 409
    bozuk = yol / 'bozuk.bin'
    bozuk.write_bytes(b'\x00' * 64)
    with db.connect() as conn:
        cur = conn.execute('''INSERT INTO flight_logs (task_id, file, file_name, size, status, analysis, uploaded_by, uploaded_at) VALUES (NULL, 'flightlogs/bozuk.bin', 'bozuk.bin', 64, 'TAMAM', '{}', 1, ?)''', (db.now(),))
        bid = cur.lastrowid
        conn.commit()
    s4 = ok(a.post('/api/drone/sim/sessions', json={'mode': 'replay', 'log_id': bid}), 201)
    g = bekle(lambda: (lambda r: r if r['state'] in ('HATA', 'HAZIR') else None)(ok(a.get(f"/api/drone/sim/sessions/{s4['id']}"))), 10)
    assert g and g['state'] == 'HATA' and g['sitl']['error'], g
    assert a.get(f"/api/drone/sim/sessions/{s4['id']}/replay").status_code == 409
    ok(a.delete(f"/api/drone/sim/sessions/{s4['id']}"))
    oynatma_girisleri_testleri(a, mon, tl)   # §8.5 simülatör listesi süzgeci + kaydı doğrudan izleme
    # log silinince önbellek de silinir
    ok(a.delete(f'/api/tools/flight-logs/{lid}'))
    assert not R.onbellek_yolu(lid).exists()
    print('Kayıttan oynatma testleri geçti.')


def oynatma_girisleri_testleri(a, mon, tl):
    """§8.5 (kullanıcı isteği): (1) simülatörün log listesi YALNIZ simülatör kayıtları — saha görevine (task_id) ya da saha uçuşuna (flight_id)
    bağlı loglar ve bağımsız gerçek loglar listelenmez; `?id=` "Simüle et" girişi; simülatör kaydına drone.sim erişimi yeter.
    (2) POST /runs/{id}/replay: sihirbazsız, kaydın ayarlarıyla (dünya/hava/rüzgâr/saat/sis, kalkış rampa açı-yön, model, kamera) oturum;
    yetki (okuma izni 403), log yok 409, bulunamadı 404; Google 3B artık kapalıysa gerçek araziye düşer."""
    import shutil
    from app import config, db, flightsim_runs
    hedef = config.UPLOAD_DIR / 'flightlogs' / 'sim-kayit.tlog'
    shutil.copy(tl, hedef)
    ozet = json.dumps({'summary': {'vehicle': 'ArduCopter', 'flight_s': 40, 'duration_s': 60, 'home': {'lat': 39.925, 'lng': 32.837}}})
    with db.connect() as conn:
        ins = lambda ad, origin, task_id=None, flight_id=None: conn.execute(   # noqa: E731
            '''INSERT INTO flight_logs (task_id, flight_id, file, file_name, size, status, analysis, aircraft, uploaded_by, uploaded_at, origin)
               VALUES (?, ?, 'flightlogs/sim-kayit.tlog', ?, ?, 'TAMAM', ?, 'Simülatör · Multikopter', 1, ?, ?)''', (task_id, flight_id, ad, hedef.stat().st_size, ozet, db.now(), origin)).lastrowid
        tid = conn.execute("INSERT INTO field_tasks (code, created_at) VALUES ('SG-SIMTEST', ?)", (db.now(),)).lastrowid
        fid = conn.execute('INSERT INTO field_flights (task_id) VALUES (?)', (tid,)).lastrowid
        sim_id = ins('SIM-9-20261021-1000.bin.tlog', 'SIM')                  # simülatör kaydı (görevsiz)
        gorev_id = ins('gorev-ucus.tlog', 'REAL', task_id=tid)                 # saha görevi logu
        ucus_id = ins('saha-ucus-sim.tlog', 'SIM', task_id=tid, flight_id=fid)   # saha uçuşuna bağlı (kaynak SIM olsa da)
        nul_id = ins('kosu.tlog', None)                                         # kaynağı okunamamış ama bir simülasyon kaydının .bin'i
        w = {'mode': 'google3d', 'time': 'dusk', 'weather': 'rain', 'wind_ms': 7.0, 'wind_dir': 200.0, 'fog': 0.3, 'seed': 42, 'size_m': 3000,
             'runway_heading': 120.0, 'launch': {'method': 'ramp', 'angle_deg': 22, 'azimuth_deg': 135, 'phase': 'ARM'}}
        run = lambda bin_id, world, camera='thermal', model='builtin:quad', owner=1: conn.execute(   # noqa: E731
            '''INSERT INTO drone_sim_runs (session_id, owner_id, owner_name, type, model_id, world, launch, camera, started_at, mode, result, bin_log_id, created_at)
               VALUES (900, ?, 'Yönetici', 'multirotor', ?, ?, ?, ?, ?, 'sitl', 'tamam', ?, ?)''',
            (owner, model, json.dumps(world) if world is not None else None, json.dumps({'method': 'ramp', 'angle_deg': 18, 'phase': None}), camera, db.now(), bin_id, db.now())).lastrowid
        rid = run(sim_id, w)
        rid_nul = run(nul_id, None, camera=None, model=None)   # eski satır: dünya yok → varsayılan + launch sütunu
        rid_yok = run(None, {'mode': 'procedural'})            # .bin kaydı kapalıydı
        conn.commit()
    # (1) liste süzgeci
    ids = [l['id'] for l in ok(a.get('/api/drone/sim/logs'))]
    assert sim_id in ids and nul_id in ids and gorev_id not in ids and ucus_id not in ids, (ids, sim_id, nul_id, gorev_id, ucus_id)
    assert all(l['sim'] for l in ok(a.get('/api/drone/sim/logs'))), 'liste yalnız simülatör kayıtları'
    assert [l['id'] for l in ok(a.get('/api/drone/sim/logs', params={'id': gorev_id}))] == [gorev_id]   # "Simüle et" girişi: saha logu (tools yetkisi)
    mids = [l['id'] for l in ok(mon.get('/api/drone/sim/logs'))]   # montaj: flightlogs yetkisi yok ama simülatör kayıtlarını görür
    assert sim_id in mids and gorev_id not in mids and ok(mon.get('/api/drone/sim/logs', params={'id': gorev_id})) == [], mids
    # (2) kaydı doğrudan izle
    RR = '/api/drone/sim/runs'
    assert a.post(f'{RR}/999999/replay').status_code == 404
    assert a.post(f'{RR}/{rid_yok}/replay').status_code == 409
    assert mon.post(f'{RR}/{rid}/replay').status_code == 403   # okuma izni (yazma yok) → oturum açamaz
    r = ok(a.get(f'{RR}/{rid}'))
    assert r['play_log_id'] == sim_id, r
    ayar = flightsim_runs.oynatma_ayarlari(r)
    beklenen_kip = 'google3d' if flightsim.google3d_etkin() else 'real'   # Google 3B anahtarı yoksa gerçek araziye düşer (ortama bağlı)
    assert ayar['world']['mode'] == beklenen_kip and ayar['world']['time'] == 'dusk' and ayar['camera'] == 'thermal' and ayar['model'] == {'id': 'builtin:quad'}, ayar
    assert ayar['world']['launch']['method'] == 'ramp' and ayar['world']['launch']['angle_deg'] == 22 and ayar['world']['launch']['azimuth_deg'] == 135, ayar['world']['launch']
    s = ok(a.post(f'{RR}/{rid}/replay'), 201)
    assert s['mode'] == 'replay' and s['run_id'] == rid and s['replay']['log_id'] == sim_id, s
    W = s['world']
    assert (W['mode'], W['time'], W['weather'], W['wind_ms'], W['wind_dir'], W['fog'], W['seed'], W['size_m'], W['runway_heading']) == (beklenen_kip, 'dusk', 'rain', 7.0, 200.0, 0.3, 42, 3000, 120.0), W
    assert W['launch']['method'] == 'ramp' and W['launch']['angle_deg'] == 22 and W['launch']['azimuth_deg'] == 135, W['launch']   # kayıttaki rampa yön/açı
    assert s['camera'] == 'thermal' and s['model']['id'] == 'builtin:quad', (s['camera'], s['model'])
    g = bekle(lambda: (lambda x: x if x['state'] == 'HAZIR' else None)(ok(a.get(f"/api/drone/sim/sessions/{s['id']}"))), 10)
    assert g and g['replay']['frames'], g
    ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
    s2 = ok(a.post(f'{RR}/{rid_nul}/replay'), 201)   # eski satır: dünya yok → varsayılan dünya + launch sütunundaki rampa (phase atılır)
    assert s2['world']['launch']['method'] == 'ramp' and s2['world']['launch']['angle_deg'] == 18 and s2['world']['mode'] == flightsim.WORLD_DEFAULTS['mode'] and s2['camera'] == 'day', s2['world']
    ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
    with db.connect() as conn:
        conn.execute('DELETE FROM drone_sim_runs WHERE id IN (?, ?, ?)', (rid, rid_nul, rid_yok))
        conn.execute('DELETE FROM drone_sim_runs WHERE source_log_id IN (?, ?)', (sim_id, nul_id))
        conn.execute('DELETE FROM flight_logs WHERE id IN (?, ?, ?, ?)', (sim_id, gorev_id, ucus_id, nul_id))
        conn.execute('DELETE FROM field_flights WHERE id = ?', (fid,))
        conn.execute('DELETE FROM field_tasks WHERE id = ?', (tid,))
        conn.commit()
    print('  §8.5 kayıttan oynatma girişleri (liste süzgeci + kaydı doğrudan izle) testleri geçti')


def kucuk_glb():
    """Geçerli GLB zarfı: 12 bayt başlık + JSON parçası (asset 2.0, boş sahne). Sunucu yalnız başlık/boyut denetler."""
    js = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0}).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    toplam = 12 + 8 + len(js)
    return struct.pack('<III', 0x46546C67, 2, toplam) + struct.pack('<II', len(js), 0x4E4F534A) + js


def kucuk_png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (320, 240), (40, 60, 90)).save(buf, 'PNG')
    return buf.getvalue()


def model_testleri(a, mon, c1):
    """§12 görsel model kütüphanesi: dahili liste, yükleme (GLB/STEP), GLB/thumb PUT-GET, yönelim, yetki, oturumda model doğrulama, geriye uyumlu airframe."""
    from app import config, flightsim_models as FM
    M = '/api/drone/sim/models'
    # --- liste: dahili modeller her tip için; type filtresi; VTOL adı ---
    r = ok(a.get(M))
    assert r['can_write'] is True and r['design_allowed'] is True and r['limits']['max_bytes'] == 50 * 1024 * 1024
    ids = [m['id'] for m in r['models']]
    assert ids.count('builtin:caymaz') == 2 and ids.count('builtin:quad') == 1 and all(m['source'] == 'builtin' for m in r['models']), ids
    sk = ok(a.get(M, params={'type': 'sabit_kanat'}))['models']
    assert [m['id'] for m in sk] == ['builtin:caymaz', 'builtin:delta', 'builtin:talon'] and sk[0]['name'] == 'Caymaz V3' and sk[0]['glb_url'] == '/static/models/caymaz-sim.glb' and sk[0]['ready'] is True, sk
    assert sk[0]['thumb_url'] is None and sk[0]['has_prop'] is True and sk[0]['size'] and sk[0]['format'] == 'glb' and sk[1]['format'] == 'procedural'
    vt = ok(a.get(M, params={'type': 'vtol'}))['models']
    assert [m['name'] for m in vt] == ['VTOL-Caymaz V3', 'VTOL-Delta kanat'], [m['name'] for m in vt]
    assert ok(a.get(M, params={'type': 'multirotor'}))['models'][0]['name'] == 'Quad'
    assert a.get(M, params={'type': 'ucan_hali'}).status_code == 400
    assert ok(a.get(f'{M}/builtin:heli'))['type'] == 'helikopter' and a.get(f'{M}/builtin:yok').status_code == 404 and a.get(f'{M}/../x').status_code in (404, 400)
    assert ok(a.get(f'{M}/design-files')) == []   # admin design modülünde; henüz sürüm yok
    assert mon.get(f'{M}/design-files').status_code == 403   # Montaj: design yok
    # --- yükleme: GLB (hazır), STEP (dönüşüm bekler), geçersiz uzantı, boş ---
    glb = kucuk_glb()
    m1 = ok(a.post(M, files={'file': ('ucak.glb', glb, 'model/gltf-binary')}, data={'type': 'sabit_kanat', 'name': 'Test Uçak'}), 201)
    assert m1['source'] == 'upload' and m1['name'] == 'Test Uçak' and m1['type'] == 'sabit_kanat' and m1['ready'] is True and m1['format'] == 'glb', m1
    assert m1['glb_url'] == f"{M}/{m1['id']}/glb" and m1['file_url'] == f"{M}/{m1['id']}/file" and m1['thumb_url'] is None and m1['size'] == len(glb)
    assert m1['orient'] == {'forward': '+z', 'up': '+y', 'scale': 1.0, 'offset': [0.0, 0.0, 0.0], 'prop': {'mode': 'none', 'pos': [0.0, 0.0, 0.0], 'r': 0.3}}, m1['orient']
    assert (config.DATA_DIR / 'sim_models' / m1['id'] / 'orijinal.glb').read_bytes() == glb and (config.DATA_DIR / 'sim_models' / m1['id'] / 'model.glb').exists()
    g = a.get(m1['glb_url'])
    assert g.status_code == 200 and g.content == glb and g.headers['content-type'].startswith('model/gltf-binary')
    m2 = ok(a.post(M, files={'file': ('govde.STEP', b'ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n', 'application/octet-stream')}, data={'type': 'multirotor'}), 201)
    assert m2['ready'] is False and m2['glb_url'] is None and m2['format'] == 'step' and m2['name'] == 'govde' and m2['orient']['forward'] == '+y' and m2['orient']['up'] == '+z', m2
    assert a.get(m2['file_url']).content.startswith(b'ISO-10303-21') and a.get(f"{M}/{m2['id']}/glb").status_code == 404
    assert a.post(M, files={'file': ('x.txt', b'abc', 'text/plain')}, data={'type': 'multirotor'}).status_code == 400
    assert a.post(M, files={'file': ('x.obj', b'', 'text/plain')}, data={'type': 'multirotor'}).status_code == 400
    assert a.post(M, files={'file': ('x.obj', b'v 0 0 0', 'text/plain')}, data={'type': 'ucan_hali'}).status_code == 400
    # --- GLB PUT (tarayıcı dönüşümü): geçersiz başlık 400; geçerli → ready ---
    assert a.put(f"{M}/{m2['id']}/glb", content=b'NOT-GLB-AT-ALL-REALLY-NOT', headers={'content-type': 'application/octet-stream'}).status_code == 400
    m2b = ok(a.put(f"{M}/{m2['id']}/glb", content=glb, headers={'content-type': 'application/octet-stream'}))
    assert m2b['ready'] is True and a.get(m2b['glb_url']).content == glb
    assert a.put(f"{M}/builtin:caymaz/glb", content=glb).status_code == 400   # dahili modele GLB yazılamaz
    assert a.put(f"{M}/{m2['id']}/glb", content=b'x', headers={'content-length': str(60 * 1024 * 1024)}).status_code == 413
    # --- küçük resim: PNG dışı 400; model + dahili (VTOL varyantı ayrı) ---
    png = kucuk_png()
    assert a.put(f"{M}/{m1['id']}/thumb", content=b'GIF89a', headers={'content-type': 'image/gif'}).status_code == 400
    m1t = ok(a.put(f"{M}/{m1['id']}/thumb", content=png, headers={'content-type': 'image/png'}))
    assert m1t['thumb_url'] == f"{M}/{m1['id']}/thumb"
    t = a.get(m1t['thumb_url'])
    assert t.status_code == 200 and t.content == png and t.headers['content-type'] == 'image/png'
    assert a.get(f'{M}/builtin:caymaz/thumb', params={'type': 'vtol'}).status_code == 404
    bt = ok(a.put(f'{M}/builtin:caymaz/thumb', params={'type': 'vtol'}, content=png, headers={'content-type': 'image/png'}))
    assert bt['thumb_url'] == f'{M}/builtin:caymaz/thumb?type=vtol' and bt['name'] == 'VTOL-Caymaz V3'
    assert a.get(f'{M}/builtin:caymaz/thumb', params={'type': 'vtol'}).status_code == 200 and a.get(f'{M}/builtin:caymaz/thumb', params={'type': 'sabit_kanat'}).status_code == 404
    assert (config.DATA_DIR / 'sim_models' / 'builtin' / 'caymaz-vtol.png').read_bytes() == png
    assert next(m for m in ok(a.get(M, params={'type': 'vtol'}))['models'] if m['id'] == 'builtin:caymaz')['thumb_url'] == f'{M}/builtin:caymaz/thumb?type=vtol'
    assert a.put(f'{M}/builtin:yok/thumb', content=png).status_code == 404
    # --- yönelim / ad / tip güncelleme ---
    m1o = ok(a.put(f"{M}/{m1['id']}", json={'orient': {'forward': '-x', 'up': '+z', 'scale': 0.001, 'offset': [0, 0.1, 0], 'prop': {'mode': 'tail', 'r': 0.4}}, 'has_prop': False, 'name': ' Uçak 2 '}))
    assert m1o['orient'] == {'forward': '-x', 'up': '+z', 'scale': 0.001, 'offset': [0.0, 0.1, 0.0], 'prop': {'mode': 'tail', 'pos': [0.0, 0.0, 0.0], 'r': 0.4}} and m1o['has_prop'] is False and m1o['name'] == 'Uçak 2', m1o
    assert a.put(f"{M}/{m1['id']}", json={'orient': {'forward': '+z', 'up': '-z'}}).status_code == 400   # aynı eksen
    assert a.put(f"{M}/{m1['id']}", json={'orient': {'forward': 'ileri'}}).status_code == 400
    assert a.put(f"{M}/{m1['id']}", json={'orient': {'scale': 0}}).status_code == 400
    assert a.put(f"{M}/{m1['id']}", json={'orient': {'prop': {'mode': 'yan'}}}).status_code == 400
    assert a.put(f"{M}/{m1['id']}", json={'type': 'ucan_hali'}).status_code == 400
    assert a.put(f'{M}/builtin:caymaz', json={'name': 'x'}).status_code == 400 and a.put(f'{M}/99999', json={'name': 'x'}).status_code == 404
    assert FM.orient_dogrula(None) == FM.ORIENT_VARSAYILAN and FM.kimlik_coz('builtin:caymaz') == ('builtin', 'caymaz') and FM.kimlik_coz('12') == ('db', 12)
    assert FM.kimlik_coz('builtin:../x') is None and FM.kimlik_coz('-1') is None and FM.kimlik_coz('') is None and FM.kimlik_coz('12/thumb') is None
    # --- oturumda model: bilinmeyen 400, tip uyumsuz 400, hazır olmayan 400, kütüphane modeli 201 (model + airframe None), eski airframe → model ---
    S = '/api/drone/sim/sessions'
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': {'id': '99999'}}).status_code == 400
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': 'builtin:quad'}).status_code == 400          # kopter modeli uçakta
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': {'id': 'builtin:../x'}}).status_code == 400
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': {'id': m1['id'], 'orient': {'forward': '+z', 'up': '+z'}}}).status_code == 400
    m3 = ok(a.post(M, files={'file': ('bekleyen.stp', b'ISO-10303-21;', 'application/octet-stream')}, data={'type': 'sabit_kanat'}), 201)
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': m3['id']}).status_code == 400                 # GLB'si yok (ready=false)
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': {'id': m1['id'], 'orient': {'forward': '+x', 'up': '+z', 'scale': 2}}}), 201)
    assert s['model']['id'] == m1['id'] and s['model']['source'] == 'upload' and s['model']['glb_url'] == m1['glb_url'] and s['airframe'] is None, s['model']
    assert s['model']['orient']['forward'] == '+x' and s['model']['orient']['scale'] == 2.0 and s['model']['has_prop'] is False   # oturuma özel yönelim
    assert ok(a.get(f"{M}/{m1['id']}"))['orient']['forward'] == '-x'   # kütüphanedeki kayıt değişmedi
    ok(a.delete(f"{S}/{s['id']}"))
    s = ok(a.post(S, json={'type': 'vtol', 'center_id': c1['id'], 'airframe': 'delta'}), 201)                                 # geriye uyum
    assert s['airframe'] == 'delta' and s['model']['id'] == 'builtin:delta' and s['model']['name'] == 'VTOL-Delta kanat' and s['model']['type'] == 'vtol', s
    ok(a.delete(f"{S}/{s['id']}"))
    s = ok(a.post(S, json={'type': 'hexarotor', 'center_id': c1['id']}), 201)
    assert s['model']['id'] == 'builtin:hexa' and s['airframe'] is None, s
    ok(a.delete(f"{S}/{s['id']}"))
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': 'builtin:caymaz'}), 201)
    assert s['airframe'] == 'caymaz' and s['model']['has_prop'] is True and s['model']['thumb_url'] is None, s
    ok(a.delete(f"{S}/{s['id']}"))
    # --- yetki: salt okuyan listeler/indirir, yazamaz ---
    assert ok(mon.get(M))['can_write'] is False and mon.get(m1['glb_url']).status_code == 200 and mon.get(m1t['thumb_url']).status_code == 200
    assert mon.post(M, files={'file': ('a.glb', glb, 'model/gltf-binary')}, data={'type': 'multirotor'}).status_code == 403
    assert mon.put(f"{M}/{m1['id']}/glb", content=glb).status_code == 403 and mon.put(f'{M}/builtin:quad/thumb', content=png).status_code == 403
    assert mon.put(f"{M}/{m1['id']}", json={'name': 'x'}).status_code == 403 and mon.delete(f"{M}/{m1['id']}").status_code == 403
    assert mon.post(f'{M}/from-design', json={'version_id': 1, 'type': 'multirotor'}).status_code == 403
    # --- tasarım dosyasından ekleme: proje + çizim + STEP sürümü → design-files listeler → kütüphaneye ekle (dosya kopyalanmaz) ---
    pr = ok(a.post('/api/design/projects', json={'name': 'Sim Test Projesi'}))
    dr = ok(a.post(f"/api/design/projects/{pr['id']}/drawings", json={'name': 'Gövde Montajı', 'kind': 'assembly'}))
    ver = ok(a.post(f"/api/design/drawings/{dr['id']}/version", files={'file': ('govde-v1.step', b'ISO-10303-21;\nDATA;\nENDSEC;', 'application/octet-stream')}))
    ok(a.post(f"/api/design/drawings/{dr['id']}/version", files={'file': ('cizim.dxf', b'0\nSECTION', 'application/octet-stream')}))   # 3B değil: listelenmez
    df = ok(a.get(f'{M}/design-files'))
    assert [d['id'] for d in df] == [ver['id']] and df[0]['file_name'] == 'govde-v1.step' and df[0]['drawing_name'] == 'Gövde Montajı' and df[0]['project_name'] == 'Sim Test Projesi' and df[0]['model_id'] is None, df
    assert a.post(f'{M}/from-design', json={'version_id': 99999, 'type': 'vtol'}).status_code == 400
    assert a.post(f'{M}/from-design', json={'version_id': ver['id'], 'type': 'ucan_hali'}).status_code == 400
    md = ok(a.post(f'{M}/from-design', json={'version_id': ver['id'], 'type': 'vtol'}), 201)
    assert md['source'] == 'design' and md['source_ref'] == ver['id'] and md['name'] == 'Gövde Montajı' and md['type'] == 'vtol' and md['ready'] is False and md['format'] == 'step' and md['file_name'] == 'govde-v1.step', md
    assert a.get(md['file_url']).content.startswith(b'ISO-10303-21') and md['size'] == len(b'ISO-10303-21;\nDATA;\nENDSEC;')
    assert ok(a.post(f'{M}/from-design', json={'version_id': ver['id'], 'type': 'vtol'}), 201)['id'] == md['id']   # aynı sürüm+tip: tek kayıt
    assert ok(a.get(f'{M}/design-files'))[0]['model_id'] == int(md['id'])
    assert [m['id'] for m in ok(a.get(M, params={'type': 'vtol'}))['models']] == ['builtin:caymaz', 'builtin:delta', md['id']]
    ok(a.put(f"{M}/{md['id']}/glb", content=glb))
    s = ok(a.post(S, json={'type': 'vtol', 'center_id': c1['id'], 'model': md['id']}), 201)
    assert s['model']['source'] == 'design' and s['airframe'] is None
    ok(a.delete(f"{S}/{s['id']}"))
    # --- silme: kayıt + dizin gider; tasarımın özgün dosyası kalır ---
    ok(a.delete(f"{M}/{md['id']}"))
    assert a.get(f"{M}/{md['id']}").status_code == 404 and not (config.DATA_DIR / 'sim_models' / md['id']).exists() and a.get(f"/api/design/file?v={ver['id']}").status_code == 200
    ok(a.delete(f"{M}/{m1['id']}")); ok(a.delete(f"{M}/{m2['id']}")); ok(a.delete(f"{M}/{m3['id']}"))
    assert a.delete(f"{M}/{m1['id']}").status_code == 404 and a.delete(f'{M}/builtin:quad').status_code == 400
    assert not (config.DATA_DIR / 'sim_models' / m1['id']).exists()
    assert all(m['source'] == 'builtin' for m in ok(a.get(M))['models'])
    print('  görsel model kütüphanesi testleri geçti')


def rec_testleri(a, c1):
    """§17 ekran kaydı: start/chunk(sıra, tekrar, boyut)/thumb/finish → feed_posts (oturum sahibi adına, media video+thumb), yetki (salt okuyan 403),
    boyut sınırı (413 → 'full'), yarım kayıt listesi (pending; oturum kapanınca), 24 saat temizliği, silme."""
    from app import config, flightsim_rec
    S = '/api/drone/sim/sessions'
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'launch': {'method': 'ramp'}}}), 201)
    sid = s['id']
    WEBM = b'\x1aE\xdf\xa3' + bytes(range(256)) * 40   # sahte webm: EBML başlığı + dolgu
    # --- start: yazma izni olan; salt okuyan 403; olmayan oturum 404 ---
    r = ok(a.post(f'{S}/{sid}/rec/start', json={'mime': 'video/webm;codecs=vp9,opus'}), 201)
    rid = r['rec_id']
    assert len(rid) == 16 and r['ext'] == '.webm' and r['chunk_max'] == 8 * 1024 ** 2 and r['max_bytes'] == flightsim_rec.MAX_BYTES, r
    assert a.post(f'{S}/99999/rec/start', json={}).status_code == 404
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    assert mon.post(f'{S}/{sid}/rec/start', json={}).status_code == 403
    assert mon.put(f'/api/drone/sim/rec/{rid}/chunk?seq=0', content=WEBM).status_code == 403
    # --- parçalar: sıralı; tekrar yok sayılır; atlama 409; kötü kimlik 404; parça sınırı 413 ---
    R = f'/api/drone/sim/rec/{rid}'
    c0 = ok(a.put(f'{R}/chunk?seq=0', content=WEBM, headers={'Content-Type': 'application/octet-stream'}))
    assert c0 == {'ok': True, 'seq': 0, 'size': len(WEBM), 'max_bytes': flightsim_rec.MAX_BYTES}, c0
    c1b = ok(a.put(f'{R}/chunk?seq=1', content=WEBM))
    assert c1b['seq'] == 1 and c1b['size'] == 2 * len(WEBM)
    assert ok(a.put(f'{R}/chunk?seq=1', content=WEBM))['size'] == 2 * len(WEBM)   # yinelenen gönderim: idempotent
    assert a.put(f'{R}/chunk?seq=3', content=WEBM).status_code == 409
    assert a.put('/api/drone/sim/rec/zzzz/chunk?seq=0', content=WEBM).status_code == 404
    assert a.put('/api/drone/sim/rec/0123456789abcdef/chunk?seq=0', content=WEBM).status_code == 404
    assert a.put(f'{R}/chunk?seq=2', content=b'', headers={'Content-Length': str(9 * 1024 ** 2)}).status_code == 413
    assert (flightsim_rec.REC_DIR / f'{rid}.webm').stat().st_size == 2 * len(WEBM)
    # --- küçük resim: PNG dışı 415 ---
    PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
    assert a.put(f'{R}/thumb', content=b'GIF89a').status_code == 415
    ok(a.put(f'{R}/thumb', content=PNG))
    # --- oturumun kapanması kaydı silmez: kapat → yarım kayıt listesinde; bitir → paylaşım oturum SAHİBİ adına ---
    pend = ok(a.get('/api/drone/sim/rec/pending'))
    assert pend['items'] == [] and pend['max_mb'] == flightsim_rec.MAX_MB, pend   # oturum açıkken yarım sayılmaz
    ok(a.delete(f'{S}/{sid}'))
    pend = ok(a.get('/api/drone/sim/rec/pending'))['items']
    assert len(pend) == 1 and pend[0]['id'] == rid and pend[0]['type'] == 'sabit_kanat' and pend[0]['center'] == 'Test Merkezi' and pend[0]['size'] == 2 * len(WEBM) and pend[0]['seconds'] == 20, pend
    assert pend[0]['text'].startswith('Uçuş Simülatörü kaydı · Sabit kanat · Test Merkezi · rampa · '), pend[0]['text']
    assert ok(mon.get('/api/drone/sim/rec/pending'))['items'] == []   # başkasının yarım kaydı görünmez
    fin = ok(a.post(f'{R}/finish', json={'duration_s': 23.4, 'mime': 'video/webm'}))
    assert fin['ok'] and fin['post_id'] and fin['path'].startswith('feed/') and fin['path'].endswith('.webm') and fin['thumb'].endswith('.png') and fin['link'] == '#/home', fin
    assert fin['text'].startswith('Uçuş Simülatörü kaydı · Sabit kanat · Test Merkezi · rampa · 00:23 · 20'), fin['text']
    assert (config.UPLOAD_DIR / fin['path']).read_bytes() == 2 * WEBM and (config.UPLOAD_DIR / fin['thumb']).read_bytes() == PNG
    assert not (flightsim_rec.REC_DIR / f'{rid}.webm').exists() and not (flightsim_rec.REC_DIR / f'{rid}.json').exists()
    assert a.post(f'{R}/finish', json={}).status_code == 404   # bitti: meta silindi
    posts = ok(a.get('/api/feed'))['posts']
    p = next(x for x in posts if x['id'] == fin['post_id'])
    assert p['kind'] == 'USER' and p['author_id'] == s['owner']['id'] and p['text'] == fin['text'] and p['media'] == [{'type': 'video', 'path': fin['path'], 'thumb': fin['thumb']}], p
    assert a.get(f"/api/files/{fin['path']}").status_code == 200 and mon.get(f"/api/files/{fin['path']}").status_code == 200   # akış medyası tüm kullanıcılara (giriş zorunlu)
    assert ok(a.get('/api/drone/sim/rec/pending'))['items'] == []
    # --- yazma izinli BAŞKA kullanıcı kaydeder → paylaşım yine oturum sahibi (admin) adına; istemci metni kullanılır; mp4 uzantısı ---
    pil = TestClient(app, base_url='https://testserver')
    login(pil, 'pilot', 'sifre-1234')
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    r2 = ok(pil.post(f"{S}/{s2['id']}/rec/start", json={'mime': 'video/mp4'}), 201)
    assert r2['ext'] == '.mp4'
    R2 = f"/api/drone/sim/rec/{r2['rec_id']}"
    ok(pil.put(f'{R2}/chunk?seq=0', content=WEBM))
    fin2 = ok(pil.post(f'{R2}/finish', json={'duration_s': 5, 'text': '  Flight Simulator recording · Multirotor  '}))
    p2 = next(x for x in ok(a.get('/api/feed'))['posts'] if x['id'] == fin2['post_id'])
    assert p2['author_id'] == s['owner']['id'] and p2['text'] == 'Flight Simulator recording · Multirotor' and p2['media'][0]['path'].endswith('.mp4') and 'thumb' not in p2['media'][0], p2
    # --- boyut sınırı: aşan parça 413 ve kayıt 'full' (sonraki parça 409); yine de bitirilebilir ---
    r3 = ok(a.post(f"{S}/{s2['id']}/rec/start", json={}), 201)
    R3 = f"/api/drone/sim/rec/{r3['rec_id']}"
    ok(a.put(f'{R3}/chunk?seq=0', content=WEBM))
    m3 = flightsim_rec.meta_oku(r3['rec_id']); m3['max_bytes'] = len(WEBM) + 10; flightsim_rec._meta_yaz(m3)
    assert a.put(f'{R3}/chunk?seq=1', content=WEBM).status_code == 413
    assert flightsim_rec.meta_oku(r3['rec_id'])['state'] == 'full'
    assert a.put(f'{R3}/chunk?seq=1', content=b'x').status_code == 409
    assert ok(a.post(f'{R3}/finish', json={'duration_s': 10}))['size'] == len(WEBM)
    # --- boş kayıt bitirilemez (400); silme (salt okuyan 403); 24 saat temizliği (bozuk meta da kalkar) ---
    r4 = ok(a.post(f"{S}/{s2['id']}/rec/start", json={}), 201)
    R4 = f"/api/drone/sim/rec/{r4['rec_id']}"
    assert a.post(f'{R4}/finish', json={}).status_code == 400
    assert mon.delete(R4).status_code == 403
    ok(a.delete(R4))
    assert a.delete(R4).status_code == 404 and not (flightsim_rec.REC_DIR / f"{r4['rec_id']}.json").exists()
    r5 = ok(a.post(f"{S}/{s2['id']}/rec/start", json={}), 201)
    ok(a.put(f"/api/drone/sim/rec/{r5['rec_id']}/chunk?seq=0", content=WEBM))
    m5 = flightsim_rec.meta_oku(r5['rec_id']); m5['ts'] = time.time() - flightsim_rec.TTL_S - 5; flightsim_rec._meta_yaz(m5)
    (flightsim_rec.REC_DIR / 'bozuk.json').write_text('{', encoding='utf-8')
    assert flightsim_rec.temizle() == 1
    assert not (flightsim_rec.REC_DIR / f"{r5['rec_id']}.webm").exists() and not (flightsim_rec.REC_DIR / 'bozuk.json').exists()
    assert list(flightsim_rec.REC_DIR.iterdir()) == [], list(flightsim_rec.REC_DIR.iterdir())
    ok(a.delete(f"{S}/{s2['id']}"))
    print('  ekran kaydı (§17) testleri geçti')


def rec_sakla_testleri(a, c1):
    """§17 kayıt seçenekleri: finish share:false → paylaşım YOK, dosya sunucuda 'kept' → /rec/mine listesi, /rec/{id}/file indirme (yetki),
    pending'e düşmez, temizle korur (KEEP_S), /rec/{id}/share → paylaşım; sil."""
    from app import flightsim_rec
    S = '/api/drone/sim/sessions'
    WEBM = b'\x1aE\xdf\xa3' + bytes(range(256)) * 20
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    r = ok(a.post(f"{S}/{s['id']}/rec/start", json={'mime': 'video/webm;codecs=vp9,opus'}), 201)
    rid = r['rec_id']; R = f'/api/drone/sim/rec/{rid}'
    ok(a.put(f'{R}/chunk?seq=0', content=WEBM))
    n0 = len(ok(a.get('/api/feed'))['posts'])
    fin = ok(a.post(f'{R}/finish', json={'duration_s': 12, 'share': False, 'text': 'Flight Simulator recording · kept'}))
    assert fin == {'ok': True, 'kept': True, 'rec_id': rid, 'size': len(WEBM), 'text': 'Flight Simulator recording · kept', 'file': f'{R}/file', 'link': None}, fin
    assert len(ok(a.get('/api/feed'))['posts']) == n0   # paylaşım açılmadı
    assert flightsim_rec.meta_oku(rid)['state'] == 'kept' and (flightsim_rec.REC_DIR / f'{rid}.webm').exists()
    mine = ok(a.get('/api/drone/sim/rec/mine'))
    assert mine['keep_days'] == flightsim_rec.KEEP_DAYS and len(mine['items']) == 1, mine
    it = mine['items'][0]
    assert it['id'] == rid and it['seconds'] == 12 and it['size'] == len(WEBM) and it['text'] == 'Flight Simulator recording · kept' and it['type'] == 'multirotor' and it['file_name'].endswith('.webm') and it['kept_at'], it
    assert ok(a.get('/api/drone/sim/rec/pending'))['items'] == []
    ok(a.delete(f"{S}/{s['id']}"))
    assert ok(a.get('/api/drone/sim/rec/pending'))['items'] == []   # saklanan kayıt yarım değildir
    f = a.get(f'{R}/file')
    assert f.status_code == 200 and f.content == WEBM and 'attachment' in f.headers.get('content-disposition', '') and f.headers['content-type'].startswith('video/webm'), (f.status_code, f.headers)
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    assert mon.get(f'{R}/file').status_code == 403 and ok(mon.get('/api/drone/sim/rec/mine'))['items'] == []
    assert a.get('/api/drone/sim/rec/0123456789abcdef/file').status_code == 404
    assert flightsim_rec.temizle() == 0 and (flightsim_rec.REC_DIR / f'{rid}.webm').exists()   # 24 saat kuralı saklanana uygulanmaz
    assert a.put(f'{R}/chunk?seq=1', content=WEBM).status_code == 409   # kapalı
    # sonradan paylaş: saklanan metin/süre ile feed'e; dosya feed deposuna taşınır, listeden düşer
    sh = ok(a.post(f'{R}/share', json={}))
    assert sh['post_id'] and sh['text'] == 'Flight Simulator recording · kept' and sh['link'] == '#/home', sh
    p = next(x for x in ok(a.get('/api/feed'))['posts'] if x['id'] == sh['post_id'])
    assert p['author_id'] == s['owner']['id'] and p['media'][0]['path'].endswith('.webm')
    assert ok(a.get('/api/drone/sim/rec/mine'))['items'] == [] and a.get(f'{R}/file').status_code == 404
    # sakla → sil; sakla → KEEP_S aşımı → temizle
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    for i in range(2):
        r2 = ok(a.post(f"{S}/{s2['id']}/rec/start", json={}), 201)
        ok(a.put(f"/api/drone/sim/rec/{r2['rec_id']}/chunk?seq=0", content=WEBM))
        ok(a.post(f"/api/drone/sim/rec/{r2['rec_id']}/finish", json={'share': False}))
        if i == 0:
            ok(a.delete(f"/api/drone/sim/rec/{r2['rec_id']}"))
        else:
            m2 = flightsim_rec.meta_oku(r2['rec_id']); m2['ts'] = time.time() - flightsim_rec.KEEP_S - 5; flightsim_rec._meta_yaz(m2)
            assert flightsim_rec.temizle() == 1
        assert ok(a.get('/api/drone/sim/rec/mine'))['items'] == [] and not (flightsim_rec.REC_DIR / f"{r2['rec_id']}.webm").exists()
    ok(a.delete(f"{S}/{s2['id']}"))
    print('  kayıt saklama (§17 share:false) testleri geçti')


def bin_testleri(a, c1):
    """§19 .bin uçuş logu: SITL parm içeriği (LOG_BACKEND_TYPE 1 / LOG_DISARMED 0 / LOG_FILE_DSRMROT 1), oturum `rec.bin` → session.rec,
    kapanışta (sahte .BIN dosyaları) flight_logs kaydı (aircraft/pilot/location, dosya UPLOAD_DIR/flightlogs, DELETE yanıtı `bin`), boyut sınırı, dosya yok → null."""
    import pathlib
    from app import config, db, drone_sitl, flightsim_bin
    S = '/api/drone/sim/sessions'
    p1, p0 = drone_sitl.parm_metni(1, True), drone_sitl.parm_metni(7, False)
    assert 'LOG_BACKEND_TYPE 1\n' in p1 and 'LOG_DISARMED 0\n' in p1 and 'LOG_FILE_DSRMROT 1\n' in p1 and 'MAV_SYSID 1\n' in p1, p1
    assert 'LOG_BACKEND_TYPE 0\n' in p0 and 'LOG_DISARMED 0\n' in p0 and 'DSRMROT' not in p0 and 'MAV_SYSID 7\n' in p0, p0
    assert a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'rec': 'evet'}).status_code in (400, 422)   # rec nesne olmalı (pydantic 422)
    s0 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s0['rec'] == {'bin': False, 'bin_log': None}, s0['rec']
    assert ok(a.delete(f"{S}/{s0['id']}")) == {'ok': True, 'bin': None}
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'rec': {'bin': True}}), 201)
    assert s['rec'] == {'bin': True, 'bin_log': None}, s['rec']
    bekle(lambda: ok(a.get(f"{S}/{s['id']}"))['state'] == 'HAZIR' or None)
    d = pathlib.Path(tempfile.mkdtemp())
    buyuk, kucuk = d / '00000002.BIN', d / '00000001.BIN'
    buyuk.write_bytes(b'\xa3\x95\x80\x80' + bytes(4096)); kucuk.write_bytes(b'\xa3\x95\x80\x80' + bytes(96))   # ikincisi yalnız başlık (< 1 KB)
    flightsim.MANAGER.sahte_bin_dosyalari = [buyuk, kucuk]
    r = ok(a.delete(f"{S}/{s['id']}"))
    b = r['bin']
    assert b and b['log_id'] and b['file_name'].startswith(f"SIM-{s['id']}-") and b['file_name'].endswith('.bin') and b['size'] == 4100, r
    assert not buyuk.exists() and not kucuk.exists()   # taşındı / artık silindi
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT * FROM flight_logs WHERE id = ?', (b['log_id'],)))
    assert row['aircraft'] == 'Simülatör · Multikopter' and row['pilot'] == s['owner']['name'] and row['location'] == 'Test Merkezi' and row['task_id'] is None and row['size'] == 4100, dict(row)
    assert row['file'].startswith('flightlogs/') and (config.UPLOAD_DIR / row['file']).stat().st_size == 4100 and row['file_name'] == b['file_name']
    assert 'Uçuş Simülatörü oturumu' in (row['note'] or '')
    bekle(lambda: db.row(db.connect().execute('SELECT status FROM flight_logs WHERE id = ?', (b['log_id'],)))['status'] != 'ISLENIYOR' or None, 20)   # analiz kuyruğuna girdi (sahte dosya → HATA)
    # boyut sınırı: aşan dosya kaydedilmez (error) ve silinir
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'rec': {'bin': True}}), 201)
    bekle(lambda: ok(a.get(f"{S}/{s['id']}"))['state'] == 'HAZIR' or None)
    big = d / '00000003.BIN'; big.write_bytes(bytes(8192))
    eski = flightsim_bin.MAX_BYTES; flightsim_bin.MAX_BYTES = 4096
    try:
        flightsim.MANAGER.sahte_bin_dosyalari = [big]
        r = ok(a.delete(f"{S}/{s['id']}"))
    finally:
        flightsim_bin.MAX_BYTES = eski
    assert r['bin'] and 'sınır' in r['bin']['error'] and not big.exists(), r
    # dosya yok (armed süre olmadı) → null
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'rec': {'bin': True}}), 201)
    bekle(lambda: ok(a.get(f"{S}/{s['id']}"))['state'] == 'HAZIR' or None)
    flightsim.MANAGER.sahte_bin_dosyalari = []
    assert ok(a.delete(f"{S}/{s['id']}"))['bin'] is None
    flightsim.MANAGER.sahte_bin_dosyalari = None
    with db.connect() as conn:
        conn.execute('DELETE FROM flight_logs WHERE id = ?', (b['log_id'],)); conn.commit()   # sonraki /logs listeleri etkilenmesin
    print('  .bin uçuş logu (§19) testleri geçti')


def kalkis_testleri(a, c1):
    """§13: world.launch doğrulama (400), parametre seti, sahte kipte üç yöntemin WS `launch` aşama olayları (armed → launch → released)."""
    S = '/api/drone/sim/sessions'
    # --- doğrulama ---
    for bad in ({'method': 'bungee'}, {'angle_deg': 5}, {'angle_deg': 31}, {'release_kmh': 30}, {'release_kmh': 120}, 7, {'angle_deg': True}):
        assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'launch': bad}}).status_code == 400, bad
    assert flightsim.world_dogrula({})['launch'] == flightsim.LAUNCH_DEFAULTS
    assert flightsim.world_dogrula({'launch': {'method': 'ramp', 'angle_deg': 22}})['launch'] == {'method': 'ramp', 'angle_deg': 22.0, 'release_kmh': 70}
    assert flightsim.launch_normalize('vtol', {'method': 'ramp'})['method'] == 'wheels' and flightsim.launch_normalize('sabit_kanat', {'method': 'ramp'})['method'] == 'ramp'
    # --- parametre seti ---
    pr = dict(flightsim.launch_parametreleri({'method': 'ramp', 'angle_deg': 20}, 80))
    assert pr['TKOFF_THR_MINACC'] == flightsim.RAMP_ACCEL and pr['TKOFF_THR_DELAY'] == 2.0 and pr['TKOFF_LVL_PITCH'] == 20.0 and pr['TKOFF_ALT'] == 80.0 and pr['SERVO7_FUNCTION'] == 0.0, pr
    pv = dict(flightsim.launch_parametreleri({'method': 'vehicle', 'release_kmh': 72}))
    assert pv['TKOFF_THR_MINACC'] == 0.0 and pv['TKOFF_ROTATE_SPD'] == 20.0 and 'TKOFF_ALT' not in pv, pv
    pw = dict(flightsim.launch_parametreleri({'method': 'wheels'}))
    assert pw['TKOFF_THR_MINACC'] == 0.0 and pw['TKOFF_ROTATE_SPD'] == 12.0, pw
    assert flightsim.LAUNCH_SITL_MODEL['ramp'] == 'plane-catapult' and flightsim.LAUNCH_SERVO == 7
    # yerde kayma düzeltmesi: her yöntemde SERVO3_MIN/TRIM 1000 (SITL gaz eşlemesi 1000–2000 µs; disarm'da itki 0 → uçak/düzenek kaymaz)
    for pp in (pr, pv, pw):
        assert pp['SERVO3_MIN'] == 1000.0 and pp['SERVO3_TRIM'] == 1000.0, pp
    assert dict(flightsim.PLANE_YER_PARAMLARI) == {'SERVO3_MIN': 1000.0, 'SERVO3_TRIM': 1000.0, 'CRASH_DETECT': 0.0}   # §18: ArduPlane yazılımsal tespit kapalı
    from app import drone_params
    assert 'CRASH_DETECT' in drone_params.oturum_adlari()   # oturum parametresi: dron kaydına kalıcı yazılmaz
    # RTK düzeyi GPS parametre seti (ilk kalp atışında tüm tiplerde): doğruluk ≤ 5 cm, ≥ 12 uydu, hız/aksaklık/irtifa hataları 0
    g = dict(flightsim.GPS_RTK_PARAMLARI)
    assert g['SIM_GPS1_ACC'] <= 0.05 and g['SIM_GPS1_NUMSATS'] >= 12, g
    assert all(v == 0.0 for k, v in g.items() if 'VERR' in k or 'GLTCH' in k or k.endswith(('NOISE', 'DRFTALT'))) and 'SIM_GPS1_VERR_Z' in g and 'SIM_GPS1_GLTCH_Z' in g, g
    # --- VTOL'de yöntem etkisiz (wheels) ---
    s = ok(a.post(S, json={'type': 'vtol', 'center_id': c1['id'], 'world': {'launch': {'method': 'vehicle', 'release_kmh': 90}}}), 201)
    assert s['launch'] == {'method': 'wheels', 'angle_deg': 15, 'release_kmh': 90.0, 'phase': None}, s['launch']
    ok(a.delete(f"{S}/{s['id']}"))
    # --- sahte kipte üç yöntem: aşama olayları ---
    token = a.cookies.get(auth.COOKIE)
    for launch, beklenen in (({'method': 'ramp', 'angle_deg': 18}, None), ({'method': 'vehicle', 'release_kmh': 60}, 60), ({'method': 'wheels'}, None)):
        s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'launch': launch, 'runway_heading': 90}}), 201)
        sid = s['id']
        assert s['launch']['method'] == launch['method'] and s['launch']['phase'] is None and s['world']['launch']['method'] == launch['method'], s['launch']
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            h = json.loads(ws.receive_text())
            assert h['t'] == 'hello' and h['session']['launch']['method'] == launch['method']
            # yerde kilit (sahte kip): disarm'da konum sabit (düzenek/uçak kaymaz), yer hızı 0, GPS RTK Fixed (fix 6; gerçek SITL ile tutarlı)
            teles, bitis = [], time.time() + 0.6
            while time.time() < bitis:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    teles.append(m)
            assert len(teles) >= 5, len(teles)
            assert all(not t['armed'] and t['groundspeed'] == 0 and t['gps_fix'] == 6 and t['sats'] == 18 and (t['lat'], t['lon']) == (teles[0]['lat'], teles[0]['lon']) for t in teles), teles[0]
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 60}, 'rid': 'k1'}))
            fazlar, tele_hiz, son_tele = [], {}, None
            bitis = time.time() + 12
            while time.time() < bitis and (not fazlar or fazlar[-1]['phase'] != 'released'):
                m = json.loads(ws.receive_text())
                if m['t'] == 'launch':
                    fazlar.append(m); tele_hiz[m['phase']] = (son_tele or {}).get('groundspeed')
                elif m['t'] == 'tele':
                    son_tele = m
            assert [f['phase'] for f in fazlar] == ['armed', 'launch', 'released'], fazlar
            assert all(f['method'] == launch['method'] for f in fazlar) and fazlar[0]['alt'] == 60.0
            t_launch = fazlar[1]['ts'] - fazlar[0]['ts']
            if launch['method'] == 'ramp':
                assert 1.0 <= t_launch <= 2.5 and fazlar[1]['angle_deg'] == 18.0 and fazlar[2]['speed_kmh'] >= 8 * 3.6 * 0.9, (t_launch, fazlar)
                assert (tele_hiz['launch'] or 0) < 1, tele_hiz   # fırlatma anında uçak henüz duruyor
            elif launch['method'] == 'vehicle':
                assert t_launch < 0.5 and fazlar[1]['release_kmh'] == 60.0 and 0.9 * beklenen <= fazlar[2]['speed_kmh'] <= 1.1 * beklenen, fazlar
                assert son_tele['alt_rel'] < 3 or fazlar[2]['speed_kmh'] >= 0.9 * beklenen   # bırakma yer hızında olur
            else:
                assert t_launch < 0.5 and son_tele['alt_rel'] >= 1, (t_launch, son_tele)
            g = ok(a.get(f'{S}/{sid}'))
            assert g['launch']['phase'] == 'released', g['launch']
            # havalandı: tırmanıyor, pist yönünde (doğu) ilerledi
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['alt_rel'] > 5, 6)
            assert m and m['armed'] and m['mode'] == 'TAKEOFF', m
            # reset → aşama sıfırlanır
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'k2'}))
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and not x['armed'] and x['alt_rel'] == 0, 3)
            assert ok(a.get(f'{S}/{sid}'))['launch']['phase'] is None
        ok(a.delete(f'{S}/{sid}'))
    print('  kalkış yöntemi testleri geçti')


def ruzgar_hava_testleri(a, c1):
    """§31: world.weather / wind_gust / wind_turb / launch.azimuth_deg doğrulama, esinti formülü (JS gustFactor ile aynı değerler), SITL ev yönü,
    sahte kinematikte rüzgâr etkisi (daire yer hızı salınımı, kopter eğimi, süzülme sürüklenmesi), `wind` (uçuşta rüzgâr) ve `launch_aim` (rampa) komutları."""
    S = '/api/drone/sim/sessions'
    # --- doğrulama ---
    w = flightsim.world_dogrula({'weather': 'storm', 'wind_gust': 4, 'wind_turb': 2.5, 'launch': {'method': 'ramp', 'azimuth_deg': 275}})
    assert w['weather'] == 'storm' and w['wind_gust'] == 4.0 and w['wind_turb'] == 2.5 and w['launch']['azimuth_deg'] == 275.0, w
    d = flightsim.world_dogrula({})
    assert d['weather'] == 'clear' and d['wind_gust'] == 0 and d['wind_turb'] == 0 and 'azimuth_deg' not in d['launch'], d
    for bad in ({'weather': 'hail'}, {'weather': 3}, {'wind_gust': 25}, {'wind_turb': -1}, {'wind_turb': 11}, {'launch': {'azimuth_deg': 360}}, {'launch': {'azimuth_deg': True}}):
        try:
            flightsim.world_dogrula(bad)
        except flightsim.SimHata:
            continue
        raise AssertionError(f'kabul edilmemeliydi: {bad}')
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'weather': 'hail'}}).status_code == 400
    # --- esinti: JS flightsim_weather.gustFactor ile aynı (tests/test_flightsim_worldfx.mjs aynı tabloyu doğrular) ---
    for t, beklenen in ((0.0, 0.25), (3.2, 0.3184), (7.7, 0.0256), (12.5, 0.2581)):
        assert abs(flightsim.esinti_carpani(t) - beklenen) < 1e-4, (t, flightsim.esinti_carpani(t))
    gs = [flightsim.esinti_carpani(i * 0.25) for i in range(400)]
    assert min(gs) >= 0 and max(gs) <= 1 and max(gs) > 0.8 and min(gs) < 0.05, (min(gs), max(gs))
    n, e = flightsim.ruzgar_vektoru(10, 270)   # batıdan esen → doğuya akar
    assert abs(n) < 1e-9 and abs(e - 10) < 1e-9, (n, e)
    # --- SITL ev yönü: sabit kanat rampa azimutu > pist yönü; diğer tipler 0 ---
    assert flightsim.kalkis_yonu('sabit_kanat', {'method': 'ramp', 'azimuth_deg': 95}, {'runway_heading': 10}) == 95
    assert flightsim.kalkis_yonu('sabit_kanat', {'method': 'wheels', 'azimuth_deg': 95}, {'runway_heading': 10}) == 10
    assert flightsim.kalkis_yonu('multirotor', {'method': 'ramp', 'azimuth_deg': 95}, {'runway_heading': 10}) == 0
    # --- sahte kinematik: rüzgâr ---
    def dairede(tip, ms, yon=270, turb=0):
        k = flightsim.SahteKinematik(tip, 39.9, 32.8, 900, ms, None, 0, yon, 0, turb)
        k.komut('arm', {}); k.hedef_alt = 50.0; k.alt_rel = 50.0; k.aci = 0.0
        out = []
        for _ in range(int(2 * math.pi * k.YARICAP / k.HIZ / 0.05) + 40):
            k.adim(0.05); out.append(k.tele())
        return k, out
    _, sakin = dairede('sabit_kanat', 0)
    _, ruz = dairede('sabit_kanat', 6)
    g0 = [t['groundspeed'] for t in sakin]; g1 = [t['groundspeed'] for t in ruz]; a1 = [t['airspeed'] for t in ruz]
    assert max(g0) - min(g0) < 0.2, (min(g0), max(g0))
    assert 10 <= max(g1) - min(g1) <= 13, (min(g1), max(g1))   # yer hızı = hava hızı ± rüzgâr (12 ± 6)
    assert max(a1) - min(a1) < 0.6 and abs(sum(a1) / len(a1) - 12) < 0.5, (min(a1), max(a1))   # hava hızı sabit
    yengec = max(abs(((math.degrees(math.atan2(t['ve'], t['vn'])) - t['heading'] + 540) % 360) - 180) for t in ruz)
    assert 20 <= yengec <= 40, yengec   # burun hava hızı yönünde: yengeç açısı ≈ asin(6/12) = 30°
    kk, kop = dairede('multirotor', 8)
    _, kop0 = dairede('multirotor', 0)
    assert max(abs(t['pitch'] - (-0.05)) + abs(t['roll'] - 0.12) for t in kop) > 0.08 and max(abs(t['pitch'] + 0.05) for t in kop0) < 1e-6
    _, tur = dairede('sabit_kanat', 3, turb=4)
    assert max(t['roll'] for t in tur) - min(t['roll'] for t in tur) > 0.05   # türbülans: yönelim salınımı
    k = flightsim.SahteKinematik('sabit_kanat', 39.9, 32.8, 900, 10, None, 0, 270, 0, 0)   # süzülme: hava kütlesiyle doğuya sürüklenir
    k.komut('arm', {}); k.alt_rel = 100.0; k.hedef_alt = 100.0; k.yaw = 0.0; k.komut('motor_cut', {'on': True})
    lon0 = k.lon
    for _ in range(100):
        k.adim(0.05)
    assert (k.lon - lon0) * 111320 * math.cos(math.radians(39.9)) > 40, (k.lon - lon0)
    # esinti: anlık hız taban + gust·g(t)
    k = flightsim.SahteKinematik('multirotor', 39.9, 32.8, 900, 5, None, 0, 90, 4, 0)
    vs = []
    for _ in range(300):
        k.adim(0.1); vs.append(k.ruzgar_simdi())
    assert min(vs) >= 5 - 1e-9 and max(vs) <= 9 + 1e-9 and max(vs) - min(vs) > 2.5, (min(vs), max(vs))
    # --- oturum: `wind` komutu (uçuşta rüzgâr) + tele.wind_spd/wind_dir + WS `wind` olayı ---
    token = a.cookies.get(auth.COOKIE)
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'wind_ms': 3, 'wind_dir': 200, 'weather': 'rain'}}), 201)
    sid = s['id']
    assert s['world']['weather'] == 'rain' and s['world']['wind_gust'] == 0, s['world']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        json.loads(ws.receive_text())
        m = ws_bekle(ws, lambda x: x['t'] == 'tele', 3)
        assert m['wind_spd'] == 3.0 and m['wind_dir'] == 200.0, m
        r = ok(a.post(f'{S}/{sid}/cmd', json={'name': 'wind', 'params': {'ms': 9, 'dir': 250, 'gust': 3, 'turb': 1.5}}))
        assert r['wind'] == {'wind_ms': 9.0, 'wind_dir': 250.0, 'wind_gust': 3.0, 'wind_turb': 1.5}, r
        e = ws_bekle(ws, lambda x: x['t'] == 'wind', 3)
        assert e and e['wind_ms'] == 9.0 and e['wind_dir'] == 250.0, e
        m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x.get('wind_dir') == 250.0, 3)
        assert m and 9.0 <= m['wind_spd'] <= 12.0, m
        ss = flightsim.MANAGER.sessions[sid]
        assert ss.world['wind_ms'] == 9.0 and ss.sahte.ruzgar == 9.0 and ss.sahte.ruzgar_yon == 250.0 and ss.sahte.ruzgar_turb == 1.5
        r = ok(a.post(f'{S}/{sid}/cmd', json={'name': 'wind', 'params': {'dir': 10}}))   # yalnız yön: diğerleri korunur
        assert r['wind']['wind_ms'] == 9.0 and r['wind']['wind_dir'] == 10.0
        for bad in ({}, {'ms': 31}, {'dir': 360}, {'gust': True}, {'turb': 'x'}):
            assert a.post(f'{S}/{sid}/cmd', json={'name': 'wind', 'params': bad}).status_code == 400, bad
        # rampa olmayan oturumda launch_aim 400
        assert a.post(f'{S}/{sid}/cmd', json={'name': 'launch_aim', 'params': {'azimuth_deg': 90}}).status_code == 400
    ok(a.delete(f'{S}/{sid}'))
    # --- `launch_aim`: rampa yön/açı ARM öncesi (sahte kipte kalkış yönü anında; gerçek SITL'de yön → yeniden konuşlandırma) ---
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'runway_heading': 30, 'launch': {'method': 'ramp', 'angle_deg': 15}}}), 201)
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ss = flightsim.MANAGER.sessions[sid]
    assert abs(math.degrees(ss.sahte.heading) - 30) < 1e-6   # azimut yok → pist yönü
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        json.loads(ws.receive_text())
        r = ok(a.post(f'{S}/{sid}/cmd', json={'name': 'launch_aim', 'params': {'azimuth_deg': 250, 'angle_deg': 22.5}}))
        assert r['launch']['azimuth_deg'] == 250.0 and r['launch']['angle_deg'] == 22.5 and r['heading'] == 250.0 and r['redeploy'] is False, r
        e = ws_bekle(ws, lambda x: x['t'] == 'launch_cfg', 3)
        assert e and e['launch']['azimuth_deg'] == 250.0 and e['redeploy'] is False, e
        assert abs(math.degrees(ss.sahte.heading) - 250) < 1e-6 and ss.sahte.launch['angle_deg'] == 22.5
        assert ok(a.get(f'{S}/{sid}'))['launch']['azimuth_deg'] == 250.0
        for bad in ({}, {'azimuth_deg': 360}, {'angle_deg': 9}, {'angle_deg': 31}, {'azimuth_deg': 'x'}):
            assert a.post(f'{S}/{sid}/cmd', json={'name': 'launch_aim', 'params': bad}).status_code == 400, bad
        # kalkış: rampa azimutu yönünde (250° → batı-güneybatı) ilerler; ARM sonrası launch_aim 400
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 40}, 'rid': 'r1'}))
        assert ws_bekle(ws, lambda x: x['t'] == 'launch' and x['phase'] == 'released', 8)
        m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['alt_rel'] > 0.2, 6)
        kerteriz = math.degrees(math.atan2((m['lon'] - m['home']['lon']) * math.cos(math.radians(m['home']['lat'])), m['lat'] - m['home']['lat'])) % 360
        assert m and abs(((kerteriz - 250) + 180) % 360 - 180) < 3, (kerteriz, m)   # fırlatma yönü = rampa azimutu
        assert a.post(f'{S}/{sid}/cmd', json={'name': 'launch_aim', 'params': {'azimuth_deg': 90}}).status_code == 400
    ok(a.delete(f'{S}/{sid}'))
    print('  hava durumu / rüzgâr / rampa yön-açı (§31) testleri geçti')


def duzen_testleri(a, c1):
    """§13.1 kontrol düzeni: layout doğrulama (400), model → varsayılan düzen, parametre setleri (ArduPilot autotest ile aynı), kalıcı kayıt
    önceliği (yazılacak/atlanan, etkin düzen, SITL model son eki), oturum alanları (layout, layout_effective, layout_sitl_model), model kütüphanesi
    (builtin:talon vtail + orient; caymaz/delta elevon), sahte kipte servo_fn/servo_rev tele alanları."""
    from app import drone_params, flightsim_models
    S = '/api/drone/sim/sessions'
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'layout': 'canard'}).status_code == 400
    assert flightsim.LAYOUTS == ('classic', 'elevon', 'vtail') and flightsim.LAYOUT_SITL_EKI == {'elevon': '-elevon', 'vtail': '-vtail'}
    assert flightsim.layout_dogrula('multirotor', 'vtail') is None and flightsim.layout_dogrula('vtol', 'elevon') is None
    assert flightsim.layout_dogrula('sabit_kanat', None, {'id': 'builtin:caymaz', 'layout': 'elevon'}) == 'elevon'
    assert flightsim.layout_dogrula('sabit_kanat', None, {'id': 'builtin:talon', 'layout': 'vtail'}) == 'vtail'
    assert flightsim.layout_dogrula('sabit_kanat', None, {'id': '5'}) == 'classic' and flightsim.layout_dogrula('sabit_kanat', 'vtail', {'layout': 'elevon'}) == 'vtail'
    # --- parametre setleri: ArduPilot Tools/autotest/default_params (plane-elevons.parm, plane-vtail.parm) ile aynı; REVERSED/4. kanal nötrlenir ---
    pv = dict(flightsim.LAYOUT_PARAMLARI['vtail']); pe = dict(flightsim.LAYOUT_PARAMLARI['elevon']); pc = dict(flightsim.LAYOUT_PARAMLARI['classic'])
    assert (pv['SERVO1_FUNCTION'], pv['SERVO2_FUNCTION'], pv['SERVO4_FUNCTION'], pv['SERVO2_REVERSED'], pv['SERVO1_REVERSED'], pv['MIXING_GAIN']) == (4.0, 80.0, 79.0, 1.0, 0.0, 0.5), pv
    assert (pe['SERVO1_FUNCTION'], pe['SERVO2_FUNCTION'], pe['SERVO4_FUNCTION'], pe['SERVO1_REVERSED'], pe['SERVO2_REVERSED'], pe['MIXING_GAIN']) == (78.0, 77.0, 0.0, 1.0, 1.0, 0.5), pe
    assert (pc['SERVO1_FUNCTION'], pc['SERVO2_FUNCTION'], pc['SERVO4_FUNCTION'], pc['SERVO1_REVERSED'], pc['SERVO2_REVERSED']) == (4.0, 19.0, 21.0, 0.0, 0.0), pc
    for ad in ('SERVO1_FUNCTION', 'SERVO2_REVERSED', 'MIXING_GAIN'):   # dron yapılandırması: kalıcı kaydedilir (oturum hariç listesinde DEĞİL)
        assert not drone_params.haric_mi(ad), ad
    # --- kalıcı kayıt önceliği ---
    yaz, atla = flightsim.layout_parametreleri('vtail', ())
    assert dict(yaz) == pv and atla == []
    yaz, atla = flightsim.layout_parametreleri('elevon', ['SERVO1_FUNCTION', 'SERVO2_FUNCTION', 'MIXING_GAIN'])
    assert atla == ['SERVO1_FUNCTION', 'SERVO2_FUNCTION', 'MIXING_GAIN'] and 'SERVO1_FUNCTION' not in dict(yaz) and dict(yaz)['SERVO1_REVERSED'] == 1.0
    # etkin fonksiyonlar → SITL son eki: düzen seti → kalıcı kayıt ezer
    assert flightsim.sitl_model_eki(flightsim.layout_etkin_fn('vtail')) == '-vtail' and flightsim.sitl_model_eki(flightsim.layout_etkin_fn('elevon')) == '-elevon'
    assert flightsim.sitl_model_eki(flightsim.layout_etkin_fn('classic')) == '' and flightsim.layout_etkin(flightsim.layout_etkin_fn('vtail')) == 'vtail'
    caymaz = [{'name': 'SERVO1_FUNCTION', 'value': 4.0}, {'name': 'SERVO2_FUNCTION', 'value': 19.0}, {'name': 'SERVO1_REVERSED', 'value': 1.0}]   # PROD dron 5 kaydı (§20.1)
    fn = flightsim.layout_etkin_fn('elevon', caymaz)
    assert fn[1] == 4 and fn[2] == 19 and fn[4] == 0 and flightsim.sitl_model_eki(fn) == '' and flightsim.layout_etkin(fn) == 'classic', fn   # kalıcı 4/19 → düz plane (eski davranış)
    assert flightsim.sitl_model_eki({1: 77, 2: 77, 4: 21}) == '' and flightsim.sitl_model_eki({1: 4, 2: 79, 4: 79}) == '' and flightsim.sitl_model_eki({1: 4, 2: 79, 4: 80}) == '-vtail'
    assert flightsim.sitl_model_eki({1: 4, 2: 19, 4: 21, 5: 77, 6: 78}) == '', 'çift başka kanalda: fizik göremez → düz'
    # --- model kütüphanesi: builtin:talon (vtail, orient, GLB var), caymaz/delta elevon ---
    ml = ok(a.get('/api/drone/sim/models?type=sabit_kanat'))['models']
    byid = {m['id']: m for m in ml}
    assert byid['builtin:talon']['layout'] == 'vtail' and byid['builtin:talon']['orient']['forward'] == '+x' and byid['builtin:talon']['glb_url'] == '/static/models/talon-vtail.glb' and byid['builtin:talon']['size'] > 10000, byid['builtin:talon']
    assert byid['builtin:caymaz']['layout'] == 'elevon' and byid['builtin:delta']['layout'] == 'elevon' and byid['builtin:talon']['types'] == ['sabit_kanat']
    assert 'builtin:talon' not in {m['id'] for m in ok(a.get('/api/drone/sim/models?type=vtol'))['models']}
    assert flightsim_models.kimlik_coz('builtin:talon') == ('builtin', 'talon')
    r = a.get('/static/models/talon-vtail.glb'); assert r.status_code == 200 and r.content[:4] == b'glTF'
    # --- oturumlar: düzen alanları; model → varsayılan düzen; VTOL/kopterde None ---
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': 'builtin:talon'}), 201)
    assert s['layout'] == 'vtail' and s['layout_effective'] == 'vtail' and s['layout_skipped'] == [] and s['model']['id'] == 'builtin:talon', s
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    g = ok(a.get(f'{S}/{sid}'))
    assert g['layout_sitl_model'] == 'plane-vtail', g['layout_sitl_model']   # sahte kipte de hesaplanır (bilgi); gerçek SITL bu modelle açılır
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hello = json.loads(ws.receive_text()); assert hello['session']['layout'] == 'vtail'
        t = ws_bekle(ws, lambda x: x['t'] == 'tele', 3); assert t and 'servo_fn' in t and 'servo_rev' in t and len(t['servo_rev']) == 8, t and list(t)
    ok(a.delete(f'{S}/{sid}'))
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'model': 'builtin:caymaz', 'layout': 'classic'}), 201)
    assert s['layout'] == 'classic', s['layout']; ok(a.delete(f"{S}/{s['id']}"))
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)   # model/düzen verilmedi → varsayılan Caymaz → elevon
    assert s['layout'] == 'elevon' and s['model']['id'] == 'builtin:caymaz'; ok(a.delete(f"{S}/{s['id']}"))
    s = ok(a.post(S, json={'type': 'vtol', 'center_id': c1['id'], 'layout': 'vtail'}), 201)
    assert s['layout'] is None; ok(a.delete(f"{S}/{s['id']}"))
    # --- dron kaydı ile: kalıcı 4/19 (CAYMAZ) → elevon istenir, etkin classic, atlananlar listede ---
    d = ok(a.post('/api/drone/drones', json={'name': 'Düzen Sanal', 'protocol': 'sanal', 'model': 'Caymaz plane'}))
    from app import db as _db
    with _db.connect() as conn:   # kalıcı kayıt doğrudan tabloya (import ucu denetim kaydı sayacını — param_testleri — oynatmasın)
        conn.executemany('INSERT INTO drone_sitl_params (drone_id, name, value, ptype, updated_at, updated_by, source) VALUES (?,?,?,?,?,?,?)',
                         [(d['id'], 'SERVO1_FUNCTION', 4.0, 9, _db.now(), 1, 'hepgo'), (d['id'], 'SERVO2_FUNCTION', 19.0, 9, _db.now(), 1, 'hepgo')])
        conn.commit()
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'drone_id': d['id'], 'layout': 'elevon'}), 201)
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    g = ok(a.get(f'{S}/{sid}'))
    assert g['layout'] == 'elevon' and g['layout_effective'] == 'classic' and g['layout_sitl_model'] == 'plane', (g['layout'], g['layout_effective'], g['layout_sitl_model'])   # kalıcı 4/19 öncelikli → düz plane
    # konsol notu (_layout_yaz; sahte kipte ilk kalp atışı yok → doğrudan): sarı uyarı, atlanan adlar ve fiilen uçan kurulum
    ses = flightsim.MANAGER.get(sid); olaylar = []
    ses._olay = lambda text, severity=6: olaylar.append((text, severity))
    ses._param_set = lambda ciftler: olaylar.append(('SET', dict(ciftler)))
    ses._layout_yaz()
    yaz = next(o[1] for o in olaylar if o[0] == 'SET'); met = next(o for o in olaylar if o[0] != 'SET')
    assert 'SERVO1_FUNCTION' not in yaz and 'SERVO2_FUNCTION' not in yaz and yaz['SERVO1_REVERSED'] == 1.0 and yaz['MIXING_GAIN'] == 0.5, yaz
    assert met[1] == 4 and 'kalıcı kaydı öncelikli' in met[0] and 'SERVO1_FUNCTION' in met[0] and 'Aileron + Elevatör' in met[0] and 'model plane' in met[0], met
    assert g['layout_skipped'] == [] and ok(a.get(f'{S}/{sid}'))['layout_skipped'] == ['SERVO1_FUNCTION', 'SERVO2_FUNCTION'], 'atlananlar _layout_yaz sonrası'
    ok(a.delete(f'{S}/{sid}'))
    ok(a.delete(f"/api/drone/drones/{d['id']}"))
    print('  kontrol düzeni testleri geçti')
def hub_testleri(a, c1):
    """§14 harekât paneli: oturum hub'a sanal köprü olarak kaydolur (bridge_id = -(9000+N)); GET /sessions/{id}/live; /ws/drone/live watch{sim_id}
    → hello.task/flights + status (sahte kipte kinematikten üretilen MAVLink çerçeveleri); hub komutları (arm, set_mode, GÖKTUNGU kalkış akışı,
    mission_upload → 3B rota, AUTO, mission_clear, rtl); yetki (drone.sim yazma izni; field.live'sız kullanıcı yalnız simülatörü görür); kapanış."""
    from app import drone_hub, flightsim_hub
    sd = ok(a.post('/api/drone/drones', json={'name': 'Sim Dronu', 'protocol': 'mavlink', 'model': 'Quad X'}))
    assert any(d['id'] == sd['id'] and d['code'] == sd['code'] for d in ok(a.get('/api/drone/sim/drones')))
    assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': 999999}).status_code == 400
    s = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': sd['id']}), 201)
    sid, bid = s['id'], -(flightsim.KIMLIK_TABANI + s['id'])
    assert s['hub'] == {'bridge_id': bid, 'online': True, 'name': f"{sd['code']} Sim Dronu"} and s['drone']['id'] == sd['id'] and s['route'] == [], s
    assert isinstance(drone_hub.SIMS.get(bid), flightsim_hub.SimBridge) and drone_hub.SIMS[bid].drone_id == sd['id']
    assert bekle(lambda: ok(a.get(f'/api/drone/sim/sessions/{sid}'))['state'] == 'HAZIR')
    # --- REST bağlamı (hepgo_ws.js ?sim=) ---
    lv = ok(a.get(f'/api/drone/sim/sessions/{sid}/live'))
    assert lv['task']['sim_id'] == sid and lv['task']['id'] is None and lv['task']['code'] == f'SİM #{sid}' and lv['task']['lat'] == 39.925, lv['task']
    f = lv['flights'][0]
    assert len(lv['flights']) == 1 and f['protocol'] == 'sanal' and f['sim_bridge_id'] == bid and f['label'] == sd['code'] and f['name'] == 'Sim Dronu' and f['drone_id'] == sd['id'], f
    assert lv['can_command'] is True and lv['session']['id'] == sid
    assert a.get('/api/drone/sim/sessions/99999/live').status_code == 404
    mon = TestClient(app, base_url='https://testserver')
    mtoken = login(mon, 'montaj', 'sifre-1234')
    assert ok(mon.get(f'/api/drone/sim/sessions/{sid}/live'))['can_command'] is False
    assert 'field.live' not in ok(mon.get('/api/auth/me'))['modules']   # montaj: Canlı Uçuş yok, yalnız drone.sim

    def pump(ws, kutu, sn, until=None):
        bitis = time.time() + sn
        while time.time() < bitis:
            m = json.loads(ws.receive_text())
            if m.get('t') == 'status' and m.get('bridge_id') == bid:
                kutu['state'].update(m['state'])
            elif m.get('t') in ('event', 'console') and m.get('bridge_id') == bid:
                kutu['log'].append(m['text'])
            elif m.get('t') == 'res':
                kutu['res'][m['rid']] = m
            elif m.get('t') == 'hello':
                kutu['hello'].append(m)
            elif m.get('t') == 'bridge':
                kutu['bridge'].append(m)
            elif m.get('t') == 'error':
                kutu['err'].append(m)
            if until and until():
                return True
        return bool(until and until())

    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={token}'}) as live:
        K = {'state': {}, 'log': [], 'res': {}, 'hello': [], 'bridge': [], 'err': []}
        assert pump(live, K, 3, lambda: K['hello']) and any(b['bridge_id'] == bid and b.get('simulator') for b in K['hello'][0]['bridges'])   # görevsiz izleyici: hepsi
        live.send_text(json.dumps({'t': 'watch', 'sim_id': sid}))
        assert pump(live, K, 3, lambda: len(K['hello']) >= 2)
        h = K['hello'][-1]
        assert h['task']['sim_id'] == sid and h['flights'][0]['sim_bridge_id'] == bid and [b['bridge_id'] for b in h['bridges']] == [bid] and h['me']['can_command'] is True, h
        assert 'mission_start' in h['caps'] and 'param' in h['caps'], h['caps']
        # telemetri (sahte kinematik → MAVLink çerçeveleri → hub DroneState)
        assert pump(live, K, 5, lambda: K['state'].get('lat') is not None and K['state'].get('type') == 2 and K['state'].get('mode')), K['state']
        st = K['state']
        assert abs(st['lat'] - 39.925) < 0.01 and st['armed'] is False and st['mode'] == 'STABILIZE' and st['fix'] == 3 and st['sats'] == 12 and st['volt'] > 10, st
        assert st['sensors'].get('gps') == 'ok' and st['home_lat'] is not None and st['mission_count'] == 0, st

        def cmd(rid, name, params=None, sn=12):
            live.send_text(json.dumps({'t': 'cmd', 'rid': rid, 'bridge_id': bid, 'sysid': 1, 'name': name, 'params': params or {}}))
            assert pump(live, K, sn, lambda: rid in K['res']), (rid, K['log'][-5:])
            return K['res'][rid]
        r = cmd('h1', 'arm')
        assert r['ok'] is True, r
        assert pump(live, K, 3, lambda: K['state'].get('armed') is True), K['state']
        assert any('-> arm' in x for x in K['log']) and any(x.startswith('ARM') for x in K['log']), K['log']
        r = cmd('h2', 'set_mode', {'mode': 'GUIDED'})
        assert r['ok'] is True and pump(live, K, 3, lambda: K['state'].get('mode') == 'GUIDED'), (r, K['state'].get('mode'))
        assert cmd('h2b', 'set_mode', {'mode': 'UCUS'})['ok'] is False
        # GÖKTUNGU kalkış akışı (sunucu-içi bileşik komut): GUIDED teyit → (ARM var) → NAV_TAKEOFF; sahte kinematik tırmanır
        r = cmd('h3', 'takeoff', {'alt_rel_m': 25})
        assert r['ok'] is True and r['result'] == {'kontrol_id': None}, r
        assert pump(live, K, 8, lambda: (K['state'].get('alt_rel') or 0) > 1 and any('TAKEOFF komutu iletildi' in x for x in K['log'])), (K['state'].get('alt_rel'), K['log'][-6:])
        # görev yükleme (routes/{id}/mission biçimi) → SITL'e (sahte: bellek) + 3B rota noktaları ({t:'route'} ve session.route)
        items = [{'seq': 0, 'frame': 6, 'command': 22, 'current': 1, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 0, 'y': 0, 'z': 30.0},
                 {'seq': 1, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 399260000, 'y': 328380000, 'z': 40.0},
                 {'seq': 2, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 5, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 399270000, 'y': 328390000, 'z': 50.0}]
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as sws:
            hs = json.loads(sws.receive_text())
            assert hs['t'] == 'hello' and hs['session']['route'] == [] and hs['session']['hub']['bridge_id'] == bid, hs['session']['hub']
            r = cmd('h4', 'mission_upload', {'items': items, 'cruise_speed': 8})
            assert r['ok'] is True and r['result']['count'] == 3 and r['result']['offset'] == 1, r
            rt = ws_bekle(sws, lambda m: m['t'] == 'route', 3)
            # TAKEOFF (x/y 0) çizilmez; seq = SITL seq (ev öğesi ofseti +1 → MISSION_CURRENT ile eşleşir); §18 alanları: source/home/end/landing_circle_m
            assert rt and [p['seq'] for p in rt['points']] == [2, 3] and {k: rt['points'][0][k] for k in ('seq', 'cmd', 'lat', 'lon', 'alt', 'alt_rel')} == {'seq': 2, 'cmd': 16, 'lat': 39.926, 'lon': 32.838, 'alt': 40.0, 'alt_rel': 40.0}, rt
            assert rt['source'] == 'hepgo' and rt['end'] == {'lat': 39.927, 'lon': 32.839, 'alt_rel': 50.0, 'cmd': 16, 'seq': 3, 'alt_msl': 950.0} and rt['landing_circle_m'] == 30 and rt['home']['lat'] == 39.925, rt
            ev = ws_bekle(sws, lambda m: m['t'] == 'event' and 'görev yüklendi' in m['text'], 3)
            assert ev and ev['text'] == 'HEPGO panelinden görev yüklendi: 2 nokta', ev
        assert ok(a.get(f'/api/drone/sim/sessions/{sid}'))['route'][1]['alt'] == 50.0
        assert pump(live, K, 3, lambda: K['state'].get('mission_count') == 3), K['state'].get('mission_count')
        assert cmd('h5', 'set_mode', {'mode': 'AUTO'})['ok'] is True and pump(live, K, 3, lambda: K['state'].get('mode') == 'AUTO')
        r = cmd('h6', 'mission_download')
        assert r['ok'] and len(r['result']['items']) == 3
        r = cmd('h7', 'mission_cancel', {'rota': 'Test'}, 20)   # BRAKE (doğrulanır) + mission_clear → rota silinir
        assert r['ok'] is True and ok(a.get(f'/api/drone/sim/sessions/{sid}'))['route'] == [] and pump(live, K, 3, lambda: K['state'].get('mission_count') == 0), r
        assert cmd('h8', 'rtl')['ok'] is True and pump(live, K, 3, lambda: K['state'].get('mode') == 'RTL')
        assert cmd('h9', 'arm_check')['ok'] is True and K['res']['h9']['result']['bulundu'] is True
        assert cmd('h10', 'reboot')['ok'] is False
        # --- yetki: montaj (drone.sim okur, yazamaz; field.live yok) → bağlanır, yalnız simülatörü izler, komut reddedilir ---
        with mon.websocket_connect('/ws/drone/live', headers={'cookie': f'{auth.COOKIE}={mtoken}'}) as mw:
            M = {'state': {}, 'log': [], 'res': {}, 'hello': [], 'bridge': [], 'err': []}
            assert pump(mw, M, 3, lambda: M['hello']) and M['hello'][0]['bridges'] == [] and M['hello'][0]['me']['can_command'] is False, M['hello'][0]
            mw.send_text(json.dumps({'t': 'watch', 'task_id': 1}))
            assert pump(mw, M, 3, lambda: M['err']) and 'yetki' in M['err'][0]['error'].lower(), M['err']
            mw.send_text(json.dumps({'t': 'watch', 'sim_id': sid}))
            assert pump(mw, M, 3, lambda: len(M['hello']) >= 2) and [b['bridge_id'] for b in M['hello'][-1]['bridges']] == [bid] and M['hello'][-1]['me']['can_command'] is False
            # (durum yayını ayrı TestClient = ayrı olay döngüsü olduğundan burada beklenmez: hub tek uvicorn döngüsü varsayar; hello.bridges[].drones ile denetlenir)
            assert M['hello'][-1]['bridges'][0]['drones']['1']['lat'] is not None and M['hello'][-1]['bridges'][0]['simulator'] is True
            mw.send_text(json.dumps({'t': 'cmd', 'rid': 'm1', 'bridge_id': bid, 'sysid': 1, 'name': 'arm', 'params': {}}))
            assert pump(mw, M, 5, lambda: 'm1' in M['res']) and M['res']['m1']['ok'] is False and 'yazma izni' in M['res']['m1']['error'], M['res']
            mw.send_text(json.dumps({'t': 'watch', 'sim_id': 99999}))
            assert pump(mw, M, 3, lambda: len(M['err']) >= 2) and 'bulunamadı' in M['err'][-1]['error']
        # --- kapanış: izleyici 'bridge' çevrimdışı alır; SIMS'ten düşer ---
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        assert pump(live, K, 5, lambda: any(b['bridge_id'] == bid and b['online'] is False for b in K['bridge'])), K['bridge']
        assert bid not in drone_hub.SIMS
    assert a.get(f'/api/drone/sim/sessions/{sid}/live').status_code == 404
    print('  harekât paneli köprüsü (§14) testleri geçti')


def gorev_rapor_testleri(a, c1):
    """§18: landing_circle_m doğrulama; Mission Planner yüklemesi algılama (MISSION_ACK → sunucu indirir → route source 'mp' + olay); MISSION_CURRENT →
    mission_cur; görev bitiş noktası (mission_end) kaydı/güncellemesi; crash → drone_sim_events (koordinat, sebep, hedef WP, sapma); SITL çarpışma metni
    tekilleştirme; summary ucu (istatistikler, sapma, güvenlik notu, satır güncellenir); reports listesi + tek rapor + paylaşım; yetki; kapanışta özet."""
    from app import db, flightsim_hub, flightsim_mission
    from pymavlink.dialects.v20 import ardupilotmega as D
    S = '/api/drone/sim/sessions'
    # --- birim: bitiş noktası ve mesafe ---
    assert abs(flightsim_mission.mesafe_m(39.925, 32.837, 39.926, 32.837) - 111.2) < 1.0
    assert flightsim_mission.gorev_bitis([{'seq': 2, 'cmd': 16, 'lat': 1.0, 'lon': 2.0, 'alt_rel': 40}, {'seq': 3, 'cmd': 20, 'lat': 1.0, 'lon': 2.0}], {'lat': 9.0, 'lon': 8.0}) == {'lat': 9.0, 'lon': 8.0, 'alt_rel': 0.0, 'cmd': 20, 'seq': 3}
    assert flightsim_mission.gorev_bitis([{'seq': 1, 'cmd': 21, 'lat': 1.0, 'lon': 2.0, 'alt_rel': 0}])['cmd'] == 21 and flightsim_mission.gorev_bitis([]) is None
    assert flightsim_hub.rota_noktalari([{'seq': 0, 'command': 16, 'x': 10, 'y': 20, 'z': 5, 'frame': 6}], offset=1) == [{'seq': 1, 'cmd': 16, 'lat': 1e-6, 'lon': 2e-6, 'alt': 5.0, 'alt_rel': 5.0, 'frame': 6}]
    # --- doğrulama ---
    assert a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'landing_circle_m': 5}}).status_code == 400
    assert a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'landing_circle_m': 'on'}}).status_code == 400
    assert ok(a.get('/api/drone/sim/meta'))['world_defaults']['landing_circle_m'] == 30
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'landing_circle_m': 60}}), 201)
    sid = s['id']
    assert s['world']['landing_circle_m'] == 60 and s['mission'] == {'source': None, 'home': {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}, 'current': None, 'end': None, 'landing_circle_m': 60.0}, s['mission']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    token = a.cookies.get(auth.COOKIE)
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hh = json.loads(ws.receive_text())
        assert hh['t'] == 'hello' and hh['session']['mission']['landing_circle_m'] == 60
        # --- Mission Planner yüklemesi: sahte kipte SITL görevi bellekte; SITL'in MP'ye yolladığı MISSION_ACK (hedef bileşen 190) ayrıştırıcıdan geçer ---
        ses._sahte_gorev = [{'seq': 0, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 399260000, 'y': 328380000, 'z': 40.0},
                            {'seq': 1, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 399270000, 'y': 328390000, 'z': 50.0},
                            {'seq': 2, 'frame': 6, 'command': 21, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0, 'x': 399280000, 'y': 328400000, 'z': 0.0}]
        arac = D.MAVLink(None, srcSystem=1, srcComponent=1)
        ses.loop.call_soon_threadsafe(ses._isle, arac.mission_ack_encode(255, 190, 0, 0))
        rt = ws_bekle(ws, lambda m: m['t'] == 'route', 4)
        assert rt and rt['source'] == 'mp' and [p['seq'] for p in rt['points']] == [1, 2, 3] and rt['points'][2]['cmd'] == 21, rt
        assert rt['end'] == {'lat': 39.928, 'lon': 32.84, 'alt_rel': 0.0, 'cmd': 21, 'seq': 3, 'alt_msl': 900.0}, rt['end']   # LAND → o konum, yer seviyesi
        ev = ws_bekle(ws, lambda m: m['t'] == 'event' and 'Mission Planner' in m['text'], 3)
        assert ev and ev['text'] == "Mission Planner'dan görev yüklendi: 3 nokta" and ev['severity'] == 6, ev
        g = ok(a.get(f'{S}/{sid}'))
        assert g['mission']['source'] == 'mp' and g['mission']['end']['cmd'] == 21 and len(g['route']) == 3
        # ikinci ACK hızlıca: indirme tekrarlanmaz (tek görev); bize gelen ACK (bileşen 191) tetiklemez
        ses.loop.call_soon_threadsafe(ses._isle, arac.mission_ack_encode(255, 191, 0, 0))
        assert ws_bekle(ws, lambda m: m['t'] == 'route', 1.2) is None
        # MISSION_CURRENT → mission_cur yayını, aktif WP
        ses.loop.call_soon_threadsafe(ses._isle, arac.mission_current_encode(2, 4, 0, 0))
        mc = ws_bekle(ws, lambda m: m['t'] == 'mission_cur', 3)
        assert mc and mc['seq'] == 2 and mc['total'] == 4 and ses.gorev.mission_seq == 2, mc
        # mission_end satırı yazıldı; görev değişince aynı satır güncellenir
        def satirlar(tur):
            with db.connect() as conn:
                return db.rows(conn.execute('SELECT * FROM drone_sim_events WHERE session_id = ? AND type = ? ORDER BY id', (sid, tur)))
        assert bekle(lambda: len(satirlar('mission_end')) == 1, 3)
        me = satirlar('mission_end')[0]
        assert me['lat'] == 39.928 and me['lon'] == 32.84 and me['alt_rel'] == 0.0 and json.loads(me['detail'])['source'] == 'mp' and me['owner_id'] == 1, dict(me)
        ses._sahte_gorev = ses._sahte_gorev[:2]
        ses.loop.call_soon_threadsafe(ses._isle, arac.mission_ack_encode(255, 190, 0, 0))
        rt = ws_bekle(ws, lambda m: m['t'] == 'route', 4)
        assert rt and len(rt['points']) == 2 and rt['end']['alt_rel'] == 50.0 and rt['end']['seq'] == 2, rt
        assert bekle(lambda: len(satirlar('mission_end')) == 1 and satirlar('mission_end')[0]['alt_rel'] == 50.0 and satirlar('mission_end')[0]['id'] == me['id'], 3), satirlar('mission_end')
        # --- uçuş: kalkış → birkaç saniye → crash (3B algılaması: kind terrain, hız) ---
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 30}}))
        assert ws_bekle(ws, lambda m: m['t'] == 'tele' and m['armed'] and m['alt_rel'] > 3, 6)
        ws_bekle(ws, lambda m: False, 1.2)   # 1 Hz iz örnekleri (kuyruk okunarak beklenir: 50 Hz tele crash çerçevesini düşürmesin)
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'crash', 'params': {'kind': 'terrain', 'speed': 11.5}}))
        cr = ws_bekle(ws, lambda m: m['t'] == 'crash', 3)
        assert cr and cr['reason'] == 'terrain' and cr['speed'] == 11.5 and cr['alt_rel'] > 3 and cr['target_seq'] == 2 and cr['mission_end']['seq'] == 2 and cr['deviation_m'] > 50, (cr, ses.gorev.crashes, satirlar('crash'))
        assert bekle(lambda: len(satirlar('crash')) == 1, 3)
        c = satirlar('crash')[0]
        assert c['speed'] == 11.5 and c['lat'] and c['alt_rel'] > 3 and json.loads(c['detail'])['reason'] == 'terrain', dict(c)
        # SITL metni aynı çarpışma (5 sn içinde): yeni satır yok, metin eklenir
        ses.loop.call_soon_threadsafe(ses._isle, arac.statustext_encode(2, b'SIM Hit ground at 9.800000 m/s'))
        ws_bekle(ws, lambda m: False, 0.5)
        assert len(satirlar('crash')) == 1 and ses.gorev.crashes[0]['sitl_text'].startswith('SIM Hit ground') and len(ses.gorev.crashes) == 1
        # --- özet ---
        o = ok(a.get(f'{S}/{sid}/summary'))
        assert o['id'] and o['session_id'] == sid and o['session']['type'] == 'multirotor' and o['session']['landing_circle_m'] == 60 and o['session']['center']['name'] == 'Test Merkezi', o['session']
        f = o['flight']
        assert f['duration_s'] >= 1 and f['max_agl'] > 3 and f['arm_count'] >= 1 and f['max_speed'] >= 0 and 'GUIDED' in f['modes'] and f['batt']['first_v'] and len(o['track']) >= 1, f
        assert o['mission']['source'] == 'mp' and o['mission']['count'] == 2 and o['mission']['completed'] == 1 and o['mission']['end']['seq'] == 2, o['mission']
        assert o['crash']['reason'] == 'terrain' and o['crash_count'] == 1
        d = o['deviation']
        assert d['from'] == 'crash' and d['in_circle'] is False and abs(d['dist_m'] - flightsim_mission.mesafe_m(o['crash']['lat'], o['crash']['lon'], 39.927, 32.839)) < 0.2 and d['dz_m'] == round(o['crash']['alt_rel'] - 50.0, 1), d
        assert o['safety']['code'] == 'crash_deviation' and 'sapma' in o['safety_note'] and str(round(d['dist_m'])) in o['safety_note'], o['safety_note']
        o2 = ok(a.get(f'{S}/{sid}/summary'))
        assert o2['id'] == o['id'] and len(satirlar('summary')) == 1   # tek satır, güncellenir
        # --- raporlar ---
        rs = ok(a.get('/api/drone/sim/reports?limit=5'))['items']
        assert rs and rs[0]['id'] == o['id'] and rs[0]['crash'] is True and rs[0]['deviation_m'] == d['dist_m'] and rs[0]['type_name'] == 'Multikopter' and rs[0]['owner_name'], rs[0]
        r1 = ok(a.get(f"/api/drone/sim/reports/{o['id']}"))
        assert r1['id'] == o['id'] and r1['crash']['reason'] == 'terrain' and r1['saved_at']
        assert a.get('/api/drone/sim/reports/999999').status_code == 404
        # yetki: salt okuyan görür, paylaşamaz; paylaşım → feed_posts (sahip adına) + metin
        assert ok(mon.get('/api/drone/sim/reports'))['items'][0]['id'] == o['id'] and ok(mon.get(f"/api/drone/sim/reports/{o['id']}"))['id'] == o['id']
        assert mon.post(f"/api/drone/sim/reports/{o['id']}/share", json={}).status_code == 403
        assert ok(mon.get(f'{S}/{sid}/summary'))['id'] == o['id']
        assert ok(mon.get('/api/drone/sim/reports?mine=1'))['items'] == []
        sh = ok(a.post(f"/api/drone/sim/reports/{o['id']}/share", json={}))
        assert sh['post_id'] and 'Uçuş Simülatörü raporu' in sh['text'] and 'ÇARPIŞMA' in sh['text'] and 'Sapma' in sh['text'], sh['text']
        with db.connect() as conn:
            fp = db.row(conn.execute('SELECT author_id, text FROM feed_posts WHERE id = ?', (sh['post_id'],)))
        assert fp['author_id'] == 1 and fp['text'] == sh['text']
        sh2 = ok(a.post(f"/api/drone/sim/reports/{o['id']}/share", json={'text': 'Flight report (en)'}))
        assert sh2['text'] == 'Flight report (en)'
        # kapanış: özet satırı güncellenir (ended_at dolu)
        ok(a.delete(f'{S}/{sid}'))
        assert ws_bekle(ws, lambda m: m['t'] == 'end', 3)
    assert bekle(lambda: json.loads(satirlar('summary')[0]['detail']).get('ended_at') is not None, 3)
    assert json.loads(satirlar('summary')[0]['detail'])['end_reason'] == 'kapatildi'
    # çarpışma yok + görev: dronun son konumu ↔ bitiş noktası (iniş dairesi içinde)
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    ses._rota_ayarla([{'seq': 1, 'cmd': 16, 'lat': 39.9251, 'lon': 32.837, 'alt': 20.0, 'alt_rel': 20.0}], source='hepgo', total=2)   # ev 11 m uzakta; daire 30 m → yarıçap 15
    o = ok(a.get(f'{S}/{sid}/summary'))
    assert o['crash'] is None and o['deviation']['from'] == 'last' and 10 < o['deviation']['dist_m'] < 12 and o['deviation']['in_circle'] is True and o['safety']['code'] == 'in_circle', o['deviation']
    assert o['mission']['source'] == 'hepgo' and o['mission']['completed'] == 0
    assert a.get(f'{S}/99999/summary').status_code == 404
    ok(a.delete(f'{S}/{sid}'))
    print('  görev çizimi / çarpışma / özet rapor (§18) testleri geçti')


def carpisma_siniflama_testleri(a, c1):
    """§18 sahte çarpışma düzeltmesi: STATUSTEXT sınıflandırma; yerde/yavaş "SIM Hit ground" → kayıt yok; sert temas havada → `sitl_hit`; ArduPlane
    "Crash: Disarming" → sarı uyarı + `warning` satırı (crash değil); 3B arazi adayı: SITL teyidiyle `terrain` tek kayıt, teyitsiz düşer; bina kesin;
    30 sn tekilleştirme."""
    import asyncio
    from app import db, flightsim_mission as fm
    S = fm.statustext_sinifla
    assert S('SIM Hit ground at 0.325623 m/s') == ('sitl_hit', 0.325623)
    assert S('SIM Hit ground at 12.30095 m/s') == ('sitl_hit', 12.30095)
    assert S('SIM Hit ground at -4.5 m/s') == ('sitl_hit', 4.5)
    assert S('Crash: Disarming') == ('autopilot_detect', None) and S('Crash detected') == ('autopilot_detect', None)
    assert S('Flare crash detected: speed=3.2') == ('autopilot_detect', None)
    assert S('Crash check disabled') == (None, None) and S('Saved crash_dump.bin') == (None, None) and S('Arming motors') == (None, None)
    assert S('PreArm: no crash') == (None, None) and S('') == (None, None)
    assert fm.CARPISMA_TEKIL_S == 30.0 and fm.SITL_HIT_HIZ_MIN == 3.0 and fm.ADAY_TEYIT_S == 3.0

    class Oturum:   # GorevIzleyici'nin kullandığı SimSession yüzü (gerçek SITL kipi: sahte=None)
        def __init__(self):
            self.id = 9999; self.owner = {'id': 1}; self.sahte = None; self.route = []; self.world = {}; self.center = {'lat': 39.925, 'lon': 32.837, 'alt': 900}
            self.tele = {'lat': 39.925, 'lon': 32.837, 'alt_msl': 900.0, 'alt_rel': 0.0, 'groundspeed': 0.3, 'mode': 'MANUAL', 'armed': True, 'home': None}
            self.yayin, self.olaylar, self.disarm = [], [], 0
            self.loop = asyncio.new_event_loop()
        def _yay(self, m): self.yayin.append(m)
        def _olay(self, t, sev=6): self.olaylar.append((t, sev))
        def zorla_disarm(self): self.disarm += 1

    o = Oturum(); g = fm.GorevIzleyici(o)
    g._kaydet = lambda *a, **k: g.__dict__.setdefault('kayitlar', []).append((a[0], a[7]))   # DB yerine bellek
    # yerde durağan / taksi: PROD oturum 9 metinleri → kayıt YOK
    for h in (0.229691, 0.325623, 1.504598, 2.507468, 4.340408):   # 4,34 ≥ 3 ama yerde (AGL 0, yer hızı 0,3) → yine yok
        assert g.sitl_temas(h, f'SIM Hit ground at {h} m/s') is None
    o.tele.update(alt_rel=0.2, groundspeed=2.9)
    assert g.sitl_temas(2.9, 'SIM Hit ground at 2.9 m/s') is None
    assert g.crashes == [] and o.yayin == [] and o.disarm == 0
    # normal iniş (havadan, düşey 1,2 m/s, yer hızı 14): çarpışma değil
    o.tele.update(alt_rel=0.0, groundspeed=14.0)
    assert g.sitl_temas(1.2, 'SIM Hit ground at 1.2 m/s') is None and g.crashes == []
    # sert temas (düşey 9,8, yer hızı 21) → sitl_hit, zorla disarm, yayın
    o.tele.update(alt_rel=-0.5, groundspeed=21.0)
    c = g.sitl_temas(9.8, 'SIM Hit ground at 9.800000 m/s')
    assert c and c['reason'] == 'sitl_hit' and c['speed'] == 21.0 and c['sitl_vz'] == 9.8 and c['sitl_text'].startswith('SIM Hit') and o.disarm == 1
    assert o.yayin[-1]['t'] == 'crash' and o.yayin[-1]['reason'] == 'sitl_hit' and g.kayitlar[-1][0] == 'crash'
    # 30 sn içinde ikinci temas (yerde sürüklenme) → yeni kayıt yok
    assert g.sitl_temas(5.0, 'SIM Hit ground at 5.0 m/s') is c and len(g.crashes) == 1 and o.disarm == 1
    g.crashes[-1]['t'] -= 31
    # ArduPlane yazılımsal tespit → warning, crash değil; 30 sn tekil
    w = g.otopilot_tespit('Crash: Disarming')
    assert w and w['reason'] == 'autopilot_detect' and g.kayitlar[-1][0] == 'warning' and o.yayin[-1]['t'] == 'warn' and o.olaylar[-1][1] == 4 and 'Otopilot' in o.olaylar[-1][0]
    assert g.otopilot_tespit('Crash detected') is None and len(g.warnings) == 1 and len(g.crashes) == 1
    # 3B arazi adayı: gerçek SITL kipinde kayıt yok, disarm yok; SITL teması 0,5 sn sonra → terrain kaydı (hız = 3B hızı), tek kayıt, disarm
    o.tele.update(alt_rel=30.0, groundspeed=25.0)
    async def aday_senaryo():
        k, d = g.ucboyut_bildirim('terrain', 25.4, {'dz': -0.4})
        assert k is None and d is False and g._aday and len(g.crashes) == 1
        await asyncio.sleep(0.5)
        c2 = g.sitl_temas(0.9, 'SIM Hit ground at 0.9 m/s')   # düşey yavaş olsa da aday teyidi
        assert c2 and c2['reason'] == 'terrain' and c2['speed'] == 25.4 and c2['sitl_vz'] == 0.9 and len(g.crashes) == 2 and o.disarm == 2 and g._aday is None
        await asyncio.sleep(0.1)   # iptal edilen düşürme görevi
        g.crashes[-1]['t'] -= 31
        # teyitsiz aday → ADAY_TEYIT_S sonra düşer, sarı olay, kayıt yok
        fm.ADAY_TEYIT_S = 0.3
        try:
            k, d = g.ucboyut_bildirim('terrain', 12.0, {})
            assert k is None and d is False
            await asyncio.sleep(0.6)
        finally:
            fm.ADAY_TEYIT_S = 3.0
        assert g._aday is None and len(g.crashes) == 2 and 'doğrulanmadı' in o.olaylar[-1][0] and o.olaylar[-1][1] == 4
        # bina: kesin
        k, d = g.ucboyut_bildirim('building', 18.0, {})
        assert k and d is True and k['reason'] == 'building' and len(g.crashes) == 3
        # sahte kip: arazi doğrudan
        g.crashes[-1]['t'] -= 31; o.sahte = object()
        k, d = g.ucboyut_bildirim('terrain', 7.0, {})
        assert k and d is True and k['reason'] == 'terrain'
    o.loop.run_until_complete(aday_senaryo())
    oz_crash = [c['reason'] for c in g.crashes]
    assert oz_crash == ['sitl_hit', 'terrain', 'building', 'terrain'] and len(g.warnings) == 1
    o.loop.close()
    # REST: sahte kipte `cmd crash` kind building → {'crash': True}; SITL metni yerde yavaş → kayıt yok
    S_ = '/api/drone/sim/sessions'
    s = ok(a.post(S_, json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S_}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    from pymavlink.dialects.v20 import ardupilotmega as D
    arac = D.MAVLink(None, srcSystem=1, srcComponent=1)
    for _ in range(3):
        ses.loop.call_soon_threadsafe(ses._isle, arac.statustext_encode(6, b'SIM Hit ground at 0.325623 m/s'))
    ses.loop.call_soon_threadsafe(ses._isle, arac.statustext_encode(2, b'Crash: Disarming'))
    time.sleep(0.6)
    with db.connect() as conn:
        rows = db.rows(conn.execute('SELECT type FROM drone_sim_events WHERE session_id = ? ORDER BY id', (sid,)))
    assert [r['type'] for r in rows] == ['warning'] and ses.gorev.crashes == [], rows
    r = ok(a.post(f'{S_}/{sid}/cmd', json={'name': 'crash', 'params': {'kind': 'building', 'speed': 9.0}}))
    assert r == {'ok': True, 'crash': True, 'pending': False}, r
    assert bekle(lambda: len(ses.gorev.crashes) == 1 and ses.gorev.crashes[0]['reason'] == 'building', 2)
    o2 = ok(a.get(f'{S_}/{sid}/summary'))
    assert o2['crash_count'] == 1 and o2['autopilot_detect_count'] == 1 and o2['crash']['reason'] == 'building'
    ok(a.delete(f'{S_}/{sid}'))
    print('  çarpışma sınıflandırma (§18 sahte çarpışma) testleri geçti')


def param_testleri(a, c1, sitl, mon):
    """Kalıcı parametreler (app/drone_params.py; tablo drone_sitl_params): dron kaydıyla açılan oturumda panel `param_set` → kayıt (hepgo, kullanıcı);
    Mission Planner PARAM_SET (UDP ham) + SITL PARAM_VALUE yankısı → kayıt (mp); hariç tutulanlar (SIM_WIND_*, TKOFF_*, LOG_*) kaydedilmez; tabandan
    farklı PARAM_VALUE → sitl; yeniden yüklemede parm içeriği + PARAM_SET yazımı; REST uçları (liste/export/import/sil/sıfırla), yetki."""
    from pymavlink.dialects.v20 import ardupilotmega as D
    from app import db, drone_params, drone_sitl
    S = '/api/drone/sim/sessions'
    pd_ = ok(a.post('/api/drone/drones', json={'name': 'Kalıcı Sanal', 'protocol': 'sanal', 'model': 'Quad X'}))
    md = ok(a.post('/api/drone/drones', json={'name': 'Gerçek', 'protocol': 'mavlink'}))
    P = f"/api/drone/drones/{pd_['id']}/sitl-params"
    # hariç tutma listesi: ön ekler + oturum parametreleri (flightsim'den türetilir)
    assert drone_params.haric_mi('SIM_WIND_SPD') and drone_params.haric_mi('TKOFF_ALT') and drone_params.haric_mi('LOG_BITMASK') and drone_params.haric_mi('STAT_RUNTIME')
    assert drone_params.haric_mi('MAV1_EXTRA1') and drone_params.haric_mi('SR0_POSITION') and drone_params.haric_mi('SERVO3_MIN') and drone_params.haric_mi('SIM_GPS1_ACC') and drone_params.haric_mi('FS_THR_ENABLE') and drone_params.haric_mi('MIS_TOTAL') and drone_params.haric_mi('SIM_SPEEDUP')
    assert not drone_params.haric_mi('WP_RADIUS') and not drone_params.haric_mi('SIM_BATT_VOLTAGE') and not drone_params.haric_mi('WPNAV_SPEED')
    assert drone_params.haric_mi(f'SERVO{flightsim.LAUNCH_SERVO}_FUNCTION') and not drone_params.haric_mi('SERVO9_FUNCTION')
    # flaplar (sabit kanat oturum başlangıcı; dron yapılandırması sayılır → kaydedilir, TKOFF_ ön ekine rağmen)
    assert [a for a, _ in flightsim.FLAP_PARAMLARI] == ['SERVO5_FUNCTION', 'SERVO6_FUNCTION', 'TKOFF_FLAP_PCNT', 'LAND_FLAP_PERCNT']
    assert not any(drone_params.haric_mi(a) for a, _ in flightsim.FLAP_PARAMLARI) and drone_params.haric_mi('TKOFF_ALT')
    r = ok(a.get(P))
    assert r['items'] == [] and r['count'] == 0 and 'STAT_' in r['excluded']['prefixes'] and 'MAV_SYSID' in r['excluded']['names'] and r['can_write'] is True, r
    assert a.get(f"/api/drone/drones/{md['id']}/sitl-params").status_code == 400   # yalnız sanal dron
    assert a.get('/api/drone/drones/999999/sitl-params').status_code == 404
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0   # önceki oturumların TCP'leri kapanmış olmalı
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': pd_['id']}), 201)
    sid, bid = s['id'], -(flightsim.KIMLIK_TABANI + s['id'])
    assert s['params'] == {'tracked': True, 'loaded': 0, 'saved': 0, 'virtual_mount': drone_sitl.sanal_montaj_destegi('multirotor'), 'srv_rev_mask': 0, 'srv_rev_sitl': None,
                           'mount_neutral': [], 'mount_reversed': [], 'motor_skipped': []}, s['params']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    assert ses.param_izleyici is not None and ses.param_izleyici.drone_id == pd_['id']
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5), len(sitl.baglar)
    # (a) panel param_set (hub komutu, REST yolu) → sahte yankı → kayıt hepgo + kullanıcı
    r = ok(a.post('/api/drone/live/cmd', json={'bridge_id': bid, 'name': 'param_set', 'params': {'name': 'WPNAV_SPEED', 'value': 1234}}))
    assert r['ok'] is True, r
    it = bekle(lambda: (lambda x: x if x['count'] == 1 else None)(ok(a.get(P))), 3)
    assert it and it['items'][0]['name'] == 'WPNAV_SPEED' and it['items'][0]['value'] == 1234 and it['items'][0]['source'] == 'hepgo' and it['items'][0]['updated_by'] == 1 and it['items'][0]['updated_by_name'], it
    # hariç: oturum parametresi → kaydedilmez
    ok(a.post('/api/drone/live/cmd', json={'bridge_id': bid, 'name': 'param_set', 'params': {'name': 'SIM_WIND_SPD', 'value': 5}}))
    ok(a.post('/api/drone/live/cmd', json={'bridge_id': bid, 'name': 'param_set', 'params': {'name': 'TKOFF_ALT', 'value': 60}}))
    time.sleep(0.3)
    assert [x['name'] for x in ok(a.get(P))['items']] == ['WPNAV_SPEED']
    # (b) Mission Planner: UDP'den ham PARAM_SET (SITL'e geçer) + sahte SITL'in PARAM_VALUE yankısı → kayıt mp
    gcs_enc = D.MAVLink(None, srcSystem=255, srcComponent=190)
    arac = D.MAVLink(None, srcSystem=1, srcComponent=1)
    gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs.bind(('127.0.0.1', 0)); gcs.settimeout(2)
    once = len(sitl.alinan)
    pset = gcs_enc.param_set_encode(1, 1, b'WP_RADIUS', 123.0, 9).pack(gcs_enc)
    gcs.sendto(pset, ('127.0.0.1', s['udp_port']))
    assert bekle(lambda: len(sitl.alinan) > once and bytes(sitl.alinan).endswith(pset), 3), 'PARAM_SET SITL\'e ham geçmeli'
    assert bekle(lambda: 'WP_RADIUS' in ses.param_izleyici.bekleyen, 2), ses.param_izleyici.bekleyen
    sitl.yaz(arac.param_value_encode(b'WP_RADIUS', 123.0, 9, 900, 17).pack(arac))
    it = bekle(lambda: (lambda x: x if x['count'] == 2 else None)(ok(a.get(P))), 3)
    wr = next(x for x in it['items'] if x['name'] == 'WP_RADIUS')
    assert wr['value'] == 123 and wr['source'] == 'mp' and wr['ptype'] == 9 and wr['updated_by'] is None, wr
    # MP yankısı hariç parametre için → kaydedilmez; açılış param akışı (ilk görülen) taban olur, sonra farklı değer → sitl
    gcs.sendto(gcs_enc.param_set_encode(1, 1, b'LOG_BITMASK', 0.0, 6).pack(gcs_enc), ('127.0.0.1', s['udp_port']))
    arac.seq = 5
    sitl.yaz(arac.param_value_encode(b'LOG_BITMASK', 0.0, 6, 900, 18).pack(arac) + arac.param_value_encode(b'ANGLE_MAX', 3000.0, 6, 900, 19).pack(arac))
    time.sleep(0.4)
    assert ok(a.get(P))['count'] == 2 and ses.param_izleyici.taban.get('ANGLE_MAX') == 3000.0, ses.param_izleyici.taban
    sitl.yaz(arac.param_value_encode(b'ANGLE_MAX', 3000.0, 6, 900, 19).pack(arac))   # değişmedi → kayıt yok
    time.sleep(0.3)
    assert ok(a.get(P))['count'] == 2
    sitl.yaz(arac.param_value_encode(b'ANGLE_MAX', 2600.0, 6, 900, 19).pack(arac))   # tam liste alınmadan niyetsiz fark → kayıt yok (araç kalibrasyonu olabilir)
    time.sleep(0.3)
    assert ok(a.get(P))['count'] == 2 and ses.param_izleyici.taban_tam is False and ses.param_izleyici.param_count == 900
    ses.param_izleyici.tam_liste_isaretle()   # MP param listesi tamamlandı sayılır (900 PARAM_VALUE yerine)
    sitl.yaz(arac.param_value_encode(b'ANGLE_MAX', 2500.0, 6, 900, 19).pack(arac))
    it = bekle(lambda: (lambda x: x if x['count'] == 3 else None)(ok(a.get(P))), 3)
    assert next(x for x in it['items'] if x['name'] == 'ANGLE_MAX')['source'] == 'sitl'
    assert ok(a.get(f'{S}/{sid}'))['params']['saved'] == 3
    # yeniden yükleme: parm içeriği (HEPGO varsayılanlarından sonra) + reset sonrası PARAM_SET yazımı; yankılar yeniden kaydedilmez
    rows = drone_params.yukle(pd_['id'])
    parm = drone_sitl.parm_metni(1, False, drone_params.parm_satirlari(rows))
    assert parm.index('MAV_SYSID 1') < parm.index('LOG_BACKEND_TYPE 0') < parm.index('# HEPGO kayitli') < parm.index('ANGLE_MAX 2500') < parm.index('WPNAV_SPEED 1234') < parm.index('WP_RADIUS 123'), parm
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'reset'}))
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['params']['loaded'] == 3, 3), ok(a.get(f'{S}/{sid}'))['params']
    once = len(sitl.alinan)
    ses.loop.call_soon_threadsafe(ses._kayitli_yaz)
    assert bekle(lambda: len(sitl.alinan) >= once + 3 * 25, 3)
    pr = D.MAVLink(None); pr.robust_parsing = True
    yazilan = {str(m.param_id).rstrip('\x00'): (m.param_value, m.param_type) for m in (pr.parse_buffer(bytes(sitl.alinan[once:])) or []) if m.get_type() == 'PARAM_SET'}
    assert yazilan == {'ANGLE_MAX': (2500.0, 6), 'WP_RADIUS': (123.0, 9), 'WPNAV_SPEED': (1234.0, 9)}, yazilan
    eski = {x['name']: x['updated_at'] for x in ok(a.get(P))['items']}
    time.sleep(1.1)
    sitl.yaz(arac.param_value_encode(b'WP_RADIUS', 123.0, 9, 900, 17).pack(arac))   # yükleme yankısı
    time.sleep(0.4)
    assert {x['name']: x['updated_at'] for x in ok(a.get(P))['items']} == eski, 'yükleme yankısı yeniden kaydetmemeli'
    assert ses.param_izleyici.yukleme == {'ANGLE_MAX', 'WPNAV_SPEED'}
    # tele.servo_fn: SERVOn_FUNCTION yankıları (3B flap eşlemesi); kayıtlı SERVO5_FUNCTION varsa oturum flap başlangıcını yazmaz
    sitl.yaz(arac.param_value_encode(b'SERVO5_FUNCTION', 3.0, 2, 900, 30).pack(arac) + arac.param_value_encode(b'SERVO9_FUNCTION', 4.0, 2, 900, 31).pack(arac))
    assert bekle(lambda: ses.tele['servo_fn'][4] == 3, 2) and ses.tele['servo_fn'] == [None, None, None, None, 3, None, None, None], ses.tele['servo_fn']
    assert ses.flap_parametreleri() == list(flightsim.FLAP_PARAMLARI)
    ses.kayitli_params = ses.kayitli_params + [{'name': 'SERVO5_FUNCTION', 'value': 0.0, 'ptype': 2}]
    assert [a for a, _ in ses.flap_parametreleri()] == ['SERVO6_FUNCTION', 'TKOFF_FLAP_PCNT', 'LAND_FLAP_PERCNT']
    ses.kayitli_params = ses.kayitli_params[:-1]
    # REST: export (.param), tek sil, import (yorum/boşluk/virgül; hariç ve bozuk atlanır), sıfırla, yetki
    ex = a.get(f'{P}/export')
    assert ex.status_code == 200 and ex.headers['content-disposition'] == f'attachment; filename="{pd_["code"]}.param"', ex.headers
    assert ex.text.splitlines()[0].startswith('#NOTE: HEPGO') and 'WP_RADIUS,123' in ex.text and 'ANGLE_MAX,2500' in ex.text and 'WPNAV_SPEED,1234' in ex.text, ex.text
    ok(a.delete(f'{P}/WP_RADIUS'))
    assert a.delete(f'{P}/WP_RADIUS').status_code == 404
    assert [x['name'] for x in ok(a.get(P))['items']] == ['ANGLE_MAX', 'WPNAV_SPEED']
    im = ok(a.post(f'{P}/import', json={'text': '#NOTE: MP\nRTL_ALT,150\nSIM_WIND_SPD,3\nBOZUK\nWPNAV_SPEED 900\nlog_bitmask\t0\nFS_THR_ENABLE,1\nABC,xx\n'}))
    assert im['imported'] == 2 and im['skipped_count'] == 5 and im['count'] == 3 and {x['reason'] for x in im['skipped']} == {'hariç', 'biçim', 'değer'}, im
    it = ok(a.get(P))['items']
    assert {x['name']: x['value'] for x in it} == {'ANGLE_MAX': 2500, 'RTL_ALT': 150, 'WPNAV_SPEED': 900} and all(x['source'] == 'hepgo' for x in it if x['name'] != 'ANGLE_MAX'), it
    assert a.post(f'{P}/import', json={'text': 'x' * 2_000_001}).status_code == 400
    # --- montaj parametreleri (SERVOn_REVERSED; §20.1 sanal montaj): kayıt + .param dışa aktarımı gerçek değer (1); SITL ikilisi SIM_SRV_REV tanıyorsa
    #     (sanal_montaj_destegi True) değer aynen + SIM_SRV_REV maskesi; tanımıyorsa (eski ikili) 0 + sarı uyarı; oturum içi değişiklikte maske anında;
    #     RCn_REVERSED montaj sayılmaz (kumanda yönü; olduğu gibi gider) ---
    assert drone_params.montaj_mi('SERVO1_REVERSED') and drone_params.montaj_mi('servo16_reversed') and not drone_params.montaj_mi('SERVO17_REVERSED')
    assert not drone_params.montaj_mi('RC1_REVERSED') and not drone_params.montaj_mi('SERVO1_FUNCTION') and not drone_params.montaj_mi('SERVO0_REVERSED')
    assert drone_params.montaj_kanal('SERVO12_REVERSED') == 12 and drone_params.montaj_kanal('RC1_REVERSED') is None
    assert drone_params.srv_rev_mask([{'name': 'SERVO1_REVERSED', 'value': 1}, {'name': 'SERVO2_REVERSED', 'value': 0}, {'name': 'SERVO3_REVERSED', 'value': 1.0}, {'name': 'RC1_REVERSED', 'value': 1}]) == 0b101
    assert drone_params.srv_rev_mask({'SERVO16_REVERSED': 1, 'SERVO1_REVERSED': 'x'}) == 1 << 15
    # motor (ESC) kanalı dışlaması: ArduPilot motor çıkışına REVERSED uygulamaz → bit yok (kayıtlı FUNCTION motor kodu ya da tipin varsayılan motor kanalı)
    atl = []
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 1}, 'multirotor', atl) == 0 and atl == ['SERVO1_REVERSED']
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 1, 'SERVO1_FUNCTION': 4}, 'multirotor') == 1 and drone_params.srv_rev_mask({'SERVO9_REVERSED': 1}, 'multirotor') == 1 << 8
    assert drone_params.srv_rev_mask({'SERVO5_REVERSED': 1, 'SERVO4_REVERSED': 1}, 'vtol') == 8 and drone_params.srv_rev_mask({'SERVO1_REVERSED': 1}, 'helikopter') == 1
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 1, 'SERVO1_FUNCTION': 33}, 'sabit_kanat') == 0 and drone_params.srv_rev_mask({'SERVO3_REVERSED': 1, 'SERVO3_FUNCTION': 70}, 'sabit_kanat') == 4
    # SITL modelinin nötr montajı (plane-elevon REV 1/1, plane-vtail REV2 1): etkin değer = kayıt ?? düzen seti ?? 0; bit = etkin XOR nötr
    from app import flightsim as _fs
    assert _fs.sitl_notr_mask('-elevon') == 3 and _fs.sitl_notr_mask('-vtail') == 2 and _fs.sitl_notr_mask('') == 0
    ev = {'SERVO1_REVERSED': 1.0, 'SERVO2_REVERSED': 1.0, 'SERVO4_REVERSED': 0.0}
    assert drone_params.srv_rev_mask({'SERVO1_FUNCTION': 78, 'SERVO2_FUNCTION': 77}, 'sabit_kanat', None, 3, ev) == 0          # kayıtta REVERSED yok → düzen seti (nötr) → 0
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 0, 'SERVO2_REVERSED': 0}, 'sabit_kanat', None, 3, ev) == 3             # CAYMAZ 78/77 + REV 0/0 → fizik iki kanalı yansıtır
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 1, 'SERVO2_REVERSED': 0}, 'sabit_kanat', None, 3, ev) == 2
    assert drone_params.srv_rev_mask({'SERVO2_REVERSED': 0}, 'sabit_kanat', None, 2, {'SERVO2_REVERSED': 1.0}) == 2               # V-kuyruk
    assert drone_params.srv_rev_mask({'SERVO1_REVERSED': 1}, 'sabit_kanat', None, 0, {'SERVO1_REVERSED': 0.0}) == 1               # klasik: eski davranış
    assert drone_params.sitl_kayitlari([{'name': 'SERVO1_REVERSED', 'value': 0}], True, 'sabit_kanat', 3, ev)[1]['mask'] == 1
    _, bm = drone_params.sitl_kayitlari([{'name': 'SERVO1_REVERSED', 'value': 1.0}], True, 'multirotor')
    assert bm == {'virtual_mount': True, 'mask': 0, 'neutral': [], 'reversed': [], 'motor_skipped': ['SERVO1_REVERSED'], 'sensor_skipped': []} and 'motor (ESC)' in drone_params.montaj_olayi(bm)[0] and drone_params.montaj_olayi(bm)[1] == 6, bm
    assert not drone_params.haric_mi('SERVO1_REVERSED') and not drone_params.haric_mi('RC1_REVERSED')   # kaydedilir
    assert drone_params.haric_mi('SIM_SRV_REV') and not drone_params.kaydet(pd_['id'], 'SIM_SRV_REV', 3.0)   # üretilen maske kalıcı kayda girmez
    destek_orj = drone_sitl.sanal_montaj_destegi
    assert destek_orj('multirotor') in (True, False)
    drone_sitl.sanal_montaj_destegi = lambda tip: False   # eski (resmi) ikili
    try:
        # dron 'Quad X' (multirotor): SERVO1 varsayılan motor kanalı → bit için SERVO1_FUNCTION=4 (servo) kaydı da içe aktarılır
        assert ok(a.post(f'{P}/import', json={'text': 'SERVO1_REVERSED,1\nSERVO2_REVERSED,0\nRC1_REVERSED,1\nSERVO1_FUNCTION,4\n'}))['imported'] == 4
        r = ok(a.get(P))
        assert r['excluded']['mount'] == 'SERVO1..16_REVERSED' and r['excluded']['mount_badge'] == 'montaj (sanal uçakta aynen uygulanır)' and r['excluded']['mount_badge_neutral'] == 'montaj (simülasyonda nötr)', r['excluded']
        assert r['mount'] == {'virtual_mount': False, 'srv_rev_mask': 1, 'motor_skipped': [], 'badge': 'montaj (simülasyonda nötr)', 'note': drone_params.MONTAJ_DESTEK_YOK} and 'options' not in r, r
        mnt = {x['name']: x['mount'] for x in r['items']}
        assert mnt == {'ANGLE_MAX': False, 'RC1_REVERSED': False, 'RTL_ALT': False, 'SERVO1_FUNCTION': False, 'SERVO1_REVERSED': True, 'SERVO2_REVERSED': True, 'WPNAV_SPEED': False}, mnt
        rows = drone_params.yukle(pd_['id'])
        # sanal montaj destekli ikili: değer aynen + SIM_SRV_REV (INT32) son satır; parm satırlarında SIM_SRV_REV hariç listesine rağmen yazılır
        sitl_r, bilgi = drone_params.sitl_kayitlari(rows, True)
        assert bilgi == {'virtual_mount': True, 'mask': 1, 'neutral': [], 'reversed': ['SERVO1_REVERSED'], 'motor_skipped': [], 'sensor_skipped': []}, bilgi
        assert sitl_r[-1] == {'name': 'SIM_SRV_REV', 'value': 1.0, 'ptype': 6} and {x['name']: x['value'] for x in sitl_r}['SERVO1_REVERSED'] == 1.0
        satir = drone_params.parm_satirlari(rows, True)
        assert 'SERVO1_REVERSED 1' in satir and 'SERVO2_REVERSED 0' in satir and 'RC1_REVERSED 1' in satir and satir[-1] == 'SIM_SRV_REV 1', satir
        assert drone_params.montaj_olayi(bilgi) == ('SERVO1_REVERSED: sanal uçakta servo montajı da ters (SIM_SRV_REV = 1) — gerçek uçakla aynı davranış', 6)
        # eski ikili: 0'a çekilir, SIM_SRV_REV yok, sarı olay
        sitl_r, bilgi = drone_params.sitl_kayitlari(rows, False)
        assert bilgi == {'virtual_mount': False, 'mask': 0, 'neutral': ['SERVO1_REVERSED'], 'reversed': [], 'motor_skipped': [], 'sensor_skipped': []}, bilgi
        assert {x['name']: x['value'] for x in sitl_r}['SERVO1_REVERSED'] == 0.0 and all(x['name'] != 'SIM_SRV_REV' for x in sitl_r) and {x['name']: x['value'] for x in sitl_r}['RC1_REVERSED'] == 1.0
        satir = drone_params.parm_satirlari(rows, False)
        assert 'SERVO1_REVERSED 0' in satir and 'SERVO1_REVERSED 1' not in satir and not any(x.startswith('SIM_SRV_REV') for x in satir), satir
        assert drone_params.montaj_olayi(bilgi)[1] == 4 and drone_params.MONTAJ_DESTEK_YOK in drone_params.montaj_olayi(bilgi)[0]
        assert drone_params.montaj_olayi({'virtual_mount': True, 'mask': 0, 'neutral': [], 'reversed': [], 'motor_skipped': []}) is None
        ex = a.get(f'{P}/export').text
        assert 'SERVO1_REVERSED,1' in ex and 'SERVO2_REVERSED,0' in ex and '#NOTE: SERVO1_REVERSED, SERVO2_REVERSED: montaj parametresi' in ex and 'SIM_SRV_REV' not in ex.replace('(SIM_SRV_REV)', ''), ex
        assert drone_params.param_ayristir(ex)[0].count(('SERVO1_REVERSED', 1.0)) == 1   # yorum satırı MP ayrıştırmasını bozmaz
        # oturum, eski ikili: reset → parm + PARAM_SET'te 0, SIM_SRV_REV yazılmaz, sarı olay; kayıt korunur
        olaylar = []
        eski_olay = ses._olay
        ses._olay = lambda t, s=6: (olaylar.append((str(t), int(s))), eski_olay(t, s))
        ses.param_izleyici.bildir = ses._olay   # izleyici bağlı metodu tutar; sarmalayıcıyı ona da ver
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'reset'}))
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['params']['loaded'] == 7, 3), ok(a.get(f'{S}/{sid}'))['params']
        g = ok(a.get(f'{S}/{sid}'))['params']
        assert g['virtual_mount'] is False and g['mount_neutral'] == ['SERVO1_REVERSED'] and g['mount_reversed'] == [] and g['srv_rev_mask'] == 0 and g['srv_rev_sitl'] is None, g
        assert ses.param_izleyici.sanal_montaj is False and ses.param_izleyici.srv_rev_mask is None
        parm = drone_sitl.parm_metni(1, False, drone_params.parm_satirlari(ses.kayitli_params, ses.sanal_montaj))
        assert 'SERVO1_REVERSED 0' in parm and 'RC1_REVERSED 1' in parm and 'SERVO1_REVERSED 1' not in parm and 'SIM_SRV_REV' not in parm, parm
        once = len(sitl.alinan)
        ses.loop.call_soon_threadsafe(ses._kayitli_yaz)
        assert bekle(lambda: len(sitl.alinan) >= once + 7 * 25, 3)
        yazilan = {str(m.param_id).rstrip('\x00'): m.param_value for m in (pr.parse_buffer(bytes(sitl.alinan[once:])) or []) if m.get_type() == 'PARAM_SET'}
        assert yazilan['SERVO1_REVERSED'] == 0.0 and yazilan['SERVO2_REVERSED'] == 0.0 and yazilan['RC1_REVERSED'] == 1.0 and 'SIM_SRV_REV' not in yazilan, yazilan
        assert bekle(lambda: any(drone_params.MONTAJ_DESTEK_YOK in t and s == 4 and t.startswith('SERVO1_REVERSED') for t, s in olaylar), 2), olaylar
        assert {x['name']: x['value'] for x in ok(a.get(P))['items']}['SERVO1_REVERSED'] == 1, 'kalıcı kayıt korunur'
        # oturum, yamalı ikili (sanal montaj): reset → değer aynen + SIM_SRV_REV=1 (INT32), bilgi olayı; SITL yankısı → params.srv_rev_sitl
        drone_sitl.sanal_montaj_destegi = lambda tip: True
        olaylar.clear()
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'reset'}))
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['params']['virtual_mount'] is True or None, 3), ok(a.get(f'{S}/{sid}'))['params']
        g = ok(a.get(f'{S}/{sid}'))['params']
        assert g['loaded'] == 7 and g['mount_neutral'] == [] and g['mount_reversed'] == ['SERVO1_REVERSED'] and g['srv_rev_mask'] == 1 and g['srv_rev_sitl'] is None and g['motor_skipped'] == [], g
        parm = drone_sitl.parm_metni(1, False, drone_params.parm_satirlari(ses.kayitli_params, ses.sanal_montaj))
        assert 'SERVO1_REVERSED 1' in parm and 'SIM_SRV_REV 1' in parm and parm.index('SERVO1_REVERSED 1') < parm.index('SIM_SRV_REV 1'), parm
        once = len(sitl.alinan)
        ses.loop.call_soon_threadsafe(ses._kayitli_yaz)
        assert bekle(lambda: len(sitl.alinan) >= once + 8 * 25, 3)
        msgs = [m for m in (pr.parse_buffer(bytes(sitl.alinan[once:])) or []) if m.get_type() == 'PARAM_SET']
        yazilan = {str(m.param_id).rstrip('\x00'): (m.param_value, m.param_type) for m in msgs}
        assert yazilan['SERVO1_REVERSED'][0] == 1.0 and yazilan['SIM_SRV_REV'] == (1.0, 6) and yazilan['RC1_REVERSED'][0] == 1.0, yazilan
        assert ses.param_izleyici.srv_rev_mask == 1 and any('SIM_SRV_REV = 1' in t and s == 6 for t, s in olaylar), olaylar
        assert not any(s == 4 and 'SERVO' in t for t, s in olaylar), olaylar
        assert any(t.startswith('7 kayıtlı parametre yüklendi') for t, _ in olaylar), olaylar   # SIM_SRV_REV kayıt sayılmaz
        sitl.yaz(arac.param_value_encode(b'SIM_SRV_REV', 1.0, 6, 901, 500).pack(arac))
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['params']['srv_rev_sitl'] == 1 or None, 3)
        assert ok(a.get(P))['count'] == 7   # SIM_SRV_REV yankısı kaydedilmedi
        # oturum sırasında MP SERVO9_REVERSED=1 (9: çok rotorluda varsayılan servo kanalı) → kayıt (mp) + SIM_SRV_REV maskesi anında SITL'e (bit0|bit8 = 257) + bilgi olayı
        once = len(sitl.alinan)
        olaylar.clear()
        ses.loop.call_soon_threadsafe(lambda: (ses.param_izleyici.mp_set('SERVO9_REVERSED', 1.0), ses.param_izleyici.param_value('SERVO9_REVERSED', 1.0, 2, 900, 40)))
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['params']['srv_rev_mask'] == 257 or None, 3), ok(a.get(f'{S}/{sid}'))['params']
        assert bekle(lambda: len(sitl.alinan) >= once + 25, 3)
        yazilan = {str(m.param_id).rstrip('\x00'): (m.param_value, m.param_type) for m in (pr.parse_buffer(bytes(sitl.alinan[once:])) or []) if m.get_type() == 'PARAM_SET'}
        assert yazilan == {'SIM_SRV_REV': (257.0, 6)}, yazilan
        assert ses.param_izleyici.srv_rev_mask == 257 and any('SERVO9_REVERSED = 1' in t and 'SIM_SRV_REV = 257' in t and s == 6 for t, s in olaylar), olaylar
        assert {x['name']: (x['value'], x['source']) for x in ok(a.get(P))['items']}['SERVO9_REVERSED'] == (1, 'mp')
        assert ok(a.get(P))['mount'] == {'virtual_mount': True, 'srv_rev_mask': 257, 'motor_skipped': [], 'badge': 'montaj (sanal uçakta aynen uygulanır)', 'note': None}
        # MP SERVO3_REVERSED=1: çok rotorluda SERVO3 varsayılan motor kanalı → kayıt var, bit yok, "motor (ESC)" bilgi olayı; maske 257 kalır
        once = len(sitl.alinan)
        olaylar.clear()
        ses.loop.call_soon_threadsafe(lambda: (ses.param_izleyici.mp_set('SERVO3_REVERSED', 1.0), ses.param_izleyici.param_value('SERVO3_REVERSED', 1.0, 2, 900, 40)))
        assert bekle(lambda: any('SERVO3_REVERSED = 1' in t and 'motor (ESC)' in t and 'SIM_SRV_REV = 257' in t and s == 6 for t, s in olaylar) or None, 3), olaylar
        assert bekle(lambda: len(sitl.alinan) >= once + 25, 3)
        yazilan = {str(m.param_id).rstrip('\x00'): (m.param_value, m.param_type) for m in (pr.parse_buffer(bytes(sitl.alinan[once:])) or []) if m.get_type() == 'PARAM_SET'}
        assert yazilan == {'SIM_SRV_REV': (257.0, 6)} and ok(a.get(P))['mount']['motor_skipped'] == ['SERVO3_REVERSED'], yazilan
        ses._olay = ses.param_izleyici.bildir = eski_olay
        # izleyici tek başına: eski ikili → sarı montaj uyarısı (MP kaynağı); yamalı ikili → srv_rev_yaz(mask) geri çağrısı (0'a dönüş dahil); SITL kaynağı da maskeyi günceller
        uy, yaz = [], []
        izl = drone_params.Izleyici(pd_['id'], lambda t, s: uy.append((t, s)), sanal_montaj=False)
        izl.mp_set('SERVO4_REVERSED', 1.0)
        assert izl.param_value('SERVO4_REVERSED', 1.0, 2, 900, 40) == {'name': 'SERVO4_REVERSED', 'value': 1.0, 'source': 'mp'}
        assert [s for _, s in uy] == [6, 4] and uy[1][0] == izl.montaj_uyarisi('SERVO4_REVERSED') and drone_params.MONTAJ_DESTEK_YOK in uy[1][0], uy
        izl2 = drone_params.Izleyici(pd_['id'], lambda t, s: uy.append((t, s)), sanal_montaj=True, srv_rev_yaz=yaz.append)   # tip yok: motor dışlaması yok
        izl2.hepgo_set('SERVO5_REVERSED', 1.0, 1)
        izl2.param_value('SERVO5_REVERSED', 1.0, 2, 900, 41)
        m5 = 1 | 4 | 8 | 16 | 256   # SERVO1, 3, 4, 5, 9
        assert yaz == [m5] and izl2.srv_rev_mask == m5 and uy[-1][1] == 6 and f'SIM_SRV_REV = {m5}' in uy[-1][0], (yaz, uy[-1])
        izl2.hepgo_set('SERVO5_REVERSED', 0.0, 1)
        izl2.param_value('SERVO5_REVERSED', 0.0, 2, 900, 41)   # 0'a dönüş: maske de düşer
        assert yaz == [m5, m5 - 16] and uy[-1][1] == 6 and f'SIM_SRV_REV = {m5 - 16}' in uy[-1][0], (yaz, uy[-1])
        izl3 = drone_params.Izleyici(pd_['id'], lambda t, s: uy.append((t, s)), sanal_montaj=True, srv_rev_yaz=yaz.append, tip='multirotor')
        izl3.hepgo_set('SERVO4_REVERSED', 1.0, 1)
        izl3.param_value('SERVO4_REVERSED', 1.0, 2, 900, 41)   # multirotor: SERVO1 (FUNCTION 4 kayıtlı) + SERVO9 → 257; SERVO3/4 motor → atlanır
        assert yaz[-1] == 257 and 'motor (ESC)' in uy[-1][0] and uy[-1][1] == 6, (yaz, uy[-1])
        assert ok(a.get(P))['count'] == 11   # 3 + 4 içe aktarım + SERVO9, SERVO3 (MP) + SERVO4, SERVO5 (izleyici)
    finally:
        drone_sitl.sanal_montaj_destegi = destek_orj
    # salt okuyan (drone.sim var, drone.drones yok) → 403
    assert mon.get(P).status_code == 403 and mon.delete(P).status_code == 403
    assert ok(a.delete(P)) == {'ok': True, 'deleted': 11} and ok(a.get(P))['count'] == 0
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action IN ('Sanal dron parametreleri içe aktardı', 'Sanal dron parametrelerini sıfırladı', 'Sanal dron parametresi sildi')").fetchone()[0] == 4
    gcs.close()
    ok(a.delete(f'{S}/{sid}'))
    # dron kaydı seçilmeyen oturumda izleme yok
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s2['params'] == {'tracked': False, 'loaded': 0, 'saved': 0, 'virtual_mount': drone_sitl.sanal_montaj_destegi('multirotor'), 'srv_rev_mask': 0, 'srv_rev_sitl': None,
                            'mount_neutral': [], 'mount_reversed': [], 'motor_skipped': []}
    ok(a.delete(f"{S}/{s2['id']}"))
    print('  kalıcı parametre testleri geçti')


def runs_testleri(a, c1, sitl, mon):
    """§21 Simülasyon Kayıtları (drone_sim_runs): oturum kapanışında satır (özet + .bin + video + params.param + scripts.zip ilişkileri), liste
    filtreleri/sıralama/sayfalama, MASTER yetkisi (params/scripts 403 → master 200), video ucu, silme (dosyalar dahil)."""
    import io
    import zipfile
    from pymavlink.dialects.v20 import ardupilotmega as D
    from app import config, db, drone_sitl, flightsim_runs
    S = '/api/drone/sim/sessions'
    R = '/api/drone/sim/runs'
    once = ok(a.get(R))
    assert set(once) == {'items', 'total', 'page', 'pages', 'per_page', 'facets'} and once['per_page'] == 25, once.keys()
    n0 = once['total']
    assert n0 >= 1 and all(it['mode'] in ('sitl', 'replay') and it['result'] in ('tamam', 'carpisma', 'hata') for it in once['items'])   # önceki testlerin oturumları
    assert any(it['mode'] == 'replay' and it['source_log_id'] for it in once['items']), 'kayıttan oynatma oturumları da kaydedilir'
    hepsi = ok(a.get(R, params={'result': 'carpisma'}))
    assert hepsi['total'] >= 1 and all(it['crash_count'] >= 1 for it in hepsi['items']), 'çarpışmalı oturum (gorev_rapor_testleri) → carpisma'
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'mode': 'procedural', 'launch': {'method': 'ramp', 'angle_deg': 20}}}), 201)
    sid, kimlik = s['id'], flightsim.KIMLIK_TABANI + s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5)
    # (b) son parametreler: sahte SITL'den PARAM_VALUE'lar → param_son; sahte hub param_set → _sahte_params
    arac = D.MAVLink(None, srcSystem=1, srcComponent=1)
    sitl.yaz(arac.param_value_encode(b'WP_RADIUS', 90.0, 9, 20, 3).pack(arac) + arac.param_value_encode(b'ARSPD_FBW_MIN', 12.5, 9, 20, 4).pack(arac))
    assert bekle(lambda: ses.param_son.get('ARSPD_FBW_MIN') == 12.5), ses.param_son
    assert ses._param_count == 20
    ses._sahte_params['RTL_ALT'] = 100.0
    # (c) scriptler: SITL çalışma dizini scripts/ (Lua) + APM/scripts (MP MAVFTP yolu)
    d = drone_sitl.calisma_dizini(kimlik)
    (d / 'scripts').mkdir(parents=True, exist_ok=True)
    (d / 'scripts' / 'hello.lua').write_text('-- test\nreturn update, 1000\n')
    (d / 'APM' / 'scripts').mkdir(parents=True, exist_ok=True)
    (d / 'APM' / 'scripts' / 'mp.lua').write_text('-- mp\n')
    assert [x[0] for x in flightsim_runs.script_dosyalari(d)] == ['scripts/hello.lua', 'APM/scripts/mp.lua']
    # ekran kaydı: start + parça + finish share:false (saklanan) → kapanışta video_rec_id
    rid = ok(a.post(f'{S}/{sid}/rec/start', json={'mime': 'video/webm'}), 201)['rec_id']
    ok(a.put(f'/api/drone/sim/rec/{rid}/chunk?seq=0', content=b'\x1aE\xdf\xa3' + b'v' * 500, headers={'Content-Type': 'application/octet-stream'}))
    ok(a.post(f'/api/drone/sim/rec/{rid}/finish', json={'share': False, 'duration_s': 7}))
    assert ses.video == {'rec_id': rid, 'post_id': None, 'path': None}, ses.video
    # özet raporu (Bitir akışı) → summary_event_id
    sm = ok(a.get(f'{S}/{sid}/summary'))
    # .bin: sahte DataFlash dosyası (bin_testleri kalıbı; oturum rec.bin ile açılmadı → kaydedilmez) — kayıt seçeneği açık ikinci oturumda sınanır
    # (a) kapanış → satır
    ok(a.delete(f'{S}/{sid}'))
    lst = ok(a.get(R))
    assert lst['total'] == n0 + 1
    it = lst['items'][0]
    assert it['session_id'] == sid and it['session_kimlik'] == kimlik and it['mode'] == 'sitl' and it['result'] == 'tamam' and it['crash_count'] == 0, it
    assert it['summary_event_id'] == sm['id'] and it['has_summary'] and it['bin_log_id'] is None and it['play_log_id'] is None, it
    assert it['type'] == 'sabit_kanat' and it['center_id'] == c1['id'] and it['center_name'] == 'Test Merkezi' and it['lat'] == 39.925 and it['owner_id'] == 1, it
    assert it['world']['mode'] == 'procedural' and it['launch']['method'] == 'ramp' and it['launch']['angle_deg'] == 20 and it['model_id'] == 'builtin:caymaz', it
    assert it['video_rec_id'] == rid and it['has_video'] and it['video_post_id'] is None, it
    assert it['params_count'] >= 3 and it['has_params'] and it['params_path'] == f"sim_runs/{it['id']}/params.param", it
    assert it['scripts_count'] == 2 and it['has_scripts'] and it['scripts_path'] == f"sim_runs/{it['id']}/scripts.zip", it
    assert it['started_at'] == s['created_at'] and it['ended_at'] and it['duration_s'] is not None and it['end_reason'] == 'kapatildi' and it['can_delete'] is True
    metin = (config.DATA_DIR / it['params_path']).read_text(encoding='utf-8')
    assert metin.startswith('#NOTE: HEPGO Uçuş Simülatörü oturum #') and 'WP_RADIUS,90\n' in metin and 'ARSPD_FBW_MIN,12.5\n' in metin and 'RTL_ALT,100\n' in metin, metin
    assert ok(a.get(f"{R}/{it['id']}"))['id'] == it['id'] and a.get(f'{R}/999999').status_code == 404
    # MASTER yetkisi: admin (master değil) ve salt okuyan → 403; master → dosyalar
    assert a.get(f"{R}/{it['id']}/params").status_code == 403 and a.get(f"{R}/{it['id']}/scripts").status_code == 403
    assert mon.get(f"{R}/{it['id']}/params").status_code == 403 and mon.get(f"{R}/{it['id']}/scripts").status_code == 403
    assert ok(mon.get(R))['total'] == n0 + 1 and ok(mon.get(f"{R}/{it['id']}"))['can_delete'] is False   # okuma herkese
    config.MASTER_USERNAMES.add('admin@test')
    try:
        r = a.get(f"{R}/{it['id']}/params")
        assert r.status_code == 200 and 'WP_RADIUS,90' in r.text and 'attachment' in r.headers.get('content-disposition', '') and r.headers['content-disposition'].endswith('params.param"'), (r.status_code, r.headers)
        r = a.get(f"{R}/{it['id']}/scripts")
        assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            assert sorted(z.namelist()) == ['APM/scripts/mp.lua', 'scripts/hello.lua'] and z.read('scripts/hello.lua').startswith(b'-- test')
    finally:
        config.MASTER_USERNAMES.discard('admin@test')
    assert a.get(f"{R}/{it['id']}/params").status_code == 403
    # video: saklanan kayıt dosyası
    r = a.get(f"{R}/{it['id']}/video")
    assert r.status_code == 200 and r.content.endswith(b'v' * 500) and r.headers['content-type'].startswith('video/webm'), r.headers
    assert 'attachment' in a.get(f"{R}/{it['id']}/video?dl=1").headers.get('content-disposition', '')
    # filtreler / sıralama / sayfalama / facets
    assert ok(a.get(R, params={'type': 'sabit_kanat'}))['items'][0]['id'] == it['id']
    assert all(x['type'] == 'multirotor' for x in ok(a.get(R, params={'type': 'multirotor'}))['items'])
    assert ok(a.get(R, params={'center_id': c1['id'], 'owner_id': 1, 'result': 'tamam', 'mode': 'sitl'}))['items'][0]['id'] == it['id']
    rp = ok(a.get(R, params={'mode': 'replay'}))
    assert rp['total'] >= 1 and all(x['mode'] == 'replay' for x in rp['items'])
    assert ok(a.get(R, params={'q': 'Test Merkezi'}))['total'] >= 1 and ok(a.get(R, params={'q': 'böyle bir şey yok'}))['total'] == 0
    assert ok(a.get(R, params={'q': str(sid)}))['items'][0]['id'] == it['id']   # oturum numarası
    gun = it['started_at'][:10]
    assert ok(a.get(R, params={'from': gun, 'to': gun}))['total'] == n0 + 1 and ok(a.get(R, params={'from': '2099-01-01'}))['total'] == 0 and ok(a.get(R, params={'to': '2000-01-01'}))['total'] == 0
    asc = [(x['started_at'], x['id']) for x in ok(a.get(R, params={'sort': 'started_at'}))['items']]
    assert asc == sorted(asc), asc   # artan: ikincil anahtar (id) da artan — aynı saniyede açılan oturumlar; satır id'si kapanış sırasıdır, started_at'tan bağımsız
    desc_ = [(x['started_at'], x['id']) for x in ok(a.get(R, params={'sort': '-started_at'}))['items']]
    assert desc_ == sorted(desc_, reverse=True) and desc_[0][1] == it['id'], desc_
    sure = [x['duration_s'] for x in ok(a.get(R, params={'sort': '-duration_s'}))['items']]
    assert sure == sorted(sure, reverse=True)
    tur = [x['type'] for x in ok(a.get(R, params={'sort': 'type'}))['items']]
    assert tur == sorted(tur)
    p = ok(a.get(R, params={'page': 99}))
    assert p['page'] == p['pages'] >= 1 and p['total'] == n0 + 1 and len(p['items']) >= 1 and p['pages'] == (p['total'] + 24) // 25, (p['page'], p['pages'], p['total'])
    if p['pages'] > 1:   # 25'li sayfalama: ilk sayfa dolu, sayfalar kesişmez
        s1 = {x['id'] for x in ok(a.get(R, params={'page': 1}))['items']}
        assert len(s1) == 25 and not (s1 & {x['id'] for x in p['items']})
    assert a.get(R, params={'page': 'x'}).status_code == 400 and a.get(R, params={'center_id': 'y'}).status_code == 400
    fc = lst['facets']
    assert any(c['id'] == c1['id'] and c['name'] == 'Test Merkezi' and c['n'] >= 1 for c in fc['centers']) and any(o['id'] == 1 for o in fc['owners']) and 'sabit_kanat' in fc['types'], fc
    # video_bagla: oturum kapandıktan SONRA paylaşım → satıra post_id + yol
    sh = ok(a.post(f'/api/drone/sim/rec/{rid}/share', json={}))
    g = ok(a.get(f"{R}/{it['id']}"))
    assert g['video_post_id'] == sh['post_id'] and g['video_path'] == sh['path'] and g['video_rec_id'] == rid, g
    r = a.get(f"{R}/{it['id']}/video")   # artık Şirketten Haberler dosyası
    assert r.status_code == 200 and r.content.endswith(b'v' * 500)
    # silme: salt okuyan 403 (DELETE yazma izni); sahip → satır + dizin gider, özet/video kalır
    assert mon.delete(f"{R}/{it['id']}").status_code == 403
    assert (config.DATA_DIR / 'sim_runs' / str(it['id'])).is_dir()
    ok(a.delete(f"{R}/{it['id']}"))
    assert a.get(f"{R}/{it['id']}").status_code == 404 and a.delete(f"{R}/{it['id']}").status_code == 404
    assert not (config.DATA_DIR / 'sim_runs' / str(it['id'])).exists() and ok(a.get(R))['total'] == n0
    assert ok(a.get(f"/api/drone/sim/reports/{sm['id']}"))['id'] == sm['id']   # özet raporu bağımsız kalır
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM feed_posts WHERE id = ?', (sh['post_id'],)).fetchone()[0] == 1
    # .bin kaydı açık oturum (rec.bin) + sahte DataFlash → bin_log_id; analiz sahte dosyada HATA → play_log_id None, .bin indirme ucu çalışır
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'rec': {'bin': True}}), 201)
    assert bekle(lambda: ok(a.get(f"{S}/{s2['id']}"))['state'] == 'HAZIR')
    import tempfile
    binf = os.path.join(tempfile.mkdtemp(), '00000003.BIN')
    with open(binf, 'wb') as f:
        f.write(b'\xa3\x95\x80' + b'\x00' * 4097)
    flightsim.MANAGER.sahte_bin_dosyalari = [binf]
    try:
        r = ok(a.delete(f"{S}/{s2['id']}"))
    finally:
        flightsim.MANAGER.sahte_bin_dosyalari = None
    assert r['bin'] and r['bin']['log_id']
    it2 = ok(a.get(R))['items'][0]
    assert it2['session_id'] == s2['id'] and it2['bin_log_id'] == r['bin']['log_id'] and it2['bin_file_name'] == r['bin']['file_name'] and it2['bin_file_name'].startswith('SIM-'), it2
    rb = a.get(f"{R}/{it2['id']}/bin")
    assert rb.status_code == 200 and len(rb.content) == 4100 and r['bin']['file_name'] in rb.headers.get('content-disposition', ''), rb.headers
    assert ok(a.get(R, params={'q': 'SIM-'}))['items'][0]['id'] == it2['id']   # log adı araması
    bekle(lambda: ok(a.get(f"{R}/{it2['id']}"))['bin_status'] != 'ISLENIYOR' or None, 20)
    assert ok(a.get(f"{R}/{it2['id']}"))['play_log_id'] is None   # analiz HATA → oynatılamaz
    binsiz = next(x for x in ok(a.get(R, params={'mode': 'sitl'}))['items'] if not x['bin_log_id'])   # .bin'siz satır → 404 (silinen it'in id'si SQLite'ta yeniden kullanılabilir)
    assert a.get(f"{R}/{binsiz['id']}/bin").status_code == 404 and a.get(f'{R}/999999/bin').status_code == 404
    # istatistik ucu (sayfa üstü 4 kutu): /runs/stats /runs/{rid}'den önce eşleşir; sayılar listeyle tutarlı; days kırpılır
    st = ok(a.get(f'{R}/stats'))
    assert set(st) >= {'days', 'total', 'total_all', 'flight_s', 'avg_s', 'crash', 'crash_events', 'crash_rate', 'last_crash_at', 'open_sessions', 'last_run'}, st
    hepsi = ok(a.get(R, params={'from': '2000-01-01'}))
    assert st['days'] == 30 and st['total_all'] == hepsi['total'] and st['total'] <= st['total_all'] and st['open_sessions'] == 0, st
    assert st['crash'] >= 1 and st['last_crash_at'] and 0 < st['crash_rate'] <= 100 and st['flight_s'] >= 0 and st['avg_s'] >= 0, st
    assert st['last_run'] and st['last_run']['started_at'] == hepsi['items'][0]['started_at'], st['last_run']
    assert ok(a.get(f'{R}/stats', params={'days': 0}))['days'] == 1 and ok(a.get(f'{R}/stats', params={'days': 99999}))['days'] == 3650
    s3 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'mode': 'procedural'}}), 201)
    assert ok(a.get(f'{R}/stats'))['open_sessions'] == 1
    ok(a.delete(f"{S}/{s3['id']}"))
    assert ok(a.get(f'{R}/stats'))['open_sessions'] == 0 and ok(a.get(f'{R}/stats'))['total_all'] == hepsi['total'] + 1
    print('  simülasyon kayıtları (§21) testleri geçti')


def guc_testleri(a, c1, sitl, mon):
    """§23 güç ve yakıt: saf model (yakıt L/dk, batarya Wh, SIM_Plane tam gaz hızı ↔ SIM_PLN_THR_MUL, hız parametreleri, GucDurumu adımı/bitiş),
    doğrulama/varsayılanlar (CAYMAZ; kopterde yakıt yok), dron kaydı seçenekleri (GET/PUT sim-power; öneri), sihirbaz gövdesi `power` (400'ler),
    `speed` komutu (SIM_SPEEDUP; sahte kinematik hızlanır, tele.speedup), oturumda yakıt/batarya düşüşü + bitince kırmızı olay + `warn`, summary/run
    satırı alanları, ölçümlerin dron kaydına yazılması ve sonraki öneri; sahte kipte itki ölçeği desteği yok → hız parametreleri yalnız ArduPilot."""
    from app import db, drone_params, drone_sitl, flightsim_mission, flightsim_power as P
    S = '/api/drone/sim/sessions'
    # --- saf fonksiyonlar ---
    assert abs(P.plane_tam_gaz_hizi() - 31.85) < 0.1, P.plane_tam_gaz_hizi()                      # stok SIM_Plane tam gaz seviye hızı
    mul = P.thr_mul_icin(45)
    assert 1.95 < mul < 2.05 and abs(P.plane_tam_gaz_hizi(mul) - 45) < 0.05, (mul, P.plane_tam_gaz_hizi(mul))   # hız √mul ile ölçeklenir
    assert P.thr_mul_icin(P.plane_tam_gaz_hizi()) == 1.0 and P.thr_mul_icin(0) == 1.0
    hp = dict(P.hiz_parametreleri(45))
    assert hp == {'AIRSPEED_MAX': 45.0, 'AIRSPEED_CRUISE': 24.5, 'THR_MAX': 100.0, 'SIM_PLN_THR_MUL': mul}, hp   # cruise = v × 12/22 (ArduPlane varsayılan oranı)
    hp = dict(P.hiz_parametreleri(45, [{'name': 'AIRSPEED_MAX', 'value': 30}, {'name': 'AIRSPEED_CRUISE', 'value': 18}], itki_olcegi=False))
    assert hp == {'AIRSPEED_MAX': 45.0, 'AIRSPEED_CRUISE': 27.0, 'THR_MAX': 100.0}, hp   # kayıtlı oran 18/30 korunur; yamasız ikilide çarpan yok
    assert dict(P.hiz_parametreleri(45, {'AIRSPEED_MIN': 30}))['AIRSPEED_CRUISE'] == 32.0 and P.hiz_parametreleri(None) == []
    assert abs(P.yakit_lpm(45, 100, 25) - 0.108) < 1e-9 and abs(P.yakit_lpm(45, 0, 25) - 0.054) < 1e-9 and P.yakit_lpm(45, 50, 0) == 0   # (162 km/h ÷ 60) ÷ 25 × (0,5+0,5·gaz)
    assert P.batarya_wh(10000, 4) == 148.0 and P.servo_joule([1600, 1500], [1500, 1500]) == 0.05 and P.servo_joule([0, 1500], [1500, 1500]) == 0
    assert P.olculen_km_per_l(300, 0.02) == 15.0 and P.olculen_km_per_l(299, 0.02) is None and P.olculen_km_per_l(5000, 0.01) is None
    assert P.ortalama_w(0.5, 60) == 30.0 and P.ortalama_w(0.5, 59) is None
    # doğrulama + varsayılanlar
    d = P.dogrula(None, 'sabit_kanat')
    assert d == {'max_speed_ms': 45.0, 'fuel_l': 5.0, 'fuel_km_per_l': 25.0, 'elec_cells': 4, 'elec_mah': 10000.0, 'elec_w': 30.0}, d
    assert P.dogrula({'max_speed_ms': 60}, 'multirotor')['max_speed_ms'] is None and P.dogrula(None, 'multirotor')['fuel_l'] == 0.0
    assert P.dogrula({'fuel_l': 7, 'elec_cells': 6.4}, 'vtol', {'fuel_km_per_l': 18.5, 'elec_w': 42})['fuel_km_per_l'] == 18.5 and P.dogrula({'elec_cells': 6.4}, 'vtol')['elec_cells'] == 6
    for kotu in ({'fuel_l': -1}, {'elec_cells': 0}, {'max_speed_ms': 'hızlı'}, {'elec_mah': 10}, {'fuel_km_per_l': 0}, 5):
        try:
            P.dogrula(kotu, 'sabit_kanat'); raise AssertionError(kotu)
        except ValueError:
            pass
    # GucDurumu: 10 Hz sentetik telemetri (armed 1 sn sonra, 40 m/s, gaz %80) 60 sn → yakıt/batarya/mesafe; 0,05 L tank 34,7 sn'de biter
    # (L/dk = (144 km/h ÷ 60) ÷ 25 × 0,9 = 0,0864); 1S 100 mAh (0,37 Wh) @ 20 W + servo 60 sn'de bitmez; zaman kaynağı SITL ms
    g = P.GucDurumu({'max_speed_ms': 45, 'fuel_l': 0.05, 'fuel_km_per_l': 25, 'elec_cells': 1, 'elec_mah': 100, 'elec_w': 20})
    biten = []
    for i in range(601):
        biten += g.adim({'armed': i >= 10, 'groundspeed': 40.0, 'throttle': 80.0, 'servo': [1500 + 100 * (i % 2), 1500]}, i * 100)
    assert biten == ['fuel'] and 34 < g.fuel_empty_t < 36.5, (biten, g.fuel_empty_t)
    t = g.tele_alanlari()
    assert t['speedup'] == 1.0 and t['fuel'] == {'l': 0.0, 'pct': 0.0, 'lpm': round(0.0864, 4), 'range_km': 0.0, 'empty': True} and t['elec']['cells'] == 1, t
    assert abs(g.dist_m - 40.0 * 59.1) < 1e-6 and abs(g.armed_s - 59.1) < 1e-6 and abs(g.time_s - 60.0) < 1e-6, (g.dist_m, g.armed_s, g.time_s)   # armed adım 10…600 = 591 × 0,1 sn
    assert abs(g.fuel_used - 0.05) < 1e-9 and 0.33 < g.wh_used < 0.37 and 19 < t['elec']['w'] < 24 and t['elec']['empty'] is False, (g.fuel_used, g.wh_used, t['elec'])
    o = g.ozet()
    assert o['fuel']['start_l'] == 0.05 and o['fuel']['km_per_l'] == round(2.364 / 0.05, 2) and o['elec']['wh_cap'] == 0.37 and o['max_speed_seen'] == 40.0 and o['speedup'] == {'max': 1.0, 'changes': 0, 'last': 1.0}, o
    assert 'elec_w_last' in P.drona_yazilacaklar(o) and 'fuel_km_per_l_last' in P.drona_yazilacaklar(o), P.drona_yazilacaklar(o)   # mesafe 2,36 km, yakıt ≥ 0,02 L, süre ≥ 60 s
    g.sifirla_zaman(); assert g.adim({'armed': True, 'groundspeed': 40.0, 'throttle': 80.0}, 0) == [] and g.adim({'armed': True, 'groundspeed': 40.0, 'throttle': 80.0}, 100) == []   # yeni SITL saati: ilk kare dt yok
    g.hiz_ayarla(4); g.hiz_ayarla(4); g.hiz_ayarla(1)
    assert g.ozet()['speedup'] == {'max': 4.0, 'changes': 2, 'last': 1.0}
    assert drone_params.haric_mi('SIM_PLN_THR_MUL') and drone_params.haric_mi('SIM_SPEEDUP') and not drone_params.haric_mi('AIRSPEED_MAX')
    assert drone_sitl.hiz_olcegi_destegi('sabit_kanat') is False and drone_sitl.hiz_olcegi_destegi('multirotor') is False   # sahte kip: ikili yok
    # --- dron kaydı seçenekleri (drone_sitl_options) ---
    dr = ok(a.post('/api/drone/drones', json={'name': 'Güç Uçağı', 'protocol': 'sanal', 'model': 'Caymaz sabit kanat'}))
    did = dr['id']
    pd = ok(a.get('/api/drone/sim/power-defaults', params={'type': 'sabit_kanat', 'drone_id': did}))
    assert pd['suggested'] == d and pd['from_drone'] == {} and pd['stock_max_ms'] == 31.8 and pd['thr_mul'] == mul and pd['thr_scale_supported'] is False and pd['speedups'] == [0.25, 0.5, 1, 2, 4, 8], pd
    assert ok(a.get('/api/drone/sim/power-defaults', params={'type': 'multirotor'}))['suggested']['fuel_l'] == 0.0
    r = ok(a.get(f'/api/drone/drones/{did}/sim-power'))
    assert r['options'] == {} and r['type'] == 'sabit_kanat' and r['suggested'] == d and r['can_write'] is True, r
    r = ok(a.put(f'/api/drone/drones/{did}/sim-power', json={'max_speed_ms': 50, 'fuel_l': 6.5, 'elec_w_last': 28}))
    assert r['written'] == 3 and r['options']['max_speed_ms'] == 50 and r['options']['fuel_l'] == 6.5 and r['options']['elec_w_last'] == 28 and r['options']['updated_at'], r
    assert a.put(f'/api/drone/drones/{did}/sim-power', json={'fuel_l': -3}).status_code == 400 and a.put('/api/drone/drones/999999/sim-power', json={}).status_code == 404
    assert mon.put(f'/api/drone/drones/{did}/sim-power', json={'fuel_l': 1}).status_code == 403   # salt okuyan yazamaz
    sug = ok(a.get('/api/drone/sim/power-defaults', params={'type': 'sabit_kanat', 'drone_id': did}))
    assert sug['from_drone'] == {'max_speed_ms': 50.0, 'fuel_l': 6.5, 'elec_w': 28.0} and sug['suggested']['max_speed_ms'] == 50.0 and sug['suggested']['fuel_km_per_l'] == 25.0, sug
    assert next(x for x in ok(a.get('/api/drone/sim/drones')) if x['id'] == did)['power'] == {'max_speed_ms': 50.0, 'fuel_l': 6.5, 'elec_w': 28.0}
    ok(a.put(f'/api/drone/drones/{did}/sim-power', json={'max_speed_ms': None}))   # null → silinir
    assert 'max_speed_ms' not in ok(a.get(f'/api/drone/drones/{did}/sim-power'))['options']
    # --- oturum: start gövdesi `power` ---
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'power': {'fuel_l': 'çok'}}).status_code == 400
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'power': {'elec_cells': 40}}).status_code == 400
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'power': 7}).status_code == 422   # pydantic: power nesne olmalı
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    # dron kaydıyla + küçük tank/batarya: yakıt 0,05 L @ 1 km/L (12 m/s sahte uçuşta ~5 sn), batarya 1S 100 mAh (0,37 Wh) @ 20 W (~67 sn sim)
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': did, 'power': {'fuel_l': 0.05, 'fuel_km_per_l': 1, 'elec_cells': 1, 'elec_mah': 100, 'elec_w': 20}}), 201)
    sid = s['id']
    assert s['power'] == {'max_speed_ms': None, 'fuel_l': 0.05, 'fuel_km_per_l': 1.0, 'elec_cells': 1, 'elec_mah': 100.0, 'elec_w': 20.0}, s['power']   # kopter: azami hız yok; dron önerisi (6,5 L) gövdeyle ezildi
    assert s['speedup'] == 1.0 and s['speed_scale']['supported'] is False and s['speed_scale']['thr_mul'] is None and s['power_state']['fuel']['l'] == 0.05 and s['power_state']['elec']['wh'] == 0.37, s
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    cmd = lambda name, params=None: a.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
    assert cmd('speed', {'factor': 3}).status_code == 400 and cmd('speed', {}).status_code == 400 and cmd('speed', {'factor': True}).status_code == 400
    assert ok(cmd('speed', {'factor': 8})) == {'ok': True, 'factor': 8.0}
    assert ok(a.get(f'{S}/{sid}'))['speedup'] == 8.0 and ses.sahte.speedup == 8.0
    ok(cmd('takeoff', {'alt': 20}))
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        assert json.loads(ws.receive_text())['t'] == 'hello'
        t0 = ws_bekle(ws, lambda m: m['t'] == 'tele' and m['armed'], 3)
        assert t0 and t0['speedup'] == 8 and t0['fuel'] and t0['elec'] and t0['fuel']['l'] <= 0.05 and t0['elec']['pct'] <= 100, t0
        w0 = time.time()
        fuel_warn = elec_warn = None
        olaylar = []
        t_son = t0
        while time.time() - w0 < 12 and not (fuel_warn and elec_warn):
            m = json.loads(ws.receive_text())
            if m['t'] == 'tele':
                t_son = m
            elif m['t'] == 'warn':
                if m['kind'] == 'fuel_empty':
                    fuel_warn = m
                elif m['kind'] == 'elec_empty':
                    elec_warn = m
            elif m['t'] == 'event':
                olaylar.append(m)
        assert fuel_warn and 'YAKIT BİTTİ' in fuel_warn['text'], fuel_warn
        assert elec_warn and 'BATARYA BİTTİ' in elec_warn['text'], elec_warn
        assert any(e['severity'] == 2 and 'YAKIT BİTTİ' in e['text'] for e in olaylar) and any(e['severity'] == 2 and 'BATARYA BİTTİ' in e['text'] for e in olaylar), olaylar
        t_son = ws_bekle(ws, lambda m: m['t'] == 'tele' and m['fuel']['empty'] and m['elec']['empty'], 3) or t_son   # warn'dan sonraki ilk tam-boş kare
        assert t_son['fuel']['empty'] is True and t_son['fuel']['l'] == 0 and t_son['elec']['empty'] is True and t_son['elec']['wh'] == 0 and t_son['armed'] is True, t_son   # uçuş sürer
        assert t_son['tbm'] > (time.time() - w0) * 1000 * 3, (t_son['tbm'], time.time() - w0)   # sahte SITL saati gerçek zamandan hızlı (8×)
    assert ses.guc.speedup_max == 8.0 and ses.guc.dist_m >= 300, (ses.guc.dist_m, ses.guc.armed_s)
    ok(cmd('speed', {'factor': 1}))
    sm = ok(a.get(f'{S}/{sid}/summary'))
    pw = sm['power']
    assert pw['settings']['fuel_l'] == 0.05 and pw['fuel']['used_l'] == 0.05 and pw['fuel']['left_l'] == 0 and pw['fuel']['empty_t'] is not None and pw['fuel']['km_per_l'] is not None, pw
    assert pw['elec']['wh_cap'] == 0.37 and pw['elec']['wh_used'] == 0.37 and pw['elec']['empty_t'] is not None and pw['elec']['cells'] == 1 and pw['speedup']['max'] == 8.0 and pw['speedup']['changes'] == 2, pw
    assert pw['elec']['w_avg'] is not None and 'Güç ve yakıt:' in flightsim_mission.rapor_metni(sm), flightsim_mission.rapor_metni(sm)
    ok(a.delete(f'{S}/{sid}'))
    it = ok(a.get('/api/drone/sim/runs'))['items'][0]
    # özet ile kapanış arasında uçuş sürdü: mesafe arttı, yakıt bitmişti → kapanıştaki km/L özetten büyük/eşit; ortalama W ≈ aynı (sabit 20 W, servo yok).
    # Batarya bittikten sonra w_avg = wh_used / time_s zamanla AZALIR (time_s işlemeye devam eder) → özet↔kapanış arasındaki birkaç yüz ms 0,1 W
    # yuvarlama sınırını aşabilir; tam eşitlik zamanlamaya bağlı (aralıklı başarısızlık) → ±0,5 W
    assert it['session_id'] == sid and it['fuel_used_l'] == 0.05 and it['fuel_km_per_l'] >= pw['fuel']['km_per_l'] and it['elec_wh'] == 0.37 and abs(it['elec_w_avg'] - pw['elec']['w_avg']) <= 0.5 and it['elec_w_avg'] <= pw['elec']['w_avg'] and it['speedup_max'] == 8.0, (it, pw['elec'])
    assert it['power']['settings']['elec_mah'] == 100.0 and it['power']['fuel']['empty_t'] is not None, it['power']
    # ölçümler dron kaydına yazıldı → sonraki öneri
    opts = ok(a.get(f'/api/drone/drones/{did}/sim-power'))['options']
    assert opts['fuel_km_per_l_last'] == it['fuel_km_per_l'] and opts['elec_w_last'] == it['elec_w_avg'], opts
    sug = ok(a.get('/api/drone/sim/power-defaults', params={'type': 'sabit_kanat', 'drone_id': did}))['suggested']
    assert sug['fuel_km_per_l'] == it['fuel_km_per_l'] and sug['elec_w'] == it['elec_w_avg'] and sug['fuel_l'] == 6.5, sug
    with db.connect() as conn:
        assert db.row(conn.execute('SELECT fuel_used_l, speedup_max, power FROM drone_sim_runs WHERE id = ?', (it['id'],)))['speedup_max'] == 8.0
    # --- sabit kanat: hız parametreleri sahte SITL'e yazılır (AIRSPEED_MAX/CRUISE, THR_MAX; itki ölçeği desteği yok → SIM_PLN_THR_MUL yok + sarı olay); yükleme işareti
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'drone_id': did, 'power': {'max_speed_ms': 40}}), 201)
    sid = s['id']
    assert s['power']['max_speed_ms'] == 40.0 and s['power']['fuel_l'] == 6.5 and s['speed_scale'] == {'supported': False, 'thr_mul': P.thr_mul_icin(40), 'thr_mul_sitl': None, 'stock_ms': 31.8}, s
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ses = flightsim.MANAGER.get(sid)
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5)
    assert dict(ses.hiz_parametreleri()) == {'AIRSPEED_MAX': 40.0, 'AIRSPEED_CRUISE': 21.8, 'THR_MAX': 100.0}, ses.hiz_parametreleri()
    once = len(sitl.alinan)
    olaylar = []
    ses._olay = lambda text, severity=6: olaylar.append((text, severity))
    ses._hiz_yaz()
    assert bekle(lambda: len(sitl.alinan) > once and b'AIRSPEED_MAX' in bytes(sitl.alinan[once:]) and b'THR_MAX' in bytes(sitl.alinan[once:]), 3)
    assert b'SIM_PLN_THR_MUL' not in bytes(sitl.alinan[once:]) and {'AIRSPEED_MAX', 'AIRSPEED_CRUISE', 'THR_MAX'} <= ses.param_izleyici.yukleme
    assert olaylar and olaylar[0][1] == 4 and 'itki ölçeği' in olaylar[0][0] and 'Azami hız 40 m/s' in olaylar[0][0], olaylar
    ok(a.delete(f'{S}/{sid}'))
    print('  güç ve yakıt (§23) testleri geçti')


def kamera_testleri(a, c1, sitl):
    """§22.3 kamera türü: start gövdesi `camera` enum doğrulaması (400), oturum/durum alanı, `camera` komutu (HAZIR beklemez; 400 doğrulama),
    kapanışta drone_sim_runs.camera + /drones önerisi; kayıttan oynatma kaydın türünü (bin_log_id) okur, yoksa verilen tür."""
    from app import db, flightsim_replay as R
    S = '/api/drone/sim/sessions'
    assert flightsim.kamera_dogrula(None) == 'day' and flightsim.kamera_dogrula('night') == 'night' and flightsim.kamera_dogrula('', 'thermal') == 'thermal'
    for kotu in ('ir', 'DAY', 5, ['day']):
        try:
            flightsim.kamera_dogrula(kotu); raise AssertionError(kotu)
        except flightsim.SimHata as e:
            assert e.kod == 'invalid'
    assert a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'camera': 'ir'}).status_code == 400
    assert a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'camera': ['day']}).status_code == 422
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    dr = ok(a.post('/api/drone/drones', json={'name': 'Kamera Dronu', 'protocol': 'sanal', 'model': 'Quad'}))
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': dr['id'], 'camera': 'thermal'}), 201)
    sid = s['id']
    assert s['camera'] == 'thermal', s.get('camera')
    cmd = lambda name, params=None: a.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
    assert ok(cmd('camera', {'type': 'night'})) == {'ok': True, 'camera': 'night'}   # BASLIYOR'da da kabul (SITL'e gitmez)
    assert cmd('camera', {}).status_code == 400 and cmd('camera', {'type': 'uv'}).status_code == 400
    assert ok(a.get(f'{S}/{sid}'))['camera'] == 'night'
    ok(a.delete(f'{S}/{sid}'))
    it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
    assert it['camera'] == 'night', it.get('camera')
    assert next(x for x in ok(a.get('/api/drone/sim/drones')) if x['id'] == dr['id'])['camera'] == 'night'
    # varsayılan gündüz
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s2['camera'] == 'day'
    ok(a.delete(f'{S}/{s2["id"]}'))
    # kayıttan oynatma: kaydın türü (drone_sim_runs.bin_log_id) — yoksa ac_replay'e verilen tür
    with db.connect() as conn:
        lid = conn.execute('SELECT MAX(id) FROM flight_logs').fetchone()[0]   # replay_testleri'nin logu (FK)
        conn.execute('UPDATE drone_sim_runs SET bin_log_id = ? WHERE id = ?', (lid, it['id']))
        conn.commit()
    try:
        r = R.ReplaySession(1, {'id': lid, 'file_name': 'k.bin', 'vehicle': 'ArduCopter'}, {}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        assert r.camera == 'night' and r.to_dict()['camera'] == 'night', r.camera
        r2 = R.ReplaySession(2, {'id': lid + 1000, 'file_name': 'y.bin', 'vehicle': 'ArduCopter'}, {}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        assert r2.camera is None and r2.to_dict()['camera'] == 'day'
    finally:
        with db.connect() as conn:
            conn.execute('UPDATE drone_sim_runs SET bin_log_id = NULL WHERE id = ?', (it['id'],))
            conn.commit()
    print('  kamera türü (§22.3) testleri geçti')


def _yatay_m(la, lo, la2, lo2):
    return math.hypot((la2 - la) * 110574.0, (lo2 - lo) * 111320.0 * math.cos(math.radians(la)))


def motor_cut_birim_testleri():
    """Sahte kinematik motor kesme: itki 0, ARM korunur, süzülme oranı 1:8–1:12, 100 m'den yere iniş, rulo girişiyle dönüş, yerde durma,
    motor geri verilince daireye ışınlanmadan yaklaşma, havada disarm'da da süzülme (uçak), ARM/kalkış/sıfırlamada bayrak kalkar."""
    K = flightsim.SahteKinematik

    def havada(tip='sabit_kanat', alt=100.0):
        k = K(tip, 39.925, 32.837, 900, 0)
        k.armed, k.alt_rel, k.hedef_alt, k.mode = True, alt, alt, 'FBWA'
        k.vn, k.ve, k.yaw = 12.0, 0.0, 0.0
        return k

    k = havada()
    k.komut('motor_cut', {'on': True})
    assert k.motor_cut and k.armed
    yol, t = 0.0, 0.0
    while k.alt_rel > 0 and t < 300:
        la, lo = k.lat, k.lon
        k.adim(0.02); t += 0.02
        yol += _yatay_m(la, lo, k.lat, k.lon)
        assert k.throttle == 0.0 and k.armed
    ld = yol / 100.0
    assert k.alt_rel == 0.0 and 8.0 <= ld <= 12.0 and 60 <= t <= 120, (k.alt_rel, ld, t)   # 100 m → ≈ 1000 m, ≈ 84 sn
    te = k.tele()
    assert te['throttle'] == 0.0 and te['vd'] == 0.0 and te['groundspeed'] == 0.0 and te['armed'], te   # yere indi: durur, ARM'lı kalır
    la, lo = k.lat, k.lon
    for _ in range(100):
        k.adim(0.02)
    assert (k.lat, k.lon, k.alt_rel) == (la, lo, 0.0)   # yerde, motor kesik: kıpırdamaz (hedef_alt'a tırmanmaz)
    # süzülme anı: düşey hız ≈ hız / 10, burun aşağı; RC 1 (aileron) ile yatış → yön değişir
    k = havada()
    k.komut('motor_cut', {'on': True})
    for _ in range(250):
        k.adim(0.02)
    te = k.tele()
    assert 1.0 <= te['vd'] <= 1.4 and te['pitch'] < 0 and abs(te['groundspeed'] - flightsim.SAHTE_SUZULME_HIZ) < 0.6, te
    h0 = te['heading']
    k.komut('rc', {'ch': [1900, 0, 0, 0, 0, 0, 0, 0]})
    for _ in range(250):
        k.adim(0.02)
    te = k.tele()
    assert te['roll'] > math.radians(30) and ((te['heading'] - h0) % 360) > 60, (te['roll'], te['heading'], h0)   # sağa yatış → sağa dönüş
    # motor geri: ARM ile; havada daireye ışınlanmadan yaklaşır (adım başına ≤ HIZ·dt)
    k.komut('arm', {})
    assert not k.motor_cut and k._daireye_don
    for _ in range(5000):
        la, lo = k.lat, k.lon
        k.adim(0.02)
        d = _yatay_m(la, lo, k.lat, k.lon)
        assert d <= K.HIZ * 0.02 * 1.05 + 0.05, d
        if not k._daireye_don:
            break
    assert not k._daireye_don and k.throttle > 0
    # motor_cut {on:false} ve kalkış da geri verir; sıfırlama temizler
    k = havada(); k.komut('motor_cut', {'on': True}); k.komut('motor_cut', {'on': False}); assert not k.motor_cut
    k = havada(); k.komut('motor_cut', {'on': True}); k.komut('takeoff', {'alt': 120}); assert not k.motor_cut
    k = havada(); k.komut('motor_cut', {'on': True}); k.komut('reset', {}); assert not k.motor_cut and k.alt_rel == 0.0
    # uçak havada disarm: ArduPlane gibi süzülür (eskiden havada donuyordu); kopter davranışı değişmedi
    k = havada(); k.komut('disarm', {})
    for _ in range(250):
        k.adim(0.02)
    assert not k.armed and k.alt_rel < 99.0 and k.tele()['groundspeed'] > 5, k.tele()
    k = havada('multirotor', 20.0); k.komut('disarm', {})
    for _ in range(50):
        k.adim(0.02)
    assert k.alt_rel == 20.0
    print('  motor kesme (sahte kinematik) birim testleri geçti')


def motor_cut_testleri(a, c1, sitl):
    """`motor_cut {on: bool}` sözleşmesi: doğrulama (400), kopter reddi, yanıt {ok, motor_cut}, to_dict + WS tele `motor_cut`, olay şeridi satırları,
    ARM / motor_cut{on:false} geri verir, reset ve 3B çarpışması sıfırlar, KOMUTLAR'da (SIMUMAV aynı listeyi kullanır)."""
    S = '/api/drone/sim/sessions'
    assert 'motor_cut' in flightsim.KOMUTLAR
    from app.simumav.routers import fly as smfly
    assert 'motor_cut' in smfly.SIM_KOMUT
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s = ok(a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id']}), 201)
    sid = s['id']
    assert s['motor_cut'] is False, s.get('motor_cut')
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    cmd = lambda name, params=None: a.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
    for kotu in ({}, {'on': 1}, {'on': 'true'}, {'on': None}):
        r = cmd('motor_cut', kotu)
        assert r.status_code == 400 and 'motor_cut.on' in r.text, (kotu, r.status_code, r.text)
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hello = json.loads(ws.receive_text()); assert hello['session']['motor_cut'] is False
        t = ws_bekle(ws, lambda x: x['t'] == 'tele', 3); assert t and t['motor_cut'] is False, t and list(t)
        ok(cmd('takeoff', {'alt': 60}))
        assert ok(cmd('motor_cut', {'on': True})) == {'ok': True, 'motor_cut': True}
        e = ws_bekle(ws, lambda x: x['t'] == 'event' and 'MOTOR' in x['text'], 3); assert e and e['text'] == 'MOTOR KESİLDİ — süzülüyor' and e['severity'] == 4, e
        t = ws_bekle(ws, lambda x: x['t'] == 'tele' and x.get('motor_cut') is True, 3); assert t and t['throttle'] == 0.0 and t['armed'], t
        assert ok(a.get(f'{S}/{sid}'))['motor_cut'] is True
        assert ok(cmd('motor_cut', {'on': True})) == {'ok': True, 'motor_cut': True}   # yineleme: idempotent (ikinci olay yok)
        ok(cmd('arm'))   # ARM motoru geri verir
        e = ws_bekle(ws, lambda x: x['t'] == 'event' and x['text'] in ('Motor geri verildi', 'MOTOR KESİLDİ — süzülüyor'), 3)
        assert e and e['text'] == 'Motor geri verildi' and e['severity'] == 6, e
        t = ws_bekle(ws, lambda x: x['t'] == 'tele' and x.get('motor_cut') is False, 3); assert t, t
        assert ok(cmd('motor_cut', {'on': True}))['motor_cut'] is True and ok(cmd('motor_cut', {'on': False})) == {'ok': True, 'motor_cut': False}
        assert ok(cmd('motor_cut', {'on': True}))['motor_cut'] is True
    ok(cmd('reset'))
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    assert ok(a.get(f'{S}/{sid}'))['motor_cut'] is False
    s_obj = flightsim.MANAGER.get(sid)
    assert s_obj.sahte.motor_cut is False
    # 3B çarpışması (zorla disarm) da kesmeyi kaldırır (sonraki ARM'ı MOTOR_ESTOP engellemesin)
    ok(cmd('takeoff', {'alt': 60})); ok(cmd('motor_cut', {'on': True}))
    ok(cmd('crash', {'kind': 'building', 'speed': 10}))
    assert s_obj.motor_cut is False and s_obj.sahte.motor_cut is False
    ok(a.delete(f'{S}/{sid}'))
    # kopter: reddedilir (havada motor kesmek düşürür; ön yüz DISARM'ı onayla gönderir)
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert bekle(lambda: ok(a.get(f"{S}/{s['id']}"))['state'] == 'HAZIR')
    r = a.post(f"{S}/{s['id']}/cmd", json={'name': 'motor_cut', 'params': {'on': True}})
    assert r.status_code == 400 and 'kopter' in r.text, r.text
    ok(a.delete(f"{S}/{s['id']}"))
    print('  motor kesme (motor_cut) testleri geçti')


def servo_tetik_birim_testleri():
    """§34 servo tetik saf mantığı (sahte oturum nesnesiyle): doğrulama, koşul, kenar tetik (dinleme başında zaten koşuldaysa tetik YOK),
    simülasyon zamanıyla gecikme, çarpma anı / tetik anı anlık görüntüleri (AGL arazi ↔ ev, evden mesafe, uçuş süresi), PWM 0 = koşul yok (çıkış yok → komutla kenar),
    `on:false` bekleyeni iptal, reset, kısa özet (drone_sim_runs.servo_trig), işlev adları."""
    import asyncio as aio
    from app import flightsim_servotrig as ST
    D = ST.dogrula
    assert D({'on': False}) == {'on': False}
    assert D({'on': True, 'ch': 9, 'pwm': 1900}) == {'on': True, 'ch': 9, 'pwm': 1900, 'cmp': 'ge', 'tol': 50, 'delay_ms': 0}
    assert D({'on': True, 'ch': 16, 'pwm': 800, 'cmp': 'eq', 'tol': 20, 'delay_ms': 60000.0})['delay_ms'] == 60000
    for kotu in ({}, {'on': 1}, {'on': True}, {'on': True, 'ch': 0, 'pwm': 1500}, {'on': True, 'ch': 17, 'pwm': 1500}, {'on': True, 'ch': True, 'pwm': 1500},
                 {'on': True, 'ch': 9, 'pwm': 799}, {'on': True, 'ch': 9, 'pwm': 2201}, {'on': True, 'ch': 9, 'pwm': 1900, 'cmp': 'gt'},
                 {'on': True, 'ch': 9, 'pwm': 1900, 'delay_ms': -1}, {'on': True, 'ch': 9, 'pwm': 1900, 'delay_ms': 60001},
                 {'on': True, 'ch': 9, 'pwm': 1900, 'tol': 0}, {'on': True, 'ch': 9, 'pwm': float('nan')}):
        try:
            D(kotu)
        except ST.ServoTetikHata:
            continue
        raise AssertionError(kotu)
    c = {'cmp': 'ge', 'pwm': 1900, 'tol': 50}
    assert ST.kosul(c, 1900) is True and ST.kosul(c, 1899) is False and ST.kosul(c, 0) is False and ST.kosul(c, 65535) is False and ST.kosul(c, None) is None and ST.kosul({**c, 'cmp': 'le'}, 0) is False
    assert ST.kosul({**c, 'cmp': 'le'}, 1100) is True and ST.kosul({**c, 'cmp': 'eq'}, 1949) is True and ST.kosul({**c, 'cmp': 'eq'}, 1951) is False
    assert ST.islev_adi(59) == ('RCIN9', True) and ST.islev_adi(4) == ('Aileron', False) and ST.islev_adi(33) == ('Motor1', False) and ST.islev_adi(28) == ('Gripper', True)
    assert ST.islev_adi(999) == ('F999', False) and ST.islev_adi(None) == (None, False)

    class Gorev:
        def __init__(self):
            self.crashes = []

        def carpisma(self, sebep, hiz=None, detay_metin=None, vz=None):
            self.crashes.append({'reason': sebep, 'speed': hiz, 'text': detay_metin})
            return self.crashes[-1]

    class Ses:
        def __init__(self):
            self.tele = {'lat': 39.925, 'lon': 32.837, 'alt_msl': 900.0, 'alt_rel': 0.0, 'tbm': 0, 'armed': False, 'airspeed': 0.0, 'groundspeed': 0.0,
                         'heading': 90.0, 'climb': 0.0, 'mode': 'GUIDED', 'home': {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}}
            self.center = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
            self.sahte, self.loop, self.viewers, self.state, self.drone, self.owner = object(), None, {}, 'HAZIR', None, {}
            self.end_reason, self._heartbeat_alindi, self.motor_cut = None, False, False
            self.yayin, self.olaylar, self.gorev, self.disarm = [], [], Gorev(), 0
            self.sahte = type('K', (), {'komut': lambda _s, n, p: setattr(self, 'disarm', self.disarm + (n == 'disarm'))})()

        def _yay(self, o):
            self.yayin.append(o)

        def _olay(self, t, sev=6):
            self.olaylar.append((t, sev))

    s = Ses()
    st = ST.ServoTetik(s)
    run = lambda name, p: aio.run(st.komut(name, p))   # noqa: E731
    assert st.ozet() is None and st.durum()['phase'] == 'idle'
    arr = [1500] * 8 + [1100] * 8
    # ARM: uçuş süresi tabanı (tbm 1000)
    s.tele.update(armed=True, tbm=1000); st.adim()
    # dinleme başında kanal ZATEN koşulda → tetik yok (kenar), uyarı olayı bir kez
    arr[8] = 1950
    run('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900, 'delay_ms': 1500})
    st.gozlem(arr, 2000); st.gozlem(arr, 2100)
    assert st.phase == 'listening' and sum('zaten koşulda' in o[0] for o in s.olaylar) == 1, s.olaylar
    arr[8] = 0; st.gozlem(arr, 2150)   # çıkış yok: koşul sağlanmıyor (kenar tabanı)
    arr[8] = 1100; st.gozlem(arr, 2200)
    assert st.phase == 'listening'
    # yeni kenar → tetik anı (konum: evden ~111 m kuzey, 80 m AGL, arazi verisi yok → ev referansı)
    s.tele.update(lat=39.926, alt_rel=80.0, alt_msl=980.0, airspeed=21.0, groundspeed=19.5, tbm=5000)
    arr[8] = 1900; st.gozlem(arr, 5000)
    assert st.phase == 'pending' and st.seen_pwm == 1900, st.phase
    T = st.trigger
    assert T['agl'] == 80.0 and T['agl_src'] == 'home' and T['alt_msl'] == 980.0 and 110 < T['dist_home_m'] < 112 and T['flight_s'] == 4.0 and T['tbm'] == 5000, T
    assert any(o.get('phase') == 'pending' for o in s.yayin)
    # gecikme simülasyon zamanıyla: 1499 ms'de çarpma yok, 1500'de var; çarpma anında arazi AGL'si (TERRAIN_REPORT) öncelikli
    s.tele.update(tbm=6499, lat=39.9265); st.adim()
    assert st.phase == 'pending'
    s.tele.update(tbm=6500, lat=39.927, alt_rel=75.0, terrain_agl=62.5, alt_msl=975.0); st.adim()
    assert st.phase == 'fired' and st.donuk and s.end_reason == 'servo_trigger' and s.disarm == 1, (st.phase, s.end_reason)
    H = st.hit
    assert H['agl'] == 62.5 and H['agl_src'] == 'terrain' and H['delay_sim_ms'] == 1500 and 221 < H['dist_home_m'] < 223 and H['flight_s'] == 5.5, H
    assert s.gorev.crashes[-1]['reason'] == 'servo_trigger' and s.gorev.crashes[-1]['speed'] == 21.0, s.gorev.crashes
    assert any(o.get('phase') == 'fired' for o in s.yayin)
    o = st.ozet()
    assert o['ch'] == 9 and o['pwm'] == 1900 and o['seen_pwm'] == 1900 and o['delay_ms'] == 1500 and o['trigger']['agl'] == 80.0 and o['hit']['agl'] == 62.5 and o['time_base'] == 'sim', o
    k = ST.kisa_ozet(o)
    assert k == {'ch': 9, 'fn': None, 'pwm': 1900, 'cmp': 'ge', 'delay_ms': 1500, 'trig_agl': 80.0, 'trig_msl': 980.0, 'trig_dist_m': T['dist_home_m'],
                 'hit_agl': 62.5, 'hit_dist_m': H['dist_home_m'], 'fired': True}, k
    try:   # çarpmadan sonra yeniden dinleme yok (oturum kapanıyor)
        run('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900})
        raise AssertionError('fired sonrası kabul edildi')
    except ST.ServoTetikHata:
        pass
    # ≤ koşulu + gecikme 0 → anında; on:false bekleyeni iptal eder; reset taban + bekleyeni sıfırlar
    s2 = Ses(); st2 = ST.ServoTetik(s2)
    aio.run(st2.komut('servo_trigger', {'on': True, 'ch': 3, 'pwm': 1200, 'cmp': 'le', 'delay_ms': 0}))
    a2 = [1500] * 16; st2.gozlem(a2, 100); a2[2] = 1150; st2.gozlem(a2, 200)
    assert st2.phase == 'fired' and st2.hit['delay_sim_ms'] == 0
    s5 = Ses(); st5 = ST.ServoTetik(s5)   # gerçek SITL: SERVO9_FUNCTION 0 → kanal 0 bildirir; DO_SET_SERVO 0 → 1900 kenardır
    aio.run(st5.komut('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900, 'delay_ms': 1500}))
    a5 = [0] * 16; st5.gozlem(a5, 100); a5[8] = 1900; st5.gozlem(a5, 200)
    assert st5.phase == 'pending', st5.phase
    s3 = Ses(); st3 = ST.ServoTetik(s3)
    aio.run(st3.komut('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900, 'delay_ms': 5000}))
    a3 = [1500] * 16; st3.gozlem(a3, 100); a3[8] = 2000; st3.gozlem(a3, 200)
    assert st3.phase == 'pending'
    st3.sifirla(); assert st3.phase == 'listening' and st3.trigger is None and st3._onceki is None
    st3.gozlem(a3, 300); assert st3.phase == 'listening'   # reset sonrası ilk örnek taban (zaten koşulda)
    a3[8] = 1500; st3.gozlem(a3, 400); a3[8] = 2000; st3.gozlem(a3, 500); assert st3.phase == 'pending'
    aio.run(st3.komut('servo_trigger', {'on': False}))
    assert st3.phase == 'idle' and not st3.on and any('iptal' in o[0] for o in s3.olaylar)
    s3.tele['tbm'] = 99999; st3.adim(); assert st3.phase == 'idle' and st3.hit is None
    # SERVO_OUTPUT_RAW (MAVLink2 uzantı alanları 9…16) → 16 kanal; port ≠ 0 yok sayılır
    from pymavlink.dialects.v20 import ardupilotmega as Dv
    mv = Dv.MAVLink(None, srcSystem=1, srcComponent=1)
    m = mv.parse_buffer(mv.servo_output_raw_encode(7_000_000, 0, *([1500] * 8), servo9_raw=1900, servo16_raw=1234).pack(mv))[0]
    assert ST.servo_raw_dizisi(m)[8] == 1900 and ST.servo_raw_dizisi(m)[15] == 1234
    s4 = Ses(); st4 = ST.ServoTetik(s4); st4.gozlem_mesaj(m)
    assert s4.tele['servo16'][8] == 1900 and st4.pwm[15] == 1234
    m2 = mv.parse_buffer(mv.servo_output_raw_encode(1, 1, *([1000] * 8)).pack(mv))[0]
    st4.gozlem_mesaj(m2); assert st4.pwm[0] == 1500   # port 1 (17…32) yok sayıldı
    st4.param('SERVO9_FUNCTION', 59.0); st4.param('SERVO17_FUNCTION', 1.0); st4.param('SERVO1_FUNCTION', 4)
    assert st4.fn[8] == 59 and st4.fn[0] == 4 and len(st4.fn) == 16
    print('  servo tetik (§34) birim testleri geçti')


def servo_tetik_testleri(a, c1, sitl):
    """§34 uçtan uca (sahte kinematik): komut sözleşmesi (400'ler, KOMUTLAR + SIMUMAV SIM_KOMUT), servo_set → kenar → sim zamanı gecikme →
    `crash` (reason servo_trigger) + `servo_trigger fired`, 3B donar (tele kesilir), özet `servo_trigger` bölümü, izleyici kalmayınca sunucu
    kapatır (end_reason servo_trigger), drone_sim_runs.servo_trig + result carpisma, dron kaydına son ayarlar (sonraki oturumda öneri)."""
    from app import db, drone_params, flightsim_servotrig as ST
    S = '/api/drone/sim/sessions'
    assert 'servo_trigger' in flightsim.KOMUTLAR and 'servo_set' in flightsim.KOMUTLAR
    from app.simumav.routers import fly as smfly
    assert 'servo_trigger' in smfly.SIM_KOMUT
    dr = ok(a.post('/api/drone/drones', json={'name': 'Servo Kopter', 'protocol': 'sanal', 'model': 'Quad'}))
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': dr['id']}), 201)
    sid = s['id']
    assert s['servo_trigger']['phase'] == 'idle' and s['servo_trigger']['suggest'] is None and len(s['servo_trigger']['fn']) == 16, s['servo_trigger']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    cmd = lambda name, params=None: a.post(f'{S}/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
    for kotu in ({}, {'on': True, 'ch': 0, 'pwm': 1900}, {'on': True, 'ch': 9, 'pwm': 3000}, {'on': True, 'ch': 9, 'pwm': 1900, 'cmp': 'x'}):
        r = cmd('servo_trigger', kotu); assert r.status_code == 400 and 'servo_trigger.' in r.text, (kotu, r.text)
    assert cmd('servo_set', {'ch': 9}).status_code == 400 and cmd('servo_set', {'ch': 20, 'pwm': 1500}).status_code == 400
    ok(cmd('speed', {'factor': 4}))   # gecikme sim zamanında: 4× hızda duvar saatinde ~4 kat kısa
    ok(cmd('takeoff', {'alt': 30}))
    ok(cmd('servo_set', {'ch': 9, 'pwm': 1950}))   # dinleme öncesi koşulda → tetik değil
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        r = ok(cmd('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900, 'cmp': 'ge', 'delay_ms': 1500}))
        assert r['servo_trigger']['phase'] == 'listening' and r['servo_trigger']['pwm_now'] == 1950, r
        e = ws_bekle(ws, lambda x: x['t'] == 'event' and 'zaten koşulda' in x['text'], 3); assert e, 'zaten koşulda uyarısı yok'
        assert bekle(lambda: flightsim.MANAGER.get(sid).tele['alt_rel'] > 5, 8), 'kalkış olmadı'
        ok(cmd('servo_set', {'ch': 9, 'pwm': 1100}))
        assert flightsim.MANAGER.get(sid).servo_tetik.phase == 'listening'
        t_duvar = time.time()
        ok(cmd('servo_set', {'ch': 9, 'pwm': 1900}))   # Mission Planner DO_SET_SERVO karşılığı
        p = ws_bekle(ws, lambda x: x['t'] == 'servo_trigger' and x.get('phase') == 'pending', 3); assert p and p['trigger']['agl'] > 5, p
        c = ws_bekle(ws, lambda x: x['t'] == 'crash', 6); assert c and c['reason'] == 'servo_trigger', c
        f = ws_bekle(ws, lambda x: x['t'] == 'servo_trigger' and x.get('phase') == 'fired', 3)
        assert f and f['hit']['delay_sim_ms'] >= 1500 and f['hit']['delay_wall_ms'] < 1400, f and f['hit']
        assert time.time() - t_duvar < 3
        # donma: çarpmadan sonra tele yayınlanmaz (3B çarpma anı pozunda kalır)
        ses = flightsim.MANAGER.get(sid)
        t1 = ses._tele_son; time.sleep(0.6)
        assert ses._tele_son == t1 and ses.servo_tetik.donuk
        o = ok(a.get(f'{S}/{sid}/summary'))
        sv = o['servo_trigger']
        assert sv['ch'] == 9 and sv['seen_pwm'] == 1900 and sv['delay_ms'] == 1500 and sv['trigger']['agl'] > 5 and sv['hit'] and sv['hit']['dist_home_m'] is not None, sv
        assert o['crash']['reason'] == 'servo_trigger' and o['end_reason'] == 'servo_trigger', (o['crash'], o['end_reason'])
        assert cmd('servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900}).status_code == 400   # oturum kapanıyor
    # izleyici yok → sunucu kendisi kapatır (BOS_KAPANIS_S)
    assert bekle(lambda: a.get(f'{S}/{sid}').status_code == 404 or None, ST.BOS_KAPANIS_S + 8), 'sunucu kapatmadı'
    def son_run():   # KAPANDI durumunda GET 404 verir; satır _temizle sonunda yazılır → satırı bekle
        with db.connect() as conn:
            return db.row(conn.execute("SELECT * FROM drone_sim_runs WHERE session_id = ? AND created_at >= ? ORDER BY id DESC LIMIT 1", (sid, s['created_at'])))
    run = bekle(son_run, 15)
    assert run and run['end_reason'] == 'servo_trigger' and run['result'] == 'carpisma', (run['end_reason'], run['result'])
    k = json.loads(run['servo_trig'])
    assert k['ch'] == 9 and k['fired'] is True and k['trig_agl'] > 5 and k['delay_ms'] == 1500, k
    it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['id'] == run['id'])
    assert it['servo_trig']['trig_agl'] == k['trig_agl'], it['servo_trig']   # liste/kart için JSON çözülmüş
    # dron kaydına son ayarlar → sonraki oturumda öneri
    o2 = drone_params.secenekleri_oku(dr['id'])
    assert o2['srvtrig_ch'] == 9 and o2['srvtrig_pwm'] == 1900 and o2['srvtrig_delay_ms'] == 1500 and o2['srvtrig_cmp'] == 0, o2
    s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'drone_id': dr['id']}), 201)
    assert s['servo_trigger']['suggest'] == {'ch': 9, 'pwm': 1900, 'cmp': 'ge', 'tol': 50, 'delay_ms': 1500}, s['servo_trigger']
    ok(a.delete(f"{S}/{s['id']}"))
    with db.connect() as conn:
        run2 = db.row(conn.execute('SELECT servo_trig FROM drone_sim_runs WHERE session_id = ? AND created_at >= ? ORDER BY id DESC LIMIT 1', (s['id'], s['created_at'])))
    assert run2 and run2['servo_trig'] is None   # dinlenmeyen oturumda NULL
    print('  servo tetik (§34) uçtan uca testleri geçti')


def sensor_param_testleri():
    """Görev B: gerçek uçağın sensör kalibrasyonu / yönelimi (COMPASS_*, AHRS_ORIENTATION, INS_ACC* kalibrasyonu/kimlikleri) SITL'e yazılmaz
    ("PreArm: Check mag field (xy diff …)" kök nedeni), kayıtta kalır; SITL'in kendi değeri ('sitl' kaynağı) kayda yazılmaz."""
    from app import drone_params as dp
    for ad in ('COMPASS_OFS_X', 'COMPASS_USE2', 'COMPASS_DEC', 'COMPASS_AUTODEC', 'COMPASS_ORIENT', 'COMPASS_PRIO1_ID', 'AHRS_ORIENTATION',
               'INS_ACCOFFS_X', 'INS_ACC2SCAL_Z', 'INS_GYR_ID', 'compass_dia_x'):
        assert dp.sensor_mu(ad), ad
    for ad in ('SERVO1_REVERSED', 'AHRS_EKF_TYPE', 'INS_GYROFFS_X', 'ARSPD_USE', 'COMPAS', 'TRIM_ARSPD_CM'):
        assert not dp.sensor_mu(ad), ad
    assert not dp.haric_mi('COMPASS_OFS_X')   # kayıt/içe aktarma korunur (yalnız SITL'e gitmez)
    rows = [{'name': 'COMPASS_USE2', 'value': 0.0}, {'name': 'COMPASS_OFS_X', 'value': 250.0}, {'name': 'AHRS_ORIENTATION', 'value': 2.0},
            {'name': 'TRIM_ARSPD_CM', 'value': 1500.0}, {'name': 'SERVO1_REVERSED', 'value': 1.0}]
    sitl_r, bilgi = dp.sitl_kayitlari(rows, True, 'sabit_kanat')
    adlar = [x['name'] for x in sitl_r]
    assert adlar == ['TRIM_ARSPD_CM', 'SERVO1_REVERSED', 'SIM_SRV_REV'] and bilgi['sensor_skipped'] == ['COMPASS_USE2', 'COMPASS_OFS_X', 'AHRS_ORIENTATION'], (adlar, bilgi)
    satir = dp.parm_satirlari(rows, True, 'sabit_kanat')
    assert not any(x.startswith(('COMPASS_', 'AHRS_ORIENTATION')) for x in satir) and 'TRIM_ARSPD_CM 1500' in satir, satir
    metin, sev = dp.sensor_olayi(bilgi)
    assert sev == 6 and metin.startswith('3 sensör kalibrasyonu/yönelimi parametresi (COMPASS_USE2, COMPASS_OFS_X, AHRS_ORIENTATION)') and 'Check mag field' in metin, metin
    assert dp.sensor_olayi(dp.sitl_kayitlari([{'name': 'TRIM_ARSPD_CM', 'value': 1.0}], True)[1]) is None
    uzun = dp.sensor_olayi({'sensor_skipped': [f'COMPASS_OFS{i}_X' for i in range(8)]})[0]
    assert '… (+2)' in uzun, uzun
    h = dp.haric_listesi()['sensor']
    assert h['badge'] == dp.SENSOR_ROZET and 'COMPASS_' in h['prefixes'] and 'AHRS_ORIENTATION' in h['names'], h
    # izleyici: tam liste sonrası SITL'in kendi değiştirdiği COMPASS_DEC (AUTODEC) / kalibrasyon ofseti 'sitl' kaydı üretmez
    kayit = []
    eski = dp.kaydet
    dp.kaydet = lambda *a, **k: kayit.append((a, k)) or True
    try:
        izl = dp.Izleyici(1, lambda t, s: None)
        for i, (ad, v) in enumerate((('COMPASS_DEC', 0.0), ('COMPASS_OFS_X', 5.0), ('RTL_ALT', 100.0))):
            izl.param_value(ad, v, 9, i, 3)
        assert izl.taban_tam
        assert izl.param_value('COMPASS_DEC', 0.1056, 9) is None and izl.param_value('COMPASS_OFS_X', 40.0, 9) is None and kayit == []
        izl.param_value('RTL_ALT', 150.0, 9)
        assert len(kayit) == 1 and kayit[0][0][1] == 'RTL_ALT', kayit   # sensör dışı 'sitl' değişikliği eskisi gibi kaydedilir
    finally:
        dp.kaydet = eski
    print('  sensör kalibrasyonu (Görev B: "Check mag field") testleri geçti')


def hedef_icept_testleri(a, c1, sitl):
    """§24 hedefler + §25 INTERCEPTOR: saf kinematik (durum/yerel/latlon), doğrulama sınırları (400), önleme izleyicisi (histerezis, ARM şartı,
    sıfırlama), puan/rozet, ADSB alanları; tailsitter SITL kurulumu (TIP_ESLEME, parm sırası, Q_TAILSIT_ENABLE, itki çarpanı uyumu, güç varsayılanı);
    sahte kipte INTERCEPTOR oturumu (yerde burun yukarı att_body, dikey tırmanış, yatayda görünüm = gövde); hedefli oturumda WS `target` önleme olayı
    (simülasyon hızı 8×), GCS'ye ADSB_VEHICLE, kapanışta drone_sim_runs.targets/intercept_count, özet; kayıttan oynatmada tip + hedefler."""
    from app import db, drone_sitl, flightsim_icept as I, flightsim_power as P, flightsim_replay as R, flightsim_targets as FT
    S = '/api/drone/sim/sessions'
    # --- saf kinematik (ön yüz flightsim_targets.js ile aynı formül; tests/test_flightsim_targets.mjs aynı vektörleri sınar) ---
    h = {'diameter_m': 600, 'speed_ms': 30, 'dir': 'cw', 'phase_deg': 0, 'east_m': 100, 'north_m': -50, 'alt_m': 150}
    s0 = FT.durum(h, 0)
    assert abs(s0['x'] - 400) < 1e-9 and abs(s0['y'] + 50) < 1e-9 and s0['z'] == 150 and abs(s0['heading'] - 180) < 1e-9 and s0['roll'] > 0, s0   # doğu noktası, güneye (cw), sağa yatış
    tur = 2 * math.pi * 300 / 30
    s1 = FT.durum(h, tur / 4)
    assert abs(s1['x'] - 100) < 1e-6 and abs(s1['y'] + 350) < 1e-6 and abs(s1['heading'] - 270) < 1e-6, s1   # çeyrek tur: güney noktası, batıya
    assert abs(math.degrees(s0['roll']) - math.degrees(math.atan(900 / (300 * FT.G)))) < 1e-9
    hc = dict(h, dir='ccw')
    assert abs(FT.durum(hc, 0)['heading'] - 0) < 1e-9 and FT.durum(hc, 0)['roll'] < 0   # ccw: doğu noktasında kuzeye, sola yatış
    lat, lon = FT.latlon(39.9, 32.8, 1000, 2000)
    x, y = FT.yerel(39.9, 32.8, lat, lon)
    assert abs(x - 1000) < 1e-6 and abs(y - 2000) < 1e-6
    # --- doğrulama ---
    assert FT.dogrula(None) is None and FT.dogrula([]) is None and FT.dogrula({'items': []}) is None
    c = FT.dogrula([{'model': 'tgt:lancet', 'alt_m': 150, 'diameter_m': 600}, {'model': 'builtin:quad', 'alt_m': 40, 'diameter_m': 100, 'dir': 'ccw', 'name': '<b>X</b>'}])
    assert c['radius_m'] == FT.YARICAP_VARSAYILAN and len(c['items']) == 2 and c['items'][0]['speed_ms'] == round(110 / 3.6, 2) and c['items'][0]['dir'] == 'cw'
    assert c['items'][1]['phase_deg'] == 137.5 and c['items'][1]['name'] == 'bX/b' and c['items'][0]['glb_url'] == '/static/simumav/models/tgt_lancet.glb', c   # isim temizlenir; görsel bilgi gömülü
    kotu = [[{'model': 'yok', 'alt_m': 100, 'diameter_m': 300}], [{'model': 'tgt:lancet', 'alt_m': 9, 'diameter_m': 300}], [{'model': 'tgt:lancet', 'alt_m': 3001, 'diameter_m': 300}],
            [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 49}], [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 5001}], [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 300, 'speed_ms': 84}],
            [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 300, 'dir': 'up'}], [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 300, 'east_m': 20001}],
            [{'model': 'tgt:lancet', 'alt_m': True, 'diameter_m': 300}], [{'model': 'tgt:lancet'}] * 9, {'items': [{'model': 'tgt:lancet'}], 'radius_m': 4}, 'x', [5]]
    for k in kotu:
        try:
            FT.dogrula(k); raise AssertionError(k)
        except FT.HedefHata:
            pass
    assert FT.dogrula([{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 300, 'speed_ms': 83.33}])['items'][0]['speed_ms'] == 83.33   # azami hız sınırında kabul
    # --- önleme izleyicisi: hedefin üstünden geç (ARM'lı) → 1 önleme; histerezis içinde kal → yeni sayılmaz; uzaklaş + geri gel → 2.; disarm'da sayılmaz ---
    cfg = FT.dogrula({'items': [{'model': 'tgt:sw300', 'alt_m': 100, 'diameter_m': 400, 'speed_ms': 20}], 'radius_m': 20})
    iz = FT.HedefIzleyici(cfg)
    st = FT.durum(cfg['items'][0], 30)
    assert iz.adim(10, 0, 0, 0, True) == []                                        # ARM t=10
    o = iz.adim(30, st['x'] + 5, st['y'], st['z'], True)
    assert len(o) == 1 and o[0]['first'] and o[0]['n'] == 1 and o[0]['after_s'] == 20.0 and o[0]['dist_m'] == 5.0, o
    st = FT.durum(cfg['items'][0], 31)
    assert iz.adim(31, st['x'] + 25, st['y'], st['z'], True) == []                  # 25 m < 1,5 × 20 → hâlâ içeride
    st = FT.durum(cfg['items'][0], 32)
    assert iz.adim(32, st['x'] + 40, st['y'], st['z'], True) == []                  # çıktı
    st = FT.durum(cfg['items'][0], 33)
    o = iz.adim(33, st['x'], st['y'], st['z'] + 3, True)
    assert len(o) == 1 and o[0]['n'] == 2 and not o[0]['first'], o
    st = FT.durum(cfg['items'][0], 40)
    iz.adim(39, 0, 0, 0, True)
    assert iz.adim(40, st['x'], st['y'], st['z'], False) == []                       # disarm: önleme yok
    oz = iz.ozet()
    assert oz['total'] == 2 and oz['hit_targets'] == 1 and oz['all_hit'] and oz['items'][0]['first_s'] == 20.0 and oz['items'][0]['min_dist_m'] == 0.0, oz
    assert oz['score'] == 1000 - 100 + 100 + 150 and set(oz['badges']) == {'first', 'quick', 'close'}, oz   # tek hedef: 'ace' yok
    iz.adim(1, 0, 0, 0, False)                                                      # SITL yeniden başladı (t geri): ARM zamanı yeniden ölçülür
    assert iz.t_arm is None and not iz.iz[0]['inside']
    p2 = FT.puan({'items': [{'intercepts': 1, 'first_s': 300, 'min_dist_m': 9}, {'intercepts': 3, 'first_s': 10, 'min_dist_m': 2}], 'all_hit': True, 'count': 2, 'total': 5})
    assert p2 == {'score': max(200, 1000 - 1500) + (950 + 200 + 150), 'badges': ['first', 'quick', 'ace', 'close', 'hunter']}, p2
    ad = FT.adsb_alanlari(cfg, 39.925, 32.837, 900.0, 0.0)
    assert len(ad) == 1 and ad[0][0] == FT.ADSB_ICAO_TABANI and ad[0][3] == 1 and ad[0][4] == int((900 + 100) * 1000) and ad[0][6] == 2000 and ad[0][8] == b'TGT1', ad
    # --- §25 tailsitter kurulumu ---
    assert drone_sitl.TIP_ESLEME['interceptor'] == ('arduplane', 'quadplane-copter_tailsitter') and drone_sitl.model_tipi('Tailsitter önleyici') == 'interceptor'
    pm = drone_sitl.parm_metni(1, False, ['Q_TAILSIT_ENABLE 0', 'AIRSPEED_MAX 99'], 'interceptor').splitlines()
    assert pm.index('Q_TAILSIT_ENABLE 1') < pm.index('Q_TAILSIT_ENABLE 0') and 'Q_TAILSIT_MOTMX 3' in pm and 'Q_FRAME_CLASS 1' in pm and 'Q_RTL_MODE 1' in pm, pm[:8]   # tip seti önce, kayıtlı sonra (son söz kaydın)
    assert 'Q_TAILSIT_ENABLE 1' not in drone_sitl.parm_metni(1, False, None, 'sabit_kanat')
    assert abs(I.tam_gaz_hizi(4) - 95.1) < 0.5 and abs(I.tam_gaz_hizi(7) - 117.3) < 0.5 and 6.0 < I.thr_mul_icin(111.1) < 6.2 and I.thr_mul_icin(10) == 0.1, I.thr_mul_icin(111.1)   # ölçüm uyumu (CRUISE seviye uçuş)
    assert dict(P.hiz_parametreleri(111.1, None, True, tip='interceptor'))['SIM_PLN_THR_MUL'] == I.thr_mul_icin(111.1) and P.dogrula(None, 'interceptor')['max_speed_ms'] == 111.1
    assert P.dogrula(None, 'interceptor')['fuel_l'] == 0.0 and abs(P.stok_hiz('interceptor') - math.sqrt(I.HIZ_A + I.HIZ_B)) < 1e-9
    # --- sahte kipte INTERCEPTOR oturumu + hedefler ---
    for govde in ({'type': 'interceptor', 'center_id': c1['id'], 'targets': [{'model': 'yok'}]}, {'type': 'interceptor', 'center_id': c1['id'], 'targets': {'items': [], 'radius_m': 500}},
                  {'type': 'interceptor', 'center_id': c1['id'], 'targets': [{'model': 'tgt:lancet', 'alt_m': 100, 'diameter_m': 10}]}):
        assert a.post(S, json=govde).status_code == 400, govde
    assert bekle(lambda: len(sitl.baglar) == 1 or None, 5) or len(sitl.baglar) == 0
    hedef = {'model': 'tgt:octopus', 'alt_m': 30, 'diameter_m': 300, 'speed_ms': 30, 'dir': 'cw', 'phase_deg': 0, 'name': 'Av'}
    s = ok(a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'targets': {'items': [hedef], 'radius_m': 25}}), 201)
    sid = s['id']
    assert s['vertical'] is True and s['model']['id'] == 'builtin:icept_x4' and s['model']['glb_url'] == '/static/simumav/models/icept_x4.glb' and s['launch']['method'] == 'wheels', s['model']
    assert s['power']['max_speed_ms'] == 111.1 and s['targets']['radius_m'] == 25 and s['targets']['items'][0]['glb_url'] == '/static/simumav/models/tgt_octopus.glb', s['targets']
    assert s['targets_state']['count'] == 1 and s['targets_state']['total'] == 0
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    token = a.cookies.get(auth.COOKIE)
    gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs.settimeout(2)
    try:
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            hl = json.loads(ws.receive_text())
            assert hl['t'] == 'hello' and hl['session']['targets']['items'][0]['name'] == 'Av'
            m = ws_bekle(ws, lambda m: m['t'] == 'tele')
            assert m['att_body'][1] == round(math.pi / 2, 4) and m['pitch'] == 0, m.get('att_body')   # yerde kuyruk üstünde: gövde burun yukarı, görünüm düz
            # GCS: ilk paket kilitler → ADSB_VEHICLE (msgid 246) 2 Hz
            gcs.sendto(b'\xfd\x09\x00\x00\x00\xff\xbe\x00\x00\x00' + b'\x00' * 11, ('127.0.0.1', s['udp_port']))
            from pymavlink.dialects.v20 import ardupilotmega as d
            par = d.MAVLink(None); par.robust_parsing = True
            adsb, bitis = None, time.time() + 3
            while time.time() < bitis and adsb is None:
                try:
                    data, _ = gcs.recvfrom(4096)
                except socket.timeout:
                    break
                for msg in par.parse_buffer(data) or []:
                    if msg.get_type() == 'ADSB_VEHICLE':
                        adsb = msg
            assert adsb is not None and adsb.ICAO_address == FT.ADSB_ICAO_TABANI and adsb.callsign.rstrip('\x00') == 'TGT1' and adsb.get_srcComponent() == FT.ADSB_COMP, adsb
            assert abs(adsb.altitude / 1000 - (900 + 30)) < 0.01 and adsb.hor_velocity == 3000 and adsb.flags & 0x40
            # dikey kalkış (30 m): tırmanırken yatay hız 0, gövde burun yukarı; hedef irtifada yatay daire, görünüm = gövde
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 30}, 'rid': 'i1'}))
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'speed', 'params': {'factor': 8}, 'rid': 'i2'}))
            m = ws_bekle(ws, lambda m: m['t'] == 'tele' and 5 < m['alt_rel'] < 25, 5)
            assert m and m['groundspeed'] == 0 and m['att_body'][1] == round(math.pi / 2, 4) and m['mode'] == 'GUIDED', m
            m = ws_bekle(ws, lambda m: m['t'] == 'tele' and m['alt_rel'] >= 30 and m['groundspeed'] > 1, 5)
            assert m and m['att_body'] == [m['roll'], m['pitch'], m['yaw']], m
            # önleme: sahte dron R=150 m saat yönünde 12 m/s, hedef aynı dairede 30 m/s → 8× hızda ~8 sn içinde yakalar
            ev = ws_bekle(ws, lambda m: m['t'] == 'target', 20)
            assert ev and ev['kind'] == 'intercept' and ev['first'] and ev['name'] == 'Av' and ev['dist_m'] <= 25 and ev['state']['total'] == 1, ev
            olay = ws_bekle(ws, lambda m: m['t'] == 'event' and 'ÖNLEME' in m['text'], 3)
            assert olay and olay['severity'] == 5, olay
    finally:
        gcs.close()
    g = ok(a.get(f'{S}/{sid}'))
    assert g['targets_state']['total'] >= 1 and g['targets_state']['score'] > 0
    sm = ok(a.get(f'{S}/{sid}/summary'))
    assert sm['targets']['total'] >= 1 and sm['session']['type'] == 'interceptor', sm.get('targets')
    ok(a.delete(f'{S}/{sid}'))
    it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT type, targets, intercept_count FROM drone_sim_runs WHERE id = ?', (it['id'],)))
    tj = json.loads(row['targets'])
    assert row['type'] == 'interceptor' and row['intercept_count'] >= 1 and tj['config']['items'][0]['model'] == 'tgt:octopus' and tj['result']['total'] == row['intercept_count'], row
    # kayıttan oynatma: kaydın tipi (INTERCEPTOR; firmware adı ArduPlane der) + hedefleri
    with db.connect() as conn:
        lid = conn.execute('SELECT MAX(id) FROM flight_logs').fetchone()[0]
        conn.execute('UPDATE drone_sim_runs SET bin_log_id = ? WHERE id = ?', (lid, it['id']))
        conn.commit()
    try:
        r = R.ReplaySession(1, {'id': lid, 'file_name': 'i.bin', 'vehicle': 'ArduPlane'}, {}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        rd = r.to_dict()
        assert r.type == 'interceptor' and rd['vertical'] is True and rd['targets']['items'][0]['name'] == 'Av' and r.model['id'] == 'builtin:icept_x4', rd.get('targets')
    finally:
        with db.connect() as conn:
            conn.execute('UPDATE drone_sim_runs SET bin_log_id = NULL WHERE id = ?', (it['id'],))
            conn.commit()
    assert 'body' in R.FIELDS and R.ONBELLEK_SURUM >= 4 and 'SIM' in R.BIN_TIPLERI and 'SIM' in R.BIN_SUTUNLAR   # v5: hızlı ikili yol (§8.3) da SIM okur
    # meta: hedef kataloğu + INTERCEPTOR modelleri
    m = ok(a.get('/api/drone/sim/meta'))
    keys = {x['key'] for x in m['targets']['models']}
    assert {'tgt:sw300', 'tgt:lancet', 'tgt:altius', 'tgt:octopus', 'builtin:icept_x4', 'builtin:quad'} <= keys and m['targets']['max'] == 8, keys
    mods = ok(a.get('/api/drone/sim/models', params={'type': 'interceptor'}))
    assert {x['id'] for x in mods['models'] if x['source'] == 'builtin'} == {'builtin:icept_x4', 'builtin:p1sun', 'builtin:sting'}, mods['models']
    print('  hedefler (§24) + INTERCEPTOR (§25) testleri geçti')


def firlatici_testleri(a, c1):
    """§27 INTERCEPTOR fırlatıcıları: world.launch doğrulaması (yöntem, loaded, aim_*; 400'ler), tipe göre normalizasyon, nişan noktası (istemci
    aimWaypoint ile birebir vektörler), sahte kipte kalkış aşamaları (kutu: armed → launch → released; el: nişan alanları + nişan yönünde tırmanış),
    `cmd takeoff {aim}` doğrulaması, görevde hücre sırası, drone_sim_runs.launch kaydı ve kayıttan oynatmada fırlatıcı türü (kayıttan önerilir)."""
    from app import db, flightsim_launcher as FL, flightsim_replay as R
    S = '/api/drone/sim/sessions'
    # --- doğrulama / normalizasyon ---
    assert flightsim.LAUNCH_METHODS == ('wheels', 'ramp', 'vehicle', 'pod4', 'pod8', 'tube', 'handheld')
    assert flightsim.launch_dogrula({'method': 'pod4'}) == {'method': 'pod4', 'angle_deg': 15, 'release_kmh': 70, 'loaded': 4}
    assert flightsim.launch_dogrula({'method': 'pod8', 'loaded': 5})['loaded'] == 5 and 'loaded' not in flightsim.launch_dogrula({'method': 'tube'})
    h = flightsim.launch_dogrula({'method': 'handheld', 'aim_az_deg': 360, 'aim_el_deg': 85})
    assert h['aim_az_deg'] == 0.0 and h['aim_el_deg'] == 85.0, h
    assert flightsim.launch_dogrula({'method': 'handheld'})['aim_el_deg'] == FL.AIM_DEFAULTS['aim_el_deg']
    assert flightsim.launch_dogrula({'method': 'ramp'}) == {'method': 'ramp', 'angle_deg': 15, 'release_kmh': 70}   # sabit kanat gövdesi değişmedi
    for bad in ({'method': 'pod4', 'loaded': 5}, {'method': 'pod4', 'loaded': 0}, {'method': 'pod8', 'loaded': 2.5}, {'method': 'pod8', 'loaded': True},
                {'method': 'handheld', 'aim_el_deg': 9}, {'method': 'handheld', 'aim_el_deg': 86}, {'method': 'handheld', 'aim_az_deg': -1},
                {'method': 'handheld', 'aim_az_deg': 361}, {'method': 'handheld', 'aim_az_deg': '10'}, {'method': 'hand'}, {'method': 'pod16'}):
        assert a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'world': {'launch': bad}}).status_code == 400, bad
    n = flightsim.launch_normalize
    assert n('interceptor', {'method': 'pod8', 'loaded': 3})['method'] == 'pod8' and n('interceptor', {'method': 'ramp'})['method'] == 'wheels'
    sk = n('sabit_kanat', {'method': 'handheld', 'aim_az_deg': 10.0, 'aim_el_deg': 30.0})
    assert sk['method'] == 'wheels' and 'aim_az_deg' not in sk and 'aim_el_deg' not in sk, sk
    assert n('vtol', {'method': 'pod4', 'loaded': 2})['method'] == 'wheels' and n('sabit_kanat', {'method': 'ramp'})['method'] == 'ramp'
    # nişan noktası: istemci aimWaypoint (tests/test_flightsim_launcher.mjs AIM_VECTORS) ile birebir
    for az, el, beklenen in ((0, 10, {'east_m': 0.0, 'north_m': 492.4, 'alt_m': 86.82, 'horiz_m': 492.4}), (90, 30, {'east_m': 433.01, 'north_m': 0.0, 'alt_m': 250.0, 'horiz_m': 433.01}),
                             (225, 45, {'east_m': -247.49, 'north_m': -247.49, 'alt_m': 350.0, 'horiz_m': 350.0}), (300, 80, {'east_m': -103.92, 'north_m': 60.0, 'alt_m': 350.0, 'horiz_m': 120.0})):
        assert FL.aim_noktasi(az, el) == beklenen, (az, el, FL.aim_noktasi(az, el))
    assert FL.aim_dogrula(None) is None and FL.aim_dogrula({'az_deg': 360, 'el_deg': 45}) == (0.0, 45.0)
    for bad in ({'az_deg': 10}, {'az_deg': 10, 'el_deg': 5}, 'x', {'az_deg': True, 'el_deg': 30}):
        try:
            FL.aim_dogrula(bad); raise AssertionError(bad)
        except FL.LauncherHata:
            pass
    assert FL.firlatici_sayisi('pod4', 10) == 3 and FL.firlatici_sayisi('pod8', 12) == 2 and FL.firlatici_sayisi('tube', 10) == 1 and FL.firlatici_sayisi('ramp', 5) == 0
    assert FL.etiket({'method': 'pod4', 'loaded': 3}) == "4'lü fırlatıcı (3 dolu)" and FL.etiket({'method': 'handheld', 'aim_az_deg': 40, 'aim_el_deg': 30}) == 'El fırlatıcısı 30° / 40°'
    token = a.cookies.get(auth.COOKIE)
    # --- 4'lü kutu: sahte kipte aşamalar ---
    s = ok(a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'world': {'launch': {'method': 'pod4', 'loaded': 3}}}), 201)
    sid = s['id']
    assert s['launch'] == {'method': 'pod4', 'angle_deg': 15, 'release_kmh': 70, 'loaded': 3, 'phase': None}, s['launch']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hl = json.loads(ws.receive_text())
        assert hl['t'] == 'hello' and hl['session']['launch']['method'] == 'pod4'
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 40}, 'rid': 'p1'}))
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'speed', 'params': {'factor': 4}, 'rid': 'p2'}))
        fazlar, bitis = [], time.time() + 10
        while time.time() < bitis and (not fazlar or fazlar[-1]['phase'] != 'released'):
            m = json.loads(ws.receive_text())
            if m['t'] == 'launch':
                fazlar.append(m)
        assert [f['phase'] for f in fazlar] == ['armed', 'launch', 'released'] and all(f['method'] == 'pod4' for f in fazlar), fazlar
        m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['alt_rel'] > 5, 6)
        assert m and m['groundspeed'] == 0 and m['att_body'][1] == round(math.pi / 2, 4), m   # kutudan dikey (kuyruk üstünde)
    assert ok(a.get(f'{S}/{sid}'))['launch']['phase'] == 'released'
    ok(a.delete(f'{S}/{sid}'))
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT launch FROM drone_sim_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1', (sid,)))
    assert json.loads(row['launch'])['method'] == 'pod4' and json.loads(row['launch'])['loaded'] == 3, row
    # --- el fırlatıcısı: canlı nişan (cmd takeoff aim) + nişan yönünde tırmanış ---
    s = ok(a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'world': {'launch': {'method': 'handheld', 'aim_az_deg': 10, 'aim_el_deg': 20}}}), 201)
    sid = s['id']
    assert s['launch']['aim_az_deg'] == 10.0 and s['launch']['aim_el_deg'] == 20.0
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    assert a.post(f'{S}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40, 'aim': {'az_deg': 90, 'el_deg': 5}}}).status_code == 400
    assert a.post(f'{S}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 40, 'aim': [90, 30]}}).status_code == 400
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        json.loads(ws.receive_text())
        t0 = ws_bekle(ws, lambda x: x['t'] == 'tele')
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 40, 'aim': {'az_deg': 90, 'el_deg': 30}}, 'rid': 'h1'}))
        fazlar, bitis = [], time.time() + 10
        while time.time() < bitis and (not fazlar or fazlar[-1]['phase'] != 'released'):
            m = json.loads(ws.receive_text())
            if m['t'] == 'launch':
                fazlar.append(m)
        assert [f['phase'] for f in fazlar] == ['armed', 'launch', 'released'], fazlar
        assert fazlar[1]['aim_az_deg'] == 90.0 and fazlar[1]['aim_el_deg'] == 30.0 and fazlar[1]['method'] == 'handheld', fazlar[1]
        m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['alt_rel'] > 6, 8)
        assert m, 'tırmanış yok'
        de = (m['lon'] - t0['lon']) * 111320.0 * math.cos(math.radians(t0['lat'])); dn = (m['lat'] - t0['lat']) * 110574.0
        assert de > 5 and abs(dn) < de * 0.1, (de, dn)   # doğuya (az 90°)
        assert abs(math.degrees(math.atan2(m['alt_rel'], math.hypot(de, dn))) - 30) < 6, (m['alt_rel'], de)   # tan(30°) eğimiyle
        assert abs(m['att_body'][1] - math.radians(30)) < 0.01 and abs(m['att_body'][2] - math.radians(90)) < 0.01, m['att_body']   # gövde nişan açısında
    g = ok(a.get(f'{S}/{sid}'))
    assert g['launch']['aim_az_deg'] == 90.0 and g['launch']['phase'] == 'released', g['launch']
    ok(a.delete(f'{S}/{sid}'))
    it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
    # --- kayıttan oynatma: istekte fırlatıcı yoksa canlı oturumunki ---
    with db.connect() as conn:
        lid = conn.execute("INSERT INTO flight_logs (task_id, file, file_name, size, status, analysis, uploaded_by, uploaded_at) VALUES (NULL, 'flightlogs/l.bin', 'l.bin', 1, 'TAMAM', '{}', 1, ?)", (db.now(),)).lastrowid
        conn.execute('UPDATE drone_sim_runs SET bin_log_id = ? WHERE id = ?', (lid, it['id']))
        conn.commit()
    try:
        r = R.ReplaySession(2, {'id': lid, 'file_name': 'l.bin', 'vehicle': 'ArduPlane'}, {}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        assert r.type == 'interceptor' and r.launch['method'] == 'handheld' and r.launch['aim_az_deg'] == 90.0, r.launch
        r2 = R.ReplaySession(3, {'id': lid, 'file_name': 'l.bin', 'vehicle': 'ArduPlane'}, {'launch': {'method': 'pod8'}}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        assert r2.launch['method'] == 'pod8', r2.launch   # istekte seçilen fırlatıcı öncelikli
        with db.connect() as conn:
            lst = [x for x in R.loglari_listele(conn, {'modules': ['tools']}) if x['id'] == lid]
        assert lst and lst[0]['type'] == 'interceptor' and lst[0]['sim_launch']['method'] == 'handheld', lst
    finally:
        with db.connect() as conn:
            conn.execute('UPDATE drone_sim_runs SET bin_log_id = NULL WHERE id = ?', (it['id'],))
            conn.execute('DELETE FROM flight_logs WHERE id = ?', (lid,))
            conn.commit()
    # --- görev: 8'li kutu + "Yer kontrolünü koru": hücre sırası olayda ---
    s = ok(a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'world': {'launch': {'method': 'pod8'}}, 'site': {'station': True},
                           'defend': {'seed': 5, 'waves': 1, 'interceptors': 12, 'prep_s': 300}}), 201)
    sid = s['id']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 30}, 'rid': 'd1'}))
        m = ws_bekle(ws, lambda x: x['t'] == 'launch' and x['phase'] == 'launch', 5)
        assert m and m['cell'] == 1 and m['method'] == 'pod8', m
    ok(a.delete(f'{S}/{sid}'))
    print('  fırlatıcı (§27) testleri geçti')


def gcs_testleri(a, c1, sitl):
    """§26 yer kontrol sahası + "Yer kontrolünü koru": saf fonksiyonlar (doğrulama 400'leri, yerleşim, radar/EO, mulberry32 — ön yüzle aynı vektörler,
    plan determinizmi, tehdit kinematiği, önleme/sızma/bitiş, yeniden konuşlandırma ve görev saati tabanı, puan/rütbe); sahte kipte oturum: site/defend
    alanları, WS `defend` (dalga, doğuş, sızma) 8× hızda, `defend next` (uçmamış → ücretsiz; uçmuş → harcanır; SITL yeniden başlar, taban sürer),
    reset = konuşlandırma, özet + drone_sim_runs.targets (site/defend), kayıttan oynatmada plan + sonuç; tip INTERCEPTOR değilse 400."""
    from app import db, flightsim_gcs as GC, flightsim_replay as R
    S = '/api/drone/sim/sessions'
    # --- doğrulama ---
    assert GC.gcs_dogrula(None) is None and GC.gcs_dogrula({}) is None and GC.gcs_dogrula({'station': False, 'radar': False, 'eo': False}) is None
    g = GC.gcs_dogrula({'station': True, 'radar': True, 'eo': True})
    assert g == {'station': True, 'radar': True, 'radar_km': 20.0, 'eo': True, 'eo_km': 5.0}, g
    assert GC.gcs_dogrula({'radar': True, 'radar_km': 50, 'eo': True, 'eo_km': 0.5})['radar_km'] == 50.0
    for kotu in ({'radar': 1}, {'radar': True, 'radar_km': 0.9}, {'radar': True, 'radar_km': 51}, {'eo': True, 'eo_km': 15.5}, {'eo': True, 'eo_km': float('nan')},
                 {'radar': True, 'radar_km': '20'}, {'radar': True, 'radar_km': True}, {'radar': True, 'x': 1}, 'x', [1], {'station': 'evet'}):
        try:
            GC.gcs_dogrula(kotu); raise AssertionError(kotu)
        except GC.GcsHata:
            pass
    d = GC.savunma_dogrula({'seed': 7}, 'interceptor')
    assert d == {'waves': 5, 'interceptors': 10, 'difficulty': 'normal', 'radius_m': 30.0, 'prep_s': 45.0, 'seed': 7}, d
    assert GC.savunma_dogrula(None) is None and 1 <= GC.savunma_dogrula({}, 'interceptor')['seed'] <= 2 ** 31 - 1
    for kotu, tip in (({}, 'sabit_kanat'), ({'waves': 0}, None), ({'waves': 11}, None), ({'interceptors': 21}, None), ({'interceptors': 2.5}, None), ({'radius_m': 5}, None),
                      ({'prep_s': 301}, None), ({'difficulty': 'nightmare'}, None), ({'seed': -1}, None), ({'seed': 2 ** 31}, None), ({'seed': True}, None), ({'evil': 1}, None), ('x', None)):
        try:
            GC.savunma_dogrula(kotu, tip); raise AssertionError((kotu, tip))
        except GC.GcsHata:
            pass
    # --- yerleşim / radar / EO (tests/test_flightsim_gcs.mjs aynı değerleri sınar) ---
    y0, y90 = GC.yerlesim(0), GC.yerlesim(90)
    assert y0['station'] == {'x': 55.0, 'y': -40.0, 'yaw_deg': 0.0} and y0['tower'] == {'x': 85.0, 'y': -40.0, 'yaw_deg': 0.0} and y0['rack'] == {'x': 34.0, 'y': -14.0, 'yaw_deg': 0.0}, y0
    assert y90['station'] == {'x': -40.0, 'y': -55.0, 'yaw_deg': 90.0}, y90   # pist doğuya: ileri +x, sağ −y
    assert GC.radar_kapsar(g, y0['tower'], 85 + 19999, -40) and not GC.radar_kapsar(g, y0['tower'], 85 + 20001, -40) and not GC.radar_kapsar(None, y0['tower'], 85, -40)
    lk = GC.eo_bakis(y0['tower'], 85, 960, 18 + 1000)
    assert abs(lk['az']) < 1e-9 and abs(lk['el'] - 45) < 1e-9 and abs(lk['range_m'] - 1000 * math.sqrt(2)) < 1e-6, lk
    assert abs(GC.eo_bakis(y0['tower'], 85 - 100, -40, 18)['az'] - 270) < 1e-9
    r = GC.mulberry32(42)
    assert [r(), r(), r()] == [0.6011037519201636, 0.44829055899754167, 0.8524657934904099]
    # --- plan: deterministik, sınırlar ---
    cfg = GC.savunma_dogrula({'seed': 12345}, 'interceptor')
    p1, p2 = GC.savunma_plani(cfg), GC.savunma_plani(dict(cfg))
    assert p1 == p2 and len(p1) == 2 + 3 + 4 + 5 + 6, len(p1)
    assert [p1[0][k] for k in ('model', 'spawn_t', 'bearing_deg', 'dist_m', 'alt_m', 'dive_deg', 'cruise_ms', 'dive_ms')] == ['tgt:octopus', 45.0, 110.43, 4452.6, 395.4, 37.74, 55.56, 70.83], p1[0]
    assert p1[0]['glb_url'] == '/static/simumav/models/tgt_octopus.glb' and p1[0]['damage'] == 20.0 and p1[0]['name'] == 'Octopus-100 · T1'
    assert GC.savunma_plani(dict(cfg, seed=12346)) != p1
    for th in p1:
        assert 3000 <= th['dist_m'] <= 6000 * 1.16 and 150 <= th['alt_m'] <= 450 and 25 <= th['dive_deg'] <= 50 and th['dive_ms'] > th['cruise_ms'] and th['model'] in GC.TEHDIT_MODELLERI, th
    zor = GC.savunma_plani(GC.savunma_dogrula({'seed': 1, 'waves': 10, 'difficulty': 'hard'}, 'interceptor'), False)
    assert len(zor) == GC.TEHDIT_MAX and all(th['wave'] < 10 for th in zor)
    # --- kinematik: seyir → dalış → çarpma (istasyon çatısı) ---
    ist = {'x': 55.0, 'y': -40.0, 'z': GC.ISTASYON_Z}
    th = dict(p1[0])
    geo = GC.tehdit_geometri(th, ist)
    assert GC.tehdit_durum(th, 44.9, ist) is None
    s0 = GC.tehdit_durum(th, 45.0, ist)
    assert abs(math.hypot(s0['x'] - 55, s0['y'] + 40) - 4452.6) < 1e-6 and s0['z'] == 395.4 and s0['phase'] == 'cruise' and abs(s0['heading'] - (110.43 + 180) % 360) < 1e-9
    s1 = GC.tehdit_durum(th, 45 + geo['tc'] + geo['td'] / 2, ist)
    assert s1['phase'] == 'dive' and abs(s1['z'] - (395.4 + GC.ISTASYON_Z) / 2) < 1e-6 and s1['pitch'] < 0 and s1['vz'] < 0, s1
    s2 = GC.tehdit_durum(th, geo['t_impact'] + 5, ist)
    assert s2['phase'] == 'impact' and abs(s2['x'] - 55) < 1e-6 and abs(s2['y'] + 40) < 1e-6 and abs(s2['z'] - GC.ISTASYON_Z) < 1e-9
    assert abs(math.degrees(-s1['pitch']) - math.degrees(math.atan2(395.4 - GC.ISTASYON_Z, geo['dd']))) < 1e-9
    # --- izleyici: önleme (yarıçap içinde ARM'lı), sızma (sağlık), bitiş; görev saati tabanı (tbm geri sarma) ---
    sv = GC.SavunmaGorevi(GC.savunma_dogrula({'seed': 12345, 'waves': 1, 'prep_s': 15}, 'interceptor'), y0)
    assert len(sv.plan) == 2 and sv.durum()['health'] == 100 and sv.durum()['remaining'] == 9
    ev = sv.adim(15000, 0, 0, 0, False)
    assert [e['kind'] for e in ev] == ['wave', 'spawn'] and ev[0]['wave'] == 1 and ev[0]['count'] == 2, ev
    k0 = GC.tehdit_durum(sv.plan[0], 20.0, sv.ist)
    ev = sv.adim(20000, k0['x'] + 10, k0['y'], k0['z'], False)
    assert not [e for e in ev if e['kind'] == 'kill'], ev                              # disarm: önleme yok
    ev = sv.adim(20000, k0['x'] + 10, k0['y'], k0['z'], True)
    kill = [e for e in ev if e['kind'] == 'kill']
    assert len(kill) == 1 and kill[0]['k'] == 0 and kill[0]['dist_m'] == 10.0 and kill[0]['ttk_s'] == 5.0 and kill[0]['interceptor'] == 1 and kill[0]['station_m'] > 3000, kill
    assert sv.durum()['killed'] == [[0, 20.0]] and sv.icept['armed']
    # sıradaki interceptor: uçmuş → harcanır; görev saati SITL geri sarmasında sürer
    assert sv.konuslandir() is True and sv.icept['used'] == 2 and not sv.icept['armed']
    assert sv.konuslandir() is False and sv.icept['used'] == 2                         # uçmamış → ücretsiz
    sv.adim(3000, 0, 0, 0, False)                                                     # yeni SITL: tbm 3 sn → görev saati 23 sn
    assert abs(sv.t - 23.0) < 1e-9 and sv.taban == 20.0, (sv.t, sv.taban)
    g1 = GC.tehdit_geometri(sv.plan[1], sv.ist)
    ev = sv.adim(int((g1['t_impact'] - 20.0 + 0.5) * 1000), 0, 0, 0, False)
    leak = [e for e in ev if e['kind'] == 'leak']
    end = [e for e in ev if e['kind'] == 'end']
    assert len(leak) == 1 and leak[0]['health'] == 100 - sv.plan[1]['damage'] and end and end[0]['success'] is True and end[0]['reason'] == 'all_resolved', ev
    oz = end[0]['result']
    assert oz['spawned'] == 2 and len(oz['kills']) == 1 and len(oz['leaks']) == 1 and oz['accuracy'] == 0.5 and oz['icept'] == {'total': 10, 'used': 2, 'lost': 1}, oz
    beklenen = 300 + min(400, int(round(kill[0]['station_m'] / 10))) + 195 - 250 + int(round(oz['health'])) * 10 + 800 + 1000
    assert oz['score'] == beklenen and oz['rank'] == GC.rutbe(0.65 * 0.5 + 0.35 * oz['health'] / 100) and oz['rank_name'] == GC.RUTBE_TR[oz['rank']], (oz['score'], beklenen, oz['rank'])
    assert sv.adim(999999, 0, 0, 0, True) == []                                        # bitti: olay yok
    sv2 = GC.SavunmaGorevi(dict(cfg, interceptors=1), y0)
    sv2.icept['armed'] = True
    try:
        sv2.konuslandir(); raise AssertionError('raf boşken konuşlandırıldı')
    except GC.GcsHata:
        pass
    sv3 = GC.SavunmaGorevi(GC.savunma_dogrula({'seed': 5, 'waves': 3, 'difficulty': 'hard'}, 'interceptor'), y0)   # hiç önleme yok: istasyon düşer
    son = []
    for t in range(0, 2000, 2):
        son = sv3.adim(t * 1000, 0, 0, 0, False) or son
        if sv3.bitti:
            break
    assert sv3.bitti and sv3.bitti['success'] is False and sv3.bitti['reason'] == 'station_destroyed' and sv3.health == 0 and sv3.ozet()['rank'] == 'private', sv3.bitti
    assert GC.savunma_puan({'kills': [], 'leaks': [{}] * 20, 'health': 0, 'icept': {'total': 1, 'used': 1}, 'spawned': 20})['score'] == 0   # ≥ 0
    # --- sahte kipte oturum ---
    assert a.post(S, json={'type': 'sabit_kanat', 'center_id': c1['id'], 'defend': {'seed': 1}}).status_code == 400
    assert a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'site': {'radar': True, 'radar_km': 99}}).status_code == 400
    assert a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'defend': {'waves': 'çok'}}).status_code == 400
    s = ok(a.post(S, json={'type': 'interceptor', 'center_id': c1['id'], 'site': {'station': False, 'radar': True, 'radar_km': 12, 'eo': False},
                           'defend': {'seed': 12345, 'waves': 1, 'prep_s': 15, 'interceptors': 3}}), 201)
    sid = s['id']
    assert s['site']['station'] is True and s['site']['radar_km'] == 12 and s['site']['eo'] is False and s['site']['layout']['tower'] == y0['tower'], s['site']   # görev istasyonu açar
    assert s['gcs']['connected'] is False   # 'gcs' = Mission Planner bağlantısı (çakışma yok)
    D = s['defend']
    assert D['config']['seed'] == 12345 and len(D['plan']) == 2 and D['plan'][0]['glb_url'] and D['station'] == {'x': 55.0, 'y': -40.0, 'z': GC.ISTASYON_Z} and D['state']['remaining'] == 2, D['state']
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    token = a.cookies.get(auth.COOKIE)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        hl = json.loads(ws.receive_text())
        assert hl['session']['defend']['config']['waves'] == 1 and hl['session']['site']['radar'] is True
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'speed', 'params': {'factor': 8}, 'rid': 'g1'}))
        m = ws_bekle(ws, lambda m: m['t'] == 'defend' and m['kind'] == 'wave', 12)
        assert m and m['wave'] == 1 and m['count'] == 2 and m['state']['wave'] == 1, m
        m = ws_bekle(ws, lambda m: m['t'] == 'event' and 'DALGA 1/1' in m['text'], 3)
        assert m and m['severity'] == 4, m
        # uçmamış interceptor: yeniden konuşlandırma ücretsiz
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'defend', 'params': {'action': 'next'}, 'rid': 'g2'}))
        m = ws_bekle(ws, lambda m: m['t'] == 'defend' and m['kind'] == 'next', 5)
        assert m and m['spent'] is False and m['state']['icept']['used'] == 1, m
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    r = a.post(f'{S}/{sid}/cmd', json={'name': 'defend', 'params': {'action': 'yok'}})
    assert r.status_code == 400
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'arm'}))
    assert bekle(lambda: flightsim.MANAGER.get(sid).savunma.icept['armed'] or None, 5)
    t_once = flightsim.MANAGER.get(sid).savunma.t
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'reset'}))                                   # görevde Sıfırla = konuşlandırma (uçmuş → harcanır)
    sess = flightsim.MANAGER.get(sid)
    assert sess.savunma.icept['used'] == 2 and sess.savunma.icept['lost'] == 1
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    assert bekle(lambda: (sess.savunma.taban > 0 and sess.savunma.t >= t_once) or None, 5), (sess.savunma.taban, sess.savunma.t, t_once)   # görev saati sürer
    assert ok(a.get(f'{S}/{sid}'))['defend']['state']['remaining'] == 1
    # sızma (8×): 2 tehdit istasyona ulaşır → görev biter (önleme yok → başarı yalnız sağlık > 0)
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        json.loads(ws.receive_text())
        m = ws_bekle(ws, lambda m: m['t'] == 'defend' and m['kind'] == 'leak', 40)   # çerçeve türü `t` korunur (kayıt zamanı `tt`)
        assert m and m['tt'] > 0 and m['health'] < 100 and m['state']['leaked'], m
        m = ws_bekle(ws, lambda m: m['t'] == 'defend' and m['kind'] == 'end', 40)
        assert m and m['result']['spawned'] == 2 and 'score' in m['result'] and m['tt'] > 0, m
    assert sess.savunma.bitti, sess.savunma.durum()
    sm = ok(a.get(f'{S}/{sid}/summary'))
    assert sm['defend']['spawned'] == 2 and len(sm['defend']['leaks']) == 2 and sm['defend']['ended'] and sm['site']['radar'] is True, sm.get('defend')
    ok(a.delete(f'{S}/{sid}'))
    it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT targets, world FROM drone_sim_runs WHERE id = ?', (it['id'],)))
    tj = json.loads(row['targets'])
    assert tj['config'] is None and tj['site']['radar_km'] == 12 and tj['defend']['config']['seed'] == 12345 and len(tj['defend']['result']['leaks']) == 2, tj
    with db.connect() as conn:
        lid = conn.execute('SELECT MAX(id) FROM flight_logs').fetchone()[0]
        conn.execute('UPDATE drone_sim_runs SET bin_log_id = ? WHERE id = ?', (lid, it['id']))
        conn.commit()
    try:
        rp = R.ReplaySession(1, {'id': lid, 'file_name': 'g.bin', 'vehicle': 'ArduPlane'}, {'runway_heading': 90}, {'id': 1, 'name': 'x'}, flightsim.MANAGER)
        rd = rp.to_dict()
        assert rd['site']['radar_km'] == 12 and rd['site']['layout']['tower'] == y0['tower'], rd['site']   # canlı oturumun pist yönü (0), kayıt dünyasının değil
        assert rd['defend']['plan'][0]['spawn_t'] == 15.0 and rd['defend']['replay'] and len(rd['defend']['state']['leaked']) == 2 and rd['defend']['result']['spawned'] == 2, rd['defend']['state']
    finally:
        with db.connect() as conn:
            conn.execute('UPDATE drone_sim_runs SET bin_log_id = NULL WHERE id = ?', (it['id'],))
            conn.commit()
    m = ok(a.get('/api/drone/sim/meta'))
    assert m['site']['radar_km'] == [1.0, 50.0] and m['site']['eo_km_default'] == 5.0 and m['site']['defend']['defaults']['interceptors'] == 10 and 'hard' in m['site']['defend']['difficulties']
    assert 'defend' in flightsim.KOMUTLAR
    print('  yer kontrol sahası + "Yer kontrolünü koru" (§26) testleri geçti')


def preset_testleri(a, c1, sitl, mon):
    """§27 Kayıtlı Simülasyonlar: pilot listesi, CRUD + doğrulama (başlatma gövdesiyle aynı), ad benzersizliği (Türkçe büyük/küçük harf, boşluk),
    yetki (başlat = atanan pilot / tasarlayan; düzenle-sil = tasarlayan / ADMIN; diğer pilot ve salt okuyan 403), atama bildirimi (push + zil),
    kayıtla başlat → oturum + kapanışta drone_sim_runs.preset_id, ?preset=free|<id> süzgeci, yumuşak silme; azami süre/menzil saf hesabı."""
    from app import db, flightsim_icept, flightsim_power, flightsim_presets, notifications, push
    P = '/api/drone/sim/presets'
    # --- saf hesap: azami uçuş süresi / menzil (JS flightBudget ile birebir: tests/test_flightsim_saved.mjs aynı sayılar) ---
    b = flightsim_power.menzil_sure({}, 'sabit_kanat')   # CAYMAZ 45 m/s, 5 L @ 25 km/L, 4S 10000 mAh 30 W
    assert b['speed'] == {'cruise_ms': 24.5, 'max_ms': 45.0, 'cruise_thr': 0.3}, b
    assert b['fuel'] == {'range_km': 192.7, 'time_min': 130.8, 'range_km_max': 125.0, 'time_min_max': 46.3}, b
    assert b['elec'] == {'wh': 148.0, 'time_min': 296.0, 'range_km': 435.9, 'time_min_max': 296.0, 'range_km_max': 799.2}, b
    assert b['limit'] == 'fuel' and b['time_min'] == 130.8 and b['range_km'] == 192.7 and b['time_min_max'] == 46.3 and b['range_km_max'] == 125.0, b
    k = flightsim_power.menzil_sure({'fuel_l': 2.0}, 'multirotor')   # kopter: 10 m/s seyir, askı gazı 0,5
    assert k['speed']['cruise_ms'] == 10.0 and k['fuel'] == {'range_km': 66.7, 'time_min': 111.1, 'range_km_max': 50.0, 'time_min_max': 66.7} and k['limit'] == 'fuel', k
    i = flightsim_power.menzil_sure({}, 'interceptor')
    assert i['fuel'] is None and i['limit'] == 'elec' and i['speed']['cruise_ms'] == 88.9 and i['elec']['time_min'] == 266.4, i
    # §31 kara aracı (JS flightBudget rover dalı ile birebir: tests/test_flightsim_rover.mjs aynı sayılar)
    rv = flightsim_power.menzil_sure({}, 'rover')
    assert rv['speed'] == {'cruise_ms': 5.0, 'max_ms': 20.0, 'cruise_thr': 0.3} and rv['fuel'] is None and rv['limit'] == 'elec', rv
    assert rv['elec'] == {'wh': 236.8, 'time_min': 236.8, 'range_km': 71.0, 'time_min_max': 236.8, 'range_km_max': 284.2}, rv
    rf = flightsim_power.menzil_sure({'fuel_l': 10}, 'rover')
    assert rf['fuel'] == {'range_km': 184.6, 'time_min': 615.4, 'range_km_max': 120.0, 'time_min_max': 100.0} and rf['limit'] == 'elec' and rf['time_min_max'] == 100.0, rf
    e = flightsim_power.menzil_sure({'fuel_l': 1, 'elec_w': 5}, 'sabit_kanat')
    assert e['limit'] == 'fuel' and e['time_min'] == 26.2 and e['elec']['time_min'] == 1776.0, e
    w = flightsim_power.menzil_sure({'fuel_l': 50, 'fuel_km_per_l': 100, 'elec_mah': 1000, 'elec_cells': 1}, 'sabit_kanat')
    assert w['limit'] == 'elec' and w['time_min'] == w['elec']['time_min'] == 7.4 and w['range_km'] == 10.9, w   # batarya sınırlar
    yok = flightsim_power.menzil_sure({'fuel_l': 0, 'elec_w': 0}, 'sabit_kanat')
    assert yok['fuel'] is None and yok['elec'] is None and yok['limit'] is None and yok['time_min'] is None, yok
    assert flightsim_power.ICEPT_SEYIR_ORAN == flightsim_icept.CRUISE_ORAN
    assert dict(flightsim_power.hiz_parametreleri(45.0))['AIRSPEED_CRUISE'] == b['speed']['cruise_ms']   # seyir oranı oturum parametreleriyle aynı
    assert flightsim_power.yuvarla(0.25, 1) == 0.3 and flightsim_power.yuvarla(2.675, 2) == 2.68   # yarım yukarı (JS Math.floor(x+0,5) ile aynı)

    # --- kullanıcılar: tasarlayan (Saha Sorumlusu), atanan pilot, diğer pilot ---
    ok(a.post('/api/users', json={'username': 'lead', 'full_name': 'Saha Lideri', 'roles': [auth.FIELD_LEAD], 'password': 'sifre-1234'}))
    ok(a.post('/api/users', json={'username': 'pilot2', 'full_name': 'İkinci Pilot', 'roles': [auth.PILOT], 'password': 'sifre-1234'}))
    lead, pil, pil2 = (TestClient(app, base_url='https://testserver') for _ in range(3))
    tok = {'lead': login(lead, 'lead', 'sifre-1234'), 'pilot': login(pil, 'pilot', 'sifre-1234'), 'pilot2': login(pil2, 'pilot2', 'sifre-1234'), 'admin': a.cookies.get(auth.COOKIE)}

    def kim(ad):   # oturum açan istekler `with` içindeki istemciden (a) gider: with'siz TestClient'ın olay döngüsü istek bitince kapanır, oturum görevi ölür
        a.cookies.clear()
        a.cookies.set(auth.COOKIE, tok[ad])
        return a
    me = {n: ok(c.get('/api/auth/me'))['id'] for n, c in (('lead', lead), ('pilot', pil), ('pilot2', pil2), ('admin', a))}
    pl = ok(lead.get(f'{P}/pilots'))
    ids = {x['id']: x for x in pl}
    assert {me['lead'], me['pilot'], me['pilot2'], me['admin']} <= set(ids), pl   # kendisi de seçilebilir
    assert ids[me['pilot']]['pilot'] is True and ids[me['lead']]['pilot'] is False and pl[0]['pilot'] is True, pl   # PILOT rolü önce
    assert not any(x['username'] == 'montaj' for x in pl) and not any(x['username'] == 'guv' for x in pl), pl   # salt okuyan / yetkisiz pilot olamaz
    mon_id = next(u['id'] for u in ok(a.get('/api/users')) if u['username'] == 'montaj')

    # --- doğrulama (başlatma gövdesiyle aynı doğrulayıcılar; oturum açılmaz) ---
    ayar = {'type': 'sabit_kanat', 'center_id': c1['id'], 'world': {'mode': 'procedural', 'seed': 42, 'size_m': 3000, 'launch': {'method': 'ramp', 'angle_deg': 18}},
            'model': {'id': 'builtin:caymaz'}, 'power': {'max_speed_ms': 40, 'fuel_l': 3, 'fuel_km_per_l': 20, 'elec_cells': 4, 'elec_mah': 8000, 'elec_w': 25},
            'layout': 'elevon', 'camera': 'thermal', 'rec': {'bin': False}, 'targets': None}
    govde = lambda **kw: {'name': 'Görev A', 'description': 'Rampadan kalkış, termal kamera', 'pilot_id': me['pilot'], 'settings': ayar, **kw}   # noqa: E731
    acik_once = len(flightsim.MANAGER.sessions)
    for bozuk, ipucu in ((dict(ayar, center_id=None), 'center'), (dict(ayar, center_id=99999), 'Merkez'), (dict(ayar, type='ucan_hali'), 'tip'),
                         (dict(ayar, power={'max_speed_ms': 500}), 'power'), (dict(ayar, world={'tree_density': 5}), None), (dict(ayar, camera='rontgen'), None),
                         (dict(ayar, layout='kanatsiz'), None), (dict(ayar, model={'id': 'builtin:yok'}), None), (dict(ayar, mode='replay'), 'SITL'),
                         (dict(ayar, drone_id=99999), 'Dron'), (dict(ayar, targets=[{'model': 'yok', 'alt_m': 100, 'diameter_m': 300}]), None)):
        r = lead.post(P, json=govde(settings=bozuk))
        assert r.status_code == 400 and (ipucu is None or ipucu.lower() in r.json()['detail'].lower()), (bozuk, r.status_code, r.text)
    assert len(flightsim.MANAGER.sessions) == acik_once   # doğrulama oturum açmaz
    assert lead.post(P, json=govde(name='   ')).status_code == 400
    assert lead.post(P, json=govde(name='x' * 81)).status_code == 400
    assert lead.post(P, json=govde(pilot_id=mon_id)).status_code == 400   # pilot yetkisi yok (salt okuyan)
    assert lead.post(P, json=govde(settings='metin')).status_code in (400, 422)
    assert mon.post(P, json=govde()).status_code == 403                   # salt okuyan: yazma izni yok

    # --- oluştur (+ atama bildirimi: push anında, zilde 'sim-assigned') ---
    gonderilen = []
    eski_send = push.send
    push.send = lambda ids_, payload, ttl=300: gonderilen.append((sorted(ids_), payload))
    try:
        p = ok(lead.post(P, json=govde()), 201)
        assert p['name'] == 'Görev A' and p['pilot_id'] == me['pilot'] and p['created_by'] == me['lead'] and p['pilot_name'] == 'Pilot' and p['created_by_name'] == 'Saha Lideri', p
        assert p['type'] == 'sabit_kanat' and p['center_id'] == c1['id'] and p['center_name'] == 'Test Merkezi' and p['run_count'] == 0 and p['deleted_at'] is None, p
        assert p['settings']['world']['launch'] == {'method': 'ramp', 'angle_deg': 18} and p['settings']['camera'] == 'thermal' and 'targets' not in p['settings'], p['settings']
        assert p['can_start'] is True and p['can_edit'] is True and p['budget'] == flightsim_power.menzil_sure(ayar['power'], 'sabit_kanat'), p
        assert gonderilen == [([me['pilot']], {'type': 'notif', 'title': 'Size bir simülasyon atandı', 'tag': f"notif-sim-assigned-{p['id']}",
                                               'body': 'Görev A · Saha Lideri', 'url': f"/app#/drone/sim?tab=saved&preset={p['id']}"})], gonderilen
        # kendine atama: bildirim yok
        p_kendi = ok(lead.post(P, json=govde(name='Kendi Uçuşum', pilot_id=me['lead'])), 201)
        p_pilotsuz = ok(lead.post(P, json=govde(name='Pilotsuz', pilot_id=None, description=None)), 201)
        assert len(gonderilen) == 1 and p_pilotsuz['pilot_id'] is None and p_pilotsuz['description'] is None
        # ad benzersizliği: baş/son/ardışık boşluk ve Türkçe büyük/küçük harf duyarsız → 409
        for ad in ('Görev A', '  görev   a ', 'GÖREV A', 'görev a'):
            r = lead.post(P, json=govde(name=ad))
            assert r.status_code == 409 and 'Görev A' in r.json()['detail'], (ad, r.status_code, r.text)
        assert flightsim_presets.ad_anahtari('IŞIK İz') == flightsim_presets.ad_anahtari('ışık iz')
        with db.connect() as conn:
            u_pil = db.row(conn.execute('SELECT id, prefs FROM users WHERE id = ?', (me['pilot'],)))
            u_pil.update(roles=[auth.PILOT], real_roles=[auth.PILOT], modules=['drone', 'drone.sim'])
            zil = notifications.sim_assigned(conn, u_pil)
            assert [r['id'] for r in zil['rows']] == [p['id']] and zil['href'] == f"#/drone/sim?tab=saved&preset={p['id']}" and zil['names'] == ['Görev A (Saha Lideri)'], zil
            assert any(n['key'] == 'sim-assigned' and n['push'] is False for n in notifications.NOTIFICATIONS)
            assert notifications.sim_assigned(conn, dict(u_pil, modules=['stock']))['rows'] == []   # modülsüz kullanıcıya düşmez

        # --- liste ve yetki: diğer pilot görür ama başlatamaz/düzenleyemez; ADMIN düzenler/siler ama başlatamaz (MASTER değil) ---
        l2 = {x['id']: x for x in ok(pil2.get(P))}
        assert p['id'] in l2 and l2[p['id']]['can_start'] is False and l2[p['id']]['can_edit'] is False and l2[p['id']]['mine'] is False
        assert ok(pil.get(P)) and next(x for x in ok(pil.get(P)) if x['id'] == p['id'])['can_start'] is True and next(x for x in ok(pil.get(P)) if x['id'] == p['id'])['can_edit'] is False
        la = next(x for x in ok(a.get(P)) if x['id'] == p['id'])
        assert la['can_edit'] is True and la['can_start'] is False, la
        assert ok(mon.get(P)) and ok(mon.get(f"{P}/{p['id']}"))['name'] == 'Görev A'   # salt okuyan görür
        assert pil2.post(f"{P}/{p['id']}/start").status_code == 403
        assert a.post(f"{P}/{p['id']}/start").status_code == 403
        assert pil2.put(f"{P}/{p['id']}", json=govde()).status_code == 403 and pil.put(f"{P}/{p['id']}", json=govde()).status_code == 403
        assert pil2.delete(f"{P}/{p['id']}").status_code == 403 and pil.delete(f"{P}/{p['id']}").status_code == 403
        assert lead.get(f'{P}/99999').status_code == 404 and lead.post(f'{P}/99999/start').status_code == 404

        # --- atanan pilot başlatır: kayıtlı gövdeyle oturum (sihirbaz yok) → kapanışta drone_sim_runs.preset_id ---
        s = ok(kim('pilot').post(f"{P}/{p['id']}/start"), 201)
        assert s['preset'] == {'id': p['id'], 'name': 'Görev A'} and s['type'] == 'sabit_kanat' and s['center']['id'] == c1['id'] and s['owner']['id'] == me['pilot'], s
        assert s['world']['seed'] == 42 and s['world']['launch']['method'] == 'ramp' and s['power']['max_speed_ms'] == 40 and s['camera'] == 'thermal' and s['layout'] == 'elevon', s
        assert bekle(lambda: ok(a.get(f"/api/drone/sim/sessions/{s['id']}"))['state'] == 'HAZIR')
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
        with db.connect() as conn:
            run = bekle(lambda: db.row(conn.execute('SELECT id, preset_id, owner_id FROM drone_sim_runs WHERE session_id = ? AND mode = ? ORDER BY id DESC LIMIT 1', (s['id'], 'sitl'))), 10)
        assert run and run['preset_id'] == p['id'] and run['owner_id'] == me['pilot'], run
        with db.connect() as conn:
            assert flightsim_presets.atanan_bekleyenler(conn, me['pilot']) == []   # ilk uçuşla zil düşer
        # tasarlayan da başlatabilir (pilot atanmış olsa bile)
        s2 = ok(kim('lead').post(f"{P}/{p_pilotsuz['id']}/start"), 201)
        assert s2['preset']['id'] == p_pilotsuz['id'] and s2['owner']['id'] == me['lead']
        ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
        with db.connect() as conn:
            assert bekle(lambda: db.row(conn.execute('SELECT preset_id FROM drone_sim_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1', (s2['id'],))), 10)['preset_id'] == p_pilotsuz['id']
        # serbest sihirbaz oturumu: preset_id NULL
        s3 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
        kim('admin')
        with db.connect() as conn:
            r3 = bekle(lambda: db.row(conn.execute('SELECT id, preset_id FROM drone_sim_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1', (s3['id'],))), 10)
        assert r3 and r3['preset_id'] is None, r3

        # --- uçuş kayıtları süzgeci: ?preset=<id> | free; preset_name; per_page ---
        R = '/api/drone/sim/runs'
        rp = ok(lead.get(R, params={'preset': p['id']}))
        assert [x['id'] for x in rp['items']] == [run['id']] and rp['items'][0]['preset_name'] == 'Görev A' and rp['items'][0]['preset_id'] == p['id'], rp
        rf = ok(lead.get(R, params={'preset': 'free', 'per_page': 100}))
        fids = {x['id'] for x in rf['items']}
        assert r3['id'] in fids and run['id'] not in fids and rf['per_page'] == 100 and all(x['preset_id'] is None for x in rf['items']), rf['per_page']
        assert lead.get(R, params={'preset': 'abc'}).status_code == 400
        assert ok(lead.get(R, params={'per_page': 500}))['per_page'] == 100
        assert next(x for x in ok(lead.get(P)) if x['id'] == p['id'])['run_count'] == 1

        # --- düzenle: tasarlayan; pilot değişince yeni pilota bildirim; ad çakışması; ADMIN de düzenler ---
        gonderilen.clear()
        ayar2 = dict(ayar, world=dict(ayar['world'], seed=43), camera='night')
        assert lead.put(f"{P}/{p['id']}", json=govde(name='Kendi Uçuşum', settings=ayar2)).status_code == 409   # başka kaydın adı
        u = ok(lead.put(f"{P}/{p['id']}", json=govde(name='Görev A (gece)', pilot_id=me['pilot2'], settings=ayar2)))
        assert u['name'] == 'Görev A (gece)' and u['pilot_id'] == me['pilot2'] and u['settings']['camera'] == 'night' and u['settings']['world']['seed'] == 43 and u['updated_at'] >= p['updated_at'], u
        assert [g[0] for g in gonderilen] == [[me['pilot2']]], gonderilen
        ok(lead.put(f"{P}/{p['id']}", json=govde(name='Görev A (gece)', pilot_id=me['pilot2'], settings=ayar2)))   # aynı ad (kendisi) + aynı pilot: bildirim yok
        assert len(gonderilen) == 1
        assert lead.put(f"{P}/{p['id']}", json=govde(name='Görev A (gece)', settings=dict(ayar2, center_id=99999))).status_code == 400
        assert ok(a.put(f"{P}/{p['id']}", json=govde(name='Görev A (gece)', pilot_id=me['pilot2'], settings=ayar2)))['name'] == 'Görev A (gece)'   # ADMIN
        l2 = {x['id']: x for x in ok(pil2.get(P))}
        assert l2[p['id']]['can_start'] is True and l2[p['id']]['mine'] is True   # yeni pilot artık başlatabilir
        assert pil.post(f"{P}/{p['id']}/start").status_code == 403                 # eski pilot artık başlatamaz
    finally:
        push.send = eski_send
        kim('admin')

    # --- sil (yumuşak): liste/başlat dışı, uçuşları Serbest Uçuş altında 'silinmiş' rozetiyle; ad yeniden kullanılabilir ---
    ok(lead.delete(f"{P}/{p['id']}"))
    assert p['id'] not in {x['id'] for x in ok(lead.get(P))} and lead.get(f"{P}/{p['id']}").status_code == 404
    assert pil2.post(f"{P}/{p['id']}/start").status_code == 404 and lead.delete(f"{P}/{p['id']}").status_code == 404
    rf = ok(lead.get(R, params={'preset': 'free', 'per_page': 100}))
    sil_run = next(x for x in rf['items'] if x['id'] == run['id'])
    assert sil_run['preset_id'] == p['id'] and sil_run['preset_name'] == 'Görev A (gece)' and sil_run['preset_deleted_at'], sil_run
    assert ok(lead.get(R, params={'preset': p['id']}))['total'] == 1   # kimlikle hâlâ erişilir
    ok(lead.post(P, json=govde(name='Görev A (gece)')), 201)                 # silinmiş kaydın adı serbest
    ok(a.delete(f"{P}/{p_kendi['id']}"))                                     # ADMIN siler
    assert pil.delete(f"{P}/{p_pilotsuz['id']}").status_code == 403
    for c in (lead, pil, pil2):
        c.close()
    print('  kayıtlı simülasyonlar (§27) testleri geçti')


def rover_testleri(a, c1):
    """§31 KARA ARACI: tip/ikili eşlemesi, sürüş biçimi doğrulaması (400), SITL modeli + rover.parm seti, kalkış/motor kesme 400, ArduRover kipleri,
    sahte kipte yerde sürüş (MANUAL RC1 direksiyon / RC3 gaz, servo çıkışı, HOLD), dahili modeller ve güç varsayılanları."""
    from app import drone_sitl, flightsim_models, flightsim_power, flightsim_targets
    S = '/api/drone/sim/sessions'
    assert drone_sitl.TIP_ESLEME['rover'] == ('ardurover', 'rover') and drone_sitl.SURUM['ardurover'] == ('Rover', 'stable-4.7.2')
    assert drone_sitl.model_tipi('Rover UGV-2') == 'rover' and drone_sitl.model_tipi('Caymaz') == 'multirotor'
    pm = drone_sitl.parm_metni(1, tip='rover', model='rover-skid')
    assert 'SERVO1_FUNCTION 73' in pm and 'SERVO3_FUNCTION 74' in pm and 'CRUISE_SPEED 3' in pm, pm
    pa = drone_sitl.parm_metni(1, tip='rover', model='rover')
    assert 'SERVO1_FUNCTION 26' in pa and 'SERVO3_FUNCTION 70' in pa and 'WP_SPEED 5' in pa and 'SERVO1_FUNCTION 73' not in pa, pa
    assert flightsim._varsayilan_vtype('rover') == flightsim.MAV_TYPE_GROUND_ROVER == 10
    kipler = set(flightsim._modlar(10))
    assert {'MANUAL', 'ACRO', 'STEERING', 'HOLD', 'LOITER', 'FOLLOW', 'SIMPLE', 'AUTO', 'RTL', 'SMART_RTL', 'GUIDED'} <= kipler, kipler
    # sürüş biçimi: modelden / açık / hatalı
    assert flightsim.drive_dogrula('rover', None, {'drive': 'skid'}) == 'skid' and flightsim.drive_dogrula('rover', '', None) == 'ackermann'
    assert flightsim.drive_dogrula('sabit_kanat', 'skid') is None
    assert a.post(S, json={'type': 'rover', 'center_id': c1['id'], 'drive': 'tank'}).status_code == 400
    # dahili modeller
    mods = ok(a.get('/api/drone/sim/models', params={'type': 'rover'}))
    ids = {m['id']: m for m in mods['models']}
    assert {'builtin:rover_4x4', 'builtin:rover_ugv', 'builtin:rover_bot'} <= set(ids), ids
    assert ids['builtin:rover_ugv']['drive'] == 'skid' and ids['builtin:rover_4x4']['drive'] == 'ackermann' and ids['builtin:rover_4x4']['has_prop'] is False
    assert flightsim_models.VARSAYILAN['rover'] == 'builtin:rover_4x4'
    assert all(not k.startswith('builtin:rover') for k in (t['key'] for t in flightsim_targets.katalog()))   # kara aracı hava hedefi değil
    # güç varsayılanları
    pw = flightsim_power.dogrula({'max_speed_ms': 30}, 'rover')
    assert pw['max_speed_ms'] is None and pw['fuel_l'] == 0.0 and pw['elec_mah'] == 16000.0, pw
    # oturum: UGV → skid (modelden), SITL modeli rover-skid
    s = ok(a.post(S, json={'type': 'rover', 'center_id': c1['id'], 'model': {'id': 'builtin:rover_ugv'}}), 201)
    sid = s['id']
    assert s['type'] == 'rover' and s['drive'] == 'skid' and s['ground'] is True and s['vertical'] is False and s['layout'] is None, s
    assert s['model']['id'] == 'builtin:rover_ugv' and s['launch']['method'] == 'wheels', s
    ss = flightsim.MANAGER.sessions[sid]
    assert ss._sitl_modeli() == 'rover-skid'
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    r = a.post(f'{S}/{sid}/cmd', json={'name': 'takeoff', 'params': {'alt': 10}})
    assert r.status_code == 400 and 'kalkış yok' in r.text, r.text
    assert a.post(f'{S}/{sid}/cmd', json={'name': 'motor_cut', 'params': {'on': True}}).status_code == 400
    assert a.post(f'{S}/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'FBWA'}}).status_code == 400   # uçak kipi kara aracında yok
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'MANUAL'}}))
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'arm'}))
    k = ss.sahte
    assert k.rover and k.drive == 'skid' and k.rc[2] == 1500   # gaz ortası = dur
    lat0, lon0 = k.lat, k.lon
    for _ in range(12):   # %60 ileri + hafif sağ
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'rc', 'params': {'ch': [1600, 0, 1800, 0, 0, 0, 0, 0]}}))
        time.sleep(0.1)
    assert bekle(lambda: k.hiz > 1.0, 3), k.hiz
    te = ss.tele
    assert te['alt_rel'] == 0.0 and te['groundspeed'] > 1.0 and te['armed'] is True, te
    assert te['servo'][0] > te['servo'][2] > 1500, te['servo']   # skid: sol palet (SERVO1) sağdan (SERVO3) hızlı → sağa dönüş
    assert (k.lat, k.lon) != (lat0, lon0)
    assert k.hiz <= flightsim.SahteKinematik.ROVER_VMAX['skid'] + 1e-6
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'mode', 'params': {'mode': 'HOLD'}}))
    assert bekle(lambda: abs(k.hiz) < 0.05, 3), k.hiz
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'rtl'}))
    assert bekle(lambda: k.mode == 'HOLD' and abs(k.hiz) < 0.5, 20), (k.mode, k.hiz)   # eve sürer, varınca HOLD
    ok(a.delete(f'{S}/{sid}'))
    # Ackermann: direksiyon SERVO1, gaz SERVO3; geri vites (RC3 < 1500)
    s = ok(a.post(S, json={'type': 'rover', 'center_id': c1['id']}), 201)
    sid = s['id']
    assert s['drive'] == 'ackermann' and s['model']['id'] == 'builtin:rover_4x4', s
    ss = flightsim.MANAGER.sessions[sid]
    assert ss._sitl_modeli() == 'rover'
    assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
    ok(a.post(f'{S}/{sid}/cmd', json={'name': 'arm'}))
    for _ in range(8):
        ok(a.post(f'{S}/{sid}/cmd', json={'name': 'rc', 'params': {'ch': [2000, 0, 1200, 0, 0, 0, 0, 0]}}))
        time.sleep(0.1)
    k = ss.sahte
    assert bekle(lambda: k.hiz < -0.5, 3), k.hiz   # geri
    sv = ss.tele['servo']
    assert sv[0] > 1900 and sv[2] < 1500, sv
    import asyncio   # panel 'land' kara aracında HOLD, 'takeoff' reddedilir
    res = asyncio.run_coroutine_threadsafe(ss.hub_komut('land', {}), ss.loop).result(5)
    assert res['ok'] and res['result']['mode'] == 'HOLD', res
    res = asyncio.run_coroutine_threadsafe(ss.hub_komut('takeoff', {'alt_rel_m': 10}), ss.loop).result(5)
    assert not res['ok'], res
    ok(a.delete(f'{S}/{sid}'))
    print('  kara aracı (§31) testleri geçti')


def runs_kapanis_testi():
    """Sunucu kapanışı (lifespan kapat_hepsi): kayıt tablosu kapanış sonrası okunabilir; son satırlar tutarlı."""
    from app import db
    with db.connect() as conn:
        rows = db.rows(conn.execute("SELECT mode, result, end_reason FROM drone_sim_runs ORDER BY id DESC LIMIT 3"))
    assert rows and all(r['mode'] in ('sitl', 'replay') for r in rows), rows
    print('  kapanış kaydı:', rows[0])


def main():
    terrain_birim_testleri()
    sitl = SahteSitl()
    flightsim.MANAGER.sahte_tcp_port = sitl.port
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Test Merkezi', 'lat': 39.925, 'lon': 32.837, 'alt': 900}))
        ok(a.post('/api/drone/centers', json={'name': 'Pasif Merkez', 'lat': 40.0, 'lon': 33.0, 'active': False}))
        c_altsiz = ok(a.post('/api/drone/centers', json={'name': 'İrtifasız Merkez', 'lat': 39.925, 'lon': 32.837}))
        # salt okuyan rol: Montaj Personeli'ne drone.sim yalnız aç + oku
        ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
        ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'},
                 json={'changes': [{'node': 'drone.sim', 'cap': 'open', 'value': True}, {'node': 'drone.sim', 'cap': 'read', 'value': True}]}))
        ok(a.post('/api/users', json={'username': 'pilot', 'full_name': 'Pilot', 'roles': [auth.PILOT], 'password': 'sifre-1234'}))

        # --- meta ---
        m = ok(a.get('/api/drone/sim/meta'))
        assert {t['key'] for t in m['types']} == {'multirotor', 'hexarotor', 'helikopter', 'sabit_kanat', 'vtol', 'interceptor', 'rover'} and all(t['binary'] for t in m['types']), m
        assert {c['id'] for c in m['centers']} == {c1['id'], c_altsiz['id']} and next(c for c in m['centers'] if c['id'] == c1['id'])['alt'] == 900, m   # pasif merkez listelenmez
        assert m['limits'] == {'max_sessions': 2, 'max_minutes': flightsim.MAX_MINUTES} and m['host'] == 'testserver' and m['can_command'] is True, m
        assert m['world_defaults']['seed'] == 12345 and m['world_defaults']['mode'] == 'procedural'
        assert m['google3d'] == {'enabled': bool(flightsim.GOOGLE_KEY)}   # Google 3B kipi: anahtar tanımlıysa açık (testte env yok → False)

        # --- oturum aç: doğrulama ---
        assert a.post('/api/drone/sim/sessions', json={'type': 'ucan_hali', 'center_id': c1['id']}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': 99999}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'tree_density': 5}}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': {'time': 'gece'}}).status_code == 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c1['id'], 'airframe': 'shuttle'}).status_code == 400
        # airframe (3B gövde): uçakta varsayılan caymaz, delta seçilebilir; kopterde yok sayılır
        assert flightsim.airframe_dogrula('sabit_kanat', None) == 'caymaz' and flightsim.airframe_dogrula('vtol', 'delta') == 'delta'
        assert flightsim.airframe_dogrula('multirotor', 'delta') is None
        world = {'seed': 7, 'size_m': 3000, 'tree_density': 0.5, 'wind_ms': 4, 'wind_dir': 90, 'time': 'dusk', 'runway': True}
        s = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id'], 'world': world}), 201)
        assert s['type'] == 'multirotor' and s['center']['id'] == c1['id'] and s['center']['lat'] == 39.925 and s['world']['seed'] == 7
        assert s['world']['mountain_height'] == 300 and s['world']['time'] == 'dusk', s   # eksikler varsayılanla dolar
        assert 24550 <= s['udp_port'] <= 24649 and s['host'] == 'testserver' and s['owner']['name'] == 'Sistem Yöneticisi' or s['owner']['id'], s
        assert s['state'] in ('BASLIYOR', 'HAZIR') and s['gcs'] == {'connected': False, 'addr': None, 'since': None}, s
        sid = s['id']
        g = bekle(lambda: (lambda r: r if r['state'] == 'HAZIR' else None)(ok(a.get(f'/api/drone/sim/sessions/{sid}'))))
        assert g and g['state'] == 'HAZIR' and g['sitl']['port'] == sitl.port, g
        # --- limit ---
        s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c1['id'], 'airframe': 'delta'}), 201)
        assert s2['udp_port'] != s['udp_port'] and s2['airframe'] == 'delta' and s['airframe'] is None
        r = a.post('/api/drone/sim/sessions', json={'type': 'vtol', 'center_id': c1['id']})
        assert r.status_code == 409, (r.status_code, r.text)
        assert [x['id'] for x in ok(a.get('/api/drone/sim/sessions'))] == [sid, s2['id']]
        ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
        assert a.get(f"/api/drone/sim/sessions/{s2['id']}").status_code == 404
        assert a.delete(f"/api/drone/sim/sessions/{s2['id']}").status_code == 404
        assert [x['id'] for x in ok(a.get('/api/drone/sim/sessions'))] == [sid]

        # --- komutlar (REST) ---
        cmd = lambda name, params=None: a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': name, 'params': params or {}})   # noqa: E731
        assert cmd('ucur').status_code == 400
        assert cmd('rc', {'ch': [1500, 1500, 1500]}).status_code == 400
        assert cmd('rc', {'ch': [1500, 1500, 2500, 1500, 1500, 1500, 1500, 1500]}).status_code == 400
        assert cmd('takeoff', {'alt': 'yüksek'}).status_code == 400
        assert cmd('mode', {'mode': 'UCUS'}).status_code == 400
        ok(cmd('takeoff'))   # varsayılan irtifa (kopter 10 m)
        ok(cmd('mode', {'mode': 'LOITER'}))
        ok(cmd('rc', {'ch': [1500, 1500, 1800, 1500, 1500, 1500, 1500, 1500]}))
        ok(cmd('set_home', {'lat': 39.93, 'lon': 32.84, 'alt': 905}))

        # --- salt okuyan rol: görür ama komut veremez / oturum açamaz ---
        if True:   # yardımcı istemciler with'siz: `with TestClient` çıkışı lifespan kapanışını (kapat_hepsi) tetikler
            mon = TestClient(app, base_url='https://testserver')
            mtoken = login(mon, 'montaj', 'sifre-1234')
            mm = ok(mon.get('/api/drone/sim/meta'))
            assert mm['can_command'] is False
            assert [x['id'] for x in ok(mon.get('/api/drone/sim/sessions'))] == [sid]
            assert mon.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'arm'}).status_code == 403
            assert mon.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c1['id']}).status_code == 403
            assert mon.delete(f'/api/drone/sim/sessions/{sid}').status_code == 403
            # --- gerçek topoğrafya vekili (ağsız) ---
            vekil_testleri(a, mon, c_altsiz)
            arazi_sunum_testleri(a, c_altsiz)   # §18 SITL arazi sunumu (TERRAIN_REQUEST → TERRAIN_DATA)
            # WS: izler, komut reddedilir
            with mon.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={mtoken}'}) as ws:
                h = json.loads(ws.receive_text())
                assert h['t'] == 'hello' and h['session']['id'] == sid and h['can_command'] is False, h
                ws.send_text(json.dumps({'t': 'cmd', 'name': 'arm', 'rid': 'r1'}))
                res = ws_bekle(ws, lambda m: m['t'] == 'res', 3)
                assert res and res['ok'] is False and res['rid'] == 'r1', res
            # --- görsel model kütüphanesi (§12) ---
            model_testleri(a, mon, c1)
        # drone paketine erişimi olmayan rol (Pilot var ama bu kullanıcı 'drone' modülünde değil?) → Pilot drone'a sahiptir; yetkisiz rol: Güvenlik
        ok(a.post('/api/users', json={'username': 'guv', 'full_name': 'Guv', 'roles': ['Güvenlik'], 'password': 'sifre-1234'}))
        if True:
            guv = TestClient(app, base_url='https://testserver')
            gtoken = login(guv, 'guv', 'sifre-1234')
            assert guv.get('/api/drone/sim/meta').status_code == 403
            assert guv.get('/api/drone/sim/terrain', params={'lat': 39.925, 'lon': 32.837}).status_code == 403
            assert guv.get('/api/drone/sim/tile/elev/13/4843/3103').status_code == 403 and guv.get('/api/drone/sim/osm', params={'lat': 39.925, 'lon': 32.837}).status_code == 403
            with guv.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={gtoken}'}) as ws:
                assert json.loads(ws.receive_text()) == {'t': 'error', 'error': 'auth'}
                assert close_code(ws) == 4403
        # çerezsiz → 4403; olmayan oturum → 4404
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': 'yok=1'}) as ws:
            assert json.loads(ws.receive_text())['error'] == 'auth' and close_code(ws) == 4403
        token = a.cookies.get(auth.COOKIE)
        with a.websocket_connect('/ws/drone/sim/99999', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            assert json.loads(ws.receive_text())['error'] == 'not_found' and close_code(ws) == 4404

        # --- WS: hello + telemetri (sahte kinematik komutlara tepki verir) ---
        with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
            h = json.loads(ws.receive_text())
            assert h['t'] == 'hello' and h['session']['state'] == 'HAZIR' and h['can_command'] is True, h
            teles = []
            bitis = time.time() + 3
            while time.time() < bitis and len(teles) < 5:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    teles.append(m)
            assert len(teles) >= 2, len(teles)
            t0 = teles[-1]
            assert TELE_ALANLARI <= set(t0), TELE_ALANLARI - set(t0)
            assert t0['armed'] is True and t0['mode'] == 'LOITER' and t0['alt_rel'] > 0 and len(t0['rc']) == 8 and t0['rc'][2] == 1800, t0
            assert t0['home'] == {'lat': 39.93, 'lon': 32.84, 'alt': 905.0} and t0['gcs_connected'] is False and t0['gcs_addr'] is None, t0
            assert abs(t0['lat'] - 39.925) < 0.01 and abs(t0['lon'] - 32.837) < 0.01 and t0['alt_msl'] > 900, t0
            assert {'rs', 'ps', 'ys', 'tbm', 'tbm_pos'} <= set(t0) and isinstance(t0['tbm'], int) and t0['tbm'] > 0 and t0['tbm_pos'] == t0['tbm'], t0   # açısal hızlar + SITL zaman damgaları (sahte: konum = yönelim)
            # --- 50 Hz sahte akış: 1 sn'de ≥ 40 tele, ardışık ts farkı ort. ≤ 25 ms, ts sunucu alım zamanı (Unix sn) ---
            ts_liste = []
            bitis = time.time() + 1.0
            while time.time() < bitis:
                m = json.loads(ws.receive_text())
                if m['t'] == 'tele':
                    ts_liste.append(m['ts'])
            farklar = [b - a for a, b in zip(ts_liste, ts_liste[1:])]
            assert len(ts_liste) >= 40, len(ts_liste)
            assert sum(farklar) / len(farklar) <= 0.025, sum(farklar) / len(farklar)
            assert abs(ts_liste[-1] - time.time()) < 2, (ts_liste[-1], time.time())
            ws.send_text(json.dumps({'t': 'ping'}))
            assert ws_bekle(ws, lambda x: x['t'] == 'pong', 2)
            # --- RC override: değer paketi hemen ardından serbest bırakma paketi (8×0) hız sınırına takılmaz, kanallar varsayılana döner ---
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1600, 1400, 1900, 1500, 2000, 1500, 1500, 1500]}))
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and x['rc'][2] == 1900 and x['rc'][4] == 2000, 3), 'rc override tele\'ye yansımadı'
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1650, 1500, 1950, 1500, 1500, 1500, 1500, 1500]}))   # < 25 ms: hız sınırı atar
            ws.send_text(json.dumps({'t': 'rc', 'ch': [0] * 8}))                                              # serbest: atılmaz
            assert ws_bekle(ws, lambda x: x['t'] == 'tele' and x['rc'] == list(flightsim.SahteKinematik.RC_VARSAYILAN), 3), 'rc serbest bırakma işlenmedi'
            # WS komutu: crash → disarm + olay; rc akışı
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'crash', 'rid': 'c1'}))
            gor = {'res': None, 'event': None, 'tele': None}
            bitis = time.time() + 3
            while time.time() < bitis and not all(gor.values()):
                m = json.loads(ws.receive_text())
                if m['t'] == 'res':
                    gor['res'] = m
                elif m['t'] == 'event' and 'ÇARPIŞMA' in m['text']:
                    gor['event'] = m
                elif m['t'] == 'tele' and m['armed'] is False:
                    gor['tele'] = m
            assert gor['res'] and gor['res']['ok'] is True and gor['res']['rid'] == 'c1', gor['res']
            assert gor['event'] and gor['event']['severity'] == 2 and gor['tele'] and gor['tele']['alt_rel'] == 0, gor
            ws.send_text(json.dumps({'t': 'rc', 'ch': [1500, 1500, 1200, 1500, 1500, 1500, 1500, 1500]}))
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 30}, 'rid': 'c2'}))
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['armed'], 3)
            assert m and m['mode'] == 'GUIDED', m
            # geçersiz WS komutu → res ok:false
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'mode', 'params': {'mode': 'UCUS'}, 'rid': 'c3'}))
            m = ws_bekle(ws, lambda x: x['t'] == 'res' and x.get('rid') == 'c3', 3)
            assert m and m['ok'] is False and 'mod' in m['error'].lower(), m
            # reset → state BASLIYOR/HAZIR, kinematik sıfır
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'reset', 'rid': 'c4'}))
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and not x['armed'] and x['alt_rel'] == 0, 3)
            assert m, 'reset sonrası sıfır telemetri gelmedi'

            # --- UDP köprüsü: GCS (UDP) ↔ sahte SITL (TCP) ham bayt; GCS kilidi ---
            udp_port = h['session']['udp_port']
            gcs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            gcs.bind(('127.0.0.1', 0))
            gcs.settimeout(3)
            gcs.sendto(b'\xfd\x09GCS-PAKET-1', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'GCS-PAKET-1'), 3), bytes(sitl.alinan)
            sitl.yaz(b'\xfd\x05SITL-TELE-1')
            data, hb = udp_al(gcs, b'\xfd\x05SITL-TELE-1', udp_port)
            assert data == b'\xfd\x05SITL-TELE-1', data
            # GCS bağlanınca sahte otopilot 1 Hz MAVLink HEARTBEAT da gönderir (Mission Planner 'bağlı' görsün)
            if not hb:
                d2, _ = gcs.recvfrom(4096)
                assert d2[:1] == b'\xfd' and len(d2) == 21 and d2[7:10] == b'\x00\x00\x00', d2
            # oturumda GCS görünür (REST + tele)
            g = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
            assert g['gcs']['connected'] is True and g['gcs']['addr'] == f'127.0.0.1:{gcs.getsockname()[1]}' and g['gcs']['since'], g
            m = ws_bekle(ws, lambda x: x['t'] == 'tele' and x['gcs_connected'], 3)
            assert m and m['gcs_addr'] == g['gcs']['addr'], m
            # ikinci adres: iletilmez (kilit); ilk GCS'nin paketi iletilir
            sahtekar = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sahtekar.bind(('127.0.0.1', 0))
            sahtekar.settimeout(0.5)
            once = len(sitl.alinan)
            sahtekar.sendto(b'SAHTEKAR', ('127.0.0.1', udp_port))
            time.sleep(0.5)
            assert len(sitl.alinan) == once and b'SAHTEKAR' not in bytes(sitl.alinan)
            gcs.sendto(b'GCS-PAKET-2', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'GCS-PAKET-2'), 3)
            sitl.yaz(b'SITL-TELE-2')
            assert udp_al(gcs, b'SITL-TELE-2', udp_port)[0] == b'SITL-TELE-2'
            try:
                sahtekar.recvfrom(4096)
                raise AssertionError('kilit dışı adres SITL verisi almamalı')
            except socket.timeout:
                pass
            ses = flightsim.MANAGER.get(sid)
            assert ses.gcs_rx == 2 and ses.gcs_atilan == 1 and ses.sitl_rx == len(b'\xfd\x05SITL-TELE-1') + len(b'SITL-TELE-2'), (ses.gcs_rx, ses.gcs_atilan, ses.sitl_rx)
            # SERVO_OUTPUT_RAW (araç sysid'den) → tele.servo 1…8 µs (3B kontrol yüzeyleri, §5); sahte kipte başlangıç None; GCS yankısı işlenmez
            assert ses.tele['servo'] is None
            d = flightsim._dialect()
            ayristir = d.MAVLink(None)   # başlık (sysid) ancak pack ile oluşur → bayt → mesaj
            arac = d.MAVLink(None, srcSystem=ses.sysid, srcComponent=1)
            for m_ in ayristir.parse_buffer(arac.servo_output_raw_encode(123456, 0, 1620, 1380, 1100, 1500, 1750, 1750, 1500, 0).pack(arac)) or []:
                ses._isle(m_)
            assert ses.tele['servo'] == [1620, 1380, 1100, 1500, 1750, 1750, 1500, 0], ses.tele['servo']
            gcs_mav = d.MAVLink(None, srcSystem=flightsim.GCS_SYSID, srcComponent=flightsim.GCS_COMP)
            for m_ in ayristir.parse_buffer(gcs_mav.servo_output_raw_encode(1, 0, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000).pack(gcs_mav)) or []:
                ses._isle(m_)   # GCS yankısı: işlenmez
            assert ses.tele['servo'][0] == 1620
            assert (36, 50000) in flightsim.MESAJ_ARALIKLARI   # SERVO_OUTPUT_RAW 20 Hz istenir
            # kilit sessizlikte kalkar (süreyi kısaltarak): yeni adres GCS olur
            ses.gcs_last -= flightsim.GCS_SESSIZLIK + 1
            sahtekar.sendto(b'YENI-GCS', ('127.0.0.1', udp_port))
            assert bekle(lambda: bytes(sitl.alinan).endswith(b'YENI-GCS'), 3)
            g = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
            assert g['gcs']['addr'] == f'127.0.0.1:{sahtekar.getsockname()[1]}', g
            gcs.close(); sahtekar.close()

            # --- kapat: WS 'end' alır, UDP portu boşalır, oturum listeden düşer ---
            ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
            m = ws_bekle(ws, lambda x: x['t'] == 'end', 3)
            assert m and m['reason'] == 'kapatildi', m
        assert ok(a.get('/api/drone/sim/sessions')) == []
        assert a.get(f'/api/drone/sim/sessions/{sid}').status_code == 404
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.bind(('0.0.0.0', udp_port)); sk.close()   # port serbest
        # yeniden açılabilir (limit sayacı düştü); lifespan kapanışı kalanı temizler
        s3 = ok(a.post('/api/drone/sim/sessions', json={'type': 'hexarotor', 'center_id': c1['id']}), 201)
        assert s3['id'] == sid + 14 and s3['udp_port'] == udp_port, (s3['id'], sid, s3['udp_port'], udp_port)   # kimlik sayacı (s2 + vekil testlerinin 5 oturumu + arazi sunumunun 2 oturumu + model testlerinin 5 oturumu) ilerler; ilk boş port yeniden verilir
        ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
        # --- ekran kaydı (§17) ---
        rec_testleri(a, c1)
        rec_sakla_testleri(a, c1)
        # --- .bin uçuş logu (§19) ---
        bin_testleri(a, c1)
        # --- sabit kanat kalkış yöntemi (§13) ---
        kalkis_testleri(a, c1)
        ruzgar_hava_testleri(a, c1)   # §31 hava durumu / rüzgâr / rampa yön-açı
        duzen_testleri(a, c1)   # §13.1 kontrol düzeni
        # --- harekât paneli köprüsü (§14) ---
        hub_testleri(a, c1)
        # --- görev çizimi / çarpışma / özet rapor (§18) ---
        gorev_rapor_testleri(a, c1)
        carpisma_siniflama_testleri(a, c1)
        # --- kalıcı parametreler (drone_sitl_params) ---
        param_testleri(a, c1, sitl, mon)
        # --- kayıttan oynatma (§8) ---
        replay_testleri(a, c1, None)
        # --- simülasyon kayıtları (§21) ---
        runs_testleri(a, c1, sitl, mon)
        # --- güç ve yakıt (§23) ---
        guc_testleri(a, c1, sitl, mon)
        # --- kamera türü (§22.3) ---
        kamera_testleri(a, c1, sitl)
        motor_cut_birim_testleri()          # motor kesme: sahte kinematik süzülme
        motor_cut_testleri(a, c1, sitl)     # motor kesme: komut sözleşmesi, tele/to_dict alanı, olaylar, sıfırlama
        sensor_param_testleri()             # Görev B: sensör kalibrasyonu SITL'de nötr ("Check mag field")
        hedef_icept_testleri(a, c1, sitl)   # §24 hedefler + §25 INTERCEPTOR
        gcs_testleri(a, c1, sitl)   # §26 yer kontrol sahası + görev
        firlatici_testleri(a, c1)   # §27 INTERCEPTOR fırlatıcıları
        preset_testleri(a, c1, sitl, mon)   # §27 kayıtlı simülasyonlar
        rover_testleri(a, c1)   # §31 kara aracı
        servo_tetik_birim_testleri()   # §34 servo tetik (saf mantık)
        servo_tetik_testleri(a, c1, sitl)   # §34 servo tetik uçtan uca
    assert flightsim.MANAGER.sessions == {}, flightsim.MANAGER.sessions   # lifespan: kapat_hepsi
    runs_kapanis_testi()
    sitl.kapat()
    print('Uçuş Simülatörü testleri geçti.')


if __name__ == '__main__':
    main()
