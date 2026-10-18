"""Araçlar › Convert Master (web) — dosya dönüştürme.

Görsel (Pillow: png/jpg/webp/bmp/ico + yeniden boyutlandır), görsel→PDF (Pillow), PDF→görsel (yalnız sunucuda pdftoppm varsa),
metin kodlama/satır sonu, JSON↔CSV↔XLSX (XLSX stdlib zipfile ile yazılır/okunur; openpyxl GEREKMEZ).
Base64/hex/url ve birim dönüştürücü tarayıcıda çalışır. Çıktılar DATA_DIR/tools/tmp altında 1 saat saklanır.
"""
import asyncio
import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .tools_common import new_tmp, safe_name, tmp_path, tools_user

router = APIRouter(prefix='/api/tools/convert')
IMG_FORMATS = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'webp': 'WEBP', 'bmp': 'BMP', 'ico': 'ICO', 'gif': 'GIF', 'tiff': 'TIFF'}
MAX_UPLOAD = 200 * 1024 * 1024
PDFTOPPM = shutil.which('pdftoppm')


@router.get('/caps')
def caps(user=Depends(tools_user)):
    return {'image': sorted(set(IMG_FORMATS) - {'jpeg'}), 'image_to_pdf': True, 'pdf_to_image': bool(PDFTOPPM),
            'pdf_note': None if PDFTOPPM else 'PDF→görsel için sunucuda pdftoppm (poppler-utils) yok; yalnız görsel→PDF çalışır',
            'xlsx': True}


def _out(token, path, extra=None):
    return {'token': token, 'name': token.split('__', 1)[1], 'size': path.stat().st_size, 'url': f'/api/tools/convert/download/{token}', **(extra or {})}


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, 'Dosya 200 MB sınırını aşıyor')
    return data


def _stem(name):
    return safe_name(name).rsplit('.', 1)[0] or 'dosya'


# ---------------- Görsel ----------------
def _convert_image(data, fmt, width, height, quality, keep_ratio):
    from PIL import Image   # noqa: PLC0415
    im = Image.open(io.BytesIO(data))
    im.load()
    if width or height:
        w, h = im.size
        tw, th = width or 0, height or 0
        if keep_ratio or not (tw and th):
            if tw and not th:
                th = round(h * tw / w)
            elif th and not tw:
                tw = round(w * th / h)
            else:
                r = min(tw / w, th / h)
                tw, th = round(w * r), round(h * r)
        im = im.resize((max(1, tw), max(1, th)), Image.LANCZOS)
    pil = IMG_FORMATS[fmt]
    if pil in ('JPEG', 'BMP') and im.mode not in ('RGB', 'L'):
        bg = Image.new('RGB', im.size, (255, 255, 255))
        if im.mode in ('RGBA', 'LA', 'P'):
            im = im.convert('RGBA')
            bg.paste(im, mask=im.split()[-1])
        else:
            bg.paste(im.convert('RGB'))
        im = bg
    out = io.BytesIO()
    kw = {}
    if pil in ('JPEG', 'WEBP'):
        kw['quality'] = quality
    if pil == 'ICO':
        im.thumbnail((256, 256))
        kw['sizes'] = [im.size]
    im.save(out, format=pil, **kw)
    return out.getvalue(), im.size


@router.post('/image')
async def image(file: UploadFile, fmt: str = Form('png'), width: Optional[int] = Form(None), height: Optional[int] = Form(None),
                quality: int = Form(88), keep_ratio: bool = Form(True), user=Depends(tools_user)):
    fmt = fmt.lower().lstrip('.')
    if fmt not in IMG_FORMATS:
        raise HTTPException(400, 'Desteklenmeyen hedef biçim')
    data = await _read_upload(file)
    try:
        res, size = await asyncio.to_thread(_convert_image, data, fmt, width, height, min(100, max(1, quality)), keep_ratio)
    except Exception as e:   # noqa: BLE001
        raise HTTPException(400, f'Görsel dönüştürülemedi: {e}') from None
    token, p = new_tmp(f'{_stem(file.filename)}.{fmt}')
    p.write_bytes(res)
    return _out(token, p, {'width': size[0], 'height': size[1]})


# ---------------- PDF ----------------
def _images_to_pdf(blobs):
    from PIL import Image   # noqa: PLC0415
    pages = []
    for b in blobs:
        im = Image.open(io.BytesIO(b))
        im.load()
        if im.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', im.size, (255, 255, 255))
            im = im.convert('RGBA')
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != 'RGB':
            im = im.convert('RGB')
        pages.append(im)
    out = io.BytesIO()
    pages[0].save(out, format='PDF', save_all=True, append_images=pages[1:], resolution=150)
    return out.getvalue()


def _pdf_to_images(data, fmt, dpi):
    with tempfile.TemporaryDirectory(prefix='mt-pdf-') as d:
        src = Path(d) / 'in.pdf'
        src.write_bytes(data)
        subprocess.run([PDFTOPPM, '-r', str(dpi), '-png' if fmt == 'png' else '-jpeg', str(src), str(Path(d) / 'sayfa')],
                       check=True, capture_output=True, timeout=300)
        files = sorted(Path(d).glob('sayfa*'))
        if not files:
            raise RuntimeError('sayfa üretilemedi')
        if len(files) == 1:
            return files[0].read_bytes(), fmt
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.name)
        return out.getvalue(), 'zip'


@router.post('/pdf')
async def pdf(files: List[UploadFile], fmt: str = Form('png'), dpi: int = Form(150), user=Depends(tools_user)):
    if not files:
        raise HTTPException(400, 'Dosya seçin')
    blobs = [await _read_upload(f) for f in files]
    first = files[0]
    if (first.filename or '').lower().endswith('.pdf') or blobs[0][:5] == b'%PDF-':
        if not PDFTOPPM:
            raise HTTPException(400, 'PDF→görsel için sunucuda pdftoppm (poppler-utils) kurulu değil')
        fmt = 'jpg' if fmt.lower() in ('jpg', 'jpeg') else 'png'
        try:
            res, ext = await asyncio.to_thread(_pdf_to_images, blobs[0], fmt, min(600, max(36, dpi)))
        except Exception as e:   # noqa: BLE001
            raise HTTPException(400, f'PDF dönüştürülemedi: {e}') from None
        token, p = new_tmp(f'{_stem(first.filename)}.{ext}')
    else:
        try:
            res = await asyncio.to_thread(_images_to_pdf, blobs)
        except Exception as e:   # noqa: BLE001
            raise HTTPException(400, f'PDF üretilemedi: {e}') from None
        token, p = new_tmp(f'{_stem(first.filename)}.pdf')
    p.write_bytes(res)
    return _out(token, p, {'pages': len(blobs)})


# ---------------- Metin kodlama / satır sonu ----------------
ENCODINGS = ('utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1254', 'iso-8859-9', 'cp1252', 'iso-8859-1', 'cp1251', 'cp1256', 'ascii')


@router.post('/text')
async def text(file: Optional[UploadFile] = None, content: Optional[str] = Form(None), enc_from: str = Form('utf-8'),
               enc_to: str = Form('utf-8'), eol: str = Form('keep'), name: str = Form('metin.txt'), user=Depends(tools_user)):
    if enc_from not in ENCODINGS or enc_to not in ENCODINGS:
        raise HTTPException(400, 'Desteklenmeyen kodlama')
    if file is not None:
        raw = await _read_upload(file)
        name = file.filename or name
        try:
            s = raw.decode(enc_from)
        except UnicodeDecodeError as e:
            raise HTTPException(400, f'Kaynak kodlama uymuyor ({enc_from}): {e.reason}') from None
    else:
        s = content or ''
    if eol in ('lf', 'crlf', 'cr'):
        s = s.replace('\r\n', '\n').replace('\r', '\n')
        s = s.replace('\n', {'lf': '\n', 'crlf': '\r\n', 'cr': '\r'}[eol])
    try:
        out = s.encode(enc_to)
    except UnicodeEncodeError as e:
        raise HTTPException(400, f'Hedef kodlamada karşılığı olmayan karakter: {e.object[e.start:e.end]!r}') from None
    token, p = new_tmp(safe_name(name, 'metin.txt'))
    p.write_bytes(out)
    return _out(token, p, {'chars': len(s), 'lines': s.count('\n') + (1 if s and not s.endswith('\n') else 0)})


# ---------------- JSON ↔ CSV ↔ XLSX ----------------
def _rows_from_json(s):
    data = json.loads(s)
    if isinstance(data, dict):
        for v in data.values():   # {"veri": [...]} biçimi
            if isinstance(v, list):
                data = v
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError('JSON bir nesne listesi olmalı')
    if data and all(isinstance(r, list) for r in data):
        return [[_cell(v) for v in r] for r in data]
    cols = []
    for r in data:
        if not isinstance(r, dict):
            raise ValueError('JSON öğeleri nesne (sözlük) olmalı')
        for k in r:
            if k not in cols:
                cols.append(k)
    return [cols] + [[_cell(r.get(c)) for c in cols] for r in data]


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _rows_from_csv(s, delimiter):
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(s[:4096], delimiters=',;\t|').delimiter
        except csv.Error:
            delimiter = ','
    return [list(r) for r in csv.reader(io.StringIO(s.lstrip('﻿')), delimiter=delimiter)]


def _col_letter(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_bytes(rows):
    """Tek sayfalı XLSX (inlineStr hücreler; sayılar sayı olarak)."""
    cells = []
    for ri, row in enumerate(rows, 1):
        parts = []
        for ci, v in enumerate(row):
            ref = f'{_col_letter(ci)}{ri}'
            if isinstance(v, bool):
                parts.append(f'<c r="{ref}" t="b"><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)) and v == v and abs(v) != float('inf'):
                parts.append(f'<c r="{ref}"><v>{v!r}</v></c>')
            else:
                sv = '' if v is None else str(v)
                sv = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', sv)
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(sv)}</t></is></c>')
        cells.append(f'<row r="{ri}">{"".join(parts)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + ''.join(cells) + '</sheetData></worksheet>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '</Types>')
        z.writestr('_rels/.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr('xl/workbook.xml',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Sayfa1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return out.getvalue()


NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def _col_index(ref):
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _rows_from_xlsx(data):
    """İlk sayfayı okur (paylaşılan dizgeler + inlineStr + sayı/boole)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
                shared.append(''.join(t.text or '' for t in si.iter(f'{{{NS["m"]}}}t')))
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        first = wb.find('m:sheets/m:sheet', NS)
        target = rels.get(first.get(f'{{{NS["r"]}}}id'), 'worksheets/sheet1.xml') if first is not None else 'worksheets/sheet1.xml'
        target = target.lstrip('/')
        path = target if target.startswith('xl/') else 'xl/' + target
        rows = []
        for row in ET.fromstring(z.read(path)).iter(f'{{{NS["m"]}}}row'):
            vals = {}
            for c in row.findall('m:c', NS):
                ci = _col_index(c.get('r', 'A'))
                t = c.get('t')
                v = c.find('m:v', NS)
                if t == 's':
                    val = shared[int(v.text)] if v is not None and v.text else ''
                elif t == 'inlineStr':
                    val = ''.join(x.text or '' for x in c.iter(f'{{{NS["m"]}}}t'))
                elif t == 'b':
                    val = bool(int(v.text)) if v is not None and v.text else False
                elif v is None or v.text is None:
                    val = ''
                elif t == 'str':
                    val = v.text
                else:
                    try:
                        f = float(v.text)
                        val = int(f) if f.is_integer() and 'e' not in v.text.lower() and '.' not in v.text else f
                    except ValueError:
                        val = v.text
                vals[ci] = val
            width = max(vals) + 1 if vals else 0
            rows.append([vals.get(i, '') for i in range(width)])
        return rows


def _to_json(rows, as_objects):
    if not as_objects or not rows:
        return json.dumps(rows, ensure_ascii=False, indent=2)
    head = [str(h) for h in rows[0]]
    return json.dumps([dict(zip(head, r + [''] * (len(head) - len(r)))) for r in rows[1:]], ensure_ascii=False, indent=2)


def _to_csv(rows, delimiter):
    out = io.StringIO()
    w = csv.writer(out, delimiter=delimiter or ',', lineterminator='\r\n')
    for r in rows:
        w.writerow(['' if v is None else v for v in r])
    return out.getvalue()


@router.post('/data')
async def data(file: Optional[UploadFile] = None, content: Optional[str] = Form(None), src: str = Form('json'), dst: str = Form('csv'),
               delimiter: str = Form(''), out_delimiter: str = Form(','), objects: bool = Form(True), name: str = Form('veri'), user=Depends(tools_user)):
    if src not in ('json', 'csv', 'xlsx') or dst not in ('json', 'csv', 'xlsx'):
        raise HTTPException(400, 'Geçersiz biçim')
    raw = await _read_upload(file) if file is not None else None
    if file is not None:
        name = file.filename or name
    try:
        if src == 'xlsx':
            if raw is None:
                raise HTTPException(400, 'XLSX için dosya yükleyin')
            rows = await asyncio.to_thread(_rows_from_xlsx, raw)
        else:
            s = raw.decode('utf-8-sig', errors='replace') if raw is not None else (content or '')
            rows = _rows_from_json(s) if src == 'json' else _rows_from_csv(s, delimiter)
    except HTTPException:
        raise
    except Exception as e:   # noqa: BLE001
        raise HTTPException(400, f'Kaynak okunamadı: {e}') from None
    stem = _stem(name)
    preview = None
    if dst == 'xlsx':
        res = _xlsx_bytes(rows)
        token, p = new_tmp(f'{stem}.xlsx')
    else:
        txt = _to_json(rows, objects) if dst == 'json' else _to_csv(rows, out_delimiter[:1] or ',')
        res = txt.encode('utf-8')
        preview = txt[:20000]
        token, p = new_tmp(f'{stem}.{dst}')
    p.write_bytes(res)
    return _out(token, p, {'rows': len(rows), 'preview': preview})


@router.get('/download/{token}')
def download(token: str, user=Depends(tools_user)):
    p = tmp_path(token)
    if not p:
        raise HTTPException(404, 'Dosya bulunamadı ya da süresi (1 saat) doldu')
    return FileResponse(p, filename=token.split('__', 1)[1], media_type='application/octet-stream')
