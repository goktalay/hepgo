# FTP Masters hesap ve senkronizasyon API'si (sözleşme v1, Mastertool)

FTP Masters, SSH Master ile **aynı Mastertool hesabını** kullanır: kullanıcı aynı e-posta ve şifreyle girer, yeniden kayıt olmaz.
Sunucu: `https://ftpmasters.com` (hesap portalı `https://mastertool.download`; API her iki adreste de aynıdır — istemci
`https://ftpmasters.com` kullanır). Kaynak `central/sshmaster_server/` (servis `hepgo-sshmasters`). SSH Master sözleşmesi:
docs/sshmaster-api.md (v2) — burada yalnız farklar ve FTP Masters'a özel kısımlar var; değinilmeyen her şey v2 ile birebir aynıdır.

Tüm gövdeler JSON (UTF-8). Hata yanıtı: `{"code": "<makine kodu>", "message": "<Türkçe açıklama>", "detail": "<aynı>"}`.
`GET /api/fm/health` → `{ok, version, time}`.

## 0. Türetme (v2 ile aynı; yalnız şifreleme anahtarının `info` değeri farklı)
- `POST /api/fm/auth/prelogin {email}` → `{kdf:{alg:"PBKDF2-SHA256", iter:310000, salt}}` (tuz hesaba bağlıdır; SSH Master ile aynı tuz).
- `master = PBKDF2-SHA256(şifre_utf8, base64dec(kdf.salt), kdf.iter, 32 bayt)` — yalnız istemcide.
- `auth_hash = base64(PBKDF2-SHA256(anahtar=master, tuz=şifre_utf8, 1, 32 bayt))` — sunucuya giden tek değer (SSH Master ile aynı).
- `encKey = HKDF-SHA256(ikm=master, salt=boş, info="ftpm-enc-v1", 32 bayt)` — **`ftpm-enc-v1`** (SSH Master `sshm-enc-v1`).
  Ayrı `info`, iki uygulamanın şifreli kopyalarını birbirinden ayırır; biri diğerinin kopyasını çözemez.
- Test vektörü: şifre `Test1234!`, salt `AAECAwQFBgcICQoLDA0ODw==`, iter 310000 → auth_hash `mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY=`
  (SSH Master ile aynı), encKey (`ftpm-enc-v1`) ilk 8 bayt `fb085d5af3218dac`.

## 1. Hesap (web)
Kayıt, e-posta doğrulama, şifremi unuttum, şifre değiştirme, cihazlar, indirme ve destek web'dedir. Uygulama tarayıcıda açar
(`shell.openExternal`): `https://ftpmasters.com/kayit`, `https://ftpmasters.com/sifremi-unuttum`, `https://ftpmasters.com/hesabim`
(portal yayına girince bunlar `mastertool.download`'a yönlenir; uygulamada değişiklik gerekmez). Kayıt / şifre e-postaları
**FTP Masters** markalıdır.

## 2. Uygulama girişi
`POST /api/fm/auth/login`
```json
{"email": "a@b.com", "auth_hash": "<base64 32 bayt>", "device": "MASAÜSTÜ-PC (Windows 11)", "app_version": "1.0.1"}
```
→ `200 {"token": "<opak>", "user": {"id": 7, "email": "a@b.com", "name": "Ali"}, "sync_enabled": true, "kdf": {...}}`

Hatalar: `401 bad_credentials`, `403 unverified`, `403 suspended` (hesap askıda), **`403 app_disabled`** (yönetici bu hesapta
FTP Masters lisansını kapattı — "Hesabınızda FTP Masters kapalı; mastertool.download › Destek" gösterin), `429 rate_limited`.

- `Authorization: Bearer <token>`; 30 gün kullanılmazsa düşer, her istekte uzar. Token `safeStorage` (DPAPI) ile saklanır.
  Çevrimdışıyken saklı token ile yerel kayıtlarla açılır. `401 session_expired` → giriş ekranı.
- FTP Masters token'ı **yalnız `/api/fm/*`** uçlarında geçer (SSH Master ucunda `403 wrong_app`); SSH Master token'ı da burada geçmez.
- Lisans kapatılınca açık FTP Masters oturumları sunucuda silinir → sonraki istekte `401 session_expired`, yeniden girişte `403 app_disabled`.
- `POST /api/fm/auth/logout` (Bearer). `GET /api/fm/me` (Bearer) → `{user, kdf, sync_enabled, library: {version, updated_at, size, device}}`.

## 3. Site kütüphanesi senkronizasyonu (uçtan uca şifreli)
Sunucu içeriği **okuyamaz**. Blob = `base64( iv[12] ‖ AES-256-GCM şifreli metin ‖ etiket[16] )`, anahtar `encKey` (`ftpm-enc-v1`).
Açık metin:
```json
{"schema": 1, "items": [
  {"id": "<16 hex>", "kind": "site|folder|settings", "updated_at": 1792080000000, "rev": 3, "device": "<cihaz id>", "deleted": false, "data": { … }}
]}
```
- `folder.data`: `name`, `parentId` (null = kök).
- `site.data` (store.json bağlantı kaydı, **cihaza özgü alanlar çıkarılmış**, gizli alanlar **düz metin** — blob zaten uçtan uca şifreli):
  `createdAt, name, host, port, protocol ('ftp'|'ftps-implicit'|'ftps-ssl'|'ftps-tls'|'sftp'), username, loginMethod ('normal'|'anonymous'),
  authType ('password'|'key'), password, passphrase, privateKey (PEM içerik — anahtar dosyası okunup gömülür; cihazda dosyaya yazılır,
  keyPath yerel kalır), comments, folderId, color, remoteDir, rememberLastDir, cacheMode, uploadCase, transferType, timezone,
  siteOptions, retryAttempts, retryDelay, maxConcurrent, conflict, encoding, hostKey` (SHA256 parmak izi — senkronlanır).
- **Senkronlanmaz (cihaza özgü):** `keyPath, localDir, lastLocalDir, lastRemoteDir`; yerelde `enc:`/`b64:` önekli saklama biçimi
  (senkron metnine çözülmüş değer girer, cihaza yazarken yeniden safeStorage ile şifrelenir).
- `settings` (tek kayıt, `id: "settings"`): `appTheme, language, speedLimitOn, speedLimitKB, maxConcurrent, retryAttempts, retryDelay,
  transferType, conflict`. UI düzeni (`localWidth, localOpen, transferWidth, transferOpen, trCols, showHidden, localDir`) senkronlanmaz.
- Birleştirme v2 ile aynı: aynı `id` için büyük `updated_at` kazanır; eşitlikte `rev`, sonra `device`. Silinenler `deleted: true` ile 30 gün.

`GET /api/fm/library` → `{version, updated_at, blob | null}` ·
`PUT /api/fm/library {base_version, blob}` → `200 {version}` | `409 {code:"conflict", version, blob}` (çöz → birleştir → yeniden dene) |
`413 too_large` (5 MB) · `DELETE /api/fm/library` · `PUT /api/fm/settings {sync_enabled}` → `{sync_enabled}` (SSH Master'dan bağımsız).

**Ne zaman:** girişte, açılışta, yerel değişiklikten 3 sn sonra (ertelemeli), açıkken 5 dakikada bir. İlk girişte sunucu boşsa yerel yüklenir.
**Şifre değişince / sıfırlanınca** (web'den; SSH Master ve FTP Masters için ortak) sunucu tüm uygulamaların şifreli kopyalarını siler ve
yeni tuz üretir, diğer oturumlar düşer. Yeni şifreyle girişte cihazdaki yerel kayıtlar yeniden yüklenir (yerel kopya hiç silinmez).

## 4. Sürüm yükleme (CI)
Anahtar: `X-Release-Key: <FTPM_RELEASE_KEY>` (GitHub secret `FTPM_RELEASE_KEY`; SSH Master anahtarı burada geçmez).

**Önerilen (Cloudflare tek istekte 100 MB sınırı; exe'ler ~78 MB ve büyüyor):** dosya başına ayrı, gerekirse parçalı istek:
1. `POST /api/fm/releases/<sürüm>/setup` — `multipart/form-data`: `file`, `part` (0..parts-1), `parts`, `filename`
   (`FTP-Masters-Setup-<sürüm>.exe`), `notes` (sürüm notları). Parça boyutu ≤ 90 MB önerilir; parçalar sırayla.
2. `POST /api/fm/releases/<sürüm>/portable` — aynı biçim, `filename` `FTP-Masters-Portable-<sürüm>.exe`.

Ara parça → `{ok, received}`; son parça → `{ok, version, kind, sha256, size}` (sha256 Release'teki dosyayla karşılaştırılmalı).
Hatalar: `409 exists` (sürüm / taşınabilir zaten yüklü → iş akışı atlayabilir), `404 no_release` (önce setup), `409 part_order`
(part=0'dan yeniden), `422 not_exe` (MZ değil), `422 invalid_version`, `403` (anahtar yanlış).
Tek istekte de olur (≤ 100 MB toplam): `POST /api/fm/releases` — `version`, `setup`, isteğe bağlı `portable`, `notes`.
`GET /api/fm/releases/latest` (Bearer) → `{version, notes, size, sha256, portable, portable_size, date}` | `{version: null}`
(uygulama içi "yeni sürüm var"; indirme yine web hesabından: `https://ftpmasters.com/hesabim`).

## 5. Yönetim
HEPGO Merkez › Mastertool: kullanıcılar (hesap durumu, uygulama bazında lisans AKTIF/KAPALI, oturumlar, indirmeler, senkron),
FTP Masters sürümleri. Kullanıcının destek talepleri `mastertool.download › Hesabım › Destek`'ten açılır (uygulama: FTP Masters).
