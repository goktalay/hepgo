"""mtweb aşama 2 testleri (docs/mtweb.md §Dış bağlantılar): SSH Master · FTP Masters · SQL Master · Notepad uzak klasör.

- SSRF: 127.0.0.1, 10.x, 169.254.169.254, ::1, ::ffff:127.0.0.1, CGNAT, ULA, 6to4 / NAT64 içi özel adres, özel IP'ye çözen ad,
  karışık çözüm (biri bile özelse ret), 178.157.10.114 (MTWEB_ALLOW_PRIVATE=1 iken de), port 25 / 465 / 587 + MTWEB_BLOCK_PORTS.
- Bağlantı doğrulanan IP'ye: paramiko'ya hazır soket, FTP'de PASV yanıtındaki (özel) IP yok sayılır, engelli PASV portu ve
  aktif kip (PORT) reddi, PG hostaddr / MySQL hazır soket, SQL SSH tünelinde ajan reddi + hedef denetimi.
- WebSocket: Origin != Host reddi, oturumsuz ret, boşta kapanış; devre dışı uygulama (acil anahtar) — API, sayfa, WS, guard.
- Kotalar: kullanıcı başına eşzamanlı oturum (4), genel tavan, deneme oranı (kullanıcı / IP), SSH indirmesi alan kotasına takılır.
- SQLite: ATTACH / VACUUM INTO / load_extension / TEMP reddi, caymaz.db istisnası kapalı, sayfa tavanı, süre sınırı.
- Denetim: mtweb_audit 'net' kayıtları (kullanıcı, uygulama, host, IP, port, sonuç, istemci IP; parola / komut / sorgu yok).
- Parolalar Fernet ('enc:'), anahtar dosyası 0600, arayüze gitmez; known_hosts kullanıcı başına.
- HEPGO'da guard kapalı (ayrı süreçte: kancalar None, net_target adresi olduğu gibi döndürür).
- Uçtan uca (MTWEB_ALLOW_PRIVATE): yerel paramiko SSH sunucusunda WebSocket ile komut çıktısı + SFTP listesi, yerel FTP'de liste.

Çalıştırma: .venv/bin/python -m tests.test_mtweb_net
"""
import ftplib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

D = tempfile.mkdtemp(prefix='mtweb-net-')
for k in [k for k in os.environ if k.startswith(('CAYMAZ_', 'MTWEB_'))]:
    del os.environ[k]
from tests import mtweb_fake_mt  # noqa: E402

_srv, _port = mtweb_fake_mt.serve()
os.environ.update(MTWEB_DATA_DIR=D, MTWEB_ACCOUNT_URL=f'http://127.0.0.1:{_port}', MTWEB_SPACE_MB='3', MTWEB_UPLOAD_MB='1',
                  MTWEB_NET_ATTEMPTS_USER='1000', MTWEB_NET_ATTEMPTS_IP='2000', MTWEB_BLOCK_PORTS='2525',
                  CAYMAZ_ENV_FILE=os.path.join(D, 'yok.env'))
for k in [k for k in sys.modules if k == 'app' or k.startswith('app.')]:
    del sys.modules[k]

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.mtweb import auth, config, guard, main as mmain, quota  # noqa: E402
from app.routers import tools_common, tools_ftp, tools_mt, tools_sql, tools_ssh  # noqa: E402
from tests.mtweb_ftpd import FtpServer  # noqa: E402
from tests.mtweb_sshd import SshServer  # noqa: E402

ALI, AYSE, _ = list(mtweb_fake_mt.TOKENS)
O = {'Origin': 'http://testserver'}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text[:300])
    return r.json() if 'json' in r.headers.get('content-type', '') else r.content


def client(tok=None):
    c = TestClient(mmain.app)
    c.__enter__()
    if tok:
        c.cookies.set('sm_session', tok)
    return c


def denied(host, port=22, uid=1, app='sshmaster', kind='connect'):
    try:
        ip = guard.resolve_target(host, port, uid, app, kind)
    except guard.Denied as e:
        return str(e)
    raise AssertionError(f'izin verildi: {host}:{port} → {ip}')


class private:
    """config.ALLOW_PRIVATE geçici olarak açık (yerel test sunucuları)."""
    def __enter__(self):
        self.old = config.ALLOW_PRIVATE
        config.ALLOW_PRIVATE = True

    def __exit__(self, *a):
        config.ALLOW_PRIVATE = self.old


# --- 1. SSRF ---------------------------------------------------------------------------------------------------------
def test_ssrf():
    for h in ('127.0.0.1', '10.1.2.3', '172.16.0.9', '192.168.1.1', '169.254.169.254', '100.64.0.1', '0.0.0.0', '224.0.0.1', '255.255.255.255',
              '::1', '[::1]', '::ffff:127.0.0.1', '::ffff:10.0.0.1', 'fd00::1', 'fe80::1', 'fec0::1', '2002:7f00:1::1', '64:ff9b::a00:1',
              '::', 'localhost', '127.1'):
        msg = denied(h)
        assert 'yerel / özel' in msg or 'Geçersiz' in msg, (h, msg)
    # Adreslerden biri bile özelse ret (karışık DNS yanıtı)
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        if host == 'karma.example':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', port))]
        if host == 'ozel.example':
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::ffff:192.168.0.10', port, 0, 0))]
        if host == 'genel.example':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
        return real(host, port, *a, **k)
    guard.socket.getaddrinfo = fake
    try:
        assert 'yerel / özel' in denied('karma.example')
        assert 'yerel / özel' in denied('ozel.example')
        assert guard.resolve_target('genel.example', 22, 1, 'sshmaster') == '93.184.216.34'
    finally:
        guard.socket.getaddrinfo = real
    # Sunucunun kendi adresi: ALLOW_PRIVATE açıkken de ret
    with private():
        assert 'kendi adresi' in denied('178.157.10.114')
        assert 'kendi adresi' in denied('::ffff:178.157.10.114')
        assert guard.resolve_target('127.0.0.1', 22, 1, 'sshmaster') == '127.0.0.1'
    assert 'kendi adresi' in denied('178.157.10.114')
    # Yerel arabirim adresleri (ör. sunucunun kendi LAN/genel IP'si) — global olsa da ret
    old = guard._local['addrs'], guard._local['at']
    guard._local.update(addrs=frozenset({guard.ipaddress.ip_address('93.184.216.34')}), at=time.time())
    try:
        assert 'kendi adresi' in denied('93.184.216.34')
    finally:
        guard._local.update(addrs=old[0], at=old[1])
    assert any(a.is_loopback for a in guard.local_addresses())
    # Portlar: 25 / 465 / 587 + MTWEB_BLOCK_PORTS
    for p in (25, 465, 587, 2525, 0, 70000):
        assert 'port' in denied('93.184.216.34', p).lower() or 'Port' in denied('93.184.216.34', p), p
    assert guard.resolve_target('93.184.216.34', 22, 1, 'sshmaster') == '93.184.216.34'
    assert guard.resolve_target('2606:4700:4700::1111', 443, 1, 'sqlmaster') == '2606:4700:4700::1111'
    # Geçersiz host (ssh seçeneği gibi)
    assert 'Geçersiz' in denied('-oProxyCommand=x')
    # Ad çözülemezse DNS hatası (arayüzde "sunucu adı çözümlenemedi")
    try:
        guard.resolve_target('yok.invalid', 22, 1, 'sshmaster')
        raise AssertionError('DNS hatası beklenirdi')
    except socket.gaierror:
        pass


def test_connect_paths():
    """Her araç bağlantısı guard'dan geçer (HTTP/IPC uçları üzerinden)."""
    a = client(ALI)
    # SSH Master: conn:test (IPC) → 10.x reddi
    r = ok(a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'conn:test', 'a': {'host': '10.0.0.7', 'port': 22, 'username': 'x', 'password': 'p'}}, headers=O))
    assert r['ok'] and r['v']['ok'] is False and 'yerel / özel' in r['v']['message'], r
    # FTP Masters: ftp ve sftp
    for proto in ('ftp', 'sftp', 'ftps-tls'):
        r = ok(a.post('/api/tools/mt/ftpmaster/invoke', json={'m': 'conn:test', 'a': {'host': '169.254.169.254', 'protocol': proto, 'username': 'x'}}, headers=O))
        assert r['v']['ok'] is False and 'yerel / özel' in r['v']['message'], (proto, r)
    r = ok(a.post('/api/tools/mt/ftpmaster/invoke', json={'m': 'conn:test', 'a': {'host': '93.184.216.34', 'port': 25, 'protocol': 'ftp', 'username': 'x'}}, headers=O))
    assert 'Port 25' in r['v']['message'], r
    # SQL Master: postgres / mysql doğrudan, SSH tüneli
    for prov in ('postgres', 'mysql'):
        r = ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': prov, 'host': '127.0.0.1', 'user': 'u'}}, headers=O))
        assert r['ok'] is False and 'yerel / özel' in r['message'], (prov, r)
        r = ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': prov, 'host': '', 'user': 'u'}}, headers=O))   # boş → localhost
        assert r['ok'] is False and 'yerel / özel' in r['message'], (prov, r)
    r = ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'postgres', 'host': '93.184.216.34', 'ssh': {'enabled': True, 'host': '10.9.9.9', 'user': 'u', 'auth': 'password'}}}, headers=O))
    assert r['ok'] is False and 'yerel / özel' in r['message'], r
    r = ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'postgres', 'host': '93.184.216.34', 'ssh': {'enabled': True, 'host': '93.184.216.34', 'user': 'u', 'auth': 'agent'}}}, headers=O))
    assert r['ok'] is False and 'ajanı' in r['message'], r
    # Tünel hedefi de yerelde denetlenir (SSH sunucusundan önce): localhost hedefi reddedilir
    r = ok(a.post('/api/tools/sql/conn/test', json={'form': {'provider': 'postgres', 'host': 'localhost', 'ssh': {'enabled': True, 'host': '93.184.216.34', 'user': 'u', 'auth': 'password'}}}, headers=O))
    assert r['ok'] is False and 'yerel / özel' in r['message'], r
    # PG: hostaddr = doğrulanmış IP; MySQL: hazır soket (defer_connect) — sürücüye giden argümanlar
    seen = {}
    if tools_sql.DRIVERS['postgres']:
        import psycopg
        orig = psycopg.connect
        psycopg.connect = lambda **kw: seen.setdefault('pg', kw) and (_ for _ in ()).throw(RuntimeError('durdur'))
        try:
            with private():
                tools_sql.open_connection({'provider': 'postgres', 'host': 'localhost', 'port': 5432, 'user': 'u'}, 1)
        except RuntimeError:
            pass
        finally:
            psycopg.connect = orig
        assert seen['pg']['hostaddr'] in ('127.0.0.1', '::1') and seen['pg']['host'] == 'localhost', seen
    if tools_sql.DRIVERS['mysql']:
        import pymysql
        lst = socket.socket()
        lst.bind(('127.0.0.1', 0))
        lst.listen(1)
        orig = pymysql.connect

        class FakeCn:
            def __init__(self, **kw):
                seen['my'] = kw

            def connect(self, sock=None):
                seen['my_sock'] = sock.getpeername()
                raise RuntimeError('durdur')
        pymysql.connect = FakeCn
        try:
            with private():
                tools_sql.open_connection({'provider': 'mysql', 'host': '127.0.0.1', 'port': lst.getsockname()[1], 'user': 'u'}, 1)
        except RuntimeError:
            pass
        finally:
            pymysql.connect = orig
            lst.close()
        assert seen['my']['defer_connect'] is True and seen['my']['host'] == '127.0.0.1' and seen['my_sock'][0] == '127.0.0.1', seen
    # Notepad uzak klasör
    r = ok(a.post('/api/tools/notepad/conn/test', json={'form': {'kind': 'ftp', 'protocol': 'ftp', 'host': '10.1.1.1', 'username': 'x'}}, headers=O))
    assert r['ok'] is False and 'yerel / özel' in r['message'], r


# --- FTP: PASV IP'si yok sayılır, engelli PASV portu, aktif kip kapalı -------------------------------------------------------
def test_ftp_pasv(root):
    srv = FtpServer(root, pasv_ip='10.0.0.1').start()
    try:
        with private():
            conn = {'host': '127.0.0.1', 'port': srv.port, 'protocol': 'ftp', 'username': 'test', 'password': 'parola'}
            r = tools_ftp.FtpRemote(conn, 1).connect()
            names = {e['name'] for e in r.list('/')}
            assert 'merhaba.txt' in names, names
            assert srv.data_peers and all(p == '127.0.0.1' for p in srv.data_peers)   # 10.0.0.1'e değil, kontrol IP'sine
            assert r.client.trust_server_pasv_ipv4_address is False
            try:
                r.client.makeport()
                raise AssertionError('PORT açıldı')
            except tools_common.NetDenied:
                pass
            r.close()
            srv.pasv_port = 25   # PASV yanıtı engelli port gösterirse veri kanalı açılmaz
            r = tools_ftp.FtpRemote(conn, 1).connect()
            try:
                r.list('/')
                raise AssertionError('port 25 veri kanalı açıldı')
            except tools_common.NetDenied as e:
                assert '25' in str(e)
            r.close()
            # Notepad'in FTP katmanı da aynı sertleştirmeden geçer
            from app.routers import tools_notepad
            srv.pasv_port = None
            nr = tools_notepad.create_remote(1, {'kind': 'ftp', 'protocol': 'ftp', 'host': '127.0.0.1', 'port': srv.port, 'username': 'test', 'password': 'parola'}).connect()
            assert nr.client.trust_server_pasv_ipv4_address is False and 'merhaba.txt' in {e['name'] for e in nr.list('/')}
            nr.close()
    finally:
        srv.stop()
    # Kötü niyetli sunucu / istemci adı yerel alandan kaçamaz
    for bad in ('..', '../x', 'a/b', '.', '', 'a\\b', 'x\x00'):
        try:
            tools_mt.safe_segment(bad)
            raise AssertionError(bad)
        except tools_mt.MtError:
            pass
    assert tools_mt.safe_join(Path('/k'), 'a/b') == Path('/k/a/b')


# --- 2. WebSocket --------------------------------------------------------------------------------------------------------
def ws_try(c, path='/ws/tools/ssh', headers=None):
    try:
        with c.websocket_connect(path, headers=headers or {}) as ws:
            ws.send_text(json.dumps({'t': 'call', 'id': 1, 'm': 'ssh:start', 'a': {'pane': 'p1', 'connId': 'yok'}}))
            return json.loads(ws.receive_text())
    except WebSocketDisconnect as e:
        return ('kapandı', e.code)


def test_ws():
    a = client(ALI)
    assert ws_try(a, headers={'Origin': 'https://kotu.example'})[0] == 'kapandı'
    assert ws_try(a, headers={'Origin': 'http://testserver.kotu.example'})[0] == 'kapandı'
    assert ws_try(a, headers={'Origin': 'null'})[0] == 'kapandı'
    assert ws_try(a, headers={})[0] == 'kapandı'                                   # Origin yok
    assert ws_try(a, '/ws/tools/drone', headers=O)[0] == 'kapandı'                # beyaz liste dışı WS
    r = ws_try(client(), headers=O)                                                 # oturumsuz
    assert r == ('kapandı', 4403) or (isinstance(r, dict) and r.get('ch') == 'error'), r
    r = ws_try(a, headers=O)                                                        # geçerli: çağrı yanıtı
    assert r['t'] == 'ret' and r['ok'] and r['v']['ok'] is False, r
    # Boşta kapanış
    old = config.WS_IDLE_S
    config.WS_IDLE_S = 1
    try:
        with a.websocket_connect('/ws/tools/ftp?id=yok', headers=O) as ws:
            time.sleep(1.4)
            try:
                ws.receive_text()
                raise AssertionError('boşta kapanmadı')
            except WebSocketDisconnect as e:
                assert e.code == 4408, e.code
    finally:
        config.WS_IDLE_S = old


# --- 3. Kotalar ----------------------------------------------------------------------------------------------------------
def test_limits():
    guard.reset()
    rel = [guard.acquire(7, 'sshmaster') for _ in range(4)]
    try:
        guard.acquire(7, 'sshmaster')
        raise AssertionError('5. oturum açıldı')
    except guard.Denied as e:
        assert 'en çok 4 SSH Master' in str(e), e
    guard.acquire(7, 'ftpmaster')()                       # uygulama başına ayrı
    rel[0]()
    rel[0]()                                              # iki kez bırakmak güvenli
    rel.append(guard.acquire(7, 'sshmaster'))
    assert guard.open_sessions(7, 'sshmaster') == 4
    for r in rel:
        r()
    assert guard.open_sessions() == 0
    old = config.NET_SESSIONS
    config.NET_SESSIONS = 2
    try:
        x, y = guard.acquire(1, 'sqlmaster'), guard.acquire(2, 'sqlmaster')
        try:
            guard.acquire(3, 'sqlmaster')
            raise AssertionError('genel tavan aşıldı')
        except guard.Denied as e:
            assert 'yoğun' in str(e)
        x(), y()
    finally:
        config.NET_SESSIONS = old
    # Deneme oranı: kullanıcı ve istemci IP
    auth.reset()
    old = config.NET_ATTEMPTS_USER, config.NET_ATTEMPTS_IP
    config.NET_ATTEMPTS_USER, config.NET_ATTEMPTS_IP = 3, 5
    try:
        for _ in range(3):
            guard.resolve_target('93.184.216.34', 22, 9, 'sshmaster')
        assert 'Çok fazla' in denied('93.184.216.34', 22, 9)
        guard.resolve_target('93.184.216.34', 22, 9, 'sshmaster', 'data')   # veri kanalı oran saymaz
        guard.CLIENT_IP[10] = guard.CLIENT_IP[11] = '203.0.113.9'
        for _ in range(3):
            guard.resolve_target('93.184.216.34', 22, 10, 'sshmaster')
        guard.resolve_target('93.184.216.34', 22, 11, 'sshmaster')
        guard.resolve_target('93.184.216.34', 22, 11, 'sshmaster')
        assert 'Çok fazla' in denied('93.184.216.34', 22, 11)              # aynı IP'den 6. deneme
    finally:
        config.NET_ATTEMPTS_USER, config.NET_ATTEMPTS_IP = old
        auth.reset()


# --- 6. Acil anahtar -------------------------------------------------------------------------------------------------------
def test_disabled():
    a = client(ALI)
    old = config.DISABLED_APPS
    config.DISABLED_APPS = frozenset({'sshmaster', 'ftpmaster', 'sqlmaster'})
    try:
        assert a.get('/api/tools/mt/sshmaster/boot').status_code == 403
        assert a.get('/api/tools/sql/store').status_code == 403
        assert a.get('/api/tools/ftp/caps').status_code == 403
        assert a.get('/web/sshmaster/').status_code == 503
        assert a.get('/web/sqlmaster/renderer/main/').status_code == 503
        assert ws_try(a, headers=O)[0] == 'kapandı'
        assert ws_try(a, '/ws/tools/ftp?id=x', headers=O)[0] == 'kapandı'
        assert 'kapalı' in denied('93.184.216.34', 22, 1, 'sqlmaster')     # süren oturum yeni bağlantı açamaz
        ok(a.get('/api/tools/notepad/store'))
    finally:
        config.DISABLED_APPS = old


# --- SQLite --------------------------------------------------------------------------------------------------------------
def sql_run(a, sid, sql):
    ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'r1', 'req': {'sql': sql}}, headers=O))
    evs = ok(a.get('/api/tools/sql/db/events', params={'sid': sid, 'since': 0}))['events']
    return [e['data']['ev'] for e in evs if e['ch'] == 'db:event']


def test_sqlite():
    a = client(ALI)
    st = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'name': 'yerel', 'filePath': '/test.db', 'readOnly': False}}, headers=O))
    cid = st['id']
    r = ok(a.post('/api/tools/sql/cw/connect', json={'id': cid}, headers=O))
    assert r['ok'], r
    sid = r['sid']
    evs = sql_run(a, sid, "create table t(x); insert into t values (1),(2),(3); select sum(x) as s from t;")
    assert any(e['type'] == 'rows' and e['rows'] == [[6]] for e in evs), evs
    assert (quota.tools_common.TOOLS_DIR / 'sqlmaster' / '1' / 'files' / 'test.db').is_file()
    kids = ok(a.post('/api/tools/sql/db/children', json={'sid': sid, 'node': None}, headers=O))
    assert kids[0]['detail'] == '/test.db', kids                                     # sunucu yolu arayüze gitmez
    out = Path(D) / 'kacis.db'
    for q, word in ((f"ATTACH '{out}' AS k", 'authoriz'), (f"VACUUM INTO '{out}'", 'authoriz'), ("select load_extension('/tmp/x.so')", 'authoriz'),
                    ('create temp table q(x)', 'authoriz'), ('pragma max_page_count = 999999999', 'authoriz'), ("pragma writable_schema = 1", 'authoriz')):
        ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'q', 'req': {'sql': q}}, headers=O))
        evs = ok(a.get('/api/tools/sql/db/events', params={'sid': sid, 'since': 0}))['events']
        errs = [e['data']['ev'] for e in evs if e['ch'] == 'db:event' and e['data']['ev']['type'] == 'error']
        assert errs and word in errs[-1]['message'].lower(), (q, errs[-1:] if errs else evs[-3:])
    assert not out.exists()
    # Sayfa tavanı = kalan alan kotası (3 MB): büyük ekleme "dolu" hatası
    ok(a.post('/api/tools/sql/db/execute', json={'sid': sid, 'runId': 'big', 'req': {'sql': 'create table b(x); insert into b select randomblob(1000000) from (select 1 union select 2 union select 3 union select 4 union select 5)'}}, headers=O))
    evs = ok(a.get('/api/tools/sql/db/events', params={'sid': sid, 'since': 0}))['events']
    msgs = [e['data']['ev'].get('message', '') for e in evs if e['ch'] == 'db:event' and e['data']['ev']['type'] == 'error']
    assert any('full' in m for m in msgs), msgs
    # Süre sınırı (sunucu CPU'su)
    old = config.SQL_TIMEOUT_S
    config.SQL_TIMEOUT_S = 1
    try:
        r2 = ok(a.post('/api/tools/sql/cw/connect', json={'id': cid}, headers=O))
        t0 = time.time()
        ok(a.post('/api/tools/sql/db/execute', json={'sid': r2['sid'], 'runId': 'loop', 'req': {'sql': 'with recursive c(i) as (select 1 union all select i+1 from c) select count(*) from c'}}, headers=O))
        assert time.time() - t0 < 10
        evs = ok(a.get('/api/tools/sql/db/events', params={'sid': r2['sid'], 'since': 0}))['events']
        assert any(e['data']['ev']['type'] == 'error' and 'interrupt' in e['data']['ev']['message'] for e in evs if e['ch'] == 'db:event'), evs[-3:]
        ok(a.post('/api/tools/sql/cw/close', json={'sid': r2['sid']}, headers=O))
    finally:
        config.SQL_TIMEOUT_S = old
    ok(a.post('/api/tools/sql/cw/close', json={'sid': sid}, headers=O))
    # caymaz.db / mtweb.db istisnası kapalı: ad kullanıcının alanındaki sıradan dosyadır (mtweb.db'ye erişim yok)
    for name in ('caymaz.db', 'mtweb.db', str(config.DB_PATH)):
        st = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'name': name, 'filePath': name, 'readOnly': True}}, headers=O))
        r = ok(a.post('/api/tools/sql/cw/connect', json={'id': st['id']}, headers=O))
        assert r['ok'] is False and 'bulunamadı' in r['message'], (name, r)
    st = ok(a.post('/api/tools/sql/conn/save', json={'form': {'provider': 'sqlite', 'name': 'm', 'filePath': 'mtweb.db', 'readOnly': False}}, headers=O))
    r = ok(a.post('/api/tools/sql/cw/connect', json={'id': st['id']}, headers=O))
    evs = sql_run(a, r['sid'], 'select count(*) from mtweb_audit')
    assert any(e['type'] == 'error' and 'no such table' in e['message'] for e in evs), evs
    ok(a.post('/api/tools/sql/cw/close', json={'sid': r['sid']}, headers=O))
    # Satır tavanı
    assert tools_sql.ROW_LIMIT_MAX == config.SQL_ROW_LIMIT and tools_sql.EXPORT_MAX == config.UPLOAD_BYTES
    assert guard.open_sessions() == 0, guard._sessions


# --- 5. Parolalar ---------------------------------------------------------------------------------------------------------
def test_secrets():
    a = client(ALI)
    r = ok(a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'conn:save', 'a': {'name': 's', 'host': 'ornek.example', 'port': 22, 'username': 'u', 'password': 'COKGIZLI-PAROLA'}}, headers=O))
    assert 'COKGIZLI' not in json.dumps(r) and r['store']['connections'][0]['hasPassword'] is True
    con = sqlite3.connect(Path(D) / 'mtweb.db')
    raw = ' '.join(x[0] for x in con.execute("SELECT json FROM tools_mt_store"))
    assert 'COKGIZLI' not in raw and '"password": "enc:' in raw
    key = quota.tools_common.TOOLS_DIR / 'mt_secret.key'
    assert key.is_file() and (key.stat().st_mode & 0o777) == 0o600
    boot = ok(a.get('/api/tools/mt/sshmaster/boot'))
    assert 'COKGIZLI' not in json.dumps(boot) and 'password' not in boot['store']['connections'][0]
    assert tools_ssh.known_hosts_path(1) != tools_ssh.known_hosts_path(2) and tools_ssh.known_hosts_path(1).parent.name == 'ssh_known_hosts.d'


# --- Uçtan uca: SSH (WebSocket) + SFTP + kota, FTP Masters WS listesi --------------------------------------------------
def test_ssh_e2e(root):
    srv = SshServer(root).start()
    a = client(ALI)
    try:
        with private():
            r = ok(a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'conn:save', 'a': {'name': 'yerel', 'host': '127.0.0.1', 'port': srv.port, 'username': 'test', 'password': 'parola'}}, headers=O))
            cid = r['v']
            t = ok(a.post('/api/tools/mt/sshmaster/invoke', json={'m': 'conn:test', 'a': {'id': cid, 'host': '127.0.0.1', 'port': srv.port, 'username': 'test'}}, headers=O))
            assert t['v']['ok'] and t['v']['fingerprint'], t
            with a.websocket_connect('/ws/tools/ssh', headers=O) as ws:
                def call(i, m, arg):
                    ws.send_text(json.dumps({'t': 'call', 'id': i, 'm': m, 'a': arg}))
                    while True:
                        msg = ws.receive()
                        if msg.get('text'):
                            o = json.loads(msg['text'])
                            if o.get('t') == 'ret' and o['id'] == i:
                                return o
                started = call(1, 'ssh:start', {'pane': 'p1', 'connId': cid, 'cols': 80, 'rows': 24})
                assert started['ok'] and started['v']['ok'], started
                ws.send_bytes(bytes([2]) + b'p1' + b'echo mtweb-merhaba\r')
                got = b''
                deadline = time.time() + 10
                while b'mtweb-merhaba\r\n$' not in got and time.time() < deadline:
                    msg = ws.receive()
                    if msg.get('bytes'):
                        got += msg['bytes'][3:]
                assert b'mtweb-merhaba\r\n$' in got, got
                lst = call(2, 'sftp:list', {'pane': 'p1', 'dir': '/'})
                assert 'merhaba.txt' in {e['name'] for e in lst['v']}, lst
                # Eşzamanlı oturum: 4 bölme açık iken 5.'si reddedilir
                for i in range(2, 5):
                    assert call(10 + i, 'ssh:start', {'pane': f'p{i}', 'connId': cid})['v']['ok']
                fifth = call(20, 'ssh:start', {'pane': 'p5', 'connId': cid})
                assert fifth['v']['ok'] is False and 'en çok 4' in str(fifth['v']['message']), fifth
                # SFTP indirme: H:\ alanına iner; alan kotası aşılırsa yarıda kalır
                d = call(30, 'sftp:download', {'pane': 'p1', 'id': 't1', 'remotePath': '/merhaba.txt', 'localDir': 'H:\\'})
                assert d['v']['ok'], d
                assert (quota.tools_common.TOOLS_DIR / 'files' / '1' / 'merhaba.txt').read_text() == 'selam\n'
                (Path(root) / 'buyuk.bin').write_bytes(os.urandom(4 * config.MB))
                d = call(31, 'sftp:download', {'pane': 'p1', 'id': 't2', 'remotePath': '/buyuk.bin', 'localDir': 'H:\\'})
                assert d['v']['ok'] is False and 'alan' in str(d['v']['message']).lower(), d
                assert not (quota.tools_common.TOOLS_DIR / 'files' / '1' / 'buyuk.bin').exists()
                # Kötü ad ile kaçış yok
                d = call(32, 'sftp:download', {'pane': 'p1', 'id': 't3', 'remotePath': '/..', 'localDir': 'H:\\'})
                assert d['ok'] is False or d['v']['ok'] is False, d
            for _ in range(100):   # WS kapanınca oturumlar kapanış iş parçacığında bırakılır (eşzamansız; ≤ 10 sn)
                if guard.open_sessions(1, 'sshmaster') == 0:
                    break
                time.sleep(0.1)
            assert guard.open_sessions(1, 'sshmaster') == 0, guard._sessions     # WS kapanınca oturumlar bırakılır
            assert tools_ssh.known_hosts_path(1).read_text().strip()               # kullanıcının known_hosts'u
            assert not ('agent',) in srv.log and not any(x[0] in ('port-forward', 'x11', 'direct-tcpip') for x in srv.log), srv.log
            # FTP Masters (SFTP protokolü) WebSocket: site:open + list
            r = ok(a.post('/api/tools/mt/ftpmaster/invoke', json={'m': 'conn:save', 'a': {'name': 'sftp', 'protocol': 'sftp', 'host': '127.0.0.1', 'port': srv.port, 'username': 'test', 'password': 'parola'}}, headers=O))
            fid = r['v']
            with a.websocket_connect(f'/ws/tools/ftp?id={fid}', headers=O) as ws:
                rets = {}

                def fcall(i, m, arg):
                    ws.send_text(json.dumps({'t': 'call', 'id': i, 'm': m, 'a': arg}))
                    while i not in rets:
                        o = json.loads(ws.receive_text())
                        if o.get('t') == 'ret':
                            rets[o['id']] = o
                    return rets[i]
                fcall(1, 'site:open', None)
                fcall(2, 'site:list', {'dir': '/'})
                assert rets[1]['v']['ok'], rets
                assert 'merhaba.txt' in {e['name'] for e in rets[2]['v']}, rets
                # İstemciden gelen kötü ad (../) yerel alandan kaçamaz
                ws.send_text(json.dumps({'t': 'call', 'id': 3, 'm': 'site:download', 'a': {'items': [{'path': '/merhaba.txt', 'name': '../../2/kacis.txt'}], 'localDir': 'H:\\'}}))
                while True:
                    o = json.loads(ws.receive_text())
                    if o.get('t') == 'ret' and o['id'] == 3:
                        break
                assert o['ok'] is False and 'Geçersiz dosya adı' in str(o['e']), o
    finally:
        srv.stop()
    con = sqlite3.connect(Path(D) / 'mtweb.db')
    rows = con.execute("SELECT user_id, app, host, rip, port, result, ip FROM mtweb_audit WHERE action = 'net' AND result = 'ok' AND app = 'sshmaster' AND port = ?", (srv.port,)).fetchall()
    assert rows and all(r[0] == 1 and r[2] == '127.0.0.1' and r[3] == '127.0.0.1' and r[4] == srv.port and r[6] for r in rows), rows


def test_audit():
    con = sqlite3.connect(Path(D) / 'mtweb.db')
    rows = con.execute("SELECT user_id, app, action, host, rip, port, result, ip, detail FROM mtweb_audit WHERE action = 'net'").fetchall()
    res = {r[6].split(':')[0] for r in rows}
    assert {'ok', 'denied', 'dns'} <= res, res
    assert any(r[6] == 'denied:private' and r[3] == '10.0.0.7' and r[1] == 'sshmaster' for r in rows), rows[:5]
    assert any(r[6] == 'denied:port' and r[5] == 25 for r in rows)
    blob = json.dumps(con.execute('SELECT * FROM mtweb_audit').fetchall())
    for secret in ('COKGIZLI', 'parola', 'mtweb-merhaba', 'select sum', 'randomblob'):
        assert secret not in blob, secret


def test_hepgo_off():
    """HEPGO sürecinde kancalar kapalı: özel adrese bağlanılabilir (firmalar LAN cihazlarına bağlanıyor)."""
    code = ("from app.routers import tools_common as tc, tools_ssh, tools_sql, tools_ftp, tools_notepad\n"
            "assert tc.NET_GUARD is None and tc.CONN_GATE is None and tc.WS_USER is None\n"
            "assert tc.net_target('10.0.0.5', 22) == '10.0.0.5' and tc.net_socket('10.0.0.5', 22, 1) is None\n"
            "assert tc.conn_slot(1, 'sshmaster')() is None\n"
            "assert tools_sql.APP_DB_READONLY and tools_sql.ALLOW_SSH_AGENT and tools_sql.SQLITE_GUARD is None and tools_ftp.POOL_MAX == 20\n"
            "assert tools_ssh.KNOWN_HOSTS is None and tools_ssh.known_hosts_path().name == 'ssh_known_hosts'\n"
            "assert tools_notepad.ALLOW_REMOTE is True\n"
            "import ftplib; c = ftplib.FTP(); assert tools_ftp.harden_ftp(c, 1, 'ftpmaster') is c and 'makepasv' not in c.__dict__\n"
            "print('hepgo-ok')\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MTWEB_', 'CAYMAZ_'))}
    env['CAYMAZ_DATA_DIR'] = tempfile.mkdtemp(prefix='hepgo-off-')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, cwd=str(Path(__file__).resolve().parent.parent), timeout=120)
    assert 'hepgo-ok' in out.stdout, out.stderr[-2000:]


def main():
    root = Path(tempfile.mkdtemp(prefix='mtweb-uzak-'))
    (root / 'merhaba.txt').write_text('selam\n')
    (root / 'klasor').mkdir()
    client(ALI)
    test_hepgo_off()
    test_ssrf()
    test_connect_paths()
    test_ftp_pasv(root)
    test_ws()
    test_limits()
    test_disabled()
    test_sqlite()
    test_secrets()
    test_ssh_e2e(root)
    test_audit()
    print('mtweb ağ testleri geçti.')


if __name__ == '__main__':
    main()
