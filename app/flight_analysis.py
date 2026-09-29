"""Uçuş loglarının arka planda analizi. Büyük .bin dosyalarının çözümlenmesi dakikalar
sürebileceğinden istek beklemez; sonuç flight_logs tablosuna yazılır."""
import json
import threading

from . import config, db
from .flightlog import analyze

_running = set()
_lock = threading.Lock()


def _run(log_id):
    try:
        with db.connect() as conn:
            row = db.row(conn.execute('SELECT * FROM flight_logs WHERE id = ?', (log_id,)))
        if not row:
            return
        try:
            result = analyze(config.UPLOAD_DIR / row['file'])
        except Exception as exc:   # bozuk/eksik log: kullanıcıya gösterilecek hata
            with db.connect() as conn:
                conn.execute("UPDATE flight_logs SET status = 'HATA', error = ?, analyzed_at = ? WHERE id = ?",
                             (f'Log çözümlenemedi: {exc}', db.now(), log_id))
            return
        now = db.now()
        with db.connect() as conn:
            conn.execute("UPDATE flight_logs SET status = 'TAMAM', analysis = ?, error = NULL, analyzed_at = ? WHERE id = ?",
                         (json.dumps(result, ensure_ascii=False), now, log_id))
            # tek kullanımlık uçak havada kaldıysa (uçtu) HURDA olur
            flight_s = (result.get('summary') or {}).get('flight_s') or 0
            if row['flight_id'] and flight_s > 0:
                from .production import scrap
                order = conn.execute('SELECT order_id FROM field_flights WHERE id = ?', (row['flight_id'],)).fetchone()
                if order:
                    scrap(conn, order[0], row['uploaded_by'], f'Uçtu (uçuş logu: {int(flight_s // 60)} dk {int(flight_s % 60)} sn havada)')
            if row['task_id']:
                from .routers.field import complete_if_reported   # döngüsel içe aktarmayı önlemek için burada
                complete_if_reported(conn, row['task_id'])
                db.audit(conn, row['uploaded_by'], 'Uçuş raporu oluşturuldu', 'field_task', row['task_id'], row['file_name'])
    finally:
        with _lock:
            _running.discard(log_id)


def start(log_id):
    with _lock:
        if log_id in _running:
            return
        _running.add(log_id)
    threading.Thread(target=_run, args=(log_id,), daemon=True, name=f'flightlog-{log_id}').start()


def resume_pending():
    """Sunucu yeniden başladığında yarım kalan analizleri sürdürür."""
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM flight_logs WHERE status = 'ISLENIYOR'")]
    for log_id in ids:
        start(log_id)
