"""SSH Erişim — yalnızca MASTER (sistem sahibi).

Sistem sahibinin kayıtlı uzak sunuculara (ör. fabrikadaki GX10) tarayıcıdan bağlanıp komut çalıştırabilmesi için.
Bağlantı DIŞA DOĞRU kurulur (sistem `ssh` istemcisi bir PTY içinde); merkez sunucuda kabuk AÇMAZ. Parola / özel anahtar
cameras.encrypt ile şifreli saklanır, hiçbir yanıtta dönmez. Her bağlantı denetim kaydına yazılır.

Çok firmalı sunucu uyarısı yok: bu araç sunucunun kendi kabuğunu açmaz, yalnız sistem sahibinin tanımladığı dış
sunuculara gider. Yine de yalnız MASTER erişebilir.
"""
import asyncio
import json
import os
import pty
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import auth, config, db
from ..cameras import decrypt, encrypt
from .console import _read, _set_winsize   # aynı PTY yardımcıları (okuma + pencere boyutu)

router = APIRouter(prefix='/api/ssh')
ws_router = APIRouter()

AUTH_TYPES = ('password', 'key')
PUBLIC = ('id', 'label', 'host', 'port', 'username', 'auth_type', 'note', 'sort', 'last_used', 'created_at')


def _master(user=Depends(auth.current_user)):
    if not user.get('master'):
        raise HTTPException(403, 'SSH Erişim yalnızca sistem sahibine açıktır')
    return user


def _public(r):
    d = {k: r[k] for k in PUBLIC}
    d['has_secret'] = bool(r['secret'])
    return d


class HostIn(BaseModel):
    label: str
    host: str
    port: int = 22
    username: str
    auth_type: str = 'password'
    secret: Optional[str] = None   # parola ya da özel anahtar; boş/None → mevcut korunur (düzenlemede)
    note: Optional[str] = None


def _clean(body: HostIn):
    label, host, user = body.label.strip(), body.host.strip(), body.username.strip()
    if not (label and host and user):
        raise HTTPException(400, 'Ad, sunucu ve kullanıcı adı zorunlu')
    if body.auth_type not in AUTH_TYPES:
        raise HTTPException(400, 'Geçersiz kimlik türü')
    if not (1 <= body.port <= 65535):
        raise HTTPException(400, 'Geçersiz port')
    return label[:80], host[:200], user[:80]


@router.get('/hosts')
def list_hosts(user=Depends(_master), conn=db.DB):
    rows = db.rows(conn.execute('SELECT * FROM ssh_hosts ORDER BY sort, label'))
    return [_public(r) for r in rows]


@router.post('/hosts')
def add_host(body: HostIn, user=Depends(_master), conn=db.DB):
    label, host, uname = _clean(body)
    if body.auth_type == 'password' and not (body.secret or '').strip():
        raise HTTPException(400, 'Parola ile bağlanmak için parola girin')
    if body.auth_type == 'key' and not (body.secret or '').strip():
        raise HTTPException(400, 'Anahtar ile bağlanmak için özel anahtarı yapıştırın')
    sort = (conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM ssh_hosts').fetchone()[0])
    cur = conn.execute('''INSERT INTO ssh_hosts (label, host, port, username, auth_type, secret, note, sort, created_at)
                          VALUES (?,?,?,?,?,?,?,?,?)''',
                       (label, host, body.port, uname, body.auth_type, encrypt(body.secret.strip()),
                        (body.note or '').strip()[:300] or None, sort, db.now()))
    db.audit(conn, user['id'], 'SSH sunucusu ekledi', 'ssh', cur.lastrowid, f'{label} ({uname}@{host}:{body.port})')
    conn.commit()
    return {'id': cur.lastrowid}


@router.put('/hosts/{hid}')
def update_host(hid: int, body: HostIn, user=Depends(_master), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM ssh_hosts WHERE id = ?', (hid,)))
    if not r:
        raise HTTPException(404, 'Sunucu bulunamadı')
    label, host, uname = _clean(body)
    secret = encrypt(body.secret.strip()) if (body.secret or '').strip() else r['secret']
    if body.auth_type != r['auth_type'] and not (body.secret or '').strip():
        raise HTTPException(400, 'Kimlik türünü değiştirince parolayı / anahtarı yeniden girin')
    conn.execute('''UPDATE ssh_hosts SET label = ?, host = ?, port = ?, username = ?, auth_type = ?, secret = ?, note = ? WHERE id = ?''',
                 (label, host, body.port, uname, body.auth_type, secret, (body.note or '').strip()[:300] or None, hid))
    db.audit(conn, user['id'], 'SSH sunucusunu düzenledi', 'ssh', hid, f'{label} ({uname}@{host}:{body.port})')
    conn.commit()
    return {'ok': True}


@router.delete('/hosts/{hid}')
def delete_host(hid: int, user=Depends(_master), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM ssh_hosts WHERE id = ?', (hid,)))
    if not r:
        raise HTTPException(404, 'Sunucu bulunamadı')
    conn.execute('DELETE FROM ssh_hosts WHERE id = ?', (hid,))
    db.audit(conn, user['id'], 'SSH sunucusunu sildi', 'ssh', hid, f"{r['label']} ({r['username']}@{r['host']})")
    conn.commit()
    return {'ok': True}


def _known_hosts():
    p = config.DATA_DIR / 'ssh' / 'known_hosts'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# İlk bağlantıda sunucu anahtarı kaydedilir (accept-new); sonradan DEĞİŞİRSE reddedilir (ortadaki adam koruması).
# Ajan iletimi ve X11 kapalı; parola denemesi tek; bağlantı ve boşta zaman aşımları var.
def _ssh_cmd(r, key_path=None):
    kh = str(_known_hosts())
    opts = ['-p', str(r['port']), '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={kh}',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3',
            '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'NumberOfPasswordPrompts=1']
    if r['auth_type'] == 'key' and key_path:
        opts += ['-o', 'PreferredAuthentications=publickey', '-o', 'IdentitiesOnly=yes', '-i', key_path]
    else:
        opts += ['-o', 'PreferredAuthentications=password,keyboard-interactive', '-o', 'PubkeyAuthentication=no']
    return ['ssh', *opts, f"{r['username']}@{r['host']}"]


@ws_router.websocket('/ws/ssh/{hid}')
async def ws_ssh(ws: WebSocket, hid: int):
    await ws.accept()

    def load():
        with db.connect() as conn:
            u = auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
            if not (u and auth.is_master(u['username'])):
                return None, None
            r = db.row(conn.execute('SELECT * FROM ssh_hosts WHERE id = ?', (hid,)))
            if r:
                conn.execute('UPDATE ssh_hosts SET last_used = ? WHERE id = ?', (db.now(), hid))
                db.audit(conn, u['id'], 'SSH bağlantısı açtı', 'ssh', hid, f"{r['label']} ({r['username']}@{r['host']}:{r['port']})")
                conn.commit()
            return u, r

    user, host = await asyncio.to_thread(load)
    if not user:
        await ws.send_text('\x1b[31mYetkisiz: SSH Erişim yalnızca sistem sahibine açıktır.\x1b[0m\r\n')
        await ws.close(code=4403)
        return
    if not host:
        await ws.send_text('\x1b[31mSunucu bulunamadı.\x1b[0m\r\n')
        await ws.close(code=4404)
        return

    secret = decrypt(host['secret']) if host['secret'] else ''
    key_file = None
    if host['auth_type'] == 'key' and secret:
        fd, key_file = tempfile.mkstemp(prefix='sshkey-')
        os.write(fd, secret.encode() + (b'' if secret.endswith('\n') else b'\n'))
        os.close(fd)
        os.chmod(key_file, 0o600)

    await ws.send_text(f"\x1b[90m{host['username']}@{host['host']}:{host['port']} bağlanılıyor…\x1b[0m\r\n")
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, 24, 80)
    env = dict(os.environ, TERM='xterm-256color')
    proc = subprocess.Popen(_ssh_cmd(host, key_file), stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                            start_new_session=True, env=env)
    os.close(slave_fd)
    loop = asyncio.get_event_loop()
    pw_sent = [host['auth_type'] != 'password' or not secret]   # parola gerekmiyorsa gönderilmiş say

    async def pty_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, _read, master_fd)
                if not data:
                    break
                text = data.decode('utf-8', 'replace')
                if not pw_sent[0] and ('assword:' in text or 'Password:' in text):
                    pw_sent[0] = True
                    os.write(master_fd, secret.encode() + b'\n')
                    continue   # parolayı ekrana yansıtma
                await ws.send_text(text)
        except Exception:   # noqa: BLE001
            pass
        finally:
            try:
                await ws.close()
            except Exception:   # noqa: BLE001
                pass

    reader = asyncio.create_task(pty_to_ws())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                obj = json.loads(msg)
            except ValueError:
                continue
            if obj.get('t') == 'i':
                os.write(master_fd, obj.get('d', '').encode('utf-8'))
            elif obj.get('t') == 'r':
                _set_winsize(master_fd, int(obj.get('r', 24)), int(obj.get('c', 80)))
    except WebSocketDisconnect:
        pass
    except Exception:   # noqa: BLE001
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
