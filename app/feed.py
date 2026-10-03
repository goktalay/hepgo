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
    return d


def list_posts(conn, since=None, limit=60, located=False, viewer_id=None):
    where = 'f.deleted_at IS NULL'
    args = []
    if located:
        where += ' AND f.lat IS NOT NULL AND f.lng IS NOT NULL'
    if since:
        where += ' AND f.created_at >= ?'
        args.append(since)
    rows = db.rows(conn.execute(
        f'''SELECT f.id, f.kind, f.author_id, f.text, f.media, f.lat, f.lng, f.ref_type, f.ref_id, f.ref_link, f.created_at,
                   u.full_name AS author_name, u.photo AS author_photo
            FROM feed_posts f LEFT JOIN users u ON u.id = f.author_id
            WHERE {where} ORDER BY f.created_at DESC, f.id DESC LIMIT ?''', (*args, min(limit, 300))))
    posts = [_row(r) for r in rows]
    if posts:
        ids = [p['id'] for p in posts]
        ph = ','.join('?' * len(ids))
        counts = {}
        for pid, emoji, n in conn.execute(
                f'SELECT post_id, emoji, COUNT(*) FROM feed_reactions WHERE post_id IN ({ph}) GROUP BY post_id, emoji', ids):
            counts.setdefault(pid, {})[emoji] = n
        comments = {pid: n for pid, n in conn.execute(
            f'SELECT post_id, COUNT(*) FROM feed_comments WHERE post_id IN ({ph}) AND deleted_at IS NULL GROUP BY post_id', ids)}
        mine = {}
        if viewer_id:
            mine = {pid: emoji for pid, emoji in conn.execute(
                f'SELECT post_id, emoji FROM feed_reactions WHERE user_id = ? AND post_id IN ({ph})', (viewer_id, *ids))}
        for p in posts:
            p['reactions'] = counts.get(p['id'], {})
            p['comment_count'] = comments.get(p['id'], 0)
            p['my_reaction'] = mine.get(p['id'])
    return posts


REACTIONS = ('👍', '❤️', '😂', '😮', '😢', '👏', '🎉')   # izin verilen tepki simgeleri


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


def list_comments(conn, post_id):
    rows = db.rows(conn.execute(
        '''SELECT c.id, c.user_id, c.text, c.created_at, u.full_name AS author_name, u.photo AS author_photo
           FROM feed_comments c LEFT JOIN users u ON u.id = c.user_id
           WHERE c.post_id = ? AND c.deleted_at IS NULL ORDER BY c.created_at, c.id''', (post_id,)))
    return rows


def add_comment(conn, post_id, user_id, text):
    text = (text or '').strip()[:1000]
    if not text:
        return None
    if not conn.execute('SELECT 1 FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone():
        return None
    cur = conn.execute('INSERT INTO feed_comments (post_id, user_id, text, created_at) VALUES (?,?,?,?)',
                       (post_id, user_id, text, db.now()))
    return cur.lastrowid


def delete_comment(conn, comment_id, viewer):
    row = conn.execute('SELECT user_id FROM feed_comments WHERE id = ? AND deleted_at IS NULL', (comment_id,)).fetchone()
    if not row:
        return False
    is_admin = ('admin' in viewer.get('modules', [])) or viewer.get('master')
    if row[0] != viewer['id'] and not is_admin:
        return False
    conn.execute('UPDATE feed_comments SET deleted_at = ? WHERE id = ?', (db.now(), comment_id))
    return True


def delete(conn, post_id, viewer):
    row = conn.execute('SELECT author_id, media FROM feed_posts WHERE id = ? AND deleted_at IS NULL', (post_id,)).fetchone()
    if not row:
        return False
    is_admin = ('admin' in viewer.get('modules', [])) or viewer.get('master')
    if row[0] != viewer['id'] and not is_admin:
        return False
    conn.execute('UPDATE feed_posts SET deleted_at = ? WHERE id = ?', (db.now(), post_id))
    return True
