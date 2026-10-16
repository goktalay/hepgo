"""Sistem geneli arama (/api/search): 3 harften kısa sorgu boş döner; büyük/küçük ve Türkçe harf farkı yok sayılır
("korkmaz" → "Korkmaz Elektronik", "ŞİŞE" → "şişe"); evrak OCR metni FTS ile bulunur ve alıntı gelir; sonuç türe göre
gruplanır ve her öğe detay adresi taşır; yetkisi olmayan kullanıcı o grubu görmez; yönetici/master her şeyi görür.

Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_search
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, document_ocr  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p='sifre-1234'):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def groups(c, q):
    return {g['type']: g['items'] for g in ok(c.get(f'/api/search?q={q}'))['groups']}


def main():
    with TestClient(app) as a:
        login(a, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,   # noqa: E731
                                                            'password': 'sifre-1234'}))['id']
        mk('montaj', ['Montaj Personeli'])
        mk('ik', ['İnsan Kaynakları'])
        with db.connect() as c:
            now = db.now()
            c.execute("INSERT INTO companies (name, phone, email, created_at) VALUES ('Korkmaz Elektronik', '0532', 'info@korkmaz.com', ?)", (now,))
            c.execute("INSERT INTO companies (name, is_supplier, created_at) VALUES ('Şişecam Tedarik', 1, ?)", (now,))
            c.execute('''INSERT INTO products (code, name, serial, schema, queue_prefix, type, active, created_at)
                         VALUES ('KRK-1', 'Korkmaz kablo', 'KRK', 'custom', 'KRK', 'YEDEK_PARCA', 1, ?)''', (now,))
            c.execute("INSERT INTO employees (first_name, last_name, status, created_at) VALUES ('Ayşe', 'Korkmazoğlu', 'AKTIF', ?)", (now,))
            c.execute('''INSERT INTO documents (title, kind, file, file_name, size, uploaded_at, uploaded_by, visibility, ocr_text, ocr_status)
                         VALUES ('Fatura 2026-10', 'EVRAK', 'documents/f.pdf', 'f.pdf', 10, ?, 1, 'ALL',
                                 'Sayın KORKMAZ ELEKTRONİK yetkilisi, siparişiniz hazırdır.', 'TAMAM')''', (now,))
            did = c.execute("SELECT id FROM documents WHERE title = 'Fatura 2026-10'").fetchone()[0]
            document_ocr.index(c, did)
        # kısa sorgu
        assert ok(a.get('/api/search?q=ko'))['groups'] == []
        # yönetici: küçük harf ve karışık harfle cari, ürün, personel, evrak (OCR) gelir
        for q in ('korkmaz', 'KORKMAZ', 'korkmAZ'):
            g = groups(a, q)
            assert [x['title'] for x in g['company']] == ['Korkmaz Elektronik'], g
            assert g['company'][0]['href'].startswith('#/companies/')
            assert g['material'][0]['title'] == 'Korkmaz kablo' and g['material'][0]['href'].startswith('#/mrp/materials/')
            assert g['employee'][0]['title'] == 'Ayşe Korkmazoğlu' and g['employee'][0]['href'].startswith('#/hr/')
            d = g['document'][0]
            assert d['title'] == 'Fatura 2026-10' and d['href'] == f'#/documents/{did}' and d['snippet']['match'].lower() == 'korkmaz', d
        # Türkçe harf: ŞİŞE → Şişecam (tedarikçi grubu, satın alma adresi)
        g = groups(a, 'ŞİŞE')
        assert g['supplier'][0]['title'] == 'Şişecam Tedarik' and g['supplier'][0]['href'].startswith('#/purchasing/suppliers/')
        assert 'company' not in g
        # kullanıcı grubu yalnız yöneticide
        assert any(x['title'] == 'Montaj' for x in groups(a, 'montaj').get('user', []))
    with TestClient(app) as montaj, TestClient(app) as ik:
        login(montaj, 'montaj'); login(ik, 'ik')
        # montaj personeli: cari/personel/evrak yetkisi yok → bu gruplar gelmez (ürün modülü varsa malzeme gelebilir)
        g = groups(montaj, 'korkmaz')
        assert 'company' not in g and 'employee' not in g and 'document' not in g and 'user' not in g, list(g)
        # İK: personel gelir, cari gelmez
        g = groups(ik, 'korkmaz')
        assert g.get('employee') and 'company' not in g and 'user' not in g, list(g)
    print('Arama testleri geçti.')


if __name__ == '__main__':
    main()
