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
-- İnsan Kaynakları (app/routers/hr.py): personel = kullanıcı (user_id) ya da iş başvurusuyla açılan kayıt.
-- Durum: BASVURU (iş başvurusu; personel ve kullanıcı olarak görünmez) | REDDEDILDI | AKTIF | AYRILDI
CREATE TABLE IF NOT EXISTS employees (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    tc_no        TEXT UNIQUE,
    first_name   TEXT NOT NULL,
    last_name    TEXT NOT NULL,
    gender       TEXT,              -- E | K
    birth_date   TEXT,
    phone        TEXT,
    email        TEXT,
    address      TEXT,
    status       TEXT NOT NULL,
    position     TEXT,              -- başvurulan pozisyon
    source       TEXT,              -- başvuru kaynağı (Kariyer.net, Eleman Online, Referans ...)
    source_note  TEXT,
    applied_at   TEXT,
    cv_file      TEXT,
    cv_name      TEXT,
    reject_reason TEXT,
    decided_at   TEXT,
    decided_by   INTEGER REFERENCES users(id),
    title        TEXT,              -- görevi
    department   TEXT,
    salary       REAL,
    start_date   TEXT,              -- resmi işe başlama
    end_date     TEXT,
    end_reason   TEXT,
    note         TEXT,
    created_at   TEXT NOT NULL,
    created_by   INTEGER REFERENCES users(id)
);
-- Personel aile üyeleri (İK › personel detayı › Ailesi). Yüz tanımada eğitilebilir (face_enroll.family_id).
CREATE TABLE IF NOT EXISTS family_members (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    full_name   TEXT NOT NULL,
    relation    TEXT,                -- yakınlık: Eş, Çocuk, Anne, Baba, Kardeş, Diğer
    birth_date  TEXT,
    phone       TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_family_members_emp ON family_members(employee_id);
-- MRP › Depo Yönetimi: depolar ve sorumluları
CREATE TABLE IF NOT EXISTS warehouses (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    code           TEXT UNIQUE,
    location       TEXT,
    responsible_id INTEGER REFERENCES users(id),
    note           TEXT,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);
-- Malzeme alım belgeleri: fatura / irsaliye (dosyasıyla)
CREATE TABLE IF NOT EXISTS material_docs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,      -- FATURA | IRSALIYE
    number      TEXT,
    doc_date    TEXT,
    company_id  INTEGER REFERENCES companies(id),
    supplier    TEXT,
    amount      REAL,
    file        TEXT,
    file_name   TEXT,
    note        TEXT,
    user_id     INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
-- MRP › Malzeme Yönetimi: yedek parça / hammadde stok hareketleri (depo başına; stok = toplam)
-- kind: GIRIS | CIKIS | TRANSFER | SAYIM | KULLANIM (eritme) | HURDA | GERI_KAZANIM; depo yoksa (uçuş hurdası) stoğu etkilemez
CREATE TABLE IF NOT EXISTS material_moves (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    warehouse_id INTEGER REFERENCES warehouses(id),
    kind         TEXT NOT NULL,
    qty          REAL NOT NULL,
    unit_price   REAL,
    reason       TEXT,
    source       TEXT,              -- UCUS: uçuş kaynaklı hurda
    doc_id       INTEGER REFERENCES material_docs(id),
    order_id     INTEGER REFERENCES orders(id),
    group_id     TEXT,              -- transferin iki satırı
    user_id      INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL
);
-- Malzeme resimleri (birden fazla)
CREATE TABLE IF NOT EXISTS material_images (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    file_name   TEXT,
    user_id     INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
-- Satın Alma › Talep Yönetimi: satın alma talepleri (Sistem Yöneticisi onaylar) ve kalemleri
CREATE TABLE IF NOT EXISTS purchase_requests (
    id            INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    note          TEXT,
    needed_by     TEXT,
    status        TEXT NOT NULL DEFAULT 'TASLAK',   -- TASLAK | ONAY_BEKLIYOR | ONAYLANDI | REDDEDILDI | TAMAMLANDI | IPTAL
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL,
    submitted_at  TEXT,
    decided_by    INTEGER REFERENCES users(id),
    decided_at    TEXT,
    decision_note TEXT,
    seen_at       TEXT
);
CREATE TABLE IF NOT EXISTS purchase_request_items (
    id          INTEGER PRIMARY KEY,
    request_id  INTEGER NOT NULL REFERENCES purchase_requests(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    qty         REAL NOT NULL,
    note        TEXT,
    pos         INTEGER NOT NULL DEFAULT 0
);
-- Satın Alma › Teklif Yönetimi: teklifler, kalemleri ve eski revizyonların anlık görüntüsü
CREATE TABLE IF NOT EXISTS quotes (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    company_id  INTEGER REFERENCES companies(id),
    title       TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'TRY',
    vat_rate    REAL NOT NULL DEFAULT 20,
    valid_until TEXT,
    note        TEXT,
    status      TEXT NOT NULL DEFAULT 'TASLAK',   -- TASLAK | GONDERILDI | KABUL | RED
    revision    INTEGER NOT NULL DEFAULT 0,
    request_id  INTEGER REFERENCES purchase_requests(id),
    sent_at     TEXT,
    sent_to     TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS quote_items (
    id          INTEGER PRIMARY KEY,
    quote_id    INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    product_id  INTEGER REFERENCES products(id),
    description TEXT NOT NULL,
    qty         REAL NOT NULL,
    unit        TEXT,
    unit_price  REAL,
    note        TEXT,
    pos         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quote_revisions (
    id          INTEGER PRIMARY KEY,
    quote_id    INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    revision    INTEGER NOT NULL,
    data        TEXT NOT NULL,       -- revizyon anındaki teklif (başlık + kalemler, JSON)
    reason      TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
-- Doğrudan depoya ekleme talepleri: parça basılmış kabul edilip (seçili yazıcıyla) Sistem Yöneticisi onayına gider;
-- onaylanınca parça sanki o yazıcıdan çıkmış gibi DEPO durumuna geçer ve depo onayına düşer.
CREATE TABLE IF NOT EXISTS direct_part_requests (
    id            INTEGER PRIMARY KEY,
    order_part_id INTEGER NOT NULL REFERENCES order_parts(id) ON DELETE CASCADE,
    printer_id    INTEGER REFERENCES printers(id),
    print_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'BEKLIYOR',   -- BEKLIYOR | ONAYLANDI | REDDEDILDI
    requested_by  INTEGER REFERENCES users(id),
    requested_at  TEXT NOT NULL,
    decided_by    INTEGER REFERENCES users(id),
    decided_at    TEXT,
    note          TEXT
);
-- Mikro ERP veri aktarımı: hangi Mikro kaydı (kind=cari|stok, code) hangi yerel kayda (local_id) aktarıldı
CREATE TABLE IF NOT EXISTS mikro_links (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,      -- cari | stok
    mikro_code  TEXT NOT NULL,
    local_id    INTEGER NOT NULL,   -- companies.id (cari) ya da products.id (stok)
    label       TEXT,
    imported_at TEXT NOT NULL,
    updated_at  TEXT,
    UNIQUE (kind, mikro_code)
);
-- Küçük sistem değerleri (ör. son ağ taramasının özeti)
CREATE TABLE IF NOT EXISTS app_kv (
    k TEXT PRIMARY KEY,
    v TEXT
);
-- Şifre geçmişi (Program Ayarları → Güvenlik: son N şifre yeniden kullanılamaz kuralı için)
CREATE TABLE IF NOT EXISTS password_history (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pwhist_user ON password_history(user_id);
-- Yapay zeka asistanı (maskot) token kullanımı: kullanıcı başına aylık kota takibi için
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    ym TEXT NOT NULL,            -- 'YYYY-MM' (aylık toplama)
    model TEXT,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user_ym ON ai_usage(user_id, ym);
-- Yapay zekanın önerdiği kayıt değişiklikleri: sistem yöneticisi onayına düşer, onaylanınca uygulanır, kullanıcı bildirim alır
CREATE TABLE IF NOT EXISTS ai_change_requests (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,          -- kullanıcı diliyle açıklama
    sql TEXT NOT NULL,              -- uygulanacak tek yazma ifadesi
    status TEXT NOT NULL DEFAULT 'BEKLIYOR',   -- BEKLIYOR | ONAYLANDI | RED | HATA
    created_at TEXT NOT NULL,
    decided_by INTEGER REFERENCES users(id),
    decided_at TEXT,
    note TEXT,                      -- yöneticinin notu / hata mesajı
    affected INTEGER,               -- etkilenen satır sayısı
    seen_at TEXT                    -- kullanıcı bildirimi gördü mü
);
CREATE INDEX IF NOT EXISTS idx_ai_change_status ON ai_change_requests(status);
-- Telsiz: bas-konuş kanalları (Program Ayarları → Telsiz). Ses sunucu üzerinden çevrimiçi üyelere canlı aktarılır, saklanmaz.
CREATE TABLE IF NOT EXISTS radio_channels (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    color      TEXT,
    is_company INTEGER NOT NULL DEFAULT 0,   -- 1: sabit "Tüm Şirket" kanalı (herkes üye, silinemez)
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS radio_members (
    channel_id INTEGER NOT NULL REFERENCES radio_channels(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'UYE',   -- DAVET (onay bekliyor) | UYE
    invited_by INTEGER REFERENCES users(id),
    invited_at TEXT,
    PRIMARY KEY (channel_id, user_id)
);
-- Görüntülü online toplantı (Zoom tarzı): davet kodu, bekleme odası, şirket içi/dışı katılımcı
CREATE TABLE IF NOT EXISTS online_meetings (
    id             INTEGER PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    host_id        INTEGER NOT NULL REFERENCES users(id),
    status         TEXT NOT NULL DEFAULT 'PLANLANDI',   -- PLANLANDI | DEVAM | BITTI
    waiting_room   INTEGER NOT NULL DEFAULT 1,
    record         INTEGER NOT NULL DEFAULT 0,
    scheduled_at   TEXT,
    started_at     TEXT,
    ended_at       TEXT,
    created_at     TEXT NOT NULL,
    process_status TEXT, process_error TEXT, processed_at TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS online_meeting_participants (
    id          INTEGER PRIMARY KEY,
    meeting_id  INTEGER NOT NULL REFERENCES online_meetings(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),
    name        TEXT NOT NULL,
    email       TEXT,
    is_external INTEGER NOT NULL DEFAULT 0,
    role        TEXT NOT NULL DEFAULT 'uye',             -- host | uye
    token       TEXT,                                    -- dış katılımcı erişim jetonu
    state       TEXT NOT NULL DEFAULT 'DAVETLI',         -- DAVETLI | BEKLIYOR | KABUL | RED | AYRILDI
    created_at  TEXT NOT NULL,
    joined_at   TEXT, left_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_omp_meeting ON online_meeting_participants(meeting_id);
CREATE TABLE IF NOT EXISTS online_meeting_audio (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES online_meetings(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    speaker_name TEXT,
    file TEXT NOT NULL, wav TEXT, chunks INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL, ended_at TEXT, seconds REAL
);
CREATE TABLE IF NOT EXISTS online_meeting_speakers (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES online_meetings(id) ON DELETE CASCADE,
    label TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
    auto INTEGER NOT NULL DEFAULT 0, score REAL, embedding TEXT, seconds REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS online_meeting_segments (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES online_meetings(id) ON DELETE CASCADE,
    audio_id INTEGER NOT NULL REFERENCES online_meeting_audio(id) ON DELETE CASCADE,
    speaker_id INTEGER REFERENCES online_meeting_speakers(id) ON DELETE SET NULL,
    t0 REAL NOT NULL, t1 REAL NOT NULL, at TEXT, text TEXT NOT NULL
);
-- Toplantı dosya kutusu: katılımcıların paylaştığı dosyalar
CREATE TABLE IF NOT EXISTS online_meeting_files (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES online_meetings(id) ON DELETE CASCADE,
    uploader_pid INTEGER,
    uploader_name TEXT,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_omf_meeting ON online_meeting_files(meeting_id);
-- Temizlik modülü: günlük yapılacak işler çeklisti ve günlük yapıldı kayıtları
CREATE TABLE IF NOT EXISTS cleaning_items (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cleaning_log (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES cleaning_items(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    done_at TEXT,
    done_by INTEGER REFERENCES users(id),
    note TEXT,
    UNIQUE(item_id, day)
);
CREATE INDEX IF NOT EXISTS idx_cleaning_log_day ON cleaning_log(day);
-- Güvenlik › Bina Kontrol: günlük bina turu; başlat/bitir ile GPS rotası kaydedilir
CREATE TABLE IF NOT EXISTS building_checks (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    slot TEXT,
    status TEXT NOT NULL DEFAULT 'DEVAM',
    started_at TEXT,
    finished_at TEXT,
    started_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_bchecks_day ON building_checks(day);
CREATE TABLE IF NOT EXISTS building_check_points (
    id INTEGER PRIMARY KEY,
    check_id INTEGER NOT NULL REFERENCES building_checks(id) ON DELETE CASCADE,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    acc REAL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bpoints_check ON building_check_points(check_id);
-- Bina kontrol turuna düşülen notlar (tespit edilen sorunlar; başlarken/bitince birden çok)
CREATE TABLE IF NOT EXISTS building_check_notes (
    id INTEGER PRIMARY KEY,
    check_id INTEGER NOT NULL REFERENCES building_checks(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bcnotes_check ON building_check_notes(check_id);
-- Endüstriyel Tasarım: projeler, çizim/montaj ağacı (parent_id), her çizimin sürüm geçmişi (dosya + açıklama)
CREATE TABLE IF NOT EXISTS design_projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS design_drawings (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES design_drawings(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'drawing',
    sort INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ddr_project ON design_drawings(project_id);
CREATE INDEX IF NOT EXISTS idx_ddr_parent ON design_drawings(parent_id);
CREATE TABLE IF NOT EXISTS design_drawing_versions (
    id INTEGER PRIMARY KEY,
    drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    file_path TEXT,
    file_name TEXT,
    size INTEGER,
    note TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ddv_drawing ON design_drawing_versions(drawing_id);
-- Her çizime / montaja farklı zamanlarda düşülen notlar
CREATE TABLE IF NOT EXISTS design_drawing_notes (
    id INTEGER PRIMARY KEY,
    drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ddn_drawing ON design_drawing_notes(drawing_id);
-- Montaja üretim aşaması için eklenen parçalar (G-code dosyası + açıklama)
CREATE TABLE IF NOT EXISTS design_production_parts (
    id INTEGER PRIMARY KEY,
    drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    qty REAL,
    unit TEXT,
    note TEXT,
    file_path TEXT,
    file_name TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dpp_drawing ON design_production_parts(drawing_id);
-- Tasarım dosyası silme talepleri: Master dışı kullanıcı silmek isterse Master onayına düşer
CREATE TABLE IF NOT EXISTS design_delete_requests (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    label TEXT,
    project_id INTEGER,
    requested_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'BEKLIYOR'
);
CREATE INDEX IF NOT EXISTS idx_ddreq_status ON design_delete_requests(status);
-- Evrak › Belge Yönetim: uygulama içi ofis belgeleri (Excel/Word/Sunum), paylaşım izni + sürüm geçmişi
CREATE TABLE IF NOT EXISTS office_docs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                 -- excel | word | sunum
    title TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    content TEXT NOT NULL DEFAULT '',   -- JSON (türüne göre: hücreler / zengin metin / slaytlar)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id),
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_office_docs_owner ON office_docs(owner_id);
CREATE TABLE IF NOT EXISTS office_versions (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES office_docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    saved_by INTEGER REFERENCES users(id),
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_office_versions_doc ON office_versions(doc_id);
CREATE TABLE IF NOT EXISTS office_shares (
    doc_id INTEGER NOT NULL REFERENCES office_docs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    perm TEXT NOT NULL DEFAULT 'write',  -- write (varsayılan erişim zaten görüntüleme)
    PRIMARY KEY (doc_id, user_id)
);
-- Araçlar › Ağ Tarayıcı: yerel ağda görülen cihazlar (MAC ile izlenir; MAC yoksa IP)
CREATE TABLE IF NOT EXISTS network_devices (
    id         INTEGER PRIMARY KEY,
    key        TEXT NOT NULL UNIQUE,
    ip         TEXT,
    mac        TEXT,
    vendor     TEXT,
    hostname   TEXT,
    netbios    TEXT,
    mdns       TEXT,
    dns        TEXT,
    workgroup  TEXT,
    ports      TEXT,
    kind       TEXT,
    known      TEXT,
    label      TEXT,               -- yöneticinin verdiği ad (ör. Muhasebe PC)
    note       TEXT,
    is_gateway INTEGER NOT NULL DEFAULT 0,
    is_server  INTEGER NOT NULL DEFAULT 0,
    online     INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
-- Personel adresleri (birden fazla; biri birincil)
CREATE TABLE IF NOT EXISTS employee_addresses (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,        -- Ev, İkametgâh, Tebligat, Acil durum, Diğer
    address     TEXT NOT NULL,
    district    TEXT,
    city        TEXT,
    postal_code TEXT,
    note        TEXT,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
-- Özlük dosyaları ve sözleşmeler (tür başına en son yüklenen geçerlidir)
CREATE TABLE IF NOT EXISTS employee_files (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    path        TEXT NOT NULL,
    file_name   TEXT,
    size        INTEGER,
    note        TEXT,
    uploaded_by INTEGER REFERENCES users(id),
    created_at  TEXT NOT NULL
);
-- Personel geçmişi: başvuru, ret, kabul, görev / maaş değişikliği, ayrılış
CREATE TABLE IF NOT EXISTS employee_events (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
-- İzin talepleri: istenen tarihler (req_*) ve İK'nın onayladığı tarihler (start_date / end_date)
CREATE TABLE IF NOT EXISTS leave_requests (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    requested_by  INTEGER REFERENCES users(id),
    kind          TEXT NOT NULL,     -- UCRETLI | UCRETSIZ
    req_start     TEXT NOT NULL,
    req_end       TEXT NOT NULL,
    reason        TEXT,
    location      TEXT,
    status        TEXT NOT NULL DEFAULT 'BEKLIYOR',   -- BEKLIYOR | ONAYLANDI | REDDEDILDI | IPTAL
    start_date    TEXT,
    end_date      TEXT,
    decided_by    INTEGER REFERENCES users(id),
    decided_at    TEXT,
    decision_note TEXT,
    seen_at       TEXT,               -- talep eden kararı gördü
    created_at    TEXT NOT NULL
);
-- Ürün ağacı: üst ürün (mamul / yarı mamul) → alt yarı mamul ve adedi (iç içe; app/bom.py)
CREATE TABLE IF NOT EXISTS product_bom (
    parent_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    child_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty       REAL NOT NULL DEFAULT 1,
    pos       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (parent_id, child_id)
);
-- Reçete: üründe kullanılan yedek parça / hammadde ve miktarı (hammaddenin birimiyle)
CREATE TABLE IF NOT EXISTS product_recipe (
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    qty        REAL NOT NULL,
    note       TEXT,
    pos        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, item_id)
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
-- Şirket içi toplantılar (Kişisel → Toplantılar): düzenleyen kullanıcıları davet eder; davet bildirim olarak düşer, davetli
-- notla yanıt verir (KATILIYOR / BELKI / KATILMIYOR); toplantıdan remind_min dakika önce hatırlatılır.
CREATE TABLE IF NOT EXISTS team_meetings (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    starts_at    TEXT NOT NULL,
    ends_at      TEXT,
    location     TEXT,
    note         TEXT,
    remind_min   INTEGER NOT NULL DEFAULT 15,
    created_by   INTEGER NOT NULL REFERENCES users(id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT,
    cancelled_at TEXT,
    started_at   TEXT,     -- toplantı ekranı açıldı
    ended_at     TEXT,     -- düzenleyen sonlandırdı
    process_status TEXT,   -- ses işleme: ISLENIYOR | TAMAM | HATA
    process_error  TEXT,
    processed_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_team_meetings_time ON team_meetings(starts_at);
CREATE TABLE IF NOT EXISTS team_meeting_invites (
    meeting_id   INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    status       TEXT NOT NULL DEFAULT 'BEKLIYOR',
    response     TEXT,
    responded_at TEXT,
    invited_at   TEXT NOT NULL,
    joined_at    TEXT,     -- toplantı ekranına ilk girdiği an
    last_seen    TEXT,     -- ekranda (canlı katılım)
    PRIMARY KEY (meeting_id, user_id)
);
-- Toplantı ekranı: kişisel notlar, ses kayıtları, konuşmacı grupları ve konuşma dökümü; ses profilleri (konuşmacı tanıma)
CREATE TABLE IF NOT EXISTS team_meeting_notes (
    meeting_id INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (meeting_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_meeting_audio (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
    file       TEXT NOT NULL,          -- tarayıcı kaydı (webm/ogg), parça parça eklenir
    wav        TEXT,                   -- işlenince 16 kHz WAV
    chunks     INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    seconds    REAL
);
CREATE TABLE IF NOT EXISTS team_meeting_speakers (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,          -- Tanımsız kişi 1…
    user_id    INTEGER REFERENCES users(id),
    auto       INTEGER NOT NULL DEFAULT 0,   -- ses profilinden otomatik tanındı
    score      REAL,
    embedding  TEXT,                   -- ortalama ses kimliği (JSON)
    seconds    REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS team_meeting_segments (
    id         INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES team_meetings(id) ON DELETE CASCADE,
    audio_id   INTEGER NOT NULL REFERENCES team_meeting_audio(id) ON DELETE CASCADE,
    speaker_id INTEGER REFERENCES team_meeting_speakers(id) ON DELETE SET NULL,
    t0         REAL NOT NULL,          -- kayıt içindeki başlangıç (sn)
    t1         REAL NOT NULL,
    at         TEXT,                   -- gerçek zaman
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tm_segments ON team_meeting_segments(meeting_id, at);
CREATE TABLE IF NOT EXISTS voice_profiles (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    embedding  TEXT NOT NULL,          -- birim uzunlukta ortalama ses kimliği (JSON)
    samples    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
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

-- Kişisel → Mail: kullanıcının Gmail hesabı (IMAP/SMTP, uygulama şifresi şifrelenmiş saklanır; API'den dönmez)
CREATE TABLE IF NOT EXISTS mail_accounts (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email      TEXT NOT NULL,
    secret     TEXT NOT NULL,
    name       TEXT,
    signature  TEXT,
    created_at TEXT NOT NULL,
    last_ok    TEXT,
    last_error TEXT,
    auto_import INTEGER NOT NULL DEFAULT 1,   -- gelen eklerini Evrak Yönetimi'ne kaydet
    last_uid   INTEGER,                        -- gelen kutusunda en son taranan UID
    uid_validity TEXT,
    auth_type  TEXT NOT NULL DEFAULT 'password'   -- password: uygulama şifresi · oauth: Google ile bağlan (secret = yenileme jetonu)
);
-- Evraklara aktarılan mail ekleri (aynı ek iki kez aktarılmaz)
CREATE TABLE IF NOT EXISTS mail_imports (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    att_name    TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    at          TEXT NOT NULL,
    PRIMARY KEY (user_id, message_id, att_name)
);

-- Mesajlaşma grupları. is_company = 1: "Tüm Şirket" kanalı (herkes üyedir, yalnızca Sistem Yöneticisi yazar)
CREATE TABLE IF NOT EXISTS chat_groups (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    is_company INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_group_members (
    group_id  INTEGER NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    is_admin  INTEGER NOT NULL DEFAULT 0,       -- grubu kuran / yöneten
    joined_at TEXT NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS chat_group_messages (
    id         INTEGER PRIMARY KEY,
    group_id   INTEGER NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE,
    from_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT,
    file       TEXT,
    file_name  TEXT,
    file_kind  TEXT,
    file_size  INTEGER,
    duration   REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chat_gm ON chat_group_messages(group_id, id);
CREATE TABLE IF NOT EXISTS chat_group_reads (           -- kişinin grupta okuduğu son ileti
    group_id     INTEGER NOT NULL REFERENCES chat_groups(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, user_id)
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
    family_id   INTEGER REFERENCES family_members(id) ON DELETE SET NULL,
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
    score     REAL NOT NULL DEFAULT 0,
    threshold REAL                          -- görülme anında etkin tanıma hassasiyeti (eşik)
);
CREATE INDEX IF NOT EXISTS ix_face_sightings_group ON face_sightings(group_id, at);
CREATE INDEX IF NOT EXISTS ix_face_sightings_at ON face_sightings(at);
-- Yüz tanıma eğitimi: bir kişi için (personel ya da firma personeli) yüklenen eğitim fotoğraflarından çıkarılan yüz izleri.
-- Kameralarda görülen yüzler bu izlerle eşleştirilir. subject_type: 'user' (personel) | 'person' (firma kişisi) | 'visitor'.
CREATE TABLE IF NOT EXISTS face_enroll (
    id           INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    person_id    INTEGER REFERENCES company_people(id) ON DELETE CASCADE,
    family_id    INTEGER REFERENCES family_members(id) ON DELETE CASCADE,
    name         TEXT,                       -- subject_type='visitor' için serbest ad
    crop         TEXT NOT NULL,              -- yüz kırpığı (uploads altında göreli yol)
    embedding    BLOB NOT NULL,
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_face_enroll_user ON face_enroll(user_id);
CREATE INDEX IF NOT EXISTS ix_face_enroll_person ON face_enroll(person_id);
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
-- Faturalar (Satış Yönetimi + Mikro ERP alış/satış aktarımı ortak kullanır).
-- kind: alis (stok giriş) | satis (stok çıkış). source: manual (elle oluşturulan) | mikro (Mikro ERP'den çekilen).
-- is_return: iade faturası (stok yönü ters). stock_applied: stok hareketleri uygulandı mı.
CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,               -- alis | satis
    source       TEXT NOT NULL DEFAULT 'manual', -- manual | mikro
    is_return    INTEGER NOT NULL DEFAULT 0,
    number       TEXT,                         -- fatura / belge no
    company_id   INTEGER REFERENCES companies(id),
    company_name TEXT,                         -- anlık ünvan (firma silinse de kalır)
    invoice_date TEXT,
    warehouse_id INTEGER REFERENCES warehouses(id),
    currency     TEXT NOT NULL DEFAULT 'TRY',
    subtotal     REAL NOT NULL DEFAULT 0,
    vat_total    REAL NOT NULL DEFAULT 0,
    total        REAL NOT NULL DEFAULT 0,
    note         TEXT,
    stock_applied INTEGER NOT NULL DEFAULT 0,
    mikro_evrak  TEXT,                         -- Mikro evrak anahtarı (seri|sira|evraktip) — mükerrer aktarımı önler
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT,
    UNIQUE (source, mikro_evrak)
);
CREATE INDEX IF NOT EXISTS ix_invoices_kind ON invoices(kind, invoice_date);
CREATE TABLE IF NOT EXISTS invoice_items (
    id            INTEGER PRIMARY KEY,
    invoice_id    INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    product_id    INTEGER REFERENCES products(id) ON DELETE SET NULL,  -- eşleşen yerel malzeme (stok hareketi bunun üzerinden)
    mikro_stok    TEXT,                        -- Mikro stok kodu (eşleşmese de saklanır)
    description   TEXT NOT NULL,
    qty           REAL NOT NULL DEFAULT 0,
    unit          TEXT,
    unit_price    REAL NOT NULL DEFAULT 0,
    vat_rate      REAL NOT NULL DEFAULT 20,
    line_total    REAL NOT NULL DEFAULT 0,     -- KDV hariç satır tutarı
    move_id       INTEGER REFERENCES material_moves(id) ON DELETE SET NULL,  -- uygulanan stok hareketi
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_invoice_items_inv ON invoice_items(invoice_id);
-- Sesli görüşmeler (kişiler arası WebRTC): 1-1 ve grup. Kayıt yalnızca tüm katılımcıların onayıyla; kayıt varsa
-- görüşme bitince metne çevrilir, konuşmacılar ses profilleriyle tanınır (voice_profiles), özet çıkarılır.
CREATE TABLE IF NOT EXISTS voice_calls (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL DEFAULT 'bire_bir',   -- bire_bir | grup
    initiator_id   INTEGER REFERENCES users(id),
    title          TEXT,
    status         TEXT NOT NULL DEFAULT 'ARANIYOR',   -- ARANIYOR | DEVAM | BITTI | KACIRILDI | IPTAL
    recorded       INTEGER NOT NULL DEFAULT 0,
    process_status TEXT,                               -- NULL | ISLENIYOR | TAMAM | HATA
    process_error  TEXT,
    summary        TEXT,
    started_at     TEXT NOT NULL,
    answered_at    TEXT,
    ended_at       TEXT,
    seconds        REAL,
    processed_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_voice_calls_time ON voice_calls(started_at);
CREATE TABLE IF NOT EXISTS voice_call_participants (
    id          INTEGER PRIMARY KEY,
    call_id     INTEGER NOT NULL REFERENCES voice_calls(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT,                                  -- initiator | callee
    invited_at  TEXT,
    joined_at   TEXT,
    left_at     TEXT,
    outcome     TEXT,                                  -- ANSWERED | REJECTED | MISSED | LEFT
    rec_consent INTEGER,                               -- NULL bekliyor | 1 onay | 0 ret
    UNIQUE (call_id, user_id)
);
CREATE TABLE IF NOT EXISTS voice_call_audio (
    id         INTEGER PRIMARY KEY,
    call_id    INTEGER NOT NULL REFERENCES voice_calls(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id),           -- kaydı yükleyen (karışık ses)
    file       TEXT NOT NULL,
    wav        TEXT,
    chunks     INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    seconds    REAL
);
CREATE TABLE IF NOT EXISTS voice_call_speakers (
    id         INTEGER PRIMARY KEY,
    call_id    INTEGER NOT NULL REFERENCES voice_calls(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    user_id    INTEGER REFERENCES users(id),
    auto       INTEGER NOT NULL DEFAULT 0,
    score      REAL,
    embedding  TEXT,
    seconds    REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS voice_call_segments (
    id         INTEGER PRIMARY KEY,
    call_id    INTEGER NOT NULL REFERENCES voice_calls(id) ON DELETE CASCADE,
    audio_id   INTEGER NOT NULL REFERENCES voice_call_audio(id) ON DELETE CASCADE,
    speaker_id INTEGER REFERENCES voice_call_speakers(id) ON DELETE SET NULL,
    t0         REAL NOT NULL,
    t1         REAL NOT NULL,
    at         TEXT,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_voice_call_segments ON voice_call_segments(call_id);
"""


def now():
    return datetime.now().isoformat(timespec='seconds')


def date_cond(col, date_from=None, date_to=None):
    """Liste tarih filtresi: (SQL koşulu, parametreler). Sütun 'YYYY-MM-DD' ya da 'YYYY-MM-DDTHH:MM:SS' olabilir;
    karşılaştırma gün bazında yapılır (bitiş günü dahil). Değer verilmezse koşul '1=1'."""
    parts, args = [], []
    for v, op in ((date_from, '>='), (date_to, '<=')):
        if v:
            if not (len(v) == 10 and v[4] == '-' and v[7] == '-'):
                from fastapi import HTTPException
                raise HTTPException(400, 'Tarih YYYY-AA-GG biçiminde olmalı')
            parts.append(f'substr({col}, 1, 10) {op} ?')
            args.append(v)
    return (' AND '.join(parts) or '1=1'), args


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
    tm_cols = {r[1] for r in conn.execute('PRAGMA table_info(team_meetings)')}
    for col in ('started_at', 'ended_at', 'process_status', 'process_error', 'processed_at'):   # toplantı ekranı ve özet
        if tm_cols and col not in tm_cols:
            conn.execute(f'ALTER TABLE team_meetings ADD COLUMN {col} TEXT')
    inv_cols = {r[1] for r in conn.execute('PRAGMA table_info(team_meeting_invites)')}
    for col in ('joined_at', 'last_seen'):   # toplantı ekranına katılım
        if inv_cols and col not in inv_cols:
            conn.execute(f'ALTER TABLE team_meeting_invites ADD COLUMN {col} TEXT')
    mail_cols = {r[1] for r in conn.execute('PRAGMA table_info(mail_accounts)')}
    for col, ddl in (('auto_import', 'INTEGER NOT NULL DEFAULT 1'), ('last_uid', 'INTEGER'), ('uid_validity', 'TEXT'),
                     ('auth_type', "TEXT NOT NULL DEFAULT 'password'")):
        if mail_cols and col not in mail_cols:
            conn.execute(f'ALTER TABLE mail_accounts ADD COLUMN {col} {ddl}')
    if 'must_change_password' not in user_cols:   # ilk girişte şifre değişikliği zorunlu (yöneticinin verdiği şifre)
        conn.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
        # bir kez: şifresini hiç kendisi değiştirmemiş mevcut kullanıcılar da ilk girişte değiştirir
        conn.execute('''UPDATE users SET must_change_password = 1 WHERE deleted_at IS NULL AND id NOT IN
                        (SELECT user_id FROM audit_logs WHERE action = 'Şifresini değiştirdi' AND user_id IS NOT NULL)''')
    if 'pin_hash' not in user_cols:     # 4 haneli giriş PIN'i (Ayarlar → Hesap)
        conn.execute('ALTER TABLE users ADD COLUMN pin_hash TEXT')
    if 'password_changed_at' not in user_cols:   # şifre geçerlilik süresi (Program Ayarları → Güvenlik) için son değişim
        conn.execute('ALTER TABLE users ADD COLUMN password_changed_at TEXT')
    if 'delivered_at' not in {r[1] for r in conn.execute('PRAGMA table_info(chat_messages)')}:   # WhatsApp tarzı "iletildi" (✓✓)
        conn.execute('ALTER TABLE chat_messages ADD COLUMN delivered_at TEXT')
        conn.execute('UPDATE chat_messages SET delivered_at = read_at WHERE read_at IS NOT NULL')
    rm_cols = {r[1] for r in conn.execute('PRAGMA table_info(radio_members)')}
    if rm_cols and 'status' not in rm_cols:   # telsiz: kullanıcı daveti + onay
        conn.execute("ALTER TABLE radio_members ADD COLUMN status TEXT NOT NULL DEFAULT 'UYE'")
        conn.execute('ALTER TABLE radio_members ADD COLUMN invited_by INTEGER REFERENCES users(id)')
        conn.execute('ALTER TABLE radio_members ADD COLUMN invited_at TEXT')
    rc_cols = {r[1] for r in conn.execute('PRAGMA table_info(radio_channels)')}
    if rc_cols and 'is_company' not in rc_cols:   # telsiz: sabit "Tüm Şirket" kanalı
        conn.execute('ALTER TABLE radio_channels ADD COLUMN is_company INTEGER NOT NULL DEFAULT 0')
    # İK › Görev Tanımı: personel başına madde madde, gizlilik dereceli
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS employee_duties (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            text TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'KURUM_ICI', sort INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, created_by INTEGER REFERENCES users(id), updated_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_emp_duties ON employee_duties(employee_id);
        -- Arka plan bildirimleri (Web Push): cihaz başına tarayıcı aboneliği
        CREATE TABLE IF NOT EXISTS push_subs (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL, ua TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_push_user ON push_subs(user_id);
        -- Saha görevi İSG kontrolü: görevdeki her kişinin KKD maddeleri için saha sorumlusunun Yaptı / Yapmadı işareti
        CREATE TABLE IF NOT EXISTS field_task_isg (
            task_id INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
            item TEXT NOT NULL, status TEXT, note TEXT, checked_by INTEGER REFERENCES users(id), checked_at TEXT,
            PRIMARY KEY (task_id, user_id, item));
        -- Sağlık raporları: rapor süresince personel izinli (raporlu) görünür ve sisteme giremez
        CREATE TABLE IF NOT EXISTS employee_health_reports (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, file TEXT, file_name TEXT, note TEXT,
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_health_emp ON employee_health_reports(employee_id, end_date);
        -- İSG: kişinin kullanacağı KKD, zorunlu eğitimleri, göreve özgü tehlikeler ve kontrol tedbirleri
        CREATE TABLE IF NOT EXISTS employee_ppe (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            name TEXT NOT NULL, usage TEXT, issued_at TEXT, note TEXT, sort INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS employee_trainings (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            name TEXT NOT NULL, done_at TEXT, valid_until TEXT, note TEXT, sort INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS employee_hazards (
            id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            hazard TEXT NOT NULL, control TEXT, sort INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    ''')
    dcols = {r[1] for r in conn.execute('PRAGMA table_info(employee_duties)')}
    for col in ('section', 'role', 'phase'):   # görev tanımı bölümü (AMAC / POZISYON / ROL / YETKI / DIGER), rol ve aşama
        if col not in dcols:
            conn.execute(f'ALTER TABLE employee_duties ADD COLUMN {col} TEXT')
    ecols = {r[1] for r in conn.execute('PRAGMA table_info(employees)')}
    for col, typ in (('flight_position', 'TEXT'), ('supervisor', 'TEXT'), ('deputy_id', 'INTEGER'), ('deputy_note', 'TEXT'),
                     ('emergency_duty', 'TEXT'), ('duty_doc_no', 'TEXT'), ('duty_rev', 'TEXT'), ('duty_signed_at', 'TEXT'), ('duty_signed_file', 'TEXT')):
        if col not in ecols:
            conn.execute(f'ALTER TABLE employees ADD COLUMN {col} {typ}')
    # Saha Yönetimi › Modül Ayarları: standart saha ekipman listesi ve göreve özel ekipman listesi
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS field_equipment (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1, unit TEXT, note TEXT,
            sort INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS field_task_equipment (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1, unit TEXT, note TEXT, std_id INTEGER, sort INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fte_task ON field_task_equipment(task_id);
    ''')
    # Dış firma personeli (ör. kiralık güvenlik): firmanın Kişiler kaydı bir sistem kullanıcısına bağlanabilir; personel kaydı açılmaz
    if 'user_id' not in {r[1] for r in conn.execute('PRAGMA table_info(company_people)')}:
        conn.execute('ALTER TABLE company_people ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_company_people_user ON company_people(user_id) WHERE user_id IS NOT NULL')
    emp_cols = {r[1] for r in conn.execute('PRAGMA table_info(employees)')}
    if 'is_foreign' not in emp_cols:   # yabancı uyruklu: pasaport ve çalışma izni zorunlu
        conn.execute('ALTER TABLE employees ADD COLUMN is_foreign INTEGER NOT NULL DEFAULT 0')
    if 'security_code' not in emp_cols:   # Kişi Güvenlik Kodu (MSB Tesis Güvenlik Belgesi kapsamında alınır)
        conn.execute('ALTER TABLE employees ADD COLUMN security_code TEXT')
    if 'application_info' not in emp_cols:   # İş başvuru formundan çıkarılan ek bilgiler (JSON; İK onaylı)
        conn.execute('ALTER TABLE employees ADD COLUMN application_info TEXT')
    if 'nationality' not in emp_cols:
        conn.execute('ALTER TABLE employees ADD COLUMN nationality TEXT')
    ef_cols = {r[1] for r in conn.execute('PRAGMA table_info(employee_files)')}
    if 'approved' not in ef_cols:   # personelin kendi yüklediği özlük evrakı İK onayında bekler (mevcutlar onaylı sayılır)
        conn.execute('ALTER TABLE employee_files ADD COLUMN approved INTEGER NOT NULL DEFAULT 1')
    # Organizasyon şeması: üstten alta bağlı kartlar (kök parent_id NULL). Her kart bir personele ve göreve bağlı.
    conn.execute('''CREATE TABLE IF NOT EXISTS org_nodes (
        id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES org_nodes(id) ON DELETE CASCADE,
        employee_id INTEGER REFERENCES employees(id) ON DELETE SET NULL, title TEXT, sort INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)''')
    # PDKS (Firebird) kart numarası → personel eşleşmesi (otomatik ad eşleştirme; İK elle düzeltebilir)
    conn.execute('''CREATE TABLE IF NOT EXISTS pdks_links (
        kart_id TEXT PRIMARY KEY, employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
        pdks_name TEXT, matched_by TEXT, updated_at TEXT)''')
    for t in ('field_equipment', 'field_task_equipment'):   # ekipman stoktaki ürüne bağlı (ürün ararken seçilir)
        if 'product_id' not in {r[1] for r in conn.execute(f'PRAGMA table_info({t})')}:
            conn.execute(f'ALTER TABLE {t} ADD COLUMN product_id INTEGER REFERENCES products(id) ON DELETE SET NULL')
    if 'equip_init' not in {r[1] for r in conn.execute('PRAGMA table_info(field_tasks)')}:   # standart liste göreve kopyalandı mı
        conn.execute('ALTER TABLE field_tasks ADD COLUMN equip_init INTEGER NOT NULL DEFAULT 0')
    # Mesaj menüsü (WhatsApp tarzı): yanıt, iletildi, düzenlendi, herkesten silindi, değişiklik zamanı (açık sohbetler tazelensin)
    for t in ('chat_messages', 'chat_group_messages'):
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info({t})')}
        for col, typ in (('reply_to', 'INTEGER'), ('forwarded', 'INTEGER NOT NULL DEFAULT 0'), ('edited_at', 'TEXT'),
                         ('deleted_at', 'TEXT'), ('updated_at', 'TEXT')):
            if cols and col not in cols:
                conn.execute(f'ALTER TABLE {t} ADD COLUMN {col} {typ}')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS chat_reactions (   -- kind: d (birebir) | g (grup)
            kind TEXT NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
            emoji TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (kind, msg_id, user_id));
        CREATE TABLE IF NOT EXISTS chat_hidden (      -- "benden sil"
            kind TEXT NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (kind, msg_id, user_id));
        CREATE TABLE IF NOT EXISTS chat_stars (       -- yıldızlı mesajlar
            kind TEXT NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
            at TEXT NOT NULL, PRIMARY KEY (kind, msg_id, user_id));
        CREATE INDEX IF NOT EXISTS idx_chat_upd ON chat_messages(updated_at);
        CREATE INDEX IF NOT EXISTS idx_chat_gupd ON chat_group_messages(updated_at);
    ''')
    acr_cols = {r[1] for r in conn.execute('PRAGMA table_info(ai_change_requests)')}
    if acr_cols and 'preview' not in acr_cols:   # talep oluşturulurken yapılan ön deneme sonucu (etkilenecek satır sayıları)
        conn.execute('ALTER TABLE ai_change_requests ADD COLUMN preview TEXT')
    if 'ai_offtopic' not in user_cols:   # yapay zekaya sistem dışı (genel) soru sorabilme (yönetici açar/kapatır)
        conn.execute('ALTER TABLE users ADD COLUMN ai_offtopic INTEGER NOT NULL DEFAULT 1')
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
    pcols = {r[1] for r in conn.execute('PRAGMA table_info(printers)')}
    if pcols and 'mac' not in pcols:        # yazıcının kablolu ağ MAC'i (kalıcı kimlik; ağ adı K2Plus-XXXX son iki bayttan türer)
        conn.execute('ALTER TABLE printers ADD COLUMN mac TEXT')
    if pcols and 'hw_alias' not in pcols:   # ağ adı elle sayıya çevrilmiş yazıcılar için ikinci kimlik (Moonraker'ın bildirdiği ad)
        conn.execute('ALTER TABLE printers ADD COLUMN hw_alias TEXT')
    if 'hw_id' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:   # kalıcı donanım kimliği (Moonraker seri-adı); IP değişse de aynı
        conn.execute('ALTER TABLE printers ADD COLUMN hw_id TEXT')
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
    for col in ('gcode_file', 'gcode_meta', 'gcode_thumb', 'gcode_preview'):   # parçanın G-code dosyası, bilgileri, önizleme, 3B yol
        if col not in prod_cols:
            conn.execute(f'ALTER TABLE products ADD COLUMN {col} TEXT')
    if 'parent_id' not in prod_cols:   # yarı mamul: ait olduğu mamul
        conn.execute('ALTER TABLE products ADD COLUMN parent_id INTEGER REFERENCES products(id)')
    md_cols = {r[1] for r in conn.execute('PRAGMA table_info(material_docs)')}
    if 'request_id' not in md_cols:   # Satın Alma: faturanın bağlı olduğu talep ve girişin yapıldığı depo
        conn.execute('ALTER TABLE material_docs ADD COLUMN request_id INTEGER REFERENCES purchase_requests(id)')
        conn.execute('ALTER TABLE material_docs ADD COLUMN warehouse_id INTEGER REFERENCES warehouses(id)')
    if 'is_supplier' not in {r[1] for r in conn.execute('PRAGMA table_info(companies)')}:   # tedarikçi (Satın Alma)
        conn.execute('ALTER TABLE companies ADD COLUMN is_supplier INTEGER NOT NULL DEFAULT 0')
    lr_cols = {r[1] for r in conn.execute('PRAGMA table_info(leave_requests)')}
    if 'signed_file' not in lr_cols:   # onaylanan iznin ıslak imzalı formu (İK yükler)
        for col in ('signed_file', 'signed_name', 'signed_at'):
            conn.execute(f'ALTER TABLE leave_requests ADD COLUMN {col} TEXT')
        conn.execute('ALTER TABLE leave_requests ADD COLUMN signed_by INTEGER REFERENCES users(id)')
    if 'edited_by' not in {r[1] for r in conn.execute('PRAGMA table_info(team_meeting_notes)')}:   # toplantı sonrası düzenleyen
        conn.execute('ALTER TABLE team_meeting_notes ADD COLUMN edited_by INTEGER REFERENCES users(id)')
    if 'seen_at' not in {r[1] for r in conn.execute('PRAGMA table_info(guest_visit_hosts)')}:   # misafir bildirimi görüldü
        conn.execute('ALTER TABLE guest_visit_hosts ADD COLUMN seen_at TEXT')
    for col, typ in (('barcode', 'TEXT'), ('brand', 'TEXT'), ('model', 'TEXT'), ('color', 'TEXT'), ('width_mm', 'REAL'),
                     ('height_mm', 'REAL'), ('depth_mm', 'REAL'), ('weight_g', 'REAL'), ('min_stock', 'REAL')):   # MRP malzeme bilgileri
        if col not in prod_cols:
            conn.execute(f'ALTER TABLE products ADD COLUMN {col} {typ}')
    if 'material_review_at' not in {r[1] for r in conn.execute('PRAGMA table_info(orders)')}:   # hurda uçağın malzemeleri değerlendirildi
        conn.execute('ALTER TABLE orders ADD COLUMN material_review_at TEXT')
        conn.execute("UPDATE orders SET material_review_at = scrapped_at WHERE status = 'HURDA'")   # eski hurdalar sorulmaz
    if not conn.execute('SELECT 1 FROM warehouses').fetchone():
        conn.execute("INSERT INTO warehouses (name, code, created_at) VALUES ('Ana Depo', 'ANA', ?)", (now(),))
    first_bom = 'unit' not in prod_cols   # ürün ağacı / reçete sistemine geçiş (bir kez)
    for col in ('unit', 'image'):   # birim (yedek parça, hammadde) · 2B üstten görünüm resmi
        if col not in prod_cols:
            conn.execute(f'ALTER TABLE products ADD COLUMN {col} TEXT')
    from . import bom, semis, spares   # döngüsel içe aktarmayı önlemek için burada
    spares.seed(conn)
    semis.seed(conn)
    if first_bom:
        bom.migrate(conn)
    from .routers import hr   # her kullanıcı aynı zamanda personeldir
    hr.sync_users(conn)
    # (bir kez) personelin tek adres alanı Adresler'e taşınır
    conn.execute("""INSERT INTO employee_addresses (employee_id, label, address, is_primary, created_at)
                    SELECT id, 'Ev', address, 1, created_at FROM employees e WHERE address IS NOT NULL AND trim(address) != ''
                      AND NOT EXISTS (SELECT 1 FROM employee_addresses a WHERE a.employee_id = e.id)""")
    conn.execute('UPDATE employees SET address = NULL WHERE address IS NOT NULL AND id IN (SELECT employee_id FROM employee_addresses)')
    conn.execute("UPDATE products SET orderable = 0 WHERE (schema LIKE 'semi-%' OR schema = 'custom') AND orderable = 1")
    default = conn.execute('SELECT id FROM products ORDER BY id LIMIT 1').fetchone()[0]
    conn.execute('UPDATE orders SET product_id = ? WHERE product_id IS NULL', (default,))
    if 'clip' not in {r[1] for r in conn.execute('PRAGMA table_info(face_sightings)')}:   # görülme anının kısa videosu (lokal)
        conn.execute('ALTER TABLE face_sightings ADD COLUMN clip TEXT')
    if 'threshold' not in {r[1] for r in conn.execute('PRAGMA table_info(face_sightings)')}:   # görülme anındaki tanıma hassasiyeti (eşik)
        conn.execute('ALTER TABLE face_sightings ADD COLUMN threshold REAL')
    # Personel aile üyeleri + yüz tanımada eğitilebilirlik
    conn.execute('''CREATE TABLE IF NOT EXISTS family_members (
        id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        full_name TEXT NOT NULL, relation TEXT, birth_date TEXT, phone TEXT, note TEXT, created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_family_members_emp ON family_members(employee_id)')
    if 'family_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_enroll)')}:
        conn.execute('ALTER TABLE face_enroll ADD COLUMN family_id INTEGER REFERENCES family_members(id) ON DELETE CASCADE')
    if 'family_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_groups)')}:
        conn.execute('ALTER TABLE face_groups ADD COLUMN family_id INTEGER REFERENCES family_members(id) ON DELETE SET NULL')


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
