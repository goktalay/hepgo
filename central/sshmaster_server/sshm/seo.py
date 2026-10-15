"""Ürün siteleri için SEO: dile göre sunucu tarafı başlık/açıklama, canonical + hreflang (8 dil), Open Graph / Twitter kartı,
schema.org yapılandırılmış verisi, robots.txt ve sitemap.xml.

Sayfa metinleri tarayıcıda kit.js ile çevrilir; arama motorları için ?lang=<dil> adresinde <html lang/dir>, <title>, açıklama ve
sosyal etiketler sunucuda aynı sözlükten (static/i18n/<site>.<dil>.json) doldurulur. Türkçe kaynak dildir (parametresiz adres)."""
import html as _h
import json
import re

from . import settings

LANGS = ('tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru')
OG_LOCALE = {'tr': 'tr_TR', 'en': 'en_US', 'fr': 'fr_FR', 'de': 'de_DE', 'es': 'es_ES', 'ar': 'ar_AR', 'zh': 'zh_CN', 'ru': 'ru_RU'}
HREFLANG = {'zh': 'zh-Hans'}
PRODUCTS = {   # site → (ad, schema.org applicationCategory)
    'sm': ('SSH Master', 'DeveloperApplication'),
    'fm': ('FTP Masters', 'UtilitiesApplication'),
    'sq': ('SQL Master', 'DeveloperApplication'),
    'np': ('Notepad Master', 'DeveloperApplication'),
    'cv': ('Convert Master', 'MultimediaApplication'),
}
_norm = lambda s: re.sub(r'\s+', ' ', s).strip()   # noqa: E731
_cache = {}


def _dict(site, lang):
    if lang == 'tr':
        return {}
    key = (site, lang)
    if key not in _cache:
        try:
            _cache[key] = json.loads((settings.STATIC_DIR / 'i18n' / f'{site}.{lang}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _cache[key] = {}
    return _cache[key]


def _t(d, s):
    return d.get(_norm(_h.unescape(s)), _h.unescape(s))


def base(site):
    return settings.SITE_URLS[site].rstrip('/')


def _url(site, lang):
    return f'{base(site)}/' if lang == 'tr' else f'{base(site)}/?lang={lang}'


def _jsonld(site, title, desc, lang):
    if site == 'mt':
        data = [{'@context': 'https://schema.org', '@type': 'Organization', 'name': 'Mastertool', 'url': f'{base("mt")}/',
                 'logo': f'{base("mt")}/brand/mt.png'},
                {'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'Mastertool', 'url': f'{base("mt")}/', 'inLanguage': list(LANGS)},
                {'@context': 'https://schema.org', '@type': 'ItemList', 'name': title,
                 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': n, 'url': f'{base(k)}/'}
                                     for i, (k, (n, _)) in enumerate(PRODUCTS.items())]}]
    else:
        name, cat = PRODUCTS[site]
        data = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': name, 'description': desc,
                'url': _url(site, lang), 'image': f'{base(site)}/og.png', 'operatingSystem': 'Windows 10, Windows 11',
                'applicationCategory': cat, 'inLanguage': list(LANGS),
                'publisher': {'@type': 'Organization', 'name': 'Mastertool', 'url': f'{base("mt")}/'}}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('</', '<\\/') + '</script>'


def render_index(site, page, lang):
    """index.html → dile göre SEO etiketleriyle. lang geçersizse Türkçe."""
    lang = lang if lang in LANGS else 'tr'
    d = _dict(site, lang)
    m = re.search(r'<title>(.*?)</title>', page, re.S)
    title = _t(d, m.group(1)) if m else PRODUCTS.get(site, ('Mastertool',))[0]
    m = re.search(r'<meta name="description" content="([^"]*)">', page)
    desc = _t(d, m.group(1)) if m else ''
    m = re.search(r'<meta property="og:title" content="([^"]*)">', page)
    og_title = _t(d, m.group(1)) if m else title
    m = re.search(r'<meta property="og:description" content="([^"]*)">', page)
    og_desc = _t(d, m.group(1)) if m else desc
    esc = _h.escape
    page = re.sub(r'<html lang="[^"]*"', f'<html lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}"', page, count=1)
    page = re.sub(r'<title>.*?</title>', f'<title>{esc(title, False)}</title>', page, count=1, flags=re.S)
    page = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{esc(desc)}">', page, count=1)
    page = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{esc(og_title)}">', page, count=1)
    page = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{esc(og_desc)}">', page, count=1)
    page = re.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{esc(_url(site, lang))}">', page, count=1)
    alts = ''.join(f'<link rel="alternate" hreflang="{HREFLANG.get(l, l)}" href="{esc(_url(site, l))}">' for l in LANGS)
    name = PRODUCTS.get(site, ('Mastertool',))[0]
    extra = (f'\n<link rel="canonical" href="{esc(_url(site, lang))}">{alts}'
             f'<link rel="alternate" hreflang="x-default" href="{esc(_url(site, "tr"))}">'
             f'\n<meta name="robots" content="index, follow, max-image-preview:large">'
             f'\n<meta name="theme-color" content="#0b0f17">'
             f'\n<link rel="apple-touch-icon" href="/logo.png">'
             f'\n<meta property="og:site_name" content="{esc(name)}">'
             f'<meta property="og:locale" content="{OG_LOCALE[lang]}">'
             + ''.join(f'<meta property="og:locale:alternate" content="{OG_LOCALE[l]}">' for l in LANGS if l != lang)
             + f'\n<meta property="og:image" content="{base(site)}/og.png"><meta property="og:image:width" content="1200">'
               f'<meta property="og:image:height" content="630"><meta property="og:image:alt" content="{esc(og_title)}">'
             f'\n<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(og_title)}">'
             f'<meta name="twitter:description" content="{esc(og_desc)}"><meta name="twitter:image" content="{base(site)}/og.png">'
             f'\n{_jsonld(site, title, desc, lang)}\n')
    return page.replace('</head>', extra + '</head>', 1)


def robots(site):
    return (f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /hesabim\nDisallow: /indir/\nDisallow: /dogrula/\n'
            f'Disallow: /sifre-sifirla/\n\nSitemap: {base(site)}/sitemap.xml\n')


def sitemap(site):
    alts = ''.join(f'<xhtml:link rel="alternate" hreflang="{HREFLANG.get(l, l)}" href="{_h.escape(_url(site, l))}"/>' for l in LANGS)
    urls = ''.join(f'<url><loc>{_h.escape(_url(site, l))}</loc>{alts}<changefreq>weekly</changefreq>'
                   f'<priority>{"1.0" if l == "tr" else "0.8"}</priority></url>' for l in LANGS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            f'xmlns:xhtml="http://www.w3.org/1999/xhtml">{urls}</urlset>\n')
