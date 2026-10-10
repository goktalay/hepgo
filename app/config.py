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
ADMIN_LANG = os.environ.get('CAYMAZ_ADMIN_LANG', '')   # kayıt dili → master'ın ERP varsayılan dili (prefs.settings.lang)
# İlk admin ilk girişte şifre değiştirmeli mi? Self-kayıtta master şifreyi KENDİ belirlediğinden 0 verilir (zorlanmaz).
ADMIN_MUST_CHANGE = os.environ.get('CAYMAZ_ADMIN_MUST_CHANGE', '1') != '0'

COMPANY_NAME = os.environ.get('CAYMAZ_COMPANY_NAME', 'GÖKKUBBE Teknoloji')
# Resmî / yasal ünvan: kimlik kartlarında tam ünvan gösterilir (başlıklarda kısa COMPANY_NAME kullanılır).
# Boşsa kartlarda COMPANY_NAME'e düşülür. Panelden (Program Ayarları › Firma Kimliği) canlı değiştirilebilir.
COMPANY_LEGAL_NAME = os.environ.get('CAYMAZ_COMPANY_LEGAL_NAME', '')
# Bu tenant'a merkez (Veilox) tarafından verilen modüller (virgüllü). Boşsa tüm modüller açıktır.
_mods = os.environ.get('CAYMAZ_MODULES', '').strip()
MODULES = [m.strip() for m in _mods.split(',') if m.strip()] if _mods else None
# Mikro ERP (MSSQL) tek yönlü veri aktarımı bağlantısı
MIKRO_HOST = os.environ.get('CAYMAZ_MIKRO_HOST', '192.168.1.100')
MIKRO_PORT = int(os.environ.get('CAYMAZ_MIKRO_PORT', '1433'))
MIKRO_DB = os.environ.get('CAYMAZ_MIKRO_DB', '')
MIKRO_USER = os.environ.get('CAYMAZ_MIKRO_USER', '')
MIKRO_PASSWORD = os.environ.get('CAYMAZ_MIKRO_PASSWORD', '')
# MASTER (sistem sahibi) hesapları: her firmada bu e-postalar tam yetkilidir; başka kimse MASTER olamaz.
MASTER_USERNAMES = {u.strip().lower() for u in os.environ.get(
    'CAYMAZ_MASTER_USERNAME', 'mkaderoglu@gokkubbetech.com,mkaderoglu@turkbey.com').split(',') if u.strip()}
# Web terminal (Araçlar › Terminal, /ws/console): sunucuda gerçek bir kabuk açar. Yalnız fabrikadaki yerel kurulum
# için; çok firmalı sunucuda kabuk diğer firmaların verisine erişebileceğinden varsayılan KAPALI (açmak: CAYMAZ_CONSOLE=1).
CONSOLE_ENABLED = os.environ.get('CAYMAZ_CONSOLE', '0') == '1'
# Yedek parçaların başlangıç stoğu (GÖKKUBBE sayımı); yeni firmada 0 yapılır, stok sıfırdan başlar
SEED_SPARE_STOCK = os.environ.get('CAYMAZ_SEED_SPARE_STOCK', '1') == '1'
# Firma logosu ve uygulama simgeleri: bu klasördeki img/ ve icons/ dosyaları static/ içindekilerin yerine sunulur
BRAND_DIR = Path(os.environ['CAYMAZ_BRAND_DIR']) if os.environ.get('CAYMAZ_BRAND_DIR') else None
SESSION_HOURS = int(os.environ.get('CAYMAZ_SESSION_HOURS', '12'))
# Oturum çerezi her zaman Secure (yalnız HTTPS'te gönderilir): üretimde tüm trafik Cloudflare TLS üzerinden gelir ve
# doğrudan açık TCP portu yoktur; bu yüzden varsayılan AÇIK. Yalnız yerel http:// geliştirmede CAYMAZ_FORCE_SECURE_COOKIE=0.
FORCE_SECURE_COOKIE = os.environ.get('CAYMAZ_FORCE_SECURE_COOKIE', '1') == '1'
# Dağıtık entegrasyon (fabrika ajanı): 'local' = cihazlara doğrudan erişim (bu makinede; varsayılan),
# 'remote' = Mikro ERP / PDKS / yazıcılar fabrikadaki ajan üzerinden (merkez bulut sunucuda).
AGENT_MODE = os.environ.get('CAYMAZ_AGENT_MODE', 'local').strip().lower()
# Beyaz etiket: firma kendi domaini + markasıyla kullanıyorsa (ör. caymaz.app) arayüzde HEPGO görünmez;
# her yerde firmanın adı (COMPANY_NAME) ve logosu (BRAND_DIR) kullanılır. Pakete göre provisioning'de set edilir.
WHITE_LABEL = os.environ.get('CAYMAZ_WHITE_LABEL', '0') == '1'
# Fabrika ajanının merkeze bağlanırken kullanacağı paylaşılan anahtar (her firma için ayrı).
AGENT_KEY = os.environ.get('CAYMAZ_AGENT_KEY', '')
# Ajan tarafı için merkez WebSocket adresi (ör. wss://caymaz.app/ws/agent) — yalnız ajan süreci kullanır.
AGENT_CENTRAL_URL = os.environ.get('CAYMAZ_AGENT_CENTRAL_URL', '')
# Merkez (Veilox) destek girişi — federasyon. Müşteri instance'ı, bilinmeyen kullanıcıyı merkeze sorar;
# merkez kullanıcı "Destek" rolündeyse, firma master'ının onayıyla master-benzeri geçici oturum açılır.
# Merkezde: ana anahtar. Firmada: o firmaya türetilmiş anahtar (python -m app.fedauth <slug>; bkz. app/fedauth.py)
FEDERATION_SECRET = os.environ.get('CAYMAZ_FEDERATION_SECRET', '')
# Merkez, geçiş döneminde eski ortak (ana) anahtarı da kabul etsin mi? Tüm firmalara türetilmiş anahtar verilince 0.
FEDERATION_ALLOW_SHARED = os.environ.get('CAYMAZ_FEDERATION_ALLOW_SHARED', '1') == '1'
FEDERATION_URL = os.environ.get('CAYMAZ_FEDERATION_URL', '').rstrip('/')    # müşteri: merkez taban adresi (ör. https://veilox.app)
FEDERATION_CENTRAL = os.environ.get('CAYMAZ_FEDERATION_CENTRAL', '0') == '1'   # merkez (Veilox) instance'ı mı (doğrulama ucunu açar)
FEDERATION_SESSION_HOURS = int(os.environ.get('CAYMAZ_FEDERATION_SESSION_HOURS', '4'))   # onaylı destek oturumu süresi
# Firma kimliği (merkezdeki slug): destek talebi, üyelik/ödeme bilgisi ve askı durumu merkezden bu kimlikle sorulur.
TENANT_SLUG = os.environ.get('CAYMAZ_TENANT_SLUG', '').strip().lower()
# Merkez (HEPGO merkez modu) ↔ Veilox kurulum servisi arası İÇ anahtar (federasyon anahtarından AYRI; firmalarda yok).
CENTRAL_API_SECRET = os.environ.get('CAYMAZ_CENTRAL_API_SECRET', '')
VEILOX_SOCKET = os.environ.get('CAYMAZ_VEILOX_SOCKET', '/run/hepgo/veilox.sock')
PRINTER_POLL_SECONDS = int(os.environ.get('CAYMAZ_PRINTER_POLL_SECONDS', '10'))
# Testlerde arka plan yazıcı yoklamasını kapatmak için 0 yapılır.
PRINTER_POLL_ENABLED = os.environ.get('CAYMAZ_PRINTER_POLL', '1') == '1'
# Video ve uçuş logu gibi büyük dosyalar yalnızca yerel ağdan yüklenir (Cloudflare tüneli üzerinden çok yavaş).
LOCAL_URL = os.environ.get('CAYMAZ_LOCAL_URL', 'http://192.168.1.189:8080')
# Büyük dosya (video/uçuş logu) yüklemesi yalnızca yerel ağdan mı zorunlu? Bulut/merkez kurulumda 0 yapılır.
LOCAL_UPLOAD_REQUIRED = os.environ.get('CAYMAZ_LOCAL_UPLOAD', '1') == '1'

# Şifresini hiç değiştirmemiş (yöneticinin verdiği / sıfırladığı şifreyle giren) kullanıcı ilk girişte şifresini değiştirmeden
# sistemi kullanamaz. Testler ve demo için 0 yapılabilir.
FORCE_PASSWORD_CHANGE = os.environ.get('CAYMAZ_FORCE_PASSWORD_CHANGE', '1') == '1'

# Kişisel → Mail: kurumsal Gmail (Google Workspace) için "Google ile bağlan" (OAuth). Google Cloud'da oluşturulan
# OAuth istemcisi (Web uygulaması); yönlendirme adresi https://<alan-adı>/api/mail/oauth/google/callback olarak eklenmelidir.
# PDKS (personel devam kontrol — Firebird veritabanı, ör. Fixap / ZKTeco tabanlı)
PDKS_HOST = os.environ.get('CAYMAZ_PDKS_HOST', '192.168.1.100')
PDKS_PORT = int(os.environ.get('CAYMAZ_PDKS_PORT', '3050'))
PDKS_DB = os.environ.get('CAYMAZ_PDKS_DB', r'\\192.168.1.100\MPremium\PDKS.GDB')
PDKS_USER = os.environ.get('CAYMAZ_PDKS_USER', 'SYSDBA')
PDKS_PASSWORD = os.environ.get('CAYMAZ_PDKS_PASSWORD', '')

# NVR (ağ kayıt cihazı — kameralar NVR arkasında; ONVIF + RTSP). Uzak modda fabrika ajanı üzerinden erişilir.
NVR_HOST = os.environ.get('CAYMAZ_NVR_HOST', '')
NVR_PORT = int(os.environ.get('CAYMAZ_NVR_PORT', '80'))
NVR_USER = os.environ.get('CAYMAZ_NVR_USER', 'admin')
NVR_PASSWORD = os.environ.get('CAYMAZ_NVR_PASSWORD', '')

GOOGLE_CLIENT_ID = os.environ.get('CAYMAZ_GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('CAYMAZ_GOOGLE_CLIENT_SECRET', '')
# Microsoft (Outlook.com / Microsoft 365 / Exchange Online) OAuth — Azure › Entra ID › App registrations
MS_CLIENT_ID = os.environ.get('CAYMAZ_MS_CLIENT_ID', '')
MS_CLIENT_SECRET = os.environ.get('CAYMAZ_MS_CLIENT_SECRET', '')
MS_TENANT = os.environ.get('CAYMAZ_MS_TENANT', 'common')
# Sosyal medya OAuth uygulamaları (anahtar girilince ilgili sağlayıcı Kişisel Ayarlar › Sosyal Medya'da açılır)
META_APP_ID = os.environ.get('CAYMAZ_META_APP_ID', '')
META_APP_SECRET = os.environ.get('CAYMAZ_META_APP_SECRET', '')
X_CLIENT_ID = os.environ.get('CAYMAZ_X_CLIENT_ID', '')
X_CLIENT_SECRET = os.environ.get('CAYMAZ_X_CLIENT_SECRET', '')
# Spotify (kullanıcı kendi Spotify hesabını bağlar: anlık çalan + oynatma kontrolü). developer.spotify.com › Dashboard
SPOTIFY_CLIENT_ID = os.environ.get('CAYMAZ_SPOTIFY_CLIENT_ID', '')
SPOTIFY_CLIENT_SECRET = os.environ.get('CAYMAZ_SPOTIFY_CLIENT_SECRET', '')
# Konuşma tanıma (ses → metin, konuşmacı / ses kimliği): Program Ayarları › Entegrasyonlar › Konuşma Tanıma. Kapalıyken
# toplantı / görüşme / evrak sesleri yalnız KAYDEDİLİR; metne çevrilmez, konuşmacı tanınmaz, sesle yazdırma görünmez.
SPEECH_ENABLED = os.environ.get('CAYMAZ_SPEECH', '0') == '1'
# Konuşma tanıma fabrikadaki ajanda (GX10, NVIDIA GB10) mı yapılsın (yalnız AGENT_MODE=remote iken geçerli)
SPEECH_ON_AGENT = os.environ.get('CAYMAZ_SPEECH_AGENT', '0') == '1'
# X (Twitter) paylaşımları kaç saatte bir çekilsin (okuma kotası ücretli/sınırlı; elle yenileme her zaman çalışır)
X_POLL_HOURS = float(os.environ.get('CAYMAZ_X_POLL_HOURS', '6') or 6)
TIKTOK_CLIENT_KEY = os.environ.get('CAYMAZ_TIKTOK_CLIENT_KEY', '')
TIKTOK_CLIENT_SECRET = os.environ.get('CAYMAZ_TIKTOK_CLIENT_SECRET', '')
# Google Haritalar JavaScript API anahtarı (istemci tarafında kullanılır; HTTP yönlendiren kısıtıyla korunur).
GOOGLE_MAPS_API_KEY = os.environ.get('CAYMAZ_GOOGLE_MAPS_API_KEY', '')
PUBLIC_URL = os.environ.get('CAYMAZ_PUBLIC_URL', '').rstrip('/')   # ör. https://caymaz.app

# Yapay zeka asistanı (maskot sohbeti) — Claude API. Anahtar .env'de tutulur (asla loglanmaz).
# CAYMAZ_AI_API_KEY yoksa standart ANTHROPIC_API_KEY de kabul edilir. Model env ile değiştirilebilir.
AI_API_KEY = os.environ.get('CAYMAZ_AI_API_KEY', '') or os.environ.get('ANTHROPIC_API_KEY', '')
AI_MODEL = os.environ.get('CAYMAZ_AI_MODEL', 'claude-haiku-4-5')
# Anahtar bir çalışma alanına (workspace) bağlı değilse Anthropic bu başlığı ister. Workspace'e bağlı anahtarda gerekmez.
AI_WORKSPACE_ID = os.environ.get('CAYMAZ_AI_WORKSPACE_ID', '')

for d in (DATA_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)
