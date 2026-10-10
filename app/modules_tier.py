"""Modül katmanları (tier): firma kaydında ve Program Ayarları › Modül Yönetimi'nde modüllerin
zorunlu / seçmeli / merkez ayrımı. Merkez katalog central/veilox_server/veilox/modules_catalog.py
içindeki TIER ile BİREBİR uyumlu tutulur.

- required: her KOBİ firmada her zaman açık; master kapatamaz.
- optional: master Program Ayarları'ndan açıp kapatabilir (firma sahip olduğu sürece).
- central: yalnızca merkez (Veilox) yöneticisi açabilir; master'a modül yönetiminde görünmez.

Bir anahtar hiçbirinde değilse 'optional' varsayılır (güvenli: master yönetebilir).
'master' ve 'uyelik' modülleri paketten bağımsız her zaman açıktır (auth.current_user'da ele alınır),
bu yüzden tier listelerinde yer almazlar.
"""

REQUIRED = {
    'admin', 'users', 'mrp', 'stock', 'warehouse',
    'purchasing', 'sales', 'companies', 'documents', 'hr', 'finance',
}
OPTIONAL = {
    'boss', 'production', 'orders', 'printers', 'products', 'design', 'field',
    'certs', 'fleet', 'projects', 'secretariat', 'security', 'rehber',
    'reports', 'announcements', 'cleaning', 'tools', 'pos',
}
CENTRAL = {
    'cameras', 'mikro', 'factory', 'konum', 'sms',
}

# Her zaman açık (modül yönetiminde görünmez / kapatılamaz)
ALWAYS = {'master', 'uyelik'}


def tier(key):
    k = (key or '').split('.')[0]
    if k in ALWAYS:
        return 'always'
    if k in REQUIRED:
        return 'required'
    if k in CENTRAL:
        return 'central'
    return 'optional'
