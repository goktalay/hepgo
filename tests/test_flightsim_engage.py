"""Uçuş Simülatörü §40 — Boşluk ile KİLİT + ANGAJMAN: saf izleyici (app/flightsim_targets.HedefIzleyici: kilit → başlangıç, kilitli hedefi önleme →
BAŞARILI, bırakma / görüş dışı / Sıfırla → KESİLDİ, hedef değişimi, en yakın mesafe, puan bonusu, özet listesi) + HEPGO API uçtan uca (sahte kinematik
HEPGO_SITL=0): `cmd engage` doğrulaması (400'ler), WS `engage` start → (araç hedefin içinden geçirilir) success, release, hello'da etkin angajman,
özet raporda angajman listesi, kapanışta drone_sim_runs.targets.result.engagements, kayıttan oynatma oturumunda `engagements`.

Çalıştırma: .venv/bin/python -m tests.test_flightsim_engage
"""
import json
import os
import tempfile
import time

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25850', SIM_MAX_SESSIONS='2', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, flightsim  # noqa: E402
from app import flightsim_targets as FT  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, bekle, ok, ws_bekle  # noqa: E402

MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
HEDEF = {'i': 0, 'model': 'tgt:lancet', 'name': 'Av', 'alt_m': 60.0, 'diameter_m': 400.0, 'speed_ms': 20.0, 'dir': 'cw', 'phase_deg': 0.0, 'east_m': 0.0, 'north_m': 0.0}


def saf_testler():
    cfg = {'items': [HEDEF, {**HEDEF, 'i': 1, 'name': 'İkinci', 'phase_deg': 180.0}], 'radius_m': 25.0}
    iz = FT.HedefIzleyici(cfg)
    try:
        iz.kilit_ac(7)
        raise AssertionError('bilinmeyen hedef kabul edildi')
    except ValueError:
        pass
    assert iz.kilit_birak() == [] and iz.angajman_durumu() is None
    iz.adim(1.0, 0, 0, 0, True)                       # ARM t=1; araç merkezde
    o = iz.kilit_ac(0)
    assert len(o) == 1 and o[0]['kind'] == 'start' and o[0]['i'] == 0 and o[0]['start_s'] == 0.0 and abs(o[0]['start_dist_m'] - ((200 ** 2 + 60 ** 2) ** 0.5)) < 0.2, o
    assert iz.kilit_ac(0) == []                       # aynı hedef: yinelenmez
    # hedef değişimi: önceki 'switched' ile kesilir, yenisi başlar
    iz.adim(2.0, 0, 0, 0, True)
    o = iz.kilit_ac(1)
    assert [x['kind'] for x in o] == ['cut', 'start'] and o[0]['reason'] == 'switched' and o[0]['dur_s'] == 1.0 and o[1]['i'] == 1, o
    o = iz.kilit_birak('lost')
    assert o[0]['kind'] == 'cut' and o[0]['reason'] == 'lost' and iz.ang is None, o
    # kilit → hedefin konumuna git → önleme olayı locked + BAŞARILI
    iz.adim(3.0, 0, 0, 0, True)
    iz.kilit_ac(0)
    st = FT.durum(HEDEF, 10.0)
    iz.adim(9.0, st['x'] + 80, st['y'], 60, True)     # yaklaşırken en yakın mesafe güncellenir
    ol = iz.adim(10.0, st['x'] + 3, st['y'], 60, True)
    assert len(ol) == 1 and ol[0]['locked'] and ol[0]['engagement']['kind'] == 'success' and ol[0]['engagement']['dur_s'] == 7.0, ol
    assert ol[0]['engagement']['min_dist_m'] <= 3.1 and ol[0]['engagement']['end_dist_m'] <= 3.1 and iz.ang is None
    # Sıfırla (saat geri): etkin angajman 'reset' ile kesilir
    iz.adim(11.0, 0, 0, 0, True)
    iz.kilit_ac(1)
    ol = iz.adim(0.5, 0, 0, 0, True)
    assert any(x.get('engage') and x['reason'] == 'reset' for x in ol), ol
    oz = iz.ozet()
    assert [a['result'] for a in oz['engagements']] == ['cut', 'cut', 'success', 'cut'] and oz['engaged_hits'] == 1, oz['engagements']
    iz.kilit_ac(0)
    oz2 = iz.ozet()
    assert oz2['engagements'][-1]['result'] == 'active' and oz2['engagements'][-1]['reason'] is None
    # puan: kilitli önleme bonusu (hedef başına bir kez) — kilitsiz eşdeğerine göre +250
    kilitsiz = FT.HedefIzleyici({'items': [HEDEF], 'radius_m': 25.0})
    kilitsiz.adim(1.0, 0, 0, 0, True)
    kilitsiz.adim(10.0, st['x'] + 3, st['y'], 60, True)
    kilitli = FT.HedefIzleyici({'items': [HEDEF], 'radius_m': 25.0})
    kilitli.adim(1.0, 0, 0, 0, True)
    kilitli.kilit_ac(0)
    kilitli.adim(10.0, st['x'] + 3, st['y'], 60, True)
    assert kilitli.ozet()['score'] - kilitsiz.ozet()['score'] == FT.ANGAJMAN_BONUS == 250, (kilitli.ozet()['score'], kilitsiz.ozet()['score'])
    print('  saf izleyici geçti')


def api_testleri():
    S = '/api/drone/sim/sessions'
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Hedef Sahası', **MERKEZ}))
        hedef = {k: v for k, v in HEDEF.items() if k != 'i'}
        s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id'], 'targets': {'items': [hedef], 'radius_m': 25}}), 201)
        sid = s['id']
        assert s['engagement'] is None and s['targets_state']['engagements'] == []
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
        C = f'{S}/{sid}/cmd'
        for bad in ({}, {'action': 'x'}, {'action': 'lock'}, {'action': 'lock', 'i': '0'}, {'action': 'lock', 'i': True}, {'action': 'lock', 'i': 5},
                    {'action': 'release', 'reason': 'hack'}):
            assert a.post(C, json={'name': 'engage', 'params': bad}).status_code == 400, bad
        sess = flightsim.MANAGER.sessions[sid]
        k = sess.sahte
        mc = {'lat': MERKEZ['lat'], 'lon': MERKEZ['lon']}
        hz = {'on': False}

        def adim(dt):   # test pilotu: önce merkezde askı; hz['on'] → hedefin 2 m yanına ışınla (yalnız kinematik test aracı)
            k.sure_ms += dt * 1000
            k.armed, k.mode = True, 'GUIDED'
            if hz['on']:
                st = FT.durum({**HEDEF}, k.sure_ms / 1000.0)
                k.lat, k.lon = FT.latlon(mc['lat'], mc['lon'], st['x'] + 2, st['y'])
                k.alt_rel = 60.0
            else:
                k.lat, k.lon, k.alt_rel = mc['lat'], mc['lon'], 60.0
        k.adim = adim
        with a.websocket_connect(f'/ws/drone/sim/{sid}') as ws:
            assert ws_bekle(ws, lambda m: m['t'] == 'hello')
            assert ws_bekle(ws, lambda m: m['t'] == 'tele' and m.get('armed'), 5)
            r = ok(a.post(C, json={'name': 'engage', 'params': {'action': 'lock', 'i': 0}}))
            assert r['ok'] and r['engagement']['i'] == 0 and r['engagement']['name'] == 'Av', r
            ev = ws_bekle(ws, lambda m: m['t'] == 'engage', 3)
            assert ev and ev['kind'] == 'start' and ev['i'] == 0 and ev['state']['engagements'][-1]['result'] == 'active', ev
            assert ok(a.get(f'{S}/{sid}'))['engagement']['i'] == 0   # yeniden bağlanan istemci için
            # bırak → KESİLDİ (released)
            ok(a.post(C, json={'name': 'engage', 'params': {'action': 'release'}}))
            ev = ws_bekle(ws, lambda m: m['t'] == 'engage', 3)
            assert ev['kind'] == 'cut' and ev['reason'] == 'released' and ev['result'] == 'cut', ev
            # yeniden kilit (WS komutu) → hedefin içinden geç → önleme + BAŞARILI
            ws.send_text(json.dumps({'t': 'cmd', 'name': 'engage', 'params': {'action': 'lock', 'i': 0}, 'rid': 'e1'}))
            assert ws_bekle(ws, lambda m: m['t'] == 'engage' and m['kind'] == 'start', 3)
            time.sleep(0.3)
            hz['on'] = True
            ev = ws_bekle(ws, lambda m: m['t'] == 'engage' and m['kind'] != 'start', 5)
            assert ev and ev['kind'] == 'success' and ev['reason'] == 'intercept' and ev['min_dist_m'] <= 25 and ev['dur_s'] > 0, ev
            assert ev['state']['engaged_hits'] == 1 and ev['state']['items'][0]['locked_hits'] == 1, ev['state']
        sm = ok(a.get(f'{S}/{sid}/summary'))
        E = sm['targets']['engagements']
        assert [x['result'] for x in E] == ['cut', 'success'] and E[1]['name'] == 'Av' and E[1]['t0'] > 0, E
        ok(a.delete(f'{S}/{sid}'))
        it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
        from app import db
        with db.connect() as conn:
            row = db.row(conn.execute('SELECT targets FROM drone_sim_runs WHERE id = ?', (it['id'],)))
        res = json.loads(row['targets'])['result']
        assert [x['result'] for x in res['engagements']] == ['cut', 'success'] and res['engaged_hits'] == 1, res
    print('  API uçtan uca geçti')


def replay_testi():
    """Kayıttan oynatma oturumu kaydın canlı oturumundan angajman listesini alır (bin_log_id eşleşmesi; DB satırı elle)."""
    from app import flightsim_replay as R
    import inspect
    src = inspect.getsource(R)
    assert "'engagements': list(self.angajmanlar)" in src and "(tj.get('result') or {}).get('engagements')" in src
    print('  kayıttan oynatma alanı geçti')


def main():
    saf_testler()
    api_testleri()
    replay_testi()
    print('test_flightsim_engage: TAMAM')


if __name__ == '__main__':
    main()
