"""Ürün sitesi ekran görüntüleri: uygulama deposundaki docs/screenshots (PNG + manifest.json) → static/<site>/shots/ (WebP 1600 ve
800 px önizleme) + sayfada galeri ve tema duyarlı kahraman görseli. Kullanım (sshmaster_server içinde):
  ../../.venv/bin/python -I tools/shots.py <site> <kaynak docs/screenshots dizini>
Sayfadaki <!--SHOTS-->…<!--/SHOTS--> ve <!--HERO-->…<!--/HERO--> blokları yeniden yazılır (ilk çalıştırmada eklenir)."""
import html
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / 'static'
site, src = sys.argv[1], Path(sys.argv[2])
hero_pick = sys.argv[3].split(',') if len(sys.argv) > 3 and sys.argv[3] else []   # isteğe bağlı: kahraman için dosya öneki (gece,gündüz), ör. 05,06
en_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else None   # isteğe bağlı: İngilizce arayüz görüntüleri (aynı dosya adları) → Türkçe dışı dillerde
items = json.loads((src / 'manifest.json').read_text(encoding='utf-8'))
out = ROOT / site / 'shots'
out.mkdir(parents=True, exist_ok=True)
for f in out.glob('*'):
    f.unlink()
shots = []
for it in items:
    name = Path(it['file']).name
    if not re.fullmatch(r'[0-9a-z._-]+\.png', name):
        raise SystemExit(f'geçersiz dosya adı: {name}')
    im = Image.open(src / name)
    im.load()
    im = im.convert('RGB')
    stem = name[:-4]
    w, h = im.size
    big = im if w <= 1600 else im.resize((1600, round(h * 1600 / w)), Image.LANCZOS)
    big.save(out / f'{stem}.webp', 'WEBP', quality=84, method=6)
    im.resize((800, round(h * 800 / w)), Image.LANCZOS).save(out / f'{stem}-800.webp', 'WEBP', quality=80, method=6)
    en = bool(en_dir and (en_dir / name).is_file())
    if en:
        ie = Image.open(en_dir / name)
        ie.load()
        ie = ie.convert('RGB')
        (ie if ie.size[0] <= 1600 else ie.resize((1600, round(ie.size[1] * 1600 / ie.size[0])), Image.LANCZOS)).save(
            out / f'{stem}-en.webp', 'WEBP', quality=84, method=6)
        ie.resize((800, round(ie.size[1] * 800 / ie.size[0])), Image.LANCZOS).save(out / f'{stem}-en-800.webp', 'WEBP', quality=80, method=6)
    shots.append({'stem': stem, 'theme': it.get('theme', 'dark'), 'title': it['title'][:90], 'caption': it.get('caption', '')[:120],
                  'w': big.size[0], 'h': big.size[1], 'en': en})
(out / 'shots.json').write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding='utf-8')

e = lambda s: html.escape(s, quote=True)   # noqa: E731
EN = lambda s: ' data-shot-en' if s.get('en') else ''   # noqa: E731  (kit.js / seo.py: Türkçe dışı dillerde -en görüntüsü)
figs = ''.join(
    f'        <figure class="shot" data-theme-shot="{s["theme"]}"><a href="/shots/{s["stem"]}.webp" data-lightbox{EN(s)}>'
    f'<img{EN(s)} src="/shots/{s["stem"]}-800.webp" srcset="/shots/{s["stem"]}-800.webp 800w, /shots/{s["stem"]}.webp 1600w" '
    f'sizes="(max-width: 960px) 100vw, 380px" width="{s["w"]}" height="{s["h"]}" loading="lazy" decoding="async" alt="{e(s["title"])}"></a>'
    f'<figcaption><b>{e(s["title"])}</b><span>{e(s["caption"])}</span></figcaption></figure>\n' for s in shots)
gallery = (f'<!--SHOTS-->\n  <section class="alt" id="ekranlar">\n    <div class="wrap">\n      <h2>Uygulamadan görüntüler</h2>\n'
           f'      <p class="sub">Gerçek ekranlar: gece ve gündüz temasıyla. Büyütmek için tıklayın.</p>\n'
           f'      <div class="shots" data-gallery>\n{figs}      </div>\n    </div>\n  </section>\n<!--/SHOTS-->')
pick = lambda i, th: next((s for s in shots if len(hero_pick) > i and s['stem'].startswith(hero_pick[i])),   # noqa: E731
                         next((s for s in shots if s['theme'] == th), None))
dark = pick(0, 'dark') or shots[0]
light = pick(1, 'light') or dark
hero = (f'<!--HERO--><div class="hero-shot" aria-hidden="false">'
        f'<img class="hs-dark"{EN(dark)} src="/shots/{dark["stem"]}.webp" width="{dark["w"]}" height="{dark["h"]}" alt="{e(dark["title"])}" fetchpriority="high">'
        f'<img class="hs-light"{EN(light)} src="/shots/{light["stem"]}.webp" width="{light["w"]}" height="{light["h"]}" alt="{e(light["title"])}" loading="lazy">'
        f'</div><!--/HERO-->')
p = ROOT / site / 'index.html'
s = p.read_text(encoding='utf-8')
if '<!--HERO-->' in s:
    s = re.sub(r'<!--HERO-->.*?<!--/HERO-->', lambda m: hero, s, flags=re.S)
else:   # ilk kez: çizim önizlemeyi (.app) gerçek ekranla değiştir
    i = s.index('<div class="app" aria-hidden="true">')
    depth, j = 0, i
    for m in re.finditer(r'<div\b|</div>', s[i:]):
        depth += 1 if m.group(0) == '<div' else -1
        if depth == 0:
            j = i + m.end(); break
    s = s[:i] + hero + s[j:]
if '<!--SHOTS-->' in s:
    s = re.sub(r'<!--SHOTS-->.*?<!--/SHOTS-->', lambda m: gallery, s, flags=re.S)
else:
    k = s.index('  <section class="alt" id="nasil">') if '<section class="alt" id="nasil">' in s else s.index('  <section id="nasil">')
    s = s[:k] + gallery + '\n\n' + s[k:]
s = s.replace('<a href="#ozellikler">Özellikler</a>', '<a href="#ozellikler">Özellikler</a><a href="#ekranlar">Ekranlar</a>', 1) \
    if '#ekranlar' not in s else s
p.write_text(s, encoding='utf-8')
print(site, len(shots), 'görüntü')
