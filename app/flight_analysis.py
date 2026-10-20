"""Uçuş loglarının arka planda analizi — ALT SÜREÇ + KUYRUK (docs/ucus-simulatoru.md §8.4).

Neden: analiz sunucu sürecinin içinde (iş parçacığında) çalışınca 700 MB'lık .BIN'de ~2 dk GIL tutuluyor ve süreç ~2,4 GB'a
çıkıyordu; aynı makinedeki firma servisleri ağırlaşıyordu. Şimdi:
  * Her analiz ayrı süreçte: `python -m app.flightlog analyze <log> <çıktı.json> <ebeveyn pid>` (nice, bellek tavanı RLIMIT_AS, BLAS tek
    iş parçacığı, ebeveyn ölürse PDEATHSIG ile kendini kapatır). İkili .BIN hızlı akış okuyucuyla (dataflash), metin .log / .tlog pymavlink.
  * İstek iş parçacığı beklemez: `start(id)` yalnız kuyruğa ekler. Aynı anda en çok FLIGHTLOG_ANALIZ_PARALEL (vars. 1) analiz; kalanlar
    sırada bekler (status ISLENIYOR, progress NULL = sırada).
  * İlerleme: alt süreç `P <yüzde>` satırları yazar → flight_logs.progress (0…100; en çok saniyede bir yazılır) + bellekteki durum().
  * Sonuç: TAMAM (analysis JSON) / HATA (error). Zaman aşımı (FLIGHTLOG_ANALIZ_ZAMAN_ASIMI_S) → süreç öldürülür, HATA.
  * Sunucu yeniden başlarsa (resume_pending) ISLENIYOR'da kalan her kayıt progress NULL'a çekilir ve BAŞTAN kuyruğa alınır (yarım çıktı
    dosyası kullanılmaz, üzerine yazılır).
Ortam: FLIGHTLOG_ANALIZ_PARALEL (1), FLIGHTLOG_ANALIZ_NICE (10), FLIGHTLOG_ANALIZ_BELLEK_MB (3072; 0 = sınırsız),
       FLIGHTLOG_ANALIZ_ZAMAN_ASIMI_S (3600).
"""
import collections
import json
import os
import subprocess
import sys
import threading
import time

from . import config, db


def _env_int(ad, vars_):
    try:
        return int(os.environ.get(ad, '') or vars_)
    except ValueError:
        return vars_


PARALEL = max(1, _env_int('FLIGHTLOG_ANALIZ_PARALEL', 1))
NICE = max(0, min(19, _env_int('FLIGHTLOG_ANALIZ_NICE', 10)))
BELLEK_MB = max(0, _env_int('FLIGHTLOG_ANALIZ_BELLEK_MB', 3072))
ZAMAN_ASIMI_S = max(5, _env_int('FLIGHTLOG_ANALIZ_ZAMAN_ASIMI_S', 3600))

_kosul = threading.Condition()
_kuyruk = collections.deque()      # sıradaki log id'leri
_calisan = {}                      # log id → {'pct': int, 'pid': int | None}
_iscilar = []


def durum():
    """Bellekteki kuyruk durumu: {log_id: {'progress': yüzde | None, 'queue': sıra (1…) | None}}."""
    with _kosul:
        out = {lid: {'progress': c['pct'], 'queue': None} for lid, c in _calisan.items()}
        for i, lid in enumerate(_kuyruk, 1):
            out[lid] = {'progress': None, 'queue': i}
    return out


def start(log_id):
    """Analizi kuyruğa ekler (beklemez). Aynı kayıt kuyruktaysa ya da çalışıyorsa yok sayılır."""
    with _kosul:
        if log_id in _calisan or log_id in _kuyruk:
            return
        _kuyruk.append(log_id)
        canli = [t for t in _iscilar if t.is_alive()]
        _iscilar[:] = canli
        while len(_iscilar) < PARALEL:
            t = threading.Thread(target=_isci, daemon=True, name=f'flightlog-analiz-{len(_iscilar) + 1}')
            _iscilar.append(t)
            t.start()
        _kosul.notify()


def resume_pending():
    """Sunucu yeniden başladığında ISLENIYOR'da kalan analizler baştan kuyruğa alınır (ilerleme sıfırlanır)."""
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM flight_logs WHERE status = 'ISLENIYOR' ORDER BY id")]
        if ids:
            conn.execute("UPDATE flight_logs SET progress = NULL WHERE status = 'ISLENIYOR'")
    for log_id in ids:
        start(log_id)


def _isci():
    while True:
        with _kosul:
            while not _kuyruk:
                _kosul.wait()
            log_id = _kuyruk.popleft()
            _calisan[log_id] = {'pct': 0, 'pid': None}
        try:
            _isle(log_id)
        except Exception as exc:   # noqa: BLE001 — işçi ölmesin; kayıt HATA'ya düşer
            try:
                _hata(log_id, f'Analiz başarısız: {exc}'[:300])
            except Exception:   # noqa: BLE001
                pass
        finally:
            with _kosul:
                _calisan.pop(log_id, None)


def _ilerleme_yaz(log_id, pct):
    try:
        with db.connect() as conn:
            conn.execute("UPDATE flight_logs SET progress = ? WHERE id = ? AND status = 'ISLENIYOR'", (pct, log_id))
    except Exception:   # noqa: BLE001 — kilitli DB vb.: ilerleme kaybı önemsiz
        pass


def _hata(log_id, mesaj):
    with db.connect() as conn:
        conn.execute("UPDATE flight_logs SET status = 'HATA', error = ?, progress = NULL, analyzed_at = ? WHERE id = ?",
                     (mesaj, db.now(), log_id))


def _alt_surec(log_id, girdi, cikti):
    """Analizi alt süreçte çalıştırır; ilerlemeyi işler. Dönüş: (sonuç dict | None, hata mesajı | None)."""
    env = dict(os.environ, FLIGHTLOG_ANALIZ_NICE=str(NICE), FLIGHTLOG_ANALIZ_BELLEK_MB=str(BELLEK_MB),
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONUNBUFFERED='1')
    proc = subprocess.Popen([sys.executable, '-m', 'app.flightlog', 'analyze', str(girdi), str(cikti), str(os.getpid())],
                            cwd=str(config.BASE_DIR), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors='replace')
    with _kosul:
        if log_id in _calisan:
            _calisan[log_id]['pid'] = proc.pid
    asim = {'oldu': False}

    def oldur():
        asim['oldu'] = True
        proc.kill()
    zamanlayici = threading.Timer(ZAMAN_ASIMI_S, oldur)
    zamanlayici.daemon = True
    zamanlayici.start()
    hata, son_yazim, son_pct = None, 0.0, -1
    try:
        for satir in proc.stdout:
            satir = satir.strip()
            if satir.startswith('P '):
                try:
                    pct = max(0, min(100, int(satir[2:])))
                except ValueError:
                    continue
                with _kosul:
                    if log_id in _calisan:
                        _calisan[log_id]['pct'] = pct
                now = time.monotonic()
                if pct != son_pct and (now - son_yazim >= 1.0 or pct >= 100):
                    son_pct, son_yazim = pct, now
                    _ilerleme_yaz(log_id, pct)
            elif satir.startswith('ERR '):
                hata = satir[4:]
        proc.wait()
    finally:
        zamanlayici.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if asim['oldu']:
        return None, f'Analiz zaman aşımına uğradı ({ZAMAN_ASIMI_S} sn)'
    if proc.returncode != 0 or not os.path.exists(cikti):
        if hata:
            return None, hata
        if proc.returncode == -9:
            return None, 'Analiz süreci sonlandırıldı (bellek sınırı ya da sistem)'
        return None, f'Analiz süreci beklenmedik biçimde sonlandı (çıkış kodu {proc.returncode})'
    with open(cikti, encoding='utf-8') as f:
        return json.load(f), None


def _isle(log_id):
    with db.connect() as conn:
        row = db.row(conn.execute('SELECT * FROM flight_logs WHERE id = ?', (log_id,)))
        if row:
            conn.execute("UPDATE flight_logs SET progress = 0 WHERE id = ? AND status = 'ISLENIYOR'", (log_id,))
    if not row:
        return
    girdi = config.UPLOAD_DIR / row['file']
    cikti = config.UPLOAD_DIR / (row['file'] + '.analiz.json')
    try:
        result, hata = _alt_surec(log_id, girdi, cikti)
    finally:
        try:
            os.unlink(cikti)
        except OSError:
            pass
    if hata is not None:   # bozuk/eksik log: kullanıcıya gösterilecek hata
        _hata(log_id, f'Log çözümlenemedi: {hata}'[:500])
        return
    _kaydet(row, result)


def _kaydet(row, result):
    log_id = row['id']
    now = db.now()
    with db.connect() as conn:
        conn.execute("UPDATE flight_logs SET status = 'TAMAM', analysis = ?, error = NULL, progress = NULL, analyzed_at = ? WHERE id = ?",
                     (json.dumps(result, ensure_ascii=False), now, log_id))
        # tek kullanımlık uçak havada kaldıysa (uçtu) HURDA olur
        flight_s = (result.get('summary') or {}).get('flight_s') or 0
        if row['flight_id'] and flight_s > 0:
            from .production import scrap
            order = conn.execute('SELECT order_id FROM field_flights WHERE id = ?', (row['flight_id'],)).fetchone()
            if order and order[0]:   # dron uçuşlarında (order_id NULL) hurda yok
                scrap(conn, order[0], row['uploaded_by'], f'Uçtu (uçuş logu: {int(flight_s // 60)} dk {int(flight_s % 60)} sn havada)')
        if row['task_id']:
            from .routers.field import complete_if_reported   # döngüsel içe aktarmayı önlemek için burada
            complete_if_reported(conn, row['task_id'])
            db.audit(conn, row['uploaded_by'], 'Uçuş raporu oluşturuldu', 'field_task', row['task_id'], row['file_name'])
