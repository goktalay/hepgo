# §23 güç ve yakıt doğrulaması — GERÇEK ArduPilot SITL. Sunucu bu betikten açılır/kapatılır (PID ile; pkill yok).
# Kullanım: dogrula_guc.py <SITL ikili dizini> <senaryo,...>   senaryolar: hiz speedup yakit
#   hiz     : CAYMAZ sabit kanat, power.max_speed_ms=45 → tekerlekli kalkış 120 m → FBWA + RC gaz %100 (pitch nötr) 70 sn → son 25 sn yer/hava hızı
#             ortalaması. Yamasız ikili (0001): SIM_PLN_THR_MUL yok → stok fizik ≈ 31,8 m/s; yamalı ikili (0002, bin-new): ≈ 45 m/s (±%10 hedef).
#   speedup : rec.bin açık, SIM_SPEEDUP 4 → kalkış → SITL saatinde 120 sn (time_boot_ms) → gerçek süre < 40 sn; kapanışta .bin → analiz → kayıttan
#             oynatma oturumu → duration_s ≈ SITL armed süresi (gerçek süre değil).
#   yakit   : küçük tank (0,15 L @ 10 km/L) + küçük batarya (1S 300 mAh @ 60 W) → kalkış → GET /sessions power_state ile yakıt/batarya düşüşü; bitince
#             summary.power.fuel.empty_t / elec.empty_t, olay şeridinde kırmızı satır (WS yerine özet + run satırı), uçuş sürer (armed kalır).
import json
import os
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get('DOGRULA_REPO', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PORT = int(os.environ.get('DOGRULA_PORT', '8795'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/flsim/guc')
SITL_DIR = sys.argv[1] if len(sys.argv) > 1 else '/opt/hepgo/sitl/bin-new'
SENARYOLAR = (sys.argv[2] if len(sys.argv) > 2 else 'hiz,speedup,yakit').split(',')
DATA = f'{OUT}/data-{os.path.basename(SITL_DIR)}'
ENV = dict(os.environ, CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL_DIR=SITL_DIR,
           SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '38850'), CAYMAZ_DATA_DIR=DATA, CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
           CAYMAZ_PRINTER_POLL='0', SIM_TERRAIN_SERVE='0')
SRV = None


def kapat():
    global SRV
    if SRV is not None:
        try:
            os.killpg(SRV.pid, signal.SIGTERM)
        except Exception:   # noqa: BLE001
            pass
        try:
            SRV.wait(30)
        except Exception:   # noqa: BLE001
            try:
                os.killpg(SRV.pid, signal.SIGKILL)
            except Exception:   # noqa: BLE001
                pass
        SRV = None
    try:   # artık SITL süreci (yalnız bu betiğin veri dizini) → PID ile kapat
        pids = subprocess.run(['pgrep', '-f', f'{DATA}/sitl_calisma/'], capture_output=True, text=True).stdout.split()
        for p in pids:
            try:
                os.kill(int(p), signal.SIGKILL)
            except Exception:   # noqa: BLE001
                pass
        if pids:
            print('artık SITL kapatıldı:', pids, flush=True)
    except Exception:   # noqa: BLE001
        pass


def ac():
    global SRV
    os.makedirs(DATA, exist_ok=True)
    SRV = subprocess.Popen([f'{REPO}/.venv/bin/uvicorn', 'app.main:app', '--port', str(PORT)], cwd=REPO, env=ENV,
                           stdout=open(f'{OUT}/server-{os.path.basename(SITL_DIR)}.log', 'ab'), stderr=subprocess.STDOUT, start_new_session=True)   # noqa: SIM115
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            urllib.request.urlopen(BASE + '/api/auth/me', timeout=2)
        except urllib.error.HTTPError:
            print('sunucu hazır', round(time.time() - t0, 1), 's', flush=True)
            return
        except Exception:   # noqa: BLE001
            time.sleep(0.5)
    raise SystemExit('sunucu açılmadı')


class Api:
    def __init__(self):
        import http.cookiejar
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(BASE + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        try:
            with self.op.open(r, timeout=60) as resp:
                t = resp.read().decode()
                return resp.status, (json.loads(t) if t and resp.headers.get('content-type', '').startswith('application/json') else t)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]

    def cmd(self, sid, name, params=None):
        return self.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': name, 'params': params or {}})


def oturum_bekle(api, sid, sn=150):
    t0 = time.time()
    while time.time() - t0 < sn:
        st, g = api.req('GET', f'/api/drone/sim/sessions/{sid}')
        if g['state'] in ('HAZIR', 'HATA'):
            return g
        time.sleep(1)
    raise SystemExit('oturum hazır olmadı')


def gcs_ac(port):
    from pymavlink import mavutil
    gcs = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190)
    t0 = time.time()
    hb = None
    while time.time() - t0 < 120 and hb is None:
        gcs.mav.heartbeat_send(6, 8, 0, 0, 0)
        hb = gcs.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if hb is not None and hb.type in (6, 18):
            hb = None
    assert hb is not None, 'araç kalp atışı gelmedi'
    return gcs


def param_oku(gcs, ad, deneme=3):
    for _ in range(deneme):
        gcs.mav.param_request_read_send(1, 1, ad.encode(), -1)
        t1 = time.time()
        while time.time() - t1 < 4:
            m = gcs.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
            if m is not None and str(m.param_id).rstrip('\x00') == ad:
                return m.param_value
    return None


def izle(gcs, sure, api=None, sid=None, rc=None, durdur=None):
    """`sure` sn (gerçek) telemetri toplar: (t, gs, as, alt_rel, mode, armed, tbm). rc verilirse her 1 sn RC override gönderir (REST cmd rc)."""
    from pymavlink import mavutil
    t0 = time.time()
    orn, son_rc, son_hb = [], 0.0, 0.0
    gs = as_ = alt = tbm = None
    mode = armed = None
    while time.time() - t0 < sure:
        now = time.time()
        if now - son_hb >= 1.0:
            son_hb = now
            gcs.mav.heartbeat_send(6, 8, 0, 0, 0)
        if rc is not None and now - son_rc >= 1.0:
            son_rc = now
            api.cmd(sid, 'rc', {'ch': rc})
        m = gcs.recv_match(type=['VFR_HUD', 'GLOBAL_POSITION_INT', 'HEARTBEAT'], blocking=True, timeout=1)
        if m is None:
            continue
        t = m.get_type()
        if t == 'VFR_HUD':
            gs, as_ = m.groundspeed, m.airspeed
        elif t == 'GLOBAL_POSITION_INT':
            alt, tbm = m.relative_alt / 1000.0, m.time_boot_ms
        elif t == 'HEARTBEAT' and m.type not in (6, 18):
            mode, armed = mavutil.mode_string_v10(m), bool(m.base_mode & 128)
        if gs is not None and alt is not None:
            orn.append((round(now - t0, 2), round(gs, 2), round(as_, 2), round(alt, 1), mode, armed, tbm))
            if durdur is not None and durdur(orn[-1]):
                break
    return orn


def oturum_ac(api, c, d, **ek):
    body = {'mode': 'sitl', 'type': 'sabit_kanat', 'center_id': c['id'], 'drone_id': d['id'],
            'world': {'mode': 'procedural', 'seed': 7, 'size_m': 4000, 'time': 'day', 'wind_ms': 0, 'launch': {'method': 'wheels'}}}
    body.update(ek)
    st, s = api.req('POST', '/api/drone/sim/sessions', body)
    assert st == 201, s
    g = oturum_bekle(api, s['id'])
    assert g['state'] == 'HAZIR', g
    return g


def sn_hiz(api, c, d):
    """Tam gaz seviye hız ölçümü: kalkış 120 m → FBWA + gaz %100 70 sn → son 25 sn ortalaması."""
    g = oturum_ac(api, c, d, power={'max_speed_ms': 45, 'fuel_l': 5, 'fuel_km_per_l': 25, 'elec_cells': 4, 'elec_mah': 10000, 'elec_w': 30})
    sid = g['id']
    print(f"[hiz] oturum {sid} speed_scale {g['speed_scale']} power {g['power']}", flush=True)
    gcs = gcs_ac(g['udp_port'])
    time.sleep(6)   # ilk kalp atışında hız parametreleri yazılır
    sitl = {ad: param_oku(gcs, ad) for ad in ('AIRSPEED_MAX', 'AIRSPEED_CRUISE', 'THR_MAX', 'SIM_PLN_THR_MUL')}
    print('[hiz] SITL parametreleri:', sitl, flush=True)
    st, r = api.cmd(sid, 'takeoff', {'alt': 120})
    print('[hiz] takeoff', st, r, flush=True)
    orn = izle(gcs, 60, durdur=lambda o: o[3] > 80)   # 80 m AGL'ye kadar
    print(f'[hiz] kalkış: {round(orn[-1][0], 1) if orn else None} s, alt {orn[-1][3] if orn else None} m, mod {orn[-1][4] if orn else None}', flush=True)
    api.cmd(sid, 'mode', {'mode': 'FBWA'})
    rc = [1500, 1500, 2000, 1500, 0, 0, 0, 0]   # roll/pitch nötr, gaz %100
    orn = izle(gcs, 75, api, sid, rc=rc)
    for k in range(0, 75, 15):
        p = [o for o in orn if k <= o[0] < k + 15]
        if p:
            print(f'[hiz]  t={k:2d}-{k+15:2d}s  yer hızı {statistics.fmean(o[1] for o in p):5.1f} m/s  hava hızı {statistics.fmean(o[2] for o in p):5.1f} m/s  alt {min(o[3] for o in p):6.1f}…{max(o[3] for o in p):6.1f} m  mod {p[-1][4]}', flush=True)
    son = [o for o in orn if o[0] >= 50]
    ozet = {'gs_ort': round(statistics.fmean(o[1] for o in son), 2), 'as_ort': round(statistics.fmean(o[2] for o in son), 2), 'gs_maks': max(o[1] for o in son),
            'alt_son': son[-1][3], 'mod': son[-1][4], 'sitl': sitl, 'speed_scale': g['speed_scale']} if son else {'veri': 'yok'}
    api.cmd(sid, 'rc', {'ch': [0] * 8})
    g2 = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
    ozet['power_state'] = g2.get('power_state')
    st, sm = api.req('GET', f'/api/drone/sim/sessions/{sid}/summary')
    ozet['summary_power'] = (sm or {}).get('power') if st == 200 else None
    print(f'[hiz] ÖZET {json.dumps(ozet, ensure_ascii=False)}', flush=True)
    gcs.close()
    api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    time.sleep(3)
    return ozet


def sn_speedup(api, c, d):
    """SIM_SPEEDUP 4: 120 sn SITL zamanı gerçekte kaç sn; .bin → kayıttan oynatma süresi."""
    g = oturum_ac(api, c, d, rec={'bin': True}, power={'max_speed_ms': 45})
    sid = g['id']
    gcs = gcs_ac(g['udp_port'])
    time.sleep(6)
    st, r = api.cmd(sid, 'speed', {'factor': 4})
    print('[speedup] speed 4', st, r, flush=True)
    time.sleep(2)
    print('[speedup] SITL SIM_SPEEDUP =', param_oku(gcs, 'SIM_SPEEDUP'), 'session.speedup =', api.req('GET', f'/api/drone/sim/sessions/{sid}')[1].get('speedup'), flush=True)
    st, r = api.cmd(sid, 'takeoff', {'alt': 100})
    print('[speedup] takeoff', st, r, flush=True)
    # ARM anı → SITL saatinde 120 sn
    arm_t = None
    t_real0 = time.time()
    tbm0 = None

    def durdur(o):
        nonlocal arm_t, tbm0
        if o[5] and arm_t is None:
            arm_t, tbm0 = time.time(), o[6]
        return arm_t is not None and o[6] - tbm0 >= 120000

    orn = izle(gcs, 180, durdur=durdur)
    gercek = round(time.time() - arm_t, 1) if arm_t else None
    sitl_s = round((orn[-1][6] - tbm0) / 1000.0, 1) if tbm0 else None
    print(f'[speedup] ARM→SITL {sitl_s} sn: gerçek süre {gercek} sn (oran {round(sitl_s / gercek, 2) if gercek else None}); toplam gözlem {round(time.time() - t_real0, 1)} sn; alt {orn[-1][3]} m mod {orn[-1][4]}', flush=True)
    g2 = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
    print('[speedup] power_state', g2.get('power_state'), 'speedup', g2.get('speedup'), flush=True)
    api.cmd(sid, 'speed', {'factor': 1})
    time.sleep(1)
    st, sm = api.req('GET', f'/api/drone/sim/sessions/{sid}/summary')
    ozet = {'sitl_s': sitl_s, 'gercek_s': gercek, 'oran': round(sitl_s / gercek, 2) if gercek and sitl_s else None, 'summary_speedup': (sm or {}).get('power', {}).get('speedup'),
            'summary_duration_s': (sm or {}).get('flight', {}).get('duration_s'), 'armed_s_power': (sm or {}).get('power', {}).get('armed_s')}
    gcs.close()
    st, r = api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    print('[speedup] kapanış', st, r, flush=True)
    log_id = (r.get('bin') or {}).get('log_id') if isinstance(r, dict) else None
    ozet['bin_log_id'] = log_id
    if log_id:
        t0 = time.time()
        durum = None
        while time.time() - t0 < 240:
            st, logs = api.req('GET', '/api/drone/sim/logs')
            lg = next((x for x in (logs if isinstance(logs, list) else logs.get('items', [])) if x['id'] == log_id), None)
            if lg:
                durum = lg
                break
            time.sleep(3)
        print('[speedup] log listesi:', durum, flush=True)
        if durum:
            st, rs = api.req('POST', '/api/drone/sim/sessions', {'mode': 'replay', 'log_id': log_id, 'world': {'mode': 'procedural'}})
            print('[speedup] replay oturumu', st, rs if st != 201 else rs['id'], flush=True)
            if st == 201:
                g3 = oturum_bekle(api, rs['id'])
                ozet['replay'] = {'duration_s': g3['replay'].get('duration_s'), 'frames': g3['replay'].get('frames'), 'takeoff_t': g3['replay'].get('takeoff_t'), 'power': g3.get('power')}
                print('[speedup] replay meta', ozet['replay'], flush=True)
                api.req('DELETE', f"/api/drone/sim/sessions/{rs['id']}")
    print(f'[speedup] ÖZET {json.dumps(ozet, ensure_ascii=False)}', flush=True)
    time.sleep(3)
    return ozet


def sn_yakit(api, c, d):
    """Küçük tank/batarya: düşüş ve bitiş (uyarı), uçuş sürer; ölçümler dron kaydına yazılır."""
    g = oturum_ac(api, c, d, power={'max_speed_ms': 45, 'fuel_l': 0.15, 'fuel_km_per_l': 10, 'elec_cells': 1, 'elec_mah': 300, 'elec_w': 60})
    sid = g['id']
    gcs = gcs_ac(g['udp_port'])
    time.sleep(6)
    api.cmd(sid, 'speed', {'factor': 4})
    st, r = api.cmd(sid, 'takeoff', {'alt': 100})
    print('[yakit] takeoff', st, r, flush=True)
    seri = []
    t0 = time.time()
    while time.time() - t0 < 150:
        time.sleep(3)
        g2 = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
        ps = g2.get('power_state') or {}
        seri.append((round(time.time() - t0, 1), ps.get('fuel'), ps.get('elec')))
        print(f"[yakit] t={seri[-1][0]:5.1f}s yakıt {ps.get('fuel')} batarya {ps.get('elec')}", flush=True)
        if ps.get('fuel', {}).get('empty') and ps.get('elec', {}).get('empty'):
            break
    # armed hâlâ mı? UDP tamponundaki eski kalp atışları atılır (150 sn okunmadı), son 3 sn'nin araç HB'si alınır
    t1 = time.time()
    armed = None
    while time.time() - t1 < 4:
        gcs.mav.heartbeat_send(6, 8, 0, 0, 0)
        hb = gcs.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if hb is not None and hb.type not in (6, 18) and time.time() - t1 > 2.5:
            armed = bool(hb.base_mode & 128)
    st, sm = api.req('GET', f'/api/drone/sim/sessions/{sid}/summary')
    pw = (sm or {}).get('power') or {}
    ozet = {'fuel': pw.get('fuel'), 'elec': pw.get('elec'), 'dist_m': pw.get('dist_m'), 'armed_sonra': armed, 'gozlem': seri[:3] + seri[-2:]}
    gcs.close()
    st, r = api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    time.sleep(2)
    st, run = api.req('GET', '/api/drone/sim/runs')
    it = next((x for x in run['items'] if x['session_id'] == sid), None)
    ozet['run'] = {k: it.get(k) for k in ('fuel_used_l', 'fuel_km_per_l', 'elec_wh', 'elec_w_avg', 'speedup_max')} if it else None
    ozet['drone_power'] = api.req('GET', f"/api/drone/drones/{d['id']}/sim-power")[1].get('options')
    print(f'[yakit] ÖZET {json.dumps(ozet, ensure_ascii=False)}', flush=True)
    return ozet


def main():
    print('SITL dizini:', SITL_DIR, 'senaryolar:', SENARYOLAR, flush=True)
    os.makedirs(OUT, exist_ok=True)
    ac()
    sonuc = {}
    try:
        api = Api()
        st, _ = api.req('POST', '/api/auth/login', {'username': 'admin@test', 'password': 'admin-sifre-1'})
        assert st == 200, st
        api.req('POST', '/api/kvkk/accept-terms', {})
        api.req('POST', '/api/drone/centers', {'name': 'Ankara Merkez', 'lat': 39.925, 'lon': 32.837, 'alt': 900})
        c = api.req('GET', '/api/drone/centers')[1][0]
        api.req('POST', '/api/drone/drones', {'name': 'CAYMAZ Sanal', 'protocol': 'sanal', 'model': 'CAYMAZ sabit kanat'})
        dronlar = api.req('GET', '/api/drone/drones')[1]
        dronlar = dronlar.get('items', dronlar) if isinstance(dronlar, dict) else dronlar
        d = next(x for x in dronlar if x['name'] == 'CAYMAZ Sanal')
        print('power-defaults:', api.req('GET', f"/api/drone/sim/power-defaults?type=sabit_kanat&drone_id={d['id']}")[1], flush=True)
        for sn in SENARYOLAR:
            print(f'=== {sn} ===', flush=True)
            sonuc[sn] = {'hiz': sn_hiz, 'speedup': sn_speedup, 'yakit': sn_yakit}[sn](api, c, d)
        for k, v in sonuc.items():
            print(f'SONUÇ {k}:', json.dumps(v, ensure_ascii=False), flush=True)
        json.dump(sonuc, open(f'{OUT}/sonuc-{os.path.basename(SITL_DIR)}.json', 'w'), ensure_ascii=False, indent=1)
        print('TAMAM', flush=True)
    finally:
        kapat()


if __name__ == '__main__':
    main()
