"""Sistem geneli güvenlik / şifre kuralları (Program Ayarları → Güvenlik).

Tek JSON olarak app_kv['security.policy'] içinde saklanır; varsayılanlarla birleştirilir. Şifre değiştirme, giriş,
oturum süresi, kaba kuvvet kilidi ve PIN kuralları bu değerlere göre uygulanır. Yalnızca sistem yöneticisi / MASTER düzenler.
"""
import json
import re

from . import db

KEY = 'security.policy'

DEFAULTS = {
    'min_length': 8,           # en az karakter
    'require_upper': False,    # büyük harf zorunlu
    'require_lower': False,    # küçük harf zorunlu
    'require_digit': False,    # rakam zorunlu
    'require_symbol': False,   # özel karakter zorunlu
    'disallow_username': True, # şifre kullanıcı adını içeremez
    'disallow_common': True,   # yaygın şifreler yasak
    'expire_days': 0,          # şifre geçerlilik süresi (gün); 0 = süresiz
    'reuse_block': 0,          # son N şifre yeniden kullanılamaz; 0 = kapalı
    'force_first_change': True,# yöneticinin verdiği şifreyle ilk girişte değiştirme zorunlu
    'lockout_fails': 5,        # aynı kullanıcıya art arda hatalı deneme sınırı
    'ip_fails': 20,            # aynı IP'den hatalı deneme sınırı
    'lockout_minutes': 15,     # kilit süresi (dakika)
    'session_hours': 12,       # oturum geçerlilik süresi (saat)
    'pin_enabled': True,       # PIN ile girişe izin ver
    'pin_length': 4,           # PIN hane sayısı
}

COMMON = {'12345678', '123456789', '1234567890', 'password', 'password1', 'parola', 'parola1', 'sifre', 'sifre123',
          '12345', '123456', '1234', 'qwerty', 'qwerty123', 'qwe123', '111111', '000000', 'admin', 'admin123',
          'deneme', 'deneme123', 'abc123', '1q2w3e4r', 'asdasd', '123123', 'gokkubbe', 'caymaz'}

_INT = {'min_length': (4, 64), 'expire_days': (0, 3650), 'reuse_block': (0, 24), 'lockout_fails': (3, 100),
        'ip_fails': (5, 500), 'lockout_minutes': (1, 1440), 'session_hours': (1, 720), 'pin_length': (4, 8)}


def get(conn):
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (KEY,)).fetchone()
    data = {}
    if row and row[0]:
        try:
            data = json.loads(row[0])
        except Exception:
            data = {}
    return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}


def save(conn, data):
    clean = {}
    for k, dv in DEFAULTS.items():
        v = data.get(k, dv)
        if isinstance(dv, bool):
            clean[k] = bool(v)
        else:
            lo, hi = _INT[k]
            try:
                clean[k] = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                clean[k] = dv
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (KEY, json.dumps(clean)))
    return clean


def validate_password(policy, pw, username=None):
    """Kurallara uymuyorsa ValueError(Türkçe mesaj) fırlatır."""
    pw = pw or ''
    if len(pw) < policy['min_length']:
        raise ValueError(f"Şifre en az {policy['min_length']} karakter olmalı")
    if policy['require_upper'] and not re.search(r'[A-ZÇĞİÖŞÜ]', pw):
        raise ValueError('Şifre en az bir büyük harf içermeli')
    if policy['require_lower'] and not re.search(r'[a-zçğıiöşü]', pw):
        raise ValueError('Şifre en az bir küçük harf içermeli')
    if policy['require_digit'] and not re.search(r'\d', pw):
        raise ValueError('Şifre en az bir rakam içermeli')
    if policy['require_symbol'] and not re.search(r'[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]', pw):
        raise ValueError('Şifre en az bir özel karakter (!, ?, *, . vb.) içermeli')
    if policy['disallow_username'] and username:
        u = username.split('@')[0].strip().lower()
        if len(u) >= 3 and u in pw.lower():
            raise ValueError('Şifre kullanıcı adınızı içeremez')
    if policy['disallow_common'] and pw.lower() in COMMON:
        raise ValueError('Bu şifre çok yaygın; daha güçlü bir şifre seçin')


def record_history(conn, uid, password_hash):
    """Şifre geçmişine ekler (yeniden kullanım engeli için) ve şifre değişim zamanını günceller."""
    now = db.now()
    conn.execute('INSERT INTO password_history (user_id, password_hash, at) VALUES (?,?,?)', (uid, password_hash, now))
    conn.execute('UPDATE users SET password_changed_at = ? WHERE id = ?', (now, uid))
    # Geçmişi makul boyutta tut (son 24)
    conn.execute('''DELETE FROM password_history WHERE user_id = ? AND id NOT IN
                    (SELECT id FROM password_history WHERE user_id = ? ORDER BY id DESC LIMIT 24)''', (uid, uid))


def recent_hashes(conn, uid, n):
    if n <= 0:
        return []
    return [r[0] for r in conn.execute(
        'SELECT password_hash FROM password_history WHERE user_id = ? ORDER BY id DESC LIMIT ?', (uid, n))]
