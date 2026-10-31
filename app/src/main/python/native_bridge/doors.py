"""
native_bridge.doors - the doors a pack (or the app) can open on the phone, through Chaquopy
=========================================================================================
Every door is a small class over a `JavaBridge`. A door call NEVER raises into the caller (except a missing pack permission,
which is the pack author's bug) and NEVER pretends: it answers a `DoorResult` with an exact code.

    ClipboardDoor   get_text / set_text                     (Android 10+ lets only the foreground app read the clipboard)
    ShareDoor       send_text, open_app, open_url, visible, assistants_visible
    SettingsDoor    open_settings("accessibility" | "app" | "notifications" | "battery")
    NotifyDoor      show(title, text)                       (Android 13+: needs the POST_NOTIFICATIONS permission)
    SpeechDoor      speak(text, lang), stop(), availability(lang)       (text to speech; Persian voices depend on the phone)
    VoiceDoor       start(lang), take_result()              (the system's speech dialog, through MainActivity)
    DeviceDoor      battery(), info()

UNVERIFIED ON DEVICE: written against Android's documented APIs and exercised against hand-written fakes only.
"""

import re
import threading

from .jvm import MAIN_ACTIVITY, NativeUnavailable
from .result import DoorPermissionError, fail, ok

__all__ = ["ClipboardDoor", "ShareDoor", "SettingsDoor", "NotifyDoor", "SpeechDoor", "VoiceDoor", "DeviceDoor", "valid_package",
           "valid_https_url", "MAX_CLIPBOARD_CHARS", "MAX_SHARE_CHARS"]

MAX_CLIPBOARD_CHARS = 300_000
MAX_SHARE_CHARS = 100_000                 # an Intent extra travels through Binder (about 1 MB for everything): stay far below
MAX_SPEAK_CHARS = 3900                    # TextToSpeech.getMaxSpeechInputLength() is 4000
NEW_TASK = 0x10000000                     # Intent.FLAG_ACTIVITY_NEW_TASK (the application context is not an Activity)
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){1,8}\Z")
_LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}\Z")
_URL_RE = re.compile(r"^https://[^\s/?#@]+(?:[/?#][^\s]*)?\Z")
CHANNEL_ID = "assistant_default"


def valid_package(name):
    return isinstance(name, str) and len(name) <= 150 and bool(_PACKAGE_RE.match(name))


def valid_https_url(url):
    return isinstance(url, str) and len(url) <= 2000 and bool(_URL_RE.match(url))


def _name(exc):
    return type(exc).__name__


class _Door:
    def __init__(self, jvm):
        self._jvm = jvm

    def _run(self, fn, *, feature=None):
        """Run one door action: every failure becomes a `DoorResult`."""
        try:
            if not self._jvm.available():
                return fail("unavailable_platform", "این قابلیت فقط داخل برنامهٔ اندروید در دسترس است.")
            if feature is not None and not self._has_feature(feature):
                return fail("native_feature_missing", "این نسخهٔ APK این بخش بومی را ندارد؛ فقط با ساختِ APK جدید اضافه می‌شود.", needs=feature)
            return fn()
        except DoorPermissionError:
            raise
        except NativeUnavailable as exc:
            if exc.code == "unavailable_platform":
                return fail("unavailable_platform", "این قابلیت فقط داخل برنامهٔ اندروید در دسترس است.")
            if exc.code in ("class_missing", "no_context"):
                return fail("native_feature_missing", "بخش بومی لازم در این APK نیست.", needs=str(exc.detail or exc.code))
            return fail(exc.code, "")
        except Exception as exc:                       # any Java or Python error: never propagates
            name = _name(exc)
            if name == "SecurityException":
                return fail("permission_denied", "اندروید اجازهٔ این کار را نداد (مجوز لازم داده نشده).", needs="android_permission")
            if name == "ActivityNotFoundException":
                return fail("no_handler", "برنامه‌ای که این کار را انجام دهد پیدا نشد.")
            if name == "NameNotFoundException":
                return fail("not_installed", "این برنامه روی گوشی نیست (یا اندروید اجازهٔ دیدنش را به ما نداده).")
            return fail("java_error", "خطای اندروید: %s" % name)

    def _has_feature(self, feature):
        return feature in self._jvm.native_features()

    def _flags(self, intent):
        intent.addFlags(NEW_TASK)
        return intent


# ============================================================================ clipboard
class ClipboardDoor(_Door):
    def get_text(self):
        def run():
            ctx = self._jvm.context()
            manager = ctx.getSystemService("clipboard")
            if manager is None:
                return fail("java_error", "سرویس کلیپ‌بورد پیدا نشد.")
            clip = manager.getPrimaryClip()
            if clip is None or int(clip.getItemCount()) == 0:
                return fail("empty", "کلیپ‌بورد خالی است (یا اندروید اجازهٔ خواندنش را وقتی برنامه جلو نیست نمی‌دهد).")
            text = clip.getItemAt(0).coerceToText(ctx)
            value = str(text) if text is not None else ""
            if not value.strip():
                return fail("empty", "در کلیپ‌بورد متنی نیست.")
            truncated = len(value) > MAX_CLIPBOARD_CHARS
            return ok({"text": value[:MAX_CLIPBOARD_CHARS], "truncated": truncated})
        return self._run(run)

    def set_text(self, text, label="دستیار هوشمند"):
        if not isinstance(text, str) or not text:
            return fail("bad_arguments", "متنی برای گذاشتن در کلیپ‌بورد نیست.")
        if len(text) > MAX_CLIPBOARD_CHARS:
            return fail("too_large", "متن برای کلیپ‌بورد بزرگ است.")

        def run():
            ctx = self._jvm.context()
            manager = ctx.getSystemService("clipboard")
            if manager is None:
                return fail("java_error", "سرویس کلیپ‌بورد پیدا نشد.")
            clip = self._jvm.jclass("android.content.ClipData").newPlainText(str(label)[:60], text)
            manager.setPrimaryClip(clip)
            return ok({"chars": len(text)})
        return self._run(run)


# ============================================================================ share / open
class ShareDoor(_Door):
    def visible(self, package):
        """Is the app installed AND visible to us? (Android 11+ hides other apps unless the manifest's <queries> names them.)"""
        if not valid_package(package):
            return fail("bad_arguments", "نام بستهٔ برنامه معتبر نیست.")

        def run():
            self._jvm.context().getPackageManager().getPackageInfo(package, 0)
            return ok({"package": package})
        return self._run(run)

    def assistants_visible(self, packages):
        """The subset of `packages` that is installed and visible, in the given order."""
        found = []
        for package in list(packages)[:40]:
            if valid_package(package) and self.visible(package).ok:
                found.append(package)
        return found

    def open_app(self, package):
        if not valid_package(package):
            return fail("bad_arguments", "نام بستهٔ برنامه معتبر نیست.")

        def run():
            ctx = self._jvm.context()
            intent = ctx.getPackageManager().getLaunchIntentForPackage(package)
            if intent is None:
                return fail("not_installed", "این برنامه روی گوشی نیست یا اندروید اجازهٔ دیدنش را نداده.")
            ctx.startActivity(self._flags(intent))
            return ok({"package": package})
        return self._run(run)

    def send_text(self, text, package=None, chooser_title="ارسال به…"):
        if not isinstance(text, str) or not text.strip():
            return fail("bad_arguments", "متنی برای ارسال نیست.")
        if len(text) > MAX_SHARE_CHARS:
            return fail("too_large", "متن برای اشتراک‌گذاری از طریق اندروید بزرگ است (حداکثر %d نویسه)." % MAX_SHARE_CHARS)
        if package is not None and not valid_package(package):
            return fail("bad_arguments", "نام بستهٔ برنامه معتبر نیست.")

        def run():
            ctx = self._jvm.context()
            intent_cls = self._jvm.jclass("android.content.Intent")
            intent = intent_cls(intent_cls.ACTION_SEND)
            intent.setType("text/plain")
            intent.putExtra(intent_cls.EXTRA_TEXT, text)
            if package:
                intent.setPackage(package)
                ctx.startActivity(self._flags(intent))
            else:
                chooser = intent_cls.createChooser(intent, str(chooser_title)[:60])
                ctx.startActivity(self._flags(chooser))
            return ok({"package": package or "", "chars": len(text)})
        return self._run(run)

    def open_url(self, url):
        if not valid_https_url(url):
            return fail("bad_arguments", "فقط نشانی https معتبر باز می‌شود.")

        def run():
            ctx = self._jvm.context()
            intent_cls = self._jvm.jclass("android.content.Intent")
            uri = self._jvm.jclass("android.net.Uri").parse(url)
            ctx.startActivity(self._flags(intent_cls(intent_cls.ACTION_VIEW, uri)))
            return ok({"url": url})
        return self._run(run)


# ============================================================================ settings pages
class SettingsDoor(_Door):
    _KINDS = {"accessibility": "ACTION_ACCESSIBILITY_SETTINGS", "app": "ACTION_APPLICATION_DETAILS_SETTINGS",
              "notifications": "ACTION_APP_NOTIFICATION_SETTINGS", "battery": "ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS"}

    def open_settings(self, kind):
        if kind not in self._KINDS:
            return fail("bad_arguments", "صفحهٔ تنظیمات ناشناخته است.")

        def run():
            ctx = self._jvm.context()
            settings = self._jvm.jclass("android.provider.Settings")
            intent_cls = self._jvm.jclass("android.content.Intent")
            intent = intent_cls(getattr(settings, self._KINDS[kind]))
            if kind == "app":
                intent.setData(self._jvm.jclass("android.net.Uri").parse("package:" + str(ctx.getPackageName())))
            elif kind == "notifications":
                intent.putExtra(settings.EXTRA_APP_PACKAGE, str(ctx.getPackageName()))
            ctx.startActivity(self._flags(intent))
            return ok({"kind": kind})
        return self._run(run)


# ============================================================================ notifications
class NotifyDoor(_Door):
    POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"

    def show(self, title, text, notification_id=1001):
        title, text = " ".join(str(title or "").split())[:80], str(text or "").strip()[:400]
        if not title or not text:
            return fail("bad_arguments", "عنوان و متن اعلان لازم است.")
        if not isinstance(notification_id, int) or isinstance(notification_id, bool) or not 1000 <= notification_id <= 1999:
            return fail("bad_arguments", "شناسهٔ اعلان باید بین ۱۰۰۰ و ۱۹۹۹ باشد.")

        def run():
            ctx = self._jvm.context()
            sdk = self._jvm.sdk_int() or 0
            if sdk >= 33:
                granted = self._jvm.jclass("androidx.core.content.ContextCompat").checkSelfPermission(ctx, self.POST_NOTIFICATIONS)
                if int(granted) != 0:
                    return fail("permission_denied", "برای اعلان در اندروید ۱۳ به بالا باید مجوز اعلان را بدهی.", needs=self.POST_NOTIFICATIONS)
            manager = ctx.getSystemService("notification")
            if manager is None:
                return fail("java_error", "سرویس اعلان پیدا نشد.")
            builder_cls = self._jvm.jclass("android.app.Notification$Builder")
            if sdk >= 26:
                channel_cls = self._jvm.jclass("android.app.NotificationChannel")
                importance = self._jvm.jclass("android.app.NotificationManager").IMPORTANCE_DEFAULT
                manager.createNotificationChannel(channel_cls(CHANNEL_ID, "دستیار هوشمند", importance))
                builder = builder_cls(ctx, CHANNEL_ID)
            else:
                builder = builder_cls(ctx)
            icon = self._jvm.jclass("android.R$drawable").stat_notify_chat
            builder.setSmallIcon(icon)
            builder.setContentTitle(title)
            builder.setContentText(text)
            builder.setAutoCancel(True)
            manager.notify(notification_id, builder.build())
            return ok({"id": notification_id})
        return self._run(run)


# ============================================================================ text to speech
class SpeechDoor(_Door):
    def __init__(self, jvm):
        super().__init__(jvm)
        self._tts = None
        self._status = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def _on_init(self, status):
        self._status = int(status)
        self._ready.set()

    def _engine(self, wait_seconds=6.0):
        with self._lock:
            if self._tts is None:
                listener = self._jvm.proxy("android.speech.tts.TextToSpeech$OnInitListener", {"onInit": self._on_init})
                self._tts = self._jvm.jclass("android.speech.tts.TextToSpeech")(self._jvm.context(), listener)
        if not self._ready.wait(wait_seconds):
            return None
        return self._tts if self._status == 0 else None          # TextToSpeech.SUCCESS == 0

    def availability(self, lang="fa"):
        if not isinstance(lang, str) or not _LANG_RE.match(lang):
            return fail("bad_arguments", "کد زبان معتبر نیست.")

        def run():
            engine = self._engine()
            if engine is None:
                return fail("unavailable", "موتور گفتار روی این گوشی آماده نشد.")
            locale = self._jvm.jclass("java.util.Locale").forLanguageTag(lang)
            level = int(engine.isLanguageAvailable(locale))      # >= 0: available; -1 missing data; -2 not supported
            return ok({"lang": lang, "level": level, "available": level >= 0})
        return self._run(run)

    def speak(self, text, lang="fa", rate=1.0):
        text = str(text or "").strip()
        if not text:
            return fail("bad_arguments", "متنی برای خواندن نیست.")
        if not isinstance(lang, str) or not _LANG_RE.match(lang):
            return fail("bad_arguments", "کد زبان معتبر نیست.")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not 0.3 <= float(rate) <= 3.0:
            return fail("bad_arguments", "سرعت خواندن باید بین ۰٫۳ و ۳ باشد.")

        def run():
            engine = self._engine()
            if engine is None:
                return fail("unavailable", "موتور گفتار روی این گوشی آماده نشد.")
            locale = self._jvm.jclass("java.util.Locale").forLanguageTag(lang)
            if int(engine.isLanguageAvailable(locale)) < 0:
                return fail("language_unavailable", "صدای این زبان روی گوشی نصب نیست؛ از تنظیمات «تبدیل متن به گفتار» می‌شود افزود.", needs="tts_voice:" + lang)
            engine.setLanguage(locale)
            engine.setSpeechRate(float(rate))
            engine.speak(text[:MAX_SPEAK_CHARS], 0, None, "utt")          # QUEUE_FLUSH
            return ok({"chars": min(len(text), MAX_SPEAK_CHARS)})
        return self._run(run)

    def stop(self):
        def run():
            if self._tts is not None and self._ready.is_set():
                self._tts.stop()
            return ok()
        return self._run(run)


# ============================================================================ voice input (the system's dialog)
class VoiceDoor(_Door):
    FEATURE = "voice_input"

    def start(self, lang="fa-IR"):
        if not isinstance(lang, str) or not _LANG_RE.match(lang):
            return fail("bad_arguments", "کد زبان معتبر نیست.")

        def run():
            dispatched = bool(self._jvm.jclass(MAIN_ACTIVITY).startVoiceInput(lang))
            if not dispatched:
                return fail("no_handler", "پنجرهٔ تشخیص گفتار باز نشد (برنامهٔ گوگل یا سرویس گفتار لازم است، یا صفحه جلو نیست).")
            return ok({"lang": lang}, "پنجرهٔ تشخیص گفتار باز شد؛ نتیجه بعد از حرف زدنِ تو می‌رسد.")
        return self._run(run, feature=self.FEATURE)

    def take_result(self):
        def run():
            value = self._jvm.jclass(MAIN_ACTIVITY).takeVoiceResult()
            text = str(value) if value is not None else ""
            if not text.strip():
                return fail("empty", "هنوز نتیجه‌ای از تشخیص گفتار نرسیده است.")
            return ok({"text": text[:4000]})
        return self._run(run, feature=self.FEATURE)


# ============================================================================ device facts
class DeviceDoor(_Door):
    def battery(self):
        def run():
            ctx = self._jvm.context()
            intent_cls = self._jvm.jclass("android.content.Intent")
            filt = self._jvm.jclass("android.content.IntentFilter")(intent_cls.ACTION_BATTERY_CHANGED)
            sticky = ctx.registerReceiver(None, filt)
            if sticky is None:
                return fail("unavailable", "وضعیت باتری خوانده نشد.")
            level, scale = int(sticky.getIntExtra("level", -1)), int(sticky.getIntExtra("scale", -1))
            status = int(sticky.getIntExtra("status", -1))
            if level < 0 or scale <= 0:
                return fail("unavailable", "وضعیت باتری خوانده نشد.")
            return ok({"percent": int(round(100.0 * level / scale)), "charging": status in (2, 5)})   # CHARGING / FULL
        return self._run(run)

    def info(self):
        def run():
            build = self._jvm.jclass("android.os.Build")
            version = self._jvm.jclass("android.os.Build$VERSION")
            return ok({"model": str(build.MODEL)[:60], "manufacturer": str(build.MANUFACTURER)[:40],
                       "android": str(version.RELEASE)[:20], "sdk": int(version.SDK_INT)})
        return self._run(run)
