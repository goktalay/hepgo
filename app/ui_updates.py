"""Ekran bazlı arayüz sürüm takibi.

Her başlangıçta arayüz dosyalarının (static/js, static/css, static/*.html) içerik özeti (manifest) çıkarılır ve bir önceki
sürümle karşılaştırılır. Değişen dosyalar varsa yeni bir SÜRÜM (ui_releases) kaydedilir; değişen her dosyanın hangi
EKRANLARI etkilediği app.js'nin import ağacından bulunur (ekran = MODULES / PERSONAL girdisi; ortak dosyalar → '*' = tüm ekranlar).

İstemci (app.js) açılışta hangi sürümle yüklendiğini bildirir (ui_loaded); sonraki sürümlerde yalnız ETKİLENEN ekranlarda
"Yenile" düğmesi gösterir. Kullanıcı yenileyince ya da güncel kodla ekrana girince (release, user, screen) kaydı düşer (ui_acks);
Yönetim › Sürüm Takibi bunu sürüm → ekran → kullanıcı (güncelledi / güncellemedi) olarak gösterir."""
import hashlib
import json
import re
from pathlib import Path

from . import config, db

DDL = '''
CREATE TABLE IF NOT EXISTS ui_releases (
    id INTEGER PRIMARY KEY,
    stamp TEXT,                 -- asset_version (sv/<ver>) damgası
    created_at TEXT NOT NULL,
    screens TEXT NOT NULL,      -- JSON: etkilenen ekran anahtarları ('*' = tüm ekranlar)
    files TEXT NOT NULL,        -- JSON: değişen dosyalar
    manifest TEXT NOT NULL      -- JSON: dosya → içerik özeti (bir sonraki karşılaştırma için)
);
CREATE TABLE IF NOT EXISTS ui_acks (
    release_id INTEGER NOT NULL REFERENCES ui_releases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    screen TEXT NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'refresh',   -- refresh: Yenile'ye bastı · visit: güncel kodla ekrana girdi
    PRIMARY KEY (release_id, user_id, screen)
);
CREATE TABLE IF NOT EXISTS ui_loaded (
    user_id INTEGER PRIMARY KEY,
    release_id INTEGER,
    stamp TEXT,
    at TEXT NOT NULL
);
'''
_IMPORT_RE = re.compile(r'''(?:import|export)\s+(?:[^'";]*?\s+from\s+)?['"](\.{1,2}/[^'"]+\.js)['"]|import\(\s*['"](\.{1,2}/[^'"]+\.js)['"]\s*\)''')
_ALIAS_RE = re.compile(r'''^import\s+\*\s+as\s+(\w+)\s+from\s+['"]\./([^'"]+\.js)['"]''', re.M)
_NAMED_RE = re.compile(r'''^import\s+\{([^}]+)\}\s+from\s+['"]\./([^'"]+\.js)['"]''', re.M)
_MODULE_RE = re.compile(r'''\{\s*key:\s*'([^']+)',\s*title:\s*'([^']*)'[^}\n]*?\bmod:\s*(\w+)''')
_PERSONAL_RE = re.compile(r'''\{\s*key:\s*'(\w+)',\s*route:\s*'([^']+)',\s*title:\s*'([^']*)'[^\n]*?render:\s*(?:params|\(\s*\))?\s*=>\s*(\w+)''')
# app.js içinde doğrudan çizilen ekranlar (MODULES/PERSONAL dışı): anahtar → (başlık, dosya)
_EXTRA_SCREENS = {'home': ('Ana Sayfa (Pano)', 'modules/dashboard.js'), 'settings': ('Ayarlar', 'modules/settings.js'),
                  'alerts': ('Uyarılar', 'modules/alerts.js'), 'meet': ('Online Toplantı', 'modules/meet.js'),
                  'sign': ('İmza Talepleri', 'modules/sign.js')}
_cache = {}


def ensure_tables(conn):
    conn.executescript(DDL)


def _static():
    return Path(config.STATIC_DIR).resolve()


def _rel(p):
    try:
        return Path(p).resolve().relative_to(_static()).as_posix()
    except ValueError:
        return None


def _closure(entry):
    """Bir giriş dosyasının statik + dinamik import kapanışı (static'e göreli yollar)."""
    seen, stack = set(), [Path(entry)]
    while stack:
        f = stack.pop().resolve()
        r = _rel(f)
        if r is None or r in seen or not f.is_file():
            continue
        seen.add(r)
        txt = f.read_text(encoding='utf-8', errors='ignore')
        for m in _IMPORT_RE.finditer(txt):
            stack.append(f.parent / (m.group(1) or m.group(2)))
    return seen


def screens():
    """Ekran tanımları: {key: {'title', 'entry', 'files': set}} + 'global' dosya kümesi. app.js ayrıştırılır; sonuç
    app.js'nin değişiklik zamanıyla önbelleklenir."""
    js = _static() / 'js'
    appjs = js / 'app.js'
    try:
        key = appjs.stat().st_mtime_ns
    except OSError:
        return {}, set()
    if _cache.get('key') == key:
        return _cache['screens'], _cache['global']
    txt = appjs.read_text(encoding='utf-8', errors='ignore')
    alias = {m.group(1): m.group(2) for m in _ALIAS_RE.finditer(txt)}
    for m in _NAMED_RE.finditer(txt):
        for name in m.group(1).split(','):
            name = name.strip().split(' as ')[-1].strip()
            if name:
                alias.setdefault(name, m.group(2))
    out = {}
    for m in _MODULE_RE.finditer(txt):
        k, title, mod = m.group(1), m.group(2), m.group(3)
        if mod in alias:
            out[k] = {'title': title, 'entry': 'js/' + alias[mod]}
    for m in _PERSONAL_RE.finditer(txt):
        _k, route, title, ident = m.groups()
        if ident in alias:
            out[route] = {'title': title, 'entry': 'js/' + alias[ident], 'personal': True}
    for k, (title, f) in _EXTRA_SCREENS.items():
        out.setdefault(k, {'title': title, 'entry': 'js/' + f})
    entries = {s['entry'] for s in out.values()}
    for s in out.values():
        s['files'] = _closure(_static() / s['entry'])
    # ortak (global) dosyalar: app.js + doğrudan import ettiği, ekran girişi olmayan dosyalar + tüm CSS/HTML
    glob = {'js/app.js'}
    for m in _IMPORT_RE.finditer(txt):
        r = _rel(appjs.parent / (m.group(1) or m.group(2)))
        if r and r not in entries:
            glob.add(r)
    # bir ekran girişinin kendisi de app.js'den geliyorsa global sayılmaz; ancak ekran girişlerinin ortak alt dosyaları
    # (ui.js, api.js …) zaten app.js'nin doğrudan importlarıdır → global
    _cache.update(key=key, screens=out, **{'global': glob})
    return out, glob


def manifest():
    """static/js, static/css ve static/*.html içerik özetleri."""
    base = _static()
    out = {}
    for d in ('js', 'css'):
        for f in sorted((base / d).rglob('*')):
            if f.is_file() and not any(part in ('vendor',) for part in f.relative_to(base).parts[:1]):
                out[f.relative_to(base).as_posix()] = hashlib.md5(f.read_bytes()).hexdigest()
    for f in sorted(base.glob('*.html')):
        out[f.name] = hashlib.md5(f.read_bytes()).hexdigest()
    return out


def screens_for(files):
    """Değişen dosyalar → etkilenen ekran anahtarları (sıralı); ortak dosya değiştiyse ['*']."""
    scr, glob = screens()
    files = set(files)
    if any(f in glob or f.startswith('css/') or f.endswith('.html') for f in files):
        return ['*']
    hit = sorted(k for k, s in scr.items() if files & s['files'])
    orphan = [f for f in files if not any(f in s['files'] for s in scr.values())]
    if orphan and not hit:   # hiçbir ekrana bağlanamayan dosya (ör. yeni/yalnız dinamik yüklenen) → güvenli taraf: tüm ekranlar
        return ['*']
    return hit


def ensure_release(conn, stamp=None):
    """Başlangıçta: manifest değiştiyse yeni sürüm kaydı. İlk kurulumda temel (etkilenen ekran yok) kayıt. Döner: güncel sürüm id."""
    ensure_tables(conn)
    cur = manifest()
    last = db.row(conn.execute('SELECT id, manifest FROM ui_releases ORDER BY id DESC LIMIT 1'))
    if not last:
        rid = conn.execute('INSERT INTO ui_releases (stamp, created_at, screens, files, manifest) VALUES (?,?,?,?,?)',
                           (stamp, db.now(), '[]', '[]', json.dumps(cur))).lastrowid
        conn.commit()
        return rid
    prev = json.loads(last['manifest'] or '{}')
    changed = sorted(f for f in set(cur) | set(prev) if cur.get(f) != prev.get(f))
    if not changed:
        if stamp:
            conn.execute('UPDATE ui_releases SET stamp = COALESCE(stamp, ?) WHERE id = ?', (stamp, last['id']))
            conn.commit()
        return last['id']
    scr = screens_for(changed)
    rid = conn.execute('INSERT INTO ui_releases (stamp, created_at, screens, files, manifest) VALUES (?,?,?,?,?)',
                       (stamp, db.now(), json.dumps(scr), json.dumps(changed), json.dumps(cur))).lastrowid
    conn.commit()
    return rid


def current_id(conn):
    r = conn.execute('SELECT MAX(id) FROM ui_releases').fetchone()
    return int(r[0] or 0)


def releases_after(conn, loaded):
    return db.rows(conn.execute('SELECT id, created_at, screens FROM ui_releases WHERE id > ? ORDER BY id', (int(loaded or 0),)))


def affects(rel, screen):
    scr = json.loads(rel['screens'] or '[]')
    return '*' in scr or screen in scr


def pending_for(conn, loaded):
    """loaded sürümünden sonra hangi ekranlar hangi (en yüksek) sürümle değişti: {screen: release_id}; '*' anahtarı = tüm ekranlar."""
    out = {}
    for r in releases_after(conn, loaded):
        for s in json.loads(r['screens'] or '[]'):
            out[s] = r['id']
    return out


def ack(conn, user_id, screen, release_id, kind):
    """Kullanıcı bu ekranı 'release_id' ve öncesindeki tüm sürümler için güncellemiş sayılır."""
    now = db.now()
    rows = db.rows(conn.execute('SELECT id, screens FROM ui_releases WHERE id <= ? AND screens != ?', (int(release_id), '[]')))
    n = 0
    for r in rows:
        if affects(r, screen):
            conn.execute('INSERT OR IGNORE INTO ui_acks (release_id, user_id, screen, at, kind) VALUES (?,?,?,?,?)',
                         (r['id'], user_id, screen, now, kind))
            n += 1
    conn.commit()
    return n


def set_loaded(conn, user_id, stamp):
    """İstemci açılışta hangi derlemeyle yüklendiğini bildirir → sürüm id'si (damga eşleşmezse en güncel sürüm)."""
    r = db.row(conn.execute('SELECT id FROM ui_releases WHERE stamp = ? ORDER BY id DESC LIMIT 1', (stamp,))) if stamp else None
    rid = r['id'] if r else current_id(conn)
    conn.execute('INSERT INTO ui_loaded (user_id, release_id, stamp, at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET release_id = excluded.release_id, stamp = excluded.stamp, at = excluded.at',
                 (user_id, rid, stamp, db.now()))
    conn.commit()
    return rid


def screen_title(key):
    scr, _ = screens()
    return scr.get(key, {}).get('title') or key


def release_screens(conn, rid):
    """Sürümün etkilediği ekranlar + kullanıcı sayıları ('*' → tüm ekranlar açılır)."""
    rel = db.row(conn.execute('SELECT * FROM ui_releases WHERE id = ?', (rid,)))
    if not rel:
        return None
    scr, _ = screens()
    keys = sorted(scr) if '*' in json.loads(rel['screens'] or '[]') else json.loads(rel['screens'] or '[]')
    total = conn.execute('SELECT COUNT(*) FROM users WHERE active = 1 AND deleted_at IS NULL').fetchone()[0]
    acks = {k: n for k, n in conn.execute('SELECT screen, COUNT(*) FROM ui_acks WHERE release_id = ? GROUP BY screen', (rid,))}
    return {'release': {'id': rel['id'], 'created_at': rel['created_at'], 'stamp': rel['stamp'], 'files': json.loads(rel['files'] or '[]'),
                        'all': '*' in json.loads(rel['screens'] or '[]')},
            'total_users': total,
            'screens': [{'key': k, 'title': scr.get(k, {}).get('title') or k, 'personal': bool(scr.get(k, {}).get('personal')),
                         'updated': acks.get(k, 0), 'total': total} for k in keys]}


def screen_users(conn, rid, screen):
    """Sürüm + ekran için kullanıcılar: güncelledi (ack) / güncellemedi (kodu güncel ama ekrana girmedi · eski kodla açık)."""
    users = db.rows(conn.execute('''SELECT u.id, u.full_name, u.username, u.photo, u.last_seen, l.release_id AS loaded, l.at AS loaded_at
                                    FROM users u LEFT JOIN ui_loaded l ON l.user_id = u.id
                                    WHERE u.active = 1 AND u.deleted_at IS NULL ORDER BY u.full_name'''))
    acks = {r['user_id']: r for r in db.rows(conn.execute('SELECT user_id, at, kind FROM ui_acks WHERE release_id = ? AND screen = ?', (rid, screen)))}
    done, pending = [], []
    for u in users:
        a = acks.get(u['id'])
        if a:
            done.append({**u, 'at': a['at'], 'kind': a['kind']})
        else:
            u['state'] = 'fresh' if (u['loaded'] or 0) >= rid else ('stale' if u['loaded'] else 'never')
            pending.append(u)
    return {'screen': screen, 'title': screen_title(screen), 'updated': done, 'pending': pending}
