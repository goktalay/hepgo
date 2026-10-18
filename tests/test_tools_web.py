"""Araçlar › Master Tool web sürümleri: yetki (403), SQL Master (SQLite yükle/sorgu/sayfa), Convert Master (png→jpg, json→csv,
csv→xlsx→json), Notepad Master (kaydet/aç/listele/sil), FTP Master (yol doğrulama + bağlanamama), SSH Master (yetkisiz WS, geçersiz adres).
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_web
"""
import io
import json
import os
import sqlite3
import tempfile
import zipfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import tools_common, tools_convert, tools_ftp  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.headers.get('content-type', '').startswith('application/json') else r.content


def png_bytes():
    out = io.BytesIO()
    Image.new('RGBA', (64, 40), (200, 30, 30, 128)).save(out, format='PNG')
    return out.getvalue()


def test_permissions(a, g):
    # Güvenlik rolü Araçlar modülüne yetkili değil → 403; yönetici → 200
    for url in ('/api/tools/ssh/status', '/api/tools/ftp/caps', '/api/tools/sql/drivers', '/api/tools/notepad/files', '/api/tools/convert/caps'):
        assert g.get(url).status_code == 403, url
        ok(a.get(url))
    assert g.post('/api/tools/sql/connect', json={'driver': 'sqlite', 'path': 'x.db'}).status_code == 403
    # SSH WebSocket: yetkisiz kullanıcıya kırmızı mesaj + kapanış
    with g.websocket_connect('/ws/tools/ssh') as ws:
        assert 'Yetkisiz' in ws.receive_text()
    # SSH WebSocket: yetkili ama geçersiz sunucu adresi → hata metni
    with a.websocket_connect('/ws/tools/ssh') as ws:
        ws.send_text(json.dumps({'t': 'connect', 'host': '-oProxyCommand=x', 'port': 22, 'username': 'u'}))
        assert 'Geçersiz sunucu adresi' in ws.receive_text()
    with a.websocket_connect('/ws/tools/ssh') as ws:
        ws.send_text(json.dumps({'t': 'connect', 'host': 'localhost', 'port': 70000, 'username': 'u'}))
        assert 'Geçersiz port' in ws.receive_text()


def test_sql(a):
    drv = ok(a.get('/api/tools/sql/drivers'))
    assert drv['sqlite'] is True and 'mysql' in drv and 'postgres' in drv
    # SQLite dosyası hazırla ve yükle
    p = os.path.join(tmp, 'ornek.db')
    c = sqlite3.connect(p)
    c.execute('CREATE TABLE kisiler (id INTEGER PRIMARY KEY, ad TEXT, yas INTEGER)')
    c.executemany('INSERT INTO kisiler (ad, yas) VALUES (?, ?)', [(f'Kişi {i}', 20 + i) for i in range(250)])
    c.commit(); c.close()
    with open(p, 'rb') as f:
        up = ok(a.post('/api/tools/sql/upload', files={'file': ('ornek.db', f, 'application/octet-stream')}))
    assert up['name'] == 'ornek.db'
    assert any(x['name'] == 'ornek.db' for x in ok(a.get('/api/tools/sql/files')))
    # Geçersiz dosya reddedilir
    assert a.post('/api/tools/sql/upload', files={'file': ('bozuk.db', b'bu bir sqlite degil', 'application/octet-stream')}).status_code == 400
    # Bağlan + tablolar + sayfalı sorgu
    s = ok(a.post('/api/tools/sql/connect', json={'driver': 'sqlite', 'path': 'ornek.db'}))
    sid = s['sid']
    tbl = ok(a.get('/api/tools/sql/tables', params={'sid': sid}))
    assert tbl[0]['name'] == 'kisiler' and tbl[0]['columns'] == ['id', 'ad', 'yas']
    r = ok(a.post('/api/tools/sql/query', params={'sid': sid}, json={'sql': 'SELECT * FROM kisiler ORDER BY id', 'page': 1, 'page_size': 100}))
    assert r['columns'] == ['id', 'ad', 'yas'] and r['total'] == 250 and len(r['rows']) == 100 and r['rows'][0] == [1, 'Kişi 0', 20]
    r3 = ok(a.post('/api/tools/sql/query', params={'sid': sid}, json={'sql': 'SELECT * FROM kisiler ORDER BY id', 'page': 3, 'page_size': 100}))
    assert len(r3['rows']) == 50 and r3['rows'][0][0] == 201
    w = ok(a.post('/api/tools/sql/query', params={'sid': sid}, json={'sql': "UPDATE kisiler SET yas = 99 WHERE id <= 5"}))
    assert w['rowcount'] == 5
    assert a.post('/api/tools/sql/query', params={'sid': sid}, json={'sql': 'SELECT * FROM yok'}).status_code == 400
    # DATA_DIR dışı yol reddedilir; uygulama DB'si salt okunur
    assert a.post('/api/tools/sql/connect', json={'driver': 'sqlite', 'path': '/etc/passwd'}).status_code == 400
    ro = ok(a.post('/api/tools/sql/connect', json={'driver': 'sqlite', 'path': 'caymaz.db'}))
    assert ro['readonly'] is True
    assert a.post('/api/tools/sql/query', params={'sid': ro['sid']}, json={'sql': 'CREATE TABLE zarar (x)'}).status_code == 400
    # Kurulu olmayan sürücü
    if not drv['mysql']:
        assert 'kurulu değil' in a.post('/api/tools/sql/connect', json={'driver': 'mysql', 'host': 'localhost', 'username': 'u'}).json()['detail']
    ok(a.post('/api/tools/sql/disconnect', params={'sid': sid}))
    assert a.get('/api/tools/sql/tables', params={'sid': sid}).status_code == 404
    ok(a.delete('/api/tools/sql/files/ornek.db'))


def test_convert(a):
    caps = ok(a.get('/api/tools/convert/caps'))
    assert 'jpg' in caps['image'] and caps['image_to_pdf'] is True
    # png → jpg (saydamlık beyaza basılır) + yeniden boyutlandır
    r = ok(a.post('/api/tools/convert/image', files={'file': ('resim.png', png_bytes(), 'image/png')}, data={'fmt': 'jpg', 'width': '32'}))
    assert r['name'] == 'resim.jpg' and r['width'] == 32 and r['height'] == 20
    body = ok(a.get(r['url']))
    im = Image.open(io.BytesIO(body))
    assert im.format == 'JPEG' and im.size == (32, 20)
    assert tools_common.tmp_path(r['token']) is not None
    assert a.get('/api/tools/convert/download/yok__x.jpg').status_code == 404
    # görsel → PDF
    r = ok(a.post('/api/tools/convert/pdf', files=[('files', ('a.png', png_bytes(), 'image/png')), ('files', ('b.png', png_bytes(), 'image/png'))]))
    assert r['name'] == 'a.pdf' and ok(a.get(r['url']))[:5] == b'%PDF-' and r['pages'] == 2
    if not caps['pdf_to_image']:
        assert 'pdftoppm' in a.post('/api/tools/convert/pdf', files=[('files', ('x.pdf', b'%PDF-1.4 bos', 'application/pdf'))]).json()['detail']
    # json → csv
    data = json.dumps([{'ad': 'Ali', 'yas': 30}, {'ad': 'Veli; Jr', 'yas': 25, 'sehir': 'Ankara'}], ensure_ascii=False)
    r = ok(a.post('/api/tools/convert/data', data={'content': data, 'src': 'json', 'dst': 'csv', 'out_delimiter': ';'}))
    csv_txt = ok(a.get(r['url'])).decode('utf-8')
    assert csv_txt.splitlines() == ['ad;yas;sehir', 'Ali;30;', '"Veli; Jr";25;Ankara'] and r['rows'] == 3
    # csv → xlsx (stdlib yazıcı) → json (stdlib okuyucu)
    r = ok(a.post('/api/tools/convert/data', data={'content': csv_txt, 'src': 'csv', 'dst': 'xlsx'}))
    xl = ok(a.get(r['url']))
    with zipfile.ZipFile(io.BytesIO(xl)) as z:
        assert 'xl/worksheets/sheet1.xml' in z.namelist()
    r = ok(a.post('/api/tools/convert/data', files={'file': ('veri.xlsx', xl, 'application/octet-stream')}, data={'src': 'xlsx', 'dst': 'json'}))
    back = json.loads(ok(a.get(r['url'])).decode('utf-8'))
    assert back == [{'ad': 'Ali', 'yas': '30', 'sehir': ''}, {'ad': 'Veli; Jr', 'yas': '25', 'sehir': 'Ankara'}], back
    # sayı hücreleri: json → xlsx → json (sayılar sayı kalır)
    r = ok(a.post('/api/tools/convert/data', data={'content': '[{"a": 1, "b": 2.5}]', 'src': 'json', 'dst': 'xlsx'}))
    rows = tools_convert._rows_from_xlsx(ok(a.get(r['url'])))
    assert rows == [['a', 'b'], [1, 2.5]], rows
    # metin kodlama + satır sonu
    r = ok(a.post('/api/tools/convert/text', data={'content': 'şğü\nikinci', 'enc_from': 'utf-8', 'enc_to': 'cp1254', 'eol': 'crlf', 'name': 'm.txt'}))
    assert ok(a.get(r['url'])) == 'şğü\r\nikinci'.encode('cp1254')
    assert a.post('/api/tools/convert/text', data={'content': 'şğü', 'enc_to': 'ascii'}).status_code == 400
    # 1 saatten eski geçici dosya silinir
    p = tools_common.tmp_path(r['token'])
    os.utime(p, (p.stat().st_atime - 7200, p.stat().st_mtime - 7200))
    tools_common.sweep_tmp(force=True)
    assert not p.exists()


def test_notepad(a, g):
    assert ok(a.get('/api/tools/notepad/files')) == []
    r = ok(a.put('/api/tools/notepad/file', json={'name': '../../gizli.txt', 'content': 'merhaba\ndünya'}))
    assert r['name'] == 'gizli.txt'   # dizin kaçışı temizlenir
    assert os.path.isfile(os.path.join(tmp, 'tools', 'notes', '1', 'gizli.txt'))
    lst = ok(a.get('/api/tools/notepad/files'))
    assert [x['name'] for x in lst] == ['gizli.txt']
    assert ok(a.get('/api/tools/notepad/file', params={'name': 'gizli.txt'}))['content'] == 'merhaba\ndünya'
    assert a.get('/api/tools/notepad/file', params={'name': 'yok.txt'}).status_code == 404
    assert g.get('/api/tools/notepad/file', params={'name': 'gizli.txt'}).status_code == 403   # başka kullanıcı/yetkisiz göremez
    assert a.put('/api/tools/notepad/file', json={'name': 'buyuk.txt', 'content': 'x' * (2 * 1024 * 1024 + 1)}).status_code == 413
    ok(a.delete('/api/tools/notepad/file', params={'name': 'gizli.txt'}))
    assert ok(a.get('/api/tools/notepad/files')) == []


def test_ftp(a):
    caps = ok(a.get('/api/tools/ftp/caps'))
    assert caps['ftp'] and caps['ftps'] and 'sftp' in caps
    # Yol doğrulama (birim): kök dışına çıkış yok, ters bölü düzeltilir
    assert tools_ftp._norm('../../etc') == '/etc'
    assert tools_ftp._norm('a\\b/../c') == '/a/b/c'
    assert tools_ftp._norm('') == '/'
    e = tools_ftp._parse_list_line('drwxr-xr-x    2 ftp      ftp          4096 Jan 01 12:00 klasor adi')
    assert e == {'name': 'klasor adi', 'dir': True, 'size': 4096, 'mtime': 'Jan 01 12:00'}
    assert tools_ftp._parse_list_line('-rw-r--r--    1 ftp      ftp           123 Mar 05 2024 dosya.txt')['dir'] is False
    # Yerel FTP sunucusu yok: kapalı porta bağlanma 502 ile açıklanır; geçersiz adres 400
    assert a.post('/api/tools/ftp/connect', json={'host': '127.0.0.1', 'port': 1, 'username': 'u', 'password': 'p'}).status_code == 502
    assert a.post('/api/tools/ftp/connect', json={'host': '-bad host', 'username': 'u'}).status_code == 400
    if not caps['sftp']:
        assert 'paramiko' in a.post('/api/tools/ftp/connect', json={'host': '127.0.0.1', 'protocol': 'sftp', 'username': 'u'}).json()['detail']
    assert a.get('/api/tools/ftp/list', params={'sid': 'yok', 'path': '/'}).status_code == 404


def main():
    with TestClient(app) as a, TestClient(app) as g:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'guvenlik@test', 'full_name': 'Güvenlik', 'roles': ['Güvenlik'], 'password': 'Gizli-Parola-77'}))
        ok(g.post('/api/auth/login', json={'username': 'guvenlik@test', 'password': 'Gizli-Parola-77'}))
        assert 'tools' not in ok(g.get('/api/auth/me'))['modules']
        test_permissions(a, g)
        test_sql(a)
        test_convert(a)
        test_notepad(a, g)
        test_ftp(a)
    print('Araçlar › Master Tool web testleri geçti.')


if __name__ == '__main__':
    main()
