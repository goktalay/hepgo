"""Test için yerel SSH sunucusu (paramiko): parola kimliği, basit kabuk ve SFTP (kök: verilen klasör).

Kabuk gerçek bir kabuk değildir: satır satır okur, `echo …`, `pwd`, `ls` ve `uname` karşılıklarını yanıtlar; diğer komutlar
için "komut yok" yazar. Yalnız 127.0.0.1'de dinler; testler bitince `stop()` ile kapanır (arka planda süreç kalmaz).

Kullanım: srv = SshServer(root, user='test', password='parola'); srv.start(); … srv.stop()
"""
import os
import socket
import threading
import time
from pathlib import Path

import paramiko
from paramiko.sftp_attr import SFTPAttributes
from paramiko.sftp_handle import SFTPHandle
from paramiko.sftp_server import SFTPServer
from paramiko.sftp_si import SFTPServerInterface

HOST_KEY = paramiko.RSAKey.generate(2048)


class _Iface(paramiko.ServerInterface):
    def __init__(self, user, password, log, root):
        self.user, self.password, self.log, self.root = user, password, log, root

    def check_auth_password(self, username, password):
        ok = username == self.user and password == self.password
        self.log.append(('auth', username, ok))
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_request(self, kind, chanid):
        self.log.append(('channel', kind))
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, *a):
        return True

    def check_channel_shell_request(self, channel):
        self.log.append(('shell',))
        threading.Thread(target=_shell, args=(channel, self.root), daemon=True).start()
        return True

    def check_channel_exec_request(self, channel, command):
        self.log.append(('exec', command.decode('utf-8', 'replace')))

        def run():
            time.sleep(0.1)
            channel.sendall(b'Linux 6.0-test\ntest-sunucu\n')
            channel.send_exit_status(0)
            channel.close()
        threading.Thread(target=run, daemon=True).start()
        return True

    def check_channel_window_change_request(self, *a):
        return True

    def check_port_forward_request(self, address, port):
        self.log.append(('port-forward', address, port))
        return False

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        self.log.append(('direct-tcpip', destination))
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_x11_request(self, *a):
        self.log.append(('x11',))
        return False

    def check_channel_forward_agent_request(self, channel):
        self.log.append(('agent',))
        return False


class _Handle(SFTPHandle):
    def stat(self):
        return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno() if hasattr(self, 'readfile') else self.writefile.fileno()))


class _Sftp(SFTPServerInterface):
    ROOT = '/'

    def _real(self, p):
        p = self.canonicalize(p)
        return os.path.join(self.ROOT, p.lstrip('/'))

    def canonicalize(self, path):
        return os.path.normpath('/' + (path or '/')).replace('//', '/')

    def list_folder(self, path):
        out = []
        real = self._real(path)
        for n in sorted(os.listdir(real)):
            a = SFTPAttributes.from_stat(os.stat(os.path.join(real, n)))
            a.filename = n
            out.append(a)
        return out

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    lstat = stat

    def open(self, path, flags, attr):
        real = self._real(path)
        try:
            mode = 'r+b' if flags & os.O_RDWR else 'wb' if flags & os.O_WRONLY else 'rb'
            if flags & os.O_WRONLY or flags & os.O_RDWR:
                fd = os.open(real, flags, 0o644)
                f = os.fdopen(fd, mode)
            else:
                f = open(real, 'rb')
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        h = _Handle(flags)
        h.filename = real
        h.readfile = f
        h.writefile = f
        return h

    def remove(self, path):
        os.remove(self._real(path))
        return paramiko.SFTP_OK

    def mkdir(self, path, attr):
        os.mkdir(self._real(path))
        return paramiko.SFTP_OK

    def rmdir(self, path):
        os.rmdir(self._real(path))
        return paramiko.SFTP_OK

    def rename(self, a, b):
        os.rename(self._real(a), self._real(b))
        return paramiko.SFTP_OK


def _shell(chan, root):
    cwd = '/'
    time.sleep(0.3)   # kabuk isteği yanıtı istemciye ulaşsın
    chan.sendall(b'Test SSH sunucusu\r\n$ ')
    buf = b''
    try:
        while True:
            d = chan.recv(1024)
            if not d:
                break
            chan.sendall(d.replace(b'\r', b'\r\n'))   # yankı
            buf += d
            while b'\r' in buf or b'\n' in buf:
                i = min(x for x in (buf.find(b'\r'), buf.find(b'\n')) if x >= 0)
                line, buf = buf[:i].decode('utf-8', 'replace').strip(), buf[i + 1:]
                if not line:
                    chan.sendall(b'$ ')
                    continue
                if line.startswith(' __sm_osc7') or line.startswith('__sm_osc7'):
                    out = ''
                elif line.startswith('echo '):
                    out = line[5:].strip('\'"') + '\n'
                elif line == 'pwd':
                    out = cwd + '\n'
                elif line == 'ls':
                    out = '  '.join(sorted(os.listdir(root))) + '\n'
                elif line.startswith('uname'):
                    out = 'Linux 6.0-test\n'
                elif line in ('exit', 'logout'):
                    chan.sendall(b'logout\r\n')
                    chan.close()
                    return
                else:
                    out = f'{line.split()[0]}: komut yok\n'
                chan.sendall(out.replace('\n', '\r\n').encode('utf-8') + b'$ ')
    except (OSError, EOFError):
        pass


class SshServer:
    def __init__(self, root, user='test', password='parola'):
        self.root, self.user, self.password = str(root), user, password
        self.log = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        self.transports = []
        self.alive = False

    def start(self):
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def _accept(self):
        while self.alive:
            try:
                c, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        t = paramiko.Transport(c)
        self.transports.append(t)
        t.add_server_key(HOST_KEY)
        root = self.root

        class S(_Sftp):
            ROOT = root
        t.set_subsystem_handler('sftp', SFTPServer, S)
        iface = _Iface(self.user, self.password, self.log, root)
        try:
            t.start_server(server=iface)
        except Exception:   # noqa: BLE001
            return
        chans = []   # kabul edilen kanallar tutulur (çöp toplayıcı kapatmasın); işleri istek işleyicilerinde
        while t.is_active() and self.alive:
            ch = t.accept(1)
            if ch is not None:
                chans.append(ch)

    def stop(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass
        for t in self.transports:
            try:
                t.close()
            except Exception:   # noqa: BLE001
                pass


if __name__ == '__main__':   # elle deneme: python -m tests.mtweb_sshd <klasör>
    import sys
    import time
    s = SshServer(Path(sys.argv[1] if len(sys.argv) > 1 else '.')).start()
    print('ssh 127.0.0.1', s.port, 'test / parola')
    try:
        time.sleep(3600)
    finally:
        s.stop()
