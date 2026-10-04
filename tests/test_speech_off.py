"""Konuşma Tanıma entegrasyonu KAPALI (varsayılan): sesler yalnız kaydedilir — toplantı kaydı alınır ama metne çevrilmez,
konuşmacı çıkarılmaz; evrak sesi metinsiz TAMAM olur; sesle yazdırma kapalı (me.speech false, /dictate 503);
entegrasyondan açılınca me.speech true olur. Whisper çalıştırılmaz (hızlı).
Çalıştırma: .venv/bin/python -m tests.test_speech_off
"""
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.pop('CAYMAZ_SPEECH', None)
os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from fastapi.testclient import TestClient  # noqa: E402

from app import config, document_media, meeting_audio  # noqa: E402
from app.main import app  # noqa: E402

MP3 = (Path(__file__).parent / 'fixtures' / 'speech-en.mp3').read_bytes()
calls = []
document_media.subprocess.run = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError('Whisper çalıştırılmamalı'))


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def main():
    assert config.SPEECH_ENABLED is False and not document_media.whisper_available() and not meeting_audio.available()
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert ok(a.get('/api/auth/me'))['speech'] is False
        r = a.post('/api/system/dictate?lang=tr', files={'file': ('d.mp3', MP3, 'audio/mpeg')})
        assert r.status_code == 503 and 'kapalı' in r.json()['detail'], r.text
        t = ok(a.post('/api/system/integrations/speech/test', json={}))
        assert t['ok'] is False and 'Kapalı' in t['message']

        # Toplantı: kayıt alınır, bitince metne çevrilmez, hata da olmaz
        uid = ok(a.post('/api/users', json={'username': 'ayse', 'full_name': 'Ayşe', 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
        start = datetime.now() + timedelta(minutes=1)
        mid = ok(a.post('/api/meetings', json={'title': 'Kayıt', 'starts_at': start.replace(microsecond=0).isoformat(),
                                               'remind_min': 15, 'user_ids': [uid]}))['id']
        ok(a.post(f'/api/meetings/{mid}/start'))
        assert ok(a.get(f'/api/meetings/{mid}/room'))['audio_available'] is False
        aid = ok(a.post(f'/api/meetings/{mid}/audio/start?ext=mp3'))['id']
        ok(a.post(f'/api/meetings/{mid}/audio/{aid}/chunk?seq=0', content=MP3))
        ok(a.post(f'/api/meetings/{mid}/audio/{aid}/stop'))
        ok(a.post(f'/api/meetings/{mid}/end'))
        s = ok(a.get(f'/api/meetings/{mid}/summary'))
        assert s['process_status'] == 'TAMAM' and not s.get('process_error') and not s['segments'] and not s['speakers'], s
        assert ok(a.get(f'/api/meetings/{mid}/room'))['recordings'] >= 1   # ses saklandı

        # Evrak: ses dosyası metinsiz (YOK), süresi bilinir, hata yok
        up = ok(a.post('/api/uploads', json={'kind': 'documents', 'file_name': 'kayit.mp3', 'size': len(MP3)}))['upload_id']
        ok(a.put(f'/api/uploads/{up}?offset=0', content=MP3))
        did = ok(a.post('/api/documents', json={'upload_ids': [up], 'kind': 'SES'}))['ids'][0]
        for _ in range(100):
            d = ok(a.get(f'/api/documents/{did}'))
            if d['ocr_status'] not in ('BEKLIYOR', 'ISLENIYOR'):
                break
            time.sleep(0.2)
        assert d['ocr_status'] in ('TAMAM', 'YOK') and d['duration'] and not d.get('ocr_text') and not d.get('ocr_error'), d

        # Modül Ayarları: entegrasyon çalışmıyorken hiçbir modülde açılamaz
        v = ok(a.get('/api/system/speech'))
        assert v['integration'] is False and {f['key'] for f in v['features']} == {'meetings', 'meet', 'calls', 'documents', 'dictation'}
        assert not any(f['active'] for f in v['features'])
        r = a.put('/api/system/speech/meetings', json={'on': True})
        assert r.status_code == 400 and 'entegrasyonu çalışmıyor' in r.json()['detail']
        assert a.put('/api/system/speech/yok', json={'on': False}).status_code == 404
        ok(a.put('/api/system/speech/meetings', json={'on': False}))   # kapatmak her zaman serbest

        # Açılınca: me.speech (Whisper kuruluysa) true
        ok(a.put('/api/system/integrations/speech', json={'values': {'SPEECH_ENABLED': '1'}}))
        assert config.SPEECH_ENABLED is True
        installed = document_media.WHISPER.exists() and document_media.WHISPER_MODEL.exists()
        assert ok(a.get('/api/auth/me'))['speech'] is installed
        if installed:   # modül anahtarları entegrasyondan bağımsız kapatılır / açılır
            assert meeting_audio.available() is False   # toplantılar az önce kapatıldı
            ok(a.put('/api/system/speech/meetings', json={'on': True}))
            assert meeting_audio.available() == meeting_audio.MODEL.exists()
            ok(a.put('/api/system/speech/dictation', json={'on': False}))
            assert ok(a.get('/api/auth/me'))['speech'] is False
            assert a.post('/api/system/dictate?lang=tr', files={'file': ('d.mp3', MP3, 'audio/mpeg')}).status_code == 503
            ok(a.put('/api/system/speech/dictation', json={'on': True}))
            assert ok(a.get('/api/auth/me'))['speech'] is True
        ok(a.put('/api/system/integrations/speech', json={'values': {'SPEECH_ENABLED': '0'}}))
        assert ok(a.get('/api/auth/me'))['speech'] is False
    assert not calls
    print('Konuşma tanıma kapalı testleri geçti.')


if __name__ == '__main__':
    main()
