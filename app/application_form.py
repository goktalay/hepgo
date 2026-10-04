"""İş Başvuru Formu okuma: el yazısı doldurulmuş başvuru formlarını (PDF/resim) Claude görüntü modeliyle yapılandırılmış
veriye çevirir. Sonuç İK onayına taslak olarak sunulur; doğrudan personel kaydının üzerine yazılmaz.

Yalnızca okuma + çıkarım yapar; veri kalıcılaştırma İK ekranındaki onaydan sonra yapılır.
"""
import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import config

# Formdaki bölümler → çıkarılacak alanlar (İK ekranı bunları gösterir/düzenler)
FIELDS = {
    'dogum_yeri': 'Doğum yeri', 'dogum_tarihi': 'Doğum tarihi (GG.AA.YYYY)', 'medeni_durum': 'Medeni durumu',
    'kan_grubu': 'Kan grubu', 'adres': 'Ev adresi', 'telefon': 'Cep telefonu', 'email': 'E-posta',
    'acil_kisi': 'Acil durumda haber verilecek kişi (ad ve telefon)',
    'es_ad': 'Eşinin adı soyadı', 'es_meslek': 'Eşinin mesleği', 'es_telefon': 'Eşinin telefonu', 'cocuk': 'Çocuk sayısı / yaşı',
    'egitim_lise': 'Lise', 'egitim_lisans': 'Lisans (okul / bölüm)', 'egitim_yuksek': 'Yüksek lisans', 'egitim_devam': 'Devam eden eğitim',
    'tecrube': 'İş tecrübeleri (işyeri · görev · süre; birden çoksa noktalı virgülle)',
}

PROMPT = (
    'Bu bir el yazısıyla doldurulmuş Türkçe "İş Başvuru Formu". Alanları olabildiğince doğru oku ve yalnızca JSON döndür. '
    'Okunamayan ya da boş alanı null bırak; tahmin uydurma. Telefonları yalnızca rakam ve boşlukla, Türkçe karakterleri koru. '
    'Şu anahtarlarla bir JSON nesnesi döndür: ' + ', '.join(FIELDS) + '. '
    'Her değer kısa düz metin ya da null olsun. Sadece JSON, başka açıklama yazma.'
)


def _page_png(path: Path):
    """Formun ilk sayfasını PNG baytı olarak döndürür (PDF ise 200 dpi render)."""
    ext = path.suffix.lower()
    if ext in ('.png', '.jpg', '.jpeg', '.webp'):
        return path.read_bytes(), 'image/png' if ext == '.png' else 'image/jpeg'
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / 'p'
        from .document_ocr import TESS_ENV, tool
        subprocess.run([tool('pdftoppm'), '-f', '1', '-l', '1', '-r', '200', '-png', '-singlefile', str(path), str(out)],
                       env=TESS_ENV, capture_output=True, timeout=120, check=True)
        return (out.with_suffix('.png')).read_bytes(), 'image/png'


def available():
    return bool(config.AI_API_KEY)


def extract(path: Path):
    """Formu Claude görüntü modeliyle oku → {alan: değer|None}. AI anahtarı yoksa / hata olursa istisna fırlatır."""
    if not config.AI_API_KEY:
        raise RuntimeError('Claude API anahtarı tanımlı değil (Program Ayarları › Entegrasyonlar).')
    img, media = _page_png(Path(path))
    b64 = base64.standard_b64encode(img).decode()
    import anthropic
    headers = {'anthropic-workspace-id': config.AI_WORKSPACE_ID} if config.AI_WORKSPACE_ID else None
    client = anthropic.Anthropic(api_key=config.AI_API_KEY, default_headers=headers, timeout=90)
    # El yazısı için okuma gücü yüksek bir model (yapılandırmadaki model haiku ise de çalışır)
    model = config.AI_MODEL
    kwargs = dict(model=model, max_tokens=1500,
                  messages=[{'role': 'user', 'content': [
                      {'type': 'image', 'source': {'type': 'base64', 'media_type': media, 'data': b64}},
                      {'type': 'text', 'text': PROMPT}]}])
    if 'haiku' not in model:
        kwargs['thinking'] = {'type': 'disabled'}
    resp = client.messages.create(**kwargs)
    text = ''.join(b.text for b in resp.content if b.type == 'text').strip()
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        raise RuntimeError('Model yapılandırılmış veri döndürmedi.')
    data = json.loads(m.group(0))
    out = {k: (str(data[k]).strip() or None) if data.get(k) not in (None, '', 'null') else None for k in FIELDS}
    usage = resp.usage
    return {'fields': out, 'tokens': {'in': getattr(usage, 'input_tokens', 0), 'out': getattr(usage, 'output_tokens', 0)}, 'model': model}
