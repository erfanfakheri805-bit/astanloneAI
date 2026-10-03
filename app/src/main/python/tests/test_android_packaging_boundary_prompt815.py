"""Prompt 815 - Android packaging boundary.

Pins the thin Android layer (Gradle config, manifest, MainActivity,
android_entry.py, CI workflow) so it stays isolated from the Python
architecture. Static checks only: no sockets are opened, no Android or
Chaquopy modules are needed, no network is used and nothing is written
outside a temporary directory.
"""

import ast
import os
import re
import sys
import tempfile
import unittest

_PY_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(_PY_ROOT, "..", "..", "..", ".."))
_APP = os.path.join(_PROJECT_ROOT, "app")


def _read(*parts):
    with open(os.path.join(_PROJECT_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _read_abs(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _code(text, marker):
    """Drop whole-line and trailing comments so prose is not matched."""
    return "\n".join(line.split(marker, 1)[0] for line in text.splitlines())


_HAS_PROJECT = os.path.isfile(os.path.join(_PROJECT_ROOT, "settings.gradle"))


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class GradleConfigTests(unittest.TestCase):
    def test_chaquopy_plugin_is_pinned(self):
        root = _read("build.gradle")
        self.assertIn('com.chaquo.python:gradle:17.0.0', root)
        self.assertNotIn("17.+", root)

    def test_agp_within_chaquopy_17_supported_range(self):
        m = re.search(r"com\.android\.tools\.build:gradle:(\d+)\.(\d+)", _read("build.gradle"))
        self.assertIsNotNone(m)
        self.assertGreaterEqual((int(m.group(1)), int(m.group(2))), (7, 3))
        self.assertLessEqual((int(m.group(1)), int(m.group(2))), (9, 2))

    def test_python_version_pinned_and_abi_matches(self):
        app = _code(_read("app", "build.gradle"), "//")
        self.assertRegex(app, r'version\s+"3\.12"')
        # Python 3.12+ on Chaquopy is 64-bit only.
        abis = re.search(r"abiFilters\s+([^\n]+)", app).group(1)
        self.assertIn("arm64-v8a", abis)
        self.assertNotIn("armeabi-v7a", abis)
        self.assertNotIn('"x86"', abis)

    def test_minsdk_meets_chaquopy_minimum(self):
        m = re.search(r"minSdk\s+(\d+)", _read("app", "build.gradle"))
        self.assertGreaterEqual(int(m.group(1)), 24)

    def test_no_pip_requirements_block(self):
        app = _code(_read("app", "build.gradle"), "//")
        self.assertNotRegex(app, r"pip\s*\{")
        self.assertNotRegex(app, r"\binstall\s*[\(\"']")

    def test_only_appcompat_dependency(self):
        app = _read("app", "build.gradle")
        deps = re.findall(r"^\s*(?:implementation|api|compileOnly|runtimeOnly)\s+['\"]([^'\"]+)", app, re.M)
        self.assertEqual(deps, ["androidx.appcompat:appcompat:1.7.0"])

    def test_gitignore_blocks_bytecode_and_build_output(self):
        gi = _read(".gitignore")
        for entry in ("__pycache__/", "*.pyc", "app/build/", ".gradle/", "local.properties"):
            self.assertIn(entry, gi)


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class ManifestAndJavaTests(unittest.TestCase):
    def test_manifest_permissions_are_internet_only(self):
        manifest = _read("app", "src", "main", "AndroidManifest.xml")
        perms = re.findall(r'<uses-permission android:name="([^"]+)"', manifest)
        self.assertEqual(perms, ["android.permission.INTERNET"])

    def test_single_launcher_activity(self):
        manifest = _read("app", "src", "main", "AndroidManifest.xml")
        self.assertEqual(manifest.count("<activity"), 1)
        self.assertIn("android.intent.category.LAUNCHER", manifest)

    def test_java_layer_is_one_thin_file(self):
        java_root = os.path.join(_APP, "src", "main", "java")
        files = [os.path.join(r, f) for r, _, fs in os.walk(java_root) for f in fs]
        self.assertEqual([os.path.basename(f) for f in files], ["MainActivity.java"])
        src = _read_abs(files[0])
        # The only Python module the Java layer may touch is android_entry.
        self.assertEqual(re.findall(r'getModule\("([^"]+)"\)', src), ["android_entry"])
        self.assertEqual(re.findall(r'callAttr\("([^"]+)"', src), ["start"])

    def test_webview_targets_loopback_only(self):
        src = _read_abs(os.path.join(_APP, "src", "main", "java", "com", "erfan",
                                     "standaloneai", "MainActivity.java"))
        self.assertNotRegex(src, r"https?://")
        sys.path.insert(0, _PY_ROOT)
        try:
            from core.config import UIConfig
            self.assertEqual(UIConfig().host, "127.0.0.1")
        finally:
            sys.path.remove(_PY_ROOT)


@unittest.skipUnless(_HAS_PROJECT, "Gradle project files not present")
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.wf = _code(_read(".github", "workflows", "android-debug-apk.yml"), "#")

    def test_manual_trigger_only(self):
        self.assertIn("workflow_dispatch:", self.wf)
        for trigger in ("push:", "pull_request:", "schedule:"):
            self.assertNotIn("\n  " + trigger, self.wf)

    def test_no_secrets_or_signing(self):
        self.assertNotIn("secrets.", self.wf)
        self.assertNotIn("assembleRelease", self.wf)
        self.assertNotIn("keystore", self.wf.lower())

    def test_builds_debug_with_matching_toolchain(self):
        self.assertIn(":app:assembleDebug", self.wf)
        self.assertIn('java-version: "17"', self.wf)
        self.assertIn('python-version: "3.12"', self.wf)
        self.assertIn('gradle-version: "8.7"', self.wf)
        self.assertIn("needs: python-regression", self.wf)


class AndroidEntryBoundaryTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, _PY_ROOT)
        self.addCleanup(sys.path.remove, _PY_ROOT)

    def test_import_has_no_side_effects_and_no_android_modules(self):
        import android_entry
        self.assertIsNone(android_entry._server)
        self.assertNotIn("com.chaquo.python", sys.modules)
        self.assertNotIn("java", sys.modules)

    def test_adapter_is_a_platform_adapter_confined_to_files_dir(self):
        import android_entry
        from platform_layer import PlatformAdapter
        with tempfile.TemporaryDirectory() as d:
            a = android_entry.AndroidFilesDirAdapter(d)
            self.assertIsInstance(a, PlatformAdapter)
            for path in (a.app_data_dir(), a.skill_definitions_dir(), a.temp_dir()):
                self.assertTrue(os.path.isdir(path))
                self.assertEqual(os.path.commonpath([d, path]), d)
            self.assertFalse(a.network_available())

    def test_entry_exposes_start_taking_files_dir(self):
        import android_entry
        import inspect
        self.assertEqual(list(inspect.signature(android_entry.start).parameters), ["files_dir"])

    def test_android_entry_imports_only_stdlib_and_project_modules(self):
        std = set(sys.stdlib_module_names)
        local = {n for n in os.listdir(_PY_ROOT)
                 if os.path.isdir(os.path.join(_PY_ROOT, n)) or n.endswith(".py")}
        local = {n[:-3] if n.endswith(".py") else n for n in local}
        tree = ast.parse(_read_abs(os.path.join(_PY_ROOT, "android_entry.py")))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                self.assertIn(m.split(".")[0], std | local, m)


class NoThirdPartyDependencyTests(unittest.TestCase):
    """The APK ships the stdlib only (no pip block), so production code
    must not import anything outside the stdlib and this project."""

    def test_production_code_imports_only_stdlib_and_project(self):
        std = set(sys.stdlib_module_names)
        local = {n[:-3] if n.endswith(".py") else n for n in os.listdir(_PY_ROOT)
                 if os.path.isdir(os.path.join(_PY_ROOT, n)) or n.endswith(".py")}
        offenders = {}
        for root, dirs, files in os.walk(_PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                tree = ast.parse(_read_abs(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        mods = [node.module]
                    else:
                        continue
                    for m in mods:
                        top = m.split(".")[0]
                        if top not in std and top not in local:
                            offenders.setdefault(top, []).append(os.path.relpath(path, _PY_ROOT))
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
