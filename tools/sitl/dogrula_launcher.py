# §27 INTERCEPTOR fırlatıcıları doğrulaması — GERÇEK ArduPilot SITL (yamalı arduplane 4.7.2), HEPGO sunucusu üzerinden. Sunucu bu betikten
# açılır/kapatılır (süreç grubu PID ile; pkill yok). Kullanım: dogrula_launcher.py <SITL ikili dizini>   (varsayılan /opt/hepgo/sitl/bin)
# Senaryolar (her biri ayrı oturum):
#   1) El fırlatıcısı: aim az 120° / el 30° → cmd takeoff {alt, aim} → aşamalar (armed → launch → released), 8 m dikey + DO_REPOSITION → nişan
#      noktasına (aim_noktasi: 433 m ileride, 250 m) uçuş; ölçüm: çıkış kerterizi (evden yatay yer değiştirme yönü) ↔ nişan azimutu, irtifa,
#      kararlılık (çarpışma yok, ARM sürer, mod GUIDED), nişan noktasına yaklaşma.
#   2) 4'lü fırlatıcı: cmd takeoff {alt 50} → dikey çıkış (yatay hız küçük), askıda kararlı (irtifa salınımı).
# Çıktı: <OUT>/sonuc.json ve stdout ÖZET.
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get('DOGRULA_REPO', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PORT = int(os.environ.get('DOGRULA_PORT', '8798'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/launcher-sitl')
SITL_DIR = sys.argv[1] if len(sys.argv) > 1 else '/opt/hepgo/sitl/bin'
DATA = f'{OUT}/data'
ENV = dict(os.environ, CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL_DIR=SITL_DIR, HEPGO_SITL='1',
           SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '39050'), CAYMAZ_DATA_DIR=DATA, CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
           CAYMAZ_PRINTER_POLL='0', SIM_TERRAIN_SERVE='0')
SRV = None
LAT0, LON0 = 39.925, 32.837


def kapat():
    global SRV
    if SRV is not None:
        try:
            os.killpg(SRV.pid, signal.SIGTERM)
            SRV.wait(30)
        except Exception:   # noqa: BLE001
            try:
                os.killpg(SRV.pid, signal.SIGKILL)
            except Exception:   # noqa: BLE001
                pass
        SRV = None
    pids = subprocess.run(['pgrep', '-f', f'{DATA}/sitl_calisma/'], capture_output=True, text=True).stdout.split()
    for p in pids:   # artık SITL (yalnız bu betiğin veri dizini) → PID ile
        try:
            os.kill(int(p), signal.SIGKILL)
        except Exception:   # noqa: BLE001
            pass


def ac():
    global SRV
    os.makedirs(DATA, exist_ok=True)
    SRV = subprocess.Popen([f'{REPO}/.venv/bin/uvicorn', 'app.main:app', '--port', str(PORT)], cwd=REPO, env=ENV,
                           stdout=open(f'{OUT}/server.log', 'ab'), stderr=subprocess.STDOUT, start_new_session=True)   # noqa: SIM115
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            urllib.request.urlopen(BASE + '/api/auth/me', timeout=2)
        except urllib.error.HTTPError:
            return
        except Exception:   # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit('sunucu açılmadı')


class Api:
    def __init__(self):
        import http.cookiejar
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(BASE + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        try:
            with self.op.open(r, timeout=90) as resp:
                t = resp.read().decode()
                return resp.status, (json.loads(t) if t and resp.headers.get('content-type', '').startswith('application/json') else t)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]

    def cmd(self, sid, name, params=None):
        return self.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': name, 'params': params or {}})


class Gcs:
    """Mission Planner yerine pymavlink GCS: ilk paket kilitler; konum/irtifa/yön/mod + SIMSTATE gövde yönelimi."""
    def __init__(self, port):
        from pymavlink import mavutil
        self.mu = mavutil
        self.m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190)
        self.st = {'alt': 0.0, 'gs': 0.0, 'mode': None, 'armed': False, 'lat': None, 'lon': None, 'hdg': None, 'body_pitch': None, 'body_yaw': None, 'att_yaw': None, 'vz': 0.0}
        self.metin = []
        self.hb = 0.0

    def pump(self, sure):
        t = time.time()
        while time.time() - t < sure:
            if time.time() - self.hb > 1:
                self.hb = time.time()
                self.m.mav.heartbeat_send(6, 8, 0, 0, 0)
            x = self.m.recv_match(blocking=True, timeout=0.2)
            if x is None:
                continue
            tp = x.get_type()
            if tp == 'VFR_HUD':
                self.st.update(gs=x.groundspeed, hdg=x.heading)
            elif tp == 'GLOBAL_POSITION_INT':
                self.st.update(alt=x.relative_alt / 1000.0, vz=-x.vz / 100.0, lat=x.lat / 1e7, lon=x.lon / 1e7)
            elif tp == 'ATTITUDE':
                self.st['att_yaw'] = math.degrees(x.yaw) % 360   # Q kiplerinde "VTOL görünümü" yönü (tailsitter askıda anlamlı yön)
            elif tp == 'SIMSTATE':
                self.st.update(body_pitch=math.degrees(x.pitch), body_yaw=math.degrees(x.yaw) % 360)
            elif tp == 'HEARTBEAT' and x.type not in (6, 18) and x.get_srcComponent() == 1:
                self.st['mode'], self.st['armed'] = self.mu.mode_string_v10(x), bool(x.base_mode & 128)
            elif tp == 'STATUSTEXT':
                self.metin.append(x.text)

    def yerel(self):
        if self.st['lat'] is None:
            return 0.0, 0.0
        return (self.st['lon'] - LON0) * 111320.0 * math.cos(math.radians(LAT0)), (self.st['lat'] - LAT0) * 110574.0


def oturum_ac(api, c, launch):
    body = {'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': False},
            'world': {'mode': 'procedural', 'seed': 7, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'launch': launch}}
    st, s = api.req('POST', '/api/drone/sim/sessions', body)
    assert st == 201, s
    sid = s['id']
    t0 = time.time()
    while time.time() - t0 < 120:
        g = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
        if g['state'] in ('HAZIR', 'HATA'):
            break
        time.sleep(1)
    assert g['state'] == 'HAZIR', g.get('sitl')
    gcs = Gcs(g['udp_port'])
    gcs.pump(25)   # EKF otursun + ilk kalp atışı parametreleri
    return sid, gcs


def faz(api, sid):
    return (api.req('GET', f'/api/drone/sim/sessions/{sid}')[1].get('launch') or {}).get('phase')


def el_firlaticisi(api, c, az=120.0, el=30.0):
    from app import flightsim_launcher as FL
    sid, gcs = oturum_ac(api, c, {'method': 'handheld', 'aim_az_deg': 10, 'aim_el_deg': 60})
    wp = FL.aim_noktasi(az, el)
    yerde = {'body_pitch': gcs.st['body_pitch'], 'alt': gcs.st['alt']}
    print('el: takeoff', api.cmd(sid, 'takeoff', {'alt': 60, 'aim': {'az_deg': az, 'el_deg': el}}), flush=True)
    t1, fazlar, seri = time.time(), [], []
    while time.time() - t1 < 75:
        gcs.pump(0.5)
        f = faz(api, sid)
        if f and (not fazlar or fazlar[-1][0] != f):
            fazlar.append((f, round(time.time() - t1, 1)))
        e, n = gcs.yerel()
        seri.append((round(time.time() - t1, 1), round(e, 1), round(n, 1), round(gcs.st['alt'], 1), round(gcs.st['gs'] or 0, 1), gcs.st['mode'], gcs.st['armed'], gcs.st['body_pitch'], gcs.st['body_yaw']))
    def kerteriz(x):
        return round((math.degrees(math.atan2(x[1], x[2])) + 360) % 360, 1)
    ornek = {f't{int(x[0])}': {'e': x[1], 'n': x[2], 'alt': x[3], 'gs': x[4], 'kerteriz': kerteriz(x) if math.hypot(x[1], x[2]) > 10 else None, 'mod': x[5]}
             for x in seri if int(x[0]) in (5, 10, 15, 20, 30, 40, 50, 60, 70) and abs(x[0] - int(x[0])) < 0.3}
    cik = [x for x in seri if math.hypot(x[1], x[2]) > 40]
    ilk = cik[0] if cik else None
    yakin = min((math.hypot(x[1] - wp['east_m'], x[2] - wp['north_m']) for x in seri), default=None)
    sonuc = {'nisan': {'az': az, 'el': el, 'wp': wp}, 'yerde': yerde, 'fazlar': fazlar, 'ornek': ornek,
             'cikis_kerterizi_40m': kerteriz(ilk) if ilk else None, 'cikis_t_40m': ilk[0] if ilk else None, 'cikis_alt_40m': ilk[3] if ilk else None,
             'kerteriz_hatasi': round(abs(((kerteriz(ilk) - az + 180) % 360) - 180), 1) if ilk else None,
             'wp_en_yakin_m': round(yakin, 1) if yakin is not None else None, 'maks_alt': max(x[3] for x in seri), 'son_alt': seri[-1][3],
             'arm_surdu': all(x[6] for x in seri if x[0] > 3), 'carpisma': [t for t in gcs.metin if 'crash' in t.lower() or 'hit ground' in t.lower()],
             'modlar': sorted({x[5] for x in seri if x[5]})}
    api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    return sonuc


def kutu(api, c):
    sid, gcs = oturum_ac(api, c, {'method': 'pod4', 'loaded': 4})
    print('pod4: takeoff', api.cmd(sid, 'takeoff', {'alt': 50}), flush=True)
    t1, fazlar, seri = time.time(), [], []
    while time.time() - t1 < 60:
        gcs.pump(0.5)
        f = faz(api, sid)
        if f and (not fazlar or fazlar[-1][0] != f):
            fazlar.append((f, round(time.time() - t1, 1)))
        e, n = gcs.yerel()
        seri.append((round(time.time() - t1, 1), e, n, gcs.st['alt'], gcs.st['gs'] or 0, gcs.st['body_pitch'], gcs.st['armed']))
    tirman = [x for x in seri if 2 < x[3] < 45]
    aski = [x for x in seri if x[0] > 45]
    sonuc = {'fazlar': fazlar, 't_45m': next((x[0] for x in seri if x[3] >= 45), None), 'tirmanis_maks_yatay_ms': round(max((x[4] for x in tirman), default=0), 2),
             'tirmanis_govde_pitch_ort': round(statistics.fmean(x[5] for x in tirman if x[5] is not None), 1) if tirman else None,
             'yatay_kayma_m': round(max(math.hypot(x[1], x[2]) for x in seri), 1),
             'aski_alt': [round(min(x[3] for x in aski), 1), round(max(x[3] for x in aski), 1)] if aski else None,
             'arm_surdu': all(x[6] for x in seri if x[0] > 3), 'carpisma': [t for t in gcs.metin if 'crash' in t.lower() or 'hit ground' in t.lower()]}
    api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    return sonuc


def main():
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, REPO)
    ac()
    sonuc = {}
    try:
        api = Api()
        assert api.req('POST', '/api/auth/login', {'username': 'admin@test', 'password': 'admin-sifre-1'})[0] == 200
        api.req('POST', '/api/kvkk/accept-terms', {})
        api.req('POST', '/api/drone/centers', {'name': 'Ankara Merkez', 'lat': LAT0, 'lon': LON0, 'alt': 900})
        c = api.req('GET', '/api/drone/centers')[1][0]
        if os.environ.get('ONLY') in (None, '', 'hand'):
            sonuc['el'] = el_firlaticisi(api, c)
            print('EL FIRLATICISI', json.dumps(sonuc['el'], ensure_ascii=False), flush=True)
            time.sleep(3)
        if os.environ.get('ONLY') in (None, '', 'pod4'):
            sonuc['pod4'] = kutu(api, c)
            print('4\'LÜ', json.dumps(sonuc['pod4'], ensure_ascii=False), flush=True)
    finally:
        kapat()
        with open(f'{OUT}/sonuc.json', 'w') as f:
            json.dump(sonuc, f, ensure_ascii=False, indent=1)
    print('ÖZET', json.dumps(sonuc, ensure_ascii=False)[:3000])


if __name__ == '__main__':
    main()
