package com.turkbey.hepgo;

import com.capacitorjs.plugins.pushnotifications.MessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/**
 * FCM mesajlarını karşılar. type=call (data-only) ise uygulama TAM KAPALI olsa bile tam-ekran gelen arama
 * bildirimi kurar (kilit ekranında otomatik açılır). Diğer tüm mesajları Capacitor'ın MessagingService'ine devreder
 * (jeton kaydı + normal bildirim/JS teslimi korunur).
 */
public class CallMessagingService extends MessagingService {
    @Override
    public void onMessageReceived(RemoteMessage remoteMessage) {
        Map<String, String> data = remoteMessage.getData();
        if (data != null && "call".equals(data.get("type"))) {
            String title = data.get("title");
            String body = data.get("body");
            CallNotifier.show(getApplicationContext(), title != null ? title : "Gelen arama", body);
            return;
        }
        super.onMessageReceived(remoteMessage);
    }
}
