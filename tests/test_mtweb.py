"""mtweb testleri (docs/mtweb.md): kimlik (302/401/403, önbellek, yalnız sm_session iletimi), Origin/Referer reddi, uzak özellik uçlarının
kapalı olması, beyaz liste dışı araç uçları (SSH/FTP/SQL) 404, kotalar (tek yükleme, alan, dosya sayısı, gövde, Convert giriş boyutu,
oran sınırı), yol kaçışı (../, mutlak yol, sembolik bağ), devre dışı uygulama, /web/ yönlendirmeleri, bilgi sayfaları, güvenlik
başlıkları, iç hata sızdırmama, denetim günlüğü (içerik yok), kullanıcı yalıtımı, Notepad yerel proje ve Convert png→jpg.

Çalıştırma: .venv/bin/python -m tests.test_mtweb
"""
import io
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

D = tempfile.mkdtemp(prefix='mtweb-test-')
for k in [k for k in os.environ if k.startswith(('CAYMAZ_', 'MTWEB_'))]:
    del os.environ[k]
from tests import mtweb_fake_mt  # noqa: E402

_srv, _port = mtweb_fake_mt.serve()
os.environ.update(MTWEB_DATA_DIR=D, MTWEB_ACCOUNT_URL=f'http://127.0.0.1:{_port}', MTWEB_SPACE_MB='3', MTWEB_UPLOAD_MB='1', MTWEB_MAX_FILES='40',
                  MTWEB_BODY_MB='2', MTWEB_CONVERT_INPUT_MB='1', CAYMAZ_ENV_FILE=os.path.join(D, 'yok.env'))
for k in [k for k in sys.modules if k == 'app' or k.startswith('app.')]:
    del sys.modules[k]

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.mtweb import auth, config, main as mmain, quota  # noqa: E402
from app.routers import tools_notepad  # noqa: E402

ALI, AYSE, NOVERIFY = list(mtweb_fake_mt.TOKENS)
O = {'Origin': 'http://testserver'}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text[:300])
    return r.json() if 'json' in r.headers.get('content-type', '') else r.content


def client(tok=None, **kw):
    c = TestClient(mmain.app, **kw)
    c.__enter__()
    if tok:
        c.cookies.set('sm_session', tok)
    return c


def png(w=64, h=40):
    b = io.BytesIO()
    Image.new('RGB', (w, h), (200, 30, 30)).save(b, format='PNG')
    return b.getvalue()


def test_auth(anon, a):
    r = anon.get('/web/notepadmaster/', follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == '/giris?next=/web/notepadmaster/', r.headers
    r = anon.get('/web/convertmaster/project.html?id=x', follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'].startswith('/giris?next=/web/convertmaster/project.html%3Fid%3Dx'), r.headers
    assert anon.get('/api/tools/notepad/store').status_code == 401
    bad = client('tok-yok-0123456789abcdef')
    assert bad.get('/api/tools/notepad/store').status_code == 401
    assert bad.get('/web/notepadmaster/', follow_redirects=False).status_code == 302
    nv = client(NOVERIFY)
    assert nv.get('/api/tools/notepad/store').status_code == 403
    assert nv.get('/web/notepadmaster/', follow_redirects=False).status_code == 403
    # Geçerli oturum: sayfa + enjekte edilen betikler
    html = a.get('/web/notepadmaster/').text
    assert '/web/config.js?app=notepadmaster' in html and '../common/mtweb.js' in html and '../common/mtweb.css' in html
    assert html.index('mtweb.js') < html.index('hepgo.js')
    cfg = a.get('/web/config.js?app=notepadmaster').text
    assert cfg.startswith('window.MTWEB = ') and 'Ali Yılmaz' in cfg and '"remote": false' in cfg
    # Hesap servisine yalnız sm_session çerezi gider; ~60 sn önbellek
    calls = mtweb_fake_mt.STATE['me_calls']
    for _ in range(5):
        ok(a.get('/api/tools/notepad/store'))
    assert mtweb_fake_mt.STATE['me_calls'] == calls
    hdr = mtweb_fake_mt.STATE['headers'][-1]
    assert list(hdr) == ['Cookie'] and hdr['Cookie'] == f'sm_session={ALI}', hdr
    acct = ok(a.get('/api/tools/mt/account'))
    assert acct['user']['email'] == 'ali@test.com' and acct['user']['id'] == 501 and acct['hepgo'] is False
    # Hesap servisi kapalıysa 503 (önbellekte olmayan belirteç)
    old = config.ACCOUNT_URL
    config.ACCOUNT_URL = 'http://127.0.0.1:1'
    try:
        assert client('tok-baska-0123456789abcdef').get('/api/tools/notepad/store').status_code == 503
    finally:
        config.ACCOUNT_URL = old


def test_origin(a):
    body = {'patch': {'appTheme': 'dark'}}
    assert a.post('/api/tools/notepad/settings', json=body).status_code == 403                                    # Origin/Referer yok
    assert a.post('/api/tools/notepad/settings', json=body, headers={'Origin': 'https://kotu.example'}).status_code == 403
    assert a.post('/api/tools/notepad/settings', json=body, headers={'Origin': 'http://testserver.kotu.example'}).status_code == 403
    assert a.post('/api/tools/notepad/settings', json=body, headers={'Origin': 'null'}).status_code == 403
    assert a.post('/api/tools/notepad/settings', json=body, headers={'Referer': 'https://kotu.example/web/'}).status_code == 403
    ok(a.post('/api/tools/notepad/settings', json=body, headers={'Referer': 'http://testserver/web/notepadmaster/'}))
    ok(a.post('/api/tools/notepad/settings', json=body, headers=O))
    # Origin reddi kimlikten önce: oturumsuz istek de 403
    assert client().post('/api/tools/notepad/settings', json=body).status_code == 403


def test_remote_closed(a):
    for path, body in (('/api/tools/notepad/browse/open', {'form': {'kind': 'ssh', 'host': '127.0.0.1'}}),
                       ('/api/tools/notepad/browse/list', {'token': 'x'}), ('/api/tools/notepad/keys/upload', {}),
                       ('/api/tools/convert/speech/download', {}), ('/api/tools/convert/ocr/download', {}),
                       ('/api/tools/notepad/conn/save', {'form': {'kind': 'ssh', 'host': '10.0.0.1', 'username': 'x'}}),
                       ('/api/tools/notepad/conn/save', {'form': {'kind': 'ftp', 'host': '10.0.0.1'}}),
                       ('/api/tools/notepad/conn/save', {'form': {'host': '10.0.0.1'}}),
                       ('/api/tools/notepad/conn/test', {'form': {'kind': 'ssh', 'host': '127.0.0.1', 'username': 'x'}})):
        r = a.post(path, json=body, headers=O)
        assert r.status_code == 403 and r.json()['detail'] == 'Bu özellik masaüstü sürümünde', (path, r.status_code, r.text)
    # Diğer araç uygulamaları (SSH/FTP/SQL Master) bu serviste yok
    for path in ('/api/tools/ssh/status', '/api/tools/ftp/caps', '/api/tools/sql/drivers', '/api/tools/mt/sshmaster/boot',
                 '/api/tools/mt/ftpmaster/boot', '/api/tools/mt/sqlmaster/fs/list', '/api/tools/volfai/profile', '/api/auth/me', '/api/users'):
        assert a.get(path).status_code == 404, path
    assert a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'store:get'}, headers=O).status_code == 404
    # Savunma derinliği: depo elle bozulsa da uzak bağlantı açılmaz
    try:
        tools_notepad.create_remote(1, {'kind': 'ssh', 'host': '127.0.0.1', 'port': 22})
        raise AssertionError('uzak bağlantı açıldı')
    except tools_notepad.RemoteError as e:
        assert e.code == 'REMOTE_OFF'
    ok(a.post('/api/tools/notepad/conn/test', json={'form': {'kind': 'local', 'localPath': '/'}}, headers=O))


def test_notepad(a):
    cid = ok(a.post('/api/tools/notepad/conn/save', json={'form': {'kind': 'local', 'name': 'Proje', 'localPath': '/'}}, headers=O))['id']
    r = ok(a.post('/api/tools/notepad/proj/open', json={'id': cid}, headers=O))
    assert r['ok'] and r['root'] == '/' and not r['cacheRoot'].startswith('/'), r     # sunucu yolu sızmaz
    sid = r['sid']
    ok(a.post('/api/tools/notepad/proj/newFile', json={'sid': sid, 'path': '/not.txt'}, headers=O))
    s = ok(a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/not.txt', 'text': 'GIZLI-ICERIK merhaba\n', 'encoding': 'utf8'}, headers=O))
    assert s['ok'] and not s['cachePath'].startswith('/'), s
    rd = ok(a.post('/api/tools/notepad/proj/read', json={'sid': sid, 'path': '/not.txt'}, headers=O))
    assert rd['text'] == 'GIZLI-ICERIK merhaba\n'
    # Proje kökü dışına çıkamaz
    r = a.post('/api/tools/notepad/proj/read', json={'sid': sid, 'path': '/../../mtweb.db'}, headers=O)
    assert r.status_code == 400, r.text
    return sid


def test_paths(a):
    root = quota.tools_common.TOOLS_DIR / 'notepadmaster' / '1' / 'files'
    assert root.is_dir(), root
    out = Path(D) / 'disari'
    out.mkdir(exist_ok=True)
    (out / 'gizli.txt').write_text('dışarıdaki dosya')
    (root / 'bag').symlink_to(out)
    (root / 'dosyabag.txt').symlink_to(out / 'gizli.txt')
    items = ok(a.get('/api/tools/mt/notepadmaster/fs/list', params={'path': '/../../..'}))['items']
    assert {i['name'] for i in items} >= {'not.txt'}, items                       # ../ köke sıkışır
    assert a.get('/api/tools/mt/notepadmaster/fs/list', params={'path': '/bag'}).status_code == 400
    assert a.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '/bag/gizli.txt'}).status_code == 400
    assert a.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '/dosyabag.txt'}).status_code == 400
    assert a.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '/etc/passwd'}).status_code == 404
    assert a.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '../../mtweb.db'}).status_code == 404
    assert a.post('/api/tools/mt/notepadmaster/fs/rename', json={'path': '/not.txt', 'name': '../../kacis.txt'}, headers=O).json()['path'] == '/kacis.txt'
    ok(a.post('/api/tools/mt/notepadmaster/fs/rename', json={'path': '/kacis.txt', 'name': 'not.txt'}, headers=O))
    r = a.post('/api/tools/mt/notepadmaster/fs/upload', files={'files': ('../../../kacis.txt', b'x')}, data={'dir': '/../..'}, headers=O)
    assert ok(r)['items'][0]['path'] == '/kacis.txt'
    assert not (Path(D) / 'kacis.txt').exists() and not (Path(D) / 'tools' / 'kacis.txt').exists()
    (root / 'bag').unlink()
    (root / 'dosyabag.txt').unlink()
    ok(a.post('/api/tools/mt/notepadmaster/fs/delete', json={'path': '/kacis.txt'}, headers=O))


def test_isolation(a, b):
    assert 'not.txt' not in {i['name'] for i in ok(b.get('/api/tools/mt/notepadmaster/fs/list'))['items']}
    assert b.get('/api/tools/mt/notepadmaster/fs/download', params={'path': '/not.txt'}).status_code == 404
    assert ok(b.get('/api/tools/notepad/store'))['connections'] == []


def test_quotas(a, sid):
    quota.invalidate(1)
    big = os.urandom(int(1.5 * config.MB))
    r = a.post('/api/tools/mt/notepadmaster/fs/upload', files={'files': ('buyuk.bin', big)}, data={'dir': '/'}, headers=O)
    assert r.status_code == 413, r.text                                          # tek yükleme > 1 MB
    assert not any(i['name'] == 'buyuk.bin' for i in ok(a.get('/api/tools/mt/notepadmaster/fs/list'))['items'])
    part = os.urandom(int(0.9 * config.MB))
    codes = [a.post('/api/tools/mt/convertmaster/fs/upload', files={'files': (f'p{i}.bin', part)}, data={'dir': '/'}, headers=O).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and 413 in codes[3:], codes             # 3 MB alan iki uygulamanın toplamı
    quota.invalidate(1)
    used, _ = quota.usage(1)
    assert used <= config.SPACE_BYTES, used
    # Notepad kaydı da alan kotasına takılır
    text = 'x' * int(0.8 * config.MB)
    r = a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/buyuk.txt', 'text': text, 'encoding': 'utf8'}, headers=O)
    assert r.status_code == 413, r.text
    # Gövde sınırı (yükleme dışı ≤ 2 MB)
    r = a.post('/api/tools/notepad/proj/save', json={'sid': sid, 'path': '/x.txt', 'text': 'y' * (3 * config.MB)}, headers=O)
    assert r.status_code == 413
    # Alanı boşalt, dosya sayısı tavanı
    for i in range(5):
        a.post('/api/tools/mt/convertmaster/fs/delete', json={'path': f'/p{i}.bin'}, headers=O)
    quota.invalidate(1)
    codes = [a.post('/api/tools/notepad/proj/newFile', json={'sid': sid, 'path': f'/f{i}.txt'}, headers=O).status_code for i in range(60)]
    assert 413 in codes and codes[0] == 200, codes
    for i in range(60):
        a.post('/api/tools/mt/notepadmaster/fs/delete', json={'path': f'/f{i}.txt'}, headers=O)
    quota.invalidate(1)
    # Oran sınırı
    old = config.RATE_READ
    config.RATE_READ = (5, 60)
    auth.reset()
    try:
        codes = [a.get('/api/tools/notepad/store').status_code for _ in range(8)]
        assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3, codes
    finally:
        config.RATE_READ = old
        auth.reset()


def test_convert(a):
    up = a.post('/api/tools/mt/convertmaster/fs/upload', files=[('files', ('resim.png', png())), ('files', ('dev.png', b'0' * 10))],
                data={'dir': '/girdi'}, headers=O)
    ok(up)
    big = Image.new('RGB', (2000, 1500))
    raw = io.BytesIO()
    big.save(raw, format='BMP')   # ~9 MB BMP > 1 MB giriş sınırı, ama yükleme sınırı da 1 MB → dosyayı doğrudan alana koy
    (quota.tools_common.TOOLS_DIR / 'convertmaster' / '1' / 'files' / 'girdi' / 'buyuk.bmp').write_bytes(raw.getvalue()[: int(1.2 * config.MB)])
    quota.invalidate(1)
    pid = ok(a.post('/api/tools/convert/project/save', json={'form': {'name': 'Resim', 'type': 'image', 'sourceExts': ['png', 'bmp'], 'targetExt': 'jpg',
                                                                     'sourcePath': '/girdi', 'concurrency': 8}}, headers=O))['id']
    snap = ok(a.post('/api/tools/convert/pj/init', json={'id': pid}, headers=O))['snapshot']
    assert sorted(f['rel'] for f in snap['files']) == ['buyuk.bmp', 'dev.png', 'resim.png'], snap
    ok(a.post('/api/tools/convert/pj/start', json={'id': pid, 'opts': {}}, headers=O))
    items = {}
    for _ in range(100):
        ev = ok(a.get('/api/tools/convert/pj/events', params={'id': pid, 'since': 0}))
        for e in ev['events']:
            if e['ch'] == 'job:items':
                for it in e['data']:
                    items[it['rel']] = it
        if all(items.get(r, {}).get('status') in ('done', 'error') for r in ('resim.png', 'dev.png', 'buyuk.bmp')):
            break
        time.sleep(0.1)
    assert items['resim.png']['status'] == 'done', items
    assert items['buyuk.bmp']['status'] == 'error' and 'çok büyük' in items['buyuk.bmp']['error'], items
    assert items['dev.png']['status'] == 'error'
    z = a.get('/api/tools/convert/pj/exportOutputs', params={'id': pid})
    assert z.status_code == 200 and z.content[:2] == b'PK'
    from app.routers import tools_convert
    assert tools_convert.MAX_CONCURRENCY == 1 and tools_convert.FFMPEG_TIMEOUT == config.CONVERT_TIMEOUT_S
    assert tools_convert.Image.MAX_IMAGE_PIXELS == config.IMAGE_MAX_PIXELS
    ok(a.post('/api/tools/convert/pj/close', json={'id': pid}, headers=O))
    st = ok(a.get('/api/tools/convert/storage/info'))
    assert st['dir'].startswith('Mastertool'), st


def test_disabled(a):
    old = config.DISABLED_APPS
    config.DISABLED_APPS = frozenset({'convertmaster'})
    try:
        assert a.get('/api/tools/convert/store').status_code == 403
        assert a.get('/api/tools/mt/convertmaster/fs/list').status_code == 403
        assert a.get('/web/convertmaster/').status_code == 503
        ok(a.get('/api/tools/notepad/store'))
        ok(a.get('/web/notepadmaster/'))
    finally:
        config.DISABLED_APPS = old


def test_pages(anon, a):
    for host, loc in (('notepadmaster.com', '/web/notepadmaster/'), ('www.convertmaster.app', '/web/convertmaster/'),
                      ('mastertool.download', '/uygulamalar'), ('sshmasters.com', '/'), ('simumav.com:8443', '/')):
        r = anon.get('/web/', headers={'Host': host}, follow_redirects=False)
        assert r.status_code == 302 and r.headers['location'] == loc, (host, r.headers)
    for name in ('sshmaster', 'ftpmaster', 'sqlmaster'):
        r = anon.get(f'/web/{name}/')
        assert r.status_code == 200 and 'coming soon' in r.text and 'href="/#indir"' in r.text, name
        assert anon.get(f'/web/{name}', follow_redirects=False).status_code == 307
    assert anon.get('/web/yok/').status_code == 404
    ok(anon.get('/web/healthz'))
    # Statik ortak dosyalar oturumsuz da sunulur; çıplak HTML kimlikli sayfaya yönlenir
    assert anon.get('/static/mt/common/hepgo.js').status_code == 200
    assert anon.get('/web/common/mtweb.js').status_code == 200
    assert anon.get('/web/notepadmaster/bridge.js').status_code == 200
    assert anon.get('/web/notepadmaster/vendor/monaco/vs/loader.js').status_code == 200
    r = anon.get('/static/mt/notepadmaster/index.html', follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == '/web/notepadmaster/'
    # Güvenlik başlıkları
    r = a.get('/web/notepadmaster/')
    csp = r.headers['content-security-policy']
    assert "frame-ancestors 'self'" in csp and "script-src 'self';" in csp and 'unsafe-inline' not in csp.split('script-src')[1].split(';')[0]
    assert r.headers['x-content-type-options'] == 'nosniff' and r.headers['x-frame-options'] == 'SAMEORIGIN' and r.headers['referrer-policy']
    assert a.get('/api/tools/notepad/store').headers['cache-control'] == 'no-store'
    assert anon.get('/api/tools/notepad/store').headers['cache-control'] == 'no-store'


def test_internal_error(a):
    c = client(ALI, raise_server_exceptions=False)
    old = tools_notepad.load_store
    tools_notepad.load_store = lambda uid: (_ for _ in ()).throw(RuntimeError('/opt/gizli/yol SECRET-AYRINTI'))
    try:
        r = c.get('/api/tools/notepad/store')
        assert r.status_code == 500 and 'SECRET' not in r.text and '/opt' not in r.text and r.headers['content-security-policy'], r.text
    finally:
        tools_notepad.load_store = old


def test_audit():
    con = sqlite3.connect(Path(D) / 'mtweb.db')
    rows = con.execute('SELECT user_id, app, action, size, ip, detail FROM mtweb_audit').fetchall()
    acts = {r[2] for r in rows}
    assert {'session', 'csrf', 'blocked', 'notepad/proj/save', 'mt/notepadmaster/fs/upload', 'quota', 'rate', 'convert'} <= acts, acts
    assert not any('GIZLI' in str(r) for r in rows)
    assert all(r[4] for r in rows if r[2] == 'notepad/proj/save')
    # 90 günden eski kayıtlar temizlenir
    con.execute("INSERT INTO mtweb_audit (at, action) VALUES (?, 'eski')", (time.time() - 91 * 86400,))
    con.commit()
    from app.mtweb import db as mdb
    mdb.purge(force=True)
    assert not con.execute("SELECT 1 FROM mtweb_audit WHERE action = 'eski'").fetchone()
    # Kullanıcı satırı Mastertool kimliğine bağlı
    assert con.execute('SELECT id, mt_id, username FROM users ORDER BY id').fetchall()[:2] == [(1, 501, 'ali@test.com'), (2, 502, 'ayse@test.com')]


def main():
    anon = client()
    a = client(ALI)
    b = client(AYSE)
    test_auth(anon, a)
    ok(b.get('/api/tools/notepad/store'))
    test_origin(a)
    test_remote_closed(a)
    sid = test_notepad(a)
    test_paths(a)
    test_isolation(a, b)
    test_quotas(a, sid)
    test_convert(a)
    test_disabled(a)
    test_pages(anon, a)
    test_internal_error(a)
    test_audit()
    print('mtweb testleri geçti.')


if __name__ == '__main__':
    main()
