"""Demo şirketle ekran görüntüsü üreticisi: uygulamayı yerelde ayağa kaldırır, demo veri ekler,
Playwright ile ana modüllerin görüntüsünü çeker. (#15.2)"""
import os, tempfile, threading, time, socket, sys

sys.path.insert(0, '/home/mkaderoglu/caymazbuild')
DATA = tempfile.mkdtemp()
os.environ.update(
    CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
    CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12',
    CAYMAZ_ADMIN_FULL_NAME='Demo Yönetici', CAYMAZ_MASTER_USERNAME='demo@firma.com',
    CAYMAZ_COMPANY_NAME='DEMO Fabrika A.Ş.',
)

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

PORT = free_port()
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.path.join(os.path.dirname(__file__), 'shots')
os.makedirs(OUT, exist_ok=True)

import uvicorn
from app.main import app
from app import db

def serve():
    uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='error')

threading.Thread(target=serve, daemon=True).start()
# port hazır olana kadar bekle
for _ in range(80):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
time.sleep(1.5)

# --- Demo veri: duyurular + Şirketten Haberler akışı ---
import requests
s = requests.Session()
r = s.post(f'{BASE}/api/auth/login', json={'username': 'demo@firma.com', 'password': 'Demo-Sifre-12'})
print('login:', r.status_code)

def feed_event(kind, text):
    try:
        with db.connect() as conn:
            from app import feed
            feed.add_event(conn, kind, text); conn.commit()
    except Exception as e:
        print('feed err', e)

feed_event('HIRE', 'Ayşe Yılmaz üretim ekibine katıldı. Aramıza hoş geldin!')
feed_event('ORDER', 'Yeni sipariş: SP-0042 · CAYMAZ V2 · 3 adet')
feed_event('MEETING', 'Haftalık üretim toplantısı yarın 10:00’da.')
try:
    with db.connect() as conn:
        for t, lv in [('Yıl sonu üretim hedefleri açıklandı', 'BILGI'), ('Fabrika bakım duyurusu: Cumartesi elektrik kesintisi', 'UYARI')]:
            conn.execute("INSERT INTO announcements (title, body, level, created_by, created_at) VALUES (?,?,?,?,?)",
                         (t, 'Ayrıntılar için yönetime danışın.', lv, 1, db.now()))
        conn.commit()
except Exception as e:
    print('ann err', e)

# --- Playwright yakalama ---
from playwright.sync_api import sync_playwright

SCREENS = [
    ('dashboard', '#/', 'Kişisel Pano (Şirketten Haberler dâhil)'),
    ('orders', '#/orders', 'İş Emri Yönetimi'),
    ('production', '#/production', 'Üretim Yönetimi'),
    ('printers', '#/printers', 'Yazıcı Yönetimi'),
    ('reports', '#/reports', 'Raporlar'),
    ('documents', '#/documents', 'Evrak Yönetimi'),
    ('hr', '#/hr', 'İnsan Kaynakları'),
    ('field', '#/field', 'Saha Yönetimi'),
    ('companies', '#/companies', 'Firma Yönetimi (CRM)'),
    ('settings', '#/settings', 'Kişisel Ayarlar'),
]
results = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1360, 'height': 900}, device_scale_factor=1)
    pg = ctx.new_page()
    pg.goto(BASE, wait_until='networkidle', timeout=30000)
    # giriş
    try:
        pg.fill('input[type=email], input[autocomplete=username]', 'demo@firma.com')
        pg.fill('input[type=password]', 'Demo-Sifre-12')
        pg.click('button[type=submit]')
        pg.wait_for_timeout(2500)
    except Exception as e:
        print('login ui err', e)
    for key, hashv, label in SCREENS:
        try:
            pg.evaluate("h => location.hash = h", hashv)
            pg.wait_for_timeout(1800)
            path = os.path.join(OUT, f'{key}.png')
            pg.screenshot(path=path)
            results.append((key, label, path))
            print('OK', key)
        except Exception as e:
            print('shot err', key, e)
    b.close()

print('TOPLAM', len(results), 'görüntü →', OUT)
for k, l, pth in results:
    print(' -', k, pth)
