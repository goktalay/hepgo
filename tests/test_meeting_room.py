"""Toplantı ekranı: başlat / bitir yetkisi, notlar yalnızca toplantı sürerken, parça parça ses kaydı, bitince konuşma →
metin + konuşmacılara ayırma, kişiye atama → ses profili → sonraki toplantıda otomatik tanıma, özet (notlar dahil).

Çalıştırma: .venv/bin/python -m tests.test_meeting_room   (Whisper ve ses modeli kuruluysa ses bölümü de çalışır)
"""
import io
import os
import tempfile
import time
import wave
from datetime import datetime, timedelta

tmp = tempfile.mkdtemp()
os.environ.update(CAYMAZ_DATA_DIR=tmp, CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1')

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import meeting_audio  # noqa: E402
from app.document_media import _to_wav  # noqa: E402
from app.main import app  # noqa: E402

HERE = os.path.dirname(__file__)


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def two_voices():
    """Aynı konuşma: normal ve perdesi değiştirilmiş (farklı kişi gibi), art arda — 16 kHz WAV baytları."""
    wav = os.path.join(tmp, 'src.wav')
    _to_wav(os.path.join(HERE, 'fixtures', 'speech-en.mp3'), wav)
    sig = meeting_audio.read_wav(wav)
    idx = np.arange(0, len(sig) - 1, 1.3)
    other = np.interp(idx, np.arange(len(sig)), sig).astype(np.float32)
    gap = np.zeros(8000, np.float32)
    full = np.concatenate([sig, gap, other, gap, sig, gap, other])
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.clip(full, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def meeting(c, ids, title):
    start = datetime.now() + timedelta(minutes=30)
    return ok(c.post('/api/meetings', json={'title': title, 'starts_at': start.replace(microsecond=0).isoformat(),
                                            'remind_min': 15, 'user_ids': ids}))['id']


def main():
    with TestClient(app) as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        ids = {u: ok(a.post('/api/users', json={'username': u, 'full_name': u.title(), 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
               for u in ('ali', 'ayse', 'veli')}
    with TestClient(app) as al, TestClient(app) as ay, TestClient(app) as ve:
        for c, u in ((al, 'ali'), (ay, 'ayse'), (ve, 'veli')):
            ok(c.post('/api/auth/login', json={'username': u, 'password': 'sifre-1234'}))
        mid = meeting(al, [ids['ayse']], 'Üretim planlama')
        r = ok(ay.get(f'/api/meetings/{mid}/room'))
        assert r['state'] == 'BASLAMADI' and len(r['people']) == 2
        assert ve.get(f'/api/meetings/{mid}/room').status_code == 404                              # davetli değil
        assert ay.put(f'/api/meetings/{mid}/notes', json={'body': 'x'}).status_code == 400          # başlamadan not yok
        assert ay.post(f'/api/meetings/{mid}/start').status_code == 403                           # yalnızca düzenleyen
        assert al.post(f'/api/meetings/{mid}/audio/start').status_code == 400                     # başlamadan kayıt yok
        assert ok(al.post(f'/api/meetings/{mid}/start'))['state'] == 'DEVAM'
        ok(ay.put(f'/api/meetings/{mid}/notes', json={'body': '- Ayşe raporu cuma günü teslim edecek\n- Filament siparişi verilecek'}))
        ok(al.put(f'/api/meetings/{mid}/notes', json={'body': 'Yazıcı bakımına karar verildi.'}))
        people = {p['full_name']: p for p in ok(al.get(f'/api/meetings/{mid}/room'))['people']}
        assert people['Ayse']['online'] and ok(ay.get(f'/api/meetings/{mid}/room'))['my_note'].startswith('- Ayşe')
        audio = meeting_audio.available()
        if audio:
            aid = ok(al.post(f'/api/meetings/{mid}/audio/start?ext=webm'))['id']
            data = two_voices()
            parts = [data[i:i + 200_000] for i in range(0, len(data), 200_000)]
            for i, part in enumerate(parts):
                assert ok(al.post(f'/api/meetings/{mid}/audio/{aid}/chunk?seq={i}', content=part))['chunks'] == i + 1
            assert ok(al.post(f'/api/meetings/{mid}/audio/{aid}/chunk?seq=0', content=parts[0])).get('skipped')   # tekrar
            ok(al.post(f'/api/meetings/{mid}/audio/{aid}/stop'))
        assert ay.post(f'/api/meetings/{mid}/end').status_code == 403
        assert al.get(f'/api/meetings/{mid}/summary').status_code == 400                          # bitmeden özet yok
        ok(al.post(f'/api/meetings/{mid}/end'))
        for _ in range(240):
            s = ok(al.get(f'/api/meetings/{mid}/summary'))
            if s['process_status'] != 'ISLENIYOR':
                break
            time.sleep(1)
        assert s['process_status'] == 'TAMAM', s.get('process_error')
        assert [n['full_name'] for n in s['notes']] == ['Ali', 'Ayse']
        assert any('Filament' in x['text'] for x in s['points']['actions'])
        assert any('karar' in x['text'] for x in s['points']['decisions'])
        # Toplantı bittikten sonra: herkes kendi notunu, düzenleyen katılımcıların notlarını düzeltebilir
        ok(ay.put(f'/api/meetings/{mid}/notes', json={'body': '- Ayşe raporu pazartesi teslim edecek\n- Filament siparişi verilecek'}))
        ok(al.put(f'/api/meetings/{mid}/notes', json={'body': 'Yazıcı bakımına karar verildi. Filament 10 kg.', 'user_id': ids['ayse']}))
        assert ay.put(f'/api/meetings/{mid}/notes', json={'body': 'x', 'user_id': ids['ali']}).status_code == 403   # düzenleyen değil
        n = {x['full_name']: x for x in ok(al.get(f'/api/meetings/{mid}/summary'))['notes']}
        assert n['Ayse']['body'].endswith('10 kg.') and n['Ayse']['edited_by_name'] == 'Ali'
        if audio:
            assert s['segments'] and all(x['text'] for x in s['segments'])
            assert len(s['speakers']) == 2, [(x['label'], x['seconds']) for x in s['speakers']]
            assert all(x['user_id'] is None and x['label'].startswith('Tanımsız kişi') for x in s['speakers'])
            sp = s['speakers'][0]
            assert al.get(f'/api/meetings/{mid}/speakers/{sp["id"]}/sample').headers['content-type'] == 'audio/wav'
            assert ay.put(f'/api/meetings/{mid}/speakers/{sp["id"]}', json={'user_id': ids['ali']}).status_code == 403
            s = ok(al.put(f'/api/meetings/{mid}/speakers/{sp["id"]}', json={'user_id': ids['ali']}))
            assert next(x for x in s['speakers'] if x['id'] == sp['id'])['full_name'] == 'Ali'
            assert all(seg['speaker'] in ('Ali', 'Tanımsız kişi 2', 'Tanımsız kişi 1') for seg in s['segments'])
            # Sonraki toplantı: aynı ses otomatik tanınır
            mid2 = meeting(al, [ids['ayse']], 'İkinci toplantı')
            ok(al.post(f'/api/meetings/{mid2}/start'))
            aid2 = ok(al.post(f'/api/meetings/{mid2}/audio/start'))['id']
            ok(al.post(f'/api/meetings/{mid2}/audio/{aid2}/chunk?seq=0', content=data))
            ok(al.post(f'/api/meetings/{mid2}/end'))
            for _ in range(240):
                s2 = ok(al.get(f'/api/meetings/{mid2}/summary'))
                if s2['process_status'] != 'ISLENIYOR':
                    break
                time.sleep(1)
            assert s2['process_status'] == 'TAMAM', s2.get('process_error')
            auto = [x for x in s2['speakers'] if x['user_id'] == ids['ali']]
            assert auto and auto[0]['auto'], [(x['label'], x['score']) for x in s2['speakers']]
        else:
            print('(Whisper / ses modeli yok: ses bölümü atlandı)')
    print('Toplantı ekranı testleri geçti.')


if __name__ == '__main__':
    main()
