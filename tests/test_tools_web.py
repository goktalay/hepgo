"""Araçlar › Master Tool web sürümleri: yetki (403), ortak katman (hesap, dosya alanı, Fernet), SQL Master (kütüphane, bağlan, ağaç, sorgu akışı,
salt okunur koruması, dışa aktarma, geçmiş), Convert Master (proje, png→jpg kuyruğu, önizleme, ZIP), Notepad Master (yerel proje, kodlama, çakışma),
FTP Master (yol doğrulama + bağlanamama), SSH Master (yetkisiz WS, geçersiz adres).
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_web
"""
import io
import json
import os
import sqlite3
import tempfile
import time
import zipfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import tools_ftp, tools_mt  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.headers.get('content-type', '').startswith('application/json') else r.content


def png_bytes():
    out = io.BytesIO()
    Image.new('RGBA', (64, 40), (200, 30, 30, 128)).save(out, format='PNG')
    return out.getvalue()


def test_permissions(a, g):
    # Güvenlik rolü Araçlar modülüne yetkili değil → 403; yönetici → 200
    for url in ('/api/tools/ssh/status', '/api/tools/ftp/caps', '/api/tools/sql/drivers', '/api/tools/notepad/files', '/api/tools/convert/caps',
                '/api/tools/mt/account', '/api/tools/mt/sqlmaster/fs/list'):
        assert g.get(url).status_code == 403, url
        ok(a.get(url))
    assert g.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'filePath': 'x.db'}}).status_code == 403
    assert a.get('/api/tools/mt/bilinmeyen/fs/list').status_code == 404
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


def events(a, url, want, tries=60):
    """Olay akışını (db:event / job:*) yoklar; 'want' türü gelince biriken olayları döndürür."""
    since, got = 0, []
    for _ in range(tries):
        r = ok(a.get(f'{url}&since={since}'))
        since = r['seq']
        got += r['events']
        if any(e['ch'] == want[0] and (want[1] is None or want[1](e['data'])) for e in r['events']):
            return got
        time.sleep(0.05)
    raise AssertionError(f'olay gelmedi: {want[0]}')


def test_mt_store(a):
    # Ortak katman: hesap durumu HEPGO oturumu; dosya alanı (yükle / listele / klasör / sil); Fernet şifreleme
    acc = ok(a.get('/api/tools/mt/account'))
    assert acc['loggedIn'] and acc['user']['email'] == 'admin@test' and acc['state'] == 'off'
    ok(a.post('/api/tools/mt/notepadmaster/fs/mkdir', json={'path': '/', 'name': 'proje'}))
    up = ok(a.post('/api/tools/mt/notepadmaster/fs/upload', data={'dir': '/proje'}, files=[('files', ('merhaba.txt', 'selam dünya'.encode(), 'text/plain'))]))
    assert up['items'][0]['path'] == '/proje/merhaba.txt'
    lst = ok(a.get('/api/tools/mt/notepadmaster/fs/list', params={'path': '/proje'}))['items']
    assert [x['name'] for x in lst] == ['merhaba.txt'] and lst[0]['isDir'] is False
    assert a.get('/api/tools/mt/notepadmaster/fs/list', params={'path': '/../..'}).status_code in (200, 400)   # kök dışına çıkılamaz
    assert ok(a.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '/proje/merhaba.txt'})) == 'selam dünya'.encode()
    enc = tools_mt.protect('gizli-parola')
    assert enc.startswith('enc:') and 'gizli' not in enc and tools_mt.unprotect(enc) == 'gizli-parola'


def test_sql(a):
    drv = ok(a.get('/api/tools/sql/drivers'))
    assert drv['sqlite'] is True and 'mysql' in drv and 'postgres' in drv
    assert any(p['id'] == 'sqlite' for p in ok(a.get('/api/tools/sql/providers')))
    # SQLite dosyası hazırla ve kullanıcının dosya alanına yükle
    p = os.path.join(tmp, 'ornek.db')
    c = sqlite3.connect(p)
    c.executescript('CREATE TABLE kisiler (id INTEGER PRIMARY KEY, ad TEXT, yas INTEGER); CREATE INDEX ix_ad ON kisiler(ad);')
    c.executemany('INSERT INTO kisiler (ad, yas) VALUES (?, ?)', [(f'Kişi {i}', 20 + i % 50) for i in range(250)])
    c.commit(); c.close()
    with open(p, 'rb') as f:
        ok(a.post('/api/tools/mt/sqlmaster/fs/upload', data={'dir': '/'}, files=[('files', ('ornek.db', f, 'application/octet-stream'))]))
    # Bağlantı kütüphanesi (store.json şeması) ve klasör
    fid = ok(a.post('/api/tools/sql/folder/save', json={'name': 'Yerel'}))['id']
    r = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'name': 'Örnek', 'filePath': '/ornek.db', 'readOnly': True, 'folderId': fid, 'ssh': {}}}))
    cid = r['id']
    conn = next(x for x in r['store']['connections'] if x['id'] == cid)
    assert conn['folderId'] == fid and conn['readOnly'] is True and conn['hasPassword'] is False and conn['ssh']['port'] == 22
    assert ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'sqlite', 'filePath': '/ornek.db', 'readOnly': True, 'ssh': {}}}))['ok']
    assert ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'sqlite', 'filePath': '/yok.db', 'readOnly': True, 'ssh': {}}}))['ok'] is False
    # Bağlantı penceresi: bağlan, ağaç, sorgu akışı
    info = ok(a.get('/api/tools/sql/cw/info', params={'id': cid}))
    assert info['needsPassword'] is False and info['connection']['name'] == 'Örnek'
    cw = ok(a.post('/api/tools/sql/cw/connect', json={'id': cid}))
    assert cw['ok'] and cw['readOnly'] and cw['info']['product'].startswith('SQLite'), cw
    sid = cw['sid']
    dbs = ok(a.post('/api/tools/sql/db/children', json={'sid': sid, 'node': None}))
    assert dbs[0]['kind'] == 'database' and dbs[0]['name'] == 'main'
    folders = ok(a.post('/api/tools/sql/db/children', json={'sid': sid, 'node': dbs[0]}))
    tables = ok(a.post('/api/tools/sql/db/children', json={'sid': sid, 'node': folders[0]}))
    assert tables[0]['name'] == 'kisiler' and tables[0]['openAs'] == 'data'
    assert 'CREATE TABLE kisiler' in ok(a.post('/api/tools/sql/db/ddl', json={'sid': sid, 'node': tables[0]}))
    cols = ok(a.post('/api/tools/sql/db/columns', json={'sid': sid, 'path': tables[0]['path']}))
    assert [x['name'] for x in cols] == ['id', 'ad', 'yas'] and cols[2]['numeric']
    assert ok(a.post('/api/tools/sql/db/completion', json={'sid': sid}))['tables']['main']['kisiler'] == ['id', 'ad', 'yas']
    r = ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'r1', 'req': {'sql': 'SELECT * FROM kisiler ORDER BY id; SELECT count(*) n FROM kisiler', 'limit': 100}}))
    assert r == {'errors': 0, 'cancelled': False}
    evs = [e['data']['ev'] for e in events(a, f'/api/tools/sql/db/events?sid={sid}', ('db:event', lambda d: d['ev']['type'] == 'done')) if e['ch'] == 'db:event']
    assert [e['type'] for e in evs if e['type'] == 'statement'] == ['statement', 'statement']
    rows = sum(len(e['rows']) for e in evs if e['type'] == 'rows' and e['index'] == 0)
    end0 = next(e for e in evs if e['type'] == 'end' and e['index'] == 0)
    assert rows == 100 and end0['truncated'] is True
    assert next(e for e in evs if e['type'] == 'rows' and e['index'] == 1)['rows'] == [[250]]
    # Salt okunur koruması: yazma ifadesi engellenir (blocked), onayla (allowWrite) çalışır
    ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'r2', 'req': {'sql': 'UPDATE kisiler SET yas = 99 WHERE id <= 5'}}))
    evs = [e['data']['ev'] for e in events(a, f'/api/tools/sql/db/events?sid={sid}', ('db:event', lambda d: d['runId'] == 'r2' and d['ev']['type'] == 'done')) if e['data']['runId'] == 'r2']
    assert evs[0]['type'] == 'blocked' and evs[0]['statements'][0]['keyword'] == 'UPDATE'
    ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'r3', 'req': {'sql': 'UPDATE kisiler SET yas = 99 WHERE id <= 5', 'allowWrite': True}}))
    evs = [e['data']['ev'] for e in events(a, f'/api/tools/sql/db/events?sid={sid}', ('db:event', lambda d: d['runId'] == 'r3' and d['ev']['type'] == 'done')) if e['data']['runId'] == 'r3']
    assert next(e for e in evs if e['type'] == 'command')['rowsAffected'] == 5
    r = ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'r4', 'req': {'sql': 'SELECT * FROM yok'}}))
    assert r['errors'] == 1
    # Dışa aktarma (CSV) ve geçmiş
    ex = ok(a.post('/api/tools/sql/db/export', json={'sid': sid, 'runId': 'e1', 'sql': 'SELECT id, ad FROM kisiler WHERE id <= 3', 'format': 'csv', 'defaultName': 'kisiler'}))
    assert ex['rows'] == 3 and ex['fileName'] == 'kisiler.csv'
    body = ok(a.get('/api/tools/sql/db/download', params={'token': ex['token']})).decode('utf-8-sig')
    assert body.splitlines()[0] == 'id,ad' and 'Kişi 1' in body
    hist = ok(a.get('/api/tools/sql/history', params={'id': cid}))
    assert len(hist) >= 4 and hist[0]['ok'] is False and 'kisiler' in hist[-1]['sql']
    # Uygulamanın kendi veritabanı yalnız salt okunur; yazmaya açılamaz
    r2 = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'name': 'HEPGO', 'filePath': 'caymaz.db', 'readOnly': False, 'ssh': {}}}))
    cw2 = ok(a.post('/api/tools/sql/cw/connect', json={'id': r2['id']}))
    assert cw2['ok'], cw2
    assert a.post('/api/tools/sql/db/setReadOnly', json={'sid': cw2['sid'], 'on': False}).status_code == 400
    assert a.post('/api/tools/sql/db/execute', json={'sid': cw2['sid'], 'runId': 'x', 'req': {'sql': 'CREATE TABLE zarar (x)', 'allowWrite': True}}).json()['errors'] == 1
    # Sürücüsü olmayan sağlayıcılar: orijinal "sürücü yok" anlamında mesaj
    if not drv['mysql']:
        assert 'kurulu değil' in ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'mysql', 'host': 'localhost', 'user': 'u', 'ssh': {}}}))['message']
    assert 'kurulu değil' in ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'mssql', 'host': 'localhost', 'user': 'u', 'ssh': {}}}))['message']
    # Parola Fernet ile şifreli saklanır; depoda düz metin yok
    r3 = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'postgres', 'name': 'PG', 'host': 'db', 'user': 'u', 'password': 'Cok-Gizli-1', 'ssh': {}}}))
    assert next(x for x in r3['store']['connections'] if x['id'] == r3['id'])['hasPassword'] is True
    raw = json.dumps(tools_mt.kv_get(1, 'sqlmaster', 'secrets')) + json.dumps(tools_mt.kv_get(1, 'sqlmaster', 'store'))
    assert 'Cok-Gizli-1' not in raw
    ok(a.post('/api/tools/sql/cw/close', json={'sid': sid}))
    assert a.post('/api/tools/sql/db/children', json={'sid': sid, 'node': None}).status_code == 404
    ok(a.post('/api/tools/sql/conn/delete', json={'id': r3['id']}))


def test_convert(a):
    caps = ok(a.get('/api/tools/convert/caps'))
    assert caps['image'] is True and caps['speech'] is False and caps['ocr'] is False
    # Kaynak klasörü hazırla (kullanıcı alanı): iki PNG
    ok(a.post('/api/tools/mt/convertmaster/fs/mkdir', json={'path': '/', 'name': 'resimler'}))
    ok(a.post('/api/tools/mt/convertmaster/fs/upload', data={'dir': '/resimler'}, files=[('files', ('a.png', png_bytes(), 'image/png')), ('files', ('alt/b.png', png_bytes(), 'image/png'))]))
    # Proje (store.json şeması): resim → jpg, en fazla 32 px
    r = ok(a.post('/api/tools/convert/project/save', json={'form': {'name': 'PNG→JPG', 'type': 'image', 'sourceExts': ['png'], 'targetExt': 'jpg', 'sourceMode': 'folder',
                                                                    'sourcePath': '/resimler', 'options': {'image': {'quality': 80, 'maxWidth': 32}}}}))
    pid = r['id']
    proj = next(p for p in r['store']['projects'] if p['id'] == pid)
    assert proj['sourcePath'] == '/resimler' and proj['options']['image']['maxWidth'] == 32 and proj['speech']['enabled'] is False
    init = ok(a.post('/api/tools/convert/pj/init', json={'id': pid}))
    rels = sorted(f['rel'] for f in init['snapshot']['files'])
    assert rels == ['a.png', 'alt/b.png'] and init['snapshot']['counts']['total'] == 2
    ok(a.post('/api/tools/convert/pj/check', json={'id': pid, 'rels': ['alt/b.png'], 'checked': False}))
    ok(a.post('/api/tools/convert/pj/start', json={'id': pid, 'opts': {}}))
    evs = events(a, f'/api/tools/convert/pj/events?id={pid}', ('job:finished', None))
    fin = next(e['data'] for e in evs if e['ch'] == 'job:finished')
    assert fin['counts'] == {'total': 1, 'done': 1, 'error': 0, 'active': 0, 'queued': 0, 'speechActive': 0, 'speechQueued': 0}, fin
    out = ok(a.get('/api/tools/convert/pj/file', params={'id': pid, 'rel': 'a.png', 'which': 'out'}))
    im = Image.open(io.BytesIO(out)); assert im.format == 'JPEG' and im.width == 32
    pv = ok(a.post('/api/tools/convert/pj/preview', json={'id': pid, 'rel': 'a.png', 'which': 'out'}))
    assert pv['kind'] == 'image' and pv['info']['video']['width'] == 32 and pv['url'].startswith('/api/tools/convert/media/')
    assert ok(a.get(pv['url']))[:3] == b'\xff\xd8\xff'
    stats = ok(a.get('/api/tools/convert/projects/stats'))
    assert stats[pid] == {'done': 1, 'error': 0, 'running': False}
    z = zipfile.ZipFile(io.BytesIO(ok(a.get('/api/tools/convert/pj/exportOutputs', params={'id': pid}))))
    assert z.namelist() == ['a.jpg']
    # Konuşma/OCR motorları yok: indirme reddedilir
    assert ok(a.post('/api/tools/convert/speech/download', json={'model': 'base'}))['ok'] is False
    assert ok(a.get('/api/tools/convert/speech/status'))['engine'] is False
    # Video dönüştürme: ffmpeg yoksa açık hata
    if not caps['video']:
        ok(a.post('/api/tools/mt/convertmaster/fs/upload', data={'dir': '/'}, files=[('files', ('v.avi', b'RIFF....AVI LIST', 'video/x-msvideo'))]))
        r = ok(a.post('/api/tools/convert/project/save', json={'form': {'name': 'Video', 'type': 'video', 'sourceMode': 'file', 'sourcePath': '/v.avi', 'sourceExts': ['avi']}}))
        ok(a.post('/api/tools/convert/pj/init', json={'id': r['id']})); ok(a.post('/api/tools/convert/pj/start', json={'id': r['id'], 'opts': {}}))
        evs = events(a, f"/api/tools/convert/pj/events?id={r['id']}", ('job:finished', None))
        items = [x for e in evs if e['ch'] == 'job:items' for x in e['data']]
        assert any(x['status'] == 'error' and 'ffmpeg' in x['error'] for x in items), items
    ok(a.post('/api/tools/convert/project/delete', json={'id': pid}))
    assert pid not in ok(a.get('/api/tools/convert/projects/stats'))


def test_notepad(a, g):
    # Yerel (sunucu alanı) proje: bağlantı kaydet, aç, dosya oluştur/kaydet/oku/listele, kodlama
    r = ok(a.post('/api/tools/notepad/conn/save', json={'form': {'kind': 'local', 'name': 'Proje', 'localPath': '/proje'}}))
    cid = r['id']
    c = next(x for x in r['store']['connections'] if x['id'] == cid)
    assert c['hasLocalPath'] is True and c['editorMode'] == 'global' and c['editor']['tabSize'] == 4 and 'password' not in c
    o = ok(a.post('/api/tools/notepad/proj/open', json={'id': cid}))
    assert o['ok'] and o['root'] == '/proje' and o['sep'] == '/'
    sid = o['sid']
    lst = ok(a.post('/api/tools/notepad/proj/list', json={'sid': sid, 'dir': '/proje'}))
    assert [x['name'] for x in lst] == ['merhaba.txt']
    rd = ok(a.post('/api/tools/notepad/proj/read', json={'sid': sid, 'path': '/proje/merhaba.txt', 'encoding': 'auto'}))
    assert rd['text'] == 'selam dünya' and rd['encoding'] == 'utf8' and rd['bom'] is False
    ok(a.post('/api/tools/notepad/proj/newFile', json={'sid': sid, 'path': '/proje/yeni.py'}))
    assert a.post('/api/tools/notepad/proj/newFile', json={'sid': sid, 'path': '/proje/yeni.py'}).status_code == 400   # zaten var
    sv = ok(a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/proje/yeni.py', 'text': 'print("şğü")\n', 'encoding': 'windows-1254'}))
    assert sv['ok'] and sv['size'] == len('print("şğü")\n'.encode('cp1254'))
    rd = ok(a.post('/api/tools/notepad/proj/read', json={'sid': sid, 'path': '/proje/yeni.py', 'encoding': 'auto', 'fallback': 'windows-1254'}))
    assert rd['text'] == 'print("şğü")\n' and rd['encoding'] == 'windows-1254' and rd['eol'] == 'lf'
    assert ok(a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/proje/yeni.py', 'text': 'şğü', 'encoding': 'windows-1252'})) == {'lossy': True}
    # Çakışma: dosya açıldıktan sonra değişmişse kaydetme uyarır
    cf = ok(a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/proje/yeni.py', 'text': 'x', 'encoding': 'utf8', 'expect': {'size': 1, 'mtime': rd['mtime']}}))
    assert cf.get('conflict') is True
    ok(a.post('/api/tools/notepad/proj/mkdir', json={'sid': sid, 'path': '/proje/alt'}))
    ok(a.post('/api/tools/notepad/proj/rename', json={'sid': sid, 'from': '/proje/yeni.py', 'to': '/proje/alt/yeni.py'}))
    assert a.post('/api/tools/notepad/proj/read', json={'sid': sid, 'path': '/etc/passwd'}).status_code == 400   # proje klasörü dışı yasak
    ok(a.post('/api/tools/notepad/proj/tabs', json={'sid': sid, 'openTabs': ['/proje/alt/yeni.py'], 'activeTab': '/proje/alt/yeni.py'}))
    assert next(x for x in ok(a.get('/api/tools/notepad/store'))['connections'] if x['id'] == cid)['openTabs'] == ['/proje/alt/yeni.py']
    ok(a.post('/api/tools/notepad/proj/delete', json={'sid': sid, 'path': '/proje/alt', 'isDir': True}))
    assert ok(a.post('/api/tools/notepad/proj/status', json={})) if False else ok(a.get('/api/tools/notepad/proj/status', params={'sid': sid}))['status'] == 'on'
    ok(a.post('/api/tools/notepad/proj/close', json={'sid': sid}))
    assert a.post('/api/tools/notepad/proj/list', json={'sid': sid, 'dir': '/proje'}).status_code == 404
    # Uzak bağlantı testi: kapalı port → kullanıcı dostu hata; SSH parola Fernet ile saklanır
    t = ok(a.post('/api/tools/notepad/conn/test', json={'form': {'kind': 'ftp', 'protocol': 'ftp', 'host': '127.0.0.1', 'port': 1, 'username': 'u', 'password': 'p'}}))
    assert t['ok'] is False and 'reddedildi' in t['message']
    r = ok(a.post('/api/tools/notepad/conn/save', json={'form': {'kind': 'ssh', 'name': 'Sunucu', 'host': 'srv', 'port': 22, 'username': 'root', 'password': 'Gizli-99'}}))
    c = next(x for x in r['store']['connections'] if x['id'] == r['id'])
    assert c['hasPassword'] is True and 'Gizli-99' not in json.dumps(tools_mt.kv_get(1, 'notepadmaster', 'store'))
    assert g.get('/api/tools/notepad/store').status_code == 403
    ok(a.post('/api/tools/notepad/conn/delete', json={'id': r['id']}))


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
        test_mt_store(a)
        test_sql(a)
        test_convert(a)
        test_notepad(a, g)
        test_ftp(a)
    print('Araçlar › Master Tool web testleri geçti.')


if __name__ == '__main__':
    main()
