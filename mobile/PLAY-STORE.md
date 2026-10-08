# HEPGO — Google Play Store Yayın Rehberi

Bu dosya, HEPGO Android uygulamasını **Google Play Console**'da yayınlamak için adım adım süreci ve
kopyala‑yapıştır hazır mağaza içeriklerini içerir. Uygulama paketi: **`com.turkbey.hepgo`**.

> Hazır dosyalar:
> - İmzalı yayın paketi: `mobile/dist/HEPGO-release.aab` (Play'e bu yüklenir)
> - Mağaza ikonu 512×512: `mobile/store/icon-512.png`
> - Öne çıkan görsel 1024×500: `mobile/store/feature-graphic-1024x500.png`
> - Mağaza metinleri (TR): aşağıda + `mobile/store/listing-tr.md`
> - İmzalama: `mobile/android/keystore.properties` + `mobile/android/app/hepgo-upload.jks` (git'e GİRMEZ; **yedekleyin**)

---

## 0) Ön koşullar (bir kez)

1. **Google Play Developer hesabı** — https://play.google.com/console → tek seferlik **25 USD** kayıt ücreti.
   Kuruluş hesabı için D‑U‑N‑S numarası ve kimlik doğrulama istenir (birkaç gün sürebilir).
2. Geliştirici hesabı + ödeme profili tamamlanmış olmalı.
3. Elinizde hazır olmalı: imzalı **AAB**, ikon, feature graphic, en az **2 telefon ekran görüntüsü**,
   gizlilik politikası URL'si (var: https://app.hepgo.com/gizlilik).

---

## 1) İMZALAMA (çok önemli — önce okuyun)

Uygulama **Play App Signing** ile yayınlanır: Google *uygulama imzalama anahtarını* kendi saklar; siz yalnızca
*upload key* ile imzalar, Play'e yüklersiniz.

- Upload keystore ZATEN OLUŞTURULDU: `mobile/android/app/hepgo-upload.jks`
  - Alias: `hepgo`, RSA 2048, 10.000 gün geçerli.
  - SHA‑256: `44:7F:FC:FF:8F:30:14:6C:AD:84:69:67:70:68:51:27:04:EA:9A:48:30:DD:C5:3F:89:D5:AA:00:FA:38:81:32`
- Parolalar `mobile/android/keystore.properties` içinde (git'e girmez). **Bu dosyayı ve .jks'i güvenli bir yerde yedekleyin.**
- Keystore/parola GİT'TE DEĞİLDİR ve oturum kapanınca sunucudan silinebilir → mutlaka indirip saklayın.

> Kaybederseniz: Play App Signing'de upload key'i Google desteğiyle sıfırlayabilirsiniz, ama yine de kaybetmeyin.

**Yeniden imzalı AAB üretmek** (kod/sürüm değişince):
```bash
cd mobile
npm install && npx cap sync android
cd android
./gradlew bundleRelease     # app/build/outputs/bundle/release/app-release.aab
```
`keystore.properties` varsa çıktı otomatik imzalanır.

### Sürüm numarası (her güncelleme için ZORUNLU)
`mobile/android/app/build.gradle` → `versionCode` her yüklemede **artırılmalı** (1 → 2 → 3 …),
`versionName` kullanıcıya görünen etiket (ör. "1.0.1"). Aynı versionCode ikinci kez yüklenemez.

---

## 2) Play Console'da uygulama oluştur

1. Play Console → **Uygulama oluştur (Create app)**.
2. Uygulama adı: **HEPGO** · Varsayılan dil: **Türkçe (tr‑TR)** · Tür: **Uygulama** · Ücretsiz.
3. Beyanlar (Developer Program Policies + US export) onayla.

---

## 3) Önce test kanalı (önerilir)

Doğrudan prod yerine önce **Internal testing (İç test)** kullanın:
1. Sol menü → **Test > Internal testing > Create new release**.
2. **App bundle** olarak `HEPGO-release.aab` yükle (ilk yüklemede Play App Signing'i kabul et).
3. Testçi e‑postalarını ekle (kendi Google hesabın), test linkini aç, cihazda kur‑dene.
4. Sorun yoksa aynı sürümü **Production**'a yükselt (Promote release).

---

## 4) Mağaza kaydı (Store listing) — hazır içerik

**Main store listing** sayfasında:

- **Uygulama adı (≤30):** `HEPGO`
- **Kısa açıklama (≤80):**
  `Fabrika ve saha yönetimi: üretim, stok, İK, görüşme ve canlı konum tek uygulamada.`
- **Tam açıklama (≤4000):** → `mobile/store/listing-tr.md` içinde (aşağıda da var).
- **Uygulama ikonu:** `store/icon-512.png` (512×512 PNG)
- **Öne çıkan görsel:** `store/feature-graphic-1024x500.png` (1024×500 PNG)
- **Telefon ekran görüntüleri:** en az 2 (önerilen 4–8), 16:9/9:16, kenar ≥ 320px, ≤ 3840px.
  (Cihazınızdan Pano, Rehber, Canlı Konum, Görüşme ekranlarının görüntülerini çekip yükleyin.)
- **Kategori:** `İş (Business)` · Etiketler: ERP, üretim, saha, İK.
- **İletişim:** e‑posta `destek@hepgo.com` (veya kurumsal adres) · Web: `https://www.hepgo.com`
- **Gizlilik politikası:** `https://app.hepgo.com/gizlilik`

---

## 5) Uygulama içeriği (App content) — ZORUNLU formlar

Sol menü → **Policy > App content**. Bu uygulama hassas izinler kullandığı için dikkatli doldurun.

### 5.1 Gizlilik politikası
`https://app.hepgo.com/gizlilik` URL'sini girin (Kullanım şartları: `https://app.hepgo.com/kullanim-sartlari`).

### 5.2 Reklamlar
**Hayır** — uygulama reklam içermez.

### 5.3 Veri güvenliği (Data safety) — beyan edilecekler
Toplanan/işlenen veriler (hepsi uygulamanın çalışması için, şifreli iletim HTTPS, hesap silinince silinir):

| Veri türü | Toplanıyor | Paylaşılıyor | Amaç | Not |
|---|---|---|---|---|
| Konum (yaklaşık + kesin) | Evet | Hayır | Uygulama işlevi (saha/görev takibi) | **Arka planda** — yalnız açık rıza + mesai/görev kuralları |
| Kişiler (rehber) | Evet | Hayır | Uygulama işlevi | Yalnız kullanıcı başlatınca; kişinin özel rehberinde, sadece sahibi görür |
| Kişisel bilgiler (ad, e‑posta, telefon) | Evet | Hayır | Hesap yönetimi, uygulama işlevi | |
| Fotoğraflar/Medya | Evet | Hayır | Profil, evrak, yüz tanıma (varsa) | |
| Ses | Evet | Hayır | Sesli/görüntülü görüşme (WebRTC) | Kayıt sunucuda tutulmaz (görüşme canlı) |
| Uygulama etkinliği / cihaz kimliği | Evet | Hayır | Güvenlik, bildirim (FCM), oturum | |

- Aktarım şifreli: **Evet (HTTPS/TLS)**.
- Kullanıcı silme talebi: **Evet** — hesap kapatma ile veriler silinir (gizlilik sayfasında anlatılır).

### 5.4 İzin beyanları (Permissions declaration) — kritik
Aşağıdaki hassas izinler için Play'de gerekçe (bazıları **video**) istenir:

- **Arka plan konumu (`ACCESS_BACKGROUND_LOCATION`)** → en çok incelenen izin.
  - Gerekçe: Saha/görevdeki personelin iş güvenliği ve operasyon takibi; işveren tarafından, **çalışanın açık rızası (KVKK)** ile.
  - "Prominent disclosure" (belirgin bildirim) uygulama içinde var (ilk açılış onboarding + Kişisel Ayarlar rıza).
  - Genellikle özelliği gösteren **kısa ekran kaydı videosu** (YouTube linki) istenir; konum rızası + canlı konum ekranını gösterin.
  - Konum kapatma kuralları: mesai dışında kapatılabilir; görevde/sahada veya "konumu her zaman açık" rollerde (ör. Güvenlik) açık kalır — bunu açıklayın.
- **Kişiler (`READ_CONTACTS` / `WRITE_CONTACTS`)**
  - Gerekçe: Kullanıcı **kendi isteğiyle** telefon kişilerini özel rehberine aktarır veya sistemdeki yetkili olduğu kişileri telefonuna kaydeder. Otomatik/arka planda okuma YOK.
- **Kamera / Mikrofon (`CAMERA`, `RECORD_AUDIO`)**
  - Gerekçe: QR okuma + uygulama içi sesli/görüntülü görüşme (WebRTC).
- **Tam ekran bildirim (`USE_FULL_SCREEN_INTENT`)**
  - Gerekçe: Gelen sesli/görüntülü **arama** bildirimi (WhatsApp tarzı). Android 14 politikası yalnız arama/alarm için izin verir — uygunuz.
- **Ön plan hizmeti (`FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_LOCATION`)**
  - Gerekçe: Saha takibinde kesintisiz konum için ön plan hizmeti; kullanıcıya bildirimde görünür.

### 5.5 İçerik derecelendirmesi (Content rating)
Anketi doldurun: İş/üretkenlik uygulaması, şiddet/müstehcenlik yok → genellikle **Herkes (3+)**.

### 5.6 Hedef kitle ve çocuklar
Hedef yaş: **18+ / yetişkin (kurumsal çalışanlar)**. Çocuklara yönelik değil.

### 5.7 Veri erişimi / resmi uygulama
- "Government app" vb. değil.
- WebView tabanlı (içerik `app.hepgo.com`): meşru kurumsal uygulama; native push/konum/kişi/kamera özellikleri var.

---

## 6) Ülke ve fiyat
- Ücretsiz uygulama. Dağıtım ülkeleri: en azından **Türkiye** (gerekirse diğerleri).

---

## 7) Gönderim ve inceleme
1. Tüm "App content" formları yeşil (tamamlandı) olmalı.
2. Production > Create release > AAB yükle > Rollout.
3. İnceleme: hassas izinler (arka plan konumu) nedeniyle birkaç gün sürebilir; ek bilgi/video istenebilir.

---

## 8) Güncellemeler (sonraki sürümler)
1. Kodu güncelle → `versionCode` artır, `versionName` güncelle (`build.gradle`).
2. `npx cap sync android` → `./gradlew bundleRelease` → yeni imzalı AAB.
3. Play Console > yeni release > AAB yükle > rollout.

> Not: Arayüz canlı web (`app.hepgo.com`) olduğu için çoğu **arayüz** güncellemesi APK/AAB gerektirmez
> (uygulama açık sürüm değişimini algılayıp kendini tazeler). Yeni **native** özellik/izin veya
> `versionCode`/yapılandırma değişikliğinde yeni AAB gerekir.

---

## 9) Hızlı kontrol listesi
- [ ] Developer hesabı aktif (25$ ödendi)
- [ ] `HEPGO-release.aab` imzalı ve hazır
- [ ] Keystore + parolalar güvenle yedeklendi
- [ ] İkon 512 + feature graphic 1024×500 + ≥2 ekran görüntüsü
- [ ] Kısa + tam açıklama girildi
- [ ] Gizlilik politikası URL'si
- [ ] Veri güvenliği formu (konum/kişiler/kamera/ses) dolduruldu
- [ ] İzin beyanları (arka plan konumu videosu dahil) gönderildi
- [ ] İçerik derecelendirme anketi
- [ ] Internal testing'de denendi → Production'a yükseltildi
