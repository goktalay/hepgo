"""Tüm kullanıcılara açık uyarı sistemi (üst çubuktaki uyarı simgesi).

Her uyarı türü bir fonksiyondur; yeni tür eklemek için ALERTS listesine bir kayıt eklenir.
Şu anki türler yazıcının kendi bildirdiği durum ile sistemdeki kayıt arasındaki uyumsuzluklardır.
"""
import re
from datetime import datetime

from . import db, semis

NOT_PRINTING = ('HAZIR', 'TAMAMLANDI')
ACTIVE = ('YAZDIRIYOR', 'DURAKLADI')   # yazıcıda bir dosya işleniyor


def norm_file(name):
    """Dosya adı karşılaştırması: klasör ve uzantı atılır, büyük/küçük harf ve boşluklar yok sayılır
    ('c5- sol - part 1_ABS_9h16m.gcode' == 'C5-sol-part 1_ABS_9h16m')."""
    if not name:
        return ''
    base = re.split(r'[\\/]', name.strip())[-1]
    base = re.sub(r'\.(gcode|gco|g|bgcode)$', '', base, flags=re.I)
    return re.sub(r'\s+', '', base).casefold()


def expected_files(conn):
    """Parça kodu → baskı dosyası (parça yedekleri ve kod = parça olan yedek parçalar, ör. KMH)."""
    files = {pid: i['print_file'] for pid, i in semis.print_info(conn).items() if i['print_file']}
    for code, f in conn.execute("SELECT code, print_file FROM products WHERE type = 'YEDEK_PARCA' AND print_file IS NOT NULL"):
        files.setdefault(code, f)
    return files


def _file_parts(files):
    by_file = {}
    for pid, f in files.items():
        by_file.setdefault(norm_file(f), []).append(pid)
    return by_file


def _elapsed(iso):
    return int((datetime.now() - datetime.fromisoformat(iso)).total_seconds()) if iso else None


def printer_stale(conn):
    """Yazıcı yazdırmıyor ama sistemde hâlâ bir parça bu yazıcıda üretimde görünüyor."""
    rows = db.rows(conn.execute(
        f'''SELECT p.id, p.name, p.ip, p.live_state, p.live_file, p.last_seen,
                   op.part_id, op.started_at, op.printer_done_at, o.id AS order_id, o.code AS order_code
            FROM printers p JOIN order_parts op ON op.id = p.current_part_id
            JOIN orders o ON o.id = op.order_id
            WHERE p.live_state IN ({','.join('?' * len(NOT_PRINTING))})
            ORDER BY op.started_at''', NOT_PRINTING))
    for r in rows:
        r['elapsed_seconds'] = _elapsed(r['started_at'])
        r['waiting_seconds'] = _elapsed(r['printer_done_at'])   # yazıcı "tamamlandı" dediğinden beri
    return rows


def printer_outside(conn):
    """Yazıcı baskı yapıyor ama sistemde bu yazıcıya atanmış bir parça yok; dosya adından parça bulunur."""
    by_file = _file_parts(expected_files(conn))
    rows = db.rows(conn.execute(
        f'''SELECT id, name, ip, live_state, live_file, live_progress, last_seen FROM printers
            WHERE live_state IN ({','.join('?' * len(ACTIVE))}) AND current_part_id IS NULL ORDER BY name''', ACTIVE))
    for r in rows:
        r['file_parts'] = by_file.get(norm_file(r['live_file']), [])
    return rows


def printer_wrong_file(conn):
    """Yazıcıda sistemde atanan parçanın dosyasından farklı bir dosya basılıyor (dosya adı karşılaştırması)."""
    files = expected_files(conn)
    by_file = _file_parts(files)
    rows = db.rows(conn.execute(
        f'''SELECT p.id, p.name, p.ip, p.live_state, p.live_file, p.live_progress, p.last_seen,
                   op.part_id, op.started_at, o.id AS order_id, o.code AS order_code
            FROM printers p JOIN order_parts op ON op.id = p.current_part_id JOIN orders o ON o.id = op.order_id
            WHERE p.live_state IN ({','.join('?' * len(ACTIVE))}) AND COALESCE(p.live_file, '') != ''
            ORDER BY p.name''', ACTIVE))
    out = []
    for r in rows:
        expected = files.get(r['part_id'])
        if expected and norm_file(expected) != norm_file(r['live_file']):
            r['expected_file'] = expected
            r['file_parts'] = by_file.get(norm_file(r['live_file']), [])
            out.append(r)
    return out


def printer_error(conn):
    """Yazıcı kendi durumunu hata olarak bildiriyor."""
    return db.rows(conn.execute(
        '''SELECT p.id, p.name, p.ip, p.live_state, p.live_file, p.live_progress, p.last_seen,
                  op.part_id, o.id AS order_id, o.code AS order_code
           FROM printers p
           LEFT JOIN order_parts op ON op.id = p.current_part_id
           LEFT JOIN orders o ON o.id = op.order_id
           WHERE p.live_state = 'HATA' ORDER BY p.name'''))


def printer_unrecorded_abort(conn):
    """KRİTİK: sisteme girilmeden yazıcıya yüklenen baskı yarıda kesildi (iptal / hata). "Gördüm" denene kadar kalır."""
    rows = db.rows(conn.execute(
        '''SELECT i.id AS incident_id, i.file AS live_file, i.progress AS live_progress, i.end_state, i.started_at, i.ended_at,
                  p.id, p.name, p.ip, p.live_state, p.last_seen
           FROM printer_incidents i JOIN printers p ON p.id = i.printer_id
           WHERE i.kind = 'KAYITSIZ_IPTAL' AND i.ack_at IS NULL ORDER BY i.ended_at DESC'''))
    by_file = _file_parts(expected_files(conn))
    for r in rows:
        r['file_parts'] = by_file.get(norm_file(r['live_file']), [])
    return rows


ALERTS = [
    {
        'key': 'printer-unrecorded-abort', 'level': 'danger', 'fn': printer_unrecorded_abort, 'critical': True,
        'title': 'KRİTİK: Kayıtsız baskı yarıda kesildi',
        'hint': 'Yazıcıya sisteme girilmeden bir baskı yüklenmiş ve bu baskı tamamlanmadan durdurulmuş (iptal edilmiş ya da '
                'hata vermiş). Malzeme ve süre kaybı kayıt dışı kaldı. Baskıyı kimin, neden başlatıp durdurduğunu '
                'öğrenin; parçalar Üretim Yönetimi\'nden yazıcıya atanarak başlatılmalıdır. İnceledikten sonra "Gördüm" deyin.',
    },
    {
        'key': 'printer-error', 'level': 'danger', 'fn': printer_error,
        'title': 'Yazıcı hata verdi',
        'hint': 'Yazıcı kendi durumunu hata olarak bildiriyor. Yazıcıyı kontrol edin; üzerinde sistemden başlatılmış bir '
                'parça varsa Üretim Yönetimi\'nde "Hata Verdi" ile kapatıp yeniden üretime alın.',
    },
    {
        'key': 'printer-wrong-file', 'level': 'danger', 'fn': printer_wrong_file,
        'title': 'Yazıcıda yanlış dosya basılıyor',
        'hint': 'Yazıcının bastığı dosya, sistemde bu yazıcıya atanan parçanın baskı dosyasıyla uyuşmuyor. Yazıcıya '
                'doğru dosyanın verildiğini kontrol edin; yanlış parça başlatıldıysa baskıyı durdurun ya da sistemdeki '
                'kaydı düzeltin. Parçaların baskı dosyaları Ürün Yönetimi\'ndeki yedek parça sayfalarında tanımlıdır.',
    },
    {
        'key': 'printer-stale', 'level': 'danger', 'fn': printer_stale,
        'title': 'Yazıcı boşta ama sistemde üretimde',
        'hint': 'Yazıcı baskı yapmıyor ancak sistemde bu yazıcıda üretimde görünen bir parça var. Baskı bittiyse '
                'Üretim Yönetimi\'nde parçayı "Üretim Tamamlandı" ile depoya teslim edin; baskı başarısızsa "Hata Verdi" '
                'ile kapatın.',
    },
    {
        'key': 'printer-outside', 'level': 'warn', 'fn': printer_outside,
        'title': 'Sistemde boş ama yazıcıda baskı var',
        'hint': 'Yazıcı baskı yapıyor (ya da duraklatılmış) ancak sistemde bu yazıcıya atanmış bir parça yok. Basılan '
                'dosyanın hangi parçaya ait olduğu dosya adından bulunur; Üretim Yönetimi\'nde o parçayı bu yazıcıyla '
                'üretime başlatın. "Tanımsız dosya" sistemde hiçbir parçanın baskı dosyası değildir.',
    },
]


def summary(conn):
    out = []
    for a in ALERTS:
        items = a['fn'](conn)
        if items:
            out.append({'key': a['key'], 'level': a['level'], 'title': a['title'], 'count': len(items), 'critical': a.get('critical', False),
                        'names': [i['name'] for i in items[:5]]})
    return out


def detail(conn, key):
    a = next((x for x in ALERTS if x['key'] == key), None)
    if not a:
        return None
    return {'key': a['key'], 'level': a['level'], 'title': a['title'], 'hint': a['hint'], 'items': a['fn'](conn),
            'critical': a.get('critical', False)}


def acknowledge(conn, incident_id, user_id):
    return conn.execute('UPDATE printer_incidents SET ack_by = ?, ack_at = ? WHERE id = ? AND ack_at IS NULL',
                        (user_id, db.now(), incident_id)).rowcount
