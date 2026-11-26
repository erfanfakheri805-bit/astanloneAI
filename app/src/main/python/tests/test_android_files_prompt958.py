"""
Prompt 958 - the Android files (Java, manifest, resources, Gradle, workflow) against the Python side.

Static checks only: nothing is compiled or run here (the Android SDK is not part of the test run). What they prove is that every
name, argument count, JSON key, folder, file-size limit and permission the Java and XML files use is the one the Python side expects
and that the safety rules written in the design are really in the files. Whether the code compiles with the real SDK and behaves on a
phone is shown only by the GitHub build and by trying the installed app.
"""

import inspect
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

_PY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_PY_ROOT, "..", "..", "..", ".."))
_MAIN = os.path.join(_PROJECT_ROOT, "app", "src", "main")
_JAVA = os.path.join(_MAIN, "java", "com", "erfan", "standaloneai")
_HAS_PROJECT = os.path.isfile(os.path.join(_PROJECT_ROOT, "settings.gradle"))
ANDROID = "{http://schemas.android.com/apk/res/android}"

sys.path.append(_PY_ROOT)

import android_entry                                   # noqa: E402
import platform_boot                                   # noqa: E402
from android_adapters import catalog                   # noqa: E402
from brain_hub import builtin_tools                    # noqa: E402
from model_runtime import card as model_card           # noqa: E402
from native_bridge import doors, jvm, screen           # noqa: E402
from teacher import assistants                         # noqa: E402


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


def java(name):
    return read(_JAVA, name)


def code_only(source):
    """The Java source without comments and without string contents (so words in prose are not matched)."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in source.splitlines())


def split_args(text):
    """Top-level comma separated arguments of a call (`a, f(b, c), d[:2]` -> 3 items); an empty text -> 0 items."""
    items, depth, current = [], 0, ""
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        items.append(current.strip())
    return items


def static_methods(source):
    """`{name: (return type, [parameter types])}` of the `public static` methods of a Java file."""
    found = {}
    for ret, name, params in re.findall(r"public static\s+([\w\[\]]+)\s+(\w+)\(([^)]*)\)", source):
        types = [p.strip().rsplit(" ", 1)[0].replace("final ", "").strip() for p in split_args(params)]
        found[name] = (ret, types)
    return found


def python_call_args(source, receiver_pattern, method):
    """The argument counts with which `<receiver>.<method>(...)` is called in a Python source."""
    counts = set()
    for match in re.finditer(receiver_pattern + r"\." + method + r"\(", source):
        start, depth, end = match.end(), 1, match.end()
        while end < len(source) and depth:
            depth += {"(": 1, ")": -1}.get(source[end], 0)
            end += 1
        counts.add(len(split_args(source[start:end - 1])))
    return counts


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class JavaPythonContractTests(unittest.TestCase):
    def setUp(self):
        self.main = java("MainActivity.java")
        self.service = java("PyAccessibilityService.java")

    # ------------------------------------------------------------------------------------------ names and features
    def test_package_and_class_names_are_the_ones_python_uses(self):
        for source, cls in ((self.main, "MainActivity"), (self.service, "PyAccessibilityService")):
            self.assertIn("package com.erfan.standaloneai;", source)
            self.assertRegex(source, r"public class %s extends" % cls)
        self.assertEqual(jvm.MAIN_ACTIVITY, "com.erfan.standaloneai.MainActivity")
        self.assertEqual(screen.SERVICE_CLASS, "com.erfan.standaloneai.PyAccessibilityService")

    def features(self):
        body = re.search(r"NATIVE_FEATURES\s*=\s*\{([^}]*)\}", self.main).group(1)
        return re.findall(r'"([a-z_]+)"', body)

    def test_native_features_are_exactly_the_implemented_ones(self):
        features = self.features()
        self.assertEqual(len(features), len(set(features)))
        # Prompt 959 (stage B; a conscious change of this pin, was the six features of Prompt 958): body_service - BodyService, the foreground service
        # of long jobs with the notification's stop button (see tests/test_body_service_prompt959.py).
        self.assertEqual(set(features), {"file_chooser", "permission_request", "voice_input", "accessibility", "share_target", "file_pick", "body_service"})
        # every name Python asks for is there ...
        for needed in (doors.VoiceDoor.FEATURE, screen.FEATURE, catalog.NATIVE_FILE_CHOOSER, catalog.NATIVE_PERMISSION_REQUEST):
            self.assertIn(needed, features)
        # ... and every name is backed by the code that implements it
        manifest = read(_MAIN, "AndroidManifest.xml")
        evidence = {"file_chooser": ("onShowFileChooser", self.main), "permission_request": ("requestPermissions", self.main),
                    "voice_input": ("ACTION_RECOGNIZE_SPEECH", self.main), "file_pick": ("ACTION_OPEN_DOCUMENT", self.main),
                    "share_target": ("android.intent.action.SEND", manifest), "accessibility": ("BIND_ACCESSIBILITY_SERVICE", manifest),
                    "body_service": ("FOREGROUND_SERVICE_TYPE_DATA_SYNC", java("BodyService.java"))}
        for feature, (needle, text) in evidence.items():
            self.assertIn(needle, text, feature)

    # ------------------------------------------------------------------------------------------ what Python calls
    def test_the_screen_door_calls_exactly_the_static_methods_the_service_has(self):
        methods = static_methods(self.service)
        expected = {"isConnected": ("boolean", []), "activePackage": ("String", []), "readScreen": ("String", ["int"]),
                    "clickNode": ("boolean", ["String", "boolean", "String", "boolean"]), "setText": ("boolean", ["String", "String", "String"]),
                    "globalAction": ("boolean", ["String"]), "scroll": ("boolean", ["boolean"])}
        self.assertEqual(methods, expected)
        source = inspect.getsource(screen)
        for name, (_ret, params) in expected.items():
            counts = python_call_args(source, r"(?:service|self\._service\(\))", name)
            self.assertEqual(counts, {len(params)}, name)

    def test_the_voice_and_permission_doors_call_static_methods_of_the_activity(self):
        methods = static_methods(self.main)
        self.assertEqual(methods["startVoiceInput"], ("boolean", ["String"]))
        self.assertEqual(methods["takeVoiceResult"], ("String", []))
        self.assertEqual(methods["requestAndroidPermissions"], ("boolean", ["String[]"]))
        self.assertEqual(python_call_args(inspect.getsource(doors), r"jclass\(MAIN_ACTIVITY\)", "startVoiceInput"), {1})
        self.assertEqual(python_call_args(inspect.getsource(doors), r"jclass\(MAIN_ACTIVITY\)", "takeVoiceResult"), {0})
        from android_adapters import bridge
        self.assertIn("requestAndroidPermissions", inspect.getsource(bridge))

    def test_the_screen_json_has_exactly_the_keys_python_reads(self):
        body = self.service[self.service.index("private static JSONObject describe"):]
        body = body[:body.index("private static boolean matches")]
        java_keys = set(re.findall(r'o\.put\("(\w+)"', body))
        py_source = inspect.getsource(screen._clean_screen)
        py_node_keys = set(re.findall(r'raw\.get\("(\w+)"\)', py_source))
        self.assertEqual(java_keys, py_node_keys)
        top = self.service[self.service.index("public static String readScreen"):]
        top = top[:top.index("public static boolean clickNode")]
        self.assertEqual(set(re.findall(r'out\.put\("(\w+)"', top)), set(re.findall(r'parsed\.get\("(\w+)"\)', py_source)))

    def test_the_four_system_keys_are_the_ones_python_allows(self):
        self.assertEqual(set(re.findall(r'"(\w+)"\.equals\(name\)', self.service)), set(screen._GLOBAL_ACTIONS))
        for forbidden in ("GLOBAL_ACTION_POWER_DIALOG", "GLOBAL_ACTION_LOCK_SCREEN", "GLOBAL_ACTION_TAKE_SCREENSHOT", "GLOBAL_ACTION_QUICK_SETTINGS",
                          "GLOBAL_ACTION_ACCESSIBILITY", "GestureDescription", "dispatchGesture", "takeScreenshot"):
            self.assertNotIn(forbidden, self.service)

    # ------------------------------------------------------------------------------------------ what Java calls
    def test_java_names_only_the_two_entry_modules_and_calls_them_with_the_right_arguments(self):
        source = code_only(self.main)
        self.assertEqual(sorted(set(re.findall(r'getModule\("([^"]+)"\)', source))), ["android_entry", "platform_boot"])
        modules = {"android_entry": android_entry, "platform_boot": platform_boot}
        calls = re.findall(r'callAttr\("(\w+)"((?:,\s*[\w.()]+)*)\)', source)
        self.assertEqual(sorted(name for name, _ in calls), ["inbox_dir", "on_shared_text", "prepare", "start"])
        for name, args in calls:
            function = next(getattr(module, name) for module in modules.values() if callable(getattr(module, name, None)))
            parameters = list(inspect.signature(function).parameters.values())
            required = len([p for p in parameters if p.default is p.empty])
            given = len(split_args(args.lstrip(",")))
            self.assertTrue(required <= given <= len(parameters), "%s: %d arguments, Python takes %d..%d" % (name, given, required, len(parameters)))

    def test_the_boot_step_runs_before_the_app_is_imported(self):
        source = code_only(self.main)
        create = source[source.index("protected void onCreate"):source.index("private void runBootStep")]
        self.assertLess(create.index("runBootStep(py)"), create.index('getModule("android_entry")'))
        boot = source[source.index("private void runBootStep"):source.index("protected void onStart")]
        self.assertLess(boot.index('callAttr("prepare"'), boot.index('callAttr("inbox_dir"'))
        self.assertIn("catch (RuntimeException e)", boot)                                 # the boot step can never stop the app

    def test_the_inbox_fallback_path_is_the_one_python_computes(self):
        match = re.search(r'new File\(new File\(new File\(getFilesDir\(\), "(\w+)"\), "(\w+)"\), "(\w+)"\)', self.main)
        self.assertEqual(match.groups(), ("data", platform_boot.HUB_DIRNAME, platform_boot.INBOX_DIRNAME))
        tail = os.path.join("data", platform_boot.HUB_DIRNAME, platform_boot.INBOX_DIRNAME)
        self.assertTrue(platform_boot.inbox_dir("/x").endswith(tail))

    def test_limits_and_names_match_the_python_inbox_rules(self):
        self.assertEqual(int(re.search(r"MAX_NAME_CHARS = (\d+);", self.main).group(1)), 100)
        self.assertEqual(builtin_tools._FILE_NAME_RE.pattern, r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
        self.assertEqual(re.search(r"MAX_MODEL_BYTES = ([\dL * ]+);", self.main).group(1).replace("L", "").replace(" ", ""), "8*1024*1024*1024")
        self.assertEqual(model_card.MAX_SIZE_BYTES, 8 * 1024 ** 3)
        extensions = set(re.findall(r'endsWith\("(\.\w+)"\)', self.main[self.main.index("hasModelExtension"):]))
        self.assertEqual(extensions, {ext for ext in builtin_tools.MODEL_FILE_FORMATS if ext != ".json"})

    def test_every_string_resource_the_java_uses_exists(self):
        used = set(re.findall(r"R\.string\.(\w+)", self.main + self.service))
        defined = {el.get("name") for el in ET.parse(os.path.join(_MAIN, "res", "values", "strings.xml")).getroot()}
        self.assertTrue(used)
        self.assertLessEqual(used, defined)

    def test_the_callbacks_java_calls_in_the_page_are_the_fixed_list(self):
        self.assertEqual(set(re.findall(r'tellPage\("(\w+)"', code_only(self.main))),
                         {"nativeOnShared", "nativeOnFile", "nativeOnProgress", "nativeOnVoice"})


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class JavaSafetyTests(unittest.TestCase):
    def setUp(self):
        self.main = code_only(java("MainActivity.java"))
        self.service = code_only(java("PyAccessibilityService.java"))

    def test_the_page_can_reach_only_three_methods_and_two_of_them_check_the_page_first(self):
        self.assertEqual(self.main.count("@JavascriptInterface"), 3)
        self.assertEqual(self.main.count('addJavascriptInterface(new NativeBridge(), "AndroidBridge")'), 1)
        bridge = self.main[self.main.index("public final class NativeBridge"):self.main.index("private void startCopy")]
        for method in ("pickFile", "startVoice"):
            body = bridge[bridge.index("public boolean %s(" % method):]
            self.assertIn("if (!pageTrusted)", body[:200], method)

    def test_the_web_view_loads_only_the_local_origin(self):
        self.assertEqual(len(re.findall(r"\.loadUrl\(", self.main)), 1)
        self.assertIn("webView.loadUrl(url);", self.main)
        self.assertIn("shouldOverrideUrlLoading", self.main)
        self.assertIn('"https".equals(uri.getScheme())', self.main)               # only secure links go to the browser
        for risky in ("setAllowFileAccess(true)", "setAllowUniversalAccessFromFileURLs", "setJavaScriptCanOpenWindowsAutomatically",
                      "setMixedContentMode", "setAllowContentAccess(true)"):
            self.assertNotIn(risky, self.main)
        self.assertNotRegex(self.main, r"https?://")

    def test_nothing_in_java_runs_commands_or_loads_code(self):
        for source in (self.main, self.service):
            for risky in ("Runtime.getRuntime", "ProcessBuilder", "DexClassLoader", "PathClassLoader", "System.loadLibrary", "Class.forName",
                          ".exec(", "java.net.", "android.net.http", "HttpURLConnection", "DownloadManager", "PackageInstaller",
                          "ACTION_INSTALL_PACKAGE", "ACTION_DELETE", "Settings.Secure", "setComponentEnabledSetting"):
                self.assertNotIn(risky, source, risky)

    def test_the_activity_never_opens_anything_by_itself(self):
        # the only activities it starts: the system pickers/dialogs the user answers, and a secure link the user tapped
        starts = set(re.findall(r"new Intent\(([\w.]+)", self.main))
        self.assertEqual(starts, {"RecognizerIntent.ACTION_RECOGNIZE_SPEECH", "Intent.ACTION_OPEN_DOCUMENT", "Intent.ACTION_VIEW"})

    def test_a_shared_text_is_only_saved(self):
        body = self.main[self.main.index("private void deliverSharedText"):self.main.index("public final class NativeBridge")]
        self.assertEqual(re.findall(r'callAttr\("(\w+)"', body), ["on_shared_text"])
        self.assertNotIn("evaluateJavascript", body)
        handler = self.main[self.main.index("private void handleIntent"):self.main.index("private void deliverSharedText")]
        self.assertIn("FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY", handler)           # an old share is not taken again from Recents
        self.assertIn('startsWith("text/")', handler)

    def test_the_file_copy_never_overwrites_in_place_and_checks_the_size(self):
        body = self.main[self.main.index("private String copyPickedFile"):self.main.index("private static boolean hasModelExtension")]
        for needle in (".partial", "renameTo(target)", "copied != expected", "getAvailableBytes", "MAX_MODEL_BYTES", "MAX_OTHER_BYTES", "getFD().sync()",
                       "partial.delete()"):
            self.assertIn(needle, body, needle)
        self.assertNotIn("readAllBytes", body)                                      # never the whole file in memory
        self.assertNotIn("ByteArrayOutputStream", body)

    def test_the_service_never_reads_or_writes_password_fields_and_keeps_no_text(self):
        self.assertGreaterEqual(self.service.count("isPassword()"), 5)
        describe = self.service[self.service.index("private static JSONObject describe"):self.service.index("private static boolean matches")]
        self.assertIn("(password || text == null)", describe)
        self.assertIn("(password || desc == null)", describe)
        for stored in ("static String lastText", "SharedPreferences", "FileOutputStream", "openFileOutput", "Log.", "System.out"):
            self.assertNotIn(stored, self.service)
        self.assertEqual(self.service.count("static volatile"), 2)                  # the instance and the name of the app in front

    def test_the_service_reacts_to_nothing_but_the_window_that_came_to_the_front(self):
        self.assertEqual(re.findall(r"AccessibilityEvent\.(TYPE_\w+)", self.service), ["TYPE_WINDOW_STATE_CHANGED"])
        handler = self.service[self.service.index("public void onAccessibilityEvent"):self.service.index("public void onInterrupt")]
        self.assertNotIn("getText", handler)
        self.assertNotIn("getSource", handler)


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tree = ET.parse(os.path.join(_MAIN, "AndroidManifest.xml")).getroot()
        self.app = self.tree.find("application")

    def test_permissions_are_exactly_the_five_the_design_lists(self):
        # Prompt 959 (stage B; a conscious change of this pin, was "exactly internet and notifications", with READ_SMS and FOREGROUND_SERVICE on the
        # never-list): the body adds FOREGROUND_SERVICE + FOREGROUND_SERVICE_DATA_SYNC (a long download keeps a notification and stays alive) and READ_SMS
        # (the newest one-time code, only when the user asks in the chat). The never-list keeps everything else - and the other foreground-service
        # TYPES (location, microphone, camera, screen capture ...) and the ways of RECEIVING or SENDING messages.
        perms = [el.get(ANDROID + "name") for el in self.tree.findall("uses-permission")]
        self.assertEqual(perms, ["android.permission.INTERNET", "android.permission.POST_NOTIFICATIONS", "android.permission.FOREGROUND_SERVICE",
                                 "android.permission.FOREGROUND_SERVICE_DATA_SYNC", "android.permission.READ_SMS"])
        text = read(_MAIN, "AndroidManifest.xml")
        for never in ("RECORD_AUDIO", "CAMERA", "READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE", "MANAGE_EXTERNAL_STORAGE", "SYSTEM_ALERT_WINDOW",
                      "REQUEST_INSTALL_PACKAGES", "RECEIVE_SMS", "SEND_SMS", "READ_PHONE_STATE", "CALL_PHONE", "ANSWER_PHONE_CALLS", "READ_CONTACTS",
                      "ACCESS_FINE_LOCATION", "FOREGROUND_SERVICE_LOCATION", "FOREGROUND_SERVICE_MICROPHONE", "FOREGROUND_SERVICE_CAMERA",
                      "FOREGROUND_SERVICE_MEDIA_PROJECTION", "FOREGROUND_SERVICE_SPECIAL_USE", "RECEIVE_BOOT_COMPLETED", "QUERY_ALL_PACKAGES",
                      "BIND_DEVICE_ADMIN", "WRITE_SETTINGS", "SCHEDULE_EXACT_ALARM", "USE_FULL_SCREEN_INTENT"):
            self.assertNotIn(never, text, never)

    def test_the_visible_apps_are_exactly_the_assistants_the_teacher_knows(self):
        queries = self.tree.find("queries")
        self.assertEqual([el.get(ANDROID + "name") for el in queries.findall("package")], list(assistants.all_packages()))
        intents = queries.findall("intent")
        self.assertEqual([[a.get(ANDROID + "name") for a in i.findall("action")] for i in intents], [["android.speech.action.RECOGNIZE_SPEECH"]])
        self.assertEqual(len(list(queries)), len(assistants.all_packages()) + 1)

    def test_the_one_activity_takes_shared_text_and_nothing_else(self):
        activities = self.app.findall("activity")
        self.assertEqual(len(activities), 1)
        activity = activities[0]
        self.assertEqual(activity.get(ANDROID + "name"), ".MainActivity")
        self.assertEqual(activity.get(ANDROID + "launchMode"), "singleTask")
        self.assertEqual(activity.get(ANDROID + "exported"), "true")
        self.assertEqual(activity.get(ANDROID + "screenOrientation"), "portrait")
        filters = activity.findall("intent-filter")
        self.assertEqual(len(filters), 2)
        main, send = filters
        self.assertEqual([a.get(ANDROID + "name") for a in main.findall("action")], ["android.intent.action.MAIN"])
        self.assertEqual([c.get(ANDROID + "name") for c in main.findall("category")], ["android.intent.category.LAUNCHER"])
        self.assertEqual([a.get(ANDROID + "name") for a in send.findall("action")], ["android.intent.action.SEND"])
        self.assertEqual([c.get(ANDROID + "name") for c in send.findall("category")], ["android.intent.category.DEFAULT"])
        self.assertEqual([(d.get(ANDROID + "mimeType"), d.attrib.keys() - {ANDROID + "mimeType"}) for d in send.findall("data")], [("text/plain", set())])

    def test_the_accessibility_service_is_declared_the_way_android_requires(self):
        # Prompt 959 (stage B; a conscious change of this pin, was "exactly one service"): the body's foreground service is the second one (not exported;
        # tests/test_body_service_prompt959.py checks it), and its notification button's receiver is the only receiver.
        services = {el.get(ANDROID + "name"): el for el in self.app.findall("service")}
        self.assertEqual(set(services), {".PyAccessibilityService", ".BodyService"})
        self.assertEqual(len(self.app.findall("service")), 2)
        service = services[".PyAccessibilityService"]
        self.assertEqual(service.get(ANDROID + "name"), ".PyAccessibilityService")
        self.assertEqual(service.get(ANDROID + "permission"), "android.permission.BIND_ACCESSIBILITY_SERVICE")
        self.assertEqual([a.get(ANDROID + "name") for a in service.find("intent-filter").findall("action")], ["android.accessibilityservice.AccessibilityService"])
        meta = service.find("meta-data")
        self.assertEqual((meta.get(ANDROID + "name"), meta.get(ANDROID + "resource")), ("android.accessibilityservice", "@xml/accessibility_service_config"))
        self.assertTrue(os.path.isfile(os.path.join(_MAIN, "res", "xml", "accessibility_service_config.xml")))
        self.assertEqual([el.get(ANDROID + "name") for el in self.app.findall("receiver")], [".StopReceiver"])
        self.assertEqual(self.app.findall("provider"), [])                                        # nothing else is exposed

    def test_the_accessibility_config_asks_for_no_more_than_reading_and_acting(self):
        config = ET.parse(os.path.join(_MAIN, "res", "xml", "accessibility_service_config.xml")).getroot()
        attrs = {key.replace(ANDROID, ""): value for key, value in config.attrib.items()}
        self.assertEqual(attrs["accessibilityEventTypes"], "typeWindowStateChanged")
        self.assertEqual(attrs["canRetrieveWindowContent"], "true")
        self.assertEqual(set(attrs["accessibilityFlags"].split("|")), {"flagReportViewIds", "flagIncludeNotImportantViews"})
        self.assertEqual(attrs["description"], "@string/accessibility_service_description")
        for never in ("canPerformGestures", "canTakeScreenshot", "canRequestTouchExplorationMode", "canRequestFilterKeyEvents", "canControlMagnification",
                      "packageNames", "isAccessibilityTool", "settingsActivity"):
            self.assertNotIn(never, attrs)

    def test_the_gpu_libraries_are_optional(self):
        libs = self.app.findall("uses-native-library")
        self.assertEqual({el.get(ANDROID + "name") for el in libs}, {"libOpenCL.so", "libOpenCL-pixel.so", "libOpenCL-car.so"})
        self.assertEqual({el.get(ANDROID + "required") for el in libs}, {"false"})

    def test_the_resources_are_persian_and_complete(self):
        strings = {el.get("name"): el.text for el in ET.parse(os.path.join(_MAIN, "res", "values", "strings.xml")).getroot()}
        for name in ("voice_prompt", "voice_unavailable", "accessibility_service_label", "accessibility_service_description", "file_chooser_unavailable"):
            self.assertRegex(strings[name], "[\u0600-ۿ]", name)
        description = strings["accessibility_service_description"]
        for promise in ("فقط وقتی خودت", "رمزها خوانده نمی‌شوند", "تنظیماتِ اندروید", "هر وقت خواستی"):
            self.assertIn(promise, description)
        self.assertEqual(self.app.get(ANDROID + "label"), "@string/app_name")
        self.assertEqual(self.app.get(ANDROID + "supportsRtl"), "true")


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class GradleAndWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.gradle = read(_PROJECT_ROOT, "app", "build.gradle")
        self.workflow = read(_PROJECT_ROOT, ".github", "workflows", "android-debug-apk.yml")

    @staticmethod
    def no_comments(text, marker="//"):
        return "\n".join(line.split(marker, 1)[0] for line in text.splitlines())

    def test_the_engine_is_added_only_when_the_build_asks_for_it(self):
        gradle = self.no_comments(self.gradle)
        coordinates = "com.google.mediapipe:tasks-genai:0.10.27"
        self.assertEqual(gradle.count(coordinates), 1)
        self.assertIn(coordinates, inspect.getsource(sys.modules["model_runtime.mediapipe_runtime"]))
        block = re.search(r"if \(project\.findProperty\('withLlm'\) == 'true'\) \{\s*implementation '%s'\s*\}" % re.escape(coordinates), gradle)
        self.assertIsNotNone(block)
        unconditional = [d for d in re.findall(r"^    (?:implementation|api)\s+['\"]([^'\"]+)", gradle, re.M)]
        self.assertEqual(unconditional, ["androidx.appcompat:appcompat:1.7.0"])
        # Prompt 959 (a conscious change of this pin, was "exactly one pickFirsts"): the phone's own brain engine (LiteRT-LM) has its own
        # `withLiteRtLm` condition with its own packaging block (its native files may collide with the C++ runtime and the LiteRT runtime
        # that other libraries ship); each engine's block sits inside its own condition, so an ordinary build has no packaging rule at all.
        # Prompt 959 (stage B; a conscious change of this pin, was 4): the LiteRT-LM packaging block also keeps the first copy of the licence and
        # notice files its libraries ship (one `resources { pickFirsts.addAll([...]) }` call), so 5 calls in all - three of them for native files.
        self.assertEqual(len(re.findall(r"pickFirsts\.add", gradle)), 5)
        self.assertEqual(len(re.findall(r"\bpackaging \{", gradle)), 2)
        self.assertRegex(gradle, r"if \(project\.findProperty\('withLlm'\) == 'true'\) \{\s*packaging \{")
        self.assertRegex(gradle, r"if \(project\.findProperty\('withLiteRtLm'\) == 'true'\) \{\s*packaging \{")
        # Prompt 959 (stage B; a conscious change of this pin, was "litertlm-android:latest.release"): the engine's version is pinned to 0.19.1 (the one
        # the first real build resolved from latest.release), so that every build is the same build; see tests/test_android_packaging_boundary_prompt815.py.
        self.assertRegex(gradle, r"if \(project\.findProperty\('withLiteRtLm'\) == 'true'\) \{\s*implementation 'com\.google\.ai\.edge\.litertlm:litertlm-android:0\.19\.1'\s*\}")
        # ... and the AAR-metadata check is switched off only in that variant
        self.assertRegex(gradle, r"if \(project\.findProperty\('withLiteRtLm'\) == 'true'\) \{\s*tasks\.configureEach \{ task ->\s*if \(task\.name\.startsWith\('check'\) && task\.name\.endsWith\('AarMetadata'\)\) \{\s*task\.enabled = false")
        self.assertEqual(gradle.count("task.enabled = false"), 1)

    def test_only_the_engine_variant_is_built_for_android_8(self):
        # Prompt 959 (stage B): the first real LiteRT-LM build log said "Invoke-customs are only supported starting with Android O (--min-api 26)"
        # (litertlm-android 0.19.1), so the engine variant - and only that one - is built with minSdk 26. The literal `minSdk 24` stays the default
        # (the plain and the MediaPipe builds, and the pin in test_android_packaging_boundary), the later assignment wins.
        gradle = self.no_comments(self.gradle)
        self.assertEqual(len(re.findall(r"\bminSdk\s+\d+", gradle)), 2)
        self.assertEqual(gradle.count("minSdk 24"), 1)
        self.assertEqual(gradle.count("minSdk 26"), 1)
        self.assertRegex(gradle, r"if \(project\.findProperty\('withLiteRtLm'\) == 'true'\) \{\s*defaultConfig \{\s*minSdk 26\s*\}\s*\}")
        self.assertLess(gradle.index("minSdk 24"), gradle.index("minSdk 26"), "the engine variant's value must come LAST so that it wins")
        self.assertRegex(gradle, r"resources \{\s*pickFirsts\.addAll\(\['META-INF/LICENSE\*', 'META-INF/NOTICE\*', 'META-INF/DEPENDENCIES', 'META-INF/INDEX\.LIST'\]\)\s*\}")
        # the resource rule sits inside the engine variant's packaging block, never in the unconditional part
        engine_block = re.search(r"if \(project\.findProperty\('withLiteRtLm'\) == 'true'\) \{\s*packaging \{.*?\n    \}\n", gradle, re.S).group(0)
        self.assertIn("resources {", engine_block)
        self.assertEqual(gradle.count("resources {"), 1)

    def test_the_identity_and_the_abi_are_unchanged(self):
        self.assertIn('applicationId "com.erfan.standaloneai"', self.gradle)
        self.assertIn('abiFilters "arm64-v8a"', self.gradle)
        self.assertRegex(self.gradle, r"versionCode (\d+)")
        self.assertGreaterEqual(int(re.search(r"versionCode (\d+)", self.gradle).group(1)), 2)

    def test_the_workflow_tries_the_engine_first_and_always_ends_with_an_apk(self):
        # Prompt 959 (a conscious change of this pin, was "one engine build, then the plain build"): a LADDER of three builds - the phone's
        # own brain engine (LiteRT-LM), then the MediaPipe engine of Prompt 958, then no engine - so that there is always an APK; the
        # release notes say which rung it is, and the log of every failed rung is kept.
        text = self.no_comments(self.workflow, "#")
        first = text.index("-PwithLiteRtLm=true")
        second = text.index("-PwithLlm=true", first)
        plain = text.index("gradle --no-daemon :app:assembleDebug\n", second)
        self.assertLess(first, second)
        self.assertLess(second, plain)
        self.assertEqual(text[:first].count("continue-on-error: true"), 1)            # the first rung may fail ...
        self.assertGreaterEqual(text[first:second].count("continue-on-error: true"), 1)   # ... and so may the second
        last_rung = text[text.rindex("      - name: ", 0, plain):plain]                       # the step that runs the plain build
        self.assertNotIn("continue-on-error", last_rung, "the last rung must be allowed to fail the job: no APK, no success")
        for needle in ("id: with_litertlm", "id: with_engine",
                       "if: steps.with_litertlm.outcome != 'success'",
                       "if: steps.with_litertlm.outcome != 'success' && steps.with_engine.outcome != 'success'",
                       "if: steps.with_litertlm.outcome == 'failure'", "if: steps.with_engine.outcome == 'failure'",
                       "litertlm-build.log", "engine-build.log", "ENGINE_NOTE"):
            self.assertIn(needle, text)
        self.assertIn("if-no-files-found: error", text)                       # no APK, no success
        # the release notes say which engine is in the APK
        self.assertIn("INCLUDED.", text)
        self.assertIn("NOT included", text)
        self.assertIn("$ENGINE_NOTE", text)
        self.assertIn("This build needs Android 8.0 or newer.", text)             # Prompt 959: the engine variant is built for minSdk 26
        self.assertEqual(text.count("shell: bash\n        run: gradle --no-daemon :app:assembleDebug -P"), 2)   # `shell: bash` = pipefail: a failed gradle fails the step

    def test_the_workflow_keeps_every_earlier_rule(self):
        text = self.no_comments(self.workflow, "#")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("needs: python-regression", text)
        for bad in ("secrets.", "assembleRelease"):
            self.assertNotIn(bad, text)
        # Prompt 959 (stage B; a conscious change of this pin, was "the word keystore appears nowhere"): the debug workflow now keeps GRADLE'S OWN
        # DEBUG key in the Actions cache - the one file `~/.android/debug.keystore` that Android's tools create for debug builds - so that a new debug
        # APK installs OVER the old one. That key is not a signing secret (no secret is read: `secrets.` stays forbidden above) and the word may
        # appear only as that one path (and in the notes that name it); a release key, a password or a keystore file in the repo still may not.
        rest = text.lower().replace("~/.android/debug.keystore", "").replace("$home/.android/debug.keystore", "").replace("debug-keystore-v1", "")
        self.assertNotIn("keystore", rest)
        for bad in ("storepassword", "keypassword", "keyalias", "base64 -d", "signingconfigs"):
            self.assertNotIn(bad, text.lower())

    def test_the_debug_signing_key_is_restored_before_the_first_build_and_saved_by_the_cache_only(self):
        # Prompt 959 (stage B): without a stable key every new debug APK is refused over the old one ("App not installed") and the user has to
        # uninstall - which deletes his chats and the downloaded brain. The cache restore comes BEFORE the first rung; the cache action saves the
        # file at the end of a successful job (nothing of ours writes it); the release notes say which case this build is.
        text = self.no_comments(self.workflow, "#")
        step = text.index("      - name: Restore the debug signing key")
        self.assertLess(step, text.index("-PwithLiteRtLm=true"))
        block = text[step:text.index("\n      - ", step + 10)]
        for needle in ("id: debug_key", "uses: actions/cache@v4", "path: ~/.android/debug.keystore", "key: debug-keystore-v1"):
            self.assertIn(needle, block, needle)
        self.assertEqual(text.count("actions/cache@"), 1)
        self.assertNotIn("restore-keys", text, "a key that merely looks similar must never be restored")
        self.assertIn("${{ steps.debug_key.outputs.cache-hit }}", text)
        for needle in ("KEY_NOTE=Signing key: the SAVED debug key", "KEY_NOTE=Signing key: a NEW debug key (uninstall the previous app first",
                       "that could NOT be saved", "$ENGINE_NOTE $KEY_NOTE"):
            self.assertIn(needle, text, needle)
        self.assertEqual(text.count("$HOME/.android/debug.keystore"), 1, "only the check that the key exists after the build reads it")
        self.assertNotIn(".keystore >", text)
        self.assertNotIn("> ~/.android", text)


if __name__ == "__main__":
    unittest.main()
