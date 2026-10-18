"""Firma logolarını web'den bulma (Firma Yönetimi › Logolarını bul). Konum bulma (geocode.py) ile aynı kalıp:
toplu tarama arka planda tek iş parçacığında çalışır, ilerleme STATE'te okunur.

Sıra (firma başına):
  1) Alan adı: web sitesi alanından, yoksa e-posta alanından (genel servisler — gmail, hotmail … — sayılmaz) türetilir.
     Alan adı varsa site HTML'i (5 sn, 2 MB sınır) okunur: apple-touch-icon → <link rel="icon"> (en büyüğü) → og:image;
     ardından sabit yollar /apple-touch-icon.png ve /favicon.ico denenir.
  2) Site vermezse Clearbit (logo.clearbit.com/<alan>) ve Google favicon servisi (s2/favicons, 128 px).
  3) Hiç alan adı yoksa firma adı DuckDuckGo HTML aramasında aranır; ilk sonucun alan adıyla 1–2 yinelenir (bulunamazsa atlanır).
Küçük (<32 px) ya da boş görseller reddedilir; ICO → PNG çevrilir. Bulunan görsel data/uploads/logos/<rastgele>.<uzantı>
olarak kaydedilir (elle yüklenen logo ile aynı yol kalıbı) ve companies.logo alanına yazılır."""
import html
import io
import re
import secrets
import threading
import time
import urllib.parse

import httpx

from . import config, db

UA = 'Mozilla/5.0 (compatible; HEPGO-ERP/1.0; firma logo; +https://hepgo.com)'
TIMEOUT = 5.0            # istek başına (sn)
MAX_BYTES = 2 * 1024 * 1024
MIN_PX = 32              # bundan küçük görsel logo sayılmaz
PER_COMPANY = 25.0       # firma başına toplam süre bütçesi (sn)
MAX_PER_RUN = 50         # bir çağrıda en çok bu kadar firma taranır
# e-posta alanından firma alan adı türetilmez (genel posta servisleri)
GENERIC_MAIL = {'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.com.tr', 'outlook.com', 'outlook.com.tr', 'live.com',
                'yahoo.com', 'yahoo.com.tr', 'yandex.com', 'yandex.com.tr', 'icloud.com', 'me.com', 'mail.com', 'mynet.com',
                'protonmail.com', 'proton.me', 'windowslive.com', 'msn.com', 'aol.com', 'superonline.com', 'ttmail.com'}
CT_EXT = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif',
          'image/svg+xml': '.svg', 'image/x-icon': '.ico', 'image/vnd.microsoft.icon': '.ico', 'image/ico': '.ico'}

STATE = {'running': False, 'total': 0, 'done': 0, 'found': 0, 'skipped': 0, 'failed': 0, 'current': '', 'items': [],
         'started_at': None, 'finished_at': None, 'error': None}
_lock = threading.Lock()
_worker = None   # son başlatılan iş parçacığı (testlerin beklemesi için)


# ---- Ağ
def fetch(url, timeout=TIMEOUT):
    """(durum kodu, content-type, gövde) — gövde en çok MAX_BYTES; hata durumunda istisna yayılır (çağıran yakalar).
    Testler bu fonksiyonu sahte ile değiştirir."""
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={'User-Agent': UA, 'Accept': '*/*'}) as c:
        with c.stream('GET', url) as r:
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    break
            return r.status_code, (r.headers.get('content-type') or '').split(';')[0].strip().lower(), bytes(buf[:MAX_BYTES])


class _Budget:
    """Firma başına süre bütçesi: her istek kalan süreyle sınırlanır; bütçe bitince istekler atlanır."""
    def __init__(self, seconds=PER_COMPANY):
        self.deadline = time.monotonic() + seconds

    def get(self, url):
        left = self.deadline - time.monotonic()
        if left <= 0.5:
            return None
        try:
            return fetch(url, timeout=min(TIMEOUT, left))
        except Exception:   # noqa: BLE001 — ağ hatası: kaynak yok sayılır
            return None


# ---- Alan adı türetme
def domain_of(website=None, email=None):
    """Web sitesi (öncelikli) ya da e-posta alanından alan adı; 'www.' atılır; genel posta servisleri yok sayılır."""
    if website:
        w = website.strip()
        if not re.match(r'^https?://', w, re.I):
            w = 'https://' + w
        host = (urllib.parse.urlsplit(w).hostname or '').lower().strip('.')
        host = host[4:] if host.startswith('www.') else host
        if '.' in host:
            return host
    if email and '@' in email:
        host = email.rsplit('@', 1)[1].strip().lower().strip('.>')
        host = host[4:] if host.startswith('www.') else host
        if '.' in host and host not in GENERIC_MAIL:
            return host
    return None


def duckduckgo_domain(name, budget):
    """Firma adını DuckDuckGo HTML aramasında arar; ilk organik sonucun alan adını döner (yoksa None)."""
    q = urllib.parse.urlencode({'q': name})
    r = budget.get(f'https://html.duckduckgo.com/html/?{q}')
    if not r or r[0] != 200:
        return None
    text = r[2].decode('utf-8', errors='replace')
    for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"', text):
        href = html.unescape(m.group(1))
        # DDG yönlendirme bağlantısı: //duckduckgo.com/l/?uddg=<hedef>&…
        u = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get('uddg', [href])[0]
        d = domain_of(u)
        if d and 'duckduckgo.com' not in d:
            return d
    return None


# ---- Görsel doğrulama / dönüştürme
def check_image(ctype, data):
    """Kabul edilirse (uzantı, veri) döner; aksi halde None. SVG boyut denetimi olmadan kabul edilir; ICO → PNG çevrilir;
    öteki biçimlerde en küçük kenar MIN_PX altındaysa reddedilir."""
    if not data or len(data) < 64:
        return None
    ext = CT_EXT.get(ctype)
    head = data[:512].lstrip()
    if ext is None or ext == '.svg':   # content-type eksik/yanlış olabilir: imzadan tanı
        if head.startswith(b'<?xml') or head.startswith(b'<svg') or b'<svg' in head:
            return ('.svg', data) if b'<svg' in data[:4096] else None
        if ext == '.svg':
            return None
    if ext is None:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            ext = '.png'
        elif data[:3] == b'\xff\xd8\xff':
            ext = '.jpg'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            ext = '.gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            ext = '.webp'
        elif data[:4] == b'\x00\x00\x01\x00':
            ext = '.ico'
        else:
            return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if ext == '.ico':   # en büyük kare seçilir, PNG'ye çevrilir
            sizes = sorted(getattr(im, 'info', {}).get('sizes') or {im.size}, key=lambda s: s[0] * s[1], reverse=True)
            im.size = sizes[0]
            im.load()
            if min(im.size) < MIN_PX:
                return None
            out = io.BytesIO()
            im.convert('RGBA').save(out, format='PNG')
            return '.png', out.getvalue()
        w, h = im.size
        if min(w, h) < MIN_PX:
            return None
        return ext, data
    except Exception:   # noqa: BLE001 — bozuk / okunamayan görsel
        return None


# ---- Kaynaklar
def _abs(base, href):
    return urllib.parse.urljoin(base, html.unescape(href.strip()))


def icons_from_html(base_url, text):
    """HTML'den aday görsel adresleri (kalite sırasıyla): apple-touch-icon, <link rel=icon> (büyükten küçüğe), og:image."""
    out, icons = [], []
    for m in re.finditer(r'<link\b[^>]*>', text, flags=re.I):
        tag = m.group(0)
        rel = re.search(r'\brel\s*=\s*["\']?([^"\'>]+)', tag, re.I)
        href = re.search(r'\bhref\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if not rel or not href:
            continue
        rels = rel.group(1).lower().split()
        if 'apple-touch-icon' in rels or 'apple-touch-icon-precomposed' in rels:
            out.append(_abs(base_url, href.group(1)))
        elif 'icon' in rels:
            sz = re.search(r'\bsizes\s*=\s*["\']?(\d+)x', tag, re.I)
            icons.append((int(sz.group(1)) if sz else 0, _abs(base_url, href.group(1))))
    out += [u for _, u in sorted(icons, key=lambda x: -x[0])]
    og = re.search(r'<meta\b[^>]*property\s*=\s*["\']og:image["\'][^>]*content\s*=\s*["\']([^"\']+)["\']', text, re.I) \
        or re.search(r'<meta\b[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*property\s*=\s*["\']og:image["\']', text, re.I)
    if og:
        out.append(_abs(base_url, og.group(1)))
    seen, uniq = set(), []
    for u in out:
        if u not in seen and u.startswith(('http://', 'https://')):
            seen.add(u); uniq.append(u)
    return uniq


def _try_image(url, budget):
    r = budget.get(url)
    if not r or r[0] != 200:
        return None
    return check_image(r[1], r[2])


def find_for_domain(domain, budget):
    """Alan adı için logo: (uzantı, veri, kaynak) ya da None. Sıra: site HTML'indeki simgeler → sabit yollar → Clearbit → Google."""
    base = f'https://{domain}/'
    r = budget.get(base)
    if r and r[0] == 200 and r[1].startswith('text/html'):
        for u in icons_from_html(base, r[2].decode('utf-8', errors='replace'))[:6]:
            got = _try_image(u, budget)
            if got:
                return got[0], got[1], 'site'
    for path in ('apple-touch-icon.png', 'favicon.ico'):
        got = _try_image(base + path, budget)
        if got:
            return got[0], got[1], 'site'
    got = _try_image(f'https://logo.clearbit.com/{domain}', budget)
    if got:
        return got[0], got[1], 'clearbit'
    got = _try_image(f'https://www.google.com/s2/favicons?domain={urllib.parse.quote(domain)}&sz=128', budget)
    if got:
        return got[0], got[1], 'google'
    return None


def find(name, website=None, email=None):
    """Bir firma için logo: {'ext','data','source','domain'} ya da None."""
    budget = _Budget()
    domain = domain_of(website, email)
    if not domain:
        domain = duckduckgo_domain(name, budget)
        if not domain:
            return None
        src_suffix = '+ddg'
    else:
        src_suffix = ''
    got = find_for_domain(domain, budget)
    if not got:
        return None
    return {'ext': got[0], 'data': got[1], 'source': got[2] + src_suffix, 'domain': domain}


def save_logo(ext, data):
    """Görseli elle yüklenen logolarla aynı yere yazar: data/uploads/logos/<rastgele><uzantı>; 'logos/<ad>' döner."""
    folder = config.UPLOAD_DIR / 'logos'
    folder.mkdir(parents=True, exist_ok=True)
    fname = secrets.token_hex(12) + ext
    (folder / fname).write_bytes(data)
    return f'logos/{fname}'


# ---- Toplu tarama (arka plan)
def run(conn_factory, only_missing=True, ids=None, supplier=None, user_id=None):
    """Toplu logo taraması; zaten çalışıyorsa False. supplier: True yalnız tedarikçiler, False yalnız firmalar, None hepsi.
    En çok MAX_PER_RUN firma taranır (kalanlar bir sonraki çağrıda)."""
    global _worker
    with _lock:
        if STATE['running']:
            return False
        STATE.update(running=True, total=0, done=0, found=0, skipped=0, failed=0, current='', items=[],
                     started_at=db.now(), finished_at=None, error=None)

    def work():
        conn = conn_factory()
        try:
            where, args = ['active = 1'], []
            if only_missing:
                where.append("(logo IS NULL OR logo = '')")
            if ids:
                where.append(f"id IN ({','.join('?' * len(ids))})")
                args += list(ids)
            if supplier is not None:
                where.append('COALESCE(is_supplier, 0) = ?')
                args.append(1 if supplier else 0)
            rows = conn.execute(f"SELECT id, name, website, email, logo FROM companies WHERE {' AND '.join(where)} ORDER BY name LIMIT ?",
                                args + [MAX_PER_RUN]).fetchall()
            STATE['total'] = len(rows)
            for cid, name, website, email, logo in rows:
                STATE['current'] = name
                try:
                    r = find(name, website, email)
                except Exception:   # noqa: BLE001
                    r = None
                if r:
                    path = save_logo(r['ext'], r['data'])
                    conn.execute('UPDATE companies SET logo = ? WHERE id = ?', (path, cid))
                    if user_id:
                        db.audit(conn, user_id, 'Firma logosunu web\'den buldu', 'company', cid, f"{name} · {r['source']} ({r['domain']})")
                    conn.commit()
                    STATE['found'] += 1
                    STATE['items'].append({'id': cid, 'name': name, 'source': r['source'], 'logo': path})
                elif not domain_of(website, email):
                    STATE['skipped'] += 1   # alan adı yok ve aramadan da çıkmadı
                else:
                    STATE['failed'] += 1
                STATE['done'] += 1
        except Exception as e:   # noqa: BLE001
            STATE['error'] = str(e)
        finally:
            STATE.update(running=False, current='', finished_at=db.now())
            try:
                conn.close()
            except Exception:   # noqa: BLE001
                pass

    _worker = threading.Thread(target=work, daemon=True, name='logofind')
    _worker.start()
    return True
