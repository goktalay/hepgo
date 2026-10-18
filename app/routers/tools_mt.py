"""Araçlar › Master Tool web sürümleri (SQL Master · Notepad Master · Convert Master) — ortak katman.

Masaüstü uygulamalarda "Master Tool hesabı" ile saklanan kullanıcı verileri burada HEPGO kullanıcısı başına,
AYNI JSON ŞEMASIYLA tools_mt_store(user_id, app, key, json, updated_at) tablosunda tutulur:
  key = 'store'   → { folders, connections|projects, settings, … }   (masaüstündeki userData/store.json)
  key = 'secrets' → { ref: 'enc:…' }                                  (SQL Master secrets.json; Fernet ile şifreli)
  key = 'history' → [ … ]                                             (SQL Master history.jsonl)
Dosya içerikleri DATA_DIR/tools/<app>/<uid>/ altında: files/ (kullanıcının "yerel" alanı: Electron'daki dosya
diyaloglarının karşılığı), cache/, work/, converted/ …

Parolalar DB'ye düz yazılmaz: Fernet anahtarı app_kv'de (tools_mt_fernet), değerler 'enc:' önekiyle saklanır.
"""
import base64
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from .tools_common import TOOLS_DIR, safe_name, tools_user

router = APIRouter(prefix='/api/tools/mt')
APPS = ('sqlmaster', 'notepadmaster', 'convertmaster')
_kv_lock = threading.Lock()
MAX_UPLOAD = 512 * 1024 * 1024


def check_app(app: str) -> str:
    if app not in APPS:
        raise HTTPException(404, 'Bilinmeyen uygulama')
    return app


# --- Anahtar/değer deposu (JSON şeması masaüstüyle aynı) -------------------------------------
def kv_get(uid: int, app: str, key: str, default=None):
    with db.connect() as conn:
        r = conn.execute('SELECT json FROM tools_mt_store WHERE user_id = ? AND app = ? AND key = ?', (uid, app, key)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r['json'])
    except ValueError:
        return default


def kv_set(uid: int, app: str, key: str, value) -> None:
    text = json.dumps(value, ensure_ascii=False)
    with _kv_lock, db.connect() as conn:
        conn.execute('''INSERT INTO tools_mt_store (user_id, app, key, json, updated_at) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, app, key) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at''',
                     (uid, app, key, text, db.now()))
        conn.commit()


# --- Gizli bilgi şifreleme (Electron safeStorage karşılığı) -------------------------------------
_fernet = [None]


def _get_fernet():
    if _fernet[0] is not None:
        return _fernet[0]
    try:
        from cryptography.fernet import Fernet
    except ImportError:   # cryptography yoksa parolalar yalnız süreç belleğinde tutulur (masaüstündeki "anahtar zinciri yok" davranışı)
        _fernet[0] = False
        return False
    with _kv_lock, db.connect() as conn:
        r = conn.execute("SELECT v FROM app_kv WHERE k = 'tools_mt_fernet'").fetchone()
        if r:
            key = r['v']
        else:
            key = Fernet.generate_key().decode()
            conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('tools_mt_fernet', ?)", (key,))
            conn.commit()
    _fernet[0] = Fernet(key.encode())
    return _fernet[0]


_memory_secrets = {}


def protect(text: str) -> str:
    """Düz metin → 'enc:…' (DB'ye yazılabilir). Fernet yoksa bellekte tutulur, 'mem:' referansı döner."""
    if not text:
        return ''
    f = _get_fernet()
    if not f:
        ref = secrets.token_urlsafe(16)
        _memory_secrets[ref] = text
        return 'mem:' + ref
    return 'enc:' + f.encrypt(text.encode('utf-8')).decode()


def unprotect(value: str) -> str:
    if not value:
        return ''
    if value.startswith('mem:'):
        return _memory_secrets.get(value[4:], '')
    if value.startswith('enc:'):
        f = _get_fernet()
        if not f:
            return ''
        try:
            return f.decrypt(value[4:].encode()).decode('utf-8')
        except Exception:   # noqa: BLE001 — anahtar değişmiş/bozuk değer
            return ''
    if value.startswith('b64:'):   # masaüstü yedek biçimi (safeStorage yokken)
        try:
            return base64.b64decode(value[4:]).decode('utf-8')
        except Exception:   # noqa: BLE001
            return ''
    return value


# --- Kullanıcı dosya alanı ---------------------------------------------------------------------
def app_dir(app: str, uid: int, *parts: str) -> Path:
    p = TOOLS_DIR / app / str(int(uid))
    for x in parts:
        p = p / x
    p.mkdir(parents=True, exist_ok=True)
    return p


def files_root(app: str, uid: int) -> Path:
    return app_dir(app, uid, 'files')


_SEG_RE = re.compile(r'[\x00-\x1f\x7f]')


def norm_rel(rel: str) -> str:
    """'/a/b' biçimine getirir; '..' ve gizli kontrol karakterleri temizlenir. Kök = '/'."""
    parts = []
    for s in str(rel or '').replace('\\', '/').split('/'):
        s = _SEG_RE.sub('', s).strip()
        if s in ('', '.'):
            continue
        if s == '..':
            if parts:
                parts.pop()
            continue
        parts.append(s[:200])
    return '/' + '/'.join(parts)


def resolve(root: Path, rel: str) -> Path:
    rel = norm_rel(rel)
    p = (root / rel.lstrip('/')).resolve() if rel != '/' else root.resolve()
    if p != root.resolve() and root.resolve() not in p.parents:
        raise HTTPException(400, 'Geçersiz yol')
    return p


def entry(root: Path, p: Path) -> dict:
    try:
        st = p.stat()
    except OSError:
        return None
    is_dir = p.is_dir()
    return {'name': p.name, 'path': '/' + p.relative_to(root).as_posix(), 'isDir': is_dir, 'isLink': p.is_symlink(),
            'size': 0 if is_dir else st.st_size, 'mtime': int(st.st_mtime * 1000)}


def list_dir(root: Path, rel: str) -> list:
    d = resolve(root, rel)
    if not d.is_dir():
        raise HTTPException(404, 'Klasör bulunamadı')
    out = [entry(root, p) for p in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))]
    return [e for e in out if e]


def dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for f in p.rglob('*'):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def rm(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def uid8() -> str:
    """Masaüstündeki crypto.randomBytes(8).toString('hex') ile aynı biçimde kimlik."""
    return secrets.token_hex(8)


def now_ms() -> int:
    return int(time.time() * 1000)


# --- HTTP: hesap ve dosya alanı ----------------------------------------------------------------
@router.get('/account')
def account(user=Depends(tools_user)):
    """Masaüstündeki account:state karşılığı: oturum HEPGO'nun; Master Tool senkronu yok (state 'off')."""
    return {'loggedIn': True, 'user': {'id': user['id'], 'email': user['username'], 'name': user.get('full_name') or user['username']},
            'email': user['username'], 'syncEnabled': False, 'state': 'off', 'lastSyncAt': None, 'error': None, 'hepgo': True,
            'notice': None, 'appVersion': 'HEPGO'}


class PathBody(BaseModel):
    path: str = '/'
    name: str = ''


@router.get('/{app}/fs/list')
def fs_list(app: str, path: str = '/', user=Depends(tools_user)):
    return {'root': '/', 'items': list_dir(files_root(check_app(app), user['id']), path)}


@router.post('/{app}/fs/mkdir')
def fs_mkdir(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    base = resolve(root, body.path)
    target = (base / safe_name(body.name, '')) if body.name else base
    if target == root or not safe_name(target.name, ''):
        raise HTTPException(400, 'Geçersiz klasör adı')
    target.mkdir(parents=True, exist_ok=True)
    return {'ok': True, 'path': '/' + target.relative_to(root).as_posix()}


@router.post('/{app}/fs/upload')
async def fs_upload(app: str, files: list[UploadFile], dir: str = Form('/'), user=Depends(tools_user)):   # noqa: A002
    root = files_root(check_app(app), user['id'])
    d = resolve(root, dir)
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        # Klasör yüklemesinde (webkitdirectory) dosya adı göreli yol taşır: alt klasörler korunur
        rel = norm_rel(f.filename or 'dosya').lstrip('/')
        target = resolve(root, '/' + (d.relative_to(root).as_posix() + '/' if d != root else '') + rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with target.open('wb') as out:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(413, 'Dosya çok büyük (en çok 512 MB)')
                out.write(chunk)
        saved.append(entry(root, target))
    return {'ok': True, 'items': saved}


@router.get('/{app}/fs/download')
def fs_download(app: str, path: str, user=Depends(tools_user)):
    p = resolve(files_root(check_app(app), user['id']), path)
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(p, filename=p.name)


@router.post('/{app}/fs/delete')
def fs_delete(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    p = resolve(root, body.path)
    if p == root.resolve():
        raise HTTPException(400, 'Kök silinemez')
    rm(p)
    return {'ok': True}


@router.post('/{app}/fs/rename')
def fs_rename(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    p = resolve(root, body.path)
    name = safe_name(body.name, '')
    if not p.exists() or not name:
        raise HTTPException(400, 'Geçersiz ad')
    p.rename(p.parent / name)
    return {'ok': True, 'path': '/' + (p.parent / name).relative_to(root).as_posix()}


@router.get('/{app}/fs/usage')
def fs_usage(app: str, user=Depends(tools_user)):
    return {'bytes': dir_size(files_root(check_app(app), user['id']))}
