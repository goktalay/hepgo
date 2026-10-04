"""Merkez ↔ firma federasyon anahtarı: her firmaya ayrı anahtar.

Merkezin .env'indeki CAYMAZ_FEDERATION_SECRET ana anahtardır ve yalnız merkezde durur. Firmanın anahtarı ondan türetilir:
HMAC-SHA256(ana_anahtar, 'tenant:' + slug). Firma .env'ine yalnız kendi türetilmiş anahtarı yazılır; merkez isteği,
istekteki slug için türetilen anahtarla karşılaştırır — bir firmanın anahtarı başka firmanın verisine erişemez.

Geçiş: eski kurulumlar ana anahtarı paylaşıyordu. CAYMAZ_FEDERATION_ALLOW_SHARED=1 (varsayılan) iken ana anahtar da
kabul edilir; tüm firmalara türetilmiş anahtar dağıtılınca merkezde 0 yapılır.
Firma anahtarı üretmek (merkez .env'iyle):  python -m app.fedauth <slug>
"""
import hashlib
import hmac

from . import config


def tenant_key(slug):
    return hmac.new(config.FEDERATION_SECRET.encode(), f'tenant:{slug}'.encode(), hashlib.sha256).hexdigest()


def _eq(a, b):
    return hmac.compare_digest(a.encode('utf-8', 'replace'), b.encode('utf-8', 'replace'))


def check(secret, slug=''):
    """İstekteki anahtar bu slug için geçerli mi? (slug yoksa yalnız geçiş dönemindeki ortak anahtar geçer)"""
    if not config.FEDERATION_SECRET or not secret:
        return False
    if slug and _eq(secret, tenant_key(slug)):
        return True
    return config.FEDERATION_ALLOW_SHARED and _eq(secret, config.FEDERATION_SECRET)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2 or not config.FEDERATION_SECRET:
        sys.exit('Kullanım: CAYMAZ_ENV_FILE=<merkez .env> python -m app.fedauth <slug>  (merkezde CAYMAZ_FEDERATION_SECRET gerekli)')
    print(tenant_key(sys.argv[1].strip().lower()))
