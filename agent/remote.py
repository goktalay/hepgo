"""Fabrika ajanı: uzaktan terminal (PTY) ve kendini güncelleme.

İkisi de AJANIN KENDİ .env'inde açıkça izin verilmedikçe çalışmaz (merkez ele geçirilse bile fabrikadaki makinede
kabuk açılamaz / kod değiştirilemez):
  CAYMAZ_AGENT_TERMINAL=1   Araçlar › Terminal › Fabrika: merkezdeki MASTER bu makinede kabuk açabilir
  CAYMAZ_AGENT_UPDATE=1     Merkez "Ajanı güncelle" diyebilir: kod paketi indirilir, doğrulanır, ajan yeniden başlar
Merkez tarafında ayrıca Program Ayarları › Entegrasyonlar › Fabrika Ajanı anahtarı gerekir.
"""
import fcntl
import hashlib
import io
import os
import pty
import signal
import struct
import subprocess
import tarfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_FILE = ROOT / '.agent-bundle'          # yüklü kod paketinin özeti (sürüm kimliği)
BACKUP_DIR = ROOT / '.agent-backups'


def allowed(flag):
    return os.environ.get(flag, '0') == '1'


def caps():
    out = ['speech']
    if allowed('CAYMAZ_AGENT_TERMINAL'):
        out.append('term')
    if allowed('CAYMAZ_AGENT_UPDATE'):
        out.append('update')
    return out


def bundle_id():
    try:
        return BUNDLE_FILE.read_text().strip()[:64]
    except OSError:
        return None


# ---------------- Terminal ----------------
class Term:
    """Bir PTY içinde giriş kabuğu (ajanın kullanıcısıyla, ev dizininde)."""

    def __init__(self, rows=24, cols=80):
        self.fd, slave = pty.openpty()
        self.resize(rows, cols)
        env = dict(os.environ, TERM='xterm-256color')
        for k in [k for k in env if k.startswith('CAYMAZ_')]:   # ajanın anahtarları kabuğa sızmasın
            env.pop(k, None)
        self.proc = subprocess.Popen(['/bin/bash', '-l'], stdin=slave, stdout=slave, stderr=slave,
                                     start_new_session=True, cwd=os.path.expanduser('~'), env=env)
        os.close(slave)

    def resize(self, rows, cols):
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', max(1, int(rows)), max(1, int(cols)), 0, 0))
        except (OSError, ValueError):
            pass

    def write(self, data):
        os.write(self.fd, data.encode('utf-8'))

    def read(self):
        try:
            return os.read(self.fd, 65536)
        except OSError:
            return b''

    def close(self):
        try:
            self.proc.send_signal(signal.SIGHUP)
            self.proc.terminate()
        except Exception:   # noqa: BLE001
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            self.proc.wait(3)
        except Exception:   # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:   # noqa: BLE001
                pass


# ---------------- Güncelleme ----------------
def apply_bundle(data, sha256):
    """Merkezin kod paketi (tar.gz): özet doğrulanır, yalnız app/ agent/ requirements.txt yazılır; önceki hâli yedeklenir."""
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError('paket özeti tutmuyor (indirme bozuk ya da değiştirilmiş)')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        members = tar.getmembers()
        for m in members:
            name = m.name
            inside = name in ('app', 'agent', 'requirements.txt') or name.startswith(('app/', 'agent/'))
            if name.startswith('/') or '..' in Path(name).parts or not (m.isfile() or m.isdir()) or not inside:
                raise RuntimeError(f'pakette izin verilmeyen yol: {name}')
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        with tarfile.open(BACKUP_DIR / f'once-{stamp}.tar.gz', 'w:gz') as bak:
            for m in members:
                p = ROOT / m.name
                if m.isfile() and p.is_file():
                    bak.add(p, arcname=m.name)
        changed = 0
        for m in members:
            p = ROOT / m.name
            if m.isdir():
                p.mkdir(parents=True, exist_ok=True)
                continue
            new = tar.extractfile(m).read()
            if not p.is_file() or p.read_bytes() != new:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + '.yeni')
                tmp.write_bytes(new)
                os.replace(tmp, p)
                changed += 1
    for old in sorted(BACKUP_DIR.glob('once-*.tar.gz'))[:-5]:   # son 5 yedek kalır
        old.unlink(missing_ok=True)
    BUNDLE_FILE.write_text(sha256)
    return {'changed': changed, 'files': len([m for m in members if m.isfile()]), 'backup': f'.agent-backups/once-{stamp}.tar.gz'}
