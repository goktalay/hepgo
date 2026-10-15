# Master Tool masaüstü uygulaması ve ortak oturum (SSO) — sözleşme v1

Master Tool (depo `goktalay/mastertool`, uygulama kodu **`mt`**), Mastertool ailesinin Windows başlatıcısıdır: ailenin uygulamalarını
"Kurulu" ve "Kurulu değil" diye iki grupta simgeleriyle gösterir, kurulu olmayanı indirip kurar, kurulu olanı açar, tepside durur.
Ayrıca **ortak oturumun** (bir kez giriş → tüm uygulamalar açık; birinde çıkış → hepsi kapalı) merkezidir.
Sunucu: `https://mastertool.download` (API her ürün sitesinde de aynı). Kardeş sözleşmeler: docs/sshmaster-api.md, ftpmasters-api.md,
sqlmaster-api.md, notepadmaster-api.md, convertmaster-api.md, mastertool-button.md. Hata biçimi: `{"code", "message", "detail"}`.

## 1. Giriş ve ortak oturum (sunucu)
Türetme diğer uygulamalarla aynı (`POST /api/mt/auth/prelogin` → kdf; `master`, `auth_hash` aynı formül).

| İstek | Yanıt | Açıklama |
|---|---|---|
| `POST /api/mt/auth/login` `{email, auth_hash, client:"desktop", device, app_version}` | `{sso_token, user, kdf, sync_enabled}` | Master Tool girişi: yalnız **ortak (sso) oturum** açılır |
| `POST /api/<app>/auth/login` `{…, sso:true}` | `{token, sso_token, user, kdf, sync_enabled}` | Bir uygulamada şifreyle giriş + cihazın ortak oturumu |
| `POST /api/<app>/auth/sso` `{sso_token, device, app_version}` | `{token, user, kdf, sync_enabled}` | **Şifresiz uygulama girişi** (ortak oturumdan türetilir) |
| `POST /api/<app>/auth/logout` (Bearer uygulama token'ı) | `{ok, sso_ended}` | Ortak oturumdan türetilmişse **tüm aile** kapanır |
| `POST /api/mt/auth/logout` (Bearer sso_token) | `{ok, sso_ended:true}` | Ortak oturum + ona bağlı tüm uygulama oturumları kapanır |

- `<app>` = `sm | fm | sq | np | cv`. Hatalar: `401 bad_credentials`, `403 unverified`, `403 suspended`, `403 app_disabled` (o uygulamanın
  lisansı kapalı — sso ile de açılmaz), `401 session_expired` (ortak oturum kapanmış / süresi dolmuş), `429 rate_limited`.
- `sso_token` yalnız **`/api/mt/*`** uçlarında geçer (`/api/<app>/*` uçlarında `403 wrong_app`); uygulama, `/auth/sso` ile kendi token'ını alır.
- Ortak oturum 30 gün kullanılmazsa düşer; ona bağlı herhangi bir uygulamanın kullanılması süresini uzatır.
- Şifre değişince, hesap askıya alınınca ya da Hesabım › Oturumlar'dan kapatılınca sunucu tüm aileyi düşürür → istemciler `401` alır.

## 2. Cihazda ortak oturumun paylaşılması (TÜM uygulamalar aynı şekilde uygular)
**Ortak kimlik deposu:** Windows Kimlik Bilgisi Yöneticisi, kullanıcı kapsamında genel kimlik bilgisi (DPAPI korumalı).
- Node: `@napi-rs/keyring` → `new Entry('Mastertool', 'sso')`, `setPassword(json)` / `getPassword()` / `deletePassword()`.
  **Altı uygulama da aynı kitaplığı ve aynı iki değeri ('Mastertool', 'sso') kullanmalı** (kitaplık hedef adını bunlardan üretir).
- İçerik (JSON, < 2 KB): `{"v":1, "email", "user":{"id","name"}, "sso_token", "master":"<base64 32 bayt>", "kdf":{alg,iter,salt}, "at":<ms>}`.
  `master` paylaşılır ki şifresiz giren uygulama kendi şifreleme anahtarını türetebilsin (`encKey = HKDF(master, info=<uygulama>-enc-v1)`).
  Asla dosyaya, günlüğe ya da sunucuya yazılmaz.

**Durum işareti (gizli bilgi yok):** `%APPDATA%\Mastertool\sso-state.json` = `{"gen": <artan sayı>, "state": "in"|"out", "at": <ms>}`.
Uygulamalar dosyayı `fs.watch` ile izler (+ 5 sn'de bir yoklama; izleme kaçırabilir).

**Akışlar**
1. *Açılış:* uygulamanın kendi token'ı varsa normal devam. Yoksa ve ortak kimlik varsa → `POST /api/<app>/auth/sso` → token'ı kendi deposuna
   (safeStorage) yaz, giriş ekranını gösterme. `401` → ortak kimliği sil, durum `out`, giriş ekranı. `403 app_disabled` → mesaj göster.
2. *Şifreyle giriş (herhangi bir uygulamada):* `/auth/login` gövdesine `sso:true` ekle → `sso_token` gelir → ortak kimliği yaz → durum
   `{gen+1, "in"}`. Master Tool: `/api/mt/auth/login` `client:"desktop"`.
3. *Durum `in` olunca:* giriş ekranında bekleyen uygulamalar 1. adımı uygular (otomatik giriş).
4. *Çıkış (herhangi bir uygulamada):* `POST /api/<app>/auth/logout` (ya da Master Tool'da `/api/mt/auth/logout`) → ortak kimliği sil →
   kendi token'ını sil → durum `{gen+1, "out"}`.
5. *Durum `out` olunca:* diğer açık uygulamalar kendi token'ını siler ve giriş ekranına döner. **Yerel veriler (bağlantılar, projeler,
   ayarlar) silinmez** — yalnız oturum kapanır.
6. *Herhangi bir istekte `401 session_expired`:* 5. adım gibi davran (sunucu aileyi kapatmıştır); ortak kimliği de sil, durumu `out` yap.

**Tek örnek ve gizli pencere:** Her uygulama `app.requestSingleInstanceLock()` kullanır; `second-instance` olayında penceresi gizliyse
(tepside) gösterir, simge durumundaysa geri yükler ve öne getirir. Master Tool kurulu bir uygulamayı açarken exe'yi yeniden başlatır;
uygulama zaten açıksa bu sayede penceresi görünür.

## 3. Uygulama kataloğu ve indirme (Bearer sso_token)
`GET /api/mt/apps` →
```json
{"apps": [{"app":"fm", "name":"FTP Masters", "exe":"FTP Masters.exe", "install_dir":"Mastertool\\FTP Masters",
           "site":"https://ftpmasters.com/", "icon_png":"/brand/fm.png", "icon_svg":"/brand/fm.svg", "license":"AKTIF",
           "release":{"version","notes","size","sha256","portable","portable_size","date"} | null}, …],
 "launcher": {"name":"Master Tool", "release": {…} | null}}
```
Sıra: sm, fm, sq, np, cv. `license != "AKTIF"` olan uygulama gri ve "Hesabınızda kapalı" etiketiyle gösterilir (indirilmez).
Simge adresleri sunucuya göredir (`https://mastertool.download/brand/fm.png`); çevrimdışı için yerelde önbelleğe alınır.

`GET /api/mt/apps/<app>/download?kind=setup` → dosya akışı; başlıklar `Content-Length`, `X-Version`, `X-Sha256`.
`<app>` = `sm|fm|sq|np|cv` ya da `mt` (Master Tool'un kendi güncellemesi). Hatalar: `403 app_disabled`, `404 no_release`, `401`.
`GET /api/mt/releases/latest` (Bearer sso) → Master Tool'un son sürümü (güncelleme denetimi).

## 4. Kurulu mu? Açma, indirme, kurma (istemci)
- **Algılama:** `HKCU` ve `HKLM` (64 ve 32 bit görünüm) `Software\Microsoft\Windows\CurrentVersion\Uninstall\*` altında `DisplayName`
  `name` ile başlayan kayıt → `InstallLocation\<exe>`; `DisplayVersion` sürümü verir. Yoksa yedek yollar:
  `%ProgramFiles%\Mastertool\<name>\<exe>`, `%LOCALAPPDATA%\Programs\Mastertool\<name>\<exe>`, eski yerler `%ProgramFiles%\<name>\<exe>`,
  `%LOCALAPPDATA%\Programs\<name>\<exe>`. Exe dosyası gerçekten yoksa "kurulu değil" sayılır. Taşınabilir sürüm kurulu sayılmaz.
- **Kurulu → tıklama:** exe'yi ayrık süreç olarak başlat (`spawn(exe, [], {detached:true, stdio:'ignore'}).unref()`). Kurulu sürüm katalogdaki
  sürümden eskiyse simgede küçük "güncelleme var" rozeti; rozetin menüsünden "Güncelle" = indirme + kurulum.
- **Kurulu değil → tıklama:** simgenin üzerinde dairesel indirme ilerlemesi (yüzde + MB), `%APPDATA%\Mastertool\downloads\<dosya>` altına
  `.part` uzantısıyla indir; bitince `X-Sha256` ile doğrula (uymazsa sil, hata göster), yeniden adlandır, kurulumu başlat. İndirme sürerken
  tekrar tıklama = iptal sorusu. Kurulum süreci bitince kayıtları yeniden tara (bitişten sonra 2 dk boyunca 2 sn'de bir); bulunca uygulama
  "Kurulu" grubuna geçer. Kurulum dosyaları başarıdan sonra silinir (Ayarlar › Depolama'da "indirilenleri temizle").
- Aynı anda birden çok indirme olabilir; her simgenin kendi ilerlemesi.

## 5. Tepsi
- Tepside her zaman simge; pencere küçültülünce ve kapatılınca tepsiye gider (çıkış yalnız tepsi menüsünden ya da Ayarlar'dan).
- **Tek tık:** kurulu uygulamaların menüsü (simge + ad); tıklayınca uygulama açılır (açıksa ve gizliyse gösterilir — §2 tek örnek).
  Menünün altında ayırıcı, "Master Tool'u göster", "Çıkış". Çift tık: Master Tool penceresini göster.

## 6. Ortak standart (diğer uygulamalarla aynı)
8 dil (tr, en, fr, de, es, ar sağdan sola, zh, ru), tema Gece / Gündüz / Sistem (varsayılan Sistem), Ayarlar: Genel (dil, tema, Windows ile
başlat, tepsiye küçült, güncelleme denetimi) / Hesap (e-posta, Hesabım, çıkış = tüm uygulamalardan çıkış) / Depolama (indirilenler) / Hakkında
(sürüm, lisanslar). Hesap sayfaları `https://mastertool.download/<yol>?lang=&theme=&app=mt`. Kurulum: `Program Files\Mastertool\Master Tool`,
Başlat menüsü klasörü **"Master Tool"** (SSH Master'ın doğrulanmış `build/installer.nsh` dosyası birebir). Simge: Mastertool logosu
(`https://mastertool.download/brand/mt.svg` / `mt.png`). Uygulama kendisi Mastertool olduğundan sağ üstte Mastertool düğmesi yerine
"mastertool.download" bağlantısı yeterli.

## 7. Sürüm yükleme (CI)
`X-Release-Key: <MASTERTOOL_RELEASE_KEY>` (GitHub secret `MASTERTOOL_RELEASE_KEY`). Diğer uygulamalarla aynı parçalı yükleme:
`POST /api/mt/releases/<sürüm>/setup` (`Master-Tool-Setup-<sürüm>.exe`), `…/portable` (`Master-Tool-Portable-<sürüm>.exe`).
Web indirme: mastertool.download › Hesabım (`/indir/<kişisel token>/mt`).
