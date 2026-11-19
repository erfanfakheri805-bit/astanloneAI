"""Prompt 959 (stage B, «مغز خودکار") - the Java side of the on-device brain: `LiteRtLmBridge.java` compiled and RUN against a stand-in engine.

The real engine (`com.google.ai.edge.litertlm`) is a Kotlin library that is not available here, so the bridge is exercised against hand-written
Java classes shaped like its compiled API (`tests/jvm_stub_litertlm/`): the constructors `@JvmOverloads` yields, `Backend.CPU()` with a public
no-argument constructor, the NON-`@JvmStatic` companions of `Contents` / `Message`, `Engine.initialize/close`, `Conversation.sendMessage/cancelProcess`.
What this proves: the file compiles for Java 8, never throws, builds the engine and conversations in the documented way, passes the history in
order, falls back to simpler configurations, cancels, reports every failure as a code, and is harmless in an APK that has no engine at all.
What it can NOT prove: that the REAL engine accepts this call sequence (only a phone running the real engine can). The test is skipped, and says so,
when no JDK is installed.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON_ROOT = os.path.dirname(HERE)
STUB = os.path.join(HERE, "jvm_stub_litertlm")
# The two stub folders are FLAT on purpose (files directly inside `ok/` and `drift/`; javac takes the files by name, the `package` line decides
# where the classes land): a deep `com/google/ai/...` tree was once lost in a GitHub web upload, and every other test then failed with an
# opaque javac error. `StubFilesPresentTests` below names the missing file instead.
STUB_FILES = {"": ("AbsentMain.java", "OkMain.java"), "drift": ("EngineConfig.java",),
              "ok": ("Backend.java", "Content.java", "Contents.java", "Conversation.java", "ConversationConfig.java", "Engine.java",
                     "EngineConfig.java", "Message.java", "Placeholders.java", "SamplerConfig.java", "StubControl.java", "ThinkingConfig.java")}
BRIDGE = os.path.normpath(os.path.join(PYTHON_ROOT, "..", "java", "com", "erfan", "standaloneai", "LiteRtLmBridge.java"))
HAVE_JDK = bool(shutil.which("javac") and shutil.which("java"))


def java_files(folder, skip=()):
    out = []
    for base, _dirs, names in os.walk(folder):
        out.extend(os.path.join(base, n) for n in sorted(names) if n.endswith(".java") and n not in skip)
    return sorted(out)


def compile_and_run(case, sources, main, *args):
    with tempfile.TemporaryDirectory() as out:
        built = subprocess.run(["javac", "-encoding", "UTF-8", "--release", "8", "-proc:none", "-nowarn", "-Xlint:-options", "-d", out] + sources,
                               capture_output=True, text=True, timeout=240)
        case.assertEqual(built.returncode, 0, "javac failed:\n" + built.stdout + built.stderr)
        ran = subprocess.run(["java", "-cp", out, main] + list(args), capture_output=True, text=True, timeout=120, encoding="utf-8")
        return ran.returncode, ran.stdout, ran.stderr


class StubFilesPresentTests(unittest.TestCase):
    """Runs even without a JDK: a partly uploaded repository must say WHICH stand-in file is missing (and where it belongs)."""

    def test_every_stand_in_file_is_there_and_nothing_else(self):
        missing, extra = [], []
        for folder, names in STUB_FILES.items():
            where = os.path.join(STUB, folder) if folder else STUB
            have = sorted(n for n in os.listdir(where) if n.endswith(".java")) if os.path.isdir(where) else []
            missing += ["tests/jvm_stub_litertlm/" + (folder + "/" if folder else "") + n for n in names if n not in have]
            extra += ["tests/jvm_stub_litertlm/" + (folder + "/" if folder else "") + n for n in have if n not in names]
        self.assertEqual(missing, [], "stand-in files missing - upload them to the repository at exactly these paths (the CI cannot compile the bridge without them): "
                         + ", ".join(missing))
        self.assertEqual(extra, [], "unexpected stand-in files (list them in STUB_FILES on purpose): " + ", ".join(extra))

    def test_the_folders_hold_their_files_directly(self):
        for folder in ("ok", "drift"):
            where = os.path.join(STUB, folder)
            self.assertTrue(os.path.isdir(where), where)
            self.assertEqual([n for n in os.listdir(where) if os.path.isdir(os.path.join(where, n))], [], folder + " must stay flat")

    def test_every_stand_in_declares_the_engine_package(self):
        for folder, names in STUB_FILES.items():
            if not folder:
                continue
            for name in names:
                with open(os.path.join(STUB, folder, name), encoding="utf-8") as fh:
                    self.assertTrue(fh.read().lstrip().startswith("package com.google.ai.edge.litertlm;"), folder + "/" + name)


class BridgeSourceTests(unittest.TestCase):
    def test_the_bridge_uses_no_android_or_third_party_class(self):
        with open(BRIDGE, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("package com.erfan.standaloneai;"))
        imports = re.findall(r"^import ([\w.]+);", text, re.M)
        self.assertTrue(imports and all(i.startswith("java.") for i in imports), imports)
        self.assertNotIn("android.", text.replace("android.jar", ""))   # not even named in code: reflection only
        self.assertNotIn("import com.google", text)                     # the engine is reached by reflection only
        for forbidden in ("Runtime.getRuntime", "ProcessBuilder", "exec(", "System.load", "loadLibrary", "HttpURLConnection", "Socket"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_every_public_method_is_static_and_never_declares_a_throw(self):
        with open(BRIDGE, encoding="utf-8") as fh:
            text = fh.read()
        public = re.findall(r"^    public (static )?[\w<>\[\], ]+ \w+\([^)]*\)( throws [\w, ]+)?\s*\{", text, re.M)
        self.assertGreaterEqual(len(public), 7)
        for static, throws in public:
            self.assertEqual(static, "static ")
            self.assertEqual(throws, "")


@unittest.skipUnless(HAVE_JDK, "no JDK (javac/java) on this machine: the bridge could not be compiled here")
class BridgeAgainstStandInTests(unittest.TestCase):
    def check(self, code, out, err, expected_passes):
        fails = [line for line in out.splitlines() if line.startswith("FAIL")]
        self.assertEqual((code, fails), (0, []), out + err)
        self.assertIn("DONE failures=0", out)
        passes = [line for line in out.splitlines() if line.startswith("PASS")]
        self.assertGreaterEqual(len(passes), expected_passes, out)

    def test_with_an_engine_shaped_as_expected(self):
        code, out, err = compile_and_run(self, [BRIDGE] + java_files(os.path.join(STUB, "ok")) + [os.path.join(STUB, "OkMain.java")], "OkMain", "ok")
        self.check(code, out, err, 25)

    def test_with_an_engine_whose_api_drifted_the_app_survives_and_says_api_mismatch(self):
        sources = [BRIDGE] + java_files(os.path.join(STUB, "ok"), skip=("EngineConfig.java",)) + java_files(os.path.join(STUB, "drift")) \
            + [os.path.join(STUB, "OkMain.java")]
        code, out, err = compile_and_run(self, sources, "OkMain", "drift")
        self.check(code, out, err, 2)

    def test_in_an_apk_without_the_engine_nothing_throws(self):
        code, out, err = compile_and_run(self, [BRIDGE, os.path.join(STUB, "AbsentMain.java")], "AbsentMain")
        self.check(code, out, err, 4)


if __name__ == "__main__":
    unittest.main()
