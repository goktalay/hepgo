"""Araçlar › Master Tool web köprüsü — ortak arka uç (SSH Master · FTP Masters · SQL Master · Notepad Master · Convert Master).

İki köprü biçimi tek dosyada:
1) SSH Master + FTP Masters (IPC kanalı kalıbı): masaüstü ana sürecin (main.js) karşılığı — kalıcı depo, bağlantı/klasör/
   kısayol/ayar işlemleri, yerel dosya yöneticisi. preload.js'in IPC kanalları aynı adla
   POST /api/tools/mt/<app>/invoke {m: '<kanal>', a: <arg>} üzerinden çağrılır (dönüş {ok, v, store?}); açılış GET /<app>/boot.
   "Bilgisayarım" paneli: kullanıcının HEPGO'daki kişisel alanı DATA_DIR/tools/files/<uid>; arayüze Windows yolu gibi sanal
   sürücü H:\\ ile sunulur (renderer'lar Windows yol mantığıyla çalışır); /<app>/files/upload|download.
   Sunucudan arayüze giden metinler {$t: 'i18n anahtarı', $p: {...}} nesneleridir; renderer kendi i18n.js sözlüğüyle çevirir.
2) SQL / Notepad / Convert Master (anahtar-değer + dosya alanı kalıbı): tools_sql.py / tools_notepad.py / tools_convert.py
   buradaki kv_get/kv_set, protect/unprotect, app_dir/files_root/resolve/list_dir yardımcılarını kullanır. HTTP uçları:
   GET /account (masaüstündeki account:state karşılığı) ve /<app>/fs/list|mkdir|upload|download|delete|rename|usage
   (kullanıcının "yerel" alanı DATA_DIR/tools/<app>/<uid>/files — Electron'daki dosya diyaloglarının karşılığı).

Depo: tools_mt_store(user_id, app, key, json) — masaüstü store.json/secrets.json/history ile AYNI JSON şeması
(key='store' → folders, connections|projects, settings, …; 'secrets', 'history'). Şifreler masaüstünde safeStorage ile
'enc:' önekiyle saklanırdı; burada aynı önekle Fernet kullanılır. TEK anahtar kaynağı: DATA_DIR/tools/mt_secret.key (0600);
eski app_kv.tools_mt_fernet kaydı varsa dosya yokken ona taşınır. Şifre hiçbir zaman arayüze gönderilmez (hasPassword…).
"""
import asyncio
import base64
import json
import re
import secrets
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, db
from .tools_common import TOOLS_DIR, safe_name, tools_user

router = APIRouter(prefix='/api/tools/mt')
IPC_APPS = ('sshmaster', 'ftpmaster')                       # boot/invoke/files (IPC kanalı kalıbı)
KV_APPS = ('sqlmaster', 'notepadmaster', 'convertmaster')   # kv + fs kalıbı
APPS = IPC_APPS + KV_APPS
VERSION = 'HEPGO web'
MAX_UPLOAD = 512 * 1024 * 1024
_kv_lock = threading.Lock()
LANGS = ('tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru')
DRIVE = 'H:\\'                 # sanal sürücü: kullanıcının HEPGO kişisel alanı
FILES_DIR = TOOLS_DIR / 'files'
UPLOAD_GUARD = None    # mtweb kancası: callable(uid, app) → denetleyici(eklenen_bayt, yeni_dosya) (kota; HEPGO'da yok)
_locks = defaultdict(threading.Lock)   # (uid, app) → depo kilidi (oku-değiştir-yaz)


def T(key, **p):
    """Arayüzde çevrilecek metin (renderer i18n.js anahtarı)."""
    return {'$t': key, '$p': p} if p else {'$t': key}


class MtError(Exception):
    """Arayüze mesaj olarak dönecek hata; msg metin ya da T(...) nesnesi."""
    def __init__(self, msg):
        super().__init__(str(msg))
        self.msg = msg


# ---------------------------------------------------------------------------
# Şifreleme (Fernet) — masaüstündeki safeStorage karşılığı, aynı 'enc:' öneki
# ---------------------------------------------------------------------------
_fernet = [None]


def _legacy_kv_key():
    """Önceki sürümün app_kv.tools_mt_fernet kaydı (varsa) — dosyaya taşınır ki eski 'enc:' değerler açılabilsin."""
    try:
        with db.connect() as conn:
            r = conn.execute("SELECT v FROM app_kv WHERE k = 'tools_mt_fernet'").fetchone()
        return r[0].strip().encode('ascii') if r and r[0] else None
    except Exception:   # noqa: BLE001 — tablo yok / DB kapalı
        return None


def fernet():
    """Tek anahtar kaynağı: DATA_DIR/tools/mt_secret.key. Dosya varsa o; yoksa app_kv'deki eski anahtar; o da yoksa yeni üretilir."""
    if _fernet[0] is None:
        from cryptography.fernet import Fernet
        p = TOOLS_DIR / 'mt_secret.key'
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(_legacy_kv_key() or Fernet.generate_key())
            p.chmod(0o600)
        _fernet[0] = Fernet(p.read_bytes().strip())
    return _fernet[0]


def encrypt(text) -> str:
    if not text:
        return ''
    return 'enc:' + fernet().encrypt(str(text).encode('utf-8')).decode('ascii')


def decrypt(value) -> str:
    if not value:
        return ''
    try:
        if value.startswith('enc:'):
            return fernet().decrypt(value[4:].encode('ascii')).decode('utf-8')
        if value.startswith('b64:'):
            return base64.b64decode(value[4:]).decode('utf-8')
    except Exception:   # noqa: BLE001 — anahtar değişmiş/bozuk kayıt: boş şifre
        return ''
    return value


# SQL/Notepad/Convert tarafının adları (aynı Fernet, aynı 'enc:' öneki)
protect = encrypt
unprotect = decrypt


# ---------------------------------------------------------------------------
# Anahtar-değer deposu (SQL/Notepad/Convert: key = store | secrets | history …; JSON şeması masaüstüyle aynı)
# ---------------------------------------------------------------------------
def check_app(app: str) -> str:
    if app not in APPS:
        raise HTTPException(404, 'Bilinmeyen uygulama')
    return app


def kv_get(uid: int, app: str, key: str, default=None):
    with db.connect() as conn:
        r = conn.execute('SELECT json FROM tools_mt_store WHERE user_id = ? AND app = ? AND key = ?', (uid, app, key)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r[0])
    except ValueError:
        return default


def kv_set(uid: int, app: str, key: str, value) -> None:
    text = json.dumps(value, ensure_ascii=False)
    with _kv_lock, db.connect() as conn:
        conn.execute('INSERT INTO tools_mt_store (user_id, app, key, json, updated_at) VALUES (?, ?, ?, ?, ?) '
                     'ON CONFLICT(user_id, app, key) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at',
                     (uid, app, key, text, db.now()))
        conn.commit()


# ---------------------------------------------------------------------------
# Kullanıcı dosya alanı (SQL/Notepad/Convert): DATA_DIR/tools/<app>/<uid>/{files,cache,work,converted…}; yollar '/a/b'
# ---------------------------------------------------------------------------
def app_dir(app: str, uid: int, *parts: str) -> Path:
    p = TOOLS_DIR / app / str(int(uid))
    for x in parts:
        p = p / x
    p.mkdir(parents=True, exist_ok=True)
    return p


def files_root(app: str, uid: int) -> Path:
    return app_dir(app, uid, 'files')


_SEG_RE = re.compile(r'[\x00-\x1f\x7f]')


def norm_rel(rel: str) -> str:
    """'/a/b' biçimine getirir; '..' ve gizli kontrol karakterleri temizlenir. Kök = '/'."""
    parts = []
    for s in str(rel or '').replace('\\', '/').split('/'):
        s = _SEG_RE.sub('', s).strip()
        if s in ('', '.'):
            continue
        if s == '..':
            if parts:
                parts.pop()
            continue
        parts.append(s[:200])
    return '/' + '/'.join(parts)


def resolve(root: Path, rel: str) -> Path:
    rel = norm_rel(rel)
    p = (root / rel.lstrip('/')).resolve() if rel != '/' else root.resolve()
    if p != root.resolve() and root.resolve() not in p.parents:
        raise HTTPException(400, 'Geçersiz yol')
    return p


def entry(root: Path, p: Path) -> dict:
    try:
        st = p.stat()
    except OSError:
        return None
    is_dir = p.is_dir()
    return {'name': p.name, 'path': '/' + p.relative_to(root).as_posix(), 'isDir': is_dir, 'isLink': p.is_symlink(),
            'size': 0 if is_dir else st.st_size, 'mtime': int(st.st_mtime * 1000)}


def list_dir(root: Path, rel: str) -> list:
    d = resolve(root, rel)
    if not d.is_dir():
        raise HTTPException(404, 'Klasör bulunamadı')
    out = [entry(root, p) for p in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))]
    return [e for e in out if e]


def dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for f in p.rglob('*'):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def rm(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Renderer i18n.js'ten sunucu tarafında gereken birkaç metin (varsayılan kısayol adları, "(kopya)" eki)
# ---------------------------------------------------------------------------
_i18n_cache = {}


def _i18n_strings(app, lang):
    key = (app, lang)
    if key not in _i18n_cache:
        out = {}
        try:
            src = (config.STATIC_DIR / 'mt' / app / 'i18n.js').read_text(encoding='utf-8')
            m = re.search(r'STRINGS\.' + re.escape(lang) + r'\s*=\s*\{(.*?)\n  \};', src, re.S)
            if m:
                for k, v1, v2 in re.findall(r'''['"](main\.[A-Za-z]+)['"]\s*:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")''', m.group(1)):
                    out[k] = (v1 or v2).replace("\\'", "'").replace('\\"', '"')
        except OSError:
            pass
        _i18n_cache[key] = out
    return _i18n_cache[key]


def mt_text(app, lang, key, default):
    return _i18n_strings(app, lang).get(key) or _i18n_strings(app, 'en').get(key) or default


def resolve_lang(code):
    c = (code or '').split('-')[0].lower()
    return c if c in LANGS else 'en'


# ---------------------------------------------------------------------------
# Depo (store.json karşılığı) — tools_mt_store tablosu
# ---------------------------------------------------------------------------
def uid_hex():
    """Masaüstündeki crypto.randomBytes(8).toString('hex') ile aynı biçimde kimlik."""
    return secrets.token_hex(8)


uid8 = uid_hex


def default_store(app, lang):
    if app == 'sshmaster':
        return {
            'folders': [],
            'connections': [],
            'shortcuts': [
                {'id': uid_hex(), 'name': mt_text(app, lang, 'main.defDisk', 'Disk usage'), 'command': 'df -h', 'enter': True},
                {'id': uid_hex(), 'name': mt_text(app, lang, 'main.defMem', 'Memory'), 'command': 'free -m', 'enter': True},
                {'id': uid_hex(), 'name': mt_text(app, lang, 'main.defTop', 'Processes (top)'), 'command': 'top', 'enter': True},
            ],
            'settings': {
                'localDir': DRIVE, 'sidebarWidth': 320, 'sidebarOpen': True, 'panelSizes': [1, 2, 2],
                'minimizeToTray': True, 'closeToTray': False, 'fontSize': 14, 'appTheme': 'system', 'openAtLogin': False,
                'language': None, 'transfersInBackground': False,
            },
        }
    return {
        'folders': [],
        'connections': [],
        'syncMeta': {},
        'settings': {
            'appTheme': 'system', 'language': None, 'speedLimitOn': False, 'speedLimitKB': 1024, 'maxConcurrent': 4,
            'retryAttempts': 3, 'retryDelay': 10, 'transferType': 'binary', 'conflict': 'overwrite', 'localDir': DRIVE,
            'localWidth': 360, 'localOpen': True, 'transferWidth': 560, 'transferOpen': True, 'trCols': [200, 72, 150, 120],
            'showHidden': True,
        },
    }


def load_store(conn, uid, app, lang='en'):
    row = conn.execute('SELECT json FROM tools_mt_store WHERE user_id = ? AND app = ? AND key = ?', (uid, app, 'store')).fetchone()
    base = default_store(app, lang)
    if not row:   # ilk açılış: varsayılanlar (rastgele kısayol kimlikleri dahil) hemen kalıcı olsun
        save_store(conn, uid, app, base)
        conn.commit()
        return base
    try:
        data = json.loads(row[0])
    except ValueError:
        return base
    store = {**base, **data}
    store['settings'] = {**base['settings'], **(data.get('settings') or {})}
    return store


def save_store(conn, uid, app, store):
    conn.execute('INSERT INTO tools_mt_store (user_id, app, key, json, updated_at) VALUES (?,?,?,?,?) '
                 'ON CONFLICT(user_id, app, key) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at',
                 (uid, app, 'store', json.dumps(store, ensure_ascii=False), db.now()))


def public_store(app, store):
    """Arayüze gönderilen kopya: şifreler ve host anahtarı asla gitmez."""
    conns = []
    for c in store.get('connections', []):
        pub = {k: v for k, v in c.items() if k not in ('password', 'passphrase', 'hostKey')}
        pub['hasPassword'] = bool(c.get('password'))
        pub['hasPassphrase'] = bool(c.get('passphrase'))
        conns.append(pub)
    out = {'folders': store.get('folders', []), 'settings': store.get('settings', {}), 'connections': conns}
    if app == 'sshmaster':
        out['shortcuts'] = store.get('shortcuts', [])
    return out


def with_store(uid, app, fn, lang='en'):
    """Depoyu kilit altında oku → fn(store) → yaz. (fn dönüşü, güncel public store) döner."""
    with _locks[(uid, app)]:
        with db.connect() as conn:
            store = load_store(conn, uid, app, lang)
            r = fn(store)
            save_store(conn, uid, app, store)
            conn.commit()
            return r, public_store(app, store)


def read_store(uid, app, lang='en'):
    with db.connect() as conn:
        return load_store(conn, uid, app, lang)


def resolve_connection(store, cid):
    """Kayıtlı bağlantının çözülmüş (şifreli alanları açılmış) hali."""
    c = next((x for x in store.get('connections', []) if x.get('id') == cid), None)
    if not c:
        raise MtError(T('main.errConnNotFound'))
    return {**c, 'password': decrypt(c.get('password')), 'passphrase': decrypt(c.get('passphrase'))}


def merge_form_with_stored(store, form, same_host_only=False):
    """Formdan gelen veri; boş şifre alanı düzenlemede "değiştirme" anlamına gelir."""
    stored = next((x for x in store.get('connections', []) if x.get('id') == form.get('id')), None) if form.get('id') else None
    same_host = stored and stored.get('host') == form.get('host') and int(stored.get('port') or 0) == int(form.get('port') or 0)
    return {
        **form,
        'password': form.get('password') or (decrypt(stored.get('password')) if stored and not form.get('clearPassword') else ''),
        'passphrase': form.get('passphrase') or (decrypt(stored.get('passphrase')) if stored else ''),
        'hostKey': (stored.get('hostKey') if stored and (same_host or not same_host_only) else None),
    }


def remember_host_key(uid, app, cid, fingerprint):
    """Başarılı bağlantıda host anahtarı parmak izini kaydeder; public store döner (değişiklik yoksa None)."""
    if not fingerprint:
        return None
    changed = [False]

    def fn(store):
        c = next((x for x in store['connections'] if x.get('id') == cid), None)
        if c and c.get('hostKey') != fingerprint:
            c['hostKey'] = fingerprint
            changed[0] = True
    _, pub = with_store(uid, app, fn)
    return pub if changed[0] else None


def site_options(store, cid):
    """FTP sitesinin aktarım seçenekleri: "Genel ayarları kullan" ise uygulama ayarlarından gelir."""
    s = store['settings']
    c = next((x for x in store.get('connections', []) if x.get('id') == cid), None) or {}
    custom = c.get('siteOptions') == 'custom'
    return {
        'maxConcurrent': c.get('maxConcurrent') if custom else s.get('maxConcurrent'),
        'retryAttempts': c.get('retryAttempts') if custom else s.get('retryAttempts'),
        'retryDelay': c.get('retryDelay') if custom else s.get('retryDelay'),
        'conflict': c.get('conflict') if custom and c.get('conflict') else s.get('conflict'),
        'transferType': c.get('transferType') if c.get('transferType') and c.get('transferType') != 'global' else s.get('transferType'),
    }


# ---------------------------------------------------------------------------
# Yerel dosya yöneticisi: H:\ → DATA_DIR/tools/files/<uid>
# ---------------------------------------------------------------------------
def user_root(uid) -> Path:
    p = FILES_DIR / str(int(uid))
    p.mkdir(parents=True, exist_ok=True)
    return p


def to_real(uid, win_path) -> Path:
    """'H:\\Belgeler\\a.txt' → gerçek yol. Sürücü dışı ya da '..' içeren yol reddedilir."""
    s = str(win_path or '').strip().replace('/', '\\')
    if not s[:2].upper() == DRIVE[:2]:
        raise MtError('Yalnızca H:\\ sürücüsü (HEPGO kişisel alanı) kullanılabilir')
    parts = [x for x in s[2:].split('\\') if x and x != '.']
    if any(x == '..' or '\x00' in x for x in parts):
        raise MtError('Geçersiz yol')
    return user_root(uid).joinpath(*parts)


def to_win(uid, real: Path) -> str:
    rel = real.resolve().relative_to(user_root(uid).resolve())
    return DRIVE + '\\'.join(rel.parts)


def local_list(uid, win_dir):
    d = to_real(uid, win_dir)
    if not d.is_dir():
        raise MtError('Klasör bulunamadı: ' + str(win_dir))
    out = []
    for e in d.iterdir():
        try:
            st = e.stat()
            is_dir = e.is_dir()
            out.append({'name': e.name, 'path': to_win(uid, e), 'isDir': is_dir, 'size': 0 if is_dir else st.st_size, 'mtime': int(st.st_mtime * 1000)})
        except OSError:
            out.append({'name': e.name, 'path': to_win(uid, e), 'isDir': False, 'size': 0, 'mtime': 0})
    return out


SPECIAL = {'home': '', 'desktop': 'Masaüstü', 'downloads': 'İndirilenler', 'documents': 'Belgeler'}


def local_special(uid):
    root = user_root(uid)
    out = {}
    for k, name in SPECIAL.items():
        if name:
            (root / name).mkdir(exist_ok=True)
        out[k] = DRIVE + name
    return out


def local_trash(uid, paths):
    trash = user_root(uid) / '.trash'
    trash.mkdir(exist_ok=True)
    for p in paths:
        src = to_real(uid, p)
        if src.exists():
            shutil.move(str(src), str(trash / f'{time.strftime("%Y%m%d-%H%M%S")}_{src.name}'))


def unique_local_path(p: Path) -> Path:
    """Aynı isimde dosya varsa "ad (1).ext" şeklinde yeni isim üretir."""
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_name(f'{p.stem} ({i}){p.suffix}')
        if not cand.exists():
            return cand
        i += 1


def cleanup_upload_tmp(uid, real_path: Path):
    """Tarayıcıdan sürüklenip H:\\.upload\\<jeton> altına alınan dosya aktarıldıktan sonra geçici klasörü siler."""
    try:
        up = (user_root(uid) / '.upload').resolve()
        rp = real_path.resolve()
        if up in rp.parents:
            shutil.rmtree(rp.parent, ignore_errors=True)   # .upload/<jeton> klasörü
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# IPC kanalları (ipcMain.handle karşılıkları) — ctx: {'uid', 'app', 'lang'}
# ---------------------------------------------------------------------------
def _num(v, default, lo, hi):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, n))


def _one_of(v, options, default):
    return v if v in options else default


def _find(items, cid):
    return next((x for x in items if x.get('id') == cid), None)


def h_store_get(ctx, a):
    return public_store(ctx['app'], read_store(ctx['uid'], ctx['app'], ctx['lang'])), False


def h_settings_set(ctx, patch):
    def fn(store):
        store['settings'].update(patch or {})
    with_store(ctx['uid'], ctx['app'], fn)
    if ctx['app'] == 'ftpmaster' and patch and ('speedLimitOn' in patch or 'speedLimitKB' in patch):
        from . import tools_ftp
        tools_ftp.apply_speed_limit(ctx['uid'], read_store(ctx['uid'], 'ftpmaster')['settings'])
    return None, True


def h_conn_save(ctx, form):
    app = ctx['app']
    out = [None]

    def fn(store):
        c = _find(store['connections'], form.get('id')) if form.get('id') else None
        if not c:
            c = {'id': uid_hex(), 'createdAt': int(time.time() * 1000)}
            store['connections'].append(c)
        if app == 'sshmaster':
            if c.get('host') and (c.get('host') != form.get('host') or int(c.get('port') or 0) != int(form.get('port') or 0)):
                c['hostKey'] = None   # host veya port değiştiyse eski host anahtarını unut
            c.update({
                'name': str(form.get('name') or '').strip(), 'host': str(form.get('host') or '').strip(),
                'port': _num(form.get('port'), 22, 1, 65535), 'username': str(form.get('username') or '').strip(),
                'authType': 'key' if form.get('authType') == 'key' else 'password', 'keyPath': form.get('keyPath') or '',
                'folderId': form.get('folderId', c.get('folderId')) or None, 'rememberLastDir': bool(form.get('rememberLastDir')),
                'color': form.get('color') or c.get('color') or '#3b82f6', 'theme': form.get('theme') or c.get('theme') or 'sshmaster',
                'notes': form.get('notes') or '',
            })
            if not c['rememberLastDir']:
                c['lastDir'] = ''
        else:
            from . import tools_ftp
            protocol = _one_of(form.get('protocol'), list(tools_ftp.PROTOCOLS), 'ftp')
            if c.get('host') and (c.get('host') != form.get('host') or int(c.get('port') or 0) != int(form.get('port') or 0) or c.get('protocol') != protocol):
                c['hostKey'] = None
            c.update({
                'name': str(form.get('name') or form.get('host') or '').strip(), 'host': str(form.get('host') or '').strip(),
                'username': str(form.get('username') or '').strip(),
                'loginMethod': _one_of(form.get('loginMethod'), ['normal', 'anonymous'], 'normal'),
                'authType': 'key' if form.get('authType') == 'key' else 'password', 'keyPath': form.get('keyPath') or '',
                'comments': form.get('comments') or '', 'folderId': form.get('folderId', c.get('folderId')) or None,
                'color': form.get('color') or c.get('color') or '#22d3ee',
                'remoteDir': str(form.get('remoteDir') or '').strip(), 'localDir': str(form.get('localDir') or '').strip(),
                'rememberLastDir': bool(form.get('rememberLastDir')),
                'cacheMode': _one_of(form.get('cacheMode'), ['session', 'always', 'never'], 'session'),
                'uploadCase': _one_of(form.get('uploadCase'), ['preserve', 'lower', 'upper'], 'preserve'),
                'protocol': protocol, 'port': _num(form.get('port'), tools_ftp.PROTOCOLS[protocol]['port'], 1, 65535),
                'transferType': _one_of(form.get('transferType'), ['global', 'binary', 'ascii', 'auto'], 'global'),
                'timezone': _num(form.get('timezone'), 0, -14, 14),
                'siteOptions': _one_of(form.get('siteOptions'), ['global', 'custom'], 'global'),
                'retryAttempts': _num(form.get('retryAttempts'), 3, 0, 99), 'retryDelay': _num(form.get('retryDelay'), 10, 0, 3600),
                'maxConcurrent': _num(form.get('maxConcurrent'), 4, 1, 20),
                'conflict': _one_of(form.get('conflict'), ['overwrite', 'rename', 'skip'], 'overwrite'),
                'encoding': _one_of(form.get('encoding'), ['auto', 'utf8', 'ascii'], 'auto'),
            })
            if not c['rememberLastDir']:
                c['lastRemoteDir'] = ''
                c['lastLocalDir'] = ''
        if form.get('password'):
            c['password'] = encrypt(form['password'])
        if form.get('clearPassword'):
            c['password'] = ''
        if form.get('passphrase'):
            c['passphrase'] = encrypt(form['passphrase'])
        if form.get('testedHostKey') and not c.get('hostKey'):
            c['hostKey'] = form['testedHostKey']
        out[0] = c['id']
    with_store(ctx['uid'], app, fn)
    return out[0], True


def h_conn_delete(ctx, cid):
    def fn(store):
        store['connections'] = [c for c in store['connections'] if c.get('id') != cid]
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_conn_duplicate(ctx, cid):
    def fn(store):
        c = _find(store['connections'], cid)
        if c:
            dup = {**c, 'id': uid_hex(), 'name': c.get('name', '') + mt_text(ctx['app'], ctx['lang'], 'main.copySuffix', ' (copy)'),
                   'createdAt': int(time.time() * 1000)}
            if ctx['app'] == 'sshmaster':
                dup['lastDir'] = ''
            else:
                dup['lastRemoteDir'] = ''
                dup['lastLocalDir'] = ''
            store['connections'].append(dup)
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_conn_move(ctx, a):
    def fn(store):
        c = _find(store['connections'], a.get('id'))
        if c:
            c['folderId'] = a.get('folderId') or None
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_conn_set_theme(ctx, a):
    def fn(store):
        c = _find(store['connections'], a.get('id'))
        if c:
            c['theme'] = a.get('theme')
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_conn_reset_last_dir(ctx, cid):
    def fn(store):
        c = _find(store['connections'], cid)
        if c:
            c['lastDir'] = ''
            c['lastRemoteDir'] = ''
            c['lastLocalDir'] = ''
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_conn_test(ctx, form):
    store = read_store(ctx['uid'], ctx['app'], ctx['lang'])
    if ctx['app'] == 'sshmaster':
        from . import tools_ssh
        return tools_ssh.test_connection(ctx['uid'], store, form or {}), False
    from . import tools_ftp
    return tools_ftp.test_connection(ctx['uid'], store, form or {}), False


def h_folder_save(ctx, a):
    out = [None]

    def fn(store):
        f = _find(store['folders'], a.get('id')) if a.get('id') else None
        if not f:
            f = {'id': uid_hex(), 'parentId': a.get('parentId') or None}
            store['folders'].append(f)
        f['name'] = str(a.get('name') or '').strip()
        out[0] = f['id']
    with_store(ctx['uid'], ctx['app'], fn)
    return out[0], True


def h_folder_move(ctx, a):
    ok = [True]

    def fn(store):
        p = a.get('parentId')   # bir klasörü kendi alt klasörüne taşımayı engelle
        while p:
            if p == a.get('id'):
                ok[0] = False
                return
            p = (_find(store['folders'], p) or {}).get('parentId')
        f = _find(store['folders'], a.get('id'))
        if f:
            f['parentId'] = a.get('parentId') or None
    with_store(ctx['uid'], ctx['app'], fn)
    return ok[0], True


def h_folder_delete(ctx, fid):
    def fn(store):
        f = _find(store['folders'], fid)
        if not f:
            return
        for c in store['connections']:   # içerik üst klasöre taşınır
            if c.get('folderId') == fid:
                c['folderId'] = f.get('parentId') or None
        for sub in store['folders']:
            if sub.get('parentId') == fid:
                sub['parentId'] = f.get('parentId') or None
        store['folders'] = [x for x in store['folders'] if x.get('id') != fid]
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_shortcut_save(ctx, s):
    def fn(store):
        item = _find(store['shortcuts'], s.get('id')) if s.get('id') else None
        if not item:
            item = {'id': uid_hex()}
            store['shortcuts'].append(item)
        item.update({'name': str(s.get('name') or '').strip() or str(s.get('command') or '').strip(), 'command': s.get('command') or '', 'enter': bool(s.get('enter'))})
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_shortcut_delete(ctx, sid):
    def fn(store):
        store['shortcuts'] = [x for x in store['shortcuts'] if x.get('id') != sid]
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_shortcut_reorder(ctx, ids):
    def fn(store):
        m = {s['id']: s for s in store['shortcuts']}
        store['shortcuts'] = [m[i] for i in (ids or []) if i in m]
    with_store(ctx['uid'], ctx['app'], fn)
    return None, True


def h_local_list(ctx, d):
    return local_list(ctx['uid'], d), False


def h_local_drives(ctx, a):
    return [DRIVE], False


def h_local_special(ctx, a):
    return local_special(ctx['uid']), False


def h_local_mkdir(ctx, p):
    to_real(ctx['uid'], p).mkdir()
    return None, False


def h_local_rename(ctx, a):
    to_real(ctx['uid'], a.get('from')).rename(to_real(ctx['uid'], a.get('to')))
    return None, False


def h_local_trash(ctx, paths):
    local_trash(ctx['uid'], paths or [])
    return None, False


def h_local_exists(ctx, p):
    return to_real(ctx['uid'], p).exists(), False


def h_local_is_file(ctx, p):
    return to_real(ctx['uid'], p).is_file(), False


HANDLERS = {
    'store:get': h_store_get, 'settings:set': h_settings_set,
    'conn:save': h_conn_save, 'conn:delete': h_conn_delete, 'conn:duplicate': h_conn_duplicate, 'conn:move': h_conn_move,
    'conn:setTheme': h_conn_set_theme, 'conn:resetLastDir': h_conn_reset_last_dir, 'conn:test': h_conn_test,
    'folder:save': h_folder_save, 'folder:move': h_folder_move, 'folder:delete': h_folder_delete,
    'shortcut:save': h_shortcut_save, 'shortcut:delete': h_shortcut_delete, 'shortcut:reorder': h_shortcut_reorder,
    'local:list': h_local_list, 'local:drives': h_local_drives, 'local:special': h_local_special, 'local:mkdir': h_local_mkdir,
    'local:rename': h_local_rename, 'local:trash': h_local_trash, 'local:exists': h_local_exists, 'local:isFile': h_local_is_file,
}


def _ctx(app, user, lang=None):
    if app not in IPC_APPS:
        raise HTTPException(404, 'Bilinmeyen uygulama')
    store_lang = None
    try:   # yalnız kayıtlı ayar okunur; depo henüz yoksa varsayılanlar istenen dilde sonra oluşur
        with db.connect() as conn:
            row = conn.execute('SELECT json FROM tools_mt_store WHERE user_id = ? AND app = ? AND key = ?', (user['id'], app, 'store')).fetchone()
        store_lang = (json.loads(row[0]).get('settings') or {}).get('language') if row else None
    except Exception:   # noqa: BLE001
        pass
    return {'uid': user['id'], 'app': app, 'lang': resolve_lang(store_lang or lang or 'tr')}


class InvokeIn(BaseModel):
    m: str
    a: Any = None


@router.get('/{app}/boot')
def boot(app: str, lang: str = '', user=Depends(tools_user)):
    """Açılış: dil (uygulama ayarı > HEPGO dili), kullanıcı ve depo tek istekte (preload sendSync karşılığı)."""
    ctx = _ctx(app, user, lang)
    store = read_store(ctx['uid'], app, ctx['lang'])
    return {'user': {'email': user.get('username') or '', 'name': user.get('full_name') or ''}, 'lang': ctx['lang'],
            'store': public_store(app, store), 'version': VERSION}


@router.post('/{app}/invoke')
async def invoke(app: str, body: InvokeIn, user=Depends(tools_user)):
    """IPC kanalı çağrısı. Depoyu değiştiren kanallar güncel public store'u da döndürür (store:changed yayını)."""
    ctx = _ctx(app, user)
    handler = HANDLERS.get(body.m)
    if not handler:
        raise HTTPException(400, f'Bilinmeyen kanal: {body.m}')
    try:
        v, changed = await asyncio.to_thread(handler, ctx, body.a)
    except MtError as e:
        return {'ok': False, 'e': e.msg}
    except Exception as e:   # noqa: BLE001 — dosya sistemi/ağ hataları arayüze metin olarak
        return {'ok': False, 'e': str(e) or e.__class__.__name__}
    out = {'ok': True, 'v': v}
    if changed:
        out['store'] = public_store(app, read_store(ctx['uid'], app, ctx['lang']))
    return out


@router.post('/{app}/files/upload')
async def files_upload(app: str, file: UploadFile, dir: str = Form(DRIVE), user=Depends(tools_user)):
    """Tarayıcıdan dosya → kişisel alan (H:\\…). Özel anahtar dosyaları (H:\\.ssh) 0600 ile yazılır."""
    ctx = _ctx(app, user)
    try:
        d = to_real(ctx['uid'], dir)
    except MtError as e:
        raise HTTPException(400, str(e)) from None
    d.mkdir(parents=True, exist_ok=True)
    name = Path((file.filename or 'dosya').replace('\\', '/')).name.strip() or 'dosya'
    target = unique_local_path(d / name)

    def write():
        with open(target, 'wb') as f:
            shutil.copyfileobj(file.file, f, 1024 * 1024)
        if '.ssh' in target.parts:
            target.chmod(0o600)
    await asyncio.to_thread(write)
    return {'path': to_win(ctx['uid'], target), 'size': target.stat().st_size}


@router.get('/{app}/files/download')
def files_download(app: str, path: str, user=Depends(tools_user)):
    ctx = _ctx(app, user)
    try:
        p = to_real(ctx['uid'], path)
    except MtError as e:
        raise HTTPException(400, str(e)) from None
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(p, filename=p.name, media_type='application/octet-stream')


# ---------------------------------------------------------------------------
# HTTP: hesap ve dosya alanı (SQL / Notepad / Convert Master; static/mt/common/hepgo.js köprüsü)
# ---------------------------------------------------------------------------
@router.get('/account')
def account(user=Depends(tools_user)):
    """Masaüstündeki account:state karşılığı: oturum HEPGO'nun; Master Tool senkronu yok (state 'off')."""
    return {'loggedIn': True, 'user': {'id': user['id'], 'email': user['username'], 'name': user.get('full_name') or user['username']},
            'email': user['username'], 'syncEnabled': False, 'state': 'off', 'lastSyncAt': None, 'error': None, 'hepgo': True,
            'notice': None, 'appVersion': 'HEPGO'}


class PathBody(BaseModel):
    path: str = '/'
    name: str = ''


@router.get('/{app}/fs/list')
def fs_list(app: str, path: str = '/', user=Depends(tools_user)):
    return {'root': '/', 'items': list_dir(files_root(check_app(app), user['id']), path)}


@router.post('/{app}/fs/mkdir')
def fs_mkdir(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    base = resolve(root, body.path)
    target = (base / safe_name(body.name, '')) if body.name else base
    if target == root or not safe_name(target.name, ''):
        raise HTTPException(400, 'Geçersiz klasör adı')
    target.mkdir(parents=True, exist_ok=True)
    return {'ok': True, 'path': '/' + target.relative_to(root).as_posix()}


@router.post('/{app}/fs/upload')
async def fs_upload(app: str, files: list[UploadFile], dir: str = Form('/'), user=Depends(tools_user)):   # noqa: A002
    root = files_root(check_app(app), user['id'])
    d = resolve(root, dir)
    d.mkdir(parents=True, exist_ok=True)
    saved = []
    check = UPLOAD_GUARD(user['id'], app) if UPLOAD_GUARD else None
    for f in files:
        # Klasör yüklemesinde (webkitdirectory) dosya adı göreli yol taşır: alt klasörler korunur
        rel = norm_rel(f.filename or 'dosya').lstrip('/')
        target = resolve(root, '/' + (d.relative_to(root).as_posix() + '/' if d != root else '') + rel)
        if check:
            check(-(target.stat().st_size if target.is_file() else 0), not target.exists())
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with target.open('wb') as out:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                try:
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, f'Dosya çok büyük (en çok {MAX_UPLOAD // (1024 * 1024)} MB)')
                    if check:
                        check(len(chunk), False)
                except HTTPException:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise
                out.write(chunk)
        saved.append(entry(root, target))
    return {'ok': True, 'items': saved}


@router.get('/{app}/fs/download')
def fs_download(app: str, path: str, user=Depends(tools_user)):
    p = resolve(files_root(check_app(app), user['id']), path)
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(p, filename=p.name)


@router.post('/{app}/fs/delete')
def fs_delete(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    p = resolve(root, body.path)
    if p == root.resolve():
        raise HTTPException(400, 'Kök silinemez')
    rm(p)
    return {'ok': True}


@router.post('/{app}/fs/rename')
def fs_rename(app: str, body: PathBody, user=Depends(tools_user)):
    root = files_root(check_app(app), user['id'])
    p = resolve(root, body.path)
    name = safe_name(body.name, '')
    if not p.exists() or not name:
        raise HTTPException(400, 'Geçersiz ad')
    p.rename(p.parent / name)
    return {'ok': True, 'path': '/' + (p.parent / name).relative_to(root).as_posix()}


@router.get('/{app}/fs/usage')
def fs_usage(app: str, user=Depends(tools_user)):
    return {'bytes': dir_size(files_root(check_app(app), user['id']))}


def audit(uid, action, detail):
    with db.connect() as conn:
        db.audit(conn, uid, action, 'tools', None, detail)
        conn.commit()


def ws_ctx(user, app, lang=None):
    return _ctx(app, user, lang)


def shq(p) -> str:
    return "'" + str(p).replace("'", "'\\''") + "'"

