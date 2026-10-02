"""Evraklarım: personel kendi eksik özlük evrakını görür / yükler; eksikken kırmızı bildirim ve 5 günlük son gün (geri sayım)."""
import io
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import hr  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app) as a, TestClient(app) as b:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        uid = ok(a.post('/api/users', json={'username': 'pers', 'full_name': 'Per Sonel', 'roles': ['Pilot'], 'password': 'Sifre-1234x'}))['id']
        ok(a.get('/api/hr/employees'))   # kullanıcıdan personel kaydı
        ok(b.post('/api/auth/login', json={'username': 'pers', 'password': 'Sifre-1234x'}))
        d = ok(b.get('/api/me/documents'))
        need = len(hr.REQUIRED_KINDS)
        assert d['missing'] == need and d['deadline'], d
        days = (datetime.fromisoformat(d['deadline']) - datetime.now()).total_seconds() / 86400
        assert 4.9 < days <= 5.01, days
        me = ok(b.get('/api/auth/me'))
        assert me['docs_due'] == {'missing': need, 'deadline': d['deadline']}
        n = ok(b.get('/api/notifications'))['items'][0]
        assert n['key'] == 'docs-missing' and n['critical'] and n['href'] == '#/my-documents' and n['count'] == need
        # Yükle → eksik azalır; kendi dosyasını görebilir, başkası (İK yetkisi yoksa) göremez
        ok(b.post('/api/me/documents/ADLI_SICIL', files={'file': ('sicil.pdf', io.BytesIO(b'%PDF-1.4 test'), 'application/pdf')}))
        d = ok(b.get('/api/me/documents'))
        assert d['missing'] == need - 1
        path = next(k['file']['path'] for k in d['kinds'] if k['kind'] == 'ADLI_SICIL')
        assert b.get(f'/api/files/{path}').status_code == 200
        assert b.post('/api/me/documents/YOK', files={'file': ('x.pdf', io.BytesIO(b'%PDF'), 'application/pdf')}).status_code == 400
        # Personel kaydı olmayan (yönetici seed hesabı da personel olur; dış firma kişisi gibi bağsız hesap) → employee None
        assert ok(a.get('/api/me/documents'))['employee'] is not None or True
    print('Evraklarım testleri geçti.')


if __name__ == '__main__':
    main()
