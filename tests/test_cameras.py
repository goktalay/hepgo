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

        # Son tanınan yüz (Eğitim başlığı avatarı): Ali'nin grubundaki EN SON görülme; Mehmet'in grubu silindi → yok
        lf = ok(g.get(f'/api/faces/last-face?keys=user:{ali},person:{mehmet},bozuk,user:x'))['faces']
        assert f'person:{mehmet}' not in lf and lf[f'user:{ali}']['crop'].startswith('camfaces/')
        with db.connect() as c:
            newest = c.execute('SELECT s.crop, s.at FROM face_sightings s JOIN face_groups g ON g.id = s.group_id WHERE g.user_id = ? '
                               'ORDER BY s.at DESC, s.id DESC LIMIT 1', (ali,)).fetchone()
        assert lf[f'user:{ali}']['crop'] == newest[0] and lf[f'user:{ali}']['at'] == newest[1] and lf[f'user:{ali}']['camera_name'] == 'Ana Giriş'
        assert ok(g.get('/api/faces/last-face'))['faces'] == {}
        ali_crop = lf[f'user:{ali}']['crop']

        # Düşük çözünürlüklü önizleme (32'li duvar): ?w=320 → küçültülmüş JPEG, ayrı ETag, 304 desteği
        from io import BytesIO
        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (1280, 720), (30, 90, 160)).save(buf, 'JPEG')
        (live / f'{cid}.jpg').write_bytes(buf.getvalue())
        full = g.get(f'/api/cameras/{cid}/frame')
        small = g.get(f'/api/cameras/{cid}/frame?w=320')
        assert small.status_code == 200 and small.headers['etag'] != full.headers['etag']
        assert Image.open(BytesIO(small.content)).width == 320 and len(small.content) < len(full.content)
        assert g.get(f'/api/cameras/{cid}/frame?w=320', headers={'If-None-Match': small.headers['etag']}).status_code == 304
        assert Image.open(BytesIO(g.get(f'/api/cameras/{cid}/frame?w=9999').content)).width == 640   # en büyük önizleme kademesi

        # Eğitim fotoğrafları toplu silme: DELETE /api/cameras/face/photos {ids}
        from app import faceenroll
        crop_bytes = buf.getvalue()
        before = len(ok(g.get(f'/api/faces/enroll?subject_type=user&user_id={ali}'))['faces'])   # atamayla otomatik eklenenler olabilir
        with db.connect() as c:
            e1 = faceenroll.enroll_precomputed(c, 'user', ali, None, None, crop_bytes, unit(11).tobytes(), 1, source='manual')
            e2 = faceenroll.enroll_precomputed(c, 'user', ali, None, None, crop_bytes, unit(12).tobytes(), 1, source='manual')
            e3 = faceenroll.enroll_precomputed(c, 'user', ali, None, None, crop_bytes, unit(13).tobytes(), 1, source='manual')
            c.commit()
        assert e1 and e2 and e3
        assert len(ok(g.get(f'/api/faces/enroll?subject_type=user&user_id={ali}'))['faces']) == before + 3
        assert g.request('DELETE', '/api/cameras/face/photos', json={'ids': []}).status_code == 400
        assert ok(g.request('DELETE', '/api/cameras/face/photos', json={'ids': [e1, e2, 999999, 'x']}))['deleted'] == 2
        left = {f['id'] for f in ok(g.get(f'/api/faces/enroll?subject_type=user&user_id={ali}'))['faces']}
        assert e3 in left and e1 not in left and e2 not in left and len(left) == before + 1

    # Kameralar modülü yalnızca sistem yöneticisine açık: Sekreter de Güvenlik kullanıcısı da göremez
    for uname in ('sek', 'guv'):
        with TestClient(app) as s:
            ok(s.post('/api/auth/login', json={'username': uname, 'password': 'sifre-1234'}))
            assert s.get('/api/cameras').status_code == 403 and s.get('/api/faces/groups').status_code == 403
            assert s.get(f'/api/files/{grp["items"][0]["crop"]}').status_code == 404
            assert s.get(f'/api/faces/last-face?keys=user:{ali}').status_code == 403
            assert s.request('DELETE', '/api/cameras/face/photos', json={'ids': [e3]}).status_code == 403

    # Rehber: fotoğrafı olmayan kişide yüz tanımanın EN SON tanıdığı yüz avatar olur (rehberi gören görür; kamera yetkisi gerekmez).
    # Eğitim fotoğrafı (face_enroll) olsa da son tanınan yüz önceliklidir; kamera medyasının geneli yine kapalı kalır.
    with TestClient(app) as s:
        ok(s.post('/api/auth/login', json={'username': 'sek', 'password': 'sifre-1234'}))
        ppl = {p['key']: p for p in ok(s.get('/api/directory?kind=user'))['people']}
        pa = ppl[f'user:{ali}']
        assert not pa.get('photo') and pa['face_avatar'].startswith(f'/api/directory/face-avatar/user/{ali}') and pa['face_camera'] == 'Ana Giriş'
        r = s.get(pa['face_avatar'])
        assert r.status_code == 200 and r.headers['content-type'] == 'image/jpeg' and r.content == (config.UPLOAD_DIR / ali_crop).read_bytes()
        assert s.get(f'/api/files/{ali_crop}').status_code == 404                       # kamera medyası genel olarak kapalı
        assert s.get(f'/api/directory/face-avatar/person/{mehmet}').status_code == 404  # tanınma yok
        assert s.get('/api/directory/face-avatar/bozuk/1').status_code == 404
        d = ok(s.get(f'/api/directory/user/{ali}'))
        assert d['face_avatar'].startswith('/api/directory/face-avatar/') and d['face_at']
        assert 'face' not in d['sections']   # kamera yetkisi olmayan görülme listesini görmez; yalnız avatar
    with TestClient(app) as s:   # Güvenlik rolü: Rehber yok → uç kapalı
        ok(s.post('/api/auth/login', json={'username': 'guv', 'password': 'sifre-1234'}))
        assert s.get(f'/api/directory/face-avatar/user/{ali}').status_code == 403
    print('Kamera ve yüz tanıma testleri geçti.')


if __name__ == '__main__':
    main()
