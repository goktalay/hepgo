"""Şirketten Haberler — pano akışı (Facebook tarzı). Sistem olayları (işe alım, çıkış, uçuş, sipariş, toplantı…) ve
kullanıcı paylaşımları (resim/video/ses + konum) tek akışta. Sistem olayları için şirket logosu, kullanıcı paylaşımı
için kişinin fotoğrafı gösterilir. İki görünüm: akış (dashboard) ve harita (konumlu paylaşımlar)."""
import json

from . import db

KINDS = {   # olay türü → (ikon anahtarı, varsayılan başlık öneki)
    'USER': 'megaphone', 'HIRE': 'badgePerson', 'TERMINATION': 'door', 'FLIGHT': 'plane',
    'ORDER': 'box', 'MEETING': 'calendar', 'ANNOUNCE': 'megaphone',
}


def add_event(conn, kind, text, ref_type=None, ref_id=None, ref_link=None, media=None, lat=None, lng=None):
    """Sistem olayı ekler (author_id NULL → şirket logosu). Akışı bozmamak için her çağrı try/except ile sarılmalı."""
    conn.execute('''INSERT INTO feed_posts (kind, author_id, text, media, lat, lng, ref_type, ref_id, ref_link, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                 (kind, None, text, json.dumps(media) if media else None, lat, lng, ref_type, ref_id, ref_link, db.now()))


def safe_event(kind, text, **kw):
    """Router akışlarından güvenli çağrı: kendi bağlantısını açar, hata akışı bozmaz."""
    try:
        with db.connect() as conn:
            add_event(conn, kind, text, **kw)
            conn.commit()
    except Exception:   # noqa: BLE001
        pass


def add_post(conn, author_id, text, media=None, lat=None, lng=None):
    cur = conn.execute('''INSERT INTO feed_posts (kind, author_id, text, media, lat, lng, created_at)
                          VALUES ('USER',?,?,?,?,?,?)''',
                       (author_id, text, json.dumps(media) if media else None, lat, lng, db.now()))
    return cur.lastrowid


def _row(r):
    d = dict(r)
    try:
        d['media'] = json.loads(d['media']) if d.get('media') else []
    except (ValueError, TypeError):
        d['media'] = []
    d['system'] = d.get('author_id') is None
    d['pinned'] = bool(d.get('pinned_at'))
    return d


def list_posts(conn, since=None, limit=60, located=False, viewer_id=None, saved=False, before=None, after=None):
    """before=(created_at, id): bu paylaşımdan eskiler (sonsuz kaydırmada sonraki sayfa); after=id: bundan yeniler (canlı ekleme)."""
    where = 'f.deleted_at IS NULL'
    args = []
    # Sabitli paylaşım: ilk sayfada (before/after/saved/located yokken) en üstte; her sorguda normal listeden hariç (tekrarlanmasın)
    pinned = db.row(conn.execute('SELECT id FROM feed_posts WHERE deleted_at IS NULL AND pinned_at IS NOT NULL ORDER BY pinned_at DESC LIMIT 1'))
    if pinned:
        where += ' AND f.id != ?'
        args.append(pinned['id'])
    if before:
        where += ' AND (f.created_at < ? OR (f.created_at = ? AND f.id < ?))'
        args += [before[0], before[0], before[1]]
    if after:
        where += ' AND f.id > ?'
        args.append(after)
    if saved:   # yalnız izleyenin favorilere kaydettikleri
        where += ' AND f.id IN (SELECT post_id FROM feed_saves WHERE user_id = ?)'
        args.append(viewer_id or 0)
    if located:
        where += ' AND f.lat IS NOT NULL AND f.lng IS NOT NULL'
    if since:
        where += ' AND f.created_at >= ?'
        args.append(since)
    rows = db.rows(conn.execute(
        f'''SELECT f.id, f.kind, f.author_id, f.text, f.media, f.lat, f.lng, f.ref_type, f.ref_id, f.ref_link, f.created_at, f.pinned_at,
                   u.full_name AS author_name, u.photo AS author_photo
            FROM feed_posts f LEFT JOIN users u ON u.id = f.author_id
            WHERE {where} ORDER BY f.created_at DESC, f.id DESC LIMIT ?''', (*args, min(limit, 300))))
    if pinned and not before and not after and not saved and not located:
        top = db.row(conn.execute('''SELECT f.id, f.kind, f.author_id, f.text, f.media, f.lat, f.lng, f.ref_type, f.ref_id, f.ref_link, f.created_at, f.pinned_at,
                                            u.full_name AS author_name, u.photo AS author_photo
                                     FROM feed_posts f LEFT JOIN users u ON u.id = f.author_id WHERE f.id = ?''', (pinned['id'],)))
        if top:
            rows = [top, *rows]
    posts = [_row(r) for r in rows]
    if posts:
        ids = [p['id'] for p in posts]
        ph = ','.join('?' * len(ids))
        counts = {}
        for pid, emoji, n in conn.execute(
                f'SELECT post_id, emoji, COUNT(*) FROM feed_reactions WHERE post_id IN ({ph}) GROUP BY post_id, emoji', ids):
            counts.setdefault(pid, {})[emoji] = n
        views = {pid: n for pid, n in conn.execute(
            f'SELECT post_id, COUNT(*) FROM feed_views WHERE post_id IN ({ph}) GROUP BY post_id', ids)}
        comments = {pid: n for pid, n in conn.execute(
            f'SELECT post_id, COUNT(*) FROM feed_comments WHERE post_id IN ({ph}) AND deleted_at IS NULL GROUP BY post_id', ids)}
        mine, saves = {}, set()
        if viewer_id:
            mine = {pid: emoji for pid, emoji in conn.execute(
                f'SELECT post_id, emoji FROM feed_reactions WHERE user_id = ? AND post_id IN ({ph})', (viewer_id, *ids))}
            saves = {r[0] for r in conn.execute(f'SELECT post_id FROM feed_saves WHERE user_id = ? AND post_id IN ({ph})', (viewer_id, *ids))}
        for p in posts:
            p['reactions'] = counts.get(p['id'], {})
            p['comment_count'] = comments.get(p['id'], 0)
            p['view_count'] = views.get(p['id'], 0)
            p['my_reaction'] = mine.get(p['id'])
            p['saved'] = p['id'] in saves
    return posts


REACTIONS = ('👍', '❤️', '😂', '😮', '😢', '👏', '🎉')   # izin verilen tepki simgeleri


def set_pinned(conn, post_id, user_id, on):
    """Master: paylaşımı üste sabitle / kaldır. Aynı anda tek sabitli paylaşım olur."""
    if not conn.execute('SELECT 1 FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone():
        return None
    if on:
        conn.execute('UPDATE feed_posts SET pinned_at = NULL, pinned_by = NULL WHERE pinned_at IS NOT NULL')
        conn.execute('UPDATE feed_posts SET pinned_at = ?, pinned_by = ? WHERE id = ?', (db.now(), user_id, post_id))
    else:
        conn.execute('UPDATE feed_posts SET pinned_at = NULL, pinned_by = NULL WHERE id = ?', (post_id,))
    return bool(on)


def react(conn, post_id, user_id, emoji):
    """Tek tepki/kullanıcı: aynı emoji tekrar → kaldırır (toggle); farklı emoji → değiştirir; geçersiz emoji → kaldırır."""
    if not conn.execute('SELECT 1 FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone():
        return None
    cur = conn.execute('SELECT emoji FROM feed_reactions WHERE post_id = ? AND user_id = ?', (post_id, user_id)).fetchone()
    if emoji not in REACTIONS or (cur and cur[0] == emoji):
        conn.execute('DELETE FROM feed_reactions WHERE post_id = ? AND user_id = ?', (post_id, user_id))
        return None
    conn.execute('INSERT OR REPLACE INTO feed_reactions (post_id, user_id, emoji, created_at) VALUES (?,?,?,?)',
                 (post_id, user_id, emoji, db.now()))
    return emoji


def toggle_save(conn, post_id, user_id):
    """Favorilere kaydet / çıkar (yalnız kullanıcının kendisi görür). Paylaşım yoksa None."""
    if not conn.execute('SELECT 1 FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone():
        return None
    if conn.execute('DELETE FROM feed_saves WHERE post_id = ? AND user_id = ?', (post_id, user_id)).rowcount:
        return False
    conn.execute('INSERT INTO feed_saves (post_id, user_id, created_at) VALUES (?,?,?)', (post_id, user_id, db.now()))
    return True


def list_comments(conn, post_id, viewer_id=None):
    """Yorumlar + yanıtlar (tek seviye, parent_id) + kalp sayısı / benim kalbim. Yanıtı olan silinmiş ana yorum, yanıtlar
    kopmasın diye metinsiz yer tutucu olarak döner (başkasının yanıtı silinmez — bkz. delete_comment)."""
    rows = db.rows(conn.execute(
        """SELECT c.id, c.user_id, c.parent_id, c.text, c.created_at, c.deleted_at, u.full_name AS author_name, u.photo AS author_photo
           FROM feed_comments c LEFT JOIN users u ON u.id = c.user_id
           WHERE c.post_id = ? ORDER BY c.created_at, c.id""", (post_id,)))
    live_parents = {r['parent_id'] for r in rows if r['parent_id'] and not r['deleted_at']}
    out = []
    for r in rows:
        if r['deleted_at']:
            if r['parent_id'] or r['id'] not in live_parents:
                continue
            r.update(text='', user_id=None, author_name=None, author_photo=None, deleted=True)
        r.pop('deleted_at', None)
        out.append(r)
    if out:
        ids = [r['id'] for r in out]
        ph = ','.join('?' * len(ids))
        likes = dict(conn.execute(f'SELECT comment_id, COUNT(*) FROM feed_comment_likes WHERE comment_id IN ({ph}) GROUP BY comment_id', ids).fetchall())
        mine = {x[0] for x in conn.execute(f'SELECT comment_id FROM feed_comment_likes WHERE user_id = ? AND comment_id IN ({ph})', (viewer_id or 0, *ids))}
        for r in out:
            r['like_count'] = likes.get(r['id'], 0)
            r['liked'] = r['id'] in mine
    return out


def add_comment(conn, post_id, user_id, text, parent_id=None):
    """Yorum ya da yanıt. Yanıta yanıt da ana yorumun altına bağlanır (tek seviye, Instagram gibi)."""
    text = (text or '').strip()[:1000]
    if not text:
        return None
    if not conn.execute('SELECT 1 FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone():
        return None
    if parent_id:
        par = conn.execute('SELECT id, parent_id, post_id FROM feed_comments WHERE id = ?', (parent_id,)).fetchone()
        if not par or par[2] != post_id:
            return None
        parent_id = par[1] or par[0]
    cur = conn.execute('INSERT INTO feed_comments (post_id, user_id, text, created_at, parent_id) VALUES (?,?,?,?,?)',
                       (post_id, user_id, text, db.now(), parent_id or None))
    return cur.lastrowid


def like_comment(conn, comment_id, user_id):
    """Yoruma kalp: aç / kapat. (beğenildi mi, toplam) döner; yorum yoksa None."""
    if not conn.execute('SELECT 1 FROM feed_comments WHERE id = ? AND deleted_at IS NULL', (comment_id,)).fetchone():
        return None
    if conn.execute('DELETE FROM feed_comment_likes WHERE comment_id = ? AND user_id = ?', (comment_id, user_id)).rowcount:
        liked = False
    else:
        conn.execute('INSERT INTO feed_comment_likes (comment_id, user_id, created_at) VALUES (?,?,?)', (comment_id, user_id, db.now()))
        liked = True
    n = conn.execute('SELECT COUNT(*) FROM feed_comment_likes WHERE comment_id = ?', (comment_id,)).fetchone()[0]
    return liked, n


def comment_likers(conn, comment_id):
    return db.rows(conn.execute(
        """SELECT l.created_at, u.id AS user_id, u.full_name, u.photo FROM feed_comment_likes l JOIN users u ON u.id = l.user_id
           WHERE l.comment_id = ? ORDER BY l.created_at DESC""", (comment_id,)))


def delete_comment(conn, comment_id, viewer):
    """Yorumu yalnızca yazan siler — başkasının yorumunu kimse (yönetici / sistem sahibi dahil) silemez."""
    row = conn.execute('SELECT user_id FROM feed_comments WHERE id = ? AND deleted_at IS NULL', (comment_id,)).fetchone()
    if not row or row[0] != viewer['id']:
        return False
    conn.execute('UPDATE feed_comments SET deleted_at = ? WHERE id = ?', (db.now(), comment_id))
    return True


def delete(conn, post_id, viewer):
    """Paylaşımı yalnızca sahibi siler — başkasının paylaşımını kimse (yönetici / sistem sahibi / merkez destek dahil)
    silemez. Sistem olayları (yazarı yok) yöneticice kaldırılabilir."""
    row = conn.execute('SELECT author_id, media FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not row:
        return False
    if row[0] is None:
        if not (('admin' in viewer.get('modules', [])) or viewer.get('master')):
            return False
    elif row[0] != viewer['id']:
        return False
    conn.execute('UPDATE feed_posts SET deleted_at = ? WHERE id = ?', (db.now(), post_id))
    return True


def remove_by_master(conn, post_id, master, reason):
    """Sistem sahibi (MASTER) bir kullanıcının paylaşımını sebep yazarak kaldırır. Paylaşım akıştan kalkar; sebep sahibine
    bildirim olarak gider (zil + anlık). Dönüş: (sahibin kullanıcı kimliği, paylaşım özeti) ya da None."""
    row = conn.execute('SELECT author_id, text, media FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not row:
        return None
    now = db.now()
    conn.execute('UPDATE feed_posts SET deleted_at = ?, removed_by = ?, removed_reason = ?, pinned_at = NULL, pinned_by = NULL WHERE id = ?',
                 (now, master['id'], reason, post_id))
    return row[0], snippet(row[1], row[2])


def removed_unseen(conn, user_id):
    """Sahibinin henüz görmediği, master tarafından kaldırılmış paylaşımları (sebebiyle)."""
    return db.rows(conn.execute(
        """SELECT f.id, f.text, f.media, f.deleted_at, f.removed_reason, u.full_name AS removed_by_name
           FROM feed_posts f LEFT JOIN users u ON u.id = f.removed_by
           WHERE f.author_id = ? AND f.removed_reason IS NOT NULL AND f.removed_seen_at IS NULL ORDER BY f.deleted_at DESC""", (user_id,)))


def mark_removed_seen(conn, user_id):
    conn.execute('UPDATE feed_posts SET removed_seen_at = ? WHERE author_id = ? AND removed_reason IS NOT NULL AND removed_seen_at IS NULL',
                 (db.now(), user_id))


# ---------- Görülme (ana ekranda akışı gören kullanıcı) + bildirim ----------
SEEN_KEY = 'feed_seen'


def seen_id(conn, user_id):
    r = conn.execute('SELECT value FROM user_prefs WHERE user_id=? AND key=?', (user_id, SEEN_KEY)).fetchone()
    try:
        return int(r[0]) if r and r[0] else None
    except (TypeError, ValueError):
        return None


def mark_seen(conn, user_id, last_id):
    """Akışı gördü: en son görülen paylaşım id'si (yalnızca ileri gider)."""
    cur = seen_id(conn, user_id) or 0
    top = conn.execute('SELECT COALESCE(MAX(id),0) FROM feed_posts').fetchone()[0]
    val = max(cur, min(int(last_id or 0), top))
    conn.execute('INSERT INTO user_prefs (user_id, key, value) VALUES (?,?,?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value',
                 (user_id, SEEN_KEY, str(val)))
    return val


def unseen_posts(conn, user_id):
    """Kullanıcının henüz görmediği, başkalarının paylaşımları (sistem olayları hariç). Hiç görmediyse son 2 gün."""
    seen = seen_id(conn, user_id)
    base = """SELECT f.id, f.text, f.media, u.full_name AS author_name FROM feed_posts f LEFT JOIN users u ON u.id=f.author_id
              WHERE f.kind='USER' AND f.deleted_at IS NULL AND f.author_id IS NOT NULL AND f.author_id != ?"""
    if seen is None:
        return db.rows(conn.execute(base + " AND f.created_at >= strftime('%Y-%m-%dT%H:%M:%S','now','localtime','-2 days') ORDER BY f.id DESC LIMIT 20", (user_id,)))
    return db.rows(conn.execute(base + ' AND f.id > ? ORDER BY f.id DESC LIMIT 20', (user_id, seen)))


def snippet(text, media=None):
    t = ' '.join((text or '').split())
    if t:
        return t[:70] + ('…' if len(t) > 70 else '')
    try:
        m = json.loads(media) if isinstance(media, str) else (media or [])
    except ValueError:
        m = []
    kinds = {x.get('type') for x in m}
    return '🎬 video paylaştı' if 'video' in kinds else '🖼 fotoğraf paylaştı' if 'image' in kinds else '🎤 ses paylaştı' if 'audio' in kinds else 'paylaşım yaptı'


def can_see_home(modules):
    """Ana ekranı (pano / haber akışı) görebilen kullanıcı mı? Rolsüz ve yalnız-Güvenlik hesaplar göremez (istemci: securityOnly)."""
    mods = list(modules or [])
    return bool(mods) and not all(m in ('security', 'announcements') for m in mods)


def push_recipients(conn, author_id, exclude=(), mute_key='feed-new'):
    """Yeni paylaşımın telefon/OS bildirimi alıcıları: aktif, silinmemiş, izinli/raporlu olmayan (master hariç), 'yeni paylaşım'
    bildirimini kapatmamış ve ana ekranı görebilen kullanıcılar. Süresi bitmiş merkez-destek temsil hesapları ve uygulaması şu an
    ekranda açık olanlar (exclude: uygulama içi bildirim yeter) hariç."""
    from . import auth, config, notifications
    absent = auth.absent_map(conn)
    roles = {}
    for uid, role in conn.execute('SELECT user_id, role FROM user_roles'):
        roles.setdefault(uid, []).append(role)
    now = db.now()
    out = []
    rows = db.rows(conn.execute('SELECT id, username, prefs, password_hash, support_until FROM users '
                                'WHERE active=1 AND deleted_at IS NULL AND id != ?', (author_id,)))
    for r in rows:
        if r['id'] in exclude:
            continue
        master = auth.is_master(r['username'])
        if r['password_hash'] == '*FEDERATED*' and not (r['support_until'] and r['support_until'] > now):
            continue
        if r['id'] in absent and not master:
            continue
        if mute_key in notifications._muted(r):
            continue
        mods = list(auth.MODULE_ROLES.keys()) if master else auth.allowed_modules(roles.get(r['id'], []))
        if config.MODULES is not None:
            mods = [m for m in mods if m in config.MODULES]
        if can_see_home(mods):
            out.append(r['id'])
    return out


def reactors(conn, post_id):
    return db.rows(conn.execute(
        """SELECT r.emoji, r.created_at, u.id AS user_id, u.full_name, u.photo FROM feed_reactions r
           JOIN users u ON u.id=r.user_id WHERE r.post_id=? ORDER BY r.created_at DESC""", (post_id,)))
