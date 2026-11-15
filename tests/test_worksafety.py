"""İş Güvenliği modülü: katalog (39 kural), yapılandırma (doğrulama / sınırlama), kamera kapsamı, uyarı listesi + süzgeç +
kapatma / geri alma, ısı haritası, dönem raporu (güvenlik puanı), işleyici durumu, canlı kaplama ve yetkiler.

Tespit motoru (model gerektirir) burada çalıştırılmaz; kural mantığı yapay tespitlerle sınanır.

Çalıştırma: .venv/bin/python -m tests.test_worksafety
"""
import json
import os
import tempfile
import time
from datetime import date, timedelta

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app import worksafety as W  # noqa: E402
from app import worksafety_rules as R  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def person(x, y, w=0.08, h=0.4, **kw):
    return {'box': [x, y, w, h], 'score': 0.9, **kw}


def rules_unit():
    """Kural motoru: bölge + süre + doğrulama (yapay tespitlerle)."""
    assert len(R.RULES) == 39 and len({r['key'] for r in R.RULES}) == 39 and [r['no'] for r in R.RULES] == list(range(1, 40))
    assert R.in_poly((0.5, 0.5), [[0, 0], [1, 0], [1, 1], [0, 1]]) and not R.in_poly((1.5, 0.5), [[0, 0], [1, 0], [1, 1], [0, 1]])
    assert abs(R.iou([0, 0, 0.2, 0.2], [0, 0, 0.2, 0.2]) - 1) < 1e-6 and R.iou([0, 0, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]) == 0
    cfg = W.default_config()
    eff = R.effective(cfg)
    assert not eff['after_hours']['on'] and not eff['too_close']['on'] and eff['restricted_entry']['on']
    caps = {'objects': True, 'pose': True, 'ppe': ['hardhat', 'vest'], 'classes': ['person', 'car', 'truck'], 'backend': 'cpu'}
    assert R.model_ok(R.BY_KEY['no_hardhat'], caps) == (True, None) and not R.model_ok(R.BY_KEY['no_hardhat'], {**caps, 'ppe': []})[0]
    assert not R.model_ok(R.BY_KEY['reba'], {**caps, 'pose': False})[0] and R.model_ok(R.BY_KEY['reba'], caps)[0]
    assert not R.model_ok(R.BY_KEY['restricted_entry'], {})[0]   # nesne modeli olmadan hiçbir kural çalışmaz


def main():
    rules_unit()
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'kam', 'full_name': 'Kam', 'roles': ['Kamera Yetkilisi'], 'password': 'sifre-1234'}))
        ok(a.post('/api/users', json={'username': 'sek', 'full_name': 'Sek', 'roles': ['Sekreter'], 'password': 'sifre-1234'}))
        assert 'worksafety' in ok(a.get('/api/auth/me'))['modules']

        # Katalog: 39 kural, kategoriler, bölge türleri; işleyici çalışmıyorken model durumu taşınmaz
        cat = ok(a.get('/api/worksafety/catalog'))
        assert len(cat['rules']) == 39 and {r['cat'] for r in cat['rules']} <= {c['key'] for c in cat['cats']}
        assert {z['key'] for z in cat['zone_types']} >= {'ppe_zone', 'restricted', 'machine', 'vehicle_lane', 'crossing', 'walkway'}
        assert cat['status']['running'] is False and cat['status']['enabled'] is False and 'model_ok' not in cat['rules'][0]
        assert cat['grid'] == [W.GRID_W, W.GRID_H] or cat['grid'] == {'w': W.GRID_W, 'h': W.GRID_H}

        # Yapılandırma: varsayılan kapalı; kaydetme doğrular / sınırlar, bilinmeyeni atar
        cfg = ok(a.get('/api/worksafety/config'))
        assert cfg == W.default_config()
        with db.connect() as conn:
            c1, c2 = [conn.execute('INSERT INTO cameras (name, location, stream_url, faces, active, status, created_at) VALUES (?,?,?,?,?,?,?)',
                                   (n, 'Atölye', 'rtsp://x', 1, 1, 'ok', db.now())).lastrowid for n in ('Hat 1', 'Depo')]
            conn.commit()
        body = {**cfg, 'enabled': True, 'cooldown': 5, 'interval': 999, 'faces_mode': 'bozuk', 'bilinmeyen': 1,
                'rules': {'no_hardhat': {'sev': 9, 'enabled': True}, 'olmayan_kural': {'enabled': True},
                          'forbidden_object': {'params': {'objects': ['cell phone'], 'yok': 1}}},
                'cameras': {str(c1): {'enabled': True, 'ppe': True, 'rules': None, 'zones': [
                    {'id': 'z1', 'name': 'Pres', 'type': 'machine', 'points': [[0.1, 0.1], [0.5, 0.1], [0.5, 0.9], [0.1, 0.9]], 'params': {}},
                    {'id': 'z2', 'name': 'Bozuk', 'type': 'olmayan_tur', 'points': [[0, 0], [1, 0], [1, 1]]},
                    {'id': 'z3', 'name': 'İki nokta', 'type': 'restricted', 'points': [[0, 0], [1, 1]]}]},
                    'abc': {'enabled': True}}}
        r = ok(a.put('/api/worksafety/config', json=body))
        got = r['config']
        assert r['ok'] and r['warning'] is None and got['enabled'] is True
        assert got['cooldown'] == 30 and got['interval'] == 60 and got['faces_mode'] == 'auto' and 'bilinmeyen' not in got
        assert got['rules']['no_hardhat']['sev'] == 5 and 'olmayan_kural' not in got['rules']
        assert got['rules']['forbidden_object']['params'] == {'objects': ['cell phone']}
        assert list(got['cameras']) == [str(c1)] and [z['id'] for z in got['cameras'][str(c1)]['zones']] == ['z1']
        assert ok(a.get('/api/worksafety/config')) == got

        # Kamera kapsamı
        cams = {c['id']: c for c in ok(a.get('/api/worksafety/cameras'))}
        assert cams[c1]['in_scope'] and cams[c1]['ppe'] and cams[c1]['zones'] == 1
        assert cams[c2]['in_scope'] and not cams[c2]['ppe'] and cams[c2]['zones'] == 0   # all_cameras: tümü kapsamda

        # Uyarılar: ekle, listele, süz, kapat, geri al
        eff = R.effective(got)
        today = date.today()
        with db.connect() as conn:
            ids = []
            for i, (k, cid, name) in enumerate([('no_hardhat', c1, 'Hat 1'), ('machine_unauth', c1, 'Hat 1'), ('fall', c2, 'Depo')]):
                r_ = eff[k]
                risk = r_['sev'] * r_['lik']
                ids.append(W.add_event(conn, cid, name, {
                    'rule': k, 'name': r_['name'], 'cat': r_['cat'], 'zone': 'z1' if k == 'machine_unauth' else None,
                    'zone_name': 'Pres' if k == 'machine_unauth' else None, 'sev': r_['sev'], 'lik': r_['lik'], 'risk': risk,
                    'level': next(n for t, n in R.LEVELS if risk >= t), 'detail': f'{r_["name"]} — 1 kişi',
                    'boxes': [[0.3, 0.3, 0.1, 0.4]], 'duration': 4.0 + i, 'viol': 1}))
            for d in range(3):
                day = (today - timedelta(days=d)).isoformat()
                W.stats_add(conn, day, 9, {(c1, 'no_hardhat'): [200, 10 + d], (c1, 'machine_unauth'): [200, 2], (c2, 'fall'): [100, 0]})
                W.stats_add(conn, day, 9, {(c1, 'no_hardhat'): [100, 0]})   # aynı saat: toplanır
                W.heat_add(conn, c1, day, 'person', {0: 3, 33: 5})
                W.heat_add(conn, c1, day, 'person', {33: 1})
            conn.commit()
        lst = lambda **prm: ok(a.get('/api/worksafety/events', params=prm))['rows']   # noqa: E731
        full = ok(a.get('/api/worksafety/events', params={'limit': 2}))
        assert full['total'] == 3 and len(full['rows']) == 2
        evs = lst()
        assert [e['id'] for e in evs] == ids[::-1] and evs[0]['rule'] == 'fall' and evs[0]['meta']['boxes'] == [[0.3, 0.3, 0.1, 0.4]] and evs[0]['meta']['duration'] == 6.0
        assert [e['id'] for e in lst(rule='no_hardhat')] == [ids[0]]
        assert [e['id'] for e in lst(camera=c2)] == [ids[2]]
        assert len(lst(cat=eff['no_hardhat']['cat'])) == 1
        assert ok(a.get(f'/api/worksafety/events/{ids[1]}'))['zone_name'] == 'Pres'
        ok(a.get('/api/worksafety/events/999999'), 404)
        assert ok(a.post('/api/worksafety/events/ack', json={'ids': ids[:2], 'note': 'Uyarıldı'}))['n'] == 2
        assert [e['id'] for e in lst(ack='open')] == [ids[2]]
        done = lst(ack='done')
        assert {e['id'] for e in done} == set(ids[:2]) and done[0]['ack_note'] == 'Uyarıldı' and done[0]['ack_name']
        assert ok(a.post('/api/worksafety/events/ack', json={'ids': [ids[0]], 'undo': True}))['n'] == 1
        assert len(lst(ack='open')) == 2

        # Isı haritası: hücreler gün ve çağrılar arasında toplanır
        heat = ok(a.get('/api/worksafety/heatmap', params={'kind': 'person', 'camera': c1,
                                                            'from': (today - timedelta(days=6)).isoformat(), 'to': today.isoformat()}))
        assert (heat['w'], heat['h']) == (W.GRID_W, W.GRID_H) and [c['camera_id'] for c in heat['cameras']] == [c1]
        grid = heat['cameras'][0]['grid']
        assert len(grid) == W.GRID_W * W.GRID_H and grid[0] == 9 and grid[33] == 18 and sum(grid) == 27 and heat['cameras'][0]['max'] == 18
        assert ok(a.get('/api/worksafety/heatmap', params={'kind': 'olmayan'}))['kind'] == 'person'   # bilinmeyen tür → kişi
        assert ok(a.get('/api/worksafety/heatmap', params={'kind': 'vehicle', 'camera': c1}))['cameras'] == []

        # Rapor: puan 0–100, kırılımlar tutarlı
        rep = ok(a.get('/api/worksafety/report', params={'from': (today - timedelta(days=6)).isoformat(), 'to': today.isoformat()}))
        assert rep['checks'] == 3 * 600 and rep['violations'] == (10 + 11 + 12) + 3 * 2 and 0 < rep['score'] < 100
        assert rep['events'] == 3 and rep['open_events'] == 2
        by_rule = {x['rule']: x for x in rep['by_rule']}
        assert by_rule['no_hardhat']['checks'] == 900 and by_rule['no_hardhat']['violations'] == 33 and by_rule['fall']['violations'] == 0
        by_cam = {x['camera_id']: x for x in rep['by_camera']}
        assert by_cam[c2]['score'] == 100 and by_cam[c1]['score'] < 100
        assert sum(x['checks'] for x in rep['by_day']) == rep['checks'] and sum(x['checks'] for x in rep['by_shift']) == rep['checks']
        assert [x for x in rep['by_zone'] if x['zone'] == 'Pres'][0]['events'] == 1
        assert sum(x['events'] for x in rep['levels']) == 3

        # İşleyici durumu: taze kayıt → çalışıyor; katalog model durumunu taşır
        with db.connect() as conn:
            W.set_status(conn, {'ts': time.time(), 'at': db.now(), 'backend': 'cpu', 'objects': True, 'pose': False, 'ppe': ['hardhat'],
                                'classes_extra': [], 'models': {}, 'cycle_s': 1.2, 'cams_total': 2, 'cams_active': 2, 'errors': []})
            conn.commit()
        st = ok(a.get('/api/worksafety/status'))
        assert st['running'] and st['reachable'] and st['enabled'] and st['events_today'] == 3 and st['open_events'] == 2
        rules = {r['key']: r for r in ok(a.get('/api/worksafety/catalog'))['rules']}
        assert rules['no_hardhat']['model_ok'] and not rules['no_vest']['model_ok'] and not rules['reba']['model_ok']
        assert rules['restricted_entry']['model_ok']

        # Canlı kaplama: taze dosya döner, bayat dosya dönmez
        W.LIVE_DIR.mkdir(parents=True, exist_ok=True)
        (W.LIVE_DIR / f'{c1}.ws.json').write_text(json.dumps({'t': time.time(), 'persons': [{'box': [0.1, 0.1, 0.1, 0.3], 'bad': False}], 'vehicles': [], 'viol': []}))
        (W.LIVE_DIR / f'{c2}.ws.json').write_text(json.dumps({'t': time.time() - 600, 'persons': [], 'vehicles': [], 'viol': []}))
        os.utime(W.LIVE_DIR / f'{c2}.ws.json', (time.time() - 600, time.time() - 600))
        live = ok(a.get('/api/worksafety/live', params={'ids': f'{c1},{c2},x'}))
        assert list(live) == [str(c1)] and live[str(c1)]['persons'][0]['box'] == [0.1, 0.1, 0.1, 0.3]
        assert ok(a.get('/api/worksafety/live')) == {}

        # Eski kayıt temizliği: süre dolan uyarılar silinir
        with db.connect() as conn:
            conn.execute("UPDATE ws_events SET at = '2020-01-01 00:00:00' WHERE id = ?", (ids[0],))
            W.purge(conn, 90)
            conn.commit()
        assert len(lst()) == 2

        # Yetki: Kamera Yetkilisi erişir, Sekreter erişemez; oturumsuz 401
        ok(a.post('/api/auth/logout'))
        ok(a.get('/api/worksafety/events'), 401)
        ok(a.post('/api/auth/login', json={'username': 'kam', 'password': 'sifre-1234'}))
        assert ok(a.get('/api/worksafety/events'))['total'] == 2
        ok(a.post('/api/auth/logout'))
        ok(a.post('/api/auth/login', json={'username': 'sek', 'password': 'sifre-1234'}))
        ok(a.get('/api/worksafety/events'), 403)
        ok(a.get('/api/worksafety/config'), 403)
    print('test_worksafety: tamam')


if __name__ == '__main__':
    main()
