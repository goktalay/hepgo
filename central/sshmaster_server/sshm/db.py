"""SSH Master hesap veritabanı (data/sshm.db, stdlib sqlite3). Kütüphane blob'u uçtan uca şifrelidir: sunucu okuyamaz."""
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
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    blob TEXT NOT NULL,
    size INTEGER NOT NULL,
    device TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    setup_file TEXT NOT NULL,
    setup_size INTEGER NOT NULL,
    setup_sha256 TEXT NOT NULL,
    portable_file TEXT,
    portable_size INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    release_id INTEGER REFERENCES releases(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,                            -- setup | portable
    ip TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_downloads_user ON downloads(user_id);
"""


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
