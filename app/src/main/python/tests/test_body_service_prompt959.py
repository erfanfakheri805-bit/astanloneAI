"""Prompt 959 (stage B, the body) - the Java side of the background service (`BodyService`, `StopReceiver`) against the Python side.

The service is what keeps a long job (today: the download of the assistant's own brain) alive while the screen is off, and it carries the
«ایست» button of the notification. It is the one piece of the body that Python alone cannot exercise, and it can break the whole APK build (a
compile error, a missing string, a manifest rule), so three layers look at it:

  * static checks (always run, no JDK needed): every name, argument count, JSON key, limit, permission and string the Java and XML files use is
    the one the Python side expects, and the safety rules written in the design are really in the files;
  * a compile against the REAL android.jar and a run of `tests/jvm_stub_body/BodyServiceMain.java` (skipped, and saying why, when the machine has
    no JDK or no Android platform jar; the GitHub runner has both);
  * the compiled public surface (`javap`): exactly the three static methods Python calls, with their exact JNI signatures.

What none of it can show: how Android and HyperOS treat the service on a real phone (a start from the background, the notification's button, the
Android 15 limit of six hours for a data-sync service). Only the installed app tells that.
"""
import ast
import glob
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PY_ROOT = os.path.dirname(HERE)
MAIN = os.path.normpath(os.path.join(PY_ROOT, ".."))                          # app/src/main
PROJECT = os.path.normpath(os.path.join(MAIN, "..", "..", ".."))
JAVA_DIR = os.path.join(MAIN, "java", "com", "erfan", "standaloneai")
SERVICE_JAVA = os.path.join(JAVA_DIR, "BodyService.java")
RECEIVER_JAVA = os.path.join(JAVA_DIR, "StopReceiver.java")
ACTIVITY_JAVA = os.path.join(JAVA_DIR, "MainActivity.java")
MANIFEST = os.path.join(MAIN, "AndroidManifest.xml")
STRINGS = os.path.join(MAIN, "res", "values", "strings.xml")
STUB = os.path.join(HERE, "jvm_stub_body")
# FLAT on purpose (javac takes the files by name, the `package` line decides where the classes land): a deep tree was once lost in a GitHub web upload.
STUB_FILES = ("BodyServiceMain.java", "PyObject.java", "Python.java")
ANDROID = "{http://schemas.android.com/apk/res/android}"
HAVE_PROJECT = os.path.isfile(os.path.join(PROJECT, "settings.gradle"))
HAVE_JDK = bool(shutil.which("javac") and shutil.which("java"))
BODY_STRINGS = ("body_channel_name", "body_channel_description", "body_default_title", "body_stop", "body_stopping", "body_stop_failed")

sys.path.append(PY_ROOT)

import platform_boot                                           # noqa: E402
from native_bridge import body as door                         # noqa: E402
from persian_brain import hub_brain_commands as HBC            # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code_only(text):
    """The Java source without its comments (string and character literals kept as they are), so that a rule written in prose in a comment
    ("no timer, no network") is never mistaken for code, and a forbidden word in code is never hidden by a comment."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif text[i] in "\"'":
            quote, j = text[i], i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def java_files():
    return sorted(os.path.join(JAVA_DIR, name) for name in os.listdir(JAVA_DIR) if name.endswith(".java"))


def calls_of(text, pattern):
    """The full text of every call whose head matches `pattern` (the head ends with the opening parenthesis), up to its matching parenthesis."""
    found = []
    for match in re.finditer(pattern, text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            if text[i] == '"':
                i += 1
                while i < len(text) and text[i] != '"':
                    i += 2 if text[i] == "\\" else 1
            elif text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        found.append(text[match.start():i])
    return found


STATIC_PUBLIC = re.compile(r"^    public static ([\w<>\[\]]+) (\w+)\(([^)]*)\)\s*\{", re.M)


def public_static_methods(text):
    """{name: (return type, [parameter types])} of the `public static` methods at class level."""
    methods = {}
    for ret, name, params in STATIC_PUBLIC.findall(text):
        methods[name] = (ret, [p.split()[0] for p in params.split(",") if p.strip()])
    return methods


def python_calls_on_the_service():
    """{method: [ast.Call, ...]} of every `<anything>.jclass(SERVICE_CLASS).<method>(...)` in native_bridge/body.py."""
    tree = ast.parse(read(os.path.join(PY_ROOT, "native_bridge", "body.py")))
    calls = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        inner = node.func.value
        if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "jclass" and inner.args
                and isinstance(inner.args[0], ast.Name) and inner.args[0].id == "SERVICE_CLASS"):
            calls.setdefault(node.func.attr, []).append(node)
    return calls


def manifest_root():
    return ET.parse(MANIFEST).getroot()


def manifest_components(root):
    return [(el.tag, el.get(ANDROID + "name"), el) for el in root.find("application") if el.tag in ("activity", "service", "receiver", "provider")]


def component(root, name):
    found = [el for _tag, n, el in manifest_components(root) if n == name]
    assert len(found) == 1, (name, found)
    return found[0]


def strings_xml():
    """{name: decoded text} in file order."""
    return {el.get("name"): "".join(el.itertext()) for el in ET.parse(STRINGS).getroot().findall("string")}


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class StubFilesPresentTests(unittest.TestCase):
    """Runs even without a JDK: a partly uploaded repository must say WHICH stand-in file is missing (and where it belongs)."""

    def test_every_stand_in_file_is_there_and_nothing_else(self):
        have = sorted(n for n in os.listdir(STUB) if n.endswith(".java")) if os.path.isdir(STUB) else []
        missing = ["tests/jvm_stub_body/" + n for n in STUB_FILES if n not in have]
        extra = ["tests/jvm_stub_body/" + n for n in have if n not in STUB_FILES]
        self.assertEqual(missing, [], "stand-in files missing - upload them at exactly these paths: " + ", ".join(missing))
        self.assertEqual(extra, [], "unexpected stand-in files (list them in STUB_FILES on purpose): " + ", ".join(extra))

    def test_the_folder_is_flat(self):
        self.assertEqual([n for n in os.listdir(STUB) if os.path.isdir(os.path.join(STUB, n))], [])

    def test_every_stand_in_declares_the_package_it_stands_in_for(self):
        expected = {"PyObject.java": "com.chaquo.python", "Python.java": "com.chaquo.python", "BodyServiceMain.java": "com.erfan.standaloneai"}
        for name, package in expected.items():
            self.assertTrue(read(os.path.join(STUB, name)).lstrip().startswith("package %s;" % package), name)


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class JavaSurfaceTests(unittest.TestCase):
    """The three static methods Python calls: names, parameters, argument counts, the class's name, the limits."""

    def test_the_public_static_methods_are_exactly_what_python_calls(self):
        self.assertEqual(public_static_methods(code_only(read(SERVICE_JAVA))),
                         {"hold": ("boolean", ["Context", "String", "String", "int"]), "release": ("void", ["Context"]), "isRunning": ("boolean", [])})

    def test_python_calls_each_of_them_with_the_right_number_of_arguments(self):
        calls = python_calls_on_the_service()
        self.assertEqual({name: sorted({len(node.args) for node in nodes}) for name, nodes in calls.items()},
                         {"hold": [4], "release": [1], "isRunning": [0]})
        for name in calls:
            for node in calls[name]:
                self.assertEqual(node.keywords, [], name + ": Chaquopy calls take positional arguments only")

    def test_python_passes_the_android_context_first_and_a_whole_number_for_the_percent(self):
        calls = python_calls_on_the_service()
        for name in ("hold", "release"):
            for node in calls[name]:
                first = node.args[0]
                self.assertTrue(isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute) and first.func.attr == "context", name)
        for node in calls["hold"]:
            last = node.args[3]
            self.assertTrue(isinstance(last, ast.Call) and isinstance(last.func, ast.Name) and last.func.id == "int", "the percent must be an int")

    def test_the_class_name_python_asks_for_is_the_class_in_the_java_file(self):
        self.assertEqual(door.SERVICE_CLASS, "com.erfan.standaloneai.BodyService")
        text = code_only(read(SERVICE_JAVA))
        self.assertTrue(text.lstrip().startswith("package com.erfan.standaloneai;"))
        self.assertRegex(text, r"\npublic class BodyService extends Service \{")
        self.assertRegex(read(os.path.join(PROJECT, "app", "build.gradle")), r"namespace ['\"]com\.erfan\.standaloneai['\"]")

    def test_the_word_limits_are_the_same_on_both_sides(self):
        text = code_only(read(SERVICE_JAVA))
        title = int(re.search(r"static final int MAX_TITLE = (\d+);", text).group(1))
        words = int(re.search(r"static final int MAX_TEXT = (\d+);", text).group(1))
        self.assertEqual((title, words), (door.MAX_TITLE, door.MAX_TEXT))

    def test_the_percent_is_clamped_to_the_progress_bars_hundred_steps(self):
        """Python only lets -1 (unknown) and 0..100 through (`BodyDoor.hold`); Java clamps the same way, so one bad number can never draw a wrong bar."""
        text = code_only(read(SERVICE_JAVA))
        self.assertEqual(text.count("percent < 0 ? -1 : Math.min(percent, 100)"), 2, "hold() and onStartCommand() clamp the same way")
        self.assertIn("percent >= 0 && percent <= 100", text)
        self.assertIn("builder.setProgress(100, percent, false);", text)
        self.assertIn("builder.setProgress(0, 0, true);", text, "an unknown percent shows the moving bar")

    def test_the_feature_name_python_checks_is_one_the_activity_announces(self):
        text = code_only(read(ACTIVITY_JAVA))
        listed = re.search(r"NATIVE_FEATURES = \{(.*?)\};", text, re.S).group(1)
        names = re.findall(r'"([^"]+)"', listed)
        self.assertIn(door.FEATURE_SERVICE, names)
        self.assertEqual(len(names), len(set(names)), "a feature listed twice")


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class PythonAnswerTests(unittest.TestCase):
    """The one thing Java asks Python for (the notification's stop), and the JSON that comes back."""

    def test_java_asks_python_for_exactly_one_thing_and_gives_it_no_argument(self):
        text = code_only(read(SERVICE_JAVA))
        self.assertEqual(re.findall(r'getModule\("([^"]*)"\)', text), ["platform_boot"])
        self.assertEqual(re.findall(r'callAttr\("([^"]*)"[^)]*\)', text), ["emergency_stop"])
        self.assertIn('callAttr("emergency_stop")', text)
        self.assertEqual(list(inspect.signature(platform_boot.emergency_stop).parameters), [])

    def test_the_answer_python_gives_is_the_one_java_reads(self):
        text = code_only(read(SERVICE_JAVA))
        with mock.patch("brain_hub.body.emergency_stop_all", return_value={"hubs": 2, "stopped": ["download"], "released": True}):
            answer = json.loads(platform_boot.emergency_stop())
        self.assertIs(answer["ok"], True)
        self.assertIn('optBoolean("ok", false)', text, "Java must read the `ok` key Python writes")
        with mock.patch("brain_hub.body.emergency_stop_all", side_effect=RuntimeError("boom")):
            failed = json.loads(platform_boot.emergency_stop())
        self.assertIs(failed["ok"], False, "a stop that could not run says so (Java then keeps the notification and tells the user)")

    def test_what_java_answers_when_python_never_started_has_the_same_keys(self):
        text = code_only(read(SERVICE_JAVA))
        literal = re.search(r'return "(\{.*?\})";', text).group(1).replace('\\"', '"')
        fallback = json.loads(literal)
        with mock.patch("brain_hub.body.emergency_stop_all", return_value={"hubs": 0, "stopped": [], "released": False}):
            real = json.loads(platform_boot.emergency_stop())
        self.assertEqual(sorted(fallback), sorted(real))
        self.assertIs(fallback["ok"], True, "a process without Python has nothing running: the stop is done")

    def test_a_stop_python_did_not_confirm_keeps_the_notification_and_says_so(self):
        text = code_only(read(SERVICE_JAVA))
        block = text[text.index("static void stopFromNotification"):text.index("private static String askPythonToStop")]
        self.assertRegex(block, r"if \(answer != null && isOk\(answer\)\) \{\s*release\(app\);\s*\} else \{\s*"
                                r"postIfRunning\(app, app\.getString\(R\.string\.body_stop_failed\)\);\s*\}")
        self.assertIn("R.string.body_stopping", block)
        self.assertEqual(block.count("release("), 1, "the service is released in ONE place: after Python confirmed")


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class StopButtonTests(unittest.TestCase):
    def test_the_button_names_the_receiver_explicitly_and_the_receiver_checks_the_action(self):
        service, receiver = code_only(read(SERVICE_JAVA)), code_only(read(RECEIVER_JAVA))
        self.assertIn("new Intent(app, StopReceiver.class)", service)
        self.assertIn("setAction(StopReceiver.ACTION_STOP)", service)
        self.assertIn("ACTION_STOP.equals(intent.getAction())", receiver)
        value = re.search(r'static final String ACTION_STOP = "([^"]+)";', receiver).group(1)
        self.assertTrue(value.startswith("com.erfan.standaloneai.action."), value)

    def test_python_never_runs_on_the_receivers_main_thread(self):
        receiver = code_only(read(RECEIVER_JAVA))
        self.assertIn("goAsync()", receiver)
        self.assertEqual(receiver.count("new Thread("), 1)
        before_run, run = receiver.split("public void run()", 1)
        self.assertNotIn("stopFromNotification", before_run, "the stop must be started inside the worker thread only")
        self.assertIn("BodyService.stopFromNotification(context)", run)
        self.assertRegex(receiver, r"finally \{\s*if \(pending != null\) \{\s*pending\.finish\(\);")

    def test_the_receiver_survives_what_the_stop_throws(self):
        receiver = code_only(read(RECEIVER_JAVA))
        self.assertRegex(receiver, r"catch \(RuntimeException e\)")
        self.assertIn("intent == null", receiver)


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class ManifestTests(unittest.TestCase):
    def test_the_service_is_private_declares_its_type_and_has_no_intent_filter(self):
        service = component(manifest_root(), ".BodyService")
        self.assertEqual(service.tag, "service")
        self.assertEqual(service.get(ANDROID + "exported"), "false")
        self.assertEqual(service.get(ANDROID + "foregroundServiceType"), "dataSync")
        self.assertIsNone(service.find("intent-filter"))

    def test_the_receiver_is_private_and_has_no_intent_filter(self):
        receiver = component(manifest_root(), ".StopReceiver")
        self.assertEqual(receiver.tag, "receiver")
        self.assertEqual(receiver.get(ANDROID + "exported"), "false")
        self.assertIsNone(receiver.find("intent-filter"))

    def test_every_component_with_an_intent_filter_says_whether_it_is_exported(self):
        for tag, name, el in manifest_components(manifest_root()):
            if el.find("intent-filter") is not None:
                self.assertIn(el.get(ANDROID + "exported"), ("true", "false"), "%s %s: Android 12 and newer refuse the build without it" % (tag, name))

    def test_every_service_type_has_its_own_permission_declared(self):
        root = manifest_root()
        permissions = {el.get(ANDROID + "name") for el in root.findall("uses-permission")}
        self.assertIn("android.permission.FOREGROUND_SERVICE", permissions)
        seen = 0
        for _tag, name, el in manifest_components(root):
            for kind in (el.get(ANDROID + "foregroundServiceType") or "").split("|"):
                if not kind or kind == "shortService":                      # a short service needs no type permission
                    continue
                seen += 1
                need = "android.permission.FOREGROUND_SERVICE_" + re.sub(r"(?<!^)(?=[A-Z])", "_", kind).upper()
                self.assertIn(need, permissions, "%s declares the type %s: Android 14 needs %s" % (name, kind, need))
        self.assertGreaterEqual(seen, 1)

    def test_java_starts_the_service_with_the_type_the_manifest_declares(self):
        text = code_only(read(SERVICE_JAVA))
        declared = component(manifest_root(), ".BodyService").get(ANDROID + "foregroundServiceType")
        constant = re.sub(r"(?<!^)(?=[A-Z])", "_", declared).upper()
        self.assertEqual(set(re.findall(r"ServiceInfo\.FOREGROUND_SERVICE_TYPE_(\w+)", text)), {constant})

    def test_the_foreground_start_is_guarded_by_the_api_level_that_has_it(self):
        text = code_only(read(SERVICE_JAVA))
        self.assertRegex(text, r"if \(Build\.VERSION\.SDK_INT >= 29\) \{\s*startForeground\(NOTIFICATION_ID, notification, ServiceInfo\.FOREGROUND_SERVICE_TYPE_DATA_SYNC\);")
        self.assertRegex(text, r"if \(Build\.VERSION\.SDK_INT >= 26\) \{\s*app\.startForegroundService\(intent\);")
        self.assertIn("if (Build.VERSION.SDK_INT >= 31) {\n            builder.setForegroundServiceBehavior", text)


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class PendingIntentTests(unittest.TestCase):
    def test_every_pending_intent_in_the_app_says_whether_it_is_mutable(self):
        total = 0
        for path in java_files():
            for call in calls_of(code_only(read(path)), r"PendingIntent\.get(?:Activity|Activities|Broadcast|Service|ForegroundService)\("):
                total += 1
                self.assertTrue("FLAG_IMMUTABLE" in call or "FLAG_MUTABLE" in call, "%s: %s (Android 12 and newer refuse a PendingIntent without it)" % (os.path.basename(path), call))
        self.assertGreaterEqual(total, 2)

    def test_the_services_own_pending_intents_are_immutable(self):
        calls = calls_of(code_only(read(SERVICE_JAVA)), r"PendingIntent\.get\w+\(")
        self.assertEqual(len(calls), 2, "the stop button and the tap that opens the app")
        for call in calls:
            self.assertIn("FLAG_IMMUTABLE", call)
            self.assertNotIn("FLAG_MUTABLE", call)


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class StringTests(unittest.TestCase):
    def test_every_string_the_service_uses_exists_and_none_is_left_over(self):
        used = set(re.findall(r"R\.string\.(\w+)", code_only(read(SERVICE_JAVA)) + code_only(read(RECEIVER_JAVA))))
        have = strings_xml()
        self.assertEqual(sorted(used - set(have)), [], "R.string names that strings.xml does not define")
        self.assertEqual(used, set(BODY_STRINGS))
        self.assertEqual(len([n for n in have if n.startswith("body_")]), len(BODY_STRINGS))

    def test_the_body_strings_are_persian_and_plain(self):
        have = strings_xml()
        for name in BODY_STRINGS:
            text = have[name]
            self.assertTrue(re.search("[؀-ۿ]", text), name + " must be Persian")
            self.assertIsNone(re.search("[A-Za-z]", text), name + " has no Latin letters")
            self.assertNotIn("%", text, name + " is shown through getString(int): no format codes")
            self.assertEqual(text, text.strip(), name)
            self.assertLessEqual(len(text), 200, name)

    def test_the_stop_button_says_the_word_the_chat_understands(self):
        have = strings_xml()
        self.assertEqual(have["body_stop"], "ایست")
        self.assertTrue(HBC.is_halt([have["body_stop"]]))
        self.assertIn("«ایست»", have["body_stop_failed"], "when the stop failed, the user is told which word to write")
        self.assertIn("«ایست»", have["body_channel_description"])

    def test_no_string_breaks_the_resource_compiler(self):
        raw = read(STRINGS)
        items = re.findall(r'<string name="([^"]+)"[^>]*>(.*?)</string>', raw, re.S)
        self.assertEqual([name for name, _ in items], list(strings_xml()), "a <string> the regular expression cannot read")
        for name, value in items:
            self.assertIsNone(re.search(r"(?<!\\)'", value), name + ": an apostrophe needs a backslash (aapt2 stops the build)")
            self.assertIsNone(re.search(r'(?<!\\)"', value), name + ": a double quote needs a backslash")
            self.assertNotIn(value[:1], ("@", "?"), name + ": a leading @ or ? is a reference")
            self.assertEqual(re.findall(r"%(?!\d+\$[sdf]|%)", value), [], name + ": a format code without a position")
            self.assertNotIn("<", value, name)


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
class SafetyRulesTests(unittest.TestCase):
    """What the design promised: the service does nothing on its own, reaches no network, runs no program and loads no code."""

    FORBIDDEN = ("Runtime.getRuntime", "ProcessBuilder", ".exec(", "DexClassLoader", "PathClassLoader", "System.load", "loadLibrary", "Class.forName",
                 "HttpURLConnection", "java.net", "Socket", "WebView", "AlarmManager", "WorkManager", "JobScheduler", "Handler", "Timer", "Executor",
                 "ContentResolver", "SmsManager", "TelephonyManager", "PackageInstaller")

    def test_neither_file_uses_a_forbidden_facility(self):
        for path in (SERVICE_JAVA, RECEIVER_JAVA):
            text = code_only(read(path))
            for word in self.FORBIDDEN:
                self.assertNotIn(word, text, "%s: %s" % (os.path.basename(path), word))

    def test_only_the_expected_libraries_are_imported(self):
        for path in (SERVICE_JAVA, RECEIVER_JAVA):
            imports = re.findall(r"^import ([\w.]+);", read(path), re.M)
            self.assertTrue(imports)
            for name in imports:
                self.assertTrue(name.startswith(("android.", "java.", "org.json.", "com.chaquo.python.")), name)

    def test_the_service_starts_no_thread_of_its_own_and_is_not_sticky_and_cannot_be_bound(self):
        text = code_only(read(SERVICE_JAVA))
        self.assertNotIn("Thread", text, "the service does no work of its own: the stop button's thread lives in the receiver")
        self.assertIn("return START_NOT_STICKY;", text)
        self.assertRegex(text, r"public IBinder onBind\(Intent intent\) \{\s*return null;")
        self.assertNotIn("while (", text)

    def test_the_service_asks_python_nothing_but_the_stop(self):
        text = code_only(read(SERVICE_JAVA))
        self.assertEqual(text.count("Python.getInstance()"), 1)
        self.assertEqual(text.count("callAttr("), 1)


def find_android_jar():
    """The platform jar to compile against: $ANDROID_JAR, else the API level of the project (34) - or the nearest newer one - under
    $ANDROID_HOME / $ANDROID_SDK_ROOT. None when there is none (the JVM tests are then skipped, and say so)."""
    explicit = os.environ.get("ANDROID_JAR")
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    best = None
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(key)
        if not root:
            continue
        for jar in glob.glob(os.path.join(root, "platforms", "android-*", "android.jar")):
            match = re.fullmatch(r"android-(\d+)", os.path.basename(os.path.dirname(jar)))
            level = int(match.group(1)) if match else 0
            if level >= 34 and (best is None or level < best[0]):
                best = (level, jar)
    return best[1] if best else None


ANDROID_JAR = find_android_jar()


def write_r_java(folder):
    """`R.java` for the compile: one constant for every string of strings.xml (the real one is made by the Android build)."""
    lines = "".join("        public static final int %s = %d;\n" % (name.replace(".", "_"), 0x7F120000 + index) for index, name in enumerate(strings_xml()))
    path = os.path.join(folder, "R.java")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("package com.erfan.standaloneai;\n\npublic final class R {\n    public static final class string {\n" + lines + "    }\n}\n")
    return path


@unittest.skipUnless(HAVE_PROJECT, "the Android project is not next to the Python files here")
@unittest.skipUnless(HAVE_JDK, "no JDK (javac/java) on this machine: the service could not be compiled here")
@unittest.skipUnless(ANDROID_JAR, "no Android platform jar (API 34 or newer) found: set ANDROID_JAR, or ANDROID_HOME / ANDROID_SDK_ROOT with platforms/android-34")
class ServiceOnTheJvmTests(unittest.TestCase):
    """BodyService and StopReceiver compiled against the REAL android.jar (the same API the APK build uses) and the parts that need no phone run."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = os.path.join(cls._tmp.name, "out")
        os.makedirs(cls.out)
        sources = [SERVICE_JAVA, RECEIVER_JAVA, write_r_java(cls._tmp.name)] + [os.path.join(STUB, name) for name in STUB_FILES]
        cls.built = subprocess.run(["javac", "-encoding", "UTF-8", "--release", "8", "-proc:none", "-nowarn", "-Xlint:-options", "-cp", ANDROID_JAR,
                                    "-d", cls.out] + sources, capture_output=True, text=True, timeout=240)
        cls.classpath = os.pathsep.join([cls.out, ANDROID_JAR])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.built.returncode, 0, "javac failed:\n" + self.built.stdout + self.built.stderr)

    def test_the_service_and_the_receiver_compile_against_the_real_android_jar(self):
        for name in ("BodyService", "StopReceiver"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "com", "erfan", "standaloneai", name + ".class")), name)

    def test_the_parts_that_need_no_phone_behave(self):
        ran = subprocess.run(["java", "-cp", self.classpath, "com.erfan.standaloneai.BodyServiceMain"], capture_output=True, text=True, timeout=120, encoding="utf-8")
        fails = [line for line in ran.stdout.splitlines() if line.startswith("FAIL")]
        passes = [line for line in ran.stdout.splitlines() if line.startswith("PASS")]
        self.assertEqual((ran.returncode, fails), (0, []), ran.stdout + ran.stderr)
        self.assertIn("DONE failures=0", ran.stdout)
        self.assertGreaterEqual(len(passes), 17, ran.stdout)

    @unittest.skipUnless(shutil.which("javap"), "no javap on this machine")
    def test_the_compiled_surface_python_can_reach_is_exactly_the_three_methods(self):
        shown = subprocess.run(["javap", "-s", "-public", "-cp", self.classpath, "com.erfan.standaloneai.BodyService"],
                               capture_output=True, text=True, timeout=60).stdout
        lines = shown.splitlines()
        static, instance = {}, set()
        for index, line in enumerate(lines):
            match = re.match(r"\s+public (static )?[\w.\[\]]+ (\w+)\(", line)
            if match:
                if match.group(1):
                    static[match.group(2)] = lines[index + 1].strip()
                else:
                    instance.add(match.group(2))
        self.assertEqual(static, {"hold": "descriptor: (Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;I)Z",
                                  "release": "descriptor: (Landroid/content/Context;)V", "isRunning": "descriptor: ()Z"})
        self.assertEqual(instance, {"onCreate", "onStartCommand", "onDestroy", "onBind"}, "no other public method may give Python a way in")


if __name__ == "__main__":
    unittest.main()
