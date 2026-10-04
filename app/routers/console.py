"""Araçlar › Terminal — yalnızca MASTER (sistem sahibi) için web konsolu.

Sahada olmayan master'ın yerel makinede komut çalıştırabilmesi için. Oturum çerezi ile kimlik doğrulanır
ve yalnızca config.MASTER_USERNAMES hesaplarına açıktır; her oturum denetim kaydına yazılır. Komutlar
uygulamanın çalıştığı kullanıcı (ör. mkaderoglu) yetkisiyle gerçek bir PTY (bash) üzerinde çalışır.

NOT: Bu, merkeze taşınacak yazılımın değil, yerel entegrasyon/ajan tarafının bir aracıdır (fabrika makinesi).
"""
import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import auth, config, db

ws_router = APIRouter()


def _set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', max(1, rows), max(1, cols), 0, 0))
    except OSError:
        pass


@ws_router.websocket('/ws/console')
async def ws_console(ws: WebSocket):
    await ws.accept()

    def who():
        with db.connect() as conn:
            u = auth.user_by_token(conn, ws.cookies.get(auth.COOKIE))
            if config.CONSOLE_ENABLED and u and auth.is_master(u['username']):
                db.audit(conn, u['id'], 'MASTER web konsol açtı', 'console', None, '')
                conn.commit()
                return u
            return None

    user = await asyncio.to_thread(who)
    if not user:
        try:
            msg = ('Yetkisiz: bu konsol yalnızca sistem sahibine (MASTER) açıktır.' if config.CONSOLE_ENABLED else
                   'Web terminal bu kurulumda kapalı (CAYMAZ_CONSOLE=1 ile yalnız yerel kurulumda açılır).')
            await ws.send_text(f'\x1b[31m{msg}\x1b[0m\r\n')
        except Exception:   # noqa: BLE001
            pass
        await ws.close(code=4403)
        return

    # Gerçek PTY + bash (giriş kabuğu). openpty + Popen; sunucu sürecini fork ETMEZ.
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, 24, 80)
    env = dict(os.environ, TERM='xterm-256color')
    proc = subprocess.Popen(['/bin/bash', '-l'], stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                            start_new_session=True, cwd=os.path.expanduser('~'), env=env)
    os.close(slave_fd)
    loop = asyncio.get_event_loop()

    async def pty_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, _read, master_fd)
                if not data:
                    break
                await ws.send_text(data.decode('utf-8', 'replace'))
        except Exception:   # noqa: BLE001
            pass
        finally:
            try:
                await ws.close()
            except Exception:   # noqa: BLE001
                pass

    reader = asyncio.create_task(pty_to_ws())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                obj = json.loads(msg)
            except ValueError:
                continue
            if obj.get('t') == 'i':                       # kullanıcı girdisi
                os.write(master_fd, obj.get('d', '').encode('utf-8'))
            elif obj.get('t') == 'r':                     # boyut değişimi
                _set_winsize(master_fd, int(obj.get('r', 24)), int(obj.get('c', 80)))
    except WebSocketDisconnect:
        pass
    except Exception:   # noqa: BLE001
        pass
    finally:
        reader.cancel()
        try:
            proc.send_signal(signal.SIGHUP)
            proc.terminate()
        except Exception:   # noqa: BLE001
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            await asyncio.to_thread(proc.wait, 5)
        except Exception:   # noqa: BLE001
            try:
                proc.kill()
            except Exception:   # noqa: BLE001
                pass


def _read(fd):
    try:
        return os.read(fd, 65536)
    except OSError:
        return b''
