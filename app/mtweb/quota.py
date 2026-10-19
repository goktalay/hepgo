"""mtweb kotaları (docs/mtweb.md §Kotalar) ve HEPGO araç router'larına takılan kancalar.

Dosya alanı: kullanıcının iki uygulamadaki tüm dizinleri (DATA_DIR/tools/{notepadmaster,convertmaster}/<uid>: files, cache,
converted, work) toplamı ≤ MTWEB_SPACE_MB; girdi sayısı ≤ MTWEB_MAX_FILES; tek yükleme ≤ MTWEB_UPLOAD_MB.
Convert: kullanıcı başına MTWEB_CONVERT_USER_JOBS, genel MTWEB_CONVERT_JOBS eşzamanlı iş; giriş ≤ MTWEB_CONVERT_INPUT_MB;
ffmpeg `nice` + `-threads` + süre sınırı; Pillow piksel tavanı.
"""
import contextlib
import os
import threading
import time
from collections import defaultdict

from fastapi import HTTPException

from app.routers import tools_common, tools_convert, tools_mt, tools_notepad

from . import config, db

APP_DIRS = ('notepadmaster', 'convertmaster')
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


def install():
    """HEPGO araç router'larının kancalarını mtweb'e göre ayarlar (yalnız mtweb sürecinde çağrılır)."""
    tools_common.BRAND = 'Mastertool'
    tools_notepad.ALLOW_REMOTE = False
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


def _which(name):
    import shutil
    return shutil.which(name)
