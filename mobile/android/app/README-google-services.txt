FCM push bildirimleri için:
1) Firebase Console → proje → Android uygulaması ekle (paket adı: com.gokkubbe.hepgo)
2) google-services.json indirip BU KLASÖRE koyun (android/app/google-services.json)
3) `npx cap sync android` → derleyin.
Not: google-services.json yoksa uygulama yine derlenir ve çalışır; yalnız push devre dışı olur
(app/build.gradle koşullu olarak google-services eklentisini yalnız dosya varsa uygular).
google-services.json .gitignore'dadır (gizli anahtar; repoya girmez).
