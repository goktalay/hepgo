"""Mastertool hesap ve senkronizasyon servisi: tek hesapla SSH Master (sm) ve FTP Masters (fm).
Sözleşmeler: docs/sshmaster-api.md (v2, /api/sm — geriye dönük uyumlu), docs/ftpmasters-api.md (/api/fm), portal /api/mt.

- Siteler Host başlığıyla ayrılır: mastertool.download (hesap portalı + /uygulamalar web başlatıcısı), ürün siteleri (sshmasters.com …:
  tanıtım, site içi giriş / kayıt; MT_PORTAL_LIVE=1 iken Hesabım, doğrulama, şifre sıfırlama ve indirme portala yönlenir).
- Kimlik uçları (/auth/*, /me) üç önekte de aynıdır; kütüphane / ayar / sürüm uçları uygulamaya özeldir (/api/sm, /api/fm).
  Uygulama oturumu kendi uygulamasının uçlarını kullanır; yönetici o uygulamanın lisansını KAPALI yaparsa giriş ve indirme kapanır.

- Düz şifre sunucuya HİÇ gelmez: istemci (uygulama ve web/WebCrypto) master = PBKDF2(şifre, kdf_salt, 310000) türetir,
  auth_hash = b64(PBKDF2(master, şifre, 1)) gönderir; sunucu auth_hash'i kendi PBKDF2'siyle (ayrı tuz) saklar.
  Kütüphane anahtarı (HKDF(master)) istemcide kalır; sunucu blob'u okuyamaz.
- Web oturumu çerez (sm_session, HttpOnly/Secure/Lax); çerezli değişiklik istekleri ayrıca X-SSHM: 1 başlığı ister (CSRF).
  Uygulama oturumu Bearer token. Token'lar özet olarak saklanır.
- Kişiye özel indirme /indir/<dl_token>: yalnız AYNI kullanıcı web oturumuyla çalışır.
- Yönetim (HEPGO Merkez): /api/sm/admin/* iç anahtarla (X-Central-Secret). Destek talepleri Merkez'e iç anahtarla iletilir.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
from collections import defaultdict, deque
from html import escape as _hesc

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from . import db, mailer, merkez, mw_catalog, seo, settings

VERSION = '2.0.0'
APPS = {'sm': {'name': 'SSH Master', 'setup': 'SSH Master Setup {v}.exe', 'portable': 'SSH-Master-Portable-{v}.exe'},
        'fm': {'name': 'FTP Masters', 'setup': 'FTP-Masters-Setup-{v}.exe', 'portable': 'FTP-Masters-Portable-{v}.exe'},
        'sq': {'name': 'SQL Master', 'setup': 'SQL-Master-Setup-{v}.exe', 'portable': 'SQL-Master-Portable-{v}.exe'},
        'np': {'name': 'Notepad Master', 'setup': 'Notepad-Master-Setup-{v}.exe', 'portable': 'Notepad-Master-Portable-{v}.exe'},
        'cv': {'name': 'Convert Master', 'setup': 'Convert-Master-Setup-{v}.exe', 'portable': 'Convert-Master-Portable-{v}.exe'}}
# Araçlar: Master Tool altındaki küçük uygulamalar — kendi siteleri yok; tanıtım mastertool.download/araclar/<slug>, indirme Hesabım ve
# Master Tool'dan. Yeni araç = buraya bir satır + <SLUG büyük harf>_RELEASE_KEY (sunucu .env + GitHub) + static/mt/araclar/<slug>.html.
TOOLS = {'ip': {'name': 'IP Tools', 'slug': 'ip-tools', 'setup': 'IP-Tools-Setup-{v}.exe', 'portable': 'IP-Tools-Portable-{v}.exe'},
         'fs': {'name': 'File Search', 'slug': 'file-search', 'setup': 'File-Search-Setup-{v}.exe', 'portable': 'File-Search-Portable-{v}.exe'},
         'qp': {'name': 'Quick Preview', 'slug': 'quick-preview', 'setup': 'Quick-Preview-Setup-{v}.exe', 'portable': 'Quick-Preview-Portable-{v}.exe'},
         'm3': {'name': 'Master 3D', 'slug': 'master-3d', 'setup': 'Master-3D-Setup-{v}.exe', 'portable': 'Master-3D-Portable-{v}.exe'},
         'sd': {'name': 'Social Download', 'slug': 'social-download', 'setup': 'Social-Download-Setup-{v}.exe', 'portable': 'Social-Download-Portable-{v}.exe'},
         # group:'apps' — katalogda uygulamalarla; path: tanıtım sayfası araclar/ altında değil kökte (dosya yine static/mt/araclar/<slug>.html)
         'md': {'name': 'Master Download', 'slug': 'master-download', 'group': 'apps', 'path': '/master-download',
                'setup': 'Master-Download-Setup-{v}.exe', 'portable': 'Master-Download-Portable-{v}.exe'}}
TOOLS['ip']['desc'] = {'tr': 'Ağdaki cihazları, açık portları ve servisleri tarar', 'en': 'Scans your network for devices, open ports and services',
                       'fr': 'Analyse le réseau : appareils, ports ouverts et services', 'de': 'Durchsucht das Netzwerk nach Geräten, offenen Ports und Diensten',
                       'es': 'Escanea la red en busca de dispositivos, puertos abiertos y servicios', 'ar': 'يفحص الشبكة بحثًا عن الأجهزة والمنافذ المفتوحة والخدمات',
                       'zh': '扫描网络中的设备、开放端口和服务', 'ru': 'Сканирует сеть: устройства, открытые порты и службы'}
TOOLS['fs']['desc'] = {'tr': 'Klasörleri dizinler, belgelerin içinde akıllı arama yapar', 'en': 'Indexes folders and searches smartly inside documents',
                       'fr': 'Indexe des dossiers et recherche intelligemment dans les documents', 'de': 'Indiziert Ordner und durchsucht Dokumente intelligent',
                       'es': 'Indexa carpetas y busca de forma inteligente dentro de los documentos', 'ar': 'يفهرس المجلدات ويبحث بذكاء داخل المستندات',
                       'zh': '为文件夹建立索引，并在文档内容中智能搜索', 'ru': 'Индексирует папки и умно ищет по содержимому документов'}
TOOLS['qp']['desc'] = {'tr': 'Sağ tıkla dosyaları anında önizler (resim, PSD, PDF)', 'en': 'Instantly previews files from the right-click menu (images, PSD, PDF)',
                       'fr': 'Aperçu instantané des fichiers depuis le clic droit (images, PSD, PDF)', 'de': 'Sofortvorschau von Dateien per Rechtsklick (Bilder, PSD, PDF)',
                       'es': 'Vista previa instantánea de archivos con clic derecho (imágenes, PSD, PDF)', 'ar': 'يعاين الملفات فورًا من قائمة النقر بزر الماوس الأيمن (صور، PSD، PDF)',
                       'zh': '通过右键菜单即时预览文件（图片、PSD、PDF）', 'ru': 'Мгновенный предпросмотр файлов из контекстного меню (изображения, PSD, PDF)'}
TOOLS['m3']['desc'] = {'tr': '3B dosyaları açar, parçalarına ayırır (patlatma) ve 15 biçime dışa aktarır (STEP, FBX, glTF, STL…)',
                       'en': 'Opens 3D files, explodes them into parts and exports to 15 formats (STEP, FBX, glTF, STL…)',
                       'fr': 'Ouvre les fichiers 3D, les éclate en pièces et exporte vers 15 formats (STEP, FBX, glTF, STL…)',
                       'de': 'Öffnet 3D-Dateien, zerlegt sie in Teile (Explosionsansicht) und exportiert in 15 Formate (STEP, FBX, glTF, STL…)',
                       'es': 'Abre archivos 3D, los despieza (vista explosionada) y exporta a 15 formatos (STEP, FBX, glTF, STL…)',
                       'ar': 'يفتح الملفات ثلاثية الأبعاد ويفككها إلى قطع ويصدّرها إلى 15 صيغة (STEP وFBX وglTF وSTL…)',
                       'zh': '打开 3D 文件，拆分为零件（爆炸视图），并导出为 15 种格式（STEP、FBX、glTF、STL…）',
                       'ru': 'Открывает 3D-файлы, разносит их на детали и экспортирует в 15 форматов (STEP, FBX, glTF, STL…)'}
TOOLS['sd']['desc'] = {'tr': 'Herkese açık sosyal medya bağlantılarından video ve ses indirir (çözünürlük seçimi, oynatma listesi, kuyruk)',
                       'en': 'Downloads video and audio from public social media links (resolution choice, playlists, queue)',
                       'fr': 'Télécharge vidéo et audio depuis des liens publics de réseaux sociaux (choix de résolution, playlists, file d’attente)',
                       'de': 'Lädt Video und Audio von öffentlichen Social-Media-Links (Auflösungswahl, Playlists, Warteschlange)',
                       'es': 'Descarga vídeo y audio de enlaces públicos de redes sociales (elección de resolución, listas, cola)',
                       'ar': 'ينزّل الفيديو والصوت من روابط وسائل التواصل الاجتماعي العامة (اختيار الدقة، قوائم التشغيل، قائمة الانتظار)',
                       'zh': '从公开的社交媒体链接下载视频和音频（选择分辨率、播放列表、下载队列）',
                       'ru': 'Скачивает видео и звук по общедоступным ссылкам соцсетей (выбор разрешения, плейлисты, очередь)'}
TOOLS['md']['desc'] = {'tr': 'İnternetten hızlı indirme yöneticisi: çok bağlantılı, sürdürülebilir, tarayıcı eklentili',
                       'en': 'Fast download manager: multi-connection, resumable, with browser integration',
                       'fr': 'Gestionnaire de téléchargements rapide : multi-connexion, reprise possible, intégration au navigateur',
                       'de': 'Schneller Download-Manager: mehrere Verbindungen, fortsetzbar, mit Browser-Integration',
                       'es': 'Gestor de descargas rápido: multiconexión, reanudable, con integración en el navegador',
                       'ar': 'مدير تنزيل سريع: اتصالات متعددة، قابل للاستئناف، مع تكامل المتصفح',
                       'zh': '快速下载管理器：多连接、支持断点续传、集成浏览器扩展',
                       'ru': 'Быстрый менеджер загрузок: многопоточный, с докачкой и интеграцией в браузер'}
APPS |= TOOLS                                          # lisans, oturum, senkron, sürüm ve indirme araçlarda da aynı
# Oyunlar: mastertool.download altında sunulan web (HTML5) oyunları — kurulum, lisans ve sürüm yok; Mastertool hesabıyla giriş ve
# kullanıcı başına tek profil JSON'u (/api/<kod>/profile). Dosyalar depoda DEĞİLDİR: dağıtımda static/mt/oyunlar/<slug>/ altına
# kopyalanır (tanıtım sayfası static/mt/oyunlar/<slug>/tanitim/ depodan gelir). Simge: static/mt/img/<slug>.svg|.png|-512.png.
GAMES = {'vf': {'name': 'VOLFAI', 'slug': 'volfai', 'icon': 'volfai'},
         # SIMUMAV: kendi sitesinde çalışan oyun (site → url/tanıtım simumav.com; mastertool.download altında dosya sunulmaz); profil sv_profiles
         'sv': {'name': 'SIMUMAV', 'slug': 'simumav', 'icon': 'simumav', 'site': settings.SIMUMAV_SITE, 'promo': settings.SIMUMAV_SITE + '/'},
         # MASTERWORLD: kendi sitesinde çalışan web UYGULAMASI (oyun değil: group 'apps'); üyelik isteğe bağlı, ayarlar mw_profiles (docs/masterworld.md §7)
         'mw': {'name': 'MASTERWORLD', 'slug': 'masterworld', 'icon': 'masterworld', 'site': settings.MASTERWORLD_SITE,
                'promo': settings.MASTERWORLD_SITE + '/', 'group': 'apps'}}
GAMES['vf']['desc'] = {'tr': "Volfied'in dokunmatik yeniden doğuşu: alanı ele geçir, uzaylıları kuşat", 'en': 'A touch-first rebirth of Volfied: claim the field, trap the aliens',
                       'fr': "Renaissance tactile de Volfied : conquérez le terrain, encerclez les aliens", 'de': 'Volfied neu für Touch: Fläche erobern, Aliens einkesseln',
                       'es': 'El renacer táctil de Volfied: conquista el campo, acorrala a los aliens', 'ar': 'ولادة جديدة للمس للعبة Volfied: استولِ على الساحة وحاصر الفضائيين',
                       'zh': 'Volfied 的触屏新生：占领区域，围困外星人', 'ru': 'Volfied заново для сенсора: захватывай поле, окружай пришельцев'}
GAMES['sv']['desc'] = {'tr': 'ArduPilot SITL fiziği, Google 3B dünyası ve Mission Planner bağlantısıyla tarayıcıda çalışan dron simülasyon oyunu',
                       'en': 'A drone simulation game that runs in the browser on ArduPilot SITL physics, the Google 3D world and a Mission Planner link',
                       'fr': 'Jeu de simulation de drone dans le navigateur : physique ArduPilot SITL, monde 3D de Google et liaison Mission Planner',
                       'de': 'Drohnen-Simulationsspiel im Browser mit ArduPilot-SITL-Physik, Googles 3D-Welt und Mission-Planner-Anbindung',
                       'es': 'Juego de simulación de drones en el navegador con física ArduPilot SITL, el mundo 3D de Google y enlace a Mission Planner',
                       'ar': 'لعبة محاكاة طائرات بدون طيار تعمل في المتصفح بفيزياء ArduPilot SITL وعالم Google ثلاثي الأبعاد واتصال Mission Planner',
                       'zh': '在浏览器中运行的无人机模拟游戏：ArduPilot SITL 物理、Google 3D 世界与 Mission Planner 连接',
                       'ru': 'Игра-симулятор дрона в браузере: физика ArduPilot SITL, 3D-мир Google и связь с Mission Planner'}
GAMES['mw']['desc'] = {'tr': 'Uçak, gemi, uydu, deprem, kamera ve radyo gibi kamuya açık canlı verileri tam ekran 3B kürede gösteren web uygulaması',
                       'en': 'A web app that shows public live data such as aircraft, ships, satellites, earthquakes, cameras and radio on a full-screen 3D globe',
                       'fr': "Application web qui affiche sur un globe 3D plein écran des données publiques en direct : avions, navires, satellites, séismes, caméras et radios",
                       'de': 'Web-App, die öffentliche Live-Daten wie Flugzeuge, Schiffe, Satelliten, Erdbeben, Kameras und Radio auf einem 3D-Vollbild-Globus zeigt',
                       'es': 'Aplicación web que muestra en un globo 3D a pantalla completa datos públicos en directo: aviones, barcos, satélites, terremotos, cámaras y radio',
                       'ar': 'تطبيق ويب يعرض البيانات الحية العامة مثل الطائرات والسفن والأقمار الصناعية والزلازل والكاميرات والراديو على كرة أرضية ثلاثية الأبعاد بملء الشاشة',
                       'zh': '在全屏 3D 地球上展示飞机、船舶、卫星、地震、摄像头和电台等公开实时数据的网页应用',
                       'ru': 'Веб-приложение, показывающее на полноэкранном 3D-глобусе открытые данные в реальном времени: самолёты, суда, спутники, землетрясения, камеры и радио'}
GAME_FILE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')          # oyun dizinindeki yol parçaları (gizli dosya ve .. yok)
GAME_MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
             '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.map': 'application/json',
             '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif',
             '.ico': 'image/x-icon', '.wasm': 'application/wasm', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.m4a': 'audio/mp4',
             '.woff': 'font/woff', '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8'}
# Oyun dizininin içerik güvenlik politikası: oyun kendi dosyaları + aynı kökendeki /api; satır içi betik yok (VOLFAI: type=module src)
GAME_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; "
            "connect-src 'self'; worker-src 'self'; manifest-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'")
# Tanıtım sayfası: site kiti (kit.js/kit.css) + yalnız ziyaretçi izniyle Google Analytics (kit.js gtag betiğini ekler)
PROMO_CSP = ("default-src 'self'; script-src 'self' https://www.googletagmanager.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: "
             "https://www.googletagmanager.com https://*.google-analytics.com; connect-src 'self' https://*.google-analytics.com "
             "https://*.analytics.google.com https://www.googletagmanager.com; font-src 'self'; object-src 'none'; base-uri 'self'; "
             "form-action 'self'; frame-ancestors 'self'")
# Web sürümleri (mtweb servisi; Cloudflare tüneli /web, /static/mt, /api/tools, /ws/tools yollarını ona verir): her Mastertool
# hostunda /web/<slug>/ adresinde çalışır, oturumu aynı hosttaki sm_session çerezinden /api/mt/me ile doğrular. Araçlarda (IP Tools …)
# web sürümü YOK (sunucudan ağ taraması güvenlik nedeniyle sunulmaz) — yalnız indirme.
WEB_APPS = {'sm': 'sshmaster', 'fm': 'ftpmaster', 'sq': 'sqlmaster', 'np': 'notepadmaster', 'cv': 'convertmaster'}
# Hesap sayfaları ve başlatıcı (/uygulamalar): satır içi betik yok; iframe yalnız aynı köken (/web/, /oyunlar/)
ACCOUNT_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
               "font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
LAUNCHER_CSP = ACCOUNT_CSP.replace("connect-src 'self';", "connect-src 'self'; frame-src 'self';")
PROFILE_MAX = 64 * 1024                               # oyun profili JSON'u üst sınırı (bayt)
LAUNCHER = {'name': 'Master Tool', 'setup': 'Master-Tool-Setup-{v}.exe', 'portable': 'Master-Tool-Portable-{v}.exe'}
MT_CLIENTS = ('desktop', 'android', 'ios')          # Master Tool istemcileri: /api/mt/auth/login'de yalnız ortak (sso) oturum açar
MT_APPS_WEB_MIN = (1, 2, 0)                         # /api/mt/apps?v=<istemci sürümü>: kind:'web' (oyun) kayıtları bu sürümden itibaren verilir
RELEASE_APPS = APPS | {'mt': LAUNCHER}              # sürüm yükleme / indirme: uygulamalar + Master Tool masaüstü (başlatıcı)
PREFIXES = ('sm', 'fm', 'sq', 'np', 'cv', 'mt') + tuple(TOOLS) + tuple(GAMES)   # mt = Mastertool portalı (web hesabı); kimlik uçları her önekte aynı
SITES = ('sm', 'fm', 'sq', 'np', 'cv', 'mt')
app = FastAPI(title='Mastertool', docs_url=None, redoc_url=None, openapi_url=None)
COOKIE = 'sm_session'
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$')
AUTH_RE = re.compile(r'^[A-Za-z0-9+/]{43}=$')          # base64(32 bayt)
SALT_RE = re.compile(r'^[A-Za-z0-9+/]{22}==$')          # base64(16 bayt)
VERSION_RE = re.compile(r'^\d{1,4}\.\d{1,4}\.\d{1,4}([.-][0-9A-Za-z.-]{1,20})?$')
SERVER_ITER = 240_000


# ---------------- yardımcılar ----------------
class Err(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def need_release_app(a):
    if a not in RELEASE_APPS:
        raise Err(404, 'not_found', 'Bulunamadı')
    return a


def need_prefix(a, apps_only=False):
    if a not in (APPS if apps_only else PREFIXES):
        raise Err(404, 'not_found', 'Bulunamadı')
    return a


def _site_origins(site):
    return {site, site.replace('https://', 'https://www.')}


SV_CORS_ORIGINS = _site_origins(settings.SIMUMAV_SITE)
MW_CORS_ORIGINS = _site_origins(settings.MASTERWORLD_SITE)
# yol öneki → izinli kökenler: her site YALNIZ kendi önekinde (simumav.com /api/sv/*, masterworld.app /api/mw/*). Sunucular arası iç uçlar hariç.
CORS_SITES = (('/api/sv/', SV_CORS_ORIGINS), ('/api/mw/', MW_CORS_ORIGINS))
CORS_EXCLUDE = ('/api/mw/internal/',)


def cors_allowed(path, origin):
    return bool(origin) and not path.startswith(CORS_EXCLUDE) and any(path.startswith(p) and origin in o for p, o in CORS_SITES)


@app.middleware('http')
async def _site_cors(request: Request, call_next):
    """CORS yalnız kendi sitesinde çalışan uygulamaların yolları ve yalnız o sitenin kökeni (SIMUMAV /api/sv/* ← simumav.com,
    MASTERWORLD /api/mw/* ← masterworld.app): tarayıcı hesap servisine o siteden Bearer ile giriş yapar.
    Çerez gönderilmez (credentials yok); izinli başlıklar Authorization, Content-Type, X-SSHM."""
    origin = request.headers.get('origin')
    izinli = cors_allowed(request.url.path, origin)
    if izinli and request.method == 'OPTIONS':
        resp = Response(status_code=204)
    else:
        resp = await call_next(request)
    if izinli:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, X-SSHM'
        resp.headers['Access-Control-Max-Age'] = '600'
        resp.headers['Vary'] = 'Origin'
    return resp


@app.exception_handler(Err)
async def _err(request, e: Err):
    return JSONResponse({'code': e.code, 'message': e.message, 'detail': e.message}, status_code=e.status)


@app.exception_handler(HTTPException)
async def _http(request, e: HTTPException):
    msg = e.detail if isinstance(e.detail, str) else 'Hata'
    return JSONResponse({'code': 'error', 'message': msg, 'detail': msg}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def _val(request, e):
    return JSONResponse({'code': 'invalid', 'message': 'İstek gövdesi geçersiz', 'detail': 'İstek gövdesi geçersiz'}, status_code=422)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def b64salt():
    return base64.b64encode(secrets.token_bytes(16)).decode()


def det_salt(email):
    """Kullanıcı yokken / kayıtta: e-postaya bağlı deterministik tuz (prelogin varlık sızdırmasın)."""
    return base64.b64encode(hmac.new(settings.SALT_KEY.encode(), email.lower().encode(), hashlib.sha256).digest()[:16]).decode()


def hash_auth(auth_hash):
    salt = secrets.token_bytes(16)
    d = hashlib.pbkdf2_hmac('sha256', auth_hash.encode(), salt, SERVER_ITER)
    return f'pbkdf2_sha256${SERVER_ITER}${salt.hex()}${d.hex()}'


def check_auth(auth_hash, stored):
    try:
        _, it, salt, d = stored.split('$')
        calc = hashlib.pbkdf2_hmac('sha256', auth_hash.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), d)
    except (ValueError, AttributeError):
        return False


_DUMMY = hash_auth('A' * 43 + '=')   # bilinmeyen e-postada da aynı süre harcansın (zamanlama ile varlık sızmasın)


def kdf(salt):
    return {'alg': 'PBKDF2-SHA256', 'iter': settings.KDF_ITER, 'salt': salt}


def client_ip(request: Request):
    return (request.headers.get('cf-connecting-ip') or (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
            or (request.client.host if request.client else ''))[:64]


_RATE = defaultdict(deque)


def rate(request, key, limit, window=60):
    k = f'{key}:{client_ip(request)}'
    q, t = _RATE[k], time.time()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= limit:
        raise Err(429, 'rate_limited', 'Çok fazla deneme; biraz sonra tekrar deneyin')
    q.append(t)


async def body(request):
    try:
        b = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    if not isinstance(b, dict):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    return b


def norm_email(v):
    e = str(v or '').strip().lower()
    if not EMAIL_RE.match(e):
        raise Err(422, 'invalid_email', 'Geçerli bir e-posta adresi girin')
    return e


def need_auth_hash(v, field='auth_hash'):
    v = str(v or '')
    if not AUTH_RE.match(v):
        raise Err(422, 'invalid', f'{field} geçersiz')
    return v


def user_public(u):
    return {'id': u['id'], 'email': u['email'], 'name': u['name'], 'verified': bool(u['verified_at']) or u['status'] == 'AKTIF'}


def lic(conn, uid, a):
    """Kullanıcının uygulama lisansı / senkron tercihi; satır yoksa varsayılanla (AKTIF, senkron açık) oluşturulur."""
    r = conn.execute('SELECT * FROM user_apps WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    if not r:
        conn.execute('INSERT OR IGNORE INTO user_apps (user_id, app, created_at) VALUES (?,?,?)', (uid, a, db.now()))
        conn.commit()
        r = conn.execute('SELECT * FROM user_apps WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    return r


def need_license(conn, uid, a):
    if a in APPS and lic(conn, uid, a)['license'] != 'AKTIF':
        raise Err(403, 'app_disabled', f'Bu hesapta {APPS[a]["name"]} kullanımı kapalı')


def new_session(conn, user_id, kind, device=None, app_version=None, ip=None, a=None, parent_id=None):
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO sessions (user_id, token_hash, kind, app, device, app_version, ip, created_at, last_seen, parent_id) '
                 'VALUES (?,?,?,?,?,?,?,?,?,?)',
                 (user_id, sha(tok), kind, a if kind == 'app' else None, (device or '')[:120] or None, (app_version or '')[:30] or None, ip,
                  db.now(), time.time(), parent_id))
    return tok


def end_session(conn, s):
    """Oturumu kapatır. Ortak (sso) oturum ya da ondan türetilmiş uygulama oturumu kapanınca o cihazdaki tüm aile düşer:
    ana sso oturumu ve ona bağlı bütün uygulama oturumları. Dönüş: sso ailesi kapandı mı."""
    root = s['id'] if s['kind'] == 'sso' else s['parent_id']
    if root:
        conn.execute('DELETE FROM sessions WHERE id = ? OR parent_id = ?', (root, root))
    conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))
    return bool(root)


def current(request, conn, require=True, web_only=False, a=None):
    """Oturumdaki kullanıcı: Bearer (uygulama) ya da çerez (web). Dönüş (user_row, session_row) | (None, None).
    a (sm|fm) verilirse uygulama oturumu yalnız kendi uygulamasının uçlarını kullanabilir ve lisansı açık olmalıdır."""
    tok, via_cookie = None, False
    hdr = request.headers.get('authorization') or ''
    if hdr.lower().startswith('bearer ') and not web_only:
        tok = hdr[7:].strip()
    elif request.cookies.get(COOKIE):
        tok, via_cookie = request.cookies.get(COOKIE), True
    if not tok:
        if require:
            raise Err(401, 'unauthorized', 'Oturum açın')
        return None, None
    s = conn.execute('SELECT * FROM sessions WHERE token_hash = ?', (sha(tok),)).fetchone()
    if not s or time.time() - s['last_seen'] > settings.TOKEN_DAYS * 86400:
        if s:
            conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))
            conn.commit()
        if require:
            raise Err(401, 'session_expired', 'Oturum süresi doldu; yeniden giriş yapın')
        return None, None
    u = conn.execute('SELECT * FROM users WHERE id = ?', (s['user_id'],)).fetchone()
    if not u or u['status'] != 'AKTIF':
        if require:
            raise Err(403, 'suspended' if u and u['status'] == 'ASKIDA' else 'unauthorized', 'Hesap kullanılamıyor')
        return None, None
    if via_cookie and request.method not in ('GET', 'HEAD') and request.headers.get('x-sshm') != '1':
        raise Err(403, 'csrf', 'Geçersiz istek')
    if s['parent_id'] and not conn.execute('SELECT 1 FROM sessions WHERE id = ?', (s['parent_id'],)).fetchone():
        conn.execute('DELETE FROM sessions WHERE id = ?', (s['id'],))   # ortak oturum başka bir uygulamada kapatıldı
        conn.commit()
        if require:
            raise Err(401, 'session_expired', 'Oturum kapatıldı; yeniden giriş yapın')
        return None, None
    if s['kind'] == 'sso' and a in APPS:
        raise Err(403, 'wrong_app', 'Ortak oturum yalnız Master Tool uçlarında geçer; uygulama oturumu için /auth/sso kullanın')
    if s['kind'] == 'app' and a in APPS:
        if (s['app'] or 'sm') != a:
            raise Err(403, 'wrong_app', 'Bu oturum başka bir uygulamaya ait')
        need_license(conn, u['id'], a)
    conn.execute('UPDATE sessions SET last_seen = ? WHERE id = ? OR id = ?', (time.time(), s['id'], s['parent_id'] or 0))
    conn.commit()
    return u, s


def set_cookie(resp, tok):
    resp.set_cookie(COOKIE, tok, max_age=settings.TOKEN_DAYS * 86400, httponly=True, secure=settings.SECURE_COOKIE, samesite='lax', path='/')


def central(request):
    sec = request.headers.get('x-central-secret') or ''
    if not settings.CENTRAL_SECRET or not hmac.compare_digest(sec, settings.CENTRAL_SECRET):
        raise Err(403, 'forbidden', 'Yetkisiz')


def new_token(conn, user_id, kind, seconds, salt=None):
    tok = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO tokens (user_id, kind, token_hash, salt, expires) VALUES (?,?,?,?,?)', (user_id, kind, sha(tok), salt, time.time() + seconds))
    return tok


def take_token(conn, tok, kind):
    t = conn.execute('SELECT * FROM tokens WHERE token_hash = ? AND kind = ?', (sha(tok or ''), kind)).fetchone()
    if not t or t['used_at'] or t['expires'] < time.time():
        return None
    return t


def latest_release(conn, a='sm'):
    return conn.execute('SELECT * FROM releases WHERE app = ? ORDER BY id DESC LIMIT 1', (a,)).fetchone()


def rel_dir(a, version):
    return settings.RELEASE_DIR / version if a == 'sm' else settings.RELEASE_DIR / a / version   # sm: v1 yolu korunur


def site_of(request):
    """İsteğin geldiği site: mastertool.download → mt, sshmasters.com → sm, ftpmasters.com → fm (www dahil)."""
    host = (request.headers.get('host') or '').split(':')[0].lower().removeprefix('www.')
    for k, url in settings.SITE_URLS.items():
        if host and host == url.split('://', 1)[-1].split('/')[0].lower().removeprefix('www.'):
            return k
    return settings.DEFAULT_SITE if settings.DEFAULT_SITE in SITES else 'sm'


NEXT_BAD = re.compile(r'[\x00-\x20\x7f\\]')


def safe_next(v):
    """Giriş sonrası dönüş adresi (açık yönlendirme yok): yalnız aynı sitede göreli yol — '/' ile başlar, '//' ile başlamaz, ters bölü,
    boşluk ve denetim karakteri içermez, ≤ 512 karakter. Geçersizse ''."""
    v = str(v or '')
    if not v.startswith('/') or v.startswith('//') or len(v) > 512 or NEXT_BAD.search(v):
        return ''
    return v


def acct(path):
    return f'{settings.ACCOUNT_URL}{path}'


@app.on_event('startup')
def _startup():
    db.init()
    settings.RELEASE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------- genel ----------------
@app.get('/api/{a}/health')
def health(a: str):
    need_prefix(a)
    return {'ok': True, 'version': VERSION, 'time': db.now()}


@app.post('/api/{a}/auth/prelogin')
async def prelogin(a: str, request: Request):
    need_prefix(a)
    rate(request, 'prelogin', 30)
    email = norm_email((await body(request)).get('email'))
    with db.connect() as conn:
        u = conn.execute('SELECT kdf_salt FROM users WHERE email = ?', (email,)).fetchone()
    return {'kdf': kdf(u['kdf_salt'] if u else det_salt(email))}


def brand_of(a, b):
    br = str((b or {}).get('brand') or '')
    return br if br in SITES else (a if a in SITES else 'mt')   # araçların kendi sitesi yok → Mastertool markası


@app.post('/api/{a}/auth/register')
async def register(a: str, request: Request):
    need_prefix(a)
    rate(request, 'register', 5)
    b = await body(request)
    brand = brand_of(a, b)
    email = norm_email(b.get('email'))
    name = re.sub(r'\s+', ' ', str(b.get('name') or '')).strip()[:80]
    if len(name) < 2:
        raise Err(422, 'invalid_name', 'Adınızı girin')
    auth = need_auth_hash(b.get('auth_hash'))
    if not mailer.enabled():
        raise Err(503, 'mail_disabled', 'E-posta gönderimi şu an kullanılamıyor')
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if u and u['status'] != 'BEKLIYOR':
            mailer.send_exists(email, u['name'], acct('/giris'), acct('/sifremi-unuttum'), brand)
            return {'ok': True}
        if u:   # doğrulanmamış kayıt yinelendi: ad/şifre güncellenir, yeni bağlantı gider
            conn.execute('UPDATE users SET name = ?, pw_hash = ?, kdf_salt = ? WHERE id = ?', (name, hash_auth(auth), det_salt(email), u['id']))
            uid = u['id']
        else:
            uid = conn.execute('INSERT INTO users (email, name, pw_hash, kdf_salt, dl_token, created_at) VALUES (?,?,?,?,?,?)',
                               (email, name, hash_auth(auth), det_salt(email), secrets.token_urlsafe(24), db.now())).lastrowid
        if a in APPS:
            lic(conn, uid, a)
        conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), uid))
        tok = new_token(conn, uid, 'verify', settings.VERIFY_HOURS * 3600)
        conn.commit()
    mailer.send_verify(email, name, acct(f'/dogrula/{tok}' + _verify_q(b)), brand)
    return {'ok': True}


@app.post('/api/{a}/auth/resend-verify')
async def resend_verify(a: str, request: Request):
    need_prefix(a)
    rate(request, 'resend', 5)
    b = await body(request)
    email, brand = norm_email(b.get('email')), brand_of(a, b)
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status = 'BEKLIYOR'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'verify' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'verify', settings.VERIFY_HOURS * 3600)
            conn.commit()
            mailer.send_verify(email, u['name'], acct(f'/dogrula/{tok}' + _verify_q(b)), brand)
    return {'ok': True}


def _verify_q(b):
    """Doğrulama bağlantısına kaydın geldiği yer: oyun (?app=vf) ya da ürün sitesi (?app=sm) — doğrulama sonrası Hesabım'da oyuna dönüş
    ya da '<uygulama> web'de aç' düğmesi gösterilir (yalnız bilinen kodlar)."""
    g = str((b or {}).get('brand') or '')
    return f'?app={g}' if g in GAMES or g in WEB_APPS else ''


def to_portal(request):
    """Ürün sitesindeki hesap sayfası isteği → portal (yalnız MT_PORTAL_LIVE=1 iken). Dönüş RedirectResponse | None."""
    site = site_of(request)
    if not settings.PORTAL_LIVE or site == 'mt':
        return None
    q = request.url.query
    q = q + ('&' if q else '') + f'app={site}' if 'app=' not in q else q
    return RedirectResponse(f'{settings.PORTAL_URL}{request.url.path}?{q}', status_code=302)


@app.get('/dogrula/{tok}')
def verify(tok: str, request: Request):
    if (r := to_portal(request)):
        return r
    with db.connect() as conn:
        t = take_token(conn, tok, 'verify')
        if not t:
            return RedirectResponse('/giris?durum=dogrulama-gecersiz', status_code=303)
        u = conn.execute('SELECT * FROM users WHERE id = ?', (t['user_id'],)).fetchone()
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        if u['status'] == 'BEKLIYOR':
            conn.execute("UPDATE users SET status = 'AKTIF', verified_at = ? WHERE id = ?", (db.now(), u['id']))
        conn.commit()
        if u['status'] == 'ASKIDA':
            return RedirectResponse('/giris?durum=askida', status_code=303)
        s = new_session(conn, u['id'], 'web', ip=client_ip(request))
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (db.now(), u['id']))
        conn.commit()
    game = request.query_params.get('app') or ''
    resp = RedirectResponse('/hesabim?durum=dogrulandi' + (f'&app={game}' if game in GAMES or game in WEB_APPS else ''), status_code=303)
    set_cookie(resp, s)
    return resp


@app.post('/api/{a}/auth/login')
async def login(a: str, request: Request):
    need_prefix(a)
    rate(request, 'login', 10)
    b = await body(request)
    email = norm_email(b.get('email'))
    auth = need_auth_hash(b.get('auth_hash'))
    desktop = a == 'mt' and b.get('client') in MT_CLIENTS     # Master Tool masaüstü / Android / iPhone: ortak (sso) oturum
    web = (b.get('client') == 'web' or a == 'mt') and not desktop   # oyunlar (GAMES) client:'web' ile çerezli oturum açar; client yoksa Bearer
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if not u:
            check_auth(auth, _DUMMY)
            raise Err(401, 'bad_credentials', 'E-posta veya şifre hatalı')
        if not check_auth(auth, u['pw_hash']):
            raise Err(401, 'bad_credentials', 'E-posta veya şifre hatalı')
        if u['status'] == 'BEKLIYOR':
            raise Err(403, 'unverified', 'E-posta adresiniz henüz doğrulanmadı; gelen kutunuzdaki bağlantıya tıklayın')
        if u['status'] == 'ASKIDA':
            raise Err(403, 'suspended', 'Hesabınız askıya alınmış')
        if not web and not desktop:
            need_license(conn, u['id'], a)
        ip, dev, ver = client_ip(request), b.get('device'), b.get('app_version')
        sso = sso_id = None
        if desktop or (a in APPS and b.get('sso') is True):   # uygulama girişinde sso:true → cihazın ortak oturumu da açılır
            sso = new_session(conn, u['id'], 'sso', dev, ver, ip)
            sso_id = conn.execute('SELECT id FROM sessions WHERE token_hash = ?', (sha(sso),)).fetchone()[0]
        tok = None if desktop else new_session(conn, u['id'], 'web' if web else 'app', dev, ver, ip, a, parent_id=sso_id)
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (db.now(), u['id']))
        conn.commit()
        sync = bool(lic(conn, u['id'], a)['sync_enabled']) if a in APPS else True
    out = {'user': user_public(u), 'sync_enabled': sync, 'kdf': kdf(u['kdf_salt'])}
    if web:
        resp = JSONResponse(out)
        set_cookie(resp, tok)
        return resp
    if desktop:
        return {'sso_token': sso, **out}
    return {'token': tok, **out} | ({'sso_token': sso} if sso else {})


@app.post('/api/{a}/auth/sso')
async def login_sso(a: str, request: Request):
    """Ortak oturumla (Master Tool ya da başka bir uygulamada bir kez giriş yapılmış) şifresiz uygulama girişi.
    Gövde: {sso_token, device, app_version}. Yanıt /auth/login ile aynı: {token, user, sync_enabled, kdf}.
    Uygulama oturumu ortak oturuma bağlıdır: herhangi bir uygulamada çıkış yapılınca hepsi düşer."""
    need_prefix(a, apps_only=True)
    rate(request, 'sso', 60)
    b = await body(request)
    st = str(b.get('sso_token') or '')
    with db.connect() as conn:
        s = conn.execute("SELECT * FROM sessions WHERE token_hash = ? AND kind = 'sso'", (sha(st),)).fetchone()
        if not s or time.time() - s['last_seen'] > settings.TOKEN_DAYS * 86400:
            if s:
                end_session(conn, s)
                conn.commit()
            raise Err(401, 'session_expired', 'Ortak oturum geçersiz; yeniden giriş yapın')
        u = conn.execute('SELECT * FROM users WHERE id = ?', (s['user_id'],)).fetchone()
        if not u or u['status'] != 'AKTIF':
            raise Err(403, 'suspended' if u and u['status'] == 'ASKIDA' else 'unauthorized', 'Hesap kullanılamıyor')
        need_license(conn, u['id'], a)
        tok = new_session(conn, u['id'], 'app', b.get('device') or s['device'], b.get('app_version'), client_ip(request), a, parent_id=s['id'])
        conn.execute('UPDATE sessions SET last_seen = ? WHERE id = ?', (time.time(), s['id']))
        conn.commit()
        sync = bool(lic(conn, u['id'], a)['sync_enabled'])
    return {'token': tok, 'user': user_public(u), 'sync_enabled': sync, 'kdf': kdf(u['kdf_salt'])}


@app.post('/api/{a}/auth/logout')
def logout(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, s = current(request, conn, require=False)
        ended = False
        if s:
            ended = end_session(conn, s)
            conn.commit()
    resp = JSONResponse({'ok': True, 'sso_ended': ended})
    resp.delete_cookie(COOKIE, path='/')
    return resp


def library_meta(conn, uid, a='sm'):
    lib = conn.execute('SELECT version, updated_at, size, device FROM libraries WHERE user_id = ? AND app = ?', (uid, a)).fetchone()
    return dict(lib) if lib else {'version': 0, 'updated_at': None, 'size': 0, 'device': None}


@app.get('/api/{a}/me')
def me(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        out = {'user': user_public(u), 'kdf': kdf(u['kdf_salt'])}
        if a in APPS:
            out |= {'sync_enabled': bool(lic(conn, u['id'], a)['sync_enabled']), 'library': library_meta(conn, u['id'], a)}
        return out


@app.get('/api/{a}/session')
def session_state(a: str, request: Request):
    """Hafif oturum durumu (site başlığındaki Giriş / kullanıcı adı için; çerez HttpOnly olduğundan sayfa bunu sorar): oturum yoksa da 200."""
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, require=False, web_only=True)
    out = {'user': {'name': u['name'], 'email': u['email']} if u else None}
    return JSONResponse(out, headers={'Cache-Control': 'private, no-store'})


@app.post('/api/{a}/auth/forgot')
async def forgot(a: str, request: Request):
    need_prefix(a)
    rate(request, 'forgot', 5)
    b = await body(request)
    email, brand = norm_email(b.get('email')), brand_of(a, b)
    with db.connect() as conn:
        u = conn.execute("SELECT * FROM users WHERE email = ? AND status != 'ASKIDA'", (email,)).fetchone()
        if u and mailer.enabled():
            conn.execute("UPDATE tokens SET used_at = ? WHERE user_id = ? AND kind = 'reset' AND used_at IS NULL", (db.now(), u['id']))
            tok = new_token(conn, u['id'], 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
            conn.commit()
            mailer.send_reset(email, u['name'], acct(f'/sifre-sifirla/{tok}'), brand)
    return {'ok': True}   # e-posta kayıtlı olsun olmasın aynı yanıt


@app.get('/api/{a}/auth/reset/{tok}')
def reset_info(a: str, tok: str):
    need_prefix(a)
    with db.connect() as conn:
        t = take_token(conn, tok, 'reset')
        if not t:
            raise Err(404, 'invalid_token', 'Bağlantı geçersiz ya da süresi dolmuş')
        u = conn.execute('SELECT email FROM users WHERE id = ?', (t['user_id'],)).fetchone()
    return {'email': u['email'], 'kdf': kdf(t['salt'])}


def _apply_new_password(conn, uid, new_auth, new_salt, keep_session=None):
    """Şifre değişti: eski anahtarla şifreli kütüphaneler (tüm uygulamalar) okunamaz → silinir; diğer oturumlar düşer."""
    conn.execute('UPDATE users SET pw_hash = ?, kdf_salt = ? WHERE id = ?', (hash_auth(new_auth), new_salt, uid))
    conn.execute('DELETE FROM libraries WHERE user_id = ?', (uid,))
    conn.execute('DELETE FROM sessions WHERE user_id = ? AND id != ?', (uid, keep_session or 0))


@app.post('/api/{a}/auth/reset/{tok}')
async def reset_apply(a: str, tok: str, request: Request):
    need_prefix(a)
    rate(request, 'reset', 10)
    new_auth = need_auth_hash((await body(request)).get('new_auth_hash'), 'new_auth_hash')
    with db.connect() as conn:
        t = take_token(conn, tok, 'reset')
        if not t:
            raise Err(404, 'invalid_token', 'Bağlantı geçersiz ya da süresi dolmuş')
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        _apply_new_password(conn, t['user_id'], new_auth, t['salt'])
        conn.execute("UPDATE users SET status = 'AKTIF', verified_at = COALESCE(verified_at, ?) WHERE id = ? AND status = 'BEKLIYOR'",
                     (db.now(), t['user_id']))   # sıfırlama bağlantısını açabilen e-postanın sahibidir
        conn.commit()
    return {'ok': True}


@app.post('/api/{a}/auth/new-salt')
def new_salt(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn)
        salt = b64salt()
        conn.execute('INSERT INTO tokens (user_id, kind, token_hash, salt, expires) VALUES (?,?,?,?,?)',
                     (u['id'], 'newsalt', sha(salt + ':' + secrets.token_hex(8)), salt, time.time() + 900))
        conn.commit()
    return {'kdf': kdf(salt)}


@app.post('/api/{a}/auth/change-password')
async def change_password(a: str, request: Request):
    need_prefix(a)
    rate(request, 'chpw', 10)
    b = await body(request)
    old = need_auth_hash(b.get('old_auth_hash'), 'old_auth_hash')
    new = need_auth_hash(b.get('new_auth_hash'), 'new_auth_hash')
    salt = str(b.get('new_salt') or '')
    if not SALT_RE.match(salt):
        raise Err(422, 'invalid', 'new_salt geçersiz')
    with db.connect() as conn:
        u, s = current(request, conn)
        if not check_auth(old, u['pw_hash']):
            raise Err(401, 'bad_credentials', 'Mevcut şifre hatalı')
        t = conn.execute("SELECT * FROM tokens WHERE user_id = ? AND kind = 'newsalt' AND salt = ? AND used_at IS NULL AND expires > ?",
                         (u['id'], salt, time.time())).fetchone()
        if not t:
            raise Err(422, 'invalid_salt', 'Tuz geçersiz ya da süresi dolmuş; yeniden deneyin')
        conn.execute('UPDATE tokens SET used_at = ? WHERE id = ?', (db.now(), t['id']))
        _apply_new_password(conn, u['id'], new, salt, keep_session=s['id'])
        conn.commit()
    return {'ok': True}


# ---------------- kütüphane (uçtan uca şifreli blob) ----------------
@app.get('/api/{a}/library')
def library_get(a: str, request: Request):
    need_prefix(a, apps_only=True)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a)).fetchone()
    if not lib:
        return {'version': 0, 'updated_at': None, 'blob': None}
    return {'version': lib['version'], 'updated_at': lib['updated_at'], 'blob': lib['blob']}


@app.put('/api/{a}/library')
async def library_put(a: str, request: Request):
    need_prefix(a, apps_only=True)
    raw = await request.body()
    if len(raw) > settings.LIBRARY_MAX * 1.4 + 1024:
        raise Err(413, 'too_large', 'Kütüphane 5 MB sınırını aşıyor')
    try:
        b = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Err(422, 'invalid', 'İstek gövdesi geçersiz')
    blob = b.get('blob') if isinstance(b, dict) else None
    try:
        base = int(b.get('base_version'))
        dec = base64.b64decode(blob, validate=True) if isinstance(blob, str) else None
    except (TypeError, ValueError):
        dec = None
    if dec is None or len(dec) < 29:
        raise Err(422, 'invalid', 'blob ya da base_version geçersiz')
    if len(dec) > settings.LIBRARY_MAX:
        raise Err(413, 'too_large', 'Kütüphane 5 MB sınırını aşıyor')
    with db.connect() as conn:
        u, s = current(request, conn, a=a)
        lib = conn.execute('SELECT * FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a)).fetchone()
        cur = lib['version'] if lib else 0
        if base != cur:
            return JSONResponse({'code': 'conflict', 'message': 'Sunucudaki kütüphane daha yeni', 'detail': 'conflict',
                                 'version': cur, 'blob': lib['blob'] if lib else None}, status_code=409)
        ver = cur + 1
        conn.execute('INSERT INTO libraries (user_id, app, version, blob, size, device, updated_at) VALUES (?,?,?,?,?,?,?) '
                     'ON CONFLICT(user_id, app) DO UPDATE SET version = excluded.version, blob = excluded.blob, size = excluded.size, '
                     'device = excluded.device, updated_at = excluded.updated_at', (u['id'], a, ver, blob, len(dec), s['device'], db.now()))
        conn.commit()
    return {'version': ver}


@app.delete('/api/{a}/library')
def library_delete(a: str, request: Request):
    need_prefix(a, apps_only=True)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        conn.execute('DELETE FROM libraries WHERE user_id = ? AND app = ?', (u['id'], a))
        conn.commit()
    return {'ok': True}


@app.put('/api/{a}/settings')
async def settings_put(a: str, request: Request):
    need_prefix(a, apps_only=True)
    b = await body(request)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        lic(conn, u['id'], a)
        if 'sync_enabled' in b:
            conn.execute('UPDATE user_apps SET sync_enabled = ? WHERE user_id = ? AND app = ?', (1 if b['sync_enabled'] else 0, u['id'], a))
            if a == 'sm':   # v1 alanı (eski yönetim görünümü) eşit kalsın
                conn.execute('UPDATE users SET sync_enabled = ? WHERE id = ?', (1 if b['sync_enabled'] else 0, u['id']))
            conn.commit()
        return {'sync_enabled': bool(lic(conn, u['id'], a)['sync_enabled'])}


# ---------------- oyun profili (kullanıcı başına tek JSON; sunucu içeriği yorumlamaz) ----------------
def need_game(a):
    if a not in GAMES:
        raise Err(404, 'not_found', 'Bulunamadı')
    return a


def game_url(k, promo=False):
    g = GAMES[k]
    if g.get('site'):   # kendi sitesinde çalışan oyun (SIMUMAV): url = site, tanıtım = promo
        return (g.get('promo') or g['site'] + '/') if promo else g['site'] + '/'
    return f"{settings.PORTAL_URL}/oyunlar/{g['slug']}/" + ('tanitim/' if promo else '')


@app.get('/api/{a}/profile')
def profile_get(a: str, request: Request):
    need_game(a)
    with db.connect() as conn:
        u, _ = current(request, conn, a=a)
        r = conn.execute(f'SELECT profile, updated_at FROM {a}_profiles WHERE user_id = ?', (u['id'],)).fetchone()
    return {'user': {'id': u['id'], 'name': u['name']}, 'profile': json.loads(r['profile']) if r else None, 'updated_at': r['updated_at'] if r else None}


@app.put('/api/{a}/profile')
async def profile_put(a: str, request: Request):
    need_game(a)
    raw = await request.body()
    if len(raw) > PROFILE_MAX + 4096:
        raise Err(413, 'too_large', 'Profil 64 KB sınırını aşıyor')
    try:
        b = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Err(400, 'invalid', 'İstek gövdesi geçerli JSON değil')
    if not isinstance(b, dict) or not isinstance(b.get('profile'), dict):
        raise Err(400, 'invalid', 'profile bir JSON nesnesi olmalı')
    text = json.dumps(b['profile'], ensure_ascii=False, separators=(',', ':'))
    if len(text.encode()) > PROFILE_MAX:
        raise Err(413, 'too_large', 'Profil 64 KB sınırını aşıyor')
    with db.connect() as conn:
        sec = request.headers.get('x-simumav-secret')
        if a == 'sv' and sec is not None:   # SIMUMAV sunucusu (paylaşılan gizli): kullanıcı adına özet yazar (§7 hesap servisi tarafı)
            if not settings.SIMUMAV_SHARED_SECRET or not hmac.compare_digest(sec, settings.SIMUMAV_SHARED_SECRET):
                raise Err(403, 'forbidden', 'Yetkisiz')
            try:
                uid = int(b.get('user_id'))
            except (TypeError, ValueError):
                raise Err(422, 'invalid', 'user_id gerekir')
            u = conn.execute("SELECT * FROM users WHERE id = ? AND status = 'AKTIF'", (uid,)).fetchone()
            if not u:
                raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        else:
            u, _ = current(request, conn, a=a)
        conn.execute(f'INSERT INTO {a}_profiles (user_id, profile, updated_at) VALUES (?,?,?) '
                     'ON CONFLICT(user_id) DO UPDATE SET profile = excluded.profile, updated_at = excluded.updated_at', (u['id'], text, db.now()))
        conn.commit()
    return {'ok': True}


# ---------------- web hesabım (portal) ----------------
def release_public(r):
    if not r:
        return None
    return {'version': r['version'], 'notes': r['notes'], 'size': r['setup_size'], 'sha256': r['setup_sha256'],
            'portable': bool(r['portable_file']), 'portable_size': r['portable_size'], 'date': r['created_at']}


def _dl_url(u, a):
    return f"/indir/{u['dl_token']}" if a == 'sm' else f"/indir/{u['dl_token']}/{a}"


@app.get('/api/{a}/account')
def account(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, s = current(request, conn, web_only=True)
        sessions = [{'id': x['id'], 'kind': x['kind'], 'app': x['app'], 'device': x['device'], 'app_version': x['app_version'],
                     'created_at': x['created_at'], 'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen'])),
                     'current': x['id'] == s['id']}
                    for x in conn.execute('SELECT * FROM sessions WHERE user_id = ? ORDER BY last_seen DESC', (u['id'],))]
        apps = []
        for k, meta in APPS.items():
            L = lic(conn, u['id'], k)
            apps.append({'app': k, 'name': meta['name'], 'group': app_group(k), 'site': app_site(k),
                         'license': L['license'], 'sync_enabled': bool(L['sync_enabled']),
                         'library': library_meta(conn, u['id'], k), 'release': release_public(latest_release(conn, k)),
                         'download_url': _dl_url(u, k), 'web': f'/web/{WEB_APPS[k]}/' if k in WEB_APPS else None,
                         'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ? AND app = ?', (u['id'], k)).fetchone()[0]})
        launcher = {'name': LAUNCHER['name'], 'release': release_public(latest_release(conn, 'mt')), 'download_url': _dl_url(u, 'mt')}
        games = [game_entry(k) | {'has_profile': bool(conn.execute(f'SELECT 1 FROM {k}_profiles WHERE user_id = ?', (u['id'],)).fetchone())}
                 for k in GAMES]
        sm = apps[0]
        # sm alanları üst düzeyde de (v1 hesap sayfası önbellekte kalmış tarayıcılar için)
        return {'user': user_public(u), 'apps': apps, 'games': games, 'launcher': launcher, 'sessions': sessions, 'sync_enabled': sm['sync_enabled'], 'library': sm['library'],
                'release': sm['release'], 'download_url': sm['download_url'],
                'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ?', (u['id'],)).fetchone()[0]}


@app.delete('/api/{a}/sessions/{sid}')
def session_revoke(a: str, sid: int, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        s = conn.execute('SELECT * FROM sessions WHERE id = ? AND user_id = ?', (sid, u['id'])).fetchone()
        if s:
            end_session(conn, s)
            conn.commit()
    return {'ok': True}


@app.post('/api/{a}/account/rotate-link')
def rotate_link(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = current(request, conn, web_only=True)
        tok = secrets.token_urlsafe(24)
        conn.execute('UPDATE users SET dl_token = ? WHERE id = ?', (tok, u['id']))
        conn.commit()
    return {'download_url': f'/indir/{tok}'}


def _download(tok, a, request, tur):
    if (r := to_portal(request)):
        return r
    with db.connect() as conn:
        u, _ = current(request, conn, require=False, web_only=True)
        if not u:
            return RedirectResponse(f'/giris?sonra={request.url.path}', status_code=303)
        if not hmac.compare_digest(u['dl_token'], tok):
            return HTMLResponse(_page_msg(request, 'Bu indirme bağlantısı size ait değil',
                                          'İndirme bağlantıları kişiye özeldir ve yalnız sahibi oturum açmışken çalışır. '
                                          'Kendi bağlantınıza <a href="/hesabim">Hesabım</a> sayfasından ulaşabilirsiniz.'), status_code=403)
        if a in APPS and lic(conn, u['id'], a)['license'] != 'AKTIF':
            return HTMLResponse(_page_msg(request, f'{APPS[a]["name"]} hesabınızda kapalı',
                                          'Bu uygulamanın kullanımı hesabınız için kapatılmış. <a href="/hesabim#destek">Destek</a> talebi açabilirsiniz.'),
                                status_code=403)
        r = latest_release(conn, a)
        if not r:
            return HTMLResponse(_page_msg(request, 'Henüz indirilebilir sürüm yok', 'Sürüm yayımlanınca bu sayfadan indirebilirsiniz.'), status_code=404)
        port = tur == 'portable' and r['portable_file']
        name = r['portable_file'] if port else r['setup_file']
        path = rel_dir(a, r['version']) / name
        if not path.is_file():
            return HTMLResponse(_page_msg(request, 'Dosya bulunamadı', 'Lütfen daha sonra tekrar deneyin.'), status_code=404)
        conn.execute('INSERT INTO downloads (user_id, release_id, app, kind, ip, at) VALUES (?,?,?,?,?,?)',
                     (u['id'], r['id'], a, 'portable' if port else 'setup', client_ip(request), db.now()))
        conn.commit()
    return FileResponse(path, filename=name, media_type='application/octet-stream', headers={'Cache-Control': 'private, no-store'})


@app.get('/indir/{tok}')
def download(tok: str, request: Request, tur: str = 'setup'):
    return _download(tok, 'sm', request, tur)


@app.get('/indir/{tok}/{a}')
def download_app(tok: str, a: str, request: Request, tur: str = 'setup'):
    if a not in RELEASE_APPS:
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    return _download(tok, a, request, tur)


@app.get('/api/{a}/releases/latest')
def release_latest(a: str, request: Request):
    need_release_app(a)
    with db.connect() as conn:
        current(request, conn, a=a)
        r = latest_release(conn, a)
    return release_public(r) or {'version': None}


# ---------------- Master Tool masaüstü: uygulama kataloğu ve indirme (ortak oturumla) ----------------
def app_group(k):
    """Katalog grubu: araçlar 'tools'; TOOLS kaydında group verilmişse o (md kendi sitesi olmayan bir uygulama)."""
    return APPS[k].get('group') or ('tools' if k in TOOLS else 'apps')


APP_ORDER = ('sm', 'fm', 'sq', 'np', 'cv') + tuple(sorted(TOOLS, key=lambda k: app_group(k) != 'apps'))   # uygulama grubundaki araçlar (md) önce


def app_site(k):
    """Uygulamanın tanıtım adresi: kendi sitesi ya da (araçlar) mastertool.download/araclar/<slug>."""
    return settings.PORTAL_URL + tool_path(k) if k in TOOLS else settings.SITE_URLS[k] + '/'


def tool_path(k):
    return TOOLS[k].get('path') or f"/araclar/{TOOLS[k]['slug']}"


def game_entry(k):
    """Katalog / Hesabım kaydı (kind:'web'): kurulum, lisans ve sürüm yok; url tarayıcıda açılır, site tanıtım sayfası."""
    return {'app': k, 'code': k, 'name': GAMES[k]['name'], 'group': GAMES[k].get('group', 'games'), 'kind': 'web', 'url': game_url(k), 'site': game_url(k, promo=True),
            'icon_svg': f'/brand/{k}.svg', 'icon_png': f'/brand/{k}.png', 'description': GAMES[k].get('desc')}


def client_version(v):
    """'1.2.0' → (1, 2, 0); boş ya da bozuk → (0,). Ön ek 'v' ve '-beta' gibi ekler yok sayılır."""
    m = re.match(r'^v?(\d{1,4})(?:\.(\d{1,4}))?(?:\.(\d{1,4}))?', (v or '').strip())
    return tuple(int(x or 0) for x in m.groups()) if m else (0,)


@app.get('/api/mt/apps')
def mt_apps(request: Request, v: str = '', web: int = 0):
    """Master Tool'un gösterdiği uygulamalar. Kurulu mu değil mi istemcide belirlenir (Windows kaldırma kayıtları: DisplayName
    = name, InstallLocation; yoksa Program Files\\Mastertool\\<name>\\<exe>). Simge: /brand/<kod>.svg (tercih) ve .png (128 px).
    ?v=<istemci sürümü>: 1.2.0 ve üstü kind:'web' (oyun, group:'games') kayıtlarını da alır; eski istemciler kind'i tanımadığı için
    v yoksa ya da küçükse bu kayıtlar yanıtta yer almaz.
    ?web=1 (mastertool.download/uygulamalar başlatıcısı): oyunlar her zaman; her kayda 'web' (web sürümü yolu /web/<slug>/ ya da null)
    ve web (çerez) oturumunda kişiye özel 'download_url' (/indir/<dl_token>/<kod>) eklenir."""
    with db.connect() as conn:
        u, s = current(request, conn, a='mt')
        webui = web == 1
        personal = webui and s['kind'] == 'web'
        out = []
        for k in APP_ORDER:
            L = lic(conn, u['id'], k)
            out.append({'app': k, 'name': APPS[k]['name'], 'exe': f"{APPS[k]['name']}.exe", 'install_dir': f"Mastertool\\{APPS[k]['name']}",
                        'group': app_group(k), 'site': app_site(k), 'description': APPS[k].get('desc'), 'icon_png': f'/brand/{k}.png', 'icon_svg': f'/brand/{k}.svg',
                        'license': L['license'], 'release': release_public(latest_release(conn, k))}
                       | ({'web': f'/web/{WEB_APPS[k]}/' if k in WEB_APPS else None} if webui else {})
                       | ({'download_url': _dl_url(u, k)} if personal else {}))
        if webui or client_version(v) >= MT_APPS_WEB_MIN:
            out += [game_entry(k) for k in GAMES]
        launcher = {'name': LAUNCHER['name'], 'release': release_public(latest_release(conn, 'mt'))}
        if personal:
            launcher['download_url'] = _dl_url(u, 'mt')
        return {'apps': out, 'launcher': launcher}


@app.get('/api/mt/apps/{a}/download')
def mt_app_download(a: str, request: Request, kind: str = 'setup'):
    """Kurulum dosyasını ortak oturumla indirir (Master Tool'un indirme çubuğu için Content-Length ve X-Sha256 başlıkları).
    a = sm|fm|sq|np|cv ya da mt (Master Tool'un kendi güncellemesi). kind = setup|portable."""
    need_release_app(a)
    with db.connect() as conn:
        u, _ = current(request, conn, a='mt')
        if a in APPS:
            need_license(conn, u['id'], a)
        r = latest_release(conn, a)
        if not r:
            raise Err(404, 'no_release', 'Henüz yayımlanmış sürüm yok')
        port = kind == 'portable' and r['portable_file']
        name = r['portable_file'] if port else r['setup_file']
        path = rel_dir(a, r['version']) / name
        if not path.is_file():
            raise Err(404, 'no_file', 'Dosya bulunamadı')
        sha = r['setup_sha256'] if not port else ''
        conn.execute('INSERT INTO downloads (user_id, release_id, app, kind, ip, at) VALUES (?,?,?,?,?,?)',
                     (u['id'], r['id'], a, 'portable' if port else 'setup', client_ip(request), db.now()))
        conn.commit()
    return FileResponse(path, filename=name, media_type='application/octet-stream',
                        headers={'Cache-Control': 'private, no-store', 'X-Version': r['version'], **({'X-Sha256': sha} if sha else {})})


# ---------------- sürüm yükleme (CI / Merkez) ----------------
def _release_auth(request, a):
    key = request.headers.get('x-release-key') or ''
    rk = settings.RELEASE_KEYS.get(a) or ''
    if rk and hmac.compare_digest(key, rk):
        return
    central(request)


def _safe_name(n, fallback):
    n = re.sub(r'[^A-Za-z0-9 ._()-]', '_', (n or '').split('/')[-1].split('\\')[-1]).strip() or fallback
    return n[:120] if n.lower().endswith('.exe') else fallback


def _version(v):
    v = (v or '').strip().lstrip('vV')
    if not VERSION_RE.match(v):
        raise Err(422, 'invalid_version', 'Sürüm numarası geçersiz (ör. 1.2.0)')
    return v


async def _save_upload(up, path, append=False):
    size = 0
    with open(path, 'ab' if append else 'wb') as f:
        while chunk := await up.read(1024 * 1024):
            f.write(chunk); size += len(chunk)
    return size


def _finish_exe(path):
    """Dosya tamam: exe mi (MZ), boyut ve SHA-256."""
    with open(path, 'rb') as f:
        if f.read(2) != b'MZ':
            raise Err(422, 'not_exe', f'{path.name} bir Windows exe dosyası değil')
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return path.stat().st_size, h.hexdigest()


@app.post('/api/{a}/releases')
async def release_upload(a: str, request: Request, version: str = Form(...), setup: UploadFile = File(...),
                         portable: UploadFile = File(None), notes: str = Form('')):
    """Tek istekte yükleme (setup + isteğe bağlı portable). Cloudflare tek istekte 100 MB sınırı koyar: büyük dosyalar için
    parçalı uç /api/{a}/releases/{version}/{setup|portable} kullanılır."""
    need_release_app(a)
    _release_auth(request, a)
    version = _version(version)
    d = rel_dir(a, version)
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM releases WHERE app = ? AND version = ?', (a, version)).fetchone():
            raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    d.mkdir(parents=True, exist_ok=True)
    try:
        sname = _safe_name(setup.filename, RELEASE_APPS[a]['setup'].format(v=version))
        await _save_upload(setup, d / sname)
        ssize, ssha = _finish_exe(d / sname)
        pname = psize = None
        if portable is not None and portable.filename:
            pname = _safe_name(portable.filename, RELEASE_APPS[a]['portable'].format(v=version))
            await _save_upload(portable, d / pname)
            psize, _ = _finish_exe(d / pname)
    except Err:
        shutil.rmtree(d, ignore_errors=True)
        raise
    with db.connect() as conn:
        conn.execute('INSERT INTO releases (app, version, setup_file, setup_size, setup_sha256, portable_file, portable_size, notes, created_at) '
                     'VALUES (?,?,?,?,?,?,?,?,?)', (a, version, sname, ssize, ssha, pname, psize, notes.strip()[:4000] or None, db.now()))
        conn.commit()
    return {'ok': True, 'version': version, 'sha256': ssha}


@app.post('/api/{a}/releases/{version}/{kind}')
async def release_part(a: str, version: str, kind: str, request: Request, file: UploadFile = File(...), part: int = Form(0),
                       parts: int = Form(1), notes: str = Form(''), filename: str = Form('')):
    """Tek dosya, isteğe bağlı parçalı yükleme (her parça < 100 MB). part 0..parts-1 sırayla gönderilir; son parçada dosya
    doğrulanır (MZ, SHA-256). kind=setup sürümü oluşturur (notes ile); kind=portable var olan sürüme taşınabilir dosyayı ekler.
    Yanıt: ara parçada {ok, received}, son parçada {ok, version, kind, sha256, size}."""
    need_release_app(a)
    _release_auth(request, a)
    version = _version(version)
    if kind not in ('setup', 'portable'):
        raise Err(404, 'not_found', 'Bulunamadı')
    if not (1 <= parts <= 64 and 0 <= part < parts):
        raise Err(422, 'invalid', 'part / parts geçersiz')
    with db.connect() as conn:
        r = conn.execute('SELECT * FROM releases WHERE app = ? AND version = ?', (a, version)).fetchone()
    if kind == 'setup' and r:
        raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    if kind == 'portable' and not r:
        raise Err(404, 'no_release', 'Önce kurulum dosyası yüklenmeli')
    if kind == 'portable' and r['portable_file']:
        raise Err(409, 'exists', 'Bu sürümün taşınabilir dosyası zaten yüklü')
    d = rel_dir(a, version)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f'.{kind}.part'
    if part == 0:
        tmp.unlink(missing_ok=True)
    elif not tmp.exists() or int(request.headers.get('x-part-offset', tmp.stat().st_size)) != tmp.stat().st_size:
        raise Err(409, 'part_order', 'Parçalar sırayla gönderilmeli (baştan başlayın: part=0)')
    await _save_upload(file, tmp, append=part > 0)
    if tmp.stat().st_size > 2 * 1024 ** 3:
        tmp.unlink(missing_ok=True)
        raise Err(413, 'too_large', 'Dosya çok büyük')
    if part < parts - 1:
        return {'ok': True, 'received': tmp.stat().st_size}
    name = _safe_name(filename or file.filename, RELEASE_APPS[a][kind].format(v=version))
    try:
        size, sha = _finish_exe(tmp)
    except Err:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(d / name)
    with db.connect() as conn:
        if kind == 'setup':
            conn.execute('INSERT INTO releases (app, version, setup_file, setup_size, setup_sha256, notes, created_at) VALUES (?,?,?,?,?,?,?)',
                         (a, version, name, size, sha, notes.strip()[:4000] or None, db.now()))
        else:
            conn.execute('UPDATE releases SET portable_file = ?, portable_size = ? WHERE id = ?', (name, size, r['id']))
        conn.commit()
    return {'ok': True, 'version': version, 'kind': kind, 'sha256': sha, 'size': size}


# ---------------- web uygulaması paketleri (SIMUMAV: GitHub Actions → tar.gz; sunucudaki root yayın birimi `latest` dosyasını izler) ----------------
WEB_RELEASE_APPS = {'sv': 'simumav', 'mw': 'masterworld'}   # kod → paket adı öneki (simumav-<v>.tar.gz, masterworld-<v>.tar.gz)
TAR_MAX_UYE = 20000


def _tar_dogrula(path, version, paket='simumav'):
    """Paket güvenliği (docs/simumav.md §6.2): gzip imzası (`not_gzip`); tar yalnız LİSTELENİR, açılmaz; üye adı normalize edilir — mutlak yol,
    `..` bileşeni, sembolik/sert bağ, aygıt/fifo → `unsafe_archive`; üye sayısı ≤ TAR_MAX_UYE; kökte (`VERSION`, `./VERSION` ya da tek kök klasör
    altında) VERSION == version (`version_mismatch`); `requirements.txt` ve `run-<paket>.sh` (run-simumav.sh, run-masterworld.sh) yoksa `incomplete`."""
    import tarfile
    with open(path, 'rb') as f:
        if f.read(2) != b'\x1f\x8b':
            raise Err(422, 'not_gzip', 'Paket gzip değil')
    kokler, ver_icerik, dosyalar = set(), None, set()
    try:
        with tarfile.open(path, 'r:gz') as tf:
            n = 0
            while (m := tf.next()) is not None:
                n += 1
                if n > TAR_MAX_UYE:
                    raise Err(422, 'unsafe_archive', f'Pakette {TAR_MAX_UYE} üyeden fazla girdi var')
                ad = m.name.replace('\\', '/')
                parcalar = [p for p in ad.split('/') if p not in ('', '.')]
                if not parcalar and m.isdir():   # `tar -C . .` paketlerinde kök girdisi "./" — zararsız, atla
                    continue
                if ad.startswith('/') or '..' in parcalar or ad.startswith('~') or not parcalar or (len(parcalar[0]) == 2 and parcalar[0][1] == ':'):
                    raise Err(422, 'unsafe_archive', f'Pakette geçersiz yol: {ad[:80]}')
                if m.issym() or m.islnk() or m.isdev() or m.isfifo() or not (m.isfile() or m.isdir()):
                    raise Err(422, 'unsafe_archive', f'Pakette bağ/aygıt girdisi: {ad[:80]}')
                kokler.add(parcalar[0])
                if m.isfile():
                    dosyalar.add('/'.join(parcalar))
                    if parcalar[-1] == 'VERSION' and len(parcalar) <= 2:
                        fo = tf.extractfile(m)
                        ver_icerik = (fo.read(64).decode('utf-8', 'replace').strip() if fo else '')
    except tarfile.TarError as e:
        raise Err(422, 'unsafe_archive', f'Paket okunamadı: {str(e)[:120]}')
    tek_kok = next(iter(kokler)) if len(kokler) == 1 and 'VERSION' not in dosyalar else None   # tek kök klasör altında paket
    on = f'{tek_kok}/' if tek_kok else ''
    if ver_icerik is None or f'{on}VERSION' not in dosyalar:
        raise Err(422, 'version_mismatch', 'Pakette kök VERSION dosyası yok')
    if ver_icerik.lstrip('vV') != version:
        raise Err(422, 'version_mismatch', f'Paketteki VERSION ({ver_icerik[:20]}) sürümle eşleşmiyor')
    if f'{on}requirements.txt' not in dosyalar or f'{on}run-{paket}.sh' not in dosyalar:
        raise Err(422, 'incomplete', f'Pakette requirements.txt / run-{paket}.sh yok')


@app.post('/api/{a}/web-releases')
async def web_release_upload(a: str, request: Request, version: str = Form(...), package: UploadFile = File(...), sha256: str = Form(...), notes: str = Form('')):
    """SIMUMAV / MASTERWORLD web paketi (tar.gz ≤ 95 MB): X-Release-Key (SIMUMAV_RELEASE_KEY / MASTERWORLD_RELEASE_KEY) ya da Merkez anahtarı. Kayıt RELEASE_DIR/sv/<v>/simumav-<v>.tar.gz +
    web_releases satırı; `RELEASE_DIR/sv/latest` dosyasına sürüm ATOMİK yazılır (tmp + os.replace) — root yayın birimi (deploy/simumav) izler."""
    if a not in WEB_RELEASE_APPS:
        raise Err(404, 'not_found', 'Bulunamadı')
    rate(request, 'web-release', 10)
    _release_auth(request, a)
    kim = 'release-key' if request.headers.get('x-release-key') else 'central'
    version = _version(version)
    sha = (sha256 or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise Err(422, 'bad_sha256', 'sha256 geçersiz (64 hex)')
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM web_releases WHERE app = ? AND version = ?', (a, version)).fetchone():
            raise Err(409, 'exists', 'Bu sürüm zaten yüklü')
    d = settings.RELEASE_DIR / a / version
    d.mkdir(parents=True, exist_ok=True)
    name = f'{WEB_RELEASE_APPS[a]}-{version}.tar.gz'
    tmp = d / f'.{name}.part'
    try:
        size = 0
        h = hashlib.sha256()
        with open(tmp, 'wb') as f:
            while chunk := await package.read(1024 * 1024):
                size += len(chunk)
                if size > settings.WEB_RELEASE_MAX:
                    raise Err(413, 'too_large', 'Paket 95 MB sınırını aşıyor')
                h.update(chunk)
                f.write(chunk)
        if size < 64:
            raise Err(422, 'invalid', 'Paket boş')
        if h.hexdigest() != sha:
            raise Err(422, 'bad_sha256', 'sha256 dosya ile eşleşmiyor')
        _tar_dogrula(tmp, version, WEB_RELEASE_APPS[a])
        tmp.replace(d / name)
        os.chmod(d / name, 0o644)
        (d / f'{name}.sha256').write_text(f'{sha}  {name}\n')
    except Err:
        shutil.rmtree(d, ignore_errors=True)   # hata: sürüm klasörü silinir, latest değişmez
        raise
    with db.connect() as conn:
        conn.execute('INSERT INTO web_releases (app, version, file, size, sha256, notes, created_at, created_by) VALUES (?,?,?,?,?,?,?,?)',
                     (a, version, f'{a}/{version}/{name}', size, sha, notes.strip()[:4000] or None, db.now(), kim))
        conn.commit()
    latest_tmp = settings.RELEASE_DIR / a / 'latest.tmp'
    latest_tmp.write_text(version + '\n')
    os.replace(latest_tmp, settings.RELEASE_DIR / a / 'latest')   # atomik: path unit bunu izler
    return JSONResponse({'ok': True, 'app': a, 'version': version, 'sha256': sha, 'size': size, 'file': f'{a}/{version}/{name}'}, status_code=201)


@app.get('/api/{a}/web-releases/latest')
def web_release_latest(a: str):
    """Açık uç (dışarıdan yayın doğrulaması): son web paketi {version, sha256, size, created_at}; yoksa 404."""
    if a not in WEB_RELEASE_APPS:
        raise Err(404, 'not_found', 'Bulunamadı')
    with db.connect() as conn:
        r = conn.execute('SELECT version, sha256, size, created_at FROM web_releases WHERE app = ? ORDER BY id DESC LIMIT 1', (a,)).fetchone()
    if not r:
        raise Err(404, 'no_release', 'Henüz yayımlanmış paket yok')
    return dict(r)


@app.get('/api/{a}/web-releases')
def web_release_list(a: str, request: Request):
    if a not in WEB_RELEASE_APPS:
        raise Err(404, 'not_found', 'Bulunamadı')
    central(request)
    with db.connect() as conn:
        rows = conn.execute('SELECT id, app, version, file, size, sha256, notes, created_at FROM web_releases WHERE app = ? ORDER BY id DESC', (a,)).fetchall()
    latest = settings.RELEASE_DIR / a / 'latest'
    return {'releases': [dict(r) for r in rows], 'latest': latest.read_text().strip() if latest.is_file() else None}


# ---------------- destek talepleri (Merkez talep ekranına düşer) ----------------
TICKET_APPS = ({'sm': 'SSH Master', 'fm': 'FTP Masters', 'sq': 'SQL Master', 'np': 'Notepad Master', 'cv': 'Convert Master'}
               | {k: v['name'] for k, v in TOOLS.items()} | {k: v['name'] for k, v in GAMES.items()} | {'mt': 'Hesap / genel'})


def _mz(fn):
    try:
        return fn()
    except merkez.MerkezError as e:
        raise Err(e.status, 'support_error', e.message)


def _who(u):
    return {'email': u['email'], 'name': u['name']}


def _ticket_user(request, conn, a, user_id=None):
    """Talep uçlarının kimliği: web çerezi (Hesabım › Destek) YA DA `a == 'sv'` + X-Simumav-Secret: SIMUMAV sunucusu kullanıcı adına
    (user_id sorgu/gövde; `profile_put` kalıbı, docs/simumav.md §9). Dönüş (user, sunucu_mu). Sunucu yolunda IP oran sınırı uygulanmaz
    (tek iç IP; SIMUMAV kendi 5/sa/kullanıcı sınırını uygular)."""
    sec = request.headers.get('x-simumav-secret')
    if a == 'sv' and sec is not None:
        if not settings.SIMUMAV_SHARED_SECRET or not hmac.compare_digest(sec, settings.SIMUMAV_SHARED_SECRET):
            raise Err(403, 'forbidden', 'Yetkisiz')
        try:
            uid = int(user_id if user_id is not None else request.query_params.get('user_id'))
        except (TypeError, ValueError):
            raise Err(422, 'invalid', 'user_id gerekir')
        u = conn.execute("SELECT * FROM users WHERE id = ? AND status = 'AKTIF'", (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        return u, True
    u, _ = current(request, conn, web_only=True)
    return u, False


@app.get('/api/{a}/tickets')
def tickets(a: str, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = _ticket_user(request, conn, a)
    return _mz(lambda: merkez.call('GET', '/api/federation/mastertool/tickets', params={'email': u['email']}))


@app.post('/api/{a}/tickets')
async def ticket_create(a: str, request: Request):
    need_prefix(a)
    b = await body(request)
    with db.connect() as conn:
        u, srv = _ticket_user(request, conn, a, b.get('user_id'))
    if not srv:
        rate(request, 'ticket', 10, 600)
    ta = str(b.get('app') or 'mt')
    payload = _who(u) | {'app': ta if ta in TICKET_APPS else 'mt', 'subject': str(b.get('subject') or '')[:200],
                         'body': str(b.get('body') or '')[:8000], 'category': str(b.get('category') or 'teknik')[:20]}
    return _mz(lambda: merkez.call('POST', '/api/federation/mastertool/tickets', json=payload))


@app.get('/api/{a}/tickets/{tid}')
def ticket_get(a: str, tid: int, request: Request):
    need_prefix(a)
    with db.connect() as conn:
        u, _ = _ticket_user(request, conn, a)
    return _mz(lambda: merkez.call('GET', f'/api/federation/mastertool/tickets/{tid}', params={'email': u['email']}))


@app.post('/api/{a}/tickets/{tid}/messages')
async def ticket_reply(a: str, tid: int, request: Request):
    need_prefix(a)
    b = await body(request)
    with db.connect() as conn:
        u, srv = _ticket_user(request, conn, a, b.get('user_id'))
    if not srv:
        rate(request, 'ticket-msg', 30, 600)
    return _mz(lambda: merkez.call('POST', f'/api/federation/mastertool/tickets/{tid}/messages',
                                   json=_who(u) | {'body': str(b.get('body') or '')[:8000]}))


@app.post('/api/{a}/tickets/{tid}/close')
async def ticket_close(a: str, tid: int, request: Request):
    need_prefix(a)
    b = await body(request) if int(request.headers.get('content-length') or 0) > 0 else {}
    with db.connect() as conn:
        u, _ = _ticket_user(request, conn, a, b.get('user_id'))
    return _mz(lambda: merkez.call('POST', f'/api/federation/mastertool/tickets/{tid}/close', json=_who(u)))


@app.post('/api/mt/internal/ticket-reply')
async def ticket_notify(request: Request):
    """Merkez destek ekibi bir Mastertool talebine yanıt yazınca çağırır → kullanıcıya markalı e-posta."""
    central(request)
    b = await body(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE email = ?', (str(b.get('email') or '').lower(),)).fetchone()
    if not u or not mailer.enabled():
        return {'ok': True, 'sent': False}
    brand = b.get('app') if b.get('app') in SITES else 'mt'
    # SIMUMAV talebi: bağlantı oyunun "Taleplerim" ayrıntısına (simumav.com/app/#/support/<id>); Hesabım › Destek'te de görünür
    url = f"{settings.SIMUMAV_SITE}/app/#/support/{int(b.get('id') or 0)}" if b.get('app') == 'sv' else acct(f"/hesabim?talep={int(b.get('id') or 0)}#destek")
    mailer.send_ticket_reply(u['email'], u['name'], str(b.get('code') or '')[:20], str(b.get('subject') or '')[:200], url, brand)
    return {'ok': True, 'sent': True}


# ---------------- yönetim (HEPGO Merkez) ----------------
def _admin_apps(conn, uid):
    out = {}
    for k in APPS:
        L = lic(conn, uid, k)
        lib = library_meta(conn, uid, k)
        out[k] = {'license': L['license'], 'sync_enabled': bool(L['sync_enabled']), 'lib_version': lib['version'], 'lib_size': lib['size'],
                  'lib_updated': lib['updated_at'],
                  'app_sessions': conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND kind = 'app' AND COALESCE(app, 'sm') = ?",
                                               (uid, k)).fetchone()[0],
                  'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE user_id = ? AND app = ?', (uid, k)).fetchone()[0]}
    return out


def _num(v, f=float):
    try:
        return f(v or 0)
    except (TypeError, ValueError):
        return 0


def _admin_games(conn, uid):
    """Oyun kullanım özeti (Merkez › Mastertool). sv: SIMUMAV sunucusunun X-Simumav-Secret ile yazdığı özet (app/simumav/bridge.py
    _profil_ozeti: pilot, pilots, drones, flights, hours, last_flight_at, version). vf: VOLFAI'nin tarayıcıdan yazdığı profil
    (hiScore, levels{N: {parkurs{…}}}); sunucu içeriği yorumlamaz, yalnız sayım. Profil yoksa has_profile False, alanlar 0/None."""
    out = {}
    for k in GAMES:
        r = conn.execute(f'SELECT profile, updated_at FROM {k}_profiles WHERE user_id = ?', (uid,)).fetchone()
        try:
            p = json.loads(r['profile']) if r else {}
        except ValueError:
            p = {}
        p = p if isinstance(p, dict) else {}
        g = {'has_profile': bool(r), 'last_at': r['updated_at'] if r else None}
        if k == 'mw':   # MASTERWORLD: ayarlar (katman seçimi, görünüm); yalnız var mı + son güncelleme
            pass
        elif k == 'sv':
            g |= {'flights': _num(p.get('flights'), int), 'hours': round(_num(p.get('hours')), 2), 'pilots': _num(p.get('pilots'), int),
                  'drones': _num(p.get('drones'), int), 'pilot': p.get('pilot') or None, 'last_flight_at': p.get('last_flight_at') or None,
                  'last_version': p.get('version') or None}
        else:
            levels = p.get('levels') if isinstance(p.get('levels'), dict) else {}
            g |= {'hi_score': _num(p.get('hiScore') if 'hiScore' in p else p.get('hi_score'), int), 'levels': len(levels),
                  'parkurs': sum(len(v.get('parkurs') or {}) for v in levels.values() if isinstance(v, dict)), 'coins': _num(p.get('coins'), int)}
        out[k] = g
    return out


def _games_stats(conn, users):
    """Üst kartlar: oyun / web uygulaması başına kullanıcı (profili olan) sayısı; SIMUMAV için toplam uçuş/saat; web paketli olanlarda son sürüm."""
    def rel(a):
        r = conn.execute('SELECT version, created_at FROM web_releases WHERE app = ? ORDER BY id DESC LIMIT 1', (a,)).fetchone()
        return dict(r) if r else None
    sv = [u['games']['sv'] for u in users if u['games']['sv']['has_profile']]
    return {'sv': {'name': GAMES['sv']['name'], 'users': len(sv), 'flights': sum(x['flights'] for x in sv), 'hours': round(sum(x['hours'] for x in sv), 1),
                   'release': rel('sv')},
            'vf': {'name': GAMES['vf']['name'], 'users': sum(1 for u in users if u['games']['vf']['has_profile']), 'release': None},
            'mw': {'name': GAMES['mw']['name'], 'users': sum(1 for u in users if u['games']['mw']['has_profile']), 'release': rel('mw')}}


@app.get('/api/sm/admin/users')
def admin_users(request: Request):
    central(request)
    with db.connect() as conn:
        rows = conn.execute('SELECT id, email, name, status, verified_at, sync_enabled, note, created_at, last_login FROM users ORDER BY id DESC').fetchall()
        users = []
        for r in rows:
            apps = _admin_apps(conn, r['id'])
            sm = apps['sm']   # v1 alanları üst düzeyde (eski yönetim ekranı)
            users.append(dict(r) | {'apps': apps, 'games': _admin_games(conn, r['id']), 'sync_enabled': int(sm['sync_enabled']),
                                    'lib_version': sm['lib_version'] or None, 'lib_size': sm['lib_size'] or None, 'lib_updated': sm['lib_updated'],
                                    'app_sessions': sum(x['app_sessions'] for x in apps.values()),
                                    'downloads': sum(x['downloads'] for x in apps.values())})
        stats = {'users': len(rows), 'active': sum(1 for r in rows if r['status'] == 'AKTIF'),
                 'pending': sum(1 for r in rows if r['status'] == 'BEKLIYOR'), 'suspended': sum(1 for r in rows if r['status'] == 'ASKIDA'),
                 'downloads': conn.execute('SELECT COUNT(*) FROM downloads').fetchone()[0],
                 'release': release_public(latest_release(conn, 'sm')),
                 'apps': {k: {'name': m['name'], 'release': release_public(latest_release(conn, k)),
                              'downloads': conn.execute('SELECT COUNT(*) FROM downloads WHERE app = ?', (k,)).fetchone()[0],
                              'users': sum(1 for x in users if x['apps'][k]['app_sessions'] or x['apps'][k]['downloads'])}
                          for k, m in APPS.items()},
                 'games': _games_stats(conn, users)}
    return {'users': users, 'stats': stats}


@app.get('/api/sm/admin/users/{uid}')
def admin_user(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        u = conn.execute('SELECT id, email, name, status, verified_at, sync_enabled, note, created_at, last_login FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        sessions = [dict(x) | {'last_seen': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(x['last_seen']))}
                    for x in conn.execute('SELECT id, kind, app, device, app_version, ip, created_at, last_seen FROM sessions WHERE user_id = ? '
                                          'ORDER BY last_seen DESC', (uid,))]
        downloads = [dict(x) for x in conn.execute('''SELECT d.at, d.app, d.kind, d.ip, r.version FROM downloads d LEFT JOIN releases r ON r.id = d.release_id
                                                       WHERE d.user_id = ? ORDER BY d.id DESC LIMIT 50''', (uid,))]
        return {'user': dict(u), 'apps': _admin_apps(conn, uid), 'games': _admin_games(conn, uid), 'library': library_meta(conn, uid, 'sm'),
                'sessions': sessions, 'downloads': downloads}


@app.put('/api/sm/admin/users/{uid}')
async def admin_user_update(uid: int, request: Request):
    central(request)
    b = await body(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        if 'status' in b:
            st = b['status']
            if st not in ('AKTIF', 'ASKIDA'):
                raise Err(422, 'invalid', 'Durum AKTIF ya da ASKIDA olmalı')
            conn.execute('UPDATE users SET status = ?, verified_at = COALESCE(verified_at, ?) WHERE id = ?', (st, db.now() if st == 'AKTIF' else None, uid))
            if st == 'ASKIDA':
                conn.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))   # askıya alınan hemen düşer
        if isinstance(b.get('apps'), dict):   # uygulama bazında lisans: {"fm": "KAPALI", "sm": "AKTIF"}
            for k, v in b['apps'].items():
                if k not in APPS or v not in ('AKTIF', 'KAPALI'):
                    raise Err(422, 'invalid', 'Lisans AKTIF ya da KAPALI olmalı')
                lic(conn, uid, k)
                conn.execute('UPDATE user_apps SET license = ? WHERE user_id = ? AND app = ?', (v, uid, k))
                if v == 'KAPALI':
                    conn.execute("DELETE FROM sessions WHERE user_id = ? AND kind = 'app' AND COALESCE(app, 'sm') = ?", (uid, k))
        if 'name' in b:
            name = str(b['name'] or '').strip()[:80]
            if len(name) >= 2:
                conn.execute('UPDATE users SET name = ? WHERE id = ?', (name, uid))
        if 'note' in b:
            conn.execute('UPDATE users SET note = ? WHERE id = ?', (str(b['note'] or '').strip()[:1000] or None, uid))
        conn.commit()
    return {'ok': True}


@app.delete('/api/sm/admin/users/{uid}')
def admin_user_delete(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        conn.execute('DELETE FROM users WHERE id = ?', (uid,))
        conn.commit()
    return {'ok': True}


@app.post('/api/sm/admin/users/{uid}/reset-mail')
def admin_reset_mail(uid: int, request: Request):
    central(request)
    with db.connect() as conn:
        u = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not u:
            raise Err(404, 'not_found', 'Kullanıcı bulunamadı')
        if not mailer.enabled():
            raise Err(503, 'mail_disabled', 'E-posta gönderimi yapılandırılmamış')
        if u['status'] == 'BEKLIYOR':
            tok = new_token(conn, uid, 'verify', settings.VERIFY_HOURS * 3600)
            conn.commit()
            mailer.send_verify(u['email'], u['name'], acct(f'/dogrula/{tok}'))
            return {'ok': True, 'sent': 'verify'}
        tok = new_token(conn, uid, 'reset', settings.RESET_MINUTES * 60, salt=b64salt())
        conn.commit()
        mailer.send_reset(u['email'], u['name'], acct(f'/sifre-sifirla/{tok}'))
    return {'ok': True, 'sent': 'reset'}


@app.get('/api/sm/admin/releases')
def admin_releases(request: Request, app_: str = Query('', alias='app')):
    central(request)
    with db.connect() as conn:
        rows = conn.execute('''SELECT r.*, (SELECT COUNT(*) FROM downloads d WHERE d.release_id = r.id) AS downloads
                               FROM releases r WHERE (? = '' OR r.app = ?) ORDER BY r.id DESC''', (app_, app_)).fetchall()
    return [dict(r) for r in rows]


@app.delete('/api/sm/admin/releases/{rid}')
def admin_release_delete(rid: int, request: Request):
    central(request)
    with db.connect() as conn:
        r = conn.execute('SELECT * FROM releases WHERE id = ?', (rid,)).fetchone()
        if not r:
            raise Err(404, 'not_found', 'Sürüm bulunamadı')
        conn.execute('DELETE FROM releases WHERE id = ?', (rid,))
        conn.commit()
    shutil.rmtree(rel_dir(r['app'], r['version']), ignore_errors=True)
    return {'ok': True}


# ---------------- MASTERWORLD kaynak kaydı (docs/masterworld.md §3.2–§3.3) ----------------
# Yönetim Merkez › Mastertool › MASTERWORLD (X-Central-Secret). api_key YALNIZ YAZILIR: yönetici yanıtlarında has_key; değer yalnız iç uçta.
MW_SRC_OUT = ('id', 'slug', 'category', 'kind', 'name', 'data_desc', 'endpoint', 'protocol', 'auth', 'push_pull', 'scale', 'license', 'note', 'adapter',
              'key_required', 'noncommercial', 'attribution_required', 'attribution', 'attribution_url', 'rate_per_min', 'ttl_s', 'enabled',
              'default_on', 'sort', 'origin', 'created_at', 'updated_at')
MW_PT_OUT = ('id', 'source_id', 'name', 'lat', 'lon', 'media_type', 'media_url', 'enabled', 'created_at', 'updated_at')


def _jload(s):
    try:
        v = json.loads(s or '{}')
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _mw_source(r, points=0):
    has_key = bool(r['api_key'])
    return {k: r[k] for k in MW_SRC_OUT} | {'params': _jload(r['params']), 'has_key': has_key, 'live': mw_catalog.is_live(r, has_key),
                                            'key_missing': bool(r['adapter'] and r['key_required'] and not has_key), 'points': points}


def _mw_point(p):
    return {k: p[k] for k in MW_PT_OUT} | {'props': _jload(p['props'])}


def _mw_get(conn, sid):
    r = conn.execute('SELECT * FROM mw_sources WHERE id = ?', (sid,)).fetchone()
    if not r:
        raise Err(404, 'not_found', 'Kaynak bulunamadı')
    return r


def _mw_clean(fn, b, partial):
    try:
        return fn(b, partial)
    except mw_catalog.Invalid as e:
        raise Err(422, 'invalid', str(e))


@app.get('/api/sm/admin/mw/sources')
def mw_sources(request: Request):
    central(request)
    with db.connect() as conn:
        counts = dict(conn.execute('SELECT source_id, COUNT(*) FROM mw_points GROUP BY source_id').fetchall())
        rows = [_mw_source(r, counts.get(r['id'], 0)) for r in conn.execute('SELECT * FROM mw_sources ORDER BY sort, name COLLATE NOCASE')]
    return {'sources': rows, 'adapters': list(mw_catalog.ADAPTERS), 'categories': {k: list(v) for k, v in mw_catalog.CATEGORIES.items()},
            'category_labels': mw_catalog.CATEGORY_LABELS, 'kinds': list(mw_catalog.KINDS), 'media_types': list(mw_catalog.MEDIA_TYPES),
            'stats': {'total': len(rows), 'enabled': sum(1 for r in rows if r['enabled']), 'live': sum(1 for r in rows if r['live']),
                      'key_missing': sum(1 for r in rows if r['key_missing'])}}


@app.post('/api/sm/admin/mw/sources')
async def mw_source_create(request: Request):
    central(request)
    v = _mw_clean(mw_catalog.clean_source, await body(request), False)
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM mw_sources WHERE slug = ?', (v['slug'],)).fetchone():
            raise Err(409, 'exists', 'Bu slug zaten kayıtlı')
        sid = mw_catalog._insert(conn, v | {'params': json.loads(v.get('params') or '{}'), 'origin': 'manual'})
        conn.commit()
        return JSONResponse(_mw_source(_mw_get(conn, sid)), status_code=201)


@app.put('/api/sm/admin/mw/sources/{sid}')
async def mw_source_update(sid: int, request: Request):
    central(request)
    b = await body(request)
    v = _mw_clean(mw_catalog.clean_source, b, True)
    if isinstance(b, dict) and b.get('api_key') == '':
        v['api_key'] = None   # "" = anahtarı sil (None/yok = dokunma)
    with db.connect() as conn:
        _mw_get(conn, sid)
        if 'slug' in v and conn.execute('SELECT 1 FROM mw_sources WHERE slug = ? AND id != ?', (v['slug'], sid)).fetchone():
            raise Err(409, 'exists', 'Bu slug zaten kayıtlı')
        if v:
            v['updated_at'] = db.now()
            conn.execute(f"UPDATE mw_sources SET {', '.join(f'{k} = ?' for k in v)} WHERE id = ?", [*v.values(), sid])
            conn.commit()
        n = conn.execute('SELECT COUNT(*) FROM mw_points WHERE source_id = ?', (sid,)).fetchone()[0]
        return _mw_source(_mw_get(conn, sid), n)


@app.delete('/api/sm/admin/mw/sources/{sid}')
def mw_source_delete(sid: int, request: Request):
    central(request)
    with db.connect() as conn:
        r = _mw_get(conn, sid)
        conn.execute('DELETE FROM mw_sources WHERE id = ?', (sid,))   # noktalar ON DELETE CASCADE
        conn.commit()
    return {'ok': True, 'slug': r['slug']}


@app.post('/api/sm/admin/mw/import')
async def mw_import(request: Request, file: UploadFile = File(...)):
    """Excel (.xlsx ≤ 5 MB, zip imzası PK) → §3.1 idempotent içe aktarma; önce veritabanı yedeği (data/sshm-pre-mw-<ts>.db)."""
    central(request)
    data = await file.read(mw_catalog.XLSX_MAX + 1)
    if len(data) > mw_catalog.XLSX_MAX:
        raise Err(413, 'too_large', 'Dosya 5 MB sınırını aşıyor')
    if data[:2] != b'PK':
        raise Err(422, 'not_xlsx', 'Dosya .xlsx değil')
    with db.connect() as conn:
        try:
            recs, skipped = mw_catalog.parse_sources(data)
        except mw_catalog.XlsxError as e:
            raise Err(422, 'not_xlsx', str(e))
        mw_catalog.backup(conn)
        res = mw_catalog.import_records(conn, recs, skipped)
        conn.commit()
    return res | {'rows': len(recs) + len(skipped)}


@app.get('/api/sm/admin/mw/sources/{sid}/points')
def mw_points(sid: int, request: Request):
    central(request)
    with db.connect() as conn:
        _mw_get(conn, sid)
        return {'points': [_mw_point(p) for p in conn.execute('SELECT * FROM mw_points WHERE source_id = ? ORDER BY name COLLATE NOCASE, id', (sid,))]}


@app.post('/api/sm/admin/mw/sources/{sid}/points')
async def mw_point_create(sid: int, request: Request):
    central(request)
    v = _mw_clean(mw_catalog.clean_point, await body(request), False)
    with db.connect() as conn:
        if _mw_get(conn, sid)['adapter'] != 'points':
            raise Err(422, 'invalid', "Noktalar yalnız 'points' adaptörlü kaynağa eklenir")
        now = db.now()
        v = {'props': '{}', 'enabled': 1} | v | {'source_id': sid, 'created_at': now, 'updated_at': now}
        pid = conn.execute(f"INSERT INTO mw_points ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})", list(v.values())).lastrowid
        conn.execute('UPDATE mw_sources SET updated_at = ? WHERE id = ?', (now, sid))
        conn.commit()
        return JSONResponse(_mw_point(conn.execute('SELECT * FROM mw_points WHERE id = ?', (pid,)).fetchone()), status_code=201)


@app.put('/api/sm/admin/mw/points/{pid}')
async def mw_point_update(pid: int, request: Request):
    central(request)
    v = _mw_clean(mw_catalog.clean_point, await body(request), True)
    with db.connect() as conn:
        p = conn.execute('SELECT * FROM mw_points WHERE id = ?', (pid,)).fetchone()
        if not p:
            raise Err(404, 'not_found', 'Nokta bulunamadı')
        if v:
            v['updated_at'] = db.now()
            conn.execute(f"UPDATE mw_points SET {', '.join(f'{k} = ?' for k in v)} WHERE id = ?", [*v.values(), pid])
            conn.commit()
        return _mw_point(conn.execute('SELECT * FROM mw_points WHERE id = ?', (pid,)).fetchone())


@app.delete('/api/sm/admin/mw/points/{pid}')
def mw_point_delete(pid: int, request: Request):
    central(request)
    with db.connect() as conn:
        p = conn.execute('SELECT * FROM mw_points WHERE id = ?', (pid,)).fetchone()
        if not p:
            raise Err(404, 'not_found', 'Nokta bulunamadı')
        conn.execute('DELETE FROM mw_points WHERE id = ?', (pid,))
        conn.execute('UPDATE mw_sources SET updated_at = ? WHERE id = ?', (db.now(), p['source_id']))
        conn.commit()
    return {'ok': True}


MW_INTERNAL_SRC = ('id', 'slug', 'category', 'kind', 'name', 'data_desc', 'adapter', 'api_key', 'key_required', 'noncommercial', 'attribution_required',
                   'attribution', 'attribution_url', 'license', 'rate_per_min', 'ttl_s', 'enabled', 'default_on', 'sort', 'scale')


@app.get('/api/mw/internal/sources')
def mw_internal_sources(request: Request):
    """masterworld sunucusu → hesap servisi (§3.3): X-Masterworld-Secret; yalnız enabled=1 kaynaklar (katalog satırları dahil) ve etkin noktaları.
    api_key YALNIZ burada döner."""
    sec = request.headers.get('x-masterworld-secret') or ''
    if not settings.MASTERWORLD_SHARED_SECRET or not hmac.compare_digest(sec.encode(), settings.MASTERWORLD_SHARED_SECRET.encode()):
        raise Err(403, 'forbidden', 'Yetkisiz')
    with db.connect() as conn:
        rows = conn.execute('SELECT * FROM mw_sources WHERE enabled = 1 ORDER BY sort, name COLLATE NOCASE').fetchall()
        ids = [r['id'] for r in rows]
        points = {}
        if ids:
            for p in conn.execute(f"SELECT * FROM mw_points WHERE enabled = 1 AND source_id IN ({', '.join('?' * len(ids))}) ORDER BY id", ids):
                points.setdefault(str(p['source_id']), []).append({k: p[k] for k in ('id', 'name', 'lat', 'lon', 'media_type', 'media_url')}
                                                                  | {'props': _jload(p['props'])})
        version = max([r['updated_at'] for r in rows] + [x[0] for x in conn.execute('SELECT MAX(updated_at) FROM mw_points') if x[0]] or [None])
    return JSONResponse({'version': version, 'sources': [{k: r[k] for k in MW_INTERNAL_SRC} | {'params': _jload(r['params'])} for r in rows],
                         'points': points}, headers={'Cache-Control': 'no-store'})

# ---------------- sayfalar (Host'a göre site) ----------------
APP_ALIASES = {'sshmaster': 'sm', 'sshmasters': 'sm', 'ftpmasters': 'fm', 'ftpmaster': 'fm', 'sqlmaster': 'sq', 'notepadmaster': 'np',
               'convertmaster': 'cv'}   # uygulamalar ?app=<uzun ad> gönderebilir
SITE_NAMES = {'sm': 'SSH Master', 'fm': 'FTP Masters', 'sq': 'SQL Master', 'np': 'Notepad Master', 'cv': 'Convert Master', 'mt': 'Mastertool'}


def _page_msg(request, title, html):
    site = site_of(request)
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} — {SITE_NAMES[site]}</title><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/site.css"></head>'
            f'<body class="acc"><main class="acc-box"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="30" height="30">{SITE_NAMES[site]}</a>'
            f'<h1>{title}</h1><p class="muted">{html}</p></main></body></html>')


def _static(path, media=None):
    return FileResponse(path, media_type=media, headers={'Cache-Control': 'no-cache'})


@app.get('/')
def page_index(request: Request, lang: str = ''):
    site = site_of(request)
    page = (settings.STATIC_DIR / site / 'index.html').read_text(encoding='utf-8')
    with db.connect() as conn:
        rel = release_public(latest_release(conn, site)) if site in RELEASE_APPS else None
    return HTMLResponse(seo.render_index(site, page, lang, rel), headers={'Cache-Control': 'no-cache', 'Vary': 'Host'})


@app.get('/gizlilik')
@app.get('/privacy')
def page_privacy(request: Request):
    """Gizlilik ve çerezler (her ürün sitesinde; site adı ve veri sorumlusu doldurulur, metin kit.js ile 8 dile çevrilir)."""
    site = site_of(request)
    page = (settings.STATIC_DIR / 'legal' / 'gizlilik.html').read_text(encoding='utf-8')
    for k, v in {'SITE': SITE_NAMES.get(site, 'Mastertool'), 'PROVIDER': settings.LEGAL_PROVIDER, 'DATE': settings.LEGAL_DATE,
                 'PORTAL': settings.PORTAL_URL, 'HOME': seo.base(site) + '/'}.items():
        page = page.replace('{{' + k + '}}', _hesc(v))
    ga = settings.GA_IDS.get(site)   # "Çerez tercihleri" düğmesi çalışsın diye bu sayfada da ölçüm kimliği (yine yalnız izinle)
    page = page.replace('{{GAMETA}}', f'<meta name="mt-ga" content="{_hesc(ga)}"><meta name="mt-privacy" content="/gizlilik">' if ga else '')
    return HTMLResponse(page, headers={'Cache-Control': 'public, max-age=3600', 'Vary': 'Host'})


@app.get('/robots.txt')
def page_robots(request: Request):
    return Response(seo.robots(site_of(request)), media_type='text/plain', headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/sitemap.xml')
def page_sitemap(request: Request):
    return Response(seo.sitemap(site_of(request)), media_type='application/xml', headers={'Cache-Control': 'public, max-age=3600'})


SHOT_RE = re.compile(r'^[0-9a-z._-]+\.webp$')


@app.get('/shots/{name}')
def page_shot(name: str, request: Request):
    """Uygulama ekran görüntüleri (tools/shots.py üretir): static/<site>/shots/<ad>.webp."""
    p = settings.STATIC_DIR / site_of(request) / 'shots' / name
    if not SHOT_RE.match(name) or not p.is_file():
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    return FileResponse(p, media_type='image/webp', headers={'Cache-Control': 'public, max-age=604800'})


@app.get('/og.png')
def page_og(request: Request):
    """Sosyal paylaşım görseli (1200×630): static/<site>/og.png."""
    p = settings.STATIC_DIR / site_of(request) / 'og.png'
    if not p.is_file():
        p = settings.STATIC_DIR / site_of(request) / 'logo.png'
    return FileResponse(p, media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})


SITE_AUTH_PAGES = ('/giris', '/kayit', '/sifremi-unuttum')   # ürün sitelerinde YERİNDE çalışır (portal yönlendirmesi yok)


def _account_page(request):
    """Hesap sayfaları (hesap.html + hesap.js). Giriş / kayıt / şifremi unuttum her sitede yerinde açılır (aynı Mastertool hesabı); Hesabım,
    şifre sıfırlama ve doğrulama MT_PORTAL_LIVE=1 iken portalda. Giriş sonrası dönüş: ?next= (safe_next), yoksa ürün sitesinde /web/<slug>/.
    Oturum varken /giris kendiliğinden yönlenmez (mtweb ile yönlendirme döngüsü olmasın)."""
    path = request.url.path.rstrip('/') or '/'
    if path not in SITE_AUTH_PAGES and (r := to_portal(request)):
        return r
    site = site_of(request)
    qa = APP_ALIASES.get((request.query_params.get('app') or '').lower(), request.query_params.get('app'))
    brand = qa if site == 'mt' and (qa in SITES or qa in GAMES) else site   # ?app=vf: oyundan gelen kayıt / giriş, dönüş oyuna
    nxt = safe_next(request.query_params.get('next'))
    if not nxt and site in WEB_APPS:
        nxt = f'/web/{WEB_APPS[site]}/'
    web = ''
    if brand in WEB_APPS:   # Hesabım'da "<uygulama> web'de aç" (kendi sitesinde; yalnız bilinen SITE_URLS)
        web = f'/web/{WEB_APPS[brand]}/' if brand == site else f'{settings.SITE_URLS[brand]}/web/{WEB_APPS[brand]}/'
    html = (settings.STATIC_DIR / 'hesap.html').read_text(encoding='utf-8')
    for k, v in {'SITE': site, 'BRAND': brand, 'NAME': SITE_NAMES[site], 'NEXT': nxt, 'WEB': web, 'PORTAL': settings.PORTAL_URL}.items():
        html = html.replace('{{' + k + '}}', _hesc(v))
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache', 'Content-Security-Policy': ACCOUNT_CSP})


@app.get('/kayit')
@app.get('/giris')
@app.get('/sifremi-unuttum')
@app.get('/hesabim')
def page_account(request: Request):
    return _account_page(request)


@app.get('/sifre-sifirla/{tok}')
def page_reset(tok: str, request: Request):
    return _account_page(request)


@app.get('/uygulamalar')
def page_launcher(request: Request):
    """Master Tool web başlatıcısı (yalnız mastertool.download): masaüstü Master Tool ana ekranının web karşılığı. Katalog /api/mt/apps?web=1;
    web sürümü olanlar aynı sayfada sekmede (iframe /web/<slug>/, aynı köken) açılır; oturum yoksa sayfa içinde giriş / kayıt."""
    if site_of(request) != 'mt':
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    html = (settings.STATIC_DIR / 'uygulamalar.html').read_text(encoding='utf-8').replace('{{PORTAL}}', _hesc(settings.PORTAL_URL))
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache', 'Content-Security-Policy': LAUNCHER_CSP})


@app.get('/web')
@app.get('/web/{path:path}')
def page_web_fallback(request: Request, path: str = ''):
    """YEDEK: üretimde /web/* tünelde mtweb servisine gider ve buraya hiç gelmez. Yerel çalıştırma / mtweb yokken: mastertool.download/web/ →
    /uygulamalar; oturum yoksa giriş akışı (/giris?next=/web/<slug>/); oturum varsa 'web sürümü şu an kullanılamıyor' sayfası."""
    site = site_of(request)
    slug = path.split('/')[0]
    if not slug:
        if site == 'mt':
            return RedirectResponse('/uygulamalar', status_code=302)
        slug = WEB_APPS.get(site, '')
    if slug not in WEB_APPS.values():
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    with db.connect() as conn:
        u, _ = current(request, conn, require=False, web_only=True)
    if not u:
        return RedirectResponse(f'/giris?next=/web/{slug}/', status_code=302)
    name = next(SITE_NAMES[k] for k, v in WEB_APPS.items() if v == slug)
    return HTMLResponse(_page_msg(request, f'{name} web sürümü şu an kullanılamıyor',
                                  'Lütfen biraz sonra yeniden deneyin ya da masaüstü sürümünü Hesabım sayfanızdan indirin.'), status_code=503)


BRAND_FILES = {'sm.png': ('sm', 'logo.png', 'image/png'), 'fm.png': ('fm', 'logo.png', 'image/png'), 'mt.png': ('mt', 'logo.png', 'image/png'),
               'sq.png': ('sq', 'logo.png', 'image/png'), 'sq.svg': ('sq', 'favicon.svg', 'image/svg+xml'),
               'np.png': ('np', 'logo.png', 'image/png'), 'np.svg': ('np', 'favicon.svg', 'image/svg+xml'),
               'cv.png': ('cv', 'logo.png', 'image/png'), 'cv.svg': ('cv', 'favicon.svg', 'image/svg+xml'),
               'sm.svg': ('sm', 'favicon.svg', 'image/svg+xml'), 'fm.svg': ('fm', 'favicon.svg', 'image/svg+xml'),
               'mt.svg': ('mt', 'favicon.svg', 'image/svg+xml'), 'hepgo.png': ('mt', 'hepgo.png', 'image/png')}
for _k in TOOLS:   # araç simgeleri: /brand/<kod>.png (128), /brand/<kod>-512.png, /brand/<kod>.svg
    BRAND_FILES |= {f'{_k}.png': ('mt', f'araclar/{_k}.png', 'image/png'), f'{_k}-512.png': ('mt', f'araclar/{_k}-512.png', 'image/png'),
                    f'{_k}.svg': ('mt', f'araclar/{_k}.svg', 'image/svg+xml')}
for _k, _g in GAMES.items():   # oyun simgeleri: static/mt/img/<icon>.svg|.png|-512.png
    BRAND_FILES |= {f'{_k}.png': ('mt', f"img/{_g['icon']}.png", 'image/png'), f'{_k}-512.png': ('mt', f"img/{_g['icon']}-512.png", 'image/png'),
                    f'{_k}.svg': ('mt', f"img/{_g['icon']}.svg", 'image/svg+xml')}


@app.get('/oyunlar/{slug}')
def page_game_root(slug: str, request: Request):
    """/oyunlar/<slug> → /oyunlar/<slug>/ (oyunun göreli yolları dizin kökü ister)."""
    k = next((k for k, v in GAMES.items() if v['slug'] == slug), None)
    if site_of(request) != 'mt' or not k:
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    if GAMES[k].get('site'):   # kendi sitesinde çalışan oyun (SIMUMAV): portal yolu siteye gider
        return RedirectResponse(game_url(k), status_code=307)
    return RedirectResponse(f'/oyunlar/{slug}/', status_code=308)


@app.get('/oyunlar/{slug}/{path:path}')
def page_game(slug: str, path: str, request: Request, lang: str = ''):
    """Web oyunu (yalnız mastertool.download): static/mt/oyunlar/<slug>/ dizini olduğu gibi sunulur (dağıtımda kopyalanır; depoda yok).
    '' → index.html; 'tanitim/' → tanıtım sayfası (depodan, SEO + site kiti); diğerleri dosya (sw.js / manifest doğru MIME, önbellek yok)."""
    k = next((k for k, v in GAMES.items() if v['slug'] == slug), None)
    nf = HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    if site_of(request) != 'mt' or not k:
        return nf
    if GAMES[k].get('site'):   # kendi sitesinde çalışan oyun (SIMUMAV): /oyunlar/<slug>/ → site, /oyunlar/<slug>/tanitim/ → tanıtım (307)
        return RedirectResponse(game_url(k, promo=path.startswith('tanitim')), status_code=307)
    root = settings.STATIC_DIR / 'mt' / 'oyunlar' / slug
    if path == 'tanitim':
        return RedirectResponse(f'/oyunlar/{slug}/tanitim/', status_code=308)
    if path == 'tanitim/':
        p = root / 'tanitim' / 'index.html'
        if not p.is_file():
            return nf
        return HTMLResponse(seo.render_game(k, GAMES[k], p.read_text(encoding='utf-8'), lang),
                            headers={'Cache-Control': 'no-cache', 'Vary': 'Host', 'Content-Security-Policy': PROMO_CSP})
    parts = path.split('/') if path else ['index.html']
    if parts[-1] == '':
        return nf   # alt dizin listesi yok
    if not all(GAME_FILE_RE.match(x) for x in parts):
        return nf
    p = root.joinpath(*parts)
    if not p.is_file():
        if path == '':
            return HTMLResponse(_page_msg(request, f"{GAMES[k]['name']} henüz yayında değil",
                                          f'Tanıtım: <a href="/oyunlar/{slug}/tanitim/">/oyunlar/{slug}/tanitim/</a>.'), status_code=404)
        return nf
    media = GAME_MIME.get(p.suffix.lower(), 'application/octet-stream')
    hdr = {'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff'}   # sw.js / sürüm değişimi hemen görülsün (ETag ile doğrulanır)
    if media.startswith('text/html'):
        hdr['Content-Security-Policy'] = GAME_CSP
    return FileResponse(p, media_type=media, headers=hdr)


@app.get('/master-download')
def page_md(request: Request, lang: str = ''):
    """Master Download tanıtım sayfası: kökte (TOOLS['md']['path']); içerik araç sayfasıyla aynı yoldan."""
    return page_tool('master-download', request, lang, _path=True)


@app.get('/araclar/{slug}')
def page_tool(slug: str, request: Request, lang: str = '', _path: bool = False):
    """Araç tanıtım sayfası (yalnız mastertool.download): static/mt/araclar/<slug>.html — SEO etiketleri ana sayfalar gibi.
    Kendi yolu olan kayıtlar (path) /araclar/<slug> adresinden kalıcı olarak oraya yönlenir."""
    k = next((k for k, v in TOOLS.items() if v['slug'] == slug), None)
    p = settings.STATIC_DIR / 'mt' / 'araclar' / f'{slug}.html'
    if k and TOOLS[k].get('path') and not _path and site_of(request) == 'mt':
        return RedirectResponse(TOOLS[k]['path'] + (f'?lang={lang}' if lang in seo.LANGS else ''), status_code=301)
    if site_of(request) != 'mt' or not k or not p.is_file():
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    with db.connect() as conn:
        rel = release_public(latest_release(conn, k))
    return HTMLResponse(seo.render_tool(k, TOOLS[k], p.read_text(encoding='utf-8'), lang, rel),
                        headers={'Cache-Control': 'no-cache', 'Vary': 'Host'})


@app.get('/brand/{name}')
def page_brand(name: str, request: Request):
    """Marka görselleri (e-posta logoları, portal ürün kartları) — her sitede aynı adreste."""
    if name not in BRAND_FILES:
        return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
    d, f, media = BRAND_FILES[name]
    return FileResponse(settings.STATIC_DIR / d / f, media_type=media, headers={'Cache-Control': 'public, max-age=86400'})


I18N_RE = re.compile(r'^(sm|fm|sq|np|cv|mt|hesap|legal)\.(en|fr|de|es|ar|zh|ru)\.json$')


@app.get('/i18n/{name}')
def page_i18n(name: str, request: Request):
    """Site çeviri sözlükleri (kit.js); Türkçe kaynak sayfanın kendisidir."""
    path = settings.STATIC_DIR / 'i18n' / name
    if not I18N_RE.match(name) or not path.is_file():
        return JSONResponse({}, status_code=404)
    return FileResponse(path, media_type='application/json', headers={'Cache-Control': 'no-cache'})


@app.get('/{name}')
def page_asset(name: str, request: Request):
    shared = {'site.css': 'text/css', 'hesap.js': 'text/javascript', 'kit.js': 'text/javascript', 'kit.css': 'text/css',
              'mtsite.js': 'text/javascript', 'mtsite.css': 'text/css', 'uygulamalar.js': 'text/javascript', 'uygulamalar.css': 'text/css'}
    per_site = {'favicon.svg': 'image/svg+xml', 'logo.png': 'image/png'}
    if name in shared and (settings.STATIC_DIR / name).is_file():
        return _static(settings.STATIC_DIR / name, shared[name])
    if name in per_site:
        return _static(settings.STATIC_DIR / site_of(request) / name, per_site[name])
    return HTMLResponse(_page_msg(request, 'Sayfa bulunamadı', '<a href="/">Ana sayfaya dönün</a>.'), status_code=404)
