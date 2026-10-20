"""Araçlar › SSH Master (web) — paramiko arka ucu (masaüstü main.js'teki ssh2 mantığının karşılığı).

WebSocket /ws/tools/ssh: tek bağlantı = bir terminal penceresi; her çağrı bölme kimliği (pane) taşır.
  metin  {t:'call', id, m, a}  → {t:'ret', id, ok, v|e, store?}     (ssh:start, sftp:*)
  metin  {t:'send', m, a}      → yanıt yok                            (ssh:resize, ssh:stop, ssh:lastDir, transfer:cancel)
  ikili  [1B uzunluk][pane][veri]  → kabuğa yazılır; sunucudan aynı biçimde kabuk çıktısı gelir
  olay   {t:'ev', ch, d}       (ssh:closed, transfer:progress)
Kimlik: parola / özel anahtar (+parola); klavye etkileşimli parola ile tamamlanır. Host anahtarı: bağlantı kaydındaki
parmak izi (sha256/base64) ile karşılaştırılır; yeni sunucular DATA_DIR/tools/ssh_known_hosts'a eklenir (AutoAdd).
SFTP: bölmenin ana kanalı listeleme için; her aktarım kendi SFTP kanalını açar (iptal = kanalı kapatmak).
Hatalar renderer i18n anahtarlarıyla ({$t: 'main.errAuth'}) döner; parola DB'ye şifreli (Fernet) yazılır, arayüze gitmez.
"""
import asyncio
import base64
import errno
import hashlib
import json
import posixpath
import socket
import stat as st_mod
import threading
import time
from pathlib import Path

import paramiko
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from . import tools_common as tc
from . import tools_mt
from .tools_common import TOOLS_DIR, tools_user, ws_user
from .tools_mt import T, MtError

router = APIRouter(prefix='/api/tools/ssh')
ws_router = APIRouter()
APP = 'sshmaster'

# Kabuk her prompt'ta OSC 7 ile bulunduğu klasörü bildirir (bash + zsh) — main.js ile aynı
OSC7_INIT = ("__sm_osc7(){ printf '\\033]7;file://%s\\007' \"$PWD\"; }; "
             'PROMPT_COMMAND="__sm_osc7${PROMPT_COMMAND:+;$PROMPT_COMMAND}"; '
             'precmd_functions+=(__sm_osc7) 2>/dev/null')
CHUNK = 256 * 1024
KNOWN_HOSTS = None   # mtweb kancası: callable(uid) → kullanıcıya ayrı known_hosts yolu (HEPGO: ortak dosya)


@router.get('/status')
def status(user=Depends(tools_user)):
    return {'backend': 'paramiko', 'available': True, 'version': paramiko.__version__}


# ---------------------------------------------------------------------------
# Bağlantı yardımcıları
# ---------------------------------------------------------------------------
class HostKeyMismatch(Exception):
    def __init__(self, old, new):
        super().__init__('HOSTKEY')
        self.old, self.new = old, new


class Cancelled(Exception):
    pass


def fingerprint(key) -> str:
    return base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode('ascii')


def known_hosts_path(uid=None) -> Path:
    p = KNOWN_HOSTS(uid) if KNOWN_HOSTS is not None else TOOLS_DIR / 'ssh_known_hosts'
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch()
    return p


class _Policy(paramiko.MissingHostKeyPolicy):
    """Bilinmeyen host anahtarı: kayıtlı parmak iziyle çelişiyorsa reddet, değilse known_hosts'a ekle (AutoAdd)."""
    def __init__(self, conn, uid=None):
        self.conn, self.uid = conn, uid

    def missing_host_key(self, client, hostname, key):
        fp = fingerprint(key)
        if self.conn.get('hostKey') and self.conn['hostKey'] != fp and not self.conn.get('acceptNewHostKey'):
            raise HostKeyMismatch(self.conn['hostKey'], fp)
        client.get_host_keys().add(hostname, key.get_name(), key)
        try:
            client.save_host_keys(str(known_hosts_path(self.uid)))
        except OSError:
            pass


def load_pkey(uid, key_path, passphrase):
    """Özel anahtar: kullanıcının kişisel alanındaki (H:\\) dosyadan."""
    try:
        real = tools_mt.to_real(uid, key_path)
    except MtError:
        raise FileNotFoundError(key_path) from None
    if not real.is_file():
        raise FileNotFoundError(key_path)
    return paramiko.PKey.from_path(str(real), passphrase=passphrase or None)


def connect_client(uid, conn, app=APP):
    """Çözülmüş bağlantı kaydıyla paramiko SSHClient açar; (client, fingerprint) döner.
    mtweb: soket NET kancasının doğruladığı IP'ye önceden açılır (hostname yalnız known_hosts anahtarı olarak kalır);
    ajan / port yönlendirme / X11 hiçbir zaman istenmez (allow_agent=False, yalnız kabuk + SFTP kanalı açılır)."""
    host = str(conn.get('host') or '').strip()
    port = int(conn.get('port') or 22)
    username = str(conn.get('username') or '').strip()
    client = paramiko.SSHClient()
    client.load_host_keys(str(known_hosts_path(uid)))
    client.set_missing_host_key_policy(_Policy(conn, uid))
    kw = dict(hostname=host, port=port, username=username, timeout=15, banner_timeout=15, auth_timeout=20,
              allow_agent=False, look_for_keys=False)
    if conn.get('authType') == 'key' and conn.get('keyPath'):
        kw['pkey'] = load_pkey(uid, conn['keyPath'], conn.get('passphrase'))
    else:
        kw['password'] = conn.get('password') or ''
    sock = tc.net_socket(host, port, 15, uid, app)
    if sock is not None:
        kw['sock'] = sock
    try:
        client.connect(**kw)
    except BaseException:
        if sock is not None:
            sock.close()
        raise
    t = client.get_transport()
    t.set_keepalive(20)
    fp = fingerprint(t.get_remote_server_key())
    if conn.get('hostKey') and conn['hostKey'] != fp and not conn.get('acceptNewHostKey'):
        client.close()
        raise HostKeyMismatch(conn['hostKey'], fp)
    return client, fp


def friendly_error(err):
    """ssh2 hatalarının main.js'teki karşılığı: renderer i18n anahtarı (ya da ham metin)."""
    msg = str(err) or err.__class__.__name__
    if isinstance(err, tc.NetDenied):
        return msg
    if isinstance(err, HostKeyMismatch):
        return T('main.errHostKey', old=err.old, new=err.new)
    if isinstance(err, paramiko.BadHostKeyException):
        return T('main.errHostKey', old=fingerprint(err.expected_key), new=fingerprint(err.key))
    if isinstance(err, paramiko.AuthenticationException) or 'uthentication' in msg and 'failed' in msg:
        return T('main.errAuth')
    if isinstance(err, paramiko.ssh_exception.NoValidConnectionsError):
        inner = list(err.errors.values())
        return friendly_error(inner[0]) if inner else T('main.errRefused')
    if isinstance(err, socket.gaierror) or 'getaddrinfo' in msg or 'Name or service not known' in msg:
        return T('main.errDns')
    if isinstance(err, ConnectionRefusedError) or 'refused' in msg.lower():
        return T('main.errRefused')
    if isinstance(err, (socket.timeout, TimeoutError)) or 'timed out' in msg.lower() or 'Timeout' in msg:
        return T('main.errTimeout')
    if getattr(err, 'errno', None) in (errno.EHOSTUNREACH, errno.ENETUNREACH) or 'unreachable' in msg.lower():
        return T('main.errUnreach')
    if isinstance(err, FileNotFoundError):
        return T('main.errKeyFile')
    if isinstance(err, paramiko.PasswordRequiredException):
        return T('main.errAuth')
    return msg


def test_connection(uid, store, form):
    """conn:test — bağlan, 'uname -sr; hostname' ile sunucu bilgisi al."""
    conn = tools_mt.merge_form_with_stored(store, form)
    if not conn.get('host') or not conn.get('username'):
        return {'ok': False, 'message': T('main.errHostUser')}
    started = time.time()
    try:
        client, fp = connect_client(uid, conn)
    except Exception as e:   # noqa: BLE001
        return {'ok': False, 'message': friendly_error(e)}
    info = ''
    try:
        _, out, _ = client.exec_command('uname -sr 2>/dev/null; hostname 2>/dev/null', timeout=10)
        info = ' · '.join(x for x in out.read().decode('utf-8', 'replace').strip().split('\n') if x)
    except Exception:   # noqa: BLE001
        pass
    client.close()
    return {'ok': True, 'ms': int((time.time() - started) * 1000), 'fingerprint': fp, 'info': info, 'firstTime': not conn.get('hostKey')}


# ---------------------------------------------------------------------------
# SFTP yardımcıları
# ---------------------------------------------------------------------------
def sftp_entry(d, e):
    mode = e.st_mode or 0
    return {'name': e.filename, 'path': posixpath.join(d, e.filename), 'isDir': st_mod.S_ISDIR(mode), 'isLink': st_mod.S_ISLNK(mode),
            'size': e.st_size or 0, 'mtime': int((e.st_mtime or 0) * 1000)}


def remote_walk(sftp, root):
    """root altındaki tüm dosyaları (rel, size) ve klasörleri verir."""
    files, dirs, queue = [], [''], ['']
    while queue:
        rel = queue.pop(0)
        for e in sftp.listdir_attr(posixpath.join(root, rel) if rel else root):
            r = posixpath.join(rel, e.filename) if rel else e.filename
            mode = e.st_mode or 0
            if st_mod.S_ISDIR(mode):
                dirs.append(r)
                queue.append(r)
            elif st_mod.S_ISREG(mode):
                files.append((r, e.st_size or 0))
    return files, dirs


def local_walk(root: Path):
    files, dirs, queue = [], [''], ['']
    while queue:
        rel = queue.pop(0)
        for e in sorted((root / rel).iterdir() if rel else root.iterdir()):
            r = f'{rel}/{e.name}' if rel else e.name
            if e.is_dir():
                dirs.append(r)
                queue.append(r)
            elif e.is_file():
                files.append((r, e.stat().st_size))
    return files, dirs


def remote_exists(sftp, p):
    try:
        sftp.stat(p)
        return True
    except OSError:
        return False


def unique_remote_path(sftp, p):
    if not remote_exists(sftp, p):
        return p
    d, base = posixpath.split(p)
    stem, ext = posixpath.splitext(base)
    i = 1
    while True:
        cand = posixpath.join(d, f'{stem} ({i}){ext}')
        if not remote_exists(sftp, cand):
            return cand
        i += 1


def remote_remove(sftp, p):
    try:
        st = sftp.lstat(p)
    except OSError:
        return
    if not st_mod.S_ISDIR(st.st_mode or 0):
        sftp.remove(p)
        return
    files, dirs = remote_walk(sftp, p)
    for rel, _ in files:
        sftp.remove(posixpath.join(p, rel))
    for d in sorted(dirs, key=len, reverse=True):
        sftp.rmdir(posixpath.join(p, d) if d else p)


def xfer_download(sftp, remote, local: Path, step, job):
    check = job.get('space')   # mtweb: alan kotası (parça parça)
    if check:
        check(0, True)
    with sftp.open(remote, 'rb') as rf:
        size = rf.stat().st_size
        rf.prefetch(size)
        with open(local, 'wb') as lf:
            while True:
                if job['cancelled']:
                    raise Cancelled()
                b = rf.read(CHUNK)
                if not b:
                    break
                if check:
                    try:
                        check(len(b), False)
                    except MtError:   # kota aşıldı: yarım dosya kalmasın
                        lf.close()
                        local.unlink(missing_ok=True)
                        raise
                lf.write(b)
                step(len(b))


def xfer_upload(sftp, local: Path, remote, step, job):
    with open(local, 'rb') as lf, sftp.open(remote, 'wb') as wf:
        wf.set_pipelined(True)
        while True:
            if job['cancelled']:
                raise Cancelled()
            b = lf.read(CHUNK)
            if not b:
                break
            wf.write(b)
            step(len(b))


# ---------------------------------------------------------------------------
# Terminal penceresi: bir WebSocket, birden çok bölme (pane) → her biri kendi SSH bağlantısı
# ---------------------------------------------------------------------------
class Window:
    def __init__(self, ws, user, lang):
        self.ws, self.user, self.lang = ws, user, lang
        self.uid = user['id']
        self.loop = asyncio.get_running_loop()
        self.q = asyncio.Queue()
        self.sessions = {}    # pane → dict(client, chan, sftp, conn, wq)
        self.transfers = {}   # id → job
        self.lock = threading.Lock()
        self.closed = False

    # --- arayüze ileti (iş parçacığından güvenli) ---
    def emit(self, item):
        if not self.closed:
            self.loop.call_soon_threadsafe(self.q.put_nowait, item)

    def event(self, ch, d):
        self.emit({'t': 'ev', 'ch': ch, 'd': d})

    @staticmethod
    def frame(pane, data: bytes) -> bytes:
        p = pane.encode('utf-8')
        return bytes([len(p)]) + p + data

    async def sender(self):
        while True:
            item = await self.q.get()
            if isinstance(item, (bytes, bytearray)):
                await self.ws.send_bytes(bytes(item))
            else:
                await self.ws.send_text(json.dumps(item, ensure_ascii=False))

    # --- oturumlar ---
    def session(self, pane):
        s = self.sessions.get(pane)
        if not s:
            raise MtError(T('main.errNoSession'))
        return s

    def close_session(self, pane):
        s = self.sessions.pop(pane, None)
        if not s:
            return
        try:
            s['wq'].put(None)
        except Exception:   # noqa: BLE001
            pass
        if s.get('release'):
            s['release']()
        for step in (lambda: s['chan'] and s['chan'].close(), lambda: s['sftp'] and s['sftp'].close(), s['client'].close):
            try:
                step()
            except Exception:   # noqa: BLE001
                pass

    def close_all(self):
        self.closed = True
        for pane in list(self.sessions):
            self.close_session(pane)
        for job in list(self.transfers.values()):
            self.cancel_job(job)

    def pane_sftp(self, pane):
        s = self.session(pane)
        with s['lock']:
            if s['sftp'] is None or s['sftp'].sock.closed:
                s['sftp'] = s['client'].open_sftp()
            return s['sftp']

    def _reader(self, pane, s):
        chan = s['chan']
        try:
            while True:
                data = chan.recv(65536)
                if not data:
                    break
                self.emit(self.frame(pane, data))
        except Exception:   # noqa: BLE001
            pass
        finally:
            if self.sessions.get(pane) is s:
                self.close_session(pane)
                self.event('ssh:closed', {'pane': pane})

    def _writer(self, s):
        while True:
            d = s['wq'].get()
            if d is None:
                break
            try:
                s['chan'].sendall(d)
            except Exception:   # noqa: BLE001
                break

    # --- ssh:start ---
    def ssh_start(self, a):
        import queue
        pane, conn_id = str(a.get('pane')), a.get('connId')
        self.close_session(pane)
        store = tools_mt.read_store(self.uid, APP, self.lang)
        try:
            conn = tools_mt.resolve_connection(store, conn_id)
        except MtError as e:
            return {'ok': False, 'message': e.msg}, None
        try:
            release = tc.conn_slot(self.uid, APP)
        except Exception as e:   # noqa: BLE001 — eşzamanlı oturum sınırı (mtweb)
            return {'ok': False, 'message': friendly_error(e)}, None
        try:
            client, fp = connect_client(self.uid, conn)
        except Exception as e:   # noqa: BLE001
            release()
            return {'ok': False, 'message': friendly_error(e)}, None
        pub = tools_mt.remember_host_key(self.uid, APP, conn_id, fp)
        try:
            chan = client.invoke_shell(term='xterm-256color', width=int(a.get('cols') or 120), height=int(a.get('rows') or 30))
        except Exception as e:   # noqa: BLE001
            client.close()
            release()
            return {'ok': False, 'message': friendly_error(e)}, pub
        s = {'client': client, 'chan': chan, 'sftp': None, 'conn': conn, 'wq': queue.Queue(), 'lock': threading.Lock(), 'release': release}
        self.sessions[pane] = s
        if self.closed:   # pencere bu çağrı sürerken kapandı (close_all önce çalıştı): oturum sızmasın, eşzamanlı oturum yuvası bırakılsın
            self.close_session(pane)
            return {'ok': False, 'message': T('main.errNoSession')}, pub
        threading.Thread(target=self._reader, args=(pane, s), daemon=True, name=f'ssh-rd-{pane}').start()
        threading.Thread(target=self._writer, args=(s,), daemon=True, name=f'ssh-wr-{pane}').start()
        if conn.get('rememberLastDir'):   # son klasörü takip et / oraya git
            init = ' ' + OSC7_INIT
            if conn.get('lastDir'):
                init += f"; cd -- {tools_mt.shq(conn['lastDir'])} 2>/dev/null"
            init += '; clear\r'
            s['wq'].put(init.encode('utf-8'))
        tools_mt.audit(self.uid, 'SSH Master bağlantısı açtı', f"{conn.get('username')}@{conn.get('host')}:{conn.get('port')}")
        return {'ok': True, 'startDir': conn.get('lastDir') if conn.get('rememberLastDir') and conn.get('lastDir') else None,
                'name': conn.get('name'), 'host': conn.get('host'), 'username': conn.get('username')}, pub

    # --- gönderimler (yanıtsız) ---
    def on_send(self, m, a):
        a = a or {}
        if m == 'ssh:resize':
            s = self.sessions.get(str(a.get('pane')))
            if s:
                try:
                    s['chan'].resize_pty(width=int(a.get('cols') or 80), height=int(a.get('rows') or 24))
                except Exception:   # noqa: BLE001
                    pass
        elif m == 'ssh:stop':
            self.close_session(str(a.get('pane')))
        elif m == 'ssh:lastDir':
            s = self.sessions.get(str(a.get('pane')))
            d = a.get('dir')
            if s and d and s['conn'].get('rememberLastDir') and s['conn'].get('lastDir') != d:
                s['conn']['lastDir'] = d
                cid = s['conn']['id']

                def fn(store):
                    c = next((x for x in store['connections'] if x.get('id') == cid), None)
                    if c and c.get('rememberLastDir'):
                        c['lastDir'] = d
                tools_mt.with_store(self.uid, APP, fn)
        elif m == 'transfer:cancel':
            job = self.transfers.get(a if isinstance(a, str) else a.get('id'))
            if job:
                self.cancel_job(job)

    def write_bytes(self, raw: bytes):
        n = raw[0]
        pane = raw[1:1 + n].decode('utf-8', 'replace')
        s = self.sessions.get(pane)
        if s:
            s['wq'].put(bytes(raw[1 + n:]))

    # --- çağrılar ---
    def call(self, m, a):
        a = a or {}
        if m == 'ssh:start':
            return self.ssh_start(a)
        pane = str(a.get('pane'))
        if m == 'sftp:realpath':
            return self.pane_sftp(pane).normalize(a.get('p') or '.'), None
        if m == 'sftp:list':
            d = a.get('dir') or '/'
            sftp = self.pane_sftp(pane)
            try:
                return [sftp_entry(d, e) for e in sftp.listdir_attr(d)], None
            except Exception as e:   # noqa: BLE001
                raise MtError(friendly_error(e)) from None
        if m == 'sftp:stat':
            st = self.pane_sftp(pane).stat(a.get('p'))
            return {'isDir': st_mod.S_ISDIR(st.st_mode or 0), 'size': st.st_size or 0}, None
        if m == 'sftp:mkdir':
            self.pane_sftp(pane).mkdir(a.get('p'))
            return True, None
        if m == 'sftp:rename':
            self.pane_sftp(pane).rename(a.get('from'), a.get('to'))
            return True, None
        if m == 'sftp:delete':
            sftp = self.pane_sftp(pane)
            if not a.get('isDir'):
                sftp.remove(a.get('p'))
            else:
                remote_remove(sftp, a.get('p'))
            return True, None
        if m == 'sftp:download':
            return self.download(a), None
        if m == 'sftp:upload':
            return self.upload(a), None
        raise MtError(f'Bilinmeyen kanal: {m}')

    # --- aktarımlar: her aktarım kendi SFTP kanalını açar; iptal kanalı kapatır ---
    def progress(self, base):
        state = {**base, 'phase': 'scan', 'total': 0, 'done': 0, 'files': 0, 'fileIndex': 0, 'current': '', 'error': None}
        last = [0.0]

        def send():
            self.event('transfer:progress', dict(state))

        def add(n):
            state['done'] += n
            now = time.time()
            if now - last[0] > 0.15:
                last[0] = now
                send()

        def file(i, rel):
            state['fileIndex'] = i
            state['current'] = rel
            send()

        def finish(phase, error=None):
            state['phase'] = phase
            state['error'] = error
            send()
        return state, send, add, file, finish

    def cancel_job(self, job):
        job['cancelled'] = True
        try:
            if job.get('sftp'):
                job['sftp'].close()
        except Exception:   # noqa: BLE001
            pass

    def run_transfer(self, a, kind, name, work, cleanup):
        tid, pane = a.get('id'), str(a.get('pane'))
        job = {'cancelled': False, 'sftp': None, 'space': tools_mt.space_check(self.uid, APP) if kind == 'download' else None}
        self.transfers[tid] = job
        state, send, add, file, finish = self.progress({'id': tid, 'pane': pane, 'kind': kind, 'name': name})
        send()
        try:
            s = self.session(pane)
            job['sftp'] = s['client'].open_sftp()
            work(job['sftp'], state, send, add, file, job)
            if job['cancelled']:
                raise Cancelled()
            finish('done')
            return {'ok': True}
        except Exception as e:   # noqa: BLE001
            if job['cancelled'] or isinstance(e, Cancelled):
                for _ in range(8):
                    try:
                        cleanup()
                        break
                    except Exception:   # noqa: BLE001
                        time.sleep(0.5)
                finish('cancelled')
                return {'ok': False, 'cancelled': True}
            msg = e.msg if isinstance(e, MtError) else friendly_error(e)
            finish('error', msg)
            return {'ok': False, 'message': msg}
        finally:
            self.transfers.pop(tid, None)
            try:
                if job['sftp']:
                    job['sftp'].close()
            except Exception:   # noqa: BLE001
                pass

    def download(self, a):
        remote = a.get('remotePath')
        name = tools_mt.safe_segment(posixpath.basename(str(remote or '').rstrip('/')))
        local_dir = tools_mt.to_real(self.uid, a.get('localDir'))
        target = [None]

        def work(sftp, state, send, add, file, job):
            st = sftp.stat(remote)
            target[0] = tools_mt.unique_local_path(local_dir / name)
            if st_mod.S_ISDIR(st.st_mode or 0):
                files, dirs = remote_walk(sftp, remote)
                state.update(phase='transfer', total=sum(s for _, s in files), files=len(files))
                send()
                for d in dirs:
                    tools_mt.safe_join(target[0], d).mkdir(parents=True, exist_ok=True)
                for i, (rel, _) in enumerate(files):
                    if job['cancelled']:
                        raise Cancelled()
                    file(i + 1, rel)
                    xfer_download(sftp, posixpath.join(remote, rel), tools_mt.safe_join(target[0], rel), add, job)
            else:
                state.update(phase='transfer', total=st.st_size or 0, files=1, fileIndex=1, current=name)
                send()
                xfer_download(sftp, remote, target[0], add, job)

        def cleanup():   # iptalde yarım inen dosya/klasörü sil
            if target[0] and target[0].exists():
                if target[0].is_dir():
                    import shutil
                    shutil.rmtree(target[0], ignore_errors=True)
                else:
                    target[0].unlink(missing_ok=True)
        return self.run_transfer(a, 'download', name, work, cleanup)

    def upload(self, a):
        local = tools_mt.to_real(self.uid, a.get('localPath'))
        name = local.name
        remote_dir = a.get('remoteDir') or '/'
        target = [None]
        pane = str(a.get('pane'))

        def work(sftp, state, send, add, file, job):
            if not local.exists():
                raise MtError(f'Dosya bulunamadı: {name}')
            target[0] = unique_remote_path(sftp, posixpath.join(remote_dir, name))
            if local.is_dir():
                files, dirs = local_walk(local)
                state.update(phase='transfer', total=sum(s for _, s in files), files=len(files))
                send()
                for d in dirs:
                    try:
                        sftp.mkdir(posixpath.join(target[0], d) if d else target[0])
                    except OSError:
                        pass   # zaten var
                for i, (rel, _) in enumerate(files):
                    if job['cancelled']:
                        raise Cancelled()
                    file(i + 1, rel)
                    xfer_upload(sftp, local / rel, posixpath.join(target[0], rel), add, job)
            else:
                state.update(phase='transfer', total=local.stat().st_size, files=1, fileIndex=1, current=name)
                send()
                xfer_upload(sftp, local, target[0], add, job)

        def cleanup():   # iptalde sunucuya yarım yüklenen hedefi, bölmenin ana SFTP kanalıyla sil
            if target[0]:
                remote_remove(self.pane_sftp(pane), target[0])
        try:
            return self.run_transfer(a, 'upload', name, work, cleanup)
        finally:
            tools_mt.cleanup_upload_tmp(self.uid, local)


async def _reject(ws, msg, code=4403):
    try:
        await ws.send_text(json.dumps({'t': 'ev', 'ch': 'error', 'd': msg}))
        await ws.close(code=code)
    except Exception:   # noqa: BLE001
        pass


@ws_router.websocket('/ws/tools/ssh')
async def ws_ssh(ws: WebSocket):
    await ws.accept()
    user = await ws_user(ws)
    if not user:
        return await _reject(ws, 'Yetkisiz: Araçlar modülü yetkisi gerekir.')
    win = Window(ws, user, tools_mt.ws_ctx(user, APP)['lang'])
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
            if msg.get('bytes'):
                win.write_bytes(msg['bytes'])
                continue
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
        sender.cancel()
        # Ayrı iş parçacığında, beklemeden başlatılır: bağlantı koparken görev iptal edilse de (CancelledError) oturumlar mutlaka kapanır,
        # eşzamanlı oturum yuvaları (mtweb kotası) bırakılır.
        threading.Thread(target=win.close_all, daemon=True, name='ssh-close-all').start()
