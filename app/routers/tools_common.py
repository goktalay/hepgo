"""Araçlar › Master Tool web sürümleri — ortak yardımcılar.

Yetki: Araçlar modülü (auth.require_module('tools')). WebSocket uçları oturum çerezini doğrular (ws_user).
Bağlantı bilgileri (sunucu/kullanıcı/parola) yalnız süreç belleğinde tutulur; veritabanına PAROLA YAZILMAZ.
Geçici dosyalar DATA_DIR/tools/tmp altında saklanır ve 1 saat sonra silinir.
"""
import asyncio
import re
import secrets
import socket
import time
from pathlib import Path

from .. import auth, config

tools_user = auth.require_module('tools')
BRAND = 'HEPGO'   # arayüzde görünen alan etiketi (mtweb: 'Mastertool')

# --- mtweb kancaları (app/mtweb; HEPGO'da hepsi None → davranış değişmez: firmalar LAN cihazlarına bağlanabilir) -------
# NET_GUARD(host, port, uid, app, kind) → doğrulanmış IP (str). Her dış bağlantı (SSH/SFTP/FTP/SQL/SSH tüneli) açılmadan
#   önce çağrılır; bağlantı bu IP'ye yapılır (DNS yeniden bağlama yok). kind: 'connect' (oran sınırı + denetim kaydı) |
#   'data' (FTP veri kanalı / tünel hedefi: yalnız adres + port denetimi). Reddederse NetDenied.
# CONN_GATE(uid, app) → release(); kullanıcı/genel eşzamanlı oturum sınırı aşılırsa NetDenied.
# WS_USER(ws) → kullanıcı | None (async); WebSocket kimliği (mtweb: Mastertool oturumu).
NET_GUARD = None
CONN_GATE = None
WS_USER = None


class NetDenied(Exception):
    """Dış bağlantı politikası reddi (mtweb). Mesaj arayüze olduğu gibi gider."""


def net_target(host, port, uid=None, app=None, kind='connect'):
    """Bağlanılacak adres: kanca yoksa host aynen (HEPGO), varsa doğrulanmış IP."""
    if NET_GUARD is None:
        return host
    return NET_GUARD(host, int(port), uid, app, kind)


def net_socket(host, port, timeout, uid=None, app=None):
    """Kanca varsa doğrulanmış IP'ye bağlı TCP soketi; kanca yoksa None (çağıran kendi yolunu kullanır)."""
    if NET_GUARD is None:
        return None
    ip = NET_GUARD(host, int(port), uid, app, 'connect')
    return socket.create_connection((ip, int(port)), timeout=timeout)


def _noop():
    return None


def conn_slot(uid, app):
    """Eşzamanlı oturum yeri: release() döner (HEPGO'da sınır yok)."""
    return CONN_GATE(uid, app) if CONN_GATE else _noop

TOOLS_DIR = config.DATA_DIR / 'tools'
TMP_DIR = TOOLS_DIR / 'tmp'
TMP_TTL = 3600   # geçici dosya ömrü (sn)
_last_sweep = [0.0]

HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.\-:\[\]_]{0,252}$')   # alan adı / IPv4 / IPv6 — başta '-' yok (ssh seçeneği sanılmasın)
USER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-@]{0,63}$')


def _ws_lookup(token):
    from ..drone_hub import _ws_user   # oturum çerezi → kullanıcı + roller + modül izinleri (/ws/drone/live kalıbı)
    u = _ws_user(token)
    return u if u and 'tools' in u.get('modules', []) else None


async def ws_user(ws):
    """WebSocket için oturum çerezinden kullanıcı; Araçlar modülü yetkisi yoksa None."""
    if WS_USER is not None:
        return await WS_USER(ws)
    return await asyncio.to_thread(_ws_lookup, ws.cookies.get(auth.COOKIE))


def check_host(host: str) -> str:
    host = (host or '').strip()
    if not HOST_RE.match(host):
        raise ValueError('Geçersiz sunucu adresi')
    return host


def check_port(port) -> int:
    try:
        p = int(port)
    except (TypeError, ValueError):
        raise ValueError('Geçersiz port') from None
    if not (1 <= p <= 65535):
        raise ValueError('Geçersiz port')
    return p


def check_user(name: str) -> str:
    name = (name or '').strip()
    if not USER_RE.match(name):
        raise ValueError('Geçersiz kullanıcı adı')
    return name


def safe_name(name: str, default='dosya') -> str:
    """Dosya adı: dizin ayracı/kontrol karakteri yok, gizli dosya yok, en çok 120 karakter."""
    name = (name or '').replace('\\', '/').split('/')[-1].strip()
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).lstrip('.')
    return (name or default)[:120]


def user_dir(kind: str, uid: int) -> Path:
    p = TOOLS_DIR / kind / str(int(uid))
    p.mkdir(parents=True, exist_ok=True)
    return p


def sweep_tmp(force=False):
    """1 saatten eski geçici dosyaları siler (en çok dakikada bir tarar)."""
    now = time.time()
    if not force and now - _last_sweep[0] < 60:
        return
    _last_sweep[0] = now
    if not TMP_DIR.exists():
        return
    for p in TMP_DIR.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > TMP_TTL:
                p.unlink()
        except OSError:
            pass


def new_tmp(name: str) -> tuple[str, Path]:
    """Geçici çıktı dosyası: (indirme jetonu, yol). Jeton = rastgele + güvenli ad."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    sweep_tmp()
    token = f'{secrets.token_urlsafe(12)}__{safe_name(name)}'
    return token, TMP_DIR / token


def tmp_path(token: str) -> Path:
    """İndirme jetonu → dosya yolu; yoksa/eskiyse None."""
    token = safe_name(token, '')
    if not token or '__' not in token:
        return None
    p = TMP_DIR / token
    if not p.is_file() or time.time() - p.stat().st_mtime > TMP_TTL:
        return None
    return p
