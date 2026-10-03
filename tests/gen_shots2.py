"""Tanıtım sayfası (veilox.app) için yeni ekran görüntüleri — KURGUSAL demo şirketle (gerçek veri kullanılmaz).

Üretilenler (central/veilox_server/static/img/landing/shots/*.webp):
  dashboard (yeni akışlı pano), m-feed (Instagram tarzı akış), m-viewer (tam ekran + sağ şerit), m-live (canlı yayın),
  finance-cash, finance-statements, finance-trial, mascot3d.
Çalıştırma: .venv/bin/python tests/gen_shots2.py   (Playwright Chromium; canlı yayın için sahte kamera dosyası üretilir)
"""
import io
import json
import os
import random
import socket
import sys
import tempfile
import threading
import time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=DATA, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_ENV_FILE='/dev/null',
                  CAYMAZ_ADMIN_USERNAME='demo@firma.com', CAYMAZ_ADMIN_PASSWORD='Demo-Sifre-12', CAYMAZ_ADMIN_FULL_NAME='Selin Aydın',
                  CAYMAZ_MASTER_USERNAME='demo@firma.com', CAYMAZ_COMPANY_NAME='DEMO Fabrika A.Ş.', CAYMAZ_AI_API_KEY='sk-demo-yalnizca-gorsel')
from PIL import Image  # noqa: E402

OUT = os.path.join(ROOT, 'central/veilox_server/static/img/landing/shots')
ROOM = os.path.join(ROOT, 'central/veilox_server/static/img/landing/desk-printers3d.webp')
TMP = tempfile.mkdtemp()
PW = 'Demo-Sifre-12'
random.seed(7)


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


PORT = free_port()
BASE = f'http://127.0.0.1:{PORT}'
import uvicorn  # noqa: E402
from app.main import app  # noqa: E402
from app import auth, db  # noqa: E402

threading.Thread(target=lambda: uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='error'), daemon=True).start()
for _ in range(80):
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close(); break
    except OSError:
        time.sleep(0.25)
time.sleep(1.5)

# ---------------- Görseller: 3B yazıcı odası kareleri (paylaşım fotoğrafları + sahte kamera) ----------------
room = Image.open(ROOM).convert('RGB')
scene = room.crop((30, 620, 2130, 1290))   # 3B oda bölümü


def jpg(img, name):
    p = os.path.join(TMP, name); img.save(p, 'JPEG', quality=90); return p


photo1 = jpg(scene.crop((200, 0, 1550, 670)).resize((1350, 670)), 'oda1.jpg')
photo2 = jpg(scene.crop((600, 0, 1270, 670)).resize((1080, 1080)), 'oda2.jpg')
photo3 = jpg(scene.crop((0, 120, 900, 670)).resize((1080, 660)), 'oda3.jpg')
# sahte kamera: odada yavaş yatay kaydırma (YUV4MPEG2, 4:2:0)
Y4M = os.path.join(TMP, 'cam.y4m')
W, H, N = 960, 540, 60
with open(Y4M, 'wb') as f:
    f.write(f'YUV4MPEG2 W{W} H{H} F12:1 Ip A1:1 C420jpeg\n'.encode())
    sw = scene.width - 1200
    for i in range(N):
        x = int(sw * (0.5 - 0.5 * abs((i / N) * 2 - 1)))
        fr = scene.crop((x, 0, x + 1200, 670)).resize((W, H)).convert('YCbCr')
        y, cb, cr = fr.split()
        f.write(b'FRAME\n' + y.tobytes() + cb.resize((W // 2, H // 2)).tobytes() + cr.resize((W // 2, H // 2)).tobytes())

# ---------------- Kurgusal kullanıcılar ----------------
PEOPLE = [('zeynep@demo.com', 'Zeynep Kaya'), ('mehmet@demo.com', 'Mehmet Demir'), ('ayse@demo.com', 'Ayşe Yılmaz'), ('can@demo.com', 'Can Öztürk'),
          ('elif@demo.com', 'Elif Şahin'), ('burak@demo.com', 'Burak Arslan')]
with db.connect() as conn:
    for u, n in PEOPLE:
        i = conn.execute('INSERT INTO users (username, full_name, password_hash, active, created_at, must_change_password) VALUES (?,?,?,1,?,0)',
                         (u, n, auth.hash_password(PW), db.now())).lastrowid
        conn.execute('INSERT INTO user_roles (user_id, role) VALUES (?,?)', (i, auth.ADMIN_STAFF))
    conn.commit()

import httpx  # noqa: E402


def client(user):
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post('/api/auth/login', json={'username': user, 'password': PW})
    assert r.status_code == 200, r.text
    return c


admin = client('demo@firma.com')
cl = {u: client(u) for u, _ in PEOPLE}

# ---------------- Şirketten Haberler: paylaşımlar, tepkiler, yorumlar ----------------
from app import feed  # noqa: E402
with db.connect() as conn:
    feed.add_event(conn, 'HIRE', 'Elif Şahin kalite ekibine katıldı. Aramıza hoş geldin!')
    feed.add_event(conn, 'ORDER', 'Yeni sipariş: SP-0142 · Anadolu Savunma A.Ş. · 40 adet gövde seti')
    conn.commit()


def post(c, text, files=()):
    fs = [('files', (os.path.basename(p), open(p, 'rb'), 'image/jpeg')) for p in files]
    r = c.post('/api/feed', data={'text': text}, files=fs)
    assert r.status_code == 200, r.text
    return r.json()['id']


p0 = post(cl['ayse@demo.com'], 'Bu ay 1.240 parça teslim ettik — planın %112’si! Emeği geçen herkese teşekkürler 🎉')
p1 = post(cl['mehmet@demo.com'], 'Montaj hattında yeni fikstürler devrede; çevrim süresi 6 dakikadan 4’e indi ⏱️', [photo3])
p2 = post(cl['zeynep@demo.com'], 'Yazıcı odamız yeni raflarıyla hazır! 16 yazıcı aynı anda üretimde 💪 #üretim', [photo1, photo2])
for u, em in [('mehmet@demo.com', '❤️'), ('ayse@demo.com', '👏'), ('can@demo.com', '❤️'), ('elif@demo.com', '🎉'), ('burak@demo.com', '❤️'), ('demo@firma.com', '❤️')]:
    (admin if u == 'demo@firma.com' else cl[u]).post(f'/api/feed/{p2}/react', json={'emoji': em})
for u in ('zeynep@demo.com', 'can@demo.com', 'demo@firma.com'):
    (admin if u == 'demo@firma.com' else cl[u]).post(f'/api/feed/{p0}/react', json={'emoji': '🎉'})
c1 = cl['can@demo.com'].post(f'/api/feed/{p2}/comments', json={'text': 'Harika olmuş, kablolama da çok düzenli 👌'}).json()['id']
cl['zeynep@demo.com'].post(f'/api/feed/{p2}/comments', json={'text': 'Teşekkürler Can! Haftaya kalibrasyon istasyonu da geliyor.', 'parent_id': c1})
cl['elif@demo.com'].post(f'/api/feed/{p2}/comments', json={'text': 'Kalite tarafında ilk partiyi bugün onayladık ✅'})
cl['mehmet@demo.com'].post(f'/api/feed/comments/{c1}/like')
cl['ayse@demo.com'].post(f'/api/feed/{p1}/comments', json={'text': 'Süper iyileştirme 👏'})

# ---------------- Finans: kurgusal cariler, banka/kasa, hareketler, çek/senet, planlı kalemler, dengeli yevmiye ----------------
today = date.today()
CUST = ['Anadolu Savunma A.Ş.', 'Ege Otomotiv Ltd. Şti.', 'Marmara Elektronik A.Ş.', 'Kuzey Lojistik A.Ş.', 'Başkent Medikal Ltd.']
SUPP = ['Atlas Metal San.', 'Delta Plastik A.Ş.', 'Nova Kimya Ltd.', 'Orion Elektronik Komponent']
with db.connect() as conn:
    ids = {}
    for n in CUST + SUPP:
        ids[n] = conn.execute('INSERT INTO companies (name, active, created_at, is_supplier) VALUES (?,1,?,?)', (n, db.now(), 1 if n in SUPP else 0)).lastrowid

    def acc(kind, name, company=None, opening=0, iban=None, bank=None):
        return conn.execute('INSERT INTO fin_accounts (kind, name, company_id, opening, iban, bank, active, created_at) VALUES (?,?,?,?,?,?,1,?)',
                            (kind, name, company, opening, iban, bank, db.now())).lastrowid
    kasa = acc('kasa', 'Merkez Kasa', opening=48_500)
    banks = [acc('banka', 'Ziraat Bankası', opening=1_850_000, iban='TR000001000000000000000001', bank='Ziraat Bankası'),
             acc('banka', 'Garanti BBVA', opening=920_000, iban='TR000006200000000000000002', bank='Garanti BBVA'),
             acc('banka', 'İş Bankası', opening=410_000, iban='TR000006400000000000000003', bank='İş Bankası')]
    cari = {n: acc('cari', n, ids[n]) for n in CUST + SUPP}

    def tx(a, d, dirn, amt, desc, cat=None, due=None):
        conn.execute('INSERT INTO fin_txns (account_id, date, direction, amount, currency, category, description, due_date, created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                     (a, d.isoformat(), dirn, round(amt, 2), 'TRY', cat, desc, due.isoformat() if due else None, db.now()))
    for m in range(5, -1, -1):   # son 6 ay
        base = today.replace(day=1) - timedelta(days=30 * m)
        for n in CUST:
            amt = random.randint(180, 950) * 1000
            d = base + timedelta(days=random.randint(2, 20))
            tx(cari[n], d, 'in', amt, f'Satış faturası {n.split()[0]}', 'Fatura', d + timedelta(days=random.choice([30, 45, 60])))
            if m > 0 or random.random() < .4:   # tahsilat (eski aylar)
                b = random.choice(banks); pay = amt * random.uniform(.6, 1.0)
                tx(cari[n], d + timedelta(days=35), 'out', pay, 'Havale ile tahsilat', 'Gelen havale')
                tx(b, d + timedelta(days=35), 'in', pay, f'Tahsilat · {n}', 'Gelen havale')
        for n in SUPP:
            amt = random.randint(90, 420) * 1000
            d = base + timedelta(days=random.randint(3, 22))
            tx(cari[n], d, 'out', amt, f'Alış faturası {n.split()[0]}', 'Fatura', d + timedelta(days=random.choice([30, 60])))
            if m > 0:
                b = random.choice(banks); pay = amt * random.uniform(.7, 1.0)
                tx(cari[n], d + timedelta(days=40), 'in', pay, 'Havale ile ödeme', 'Giden havale')
                tx(b, d + timedelta(days=40), 'out', pay, f'Ödeme · {n}', 'Giden havale')
        for desc, amt in [('Personel maaşları', 1_180_000), ('Fabrika kirası', 85_000), ('Elektrik', 64_000), ('SGK primleri', 410_000)]:
            tx(banks[0], base + timedelta(days=5), 'out', amt * random.uniform(.95, 1.05), desc, 'Gider')
        tx(kasa, base + timedelta(days=9), 'out', random.randint(6, 18) * 1000, 'Kırtasiye ve mutfak', 'Gider')
    for k, dirn, num, bank, comp, amt, due, st in [
        ('cek', 'alinan', 'ZR-4471205', 'Ziraat Bankası', 'Anadolu Savunma A.Ş.', 650_000, 18, 'portfoy'),
        ('cek', 'alinan', 'GR-0193320', 'Garanti BBVA', 'Ege Otomotiv Ltd. Şti.', 240_000, 33, 'tahsilde'),
        ('cek', 'alinan', 'IS-7720018', 'İş Bankası', 'Marmara Elektronik A.Ş.', 180_000, 52, 'portfoy'),
        ('senet', 'verilen', 'S-2026-14', None, 'Atlas Metal San.', 320_000, 26, 'portfoy'),
        ('cek', 'verilen', 'ZR-0099812', 'Ziraat Bankası', 'Delta Plastik A.Ş.', 145_000, 40, 'portfoy')]:
        conn.execute('''INSERT INTO fin_instruments (kind, direction, number, bank, company_id, amount, due_date, status, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''', (k, dirn, num, bank, ids[comp], amt, (today + timedelta(days=due)).isoformat(), st, db.now(), db.now()))
    for d, dirn, amt, desc, cat in [(5, 'out', 85_000, 'Fabrika kirası', 'Kira'), (10, 'out', 142_000, 'Yatırım kredisi taksidi', 'Kredi'),
                                    (3, 'out', 1_180_000, 'Personel maaşları', 'Maaş'), (20, 'in', 95_000, 'Teşvik geri ödemesi', 'Teşvik')]:
        dd = today.replace(day=d) if today.day < d else (today.replace(day=1) + timedelta(days=32)).replace(day=d)
        conn.execute("INSERT INTO fin_plans (date, direction, amount, description, category, repeat, created_at) VALUES (?,?,?,?,?, 'monthly', ?)",
                     (dd.isoformat(), dirn, amt, desc, cat, db.now()))
    # Dengeli yevmiye (Tekdüzen hesap planı; kurgusal tutarlar)
    COA = {'1': 'DÖNEN VARLIKLAR', '10': 'HAZIR DEĞERLER', '100': 'KASA', '100.01': 'Merkez Kasa', '102': 'BANKALAR', '102.01': 'Ziraat Bankası',
           '102.02': 'Garanti BBVA', '102.03': 'İş Bankası', '12': 'TİCARİ ALACAKLAR', '120': 'ALICILAR', '101': 'ALINAN ÇEKLER', '101.01': 'Portföydeki çekler',
           '15': 'STOKLAR', '150': 'İLK MADDE VE MALZEME', '152': 'MAMULLER', '19': 'DİĞER DÖNEN VARLIKLAR', '191': 'İNDİRİLECEK KDV',
           '2': 'DURAN VARLIKLAR', '25': 'MADDİ DURAN VARLIKLAR', '253': 'TESİS, MAKİNE VE CİHAZLAR', '257': 'BİRİKMİŞ AMORTİSMANLAR (−)',
           '3': 'KISA VADELİ YABANCI KAYNAKLAR', '32': 'TİCARİ BORÇLAR', '320': 'SATICILAR', '33': 'DİĞER BORÇLAR', '335': 'PERSONELE BORÇLAR',
           '36': 'ÖDENECEK VERGİ VE DİĞER YÜKÜMLÜLÜKLER', '360': 'ÖDENECEK VERGİ VE FONLAR', '361': 'ÖDENECEK SOSYAL GÜVENLİK KESİNTİLERİ',
           '39': 'DİĞER KISA VADELİ YABANCI KAYNAKLAR', '391': 'HESAPLANAN KDV', '4': 'UZUN VADELİ YABANCI KAYNAKLAR', '40': 'MALİ BORÇLAR', '400': 'BANKA KREDİLERİ',
           '5': 'ÖZKAYNAKLAR', '50': 'ÖDENMİŞ SERMAYE', '500': 'SERMAYE', '57': 'GEÇMİŞ YILLAR KÂRLARI', '570': 'GEÇMİŞ YILLAR KÂRLARI',
           '6': 'GELİR TABLOSU HESAPLARI', '60': 'BRÜT SATIŞLAR', '600': 'YURT İÇİ SATIŞLAR', '601': 'YURT DIŞI SATIŞLAR', '61': 'SATIŞ İNDİRİMLERİ',
           '611': 'SATIŞ İSKONTOLARI', '62': 'SATIŞLARIN MALİYETİ', '620': 'SATILAN MAMULLER MALİYETİ', '63': 'FAALİYET GİDERLERİ',
           '631': 'PAZARLAMA SATIŞ VE DAĞITIM GİDERLERİ', '632': 'GENEL YÖNETİM GİDERLERİ', '66': 'FİNANSMAN GİDERLERİ', '660': 'KISA VADELİ BORÇLANMA GİDERLERİ',
           '64': 'DİĞER FAALİYETLERDEN OLAĞAN GELİR VE KÂRLAR', '642': 'FAİZ GELİRLERİ'}
    for i, n in enumerate(CUST, 1):
        COA[f'120.01.{i:03d}'] = n
    for i, n in enumerate(SUPP, 1):
        COA[f'320.01.{i:03d}'] = n
    for k, v in COA.items():
        conn.execute('INSERT INTO fin_coa (code, name, updated_at) VALUES (?,?,?)', (k, v, db.now()))
    seq = [0]

    def je(d, lines, desc):
        seq[0] += 1
        for k, (acc_code, deb, cre) in enumerate(lines):
            conn.execute('INSERT INTO fin_ledger (guid, date, journal_no, entry_no, kind, account, description, debit, credit) VALUES (?,?,?,?,0,?,?,?,?)',
                         (f'demo-{seq[0]}-{k}', d.isoformat(), seq[0], seq[0], acc_code, desc, round(deb, 2), round(cre, 2)))
    y0 = date(today.year, 1, 1)
    je(y0, [('100.01', 60_000, 0), ('102.01', 2_400_000, 0), ('102.02', 900_000, 0), ('253', 18_500_000, 0), ('152', 3_200_000, 0),
            ('257', 0, 4_100_000), ('400', 0, 6_000_000), ('500', 0, 10_000_000), ('570', 0, 4_960_000)], 'Açılış fişi')
    for mth in range(1, today.month + 1):
        d = date(today.year, mth, 15)
        for i, n in enumerate(CUST, 1):
            net = random.randint(380, 1100) * 1000
            je(d, [(f'120.01.{i:03d}', net * 1.2, 0), ('600', 0, net), ('391', 0, net * .2)], f'Satış faturası · {n}')
            je(d + timedelta(days=10), [(random.choice(['102.01', '102.02', '102.03']), net * 1.2 * .85, 0), (f'120.01.{i:03d}', 0, net * 1.2 * .85)], f'Tahsilat · {n}')
            je(d, [('620', net * .52, 0), ('152', 0, net * .52)], 'Satılan mamul maliyeti')
        if mth % 3 == 0:
            je(d, [('120.01.001', 1_440_000, 0), ('601', 0, 1_440_000)], 'İhracat faturası')
            je(d, [('611', 60_000, 0), ('120.01.002', 0, 72_000), ('391', 12_000, 0)], 'Satış iskontosu')
        for i, n in enumerate(SUPP, 1):
            net = random.randint(260, 700) * 1000
            je(d, [('150', net, 0), ('191', net * .2, 0), (f'320.01.{i:03d}', 0, net * 1.2)], f'Alış faturası · {n}')
            je(d + timedelta(days=20), [(f'320.01.{i:03d}', net * 1.2 * .9, 0), ('102.01', 0, net * 1.2 * .9)], f'Ödeme · {n}')
            je(d, [('152', net * .95, 0), ('150', 0, net * .95)], 'Üretime sevk')
        je(d + timedelta(days=13), [('632', 1_180_000, 0), ('335', 0, 1_180_000)], 'Personel maaş tahakkuku')
        je(d + timedelta(days=14), [('335', 1_180_000, 0), ('102.01', 0, 1_180_000)], 'Maaş ödemesi')
        je(d, [('632', 149_000, 0), ('631', 96_000, 0), ('102.02', 0, 245_000)], 'Kira, enerji, lojistik giderleri')
        je(d, [('660', 92_000, 0), ('400', 140_000, 0), ('102.01', 0, 232_000)], 'Kredi taksidi ve faizi')
        je(d, [('102.03', 21_000, 0), ('642', 0, 21_000)], 'Mevduat faizi')
        je(d, [('632', 120_000, 0), ('257', 0, 120_000)], 'Amortisman')
    conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('fin.settings', ?)", (json.dumps({'payday': 0, 'salaries': True}),))
    # 3D maskot + mobilde tam ekran akış (yalnızca görsel)
    conn.commit()
with db.connect() as conn:   # pano: duyurular + yaklaşan doğum günleri
    for t, lv, body in [('Yeni vardiya planı yayında', 'ONEMLI', 'Ekim vardiya çizelgesi İK panosunda.'), ('Cumartesi planlı bakım', 'BILGI', '08:00–12:00 arası kompresör bakımı.')]:
        conn.execute('INSERT INTO announcements (title, body, level, created_by, created_at) VALUES (?,?,?,?,?)', (t, body, lv, 1, db.now()))
    for k, (fn, ln) in enumerate([('Elif', 'Şahin'), ('Burak', 'Arslan'), ('Deniz', 'Koç')]):
        bd = (today + timedelta(days=2 + k * 3)).replace(year=1990 + k * 3)
        conn.execute("INSERT INTO employees (first_name, last_name, status, birth_date, created_at) VALUES (?,?,'AKTIF',?,?)", (fn, ln, bd.isoformat(), db.now()))
    conn.commit()
admin.put('/api/auth/prefs/settings', json={'mascot': 'kubbe', 'mascot3d': True, 'feedFullMobile': True})
print('demo verisi hazır')

# ---------------- Ekran görüntüleri ----------------
from playwright.sync_api import sync_playwright  # noqa: E402

shots = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', f'--use-file-for-fake-video-capture={Y4M}',
                                '--autoplay-policy=no-user-gesture-required', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])

    def page(user, mobile=False):
        ctx = b.new_context(viewport={'width': 390, 'height': 844} if mobile else {'width': 1360, 'height': 900}, device_scale_factor=2 if mobile else 1,
                            is_mobile=mobile, has_touch=mobile, permissions=['camera', 'microphone'])
        pg = ctx.new_page()
        pg.goto(f'{BASE}/app', wait_until='networkidle')
        pg.fill('input[type=email]', user); pg.fill('input[type=password]', PW); pg.click('button[type=submit]')
        pg.wait_for_timeout(2500)
        pg.evaluate("localStorage.setItem('caymaz.liveMime','video/mp4;codecs=vp9,opus')")
        return pg

    def snap(pg, name, full=False):
        path = os.path.join(TMP, f'{name}.png'); pg.screenshot(path=path, full_page=full); shots[name] = path; print('ok', name)

    D = page('demo@firma.com')
    D.evaluate("location.hash='#/messages'"); D.wait_for_timeout(800); D.evaluate("location.hash='#/'"); D.wait_for_timeout(3500)
    snap(D, 'dashboard')
    for sub in ('cash', 'statements', 'trial'):
        D.evaluate(f"location.hash='#/finance/{sub}'"); D.wait_for_timeout(3000)
        snap(D, f'finance-{sub}')
    D.evaluate("location.hash='#/settings/mascot'"); D.wait_for_timeout(4000)
    snap(D, 'mascot3d')
    M = page('zeynep@demo.com', mobile=True)
    M.evaluate("async()=>{await fetch('/api/auth/prefs/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({feedFullMobile:true, mascot:'pati', mascot3d:true})});}")
    M.reload(); M.wait_for_timeout(3500)
    M.locator('.feed-post', has_text='raflarıyla').first.scroll_into_view_if_needed(); M.wait_for_timeout(400)
    M.evaluate("()=>{const e=document.querySelector('.feed-post.has-media'); if(e) e.scrollIntoView({block:'start'}); window.scrollBy(0,-70)}"); M.wait_for_timeout(800)
    snap(M, 'm-feed')
    M.locator('.feed-post', has_text='raflarıyla').first.locator('.feed-media').first.click(); M.wait_for_timeout(1500)
    snap(M, 'm-viewer')
    M.keyboard.press('Escape'); M.wait_for_timeout(500)
    # canlı yayın: Mehmet yayında, Zeynep (telefon) izliyor, diğerleri yorum + kalp gönderiyor
    L = page('mehmet@demo.com', mobile=True)
    L.locator('.feed-livebtn').click(); L.wait_for_timeout(2500)
    L.locator('.lv-title-in').fill('Yazıcı odasından canlı: yeni raflar'); L.locator('.lv-go').click(); L.wait_for_timeout(5000)
    viewers = [page(u) for u in ('can@demo.com', 'elif@demo.com', 'ayse@demo.com')]
    lid = L.evaluate("async()=>{const r=await (await fetch('/api/live/active')).json(); return r[0].id}")
    for v in viewers:
        v.evaluate(f"location.hash='#/live/{lid}'"); v.wait_for_timeout(2000)
    M.evaluate(f"location.hash='#/live/{lid}'"); M.wait_for_timeout(5000)
    for v, txt in zip(viewers, ['Harika görünüyor! 👏', 'Kalibrasyon istasyonu nereye gelecek?', 'Ellerinize sağlık 💪']):
        v.locator('.lv-input').fill(txt); v.locator('.lv-input').press('Enter'); v.wait_for_timeout(700)
        for _ in range(4):
            v.locator('.lv-heartbtn').click(); v.wait_for_timeout(120)
    M.wait_for_timeout(900)
    M.evaluate("()=>document.querySelector('.lv-sound')?.setAttribute('hidden','')")
    snap(M, 'm-live')
    b.close()

os.makedirs(OUT, exist_ok=True)
for name, path in shots.items():
    im = Image.open(path).convert('RGB')
    if im.width > 1600:
        im = im.resize((im.width // 2 if name.startswith('m-') else im.width, im.height // 2 if name.startswith('m-') else im.height))
    im.save(os.path.join(OUT, f'{name}.webp'), 'WEBP', quality=86, method=5)
print('Kaydedildi →', OUT, sorted(shots))
