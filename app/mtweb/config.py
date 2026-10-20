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

APPS = ('notepadmaster', 'convertmaster', 'sshmaster', 'ftpmaster', 'sqlmaster')   # web sürümü olan uygulamalar
SOON_APPS = ()                                            # "Web sürümü yakında" bilgi sayfası (şu an yok)
NET_APPS = ('sshmaster', 'ftpmaster', 'sqlmaster', 'notepadmaster')   # sunucudan dışarı bağlantı açan uygulamalar
# Uygulama sayfaları: yol (/web/<app>/ sonrası) → static/mt/<app>/ altındaki dosya. '' = kök sayfa.
PAGES = {
    'notepadmaster': {'': 'index.html', 'index.html': 'index.html', 'project.html': 'project.html'},
    'convertmaster': {'': 'index.html', 'index.html': 'index.html', 'project.html': 'project.html'},
    'sshmaster': {'': 'index.html', 'index.html': 'index.html', 'terminal.html': 'terminal.html'},
    'ftpmaster': {'': 'index.html', 'index.html': 'index.html', 'site.html': 'site.html'},
    # SQL Master renderer'ı alt klasörlerde (göreli yollar ../../bridge.js, ../../../common/hepgo.js): kök → main/ yönlendirmesi
    'sqlmaster': {'renderer/main/': 'renderer/main/index.html', 'renderer/main/index.html': 'renderer/main/index.html',
                  'renderer/conn/conn.html': 'renderer/conn/conn.html'},
}
APP_HOME = {'sqlmaster': '/web/sqlmaster/renderer/main/'}   # /web/<app>/ yerine açılan sayfa
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

# Dış bağlantılar (SSH Master · FTP Masters · SQL Master · Notepad uzak klasör) — guard.py
ALLOW_PRIVATE = os.environ.get('MTWEB_ALLOW_PRIVATE', '') == '1'      # YALNIZ TEST: özel/yerel adreslere izin
BLOCK_IPS = tuple(x.strip() for x in (os.environ.get('MTWEB_BLOCK_IPS') or '178.157.10.114').split(',') if x.strip())   # IP / CIDR
BLOCK_PORTS = frozenset({25, 465, 587} | {int(x) for x in os.environ.get('MTWEB_BLOCK_PORTS', '').split(',') if x.strip().isdigit()})
NET_USER_SESSIONS = _int('MTWEB_NET_USER_SESSIONS', 4)    # kullanıcı başına uygulama başına eşzamanlı bağlantı oturumu
NET_SESSIONS = _int('MTWEB_NET_SESSIONS', 300)            # genel eşzamanlı tavan
NET_ATTEMPTS_USER = _int('MTWEB_NET_ATTEMPTS_USER', 30)   # bağlantı denemesi / pencere (kullanıcı)
NET_ATTEMPTS_IP = _int('MTWEB_NET_ATTEMPTS_IP', 60)       # bağlantı denemesi / pencere (istemci IP)
NET_WINDOW_S = _int('MTWEB_NET_WINDOW_S', 600)
WS_IDLE_S = _int('MTWEB_WS_IDLE_S', 1800)                 # WebSocket boşta kapanış (istemciden ileti yok)
WS_MAX_S = _int('MTWEB_WS_MAX_S', 8 * 3600)               # WebSocket en uzun ömür
WS_PER_IP = _int('MTWEB_WS_PER_IP', 32)                   # istemci IP başına eşzamanlı WebSocket
FTP_POOL = _int('MTWEB_FTP_POOL', 2)                      # FTP sitesi başına aktarım bağlantısı tavanı
SQL_ROW_LIMIT = _int('MTWEB_SQL_ROW_LIMIT', 50_000)       # sorgu başına satır tavanı
SQL_TIMEOUT_S = _int('MTWEB_SQL_TIMEOUT_S', 60)           # SQLite ifade süresi (sunucu CPU'su)
SQL_MEMORY_MB = _int('MTWEB_SQL_MEMORY_MB', 64)           # bellek içi SQLite tavanı
