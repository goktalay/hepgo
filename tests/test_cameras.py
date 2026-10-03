"""Güvenlik → Kameralar ve Tanımlanamayan Kişiler: kamera ekleme (şifre saklanır, dönmez; dosya yolu kabul edilmez),
izleme karesi (ETag / 304), kamera servisinin yüz gruplaması (yapay yüz izleriyle), gruba kişi atama, birleştirme, silme,
kullanıcı tercihi (izleme düzeni) ve yetkiler.

Çalıştırma: .venv/bin/python -m tests.test_cameras
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import camera_service, cameras as camlib, config, db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def unit(seed, noise=0.0, base=None):
    rng = np.random.default_rng(seed)
    v = (base if base is not None else rng.normal(size=128)) + rng.normal(size=128) * noise
    return (v / np.linalg.norm(v)).astype(np.float32)


def main():
    # Şifre saklama: geri çözülür, bozulursa boş döner
    enc = camlib.encrypt('gizli-şifre')
    assert enc and 'gizli' not in enc and camlib.decrypt(enc) == 'gizli-şifre'
    assert camlib.decrypt(enc[:-4] + 'AAAA') == ''
    assert camlib.with_credentials('rtsp://10.0.0.5:554/s1', 'ad min', 'p@ss') == 'rtsp://ad%20min:p%40ss@10.0.0.5:554/s1'
    assert camlib.mask('rtsp://admin:xyz@10.0.0.5/s1') == 'rtsp://admin:***@10.0.0.5/s1'

    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'guv', 'full_name': 'Güv', 'roles': ['Güvenlik'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'sek', 'full_name': 'Sek', 'roles': ['Sekreter'], 'password': 'sifre-1234'}))
        ali = ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali Veli', 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
        rok = ok(a.post('/api/companies', json={'name': 'Roketsan'}))['id']
        mehmet = ok(a.post(f'/api/companies/{rok}/people', json={'full_name': 'Mehmet Kaya'}))['id']

    with TestClient(app) as g:   # Kameralar yalnızca sistem yöneticisine açık (Sistem Yönetimi)
        ok(g.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert g.post('/api/cameras', json={'name': 'X', 'stream_url': '/etc/passwd'}).status_code == 400   # dosya yolu yok
        assert g.post('/api/cameras', json={'name': 'X'}).status_code == 400
        cid = ok(g.post('/api/cameras', json={'name': 'Giriş', 'stream_url': 'rtsp://10.0.0.5/s1', 'username': 'admin',
                                              'password': 'kamera-sifre', 'location': 'Kapı'}))['id']
        cam = ok(g.get('/api/cameras'))[0]
        assert 'password_enc' not in cam and 'kamera-sifre' not in str(cam) and cam['has_password']
        with db.connect() as c:
            enc = c.execute('SELECT password_enc FROM cameras WHERE id = ?', (cid,)).fetchone()[0]
        assert camlib.decrypt(enc) == 'kamera-sifre'
        ok(g.put(f'/api/cameras/{cid}', json={'name': 'Ana Giriş', 'stream_url': cam['stream_url'], 'username': 'admin', 'faces': False}))
        with db.connect() as c:   # şifre boş gönderildi: değişmedi
            row = c.execute('SELECT name, password_enc, faces FROM cameras WHERE id = ?', (cid,)).fetchone()
        assert row[0] == 'Ana Giriş' and camlib.decrypt(row[1]) == 'kamera-sifre' and row[2] == 0
        # İzleme karesi: servis yazar; yoksa 404, değişmediyse 304
        assert g.get(f'/api/cameras/{cid}/frame').status_code == 404
        live = config.DATA_DIR / 'cameras' / 'live'
        live.mkdir(parents=True, exist_ok=True)
        (live / f'{cid}.jpg').write_bytes(b'\xff\xd8\xff jpeg')
        r = g.get(f'/api/cameras/{cid}/frame')
        assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg'
        assert g.get(f'/api/cameras/{cid}/frame', headers={'If-None-Match': r.headers['etag']}).status_code == 304
        # Tercih: izleme düzeni sunucuda
        ok(g.put('/api/me/prefs/camera.wall', json={'value': '{"layout": 6, "slots": [1]}'}))
        assert ok(g.get('/api/me/prefs/camera.wall'))['value'] == '{"layout": 6, "slots": [1]}'

        # Kamera servisi gruplaması (yapay yüz izleri): aynı kişi aynı grupta; 20 sn kuralı; yeni kişi yeni grup
        ident = camera_service.Identities()
        ident.reload()
        crop = np.zeros((256, 256, 3), np.uint8)
        frame = np.zeros((720, 1280, 3), np.uint8)
        a1 = unit(1)
        camera_service._store_sighting(ident, cid, a1, crop, frame, 900.0, db.now())
        camera_service._store_sighting(ident, cid, unit(2, 0.15, a1), crop, frame, 1200.0, db.now())   # aynı kişi, 20 sn içinde
        b1 = unit(3)
        camera_service._store_sighting(ident, cid, b1, crop, frame, 500.0, db.now())
        with db.connect() as c:
            groups = c.execute('SELECT id, samples FROM face_groups ORDER BY id').fetchall()
            sightings = c.execute('SELECT group_id, crop, frame FROM face_sightings ORDER BY id').fetchall()
        assert [s for _, s in groups] == [2, 1] and len(sightings) == 2   # ikinci görülme 20 sn içinde: saklanmadı
        ga, gb = groups[0][0], groups[1][0]
        assert all((config.UPLOAD_DIR / p).exists() for s in sightings for p in s[1:])
        ident.last_store.clear()
        camera_service._store_sighting(ident, cid, unit(4, 0.15, a1), crop, frame, 1500.0, db.now())
        lst = ok(g.get('/api/faces/groups'))
        assert {x['id']: x['sightings'] for x in lst} == {ga: 2, gb: 1}
        grp = ok(g.get(f'/api/faces/groups/{ga}'))
        assert len(grp['items']) == 2 and g.get(f'/api/files/{grp["items"][0]["frame"]}').status_code == 200

        # Kişiye atama: gruptaki tüm yüzler; Tanınan Kişiler'e geçer
        people = ok(g.get('/api/faces/people'))
        assert any(u['id'] == ali for u in people['users']) and any(p['id'] == mehmet for p in people['people'])
        assert g.post(f'/api/faces/groups/{ga}/assign', json={}).status_code == 400
        ok(g.post(f'/api/faces/groups/{ga}/assign', json={'user_id': ali}))
        assert [x['id'] for x in ok(g.get('/api/faces/groups'))] == [gb]
        known = ok(g.get('/api/faces/groups?state=known'))
        assert known[0]['user_name'] == 'Ali Veli' and known[0]['sightings'] == 2
        assert ok(g.get('/api/faces/recent'))[0]['user_name'] == 'Ali Veli'
        # Servis atamayı okur: aynı kişinin yeni yüzü atanmış gruba gider
        ident.reload()
        ident.last_store.clear()
        camera_service._store_sighting(ident, cid, unit(5, 0.15, a1), crop, frame, 800.0, db.now())
        assert ok(g.get('/api/faces/groups?state=known'))[0]['sightings'] == 3
        # Birleştirme ve aynı kişiye ikinci atama (gruplar birleşir)
        camera_service._store_sighting(ident, cid, unit(6), crop, frame, 700.0, db.now())
        unknown = [x['id'] for x in ok(g.get('/api/faces/groups'))]
        assert len(unknown) == 2
        ok(g.post('/api/faces/merge', json={'ids': unknown}))
        merged = ok(g.get('/api/faces/groups'))
        assert len(merged) == 1 and merged[0]['sightings'] == 2
        r = ok(g.post(f'/api/faces/groups/{merged[0]["id"]}/assign', json={'person_id': mehmet}))
        assert ok(g.get('/api/faces/groups?state=known'))[0]['person_name'] in ('Mehmet Kaya', 'Ali Veli')
        # Silme: yanlış tespit; resimler de silinir
        files = ok(g.get(f'/api/faces/groups/{r["id"]}'))['items']
        ok(g.delete(f'/api/faces/groups/{r["id"]}'))
        assert all(not (config.UPLOAD_DIR / s['crop']).exists() for s in files)
        assert g.get(f'/api/faces/groups/{r["id"]}').status_code == 404

    # Kameralar modülü yalnızca sistem yöneticisine açık: Sekreter de Güvenlik kullanıcısı da göremez
    for uname in ('sek', 'guv'):
        with TestClient(app) as s:
            ok(s.post('/api/auth/login', json={'username': uname, 'password': 'sifre-1234'}))
            assert s.get('/api/cameras').status_code == 403 and s.get('/api/faces/groups').status_code == 403
            assert s.get(f'/api/files/{grp["items"][0]["crop"]}').status_code == 404
    print('Kamera ve yüz tanıma testleri geçti.')


if __name__ == '__main__':
    main()
