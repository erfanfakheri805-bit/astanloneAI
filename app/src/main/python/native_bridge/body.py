"""
native_bridge.body - the doors of the app's BODY (Prompt 959, stage B)
======================================================================
Three doors that only the APP itself uses (a pack cannot ask for them: their permission names are not in `pack_system.limits.PERMISSIONS`):

    BodyDoor    hold(title, text, percent) / release() / running()   the foreground service (`BodyService.java`): while a long job runs
                                                                    (the own brain's download) Android keeps the app alive and shows ONE
                                                                    notification with a stop button «ایست»
    PhoneDoor   battery_optimization(), app_info(), memory()         facts the access checklist and the self-test report need
    SmsDoor     latest_code(max_age_minutes)                         the user's order «کد پیامک را بخوان»: the newest few messages are
                                                                    searched for a one-time code; only the code, the sender and the age
                                                                    come back - never the message. Needs READ_SMS, which the user grants.
                request_permission()                                 the user's order «مجوز پیامک را بده»: Android's OWN dialog is shown
                                                                    (he taps «اجازه» himself); the app never grants itself anything

The service is started only while the app is on the screen (Android 12+ refuses it from the background - the door then says "not_allowed")
and it stops by itself when the last job ends. It never restarts after Android kills the process (START_NOT_STICKY): the own brain
resumes its download when the user opens the app again.

UNVERIFIED ON DEVICE: written against Android's documented APIs, compile-checked against android.jar (API 34) and exercised against
hand-written fakes only.
"""

import time

from . import otp
from .doors import _Door
from .jvm import MAIN_ACTIVITY
from .result import fail, ok

__all__ = ["BodyDoor", "PhoneDoor", "SmsDoor", "SERVICE_CLASS", "FEATURE_SERVICE", "READ_SMS", "SMS_URI", "MAX_TITLE", "MAX_TEXT"]

SERVICE_CLASS = "com.erfan.standaloneai.BodyService"
FEATURE_SERVICE = "body_service"
READ_SMS = "android.permission.READ_SMS"
SMS_URI = "content://sms/inbox"
MAX_TITLE, MAX_TEXT = 60, 160
MAX_AGE_MINUTES = 120
LOOK_AT = 8                              # how many of the newest messages are looked at (never more)


class BodyDoor(_Door):
    def hold(self, title, text="", percent=-1):
        title = " ".join(str(title or "").split())[:MAX_TITLE]
        text = " ".join(str(text or "").split())[:MAX_TEXT]
        if not title:
            return fail("bad_arguments", "عنوانِ اعلان لازم است.")
        if isinstance(percent, bool) or not isinstance(percent, int) or not -1 <= percent <= 100:
            return fail("bad_arguments", "درصد باید بین ۰ و ۱۰۰ باشد (یا ۱- برای «نامشخص»).")

        def run():
            started = bool(self._jvm.jclass(SERVICE_CLASS).hold(self._jvm.context(), title, text, int(percent)))
            if not started:
                return fail("not_allowed", "اندروید در این لحظه اجازهٔ روشن‌کردنِ سرویسِ پس‌زمینه را نداد (برنامه باید روی صفحه باز باشد).")
            return ok({"running": True})
        return self._run(run, feature=FEATURE_SERVICE)

    def release(self):
        def run():
            self._jvm.jclass(SERVICE_CLASS).release(self._jvm.context())
            return ok({"running": False})
        return self._run(run, feature=FEATURE_SERVICE)

    def running(self):
        def run():
            return ok({"running": bool(self._jvm.jclass(SERVICE_CLASS).isRunning())})
        return self._run(run, feature=FEATURE_SERVICE)


class PhoneDoor(_Door):
    def battery_optimization(self):
        """`{"ignoring": bool, "power_save": bool}` - is this app exempt from Android's battery optimisation («بدون محدودیت»)?"""
        def run():
            ctx = self._jvm.context()
            power = ctx.getSystemService("power")
            if power is None:
                return fail("java_error", "سرویس باتری پیدا نشد.")
            return ok({"ignoring": bool(power.isIgnoringBatteryOptimizations(str(ctx.getPackageName()))),
                       "power_save": bool(power.isPowerSaveMode())})
        return self._run(run)

    def app_info(self):
        """`{"package", "version_name", "version_code", "abis", "sdk"}` - which build is this."""
        def run():
            ctx = self._jvm.context()
            package = str(ctx.getPackageName())
            info = ctx.getPackageManager().getPackageInfo(package, 0)
            sdk = int(self._jvm.sdk_int() or 0)
            code = int(info.getLongVersionCode()) if sdk >= 28 else int(info.versionCode)
            abis = []
            try:
                for abi in self._jvm.jclass("android.os.Build").SUPPORTED_ABIS:
                    abis.append(str(abi)[:20])
            except Exception:
                abis = []
            return ok({"package": package[:100], "version_name": str(info.versionName or "")[:30], "version_code": code, "abis": abis[:6],
                       "sdk": sdk})
        return self._run(run)

    def memory(self):
        """`{"total": bytes, "available": bytes, "low": bool}` - the phone's RAM as Android reports it."""
        def run():
            ctx = self._jvm.context()
            manager = ctx.getSystemService("activity")
            if manager is None:
                return fail("java_error", "سرویس حافظه پیدا نشد.")
            info = self._jvm.jclass("android.app.ActivityManager$MemoryInfo")()
            manager.getMemoryInfo(info)
            return ok({"total": int(info.totalMem), "available": int(info.availMem), "low": bool(info.lowMemory)})
        return self._run(run)


class SmsDoor(_Door):
    def __init__(self, jvm, clock=time.time):
        super().__init__(jvm)
        self._clock = clock

    def has_permission(self):
        """`ok({"granted": bool})` - the READ_SMS permission, without reading anything."""
        def run():
            granted = self._jvm.jclass("androidx.core.content.ContextCompat").checkSelfPermission(self._jvm.context(), READ_SMS)
            return ok({"granted": int(granted) == 0})
        return self._run(run)

    def request_permission(self):
        """Show Android's own dialog for READ_SMS. `ok({"granted": True, "dispatched": False})` when it is given already; `ok({"granted":
        False, "dispatched": True})` when the dialog was shown (the decision is seen later with `has_permission()`); "not_allowed" when the
        screen is not in front. Called only on the user's own order - the app never asks by itself."""
        def run():
            ctx = self._jvm.context()
            granted = self._jvm.jclass("androidx.core.content.ContextCompat").checkSelfPermission(ctx, READ_SMS)
            if int(granted) == 0:
                return ok({"granted": True, "dispatched": False})
            shown = bool(self._jvm.jclass(MAIN_ACTIVITY).requestAndroidPermissions(self._jvm.string_array([READ_SMS])))
            if not shown:
                return fail("not_allowed", "پنجرهٔ مجوز باز نشد؛ برنامه باید روی صفحه باز باشد.")
            return ok({"granted": False, "dispatched": True})
        return self._run(run)

    def latest_code(self, max_age_minutes=15):
        """The one-time code of the newest message (among the newest few) that holds one and is not older than `max_age_minutes`.
        `ok({"code", "sender", "age_seconds", "looked_at"})`, or "empty" when no recent message holds a code, or "permission_denied"
        with `needs=READ_SMS`. The message text is never returned and never kept."""
        if isinstance(max_age_minutes, bool) or not isinstance(max_age_minutes, int) or not 1 <= max_age_minutes <= MAX_AGE_MINUTES:
            return fail("bad_arguments", "عمرِ پیام باید بین ۱ و ۱۲۰ دقیقه باشد.")

        def run():
            ctx = self._jvm.context()
            granted = self._jvm.jclass("androidx.core.content.ContextCompat").checkSelfPermission(ctx, READ_SMS)
            if int(granted) != 0:
                return fail("permission_denied", "برای خواندنِ کدِ پیامک باید مجوزِ «پیامک» را بدهی (فقط وقتی خودت می‌گویی می‌خوانم).", needs=READ_SMS)
            uri = self._jvm.jclass("android.net.Uri").parse(SMS_URI)
            columns = self._jvm.string_array(["address", "body", "date"])
            cursor = ctx.getContentResolver().query(uri, columns, None, None, "date DESC")
            if cursor is None:
                return fail("unavailable", "صندوقِ پیامک در این گوشی خوانده نشد.")
            now_ms, looked, found = int(self._clock() * 1000), 0, None
            try:
                while looked < LOOK_AT and cursor.moveToNext():
                    looked += 1
                    body, date = cursor.getString(1), int(cursor.getLong(2))
                    age = (now_ms - date) // 1000
                    if age > max_age_minutes * 60:
                        break                                         # newest first: everything after this one is older still
                    code = otp.extract_code(str(body or ""))
                    if code:
                        found = {"code": code, "sender": str(cursor.getString(0) or "")[:40], "age_seconds": max(0, int(age)), "looked_at": looked}
                        break
            finally:
                cursor.close()
            if found is None:
                return fail("empty", "در پیامک‌های %d دقیقهٔ اخیر کدِ یک‌بارمصرفی پیدا نشد." % max_age_minutes, data={"looked_at": looked})
            return ok(found)
        return self._run(run)
