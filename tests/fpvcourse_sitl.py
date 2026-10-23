"""§47 hazır FPV parkuru — GERÇEK SITL doğrulaması: kurucu + 1 yapay zekâ pilot (kopter) FPV parkur yarışı; kurucu uçmaz. Bot KENDİ ArduCopter
SITL'inde yarış başlayınca GUIDED + ARM + kalkış (parkurun başlangıç kapısı yüksekliği) yapar ve 5 Hz hız komutlarıyla yarış hattını izler; kapı
geçişleri sunucunun tele kancasında `ParkurIzleyici` ile (yön + düzlem + açıklık) doğrulanır. Beklenen: en az 3 kapı (`ring` olayı).
Kendi başlattığı SITL süreçleri PID ile denetlenir/kapatılır (başka SITL'lere dokunulmaz).
Çalıştırma: .venv/bin/python -m tests.fpvcourse_sitl   (FPV_PARKUR=stadium, BOT_SEVIYE=hard)
"""
import json
import os
import signal
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='fpvcourse-sitl-'), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE='41850', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='', SIM_MATCH_MAX_SESSIONS='4', SIM_PARAM_DUMP_S='0')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/fabrika-yonetim/data/sitl')

from fastapi.testclient import TestClient  # noqa: E402

from app import flightsim  # noqa: E402
from app.main import app  # noqa: E402
from tests.match_sitl_e2e import _yasiyor, bekle  # noqa: E402
from tests.test_flightsim_match import Kullanici, ok  # noqa: E402

M = '/api/drone/sim/matches'
MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
pids = set()


def main():
    t0 = time.time()
    seviye = os.environ.get('BOT_SEVIYE', 'hard')
    cid = os.environ.get('FPV_PARKUR', 'stadium')
    hedef = int(os.environ.get('FPV_KAPI', '3'))
    try:
        with TestClient(app, base_url='https://testserver') as tc:
            a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
            c1 = ok(a.post('/api/drone/centers', json={'name': 'SITL FPV', 'lat': MERKEZ['lat'], 'lon': MERKEZ['lon'], 'alt': 900}))
            ayar = {'type': 'multirotor', 'center_id': c1['id'], 'world': {'mode': 'procedural', 'seed': 3}}
            mt = ok(a.post(M, json={'settings': ayar, 'kind': 'fpv', 'fpv': {'course_id': cid, 'laps': 1, 'crash_rule': 'continue', 'time_limit_min': 5},
                                    'invite': [], 'bots': [{'level': seviye}]}), 201)
            mid = mt['id']
            bot = next(p for p in mt['players'] if p['is_bot'])
            print(f"  karşılaşma {mid} · parkur {cid} · bot {bot['name']} · {len(mt['rings'])} kontrol noktası", flush=True)
            with a.websocket_connect(f'/ws/drone/match/{mid}') as wa:
                json.loads(wa.receive_text())
                d = bekle(lambda: (lambda x: x if all(p['session_id'] for p in x['players']) else None)(ok(a.get(f'{M}/{mid}'))), 40)
                assert d, ok(a.get(f'{M}/{mid}'))
                sids = {p['id']: p['session_id'] for p in d['players']}
                ss = {u: flightsim.MANAGER.get(s) for u, s in sids.items()}
                for s in ss.values():
                    assert bekle(lambda s=s: s.state in ('HAZIR', 'HATA'), 120), s.state
                    assert s.state == 'HAZIR', s.sitl
                    if s.sitl.get('pid'):
                        pids.add(int(s.sitl['pid']))
                    assert bekle(lambda s=s: s._heartbeat_alindi, 120), ('SITL kalp atışı yok', s.sitl)
                sb = ss[bot['id']]
                assert sb.world.get('fpv_course') == cid
                print(f'  SITL hazır ({time.time() - t0:.0f} sn), pid {sorted(pids)}', flush=True)
                wa.send_text(json.dumps({'t': 'ready'}))
                gorulen = []

                def ws_bekle(kosul, sn):
                    bitis = time.time() + sn
                    while time.time() < bitis:
                        m = json.loads(wa.receive_text())
                        gorulen.append(m)
                        if kosul(m):
                            return m
                    return None
                assert ws_bekle(lambda m: m['t'] == 'state' and m['state'] == 'YARIS', 40)
                print(f'  YARIS ({time.time() - t0:.0f} sn) — bot kalkıyor', flush=True)
                son = [0.0]

                def durum(m):
                    if m['t'] in ('ring', 'miss', 'hit', 'lap', 'sector') and m.get('id') == bot['id']:
                        print(f"  bot {m['t']} " + json.dumps({k: m.get(k) for k in ('i', 'gate', 'lap', 'sector', 's', 'elapsed_s', 'mat', 'pen_s') if m.get(k) is not None}), flush=True)
                    if time.time() - son[0] > 10:
                        son[0] = time.time()
                        te = sb.tele
                        print(f"    tele: kip {te.get('mode')} armed {te.get('armed')} alt {te.get('alt_rel')} gs {te.get('groundspeed')}", flush=True)
                    gecen = [x for x in gorulen if x['t'] == 'ring' and x['id'] == bot['id']]
                    return m['t'] == 'result' or len(gecen) >= max(hedef, 1) + 3
                res = ws_bekle(durum, 360)
                ringev = [m['i'] for m in gorulen if m['t'] == 'ring' and m['id'] == bot['id']]
                miss = [m['i'] for m in gorulen if m['t'] == 'miss' and m['id'] == bot['id']]
                assert len(ringev) >= hedef, (ringev, miss, sb.tele)
                print(f"  bot {len(ringev)} kapı geçti {ringev} · kaçırılan {miss} · sonuç: " + (f"{res['result']['reason']}" if res and res['t'] == 'result' else 'iptal'), flush=True)
                if not res or res['t'] != 'result':
                    ok(a.post(f'{M}/{mid}/cancel'))
                assert bekle(lambda: all(flightsim.MANAGER.get(x) is None for x in sids.values()), 60)
    finally:
        acik = [p for p in pids if _yasiyor(p)]
        for p in acik:
            try:
                os.kill(p, signal.SIGTERM)
            except OSError:
                pass
    assert not acik, f'kapanmayan SITL: {acik}'
    print(f'fpvcourse_sitl: TAMAM ({time.time() - t0:.0f} sn)')


if __name__ == '__main__':
    main()
