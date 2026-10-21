"""Yazıcı 'Otomatik Ekle / IP Düzelt': tarama geçici tabloya alınır, mevcut yazıcılarla FİZİKSEL ADRESE (donanım kimliği)
göre eşleştirilir, yeni bilgiler eskinin üzerine yazılır. IP değişimi/TAKASI ve IP'yi tutan eski kayıt olsa bile benzersizlik
kısıtı yoktur (IP geçici; benzersiz anahtar MAC) — IP'yi tutan eski kaydın IP'si boşaltılır. Ağ gerektirmez; _add_discovered doğrudan test edilir.
Çalıştırma: .venv/bin/python -m tests.test_printer_discover
"""
import os
import tempfile

os.environ.update(CAYMAZ_DATA_DIR=tempfile.mkdtemp(), CAYMAZ_PRINTER_POLL='0',
                  CAYMAZ_ADMIN_USERNAME='admin@test', CAYMAZ_ADMIN_PASSWORD='admin-sifre-1', CAYMAZ_FORCE_PASSWORD_CHANGE='0')

from app import db, printer_driver  # noqa: E402
from app.routers.printers import _add_discovered  # noqa: E402

USER = {'id': 1}


def live(hw=None, state='HAZIR', prog=0.0):
    d = {'model': 'Creality K2 Plus', 'state': state, 'progress': prog, 'file': None, 'source': 'moonraker', 'hostname': None}
    if hw is not None:
        d['hw'] = hw
    return d


def add_printer(name, ip, hw=None):
    with db.connect() as conn:
        conn.execute('INSERT INTO printers (name, ip, hw_id, auto_added, created_at) VALUES (?,?,?,1,?)', (name, ip, hw, db.now()))
        conn.commit()


def ips():
    with db.connect() as conn:
        return {r['name']: r['ip'] for r in db.rows(conn.execute('SELECT name, ip FROM printers'))}


def total():
    with db.connect() as conn:
        return conn.execute('SELECT COUNT(*) FROM printers').fetchone()[0]


def main():
    db.init()
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id, username, password_hash, full_name, active, created_at) VALUES (1,'admin@test','x','A',1,?)", (db.now(),))
        conn.commit()

    # 1) Basit IP düzeltme (donanım kimliği taramaya gömülü — uzak mod)
    add_printer('Y1', '192.168.1.10', 'K2-AAAA')
    r = _add_discovered([['192.168.1.50', live('K2-AAAA')]], USER)
    assert ips()['Y1'] == '192.168.1.50' and len(r['moved']) == 1 and total() == 1, (ips(), r)

    # 2) IP TAKASI: A .50→.60, B .70→.50 (B'nin yeni IP'si A'nın eski IP'si → çakışma)
    with db.connect() as conn:
        conn.execute('DELETE FROM printers'); conn.commit()
    add_printer('A', '192.168.1.50', 'K2-A')
    add_printer('B', '192.168.1.70', 'K2-B')
    r = _add_discovered([['192.168.1.60', live('K2-A')], ['192.168.1.50', live('K2-B')]], USER)
    assert ips() == {'A': '192.168.1.60', 'B': '192.168.1.50'}, ('takas', ips())
    assert total() == 2 and len(r['moved']) == 2 and not r['added'], r

    # 3) Eski kayıt IP'yi tutuyor + yeni cihaz o IP'de: D çevrimdışı (.80), yeni E cihazı .80'de
    with db.connect() as conn:
        conn.execute('DELETE FROM printers'); conn.commit()
    add_printer('D', '192.168.1.80', 'K2-D')   # taramada yok (çevrimdışı)
    r = _add_discovered([['192.168.1.80', live('K2-E')]], USER)   # .80'de artık başka cihaz (K2-E)
    cur = ips()
    assert cur.get('D', 'yok') is None, ('eski kaydın IP’si boşaltıldı', cur)   # D IP'den feragat etti (çevrimdışı; IP geçici)
    new = [n for n in cur if n != 'D']
    assert len(new) == 1 and cur[new[0]] == '192.168.1.80', ('yeni cihaz eklendi', cur)
    assert total() == 2 and len(r['added']) == 1, r

    # 4) Değişiklik yok: yalnız canlı durum eskinin üzerine yazılır (yeni kayıt/taşıma yok)
    with db.connect() as conn:
        conn.execute('DELETE FROM printers'); conn.commit()
    add_printer('C', '192.168.1.90', 'K2-C')
    r = _add_discovered([['192.168.1.90', live('K2-C', state='YAZDIRIYOR', prog=42.0)]], USER)
    assert not r['moved'] and not r['added'] and total() == 1, r
    with db.connect() as conn:
        row = db.row(conn.execute("SELECT live_state, live_progress FROM printers WHERE name = 'C'"))
    assert row['live_state'] == 'YAZDIRIYOR' and row['live_progress'] == 42.0, ('canlı durum yazıldı', row)

    # 5) hw yok (kimliksiz cihaz): IP'ye göre, yalnız kayıtlı değilse eklenir
    with db.connect() as conn:
        conn.execute('DELETE FROM printers'); conn.commit()
    printer_driver.hardware_id = lambda ip: None   # yerelde de kimlik okunamıyor
    r = _add_discovered([['192.168.1.11', live()]], USER)   # 'hw' anahtarı yok
    assert len(r['added']) == 1 and total() == 1
    r = _add_discovered([['192.168.1.11', live()]], USER)   # ikinci kez: zaten kayıtlı
    assert not r['added'] and total() == 1, r

    print('Yazıcı Otomatik Ekle / IP Düzelt (geçici tablo + fiziksel adres eşleşmesi) testleri geçti.')


if __name__ == '__main__':
    main()
