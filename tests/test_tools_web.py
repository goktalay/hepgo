"""Araçlar › Master Tool web sürümleri: yetki (403), ortak katman (hesap, dosya alanı, Fernet), SQL Master (kütüphane, bağlan, ağaç,
sorgu akışı, salt okunur koruması, dışa aktarma, geçmiş), Convert Master (proje, png→jpg kuyruğu, önizleme, ZIP), Notepad Master
(yerel proje, kodlama, çakışma), SSH Master (depo/klasör/kısayol, Fernet, H:\\ yol koruması, localhost sshd'ye yanlış parola →
main.errAuth, WS ssh:start), FTP Masters (stdlib mini FTP sunucusu: bağlan, listele, klasör, yükle/indir kuyruğu, yeniden adlandır,
sil; SFTP yanlış parola → main.errAuth).
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_web
"""
import io
import json
import os
import socket
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path

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
                '/api/tools/mt/sshmaster/boot', '/api/tools/mt/ftpmaster/boot', '/api/tools/mt/account', '/api/tools/mt/sqlmaster/fs/list'):
        assert g.get(url).status_code == 403, url
        ok(a.get(url))
    assert g.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'filePath': 'x.db'}}).status_code == 403
    assert g.post('/api/tools/mt/sshmaster/invoke', json={'m': 'store:get'}).status_code == 403
    # SSH / FTP WebSocket: yetkisiz kullanıcıya hata olayı + kapanış
    for path in ('/ws/tools/ssh', '/ws/tools/ftp?id=x'):
        with g.websocket_connect(path) as ws:
            ev = json.loads(ws.receive_text())
            assert ev['ch'] == 'error' and 'Yetkisiz' in ev['d'], ev
    # Bilinmeyen uygulama / kanal
    assert a.get('/api/tools/mt/yok/boot').status_code == 404
    assert a.get('/api/tools/mt/sqlmaster/boot').status_code == 404       # boot/invoke yalnız SSH/FTP (IPC kalıbı)
    assert a.get('/api/tools/mt/bilinmeyen/fs/list').status_code == 404
    assert a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'yok:kanal'}).status_code == 400


def inv(c, app, m, a=None):
    """IPC kanalı çağrısı (bridge invoke karşılığı); {ok, v, store?} döner."""
    return ok(c.post(f'/api/tools/mt/{app}/invoke', json={'m': m, 'a': a}))


def ws_call(ws, m, a=None, cid=1, evs=None, timeout=20):
    """WS üzerinden çağrı; yanıt gelene kadar olayları (ev) toplar."""
    ws.send_text(json.dumps({'t': 'call', 'id': cid, 'm': m, 'a': a}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = json.loads(ws.receive_text())
        if msg.get('t') == 'ret' and msg.get('id') == cid:
            return msg
        if evs is not None:
            evs.append(msg)
    raise AssertionError('WS yanıtı gelmedi: ' + m)


def ws_wait_event(ws, ch, pred=lambda d: True, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = json.loads(ws.receive_text())
        if msg.get('t') == 'ev' and msg.get('ch') == ch and pred(msg['d']):
            return msg['d']
    raise AssertionError('WS olayı gelmedi: ' + ch)


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


# ---------- SSH Master (web): depo, Fernet, H:\ alanı, bağlantı testi, WS ----------
def test_sshmaster(a):
    st = ok(a.get('/api/tools/ssh/status'))
    assert st['backend'] == 'paramiko' and st['available']
    boot = ok(a.get('/api/tools/mt/sshmaster/boot?lang=tr'))
    assert boot['lang'] == 'tr' and boot['user']['email'] == 'admin@test'
    assert [s['command'] for s in boot['store']['shortcuts']] == ['df -h', 'free -m', 'top']   # masaüstü varsayılanları
    assert boot['store']['shortcuts'][0]['name'] == 'Disk kullanımı'                           # i18n.js'ten (tr)
    # Klasör + bağlantı kaydı: şifre Fernet ile saklanır, arayüze yalnız hasPassword gider
    fid = inv(a, 'sshmaster', 'folder:save', {'name': 'Sunucular'})['v']
    r = inv(a, 'sshmaster', 'conn:save', {'name': 'Yerel', 'host': '127.0.0.1', 'port': 22, 'username': 'hepgo-test-yok', 'authType': 'password',
                                          'password': 'yanlis-parola', 'folderId': fid, 'rememberLastDir': True, 'color': '#3b82f6', 'theme': 'dracula'})
    cid = r['v']
    c = next(x for x in r['store']['connections'] if x['id'] == cid)
    assert c['hasPassword'] is True and 'password' not in c and c['folderId'] == fid and c['theme'] == 'dracula'
    raw = tools_mt.read_store(1, 'sshmaster')['connections'][0]
    assert raw['password'].startswith('enc:') and tools_mt.decrypt(raw['password']) == 'yanlis-parola'
    # Klasörü kendi içine taşıma reddedilir; silinince içerik üst klasöre çıkar
    sub = inv(a, 'sshmaster', 'folder:save', {'name': 'Alt', 'parentId': fid})['v']
    assert inv(a, 'sshmaster', 'folder:move', {'id': fid, 'parentId': sub})['v'] is False
    r = inv(a, 'sshmaster', 'folder:delete', fid)
    assert r['store']['connections'][0]['folderId'] is None and r['store']['folders'][0]['parentId'] is None
    # Kısayol sırası
    ids = [s['id'] for s in boot['store']['shortcuts']]
    r = inv(a, 'sshmaster', 'shortcut:reorder', ids[::-1])
    assert [s['command'] for s in r['store']['shortcuts']] == ['top', 'free -m', 'df -h']
    # Bilgisayarım = H:\ kişisel alanı; sürücü dışı ve '..' reddedilir
    sp = inv(a, 'sshmaster', 'local:special')['v']
    assert sp['home'] == 'H:\\' and sp['documents'] == 'H:\\Belgeler'
    inv(a, 'sshmaster', 'local:mkdir', 'H:\\Belgeler\\deneme')
    assert any(e['name'] == 'deneme' and e['isDir'] for e in inv(a, 'sshmaster', 'local:list', 'H:\\Belgeler')['v'])
    assert inv(a, 'sshmaster', 'local:list', 'C:\\')['ok'] is False
    assert inv(a, 'sshmaster', 'local:list', 'H:\\..\\..\\etc')['ok'] is False
    assert os.path.isdir(os.path.join(tmp, 'tools', 'files', '1', 'Belgeler', 'deneme'))
    up = ok(a.post('/api/tools/mt/sshmaster/files/upload', data={'dir': 'H:\\.ssh'}, files={'file': ('id_test', b'anahtar-degil', 'application/octet-stream')}))
    assert up['path'] == 'H:\\.ssh\\id_test' and oct(os.stat(os.path.join(tmp, 'tools', 'files', '1', '.ssh', 'id_test')).st_mode)[-3:] == '600'
    assert ok(a.get('/api/tools/mt/sshmaster/files/download', params={'path': 'H:\\.ssh\\id_test'})) == b'anahtar-degil'
    # Bağlantı testi: localhost sshd'ye yanlış parola → main.errAuth; eksik alan → errHostUser; kapalı port → errRefused
    r = inv(a, 'sshmaster', 'conn:test', {'id': cid, 'host': '127.0.0.1', 'port': 22, 'username': 'hepgo-test-yok', 'authType': 'password', 'password': ''})
    assert r['v'] == {'ok': False, 'message': {'$t': 'main.errAuth'}}, r
    assert inv(a, 'sshmaster', 'conn:test', {'host': '', 'username': ''})['v']['message'] == {'$t': 'main.errHostUser'}
    assert inv(a, 'sshmaster', 'conn:test', {'host': '127.0.0.1', 'port': 1, 'username': 'u', 'password': 'p'})['v']['message'] == {'$t': 'main.errRefused'}
    # Geçersiz anahtar dosyası → errKeyFile
    r = inv(a, 'sshmaster', 'conn:test', {'host': '127.0.0.1', 'port': 22, 'username': 'u', 'authType': 'key', 'keyPath': 'H:\\.ssh\\yok'})
    assert r['v']['message'] == {'$t': 'main.errKeyFile'}
    # WS: ssh:start yanlış parola → ok:false + errAuth; bilinmeyen bağlantı → errConnNotFound; oturum yokken sftp → errNoSession
    with a.websocket_connect('/ws/tools/ssh') as ws:
        r = ws_call(ws, 'ssh:start', {'pane': 'p1', 'connId': cid, 'cols': 100, 'rows': 30})
        assert r['ok'] and r['v'] == {'ok': False, 'message': {'$t': 'main.errAuth'}}, r
        r = ws_call(ws, 'ssh:start', {'pane': 'p1', 'connId': 'yok'}, cid=2)
        assert r['v']['message'] == {'$t': 'main.errConnNotFound'}
        r = ws_call(ws, 'sftp:list', {'pane': 'p1', 'dir': '/'}, cid=3)
        assert r['ok'] is False and r['e'] == {'$t': 'main.errNoSession'}
    inv(a, 'sshmaster', 'conn:delete', cid)
    assert inv(a, 'sshmaster', 'store:get')['v']['connections'] == []


# ---------- Mini FTP sunucusu (stdlib): pasif kip, tek kullanıcı ----------
class MiniFtp(threading.Thread):
    def __init__(self, root, user='test', pw='gizli'):
        super().__init__(daemon=True)
        self.root, self.user, self.pw = Path(root), user, pw
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(c,), daemon=True).start()

    def real(self, cwd, arg):
        import posixpath
        p = posixpath.normpath(posixpath.join(cwd, arg or '')) if arg else cwd
        return p, self.root / p.lstrip('/')

    def handle(self, c):
        f = c.makefile('rb')
        send = lambda s: c.sendall((s + '\r\n').encode('utf-8'))   # noqa: E731
        send('220 MiniFTP hazır')
        cwd, pasv, rnfr, authed = '/', None, None, False

        def data():
            d, _ = pasv.accept()
            pasv.close()
            return d
        while True:
            line = f.readline()
            if not line:
                break
            cmd, _, arg = line.decode('utf-8').rstrip('\r\n').partition(' ')
            cmd = cmd.upper()
            if cmd == 'USER':
                send('331 Parola')
            elif cmd == 'PASS':
                authed = arg == self.pw
                send('230 Giriş yapıldı' if authed else '530 Login incorrect')
            elif cmd == 'QUIT':
                send('221 Güle güle')
                break
            elif not authed:
                send('530 Please login')
            elif cmd == 'SYST':
                send('215 UNIX Type: L8 MiniFTP')
            elif cmd == 'FEAT':
                c.sendall(b'211-Features\r\n MLST type*;size*;modify*;\r\n UTF8\r\n211 End\r\n')
            elif cmd in ('OPTS', 'NOOP'):
                send('200 Tamam')
            elif cmd == 'TYPE':
                send('200 Tür ' + arg)
            elif cmd == 'PWD':
                send(f'257 "{cwd}"')
            elif cmd == 'CWD':
                p, r = self.real(cwd, arg)
                if r.is_dir():
                    cwd = p
                    send('250 Tamam')
                else:
                    send('550 No such directory')
            elif cmd == 'PASV':
                pasv = socket.socket()
                pasv.bind(('127.0.0.1', 0))
                pasv.listen(1)
                port = pasv.getsockname()[1]
                send(f'227 Entering Passive Mode (127,0,0,1,{port // 256},{port % 256})')
            elif cmd in ('MLSD', 'LIST'):
                p, r = self.real(cwd, arg.lstrip('-la ').strip())
                if not r.is_dir():
                    send('550 No such directory')
                    continue
                send('150 Liste')
                d = data()
                for e in sorted(r.iterdir()):
                    st = e.stat()
                    mod = time.strftime('%Y%m%d%H%M%S', time.gmtime(st.st_mtime))
                    if cmd == 'MLSD':
                        d.sendall(f"type={'dir' if e.is_dir() else 'file'};size={0 if e.is_dir() else st.st_size};modify={mod}; {e.name}\r\n".encode())
                    else:
                        d.sendall(f"{'d' if e.is_dir() else '-'}rw-r--r-- 1 ftp ftp {st.st_size} {time.strftime('%b %d %H:%M', time.gmtime(st.st_mtime))} {e.name}\r\n".encode())
                d.close()
                send('226 Bitti')
            elif cmd == 'RETR':
                p, r = self.real(cwd, arg)
                if not r.is_file():
                    send('550 No such file')
                    continue
                send('150 Gönderiliyor')
                d = data()
                d.sendall(r.read_bytes())
                d.close()
                send('226 Bitti')
            elif cmd == 'STOR':
                p, r = self.real(cwd, arg)
                send('150 Alınıyor')
                d = data()
                buf = b''
                while True:
                    chunk = d.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                d.close()
                r.write_bytes(buf)
                send('226 Bitti')
            elif cmd == 'SIZE':
                p, r = self.real(cwd, arg)
                send(f'213 {r.stat().st_size}' if r.is_file() else '550 Not a file')
            elif cmd == 'MKD':
                p, r = self.real(cwd, arg)
                r.mkdir()
                send(f'257 "{p}" oluşturuldu')
            elif cmd == 'RMD':
                p, r = self.real(cwd, arg)
                r.rmdir()
                send('250 Silindi')
            elif cmd == 'DELE':
                p, r = self.real(cwd, arg)
                if r.is_file():
                    r.unlink()
                    send('250 Silindi')
                else:
                    send('550 No such file')
            elif cmd == 'RNFR':
                rnfr = self.real(cwd, arg)[1]
                send('350 Hazır')
            elif cmd == 'RNTO':
                rnfr.rename(self.real(cwd, arg)[1])
                send('250 Yeniden adlandırıldı')
            else:
                send('502 Komut yok')
        c.close()


# ---------- FTP Masters (web): mini FTP sunucusuyla uçtan uca ----------
def test_ftpmaster(a):
    caps = ok(a.get('/api/tools/ftp/caps'))
    assert caps['ftp'] and caps['ftps'] and caps['sftp'] is True
    # LIST ayrıştırma (birim): UNIX ve DOS biçimleri
    e = tools_ftp.parse_list_line('drwxr-xr-x    2 ftp      ftp          4096 Jan 01 12:00 klasor adi')
    assert e['name'] == 'klasor adi' and e['isDir'] is True and e['size'] == 4096 and e['raw'] == 'Jan 01 12:00'
    assert tools_ftp.parse_list_line('-rw-r--r--    1 ftp      ftp           123 Mar 05 2024 dosya.txt')['isDir'] is False
    assert tools_ftp.parse_list_line('lrwxrwxrwx    1 ftp      ftp             5 Mar 05 2024 link -> hedef')['name'] == 'link'
    d = tools_ftp.parse_list_line('01-15-24  09:30AM       <DIR>          Belgeler')
    assert d['isDir'] and d['name'] == 'Belgeler'
    assert tools_ftp.parse_list_line('01-15-24  09:30AM             1234 a.txt')['size'] == 1234
    # Mini FTP sunucusu
    root = Path(tmp) / 'ftproot'
    (root / 'alt').mkdir(parents=True)
    (root / 'okubeni.txt').write_text('merhaba ftp', encoding='utf-8')
    (root / 'alt' / 'ic.txt').write_text('iç dosya', encoding='utf-8')
    srv = MiniFtp(root)
    srv.start()
    # Site kaydı (protokol/port doğrulaması) + bağlantı testi: yanlış parola → errAuth, kapalı port → errRefused, doğru → ok
    r = inv(a, 'ftpmaster', 'conn:save', {'name': 'Mini', 'host': '127.0.0.1', 'port': srv.port, 'protocol': 'ftp', 'username': 'test', 'password': 'gizli',
                                          'rememberLastDir': True, 'remoteDir': '/alt', 'retryAttempts': 0, 'siteOptions': 'custom', 'maxConcurrent': 2})
    sid = r['v']
    c = next(x for x in r['store']['connections'] if x['id'] == sid)
    assert c['hasPassword'] and c['protocol'] == 'ftp' and c['port'] == srv.port and c['retryAttempts'] == 0
    bad = inv(a, 'ftpmaster', 'conn:test', {'host': '127.0.0.1', 'port': srv.port, 'protocol': 'ftp', 'username': 'test', 'password': 'yanlis'})['v']
    assert bad == {'ok': False, 'message': {'$t': 'main.errAuth'}}, bad
    assert inv(a, 'ftpmaster', 'conn:test', {'host': '127.0.0.1', 'port': 1, 'protocol': 'ftp', 'username': 'u', 'password': 'p'})['v']['message'] == {'$t': 'main.errRefused'}
    assert inv(a, 'ftpmaster', 'conn:test', {'host': '-bad host', 'username': 'u'})['v']['ok'] is False
    good = inv(a, 'ftpmaster', 'conn:test', {'id': sid, 'host': '127.0.0.1', 'port': srv.port, 'protocol': 'ftp', 'username': 'test', 'password': '', 'remoteDir': '/alt'})['v']
    assert good['ok'] and good['home'] == '/' and good['remoteDirOk'] is True and 'MiniFTP' in good['info'], good
    # SFTP: localhost sshd'ye yanlış parola → errAuth (paramiko)
    r = inv(a, 'ftpmaster', 'conn:test', {'host': '127.0.0.1', 'port': 22, 'protocol': 'sftp', 'username': 'hepgo-test-yok', 'password': 'yanlis'})['v']
    assert r == {'ok': False, 'message': {'$t': 'main.errAuth'}}, r
    # Yerel (H:\) tarafta yüklenecek dosya
    ok(a.post('/api/tools/mt/ftpmaster/files/upload', data={'dir': 'H:\\Belgeler'}, files={'file': ('yukle.txt', b'x' * 70000, 'text/plain')}))
    with a.websocket_connect(f'/ws/tools/ftp?id={sid}') as ws:
        r = ws_call(ws, 'site:open')
        assert r['ok'] and r['v']['ok'] and r['v']['home'] == '/' and r['v']['startRemote'] == '/alt' and r['v']['startLocal'] == 'H:\\', r
        items = ws_call(ws, 'site:list', {'dir': '/', 'refresh': True}, cid=2)['v']
        assert {i['name']: i['isDir'] for i in items} == {'alt': True, 'okubeni.txt': False} and next(i for i in items if i['name'] == 'okubeni.txt')['size'] == 11
        ws_call(ws, 'site:mkdir', '/yeni', cid=3)
        assert (root / 'yeni').is_dir()
        assert any(i['name'] == 'yeni' for i in ws_call(ws, 'site:list', {'dir': '/', 'refresh': False}, cid=4)['v'])   # mkdir önbelleği düşürdü
        ws_call(ws, 'site:rename', {'from': '/yeni', 'to': '/yeniad'}, cid=5)
        assert (root / 'yeniad').is_dir() and not (root / 'yeni').exists()
        # Yükleme kuyruğu: transfer:update (added/changed) + transfer:rootDone
        ws_call(ws, 'site:upload', {'paths': ['H:\\Belgeler\\yukle.txt'], 'remoteDir': '/yeniad'}, cid=6)
        done = ws_wait_event(ws, 'transfer:rootDone', lambda d: d['kind'] == 'upload')
        assert done['status'] == 'done' and done['name'] == 'yukle.txt' and done['dstDir'] == '/yeniad', done
        assert (root / 'yeniad' / 'yukle.txt').read_bytes() == b'x' * 70000
        # İndirme: klasör (alt) → H:\İndirilenler; ağaç tarandıktan sonra tamamlanır
        ws_call(ws, 'site:download', {'items': [{'path': '/alt', 'name': 'alt', 'isDir': True, 'size': 0, 'mtime': 0},
                                               {'path': '/okubeni.txt', 'name': 'okubeni.txt', 'isDir': False, 'size': 11, 'mtime': 0}], 'localDir': 'H:\\İndirilenler'}, cid=7)
        got = {}
        while len(got) < 2:
            d = ws_wait_event(ws, 'transfer:rootDone', lambda d: d['kind'] == 'download')
            got[d['name']] = d['status']
        assert got == {'alt': 'done', 'okubeni.txt': 'done'}, got
        files_dir = Path(tmp) / 'tools' / 'files' / '1' / 'İndirilenler'
        assert (files_dir / 'okubeni.txt').read_text(encoding='utf-8') == 'merhaba ftp' and (files_dir / 'alt' / 'ic.txt').read_text(encoding='utf-8') == 'iç dosya'
        # Aynı adlı hedef: varsayılan "üzerine yaz" → tekrar indirme de başarılı
        ws_call(ws, 'site:download', {'items': [{'path': '/okubeni.txt', 'name': 'okubeni.txt', 'isDir': False, 'size': 11, 'mtime': 0}], 'localDir': 'H:\\İndirilenler'}, cid=8)
        assert ws_wait_event(ws, 'transfer:rootDone', lambda d: d['name'] == 'okubeni.txt')['status'] == 'done'
        # Bitmiş aktarımları temizle → kaldırılan kök kimlikleri
        removed = ws_call(ws, 'transfer:clear', None, cid=9)['v']
        assert len(removed) == 4, removed
        # Sil (dosya + klasör) ve son klasörü hatırla
        ws_call(ws, 'site:delete', [{'path': '/yeniad', 'isDir': True, 'isLink': False}], cid=10)
        assert not (root / 'yeniad').exists()
        ws.send_text(json.dumps({'t': 'send', 'm': 'site:lastDir', 'a': {'remote': '/alt', 'local': 'H:\\Belgeler'}}))
        r = ws_call(ws, 'site:stat', '/okubeni.txt', cid=11)
        assert r['v'] == {'isDir': False, 'size': 11}
        assert ws_call(ws, 'site:stat', '/alt', cid=12)['v']['isDir'] is True
        r = ws_call(ws, 'site:list', {'dir': '/yok', 'refresh': True}, cid=13)
        assert r['ok'] is False and r['e']['$t'] == 'main.err550', r
    st = tools_mt.read_store(1, 'ftpmaster')['connections'][0]
    assert st['lastRemoteDir'] == '/alt' and st['lastLocalDir'] == 'H:\\Belgeler'
    # Geçersiz site kimliğiyle açılış
    with a.websocket_connect('/ws/tools/ftp?id=yok') as ws:
        assert ws_call(ws, 'site:open')['v'] == {'ok': False, 'message': {'$t': 'main.errConnNotFound'}}
    srv.srv.close()


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
        test_sshmaster(a)
        test_ftpmaster(a)
    print('Araçlar › Master Tool web testleri geçti.')


if __name__ == '__main__':
    main()
