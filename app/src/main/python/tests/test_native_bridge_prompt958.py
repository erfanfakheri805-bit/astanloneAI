"""Prompt 958 - native_bridge: the doors from the app's Python to the phone, tested against a hand-written fake Android."""

import json
import threading
import unittest

from native_bridge import doors, facade, rawjvm, screen
from native_bridge.jvm import ChaquopyJava, NativeUnavailable, NullJava, detect_jvm, valid_class_name
from native_bridge.result import DoorPermissionError, DoorResult, fail, ok
from tests.native_support_prompt958 import (ActivityNotFoundException, FakeJava, SecurityException, make_screen)


class ClipboardTests(unittest.TestCase):
    def test_get_and_set(self):
        jvm = FakeJava(clipboard_text="سلام")
        door = doors.ClipboardDoor(jvm)
        got = door.get_text()
        self.assertTrue(got.ok)
        self.assertEqual(got.data, {"text": "سلام", "truncated": False})
        self.assertTrue(door.set_text("متن تازه").ok)
        self.assertEqual(door.get_text().data["text"], "متن تازه")

    def test_empty_clipboard_is_reported_not_faked(self):
        for value in (None, "   "):
            r = doors.ClipboardDoor(FakeJava(clipboard_text=value)).get_text()
            self.assertFalse(r.ok)
            self.assertEqual(r.code, "empty")

    def test_big_text_is_truncated_and_refused_on_set(self):
        door = doors.ClipboardDoor(FakeJava(clipboard_text="x" * (doors.MAX_CLIPBOARD_CHARS + 5)))
        r = door.get_text()
        self.assertTrue(r.data["truncated"])
        self.assertEqual(len(r.data["text"]), doors.MAX_CLIPBOARD_CHARS)
        self.assertEqual(door.set_text("y" * (doors.MAX_CLIPBOARD_CHARS + 1)).code, "too_large")
        self.assertEqual(door.set_text("").code, "bad_arguments")
        self.assertEqual(door.set_text(5).code, "bad_arguments")


class ShareTests(unittest.TestCase):
    def test_send_text_to_a_package(self):
        jvm = FakeJava(installed={"com.anthropic.claude"})
        r = doors.ShareDoor(jvm).send_text("پرسش", package="com.anthropic.claude")
        self.assertTrue(r.ok)
        intent = jvm.started[0]
        self.assertEqual((intent.action, intent.type, intent.package), ("SEND", "text/plain", "com.anthropic.claude"))
        self.assertEqual(intent.extras["EXTRA_TEXT"], "پرسش")
        self.assertTrue(intent.flags & doors.NEW_TASK)

    def test_send_text_without_package_uses_the_chooser(self):
        jvm = FakeJava()
        self.assertTrue(doors.ShareDoor(jvm).send_text("سلام").ok)
        chooser = jvm.started[0]
        self.assertEqual(chooser.action, "CHOOSER")
        self.assertEqual(chooser.extras["wrapped"].extras["EXTRA_TEXT"], "سلام")
        self.assertTrue(chooser.flags & doors.NEW_TASK)

    def test_send_text_validation(self):
        door = doors.ShareDoor(FakeJava())
        self.assertEqual(door.send_text("").code, "bad_arguments")
        self.assertEqual(door.send_text("x" * (doors.MAX_SHARE_CHARS + 1)).code, "too_large")
        self.assertEqual(door.send_text("x", package="not a package").code, "bad_arguments")
        self.assertEqual(door.send_text("x", package="../etc").code, "bad_arguments")

    def test_no_handler_is_reported(self):
        jvm = FakeJava()
        jvm.raise_on["startActivity"] = ActivityNotFoundException("none")
        r = doors.ShareDoor(jvm).send_text("x", package="com.example.none")
        self.assertEqual(r.code, "no_handler")

    def test_open_app(self):
        jvm = FakeJava(installed={"com.openai.chatgpt"})
        door = doors.ShareDoor(jvm)
        self.assertTrue(door.open_app("com.openai.chatgpt").ok)
        self.assertTrue(jvm.started[0].flags & doors.NEW_TASK)
        r = door.open_app("com.anthropic.claude")
        self.assertEqual(r.code, "not_installed")
        self.assertEqual(door.open_app("bad name").code, "bad_arguments")

    def test_visible_and_assistants_visible(self):
        door = doors.ShareDoor(FakeJava(installed={"a.b", "c.d"}))
        self.assertTrue(door.visible("a.b").ok)
        self.assertEqual(door.visible("x.y").code, "not_installed")
        self.assertEqual(door.assistants_visible(["x.y", "c.d", "a.b", "bad name"]), ["c.d", "a.b"])

    def test_open_url_only_https(self):
        jvm = FakeJava()
        door = doors.ShareDoor(jvm)
        self.assertTrue(door.open_url("https://example.com/a?b=1").ok)
        self.assertEqual((jvm.started[0].action, jvm.started[0].uri.text), ("VIEW", "https://example.com/a?b=1"))
        for bad in ("http://example.com", "javascript:alert(1)", "https://user:pw@example.com", "file:///etc/passwd", "https://", "https://a b.com", ""):
            self.assertEqual(door.open_url(bad).code, "bad_arguments", bad)

    def test_valid_package_and_url_helpers(self):
        self.assertTrue(doors.valid_package("com.openai.chatgpt"))
        self.assertTrue(doors.valid_package("ai.perplexity.app.android"))
        for bad in ("", "a", "1a.b", "a..b", "a.b c", "a.b;rm", None, 5, "a." + "b" * 200):
            self.assertFalse(doors.valid_package(bad), bad)
        self.assertTrue(doors.valid_https_url("https://example.com"))
        self.assertFalse(doors.valid_https_url("https://example.com/\n"))


class SettingsTests(unittest.TestCase):
    def test_pages(self):
        jvm = FakeJava()
        door = doors.SettingsDoor(jvm)
        for kind, action in (("accessibility", "ACCESSIBILITY"), ("app", "APP_DETAILS"), ("notifications", "APP_NOTIF"), ("battery", "BATTERY_OPT")):
            self.assertTrue(door.open_settings(kind).ok, kind)
            self.assertEqual(jvm.started[-1].action, action)
        self.assertEqual(jvm.started[1].data.text, "package:com.erfan.standaloneai")
        self.assertEqual(jvm.started[2].extras["EXTRA_APP_PACKAGE"], "com.erfan.standaloneai")
        self.assertEqual(door.open_settings("wifi").code, "bad_arguments")


class NotifyTests(unittest.TestCase):
    def test_shows_with_channel_on_modern_android(self):
        jvm = FakeJava(sdk=34)
        r = doors.NotifyDoor(jvm).show("عنوان", "متن")
        self.assertTrue(r.ok)
        self.assertEqual(jvm.channels, [doors.CHANNEL_ID])
        self.assertEqual(jvm.notified, [(1001, "عنوان", "متن")])

    def test_needs_the_runtime_permission_from_android_13(self):
        jvm = FakeJava(sdk=34, granted=())
        r = doors.NotifyDoor(jvm).show("t", "x")
        self.assertEqual((r.ok, r.code, r.needs), (False, "permission_denied", "android.permission.POST_NOTIFICATIONS"))
        self.assertEqual(jvm.notified, [])

    def test_old_android_has_no_channel_and_no_permission(self):
        jvm = FakeJava(sdk=24, granted=())
        self.assertTrue(doors.NotifyDoor(jvm).show("t", "x").ok)
        self.assertEqual(jvm.channels, [])

    def test_validation(self):
        door = doors.NotifyDoor(FakeJava())
        self.assertEqual(door.show("", "x").code, "bad_arguments")
        self.assertEqual(door.show("t", "").code, "bad_arguments")
        self.assertEqual(door.show("t", "x", notification_id=5).code, "bad_arguments")
        self.assertEqual(door.show("t", "x", notification_id=True).code, "bad_arguments")


class SpeechTests(unittest.TestCase):
    def test_speak(self):
        jvm = FakeJava()
        door = doors.SpeechDoor(jvm)
        r = door.speak("سلام دنیا", lang="fa", rate=1.2)
        self.assertTrue(r.ok)
        self.assertEqual(jvm.spoken, [("سلام دنیا", "fa", 1.2)])
        door.stop()
        self.assertEqual(jvm.spoken[-1][0], "<stop>")

    def test_missing_voice_is_reported(self):
        jvm = FakeJava(tts_languages=("en",))
        r = doors.SpeechDoor(jvm).speak("سلام", lang="fa")
        self.assertEqual(r.code, "language_unavailable")
        self.assertEqual(r.needs, "tts_voice:fa")
        self.assertEqual(jvm.spoken, [])
        self.assertTrue(doors.SpeechDoor(jvm).availability("en").data["available"])
        self.assertFalse(doors.SpeechDoor(jvm).availability("fa").data["available"])

    def test_engine_that_failed_to_start(self):
        r = doors.SpeechDoor(FakeJava(tts_status=-1)).speak("سلام")
        self.assertEqual(r.code, "unavailable")

    def test_long_text_is_cut_and_arguments_checked(self):
        jvm = FakeJava()
        door = doors.SpeechDoor(jvm)
        door.speak("a" * 9000, lang="en")
        self.assertEqual(len(jvm.spoken[0][0]), doors.MAX_SPEAK_CHARS)
        self.assertEqual(door.speak("").code, "bad_arguments")
        self.assertEqual(door.speak("x", lang="Persian!").code, "bad_arguments")
        self.assertEqual(door.speak("x", rate=0.01).code, "bad_arguments")
        self.assertEqual(door.speak("x", rate=True).code, "bad_arguments")


class VoiceTests(unittest.TestCase):
    def test_start_and_result(self):
        jvm = FakeJava()
        door = doors.VoiceDoor(jvm)
        self.assertTrue(door.start("fa-IR").ok)
        self.assertEqual(jvm.voice_started, ["fa-IR"])
        self.assertEqual(door.take_result().code, "empty")
        jvm.voice_result = "یک عکس بساز"
        self.assertEqual(door.take_result().data, {"text": "یک عکس بساز"})
        self.assertEqual(door.take_result().code, "empty")

    def test_an_apk_without_the_feature_says_so(self):
        r = doors.VoiceDoor(FakeJava(features=("file_chooser",))).start()
        self.assertEqual((r.ok, r.code, r.needs), (False, "native_feature_missing", "voice_input"))

    def test_dialog_that_could_not_open(self):
        jvm = FakeJava()
        jvm.raise_on["startVoice"] = True
        self.assertEqual(doors.VoiceDoor(jvm).start().code, "no_handler")
        self.assertEqual(doors.VoiceDoor(FakeJava()).start("persian").code, "bad_arguments")


class DeviceTests(unittest.TestCase):
    def test_battery_and_info(self):
        door = doors.DeviceDoor(FakeJava())
        self.assertEqual(door.battery().data, {"percent": 42, "charging": True})
        info = door.info().data
        self.assertEqual((info["model"], info["sdk"]), ("TestPhone", 34))

    def test_battery_unreadable(self):
        jvm = FakeJava()
        jvm.battery = {}
        self.assertEqual(doors.DeviceDoor(jvm).battery().code, "unavailable")


class ErrorHandlingTests(unittest.TestCase):
    def test_security_exception_becomes_permission_denied(self):
        jvm = FakeJava()
        jvm.raise_on["startActivity"] = SecurityException("no")
        r = doors.ShareDoor(jvm).send_text("x", package="a.b")
        self.assertEqual(r.code, "permission_denied")

    def test_unknown_java_error_never_propagates(self):
        jvm = FakeJava()
        jvm.raise_on["startActivity"] = RuntimeError("boom")
        r = doors.ShareDoor(jvm).send_text("x", package="a.b")
        self.assertEqual((r.ok, r.code), (False, "java_error"))
        self.assertIn("RuntimeError", r.detail_fa)

    def test_null_java_answers_everywhere_without_raising(self):
        jvm = NullJava()
        calls = (doors.ClipboardDoor(jvm).get_text, lambda: doors.ClipboardDoor(jvm).set_text("x"), doors.DeviceDoor(jvm).battery,
                 lambda: doors.ShareDoor(jvm).open_app("a.b"), lambda: doors.ShareDoor(jvm).send_text("x"),
                 lambda: doors.NotifyDoor(jvm).show("t", "x"), lambda: doors.SpeechDoor(jvm).speak("x"),
                 lambda: doors.VoiceDoor(jvm).start(), lambda: screen.ScreenDoor(jvm).read(), lambda: doors.SettingsDoor(jvm).open_settings("app"))
        for call in calls:
            r = call()
            self.assertEqual((r.ok, r.code), (False, "unavailable_platform"))


class ScreenTests(unittest.TestCase):
    def door(self, jvm, allowed=("com.openai.chatgpt",)):
        return screen.ScreenDoor(jvm, lambda: frozenset(allowed))

    def test_not_enabled(self):
        jvm = FakeJava(connected=False)
        d = self.door(jvm)
        self.assertEqual(d.read().code, "not_enabled")
        self.assertEqual(d.read().needs, "accessibility_service")
        self.assertEqual(d.status().data, {"enabled": False, "package": ""})

    def test_only_an_allowed_app_is_read(self):
        jvm = FakeJava(package="com.example.bank", screen=make_screen("com.example.bank", "balance 1000"))
        r = self.door(jvm).read()
        self.assertEqual((r.ok, r.code, r.needs), (False, "not_allowed", "user_allow:com.example.bank"))
        self.assertEqual(self.door(jvm, allowed=("com.example.bank",)).read().data["texts"], ["balance 1000"])

    def test_hard_deny_even_when_allowed(self):
        for package in sorted(screen.HARD_DENY):
            jvm = FakeJava(package=package, screen=make_screen(package, "x"))
            d = self.door(jvm, allowed=(package,))
            for r in (d.read(), d.click("OK"), d.set_text("x"), d.scroll()):
                self.assertEqual(r.code, "not_allowed", package)
            self.assertEqual(jvm.clicks, [])
            self.assertEqual(jvm.typed, [])

    def test_password_text_is_never_returned(self):
        jvm = FakeJava(screen=make_screen("com.openai.chatgpt", "hello", editable="draft", password="hunter2"))
        data = self.door(jvm).read().data
        flat = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("hunter2", flat)
        self.assertEqual(sum(1 for n in data["nodes"] if n["password"]), 1)
        self.assertEqual(data["texts"], ["hello"])           # editable and password fields are not "screen text"

    def test_read_is_bounded_and_clean(self):
        texts = ["t%d" % i for i in range(400)]
        jvm = FakeJava(screen=make_screen("com.openai.chatgpt", *texts))
        data = self.door(jvm).read(max_nodes=50).data
        self.assertEqual(len(data["nodes"]), 50)
        self.assertEqual(self.door(jvm).read(max_nodes=0).code, "bad_arguments")
        self.assertEqual(self.door(jvm).read(max_nodes=screen.MAX_NODES + 1).code, "bad_arguments")
        self.assertEqual(self.door(jvm).read(max_nodes=True).code, "bad_arguments")

    def test_damaged_service_output_is_not_trusted(self):
        jvm = FakeJava()
        jvm.classes["com.erfan.standaloneai.PyAccessibilityService"].readScreen = staticmethod(lambda n: "not json")
        self.assertEqual(self.door(jvm).read().code, "java_error")
        jvm.classes["com.erfan.standaloneai.PyAccessibilityService"].readScreen = staticmethod(lambda n: json.dumps([1, 2]))
        self.assertEqual(self.door(jvm).read().data["nodes"], [])

    def test_click_type_key_scroll(self):
        jvm = FakeJava()
        d = self.door(jvm)
        self.assertTrue(d.click("Send", exact=True).ok)
        self.assertEqual(jvm.clicks, [("Send", True, "", False)])
        self.assertTrue(d.click("Copy", last=True).ok)
        self.assertEqual(jvm.clicks[-1], ("Copy", False, "", True))
        self.assertTrue(d.set_text("hello", hint="Message").ok)
        self.assertEqual(jvm.typed, [("Message", "", "hello")])
        self.assertTrue(d.key("back").ok)
        self.assertTrue(d.scroll(True).ok)
        self.assertEqual((jvm.keys, jvm.scrolls), (["back"], 1))
        jvm.click_ok = False
        self.assertEqual(d.click("Nope").code, "not_found")
        self.assertEqual(d.click("").code, "bad_arguments")
        self.assertEqual(d.key("power").code, "bad_arguments")
        self.assertEqual(d.set_text("x" * 20000).code, "too_large")

    def test_keys_need_the_service_but_not_an_allowed_app(self):
        jvm = FakeJava(package="com.example.other")
        self.assertTrue(self.door(jvm).key("home").ok)
        self.assertEqual(self.door(FakeJava(connected=False)).key("home").code, "not_enabled")

    def test_an_apk_without_the_service_says_so(self):
        jvm = FakeJava(features=("file_chooser",))
        r = self.door(jvm).read()
        self.assertEqual((r.code, r.needs), ("native_feature_missing", "accessibility"))


class RawJvmTests(unittest.TestCase):
    def test_allow_and_deny(self):
        allowed = ("android.os.Vibrator", "android.net.Uri", "android.media.MediaPlayer", "androidx.core.app.NotificationManagerCompat",
                   "java.util.ArrayList", "org.json.JSONObject", "com.erfan.standaloneai.MainActivity", "java.lang.String")
        denied = ("java.lang.Runtime", "java.lang.ProcessBuilder", "java.lang.System", "java.lang.Class", "java.lang.reflect.Method",
                  "dalvik.system.DexClassLoader", "android.webkit.WebView", "android.net.http.HttpEngine", "android.net.wifi.WifiManager",
                  "android.app.DownloadManager", "android.app.admin.DevicePolicyManager", "android.content.pm.PackageInstaller",
                  "java.net.URL", "java.io.File", "android.accounts.AccountManager", "android.os.Process", "x", "", None, "a b.C",
                  "com.erfan.standaloneai.PyAccessibilityService", "com.erfan.standaloneai.PyAccessibilityService$Anything")
        for name in allowed:
            self.assertTrue(rawjvm.class_allowed(name), name)
        for name in denied:
            self.assertFalse(rawjvm.class_allowed(name), name)

    def test_jclass_refuses_a_denied_class(self):
        raw = rawjvm.RawJvm(FakeJava())
        self.assertIsNotNone(raw.jclass("android.os.Vibrator"))
        with self.assertRaises(PermissionError):
            raw.jclass("java.lang.Runtime")
        with self.assertRaises(NativeUnavailable):
            raw.jclass("android.os.Nothing")


class FakeHub:
    def __init__(self):
        self.entries = []
        outer = self

        class Audit:
            def append(self, kind, subject, detail=None):
                outer.entries.append((kind, subject, detail))
        self.audit = Audit()


class FacadeTests(unittest.TestCase):
    def setUp(self):
        facade.reset_for_tests()
        self.addCleanup(facade.reset_for_tests)
        self.jvm = FakeJava(installed={"com.openai.chatgpt"}, clipboard_text="secret clipboard text")
        self.hub = FakeHub()

    def doors(self, permissions, clock=None):
        kwargs = {"clock": clock} if clock else {}
        return facade.Doors("demo_pack", permissions, self.hub, self.jvm, **kwargs)

    def test_each_door_needs_its_permission(self):
        d = self.doors(["android"])
        self.assertTrue(d.device.battery().ok)
        for name in ("clipboard", "screen", "jvm"):
            with self.assertRaises(DoorPermissionError, msg=name):
                getattr(d, name)
        d2 = self.doors(["clipboard"])
        self.assertTrue(d2.clipboard.get_text().ok)
        with self.assertRaises(DoorPermissionError):
            d2.notify
        self.assertIsNotNone(self.doors(["unsafe_native"]).jvm)
        self.assertIsNotNone(self.doors(["screen"]).screen)

    def test_private_names_are_not_reachable(self):
        d = self.doors(["android"])
        door = d.share
        for attr in ("_door", "_owner", "_jvm", "__class__x"):
            with self.assertRaises(AttributeError):
                getattr(door, attr)
        with self.assertRaises(AttributeError):
            door.no_such_method

    def test_audit_never_contains_the_content(self):
        d = self.doors(["android", "clipboard"])
        d.notify.show("عنوان خصوصی", "متن خصوصی اعلان")
        d.clipboard.set_text("رمز عبور من")
        d.share.send_text("پیام محرمانه", package="com.openai.chatgpt")
        flat = json.dumps(self.hub.entries, ensure_ascii=False)
        for secret in ("عنوان خصوصی", "متن خصوصی اعلان", "رمز عبور من", "پیام محرمانه"):
            self.assertNotIn(secret, flat)
        self.assertEqual([e[0] for e in self.hub.entries], ["native.notify", "native.clipboard", "native.share"])
        self.assertTrue(all(e[1] == "demo_pack" for e in self.hub.entries))

    def test_quiet_reads_are_not_audited(self):
        d = self.doors(["android", "clipboard", "screen"])
        facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        d.clipboard.get_text()
        d.device.battery()
        d.screen.read()
        self.assertEqual(self.hub.entries, [])

    def test_rate_limit(self):
        now = [1000.0]
        d = self.doors(["android"], clock=lambda: now[0])
        calls, seconds = facade.RATE_LIMITS["notify"]
        for _ in range(calls):
            self.assertTrue(d.notify.show("t", "x").ok)
        r = d.notify.show("t", "x")
        self.assertEqual((r.ok, r.code), (False, "rate_limited"))
        now[0] += seconds + 1
        self.assertTrue(d.notify.show("t", "x").ok)

    def test_rate_limits_are_per_pack(self):
        a = facade.Doors("pack_a", ["android"], self.hub, self.jvm)
        b = facade.Doors("pack_b", ["android"], self.hub, self.jvm)
        for _ in range(facade.RATE_LIMITS["notify"][0]):
            a.notify.show("t", "x")
        self.assertEqual(a.notify.show("t", "x").code, "rate_limited")
        self.assertTrue(b.notify.show("t", "x").ok)

    def test_the_allowed_apps_come_from_the_provider(self):
        jvm = FakeJava(screen=make_screen("com.openai.chatgpt", "hi"))
        d = facade.Doors("p", ["screen"], self.hub, jvm)
        self.assertEqual(d.screen.read().code, "not_allowed")
        facade.set_allowed_apps_provider(lambda: {"com.openai.chatgpt"})
        self.assertEqual(d.screen.read().data["texts"], ["hi"])
        facade.set_allowed_apps_provider(lambda: 1 / 0)               # a failing provider means "nothing is allowed"
        self.assertEqual(d.screen.read().code, "not_allowed")

    def test_the_tts_engine_is_created_once(self):
        d = self.doors(["android"])
        d.speech.speak("سلام")
        d.speech.speak("دوباره")
        self.assertEqual(len(self.jvm.spoken), 2)

    def test_for_app_has_every_door_but_the_unsafe_one(self):
        d = facade.for_app(self.hub, jvm=self.jvm)
        self.assertTrue(d.device.battery().ok)
        self.assertTrue(d.clipboard.get_text().ok)
        self.assertIsNotNone(d.screen)
        with self.assertRaises(DoorPermissionError):
            d.jvm

    def test_platform_facts(self):
        facts = self.doors(["android"]).platform()
        self.assertEqual(facts["platform"], "android")
        self.assertIn("voice_input", facts["native_features"])
        self.assertEqual(facade.Doors("p", [], None, NullJava()).platform()["platform"], "none")


class JvmTests(unittest.TestCase):
    def test_class_names(self):
        for good in ("android.os.Build", "android.os.Build$VERSION", "com.erfan.standaloneai.MainActivity", "java.lang.String"):
            self.assertTrue(valid_class_name(good), good)
        for bad in ("", "a", "a b", "android..os", "android.os.", "../x", "a.b;c", None, "x" * 300, "android.os.Build$"):
            self.assertFalse(valid_class_name(bad), bad)

    def test_detect_without_chaquopy_is_null(self):
        self.assertEqual(detect_jvm().platform_name, "none")

    def test_chaquopy_wrapper_over_a_fake_java_module(self):
        class FakeModule:
            def __init__(self):
                self.created = []

            def jclass(self, name):
                if name == "com.chaquo.python.Python":
                    class P:
                        @staticmethod
                        def getPlatform():
                            return type("Pl", (), {"getApplication": staticmethod(lambda: "APP")})
                    return P
                if name == "android.os.Build$VERSION":
                    return type("V", (), {"SDK_INT": 33})
                if name == "com.erfan.standaloneai.MainActivity":
                    return type("M", (), {"NATIVE_FEATURES": ["file_chooser", "voice_input"]})
                if name == "java.lang.Runnable":
                    return "RUNNABLE"
                raise RuntimeError("no class " + name)

            def dynamic_proxy(self, iface):
                self.created.append(iface)
                return type("Base", (), {})

        module = FakeModule()
        jvm = ChaquopyJava(module)
        self.assertEqual((jvm.context(), jvm.sdk_int()), ("APP", 33))
        self.assertEqual(jvm.native_features(), frozenset({"file_chooser", "voice_input"}))
        seen = []
        proxy = jvm.proxy("java.lang.Runnable", {"run": lambda: seen.append("ran")})
        proxy.run()
        self.assertEqual((seen, module.created), (["ran"], ["RUNNABLE"]))
        with self.assertRaises(NativeUnavailable) as caught:
            jvm.jclass("com.example.Missing")
        self.assertEqual(caught.exception.code, "class_missing")
        with self.assertRaises(NativeUnavailable) as caught:
            jvm.jclass("bad name")
        self.assertEqual(caught.exception.code, "bad_class_name")

    def test_results(self):
        self.assertTrue(ok({"a": 1}))
        self.assertFalse(fail("x"))
        self.assertEqual(DoorResult(True, "ok").to_dict()["code"], "ok")


if __name__ == "__main__":
    unittest.main()
