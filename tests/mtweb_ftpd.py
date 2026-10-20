"""Test için küçük FTP sunucusu (yalnız 127.0.0.1, pasif kip): USER/PASS, SYST, PWD, CWD, TYPE, OPTS, NOOP, PASV, LIST,
RETR, STOR, SIZE, MKD, DELE, QUIT. MLSD desteklemez (istemci LIST'e düşer).

`pasv_ip` PASV yanıtında İLAN EDİLEN adrestir (ör. '10.0.0.1'): güvenli istemci bunu yok sayıp kontrol bağlantısının IP'sine
bağlanmalıdır. `pasv_port` verilirse yanıttaki port odur (engelli port testi). Testler bitince stop().
"""
import os
import socket
import threading
import time


class FtpServer:
    def __init__(self, root, user='test', password='parola', pasv_ip='127.0.0.1', pasv_port=None):
        self.root, self.user, self.password = str(root), user, password
        self.pasv_ip, self.pasv_port = pasv_ip, pasv_port
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.alive = False
        self.log = []
        self.data_peers = []

    def start(self):
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass

    def _accept(self):
        while self.alive:
            try:
                c, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        f = c.makefile('rb')
        cwd = '/'
        data_srv = None
        authed = False

        def send(line):
            c.sendall((line + '\r\n').encode('utf-8'))

        def data_conn():
            data_srv.settimeout(10)
            d, peer = data_srv.accept()
            self.data_peers.append(peer[0])
            return d

        def real(p):
            p = p if p.startswith('/') else os.path.join(cwd, p)
            p = os.path.normpath(p)
            return os.path.join(self.root, p.lstrip('/'))

        send('220 test ftp')
        try:
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                cmd, _, arg = line.partition(' ')
                cmd = cmd.upper()
                self.log.append(cmd)
                if cmd == 'USER':
                    send('331 parola')
                elif cmd == 'PASS':
                    authed = arg == self.password
                    send('230 tamam' if authed else '530 Login incorrect')
                elif not authed and cmd not in ('QUIT',):
                    send('530 giriş yok')
                elif cmd == 'SYST':
                    send('215 UNIX Type: L8')
                elif cmd in ('OPTS', 'TYPE', 'NOOP'):
                    send('200 tamam')
                elif cmd == 'PWD':
                    send(f'257 "{cwd}"')
                elif cmd == 'CWD':
                    if os.path.isdir(real(arg)):
                        cwd = os.path.normpath(arg if arg.startswith('/') else os.path.join(cwd, arg))
                        send('250 tamam')
                    else:
                        send('550 yok')
                elif cmd == 'PASV':
                    data_srv = socket.socket()
                    data_srv.bind(('127.0.0.1', 0))
                    data_srv.listen(1)
                    port = self.pasv_port or data_srv.getsockname()[1]
                    a = self.pasv_ip.replace('.', ',')
                    send(f'227 Entering Passive Mode ({a},{port >> 8},{port & 255})')
                elif cmd in ('EPSV', 'MLSD', 'FEAT', 'PORT', 'EPRT'):
                    send('500 desteklenmiyor')
                elif cmd == 'SIZE':
                    p = real(arg)
                    send(f'213 {os.path.getsize(p)}' if os.path.isfile(p) else '550 yok')
                elif cmd == 'LIST':
                    p = real(arg.split()[-1] if arg and not arg.startswith('-') else cwd)
                    send('150 liste')
                    d = data_conn()
                    rows = []
                    for n in sorted(os.listdir(p)):
                        st = os.stat(os.path.join(p, n))
                        kind = 'd' if os.path.isdir(os.path.join(p, n)) else '-'
                        when = time.strftime('%b %d %H:%M', time.localtime(st.st_mtime))
                        rows.append(f'{kind}rw-r--r--   1 test test {st.st_size:>8} {when} {n}')
                    d.sendall(('\r\n'.join(rows) + '\r\n').encode('utf-8'))
                    d.close()
                    send('226 bitti')
                elif cmd == 'RETR':
                    p = real(arg)
                    if not os.path.isfile(p):
                        send('550 yok')
                        continue
                    send('150 gönderiliyor')
                    d = data_conn()
                    with open(p, 'rb') as fh:
                        d.sendall(fh.read())
                    d.close()
                    send('226 bitti')
                elif cmd == 'STOR':
                    send('150 alınıyor')
                    d = data_conn()
                    with open(real(arg), 'wb') as fh:
                        while True:
                            b = d.recv(65536)
                            if not b:
                                break
                            fh.write(b)
                    d.close()
                    send('226 bitti')
                elif cmd == 'MKD':
                    os.makedirs(real(arg), exist_ok=True)
                    send(f'257 "{arg}"')
                elif cmd == 'DELE':
                    os.remove(real(arg))
                    send('250 silindi')
                elif cmd == 'QUIT':
                    send('221 güle güle')
                    break
                else:
                    send('502 bilinmiyor')
        except (OSError, socket.timeout):
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass
