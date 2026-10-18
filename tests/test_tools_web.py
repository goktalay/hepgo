"""Araçlar › Master Tool web sürümleri: yetki (403), SQL Master (SQLite yükle/sorgu/sayfa), Convert Master (png→jpg, json→csv,
csv→xlsx→json), Notepad Master (kaydet/aç/listele/sil), SSH Master (depo/klasör/kısayol, Fernet, H:\\ yol koruması, localhost sshd'ye
yanlış parola → main.errAuth, WS ssh:start), FTP Masters (stdlib mini FTP sunucusu: bağlan, listele, klasör, yükle/indir kuyruğu,
yeniden adlandır, sil; SFTP yanlış parola → main.errAuth).
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
from app.routers import tools_common, tools_convert, tools_ftp, tools_mt  # noqa: E402


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
                '/api/tools/mt/sshmaster/boot', '/api/tools/mt/ftpmaster/boot'):
        assert g.get(url).status_code == 403, url
        ok(a.get(url))
    assert g.post('/api/tools/sql/connect', json={'driver': 'sqlite', 'path': 'x.db'}).status_code == 403
    assert g.post('/api/tools/mt/sshmaster/invoke', json={'m': 'store:get'}).status_code == 403
    # SSH / FTP WebSocket: yetkisiz kullanıcıya hata olayı + kapanış
    for path in ('/ws/tools/ssh', '/ws/tools/ftp?id=x'):
        with g.websocket_connect(path) as ws:
            ev = json.loads(ws.receive_text())
            assert ev['ch'] == 'error' and 'Yetkisiz' in ev['d'], ev
    # Bilinmeyen uygulama / kanal
    assert a.get('/api/tools/mt/yok/boot').status_code == 404
    assert a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'yok:kanal'}).status_code == 400


def inv(c, app, m, a=None):
    """IPC kanalı çağrısı (bridge invoke karşılığı); {ok, v, store?} döner."""
    return ok(c.post(f'/api/tools/mt/{app}/invoke', json={'m': m, 'a': a}))


def ws_call(ws, m, a=None, cid=1, events=None, timeout=20):
    """WS üzerinden çağrı; yanıt gelene kadar olayları (ev) toplar."""
    ws.send_text(json.dumps({'t': 'call', 'id': cid, 'm': m, 'a': a}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = json.loads(ws.receive_text())
        if msg.get('t') == 'ret' and msg.get('id') == cid:
            return msg
        if events is not None:
            events.append(msg)
    raise AssertionError('WS yanıtı gelmedi: ' + m)


def ws_wait_event(ws, ch, pred=lambda d: True, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = json.loads(ws.receive_text())
        if msg.get('t') == 'ev' and msg.get('ch') == ch and pred(msg['d']):
            return msg['d']
    raise AssertionError('WS olayı gelmedi: ' + ch)


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
        test_sql(a)
        test_convert(a)
        test_notepad(a, g)
        test_sshmaster(a)
        test_ftpmaster(a)
    print('Araçlar › Master Tool web testleri geçti.')


if __name__ == '__main__':
    main()
