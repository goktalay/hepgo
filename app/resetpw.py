"""Sunucuda (root / hepgo) kullanıcı listeleme ve şifre sıfırlama — giriş yapılamadığında.

Kullanım (servisin ortam değişkenleriyle; CAYMAZ_DATA_DIR hangi tenant olduğunu belirler):
  python -m app.resetpw                 → kullanıcılar (kullanıcı adı = e-posta, ad, roller, aktif mi)
  python -m app.resetpw <kullanıcı adı> → yeni şifre sorulur (ekrana yazılmaz); hesap aktif edilir, açık oturumları kapatılır
Şifreler tek yönlü özetle saklanır: eskisi okunamaz, yalnız yenisi verilir. İşlem denetim kaydına yazılır.
"""
import getpass
import sqlite3
import sys

from . import auth, config, db


def main(argv):
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    print(f'Veritabanı: {config.DB_PATH}')
    if len(argv) < 2:
        for uid, un, name, active in conn.execute('SELECT id, username, full_name, active FROM users ORDER BY id'):
            roles = ', '.join(r for (r,) in conn.execute('SELECT role FROM user_roles WHERE user_id = ?', (uid,)))
            tag = 'MASTER' if auth.is_master(un) else roles or 'rol yok'
            print(f'{uid:>4}  {un:<40} {name:<28} {tag}{"" if active else "  (PASİF)"}')
        return 0
    row = conn.execute('SELECT id, username FROM users WHERE username = ? COLLATE NOCASE', (argv[1].strip(),)).fetchone()
    if not row:
        print('Kullanıcı bulunamadı (listelemek için argümansız çalıştırın).')
        return 1
    pw = getpass.getpass('Yeni şifre: ')
    if len(pw) < 8:
        print('Şifre en az 8 karakter olmalı.')
        return 1
    if pw != getpass.getpass('Yeni şifre (tekrar): '):
        print('Şifreler aynı değil.')
        return 1
    conn.execute('UPDATE users SET password_hash = ?, active = 1 WHERE id = ?', (auth.hash_password(pw), row[0]))
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (row[0],))
    conn.execute('INSERT INTO audit_logs (user_id, action, entity, entity_id, detail, at) VALUES (?,?,?,?,?,?)',
                 (None, 'Şifre sunucudan sıfırlandı (app.resetpw)', 'user', str(row[0]), row[1], db.now()))
    conn.commit()
    print(f'{row[1]}: şifre değiştirildi, hesap aktif, açık oturumlar kapatıldı.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
