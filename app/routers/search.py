"""Sistem geneli arama (üst çubuktaki büyüteç): tek sorgu, kullanıcının yetkili olduğu modüllerin tablolarında arar.

- En az 3 karakter; büyük/küçük harf ve Türkçe harf (İ/ı, Ş/s, Ğ/g, Ü/u, Ö/o, Ç/c) farkı yok sayılır (document_ocr.fold,
  SQLite'a trfold() olarak kaydedilir).
- Her kaynak bir modül anahtarına bağlıdır; master ve Sistem Yöneticisi her şeyi arar (modül listeleri zaten tamdır), evrak
  görünürlük süzgeci de onlar için kalkar. Kişiye özel kaynaklar (görevler) yalnız sahibine döner.
- Evraklarda OCR / ses dökümü metni dahil FTS5 dizini (documents_fts) kullanılır ve eşleşen yerden alıntı verilir.
- Günlük/olay tabloları (audit_logs, part_events, mail_cache, sohbet…) aramaya katılmaz.
- Sonuç: gruplar halinde {type, label, items:[{id, title, sub, href, snippet?}]}; tıklayınca ilgili detay ekranı açılır.
"""
import sqlite3

from fastapi import APIRouter, Depends

from .. import auth, db
from ..document_ocr import fold
from .documents import _match_query, _snippet, _tokens, _visible_sql

router = APIRouter(prefix='/api/search')

MIN_LEN = 3
PER_GROUP = 8

LABELS = {
    'company': 'Cari', 'supplier': 'Tedarikçi', 'person': 'Kişi', 'product': 'Ürün', 'material': 'Stok / Malzeme',
    'order': 'Sipariş', 'employee': 'Personel', 'user': 'Kullanıcı', 'visit': 'Ziyaret', 'document': 'Evrak',
    'project': 'Proje', 'request': 'Satın Alma Talebi', 'quote': 'Teklif', 'invoice': 'Fatura', 'vehicle': 'Araç',
    'account': 'Finans Hesabı', 'post': 'Şirketten Haber', 'todo': 'Görev', 'cargo': 'Kargo',
}


def _can(user, *mods):
    return any(m in user['modules'] for m in mods)


def _is_admin(user):
    return bool(user.get('master')) or auth.ADMIN in user['roles']


def _like(*cols):
    return '(' + ' OR '.join(f"trfold({c}) LIKE ? ESCAPE '\\'" for c in cols) + ')'


def _pattern(q):
    f = fold(q).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{f}%'


def _q(conn, sql, args):
    try:
        return db.rows(conn.execute(sql, args))
    except sqlite3.OperationalError:   # eski şemada sütun/tablo yoksa kaynak atlanır
        return []


def _item(id, title, sub, href, **extra):
    return {'id': id, 'title': title or '', 'sub': sub or '', 'href': href, **extra}


# ---------- kaynaklar: her biri (user, conn, pat, q) alır, öğe listesi döner

def _companies(user, conn, pat, q):
    if not _can(user, 'companies', 'documents', 'purchasing', 'finance.cari'):
        return {}
    rows = _q(conn, f'''SELECT id, name, tax_no, phone, email, is_supplier FROM companies
                        WHERE active = 1 AND {_like('name', 'tax_no', 'phone', 'email', 'address', 'note')}
                        ORDER BY name LIMIT ?''', (*[pat] * 6, PER_GROUP * 2))
    out = {'company': [], 'supplier': []}
    for r in rows:
        sub = ' · '.join(x for x in (r['tax_no'], r['phone'], r['email']) if x)
        if r['is_supplier']:
            if _can(user, 'purchasing'):
                out['supplier'].append(_item(r['id'], r['name'], sub, f"#/purchasing/suppliers/{r['id']}"))
        elif _can(user, 'companies', 'documents', 'finance.cari'):
            href = f"#/companies/{r['id']}" if _can(user, 'companies', 'documents') else f"#/finance/cari/{r['id']}"
            out['company'].append(_item(r['id'], r['name'], sub, href))
    return out


def _people(user, conn, pat, q):
    if not _can(user, 'companies', 'rehber'):
        return {}
    rows = _q(conn, f'''SELECT p.id, p.full_name, p.title, p.phone, p.email, c.name AS company FROM company_people p
                        LEFT JOIN companies c ON c.id = p.company_id
                        WHERE {_like('p.full_name', 'p.title', 'p.phone', 'p.email')} ORDER BY p.full_name LIMIT ?''',
             (*[pat] * 4, PER_GROUP))
    base = '#/companies/rehber/person/' if _can(user, 'companies') else '#/rehber/person/'
    return {'person': [_item(r['id'], r['full_name'], ' · '.join(x for x in (r['company'], r['title'], r['phone']) if x),
                             f"{base}{r['id']}") for r in rows]}


def _products(user, conn, pat, q):
    if not _can(user, 'products', 'mrp', 'stock', 'warehouse', 'sales', 'pos'):
        return {}
    rows = _q(conn, f'''SELECT id, code, name, type, barcode, brand, model FROM products
                        WHERE active = 1 AND {_like('code', 'name', 'barcode', 'serial', 'brand', 'model', 'description')}
                        ORDER BY name LIMIT ?''', (*[pat] * 7, PER_GROUP * 2))
    out = {'product': [], 'material': []}
    for r in rows:
        sub = ' · '.join(x for x in (r['code'], r['brand'], r['model'], r['barcode']) if x)
        if r['type'] == 'MAMUL' and _can(user, 'products', 'sales', 'pos'):
            out['product'].append(_item(r['id'], r['name'], sub, f"#/products/{r['id']}"))
        elif r['type'] != 'MAMUL' and _can(user, 'mrp', 'stock', 'warehouse'):
            href = f"#/mrp/semi/{r['id']}" if r['type'] == 'YARI_MAMUL' else f"#/mrp/materials/{r['id']}"
            out['material'].append(_item(r['id'], r['name'], f"{sub} · {r['type']}", href))
    return out


def _orders(user, conn, pat, q):
    if not _can(user, 'orders', 'production'):
        return {}
    rows = _q(conn, f'''SELECT o.id, o.code, o.status, o.note, p.name AS product FROM orders o
                        LEFT JOIN products p ON p.id = o.product_id
                        WHERE {_like('o.code', 'o.note', 'p.name')} ORDER BY o.id DESC LIMIT ?''', (*[pat] * 3, PER_GROUP))
    return {'order': [_item(r['id'], r['code'], ' · '.join(x for x in (r['product'], r['status']) if x),
                            f"#/orders/{r['id']}") for r in rows]}


def _employees(user, conn, pat, q):
    if not _can(user, 'hr'):
        return {}
    rows = _q(conn, f'''SELECT id, first_name, last_name, title, department, phone, status FROM employees
                        WHERE {_like("first_name || ' ' || last_name", 'tc_no', 'phone', 'email', 'title', 'department', 'position')}
                        ORDER BY first_name, last_name LIMIT ?''', (*[pat] * 7, PER_GROUP))
    return {'employee': [_item(r['id'], f"{r['first_name']} {r['last_name']}",
                               ' · '.join(x for x in (r['title'], r['department'], r['status']) if x), f"#/hr/{r['id']}")
                         for r in rows]}


def _users(user, conn, pat, q):
    if not _is_admin(user):
        return {}
    rows = _q(conn, f'''SELECT id, username, full_name, phone FROM users WHERE deleted_at IS NULL AND active = 1
                        AND {_like('username', 'full_name', 'phone', 'email')} ORDER BY full_name LIMIT ?''',
             (*[pat] * 4, PER_GROUP))
    return {'user': [_item(r['id'], r['full_name'] or r['username'], r['username'], f"#/users/{r['id']}") for r in rows]}


def _visits(user, conn, pat, q):
    if not _can(user, 'secretariat'):
        return {}
    rows = _q(conn, f'''SELECT v.id, v.code, v.purpose, v.arrived_at, v.left_at,
                               (SELECT group_concat(full_name, ', ') FROM guest_visit_people WHERE visit_id = v.id) AS names,
                               (SELECT group_concat(DISTINCT company_text) FROM guest_visit_people WHERE visit_id = v.id) AS firms
                        FROM guest_visits v
                        WHERE {_like('v.code', 'v.purpose', 'v.note')} OR v.id IN
                              (SELECT visit_id FROM guest_visit_people WHERE {_like('full_name', 'company_text', 'phone')})
                        ORDER BY v.id DESC LIMIT ?''', (*[pat] * 6, PER_GROUP))
    return {'visit': [_item(r['id'], r['names'] or r['code'],
                            ' · '.join(x for x in (r['firms'], (r['arrived_at'] or '')[:10], r['purpose']) if x),
                            f"#/secretariat/visit/{r['id']}") for r in rows]}


def _documents(user, conn, pat, q):
    if not _can(user, 'documents', 'companies'):
        return {}
    tokens = _tokens(q)
    if not tokens:
        return {}
    vis, args = ('1', []) if _is_admin(user) else _visible_sql(user)
    rows = []
    for phrase in (True, False):
        rows = _q(conn, f'''SELECT d.id, d.title, d.file_name, d.kind, d.doc_date, d.uploaded_at FROM documents d
                            JOIN documents_fts f ON f.rowid = d.id WHERE {vis} AND documents_fts MATCH ?
                            ORDER BY bm25(documents_fts, 5.0, 1.0) LIMIT ?''', (*args, _match_query(tokens, phrase), PER_GROUP))
        if rows or len(tokens) == 1:
            break
    out = []
    for d in rows:
        full = conn.execute('SELECT title, note, ocr_text FROM documents WHERE id = ?', (d['id'],)).fetchone()
        snip = _snippet(tokens, full['ocr_text'], full['note'], full['title']) if full else None
        out.append(_item(d['id'], d['title'] or d['file_name'],
                         ' · '.join(x for x in (d['kind'], (d['doc_date'] or d['uploaded_at'] or '')[:10]) if x),
                         f"#/documents/{d['id']}", snippet=snip))
    return {'document': out}


def _projects(user, conn, pat, q):
    if not _can(user, 'projects'):
        return {}
    rows = _q(conn, f'''SELECT id, code, name, status FROM projects WHERE {_like('code', 'name', 'summary', 'keywords')}
                        ORDER BY id DESC LIMIT ?''', (*[pat] * 4, PER_GROUP))
    return {'project': [_item(r['id'], r['name'], ' · '.join(x for x in (r['code'], r['status']) if x),
                              f"#/projects/{r['id']}") for r in rows]}


def _purchasing(user, conn, pat, q):
    if not _can(user, 'purchasing'):
        return {}
    reqs = _q(conn, f'''SELECT id, code, title, status FROM purchase_requests WHERE {_like('code', 'title', 'note')}
                        ORDER BY id DESC LIMIT ?''', (*[pat] * 3, PER_GROUP))
    quotes = _q(conn, f'''SELECT q.id, q.code, q.status, c.name AS supplier FROM quotes q LEFT JOIN companies c ON c.id = q.company_id
                          WHERE {_like('q.code', 'q.note', 'c.name')} ORDER BY q.id DESC LIMIT ?''', (*[pat] * 3, PER_GROUP))
    return {'request': [_item(r['id'], r['title'] or r['code'], ' · '.join(x for x in (r['code'], r['status']) if x),
                              f"#/purchasing/requests/{r['id']}") for r in reqs],
            'quote': [_item(r['id'], r['code'], ' · '.join(x for x in (r['supplier'], r['status']) if x),
                            f"#/purchasing/quotes/{r['id']}") for r in quotes]}


def _invoices(user, conn, pat, q):
    if not _can(user, 'sales', 'purchasing'):
        return {}
    rows = _q(conn, f'''SELECT id, number, kind, company_name, total, invoice_date AS date FROM invoices
                        WHERE {_like('number', 'company_name', 'note')} ORDER BY id DESC LIMIT ?''', (*[pat] * 3, PER_GROUP))
    out = []
    for r in rows:
        if r['kind'] == 'alis' and not _can(user, 'purchasing'):
            continue
        if r['kind'] != 'alis' and not _can(user, 'sales'):
            continue
        out.append(_item(r['id'], r['number'], ' · '.join(x for x in (r['company_name'], (r['date'] or '')[:10]) if x),
                         '#/purchasing/invoices' if r['kind'] == 'alis' else '#/sales'))
    return {'invoice': out}


def _vehicles(user, conn, pat, q):
    if not _can(user, 'fleet'):
        return {}
    rows = _q(conn, f'''SELECT id, plate, brand, model, description FROM field_vehicles WHERE active = 1
                        AND {_like('plate', 'brand', 'model', 'description')} ORDER BY plate LIMIT ?''', (*[pat] * 4, PER_GROUP))
    return {'vehicle': [_item(r['id'], r['plate'], ' · '.join(x for x in (r['brand'], r['model']) if x), f"#/fleet/{r['id']}")
                        for r in rows]}


def _accounts(user, conn, pat, q):
    if not _can(user, 'finance.bank', 'finance.cari'):
        return {}
    rows = _q(conn, f'''SELECT id, name, kind, iban, company_id FROM fin_accounts WHERE active = 1
                        AND {_like('name', 'iban', 'mikro_code')} ORDER BY name LIMIT ?''', (*[pat] * 3, PER_GROUP))
    out = []
    for r in rows:
        if r['kind'] == 'cari':
            if _can(user, 'finance.cari') and r['company_id']:
                out.append(_item(r['id'], r['name'], 'Cari hesap', f"#/finance/cari/{r['company_id']}"))
        elif _can(user, 'finance.bank'):
            out.append(_item(r['id'], r['name'], ' · '.join(x for x in (r['kind'], r['iban']) if x), f"#/finance/bank/{r['id']}"))
    return {'account': out}


def _cargo(user, conn, pat, q):
    if not _can(user, 'secretariat'):
        return {}
    rows = _q(conn, f'''SELECT id, carrier, tracking_no, description, delivered_at FROM cargo
                        WHERE {_like('carrier', 'tracking_no', 'description')} ORDER BY id DESC LIMIT ?''', (*[pat] * 3, PER_GROUP))
    return {'cargo': [_item(r['id'], r['description'] or r['tracking_no'],
                            ' · '.join(x for x in (r['carrier'], r['tracking_no'], 'Teslim edildi' if r['delivered_at'] else None) if x),
                            '#/secretariat/cargo') for r in rows]}


def _posts(user, conn, pat, q):
    rows = _q(conn, f'''SELECT p.id, p.text, p.ref_link, p.created_at, u.full_name FROM feed_posts p LEFT JOIN users u ON u.id = p.author_id
                        WHERE p.deleted_at IS NULL AND p.removed_by IS NULL AND {_like('p.text')} ORDER BY p.id DESC LIMIT ?''',
             (pat, PER_GROUP))
    return {'post': [_item(r['id'], (r['text'] or '')[:120], ' · '.join(x for x in (r['full_name'], (r['created_at'] or '')[:10]) if x),
                           r['ref_link'] or '#/') for r in rows]}


def _todos(user, conn, pat, q):
    rows = _q(conn, f'''SELECT id, title, status FROM todos WHERE (assignee_id = ? OR created_by = ?) AND {_like('title', 'note')}
                        ORDER BY id DESC LIMIT ?''', (user['id'], user['id'], pat, pat, PER_GROUP))
    return {'todo': [_item(r['id'], r['title'], r['status'] or '', f"#/my-todos/{r['id']}") for r in rows]}


SOURCES = (_companies, _people, _products, _orders, _employees, _users, _visits, _documents, _projects, _purchasing, _invoices,
           _vehicles, _accounts, _cargo, _posts, _todos)
ORDER = ('company', 'supplier', 'person', 'product', 'material', 'order', 'employee', 'user', 'visit', 'document', 'project',
         'request', 'quote', 'invoice', 'vehicle', 'account', 'cargo', 'post', 'todo')


def search(conn, user, q):
    q = (q or '').strip()
    if len(q) < MIN_LEN:
        return []
    conn.create_function('trfold', 1, fold, deterministic=True)
    pat = _pattern(q)
    found = {}
    for src in SOURCES:
        for key, items in src(user, conn, pat, q).items():
            if items:
                found.setdefault(key, []).extend(items[:PER_GROUP])
    return [{'type': k, 'label': LABELS[k], 'items': found[k]} for k in ORDER if k in found]


@router.get('')
def global_search(q: str = '', user=Depends(auth.current_user), conn=db.DB):
    return {'q': q, 'min': MIN_LEN, 'groups': search(conn, user, q)}
