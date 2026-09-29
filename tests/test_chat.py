"""Canlı mesajlaşma: metin, dosya / resim, sesli mesaj; okunmamışlar gönderene göre gruplanır; okundu bilgisi;
dosyayı yalnızca iki taraf açabilir.

Çalıştırma: .venv/bin/python -m tests.test_chat
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082')


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    return ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def main():
    with TestClient(app) as a:
        me = login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
        ali, ayse, veli = mk('ali'), mk('ayse'), mk('veli')
        admin_id = ok(a.get('/api/auth/me'))['id']
    with TestClient(app) as al, TestClient(app) as ay, TestClient(app) as ve:
        login(al, 'ali'); login(ay, 'ayse'); login(ve, 'veli')
        assert al.post(f'/api/chat/{ali}', data={'body': 'x'}).status_code == 400          # kendine
        assert al.post(f'/api/chat/{ayse}', data={'body': '  '}).status_code == 400        # boş
        assert al.post('/api/chat/99999', data={'body': 'x'}).status_code == 404
        m1 = ok(al.post(f'/api/chat/{ayse}', data={'body': 'Merhaba Ayşe'}))
        ok(al.post(f'/api/chat/{ayse}', data={'body': 'Resim'}, files={'file': ('foto.png', PNG, 'image/png')}))
        ok(al.post(f'/api/chat/{ayse}', data={'duration': '2.4'}, files={'file': ('ses.webm', b'\x1aE\xdf\xa3' + b'0' * 200, 'audio/webm')}))
        f = ok(al.post(f'/api/chat/{ayse}', files={'file': ('rapor.pdf', b'%PDF-1.4 test', 'application/pdf')}))
        assert al.post(f'/api/chat/{ayse}', files={'file': ('x.html', b'<script>', 'text/html')}).status_code == 400
        ok(ve.post(f'/api/chat/{ayse}', data={'body': 'Selam'}))
        s = ok(ay.get('/api/chat/summary'))
        assert s['people'] == 2 and s['unread'] == 5                                          # gönderene göre gruplu
        byid = {x['id']: x for x in s['items']}
        assert byid[ali]['unread'] == 4 and byid[veli]['unread'] == 1 and byid[ali]['file_kind'] == 'file'
        d = ok(ay.get(f'/api/chat/{ali}'))
        kinds = [m['file_kind'] for m in d['items']]
        assert kinds == [None, 'image', 'audio', 'file'] and d['items'][2]['duration'] == 2.4 and d['peer']['full_name'] == 'Ali'
        assert d['items'][3]['file_name'] == 'rapor.pdf' and d['items'][3]['file_size'] > 0
        s = ok(ay.get('/api/chat/summary'))
        assert s['people'] == 1 and s['unread'] == 1                                          # ali okundu, veli bekliyor
        # dosya: iki taraf açar, üçüncü kişi açamaz
        url = '/api/files/' + f['file']
        assert al.get(url).status_code == 200 and ay.get(url).status_code == 200 and ve.get(url).status_code == 404
        # okundu bilgisi ve yeni mesajlar (after)
        d = ok(al.get(f'/api/chat/{ayse}'))
        assert d['seen_upto'] == f['id']
        r = ok(ay.post(f'/api/chat/{ali}', data={'body': 'Aldım'}))
        new = ok(al.get(f'/api/chat/{ayse}?after={f["id"]}'))['items']
        assert [m['id'] for m in new] == [r['id']]
        older = ok(al.get(f'/api/chat/{ayse}?before={f["id"]}'))['items']
        assert older[0]['id'] == m1['id'] and len(older) == 3
        s = ok(al.get('/api/chat/summary'))
        assert s['items'][0]['id'] == ayse and s['items'][0]['mine'] is False and s['unread'] == 0   # az önce okudu
        assert ok(ve.get('/api/system/details?what=users'))['me'] == veli
        # Çevrimiçi olan / ayrılan sesi için kimlikler: kendisi hariç
        ids = ok(ve.get('/api/system/status'))['online_ids']
        assert ayse in ids and ali in ids and veli not in ids
        # Gizlilik (Ayarlar): çevrimiçi gizle, okundu gönderme, mesaj alma
        assert ok(ve.get(f'/api/chat/{ayse}'))['peer']['online']
        ok(ay.put('/api/auth/prefs/settings', json={'privacy': {'hide_online': True, 'hide_read': True, 'no_messages': False}}))
        p = ok(ve.get(f'/api/chat/{ayse}'))['peer']
        assert not p['online'] and p['last_seen'] is None
        assert ayse not in [u['id'] for u in ok(ve.get('/api/system/details?what=users'))['users']]
        assert ayse not in ok(ve.get('/api/system/status'))['online_ids']                              # gizleyen sessiz
        assert ayse in [u['id'] for u in ok(ay.get('/api/system/details?what=users'))['users']]      # kendisi görür
        ok(ay.get(f'/api/chat/{veli}'))
        assert ok(ve.get(f'/api/chat/{ayse}'))['seen_upto'] == 0                                     # okundu gizli
        ok(ay.put('/api/auth/prefs/settings', json={'privacy': {'no_messages': True}}))
        r = ve.post(f'/api/chat/{ayse}', data={'body': 'x'})
        assert r.status_code == 400 and 'kapatmış' in r.json()['detail']
    print('Mesajlaşma testleri geçti.')


if __name__ == '__main__':
    main()
