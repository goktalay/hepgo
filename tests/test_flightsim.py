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
    finally:
        sim_terrain.FETCH = sim_terrain._fetch
    print('  sim_terrain birim testleri geçti')


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
        assert s['center']['alt'] is None and s['world']['mode'] == 'procedural'   # prosedürel: dokunulmaz
        ok(a.delete(f"/api/drone/sim/sessions/{s['id']}"))
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
    # --- /logs: admin (tools) görür; analizi bitmemiş listelenmez; arama ---
    m = ok(a.get('/api/drone/sim/meta'))
    assert m['replay']['logs_allowed'] is True and m['replay']['hz'] == R.REPLAY_HZ and '.tlog' in m['replay']['formats'], m['replay']
    logs = ok(a.get('/api/drone/sim/logs'))
    assert [l['id'] for l in logs] == [lid] and logs[0]['ext'] == 'tlog' and logs[0]['type'] == 'multirotor' and logs[0]['cached'] is False and logs[0]['aircraft'] == 'CZ-TEST', logs
    assert ok(a.get('/api/drone/sim/logs?q=cz-test')) and ok(a.get('/api/drone/sim/logs?q=yokboyle')) == []
    # montaj: drone.sim var; Araçlar (tools) rolden kapatılır, Saha (field) zaten yok → log listesi boş, oturum açamaz (yazma yok → 403)
    ok(a.put('/api/roles/perms', params={'name': 'Montaj Personeli'}, json={'changes': [{'node': 'tools', 'cap': 'open', 'value': False}]}))
    mon = TestClient(app, base_url='https://testserver')
    login(mon, 'montaj', 'sifre-1234')
    assert not ({'tools', 'field'} & set(ok(mon.get('/api/auth/me'))['modules'])), ok(mon.get('/api/auth/me'))['modules']
    assert ok(mon.get('/api/drone/sim/meta'))['replay']['logs_allowed'] is False and ok(mon.get('/api/drone/sim/logs')) == []
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
    assert R.onbellek_yolu(lid).exists() and ok(a.get('/api/drone/sim/logs'))[0]['cached'] is True
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
    # log silinince önbellek de silinir
    ok(a.delete(f'/api/tools/flight-logs/{lid}'))
    assert not R.onbellek_yolu(lid).exists()
    print('Kayıttan oynatma testleri geçti.')


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
    assert [m['id'] for m in sk] == ['builtin:caymaz', 'builtin:delta'] and sk[0]['name'] == 'Caymaz V3' and sk[0]['glb_url'] == '/static/models/caymaz-sim.glb' and sk[0]['ready'] is True, sk
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
    assert s['params'] == {'tracked': True, 'loaded': 0, 'saved': 0}, s['params']
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
    # salt okuyan (drone.sim var, drone.drones yok) → 403
    assert mon.get(P).status_code == 403 and mon.delete(P).status_code == 403
    assert ok(a.delete(P)) == {'ok': True, 'deleted': 3} and ok(a.get(P))['count'] == 0
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action IN ('Sanal dron parametreleri içe aktardı', 'Sanal dron parametrelerini sıfırladı', 'Sanal dron parametresi sildi')").fetchone()[0] == 3
    gcs.close()
    ok(a.delete(f'{S}/{sid}'))
    # dron kaydı seçilmeyen oturumda izleme yok
    s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
    assert s2['params'] == {'tracked': False, 'loaded': 0, 'saved': 0}
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
    print('  simülasyon kayıtları (§21) testleri geçti')


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
        assert {t['key'] for t in m['types']} == {'multirotor', 'hexarotor', 'helikopter', 'sabit_kanat', 'vtol'} and all(t['binary'] for t in m['types']), m
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
        assert s3['id'] == sid + 10 and s3['udp_port'] == udp_port   # kimlik sayacı (s2 + vekil testlerinin 3 oturumu + model testlerinin 5 oturumu) ilerler; ilk boş port yeniden verilir
        ok(a.delete(f"/api/drone/sim/sessions/{s3['id']}"))
        # --- ekran kaydı (§17) ---
        rec_testleri(a, c1)
        rec_sakla_testleri(a, c1)
        # --- .bin uçuş logu (§19) ---
        bin_testleri(a, c1)
        # --- sabit kanat kalkış yöntemi (§13) ---
        kalkis_testleri(a, c1)
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
    assert flightsim.MANAGER.sessions == {}, flightsim.MANAGER.sessions   # lifespan: kapat_hepsi
    runs_kapanis_testi()
    sitl.kapat()
    print('Uçuş Simülatörü testleri geçti.')


if __name__ == '__main__':
    main()
