"""mtweb kotaları (docs/mtweb.md §Kotalar) ve HEPGO araç router'larına takılan kancalar.

Dosya alanı: kullanıcının tüm uygulama dizinleri (DATA_DIR/tools/{notepadmaster,convertmaster,sqlmaster}/<uid>: files, cache,
converted, work, keys + SSH/FTP Master'ın H:\\ alanı DATA_DIR/tools/files/<uid>) toplamı ≤ MTWEB_SPACE_MB; girdi sayısı
≤ MTWEB_MAX_FILES; tek yükleme ≤ MTWEB_UPLOAD_MB. SSH/FTP indirmeleri ve SQLite dosyaları da bu alana sayılır.
Convert: kullanıcı başına MTWEB_CONVERT_USER_JOBS, genel MTWEB_CONVERT_JOBS eşzamanlı iş; giriş ≤ MTWEB_CONVERT_INPUT_MB;
ffmpeg `nice` + `-threads` + süre sınırı; Pillow piksel tavanı.
"""
import contextlib
import os
import sqlite3
import threading
import time
from collections import defaultdict

from fastapi import HTTPException

from app.routers import tools_common, tools_convert, tools_ftp, tools_mt, tools_notepad, tools_sql, tools_ssh

from . import config, db, guard

APP_DIRS = ('notepadmaster', 'convertmaster', 'sqlmaster', 'files')   # 'files' = SSH/FTP Master H:\\ alanı
_usage = {}                    # uid → [bitiş, bayt, girdi]
_usage_lock = threading.Lock()
_user_jobs = defaultdict(lambda: threading.BoundedSemaphore(max(1, config.CONVERT_USER_JOBS)))
_user_jobs_lock = threading.Lock()
_jobs = threading.BoundedSemaphore(max(1, config.CONVERT_JOBS))


def _scan(uid):
    total = count = 0
    for app in APP_DIRS:
        root = tools_common.TOOLS_DIR / app / str(int(uid))
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            count += len(dirnames) + len(filenames)
            for n in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, n)).st_size
                except OSError:
                    pass
    return total, count


def usage(uid, fresh=False):
    """(bayt, girdi sayısı) — 5 sn önbellekli."""
    t = time.time()
    with _usage_lock:
        u = _usage.get(uid)
        if u and u[0] > t and not fresh:
            return u[1], u[2]
    b, c = _scan(uid)
    with _usage_lock:
        _usage[uid] = [t + 5, b, c]
    return b, c


def invalidate(uid):
    with _usage_lock:
        _usage.pop(uid, None)


def space_error():
    return HTTPException(413, f'Dosya alanınız doldu (en çok {config.SPACE_BYTES // config.MB} MB)')


def _check(b, c, add_bytes, add_files):
    if add_bytes > 0 and b + add_bytes > config.SPACE_BYTES:
        raise space_error()
    if add_files > 0 and c + add_files > config.MAX_FILES:
        raise HTTPException(413, f'Dosya sayısı sınırına ulaşıldı (en çok {config.MAX_FILES})')


def ensure(uid, add_bytes=0, add_files=0):
    """Eklenecek bayt / girdi kotayı aşıyorsa 413. Yazma sonrası ölçüm tazelensin diye önbellek düşürülür."""
    b, c = usage(uid, fresh=True)
    _check(b, c, add_bytes, add_files)
    invalidate(uid)


# --- kancalar ---------------------------------------------------------------------------------------------------
def _upload_guard(uid, app):
    """Yükleme başında bir kez ölçülür; parça parça eklenen bayt/dosya bu taban üzerinden denetlenir."""
    b, c = usage(uid, fresh=True)
    added = [0, 0]

    def check(nbytes, new_file):
        added[0] += nbytes
        added[1] += 1 if new_file else 0
        invalidate(uid)
        _check(b, c, added[0] if nbytes > 0 else 0, 0)
        if new_file:
            _check(b, c + added[1] - 1, 0, 1)
    return check


def _write_guard(uid, nbytes, new_file):
    ensure(uid, nbytes, 1 if new_file else 0)


def _public_path(p):
    try:
        return p.relative_to(tools_common.TOOLS_DIR).as_posix().split('/', 2)[-1]
    except ValueError:
        return p.name


class _Busy(tools_convert.ConvertError):
    pass


@contextlib.contextmanager
def _job_gate(uid, src, out, cancel):
    """Convert işi: giriş boyutu, kota, kullanıcı + genel eşzamanlılık; iş bitince kota yeniden ölçülür (aşımda çıktı silinir)."""
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    if size > config.CONVERT_INPUT_BYTES:
        raise tools_convert.ConvertError('too_large', f'Giriş dosyası çok büyük (en çok {config.CONVERT_INPUT_BYTES // config.MB} MB)')
    b, _ = usage(uid, fresh=True)
    if b >= config.SPACE_BYTES:
        raise tools_convert.ConvertError('quota', space_error().detail)
    with _user_jobs_lock:
        mine = _user_jobs[uid]
    waited = 0.0
    acquired_user = acquired_all = False
    try:
        while not acquired_user or not acquired_all:
            if cancel is not None and cancel.is_set():
                raise tools_convert.ConvertError('canceled')
            if cancel is None and waited > 30:   # eşzamanlı önizleme vekili: kısa bekleme
                raise _Busy('busy', 'Sunucu meşgul; biraz sonra tekrar deneyin')
            if not acquired_user:
                acquired_user = mine.acquire(timeout=0.5)
            elif not acquired_all:
                acquired_all = _jobs.acquire(timeout=0.5)
            waited += 0.5
        yield
    finally:
        if acquired_all:
            _jobs.release()
        if acquired_user:
            mine.release()
    b, _ = usage(uid, fresh=True)
    if b > config.SPACE_BYTES:
        try:
            out.unlink()
        except OSError:
            pass
        invalidate(uid)
        raise tools_convert.ConvertError('quota', space_error().detail)
    db.audit(uid, 'convertmaster', 'convert', size)


# --- SQLite (SQL Master): yalnız kullanıcı alanı; ATTACH / VACUUM INTO / load_extension / geçici nesne yok; boyut + süre ----
_SQLITE_DENY_PRAGMA = {'max_page_count', 'writable_schema', 'temp_store_directory', 'data_store_directory', 'mmap_size',
                       'hard_heap_limit', 'soft_heap_limit', 'trusted_schema', 'cache_size', 'page_size'}
_SQLITE_DENY_FUNC = {'load_extension', 'readfile', 'writefile', 'edit', 'fts3_tokenizer'}
_SQLITE_DENY_ACT = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE,
                    sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW}


def _sqlite_authorizer(action, a1, a2, dbname, trigger):
    if action in _SQLITE_DENY_ACT:          # ATTACH, VACUUM INTO (içte ATTACH), DETACH, TEMP nesneleri
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and str(a1 or '').lower() in _SQLITE_DENY_PRAGMA:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and str(a2 or '').lower() in _SQLITE_DENY_FUNC:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _sqlite_guard(sc, uid):
    """tools_sql.SqliteConn açılınca: sayfa tavanı = kalan alan kotası (bellek içi: MTWEB_SQL_MEMORY_MB), yetkilendirici,
    ifade süre sınırı (MTWEB_SQL_TIMEOUT_S; ilerleme işleyicisi)."""
    con = sc.db
    page = con.execute('PRAGMA page_size').fetchone()[0] or 4096
    cur = con.execute('PRAGMA page_count').fetchone()[0] or 0
    if sc.path is None:
        allow = config.SQL_MEMORY_MB * config.MB
    else:
        used, _ = usage(uid, fresh=True)
        allow = max(0, config.SPACE_BYTES - used)
    con.execute(f'PRAGMA max_page_count = {int(cur + allow // page) or 1}')
    con.set_authorizer(_sqlite_authorizer)
    limit = max(1, config.SQL_TIMEOUT_S)
    con.set_progress_handler(lambda: 1 if time.time() - sc.started > limit else 0, 20000)
    invalidate(uid)


def install():
    """HEPGO araç router'larının kancalarını mtweb'e göre ayarlar (yalnız mtweb sürecinde çağrılır)."""
    tools_common.BRAND = 'Mastertool'
    # Dış bağlantılar: SSRF koruması + oran + eşzamanlılık + denetim (guard.py)
    tools_common.NET_GUARD = guard.resolve_target
    tools_common.CONN_GATE = guard.acquire
    tools_ssh.KNOWN_HOSTS = lambda uid: _known_hosts(uid)
    tools_ftp.POOL_MAX = max(1, config.FTP_POOL)
    tools_sql.APP_DB_READONLY = False
    tools_sql.ALLOW_SSH_AGENT = False
    tools_sql.SQLITE_GUARD = _sqlite_guard
    tools_sql.EXPORT_MAX = config.UPLOAD_BYTES
    tools_sql.ROW_LIMIT_MAX = config.SQL_ROW_LIMIT
    tools_sql.PUBLIC_PATH = _sql_public_path
    tools_notepad.ALLOW_REMOTE = 'notepadmaster' not in config.DISABLED_APPS
    tools_notepad.WRITE_GUARD = _write_guard
    tools_notepad.PUBLIC_PATH = _public_path
    tools_mt.UPLOAD_GUARD = _upload_guard
    tools_mt.MAX_UPLOAD = config.UPLOAD_BYTES
    tools_mt.VERSION = 'Mastertool web'
    tools_convert.JOB_GATE = _job_gate
    tools_convert.MAX_CONCURRENCY = max(1, config.CONVERT_USER_JOBS)
    tools_convert.FFMPEG_PREFIX = ['nice', '-n', str(config.CONVERT_NICE)] if config.CONVERT_NICE > 0 and _which('nice') else []
    tools_convert.FFMPEG_THREADS = config.CONVERT_THREADS
    tools_convert.FFMPEG_TIMEOUT = config.CONVERT_TIMEOUT_S
    if tools_convert.Image is not None:
        tools_convert.Image.MAX_IMAGE_PIXELS = config.IMAGE_MAX_PIXELS


def _sql_public_path(f):
    """SQLite dosyasının sunucu yolu → kullanıcının alanındaki göreli yol ('/e2e.db'); arayüze sunucu yolu gitmez."""
    from pathlib import Path
    try:
        parts = Path(f).resolve().relative_to(tools_common.TOOLS_DIR.resolve()).parts
    except (ValueError, OSError):
        return Path(f).name
    return '/' + '/'.join(parts[3:]) if len(parts) > 3 and parts[2] == 'files' else Path(f).name


def _known_hosts(uid):
    """Kullanıcıya ayrı known_hosts (bir kullanıcının kabul ettiği anahtar başkasını etkilemez)."""
    d = tools_common.TOOLS_DIR / 'ssh_known_hosts.d'
    d.mkdir(parents=True, exist_ok=True)
    return d / str(int(uid or 0))


def _which(name):
    import shutil
    return shutil.which(name)
