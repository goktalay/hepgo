"""Dron paketi ayrımı: Dron Yönetimi yalnız dron paketinde (CAYMAZ_DRONE_PKG) ya da merkezin açıkça verdiği / önceden dron kaydı
olan kurulumda görünür; KOBİ / esnaf firmalarında (Saha Yönetimi olsa bile) gizli, modül yönetiminde de listelenmez.
Merkez kataloğu: 'drone' KOBİ seçmeli modülü değildir, Dron paketi sabit modül setiyle kurulur ve tenant .env'e CAYMAZ_DRONE_PKG=1 yazılır.
Çalıştırma: .venv/bin/python -m tests.test_drone_package"""
import os
import sys
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_MODULES='admin,users,field,companies,finance,documents')   # Saha Yönetimi'li KOBİ firması
os.environ.pop('CAYMAZ_DRONE_PKG', None)

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, config, modules_tier  # noqa: E402
from app.main import app  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'central', 'veilox_server'))
from veilox import modules_catalog as mc  # noqa: E402
from veilox.provision import _env_text  # noqa: E402


def main():
    with TestClient(app, base_url='https://testserver') as c:
        assert c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
        me = c.get('/api/auth/me').json()
        assert 'field' in me['modules'] and 'drone' not in me['modules'], me['modules']   # Saha var, Dron yok
        assert c.get('/api/drone/bridges').status_code == 403
        mods = [m['key'] for m in c.get('/api/system/modules').json()['modules']]
        assert 'drone' not in mods and 'field' in mods, mods
        # dron paketi firması: merkez modül listesinde 'drone' var (drone_modules) → görünür
        saved = config.MODULES
        config.MODULES = saved + ['drone']
        try:
            assert 'drone' in c.get('/api/auth/me').json()['modules']
            assert c.get('/api/drone/bridges').status_code == 200
        finally:
            config.MODULES = saved
        assert 'drone' not in c.get('/api/auth/me').json()['modules']
        # kısıtsız kurulum (CAYMAZ_MODULES yok): dron paketi bayrağıyla görünür, bayraksız ve dron kaydı yokken gizli
        config.MODULES = None
        try:
            assert 'drone' not in c.get('/api/auth/me').json()['modules']
            config.DRONE_PKG = True
            assert 'drone' in c.get('/api/auth/me').json()['modules']
            config.DRONE_PKG = False
            # paket ayrımından önce dron kaydı açılmış kurulum: görünür kalır (mevcut kullanım kesilmez)
            from app import db
            with db.connect() as conn:
                conn.execute("INSERT INTO drone_drones (code, name, created_at) VALUES ('D-0001', 'Eski dron', '2026-10-01T10:00:00')")
                conn.commit()
            auth._drone_legacy = None
            assert 'drone' in c.get('/api/auth/me').json()['modules']
        finally:
            config.MODULES, config.DRONE_PKG, auth._drone_legacy = saved, False, False
    # katmanlar
    assert modules_tier.tier('drone') == 'package' and 'drone' not in modules_tier.OPTIONAL
    assert mc.tier('drone') == 'package' and 'drone' not in mc.kobi_modules(['drone', 'field'])
    assert set(mc.drone_modules()) >= {'drone', 'field', 'companies', 'finance'} and 'production' not in mc.drone_modules()
    assert 'CAYMAZ_DRONE_PKG=1' in _env_text('a@b.c', 'x' * 12, 'Ad', 'Firma', 'a@b.c', mc.drone_modules(), drone_pkg=True)
    assert 'CAYMAZ_DRONE_PKG' not in _env_text('a@b.c', 'x' * 12, 'Ad', 'Firma', 'a@b.c', mc.kobi_modules(['field']))
    print('Dron paketi testleri geçti.')


if __name__ == '__main__':
    main()
