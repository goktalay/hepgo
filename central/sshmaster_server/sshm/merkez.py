"""Merkez (HEPGO destek talepleri) istemcisi: Mastertool kullanıcılarının talepleri Merkez'in talep ekranına 'mastertool' kaydıyla düşer.
Merkez adresi / hata ayrıntısı son kullanıcıya ASLA gösterilmez: bağlantı hatası tek tip iletiye çevrilir."""
import httpx

from . import settings


class MerkezError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def call(method, path, json=None, params=None):
    if not settings.CENTRAL_SECRET:
        raise MerkezError(503, 'Destek sistemi şu an kullanılamıyor')
    transport = httpx.HTTPTransport(uds=settings.MERKEZ_UDS) if settings.MERKEZ_UDS else None
    try:
        with httpx.Client(base_url=settings.MERKEZ_URL, transport=transport, timeout=20) as c:
            r = c.request(method, path, json=json, params=params, headers={'X-Central-Secret': settings.CENTRAL_SECRET})
    except httpx.HTTPError:
        raise MerkezError(503, 'Destek sistemine şu an ulaşılamıyor; biraz sonra tekrar deneyin')
    if r.status_code >= 400:
        try:
            msg = r.json().get('detail')
        except ValueError:
            msg = None
        if not isinstance(msg, str) or len(msg) > 200 or '://' in msg or r.status_code >= 500:
            msg = 'Destek isteği işlenemedi' if r.status_code < 500 else 'Destek sistemine şu an ulaşılamıyor; biraz sonra tekrar deneyin'
        raise MerkezError(r.status_code if r.status_code < 500 else 503, msg)
    return r.json()
