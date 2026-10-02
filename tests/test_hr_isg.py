"""İK › İSG testleri: görev tanımı üst bilgileri, bölümlü maddeler (rol › aşama), KKD / eğitim / tehlike listeleri,
görev matrisi, İSG genel hükümleri ve saha belgelerinde pozisyon görevlerinin öncelikli kullanılması.

Çalıştırma: .venv/bin/python -m tests.test_hr_isg
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.hr import shareable_duties  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        uid = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot Bey', 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
        uid2 = ok(a.post('/api/users', json={'username': 'vekil@test', 'full_name': 'Vekil Bey', 'roles': ['Saha Personeli'], 'password': 'sifre-1234'}))['id']
        emps = ok(a.get('/api/hr/employees'))
        eid = next(e['id'] for e in emps if e.get('username') == 'pilot@test')
        did = next(e['id'] for e in emps if e.get('username') == 'vekil@test')
        with db.connect() as c:   # kabul edilmiş aktif personel
            c.execute("UPDATE employees SET status = 'AKTIF' WHERE id IN (?, ?)", (eid, did)); c.commit()
        i = ok(a.put(f'/api/hr/employees/{eid}/isg', json={'flight_position': 'Pilot / Uçuş Komutanı', 'supervisor': 'Saha Amiri',
                                                           'deputy_id': did, 'emergency_duty': 'Abort / RTL uygular', 'duty_doc_no': 'GT-07'}))
        assert i['flight_position'] == 'Pilot / Uçuş Komutanı' and i['deputy_name'] == 'Vekil Bey'
        assert a.put(f'/api/hr/employees/{eid}/isg', json={'deputy_id': eid}).status_code == 400   # kendisi vekil olamaz
        for kind, body in (('ppe', {'name': 'Yelek (EN ISO 20471)', 'usage': 'Test alanında her zaman'}),
                           ('trainings', {'name': 'Temel İSG', 'done_at': '2026-09-01', 'valid_until': '2027-09-01'}),
                           ('hazards', {'hazard': 'Yorgunluk', 'control': 'Mola planı'})):
            r = ok(a.post(f'/api/hr/employees/{eid}/isg/{kind}', json=body))
        assert (len(r['ppe']), len(r['trainings']), len(r['hazards'])) == (1, 1, 1)
        assert a.post(f'/api/hr/employees/{eid}/isg/ppe', json={'usage': 'x'}).status_code == 400   # ad zorunlu
        assert a.post(f'/api/hr/employees/{eid}/isg/xx', json={'name': 'x'}).status_code == 404
        ok(a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'Uçuşu yönetir', 'section': 'POZISYON'}))
        d = ok(a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'Run-up yapar', 'section': 'ROL', 'role': 'Pilot', 'phase': 'Uçuş öncesi'}))
        assert [(x['section'], x['role'], x['phase']) for x in d] == [('POZISYON', None, None), ('ROL', 'Pilot', 'Uçuş öncesi')]
        assert a.post(f'/api/hr/employees/{eid}/duties', json={'text': 'x', 'section': 'YOK'}).status_code == 400
        e = ok(a.get(f'/api/hr/employees/{eid}'))
        assert e['isg']['emergency_duty'] == 'Abort / RTL uygular' and len(e['isg']['hazards']) == 1
        m = {r['name']: r for r in ok(a.get('/api/hr/matrix'))}
        assert m['Pilot Bey']['flight_position'] == 'Pilot / Uçuş Komutanı' and m['Pilot Bey']['deputy_name'] == 'Vekil Bey' and m['Pilot Bey']['roles'] == ['Pilot']
        g = ok(a.put('/api/hr/isg-general', json={'doc_no': 'GKT-01', 'common': ['KKD kullanır'], 'zones': [{'a': 'SAHA TEMİZ', 'b': 'Saha Amiri verir'}]}))
        assert ok(a.get('/api/hr/isg-general'))['zones'][0]['a'] == 'SAHA TEMİZ' and g['legal'] == []
        with db.connect() as c:
            assert shareable_duties(c, [uid]) == {uid: ['Uçuşu yönetir']}   # saha belgelerinde pozisyon görevleri önce
    print('İK İSG testleri geçti.')


if __name__ == '__main__':
    main()
