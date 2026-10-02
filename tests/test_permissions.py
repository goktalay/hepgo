"""Yetki matrisi: rol → görebildiği modüller (kullanıcının 2026-09-25 tablosu).

Çalıştırma: .venv/bin/python -m tests.test_permissions
"""
from app import auth

M = {'M1': 'admin', 'M2': 'production', 'M3': 'orders', 'M4': 'warehouse', 'M5': 'stock', 'M6': 'field',
     'M7': 'printers', 'M8': 'products', 'M9': 'tools', 'M10': 'users', 'M11': 'companies', 'M12': 'documents',
     'M13': 'secretariat', 'M14': 'security', 'M15': 'reports', 'M16': 'announcements', 'M17': 'hr', 'M18': 'mrp', 'M19': 'purchasing', 'M21': 'sales', 'M22': 'cleaning', 'M23': 'design'}
R = {'R1': auth.ADMIN, 'R2': auth.WAREHOUSE_MANAGER, 'R3': auth.PRODUCTION_MANAGER, 'R4': auth.PRODUCTION_LEAD,
     'R5': auth.PRINTER_MAINTAINER, 'R6': auth.FIELD_LEAD, 'R7': auth.FIELD_STAFF, 'R8': auth.DRIVER, 'R9': auth.PILOT,
     'R10': auth.ASSEMBLER, 'R11': auth.ELECTRONICS, 'R12': auth.ADMIN_STAFF, 'R13': auth.SECRETARY, 'R14': auth.SECURITY, 'R15': auth.HR, 'R16': auth.PURCHASING, 'R17': auth.MRP_LEAD, 'R18': auth.SALES, 'R19': auth.CLEANER, 'R20': auth.DESIGNER}
EXPECTED = {
    'R1': 'M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M21 M22 M23',
    'R2': 'M4 M5 M9 M15 M16 M18',
    'R3': 'M2 M3 M5 M7 M9 M15 M16 M18',
    'R4': 'M2 M5 M7 M9 M15 M16 M18',
    'R5': 'M7 M9 M15 M16',
    'R6': 'M5 M6 M9 M15 M16 M18',
    'R7': 'M5 M6 M9 M15 M16 M18',
    'R8': 'M6 M9 M15 M16',
    'R9': 'M5 M6 M9 M15 M16 M18',
    'R10': 'M2 M9 M15 M16',
    'R11': 'M2 M9 M15 M16',
    'R12': 'M9 M11 M12 M15 M16',
    'R13': 'M9 M13 M15 M16',
    'R14': 'M14 M16',
    'R15': 'M9 M15 M16 M17',   # İnsan Kaynakları
    'R16': 'M9 M15 M16 M19',   # Satın Alma
    'R17': 'M5 M9 M15 M16 M18',
    'R18': 'M9 M15 M16 M21',   # Satış: Satış Yönetimi + Araçlar + Raporlar + Duyurular   # MRP Sorumlusu: MRP (Yarı Mamül = stock); Onay Yönetimi Depo Yöneticisinde   # Güvenlik: yalnızca araç giriş / çıkış; Araçlar dahil başka modül yok
    'R19': 'M16 M22',   # Temizlik Görevlisi: yalnızca Temizlik + Duyurular
    'R20': 'M9 M15 M16 M23',   # Endüstriyel Tasarımcı: Tasarım + Araçlar + Raporlar + Duyurular
}


def main():
    for code, role in R.items():
        got = set(auth.allowed_modules([role]))
        want = {M[m] for m in EXPECTED[code].split()}
        assert got == want, (code, role, sorted(got ^ want))
    assert set(auth.allowed_modules([auth.PRODUCTION_LEAD, auth.PRINTER_MAINTAINER])) == {
        'production', 'stock', 'printers', 'tools', 'reports', 'announcements', 'mrp'}
    print('Yetki matrisi testi geçti.')


if __name__ == '__main__':
    main()
