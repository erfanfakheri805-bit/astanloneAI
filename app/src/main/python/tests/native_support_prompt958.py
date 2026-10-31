"""
Test support (Prompt 958): a fake Android runtime for `native_bridge`.

`FakeJava` is a `JavaBridge` whose Java classes are small Python classes that record what was done to them, so the doors can be
tested without a phone. It is hand-written from Android's documented API - it proves the DOORS' logic (what they call, what they
refuse, how they report), not that Android behaves like this. Not a test module (no `test_` prefix).
"""

import json
import threading

from native_bridge.jvm import JavaBridge, NativeUnavailable

__all__ = ["FakeJava", "NameNotFoundException", "SecurityException", "ActivityNotFoundException", "make_screen"]


class NameNotFoundException(Exception):
    pass


class SecurityException(Exception):
    pass


class ActivityNotFoundException(Exception):
    pass


class FakeJava(JavaBridge):
    platform_name = "android"

    def __init__(self, sdk=34, features=("file_chooser", "permission_request", "voice_input", "accessibility"), installed=(),
                 clipboard_text=None, granted=("android.permission.POST_NOTIFICATIONS",), tts_status=0, tts_languages=("fa", "en"),
                 screen=None, connected=True, package="com.openai.chatgpt"):
        self.sdk, self.features = sdk, frozenset(features)
        self.installed = set(installed)
        self.granted = set(granted)
        self.started = []                  # intents passed to startActivity
        self.notified = []                 # (id, title, text)
        self.channels = []
        self.spoken = []
        self.tts_status, self.tts_languages = tts_status, set(tts_languages)
        self.clipboard = clipboard_text
        self.voice_started, self.voice_result = [], None
        self.screen = {"package": package, "nodes": [], "truncated": False} if screen is None else screen
        self.connected, self.active_package = connected, package
        self.clicks, self.typed, self.keys, self.scrolls = [], [], [], 0
        self.click_ok, self.type_ok = True, True
        self.raise_on = {}                 # method name -> exception to raise
        self.classes = {}
        self._build()

    # ---- the JavaBridge surface ------------------------------------------------------------------------------------
    def available(self):
        return True

    def jclass(self, name):
        if name not in self.classes:
            raise NativeUnavailable("class_missing", name)
        return self.classes[name]

    def context(self):
        return self.ctx

    def sdk_int(self):
        return self.sdk

    def native_features(self):
        return self.features

    def proxy(self, interface_name, methods):
        class Proxy:
            pass
        obj = Proxy()
        for name, fn in methods.items():
            setattr(obj, name, fn)
        return obj

    def run_on_main(self, fn):
        fn()
        return True

    def string_array(self, items):
        return list(items)

    # ---- the fake classes --------------------------------------------------------------------------------------------
    def _build(self):
        fake = self

        class Uri:
            def __init__(self, text):
                self.text = text

            @staticmethod
            def parse(text):
                return Uri(text)

        class Intent:
            ACTION_SEND, ACTION_VIEW, EXTRA_TEXT, ACTION_BATTERY_CHANGED = "SEND", "VIEW", "EXTRA_TEXT", "BATTERY"

            def __init__(self, action=None, uri=None):
                self.action, self.uri, self.type, self.extras, self.package, self.flags, self.data = action, uri, None, {}, None, 0, None

            def setType(self, value):
                self.type = value
                return self

            def putExtra(self, key, value):
                self.extras[key] = value
                return self

            def setPackage(self, package):
                self.package = package
                return self

            def addFlags(self, flags):
                self.flags |= flags
                return self

            def setData(self, uri):
                self.data = uri
                return self

            def getIntExtra(self, key, default):
                return fake.battery.get(key, default)

            @staticmethod
            def createChooser(intent, title):
                chooser = Intent("CHOOSER")
                chooser.extras["wrapped"], chooser.extras["title"] = intent, title
                return chooser

        class IntentFilter:
            def __init__(self, action):
                self.action = action

        class ClipItem:
            def __init__(self, text):
                self.text = text

            def coerceToText(self, ctx):
                return self.text

        class ClipData:
            def __init__(self, label, text):
                self.label, self.text = label, text

            def getItemCount(self):
                return 1

            def getItemAt(self, index):
                return ClipItem(self.text)

            @staticmethod
            def newPlainText(label, text):
                return ClipData(label, text)

        class ClipboardManager:
            def getPrimaryClip(self):
                return None if fake.clipboard is None else ClipData("x", fake.clipboard)

            def setPrimaryClip(self, clip):
                fake.clipboard = clip.text

        class PackageManager:
            def getPackageInfo(self, package, flags):
                if package not in fake.installed:
                    raise NameNotFoundException(package)
                return object()

            def getLaunchIntentForPackage(self, package):
                return Intent("MAIN") if package in fake.installed else None

        class NotificationManager:
            IMPORTANCE_DEFAULT = 3

            def createNotificationChannel(self, channel):
                fake.channels.append(channel.id)

            def notify(self, nid, notification):
                fake.notified.append((nid, notification.title, notification.text))

        class NotificationChannel:
            def __init__(self, cid, name, importance):
                self.id, self.name, self.importance = cid, name, importance

        class Notification:
            class Builder:
                def __init__(self, ctx, channel=None):
                    self.channel, self.title, self.text, self.icon = channel, None, None, None

                def setSmallIcon(self, icon):
                    self.icon = icon
                    return self

                def setContentTitle(self, title):
                    self.title = title
                    return self

                def setContentText(self, text):
                    self.text = text
                    return self

                def setAutoCancel(self, flag):
                    return self

                def build(self):
                    return self

        class Context:
            def getSystemService(self, name):
                return {"clipboard": ClipboardManager(), "notification": NotificationManager()}.get(name)

            def getPackageManager(self):
                return PackageManager()

            def getPackageName(self):
                return "com.erfan.standaloneai"

            def startActivity(self, intent):
                pending = fake.raise_on.get("startActivity")
                if isinstance(pending, list):             # a list of exceptions is consumed one per call (then calls succeed)
                    if pending:
                        raise pending.pop(0)
                elif pending is not None:
                    raise pending
                fake.started.append(intent)

            def registerReceiver(self, receiver, filt):
                return Intent("BATTERY") if fake.battery else None

        class ContextCompat:
            @staticmethod
            def checkSelfPermission(ctx, name):
                return 0 if name in fake.granted else -1

        class Locale:
            def __init__(self, tag):
                self.tag = tag

            @staticmethod
            def forLanguageTag(tag):
                return Locale(tag)

        class TextToSpeech:
            def __init__(self, ctx, listener):
                self.language, self.rate = None, None
                listener.onInit(fake.tts_status)

            def isLanguageAvailable(self, locale):
                return 0 if locale.tag.split("-")[0] in fake.tts_languages else -2

            def setLanguage(self, locale):
                self.language = locale.tag
                return 0

            def setSpeechRate(self, rate):
                self.rate = rate

            def speak(self, text, mode, bundle, utterance_id):
                fake.spoken.append((text, self.language, self.rate))
                return 0

            def stop(self):
                fake.spoken.append(("<stop>", None, None))

        class MainActivity:
            NATIVE_FEATURES = sorted(fake.features)

            @staticmethod
            def startVoiceInput(lang):
                fake.voice_started.append(lang)
                return "voice_input" in fake.features and "startVoice" not in fake.raise_on

            @staticmethod
            def takeVoiceResult():
                value, fake.voice_result = fake.voice_result, None
                return value

        class Settings:
            ACTION_ACCESSIBILITY_SETTINGS = "ACCESSIBILITY"
            ACTION_APPLICATION_DETAILS_SETTINGS = "APP_DETAILS"
            ACTION_APP_NOTIFICATION_SETTINGS = "APP_NOTIF"
            ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS = "BATTERY_OPT"
            EXTRA_APP_PACKAGE = "EXTRA_APP_PACKAGE"

        class Build:
            MODEL, MANUFACTURER = "TestPhone", "Acme"

        class Version:
            RELEASE, SDK_INT = "14", fake.sdk

        class Drawable:
            stat_notify_chat = 17301646

        class Service:
            @staticmethod
            def isConnected():
                return fake.connected

            @staticmethod
            def activePackage():
                return fake.active_package if fake.connected else ""

            @staticmethod
            def readScreen(limit):
                data = dict(fake.screen)
                data["nodes"] = list(data.get("nodes", []))[:limit]
                return json.dumps(data)

            @staticmethod
            def clickNode(text, exact, view_id, last):
                fake.clicks.append((text, exact, view_id, last))
                return fake.click_ok

            @staticmethod
            def setText(hint, view_id, text):
                fake.typed.append((hint, view_id, text))
                return fake.type_ok

            @staticmethod
            def globalAction(name):
                fake.keys.append(name)
                return True

            @staticmethod
            def scroll(forward):
                fake.scrolls += 1
                return True

        self.battery = {"level": 42, "scale": 100, "status": 2}
        self.ctx = Context()
        self.classes.update({
            "android.net.Uri": Uri, "android.content.Intent": Intent, "android.content.IntentFilter": IntentFilter,
            "android.content.ClipData": ClipData, "androidx.core.content.ContextCompat": ContextCompat,
            "android.app.NotificationManager": NotificationManager, "android.app.NotificationChannel": NotificationChannel,
            "android.app.Notification$Builder": Notification.Builder, "android.R$drawable": Drawable,
            "java.util.Locale": Locale, "android.speech.tts.TextToSpeech": TextToSpeech,
            "android.provider.Settings": Settings, "android.os.Build": Build, "android.os.Build$VERSION": Version,
            "com.erfan.standaloneai.MainActivity": MainActivity, "com.erfan.standaloneai.PyAccessibilityService": Service,
            "android.os.Vibrator": type("Vibrator", (), {})})
        if not self.features:
            self.classes.pop("com.erfan.standaloneai.PyAccessibilityService", None)


def make_screen(package, *texts, editable=None, password=None):
    """A screen as `PyAccessibilityService.readScreen` returns it (compact keys)."""
    nodes = [{"t": text, "d": "", "id": "", "c": "android.widget.TextView", "k": False, "e": False, "f": False, "s": False, "b": [0, i * 10, 100, i * 10 + 9]}
             for i, text in enumerate(texts)]
    if editable is not None:
        nodes.append({"t": editable, "d": "Message", "id": "x:id/input", "c": "android.widget.EditText", "k": True, "e": True, "f": True, "s": False})
    if password is not None:
        nodes.append({"t": password, "d": "", "id": "x:id/pw", "c": "android.widget.EditText", "k": True, "e": True, "f": False, "s": False, "p": True})
    return {"package": package, "nodes": nodes, "truncated": False}
