"""Yüz ile giriş (app/facelogin.py + app/routers/faceauth.py) uç testleri — SAHTE gömme ile (model çalıştırılmaz).

Kare yerine "FAKE:{json}" gönderilir: {"id": kişi, "yaw", "pitch"}; id → deterministik 128-d birim vektör (farklı id'ler
≈ ortogonal), "none" → yüz yok. Böylece eğitim yuvaları, tek kullanımlık meydan okuma, eşleşme/eşleşmeme, canlılık adımı,
yüz+PIN kipi, hız sınırı, politika kapalı, silme ve pasif kullanıcı denetlenir.

Çalıştırma: .venv/bin/python -m tests.test_face
"""
import json
import os
import tempfile

import numpy as np

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402

from app import facelogin  # noqa: E402
from app.main import app  # noqa: E402

PW = 'admin-sifre-1'


def _vec(pid):
    rng = np.random.default_rng(1000 + int(pid))
    return facelogin._norm(rng.normal(size=128))


def fake_embed(jpg):
    if not str(jpg).startswith('FAKE:'):
        return {'found': False}
    d = json.loads(jpg[5:])
    if d.get('id') == 'none':
        return {'found': False, 'w': 480, 'h': 360}
    noise = np.random.default_rng(int(d.get('n', 0))).normal(scale=0.02, size=128)
    return {'found': True, 'w': 480, 'h': 360, 'box': [100, 80, 200, 200], 'score': d.get('score', 0.9),
            'yaw': d.get('yaw', 0.0), 'pitch': d.get('pitch', 0.0), 'emb': facelogin._norm(_vec(d['id']) + noise)}


facelogin.EMBED = fake_embed
facelogin.engine_available = lambda: True

# ekran yuvası → ham (yaw, pitch): segment_of aynalıdır (ham yaw<0 → ekranda sağ)
POSE = {'center': (0, 0), 'right': (-0.5, 0), 'left': (0.5, 0), 'up': (0, -0.5), 'down': (0, 0.5),
        'up_right': (-0.4, -0.4), 'up_left': (0.4, -0.4), 'down_right': (-0.4, 0.4), 'down_left': (0.4, 0.4)}


def frame(pid, slot='center', **kw):
    y, p = POSE[slot]
    return 'FAKE:' + json.dumps({'id': pid, 'yaw': y, 'pitch': p, **kw})


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def enroll(c, pid, slots=('center', 'right', 'left', 'up', 'down', 'up_right'), append=False, mode=None):
    eid = ok(c.post('/api/auth/face/enroll/start', json={'password': PW, 'append': append}))['enroll_id']
    for s in slots:
        ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(pid, s)}))
    body = {'enroll_id': eid}
    if mode:
        body['mode'] = mode
    return ok(c.post('/api/auth/face/enroll/finish', json=body))


def main():
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW}))['device_token']
        st = ok(c.get('/api/auth/face/status'))
        assert st['policy_enabled'] and not st['enrolled'] and st['count'] == 0 and st['min_slots'] == 5, st

        # ---- eğitim
        assert c.post('/api/auth/face/enroll/start', json={'password': 'yanlis'}).status_code == 400
        eid = ok(c.post('/api/auth/face/enroll/start', json={'password': PW}))['enroll_id']
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame('none')}))
        assert not r['found'] and r['slots'] == []
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(1, 'right')}))
        assert r['found'] and r.get('need_center') and r['slots'] == [], r          # ilk kayıt merkezden
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(1, 'center')}))
        assert r['slot'] == 'center' and r['added'] and r['slots'] == ['center'] and not r['enough'], r
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(2, 'right')}))
        assert r.get('other_face') and r['slots'] == ['center'], r                   # başka kişinin yüzü eklenmez
        assert c.post('/api/auth/face/enroll/finish', json={'enroll_id': eid}).status_code == 400   # yetersiz yuva
        for s in ('right', 'left', 'up'):
            r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(1, s)}))
        assert r['slots'] == ['right', 'up', 'left', 'center'] or set(r['slots']) == {'center', 'right', 'left', 'up'}
        assert not r['enough']
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(1, 'down_right')}))
        assert r['enough'] and not r['complete'] and len(r['slots']) == 5, r
        # ara bölge (|poz| 0,14–0,20) yuva vermez
        r = ok(c.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': 'FAKE:' + json.dumps({'id': 1, 'yaw': -0.17, 'pitch': 0})}))
        assert r['slot'] is None and not r.get('added')
        fin = ok(c.post('/api/auth/face/enroll/finish', json={'enroll_id': eid}))
        assert fin['ok'] and fin['count'] == 5 and fin['enrolled'] and fin['mode'] == 'face', fin
        assert c.post('/api/auth/face/enroll/finish', json={'enroll_id': eid}).status_code == 410   # oturum tüketildi
        st = ok(c.get('/api/auth/face/status'))
        assert st['enrolled'] and st['count'] == 5 and st['model_ver'] == facelogin.MODEL_VER
        # ikinci tarama → eklenir
        fin = enroll(c, 1, slots=('center', 'right', 'left', 'up', 'down', 'down_left', 'down_right', 'up_left', 'up_right'), append=True)
        assert fin['count'] == 14, fin
        # saklanan veri şifreli (düz JSON değil) ve 128-d
        from app import db as _db
        with _db.connect() as conn:
            row = conn.execute('SELECT data, count FROM user_face').fetchone()
            assert row[1] == 14 and not row[0].startswith('{') and '"embeddings"' not in row[0]
            embs = facelogin.embeddings_of(conn, ok(c.get('/api/auth/me'))['id'])
            assert len(embs) == 14 and all(e.shape == (128,) for e in embs)

        # ---- cihaz listesi
        devs = ok(c.post('/api/auth/devices', json={'tokens': [dev]}))
        assert devs and devs[0]['has_face'] and devs[0]['face_mode'] == 'face', devs

    # ---- giriş: oturumsuz istemci
    with TestClient(app) as g:
        assert g.get('/api/auth/me').status_code == 401
        assert g.post('/api/auth/face/challenge', json={'token': 'yok'}).status_code == 401
        ch = ok(g.post('/api/auth/face/challenge', json={'token': dev}))
        assert ch['pose'] in ('left', 'right', 'up') and ch['mode'] == 'face' and ch['expires_in'] == 60, ch
        n = ch['challenge']
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame('none')}))
        assert not r['found'] and not r['matched'] and r['stage'] == 'match'
        # başka kişi: 10 eşleşmeyen kare → 401 ve meydan okuma kapanır
        for i in range(facelogin.MAX_MISS - 1):
            r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(2, 'center', n=i)}))
            assert r['found'] and not r['matched'] and 'sim' not in r
        rr = g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(2, 'center')})
        assert rr.status_code == 401 and 'eşleşmedi' in rr.json()['detail'], rr.text
        assert g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1)}).status_code == 410   # tek kullanımlık
        assert g.get('/api/auth/me').status_code == 401
        # doğru kişi: eşleme → canlılık (yanlış yön kabul edilmez) → oturum
        ch = ok(g.post('/api/auth/face/challenge', json={'token': dev}))
        n, pose = ch['challenge'], ch['pose']
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, 'right')}))   # merkezde değil → eşleme yok
        assert r['found'] and not r['matched'] and r['stage'] == 'match'
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, 'center')}))
        assert r['matched'] and r['stage'] == 'pose' and r['pose'] == pose and not r['done'], r
        wrong = {'left': 'right', 'right': 'left', 'up': 'down'}[pose]
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, wrong)}))
        assert not r['matched'] and r['stage'] == 'pose' and not r['done']
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, pose)}))
        assert r['matched'] and r['done'] and r.get('ok'), r
        me = ok(g.get('/api/auth/me'))
        assert me['username'] == 'admin@test'
        assert g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1)}).status_code == 410   # tüketildi
        with _db.connect() as conn:
            acts = [r[0] for r in conn.execute("SELECT action FROM audit_logs WHERE action LIKE 'Yüz%' OR action LIKE 'Sisteme yüz%' ORDER BY id")]
            assert 'Yüz tanıtma kaydı oluşturdu' in acts and 'Yüz ile giriş başarısız' in acts and 'Sisteme yüz ile giriş yaptı' in acts, acts
            fails = conn.execute("SELECT COUNT(*) FROM login_logs WHERE success = 0 AND username = 'admin@test'").fetchone()[0]
            assert fails == 1, fails
        ok(g.post('/api/auth/logout'))

    # ---- hız sınırı: dakikada 5 meydan okuma
    facelogin._rate.clear()
    with TestClient(app) as g:
        for _ in range(facelogin.FACE_RATE):
            ok(g.post('/api/auth/face/challenge', json={'token': dev}))
        assert g.post('/api/auth/face/challenge', json={'token': dev}).status_code == 429
    facelogin._rate.clear()

    # ---- yüz + PIN kipi
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        ok(c.put('/api/auth/pin', json={'password': PW, 'pin': '2580'}))
        assert c.put('/api/auth/face/mode', json={'mode': 'sacma'}).status_code == 400
        ok(c.put('/api/auth/face/mode', json={'mode': 'face_pin'}))
        assert ok(c.get('/api/auth/face/status'))['mode'] == 'face_pin'
    with TestClient(app) as g:
        ch = ok(g.post('/api/auth/face/challenge', json={'token': dev}))
        assert ch['mode'] == 'face_pin'
        n, pose = ch['challenge'], ch['pose']
        assert g.post('/api/auth/face/pin', json={'challenge': n, 'pin': '2580'}).status_code == 410   # önce yüz
        ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, 'center')}))
        r = ok(g.post('/api/auth/face/verify', json={'challenge': n, 'jpg': frame(1, pose)}))
        assert r['matched'] and r.get('need_pin') and not r['done'] and not r.get('ok'), r
        assert g.get('/api/auth/me').status_code == 401
        assert g.post('/api/auth/face/pin', json={'challenge': n, 'pin': '0000'}).status_code == 400
        ok(g.post('/api/auth/face/pin', json={'challenge': n, 'pin': '2580'}))
        assert ok(g.get('/api/auth/me'))['username'] == 'admin@test'
        ok(g.post('/api/auth/logout'))

    # ---- canlılık kapalı → merkez eşleşme yeter; politika kapalı → 403
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        ok(c.put('/api/auth/face/mode', json={'mode': 'face'}))
        pol = ok(c.get('/api/system/security'))['policy']
        ok(c.put('/api/system/security', json={**pol, 'face_liveness': False, 'face_threshold': 55}))
        assert ok(c.get('/api/system/security'))['policy']['face_threshold'] == 55
    with TestClient(app) as g:
        ch = ok(g.post('/api/auth/face/challenge', json={'token': dev}))
        assert ch['pose'] is None
        r = ok(g.post('/api/auth/face/verify', json={'challenge': ch['challenge'], 'jpg': frame(1, 'center')}))
        assert r['done'] and r.get('ok'), r
        ok(g.get('/api/auth/me'))
        ok(g.post('/api/auth/logout'))
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        ok(c.put('/api/system/security', json={**pol, 'face_enabled': False}))
        assert not ok(c.get('/api/auth/face/status'))['policy_enabled']
        assert c.post('/api/auth/face/enroll/start', json={'password': PW}).status_code == 403
        devs = ok(c.post('/api/auth/devices', json={'tokens': [dev]}))
        assert not devs[0]['has_face']
    with TestClient(app) as g:
        assert g.post('/api/auth/face/challenge', json={'token': dev}).status_code == 403
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        ok(c.put('/api/system/security', json={**pol, 'face_enabled': True}))

        # ---- pasif kullanıcı: tanıtılmış yüzle giriş reddedilir
        uid = ok(c.post('/api/users', json={'username': 'ayse', 'full_name': 'Ayşe', 'roles': ['Pilot'], 'password': 'pilot-gizli-77'}))['id']
    with TestClient(app) as u:
        dev2 = ok(u.post('/api/auth/login', json={'username': 'ayse', 'password': 'pilot-gizli-77'}))['device_token']
        eid = ok(u.post('/api/auth/face/enroll/start', json={'password': 'pilot-gizli-77'}))['enroll_id']
        for s in ('center', 'right', 'left', 'up', 'down'):
            ok(u.post('/api/auth/face/enroll/frame', json={'enroll_id': eid, 'jpg': frame(7, s)}))
        ok(u.post('/api/auth/face/enroll/finish', json={'enroll_id': eid}))
    with TestClient(app) as g:   # ayşe aktif: eşleşme başka kişiyle (admin yüzü) olmaz
        ch = ok(g.post('/api/auth/face/challenge', json={'token': dev2}))
        r = ok(g.post('/api/auth/face/verify', json={'challenge': ch['challenge'], 'jpg': frame(1, 'center')}))
        assert r['found'] and not r['matched']
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        ok(c.put(f'/api/users/{uid}', json={'username': 'ayse', 'full_name': 'Ayşe', 'roles': ['Pilot'], 'active': False}))
    with TestClient(app) as g:
        assert g.post('/api/auth/face/challenge', json={'token': dev2}).status_code == 401

        # ---- silme (şifre ile) → giriş yok
    with TestClient(app) as c:
        dev = ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': PW, 'device_token': dev}))['device_token']   # jeton yenilenir
        assert c.post('/api/auth/face/delete', json={'password': 'yanlis'}).status_code == 400
        assert not ok(c.post('/api/auth/face/delete', json={'password': PW}))['enrolled']
        assert not ok(c.get('/api/auth/face/status'))['enrolled']
    with TestClient(app) as g:
        assert g.post('/api/auth/face/challenge', json={'token': dev}).status_code == 401

    # ---- saf fonksiyonlar
    assert facelogin.segment_of(0, 0) == 'center' and facelogin.segment_of(-0.5, 0) == 'right' and facelogin.segment_of(0.5, 0) == 'left'
    assert facelogin.segment_of(0, -0.5) == 'up' and facelogin.segment_of(0, 0.5) == 'down' and facelogin.segment_of(-0.4, -0.4) == 'up_right'
    assert facelogin.segment_of(-0.17, 0) is None
    assert facelogin.pose_matches(-0.3, 0, 'right') and not facelogin.pose_matches(0.3, 0, 'right') and facelogin.pose_matches(0, -0.3, 'up')
    a = _vec(1)
    assert abs(facelogin.cosine(a, a) - 1) < 1e-6 and abs(facelogin.cosine(a, _vec(2))) < 0.3
    assert facelogin.threshold({'face_threshold': 45}) == 0.45 and facelogin.threshold({'face_threshold': 999}) == 0.80 and facelogin.threshold({}) == 0.45
    print('Yüz ile giriş testleri geçti.')


if __name__ == '__main__':
    main()
