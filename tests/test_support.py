"""Destek Merkezi (merkez) ↔ Üyeliğim & Destek (firma) uçtan uca: iki ayrı süreç — merkez (CAYMAZ_FEDERATION_CENTRAL=1)
uvicorn ile, firma bu süreçte TestClient ile; aradaki tüm çağrılar gerçek federasyon HTTP'si.

Kapsam: çevrimdışıyken canlı destek → talep; destek personeli ekleme, çevrimiçi durum, otomatik atama; sohbet (hoş geldin,
yazıyor, dosya, ekran paylaşım linki doğrulaması, talebe dönüştürme, bitirme, puan); dosyalı talep, iç notun firmaya
gitmemesi, ilk yanıt (SLA), firma dosya indirme, çözülmeden puan verilememesi, kapatma; ödeme bildirimi → onay → ödeme;
başka firmanın kaydına erişilememesi; yönetici olmayanın ayar değiştirememesi.

Çalıştırma: .venv/bin/python -m tests.test_support
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SECRET = 'fed-test-secret-123'
s = socket.socket(); s.bind(('127.0.0.1', 0)); PORT = s.getsockname()[1]; s.close()
CENTRAL = f'http://127.0.0.1:{PORT}'
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@firma', CAYMAZ_ADMIN_PASSWORD='firma-sifre-1', CAYMAZ_COMPANY_NAME='Acme Makine',
                  CAYMAZ_FEDERATION_URL=CENTRAL, CAYMAZ_FEDERATION_SECRET=SECRET, CAYMAZ_TENANT_SLUG='acme')

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.headers.get('content-type', '').startswith('application/json') else r


def start_central():
    env = dict(os.environ, CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_FEDERATION_CENTRAL='1', CAYMAZ_FEDERATION_URL='', CAYMAZ_TENANT_SLUG='',
               CAYMAZ_ADMIN_USERNAME='admin@merkez', CAYMAZ_ADMIN_PASSWORD='merkez-sifre-1', CAYMAZ_COMPANY_NAME='Merkez',
               CAYMAZ_VEILOX_SOCKET='/nonexistent.sock', CAYMAZ_CENTRAL_API_SECRET='')
    p = subprocess.Popen([str(ROOT / '.venv/bin/uvicorn'), 'app.main:app', '--port', str(PORT), '--log-level', 'error'], cwd=ROOT, env=env)
    for _ in range(160):
        try:
            if httpx.get(f'{CENTRAL}/api/meta', timeout=1).status_code < 500:
                return p
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    p.terminate()
    raise RuntimeError('merkez başlamadı')


def main():
    proc = start_central()
    try:
        run()
    finally:
        proc.terminate()
    print('Destek Merkezi testleri geçti.')


def run():
    m = httpx.Client(base_url=CENTRAL, timeout=30)
    ok(m.post('/api/auth/login', json={'username': 'admin@merkez', 'password': 'merkez-sifre-1'}))
    with TestClient(app) as f:
        ok(f.post('/api/auth/login', json={'username': 'admin@firma', 'password': 'firma-sifre-1'}))
        st = ok(f.get('/api/membership/support-status'))
        assert st['online'] == 0 and 'welcome' in st
        # 1) kimse çevrimiçi değilken canlı destek → talep olarak kaydedilir
        r = ok(f.post('/api/membership/chats', json={'topic': 'Giriş sorunu', 'message': 'Kullanıcılar giriş yapamıyor'}))
        assert r['offline'] and r['ticket']['code'].startswith('T-'), r
        # 2) destek personeli ekle; personel Destek Merkezi'ni açınca çevrimiçi
        sid = ok(m.post('/api/central/support/staff', json={'full_name': 'Ayşe Destek', 'username': 'ayse@merkez', 'password': 'Destek-Parola-82x',
                                                              'title': 'Teknik Destek Uzmanı', 'skills': ['teknik']}))['id']
        d = httpx.Client(base_url=CENTRAL, timeout=30)
        ok(d.post('/api/auth/login', json={'username': 'ayse@merkez', 'password': 'Destek-Parola-82x'}))
        ok(d.get('/api/central/support/pulse'))
        assert ok(f.get('/api/membership/support-status'))['online'] == 1
        # yönetici olmayan personel ayar değiştiremez / ekip yönetemez
        assert d.put('/api/central/support/settings', json={'auto_assign': False}).status_code == 403
        assert d.post('/api/central/support/staff', json={'user_id': 1}).status_code == 403
        # 3) canlı sohbet: otomatik atama + hoş geldin mesajı
        c = ok(f.post('/api/membership/chats', json={'topic': 'Yazıcı bağlantısı', 'category': 'teknik', 'message': 'Yazıcılar görünmüyor'}))
        cid = c['id']
        v = ok(f.get(f'/api/membership/chats/{cid}'))
        assert v['status'] == 'active' and v['assignee_name'] == 'Ayşe Destek', v
        assert any(x['author_kind'] == 'support' for x in v['messages'])
        last = v['messages'][-1]['id']
        live = ok(d.get('/api/central/support/live'))
        assert [x['id'] for x in live['mine']] == [cid]
        ok(f.post(f'/api/membership/chats/{cid}/typing'))
        assert ok(d.get(f'/api/central/support/chats/{cid}'))['typing'] is True
        ok(d.post(f'/api/central/support/chats/{cid}/messages', data={'body': 'Ağ ayarlarınızı kontrol edelim.'}))
        v = ok(f.get(f'/api/membership/chats/{cid}', params={'after': last}))
        assert [x['body'] for x in v['messages']] == ['Ağ ayarlarınızı kontrol edelim.'], v['messages']
        # dosya ve ekran paylaşım linki
        ok(f.post(f'/api/membership/chats/{cid}/messages', data={'body': ''}, files=[('files', ('ekran.png', b'\x89PNG-test', 'image/png'))]))
        bad = f.post(f'/api/membership/chats/{cid}/messages', data={'body': 'javascript:alert(1)', 'kind': 'screen'})
        assert bad.status_code == 400 and 'ekran' in bad.text.lower(), bad.text
        ok(f.post(f'/api/membership/chats/{cid}/messages', data={'body': 'https://acme.hepgo.com/s/ABC2345', 'kind': 'screen'}))
        msgs = ok(d.get(f'/api/central/support/chats/{cid}'))['messages']
        fmsg = next(x for x in msgs if x['kind'] == 'file')
        assert ok(d.get(f'/api/central/support/files/{fmsg["file"]["token"]}')).content == b'\x89PNG-test'
        assert any(x['kind'] == 'screen' for x in msgs)
        # talebe dönüştür, bitir, puan
        tid_chat = ok(d.post(f'/api/central/support/chats/{cid}/ticket', json={'subject': 'Yazıcılar görünmüyor'}))['ticket_id']
        ok(d.post(f'/api/central/support/chats/{cid}/end'))
        assert f.post(f'/api/membership/chats/{cid}/messages', data={'body': 'hala orada mısınız'}).status_code == 409
        ok(f.post(f'/api/membership/chats/{cid}/rate', json={'rating': 5, 'note': 'Çok hızlı'}))
        # 4) dosyalı destek talebi
        t = ok(f.post('/api/membership/tickets', data={'subject': 'Rapor hatası', 'body': 'Aylık rapor açılmıyor', 'category': 'teknik', 'priority': 'yuksek'},
                      files=[('files', ('hata.txt', b'Traceback...', 'text/plain'))]))
        tid = t['id']
        det = ok(d.get(f'/api/central/support/tickets/{tid}'))
        assert det['assignee_name'] == 'Ayşe Destek' and det['due_at'] and det['messages'][0]['files'][0]['name'] == 'hata.txt'
        assert det['member']['slug'] == 'acme'
        ok(d.post(f'/api/central/support/tickets/{tid}/messages', data={'body': 'Bu firmanın rapor modülü eski sürümde', 'internal': '1'}))
        assert ok(d.get(f'/api/central/support/tickets/{tid}'))['first_response_at'] is None   # iç not ilk yanıt sayılmaz
        ok(d.post(f'/api/central/support/tickets/{tid}/messages', data={'body': 'Düzeltme yayınlandı, tekrar dener misiniz?'},
                  files=[('files', ('cozum.pdf', b'%PDF-1.4 x', 'application/pdf'))]))
        det = ok(d.get(f'/api/central/support/tickets/{tid}'))
        assert det['first_response_at'] and det['status'] == 'yanit_bekliyor' and det['sla']['first'] == 'met'
        ft = ok(f.get(f'/api/membership/tickets/{tid}'))
        assert all(x['author_kind'] != 'note' for x in ft['messages']), 'iç not firmaya gitmemeli'
        assert 'assignee_id' not in ft
        tok = next(x for x in ft['messages'] if x['files'] and x['author_kind'] == 'support')['files'][-1]['token']
        assert ok(f.get(f'/api/membership/files/{tok}')).content == b'%PDF-1.4 x'
        assert f.post(f'/api/membership/tickets/{tid}/rate', json={'rating': 4}).status_code == 409
        ok(d.put(f'/api/central/support/tickets/{tid}', json={'status': 'cozuldu'}))
        ok(f.post(f'/api/membership/tickets/{tid}/rate', json={'rating': 4, 'note': 'Teşekkürler'}))
        ok(f.post(f'/api/membership/tickets/{tid}/messages', data={'body': 'Bir sorun daha var'}))
        assert ok(d.get(f'/api/central/support/tickets/{tid}'))['status'] == 'acik'   # firma yanıtı yeniden açar
        ok(f.post(f'/api/membership/tickets/{tid}/close'))
        assert ok(d.get(f'/api/central/support/tickets/{tid}'))['status'] == 'cozuldu'
        lst = ok(f.get('/api/membership/tickets'))
        assert {x['id'] for x in lst} >= {tid, tid_chat, r['ticket']['id']}
        # başka firmanın kaydı görünmez (federasyon slug denetimi)
        other = httpx.get(f'{CENTRAL}/api/federation/tickets/{tid}', params={'slug': 'baska'}, headers={'X-Fed-Secret': SECRET})
        assert other.status_code == 404
        assert httpx.get(f'{CENTRAL}/api/federation/tickets', params={'slug': 'acme'}, headers={'X-Fed-Secret': 'yanlis'}).status_code == 403
        # 5) ödeme bildirimi → merkez onayı → ödeme kaydı
        n = ok(f.post('/api/membership/payment-notices', json={'amount': 3500, 'period': '2026-10', 'method': 'havale', 'reference': 'DK-991'}))
        pend = ok(m.get('/api/central/support/payment-notices'))
        assert [x['id'] for x in pend] == [n['id']]
        ok(m.post(f'/api/central/support/payment-notices/{n["id"]}/decide', json={'approve': True}))
        assert m.post(f'/api/central/support/payment-notices/{n["id"]}/decide', json={'approve': True}).status_code == 409
        mem = ok(f.get('/api/membership'))
        assert mem['notices'][0]['status'] == 'onaylandi' and any(p['amount'] == 3500 for p in mem['payments'])
        assert mem['support']['online'] == 1 and mem['open_tickets'] >= 1
        # 6) pano, ekip, hazır yanıt, ayarlar
        ov = ok(d.get('/api/central/support/overview'))
        assert ov['csat'] and ov['staff'][0]['full_name'] == 'Ayşe Destek'
        team = ok(m.get('/api/central/support/staff'))
        assert team['staff'][0]['id'] == sid and team['staff'][0]['skills'] == ['teknik']
        ok(m.put(f'/api/central/support/staff/{sid}', json={'max_chats': 5, 'skills': ['teknik', 'egitim']}))
        cn = ok(d.post('/api/central/support/canned', json={'title': 'Selamlama', 'body': 'Merhaba, nasıl yardımcı olabilirim?', 'shortcut': 'selam'}))
        assert ok(d.get('/api/central/support/canned'))[0]['id'] == cn['id']
        s2 = ok(m.put('/api/central/support/settings', json={'contact_phone': '0850 000 00 00', 'sla_first': {'acil': 0.5}}))['settings']
        assert s2['sla_first']['acil'] == 0.5 and ok(f.get('/api/membership/support-status'))['contact']['phone'] == '0850 000 00 00'
        # personel çevrimdışı olunca yeni sohbet yine talebe döner
        ok(d.put('/api/central/support/me/status', json={'status': 'away'}))
        assert ok(f.post('/api/membership/chats', json={'message': 'Mesai dışı soru'}))['offline']


if __name__ == '__main__':
    sys.exit(main())
