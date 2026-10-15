# SQL Master hesap ve senkronizasyon API'si (sözleşme v1, Mastertool)

SQL Master, SSH Master ve FTP Masters ile **aynı Mastertool hesabını** kullanır: kullanıcı aynı e-posta ve şifreyle girer, yeniden kayıt olmaz.
Sunucu: `https://sqlmaster.app` (hesap portalı `https://mastertool.download`; API her iki adreste de aynıdır — istemci
`https://sqlmaster.app` kullanır). Uygulama kodu **`sq`**. Kardeş sözleşmeler: docs/sshmaster-api.md (v2), docs/ftpmasters-api.md (v1);
burada yalnız SQL Master'a özel kısımlar var, değinilmeyen her şey onlarla birebir aynıdır.

Tüm gövdeler JSON (UTF-8). Hata yanıtı: `{"code": "<makine kodu>", "message": "<Türkçe açıklama>", "detail": "<aynı>"}`.
`GET /api/sq/health` → `{ok, version, time}`.

## 0. Türetme (yalnız şifreleme anahtarının `info` değeri farklı)
- `POST /api/sq/auth/prelogin {email}` → `{kdf:{alg:"PBKDF2-SHA256", iter:310000, salt}}` (tuz hesaba bağlıdır; diğer uygulamalarla aynı tuz).
- `master = PBKDF2-SHA256(şifre_utf8, base64dec(kdf.salt), kdf.iter, 32 bayt)` — yalnız istemcide.
- `auth_hash = base64(PBKDF2-SHA256(anahtar=master, tuz=şifre_utf8, 1, 32 bayt))` — sunucuya giden tek değer.
- `encKey = HKDF-SHA256(ikm=master, salt=boş, info="sqlm-enc-v1", 32 bayt)` — **`sqlm-enc-v1`** (SSH Master `sshm-enc-v1`, FTP Masters `ftpm-enc-v1`).
- Test vektörü: şifre `Test1234!`, salt `AAECAwQFBgcICQoLDA0ODw==`, iter 310000 → auth_hash `mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY=`,
  encKey (`sqlm-enc-v1`) ilk 8 bayt `69fa902720ef92b1`.

## 1. Hesap (web)
Kayıt, doğrulama, şifremi unuttum, şifre değiştirme, cihazlar, indirme ve destek web'dedir. Uygulama tarayıcıda açar (`shell.openExternal`):
`https://sqlmaster.app/kayit`, `/sifremi-unuttum`, `/hesabim` → otomatik olarak `https://mastertool.download/...?app=sq`'ya yönlenir
(sayfa ve e-postalar **SQL Master** markalıdır). Dil ve tema taşımak için `?lang=<tr|en|fr|de|es|ar|zh|ru>&theme=<dark|light>` eklenebilir.

## 2. Uygulama girişi
`POST /api/sq/auth/login` `{"email", "auth_hash", "device": "MASAÜSTÜ-PC (Windows 11)", "app_version": "1.0.0"}`
→ `200 {"token", "user": {"id", "email", "name"}, "sync_enabled", "kdf"}`.
Hatalar: `401 bad_credentials`, `403 unverified`, `403 suspended`, **`403 app_disabled`** (yönetici bu hesapta SQL Master lisansını
kapattı — "Hesabınızda SQL Master kapalı; mastertool.download › Destek"), `429 rate_limited`.
- `Authorization: Bearer <token>`; 30 gün kullanılmazsa düşer. Token `safeStorage` (DPAPI) ile saklanır; `401 session_expired` → giriş ekranı.
- SQL Master token'ı **yalnız `/api/sq/*`** uçlarında geçer (başka uygulamanın ucunda `403 wrong_app`).
- `POST /api/sq/auth/logout` · `GET /api/sq/me` → `{user, kdf, sync_enabled, library: {version, updated_at, size, device}}`.

## 3. Bağlantı kütüphanesi senkronizasyonu (uçtan uca şifreli)
Blob = `base64( iv[12] ‖ AES-256-GCM şifreli metin ‖ etiket[16] )`, anahtar `encKey` (`sqlm-enc-v1`). Sunucu içeriği okuyamaz.
Açık metin:
```json
{"schema": 1, "items": [
  {"id": "<16 hex>", "kind": "connection|folder|query|settings", "updated_at": 1792080000000, "rev": 3, "device": "<cihaz id>", "deleted": false, "data": { … }}
]}
```
`data` uygulamanın kendi biçimidir (istemci belirler, sunucu görmez). Önerilen:
- `folder`: `name`, `parentId`.
- `connection`: `name, engine` (ör. `mysql|mariadb|postgresql|mssql|sqlite|…` — istemcinin desteklediği motorlar), `host, port, database,
  username, password` (düz metin — blob zaten şifreli), `ssl` ayarları, `sshTunnel` (`host, port, username, authType, password,
  privateKey` PEM içerik, `passphrase`, `hostKey`), `folderId, color, notes`, motor özel seçenekler.
  **Cihaza özgü (senkronlanmaz):** yerel dosya yolları (SQLite dosyası, anahtar dosyası yolu, sertifika yolları), son açılan şema/sekme.
- `query`: kayıtlı sorgular / kod parçacıkları — `name, sql, connectionId?, folderId?`.
- `settings` (tek kayıt, `id: "settings"`): tema, dil, editör tercihleri gibi genel ayarlar (pencere düzeni senkronlanmaz).
- Birleştirme: aynı `id` için büyük `updated_at` kazanır; eşitlikte `rev`, sonra `device`. Silinenler `deleted: true` ile 30 gün.

`GET /api/sq/library` → `{version, updated_at, blob | null}` · `PUT /api/sq/library {base_version, blob}` → `200 {version}` |
`409 {code:"conflict", version, blob}` | `413 too_large` (5 MB) · `DELETE /api/sq/library` · `PUT /api/sq/settings {sync_enabled}`.
**Ne zaman:** girişte, açılışta, yerel değişiklikten 3 sn sonra, açıkken 5 dakikada bir. **Şifre değişince** tüm uygulamaların web
kopyaları silinir, oturumlar düşer; yeni şifreyle girişte yerel kayıtlar yeniden yüklenir (yerel kopya hiç silinmez).

## 4. Sürüm yükleme (CI)
Anahtar: `X-Release-Key: <SQLM_RELEASE_KEY>` (GitHub secret `SQLM_RELEASE_KEY`; diğer uygulamaların anahtarı geçmez).
Dosya başına, gerekirse parçalı (Cloudflare tek istekte 100 MB sınırı; parça ≤ 90 MB, sırayla):
1. `POST /api/sq/releases/<sürüm>/setup` — `multipart/form-data`: `file`, `part` (0..parts-1), `parts`, `filename` (`SQL-Master-Setup-<sürüm>.exe`), `notes`.
2. `POST /api/sq/releases/<sürüm>/portable` — aynı biçim, `filename` `SQL-Master-Portable-<sürüm>.exe`.
Ara parça → `{ok, received}`; son parça → `{ok, version, kind, sha256, size}`. Hatalar: `409 exists` (atla), `404 no_release`,
`409 part_order`, `422 not_exe`, `422 invalid_version`, `403`. Tek istek (≤ 100 MB): `POST /api/sq/releases` (`version, setup, portable?, notes`).
`GET /api/sq/releases/latest` (Bearer) → `{version, notes, size, sha256, portable, portable_size, date}` | `{version: null}`.

## 5. Mastertool düğmesi ve yönetim
- Pencerenin en sağ üst köşesinde animasyonlu **Mastertool** düğmesi: docs/mastertool-button.md (işaretleme + CSS birebir);
  tıklama `shell.openExternal('https://mastertool.download/?lang=<dil>&theme=<tema>')`.
- Yönetim: HEPGO Merkez › Mastertool (kullanıcılar, uygulama bazında lisans, SQL Master sürümleri). Destek: mastertool.download › Hesabım › Destek (uygulama: SQL Master).
