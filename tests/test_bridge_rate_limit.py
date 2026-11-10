"""Köprü uydu veri kısıtı (kopru_core.MavLink rate_pm) — gerçek ArduCopter SITL ile:
- sınırsız kip: tüm akışlar (4 Hz) iletilir
- dakikada 10: konum (GLOBAL_POSITION_INT) ~6 sn'de bir, köprüden sunucuya giden bayt sınırsıza göre çok az
- mod değişikliği (HEARTBEAT) ve komut yanıtı (COMMAND_ACK) beklemeden iletilir
- FS_GCS_ENABLE okunur (yer istasyonu sinyali buna göre seyrelir ya da 1 sn kalır)
Çalıştırma: .venv/bin/python -m tests.test_bridge_rate_limit
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bridge' / 'dron_koprusu'))

from pymavlink import mavutil  # noqa: E402

import kopru_core  # noqa: E402
from app import drone_sitl  # noqa: E402


class Toplayici:
    def __init__(self):
        self.lock = threading.Lock()
        self.bayt, self.paket, self.olay = 0, 0, []   # olay: (zaman, tür)
        self.mav = mavutil.mavlink.MAVLink(None)
        self.mav.robust_parsing = True

    def __call__(self, data):
        with self.lock:
            self.bayt += len(data)
            self.paket += 1
            for m in self.mav.parse_buffer(data) or []:
                self.olay.append((time.time(), m.get_type(), m))

    def turler(self, t0=0.0):
        with self.lock:
            return [(ts, t, m) for ts, t, m in self.olay if ts >= t0]


def calistir(port, rate_pm, sure):
    top = Toplayici()
    link = kopru_core.MavLink({'type': 'tcp', 'host': '127.0.0.1', 'port': port, 'sysid': 1, **({'rate_pm': rate_pm} if rate_pm else {})},
                              top, lambda *a: None, log=lambda s: None)
    link.open()
    try:
        t0 = time.time()
        while not link.target and time.time() - t0 < 30:
            time.sleep(0.2)
        assert link.target == 1, 'SITL kalp atışı gelmedi'
        time.sleep(3)                          # akış isteği otursun; ölçüm bundan sonra
        with top.lock:
            b0, p0 = top.bayt, top.paket
        tb = time.time()
        time.sleep(sure)
        with top.lock:
            bayt, paket = top.bayt - b0, top.paket - p0
        poz = [ts for ts, t, _ in top.turler(tb) if t == 'GLOBAL_POSITION_INT']
        sonuc = {'bayt_sn': bayt / sure, 'paket_sn': paket / sure, 'poz': len(poz), 'fs_gcs': link.fs_gcs,
                 'hat_rx': link.link_rx, 'hat_tx': link.link_tx}   # veri_sayaci: dron ↔ köprü hattı (TCP başlığı tahminiyle)
        if rate_pm:
            # mod değişikliği beklemeden: GUIDED'a geçince HEARTBEAT ve COMMAND_ACK ~hemen gelir (aralık 6 sn)
            ts = time.time()
            link.m.mav.command_long_send(1, 1, 176, 0, 1, 4, 0, 0, 0, 0, 0)   # MAV_CMD_DO_SET_MODE → GUIDED (copter 4)
            ack = hb = None
            while time.time() - ts < 4 and not (ack and hb):
                for t_, ty, m in top.turler(ts):
                    if ty == 'COMMAND_ACK' and m.command == 176:
                        ack = ack or t_
                    if ty == 'HEARTBEAT' and m.get_srcSystem() == 1 and m.custom_mode == 4:
                        hb = hb or t_
                time.sleep(0.1)
            sonuc['ack_s'] = (ack - ts) if ack else None
            sonuc['hb_s'] = (hb - ts) if hb else None
        return sonuc
    finally:
        link.close()


def main():
    yon = drone_sitl.SitlYoneticisi()
    kimlik = 990777
    port, hata = yon.baslat(kimlik, 'multirotor', 39.9, 32.8, 1, temiz=True)
    assert port, hata
    try:
        sinirsiz = calistir(port, 0, 20)
        kisitli = calistir(port, 10, 60)
    finally:
        yon.durdur(kimlik)
    oran = kisitli['bayt_sn'] / sinirsiz['bayt_sn']
    print(f"sınırsız: {sinirsiz['bayt_sn']:.0f} B/sn, {sinirsiz['paket_sn']:.1f} paket/sn, 20 sn'de {sinirsiz['poz']} konum")
    print(f"dakikada 10: {kisitli['bayt_sn']:.1f} B/sn, {kisitli['paket_sn']:.2f} paket/sn, 60 sn'de {kisitli['poz']} konum, oran %{oran * 100:.2f}, "
          f"FS_GCS={kisitli['fs_gcs']}, mod yanıtı {kisitli['ack_s']} sn, kalp atışı {kisitli['hb_s']} sn")
    print(f"tahmini saatlik: sınırsız {sinirsiz['bayt_sn'] * 3600 / 1e6:.1f} MB, dakikada 10 {kisitli['bayt_sn'] * 3600 / 1e6:.2f} MB")
    print(f"dron ↔ köprü hattı (sayaç): sınırsız 20 sn {sinirsiz['hat_rx'] + sinirsiz['hat_tx']} B, dakikada 10 / 60 sn {kisitli['hat_rx'] + kisitli['hat_tx']} B")
    assert sinirsiz['poz'] >= 40, sinirsiz                      # 4 Hz × 20 sn ≈ 80
    assert 8 <= kisitli['poz'] <= 12, kisitli                    # 60 sn / 6 sn = 10
    assert oran < 0.1, oran                                      # en az 10 kat az
    assert kisitli['paket_sn'] < 0.5, kisitli                    # ~6 sn'de bir toplu paket (+ anlık olaylar)
    assert kisitli['fs_gcs'] is not None, kisitli                # FS_GCS okundu
    assert sinirsiz['hat_rx'] > kisitli['hat_rx'] > 0 and kisitli['hat_tx'] > 0, (sinirsiz, kisitli)   # hat sayacı: kısıt otopilottan gelen veriyi de azaltır
    assert kisitli['ack_s'] is not None and kisitli['ack_s'] < 2, kisitli   # komut yanıtı beklemeden
    assert kisitli['hb_s'] is not None and kisitli['hb_s'] < 3, kisitli     # mod değişikliği beklemeden
    print('Köprü veri kısıtı testleri geçti.')


if __name__ == '__main__':
    main()
