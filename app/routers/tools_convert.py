"""Araçlar › Convert Master (web) — masaüstü uygulamanın ana süreci (main.js + jobs.js + media.js) Python'a taşındı.
Arayüz static/mt/convertmaster (orijinal renderer); köprü bridge.js aynı IPC adlarıyla buraya gelir.

Depo: tools_mt_store('convertmaster','store') — masaüstündeki store.json şeması
  { folders, projects:[{id,name,type,sourceExts,targetExt,sourceMode,includeSubfolders,concurrency,speech,ocr,options,folderId,color,notes}],
    local:{pid:{sourcePath, unchecked:[rel]}}, syncMeta, settings:{…} }
Kaynak dosyalar kullanıcının sunucudaki alanındadır (DATA_DIR/tools/convertmaster/<uid>/files; diyalogdan yüklenir).
Çıktılar converted/<pid>/…, durum work/<pid>/state.json, önizleme kopyaları cache/preview — masaüstüyle aynı düzen.
Motorlar: resimler Pillow; video/ses ffmpeg (sunucuda yoksa orijinal "ffmpeg bulunamadı" hatası); konuşmadan metne
(whisper) ve OCR (tesseract) bu sunucuda kurulu değil → ayarlarda "motor yok", indirme kapalı.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .tools_common import safe_name, tools_user
from . import tools_common as tc
from . import tools_mt as mt

router = APIRouter(prefix='/api/tools/convert')
APP = 'convertmaster'
LANGS = (None, 'tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru')
FFMPEG = shutil.which('ffmpeg')
try:
    from PIL import Image, ImageOps
except ImportError:   # pragma: no cover
    Image = ImageOps = None

# formats.js ile aynı tablolar
TYPES = {
    'video': {'color': '#a855f7',
              'source': ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'webm', 'flv', 'm4v', 'mpg', 'mpeg', 'ts', 'mts', 'm2ts', '3gp', 'ogv', 'vob'],
              'target': ['mp4', 'mkv', 'webm', 'avi', 'mov', 'wmv', 'flv', 'm4v', 'mpg', '3gp', 'ogv', 'gif', 'mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'],
              'audioOnlyTargets': ['mp3', 'm4a', 'wav', 'flac', 'ogg', 'opus'], 'play': ['mp4', 'm4v', 'webm', 'ogv', 'mov', 'mkv'],
              'defaultSource': ['mkv', 'avi', 'mov', 'wmv'], 'defaultTarget': 'mp4'},
    'image': {'color': '#34d399', 'source': ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tif', 'tiff', 'ico', 'svg', 'tga'],
              'target': ['jpg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tiff', 'ico'], 'play': ['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'ico', 'svg'],
              'defaultSource': ['png', 'bmp', 'tif', 'tiff'], 'defaultTarget': 'jpg'},
    'audio': {'color': '#f97316', 'source': ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'oga', 'opus', 'wma', 'aiff', 'aif', 'amr', 'ac3', 'mka', 'ape', 'wv'],
              'target': ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'opus', 'wma', 'aiff', 'ac3'], 'play': ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'oga', 'opus', 'webm'],
              'defaultSource': ['wav', 'flac', 'wma', 'm4a'], 'defaultTarget': 'mp3'},
}
SPEECH_MODELS = {'tiny': 'ggml-tiny.bin', 'base': 'ggml-base.bin', 'small': 'ggml-small.bin', 'medium': 'ggml-medium-q5_0.bin', 'turbo': 'ggml-large-v3-turbo-q5_0.bin'}
SPEECH_LANGS = ['auto', 'tr', 'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'ru', 'uk', 'ar', 'fa', 'az', 'el', 'bg', 'ro', 'pl', 'cs', 'hu', 'sv', 'no', 'da', 'fi',
                'zh', 'ja', 'ko', 'hi', 'ur', 'id', 'ms', 'th', 'vi', 'he']
OCR_LANGS = ['tur', 'eng', 'deu', 'fra', 'spa', 'ita', 'por', 'nld', 'rus', 'ukr', 'ara', 'fas', 'heb', 'aze', 'ell', 'pol', 'chi_sim', 'chi_tra', 'jpn', 'kor', 'hin']
QUALITY = ['high', 'medium', 'low']
RESOLUTIONS = ['source', '2160', '1440', '1080', '720', '480', '360']
FPS = ['source', '60', '50', '30', '25', '24', '15']
AUDIO_BITRATES = ['64', '96', '128', '160', '192', '256', '320']
SAMPLE_RATES = ['source', '48000', '44100', '32000', '22050', '16000']
MIME = {'mp4': 'video/mp4', 'm4v': 'video/mp4', 'mov': 'video/mp4', 'webm': 'video/webm', 'ogv': 'video/ogg', 'mkv': 'video/x-matroska',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'flac': 'audio/flac', 'aac': 'audio/aac', 'm4a': 'audio/mp4', 'ogg': 'audio/ogg', 'oga': 'audio/ogg', 'opus': 'audio/ogg',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp', 'avif': 'image/avif', 'bmp': 'image/bmp',
        'ico': 'image/x-icon', 'svg': 'image/svg+xml'}
# mtweb kancaları (app/mtweb; HEPGO'da varsayılanlar → davranış değişmez)
JOB_GATE = None          # callable(uid, src: Path, out: Path, cancel) → bağlam yöneticisi: eşzamanlılık / giriş boyutu / kota
FFMPEG_PREFIX = []       # ör. ['nice', '-n', '15'] — dönüştürücü süreç düşük öncelikle
FFMPEG_THREADS = 0       # > 0 → çıktıdan önce '-threads N'
FFMPEG_TIMEOUT = 0       # sn; > 0 → aşımda süreç öldürülür (ConvertError 'timeout')
MAX_CONCURRENCY = 32     # proje başına eşzamanlı dosya tavanı
PIL_WRITE = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF', 'bmp': 'BMP', 'tiff': 'TIFF', 'tif': 'TIFF', 'ico': 'ICO', 'avif': 'AVIF'}


def ext_of(p):
    m = re.search(r'\.([^./\\]+)$', str(p or ''))
    return m.group(1).lower() if m else ''


def _one(v, lst, d):
    return v if v in lst else d


def _num(v, d, lo, hi):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return d
    return int(min(hi, max(lo, round(n))))


def default_options():
    return {'video': {'quality': 'medium', 'resolution': 'source', 'fps': 'source', 'codec': 'h264', 'speed': 'medium', 'audioBitrate': '192', 'noAudio': False},
            'image': {'quality': 85, 'maxWidth': 0, 'maxHeight': 0, 'keepMeta': False},
            'audio': {'bitrate': '192', 'sampleRate': 'source', 'channels': 'source'}}


def clean_options(o):
    o = o if isinstance(o, dict) else {}
    d = default_options()
    v, i, a = o.get('video') or {}, o.get('image') or {}, o.get('audio') or {}
    return {
        'video': {'quality': _one(v.get('quality'), QUALITY, d['video']['quality']), 'resolution': _one(str(v.get('resolution')), RESOLUTIONS, d['video']['resolution']),
                  'fps': _one(str(v.get('fps')), FPS, d['video']['fps']), 'codec': _one(v.get('codec'), ['h264', 'h265'], d['video']['codec']),
                  'speed': _one(v.get('speed'), ['veryfast', 'fast', 'medium', 'slow'], d['video']['speed']),
                  'audioBitrate': _one(str(v.get('audioBitrate')), AUDIO_BITRATES, d['video']['audioBitrate']), 'noAudio': bool(v.get('noAudio'))},
        'image': {'quality': _num(i.get('quality'), d['image']['quality'], 1, 100), 'maxWidth': _num(i.get('maxWidth'), 0, 0, 20000),
                  'maxHeight': _num(i.get('maxHeight'), 0, 0, 20000), 'keepMeta': bool(i.get('keepMeta'))},
        'audio': {'bitrate': _one(str(a.get('bitrate')), AUDIO_BITRATES, d['audio']['bitrate']), 'sampleRate': _one(str(a.get('sampleRate')), SAMPLE_RATES, d['audio']['sampleRate']),
                  'channels': _one(a.get('channels'), ['source', 'stereo', 'mono'], d['audio']['channels'])},
    }


def default_store():
    return {'folders': [], 'projects': [], 'local': {}, 'syncMeta': {},
            'settings': {'appTheme': 'system', 'language': None, 'openAtLogin': False, 'minimizeToTray': False, 'closeToTray': False,
                         'defaultConcurrency': 2, 'speechModel': 'base', 'speechConcurrency': 1, 'ocrLanguages': ['tur', 'eng'],
                         'previewHeight': 320, 'treeWidth': 280, 'transcriptWidth': 380, 'linkPreview': True}}


def load_store(uid):
    raw = mt.kv_get(uid, APP, 'store') or {}
    s = {**default_store(), **raw}
    s['settings'] = {**default_store()['settings'], **(raw.get('settings') or {})}
    s.setdefault('local', {})
    s.setdefault('syncMeta', {})
    return s


def save_store(uid, s):
    mt.kv_set(uid, APP, 'store', s)


def get_local(s, pid):
    return s['local'].setdefault(pid, {'sourcePath': '', 'unchecked': []})


def project_for(s, pid):
    p = next((x for x in s['projects'] if x['id'] == pid), None)
    return {**p, 'sourcePath': get_local(s, pid).get('sourcePath') or ''} if p else None


def public_store(s):
    return {'folders': s['folders'], 'settings': s['settings'], 'projects': [project_for(s, p['id']) for p in s['projects']]}


# --- Hata metinleri (errText) --------------------------------------------------------------------------------
class ConvertError(Exception):
    def __init__(self, code, message='', detail=''):
        super().__init__(message or code)
        self.code = code
        self.detail = detail


ERR_TEXT = {
    'canceled': 'İptal edildi', 'unreadable': 'Dosya okunamadı (bozuk ya da desteklenmeyen biçim)', 'no_video': 'Dosyada görüntü akışı yok',
    'no_audio': 'Dosyada ses yok', 'unsupported': 'Bu biçim desteklenmiyor', 'ffmpeg_missing': 'ffmpeg bulunamadı: video/ses dönüştürme bu sunucuda kapalı',
    'engine_missing': 'Konuşma motoru (whisper) bu sunucuda kurulu değil', 'download_failed': 'İndirme başarısız: {msg}',
    'timeout': 'Süre sınırı aşıldı', 'ENOENT': 'Dosya bulunamadı', 'EACCES': 'Erişim izni yok', 'ENOSPC': 'Diskte yer kalmadı',
}


def err_text(err):
    code = getattr(err, 'code', None)
    if code in ERR_TEXT:
        return ERR_TEXT[code].replace('{msg}', str(err))
    if code == 'ffmpeg_failed':
        return f'ffmpeg hatası: {err}'
    if isinstance(err, FileNotFoundError):
        return ERR_TEXT['ENOENT']
    if isinstance(err, PermissionError):
        return ERR_TEXT['EACCES']
    return str(err) or err.__class__.__name__


# --- Medya motoru (media.js): resimler Pillow, video/ses ffmpeg -------------------------------------------------
def run_ffmpeg(args, duration=0, on_progress=None, cancel=None):
    if not FFMPEG:
        raise ConvertError('ffmpeg_missing')
    if cancel and cancel.is_set():
        raise ConvertError('canceled')
    if FFMPEG_THREADS > 0 and args:
        args = [*args[:-1], '-threads', str(int(FFMPEG_THREADS)), args[-1]]
    proc = subprocess.Popen([*FFMPEG_PREFIX, FFMPEG, '-hide_banner', '-nostdin', '-y', '-progress', 'pipe:1', '-nostats', *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    err_lines = []
    timed_out = threading.Event()
    watchdog = None
    if FFMPEG_TIMEOUT > 0:
        def _kill():
            timed_out.set()
            proc.kill()
        watchdog = threading.Timer(FFMPEG_TIMEOUT, _kill)
        watchdog.daemon = True
        watchdog.start()

    def read_err():
        for ln in proc.stderr:
            err_lines.append(ln.rstrip())
            if len(err_lines) > 400:
                del err_lines[:200]
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    for ln in proc.stdout:
        m = re.match(r'^out_time_(?:us|ms)=(\d+)', ln.strip())
        if m and duration > 0 and on_progress:
            on_progress(min(0.999, int(m.group(1)) / 1e6 / duration))
        if cancel and cancel.is_set():
            proc.kill()
    proc.wait()
    t.join(timeout=2)
    if watchdog:
        watchdog.cancel()
    if timed_out.is_set():
        raise ConvertError('timeout')
    if cancel and cancel.is_set():
        raise ConvertError('canceled')
    if proc.returncode != 0:
        noise = re.compile(r'Conversion failed|Nothing was written|Task finished|^frame=|^size=')
        lines = [x.strip() for x in err_lines if x.strip() and not noise.search(x)]
        bad = [x for x in lines if re.search(r'error|invalid|not supported|unsupported|could not|unable|no such|failed|denied', x, re.I)]
        msg = re.sub(r'^\[[^\]]+\]\s*', '', (bad or lines or ['ffmpeg'])[-1])[:300]
        raise ConvertError('ffmpeg_failed', msg, '\n'.join(err_lines[-20:]))


def probe(file):
    """ffmpeg -i çıktısından süre / akış bilgisi (ffprobe yerine tek ikili)."""
    info = {'duration': 0, 'bitrate': 0, 'video': None, 'audio': None}
    if not FFMPEG:
        info['unreadable'] = True
        return info
    r = subprocess.run([*FFMPEG_PREFIX, FFMPEG, '-hide_banner', '-nostdin', '-i', str(file)], capture_output=True, text=True, errors='replace', timeout=60)
    err = r.stderr
    d = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', err)
    if d:
        info['duration'] = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    b = re.search(r'bitrate:\s*(\d+)\s*kb/s', err)
    if b:
        info['bitrate'] = int(b.group(1))
    v = re.search(r'Stream #\d+:\d+.*?: Video: (\w+).*?,\s*(\d{2,5})x(\d{2,5})', err)
    if v:
        info['video'] = {'codec': v.group(1), 'width': int(v.group(2)), 'height': int(v.group(3))}
        f = re.search(r'(\d+(?:\.\d+)?) fps', err)
        if f:
            info['video']['fps'] = float(f.group(1))
    a = re.search(r'Stream #\d+:\d+.*?: Audio: (\w+).*?,\s*(\d+) Hz,\s*([\w.]+)', err)
    if a:
        info['audio'] = {'codec': a.group(1), 'sampleRate': int(a.group(2)), 'channels': a.group(3)}
    if not info['video'] and not info['audio'] and 'Input #0' not in err:
        info['unreadable'] = True
    return info


def media_info(file):
    st = os.stat(file)
    ext = ext_of(file)
    info = probe(file) if ext not in TYPES['image']['source'] else {'duration': 0, 'bitrate': 0, 'video': None, 'audio': None}
    if not info['video'] and not info['audio'] and Image is not None:
        try:
            with Image.open(file) as im:
                info['video'] = {'codec': (im.format or '').lower(), 'width': im.width, 'height': im.height}
            info.pop('unreadable', None)
        except Exception:   # noqa: BLE001 — ne ffmpeg ne Pillow okudu
            pass
    return {**info, 'size': st.st_size, 'ext': ext}


def image_convert(src, out, target, o):
    if Image is None:
        raise ConvertError('unsupported', 'Pillow kurulu değil')
    fmt = PIL_WRITE.get(target)
    if not fmt:
        raise ConvertError('unsupported')
    try:
        im = Image.open(src)
    except Exception as e:   # noqa: BLE001
        if ext_of(src) in ('svg', 'tga', 'avif'):
            raise ConvertError('unsupported', f'{ext_of(src).upper()} kaynağı bu sunucuda okunamıyor') from None
        raise ConvertError('unreadable', str(e)) from None
    with im:
        animated = getattr(im, 'is_animated', False) and target in ('gif', 'webp')
        exif = im.info.get('exif') if o.get('keepMeta') else None
        img = ImageOps.exif_transpose(im) if not animated else im
        mw, mh = int(o.get('maxWidth') or 0), int(o.get('maxHeight') or 0)
        if (mw or mh) and not animated:
            img.thumbnail((mw or 10 ** 6, mh or 10 ** 6))
        q = max(1, min(100, int(o.get('quality') or 85)))
        kw = {}
        if fmt == 'JPEG':
            if img.mode not in ('RGB', 'L'):
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[-1])
                img = bg
            kw = {'quality': q, 'optimize': True, 'progressive': True}
        elif fmt == 'PNG':
            kw = {'optimize': True}
            if q < 80 and img.mode in ('RGB', 'RGBA'):
                img = img.convert('P', palette=Image.ADAPTIVE)
        elif fmt == 'WEBP':
            kw = {'quality': q}
        elif fmt == 'AVIF':
            kw = {'quality': max(1, q - 20)}
        elif fmt == 'TIFF':
            kw = {'compression': 'jpeg', 'quality': q} if img.mode in ('RGB', 'L') else {'compression': 'tiff_lzw'}
        elif fmt == 'ICO':
            img.thumbnail((256, 256))
        elif fmt == 'BMP' and img.mode not in ('RGB', 'RGBA', 'L', 'P'):
            img = img.convert('RGB')
        if exif:
            kw['exif'] = exif
        if animated:
            kw['save_all'] = True
        try:
            img.save(out, fmt, **kw)
        except (OSError, ValueError) as e:
            if fmt == 'AVIF':
                raise ConvertError('unsupported', 'AVIF yazımı bu sunucuda desteklenmiyor') from None
            raise ConvertError('ffmpeg_failed', str(e)) from None


def video_args(target, o, info):
    T = TYPES['video']
    if target in T['audioOnlyTargets']:
        return audio_only_args(target, o)
    args = []
    vf = []
    if o.get('resolution') not in (None, 'source'):
        vf.append(f"scale=-2:'min({o['resolution']},ih)'")
    if o.get('fps') not in (None, 'source'):
        args += ['-r', str(o['fps'])]
    if target == 'gif':
        vf.append('fps=12,scale=480:-1:flags=lanczos')
        return ['-vf', ','.join(vf), '-an', '-loop', '0']
    if vf:
        args += ['-vf', ','.join(vf)]
    crf = {'high': 18, 'medium': 23, 'low': 28}[o.get('quality') or 'medium']
    if target == 'webm':
        args += ['-c:v', 'libvpx-vp9', '-crf', str(crf + 8), '-b:v', '0', '-row-mt', '1']
    elif target in ('wmv',):
        args += ['-c:v', 'wmv2', '-q:v', str(crf // 3)]
    elif target in ('mpg', 'vob'):
        args += ['-c:v', 'mpeg2video', '-q:v', str(max(2, crf // 4))]
    elif target in ('flv', '3gp'):
        args += ['-c:v', 'libx264', '-crf', str(crf), '-preset', o.get('speed') or 'medium', '-pix_fmt', 'yuv420p']
    elif target == 'ogv':
        args += ['-c:v', 'libtheora', '-q:v', '7']
    else:
        codec = 'libx265' if o.get('codec') == 'h265' else 'libx264'
        args += ['-c:v', codec, '-crf', str(crf if codec == 'libx264' else crf + 5), '-preset', o.get('speed') or 'medium', '-pix_fmt', 'yuv420p']
        if codec == 'libx265':
            args += ['-tag:v', 'hvc1']
        if target in ('mp4', 'm4v', 'mov'):
            args += ['-movflags', '+faststart']
    if o.get('noAudio') or not info.get('audio'):
        args += ['-an']
    else:
        ac = {'webm': 'libopus', 'ogv': 'libvorbis', 'wmv': 'wmav2', 'mpg': 'mp2', 'vob': 'ac3', '3gp': 'aac', 'flv': 'aac'}.get(target, 'aac')
        args += ['-c:a', ac, '-b:a', f"{o.get('audioBitrate') or '192'}k"]
        if ac == 'libopus':
            args += ['-ar', '48000']
    return args


def audio_only_args(target, o):
    codec = {'mp3': 'libmp3lame', 'm4a': 'aac', 'aac': 'aac', 'wav': 'pcm_s16le', 'flac': 'flac', 'ogg': 'libvorbis', 'opus': 'libopus', 'wma': 'wmav2',
             'aiff': 'pcm_s16be', 'ac3': 'ac3'}[target]
    args = ['-vn', '-c:a', codec]
    if codec not in ('pcm_s16le', 'pcm_s16be', 'flac'):
        args += ['-b:a', f"{o.get('bitrate') or o.get('audioBitrate') or '192'}k"]
    if o.get('sampleRate') not in (None, 'source'):
        args += ['-ar', str(o['sampleRate'])]
    elif codec == 'libopus':
        args += ['-ar', '48000']
    if o.get('channels') == 'mono':
        args += ['-ac', '1']
    elif o.get('channels') == 'stereo':
        args += ['-ac', '2']
    return args


def convert(src, out, type_, target, options, on_progress=None, cancel=None):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / f'.~{out.stem}.cvmtmp.{target}'
    o = options or {}
    try:
        if type_ == 'image':
            image_convert(src, tmp, target, o.get('image') or {})
        else:
            info = probe(src)
            if info.get('unreadable'):
                raise ConvertError('unreadable' if FFMPEG else 'ffmpeg_missing')
            if type_ == 'video' and not info['video']:
                raise ConvertError('no_video')
            if type_ == 'audio' and not info['audio']:
                raise ConvertError('no_audio')
            args = video_args(target, o.get('video') or {}, info) if type_ == 'video' else audio_only_args(target, o.get('audio') or {})
            run_ffmpeg(['-i', str(src), *args, str(tmp)], duration=info['duration'], on_progress=on_progress, cancel=cancel)
        if cancel and cancel.is_set():
            raise ConvertError('canceled')
        if out.exists():
            out.unlink()
        tmp.rename(out)
        return {'size': out.stat().st_size}
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# --- Proje çalıştırıcı (jobs.js ProjectRunner) ----------------------------------------------------------------
def sha(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def scan_folder(root: Path, exts, recursive):
    files = []
    want = set(exts)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if recursive and not d.startswith(('.', '$'))]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for name in filenames:
            if name.startswith(('.', '$')) or ext_of(name) not in want:
                continue
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            files.append({'rel': f'{rel_dir}/{name}' if rel_dir != '.' else name, 'size': st.st_size, 'mtime': int(st.st_mtime * 1000)})
    files.sort(key=lambda f: [(int(x) if x.isdigit() else x.lower()) for x in re.split(r'(\d+)', f['rel'])])
    return files


class ProjectRunner:
    def __init__(self, uid, pid):
        self.uid, self.id = uid, pid
        self.work_dir = mt.app_dir(APP, uid, 'work', pid)
        self.out_dir = mt.app_dir(APP, uid, 'converted', pid)
        self.state_file = self.work_dir / 'state.json'
        self.state = {'items': {}}
        try:
            self.state = {'items': {}, **json.loads(self.state_file.read_text('utf-8'))}
        except (OSError, ValueError):
            pass
        self.files = []
        self.root = None
        self.queue = []
        self.speech_queue = []
        self.active = {}        # rel -> cancel Event
        self.speech_active = {}
        self.running = False
        self.pending = {}
        self.events = []        # (seq, ch, data) — pencereye webContents.send karşılığı
        self.seq = 0
        self.lock = threading.RLock()
        self.closed = False
        self.out_map = None
        self.last = time.time()

    # --- depo erişimi -------------------------------------------------------------------------------------
    def project(self):
        return next((p for p in load_store(self.uid)['projects'] if p['id'] == self.id), None)

    def local(self):
        return get_local(load_store(self.uid), self.id)

    def settings(self):
        return load_store(self.uid)['settings']

    def item(self, rel):
        return self.state['items'].setdefault(rel, {'status': 'pending', 'progress': 0})

    # --- kalıcılık ve olaylar ----------------------------------------------------------------------------
    def save(self):
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state), 'utf-8')
        except OSError:
            pass

    def send(self, ch, data):
        with self.lock:
            self.seq += 1
            self.events.append((self.seq, ch, data))
            if len(self.events) > 2000:
                del self.events[:1000]

    def events_since(self, since):
        with self.lock:
            self.flush()
            return self.seq, [{'ch': ch, 'data': d} for s, ch, d in self.events if s > since]

    def touch(self, rel):
        with self.lock:
            self.pending[rel] = {'rel': rel, **self.item(rel)}

    def flush(self):
        if not self.pending:
            return
        items = list(self.pending.values())
        self.pending.clear()
        self.send('job:items', items)

    def emit_state(self):
        self.send('job:state', self.summary())

    def summary(self):
        sel = self.selected()
        c = {'total': len(sel), 'done': 0, 'error': 0, 'active': len(self.active), 'queued': len(self.queue), 'speechActive': len(self.speech_active),
             'speechQueued': len(self.speech_queue)}
        for f in sel:
            it = self.state['items'].get(f['rel'])
            if it and it['status'] == 'done':
                c['done'] += 1
            if it and it['status'] == 'error':
                c['error'] += 1
        return {'running': self.running, 'counts': c}

    # --- tarama ---------------------------------------------------------------------------------------------
    def scan(self):
        p = self.project()
        loc = self.local()
        files_root = mt.files_root(APP, self.uid)
        if not p or not loc.get('sourcePath'):
            self.files, self.root = [], None
            return self.snapshot()
        try:
            src = mt.resolve(files_root, loc['sourcePath'])
        except HTTPException:
            src = None
        files = []
        if p.get('sourceMode') == 'file':
            self.root = src.parent if src else None
            if src and src.is_file():
                st = src.stat()
                files = [{'rel': src.name, 'size': st.st_size, 'mtime': int(st.st_mtime * 1000)}]
        else:
            self.root = src if src and src.is_dir() else None
            if self.root:
                files = scan_folder(self.root, p.get('sourceExts') or [], p.get('includeSubfolders', True) is not False)
        for f in files:   # değişen kaynak dosyalarının sonucu geçersiz
            it = self.state['items'].get(f['rel'])
            if it and 'srcSize' in it and (it['srcSize'] != f['size'] or it.get('srcMtime') != f['mtime']) and f['rel'] not in self.active:
                it.update({'status': 'pending', 'progress': 0, 'error': '', 'outSize': 0})
                it.pop('speech', None)
        self.files = files
        self.compute_outputs()
        self.save()
        return self.snapshot()

    def snapshot(self):
        loc = self.local()
        unchecked = set(loc.get('unchecked') or [])
        p = self.project()
        return {'root': loc.get('sourcePath') or '', 'sourcePath': loc.get('sourcePath') or '',
                'missing': bool(loc.get('sourcePath')) and not self.files and bool(p and p.get('sourceMode') == 'file'),
                'files': [{**f, 'checked': f['rel'] not in unchecked, **self.public_item(f['rel'])} for f in self.files],
                'outDir': f"converted/{self.id}", **self.summary()}

    def public_item(self, rel):
        it = self.state['items'].get(rel) or {'status': 'pending', 'progress': 0}
        return {'status': it['status'], 'progress': it.get('progress', 0), 'error': it.get('error', ''), 'outSize': it.get('outSize', 0),
                'duration': it.get('duration', 0), 'speech': it.get('speech')}

    def selected(self):
        unchecked = set(self.local().get('unchecked') or [])
        return [f for f in self.files if f['rel'] not in unchecked]

    def compute_outputs(self):
        p = self.project() or {}
        groups = {}
        for f in self.files:
            base = f['rel'][: len(f['rel']) - len(Path(f['rel']).suffix)]
            groups.setdefault(base.lower(), []).append((f, base))
        self.out_map = {}
        for lst in groups.values():
            for f, base in lst:
                name = f"{base}_{ext_of(f['rel'])}" if len(lst) > 1 else base
                self.out_map[f['rel']] = f"{name}.{p.get('targetExt', 'out')}"

    def src_path(self, rel):
        return self.root / rel

    def out_path(self, rel):
        if self.out_map is None:
            self.compute_outputs()
        return self.out_dir / (self.out_map.get(rel) or rel)

    def speech_file(self, rel):
        p = self.project() or {}
        return self.work_dir / ('ocr' if p.get('type') == 'image' else 'speech') / f'{sha(rel)}.json'

    # --- çalıştırma -------------------------------------------------------------------------------------------
    def speech_wanted(self):
        p = self.project()
        if p and p.get('type') == 'image':
            return bool((p.get('ocr') or {}).get('enabled'))
        return bool(p and (p.get('speech') or {}).get('enabled') and p.get('type') in ('video', 'audio'))

    def start(self, rels=None, force=False):
        if not self.root:
            return
        with self.lock:
            lst = [f for f in self.files if f['rel'] in rels] if rels else self.selected()
            for f in lst:
                rel = f['rel']
                it = self.item(rel)
                if rel in self.active or rel in self.queue:
                    continue
                if it['status'] == 'done' and not force:
                    if self.speech_wanted() and (not it.get('speech') or it['speech'].get('status') in ('error', 'canceled')):
                        self.queue_speech(rel)
                    continue
                it.update({'status': 'queued', 'progress': 0, 'error': ''})
                self.queue.append(rel)
                self.touch(rel)
            self.running = bool(self.queue or self.active or self.speech_queue or self.speech_active)
        self.emit_state()
        self.pump()

    def stop(self):
        with self.lock:
            for rel in self.queue:
                self.item(rel).update({'status': 'pending', 'progress': 0})
                self.touch(rel)
            for rel in self.speech_queue:
                it = self.item(rel)
                if it.get('speech'):
                    it['speech'] = {'status': 'canceled', 'progress': 0}
                self.touch(rel)
            self.queue, self.speech_queue = [], []
            for c in list(self.active.values()) + list(self.speech_active.values()):
                c.set()
            self.running = False
        self.save()
        self.emit_state()

    def on_selection_changed(self):
        unchecked = set(self.local().get('unchecked') or [])
        with self.lock:
            keep = []
            for rel in self.queue:
                if rel in unchecked:
                    self.item(rel).update({'status': 'pending', 'progress': 0})
                    self.touch(rel)
                else:
                    keep.append(rel)
            self.queue = keep
            self.speech_queue = [r for r in self.speech_queue if r not in unchecked]
        self.save()
        self.emit_state()

    def concurrency(self):
        p = self.project()
        return max(1, min(MAX_CONCURRENCY, int((p or {}).get('concurrency') or 2)))

    def pump(self):
        if self.closed:
            return
        with self.lock:
            while len(self.active) < self.concurrency() and self.queue:
                rel = self.queue.pop(0)
                ev = threading.Event()
                self.active[rel] = ev
                threading.Thread(target=self.run_item, args=(rel, ev), daemon=True).start()
            while self.speech_queue:   # motor yok: sıradaki konuşma/OCR işleri hemen hatayla biter
                rel = self.speech_queue.pop(0)
                self.item(rel)['speech'] = {'status': 'error', 'progress': 0, 'error': ERR_TEXT['engine_missing']}
                self.touch(rel)
            busy = self.queue or self.active or self.speech_queue or self.speech_active
            if self.running and not busy:
                self.running = False
                self.save()
                self.send('job:finished', self.summary())
        self.emit_state()

    def run_item(self, rel, cancel):
        p = self.project()
        f = next((x for x in self.files if x['rel'] == rel), None)
        it = self.item(rel)
        if not p or not f:
            self.active.pop(rel, None)
            return self.pump()
        it.update({'status': 'converting', 'progress': 0, 'error': '', 'startedAt': mt.now_ms()})
        self.touch(rel)
        try:
            def prog(x):
                it['progress'] = x
                self.touch(rel)
            src, out = self.src_path(rel), self.out_path(rel)
            with (JOB_GATE(self.uid, src, out, cancel) if JOB_GATE else contextlib.nullcontext()):
                r = convert(src, out, p['type'], p['targetExt'], p.get('options'), on_progress=prog, cancel=cancel)
            it.update({'status': 'done', 'progress': 1, 'outSize': r['size'], 'srcSize': f['size'], 'srcMtime': f['mtime'], 'finishedAt': mt.now_ms(),
                       'out': self.out_map.get(rel)})
            it['took'] = it['finishedAt'] - it['startedAt']
            if self.speech_wanted() and (not it.get('speech') or it['speech'].get('status') not in ('done', 'none')):
                self.queue_speech(rel)
        except Exception as e:   # noqa: BLE001
            if getattr(e, 'code', None) == 'canceled':
                it.update({'status': 'pending', 'progress': 0})
            else:
                it.update({'status': 'error', 'progress': 0, 'error': err_text(e)})
        finally:
            self.active.pop(rel, None)
            self.touch(rel)
            self.save()
            self.pump()

    def queue_speech(self, rel):
        if rel in self.speech_queue or rel in self.speech_active:
            return
        self.item(rel)['speech'] = {'status': 'queued', 'progress': 0}
        self.speech_queue.append(rel)
        self.running = True
        self.touch(rel)

    def transcribe_only(self, rels):
        if not self.root:
            return
        for rel in rels:
            self.queue_speech(rel)
        self.emit_state()
        self.pump()

    def transcript(self, rel):
        try:
            return json.loads(self.speech_file(rel).read_text('utf-8'))
        except (OSError, ValueError):
            return None

    # --- temizlik --------------------------------------------------------------------------------------------
    def delete_outputs(self, rels=None, transcripts=False):
        if not rels:
            self.stop()
        for rel in rels or list(self.state['items']):
            if rel in self.active:
                continue
            it = self.state['items'].get(rel)
            if not it:
                continue
            mt.rm(self.out_path(rel))
            it.update({'status': 'pending', 'progress': 0, 'outSize': 0, 'error': ''})
            if transcripts:
                it.pop('speech', None)
                mt.rm(self.speech_file(rel))
            self.touch(rel)
        if not rels:
            mt.rm(self.out_dir)
            if transcripts:
                mt.rm(self.work_dir / 'speech')
                mt.rm(self.work_dir / 'ocr')
        self.save()
        self.emit_state()

    def is_busy(self):
        return bool(self.active or self.speech_active or self.queue or self.speech_queue)

    def close(self):
        self.stop()
        self.closed = True
        self.save()


RUNNERS: dict[tuple, ProjectRunner] = {}


def get_runner(uid, pid, create=True):
    key = (uid, pid)
    r = RUNNERS.get(key)
    if not r and create:
        r = RUNNERS[key] = ProjectRunner(uid, pid)
    if r:
        r.last = time.time()
    return r


def project_stats(uid, s=None):
    s = s or load_store(uid)
    out = {}
    for p in s['projects']:
        r = RUNNERS.get((uid, p['id']))
        st = r.state if r else None
        if st is None:
            try:
                st = json.loads((mt.app_dir(APP, uid, 'work', p['id']) / 'state.json').read_text('utf-8'))
            except (OSError, ValueError):
                st = None
        items = list((st or {}).get('items', {}).values())
        out[p['id']] = {'done': sum(1 for x in items if x.get('status') == 'done'), 'error': sum(1 for x in items if x.get('status') == 'error'),
                        'running': bool(r and r.is_busy())}
    return out


# --- Önizleme (cvm://media → /media/<anahtar>/<ad>) --------------------------------------------------------------
MEDIA = {}   # anahtar -> (uid, Path)


def media_url(uid, abs_path: Path):
    key = hashlib.sha1(f'{uid}|{abs_path}'.encode('utf-8')).hexdigest()
    MEDIA[key] = (uid, abs_path)
    try:
        v = int(abs_path.stat().st_mtime * 1000)
    except OSError:
        v = 0
    from urllib.parse import quote
    return f'/api/tools/convert/media/{key}/{quote(abs_path.name)}?v={v}'


def cache_dir(uid):
    return mt.app_dir(APP, uid, 'cache', 'preview')


def cache_key(abs_path: Path):
    st = abs_path.stat()
    return hashlib.sha1(f'{abs_path}|{st.st_size}|{st.st_mtime}'.encode('utf-8')).hexdigest()[:20]


def preview_for(uid, abs_path: Path, kind):
    ext = ext_of(abs_path)
    info = media_info(abs_path)
    key = cache_key(abs_path)
    T = TYPES
    k = 'audio' if kind == 'video' and ext in T['video']['audioOnlyTargets'] else 'image' if kind == 'video' and ext == 'gif' else kind
    out = {'kind': k, 'info': info, 'name': abs_path.name, 'path': str(abs_path.relative_to(mt.TOOLS_DIR))}
    if k == 'image':
        if ext in T['image']['play']:
            out['url'] = media_url(uid, abs_path)
        else:
            png = cache_dir(uid) / f'{key}.png'
            if not png.exists():
                image_convert(abs_path, png, 'png', {'quality': 100})
            out['url'] = media_url(uid, png)
        return out
    if k == 'audio':
        if FFMPEG:
            wave = cache_dir(uid) / f'{key}.wave.png'
            try:
                if not wave.exists():
                    run_ffmpeg(['-i', str(abs_path), '-filter_complex', 'showwavespic=s=1200x160:colors=22d3ee', '-frames:v', '1', str(wave)])
                out['waveform'] = media_url(uid, wave)
            except ConvertError:
                pass
        if ext in T['audio']['play']:
            out['url'] = media_url(uid, abs_path)
        elif FFMPEG:
            mp3 = cache_dir(uid) / f'{key}.mp3'
            if not mp3.exists():
                run_ffmpeg(['-i', str(abs_path), '-vn', '-c:a', 'libmp3lame', '-b:a', '128k', str(mp3)], duration=info['duration'])
            out['url'] = media_url(uid, mp3)
        return out
    if FFMPEG:
        poster = cache_dir(uid) / f'{key}.jpg'
        try:
            if not poster.exists():
                run_ffmpeg(['-ss', str(min(3, info['duration'] / 2 if info['duration'] else 0)), '-i', str(abs_path), '-frames:v', '1', '-vf', 'scale=640:-2', str(poster)])
            out['poster'] = media_url(uid, poster)
        except ConvertError:
            pass
    proxy = cache_dir(uid) / f'{key}.mp4'
    if proxy.exists():
        out['url'], out['proxy'] = media_url(uid, proxy), True
    elif ext in T['video']['play']:
        out['url'] = media_url(uid, abs_path)
    else:
        out['needProxy'] = True
    return out


# --- HTTP ------------------------------------------------------------------------------------------------------
class Body(BaseModel):
    model_config = {'extra': 'allow'}


def _b(body: Body) -> dict:
    return body.model_dump()


def _with_store(uid, s, **extra):
    return {'store': public_store(s), 'stats': project_stats(uid, s), **extra}


def wrap(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as err:   # noqa: BLE001
        raise HTTPException(400, err_text(err)) from None


@router.get('/caps')
def caps(user=Depends(tools_user)):
    """Sunucudaki motorlar: resim (Pillow), video/ses (ffmpeg), konuşma (whisper) ve OCR (tesseract) yok."""
    return {'image': Image is not None, 'video': bool(FFMPEG), 'audio': bool(FFMPEG), 'speech': False, 'ocr': False, 'ffmpeg': FFMPEG or None}


@router.get('/store')
def get_store(user=Depends(tools_user)):
    return public_store(load_store(user['id']))


@router.get('/projects/stats')
def stats(user=Depends(tools_user)):
    return project_stats(user['id'])


@router.post('/settings')
def set_settings(body: Body, user=Depends(tools_user)):
    uid = user['id']
    patch = _b(body).get('patch') or {}
    s = load_store(uid)
    if 'language' in patch:
        patch['language'] = _one(patch['language'], LANGS, None)
    if 'appTheme' in patch:
        patch['appTheme'] = _one(patch['appTheme'], ['dark', 'light', 'system'], 'system')
    if 'ocrLanguages' in patch:
        patch['ocrLanguages'] = [x for x in (patch['ocrLanguages'] or []) if x in OCR_LANGS] or ['tur', 'eng']
    s['settings'].update(patch)
    save_store(uid, s)
    return _with_store(uid, s)


@router.post('/project/save')
def project_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    form = _b(body).get('form') or {}
    s = load_store(uid)
    p = next((x for x in s['projects'] if x['id'] == form.get('id')), None) if form.get('id') else None
    is_new = p is None
    if is_new:
        p = {'id': mt.uid8(), 'createdAt': mt.now_ms()}
        s['projects'].append(p)
    type_ = _one(form.get('type'), list(TYPES), 'video')
    T = TYPES[type_]
    source_exts = list(dict.fromkeys(x for x in (form.get('sourceExts') or []) if x in T['source']))
    prev_target = p.get('targetExt')
    sp, oc = form.get('speech') or {}, form.get('ocr') or {}
    ocr_langs = [x for x in (oc.get('languages') or []) if x in OCR_LANGS]
    p.update({
        'name': str(form.get('name') or '').strip()[:120] or 'Adsız proje',
        'type': type_,
        'sourceExts': source_exts or list(T['defaultSource']),
        'targetExt': _one(form.get('targetExt'), T['target'], T['defaultTarget']),
        'sourceMode': 'file' if form.get('sourceMode') == 'file' else 'folder',
        'includeSubfolders': form.get('includeSubfolders') is not False,
        'concurrency': _num(form.get('concurrency'), s['settings'].get('defaultConcurrency') or 2, 1, 32),
        'speech': {'enabled': type_ in ('video', 'audio') and bool(sp.get('enabled')), 'model': _one(sp.get('model'), list(SPEECH_MODELS), s['settings'].get('speechModel') or 'base'),
                   'language': _one(sp.get('language'), SPEECH_LANGS, 'auto'), 'perWindow': bool(sp.get('perWindow'))},
        'ocr': {'enabled': type_ == 'image' and bool(oc.get('enabled')), 'languages': list(dict.fromkeys(ocr_langs))[:6] or (s['settings'].get('ocrLanguages') or ['tur', 'eng'])},
        'options': clean_options(form.get('options')),
        'folderId': form.get('folderId') if 'folderId' in form else p.get('folderId'),
        'color': form.get('color') or p.get('color') or T['color'],
        'notes': str(form.get('notes') or '')[:2000],
    })
    if isinstance(form.get('sourcePath'), str):
        loc = get_local(s, p['id'])
        sp_norm = mt.norm_rel(form['sourcePath']) if form['sourcePath'] else ''
        if loc.get('sourcePath') != sp_norm:
            loc['sourcePath'] = sp_norm
            loc['unchecked'] = []
    save_store(uid, s)
    r = RUNNERS.get((uid, p['id']))
    if r:
        if not is_new and prev_target != p['targetExt']:
            r.compute_outputs()
        r.send('project:changed', project_for(s, p['id']))
        r.pump()
    return _with_store(uid, s, id=p['id'])


@router.post('/project/delete')
def project_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    pid = _b(body).get('id')
    s = load_store(uid)
    r = RUNNERS.pop((uid, pid), None)
    if r:
        r.close()
    s['projects'] = [p for p in s['projects'] if p['id'] != pid]
    s['local'].pop(pid, None)
    save_store(uid, s)
    mt.rm(mt.app_dir(APP, uid, 'converted') / str(pid))
    mt.rm(mt.app_dir(APP, uid, 'work') / str(pid))
    return _with_store(uid, s)


@router.post('/project/duplicate')
def project_duplicate(body: Body, user=Depends(tools_user)):
    uid = user['id']
    pid = _b(body).get('id')
    s = load_store(uid)
    p = next((x for x in s['projects'] if x['id'] == pid), None)
    if p:
        copy = {**json.loads(json.dumps(p)), 'id': mt.uid8(), 'name': p['name'] + ' (kopya)', 'createdAt': mt.now_ms()}
        s['projects'].append(copy)
        loc = get_local(s, pid)
        s['local'][copy['id']] = {'sourcePath': loc.get('sourcePath') or '', 'unchecked': list(loc.get('unchecked') or [])}
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/project/move')
def project_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    p = next((x for x in s['projects'] if x['id'] == b.get('id')), None)
    if p:
        p['folderId'] = b.get('folderId') or None
        save_store(uid, s)
    return _with_store(uid, s)


@router.post('/project/clearOutputs')
def project_clear(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    r = get_runner(uid, b.get('id'))
    r.delete_outputs(None, bool(b.get('transcripts')))
    return _with_store(uid, load_store(uid))


@router.post('/folder/save')
def folder_save(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None) if b.get('id') else None
    if not f:
        f = {'id': mt.uid8(), 'parentId': b.get('parentId') or None}
        s['folders'].append(f)
    f['name'] = str(b.get('name') or '').strip()[:200]
    save_store(uid, s)
    return _with_store(uid, s, id=f['id'])


@router.post('/folder/move')
def folder_move(body: Body, user=Depends(tools_user)):
    uid = user['id']
    b = _b(body)
    s = load_store(uid)
    p = b.get('parentId')
    while p:
        if p == b.get('id'):
            return _with_store(uid, s, ok=False)
        p = next((x for x in s['folders'] if x['id'] == p), {}).get('parentId')
    f = next((x for x in s['folders'] if x['id'] == b.get('id')), None)
    if f:
        f['parentId'] = b.get('parentId') or None
    save_store(uid, s)
    return _with_store(uid, s, ok=True)


@router.post('/folder/delete')
def folder_delete(body: Body, user=Depends(tools_user)):
    uid = user['id']
    fid = _b(body).get('id')
    s = load_store(uid)
    f = next((x for x in s['folders'] if x['id'] == fid), None)
    if f:
        for p in s['projects']:
            if p.get('folderId') == fid:
                p['folderId'] = f.get('parentId') or None
        for sub in s['folders']:
            if sub.get('parentId') == fid:
                sub['parentId'] = f.get('parentId') or None
        s['folders'] = [x for x in s['folders'] if x['id'] != fid]
        save_store(uid, s)
    return _with_store(uid, s)


# --- proje penceresi -----------------------------------------------------------------------------------------
def _runner(body, user):
    pid = _b(body).get('id')
    s = load_store(user['id'])
    if not pid or not any(p['id'] == pid for p in s['projects']):
        raise HTTPException(404, 'Proje bulunamadı')
    return get_runner(user['id'], pid), s


@router.post('/pj/init')
def pj_init(body: Body, user=Depends(tools_user)):
    r, s = _runner(body, user)
    return wrap(lambda: {'project': project_for(s, r.id), 'snapshot': r.scan()})


@router.post('/pj/scan')
def pj_scan(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    return wrap(r.scan)


@router.post('/pj/check')
def pj_check(body: Body, user=Depends(tools_user)):
    r, s = _runner(body, user)
    b = _b(body)
    loc = get_local(s, r.id)
    st = set(loc.get('unchecked') or [])
    for rel in b.get('rels') or []:
        (st.discard if b.get('checked') else st.add)(rel)
    loc['unchecked'] = sorted(st)
    save_store(user['id'], s)
    r.on_selection_changed()
    return {'ok': True}


@router.post('/pj/start')
def pj_start(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    o = _b(body).get('opts') or {}
    wrap(lambda: r.start(o.get('rels'), bool(o.get('force'))))
    return {'ok': True}


@router.post('/pj/stop')
def pj_stop(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    r.stop()
    return {'ok': True}


@router.post('/pj/transcribe')
def pj_transcribe(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    r.transcribe_only(_b(body).get('rels') or [])
    return {'ok': True}


@router.post('/pj/transcript')
def pj_transcript(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    return r.transcript(_b(body).get('rel') or '')


@router.post('/pj/deleteOutputs')
def pj_delete_outputs(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    o = _b(body).get('opts') or {}
    wrap(lambda: r.delete_outputs(o.get('rels'), bool(o.get('transcripts'))))
    return {'ok': True}


@router.post('/pj/setConcurrency')
def pj_set_concurrency(body: Body, user=Depends(tools_user)):
    r, s = _runner(body, user)
    p = next(x for x in s['projects'] if x['id'] == r.id)
    p['concurrency'] = _num(_b(body).get('n'), p.get('concurrency', 2), 1, 32)
    save_store(user['id'], s)
    r.pump()
    return p['concurrency']


@router.post('/pj/changeSource')
def pj_change_source(body: Body, user=Depends(tools_user)):
    r, s = _runner(body, user)
    picked = mt.norm_rel(_b(body).get('sourcePath') or '')
    p = next(x for x in s['projects'] if x['id'] == r.id)
    if r.is_busy():
        r.stop()
    if p.get('sourceMode') == 'file':
        e = ext_of(picked)
        if e and e not in p['sourceExts']:
            p['sourceExts'] = [*p['sourceExts'], e]
    loc = get_local(s, r.id)
    loc['sourcePath'] = picked
    loc['unchecked'] = []
    save_store(user['id'], s)
    return wrap(lambda: {**_with_store(user['id'], s), 'project': project_for(s, r.id), 'snapshot': r.scan()})


def _abs(r, rel, which):
    if not r.root:
        raise HTTPException(404, 'Kaynak klasör seçilmemiş')
    p = r.out_path(rel) if which == 'out' else r.src_path(rel)
    root = r.out_dir if which == 'out' else r.root
    if root.resolve() not in p.resolve().parents:
        raise HTTPException(400, 'Geçersiz yol')
    return p


@router.post('/pj/preview')
def pj_preview(body: Body, user=Depends(tools_user)):
    r, s = _runner(body, user)
    b = _b(body)
    if not r.root:
        r.scan()
    p = next(x for x in s['projects'] if x['id'] == r.id)
    abs_path = _abs(r, b.get('rel') or '', b.get('which'))
    if not abs_path.exists():
        return None
    return wrap(lambda: preview_for(user['id'], abs_path, p['type']))


@router.post('/pj/proxy')
def pj_proxy(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    b = _b(body)
    if not r.root:
        r.scan()
    abs_path = _abs(r, b.get('rel') or '', b.get('which'))

    def make():
        info = probe(abs_path)
        out = cache_dir(user['id']) / f'{cache_key(abs_path)}.mp4'
        if not out.exists():
            def prog(x):
                r.send('preview:progress', {'rel': b.get('rel'), 'which': b.get('which'), 'progress': x})
            with (JOB_GATE(user['id'], abs_path, out, None) if JOB_GATE else contextlib.nullcontext()):
                run_ffmpeg(['-i', str(abs_path), '-vf', "scale=-2:'min(480,ih)'", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-c:a', 'aac', '-b:a', '96k',
                            '-movflags', '+faststart', str(out)], duration=info['duration'], on_progress=prog)
        return {'url': media_url(user['id'], out)}
    return wrap(make)


@router.get('/pj/file')
def pj_file(id: str, rel: str, which: str = 'src', user=Depends(tools_user)):   # noqa: A002
    r = get_runner(user['id'], id)
    if not r.root:
        r.scan()
    p = _abs(r, rel, which)
    if not p.is_file():
        raise HTTPException(404, 'Dosya bulunamadı')
    return FileResponse(p, filename=p.name)


@router.post('/pj/exportCount')
def pj_export_count(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    rels = _b(body).get('rels')
    lst = [x for x in (rels or list(r.state['items'])) if (r.state['items'].get(x) or {}).get('status') == 'done' and r.out_path(x).exists()]
    return {'count': len(lst)}


@router.get('/pj/exportOutputs')
def pj_export_outputs(id: str, rels: str = '', user=Depends(tools_user)):   # noqa: A002
    """Dönüştürülmüş dosyalar klasör yapısıyla ZIP olarak indirilir (masaüstünde klasöre kopyalanırdı)."""
    r = get_runner(user['id'], id)
    if not r.root:
        r.scan()
    wanted = [x for x in rels.split('\n') if x] or list(r.state['items'])
    lst = [x for x in wanted if (r.state['items'].get(x) or {}).get('status') == 'done' and r.out_path(x).exists()]
    if not lst:
        raise HTTPException(404, 'Dönüştürülmüş dosya yok')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for x in lst:
            z.write(r.out_path(x), r.out_path(x).relative_to(r.out_dir).as_posix())
    buf.seek(0)
    name = safe_name((r.project() or {}).get('name') or 'convert', 'convert') + '.zip'
    return StreamingResponse(buf, media_type='application/zip', headers={'Content-Disposition': _disposition(name)})


def _disposition(name):
    """İndirme başlığı: ASCII dışı adlar RFC 5987 ile (Türkçe karakterli proje adları)."""
    from urllib.parse import quote
    ascii_name = name.encode('ascii', 'ignore').decode() or 'dosya'
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def export_transcript(segments, fmt):
    def tm(sec, sep):
        h, m = divmod(int(sec), 3600)
        m, s = divmod(m, 60)
        return f'{h:02d}:{m:02d}:{s:02d}{sep}{int((sec % 1) * 1000):03d}'
    if fmt == 'srt':
        return '\n'.join(f"{i + 1}\n{tm(s['start'], ',')} --> {tm(s['end'], ',')}\n{s['text'].strip()}\n" for i, s in enumerate(segments))
    if fmt == 'vtt':
        return 'WEBVTT\n\n' + '\n'.join(f"{tm(s['start'], '.')} --> {tm(s['end'], '.')}\n{s['text'].strip()}\n" for s in segments)
    if fmt == 'json':
        return json.dumps(segments, ensure_ascii=False, indent=2)
    return '\n'.join(s['text'].strip() for s in segments)


@router.get('/pj/exportTranscript')
def pj_export_transcript(id: str, rel: str, format: str = 'txt', user=Depends(tools_user)):   # noqa: A002
    r = get_runner(user['id'], id)
    tr = r.transcript(rel)
    if not tr:
        raise HTTPException(404, 'Metin yok')
    fmt = _one(format, ['txt', 'srt', 'vtt', 'json'], 'txt')
    text = '\n'.join(x.get('text', '') for x in tr.get('lines', [])) if tr.get('kind') == 'ocr' else export_transcript(tr.get('segments') or [], fmt)
    name = f"{Path(rel).stem}.{fmt}"
    return StreamingResponse(io.BytesIO(text.encode('utf-8')), media_type='text/plain; charset=utf-8', headers={'Content-Disposition': _disposition(safe_name(name))})


@router.post('/pj/outSize')
def pj_out_size(body: Body, user=Depends(tools_user)):
    r, _ = _runner(body, user)
    return {'bytes': mt.dir_size(r.out_dir)}


@router.get('/pj/events')
def pj_events(id: str, since: int = 0, user=Depends(tools_user)):   # noqa: A002
    r = RUNNERS.get((user['id'], id))
    if not r:
        return {'seq': since, 'events': []}
    seq, events = r.events_since(since)
    return {'seq': seq, 'events': events}


@router.post('/pj/close')
def pj_close(body: Body, user=Depends(tools_user)):
    r = RUNNERS.pop((user['id'], _b(body).get('id')), None)
    if r:
        r.close()
    return {'ok': True}


# --- konuşma motoru / OCR / depolama (ayarlar) ----------------------------------------------------------------
@router.get('/speech/status')
def speech_status(user=Depends(tools_user)):
    return {'engine': False, 'canDownloadEngine': False, 'models': {k: {'installed': False, 'size': 0} for k in SPEECH_MODELS}, 'modelsDir': '', 'downloading': []}


@router.post('/speech/download')
def speech_download(body: Body, user=Depends(tools_user)):
    return {'ok': False, 'message': ERR_TEXT['engine_missing']}


@router.post('/speech/deleteModel')
def speech_delete(body: Body, user=Depends(tools_user)):
    return {'ok': True}


@router.get('/ocr/status')
def ocr_status(user=Depends(tools_user)):
    return {'langs': {k: {'installed': False, 'size': 0} for k in OCR_LANGS}, 'dir': '', 'downloading': []}


@router.post('/ocr/download')
def ocr_download(body: Body, user=Depends(tools_user)):
    return {'ok': False, 'message': 'OCR motoru (tesseract) bu sunucuda kurulu değil'}


@router.post('/ocr/delete')
def ocr_delete(body: Body, user=Depends(tools_user)):
    return {'ok': True}


@router.get('/storage/info')
def storage_info(user=Depends(tools_user)):
    uid = user['id']
    return {'converted': mt.dir_size(mt.app_dir(APP, uid, 'converted')), 'cache': mt.dir_size(cache_dir(uid)), 'models': 0, 'dir': f'{tc.BRAND} · tools/convertmaster/{uid}'}


@router.post('/storage/clearConverted')
def storage_clear_converted(body: Body, user=Depends(tools_user)):
    uid = user['id']
    s = load_store(uid)
    transcripts = bool(_b(body).get('transcripts'))
    for p in s['projects']:
        r = get_runner(uid, p['id'])
        r.delete_outputs(None, transcripts)
    mt.rm(mt.app_dir(APP, uid, 'converted'))
    return _with_store(uid, s)


@router.post('/storage/clearCache')
def storage_clear_cache(user=Depends(tools_user)):
    mt.rm(cache_dir(user['id']))
    MEDIA.clear()
    return {'ok': True}


@router.get('/media/{key}/{name}')
def media(key: str, name: str, user=Depends(tools_user)):
    m = MEDIA.get(key)
    if not m or m[0] != user['id'] or not m[1].is_file():
        raise HTTPException(404, 'Bulunamadı')
    return FileResponse(m[1], media_type=MIME.get(ext_of(m[1]), 'application/octet-stream'))
