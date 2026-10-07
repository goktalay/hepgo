package com.turkbey.hepgo;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.app.NotificationCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Gelen arama için tam-ekran bildirim (WhatsApp tarzı): uygulama arka planda / kilit ekranında iken
 * aramayı tam ekran gösterir (setFullScreenIntent). voice.js gelen aramada show(), kapanınca dismiss() çağırır.
 */
@CapacitorPlugin(name = "IncomingCall")
public class IncomingCallPlugin extends Plugin {
    private static final String CH = "incoming_calls";
    private static final int NID = 73100;

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) getContext().getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CH) == null) {
                NotificationChannel ch = new NotificationChannel(CH, "Gelen aramalar", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("Gelen sesli/görüntülü aramalar");
                ch.enableVibration(true);
                ch.setVibrationPattern(new long[]{0, 600, 500, 600, 500});
                nm.createNotificationChannel(ch);
            }
        }
    }

    @PluginMethod
    public void show(PluginCall call) {
        String name = call.getString("name", "Gelen arama");
        boolean video = call.getBoolean("video", false);
        CallNotifier.show(getContext(), name, video ? "Görüntülü arama…" : "Sesli arama…");
        call.resolve();
    }

    @PluginMethod
    public void dismiss(PluginCall call) {
        CallNotifier.dismiss(getContext());
        call.resolve();
    }

    @PluginMethod
    public void canUseFullScreen(PluginCall call) {
        boolean ok = true;
        if (Build.VERSION.SDK_INT >= 34) {
            try {
                NotificationManager nm = (NotificationManager) getContext().getSystemService(Context.NOTIFICATION_SERVICE);
                ok = nm != null && nm.canUseFullScreenIntent();
            } catch (Exception e) {
                ok = true;
            }
        }
        JSObject r = new JSObject();
        r.put("granted", ok);
        call.resolve(r);
    }

    @PluginMethod
    public void requestFullScreen(PluginCall call) {
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                Intent i = new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:" + getContext().getPackageName()));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(i);
            }
        } catch (Exception ignored) {
        }
        call.resolve();
    }
}
