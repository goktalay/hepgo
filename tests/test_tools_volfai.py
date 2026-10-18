"""Araçlar › VOLFAI (HEPGO sürümü): yetki (403), profil PUT/GET aynı JSON (vf/profile şeması), doğrulama (nesne zorunlu, 64 KB),
şirket içi skor tablosu, oyun dosyaları static/mt/volfai altında ve Master Tool hesap çağrısı kalmadı.
Çalıştırma: CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_tools_volfai
"""
import os
import re
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / 'static' / 'mt' / 'volfai'

PROFILE = {
    'v': 1, 'coins': 120, 'hiScore': 48250,
    'upgrades': {'engine': 1, 'shield': 0, 'laser': 0, 'cells': 0, 'time': 0, 'magnet': 0, 'armor': 0, 'deflector': 0},
    'ship': 'monotros', 'ships': {'monotros': True},
    'levels': {'1': {'parkurs': {'1': {'honor': 22, 'best': 48250, 'special': False, 'percent': 91, 'difficulty': 'acemi'},
                                 '2': {'honor': 15, 'best': 30000, 'special': False, 'percent': 84, 'difficulty': 'acemi'}}}},
    'settings': {'muted': False, 'vibrate': True, 'field': 'normal', 'spriteScale': 1.3, 'difficulty': 'acemi'},
    'stats': {'parkursCleared': 2, 'coinsEarned': 120, 'bossKills': 0, 'deaths': 1},
    'updatedAt': 1760000000000,
}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def test_permissions(g):
    # Güvenlik rolü Araçlar modülüne yetkili değil → 403
    assert g.get('/api/tools/volfai/profile').status_code == 403
    assert g.put('/api/tools/volfai/profile', json={'profile': PROFILE}).status_code == 403
    assert g.get('/api/tools/volfai/leaderboard').status_code == 403


def test_profile(a, uid):
    # Boş: vf/profile şeması — {user:{id,name}, profile:None, updated_at:None}
    r = ok(a.get('/api/tools/volfai/profile'))
    assert r['user']['id'] == uid and r['user']['name'] and r['profile'] is None and r['updated_at'] is None
    # PUT → GET aynı JSON
    assert ok(a.put('/api/tools/volfai/profile', json={'profile': PROFILE})) == {'ok': True}
    r = ok(a.get('/api/tools/volfai/profile'))
    assert r['profile'] == PROFILE and r['updated_at']
    # Güncelleme üzerine yazar (tek kayıt)
    ok(a.put('/api/tools/volfai/profile', json={'profile': PROFILE | {'coins': 38}}))
    assert ok(a.get('/api/tools/volfai/profile'))['profile']['coins'] == 38
    # Doğrulama: nesne zorunlu; 64 KB sınırı
    assert a.put('/api/tools/volfai/profile', json={'profile': 'metin'}).status_code == 400
    assert a.put('/api/tools/volfai/profile', json=[1]).status_code == 400
    assert a.put('/api/tools/volfai/profile', json={'profile': {'big': 'x' * (64 * 1024)}}).status_code == 413
    assert ok(a.put('/api/tools/volfai/profile', json={'profile': {'big': 'x' * (60 * 1024)}}))['ok']
    ok(a.put('/api/tools/volfai/profile', json={'profile': PROFILE}))


def test_leaderboard(a, b, uid_a, uid_b):
    ok(b.put('/api/tools/volfai/profile', json={'profile': PROFILE | {'hiScore': 99000, 'levels': {}, 'stats': {'parkursCleared': 0}}}))
    lb = ok(a.get('/api/tools/volfai/leaderboard'))
    assert [x['user_id'] for x in lb] == [uid_b, uid_a]          # yüksek skor önce
    me = lb[1]
    assert me['hi_score'] == 48250 and me['honor'] == 37 and me['parkurs'] == 2 and me['coins'] == 120 and me['name']
    assert lb[0]['honor'] == 0 and lb[0]['hi_score'] == 99000
    # Her kullanıcı yalnız kendi profilini görür (b'nin GET'i kendi kaydı)
    assert ok(b.get('/api/tools/volfai/profile'))['profile']['hiScore'] == 99000


def test_static(a):
    # Oyun dosyaları HEPGO static altında, aynı kökende (iframe frame-ancestors 'self' ile izinli)
    for p in ('index.html', 'css/style.css', 'js/main.js', 'js/account.js', 'js/game.js', 'manifest.webmanifest', 'icons/icon.svg'):
        assert (GAME / p).is_file(), p
        r = a.get(f'/static/mt/volfai/{p}')
        assert r.status_code == 200, p
        assert "frame-ancestors 'self'" in r.headers.get('content-security-policy', ''), p
    html = (GAME / 'index.html').read_text('utf-8')
    assert '<script type="module" src="js/main.js">' in html and 'login-form' not in html and 'mastertool.download' not in html
    # Master Tool hesap çağrıları kalmadı; HEPGO uçları kullanılıyor
    js = ''.join((GAME / 'js' / f).read_text('utf-8') for f in os.listdir(GAME / 'js'))
    assert not re.search(r"/api/vf/|prelogin|computeAuthHash|x-sshm", js)
    assert '/api/tools/volfai/profile' in js and '/api/auth/me' in js and 'serviceWorker' not in js
    # Araçlar modülü: VOLFAI yükleyicisi aynı-origin iframe'e bakıyor
    loader = (ROOT / 'static' / 'js' / 'modules' / 'tool_volfai.js').read_text('utf-8')
    assert '/static/mt/volfai/index.html' in loader and 'mastertool.download' not in loader


def main():
    with TestClient(app) as a, TestClient(app) as g, TestClient(app) as b:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ok(a.post('/api/users', json={'username': 'guvenlik@test', 'full_name': 'Güvenlik', 'roles': ['Güvenlik'], 'password': 'Gizli-Parola-77'}))
        ok(g.post('/api/auth/login', json={'username': 'guvenlik@test', 'password': 'Gizli-Parola-77'}))
        assert 'tools' not in ok(g.get('/api/auth/me'))['modules']
        uid_a = ok(a.get('/api/auth/me'))['id']
        # Depo Yöneticisi Araçlar modülüne yetkili (auth.MODULE_ROLES['tools']) → ikinci oyuncu
        ok(a.post('/api/users', json={'username': 'oyuncu@test', 'full_name': 'Oyuncu İki', 'roles': ['Depo Yöneticisi'], 'password': 'Gizli-Parola-88'}))
        ok(b.post('/api/auth/login', json={'username': 'oyuncu@test', 'password': 'Gizli-Parola-88'}))
        me_b = ok(b.get('/api/auth/me'))
        assert 'tools' in me_b['modules'], me_b['modules']
        test_permissions(g)
        test_profile(a, uid_a)
        test_leaderboard(a, b, uid_a, me_b['id'])
        test_static(a)
    print('Araçlar › VOLFAI testleri geçti.')


if __name__ == '__main__':
    main()
