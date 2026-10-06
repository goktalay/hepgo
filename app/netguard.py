"""SSRF koruması: kullanıcı kaynaklı bir URL'ye sunucudan istek atmadan önce hedef host'un GENEL (public) bir
adrese çözüldüğünü doğrular. İç ağ (10/8, 172.16/12, 192.168/16), loopback (127/8, ::1), link-local
(169.254/16 — bulut metadata), özel/çok noktalı/ayrılmış adresler reddedilir. DNS yeniden-bağlama (rebinding)
ve yönlendirme (redirect) ile iç ağa sızmayı engellemek için her istek/yönlendirme adımında yeniden denetlenir.
"""
import ipaddress
import socket
from urllib.parse import urlsplit


class BlockedURLError(Exception):
    """Hedef URL güvenli değil (iç ağ / geçersiz şema)."""


def _ip_is_public(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
                or a.is_multicast or a.is_unspecified or a.is_site_local)


def assert_public_url(url, *, schemes=('http', 'https')):
    """URL geçerli şemada mı ve host'u yalnız GENEL IP'lere mi çözülüyor? Değilse BlockedURLError."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in schemes:
        raise BlockedURLError(f'İzin verilmeyen şema: {parts.scheme or "(yok)"}')
    host = parts.hostname
    if not host:
        raise BlockedURLError('Geçersiz adres (host yok)')
    # IP literali ise doğrudan; değilse çözümle (tüm kayıtlar genel olmalı)
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise BlockedURLError(f'Adres çözümlenemedi: {host}') from e
    ips = {info[4][0] for info in infos}
    if not ips:
        raise BlockedURLError(f'Adres çözümlenemedi: {host}')
    for ip in ips:
        if not _ip_is_public(ip):
            raise BlockedURLError(f'İç ağ/özel adrese istek engellendi: {host}')
    return url


def safe_get(client_get, url, *, max_redirects=5, **kw):
    """httpx.get benzeri bir çağrıyı SSRF-güvenli çalıştırır: her adımda host doğrulanır, yönlendirmeler elle
    (en çok max_redirects) ve her hop yeniden doğrulanarak izlenir. client_get(url, follow_redirects=False, **kw)
    imzasına uymalı. İzin verilmeyen hedefte BlockedURLError yükselir."""
    kw.pop('follow_redirects', None)
    seen = url
    for _ in range(max_redirects + 1):
        assert_public_url(seen)
        r = client_get(seen, follow_redirects=False, **kw)
        if r.status_code in (301, 302, 303, 307, 308) and 'location' in r.headers:
            nxt = str(r.url.join(r.headers['location']))
            seen = nxt
            continue
        return r
    raise BlockedURLError('Çok fazla yönlendirme')
