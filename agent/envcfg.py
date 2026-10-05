"""Ajan yerel yapılandırması: agent-config.env okuma/yazma ve ortam değişkeni eşlemesi.

Kurulum düzeni (installer): /opt/hepgo-<integ>/agent-config.env ; systemd birimi HEPGO_AGENT_CONFIG ile
tam yolu verir. Geliştirme düzeni: depo kökündeki agent-config.env.

Alanlar app/config.py'nin beklediği CAYMAZ_* adlarıyla saklanır; böylece dosya ortama yüklenince
`from app import config` doğru değerleri alır. Kullanıcıya yalnız "Domain" sorulur; buradan
CAYMAZ_AGENT_CENTRAL_URL (wss://<domain>/ws/agent) türetilir.
"""
import os
from pathlib import Path


def integ_name():
    return os.environ.get('HEPGO_INTEG', '').strip().lower()


def config_path():
    p = os.environ.get('HEPGO_AGENT_CONFIG')
    if p:
        return Path(p)
    return Path(__file__).resolve().parent.parent / 'agent-config.env'


def domain_to_url(domain):
    domain = (domain or '').strip().rstrip('/')
    if not domain:
        return ''
    # Zaten tam ws(s) adresi verildiyse olduğu gibi kullan.
    if domain.startswith(('ws://', 'wss://')):
        return domain
    if domain.startswith(('http://', 'https://')):
        domain = domain.split('://', 1)[1]
    domain = domain.rstrip('/')
    return f'wss://{domain}/ws/agent'


def url_to_domain(url):
    url = (url or '').strip()
    if not url:
        return ''
    for pre in ('wss://', 'ws://', 'https://', 'http://'):
        if url.startswith(pre):
            url = url[len(pre):]
            break
    return url.split('/', 1)[0]


def read_file(path=None):
    """agent-config.env → {ANAHTAR: değer} (yorum ve boş satırlar atlanır)."""
    path = Path(path) if path else config_path()
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def load_into_environ(path=None):
    """Dosyayı ortama yükler (mevcut ortam değerini EZMEZ). Domain'den WSS adresi türetir."""
    data = read_file(path)
    for k, v in data.items():
        if k.startswith('_'):          # arayüz-içi not alanları saklanmaz/atlanır
            continue
        if v != '':
            os.environ.setdefault(k, v)
    # Domain → CAYMAZ_AGENT_CENTRAL_URL
    dom = data.get('CAYMAZ_AGENT_CENTRAL_URL_DOMAIN', '').strip()
    if dom and not os.environ.get('CAYMAZ_AGENT_CENTRAL_URL'):
        os.environ['CAYMAZ_AGENT_CENTRAL_URL'] = domain_to_url(dom)
    return data


def has_config(path=None):
    """Bağlanmak için yeterli yapılandırma var mı? (merkez adresi + anahtar)."""
    data = read_file(path)
    url = os.environ.get('CAYMAZ_AGENT_CENTRAL_URL') or domain_to_url(
        data.get('CAYMAZ_AGENT_CENTRAL_URL_DOMAIN', ''))
    key = os.environ.get('CAYMAZ_AGENT_KEY') or data.get('CAYMAZ_AGENT_KEY', '')
    return bool(url and key)


def write_file(values, path=None):
    """values ({ANAHTAR: değer}) → agent-config.env, chmod 600. '_' ile başlayan not alanları yazılmaz."""
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['# HEPGO fabrika ajanı yerel yapılandırması — otomatik üretildi (agent.localconfig).',
             '# Parolalar burada düz metindir; dosya izni 600 olmalıdır.', '']
    for k, v in values.items():
        if k.startswith('_'):
            continue
        lines.append(f'{k}={v}')
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
