"""Firma instance'ından merkeze (Veilox Merkez) federasyon çağrıları: destek talepleri, üyelik/ödeme bilgisi, askı durumu.
Paylaşılan federasyon anahtarı + firma kimliği (TENANT_SLUG) ile. Merkeze ulaşılamazsa müşteriyi kilitlemez (fail-open)."""
import time

import httpx
from fastapi import HTTPException

from . import config


def enabled():
    return bool(config.FEDERATION_URL and config.FEDERATION_SECRET and config.TENANT_SLUG)


def call(method, path, json=None, params=None, timeout=10):
    if not enabled():
        raise HTTPException(400, 'Merkez bağlantısı yapılandırılmamış')
    p = dict(params or {}); p['slug'] = config.TENANT_SLUG
    try:
        r = httpx.request(method, f'{config.FEDERATION_URL}/api/federation{path}', params=p, json=json,
                          headers={'X-Fed-Secret': config.FEDERATION_SECRET}, timeout=timeout)
    except httpx.HTTPError:
        raise HTTPException(503, 'Merkeze şu an ulaşılamıyor, lütfen biraz sonra tekrar deneyin')
    if r.status_code >= 400:
        try:
            detail = r.json().get('detail')
        except ValueError:
            detail = None
        raise HTTPException(r.status_code if r.status_code < 500 else 503, detail or 'Merkez isteği başarısız')   # 502 Cloudflare'de mesajı yutar
    return r.json()


_SUSP = {'at': 0.0, 'data': {'suspended': False}}


def suspension():
    """Askı durumu (5 dk önbellek). Hata olursa son bilinen değer; hiç yoksa askıda değil."""
    if not enabled():
        return {'suspended': False}
    now = time.monotonic()
    if now - _SUSP['at'] < 300:
        return _SUSP['data']
    try:
        d = call('GET', '/status', timeout=5)
        _SUSP['data'] = {'suspended': bool(d.get('suspended')), 'reason': d.get('reason') or ''}
    except HTTPException:
        pass
    _SUSP['at'] = now
    return _SUSP['data']


def suspended_message(s):
    msg = 'Firma hesabınız askıya alınmıştır.'
    if s.get('reason'):
        msg += f' ({s["reason"]})'
    return msg + ' Lütfen firma yöneticinizle iletişime geçin.'


_CT = {'at': 0.0, 'data': []}


def pending_contracts():
    """Onay bekleyen zorunlu sözleşmeler (5 dk önbellek; bildirim zili her yoklamada merkeze gitmesin)."""
    if not enabled():
        return []
    now = time.monotonic()
    if now - _CT['at'] < 300:
        return _CT['data']
    try:
        d = call('GET', '/contracts', timeout=5)
        _CT['data'] = [{'id': x['id'], 'title': x['title'], 'version': x['version']} for x in d.get('docs', [])
                       if x.get('required') and not x.get('acceptance')]
    except HTTPException:
        pass
    _CT['at'] = now
    return _CT['data']


def forget_contracts():
    _CT['at'] = 0.0
