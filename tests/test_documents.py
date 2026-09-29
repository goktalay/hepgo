"""Firma ve Evrak Yönetimi testi: firma/kişi/logo, evrak yükleme, OCR (resim, taranmış PDF, metin), Türkçe arama,
görünürlük (herkes / roller / yalnızca yükleyen — sistem yöneticisi dahil) ve dosya erişim koruması.

Çalıştırma: .venv/bin/python -m tests.test_documents
"""
import io
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.main import app  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def login(c, u, p):
    ok(c.post('/api/auth/login', json={'username': u, 'password': p}))


def page(lines, angle=0.0):
    img = Image.new('RGB', (1600, 120 + 90 * len(lines)), 'white')
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 44)
    for i, line in enumerate(lines):
        d.text((60, 60 + i * 90), line, fill='black', font=f)
    return img.rotate(angle, expand=True, fillcolor='white') if angle else img


def png(img):
    b = io.BytesIO()
    img.save(b, 'PNG')
    return b.getvalue()


def upload(c, name, data):
    up = ok(c.post('/api/uploads', json={'kind': 'documents', 'file_name': name, 'size': len(data)}))['upload_id']
    ok(c.put(f'/api/uploads/{up}?offset=0', content=data))
    return up


def wait_ocr(c, doc_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        d = ok(c.get(f'/api/documents/{doc_id}'))
        if d['ocr_status'] not in ('BEKLIYOR', 'ISLENIYOR'):
            return d
        time.sleep(0.3)
    raise AssertionError('OCR zaman aşımı')


def main():
    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        mk = lambda u, roles: ok(admin.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': roles,
                                                                'password': 'sifre-1234'}))['id']
        mk('idari1', ['İdari Personel'])
        mk('idari2', ['İdari Personel'])
        mk('pilot', ['Pilot'])
        me = ok(admin.get('/api/auth/me'))['id']

    with TestClient(app) as c:
        login(c, 'pilot', 'sifre-1234')
        assert c.get('/api/companies').status_code == 403 and c.get('/api/documents').status_code == 403

    with TestClient(app) as a:
        login(a, 'idari1', 'sifre-1234')
        # ---- Firma, logo, kişiler
        cid = ok(a.post('/api/companies', json={'name': 'Şahin Çelik A.Ş.', 'tax_no': '1234567890', 'phone': '0312 000 00 00'}))['id']
        assert a.post('/api/companies', json={'name': 'şahin çelik a.ş.'}).status_code == 400   # aynı ad
        cid2 = ok(a.post('/api/companies', json={'name': 'Kalecik Belediyesi'}))['id']
        logo = ok(a.post(f'/api/companies/{cid}/logo', files={'file': ('logo.png', png(page(['LOGO'])), 'image/png')}))['logo']
        assert a.get(f'/api/files/{logo}').status_code == 200
        pid = ok(a.post(f'/api/companies/{cid}/people', json={'full_name': 'Ayşe Yılmaz', 'title': 'Satın Alma Müdürü'}))['id']
        ok(a.put(f'/api/companies/people/{pid}', json={'full_name': 'Ayşe Yılmaz', 'title': 'Genel Müdür', 'email': 'ayse@sahin.com'}))
        co = ok(a.get(f'/api/companies/{cid}'))
        assert co['people'][0]['title'] == 'Genel Müdür' and co['logo'] == logo

        # ---- Toplantılar: karşı taraftan (firma kişileri) ve bizden (kullanıcılar) katılanlar
        pid2 = ok(a.post(f'/api/companies/{cid2}/people', json={'full_name': 'Başkan Yardımcısı'}))['id']
        users = {u['username']: u['id'] for u in ok(a.get('/api/people'))}
        body = {'subject': 'Tedarik görüşmesi', 'meeting_at': '2026-10-02T14:30+03:00', 'location': 'Şahin Çelik ofisi',
                'person_ids': [pid], 'user_ids': [users['idari1'], users['admin@test']], 'other_attendees': 'Avukat',
                'notes': 'Filament fiyatları görüşüldü.'}
        assert a.post(f'/api/companies/{cid}/meetings', json={**body, 'person_ids': [pid2]}).status_code == 400   # başka firmanın kişisi
        assert a.post(f'/api/companies/{cid}/meetings', json={**body, 'subject': ' '}).status_code == 400
        # ---- Adresler: yeni firmada girilen adres "Merkez"; birden fazla adres; toplantıda seçilir
        cid3 = ok(a.post('/api/companies', json={'name': 'Adres Test Ltd.', 'address': 'Ostim OSB 1. Cad. No:5'}))['id']
        ad = ok(a.get(f'/api/companies/{cid3}'))['addresses']
        assert [(x['label'], x['address']) for x in ad] == [('Merkez', 'Ostim OSB 1. Cad. No:5')]
        assert a.post(f'/api/companies/{cid}/addresses', json={'label': ' ', 'address': 'x'}).status_code == 400
        a1 = ok(a.post(f'/api/companies/{cid}/addresses', json={'label': 'Merkez', 'address': 'Atatürk Blv. 10', 'city': 'Ankara'}))['id']
        a2 = ok(a.post(f'/api/companies/{cid}/addresses', json={'label': 'Fabrika', 'address': 'Sincan OSB', 'city': 'Ankara / Sincan'}))['id']
        ok(a.put(f'/api/companies/addresses/{a2}', json={'label': 'Fabrika', 'address': 'Sincan OSB 12. Cad.', 'city': 'Ankara / Sincan'}))
        co = ok(a.get(f'/api/companies/{cid}'))
        assert [x['label'] for x in co['addresses']] == ['Merkez', 'Fabrika'] and co['addresses'][1]['address'].endswith('12. Cad.')
        assert next(x for x in ok(a.get('/api/companies')) if x['id'] == cid)['address_count'] == 2
        assert a.post(f'/api/companies/{cid}/meetings', json={**body, 'address_id': ad[0]['id']}).status_code == 400   # başka firmanın adresi
        body['address_id'] = a2
        mid = ok(a.post(f'/api/companies/{cid}/meetings', json=body))['id']
        m = ok(a.get(f'/api/companies/{cid}'))['meetings'][0]
        assert m['address_label'] == 'Fabrika' and m['address_city'] == 'Ankara / Sincan'
        assert a.delete(f'/api/companies/addresses/{a2}').status_code == 400   # toplantıda kullanılıyor
        ok(a.delete(f'/api/companies/addresses/{a1}'))
        m = ok(a.get(f'/api/companies/{cid}'))['meetings'][0]
        assert m['id'] == mid and [p['full_name'] for p in m['people']] == ['Ayşe Yılmaz']
        assert sorted(u['id'] for u in m['users']) == sorted([users['idari1'], users['admin@test']])
        assert m['meeting_at'].startswith('2026-10-02T') and m['other_attendees'] == 'Avukat'
        ok(a.put(f'/api/companies/meetings/{mid}', json={**body, 'user_ids': [users['idari1']], 'notes': 'Karar: sipariş verilecek.'}))
        m = ok(a.get(f'/api/companies/{cid}'))['meetings'][0]
        assert [u['full_name'] for u in m['users']] == ['Idari1'] and m['notes'].startswith('Karar')
        mid2 = ok(a.post(f'/api/companies/{cid}/meetings', json={**body, 'subject': 'Silinecek'}))['id']
        ok(a.delete(f'/api/companies/meetings/{mid2}'))
        assert len(ok(a.get(f'/api/companies/{cid}'))['meetings']) == 1

        # ---- Evrak: resim (OCR), taranmış PDF (iki sayfa, birleştirilmiş resimler), metin dosyası
        img_doc = ok(a.post('/api/documents', json={
            'upload_ids': [upload(a, 'fatura.png', png(page(['GÖKKUBBE Teknoloji A.Ş. Fatura No: 2026/147',
                                                               'Ödeme tutarı: 125.000,00 TL', 'Iğdır şubesi'], 1.2)))],
            'title': 'Eylül faturası', 'company_ids': [cid], 'doc_date': '2026-09-20'}))['ids'][0]
        scan = ok(a.post('/api/documents', json={
            'upload_ids': [upload(a, 's1.jpg', png(page(['İşbu sözleşme ŞAHİN Çelik ile imzalanmıştır.']))),
                           upload(a, 's2.jpg', png(page(['Sözleşme süresi on iki aydır.'])))],
            'merge_images': True, 'title': 'Tedarik sözleşmesi', 'company_ids': [cid], 'person_ids': [pid]}))['ids']
        assert len(scan) == 1
        txt = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'not.txt', 'Toplantı notu: Kalecik test sahası'.encode())],
                                                 'company_ids': [cid2]}))['ids'][0]
        d = wait_ocr(a, img_doc)
        assert d['ocr_status'] == 'TAMAM' and 'Fatura No' in d['ocr_text'] and '125.000,00' in d['ocr_text'], d['ocr_text']
        assert d['kind'] == 'RESIM' and d['thumb']
        s = wait_ocr(a, scan[0])
        assert s['kind'] == 'EVRAK' and s['file_name'] == 'Tedarik sözleşmesi.pdf' and s['pages'] == 2
        assert 'sözleşme' in s['ocr_text'].lower() and 'on iki' in s['ocr_text']
        assert wait_ocr(a, txt)['ocr_text'].startswith('Toplantı notu') and ok(a.get(f'/api/documents/{txt}'))['title'] == 'not'

        # ---- Arama: Türkçe harf / büyük-küçük farkı yok sayılır; cümle; kelime öneki; alıntı
        search = lambda q, **kw: ok(a.get('/api/documents', params={'q': q, **kw}))['documents']
        assert [x['id'] for x in search('sozlesme suresi')] == scan
        r = search('SÖZLEŞME SÜRESİ')[0]['snippet']
        assert r['match'].lower().startswith('sözleşme') and 'aydır' in r['after']
        assert [x['id'] for x in search('igdir')] == [img_doc]       # ı/İ farkı
        assert [x['id'] for x in search('fatur')] == [img_doc]       # önek
        assert {x['id'] for x in search('kalecik')} == {txt}          # metin dosyası
        assert [x['id'] for x in search('ayse yilmaz')] == scan       # ilişkili kişi adı
        assert search('olmayan kelime zzz') == []
        assert {x['id'] for x in ok(a.get('/api/documents', params={'company_id': cid}))['documents']} == {img_doc, *scan}
        assert [x['id'] for x in ok(a.get('/api/documents', params={'person_id': pid}))['documents']] == scan
        assert [x['id'] for x in ok(a.get('/api/documents', params={'kind': 'RESIM'}))['documents']] == [img_doc]

        # ---- Görünürlük: yalnızca ben (sistem yöneticisi de göremez) ve seçili roller
        secret = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'gizli.png', png(page(['Gizli maaş listesi'])))],
                                                    'title': 'Gizli', 'company_ids': [cid], 'visibility': 'PRIVATE'}))['ids'][0]
        ops = ok(a.post('/api/documents', json={'upload_ids': [upload(a, 'rol.txt', b'Idari rol belgesi')],
                                                 'title': 'Rol belgesi', 'visibility': 'ROLES', 'roles': ['İdari Personel']}))['ids'][0]
        assert a.post('/api/documents', json={'upload_ids': [upload(a, 'x.txt', b'x')], 'visibility': 'ROLES'}).status_code == 400
        sd = wait_ocr(a, secret)
        wait_ocr(a, ops)
        secret_file = sd['file'].split('/', 1)[1]
        assert a.get(f'/api/files/documents/{secret_file}').status_code == 200

    with TestClient(app) as admin:
        login(admin, 'admin@test', 'admin-sifre-1')
        ids = {x['id'] for x in ok(admin.get('/api/documents'))['documents']}
        assert secret not in ids and ops not in ids and img_doc in ids          # yönetici rolü seçilmedi
        assert admin.get(f'/api/documents/{secret}').status_code == 404
        assert admin.get(f'/api/files/documents/{secret_file}').status_code == 404
        assert admin.get(f'/api/files/{sd["thumb"]}').status_code == 404
        assert ok(admin.get('/api/documents', params={'q': 'maas'}))['documents'] == []
        co = ok(admin.get(f'/api/companies/{cid}'))
        assert secret not in {x['id'] for x in co['documents']}
        assert next(x for x in ok(admin.get('/api/companies')) if x['id'] == cid)['document_count'] == 2
        # yönetici başkasının evrakını düzenleyebilir ama görünürlüğünü değiştiremez
        body = {'title': 'Eylül faturası (düzeltildi)', 'company_ids': [cid, cid2], 'visibility': 'ALL'}
        ok(admin.put(f'/api/documents/{img_doc}', json=body))
        assert admin.put(f'/api/documents/{img_doc}', json={**body, 'visibility': 'PRIVATE'}).status_code == 403
        assert admin.delete(f'/api/companies/{cid}').status_code == 400        # bağlı evrak var

    with TestClient(app) as b:
        login(b, 'idari2', 'sifre-1234')
        ids = {x['id'] for x in ok(b.get('/api/documents'))['documents']}
        assert ops in ids and secret not in ids                                 # rol görür, gizli yok
        assert b.put(f'/api/documents/{ops}', json={'title': 'x', 'visibility': 'ALL'}).status_code == 403   # yükleyen değil
        assert b.delete(f'/api/documents/{ops}').status_code == 403
        assert [x['id'] for x in ok(b.get('/api/documents', params={'q': 'eylul faturasi duzeltildi'}))['documents']] == [img_doc]

    # ---- İmza talepleri: kısıtlı evrak bile imzacıya (modülü olmayan Pilot) açılır; imza doğrulanır
    with TestClient(app) as a:
        login(a, 'idari1', 'sifre-1234')
        people = {u['username']: u['id'] for u in ok(a.get('/api/people'))}
        r = ok(a.post(f'/api/documents/{secret}/signatures', json={'user_ids': [people['pilot'], people['idari2']], 'message': 'Lütfen imzalayın'}))
        assert len(r['created']) == 2
        assert ok(a.post(f'/api/documents/{secret}/signatures', json={'user_ids': [people['pilot']]}))['skipped'] == ['Pilot']
        sigs = {x['signer_name']: x['id'] for x in ok(a.get(f'/api/documents/{secret}'))['signatures']}
        sid, sid2 = sigs['Pilot'], sigs['Idari2']
    with TestClient(app) as pc:
        login(pc, 'pilot', 'sifre-1234')
        n = {x['key']: x for x in ok(pc.get('/api/notifications'))['items']}
        assert n['signature-pending']['href'] == f'#/sign/{sid}' and n['signature-pending']['count'] == 1
        s = ok(pc.get(f'/api/signatures/{sid}'))
        assert s['can_decide'] and s['document_title'] == 'Gizli' and s['message'] == 'Lütfen imzalayın'
        assert pc.get(f'/api/files/{s["file"]}').status_code == 200            # imzacı dosyayı görür
        assert pc.get(f'/api/documents/{secret}').status_code == 403            # ama Evrak modülüne giremez
        assert pc.get(f'/api/signatures/{sid2}').status_code in (403, 404)      # başkasının talebi
        assert pc.post(f'/api/signatures/{sid}/reject', json={'reason': ' '}).status_code == 400
        ok(pc.post(f'/api/signatures/{sid}/sign'))
        assert pc.post(f'/api/signatures/{sid}/sign').status_code == 400
        s = ok(pc.get(f'/api/signatures/{sid}'))
        assert s['status'] == 'IMZALANDI' and len(s['file_sha256']) == 64 and len(s['signature']) == 64
        assert ok(pc.get(f'/api/signatures/{sid}/verify')) == {'valid': True, 'file_unchanged': True, 'seal_ok': True}
        assert 'signature-pending' not in {x['key'] for x in ok(pc.get('/api/notifications'))['items']}
        assert ok(pc.get('/api/signatures?box=inbox'))[0]['status'] == 'IMZALANDI'
    with TestClient(app) as b:
        login(b, 'idari2', 'sifre-1234')
        assert b.post(f'/api/signatures/{sid}/sign').status_code in (403, 404)   # başkasının talebi (gizli evrak: 404)
        ok(b.post(f'/api/signatures/{sid2}/reject', json={'reason': 'Tutar hatalı'}))
        assert ok(b.get(f'/api/signatures/{sid2}'))['status'] == 'REDDEDILDI'
    with TestClient(app) as a:
        login(a, 'idari1', 'sifre-1234')
        sent = {x['id']: x for x in ok(a.get('/api/signatures?box=sent'))}
        assert sent[sid2]['reason'] == 'Tutar hatalı' and sent[sid]['status'] == 'IMZALANDI'
        sid3 = ok(a.post(f'/api/documents/{img_doc}/signatures', json={'user_ids': [people['idari2']]}))['created'][0]
        ok(a.post(f'/api/signatures/{sid3}/cancel'))
        assert ok(a.get(f'/api/signatures/{sid3}'))['status'] == 'IPTAL'
        # dosya imzadan sonra değişirse doğrulama bozulur
        path = os.path.join(tmp, 'uploads', ok(a.get(f'/api/documents/{secret}'))['file'])
        with open(path, 'ab') as f:
            f.write(b'x')
        v = ok(a.get(f'/api/signatures/{sid}/verify'))
        assert v == {'valid': False, 'file_unchanged': False, 'seal_ok': True}

    with TestClient(app) as a:
        login(a, 'idari1', 'sifre-1234')
        ok(a.post(f'/api/documents/{img_doc}/ocr'))
        assert wait_ocr(a, img_doc)['ocr_status'] == 'TAMAM'
        f = ok(a.get(f'/api/documents/{secret}'))['file']
        ok(a.delete(f'/api/documents/{secret}'))
        assert a.get(f'/api/documents/{secret}').status_code == 404
        assert not (app.state if False else os.path.exists(os.path.join(tmp, 'uploads', f)))
        assert ok(a.get('/api/documents', params={'q': 'maas'}))['documents'] == []
        assert a.delete(f'/api/companies/people/{pid}').status_code == 400    # kişiye bağlı evrak var
        ok(a.delete(f'/api/documents/{scan[0]}'))
        ok(a.delete(f'/api/companies/people/{pid}'))
    print('Firma ve evrak testleri geçti.')


if __name__ == '__main__':
    main()
