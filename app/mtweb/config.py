"""mtweb yapılandırması (docs/mtweb.md §Ortam değişkenleri).

Yalıtım: HEPGO araç router'ları `app.config` / `app.db` üzerinden veri dizini ve veritabanı yolu alır. Bu modül, onlar içe
aktarılmadan ÖNCE yolları mtweb veri dizinine yönlendirir: `CAYMAZ_DATA_DIR` = MTWEB_DATA_DIR (ya da verilen CAYMAZ_DATA_DIR),
`CAYMAZ_DB` = <veri>/mtweb.db (ZORLA), `CAYMAZ_ENV_FILE` yoksa <veri>/.env. HEPGO'nun `data/` dizini ya da `caymaz.db`'si
seçilmişse servis açılmaz. `app.main` hiçbir yerde içe aktarılmaz.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / 'static'
MT_STATIC = STATIC_DIR / 'mt'

DATA_DIR = Path(os.environ.get('MTWEB_DATA_DIR') or os.environ.get('CAYMAZ_DATA_DIR') or (BASE_DIR / 'data' / 'mtweb')).resolve()
if DATA_DIR == (BASE_DIR / 'data').resolve():
    raise SystemExit('mtweb: veri dizini HEPGO data/ olamaz (MTWEB_DATA_DIR ayrı bir dizin olmalı)')
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'mtweb.db'
os.environ['CAYMAZ_DATA_DIR'] = str(DATA_DIR)
os.environ['CAYMAZ_DB'] = str(DB_PATH)
os.environ.setdefault('CAYMAZ_ENV_FILE', str(DATA_DIR / '.env'))
os.environ['CAYMAZ_CONSOLE'] = '0'
os.environ.setdefault('CAYMAZ_PRINTER_POLL', '0')

from app import config as _core  # noqa: E402 — .env (CAYMAZ_ENV_FILE) burada okunur; MTWEB_* değerleri ortama girer

if Path(_core.DB_PATH).resolve() != DB_PATH or Path(_core.DATA_DIR).resolve() != DATA_DIR:
    raise SystemExit('mtweb: çekirdek yapılandırması mtweb veri dizinine yönlenmedi (app.config önceden yüklenmiş)')


def _int(name, default):
    try:
        return int(os.environ.get(name, '') or default)
    except ValueError:
        return default


MB = 1024 * 1024
ACCOUNT_URL = os.environ.get('MTWEB_ACCOUNT_URL', 'http://127.0.0.1:8095').rstrip('/')
ACCOUNT_CACHE_S = _int('MTWEB_ACCOUNT_CACHE_S', 60)
COOKIE = 'sm_session'
ALL_APPS_URL = os.environ.get('MTWEB_ALL_APPS_URL', 'https://mastertool.download/uygulamalar')
DOWNLOAD_URL = os.environ.get('MTWEB_DOWNLOAD_URL', '/#indir')

APPS = ('notepadmaster', 'convertmaster')                 # web sürümü olan uygulamalar
SOON_APPS = ('sshmaster', 'ftpmaster', 'sqlmaster')       # "Web sürümü yakında" bilgi sayfası
APP_NAMES = {'notepadmaster': 'Notepad Master', 'convertmaster': 'Convert Master', 'sshmaster': 'SSH Master',
             'ftpmaster': 'FTP Masters', 'sqlmaster': 'SQL Master'}
DISABLED_APPS = frozenset(a.strip().lower() for a in os.environ.get('MTWEB_DISABLED_APPS', '').split(',') if a.strip())
# Host → /web/ yönlendirmesi
HOST_APP = {'notepadmaster.com': '/web/notepadmaster/', 'convertmaster.app': '/web/convertmaster/'}
HUB_HOSTS = ('mastertool.download',)

# Kotalar
SPACE_BYTES = _int('MTWEB_SPACE_MB', 200) * MB            # kullanıcı başına dosya alanı (iki uygulamanın toplamı)
UPLOAD_BYTES = _int('MTWEB_UPLOAD_MB', 100) * MB           # tek yükleme
MAX_FILES = _int('MTWEB_MAX_FILES', 5000)                  # kullanıcı başına dosya + klasör sayısı
BODY_BYTES = _int('MTWEB_BODY_MB', 60) * MB                # yükleme dışı istek gövdesi (Notepad kaydı ≤ 50 MB metin)
CONVERT_USER_JOBS = _int('MTWEB_CONVERT_USER_JOBS', 1)
CONVERT_JOBS = _int('MTWEB_CONVERT_JOBS', 2)
CONVERT_INPUT_BYTES = _int('MTWEB_CONVERT_INPUT_MB', 200) * MB
CONVERT_TIMEOUT_S = _int('MTWEB_CONVERT_TIMEOUT_S', 600)
CONVERT_THREADS = _int('MTWEB_CONVERT_THREADS', 2)
CONVERT_NICE = _int('MTWEB_CONVERT_NICE', 15)
IMAGE_MAX_PIXELS = _int('MTWEB_IMAGE_MAX_MPX', 80) * 1_000_000
RATE_READ = (_int('MTWEB_RATE_READ', 1200), 60)            # (adet, pencere sn) — Convert iş olayları 400 ms'de bir yoklanır
RATE_WRITE = (_int('MTWEB_RATE_WRITE', 300), 60)
AUDIT_DAYS = _int('MTWEB_AUDIT_DAYS', 90)
