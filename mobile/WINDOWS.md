# HEPGO Android — Windows'ta adım adım derleme

`mobile/android/` projesi hazır ve yapılandırılmış (izinler, SDK 35, ikon/splash, FCM wiring, arkaplan konum).
Aşağıdaki adımlar Windows 10/11 içindir.

> ⚠️ ÖNEMLİ: Bu bir **Capacitor** projesidir. `android/` klasörü eklentileri `node_modules`'tan okur ve
> `capacitor-cordova-android-plugins/` klasörü `cap sync` ile ÜRETİLİR (repoya girmez). Bu yüzden Android Studio'da
> açmadan ÖNCE mutlaka **`npm install` + `npx cap sync android`** çalıştırmalısın. Yoksa
> *"Could not read script … cordova.variables.gradle does not exist"* hatası alırsın.

---

## A) Araçları kur (bir kez)

1. **Node.js 20 LTS** (ZORUNLU): https://nodejs.org → "LTS" sürümünü indir, kur. (Capacitor CLI + eklenti modülleri için.)
2. **Android Studio** (ücretsiz): https://developer.android.com/studio → "Standard" kurulum (Android SDK + JDK otomatik gelir).
3. **Git for Windows**: https://git-scm.com/download/win

> Ayrı JDK kurmana gerek YOK; Android Studio kendi JDK'siyle gelir.

---

## B) Kodu al + eklentileri hazırla (HER yeni klonda / `git pull`'dan sonra)

PowerShell aç:
```powershell
cd %USERPROFILE%\Documents
git clone https://github.com/goktalay/fabrika-yonetim.git
cd fabrika-yonetim\mobile
npm install
npx cap sync android
```
- `npm install` → `node_modules` (capacitor eklentileri) gelir.
- `npx cap sync android` → `capacitor-cordova-android-plugins/`, web asset'leri ve plugin bağlantılarını ÜRETİR.
> Not: Web/eklenti tarafını değiştirmesen de ilk klonda bu iki komut ŞART. Sonradan `git pull` yaptığında da tekrar `npx cap sync android` çalıştır.

---

## C) Projeyi Android Studio'da aç

1. Android Studio → **Open** → `fabrika-yonetim\mobile\android` klasörünü seç (içteki `android` — `mobile` değil).
2. Alt barda **Gradle sync** başlar. Eksik SDK bileşeni isterse (SDK Platform 35, Build-Tools 35) **"Install"** de, kabul et.
   - Takılırsa: **File → Settings → Languages & Frameworks → Android SDK** → "Android 15.0 (API 35)" işaretli olsun.
3. Sync bitince sağ üstte cihaz/emülatör seçip **Run ▶** ile çalıştırabilirsin.
   - (Alternatif: `mobile` klasöründe `npx cap open android` komutu projeyi doğrudan Android Studio'da açar.)

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
4. **Google Play Console** ($25 tek seferlik): https://play.google.com/console → Uygulama oluştur → paket adı **com.turkbey.hepgo** → `.aab` yükle.
5. Gerekli: gizlilik politikası URL'si (`https://gokkubbe.hepgo.com/gizlilik`), mağaza açıklaması, ekran görüntüleri (telefon + tablet), içerik derecelendirme formu, **Veri güvenliği** formu (konum + bildirim topladığını beyan et).

---

## F) Push bildirimleri (FCM) — DİKKAT: push eklentisi varsa google-services.json ŞART

> ⚠️ Uygulama push eklentisiyle derlenir ama `google-services.json` YOKSA, açılışta push kaydı sırasında
> **çöker**: *"Default FirebaseApp is not initialized"*. İki çözümden biri gerekir:

**Push'u kullanacaksan (önerilen):**
1. **Firebase Console** (https://console.firebase.google.com) → yeni proje → **Android uygulaması ekle** → paket adı **com.turkbey.hepgo**.
2. `google-services.json` indir → `mobile\android\app\` içine koy.
3. `cd mobile && npx cap sync android` → Android Studio'da **Run**. Çökme biter, push çalışır.
4. Firebase → Proje ayarları → Hizmet hesapları → özel anahtar JSON'u bana ver; sunucuya koyunca push gönderimi aktif olur. (Bu olmadan da uygulama çökmez, sadece bildirim gelmez.)

**Şimdilik push istemiyorsan (Firebase'siz test):** eklentiyi çıkar — `native.js` otomatik atlar, çökmez:
```powershell
cd mobile
npm uninstall @capacitor/push-notifications
npx cap sync android
```
Geri eklemek: `npm i @capacitor/push-notifications` + google-services.json + `npx cap sync android`.

---

## G) Konum izinleri (önemli not)

- Uygulama ilk kez konum isteyince Android "Uygulama kullanılırken" sorar. **7/24 arkaplan** için kullanıcı
  ayrı olarak **Ayarlar → Uygulama → Konum → "Her zaman izin ver"** seçmeli (Android bunu zorunlu kılar).
- Play incelemesi arkaplan konumunu sıkı inceler: net gerekçe ("personel saha/güvenlik takibi") + gizlilik metni şart.

---

## Sık sorunlar
- **Açılışta çökme: "Default FirebaseApp is not initialized in this process com.turkbey.hepgo"**
  → Push eklentisi var ama `google-services.json` yok. F adımı: ya google-services.json ekle, ya da push eklentisini
  geçici çıkar (`npm uninstall @capacitor/push-notifications && npx cap sync android`).
- **"Could not read script … capacitor-cordova-android-plugins\cordova.variables.gradle does not exist"**
  → B adımını atlamışsın. `mobile` klasöründe `npm install` sonra `npx cap sync android` çalıştır, ardından
  Android Studio'da **File → Sync Project with Gradle Files**.
- **"SDK location not found"** → Android Studio ilk açılışta `local.properties`'i kendi oluşturur; olmazsa
  `mobile\android\local.properties` içine `sdk.dir=C\:\\Users\\<kullanıcı>\\AppData\\Local\\Android\\Sdk` yaz.
- **Gradle JDK hatası** → File → Settings → Build Tools → Gradle → "Gradle JDK" = 17 (Android Studio'nun gömülü JBR'si uygundur).
- **Sürüm yükseltme** → `mobile\android\app\build.gradle` içinde `versionCode` (tam sayı, her yüklemede +1) ve `versionName` ("1.0.1" vb.) artır.
