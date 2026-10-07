package com.turkbey.hepgo;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import androidx.core.app.NotificationCompat;

/** Gelen arama tam-ekran bildirimi (hem IncomingCallPlugin JS'ten hem CallMessagingService FCM'den kullanır). */
public final class CallNotifier {
    public static final String CH = "incoming_calls";
    public static final int NID = 73100;

    private CallNotifier() {}

    public static void ensureChannel(Context ctx) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CH) == null) {
                NotificationChannel ch = new NotificationChannel(CH, "Gelen aramalar", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("Gelen sesli/görüntülü aramalar");
                ch.enableVibration(true);
                ch.setVibrationPattern(new long[]{0, 600, 500, 600, 500});
                nm.createNotificationChannel(ch);
            }
        }
    }

    public static void show(Context ctx, String title, String body) {
        try {
            ensureChannel(ctx);
            Intent launch = new Intent(ctx, MainActivity.class);
            launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
            PendingIntent pi = PendingIntent.getActivity(ctx, 0, launch, flags);
            NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CH)
                    .setSmallIcon(ctx.getApplicationInfo().icon)
                    .setContentTitle(title != null ? title : "Gelen arama")
                    .setContentText(body != null ? body : "Sizi arıyor…")
                    .setPriority(NotificationCompat.PRIORITY_MAX)
                    .setCategory(NotificationCompat.CATEGORY_CALL)
                    .setOngoing(true)
                    .setAutoCancel(true)
                    .setTimeoutAfter(40000)   // güvenlik: 40 sn sonra kendi kapansın (zil/titreşim sonsuza kalmasın)
                    .setFullScreenIntent(pi, true)
                    .setContentIntent(pi);
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.notify(NID, b.build());
        } catch (Exception ignored) {
        }
    }

    public static void dismiss(Context ctx) {
        try {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) nm.cancel(NID);
        } catch (Exception ignored) {
        }
    }
}
