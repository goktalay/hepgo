"""Konuşma tanıma fabrikadaki GX10'da (ajan): merkez WAV'ı kısa ömürlü bağlantıyla paylaşır, ajan indirip işler, yalnız
metin döner — sesle yazdırma ve toplantı dökümü bu yoldan çalışır; iş bitince bağlantı kapanır. Ajan bağlı değilse /
eskiyse (bilinmeyen op) entegrasyon "Bağlı" görünmez ve anlaşılır neden yazar. Ajan op'u (speech.transcribe) da sahte
whisper ile denenir. Gerçek ajan / ekran kartı gerekmez.
Çalıştırma: .venv/bin/python -m tests.test_speech_agent
"""
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_AGENT_MODE='remote',
                  CAYMAZ_SPEECH='1', CAYMAZ_SPEECH_AGENT='1', CAYMAZ_AGENT_CENTRAL_URL='wss://merkez.example/ws/agent')

from fastapi.testclient import TestClient  # noqa: E402

from app import agent_ops, devices, document_media, integrations, meeting_audio  # noqa: E402
from app.main import app  # noqa: E402

MP3 = (Path(__file__).parent / 'fixtures' / 'speech-en.mp3').read_bytes()
agent = {'online': True, 'old': False, 'urls': [], 'got': []}
client = None


def fake_call(op, args=None, timeout=25):
    if agent['old']:
        raise RuntimeError(f'bilinmeyen op: {op}')
    if op == 'speech.status':
        return {'whisper': True, 'model': True, 'gpu': 'NVIDIA GB10', 'host': 'gx10-c58a'}
    if op == 'speech.transcribe':
        agent['urls'].append(args['url'])
        r = client.get(args['url'])            # ajan merkezden WAV'ı indirir
        assert r.status_code == 200 and r.content[:4] == b'RIFF', r.status_code
        agent['got'].append(len(r.content))
        return {'result': {'language': 'en'}, 'transcription': [
            {'text': ' Ask not what your country can do for you.', 'offsets': {'from': 0, 'to': 4000}},
            {'text': ' [BLANK_AUDIO]', 'offsets': {'from': 4000, 'to': 5000}},
            {'text': ' Ask what you can do for your country.', 'offsets': {'from': 5000, 'to': 10000}}]}
    raise AssertionError(op)


devices.online = lambda: agent['online']
devices.call_sync = fake_call


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def agent_op_test():
    """Ajan tarafı: speech.transcribe indirir, whisper'ı çalıştırır, yalnız metin + zaman döner."""
    tmp = Path(tempfile.mkdtemp())
    fake = tmp / 'whisper-cli'
    fake.write_text('#!/bin/bash\nwhile [ $# -gt 0 ]; do [ "$1" = -of ] && out=$2; shift; done\n'
                    'echo \'{"result":{"language":"tr"},"transcription":[{"text":" Merhaba","offsets":{"from":0,"to":900},'
                    '"tokens":[1,2,3]}]}\' > "$out.json"\n')
    fake.chmod(0o755)
    model = tmp / 'model.bin'
    model.write_bytes(b'x')
    old = document_media.WHISPER, document_media.WHISPER_MODEL, agent_ops._download
    document_media.WHISPER, document_media.WHISPER_MODEL = fake, model
    seen = []
    agent_ops._download = lambda url, dest: (seen.append(url), Path(dest).write_bytes(b'RIFF....'))
    try:
        out = agent_ops.OPS['speech.transcribe']({'url': '/api/agent/media/abc', 'lang': 'tr', 'seconds': 3})
        assert seen == ['https://merkez.example/api/agent/media/abc'], seen
        assert out == {'result': {'language': 'tr'}, 'transcription': [{'text': ' Merhaba', 'offsets': {'from': 0, 'to': 900}}]}, out
        try:
            agent_ops.OPS['speech.transcribe']({'url': 'https://saldirgan.example/x'})
            raise AssertionError('dış adres kabul edildi')
        except RuntimeError:
            pass
        st = agent_ops.OPS['speech.status']({})
        assert st['whisper'] and st['model'] and st['host']
    finally:
        document_media.WHISPER, document_media.WHISPER_MODEL, agent_ops._download = old
        shutil.rmtree(tmp)


def main():
    global client
    agent_op_test()
    with TestClient(app) as c:
        client = c
        ok(c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        assert document_media.on_agent()
        assert ok(c.post('/api/system/integrations/speech/test', json={}))['message'].startswith('GX10 hazır · NVIDIA GB10')
        assert document_media.whisper_available() and ok(c.get('/api/auth/me'))['speech'] is True
        assert c.get('/api/agent/media/uydurma').status_code == 404

        # Sesle yazdırma GX10'da
        d = ok(c.post('/api/system/dictate?lang=en', files={'file': ('d.mp3', MP3, 'audio/mpeg')}))
        assert 'Ask not what your country' in d['text'] and 'BLANK' not in d['text'], d
        assert agent['got'] and agent['got'][0] > 100_000                       # 16 kHz WAV indirildi
        assert c.get(agent['urls'][-1]).status_code == 404                      # iş bitince bağlantı kapandı

        # Toplantı kaydı GX10'da metne çevrilir
        uid = ok(c.post('/api/users', json={'username': 'ayse', 'full_name': 'Ayşe', 'roles': ['Pilot'], 'password': 'sifre-1234'}))['id']
        start = datetime.now() + timedelta(minutes=30)
        mid = ok(c.post('/api/meetings', json={'title': 'GX10', 'starts_at': start.replace(microsecond=0).isoformat(),
                                               'remind_min': 15, 'user_ids': [uid]}))['id']
        ok(c.post(f'/api/meetings/{mid}/start'))
        aid = ok(c.post(f'/api/meetings/{mid}/audio/start?ext=mp3'))['id']
        ok(c.post(f'/api/meetings/{mid}/audio/{aid}/chunk?seq=0', content=MP3))
        ok(c.post(f'/api/meetings/{mid}/audio/{aid}/stop'))
        ok(c.post(f'/api/meetings/{mid}/end'))
        if meeting_audio.available():
            for _ in range(120):
                s = ok(c.get(f'/api/meetings/{mid}/summary'))
                if s['process_status'] != 'ISLENIYOR':
                    break
                time.sleep(0.5)
            assert s['process_status'] == 'TAMAM', s.get('process_error')
            assert [x['text'] for x in s['segments']] == ['Ask not what your country can do for you.',
                                                          'Ask what you can do for your country.'], s['segments']

        # Ajan eski sürüm → anlaşılır neden, kullanılamaz
        agent['old'] = True
        t = ok(c.post('/api/system/integrations/speech/test', json={}))
        assert t['ok'] is False and 'Ajan güncel değil' in t['message'], t
        assert not document_media.whisper_available() and ok(c.get('/api/auth/me'))['speech'] is False
        # Ajan bağlı değil
        agent['old'], agent['online'] = False, False
        t = ok(c.post('/api/system/integrations/speech/test', json={}))
        assert t['ok'] is False and 'bağlı değil' in t['message'], t
        g = next(g for g in ok(c.get('/api/system/integrations'))['groups'] if g['key'] == 'speech')
        assert g['configured'] and g['online'] is False and [f['key'] for f in g['fields']] == ['SPEECH_ENABLED', 'SPEECH_ON_AGENT']
        # Ajan geri gelince
        agent['online'] = True
        assert ok(c.post('/api/system/integrations/speech/test', json={}))['ok'] is True
        assert integrations.config.SPEECH_ON_AGENT is True
    print('GX10 (ajan) konuşma tanıma testleri geçti.')


if __name__ == '__main__':
    main()
