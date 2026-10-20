# §25 INTERCEPTOR (tailsitter) + §24 hedefler doğrulaması — GERÇEK ArduPilot SITL, HEPGO sunucusu üzerinden. Sunucu bu betikten açılır/kapatılır
# (PID / süreç grubu ile; pkill yok). Kullanım: dogrula_icept.py <SITL ikili dizini>   (varsayılan /opt/hepgo/sitl/bin — yamalı 4.7.2)
# Senaryo: interceptor oturumu (power.max_speed_ms 111,1 → SIM_PLN_THR_MUL), 1 hedef → GCS'de ADSB_VEHICLE; cmd takeoff 80 m (GUIDED VTOL kalkışı)
# → dikey tırmanış ölçümü (süre, yatay hız, SIMSTATE pitch) → CRUISE + gaz %100 (RC override) 70 sn → seviye hız → RTL (Q_RTL_MODE 1: VTOL yaklaşma
# + dikey iniş) → disarm; kapanışta drone_sim_runs.targets + .bin. Çıktı: <OUT>/sonuc.json ve stdout ÖZET.
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
PORT = int(os.environ.get('DOGRULA_PORT', '8797'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/icept-sitl/e2e')
SITL_DIR = sys.argv[1] if len(sys.argv) > 1 else '/opt/hepgo/sitl/bin'
DATA = f'{OUT}/data'
CRUISE_S = float(os.environ.get('CRUISE_S', '70'))
ENV = dict(os.environ, CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL_DIR=SITL_DIR,
           SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '38950'), CAYMAZ_DATA_DIR=DATA, CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
           CAYMAZ_PRINTER_POLL='0', SIM_TERRAIN_SERVE='0')
SRV = None


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
    """Mission Planner yerine pymavlink GCS: ilk paket kilitler; telemetri + SIMSTATE + ADSB_VEHICLE toplanır."""
    def __init__(self, port):
        from pymavlink import mavutil
        self.mu = mavutil
        self.m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190)
        self.st = {'alt': 0.0, 'gs': 0.0, 'as': 0.0, 'mode': None, 'armed': False, 'body_pitch': None, 'pitch': None, 'vz': 0.0, 'thr': 0}
        self.adsb = None
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
                self.st.update(gs=x.groundspeed, as_=x.airspeed, thr=x.throttle)
                self.st['as'] = x.airspeed
            elif tp == 'GLOBAL_POSITION_INT':
                self.st['alt'], self.st['vz'] = x.relative_alt / 1000.0, -x.vz / 100.0
            elif tp == 'ATTITUDE':
                self.st['pitch'] = math.degrees(x.pitch)
            elif tp == 'SIMSTATE':
                self.st['body_pitch'] = math.degrees(x.pitch)
            elif tp == 'HEARTBEAT' and x.type not in (6, 18) and x.get_srcComponent() == 1:
                self.st['mode'], self.st['armed'] = self.mu.mode_string_v10(x), bool(x.base_mode & 128)
            elif tp == 'ADSB_VEHICLE' and self.adsb is None:
                self.adsb = {'icao': x.ICAO_address, 'callsign': x.callsign.rstrip('\x00'), 'alt_m': x.altitude / 1000, 'hor_ms': x.hor_velocity / 100, 'comp': x.get_srcComponent()}


def main():
    os.makedirs(OUT, exist_ok=True)
    ac()
    sonuc = {}
    try:
        api = Api()
        assert api.req('POST', '/api/auth/login', {'username': 'admin@test', 'password': 'admin-sifre-1'})[0] == 200
        api.req('POST', '/api/kvkk/accept-terms', {})
        api.req('POST', '/api/drone/centers', {'name': 'Ankara Merkez', 'lat': 39.925, 'lon': 32.837, 'alt': 900})
        c = api.req('GET', '/api/drone/centers')[1][0]
        body = {'mode': 'sitl', 'type': 'interceptor', 'center_id': c['id'], 'rec': {'bin': True},
                'world': {'mode': 'procedural', 'seed': 7, 'size_m': 4000, 'time': 'day', 'wind_ms': 0},
                'targets': {'items': [{'model': 'tgt:lancet', 'alt_m': 80, 'diameter_m': 600, 'dir': 'cw', 'name': 'Lancet-1'}], 'radius_m': 30}}
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
        print('oturum', sid, 'udp', g['udp_port'], 'speed_scale', g['speed_scale'], 'model', g['model']['id'], flush=True)
        gcs = Gcs(g['udp_port'])
        gcs.pump(25)   # EKF otursun + ilk kalp atışı parametreleri
        sonuc['adsb'] = gcs.adsb
        sonuc['yerde_body_pitch'] = gcs.st['body_pitch']
        # --- dikey kalkış ---
        print('takeoff', api.cmd(sid, 'takeoff', {'alt': 80}), flush=True)
        t1 = time.time()
        maks_gs, pitchler, t75 = 0.0, [], None
        while time.time() - t1 < 80:
            gcs.pump(0.5)
            if gcs.st['alt'] > 2:
                maks_gs = max(maks_gs, gcs.st['gs'] or 0)
                if gcs.st['body_pitch'] is not None:
                    pitchler.append(gcs.st['body_pitch'])
            if gcs.st['alt'] >= 75 and t75 is None:
                t75 = round(time.time() - t1, 1)
                break
        sonuc['kalkis'] = {'t_75m_s': t75, 'maks_yatay_ms': round(maks_gs, 2), 'govde_pitch_ort': round(statistics.fmean(pitchler), 1) if pitchler else None,
                           'mod': gcs.st['mode'], 'goruntu_pitch': gcs.st['pitch']}
        print('KALKIŞ', sonuc['kalkis'], flush=True)
        gcs.pump(3)
        # --- yatay uçuş: CRUISE + gaz %100 ---
        api.cmd(sid, 'mode', {'mode': 'CRUISE'})
        seri, t2, son_rc = [], time.time(), 0
        while time.time() - t2 < CRUISE_S:
            if time.time() - son_rc > 1:
                son_rc = time.time()
                api.cmd(sid, 'rc', {'ch': [1500, 1500, 2000, 1500, 0, 0, 0, 0]})
            gcs.pump(0.5)
            seri.append((time.time() - t2, gcs.st['gs'], gcs.st['as'], gcs.st['alt'], gcs.st['body_pitch']))
        son = [x for x in seri if x[0] > CRUISE_S - 20]
        gecis = next((round(x[0], 1) for x in seri if x[4] is not None and abs(x[4]) < 30), None)
        sonuc['yatay'] = {'gecis_s': gecis, 'gs_ort_ms': round(statistics.fmean(x[1] for x in son), 1), 'gs_ort_kmh': round(statistics.fmean(x[1] for x in son) * 3.6),
                          'gs_maks_ms': round(max(x[1] for x in seri), 1), 'as_ort': round(statistics.fmean(x[2] for x in son), 1),
                          'alt_min': round(min(x[3] for x in son), 1), 'alt_max': round(max(x[3] for x in son), 1), 'govde_pitch': [round(min(x[4] for x in son), 1), round(max(x[4] for x in son), 1)]}
        print('YATAY', sonuc['yatay'], flush=True)
        api.cmd(sid, 'rc', {'ch': [0] * 8})
        # --- dönüş: RTL → VTOL yaklaşma + dikey iniş ---
        api.cmd(sid, 'rtl')
        t3, modlar, inis_pitch = time.time(), [], []
        while time.time() - t3 < 360:
            gcs.pump(1)
            if gcs.st['mode'] and (not modlar or modlar[-1] != gcs.st['mode']):
                modlar.append(gcs.st['mode'])
            if gcs.st['alt'] < 20 and gcs.st['body_pitch'] is not None:
                inis_pitch.append(gcs.st['body_pitch'])
            if not gcs.st['armed'] and gcs.st['alt'] < 2:
                break
        sonuc['donus'] = {'sure_s': round(time.time() - t3, 1), 'modlar': modlar, 'disarm': not gcs.st['armed'], 'son_alt': gcs.st['alt'],
                          'inis_govde_pitch_ort': round(statistics.fmean(inis_pitch), 1) if inis_pitch else None}
        print('DÖNÜŞ', sonuc['donus'], flush=True)
        g = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
        sonuc['targets_state'] = g.get('targets_state')
        sonuc['thr_mul'] = g.get('speed_scale')
        st, r = api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
        sonuc['bin'] = (r or {}).get('bin') if isinstance(r, dict) else None
        time.sleep(2)
        run = next((x for x in api.req('GET', '/api/drone/sim/runs')[1]['items'] if x['session_id'] == sid), None)
        sonuc['run'] = {k: run.get(k) for k in ('type', 'intercept_count', 'bin_log_id', 'result')} if run else None
        json.dump(sonuc, open(f'{OUT}/sonuc.json', 'w'), ensure_ascii=False, indent=1)
        print('ÖZET', json.dumps(sonuc, ensure_ascii=False), flush=True)
    finally:
        kapat()


if __name__ == '__main__':
    main()
