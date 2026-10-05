"""İnsan Kaynakları: iş başvurusu (TC, kaynak, CV), ret / kabul, özlük dosyaları ve sözleşmeler (eksikse kırmızı),
kullanıcı = personel eşleşmesi, izin talebi → İK onayı (tarih değiştirerek) ve bildirimler, yetki.

Çalıştırma: .venv/bin/python -m tests.test_hr
"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers.hr import valid_tc  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def tc(n):
    """Geçerli TC üretir (ilk 9 hane n'den)."""
    d = [int(c) for c in f'{n:09d}']
    d.append((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10)
    d.append(sum(d) % 10)
    return ''.join(map(str, d))


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


PDF = ('belge.pdf', b'%PDF-1.4\n%test\n', 'application/pdf')


def main():
    assert valid_tc('10000000146') and not valid_tc('10000000147') and not valid_tc('01234567890')
    d = lambda n: (date.today() + timedelta(days=n)).isoformat()   # noqa: E731
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        ok(a.post('/api/users', json={'username': 'ik', 'full_name': 'İnsan Kaynak', 'roles': ['İnsan Kaynakları'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'ali', 'full_name': 'Ali Veli Yılmaz', 'roles': ['Montaj Personeli'], 'password': 'sifre-1234'}))
    with TestClient(app) as ik:
        login(ik, 'ik')
        assert set(ok(ik.get('/api/auth/me'))['modules']) >= {'hr'}
        # Her kullanıcı aynı zamanda personel (aktif, TC henüz yok)
        emps = ok(ik.get('/api/hr/employees'))
        ali = next(e for e in emps if e['username'] == 'ali')
        assert (ali['status'], ali['first_name'], ali['last_name'], ali['tc_no']) == ('AKTIF', 'Ali Veli', 'Yılmaz', None)
        assert len(ali['missing']) == 9   # 6 özlük (askerlik: cinsiyet girilmemiş; banka zorunlu değil) + 3 sözleşme → kırmızı

        # İş başvurusu: TC zorunlu ve geçerli, kaynak zorunlu
        app_body = {'tc_no': tc(123456789), 'first_name': 'Ayşe', 'last_name': 'Demir', 'gender': 'K', 'phone': '0555',
                    'position': 'Montaj Teknisyeni', 'source': 'Kariyer.net'}
        assert ik.post('/api/hr/applications', json={**app_body, 'tc_no': '12345678901'}).status_code == 400
        assert ik.post('/api/hr/applications', json={**app_body, 'source': None}).status_code == 400
        aid = ok(ik.post('/api/hr/applications', json=app_body))['id']
        assert ik.post('/api/hr/applications', json=app_body).status_code == 409   # aynı TC
        ok(ik.post(f'/api/hr/employees/{aid}/cv', files={'file': ('cv.pdf', PDF[1], 'application/pdf')}))
        e = ok(ik.get(f'/api/hr/employees/{aid}'))
        assert e['status'] == 'BASVURU' and e['user_id'] is None and e['cv_name'] == 'cv.pdf' and e['missing'] == []
        assert ik.get(f'/api/files/{e["cv_file"]}').status_code == 200
        # başvuru aşamasında özlük dosyası girilmez
        assert ik.post(f'/api/hr/employees/{aid}/files/SAGLIK', files={'file': PDF}).status_code == 400
        # Ret: sebep zorunlu; yeniden değerlendirme
        assert ik.post(f'/api/hr/employees/{aid}/reject', json={'reason': ' '}).status_code == 400
        ok(ik.post(f'/api/hr/employees/{aid}/reject', json={'reason': 'Deneyim yetersiz'}))
        assert ok(ik.get(f'/api/hr/employees/{aid}'))['status'] == 'REDDEDILDI'
        assert ik.post(f'/api/hr/employees/{aid}/accept', json={'title': 'X', 'start_date': d(0)}).status_code == 400
        ok(ik.post(f'/api/hr/employees/{aid}/reopen'))
        # Kabul: görev ve resmi işe başlama tarihi zorunlu
        assert ik.post(f'/api/hr/employees/{aid}/accept', json={'title': 'Montaj', 'start_date': ''}).status_code == 400
        ok(ik.post(f'/api/hr/employees/{aid}/accept', json={'title': 'Montaj Teknisyeni', 'salary': 30000, 'start_date': d(3)}))
        e = ok(ik.get(f'/api/hr/employees/{aid}'))
        assert (e['status'], e['title'], e['salary'], e['start_date']) == ('AKTIF', 'Montaj Teknisyeni', 30000, d(3))
        assert len(e['missing']) == 8 and 'Askerlik Durum Belgesi' not in e['missing']   # kadın: askerlik istenmez; banka zorunlu değil
        # Maaş / görev değişikliği geçmişe yazılır
        ok(ik.put(f'/api/hr/employees/{aid}', json={**app_body, 'title': 'Montaj Sorumlusu', 'salary': 35000, 'start_date': d(3)}))
        assert any('Maaş' in (ev['detail'] or '') and 'Görev' in ev['detail'] for ev in ok(ik.get(f'/api/hr/employees/{aid}'))['events'])
        # Özlük dosyaları ve sözleşmeler: hepsi girilince eksik kalmaz
        for kind in ('ADLI_SICIL', 'SAGLIK', 'MEZUNIYET', 'HIZMET_DOKUMU', 'BANKA', 'GIZLILIK', 'IS_SOZLESMESI', 'ARAC'):
            ok(ik.post(f'/api/hr/employees/{aid}/files/{kind}', files={'file': PDF}))
        e = ok(ik.get(f'/api/hr/employees/{aid}'))
        assert e['missing'] == ['Vesikalık Fotoğraf']
        png = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                            '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')
        ok(ik.post(f'/api/hr/employees/{aid}/files/VESIKALIK', files={'file': ('foto.png', png, 'image/png')}))
        e = ok(ik.get(f'/api/hr/employees/{aid}'))
        assert e['missing'] == [] and e['photo_file']
        fid = e['files']['ARAC']['id']
        ok(ik.delete(f'/api/hr/employees/{aid}/files/{fid}'))
        assert ok(ik.get(f'/api/hr/employees/{aid}'))['missing'] == ['Araç Kullanım Sözleşmesi']
        assert ik.post(f'/api/hr/employees/{aid}/files/XYZ', files={'file': PDF}).status_code == 400

        # Adresler: birden fazla, biri birincil; posta kodu 5 hane
        a1 = ok(ik.post(f'/api/hr/employees/{aid}/addresses', json={'label': 'Ev', 'address': 'Atatürk Mah. 1. Sok. No:3', 'district': 'Çankaya', 'city': 'Ankara', 'postal_code': '06100'}))['id']
        a2 = ok(ik.post(f'/api/hr/employees/{aid}/addresses', json={'label': 'Tebligat', 'address': 'Kızılay Cad. No:5'}))['id']
        assert ik.post(f'/api/hr/employees/{aid}/addresses', json={'label': 'Ev', 'address': ' '}).status_code == 400
        assert ik.post(f'/api/hr/employees/{aid}/addresses', json={'label': 'Ev', 'address': 'x', 'postal_code': '12'}).status_code == 400
        adr = ok(ik.get(f'/api/hr/employees/{aid}'))['addresses']
        assert [(a['id'], a['is_primary']) for a in adr] == [(a1, 1), (a2, 0)]   # ilk adres birincil
        ok(ik.put(f'/api/hr/employees/{aid}/addresses/{a2}', json={'label': 'Tebligat', 'address': 'Kızılay Cad. No:7', 'is_primary': True}))
        adr = ok(ik.get(f'/api/hr/employees/{aid}'))['addresses']
        assert [(a['id'], a['is_primary']) for a in adr] == [(a2, 1), (a1, 0)] and adr[0]['address'] == 'Kızılay Cad. No:7'
        ok(ik.delete(f'/api/hr/employees/{aid}/addresses/{a2}'))
        assert [(a['id'], a['is_primary']) for a in ok(ik.get(f'/api/hr/employees/{aid}'))['addresses']] == [(a1, 1)]   # kalan birincil olur
        assert any(ev['action'] == 'Adres silindi' for ev in ok(ik.get(f'/api/hr/employees/{aid}'))['events'])

        # Kullanıcıyla eşleştirme: Ali'nin otomatik kaydı (TC'siz, dosyasız) birleştirilir
        ali_uid = ali['user_id']
        ok(ik.put(f'/api/hr/employees/{aid}/user', json={'user_id': ali_uid}))
        assert ik.get(f'/api/hr/employees/{ali["id"]}').status_code == 404
        ok(ik.put(f'/api/hr/employees/{aid}/user', json={'user_id': None}))   # geri al
        ok(ik.get('/api/hr/employees'))   # Ali yeniden otomatik personel olur
        ok(ik.put(f'/api/hr/employees/{aid}/user', json={'user_id': ali_uid}))

    # İzin: personel (Ali) ister → İK tarih değiştirerek onaylar → Ali bildirim alır; istenen / verilen ayrı
    with TestClient(app) as u:
        login(u, 'ali')
        leave = {'kind': 'UCRETLI', 'start': d(10), 'end': d(14), 'reason': 'Aile ziyareti', 'location': 'Ankara'}
        assert u.post('/api/me/leaves', json={**leave, 'location': ''}).status_code == 400
        assert u.post('/api/me/leaves', json={**leave, 'end': d(5)}).status_code == 400
        assert u.post('/api/me/leaves', json={**leave, 'start': d(-3)}).status_code == 400
        lid = ok(u.post('/api/me/leaves', json=leave))['id']
        l2 = ok(u.post('/api/me/leaves', json={**leave, 'kind': 'UCRETSIZ', 'start': d(30), 'end': d(30)}))['id']
        ok(u.delete(f'/api/me/leaves/{l2}'))
        assert u.get('/api/hr/employees').status_code == 403   # İK modülü yok
        assert u.get(f'/api/files/{e["cv_file"]}').status_code == 404   # İK dosyaları yalnızca İK'ya (varlığı da belli edilmez)
    with TestClient(app) as ik:
        login(ik, 'ik')
        assert any(n['key'] == 'hr-leave-pending' for n in ok(ik.get('/api/notifications'))['items'])
        assert [x['id'] for x in ok(ik.get('/api/hr/leaves?status=BEKLIYOR'))] == [lid]
        assert ik.post(f'/api/hr/leaves/{lid}/approve', json={'start': d(11), 'end': d(9)}).status_code == 400
        ok(ik.post(f'/api/hr/leaves/{lid}/approve', json={'start': d(11), 'end': d(13), 'note': 'Yoğunluk nedeniyle kısaltıldı'}))
        r = next(x for x in ok(ik.get('/api/hr/leaves')) if x['id'] == lid)
        assert (r['req_start'], r['req_end'], r['start_date'], r['end_date'], r['req_days'], r['days'], r['changed']) == (
            d(10), d(14), d(11), d(13), 5, 3, True)
        assert ik.post(f'/api/hr/leaves/{lid}/reject', json={'note': 'x'}).status_code == 400   # sonuçlandı
        # Islak imzalı form: onaylanan izin imzasız görünür (personel kırmızı), form yüklenince düzelir
        assert r['unsigned'] and ok(ik.get(f'/api/hr/employees/{aid}'))['unsigned_leaves'] == 1
        assert next(x for x in ok(ik.get('/api/hr/employees')) if x['id'] == aid)['unsigned_leaves'] == 1
        assert ik.post(f'/api/hr/leaves/{l2}/signed', files={'file': PDF}).status_code == 400   # geri çekilen izne eklenmez
        ok(ik.post(f'/api/hr/leaves/{lid}/signed', files={'file': ('izin-imzali.pdf', PDF[1], 'application/pdf')}))
        r = next(x for x in ok(ik.get('/api/hr/leaves')) if x['id'] == lid)
        assert not r['unsigned'] and r['signed_name'] == 'izin-imzali.pdf' and r['signed_by_name'] == 'İnsan Kaynak'
        assert ok(ik.get(f'/api/hr/employees/{aid}'))['unsigned_leaves'] == 0
        ok(ik.delete(f'/api/hr/leaves/{lid}/signed'))
        assert ok(ik.get(f'/api/hr/employees/{aid}'))['unsigned_leaves'] == 1
        ok(ik.post(f'/api/hr/leaves/{lid}/signed', files={'file': PDF}))
        # İK personel adına izin girer (onaylı)
        ok(ik.post(f'/api/hr/employees/{aid}/leaves', json={**leave, 'kind': 'UCRETSIZ', 'start': d(40), 'end': d(41)}))
        # İşten ayrılış ve yeniden işe alma
        ok(ik.post(f'/api/hr/employees/{aid}/leave-job', json={'end_date': d(60), 'reason': 'İstifa'}))
        assert ok(ik.get(f'/api/hr/employees/{aid}'))['status'] == 'AYRILDI'
        ok(ik.post(f'/api/hr/employees/{aid}/rehire'))
    with TestClient(app) as u:
        login(u, 'ali')
        assert any(n['key'] == 'leave-decided' for n in ok(u.get('/api/notifications'))['items'])
        mine = ok(u.get('/api/me/leaves'))
        assert mine['used_paid_this_year'] in (3, 0) and len(mine['items']) == 3
        assert not any(n['key'] == 'leave-decided' for n in ok(u.get('/api/notifications'))['items'])   # görüldü
    print('İnsan Kaynakları testleri geçti.')


if __name__ == '__main__':
    main()
