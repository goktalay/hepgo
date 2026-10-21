"""§35 "Sıfırla" korunumu + Mission Planner bağlantısı + ağır çekim + kamera yok — GERÇEK ArduPilot SITL ile (docs/ucus-simulatoru.md §35).

Kanıtlananlar:
  1) Oturum içinde Mission Planner'dan (UDP, pymavlink ile taklit) yazılan parametreler reset sonrası YENİ SITL sürecinde korunur: eeprom'da kalan
     (BATT_CAPACITY) ve oturumun kalp atışında kendi değerini yazdığı ad (RC_OVERRIDE_TIME: HEPGO 3 yazar, MP 5 → reset sonrası yine 5);
     SITL çalışma dizinindeki scripts/ ve APM/scripts/ dosyaları reset'te durur; YENİ OTURUM ise temiz başlar (eeprom + scriptler silinir).
  2) SIM_SPEEDUP 0,5× (ağır çekim) gerçek SITL'de çalışır: time_boot_ms / duvar saati ≈ 0,5; reset sonrası hız korunur.
  3) Kamera 'none' sunucuda kabul edilir (oturum/to_dict), geçersiz tür 400.
  4) Reset sırasında MP bağlantısı KOPMAZ: aynı UDP portu, GCS adresi unutulmaz, SITL yokken köprü aynı sysid'le 1 Hz kalp atışı gönderir
     (en uzun kalp atışı boşluğu < 2,5 sn), reset sonrası yeni SITL'den PARAM_VALUE/ATTITUDE gelir; MP'nin yüklediği görev de korunur.
  5) Sabit kanat (elevon düzeni): düzen parametreleri (SERVOn_FUNCTION/REVERSED, MIXING_GAIN) reset sonrası aynı; MP'nin değiştirdiği düzen
     parametresi (MIXING_GAIN) reset'te oturum setinin üstüne yeniden yazılır.
Çalıştırma: HEPGO_SITL_DIR=/opt/hepgo/sitl/bin CAYMAZ_FORCE_SECURE_COOKIE=0 .venv/bin/python -m tests.test_flightsim_resetkeep
"""
import faulthandler
import os
import shutil
import tempfile
import threading
import time

faulthandler.dump_traceback_later(900, exit=True)
os.environ.setdefault('HEPGO_SITL_DIR', '/opt/hepgo/sitl/bin')
os.environ.update(CAYMAZ_DRONE_PKG='1', CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0', CAYMAZ_FORCE_SECURE_COOKIE='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0',
                  HEPGO_SITL='1', SIM_UDP_BASE='26650', SIM_MAX_SESSIONS='2', SIM_TERRAIN_SERVE='0')

from fastapi.testclient import TestClient  # noqa: E402
from pymavlink import mavutil  # noqa: E402

from app import drone_sitl, flightsim  # noqa: E402
from app.main import app  # noqa: E402


def ok(r, code=200):
    assert r.status_code == code, (r.request.url, r.status_code, r.text)
    return r.json()


def bekle(kosul, sn, adim=0.2, mesaj=''):
    son = time.time() + sn
    while time.time() < son:
        if kosul():
            return True
        time.sleep(adim)
    raise AssertionError(f'zaman aşımı ({sn} sn): {mesaj}')


class SahteMP:
    """Mission Planner taklidi: UDP istemcisi (udpout), 1 Hz GCS kalp atışı; gelen her mesaj (zaman, tür, sysid, mesaj) kaydedilir."""

    def __init__(self, port):
        self.c = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=255, source_component=190, dialect='ardupilotmega')
        self.kayit = []
        self.kilit = threading.Lock()
        self.dur = False
        self.t1 = threading.Thread(target=self._kalp, daemon=True)
        self.t2 = threading.Thread(target=self._al, daemon=True)
        self.t1.start()
        self.t2.start()

    def _kalp(self):
        while not self.dur:
            try:
                self.c.mav.heartbeat_send(6, 8, 0, 0, 4)   # MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID
            except OSError:
                pass
            time.sleep(1.0)

    def _al(self):
        while not self.dur:
            try:
                m = self.c.recv_match(blocking=True, timeout=0.5)
            except Exception:   # noqa: BLE001
                continue
            if m is None or m.get_type() == 'BAD_DATA':
                continue
            with self.kilit:
                self.kayit.append((time.time(), m.get_type(), m.get_srcSystem(), m))

    def mesajlar(self, tur, t0=0.0):
        with self.kilit:
            return [x for x in self.kayit if x[1] == tur and x[0] >= t0]

    def param_oku(self, ad, sn=15):
        """PARAM_REQUEST_READ → aynı adlı PARAM_VALUE (yeniden dener)."""
        son = time.time() + sn
        while time.time() < son:
            t0 = time.time()
            self.c.mav.param_request_read_send(1, 1, ad.encode(), -1)
            bitis = time.time() + 1.5
            while time.time() < bitis:
                for _, _, _, m in self.mesajlar('PARAM_VALUE', t0):
                    if str(m.param_id).rstrip('\x00') == ad:
                        return float(m.param_value)
                time.sleep(0.05)
        raise AssertionError(f'MP: {ad} okunamadı')

    def param_yaz(self, ad, deger, ptype=9):
        son = time.time() + 15
        while time.time() < son:
            self.c.mav.param_set_send(1, 1, ad.encode(), float(deger), ptype)
            try:
                if abs(self.param_oku(ad, 3) - float(deger)) < 1e-4:
                    return
            except AssertionError:
                pass
        raise AssertionError(f'MP: {ad} = {deger} yazılamadı')

    def gorev_yukle(self, noktalar):
        """MAVLink görev protokolü (MP gibi): MISSION_COUNT → MISSION_REQUEST(_INT) → MISSION_ITEM_INT … → MISSION_ACK. Sıra 0 = ev."""
        t0 = time.time()
        n = len(noktalar) + 1
        self.c.mav.mission_count_send(1, 1, n, 0)
        gonderilen = set()
        son = time.time() + 20
        while time.time() < son:
            for _, tur, _, m in self.mesajlar('MISSION_REQUEST_INT', t0) + self.mesajlar('MISSION_REQUEST', t0):
                if m.seq in gonderilen:
                    continue
                gonderilen.add(m.seq)
                lat, lon, alt = (39.925, 32.837, 0) if m.seq == 0 else noktalar[m.seq - 1]
                self.c.mav.mission_item_int_send(1, 1, m.seq, 3 if m.seq else 0, 16, 0, 1, 0, 0, 0, 0, int(lat * 1e7), int(lon * 1e7), alt, 0)
            ack = [m for _, _, _, m in self.mesajlar('MISSION_ACK', t0)]
            if ack:
                assert ack[-1].type == 0, ack[-1]
                return
            time.sleep(0.05)
        raise AssertionError('MP: görev yüklenemedi')

    def gorev_sayisi(self):
        son = time.time() + 15
        while time.time() < son:
            t0 = time.time()
            self.c.mav.mission_request_list_send(1, 1, 0)
            time.sleep(1.0)
            c = [m for _, _, _, m in self.mesajlar('MISSION_COUNT', t0)]
            if c:
                self.c.mav.mission_ack_send(1, 1, 0, 0)   # indirmeyi bırak (öğeleri istemiyoruz)
                return c[-1].count
        raise AssertionError('MP: MISSION_COUNT yok')

    def kapat(self):
        self.dur = True
        self.t1.join(2)
        self.t2.join(2)
        self.c.close()


def hazir(s):
    return s.state == 'HAZIR' and s._heartbeat_alindi


def oran_olc(mp, sn=6.0):
    """MP'ye gelen ATTITUDE time_boot_ms artışı / duvar saati (SITL zaman oranı)."""
    t0 = time.time()
    time.sleep(sn)
    att = [x for x in mp.mesajlar('ATTITUDE', t0) if x[2] == 1]
    assert len(att) > 5, len(att)
    (w0, _, _, a), (w1, _, _, b) = att[0], att[-1]
    return (b.time_boot_ms - a.time_boot_ms) / 1000.0 / (w1 - w0)


def main():
    assert flightsim.SITL_ENABLED and drone_sitl.ikili_yolu('multirotor').is_file(), 'gerçek SITL ikilisi gerekli (HEPGO_SITL_DIR)'
    with TestClient(app, base_url='https://testserver') as a:
        ok(a.post('/api/auth/login', json={'username': 'admin@test', 'password': 'admin-sifre-1'}))
        c = ok(a.post('/api/drone/centers', json={'name': 'Reset Merkezi', 'lat': 39.925, 'lon': 32.837, 'alt': 900}))
        # 3) kamera 'none' kabul; geçersiz tür 400
        assert a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c['id'], 'world': {'mode': 'procedural'}, 'camera': 'yok'}).status_code == 400
        s0 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c['id'], 'world': {'mode': 'procedural'}, 'camera': 'none'}), 201)
        sid = s0['id']
        s = flightsim.MANAGER.get(sid)
        assert s.camera == 'none' and ok(a.get(f'/api/drone/sim/sessions/{sid}'))['camera'] == 'none'
        bekle(lambda: hazir(s), 90, mesaj='SITL kalp atışı')
        port, kimlik = s.udp_port, s.kimlik
        dizin = drone_sitl.calisma_dizini(kimlik)
        print('oturum', sid, 'UDP', port, 'dizin', dizin)
        mp = SahteMP(port)
        try:
            bekle(lambda: any(x[2] == 1 for x in mp.mesajlar('HEARTBEAT')), 20, mesaj='MP: araç kalp atışı')
            bekle(lambda: s.gcs_addr is not None, 10, mesaj='GCS kilidi')
            gcs0 = s.gcs_addr
            # 1) MP'den parametre + scriptler
            assert mp.param_oku('RC_OVERRIDE_TIME') == 3.0   # HEPGO oturum seti
            mp.param_yaz('BATT_CAPACITY', 4321)
            mp.param_yaz('RC_OVERRIDE_TIME', 5)
            assert 'BATT_CAPACITY' in s.oturum_paramlari and s.oturum_paramlari['RC_OVERRIDE_TIME'][0] == 5.0, s.oturum_paramlari
            for alt in ('scripts', 'APM/scripts'):
                (dizin / alt).mkdir(parents=True, exist_ok=True)
                (dizin / alt / 'hepgo_test.lua').write_text('-- §35 reset testi\nfunction update() return update, 1000 end\nreturn update()\n')
            # 2) ağır çekim 0,5×
            assert a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 0.3}}).status_code == 400
            assert ok(a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 0.25}}))['factor'] == 0.25
            bekle(lambda: s.guc.speedup == 0.25, 10, mesaj='SIM_SPEEDUP 0,25 yankısı')
            r = oran_olc(mp, 8.0)
            print('0,25× ölçülen SITL zaman oranı', round(r, 3))
            assert 0.17 < r < 0.33, r
            assert ok(a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'speed', 'params': {'factor': 0.5}}))['factor'] == 0.5
            bekle(lambda: s.guc.speedup == 0.5, 10, mesaj='SIM_SPEEDUP yankısı')
            r = oran_olc(mp)
            print('0,5× ölçülen SITL zaman oranı', round(r, 3))
            assert 0.38 < r < 0.62, r
            mp.gorev_yukle([(39.926, 32.838, 30), (39.927, 32.839, 30)])
            assert mp.gorev_sayisi() == 3
            pid0 = s.sitl['pid']
            # 4) reset: MP bağlı kalır
            t_reset = time.time()
            ok(a.post(f'/api/drone/sim/sessions/{sid}/cmd', json={'name': 'reset', 'params': {}}))
            assert s.state == 'HAZIR' and s.sitl['pid'] != pid0, (s.state, s.sitl)
            bekle(lambda: hazir(s), 60, mesaj='reset sonrası SITL kalp atışı')
            time.sleep(3)
            assert s.udp_port == port and s.gcs_addr == gcs0, (s.udp_port, port, s.gcs_addr, gcs0)
            hb = [x[0] for x in mp.mesajlar('HEARTBEAT', t_reset - 3) if x[2] == 1]
            bosluk = max(b - a_ for a_, b in zip(hb, hb[1:]))
            print('reset sırasında en uzun araç kalp atışı boşluğu', round(bosluk, 2), 'sn; köprü kalp atışı', s.kopru_kalp_sayac)
            assert bosluk < 2.5, bosluk
            assert s.kopru_kalp_sayac >= 2, s.kopru_kalp_sayac
            assert any('yeniden' in str(x[3].text) for x in mp.mesajlar('STATUSTEXT', t_reset)), 'köprü STATUSTEXT'
            assert any(x[2] == 1 for x in mp.mesajlar('ATTITUDE', time.time() - 2)), 'reset sonrası telemetri'
            # parametreler yeni SITL'de (MP üzerinden okunur)
            assert mp.param_oku('BATT_CAPACITY') == 4321.0
            assert mp.param_oku('RC_OVERRIDE_TIME') == 5.0
            assert abs(mp.param_oku('SIM_SPEEDUP') - 0.5) < 1e-6
            assert mp.gorev_sayisi() == 3   # görev de eeprom'da (ArduPilot depolaması) → yeni SITL'de yüklü
            assert s.guc.speedup == 0.5
            r = oran_olc(mp, 5.0)
            print('reset sonrası SITL zaman oranı', round(r, 3))
            assert 0.38 < r < 0.62, r
            for alt in ('scripts', 'APM/scripts'):
                assert (dizin / alt / 'hepgo_test.lua').is_file(), alt
            assert (dizin / 'eeprom.bin').is_file()
            print('reset: parametreler + scriptler korundu, MP bağlantısı kopmadı')
        finally:
            mp.kapat()
        ok(a.delete(f'/api/drone/sim/sessions/{sid}'))
        # yeni oturum: TEMİZ başlar (eeprom + scriptler silinir). Yuvalar sunucu yeniden başlayınca yeniden kullanılır → sıradaki yuvanın dizinine
        # önceki oturumun eeprom.bin + scriptleri kopyalanır (yeniden kullanım taklidi)
        for k in (kimlik + 1, kimlik + 2):
            shutil.copytree(dizin, drone_sitl.calisma_dizini(k), dirs_exist_ok=True)
        s1 = ok(a.post('/api/drone/sim/sessions', json={'type': 'multirotor', 'center_id': c['id'], 'world': {'mode': 'procedural'}}), 201)
        s = flightsim.MANAGER.get(s1['id'])
        bekle(lambda: hazir(s), 90, mesaj='yeni oturum SITL')
        assert s.kimlik in (kimlik + 1, kimlik + 2), s.kimlik
        for alt in ('scripts', 'APM/scripts'):
            assert not (drone_sitl.calisma_dizini(s.kimlik) / alt).exists(), alt
        mp = SahteMP(s.udp_port)
        try:
            bekle(lambda: any(x[2] == 1 for x in mp.mesajlar('HEARTBEAT')), 20, mesaj='MP: yeni oturum')
            assert mp.param_oku('BATT_CAPACITY') != 4321.0   # önceki oturumun eeprom'u silindi
            assert mp.param_oku('RC_OVERRIDE_TIME') == 3.0
            assert s.oturum_paramlari == {}
            print('yeni oturum temiz başladı (önceki eeprom + scriptler silindi)')
        finally:
            mp.kapat()
        ok(a.delete(f"/api/drone/sim/sessions/{s1['id']}"))

        # 5) sabit kanat elevon: düzen parametreleri reset'te bozulmaz; MP'nin düzen değişikliği korunur
        s2 = ok(a.post('/api/drone/sim/sessions', json={'type': 'sabit_kanat', 'center_id': c['id'], 'world': {'mode': 'procedural'}, 'layout': 'elevon'}), 201)
        s = flightsim.MANAGER.get(s2['id'])
        bekle(lambda: hazir(s), 120, mesaj='ArduPlane SITL')
        mp = SahteMP(s.udp_port)
        try:
            bekle(lambda: any(x[2] == 1 for x in mp.mesajlar('HEARTBEAT')), 20, mesaj='MP: uçak')
            time.sleep(2)
            adlar = [ad for ad, _ in flightsim.LAYOUT_PARAMLARI['elevon']]
            once = {ad: mp.param_oku(ad) for ad in adlar}
            assert once['SERVO1_FUNCTION'] == 78.0 and once['SERVO2_FUNCTION'] == 77.0, once
            srv0 = mp.param_oku('SIM_SRV_REV') if s.sanal_montaj else None
            mp.param_yaz('MIXING_GAIN', 0.7)
            ok(a.post(f"/api/drone/sim/sessions/{s2['id']}/cmd", json={'name': 'reset', 'params': {}}))
            bekle(lambda: hazir(s), 90, mesaj='uçak reset')
            time.sleep(3)
            sonra = {ad: mp.param_oku(ad) for ad in adlar}
            beklenen = {**once, 'MIXING_GAIN': 0.7}
            assert all(abs(sonra[k] - beklenen[k]) < 1e-4 for k in adlar), (sonra, beklenen)
            if srv0 is not None:
                assert mp.param_oku('SIM_SRV_REV') == srv0
            print('sabit kanat elevon: düzen parametreleri korundu', sonra, 'SIM_SRV_REV', srv0)
        finally:
            mp.kapat()
        ok(a.delete(f"/api/drone/sim/sessions/{s2['id']}"))
    print('§35 reset/MP/ağır çekim/kamera yok testi geçti.')


if __name__ == '__main__':
    main()
