"""CAYSIM istemci çekirdeği (sözleşme docs/caysim-api.md): istemci kayıtları (`drone_sim_clients`), Bearer anahtarı (şifreli saklanır,
sabit-zamanlı karşılaştırma), IP başına başarısız kimlik hız sınırı (köprüdeki gibi 10/60 sn), çevrimiçi WS sayacı, istemci sahibinin
kullanıcı nesnesi (modül izinleri; kayıttan oynatma logu yetkisi için).

CAYSIM kendi fiziğini çalıştırmaz: SITL/telemetri/komut HEPGO'da (app/flightsim.py); bu modül yalnız kimlik + kayıt katmanıdır.
"""
import hmac
import secrets
import time

from . import auth, cameras, db

RATE_WINDOW, RATE_MAX = 60, 10        # IP başına başarısız kimlik denemesi (sn, adet) → 429 / 4429
CEVRIMICI_SN = 90                     # last_seen bu kadar yeniyse durum CEVRIMICI sayılır
PLATFORMS = ('windows', 'linux', 'macos', 'other')
HOST_MAX, VER_MAX = 120, 40
CAPS = ('sessions', 'cmd', 'rc', 'tele50', 'models', 'terrain', 'osm', 'replay', 'mavlink_udp')

_fails = {}          # ip → [zaman damgası…]
WS_ACIK = {}         # client_id → {ws, …}: açık CAYSIM WebSocket'leri (rekey/sil → 4403 ile kapatılır; `online` bayrağı)


class KimlikHata(Exception):
    """kod: 'auth' (401) · 'client_inactive' (403) · 'rate_limited' (429)"""
    def __init__(self, kod):
        super().__init__(kod)
        self.kod = kod


# ---------------- hız sınırı ----------------
def rate_limited(ip):
    now = time.time()
    lst = [t for t in _fails.get(ip or '', []) if now - t < RATE_WINDOW]
    _fails[ip or ''] = lst
    return len(lst) >= RATE_MAX


def note_fail(ip):
    _fails.setdefault(ip or '', []).append(time.time())


# ---------------- anahtar ----------------
def issue_key(conn, cid):
    """Yeni kalıcı anahtar: şifreli saklar, DÜZ metni döndürür (yalnız bir kez gösterilir); eski anahtar anında geçersiz."""
    key = secrets.token_urlsafe(32)
    conn.execute('UPDATE drone_sim_clients SET key_enc = ?, updated_at = ? WHERE id = ?', (cameras.encrypt(key), db.now(), cid))
    return key


def resolve_key(key, ip=None):
    """Bearer anahtarı → istemci satırı {id, name, owner_id, active}. Tüm satırlar sabit-zamanlı karşılaştırılır (zamanlama sızıntısı yok).
    Eşleşme yok → KimlikHata('auth'); pasif → KimlikHata('client_inactive'); sınır → KimlikHata('rate_limited'). Başarısızlık IP'ye yazılır."""
    if rate_limited(ip):
        raise KimlikHata('rate_limited')
    bulunan = None
    if key and isinstance(key, str) and len(key) <= 128:
        with db.connect() as conn:
            rows = db.rows(conn.execute('SELECT id, name, owner_id, created_by, active, key_enc FROM drone_sim_clients WHERE key_enc IS NOT NULL'))
        for r in rows:
            try:
                if hmac.compare_digest(cameras.decrypt(r.pop('key_enc')), key) and bulunan is None:
                    bulunan = r
            except Exception:   # noqa: BLE001
                continue
    if bulunan is None:
        note_fail(ip)
        raise KimlikHata('auth')
    if not bulunan.get('active'):
        note_fail(ip)
        raise KimlikHata('client_inactive')
    return bulunan


def bearer(headers):
    """`Authorization: Bearer <key>` → key (yoksa None)."""
    v = (headers.get('authorization') or '').strip()
    if v[:7].lower() != 'bearer ':
        return None
    return v[7:].strip() or None


# ---------------- kayıt ----------------
def _kirp(s, n):
    s = (s or '').strip() if isinstance(s, str) else ''
    return s[:n] or None


def gorulme(conn, cid, host=None, ver=None, platform=None):
    """hello / WS açılışı: last_seen, status CEVRIMICI; istemci bildirdiyse host / client_ver / platform güncellenir."""
    sets, args = ['status = ?', 'last_seen = ?'], ['CEVRIMICI', db.now()]
    if _kirp(host, HOST_MAX):
        sets.append('host = ?'); args.append(_kirp(host, HOST_MAX))
    if _kirp(ver, VER_MAX):
        sets.append('client_ver = ?'); args.append(_kirp(ver, VER_MAX))
    if platform in PLATFORMS:
        sets.append('platform = ?'); args.append(platform)
    args.append(cid)
    conn.execute(f"UPDATE drone_sim_clients SET {', '.join(sets)} WHERE id = ?", args)


def cevrimdisi(conn, cid):
    conn.execute("UPDATE drone_sim_clients SET status = 'CEVRIMDISI', last_seen = ? WHERE id = ?", (db.now(), cid))


def sahip(conn, row):
    """Oturum sahibi {id, name}: istemci kaydının owner_id'si (yoksa oluşturan; o da yoksa istemci adı)."""
    for uid in (row.get('owner_id'), row.get('created_by')):
        if uid:
            u = conn.execute('SELECT id, full_name FROM users WHERE id = ?', (uid,)).fetchone()
            if u:
                return {'id': u[0], 'name': u[1]}
    return {'id': None, 'name': row.get('name')}


def sahip_kullanici(conn, row):
    """Sahibin yetki nesnesi (drone_hub._ws_user kalıbı: roles/modules/write_modules) — kayıttan oynatma log yetkisi için. Yoksa boş modüller."""
    bos = {'id': None, 'full_name': row.get('name'), 'modules': [], 'write_modules': [], 'roles': [], 'master': False}
    uid = row.get('owner_id') or row.get('created_by')
    if not uid:
        return bos
    u = db.row(conn.execute('SELECT id, username, full_name, active FROM users WHERE id = ?', (uid,)))
    if not u or not u.get('active', 1):
        return bos
    from . import rbac
    real = auth.user_roles(conn, u['id'])
    u['master'] = auth.is_master(u['username'])
    if u['master']:
        u['roles'] = [*auth.ROLES, auth.MASTER]
        u['modules'] = [*dict.fromkeys([*auth.MODULE_ROLES.keys(), *rbac.node_keys()])]
        u['write_modules'] = list(u['modules'])
    else:
        u['roles'] = rbac.expand(real)
        u['modules'] = rbac.allowed(real)
        u['write_modules'] = rbac.writable(real)
    return u


def durum(r, now_ts=None):
    """Liste için türetilmiş durum: açık WS varsa ya da last_seen < CEVRIMICI_SN → CEVRIMICI."""
    if r['id'] in WS_ACIK and WS_ACIK[r['id']]:
        return 'CEVRIMICI'
    ls = r.get('last_seen')
    if ls:
        try:
            from datetime import datetime
            if (datetime.now() - datetime.fromisoformat(ls)).total_seconds() < CEVRIMICI_SN:
                return 'CEVRIMICI'
        except ValueError:
            pass
    return 'CEVRIMDISI'


def listele(conn):
    """Yönetim listesi: anahtar/kod ASLA dönmez (yalnız has_key); `sessions` = istemcinin açık oturum sayısı."""
    from . import flightsim
    rows = db.rows(conn.execute('''SELECT c.id, c.name, c.platform, c.owner_id, c.host, c.client_ver, c.status, c.last_seen, c.note, c.active,
                                          c.created_at, c.updated_at, c.key_enc IS NOT NULL AS has_key, u.full_name AS owner_name
                                   FROM drone_sim_clients c LEFT JOIN users u ON u.id = c.owner_id ORDER BY c.active DESC, c.name COLLATE NOCASE'''))
    acik = {}
    for s in flightsim.MANAGER.sessions.values():
        c = getattr(s, 'client', None)
        if c and s.state != 'KAPANDI':
            acik[c['id']] = acik.get(c['id'], 0) + 1
    for r in rows:
        r['has_key'] = bool(r['has_key'])
        r['online'] = bool(WS_ACIK.get(r['id']))
        r['status'] = durum(r)
        r['sessions'] = acik.get(r['id'], 0)
    return rows


# ---------------- açık WS'ler ----------------
def ws_ekle(cid, ws):
    WS_ACIK.setdefault(cid, set()).add(ws)


def ws_sil(cid, ws):
    s = WS_ACIK.get(cid)
    if s is not None:
        s.discard(ws)
        if not s:
            WS_ACIK.pop(cid, None)
    return bool(WS_ACIK.get(cid))


async def ws_kapat_hepsi(cid, code=4403):
    """rekey / sil: istemcinin açık tüm WebSocket'leri kapatılır (yeni anahtar gerekir)."""
    for ws in list(WS_ACIK.get(cid) or ()):
        try:
            await ws.close(code=code)
        except Exception:   # noqa: BLE001
            pass
    WS_ACIK.pop(cid, None)
