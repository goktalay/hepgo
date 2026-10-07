# HEPGO Android — Windows'ta adım adım derleme

`mobile/android/` projesi hazır ve yapılandırılmış (izinler, SDK 35, ikon/splash, FCM wiring, arkaplan konum).
Aşağıdaki adımlar Windows 10/11 içindir. **Sadece APK/AAB üretmek için Android Studio yeterli** (içinde JDK + SDK gelir).

---

## A) Araçları kur (bir kez)

1. **Android Studio** (ücretsiz): https://developer.android.com/studio → indir, kur.
   - İlk açılışta "Standard" kurulumu seç → Android SDK + JDK otomatik gelir.
2. **Git for Windows**: https://git-scm.com/download/win (kodu indirmek için).
3. *(İsteğe bağlı — kodu/eklentileri değiştirip yeniden `cap sync` yapacaksan)* **Node.js 20 LTS**: https://nodejs.org

> Ayrı JDK kurmana gerek YOK; Android Studio kendi JDK'siyle gelir.

---

## B) Kodu bilgisayarına al

PowerShell veya Git Bash aç:
```powershell
cd %USERPROFILE%\Documents
git clone https://github.com/goktalay/fabrika-yonetim.git
cd fabrika-yonetim\mobile
```
(Daha sonra güncellemek için: `git pull`)

---

## C) Projeyi Android Studio'da aç

1. Android Studio → **Open** → `fabrika-yonetim\mobile\android` klasörünü seç (içindeki `android` klasörü — `mobile` değil).
2. Alt barda **Gradle sync** başlar. Eksik SDK bileşeni isterse (SDK Platform 35, Build-Tools 35) **"Install"** de, kabul et.
   - Takılırsa: **File → Settings → Languages & Frameworks → Android SDK** → "Android 15.0 (API 35)" işaretli olsun.
3. Sync bitince sağ üstte cihaz/emülatör seçip **Run ▶** ile çalıştırabilirsin.

> Uygulama **canlı siteyi** (`https://gokkubbe.hepgo.com`) açar; arayüz hep günceldir, APK'yı her seferinde yeniden derlemene gerek olmaz.

---

## D) Telefonda test (APK)

**Emülatörde:** Android Studio → Device Manager → bir Pixel + API 35 image oluştur → Run ▶.

**Gerçek telefonda (USB):**
1. Telefonda **Geliştirici seçenekleri → USB hata ayıklama** aç.
2. USB ile bağla, Android Studio cihazı görünce **Run ▶**.

**Hızlı APK (Android Studio'suz kurulum):**
- Sana ayrıca hazır bir **debug APK** göndereceğim. Onu telefona kopyalayıp aç → "Bilinmeyen kaynaklara izin ver" → kurulur. (Sadece test içindir; mağaza için E adımı.)

---

## E) Mağaza için İMZALI paket (.aab) — Play Console

1. Android Studio → **Build → Generate Signed App Bundle / APK** → **Android App Bundle** seç.
2. **Create new…** ile keystore oluştur (bir kez):
   - Key store path: `%USERPROFILE%\hepgo-release.jks` (GÜVENLİ sakla, kaybetme — kaybolursa uygulamayı güncelleyemezsin!)
   - Parola, alias (ör. `hepgo`), alias parolası belirle, geçerlilik 25+ yıl, ad/kurum bilgisi gir.
3. **release** variant → Finish. Çıktı: `mobile\android\app\release\app-release.aab`.
4. **Google Play Console** ($25 tek seferlik): https://play.google.com/console → Uygulama oluştur → paket adı **com.gokkubbe.hepgo** → `.aab` yükle.
5. Gerekli: gizlilik politikası URL'si (`https://gokkubbe.hepgo.com/gizlilik`), mağaza açıklaması, ekran görüntüleri (telefon + tablet), içerik derecelendirme formu, **Veri güvenliği** formu (konum + bildirim topladığını beyan et).

---

## F) Push bildirimleri (FCM) — isteğe bağlı

1. **Firebase Console** (https://console.firebase.google.com) → yeni proje → **Android uygulaması ekle** → paket adı **com.gokkubbe.hepgo**.
2. `google-services.json` indir → `mobile\android\app\` içine koy.
3. Android Studio'da yeniden **Sync / Build**. (Dosya yoksa da uygulama derlenir; sadece push çalışmaz.)
4. Firebase → Proje ayarları → Hizmet hesapları → özel anahtar JSON'u bana ver; sunucuya koyunca push gönderimi aktif olur.

---

## G) Konum izinleri (önemli not)

- Uygulama ilk kez konum isteyince Android "Uygulama kullanılırken" sorar. **7/24 arkaplan** için kullanıcı
  ayrı olarak **Ayarlar → Uygulama → Konum → "Her zaman izin ver"** seçmeli (Android bunu zorunlu kılar).
- Play incelemesi arkaplan konumunu sıkı inceler: net gerekçe ("personel saha/güvenlik takibi") + gizlilik metni şart.

---

## Sık sorunlar
- **"SDK location not found"** → Android Studio ilk açılışta `local.properties`'i kendi oluşturur; olmazsa
  `mobile\android\local.properties` içine `sdk.dir=C\:\\Users\\<kullanıcı>\\AppData\\Local\\Android\\Sdk` yaz.
- **Gradle JDK hatası** → File → Settings → Build Tools → Gradle → "Gradle JDK" = 17 (Android Studio'nun gömülü JBR'si uygundur).
- **Sürüm yükseltme** → `mobile\android\app\build.gradle` içinde `versionCode` (tam sayı, her yüklemede +1) ve `versionName` ("1.0.1" vb.) artır.
