#!/usr/bin/env python3
"""Hepgo Dron Köprüsü — Linux / Jetson indirme paketi üretici (tar.gz: kurulum betiği + kaynak).

Paket: HepgoDronKoprusu-Linux-Jetson-<sürüm>.tar.gz → tek klasör HepgoDronKoprusu-Linux-Jetson-<sürüm>/ içinde
  install.sh, uninstall.sh, hepgo-kopru.service, kopru.conf.ornek, requirements.txt, hepgo_kopru.py (bridge/dron_koprusu_linux)
  + kopru_core.py, goruntu_core.py (bridge/dron_koprusu — Windows köprüsüyle PAYLAŞILAN çekirdek; depoda kopyası yok) + SURUM + KURULUM.txt.
Kaynak saf Python olduğundan paket mimariden bağımsızdır (Jetson arm64 hedeflenir; x86_64 Ubuntu'da da kurulur). Bağımlılıklar kurulumda
pip ile (Python 3.8 uyumlu sabit sürümler) kurulur.

Kullanım:
  python3 tools/kopru_linux_paket.py                       → build/HepgoDronKoprusu-Linux-Jetson-<sürüm>.tar.gz (+ .sha256)
  python3 tools/kopru_linux_paket.py --cikti /tmp/x        → başka klasöre
  python3 tools/kopru_linux_paket.py --yayinla <kök>       → ayrıca <kök>/<sürüm>/ altına kopyalar (sunucu: <BASE_DIR>/data/releases/kopru;
                                                             /api/drone/bridge-app 'linux-arm64' olarak listeler)
Tekrarlanabilir: dosya sırası, zaman damgası (SOURCE_DATE_EPOCH ya da son commit), sahip (0/root) sabit.
"""
import argparse
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / 'bridge' / 'dron_koprusu_linux'
CORE = ROOT / 'bridge' / 'dron_koprusu'
FILES = [(LINUX, 'install.sh', 0o755), (LINUX, 'uninstall.sh', 0o755), (LINUX, 'hepgo-kopru.service', 0o644), (LINUX, 'kopru.conf.ornek', 0o644),
         (LINUX, 'requirements.txt', 0o644), (LINUX, 'hepgo_kopru.py', 0o755), (CORE, 'kopru_core.py', 0o644), (CORE, 'goruntu_core.py', 0o644)]
NAME = 'HepgoDronKoprusu-Linux-Jetson'

KURULUM = """Hepgo Dron Köprüsü — Linux / NVIDIA Jetson {ver}
==================================================
Telemetri köprüsü (MAVLink: Jetson UART /dev/ttyTHS1, USB /dev/ttyACM0, UDP, TCP) + görüntü köprüsü (RTSP/RTP → HEPGO).
Sunucuya yalnız DIŞA DOĞRU bağlanır (NAT / 4G arkasında port açmak gerekmez).

1) Paketi açın:          tar xzf {name}-{ver}.tar.gz && cd {name}-{ver}
2) Kurun:                sudo ./install.sh          (Jetson Nano JetPack 4.6: python3.8 + ffmpeg apt ile kurulur)
3) Köprü kodunu girin:   sudo hepgo-kopru eslestir <köprü kodu>
                         (HEPGO › Dron Yönetimi › Dron Köprüleri › Yeni Köprü — kod bir kez gösterilir)
4) Durum / günlük:       hepgo-kopru durum      hepgo-kopru log -f

Dron bağlantısı: /etc/hepgo-kopru/kopru.conf [baglanti] (varsayılan /dev/ttyTHS1 921600; ArduPilot SERIAL2_PROTOCOL=2, SERIAL2_BAUD=921).
Kameralar: HEPGO › Dron Yönetimi › Kameralar (köprü olarak bu cihazı seçin) — ayarlar siteden gelir.
Kaldırma: sudo /opt/hepgo-kopru/uninstall.sh   (yapılandırma dahil: --hepsi)
Ayrıntılı rehber: HEPGO deposu docs/jetson-kopru-kurulum.md
"""


def version():
    m = re.search(r"^LINUX_VERSION = '([^']+)'", (LINUX / 'hepgo_kopru.py').read_text(encoding='utf-8'), re.M)
    if not m:
        sys.exit('hepgo_kopru.py içinde LINUX_VERSION bulunamadı')
    return m.group(1)


def mtime():
    if os.environ.get('SOURCE_DATE_EPOCH'):
        return int(os.environ['SOURCE_DATE_EPOCH'])
    try:
        return int(subprocess.check_output(['git', '-C', str(ROOT), 'log', '-1', '--format=%ct'], stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0


def build(out_dir):
    ver = version()
    top = f'{NAME}-{ver}'
    ts = mtime()
    buf = io.BytesIO()

    def add(name, data, mode):
        ti = tarfile.TarInfo(f'{top}/{name}')
        ti.size, ti.mode, ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = len(data), mode, ts, 0, 0, 'root', 'root'
        tf.addfile(ti, io.BytesIO(data))

    with tarfile.open(fileobj=buf, mode='w', format=tarfile.PAX_FORMAT) as tf:
        d = tarfile.TarInfo(top)
        d.type, d.mode, d.mtime, d.uname, d.gname = tarfile.DIRTYPE, 0o755, ts, 'root', 'root'
        tf.addfile(d)
        for base, fn, mode in FILES:
            p = base / fn
            if not p.is_file():
                sys.exit(f'Eksik dosya: {p}')
            add(fn, p.read_bytes(), mode)
        add('SURUM', (ver + '\n').encode(), 0o644)
        add('KURULUM.txt', KURULUM.format(ver=ver, name=NAME).encode('utf-8'), 0o644)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{top}.tar.gz'
    with open(path, 'wb') as f:
        with gzip.GzipFile(filename='', mode='wb', fileobj=f, mtime=ts, compresslevel=9) as gz:
            gz.write(buf.getvalue())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (out_dir / (path.name + '.sha256')).write_text(f'{sha}  {path.name}\n')
    return path, ver, sha


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--cikti', default=str(ROOT / 'build'), help='çıktı klasörü (varsayılan build/)')
    ap.add_argument('--yayinla', help='indirme kökü (ör. <BASE_DIR>/data/releases/kopru): <kök>/<sürüm>/ altına kopyalanır')
    a = ap.parse_args()
    path, ver, sha = build(Path(a.cikti))
    print(f'{path} ({path.stat().st_size} bayt) sha256 {sha}')
    if a.yayinla:
        dst = Path(a.yayinla) / ver
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst / path.name)
        shutil.copy2(str(path) + '.sha256', dst / (path.name + '.sha256'))
        print(f'yayınlandı: {dst / path.name}')


if __name__ == '__main__':
    main()
