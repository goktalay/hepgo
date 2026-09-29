"""Üretim planlayıcı testi: yazıcı durumlarına göre kullanılabilirlik, uçak uçak / en kısa süre sıralaması,
çakışmasız yazıcı sıraları, "şimdi yükleyin" listesi ve yetki.

Çalıştırma: .venv/bin/python -m tests.test_planner
"""
import os
import tempfile
from datetime import datetime

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ids = {}
        for i, (name, state, prog, file) in enumerate([
                ('P1', 'HAZIR', 0, None), ('P2', 'TAMAMLANDI', 100, 'x.gcode'), ('P3', 'HAZIR', 0, None),
                ('P4', 'YAZDIRIYOR', 50, 'c5-orta-part1_ABS_19h40m.gcode'),   # 01: 1180 dk → ~590 dk kaldı
                ('P5', 'CEVRIMDISI', 0, None), ('P6', 'HATA', 0, None)], 1):
            ids[name] = ok(a.post('/api/printers', json={'name': name, 'ip': f'10.0.0.{i}'}))['id']
            with db.connect() as c:
                c.execute('UPDATE printers SET live_state = ?, live_progress = ?, live_file = ? WHERE id = ?', (state, prog, file, ids[name]))
        prods = ok(a.get('/api/planner/products'))
        cyz = next(p for p in prods if p['code'] == 'CYZ')
        assert cyz['part_count'] == 64 and cyz['print_minutes'] == 35683
        assert a.post('/api/planner/plan', json={'product_id': cyz['id'], 'quantity': 0}).status_code == 400
        assert a.post('/api/planner/plan', json={'product_id': 99999}).status_code == 404

        r = ok(a.post('/api/planner/plan', json={'product_id': cyz['id'], 'quantity': 2, 'change_minutes': 15}))
        assert r['jobs'] == 128 and r['total_print_minutes'] == 2 * 35683 and r['unknown_parts'] == []
        names = [p['name'] for p in r['printers']]
        assert names == ['P1', 'P2', 'P3', 'P4'] and {u['name'] for u in r['unusable']} == {'P5', 'P6'}
        assert sum(len(p['jobs']) for p in r['printers']) == 128
        busy = next(p for p in r['printers'] if p['name'] == 'P4')['busy']
        assert busy['part'] == '01' and not busy['recorded'] and not busy['estimated']
        now = datetime.fromisoformat(r['now'])
        left = (datetime.fromisoformat(busy['until']) - now).total_seconds() / 60
        assert 585 <= left <= 595, left
        # P4'ün ilk işi, mevcut baskı + hazırlık süresinden sonra başlar
        p4 = next(p for p in r['printers'] if p['name'] == 'P4')
        assert datetime.fromisoformat(p4['jobs'][0]['start']) >= datetime.fromisoformat(busy['until'])
        # şimdi yüklenecekler: boştaki üç yazıcı, en uzun parçalar önce (uçak uçak)
        assert [f['printer'] for f in r['first_loads']] == ['P1', 'P2', 'P3'] and all(f['aircraft'] == 1 for f in r['first_loads'])
        assert r['first_loads'][0]['part'] == '05' and r['first_loads'][0]['file'] == 'c5-orta-part5-aracustu_ABS_1d3h20m'
        # yazıcı sıraları çakışmaz; aralarında hazırlık süresi var
        for p in r['printers']:
            for j1, j2 in zip(p['jobs'], p['jobs'][1:]):
                gap = (datetime.fromisoformat(j2['start']) - datetime.fromisoformat(j1['end'])).total_seconds() / 60
                assert gap >= 15, (p['name'], gap)
        done = {d['aircraft']: d['end'] for d in r['aircraft_done']}
        assert done[1] < done[2] and r['end'] == done[2]
        fast = ok(a.post('/api/planner/plan', json={'product_id': cyz['id'], 'quantity': 2, 'mode': 'fastest'}))
        assert fast['end'] <= r['end']
        # tüm yazıcılar boşmuş gibi: anlık durum yok sayılır; 6 yazıcının hepsi şimdi yüklenir
        idle = ok(a.post('/api/planner/plan', json={'product_id': cyz['id'], 'quantity': 2, 'assume_idle': True}))
        assert idle['assume_idle'] and idle['unusable'] == [] and len(idle['printers']) == 6
        assert all(p['busy'] is None and p['note'] is None for p in idle['printers'])
        assert len(idle['first_loads']) == 6 and idle['end'] < r['end']

        pilot = ok(a.post('/api/users', json={'username': 'pilot@t', 'full_name': 'Pilot', 'roles': ['Pilot'], 'password': 'sifre-1234'}))
        assert pilot
    with TestClient(app) as p:   # Araçlar modülü tüm rollere açık
        ok(p.post('/api/auth/login', json={'username': 'pilot@t', 'password': 'sifre-1234'}))
        assert p.get('/api/planner/products').status_code == 200
    print('Üretim planlayıcı testleri geçti.')


if __name__ == '__main__':
    main()
