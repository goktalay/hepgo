"""Evrak metin çıkarma (OCR) ve arama dizini.

Yüklenen evrak arka planda işlenir: PDF'in metin katmanı varsa o alınır, yoksa sayfalar 300 dpi resme
çevrilip Tesseract ile (Türkçe + İngilizce) okunur; resimler doğrudan okunur; .txt/.docx metni çıkarılır.
Ses dosyası ve videonun sesi metne çevrilir, videoda yüzler bulunur (app/document_media.py). Diğer türlerde metin
çıkarılmaz. Sonuç documents.ocr_text'e ve documents_fts arama dizinine yazılır.

Tesseract sistem paketi değildir: Ubuntu paketlerinden vendor/ocr/root altına açılmıştır (bkz. README).
"""
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path

from . import config, db
from .document_media import AUDIO_EXT

OCR_ROOT = config.BASE_DIR / 'vendor' / 'ocr' / 'root'
TESSERACT = OCR_ROOT / 'usr' / 'bin' / 'tesseract'
# Kütüphane klasörü işlemci mimarisine göre (x86_64-linux-gnu / aarch64-linux-gnu)
_ARCH = {'arm64': 'aarch64'}.get(platform.machine(), platform.machine())
TESS_ENV = {**os.environ, 'LD_LIBRARY_PATH': str(OCR_ROOT / 'usr' / 'lib' / f'{_ARCH}-linux-gnu'),
            'TESSDATA_PREFIX': str(OCR_ROOT / 'usr' / 'share' / 'tesseract-ocr' / '5' / 'tessdata'),
            'OMP_THREAD_LIMIT': '2'}
LANGS = 'tur+eng'
MAX_PAGES = 300
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp', '.gif'}
def tool(name):
    """Poppler aracı (pdftoppm, pdftotext, pdfinfo): vendor/ocr/root içinde varsa o (sistem paketi gerekmez),
    yoksa PATH'teki. Vendor aracı TESS_ENV ile çalıştırılmalı (LD_LIBRARY_PATH)."""
    p = OCR_ROOT / 'usr' / 'bin' / name
    return str(p) if p.exists() else (shutil.which(name) or name)


VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi', '.3gp', '.ts'}

# ---------- Türkçe arama normalleştirmesi (her karakter tek karaktere eşlenir: konumlar korunur)
_FOLD = str.maketrans('İIıŞşĞğÜüÖöÇçÂâÎîÛû', 'iiissgguuoocc' + 'aaiiuu')


def fold(text):
    """Aramada büyük/küçük harf ve Türkçe harf farkını yok sayar (İ/ı/i, ş/s, ğ/g, ü/u, ö/o, ç/c)."""
    return (text or '').translate(_FOLD).lower()


def kind_of(file_name):
    ext = Path(file_name).suffix.lower()
    if ext == '.pdf':
        return 'EVRAK'
    if ext in IMAGE_EXT or ext in ('.heic', '.heif'):
        return 'RESIM'
    if ext in VIDEO_EXT:
        return 'VIDEO'
    if ext in AUDIO_EXT:
        return 'SES'
    return 'DIGER'


def index(conn, doc_id):
    """Arama dizinini evrakın güncel başlık, not, firma/kişi adları ve OCR metniyle yeniler."""
    d = db.row(conn.execute('SELECT title, note, ocr_text, file_name FROM documents WHERE id = ?', (doc_id,)))
    conn.execute('DELETE FROM documents_fts WHERE rowid = ?', (doc_id,))
    if not d:
        return
    names = [r[0] for r in conn.execute(
        '''SELECT c.name FROM document_companies dc JOIN companies c ON c.id = dc.company_id WHERE dc.document_id = ?
           UNION ALL SELECT p.full_name FROM document_people dp JOIN company_people p ON p.id = dp.person_id
           WHERE dp.document_id = ?''', (doc_id, doc_id))]
    conn.execute('INSERT INTO documents_fts (rowid, title, body) VALUES (?, ?, ?)',
                 (doc_id, fold(f'{d["title"]} {d["file_name"]} {" ".join(names)}'),
                  fold(f'{d["note"] or ""}\n{d["ocr_text"] or ""}')))


# ---------- Metin çıkarma

def _tesseract(image_path):
    out = subprocess.run([str(TESSERACT), str(image_path), '-', '-l', LANGS], env=TESS_ENV,
                         capture_output=True, timeout=600)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors='replace')[-300:] or 'Tesseract hatası')
    return out.stdout.decode('utf-8', errors='replace')


def _pdf(path, thumb):
    info = subprocess.run([tool('pdfinfo'), str(path)], env=TESS_ENV, capture_output=True, timeout=60).stdout.decode(errors='replace')
    m = re.search(r'Pages:\s+(\d+)', info)
    pages = int(m.group(1)) if m else None
    subprocess.run([tool('pdftoppm'), '-f', '1', '-l', '1', '-r', '50', '-png', '-singlefile', str(path),
                    str(thumb.with_suffix(''))], env=TESS_ENV, capture_output=True, timeout=120)
    text = subprocess.run([tool('pdftotext'), '-layout', str(path), '-'], env=TESS_ENV, capture_output=True,
                          timeout=300).stdout.decode(
        'utf-8', errors='replace')
    # Metin katmanı yeterliyse (dijital PDF) OCR gerekmez; taranmış PDF'te sayfalar resim olarak okunur
    if len(text.strip()) >= 40 * max(1, pages or 1):
        return text, pages
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([tool('pdftoppm'), '-r', '300', '-gray', '-png', '-l', str(MAX_PAGES), str(path), f'{tmp}/p'],
                       env=TESS_ENV, capture_output=True, timeout=3600, check=True)
        parts = [_tesseract(p) for p in sorted(Path(tmp).glob('p*.png'))]
    return '\f'.join(parts), pages


def _image(path, thumb):
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        small = im.copy()
        small.thumbnail((480, 480))
        small.convert('RGB').save(thumb, 'PNG')
        with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
            im.convert('L').save(tmp.name, 'PNG')
            return _tesseract(tmp.name), 1


def _docx(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf-8', errors='replace')
    xml = re.sub(r'</w:p>', '\n', xml)
    return re.sub(r'<[^>]+>', '', xml)


def extract(path, thumb):
    """(metin, sayfa sayısı, küçük resim var mı); metin çıkarılmayan türde metin None."""
    ext = path.suffix.lower()
    if ext == '.pdf':
        text, pages = _pdf(path, thumb)
    elif ext in IMAGE_EXT:
        text, pages = _image(path, thumb)
    elif ext in ('.txt', '.csv', '.md'):
        text, pages = path.read_text(encoding='utf-8', errors='replace'), None
    elif ext == '.docx':
        text, pages = _docx(path), None
    else:
        return None, None, False
    return text.strip(), pages, thumb.exists()


def _media(path, thumb):
    """Ses / video: (konuşma metni ya da None, None, küçük resim var mı, yüzler ya da None, süre sn).
    Yüz bulma hatası metni engellemez (yüzler boş kalır)."""
    from . import document_media as m
    video = path.suffix.lower() in VIDEO_EXT
    faces, duration = None, None
    if video:
        duration = m.video_duration(path)
        try:
            m.video_thumb(path, thumb)
        except Exception:
            pass
        if m.faces_available():
            try:
                faces = m.detect_faces(path, duration)
            except Exception:
                faces = None
    from . import speech
    if not speech.enabled('documents'):   # konuşma tanıma kapalı: yalnız kayıt (süre / küçük resim / yüzler)
        if duration is None:
            try:
                duration = m.video_duration(path)
            except Exception:
                duration = None
        return None, None, thumb.exists(), faces, duration
    text, seconds = m.transcribe(path)
    return (text or None), None, thumb.exists(), faces, duration or seconds


def image_faces(path):
    """Resimdeki yüzler; resim değilse ya da yüz tanıma kurulu değilse None. Yüz bulma hatası metni engellemez."""
    from . import document_media as m
    if path.suffix.lower() not in IMAGE_EXT or not m.faces_available():
        return None
    try:
        return m.detect_faces_image(path)
    except Exception:
        return None


# ---------- Arka plan işçisi
_running = set()
_lock = threading.Lock()


def _run(doc_id):
    try:
        with db.connect() as conn:
            d = db.row(conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)))
            if not d:
                return
            conn.execute("UPDATE documents SET ocr_status = 'ISLENIYOR' WHERE id = ?", (doc_id,))
        path = config.UPLOAD_DIR / d['file']
        thumb = path.with_name(path.name + '.thumb.png')
        faces, duration = None, None
        try:
            if path.suffix.lower() in AUDIO_EXT | VIDEO_EXT:
                text, pages, has_thumb, faces, duration = _media(path, thumb)
            else:
                text, pages, has_thumb = extract(path, thumb)
            status, error = ('YOK', None) if text is None else ('TAMAM', None)
        except Exception as exc:   # bozuk dosya, zaman aşımı: evrak durur, hata gösterilir
            text, pages, has_thumb, status, error = None, None, thumb.exists(), 'HATA', f'Metin çıkarılamadı: {exc}'[:500]
        if faces is None:
            faces = image_faces(path)   # resimdeki kişiler (metin okunamasa da)
        with db.connect() as conn:
            conn.execute('''UPDATE documents SET ocr_status = ?, ocr_text = ?, ocr_error = ?, pages = COALESCE(?, pages),
                            thumb = ?, duration = COALESCE(?, duration) WHERE id = ?''',
                         (status, text, error, pages, f'documents/{thumb.name}' if has_thumb else None, duration, doc_id))
            if faces is not None:
                from .document_media import save_faces
                try:   # yüz kaydı hatası evrakı "işleniyor"da bırakmasın
                    conn.execute('SAVEPOINT faces')
                    save_faces(conn, doc_id, path, faces)
                    conn.execute('RELEASE faces')
                except Exception:
                    conn.execute('ROLLBACK TO faces')
                    conn.execute('RELEASE faces')
            index(conn, doc_id)
    finally:
        with _lock:
            _running.discard(doc_id)


def start(doc_id):
    with _lock:
        if doc_id in _running:
            return
        _running.add(doc_id)
    threading.Thread(target=_run, args=(doc_id,), daemon=True, name=f'ocr-{doc_id}').start()


def resume_pending():
    """Sunucu yeniden başladığında yarım kalan metin çıkarma işlerini sürdürür."""
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE ocr_status IN ('BEKLIYOR', 'ISLENIYOR')")]
    for doc_id in ids:
        start(doc_id)


def available():
    return TESSERACT.exists() and Path(tool('pdftoppm')).is_absolute()
