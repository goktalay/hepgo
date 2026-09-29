import sqlite3
from datetime import datetime

from fastapi import Depends, HTTPException

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    phone         TEXT,
    photo         TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    last_seen     TEXT,
    prefs         TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role    TEXT NOT NULL,
    PRIMARY KEY (user_id, role)
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_logs (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username   TEXT NOT NULL,
    success    INTEGER NOT NULL,
    ip         TEXT,
    user_agent TEXT,
    at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id        INTEGER PRIMARY KEY,
    user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action    TEXT NOT NULL,
    entity    TEXT,
    entity_id TEXT,
    detail    TEXT,
    at        TEXT NOT NULL
);

-- Ürün tipleri. schema: app/catalogs.py'deki parça şeması anahtarı
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    serial       TEXT NOT NULL UNIQUE,
    description  TEXT,
    schema       TEXT NOT NULL,
    queue_prefix TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

-- Yedek parça kullanımı: mamul (parent) başına kullanılan yedek parça adedi (ör. CAYMAZ başına 68 BBK)
CREATE TABLE IF NOT EXISTS product_spares (
    parent_id INTEGER NOT NULL REFERENCES products(id),
    spare_id  INTEGER NOT NULL REFERENCES products(id),
    qty       INTEGER NOT NULL,
    PRIMARY KEY (parent_id, spare_id)
);
-- Yedek parça stok hareketleri: üretim (+), montaj (−), başlangıç / sayım düzeltmesi (±); stok = toplam
CREATE TABLE IF NOT EXISTS spare_moves (
    id         INTEGER PRIMARY KEY,
    spare_id   INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    order_id   INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    start_date   TEXT,
    end_date     TEXT,
    note         TEXT,
    status       TEXT NOT NULL DEFAULT 'SIPARIS',
    queue_no     TEXT UNIQUE,
    completed_at TEXT,
    completed_by INTEGER REFERENCES users(id),
    product_id   INTEGER REFERENCES products(id)
);
-- Bir siparişteki her parça (plane.py kataloğundan). state:
-- BEKLIYOR | URETIMDE | DEPO | MONTAJ | HATA
CREATE TABLE IF NOT EXISTS order_parts (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    part_id      TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'BEKLIYOR',
    printer_id   INTEGER REFERENCES printers(id) ON DELETE SET NULL,
    started_at   TEXT,
    finished_at  TEXT,
    delivered_to INTEGER REFERENCES users(id),
    approved_by  INTEGER REFERENCES users(id),
    approved_at  TEXT,
    updated_at   TEXT NOT NULL,
    UNIQUE (order_id, part_id)
);
CREATE TABLE IF NOT EXISTS part_events (
    id            INTEGER PRIMARY KEY,
    order_part_id INTEGER NOT NULL REFERENCES order_parts(id) ON DELETE CASCADE,
    event         TEXT NOT NULL,
    user_id       INTEGER REFERENCES users(id),
    printer_id    INTEGER REFERENCES printers(id) ON DELETE SET NULL,
    target_user   INTEGER REFERENCES users(id),
    error_code    TEXT,
    note          TEXT,
    photo         TEXT,
    at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS printers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    ip              TEXT NOT NULL UNIQUE,
    model           TEXT,
    auto_added      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    current_part_id INTEGER REFERENCES order_parts(id) ON DELETE SET NULL,
    last_job        TEXT,
    last_job_start  TEXT,
    last_job_end    TEXT,
    live_state      TEXT,
    live_progress   REAL,
    live_file       TEXT,
    live_source     TEXT,
    last_seen       TEXT
);

-- Saha görevleri. status:
-- BASLANGIC | GOREVDE | GOREV_TAMAMLANDI | BASARISIZ | RAPOR_TAMAMLANDI | IPTAL
CREATE TABLE IF NOT EXISTS field_tasks (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    lead_id     INTEGER REFERENCES users(id),               -- saha sorumlusu
    driver_id   INTEGER REFERENCES users(id),
    status      TEXT NOT NULL DEFAULT 'BASLANGIC',
    result      TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    report_at   TEXT,
    note        TEXT,
    location_id INTEGER REFERENCES field_locations(id),     -- yol yönetimi
    vehicle_id  INTEGER REFERENCES field_vehicles(id),
    start_km    REAL,
    end_km      REAL,
    road_note   TEXT
);
-- Görevdeki her uçak (sipariş) için bir uçuş. launch: ARAC_USTU | RAMPA
CREATE TABLE IF NOT EXISTS field_flights (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    launch     TEXT,
    note       TEXT,
    updated_at TEXT,
    UNIQUE (task_id, order_id)
);
-- Uçuş videoları (parça parça yüklenir; boyut sınırı yok)
CREATE TABLE IF NOT EXISTS flight_videos (
    id          INTEGER PRIMARY KEY,
    flight_id   INTEGER NOT NULL REFERENCES field_flights(id) ON DELETE CASCADE,
    file        TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    size        INTEGER NOT NULL,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_expenses (
    id          INTEGER PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
    spent_on    TEXT NOT NULL,
    category    TEXT NOT NULL,
    description TEXT,
    amount      REAL NOT NULL,
    receipt     TEXT,
    spent_by    INTEGER REFERENCES users(id),               -- masrafı yapan personel
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_vehicles (
    id          INTEGER PRIMARY KEY,
    plate       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_locations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
-- Göreve giden araçlar (birden fazla olabilir): her aracın şoförü ve km'leri ayrı
CREATE TABLE IF NOT EXISTS field_task_vehicles (
    id          INTEGER PRIMARY KEY,
    task_id     INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
    vehicle_id  INTEGER NOT NULL REFERENCES field_vehicles(id),
    driver_id   INTEGER REFERENCES users(id),
    start_km    REAL,
    end_km      REAL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (task_id, vehicle_id)
);
CREATE TABLE IF NOT EXISTS field_task_staff (
    task_id INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (task_id, user_id)
);

-- Montaj ve sonrası (sipariş başına adım): SOL_KANAT | SAG_KANAT | GOVDE (montaj bölümleri),
-- KALIBRASYON (checklist JSON), SAHA_DEPO (depocunun saha deposu onayı). at: kullanıcının seçtiği zaman.
CREATE TABLE IF NOT EXISTS assembly_steps (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    step        TEXT NOT NULL,
    at          TEXT NOT NULL,
    checklist   TEXT,
    note        TEXT,
    recorded_by INTEGER REFERENCES users(id),
    recorded_at TEXT NOT NULL,
    UNIQUE (order_id, step)
);
-- Adımda çalışan montaj personeli
CREATE TABLE IF NOT EXISTS assembly_staff (
    step_id INTEGER NOT NULL REFERENCES assembly_steps(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (step_id, user_id)
);

-- Firma Yönetimi: firmalar, logoları ve firmada çalışan / ilişkili kişiler (sistem kullanıcısı değil)
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tax_office  TEXT,
    tax_no      TEXT,
    phone       TEXT,
    email       TEXT,
    website     TEXT,
    address     TEXT,
    note        TEXT,
    logo        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
-- Firmanın adresleri (birden fazla: merkez, fabrika, şube…); toplantıda seçilir
CREATE TABLE IF NOT EXISTS company_addresses (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    address     TEXT NOT NULL,
    city        TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_people (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    title       TEXT,
    phone       TEXT,
    email       TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
-- Firma toplantıları: karşı taraftan (firma kişileri) ve bizden (sistem kullanıcıları) katılanlar
CREATE TABLE IF NOT EXISTS company_meetings (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    subject          TEXT NOT NULL,
    meeting_at       TEXT NOT NULL,
    location         TEXT,
    notes            TEXT,
    other_attendees  TEXT,
    created_by       INTEGER REFERENCES users(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT
);
CREATE TABLE IF NOT EXISTS meeting_people (
    meeting_id INTEGER NOT NULL REFERENCES company_meetings(id) ON DELETE CASCADE,
    person_id  INTEGER NOT NULL REFERENCES company_people(id) ON DELETE CASCADE,
    PRIMARY KEY (meeting_id, person_id)
);
CREATE TABLE IF NOT EXISTS meeting_users (
    meeting_id INTEGER NOT NULL REFERENCES company_meetings(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (meeting_id, user_id)
);
-- Evrak Yönetimi: taranmış evrak, resim, video ve diğer dosyalar. kind: EVRAK | RESIM | VIDEO | DIGER
-- ocr_status: BEKLIYOR | ISLENIYOR | TAMAM | HATA | YOK (metin çıkarılmayan tür). visibility: ALL | ROLES
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    file        TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    size        INTEGER NOT NULL,
    thumb       TEXT,
    pages       INTEGER,
    doc_date    TEXT,
    note        TEXT,
    ocr_status  TEXT NOT NULL DEFAULT 'BEKLIYOR',
    ocr_text    TEXT,
    ocr_error   TEXT,
    visibility  TEXT NOT NULL DEFAULT 'ALL',
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS document_roles (       -- visibility = ROLES iken evrakı görebilen roller
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    PRIMARY KEY (document_id, role)
);
CREATE TABLE IF NOT EXISTS document_companies (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, company_id)
);
CREATE TABLE IF NOT EXISTS document_people (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    person_id   INTEGER NOT NULL REFERENCES company_people(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, person_id)
);
-- Evrak imza talepleri (şirket içi dijital imza). status: BEKLIYOR | IMZALANDI | REDDEDILDI | IPTAL
-- İmzada dosyanın SHA-256 özeti ve sunucu anahtarıyla HMAC imzası saklanır (dosya değişirse doğrulama bozulur).
CREATE TABLE IF NOT EXISTS document_signatures (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    signer_id    INTEGER NOT NULL REFERENCES users(id),
    requested_by INTEGER REFERENCES users(id),
    requested_at TEXT NOT NULL,
    message      TEXT,
    status       TEXT NOT NULL DEFAULT 'BEKLIYOR',
    decided_at   TEXT,
    reason       TEXT,
    file_sha256  TEXT,
    signature    TEXT
);
CREATE INDEX IF NOT EXISTS ix_sign_signer ON document_signatures(signer_id, status);
-- Video evraklarında bulunan kişiler: yüz grubu (en net yüz kırpığı + 128 boyutlu SFace yüz izi). Kullanıcı yüzü bir firma
-- kişisine (person_id) ya da personele (user_id) bağlar; auto = 1: bilinen yüze benzerlikten otomatik önerildi.
-- added_link = 1: firma kişisi bu bağlama ile evrağın kişilerine eklendi (bağlama kalkarsa kaldırılır).
CREATE TABLE IF NOT EXISTS document_faces (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    crop        TEXT NOT NULL,
    embedding   BLOB NOT NULL,
    samples     INTEGER NOT NULL DEFAULT 1,
    first_at    REAL,
    person_id   INTEGER REFERENCES company_people(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id),
    auto        INTEGER NOT NULL DEFAULT 0,
    added_link  INTEGER NOT NULL DEFAULT 0,
    assigned_by INTEGER REFERENCES users(id),
    assigned_at TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_document_faces_doc ON document_faces(document_id);
-- Yazıcı olayları: KAYITSIZ_IPTAL — sistemde üretime başlatılmamış bir baskı yarıda kesildi (iptal / hata).
-- Biri "Gördüm" diyene kadar Uyarılar'da kritik uyarıdır.
CREATE TABLE IF NOT EXISTS printer_incidents (
    id         INTEGER PRIMARY KEY,
    printer_id INTEGER REFERENCES printers(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    file       TEXT,
    progress   REAL,
    end_state  TEXT,
    started_at TEXT,
    ended_at   TEXT NOT NULL,
    ack_by     INTEGER REFERENCES users(id),
    ack_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_printer_incidents_open ON printer_incidents(ack_at);
-- Uçuş notları (uçuş detayı): pilot ve saha ekibi uçuş hakkında türüyle birden çok not ekler.
-- kind: GORUS | IYILESTIRME | ARIZA | GOZLEM | DIGER
CREATE TABLE IF NOT EXISTS flight_notes (
    id         INTEGER PRIMARY KEY,
    flight_id  INTEGER NOT NULL REFERENCES field_flights(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_flight_notes_flight ON flight_notes(flight_id);
-- Notlar ve takvim (Firma Yönetimi): konu = firma (company), firma kişisi (person) ya da sistem kullanıcısı (user)
CREATE TABLE IF NOT EXISTS crm_notes (
    id           INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id   INTEGER NOT NULL,
    body         TEXT NOT NULL,
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_crm_notes_subject ON crm_notes(subject_type, subject_id);
-- kind: RANDEVU (başlangıç–bitiş) | HATIRLATMA (tek an; "tamamlandı" işaretlenir)
CREATE TABLE IF NOT EXISTS crm_events (
    id           INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id   INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    starts_at    TEXT NOT NULL,
    ends_at      TEXT,
    location     TEXT,
    note         TEXT,
    done_at      TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_crm_events_subject ON crm_events(subject_type, subject_id, starts_at);
CREATE INDEX IF NOT EXISTS ix_crm_events_time ON crm_events(starts_at);
-- Etkinliğe katılan / hatırlatılacak kullanıcılar (bildirim bunlara ve oluşturana gider)
CREATE TABLE IF NOT EXISTS crm_event_users (
    event_id INTEGER NOT NULL REFERENCES crm_events(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (event_id, user_id)
);
-- Evrak arama dizini: başlık, not ve OCR metninin Türkçe harfleri sadeleştirilmiş hali (rowid = documents.id)
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(title, body, tokenize = 'unicode61 remove_diacritics 2');

-- ArduPilot uçuş logu ve analiz sonucu (saha görevine bağlı ya da bağımsız). status: ISLENIYOR | TAMAM | HATA
CREATE TABLE IF NOT EXISTS flight_logs (
    id          INTEGER PRIMARY KEY,
    task_id     INTEGER REFERENCES field_tasks(id) ON DELETE CASCADE,   -- NULL: Araçlar modülünden bağımsız analiz
    file        TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    size        INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ISLENIYOR',
    error       TEXT,
    analysis    TEXT,
    aircraft    TEXT,
    pilot       TEXT,
    location    TEXT,
    note        TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL,
    analyzed_at TEXT,
    flight_id   INTEGER REFERENCES field_flights(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_flight_logs_task ON flight_logs(task_id);

CREATE INDEX IF NOT EXISTS ix_order_parts_order ON order_parts(order_id);
CREATE INDEX IF NOT EXISTS ix_part_events_part ON part_events(order_part_id);
CREATE INDEX IF NOT EXISTS ix_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_login_user ON login_logs(user_id);

-- Güvenlik: fabrikaya gelen araçlar (plaka); çıkış yapmamış olanlar parkta
CREATE TABLE IF NOT EXISTS vehicle_visits (
    id          INTEGER PRIMARY KEY,
    plate       TEXT NOT NULL,
    note        TEXT,
    entered_at  TEXT NOT NULL,
    entered_by  INTEGER REFERENCES users(id),
    exited_at   TEXT,
    exited_by   INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_vehicle_visits_open ON vehicle_visits(exited_at);
-- Sekreterya: misafir kaydı (bir grup = bir kayıt); gelen kişiler, gelen araçlar, görüşülecek kişiler
CREATE TABLE IF NOT EXISTS guest_visits (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    purpose     TEXT,
    note        TEXT,
    arrived_at  TEXT NOT NULL,
    left_at     TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guest_visit_people (
    id           INTEGER PRIMARY KEY,
    visit_id     INTEGER NOT NULL REFERENCES guest_visits(id) ON DELETE CASCADE,
    person_id    INTEGER REFERENCES company_people(id) ON DELETE SET NULL,
    full_name    TEXT NOT NULL,
    company_text TEXT,
    title        TEXT,
    phone        TEXT
);
CREATE TABLE IF NOT EXISTS guest_visit_vehicles (
    visit_id    INTEGER NOT NULL REFERENCES guest_visits(id) ON DELETE CASCADE,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicle_visits(id) ON DELETE CASCADE,
    PRIMARY KEY (visit_id, vehicle_id)
);
CREATE TABLE IF NOT EXISTS guest_visit_hosts (
    visit_id    INTEGER NOT NULL REFERENCES guest_visits(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    added_at    TEXT NOT NULL,
    PRIMARY KEY (visit_id, user_id)
);
-- Sekreterya: gelen kargolar; ilgili kullanıcı teslim alana kadar bekler
CREATE TABLE IF NOT EXISTS cargo (
    id           INTEGER PRIMARY KEY,
    carrier      TEXT,
    tracking_no  TEXT,
    description  TEXT,
    photo        TEXT,
    recipient_id INTEGER NOT NULL REFERENCES users(id),
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    delivered_at TEXT,
    delivered_by INTEGER REFERENCES users(id)
);

-- Güvenilir cihazlar: şifreyle giriş yapılan cihaza verilen jeton (özeti saklanır). Bu cihazda hesap listesi ve PIN ile giriş için.
CREATE TABLE IF NOT EXISTS trusted_devices (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    last_used  TEXT
);

-- Kullanıcılar arası canlı mesajlaşma (birebir). Dosya: uploads/chat; kind: image | audio | file
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY,
    from_id    INTEGER NOT NULL REFERENCES users(id),
    to_id      INTEGER NOT NULL REFERENCES users(id),
    body       TEXT,
    file       TEXT,
    file_name  TEXT,
    file_kind  TEXT,
    file_size  INTEGER,
    duration   REAL,
    created_at TEXT NOT NULL,
    read_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_chat_pair ON chat_messages(from_id, to_id, id);
CREATE INDEX IF NOT EXISTS ix_chat_unread ON chat_messages(to_id, read_at);

-- Sekreterya → Aramalar: şirkete dışarıdan gelen telefonlar. İlgili kullanıcıya bağlanır; kullanıcı tamamlayana kadar
-- (geri döndü / okudu) Aramalarım'da bekler. Notlar hem sekreterya hem ilgili kullanıcı tarafından eklenir.
CREATE TABLE IF NOT EXISTS phone_calls (
    id           INTEGER PRIMARY KEY,
    caller_name  TEXT NOT NULL,
    caller_phone TEXT,
    caller_company TEXT,
    person_id    INTEGER REFERENCES company_people(id) ON DELETE SET NULL,
    subject      TEXT,
    note         TEXT,
    result       TEXT NOT NULL DEFAULT 'MESAJ',
    callback     INTEGER NOT NULL DEFAULT 0,
    target_id    INTEGER REFERENCES users(id),
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    seen_at      TEXT,
    done_at      TEXT,
    done_by      INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_phone_calls_target ON phone_calls(target_id, done_at);
CREATE TABLE IF NOT EXISTS phone_call_notes (
    id         INTEGER PRIMARY KEY,
    call_id    INTEGER NOT NULL REFERENCES phone_calls(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id),
    body       TEXT NOT NULL,
    at         TEXT NOT NULL
);

-- Güvenlik → Kameralar (ONVIF). Şifre şifrelenmiş saklanır (cameras.py), API'den dönmez.
CREATE TABLE IF NOT EXISTS cameras (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    ip           TEXT,
    port         INTEGER,
    username     TEXT,
    password_enc TEXT,
    xaddr        TEXT,
    stream_url   TEXT,
    manufacturer TEXT,
    model        TEXT,
    location     TEXT,
    faces        INTEGER NOT NULL DEFAULT 1,
    active       INTEGER NOT NULL DEFAULT 1,
    auto_added   INTEGER NOT NULL DEFAULT 0,
    status       TEXT,
    error        TEXT,
    last_frame_at TEXT,
    created_at   TEXT NOT NULL
);
-- Kameralarda görülen yüzler: benzer yüzler bir grupta toplanır; grup kişiye (kullanıcı ya da firma kişisi) atanabilir
CREATE TABLE IF NOT EXISTS face_groups (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER REFERENCES company_people(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id),
    centroid    BLOB NOT NULL,
    samples     INTEGER NOT NULL DEFAULT 0,
    best_crop   TEXT,
    best_score  REAL NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    last_camera INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    assigned_by INTEGER REFERENCES users(id),
    assigned_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_face_groups_seen ON face_groups(last_seen);
-- Görülme: yüz kırpığı ve yüzün görüldüğü anın tam karesi
CREATE TABLE IF NOT EXISTS face_sightings (
    id        INTEGER PRIMARY KEY,
    group_id  INTEGER NOT NULL REFERENCES face_groups(id) ON DELETE CASCADE,
    camera_id INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    at        TEXT NOT NULL,
    crop      TEXT NOT NULL,
    frame     TEXT NOT NULL,
    embedding BLOB NOT NULL,
    score     REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_face_sightings_group ON face_sightings(group_id, at);
CREATE INDEX IF NOT EXISTS ix_face_sightings_at ON face_sightings(at);
-- Kullanıcı tercihleri (sunucuda; ör. kamera izleme düzeni)
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key      TEXT NOT NULL,
    value    TEXT,
    PRIMARY KEY (user_id, key)
);

-- Duyurular: yalnızca Sistem Yöneticisi yazar, herkes okur; okuyan kullanıcı kaydedilir (kimin okuduğu görülür)
CREATE TABLE IF NOT EXISTS announcements (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    level      TEXT NOT NULL DEFAULT 'BILGI',     -- BILGI | ONEMLI | KRITIK
    pinned     INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS announcement_reads (
    announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at         TEXT NOT NULL,
    PRIMARY KEY (announcement_id, user_id)
);
"""


def now():
    return datetime.now().isoformat(timespec='seconds')


def pick_time(value, not_before=None, what='Zaman', after_what='önceki işlem'):
    """Kullanıcının seçtiği işlem zamanı (boşsa şimdi); tarih ve saat serbestçe seçilir. Saat dilimi bilgisi
    gelirse sunucunun yerel saatine çevrilir. Yalnızca bir önceki işlemden önceki zaman reddedilir."""
    if not value:
        return now()
    try:
        t = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(400, f'{what} geçersiz') from None
    if t.tzinfo:
        t = t.astimezone().replace(tzinfo=None)
    if not_before and t < datetime.fromisoformat(not_before).replace(second=0):
        raise HTTPException(400, f'{what}, {after_what} zamanından ({_fmt(not_before)}) önce olamaz')
    return t.isoformat(timespec='seconds')


def _fmt(iso):
    return datetime.fromisoformat(iso).strftime('%d.%m.%Y %H:%M')


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn


def init():
    with connect() as conn:
        _migrate_field_tasks(conn)
        conn.executescript(SCHEMA)
        _rebuild_field_flights(conn)
        _migrate(conn)


def _migrate_field_tasks(conn):
    """Tek uçaklı eski saha görevi tablosunu (order_id sütunlu) çok uçaklı yapıya taşır."""
    cols = [r[1] for r in conn.execute('PRAGMA table_info(field_tasks)')]
    if 'order_id' not in cols:
        return
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.execute('PRAGMA legacy_alter_table = ON')   # personel tablosunun referansı eski ada kaymasın
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS field_flights (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, order_id INTEGER NOT NULL,
            launch TEXT, note TEXT, updated_at TEXT, UNIQUE (task_id, order_id));
        INSERT OR IGNORE INTO field_flights (task_id, order_id) SELECT id, order_id FROM field_tasks;
        ALTER TABLE field_tasks RENAME TO field_tasks_old;
    ''')
    conn.executescript(SCHEMA)
    conn.execute('''INSERT INTO field_tasks (id, code, driver_id, status, result, created_by, created_at, started_at,
                                             finished_at, report_at, note)
                    SELECT id, code, driver_id, status, result, created_by, created_at, started_at, finished_at,
                           report_at, note FROM field_tasks_old''')
    conn.execute('DROP TABLE field_tasks_old')
    conn.commit()
    conn.execute('PRAGMA legacy_alter_table = OFF')
    conn.execute('PRAGMA foreign_keys = ON')


def _rebuild_field_flights(conn):
    """Eski geçişte yabancı anahtarsız oluşan field_flights tablosunu şemadaki tanımla yeniden kurar
    (görev silinince uçuşları da silinsin). Görevi olmayan artık uçuş kayıtları temizlenir."""
    if conn.execute("SELECT COUNT(*) FROM pragma_foreign_key_list('field_flights')").fetchone()[0]:
        return
    conn.commit()
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.execute('PRAGMA legacy_alter_table = ON')   # flight_logs / flight_videos referansları eski ada kaymasın
    conn.executescript('''
        DELETE FROM field_flights WHERE task_id NOT IN (SELECT id FROM field_tasks);
        ALTER TABLE field_flights RENAME TO field_flights_old;
        CREATE TABLE field_flights (
            id         INTEGER PRIMARY KEY,
            task_id    INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
            order_id   INTEGER NOT NULL REFERENCES orders(id),
            launch     TEXT,
            note       TEXT,
            updated_at TEXT,
            UNIQUE (task_id, order_id)
        );
        INSERT INTO field_flights (id, task_id, order_id, launch, note, updated_at)
            SELECT id, task_id, order_id, launch, note, updated_at FROM field_flights_old;
        DROP TABLE field_flights_old;
    ''')
    conn.execute('PRAGMA legacy_alter_table = OFF')
    conn.execute('PRAGMA foreign_keys = ON')


def _migrate(conn):
    """Eski veritabanlarını güncel şemaya taşır (ürünlerden önce açılmış siparişler CAYMAZ'a bağlanır)."""
    user_cols = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    if 'last_seen' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN last_seen TEXT')
    if 'prefs' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN prefs TEXT')
    if 'deleted_at' not in user_cols:   # silinen ama geçmiş kayıtlarda adı geçen kullanıcılar
        conn.execute('ALTER TABLE users ADD COLUMN deleted_at TEXT')
    if 'pin_hash' not in user_cols:     # 4 haneli giriş PIN'i (Ayarlar → Hesap)
        conn.execute('ALTER TABLE users ADD COLUMN pin_hash TEXT')
    cols = {r[1] for r in conn.execute('PRAGMA table_info(orders)')}
    if 'product_id' not in cols:
        conn.execute('ALTER TABLE orders ADD COLUMN product_id INTEGER REFERENCES products(id)')
    if not conn.execute('SELECT 1 FROM products').fetchone():
        conn.execute(
            '''INSERT INTO products (code, name, serial, description, schema, queue_prefix, created_at)
               VALUES (?,?,?,?,?,?,?)''',
            ('CYZ', 'CAYMAZ', 'CYZ-S1', 'CAYMAZ insansız uçak – delta kanat, elevonlu', 'caymaz', 'CYZ', now()))
    task_cols = {r[1] for r in conn.execute('PRAGMA table_info(field_tasks)')}
    if 'vehicle_id' not in task_cols:
        conn.execute('ALTER TABLE field_tasks ADD COLUMN vehicle_id INTEGER REFERENCES field_vehicles(id)')
    # Firma: tek adres alanı → adresler tablosu; toplantıda seçilen adres
    conn.execute('''INSERT INTO company_addresses (company_id, label, address, created_at)
                    SELECT id, 'Merkez', address, created_at FROM companies WHERE address IS NOT NULL AND address != ''
                    AND id NOT IN (SELECT company_id FROM company_addresses)''')
    conn.execute("UPDATE companies SET address = NULL WHERE address IS NOT NULL")
    if 'address_id' not in {r[1] for r in conn.execute('PRAGMA table_info(company_meetings)')}:
        conn.execute('ALTER TABLE company_meetings ADD COLUMN address_id INTEGER REFERENCES company_addresses(id)')
    if 'spent_by' not in {r[1] for r in conn.execute('PRAGMA table_info(field_expenses)')}:   # masrafı yapan
        conn.execute('ALTER TABLE field_expenses ADD COLUMN spent_by INTEGER REFERENCES users(id)')
        conn.execute('UPDATE field_expenses SET spent_by = created_by')
    if 'pilot_id' not in task_cols:   # görevin pilotu
        conn.execute('ALTER TABLE field_tasks ADD COLUMN pilot_id INTEGER REFERENCES users(id)')
    # Tek araçlı eski yol kaydı (field_tasks.vehicle_id/start_km/end_km) araç tablosuna taşınır
    conn.execute('''INSERT OR IGNORE INTO field_task_vehicles (task_id, vehicle_id, driver_id, start_km, end_km, created_at)
                    SELECT id, vehicle_id, driver_id, start_km, end_km, created_at FROM field_tasks
                    WHERE vehicle_id IS NOT NULL''')
    conn.execute('UPDATE field_tasks SET vehicle_id = NULL, start_km = NULL, end_km = NULL WHERE vehicle_id IS NOT NULL')
    if 'flight_id' not in {r[1] for r in conn.execute('PRAGMA table_info(flight_logs)')}:
        conn.execute('ALTER TABLE flight_logs ADD COLUMN flight_id INTEGER REFERENCES field_flights(id) ON DELETE SET NULL')
        conn.execute('''UPDATE flight_logs SET flight_id = (SELECT f.id FROM field_flights f WHERE f.task_id = flight_logs.task_id
                        ORDER BY f.id LIMIT 1) WHERE task_id IS NOT NULL''')
    prod_cols = {r[1] for r in conn.execute('PRAGMA table_info(products)')}
    if 'type' not in prod_cols:   # MAMUL | YEDEK_PARCA | YARI_MAMUL
        conn.execute("ALTER TABLE products ADD COLUMN type TEXT NOT NULL DEFAULT 'MAMUL'")
    if 'per_print' not in prod_cols:   # bir baskıda (siparişte) üretilen adet
        conn.execute('ALTER TABLE products ADD COLUMN per_print INTEGER NOT NULL DEFAULT 1')
    if 'kind' not in {r[1] for r in conn.execute('PRAGMA table_info(flight_videos)')}:   # VIDEO | RESIM
        conn.execute("ALTER TABLE flight_videos ADD COLUMN kind TEXT NOT NULL DEFAULT 'VIDEO'")
    if 'duration' not in {r[1] for r in conn.execute('PRAGMA table_info(documents)')}:   # ses / video süresi (sn)
        conn.execute('ALTER TABLE documents ADD COLUMN duration REAL')
    op_cols = {r[1] for r in conn.execute('PRAGMA table_info(order_parts)')}
    if 'printer_started_at' not in op_cols:   # yazıcının bu parçayı basmaya başladığı / "tamamlandı" dediği an
        conn.execute('ALTER TABLE order_parts ADD COLUMN printer_started_at TEXT')
        conn.execute('ALTER TABLE order_parts ADD COLUMN printer_done_at TEXT')
    if 'orderable' not in prod_cols:   # sipariş verilebilir mi (yarı mamuller hiçbir zaman)
        conn.execute('ALTER TABLE products ADD COLUMN orderable INTEGER NOT NULL DEFAULT 1')
    if 'live_since' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:   # yazıcının şu anki durumuna geçtiği an
        conn.execute('ALTER TABLE printers ADD COLUMN live_since TEXT')
    if 'rack_side' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:   # yazıcı odasındaki yeri (3B görünüm)
        conn.execute('ALTER TABLE printers ADD COLUMN rack_side TEXT')      # L sol / R sağ
        conn.execute('ALTER TABLE printers ADD COLUMN rack_level INTEGER')  # 1 alt / 2 üst kat
        conn.execute('ALTER TABLE printers ADD COLUMN rack_slot INTEGER')   # 1 = girişe en yakın
    from . import printer_layout
    printer_layout.assign_missing(conn)
    from .production import assign_queue_no   # montajı bitmiş, kuyruk numarası olmayan uçaklar (kalibrasyona geçişte atanır)
    for (oid,) in conn.execute('''SELECT o.id FROM orders o JOIN products p ON p.id = o.product_id WHERE p.type = 'MAMUL'
                                  AND o.queue_no IS NULL AND o.status IN ('KALIBRASYON', 'SAHA_ONAY', 'TAMAMLANDI') ORDER BY o.id''').fetchall():
        assign_queue_no(conn, oid)
    if 'live_print_s' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:   # yazıcının bildirdiği net baskı süresi (sn)
        conn.execute('ALTER TABLE printers ADD COLUMN live_print_s REAL')
    if 'print_seconds' not in {r[1] for r in conn.execute('PRAGMA table_info(order_parts)')}:   # parçanın net baskı süresi (duraklamalar hariç)
        conn.execute('ALTER TABLE order_parts ADD COLUMN print_seconds INTEGER')
    if 'usage_type' not in prod_cols:   # mamul kullanım durumu: TEK (tek kullanımlık; uçunca hurda) | COKLU
        conn.execute('ALTER TABLE products ADD COLUMN usage_type TEXT')
        conn.execute("UPDATE products SET usage_type = 'TEK' WHERE type = 'MAMUL'")   # CAYMAZ, CAYMAZ V2
    order_cols = {r[1] for r in conn.execute('PRAGMA table_info(orders)')}
    if 'company_id' not in order_cols:   # siparişi veren / siparişin yapıldığı firma
        conn.execute('ALTER TABLE orders ADD COLUMN company_id INTEGER REFERENCES companies(id)')
    if 'scrapped_at' not in order_cols:   # HURDA: tek kullanımlık uçak uçtu
        conn.execute('ALTER TABLE orders ADD COLUMN scrapped_at TEXT')
        conn.execute('ALTER TABLE orders ADD COLUMN scrap_reason TEXT')
    if 'print_file' not in prod_cols:   # yazıcıya verilen baskı dosyası (gcode adı) ve baskı süresi (dakika)
        conn.execute('ALTER TABLE products ADD COLUMN print_file TEXT')
        conn.execute('ALTER TABLE products ADD COLUMN print_minutes INTEGER')
        # (bir kez) parça yedekleri mamul siparişiyle üretilir: ayrı sipariş kapalı; açık kalanlar KMH/BBK/KBK
        conn.execute("UPDATE products SET orderable = 0 WHERE schema LIKE 'part-%'")
        conn.execute("UPDATE products SET description = 'CAYMAZ parçası · mamul siparişiyle üretilir' "
                     "WHERE schema LIKE 'part-%' AND description = 'CAYMAZ parçası · yedek olarak basılıp stokta tutulur'")
    if 'parent_id' not in prod_cols:   # yarı mamul: ait olduğu mamul
        conn.execute('ALTER TABLE products ADD COLUMN parent_id INTEGER REFERENCES products(id)')
    from . import semis, spares   # döngüsel içe aktarmayı önlemek için burada
    spares.seed(conn)
    semis.seed(conn)
    conn.execute("UPDATE products SET orderable = 0 WHERE type = 'YARI_MAMUL' AND orderable = 1")
    default = conn.execute('SELECT id FROM products ORDER BY id LIMIT 1').fetchone()[0]
    conn.execute('UPDATE orders SET product_id = ? WHERE product_id IS NULL', (default,))


def get_db():
    """FastAPI bağımlılığı: istek başına bağlantı, hata yoksa commit."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Commit, yanıt istemciye gönderilmeden önce yapılmalı; aksi halde hemen ardından gelen
# istek (ör. girişten sonraki ilk istek) henüz yazılmamış veriyi göremez.
DB = Depends(get_db, scope='function')


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def row(cur):
    r = cur.fetchone()
    return dict(r) if r else None


def audit(conn, user_id, action, entity=None, entity_id=None, detail=None):
    conn.execute(
        'INSERT INTO audit_logs (user_id, action, entity, entity_id, detail, at) VALUES (?,?,?,?,?,?)',
        (user_id, action, entity, None if entity_id is None else str(entity_id), detail, now()))


def next_code(conn, table, column, prefix, width=4):
    """PREFIX-0001 biçiminde sıradaki kodu verir."""
    last = conn.execute(
        f'SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1',
        (f'{prefix}-%',)).fetchone()
    n = int(last[0].rsplit('-', 1)[1]) + 1 if last else 1
    return f'{prefix}-{n:0{width}d}'
