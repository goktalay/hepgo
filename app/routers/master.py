"""MASTER (sistem sahibi) modülü — "Veri & Yedek".

KVKK: Bu modül ARTIK kullanıcıların kişisel verilerini GÖSTERMEZ. Sistem sahibi (yalnızca config.MASTER_USERNAMES)
buradan şirketinin TÜM verisini tek pakette (ZIP) indirebilir ve otomatik yedekleri görüp indirebilir.
Veri yalnızca indirilir; bu modülden hiçbir veri değiştirilmez.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import auth, config

router = APIRouter(prefix='/api/master')

_BACKUP_NAME = re.compile(r'^caymaz-[\w.-]+\.db$')


def master_only(user=Depends(auth.current_user)):
    if not user.get('master'):
        raise HTTPException(403, 'Bu modül yalnızca sistem sahibine açıktır')
    return user


def _slug(s):
    return re.sub(r'[^a-z0-9-]+', '-', (s or 'firma').strip().lower()).strip('-') or 'firma'


def _dir_size(path: Path):
    total = 0
    if path.exists():
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


def _backup_list():
    nightly = config.DATA_DIR / 'backups' / 'nightly'
    manual_dir = config.DATA_DIR / 'backups'
    out = []
    for scope, d in (('nightly', nightly), ('manual', manual_dir)):
        if not d.exists():
            continue
        for p in sorted(d.glob('caymaz-*.db'), key=lambda x: x.stat().st_mtime, reverse=True):
            st = p.stat()
            out.append({'name': p.name, 'scope': scope, 'size': st.st_size,
                        'at': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(st.st_mtime))})
    return out


@router.get('/overview')
def overview(user=Depends(master_only)):
    """Kişisel veri İÇERMEZ: depolama boyutu, yedek durumu, firma/kurulum bilgisi."""
    db_size = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    uploads = _dir_size(config.UPLOAD_DIR)
    backups = _backup_list()
    nightly = [b for b in backups if b['scope'] == 'nightly']
    last = nightly[0] if nightly else None
    age_h = None
    if last:
        age_h = round((time.time() - time.mktime(time.strptime(last['at'], '%Y-%m-%dT%H:%M:%S'))) / 3600, 1)
    return {
        'company': config.COMPANY_NAME,
        'modules': config.MODULES,   # None = tümü
        'db_bytes': db_size,
        'uploads_bytes': uploads,
        'total_bytes': db_size + uploads,
        'backup_count': len(backups),
        'nightly_count': len(nightly),
        'last_backup': last,
        'last_backup_age_h': age_h,
        'backup_ok': age_h is not None and age_h < 30,
    }


@router.get('/backups')
def backups(user=Depends(master_only)):
    return _backup_list()


@router.get('/backups/download')
def backup_download(name: str, scope: str = 'nightly', user=Depends(master_only)):
    if not _BACKUP_NAME.match(name or ''):
        raise HTTPException(400, 'Geçersiz dosya adı')
    base = config.DATA_DIR / 'backups' / ('nightly' if scope == 'nightly' else '')
    path = (base / name).resolve()
    # yol kaçışını engelle: hedef backups klasörünün altında olmalı
    if not str(path).startswith(str((config.DATA_DIR / 'backups').resolve())) or not path.is_file():
        raise HTTPException(404, 'Yedek bulunamadı')
    return FileResponse(path, filename=name, media_type='application/octet-stream')


@router.get('/export')
def export_all(user=Depends(master_only)):
    """Şirketin tüm verisini tek ZIP'te indir: tutarlı DB kopyası + yüklenen dosyalar + anahtarlar."""
    tmpdir = Path(tempfile.mkdtemp(prefix='caymaz-export-'))
    snap = tmpdir / 'caymaz.db'
    # WAL ile tutarlı anlık kopya
    src = sqlite3.connect(f'file:{config.DB_PATH}?mode=ro', uri=True, timeout=30)
    try:
        src.execute("VACUUM INTO ?", (str(snap),))
    finally:
        src.close()

    out = tmpdir / f'{_slug(config.COMPANY_NAME)}-veri-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(snap, 'caymaz.db')
        if config.UPLOAD_DIR.exists():
            for p in config.UPLOAD_DIR.rglob('*'):
                if p.is_file():
                    z.write(p, f'uploads/{p.relative_to(config.UPLOAD_DIR)}')
        for key in ('signing.key', 'camera.key'):
            kp = config.DATA_DIR / key
            if kp.exists():
                z.write(kp, key)
        z.writestr('BILGI.txt',
                   f'{config.COMPANY_NAME} — tam veri yedeği\n'
                   f'Oluşturma: {time.strftime("%Y-%m-%d %H:%M:%S")}\n'
                   'İçerik: caymaz.db (veritabanı), uploads/ (yüklenen dosyalar), *.key (imza/kamera anahtarları).\n'
                   'Geri yükleme: bu dosyaları yeni kurulumun data/ klasörüne koyun.\n')
    # Gönderildikten sonra geçici kopya (veritabanı + anahtarlar) silinir; /tmp'de kalmaz
    return FileResponse(out, filename=out.name, media_type='application/zip',
                        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True))
