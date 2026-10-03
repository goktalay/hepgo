"""İnsan Kaynakları: personel kayıtları, iş başvuruları, özlük dosyaları, sözleşmeler ve izinler.

Her kullanıcı aynı zamanda bir personeldir (employees.user_id); kullanıcısı olmayan personel iş başvurusuyla açılır.
Ayırt edici alan TC Kimlik Numarasıdır. Başvuru (BASVURU) personel ve kullanıcı listelerinde görünmez; İK kabul
edince (görev, maaş, resmi işe başlama tarihi) AKTIF personel olur, reddederken sebep girilir.
Zorunlu özlük dosyaları ve sözleşmelerden eksiği olan aktif personel kırmızı çerçeveyle gösterilir.
İzin: personel Kişisel › İzinlerim'den ücretli / ücretsiz izin ister; İK onaylarken tarihleri değiştirebilir,
istenen ve verilen tarihler ayrı saklanır.
"""
import json
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import auth, config, db
from ..files import FILE_GUARDS, save_upload

router = APIRouter(prefix='/api/hr')
me_router = APIRouter(prefix='/api/me/leaves')
hr_user = auth.require_module('hr')


def upcoming_birthdays(conn, days=30, limit=100):
    """Yaklaşan personel doğum günleri (aktif personel). [{name, date, days, age, today, user_id, photo}]."""
    rows = db.rows(conn.execute(
        '''SELECT e.first_name || ' ' || e.last_name AS name, e.birth_date, e.user_id, u.photo
           FROM employees e LEFT JOIN users u ON u.id = e.user_id
           WHERE e.status = 'AKTIF' AND e.birth_date IS NOT NULL AND e.birth_date != '' '''))
    today = date.today()
    out = []
    for r in rows:
        bd = (r['birth_date'] or '').strip()
        if len(bd) < 10:
            continue
        try:
            yr, mo, dy = int(bd[0:4]), int(bd[5:7]), int(bd[8:10])
            try:
                nxt = date(today.year, mo, dy)
            except ValueError:            # 29 Şubat → 28'ine denk getir
                nxt = date(today.year, mo, 28)
            if nxt < today:
                nxt = nxt.replace(year=today.year + 1)
            delta = (nxt - today).days
            if delta <= days:
                out.append({'name': r['name'], 'date': nxt.isoformat(), 'days': delta,
                            'age': nxt.year - yr, 'today': delta == 0, 'user_id': r['user_id'], 'photo': r['photo']})
        except (ValueError, TypeError):
            continue
    out.sort(key=lambda x: (x['days'], x['name']))
    return out[:limit]


@router.get('/birthdays')
def birthdays(days: int = 30, user=Depends(auth.current_user), conn=db.DB):
    """Yaklaşan doğum günleri — herkese açık (iş arkadaşlarının doğum günleri panoda/takvimde görünür)."""
    return {'items': upcoming_birthdays(conn, days=max(1, min(days, 366)), limit=100)}

SOURCES = ['Kariyer.net', 'Eleman Online', 'LinkedIn', 'Referans', 'İŞKUR', 'Şirket web sitesi', 'Doğrudan başvuru', 'Diğer']
# Zorunlu özlük dosyaları (askerlik yalnızca erkek personelde) ve sözleşmeler
PERSONNEL_FILES = {
    'ADLI_SICIL': 'Adli Sicil Belgesi',
    'SAGLIK': 'Sağlık Raporu',
    'ASKERLIK': 'Askerlik Durum Belgesi',
    'MEZUNIYET': 'Mezuniyet Belgesi',
    'HIZMET_DOKUMU': '4A Hizmet Dökümü',
    'BANKA': 'Banka Hesap Bilgi Dokümanı',
    'VESIKALIK': 'Vesikalık Fotoğraf',
    # İsteğe bağlı (eksik sayılmaz)
    'KIMLIK': 'Kimlik Kartı / Nüfus Cüzdanı',
    'IKAMETGAH': 'Yerleşim Yeri (İkametgâh) Belgesi',
    'SGK_GIRIS': 'SGK İşe Giriş Bildirgesi',
    'BASVURU': 'İş Başvuru Formu',
    'EHLIYET': 'Sürücü Belgesi (Ehliyet)',
    'SERTIFIKA': 'Sertifika / Yeterlilik Belgesi',
    'PASAPORT': 'Pasaport',
    'CALISMA_IZNI': 'Çalışma İzni',
    'VIZE': 'Vize',
    'IZIN_BELGESI': 'İzin Belgesi',
    'ISTIFA': 'İstifa Dilekçesi',
    'DIGER': 'Diğer Belge',
}
CONTRACTS = {
    'GIZLILIK': 'Gizlilik Sözleşmesi',
    'IS_SOZLESMESI': 'Belirsiz Süreli İş Sözleşmesi',
    'ARAC': 'Araç Kullanım Sözleşmesi',
    # İsteğe bağlı
    'TADIL': 'İş Sözleşmesi Tadil Protokolü',
    'KVKK': 'KVKK Aydınlatma Metni',
}
FILE_KINDS = {**PERSONNEL_FILES, **CONTRACTS}
REQUIRED_KINDS = ('ADLI_SICIL', 'SAGLIK', 'ASKERLIK', 'MEZUNIYET', 'HIZMET_DOKUMU', 'BANKA', 'VESIKALIK', 'GIZLILIK', 'IS_SOZLESMESI', 'ARAC')
# Görev tanımı maddelerinin gizlilik dereceleri. Genel ve Kurum İçi maddeler başka belgelerde (ör. saha görev raporu)
# kullanılabilir; Gizli ve Çok Gizli maddeler yalnızca İK ekranında görünür.
DUTY_LEVELS = {'GENEL': 'Genel', 'KURUM_ICI': 'Kurum İçi', 'GIZLI': 'Gizli', 'COK_GIZLI': 'Çok Gizli'}
# Görev tanımı bölümleri (İSG görev tanımı belgesindeki sırayla)
DUTY_SECTIONS = {'AMAC': 'Görevin Amacı', 'POZISYON': 'Uçuş Ekibi Pozisyonuna Özgü Görevler', 'ROL': 'Rollere Göre Görev ve Sorumluluklar',
                 'YETKI': 'Yetki ve Sınırlar', 'DIGER': 'Diğer'}
SHAREABLE_LEVELS = ('GENEL', 'KURUM_ICI')
ADDRESS_LABELS = ['Ev', 'İkametgâh', 'Tebligat', 'Acil durum', 'Diğer']
LEAVE_KINDS = {'UCRETLI': 'Ücretli izin', 'UCRETSIZ': 'Ücretsiz izin'}
STATUSES = {'BASVURU': 'İş başvurusu', 'REDDEDILDI': 'Reddedildi', 'AKTIF': 'Aktif', 'AYRILDI': 'Ayrıldı'}


def _hr_file_guard(user, name):
    if 'hr' in user['modules']:
        return True
    with db.connect() as conn:   # personel kendi yüklediği / kendi özlük dosyasını görebilir (Evraklarım)
        return bool(conn.execute('''SELECT 1 FROM employee_files f JOIN employees e ON e.id = f.employee_id
                                    WHERE f.path = ? AND e.user_id = ?''', (f'hr/{name}', user['id'])).fetchone())


FILE_GUARDS['hr'] = _hr_file_guard


# ---------- Yardımcılar

def valid_tc(tc):
    """TC Kimlik No: 11 hane, ilk hane 0 değil, 10. ve 11. hane kontrol basamakları."""
    if not re.fullmatch(r'[1-9]\d{10}', tc or ''):
        return False
    d = [int(c) for c in tc]
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def split_name(full):
    parts = (full or '').strip().split()
    if len(parts) < 2:
        return (parts[0] if parts else '—'), ''
    return ' '.join(parts[:-1]), parts[-1]


def _norm(s):
    return ' '.join((s or '').casefold().split())


def sync_users(conn):
    """Her (silinmemiş) kullanıcının bir personel kaydı olur: adı aynı olan, kullanıcısı olmayan aktif personele
    bağlanır; yoksa aktif personel olarak açılır (TC ve özlük bilgileri İK tarafından tamamlanır)."""
    missing = db.rows(conn.execute(
        '''SELECT id, full_name, phone, username, created_at FROM users
           WHERE deleted_at IS NULL AND id NOT IN (SELECT user_id FROM employees WHERE user_id IS NOT NULL)
             AND id NOT IN (SELECT user_id FROM company_people WHERE user_id IS NOT NULL)'''))   # dış firma personeli personel değildir
    if not missing:
        return
    free = {}
    for e in db.rows(conn.execute("SELECT id, first_name, last_name FROM employees WHERE user_id IS NULL AND status = 'AKTIF'")):
        free.setdefault(_norm(f'{e["first_name"]} {e["last_name"]}'), e['id'])
    for u in missing:
        eid = free.pop(_norm(u['full_name']), None)
        if eid:
            conn.execute('UPDATE employees SET user_id = ? WHERE id = ?', (u['id'], eid))
            continue
        first, last = split_name(u['full_name'])
        email = u['username'] if '@' in (u['username'] or '') else None
        conn.execute('''INSERT INTO employees (user_id, first_name, last_name, phone, email, status, created_at)
                        VALUES (?,?,?,?,?,'AKTIF',?)''', (u['id'], first, last, u['phone'], email, db.now()))


def event(conn, eid, user_id, action, detail=None):
    conn.execute('INSERT INTO employee_events (employee_id, user_id, action, detail, created_at) VALUES (?,?,?,?,?)',
                 (eid, user_id, action, detail, db.now()))


def required_kinds(e):
    """Bu personel için zorunlu dosya türleri (askerlik belgesi yalnızca erkekte; cinsiyet girilmemişse istenir)."""
    need = [k for k in REQUIRED_KINDS if not (k == 'ASKERLIK' and e.get('gender') == 'K')]
    if e.get('is_foreign'):   # yabancı uyruklu personel: askerlik yerine pasaport ve çalışma izni
        need = [k for k in need if k != 'ASKERLIK'] + ['PASAPORT', 'CALISMA_IZNI']
    return need


def current_files(conn, eid):
    """Tür başına en son yüklenen dosya."""
    out = {}
    for f in db.rows(conn.execute(
            '''SELECT f.*, u.full_name AS uploaded_by_name FROM employee_files f LEFT JOIN users u ON u.id = f.uploaded_by
               WHERE f.employee_id = ? ORDER BY f.id''', (eid,))):
        out[f['kind']] = f
    return out


def leave_days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days + 1
    except (TypeError, ValueError):
        return None


def _enrich(conn, e, files=None):
    files = files if files is not None else current_files(conn, e['id'])
    e['name'] = f'{e["first_name"]} {e["last_name"]}'.strip()
    need = required_kinds(e)
    e['missing'] = [FILE_KINDS[k] for k in need if k not in files] if e['status'] == 'AKTIF' else []
    e['missing_personnel'] = sum(1 for k in need if k in PERSONNEL_FILES and k not in files)
    e['missing_contracts'] = sum(1 for k in need if k in CONTRACTS and k not in files)
    e['pending_files'] = sum(1 for f in files.values() if not f.get('approved', 1))   # personelin yüklediği, onay bekleyen evrak sayısı
    e['photo_file'] = files.get('VESIKALIK', {}).get('path')
    e['status_label'] = STATUSES.get(e['status'], e['status'])
    return e


def _get(conn, eid):
    e = db.row(conn.execute(
        '''SELECT e.*, u.username, u.photo AS user_photo, u.active AS user_active, u.deleted_at AS user_deleted,
                  d.full_name AS decided_by_name, c.full_name AS created_by_name
           FROM employees e LEFT JOIN users u ON u.id = e.user_id LEFT JOIN users d ON d.id = e.decided_by
           LEFT JOIN users c ON c.id = e.created_by WHERE e.id = ?''', (eid,)))
    if not e:
        raise HTTPException(404, 'Personel bulunamadı')
    return e


def _date(v, label, required=False):
    v = (v or '').strip()
    if not v:
        if required:
            raise HTTPException(400, f'{label} zorunlu')
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f'{label} geçersiz')
    return v


class PersonIn(BaseModel):
    tc_no: str
    first_name: str
    last_name: str
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    is_foreign: bool = False          # yabancı uyruklu (TC yerine yabancı kimlik no; pasaport ve çalışma izni zorunlu)
    nationality: Optional[str] = None
    security_code: Optional[str] = None   # Kişi Güvenlik Kodu (MSB Tesis Güvenlik Belgesi)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    position: Optional[str] = None
    source: Optional[str] = None
    source_note: Optional[str] = None
    applied_at: Optional[str] = None
    note: Optional[str] = None
    # personel (kabul edilmiş) bilgileri
    title: Optional[str] = None
    department: Optional[str] = None
    salary: Optional[float] = None
    start_date: Optional[str] = None


class RejectIn(BaseModel):
    reason: str


class AcceptIn(BaseModel):
    title: str
    department: Optional[str] = None
    salary: Optional[float] = None
    start_date: str


class LeaveJobIn(BaseModel):
    end_date: str
    reason: Optional[str] = None


class LinkIn(BaseModel):
    user_id: Optional[int] = None


def _person_fields(conn, body, eid=None):
    tc = re.sub(r'\D', '', body.tc_no or '')
    if not valid_tc(tc):
        raise HTTPException(400, 'Geçerli bir TC Kimlik Numarası girin (11 hane)')
    other = db.row(conn.execute('SELECT id, first_name, last_name, status FROM employees WHERE tc_no = ? AND id IS NOT ?', (tc, eid)))
    if other:
        raise HTTPException(409, f'Bu TC Kimlik Numarasıyla kayıt var: {other["first_name"]} {other["last_name"]} '
                                 f'({STATUSES.get(other["status"], other["status"])}) #{other["id"]}')
    first, last = body.first_name.strip(), body.last_name.strip()
    if not first or not last:
        raise HTTPException(400, 'Ad ve soyad zorunlu')
    if body.gender not in (None, '', 'E', 'K'):
        raise HTTPException(400, 'Cinsiyet geçersiz')
    if body.source and body.source not in SOURCES:
        raise HTTPException(400, 'Başvuru kaynağı geçersiz')
    if body.salary is not None and not 0 <= body.salary <= 100_000_000:
        raise HTTPException(400, 'Maaş geçersiz')
    clean = lambda v, n=200: (v or '').strip()[:n] or None   # noqa: E731
    return {'tc_no': tc, 'first_name': first[:80], 'last_name': last[:80], 'gender': body.gender or None,
            'birth_date': _date(body.birth_date, 'Doğum tarihi'), 'phone': clean(body.phone, 40), 'email': clean(body.email, 120),
            'position': clean(body.position), 'source': body.source or None,
            'source_note': clean(body.source_note), 'applied_at': _date(body.applied_at, 'Başvuru tarihi'),
            'note': clean(body.note, 2000), 'is_foreign': 1 if body.is_foreign else 0,
            'nationality': clean(body.nationality, 60) if body.is_foreign else None,
            'security_code': clean(body.security_code, 60)}


# ---------- Personel ve başvurular

@router.get('/meta')
def meta(user=Depends(hr_user)):
    return {'address_labels': ADDRESS_LABELS, 'sources': SOURCES, 'personnel_files': PERSONNEL_FILES, 'contracts': CONTRACTS, 'leave_kinds': LEAVE_KINDS, 'statuses': STATUSES, 'duty_levels': DUTY_LEVELS,
            'duty_sections': DUTY_SECTIONS}


@router.get('/employees')
def list_employees(user=Depends(hr_user), conn=db.DB):
    sync_users(conn)
    rows = db.rows(conn.execute(
        '''SELECT e.*, u.username, u.photo AS user_photo, u.active AS user_active, u.deleted_at AS user_deleted
           FROM employees e LEFT JOIN users u ON u.id = e.user_id ORDER BY e.first_name, e.last_name'''))
    files = {}
    for f in db.rows(conn.execute('SELECT employee_id, kind, path FROM employee_files ORDER BY id')):
        files.setdefault(f['employee_id'], {})[f['kind']] = f
    today = date.today().isoformat()
    on_leave = {r[0] for r in conn.execute(
        "SELECT employee_id FROM leave_requests WHERE status = 'ONAYLANDI' AND start_date <= ? AND end_date >= ?", (today, today))}
    unsigned = dict(conn.execute(
        "SELECT employee_id, COUNT(*) FROM leave_requests WHERE status = 'ONAYLANDI' AND signed_file IS NULL GROUP BY employee_id").fetchall())
    on_report = {r[0] for r in conn.execute(
        'SELECT employee_id FROM employee_health_reports WHERE start_date <= ? AND end_date >= ?', (today, today))}
    out = []
    for e in rows:
        _enrich(conn, e, files.get(e['id'], {}))
        e['on_report'] = e['id'] in on_report   # sağlık raporlu (bugün)
        e['on_leave'] = e['id'] in on_leave
        e['unsigned_leaves'] = unsigned.get(e['id'], 0)   # ıslak imzalı formu yüklenmemiş onaylı izin
        out.append(e)
    return out


@router.post('/applications')
def create_application(body: PersonIn, user=Depends(hr_user), conn=db.DB):
    """İş başvurusu: personel kaydı BASVURU durumunda açılır (henüz personel ve kullanıcı değildir)."""
    f = _person_fields(conn, body)
    f['applied_at'] = f['applied_at'] or date.today().isoformat()
    if not f['source']:
        raise HTTPException(400, 'Başvuru kaynağını seçin')
    cols = ', '.join(f)
    eid = conn.execute(f'INSERT INTO employees ({cols}, status, created_at, created_by) VALUES ({",".join("?" * len(f))}, ?, ?, ?)',
                       (*f.values(), 'BASVURU', db.now(), user['id'])).lastrowid
    event(conn, eid, user['id'], 'İş başvurusu açıldı', f'{f["source"]}{" · " + f["source_note"] if f["source_note"] else ""}'
          f'{" · " + f["position"] if f["position"] else ""}')
    db.audit(conn, user['id'], 'İş başvurusu açtı', 'employee', eid, f'{f["first_name"]} {f["last_name"]}')
    return {'id': eid}


@router.get('/employees/{eid}')
def get_employee(eid: int, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    files = current_files(conn, eid)
    _enrich(conn, e, files)
    e['files'] = files
    e['file_history'] = db.rows(conn.execute(
        '''SELECT f.id, f.kind, f.file_name, f.path, f.created_at, f.approved, f.note, u.full_name AS uploaded_by_name FROM employee_files f
           LEFT JOIN users u ON u.id = f.uploaded_by WHERE f.employee_id = ? ORDER BY f.id DESC''', (eid,)))
    e['required'] = required_kinds(e)
    e['events'] = db.rows(conn.execute(
        '''SELECT ev.*, u.full_name AS user_name FROM employee_events ev LEFT JOIN users u ON u.id = ev.user_id
           WHERE ev.employee_id = ? ORDER BY ev.id DESC''', (eid,)))
    e['leaves'] = _leaves(conn, 'l.employee_id = ?', (eid,))
    e['unsigned_leaves'] = sum(1 for l in e['leaves'] if l['status'] == 'ONAYLANDI' and not l['signed_file'])
    e['addresses'] = db.rows(conn.execute(
        'SELECT * FROM employee_addresses WHERE employee_id = ? ORDER BY is_primary DESC, id', (eid,)))
    e['family'] = db.rows(conn.execute(
        '''SELECT fm.*, (SELECT COUNT(*) FROM face_enroll WHERE family_id = fm.id) AS face_count
           FROM family_members fm WHERE fm.employee_id = ? ORDER BY fm.id''', (eid,)))
    e['duties'] = _duties(conn, eid)
    e['isg'] = _isg(conn, e)
    e['health_reports'] = _health(conn, eid)
    e['absence'] = auth.absence(conn, e['user_id']) if e.get('user_id') else None
    try:
        e['application_info'] = json.loads(e['application_info']) if e.get('application_info') else {}
    except (ValueError, TypeError):
        e['application_info'] = {}
    e['has_application_form'] = bool([1 for f in e['file_history'] if f['kind'] == 'BASVURU'])
    e['card_no'] = conn.execute('SELECT kart_id FROM pdks_links WHERE employee_id = ? LIMIT 1', (eid,)).fetchone()   # PDKS kart no (kart barkodu)
    e['card_no'] = e['card_no'][0] if e['card_no'] else None
    e['org_path'] = _org_path(conn, eid)
    return e


LOGGED = {'title': 'Görev', 'department': 'Departman', 'salary': 'Maaş', 'start_date': 'İşe başlama tarihi'}


def _fmt(k, v):
    if v is None or v == '':
        return '—'
    if k == 'salary':
        return f'{v:,.2f} ₺'.replace(',', 'X').replace('.', ',').replace('X', '.')
    if k == 'start_date':
        return f'{v[8:10]}.{v[5:7]}.{v[:4]}'
    return str(v)


@router.put('/employees/{eid}')
def update_employee(eid: int, body: PersonIn, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    f = _person_fields(conn, body, eid)
    if e['status'] in ('AKTIF', 'AYRILDI'):
        f['title'] = (body.title or '').strip()[:120] or None
        f['department'] = (body.department or '').strip()[:120] or None
        f['salary'] = body.salary
        f['start_date'] = _date(body.start_date, 'İşe başlama tarihi', required=e['status'] == 'AKTIF')
        changes = [f'{LOGGED[k]}: {_fmt(k, e[k])} → {_fmt(k, f[k])}' for k in LOGGED if (e[k] or None) != (f[k] or None)]
        if changes:
            event(conn, eid, user['id'], 'Personel bilgisi değişti', ' · '.join(changes))
    if not e['tc_no'] and f['tc_no']:
        event(conn, eid, user['id'], 'TC Kimlik Numarası girildi')
    conn.execute(f'UPDATE employees SET {", ".join(f"{k} = ?" for k in f)} WHERE id = ?', (*f.values(), eid))
    db.audit(conn, user['id'], 'Personel bilgilerini düzenledi', 'employee', eid, f'{f["first_name"]} {f["last_name"]}')
    return {'ok': True}


@router.post('/employees/{eid}/reject')
def reject(eid: int, body: RejectIn, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    if e['status'] != 'BASVURU':
        raise HTTPException(400, 'Yalnızca bekleyen iş başvurusu reddedilir')
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, 'Reddetme sebebini yazın')
    conn.execute("UPDATE employees SET status = 'REDDEDILDI', reject_reason = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                 (reason[:1000], db.now(), user['id'], eid))
    event(conn, eid, user['id'], 'Başvuru reddedildi', reason[:1000])
    db.audit(conn, user['id'], 'İş başvurusunu reddetti', 'employee', eid, reason[:200])
    return {'ok': True}


@router.post('/employees/{eid}/reopen')
def reopen(eid: int, user=Depends(hr_user), conn=db.DB):
    """Reddedilen başvuru yeniden değerlendirmeye alınır (ör. yeniden başvuru)."""
    e = _get(conn, eid)
    if e['status'] != 'REDDEDILDI':
        raise HTTPException(400, 'Yalnızca reddedilen başvuru yeniden açılır')
    conn.execute("UPDATE employees SET status = 'BASVURU', applied_at = ? WHERE id = ?", (date.today().isoformat(), eid))
    event(conn, eid, user['id'], 'Başvuru yeniden değerlendirmeye alındı')
    return {'ok': True}


@router.post('/employees/{eid}/accept')
def accept(eid: int, body: AcceptIn, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    if e['status'] != 'BASVURU':
        raise HTTPException(400, 'Yalnızca bekleyen iş başvurusu kabul edilir')
    title = body.title.strip()
    if not title:
        raise HTTPException(400, 'Görevi yazın')
    start = _date(body.start_date, 'Resmi işe başlama tarihi', required=True)
    if body.salary is not None and not 0 <= body.salary <= 100_000_000:
        raise HTTPException(400, 'Maaş geçersiz')
    conn.execute('''UPDATE employees SET status = 'AKTIF', title = ?, department = ?, salary = ?, start_date = ?, decided_at = ?,
                    decided_by = ?, reject_reason = NULL WHERE id = ?''',
                 (title[:120], (body.department or '').strip()[:120] or None, body.salary, start, db.now(), user['id'], eid))
    event(conn, eid, user['id'], 'Başvuru kabul edildi, personel oldu',
          f'Görev: {title} · İşe başlama: {_fmt("start_date", start)}' + (f' · Maaş: {_fmt("salary", body.salary)}' if body.salary else ''))
    db.audit(conn, user['id'], 'İş başvurusunu kabul etti', 'employee', eid, title)
    return {'ok': True}


@router.post('/employees/{eid}/leave-job')
def leave_job(eid: int, body: LeaveJobIn, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    if e['status'] != 'AKTIF':
        raise HTTPException(400, 'Yalnızca aktif personelin işten ayrılışı girilir')
    end = _date(body.end_date, 'İşten ayrılış tarihi', required=True)
    conn.execute("UPDATE employees SET status = 'AYRILDI', end_date = ?, end_reason = ? WHERE id = ?",
                 (end, (body.reason or '').strip()[:500] or None, eid))
    event(conn, eid, user['id'], 'İşten ayrıldı', f'{_fmt("start_date", end)}' + (f' · {body.reason.strip()}' if (body.reason or '').strip() else ''))
    return {'ok': True}


@router.post('/employees/{eid}/rehire')
def rehire(eid: int, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    if e['status'] != 'AYRILDI':
        raise HTTPException(400, 'Yalnızca ayrılan personel yeniden aktif yapılır')
    conn.execute("UPDATE employees SET status = 'AKTIF', end_date = NULL, end_reason = NULL WHERE id = ?", (eid,))
    event(conn, eid, user['id'], 'Yeniden işe alındı')
    return {'ok': True}


@router.get('/users')
def link_options(user=Depends(hr_user), conn=db.DB):
    """Personele bağlanabilecek kullanıcılar (bilgisi girilmemiş, otomatik açılmış personel kaydı olanlar dahil)."""
    return db.rows(conn.execute(
        '''SELECT u.id, u.full_name, u.username, e.id AS employee_id, e.tc_no FROM users u
           LEFT JOIN employees e ON e.user_id = u.id WHERE u.deleted_at IS NULL ORDER BY u.full_name'''))


@router.put('/employees/{eid}/user')
def link_user(eid: int, body: LinkIn, user=Depends(hr_user), conn=db.DB):
    """Personeli sistem kullanıcısıyla eşleştirir. Kullanıcının otomatik açılmış (TC'si ve dosyası olmayan) kaydı birleştirilir."""
    e = _get(conn, eid)
    if body.user_id is None:
        conn.execute('UPDATE employees SET user_id = NULL WHERE id = ?', (eid,))
        event(conn, eid, user['id'], 'Kullanıcı bağlantısı kaldırıldı')
        return {'ok': True}
    u = db.row(conn.execute('SELECT id, full_name FROM users WHERE id = ? AND deleted_at IS NULL', (body.user_id,)))
    if not u:
        raise HTTPException(404, 'Kullanıcı bulunamadı')
    other = db.row(conn.execute('SELECT * FROM employees WHERE user_id = ? AND id != ?', (u['id'], eid)))
    if other:
        used = other['tc_no'] or conn.execute('SELECT 1 FROM employee_files WHERE employee_id = ?', (other['id'],)).fetchone() \
            or conn.execute('SELECT 1 FROM leave_requests WHERE employee_id = ?', (other['id'],)).fetchone()
        if used:
            raise HTTPException(400, f'{u["full_name"]} başka bir personel kaydına bağlı (#{other["id"]}); önce o kaydın bağlantısını kaldırın')
        conn.execute('DELETE FROM employee_events WHERE employee_id = ?', (other['id'],))
        conn.execute('DELETE FROM employees WHERE id = ?', (other['id'],))
    conn.execute('UPDATE employees SET user_id = ? WHERE id = ?', (u['id'], eid))
    event(conn, eid, user['id'], 'Kullanıcıyla eşleştirildi', u['full_name'])
    return {'ok': True, 'merged': other['id'] if other else None, 'status': e['status']}


# ---------- Adresler (birden fazla; biri birincil)

class AddressIn(BaseModel):
    label: str
    address: str
    district: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    note: Optional[str] = None
    is_primary: bool = False


def _address_fields(body):
    address = body.address.strip()
    if not address:
        raise HTTPException(400, 'Adresi yazın')
    label = body.label.strip()[:40] or 'Diğer'
    clean = lambda v, n: (v or '').strip()[:n] or None   # noqa: E731
    pc = clean(body.postal_code, 10)
    if pc and not re.fullmatch(r'\d{5}', pc):
        raise HTTPException(400, 'Posta kodu 5 haneli olmalı')
    return {'label': label, 'address': address[:1000], 'district': clean(body.district, 80), 'city': clean(body.city, 80),
            'postal_code': pc, 'note': clean(body.note, 300)}


def _set_primary(conn, eid, aid, primary):
    """İstenirse bu adres birincil olur; personelin birincil adresi yoksa (ilk adres) kendiliğinden birincildir."""
    if primary or not conn.execute('SELECT 1 FROM employee_addresses WHERE employee_id = ? AND is_primary = 1 AND id != ?', (eid, aid)).fetchone():
        conn.execute('UPDATE employee_addresses SET is_primary = (id = ?) WHERE employee_id = ?', (aid, eid))


def _address(conn, eid, aid):
    a = db.row(conn.execute('SELECT * FROM employee_addresses WHERE id = ? AND employee_id = ?', (aid, eid)))
    if not a:
        raise HTTPException(404, 'Adres bulunamadı')
    return a


@router.post('/employees/{eid}/addresses')
def add_address(eid: int, body: AddressIn, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    f = _address_fields(body)
    aid = conn.execute(f'INSERT INTO employee_addresses ({", ".join(f)}, employee_id, created_at) VALUES ({",".join("?" * len(f))}, ?, ?)',
                       (*f.values(), eid, db.now())).lastrowid
    _set_primary(conn, eid, aid, body.is_primary)
    event(conn, eid, user['id'], 'Adres eklendi', f'{f["label"]}: {f["address"]}')
    return {'id': aid}


@router.put('/employees/{eid}/addresses/{aid}')
def update_address(eid: int, aid: int, body: AddressIn, user=Depends(hr_user), conn=db.DB):
    old = _address(conn, eid, aid)
    f = _address_fields(body)
    conn.execute(f'UPDATE employee_addresses SET {", ".join(f"{k} = ?" for k in f)}, updated_at = ? WHERE id = ?', (*f.values(), db.now(), aid))
    _set_primary(conn, eid, aid, body.is_primary)
    if (old['label'], old['address']) != (f['label'], f['address']):
        event(conn, eid, user['id'], 'Adres değişti', f'{old["label"]}: {old["address"]} → {f["label"]}: {f["address"]}')
    return {'ok': True}


@router.delete('/employees/{eid}/addresses/{aid}')
def delete_address(eid: int, aid: int, user=Depends(hr_user), conn=db.DB):
    a = _address(conn, eid, aid)
    conn.execute('DELETE FROM employee_addresses WHERE id = ?', (aid,))
    if a['is_primary']:   # birincil silinince en eski adres birincil olur
        conn.execute('UPDATE employee_addresses SET is_primary = 1 WHERE id = '
                     '(SELECT id FROM employee_addresses WHERE employee_id = ? ORDER BY id LIMIT 1)', (eid,))
    event(conn, eid, user['id'], 'Adres silindi', f'{a["label"]}: {a["address"]}')
    return {'ok': True}


# ---------- Aile üyeleri (personel detayı › Ailesi) — yüz tanımada eğitilebilir

RELATIONS = ['Eş', 'Çocuk', 'Anne', 'Baba', 'Kardeş', 'Nişanlı', 'Diğer']


class FamilyIn(BaseModel):
    full_name: str
    relation: Optional[str] = None
    birth_date: Optional[str] = None
    phone: Optional[str] = None
    note: Optional[str] = None


def _family_fields(body):
    name = (body.full_name or '').strip()
    if not name:
        raise HTTPException(400, 'Ad soyad girilmeli')
    rel = (body.relation or '').strip()[:40] or None
    return {'full_name': name[:120], 'relation': rel, 'birth_date': _date(body.birth_date, 'Doğum tarihi'),
            'phone': (body.phone or '').strip()[:40] or None, 'note': (body.note or '').strip()[:500] or None}


@router.post('/employees/{eid}/family')
def add_family(eid: int, body: FamilyIn, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    f = _family_fields(body)
    fid = conn.execute(f'INSERT INTO family_members ({", ".join(f)}, employee_id, created_at) VALUES ({",".join("?" * len(f))}, ?, ?)',
                       (*f.values(), eid, db.now())).lastrowid
    event(conn, eid, user['id'], 'Aile üyesi eklendi', f'{f["full_name"]} ({f["relation"] or "yakın"})')
    return {'id': fid}


@router.put('/employees/{eid}/family/{fid}')
def update_family(eid: int, fid: int, body: FamilyIn, user=Depends(hr_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM family_members WHERE id = ? AND employee_id = ?', (fid, eid)).fetchone():
        raise HTTPException(404, 'Aile üyesi bulunamadı')
    f = _family_fields(body)
    conn.execute(f'UPDATE family_members SET {", ".join(f"{k} = ?" for k in f)} WHERE id = ?', (*f.values(), fid))
    return {'ok': True}


@router.delete('/employees/{eid}/family/{fid}')
def delete_family(eid: int, fid: int, user=Depends(hr_user), conn=db.DB):
    row = conn.execute('SELECT full_name FROM family_members WHERE id = ? AND employee_id = ?', (fid, eid)).fetchone()
    if not row:
        raise HTTPException(404, 'Aile üyesi bulunamadı')
    conn.execute('DELETE FROM family_members WHERE id = ?', (fid,))   # face_enroll CASCADE ile silinir
    event(conn, eid, user['id'], 'Aile üyesi silindi', row[0])
    try:
        from .. import facebridge
        facebridge.push(conn)   # silinen yüz izleri fabrikadan da düşsün
    except Exception:   # noqa: BLE001
        pass
    return {'ok': True}


def _family(conn, eid, fid):
    if not conn.execute('SELECT 1 FROM family_members WHERE id = ? AND employee_id = ?', (fid, eid)).fetchone():
        raise HTTPException(404, 'Aile üyesi bulunamadı')


@router.get('/employees/{eid}/family/{fid}/faces')
def family_faces(eid: int, fid: int, user=Depends(hr_user), conn=db.DB):
    """Aile üyesinin yüz tanıma eğitim fotoğrafları."""
    _family(conn, eid, fid)
    from .. import faceenroll
    return {'faces': faceenroll.list_for(conn, 'family', family_id=fid)}


@router.post('/employees/{eid}/family/{fid}/faces')
async def family_face_add(eid: int, fid: int, file: UploadFile = File(...), user=Depends(hr_user), conn=db.DB):
    """Aile üyesini yüz tanımada eğit: fotoğraf yükle."""
    _family(conn, eid, fid)
    from fastapi.concurrency import run_in_threadpool

    from .. import faceenroll
    import os
    import tempfile
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, 'Fotoğraf çok büyük (en çok 15 MB)')
    fd, tmp = tempfile.mkstemp(suffix='.jpg', dir=str(config.UPLOAD_DIR))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        ok, res = await run_in_threadpool(faceenroll.enroll, conn, 'family', None, None, tmp, user['id'], fid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    finally:
        os.unlink(tmp)
    if not ok:
        raise HTTPException(422, res)
    conn.commit()
    try:
        from .. import facebridge
        facebridge.push(conn)
    except Exception:   # noqa: BLE001
        pass
    return {'ok': True, 'face': res}


@router.delete('/employees/{eid}/family/{fid}/faces/{enroll_id}')
def family_face_del(eid: int, fid: int, enroll_id: int, user=Depends(hr_user), conn=db.DB):
    _family(conn, eid, fid)
    from .. import faceenroll
    if faceenroll.delete(conn, enroll_id):
        conn.commit()
        try:
            from .. import facebridge
            facebridge.push(conn)
        except Exception:   # noqa: BLE001
            pass
    return {'ok': True}


# ---------- Görev tanımı (madde madde, gizlilik dereceli)

def _duties(conn, eid):
    return db.rows(conn.execute('SELECT id, text, level, section, role, phase, sort, created_at, updated_at FROM employee_duties '
                                'WHERE employee_id = ? ORDER BY sort, id', (eid,)))


def shareable_duties(conn, user_ids):
    """Kullanıcı → paylaşılabilir (Genel / Kurum İçi) görev tanımı maddeleri. Diğer modüllerin belgeleri için."""
    if not user_ids:
        return {}
    q = ','.join('?' * len(user_ids))
    out, pos = {}, {}
    for uid, text, section in conn.execute(
            f'''SELECT e.user_id, d.text, d.section FROM employee_duties d JOIN employees e ON e.id = d.employee_id
                WHERE e.user_id IN ({q}) AND d.level IN ({','.join('?' * len(SHAREABLE_LEVELS))}) ORDER BY d.sort, d.id''',
            (*user_ids, *SHAREABLE_LEVELS)):
        out.setdefault(uid, []).append(text)
        if section == 'POZISYON':
            pos.setdefault(uid, []).append(text)
    # Uçuş ekibi pozisyonu görevleri varsa saha belgelerinde onlar yazılır (uzun rol listesi yerine)
    return {uid: pos.get(uid) or items for uid, items in out.items()}


class DutyIn(BaseModel):
    text: str
    level: str = 'KURUM_ICI'
    section: str = 'DIGER'
    role: Optional[str] = None
    phase: Optional[str] = None


class DutyOrderIn(BaseModel):
    ids: list[int]


def _duty_fields(body):
    text = (body.text or '').strip()[:2000]
    if not text:
        raise HTTPException(400, 'Görev tanımı maddesini yazın')
    if body.level not in DUTY_LEVELS:
        raise HTTPException(400, 'Geçersiz gizlilik derecesi')
    if body.section not in DUTY_SECTIONS:
        raise HTTPException(400, 'Geçersiz bölüm')
    return text, body.level


@router.post('/employees/{eid}/duties')
def add_duty(eid: int, body: DutyIn, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    text, level = _duty_fields(body)
    top = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM employee_duties WHERE employee_id = ?', (eid,)).fetchone()[0]
    conn.execute('INSERT INTO employee_duties (employee_id, text, level, sort, created_at, created_by, section, role, phase) VALUES (?,?,?,?,?,?,?,?,?)',
                 (eid, text, level, top, db.now(), user['id'], body.section,
                  (body.role or '').strip()[:80] or None, (body.phase or '').strip()[:80] or None))
    event(conn, eid, user['id'], 'Görev tanımı maddesi eklendi', f'[{DUTY_LEVELS[level]}] {text[:200]}')
    return _duties(conn, eid)


@router.put('/employees/{eid}/duties/{did}')
def update_duty(eid: int, did: int, body: DutyIn, user=Depends(hr_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM employee_duties WHERE id = ? AND employee_id = ?', (did, eid)))
    if not old:
        raise HTTPException(404, 'Madde bulunamadı')
    text, level = _duty_fields(body)
    conn.execute('UPDATE employee_duties SET text = ?, level = ?, section = ?, role = ?, phase = ?, updated_at = ? WHERE id = ?',
                 (text, level, body.section, (body.role or '').strip()[:80] or None, (body.phase or '').strip()[:80] or None, db.now(), did))
    if (old['text'], old['level']) != (text, level):
        event(conn, eid, user['id'], 'Görev tanımı maddesi değişti', f'[{DUTY_LEVELS[level]}] {text[:200]}')
    return _duties(conn, eid)


@router.delete('/employees/{eid}/duties/{did}')
def delete_duty(eid: int, did: int, user=Depends(hr_user), conn=db.DB):
    old = db.row(conn.execute('SELECT * FROM employee_duties WHERE id = ? AND employee_id = ?', (did, eid)))
    if not old:
        raise HTTPException(404, 'Madde bulunamadı')
    conn.execute('DELETE FROM employee_duties WHERE id = ?', (did,))
    event(conn, eid, user['id'], 'Görev tanımı maddesi silindi', old['text'][:200])
    return _duties(conn, eid)


@router.put('/employees/{eid}/duties-order')
def order_duties(eid: int, body: DutyOrderIn, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    for i, did in enumerate(body.ids):
        conn.execute('UPDATE employee_duties SET sort = ? WHERE id = ? AND employee_id = ?', (i, did, eid))
    return _duties(conn, eid)


# ---------- İSG: görev tanımı üst bilgileri, KKD, eğitimler, tehlikeler, tebliğ-tebellüğ, görev matrisi, genel hükümler
ISG_LISTS = {   # tür → (tablo, alanlar)
    'ppe': ('employee_ppe', ('name', 'usage', 'issued_at', 'note')),
    'trainings': ('employee_trainings', ('name', 'done_at', 'valid_until', 'note')),
    'hazards': ('employee_hazards', ('hazard', 'control')),
}
ISG_KEY = 'isg.general'


def _isg(conn, e):
    out = {k: e.get(k) for k in ('flight_position', 'supervisor', 'deputy_id', 'deputy_note', 'emergency_duty',
                                 'duty_doc_no', 'duty_rev', 'duty_signed_at', 'duty_signed_file')}
    out['deputy_name'] = (conn.execute("SELECT first_name || ' ' || last_name FROM employees WHERE id = ?", (e['deputy_id'],)).fetchone() or [None])[0] if e.get('deputy_id') else None
    for kind, (table, cols) in ISG_LISTS.items():
        out[kind] = db.rows(conn.execute(f'SELECT id, {", ".join(cols)} FROM {table} WHERE employee_id = ? ORDER BY sort, id', (e['id'],)))
    return out


class IsgIn(BaseModel):
    flight_position: Optional[str] = None
    supervisor: Optional[str] = None
    deputy_id: Optional[int] = None
    deputy_note: Optional[str] = None
    emergency_duty: Optional[str] = None
    duty_doc_no: Optional[str] = None
    duty_rev: Optional[str] = None


@router.put('/employees/{eid}/isg')
def update_isg(eid: int, body: IsgIn, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    if body.deputy_id and (body.deputy_id == eid or not conn.execute('SELECT 1 FROM employees WHERE id = ?', (body.deputy_id,)).fetchone()):
        raise HTTPException(400, 'Geçersiz vekil')
    f = {k: (v.strip()[:2000] or None) if isinstance(v, str) else v for k, v in body.model_dump().items()}
    conn.execute(f'UPDATE employees SET {", ".join(f"{k} = ?" for k in f)} WHERE id = ?', (*f.values(), eid))
    event(conn, eid, user['id'], 'Görev tanımı bilgileri güncellendi', f.get('flight_position'))
    return _isg(conn, _get(conn, eid))


class IsgItemIn(BaseModel):
    name: Optional[str] = None
    usage: Optional[str] = None
    issued_at: Optional[str] = None
    note: Optional[str] = None
    done_at: Optional[str] = None
    valid_until: Optional[str] = None
    hazard: Optional[str] = None
    control: Optional[str] = None


def _isg_values(kind, body):
    table, cols = ISG_LISTS[kind]
    v = {c: ((getattr(body, c) or '').strip()[:1000] or None) for c in cols}
    first = cols[0]
    if not v[first]:
        raise HTTPException(400, 'Ad / tehlike alanı boş olamaz')
    for c in ('issued_at', 'done_at', 'valid_until'):
        if c in v and v[c]:
            v[c] = _date(v[c], 'Tarih')
    return table, v


@router.post('/employees/{eid}/isg/{kind}')
def add_isg_item(eid: int, kind: str, body: IsgItemIn, user=Depends(hr_user), conn=db.DB):
    if kind not in ISG_LISTS:
        raise HTTPException(404, 'Bilinmeyen liste')
    _get(conn, eid)
    table, v = _isg_values(kind, body)
    top = conn.execute(f'SELECT COALESCE(MAX(sort), 0) + 1 FROM {table} WHERE employee_id = ?', (eid,)).fetchone()[0]
    conn.execute(f'INSERT INTO {table} ({", ".join(v)}, employee_id, sort, created_at) VALUES ({",".join("?" * len(v))}, ?, ?, ?)',
                 (*v.values(), eid, top, db.now()))
    return _isg(conn, _get(conn, eid))


@router.put('/employees/{eid}/isg/{kind}/{iid}')
def update_isg_item(eid: int, kind: str, iid: int, body: IsgItemIn, user=Depends(hr_user), conn=db.DB):
    if kind not in ISG_LISTS:
        raise HTTPException(404, 'Bilinmeyen liste')
    table, v = _isg_values(kind, body)
    if not conn.execute(f'UPDATE {table} SET {", ".join(f"{k} = ?" for k in v)} WHERE id = ? AND employee_id = ?', (*v.values(), iid, eid)).rowcount:
        raise HTTPException(404, 'Kayıt bulunamadı')
    return _isg(conn, _get(conn, eid))


@router.delete('/employees/{eid}/isg/{kind}/{iid}')
def delete_isg_item(eid: int, kind: str, iid: int, user=Depends(hr_user), conn=db.DB):
    if kind not in ISG_LISTS:
        raise HTTPException(404, 'Bilinmeyen liste')
    conn.execute(f'DELETE FROM {ISG_LISTS[kind][0]} WHERE id = ? AND employee_id = ?', (iid, eid))
    return _isg(conn, _get(conn, eid))


# ---------- Sağlık raporları: rapor süresince personel raporlu görünür ve sisteme giremez
def _health(conn, eid):
    return db.rows(conn.execute(
        '''SELECT r.*, u.full_name AS created_by_name FROM employee_health_reports r LEFT JOIN users u ON u.id = r.created_by
           WHERE r.employee_id = ? ORDER BY r.start_date DESC, r.id DESC''', (eid,)))


@router.post('/employees/{eid}/health-reports')
async def add_health_report(eid: int, start_date: str = Form(...), end_date: str = Form(...), note: str = Form(''),
                            file: Optional[UploadFile] = File(None), user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    s, t = _date(start_date, 'Başlama tarihi', required=True), _date(end_date, 'Bitiş tarihi', required=True)
    if t < s:
        raise HTTPException(400, 'Bitiş tarihi başlama tarihinden önce olamaz')
    path = await save_upload('hr', file) if file is not None and file.filename else None
    conn.execute('''INSERT INTO employee_health_reports (employee_id, start_date, end_date, file, file_name, note, created_by, created_at)
                    VALUES (?,?,?,?,?,?,?,?)''', (eid, s, t, path, (file.filename or '')[:200] if path else None, (note or '').strip()[:500] or None, user['id'], db.now()))
    event(conn, eid, user['id'], 'Sağlık raporu eklendi', f'{s[8:10]}.{s[5:7]}.{s[:4]} – {t[8:10]}.{t[5:7]}.{t[:4]}')
    auth._absence_cache.pop(e.get('user_id'), None)   # rapor bugün başlıyorsa oturum hemen kapansın
    return _health(conn, eid)


@router.delete('/employees/{eid}/health-reports/{rid}')
def delete_health_report(eid: int, rid: int, user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    r = db.row(conn.execute('SELECT * FROM employee_health_reports WHERE id = ? AND employee_id = ?', (rid, eid)))
    if not r:
        raise HTTPException(404, 'Rapor bulunamadı')
    conn.execute('DELETE FROM employee_health_reports WHERE id = ?', (rid,))
    event(conn, eid, user['id'], 'Sağlık raporu silindi', f'{r["start_date"]} – {r["end_date"]}')
    auth._absence_cache.pop(e.get('user_id'), None)
    return _health(conn, eid)


@router.post('/employees/{eid}/duty-signed')
async def upload_duty_signed(eid: int, file: UploadFile = File(...), user=Depends(hr_user), conn=db.DB):
    """Islak imzalı görev tanımı (tebliğ-tebellüğ) taraması."""
    _get(conn, eid)
    path = await save_upload('hr', file)
    conn.execute('UPDATE employees SET duty_signed_file = ?, duty_signed_at = ? WHERE id = ?', (path, db.now(), eid))
    event(conn, eid, user['id'], 'İmzalı görev tanımı yüklendi', file.filename)
    return _isg(conn, _get(conn, eid))


@router.delete('/employees/{eid}/duty-signed')
def delete_duty_signed(eid: int, user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    conn.execute('UPDATE employees SET duty_signed_file = NULL, duty_signed_at = NULL WHERE id = ?', (eid,))
    event(conn, eid, user['id'], 'İmzalı görev tanımı kaldırıldı')
    return _isg(conn, _get(conn, eid))


@router.get('/matrix')
def duty_matrix(user=Depends(hr_user), conn=db.DB):
    """Personel – rol – uçuş ekibi görev matrisi ve acil durum görev dağılımı (aktif personel)."""
    rows = db.rows(conn.execute(
        '''SELECT e.id, e.first_name || ' ' || e.last_name AS name, e.title, e.flight_position, e.emergency_duty, e.supervisor,
                  e.deputy_note, e.duty_signed_at, d.first_name || ' ' || d.last_name AS deputy_name, e.user_id,
                  (SELECT COUNT(*) FROM employee_duties x WHERE x.employee_id = e.id) AS duty_count
           FROM employees e LEFT JOIN employees d ON d.id = e.deputy_id
           WHERE e.status = 'AKTIF' ORDER BY e.first_name, e.last_name'''))
    for r in rows:
        r['roles'] = [x[0] for x in conn.execute('SELECT role FROM user_roles WHERE user_id = ? ORDER BY role', (r['user_id'],))] if r['user_id'] else []
    return rows


ISG_DEFAULT = {'doc_no': '', 'rev': '', 'place': '', 'purpose': '', 'scope': '', 'legal': [], 'phases': [], 'zones': [], 'common': [], 'emergency_note': ''}


def isg_general(conn):
    import json
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (ISG_KEY,)).fetchone()
    try:
        return {**ISG_DEFAULT, **(json.loads(r[0]) if r else {})}
    except ValueError:
        return dict(ISG_DEFAULT)


@router.get('/isg-general')
def get_isg_general(user=Depends(hr_user), conn=db.DB):
    return isg_general(conn)


@router.put('/isg-general')
def put_isg_general(body: dict, user=Depends(hr_user), conn=db.DB):
    import json
    data = {k: body.get(k, v) for k, v in ISG_DEFAULT.items()}
    conn.execute('INSERT OR REPLACE INTO app_kv (k, v) VALUES (?, ?)', (ISG_KEY, json.dumps(data, ensure_ascii=False)))
    db.audit(conn, user['id'], 'İSG genel hükümlerini güncelledi', 'settings', None)
    return data


# ---------- Dosyalar: CV, özlük dosyaları, sözleşmeler

@router.post('/employees/{eid}/cv')
async def upload_cv(eid: int, file: UploadFile = File(...), user=Depends(hr_user), conn=db.DB):
    _get(conn, eid)
    path = await save_upload('hr', file)
    conn.execute('UPDATE employees SET cv_file = ?, cv_name = ? WHERE id = ?', (path, (file.filename or 'cv')[:200], eid))
    event(conn, eid, user['id'], 'CV yüklendi', file.filename)
    return {'path': path}


@router.post('/employees/{eid}/files/{kind}')
async def upload_file(eid: int, kind: str, file: UploadFile = File(...), user=Depends(hr_user), conn=db.DB):
    e = _get(conn, eid)
    if kind not in FILE_KINDS:
        raise HTTPException(400, 'Geçersiz dosya türü')
    if e['status'] not in ('AKTIF', 'AYRILDI'):
        raise HTTPException(400, 'Özlük dosyaları ve sözleşmeler kabul edilen personele girilir')
    path = await save_upload('hr', file)
    conn.execute('INSERT INTO employee_files (employee_id, kind, path, file_name, size, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)',
                 (eid, kind, path, (file.filename or kind)[:200], None, user['id'], db.now()))
    event(conn, eid, user['id'], f'{FILE_KINDS[kind]} yüklendi', file.filename)
    return {'path': path}


@router.delete('/employees/{eid}/files/{fid}')
def delete_file(eid: int, fid: int, user=Depends(hr_user), conn=db.DB):
    f = db.row(conn.execute('SELECT * FROM employee_files WHERE id = ? AND employee_id = ?', (fid, eid)))
    if not f:
        raise HTTPException(404, 'Dosya bulunamadı')
    conn.execute('DELETE FROM employee_files WHERE id = ?', (fid,))
    event(conn, eid, user['id'], f'{FILE_KINDS.get(f["kind"], f["kind"])} {"reddedildi" if not f["approved"] else "kaldırıldı"}', f['file_name'])
    return {'ok': True}


@router.post('/employees/{eid}/files/{fid}/approve')
def approve_file(eid: int, fid: int, user=Depends(hr_user), conn=db.DB):
    """Personelin kendi yüklediği (onayda bekleyen) özlük evrakını İK onaylar."""
    f = db.row(conn.execute('SELECT * FROM employee_files WHERE id = ? AND employee_id = ?', (fid, eid)))
    if not f:
        raise HTTPException(404, 'Dosya bulunamadı')
    if f['approved']:
        return {'ok': True}
    conn.execute('UPDATE employee_files SET approved = 1 WHERE id = ?', (fid,))
    event(conn, eid, user['id'], f'{FILE_KINDS.get(f["kind"], f["kind"])} onaylandı', f['file_name'])
    return {'ok': True}


@router.get('/pending-files')
def pending_files(user=Depends(hr_user), conn=db.DB):
    """Onay bekleyen (personelin kendi yüklediği) özlük evrakları."""
    return db.rows(conn.execute(
        '''SELECT f.id, f.employee_id, f.kind, f.file_name, f.path, f.created_at,
                  e.first_name || ' ' || e.last_name AS employee_name, u.full_name AS uploaded_by_name
           FROM employee_files f JOIN employees e ON e.id = f.employee_id
           LEFT JOIN users u ON u.id = f.uploaded_by
           WHERE f.approved = 0 ORDER BY f.id DESC'''))


# ---------- İzinler

class LeaveIn(BaseModel):
    kind: str
    start: str
    end: str
    reason: Optional[str] = None
    location: Optional[str] = None


class DecideIn(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    note: Optional[str] = None


def _leaves(conn, where, args=()):
    rows = db.rows(conn.execute(
        f'''SELECT l.*, e.first_name || ' ' || e.last_name AS employee_name, e.title AS employee_title, e.tc_no AS employee_tc, e.department AS employee_department, e.user_id,
                   r.full_name AS requested_by_name, d.full_name AS decided_by_name, s.full_name AS signed_by_name
            FROM leave_requests l JOIN employees e ON e.id = l.employee_id
            LEFT JOIN users r ON r.id = l.requested_by LEFT JOIN users d ON d.id = l.decided_by LEFT JOIN users s ON s.id = l.signed_by
            WHERE {where} ORDER BY l.req_start DESC, l.id DESC''', args))
    for r in rows:
        r['req_days'] = leave_days(r['req_start'], r['req_end'])
        r['days'] = leave_days(r['start_date'], r['end_date']) if r['start_date'] else None
        r['unsigned'] = r['status'] == 'ONAYLANDI' and not r['signed_file']
        r['changed'] = r['status'] == 'ONAYLANDI' and (r['start_date'], r['end_date']) != (r['req_start'], r['req_end'])
    return rows


def _leave_fields(body):
    if body.kind not in LEAVE_KINDS:
        raise HTTPException(400, 'İzin türünü seçin (ücretli / ücretsiz)')
    start, end = _date(body.start, 'İzin başlangıcı', True), _date(body.end, 'İzin bitişi', True)
    if end < start:
        raise HTTPException(400, 'İzin bitişi başlangıçtan önce olamaz')
    if leave_days(start, end) > 366:
        raise HTTPException(400, 'İzin en fazla bir yıl olabilir')
    reason = (body.reason or '').strip()
    if not reason:
        raise HTTPException(400, 'İzin sebebini yazın')
    location = (body.location or '').strip()
    if not location:
        raise HTTPException(400, 'İzinde nerede olacağınızı yazın')
    return start, end, reason[:1000], location[:300]


@router.get('/leaves')
def list_leaves(status: Optional[str] = None, date_from: str = '', date_to: str = '', user=Depends(hr_user), conn=db.DB):
    if status:
        return _leaves(conn, 'l.status = ?', (status,))
    if date_from or date_to:
        # İşlem bekleyenler (onay / imzalı form) ve yaklaşan / süren izinler her zaman; geçmiş izinler tarihi dönemle çakışıyorsa
        db.date_cond('x', date_from, date_to)   # biçim denetimi
        args, conds = [], []
        if date_to:
            conds.append('substr(COALESCE(l.start_date, l.req_start), 1, 10) <= ?'); args.append(date_to)
        if date_from:
            conds.append('substr(COALESCE(l.end_date, l.req_end), 1, 10) >= ?'); args.append(date_from)
        return _leaves(conn, f"""(l.status = 'BEKLIYOR' OR (l.status = 'ONAYLANDI' AND (l.signed_file IS NULL OR l.end_date >= date('now', 'localtime')))
                                 OR ({' AND '.join(conds)}))""", tuple(args))
    return _leaves(conn, '1 = 1')


@router.post('/employees/{eid}/leaves')
def hr_add_leave(eid: int, body: LeaveIn, user=Depends(hr_user), conn=db.DB):
    """İK personel adına izin girer (onaylı olarak kaydedilir)."""
    e = _get(conn, eid)
    if e['status'] != 'AKTIF':
        raise HTTPException(400, 'İzin yalnızca aktif personele girilir')
    start, end, reason, location = _leave_fields(body)
    lid = conn.execute(
        '''INSERT INTO leave_requests (employee_id, requested_by, kind, req_start, req_end, reason, location, status, start_date,
                                       end_date, decided_by, decided_at, created_at) VALUES (?,?,?,?,?,?,?,'ONAYLANDI',?,?,?,?,?)''',
        (eid, user['id'], body.kind, start, end, reason, location, start, end, user['id'], db.now(), db.now())).lastrowid
    db.audit(conn, user['id'], 'Personel adına izin girdi', 'leave', lid, f'{e["first_name"]} {e["last_name"]} {start}–{end}')
    return {'id': lid}


def _pending(conn, lid):
    r = db.row(conn.execute('SELECT * FROM leave_requests WHERE id = ?', (lid,)))
    if not r:
        raise HTTPException(404, 'İzin talebi bulunamadı')
    if r['status'] != 'BEKLIYOR':
        raise HTTPException(400, 'Bu talep zaten sonuçlandı')
    return r


@router.post('/leaves/{lid}/approve')
def approve_leave(lid: int, body: DecideIn, user=Depends(hr_user), conn=db.DB):
    auth._absence_cache.clear()   # izin bugünü kapsıyorsa kişi hemen izinli sayılsın
    r = _pending(conn, lid)
    start = _date(body.start, 'İzin başlangıcı') or r['req_start']
    end = _date(body.end, 'İzin bitişi') or r['req_end']
    if end < start:
        raise HTTPException(400, 'İzin bitişi başlangıçtan önce olamaz')
    conn.execute('''UPDATE leave_requests SET status = 'ONAYLANDI', start_date = ?, end_date = ?, decided_by = ?, decided_at = ?,
                    decision_note = ?, seen_at = NULL WHERE id = ?''',
                 (start, end, user['id'], db.now(), (body.note or '').strip()[:1000] or None, lid))
    db.audit(conn, user['id'], 'İzin talebini onayladı', 'leave', lid, f'{start}–{end}')
    return {'ok': True}


@router.post('/leaves/{lid}/reject')
def reject_leave(lid: int, body: DecideIn, user=Depends(hr_user), conn=db.DB):
    _pending(conn, lid)
    note = (body.note or '').strip()
    if not note:
        raise HTTPException(400, 'Reddetme sebebini yazın')
    conn.execute('''UPDATE leave_requests SET status = 'REDDEDILDI', decided_by = ?, decided_at = ?, decision_note = ?, seen_at = NULL
                    WHERE id = ?''', (user['id'], db.now(), note[:1000], lid))
    db.audit(conn, user['id'], 'İzin talebini reddetti', 'leave', lid, note[:200])
    return {'ok': True}


@router.post('/leaves/{lid}/signed')
async def upload_signed(lid: int, file: UploadFile = File(...), user=Depends(hr_user), conn=db.DB):
    """Onaylanan iznin ıslak imzalı formu (taranmış PDF / fotoğraf). Yüklenene kadar izin kırmızı görünür."""
    r = db.row(conn.execute('SELECT * FROM leave_requests WHERE id = ?', (lid,)))
    if not r:
        raise HTTPException(404, 'İzin kaydı bulunamadı')
    if r['status'] != 'ONAYLANDI':
        raise HTTPException(400, 'Islak imzalı form yalnızca onaylanan izne eklenir')
    path = await save_upload('hr', file)
    conn.execute('UPDATE leave_requests SET signed_file = ?, signed_name = ?, signed_at = ?, signed_by = ? WHERE id = ?',
                 (path, (file.filename or 'izin-formu')[:200], db.now(), user['id'], lid))
    event(conn, r['employee_id'], user['id'], 'Islak imzalı izin formu yüklendi', f'{r["start_date"]} – {r["end_date"]} · {file.filename}')
    return {'path': path}


@router.delete('/leaves/{lid}/signed')
def delete_signed(lid: int, user=Depends(hr_user), conn=db.DB):
    r = db.row(conn.execute('SELECT * FROM leave_requests WHERE id = ?', (lid,)))
    if not r or not r['signed_file']:
        raise HTTPException(404, 'Islak imzalı form bulunamadı')
    conn.execute('UPDATE leave_requests SET signed_file = NULL, signed_name = NULL, signed_at = NULL, signed_by = NULL WHERE id = ?', (lid,))
    event(conn, r['employee_id'], user['id'], 'Islak imzalı izin formu kaldırıldı', r['signed_name'])
    return {'ok': True}


# ---------- Kişisel › İzinlerim (her kullanıcı)

def my_employee(conn, user):
    sync_users(conn)
    e = db.row(conn.execute('SELECT id, status FROM employees WHERE user_id = ?', (user['id'],)))
    if not e:
        raise HTTPException(400, 'Personel kaydınız bulunamadı; İnsan Kaynakları ile görüşün')
    return e


@me_router.get('')
def my_leaves(user=Depends(auth.current_user), conn=db.DB):
    e = my_employee(conn, user)
    rows = _leaves(conn, 'l.employee_id = ?', (e['id'],))
    conn.execute("UPDATE leave_requests SET seen_at = ? WHERE employee_id = ? AND status != 'BEKLIYOR' AND seen_at IS NULL",
                 (db.now(), e['id']))
    year = str(date.today().year)
    used = sum(r['days'] or 0 for r in rows if r['status'] == 'ONAYLANDI' and r['kind'] == 'UCRETLI' and (r['start_date'] or '')[:4] == year)
    return {'items': rows, 'kinds': LEAVE_KINDS, 'used_paid_this_year': used}


@me_router.post('')
def request_leave(body: LeaveIn, user=Depends(auth.current_user), conn=db.DB):
    e = my_employee(conn, user)
    start, end, reason, location = _leave_fields(body)
    if start < date.today().isoformat():
        raise HTTPException(400, 'Geçmiş tarih için izin istenemez; İnsan Kaynakları ile görüşün')
    lid = conn.execute(
        '''INSERT INTO leave_requests (employee_id, requested_by, kind, req_start, req_end, reason, location, created_at)
           VALUES (?,?,?,?,?,?,?,?)''', (e['id'], user['id'], body.kind, start, end, reason, location, db.now())).lastrowid
    db.audit(conn, user['id'], 'İzin talebinde bulundu', 'leave', lid, f'{LEAVE_KINDS[body.kind]} {start}–{end}')
    return {'id': lid}


@me_router.delete('/{lid}')
def cancel_leave(lid: int, user=Depends(auth.current_user), conn=db.DB):
    e = my_employee(conn, user)
    r = db.row(conn.execute('SELECT * FROM leave_requests WHERE id = ? AND employee_id = ?', (lid, e['id'])))
    if not r:
        raise HTTPException(404, 'İzin talebi bulunamadı')
    if r['status'] != 'BEKLIYOR':
        raise HTTPException(400, 'Sonuçlanmış talep geri çekilemez; İnsan Kaynakları ile görüşün')
    conn.execute("UPDATE leave_requests SET status = 'IPTAL', decided_at = ?, seen_at = ? WHERE id = ?", (db.now(), db.now(), lid))
    return {'ok': True}


# ---------- Bildirimler (app/notifications.py)

def pending_leaves(conn):
    return _leaves(conn, "l.status = 'BEKLIYOR'")


def decided_unseen(conn, user_id):
    return _leaves(conn, "e.user_id = ? AND l.status IN ('ONAYLANDI', 'REDDEDILDI') AND l.seen_at IS NULL", (user_id,))


# ---------- Evraklarım: personel kendi eksik özlük evrakını yükler; tamamlanana kadar kırmızı uyarı ve geri sayım
docs_router = APIRouter(prefix='/api/me/documents')
DOCS_DAYS = 5
DOCS_START_KEY = 'hr.docs_deadline_start'


def _docs_start(conn):
    """Geri sayımın başladığı an (özellik açıldığında bir kez yazılır)."""
    r = conn.execute('SELECT v FROM app_kv WHERE k = ?', (DOCS_START_KEY,)).fetchone()
    if r:
        return r[0]
    now = db.now()
    conn.execute('INSERT OR IGNORE INTO app_kv (k, v) VALUES (?, ?)', (DOCS_START_KEY, now))
    return now


def my_docs(conn, user_id):
    """Kullanıcının bağlı olduğu aktif personelin eksik zorunlu evrakı: {employee_id, missing: [(tür, ad)], deadline} | None"""
    from datetime import datetime, timedelta
    e = db.row(conn.execute("SELECT * FROM employees WHERE user_id = ? AND status = 'AKTIF'", (user_id,)))
    if not e:
        return None
    files = current_files(conn, e['id'])
    missing = [(k, FILE_KINDS[k]) for k in required_kinds(e) if k not in files]
    start = max(_docs_start(conn), e['created_at'] or '')
    deadline = (datetime.fromisoformat(start[:19]) + timedelta(days=DOCS_DAYS)).isoformat(timespec='seconds')
    return {'employee_id': e['id'], 'missing': missing, 'deadline': deadline, 'files': files, 'employee': e}


@docs_router.get('')
def my_documents(user=Depends(auth.current_user), conn=db.DB):
    d = my_docs(conn, user['id'])
    if not d:
        return {'employee': None}
    need = set(required_kinds(d['employee']))
    kinds = [{'kind': k, 'label': FILE_KINDS[k], 'required': k in need, 'contract': k in CONTRACTS,
              'file': ({'name': d['files'][k]['file_name'], 'path': d['files'][k]['path'], 'at': d['files'][k]['created_at'],
                        'approved': d['files'][k]['approved']} if k in d['files'] else None)}
             for k in FILE_KINDS if k in need or k in d['files']]
    kinds.sort(key=lambda x: (x['file'] is not None, not x['required']))
    return {'employee': {'id': d['employee_id'], 'name': f"{d['employee']['first_name']} {d['employee']['last_name']}"},
            'kinds': kinds, 'missing': len(d['missing']), 'deadline': d['deadline'] if d['missing'] else None,
            'optional': {k: v for k, v in FILE_KINDS.items() if k not in need}}


@docs_router.post('/{kind}')
async def upload_my_document(kind: str, file: UploadFile = File(...), user=Depends(auth.current_user)):
    if kind not in FILE_KINDS:
        raise HTTPException(400, 'Geçersiz evrak türü')
    path = await save_upload('hr', file)
    with db.connect() as conn:
        e = db.row(conn.execute("SELECT id FROM employees WHERE user_id = ? AND status = 'AKTIF'", (user['id'],)))
        if not e:
            raise HTTPException(400, 'Hesabınız bir personel kaydına bağlı değil')
        conn.execute('INSERT INTO employee_files (employee_id, kind, path, file_name, size, note, uploaded_by, approved, created_at) VALUES (?,?,?,?,?,?,?,0,?)',
                     (e['id'], kind, path, (file.filename or kind)[:200], None, 'Personel tarafından yüklendi (Evraklarım)', user['id'], db.now()))
        event(conn, e['id'], user['id'], f'{FILE_KINDS[kind]} yüklendi (personel · onay bekliyor)', file.filename)
    return {'ok': True, 'pending': True}


# ---------- PDKS (giriş-çıkış) entegrasyonu: Firebird'den okunur, personelle eşlenir
_PDKS_TR = str.maketrans('İIıŞşĞğÜüÖöÇç', 'iiissgguuoocc')


def _pdks_key(s):
    return ' '.join((s or '').translate(_PDKS_TR).lower().split())


def pdks_links(conn, people):
    """PDKS kart_id → employee_id. Kayıtlı eşleşmeyi döndürür; eksikleri aktif personelle ad eşleştirip kaydeder."""
    links = {r[0]: r[1] for r in conn.execute('SELECT kart_id, employee_id FROM pdks_links WHERE employee_id IS NOT NULL')}
    by_name = {}
    for e in db.rows(conn.execute("SELECT id, first_name, last_name FROM employees WHERE status = 'AKTIF'")):
        by_name.setdefault(_pdks_key(f'{e["first_name"]} {e["last_name"]}'), e['id'])
    now = db.now()
    for p in people:
        card = p['kart_id']
        if not card or card in links:
            continue
        eid = by_name.get(_pdks_key(f'{p["ad"]} {p["soyad"]}'))
        conn.execute('INSERT OR REPLACE INTO pdks_links (kart_id, employee_id, pdks_name, matched_by, updated_at) VALUES (?,?,?,?,?)',
                     (card, eid, f'{p["ad"]} {p["soyad"]}'.strip(), 'ad' if eid else None, now))
        if eid:
            links[card] = eid
    return links


@router.get('/pdks/attendance')
async def pdks_attendance(date_from: str = '', date_to: str = '', user=Depends(hr_user)):
    """Seçili dönemde personel giriş-çıkış tablosu (PDKS Firebird, salt okuma). Yön tutulmadığından ilk okuma=giriş, son=çıkış."""
    from datetime import date as _d, timedelta
    from fastapi.concurrency import run_in_threadpool
    from .. import pdks
    if not pdks.configured():
        return {'enabled': False, 'message': 'PDKS bağlantısı Program Ayarları › Entegrasyonlar’dan tanımlanmalı.'}
    today = _d.today()
    df = date_from or (today - timedelta(days=6)).isoformat()
    dt = date_to or today.isoformat()
    try:
        people = await run_in_threadpool(pdks.fetch_personnel)
        att = await run_in_threadpool(pdks.daily_attendance, df, dt)
    except Exception as e:   # noqa: BLE001
        return {'enabled': True, 'from': df, 'to': dt, 'error': pdks._friendly(e)}

    def build():
        with db.connect() as conn:
            links = pdks_links(conn, people)
            emps = {e['id']: e for e in db.rows(conn.execute(
                "SELECT id, first_name, last_name, title, department FROM employees WHERE status = 'AKTIF'"))}
        days = [(_d.fromisoformat(df) + timedelta(days=i)).isoformat() for i in range((_d.fromisoformat(dt) - _d.fromisoformat(df)).days + 1)]
        pby = {p['kart_id']: p for p in people}
        rows, seen = [], set()
        for card, byday in att.items():
            eid = links.get(card)
            seen.add(card)
            name = (f"{emps[eid]['first_name']} {emps[eid]['last_name']}" if eid in emps
                    else (f"{pby[card]['ad']} {pby[card]['soyad']}".strip() if card in pby else f'Kart {card}'))
            rows.append({'kart_id': card, 'employee_id': eid, 'name': name, 'matched': eid in emps,
                         'title': emps[eid]['title'] if eid in emps else (pby.get(card, {}).get('unvan')),
                         'days': byday})
        rows.sort(key=lambda r: (not r['matched'], _pdks_key(r['name'])))
        # Hareketi olmayan eşli personel de görünsün (devamsızlık)
        linked_eids = {r['employee_id'] for r in rows if r['employee_id']}
        for eid, e in emps.items():
            if eid not in linked_eids:
                rows.append({'kart_id': None, 'employee_id': eid, 'name': f"{e['first_name']} {e['last_name']}",
                             'matched': True, 'title': e['title'], 'days': {}})
        unmatched = [pby[c]['ad'] + ' ' + pby[c]['soyad'] for c in seen if not links.get(c)]
        return {'enabled': True, 'from': df, 'to': dt, 'days': days, 'rows': rows, 'unmatched': unmatched}
    return await run_in_threadpool(build)


@router.get('/pdks/today')
async def pdks_today(user=Depends(hr_user)):
    """Bugün içeride görünen (en az bir okuma yapmış) personel: ana sayfa kutucuğu / hızlı bakış."""
    from datetime import date as _d
    from fastapi.concurrency import run_in_threadpool
    from .. import pdks
    if not pdks.configured():
        return {'enabled': False, 'count': 0, 'people': []}
    today = _d.today().isoformat()
    try:
        people = await run_in_threadpool(pdks.fetch_personnel)
        att = await run_in_threadpool(pdks.daily_attendance, today, today)
    except Exception:   # noqa: BLE001
        return {'enabled': True, 'count': 0, 'people': [], 'error': True}

    def build():
        with db.connect() as conn:
            links = pdks_links(conn, people)
            names = {e['id']: f"{e['first_name']} {e['last_name']}" for e in db.rows(conn.execute("SELECT id, first_name, last_name FROM employees"))}
        pby = {p['kart_id']: p for p in people}
        out = []
        for card, byday in att.items():
            v = byday.get(today)
            if not v:
                continue
            eid = links.get(card)
            out.append({'name': names.get(eid) or (f"{pby[card]['ad']} {pby[card]['soyad']}".strip() if card in pby else f'Kart {card}'),
                        'giris': v['giris'], 'cikis': v['cikis']})
        out.sort(key=lambda x: x['giris'])
        return {'enabled': True, 'count': len(out), 'people': out}
    return await run_in_threadpool(build)


class PdksLinkIn(BaseModel):
    kart_id: str
    employee_id: Optional[int] = None   # None = eşleşmeyi kaldır


@router.put('/pdks/link')
def pdks_link(body: PdksLinkIn, user=Depends(hr_user), conn=db.DB):
    """PDKS kart numarasını bir personele elle bağla / bağı kaldır (otomatik ad eşleştirmesini geçersiz kılar)."""
    if not body.kart_id:
        raise HTTPException(400, 'Kart numarası gerekli')
    if body.employee_id and not conn.execute('SELECT 1 FROM employees WHERE id = ?', (body.employee_id,)).fetchone():
        raise HTTPException(404, 'Personel bulunamadı')
    conn.execute('INSERT OR REPLACE INTO pdks_links (kart_id, employee_id, pdks_name, matched_by, updated_at) VALUES (?,?,?,?,?)',
                 (body.kart_id.strip(), body.employee_id, None, 'elle' if body.employee_id else 'yok', db.now()))
    db.audit(conn, user['id'], 'PDKS kart eşleştirmesi güncellendi', 'employee', body.employee_id, f'kart {body.kart_id}')
    return {'ok': True}


# ---------- İş Başvuru Formu okuma (Claude görüntü modeli): el yazısı formdan yapılandırılmış bilgi → İK onayı
@router.post('/employees/{eid}/application/parse')
async def parse_application(eid: int, user=Depends(hr_user)):
    """Personelin yüklü İş Başvuru Formu’nu okuyup taslak bilgi döndürür (KAYDETMEZ). Claude API gerektirir."""
    from fastapi.concurrency import run_in_threadpool
    from .. import application_form, config
    with db.connect() as conn:
        f = db.row(conn.execute("SELECT path, file_name FROM employee_files WHERE employee_id = ? AND kind = 'BASVURU' ORDER BY id DESC LIMIT 1", (eid,)))
    if not f:
        raise HTTPException(400, 'Bu personelde yüklü İş Başvuru Formu yok.')
    if not application_form.available():
        raise HTTPException(503, 'Claude API tanımlı değil (Program Ayarları › Entegrasyonlar).')
    try:
        r = await run_in_threadpool(application_form.extract, config.UPLOAD_DIR / f['path'])
    except Exception as e:   # noqa: BLE001
        raise HTTPException(502, f'Form okunamadı: {type(e).__name__} · {str(e)[:150]}')
    return {'fields': r['fields'], 'labels': application_form.FIELDS, 'file_name': f['file_name'], 'tokens': r['tokens']}


class ApplicationIn(BaseModel):
    info: dict = {}


@router.put('/employees/{eid}/application')
def save_application(eid: int, body: ApplicationIn, user=Depends(hr_user), conn=db.DB):
    """İK’nın gözden geçirdiği başvuru bilgilerini kaydeder."""
    import json
    from .. import application_form
    _get(conn, eid)
    clean = {k: (str(v).strip()[:500] or None) for k, v in (body.info or {}).items() if k in application_form.FIELDS}
    conn.execute('UPDATE employees SET application_info = ? WHERE id = ?', (json.dumps(clean, ensure_ascii=False), eid))
    event(conn, eid, user['id'], 'Başvuru bilgileri güncellendi')
    return {'ok': True, 'info': clean}


# ---------- Organizasyon şeması (üstten alta bağlı kartlar)
def _org_path(conn, eid):
    """Personelin organizasyon şemasındaki en üstten kendisine kadar zinciri: [{name, title, self}] (yoksa []).."""
    node = conn.execute('SELECT id, parent_id FROM org_nodes WHERE employee_id = ? LIMIT 1', (eid,)).fetchone()
    if not node:
        return []
    chain, cid, seen = [], node[0], set()
    sql = 'SELECT o.id, o.parent_id, o.title, e.first_name, e.last_name FROM org_nodes o LEFT JOIN employees e ON e.id = o.employee_id WHERE o.id = ?'
    while cid and cid not in seen:
        seen.add(cid)
        r = db.row(conn.execute(sql, (cid,)))
        if not r:
            break
        nm = ((r['first_name'] or '') + ' ' + (r['last_name'] or '')).strip() or '—'
        chain.append({'name': nm, 'title': r['title'], 'self': r['id'] == node[0]})
        cid = r['parent_id']
    return list(reversed(chain))


def _org_tree(conn):
    rows = db.rows(conn.execute('''SELECT o.id, o.parent_id, o.employee_id, o.title, o.sort,
        e.first_name, e.last_name, e.title AS emp_title, e.status, u.photo
        FROM org_nodes o LEFT JOIN employees e ON e.id = o.employee_id LEFT JOIN users u ON u.id = e.user_id
        ORDER BY o.sort, o.id'''))
    by_parent = {}
    for r in rows:
        r['name'] = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or '(personel seçilmedi)'
        r['children'] = []
        by_parent.setdefault(r['parent_id'], []).append(r)
    def build(pid):
        out = []
        for r in by_parent.get(pid, []):
            r['children'] = build(r['id'])
            out.append(r)
        return out
    return build(None)


class OrgNodeIn(BaseModel):
    parent_id: Optional[int] = None
    employee_id: Optional[int] = None
    title: Optional[str] = None


@router.get('/org')
def org_chart(user=Depends(hr_user), conn=db.DB):
    return {'tree': _org_tree(conn)}


@router.post('/org')
def org_add(body: OrgNodeIn, user=Depends(hr_user), conn=db.DB):
    if body.parent_id is not None and not conn.execute('SELECT 1 FROM org_nodes WHERE id = ?', (body.parent_id,)).fetchone():
        raise HTTPException(404, 'Üst kart bulunamadı')
    if body.parent_id is None and conn.execute('SELECT 1 FROM org_nodes WHERE parent_id IS NULL').fetchone():
        raise HTTPException(400, 'Şemada zaten bir en üst kart var')
    top = conn.execute('SELECT COALESCE(MAX(sort), 0) + 1 FROM org_nodes WHERE parent_id IS ?', (body.parent_id,)).fetchone()[0]
    cur = conn.execute('INSERT INTO org_nodes (parent_id, employee_id, title, sort, created_at) VALUES (?,?,?,?,?)',
                       (body.parent_id, body.employee_id, (body.title or '').strip()[:120] or None, top, db.now()))
    db.audit(conn, user['id'], 'Organizasyon şemasına kart ekledi', 'employee', body.employee_id, None)
    return {'id': cur.lastrowid, 'tree': _org_tree(conn)}


@router.put('/org/{nid}')
def org_edit(nid: int, body: OrgNodeIn, user=Depends(hr_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM org_nodes WHERE id = ?', (nid,)).fetchone():
        raise HTTPException(404, 'Kart bulunamadı')
    conn.execute('UPDATE org_nodes SET employee_id = ?, title = ? WHERE id = ?',
                 (body.employee_id, (body.title or '').strip()[:120] or None, nid))
    return {'tree': _org_tree(conn)}


@router.delete('/org/{nid}')
def org_delete(nid: int, user=Depends(hr_user), conn=db.DB):
    if not conn.execute('SELECT 1 FROM org_nodes WHERE id = ?', (nid,)).fetchone():
        raise HTTPException(404, 'Kart bulunamadı')
    conn.execute('DELETE FROM org_nodes WHERE id = ?', (nid,))   # alt kartlar CASCADE ile silinir
    db.audit(conn, user['id'], 'Organizasyon şemasından kart sildi', 'employee', None, None)
    return {'tree': _org_tree(conn)}
