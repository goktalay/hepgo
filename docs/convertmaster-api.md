# Convert Master hesap ve senkronizasyon API'si (sözleşme v1, Mastertool)

Convert Master, SSH Master, FTP Masters, SQL Master ve Notepad Master ile **aynı Mastertool hesabını** kullanır: kullanıcı aynı e-posta ve şifreyle girer, yeniden kayıt olmaz.
Sunucu: `https://convertmaster.app` (hesap portalı `https://mastertool.download`; API her iki adreste de aynıdır — istemci
`https://convertmaster.app` kullanır). Uygulama kodu **`cv`**. Kardeş sözleşmeler: docs/sshmaster-api.md (v2), docs/ftpmasters-api.md (v1), docs/sqlmaster-api.md (v1), docs/notepadmaster-api.md (v1);
burada yalnız Convert Master'a özel kısımlar var, değinilmeyen her şey onlarla birebir aynıdır.

Tüm gövdeler JSON (UTF-8). Hata yanıtı: `{"code": "<makine kodu>", "message": "<Türkçe açıklama>", "detail": "<aynı>"}`.
`GET /api/cv/health` → `{ok, version, time}`.

## 0. Türetme (yalnız şifreleme anahtarının `info` değeri farklı)
- `POST /api/cv/auth/prelogin {email}` → `{kdf:{alg:"PBKDF2-SHA256", iter:310000, salt}}` (tuz hesaba bağlıdır; diğer uygulamalarla aynı tuz).
- `master = PBKDF2-SHA256(şifre_utf8, base64dec(kdf.salt), kdf.iter, 32 bayt)` — yalnız istemcide.
- `auth_hash = base64(PBKDF2-SHA256(anahtar=master, tuz=şifre_utf8, 1, 32 bayt))` — sunucuya giden tek değer.
- `encKey = HKDF-SHA256(ikm=master, salt=boş, info="cvm-enc-v1", 32 bayt)` — **`cvm-enc-v1`** (SSH Master `sshm-enc-v1`, FTP Masters `ftpm-enc-v1`, SQL Master `sqlm-enc-v1`, Notepad Master `npm-enc-v1`).
- Test vektörü: şifre `Test1234!`, salt `AAECAwQFBgcICQoLDA0ODw==`, iter 310000 → auth_hash `mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY=`,
  encKey (`cvm-enc-v1`) ilk 8 bayt `44199cbf68e39ac9`.

## 1. Hesap (web)
Kayıt, doğrulama, şifremi unuttum, şifre değiştirme, cihazlar, indirme ve destek web'dedir. Uygulama tarayıcıda açar (`shell.openExternal`):
`https://convertmaster.app/kayit`, `/sifremi-unuttum`, `/hesabim` → otomatik olarak `https://mastertool.download/...?app=cv`'ya yönlenir
(sayfa ve e-postalar **Convert Master** markalıdır). Dil ve tema taşımak için `?lang=<tr|en|fr|de|es|ar|zh|ru>&theme=<dark|light>` eklenebilir.

## 2. Uygulama girişi
`POST /api/cv/auth/login` `{"email", "auth_hash", "device": "MASAÜSTÜ-PC (Windows 11)", "app_version": "1.0.0"}`
→ `200 {"token", "user": {"id", "email", "name"}, "sync_enabled", "kdf"}`.
Hatalar: `401 bad_credentials`, `403 unverified`, `403 suspended`, **`403 app_disabled`** (yönetici bu hesapta Convert Master lisansını
kapattı — "Hesabınızda Convert Master kapalı; mastertool.download › Destek"), `429 rate_limited`.
- `Authorization: Bearer <token>`; 30 gün kullanılmazsa düşer. Token `safeStorage` (DPAPI) ile saklanır; `401 session_expired` → giriş ekranı.
- Convert Master token'ı **yalnız `/api/cv/*`** uçlarında geçer (başka uygulamanın ucunda `403 wrong_app`).
- `POST /api/cv/auth/logout` · `GET /api/cv/me` → `{user, kdf, sync_enabled, library: {version, updated_at, size, device}}`.

## 3. Proje kütüphanesi senkronizasyonu (uçtan uca şifreli)
Blob = `base64( iv[12] ‖ AES-256-GCM şifreli metin ‖ etiket[16] )`, anahtar `encKey` (`cvm-enc-v1`). Sunucu içeriği okuyamaz.
Açık metin:
```json
{"schema": 1, "items": [
  {"id": "<16 hex>", "kind": "project|folder|settings", "updated_at": 1792080000000, "rev": 3, "device": "<cihaz id>", "deleted": false, "data": { … }}
]}
```
`data` uygulamanın kendi biçimidir (istemci belirler, sunucu görmez). Önerilen:
- `folder`: `name`, `parentId`.
- `project`: `name, type` (`video|image|audio`), `sourceExt, targetExt`, `sourceKind` (`file|folder`), `concurrency` (aynı anda çevrilecek dosya),
  `speech` (video/ses: konuşmadan metne açık mı, dil/model tercihi), hedef ayarları (çözünürlük, bit hızı, kalite …), `folderId, notes`.
  **Cihaza özgü (senkronlanmaz):** kaynak dosya/klasör yolu, çıktı ve geçici (AppData) yolları, çevrim geçmişi, önizleme durumu —
  proje tanımı senkronlanır, kaynak yolu her cihazda yeniden seçilir. Dönüştürülen dosyalar ve metin dökümleri senkronlanmaz.
- `settings` (tek kayıt, `id: "settings"`): genel varsayılanlar, tema, dil.
- Birleştirme: aynı `id` için büyük `updated_at` kazanır; eşitlikte `rev`, sonra `device`. Silinenler `deleted: true` ile 30 gün.

`GET /api/cv/library` → `{version, updated_at, blob | null}` · `PUT /api/cv/library {base_version, blob}` → `200 {version}` |
`409 {code:"conflict", version, blob}` | `413 too_large` (5 MB) · `DELETE /api/cv/library` · `PUT /api/cv/settings {sync_enabled}`.
**Ne zaman:** girişte, açılışta, yerel değişiklikten 3 sn sonra, açıkken 5 dakikada bir. **Şifre değişince** tüm uygulamaların web
kopyaları silinir, oturumlar düşer; yeni şifreyle girişte yerel kayıtlar yeniden yüklenir (yerel kopya hiç silinmez).

## 4. Sürüm yükleme (CI)
Anahtar: `X-Release-Key: <CONVERTM_RELEASE_KEY>` (GitHub secret `CONVERTM_RELEASE_KEY`; diğer uygulamaların anahtarı geçmez).
Dosya başına, gerekirse parçalı (Cloudflare tek istekte 100 MB sınırı; parça ≤ 90 MB, sırayla):
1. `POST /api/cv/releases/<sürüm>/setup` — `multipart/form-data`: `file`, `part` (0..parts-1), `parts`, `filename` (`Convert-Master-Setup-<sürüm>.exe`), `notes`.
2. `POST /api/cv/releases/<sürüm>/portable` — aynı biçim, `filename` `Convert-Master-Portable-<sürüm>.exe`.
Ara parça → `{ok, received}`; son parça → `{ok, version, kind, sha256, size}`. Hatalar: `409 exists` (atla), `404 no_release`,
`409 part_order`, `422 not_exe`, `422 invalid_version`, `403`. Tek istek (≤ 100 MB): `POST /api/cv/releases` (`version, setup, portable?, notes`).
`GET /api/cv/releases/latest` (Bearer) → `{version, notes, size, sha256, portable, portable_size, date}` | `{version: null}`.

## 5. Mastertool düğmesi ve yönetim
- Pencerenin en sağ üst köşesinde animasyonlu **Mastertool** düğmesi: docs/mastertool-button.md (işaretleme + CSS birebir);
  tıklama `shell.openExternal('https://mastertool.download/?lang=<dil>&theme=<tema>')`.
- Yönetim: HEPGO Merkez › Mastertool (kullanıcılar, uygulama bazında lisans, Convert Master sürümleri). Destek: mastertool.download › Hesabım › Destek (uygulama: Convert Master).
