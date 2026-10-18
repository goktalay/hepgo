"""Endüstriyel Tasarım — STEP sürümü 3B önizlemesi (STL / GLB / PNG; tarayıcıda üretilir, sunucuya PUT edilir).
PUT /api/design/versions/{id}/preview?kind=stl|glb|thumb: biçim denetimi (400), boyut sınırı (413), yetki (salt okuyan 403, modülsüz 403),
dosya yolları (UPLOAD_DIR/design/preview/<id>.*), sürüm/çizim/proje API'lerinde önizleme alanları, GET /api/design/file?s=|g=|t= (başlık, indirme adı, Master kuralı).

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_design_preview
"""
import io
import json
import os
import struct
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_MASTER_USERNAME='admin@test')

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402

STEP_METIN = b'ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((\'test\'),\'2;1\');\nENDSEC;\nDATA;\n#1=CARTESIAN_POINT(\'\',(0.,0.,0.));\nENDSEC;\nEND-ISO-10303-21;\n'


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def ikili_stl(n=2):
    """80 bayt başlık + üçgen sayısı + n × (normal, 3 köşe, 2 bayt öznitelik)."""
    body = b''.join(struct.pack('<12fH', 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0) for _ in range(n))
    return b'HEPGO test STL'.ljust(80, b'\0') + struct.pack('<I', n) + body


def kucuk_glb():
    js = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0}).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    return struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js)) + struct.pack('<II', len(js), 0x4E4F534A) + js


def kucuk_png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGBA', (480, 360), (40, 60, 90, 0)).save(buf, 'PNG')
    return buf.getvalue()


def main():
    with TestClient(app, base_url='https://testserver') as a:
        login(a, 'admin@test', 'admin-sifre-1')
        me = ok(a.get('/api/auth/me'))
        assert me['master'] is True and 'design' in me['modules'], me
        # --- proje, çizim, STEP sürümü
        pid = ok(a.post('/api/design/projects', json={'name': 'Caymaz', 'description': 'test'}))['id']
        did = ok(a.post(f'/api/design/projects/{pid}/drawings', json={'name': 'Gövde', 'kind': 'assembly'}))['id']
        v1 = ok(a.post(f'/api/design/drawings/{did}/version', files={'file': ('CAYMAZ V3.step', STEP_METIN, 'application/octet-stream')}, data={'note': 'ilk'}))
        vid = v1['id']
        # önizleme yok: alanlar boş, dosya uçları 404
        pr = ok(a.get('/api/design/projects'))
        p0 = next(p for p in pr if p['id'] == pid)
        assert p0['step'] and p0['step']['id'] == vid and p0['step']['preview_thumb'] is False and p0['step']['preview_glb'] is False and p0['step']['preview_stl'] is False, p0['step']
        cur = ok(a.get(f'/api/design/drawings/{did}'))['current']
        assert cur['preview'] == {'stl': None, 'glb': None, 'thumb': None, 'at': None}, cur['preview']
        for q in ('s', 'g', 't'):
            assert a.get(f'/api/design/file?{q}={vid}').status_code == 404
        U = f'/api/design/versions/{vid}/preview'
        # --- doğrulama: kind, biçim, boyut
        assert a.put(f'{U}?kind=obj', content=b'x').status_code == 400
        assert a.put(f'{U}?kind=stl', content=b'solid ascii\nendsolid\n' + b'\0' * 200).status_code == 400          # ascii / uyumsuz uzunluk
        assert a.put(f'{U}?kind=stl', content=ikili_stl(2)[:-1]).status_code == 400                                   # uzunluk n·50 ile uyuşmuyor
        assert a.put(f'{U}?kind=glb', content=b'NOT-GLB-AT-ALL-REALLY-NOT-GLB').status_code == 400
        assert a.put(f'{U}?kind=thumb', content=b'GIF89a' + b'\0' * 40).status_code == 400
        assert a.put(f'{U}?kind=stl', content=b'x', headers={'content-length': str(60 * 1024 * 1024)}).status_code == 413
        assert a.put(f'{U}?kind=thumb', content=b'x', headers={'content-length': str(3 * 1024 * 1024)}).status_code == 413
        assert a.put('/api/design/versions/999999/preview?kind=stl', content=ikili_stl()).status_code == 404
        # --- yükleme: stl, glb, thumb
        stl = ikili_stl(3)
        r = ok(a.put(f'{U}?kind=stl', content=stl, headers={'content-type': 'application/octet-stream'}))
        assert r['kind'] == 'stl' and r['size'] == len(stl) and r['preview']['stl'] == f'/api/design/file?s={vid}' and r['preview']['glb'] is None and r['preview']['at'], r
        glb = kucuk_glb()
        r = ok(a.put(f'{U}?kind=glb', content=glb, headers={'content-type': 'application/octet-stream'}))
        assert r['preview']['glb'] == f'/api/design/file?g={vid}' and r['preview']['stl']
        png = kucuk_png()
        r = ok(a.put(f'{U}?kind=thumb', content=png, headers={'content-type': 'image/png'}))
        assert r['preview']['thumb'] == f'/api/design/file?t={vid}'
        pdir = config.UPLOAD_DIR / 'design' / 'preview'
        assert (pdir / f'{vid}.stl').read_bytes() == stl and (pdir / f'{vid}.glb').read_bytes() == glb and (pdir / f'{vid}.png').read_bytes() == png
        # --- okuma: başlıklar, indirme adı (çizim dosya adının kökü + .stl), Master kuralı
        g = a.get(f'/api/design/file?s={vid}')
        assert g.status_code == 200 and g.content == stl and g.headers['content-type'].startswith('model/stl') and 'inline' in g.headers['content-disposition'], g.headers
        g = a.get(f'/api/design/file?s={vid}&dl=1')
        assert g.status_code == 200 and 'attachment' in g.headers['content-disposition'] and 'CAYMAZ%20V3.stl' in g.headers['content-disposition'].replace('"', ''), g.headers['content-disposition']
        g = a.get(f'/api/design/file?g={vid}')
        assert g.status_code == 200 and g.content == glb and g.headers['content-type'].startswith('model/gltf-binary')
        g = a.get(f'/api/design/file?t={vid}')
        assert g.status_code == 200 and g.content == png and g.headers['content-type'].startswith('image/png')
        # --- API'lerde önizleme alanları
        p1 = next(p for p in ok(a.get('/api/design/projects')) if p['id'] == pid)
        assert p1['step']['preview_thumb'] is True and p1['step']['preview_glb'] is True and p1['step']['preview_stl'] is True and p1['step']['name'] == 'Gövde', p1['step']
        cur = ok(a.get(f'/api/design/drawings/{did}'))['current']
        assert cur['preview']['stl'] == f'/api/design/file?s={vid}' and cur['preview']['thumb'] and cur['preview']['at']
        tree = ok(a.get(f'/api/design/projects/{pid}'))['tree']
        assert tree[0]['current']['preview']['glb'] == f'/api/design/file?g={vid}' and tree[0]['current']['preview_stl'] == f'design/preview/{vid}.stl'
        vs = ok(a.get(f'/api/design/drawings/{did}/versions'))
        assert vs[0]['preview_stl'] == f'design/preview/{vid}.stl' and vs[0]['preview_glb'] and vs[0]['preview_thumb'] and vs[0]['preview_at']
        # yeni sürüm → proje kartı yeni sürümü gösterir, onun önizlemesi yok
        v2 = ok(a.post(f'/api/design/drawings/{did}/version', files={'file': ('CAYMAZ V4.stp', STEP_METIN, 'application/octet-stream')}, data={'note': 'ikinci'}))
        p2 = next(p for p in ok(a.get('/api/design/projects')) if p['id'] == pid)
        assert p2['step']['id'] == v2['id'] and p2['step']['preview_stl'] is False, p2['step']
        # yeniden üretim üzerine yazar
        stl2 = ikili_stl(5)
        ok(a.put(f'{U}?kind=stl', content=stl2))
        assert a.get(f'/api/design/file?s={vid}').content == stl2
        # --- yetki: salt okuyan tasarımcı önizleme yükleyemez (403), okur; indirme (dl=1) yalnız Master
        ok(a.post('/api/users', json={'username': 'tasarimci', 'full_name': 'Tasarımcı', 'roles': ['Endüstriyel Tasarımcı'], 'password': 'sifre-1234'}))
        ok(a.put('/api/roles/perms', params={'name': 'Endüstriyel Tasarımcı'}, json={'changes': [{'node': 'design', 'cap': 'write', 'value': False}]}))
        t = TestClient(app, base_url='https://testserver')
        login(t, 'tasarimci', 'sifre-1234')
        tm = ok(t.get('/api/auth/me'))
        assert 'design' in tm['modules'] and 'design' not in tm.get('write_modules', []), tm
        assert t.put(f'{U}?kind=stl', content=ikili_stl()).status_code == 403
        assert t.get(f'/api/design/file?s={vid}').status_code == 200 and t.get(f'/api/design/file?g={vid}').status_code == 200
        assert t.get(f'/api/design/file?s={vid}&dl=1').status_code == 403
        # modülü olmayan kullanıcı
        ok(a.post('/api/users', json={'username': 'montaj', 'full_name': 'Montaj', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
        m = TestClient(app, base_url='https://testserver')
        login(m, 'montaj', 'sifre-1234')
        assert m.put(f'{U}?kind=stl', content=ikili_stl()).status_code == 403 and m.get(f'/api/design/file?s={vid}').status_code == 403
    print('Endüstriyel Tasarım önizleme (STL/GLB/PNG) testleri geçti.')


if __name__ == '__main__':
    main()
