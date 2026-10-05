"""Entegrasyon profilleri — her fabrika entegrasyonu için tek kaynak tanım.

Her entegrasyon AYRI indirilir, AYRI anahtarla çalışır ve yalnız kendi op'larına hizmet eder.
Buradaki tanımlar hem kurulum betikleri (tools/build-agent-*), hem ortak çerçeve (agent.agent /
agent.service), hem de yerel yapılandırma arayüzü (agent.localconfig) tarafından kullanılır.

Her profil:
  name        : Türkçe görünen ad
  op_prefixes : merkezin bu slot'a yönlendireceği op önekleri (ör. 'mikro.query' → 'mikro')
  pip         : TABAN bağımlılıkların ÜSTÜNE gereken ek pip paketleri (hafif tutulur; ağır yalnız 'face')
  fields      : yerel arayüzde gösterilecek cihaz alanları (Domain + API Anahtarı HER profilde ayrıca var)
  hw_note     : (ops.) asgari donanım / önemli not — arayüzde belirgin gösterilir

TABAN bağımlılıklar (hepsinde): websockets, httpx.
  Çünkü ajan açılışta yalnız `from app import agent_ops, config, sysstat` yapar; bunların tümü
  üst düzeyde yalnız stdlib + config kullanır (config: os/pathlib; sysstat: ctypes/shutil/threading;
  agent_ops: config/time). Ağır modüller (mikro/pdks/nvr/facecore) op çağrılınca TEMBEL yüklenir,
  yani ilgili entegrasyon dışındaki ağır paketler hiç import edilmez.

Not (bağımlılık zinciri, kaynaktan tespit):
  - mikro  → app.mikro (pymssql tembel). app.db'ye DOKUNMAZ → fastapi gerekmez.
  - pdks   → app.pdks (firebird-driver tembel). app.db'ye DOKUNMAZ → fastapi gerekmez.
  - printer→ app.printer_driver/printer_send → üst düzeyde `from . import config, db`;
             app.db üst düzeyde `from fastapi import ...` yapar → fastapi gerekir.
  - camera → app.nvr → üst düzeyde `from . import config, db, devices` → fastapi;
             anlık görüntü (nvr.snapshot) için cv2 (opencv-python-headless) gerekir.
  - face   → app.facecore → üst düzeyde `import numpy`, `from . import config, db` → numpy + fastapi;
             kare yakalama (nvr/document_media) için opencv + onnxruntime gömülü model çıkarımı.
"""

BASE_PIP = ['websockets>=13', 'httpx>=0.27']

# fastapi, app.db'nin (printer/camera/face zincirinde) üst düzey `from fastapi import ...` satırı için.
_FASTAPI = 'fastapi>=0.115'

_DOMAIN_FIELDS = [
    {'env': 'CAYMAZ_AGENT_CENTRAL_URL_DOMAIN', 'label': 'Merkez Alan Adı (Domain)',
     'type': 'text', 'default': '', 'placeholder': 'ornek.app',
     'help': 'Yalnız alan adı; wss://<alan>/ws/agent olarak bağlanılır.'},
    {'env': 'CAYMAZ_AGENT_KEY', 'label': 'API Anahtarı',
     'type': 'password', 'default': '', 'placeholder': 'merkezden verilen entegrasyon anahtarı',
     'help': 'Bu entegrasyona özel anahtar (her entegrasyonun kendi anahtarı vardır).'},
]


INTEGRATIONS = {
    'mikro': {
        'name': 'Mikro ERP',
        'op_prefixes': ['mikro'],
        'pip': ['pymssql>=2.2'],
        'hw_note': '',
        'fields': [
            {'env': 'CAYMAZ_MIKRO_HOST', 'label': 'Mikro Sunucu (MSSQL) IP/Ad',
             'type': 'text', 'default': '192.168.1.100', 'placeholder': '192.168.1.100'},
            {'env': 'CAYMAZ_MIKRO_PORT', 'label': 'Port', 'type': 'number', 'default': '1433'},
            {'env': 'CAYMAZ_MIKRO_DB', 'label': 'Veritabanı Adı',
             'type': 'text', 'default': '', 'placeholder': 'MikroDB_V16_FIRMA'},
            {'env': 'CAYMAZ_MIKRO_USER', 'label': 'Kullanıcı', 'type': 'text', 'default': ''},
            {'env': 'CAYMAZ_MIKRO_PASSWORD', 'label': 'Parola', 'type': 'password', 'default': ''},
        ],
    },
    'pdks': {
        'name': 'PDKS (Personel Devam Kontrol)',
        'op_prefixes': ['pdks'],
        'pip': ['firebird-driver>=1.10'],
        'hw_note': 'Firebird istemci kütüphanesi (fbclient) makinede kurulu olmalıdır.',
        'fields': [
            {'env': 'CAYMAZ_PDKS_HOST', 'label': 'Firebird Sunucu IP/Ad',
             'type': 'text', 'default': '192.168.1.100', 'placeholder': '192.168.1.100'},
            {'env': 'CAYMAZ_PDKS_PORT', 'label': 'Port', 'type': 'number', 'default': '3050'},
            {'env': 'CAYMAZ_PDKS_DB', 'label': 'Veritabanı Yolu (.GDB)',
             'type': 'text', 'default': '', 'placeholder': r'\\192.168.1.100\MPremium\PDKS.GDB'},
            {'env': 'CAYMAZ_PDKS_USER', 'label': 'Kullanıcı', 'type': 'text', 'default': 'SYSDBA'},
            {'env': 'CAYMAZ_PDKS_PASSWORD', 'label': 'Parola', 'type': 'password', 'default': ''},
        ],
    },
    'printer': {
        'name': '3B Yazıcılar (Moonraker)',
        'op_prefixes': ['printer'],
        'pip': [_FASTAPI],
        'hw_note': 'Yazıcılar fabrika yerel ağında (LAN) otomatik keşfedilir — makine yazıcılarla '
                   'aynı /24 alt ağda olmalıdır. Ayrı adres girmeye gerek yoktur.',
        'fields': [
            {'env': '_PRINTER_NOTE', 'label': 'Keşif', 'type': 'note', 'default': '',
             'help': 'Yazıcılar otomatik bulunur (Moonraker, 7125 portu). Ek alan gerekmez; '
                     'yalnız Domain + API Anahtarı yeterlidir.'},
        ],
    },
    'camera': {
        'name': 'Kamera / NVR',
        'op_prefixes': ['nvr'],
        'pip': [_FASTAPI, 'opencv-python-headless>=4.8'],
        'hw_note': 'Kameralar NVR (ağ kayıt cihazı) arkasında; ONVIF + RTSP ile erişilir.',
        'fields': [
            {'env': 'CAYMAZ_NVR_HOST', 'label': 'NVR IP/Ad',
             'type': 'text', 'default': '', 'placeholder': '192.168.1.64'},
            {'env': 'CAYMAZ_NVR_PORT', 'label': 'Port (ONVIF/HTTP)', 'type': 'number', 'default': '80'},
            {'env': 'CAYMAZ_NVR_USER', 'label': 'Kullanıcı', 'type': 'text', 'default': 'admin'},
            {'env': 'CAYMAZ_NVR_PASSWORD', 'label': 'Parola', 'type': 'password', 'default': ''},
        ],
    },
    'face': {
        'name': 'Yüz Tanıma',
        'op_prefixes': ['face'],
        'pip': [_FASTAPI, 'opencv-python-headless>=4.8', 'onnxruntime', 'numpy>=1.26'],
        'hw_note': 'ASGARİ DONANIM: yüz tanıma çıkarımı CPU-yoğundur. En az 4 çekirdek CPU + 8 GB RAM '
                   'önerilir; çok kanallı/kesintisiz kullanımda CUDA destekli NVIDIA GPU (ör. GX10) '
                   'şiddetle tavsiye edilir. OpenCV + onnxruntime paketleri kurulumla birlikte gelir.',
        'fields': [
            {'env': 'CAYMAZ_NVR_HOST', 'label': 'Kamera Kaynağı — NVR IP/Ad',
             'type': 'text', 'default': '', 'placeholder': '192.168.1.64'},
            {'env': 'CAYMAZ_NVR_PORT', 'label': 'Port', 'type': 'number', 'default': '80'},
            {'env': 'CAYMAZ_NVR_USER', 'label': 'Kullanıcı', 'type': 'text', 'default': 'admin'},
            {'env': 'CAYMAZ_NVR_PASSWORD', 'label': 'Parola', 'type': 'password', 'default': ''},
            {'env': 'CAYMAZ_FACE_MODEL', 'label': 'Model', 'type': 'text', 'default': 'buffalo_l',
             'help': 'Çıkarım modeli (ONNX). Varsayılan bırakılabilir.'},
        ],
    },
}

# ping ve sysstat her entegrasyonda geçerlidir (durum/teşhis).
UNIVERSAL_OPS = {'ping', 'sysstat'}


def names():
    """Geçerli entegrasyon adları."""
    return list(INTEGRATIONS.keys())


def get(integ):
    """Profili döndürür; bilinmeyen ad için KeyError."""
    return INTEGRATIONS[integ]


def pip_requirements(integ):
    """Bu entegrasyon için TAM pip listesi (taban + ek)."""
    return list(BASE_PIP) + list(INTEGRATIONS[integ]['pip'])


def device_fields(integ):
    """Arayüzde gösterilecek cihaz alanları (note tipleri dahil)."""
    return list(INTEGRATIONS[integ]['fields'])


def all_fields(integ):
    """Domain + API Anahtarı + cihaz alanları (sırayla)."""
    return list(_DOMAIN_FIELDS) + device_fields(integ)


def serves_op(integ, op):
    """Merkez bu op'u bu entegrasyona yönlendirir mi? (yerel doğrulama için; universal her zaman)."""
    if op in UNIVERSAL_OPS:
        return True
    prefix = op.split('.', 1)[0]
    return prefix in INTEGRATIONS[integ]['op_prefixes']
