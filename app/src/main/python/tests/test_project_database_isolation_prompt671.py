"""Prompt 671 - Section 3: test database isolation / pristine project state.

Root cause (found by tracing every sqlite3.connect() in the full suite with an audit hook): seven tests in
`TestCoreIntegration` of test_learned_pattern_matching_in_understanding.py and
test_learned_sentence_structure_in_understanding.py built a bare `Core()`. With no path, Core ->
MemorySystem() -> `_default_db_path()` -> DesktopPlatformAdapter default -> the SHIPPED project
`data/memory.db`, which those tests then wrote to (learn_language_item / process_input). Fixed in the tests
only (a per-test temporary Core); production code is unchanged.
"""
import ast
import hashlib
import json
import os
import subprocess
import sys
import shutil
import tempfile
import unittest
from unittest import mock

from core.core import Core
from memory.memory_system import MemorySystem, _default_db_path
from platform_layer.desktop import DesktopPlatformAdapter

PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.realpath(os.path.join(PYTHON_ROOT, "data", "memory.db"))
TESTS_DIR = os.path.join(PYTHON_ROOT, "tests")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

# In-process record of every sqlite3.connect() target (audit hooks cannot be removed, so it is installed once).
_CONNECTS = []


def _hook(event, args):
    if event == "sqlite3.connect":
        try:
            _CONNECTS.append(os.path.realpath(os.fsdecode(args[0])))
        except Exception:
            pass


sys.addaudithook(_hook)


def sha(path=PROJECT_DB):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class IsolatedBase(unittest.TestCase):
    """Every test in this file must leave the project DB byte-identical and must never open it."""

    def setUp(self):
        self.before = sha()
        self.mark = len(_CONNECTS)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "t.db")

    def tearDown(self):
        self.assertEqual(sha(), self.before, "project data/memory.db was mutated")
        self.assertNotIn(PROJECT_DB, _CONNECTS[self.mark:], "project data/memory.db was opened")

    def core(self):
        core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "skills"))
        self.addCleanup(lambda: core.memory._conn.close())
        return core


class TestPristineState(IsolatedBase):
    def test_project_db_is_the_pristine_baseline_before_a_test(self):
        # Meaningful in the shipped tree; a disposable full-suite copy may legitimately differ.
        if sha() != PRISTINE_SHA256:
            self.skipTest("not the pristine shipped tree (disposable copy)")
        self.assertEqual(sha(), PRISTINE_SHA256)

    def test_hash_unchanged_across_a_test_that_writes(self):
        core = self.core()
        core.learning.teach("Python", "a language", source="user")
        self.assertNotEqual(sha(self.db), self.before)  # the temp DB changed, the project DB did not


class TestDisposableCopy(IsolatedBase):
    def test_writable_state_uses_a_disposable_copy(self):
        copy = os.path.join(self.tmp, "copy.db")
        shutil.copyfile(PROJECT_DB, copy)
        memory = MemorySystem(copy)
        memory.set_config("marker", "written-to-copy")
        memory._conn.close()
        self.assertNotEqual(sha(copy), self.before)
        self.assertEqual(sha(), self.before)

    def test_core_initialization_with_explicit_path_does_not_open_shipped_db(self):
        core = self.core()
        self.assertEqual(os.path.realpath(core.memory.db_path), os.path.realpath(self.db))
        self.assertNotIn(PROJECT_DB, _CONNECTS[self.mark:])


class TestWritesDoNotTouchProjectDb(IsolatedBase):
    def test_knowledge_writes(self):
        core = self.core()
        core.knowledge.learn("Tea", "a drink")
        self.assertIsNotNone(core.knowledge.find_by_name_case_insensitive("Tea"))

    def test_learning_writes(self):
        core = self.core()
        core.learning.teach("Python", "a language", source="user")
        core.learn_language_item("english", "pattern", "I love {{thing}}")
        core.process_input("I love tea")

    def test_relationship_writes(self):
        core = self.core()
        core.learning.teach("Python", "a language", source="user")
        core.learning.teach("Code", "text", source="user")
        core.knowledge.relate("Python", "Code", "USED_FOR")

    def test_lifecycle_status_changes(self):
        core = self.core()
        core.learning.teach("Python", "a language", source="user")
        core.learning.set_status("Python", "inactive")
        core.learning.set_status("Python", "active")

    def test_close_and_reopen(self):
        core = self.core()
        core.learning.teach("Python", "a language", source="user")
        core.memory._conn.close()
        again = self.core()
        self.assertIsNotNone(again.knowledge.find_by_name_case_insensitive("Python"))


class TestRegressionSetupIsIsolated(IsolatedBase):
    def _run_traced(self, module_pattern):
        script = (
            "import sys, os, json, unittest\n"
            "sys.path.insert(0, %r); os.chdir(%r)\n"
            "hits = []\n"
            "def hook(e, a):\n"
            "    if e == 'sqlite3.connect':\n"
            "        try: hits.append(os.path.realpath(os.fsdecode(a[0])))\n"
            "        except Exception: pass\n"
            "sys.addaudithook(hook)\n"
            "suite = unittest.defaultTestLoader.discover('tests', pattern=%r, top_level_dir=%r)\n"
            "res = unittest.TextTestRunner(stream=open(os.devnull, 'w')).run(suite)\n"
            "print(json.dumps({'ran': res.testsRun, 'bad': len(res.failures) + len(res.errors), 'hits': hits}))\n"
        ) % (PYTHON_ROOT, PYTHON_ROOT, module_pattern, PYTHON_ROOT)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, env=env, timeout=600)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_previously_mutating_modules_no_longer_open_the_project_db(self):
        result = self._run_traced("test_learned_*_in_understanding.py")
        self.assertGreater(result["ran"], 0)
        self.assertEqual(result["bad"], 0)
        self.assertNotIn(PROJECT_DB, result["hits"])

    def test_platform_layer_and_dry_run_setup_stay_isolated(self):
        result = self._run_traced("test_platform_layer.py")
        self.assertEqual(result["bad"], 0)
        self.assertNotIn(PROJECT_DB, result["hits"])

    def test_no_bare_core_or_memory_system_in_tests(self):
        """Static guard: `Core()` / `MemorySystem()` with no path resolves the shipped DB unless the module
        installs its own platform adapter (set_platform)."""
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not name.endswith(".py") or name == os.path.basename(__file__):
                continue
            with open(os.path.join(TESTS_DIR, name), encoding="utf-8") as handle:
                source = handle.read()
            if "set_platform" in source or "STANDALONE_AI_DATA_DIR" in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("Core", "MemorySystem") and not node.args and not node.keywords):
                    offenders.append("%s:%d" % (name, node.lineno))
        self.assertEqual(offenders, [])


class TestProductionPathUnchanged(IsolatedBase):
    def test_runtime_default_db_path_is_still_the_shipped_data_dir(self):
        env = {k: v for k, v in os.environ.items() if k != "STANDALONE_AI_DATA_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(os.path.realpath(os.path.join(DesktopPlatformAdapter().app_data_dir(), "memory.db")), PROJECT_DB)
            self.assertEqual(os.path.realpath(_default_db_path()), PROJECT_DB)


class TestPrompt670LifecycleStillCorrect(IsolatedBase):
    def test_prompt_670_lifecycle_tests_pass(self):
        import unittest as u
        from tests import test_learned_knowledge_context_lifecycle_prompt670 as mod
        result = u.TextTestRunner(stream=open(os.devnull, "w")).run(u.defaultTestLoader.loadTestsFromModule(mod))
        self.assertGreater(result.testsRun, 0)
        self.assertEqual(len(result.failures) + len(result.errors), 0)


if __name__ == "__main__":
    unittest.main()
