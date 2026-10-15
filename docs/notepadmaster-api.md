# Notepad Master hesap ve senkronizasyon API'si (sözleşme v1, Mastertool)

Notepad Master, SSH Master, FTP Masters ve SQL Master ile **aynı Mastertool hesabını** kullanır: kullanıcı aynı e-posta ve şifreyle girer, yeniden kayıt olmaz.
Sunucu: `https://notepadmaster.com` (hesap portalı `https://mastertool.download`; API her iki adreste de aynıdır — istemci
`https://notepadmaster.com` kullanır). Uygulama kodu **`np`**. Kardeş sözleşmeler: docs/sshmaster-api.md (v2), docs/ftpmasters-api.md (v1), docs/sqlmaster-api.md (v1);
burada yalnız Notepad Master'a özel kısımlar var, değinilmeyen her şey onlarla birebir aynıdır.

Tüm gövdeler JSON (UTF-8). Hata yanıtı: `{"code": "<makine kodu>", "message": "<Türkçe açıklama>", "detail": "<aynı>"}`.
`GET /api/np/health` → `{ok, version, time}`.

## 0. Türetme (yalnız şifreleme anahtarının `info` değeri farklı)
- `POST /api/np/auth/prelogin {email}` → `{kdf:{alg:"PBKDF2-SHA256", iter:310000, salt}}` (tuz hesaba bağlıdır; diğer uygulamalarla aynı tuz).
- `master = PBKDF2-SHA256(şifre_utf8, base64dec(kdf.salt), kdf.iter, 32 bayt)` — yalnız istemcide.
- `auth_hash = base64(PBKDF2-SHA256(anahtar=master, tuz=şifre_utf8, 1, 32 bayt))` — sunucuya giden tek değer.
- `encKey = HKDF-SHA256(ikm=master, salt=boş, info="npm-enc-v1", 32 bayt)` — **`npm-enc-v1`** (SSH Master `sshm-enc-v1`, FTP Masters `ftpm-enc-v1`, SQL Master `sqlm-enc-v1`).
- Test vektörü: şifre `Test1234!`, salt `AAECAwQFBgcICQoLDA0ODw==`, iter 310000 → auth_hash `mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY=`,
  encKey (`npm-enc-v1`) ilk 8 bayt `2bba9a96476374da`.

## 1. Hesap (web)
Kayıt, doğrulama, şifremi unuttum, şifre değiştirme, cihazlar, indirme ve destek web'dedir. Uygulama tarayıcıda açar (`shell.openExternal`):
`https://notepadmaster.com/kayit`, `/sifremi-unuttum`, `/hesabim` → otomatik olarak `https://mastertool.download/...?app=np`'ya yönlenir
(sayfa ve e-postalar **Notepad Master** markalıdır). Dil ve tema taşımak için `?lang=<tr|en|fr|de|es|ar|zh|ru>&theme=<dark|light>` eklenebilir.

## 2. Uygulama girişi
`POST /api/np/auth/login` `{"email", "auth_hash", "device": "MASAÜSTÜ-PC (Windows 11)", "app_version": "1.0.0"}`
→ `200 {"token", "user": {"id", "email", "name"}, "sync_enabled", "kdf"}`.
Hatalar: `401 bad_credentials`, `403 unverified`, `403 suspended`, **`403 app_disabled`** (yönetici bu hesapta Notepad Master lisansını
kapattı — "Hesabınızda Notepad Master kapalı; mastertool.download › Destek"), `429 rate_limited`.
- `Authorization: Bearer <token>`; 30 gün kullanılmazsa düşer. Token `safeStorage` (DPAPI) ile saklanır; `401 session_expired` → giriş ekranı.
- Notepad Master token'ı **yalnız `/api/np/*`** uçlarında geçer (başka uygulamanın ucunda `403 wrong_app`).
- `POST /api/np/auth/logout` · `GET /api/np/me` → `{user, kdf, sync_enabled, library: {version, updated_at, size, device}}`.

## 3. Bağlantı kütüphanesi senkronizasyonu (uçtan uca şifreli)
Blob = `base64( iv[12] ‖ AES-256-GCM şifreli metin ‖ etiket[16] )`, anahtar `encKey` (`npm-enc-v1`). Sunucu içeriği okuyamaz.
Açık metin:
```json
{"schema": 1, "items": [
  {"id": "<16 hex>", "kind": "connection|folder|settings", "updated_at": 1792080000000, "rev": 3, "device": "<cihaz id>", "deleted": false, "data": { … }}
]}
```
`data` uygulamanın kendi biçimidir (istemci belirler, sunucu görmez). Önerilen:
- `folder`: `name`, `parentId`.
- `connection`: `name, type` (`ssh|ftp|local|file`), `folderId, color, notes`; ssh/ftp için `host, port, username, password` (düz metin — blob
  zaten şifreli), ssh'te `authType, privateKey` (PEM içerik), `passphrase`, `hostKey`; ftp'de `protocol` (`ftp|ftps-implicit|ftps-ssl|ftps-tls|sftp`)
  ve FTP Masters'taki bağlantı seçenekleri; `rootPath` (uzak proje klasörü); `editor` (Notepad++ ayarları: kodlama, satır sonu, sekme genişliği,
  boşlukla girinti, otomatik girinti, satır kaydırma, yazı tipi/boyut, tema, dil zorlama, boşluk/sekme gösterimi, sondaki boşlukları silme …).
  **Cihaza özgü (senkronlanmaz):** `local` / `file` türlerinin yerel yolları, yerel çalışma kopyası (template/önbellek) yolu, anahtar dosyası yolu,
  açık sekmeler ve pencere düzeni. `local`/`file` kayıtları ad ve editör ayarlarıyla senkronlanır, yol her cihazda yeniden seçilir.
- `settings` (tek kayıt, `id: "settings"`): genel editör varsayılanları, tema, dil.
- Birleştirme: aynı `id` için büyük `updated_at` kazanır; eşitlikte `rev`, sonra `device`. Silinenler `deleted: true` ile 30 gün.

`GET /api/np/library` → `{version, updated_at, blob | null}` · `PUT /api/np/library {base_version, blob}` → `200 {version}` |
`409 {code:"conflict", version, blob}` | `413 too_large` (5 MB) · `DELETE /api/np/library` · `PUT /api/np/settings {sync_enabled}`.
**Ne zaman:** girişte, açılışta, yerel değişiklikten 3 sn sonra, açıkken 5 dakikada bir. **Şifre değişince** tüm uygulamaların web
kopyaları silinir, oturumlar düşer; yeni şifreyle girişte yerel kayıtlar yeniden yüklenir (yerel kopya hiç silinmez).

## 4. Sürüm yükleme (CI)
Anahtar: `X-Release-Key: <NOTEPADM_RELEASE_KEY>` (GitHub secret `NOTEPADM_RELEASE_KEY`; diğer uygulamaların anahtarı geçmez).
Dosya başına, gerekirse parçalı (Cloudflare tek istekte 100 MB sınırı; parça ≤ 90 MB, sırayla):
1. `POST /api/np/releases/<sürüm>/setup` — `multipart/form-data`: `file`, `part` (0..parts-1), `parts`, `filename` (`Notepad-Master-Setup-<sürüm>.exe`), `notes`.
2. `POST /api/np/releases/<sürüm>/portable` — aynı biçim, `filename` `Notepad-Master-Portable-<sürüm>.exe`.
Ara parça → `{ok, received}`; son parça → `{ok, version, kind, sha256, size}`. Hatalar: `409 exists` (atla), `404 no_release`,
`409 part_order`, `422 not_exe`, `422 invalid_version`, `403`. Tek istek (≤ 100 MB): `POST /api/np/releases` (`version, setup, portable?, notes`).
`GET /api/np/releases/latest` (Bearer) → `{version, notes, size, sha256, portable, portable_size, date}` | `{version: null}`.

## 5. Mastertool düğmesi ve yönetim
- Pencerenin en sağ üst köşesinde animasyonlu **Mastertool** düğmesi: docs/mastertool-button.md (işaretleme + CSS birebir);
  tıklama `shell.openExternal('https://mastertool.download/?lang=<dil>&theme=<tema>')`.
- Yönetim: HEPGO Merkez › Mastertool (kullanıcılar, uygulama bazında lisans, Notepad Master sürümleri). Destek: mastertool.download › Hesabım › Destek (uygulama: Notepad Master).
