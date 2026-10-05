"""Yazıcı 'Otomatik Ekle / IP Düzelt': tarama yeni yazıcıları ekler VE elektrik kesintisi gibi sebeplerle IP'si değişen
kayıtlı yazıcıyı kalıcı donanım kimliğinden tanıyıp IP'sini düzeltir (yeni kayıt açmaz). Donanım kimliği taramadan
(uzak modda ajandan) gelebilir ya da yerelde okunur. Ağ gerektirmez.
Çalıştırma: .venv/bin/python -m tests.test_printer_discover
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from app import db, printer_driver  # noqa: E402
from app.routers.printers import _add_discovered  # noqa: E402


def live(hw=None, model='Creality K2 Plus', state='HAZIR'):
    d = {'model': model, 'state': state, 'progress': 0, 'file': None, 'source': 'moonraker', 'hostname': None}
    if hw is not None:
        d['hw'] = hw   # taramada gelen donanım kimliği (uzak modda ajan döner)
    return d


def main():
    db.init()
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id, username, password_hash, full_name, active, created_at) VALUES (1,'admin@test','x','A',1,?)", (db.now(),))
        conn.execute("INSERT INTO printers (name, ip, hw_id, auto_added, created_at) VALUES ('Yazıcı 1','192.168.1.10','K2Plus-AAAA',1,?)", (db.now(),))
        conn.execute("INSERT INTO printers (name, ip, created_at) VALUES ('Elle Yazıcı','192.168.1.11',?)", (db.now(),))
        conn.commit()
    user = {'id': 1}

    # Uzak mod benzeri: donanım kimliği taramaya gömülü (ajandan). K2Plus-AAAA artık .50'de; .51 yeni; .11 zaten kayıtlı
    found = [['192.168.1.50', live(hw='K2Plus-AAAA')], ['192.168.1.51', live(hw='K2Plus-BBBB')], ['192.168.1.11', live(hw=None)]]
    r = _add_discovered(found, user)
    moved = {m['name']: m for m in r['moved']}
    assert moved.get('Yazıcı 1', {}).get('old') == '192.168.1.10' and moved['Yazıcı 1']['ip'] == '192.168.1.50', r['moved']
    assert {a['ip'] for a in r['added']} == {'192.168.1.51'}, r['added']
    with db.connect() as conn:
        pr = {row['name']: row['ip'] for row in db.rows(conn.execute('SELECT name, ip FROM printers'))}
        total = conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]
    assert pr['Yazıcı 1'] == '192.168.1.50' and total == 3, (pr, total)   # IP düzeltildi, yeni kayıt açılmadı

    # Yerel mod benzeri: hw taramada yok → hardware_id ile okunur (yama)
    printer_driver.hardware_id = lambda ip: {'192.168.1.60': 'K2Plus-BBBB'}.get(ip)   # .51'deki cihaz .60'a geçti
    found2 = [['192.168.1.60', live()]]   # 'hw' anahtarı yok
    r2 = _add_discovered(found2, user)
    assert [m['old'] for m in r2['moved']] == ['192.168.1.51'] and not r2['added'], r2
    with db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0] == 3   # hâlâ 3, duplicate yok

    print('Yazıcı Otomatik Ekle / IP Düzelt testleri geçti.')


if __name__ == '__main__':
    main()
