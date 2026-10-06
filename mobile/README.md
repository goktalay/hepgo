# HEPGO — iOS & Android mağaza paketi (Capacitor)

Tek altyapı, iki native çıktı. Arayüz **canlı web** olarak kalır (uygulama `https://gokkubbe.hepgo.com`'u native WebView'de açar).
Native eklentiler: **push bildirimleri** (FCM/APNs), **konum** (arkaplan), **ağ durumu** (çevrimdışı şık ekran).

> Derleme Mac/Android Studio gerektirir; bu klasör hazır Capacitor projesidir. Sunucu tarafı (token kaydı, konum, push)
> hazır ve canlıdadır. Senin yapacakların aşağıda.

## 0) Gerekli araçlar
- **Android:** Android Studio + JDK 17. Play Console hesabı ($25, tek sefer).
- **iOS:** **macOS + Xcode**. Apple Developer hesabı ($99/yıl). (iOS derleme Mac olmadan YAPILAMAZ.)
- Node.js 18+.

## 1) Projeyi kur
```bash
cd mobile
npm install
npx cap add android      # android/ projesi oluşur
npx cap add ios          # ios/ projesi oluşur (yalnız macOS)
npx cap sync
```

## 2) İkon & açılış ekranı
1024×1024 ikon + splash hazırlayıp:
```bash
npm i -D @capacitor/assets
npx @capacitor/assets generate --iconBackgroundColor '#0f1d3d' --splashBackgroundColor '#0f1d3d'
```

## 3) Bildirimler
### Android (FCM)
1. Firebase Console → yeni proje → Android uygulaması ekle (paket adı: **com.gokkubbe.hepgo**) → `google-services.json` indir → `mobile/android/app/` içine koy.
2. Firebase → Proje ayarları → **Hizmet hesapları → Yeni özel anahtar** → inen JSON'u SUNUCUYA koy:
   `/opt/hepgo/caymazbuild/data/fcm-service-account.json`
3. Push eklentisi zaten bağlı (`@capacitor/push-notifications`). `npx cap sync` yeter.

### iOS (APNs)
1. Apple Developer → Certificates, IDs & Profiles → **Keys → +** → "Apple Push Notifications service (APNs)" → `.p8` indir, **Key ID**'yi not al.
2. `.p8`'i SUNUCUYA koy: `/opt/hepgo/caymazbuild/data/apns/AuthKey.p8`
3. Sunucu env'ine ekle (servis env dosyası): `CAYMAZ_APNS_KEY_ID`, `CAYMAZ_APNS_TEAM_ID` (Apple Team ID), `CAYMAZ_APNS_BUNDLE_ID=com.gokkubbe.hepgo`.
4. Sunucuda APNs HTTP/2 için **bir kez**: `/opt/hepgo/caymazbuild/.venv/bin/pip install h2`
5. Xcode → Signing & Capabilities → **Push Notifications** ve **Background Modes → Remote notifications** ekle.

> Kimlik bilgileri YOKKEN uygulama yine çalışır; cihaz jetonları toplanır ama bildirim gönderilmez (hata vermez).

## 4) Konum (arkaplan)
- `@capacitor/geolocation` ile ön planda çalışır; **gerçek 7/24 arkaplan** için:
  ```bash
  npm i @capacitor-community/background-geolocation
  npx cap sync
  ```
- **Android:** `android/app/src/main/AndroidManifest.xml` → `ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`.
- **iOS:** `ios/App/App/Info.plist` → `NSLocationWhenInUseUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription` (NET gerekçe: "personel konum takibi"), Background Modes → **Location updates**.
- Konumlar `/api/location/ping`'e gider; yönetici/güvenlik `/api/location/latest` ile en son konumları görebilir (ileride harita eklenebilir).

## 5) Çalıştır / derle
```bash
npx cap run android          # cihaz/emülatör
npx cap open android         # Android Studio → Build > Generate Signed Bundle (.aab) → Play Console
npx cap open ios             # Xcode → Product > Archive → App Store Connect
```

## 6) İzinler & mağaza
- **iOS Info.plist** açıklamaları (konum, kamera varsa). Apple arkaplan konumu sıkı inceler → kullanıcı onayı + net gerekçe şart.
- **Gizlilik politikası URL'si** (ikisi de ister), mağaza açıklaması, ekran görüntüleri.
- **Apple 4.2 riski:** "sadece web sitesi" diye reddedebilir. Push + konum + çevrimdışı + (biyometrik/kamera) native özellikler bunu geçmeye yardım eder; mümkün olduğunca native entegrasyon ekleyin.

## Nasıl çalışıyor (özet)
- `capacitor.config.json` → `server.url = https://gokkubbe.hepgo.com` (canlı web yüklenir, hep güncel).
- Web uygulaması native kabukta açılınca `static/js/native.js` devreye girer: push kaydı + konum gönderimi + ağ kopunca şık **"yalnızca çevrimiçi"** kaplaması (`static/offline.html`).
- Çevrimdışı açılışta service worker (`static/sw.js`) önbellekten offline ekranını gösterir.
