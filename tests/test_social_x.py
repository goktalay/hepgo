"""Sosyal Medya › X (Twitter): ayrı entegrasyon (meta / x / tiktok); anahtar girilince X açılır; “X ile bağlan” (OAuth 2.0 +
PKCE) → hesap eklenir, jeton şifreli saklanır, paylaşımlar çekilir; süresi dolan jeton yenilenir (yeni yenileme jetonu
kaydedilir), yalnız yeni paylaşımlar istenir (since_id); hesap silinince X izni geri alınır. X API taklit edilir.
Çalıştırma: .venv/bin/python -m tests.test_social_x
"""
import base64
import hashlib
import json
import os
import tempfile
from urllib.parse import parse_qs, quote, urlparse

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_X_CLIENT_ID='',
                  CAYMAZ_X_CLIENT_SECRET='', CAYMAZ_PUBLIC_URL='https://firma.example')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, social  # noqa: E402
from app.main import app  # noqa: E402


class Resp:
    def __init__(self, code, data):
        self.status_code, self._d, self.headers = code, data, {'content-type': 'application/json'}

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


calls = []


def fake_post(url, data=None, auth=None, **kw):
    calls.append(('POST', url, dict(data or {}), auth))
    if url == social.X_REVOKE:
        return Resp(200, {'revoked': True})
    n = sum(1 for c in calls if c[1] == social.X_TOKEN)
    return Resp(200, {'access_token': f'erisim-{n}', 'refresh_token': f'yenileme-{n}', 'expires_in': 7200})


def fake_get(url, params=None, headers=None, **kw):
    calls.append(('GET', url, dict(params or {}), headers.get('Authorization')))
    if url.endswith('/users/me'):
        return Resp(200, {'data': {'id': '42', 'username': 'gokkubbe', 'name': 'Gökkubbe', 'profile_image_url': 'https://pbs/x.jpg'}})
    if (params or {}).get('since_id'):
        return Resp(200, {'data': [{'id': '1003', 'text': 'Yeni paylaşım', 'created_at': '2026-10-04T10:00:00.000Z'}]})
    return Resp(200, {'data': [{'id': '1002', 'text': 'İkinci', 'created_at': '2026-10-03T10:00:00.000Z', 'attachments': {'media_keys': ['m1']}},
                               {'id': '1001', 'text': 'Birinci', 'created_at': '2026-10-02T10:00:00.000Z'}],
                      'includes': {'media': [{'media_key': 'm1', 'type': 'photo', 'url': 'https://pbs/foto.jpg'}]}})


social.httpx.post, social.httpx.get = fake_post, fake_get


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    with TestClient(app, base_url='https://firma.example') as c:
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        groups = {g['key'] for g in ok(c.get('/api/system/integrations'))['groups']}
        assert {'meta', 'x', 'tiktok'} <= groups and 'social' not in groups, groups
        assert ok(c.get('/api/social/accounts'))['available']['x'] is False          # anahtar yok → kapalı
        assert c.get('/api/social/oauth/x/start').status_code == 400
        ok(c.put('/api/system/integrations/x', json={'values': {'X_CLIENT_ID': 'istemci', 'X_CLIENT_SECRET': 'gizli'}}))
        d = ok(c.get('/api/social/accounts'))
        assert d['available']['x'] is True and d['providers']['x']['oauth'] and not d['available']['instagram']
        assert ok(c.post('/api/system/integrations/x/test', json={}))['ok']
        assert c.post('/api/social/accounts', json={'provider': 'x', 'handle': '@birisi'}).status_code == 400   # elle eklenemez
        assert c.get('/api/social/oauth/instagram/start').status_code == 404

        url = ok(c.get('/api/social/oauth/x/start'))['url']
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert url.startswith(social.X_AUTH) and q['client_id'] == 'istemci' and q['code_challenge_method'] == 'S256'
        assert q['redirect_uri'] == 'https://firma.example/api/social/oauth/x/callback' and 'offline.access' in q['scope']
        bad = c.get('/api/social/oauth/x/callback', params={'state': 'yanlis', 'code': 'k'}, follow_redirects=False)
        assert bad.status_code == 303 and 'msg=' in bad.headers['location'] and 'msg=ok' not in bad.headers['location']
        r = c.get('/api/social/oauth/x/callback', params={'state': q['state'], 'code': 'kod-1'}, follow_redirects=False)
        assert r.status_code == 303 and r.headers['location'].endswith('#/settings/social?msg=ok'), r.headers['location']
        tok_call = next(x for x in calls if x[1] == social.X_TOKEN)
        verifier = tok_call[2]['code_verifier']   # PKCE: verifier → challenge eşleşmeli
        assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode() == q['code_challenge']
        assert tok_call[3] == ('istemci', 'gizli') and tok_call[2]['code'] == 'kod-1'
        assert c.get('/api/social/oauth/x/callback', params={'state': q['state'], 'code': 'kod-1'}, follow_redirects=False).headers['location'] != r.headers['location']   # durum tek kullanımlık

        accs = ok(c.get('/api/social/accounts'))['accounts']
        assert len(accs) == 1 and accs[0]['handle'] == '@gokkubbe' and accs[0]['display_name'] == 'Gökkubbe' and accs[0]['posts'] == 2, accs
        aid = accs[0]['id']
        with db.connect() as conn:
            raw = conn.execute('SELECT token FROM social_accounts WHERE id = ?', (aid,)).fetchone()[0]
        assert 'erisim' not in raw and 'yenileme' not in raw   # jeton şifreli
        posts = ok(c.get('/api/social/feed'))['posts']
        assert [p['text'] for p in posts] == ['İkinci', 'Birinci'] and posts[0]['media'] == 'https://pbs/foto.jpg'
        assert posts[0]['url'] == 'https://x.com/gokkubbe/status/1002'

        # Jetonun süresi doldu → yenilenir, yeni yenileme jetonu saklanır; yalnız yeni paylaşımlar istenir
        with db.connect() as conn:
            tok = json.loads(social.decrypt(raw)); tok['exp'] = 0
            conn.execute('UPDATE social_accounts SET token = ? WHERE id = ?', (social.encrypt(json.dumps(tok)), aid)); conn.commit()
        assert ok(c.post(f'/api/social/accounts/{aid}/refresh', json={}))['new'] == 1
        ref = [x for x in calls if x[1] == social.X_TOKEN][-1]
        assert ref[2]['grant_type'] == 'refresh_token' and ref[2]['refresh_token'] == 'yenileme-1'
        last_get = [x for x in calls if x[0] == 'GET' and '/tweets' in x[1]][-1]
        assert last_get[2]['since_id'] == '1002' and last_get[3] == 'Bearer erisim-2'
        with db.connect() as conn:
            tok2 = json.loads(social.decrypt(conn.execute('SELECT token FROM social_accounts WHERE id = ?', (aid,)).fetchone()[0]))
        assert tok2['refresh'] == 'yenileme-2' and tok2['uid'] == '42'

        # Aynı hesap tekrar bağlanınca yeni kayıt açılmaz
        q2 = {k: v[0] for k, v in parse_qs(urlparse(ok(c.get('/api/social/oauth/x/start'))['url']).query).items()}
        c.get('/api/social/oauth/x/callback', params={'state': q2['state'], 'code': 'kod-2'}, follow_redirects=False)
        assert len(ok(c.get('/api/social/accounts'))['accounts']) == 1

        # X ücretli erişim yoksa (402): anlaşılır Türkçe hata hesapta görünür
        orig = social.httpx.get
        social.httpx.get = lambda url, **kw: Resp(402, {'title': 'Payment Required'})
        ok(c.post(f'/api/social/accounts/{aid}/refresh', json={}))
        err = ok(c.get('/api/social/accounts'))['accounts'][0]['last_error']
        assert 'ücretli erişim' in err and 'http' not in err, err
        social.httpx.get = orig
        # X izin ekranında hata → açıklaması gösterilir; kullanıcı vazgeçerse "İzin verilmedi"
        q3 = {k: v[0] for k, v in parse_qs(urlparse(ok(c.get('/api/social/oauth/x/start'))['url']).query).items()}
        loc = c.get('/api/social/oauth/x/callback', params={'state': q3['state'], 'error': 'invalid_request', 'error_description': 'Value passed for the redirect uri did not match'},
                    follow_redirects=False).headers['location']
        assert 'redirect%20uri' in loc, loc
        q4 = {k: v[0] for k, v in parse_qs(urlparse(ok(c.get('/api/social/oauth/x/start'))['url']).query).items()}
        loc = c.get('/api/social/oauth/x/callback', params={'state': q4['state'], 'error': 'access_denied'}, follow_redirects=False).headers['location']
        assert loc.endswith(quote('İzin verilmedi', safe='')), loc

        ok(c.delete(f'/api/social/accounts/{aid}'))
        assert calls[-1][1] == social.X_REVOKE and calls[-1][2]['token'].startswith('yenileme')
        assert ok(c.get('/api/social/accounts'))['accounts'] == []
    print('X (Twitter) testleri geçti.')


if __name__ == '__main__':
    main()
