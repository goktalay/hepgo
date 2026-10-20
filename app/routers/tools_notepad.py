"""Araçlar › Notepad Master (web) — masaüstü uygulamanın ana süreci (main.js + project.js + remote.js + textcodec.js)
Python'a taşındı. Arayüz static/mt/notepadmaster (orijinal renderer, Monaco); köprü bridge.js aynı IPC adlarıyla buraya gelir.

Depo (store): kullanıcı başına tools_mt_store('notepadmaster','store') — masaüstündeki store.json ile aynı şema
  { folders:[{id,name,parentId}], connections:[…], syncMeta:{}, settings:{appTheme,language,editor,treeWidth,…} }
Bağlantı türleri: ssh (SFTP, paramiko) · ftp (FTP/FTPS ftplib; protokol sftp ise paramiko) · local (kullanıcının
sunucudaki dosya alanı DATA_DIR/tools/notepadmaster/<uid>/files) · file (o alanda tek dosya).
Parola/anahtar parolası Fernet ile şifreli saklanır; renderer'a yalnız var/yok bilgisi gider.
Çalışma kopyası (cache): DATA_DIR/tools/notepadmaster/<uid>/cache/<bağlantı id>/<yol>.
"""
import base64
import codecs
import ftplib
import hashlib
import io
import posixpath
import re
import secrets
import shutil
import socket
import ssl
import stat as stat_
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .tools_common import check_host, check_port, safe_name, tools_user
from . import tools_mt as mt
from . import tools_common as tc

router = APIRouter(prefix='/api/tools/notepad')
APP = 'notepadmaster'
KINDS = ['ssh', 'ftp', 'local', 'file']
PROTOCOLS = {'ftp': 21, 'ftps-implicit': 990, 'ftps-ssl': 21, 'ftps-tls': 21, 'sftp': 22}
LANGS = (None, 'tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru')
MAX_FILE_BYTES = 50 * 1024 * 1024
SESSION_IDLE = 3600
# mtweb kancaları (app/mtweb; HEPGO'da varsayılanlar → davranış değişmez)
ALLOW_REMOTE = True      # False → SSH/FTP/SFTP bağlantısı hiç açılmaz (yalnız kullanıcının dosya alanı)
REMOTE_GUARD = None      # callable(uid, conn) → uzak bağlantı açılmadan önce (SSRF / kota denetimi)
WRITE_GUARD = None       # callable(uid, nbytes) → yerel alana yazmadan önce (kota)
PUBLIC_PATH = None       # callable(Path) → str; arayüze giden sunucu yolları (çalışma kopyası) gizlenir

try:
    import paramiko
except ImportError:   # pragma: no cover
    paramiko = None


# --- Varsayılanlar (defaults.js EDITOR_DEFAULTS / sanitizeEditor) ------------------------------------------
EDITOR_DEFAULTS = {
    'encoding': 'auto', 'fallbackEncoding': 'windows-1254', 'newEncoding': 'utf8', 'eol': 'auto', 'newEol': 'lf',
    'tabSize': 4, 'insertSpaces': True, 'detectIndentation': True, 'autoIndent': True, 'wordWrap': False,
    'fontFamily': "'Cascadia Code', 'Cascadia Mono', Consolas, 'Courier New', monospace", 'fontSize': 14, 'lineHeight': 0,
    'theme': 'auto', 'language': 'auto', 'renderWhitespace': 'none', 'renderControlChars': False, 'lineNumbers': True,
    'minimap': True, 'highlightLine': True, 'indentGuides': True, 'folding': True, 'bracketColors': True, 'autoClose': True,
    'smartHighlight': True, 'rulers': '', 'trimTrailing': False, 'finalNewline': False, 'checkRemoteChange': True, 'autoSave': 0,
}
ENCODINGS = ['utf8', 'utf8bom', 'utf16le', 'utf16be', 'windows-1254', 'iso-8859-9', 'windows-1252', 'iso-8859-1', 'windows-1251', 'windows-1256']
THEMES = ['mastertool-dark', 'mastertool-light', 'obsidian', 'monokai', 'vs-dark', 'vs', 'solarized-light', 'hc-black']


def _one(v, lst, d):
    return v if v in lst else d


def _num(v, d, lo, hi):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return d
    return int(min(hi, max(lo, round(n))))


def _bool(v, d):
    return v if isinstance(v, bool) else d


def _str(v, mx=500):
    return str(v if v is not None else '').strip()[:mx]


def sanitize_editor(e, base=None):
    d = {**EDITOR_DEFAULTS, **(base or {})}
    e = e if isinstance(e, dict) else {}
    ansi = [x for x in ENCODINGS if not x.startswith('utf')]
    out = {
        'encoding': _one(e.get('encoding'), ['auto', *ENCODINGS], d['encoding']),
        'fallbackEncoding': _one(e.get('fallbackEncoding'), ansi, d['fallbackEncoding']),
        'newEncoding': _one(e.get('newEncoding'), ENCODINGS, d['newEncoding']),
        'eol': _one(e.get('eol'), ['auto', 'crlf', 'lf', 'cr'], d['eol']),
        'newEol': _one(e.get('newEol'), ['crlf', 'lf', 'cr'], d['newEol']),
        'tabSize': _num(e.get('tabSize'), d['tabSize'], 1, 16),
        'fontFamily': e['fontFamily'][:200] if isinstance(e.get('fontFamily'), str) and e['fontFamily'].strip() else d['fontFamily'],
        'fontSize': _num(e.get('fontSize'), d['fontSize'], 6, 48),
        'lineHeight': _num(e.get('lineHeight'), d['lineHeight'], 0, 80),
        'theme': _one(e.get('theme'), ['auto', *THEMES], d['theme']),
        'language': e['language'] if isinstance(e.get('language'), str) and re.fullmatch(r'[\w.+-]{1,40}', e['language']) else d['language'],
        'renderWhitespace': _one(e.get('renderWhitespace'), ['none', 'boundary', 'trailing', 'all'], d['renderWhitespace']),
        'rulers': re.sub(r'[^\d,\s]', '', e['rulers'])[:40] if isinstance(e.get('rulers'), str) else d['rulers'],
        'autoSave': _num(e.get('autoSave'), d['autoSave'], 0, 3600),
    }
    for k in ('insertSpaces', 'detectIndentation', 'autoIndent', 'wordWrap', 'renderControlChars', 'lineNumbers', 'minimap', 'highlightLine',
              'indentGuides', 'folding', 'bracketColors', 'autoClose', 'smartHighlight', 'trimTrailing', 'finalNewline', 'checkRemoteChange'):
        out[k] = _bool(e.get(k), d[k])
    return out


def default_store():
    return {'folders': [], 'connections': [], 'syncMeta': {},
            'settings': {'appTheme': 'system', 'language': None, 'editor': dict(EDITOR_DEFAULTS), 'treeWidth': 300, 'treeOpen': True,
                         'minimizeToTray': True, 'closeToTray': False, 'openAtLogin': False}}


def load_store(uid):
    raw = mt.kv_get(uid, APP, 'store') or {}
    s = {**default_store(), **raw}
    s['settings'] = {**default_store()['settings'], **(raw.get('settings') or {})}
    s['settings']['editor'] = sanitize_editor(s['settings'].get('editor'))
    s.setdefault('syncMeta', {})
    return s


def save_store(uid, s):
    mt.kv_set(uid, APP, 'store', s)


def public_conn(uid, c):
    rest = {k: v for k, v in c.items() if k not in ('password', 'passphrase', 'hostKey')}
    has_local = bool(c.get('localPath')) and _local_exists(uid, c.get('localPath'))
    return {**rest, 'hasPassword': bool(c.get('password')), 'hasPassphrase': bool(c.get('passphrase')), 'hasLocalPath': has_local}


def public_store(uid, s=None):
    s = s or load_store(uid)
    return {'folders': s['folders'], 'settings': s['settings'], 'connections': [public_conn(uid, c) for c in s['connections']],
            'cacheDir': f'{tc.BRAND} · tools/notepadmaster/cache'}


def _local_exists(uid, rel):
    try:
        return mt.resolve(mt.files_root(APP, uid), rel).exists()
    except HTTPException:
        return False


def find_conn(s, cid):
    return next((c for c in s['connections'] if c['id'] == cid), None)


def resolve_conn(uid, s, cid):
    c = find_conn(s, cid)
    if not c:
        raise HTTPException(404, 'Bağlantı bulunamadı')
    return {**c, 'password': mt.unprotect(c.get('password', '')), 'passphrase': mt.unprotect(c.get('passphrase', ''))}


def merge_form(uid, s, form):
    """Formdan gelen veri; boş parola alanı düzenlemede 'değiştirme' demektir (mergeFormWithStored)."""
    stored = find_conn(s, form.get('id')) if form.get('id') else None
    same_host = stored and stored.get('host') == form.get('host') and str(stored.get('port')) == str(form.get('port'))
    return {**form, 'id': form.get('id') or 'test',
            'password': form.get('password') or (mt.unprotect(stored.get('password', '')) if stored and not form.get('clearPassword') else ''),
            'passphrase': form.get('passphrase') or (mt.unprotect(stored.get('passphrase', '')) if stored else ''),
            'hostKey': stored.get('hostKey') if same_host else None}


# --- Metin kodlaması (textcodec.js) ---------------------------------------------------------------------------
PY_CODEC = {'utf8': 'utf-8', 'utf16le': 'utf-16-le', 'utf16be': 'utf-16-be', 'windows-1254': 'cp1254', 'windows-1252': 'cp1252',
            'iso-8859-9': 'iso8859-9', 'iso-8859-1': 'latin-1', 'windows-1251': 'cp1251', 'windows-1256': 'cp1256'}
BOMS = [('utf8', codecs.BOM_UTF8), ('utf16le', codecs.BOM_UTF16_LE), ('utf16be', codecs.BOM_UTF16_BE)]


def norm_enc(e):
    if e == 'utf8bom':
        return 'utf8'
    return e if e in PY_CODEC else 'utf8'


def _sniff_bom(buf):
    for enc, b in BOMS:
        if buf.startswith(b):
            return enc, b
    return None


def _is_utf8(buf):
    try:
        buf.decode('utf-8')
        return True
    except UnicodeDecodeError as e:
        return e.start >= len(buf) - 3 and e.reason.startswith('unexpected end')   # kesilmiş dizi: yine de UTF-8 say


def _looks_binary(buf):
    return b'\x00' in buf[:8192]


def detect_eol(text):
    crlf = text.count('\r\n')
    lf = text.count('\n') - crlf
    cr = text.count('\r') - crlf
    if not (crlf or lf or cr):
        return None
    if crlf >= lf and crlf >= cr:
        return 'crlf'
    return 'lf' if lf >= cr else 'cr'


def decode(buf, encoding='auto', fallback='windows-1254'):
    bom = _sniff_bom(buf)
    if not bom and _looks_binary(buf):
        return {'binary': True}
    has_bom = False
    body = buf
    if encoding in ('auto', None, ''):
        if bom:
            enc, has_bom, body = bom[0], True, buf[len(bom[1]):]
        else:
            enc = 'utf8' if _is_utf8(buf) else norm_enc(fallback)
    else:
        enc = norm_enc(encoding)
        if bom and bom[0] == enc:
            has_bom, body = True, buf[len(bom[1]):]
        elif encoding == 'utf8bom':
            has_bom = True
    text = body.decode(PY_CODEC[enc], errors='replace')
    return {'text': text, 'encoding': enc, 'bom': has_bom, 'eol': detect_eol(text), 'binary': False}


def encode(text, encoding='utf8', bom=False):
    enc = norm_enc(encoding)
    body = text.encode(PY_CODEC[enc], errors='replace')
    if not bom:
        return body
    b = next((x[1] for x in BOMS if x[0] == enc), b'')
    return b + body


def can_encode(text, encoding):
    enc = norm_enc(encoding)
    if enc.startswith('utf'):
        return True
    try:
        text.encode(PY_CODEC[enc])
        return True
    except UnicodeEncodeError:
        return False


# --- Uzak dosya katmanı (remote.js): SFTP · FTP/FTPS · yerel alan ----------------------------------------------
class RemoteError(Exception):
    def __init__(self, code, message='', **extra):
        super().__init__(message or code)
        self.code = code
        self.extra = extra


def credentials(conn):
    if conn.get('loginMethod') == 'anonymous':
        return 'anonymous', conn.get('password') or 'anonymous@'
    return _str(conn.get('username'), 200), conn.get('password') or ''


class LocalRemote:
    """Kullanıcının sunucudaki dosya alanı (masaüstündeki 'Bu bilgisayardaki klasör')."""

    def __init__(self, uid, conn):
        self.uid = uid
        self.root = mt.files_root(APP, uid)
        self.closed = True
        self.fingerprint = None

    def _p(self, rel):
        return mt.resolve(self.root, rel)

    def connect(self):
        self.closed = False
        return self

    def info(self):
        return ''

    def pwd(self):
        return '/'

    def list(self, d):
        return mt.list_dir(self.root, d)

    def stat(self, p):
        f = self._p(p)
        if not f.exists():
            raise RemoteError('ENOENT', 'ENOENT')
        st = f.stat()
        return {'isDir': f.is_dir(), 'size': st.st_size, 'mtime': int(st.st_mtime * 1000)}

    def read_file(self, p):
        return self._p(p).read_bytes()

    def write_file(self, p, buf):
        f = self._p(p)
        if WRITE_GUARD:
            WRITE_GUARD(self.uid, len(buf) - (f.stat().st_size if f.is_file() else 0), not f.exists())
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(buf)

    def mkdir(self, p):
        f = self._p(p)
        if WRITE_GUARD:
            WRITE_GUARD(self.uid, 0, True)
        if f.exists():
            raise RemoteError('EEXIST', 'EEXIST')
        f.mkdir(parents=True)

    def rename(self, a, b):
        self._p(a).rename(self._p(b))

    def remove_file(self, p):
        self._p(p).unlink()

    def remove_dir(self, p):
        shutil.rmtree(self._p(p))

    def close(self):
        self.closed = True


class SftpRemote:
    def __init__(self, uid, conn):
        self.uid, self.conn = uid, conn
        self.ssh = self.sftp = None
        self.fingerprint = None
        self.closed = True

    def connect(self):
        if paramiko is None:
            raise RemoteError('NOSFTP', 'SFTP için paramiko paketi kurulu değil')
        c = self.conn
        host, port = check_host(c.get('host')), check_port(c.get('port') or 22)
        user, password = credentials(c)
        self._release = tc.conn_slot(self.uid, APP)
        sock = None
        try:
            sock = tc.net_socket(host, port, 20, self.uid, APP) or socket.create_connection((host, port), timeout=20)
            tr = paramiko.Transport(sock)
        except Exception:
            if sock is not None:
                sock.close()
            self._release()
            raise
        tr.set_keepalive(20)
        try:
            tr.start_client(timeout=20)
            key = tr.get_remote_server_key()
            self.fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode()
            if c.get('hostKey') and c['hostKey'] != self.fingerprint:
                raise RemoteError('HOSTKEY', 'HOSTKEY', old=c['hostKey'], new=self.fingerprint)
            if c.get('authType') == 'key':
                kp = (c.get('keyPath') or '').strip()
                kf = mt.resolve(mt.app_dir(APP, self.uid, 'keys'), kp) if kp else None
                if not kf or not kf.is_file():
                    raise RemoteError('NOKEY', 'NOKEY')
                pkey = paramiko.PKey.from_path(kf, passphrase=(c.get('passphrase') or None))
                tr.auth_publickey(user, pkey)
            else:
                try:
                    tr.auth_password(user, password)
                except paramiko.BadAuthenticationType:
                    tr.auth_interactive(user, lambda t, i, prompts: [password for _ in prompts])
            self.sftp = paramiko.SFTPClient.from_transport(tr)
        except Exception:
            tr.close()
            self._release()
            raise
        self.ssh = tr
        self.closed = False
        return self

    def info(self):
        try:
            ch = self.ssh.open_session(timeout=10)
            ch.exec_command('uname -sr 2>/dev/null; hostname 2>/dev/null')
            out = b''
            while True:
                d = ch.recv(4096)
                if not d:
                    break
                out += d
            ch.close()
            return ' · '.join(out.decode('utf-8', 'replace').strip().split('\n'))
        except Exception:   # noqa: BLE001
            return ''

    def pwd(self):
        return self.sftp.normalize('.')

    def list(self, d):
        out = []
        for e in self.sftp.listdir_attr(d):
            if e.filename in ('.', '..'):
                continue
            is_link = stat_.S_ISLNK(e.st_mode or 0)
            is_dir = stat_.S_ISDIR(e.st_mode or 0)
            p = posixpath.join(d, e.filename)
            if is_link:
                try:
                    is_dir = stat_.S_ISDIR(self.sftp.stat(p).st_mode)
                except OSError:
                    pass
            out.append({'name': e.filename, 'path': p, 'isDir': is_dir, 'isLink': is_link, 'size': e.st_size or 0, 'mtime': (e.st_mtime or 0) * 1000})
        return out

    def stat(self, p):
        s = self.sftp.stat(p)
        return {'isDir': stat_.S_ISDIR(s.st_mode), 'size': s.st_size or 0, 'mtime': (s.st_mtime or 0) * 1000}

    def read_file(self, p):
        with self.sftp.open(p, 'rb') as f:
            f.prefetch()
            return f.read()

    def write_file(self, p, buf):
        with self.sftp.open(p, 'wb') as f:
            f.write(buf)

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

    def close(self):
        self.closed = True
        try:
            if self.ssh:
                self.ssh.close()
        except Exception:   # noqa: BLE001
            pass
        rel, self._release = getattr(self, '_release', None), None
        if rel:
            rel()


class _ImplicitFTPTLS(ftplib.FTP_TLS):
    """Örtük FTPS (990): soket açılır açılmaz TLS."""

    def connect(self, host='', port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        if port:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=None if re.match(r'^[\d.:]+$', self.host) else self.host)
        self.file = self.sock.makefile('r', encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


def _mlsd_time(s):
    if not s:
        return 0
    try:
        return int(time.mktime(time.strptime(s[:14], '%Y%m%d%H%M%S')) * 1000)
    except ValueError:
        return 0


class FtpRemote:
    def __init__(self, uid, conn):
        self.uid = uid
        self._release = None
        self.conn = conn
        self.client = None
        self.fingerprint = None
        self.closed = True

    def connect(self):
        c = self.conn
        host = check_host(c.get('host'))
        proto = c.get('protocol') or 'ftp'
        port = check_port(c.get('port') or PROTOCOLS.get(proto, 21))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE   # kendinden imzalı sunucu sertifikaları (FileZilla / FTP Masters gibi)
        if proto == 'ftps-implicit':
            cl = _ImplicitFTPTLS(context=ctx, timeout=30)
        elif proto in ('ftps-tls', 'ftps-ssl'):
            cl = ftplib.FTP_TLS(context=ctx, timeout=30)
        else:
            cl = ftplib.FTP(timeout=30)
        cl.encoding = 'latin-1' if c.get('nameEncoding') == 'ascii' else 'utf-8'
        from .tools_ftp import harden_ftp
        harden_ftp(cl, self.uid, APP)
        self._release = tc.conn_slot(self.uid, APP)
        try:
            cl.connect(tc.net_target(host, port, self.uid, APP), port)
            if proto in ('ftps-tls', 'ftps-ssl'):
                cl.auth()
            user, password = credentials(c)
            cl.login(user, password)
            if isinstance(cl, ftplib.FTP_TLS):
                cl.prot_p()
            try:
                cl.sendcmd('OPTS UTF8 OFF' if c.get('nameEncoding') == 'ascii' else 'OPTS UTF8 ON')
            except ftplib.all_errors:
                pass
        except Exception:
            try:
                cl.close()
            except Exception:   # noqa: BLE001
                pass
            self._release()
            self._release = None
            raise
        self.client = cl
        self.closed = False
        return self

    def info(self):
        try:
            return re.sub(r'^\d+\s*', '', self.client.sendcmd('SYST')).strip()
        except ftplib.all_errors:
            return ''

    def pwd(self):
        return self.client.pwd()

    def list(self, d):
        out = []
        try:
            for name, facts in self.client.mlsd(d):
                if name in ('.', '..'):
                    continue
                t = facts.get('type', 'file')
                out.append({'name': name, 'path': posixpath.join(d, name), 'isDir': t in ('dir', 'cdir', 'pdir'), 'isLink': t == 'OS.unix=symlink',
                            'size': int(facts.get('size', 0) or 0), 'mtime': _mlsd_time(facts.get('modify'))})
            return out
        except ftplib.all_errors:
            pass
        lines = []
        self.client.retrlines(f'LIST {d}', lines.append)
        for ln in lines:
            m = re.match(r'^([\-dl])[\w\-+@.]{9,}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+(\w{3}\s+\d{1,2}\s+[\d:]+)\s+(.+)$', ln)
            if not m:
                continue
            name = m.group(4)
            if m.group(1) == 'l' and ' -> ' in name:
                name = name.split(' -> ')[0]
            if name in ('.', '..'):
                continue
            out.append({'name': name, 'path': posixpath.join(d, name), 'isDir': m.group(1) == 'd', 'isLink': m.group(1) == 'l', 'size': int(m.group(2)), 'mtime': 0})
        return out

    def stat(self, p):
        try:
            size = self.client.size(p)
            if size is None:
                raise ftplib.error_perm('no size')
            mtime = 0
            try:
                mtime = _mlsd_time(self.client.sendcmd('MDTM ' + p).split()[-1])
            except ftplib.all_errors:
                pass
            return {'isDir': False, 'size': size, 'mtime': mtime}
        except ftplib.all_errors:
            cwd = self.client.pwd()
            self.client.cwd(p)
            self.client.cwd(cwd)
            return {'isDir': True, 'size': 0, 'mtime': 0}

    def read_file(self, p):
        buf = io.BytesIO()
        self.client.retrbinary('RETR ' + p, buf.write)
        return buf.getvalue()

    def write_file(self, p, buf):
        self.client.storbinary('STOR ' + p, io.BytesIO(buf))

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

    def close(self):
        self.closed = True
        rel, self._release = self._release, None
        if rel:
            rel()
        if not self.client:
            return
        try:
            self.client.quit()
        except Exception:   # noqa: BLE001
            try:
                self.client.close()
            except Exception:   # noqa: BLE001
                pass


def create_remote(uid, conn):
    if conn.get('kind') in ('local', 'file'):
        return LocalRemote(uid, conn)
    if not ALLOW_REMOTE:
        raise RemoteError('REMOTE_OFF', 'Bu özellik masaüstü sürümünde')
    if REMOTE_GUARD:
        REMOTE_GUARD(uid, conn)
    if conn.get('kind') == 'ssh' or conn.get('protocol') == 'sftp':
        return SftpRemote(uid, conn)
    return FtpRemote(uid, conn)


def friendly_error(err) -> str:
    """Sunucu hatalarını kullanıcı dostu metne çevirir (remote.js friendlyError, Türkçe karşılıklar)."""
    if isinstance(err, HTTPException):
        return err.detail
    msg = str(err) or err.__class__.__name__
    if isinstance(err, tc.NetDenied):
        return msg
    if isinstance(err, OSError) and err.strerror:
        msg = err.strerror
    code = getattr(err, 'code', None)
    if code == 'HOSTKEY':
        ex = getattr(err, 'extra', {})
        return f"Sunucunun SSH anahtarı değişti (kayıtlı {ex.get('old')}, gelen {ex.get('new')}). Güvenlik için bağlantı reddedildi."
    if code == 'NOKEY':
        return 'Özel anahtar dosyası bulunamadı; bağlantı formundan anahtarı yeniden yükleyin.'
    if code == 'NOLOCAL':
        return 'Bu bağlantının klasörü/dosyası sunucudaki alanınızda bulunamadı.'
    if code in ('NOSFTP', 'CLOSED'):
        return msg
    low = msg.lower()
    if 'authentication' in low or 'login incorrect' in low or msg.startswith('530'):
        return 'Kullanıcı adı ya da parola kabul edilmedi.'
    if msg.startswith('550'):
        return 'Sunucu isteği reddetti: ' + msg[3:].strip()
    if msg.startswith('553'):
        return 'Dosya adı sunucu tarafından kabul edilmedi.'
    if 'refused' in low:
        return 'Bağlantı reddedildi (port kapalı ya da sunucu dinlemiyor).'
    if 'timed out' in low or 'timeout' in low:
        return 'Bağlantı zaman aşımına uğradı.'
    if 'name or service not known' in low or 'nodename' in low or 'getaddrinfo' in low or 'temporary failure in name' in low:
        return 'Sunucu adı çözümlenemedi.'
    if 'unreachable' in low:
        return 'Sunucuya erişilemiyor (ağ yolu yok).'
    if 'reset' in low or 'broken pipe' in low or 'not connected' in low or 'socket is closed' in low:
        return 'Bağlantı koptu.'
    if 'no such file' in low or 'enoent' in low:
        return 'Dosya ya da klasör bulunamadı.'
    if 'exists' in low or 'eexist' in low:
        return 'Aynı adda bir dosya ya da klasör zaten var.'
    if 'permission denied' in low or 'eacces' in low or 'eperm' in low:
        return 'Erişim izni yok.'
    if 'private key' in low or ('key' in low and 'not a valid' in low):
        return 'Özel anahtar dosyası okunamadı (biçim ya da parola hatalı).'
    if 'ssl' in low or 'tls' in low or 'certificate' in low:
        return 'TLS hatası: ' + msg
    return msg


# --- Proje oturumu (project.js ProjectSession) ---------------------------------------------------------------
NETWORK_ERR = re.compile(r'reset|broken pipe|not connected|closed|timed out|timeout|EOF', re.I)
_SAFE_SEG = re.compile(r'[<>:"|?*\x00-\x1f]')


def public_path(p):
    return PUBLIC_PATH(p) if PUBLIC_PATH else str(p)


def safe_segment(s):
    return _SAFE_SEG.sub('_', s).rstrip('. ') or '_'


class ProjectSession:
    def __init__(self, uid, conn, on_hostkey):
        self.uid, self.conn = uid, conn
        self.kind = conn.get('kind')
        self.cache_root = mt.app_dir(APP, uid, 'cache', conn['id'])
        self.on_hostkey = on_hostkey
        self.remote = None
        self.root = ''
        self.status = 'off'
        self.lock = threading.RLock()
        self.last = time.time()
        self.closed_by_user = False

    @property
    def is_local(self):
        return self.kind in ('local', 'file')

    def connect(self):
        if self.remote:
            self.remote.close()
        self.status = 'connecting'
        r = create_remote(self.uid, self.conn)
        try:
            r.connect()
        except Exception:
            self.status = 'off'
            raise
        if r.fingerprint:
            self.on_hostkey(r.fingerprint)
        self.remote = r
        self.status = 'on'
        return r

    def open(self):
        r = self.connect()
        home = info = ''
        if self.is_local:
            lp = self.conn.get('localPath') or ''
            if not lp or not _local_exists(self.uid, lp):
                raise RemoteError('NOLOCAL', 'NOLOCAL')
            n = mt.norm_rel(lp)
            self.root = (posixpath.dirname(n) or '/') if self.kind == 'file' else n
            home = self.root
        else:
            try:
                home = r.pwd()
            except Exception:   # noqa: BLE001
                home = '/'
            try:
                info = r.info()
            except Exception:   # noqa: BLE001
                info = ''
            self.root = self.conn.get('rootDir') or home or '/'
        return {'root': self.root, 'home': home, 'info': info, 'sep': '/'}

    def run(self, fn):
        """İşlemler sıraya girer (FTP tek komut); bağlantı koptuysa bir kez yeniden bağlanır."""
        with self.lock:
            self.last = time.time()
            if self.closed_by_user:
                raise RemoteError('CLOSED', 'Bağlantı kapatıldı')
            if not self.remote or self.remote.closed:
                self.connect()
            try:
                return fn(self.remote)
            except (RemoteError, HTTPException):
                raise
            except Exception as err:
                if self.is_local or not NETWORK_ERR.search(str(err)):
                    raise
                self.status = 'off'
                self.connect()
                return fn(self.remote)

    def check(self, p):
        if not p or not isinstance(p, str):
            raise RemoteError('ENOENT', 'ENOENT')
        if self.kind == 'file':
            if mt.norm_rel(p) != mt.norm_rel(self.conn.get('localPath') or ''):
                raise RemoteError('EACCES', 'EACCES')
        elif self.is_local:
            n = mt.norm_rel(p)
            if not (n == self.root or n.startswith(self.root.rstrip('/') + '/')):
                raise RemoteError('EACCES', 'EACCES')
        return p

    def cache_path(self, p):
        parts = [safe_segment(s) for s in posixpath.normpath(p).split('/') if s and s not in ('.', '..')]
        return self.cache_root.joinpath(*parts) if parts else self.cache_root

    def write_cache(self, p, buf):
        f = self.cache_path(p)
        if WRITE_GUARD:   # mtweb: çalışma kopyası da alan kotasına sayılır
            WRITE_GUARD(self.uid, len(buf) - (f.stat().st_size if f.is_file() else 0), not f.exists())
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(buf)
        return f

    def list(self, d):
        return self.run(lambda r: r.list(self.check(d)))

    def stat(self, p):
        return self.run(lambda r: r.stat(self.check(p)))

    def read(self, p, encoding='auto', fallback='windows-1254'):
        self.check(p)
        st = self.stat(p)
        if st['isDir']:
            raise RemoteError('EISDIR', 'Bu bir klasör')
        if st['size'] > MAX_FILE_BYTES:
            return {'tooLarge': True, 'size': st['size']}
        buf = self.run(lambda r: r.read_file(p))
        cp = self.write_cache(p, buf)
        d = decode(buf, encoding or 'auto', fallback or 'windows-1254')
        if d.get('binary'):
            return {'binary': True, 'size': len(buf), 'cachePath': public_path(cp)}
        return {**d, 'size': len(buf), 'mtime': st['mtime'], 'cachePath': public_path(cp)}

    def save(self, p, text, encoding='utf8', bom=False, expect=None, force=False, allow_lossy=False):
        self.check(p)
        if not allow_lossy and not can_encode(text, encoding or 'utf8'):
            return {'lossy': True}
        if expect and not force:
            st = None
            try:
                st = self.stat(p)
            except Exception:   # noqa: BLE001 — dosya silinmiş olabilir; yeniden oluşturulur
                st = None
            if st and ((expect.get('size') is not None and st['size'] != expect['size'])
                       or (expect.get('mtime') and st['mtime'] and abs(st['mtime'] - expect['mtime']) > 1500)):
                return {'conflict': True, 'size': st['size'], 'mtime': st['mtime']}
        buf = encode(text, encoding or 'utf8', bool(bom))
        self.run(lambda r: r.write_file(p, buf))
        cp = self.write_cache(p, buf)
        st = {'size': len(buf), 'mtime': mt.now_ms()}
        try:
            st = self.stat(p)
        except Exception:   # noqa: BLE001
            pass
        return {'ok': True, 'size': st['size'], 'mtime': st['mtime'], 'cachePath': public_path(cp)}

    def create_file(self, p):
        self.check(p)
        name = posixpath.basename(p)
        if any(e['name'] == name for e in self.list(posixpath.dirname(p) or '/')):
            raise RemoteError('EEXIST', 'EEXIST')
        self.run(lambda r: r.write_file(p, b''))

    def mkdir(self, p):
        return self.run(lambda r: r.mkdir(self.check(p)))

    def rename(self, a, b):
        self.run(lambda r: r.rename(self.check(a), self.check(b)))
        try:
            dst = self.cache_path(b)
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path(a).rename(dst)
        except OSError:
            pass

    def remove(self, p, is_dir):
        self.check(p)
        self.run(lambda r: (r.remove_dir(p) if is_dir else r.remove_file(p)))
        mt.rm(self.cache_path(p))

    def close(self):
        self.closed_by_user = True
        self.status = 'off'
        if self.remote:
            self.remote.close()


SESSIONS: dict[str, ProjectSession] = {}
BROWSERS: dict[str, Any] = {}


def _sweep():
    now = time.time()
    for k, s in list(SESSIONS.items()):
        if now - s.last > SESSION_IDLE:
            s.close()
            SESSIONS.pop(k, None)


def get_session(sid, user) -> ProjectSession:
    _sweep()
    s = SESSIONS.get(sid or '')
    if not s or s.uid != user['id']:
        raise HTTPException(404, 'Proje oturumu bulunamadı; pencereyi yeniden açın')
    s.last = time.time()
    return s


def wrap(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as err:   # noqa: BLE001
        raise HTTPException(400, friendly_error(err)) from None


# --- HTTP: depo, ayarlar, bağlantılar, klasörler -------------------------------------------------------------
class Body(BaseModel):
    model_config = {'extra': 'allow'}


def _b(body: Body) -> dict:
    return body.model_dump()


def _with_store(uid, s, **extra):
    return {'store': public_store(uid, s), **extra}


@router.get('/store')
def get_store(user=Depends(tools_user)):
    return public_store(user['id'])


@router.post('/settings')
def set_settings(body: Body, user=Depends(tools_user)):
    uid = user['id']
    patch = _b(body).get('patch') or {}
    s = load_store(uid)
    if 'editor' in patch:
        patch['editor'] = sanitize_editor(patch['editor'], s['settings']['editor'])
    if 'language' in patch:
        patch['language'] = _one(patch['language'], LANGS, None)
    if 'appTheme' in patch:
        patch['appTheme'] = _one(patch['appTheme'], ['dark', 'light', 'system'], 'system')
    s['settings'].update(patch)
    save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/save')
def conn_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    form = _b(body).get('form') or {}
    s = load_store(uid)
    c = find_conn(s, form.get('id')) if form.get('id') else None
    if not c:
        c = {'id': mt.uid8(), 'createdAt': mt.now_ms(), 'openTabs': []}
        s['connections'].append(c)
    kind = _one(form.get('kind'), KINDS, c.get('kind') or 'ssh')
    protocol = 'sftp' if kind == 'ssh' else _one(form.get('protocol'), list(PROTOCOLS), 'ftp') if kind == 'ftp' else None
    remote = kind in ('ssh', 'ftp')
    if c.get('host') and (c['host'] != form.get('host') or str(c.get('port')) != str(form.get('port')) or c.get('protocol') != protocol):
        c['hostKey'] = None
    local_path = mt.norm_rel(_str(form.get('localPath'), 2000)) if not remote and form.get('localPath') else ''
    c.update({
        'kind': kind,
        'name': _str(form.get('name'), 200) or (_str(form.get('host')) if remote else posixpath.basename(local_path)) or '—',
        'comments': str(form.get('comments') or '')[:4000],
        'folderId': form.get('folderId') if 'folderId' in form else c.get('folderId'),
        'color': form['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', str(form.get('color') or '')) else c.get('color') or '#22d3ee',
        'host': _str(form.get('host'), 255) if remote else '',
        'protocol': protocol,
        'port': _num(form.get('port'), PROTOCOLS[protocol], 1, 65535) if remote else None,
        'username': _str(form.get('username'), 200) if remote else '',
        'loginMethod': _one(form.get('loginMethod'), ['normal', 'anonymous'], 'normal') if kind == 'ftp' and protocol != 'sftp' else 'normal',
        'authType': 'key' if protocol == 'sftp' and form.get('authType') == 'key' else 'password',
        'keyPath': _str(form.get('keyPath'), 2000) if protocol == 'sftp' and form.get('authType') == 'key' else '',
        'nameEncoding': _one(form.get('nameEncoding'), ['auto', 'utf8', 'ascii'], 'auto') if kind == 'ftp' else 'auto',
        'rootDir': _str(form.get('rootDir'), 2000) if remote else '',
        'localPath': local_path,
        'showHidden': form.get('showHidden') is not False,
        'exclude': _str(form.get('exclude'), 1000),
        'restoreTabs': form.get('restoreTabs') is not False,
        'editorMode': 'custom' if form.get('editorMode') == 'custom' else 'global',
        'editor': sanitize_editor(form.get('editor'), s['settings']['editor']),
    })
    if not remote:
        c['password'] = ''
        c['passphrase'] = ''
        c['hostKey'] = None
    if form.get('password'):
        c['password'] = mt.protect(form['password'])
    if form.get('clearPassword'):
        c['password'] = ''
    if form.get('passphrase'):
        c['passphrase'] = mt.protect(form['passphrase'])
    if form.get('testedHostKey') and not c.get('hostKey'):
        c['hostKey'] = form['testedHostKey']
    save_store(uid, s)
    return _with_store(uid, s, id=c['id'])


@router.post('/conn/setLocalPath')
def conn_set_local(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    c = find_conn(s, b.get('id'))
    if c and c.get('kind') in ('local', 'file'):
        c['localPath'] = mt.norm_rel(_str(b.get('localPath'), 2000))
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/delete')
def conn_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    cid = _b(body).get('id')
    s = load_store(uid)
    s['connections'] = [c for c in s['connections'] if c['id'] != cid]
    for k, ses in list(SESSIONS.items()):
        if ses.uid == uid and ses.conn['id'] == cid:
            ses.close()
            SESSIONS.pop(k, None)
    mt.rm(mt.app_dir(APP, uid, 'cache') / str(cid))
    save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/duplicate')
def conn_duplicate(body: Body, user=Depends(tools_user)):
    uid = user['id']
    s = load_store(uid)
    c = find_conn(s, _b(body).get('id'))
    if c:
        s['connections'].append({**c, 'id': mt.uid8(), 'name': c['name'] + ' (kopya)', 'createdAt': mt.now_ms(), 'openTabs': [], 'activeTab': None})
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/move')
def conn_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    c = find_conn(s, b.get('id'))
    if c:
        c['folderId'] = b.get('folderId') or None
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/conn/test')
def conn_test(body: Body, user=Depends(tools_user)):
    uid = user['id']
    conn = merge_form(uid, load_store(uid), _b(body).get('form') or {})
    if conn.get('kind') in ('local', 'file'):
        return {'ok': True, 'ms': 0}
    if not conn.get('host'):
        return {'ok': False, 'message': 'Sunucu adresini girin.'}
    if conn.get('loginMethod') != 'anonymous' and not conn.get('username'):
        return {'ok': False, 'message': 'Kullanıcı adını girin (ya da anonim girişi seçin).'}
    started = time.time()
    remote = None
    try:
        remote = create_remote(uid, conn)
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
        root_ok = True
        if conn.get('rootDir'):
            try:
                remote.list(conn['rootDir'])
            except Exception:   # noqa: BLE001
                root_ok = False
        return {'ok': True, 'ms': ms, 'info': info, 'home': home, 'rootOk': root_ok, 'fingerprint': remote.fingerprint,
                'firstTime': bool(remote.fingerprint) and not conn.get('hostKey')}
    except Exception as err:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(err)}
    finally:
        if remote:
            remote.close()


@router.post('/folder/save')
def folder_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None) if b.get('id') else None
    if not f:
        f = {'id': mt.uid8(), 'parentId': b.get('parentId') or None}
        s['folders'].append(f)
    f['name'] = _str(b.get('name'), 200)
    save_store(uid, s)
    return _with_store(uid, s, id=f['id'])


@router.post('/folder/move')
def folder_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    p = b.get('parentId')
    while p:   # klasörü kendi alt klasörüne taşımayı engelle
        if p == b.get('id'):
            return _with_store(uid, s, ok=False)
        p = next((x for x in s['folders'] if x['id'] == p), {}).get('parentId')
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None)
    if f:
        f['parentId'] = b.get('parentId') or None
    save_store(uid, s)
    return _with_store(uid, s, ok=True)


@router.post('/folder/delete')
def folder_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    fid = _b(body).get('id')
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == fid), None)
    if f:   # içerik üst klasöre taşınır
        for c in s['connections']:
            if c.get('folderId') == fid:
                c['folderId'] = f.get('parentId') or None
        for sub in s['folders']:
            if sub.get('parentId') == fid:
                sub['parentId'] = f.get('parentId') or None
        s['folders'] = [x for x in s['folders'] if x['id'] != fid]
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/cache/clear')
def cache_clear(user=Depends(tools_user)):
    mt.rm(mt.app_dir(APP, user['id'], 'cache'))
    return {'ok': True}


@router.post('/keys/upload')
async def key_upload(file: UploadFile, user=Depends(tools_user)):
    """Özel anahtar dosyası: kullanıcının keys/ klasörüne; bağlantıda keyPath olarak dosya adı saklanır."""
    data = await file.read()
    if len(data) > 64 * 1024:
        raise HTTPException(413, 'Anahtar dosyası çok büyük')
    name = safe_name(file.filename, 'id_key')
    p = mt.app_dir(APP, user['id'], 'keys') / name
    p.write_bytes(data)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return {'path': name}


# --- Bağlantı formu: uzak klasör seçici ---------------------------------------------------------------------
@router.post('/browse/open')
def browse_open(body: Body, user=Depends(tools_user)):
    uid = user['id']
    conn = merge_form(uid, load_store(uid), _b(body).get('form') or {})
    try:
        remote = create_remote(uid, conn)
        remote.connect()
        try:
            home = remote.pwd()
        except Exception:   # noqa: BLE001
            home = '/'
        token = secrets.token_hex(8)
        BROWSERS[token] = {'remote': remote, 'uid': uid, 'at': time.time()}
        return {'ok': True, 'token': token, 'home': home, 'fingerprint': remote.fingerprint}
    except Exception as err:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(err)}


@router.post('/browse/list')
def browse_list(body: Body, user=Depends(tools_user)):
    b = _b(body)
    br = BROWSERS.get(b.get('token') or '')
    if not br or br['uid'] != user['id']:
        raise HTTPException(404, 'Oturum bulunamadı')
    return wrap(lambda: [{'name': x['name'], 'path': x['path']} for x in br['remote'].list(b.get('dir') or '/') if x['isDir']])


@router.post('/browse/close')
def browse_close(body: Body, user=Depends(tools_user)):
    br = BROWSERS.pop(_b(body).get('token') or '', None)
    if br:
        br['remote'].close()
    return {'ok': True}


# --- Proje penceresi -----------------------------------------------------------------------------------------
@router.post('/proj/open')
def proj_open(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    if b.get('prev'):
        old = SESSIONS.pop(b['prev'], None)
        if old and old.uid == uid:
            old.close()
    s = load_store(uid)
    try:
        conn = resolve_conn(uid, s, b.get('id'))
    except HTTPException as e:
        return {'ok': False, 'message': e.detail}

    def on_hostkey(fp):
        st = load_store(uid)
        c = find_conn(st, conn['id'])
        if c and fp and c.get('hostKey') != fp:
            c['hostKey'] = fp
            save_store(uid, st)

    ses = ProjectSession(uid, conn, on_hostkey)
    sid = secrets.token_urlsafe(12)
    try:
        info = ses.open()
    except Exception as err:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(err), 'code': getattr(err, 'code', None)}
    SESSIONS[sid] = ses
    return {'ok': True, 'sid': sid, **info, 'cacheRoot': public_path(ses.cache_root)}


@router.get('/proj/status')
def proj_status(sid: str, user=Depends(tools_user)):
    s = SESSIONS.get(sid)
    if not s or s.uid != user['id']:
        return {'status': 'off', 'gone': True}
    return {'status': s.status}


@router.post('/proj/reconnect')
def proj_reconnect(body: Body, user=Depends(tools_user)):
    s = get_session(_b(body).get('sid'), user)
    wrap(s.connect)
    return {'ok': True}


@router.post('/proj/list')
def proj_list(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.list(b.get('dir')))


@router.post('/proj/read')
def proj_read(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.read(b.get('path'), b.get('encoding') or 'auto', b.get('fallback') or 'windows-1254'))


@router.post('/proj/save')
def proj_save(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    return wrap(lambda: s.save(b.get('path'), str(b.get('text') or ''), b.get('encoding') or 'utf8', bool(b.get('bom')),
                               b.get('expect'), bool(b.get('force')), bool(b.get('allowLossy'))))


@router.post('/proj/newFile')
def proj_new_file(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    wrap(lambda: s.create_file(b.get('path')))
    return {'ok': True}


@router.post('/proj/mkdir')
def proj_mkdir(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    wrap(lambda: s.mkdir(b.get('path')))
    return {'ok': True}


@router.post('/proj/rename')
def proj_rename(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    wrap(lambda: s.rename(b.get('from'), b.get('to')))
    return {'ok': True}


@router.post('/proj/delete')
def proj_delete(body: Body, user=Depends(tools_user)):
    b = _b(body)
    s = get_session(b.get('sid'), user)
    wrap(lambda: s.remove(b.get('path'), bool(b.get('isDir'))))
    return {'ok': True}


@router.post('/proj/tabs')
def proj_tabs(body: Body, user=Depends(tools_user)):
    """Açık sekmeler (bir sonraki açılışta geri yüklenir)."""
    b = _b(body)
    s = SESSIONS.get(b.get('sid') or '')
    if not s or s.uid != user['id']:
        return {'ok': False}
    st = load_store(user['id'])
    c = find_conn(st, s.conn['id'])
    if c:
        c['openTabs'] = [x for x in (b.get('openTabs') or []) if isinstance(x, str)][:50]
        c['activeTab'] = b.get('activeTab') if isinstance(b.get('activeTab'), str) else None
        save_store(user['id'], st)
    return {'ok': True}


@router.get('/proj/cache')
def proj_cache(sid: str, path: str, user=Depends(tools_user)):
    """Çalışma kopyasını indir (masaüstünde Gezgin'de gösterilirdi)."""
    s = get_session(sid, user)
    f = s.cache_path(path)
    if not f.is_file():
        raise HTTPException(404, 'Çalışma kopyası yok')
    return FileResponse(f, filename=f.name)


@router.post('/proj/close')
def proj_close(body: Body, user=Depends(tools_user)):
    s = SESSIONS.pop(_b(body).get('sid') or '', None)
    if s and s.uid == user['id']:
        s.close()
    return {'ok': True}


# Yetki denetimi (test_permissions) için hafif uç: kullanıcı dosya alanının kökü
@router.get('/files')
def files(user=Depends(tools_user)):
    return mt.list_dir(mt.files_root(APP, user['id']), '/')
