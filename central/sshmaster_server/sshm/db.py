"""Mastertool hesap veritabanı (data/sshm.db, stdlib sqlite3): tek kullanıcı hesabı, uygulama bazında lisans / kütüphane / sürüm.
Uygulama kodları: sm = SSH Master, fm = FTP Masters. Kütüphane blob'u uçtan uca şifrelidir: sunucu okuyamaz.
Eski SSH Master şeması (uygulama sütunsuz) init() içinde yerinde taşınır; mevcut veriler sm'e bağlanır."""
import os
import sqlite3
import time

from . import settings

DB_PATH = settings.DATA_DIR / 'sshm.db'


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def connect():
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,                         -- auth_hash'in sunucu özeti (düz şifre sunucuya HİÇ gelmez)
    status TEXT NOT NULL DEFAULT 'BEKLIYOR',      -- BEKLIYOR (e-posta doğrulanmadı) | AKTIF | ASKIDA
    verified_at TEXT,
    kdf_salt TEXT NOT NULL,                        -- kütüphane şifreleme anahtarı için PBKDF2 tuzu (base64); şifre değişince yenilenir
    sync_enabled INTEGER NOT NULL DEFAULT 1,
    dl_token TEXT NOT NULL UNIQUE,                 -- kişiye özel indirme bağlantısı (/indir/<token>); yalnız aynı kullanıcı oturumuyla çalışır
    note TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,                            -- web | app
    app TEXT,                                      -- uygulama oturumunda sm | fm (web oturumunda NULL)
    device TEXT,
    app_version TEXT,
    ip TEXT,
    created_at TEXT NOT NULL,
    last_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS tokens (                -- e-posta doğrulama / şifre sıfırlama (tek kullanımlık, özet saklanır)
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                            -- verify | reset | newsalt (şifre değiştirme için sunucunun verdiği yeni tuz)
    token_hash TEXT NOT NULL UNIQUE,
    salt TEXT,                                     -- reset / newsalt: istemcinin yeni auth_hash'i türeteceği tuz
    expires REAL NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS libraries (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app TEXT NOT NULL DEFAULT 'sm',
    version INTEGER NOT NULL,
    blob TEXT NOT NULL,
    size INTEGER NOT NULL,
    device TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, app)
);
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    app TEXT NOT NULL DEFAULT 'sm',
    version TEXT NOT NULL,
    setup_file TEXT NOT NULL,
    setup_size INTEGER NOT NULL,
    setup_sha256 TEXT NOT NULL,
    portable_file TEXT,
    portable_size INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (app, version)
);
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    release_id INTEGER REFERENCES releases(id) ON DELETE SET NULL,
    app TEXT NOT NULL DEFAULT 'sm',
    kind TEXT NOT NULL,                            -- setup | portable
    ip TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_downloads_user ON downloads(user_id);
CREATE TABLE IF NOT EXISTS user_apps (             -- uygulama bazında lisans / yetki ve senkron tercihi
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app TEXT NOT NULL,                             -- sm | fm
    license TEXT NOT NULL DEFAULT 'AKTIF',         -- AKTIF | KAPALI (yönetici kapatır; uygulamaya giriş ve indirme kapanır)
    sync_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, app)
);
"""


def _cols(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}


def _migrate(conn):
    """SSH Master (v1) şemasından Mastertool şemasına: mevcut kütüphane / sürüm / indirme / oturum kayıtları sm'e bağlanır,
    kullanıcıların senkron tercihi user_apps(sm)'e taşınır. Tekrar çalıştırmak güvenlidir."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.execute('PRAGMA legacy_alter_table=ON')   # RENAME diğer tablolardaki FK başvurularını eski ada çevirmesin
    if 'libraries' in tables and 'app' not in _cols(conn, 'libraries'):
        conn.executescript("""ALTER TABLE libraries RENAME TO libraries_v1;
            CREATE TABLE libraries (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, app TEXT NOT NULL DEFAULT 'sm',
                version INTEGER NOT NULL, blob TEXT NOT NULL, size INTEGER NOT NULL, device TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, app));
            INSERT INTO libraries (user_id, app, version, blob, size, device, updated_at)
                SELECT user_id, 'sm', version, blob, size, device, updated_at FROM libraries_v1;
            DROP TABLE libraries_v1;""")
    if 'releases' in tables and 'app' not in _cols(conn, 'releases'):
        conn.execute('PRAGMA foreign_keys=OFF')   # downloads.release_id kimlikleri korunur (id aynen kopyalanır)
        conn.executescript("""ALTER TABLE releases RENAME TO releases_v1;
            CREATE TABLE releases (id INTEGER PRIMARY KEY, app TEXT NOT NULL DEFAULT 'sm', version TEXT NOT NULL, setup_file TEXT NOT NULL,
                setup_size INTEGER NOT NULL, setup_sha256 TEXT NOT NULL, portable_file TEXT, portable_size INTEGER, notes TEXT,
                created_at TEXT NOT NULL, UNIQUE (app, version));
            INSERT INTO releases (id, app, version, setup_file, setup_size, setup_sha256, portable_file, portable_size, notes, created_at)
                SELECT id, 'sm', version, setup_file, setup_size, setup_sha256, portable_file, portable_size, notes, created_at FROM releases_v1;
            DROP TABLE releases_v1;""")
        conn.execute('PRAGMA foreign_keys=ON')
    if 'sessions' in tables and 'app' not in _cols(conn, 'sessions'):
        conn.execute('ALTER TABLE sessions ADD COLUMN app TEXT')
        conn.execute("UPDATE sessions SET app = 'sm' WHERE kind = 'app'")
    if 'downloads' in tables and 'app' not in _cols(conn, 'downloads'):
        conn.execute("ALTER TABLE downloads ADD COLUMN app TEXT NOT NULL DEFAULT 'sm'")
    conn.execute('PRAGMA legacy_alter_table=OFF')


def init():
    with connect() as conn:
        _migrate(conn)
        conn.executescript(SCHEMA)
        # v1 kullanıcıları: SSH Master lisansı ve mevcut senkron tercihi (yalnız eksik satırlar)
        conn.execute("""INSERT OR IGNORE INTO user_apps (user_id, app, license, sync_enabled, created_at)
                        SELECT id, 'sm', 'AKTIF', sync_enabled, created_at FROM users""")
        conn.commit()
