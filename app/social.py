"""Kişisel sosyal medya akışı: kullanıcının bağladığı hesapların paylaşımları Şirketten Haberler'de YALNIZCA kendisine görünür.

Anahtarsız kaynaklar (hemen çalışır): RSS / Atom adresi, YouTube kanalı (kanalın herkese açık akışı), Bluesky (herkese açık
API), Mastodon (herkese açık API). OAuth gerektirenler (Instagram / Facebook, X, TikTok) Program Ayarları › Entegrasyonlar'a
uygulama anahtarı girildiğinde açılır. Paylaşımlar 30 dakikada bir çekilir; son 60 paylaşım saklanır.
"""
import html as _html
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from . import config, db

UA = {'User-Agent': 'Mozilla/5.0 (compatible; HepgoERP/2.1; +https://veilox.app)'}
TIMEOUT = 15
INTERVAL = 30 * 60
KEEP = 60
PROVIDERS = {
    'rss': {'title': 'RSS / Atom', 'hint': 'Blog, haber sitesi, podcast… akış adresi (…/feed, …/rss.xml)', 'needs': None},
    'youtube': {'title': 'YouTube kanalı', 'hint': 'Kanal adresi, @kullanıcıadı ya da UC… kanal kimliği', 'needs': None},
    'bluesky': {'title': 'Bluesky', 'hint': 'kullanıcı.bsky.social', 'needs': None},
    'mastodon': {'title': 'Mastodon', 'hint': 'kullanici@sunucu.social', 'needs': None},
    'instagram': {'title': 'Instagram', 'hint': 'Meta uygulama anahtarı gerekir', 'needs': ('META_APP_ID', 'META_APP_SECRET')},
    'facebook': {'title': 'Facebook', 'hint': 'Meta uygulama anahtarı gerekir', 'needs': ('META_APP_ID', 'META_APP_SECRET')},
    'x': {'title': 'X (Twitter)', 'hint': 'X geliştirici anahtarı gerekir (ücretli paket)', 'needs': ('X_CLIENT_ID', 'X_CLIENT_SECRET')},
    'tiktok': {'title': 'TikTok', 'hint': 'TikTok geliştirici anahtarı gerekir', 'needs': ('TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET')},
}


class SocialError(Exception):
    pass


def available():
    """{sağlayıcı: kullanılabilir mi} — OAuth sağlayıcıları anahtar girilince açılır (bağlantı akışı anahtarla birlikte devreye alınır)."""
    return {k: (p['needs'] is None) for k, p in PROVIDERS.items()}


def _get(url, **kw):
    try:
        r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True, **kw)
    except httpx.HTTPError as e:
        raise SocialError(f'Bağlanılamadı: {e}') from e
    if r.status_code >= 400:
        raise SocialError(f'Kaynak yanıt vermedi ({r.status_code})')
    return r


def _iso(v):
    if not v:
        return None
    try:
        if re.match(r'\d{4}-\d{2}-\d{2}T', v):
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
        else:
            dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
    except (ValueError, TypeError):
        return None


def _text(s, n=1000):
    s = re.sub(r'<br\s*/?>|</p>', '\n', s or '', flags=re.I)
    return _html.unescape(re.sub(r'<[^>]+>', '', s)).strip()[:n]


# ---------------- RSS / Atom / YouTube ----------------
NS = {'a': 'http://www.w3.org/2005/Atom', 'media': 'http://search.yahoo.com/mrss/', 'yt': 'http://www.youtube.com/xml/schemas/2015'}


def parse_feed(xml):
    """RSS 2.0 ya da Atom → (başlık, [paylaşım]) ."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise SocialError('Geçerli bir RSS / Atom akışı değil') from e
    posts = []
    if root.tag.endswith('feed'):   # Atom (YouTube dahil)
        title = (root.findtext('a:title', default='', namespaces=NS) or '').strip()
        for e in root.findall('a:entry', NS)[:KEEP]:
            link = next((l.get('href') for l in e.findall('a:link', NS) if l.get('rel', 'alternate') == 'alternate'), None)
            thumb = e.find('.//media:thumbnail', NS)
            vid = e.findtext('yt:videoId', default='', namespaces=NS)
            body = e.findtext('.//media:description', default='', namespaces=NS) or e.findtext('a:summary', default='', namespaces=NS) or ''
            posts.append({'ext_id': e.findtext('a:id', default=link or '', namespaces=NS), 'url': link,
                          'text': (e.findtext('a:title', default='', namespaces=NS) or '').strip() + (('\n' + _text(body, 600)) if body else ''),
                          'media': thumb.get('url') if thumb is not None else None, 'media_kind': 'video' if vid else ('image' if thumb is not None else None),
                          'posted_at': _iso(e.findtext('a:published', default='', namespaces=NS) or e.findtext('a:updated', default='', namespaces=NS))})
        return title, posts
    ch = root.find('channel')
    if ch is None:
        raise SocialError('Geçerli bir RSS / Atom akışı değil')
    title = (ch.findtext('title') or '').strip()
    for it in ch.findall('item')[:KEEP]:
        enc = it.find('enclosure')
        mt = it.find('media:content', NS) or it.find('media:thumbnail', NS)
        img = (enc.get('url') if enc is not None and (enc.get('type') or '').startswith('image') else None) or (mt.get('url') if mt is not None else None)
        if not img:
            m = re.search(r'<img[^>]+src="([^"]+)"', it.findtext('description') or '')
            img = m.group(1) if m else None
        posts.append({'ext_id': it.findtext('guid') or it.findtext('link') or it.findtext('title'), 'url': it.findtext('link'),
                      'text': ((it.findtext('title') or '').strip() + '\n' + _text(it.findtext('description'), 600)).strip(),
                      'media': img, 'media_kind': 'image' if img else None, 'posted_at': _iso(it.findtext('pubDate'))})
    return title, posts


def youtube_feed(handle):
    h = handle.strip()
    m = re.search(r'(UC[0-9A-Za-z_-]{22})', h)
    if not m:
        url = h if h.startswith('http') else f'https://www.youtube.com/{h if h.startswith("@") else "@" + h}'
        page = _get(url).text
        m = re.search(r'"(?:channelId|externalId)":"(UC[0-9A-Za-z_-]{22})"', page) or re.search(r'channel/(UC[0-9A-Za-z_-]{22})', page)
        if not m:
            raise SocialError('YouTube kanalı bulunamadı')
    return f'https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}'


# ---------------- Bluesky / Mastodon ----------------
def bluesky_posts(handle):
    h = handle.strip().lstrip('@')
    prof = _get('https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile', params={'actor': h}).json()
    d = _get('https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed', params={'actor': h, 'limit': 40, 'filter': 'posts_no_replies'}).json()
    posts = []
    for it in d.get('feed', []):
        p = it.get('post') or {}
        rec = p.get('record') or {}
        emb = p.get('embed') or {}
        img = ((emb.get('images') or [{}])[0].get('thumb')) or ((emb.get('external') or {}).get('thumb'))
        rkey = (p.get('uri') or '').rsplit('/', 1)[-1]
        posts.append({'ext_id': p.get('uri'), 'url': f'https://bsky.app/profile/{h}/post/{rkey}', 'text': (rec.get('text') or '')[:1000],
                      'media': img, 'media_kind': 'image' if img else None, 'posted_at': _iso(rec.get('createdAt'))})
    return prof.get('displayName') or h, prof.get('avatar'), posts


def mastodon_posts(handle):
    h = handle.strip().lstrip('@')
    if '@' not in h:
        raise SocialError('Mastodon adresi kullanici@sunucu biçiminde olmalı')
    user, host = h.split('@', 1)
    acc = _get(f'https://{host}/api/v1/accounts/lookup', params={'acct': user}).json()
    sts = _get(f"https://{host}/api/v1/accounts/{acc['id']}/statuses", params={'limit': 40, 'exclude_replies': 'true'}).json()
    posts = []
    for s in sts:
        s = s.get('reblog') or s
        media = (s.get('media_attachments') or [{}])[0]
        posts.append({'ext_id': s.get('uri') or s.get('id'), 'url': s.get('url'), 'text': _text(s.get('content')),
                      'media': media.get('preview_url'), 'media_kind': media.get('type') if media.get('preview_url') else None, 'posted_at': _iso(s.get('created_at'))})
    return acc.get('display_name') or user, acc.get('avatar'), posts


# ---------------- çekme / saklama ----------------
def resolve(provider, handle):
    """Hesap eklenirken: (görünen ad, avatar, akış adresi, paylaşımlar)."""
    if provider == 'rss':
        url = handle.strip()
        if not url.startswith('http'):
            url = 'https://' + url
        title, posts = parse_feed(_get(url).content)
        return title or url, None, url, posts
    if provider == 'youtube':
        url = youtube_feed(handle)
        title, posts = parse_feed(_get(url).content)
        return title or handle, None, url, posts
    if provider == 'bluesky':
        name, avatar, posts = bluesky_posts(handle)
        return name, avatar, None, posts
    if provider == 'mastodon':
        name, avatar, posts = mastodon_posts(handle)
        return name, avatar, None, posts
    raise SocialError(f"{PROVIDERS.get(provider, {}).get('title', provider)} için Program Ayarları › Entegrasyonlar'a uygulama anahtarı girilmeli")


def fetch(acc):
    if acc['provider'] in ('rss', 'youtube'):
        return parse_feed(_get(acc['feed_url']).content)[1]
    if acc['provider'] == 'bluesky':
        return bluesky_posts(acc['handle'])[2]
    if acc['provider'] == 'mastodon':
        return mastodon_posts(acc['handle'])[2]
    return []


def store(conn, acc_id, posts):
    now = db.now()
    n = 0
    for p in posts:
        if not p.get('ext_id'):
            continue
        cur = conn.execute('''INSERT OR IGNORE INTO social_posts (account_id, ext_id, text, url, media, media_kind, posted_at, fetched_at)
                              VALUES (?,?,?,?,?,?,?,?)''', (acc_id, str(p['ext_id'])[:500], (p.get('text') or '')[:2000], p.get('url'), p.get('media'),
                                                           p.get('media_kind'), p.get('posted_at') or now, now))
        n += cur.rowcount
    # son KEEP paylaşım tutulur
    conn.execute('''DELETE FROM social_posts WHERE account_id = ? AND id NOT IN
                    (SELECT id FROM social_posts WHERE account_id = ? ORDER BY posted_at DESC LIMIT ?)''', (acc_id, acc_id, KEEP))
    return n


def refresh(conn, acc):
    try:
        n = store(conn, acc['id'], fetch(acc))
        conn.execute('UPDATE social_accounts SET last_sync = ?, last_error = NULL WHERE id = ?', (db.now(), acc['id']))
    except Exception as e:   # bir hesabın hatası diğerlerini durdurmasın
        n = 0
        conn.execute('UPDATE social_accounts SET last_sync = ?, last_error = ? WHERE id = ?', (db.now(), str(e)[:300], acc['id']))
    conn.commit()
    return n


def _loop():
    time.sleep(60)
    while True:
        try:
            with db.connect() as conn:
                for acc in db.rows(conn.execute("SELECT * FROM social_accounts WHERE provider IN ('rss','youtube','bluesky','mastodon')")):
                    refresh(conn, acc)
        except Exception:
            pass
        time.sleep(INTERVAL)


_started = False


def start():
    global _started
    if not _started and config.PRINTER_POLL_ENABLED:   # testlerde (CAYMAZ_PRINTER_POLL=0) arka plan çekimi yok
        _started = True
        threading.Thread(target=_loop, daemon=True, name='social-sync').start()
