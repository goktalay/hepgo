"""Mastertool hesap servisi ayarları (SSH Master + FTP Masters; tarihî adı sshm). .env dosyaları içe aktarımda yüklenir; ortamdaki değer ezilmez.
Sırayla: SSHM_ENV_FILE (vars. <kök>/.env), ardından VEILOX_ENV_FILE (vars. /opt/hepgo/veilox/.env — register@hepgo.com SMTP
ayarları ve Merkez iç anahtarı VEILOX_CENTRAL_API_SECRET oradan okunur; dosya yoksa atlanır)."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
_loaded = set()


def _load(path):
    path = Path(path)
    if path in _loaded or not path.exists():
        return
    _loaded.add(path)
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def load():
    _load(os.environ.get('SSHM_ENV_FILE', BASE / '.env'))
    _load(os.environ.get('VEILOX_ENV_FILE', '/opt/hepgo/veilox/.env'))


load()
DATA_DIR = Path(os.environ.get('SSHM_DATA_DIR', BASE / 'data'))
RELEASE_DIR = DATA_DIR / 'releases'
STATIC_DIR = BASE / 'static'
PUBLIC_URL = os.environ.get('SSHM_PUBLIC_URL', 'https://sshmasters.com').rstrip('/')
PORTAL_URL = os.environ.get('MT_PUBLIC_URL', 'https://mastertool.download').rstrip('/')
# Hesap portalı (mastertool.download) yayında mı: 1 iken ürün sitelerindeki giriş/kayıt/hesap sayfaları portala yönlenir ve e-posta
# bağlantıları portala gider. 0 iken (DNS / tünel hazır olana dek) hesap sayfaları sshmasters.com'da çalışmaya devam eder.
PORTAL_LIVE = os.environ.get('MT_PORTAL_LIVE', '0') == '1'
SITE_URLS = {'sm': PUBLIC_URL, 'fm': os.environ.get('FTPM_PUBLIC_URL', 'https://ftpmasters.com').rstrip('/'),
             'sq': os.environ.get('SQLM_PUBLIC_URL', 'https://sqlmaster.app').rstrip('/'), 'mt': PORTAL_URL}
ACCOUNT_URL = PORTAL_URL if PORTAL_LIVE else PUBLIC_URL      # e-postalardaki doğrulama / sıfırlama / hesap bağlantıları
DEFAULT_SITE = os.environ.get('MT_DEFAULT_SITE', 'sm')         # tanınmayan Host (yerel erişim, testler) hangi site gibi davranır
RELEASE_KEYS = {'sm': os.environ.get('SSHM_RELEASE_KEY', ''), 'fm': os.environ.get('FTPM_RELEASE_KEY', ''), 'sq': os.environ.get('SQLM_RELEASE_KEY', '')}
# Destek talepleri Merkez'in talep ekranına düşer: Merkez aynı sunucuda UNIX soketinde (ya da MT_MERKEZ_URL) iç anahtarla çağrılır
MERKEZ_UDS = os.environ.get('MT_MERKEZ_UDS', '/run/hepgo/merkez.sock')
MERKEZ_URL = os.environ.get('MT_MERKEZ_URL', 'http://merkez').rstrip('/')
CENTRAL_SECRET = os.environ.get('SSHM_CENTRAL_SECRET', '') or os.environ.get('VEILOX_CENTRAL_API_SECRET', '')
SALT_KEY = os.environ.get('SSHM_SALT_KEY', '') or 'sshm-dev-salt-key'   # bilinmeyen e-postaya deterministik tuz (varlık sızmasın)
SECURE_COOKIE = os.environ.get('SSHM_SECURE_COOKIE', '1') != '0'
TOKEN_DAYS = 30            # uygulama/web oturumu: bu kadar gün kullanılmazsa düşer (her istekte uzar)
VERIFY_HOURS = 24          # e-posta doğrulama bağlantısı
RESET_MINUTES = 60         # şifre sıfırlama bağlantısı
LIBRARY_MAX = 5 * 1024 * 1024
KDF_ITER = 310_000
