# §34 SERVO TETİK doğrulaması — GERÇEK ArduPilot SITL, HEPGO sunucusu üzerinden (sunucu bu betikten açılır/kapatılır; PID / süreç grubu ile, pkill yok).
# Kullanım: dogrula_servotrig.py [SITL ikili dizini]   (varsayılan /opt/hepgo/sitl/bin)
# Senaryo (kopter 1× ve sabit kanat 4×): oturum → pymavlink GCS (Mission Planner yerine; UDP portu) → kalkış → `servo_trigger {ch 9, ≥ 1900, 1500 ms}`
# → GCS'den MAV_CMD_DO_SET_SERVO (9, 1900) → sunucu SERVO_OUTPUT_RAW kenarını görür → 1500 ms SİMÜLASYON zamanı sonra çarpma → izleyici yok →
# sunucu kapatır (end_reason servo_trigger). Özet raporundaki tetik / çarpma anı konumu ve irtifası, GCS'nin aynı SITL time_boot_ms'li
# GLOBAL_POSITION_INT örnekleriyle karşılaştırılır; .bin'de STATUSTEXT (MSG "SERVO TRIG"/"SERVO HIT") aranır. Çıktı: <OUT>/sonuc.json + stdout ÖZET.
import glob
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get('DOGRULA_REPO', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PORT = int(os.environ.get('DOGRULA_PORT', '8798'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/servotrig-sitl')
SITL_DIR = sys.argv[1] if len(sys.argv) > 1 else '/opt/hepgo/sitl/bin'
DATA = f'{OUT}/data'
ENV = dict(os.environ, CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL_DIR=SITL_DIR,
           SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '38750'), CAYMAZ_DATA_DIR=DATA, CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
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
    for p in subprocess.run(['pgrep', '-f', f'{DATA}/sitl_calisma/'], capture_output=True, text=True).stdout.split():   # yalnız bu betiğin SITL'leri → PID
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


def mesafe(a, b):
    c = math.cos(math.radians(a[0]))
    return math.hypot((b[0] - a[0]) * 110574.0, (b[1] - a[1]) * 111320.0 * c)


class Gcs:
    """Mission Planner yerine pymavlink GCS: GLOBAL_POSITION_INT (tbm → konum) + SERVO_OUTPUT_RAW kanal 9 + COMMAND_ACK."""
    def __init__(self, port):
        from pymavlink import mavutil
        self.mu = mavutil
        self.m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190)
        self.pos = {}          # tbm → (lat, lon, alt_rel, alt_msl)
        self.alt = 0.0
        self.s9 = []           # (tbm, servo9)
        self.ack = []
        self.hb = 0.0
        self.sysid = 1
        self.armed = False

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
            if tp == 'GLOBAL_POSITION_INT':
                self.pos[x.time_boot_ms] = (x.lat / 1e7, x.lon / 1e7, x.relative_alt / 1000.0, x.alt / 1000.0)
                self.alt = x.relative_alt / 1000.0
            elif tp == 'SERVO_OUTPUT_RAW' and getattr(x, 'port', 0) == 0:
                self.s9.append((x.time_usec // 1000, getattr(x, 'servo9_raw', None)))
            elif tp == 'HEARTBEAT' and x.type not in (6, 18) and x.get_srcComponent() == 1:
                self.armed = bool(x.base_mode & 128)
            elif tp == 'COMMAND_ACK':
                self.ack.append((x.command, x.result))

    def set_servo(self, ch, pwm):
        self.m.mav.command_long_send(self.sysid, 1, 183, 0, ch, pwm, 0, 0, 0, 0, 0)   # MAV_CMD_DO_SET_SERVO (Mission Planner Servo/Relay sekmesi)

    def yakin(self, tbm):
        k = min(self.pos, key=lambda t: abs(t - tbm))
        return k, self.pos[k]


def senaryo(api, c, tip, hiz):
    r = {'type': tip, 'speedup': hiz}
    body = {'mode': 'sitl', 'type': tip, 'center_id': c['id'], 'rec': {'bin': True}, 'world': {'mode': 'procedural', 'seed': 7, 'size_m': 4000, 'wind_ms': 0}}
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
    gcs.pump(25)
    fn = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]['servo_trigger']['fn']
    r['servo_fn'] = fn
    if hiz != 1:
        r['speed_cmd'] = api.cmd(sid, 'speed', {'factor': hiz})[0]
    print(tip, 'oturum', sid, 'udp', g['udp_port'], 'SERVO9_FUNCTION', fn[8], flush=True)
    if tip != 'sabit_kanat':   # kopter: GUIDED + ARM, sonra NAV_TAKEOFF (sabit kanatta kalkış dizisi ARM'ı kendisi yapar)
        api.cmd(sid, 'mode', {'mode': 'GUIDED'}); gcs.pump(1)
        for _ in range(20):
            api.cmd(sid, 'arm'); gcs.pump(2)
            if gcs.armed:
                break
    print('takeoff', api.cmd(sid, 'takeoff', {'alt': 60 if tip == 'sabit_kanat' else 40}), flush=True)
    t1 = time.time()
    while time.time() - t1 < 150 and gcs.alt < (45 if tip == 'sabit_kanat' else 35):
        gcs.pump(0.5)
    r['kalkis_alt'] = round(gcs.alt, 1)
    gcs.pump(2)
    st, x = api.cmd(sid, 'servo_trigger', {'on': True, 'ch': 9, 'pwm': 1900, 'cmp': 'ge', 'delay_ms': 1500})
    r['listen'] = (st, x.get('servo_trigger', {}).get('phase') if isinstance(x, dict) else x)
    gcs.pump(1)
    s9_once = gcs.s9[-1] if gcs.s9 else None
    t_set = time.time()
    gcs.set_servo(9, 1900)
    ozet = None
    while time.time() - t_set < 30:
        gcs.pump(0.3)
        st, o = api.req('GET', f'/api/drone/sim/sessions/{sid}/summary')
        if st != 200:
            break
        if (o.get('servo_trigger') or {}).get('hit'):
            ozet = o
            break
    r['duvar_s'] = round(time.time() - t_set, 2)
    r['servo9_once'], r['servo9_sonra'] = s9_once, next(((t, v) for t, v in gcs.s9 if v and v >= 1900), None)
    r['ack_183'] = [a for a in gcs.ack if a[0] == 183]
    gcs.pump(1)
    assert ozet, f'çarpma gelmedi: {r}'
    sv = ozet['servo_trigger']
    T, H = sv['trigger'], sv['hit']
    kt, pt = gcs.yakin(T['tbm'])
    kh, ph = gcs.yakin(H['tbm'])
    r['tetik'] = {k: T[k] for k in ('tbm', 'agl', 'alt_msl', 'dist_home_m', 'lat', 'lon', 'airspeed', 'groundspeed', 'flight_s')}
    r['carpma'] = {k: H[k] for k in ('tbm', 'agl', 'alt_msl', 'dist_home_m', 'lat', 'lon', 'airspeed', 'groundspeed', 'flight_s', 'delay_sim_ms', 'delay_wall_ms', 'watchdog')}
    r['gcs_karsilastirma'] = {'tetik_tbm_fark_ms': kt - T['tbm'], 'tetik_konum_fark_m': round(mesafe((T['lat'], T['lon']), pt[:2]), 2), 'tetik_alt_fark_m': round(T['alt_rel'] - pt[2], 2),
                              'carpma_tbm_fark_ms': kh - H['tbm'], 'carpma_konum_fark_m': round(mesafe((H['lat'], H['lon']), ph[:2]), 2), 'carpma_alt_fark_m': round(H['alt_rel'] - ph[2], 2)}
    r['crash_reason'] = (ozet.get('crash') or {}).get('reason')
    # izleyici yok → sunucu kapatır
    t2 = time.time()
    while time.time() - t2 < 60 and api.req('GET', f'/api/drone/sim/sessions/{sid}')[0] == 200:
        gcs.pump(0.5)
    r['sunucu_kapatti_s'] = round(time.time() - t2, 1)
    time.sleep(3)
    runs = api.req('GET', '/api/drone/sim/runs')[1]['items']
    run = next((x for x in runs if x['session_id'] == sid), None)
    r['run'] = {k: run.get(k) for k in ('id', 'result', 'end_reason', 'servo_trig', 'bin_log_id')} if run else None
    gcs.m.close()
    return r


def bin_msg():
    from pymavlink import DFReader
    out = []
    for p in sorted(glob.glob(f'{DATA}/**/*.BIN', recursive=True) + glob.glob(f'{DATA}/**/*.bin', recursive=True)):
        try:
            f = DFReader.DFReader_binary(p)
            while True:
                m = f.recv_match(type='MSG')
                if m is None:
                    break
                if 'SERVO' in m.Message:
                    out.append((os.path.basename(p), m.Message))
        except Exception as e:   # noqa: BLE001
            out.append((os.path.basename(p), f'okunamadı: {e}'))
    return out


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
        sonuc['kopter'] = senaryo(api, c, 'multirotor', 1)
        print('KOPTER', json.dumps(sonuc['kopter'], ensure_ascii=False), flush=True)
        sonuc['ucak'] = senaryo(api, c, 'sabit_kanat', 4)
        print('UÇAK', json.dumps(sonuc['ucak'], ensure_ascii=False), flush=True)
        time.sleep(3)
        sonuc['bin_msg'] = bin_msg()
        print('BIN MSG', sonuc['bin_msg'], flush=True)
    finally:
        with open(f'{OUT}/sonuc.json', 'w') as f:
            json.dump(sonuc, f, ensure_ascii=False, indent=1)
        kapat()
    print('ÖZET', json.dumps(sonuc, ensure_ascii=False))


if __name__ == '__main__':
    main()
