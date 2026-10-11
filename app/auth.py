import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request

from . import config, db, policy

ADMIN = 'Sistem Yöneticisi'
WAREHOUSE_MANAGER = 'Depo Yöneticisi'
PRODUCTION_MANAGER = 'Üretim Yöneticisi'
PRODUCTION_LEAD = 'Üretim Sorumlusu'
PRINTER_MAINTAINER = 'Yazıcı Bakım Sorumlusu'
FIELD_LEAD = 'Saha Sorumlusu'
FIELD_STAFF = 'Saha Personeli'
DRIVER = 'Şoför'
PILOT = 'Pilot'
ASSEMBLER = 'Montaj Personeli'
ELECTRONICS = 'Elektronik Personeli'
ADMIN_STAFF = 'İdari Personel'
SECRETARY = 'Sekreter'
SECURITY = 'Güvenlik'   # fabrika girişi: yalnızca araç giriş / çıkış kaydı; başka hiçbir modülü görmez
CAMERA = 'Kamera Yetkilisi'   # Kameralar modülü (izleme, yüz tanıma, tanımlanmayan kişiler) — NVR aktifse görünür
MASTER = 'MASTER'          # sistem sahibi (owner); ROLES'e eklenmez, atanamaz; yalnızca config.MASTER_USERNAMES
MRP_LEAD = 'MRP Sorumlusu'   # Malzeme İhtiyaç Planlaması: malzemeler, depolar, stok hareketleri, yarı mamul stoğu
PURCHASING = 'Satın Alma'   # tedarikçiler, satın alma talepleri, fatura / irsaliye (depo girişi), teklifler
SALES = 'Satış'   # Satış Yönetimi: firmalar için satış faturası oluşturma
HR = 'İnsan Kaynakları'   # personel kayıtları, iş başvuruları, özlük dosyaları, sözleşmeler, izin onayı
INTERN = 'Stajer'       # hiçbir modüle yetkili değil; genel yapıyı (pano, Kişisel, mesaj, duyurular) kullanır
CLEANER = 'Temizlik Görevlisi'   # yalnızca Temizlik modülü (günlük temizlik çeklisti)
DESIGNER = 'Endüstriyel Tasarımcı'   # Endüstriyel Tasarım modülü: proje + çizim / montaj çizimi + sürüm geçmişi
FINANCE = 'Finans'   # Finans / ön-muhasebe: kasa-banka, cari, nakit akışı, ödeme/tahsilat, mizan, bordro
QUALITY = 'Kalite / Sertifikasyon'   # Sertifikasyon: sertifikalar (ISO 9001, tesis güvenlik, üretim izni…), dokümanlar, denetimler
PROJECT = 'Proje / Ar-Ge Sorumlusu'   # Proje Yönetimi: projeler, proje kâr-zararı, harekete proje atama
BOSS = 'Patron / Üst Yönetim'   # Patron ekranı: şirketin tüm özet göstergeleri (yalnızca okunur)
FLEET = 'Araç / Filo Sorumlusu'   # Araç Yönetimi: araçlar, zimmet, belgeler, giderler (muhasebe hareketi etiketleme)
SUPPORT_ROLE = 'Merkez Destek'   # YALNIZCA merkez (Veilox) instance'ında atanır; müşteri firmalarına çapraz (destek) giriş yetkisi verir

ROLES = [ADMIN, WAREHOUSE_MANAGER, PRODUCTION_MANAGER, PRODUCTION_LEAD, PRINTER_MAINTAINER,
         FIELD_LEAD, FIELD_STAFF, DRIVER, PILOT, ASSEMBLER, ELECTRONICS, ADMIN_STAFF, SECRETARY, SECURITY, CAMERA, HR, PURCHASING, SALES, MRP_LEAD, DESIGNER, FINANCE, QUALITY, FLEET, PROJECT, BOSS, CLEANER, INTERN]
# Sistem rollerinin açıklaması (Rol Yönetimi'nde görünür; yönetici değiştirebilir)
ROLE_DESC = {
    ADMIN: 'Tüm modüller ve sistem ayarları', WAREHOUSE_MANAGER: 'Depo, stok ve onay işlemleri', PRODUCTION_MANAGER: 'Üretim ve iş emirleri yönetimi',
    PRODUCTION_LEAD: 'Üretim operasyonu', PRINTER_MAINTAINER: 'Yazıcı bakım ve takibi', FIELD_LEAD: 'Saha görevlerinin yönetimi',
    FIELD_STAFF: 'Saha görevlerinde çalışan personel', DRIVER: 'Saha görevi araç / yol bilgisi', PILOT: 'Uçuş ve uçuş raporları',
    ASSEMBLER: 'Montaj ve kalibrasyon', ELECTRONICS: 'Elektronik kat montajı', ADMIN_STAFF: 'İdari işler: firmalar, evrak, araçlar',
    SECRETARY: 'Misafir ve kargo kayıtları', SECURITY: 'Fabrika girişi: araç giriş / çıkış', CAMERA: 'Kameralar ve yüz tanıma',
    HR: 'Personel, izin, özlük', PURCHASING: 'Tedarikçi, talep, fatura / irsaliye', SALES: 'Satış faturaları', MRP_LEAD: 'Malzeme ihtiyaç planlaması',
    DESIGNER: 'Endüstriyel tasarım projeleri', FINANCE: 'Finans ve ön muhasebe', QUALITY: 'Sertifikalar ve denetimler',
    FLEET: 'Araçlar, zimmet ve araç giderleri', PROJECT: 'Projeler ve proje kâr-zararı', BOSS: 'Üst yönetim özeti (Patron ekranı)', CLEANER: 'Günlük temizlik çeklisti',
    INTERN: 'Modül yetkisi yok; genel alanları kullanır', SUPPORT_ROLE: 'Merkez destek: müşteri firmalara çapraz giriş',
}
# Yardımcı personel rolleri: bu rollerin seçim listelerinde stajerler de çıkar ("Stajer" etiketiyle) ve seçilebilir
HELPER_ROLES = (ASSEMBLER, ELECTRONICS, FIELD_STAFF)

# Modül → girebilen roller (yetki matrisi, 2026-09-25; Sistem Yöneticisi tüm modüllerde). Her rol yalnızca
# burada listelendiği modüllere girer; birden fazla rolü olan kullanıcı rollerinin birleşimini görür.
MODULE_ROLES = {
    'admin':      [ADMIN],                                                                    # M1 Yönetim
    'production': [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD, ASSEMBLER, ELECTRONICS],       # M2 Üretim
    'orders':     [ADMIN, PRODUCTION_MANAGER],                                                # M3 İş Emri Yönetimi (Üretim Yönetimi alt modülü; eski adı Sipariş Yönetimi)
    'warehouse':  [ADMIN, WAREHOUSE_MANAGER],                                                 # M4 Depo
    'stock':      [ADMIN, WAREHOUSE_MANAGER, PRODUCTION_MANAGER, PRODUCTION_LEAD, FIELD_LEAD,
                   FIELD_STAFF, PILOT, MRP_LEAD],                                                       # M5 Stok
    'field':      [ADMIN, FIELD_LEAD, FIELD_STAFF, DRIVER, PILOT],                            # M6 Saha
    'printers':   [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD, PRINTER_MAINTAINER],           # M7 Yazıcı
    'products':   [ADMIN],                                                                    # M8 Ürün
    'tools':      [r for r in ROLES if r not in (SECURITY, CAMERA, INTERN, CLEANER)],         # M9 Araçlar
    'users':      [ADMIN],                                                                    # M10 Kullanıcı
    'companies':  [ADMIN, ADMIN_STAFF],                                                       # M11 Firma
    'documents':  [ADMIN, ADMIN_STAFF],                                                       # M12 Evrak
    'secretariat': [ADMIN, SECRETARY],                                                        # M13 Sekreterya
    'security':   [ADMIN, SECURITY],                                                          # M14 Güvenlik
    'cameras':    [ADMIN, CAMERA],                                                            # M24 Kameralar (izleme + yüz tanıma; NVR aktifse görünür)
    'factory':    [ADMIN, CAMERA],                                                            # M31 Fabrika (dijital ikiz: kat planı + kamera/personel yerleşimi + yüz tanımadan hareket)
    'rehber':     [r for r in ROLES if r not in (SECURITY, CAMERA, INTERN, CLEANER)],         # M25 Rehber (birleşik kişi rehberi)
    'hr':         [ADMIN, HR],                                                                # M17 İnsan Kaynakları
    'purchasing': [ADMIN, PURCHASING],                                                        # M19 Satın Alma
    'sales':      [ADMIN, SALES],                                                             # M21 Satış Yönetimi
    'reports':    [r for r in ROLES if r not in (SECURITY, CAMERA, INTERN, CLEANER)],         # M15 Raporlar (içerik modül yetkisine göre)
    'announcements': list(ROLES),                                                             # M16 Duyurular (yazan: Sistem Yöneticisi)
    'cleaning':   [ADMIN, CLEANER],                                                           # M22 Temizlik (günlük çeklist)
    'design':     [ADMIN, DESIGNER],                                                          # M23 Endüstriyel Tasarım (proje + çizim + sürüm)
    'finance':    [ADMIN, FINANCE],                                                           # M24 Finans / ön-muhasebe
    'certs':      [ADMIN, QUALITY],                                                           # M27 Sertifikasyon (sertifika + doküman + denetim)
    'fleet':      [ADMIN, ADMIN_STAFF, FLEET],                                                # M28 Araç Yönetimi (araç, zimmet, belge, gider)
    'boss':       [ADMIN, BOSS],                                                              # M29 Patron ekranı (üst yönetim özeti)
    'pos':        [ADMIN, SALES],                                                             # Esnaf Kasa (POS): dokunmatik perakende satış
    'sections':     [ADMIN, SALES],                                                           # Bölümler (berber oda / lokanta salon+masa)
    'services':     [ADMIN, SALES],                                                           # Hizmetler (berber/kuaför)
    'reservations': [ADMIN, SALES],                                                           # Rezervasyon (randevu/masa)
    'waiter':       [ADMIN, SALES],                                                           # Garson (lokanta adisyon)
    'projects':   [ADMIN, PROJECT],                                                           # M30 Proje Yönetimi (Ar-Ge projeleri, proje kâr-zararı)
}
# M18 Malzeme İhtiyaç Planlaması: Yarı Mamül (stock) ve Onay Yönetimi (warehouse) alt modüllerini görenler
MODULE_ROLES['mrp'] = sorted(set(MODULE_ROLES['stock']) | set(MODULE_ROLES['warehouse']), key=ROLES.index)
MODULE_ROLES['mikro'] = []   # M20 Mikro ERP: YALNIZCA MASTER (sistem sahibi). Hiçbir role verilmez; master tüm modülleri MODULE_ROLES.keys()'ten alır.
# Merkez destek rolü yalnızca merkez (Veilox) instance'ında ATANABİLİR olsun; MODULE_ROLES'tan SONRA eklenir ki
# hiçbir modül yetkisi vermesin (yalnızca çapraz-giriş yetkisinin işareti). Müşteri instance'larında listede görünmez.
if config.FEDERATION_CENTRAL and SUPPORT_ROLE not in ROLES:
    ROLES.append(SUPPORT_ROLE)
# Merkez modu (Veilox Merkez): üyelik yönetimi, destek talepleri, toplu SMS. Firma instance'larında: Üyeliğim & Destek.
if config.FEDERATION_CENTRAL:
    MODULE_ROLES['members'] = [ADMIN]                  # firmalar, paketler, ödeme takibi, askı
    MODULE_ROLES['tickets'] = [ADMIN, SUPPORT_ROLE]    # destek talepleri (merkez gelen kutusu)
    MODULE_ROLES['sms'] = [ADMIN]                      # toplu SMS
elif config.FEDERATION_URL:
    MODULE_ROLES['uyelik'] = [ADMIN]                   # firma: paket, ödemeler, destek talepleri, sözleşme
MRP_MANAGERS = [ADMIN, WAREHOUSE_MANAGER, MRP_LEAD]   # malzeme / depo kaydı, stok hareketi
# Modül içinde değişiklik yapabilen roller (okuma MODULE_ROLES ile).
# Montaj Personeli (2026-09-26) Üretim'e montaj/kalibrasyon, Elektronik Personeli elektronik kat montajı için
# girer; ikisi de parça üretim işlemlerini yapamaz.
PART_OPERATORS = [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD]
FIELD_MANAGERS = [ADMIN, FIELD_LEAD]

def has_role_or_intern(conn, uid, role):
    """Kullanıcı bu role sahip mi (yardımcı personel rollerinde stajer de kabul edilir)?"""
    roles = (role, INTERN) if role in HELPER_ROLES else (role,)
    return conn.execute(
        f'''SELECT 1 FROM users u JOIN user_roles r ON r.user_id = u.id
            WHERE u.id = ? AND u.active = 1 AND r.role IN ({','.join('?' * len(roles))})''', (uid, *roles)).fetchone() is not None


def interns(conn):
    return {r[0] for r in conn.execute('SELECT user_id FROM user_roles WHERE role = ?', (INTERN,))}


COOKIE = 'caymaz_session'


def is_https(request):
    """İstek tarayıcıdan HTTPS ile mi geldi? Doğrudan ya da Cloudflare tüneli üzerinden (uygulama tünele düz HTTP/soket
    ile bağlanır; asıl şema X-Forwarded-Proto / CF-Visitor başlığındadır)."""
    proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower()
    return request.url.scheme == 'https' or proto == 'https' or '"scheme":"https"' in request.headers.get('cf-visitor', '').replace(' ', '')


def set_session_cookie(response, request, token, hours):
    """Oturum çerezi: HttpOnly, SameSite=Lax; Secure (çerez düz HTTP'den hiç gönderilmez). Üretimde her zaman Secure
    (config.FORCE_SECURE_COOKIE varsayılan açık; tüm trafik CF TLS, açık TCP port yok). Yerel http:// geliştirmede
    CAYMAZ_FORCE_SECURE_COOKIE=0 ile is_https'e düşer."""
    secure = config.FORCE_SECURE_COOKIE or is_https(request)
    response.set_cookie(COOKIE, token, httponly=True, samesite='lax', max_age=int(hours * 3600), secure=secure)
_ITERATIONS = 240_000


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, _ITERATIONS)
    return f'pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(password, stored):
    try:
        _, iterations, salt, digest = stored.split('$')
        calc = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(calc.hex(), digest)
    except ValueError:
        return False


def user_roles(conn, user_id):
    return [r[0] for r in conn.execute('SELECT role FROM user_roles WHERE user_id = ?', (user_id,))]


def is_master(username):
    """Sistem sahibi hesabı mı? (config.MASTER_USERNAMES; başka kimse MASTER olamaz)."""
    return bool(username) and username.strip().lower() in config.MASTER_USERNAMES


def allowed_modules(roles):
    """Rollerin okuyabildiği modüller (Rol Yönetimi: veritabanı izinleri, miras ve yasak kuralıyla)."""
    from . import rbac
    return rbac.allowed(roles)


def all_roles():
    """Atanabilir roller: sistem rolleri + Rol Yönetimi'nde eklenen roller."""
    from . import rbac
    return rbac.role_names()


def all_nodes():
    from . import rbac
    return rbac.node_keys()


def dnd_state(prefs):
    """Rahatsız etmeyin (Ayarlar → Gizlilik): {'calls':bool,'messages':bool}.

    prefs ham JSON metni ya da çözülmüş sözlük olabilir. `until` verilmişse süre geçtiyse kapalı sayılır
    (süreli); until yoksa seçili kanallar sürekli kapalıdır."""
    try:
        if isinstance(prefs, str):
            prefs = json.loads(prefs) if prefs else {}
        d = (prefs or {}).get('settings', {}).get('dnd') or {}
    except (ValueError, AttributeError):
        return {'calls': False, 'messages': False}
    until = d.get('until')
    if until:
        try:
            if datetime.now() > datetime.fromisoformat(until):
                return {'calls': False, 'messages': False}
        except (ValueError, TypeError):
            pass
    return {'calls': bool(d.get('calls')), 'messages': bool(d.get('messages'))}


# ---------- İzinli / raporlu: onaylı izin ya da sağlık raporu bugünü kapsıyorsa personel izinli görünür ve sisteme giremez
ABSENCE_SQL = '''
    SELECT e.user_id, 'IZIN' AS kind, l.end_date AS until FROM leave_requests l JOIN employees e ON e.id = l.employee_id
    WHERE l.status = 'ONAYLANDI' AND l.start_date <= :d AND l.end_date >= :d AND e.user_id IS NOT NULL {uf}
    UNION ALL
    SELECT e.user_id, 'RAPOR', r.end_date FROM employee_health_reports r JOIN employees e ON e.id = r.employee_id
    WHERE r.start_date <= :d AND r.end_date >= :d AND e.user_id IS NOT NULL {uf}'''
ABSENCE_TEXT = {'IZIN': 'İzinli', 'RAPOR': 'Raporlu'}


def absent_map(conn, day=None):
    """{user_id: {'kind': 'IZIN'|'RAPOR', 'until': 'YYYY-MM-DD', 'label': 'İzinli'|'Raporlu'}} — bugün (ya da verilen gün)."""
    d = day or datetime.now().strftime('%Y-%m-%d')
    out = {}
    for uid, kind, until in conn.execute(ABSENCE_SQL.format(uf=''), {'d': d}):
        cur = out.get(uid)
        if not cur or kind == 'RAPOR' or (until or '') > cur['until']:
            out[uid] = {'kind': kind, 'until': until, 'label': ABSENCE_TEXT[kind]}
    return out


def absence(conn, user_id, day=None):
    d = day or datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute(ABSENCE_SQL.format(uf='AND e.user_id = :u'), {'d': d, 'u': user_id}).fetchall()
    if not rows:
        return None
    kind = 'RAPOR' if any(r[1] == 'RAPOR' for r in rows) else 'IZIN'
    until = max(r[2] for r in rows if r[1] == kind)
    return {'kind': kind, 'until': until, 'label': ABSENCE_TEXT[kind]}


def absence_message(a):
    until = f'{a["until"][8:10]}.{a["until"][5:7]}.{a["until"][:4]}'
    what = 'sağlık raporlusunuz' if a['kind'] == 'RAPOR' else 'izinlisiniz'
    return f'{until} tarihine kadar {what}; bu süre içinde sisteme giriş yapılamaz. İyi dinlenmeler!'


_absence_cache = {}   # user_id -> (zaman, sonuç): her istekte sorgu yapılmasın


def create_session(conn, user_id, hours=None):
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    conn.execute('INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)',
                 (token, user_id, now.isoformat(timespec='seconds'),
                  (now + timedelta(hours=hours or config.SESSION_HOURS)).isoformat(timespec='seconds')))
    return token


def user_by_token(conn, token):
    """Oturum çerezi tokenından kullanıcı (WebSocket gibi Depends kullanılamayan yerler için). Geçersizse None."""
    if not token:
        return None
    row = db.row(conn.execute(
        '''SELECT u.id, u.username, u.full_name, u.photo FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token = ? AND s.expires_at > ? AND u.active = 1''', (token, db.now())))
    return row


def current_user(request: Request, conn=db.DB):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Oturum açılmamış')
    user = db.row(conn.execute(
        '''SELECT u.id, u.username, u.full_name, u.photo, u.active, u.last_seen, u.prefs, u.must_change_password, u.support_until, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?''', (token,)))
    now = db.now()
    if not user or user['expires_at'] < now or not user['active']:
        raise HTTPException(401, 'Oturum süresi doldu')
    # Çevrimiçi takibi: son etkinlik zamanı (yazma yükü için en fazla 20 sn'de bir güncellenir)
    if not user['last_seen'] or (datetime.fromisoformat(now) - datetime.fromisoformat(user['last_seen'])).total_seconds() > 20:
        conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (now, user['id']))
        conn.commit()   # yazma kilidini isteğin sonuna kadar tutma
    # İlk girişte şifre değişikliği zorunlu: değiştirene kadar yalnızca oturum / şifre uçları çalışır
    if user['must_change_password'] and config.FORCE_PASSWORD_CHANGE and policy.get(conn)['force_first_change'] and request.url.path not in PASSWORD_FREE_PATHS:
        raise HTTPException(428, 'Devam etmek için önce şifrenizi değiştirin')
    real = user_roles(conn, user['id'])   # DB'deki gerçek roller (bildirim / katılım bunlara göre)
    user['master'] = is_master(user['username'])
    # Merkez (Veilox) destek oturumu: firma master'ının onayıyla, süre dolana kadar master-benzeri (tüm işlevsel modüller)
    user['support'] = bool(user.get('support_until') and user['support_until'] > now) and not user['master']
    # İzinli / raporlu personelin açık oturumu da kapanır (sistem sahibi ve destek hariç); sonuç 60 sn önbellekte
    if not user['master'] and not user['support']:
        import time as _t
        hit = _absence_cache.get(user['id'])
        if not hit or _t.monotonic() - hit[0] > 60:
            hit = (_t.monotonic(), absence(conn, user['id']))
            _absence_cache[user['id']] = hit
        if hit[1]:
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            raise HTTPException(401, absence_message(hit[1]))
        # Merkez firmayı pasife aldıysa (yumuşak askı) master dışındaki herkes durur; master Üyeliğim'e erişebilir
        from . import central_client
        s = central_client.suspension()
        if s.get('suspended'):
            raise HTTPException(401, central_client.suspended_message(s))
    from . import rbac
    if user['master']:   # sistem sahibi: her şeye erişir (rol iptal edilse bile) ama role bağlı bildirim/katılım gerçek rollerine göre
        user['real_roles'] = real
        user['roles'] = [*ROLES, MASTER]
        user['modules'] = [*dict.fromkeys([*MODULE_ROLES.keys(), *rbac.node_keys()]), 'master']
        user['write_modules'] = list(user['modules'])
    elif user['support']:   # merkez destek: tüm işlevsel modüller (sahibe özel 'master' paneli hariç); süreli, onaylı, iz kaydı tutulur
        user['real_roles'] = real
        user['roles'] = real
        user['modules'] = [*dict.fromkeys([*MODULE_ROLES.keys(), *rbac.node_keys()])]
        user['write_modules'] = list(user['modules'])
    else:
        # Rol Yönetimi: roller üst rollerinden miras alır (koddaki rol adı kontrolleri de üst rolle geçer);
        # modüller rol izinlerinden (aç + oku), yazma ayrı listede. Yasak izni yener.
        user['real_roles'] = real
        user['roles'] = rbac.expand(real)
        user['modules'] = rbac.allowed(real)
        user['write_modules'] = rbac.writable(real)
    # Mikro ERP bu tenant'ta tanımlı değilse (ör. Türkbey) modülü hiç gösterme — boş ekran / yanlış firma verisi olmasın.
    if 'mikro' in user['modules'] and not (config.MIKRO_HOST and config.MIKRO_DB and config.MIKRO_USER and config.MIKRO_PASSWORD):
        user['modules'] = [m for m in user['modules'] if m != 'mikro']
    # Merkez (Veilox) bu firmaya belirli modülleri verdiyse, herkes (master dâhil) yalnızca o modülleri görür.
    # 'master' modülü (sistem sahibi aracı) her zaman kalır; CAYMAZ_MODULES tanımsızsa kısıtlama yoktur.
    if config.MODULES is not None:
        allow = set(config.MODULES) | {'master', 'uyelik'}   # Üyeliğim & Destek: paketten bağımsız, her firmada destek kanalı
        user['modules'] = [m for m in user['modules'] if m.split('.')[0] in allow]
    # Master, Program Ayarları › Modül Yönetimi'nden SEÇMELİ (optional) modülleri kapatabilir (app_kv['modules.disabled']).
    # Zorunlu (required) ve her-zaman (master/uyelik) modüller kapatılamaz.
    try:
        from . import modules_tier
        _row = conn.execute("SELECT v FROM app_kv WHERE k = 'modules.disabled'").fetchone()
        _off = set(json.loads(_row[0])) if _row and _row[0] else set()
        if _off:
            user['modules'] = [m for m in user['modules']
                               if m.split('.')[0] not in _off or modules_tier.tier(m) in ('required', 'always')]
    except Exception:   # noqa: BLE001 — modül yönetimi hatası girişi bozmasın
        pass
    # Esnaf modülleri (yazarkasa/bölümler/hizmetler/rezervasyon/garson) yalnızca esnaf paketinde görünür;
    # fabrika/KOBİ firmasında (esnaf_pkg boş) master dâhil kimseye gösterilmez.
    if not config.ESNAF_PKG:
        _esnaf = {'pos', 'sections', 'services', 'reservations', 'waiter'}
        user['modules'] = [m for m in user['modules'] if m.split('.')[0] not in _esnaf]
    user['write_modules'] = [m for m in user.get('write_modules', []) if m in user['modules']]
    return user


PASSWORD_FREE_PATHS = {'/api/auth/me', '/api/auth/password', '/api/auth/logout', '/api/system/status', '/api/activity'}


READ_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def require_module(module):
    """Modül (ya da 'finance.trial' gibi alt modül) erişimi: okuma için 'oku', diğer yöntemler (POST/PUT/DELETE) için
    'yaz' yetkisi gerekir (Rol Yönetimi)."""
    def dep(request: Request, user=Depends(current_user)):
        if module not in user['modules']:
            raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
        if request.method not in READ_METHODS and module not in user.get('write_modules', user['modules']):
            raise HTTPException(403, 'Bu modülde yalnızca görüntüleme yetkiniz var (veri yazma yetkisi yok)')
        return user
    return dep


def require_roles(*roles):
    def dep(user=Depends(current_user)):
        if not set(roles) & set(user['roles']):
            raise HTTPException(403, 'Bu işlem için yetkiniz yok')
        return user
    return dep


def require_sysadmin():
    """Yalnızca sistem yöneticisi (ADMIN rolü) ya da sistem sahibi (MASTER). Kameralar modülü gibi yönetim araçları için."""
    def dep(user=Depends(current_user)):
        if ADMIN not in user['roles'] and not user.get('master'):
            raise HTTPException(403, 'Bu işlem yalnızca sistem yöneticisine açıktır')
        return user
    return dep


def seed_admin():
    """İlk çalıştırmada .env'deki sistem yöneticisini oluşturur."""
    if not config.ADMIN_USERNAME or not config.ADMIN_PASSWORD:
        return
    with db.connect() as conn:
        exists = conn.execute('SELECT id FROM users WHERE username = ?', (config.ADMIN_USERNAME,)).fetchone()
        if exists:
            return
        # Kayıt dili varsa master'ın varsayılan arayüz dili olsun (ERP app.js initLang → prefs.settings.lang)
        _lang = (config.ADMIN_LANG or '').strip().lower()
        prefs = json.dumps({'settings': {'lang': _lang}}) if _lang in ('tr', 'en', 'de', 'fr', 'es', 'ar', 'ru') else None
        cur = conn.execute(
            'INSERT INTO users (username, password_hash, full_name, prefs, created_at, must_change_password) VALUES (?,?,?,?,?,?)',
            (config.ADMIN_USERNAME, hash_password(config.ADMIN_PASSWORD), config.ADMIN_FULL_NAME, prefs, db.now(), int(config.ADMIN_MUST_CHANGE)))
        conn.execute('INSERT INTO user_roles (user_id, role) VALUES (?,?)', (cur.lastrowid, ADMIN))
