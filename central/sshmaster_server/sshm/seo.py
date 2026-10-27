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


def _shots(site, tool=None):
    """static/<site>/shots/shots.json (tools/shots.py üretir; araçta <kod>.shots.json) — yapılandırılmış veride ekran görüntüleri."""
    key = ('shots', site, tool)
    if key not in _cache:
        try:
            _cache[key] = json.loads((settings.STATIC_DIR / site / 'shots' / (f'{tool}.shots.json' if tool else 'shots.json')).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _cache[key] = []
    return _cache[key]


def _t(d, s):
    return d.get(_norm(_h.unescape(s)), _h.unescape(s))


def base(site):
    return settings.SITE_URLS[site].rstrip('/')


def _url(site, lang):
    return f'{base(site)}/' if lang == 'tr' else f'{base(site)}/?lang={lang}'


def _app_ld(name, cat, url, desc, image, rel, lang):
    d = {'@context': 'https://schema.org', '@type': 'SoftwareApplication', 'name': name, 'description': desc, 'url': url, 'image': image,
         'operatingSystem': 'Windows 10, Windows 11', 'applicationCategory': cat, 'inLanguage': list(LANGS),
         'softwareRequirements': 'Windows 10 / 11 (x64)', 'isAccessibleForFree': True,
         'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'TRY', 'availability': 'https://schema.org/InStock', 'url': url},
         'publisher': {'@type': 'Organization', 'name': 'Mastertool', 'url': f'{base("mt")}/'}}
    if rel and rel.get('version'):
        d['softwareVersion'] = rel['version']
        if rel.get('size'):
            d['fileSize'] = f"{round(rel['size'] / 1e6)} MB"
        if rel.get('date'):
            d['dateModified'] = str(rel['date'])[:10]
    return d


def _jsonld(site, title, desc, lang, rel=None):
    if site == 'mt':
        data = [{'@context': 'https://schema.org', '@type': 'Organization', 'name': 'Mastertool', 'url': f'{base("mt")}/',
                 'logo': f'{base("mt")}/brand/mt.png'},
                {'@context': 'https://schema.org', '@type': 'WebSite', 'name': 'Mastertool', 'url': f'{base("mt")}/', 'inLanguage': list(LANGS)},
                {'@context': 'https://schema.org', '@type': 'ItemList', 'name': title,
                 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': n, 'url': f'{base(k)}/'}
                                     for i, (k, (n, _)) in enumerate(PRODUCTS.items())]
                 + [{'@type': 'ListItem', 'position': len(PRODUCTS) + 1, 'name': 'Master Tool', 'url': f'{base("mt")}/#master-tool'}]},
                _app_ld('Master Tool', 'UtilitiesApplication', f'{base("mt")}/#master-tool', desc, f'{base("mt")}/og.png', rel, lang)]
    else:
        name, cat = PRODUCTS[site]
        data = _app_ld(name, cat, _url(site, lang), desc, f'{base(site)}/og.png', rel, lang)
        shots = _shots(site)
        if shots:
            d = _dict(site, lang)
            data['screenshot'] = [{'@type': 'ImageObject', 'url': f'{base(site)}/shots/{x["stem"]}{"-en" if lang != "tr" and x.get("en") else ""}.webp', 'width': x['w'], 'height': x['h'],
                                   'caption': _t(d, x['title'])} for x in shots]
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('</', '<\\/') + '</script>'


def render_index(site, page, lang, rel=None):
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
               f'<meta property="og:image:height" content="630"><meta property="og:image:type" content="image/png">'
               f'<meta property="og:image:alt" content="{esc(og_title)}">'
             f'\n<meta name="application-name" content="{esc(name)}"><meta name="apple-mobile-web-app-title" content="{esc(name)}">'
             f'<meta name="format-detection" content="telephone=no">'
             + (f'\n<meta name="mt-ga" content="{esc(settings.GA_IDS[site])}"><meta name="mt-privacy" content="/gizlilik">'
                if settings.GA_IDS.get(site) else '')
             + f'\n<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(og_title)}">'
             f'<meta name="twitter:description" content="{esc(og_desc)}"><meta name="twitter:image" content="{base(site)}/og.png">'
             f'\n{_jsonld(site, title, desc, lang, rel)}\n')
    if lang != 'tr':   # İngilizce arayüz görüntüsü olanlar sunucuda da değiştirilir (kit.js aynı kuralı tarayıcıda uygular)
        en = {x['stem'] for x in _shots(site) if x.get('en')}
        page = re.sub(r'/shots/([0-9a-z._-]+?)(-800)?\.webp', lambda m: f'/shots/{m[1]}-en{m[2] or ""}.webp' if m[1] in en else m[0], page)
    return page.replace('</head>', extra + '</head>', 1)


def _subpage(page, lang, turl, rel=None):
    """Portal alt sayfası (araç / oyun tanıtımı): ana sayfa SEO'su, canonical / hreflang / og:url alt sayfanın adresine çevrilir.
    Dönüş (html, url_fn, description)."""
    out = render_index('mt', page, lang, rel)
    u = lambda l: turl if l == 'tr' else f'{turl}?lang={l}'   # noqa: E731
    out = re.sub(r'(href|content)="' + re.escape(base('mt')) + r'/(\?lang=([a-z]{2}))?"', lambda m: f'{m[1]}="{u(m[3] or "tr")}"', out)
    m = re.search(r'<meta name="description" content="([^"]*)">', out)
    return out, u, (_h.unescape(m.group(1)) if m else '')


def _put_ld(out, ld):
    return re.sub(r'<script type="application/ld\+json">.*?</script>',
                  lambda _: '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace('</', '<\\/') + '</script>',
                  out, count=1, flags=re.S)


def render_game(k, meta, page, lang):
    """Oyun tanıtım sayfası (mastertool.download/oyunlar/<slug>/tanitim/): schema.org VideoGame, tarayıcıda ücretsiz oynanır."""
    lang = lang if lang in LANGS else 'tr'
    out, u, desc = _subpage(page, lang, f'{base("mt")}/oyunlar/{meta["slug"]}/tanitim/')
    play = f'{base("mt")}/oyunlar/{meta["slug"]}/'
    ld = {'@context': 'https://schema.org', '@type': 'VideoGame', 'name': meta['name'], 'description': desc, 'url': u(lang),
          'image': f'{base("mt")}/brand/{k}-512.png', 'gamePlatform': ['Web browser', 'Android', 'iOS'], 'applicationCategory': 'Game',
          'operatingSystem': 'Any', 'genre': 'Arcade', 'playMode': 'SinglePlayer', 'inLanguage': list(LANGS), 'isAccessibleForFree': True,
          'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'TRY', 'availability': 'https://schema.org/InStock', 'url': play},
          'publisher': {'@type': 'Organization', 'name': 'Mastertool', 'url': f'{base("mt")}/'}}
    return _put_ld(out, ld)


def render_tool(k, meta, page, lang, rel=None):
    """Araç tanıtım sayfası (mastertool.download/araclar/<slug>): ana sayfa SEO'su + adresler ve yapılandırılmış veri araca göre."""
    lang = lang if lang in LANGS else 'tr'
    out, u, desc = _subpage(page, lang, base("mt") + (meta.get('path') or f'/araclar/{meta["slug"]}'), rel)
    ld = _app_ld(meta['name'], 'UtilitiesApplication', u(lang), desc, f'{base("mt")}/brand/{k}-512.png', rel, lang)
    ld['isPartOf'] = {'@type': 'SoftwareApplication', 'name': 'Master Tool', 'url': f'{base("mt")}/#master-tool'}
    shots = _shots('mt', k)
    if shots:
        d = _dict('mt', lang)
        ld['screenshot'] = [{'@type': 'ImageObject', 'url': f'{base("mt")}/shots/{x["stem"]}{"-en" if lang != "tr" and x.get("en") else ""}.webp',
                             'width': x['w'], 'height': x['h'], 'caption': _t(d, x['title'])} for x in shots]
    if lang != 'tr':   # araç görüntülerinin İngilizce sürümleri (ana sayfa işlevi yalnız portalın kendi listesine bakar)
        en = {x['stem'] for x in shots if x.get('en')}
        out = re.sub(r'/shots/([0-9a-z._-]+?)(-800)?\.webp', lambda m: f'/shots/{m[1]}-en{m[2] or ""}.webp' if m[1] in en and '-en' not in m[1] else m[0], out)
    return _put_ld(out, ld)


TOOL_PATHS = {'master-download': '/master-download'}   # kökte yayımlanan araç sayfaları (main.TOOLS[..]['path'])


def tool_pages():
    """Yayındaki araç sayfaları (site haritası için): static/mt/araclar/<slug>.html var olanlar."""
    d = settings.STATIC_DIR / 'mt' / 'araclar'
    return sorted(f.stem for f in d.glob('*.html')) if d.is_dir() else []


def game_pages():
    """Yayındaki oyun tanıtım sayfaları (site haritası için): static/mt/oyunlar/<slug>/tanitim/index.html var olanlar."""
    d = settings.STATIC_DIR / 'mt' / 'oyunlar'
    return sorted(f.parent.parent.name for f in d.glob('*/tanitim/index.html')) if d.is_dir() else []


def robots(site):
    # /web/: tarayıcı sürümleri (oturum ister, dizine girmez); /uygulamalar: portal başlatıcısı (uygulama kabuğu)
    return (f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /hesabim\nDisallow: /indir/\nDisallow: /dogrula/\n'
            f'Disallow: /sifre-sifirla/\nDisallow: /web/\n' + ('Disallow: /uygulamalar\n' if site == 'mt' else '')
            + f'\nSitemap: {base(site)}/sitemap.xml\n')


def sitemap(site):
    """8 dil (hreflang), Türkçe adreste ekran görüntüleri (Google Görseller için image:image) ve gizlilik sayfası."""
    e = _h.escape
    alts = ''.join(f'<xhtml:link rel="alternate" hreflang="{HREFLANG.get(l, l)}" href="{e(_url(site, l))}"/>' for l in LANGS)
    imgs = ''.join(f'<image:image><image:loc>{base(site)}/shots/{x["stem"]}.webp</image:loc></image:image>' for x in _shots(site))
    urls = ''.join(f'<url><loc>{e(_url(site, l))}</loc>{alts}{imgs if l == "tr" else ""}<changefreq>weekly</changefreq>'
                   f'<priority>{"1.0" if l == "tr" else "0.8"}</priority></url>' for l in LANGS)
    urls += f'<url><loc>{base(site)}/gizlilik</loc><changefreq>yearly</changefreq><priority>0.2</priority></url>'
    if site == 'mt':   # araç ve oyun tanıtım sayfaları (8 dil)
        subs = [base("mt") + TOOL_PATHS.get(s, f'/araclar/{s}') for s in tool_pages()] + [f'{base("mt")}/oyunlar/{s}/tanitim/' for s in game_pages()]
        for t in subs:
            ta = ''.join(f'<xhtml:link rel="alternate" hreflang="{HREFLANG.get(l, l)}" href="{e(t if l == "tr" else t + "?lang=" + l)}"/>' for l in LANGS)
            urls += ''.join(f'<url><loc>{e(t if l == "tr" else t + "?lang=" + l)}</loc>{ta}<changefreq>weekly</changefreq>'
                            f'<priority>{"0.9" if l == "tr" else "0.7"}</priority></url>' for l in LANGS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            f'{urls}</urlset>\n')
