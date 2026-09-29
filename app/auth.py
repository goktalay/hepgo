import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request

from . import config, db

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

ROLES = [ADMIN, WAREHOUSE_MANAGER, PRODUCTION_MANAGER, PRODUCTION_LEAD, PRINTER_MAINTAINER,
         FIELD_LEAD, FIELD_STAFF, DRIVER, PILOT, ASSEMBLER, ELECTRONICS, ADMIN_STAFF, SECRETARY, SECURITY]

# Modül → girebilen roller (yetki matrisi, 2026-09-25; Sistem Yöneticisi tüm modüllerde). Her rol yalnızca
# burada listelendiği modüllere girer; birden fazla rolü olan kullanıcı rollerinin birleşimini görür.
MODULE_ROLES = {
    'admin':      [ADMIN],                                                                    # M1 Yönetim
    'production': [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD, ASSEMBLER, ELECTRONICS],       # M2 Üretim
    'orders':     [ADMIN, PRODUCTION_MANAGER],                                                # M3 Sipariş
    'warehouse':  [ADMIN, WAREHOUSE_MANAGER],                                                 # M4 Depo
    'stock':      [ADMIN, WAREHOUSE_MANAGER, PRODUCTION_MANAGER, PRODUCTION_LEAD, FIELD_LEAD,
                   FIELD_STAFF, PILOT],                                                       # M5 Stok
    'field':      [ADMIN, FIELD_LEAD, FIELD_STAFF, DRIVER, PILOT],                            # M6 Saha
    'printers':   [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD, PRINTER_MAINTAINER],           # M7 Yazıcı
    'products':   [ADMIN],                                                                    # M8 Ürün
    'tools':      [r for r in ROLES if r != SECURITY],                                        # M9 Araçlar
    'users':      [ADMIN],                                                                    # M10 Kullanıcı
    'companies':  [ADMIN, ADMIN_STAFF],                                                       # M11 Firma
    'documents':  [ADMIN, ADMIN_STAFF],                                                       # M12 Evrak
    'secretariat': [ADMIN, SECRETARY],                                                        # M13 Sekreterya
    'security':   [ADMIN, SECURITY],                                                          # M14 Güvenlik
    'reports':    [r for r in ROLES if r != SECURITY],                                        # M15 Raporlar (içerik modül yetkisine göre)
    'announcements': list(ROLES),                                                             # M16 Duyurular (yazan: Sistem Yöneticisi)
}
# Modül içinde değişiklik yapabilen roller (okuma MODULE_ROLES ile).
# Montaj Personeli (2026-09-26) Üretim'e montaj/kalibrasyon, Elektronik Personeli elektronik kat montajı için
# girer; ikisi de parça üretim işlemlerini yapamaz.
PART_OPERATORS = [ADMIN, PRODUCTION_MANAGER, PRODUCTION_LEAD]
FIELD_MANAGERS = [ADMIN, FIELD_LEAD]

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


def allowed_modules(roles):
    return [m for m, rs in MODULE_ROLES.items() if set(rs) & set(roles)]


def create_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    conn.execute('INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)',
                 (token, user_id, now.isoformat(timespec='seconds'),
                  (now + timedelta(hours=config.SESSION_HOURS)).isoformat(timespec='seconds')))
    return token


def current_user(request: Request, conn=db.DB):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Oturum açılmamış')
    user = db.row(conn.execute(
        '''SELECT u.id, u.username, u.full_name, u.photo, u.active, u.last_seen, u.prefs, s.expires_at
           FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?''', (token,)))
    now = db.now()
    if not user or user['expires_at'] < now or not user['active']:
        raise HTTPException(401, 'Oturum süresi doldu')
    # Çevrimiçi takibi: son etkinlik zamanı (yazma yükü için en fazla 20 sn'de bir güncellenir)
    if not user['last_seen'] or (datetime.fromisoformat(now) - datetime.fromisoformat(user['last_seen'])).total_seconds() > 20:
        conn.execute('UPDATE users SET last_seen = ? WHERE id = ?', (now, user['id']))
        conn.commit()   # yazma kilidini isteğin sonuna kadar tutma
    user['roles'] = user_roles(conn, user['id'])
    user['modules'] = allowed_modules(user['roles'])
    return user


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
            'INSERT INTO users (username, password_hash, full_name, created_at) VALUES (?,?,?,?)',
            (config.ADMIN_USERNAME, hash_password(config.ADMIN_PASSWORD), config.ADMIN_FULL_NAME, db.now()))
        conn.execute('INSERT INTO user_roles (user_id, role) VALUES (?,?)', (cur.lastrowid, ADMIN))
