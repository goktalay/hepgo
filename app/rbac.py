"""Rol Yönetimi — veritabanı tabanlı yetki motoru.

Model
- Roller ağaçtır: her rolün en çok bir üst rolü (parent) olur; alt rol, üst rolün yetkilerini miras alır.
- Düğümler (node) modül ve alt modüllerdir: 'finance', 'finance.trial' … Noktalı alt düğüm ayarı yoksa üst düğüme bakılır.
- Yetenekler (cap): open (modülü aç / menüde gör), read (veri oku), write (veri yaz: ekle / düzenle / sil).
  write ⇒ read ⇒ open zinciri zorunludur (yazabilen okur, okuyan açar).
- Ayar değeri: 1 izin · 0 yasak · kayıt yok = miras.

Karar
- Bir rolün değeri: önce rolün kendi ayarları (en özel düğümden modüle doğru), yoksa üst rolden (aynı sırayla) miras.
- Kişinin birden çok rolü varsa: herhangi birinde YASAK varsa yasak (izinsizlik izinli olmayı yener); yoksa herhangi
  birinde İZİN varsa izin; hiçbiri yoksa yetki yok. İzin ve yasak birlikte geliyorsa bu bir çakışmadır (uyarı).

Taşıma: koddaki ROLES sistem rolü olarak, MODULE_ROLES varsayılan izinler olarak ilk açılışta aktarılır; kodda sonradan
eklenen modül / rol de bir kez aktarılır (app_kv 'rbac_seeded'), yöneticinin sonraki düzenlemeleri ezilmez.
"""
import json
import threading
import time

from . import db

CAPS = ('open', 'read', 'write')
CAP_LABELS = {'open': 'Aç', 'read': 'Veri oku', 'write': 'Veri yaz'}
LOCKED = 'Sistem Yöneticisi'   # tüm yetkiler; düzenlenemez / silinemez (kilitlenip dışarıda kalınmasın)
SEED_KEY = 'rbac_seeded'

# Düğüm kataloğu: (anahtar, başlık, grup). Noktalı anahtarlar alt modüldür (üst düğümden miras alır).
CATALOG = [
    ('boss', 'Patron ekranı', 'Yönetim'), ('admin', 'Yönetim paneli', 'Yönetim'), ('users', 'Kullanıcı Yönetimi', 'Yönetim'),
    ('reports', 'Raporlar', 'Yönetim'), ('announcements', 'Duyurular', 'Yönetim'),
    ('production', 'Üretim Yönetimi', 'Üretim'), ('orders', 'İş Emri Yönetimi', 'Üretim'), ('printers', 'Yazıcı Yönetimi', 'Üretim'),
    ('products', 'Ürün Yönetimi', 'Üretim'), ('design', 'Endüstriyel Tasarım', 'Üretim'),
    ('mrp', 'MRP', 'Malzeme & Satın Alma'), ('stock', 'Yarı Mamül / Stok', 'Malzeme & Satın Alma'),
    ('warehouse', 'Onay / Depo', 'Malzeme & Satın Alma'), ('purchasing', 'Satın Alma', 'Malzeme & Satın Alma'),
    ('companies', 'Firma Yönetimi', 'Satış & CRM'), ('documents', 'Evrak Yönetimi', 'Satış & CRM'), ('sales', 'Satış Yönetimi', 'Satış & CRM'),
    ('finance', 'Finans', 'Finans'), ('finance.bank', 'Kasa & Banka', 'Finans'), ('finance.cari', 'Cariler', 'Finans'),
    ('finance.cash', 'Nakit Akışı', 'Finans'), ('finance.instruments', 'Çek / Senet', 'Finans'), ('finance.trial', 'Mizan', 'Finans'),
    ('finance.statements', 'Mali Tablolar', 'Finans'),
    ('hr', 'İnsan Kaynakları', 'İnsan Kaynakları'),
    ('projects', 'Proje Yönetimi', 'Proje & Ar-Ge'),
    ('field', 'Saha Yönetimi', 'Saha & Operasyon'),
    ('field.live', 'Canlı Uçuş', 'Saha & Operasyon'),   # saha görevinden açılan harekât ekranı
    # Dron Yönetimi: ayrı üst modül (alt düğümler üst modülden miras alır; rol başına ayrı oku/yaz verilebilir)
    ('drone', 'Dron Yönetimi', 'Saha & Operasyon'),
    ('drone.drones', 'Dron Envanteri', 'Saha & Operasyon'), ('drone.routes', 'Rotalar', 'Saha & Operasyon'),
    ('drone.bridges', 'Dron Köprüleri', 'Saha & Operasyon'),
    ('drone.cameras', 'Dron Kameraları', 'Saha & Operasyon'),   # köprü üzerinden RTSP/RTP görüntü (app/drone_video.py)
    ('drone.sim', 'Uçuş Simülatörü', 'Saha & Operasyon'),   # ArduPilot SITL + Mission Planner köprüsü + 3B dünya (docs/ucus-simulatoru.md)
    ('fleet', 'Araç Yönetimi', 'Saha & Operasyon'), ('certs', 'Sertifikasyon', 'Saha & Operasyon'),
    ('cleaning', 'Temizlik', 'Saha & Operasyon'),
    ('pos', 'Esnaf Kasa', 'Satış & CRM'),
    ('sections', 'Bölümler', 'Satış & CRM'),
    ('services', 'Hizmetler', 'Satış & CRM'),
    ('reservations', 'Rezervasyon', 'Satış & CRM'),
    ('waiter', 'Garson', 'Satış & CRM'),
    ('secretariat', 'Sekreterya', 'Sistem'), ('security', 'Güvenlik', 'Sistem'), ('cameras', 'Kameralar', 'Sistem'),
    ('rehber', 'Rehber', 'Sistem'), ('tools', 'Araçlar', 'Sistem'),
    ('factory', 'Fabrika', 'Sistem'),
    ('members', 'Üyelik Yönetimi', 'Merkez'), ('tickets', 'Destek Merkezi', 'Merkez'), ('sms', 'Toplu SMS', 'Merkez'), ('sshmaster', 'Mastertool', 'Merkez'),
    ('uyelik', 'Üyeliğim & Destek', 'Sistem'),
]
HIDDEN = {'mikro'}   # yalnızca MASTER (Mikro ERP); rol ile verilmez

_lock = threading.Lock()
_state = {'at': 0.0, 'ver': -1, 'parents': {}, 'perms': {}, 'conflicts': set(), 'names': []}
_version = [0]
TTL = 30


def bump():
    _version[0] += 1


def catalog():
    """Kullanılabilir düğümler: kataloğun koddaki modüllerle kesişimi + katalogda olmayan yeni modüller ('Diğer')."""
    from . import auth
    info = {k: (t, g) for k, t, g in CATALOG}
    out = []
    for m in auth.MODULE_ROLES:   # koddaki modül sırası korunur (ilk modüle yönlendiren ekranlar için önemli)
        if m in HIDDEN:
            continue
        t, g = info.get(m, (m, 'Diğer'))
        out.append({'key': m, 'title': t, 'group': g, 'parent': None})
        out += [{'key': k, 'title': tt, 'group': gg, 'parent': m} for k, tt, gg in CATALOG if k.startswith(m + '.')]
    return out


def node_keys():
    return [n['key'] for n in catalog()]


# ---------------- Taşıma / tohumlama ----------------
def sync(conn):
    """Kod rollerini ve varsayılan modül izinlerini (bir kez) veritabanına aktarır."""
    from . import auth
    row = conn.execute('SELECT v FROM app_kv WHERE k = ?', (SEED_KEY,)).fetchone()
    try:
        seeded = json.loads(row[0]) if row else {}
    except ValueError:
        seeded = {}
    seen_mods, seen_roles = set(seeded.get('modules', [])), set(seeded.get('roles', []))
    now = db.now()
    existing = {r[0] for r in conn.execute('SELECT name FROM roles')}
    for i, r in enumerate(auth.ROLES):
        if r not in existing:
            conn.execute('INSERT INTO roles (name, description, parent, system, sort, created_at) VALUES (?,?,?,?,?,?)',
                         (r, auth.ROLE_DESC.get(r), None, 1, i, now))
        else:
            conn.execute('UPDATE roles SET system = 1 WHERE name = ?', (r,))
    for m, rs in auth.MODULE_ROLES.items():
        if m in HIDDEN:
            continue
        for r in rs:
            if m not in seen_mods or r not in seen_roles:
                for cap in CAPS:
                    conn.execute('INSERT OR IGNORE INTO role_perms (role, node, cap, allow) VALUES (?,?,?,1)', (r, m, cap))
    seeded = {'modules': sorted(seen_mods | set(auth.MODULE_ROLES)), 'roles': sorted(seen_roles | set(auth.ROLES))}
    conn.execute('INSERT INTO app_kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v', (SEED_KEY, json.dumps(seeded)))
    conn.commit()
    bump()


# ---------------- Durum (önbellek) ----------------
def _load(conn=None):
    own = conn is None
    conn = conn or db.connect()
    try:
        parents = {r[0]: r[1] for r in conn.execute('SELECT name, parent FROM roles')}
        names = [r[0] for r in conn.execute('SELECT name FROM roles ORDER BY system DESC, sort, name COLLATE NOCASE')]
        perms = {}
        for role, node, cap, allow in conn.execute('SELECT role, node, cap, allow FROM role_perms'):
            perms.setdefault(role, {})[(node, cap)] = bool(allow)
        conflicts = {tuple(sorted(r)) for r in conn.execute('SELECT a, b FROM role_conflicts')}
    finally:
        if own:
            conn.close()
    return {'at': time.monotonic(), 'ver': _version[0], 'parents': parents, 'perms': perms, 'conflicts': conflicts, 'names': names}


def state():
    s = _state
    if s['ver'] != _version[0] or time.monotonic() - s['at'] > TTL:
        with _lock:
            if _state['ver'] != _version[0] or time.monotonic() - _state['at'] > TTL:
                try:
                    _state.update(_load())
                except Exception:   # tablo henüz yoksa (ilk kurulum) kod varsayılanlarıyla devam
                    _state.update({'at': time.monotonic(), 'ver': _version[0]})
    return _state


def role_chain(name, parents=None):
    parents = parents if parents is not None else state()['parents']
    out, seen = [], set()
    while name and name not in seen:
        out.append(name)
        seen.add(name)
        name = parents.get(name)
    return out


def node_chain(node):
    parts = node.split('.')
    return ['.'.join(parts[:i]) for i in range(len(parts), 0, -1)]


def role_value(role, node, cap, st=None):
    """(değer, kaynak rol, kaynak düğüm) — değer True/False ya da None (ayar yok)."""
    st = st or state()
    if role == LOCKED:
        return True, role, node
    for r in role_chain(role, st['parents']):
        p = st['perms'].get(r) or {}
        for n in node_chain(node):
            v = p.get((n, cap))
            if v is not None:
                return v, r, n
    return None, None, None


def _combine(roles, node, cap, st):
    vals = [role_value(r, node, cap, st)[0] for r in roles]
    if any(v is False for v in vals):
        return False
    return True if any(v is True for v in vals) else None


_memo = {}


def effective(roles, nodes=None):
    """{düğüm: {'open','read','write'}} — çoklu rol birleşimi (yasak kazanır) ve write ⇒ read ⇒ open zinciri."""
    st = state()
    key = (tuple(sorted(set(roles))), st['at'], st['ver'], tuple(nodes) if nodes else None)
    hit = _memo.get(key)
    if hit is not None:
        return hit
    if len(_memo) > 500:
        _memo.clear()
    _memo[key] = res = _effective(roles, nodes, st)
    return res


def _effective(roles, nodes, st):
    if not st['parents'] and not st['perms']:   # tablo yok (ilk kurulum anı): koddaki eşleme
        from . import auth
        return {m: {'open': True, 'read': True, 'write': True} for m, rs in auth.MODULE_ROLES.items() if set(rs) & set(roles)}
    out = {}
    for n in nodes or node_keys():
        o = _combine(roles, n, 'open', st) is True
        r = o and _combine(roles, n, 'read', st) is True
        w = r and _combine(roles, n, 'write', st) is True
        if o or r or w:
            out[n] = {'open': o, 'read': r, 'write': w}
    return out


def allowed(roles):
    """Okunabilir düğümler (modül listesi; alt modüller noktalı anahtarla)."""
    return [n for n, e in effective(roles).items() if e['read']]


def writable(roles):
    return [n for n, e in effective(roles).items() if e['write']]


def expand(roles):
    """Kişinin rolleri + üst rolleri (koddaki rol adı kontrolleri miras yoluyla da geçsin)."""
    st = state()
    out = []
    for r in roles:
        for x in role_chain(r, st['parents']) or [r]:
            if x not in out:
                out.append(x)
    return out


def role_names():
    st = state()
    if st['names']:
        return list(st['names'])
    from . import auth
    return list(auth.ROLES)


def conflicts(roles):
    """Kişinin rolleri arasındaki çakışmalar: aynı düğüm/yetenekte izin + yasak (yasak geçerli) ve görev ayrılığı çiftleri."""
    st = state()
    cats = {n['key']: n for n in catalog()}
    perm = []
    if len(roles) > 1:
        for n in cats:
            for cap in CAPS:
                vals = {r: role_value(r, n, cap, st) for r in roles}
                yes = [r for r, v in vals.items() if v[0] is True]
                no = [r for r, v in vals.items() if v[0] is False]
                par = cats[n]['parent']
                if yes and no and par and any(x['node'] == par and x['cap'] == cap and x['allow'] == yes and x['deny'] == no for x in perm):
                    continue   # üst modüldeki çakışmanın aynısı (miras) — alt modülde tekrar gösterme
                if yes and no:
                    perm.append({'node': n, 'title': cats[n]['title'], 'group': cats[n]['group'], 'cap': cap, 'cap_label': CAP_LABELS[cap],
                                 'allow': yes, 'deny': no})
    sod = [list(p) for p in st['conflicts'] if p[0] in expand(roles) and p[1] in expand(roles)]
    return {'perm': perm, 'sod': sod}
