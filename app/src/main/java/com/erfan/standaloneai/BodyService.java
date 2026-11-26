package com.erfan.standaloneai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.IBinder;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * Prompt 959 (stage B, the body): the phone's foreground service. It keeps ONE notification, with a progress bar and a stop button, for as long
 * as the assistant does a long job (today: downloading its own brain), so that Android does not close the app while the screen is off or the
 * app is in the background.
 *
 * It does nothing on its own: no timer, no network, no loop and no Python work of its own. The Python side (native_bridge.body.BodyDoor, driven by
 * brain_hub.body) starts it when a job begins, updates its words while the job goes on, and lets it go when the job ends. The only thing this file
 * ever asks Python for is the emergency stop (the notification's button, through StopReceiver).
 *
 * The three public static methods are what Python calls (hold / release / isRunning); each answers a plain value and never throws. A start that
 * Android refuses (for example from the background, on Android 12 and newer) is reported as `false`, never as a crash.
 */
public class BodyService extends Service {

    /** The limits of the words that reach the notification (the Python door cuts to the same sizes). */
    static final int MAX_TITLE = 60;
    static final int MAX_TEXT = 160;

    static final String CHANNEL_ID = "body_jobs";
    static final int NOTIFICATION_ID = 95901;
    static final String EXTRA_TITLE = "title";
    static final String EXTRA_TEXT = "text";
    static final String EXTRA_PERCENT = "percent";

    private static volatile BodyService current;
    private static volatile boolean foreground;
    private static volatile String lastTitle = "";

    private volatile boolean stopRequested;

    // ------------------------------------------------------------------------------------------ what Python calls
    /**
     * Starts the service with these words, or - when it already runs - only updates its notification. `percent` is 0..100, or -1 for «unknown».
     * Returns whether Android accepted the request (the notification itself may still be hidden by the user's notification settings).
     */
    public static boolean hold(Context context, String title, String text, int percent) {
        Context app = appContext(context);
        String cleanTitle = clean(title, MAX_TITLE);
        if (app == null || cleanTitle.isEmpty()) {
            return false;
        }
        String cleanText = clean(text, MAX_TEXT);
        int shown = percent < 0 ? -1 : Math.min(percent, 100);
        try {
            lastTitle = cleanTitle;
            BodyService live = current;
            if (live != null && foreground && !live.stopRequested) {
                post(app, build(app, cleanTitle, cleanText, shown));      // the same id: the notification is updated in place
                return true;
            }
            Intent intent = new Intent(app, BodyService.class);
            intent.putExtra(EXTRA_TITLE, cleanTitle);
            intent.putExtra(EXTRA_TEXT, cleanText);
            intent.putExtra(EXTRA_PERCENT, shown);
            if (Build.VERSION.SDK_INT >= 26) {
                app.startForegroundService(intent);
            } else {
                app.startService(intent);
            }
            return true;
        } catch (RuntimeException e) {
            return false;                                                  // Android refused (background start, missing permission ...)
        }
    }

    /** Lets the service go (and its notification with it). Harmless when it is not running. */
    public static void release(Context context) {
        Context app = appContext(context);
        if (app == null) {
            return;
        }
        try {
            BodyService live = current;
            if (live != null) {
                live.stopRequested = true;                                 // a hold() that comes now starts a fresh service instead of updating this one
            }
            app.stopService(new Intent(app, BodyService.class));
        } catch (RuntimeException e) {
            // nothing to release
        }
    }

    /** Whether the service is really in the foreground right now (Android may have refused it after hold() said yes). */
    public static boolean isRunning() {
        return current != null && foreground;
    }

    // ------------------------------------------------------------------------------------------ the notification's stop button
    /**
     * Called by StopReceiver on a worker thread. Shows «stopping…», asks Python to stop everything that runs and, when Python says it did,
     * lets the service go. If Python cannot be reached or says no, the notification stays and says so (a stop that silently did nothing would
     * be worse than a notification that remains).
     */
    static void stopFromNotification(Context context) {
        Context app = appContext(context);
        if (app == null) {
            return;
        }
        postIfRunning(app, app.getString(R.string.body_stopping));
        String answer = askPythonToStop();
        if (answer != null && isOk(answer)) {
            release(app);
        } else {
            postIfRunning(app, app.getString(R.string.body_stop_failed));
        }
    }

    /** The JSON `platform_boot.emergency_stop()` returns, or null when Python could not be asked. A process with no Python has nothing running. */
    private static String askPythonToStop() {
        try {
            if (!Python.isStarted()) {
                return "{\"ok\":true,\"hubs\":0,\"stopped\":[],\"released\":false}";
            }
            PyObject boot = Python.getInstance().getModule("platform_boot");
            return boot.callAttr("emergency_stop").toString();
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static boolean isOk(String json) {
        try {
            return new JSONObject(json).optBoolean("ok", false);
        } catch (JSONException e) {
            return false;
        }
    }

    // ------------------------------------------------------------------------------------------ service life cycle
    @Override
    public void onCreate() {
        super.onCreate();
        current = this;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String title = intent == null ? null : intent.getStringExtra(EXTRA_TITLE);
        String text = intent == null ? null : intent.getStringExtra(EXTRA_TEXT);
        int percent = intent == null ? -1 : intent.getIntExtra(EXTRA_PERCENT, -1);
        String cleanTitle = clean(title, MAX_TITLE);
        if (cleanTitle.isEmpty()) {
            cleanTitle = getString(R.string.body_default_title);
        }
        try {
            ensureChannel(this);
            Notification notification = build(this, cleanTitle, clean(text, MAX_TEXT), percent < 0 ? -1 : Math.min(percent, 100));
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            } else {
                startForeground(NOTIFICATION_ID, notification);
            }
            lastTitle = cleanTitle;
            stopRequested = false;
            foreground = true;
        } catch (RuntimeException e) {
            // Android does not allow a foreground service now (or the permission is missing): the app goes on without it, Python sees isRunning() == false.
            foreground = false;
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        if (current == this) {
            current = null;
            foreground = false;
        }
        try {
            stopForeground(Service.STOP_FOREGROUND_REMOVE);
        } catch (RuntimeException e) {
            // already gone
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;                                                       // nothing binds to this service
    }

    // ------------------------------------------------------------------------------------------ the notification
    private static void postIfRunning(Context app, String text) {
        try {
            if (current != null && foreground) {
                post(app, build(app, lastTitle.isEmpty() ? app.getString(R.string.body_default_title) : lastTitle, text, -1));
            }
        } catch (RuntimeException e) {
            // the notification stays as it was
        }
    }

    private static void post(Context app, Notification notification) {
        NotificationManager manager = (NotificationManager) app.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, notification);
        }
    }

    private static void ensureChannel(Context app) {
        if (Build.VERSION.SDK_INT < 26) {
            return;
        }
        NotificationManager manager = (NotificationManager) app.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, app.getString(R.string.body_channel_name), NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(app.getString(R.string.body_channel_description));
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    static Notification build(Context app, String title, String text, int percent) {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(app, CHANNEL_ID) : new Notification.Builder(app);
        builder.setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_PROGRESS);
        if (percent >= 0 && percent <= 100) {
            builder.setProgress(100, percent, false);
        } else {
            builder.setProgress(0, 0, true);
        }
        PendingIntent open = openApp(app);
        if (open != null) {
            builder.setContentIntent(open);
        }
        builder.addAction(stopAction(app));
        if (Build.VERSION.SDK_INT >= 31) {
            builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        } else if (Build.VERSION.SDK_INT < 26) {
            builder.setPriority(Notification.PRIORITY_LOW);
        }
        return builder.build();
    }

    private static Notification.Action stopAction(Context app) {
        Intent stop = new Intent(app, StopReceiver.class);
        stop.setAction(StopReceiver.ACTION_STOP);
        PendingIntent pending = PendingIntent.getBroadcast(app, 1, stop, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Icon icon = Icon.createWithResource(app, android.R.drawable.ic_menu_close_clear_cancel);
        return new Notification.Action.Builder(icon, app.getString(R.string.body_stop), pending).build();
    }

    /** Tapping the notification opens the app (MainActivity is singleTask: the running window comes to the front). */
    private static PendingIntent openApp(Context app) {
        Intent launch = app.getPackageManager().getLaunchIntentForPackage(app.getPackageName());
        if (launch == null) {
            return null;
        }
        return PendingIntent.getActivity(app, 0, launch, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    // ------------------------------------------------------------------------------------------ small helpers
    private static Context appContext(Context context) {
        if (context == null) {
            return null;
        }
        Context app = context.getApplicationContext();
        return app != null ? app : context;
    }

    /** One line, no leading or trailing blanks, at most `max` characters (never cutting a surrogate pair in half). */
    static String clean(String value, int max) {
        if (value == null) {
            return "";
        }
        String text = value.trim().replaceAll("\\s+", " ");
        if (text.length() <= max) {
            return text;
        }
        int end = max;
        if (end > 0 && Character.isHighSurrogate(text.charAt(end - 1))) {
            end--;
        }
        return text.substring(0, end);
    }
}
