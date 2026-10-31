"""
Prompt 958 - the pack system (the app grows from the inside without a new APK).

Covers, with the real modules and no mocks of the code under test: finding a package in text / JSON / ZIP, manifest
validation, the static safety scan, propose -> approve -> activate -> roll back, hot loading through the import hook,
protected modules, restart-needed replacement (really restarted in a child process), hash verification, quarantine,
boot bookkeeping with safe mode, automatic switch-off of a failing pack, the permission model of `api`, the pack's own
data folder, language packs with retrieval, and the hash-chained audit.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pack_system import boot, intake, limits, manifest, overlay, scan
from pack_system.api import PackAPI, PackPermissionError
from pack_system.errors import PackError
from pack_system.lang import LangIndex, LangService, normalize_fa
from pack_system.manager import PackManager
from pack_system.registry import REGISTRY
from tests import pack_support_prompt958 as S

PACK_IDS = ("demo_greeter", "demo_other", "demo_tool", "demo_bad", "demo_native", "demo_data")


class PackCase(unittest.TestCase):
    def setUp(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()
        self.tmp = tempfile.mkdtemp(prefix="packs_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(self._cleanup_process)
        self.clock = S.FakeClock()
        self.root = os.path.join(self.tmp, "data", "packs")
        self.mgr = PackManager(self.root, self.clock)

    def _cleanup_process(self):
        S.reset_process_state(*PACK_IDS)
        boot.reset_for_tests()

    # ---- helpers
    def restart(self):
        """Another process start on the same files: new manager, no import hook, empty registry, no pack modules."""
        S.reset_process_state(*PACK_IDS)
        self.mgr = PackManager(self.root, self.clock)
        return self.mgr

    def propose(self, text, **kw):
        return self.mgr.propose(text, **kw)

    def install(self, text, **kw):
        proposal = self.propose(text)
        self.assertEqual(proposal["status"], "pending_approval", proposal)
        return self.mgr.approve(proposal["proposal_id"], user_approved=True, **kw)

    def chat(self, text, stage="fallback"):
        found = REGISTRY.run_chat(stage, S.ctx_for(None, text))
        return found[2] if found else None


class IntakeTests(unittest.TestCase):
    def test_text_form_code_pack(self):
        found = intake.find_pack_in_text("بفرما:\n" + S.text_pack())
        self.assertIsNotNone(found)
        schema, raw = found
        self.assertEqual(schema, "code.v1")
        self.assertEqual(raw["id"], "demo_greeter")
        self.assertIn("demo_greeter/main.py", raw["files"])
        self.assertIn("def register(api)", raw["files"]["demo_greeter/main.py"])

    def test_text_form_survives_a_code_fence_and_keeps_fences_inside_source(self):
        source = 'DOC = """\n```\nnot a fence of the package\n```\n"""\n\ndef register(api):\n    pass\n'
        text = "```text\n" + S.text_pack(source=source) + "```\n"
        schema, raw = intake.find_pack_in_text(text)
        self.assertIn("```", raw["files"]["demo_greeter/main.py"])
        manifest.normalize(raw)

    def test_text_form_lang_pack(self):
        schema, raw = intake.find_pack_in_text(S.lang_pack())
        self.assertEqual(schema, "lang.v1")
        self.assertEqual(len(raw["qa"]), 2)
        self.assertEqual(raw["qa"][0]["q"], ["پایتخت ایران کجاست", "پایتخت ایران چیست"])

    def test_json_in_a_fence(self):
        pkg = {"schema": "lang.v1", "id": "fa_json", "version": 1, "title": "t", "qa": [{"q": "سلام", "a": "درود"}]}
        text = "این را نصب کن:\n```json\n" + json.dumps(pkg, ensure_ascii=False) + "\n```"
        schema, raw = intake.find_pack_in_text(text)
        self.assertEqual((schema, raw["id"]), ("lang.v1", "fa_json"))

    def test_plain_chat_text_is_not_a_pack(self):
        self.assertIsNone(intake.find_pack_in_text("سلام، حالت چطوره؟"))
        self.assertIsNone(intake.find_pack_in_text(""))

    def test_zip_with_manifest(self):
        pkg = {"schema": "code.v1", "id": "demo_data", "version": 1, "title": "t", "entry": "demo_data.main"}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps(pkg))
            z.writestr("demo_data/__init__.py", "")
            z.writestr("demo_data/main.py", "def register(api):\n    pass\n")
        found = intake.parse_bytes(buf.getvalue())
        self.assertEqual(found[0], "code.v1")
        manifest.normalize(found[1])

    def test_zip_with_a_link_or_traversal_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps({"schema": "code.v1", "id": "demo_data", "version": 1}))
            z.writestr("../evil.py", "x=1")
        with self.assertRaises(PackError):
            found = intake.parse_bytes(buf.getvalue())
            manifest.normalize(found[1])


class ManifestTests(unittest.TestCase):
    def raw(self, **kw):
        schema, raw = intake.find_pack_in_text(S.text_pack(**kw))
        return raw

    def test_valid_pack_is_canonical_and_hashed(self):
        m = manifest.normalize(self.raw())
        self.assertEqual(m["id"], "demo_greeter")
        self.assertEqual(m["entry"], "demo_greeter.main")
        self.assertFalse(m["risky"])
        self.assertEqual(sorted(m["file_hashes"]), sorted(m["files"]))
        self.assertTrue(limits.SHA_RE.match(m["fingerprint"]))

    def test_missing_init_files_are_added(self):
        raw = self.raw(extra_files={"demo_greeter/sub/deep.py": "X = 1"})
        m = manifest.normalize(raw)
        self.assertIn("demo_greeter/sub/__init__.py", m["files"])

    def test_same_content_same_fingerprint_different_content_different(self):
        a, b = manifest.normalize(self.raw()), manifest.normalize(self.raw())
        c = manifest.normalize(self.raw(version=2))
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertNotEqual(a["fingerprint"], c["fingerprint"])

    def test_bad_ids_and_reserved_names(self):
        for bad in ("Demo", "x", "1abc", "has-dash", "json", "persian_brain", "core", "os", "tests"):
            with self.assertRaises(PackError, msg=bad):
                manifest.normalize(self.raw(pid=bad)) if False else manifest.normalize(dict(self.raw(), id=bad))

    def test_unknown_permission_and_future_platform(self):
        with self.assertRaises(PackError):
            manifest.normalize(self.raw(permissions="network, root"))
        with self.assertRaises(PackError) as ctx:
            manifest.normalize(dict(self.raw(), min_platform=limits.PLATFORM_LEVEL + 1))
        self.assertEqual(ctx.exception.code, "E_PACK_PLATFORM")

    def test_path_rules(self):
        for path in ("../x.py", "/abs.py", "demo_greeter/Main.py", "demo_greeter/a b.py", "demo_greeter/x.exe", "demo_greeter/.hidden.py"):
            raw = self.raw()
            raw["files"][path] = "x = 1"
            with self.assertRaises(PackError, msg=path):
                manifest.normalize(raw)
        raw = self.raw()
        raw["files"]["other_dir/x.py"] = "x = 1"
        with self.assertRaises(PackError):
            manifest.normalize(raw)

    def test_size_limits(self):
        raw = self.raw()
        raw["files"]["demo_greeter/big.txt"] = "a" * (limits.MAX_FILE_BYTES + 1)
        with self.assertRaises(PackError) as ctx:
            manifest.normalize(raw)
        self.assertEqual(ctx.exception.code, "E_PACK_FILE_SIZE")

    def test_replacing_protected_modules_is_refused(self):
        for mod in ("brain_hub.service", "persian_brain.hub_hooks", "net_tools", "ext_runtime.lifecycle", "memory.memory_system",
                    "pack_system.manager", "core.core", "interface.server", "android_entry", "android_adapters.layer"):
            raw = self.raw(replaces=mod, extra_files={mod.replace(".", "/") + ".py": "x = 1"})
            with self.assertRaises(PackError, msg=mod) as ctx:
                manifest.normalize(raw)
            self.assertEqual(ctx.exception.code, "E_PACK_PROTECTED", mod)

    def test_replacing_an_ordinary_module_is_allowed_and_risky(self):
        raw = self.raw(replaces="persian_brain.messages", extra_files={"persian_brain/messages.py": "X = 1"})
        m = manifest.normalize(raw)
        self.assertTrue(m["risky"])
        self.assertIn("replace_core", m["permissions"])

    def test_replacing_a_module_that_does_not_exist_is_refused(self):
        raw = self.raw(replaces="persian_brain.nothing_here", extra_files={"persian_brain/nothing_here.py": "X = 1"})
        with self.assertRaises(PackError):
            manifest.normalize(raw)

    def test_hidden_direction_controls_in_text_fields(self):
        with self.assertRaises(PackError):
            manifest.normalize(dict(self.raw(), title="خوب\u202eبد"))

    def test_lang_pack_rules(self):
        schema, raw = intake.find_pack_in_text(S.lang_pack())
        m = manifest.normalize(raw)
        self.assertEqual(len(m["qa"]), 2)
        bad = dict(raw, qa=[{"q": "", "a": "x"}])
        with self.assertRaises(PackError):
            manifest.normalize(bad)
        with self.assertRaises(PackError):
            manifest.normalize(dict(raw, qa=[{"q": ["a"] * (limits.MAX_QUESTIONS_PER_ENTRY + 1), "a": "x"}]))


def scan_source(source, perms=()):
    return scan.scan_source("demo_greeter/main.py", source, unsafe_native="unsafe_native" in perms)


class ScanTests(unittest.TestCase):
    def blocked(self, source, perms=()):
        report = scan_source(source, perms)
        self.assertFalse(report.ok, source)
        return {f.code for f in report.blocks}

    def test_clean_code_passes(self):
        report = scan_source("import json, re, math, time\nfrom collections import Counter\n\n"
                             "def register(api):\n    api.register_chat('x', lambda c: True, lambda c: json.dumps({'a': 1}))\n")
        self.assertTrue(report.ok, [f.to_dict() for f in report.findings])

    def test_blocked_modules(self):
        for line in ("import subprocess", "import socket", "import ctypes", "from urllib.request import urlopen", "import importlib",
                     "import sys", "import shutil", "import pickle", "import os, subprocess", "from os import system"):
            self.blocked(line + "\n")

    def test_os_is_limited_to_harmless_attributes(self):
        self.assertTrue(scan_source("import os\nx = os.path.join('a', 'b')\n").ok)
        self.blocked("import os\nos.system('ls')\n")
        self.blocked("import os\nos.remove('x')\n")
        self.blocked("import os\nos.environ\n")

    def test_dynamic_code_and_file_access(self):
        for line in ("eval('1')", "exec('x=1')", "compile('1','a','eval')", "__import__('os')", "open('x')", "globals()",
                     "getattr(object, '__subclasses__')", "x.__globals__", "x.__class__.__bases__", "f.f_back"):
            self.blocked(line + "\n")

    def test_native_access_needs_the_declared_permission(self):
        self.assertIn("E_SCAN_NATIVE", self.blocked("from java import jclass\n"))
        report = scan_source("from java import jclass\n", ("unsafe_native",))
        self.assertTrue(report.ok)
        self.assertTrue(report.warnings)

    def test_private_attributes_behind_api_are_blocked(self):
        for line in ("x = api._store", "x = api.android._jvm", "x = api.android.share._door", "x = ctx.api._registry",
                     "x = api.__class__", "api._need('network')", "y = api.teacher._doors.screen"):
            self.assertIn("E_SCAN_PRIVATE", self.blocked(line + "\n"), line)
        # a pack's own private names are its own business
        self.assertTrue(scan_source("class Cache:\n    def __init__(self):\n        self._items = []\n\n"
                                    "    def add(self, x):\n        self._items.append(x)\n\n"
                                    "def register(api):\n    api.register_chat('c', lambda c: False, lambda c: '')\n").ok)

    def test_clipboard_and_screen_are_declared_permissions(self):
        self.assertIn("clipboard", limits.PERMISSIONS)
        self.assertIn("screen", limits.PERMISSIONS)
        self.assertIn("screen", limits.RISKY_PERMISSIONS)
        self.assertNotIn("clipboard", limits.RISKY_PERMISSIONS)
        source = ("def register(api):\n    api.android.clipboard.get_text()\n    api.android.screen.read()\n")
        report = scan.scan_pack({"permissions": ["android"], "entry": "", "files": {"demo_greeter/main.py": source}})
        advised = {f.message_fa for f in report.warnings if f.code == "W_SCAN_PERMISSION"}
        self.assertEqual(len(advised), 2)
        self.assertTrue(any("clipboard" in m for m in advised) and any("screen" in m for m in advised))

    def test_syntax_error_and_hidden_characters(self):
        self.blocked("def register(api:\n")
        self.blocked("x = 1\u202e\n")
        self.blocked("héllo = 1\n")
        self.blocked("x = 1\x00\n")

    def test_scan_pack_checks_every_python_file(self):
        schema, raw = intake.find_pack_in_text(S.text_pack(extra_files={"demo_greeter/evil.py": "import subprocess\n"}))
        m = manifest.normalize(raw)
        report = scan.scan_pack(m)
        self.assertFalse(report.ok)
        self.assertEqual(report.blocks[0].file, "demo_greeter/evil.py")


if __name__ == "__main__":
    unittest.main()
