"""Araçlar › SQL Master (web) — sqlite3 (stdlib) + MySQL/PostgreSQL (yalnız sürücü kuruluysa).

SQLite dosyası: kullanıcının yüklediği dosyalar DATA_DIR/tools/sql/<uid>/ altında; ya da DATA_DIR altındaki bir yol.
Uygulamanın kendi veritabanı (DB_PATH) yalnız SALT OKUNUR açılır. Bağlantı oturumları bellekte; parola yazılmaz.
"""
import asyncio
import importlib.util
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from .. import config, db
from .tools_common import check_host, check_port, safe_name, tools_user, user_dir

router = APIRouter(prefix='/api/tools/sql')
SESSIONS = {}
IDLE = 1800
MAX_ROWS = 5000
DRIVERS = {
    'sqlite': True,
    'mysql': importlib.util.find_spec('pymysql') is not None or importlib.util.find_spec('MySQLdb') is not None,
    'postgres': importlib.util.find_spec('psycopg') is not None or importlib.util.find_spec('psycopg2') is not None,
}


class Session:
    def __init__(self, uid, driver, conn, label, readonly=False):
        self.uid, self.driver, self.conn, self.label, self.readonly = uid, driver, conn, label, readonly
        self.lock = threading.Lock()
        self.last = time.time()


def _close(sid):
    s = SESSIONS.pop(sid, None)
    if s:
        try:
            s.conn.close()
        except Exception:   # noqa: BLE001
            pass


def _get(sid, user) -> Session:
    for k, s in list(SESSIONS.items()):
        if time.time() - s.last > IDLE:
            _close(k)
    s = SESSIONS.get(sid or '')
    if not s or s.uid != user['id']:
        raise HTTPException(404, 'SQL oturumu bulunamadı ya da süresi doldu; yeniden bağlanın')
    s.last = time.time()
    return s


@router.get('/drivers')
def drivers(user=Depends(tools_user)):
    return {**DRIVERS, 'note': {k: 'Sürücü kurulu değil' for k, v in DRIVERS.items() if not v}}


@router.get('/files')
def files(user=Depends(tools_user)):
    d = user_dir('sql', user['id'])
    return [{'name': p.name, 'size': p.stat().st_size} for p in sorted(d.iterdir()) if p.is_file()]


@router.post('/upload')
async def upload(file: UploadFile, user=Depends(tools_user)):
    name = safe_name(file.filename, 'veritabani.db')
    dest = user_dir('sql', user['id']) / name
    with open(dest, 'wb') as f:
        await asyncio.to_thread(shutil.copyfileobj, file.file, f)
    try:
        c = sqlite3.connect(f'file:{dest}?mode=ro', uri=True)
        c.execute('SELECT count(*) FROM sqlite_master').fetchone()
        c.close()
    except sqlite3.Error as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f'Geçerli bir SQLite dosyası değil: {e}') from None
    return {'name': name, 'size': dest.stat().st_size}


@router.delete('/files/{name}')
def delete_file(name: str, user=Depends(tools_user)):
    p = user_dir('sql', user['id']) / safe_name(name)
    if p.is_file():
        p.unlink()
    return {'ok': True}


class ConnectIn(BaseModel):
    driver: str = 'sqlite'
    path: Optional[str] = None          # sqlite: yüklenen dosya adı ya da DATA_DIR altında yol
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None


def _sqlite_path(body: ConnectIn, user):
    raw = (body.path or '').strip()
    if not raw:
        raise HTTPException(400, 'SQLite dosyası seçin')
    cand = user_dir('sql', user['id']) / safe_name(raw)
    if cand.is_file():
        return cand, False
    p = Path(raw)
    p = (p if p.is_absolute() else config.DATA_DIR / p).resolve()
    data = config.DATA_DIR.resolve()
    if data not in p.parents and p != data:
        raise HTTPException(400, 'Yalnız veri dizini (DATA_DIR) altındaki dosyalar açılabilir')
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return p, p == Path(config.DB_PATH).resolve()


def _open(body: ConnectIn, user):
    if body.driver == 'sqlite':
        p, ro = _sqlite_path(body, user)
        c = sqlite3.connect(f'file:{p}?mode={"ro" if ro else "rw"}', uri=True, check_same_thread=False)
        return c, p.name + (' (salt okunur)' if ro else ''), ro
    if not DRIVERS.get(body.driver):
        raise HTTPException(400, f'{body.driver} sürücüsü sunucuda kurulu değil')
    host = check_host(body.host)
    if body.driver == 'mysql':
        port = check_port(body.port or 3306)
        try:
            import pymysql   # noqa: PLC0415
            c = pymysql.connect(host=host, port=port, user=body.username or '', password=body.password or '', database=body.database or None, connect_timeout=15)
        except ImportError:
            import MySQLdb   # noqa: PLC0415
            c = MySQLdb.connect(host=host, port=port, user=body.username or '', passwd=body.password or '', db=body.database or '', connect_timeout=15)
        return c, f'{body.username}@{host}:{port}/{body.database or ""}', False
    port = check_port(body.port or 5432)
    try:
        import psycopg   # noqa: PLC0415
        c = psycopg.connect(host=host, port=port, user=body.username or '', password=body.password or '', dbname=body.database or 'postgres', connect_timeout=15)
    except ImportError:
        import psycopg2   # noqa: PLC0415
        c = psycopg2.connect(host=host, port=port, user=body.username or '', password=body.password or '', dbname=body.database or 'postgres', connect_timeout=15)
    return c, f'{body.username}@{host}:{port}/{body.database or ""}', False


@router.post('/connect')
async def connect(body: ConnectIn, user=Depends(tools_user), conn=db.DB):
    if body.driver not in DRIVERS:
        raise HTTPException(400, 'Geçersiz sürücü')
    try:
        c, label, ro = await asyncio.to_thread(_open, body, user)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'Bağlanamadı: {e}') from None
    sid = secrets.token_urlsafe(18)
    SESSIONS[sid] = Session(user['id'], body.driver, c, label, ro)
    db.audit(conn, user['id'], 'SQL Master bağlantısı açtı', 'tools', None, f'{body.driver} {label}')
    conn.commit()
    return {'sid': sid, 'driver': body.driver, 'label': label, 'readonly': ro}


@router.post('/disconnect')
def disconnect(sid: str, user=Depends(tools_user)):
    s = SESSIONS.get(sid)
    if s and s.uid == user['id']:
        _close(sid)
    return {'ok': True}


def _tables(s: Session):
    cur = s.conn.cursor()
    if s.driver == 'sqlite':
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name")
        out = []
        for name, tp in cur.fetchall():
            cols = [r[1] for r in s.conn.execute(f'PRAGMA table_info("{name}")').fetchall()]
            out.append({'name': name, 'type': tp, 'columns': cols})
        return out
    if s.driver == 'mysql':
        cur.execute('SHOW FULL TABLES')
        rows = cur.fetchall()
        return [{'name': r[0], 'type': 'view' if 'VIEW' in str(r[1]).upper() else 'table', 'columns': []} for r in rows]
    cur.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = current_schema() ORDER BY 1")
    return [{'name': r[0], 'type': 'view' if 'VIEW' in str(r[1]).upper() else 'table', 'columns': []} for r in cur.fetchall()]


@router.get('/tables')
async def tables(sid: str, user=Depends(tools_user)):
    s = _get(sid, user)
    try:
        with s.lock:
            return await asyncio.to_thread(_tables, s)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'Tablolar okunamadı: {e}') from None


class QueryIn(BaseModel):
    sql: str
    page: int = 1
    page_size: int = 100


def _jsonable(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f'<blob {len(v)} B>'
    if isinstance(v, (int, float, str)) or v is None:
        return v
    return str(v)


def _query(s: Session, sql):
    t0 = time.time()
    cur = s.conn.cursor()
    cur.execute(sql)
    if cur.description:
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = [[_jsonable(v) for v in r] for r in rows[:MAX_ROWS]]
        return {'columns': cols, 'rows': rows, 'truncated': truncated, 'ms': int((time.time() - t0) * 1000)}
    rc = cur.rowcount
    if not s.readonly:
        s.conn.commit()
    return {'columns': [], 'rows': [], 'rowcount': rc, 'ms': int((time.time() - t0) * 1000)}


@router.post('/query')
async def query(sid: str, body: QueryIn, user=Depends(tools_user)):
    s = _get(sid, user)
    sql = body.sql.strip().rstrip(';')
    if not sql:
        raise HTTPException(400, 'Sorgu boş')
    try:
        with s.lock:
            res = await asyncio.to_thread(_query, s, sql)
    except Exception as e:   # noqa: BLE001
        try:
            s.conn.rollback()
        except Exception:   # noqa: BLE001
            pass
        raise HTTPException(400, f'Sorgu hatası: {e}') from None
    page, size = max(1, body.page), min(1000, max(10, body.page_size))
    total = len(res['rows'])
    res['total'], res['page'], res['page_size'] = total, page, size
    res['rows'] = res['rows'][(page - 1) * size: page * size]
    return res
