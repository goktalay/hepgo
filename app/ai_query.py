"""Yapay zeka asistanı için GÜVENLİ, salt-okunur veritabanı sorgusu.

Asistan kendi SELECT'ini yazar; SQLite authorizer ile:
  • yalnızca kullanıcının YETKİLİ olduğu tablolar okunabilir (yetkisiz tablo → sorgu reddedilir),
  • hassas kolonlar (şifre özeti, jeton, tercih vb.) NULL'a çevrilir,
  • her türlü YAZMA / PRAGMA / ATTACH engellenir.
Ayrıca bağlantı read-only açılır, süre ve satır sınırı uygulanır. Yetkisiz erişimde asistan (üslubuna göre) reddeder.
"""
import sqlite3
import time

from . import config

# SQLite authorizer eylem kodları (kararlı ABI numaraları)
SQLITE_SELECT, SQLITE_READ, SQLITE_FUNCTION, SQLITE_TRANSACTION, SQLITE_RECURSIVE = 21, 20, 31, 22, 33
SQLITE_INSERT, SQLITE_UPDATE, SQLITE_DELETE = 18, 23, 9
OK, DENY, IGNORE = 0, 1, 2

MAX_ROWS = 200
TIME_LIMIT = 6.0   # saniye

# Sonuçlarda asla görünmemesi gereken kolonlar (hangi tabloda olursa olsun NULL'a çevrilir)
SENSITIVE_COLS = {'password_hash', 'pin_hash', 'prefs', 'token', 'token_hash', 'password', 'secret',
                  'embedding', 'api_key', 'client_secret', 'access_token', 'refresh_token', 'signing_key'}

# Sorgulanabilir tablolar → gereken modül(ler). None = giriş yapmış herkes.
# Kayıtta OLMAYAN tablo hiç kimseye açılmaz (güvenli varsayılan): sohbet/görüşme/evrak/oturum/kamera vb. dışarıda.
_ANY = None
TABLES = {
    # Kişi rehberi (hassas kolonlar zaten NULL'lanır)
    'users': _ANY, 'user_roles': _ANY,
    # Üretim & İş Emirleri
    'orders': {'production', 'orders'}, 'order_parts': {'production', 'orders'}, 'part_events': {'production'},
    'assembly_steps': {'production'}, 'assembly_staff': {'production'}, 'printer_incidents': {'production', 'printers'},
    # Ürün
    'products': {'products', 'production', 'mrp', 'stock'}, 'product_bom': {'products', 'production'},
    'product_recipe': {'products', 'production'}, 'product_spares': {'products', 'mrp', 'stock'},
    # Yazıcılar
    'printers': {'printers', 'production'},
    # MRP / Stok / Depo
    'warehouses': {'mrp', 'stock', 'warehouse'}, 'material_docs': {'mrp', 'stock', 'warehouse', 'purchasing'},
    'material_moves': {'mrp', 'stock', 'warehouse'}, 'spare_moves': {'mrp', 'stock', 'warehouse'},
    'direct_part_requests': {'mrp', 'warehouse', 'production'},
    # Satın Alma
    'purchase_requests': {'purchasing'}, 'purchase_request_items': {'purchasing'},
    'quotes': {'purchasing'}, 'quote_items': {'purchasing'}, 'quote_revisions': {'purchasing'},
    # Satış
    'invoices': {'sales'}, 'invoice_items': {'sales'},
    # Firma / CRM
    'companies': {'companies', 'crm', 'sales', 'purchasing'}, 'company_addresses': {'companies', 'crm'},
    'company_people': {'companies', 'crm'}, 'company_meetings': {'companies', 'crm'},
    'crm_events': {'crm', 'companies'}, 'crm_notes': {'crm', 'companies'},
    # Saha / Uçuş
    'field_tasks': {'field'}, 'field_vehicles': {'field'}, 'field_task_vehicles': {'field'},
    'field_task_staff': {'field'}, 'field_expenses': {'field'}, 'field_flights': {'field'},
    'field_locations': {'field'}, 'flight_logs': {'field'}, 'flight_notes': {'field'},
    # İnsan Kaynakları
    'employees': {'hr'}, 'employee_addresses': {'hr'}, 'employee_events': {'hr'}, 'leave_requests': {'hr'},
    # Sekreterya
    'cargo': {'secretariat'}, 'guest_visits': {'secretariat'}, 'guest_visit_people': {'secretariat'},
    'phone_calls': {'secretariat'}, 'vehicle_visits': {'secretariat', 'security'},
    # Duyurular
    'announcements': _ANY,
    # Mikro bağlantıları
    'mikro_links': {'mikro'},
}


def _modules(user):
    return set(user.get('modules') or [])


def is_admin(user):
    return user.get('master') or 'admin' in _modules(user) or 'Sistem Yöneticisi' in (user.get('roles') or [])


def allowed_tables(user):
    """Kullanıcının okuyabileceği tablo kümesi. Admin/MASTER kayıttaki tüm tabloları görür."""
    if is_admin(user):
        return set(TABLES)
    mods = _modules(user)
    return {t for t, need in TABLES.items() if need is _ANY or (need & mods)}


def schema_text(user):
    """Kullanıcının yetkili olduğu tabloların kolonlarıyla kısa şema metni (sistem promptu için)."""
    allowed = allowed_tables(user)
    if not allowed:
        return '(Bu kullanıcı hiçbir veri tablosuna yetkili değil.)'
    con = sqlite3.connect(f'file:{config.DB_PATH}?mode=ro', uri=True, timeout=3)
    try:
        lines = []
        for t in sorted(allowed):
            cols = []
            for _, name, typ, notnull, default, pk in con.execute(f'PRAGMA table_info({t})'):
                if name.lower() in SENSITIVE_COLS:
                    continue
                # * = zorunlu (NOT NULL, varsayılanı yok) → INSERT'te mutlaka değer verilmeli
                cols.append(f'{name}*' if notnull and default is None and not pk else name)
            uniq = [', '.join(r2[2] for r2 in con.execute(f'PRAGMA index_info({r[1]})'))
                    for r in con.execute(f'PRAGMA index_list({t})') if r[2]]
            if cols:
                lines.append(f'{t}({", ".join(cols)})' + (f' UNIQUE[{"; ".join(uniq)}]' if uniq else ''))
    finally:
        con.close()
    return ('Kolonlardaki * işareti: zorunlu (boş bırakılamaz, varsayılanı yok).\n' + '\n'.join(lines))


def run(user, sql):
    """SELECT'i güvenle çalıştırır. Dönüş: {ok, columns, rows, truncated} | {denied:True} | {error:str}."""
    allowed = allowed_tables(user)

    def authorizer(action, a1, a2, dbname, source):
        if action in (SQLITE_SELECT, SQLITE_FUNCTION, SQLITE_RECURSIVE):
            return OK
        if action == SQLITE_READ:
            if (a1 or '').lower() not in allowed:
                return DENY                      # yetkisiz tablo → sorgu iptal
            if a2 and a2.lower() in SENSITIVE_COLS:
                return IGNORE                    # hassas kolon → NULL
            return OK
        return DENY                              # yazma / pragma / attach / transaction …

    con = sqlite3.connect(f'file:{config.DB_PATH}?mode=ro', uri=True, timeout=3)
    try:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only = ON')
        con.set_authorizer(authorizer)
        deadline = time.time() + TIME_LIMIT
        con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
        try:
            cur = con.execute(sql)
        except sqlite3.DatabaseError as e:
            msg = str(e).lower()
            if 'not authorized' in msg or 'access' in msg:
                return {'denied': True}
            return {'error': f'Sorgu çalıştırılamadı: {e}'}
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in (cur.description or [])]
        truncated = len(rows) > MAX_ROWS
        out = [dict(r) for r in rows[:MAX_ROWS]]
        return {'ok': True, 'columns': cols, 'rows': out, 'truncated': truncated}
    finally:
        con.set_authorizer(None)
        con.close()


def split_statements(sql):
    """Birden çok SQL ifadesini güvenle ayırır (tırnak içindeki ; bölmez)."""
    out, buf = [], ''
    for ch in sql:
        buf += ch
        if ch == ';' and sqlite3.complete_statement(buf):
            if buf.strip(' ;\n\t'):
                out.append(buf.strip())
            buf = ''
    if buf.strip(' ;\n\t'):
        out.append(buf.strip())
    return out


def run_write(user, sql, dry_run=False):
    """Onaylanmış YAZMA ifadelerini (INSERT/UPDATE/DELETE; en fazla 10, tek işlemde) güvenle uygular.

    Yalnızca isteği yapan kullanıcının YETKİLİ olduğu tablolara yazılabilir; hassas kolonlar güncellenemez;
    DDL/PRAGMA/ATTACH engellidir. Hepsi TEK işlem (transaction): biri hata verirse hiçbiri uygulanmaz.
    dry_run=True: aynı şekilde çalıştırır, sonra GERİ ALIR (talep oluşturulurken / onay öncesi ön deneme).
    Dönüş: {ok:True, affected:int, each:[int]} | {denied:True} | {error:str, index:int}."""
    allowed = allowed_tables(user)
    stmts = split_statements(sql or '')
    if not stmts:
        return {'error': 'Boş SQL'}
    if len(stmts) > 10:
        return {'error': 'En fazla 10 ifade gönderilebilir'}

    def authorizer(action, a1, a2, dbname, source):
        if action in (SQLITE_SELECT, SQLITE_FUNCTION, SQLITE_RECURSIVE, SQLITE_TRANSACTION):
            return OK
        if action == SQLITE_READ:
            return OK if (a1 or '').lower() in allowed else DENY
        if action in (SQLITE_INSERT, SQLITE_DELETE):
            return OK if (a1 or '').lower() in allowed else DENY
        if action == SQLITE_UPDATE:
            if (a1 or '').lower() not in allowed:
                return DENY
            return DENY if (a2 and a2.lower() in SENSITIVE_COLS) else OK
        return DENY   # CREATE/DROP/ALTER/PRAGMA/ATTACH …

    con = sqlite3.connect(config.DB_PATH, timeout=8, isolation_level=None)
    try:
        con.execute('PRAGMA foreign_keys = ON')
        con.set_authorizer(authorizer)
        deadline = time.time() + TIME_LIMIT
        con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
        each, i = [], 0
        try:
            con.execute('BEGIN IMMEDIATE')
            for i, st in enumerate(stmts):
                head = st.lstrip().split(None, 1)[0].upper() if st.strip() else ''
                if head not in ('INSERT', 'UPDATE', 'DELETE', 'WITH', 'REPLACE'):
                    raise sqlite3.DatabaseError(f'Yalnızca INSERT/UPDATE/DELETE kullanılabilir ({head or "boş"})')
                each.append(con.execute(st).rowcount)
            con.execute('ROLLBACK' if dry_run else 'COMMIT')
            return {'ok': True, 'affected': sum(max(0, n) for n in each), 'each': each}
        except sqlite3.DatabaseError as e:
            try:
                con.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            msg = str(e).lower()
            if 'not authorized' in msg:
                return {'denied': True, 'index': i}
            return {'error': f'{e}', 'index': i}
    finally:
        con.set_authorizer(None)
        con.close()
