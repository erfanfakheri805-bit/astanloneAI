package com.erfan.standaloneai;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Prompt 959 (stage B, the body): the «ایست» button of the background notification.
 *
 * It is declared not exported and the notification's PendingIntent names it explicitly, so only that button can reach it. It does one thing:
 * BodyService.stopFromNotification(...), on a worker thread (Python must not run on the receiver's main thread, and the stop may take a moment).
 */
public class StopReceiver extends BroadcastReceiver {

    static final String ACTION_STOP = "com.erfan.standaloneai.action.EMERGENCY_STOP";

    @Override
    public void onReceive(final Context context, Intent intent) {
        if (intent == null || !ACTION_STOP.equals(intent.getAction())) {
            return;
        }
        final PendingResult pending = goAsync();
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    BodyService.stopFromNotification(context);
                } catch (RuntimeException e) {
                    // the notification stays as it was
                } finally {
                    if (pending != null) {
                        pending.finish();
                    }
                }
            }
        }, "emergency-stop");
        worker.start();
    }
}
