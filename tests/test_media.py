"""Ses ve video evrakı testi: ses kaydının metne çevrilmesi (Whisper, gerçek örnek kayıt), video yüzlerinin kaydı,
kişiye bağlama (firma kişisi / personel), bilinen yüzün sonraki videoda otomatik önerilmesi, kaldırma ve erişim.

Yüz bulma (OpenCV) gerçek bir kişinin görüntüsünü gerektirdiği için burada yapay yüz izleriyle sınanır; bulma adımı
elle doğrulanmıştır (README). Çalıştırma: .venv/bin/python -m tests.test_media
"""
import os
import tempfile
import time
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_SPEECH='1',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, document_media  # noqa: E402
from app.main import app  # noqa: E402

FIXTURES = Path(__file__).parent / 'fixtures'


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def upload(c, name, data):
    up = ok(c.post('/api/uploads', json={'kind': 'documents', 'file_name': name, 'size': len(data)}))['upload_id']
    ok(c.put(f'/api/uploads/{up}?offset=0', content=data))
    return up


def wait(c, doc_id, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        d = ok(c.get(f'/api/documents/{doc_id}'))
        if d['ocr_status'] not in ('BEKLIYOR', 'ISLENIYOR'):
            return d
        time.sleep(0.3)
    raise AssertionError('işleme zaman aşımı')


def unit(seed, base=None, noise=0.0):
    rng = np.random.default_rng(seed)
    v = (base if base is not None else rng.standard_normal(128)) + noise * rng.standard_normal(128)
    return (v / np.linalg.norm(v)).astype(np.float32)


def main():
    person_a, person_b = unit(1), unit(2)
    crop = np.full((256, 256, 3), 128, np.uint8)
    fake = {'faces': [], 'image': []}
    document_media.detect_faces = lambda path, duration: fake['faces']   # yapay yüzler (bulma adımı elle doğrulandı)
    document_media.video_duration = lambda path: 12.0
    document_media.video_thumb = lambda path, thumb: False
    document_media.detect_faces_image = lambda path: fake['image']
    document_media.transcribe = (lambda real: (lambda path, **kw: ('', 12.0) if path.suffix == '.mp4' else real(path, **kw)))(
        document_media.transcribe)

    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        cid = ok(a.post('/api/companies', json={'name': 'MKE A.Ş.'}))['id']
        pid = ok(a.post(f'/api/companies/{cid}/people', json={'full_name': 'Ahmet Yılmaz'}))['id']
        uid = ok(a.post('/api/users', json={'username': 'personel@test', 'full_name': 'Personel Bir', 'roles': ['Pilot'],
                                            'password': 'sifre-1234'}))['id']

        # ---- Ses: yüklenir, metne çevrilir, aranır
        if document_media.whisper_available():
            sid = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'konusma.mp3', (FIXTURES / 'speech-en.mp3').read_bytes())],
                                                    'title': 'Görüşme kaydı'}))['ids'][0]
            d = wait(a, sid)
            assert d['kind'] == 'SES' and d['ocr_status'] == 'TAMAM', d
            assert 'ask not what your country can do for you' in d['ocr_text'] and d['ocr_text'].count('[00:') >= 1, d['ocr_text']
            assert round(d['duration']) == 11
            found = ok(a.get('/api/documents', params={'q': 'country'}))['documents']
            assert [x['id'] for x in found] == [sid]
        else:
            print('UYARI: Whisper kurulu değil, ses testi atlandı')
        assert a.post('/api/uploads', json={'kind': 'documents', 'file_name': 'x.exe', 'size': 10}).status_code == 400

        # ---- Sesle yazdırma (metin kutusundaki mikrofon): kısa kayıt → düz metin (zaman damgasız)
        if document_media.whisper_available():
            audio = (FIXTURES / 'speech-en.mp3').read_bytes()
            r = ok(a.post('/api/system/dictate?lang=en', files={'file': ('dikte.mp3', audio, 'audio/mpeg')}))
            assert 'ask not what your country can do for you' in r['text'] and '[' not in r['text'] and r['seconds'] == 11.0
        assert a.post('/api/system/dictate', files={'file': ('x.exe', b'abc', 'application/octet-stream')}).status_code == 400
        assert a.post('/api/system/dictate', files={'file': ('bos.webm', b'', 'audio/webm')}).status_code == 400
        assert a.post('/api/system/dictate?lang=xx', files={'file': ('a.webm', b'abc', 'audio/webm')}).status_code == 400

        # ---- Video 1: iki kişi bulunur, ikisi de tanımsız
        fake['faces'] = [{'embedding': unit(0, person_a, 0.2), 'samples': 9, 'first_at': 1.0, 'crop': crop},
                         {'embedding': unit(0, person_b, 0.2), 'samples': 3, 'first_at': 4.0, 'crop': crop}]
        v1 = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'toplanti.mp4', b'\0' * 64)], 'title': 'Toplantı videosu'}))['ids'][0]
        d = wait(a, v1)
        assert d['kind'] == 'VIDEO' and d['ocr_status'] == 'YOK'   # konuşma yok
        faces = d['faces']
        assert [(f['samples'], f['person_id'], f['user_id'], f['auto']) for f in faces] == [(9, None, None, 0), (3, None, None, 0)]
        assert a.get(f'/api/files/{faces[0]["crop"]}').status_code == 200   # yüz görüntüsü evrak görünürlüğüyle korunur
        # Birinci kişi firma kişisine, ikinci kişi personele bağlanır
        assert a.put(f'/api/documents/{v1}/faces/{faces[0]["id"]}', json={'person_id': pid, 'user_id': uid}).status_code == 400
        r = ok(a.put(f'/api/documents/{v1}/faces/{faces[0]["id"]}', json={'person_id': pid}))
        assert r['faces'][0]['person_name'] == 'Ahmet Yılmaz' and r['faces'][0]['company_name'] == 'MKE A.Ş.'
        ok(a.put(f'/api/documents/{v1}/faces/{faces[1]["id"]}', json={'user_id': uid}))
        d = ok(a.get(f'/api/documents/{v1}'))
        assert [p['full_name'] for p in d['people']] == ['Ahmet Yılmaz']   # firma kişisi evrağın kişilerine eklendi
        # kişi ve personel detayında (Rehber) bu evrak görünür
        assert [x['id'] for x in ok(a.get(f'/api/crm/person/{pid}'))['documents']] == [v1]
        assert v1 in [x['id'] for x in ok(a.get(f'/api/crm/user/{uid}'))['documents']]

        # ---- Video 2: aynı kişiler yeniden görülür → otomatik öneri; tanımadığı kişi tanımsız kalır
        fake['faces'] = [{'embedding': unit(0, person_a, 0.25), 'samples': 5, 'first_at': 2.0, 'crop': crop},
                         {'embedding': unit(0, person_b, 0.25), 'samples': 4, 'first_at': 3.0, 'crop': crop},
                         {'embedding': unit(3), 'samples': 2, 'first_at': 6.0, 'crop': crop}]
        v2 = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'saha.mp4', b'\0' * 64)], 'title': 'Saha videosu'}))['ids'][0]
        faces = wait(a, v2)['faces']
        assert [(f['person_id'], f['user_id'], f['auto']) for f in faces] == [(pid, None, 1), (None, uid, 1), (None, None, 0)]
        assert [p['full_name'] for p in ok(a.get(f'/api/documents/{v2}'))['people']] == ['Ahmet Yılmaz']
        # Öneri yanlışsa tanımsız yapılır: otomatik eklenen kişi bağlantısı kalkar
        ok(a.put(f'/api/documents/{v2}/faces/{faces[0]["id"]}', json={}))
        assert ok(a.get(f'/api/documents/{v2}'))['people'] == []
        # Yanlış tespit kaldırılır (görüntü de silinir)
        crop_path = faces[2]['crop']
        r = ok(a.delete(f'/api/documents/{v2}/faces/{faces[2]["id"]}'))
        assert len(r['faces']) == 2 and a.get(f'/api/files/{crop_path}').status_code in (403, 404)

        # ---- Resim: her yüz ayrı kişi; tanınan (Ahmet) otomatik önerilir, diğeri tanımsız
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (64, 64), 'white').save(buf, 'PNG')
        fake['image'] = [{'embedding': unit(0, person_a, 0.2), 'samples': 1, 'first_at': None, 'crop': crop},
                         {'embedding': unit(4), 'samples': 1, 'first_at': None, 'crop': crop}]
        im = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'grup.png', buf.getvalue())], 'title': 'Grup fotoğrafı'}))['ids'][0]
        d = wait(a, im)
        assert d['kind'] == 'RESIM' and [(f['person_id'], f['auto'], f['first_at']) for f in d['faces']] == [(pid, 1, None), (None, 0, None)]
        assert [p['full_name'] for p in d['people']] == ['Ahmet Yılmaz']
        ok(a.put(f'/api/documents/{im}/faces/{d["faces"][1]["id"]}', json={'user_id': uid}))
        assert im in [x['id'] for x in ok(a.get(f'/api/crm/user/{uid}'))['documents']]
        fake['image'] = []   # yüzsüz resim: kişi listesi boş
        empty = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'manzara.png', buf.getvalue())], 'title': 'Manzara'}))['ids'][0]
        assert wait(a, empty)['faces'] == []

        # ---- Başka kullanıcı: evrağı göremiyorsa yüzlerine de erişemez
        pv = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'gizli.mp4', b'\0' * 64)], 'title': 'Gizli',
                                               'visibility': 'PRIVATE'}))['ids'][0]
        pfaces = wait(a, pv)['faces']
        ok(a.post('/api/users', json={'username': 'idari@test', 'full_name': 'İdari', 'roles': ['İdari Personel'], 'password': 'sifre-1234'}))
    with TestClient(app) as o:
        ok(o.post('/api/auth/login', json={'username': 'idari@test', 'password': 'sifre-1234'}))
        assert o.get(f'/api/files/{pfaces[0]["crop"]}').status_code in (403, 404)
        assert o.put(f'/api/documents/{pv}/faces/{pfaces[0]["id"]}', json={'person_id': pid}).status_code == 404
        assert o.get(f'/api/files/{ok(o.get(f"/api/documents/{v1}"))["faces"][0]["crop"]}').status_code == 200
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        # Evrak silinince yüz görüntüleri de silinir
        crops = [f['crop'] for f in ok(a.get(f'/api/documents/{v1}'))['faces']]
        ok(a.delete(f'/api/documents/{v1}'))
        from app import config
        assert not any((config.UPLOAD_DIR / c).exists() for c in crops)
        with db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM document_faces WHERE document_id = ?', (v1,)).fetchone()[0] == 0
    print('Ses ve video (konuşma metni, yüz tanıma) testleri geçti.')


if __name__ == '__main__':
    main()
