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
MASTER = 'MASTER'          # sistem sahibi (owner); ROLES'e eklenmez, atanamaz; yalnızca config.MASTER_USERNAMES
MRP_LEAD = 'MRP Sorumlusu'   # Malzeme İhtiyaç Planlaması: malzemeler, depolar, stok hareketleri, yarı mamul stoğu
PURCHASING = 'Satın Alma'   # tedarikçiler, satın alma talepleri, fatura / irsaliye (depo girişi), teklifler
SALES = 'Satış'   # Satış Yönetimi: firmalar için satış faturası oluşturma
HR = 'İnsan Kaynakları'   # personel kayıtları, iş başvuruları, özlük dosyaları, sözleşmeler, izin onayı
INTERN = 'Stajer'       # hiçbir modüle yetkili değil; genel yapıyı (pano, Kişisel, mesaj, duyurular) kullanır
CLEANER = 'Temizlik Görevlisi'   # yalnızca Temizlik modülü (günlük temizlik çeklisti)
DESIGNER = 'Endüstriyel Tasarımcı'   # Endüstriyel Tasarım modülü: proje + çizim / montaj çizimi + sürüm geçmişi

ROLES = [ADMIN, WAREHOUSE_MANAGER, PRODUCTION_MANAGER, PRODUCTION_LEAD, PRINTER_MAINTAINER,
         FIELD_LEAD, FIELD_STAFF, DRIVER, PILOT, ASSEMBLER, ELECTRONICS, ADMIN_STAFF, SECRETARY, SECURITY, HR, PURCHASING, SALES, MRP_LEAD, DESIGNER, CLEANER, INTERN]
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
    'tools':      [r for r in ROLES if r not in (SECURITY, INTERN, CLEANER)],                 # M9 Araçlar
    'users':      [ADMIN],                                                                    # M10 Kullanıcı
    'companies':  [ADMIN, ADMIN_STAFF],                                                       # M11 Firma
    'documents':  [ADMIN, ADMIN_STAFF],                                                       # M12 Evrak
    'secretariat': [ADMIN, SECRETARY],                                                        # M13 Sekreterya
    'security':   [ADMIN, SECURITY],                                                          # M14 Güvenlik
    'hr':         [ADMIN, HR],                                                                # M17 İnsan Kaynakları
    'purchasing': [ADMIN, PURCHASING],                                                        # M19 Satın Alma
    'sales':      [ADMIN, SALES],                                                             # M21 Satış Yönetimi
    'reports':    [r for r in ROLES if r not in (SECURITY, INTERN, CLEANER)],                 # M15 Raporlar (içerik modül yetkisine göre)
    'announcements': list(ROLES),                                                             # M16 Duyurular (yazan: Sistem Yöneticisi)
    'cleaning':   [ADMIN, CLEANER],                                                           # M22 Temizlik (günlük çeklist)
    'design':     [ADMIN, DESIGNER],                                                          # M23 Endüstriyel Tasarım (proje + çizim + sürüm)
}
# M18 Malzeme İhtiyaç Planlaması: Yarı Mamül (stock) ve Onay Yönetimi (warehouse) alt modüllerini görenler
MODULE_ROLES['mrp'] = sorted(set(MODULE_ROLES['stock']) | set(MODULE_ROLES['warehouse']), key=ROLES.index)
MODULE_ROLES['mikro'] = []   # M20 Mikro ERP: YALNIZCA MASTER (sistem sahibi). Hiçbir role verilmez; master tüm modülleri MODULE_ROLES.keys()'ten alır.
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
    return [m for m, rs in MODULE_ROLES.items() if set(rs) & set(roles)]


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
        '''SELECT u.id, u.username, u.full_name, u.photo, u.active, u.last_seen, u.prefs, u.must_change_password, s.expires_at
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
    # İzinli / raporlu personelin açık oturumu da kapanır (sistem sahibi hariç); sonuç 60 sn önbellekte
    if not user['master']:
        import time as _t
        hit = _absence_cache.get(user['id'])
        if not hit or _t.monotonic() - hit[0] > 60:
            hit = (_t.monotonic(), absence(conn, user['id']))
            _absence_cache[user['id']] = hit
        if hit[1]:
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            raise HTTPException(401, absence_message(hit[1]))
    if user['master']:   # sistem sahibi: her şeye erişir (rol iptal edilse bile) ama role bağlı bildirim/katılım gerçek rollerine göre
        user['real_roles'] = real
        user['roles'] = [*ROLES, MASTER]
        user['modules'] = [*MODULE_ROLES.keys(), 'master']
    else:
        user['real_roles'] = real
        user['roles'] = real
        user['modules'] = allowed_modules(real)
    # Mikro ERP bu tenant'ta tanımlı değilse (ör. Türkbey) modülü hiç gösterme — boş ekran / yanlış firma verisi olmasın.
    if 'mikro' in user['modules'] and not (config.MIKRO_HOST and config.MIKRO_DB and config.MIKRO_USER and config.MIKRO_PASSWORD):
        user['modules'] = [m for m in user['modules'] if m != 'mikro']
    # Merkez (Veilox) bu firmaya belirli modülleri verdiyse, herkes (master dâhil) yalnızca o modülleri görür.
    # 'master' modülü (sistem sahibi aracı) her zaman kalır; CAYMAZ_MODULES tanımsızsa kısıtlama yoktur.
    if config.MODULES is not None:
        allow = set(config.MODULES) | {'master'}
        user['modules'] = [m for m in user['modules'] if m in allow]
    return user


PASSWORD_FREE_PATHS = {'/api/auth/me', '/api/auth/password', '/api/auth/logout', '/api/system/status', '/api/activity'}


def require_module(module):
    def dep(user=Depends(current_user)):
        if module not in user['modules']:
            raise HTTPException(403, 'Bu modüle erişim yetkiniz yok')
        return user
    return dep


def require_roles(*roles):
    def dep(user=Depends(current_user)):
        if not set(roles) & set(user['roles']):
            raise HTTPException(403, 'Bu işlem için yetkiniz yok')
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
        cur = conn.execute(
            'INSERT INTO users (username, password_hash, full_name, created_at, must_change_password) VALUES (?,?,?,?,?)',
            (config.ADMIN_USERNAME, hash_password(config.ADMIN_PASSWORD), config.ADMIN_FULL_NAME, db.now(), 1))
        conn.execute('INSERT INTO user_roles (user_id, role) VALUES (?,?)', (cur.lastrowid, ADMIN))
