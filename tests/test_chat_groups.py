"""Mesajlaşma grupları ve "Tüm Şirket" kanalı: grup kurma, grupça yazışma, okunmamış sayısı, üye yönetimi, ayrılma;
Tüm Şirket'e herkes üyedir, yalnızca Sistem Yöneticisi yazar; grup dosyasını yalnızca üyeler açar.

Çalıştırma: .venv/bin/python -m tests.test_chat_groups
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a, TestClient(app) as al, TestClient(app) as ay, TestClient(app) as ve:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ids = {u: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
               for u in ('ali', 'ayse', 'veli')}
        for c, u in ((al, 'ali'), (ay, 'ayse'), (ve, 'veli')):
            ok(c.post('/api/auth/login', json={'username': u, 'password': 'sifre-1234'}))
        # Tüm Şirket: herkesin listesinde, yalnızca yönetici yazar
        comp = next(x for x in ok(al.get('/api/chat/summary'))['items'] if x.get('is_company'))
        cid = comp['id']
        assert comp['kind'] == 'group' and comp['name'] == 'Tüm Şirket'
        assert al.post(f'/api/chat/g/{cid}', data={'body': 'selam'}).status_code == 403
        ok(a.post(f'/api/chat/g/{cid}', data={'body': 'Yarın fabrika saat 09.00 açılıyor'}))
        for c in (al, ay, ve):
            s = ok(c.get('/api/chat/summary'))
            item = next(x for x in s['items'] if x['id'] == cid and x['kind'] == 'group')
            assert item['unread'] == 1 and s['people'] >= 1
        d = ok(al.get(f'/api/chat/g/{cid}'))
        assert not d['group']['can_post'] and d['items'][0]['body'].startswith('Yarın')
        assert next(x for x in ok(al.get('/api/chat/summary'))['items'] if x['id'] == cid and x['kind'] == 'group')['unread'] == 0
        assert al.delete(f'/api/chat/groups/{cid}/me').status_code == 400
        # Grup kur, yazış
        assert al.post('/api/chat/groups', json={'name': ' ', 'user_ids': [ids['ayse']]}).status_code == 400
        assert al.post('/api/chat/groups', json={'name': 'Ekip', 'user_ids': []}).status_code == 400
        g = ok(al.post('/api/chat/groups', json={'name': 'Üretim ekibi', 'user_ids': [ids['ayse']]}))
        gid = g['id']
        assert g['can_edit'] and g['member_count'] == 2
        assert ve.get(f'/api/chat/g/{gid}').status_code == 404                       # üye değil
        m = ok(al.post(f'/api/chat/g/{gid}', data={'body': 'Toplantı 14:00'}, files={'file': ('plan.pdf', b'%PDF-1.4', 'application/pdf')}))
        assert m['from_name'] == 'Ali' and m['file_kind'] == 'file'
        assert ay.get('/api/files/' + m['file']).status_code == 200 and ve.get('/api/files/' + m['file']).status_code == 404
        s = ok(ay.get('/api/chat/summary'))
        gi = next(x for x in s['items'] if x['id'] == gid and x['kind'] == 'group')
        assert gi['unread'] == 1 and gi['from_name'] == 'Ali'
        ok(ay.post(f'/api/chat/g/{gid}', data={'body': 'Tamam'}))
        assert len(ok(al.get(f'/api/chat/g/{gid}?after={m["id"]}'))['items']) == 1
        # Üye yönetimi: yalnızca grup yöneticisi
        assert ay.put(f'/api/chat/groups/{gid}', json={'name': 'X', 'user_ids': []}).status_code == 403
        g = ok(al.put(f'/api/chat/groups/{gid}', json={'name': 'Üretim', 'user_ids': [ids['ayse'], ids['veli']]}))
        assert g['name'] == 'Üretim' and g['member_count'] == 3
        ok(ve.get(f'/api/chat/g/{gid}'))
        # Ayrılma: yönetici ayrılınca en eski üye yönetici olur; son kişi ayrılınca grup silinir
        ok(al.delete(f'/api/chat/groups/{gid}/me'))
        assert al.get(f'/api/chat/g/{gid}').status_code == 404
        assert ok(ay.get(f'/api/chat/groups/{gid}'))['can_edit']
        ok(ay.delete(f'/api/chat/groups/{gid}/me')); ok(ve.delete(f'/api/chat/groups/{gid}/me'))
        assert ay.get(f'/api/chat/groups/{gid}').status_code == 404
    print('Mesaj grupları ve Tüm Şirket testleri geçti.')


if __name__ == '__main__':
    main()
