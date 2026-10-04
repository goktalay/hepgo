"""Entegrasyon sağlık denetimi: ayarlı entegrasyon düzenli denenir; ulaşılamıyorsa "Bağlı" görünmez (online=false,
Çevrimdışı), sistem yöneticisine bildirim düşer; düzelince bildirim kalkar. Aralık entegrasyon başına (en az 30 sn).
Elle "Bağlantıyı Test Et" de durumu günceller; ayarı silinen entegrasyonun durumu unutulur. X sunucusu taklit edilir.
Çevrimdışıyken X ile bağlanma da kapanmaz (anahtar var) — yalnız durum gösterilir.
Çalıştırma: .venv/bin/python -m tests.test_integration_health
"""
import os
import tempfile
import time

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_X_CLIENT_ID='',
                  CAYMAZ_X_CLIENT_SECRET='', CAYMAZ_AI_API_KEY='')

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, integration_health as ih, social  # noqa: E402
from app.main import app  # noqa: E402

state = {'up': False}


class Resp:
    def __init__(self, code):
        self.status_code, self.headers = code, {}


def fake_post(url, **kw):
    if not state['up']:
        raise httpx.ConnectError('ağ yok')
    return Resp(200)


social.httpx.post = fake_post


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def grp(c, key):
    return next(g for g in ok(c.get('/api/system/integrations'))['groups'] if g['key'] == key)


def notif(c):
    return next((n for n in ok(c.get('/api/notifications'))['items'] if n['key'] == 'integrations-offline'), None)


def main():
    with TestClient(app) as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        g = grp(c, 'x')
        assert g['checked'] and not g['configured'] and not g['online'] and g['health'] is None and g['interval'] == 300
        assert not grp(c, 'maps')['checked']
        with db.connect() as conn:
            assert ih.check_due(conn) == []                      # ayarlı entegrasyon yok → deneme yok
        ok(c.put('/api/system/integrations/x', json={'values': {'X_CLIENT_ID': 'i', 'X_CLIENT_SECRET': 's'}}))
        g = grp(c, 'x')
        assert g['configured'] and not g['online'] and g['health'] is None   # henüz denenmedi: "Denetleniyor"

        with db.connect() as conn:                               # ağ yok → çevrimdışı
            assert ih.check_due(conn) == ['x']
            assert ih.check_due(conn) == []                      # aralık dolmadan tekrar denenmez
        g = grp(c, 'x')
        assert g['configured'] and not g['online'] and g['health']['ok'] is False and 'ulaşılamadı' in g['health']['message']
        n = notif(c)
        assert n and n['names'] == ['X (Twitter)'] and n['href'] == '#/sysconfig/integrations', n
        since = g['health']['since']

        # Aralık: en az 30 sn; denetlenmeyen entegrasyona aralık verilemez
        assert c.put('/api/system/integrations/x/interval', json={'seconds': 10}).status_code == 400
        assert c.put('/api/system/integrations/maps/interval', json={'seconds': 60}).status_code == 404
        ok(c.put('/api/system/integrations/x/interval', json={'seconds': 30}))
        assert grp(c, 'x')['interval'] == 30
        state['up'] = True
        with db.connect() as conn:
            assert ih.check_due(conn) == []                      # 30 sn dolmadı
            assert ih.check_due(conn, now=time.time() + 31) == ['x']
        g = grp(c, 'x')
        assert g['online'] and g['health']['ok'] and g['health']['since'] >= since
        assert notif(c) is None                                  # düzelince bildirim kalkar

        # Elle deneme de durumu günceller
        state['up'] = False
        assert ok(c.post('/api/system/integrations/x/test', json={}))['ok'] is False
        assert grp(c, 'x')['online'] is False and notif(c)

        # Ayar silinince durum unutulur, bildirim kalmaz
        ok(c.put('/api/system/integrations/x', json={'values': {}, 'clear': ['X_CLIENT_ID', 'X_CLIENT_SECRET']}))
        with db.connect() as conn:
            ih.check_due(conn)
        g = grp(c, 'x')
        assert not g['configured'] and g['health'] is None and notif(c) is None
    print('Entegrasyon sağlık denetimi testleri geçti.')


if __name__ == '__main__':
    main()
