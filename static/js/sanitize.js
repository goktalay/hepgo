// Zengin metin (kullanıcı HTML'i) temizleyici — izin listesi. Sunucudaki app/htmlclean.py ile aynı kural.
// DOMParser ile ayrıştırılan belge etkisizdir (betik çalışmaz, resim yüklenmez); izin verilen düğümler
// yeni bir ağaca kopyalanır, gerisi atılır. innerHTML'e verilecek her kullanıcı HTML'i buradan geçmeli.
const TAGS = new Set(['P', 'DIV', 'SPAN', 'BR', 'HR', 'B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'SUB', 'SUP', 'FONT',
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'PRE', 'CODE', 'A', 'IMG',
  'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TD', 'TH', 'CAPTION', 'COL', 'COLGROUP']);
const DROP = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'FRAME', 'FRAMESET', 'OBJECT', 'EMBED', 'APPLET', 'SVG', 'MATH', 'TEMPLATE',
  'NOSCRIPT', 'TEXTAREA', 'SELECT', 'BUTTON', 'TITLE', 'HEAD', 'XML', 'LINK', 'META', 'BASE', 'FORM', 'INPUT']);
const ATTRS = new Set(['style', 'align', 'color', 'face', 'size', 'href', 'src', 'alt', 'title', 'colspan', 'rowspan',
  'width', 'height', 'dir']);
const URL_OK = /^(https?:|mailto:|tel:|#)/i;
const IMG_OK = /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$/i;
const STYLE_BAD = /url\s*\(|expression|javascript|@import|behavior|-moz-binding|[\\<>]/i;

function attrOk(tag, name, value) {
  if (!ATTRS.has(name)) return false;
  if (name === 'href') return tag === 'A' && URL_OK.test(value.replace(/[\x00-\x20\x7f]+/g, ''));
  if (name === 'src') return tag === 'IMG' && IMG_OK.test(value.trim());
  if (name === 'style') return !STYLE_BAD.test(value);
  return true;
}

function copy(src, dst) {
  for (const n of src.childNodes) {
    if (n.nodeType === 3) { dst.appendChild(document.createTextNode(n.data)); continue; }
    if (n.nodeType !== 1) continue;
    const tag = n.tagName.toUpperCase();
    if (DROP.has(tag)) continue;
    if (!TAGS.has(tag)) { copy(n, dst); continue; }   // bilinmeyen etiket: yalnız içeriği kalır
    const el = document.createElement(tag);
    for (const a of n.attributes) {
      const name = a.name.toLowerCase();
      if (attrOk(tag, name, a.value)) el.setAttribute(name, a.value);
    }
    if (tag === 'A' && el.hasAttribute('href')) { el.setAttribute('target', '_blank'); el.setAttribute('rel', 'noopener noreferrer'); }
    copy(n, el);
    dst.appendChild(el);
  }
}

export function cleanHtml(html) {
  if (typeof html !== 'string' || !html) return '';
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
  const out = document.createElement('div');
  copy(doc.body, out);
  return out.innerHTML;
}
