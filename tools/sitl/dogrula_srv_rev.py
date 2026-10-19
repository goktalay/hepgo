# §20.1 sanal montaj (SIM_SRV_REV) doğrulaması — GERÇEK ArduPilot SITL. Sunucu bu betikten açılır/kapatılır (PID ile; pkill yok).
# Kullanım: dogrula.py <SITL ikili dizini> <senaryo,...>   senaryolar: rev10 rev00 rev10_mask0 copter copter_mask1
#   rev10       : SERVO1_REVERSED=1, SERVO2_REVERSED=0 (CAYMAZ; FUNCTION 4/19) → tekerlekli kalkış → 60 sn (yeni ikili: kararlı beklenir; eski ikili: nötr yol, kararlı)
#   rev00       : 0/0 → 60 sn (eski davranış korunur, SIM_SRV_REV=0)
#   rev10_mask0 : 1/0 ama kalkıştan önce MP ile SIM_SRV_REV=0 yazılır (eski ikili davranışı) → 45 sn (takla beklenir)
#   copter      : çok rotorlu, SERVO1_REVERSED=1 (motor kanalı → bit yok, SITL'e 1 yazılır ama ArduCopter motorlarda REVERSED uygulamaz) → kalkış 20 m → 40 sn kararlı
#   copter_mask1: çok rotorlu, MP ile SIM_SRV_REV=1 zorlanır (motor1 PWM fizikte ters) → kararsızlık beklenir (yamanın copter'da da etkili olduğunun kanıtı)
import os, sys, time, json, subprocess, signal, urllib.request, urllib.error, math, statistics
REPO = '/opt/hepgo/fabrika-yonetim'
PORT = int(os.environ.get('DOGRULA_PORT', '8794'))
BASE = f'http://127.0.0.1:{PORT}'
OUT = os.environ.get('DOGRULA_OUT', '/tmp/flsim/srvrev2')
SITL_DIR = sys.argv[1] if len(sys.argv) > 1 else '/opt/hepgo/sitl/bin-new'
SENARYOLAR = (sys.argv[2] if len(sys.argv) > 2 else 'rev10,rev00,rev10_mask0,copter,copter_mask1').split(',')
DATA = f'{OUT}/data-{os.path.basename(SITL_DIR)}'
ENV = dict(os.environ, CAYMAZ_FORCE_SECURE_COOKIE='0', CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_DRONE_PKG='1', HEPGO_SITL_DIR=SITL_DIR,
           SIM_UDP_BASE=os.environ.get('DOGRULA_UDP', '38750'), CAYMAZ_DATA_DIR=DATA, CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
           CAYMAZ_PRINTER_POLL='0', SIM_TERRAIN_SERVE='0')
SRV = None


def kapat():
    global SRV
    if SRV is not None:
        try: os.killpg(SRV.pid, signal.SIGTERM)
        except Exception: pass
        try: SRV.wait(20)
        except Exception:
            try: os.killpg(SRV.pid, signal.SIGKILL)
            except Exception: pass
        SRV = None
    try:   # artık SITL süreci (yalnız bu betiğin veri dizini) → PID ile kapat
        pids = subprocess.run(['pgrep', '-f', f'{DATA}/sitl_calisma/'], capture_output=True, text=True).stdout.split()
        for p in pids:
            try: os.kill(int(p), signal.SIGKILL)
            except Exception: pass
        if pids: print('artık SITL kapatıldı:', pids, flush=True)
    except Exception: pass


def ac():
    global SRV
    os.makedirs(DATA, exist_ok=True)
    SRV = subprocess.Popen([f'{REPO}/.venv/bin/uvicorn', 'app.main:app', '--port', str(PORT)], cwd=REPO, env=ENV,
                           stdout=open(f'{OUT}/server-{os.path.basename(SITL_DIR)}.log', 'ab'), stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            urllib.request.urlopen(BASE + '/api/auth/me', timeout=2)
        except urllib.error.HTTPError:
            print('sunucu hazır', round(time.time() - t0, 1), 's', flush=True); return
        except Exception:
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
            with self.op.open(r, timeout=30) as resp:
                t = resp.read().decode()
                return resp.status, (json.loads(t) if t and resp.headers.get('content-type', '').startswith('application/json') else t)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]


def oturum_bekle(api, sid, sn=150):
    t0 = time.time()
    while time.time() - t0 < sn:
        st, g = api.req('GET', f'/api/drone/sim/sessions/{sid}')
        if g['state'] in ('HAZIR', 'HATA'):
            return g
        time.sleep(1)
    raise SystemExit('oturum hazır olmadı')


def param_oku(gcs, ad, deneme=3):
    for _ in range(deneme):
        gcs.mav.param_request_read_send(1, 1, ad.encode(), -1)
        t1 = time.time()
        while time.time() - t1 < 4:
            m = gcs.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
            if m is not None and str(m.param_id).rstrip('\x00') == ad:
                return m.param_value
    return None


def param_yaz(gcs, ad, deger, ptype=6):
    for _ in range(3):
        gcs.mav.param_set_send(1, 1, ad.encode(), float(deger), ptype)
        t1 = time.time()
        while time.time() - t1 < 3:
            m = gcs.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.5)
            if m is not None and str(m.param_id).rstrip('\x00') == ad:
                return m.param_value
    return None


def kosu(api, c, d, etiket, tip, sure=60, alt=50, mask_zorla=None):
    from pymavlink import mavutil
    st, s = api.req('POST', '/api/drone/sim/sessions', {'mode': 'sitl', 'type': tip, 'center_id': c['id'], 'drone_id': d['id'],
                                                        'world': {'mode': 'procedural', 'seed': 7, 'size_m': 3000, 'time': 'day', 'wind_ms': 0}})
    assert st == 201, s
    sid = s['id']
    g = oturum_bekle(api, sid)
    print(f'[{etiket}] oturum {sid} {g["state"]} udp {g["udp_port"]} params {g["params"]}', flush=True)
    assert g['state'] == 'HAZIR', g
    parm = open(f"{DATA}/sitl_calisma/{9000 + sid}/varsayilan.parm").read()
    print(f'[{etiket}] varsayilan.parm ilgili satırlar:', [l for l in parm.splitlines() if 'REVERSED' in l or 'SRV_REV' in l or 'FUNCTION' in l], flush=True)
    gcs = mavutil.mavlink_connection(f"udpout:127.0.0.1:{g['udp_port']}", source_system=255, source_component=190)
    t0 = time.time(); hb = None
    while time.time() - t0 < 120 and hb is None:
        gcs.mav.heartbeat_send(6, 8, 0, 0, 0)
        hb = gcs.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if hb is not None and hb.type in (6, 18):
            hb = None
    assert hb is not None, 'araç kalp atışı gelmedi'
    time.sleep(6)   # ilk kalp atışında sunucu kayıtlıları (+SIM_SRV_REV) PARAM_SET ile yazar
    if mask_zorla is not None:
        print(f'[{etiket}] MP ile SIM_SRV_REV={mask_zorla} zorlanıyor → yankı', param_yaz(gcs, 'SIM_SRV_REV', mask_zorla), flush=True)
        time.sleep(1)
    degerler = {ad: param_oku(gcs, ad) for ad in ('SERVO1_REVERSED', 'SERVO2_REVERSED', 'SIM_SRV_REV', 'SERVO1_FUNCTION', 'SERVO2_FUNCTION')}
    print(f'[{etiket}] SITL değerleri:', degerler, flush=True)
    g = api.req('GET', f'/api/drone/sim/sessions/{sid}')[1]
    print(f'[{etiket}] params alanı:', g['params'], flush=True)
    if tip != 'sabit_kanat':   # çok rotorlu: EKF konum tahmini (PreArm: Need Position Estimate) için bekle — GPS_RAW fix≥3 + 25 sn
        tb = time.time(); fix = None; ekf = None; gpos = None
        while time.time() - tb < 120:
            gcs.mav.heartbeat_send(6, 8, 0, 0, 0)
            m = gcs.recv_match(type=['GPS_RAW_INT', 'EKF_STATUS_REPORT', 'GLOBAL_POSITION_INT'], blocking=True, timeout=1)
            if m is None: continue
            if m.get_type() == 'GPS_RAW_INT': fix = m.fix_type
            elif m.get_type() == 'EKF_STATUS_REPORT': ekf = m.flags
            else: gpos = (m.lat, m.lon)
            if ekf is not None and (ekf & 0x08) and (ekf & 0x10) and time.time() - tb > 20: break   # EKF_POS_HORIZ_REL | EKF_POS_HORIZ_ABS
        print(f'[{etiket}] EKF bekleme {round(time.time() - tb, 1)} s, fix {fix}, ekf_flags {ekf:#x} gpos {gpos}', flush=True)
    if tip != 'sabit_kanat':
        st, r = api.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': 'mode', 'mode': 'GUIDED'}); print(f'[{etiket}] mode GUIDED', st, r, flush=True)
        st, r = api.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': 'arm'}); print(f'[{etiket}] arm', st, r, flush=True)
        time.sleep(2)
    st, r = api.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': 'takeoff', 'alt': alt})
    print(f'[{etiket}] takeoff', st, r, flush=True)
    t0 = time.time()
    orn = []   # (t, roll°, pitch°, alt_rel m, mode, armed)
    son_att, son_pos, mode, armed = None, None, None, None
    statustext = []
    tekrar = 0
    while time.time() - t0 < sure:
        if tip != 'sabit_kanat' and not armed and time.time() - t0 > 12 * (tekrar + 1) and tekrar < 3:   # ARM olmadıysa kalkışı yinele
            tekrar += 1
            st, r = api.req('POST', f'/api/drone/sim/sessions/{sid}/cmd', {'name': 'takeoff', 'alt': alt})
            print(f'[{etiket}] takeoff tekrar {tekrar}', st, r, flush=True)
        gcs.mav.heartbeat_send(6, 8, 0, 0, 0) if int((time.time() - t0) * 10) % 10 == 0 else None
        m = gcs.recv_match(type=['ATTITUDE', 'GLOBAL_POSITION_INT', 'HEARTBEAT', 'STATUSTEXT'], blocking=True, timeout=1)
        if m is None:
            continue
        t = m.get_type()
        if t == 'ATTITUDE':
            son_att = (math.degrees(m.roll), math.degrees(m.pitch))
        elif t == 'GLOBAL_POSITION_INT':
            son_pos = m.relative_alt / 1000.0
        elif t == 'HEARTBEAT' and m.type not in (6, 18):
            mode = mavutil.mode_string_v10(m); armed = bool(m.base_mode & 128)
        elif t == 'STATUSTEXT':
            statustext.append((round(time.time() - t0, 1), m.text))
        if son_att is not None and son_pos is not None:
            orn.append((round(time.time() - t0, 2), round(son_att[0], 1), round(son_att[1], 1), round(son_pos, 1), mode, armed))
    print(f'[{etiket}] örnek sayısı {len(orn)}; son mod {mode} armed {armed}', flush=True)
    for k in range(0, sure, 5):
        p = [o for o in orn if k <= o[0] < k + 5]
        if not p: continue
        rolls = [o[1] for o in p]; alts = [o[3] for o in p]
        print(f'[{etiket}]  t={k:2d}-{k+5:2d}s  roll min/maks/σ {min(rolls):6.1f}/{max(rolls):6.1f}/{statistics.pstdev(rolls):5.1f}°  pitch {statistics.fmean(o[2] for o in p):5.1f}°  alt_rel {min(alts):6.1f}…{max(alts):6.1f} m  mod {p[-1][4]}', flush=True)
    son = [o for o in orn if o[0] >= sure - 30]
    if son:
        rolls = [abs(o[1]) for o in son]; alts = [o[3] for o in son]
        ozet = {'son30_roll_maks': round(max(rolls), 1), 'son30_roll_sigma': round(statistics.pstdev([o[1] for o in son]), 1), 'son30_alt_min': min(alts), 'son30_alt_maks': max(alts),
                'takla': any(abs(o[1]) > 90 for o in orn), 'maks_abs_roll': round(max(abs(o[1]) for o in orn), 1), 'son_mod': mode, 'armed': armed,
                'hit_ground': any('Hit ground' in s[1] for s in statustext), 'sitl': degerler, 'params': g['params']}
    else:
        ozet = {'veri': 'yok'}
    print(f'[{etiket}] ÖZET {json.dumps(ozet, ensure_ascii=False)}', flush=True)
    onemli = [s for s in statustext if any(k in s[1].lower() for k in ('hit ground', 'crash', 'disarm', 'takeoff', 'arm', 'reverse', 'srv_rev'))]
    print(f'[{etiket}] STATUSTEXT (seçili):', onemli[:20], flush=True)
    gcs.close()
    api.req('DELETE', f'/api/drone/sim/sessions/{sid}')
    time.sleep(3)
    return ozet


def main():
    print('SITL dizini:', SITL_DIR, 'senaryolar:', SENARYOLAR, flush=True)
    ac()
    sonuc = {}
    try:
        api = Api()
        st, _ = api.req('POST', '/api/auth/login', {'username': 'admin@test', 'password': 'admin-sifre-1'}); assert st == 200, st
        api.req('POST', '/api/kvkk/accept-terms', {})
        api.req('POST', '/api/drone/centers', {'name': 'Ankara Merkez', 'lat': 39.925, 'lon': 32.837, 'alt': 900})   # varsa 400 (önceki koşunun verisi)
        c = api.req('GET', '/api/drone/centers')[1][0]
        api.req('POST', '/api/drone/drones', {'name': 'CAYMAZ Sanal', 'protocol': 'sanal', 'model': 'CAYMAZ sabit kanat'})
        api.req('POST', '/api/drone/drones', {'name': 'Quad Sanal', 'protocol': 'sanal', 'model': 'Quad X'})
        dronlar = api.req('GET', '/api/drone/drones')[1]
        dronlar = dronlar.get('items', dronlar) if isinstance(dronlar, dict) else dronlar
        d = next(x for x in dronlar if x['name'] == 'CAYMAZ Sanal'); q = next(x for x in dronlar if x['name'] == 'Quad Sanal')
        P = f"/api/drone/drones/{d['id']}/sitl-params"
        Q = f"/api/drone/drones/{q['id']}/sitl-params"
        for sn in SENARYOLAR:
            if sn in ('rev10', 'rev10_mask0'):
                st, im = api.req('POST', f'{P}/import', {'text': 'SERVO1_REVERSED,1\nSERVO2_REVERSED,0\nSERVO1_FUNCTION,4\nSERVO2_FUNCTION,19\n'})
            elif sn == 'rev00':
                st, im = api.req('POST', f'{P}/import', {'text': 'SERVO1_REVERSED,0\nSERVO2_REVERSED,0\nSERVO1_FUNCTION,4\nSERVO2_FUNCTION,19\n'})
            else:
                st, im = api.req('POST', f'{Q}/import', {'text': 'SERVO1_REVERSED,1\n'})
            print(f'=== {sn} === içe aktarım', st, im, flush=True)
            print('liste mount:', api.req('GET', Q if sn.startswith('copter') else P)[1]['mount'], flush=True)
            if sn == 'rev10':
                sonuc[sn] = kosu(api, c, d, sn, 'sabit_kanat', 60)
            elif sn == 'rev00':
                sonuc[sn] = kosu(api, c, d, sn, 'sabit_kanat', 60)
            elif sn == 'rev10_mask0':
                sonuc[sn] = kosu(api, c, d, sn, 'sabit_kanat', 45, mask_zorla=0)
            elif sn == 'copter':
                sonuc[sn] = kosu(api, c, q, sn, 'multirotor', 60, alt=20)
            elif sn == 'copter_mask1':
                sonuc[sn] = kosu(api, c, q, sn, 'multirotor', 60, alt=20, mask_zorla=1)
        st, lst = api.req('GET', P)
        print('CAYMAZ kayıt sonrası değerler (korunmalı):', {x['name']: (x['value'], x['mount']) for x in lst['items']}, flush=True)
        for k, v in sonuc.items():
            print(f'SONUÇ {k}:', json.dumps({a: b for a, b in v.items() if a not in ('params', 'sitl')}, ensure_ascii=False), flush=True)
        print('TAMAM', flush=True)
    finally:
        kapat()


if __name__ == '__main__':
    main()
