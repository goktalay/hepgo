"""Uçuş Simülatörü §42 — UÇUŞ UYARI SİSTEMİ sunucu tarafı: saf kayıt (app/flightsim_gpws: doğrulama, (kod, t0) tekilleştirme, özet + puan — istemci
`summarizeAlerts` ile birebir aynı, node ile karşılaştırılır) + HEPGO API uçtan uca (sahte kinematik HEPGO_SITL=0): `cmd gpws` 400'leri, WS komutu,
özet raporda `alerts`, kapanışta drone_sim_runs.alerts / alert_score (göç sütunları), kayıt listesinde JSON; SIMUMAV shim sütun listesi.

Çalıştırma: .venv/bin/python -m tests.test_flightsim_gpws
"""
import json
import os
import random
import subprocess
import tempfile
from pathlib import Path

os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='0', SIM_UDP_BASE='25950', SIM_MAX_SESSIONS='2', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')

from fastapi.testclient import TestClient  # noqa: E402

from app import db, flightsim  # noqa: E402
from app import flightsim_gpws as G  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, bekle, ok, ws_bekle  # noqa: E402

KOK = Path(__file__).resolve().parent.parent
MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}


def js_ozet(olaylar, mode='full'):
    """İstemci summarizeAlerts (node) → sözlük."""
    kod = ("import('./static/js/modules/flightsim_gpws.js').then(m => { const a = JSON.parse(process.argv[1]); "
           "process.stdout.write(JSON.stringify(m.summarizeAlerts(a.ev, { mode: a.mode }))); })")
    r = subprocess.run(['node', '-e', kod, json.dumps({'ev': olaylar, 'mode': mode})], cwd=KOK, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def saf_testler():
    # doğrulama
    for bad in ({'events': 'x'}, {'events': [{'code': 'NOPE', 't0': 1, 'dur_s': 1}]}, {'events': [{'code': 'PULL_UP', 'level': 'caution', 't0': 1, 'dur_s': 1}]},
                {'events': [{'code': 'PULL_UP', 't0': 'a', 'dur_s': 1}]}, {'events': [{'code': 'PULL_UP', 't0': 1, 'dur_s': -1}]},
                {'events': [{'code': 'PULL_UP', 't0': 1, 'dur_s': True}]}, {'events': [{'code': 'PULL_UP', 't0': 1, 'dur_s': 1}] * 51},
                {'cfg': {'mode': 'x'}}, {'cfg': {'off': 'PULL_UP'}}, {'events': ['x']}):
        k = G.UyariKaydi()
        try:
            k.ekle(bad)
            raise AssertionError(f'kabul edildi: {str(bad)[:80]}')
        except G.GpwsHata:
            pass
    k = G.UyariKaydi()
    assert k.ozet() is None   # bildirim yok → özet alanı yok
    r = k.ekle({'cfg': {'mode': 'full', 'off': ['STALL', 'NOPE']}, 'events': []})
    assert r == {'ok': True, 'added': 0, 'total': 0} and k.cfg == {'mode': 'full', 'off': ['STALL']}
    o = k.ozet()
    assert o['score'] == 100 and o['grade'] == 'A' and o['warnings'] == 0 and o['off'] == ['STALL'], o
    e1 = {'code': 'PULL_UP', 'level': 'warning', 't0': 100.0, 'start_s': 30.0, 'dur_s': 4.0}
    assert k.ekle({'events': [e1, dict(e1)]})['added'] == 1          # aynı komutta yinelenen
    assert k.ekle({'events': [{**e1, 't0': 100.04}]})['added'] == 0   # (kod, t0 0,1 sn) — başka sekmeden aynı bölüm
    k.ekle({'events': [{'code': 'PULL_UP', 't0': 200, 'start_s': 130, 'dur_s': 2}, {'code': 'TOO_LOW', 't0': 150, 'start_s': 80, 'dur_s': 10}]})
    o = k.ozet()
    assert o['by_code']['PULL_UP'] == {'level': 'warning', 'n': 2, 'total_s': 6.0, 'first_s': 30.0} and o['score'] == 72 and o['grade'] == 'C', o
    assert [e['code'] for e in o['events']] == ['PULL_UP', 'TOO_LOW', 'PULL_UP']   # zaman sırası
    k.ekle({'cfg': {'mode': 'off'}})
    assert k.ozet()['score'] is None and k.ozet()['grade'] is None
    # istemci formülüyle birebir (rastgele 40 bölüm, iki kez)
    rnd = random.Random(42)
    for _ in range(3):
        ev = [{'code': rnd.choice(list(G.KODLAR)), 't0': round(rnd.uniform(0, 900), 2), 'start_s': round(rnd.uniform(0, 800), 2), 'dur_s': round(rnd.uniform(0, 25), 2)}
              for _ in range(rnd.randint(0, 40))]
        for e in ev:
            e['level'] = G.KODLAR[e['code']]
        py, js = G.ozetle(ev), js_ozet(ev)
        assert py['score'] == js['score'] and py['grade'] == js['grade'] and py['warnings'] == js['warnings'] and py['cautions'] == js['cautions'], (py['score'], js['score'])
        assert abs(py['total_s'] - js['total_s']) < 1e-9, (py['total_s'], js['total_s'])
        for c, b in py['by_code'].items():
            jb = js['by_code'][c]
            assert b['n'] == jb['n'] and abs(b['total_s'] - jb['total_s']) < 1e-9 and abs(b['first_s'] - jb['first_s']) < 1e-9, (c, b, jb)
    # tavanlar
    k2 = G.UyariKaydi()
    for i in range(11):
        k2.ekle({'events': [{'code': 'WIND', 't0': i * 100 + j, 'dur_s': 1} for j in range(50)]})
    assert len(k2.olaylar) == G.OLAY_TAVANI and len(k2.ozet()['events']) == G.OZET_OLAY_TAVANI
    print('  saf kayıt + puan eşitliği geçti')


def api_testleri():
    S = '/api/drone/sim/sessions'
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'Uyarı Sahası', **MERKEZ}))
        s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        sid = s['id']
        assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR')
        C = f'{S}/{sid}/cmd'
        for bad in ({'events': [{'code': 'XX', 't0': 1, 'dur_s': 1}]}, {'events': 5}, {'cfg': {'mode': 'loud'}}):
            assert a.post(C, json={'name': 'gpws', 'params': bad}).status_code == 400, bad
        r = ok(a.post(C, json={'name': 'gpws', 'params': {'cfg': {'mode': 'full', 'off': []}, 'events': []}}))
        assert r['ok'] and r['added'] == 0
        r = ok(a.post(C, json={'name': 'gpws', 'params': {'events': [{'code': 'BANK_ANGLE', 'level': 'warning', 't0': 12.3, 'start_s': 5.0, 'dur_s': 3.2}]}}))
        assert r['added'] == 1 and r['total'] == 1
        with a.websocket_connect(f'/ws/drone/sim/{sid}') as ws:   # WS komutu (SIMUMAV yolu da aynı çekirdek komutu)
            assert ws_bekle(ws, lambda m: m['t'] == 'hello')
            ws.send_text(json.dumps({'t': 'cmd', 'rid': 'g1', 'name': 'gpws', 'params': {'events': [{'code': 'TOO_LOW', 't0': 40.0, 'start_s': 33.0, 'dur_s': 6.0}]}}))
            assert bekle(lambda: len(flightsim.MANAGER.sessions[sid].uyarilar.olaylar) == 2, 3)
        sm = ok(a.get(f'{S}/{sid}/summary'))
        A = sm['alerts']
        assert A['warnings'] == 1 and A['cautions'] == 1 and A['by_code']['BANK_ANGLE']['total_s'] == 3.2 and A['score'] == round(100 - (6 + 1.5 * 3.2) - (2 + 0.5 * 6)), A
        # özetten SONRA gelen bölüm (Bitir'de flush) kapanışta yine sayılır
        ok(a.post(C, json={'name': 'gpws', 'params': {'events': [{'code': 'PULL_UP', 't0': 60.0, 'start_s': 53.0, 'dur_s': 2.0}]}}))
        ok(a.delete(f'{S}/{sid}'))
        it = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == sid)
        assert it['alert_score'] == G.ozetle([{'code': 'BANK_ANGLE', 't0': 12.3, 'dur_s': 3.2}, {'code': 'TOO_LOW', 't0': 40, 'dur_s': 6}, {'code': 'PULL_UP', 't0': 60, 'dur_s': 2}])['score'], it['alert_score']
        assert isinstance(it['alerts'], dict) and it['alerts']['warnings'] == 2, it['alerts']
        with db.connect() as conn:
            cols = {r[1] for r in conn.execute('PRAGMA table_info(drone_sim_runs)')}
        assert {'alerts', 'alert_score'} <= cols

        def rap_uyari():
            with db.connect() as conn:
                rap = db.row(conn.execute("SELECT detail FROM drone_sim_events WHERE type = 'summary' AND session_id = ? ORDER BY id DESC LIMIT 1", (sid,)))
            return (json.loads(rap['detail']).get('alerts') or {}).get('warnings') if rap else None
        assert bekle(lambda: rap_uyari() == 2, 5), rap_uyari()   # kapanışta özet satırı da güncellendi (Bitir'den sonra gelen bölüm)
        # bildirimsiz oturum: alerts yok (NULL)
        s2 = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        assert bekle(lambda: ok(a.get(f"{S}/{s2['id']}"))['state'] == 'HAZIR')
        assert ok(a.get(f"{S}/{s2['id']}/summary")).get('alerts') is None
        ok(a.delete(f"{S}/{s2['id']}"))
        it2 = next(x for x in ok(a.get('/api/drone/sim/runs'))['items'] if x['session_id'] == s2['id'])
        assert it2['alerts'] is None and it2['alert_score'] is None
    # göç idempotent (ikinci init sütunları yeniden eklemeye çalışmaz)
    db.init()
    from app.flightsim_mission import rapor_metni
    assert 'uçuş disiplini' in rapor_metni({'alerts': {'mode': 'full', 'warnings': 1, 'cautions': 0, 'total_s': 3, 'score': 91, 'grade': 'A'}})
    print('  API uçtan uca + kalıcı kayıt geçti')


def simumav_testi():
    src = (KOK / 'app/simumav/shim/db.py').read_text(encoding='utf-8')
    assert "('alerts', 'TEXT'), ('alert_score', 'INTEGER')" in src
    br = (KOK / 'app/simumav/bridge.py').read_text(encoding='utf-8')
    assert "ozet['alerts'] = u" in br
    ex = (KOK / 'tools/simumav_export.py').read_text(encoding='utf-8')
    assert "'app/flightsim_gpws.py'" in ex
    print('  SIMUMAV shim / köprü / dışa aktarma geçti')


def main():
    saf_testler()
    api_testleri()
    simumav_testi()
    print('test_flightsim_gpws: TAMAM')


if __name__ == '__main__':
    main()
