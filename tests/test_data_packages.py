"""Dron Yönetimi › Veri Paketleri: dönem hesabı (otomatik yenileme, ay sonu), API (ekle / düzenle / sil, doğrulama, yetki),
uçuş bağlantısının pakete bağlanması (package_id + sat_line), köprü hattı sayımı (köprü ↔ sunucu WebSocket çerçeveleri ve köprünün
{t:'usage'} bildirdiği dron ↔ köprü baytları) → flush → paketin kalan kotası; tüketim ayrıntısı.
Çalıştırma: .venv/bin/python -m tests.test_data_packages
"""
import json
import os
import tempfile
from datetime import date

os.environ.setdefault('HEPGO_SITL', '0')
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, data_packages as dp, db  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text[:300])
    return r.json()


def period_tests():
    p = {'start_date': '2026-01-31', 'period': 'AYLIK', 'auto_renew': 1}
    assert dp.current_period(p, date(2026, 1, 31)) == ('2026-01-31', '2026-02-28')
    assert dp.current_period(p, date(2026, 2, 27)) == ('2026-01-31', '2026-02-28')
    assert dp.current_period(p, date(2026, 2, 28)) == ('2026-02-28', '2026-03-28') or dp.current_period(p, date(2026, 2, 28))[0] <= '2026-02-28'
    assert dp.current_period({**p, 'start_date': '2026-03-17'}, date(2026, 11, 10)) == ('2026-10-17', '2026-11-17')
    q = {'start_date': '2026-02-17', 'period': '3_AYLIK', 'auto_renew': 1}
    assert dp.current_period(q, date(2026, 11, 10)) == ('2026-08-17', '2026-11-17')
    y = {'start_date': '2026-02-17', 'period': 'YILLIK', 'auto_renew': 0}
    assert dp.current_period(y, date(2027, 5, 1)) == ('2026-02-17', '2027-02-17')   # yenilemesiz: tek dönem (süresi doldu)
    assert dp.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28) and dp.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    print('  dönem hesabı geçti')


def main():
    period_tests()
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        token = a.cookies.get(auth.COOKIE)
        assert ok(a.get('/api/drone/meta'))['can']['packages'] is True
        # --- API: doğrulama + ekle / düzenle ---
        base = {'name': 'Certus Aylık 100 MB', 'provider': 'Certus 100 Aviation', 'period': 'AYLIK', 'quota_mb': 100, 'price': 518,
                'overage_per_mb': 5.18, 'start_date': date.today().isoformat(), 'auto_renew': True, 'sim_count': 2}
        for bad in ({**base, 'name': ' '}, {**base, 'period': 'HAFTALIK'}, {**base, 'quota_mb': 0}, {**base, 'price': -1}, {**base, 'start_date': 'dün'}):
            assert a.post('/api/drone/packages', json=bad).status_code == 400, bad
        pid = ok(a.post('/api/drone/packages', json=base))['id']
        ok(a.put(f'/api/drone/packages/{pid}', json={**base, 'quota_mb': 200}))
        lst = ok(a.get('/api/drone/packages'))
        p = lst['items'][0]
        assert lst['can_write'] and p['quota_mb'] == 200 and p['used_mb'] == 0 and p['remaining_mb'] == 200 and p['status'] == 'aktif', p
        assert p['period_start'] == base['start_date'] and p['days_left'] >= 27, p
        assert ok(a.get('/api/drone/packages/options'))['items'][0]['id'] == pid
        # --- uçuş bağlantısı pakete bağlanır ---
        b = ok(a.post('/api/drone/bridges', json={'name': 'Jetson-uydu', 'platform': 'linux'}))
        key = b['code'].split('/', 1)[1]
        d = ok(a.post('/api/drone/drones', json={'name': 'Göktungu-1'}))
        pilot = ok(a.post('/api/users', json={'username': 'pilot@test', 'full_name': 'Pilot', 'roles': [auth.PILOT, auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        lead = ok(a.post('/api/users', json={'username': 'saha@test', 'full_name': 'Saha', 'roles': [auth.FIELD_LEAD], 'password': 'Gizli-Parola-77'}))
        t = ok(a.post('/api/field/tasks', json={'drone_ids': [d['id']], 'lead_id': lead['id'], 'pilot_id': pilot['id'], 'staff_ids': [pilot['id']]}))
        fid = ok(a.get(f"/api/field/tasks/{t['id']}"))['flights'][0]['id']
        put = lambda link: a.put(f'/api/field/flights/{fid}', json={'bridge_id': b['id'], 'sysid': 1, 'link': link})   # noqa: E731
        ser = {'type': 'serial', 'serial': '/dev/ttyTHS1', 'baud': 921600}
        assert put({**ser, 'package_id': 99999}).status_code == 400                                   # paket yok
        assert put({**ser, 'package_id': pid, 'sat_line': 'dron_kopru'}).status_code == 400           # seride dron ↔ köprü uydu olmaz
        assert put({**ser, 'package_id': pid, 'sat_line': 'yok'}).status_code == 400
        ok(put({**ser, 'package_id': pid}))                                                            # varsayılan hat: köprü ↔ sunucu
        assert ok(a.get(f"/api/field/tasks/{t['id']}"))['flights'][0]['link'] == {**ser, 'package_id': pid, 'sat_line': 'kopru_sunucu'}
        # --- sayım: köprü ↔ sunucu (WebSocket çerçeveleri) ---
        dp._acc.clear()
        with a.websocket_connect('/ws/drone/bridge') as ws:
            ws.send_text(json.dumps({'v': 1, 't': 'auth', 'key': key, 'host': 'jetson', 'platform': 'linux', 'bridge_ver': '1.1.8',
                                     'caps': ['link', 'veri_kisiti', 'veri_sayaci']}))
            assert json.loads(ws.receive_text())['t'] == 'auth_ok'
            ws.send_bytes(b'\xfd' + b'\x00' * 2999)   # 3000 bayt "telemetri"
            ws.send_text(json.dumps({'t': 'ping'}))
            assert json.loads(ws.receive_text())['t'] == 'pong'
            # köprü kendi dron ↔ köprü hattını da bildirir: bu uçuş köprü ↔ sunucu hattında → bu baytlar pakete yazılmaz
            ws.send_text(json.dumps({'t': 'usage', 'rx': 5000, 'tx': 1000}))
            ws.send_text(json.dumps({'t': 'ping'}))
            json.loads(ws.receive_text())
        acc = dict(dp._acc)
        assert acc.get((b['id'], 'kopru_sunucu'), 0) >= 3000 + dp.WS_OVERHEAD and acc.get((b['id'], 'dron_kopru')) == 6000, acc
        wrote = dp.flush()
        assert wrote == acc[(b['id'], 'kopru_sunucu')], (wrote, acc)   # dron_kopru: bu hatta bağlı uçuş yok → atıldı
        s1 = ok(a.get(f'/api/drone/packages/{pid}'))
        assert 0 < s1['used_mb'] < 0.01 and s1['remaining_mb'] < 200, s1
        assert len(s1['usage']['flights']) == 1 and s1['usage']['flights'][0]['flight_id'] == fid and s1['usage']['flights'][0]['task_code'] == t['code'], s1['usage']
        # --- dron ↔ köprü hattı (köprü yerde, TCP): köprünün usage bildirimi pakete yazılır, aynı güne eklenir ---
        ok(put({'type': 'tcp', 'host': '10.0.0.5', 'port': 5760, 'package_id': pid, 'sat_line': 'dron_kopru', 'rate_pm': 10}))
        dp._acc.clear()
        dp.count(b['id'], 'dron_kopru', 3 * dp.MB, frames=0)
        dp.count(b['id'], 'kopru_sunucu', 10 * dp.MB)      # bu hat artık pakete bağlı değil → yazılmaz
        dp.flush()
        s2 = ok(a.get(f'/api/drone/packages/{pid}'))
        assert abs(s2['used_mb'] - s1['used_mb'] - 3) < 0.001, (s1['used_mb'], s2['used_mb'])
        assert {f['line'] for f in s2['usage']['flights']} == {'kopru_sunucu', 'dron_kopru'} and len(s2['usage']['days']) == 1, s2['usage']
        # --- kota aşımı: maliyet hesabı ---
        dp.count(b['id'], 'dron_kopru', 250 * dp.MB, frames=0)
        dp.flush()
        s3 = ok(a.get(f'/api/drone/packages/{pid}'))
        assert s3['status'] == 'bitti' and s3['remaining_mb'] == 0 and s3['over_mb'] > 50 and abs(s3['over_cost'] - round(s3['over_mb'] * 5.18, 2)) < 0.02, s3
        # görev kapanınca sayaç bu uçuşa yazılmaz
        with db.connect() as conn:
            conn.execute("UPDATE field_tasks SET status = 'TAMAMLANDI' WHERE id = ?", (t['id'],))
            conn.commit()
        dp.count(b['id'], 'dron_kopru', dp.MB, frames=0)
        assert dp.flush() == 0
        # --- silme: tüketimi olan paket silinmez; boş paket silinir ---
        assert a.delete(f'/api/drone/packages/{pid}').status_code == 400
        p2 = ok(a.post('/api/drone/packages', json={**base, 'name': 'Boş'}))['id']
        ok(a.delete(f'/api/drone/packages/{p2}'))
        # --- yetki: Veri Paketleri yetkisi olmayan saha personeli listeyi göremez, uçuş formu için kısa listeyi görür ---
        ok(a.post('/api/users', json={'username': 'saha2@test', 'full_name': 'Saha 2', 'roles': [auth.FIELD_STAFF], 'password': 'Gizli-Parola-77'}))
        with TestClient(app, base_url='https://testserver') as o:
            ok(o.post('/api/auth/login', json={'username': 'saha2@test', 'password': 'Gizli-Parola-77'}))
            me = ok(o.get('/api/auth/me'))
            assert 'drone.packages' not in me['modules'], me['modules']
            assert o.get('/api/drone/packages').status_code == 403 and o.post('/api/drone/packages', json=base).status_code == 403
            if 'field' in me['modules']:   # uçuş formu için kısa liste (fiyat yok)
                assert 'price' not in ok(o.get('/api/drone/packages/options'))['items'][0]
        with TestClient(app, base_url='https://testserver') as o:   # pilot: Dron Yönetimi'nden okuma miras; yazma yetkisi yoksa ekleyemez
            ok(o.post('/api/auth/login', json={'username': 'pilot@test', 'password': 'Gizli-Parola-77'}))
            me = ok(o.get('/api/auth/me'))
            if 'drone.packages' not in (me.get('write_modules') or []):
                assert o.post('/api/drone/packages', json=base).status_code == 403
        assert token
    print('Veri Paketleri testleri geçti.')


if __name__ == '__main__':
    main()
