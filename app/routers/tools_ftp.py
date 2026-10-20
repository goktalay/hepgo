"""Araçlar › FTP Masters (web) — FTP / FTPS (ftplib) ve SFTP (paramiko) arka ucu.

Masaüstü main.js + remote.js + session.js + throttle.js mantığının Python karşılığı:
  - Remote (FtpRemote / SftpRemote): connect, list, pwd, stat, exists, mkdir, rename, removeFile, removeDir, download, upload, close
  - Session: gezinme bağlantısı (sıralı), aktarım bağlantı havuzu (FTP: site başına "aynı anda en fazla" kadar bağlantı;
    SFTP: aynı SSH üzerinde ayrı SFTP kanalları), aktarım ağacı (kök → klasör → dosya; ~8 kez/sn toplu güncelleme),
    yeniden deneme, aynı adlı hedef kuralı (üzerine yaz / yeniden adlandır / atla), iptal / yeniden dene / temizle.
  - Limiter: kullanıcı başına global hız sınırı (KB/sn), 16 KB dilimlerle.
WebSocket /ws/tools/ftp?id=<site>: bir bağlantı = bir site penceresi. Çağrılar/olaylar preload.js kanal adlarıyla aynı:
  site:open/list/stat/mkdir/rename/delete/download/upload (call), site:lastDir, transfer:cancel/cancelAll/retry (send),
  transfer:clear (call); olaylar session:status, transfer:update {added, changed}, transfer:rootDone.
Yerel taraf kullanıcının HEPGO kişisel alanıdır (H:\\ → DATA_DIR/tools/files/<uid>).
"""
import asyncio
import ftplib
import json
import posixpath
import re
import secrets
import socket
import ssl
import stat as st_mod
import threading
import time
from datetime import datetime
from pathlib import Path

import paramiko
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from . import tools_common as tc
from . import tools_mt
from .tools_common import tools_user, ws_user
from .tools_mt import T, MtError

router = APIRouter(prefix='/api/tools/ftp')
ws_router = APIRouter()
APP = 'ftpmaster'

PROTOCOLS = {'ftp': {'port': 21}, 'ftps-implicit': {'port': 990}, 'ftps-ssl': {'port': 21}, 'ftps-tls': {'port': 21}, 'sftp': {'port': 22}}
TEXT_EXT = {'txt', 'htm', 'html', 'css', 'js', 'json', 'xml', 'php', 'asp', 'aspx', 'csv', 'ini', 'conf', 'cfg', 'md', 'sh', 'pl', 'py', 'sql', 'svg', 'htaccess', 'log'}
FINISHED = ('done', 'error', 'cancelled', 'skipped')
CHUNK = 64 * 1024
SLICE = 16 * 1024
POOL_MAX = 20   # mtweb kancası: site başına aktarım bağlantısı tavanı (HEPGO: 20)


@router.get('/caps')
def caps(user=Depends(tools_user)):
    return {'ftp': True, 'ftps': True, 'sftp': True, 'sftp_note': None, 'paramiko': paramiko.__version__}


# ---------------------------------------------------------------------------
# Hız sınırı (throttle.js): kullanıcı başına, tüm pencerelerdeki aktarımlar paylaşır
# ---------------------------------------------------------------------------
class Limiter:
    def __init__(self):
        self.bytes_per_sec = 0
        self.next_free = 0.0
        self.lock = threading.Lock()

    def set(self, kbps):
        self.bytes_per_sec = kbps * 1024 if kbps > 0 else 0
        self.next_free = 0.0

    def take(self, n):
        """n bayt için beklenecek süre (sn); boşta kalınmışsa en fazla 250 ms birikmiş hak."""
        if not self.bytes_per_sec:
            return 0.0
        with self.lock:
            now = time.time()
            start = max(now - 0.25, self.next_free)
            self.next_free = start + n / self.bytes_per_sec
            return max(0.0, start - now)


_limiters = {}


def limiter(uid) -> Limiter:
    if uid not in _limiters:
        _limiters[uid] = Limiter()
    return _limiters[uid]


def apply_speed_limit(uid, settings):
    try:
        kb = max(1, int(settings.get('speedLimitKB') or 0))
    except (TypeError, ValueError):
        kb = 1024
    limiter(uid).set(kb if settings.get('speedLimitOn') else 0)


def metered(uid, on_bytes, ctl, chunk: bytes):
    """Meter: parçayı dilimleyip hız sınırına göre bekletir; iptal edildiyse Cancelled."""
    lim = limiter(uid)
    if not lim.bytes_per_sec:
        on_bytes(len(chunk))
        yield chunk
        return
    for i in range(0, len(chunk), SLICE):
        if ctl.get('cancelled'):
            raise Cancelled()
        part = chunk[i:i + SLICE]
        wait = lim.take(len(part))
        if wait > 0:
            time.sleep(wait)
        on_bytes(len(part))
        yield part


class Cancelled(Exception):
    pass


def use_ascii(mode, name):
    if mode == 'ascii':
        return True
    if mode != 'auto':
        return False
    return (name.rsplit('.', 1)[-1] if '.' in name else '').lower() in TEXT_EXT


def credentials(conn):
    if conn.get('loginMethod') == 'anonymous':
        return 'anonymous', conn.get('password') or 'anonymous@'
    return str(conn.get('username') or '').strip(), conn.get('password') or ''


# ---------------------------------------------------------------------------
# FTP / FTPS (ftplib)
# ---------------------------------------------------------------------------
def _tls_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # sunucu sertifikaları çoğunlukla kendinden imzalıdır (FileZilla/CuteFTP gibi kabul)
    return ctx


class _ImplicitTLS(ftplib.FTP_TLS):
    """Örtük FTPS (990): kontrol soketi daha ilk bayttan TLS."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value


class _AuthSSL(ftplib.FTP_TLS):
    """AUTH SSL ile açık FTPS (eski sunucular)."""
    def auth(self):
        if isinstance(self.sock, ssl.SSLSocket):
            raise ValueError('Already using TLS')
        resp = self.voidcmd('AUTH SSL')
        self.sock = self.context.wrap_socket(self.sock)
        self.file = self.sock.makefile(mode='r', encoding=self.encoding)
        return resp


UNIX_RE = re.compile(r'^([\-dlcbps])[rwxsStT\-+@.]{9,10}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\w{3}\s+\d{1,2}\s+(?:\d{4}|\d{1,2}:\d{2}))\s+(.+)$')
UNIX_RE2 = re.compile(r'^([\-dlcbps])[rwxsStT\-+@.]{9,10}\s+\d+\s+\S+\s+(\d+)\s+(\w{3}\s+\d{1,2}\s+(?:\d{4}|\d{1,2}:\d{2}))\s+(.+)$')
DOS_RE = re.compile(r'^(\d{2}-\d{2}-\d{2,4})\s+(\d{2}:\d{2}(?:[AP]M)?)\s+(<DIR>|\d+)\s+(.+)$')


def _unix_time(s):
    now = datetime.now()
    for fmt in ('%b %d %Y', '%b %d %H:%M'):
        try:
            d = datetime.strptime(s, fmt)
            if fmt.endswith('%H:%M'):
                d = d.replace(year=now.year)
                if d > now:
                    d = d.replace(year=now.year - 1)
            return int(d.timestamp() * 1000)
        except ValueError:
            continue
    return 0


def parse_list_line(line):
    """LIST satırı → {name, isDir, isLink, size, mtime, raw} (UNIX ve DOS biçimleri)."""
    m = UNIX_RE.match(line) or UNIX_RE2.match(line)
    if m:
        kind, size, when, name = m.groups()
        if kind == 'l' and ' -> ' in name:
            name = name.split(' -> ')[0]
        return {'name': name, 'isDir': kind == 'd', 'isLink': kind == 'l', 'size': int(size), 'mtime': _unix_time(when), 'raw': when}
    m = DOS_RE.match(line)
    if m:
        date, clock, size, name = m.groups()
        mtime = 0
        for fmt in ('%m-%d-%y %I:%M%p', '%m-%d-%Y %I:%M%p', '%m-%d-%y %H:%M', '%m-%d-%Y %H:%M'):
            try:
                mtime = int(datetime.strptime(f'{date} {clock}', fmt).timestamp() * 1000)
                break
            except ValueError:
                continue
        return {'name': name, 'isDir': size == '<DIR>', 'isLink': False, 'size': 0 if size == '<DIR>' else int(size), 'mtime': mtime, 'raw': f'{date} {clock}'}
    return None


def _mlsd_time(v):
    try:
        return int(datetime.strptime(v[:14], '%Y%m%d%H%M%S').replace(tzinfo=None).timestamp() * 1000)
    except ValueError:
        return 0


def harden_ftp(c, uid, app):
    """mtweb (NET kancası varken): veri kanalı yalnız kontrol bağlantısının IP'sine (PASV yanıtındaki IP yok sayılır,
    port engel listesinden geçer); aktif kip (PORT/EPRT) kapalı. HEPGO'da dokunulmaz."""
    if tc.NET_GUARD is None:
        return c
    c.trust_server_pasv_ipv4_address = False
    orig = c.makepasv

    def makepasv():
        _, port = orig()
        peer = c.sock.getpeername()[0]
        tc.net_target(peer, port, uid, app, 'data')
        return peer, port

    def makeport():
        raise tc.NetDenied('Aktif FTP kipi (PORT) web sürümünde kapalı')
    c.makepasv = makepasv
    c.makeport = makeport
    return c


class FtpRemote:
    parallel = False
    fingerprint = None

    def __init__(self, conn, uid):
        self.conn, self.uid = conn, uid
        self.client = None

    @property
    def closed(self):
        return self.client is None or self.client.sock is None

    def connect(self):
        conn = self.conn
        host = str(conn.get('host') or '').strip()
        proto = conn.get('protocol') or 'ftp'
        port = int(conn.get('port') or PROTOCOLS[proto]['port'])
        enc = 'latin-1' if conn.get('encoding') == 'ascii' else 'utf-8'
        if proto == 'ftps-implicit':
            c = _ImplicitTLS(context=_tls_context(), timeout=30, encoding=enc)
        elif proto == 'ftps-ssl':
            c = _AuthSSL(context=_tls_context(), timeout=30, encoding=enc)
        elif proto == 'ftps-tls':
            c = ftplib.FTP_TLS(context=_tls_context(), timeout=30, encoding=enc)
        else:
            c = ftplib.FTP(timeout=30, encoding=enc)
        try:
            harden_ftp(c, self.uid, APP)
            c.connect(tc.net_target(host, port, self.uid, APP), port)
            if proto in ('ftps-ssl', 'ftps-tls'):
                c.auth()
            if proto != 'ftp':
                c.prot_p()
            user, password = credentials(conn)
            c.login(user, password)
            c.set_pasv(True)
            if conn.get('encoding') == 'ascii':
                try:
                    c.sendcmd('OPTS UTF8 OFF')
                except ftplib.all_errors:
                    pass
            else:
                try:
                    c.sendcmd('OPTS UTF8 ON')
                except ftplib.all_errors:
                    pass
        except BaseException:
            try:
                c.close()
            except Exception:   # noqa: BLE001
                pass
            raise
        self.client = c
        return self

    def info(self):
        try:
            return re.sub(r'^\d+\s*', '', self.client.sendcmd('SYST')).strip()
        except ftplib.all_errors:
            return ''

    def pwd(self):
        return self.client.pwd()

    def noop(self):
        return self.client.voidcmd('NOOP')

    def list(self, d):
        tz = int(self.conn.get('timezone') or 0)
        out = []
        try:
            for name, facts in self.client.mlsd(d, facts=['type', 'size', 'modify']):
                if name in ('.', '..') or facts.get('type') in ('cdir', 'pdir'):
                    continue
                tp = facts.get('type', 'file')
                mt = _mlsd_time(facts['modify']) if facts.get('modify') else 0
                out.append({'name': name, 'path': posixpath.join(d, name), 'isDir': tp == 'dir', 'isLink': tp.startswith('OS.unix=slink'),
                            'size': int(facts['size']) if str(facts.get('size', '')).isdigit() else 0,
                            'mtime': mt + tz * 3600000 if mt else 0, 'raw': facts.get('modify', '')})
            return out
        except ftplib.error_perm:
            pass
        lines = []
        self.client.retrlines(f'LIST {d}', lines.append)
        for ln in lines:
            e = parse_list_line(ln)
            if e and e['name'] not in ('.', '..'):
                e['path'] = posixpath.join(d, e['name'])
                if e['mtime']:
                    e['mtime'] += tz * 3600000
                out.append(e)
        return out

    def stat(self, p):
        try:
            self.client.voidcmd('TYPE I')
            return {'isDir': False, 'size': self.client.size(p) or 0}
        except ftplib.all_errors:
            cwd = self.client.pwd()   # SIZE klasörlerde başarısız olur; klasöre girmeyi deneyerek ayırt et
            self.client.cwd(p)
            self.client.cwd(cwd)
            return {'isDir': True, 'size': 0}

    def exists(self, p):
        try:
            self.stat(p)
            return True
        except ftplib.all_errors:
            return False

    def mkdir(self, p):
        self.client.mkd(p)

    def rename(self, a, b):
        self.client.rename(a, b)

    def remove_file(self, p):
        self.client.delete(p)

    def remove_dir(self, p):
        for e in self.list(p):
            if e['isDir'] and not e['isLink']:
                self.remove_dir(e['path'])
            else:
                self.client.delete(e['path'])
        self.client.rmd(p)

    def _finish_data(self, conn):
        try:
            if isinstance(conn, ssl.SSLSocket):
                conn.unwrap()
        except Exception:   # noqa: BLE001
            pass
        conn.close()
        self.client.voidresp()

    def download(self, remote, local: Path, on_bytes, ctl, opts):
        c = self.client
        ctl['abort'] = c.close
        ascii_mode = use_ascii(opts.get('transferType'), posixpath.basename(remote))
        c.voidcmd('TYPE A' if ascii_mode else 'TYPE I')
        conn, _ = c.ntransfercmd(f'RETR {remote}')
        try:
            with open(local, 'wb') as f:
                while True:
                    data = conn.recv(CHUNK)
                    if not data:
                        break
                    for part in metered(self.uid, on_bytes, ctl, data):
                        f.write(part)
            self._finish_data(conn)
        finally:
            if ascii_mode and not self.closed:
                try:
                    c.voidcmd('TYPE I')
                except ftplib.all_errors:
                    pass

    def upload(self, local: Path, remote, on_bytes, ctl, opts):
        c = self.client
        ctl['abort'] = c.close
        ascii_mode = use_ascii(opts.get('transferType'), posixpath.basename(remote))
        c.voidcmd('TYPE A' if ascii_mode else 'TYPE I')
        conn, _ = c.ntransfercmd(f'STOR {remote}')
        try:
            with open(local, 'rb') as f:
                while True:
                    data = f.read(CHUNK)
                    if not data:
                        break
                    for part in metered(self.uid, on_bytes, ctl, data):
                        conn.sendall(part)
            self._finish_data(conn)
        finally:
            if ascii_mode and not self.closed:
                try:
                    c.voidcmd('TYPE I')
                except ftplib.all_errors:
                    pass

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:   # noqa: BLE001
                pass
            self.client = None


# ---------------------------------------------------------------------------
# SFTP (paramiko) — tek SSH bağlantısı; her aktarım aynı bağlantıda kendi SFTP kanalını açar
# ---------------------------------------------------------------------------
class SftpRemote:
    parallel = True

    def __init__(self, conn, uid, ssh=None):
        self.conn, self.uid = conn, uid
        self.ssh = ssh
        self.sftp = None
        self.fingerprint = None
        self.owner = ssh is None   # SSH bağlantısının sahibi ana (gezinme) nesnedir

    @property
    def closed(self):
        t = self.ssh.get_transport() if self.ssh else None
        return not (t and t.is_active()) or self.sftp is None or self.sftp.sock.closed

    def connect(self):
        from . import tools_ssh
        if self.ssh is None:
            user, password = credentials(self.conn)
            c = {**self.conn, 'username': user, 'password': password}
            self.ssh, self.fingerprint = tools_ssh.connect_client(self.uid, c, app=APP)
        self.sftp = self.ssh.open_sftp()
        return self

    def spawn(self):
        """Aynı SSH üzerinde yeni SFTP kanalı (aktarım havuzu için)."""
        r = SftpRemote(self.conn, self.uid, self.ssh)
        r.fingerprint = self.fingerprint
        return r.connect()

    def info(self):
        try:
            _, out, _ = self.ssh.exec_command('uname -sr 2>/dev/null; hostname 2>/dev/null', timeout=10)
            return ' · '.join(x for x in out.read().decode('utf-8', 'replace').strip().split('\n') if x)
        except Exception:   # noqa: BLE001
            return ''

    def pwd(self):
        return self.sftp.normalize('.')

    def noop(self):
        return self.sftp.normalize('.')

    def list(self, d):
        out = []
        for e in self.sftp.listdir_attr(d):
            mode = e.st_mode or 0
            out.append({'name': e.filename, 'path': posixpath.join(d, e.filename), 'isDir': st_mod.S_ISDIR(mode), 'isLink': st_mod.S_ISLNK(mode),
                        'size': e.st_size or 0, 'mtime': int((e.st_mtime or 0) * 1000), 'raw': ''})
        for e in out:   # sembolik bağlantıların klasör olup olmadığını öğren
            if e['isLink']:
                try:
                    e['isDir'] = st_mod.S_ISDIR(self.sftp.stat(e['path']).st_mode or 0)
                except OSError:
                    pass
        return out

    def stat(self, p):
        st = self.sftp.stat(p)
        return {'isDir': st_mod.S_ISDIR(st.st_mode or 0), 'size': st.st_size or 0}

    def exists(self, p):
        try:
            self.sftp.stat(p)
            return True
        except OSError:
            return False

    def mkdir(self, p):
        self.sftp.mkdir(p)

    def rename(self, a, b):
        self.sftp.rename(a, b)

    def remove_file(self, p):
        self.sftp.remove(p)

    def remove_dir(self, p):
        for e in self.list(p):
            if e['isDir'] and not e['isLink']:
                self.remove_dir(e['path'])
            else:
                self.sftp.remove(e['path'])
        self.sftp.rmdir(p)

    def download(self, remote, local: Path, on_bytes, ctl, opts):
        ctl['abort'] = lambda: self.sftp.close()
        with self.sftp.open(remote, 'rb') as rf:
            rf.prefetch(rf.stat().st_size)
            with open(local, 'wb') as f:
                while True:
                    data = rf.read(CHUNK)
                    if not data:
                        break
                    for part in metered(self.uid, on_bytes, ctl, data):
                        f.write(part)

    def upload(self, local: Path, remote, on_bytes, ctl, opts):
        ctl['abort'] = lambda: self.sftp.close()
        with open(local, 'rb') as f, self.sftp.open(remote, 'wb') as wf:
            wf.set_pipelined(True)
            while True:
                data = f.read(CHUNK)
                if not data:
                    break
                for part in metered(self.uid, on_bytes, ctl, data):
                    wf.write(part)

    def close(self):
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:   # noqa: BLE001
            pass
        self.sftp = None
        if self.owner and self.ssh:
            try:
                self.ssh.close()
            except Exception:   # noqa: BLE001
                pass


def create_remote(conn, uid):
    return SftpRemote(conn, uid) if conn.get('protocol') == 'sftp' else FtpRemote(conn, uid)


def _ftp_code(err):
    m = re.match(r'^\s*(\d{3})', str(err))
    return int(m.group(1)) if m else None


def friendly_error(err):
    """Sunucu hatalarını kullanıcı dostu metne (renderer i18n anahtarına) çevirir — remote.js friendlyError."""
    from . import tools_ssh
    if isinstance(err, Cancelled):
        return 'cancelled'
    msg = str(err) or err.__class__.__name__
    if isinstance(err, tc.NetDenied):
        return msg
    code = _ftp_code(err) if isinstance(err, ftplib.Error) else None
    if isinstance(err, tools_ssh.HostKeyMismatch):
        return T('main.errHostKey', old=err.old, new=err.new)
    if isinstance(err, paramiko.BadHostKeyException):
        return T('main.errHostKey', old=tools_ssh.fingerprint(err.expected_key), new=tools_ssh.fingerprint(err.key))
    if isinstance(err, paramiko.AuthenticationException) or code == 530 or 'Login incorrect' in msg:
        return T('main.errAuth')
    if code == 550:
        return T('main.err550', msg=re.sub(r'^550\s*', '', msg))
    if code == 553:
        return T('main.err553')
    if isinstance(err, paramiko.ssh_exception.NoValidConnectionsError):
        inner = list(err.errors.values())
        return friendly_error(inner[0]) if inner else T('main.errRefused')
    if isinstance(err, socket.gaierror) or 'getaddrinfo' in msg or 'Name or service not known' in msg:
        return T('main.errDns')
    if isinstance(err, ConnectionRefusedError) or 'refused' in msg.lower():
        return T('main.errRefused')
    if isinstance(err, (socket.timeout, TimeoutError)) or 'timed out' in msg.lower() or 'Timeout' in msg:
        return T('main.errTimeout')
    if 'unreachable' in msg.lower():
        return T('main.errUnreach')
    if isinstance(err, (ConnectionResetError, BrokenPipeError, EOFError)) or 'Client is closed' in msg or 'closed by the server' in msg or 'Socket is closed' in msg:
        return T('main.errReset')
    if isinstance(err, FileNotFoundError) or 'No such file' in msg:
        return T('main.errNotFound')
    if isinstance(err, PermissionError) or 'Permission denied' in msg:
        return T('main.errPerm')
    if isinstance(err, ssl.SSLError) or 'wrong version number' in msg or 'certificate' in msg.lower():
        return T('main.errTls', msg=msg)
    return msg


def test_connection(uid, store, form):
    conn = tools_mt.merge_form_with_stored(store, form, same_host_only=True)
    if not conn.get('host'):
        return {'ok': False, 'message': T('main.errHost')}
    if conn.get('loginMethod') != 'anonymous' and not conn.get('username'):
        return {'ok': False, 'message': T('main.errUser')}
    started = time.time()
    remote = None
    try:
        remote = create_remote(conn, uid)
        remote.connect()
        ms = int((time.time() - started) * 1000)
        info = home = ''
        try:
            info = remote.info()
        except Exception:   # noqa: BLE001
            pass
        try:
            home = remote.pwd()
        except Exception:   # noqa: BLE001
            pass
        remote_dir_ok = True
        if conn.get('remoteDir'):
            try:
                remote.list(conn['remoteDir'])
            except Exception:   # noqa: BLE001
                remote_dir_ok = False
        return {'ok': True, 'ms': ms, 'info': info, 'home': home, 'remoteDirOk': remote_dir_ok, 'fingerprint': remote.fingerprint,
                'firstTime': bool(remote.fingerprint) and not conn.get('hostKey')}
    except Exception as e:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(e)}
    finally:
        if remote:
            remote.close()


# ---------------------------------------------------------------------------
# Site oturumu (session.js)
# ---------------------------------------------------------------------------
_global_cache = {}   # (uid, connId) → {dir: list}  ("Her zaman önbellek kullan")


def unique_remote_path(remote, p):
    d, base = posixpath.split(p)
    stem, ext = posixpath.splitext(base)
    i = 1
    while True:
        cand = posixpath.join(d, f'{stem} ({i}){ext}')
        if not remote.exists(cand):
            return cand
        i += 1


class Session:
    def __init__(self, uid, conn, options, send, on_host_key):
        self.uid, self.conn, self.options, self.send, self.on_host_key = uid, conn, options, send, on_host_key
        self.mu = threading.RLock()
        self.browse = None
        self.browse_lock = threading.Lock()
        self.reconnecting = None
        self.cache = _global_cache.setdefault((uid, conn.get('id')), {}) if conn.get('cacheMode') == 'always' else {}
        self.idle = []
        self.workers = 0
        self.pool_cv = threading.Condition()
        self.queue = []
        self.running = 0
        self.tasks = {}
        self.nodes = {}
        self.added = []
        self.dirty = set()
        self.flush_timer = None
        self.closed = False
        self.keepalive = threading.Timer(45, self._ping_loop)
        self.keepalive.daemon = True
        self.keepalive.start()

    # --- bağlantı ---
    def open(self):
        r = create_remote(self.conn, self.uid)
        r.connect()
        if r.fingerprint and self.on_host_key:
            self.on_host_key(r.fingerprint)
        self.browse = r
        return r

    def ensure_browse(self):
        if self.browse and not self.browse.closed:
            return self.browse
        if self.closed:
            raise MtError('Client is closed')
        self.send('session:status', {'state': 'connecting'})
        try:
            r = self.open()
        except Exception:
            self.send('session:status', {'state': 'disconnected'})
            raise
        if self.closed:   # istemci bu açılış sürerken kapandı: bağlantı (ve eşzamanlı oturum yuvası) sızmasın
            try:
                r.close()
            except Exception:   # noqa: BLE001
                pass
            raise MtError('Client is closed')
        self.send('session:status', {'state': 'connected'})
        return r

    def run(self, fn):
        """Gezinme bağlantısında sıralı çağrı; bağlantı kopmuşsa bir kez yeniden bağlanıp dener."""
        with self.browse_lock:
            try:
                return fn(self.ensure_browse())
            except Exception:
                if self.browse and self.browse.closed and not self.closed:
                    return fn(self.ensure_browse())
                raise

    def _ping_loop(self):
        if self.closed:
            return
        try:
            if self.browse and not self.browse.closed:
                self.run(lambda r: r.noop())
        except Exception:   # noqa: BLE001
            pass
        self.keepalive = threading.Timer(45, self._ping_loop)
        self.keepalive.daemon = True
        self.keepalive.start()

    def list(self, d, refresh):
        if not refresh and self.conn.get('cacheMode') != 'never' and d in self.cache:
            return self.cache[d]
        lst = self.run(lambda r: r.list(d))
        if self.conn.get('cacheMode') != 'never':
            self.cache[d] = lst
        return lst

    def invalidate(self, d):
        self.cache.pop(d, None)

    # --- aktarım bağlantı havuzu ---
    def max_concurrent(self):
        try:
            return max(1, min(POOL_MAX, int(self.options().get('maxConcurrent') or 1)))
        except (TypeError, ValueError):
            return 1

    def acquire(self):
        with self.pool_cv:
            while True:
                while self.idle:
                    r = self.idle.pop()
                    if not r.closed:
                        return r
                    self.workers -= 1
                if self.workers < self.max_concurrent():
                    self.workers += 1
                    break
                self.pool_cv.wait(0.5)
                if self.closed:
                    raise Cancelled()
        try:
            if self.conn.get('protocol') == 'sftp':
                return self.run(lambda r: r.spawn())
            return create_remote(self.conn, self.uid).connect()
        except Exception:
            with self.pool_cv:
                self.workers -= 1
                self.pool_cv.notify()
            raise

    def release(self, r):
        if r is self.browse:
            return
        with self.pool_cv:
            if self.closed or r.closed:
                self._discard_locked(r)
                return
            self.idle.append(r)
            self.pool_cv.notify()

    def discard(self, r):
        if r is self.browse:
            return
        with self.pool_cv:
            self._discard_locked(r)

    def _discard_locked(self, r):
        try:
            r.close()
        except Exception:   # noqa: BLE001
            pass
        self.workers -= 1
        self.pool_cv.notify()

    # --- aktarım ağacı ---
    def add_node(self, **n):
        node = {'size': 0, 'done': 0, 'status': 'queued', 'error': None, 'files': 0, 'finished': 0, 'failed': 0, 'active': 0, 'scanning': False,
                'cancelled': False, 'parentId': None, 'rootId': None, 'speed': 0.0, 'partial': None, **n, 'id': secrets.token_hex(6)}
        with self.mu:
            self.nodes[node['id']] = node
            self.added.append(node)
        self.schedule()
        return node

    def ancestors(self, node):
        out = []
        p = self.nodes.get(node['parentId']) if node.get('parentId') else None
        while p:
            out.append(p)
            p = self.nodes.get(p['parentId']) if p.get('parentId') else None
        return out

    def touch(self, node):
        with self.mu:
            self.dirty.add(node['id'])
        self.schedule()

    def schedule(self):
        with self.mu:
            if not self.flush_timer and not self.closed:
                self.flush_timer = threading.Timer(0.12, self.flush)
                self.flush_timer.daemon = True
                self.flush_timer.start()

    def dir_status(self, d):
        if d['cancelled'] and not d['active']:
            return 'cancelled'
        if d['scanning']:
            return 'scanning'
        if d['finished'] >= d['files']:
            return 'error' if d['failed'] else 'done'
        return 'active' if d['active'] else 'queued'

    def status_of(self, n):
        return self.dir_status(n) if n['isDir'] else n['status']

    def flush(self):
        with self.mu:
            self.flush_timer = None
            if self.closed:
                return
            now = time.time()
            changed = []
            for nid in list(self.dirty):
                n = self.nodes.get(nid)
                if not n:
                    continue
                if n['isDir']:
                    n['status'] = self.dir_status(n)
                o = {'id': nid, 'size': n['size'], 'done': n['done'], 'status': n['status'], 'error': n['error'], 'files': n['files'], 'finished': n['finished']}
                if not n['parentId']:
                    dt = now - (n.get('lastT') or n.get('startT') or now)
                    if dt >= 0.4:
                        n['speed'] = (n['done'] - n.get('lastDone', 0)) / dt
                        n['lastT'] = now
                        n['lastDone'] = n['done']
                    o['speed'] = (n.get('speed') or 0) if n['status'] in ('active', 'scanning', 'queued', 'retry') else 0
                    if o['status'] != n.get('reported') and o['status'] in FINISHED:
                        n['reported'] = o['status']
                        if n['kind'] == 'upload':
                            self.invalidate(n['dstDir'])
                            for k in list(self.cache):
                                if k == n['dst'] or k.startswith(n['dst'] + '/'):
                                    self.cache.pop(k, None)
                        self.send('transfer:rootDone', {'id': nid, 'kind': n['kind'], 'status': o['status'], 'name': n['name'], 'dstDir': n['dstDir'], 'failed': n['failed']})
                changed.append(o)
            added = [{k: n.get(k) for k in ('id', 'parentId', 'rootId', 'name', 'isDir', 'kind', 'size', 'status', 'src', 'dst')} for n in self.added]
            self.added = []
            self.dirty.clear()
            self.send('transfer:update', {'added': added, 'changed': changed})
            for n in self.nodes.values():   # süren aktarım varsa hız bilgisi güncel kalsın
                if not n['parentId'] and self.status_of(n) in ('active', 'scanning', 'queued', 'retry'):
                    self.dirty.add(n['id'])
            if self.dirty:
                self.schedule()

    def register_file(self, node):
        for a in self.ancestors(node):
            a['size'] += node['size']
            a['files'] += 1
            self.touch(a)
        if not node['parentId']:
            node['files'] = 1

    def add_done(self, node, n):
        node['done'] += n
        self.touch(node)
        for a in self.ancestors(node):
            a['done'] += n
            self.touch(a)

    def set_file_status(self, node, status, error=None):
        with self.mu:
            prev = node['status']
            node['status'] = status
            node['error'] = error
            was_active, is_active = prev == 'active', status == 'active'
            finished_now = status in FINISHED and prev not in FINISHED
            reopened = status not in FINISHED and prev in ('error', 'cancelled')
            targets = self.ancestors(node) if node['parentId'] else []
            if not node['parentId']:
                node['finished'] = 1 if finished_now else 0 if reopened else node['finished']
                node['failed'] = 1 if status == 'error' else 0
            for a in targets:
                if was_active != is_active:
                    a['active'] += 1 if is_active else -1
                if finished_now:
                    a['finished'] += 1
                    if status == 'error':
                        a['failed'] += 1
                if reopened:
                    a['finished'] -= 1
                    if prev == 'error':
                        a['failed'] -= 1
                self.touch(a)
            self.touch(node)

    # --- görev kuyruğu ---
    def enqueue(self, node):
        task = {'node': node, 'ctl': {}, 'cancelled': False}
        with self.mu:
            self.tasks[node['id']] = task
            self.queue.append(task)
        self.pump()

    def pump(self):
        with self.mu:
            while not self.closed and self.running < self.max_concurrent() and self.queue:
                task = self.queue.pop(0)
                if task['cancelled']:
                    self.tasks.pop(task['node']['id'], None)
                    continue
                self.running += 1
                threading.Thread(target=self._run_task_wrapper, args=(task,), daemon=True).start()

    def _run_task_wrapper(self, task):
        try:
            self.run_task(task)
        finally:
            with self.mu:
                self.running -= 1
                self.tasks.pop(task['node']['id'], None)
            self.pump()

    def run_task(self, task):
        node = task['node']
        opts = self.options()
        try:
            attempts = max(0, int(opts.get('retryAttempts') or 0))
        except (TypeError, ValueError):
            attempts = 0
        attempt = 0
        while True:
            remote = None
            try:
                remote = self.acquire()
                if task['cancelled']:
                    self.release(remote)
                    return
                if node['done']:
                    self.add_done(node, -node['done'])   # yeniden denemede baştan başla
                self.set_file_status(node, 'active')
                task['ctl']['cancelled'] = False
                skipped = self.transfer_file(remote, node, task, opts)
                self.release(remote)
                self.set_file_status(node, 'skipped' if skipped else 'done')
                return
            except Exception as err:   # noqa: BLE001
                if remote is not None:
                    if remote.parallel and not remote.closed and not task['cancelled']:
                        self.release(remote)
                    else:
                        self.discard(remote)
                if task['cancelled'] or self.closed or isinstance(err, Cancelled):
                    self.cleanup_partial(node)
                    self.set_file_status(node, 'cancelled')
                    return
                msg = friendly_error(err)
                if attempt < attempts and _ftp_code(err) != 550:
                    self.set_file_status(node, 'retry', msg)
                    try:
                        delay = max(0, float(opts.get('retryDelay') or 0))
                    except (TypeError, ValueError):
                        delay = 0
                    time.sleep(delay)
                    if task['cancelled']:
                        self.set_file_status(node, 'cancelled')
                        return
                    attempt += 1
                    continue
                self.set_file_status(node, 'error', msg)
                return

    def transfer_file(self, remote, node, task, opts):
        """Tek bir dosyayı aktarır; aynı adlı hedef "atla" kuralıyla geçildiyse True döner."""
        on_bytes = lambda n: self.add_done(node, n)   # noqa: E731
        ctl = task['ctl']
        if node['kind'] == 'download':
            dst = Path(node['dst'])
            if dst.exists():
                if opts.get('conflict') == 'skip':
                    return True
                if opts.get('conflict') == 'rename':
                    dst = tools_mt.unique_local_path(dst)
                    node['dst'] = str(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            node['partial'] = str(dst)
            check = tools_mt.space_check(self.uid, APP)   # mtweb: alan kotası (parça parça)
            if check:
                check(0, True)
                on_bytes = lambda n: (check(n, False), self.add_done(node, n))   # noqa: E731
            try:
                remote.download(node['src'], dst, on_bytes, ctl, opts)
            except MtError:
                if check:   # kota aşıldı: yarım dosya kalmasın
                    node['partial'] = None
                    dst.unlink(missing_ok=True)
                raise
            node['partial'] = None
        else:
            dst = node['dst']
            if opts.get('conflict') != 'overwrite' and remote.exists(dst):
                if opts.get('conflict') == 'skip':
                    return True
                node['dst'] = dst = unique_remote_path(remote, dst)
            node['partial'] = dst
            remote.upload(Path(node['src']), dst, on_bytes, ctl, opts)
            node['partial'] = None
        return False

    def cleanup_partial(self, node):
        p = node.get('partial')
        if not p:
            return
        node['partial'] = None
        if node['kind'] == 'download':
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
        else:
            try:
                self.run(lambda r: r.remove_file(p))
            except Exception:   # noqa: BLE001
                pass

    # --- indirme / yükleme başlatma ---
    def case_name(self, name):
        rule = self.conn.get('uploadCase')
        return name.lower() if rule == 'lower' else name.upper() if rule == 'upper' else name

    def download(self, items, local_dir):
        """items: [{path, name, isDir, size, mtime}] (uzak), local_dir: H:\\… hedef klasör."""
        real_dir = tools_mt.to_real(self.uid, local_dir)
        for it in items:
            dst = real_dir / tools_mt.safe_segment(it.get('name'))
            if not it.get('isDir'):
                node = self.add_node(name=it['name'], isDir=False, kind='download', src=it['path'], dst=str(dst), size=it.get('size') or 0,
                                     mtime=it.get('mtime'), dstDir=local_dir, startT=time.time())
                node['rootId'] = node['id']
                self.register_file(node)
                self.enqueue(node)
                continue
            root = self.add_node(name=it['name'], isDir=True, kind='download', src=it['path'], dst=str(dst), dstDir=local_dir, scanning=True, startT=time.time())
            root['rootId'] = root['id']
            threading.Thread(target=self._scan_remote, args=(root,), daemon=True).start()

    def _scan_remote(self, root):
        try:
            remote = self.acquire()
        except Exception as err:   # noqa: BLE001
            root['error'] = friendly_error(err)
            root['failed'] += 1
            root['scanning'] = False
            self.touch(root)
            return
        try:
            def walk(dir_node):
                Path(dir_node['dst']).mkdir(parents=True, exist_ok=True)
                lst = remote.list(dir_node['src'])
                lst.sort(key=lambda e: (not e['isDir'], e['name'].lower()))
                for e in lst:
                    if root['cancelled']:
                        return
                    tools_mt.safe_segment(e['name'])   # sunucudan gelen ad yerel alandan kaçamaz
                    if e['isDir']:
                        d = self.add_node(parentId=dir_node['id'], rootId=root['id'], name=e['name'], isDir=True, kind='download', src=e['path'],
                                          dst=str(Path(dir_node['dst']) / e['name']), scanning=True)
                        walk(d)
                        d['scanning'] = False
                        self.touch(d)
                    else:
                        f = self.add_node(parentId=dir_node['id'], rootId=root['id'], name=e['name'], isDir=False, kind='download', src=e['path'],
                                          dst=str(Path(dir_node['dst']) / e['name']), size=e.get('size') or 0, mtime=e.get('mtime'))
                        self.register_file(f)
                        self.enqueue(f)
            walk(root)
        except Exception as err:   # noqa: BLE001
            root['error'] = friendly_error(err)
            root['failed'] += 1
        finally:
            self.release(remote)
            root['scanning'] = False
            for n in list(self.nodes.values()):
                if n['rootId'] == root['id'] and n['isDir']:
                    n['scanning'] = False
                    self.touch(n)
            self.touch(root)

    def upload(self, paths, remote_dir):
        """paths: yerel (H:\\…) dosya/klasör yolları, remote_dir: hedef uzak klasör."""
        for p in paths:
            try:
                real = tools_mt.to_real(self.uid, p)
                if not real.exists():
                    continue
            except MtError:
                continue
            name = self.case_name(real.name)
            dst = posixpath.join(remote_dir, name)
            if not real.is_dir():
                node = self.add_node(name=real.name, isDir=False, kind='upload', src=str(real), dst=dst, size=real.stat().st_size, dstDir=remote_dir, startT=time.time())
                node['rootId'] = node['id']
                self.register_file(node)
                self.enqueue(node)
                continue
            root = self.add_node(name=real.name, isDir=True, kind='upload', src=str(real), dst=dst, dstDir=remote_dir, scanning=True, startT=time.time())
            root['rootId'] = root['id']
            threading.Thread(target=self._scan_local, args=(root,), daemon=True).start()

    def _scan_local(self, root):
        try:
            remote = self.acquire()
        except Exception as err:   # noqa: BLE001
            root['error'] = friendly_error(err)
            root['failed'] += 1
            root['scanning'] = False
            self.touch(root)
            return
        try:
            def walk(dir_node):
                try:
                    remote.mkdir(dir_node['dst'])
                except Exception:   # noqa: BLE001 — zaten var
                    pass
                entries = sorted(Path(dir_node['src']).iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                for e in entries:
                    if root['cancelled']:
                        return
                    dst = posixpath.join(dir_node['dst'], self.case_name(e.name))
                    if e.is_dir():
                        d = self.add_node(parentId=dir_node['id'], rootId=root['id'], name=e.name, isDir=True, kind='upload', src=str(e), dst=dst, scanning=True)
                        walk(d)
                        d['scanning'] = False
                        self.touch(d)
                    elif e.is_file():
                        f = self.add_node(parentId=dir_node['id'], rootId=root['id'], name=e.name, isDir=False, kind='upload', src=str(e), dst=dst, size=e.stat().st_size)
                        self.register_file(f)
                        self.enqueue(f)
            walk(root)
        except Exception as err:   # noqa: BLE001
            root['error'] = friendly_error(err)
            root['failed'] += 1
        finally:
            self.release(remote)
            root['scanning'] = False
            for n in list(self.nodes.values()):
                if n['rootId'] == root['id'] and n['isDir']:
                    n['scanning'] = False
                    self.touch(n)
            self.touch(root)

    # --- iptal / yeniden dene / temizle ---
    def subtree(self, nid):
        node = self.nodes.get(nid)
        if not node:
            return []
        out = [node]
        ids = {nid}
        for n in list(self.nodes.values()):
            if n['rootId'] != node['rootId'] or n is node:
                continue
            p = n['parentId']
            while p and p not in ids:
                p = (self.nodes.get(p) or {}).get('parentId')
            if p:
                out.append(n)
        return out

    def cancel(self, nid):
        for n in self.subtree(nid):
            if n['isDir']:
                n['cancelled'] = True
                self.touch(n)
                continue
            task = self.tasks.get(n['id'])
            if not task:
                continue
            task['cancelled'] = True
            task['ctl']['cancelled'] = True
            if n['status'] == 'active':
                try:
                    if task['ctl'].get('abort'):
                        task['ctl']['abort']()
                except Exception:   # noqa: BLE001
                    pass
            else:
                self.set_file_status(n, 'cancelled')

    def cancel_all(self):
        for n in list(self.nodes.values()):
            if not n['parentId']:
                self.cancel(n['id'])

    def retry(self, nid):
        for n in self.subtree(nid):
            if n['isDir']:
                n['cancelled'] = False
                self.touch(n)
                continue
            if n['status'] not in ('error', 'cancelled'):
                continue
            if n['done']:
                self.add_done(n, -n['done'])
            self.set_file_status(n, 'queued')
            self.enqueue(n)
        node = self.nodes.get(nid)
        root = self.nodes.get(node['rootId']) if node else None
        if root:
            root['reported'] = None
            if not root['scanning']:
                root['error'] = None
            self.touch(root)

    def clear(self, ids):
        with self.mu:
            roots = [self.nodes[i] for i in ids if i in self.nodes] if ids else [n for n in self.nodes.values() if not n['parentId'] and self.status_of(n) in FINISHED]
            removed = []
            for r in roots:
                if r['parentId'] or self.status_of(r) not in FINISHED:
                    continue
                for n in list(self.nodes.values()):
                    if n['rootId'] == r['id']:
                        self.nodes.pop(n['id'], None)
                        self.dirty.discard(n['id'])
                removed.append(r['id'])
            return removed

    def close(self):
        self.closed = True
        try:
            self.keepalive.cancel()
        except Exception:   # noqa: BLE001
            pass
        with self.mu:
            if self.flush_timer:
                self.flush_timer.cancel()
            tasks = list(self.tasks.values())
        for task in tasks:
            task['cancelled'] = True
            task['ctl']['cancelled'] = True
            try:
                if task['ctl'].get('abort'):
                    task['ctl']['abort']()
            except Exception:   # noqa: BLE001
                pass
        with self.pool_cv:
            for r in self.idle:
                try:
                    r.close()
                except Exception:   # noqa: BLE001
                    pass
            self.idle = []
            self.pool_cv.notify_all()
        if self.browse:
            self.browse.close()


# ---------------------------------------------------------------------------
# WebSocket: bir site penceresi
# ---------------------------------------------------------------------------
class Window:
    def __init__(self, ws, user, site_id, lang):
        self.ws, self.user, self.site_id, self.lang = ws, user, site_id, lang
        self.uid = user['id']
        self.loop = asyncio.get_running_loop()
        self.q = asyncio.Queue()
        self.session = None
        self.release = None
        self.closed = False

    def emit(self, item):
        if not self.closed:
            self.loop.call_soon_threadsafe(self.q.put_nowait, item)

    def event(self, ch, d):
        self.emit({'t': 'ev', 'ch': ch, 'd': d})

    async def sender(self):
        while True:
            item = await self.q.get()
            await self.ws.send_text(json.dumps(item, ensure_ascii=False))

    def close_session(self):
        s, self.session = self.session, None
        rel, self.release = self.release, None
        if s:
            s.close()
        if rel:
            rel()

    def need(self):
        if not self.session:
            raise MtError(T('main.errNoSession'))
        return self.session

    def site_open(self):
        self.close_session()
        store = tools_mt.read_store(self.uid, APP, self.lang)
        apply_speed_limit(self.uid, store['settings'])
        try:
            conn = tools_mt.resolve_connection(store, self.site_id)
        except MtError as e:
            return {'ok': False, 'message': e.msg}, None
        cid = conn['id']
        pub = [None]
        try:
            self.release = tc.conn_slot(self.uid, APP)
        except Exception as e:   # noqa: BLE001 — eşzamanlı oturum sınırı (mtweb)
            return {'ok': False, 'message': friendly_error(e)}, None

        def on_host_key(fp):
            pub[0] = tools_mt.remember_host_key(self.uid, APP, cid, fp) or pub[0]
        session = Session(self.uid, conn, options=lambda: tools_mt.site_options(tools_mt.read_store(self.uid, APP), cid),
                          send=self.event, on_host_key=on_host_key)
        self.session = session
        try:
            remote = session.open()
            home = '/'
            try:
                home = remote.pwd()
            except Exception:   # noqa: BLE001
                pass
            start_remote = (conn.get('rememberLastDir') and conn.get('lastRemoteDir')) or conn.get('remoteDir') or home
            start_local = (conn.get('rememberLastDir') and conn.get('lastLocalDir')) or conn.get('localDir') or store['settings'].get('localDir') or tools_mt.DRIVE
            info = ''
            try:
                info = session.run(lambda r: r.info())
            except Exception:   # noqa: BLE001
                pass
            tools_mt.audit(self.uid, 'FTP Masters bağlantısı açtı', f"{conn.get('protocol')} {conn.get('username')}@{conn.get('host')}:{conn.get('port')}")
            return {'ok': True, 'home': home, 'startRemote': start_remote, 'startLocal': start_local, 'info': info}, pub[0]
        except Exception as e:   # noqa: BLE001
            self.close_session()
            return {'ok': False, 'message': friendly_error(e)}, pub[0]

    def call(self, m, a):
        if m == 'site:open':
            return self.site_open()
        s = self.need()
        try:
            if m == 'site:list':
                return s.list(a.get('dir') or '/', bool(a.get('refresh'))), None
            if m == 'site:stat':
                return s.run(lambda r: r.stat(a)), None
            if m == 'site:mkdir':
                s.run(lambda r: r.mkdir(a))
                s.invalidate(posixpath.dirname(a))
                return None, None
            if m == 'site:rename':
                s.run(lambda r: r.rename(a['from'], a['to']))
                s.invalidate(posixpath.dirname(a['from']))
                s.invalidate(posixpath.dirname(a['to']))
                return None, None
            if m == 'site:delete':
                for it in a or []:
                    if it.get('isDir') and not it.get('isLink'):
                        s.run(lambda r, p=it['path']: r.remove_dir(p))
                    else:
                        s.run(lambda r, p=it['path']: r.remove_file(p))
                    s.invalidate(posixpath.dirname(it['path']))
                    s.invalidate(it['path'])
                return None, None
            if m == 'site:download':
                s.download(a.get('items') or [], a.get('localDir') or tools_mt.DRIVE)
                return None, None
            if m == 'site:upload':
                s.upload(a.get('paths') or [], a.get('remoteDir') or '/')
                return None, None
            if m == 'transfer:clear':
                return s.clear(a), None
        except MtError:
            raise
        except Exception as e:   # noqa: BLE001 — renderer'a temiz metin gitsin
            raise MtError(friendly_error(e)) from None
        raise MtError(f'Bilinmeyen kanal: {m}')

    def on_send(self, m, a):
        s = self.session
        if not s:
            return
        if m == 'site:lastDir':
            a = a or {}
            cid = s.conn.get('id')
            remote, local = a.get('remote'), a.get('local')

            def fn(store):
                c = next((x for x in store['connections'] if x.get('id') == cid), None)
                if not c or not c.get('rememberLastDir'):
                    return
                if remote:
                    c['lastRemoteDir'] = remote
                if local:
                    c['lastLocalDir'] = local
            tools_mt.with_store(self.uid, APP, fn)
        elif m == 'transfer:cancel':
            s.cancel(a)
        elif m == 'transfer:cancelAll':
            s.cancel_all()
        elif m == 'transfer:retry':
            s.retry(a)


async def _reject(ws, msg, code=4403):
    try:
        await ws.send_text(json.dumps({'t': 'ev', 'ch': 'error', 'd': msg}))
        await ws.close(code=code)
    except Exception:   # noqa: BLE001
        pass


@ws_router.websocket('/ws/tools/ftp')
async def ws_ftp(ws: WebSocket):
    await ws.accept()
    user = await ws_user(ws)
    if not user:
        return await _reject(ws, 'Yetkisiz: Araçlar modülü yetkisi gerekir.')
    win = Window(ws, user, ws.query_params.get('id') or '', tools_mt.ws_ctx(user, APP)['lang'])
    sender = asyncio.create_task(win.sender())

    async def handle_call(obj):
        try:
            v, store = await asyncio.to_thread(win.call, obj.get('m'), obj.get('a'))
            ret = {'t': 'ret', 'id': obj.get('id'), 'ok': True, 'v': v}
            if store:
                ret['store'] = store
        except MtError as e:
            ret = {'t': 'ret', 'id': obj.get('id'), 'ok': False, 'e': e.msg}
        except Exception as e:   # noqa: BLE001
            ret = {'t': 'ret', 'id': obj.get('id'), 'ok': False, 'e': friendly_error(e)}
        win.emit(ret)

    try:
        while True:
            msg = await ws.receive()
            if msg['type'] == 'websocket.disconnect':
                break
            try:
                obj = json.loads(msg.get('text') or '')
            except ValueError:
                continue
            if obj.get('t') == 'call':
                asyncio.create_task(handle_call(obj))
            elif obj.get('t') == 'send':
                await asyncio.to_thread(win.on_send, obj.get('m'), obj.get('a'))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        win.closed = True
        sender.cancel()
        threading.Thread(target=win.close_session, daemon=True, name='ftp-close').start()   # iptalden bağımsız: bağlantılar ve oturum yuvaları mutlaka bırakılır
