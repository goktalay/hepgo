"""Belge Yönetim: Word/Sunum HTML içeriği kaydedilirken ve okunurken temizlenir (paylaşılan belgeyle XSS olmaz);
biçimlendirme korunur; eski (temizlenmemiş) kayıtlar ve sürümler de temiz döner.
Çalıştırma: .venv/bin/python -m tests.test_belge
"""
import json
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

EVIL = '<p onclick="x()">Merhaba <b>dünya</b></p><img src=x onerror=alert(1)><script>alert(2)</script>' \
       '<a href="javascript:alert(3)">t</a><a href="https://hepgo.com">ok</a>'


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def safe(html):
    low = html.lower()
    return not any(s in low for s in ('onerror', 'onclick', '<script', 'javascript:'))


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        w = ok(a.post('/api/belge', json={'kind': 'word', 'title': 'Not'}))
        ok(a.put(f"/api/belge/{w['id']}", json={'content': {'html': EVIL}}))
        html = ok(a.get(f"/api/belge/{w['id']}"))['content']['html']
        assert safe(html) and '<b>dünya</b>' in html and 'href="https://hepgo.com"' in html, html
        with db.connect() as conn:   # kayıt da temiz (yalnız okuma değil)
            assert safe(json.loads(conn.execute('SELECT content FROM office_docs WHERE id=?', (w['id'],)).fetchone()[0])['html'])

        s = ok(a.post('/api/belge', json={'kind': 'sunum', 'title': 'Sunum'}))
        ok(a.put(f"/api/belge/{s['id']}", json={'content': {'slides': [{'html': EVIL}, {'html': '<h1>İki</h1>'}]}}))
        slides = ok(a.get(f"/api/belge/{s['id']}"))['content']['slides']
        assert all(safe(x['html']) for x in slides) and slides[1]['html'] == '<h1>İki</h1>', slides

        # Düzeltmeden önce kaydedilmiş (temizlenmemiş) içerik ve sürüm de temiz döner
        with db.connect() as conn:
            conn.execute('UPDATE office_docs SET content=? WHERE id=?', (json.dumps({'html': EVIL}), w['id']))
            conn.execute('INSERT INTO office_versions(doc_id,content,saved_at,saved_by) VALUES(?,?,?,1)',
                         (w['id'], json.dumps({'html': EVIL}), db.now()))
            conn.commit()
        assert safe(ok(a.get(f"/api/belge/{w['id']}"))['content']['html'])
        vid = ok(a.get(f"/api/belge/{w['id']}/versions"))[0]['id']
        assert safe(ok(a.get(f"/api/belge/{w['id']}/versions/{vid}"))['content']['html'])

        # Excel içeriği (HTML değil) aynen korunur
        e = ok(a.post('/api/belge', json={'kind': 'excel', 'title': 'Tablo'}))
        ok(a.put(f"/api/belge/{e['id']}", json={'content': {'rows': 5, 'cols': 3, 'cells': {'A1': '<b>x</b>'}}}))
        assert ok(a.get(f"/api/belge/{e['id']}"))['content']['cells'] == {'A1': '<b>x</b>'}
    print('Belge testleri geçti.')


if __name__ == '__main__':
    main()
