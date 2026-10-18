"""Araçlar › FTP Master (web) — FTP/FTPS (ftplib, stdlib) ve SFTP (paramiko kuruluysa).

Bağlantı oturumları yalnız süreç belleğinde (SESSIONS); parola hiçbir yere yazılmaz. 30 dk boşta kalan oturum kapanır.
Her oturum yalnız açan kullanıcıya aittir. Tüm ağ işlemleri iş parçacığında, oturum kilidi ile sırayla çalışır.
"""
import asyncio
import ftplib
import importlib.util
import secrets
import threading
import time
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from .tools_common import check_host, check_port, new_tmp, safe_name, tools_user

router = APIRouter(prefix='/api/tools/ftp')
SESSIONS = {}          # sid → Session
IDLE = 1800
HAS_SFTP = importlib.util.find_spec('paramiko') is not None


class Session:
    def __init__(self, uid, kind, conn, label):
        self.uid, self.kind, self.conn, self.label = uid, kind, conn, label
        self.lock = threading.Lock()
        self.last = time.time()
        self.cwd = '/'


def _sweep():
    for sid, s in list(SESSIONS.items()):
        if time.time() - s.last > IDLE:
            _close(sid)


def _close(sid):
    s = SESSIONS.pop(sid, None)
    if s:
        try:
            s.conn.quit() if s.kind == 'ftp' else s.conn.close()
        except Exception:   # noqa: BLE001
            pass


def _get(sid, user) -> Session:
    _sweep()
    s = SESSIONS.get(sid or '')
    if not s or s.uid != user['id']:
        raise HTTPException(404, 'FTP oturumu bulunamadı ya da süresi doldu; yeniden bağlanın')
    s.last = time.time()
    return s


def _norm(path: str) -> str:
    p = PurePosixPath('/' + (path or '').replace('\\', '/').lstrip('/'))   # '//' POSIX'te özel: baştaki bölüler tekilleştirilir
    parts = [x for x in p.parts if x not in ('', '/', '.', '..')]
    return '/' + '/'.join(parts)


class ConnectIn(BaseModel):
    host: str
    port: Optional[int] = None
    username: str = 'anonymous'
    password: str = ''
    protocol: str = 'ftp'     # ftp | ftps | sftp
    passive: bool = True


@router.get('/caps')
def caps(user=Depends(tools_user)):
    return {'ftp': True, 'ftps': True, 'sftp': HAS_SFTP, 'sftp_note': None if HAS_SFTP else 'SFTP için sunucuda paramiko kurulu değil'}


def _open(body: ConnectIn):
    host = check_host(body.host)
    if body.protocol == 'sftp':
        if not HAS_SFTP:
            raise HTTPException(400, 'SFTP sürücüsü yok: sunucuda paramiko kurulu değil')
        import paramiko   # noqa: PLC0415
        port = check_port(body.port or 22)
        t = paramiko.Transport((host, port))
        t.banner_timeout = 15
        t.connect(username=body.username, password=body.password)
        return 'sftp', paramiko.SFTPClient.from_transport(t)
    port = check_port(body.port or 21)
    ftp = ftplib.FTP_TLS(timeout=20) if body.protocol == 'ftps' else ftplib.FTP(timeout=20)
    ftp.connect(host, port)
    ftp.login(body.username or 'anonymous', body.password or '')
    if body.protocol == 'ftps':
        ftp.prot_p()
    ftp.set_pasv(body.passive)
    ftp.encoding = 'utf-8'
    return 'ftp', ftp


@router.post('/connect')
async def connect(body: ConnectIn, user=Depends(tools_user), conn=db.DB):
    if body.protocol not in ('ftp', 'ftps', 'sftp'):
        raise HTTPException(400, 'Geçersiz protokol')
    try:
        kind, c = await asyncio.to_thread(_open, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except HTTPException:
        raise
    except Exception as e:   # noqa: BLE001 — ağ/kimlik hataları kullanıcıya metin olarak
        raise HTTPException(502, f'Bağlanamadı: {e}') from None
    sid = secrets.token_urlsafe(18)
    label = f"{body.username}@{body.host}:{body.port or (22 if kind == 'sftp' else 21)}"
    SESSIONS[sid] = Session(user['id'], kind, c, label)
    db.audit(conn, user['id'], 'FTP Master bağlantısı açtı', 'tools', None, f'{body.protocol} {label}')
    conn.commit()
    return {'sid': sid, 'protocol': body.protocol, 'label': label}


@router.post('/disconnect')
def disconnect(sid: str, user=Depends(tools_user)):
    s = SESSIONS.get(sid)
    if s and s.uid == user['id']:
        _close(sid)
    return {'ok': True}


def _parse_list_line(line):
    """UNIX 'ls -l' biçimi: drwxr-xr-x 2 u g 4096 Jan 01 12:00 ad"""
    parts = line.split(None, 8)
    if len(parts) < 9 or len(parts[0]) < 10:
        return None
    name = parts[8]
    if parts[0][0] == 'l' and ' -> ' in name:
        name = name.split(' -> ')[0]
    try:
        size = int(parts[4])
    except ValueError:
        size = None
    return {'name': name, 'dir': parts[0][0] == 'd', 'size': size, 'mtime': ' '.join(parts[5:8])}


def _list(s: Session, path):
    path = _norm(path)
    if s.kind == 'sftp':
        out = []
        for a in s.conn.listdir_attr(path):
            import stat   # noqa: PLC0415
            out.append({'name': a.filename, 'dir': stat.S_ISDIR(a.st_mode), 'size': a.st_size,
                        'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(a.st_mtime)) if a.st_mtime else ''})
        return out
    ftp = s.conn
    ftp.cwd(path)
    out = []
    try:
        for name, facts in ftp.mlsd(facts=['type', 'size', 'modify']):
            if name in ('.', '..'):
                continue
            tp = facts.get('type', 'file')
            if tp in ('cdir', 'pdir'):
                continue
            m = facts.get('modify', '')
            out.append({'name': name, 'dir': tp == 'dir', 'size': int(facts['size']) if facts.get('size', '').isdigit() else None,
                        'mtime': f'{m[:4]}-{m[4:6]}-{m[6:8]} {m[8:10]}:{m[10:12]}' if len(m) >= 12 else m})
        return out
    except (ftplib.error_perm, ValueError):
        lines = []
        ftp.retrlines('LIST', lines.append)
        for ln in lines:
            e = _parse_list_line(ln)
            if e and e['name'] not in ('.', '..'):
                out.append(e)
        return out


@router.get('/list')
async def list_dir(sid: str, path: str = '/', user=Depends(tools_user)):
    s = _get(sid, user)
    try:
        with s.lock:
            items = await asyncio.to_thread(_list, s, path)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'Dizin okunamadı: {e}') from None
    items.sort(key=lambda x: (not x['dir'], x['name'].lower()))
    return {'path': _norm(path), 'items': items}


class PathIn(BaseModel):
    path: str
    new_path: Optional[str] = None
    is_dir: bool = False


def _op(s: Session, op, body: PathIn):
    p = _norm(body.path)
    if s.kind == 'sftp':
        c = s.conn
        if op == 'mkdir':
            c.mkdir(p)
        elif op == 'rename':
            c.rename(p, _norm(body.new_path))
        elif op == 'delete':
            c.rmdir(p) if body.is_dir else c.remove(p)
        return
    ftp = s.conn
    if op == 'mkdir':
        ftp.mkd(p)
    elif op == 'rename':
        ftp.rename(p, _norm(body.new_path))
    elif op == 'delete':
        ftp.rmd(p) if body.is_dir else ftp.delete(p)


async def _run_op(sid, op, body, user, conn):
    s = _get(sid, user)
    if op == 'rename' and not (body.new_path or '').strip():
        raise HTTPException(400, 'Yeni ad gerekli')
    try:
        with s.lock:
            await asyncio.to_thread(_op, s, op, body)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'İşlem yapılamadı: {e}') from None
    db.audit(conn, user['id'], f'FTP Master: {op}', 'tools', None, f'{s.label} {body.path}' + (f' → {body.new_path}' if body.new_path else ''))
    conn.commit()
    return {'ok': True}


@router.post('/mkdir')
async def mkdir(sid: str, body: PathIn, user=Depends(tools_user), conn=db.DB):
    return await _run_op(sid, 'mkdir', body, user, conn)


@router.post('/rename')
async def rename(sid: str, body: PathIn, user=Depends(tools_user), conn=db.DB):
    return await _run_op(sid, 'rename', body, user, conn)


@router.post('/delete')
async def delete(sid: str, body: PathIn, user=Depends(tools_user), conn=db.DB):
    return await _run_op(sid, 'delete', body, user, conn)


def _upload(s: Session, path, fobj):
    if s.kind == 'sftp':
        s.conn.putfo(fobj, path)
    else:
        s.conn.storbinary(f'STOR {path}', fobj)


@router.post('/upload')
async def upload(sid: str, path: str, file: UploadFile, user=Depends(tools_user), conn=db.DB):
    s = _get(sid, user)
    target = _norm(path).rstrip('/') + '/' + safe_name(file.filename)
    try:
        with s.lock:
            await asyncio.to_thread(_upload, s, target, file.file)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'Yüklenemedi: {e}') from None
    db.audit(conn, user['id'], 'FTP Master: yükleme', 'tools', None, f'{s.label} {target}')
    conn.commit()
    return {'ok': True, 'path': target}


def _download(s: Session, path, dest):
    with open(dest, 'wb') as f:
        if s.kind == 'sftp':
            s.conn.getfo(path, f)
        else:
            s.conn.retrbinary(f'RETR {path}', f.write)


@router.get('/download')
async def download(sid: str, path: str, user=Depends(tools_user)):
    s = _get(sid, user)
    p = _norm(path)
    name = safe_name(p.rsplit('/', 1)[-1])
    token, dest = new_tmp(name)
    try:
        with s.lock:
            await asyncio.to_thread(_download, s, p, dest)
    except Exception as e:   # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(502, f'İndirilemedi: {e}') from None
    return FileResponse(dest, filename=name, media_type='application/octet-stream')
