"""Uçuş Simülatörü §42 — UÇUŞ UYARILARI gerçek ArduCopter SITL senaryosu (HEPGO API + WS): kalkış → ALT_HOLD'da tam sağ yatış (BANK ANGLE;
kopter ANGLE_MAX 30° olduğundan eşik ayarla 25°) → STABILIZE'da gaz kesilip serbest düşüş (PULL UP / SINK RATE / DON'T SINK) → gaz verip toparlama.
Tüm `tele` kareleri toplanır ve İSTEMCİ değerlendiricisi (static/js/modules/flightsim_gpws.js, node) ile işlenir:
  • beklenen uyarılar açılır (BANK_ANGLE, PULL_UP),
  • normal evrelerde (yerde, kalkış, düz askı) YANLIŞ ALARM yok; gerçek SITL sağlık bitleri / EKF / titreşimle IMU_FAULT yok,
  • yeni tele alanları (sens_bad, ekf, vibe) akıyor; bölümler `cmd gpws` ile gönderilince özet raporda `alerts` + disiplin puanı.

Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin .venv/bin/python -m tests.test_flightsim_gpws_sitl   (~1–2 dk)
"""
import faulthandler
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

faulthandler.dump_traceback_later(420, exit=True)
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(prefix='gpws-sitl-'), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE='26150', SIM_MAX_SESSIONS='1', SIM_TERRAIN_SERVE='0', GOOGLE_MAPS_API_KEY='')
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')

from fastapi.testclient import TestClient  # noqa: E402

from app import flightsim  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_flightsim_match import Kullanici, bekle, ok  # noqa: E402

KOK = Path(__file__).resolve().parent.parent
MERKEZ = {'lat': 39.925, 'lon': 32.837, 'alt': 900.0}
NOTR = [1500, 1500, 1500, 1500, 1800, 0, 0, 0]


class Akis:
    def __init__(self, ws):
        self.ws, self.tele, self.kareler, self.faz, self.rc = ws, None, [], 'yer', None
        self._rc_son = 0.0

    def pump(self, sn, kosul=None):
        son = time.time() + sn
        while time.time() < son:
            if self.rc and time.time() - self._rc_son > 0.2:   # RC override ArduPilot'ta ~1 sn'de düşer → 5 Hz yinele
                self.ws.send_text(json.dumps({'t': 'cmd', 'rid': 'rc', 'name': 'rc', 'params': {'ch': self.rc}}))
                self._rc_son = time.time()
            m = json.loads(self.ws.receive_text())
            if m.get('t') == 'tele':
                self.tele = m
                self.kareler.append({**m, '_faz': self.faz})
            if kosul and self.tele and kosul(self.tele):
                return True
        return False

    def cmd(self, name, params=None):
        self.ws.send_text(json.dumps({'t': 'cmd', 'rid': f'{name}-{time.time()}', 'name': name, 'params': params or {}}))


def degerlendir(kareler):
    """İstemci değerlendiricisi (node): kare başına etkin kodlar + bölümler."""
    yol = Path(tempfile.mkdtemp()) / 'kareler.json'
    yol.write_text(json.dumps(kareler))
    kod = """
import('./static/js/modules/flightsim_gpws.js').then(m => {
  const K = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'));
  const g = m.createGpws({ vehicle: 'multirotor', cfg: { bank_copter: 25 } });
  const per = [];
  for (const k of K) { const r = g.step(m.teleInput(k)); per.push({ faz: k._faz, codes: r.active.map(a => a.code), t: k.tbm / 1000 }); }
  g.close();
  process.stdout.write(JSON.stringify({ per, episodes: g.episodes(), summary: g.summary() }));
});"""
    r = subprocess.run(['node', '-e', kod, str(yol)], cwd=KOK, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def main():
    S = '/api/drone/sim/sessions'
    with TestClient(app, base_url='https://testserver') as tc:
        a = Kullanici(tc, 'admin@test', 'admin-sifre-1')
        c1 = ok(a.post('/api/drone/centers', json={'name': 'GPWS SITL', **MERKEZ}))
        s = ok(a.post(S, json={'type': 'multirotor', 'center_id': c1['id']}), 201)
        sid = s['id']
        try:
            print('ArduCopter SITL başlatılıyor…')
            assert bekle(lambda: ok(a.get(f'{S}/{sid}'))['state'] == 'HAZIR', 120), ok(a.get(f'{S}/{sid}'))
            with a.websocket_connect(f'/ws/drone/sim/{sid}') as ws:
                A = Akis(ws)
                A.pump(3)
                # ARM (EKF hazır olana dek yinele) + GUIDED kalkış 70 m
                t0 = time.time()
                while time.time() - t0 < 120 and not (A.tele or {}).get('armed'):
                    A.cmd('mode', {'mode': 'GUIDED'}); A.cmd('arm')
                    A.pump(3, lambda t: t.get('armed'))
                assert (A.tele or {}).get('armed'), 'ARM olmadı'
                A.faz = 'kalkis'
                A.cmd('takeoff', {'alt': 70})
                assert A.pump(60, lambda t: (t.get('alt_rel') or 0) >= 66), f"kalkış: {A.tele.get('alt_rel')}"
                print(f"  kalkış tamam: {A.tele['alt_rel']:.1f} m · sens_bad={A.tele.get('sens_bad')} ekf={A.tele.get('ekf')} vibe={A.tele.get('vibe')}")
                A.faz = 'aski'
                A.pump(4)
                # BANK ANGLE: ALT_HOLD + tam sağ yatış
                A.faz = 'yatis'
                A.rc = [2000, 1500, 1500, 1500, 1800, 0, 0, 0]
                A.cmd('mode', {'mode': 'ALT_HOLD'})
                A.pump(5)
                roll_max = max(abs(k['roll']) for k in A.kareler if k['_faz'] == 'yatis') * 57.2958
                print(f'  yatış: en büyük {roll_max:.1f}°')
                A.rc = NOTR
                A.faz = 'duzel'
                A.pump(4)
                # PULL UP: STABILIZE + gaz kesik → serbest düşüş; 35 m altında tam gaz ile toparla
                A.faz = 'dusus'
                A.rc = [1500, 1500, 1000, 1500, 1800, 0, 0, 0]
                A.cmd('mode', {'mode': 'STABILIZE'})
                A.pump(12, lambda t: (t.get('alt_rel') or 99) < 35)
                vd_max = max((k.get('vd') or 0) for k in A.kareler if k['_faz'] == 'dusus')
                print(f"  düşüş: {A.tele['alt_rel']:.1f} m · en büyük alçalma {vd_max:.1f} m/s")
                A.faz = 'toparla'
                A.rc = [1500, 1500, 1950, 1500, 1800, 0, 0, 0]
                A.pump(5)
                A.cmd('mode', {'mode': 'LAND'}); A.rc = None
                A.pump(2)
            sonuc = degerlendir(A.kareler)
            per = sonuc['per']
            fazlar = {}
            for p in per:
                fazlar.setdefault(p['faz'], set()).update(p['codes'])
            print('  faz → uyarılar:', {k: sorted(v) for k, v in fazlar.items()})
            print('  bölümler:', [(e['code'], e['dur_s']) for e in sonuc['episodes']])
            assert not fazlar.get('yer') and not fazlar.get('kalkis') and not fazlar.get('aski'), f'yanlış alarm: {fazlar}'
            assert 'BANK_ANGLE' in fazlar.get('yatis', set()), fazlar
            assert 'PULL_UP' in fazlar.get('dusus', set()) | fazlar.get('toparla', set()), fazlar
            assert 'IMU_FAULT' not in set().union(*fazlar.values()), 'gerçek SITL’de IMU yanlış alarmı'
            assert any(k.get('ekf') is not None for k in A.kareler) and any(k.get('vibe') is not None for k in A.kareler) and any('sens_bad' in k for k in A.kareler)
            # sunucuya bildir → özet
            ev = sonuc['episodes']
            for i in range(0, len(ev), 50):
                ok(a.post(f'{S}/{sid}/cmd', json={'name': 'gpws', 'params': {'cfg': {'mode': 'full', 'off': []}, 'events': ev[i:i + 50]}}))
            sm = ok(a.get(f'{S}/{sid}/summary'))
            A2 = sm['alerts']
            assert A2['warnings'] >= 2 and A2['by_code'].get('BANK_ANGLE') and A2['by_code'].get('PULL_UP') and A2['score'] == sonuc['summary']['score'], (A2, sonuc['summary'])
            print(f"  özet: kırmızı {A2['warnings']} · sarı {A2['cautions']} · disiplin {A2['score']} ({A2['grade']})")
        finally:
            if flightsim.MANAGER.get(sid) is not None:
                a.delete(f'{S}/{sid}')
    print('test_flightsim_gpws_sitl: TAMAM')


if __name__ == '__main__':
    main()
