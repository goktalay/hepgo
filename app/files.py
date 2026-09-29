import secrets
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from .auth import current_user

KINDS = {
    'users': {'.jpg', '.jpeg', '.png', '.webp', '.gif'},
    'errors': {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'},
    'reports': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.jpg', '.jpeg', '.png', '.zip'},
    'flightlogs': {'.bin', '.log'},
    'videos': {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi', '.3gp', '.ts'},
    'receipts': {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.pdf'},
    'logos': {'.jpg', '.jpeg', '.png', '.webp', '.svg', '.gif'},
    'cargo': {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'},
    'camfaces': {'.jpg'},
    # Mesajlaşma: resim, ses (bas-konuş), belge. Tarayıcıda çalışabilecek türler (html, svg, js) kabul edilmez.
    'chat': {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
             '.odt', '.ods', '.txt', '.csv', '.rtf', '.zip', '.rar', '.7z', '.mp4', '.mov', '.m4v', '.webm',
             '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.weba', '.stl', '.3mf', '.gcode', '.step', '.stp', '.dwg', '.dxf'},    # kamera yüz kırpıkları ve yüzün görüldüğü tam kareler (kamera servisi yazar)
    'documents': {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp', '.gif', '.heic', '.heif',
                  '.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi', '.3gp', '.ts',
                  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.txt', '.csv', '.rtf', '.zip',
                  '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac', '.wma', '.amr', '.3ga', '.weba', '.mka'},
}
DOCUMENT_MAX_BYTES = 4 * 1024 ** 3
# Dosya indirme ek kontrolü: tür → fonksiyon(kullanıcı, dosya adı) → bool (ör. evrak görünürlüğü)
FILE_GUARDS = {}
FLIGHT_LOG_MAX_BYTES = 2 * 1024 ** 3
MAX_BYTES = 25 * 1024 * 1024

router = APIRouter()


def is_remote(request: Request):
    """İstek internetten (Cloudflare tüneli üzerinden) mi geldi? Yerel ağdan doğrudan gelen istekte CF başlıkları olmaz."""
    return 'cf-ray' in request.headers or 'cf-connecting-ip' in request.headers


def local_only(request: Request):
    """Bağımlılık: büyük dosya yüklemeleri yalnızca yerel ağdan."""
    if is_remote(request):
        raise HTTPException(403, f'Video ve uçuş logu yalnızca yerel ağdan yüklenebilir: {config.LOCAL_URL}')


# ---------- Parça parça yükleme (büyük dosyalar) ----------
# Cloudflare tüneli tek istekte ~100 MB'tan büyük gövdeyi kabul etmez. Büyük dosyalar istemcide parçalara bölünür:
# POST /api/uploads ile başlatılır, PUT /api/uploads/<jeton>?offset= ile parçalar sırayla eklenir; dosyayı kullanan
# uç nokta (ör. uçuş logu) jetonu take_upload ile alır.
CHUNK_KINDS = {'flightlogs': FLIGHT_LOG_MAX_BYTES, 'documents': DOCUMENT_MAX_BYTES}
LOCAL_ONLY_EXT = KINDS['videos']   # video her türde yalnızca yerel ağdan
CHUNK_SIZE = 16 * 1024 * 1024
CHUNK_MAX = 64 * 1024 * 1024
_chunked = {}   # jeton → durum (sunucu yeniden başlarsa yarım yüklemeler baştan alınır)


class ChunkInit(BaseModel):
    kind: str
    file_name: str
    size: int


@router.post('/api/uploads')
def chunked_init(body: ChunkInit, request: Request, user=Depends(current_user)):
    limit = CHUNK_KINDS.get(body.kind)
    if not limit:
        raise HTTPException(400, 'Bu dosya türü parça parça yüklenemez')
    ext = Path(body.file_name).suffix.lower()
    if ext not in KINDS[body.kind]:
        raise HTTPException(400, f'Desteklenmeyen dosya türü: {ext or "?"}')
    if body.kind == 'flightlogs' or ext in LOCAL_ONLY_EXT:   # büyük log ve videolar yalnızca yerel ağdan
        local_only(request)
    if body.size <= 0:
        raise HTTPException(400, 'Dosya boş')
    if body.size > limit:
        raise HTTPException(400, f'Dosya {limit // 1024 ** 2} MB sınırını aşıyor')
    folder = config.UPLOAD_DIR / body.kind
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12) + ext
    (folder / (name + '.part')).touch()
    token = secrets.token_hex(16)
    _chunked[token] = {'kind': body.kind, 'user_id': user['id'], 'file_name': body.file_name[:200], 'size': body.size,
                       'received': 0, 'name': name}
    return {'upload_id': token, 'chunk_size': CHUNK_SIZE}


def _chunk_state(token, user):
    st = _chunked.get(token)
    if not st or st['user_id'] != user['id']:
        raise HTTPException(404, 'Yükleme bulunamadı; baştan başlatın')
    return st


@router.put('/api/uploads/{token}')
async def chunked_part(token: str, offset: int, request: Request, user=Depends(current_user)):
    st = _chunk_state(token, user)
    if offset != st['received']:
        raise HTTPException(409, f'Beklenen konum {st["received"]}')
    part = config.UPLOAD_DIR / st['kind'] / (st['name'] + '.part')
    written = 0
    with open(part, 'ab') as f:
        async for chunk in request.stream():
            written += len(chunk)
            if written > CHUNK_MAX or st['received'] + written > st['size']:
                raise HTTPException(400, 'Parça boyutu hatalı')
            f.write(chunk)
    st['received'] += written
    return {'received': st['received']}


@router.delete('/api/uploads/{token}')
def chunked_cancel(token: str, user=Depends(current_user)):
    """Yükleme iptal edildi: yarım dosya silinir."""
    st = _chunk_state(token, user)
    (config.UPLOAD_DIR / st['kind'] / (st['name'] + '.part')).unlink(missing_ok=True)
    _chunked.pop(token, None)
    return {'ok': True}


def take_upload(token, user, kind):
    """Tamamlanmış parça parça yüklemeyi kalıcı dosyaya çevirir: ('kind/ad', boyut, özgün ad)."""
    st = _chunk_state(token, user)
    if st['kind'] != kind:
        raise HTTPException(400, 'Yükleme türü uyuşmuyor')
    if st['received'] != st['size']:
        raise HTTPException(400, f'Yükleme eksik ({st["received"]}/{st["size"]} bayt)')
    folder = config.UPLOAD_DIR / kind
    (folder / (st['name'] + '.part')).rename(folder / st['name'])
    _chunked.pop(token, None)
    return f'{kind}/{st["name"]}', st['size'], st['file_name']


async def save_upload(kind, upload: UploadFile):
    """Yüklenen dosyayı data/uploads/<kind>/ altına rastgele adla kaydeder, 'kind/ad' döner."""
    ext = Path(upload.filename or '').suffix.lower()
    if ext not in KINDS[kind]:
        raise HTTPException(400, f'Desteklenmeyen dosya türü: {ext or "?"}')
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, 'Dosya 25 MB sınırını aşıyor')
    folder = config.UPLOAD_DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12) + ext
    (folder / name).write_bytes(data)
    return f'{kind}/{name}'


async def save_upload_stream(kind, upload: UploadFile, max_bytes):
    """Büyük dosyaları belleğe almadan parça parça diske yazar; (yol, boyut) döner."""
    ext = Path(upload.filename or '').suffix.lower()
    if ext not in KINDS[kind]:
        raise HTTPException(400, f'Desteklenmeyen dosya türü: {ext or "?"}')
    folder = config.UPLOAD_DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12) + ext
    path = folder / name
    size = 0
    try:
        with open(path, 'wb') as f:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(400, f'Dosya {max_bytes // 1024 ** 2} MB sınırını aşıyor')
                f.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, 'Dosya boş')
    return f'{kind}/{name}', size


# Küçük resim: ?w=<genişlik> ile istenen resim sunucuda bir kez küçültülür (WebP) ve data/cache/thumbs altında saklanır.
# Yüklenen dosyaların adı rastgele ve değişmez olduğundan tarayıcı da uzun süre önbelleğe alır.
THUMB_WIDTHS = (64, 128, 256, 512, 1024, 1600)
THUMB_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
FILE_CACHE = {'Cache-Control': 'private, max-age=2592000, immutable'}
_thumb_lock = threading.Lock()


def thumbnail(path: Path, kind: str, name: str, w: int):
    """Resmin w piksel genişliğe (en boy korunur, büyütülmez) küçültülmüş WebP kopyası; yapılamazsa None."""
    if path.suffix.lower() not in THUMB_EXT:
        return None
    out = config.DATA_DIR / 'cache' / 'thumbs' / kind / f'{name}.{w}.webp'
    if out.is_file() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    with _thumb_lock:   # aynı anda gelen istekler aynı dosyayı iki kez üretmesin
        if out.is_file() and out.stat().st_mtime >= path.stat().st_mtime:
            return out
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)   # telefonda çekilen resmin yönü
                if im.width <= w and path.stat().st_size < 300_000:
                    return None                   # zaten küçük: aslı gönderilir
                im.thumbnail((w, w * 4))
                im = im.convert('RGBA' if im.mode in ('RGBA', 'LA', 'P') else 'RGB')
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix('.tmp')
                im.save(tmp, 'WEBP', quality=82, method=4)
                tmp.replace(out)
            return out
        except Exception:
            return None


@router.get('/api/files/{kind}/{name}')
def get_file(kind: str, name: str, w: int = 0, user=Depends(current_user)):
    if kind not in KINDS or '/' in name or '..' in name:
        raise HTTPException(404)
    path = config.UPLOAD_DIR / kind / name
    if not path.is_file():
        raise HTTPException(404)
    guard = FILE_GUARDS.get(kind)
    if guard and not guard(user, name):
        raise HTTPException(404)   # yetkisiz: dosyanın varlığı da belli edilmez
    if w:
        size = next((x for x in THUMB_WIDTHS if x >= w), THUMB_WIDTHS[-1])
        thumb = thumbnail(path, kind, name, size)
        if thumb:
            return FileResponse(thumb, media_type='image/webp', headers=FILE_CACHE)
    return FileResponse(path, headers=FILE_CACHE)
