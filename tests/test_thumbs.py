"""Küçük resim: /api/files/<tür>/<ad>?w= ile resim küçültülüp WebP olarak gönderilir ve önbelleğe alınır; küçük resimler
ve resim olmayan dosyalar aslıyla gelir; yetki kontrolü küçük resimde de geçerlidir.

Çalıştırma: .venv/bin/python -m tests.test_thumbs
"""
import io
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402


def main():
    with TestClient(app) as a:
        assert a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
        folder = config.UPLOAD_DIR / 'users'
        folder.mkdir(parents=True, exist_ok=True)
        Image.effect_noise((2400, 3000), 60).convert('RGB').save(folder / 'buyuk.png')
        Image.new('RGB', (60, 60), 'red').save(folder / 'kucuk.png')
        (folder / 'x.txt').write_text('x')
        big = (folder / 'buyuk.png').stat().st_size
        r = a.get('/api/files/users/buyuk.png?w=128')
        assert r.status_code == 200 and r.headers['content-type'] == 'image/webp' and 'max-age' in r.headers['cache-control']
        im = Image.open(io.BytesIO(r.content))
        assert im.width == 128 and im.height == 160 and len(r.content) < big / 20, (im.size, len(r.content), big)
        assert (config.DATA_DIR / 'cache' / 'thumbs' / 'users' / 'buyuk.png.128.webp').is_file()
        assert Image.open(io.BytesIO(a.get('/api/files/users/buyuk.png?w=300').content)).width == 512   # en yakın üst boyut
        assert a.get('/api/files/users/buyuk.png').headers['content-type'] == 'image/png'                # aslı
        assert a.get('/api/files/users/kucuk.png?w=512').headers['content-type'] == 'image/png'          # zaten küçük
        assert a.get('/api/files/users/yok.png?w=128').status_code == 404
    with TestClient(app) as anon:
        assert anon.get('/api/files/users/buyuk.png?w=128').status_code == 401
    print('Küçük resim testleri geçti.')


if __name__ == '__main__':
    main()
