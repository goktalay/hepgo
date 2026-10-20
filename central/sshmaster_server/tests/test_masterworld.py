"""MASTERWORLD hesap servisi tarafı (docs/masterworld.md §2–§3, §6, §7): Excel içe aktarma (gerçek dosya; idempotent, korunan alanlar),
yönetici CRUD + doğrulama + has_key (api_key sızmaz), noktalar, iç uç (X-Masterworld-Secret), CORS (mw kökeni yalnız /api/mw/*, sv bozulmadı),
mw profil, /api/mw/web-releases, /api/mt/apps (group apps), /oyunlar/masterworld 307, simgeler, CLI yedeği.
Çalıştırma (central/sshmaster_server içinde): ../../.venv/bin/python -m tests.test_masterworld [xlsx yolu]"""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile

D = tempfile.mkdtemp()
os.environ.update(SSHM_DATA_DIR=D, SSHM_ENV_FILE=os.path.join(D, 'yok.env'), VEILOX_ENV_FILE=os.path.join(D, 'yok2.env'), SSHM_MAIL_TEST='1',
                  SSHM_CENTRAL_SECRET='merkez-gizli', SSHM_SECURE_COOKIE='0', SSHM_SALT_KEY='test-tuz', MT_PORTAL_LIVE='0',
                  SIMUMAV_MT_SHARED_SECRET='sv-gizli', MASTERWORLD_MT_SHARED_SECRET='mw-gizli', MASTERWORLD_RELEASE_KEY='mw-anahtar')
from fastapi.testclient import TestClient  # noqa: E402
from sshm import db, mw_catalog, settings  # noqa: E402
from sshm.main import _RATE, app  # noqa: E402

XLSX = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('MW_XLSX', '/home/gelistirici/mt-work/masterworld-ref/Cesium_Canli_Veri_Kaynaklari.xlsx')
ADMIN = {'X-Central-Secret': 'merkez-gizli'}
MTH = {'Host': 'mastertool.download'}
BUILTINS = {b['slug'] for b in mw_catalog.BUILTIN}


def auth_hash(pw, kdf):
    m = hashlib.pbkdf2_hmac('sha256', pw.encode(), base64.b64decode(kdf['salt']), kdf['iter'], 32)
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', m, pw.encode(), 1, 32)).decode()


def xlsx_bytes(rows, orange_license_rows=()):
    """Küçük sentetik xlsx (satır içi dizgi + doğrudan turuncu dolgu): okuyucunun dolgu rengini ve başlık eşlemesini sınar."""
    head = ['Kategori', 'Kaynak', 'Veri', 'Erişim / Endpoint', 'Protokol', 'Kimlik Doğrulama', 'Push / Pull', 'Ölçek / Güncelleme', 'Lisans / Ticari Kullanım', 'Not']
    def cell(ci, ri, v, s=0):
        col = 'ABCDEFGHIJ'[ci]
        return f'<c r="{col}{ri}" t="inlineStr"{f" s={chr(34)}{s}{chr(34)}" if s else ""}><is><t>{v}</t></is></c>'
    xml_rows = []
    for ri, r in enumerate([head] + rows, start=1):
        xml_rows.append(f'<row r="{ri}">' + ''.join(cell(ci, ri, v, 1 if (ci == 8 and ri in orange_license_rows) else 0) for ci, v in enumerate(r)) + '</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook {ns}><sheets><sheet name="Kaynaklar" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/styles.xml', f'<styleSheet {ns}><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFF4B183"/></patternFill></fill></fills>'
                   '<cellXfs count="2"><xf fillId="0"/><xf fillId="2"/></cellXfs></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def main():
    data = open(XLSX, 'rb').read()
    c = TestClient(app, base_url='https://testserver')
    db.init()
    # ---- birim: slug, bayraklar, turuncu
    assert mw_catalog.slugify('adsb.lol') == 'adsb-lol' and mw_catalog.slugify('Open Notify / Where the ISS at') == 'open-notify'
    assert mw_catalog.slugify('Kystverket (Norveç)') == 'kystverket' and mw_catalog.slugify('Çevre Şöğüt İzmir') == 'cevre-sogut-izmir'
    assert mw_catalog.flags_from_text('Yok (açık uçlar)', 'Kişisel, ticari olmayan; atıf zorunlu') == (0, 1, 1)
    assert mw_catalog.flags_from_text('Ücretsiz API anahtarı', 'CC BY-NC') == (1, 1, 1) and mw_catalog.flags_from_text('', 'Kamu malı') == (0, 0, 0)
    assert mw_catalog._is_orange('FFFCE4D6') and mw_catalog._is_orange('FFED7D31') and not mw_catalog._is_orange('FF1F3A5F') and not mw_catalog._is_orange('FFFFFFFF')

    # ---- yönetici uçları kimliksiz 403; içe aktarma (gerçek Excel)
    assert c.get('/api/sm/admin/mw/sources').status_code == 403
    assert c.post('/api/sm/admin/mw/import', files={'file': ('k.xlsx', data)}).status_code == 403
    assert c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('k.xlsx', b'not a zip')}).json()['code'] == 'not_xlsx'
    assert c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('k.xlsx', b'PK\x03\x04bozuk')}).json()['code'] == 'not_xlsx'
    r = c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('Kaynaklar.xlsx', data)})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res['added'] == 51 + len(BUILTINS) and res['updated'] == 0 and res['unchanged'] == 0 and res['skipped'] == [] and res['rows'] == 51, res
    assert any(p.name.startswith('sshm-pre-mw-') for p in settings.DATA_DIR.iterdir())   # içe aktarmadan önce yedek
    L = c.get('/api/sm/admin/mw/sources', headers=ADMIN).json()
    src = {s['slug']: s for s in L['sources']}
    assert len(src) == 51 + len(BUILTINS) and BUILTINS <= set(src) and {'adsb-lol', 'open-notify', 'usgs-earthquake', 'telegeography-submarine-cable-map'} <= set(src)
    assert all('api_key' not in s for s in L['sources']) and set(L['adapters']) >= {'adsb_lol', 'points', 'radio_browser', 'digitraffic_cam'}
    assert L['category_labels']['radio'] == 'Radyo' and 'radio' in L['categories'] and 'aircraft' in L['kinds']
    lol = src['adsb-lol']
    assert lol['category'] == 'air' and lol['kind'] == 'aircraft' and lol['adapter'] == 'adsb_lol' and lol['enabled'] == 1 and lol['default_on'] == 1 and lol['live']
    assert lol['attribution'] == '© adsb.lol contributors (ODbL)' and lol['attribution_required'] == 1 and lol['noncommercial'] == 0 and lol['origin'] == 'excel'
    assert src['opensky-network']['key_required'] == 1 and src['opensky-network']['enabled'] == 0 and src['opensky-network']['key_missing']
    assert src['adsb-fi']['noncommercial'] == 1 and src['airplanes-live']['noncommercial'] == 1   # turuncu + metin
    assert src['celestrak']['params'] == {'groups': ['stations', 'visual', 'gps-ops']} and src['usgs-earthquake']['params'] == {'feed': 'all_day'}
    assert src['usgs-earthquake']['default_on'] == 1 and src['open-notify']['kind'] == 'iss' and src['open-notify']['default_on'] == 1
    assert src['radio-browser']['category'] == 'radio' and src['radio-browser']['default_on'] == 1 and src['radio-browser']['origin'] == 'builtin' and src['radio-browser']['live']
    assert src['caltrans-cctv']['default_on'] == 1 and src['caltrans-cctv']['kind'] == 'camera'
    dt = src['digitraffic-cam']
    assert (dt['adapter'], dt['enabled'], dt['default_on'], dt['attribution_required'], dt['key_required'], dt['license']) == ('digitraffic_cam', 1, 1, 1, 0, 'CC BY 4.0')
    assert src['gcmb-io']['adapter'] is None and src['gcmb-io']['enabled'] == 0 and not src['gcmb-io']['live']   # katalog
    assert src['telegeography-submarine-cable-map']['kind'] == 'cable' and src['telegeography-submarine-cable-map']['noncommercial'] == 1
    assert sum(1 for s in src.values() if s['default_on']) == 6   # uçak, deprem, ISS, iki kamera, radyo
    st = L['stats']
    assert st['total'] == len(src) and st['enabled'] == sum(s['enabled'] for s in src.values()) and st['live'] == sum(s['live'] for s in src.values())
    assert st['key_missing'] == sum(1 for s in src.values() if s['adapter'] and s['key_required']) == 4, st   # opensky, aisstream, firms, windy

    # ---- ikinci içe aktarma: hiçbir şey eklenmez; elle değişen alanlar korunur
    r2 = c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('Kaynaklar.xlsx', data)}).json()
    assert r2['added'] == 0 and r2['updated'] == 0 and r2['unchanged'] == 51, r2
    osk = src['opensky-network']['id']
    r = c.put(f'/api/sm/admin/mw/sources/{osk}', headers=ADMIN, json={'api_key': 'gizli-anahtar-123', 'enabled': True, 'attribution': 'Elle atıf', 'sort': 7,
                                                                     'default_on': True, 'params': {'bbox': 'tr'}})
    assert r.status_code == 200 and r.json()['has_key'] is True and 'api_key' not in r.json() and r.json()['live'] and 'gizli-anahtar-123' not in r.text, r.text
    with db.connect() as conn:   # Excel bilgi sütununu bozup yeniden içe aktarınca düzelmeli
        conn.execute("UPDATE mw_sources SET license = 'bozuk', note = 'x' WHERE slug = 'adsb-lol'")
        conn.execute("UPDATE mw_sources SET enabled = 0 WHERE slug = 'adsb-lol'")
        conn.commit()
    r3 = c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('Kaynaklar.xlsx', data)}).json()
    assert r3['added'] == 0 and r3['updated'] == 1 and r3['unchanged'] == 50, r3
    L2 = {s['slug']: s for s in c.get('/api/sm/admin/mw/sources', headers=ADMIN).json()['sources']}
    o = L2['opensky-network']
    assert o['has_key'] and o['enabled'] == 1 and o['attribution'] == 'Elle atıf' and o['sort'] == 7 and o['default_on'] == 1 and o['params'] == {'bbox': 'tr'}
    assert L2['adsb-lol']['license'] == 'ODbL' and L2['adsb-lol']['note'] == 'Yıllık globe_history arşivi' and L2['adsb-lol']['enabled'] == 0   # enabled korunur
    c.put(f"/api/sm/admin/mw/sources/{L2['adsb-lol']['id']}", headers=ADMIN, json={'enabled': 1})
    # silinen yerleşik ek yeniden eklenir; Excel'de olmayan elle kayıt silinmez
    c.delete(f"/api/sm/admin/mw/sources/{L2['radio-browser']['id']}", headers=ADMIN)
    # ---- sentetik xlsx: doğrudan turuncu dolgu, bilinmeyen kategori, aynı slug
    syn = xlsx_bytes([['Kamera', 'Örnek Kamera Ağı', 'kamera', 'https://ornek.example', 'REST', 'Yok', 'Pull', '', 'Açık veri', ''],
                      ['Bilinmeyen', 'X Kaynak', '', '', '', '', '', '', '', ''],
                      ['Kamera', 'Örnek Kamera Ağı (kopya)', '', '', '', '', '', '', 'Açık', '']], orange_license_rows=(2,))
    r4 = c.post('/api/sm/admin/mw/import', headers=ADMIN, files={'file': ('s.xlsx', syn)}).json()
    assert r4['added'] == 2 and [x['row'] for x in r4['skipped']] == [3, 4], r4   # yeni satır + radio-browser yeniden
    L3 = {s['slug']: s for s in c.get('/api/sm/admin/mw/sources', headers=ADMIN).json()['sources']}
    ok = L3['ornek-kamera-agi']
    assert ok['noncommercial'] == 1 and ok['adapter'] is None and ok['kind'] == 'camera' and ok['enabled'] == 0 and 'radio-browser' in L3 and len(L3) == len(src) + 1

    # ---- CRUD + doğrulama
    bad = [{'slug': 'A B'}, {'category': 'yok'}, {'kind': 'yok'}, {'name': ''}, {'params': '[1]'}, {'params': 'x{'}, {'params': {'a': 'x' * 5000}},
           {'attribution_url': 'javascript:alert(1)'}, {'endpoint': 'ftp://x'}, {'rate_per_min': 0}, {'rate_per_min': 601}, {'ttl_s': 4}, {'ttl_s': 86401},
           {'ttl_s': 1.5}, {'enabled': 'evet'}, {'license': 'x' * 501}, {'adapter': 'Kötü adaptör'}, {'api_key': 'a\nb'}]
    base = {'slug': 'benim-kameralarim', 'category': 'camera', 'kind': 'camera', 'name': 'Benim kameralarım', 'adapter': 'points'}
    for b in bad:
        r = c.post('/api/sm/admin/mw/sources', headers=ADMIN, json=base | b)
        assert r.status_code == 422 and r.json()['code'] == 'invalid', (b, r.text)
    assert c.post('/api/sm/admin/mw/sources', headers=ADMIN, json={'slug': 'eksik'}).status_code == 422
    r = c.post('/api/sm/admin/mw/sources', headers=ADMIN, json=base | {'enabled': True, 'api_key': 'k-1', 'endpoint': 'wss://ornek.example/ws',
                                                                      'attribution_url': 'https://ornek.example', 'rate_per_min': 0.5, 'ttl_s': 30})
    assert r.status_code == 201 and r.json()['has_key'] and r.json()['origin'] == 'manual' and 'k-1' not in r.text, r.text
    pid_src = r.json()['id']
    assert c.post('/api/sm/admin/mw/sources', headers=ADMIN, json=base).status_code == 409
    assert c.put(f'/api/sm/admin/mw/sources/{pid_src}', headers=ADMIN, json={'slug': 'adsb-lol'}).status_code == 409
    assert c.put('/api/sm/admin/mw/sources/999999', headers=ADMIN, json={'enabled': 1}).status_code == 404
    r = c.put(f'/api/sm/admin/mw/sources/{pid_src}', headers=ADMIN, json={'api_key': None, 'note': 'not'}); assert r.json()['has_key'] is True   # None = dokunma
    r = c.put(f'/api/sm/admin/mw/sources/{pid_src}', headers=ADMIN, json={'api_key': ''}); assert r.json()['has_key'] is False   # "" = sil
    c.put(f'/api/sm/admin/mw/sources/{pid_src}', headers=ADMIN, json={'api_key': 'k-2'})
    # noktalar: yalnız points adaptörlü kaynakta; doğrulama
    assert c.post(f"/api/sm/admin/mw/sources/{L3['adsb-lol']['id']}/points", headers=ADMIN, json={'name': 'x', 'lat': 1, 'lon': 1}).status_code == 422
    for b in ({'lat': 91}, {'lon': -181}, {'name': ''}, {'media_type': 'video'}, {'media_url': 'http://kamera.example/a.jpg'}, {'props': [1]},
              {'props': {'a': 'x' * 3000}}, {'lat': None}):
        r = c.post(f'/api/sm/admin/mw/sources/{pid_src}/points', headers=ADMIN, json={'name': 'Galata', 'lat': 41.0256, 'lon': 28.9744} | b)
        assert r.status_code == 422, (b, r.text)
    r = c.post(f'/api/sm/admin/mw/sources/{pid_src}/points', headers=ADMIN, json={'name': 'Galata', 'lat': 41.0256, 'lon': 28.9744, 'media_type': 'image',
                                                                                  'media_url': 'https://kamera.example/galata.jpg', 'props': {'yenileme_s': 30}})
    assert r.status_code == 201 and r.json()['props'] == {'yenileme_s': 30}, r.text
    p1 = r.json()['id']
    p2 = c.post(f'/api/sm/admin/mw/sources/{pid_src}/points', headers=ADMIN, json={'name': 'Kapalı nokta', 'lat': 0, 'lon': 0, 'enabled': False}).json()['id']
    assert c.put(f'/api/sm/admin/mw/points/{p1}', headers=ADMIN, json={'name': 'Galata Kulesi'}).json()['name'] == 'Galata Kulesi'
    assert c.put('/api/sm/admin/mw/points/999999', headers=ADMIN, json={'name': 'x'}).status_code == 404
    pts = c.get(f'/api/sm/admin/mw/sources/{pid_src}/points', headers=ADMIN).json()['points']
    assert [p['name'] for p in pts] == ['Galata Kulesi', 'Kapalı nokta']
    assert next(s for s in c.get('/api/sm/admin/mw/sources', headers=ADMIN).json()['sources'] if s['id'] == pid_src)['points'] == 2

    # ---- iç uç (masterworld sunucusu): gizlisiz / yanlış 403; doğruyla api_key dahil, yalnız etkin kaynak + etkin nokta
    assert c.get('/api/mw/internal/sources').status_code == 403
    assert c.get('/api/mw/internal/sources', headers={'X-Masterworld-Secret': 'yanlis'}).status_code == 403
    assert c.get('/api/mw/internal/sources', headers=ADMIN).status_code == 403
    r = c.get('/api/mw/internal/sources', headers={'X-Masterworld-Secret': 'mw-gizli'})
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
    I = r.json()
    isrc = {s['slug']: s for s in I['sources']}
    assert all(s['enabled'] == 1 for s in I['sources']) and 'gcmb-io' not in isrc and 'adsb-lol' in isrc
    assert isrc['opensky-network']['api_key'] == 'gizli-anahtar-123' and isrc['benim-kameralarim']['api_key'] == 'k-2' and isrc['adsb-lol']['api_key'] is None
    assert set(isrc['adsb-lol']) == set(mw_catalog_internal_keys()) and isrc['celestrak']['params']['groups'][0] == 'stations'
    assert [p['name'] for p in I['points'][str(pid_src)]] == ['Galata Kulesi'] and I['points'][str(pid_src)][0]['props'] == {'yenileme_s': 30}
    assert I['version'] and I['version'] >= max(s['updated_at'] if 'updated_at' in s else '' for s in L['sources'])
    c.delete(f'/api/sm/admin/mw/points/{p2}', headers=ADMIN)
    c.delete(f'/api/sm/admin/mw/sources/{pid_src}', headers=ADMIN)
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM mw_points WHERE source_id = ?', (pid_src,)).fetchone()[0] == 0   # ON DELETE CASCADE

    # ---- hesap: mw öneki, profil (mw_profiles), CORS
    k = c.post('/api/mw/auth/prelogin', json={'email': 'kure@test.com'}).json()['kdf']
    assert c.post('/api/mw/auth/register', json={'name': 'Küre Kullanıcı', 'email': 'kure@test.com', 'auth_hash': auth_hash('Kure-1234', k), 'brand': 'mw'}).json()['ok']
    with db.connect() as conn:
        conn.execute("UPDATE users SET status = 'AKTIF', verified_at = '2026-10-20T10:00:00' WHERE email = 'kure@test.com'")
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE email = 'kure@test.com'").fetchone()[0]
    g = TestClient(app, base_url='https://testserver')
    r = g.post('/api/mw/auth/login', json={'email': 'kure@test.com', 'auth_hash': auth_hash('Kure-1234', k), 'device': 'MASTERWORLD Web'})
    assert r.status_code == 200, r.text
    MW = {'Authorization': 'Bearer ' + r.json()['token']}
    assert g.get('/api/mw/me', headers=MW).json()['user']['email'] == 'kure@test.com'
    assert g.get('/api/mw/profile', headers=MW).json()['profile'] is None
    assert g.put('/api/mw/profile', headers=MW, json={'profile': {'layers': ['adsb-lol'], 'view': [29, 41, 3]}}).json()['ok']
    assert g.get('/api/mw/profile', headers=MW).json()['profile'] == {'layers': ['adsb-lol'], 'view': [29, 41, 3]}
    assert g.put('/api/mw/profile', headers={'X-Simumav-Secret': 'sv-gizli'}, json={'user_id': uid, 'profile': {}}).status_code == 401   # sunucu yazımı yalnız sv
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM mw_profiles WHERE user_id = ?', (uid,)).fetchone()[0] == 1
    o = {'Origin': 'https://masterworld.app'}
    r = g.options('/api/mw/me', headers=o | {'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization'})
    assert r.status_code == 204 and r.headers['access-control-allow-origin'] == 'https://masterworld.app' and 'Authorization' in r.headers['access-control-allow-headers']
    r = g.get('/api/mw/profile', headers=MW | {'Origin': 'https://www.masterworld.app'})
    assert r.headers.get('access-control-allow-origin') == 'https://www.masterworld.app' and r.headers.get('vary') == 'Origin'
    assert 'access-control-allow-origin' not in g.get('/api/sv/me', headers=MW | o).headers   # mw kökeni sv yolunda yok
    assert 'access-control-allow-origin' not in g.get('/api/sm/me', headers=o).headers
    assert g.options('/api/sv/me', headers=o | {'Access-Control-Request-Method': 'GET'}).status_code != 204
    assert 'access-control-allow-origin' not in g.get('/api/mw/me', headers=MW | {'Origin': 'https://simumav.com'}).headers   # sv kökeni mw yolunda yok
    assert 'access-control-allow-origin' not in g.get('/api/mw/internal/sources', headers=o | {'X-Masterworld-Secret': 'mw-gizli'}).headers   # iç uç CORS dışı
    assert g.options('/api/mw/internal/sources', headers=o | {'Access-Control-Request-Method': 'GET'}).status_code != 204
    r = g.options('/api/sv/me', headers={'Origin': 'https://simumav.com', 'Access-Control-Request-Method': 'GET'})   # SIMUMAV davranışı aynen
    assert r.status_code == 204 and r.headers['access-control-allow-origin'] == 'https://simumav.com'
    assert 'access-control-allow-origin' not in g.get('/api/mw/me', headers=MW | {'Origin': 'https://kotu.example'}).headers

    # ---- katalog: /api/mt/apps (web=1) mw group apps; Hesabım; admin özetleri
    w = TestClient(app, base_url='https://testserver')
    assert w.post('/api/mt/auth/login', json={'email': 'kure@test.com', 'auth_hash': auth_hash('Kure-1234', k), 'client': 'web'}).status_code == 200
    cat = w.get('/api/mt/apps?web=1').json()['apps']
    mw = next(a for a in cat if a['app'] == 'mw')
    assert mw['group'] == 'apps' and mw['kind'] == 'web' and mw['name'] == 'MASTERWORLD' and mw['url'] == 'https://masterworld.app/' and mw['site'] == 'https://masterworld.app/'
    assert set(mw['description']) == {'tr', 'en', 'fr', 'de', 'es', 'ar', 'zh', 'ru'} and mw['icon_svg'] == '/brand/mw.svg'
    assert next(a for a in cat if a['app'] == 'sv')['group'] == 'games' and next(a for a in cat if a['app'] == 'vf')['group'] == 'games'
    acc = w.get('/api/mt/account').json()
    assert [(x['app'], x['group'], x['has_profile']) for x in acc['games']][-1] == ('mw', 'apps', True)
    au = c.get('/api/sm/admin/users', headers=ADMIN).json()
    ku = next(u for u in au['users'] if u['email'] == 'kure@test.com')
    assert set(ku['games']['mw']) == {'has_profile', 'last_at'} and ku['games']['mw']['has_profile'] is True and ku['games']['mw']['last_at']
    assert au['stats']['games']['mw'] == {'name': 'MASTERWORLD', 'users': 1, 'release': None}
    # simgeler ve portal yolları
    assert c.get('/brand/mw.svg').headers['content-type'] == 'image/svg+xml' and c.get('/brand/mw.png').status_code == 200 and c.get('/brand/mw-512.png').status_code == 200
    for pth in ('/oyunlar/masterworld', '/oyunlar/masterworld/', '/oyunlar/masterworld/tanitim/', '/oyunlar/masterworld/x.html'):
        r = c.get(pth, headers=MTH, follow_redirects=False)
        assert r.status_code == 307 and r.headers['location'] == 'https://masterworld.app/', (pth, r.status_code)
    assert c.get('/oyunlar/masterworld/', headers={'Host': 'sshmasters.com'}, follow_redirects=False).status_code == 404
    home = c.get('/', headers=MTH).text
    assert 'href="https://masterworld.app/"' in home and '/brand/mw.svg' in home and 'MASTERWORLD' in home
    assert 'data-brand="mw"' in c.get('/giris?app=mw', headers=MTH).text

    # ---- web paketleri: /api/mw/web-releases (MASTERWORLD_RELEASE_KEY; run-masterworld.sh)
    def paket(version, run='run-masterworld.sh'):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            for ad, b in (('VERSION', version.encode() + b'\n'), (run, b'#!/bin/sh\n'), ('requirements.txt', b'fastapi\n'), ('app/main.py', b'# x\n')):
                ti = tarfile.TarInfo(ad); ti.size = len(b); tf.addfile(ti, io.BytesIO(b))
        d = buf.getvalue()
        return d, hashlib.sha256(d).hexdigest()
    gonder = lambda d, s, v='0.1.0', key='mw-anahtar': c.post('/api/mw/web-releases', headers={'X-Release-Key': key}, data={'version': v, 'sha256': s},   # noqa: E731
                                                            files={'package': (f'masterworld-{v}.tar.gz', d, 'application/gzip')})
    d1, s1 = paket('0.1.0')
    assert gonder(d1, s1, key='sv-anahtar').status_code == 403
    d0, s0 = paket('0.1.0', run='run-simumav.sh'); assert gonder(d0, s0).json()['code'] == 'incomplete'
    r = gonder(d1, s1); assert r.status_code == 201 and r.json()['file'] == 'mw/0.1.0/masterworld-0.1.0.tar.gz', r.text
    assert (settings.RELEASE_DIR / 'mw' / 'latest').read_text() == '0.1.0\n'
    assert c.get('/api/mw/web-releases/latest').json()['version'] == '0.1.0'
    assert c.get('/api/mw/web-releases', headers=ADMIN).json()['latest'] == '0.1.0'
    assert c.get('/api/sm/admin/users', headers=ADMIN).json()['stats']['games']['mw']['release']['version'] == '0.1.0'
    _RATE.clear()

    # ---- CLI: yedek + içe aktarma (ayrı veri dizini)
    D2 = tempfile.mkdtemp()
    env = dict(os.environ, SSHM_DATA_DIR=D2)
    p = subprocess.run([sys.executable, '-m', 'sshm.mw_catalog', XLSX], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out['added'] == 51 + len(BUILTINS) and 'Yedek:' in p.stderr and any(n.startswith('sshm-pre-mw-') for n in os.listdir(D2))
    p = subprocess.run([sys.executable, '-m', 'sshm.mw_catalog', XLSX], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert json.loads(p.stdout)['added'] == 0
    print('MASTERWORLD hesap servisi testleri geçti.')


def mw_catalog_internal_keys():
    from sshm.main import MW_INTERNAL_SRC
    return MW_INTERNAL_SRC + ('params',)


if __name__ == '__main__':
    main()
