import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'


def _load_env(path):
    """Basit .env okuyucu: ANAHTAR=değer satırları; ortamda zaten varsa ezmez."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


# Çok firmalı kullanım: her firma aynı kodla ayrı bir süreç olarak çalışır (ayrı port, veri klasörü ve .env).
# Ör. tenants/turkbey/.env + tenants/turkbey/data + tenants/turkbey/brand (logo ve simgeler).
_load_env(Path(os.environ.get('CAYMAZ_ENV_FILE', BASE_DIR / '.env')))

DATA_DIR = Path(os.environ.get('CAYMAZ_DATA_DIR', BASE_DIR / 'data'))
DB_PATH = Path(os.environ.get('CAYMAZ_DB', DATA_DIR / 'caymaz.db'))
UPLOAD_DIR = DATA_DIR / 'uploads'

ADMIN_USERNAME = os.environ.get('CAYMAZ_ADMIN_USERNAME', '')
ADMIN_PASSWORD = os.environ.get('CAYMAZ_ADMIN_PASSWORD', '')
ADMIN_FULL_NAME = os.environ.get('CAYMAZ_ADMIN_FULL_NAME', 'Sistem Yöneticisi')

COMPANY_NAME = os.environ.get('CAYMAZ_COMPANY_NAME', 'GÖKKUBBE Teknoloji')
# Yedek parçaların başlangıç stoğu (GÖKKUBBE sayımı); yeni firmada 0 yapılır, stok sıfırdan başlar
SEED_SPARE_STOCK = os.environ.get('CAYMAZ_SEED_SPARE_STOCK', '1') == '1'
# Firma logosu ve uygulama simgeleri: bu klasördeki img/ ve icons/ dosyaları static/ içindekilerin yerine sunulur
BRAND_DIR = Path(os.environ['CAYMAZ_BRAND_DIR']) if os.environ.get('CAYMAZ_BRAND_DIR') else None
SESSION_HOURS = int(os.environ.get('CAYMAZ_SESSION_HOURS', '12'))
PRINTER_POLL_SECONDS = int(os.environ.get('CAYMAZ_PRINTER_POLL_SECONDS', '10'))
# Testlerde arka plan yazıcı yoklamasını kapatmak için 0 yapılır.
PRINTER_POLL_ENABLED = os.environ.get('CAYMAZ_PRINTER_POLL', '1') == '1'
# Video ve uçuş logu gibi büyük dosyalar yalnızca yerel ağdan yüklenir (Cloudflare tüneli üzerinden çok yavaş).
LOCAL_URL = os.environ.get('CAYMAZ_LOCAL_URL', 'http://192.168.1.189:8080')

for d in (DATA_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)
