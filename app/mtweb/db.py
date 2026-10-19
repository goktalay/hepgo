"""mtweb veritabanı: HEPGO şemasının yalnız araç router'larının kullandığı tabloları + mtweb'e özgü tablolar.

users          — Mastertool hesabına (mt_id) karşılık yerel kullanıcı satırı; araç kodu `id`, `username`, `full_name` bekler
tools_mt_store — araç uygulamalarının kalıcı deposu (HEPGO şemasıyla aynı)
app_kv, audit_logs — tools_mt yardımcılarının dokunduğu HEPGO tabloları (aynı şema)
mtweb_audit    — denetim günlüğü (zaman, kullanıcı, uygulama, işlem, boyut, istemci IP; İÇERİK YAZILMAZ; 90 gün)
"""
import threading
import time

from app import db as core_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    mt_id      INTEGER NOT NULL UNIQUE,
    username   TEXT NOT NULL,
    full_name  TEXT,
    created_at TEXT NOT NULL,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS tools_mt_store (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app        TEXT NOT NULL,
    key        TEXT NOT NULL,
    json       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, app, key)
);
CREATE TABLE IF NOT EXISTS app_kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS audit_logs (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action    TEXT NOT NULL,
    entity    TEXT,
    entity_id TEXT,
    detail    TEXT,
    at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mtweb_audit (
    id      INTEGER PRIMARY KEY,
    at      REAL NOT NULL,
    user_id INTEGER,
    app     TEXT,
    action  TEXT NOT NULL,
    size    INTEGER,
    ip      TEXT,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS mtweb_audit_at ON mtweb_audit(at);
"""
_lock = threading.Lock()
_last_purge = [0.0]


def connect():
    return core_db.connect()


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    purge(force=True)


def user_for(mt_user):
    """Hesap servisi kullanıcısı → yerel users satırı (yoksa oluşturulur; ad/e-posta güncellenir)."""
    now = core_db.now()
    with _lock, connect() as conn:
        r = conn.execute('SELECT * FROM users WHERE mt_id = ?', (mt_user['id'],)).fetchone()
        if r is None:
            conn.execute('INSERT INTO users (mt_id, username, full_name, created_at, last_seen) VALUES (?,?,?,?,?)',
                         (mt_user['id'], mt_user['email'], mt_user['name'], now, now))
        else:
            conn.execute('UPDATE users SET username = ?, full_name = ?, last_seen = ? WHERE id = ?', (mt_user['email'], mt_user['name'], now, r['id']))
        conn.commit()
        r = conn.execute('SELECT * FROM users WHERE mt_id = ?', (mt_user['id'],)).fetchone()
    return {'id': r['id'], 'mt_id': r['mt_id'], 'username': r['username'], 'email': r['username'], 'full_name': r['full_name'] or r['username'],
            'roles': [], 'modules': ['tools']}


def audit(user_id, app, action, size=None, ip=None, detail=None):
    """Denetim kaydı. `detail` yalnız teknik özet (yol, kod) — dosya içeriği / parola ASLA."""
    try:
        with connect() as conn:
            conn.execute('INSERT INTO mtweb_audit (at, user_id, app, action, size, ip, detail) VALUES (?,?,?,?,?,?,?)',
                         (time.time(), user_id, app, str(action)[:80], size, (ip or '')[:64], (detail or '')[:300] or None))
            conn.commit()
    except Exception:   # noqa: BLE001 — denetim hatası isteği düşürmez
        pass
    purge()


def purge(force=False):
    from . import config
    t = time.time()
    if not force and t - _last_purge[0] < 3600:
        return
    _last_purge[0] = t
    try:
        with connect() as conn:
            conn.execute('DELETE FROM mtweb_audit WHERE at < ?', (t - config.AUDIT_DAYS * 86400,))
            conn.commit()
    except Exception:   # noqa: BLE001
        pass
