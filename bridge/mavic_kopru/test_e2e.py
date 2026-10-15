"""Mavic Köprü uçtan uca testi (Linux): geçici HEPGO sunucusu + sahte MAVLink dron (UDP) + köprü (arayüzsüz) + canlı izleyici.
Çalıştırma: cd bridge/mavic_kopru && ../../.venv/bin/python test_e2e.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
from pymavlink import mavutil
from websockets.sync.client import connect

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PY = os.path.join(ROOT, '.venv', 'bin', 'python')


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class FakeDrone(threading.Thread):
    """ArduCopter benzeri: HEARTBEAT/konum yayar, COMMAND_LONG'a ACK, set_mode, görev yükleme el sıkışması."""
    def __init__(self, port):
        super().__init__(daemon=True)
        self.m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=1, source_component=1)
        self.mode, self.armed, self.mission, self.count, self.cmds = 0, False, {}, 0, []
        self.running = True

    def run(self):
        last = 0
        while self.running:
            if time.time() - last > 0.2:
                last = time.time()
                self.m.mav.heartbeat_send(2, 3, (128 if self.armed else 0) | 1, self.mode, 4)
                self.m.mav.global_position_int_send(0, 399000000, 328000000, 950000, 15000, 0, 0, 0, 9000)
            msg = self.m.recv_match(blocking=True, timeout=0.05)
            if not msg:
                continue
            t = msg.get_type()
            if t == 'COMMAND_LONG':
                self.cmds.append(msg.command)
                if msg.command == 400:
                    self.armed = msg.param1 == 1
                if msg.command == 176:
                    self.mode = int(msg.param2)
                self.m.mav.command_ack_send(msg.command, 0)
            elif t == 'MISSION_COUNT':
                self.count, self.mission = msg.count, {}
                self.m.mav.mission_request_int_send(255, 190, 0, 0)
            elif t == 'MISSION_ITEM_INT':
                self.mission[msg.seq] = msg
                if msg.seq + 1 < self.count:
                    self.m.mav.mission_request_int_send(255, 190, msg.seq + 1, 0)
                else:
                    self.m.mav.mission_ack_send(255, 190, 0, 0)


def main():
    port, udp = free_port(), free_port()
    data = tempfile.mkdtemp()
    env = dict(os.environ, CAYMAZ_DATA_DIR=data, CAYMAZ_PRINTER_POLL='0', CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1',
               CAYMAZ_FORCE_PASSWORD_CHANGE='0', CAYMAZ_FORCE_SECURE_COOKIE='0')
    srv = subprocess.Popen([PY, '-m', 'uvicorn', 'app.main:app', '--port', str(port), '--log-level', 'warning'], cwd=ROOT, env=env)
    bridge = None
    try:
        base = f'http://127.0.0.1:{port}'
        for _ in range(120):
            try:
                if httpx.get(base + '/api/meta', timeout=1).status_code < 500:
                    break
            except Exception:
                time.sleep(0.5)
        c = httpx.Client(base_url=base)
        assert c.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}).status_code == 200
        r = c.post('/api/drone/bridges', json={'name': 'Test PC', 'platform': 'windows'}).json()
        code = r['code']
        print('köprü kodu:', code.split('/')[0] + '/…')
        drone = FakeDrone(udp); drone.start()
        benv = dict(os.environ, MAVIC_KOPRU_URL=f'ws://127.0.0.1:{port}/ws/drone/bridge')
        bridge = subprocess.Popen([PY, 'mavic_kopru.py', '--code', code, '--link', f'udp:0.0.0.0:{udp}'], cwd=os.path.dirname(__file__),
                                  env=benv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cookie = c.cookies.get('caymaz_session')
        with connect(f'ws://127.0.0.1:{port}/ws/drone/live', additional_headers={'Cookie': f'caymaz_session={cookie}'}) as live:
            def wait(pred, timeout=20):
                end = time.time() + timeout
                while time.time() < end:
                    try:
                        m = json.loads(live.recv(timeout=max(0.1, end - time.time())))
                    except TimeoutError:
                        break
                    if pred(m):
                        return m
                raise AssertionError('beklenen mesaj gelmedi')
            br = wait(lambda m: m['t'] == 'bridge' and m.get('online'))
            caps = br['info']['caps']
            print('köprü bağlandı, caps:', caps)
            assert 'link' in caps and 'param' in caps
            st = wait(lambda m: m['t'] == 'status' and m['state'].get('lat'))
            bid = st['bridge_id']
            print('telemetri: sysid', st['sysid'], 'konum', st['state']['lat'], st['state']['lon'], 'mod', st['state']['mode'])

            def cmd(name, params=None, timeout=30):
                rid = f'r-{name}-{time.time()}'
                live.send(json.dumps({'t': 'cmd', 'rid': rid, 'bridge_id': bid, 'sysid': 1, 'name': name, 'params': params or {}}))
                res = wait(lambda m: m['t'] == 'res' and m['rid'] == rid, timeout)
                print(f'  {name}: ok={res["ok"]} {json.dumps(res.get("result") or res.get("error"), ensure_ascii=False)[:120]}')
                return res
            assert cmd('arm')['ok'] and drone.armed
            assert cmd('set_mode', {'mode': 'GUIDED'})['ok'] and drone.mode == 4
            assert cmd('takeoff', {'alt_rel_m': 40})['ok'] and 22 in drone.cmds
            items = [{'seq': i, 'frame': 6, 'command': 16, 'current': 0, 'autocontinue': 1, 'param1': 0, 'param2': 0, 'param3': 0, 'param4': 0,
                      'x': 399000000 + i * 1000, 'y': 328000000, 'z': 100.0, 'mission_type': 0} for i in range(25)]
            res = cmd('mission_upload', {'items': items, 'cruise_speed': 15}, 70)
            assert res['ok'] and drone.count == 27 and len(drone.mission) == 27, (drone.count, len(drone.mission))   # ev + hız + 25
            assert cmd('rtl')['ok'] and drone.mode == 6
            assert not cmd('param_set', {'name': 'XYZ', 'value': 1})['ok']   # tip bilinmiyor → type_unknown
            assert cmd('link_open', {'type': 'udp', 'host': '0.0.0.0', 'port': udp, 'sysid': 1})['ok']   # REPLACE
            print('TÜM ADIMLAR GEÇTİ')
    finally:
        if bridge:
            bridge.terminate()
            out = bridge.communicate(timeout=5)[0]
            print('--- köprü çıktısı (son satırlar):'); print('\n'.join(out.splitlines()[-12:]))
        srv.terminate()


if __name__ == '__main__':
    sys.exit(main())
