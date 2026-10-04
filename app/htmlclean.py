"""Zengin metin (kullanıcı HTML'i) temizleyici: izin listesi, yalnız standart kütüphane.

Belge Yönetim'deki Word/Sunum içeriği başka kullanıcılara innerHTML olarak gösterilir; içine konan
<script>, on*= olay öznitelikleri, javascript: bağlantıları vb. görüntüleyenin oturumunda çalışırdı (XSS).
İzin verilen etiket/öznitelikler dışındaki her şey atılır; metin her zaman kaçışlanarak yeniden yazılır.
İstemci tarafında aynı kural static/js/sanitize.js'tedir (eski kayıtlar ve yapıştırılan içerik için).
"""
import re
from html import escape
from html.parser import HTMLParser

TAGS = {'p', 'div', 'span', 'br', 'hr', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'sub', 'sup', 'font',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'a', 'img',
        'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'col', 'colgroup'}
VOID = {'br', 'hr', 'img', 'col'}
# İçeriğiyle birlikte atılanlar (metni de gösterilmez)
DROP = {'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'svg', 'math', 'template',
        'noscript', 'textarea', 'select', 'button', 'title', 'head', 'xml'}
ATTRS = {'style', 'align', 'color', 'face', 'size', 'href', 'src', 'alt', 'title', 'colspan', 'rowspan', 'width',
         'height', 'dir'}
_URL_OK = re.compile(r'^(https?:|mailto:|tel:|#)', re.I)
_IMG_OK = re.compile(r'^data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$', re.I)
_STYLE_BAD = re.compile(r'url\s*\(|expression|javascript|@import|behavior|-moz-binding|[\\<>]', re.I)
_CTRL = re.compile(r'[\x00-\x20\x7f]+')


def _attr_ok(tag, name, value):
    if name not in ATTRS:
        return False
    if name == 'href':
        return tag == 'a' and bool(_URL_OK.match(_CTRL.sub('', value)))
    if name == 'src':
        return tag == 'img' and bool(_IMG_OK.match(value.strip()))
    if name == 'style':
        return not _STYLE_BAD.search(value)
    return True


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.drop = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.drop += tag not in VOID
            return
        if self.drop or tag not in TAGS:
            return
        kept = ''.join(f' {n}="{escape(v or "", quote=True)}"' for n, v in attrs if _attr_ok(tag, n, v or ''))
        if tag == 'a' and 'href=' in kept:
            kept += ' target="_blank" rel="noopener noreferrer"'
        self.out.append(f'<{tag}{kept}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in DROP and tag not in VOID:
            self.drop -= 1

    def handle_endtag(self, tag):
        if tag in DROP:
            self.drop = max(0, self.drop - 1)
        elif not self.drop and tag in TAGS and tag not in VOID:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.drop:
            self.out.append(escape(data, quote=False))


def clean(html):
    if not isinstance(html, str) or not html:
        return ''
    p = _Cleaner()
    p.feed(html)
    p.close()
    return ''.join(p.out)


def clean_office(content):
    """Belge içeriğindeki HTML alanları (word: html, sunum: slides[].html) temizlenir; diğerleri aynen kalır."""
    if not isinstance(content, dict):
        return content
    out = dict(content)
    if 'html' in out:
        out['html'] = clean(out['html'])
    if isinstance(out.get('slides'), list):
        out['slides'] = [{**s, 'html': clean(s.get('html'))} if isinstance(s, dict) else {'html': ''}
                         for s in out['slides']]
    return out
