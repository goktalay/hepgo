"""Yetki matrisi: rol → görebildiği modüller (kullanıcının 2026-09-25 tablosu).

Rol Yönetimi (2026-10): izinler veritabanındadır; test geçici veritabanında koddaki rolleri / MODULE_ROLES'u tohumlayıp
(rbac.sync) aynı matrisin çıktığını, ayrıca miras / yasak / yazma kurallarını doğrular.

Çalıştırma: .venv/bin/python -m tests.test_permissions
"""
import os
import tempfile

os.environ['CAYMAZ_DATA_DIR'] = tempfile.mkdtemp()
from app import auth, db, rbac  # noqa: E402

M = {'M1': 'admin', 'M2': 'production', 'M3': 'orders', 'M4': 'warehouse', 'M5': 'stock', 'M6': 'field',
     'M7': 'printers', 'M8': 'products', 'M9': 'tools', 'M10': 'users', 'M11': 'companies', 'M12': 'documents',
     'M13': 'secretariat', 'M14': 'security', 'M15': 'reports', 'M16': 'announcements', 'M17': 'hr', 'M18': 'mrp', 'M19': 'purchasing', 'M21': 'sales', 'M22': 'cleaning', 'M23': 'design',
     'M24': 'cameras', 'M25': 'rehber', 'M26': 'finance', 'M27': 'certs', 'M28': 'fleet', 'M29': 'boss'}
R = {'R1': auth.ADMIN, 'R2': auth.WAREHOUSE_MANAGER, 'R3': auth.PRODUCTION_MANAGER, 'R4': auth.PRODUCTION_LEAD,
     'R5': auth.PRINTER_MAINTAINER, 'R6': auth.FIELD_LEAD, 'R7': auth.FIELD_STAFF, 'R8': auth.DRIVER, 'R9': auth.PILOT,
     'R10': auth.ASSEMBLER, 'R11': auth.ELECTRONICS, 'R12': auth.ADMIN_STAFF, 'R13': auth.SECRETARY, 'R14': auth.SECURITY, 'R15': auth.HR, 'R16': auth.PURCHASING, 'R17': auth.MRP_LEAD, 'R18': auth.SALES, 'R19': auth.CLEANER, 'R20': auth.DESIGNER, 'R21': auth.CAMERA, 'R22': auth.FINANCE, 'R23': auth.QUALITY, 'R24': auth.FLEET, 'R25': auth.BOSS}
# Rehber (M25) güvenlik, kamera, stajer, temizlik dışı tüm rollerde; cameras (M24) yalnız admin + Kamera Yetkilisi.
EXPECTED = {
    'R1': 'M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M21 M22 M23 M24 M25 M26 M27 M28 M29',
    'R2': 'M4 M5 M9 M15 M16 M18 M25',
    'R3': 'M2 M3 M5 M7 M9 M15 M16 M18 M25',
    'R4': 'M2 M5 M7 M9 M15 M16 M18 M25',
    'R5': 'M7 M9 M15 M16 M25',
    'R6': 'M5 M6 M9 M15 M16 M18 M25',
    'R7': 'M5 M6 M9 M15 M16 M18 M25',
    'R8': 'M6 M9 M15 M16 M25',
    'R9': 'M5 M6 M9 M15 M16 M18 M25',
    'R10': 'M2 M9 M15 M16 M25',
    'R11': 'M2 M9 M15 M16 M25',
    'R12': 'M9 M11 M12 M15 M16 M25 M28',
    'R13': 'M9 M13 M15 M16 M25',
    'R14': 'M14 M16',
    'R15': 'M9 M15 M16 M17 M25',   # İnsan Kaynakları
    'R16': 'M9 M15 M16 M19 M25',   # Satın Alma
    'R17': 'M5 M9 M15 M16 M18 M25',
    'R18': 'M9 M15 M16 M21 M25',   # Satış
    'R19': 'M16 M22',   # Temizlik Görevlisi: yalnızca Temizlik + Duyurular
    'R20': 'M9 M15 M16 M23 M25',   # Endüstriyel Tasarımcı
    'R21': 'M24 M16',   # Kamera Yetkilisi: Kameralar + Duyurular
    'R22': 'M9 M15 M16 M25 M26',   # Finans: Finans + Araçlar + Raporlar + Duyurular + Rehber
    'R23': 'M9 M15 M16 M25 M27',   # Kalite / Sertifikasyon
    'R24': 'M9 M15 M16 M25 M28',   # Araç / Filo Sorumlusu
    'R25': 'M9 M15 M16 M25 M29',   # Patron / Üst Yönetim
}


def top(mods):
    return {m for m in mods if '.' not in m}   # alt modüller (finance.trial …) matriste yok


def main():
    db.init()
    with db.connect() as conn:
        rbac.sync(conn)
    for code, role in R.items():
        got = top(auth.allowed_modules([role]))
        want = {M[m] for m in EXPECTED[code].split()}
        assert got == want, (code, role, sorted(got ^ want))
    assert top(auth.allowed_modules([auth.PRODUCTION_LEAD, auth.PRINTER_MAINTAINER])) == {
        'production', 'stock', 'printers', 'tools', 'reports', 'announcements', 'mrp', 'rehber'}
    rules()
    print('Yetki matrisi testi geçti.')


def rules():
    """Miras, alt modül, yasak > izin, yazma zinciri ve çakışma raporu."""
    with db.connect() as conn:
        now = db.now()
        conn.execute("INSERT INTO roles (name, parent, system, created_at) VALUES ('Muhasebe Şefi', ?, 0, ?)", (auth.FINANCE, now))
        conn.execute("INSERT INTO roles (name, parent, system, created_at) VALUES ('Okur Finans', NULL, 0, ?)", (now,))
        conn.executemany('INSERT INTO role_perms (role, node, cap, allow) VALUES (?,?,?,?)', [
            ('Muhasebe Şefi', 'finance.trial', 'read', 0),                 # alt modül yasak
            ('Okur Finans', 'finance', 'open', 1), ('Okur Finans', 'finance', 'read', 1), ('Okur Finans', 'finance', 'write', 0),
            ('Okur Finans', 'fleet', 'open', 1), ('Okur Finans', 'fleet', 'read', 1)])
        conn.commit()
    rbac.bump()
    m = set(auth.allowed_modules(['Muhasebe Şefi']))
    assert 'finance' in m and 'finance.bank' in m and 'finance.trial' not in m, m           # miras + alt modül yasağı
    assert 'Finans' in rbac.expand(['Muhasebe Şefi'])                                      # üst rol adı kontrollerde geçer
    w = set(rbac.writable(['Okur Finans']))
    assert 'finance' not in w and 'finance' in set(auth.allowed_modules(['Okur Finans']))   # salt okunur
    assert 'fleet' not in w                                                               # yazma ayarı yok → yazamaz
    both = rbac.writable([auth.FINANCE, 'Okur Finans'])
    assert 'finance' not in both, 'yasak izni yenmeli'
    c = rbac.conflicts([auth.FINANCE, 'Okur Finans'])
    assert any(x['node'] == 'finance' and x['cap'] == 'write' for x in c['perm']), c
    assert 'admin' in auth.allowed_modules([auth.ADMIN]) and 'finance.trial' in auth.allowed_modules([auth.ADMIN])


if __name__ == '__main__':
    main()
