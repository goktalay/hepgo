"""G-code'u yazıcıya (Moonraker) gönderip baskıyı başlatma; yükleme ilerlemesi izlenebilir.

Üretim ekranındaki "Yazıcıya Gönder" bu modülü kullanır: seçilen parçanın G-code dosyası, seçilen K2 Plus yazıcıya
Moonraker HTTP API'siyle (http://IP:7125/server/files/upload, print=true) yüklenir ve baskı başlatılır. Yükleme arka
planda çalışır; ilerleme (gönderilen/bekleyen bayt) bellekte tutulur ve arayüz saniyede bir okur. Yükleme bitince
parça, o yazıcıda üretime alınmış olarak işaretlenir (order_parts state=URETIMDE).
"""
import os
import secrets
import threading
import time

import httpx

from . import config, db
from .printer_driver import MOONRAKER_PORT

_jobs = {}   # order_part_id -> {status, sent, total, filename, printer, error, started_at}
_lock = threading.Lock()
CHUNK = 256 * 1024


def state(order_part_id):
    return _jobs.get(order_part_id)


def _multipart_stream(path, filename, fields, boundary, progress):
    """multipart/form-data gövdesini parça parça üretir; dosya baytları gönderildikçe progress(sent) çağrılır."""
    pre = b''
    for name, value in fields.items():
        pre += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    pre += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    post = f'\r\n--{boundary}--\r\n'.encode()
    sent = 0
    yield pre
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            sent += len(chunk)
            progress(sent)
            yield chunk
    yield post


def _upload(printer, path, filename, start_print, job):
    """Uzak modda G-code içeriği fabrikadaki ajana aktarılır, ajan yazıcıya yükler; yerelde doğrudan yüklenir.
    printer['ip'] MAC ile doğrulanmış IP'dir (printer_identity.resolve_ip); printer['mac'] ajana da verilir — ajan
    yüklemeden hemen önce aynı IP'deki cihazın MAC'ini bir kez daha denetler (arada IP el değiştirdiyse reddeder)."""
    if config.AGENT_MODE == 'remote':
        import base64
        from . import devices
        with open(path, 'rb') as f:
            data = f.read()
        job['total'] = len(data)
        job['sent'] = 0
        res = devices.call_sync('printer.send', {'ip': printer['ip'], 'expect_mac': printer.get('mac'), 'filename': filename,
                                                 'start': bool(start_print), 'content_b64': base64.b64encode(data).decode()},
                                timeout=300)
        job['sent'] = len(data)
        return res
    _recheck(printer['ip'], printer.get('mac'))
    return _upload_direct(printer, path, filename, start_print, job)


def _recheck(ip, mac):
    """Yükleme öncesi son denetim (yerelde ya da ajanda): IP'deki cihaz kesin olarak BAŞKA bir MAC'e aitse durdur."""
    if not mac:
        return
    from . import printer_identity as pi
    try:
        ident = pi.identify_local(ip)
    except Exception:   # noqa: BLE001 — okunamadı: merkezdeki doğrulama geçerli
        return
    if pi.verdict(ident, mac) == 'mismatch':
        raise RuntimeError(f'{ip} adresindeki cihaz beklenen yazıcı değil (MAC {mac} uyuşmadı) — gönderim yapılmadı')


def _upload_direct(printer, path, filename, start_print, job):
    url = f'http://{printer["ip"]}:{MOONRAKER_PORT}/server/files/upload'
    boundary = f'----caymaz{secrets.token_hex(16)}'
    total = os.path.getsize(path)
    job['total'] = total
    fields = {'root': 'gcodes', 'print': 'true' if start_print else 'false'}

    def progress(sent):
        job['sent'] = sent

    body = _multipart_stream(path, filename, fields, boundary, progress)
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    # Büyük dosyalar için uzun zaman aşımı; bağlanma kısa
    timeout = httpx.Timeout(connect=5, read=120, write=None, pool=5)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, content=body, headers=headers)
    r.raise_for_status()
    return r.json().get('result', {})


def agent_send(args):
    """Ajan tarafı (fabrika): merkezden gelen G-code içeriğini geçici dosyaya yazıp yerel yazıcıya yükler."""
    import base64
    import tempfile
    data = base64.b64decode(args['content_b64'])
    fd, tmp = tempfile.mkstemp(suffix='.gcode')
    try:
        os.write(fd, data)
        os.close(fd)
        _recheck(args['ip'], args.get('expect_mac'))   # eski merkez bu alanı göndermez → denetim atlanır
        return _upload_direct({'ip': args['ip']}, tmp, args['filename'], bool(args.get('start', True)), {})
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _run(order_part_id, printer, path, filename, at, user_id, order_id, order_code, part_id):
    job = _jobs[order_part_id]
    try:
        # Hedef MAC ile çözülür: bilinen IP'de MAC doğrulanır, değilse ağ taranıp güncel IP bulunur; doğrulanmazsa gönderilmez
        job['status'] = 'resolving'
        from . import printer_identity
        res = printer_identity.resolve_ip(printer['id'], user_id)
        printer = dict(printer, ip=res['ip'], mac=res['mac'])
        job.update(ip=res['ip'], mac=res['mac'], verified_by=res['method'])
        job['status'] = 'uploading'
        _upload(printer, path, filename, start_print=True, job=job)
        job['status'] = 'starting'
        # Sistemde: parça bu yazıcıda üretime girdi (start_part ile aynı kayıtlar)
        with db.connect() as conn:
            op = db.row(conn.execute('SELECT id, state FROM order_parts WHERE id = ?', (order_part_id,)))
            if op and op['state'] in ('BEKLIYOR', 'HATA'):
                conn.execute('''UPDATE order_parts SET state = 'URETIMDE', printer_id = ?, started_at = ?, finished_at = NULL,
                                delivered_to = NULL, approved_by = NULL, approved_at = NULL, printer_started_at = NULL,
                                printer_done_at = NULL, print_seconds = NULL, updated_at = ? WHERE id = ?''',
                             (printer['id'], at, at, order_part_id))
                conn.execute('''UPDATE printers SET current_part_id = ?, last_job = ?, last_job_start = ?, last_job_end = NULL
                                WHERE id = ?''', (order_part_id, f'{order_code} / {part_id}', at, printer['id']))
                conn.execute('INSERT INTO part_events (order_part_id, event, user_id, printer_id, at) VALUES (?,?,?,?,?)',
                             (order_part_id, 'YAZICIYA_GONDERILDI', user_id, printer['id'], at))
                db.audit(conn, user_id, 'G-code yazıcıya gönderildi, baskı başlatıldı', 'order_part', order_part_id,
                         f'{order_code} / {part_id} → {printer["name"]}')
                from .production import recompute
                recompute(conn, order_id)
                conn.commit()
        job['status'] = 'done'
        job['finished_at'] = time.time()
    except Exception as err:
        job['status'] = 'error'
        job['error'] = _friendly(err)
        job['finished_at'] = time.time()


def _friendly(err):
    if isinstance(err, httpx.ConnectError):
        return 'Yazıcıya bağlanılamadı (Moonraker açık mı, ağda mı?)'
    if isinstance(err, httpx.HTTPStatusError):
        code = err.response.status_code
        if code == 401:
            return 'Yazıcı yetki istedi (Moonraker güvenlik ayarı)'
        return f'Yazıcı dosyayı kabul etmedi (HTTP {code})'
    if isinstance(err, httpx.TimeoutException):
        return 'Yazıcı zaman aşımına uğradı'
    return str(err) or 'Bilinmeyen hata'


def start(order_part_id, printer, gcode_rel, at, user_id, order_id, order_code, part_id):
    """Yükleme işini arka planda başlatır. Aynı parça için sürüyorsa False döner."""
    path = config.UPLOAD_DIR / gcode_rel
    if not path.is_file():
        raise FileNotFoundError('G-code dosyası bulunamadı')
    with _lock:
        cur = _jobs.get(order_part_id)
        if cur and cur['status'] in ('resolving', 'uploading', 'starting'):
            return False
        _jobs[order_part_id] = {'status': 'resolving', 'sent': 0, 'total': path.stat().st_size,
                                'filename': path.name, 'printer': printer['name'], 'error': None, 'started_at': time.time()}
    threading.Thread(target=_run, name=f'send-{order_part_id}',
                     args=(order_part_id, printer, path, path.name, at, user_id, order_id, order_code, part_id),
                     daemon=True).start()
    return True
