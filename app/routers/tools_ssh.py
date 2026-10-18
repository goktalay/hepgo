"""Araçlar › SSH Master (web) — tarayıcıdan dış sunucuya SSH.

Arka uç: sistem `ssh` istemcisi (openssh-client) bir PTY içinde çalıştırılır; paramiko/asyncssh GEREKMEZ (PROD'da ek paket yok).
Bağlantı DIŞA DOĞRU kurulur; merkez sunucuda kabuk açılmaz. Sunucu/kullanıcı/parola/anahtar yalnız bu WebSocket oturumunun
belleğinde kalır; hiçbir yere yazılmaz (anahtar geçici 0600 dosyaya yazılır, bağlantı bitince silinir). shell=True yok.

Protokol (/ws/tools/ssh): ilk ileti {t:'connect', host, port, username, password?, key?} → ardından {t:'i', d} giriş, {t:'r', r, c} boyut.
"""
import asyncio
import json
import os
import pty
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from .. import config, db
from .console import _read, _set_winsize
from .tools_common import check_host, check_port, check_user, tools_user, ws_user

router = APIRouter(prefix='/api/tools/ssh')
ws_router = APIRouter()


@router.get('/status')
def status(user=Depends(tools_user)):
    return {'backend': 'openssh', 'available': bool(shutil.which('ssh'))}


def _known_hosts():
    p = config.DATA_DIR / 'tools' / 'ssh_known_hosts'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cmd(host, port, username, key_path=None):
    opts = ['-p', str(port), '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={_known_hosts()}',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3',
            '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'NumberOfPasswordPrompts=1']
    if key_path:
        opts += ['-o', 'PreferredAuthentications=publickey', '-o', 'IdentitiesOnly=yes', '-i', key_path]
    else:
        opts += ['-o', 'PreferredAuthentications=password,keyboard-interactive', '-o', 'PubkeyAuthentication=no']
    return ['ssh', *opts, f'{username}@{host}']


async def _err(ws, msg, code=4400):
    try:
        await ws.send_text(f'\x1b[31m{msg}\x1b[0m\r\n')
        await ws.close(code=code)
    except Exception:   # noqa: BLE001
        pass


@ws_router.websocket('/ws/tools/ssh')
async def ws_ssh(ws: WebSocket):
    await ws.accept()
    user = await ws_user(ws)
    if not user:
        return await _err(ws, 'Yetkisiz: Araçlar modülü yetkisi gerekir.', 4403)
    if not shutil.which('ssh'):
        return await _err(ws, 'Sunucuda ssh istemcisi yok (openssh-client).')
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 30))
        if first.get('t') != 'connect':
            raise ValueError('İlk ileti bağlantı bilgisi olmalı')
        host, port, username = check_host(first.get('host')), check_port(first.get('port', 22)), check_user(first.get('username'))
    except (asyncio.TimeoutError, ValueError, TypeError) as e:
        return await _err(ws, str(e) or 'Bağlantı bilgisi alınamadı')
    except WebSocketDisconnect:
        return
    password = (first.get('password') or '')
    key = (first.get('key') or '').strip()
    key_file = None
    if key:
        fd, key_file = tempfile.mkstemp(prefix='mt-sshkey-')
        os.write(fd, key.encode() + b'\n')
        os.close(fd)
        os.chmod(key_file, 0o600)

    def audit():
        with db.connect() as conn:
            db.audit(conn, user['id'], 'SSH Master bağlantısı açtı', 'tools', None, f'{username}@{host}:{port}')
            conn.commit()
    await asyncio.to_thread(audit)

    await ws.send_text(f'\x1b[90m{username}@{host}:{port} bağlanılıyor…\x1b[0m\r\n')
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, int(first.get('rows') or 24), int(first.get('cols') or 80))
    env = dict(os.environ, TERM='xterm-256color')
    proc = subprocess.Popen(_cmd(host, port, username, key_file), stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                            start_new_session=True, env=env)
    os.close(slave_fd)
    loop = asyncio.get_event_loop()
    pw_sent = [not password]

    async def pty_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, _read, master_fd)
                if not data:
                    break
                text = data.decode('utf-8', 'replace')
                if not pw_sent[0] and ('assword:' in text or 'Password:' in text or 'passphrase' in text):
                    pw_sent[0] = True
                    os.write(master_fd, password.encode() + b'\n')
                    continue   # parolayı ekrana yansıtma
                await ws.send_text(text)
        except Exception:   # noqa: BLE001
            pass
        finally:
            try:
                await ws.send_text('\r\n\x1b[90m[SSH oturumu kapandı]\x1b[0m\r\n')
                await ws.close()
            except Exception:   # noqa: BLE001
                pass

    reader = asyncio.create_task(pty_to_ws())
    try:
        while True:
            try:
                obj = json.loads(await ws.receive_text())
            except ValueError:
                continue
            if obj.get('t') == 'i':
                os.write(master_fd, str(obj.get('d', '')).encode('utf-8'))
            elif obj.get('t') == 'r':
                _set_winsize(master_fd, int(obj.get('r', 24)), int(obj.get('c', 80)))
    except (WebSocketDisconnect, Exception):   # noqa: BLE001
        pass
    finally:
        reader.cancel()
        for step in (lambda: proc.send_signal(signal.SIGHUP), proc.terminate, lambda: os.close(master_fd)):
            try:
                step()
            except Exception:   # noqa: BLE001
                pass
        if key_file:
            Path(key_file).unlink(missing_ok=True)
        try:
            await asyncio.to_thread(proc.wait, 5)
        except Exception:   # noqa: BLE001
            try:
                proc.kill()
            except Exception:   # noqa: BLE001
                pass
