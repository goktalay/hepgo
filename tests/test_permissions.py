"""Yetki matrisi: rol → görebildiği modüller (kullanıcının 2026-09-25 tablosu).

Çalıştırma: .venv/bin/python -m tests.test_permissions
"""
from app import auth

M = {'M1': 'admin', 'M2': 'production', 'M3': 'orders', 'M4': 'warehouse', 'M5': 'stock', 'M6': 'field',
     'M7': 'printers', 'M8': 'products', 'M9': 'tools', 'M10': 'users', 'M11': 'companies', 'M12': 'documents',
     'M13': 'secretariat', 'M14': 'security', 'M15': 'reports', 'M16': 'announcements'}
R = {'R1': auth.ADMIN, 'R2': auth.WAREHOUSE_MANAGER, 'R3': auth.PRODUCTION_MANAGER, 'R4': auth.PRODUCTION_LEAD,
     'R5': auth.PRINTER_MAINTAINER, 'R6': auth.FIELD_LEAD, 'R7': auth.FIELD_STAFF, 'R8': auth.DRIVER, 'R9': auth.PILOT,
     'R10': auth.ASSEMBLER, 'R11': auth.ELECTRONICS, 'R12': auth.ADMIN_STAFF, 'R13': auth.SECRETARY, 'R14': auth.SECURITY}
EXPECTED = {
    'R1': 'M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M16',
    'R2': 'M4 M5 M9 M15 M16',
    'R3': 'M2 M3 M5 M7 M9 M15 M16',
    'R4': 'M2 M5 M7 M9 M15 M16',
    'R5': 'M7 M9 M15 M16',
    'R6': 'M5 M6 M9 M15 M16',
    'R7': 'M5 M6 M9 M15 M16',
    'R8': 'M6 M9 M15 M16',
    'R9': 'M5 M6 M9 M15 M16',
    'R10': 'M2 M9 M15 M16',
    'R11': 'M2 M9 M15 M16',
    'R12': 'M9 M11 M12 M15 M16',
    'R13': 'M9 M13 M15 M16',
    'R14': 'M14 M16',   # Güvenlik: yalnızca araç giriş / çıkış; Araçlar dahil başka modül yok
}


def main():
    for code, role in R.items():
        got = set(auth.allowed_modules([role]))
        want = {M[m] for m in EXPECTED[code].split()}
        assert got == want, (code, role, sorted(got ^ want))
    assert set(auth.allowed_modules([auth.PRODUCTION_LEAD, auth.PRINTER_MAINTAINER])) == {
        'production', 'stock', 'printers', 'tools', 'reports', 'announcements'}
    print('Yetki matrisi testi geçti.')


if __name__ == '__main__':
    main()
