"""Ajan-tabanlı entegrasyonların anahtar + lisans deposu (Aşama 1).

Her ajan-tabanlı entegrasyon (Mikro ERP, PDKS, Yazıcılar, Kameralar/NVR, Yüz Tanıma) AYRI bir üründür:
kendi API anahtarı, kendi lisansı (satış / etkinleştirme bayrağı) ve kendi indirilebilir kurulum dosyası vardır.

Depo app_kv['agent_integrations'] içinde JSON olarak tutulur:
    {"domain": "caymaz.app",
     "items": {"mikro": {"key": "<şifreli-gizli>", "enabled": true, "created_at": "..."}, ...}}

Anahtarlar, ilgili entegrasyon ajanının merkeze bağlanırken kullanacağı KİMLİK SIRRIDIR (Aşama 2 doğrular).
Anahtar değeri şifreli saklanır (cameras.encrypt) ve API ile asla düz dönmez; yalnız "üretilince bir kez" gösterilir.

GERİYE DÖNÜK UYUMLULUK: eski tekil config.AGENT_KEY (.env) agent_hub tarafından kabul edilmeye DEVAM eder.
Bu depo tamamen EK'tir; agent_hub'ın kimlik/op yönlendirmesine dokunmaz (çok-anahtarlı yönlendirme Aşama 2).
"""
import hmac
import json
import re
import secrets

from . import cameras, db

KV_KEY = 'agent_integrations'

# Ajan-tabanlı entegrasyonlar (her biri ayrı ürün: anahtar + lisans + indirme).
# min_req: yalnız ağır kurulumlar için yayımlanan en-az-gereksinim metni (örn. Yüz Tanıma).
INTEGRATIONS = {
    'mikro':   {'title': 'Mikro ERP'},
    'pdks':    {'title': 'PDKS (Personel Giriş-Çıkış)'},
    'printer': {'title': 'Yazıcılar'},
    'camera':  {'title': 'Kameralar / NVR'},
    'face': {
        'title': 'Yüz Tanıma',
        'min_req': 'En az gereksinimler: NVIDIA ekran kartı (önerilir) · en az 8 çekirdekli işlemci (CPU) · '
                   '16 GB RAM · ~5 GB boş disk. Yüz tanıma yoğun kaynak kullanan bir üründür; ekran kartı '
                   'olmayan makinelerde çalışır ancak başarım düşer. Fabrika makinesi bu değerleri karşılamalıdır.',
    },
    'speech': {
        'title': 'Konuşma Tanıma',
        'min_req': 'En az gereksinimler: en az 4 çekirdekli işlemci (CPU) · 8 GB RAM · ~3 GB boş disk (model). '
                   'Sürekli/çok kanallı kullanımda CUDA destekli NVIDIA GPU (ör. GX10) önerilir.',
    },
}


def _strip_scheme(domain):
    """'https://caymaz.app/' → 'caymaz.app' (şema, yol ve baştaki/sondaki boşluklar ayıklanır)."""
    d = (domain or '').strip()
    d = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', '', d)   # şema (https:// vb.)
    d = d.split('/', 1)[0].strip().strip('/')
    return d


def central_url(domain):
    """Ajanın bağlanacağı merkez WebSocket adresi: wss://<domain>/ws/agent (domain boşsa '')."""
    d = _strip_scheme(domain)
    return f'wss://{d}/ws/agent' if d else ''


def _load(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    try:
        data = json.loads(row[0]) if row else {}
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault('domain', '')
    if not isinstance(data.get('items'), dict):
        data['items'] = {}
    return data


def _save(conn, data):
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(data)))


def get_all(conn):
    """Panel için durum: domain + merkez adresi + her entegrasyonun lisans/anahtar durumu.
    Anahtarın KENDİSİ asla dönmez; yalnız 'tanımlı mı' (key_set) bilgisi döner."""
    data = _load(conn)
    items = []
    for integ, meta in INTEGRATIONS.items():
        it = data['items'].get(integ) or {}
        items.append({
            'integ': integ,
            'title': meta['title'],
            'min_req': meta.get('min_req'),
            'licensed': bool(it.get('enabled', True)),   # tanımsızsa AÇIK (mevcut firmalar bozulmasın; satış için MASTER kapatır)
            'key_set': bool(it.get('key')),
            'created_at': it.get('created_at'),
        })
    return {'domain': data['domain'], 'central_url': central_url(data['domain']), 'items': items}


def gen_key(conn, integ):
    """Entegrasyon için yeni gizli anahtar üretir (secrets.token_urlsafe(32)), şifreli saklar ve DÜZ metni döndürür
    (yalnız bir kez gösterilir). Daha önce anahtar varsa üzerine yazar (yeniden üretim)."""
    if integ not in INTEGRATIONS:
        raise ValueError('Bilinmeyen entegrasyon')
    data = _load(conn)
    key = secrets.token_urlsafe(32)
    it = data['items'].get(integ) or {}
    it['key'] = cameras.encrypt(key)
    it.setdefault('enabled', True)
    it['created_at'] = db.now()
    data['items'][integ] = it
    _save(conn, data)
    return key


def set_enabled(conn, integ, enabled):
    """Lisans (satış / etkinleştirme) bayrağını açar/kapatır."""
    if integ not in INTEGRATIONS:
        raise ValueError('Bilinmeyen entegrasyon')
    data = _load(conn)
    it = data['items'].get(integ) or {}
    it['enabled'] = bool(enabled)
    data['items'][integ] = it
    _save(conn, data)
    return bool(enabled)


def set_domain(conn, domain):
    """Ortak domaini (şema ayıklanmış biçimde) saklar; merkez adresi bundan türetilir."""
    data = _load(conn)
    data['domain'] = _strip_scheme(domain)
    _save(conn, data)
    return data['domain']


def domain(conn):
    return _load(conn)['domain']


def key_for(integ):
    """Bir entegrasyonun çözülmüş (düz) anahtarı; yoksa ''. İç kullanım (Aşama 2)."""
    with db.connect() as conn:
        it = _load(conn)['items'].get(integ) or {}
    return cameras.decrypt(it['key']) if it.get('key') else ''


def integ_for_key(key):
    """Verilen anahtara karşılık gelen entegrasyon adını döndürür; eşleşme yoksa None.

    Aşama 2'de, bağlanan ajanın hangi ürün olduğunu belirlemek ve kimlik doğrulamak için kullanılacak.
    Sabit-zamanlı karşılaştırma ile tüm tanımlı anahtarlara bakar (yalnız anahtar üretilmiş entegrasyonlar).
    """
    if not key:
        return None
    with db.connect() as conn:
        data = _load(conn)
    for integ, it in data['items'].items():
        stored = it.get('key')
        if stored and hmac.compare_digest(cameras.decrypt(stored), key):
            return integ
    return None
