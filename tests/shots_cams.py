"""Kameralar / Yüz Tanıma / Rehber ekran görüntüleri (Playwright, headless shell) — fs-cams dalı doğrulaması.
Uygulamayı aynı süreçte (iş parçacığı) 8805 portunda açar, demo veri üretir, görüntüleri tests/shots/cams-*.png'ye yazar.
Arka plan süreci bırakmaz: betik bitince sunucu iş parçacığı da ölür (daemon).

Çalıştırma:
  export LD_LIBRARY_PATH=/home/gelistirici/build/chromelibs/root/usr/lib/x86_64-linux-gnu
  CAYMAZ_DATA_DIR=/tmp/flsim/cm-data ./.venv/bin/python -m tests.shots_cams
"""
import os
import shutil
import socket
import sys
import threading
import time
from io import BytesIO

DATA = os.environ.get('CAYMAZ_DATA_DIR') or '/tmp/flsim/cm-data'
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA, exist_ok=True)
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici',
                  CAYMAZ_MASTER_USERNAME='demo@firma.com', CAYMAZ_COMPANY_NAME='DEMO Fabrika A.Ş.',
                  CAYMAZ_NVR_HOST='192.0.2.10', CAYMAZ_NVR_USER='admin')   # Kameralar modülü arayüzde NVR bayrağıyla görünür (adres yalnız bayrak için; bağlanılmaz)
PORT = int(os.environ.get('SHOT_PORT') or 8805)
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.path.join(os.path.dirname(__file__), 'shots')
os.makedirs(OUT, exist_ok=True)

import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app import camera_service, config, db, faceenroll  # noqa: E402
from app.main import app  # noqa: E402

server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='error'))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(120):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close()
        break
    except OSError:
        time.sleep(0.25)
else:
    sys.exit('sunucu açılmadı')
time.sleep(1.0)

import requests  # noqa: E402

s = requests.Session()
assert s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'}).status_code == 200
s.post(f'{BASE}/api/kvkk/accept-terms', json={})   # girişteki zorunlu KVKK onayı (tarayıcı oturumu aynı kullanıcı)


def unit(seed, noise=0.0, base=None):
    rng = np.random.default_rng(seed)
    v = (base if base is not None else rng.normal(size=128)) + rng.normal(size=128) * noise
    return (v / np.linalg.norm(v)).astype(np.float32)


def face_img(seed, size=256):
    """Basit, renkli 'yüz' çizimi (gerçek fotoğraf yerine): ten rengi oval, gözler, ağız; arka plan kameraya göre."""
    rng = np.random.default_rng(seed)
    bg = tuple(int(x) for x in rng.integers(40, 120, 3))
    skin = (random_skin := [(232, 190, 150), (200, 150, 110), (240, 205, 170), (170, 120, 90)])[seed % len(random_skin)]
    im = Image.new('RGB', (size, size), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((size * .22, size * .12, size * .78, size * .88), fill=skin)
    d.ellipse((size * .36, size * .40, size * .44, size * .48), fill=(40, 30, 30))
    d.ellipse((size * .56, size * .40, size * .64, size * .48), fill=(40, 30, 30))
    d.arc((size * .38, size * .55, size * .62, size * .74), 10, 170, fill=(120, 50, 50), width=max(2, size // 40))
    hair = tuple(int(x) for x in rng.integers(20, 90, 3))
    d.chord((size * .22, size * .08, size * .78, size * .50), 180, 360, fill=hair)
    return im


def jpg_bytes(im, q=86):
    b = BytesIO()
    im.save(b, 'JPEG', quality=q)
    return b.getvalue()


# ---- Demo veri: kameralar (32) + canlı kareler
names = ['Ana Giriş', 'Otopark', 'Üretim Hattı 1', 'Üretim Hattı 2', 'Depo', 'Sevkiyat', 'Yemekhane', 'Koridor A', 'Koridor B',
         'Kalite', 'Montaj', 'Boyahane', 'Arka Kapı', 'Çatı', 'Laboratuvar', 'Ar-Ge', 'Ofis Girişi', 'Toplantı', 'Kazan Dairesi', 'Trafo',
         'Jeneratör', 'Atık Alanı', 'Yükleme Rampası', 'Güvenlik Kulübesi', 'Bahçe', 'Kantar', 'Hammadde', 'Kalıphane', 'Pres', 'CNC', 'Kaynak', 'Paketleme']
cam_ids = []
for i, n in enumerate(names):
    r = s.post(f'{BASE}/api/cameras', json={'name': n, 'stream_url': f'rtsp://10.0.0.{i + 10}/s1', 'username': 'admin', 'password': 'x', 'location': n})
    assert r.status_code == 200, r.text
    cam_ids.append(r.json()['id'])
live = config.DATA_DIR / 'cameras' / 'live'
live.mkdir(parents=True, exist_ok=True)
for i, cid in enumerate(cam_ids):
    rng = np.random.default_rng(100 + i)
    arr = np.zeros((720, 1280, 3), np.uint8)
    base = rng.integers(30, 110, 3)
    yy, xx = np.mgrid[0:720, 0:1280]
    for c in range(3):
        arr[..., c] = np.clip(base[c] + (xx / 1280) * 60 * ((c + i) % 3 == 0) + (yy / 720) * 50 * ((c + i) % 2 == 0), 0, 255)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 44), fill=(0, 0, 0))
    d.text((14, 12), f'{names[i]}  ·  CAM-{i + 1:02d}  ·  2026-10-18 09:4{i % 10}:12', fill=(230, 230, 230))
    for k in range(4):   # sahne: birkaç kutu/koli
        x0 = int(rng.integers(80, 1000)); y0 = int(rng.integers(120, 560))
        d.rectangle((x0, y0, x0 + int(rng.integers(80, 240)), y0 + int(rng.integers(60, 160))), outline=(200, 200, 200), width=3)
    im.save(live / f'{cid}.jpg', 'JPEG', quality=80)

# ---- Kişiler
people = [('ayse', 'Ayşe Yılmaz', 'Üretim Sorumlusu'), ('mehmet', 'Mehmet Demir', 'Pilot'), ('zeynep', 'Zeynep Kaya', 'Sekreter'), ('can', 'Can Öztürk', 'Pilot')]
uids = {}
for u, full, role in people:
    r = s.post(f'{BASE}/api/users', json={'username': u, 'full_name': full, 'roles': [role], 'password': 'sifre-1234'})
    assert r.status_code == 200, r.text
    uids[u] = r.json()['id']
rok = s.post(f'{BASE}/api/companies', json={'name': 'Roketsan'}).json()['id']
pid_hasan = s.post(f'{BASE}/api/companies/{rok}/people', json={'full_name': 'Hasan Çelik', 'title': 'Satın Alma Müdürü'}).json()['id']
pid_elif = s.post(f'{BASE}/api/companies/{rok}/people', json={'full_name': 'Elif Arslan', 'title': 'Proje Yöneticisi'}).json()['id']

# ---- Kamera görülmeleri (yapay izler) → gruplar → kişiye atama (son tanınan yüz)
ident = camera_service.Identities()
ident.reload()
frame = np.array(Image.open(live / f'{cam_ids[0]}.jpg'))[:, :, ::-1].copy()
seen = {}
for seed, (who, cam_i) in enumerate([('ayse', 0), ('mehmet', 1), ('hasan', 2), ('ayse', 5)], start=1):
    base = unit(hash(who) % 1000)
    crop = np.array(face_img(seed))[:, :, ::-1].copy()
    ident.last_store.clear()
    sid = camera_service._store_sighting(ident, cam_ids[cam_i], unit(seed, 0.12, base), crop, frame, 900.0 + seed, db.now())
    seen.setdefault(who, []).append(sid)
    time.sleep(0.05)
with db.connect() as c:
    gids = {}
    for who, sids in seen.items():
        gids[who] = c.execute('SELECT group_id FROM face_sightings WHERE id = ?', (sids[0],)).fetchone()[0]
for who, gid in gids.items():
    body = {'person_id': pid_hasan} if who == 'hasan' else {'user_id': uids[who]}
    r = s.post(f'{BASE}/api/faces/groups/{gid}/assign', json=body)
    assert r.status_code == 200, r.text

# ---- Eğitim fotoğrafları (Ayşe için 9 kırpık) — "Seç" kipi görüntüsü
with db.connect() as c:
    for k in range(9):
        faceenroll.enroll_precomputed(c, 'user', uids['ayse'], None, None, jpg_bytes(face_img(50 + k)), unit(300 + k).tobytes(), 1, source='manual')
    for k in range(3):
        faceenroll.enroll_precomputed(c, 'person', None, pid_hasan, None, jpg_bytes(face_img(80 + k)), unit(400 + k).tobytes(), 1, source='manual')
    c.commit()

print('demo veri hazır; görüntüler alınıyor…')

# ---- Playwright
from playwright.sync_api import sync_playwright  # noqa: E402

shots = []
with sync_playwright() as p:
    launch = {}
    if os.environ.get('CHROMIUM_PATH'):
        launch['executable_path'] = os.environ['CHROMIUM_PATH']
    b = p.chromium.launch(**launch)

    def session(theme):
        ctx = b.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=1, locale='tr-TR')
        ctx.add_init_script(f"try{{localStorage.setItem('caymaz.theme','{theme}');}}catch(e){{}}")
        ctx.request.post(f'{BASE}/api/auth/login', data={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'})
        pg = ctx.new_page()
        pg.goto(BASE + '/#/dashboard', wait_until='networkidle', timeout=40000)
        pg.wait_for_timeout(800)
        return ctx, pg

    def shot(pg, name, hashv, wait=1800, before=None):
        pg.evaluate("h => location.hash = h", hashv)
        pg.wait_for_timeout(wait)
        path = os.path.join(OUT, f'cams-{name}.png')
        try:
            if before:
                before(pg)
            pg.screenshot(path=path)
            shots.append(path)
            print('OK', name)
        except Exception as e:   # noqa: BLE001 — hata: yine de ekranı kaydet (debug) ve devam et
            pg.screenshot(path=path.replace('.png', '-HATA.png'))
            print('HATA', name, str(e).splitlines()[0][:160], '→', path.replace('.png', '-HATA.png'), 'hash=', pg.evaluate('location.hash'))

    for theme in ('light', 'dark'):
        ctx, pg = session(theme)
        # 1) 32'li ızgara
        def pick32(pg):
            pg.click(".cw-layouts button:has-text(\"32'lı\")", timeout=8000)
            pg.wait_for_timeout(2500)
        shot(pg, f'wall32-{theme}', '#/cameras', before=pick32)
        # 2) Yüz Tanıma › Eğitim: Ayşe seçili (son tanınan yüz avatarı başlıkta) → Seç kipi + 3 seçim
        def train(pg):
            pg.click('.fr-person:has-text("Ayşe Yılmaz")', timeout=8000)
            pg.wait_for_timeout(900)
        shot(pg, f'train-lastface-{theme}', '#/cameras/facerec/train', before=train)
        def select_mode(pg):
            pg.click('.fr-subject-h button:has-text("Seç")')
            pg.wait_for_timeout(400)
            for i in (0, 2, 5):
                pg.click(f'.fr-crop:nth-child({i + 1}) .fr-pick')
            pg.wait_for_timeout(300)
        shot(pg, f'train-select-{theme}', '#/cameras/facerec/train', wait=1200, before=lambda pg: (train(pg), select_mode(pg)))
        # 3) Son tanınan yüz büyük görünümü
        def lastview(pg):
            train(pg)
            pg.click('.fr-subject-h .fr-last')
            pg.wait_for_timeout(700)
        shot(pg, f'train-lastview-{theme}', '#/cameras/facerec/train', wait=1200, before=lastview)
        pg.keyboard.press('Escape')
        # 4) Rehber: fotoğrafı olmayan Ayşe/Mehmet/Hasan → yüz tanıma avatarı + rozet
        shot(pg, f'rehber-{theme}', '#/rehber', wait=2200)
        shot(pg, f'rehber-detail-{theme}', f'#/rehber/user/{uids["ayse"]}', wait=2200)
        ctx.close()
    b.close()

print('TOPLAM', len(shots), 'görüntü →', OUT)
for pth in shots:
    print(' -', pth)
server.should_exit = True
