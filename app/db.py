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
    location_off  INTEGER NOT NULL DEFAULT 0,   -- MASTER: konum takibi tamamen kapalı (hiç kaydedilmez, haritada görünmez)
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
-- Şirketten Haberler (pano akışı, Facebook tarzı): sistem olayları (işe alım, çıkış, uçuş, sipariş, toplantı…) ve
-- kullanıcı paylaşımları (resim / video / ses + konum). author_id NULL = sistem (şirket logosu); doluysa kişinin fotoğrafı.
CREATE TABLE IF NOT EXISTS feed_posts (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'USER',   -- USER | HIRE | TERMINATION | FLIGHT | ORDER | MEETING | ANNOUNCE | ...
    author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text       TEXT,
    media      TEXT,                            -- JSON: [{type:image|video|audio, path, thumb?}]
    lat        REAL,
    lng        REAL,
    ref_type   TEXT,                            -- bağlı kayıt türü (order|flight|employee|meeting…)
    ref_id     INTEGER,
    ref_link   TEXT,                            -- tıklanınca gidilecek hash (ör. #/orders/12)
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_feed_posts_at ON feed_posts(created_at);
-- Şirketten Haberler: paylaşıma beğeni / tepki (kullanıcı başına bir tepki; emoji değiştirilebilir)
CREATE TABLE IF NOT EXISTS feed_reactions (
    post_id    INTEGER NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emoji      TEXT NOT NULL DEFAULT '👍',
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, user_id)
);
-- Şirketten Haberler: paylaşıma yorum
CREATE TABLE IF NOT EXISTS feed_comments (
    id         INTEGER PRIMARY KEY,
    post_id    INTEGER NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_feed_comments_post ON feed_comments(post_id);
-- Canlı yayın (sahadan / her yerden): yayın bitince kayıt Şirketten Haberler'e paylaşılır
CREATE TABLE IF NOT EXISTS live_streams (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT,
    status        TEXT NOT NULL DEFAULT 'live',   -- live | ended
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    viewers_peak  INTEGER NOT NULL DEFAULT 0,
    viewers_total INTEGER NOT NULL DEFAULT 0,
    likes         INTEGER NOT NULL DEFAULT 0,
    comments      INTEGER NOT NULL DEFAULT 0,
    recording     TEXT,                           -- uploads içindeki yol (feed/live_<id>.mp4)
    post_id       INTEGER,
    lat           REAL,
    lng           REAL
);
CREATE INDEX IF NOT EXISTS ix_live_status ON live_streams(status);
CREATE TABLE IF NOT EXISTS live_comments (
    id         INTEGER PRIMARY KEY,
    stream_id  INTEGER NOT NULL REFERENCES live_streams(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_viewers (
    stream_id  INTEGER NOT NULL REFERENCES live_streams(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at  TEXT NOT NULL,
    PRIMARY KEY (stream_id, user_id)
);
-- Şirketten Haberler: kullanıcının favorilere kaydettiği paylaşımlar (Instagram "Kaydet")
CREATE TABLE IF NOT EXISTS feed_views (                -- paylaşımı kim ne zaman gördü (ilk görünme; master 'Görenler')
    post_id INTEGER NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at      TEXT NOT NULL,
    PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS feed_saves (
    post_id    INTEGER NOT NULL REFERENCES feed_posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, post_id)
);
-- Şirketten Haberler: yoruma kalp (kullanıcı başına bir beğeni)
CREATE TABLE IF NOT EXISTS feed_comment_likes (
    comment_id INTEGER NOT NULL REFERENCES feed_comments(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);
-- Merkez (Veilox) destek girişi: müşteri instance'ında bekleyen çapraz-giriş onayları
CREATE TABLE IF NOT EXISTS crosslogin_requests (
    id          INTEGER PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,            -- giriş ekranının yoklama jetonu
    username    TEXT NOT NULL,                   -- merkez destek kullanıcısı (e-posta)
    full_name   TEXT,
    ip          TEXT,
    user_agent  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected | expired
    session_token TEXT,                          -- onaylanınca oluşan oturum jetonu (giriş ekranı bununla girer)
    local_user_id INTEGER,                       -- bu instance'ta destek kullanıcısını temsil eden yerel kayıt
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_crosslogin_status ON crosslogin_requests(status, created_at);
-- Finans / ön-muhasebe: hesaplar (kasa/banka/cari) + hareketler. Mikro entegrasyonu için kod/ref alanları.
CREATE TABLE IF NOT EXISTS fin_accounts (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,                 -- kasa | banka | cari
    name        TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'TRY',
    iban        TEXT,
    bank        TEXT,
    company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,   -- cari ise firma bağı
    opening     REAL NOT NULL DEFAULT 0,        -- açılış bakiyesi
    mikro_code  TEXT,                           -- Mikro cari/hesap kodu
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fin_accounts_kind ON fin_accounts(kind, active);
CREATE TABLE IF NOT EXISTS fin_txns (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES fin_accounts(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,                 -- YYYY-MM-DD
    direction     TEXT NOT NULL,                 -- in (tahsilat/giriş) | out (ödeme/çıkış)
    amount        REAL NOT NULL,                 -- pozitif tutar
    currency      TEXT NOT NULL DEFAULT 'TRY',
    category      TEXT,                          -- gelir/gider kategorisi
    counter_id    INTEGER REFERENCES fin_accounts(id) ON DELETE SET NULL,  -- virman karşı hesap
    description   TEXT,
    doc_no        TEXT,
    mikro_ref     TEXT,                          -- Mikro'dan aktarıldıysa referans
    created_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fin_txns_acc ON fin_txns(account_id, date);
-- Sertifikasyon: şirketin sahip olduğu / almaya çalıştığı sertifikalar, dokümanları ve denetimleri
CREATE TABLE IF NOT EXISTS certs (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    standard    TEXT,                          -- ör. ISO 9001:2015
    issuer      TEXT,                          -- belgelendirme kuruluşu / kurum
    cert_no     TEXT,
    status      TEXT NOT NULL DEFAULT 'gecerli',   -- hazirlik | basvuru | gecerli | askida | suresi_doldu | iptal
    apply_date  TEXT,
    issue_date  TEXT,
    expiry_date TEXT,
    scope       TEXT,
    note        TEXT,
    image       TEXT,                          -- taranmış sertifika (A4 dikey)
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS cert_audits (
    id           INTEGER PRIMARY KEY,
    cert_id      INTEGER NOT NULL REFERENCES certs(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'gozetim',  -- ilk | gozetim | yeniden | ic | musteri | ozel
    body         TEXT,                          -- denetleyen kuruluş
    auditor      TEXT,                          -- denetçi(ler)
    result       TEXT NOT NULL DEFAULT 'planlandi', -- planlandi | basarili | sartli | basarisiz | iptal
    major        INTEGER NOT NULL DEFAULT 0,    -- majör uygunsuzluk
    minor        INTEGER NOT NULL DEFAULT 0,    -- minör uygunsuzluk
    observations INTEGER NOT NULL DEFAULT 0,    -- gözlem / iyileştirme fırsatı
    capa_due     TEXT,                          -- düzeltici faaliyet son tarihi
    next_date    TEXT,                          -- bir sonraki denetim
    notes        TEXT,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_cert_audits ON cert_audits(cert_id, date);
CREATE TABLE IF NOT EXISTS cert_docs (
    id          INTEGER PRIMARY KEY,
    cert_id     INTEGER NOT NULL REFERENCES certs(id) ON DELETE CASCADE,
    audit_id    INTEGER REFERENCES cert_audits(id) ON DELETE CASCADE,
    folder      TEXT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cert_docs ON cert_docs(cert_id, audit_id);
-- Araç Yönetimi: araçlar field_vehicles'tadır (Saha ile ortak; ek sütunlar _migrate'te). Zimmet, gider, belge.
CREATE TABLE IF NOT EXISTS vehicle_assignments (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES field_vehicles(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    start_date  TEXT NOT NULL,
    start_km    REAL,
    start_fuel  TEXT,                          -- bos | 1/4 | 1/2 | 3/4 | dolu
    equipment   TEXT,                          -- JSON: teslim edilen ekipman listesi
    condition   TEXT,                          -- teslimdeki hasar / durum notu
    note        TEXT,
    end_date    TEXT,                          -- NULL: zimmet sürüyor
    end_km      REAL,
    end_fuel    TEXT,
    end_note    TEXT,
    accepted_at TEXT,                          -- personelin uygulama içi teslim alma onayı
    accepted_ip TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicle_assign ON vehicle_assignments(vehicle_id, end_date);
CREATE INDEX IF NOT EXISTS ix_vehicle_assign_user ON vehicle_assignments(user_id, end_date);
CREATE TABLE IF NOT EXISTS vehicle_expenses (
    id          INTEGER PRIMARY KEY,
    vehicle_id  INTEGER NOT NULL REFERENCES field_vehicles(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    category    TEXT NOT NULL,                 -- yakit | bakim | lastik | sigorta | vergi | otoyol | otopark | kira | ceza | yikama | diger
    amount      REAL NOT NULL,
    liters      REAL,
    km          REAL,
    vendor      TEXT,
    description TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',  -- manual | mikro (muhasebe gider satırı) | finans (kasa/banka çıkışı)
    ref         TEXT,                          -- kaynak hareket anahtarı (bir hareket birden çok araca bölünebilir)
    ref_total   REAL,                          -- kaynak hareketin toplam tutarı
    receipt     TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicle_exp ON vehicle_expenses(vehicle_id, date);
CREATE INDEX IF NOT EXISTS ix_vehicle_exp_ref ON vehicle_expenses(ref);
CREATE TABLE IF NOT EXISTS vehicle_docs (
    id            INTEGER PRIMARY KEY,
    vehicle_id    INTEGER NOT NULL REFERENCES field_vehicles(id) ON DELETE CASCADE,
    assignment_id INTEGER REFERENCES vehicle_assignments(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL DEFAULT 'diger',
    name          TEXT NOT NULL,
    path          TEXT NOT NULL,
    size          INTEGER,
    expires       TEXT,
    uploaded_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vehicle_docs ON vehicle_docs(vehicle_id);
-- Proje Yönetimi (Ar-Ge): proje bir GRUPLAMADIR — hareket / fatura / kalem projeye etiketlenir (project_tags); proje
-- silinince yalnız etiketler kalkar, finansal veri silinmez. project_id NULL etiket = bilinçli "projesiz" kararı.
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'arge',      -- arge | musteri | ic | destek
    status      TEXT NOT NULL DEFAULT 'devam',     -- fikir | planlama | devam | beklemede | tamamlandi | iptal
    manager_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,   -- müşteri / destek kurumu
    start_date  TEXT,
    end_date    TEXT,
    budget      REAL,
    image       TEXT,
    summary     TEXT,
    description TEXT,
    keywords    TEXT,                              -- tarama / eşleştirme anahtar kelimeleri (virgülle)
    mikro_code  TEXT,                              -- Mikro proje kodu (senkronla eşleşme)
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS mikro_projects (     -- Mikro PROJELER (Entegrasyonlar › Mikro senkronu)
    code TEXT PRIMARY KEY,
    name TEXT
);
CREATE TABLE IF NOT EXISTS project_images (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    caption     TEXT,
    sort        INTEGER NOT NULL DEFAULT 0,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_tags (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,                     -- txn (fin_txns) | invoice (invoices) | mdoc (material_docs)
    ref         INTEGER NOT NULL,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,   -- NULL: projesiz
    nature      TEXT NOT NULL,                     -- gelir | gider | odeme (tahsilat / ödeme: kâr-zarar dışı)
    amount      REAL NOT NULL,                     -- dilimin brüt tutarı
    net         REAL NOT NULL,                     -- KDV hariç (kâr-zarar bununla)
    line_ref    TEXT,                              -- kalem bazında ayırma: 'item:ID' | 'mline:ID' | 'ledger:GUID'
    line_desc   TEXT,
    note        TEXT,
    auto        INTEGER NOT NULL DEFAULT 0,        -- tarama / kural ile otomatik
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_project_tags_src ON project_tags(source, ref);
CREATE INDEX IF NOT EXISTS ix_project_tags_prj ON project_tags(project_id);
-- Rol Yönetimi (Program Ayarları): roller ağaç şeklinde (parent'tan yetki mirası), rol × düğüm (modül / alt modül) × yetenek
-- (open: aç · read: veri oku · write: veri yaz) → allow 1 / deny 0; kayıt yoksa miras. Sistem rolleri koddaki ROLES'tan gelir.
CREATE TABLE IF NOT EXISTS roles (
    name        TEXT PRIMARY KEY,
    description TEXT,
    parent      TEXT,
    system      INTEGER NOT NULL DEFAULT 0,
    sort        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS role_perms (
    role   TEXT NOT NULL,
    node   TEXT NOT NULL,
    cap    TEXT NOT NULL,
    allow  INTEGER NOT NULL,
    PRIMARY KEY (role, node, cap)
);
-- Görev ayrılığı: aynı kişide birlikte bulunmaması gereken roller (atamada uyarı)
CREATE TABLE IF NOT EXISTS role_conflicts (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    PRIMARY KEY (a, b)
);
-- Personel ↔ finans bağlantısı: isimle otomatik eşleşmeye ek olarak personel bir cariye (firma), kasa/banka hesabına
-- (ör. şirket kredi kartı) ya da muhasebe hesabına (ör. 331 ortaklara borçlar alt hesabı) elle bağlanır.
CREATE TABLE IF NOT EXISTS employee_fin_links (
    id          INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                 -- company | account | ledger
    ref         TEXT NOT NULL,                 -- companies.id | fin_accounts.id | fin_coa.code
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (employee_id, kind, ref)
);
-- Araçla ilgisi olmadığı işaretlenen muhasebe / finans hareketleri (etiketleme listesinde gizlenir)
CREATE TABLE IF NOT EXISTS vehicle_ignored (
    ref        TEXT PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
-- Finans v2: Mikro muhasebe (hesap planı + yevmiye satırları) → mizan / mali tablolar
CREATE TABLE IF NOT EXISTS fin_coa (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS fin_ledger (
    id          INTEGER PRIMARY KEY,
    guid        TEXT NOT NULL UNIQUE,
    date        TEXT NOT NULL,
    journal_no  INTEGER,
    entry_no    INTEGER,
    kind        INTEGER,                       -- Mikro fiş türü
    account     TEXT NOT NULL,
    description TEXT,
    debit       REAL NOT NULL DEFAULT 0,
    credit      REAL NOT NULL DEFAULT 0,
    doc_no      TEXT
);
CREATE INDEX IF NOT EXISTS ix_fin_ledger_acc ON fin_ledger(account, date);
CREATE INDEX IF NOT EXISTS ix_fin_ledger_date ON fin_ledger(date);
-- Finans v2: çek / senet portföyü
CREATE TABLE IF NOT EXISTS fin_instruments (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,                 -- cek | senet
    direction   TEXT NOT NULL,                 -- alinan (müşteriden) | verilen (tedarikçiye)
    number      TEXT,
    bank        TEXT,
    drawer      TEXT,                          -- keşideci / borçlu
    company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    amount      REAL NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'TRY',
    issue_date  TEXT,
    due_date    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'portfoy',  -- portfoy | tahsilde | teminatta | ciro | tahsil | odendi | karsiliksiz | iade
    note        TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_fin_instr_due ON fin_instruments(due_date, status);
-- Finans v2: planlı ödeme / tahsilatlar (kira, kredi taksidi… nakit akışı takvimi)
CREATE TABLE IF NOT EXISTS fin_plans (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    direction   TEXT NOT NULL,                 -- in | out
    amount      REAL NOT NULL,
    description TEXT NOT NULL,
    category    TEXT,
    repeat      TEXT NOT NULL DEFAULT 'none',  -- none | monthly
    until       TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
-- Merkez modu (Veilox Merkez): firmaların destek talepleri (ticket) + mesajları
CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY,
    code            TEXT,                          -- T-0001
    slug            TEXT NOT NULL,                 -- firma (merkez slug)
    company_name    TEXT,
    subject         TEXT NOT NULL,
    category        TEXT,                          -- teknik | fatura | öneri | diğer
    priority        TEXT NOT NULL DEFAULT 'normal',-- dusuk | normal | yuksek | acil
    status          TEXT NOT NULL DEFAULT 'acik',  -- acik | yanit_bekliyor | cozuldu | kapali
    opened_by_name  TEXT,
    opened_by_email TEXT,
    assignee_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    company_unread  INTEGER NOT NULL DEFAULT 0,    -- firmanın okumadığı destek yanıtı sayısı
    support_unread  INTEGER NOT NULL DEFAULT 1,    -- desteğin okumadığı firma mesajı sayısı
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tickets_slug ON tickets(slug, updated_at);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status, updated_at);
CREATE TABLE IF NOT EXISTS ticket_messages (
    id          INTEGER PRIMARY KEY,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_kind TEXT NOT NULL,                     -- company | support | system
    author_name TEXT,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ticket_messages_t ON ticket_messages(ticket_id, id);
-- Merkez Destek Merkezi: canlı destek (sohbet), destek ekibi, hazır yanıtlar, dosya ekleri, ödeme bildirimleri
CREATE TABLE IF NOT EXISTS support_staff (
    user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'offline',   -- online | busy | away | offline
    skills      TEXT NOT NULL DEFAULT '[]',        -- JSON: talep kategorileri (teknik, fatura, egitim…)
    max_chats   INTEGER NOT NULL DEFAULT 3,        -- aynı anda en çok canlı sohbet
    title       TEXT,                              -- ör. Teknik Destek Uzmanı
    last_seen   TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS support_chats (
    id              INTEGER PRIMARY KEY,
    code            TEXT,                          -- C-0001
    slug            TEXT NOT NULL,
    company_name    TEXT,
    user_name       TEXT,
    user_email      TEXT,
    topic           TEXT,
    category        TEXT,
    status          TEXT NOT NULL DEFAULT 'waiting',  -- waiting | active | ended | missed
    assignee_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    company_unread  INTEGER NOT NULL DEFAULT 0,
    support_unread  INTEGER NOT NULL DEFAULT 0,
    rating          INTEGER,
    rating_note     TEXT,
    ticket_id       INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    ended_by        TEXT,
    created_at      TEXT NOT NULL,
    accepted_at     TEXT,
    ended_at        TEXT,
    last_msg_at     TEXT,
    company_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_support_chats ON support_chats(status, created_at);
CREATE INDEX IF NOT EXISTS ix_support_chats_slug ON support_chats(slug, created_at);
CREATE TABLE IF NOT EXISTS support_chat_messages (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL REFERENCES support_chats(id) ON DELETE CASCADE,
    author_kind TEXT NOT NULL,                     -- company | support | system
    author_name TEXT,
    body        TEXT,
    kind        TEXT NOT NULL DEFAULT 'text',      -- text | file | screen
    file_id     INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_support_chat_msgs ON support_chat_messages(chat_id, id);
CREATE TABLE IF NOT EXISTS support_canned (
    id          INTEGER PRIMARY KEY,
    shortcut    TEXT,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS support_files (
    id          INTEGER PRIMARY KEY,
    token       TEXT UNIQUE NOT NULL,
    slug        TEXT NOT NULL,
    ticket_id   INTEGER,
    message_id  INTEGER,
    chat_id     INTEGER,
    name        TEXT NOT NULL,
    mime        TEXT,
    size        INTEGER NOT NULL DEFAULT 0,
    path        TEXT NOT NULL,
    uploaded_by TEXT,                              -- company | support
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_support_files_t ON support_files(ticket_id, message_id);
CREATE TABLE IF NOT EXISTS payment_notices (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL,
    company_name  TEXT,
    period        TEXT,                            -- YYYY-AA
    amount        REAL NOT NULL,
    paid_at       TEXT,
    method        TEXT,
    reference     TEXT,                            -- dekont / işlem no
    note          TEXT,
    by_name       TEXT,
    by_email      TEXT,
    status        TEXT NOT NULL DEFAULT 'bekliyor',  -- bekliyor | onaylandi | reddedildi
    payment_id    INTEGER,
    decided_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decided_at    TEXT,
    decision_note TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_payment_notices ON payment_notices(slug, created_at);
-- Merkez: firma bayrakları (yumuşak askı, iletişim telefonu) — kurulum kayıtları Veilox'ta, bunlar merkezde
CREATE TABLE IF NOT EXISTS member_flags (
    slug        TEXT PRIMARY KEY,
    suspended   INTEGER NOT NULL DEFAULT 0,
    reason      TEXT,
    phone       TEXT,
    note        TEXT,
    updated_at  TEXT
);
-- Merkez: üyelik ödemeleri (dönem bazlı)
CREATE TABLE IF NOT EXISTS member_payments (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL,
    period      TEXT NOT NULL,                     -- YYYY-MM
    amount      REAL NOT NULL,
    paid_at     TEXT NOT NULL,
    method      TEXT,                              -- havale | kart | nakit
    note        TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_member_payments ON member_payments(slug, period);
-- Merkez: üyelik sözleşmeleri (sürümlü şablonlar) + firmaların elektronik onay kanıtları
CREATE TABLE IF NOT EXISTS contract_docs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,                     -- abonelik | kvkk | sla | aup | diger
    title        TEXT NOT NULL,
    version      TEXT NOT NULL,
    summary      TEXT,                              -- kısa açıklama / değişiklik özeti
    body         TEXT NOT NULL,                     -- alanlı metin ({{firma}} …)
    required     INTEGER NOT NULL DEFAULT 1,        -- firmaların onayı zorunlu mu
    status       TEXT NOT NULL DEFAULT 'draft',     -- draft | published | archived
    published_at TEXT,
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS contract_acceptances (
    id           INTEGER PRIMARY KEY,
    doc_id       INTEGER NOT NULL REFERENCES contract_docs(id) ON DELETE CASCADE,
    slug         TEXT NOT NULL,
    company_name TEXT,
    signer_name  TEXT NOT NULL,
    signer_title TEXT,
    signer_email TEXT,
    doc_hash     TEXT NOT NULL,                     -- SHA-256 (firmaya özel doldurulmuş metin)
    body         TEXT NOT NULL,                     -- onaylanan metnin birebir kopyası
    ip           TEXT,
    user_agent   TEXT,
    accepted_at  TEXT NOT NULL,
    UNIQUE (doc_id, slug)
);
-- Merkez: toplu SMS gönderim kaydı
CREATE TABLE IF NOT EXISTS sms_log (
    id          INTEGER PRIMARY KEY,
    numbers     TEXT NOT NULL,                     -- JSON liste
    message     TEXT NOT NULL,
    status      TEXT NOT NULL,                     -- sent | failed | dry
    provider    TEXT,
    response    TEXT,
    sent_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
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
-- Ziyaretçiler (firmaya gelen kişiler). Yüz tanımada eğitilebilir (face_enroll.visitor_id) — personel/firma kişisi/aile dışı özne.
CREATE TABLE IF NOT EXISTS visitors (
    id          INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    company     TEXT,                -- geldiği firma (ops.)
    phone       TEXT,
    note        TEXT,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_visitors_name ON visitors(full_name);
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
-- KVKK açık rıza kayıtları: özellikle biyometrik yüz + ses-izi (özel nitelikli kişisel veri). Denetim modunda canlı
-- tanıma çalışmaya devam eder; bu tablo rıza durumunu kaydeder/raporlar. subject_type: user/employee/person/visitor/family.
CREATE TABLE IF NOT EXISTS kvkk_consent (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,            -- 'biometric' | 'voice'
    subject_type TEXT NOT NULL,
    subject_id   INTEGER NOT NULL,
    granted      INTEGER NOT NULL DEFAULT 1,
    note         TEXT,
    by_user      INTEGER REFERENCES users(id),
    updated_at   TEXT,
    UNIQUE (kind, subject_type, subject_id)
);
-- KVKK veri sahibi başvuruları (uygulama içi, KVKK md. 11): export / delete / object. status: open/handled.
CREATE TABLE IF NOT EXISTS kvkk_requests (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,            -- 'export' | 'delete' | 'object'
    note        TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    handled_by  INTEGER REFERENCES users(id),
    handled_at  TEXT,
    resolution  TEXT
);
-- SSH erişim (yalnız sistem sahibi / MASTER): kayıtlı uzak sunucular (ör. fabrikadaki GX10). Parola / özel anahtar
-- cameras.encrypt ile ŞİFRELİ saklanır, hiçbir yanıtta dönmez. Yalnız dışa doğru bağlantı (merkez sunucuda kabuk AÇMAZ).
-- Kişisel notlar (yapışkan not): yalnız sahibi görür. pinned=1 ise ekrana iğnelenir (pin_x/pin_y oranı 0–1),
-- hangi modüle gidilirse gidilsin ekranda kalır. color: sarı/yeşil/mavi/pembe vb.
CREATE TABLE IF NOT EXISTS personal_notes (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       TEXT NOT NULL DEFAULT '',
    color      TEXT NOT NULL DEFAULT 'yellow',
    pinned     INTEGER NOT NULL DEFAULT 0,
    pin_x      REAL,
    pin_y      REAL,
    sort       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON personal_notes(user_id);
-- Dosya Yöneticisi: kişiye özel dosya gezgini (iç içe klasör + dosya). Her düğüm bir kullanıcıya aittir; kullanıcı
-- ya da rol ile paylaşılabilir (fm_shares). Klasör paylaşımı alt ağacın tamamını paylaşır. file_path UPLOAD_DIR'e görelidir.
CREATE TABLE IF NOT EXISTS fm_nodes (
    id         INTEGER PRIMARY KEY,
    owner_id   INTEGER NOT NULL REFERENCES users(id),
    parent_id  INTEGER REFERENCES fm_nodes(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,              -- folder | file
    name       TEXT NOT NULL,
    file_path  TEXT,                       -- yalnız dosya: UPLOAD_DIR'e göreli yol (fm/<ad>)
    size       INTEGER,
    mime       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_fm_nodes_parent ON fm_nodes(owner_id, parent_id);
-- Dosya paylaşımı: bir düğüm (dosya / klasör) bir kullanıcı ya da rol ile paylaşılır (view / edit)
CREATE TABLE IF NOT EXISTS fm_shares (
    id             INTEGER PRIMARY KEY,
    node_id        INTEGER NOT NULL REFERENCES fm_nodes(id) ON DELETE CASCADE,
    target_type    TEXT NOT NULL,          -- user | role
    target_user_id INTEGER REFERENCES users(id),
    target_role    TEXT,
    perm           TEXT NOT NULL DEFAULT 'view',   -- view | edit
    shared_by      INTEGER NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL,
    UNIQUE (node_id, target_type, target_user_id, target_role)
);
-- Paylaşım bildirimi okundu kaydı: kullanıcı "Benimle paylaşılanlar"ı açınca bildirim temizlenir
CREATE TABLE IF NOT EXISTS fm_share_seen (
    share_id INTEGER NOT NULL REFERENCES fm_shares(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seen_at  TEXT NOT NULL,
    PRIMARY KEY (share_id, user_id)
);
-- Dosya Yöneticisi DIŞ (herkese açık) paylaşım bağlantısı: oturumsuz ziyaretçi bağlantıyı açar, şifre girer, paylaşılan
-- dosyayı / klasörü (alt ağaç) görür ve indirir. Bağlantı süreli (expires_at), şifreli (password_hash) ve TEK OTURUMA
-- bağlıdır: şifreyi ilk doğru giren oturum bağlantıyı sahiplenir (claimed_session), başka oturum reddedilir.
CREATE TABLE IF NOT EXISTS fm_public_links (
    id              INTEGER PRIMARY KEY,
    token           TEXT UNIQUE NOT NULL,
    node_id         INTEGER NOT NULL REFERENCES fm_nodes(id) ON DELETE CASCADE,
    password_hash   TEXT NOT NULL,
    expires_at      TEXT,                      -- NULL = süresiz
    created_by      INTEGER,
    created_at      TEXT,
    claimed_session TEXT,                      -- ilk doğru şifreyi giren oturumun gizli anahtarı (çerez ile eşleşir)
    claimed_at      TEXT,
    claimed_ua      TEXT,
    claimed_ip      TEXT,
    revoked         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_fm_public_links_token ON fm_public_links(token);
CREATE TABLE IF NOT EXISTS ssh_hosts (
    id         INTEGER PRIMARY KEY,
    label      TEXT NOT NULL,
    host       TEXT NOT NULL,
    port       INTEGER NOT NULL DEFAULT 22,
    username   TEXT NOT NULL,
    auth_type  TEXT NOT NULL DEFAULT 'password',   -- password | key
    secret     TEXT,                               -- şifreli parola ya da özel anahtar
    note       TEXT,
    sort       INTEGER NOT NULL DEFAULT 0,
    last_used  TEXT,
    created_at TEXT NOT NULL
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
-- Yapılacaklar (TODO): yönetici verir, personel başlatır (süre) → maddeler → tamamlar (routers/todos.py)
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    note TEXT,
    assignee_id INTEGER NOT NULL REFERENCES users(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    due_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    done_at TEXT,
    elapsed_s INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    seen_at TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_todos_assignee ON todos(assignee_id, status);
CREATE TABLE IF NOT EXISTS todo_items (
    id INTEGER PRIMARY KEY,
    todo_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_todo_items_todo ON todo_items(todo_id);
-- Günlük Görevler: Sistem Yöneticisi tarafından belirli bir kullanıcıya atanan görevler (temizlikten bağımsız).
-- recurring=1 → her gün tekrarlar (günlük tamamlama user_task_log'da); recurring=0 → tek seferlik (done_at tabloda).
-- mandatory=1 → tamamlanana kadar kullanıcının ana ekranında kalıcı uyarı şeridi gösterilir.
CREATE TABLE IF NOT EXISTS user_tasks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    note TEXT,
    mandatory INTEGER NOT NULL DEFAULT 0,     -- 1 = Zorunlu Görev (uyarı şeridi), 0 = Serbest Görev
    recurring INTEGER NOT NULL DEFAULT 0,     -- 1 = tekrarlı (haftanın günleri), 0 = tek seferlik (due_day)
    due_day TEXT,                             -- tek seferlik: tarih
    weekdays TEXT,                            -- tekrarlı: haftanın günleri '1,2,3' (Pzt=1..Paz=7); boş = her gün
    task_time TEXT,                           -- görev saati 'HH:MM' (zorunlu alan)
    done_at TEXT,                             -- tek seferlik: işlem anı (tamamlama/red)
    status TEXT,                              -- tek seferlik: 'done' / 'rejected' (NULL = bekliyor)
    reason TEXT,                              -- tek seferlik: red nedeni
    active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_tasks_user ON user_tasks(user_id, active);
CREATE TABLE IF NOT EXISTS user_task_log (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES user_tasks(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',      -- 'done' = yaptım, 'rejected' = reddetti
    done_at TEXT,                             -- işlem anı (tamamlama ya da red zamanı)
    reason TEXT,                              -- red nedeni (opsiyonel)
    note TEXT,
    UNIQUE(task_id, day)
);
-- Anket modülü: Sistem Yöneticisi anket açar (sorular), TÜM personel zorunlu cevaplar, yönetici cevapları görür.
-- mandatory=1 → cevaplanana kadar kullanıcının ana ekranında kalıcı uyarı şeridi (zorunlu anket).
CREATE TABLE IF NOT EXISTS surveys (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    mandatory INTEGER NOT NULL DEFAULT 1,     -- 1 = zorunlu (uyarı şeridi), 0 = gönüllü
    anonymous INTEGER NOT NULL DEFAULT 0,     -- 1 = yönetici kimi cevapladığını görmez (yalnız toplamlar)
    active INTEGER NOT NULL DEFAULT 1,         -- 0 = kapalı (yeni cevap alınmaz, sonuç kalır)
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS survey_questions (
    id INTEGER PRIMARY KEY,
    survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL DEFAULT 0,            -- soru sırası
    text TEXT NOT NULL,
    qtype TEXT NOT NULL DEFAULT 'single',      -- 'text' | 'single' | 'multi' | 'rating' (1-5) | 'yesno'
    options TEXT,                              -- single/multi: seçenekler JSON dizisi ["A","B"]
    required INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_survey_q ON survey_questions(survey_id, ord);
-- Bir kullanıcının bir anketi tamamlaması (UNIQUE → tek kez cevaplanır)
CREATE TABLE IF NOT EXISTS survey_responses (
    id INTEGER PRIMARY KEY,
    survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    submitted_at TEXT NOT NULL,
    UNIQUE(survey_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_survey_resp ON survey_responses(survey_id);
CREATE TABLE IF NOT EXISTS survey_answers (
    id INTEGER PRIMARY KEY,
    response_id INTEGER NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES survey_questions(id) ON DELETE CASCADE,
    value TEXT                                 -- text/rating: düz değer; single: seçenek; multi: JSON dizisi
);
CREATE INDEX IF NOT EXISTS idx_survey_ans ON survey_answers(response_id);
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
-- Görev Formu: personelin iş için fabrika DIŞINA çıkış talebi. employee_id = göreve gidecek personel,
-- requested_by = formu dolduran, approver_id = onaylayacak yönetici. Onaylanınca QR çıkış kodu üretilir.
CREATE TABLE IF NOT EXISTS duty_requests (
    id            INTEGER PRIMARY KEY,
    employee_id   INTEGER REFERENCES employees(id),      -- göreve GİDECEK personel
    requested_by  INTEGER NOT NULL REFERENCES users(id), -- formu dolduran
    approver_id   INTEGER REFERENCES users(id),          -- onaylayacak yönetici
    destination   TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    depart_at     TEXT NOT NULL,                         -- çıkış (ISO)
    return_at     TEXT,                                  -- tahmini dönüş (ISO)
    vehicle_plate TEXT,
    status        TEXT NOT NULL DEFAULT 'BEKLIYOR',      -- BEKLIYOR | ONAYLANDI | REDDEDILDI | IPTAL
    decided_by    INTEGER REFERENCES users(id),
    decided_at    TEXT,
    decision_note TEXT,
    seen_at       TEXT,                                  -- talep eden kararı gördü
    source        TEXT NOT NULL DEFAULT 'manual',        -- 'manual' (Kişisel görev formu) | 'field' (saha görevi araç çıkışı; onaysız, otomatik ONAYLANDI)
    field_task_id INTEGER REFERENCES field_tasks(id),    -- saha görevi araç çıkış grubunun bağlı olduğu saha görevi
    returned_at   TEXT,                                  -- grup fabrikaya geri döndü (güvenlik giriş yaptı); dolunca "Görevde"den düşer
    return_kind   TEXT,                                  -- dönüş türü: 'sirket' (şirkete döndü, araç içeri girer) | 'bitir' (görevi bitir, araca dokunulmaz)
    flew          INTEGER,                               -- görevi bitirirken: uçuş yapıldı mı? (1 evet / 0 hayır); stok devri ileride bu veriyi kullanacak
    complete_note TEXT,                                  -- görevi bitirme açıklaması (uçulmadıysa zorunlu)
    exited_at     TEXT,                                  -- QR ile çıkış yapıldığı an (ilk okutma); dolunca "Görevde"ye geçer
    created_at    TEXT NOT NULL
);
-- Görev formunda göreve gidecek personel (çoklu; görev araca/göreve özel, bir araçta birden çok kişi).
CREATE TABLE IF NOT EXISTS duty_people (
    id          INTEGER PRIMARY KEY,
    duty_id     INTEGER NOT NULL REFERENCES duty_requests(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    UNIQUE (duty_id, employee_id)
);
-- Personel çıkışları: güvenlik QR çıkış kodunu okutunca kaydedilen hafif giriş (araç kayıtlarından AYRI).
CREATE TABLE IF NOT EXISTS person_exits (
    id          INTEGER PRIMARY KEY,
    person_name TEXT,
    kind        TEXT NOT NULL,                           -- leave | duty
    ref_id      INTEGER,                                 -- leave_requests / duty_requests id
    scanned_by  INTEGER REFERENCES users(id),            -- okutan güvenlik görevlisi
    at          TEXT NOT NULL
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
    last_seen       TEXT,
    maint_since     TEXT,         -- BAKIM modu: bakıma alındığı an (NULL = hatta); bakımdaki süre arıza/kayıp sayılmaz
    arge_since      TEXT          -- AR-GE modu: Ar-Ge'ye alındığı an (NULL = hatta); Ar-Ge'deki süre hata/arıza sayılmaz
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
-- Görevdeki her uçak (sipariş) YA DA dron (Dron Envanteri) için bir uçuş. launch: ARAC_USTU | RAMPA
-- order_id (üretimden gelen uçak) ve drone_id (dron envanteri) birbirinin yerine geçer; en az biri dolu olmalıdır.
-- Bağlantı bilgileri (Dron Yönetimi Faz 1) UÇUŞ düzeyindedir: bridge_id (Dron Köprüleri), sysid (MAVLink sistem kimliği),
-- link (JSON: {type:'serial'|'tcp'|'udp', host?, port?, serial?, baud?} — köprünün drona yerel bağlantısı).
CREATE TABLE IF NOT EXISTS field_flights (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES field_tasks(id) ON DELETE CASCADE,
    order_id   INTEGER REFERENCES orders(id),
    drone_id   INTEGER REFERENCES drone_drones(id) ON DELETE SET NULL,
    launch     TEXT,
    note       TEXT,
    updated_at TEXT,
    bridge_id  INTEGER REFERENCES drone_bridges(id) ON DELETE SET NULL,
    sysid      INTEGER,
    link       TEXT,
    UNIQUE (task_id, order_id),
    UNIQUE (task_id, drone_id)
);
-- Dron Yönetimi paketi (Saha Yönetimi alt modülleri field.drones / field.live / field.routes / field.bridges):
-- dron envanteri (kuyruk no D-0001), telemetri köprüleri (pilotun cihazındaki yazılım; sunucuya dışa doğru WebSocket),
-- köprü oturumları, rota merkezleri / rotalar / ara noktalar. Canlı telemetri DOSYAYA yazılır (tlog_path); DB'de yalnız oturum meta.
CREATE TABLE IF NOT EXISTS drone_bridges (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    key_enc     TEXT,                                   -- eşleştirme anahtarı (cameras.encrypt ile şifreli); yalnız üretim anında düz gösterilir
    platform    TEXT,                                   -- android | windows | linux | other
    owner_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- sahibi pilot
    host        TEXT,                                   -- son bağlanan cihaz adı (köprü bildirir)
    bridge_ver  TEXT,
    status      TEXT NOT NULL DEFAULT 'CEVRIMDISI',     -- CEVRIMDISI | CEVRIMICI
    last_seen   TEXT,
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
-- Dron kaydında BAĞLANTI BİLGİSİ TUTULMAZ (Faz 1): köprü / sysid / seri-tcp-udp ayarları saha görevindeki uçuşta (field_flights) seçilir.
CREATE TABLE IF NOT EXISTS drone_drones (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,                   -- kuyruk no: db.next_code(conn, 'drone_drones', 'code', 'D') → D-0001
    name        TEXT NOT NULL,
    serial      TEXT UNIQUE COLLATE NOCASE,
    model       TEXT,
    protocol    TEXT NOT NULL DEFAULT 'mavlink',        -- mavlink | sanal (sunucu içi simülatör) | dji
    order_id    INTEGER REFERENCES orders(id) ON DELETE SET NULL,          -- üretimden gelen uçak bağı (isteğe bağlı)
    pilot_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,           -- sorumlu pilot
    status      TEXT NOT NULL DEFAULT 'AKTIF',          -- AKTIF | BAKIMDA | ARIZALI | PASIF
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS drone_bridge_sessions (
    id          INTEGER PRIMARY KEY,
    bridge_id   INTEGER NOT NULL REFERENCES drone_bridges(id) ON DELETE CASCADE,
    drone_id    INTEGER REFERENCES drone_drones(id) ON DELETE SET NULL,
    task_id     INTEGER REFERENCES field_tasks(id) ON DELETE SET NULL,
    flight_id   INTEGER REFERENCES field_flights(id) ON DELETE SET NULL,
    started_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,                                   -- NULL: açık oturum
    status      TEXT NOT NULL DEFAULT 'ACIK',           -- ACIK | KAPANDI | KOPTU | KESILDI (sunucu yeniden başladı)
    packets     INTEGER NOT NULL DEFAULT 0,
    last_seen   TEXT,
    tlog_path   TEXT,                                   -- canlı telemetri kaydı (UPLOAD_DIR altında), flight_logs'a düşmez
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_drone_bridge_sessions_bridge ON drone_bridge_sessions(bridge_id, started_at);
CREATE INDEX IF NOT EXISTS ix_drone_bridge_sessions_open ON drone_bridge_sessions(ended_at);
CREATE TABLE IF NOT EXISTS drone_route_centers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    lat         REAL NOT NULL, lon REAL NOT NULL, alt REAL,
    location_id INTEGER REFERENCES field_locations(id) ON DELETE SET NULL,
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
-- Uçuş Simülatörü görsel model kütüphanesi (docs/ucus-simulatoru.md §12): simülatöre yüklenen ya da tasarım modülünden eklenen 3B gövdeler.
-- Dahili (prosedürel/GLB) modeller tabloda değil koddadır (flightsim_models.BUILTIN; kimlik 'builtin:<ad>'). Dosyalar DATA_DIR/sim_models/<id>/.
CREATE TABLE IF NOT EXISTS drone_sim_models (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'upload',          -- upload (simülatöre yüklendi) | design (tasarım sürümü dosyası; source_ref = design_drawing_versions.id)
    source_ref  INTEGER,
    type        TEXT NOT NULL,                           -- dron tipi (multirotor | hexarotor | helikopter | sabit_kanat | vtol)
    file_path   TEXT,                                    -- özgün dosya: upload → DATA_DIR göreli (sim_models/<id>/orijinal.<ext>); design → UPLOAD_DIR göreli
    glb_path    TEXT,                                    -- tarayıcıda dönüştürülüp PUT edilen GLB (DATA_DIR göreli); boşsa ready=false
    thumb_path  TEXT,                                    -- 320×240 PNG (DATA_DIR göreli)
    orient_json TEXT,                                    -- {forward, up, scale, rot, prop:{mode, pos, r}} (flightsim_models.orient_dogrula)
    has_prop    INTEGER NOT NULL DEFAULT 0,              -- modelde döndürülecek pervane düğümü var (prop/propeller/rotor adlı)
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drone_sim_models_type ON drone_sim_models(type);
-- CAYSIM istemcileri (docs/caysim-api.md §1, §9): Unreal/Cesium masaüstü görselleştirme istemcisi; drone_bridges kalıbı — anahtar şifreli,
-- kod (<domain>/<key>) yalnız üretim anında gösterilir; istemcinin açtığı oturumların sahibi owner_id.
-- Uçuş Simülatörü olayları (docs/ucus-simulatoru.md §18): çarpışma koordinatı, görev bitiş noktası ve oturum özet raporu (detail JSON = rapor).
CREATE TABLE IF NOT EXISTS drone_sim_events (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL,                       -- SimSession.id (sunucu yeniden başlayınca 1'den başlar; satır kimliği oturum belleğinde tutulur)
    owner_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    type        TEXT NOT NULL,                          -- crash | warning (autopilot_detect) | mission_end | summary
    lat REAL, lon REAL, alt_msl REAL, alt_rel REAL,
    t           REAL,                                   -- Unix sn (olay anı)
    speed       REAL,                                   -- m/s (yer hızı)
    mode        TEXT,
    detail      TEXT,                                   -- JSON: crash {reason, target_seq, mission_end, deviation_m…} · mission_end {source, count, end} · summary = rapor
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drone_sim_events_type ON drone_sim_events(type, id);
-- Uçuş Simülatörü KAYITLARI (docs/ucus-simulatoru.md §21): her oturum (canlı SITL ya da kayıttan oynatma) kapanışında bir satır — özet rapor,
-- .bin uçuş logu, ekran kaydı (video), son parametre dökümü (.param) ve SITL scripts/ içeriği (zip) ile İLİŞKİ. Dosyalar DATA_DIR/sim_runs/<id>/.
CREATE TABLE IF NOT EXISTS drone_sim_runs (
    id              INTEGER PRIMARY KEY,
    session_id      INTEGER NOT NULL,                   -- SimSession.id (sunucu yeniden başlayınca 1'den başlar)
    session_kimlik  INTEGER,                            -- SITL kimliği (KIMLIK_TABANI + id); kayıttan oynatmada NULL
    owner_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    owner_name      TEXT,
    drone_id        INTEGER REFERENCES drone_drones(id) ON DELETE SET NULL,
    drone_code      TEXT,
    type            TEXT,                               -- multirotor | hexarotor | helikopter | sabit_kanat | vtol
    model_id        TEXT,                               -- görsel model kimliği ('builtin:caymaz' | '12')
    model_name      TEXT,
    center_id       INTEGER REFERENCES drone_route_centers(id) ON DELETE SET NULL,
    center_name     TEXT,                               -- merkez adı (kayıttan oynatmada log adı)
    lat REAL, lon REAL,
    world           TEXT,                               -- JSON: dünya ayarları
    launch          TEXT,                               -- JSON: kalkış yöntemi (sabit kanat)
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_s      INTEGER,
    mode            TEXT NOT NULL DEFAULT 'sitl',       -- sitl | replay
    result          TEXT NOT NULL DEFAULT 'tamam',      -- tamam | carpisma | hata
    end_reason      TEXT,                               -- kapatildi | bosta | sure | sunucu_kapaniyor | hata
    crash_count     INTEGER NOT NULL DEFAULT 0,
    summary_event_id INTEGER REFERENCES drone_sim_events(id) ON DELETE SET NULL,
    bin_log_id      INTEGER REFERENCES flight_logs(id) ON DELETE SET NULL,     -- kapanışta kaydedilen SITL .BIN (§19)
    source_log_id   INTEGER REFERENCES flight_logs(id) ON DELETE SET NULL,     -- kayıttan oynatma kaynağı
    video_rec_id    TEXT,                               -- flightsim_rec kimliği (sim_rec/<id>.webm; saklanan ya da yarım)
    video_post_id   INTEGER,                            -- Şirketten Haberler paylaşımı (feed_posts.id)
    video_path      TEXT,                               -- paylaşılan videonun UPLOAD_DIR göreli yolu (feed/<ad>.webm)
    params_path     TEXT,                               -- DATA_DIR göreli: sim_runs/<id>/params.param (Mission Planner AD,DEĞER)
    params_count    INTEGER NOT NULL DEFAULT 0,
    scripts_path    TEXT,                               -- DATA_DIR göreli: sim_runs/<id>/scripts.zip (SITL scripts/ içeriği)
    scripts_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drone_sim_runs_started ON drone_sim_runs(started_at);
CREATE INDEX IF NOT EXISTS ix_drone_sim_runs_owner ON drone_sim_runs(owner_id);
CREATE INDEX IF NOT EXISTS ix_drone_sim_runs_center ON drone_sim_runs(center_id);
CREATE TABLE IF NOT EXISTS drone_sim_clients (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    key_enc     TEXT,                                   -- Bearer anahtarı (cameras.encrypt ile şifreli)
    platform    TEXT,                                   -- windows | linux | macos | other
    owner_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    host        TEXT,                                   -- son bağlanan bilgisayar adı (istemci bildirir)
    client_ver  TEXT,
    status      TEXT NOT NULL DEFAULT 'CEVRIMDISI',     -- CEVRIMDISI | CEVRIMICI
    last_seen   TEXT,
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS drone_routes (
    id          INTEGER PRIMARY KEY,
    center_id   INTEGER REFERENCES drone_route_centers(id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'line',           -- line | loop | survey
    cruise_alt  REAL, cruise_speed REAL,
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_drone_routes_center ON drone_routes(center_id);
CREATE TABLE IF NOT EXISTS drone_waypoints (
    id          INTEGER PRIMARY KEY,
    route_id    INTEGER NOT NULL REFERENCES drone_routes(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    lat         REAL NOT NULL, lon REAL NOT NULL, alt REAL,
    action      TEXT NOT NULL DEFAULT 'waypoint',       -- waypoint | loiter | land | rtl | takeoff
    hold_s      REAL,
    note        TEXT,
    UNIQUE (route_id, ord)
);
CREATE INDEX IF NOT EXISTS ix_drone_waypoints_route ON drone_waypoints(route_id, ord);
-- GÖKTUNGU kalkış kontrol listesi kaydı (kalkis_kontrolleri): kayıt + takeoff tek sunucu işlemi; pilot ve zaman sunucuda damgalanır
CREATE TABLE IF NOT EXISTS drone_takeoff_checks (
    id                INTEGER PRIMARY KEY,
    task_id           INTEGER REFERENCES field_tasks(id) ON DELETE SET NULL,
    bridge_id         INTEGER REFERENCES drone_bridges(id) ON DELETE SET NULL,
    drone_id          INTEGER REFERENCES drone_drones(id) ON DELETE SET NULL,   -- sanal dron
    sysid             INTEGER NOT NULL,
    user_id           INTEGER REFERENCES users(id),
    pilot_name        TEXT,
    vehicle_type      INTEGER,
    vehicle_type_name TEXT,
    alt_m             REAL,
    item_count        INTEGER NOT NULL DEFAULT 0,
    yes_count         INTEGER NOT NULL DEFAULT 0,
    full_ok           INTEGER NOT NULL DEFAULT 0,
    items             TEXT NOT NULL,                  -- JSON [{sira, anahtar, soru, grup, cevap, zorunlu, kaynak}]
    takeoff_sent      INTEGER,                        -- akış sonucu: 1 iletildi / 0 iletilmedi / NULL sürüyor
    takeoff_error     TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_drone_takeoff_checks_task ON drone_takeoff_checks(task_id);
-- Sanal dron (SITL) kalıcı parametreleri (app/drone_params.py): HEPGO'dan ya da Mission Planner'dan değiştirilen her parametre dron
-- kaydına yazılır; aynı dronla SITL yeniden açılınca varsayilan.parm + PARAM_SET ile geri yüklenir. source: hepgo | mp | sitl
CREATE TABLE IF NOT EXISTS drone_sitl_params (
    drone_id    INTEGER NOT NULL REFERENCES drone_drones(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,                        -- ArduPilot parametre adı (≤ 16 karakter, büyük harf)
    value       REAL NOT NULL,
    ptype       INTEGER,                              -- MAV_PARAM_TYPE (1..10); PARAM_VALUE'dan öğrenilir
    updated_at  TEXT NOT NULL,
    updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source      TEXT NOT NULL DEFAULT 'hepgo',        -- hepgo (panel/içe aktarma) | mp (Mission Planner PARAM_SET) | sitl (araçta kendiliğinden değişti)
    PRIMARY KEY (drone_id, name)
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
-- Kişinin ek e-posta adresleri (birincil adres kişinin kendi email alanında) — app/person_emails.py
CREATE TABLE IF NOT EXISTS person_emails (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,              -- company (company_people) | employee (employees)
    ref_id     INTEGER NOT NULL,
    email      TEXT NOT NULL,              -- küçük harf
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,   -- bu adresin firması (yalnız kind=company; boş: firmasız)
    created_at TEXT NOT NULL,
    UNIQUE (kind, ref_id, email)
);
CREATE INDEX IF NOT EXISTS person_emails_email ON person_emails (email);
CREATE TABLE IF NOT EXISTS company_people (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,   -- birincil adresin firması; boş: firmasız kişi
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
    flight_id   INTEGER REFERENCES field_flights(id) ON DELETE SET NULL,
    source      TEXT NOT NULL DEFAULT 'UPLOAD'   -- UPLOAD (elle yükleme) | BRIDGE (dron köprüsünden uçuş sonrası .bin)
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
-- Mail v2 (Outlook gibi): kullanıcı başına birden çok hesap — Gmail / Outlook / Yandex / iCloud / Yahoo / özel IMAP / POP3.
-- auth_type: password (uygulama şifresi) | google | microsoft (OAuth yenileme jetonu). secret şifreli saklanır.
-- Mail önbelleği (app/mail_cache.py): liste özeti, okunan ileti ve katılımcılar (CRM › firma › Mailler)
CREATE TABLE IF NOT EXISTS mail_cache_state (
    box_id      INTEGER NOT NULL REFERENCES mail_boxes(id) ON DELETE CASCADE,
    folder      TEXT NOT NULL,
    uidvalidity INTEGER NOT NULL,
    PRIMARY KEY (box_id, folder)
);
CREATE TABLE IF NOT EXISTS mail_cache (
    box_id    INTEGER NOT NULL REFERENCES mail_boxes(id) ON DELETE CASCADE,
    folder    TEXT NOT NULL,
    uid       INTEGER NOT NULL,
    date      TEXT,
    seen      INTEGER NOT NULL DEFAULT 0,
    starred   INTEGER NOT NULL DEFAULT 0,
    addrs     TEXT NOT NULL DEFAULT '',      -- ' a@x.com b@y.com ' tüm katılımcılar (küçük harf)
    summary   TEXT NOT NULL,                 -- liste satırı (JSON)
    body      TEXT,                          -- okunmuş ileti (JSON), 2 MB'a kadar
    cached_at TEXT NOT NULL,
    PRIMARY KEY (box_id, folder, uid)
);
CREATE INDEX IF NOT EXISTS mail_cache_date ON mail_cache (box_id, date);
CREATE TABLE IF NOT EXISTS mail_boxes (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email         TEXT NOT NULL,
    login         TEXT,                          -- sunucu kullanıcı adı (boşsa e-posta)
    name          TEXT,                          -- gönderen adı
    provider      TEXT NOT NULL DEFAULT 'imap',  -- gmail | outlook | yandex | icloud | yahoo | imap | pop3
    auth_type     TEXT NOT NULL DEFAULT 'password',
    secret        TEXT NOT NULL,
    imap_host     TEXT, imap_port INTEGER,
    pop_host      TEXT, pop_port INTEGER,
    smtp_host     TEXT, smtp_port INTEGER, smtp_security TEXT,   -- ssl | starttls
    save_sent     INTEGER NOT NULL DEFAULT 1,    -- gönderileni sunucudaki Gönderilenler'e kaydet (Gmail / Outlook kendisi kaydeder)
    signature     TEXT,
    color         TEXT,
    sort          INTEGER NOT NULL DEFAULT 0,
    auto_import   INTEGER NOT NULL DEFAULT 0,    -- gelen eklerini Evrak Yönetimi'ne kaydet
    sync_calendar INTEGER NOT NULL DEFAULT 1,
    sync_contacts INTEGER NOT NULL DEFAULT 1,
    last_uid      INTEGER, uid_validity TEXT,
    last_ok       TEXT, last_error TEXT,
    sync_error  TEXT,                      -- takvim / kişi eşitlemesinin son hatası (Google / Microsoft)
    last_sync     TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mail_boxes_user ON mail_boxes(user_id, sort);
CREATE TABLE IF NOT EXISTS mail_pop_seen (       -- POP3: sunucuda bayrak olmadığı için okundu bilgisi yerelde
    box_id INTEGER NOT NULL REFERENCES mail_boxes(id) ON DELETE CASCADE,
    uidl   TEXT NOT NULL,
    PRIMARY KEY (box_id, uidl)
);
-- Kişisel rehber (Rehber › Kişilerim): yalnız sahibi görür. Kaynak: mail yazışmaları, Google / Outlook kişileri, elle.
CREATE TABLE IF NOT EXISTS personal_contacts (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source     TEXT NOT NULL DEFAULT 'manual',   -- mail | google | microsoft | manual
    ext_id     TEXT NOT NULL,                    -- kaynaktaki kimlik (mail: e-posta adresi)
    name       TEXT,
    email      TEXT,
    phone      TEXT,
    company    TEXT,
    title      TEXT,
    note       TEXT,
    hits       INTEGER NOT NULL DEFAULT 0,       -- yazışma sayısı (otomatik tamamlama sırası)
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (user_id, source, ext_id)
);
-- Kişisel takvime mail hesaplarından gelen öğeler (davet ICS, Google / Outlook takvimi) — yalnız sahibi görür
CREATE TABLE IF NOT EXISTS personal_events (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    box_id      INTEGER REFERENCES mail_boxes(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,                  -- ics | google | microsoft
    ext_id      TEXT NOT NULL,
    title       TEXT,
    starts_at   TEXT NOT NULL,
    ends_at     TEXT,
    all_day     INTEGER NOT NULL DEFAULT 0,
    location    TEXT,
    description TEXT,
    organizer   TEXT,
    status      TEXT,                           -- confirmed | tentative | cancelled
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, source, ext_id)
);
CREATE INDEX IF NOT EXISTS ix_personal_events ON personal_events(user_id, starts_at);
-- Sosyal medya (Kişisel Ayarlar › Sosyal Medya): bağlanan hesapların paylaşımları Şirketten Haberler'de yalnız sahibine görünür
CREATE TABLE IF NOT EXISTS social_accounts (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,                 -- rss | youtube | bluesky | mastodon | instagram | x | facebook | tiktok
    handle       TEXT NOT NULL,                 -- kullanıcı adı / kanal / adres
    feed_url     TEXT,
    display_name TEXT,
    avatar       TEXT,
    token        TEXT,                          -- OAuth (şifreli)
    show_in_feed INTEGER NOT NULL DEFAULT 1,
    last_sync    TEXT,
    last_error   TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS social_posts (
    id         INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
    ext_id     TEXT NOT NULL,
    text       TEXT,
    url        TEXT,
    media      TEXT,                            -- resim / küçük resim adresi
    media_kind TEXT,                            -- image | video
    posted_at  TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE (account_id, ext_id)
);
CREATE INDEX IF NOT EXISTS ix_social_posts ON social_posts(account_id, posted_at);
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

-- Yüz ile giriş (Face ID tarzı): kullanıcı başına tek kayıt; data = cameras.encrypt(JSON {embeddings:[[128 float]…], slots})
-- (çok açıdan 5–18 gömme, SFace 128-d). Ham kare / kırpık saklanmaz. mode: face | face_pin (yüz + PIN). Bkz. app/facelogin.py
CREATE TABLE IF NOT EXISTS user_face (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,
    model_ver  TEXT NOT NULL,
    mode       TEXT NOT NULL DEFAULT 'face',
    enabled    INTEGER NOT NULL DEFAULT 1,
    count      INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
    visitor_id  INTEGER REFERENCES visitors(id) ON DELETE SET NULL,
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
-- Kameralarda görülen yüzler bu izlerle eşleştirilir.
-- subject_type: 'user' (personel) | 'person' (firma kişisi) | 'family' (aile üyesi) | 'visitor' (ziyaretçi).
CREATE TABLE IF NOT EXISTS face_enroll (
    id           INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    person_id    INTEGER REFERENCES company_people(id) ON DELETE CASCADE,
    family_id    INTEGER REFERENCES family_members(id) ON DELETE CASCADE,
    visitor_id   INTEGER REFERENCES visitors(id) ON DELETE CASCADE,
    name         TEXT,                       -- (eski) serbest ad yer tutucu
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
CREATE TABLE IF NOT EXISTS tools_mt_store (            -- Araçlar › Master Tool web sürümleri: kullanıcı başına uygulama verisi (tools_mt.py)
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    app        TEXT NOT NULL,                          -- sshmaster | ftpmaster | sqlmaster | notepadmaster | convertmaster | volfai
    key        TEXT NOT NULL,                          -- store | secrets | history | local …
    json       TEXT NOT NULL,                          -- masaüstü uygulamadaki JSON şemasıyla birebir
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, app, key)
);
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
        conn.commit()
        _company_people_free(conn)


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
    """field_flights tablosunu şemadaki tanımla yeniden kurar: (1) eski geçişte yabancı anahtarsız oluşmuşsa
    (görev silinince uçuşları da silinsin), (2) Dron Yönetimi için drone_id sütunu yoksa (order_id NULL olabilir;
    SQLite'ta NOT NULL kaldırmak tablo yeniden kurmadır). İdempotent: ikinci açılışta hiçbir şey yapmaz.
    Görevi olmayan artık uçuş kayıtları temizlenir. flight_logs / flight_videos referansları korunur (legacy_alter_table)."""
    cols = {r[1] for r in conn.execute('PRAGMA table_info(field_flights)')}
    has_fk = conn.execute("SELECT COUNT(*) FROM pragma_foreign_key_list('field_flights')").fetchone()[0]
    if has_fk and 'drone_id' in cols:
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
            order_id   INTEGER REFERENCES orders(id),
            drone_id   INTEGER REFERENCES drone_drones(id) ON DELETE SET NULL,
            launch     TEXT,
            note       TEXT,
            updated_at TEXT,
            bridge_id  INTEGER REFERENCES drone_bridges(id) ON DELETE SET NULL,
            sysid      INTEGER,
            link       TEXT,
            UNIQUE (task_id, order_id),
            UNIQUE (task_id, drone_id)
        );
        INSERT INTO field_flights (id, task_id, order_id, launch, note, updated_at)
            SELECT id, task_id, order_id, launch, note, updated_at FROM field_flights_old;
        DROP TABLE field_flights_old;
    ''')
    conn.execute('PRAGMA legacy_alter_table = OFF')
    conn.execute('PRAGMA foreign_keys = ON')


VEHICLE_COLS = [
    ('brand', 'TEXT'), ('model', 'TEXT'), ('year', 'INTEGER'), ('body_type', 'TEXT'), ('fuel_type', 'TEXT'), ('color', 'TEXT'),
    ('vin', 'TEXT'), ('engine_no', 'TEXT'), ('photo', 'TEXT'),
    ('ownership', "TEXT NOT NULL DEFAULT 'owned'"),            # owned (satın alındı) | leased (kiralık)
    ('purchase_date', 'TEXT'), ('purchase_price', 'REAL'), ('seller_id', 'INTEGER'), ('purchase_doc', 'TEXT'),
    ('asset_account', 'TEXT'),                                  # muhasebe sabit kıymet hesabı (254.xx)
    ('lessor_id', 'INTEGER'), ('lease_no', 'TEXT'), ('lease_start', 'TEXT'), ('lease_end', 'TEXT'),
    ('lease_monthly', 'REAL'), ('lease_currency', "TEXT DEFAULT 'TRY'"), ('lease_km_limit', 'REAL'), ('lease_includes', 'TEXT'),
    ('start_km', 'REAL'), ('inspection_date', 'TEXT'), ('traffic_ins_date', 'TEXT'), ('kasko_date', 'TEXT'),
    ('next_service_date', 'TEXT'), ('next_service_km', 'REAL'),
    ('match_keys', 'TEXT'),                                     # muhasebe hareketi eşleştirme anahtar kelimeleri (virgülle)
    ('exit_date', 'TEXT'), ('exit_reason', 'TEXT'), ('note', 'TEXT'), ('updated_at', 'TEXT'),
]


def _company_people_free(conn):
    """Kişi firmadan bağımsız: company_people.company_id isteğe bağlı (firmasız kişi) ve firma silinince kişi silinmez
    (ON DELETE SET NULL). SQLite sütun kısıtını değiştiremediği için tablo yeniden kurulur (veriler, dizinler ve diğer
    tabloların bu tabloya bağları korunur). Bir kez çalışır."""
    import re
    cols = {r[1]: r for r in conn.execute('PRAGMA table_info(company_people)')}
    if not cols or not cols['company_id'][3]:   # notnull değilse zaten taşınmış
        return
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'company_people'").fetchone()[0]
    new_sql, n = re.subn(r'company_id\s+INTEGER\s+NOT\s+NULL\s+REFERENCES\s+companies\(id\)\s+ON\s+DELETE\s+CASCADE',
                         'company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL', sql)
    if n != 1:
        raise RuntimeError('company_people taşınamadı: beklenmeyen tablo tanımı')
    new_sql = new_sql.replace('CREATE TABLE company_people', 'CREATE TABLE company_people_yeni', 1)
    indexes = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'company_people' AND sql IS NOT NULL")]
    before = conn.execute('SELECT COUNT(*) FROM company_people').fetchone()[0]
    conn.commit()
    # Tablo yeniden kurulmadan önce tam veritabanı yedeği (servis kullanıcısıyla; her firma kendi veri klasörüne)
    bdir = config.DATA_DIR / 'backups' / 'migration'
    bdir.mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(bdir / f'before-company-people-{datetime.now():%Y%m%d-%H%M%S}.db')
    try:
        conn.backup(dst)
    finally:
        dst.close()
    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.executescript('BEGIN;\n' + new_sql + ';\n'
                           'INSERT INTO company_people_yeni SELECT * FROM company_people;\n'
                           'DROP TABLE company_people;\n'
                           'ALTER TABLE company_people_yeni RENAME TO company_people;\n'
                           + ''.join(f'{i};\n' for i in indexes) + 'COMMIT;')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')
    after = conn.execute('SELECT COUNT(*) FROM company_people').fetchone()[0]
    bad = conn.execute('PRAGMA foreign_key_check').fetchall()
    if after != before or bad:
        raise RuntimeError(f'company_people taşıma denetimi başarısız: {before} → {after}, bağ hatası {len(bad)}')


def _migrate(conn):
    """Eski veritabanlarını güncel şemaya taşır (ürünlerden önce açılmış siparişler CAYMAZ'a bağlanır)."""
    # Esnaf (bakkal/berber/lokanta) modülleri: bölümler, masalar, hizmetler, rezervasyon, adisyon.
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS shop_sections (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'room',      -- room (berber oda) | hall (lokanta salon/kat)
            smoking INTEGER NOT NULL DEFAULT 0,     -- lokanta: sigara içilen bölüm
            sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shop_tables (
            id INTEGER PRIMARY KEY,
            section_id INTEGER REFERENCES shop_sections(id) ON DELETE SET NULL,
            name TEXT NOT NULL, shape TEXT NOT NULL DEFAULT 'square',   -- square | round
            seats INTEGER NOT NULL DEFAULT 4, pos_x REAL, pos_y REAL,
            waiter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_shop_tables_sec ON shop_tables(section_id);
        CREATE TABLE IF NOT EXISTS shop_services (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL NOT NULL DEFAULT 0,
            duration_min INTEGER NOT NULL DEFAULT 30, staff_pct REAL NOT NULL DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shop_service_staff (
            service_id INTEGER NOT NULL REFERENCES shop_services(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (service_id, user_id));
        CREATE TABLE IF NOT EXISTS shop_reservations (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'staff',   -- staff (berber) | table (lokanta)
            staff_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            table_id INTEGER REFERENCES shop_tables(id) ON DELETE SET NULL,
            service_id INTEGER REFERENCES shop_services(id) ON DELETE SET NULL,
            customer TEXT, phone TEXT, party INTEGER,
            starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ONAYLI',   -- ONAYLI | GELMEDI | TAMAM | IPTAL
            note TEXT, source TEXT NOT NULL DEFAULT 'staff',   -- staff | public
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_shop_resv_time ON shop_reservations(starts_at);
        CREATE TABLE IF NOT EXISTS shop_orders (
            id INTEGER PRIMARY KEY,
            table_id INTEGER REFERENCES shop_tables(id) ON DELETE SET NULL,
            merged_with INTEGER, party INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | PAID
            opened_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            opened_at TEXT NOT NULL, closed_at TEXT);
        CREATE INDEX IF NOT EXISTS ix_shop_orders_tbl ON shop_orders(table_id, status);
        CREATE TABLE IF NOT EXISTS shop_order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES shop_orders(id) ON DELETE CASCADE,
            seat INTEGER NOT NULL DEFAULT 1,
            product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1, price REAL NOT NULL DEFAULT 0,
            note TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_shop_oi_order ON shop_order_items(order_id);
        -- Beta geri bildirim: firma kullanıcısı hata/tavsiye/diğer bildirir; merkeze (Veilox) iletilir, merkez cevabı buraya yazılır.
        CREATE TABLE IF NOT EXISTS beta_feedback (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name TEXT,
            category TEXT NOT NULL DEFAULT 'diger',   -- hata | tavsiye | diger
            message TEXT NOT NULL,
            screenshot TEXT,                          -- opsiyonel data URI (ekran görüntüsü)
            page TEXT,                                -- bildirim anındaki ekran (hash)
            status TEXT NOT NULL DEFAULT 'NEW',       -- NEW | SENT | ANSWERED
            reply TEXT, replied_at TEXT,
            remote_id INTEGER,                        -- merkezdeki kaydın id'si (federasyon senkronu)
            created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_beta_fb_user ON beta_feedback(user_id);
    ''')
    sess_cols = {r[1] for r in conn.execute('PRAGMA table_info(sessions)')}
    if 'device' not in sess_cols:   # istemci türü (android_app / ios_app / web / web_mobile) + ham User-Agent
        conn.execute('ALTER TABLE sessions ADD COLUMN device TEXT')
        conn.execute('ALTER TABLE sessions ADD COLUMN user_agent TEXT')
    user_cols = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    if 'last_seen' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN last_seen TEXT')
    if 'prefs' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN prefs TEXT')
    if 'deleted_at' not in user_cols:   # silinen ama geçmiş kayıtlarda adı geçen kullanıcılar
        conn.execute('ALTER TABLE users ADD COLUMN deleted_at TEXT')
    if 'email' not in user_cols:        # "şifremi unuttum" e-posta sıfırlaması + bildirim için
        conn.execute('ALTER TABLE users ADD COLUMN email TEXT')
        try:   # personel kaydındaki e-postadan doldur (varsa)
            conn.execute("""UPDATE users SET email = (SELECT e.email FROM employees e
                            WHERE e.user_id = users.id AND e.email IS NOT NULL AND e.email <> '' LIMIT 1)
                            WHERE email IS NULL""")
        except Exception:   # noqa: BLE001
            pass
    conn.execute('''CREATE TABLE IF NOT EXISTS password_resets (
        id         INTEGER PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code_hash  TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts   INTEGER NOT NULL DEFAULT 0,
        used       INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )''')
    tm_cols = {r[1] for r in conn.execute('PRAGMA table_info(team_meetings)')}
    for col in ('started_at', 'ended_at', 'process_status', 'process_error', 'processed_at'):   # toplantı ekranı ve özet
        if tm_cols and col not in tm_cols:
            conn.execute(f'ALTER TABLE team_meetings ADD COLUMN {col} TEXT')
    inv_cols = {r[1] for r in conn.execute('PRAGMA table_info(team_meeting_invites)')}
    for col in ('joined_at', 'last_seen'):   # toplantı ekranına katılım
        if inv_cols and col not in inv_cols:
            conn.execute(f'ALTER TABLE team_meeting_invites ADD COLUMN {col} TEXT')
    mb_cols = {r[1] for r in conn.execute('PRAGMA table_info(mail_boxes)')}
    if mb_cols and 'sync_error' not in mb_cols:   # takvim / kişi eşitleme hatası (ör. People API kapalı) görünsün
        conn.execute('ALTER TABLE mail_boxes ADD COLUMN sync_error TEXT')
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
    if 'support_until' not in user_cols:   # merkez destek: onaylı geçici master-benzeri oturumun bitiş zamanı
        conn.execute('ALTER TABLE users ADD COLUMN support_until TEXT')
    # KVKK: açık rıza kaydına sürüm (giriş onayı sürüm değişince yeniden istenir)
    kc_cols = {r[1] for r in conn.execute('PRAGMA table_info(kvkk_consent)')}
    if kc_cols and 'version' not in kc_cols:
        conn.execute('ALTER TABLE kvkk_consent ADD COLUMN version TEXT')
    # Sekreterya misafir KVKK imzası (parmakla; şirkette video kayıt olduğu için aydınlatma + açık rıza)
    gv_cols = {r[1] for r in conn.execute('PRAGMA table_info(guest_visits)')}
    if 'family_id' not in {r[1] for r in conn.execute('PRAGMA table_info(guest_visit_people)')}:   # gelen kişi personel aile üyesi olabilir
        conn.execute('ALTER TABLE guest_visit_people ADD COLUMN family_id INTEGER REFERENCES family_members(id) ON DELETE SET NULL')
    if 'kvkk_from_visit' not in {r[1] for r in conn.execute('PRAGMA table_info(guest_visits)')}:   # KVKK imzası önceki ziyaretten devralındı
        conn.execute('ALTER TABLE guest_visits ADD COLUMN kvkk_from_visit INTEGER REFERENCES guest_visits(id) ON DELETE SET NULL')
    for col in ('kvkk_signed_at', 'kvkk_signature', 'kvkk_version'):
        if gv_cols and col not in gv_cols:
            conn.execute(f'ALTER TABLE guest_visits ADD COLUMN {col} TEXT')
    tk_cols = {r[1] for r in conn.execute('PRAGMA table_info(tickets)')}
    for col, ddl in (('first_response_at', 'TEXT'), ('resolved_at', 'TEXT'), ('due_at', 'TEXT'), ('resolve_due_at', 'TEXT'),
                     ('rating', 'INTEGER'), ('rating_note', 'TEXT'), ('tags', 'TEXT'), ('channel', "TEXT NOT NULL DEFAULT 'ticket'"),
                     ('chat_id', 'INTEGER')):   # Destek Merkezi: SLA, memnuniyet, etiket, kanal
        if tk_cols and col not in tk_cols:
            conn.execute(f'ALTER TABLE tickets ADD COLUMN {col} {ddl}')
    # Mail v2: eski tek Gmail hesabı (mail_accounts) çok hesaplı mail_boxes'a bir kez taşınır
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'mail_boxes'").fetchone():
        conn.execute('''INSERT INTO mail_boxes (user_id, email, name, provider, auth_type, secret, imap_host, imap_port, smtp_host, smtp_port,
                        smtp_security, save_sent, signature, auto_import, last_uid, uid_validity, last_ok, last_error, created_at)
                        SELECT user_id, email, name, 'gmail', CASE auth_type WHEN 'oauth' THEN 'google' ELSE 'password' END, secret,
                        'imap.gmail.com', 993, 'smtp.gmail.com', 465, 'ssl', 0, signature, auto_import, last_uid, uid_validity, last_ok, last_error, created_at
                        FROM mail_accounts a WHERE NOT EXISTS (SELECT 1 FROM mail_boxes b WHERE b.user_id = a.user_id AND b.email = a.email)''')
    fv_cols = {r[1] for r in conn.execute('PRAGMA table_info(field_vehicles)')}
    for col, ddl in VEHICLE_COLS:   # Araç Yönetimi: satın alma / kiralama, teknik bilgi, hatırlatma tarihleri
        if fv_cols and col not in fv_cols:
            conn.execute(f'ALTER TABLE field_vehicles ADD COLUMN {col} {ddl}')
    ft_cols = {r[1] for r in conn.execute('PRAGMA table_info(fin_txns)')}
    if ft_cols and 'mikro_project' not in ft_cols:   # Mikro hareketindeki proje kodu (cha_projekodu)
        conn.execute('ALTER TABLE fin_txns ADD COLUMN mikro_project TEXT')
    fl_cols = {r[1] for r in conn.execute('PRAGMA table_info(fin_ledger)')}
    if fl_cols and 'mikro_project' not in fl_cols:   # Mikro muhasebe fişi satırındaki proje kodu (fis_proje_kodu)
        conn.execute('ALTER TABLE fin_ledger ADD COLUMN mikro_project TEXT')
    if ft_cols and 'due_date' not in ft_cols:   # vade (Mikro cha_vade) — nakit akışı / yaşlandırma
        conn.execute('ALTER TABLE fin_txns ADD COLUMN due_date TEXT')
    fc_cols = {r[1] for r in conn.execute('PRAGMA table_info(feed_comments)')}
    if fc_cols and 'parent_id' not in fc_cols:   # yoruma yanıt (tek seviye: yanıtlar ana yorumun altında)
        conn.execute('ALTER TABLE feed_comments ADD COLUMN parent_id INTEGER REFERENCES feed_comments(id) ON DELETE CASCADE')
    if fc_cols:
        conn.execute('CREATE INDEX IF NOT EXISTS ix_feed_comments_parent ON feed_comments(parent_id)')
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
        -- Native mobil bildirim jetonları (Capacitor): Android=FCM, iOS=APNs. Cihaz başına token.
        CREATE TABLE IF NOT EXISTS push_native (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL, token TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_push_native_user ON push_native(user_id);
        -- Mobil uygulamadan gelen konum sinyalleri (arkaplan takibi); en son konum kişi başına saklanır
        CREATE TABLE IF NOT EXISTS location_pings (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lat REAL NOT NULL, lng REAL NOT NULL, accuracy REAL, at TEXT, platform TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_location_pings_user ON location_pings(user_id, id);
        -- Mobil cihaz künyesi (yasal olarak alınabilen teknik bilgiler; kişi başına cihaz bazında en son durum)
        CREATE TABLE IF NOT EXISTS mobile_devices (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            device_id TEXT, platform TEXT, model TEXT, manufacturer TEXT, os_version TEXT,
            app_version TEXT, app_build TEXT, webview TEXT, language TEXT, timezone TEXT,
            screen TEXT, ua TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            UNIQUE(user_id, device_id));
        CREATE INDEX IF NOT EXISTS idx_mobile_devices_user ON mobile_devices(user_id);
        -- Fazla mesai: İK'nın kullanıcıya belirli gün için girdiği ekstra mesai (çarpanla ücretlenir)
        CREATE TABLE IF NOT EXISTS overtime_shifts (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
            multiplier REAL NOT NULL DEFAULT 1.5, note TEXT,
            created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_overtime_user ON overtime_shifts(user_id, date);
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
        -- İSG/KKD kamera denetimi alarmları (Görüntü İşleme entegrasyonu): zorunlu KKD eksik yakalandığında.
        -- FK yok: dağıtık kurulumda fabrika (gx10) yerel DB'sinde de üretilir; isimler bulutta çözülür.
        CREATE TABLE IF NOT EXISTS isg_alarms (
            id INTEGER PRIMARY KEY, camera_id INTEGER, camera_name TEXT,
            subject_type TEXT, user_id INTEGER, person_id INTEGER, family_id INTEGER, visitor_id INTEGER,
            missing TEXT, at TEXT NOT NULL, crop TEXT, frame TEXT,
            acknowledged_by INTEGER, acknowledged_at TEXT, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_isg_alarms_at ON isg_alarms(at);
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
    pe_cols = {r[1] for r in conn.execute('PRAGMA table_info(person_emails)')}
    if pe_cols and 'company_id' not in pe_cols:   # her e-posta adresinin firması (kişi birden çok firmada olabilir)
        conn.execute('ALTER TABLE person_emails ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL')
        conn.execute('''UPDATE person_emails SET company_id = (SELECT company_id FROM company_people p WHERE p.id = person_emails.ref_id)
                        WHERE kind = 'company' ''')
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
    if 'ppe_required' not in emp_cols:   # kamerayla denetlenecek zorunlu KKD (JSON dizi: ['kask','eldiven',...])
        conn.execute('ALTER TABLE employees ADD COLUMN ppe_required TEXT')
    if 'is_external' not in emp_cols:   # şirket dışı personel (taşeron/kiralık): zorunlu özlük evrakı istenmez
        conn.execute('ALTER TABLE employees ADD COLUMN is_external INTEGER NOT NULL DEFAULT 0')
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
    if 'maint_since' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:   # BAKIM modu: personel yazıcıyı bakıma aldığı an (NULL = hatta)
        conn.execute('ALTER TABLE printers ADD COLUMN maint_since TEXT')
    if 'arge_since' not in {r[1] for r in conn.execute('PRAGMA table_info(printers)')}:    # AR-GE modu: yazıcı Ar-Ge'ye alındığı an (NULL = hatta); hata/arıza sayılmaz
        conn.execute('ALTER TABLE printers ADD COLUMN arge_since TEXT')
    utcols = {r[1] for r in conn.execute('PRAGMA table_info(user_tasks)')}
    if utcols and 'weekdays' not in utcols:         # günlük görev: haftanın günleri (tekrarlı için)
        conn.execute('ALTER TABLE user_tasks ADD COLUMN weekdays TEXT')
    if utcols and 'task_time' not in utcols:        # günlük görev: görev saati HH:MM
        conn.execute('ALTER TABLE user_tasks ADD COLUMN task_time TEXT')
    if utcols and 'status' not in utcols:           # tek seferlik görev: done/rejected
        conn.execute('ALTER TABLE user_tasks ADD COLUMN status TEXT')
    if utcols and 'reason' not in utcols:           # tek seferlik görev: red nedeni
        conn.execute('ALTER TABLE user_tasks ADD COLUMN reason TEXT')
    if 'location_off' not in {r[1] for r in conn.execute('PRAGMA table_info(users)')}:   # MASTER: konum takibi tamamen kapalı
        conn.execute('ALTER TABLE users ADD COLUMN location_off INTEGER NOT NULL DEFAULT 0')
    ulcols = {r[1] for r in conn.execute('PRAGMA table_info(user_task_log)')}
    if ulcols and 'status' not in ulcols:           # görev tamamlama/red durumu
        conn.execute("ALTER TABLE user_task_log ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")
    if ulcols and 'reason' not in ulcols:           # red nedeni
        conn.execute('ALTER TABLE user_task_log ADD COLUMN reason TEXT')
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
    if 'printed' not in prod_cols:   # Ürün Yönetimi'nden açılan (custom) ürün BASILIP STOKTA tutulur mu → yerleşik sarf gibi davranır
        conn.execute('ALTER TABLE products ADD COLUMN printed INTEGER NOT NULL DEFAULT 0')
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
    if 'source' not in {r[1] for r in conn.execute('PRAGMA table_info(flight_logs)')}:   # log kaynağı: UPLOAD | BRIDGE (dron köprüsü)
        conn.execute("ALTER TABLE flight_logs ADD COLUMN source TEXT NOT NULL DEFAULT 'UPLOAD'")
    if 'fuel' not in {r[1] for r in conn.execute('PRAGMA table_info(flight_logs)')}:   # uçuş yakıtı: başlangıç/bitiş litre + itkiye göre dağıtılmış tüketim özeti (JSON)
        conn.execute('ALTER TABLE flight_logs ADD COLUMN fuel TEXT')
    if 'duration_min' not in {r[1] for r in conn.execute('PRAGMA table_info(online_meetings)')}:   # görüntülü toplantı süresi (davet metni: 15:00 – 16:00)
        conn.execute('ALTER TABLE online_meetings ADD COLUMN duration_min INTEGER NOT NULL DEFAULT 60')
    dd_cols = {r[1] for r in conn.execute('PRAGMA table_info(design_drawings)')}
    if 'product_id' not in dd_cols:   # montaj/çizim ↔ mamul (Ürün Yönetimi) eşleşmesi
        conn.execute('ALTER TABLE design_drawings ADD COLUMN product_id INTEGER REFERENCES products(id) ON DELETE SET NULL')
    if 'step_tree' not in dd_cols:   # STEP parça ağacı düzenlemeleri (JSON: kullanıcı alt kırılımları, taşımalar, ad değişiklikleri)
        conn.execute('ALTER TABLE design_drawings ADD COLUMN step_tree TEXT')
    if 'specs' not in dd_cols:   # montaj genel bilgileri (JSON: mtow_g, payload_g, empty_g, wingspan_mm, length_mm, cruise_kmh, endurance_min, battery, notes)
        conn.execute('ALTER TABLE design_drawings ADD COLUMN specs TEXT')
    ddv_cols = {r[1] for r in conn.execute('PRAGMA table_info(design_drawing_versions)')}
    if 'thumb_path' not in ddv_cols:   # STEP sürümünün 3B önizleme resmi (tarayıcıda üretilir)
        conn.execute('ALTER TABLE design_drawing_versions ADD COLUMN thumb_path TEXT')
    for col in ('preview_stl', 'preview_glb', 'preview_thumb', 'preview_at'):   # STEP → STL / GLB / PNG önizleme (tarayıcıda üretilir; UPLOAD_DIR/design/preview/<id>.*)
        if col not in ddv_cols:
            conn.execute(f'ALTER TABLE design_drawing_versions ADD COLUMN {col} TEXT')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS design_cfd_runs (   -- 3B CFD analizi (OpenFOAM) koşuları: durum dizini, parametreler, sonuç özeti
            id INTEGER PRIMARY KEY,
            drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
            version_id INTEGER REFERENCES design_drawing_versions(id) ON DELETE SET NULL,
            name TEXT,
            params TEXT,
            geometry TEXT,
            status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | cancelling | cancelled | done | failed
            phase TEXT,
            iters INTEGER NOT NULL DEFAULT 0,
            cells INTEGER NOT NULL DEFAULT 0,
            result TEXT,
            error TEXT,
            dir TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_dcr_drawing ON design_cfd_runs(drawing_id);
        CREATE TABLE IF NOT EXISTS design_step_links (   -- STEP içindeki parça (ad/yol anahtarı) ↔ Ürün Yönetimi yarı mamulü
            id INTEGER PRIMARY KEY,
            drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
            mesh_key TEXT NOT NULL,
            mesh_name TEXT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE (drawing_id, mesh_key, product_id));''')
    # STEP parça eşleşmesi: bir parça birden çok yarı mamule bağlanabilir (ör. L15 → L15A + L15B) → tekillik (drawing_id, mesh_key, product_id)
    sl_sql = (conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'design_step_links'").fetchone() or [''])[0] or ''
    if 'UNIQUE (drawing_id, mesh_key)' in sl_sql.replace('  ', ' '):
        conn.executescript('''
            CREATE TABLE design_step_links_new (
                id INTEGER PRIMARY KEY,
                drawing_id INTEGER NOT NULL REFERENCES design_drawings(id) ON DELETE CASCADE,
                mesh_key TEXT NOT NULL,
                mesh_name TEXT,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                created_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL,
                UNIQUE (drawing_id, mesh_key, product_id));
            INSERT INTO design_step_links_new (id, drawing_id, mesh_key, mesh_name, product_id, created_by, created_at)
                SELECT id, drawing_id, mesh_key, mesh_name, product_id, created_by, created_at FROM design_step_links;
            DROP TABLE design_step_links;
            ALTER TABLE design_step_links_new RENAME TO design_step_links;''')
    if 'pinned_at' not in {r[1] for r in conn.execute('PRAGMA table_info(feed_posts)')}:   # Şirketten Haberler: master'ın üste sabitlediği paylaşım
        conn.execute('ALTER TABLE feed_posts ADD COLUMN pinned_at TEXT')
        conn.execute('ALTER TABLE feed_posts ADD COLUMN pinned_by INTEGER REFERENCES users(id)')
    if 'returned_at' not in {r[1] for r in conn.execute('PRAGMA table_info(person_exits)')}:   # yönetici çıkış QR'ı: dönüş kaydı
        conn.execute('ALTER TABLE person_exits ADD COLUMN returned_at TEXT')
        conn.execute('ALTER TABLE person_exits ADD COLUMN returned_by INTEGER REFERENCES users(id)')
    if 'removed_reason' not in {r[1] for r in conn.execute('PRAGMA table_info(feed_posts)')}:   # master sebep yazarak kaldırdı → sahibine bildirim
        conn.execute('ALTER TABLE feed_posts ADD COLUMN removed_by INTEGER REFERENCES users(id)')
        conn.execute('ALTER TABLE feed_posts ADD COLUMN removed_reason TEXT')
        conn.execute('ALTER TABLE feed_posts ADD COLUMN removed_seen_at TEXT')
    lr_cols = {r[1] for r in conn.execute('PRAGMA table_info(leave_requests)')}
    if 'signed_file' not in lr_cols:   # onaylanan iznin ıslak imzalı formu (İK yükler)
        for col in ('signed_file', 'signed_name', 'signed_at'):
            conn.execute(f'ALTER TABLE leave_requests ADD COLUMN {col} TEXT')
        conn.execute('ALTER TABLE leave_requests ADD COLUMN signed_by INTEGER REFERENCES users(id)')
    if 'lat' not in {r[1] for r in conn.execute('PRAGMA table_info(companies)')}:   # firma konumu (internetten bulunan enlem/boylam)
        for col, typ in (('lat', 'REAL'), ('lng', 'REAL'), ('geo_source', 'TEXT'), ('geo_label', 'TEXT'), ('geo_at', 'TEXT')):
            conn.execute(f'ALTER TABLE companies ADD COLUMN {col} {typ}')
    if 'lat' not in {r[1] for r in conn.execute('PRAGMA table_info(employee_addresses)')}:   # ev konumu (Canlı Konum › Ev olarak kaydet)
        conn.execute('ALTER TABLE employee_addresses ADD COLUMN lat REAL')
        conn.execute('ALTER TABLE employee_addresses ADD COLUMN lng REAL')
    if 'ended_at' not in lr_cols:   # izin erken tamamlandı (İK kapattı): planlanan bitiş saklanır, end_date kapatma gününe çekilir
        for col in ('ended_at', 'end_note', 'planned_end'):
            conn.execute(f'ALTER TABLE leave_requests ADD COLUMN {col} TEXT')
        conn.execute('ALTER TABLE leave_requests ADD COLUMN ended_by INTEGER REFERENCES users(id)')
    if 'manager_id' not in {r[1] for r in conn.execute('PRAGMA table_info(employees)')}:   # personelin yöneticisi (görev formunda varsayılan onaylayan)
        conn.execute('ALTER TABLE employees ADD COLUMN manager_id INTEGER REFERENCES users(id)')
    if 'edited_by' not in {r[1] for r in conn.execute('PRAGMA table_info(team_meeting_notes)')}:   # toplantı sonrası düzenleyen
        conn.execute('ALTER TABLE team_meeting_notes ADD COLUMN edited_by INTEGER REFERENCES users(id)')
    if 'seen_at' not in {r[1] for r in conn.execute('PRAGMA table_info(guest_visit_hosts)')}:   # misafir bildirimi görüldü
        conn.execute('ALTER TABLE guest_visit_hosts ADD COLUMN seen_at TEXT')
    for col, typ in (('barcode', 'TEXT'), ('brand', 'TEXT'), ('model', 'TEXT'), ('color', 'TEXT'), ('width_mm', 'REAL'),
                     ('height_mm', 'REAL'), ('depth_mm', 'REAL'), ('weight_g', 'REAL'), ('min_stock', 'REAL')):   # MRP malzeme bilgileri
        if col not in prod_cols:
            conn.execute(f'ALTER TABLE products ADD COLUMN {col} {typ}')
    if 'sale_price' not in prod_cols:   # Esnaf Kasa (POS): perakende satış fiyatı (KDV dahil)
        conn.execute('ALTER TABLE products ADD COLUMN sale_price REAL')
    if 'is_retail' not in prod_cols:    # Esnaf Kasa: yazarkasada satılan ürün (perakende)
        conn.execute('ALTER TABLE products ADD COLUMN is_retail INTEGER NOT NULL DEFAULT 0')
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
    spares.migrate(conn)   # çizim şeması takma adları (ör. MKHV2 → Kamera Holder çizimi)
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
    _fs_cols = {r[1] for r in conn.execute('PRAGMA table_info(face_sightings)')}
    if 'fx' not in _fs_cols:   # yüzün karedeki yatay merkezi (0..1) — Canlı görünümde tahmini konum için
        conn.execute('ALTER TABLE face_sightings ADD COLUMN fx REAL')
    if 'fr' not in _fs_cols:   # yüz genişliği / kare genişliği (0..1) — uzaklık tahmini (büyük=yakın)
        conn.execute('ALTER TABLE face_sightings ADD COLUMN fr REAL')
    # Silinen (gereksiz) yüz gruplarının izleri: bu yüzlere benzeyen yeni görülmeler tekrar listeye alınmaz
    conn.execute('CREATE TABLE IF NOT EXISTS face_ignored (id INTEGER PRIMARY KEY, centroid BLOB NOT NULL, created_at TEXT NOT NULL)')
    # (bir kez) mevcut Güvenlik personeline "Kamera Yetkilisi" rolü ver (Kameralar modülünü görsünler)
    if not conn.execute("SELECT 1 FROM app_kv WHERE k = 'camera_role_seeded'").fetchone():
        conn.execute('''INSERT OR IGNORE INTO user_roles (user_id, role)
                        SELECT DISTINCT user_id, 'Kamera Yetkilisi' FROM user_roles WHERE role = 'Güvenlik' ''')
        conn.execute("INSERT OR REPLACE INTO app_kv (k, v) VALUES ('camera_role_seeded', '1')")
    # Personel aile üyeleri + yüz tanımada eğitilebilirlik
    conn.execute('''CREATE TABLE IF NOT EXISTS family_members (
        id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        full_name TEXT NOT NULL, relation TEXT, birth_date TEXT, phone TEXT, note TEXT, created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_family_members_emp ON family_members(employee_id)')
    if 'family_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_enroll)')}:
        conn.execute('ALTER TABLE face_enroll ADD COLUMN family_id INTEGER REFERENCES family_members(id) ON DELETE CASCADE')
    if 'family_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_groups)')}:
        conn.execute('ALTER TABLE face_groups ADD COLUMN family_id INTEGER REFERENCES family_members(id) ON DELETE SET NULL')
    # Ziyaretçiler + yüz tanımada eğitilebilirlik (face_enroll.visitor_id MERKEZ DB'de, face_groups.visitor_id FABRİKA/gx10 DB'de)
    conn.execute('''CREATE TABLE IF NOT EXISTS visitors (
        id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, company TEXT, phone TEXT, note TEXT,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_visitors_name ON visitors(full_name)')
    if 'visitor_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_enroll)')}:
        conn.execute('ALTER TABLE face_enroll ADD COLUMN visitor_id INTEGER REFERENCES visitors(id) ON DELETE CASCADE')
    if 'visitor_id' not in {r[1] for r in conn.execute('PRAGMA table_info(face_groups)')}:
        conn.execute('ALTER TABLE face_groups ADD COLUMN visitor_id INTEGER REFERENCES visitors(id) ON DELETE SET NULL')
    # Yüz eğitim izi kaynağı: 'manual' (elle yüklenen/kameradan eğitim) | 'auto' (kameradan atanan görülmeden). Rehber "Yapay Zeka"da ayrı gruplanır.
    if 'source' not in {r[1] for r in conn.execute('PRAGMA table_info(face_enroll)')}:
        conn.execute("ALTER TABLE face_enroll ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        # Geçmiş kayıtları dosya adından çıkar: auto kırpıklarının adı '..._<8hex>.jpg' ile biter (enroll_precomputed).
        conn.execute("UPDATE face_enroll SET source = 'auto' WHERE crop GLOB '*_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].jpg'")
    # Ses tanıma örnekleri: kişi (user) başına katkı sağlayan ses izleri; 'manual' (eğitim) | 'auto' (toplantı/arama tanıması).
    # voice_profiles bu örneklerin ortalamasıdır; örnek silinince profil yeniden kurulur (meeting_audio.rebuild_profile).
    conn.execute('''CREATE TABLE IF NOT EXISTS voice_samples (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        embedding TEXT NOT NULL, clip TEXT, source TEXT NOT NULL DEFAULT 'manual', seconds REAL, note TEXT,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_voice_samples_user ON voice_samples(user_id, source)')
    # Görev formu kaynağı: 'manual' (Kişisel görev formu) | 'field' (saha görevi araç çıkış grubu; onaysız/otomatik aktif)
    duty_cols = {r[1] for r in conn.execute('PRAGMA table_info(duty_requests)')}
    if 'source' not in duty_cols:
        conn.execute("ALTER TABLE duty_requests ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
    if 'field_task_id' not in duty_cols:   # saha görevi araç çıkış grubunun bağlı olduğu saha görevi
        conn.execute('ALTER TABLE duty_requests ADD COLUMN field_task_id INTEGER REFERENCES field_tasks(id)')
    if 'returned_at' not in duty_cols:   # grup fabrikaya döndü (güvenlik giriş yaptı) → "Görevde"den düşer
        conn.execute('ALTER TABLE duty_requests ADD COLUMN returned_at TEXT')
    if 'return_kind' not in duty_cols:   # dönüş türü: 'sirket' | 'bitir'
        conn.execute('ALTER TABLE duty_requests ADD COLUMN return_kind TEXT')
    if 'flew' not in duty_cols:   # görevi bitirirken uçuş yapıldı mı (stok devri için)
        conn.execute('ALTER TABLE duty_requests ADD COLUMN flew INTEGER')
    if 'complete_note' not in duty_cols:   # görevi bitirme açıklaması
        conn.execute('ALTER TABLE duty_requests ADD COLUMN complete_note TEXT')
    if 'exited_at' not in duty_cols:   # QR ile çıkış yapıldığı an → "Görevde"ye geçer
        conn.execute('ALTER TABLE duty_requests ADD COLUMN exited_at TEXT')
    # Mikro ERP stok hareketi defter aktarımı: her yerel hareketin Mikro STOK_HAREKETLERI satır kimliği
    # ('mikro:<sth_RECno_RECno>' veya açılış için 'mikro-open:<kod>'). Çift sayımı ve tekrar aktarımı önler.
    if 'mikro_key' not in {r[1] for r in conn.execute('PRAGMA table_info(material_moves)')}:
        conn.execute('ALTER TABLE material_moves ADD COLUMN mikro_key TEXT')
    _migrate_drone_links(conn)


def _migrate_drone_links(conn):
    """Dron Yönetimi Faz 1: bağlantı bilgileri dron kaydından (drone_drones) saha görevi uçuşuna (field_flights) taşınır.
    field_flights'a bridge_id / sysid / link eklenir; drone_drones'tan conn_* / bridge_id / sysid sütunları düşürülür
    (sqlite ≥ 3.35 DROP COLUMN; önce sütuna bağlı dizin kaldırılır). PRAGMA table_info ile denetlenir: idempotent."""
    ff_cols = {r[1] for r in conn.execute('PRAGMA table_info(field_flights)')}
    if 'bridge_id' not in ff_cols:
        conn.execute('ALTER TABLE field_flights ADD COLUMN bridge_id INTEGER REFERENCES drone_bridges(id) ON DELETE SET NULL')
    if 'sysid' not in ff_cols:
        conn.execute('ALTER TABLE field_flights ADD COLUMN sysid INTEGER')
    if 'link' not in ff_cols:
        conn.execute('ALTER TABLE field_flights ADD COLUMN link TEXT')
    conn.execute('CREATE INDEX IF NOT EXISTS ix_field_flights_bridge ON field_flights(bridge_id)')
    dd_cols = {r[1] for r in conn.execute('PRAGMA table_info(drone_drones)')}
    old = [c for c in ('conn_type', 'conn_host', 'conn_port', 'conn_serial', 'conn_baud', 'bridge_id', 'sysid') if c in dd_cols]
    if not old:
        return
    conn.execute('DROP INDEX IF EXISTS ix_drone_drones_bridge')   # bridge_id'ye bağlı dizin: sütun düşürülmeden önce kalkmalı
    for col in old:
        conn.execute(f'ALTER TABLE drone_drones DROP COLUMN {col}')


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
