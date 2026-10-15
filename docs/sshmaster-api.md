# SSH Master hesap ve senkronizasyon API'si (sözleşme v2)

Sunucu: `https://sshmasters.com` (HEPGO canlı sunucusu, servis `hepgo-sshmasters`, kaynak `central/sshmaster_server/`).
Yönetim: HEPGO Merkez (`merkez.veilox.app`) › SSH Master. Kayıt/şifre e-postaları `register@hepgo.com` üzerinden gider;
gönderen adı, konu ve logo **SSH Master**'dır.

Tüm gövdeler JSON (UTF-8). Hata yanıtı: `{"code": "<makine kodu>", "message": "<Türkçe açıklama>", "detail": "<aynı>"}`.
`GET /api/sm/health` → `{ok, version, time}`.

## 0. Türetme (v2 — düz şifre sunucuya HİÇ gitmez; uygulama ve web/WebCrypto aynı)
- `master = PBKDF2-SHA256(şifre_utf8, base64dec(kdf.salt), kdf.iter, 32 bayt)` — yalnız istemcide.
- `auth_hash = base64(PBKDF2-SHA256(anahtar=master, tuz=şifre_utf8, 1, 32 bayt))` — sunucuya giden tek değer; sunucu kendi PBKDF2'siyle saklar.
- `encKey = HKDF-SHA256(ikm=master, salt=boş, info="sshm-enc-v1", 32 bayt)` — kütüphane AES-256-GCM anahtarı, istemcide kalır.
- `POST /api/sm/auth/prelogin {email}` → `{kdf:{alg:"PBKDF2-SHA256", iter:310000, salt}}`; kullanıcı yoksa e-postaya bağlı deterministik
  tuz döner (varlık sızmaz). Kayıt bu tuzu kullanır.
- Test vektörü: şifre `Test1234!`, salt `AAECAwQFBgcICQoLDA0ODw==`, iter 310000 → auth_hash `mLBQ6HQqD19kX/VavErWYq+7tM4mCmGfic7GuQQlBMY=`,
  encKey ilk 8 bayt `057420fdf256cfde`.

## 1. Hesap akışı (web)

| Sayfa | İş |
|---|---|
| `/kayit` | Ad, e-posta, şifre (en az 8 karakter) → doğrulama e-postası (bağlantı, 24 saat) |
| `/dogrula/<token>` | E-postayı doğrular, hesabı açar, oturum açar → `/hesabim` |
| `/giris` | E-posta + şifre |
| `/sifremi-unuttum` | E-posta → sıfırlama bağlantısı (1 saat) |
| `/sifre-sifirla/<token>` | Yeni şifre |
| `/hesabim` | Kişiye özel indirme, senkronizasyon durumu, cihazlar (oturumlar), şifre değiştir, çıkış |

**İndirme kişiye özeldir:** `/hesabim`'daki bağlantı `/indir/<token>` biçimindedir; token kullanıcıya bağlıdır ve
**yalnız aynı kullanıcı oturum açmışken** çalışır (başka tarayıcıda/oturumsuz açılırsa girişe yönlenir; giriş yapan farklı
kullanıcıysa 403). İndirme kaydı tutulur. Hesap askıdaysa indirme ve uygulama girişi kapalıdır.

## 2. Uygulama girişi

`POST /api/sm/auth/login`
```json
{"email": "a@b.com", "auth_hash": "<base64 32 bayt>", "device": "MASAÜSTÜ-PC (Windows 11)", "app_version": "1.2.0"}
```
(`client: "web"` gönderilirse token yerine `sm_session` çerezi verilir.)
→ `200 {"token": "<opak>", "user": {"id": 7, "email": "a@b.com", "name": "Ali"}, "sync_enabled": true,
        "kdf": {"alg": "PBKDF2-SHA256", "iter": 310000, "salt": "<base64 16 bayt>"}}`

Hatalar: `401 code=bad_credentials`, `403 code=unverified` (e-posta doğrulanmamış), `403 code=suspended`, `429 code=rate_limited`.

- Token opak; `Authorization: Bearer <token>` ile gönderilir. 30 gün kullanılmazsa düşer, her istekte süre uzar.
- Uygulama token'ı Electron `safeStorage` (DPAPI) ile saklar. **Çevrimdışıyken** saklı token varsa uygulama yerel
  kütüphaneyle açılır; senkronizasyon bağlantı gelince yapılır. Sunucu `401 code=session_expired` dönerse giriş ekranı açılır.
- `POST /api/sm/auth/logout` (Bearer) — token'ı siler. `GET /api/sm/me` (Bearer) → `{user, sync_enabled, kdf, library: {version, updated_at, size}}`.
- Şifremi unuttum / kayıt: uygulama tarayıcıda `https://sshmasters.com/sifremi-unuttum` ve `/kayit` açar (`shell.openExternal`).

## 3. Bağlantı kütüphanesi senkronizasyonu (uçtan uca şifreli)

Sunucu kütüphaneyi **okuyamaz**. Şifreleme istemcide yapılır (anahtar `encKey`, bkz. bölüm 0):
- Blob = `base64( iv[12] ‖ AES-256-GCM şifreli metin ‖ etiket[16] )`.
- Açık metin:
```json
{"schema": 1, "items": [
  {"id": "<string ≤64>", "kind": "connection|folder|shortcut", "updated_at": 1792080000000, "rev": 3, "device": "<cihaz id>", "deleted": false, "data": { … }}
]}
```
`data` uygulamanın kendi biçimidir — bağlantı: name, host, port, username, authType (password|key), password, privateKey (PEM içerik;
cihazda dosyaya yazılır), passphrase, folderId, color, theme, rememberLastDir, lastDir, hostKey (SHA256 parmak izi); klasör: name, parentId;
kısayol: name, command, enter, order. Eşitlikte (aynı updated_at) rev, sonra device ile deterministik kırılım.
Cihaza özgü ayarlar (tepsi, yazı boyutu, pencere düzeni) senkronize edilmez.

`GET /api/sm/library` (Bearer) → `200 {"version": 12, "updated_at": "…", "blob": "<base64>" | null}`

`PUT /api/sm/library` (Bearer) `{"base_version": 12, "blob": "<base64>"}` →
- `200 {"version": 13}` ya da
- `409 {"code": "conflict", "version": 14, "blob": "<base64>"}` → istemci sunucudaki blob'u çözer, **öğe düzeyinde birleştirir**
  (aynı `id` için büyük `updated_at` kazanır; silinenler `deleted: true` ile 30 gün tutulur), yeni `base_version` ile tekrar dener.
- Blob üst sınırı 5 MB (`413 code=too_large`).

`DELETE /api/sm/library` (Bearer) → sunucudaki kopyayı siler (version 0'a döner).

`PUT /api/sm/settings` (Bearer) `{"sync_enabled": false}` → yönetim panelinde görünür; kapalıyken istemci GET/PUT yapmaz.

**Ne zaman:** girişte, uygulama açılışında, yerel değişiklikten 3 sn sonra (ertelemeli), açıkken 5 dakikada bir.
**İlk giriş:** sunucu boşsa yerel kütüphane yüklenir; ikisi de doluysa birleştirilir.

**Şifre değişince / sıfırlanınca** eski anahtarla şifreli kopya okunamaz: sunucu kopyayı siler ve yeni `salt` üretir; diğer oturumlar düşer.
Web: `POST /api/sm/auth/new-salt` (oturumlu) → `{kdf}`; `POST /api/sm/auth/change-password {old_auth_hash, new_auth_hash, new_salt}`.
Sıfırlama: `POST /api/sm/auth/forgot {email}` (her durumda aynı yanıt) → e-posta → `GET /api/sm/auth/reset/<token>` → `{email, kdf(yeni tuz)}` →
`POST /api/sm/auth/reset/<token> {new_auth_hash}`. Kayıt: `POST /api/sm/auth/register {name, email, auth_hash}`, `POST /api/sm/auth/resend-verify {email}`.
Kullanıcı yeni şifreyle girişte cihazındaki kütüphane yeniden yüklenir (yerel kopya hiç silinmez). Web sayfası bunu kullanıcıya söyler.

## 4. Sürüm yükleme (yönetim / CI)

`POST /api/sm/releases` — başlık `X-Release-Key: <gizli>` ya da Merkez iç anahtarı; `multipart/form-data`:
`version` (ör. 1.2.0), `setup` (SSH Master Setup x.y.z.exe), `portable` (isteğe bağlı), `notes` (isteğe bağlı).
En son yüklenen sürüm `/hesabim` indirmesinde verilir. `GET /api/sm/releases/latest` (Bearer) → `{version, notes, size}`
(uygulama içi "yeni sürüm var" bildirimi için; indirme yine web hesabından).

## 5. Yönetim (Merkez, iç anahtar `X-Central-Secret`)

`GET /api/sm/admin/users` · `PUT /api/sm/admin/users/{id}` `{status: AKTIF|ASKIDA, name}` · `DELETE /api/sm/admin/users/{id}` ·
`POST /api/sm/admin/users/{id}/reset-mail` · `GET /api/sm/admin/users/{id}` (oturumlar, indirmeler, kütüphane boyutu/son senkron) ·
`GET/POST/DELETE /api/sm/admin/releases`.
