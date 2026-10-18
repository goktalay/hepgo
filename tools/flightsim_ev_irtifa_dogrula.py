"""Uçuş Simülatörü — §9 EV İRTİFASI KURALI doğrulaması (DEV; GERÇEK arduplane SITL + gerçek arazi kipi + rampa kalkışı).

PROD vakası (18 Ekim): merkezler "Ankara 39.3775/34.2904 alt 0" ve "Bedesten 39.8565/33.3998 alt 1500" kayıtlıyken SITL arazi sunumu açıldı →
SITL yüzeyi terrarium'dan biliyor, ev irtifası kullanıcının girdiği 0/1500 m ile kuruluyordu → uçak yerin altında/üstünde doğup takla atıyordu.
Bu araç her iki merkez için gerçek kipte oturum açar ve ölçer: session.center.alt ≈ terrarium (alt_entered = girilen), yerde alt_rel 0±1 ve
terrain_agl 0±2, 60 sn boyunca |pitch|,|roll| < 5°, ardından rampa kalkışı normal (alt_rel yükselir). Çıkış: EV-IRTIFA-OK / hata.

Çalıştırma (DEV): HEPGO_SITL_DIR=/opt/hepgo/sitl/bin SIM_UDP_BASE=44550 .venv/bin/python -m tools.flightsim_ev_irtifa_dogrula [izleme_sn]
"""
import json
import math
import os
import sys
import tempfile
import time

IZLEME_SN = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
ISINMA_SN = 10.0   # izlemenin ilk saniyeleri: arazi veritabanı dolarken terrain_agl geçici değerleri ölçüme girmez (raporlanır)
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_ADMIN_USERNAME='admin@test',
                  CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0', HEPGO_SITL='1')
os.environ.setdefault('CAYMAZ_DATA_DIR', tempfile.mkdtemp(prefix='hepgo-evirtifa-'))
os.environ.setdefault('SIM_UDP_BASE', '44550')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, flightsim, sim_terrain  # noqa: E402
from app.main import app  # noqa: E402

MERKEZLER = (('Ankara-Karapınar (alt 0)', 39.3775438, 34.2903542, 0.0), ('Bedesten (alt 1500)', 39.8565433, 33.399836, 1500.0))


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def oturum(a, token, ad, lat, lon, alt_girilen):
    t0 = time.time()
    c = next((x for x in ok(a.get('/api/drone/centers')) if x['name'] == ad), None)   # kalıcı veri dizininde aynı ad varsa yeniden kullan
    if c is None:
        c = ok(a.post('/api/drone/centers', json={'name': ad, 'lat': lat, 'lon': lon, 'alt': alt_girilen}))
    arazi = sim_terrain.ev_irtifa(lat, lon)
    print(f'\n=== {ad}: terrarium ev irtifası {arazi} m · kayıtlı {alt_girilen} m')
    s = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c['id'],
                                                   'world': {'mode': 'real', 'building_count': 0, 'wind_ms': 0, 'launch': {'method': 'ramp', 'angle_deg': 15}}}), 201)
    sid = s['id']
    print(f"oturum {sid}: center.alt={s['center']['alt']} alt_entered={s['center']['alt_entered']} launch={s['launch']['method']}")
    assert abs(float(s['center']['alt']) - arazi) < 0.01 and s['center']['alt_entered'] == alt_girilen, s['center']
    ses = flightsim.MANAGER.get(sid)
    print('alt_not:', ses.alt_not)
    assert (abs(alt_girilen - arazi) > flightsim.EV_FARK_UYARI) == bool(ses.alt_not), (alt_girilen, arazi, ses.alt_not)
    bitis = time.time() + 120
    while time.time() < bitis:
        s = ok(a.get(f'/api/drone/sim/sessions/{sid}'))
        if s['state'] in ('HAZIR', 'HATA'):
            break
        time.sleep(1)
    print(f"state={s['state']} sitl={s['sitl']} ({time.time() - t0:.0f} sn)")
    assert s['state'] == 'HAZIR', s
    sonuc = {'ad': ad, 'arazi': arazi, 'girilen': alt_girilen, 'center_alt': s['center']['alt']}
    with a.websocket_connect(f'/ws/drone/sim/{sid}', headers={'cookie': f'{auth.COOKIE}={token}'}) as ws:
        h = json.loads(ws.receive_text())
        assert h['t'] == 'hello', h
        olaylar, son = [], None
        bitis = time.time() + 120   # GPS/EKF kilidi
        while time.time() < bitis:
            m = json.loads(ws.receive_text())
            if m['t'] == 'tele':
                son = m
                if son['gps_fix'] >= 3 and son['home'] and son.get('terrain_agl') is not None:
                    break
            elif m['t'] == 'event':
                olaylar.append(m['text'])
        print(f'GPS+arazi kilidi ({time.time() - t0:.0f} sn) · olaylar: {[o[:90] for o in olaylar]}')
        assert son and son['gps_fix'] >= 3, son
        assert any('Ev irtifası' in o for o in olaylar), olaylar
        if ses.alt_not:
            assert any('kayıtlı irtifası' in o for o in olaylar), olaylar
        # --- yerde izleme: alt_rel, terrain_agl, pitch/roll ---
        pr_max = agl_min = agl_max = rel_min = rel_max = None
        n, gecici = 0, []
        t_bas = time.time()
        bitis = t_bas + IZLEME_SN
        while time.time() < bitis:
            m = json.loads(ws.receive_text())
            if m['t'] != 'tele':
                if m['t'] == 'event':
                    olaylar.append(m['text'])
                continue
            if time.time() - t_bas < ISINMA_SN:   # SITL arazi veritabanı ilk blokları yüklerken TERRAIN_REPORT.terrain_height geçici (0/eksik) olabilir
                if m.get('terrain_agl') is not None and abs(m['terrain_agl']) > 2:
                    gecici.append(m['terrain_agl'])
                continue
            n += 1
            p, r = abs(math.degrees(m['pitch'])), abs(math.degrees(m['roll']))
            pr_max = max(pr_max or 0, p, r)
            rel_min = m['alt_rel'] if rel_min is None else min(rel_min, m['alt_rel'])
            rel_max = m['alt_rel'] if rel_max is None else max(rel_max, m['alt_rel'])
            if m.get('terrain_agl') is not None:
                agl_min = m['terrain_agl'] if agl_min is None else min(agl_min, m['terrain_agl'])
                agl_max = m['terrain_agl'] if agl_max is None else max(agl_max, m['terrain_agl'])
        sonuc.update(kare=n, isinma_gecici_agl=(len(gecici), min(gecici) if gecici else None), alt_msl=m['alt_msl'], alt_rel=(rel_min, rel_max), terrain_agl=(agl_min, agl_max), terrain_h=m.get('terrain_h'), pitch_roll_max_deg=round(pr_max or 0, 2),
                     home=m['home'], mode=m['mode'], armed=m['armed'])
        print('yerde izleme:', {k: sonuc[k] for k in ('kare', 'isinma_gecici_agl', 'alt_msl', 'alt_rel', 'terrain_agl', 'terrain_h', 'pitch_roll_max_deg', 'home', 'mode', 'armed')})
        assert n > 100, n
        assert -1 <= rel_min and rel_max <= 1, (rel_min, rel_max)
        assert agl_min is not None and -2 <= agl_min and agl_max <= 2, (agl_min, agl_max)
        assert abs(m['alt_msl'] - arazi) < 3, (m['alt_msl'], arazi)
        assert pr_max < 5, pr_max
        assert not m['armed'], m['mode']
        # --- rampa kalkışı ---
        ws.send_text(json.dumps({'t': 'cmd', 'name': 'takeoff', 'params': {'alt': 60}, 'rid': 'k1'}))
        fazlar, en_yuksek, pr_ucus = [], 0.0, 0.0
        bitis = time.time() + 75
        while time.time() < bitis:
            m = json.loads(ws.receive_text())
            if m['t'] == 'launch':
                fazlar.append(m['phase'])
            elif m['t'] == 'event':
                olaylar.append(m['text'])
            elif m['t'] == 'tele':
                en_yuksek = max(en_yuksek, m['alt_rel'])
                if m['alt_rel'] > 5:
                    pr_ucus = max(pr_ucus, abs(math.degrees(m['roll'])))
                if en_yuksek >= 40:
                    break
        sonuc.update(launch_fazlari=fazlar, kalkis_en_yuksek_alt_rel=round(en_yuksek, 1), ucus_roll_max_deg=round(pr_ucus, 1), son_mode=m.get('mode'))
        print('kalkış:', {k: sonuc[k] for k in ('launch_fazlari', 'kalkis_en_yuksek_alt_rel', 'ucus_roll_max_deg', 'son_mode')}, '· olaylar:', [o[:70] for o in olaylar[-4:]])
        assert 'launch' in fazlar and en_yuksek >= 20, (fazlar, en_yuksek)
        assert pr_ucus < 60, pr_ucus
    ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
    time.sleep(2)
    return sonuc


def main():
    print(f"veri dizini {os.environ['CAYMAZ_DATA_DIR']} · UDP {os.environ['SIM_UDP_BASE']} · izleme {IZLEME_SN:.0f} sn")
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        token = a.cookies.get(auth.COOKIE)
        sonuclar = [oturum(a, token, *m) for m in MERKEZLER]
    print('\nÖZET:')
    for s in sonuclar:
        print(json.dumps(s, ensure_ascii=False))
    print('EV-IRTIFA-OK')


if __name__ == '__main__':
    main()
