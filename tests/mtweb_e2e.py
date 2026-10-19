"""mtweb uçtan uca: sahte hesap servisi + uvicorn (yerel port) + Playwright (headless Chromium).
Notepad Master: yeni yerel proje → yeni dosya → Monaco'da yaz → Ctrl+S (sunucuda içerik doğrulanır).
Convert Master: resim yükle → png→jpg projesi → proje penceresinde Başlat → çıktı doğrulanır. Bilgi sayfası + uzak türlerin kapalılığı.
Konsol CSP ihlalleri toplanır (sıfır olmalı). Ekran görüntüleri /tmp/mtweb-shots. Sunucular PID ile kapatılır.

Çalıştırma: LD_LIBRARY_PATH=… CHROMIUM_PATH=… .venv/bin/python -m tests.mtweb_e2e
"""
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path('/tmp/mtweb-shots')
PORT, FAKE = 8797, 8796
BASE = f'http://127.0.0.1:{PORT}'
TOK = 'tok-ali-0123456789abcdef'


def wait_http(url, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:   # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f'{url} açılmadı')


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    data = tempfile.mkdtemp(prefix='mtweb-e2e-')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CAYMAZ_', 'MTWEB_'))}
    env.update(MTWEB_DATA_DIR=data, MTWEB_ACCOUNT_URL=f'http://127.0.0.1:{FAKE}', CAYMAZ_ENV_FILE=os.path.join(data, 'yok.env'))
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, '-m', 'tests.mtweb_fake_mt', '--port', str(FAKE)], cwd=ROOT, env=env))
        procs.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.mtweb.main:app', '--host', '127.0.0.1', '--port', str(PORT), '--log-level', 'warning'],
                                      cwd=ROOT, env=env))
        wait_http(BASE + '/web/healthz')
        run(data)
    except Exception:
        print('veri dizini:', data)
        raise
    finally:
        for p in procs:
            os.kill(p.pid, signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.kill(p.pid, signal.SIGKILL)
        shutil.rmtree(data, ignore_errors=True)


def run(data):
    csp = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or None)
        ctx = b.new_context(viewport={'width': 1400, 'height': 860}, locale='tr-TR')
        ctx.add_cookies([{'name': 'sm_session', 'value': TOK, 'domain': '127.0.0.1', 'path': '/', 'httpOnly': True}])
        page = ctx.new_page()
        ctx.on('console', lambda m: csp.append(m.text) if ('Content Security Policy' in m.text or 'Refused to' in m.text) else None)
        try:
            steps(b, ctx, page, data)
        except Exception:
            page.screenshot(path=str(SHOTS / 'HATA.png'))
            raise
        b.close()
    assert not csp, 'CSP ihlali:\n' + '\n'.join(csp[:10])
    print('Uçtan uca mtweb geçti; ekran görüntüleri', SHOTS)


def steps(b, ctx, page, data):
    ctx.on('weberror', lambda e: print('SAYFA HATASI:', e.error))

    # --- oturumsuz: girişe yönlendirme
    anon = b.new_context().new_page()
    anon.goto(BASE + '/web/notepadmaster/', wait_until='commit')
    assert '/giris?next=/web/notepadmaster/' in anon.url, anon.url

    # --- Notepad Master
    page.goto(BASE + '/web/notepadmaster/')
    page.wait_for_selector('#mtweb-strip .mw-user')
    assert 'Ali Yılmaz' in page.inner_text('#mtweb-strip')
    page.click('#btnNewConn')
    page.wait_for_selector('#f-kind')
    assert page.is_disabled('#f-kind button[data-v=ssh]') and page.is_disabled('#f-kind button[data-v=ftp]')
    assert 'masaüstü' in page.inner_text('#f-kind button[data-v=ssh]').lower()
    page.screenshot(path=str(SHOTS / '01-notepad-form.png'))
    page.fill('#f-name', 'Notlarım')
    page.fill('#f-lpath', '/')
    page.locator('.modal footer .btn', has_text='aç').first.click()
    frame_el = page.wait_for_selector('iframe.mt-win.on')
    fr = frame_el.content_frame()
    fr.wait_for_selector('.col-tree [data-a=newFile]')
    assert not fr.query_selector('#mtweb-strip'), 'iframe içinde şerit gizli olmalı'
    for _ in range(50):   # wait_for_function CSP'ye takılır (eval); evaluate ile yokla
        if fr.evaluate("() => document.querySelector('.col-tree [data-a=newFile]').onclick !== null"):
            break
        time.sleep(0.1)
    fr.click('.col-tree [data-a=newFile]')
    fr.fill('#pv', 'merhaba.txt')
    fr.locator('.modal footer .btn.primary').click()
    fr.wait_for_selector('.monaco-editor', timeout=20000)
    fr.click('.monaco-editor .view-lines')
    page.keyboard.type('Mastertool web — Notepad Master\nikinci satır\n')
    page.keyboard.press('Control+s')
    f = Path(data) / 'tools' / 'notepadmaster' / '1' / 'files' / 'merhaba.txt'
    for _ in range(50):
        if f.exists() and 'ikinci satır' in f.read_text(encoding='utf-8'):
            break
        time.sleep(0.2)
    assert 'Mastertool web — Notepad Master' in f.read_text(encoding='utf-8'), f.read_text(encoding='utf-8')
    page.wait_for_timeout(600)
    page.screenshot(path=str(SHOTS / '02-notepad-editor.png'))
    print('Notepad: dosya oluşturuldu ve kaydedildi →', f.read_text(encoding='utf-8').splitlines()[0])

    # --- Convert Master
    page.goto(BASE + '/web/convertmaster/')
    page.wait_for_selector('#btnNew')
    buf = io.BytesIO()
    Image.new('RGB', (320, 200), (40, 120, 220)).save(buf, format='PNG')
    res = page.evaluate("""async (bytes) => {
        const fd = new FormData(); fd.append('dir', '/resimler');
        fd.append('files', new Blob([new Uint8Array(bytes)], { type: 'image/png' }), 'mavi.png');
        const up = await fetch('/api/tools/mt/convertmaster/fs/upload', { method: 'POST', body: fd, credentials: 'same-origin' });
        const pr = await fetch('/api/tools/convert/project/save', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ form: { name: 'Resimler', type: 'image', sourceExts: ['png'], targetExt: 'jpg', sourcePath: '/resimler' } }) });
        return [up.status, pr.status, (await pr.json()).id];
    }""", list(buf.getvalue()))
    assert res[0] == 200 and res[1] == 200, res
    page.reload()
    page.wait_for_selector('.proj-card')
    page.screenshot(path=str(SHOTS / '03-convert-main.png'))
    page.dblclick('.proj-card')
    fr = page.wait_for_selector('iframe.mt-win.on').content_frame()
    fr.wait_for_selector('#btnRun')
    fr.wait_for_timeout(800)
    fr.click('#btnRun')
    out = Path(data) / 'tools' / 'convertmaster' / '1' / 'converted' / res[2] / 'mavi.jpg'
    for _ in range(100):
        if out.exists():
            break
        time.sleep(0.2)
    assert out.exists(), out
    with Image.open(out) as im:
        assert im.format == 'JPEG' and im.size == (320, 200)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(SHOTS / '04-convert-done.png'))
    print('Convert: mavi.png → mavi.jpg', out.stat().st_size, 'bayt')

    # --- bilgi sayfası
    page.goto(BASE + '/web/sshmaster/')
    page.wait_for_selector('.mtweb-card')
    assert 'yakında' in page.inner_text('.mtweb-card'), page.inner_text('.mtweb-card')
    page.screenshot(path=str(SHOTS / '05-sshmaster-soon.png'))


if __name__ == '__main__':
    main()
