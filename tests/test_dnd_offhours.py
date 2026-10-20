"""Kişisel Ayarlar: Rahatsız etmeyin › "Mesai sonrası" (sunucu bastırma kuralı) + Mail Hesaplarım "Yeniden bağlan".

- dur='offhours': kişisel saatler (varsayılan hafta içi 08:30–18:00; hafta sonu tüm gün), sistem mesai programı kayıtlıysa o
  program + tatiller; workSrc='custom' ise kişisel saatler; eski süreli / sürekli kipler aynen.
- Süresi dolan Google hesabı: needs_reauth=true; yetki adresi aynı hesap için login_hint taşır.

Çalıştırma: .venv/bin/python -m tests.test_dnd_offhours
"""
import json
import os
import tempfile
from datetime import datetime

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
                  CAYMAZ_GOOGLE_CLIENT_ID='sahte-id', CAYMAZ_GOOGLE_CLIENT_SECRET='sahte-gizli')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db, mail, worktime  # noqa: E402
from app.main import app  # noqa: E402

PZT_10 = datetime(2026, 10, 19, 10, 0)    # Pazartesi mesai içi
PZT_19 = datetime(2026, 10, 19, 19, 0)    # Pazartesi mesai sonrası
SALI_07 = datetime(2026, 10, 20, 7, 0)    # Salı mesai öncesi
CMT_12 = datetime(2026, 10, 24, 12, 0)    # Cumartesi öğle
PZT_1745 = datetime(2026, 10, 19, 17, 45)  # kişisel (18:00) içinde, sistem (17:30) dışında


def prefs(**dnd):
    return json.dumps({'settings': {'dnd': dnd}})


def reset_cache():
    auth._WORK_CACHE.update(t=0.0, v=None)


def main():
    with TestClient(app) as c:
        # ---- kişisel saatler (sistem programı kayıtlı değil)
        reset_cache()
        p = prefs(calls=True, messages=False, dur='offhours')
        assert auth.dnd_state(p, PZT_10) == {'calls': False, 'messages': False}, 'mesai içinde açık olmalı'
        assert auth.dnd_state(p, PZT_19)['calls'], 'mesai sonrası kapalı olmalı'
        assert auth.dnd_state(p, SALI_07)['calls'], 'ertesi mesai başlangıcına kadar kapalı olmalı'
        assert auth.dnd_state(p, CMT_12)['calls'], 'hafta sonu tüm gün kapalı olmalı'
        assert not auth.dnd_state(p, PZT_1745)['calls'], 'varsayılan bitiş 18:00'
        assert not auth.dnd_state(p, PZT_19)['messages'], 'seçilmeyen kanal açık kalır'
        p2 = prefs(calls=True, messages=True, dur='offhours', work={'from': '09:00', 'to': '17:00'})
        assert auth.dnd_state(p2, datetime(2026, 10, 19, 8, 30)) == {'calls': True, 'messages': True}
        assert auth.dnd_state(p2, datetime(2026, 10, 19, 16, 59)) == {'calls': False, 'messages': False}
        assert auth.dnd_state(prefs(calls=False, messages=False, dur='offhours'), PZT_19) == {'calls': False, 'messages': False}
        # eski kipler bozulmadı
        assert auth.dnd_state(prefs(calls=True, dur='always'), PZT_10)['calls']
        assert not auth.dnd_state(prefs(calls=True, dur='1', until='2026-10-19T09:00:00'), PZT_10)['calls']
        assert auth.dnd_state(prefs(calls=True, dur='1', until='2026-10-19T11:00:00'), PZT_10)['calls']

        # ---- sistem mesai programı (Program Ayarları) kayıtlı: Pzt–Cum 08:30–17:30 + tatil
        r = c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'})
        assert r.status_code == 200, r.text
        assert c.get('/api/worktime/schedule').json()['defined'] is False
        days = {str(d): {'on': d <= 5, 'from': '08:30', 'to': '17:30'} for d in range(1, 8)}
        r = c.put('/api/worktime/schedule', json={'days': days, 'holidays': ['2026-10-29'], 'overtime_multiplier': 1.5})
        assert r.status_code == 200, r.text
        assert c.get('/api/worktime/schedule').json()['defined'] is True
        reset_cache()
        assert auth.dnd_state(p, PZT_1745)['calls'], 'sistem programında 17:30 sonrası mesai dışı'
        assert not auth.dnd_state(p, PZT_10)['calls']
        assert auth.dnd_state(p, datetime(2026, 10, 29, 11, 0))['calls'], 'tatil günü tüm gün kapalı'
        pc = prefs(calls=True, dur='offhours', workSrc='custom')
        assert not auth.dnd_state(pc, PZT_1745)['calls'], 'kendi saatlerim seçiliyse sistem programı yok sayılır'
        assert worktime.is_off_hours_custom(CMT_12) and not worktime.is_off_hours_custom(PZT_10)

        # ---- Mail Hesaplarım için kullanıcı kimliği
        with db.connect() as conn:
            uid = conn.execute("SELECT id FROM users WHERE username = 'admin@test'").fetchone()[0]

        # ---- Mail: süresi dolan Google hesabı
        msg = f'Google {mail.REAUTH_MARK}; Mail Hesaplarım’dan yeniden bağlayın.'
        with db.connect() as conn:
            conn.execute("INSERT INTO mail_boxes (user_id, email, provider, auth_type, secret, last_error, sync_error, created_at) "
                         "VALUES (?, 'ornek@gmail.com', 'gmail', 'google', 'x', ?, ?, datetime('now'))", (uid, msg, msg))
            conn.execute("INSERT INTO mail_boxes (user_id, email, provider, auth_type, secret, last_error, sort, created_at) "
                         "VALUES (?, 'b@firma.com', 'imap', 'password', 'x', 'IMAP girişi reddedildi', 1, datetime('now'))", (uid,))
            conn.commit()
        boxes = {b['email']: b for b in c.get('/api/mail/boxes').json()['boxes']}
        assert boxes['ornek@gmail.com']['needs_reauth'] is True
        assert boxes['b@firma.com']['needs_reauth'] is False, 'şifreli hesapta yeniden bağlanma yok'
        assert not mail.needs_reauth({'auth_type': 'google', 'sync_error': 'Kişiler: bu izin verilmemiş'})
        url = c.get('/api/mail/oauth/google/start', params={'hint': 'ornek@gmail.com'}).json()['url']
        assert 'login_hint=ornek%40gmail.com' in url, url
        assert 'login_hint' not in c.get('/api/mail/oauth/google/start').json()['url']
    print('test_dnd_offhours: tamam')


if __name__ == '__main__':
    main()
