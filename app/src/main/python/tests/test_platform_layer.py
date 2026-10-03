"""
Stage 2 tests: mobile-safe core architecture.

These tests prove the success criteria from the Stage 2 brief:
  - the core can be constructed and used with zero UI code involved
  - memory / knowledge / Understanding Engine / AEL all work headless
  - the persistent data directory is configurable, and data survives
    across a second MemorySystem instance pointed at the same path
  - nothing in the core requires network access
  - the platform abstraction boundary (get_platform/set_platform)
    actually changes where a fresh Core stores its data
  - the existing web UI (interface/server.py) still starts up and
    answers a real HTTP request, unchanged

Run directly:
    python -m unittest tests.test_platform_layer -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from platform_layer import PlatformAdapter, get_platform, set_platform, reset_platform
from interface.server import make_handler


class _TempPlatformAdapter(PlatformAdapter):
    """A PlatformAdapter fully isolated to a temp directory - used to
    prove set_platform()/get_platform() actually control where a fresh
    Core's subsystems store their data, without touching the real
    desktop data/ folder at all."""

    def __init__(self, root):
        self._root = root
        self.logged = []

    def app_data_dir(self):
        return self.ensure_dir(os.path.join(self._root, "data"))

    def skill_definitions_dir(self):
        return self.ensure_dir(os.path.join(self._root, "skills_definitions"))

    def temp_dir(self):
        return self.ensure_dir(os.path.join(self._root, "tmp"))

    def log(self, component, message, level="INFO"):
        self.logged.append((level, component, message))


class TestCoreWithoutUI(unittest.TestCase):
    """Application initialization and every named subsystem, used with
    no web server, no HTTP handler, and no browser involved at all."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self._tmpdir.name, "memory.db")
        skills_dir = os.path.join(self._tmpdir.name, "skills")
        self.core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_application_initializes_without_ui(self):
        self.assertIsNotNone(self.core)
        snapshot = self.core.status_snapshot()
        self.assertIn("app_version", snapshot)

    def test_memory_access_without_ui(self):
        self.core.memory.log_message("user", "hello")
        messages = self.core.recent_messages(10)
        self.assertTrue(any(m["content"] == "hello" for m in messages))

    def test_knowledge_access_without_ui(self):
        reply = self.core.process_input("TEACH gravity IS a force that attracts mass")
        self.assertIn("[AEL OK]", reply)
        match = self.core.knowledge.find_by_name_case_insensitive("gravity")
        self.assertIsNotNone(match)
        self.assertIn("force", match["description"])

    def test_understanding_engine_without_ui(self):
        result = self.core.understand("Python is a programming language.")
        self.assertEqual(result.sentence_type, "statement")
        self.assertTrue(len(result.entities) >= 1)

    def test_ael_processing_without_ui(self):
        reply = self.core.process_input("TEACH water IS a liquid")
        self.assertIn("[AEL OK]", reply)
        ask_reply = self.core.process_input("ASK water")
        self.assertIn("liquid", ask_reply)


class TestConfigurableDataDirectory(unittest.TestCase):
    """Persistent storage location is a parameter, not a hard-coded
    desktop path - and the data actually survives a restart."""

    def test_two_cores_with_different_dirs_are_isolated(self):
        with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
            core_a = Core(
                memory_db_path=os.path.join(dir_a, "memory.db"),
                skill_definitions_dir=os.path.join(dir_a, "skills"),
            )
            core_b = Core(
                memory_db_path=os.path.join(dir_b, "memory.db"),
                skill_definitions_dir=os.path.join(dir_b, "skills"),
            )
            core_a.process_input("TEACH onlyInA IS a fact that only exists in core A")
            match_in_b = core_b.knowledge.find_by_name_case_insensitive("onlyInA")
            self.assertIsNone(match_in_b)

    def test_persistent_database_location_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "nested", "memory.db")
            first = MemorySystem(db_path)
            first.set_config("marker", "still-here")
            first._conn.close()

            second = MemorySystem(db_path)
            self.assertEqual(second.get_config("marker"), "still-here")

    def test_platform_adapter_controls_default_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _TempPlatformAdapter(tmp)
            set_platform(adapter)
            try:
                core = Core()  # no explicit paths - must come from the adapter
                core.process_input("TEACH viaAdapter IS routed through the platform adapter")
                expected_db = os.path.join(tmp, "data", "memory.db")
                self.assertTrue(os.path.isfile(expected_db))
                self.assertTrue(adapter.logged)  # Core logs its own startup via the adapter
            finally:
                reset_platform()


class TestNoNetworkRequired(unittest.TestCase):
    """The core must fully function with the platform reporting no
    network connectivity - it must never branch on network_available()
    to decide whether memory/knowledge/AEL/Understanding work."""

    def test_core_and_all_named_systems_work_with_network_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _TempPlatformAdapter(tmp)
            self.assertFalse(adapter.network_available())
            set_platform(adapter)
            try:
                core = Core()
                self.assertTrue(core.process_input("TEACH offline IS possible").startswith("[AEL"))
                self.assertIsNotNone(core.knowledge.find_by_name_case_insensitive("offline"))
                self.assertEqual(core.understand("Is this possible?").sentence_type, "question")
                health = core.health.check()
                self.assertIn(health["overall"], ("HEALTHY", "WARNING", "DEGRADED"))
            finally:
                reset_platform()

    def test_default_platform_reports_no_network_requirement(self):
        # The desktop adapter is conservative by default; nothing in the
        # core is allowed to depend on this being True.
        self.assertFalse(get_platform().network_available())


class TestExistingWebUIStillWorks(unittest.TestCase):
    """The web application described in Section 10 of the brief must
    keep working exactly as before - same server, same endpoints."""

    def test_server_starts_and_answers_real_http_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Core(
                memory_db_path=os.path.join(tmp, "memory.db"),
                skill_definitions_dir=os.path.join(tmp, "skills"),
            )
            handler_cls = make_handler(core)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/status", timeout=5
                ) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                self.assertIn("app_version", body)

                payload = json.dumps({"text": "hi"}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/message",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                self.assertIn("reply", body)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


class TestPlatformAdapterItself(unittest.TestCase):
    def tearDown(self):
        reset_platform()

    def test_default_adapter_is_desktop_and_is_singleton(self):
        reset_platform()
        first = get_platform()
        second = get_platform()
        self.assertIs(first, second)

    def test_set_platform_overrides_and_reset_restores_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _TempPlatformAdapter(tmp)
            set_platform(adapter)
            self.assertIs(get_platform(), adapter)
            reset_platform()
            self.assertIsNot(get_platform(), adapter)

    def test_ensure_dir_creates_missing_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = _TempPlatformAdapter(tmp)
            path = adapter.app_data_dir()
            self.assertTrue(os.path.isdir(path))


if __name__ == "__main__":
    unittest.main()
