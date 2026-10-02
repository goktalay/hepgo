"""Entegrasyon ayarları (Program Ayarları › Entegrasyonlar): Claude API, Mikro ERP, Google e-posta, genel adresler.

Sistem yöneticisi değerleri panelden girer; app_kv['integrations'] içinde saklanır ve config modülündeki
karşılıklarının üzerine yazılır (kod her yerde `config.X` okuduğu için anında geçerli olur, yeniden başlatma
gerekmez). Panelde değer yoksa .env'deki değer kullanılır. Gizli alanlar (anahtar / şifre) veri klasöründeki
anahtarla şifreli saklanır ve API'den asla geri dönmez: yalnızca tanımlı olup olmadığı ve kaynağı (panel / .env) döner.
"""
import json

from . import cameras, config

KV_KEY = 'integrations'

# grup → başlık, açıklama, alanlar: (config adı, etiket, tür: text | secret | int | url, ipucu)
GROUPS = {
    'ai': {
        'title': 'Claude API (Yapay Zeka)',
        'desc': 'Maskot asistanı “Kubbe” bu anahtarla çalışır. Anahtar: console.anthropic.com › API Keys.',
        'fields': [
            ('AI_API_KEY', 'API anahtarı', 'secret', 'sk-ant-… ile başlar'),
            ('AI_WORKSPACE_ID', 'Workspace ID', 'text', 'Anahtar bir çalışma alanına bağlıysa (wrkspc_…)'),
            ('AI_MODEL', 'Model', 'text', 'Varsayılan: claude-haiku-4-5'),
        ],
    },
    'mikro': {
        'title': 'Mikro ERP',
        'desc': 'Cari, stok ve fatura içe aktarımı için Mikro SQL Server bağlantısı.',
        'fields': [
            ('MIKRO_HOST', 'Sunucu IP / adı', 'text', 'ör. 192.168.1.100'),
            ('MIKRO_PORT', 'Port', 'int', 'SQL Server varsayılanı 1433'),
            ('MIKRO_DB', 'Veritabanı', 'text', 'ör. MikroDB_V16_FIRMA'),
            ('MIKRO_USER', 'Kullanıcı adı', 'text', 'SQL kullanıcı adı'),
            ('MIKRO_PASSWORD', 'Şifre', 'secret', 'SQL kullanıcı şifresi'),
        ],
    },
    'pdks': {
        'title': 'PDKS (Personel Giriş-Çıkış)',
        'desc': 'Personel devam kontrol cihazlarının Firebird veritabanı (ör. Fixap). Giriş-çıkış hareketleri yalnızca okunur; cihaza / veritabanına hiçbir şey yazılmaz.',
        'fields': [
            ('PDKS_HOST', 'Sunucu IP / adı', 'text', 'ör. 192.168.1.100'),
            ('PDKS_PORT', 'Port', 'int', 'Firebird varsayılanı 3050'),
            ('PDKS_DB', 'Veritabanı yolu', 'text', r'Sunucudaki yol, ör. \\192.168.1.100\MPremium\PDKS.GDB'),
            ('PDKS_USER', 'Kullanıcı adı', 'text', 'Firebird kullanıcısı (genelde SYSDBA)'),
            ('PDKS_PASSWORD', 'Şifre', 'secret', 'Firebird şifresi'),
        ],
    },
    'google': {
        'title': 'Google E-posta (Gmail)',
        'desc': 'Kullanıcıların Gmail hesaplarını bağlaması için Google Cloud OAuth istemcisi.',
        'fields': [
            ('GOOGLE_CLIENT_ID', 'OAuth Client ID', 'text', '….apps.googleusercontent.com'),
            ('GOOGLE_CLIENT_SECRET', 'Client Secret', 'secret', 'GOCSPX-…'),
        ],
    },
    'general': {
        'title': 'Genel',
        'desc': 'Davet / e-posta bağlantılarında kullanılan adresler ve firma adı.',
        'fields': [
            ('COMPANY_NAME', 'Firma adı', 'text', 'Başlıklarda ve asistanda görünür'),
            ('PUBLIC_URL', 'İnternet adresi', 'url', 'ör. https://caymaz.app'),
            ('LOCAL_URL', 'Yerel ağ adresi', 'url', 'ör. http://192.168.1.189:8080'),
        ],
    },
}
FIELDS = {k: (g, kind) for g, grp in GROUPS.items() for k, _, kind, _ in grp['fields']}
ENV = {k: getattr(config, k) for k in FIELDS}   # .env / varsayılan değerler (panelden silinince geri dönülür)


def _load(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KV_KEY,)).fetchone()
    try:
        return json.loads(row[0]) if row else {}
    except ValueError:
        return {}


def _cast(key, value):
    kind = FIELDS[key][1]
    if kind == 'int':
        return int(value)
    if kind == 'url':
        return str(value).strip().rstrip('/')
    return str(value).strip()


def _value(key, stored):
    """Saklanan ham değer → gerçek değer (gizliler çözülür)."""
    return cameras.decrypt(stored) if FIELDS[key][1] == 'secret' else stored


def apply(conn):
    """Panel değerlerini config'e uygular; panelde olmayanlar .env değerine döner. Açılışta ve her kayıtta çağrılır."""
    data = _load(conn)
    for key in FIELDS:
        if key in data and data[key] not in (None, ''):
            try:
                setattr(config, key, _cast(key, _value(key, data[key])))
                continue
            except (TypeError, ValueError):
                pass
        setattr(config, key, ENV[key])


def view(conn, group_keys=None):
    """Panel için durum. Gizli alanların değeri asla dönmez."""
    data = _load(conn)
    out = []
    for g, grp in GROUPS.items():
        if group_keys is not None and g not in group_keys:
            continue
        fields = []
        for key, label, kind, hint in grp['fields']:
            in_panel = key in data and data[key] not in (None, '')
            cur = getattr(config, key)
            f = {'key': key, 'label': label, 'kind': kind, 'hint': hint, 'set': bool(cur),
                 'source': 'panel' if in_panel else ('env' if ENV[key] else '')}
            if kind != 'secret':
                f['value'] = cur if cur is not None else ''
            fields.append(f)
        out.append({'key': g, 'title': grp['title'], 'desc': grp['desc'], 'fields': fields,
                    'configured': bool(config.COMPANY_NAME) if g == 'general'
                    else all(f['set'] for f in fields if f['key'] not in ('AI_WORKSPACE_ID',))})
    return out


def save(conn, group, values, clear=()):
    """values: {KEY: değer}. Gizli alanda boş değer = değiştirme. clear: panelden silinip .env'e dönülecek alanlar."""
    if group not in GROUPS:
        raise ValueError('Bilinmeyen bölüm')
    keys = {k for k, *_ in GROUPS[group]['fields']}
    data = _load(conn)
    changed = []
    for key, val in (values or {}).items():
        if key not in keys:
            continue
        kind = FIELDS[key][1]
        val = '' if val is None else str(val).strip()
        if kind == 'secret':
            if not val:
                continue
            data[key] = cameras.encrypt(val)
        else:
            if val == '':
                data.pop(key, None)
            else:
                try:
                    _cast(key, val)
                except ValueError:
                    raise ValueError(f'{key}: geçersiz değer')
                data[key] = val
        changed.append(key)
    for key in clear or ():
        if key in keys and key in data:
            data.pop(key)
            changed.append(key)
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KV_KEY, json.dumps(data)))
    apply(conn)
    return changed


def test(group):
    """Bağlantı denemesi → (ok, mesaj). Mesajlarda anahtar / şifre yer almaz."""
    if group == 'ai':
        if not config.AI_API_KEY:
            return False, 'API anahtarı tanımlı değil.'
        try:
            import anthropic
            headers = {'anthropic-workspace-id': config.AI_WORKSPACE_ID} if config.AI_WORKSPACE_ID else None
            client = anthropic.Anthropic(api_key=config.AI_API_KEY, default_headers=headers, timeout=15, max_retries=0)
            m = client.models.retrieve(config.AI_MODEL)   # jeton harcamaz
            return True, f'Bağlantı başarılı · model: {getattr(m, "display_name", None) or m.id}'
        except Exception as e:   # noqa: BLE001 — kullanıcıya anlaşılır mesaj
            status = getattr(e, 'status_code', None)
            if status == 401:
                return False, 'Anahtar geçersiz (401). Anahtarı ve workspace ID’yi kontrol edin.'
            if status == 404:
                return False, f'Model bulunamadı: {config.AI_MODEL}'
            if status == 403:
                return False, 'Anahtarın bu işleme / workspace’e yetkisi yok (403).'
            return False, f'Bağlanılamadı: {type(e).__name__}'
    if group == 'mikro':
        from . import mikro
        if not mikro.configured():
            return False, 'Sunucu, veritabanı, kullanıcı ve şifre girilmeli.'
        try:
            with mikro.connect() as c:
                cur = c.cursor()
                cur.execute('SELECT DB_NAME() AS db')
                name = cur.fetchone()['db']
            return True, f'Bağlantı başarılı · veritabanı: {name}'
        except Exception as e:   # noqa: BLE001
            msg = str(e)
            if config.MIKRO_PASSWORD:
                msg = msg.replace(config.MIKRO_PASSWORD, '***')
            if '18456' in msg or 'Login failed' in msg:
                return False, 'Kullanıcı adı veya şifre hatalı.'
            if '4060' in msg or 'Cannot open database' in msg:
                return False, f'Veritabanı bulunamadı ya da bu kullanıcının erişimi yok: {config.MIKRO_DB}'
            if '20009' in msg or 'timed out' in msg or 'unavailable' in msg:
                return False, f'Sunucuya ulaşılamadı ({config.MIKRO_HOST}:{config.MIKRO_PORT}). IP / port, ağ bağlantısı ya da güvenlik duvarını kontrol edin.'
            return False, f'Bağlanılamadı: {msg[:160]}'
    if group == 'pdks':
        from . import pdks
        if not pdks.configured():
            return False, 'Sunucu, veritabanı yolu, kullanıcı ve şifre girilmeli.'
        return pdks.test()
    if group == 'google':
        ok = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
        return ok, 'Bilgiler tanımlı; kullanıcılar E-posta bölümünden Gmail bağlayabilir.' if ok else 'Client ID ve Secret girilmeli.'
    if group == 'general':
        return True, 'Genel ayarlar kaydedildi.'
    return False, 'Bilinmeyen bölüm'
