"""
Tests for Prompt 954 - Runtime Growth Entry Integration (POST /api/runtime-growth).

Run directly:
    python -m unittest tests.test_runtime_growth_entry_integration_prompt954 -v
"""

import ast
import copy
import hashlib
import json
import os
import random  # noqa: F401 - imported up front so patching never triggers a lazy import
import socket  # noqa: F401
import sqlite3  # noqa: F401
import subprocess  # noqa: F401
import sys
import tempfile
import threading
import time  # noqa: F401
import unittest
import urllib.error
import urllib.request
import uuid  # noqa: F401
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from interface import server as srv
from runtime_growth import runtime_growth_cycle as cy
from runtime_integration.runtime_core import RuntimeCore

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PATH = os.path.join(PY_ROOT, "interface", "server.py")
UNAVAILABLE = cy._unavailable_cycle()
KEYS = list(cy.FIELDS)
UNCHANGED_FILES = {
    "android_entry.py": "ffa9d214a53e4aeb7e043f65ade9a398c4be2fd7d6e2dc69f4e7ce1c6bc40c07",
    "core/core.py": "64dbaef03caba1b1bc43795a21516dfce04c68d01c68f22c1f97ae98b7f77d0b",
    "ael/interpreter.py": "8c96be945ef91e5ba33c7290d6483801d7acd1beba7d14ab846dd9a7f8f3984b",
    "runtime_integration/bridge.py": "4b2177f0153d05741bc07d196f6fbadf7917521da71f4804761588564383bfac",
}


def data(**over):
    d = {"kind": "IMPROVE_RUNTIME", "goal": "Grow the runtime safely",
         "target": "runtime_growth", "reason": "Controlled growth", "source": "runtime"}
    d.update(over)
    return d


class ServerCase(unittest.TestCase):
    cls = RuntimeCore

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = self.make_core("core")
        self.start(self.core)

    def make_core(self, name, cls=None):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return (cls or self.cls)(memory_db_path=os.path.join(base, "m.sqlite3"),
                                 skill_definitions_dir=os.path.join(base, "skills"))

    def start(self, core):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(core))
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        def stop():
            self.server.shutdown()
            self.server.server_close()
        self.addCleanup(stop)

    def call(self, method, path, body=None, raw=None, port=None):
        payload = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(f"http://127.0.0.1:{port or self.port}{path}",
                                     data=payload, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def grow(self, body=None, **kw):
        return self.call("POST", "/api/runtime-growth", body, **kw)


class TestEndpoint(ServerCase):
    def test_endpoint_exists(self):
        status, body = self.grow(data())
        self.assertEqual(status, 200)
        self.assertNotEqual(body, {"error": "not found"})
        self.assertEqual(self.call("GET", "/api/runtime-growth")[0], 404)  # POST only
        self.assertEqual(self.call("POST", "/api/runtime-growth-x", data())[0], 404)

    def test_valid_request_reaches_runtimecore_only_growth_entry(self):
        real = RuntimeCore.run_controlled_runtime_growth
        with mock.patch.object(RuntimeCore, "run_controlled_runtime_growth", autospec=True,
                               side_effect=real) as entry:
            status, body = self.grow(data())
        self.assertEqual(status, 200)
        entry.assert_called_once_with(self.core, data())  # the handler's own RuntimeCore
        self.assertEqual(body["status"], "verified")

    def test_prompt_952_remains_sole_orchestrator(self):
        real = cy.run_controlled_runtime_growth_cycle
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle", side_effect=real) as spy:
            self.grow(data())
            self.grow(None)
        self.assertEqual(spy.call_count, 2)
        spy.assert_any_call(data())

    def test_valid_supported_request_result(self):
        status, body = self.grow(data())
        self.assertEqual(status, 200)
        self.assertEqual(list(body), KEYS)
        self.assertEqual(body["status"], "verified")
        self.assertIs(body["available"], True)
        self.assertIs(body["application_verified"], True)
        self.assertIs(body["persistent"], False)
        self.assertIs(body["source_modified"], False)

    def test_response_is_the_runtimecore_result_unchanged(self):
        _, body = self.grow(data())
        self.assertEqual(body, cy.run_controlled_runtime_growth_cycle(data()))
        self.assertEqual(body, self.core.get_last_controlled_runtime_growth())
        other = self.make_core("other").run_controlled_runtime_growth(data())
        self.assertEqual(body, other)

    def test_no_permission_or_extra_claims(self):
        _, body = self.grow(data())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "executed", "committed", "code", "persisted"):
            self.assertNotIn(name, body)
        self.assertIs(body["persistent"], False)
        self.assertIs(body["source_modified"], False)

    def test_repeated_requests_deterministic(self):
        first = self.grow(data())
        for _ in range(5):
            self.assertEqual(self.grow(data()), first)

    def test_stub_result_passes_through_untouched(self):
        sentinel = {"sentinel": [1, 2, 3], "n": None}
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle", return_value=sentinel):
            self.assertEqual(self.grow(data()), (200, sentinel))


class TestInvalidRequests(ServerCase):
    def assert_unavailable(self, status_body):
        status, body = status_body
        self.assertEqual(status, 200)
        self.assertEqual(body, UNAVAILABLE)
        self.assertEqual(list(body), KEYS)

    def test_invalid_request_exact_unavailable(self):
        for bad in ({}, {"kind": "NOPE"}, dict(data(), extra=1),
                    dict(data(), request_id="growth_req_forged"), [], "x", 5, None, True,
                    data(goal=""), data(goal=5)):
            self.assert_unavailable(self.grow(bad, raw=json.dumps(bad).encode()))

    def test_malformed_json_safely_handled(self):
        for raw in (b"{not json", b"\xff\xfe", b'{"kind": ', b"[1,"):
            status, body = self.grow(raw=raw)
            self.assertEqual((status, body), (400, {"error": "invalid json"}))
        self.assertEqual(self.call("GET", "/api/health")[0], 200)  # server still healthy

    def test_missing_body_safely_handled(self):
        self.assert_unavailable(self.grow())
        self.assert_unavailable(self.grow(raw=b""))

    def test_unsupported_kind_rejected(self):
        for kind in ("DELETE_CAPABILITY", "improve_runtime", "", None, 5):
            self.assert_unavailable(self.grow(data(kind=kind)))

    def test_unsupported_target_rejected(self):
        for target in ("code_analysis", "other", "Runtime_Growth", "", None):
            self.assert_unavailable(self.grow(data(target=target)))

    def test_create_and_improve_capability_do_not_enter_cycle(self):
        for kind in ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY"):
            for target in ("runtime_growth", "code_analysis"):
                self.assert_unavailable(self.grow(data(kind=kind, target=target)))
        self.assertEqual(self.core.get_last_controlled_runtime_growth(), UNAVAILABLE)

    def test_invalid_request_does_not_leak_untrusted_fields(self):
        _, body = self.grow(data(kind="CREATE_CAPABILITY", goal="secret-goal"))
        self.assertNotIn("secret", json.dumps(body))

    def test_oversized_body_keeps_existing_convention(self):
        raw = b"{" + b" " * (srv.MAX_BODY_BYTES + 10) + b"}"
        self.assertEqual(self.grow(raw=raw), (413, {"error": "request body too large"}))

    def test_plain_core_has_no_growth_route(self):
        plain = self.make_core("plain", Core)
        self.start(plain)
        self.assertEqual(self.call("POST", "/api/runtime-growth", data()),
                         (404, {"error": "not found"}))


class TestExistingEndpointsUnchanged(ServerCase):
    def two_servers(self):
        """A server that also served growth requests vs a pristine one."""
        grown, pristine = self.core, self.make_core("pristine")
        server_a = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(grown))
        server_b = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(pristine))
        for s in (server_a, server_b):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(lambda s=s: (s.shutdown(), s.server_close()))
        return server_a.server_address[1], server_b.server_address[1]

    def test_message_status_health_history_unchanged(self):
        pa, pb = self.two_servers()
        for text in ("hello", "من عرفان هستم", "What is Python?", "TEACH sun IS a star",
                     "ASK sun", ""):
            self.call("POST", "/api/runtime-growth", data(), port=pa)
            self.call("POST", "/api/runtime-growth", {"kind": "NOPE"}, port=pa)
            sa, ba = self.call("POST", "/api/message", {"text": text}, port=pa)
            sb, bb = self.call("POST", "/api/message", {"text": text}, port=pb)
            self.assertEqual((sa, ba["reply"]), (sb, bb["reply"]), text)
            self.assertEqual(set(ba), set(bb))
            self.assertEqual(set(ba["status"]), set(bb["status"]))
        for path in ("/api/status", "/api/health", "/api/history", "/api/learning-history",
                     "/api/errors", "/api/runtime-result"):
            sa, ba = self.call("GET", path, port=pa)
            sb, bb = self.call("GET", path, port=pb)
            self.assertEqual(sa, sb, path)
            self.assertEqual(set(ba), set(bb), path)
        _, ha = self.call("GET", "/api/history", port=pa)
        _, hb = self.call("GET", "/api/history", port=pb)
        self.assertEqual([m.get("text") for m in ha["messages"]],
                         [m.get("text") for m in hb["messages"]])
        self.assertEqual(self.call("GET", "/api/health", port=pa)[1]["overall"]
                         if "overall" in self.call("GET", "/api/health", port=pa)[1] else None,
                         self.call("GET", "/api/health", port=pb)[1]["overall"]
                         if "overall" in self.call("GET", "/api/health", port=pb)[1] else None)

    def test_static_inspect_code_and_unknown_routes_unchanged(self):
        self.assertEqual(self.call("GET", "/nope"), (404, {"error": "not found"}))
        self.assertEqual(self.call("GET", "/static/../core/core.py"), (404, {"error": "not found"}))
        self.assertEqual(self.call("POST", "/api/nope", {}), (404, {"error": "not found"}))
        status, body = self.call("POST", "/api/inspect-code", {"code": "x = 1"})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.core.inspect_code("x = 1"))
        self.assertEqual(self.call("POST", "/api/inspect-code", {"code": 5})[0], 400)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as resp:
            self.assertEqual(resp.status, 200)

    def test_growth_calls_do_not_change_conversation_state(self):
        before = (len(self.core.recent_messages(50)), len(self.core.context.get_recent_turns()),
                  len(self.core.upgrades.history(100)), self.core.capabilities.all())
        for _ in range(3):
            self.grow(data())
            self.grow(data(kind="CREATE_CAPABILITY"))
        self.assertEqual(before, (len(self.core.recent_messages(50)),
                                  len(self.core.context.get_recent_turns()),
                                  len(self.core.upgrades.history(100)),
                                  self.core.capabilities.all()))
        self.assertIsNone(self.core.last_runtime_result)  # no turn was processed

    def test_core_ael_learning_android_files_unchanged(self):
        for rel, digest in UNCHANGED_FILES.items():
            with open(os.path.join(PY_ROOT, rel), "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), digest, rel)

    def test_growth_does_not_execute_ael_learning_or_upgrades(self):
        boom = AssertionError("growth must not run this")
        with mock.patch.object(self.core.ael, "run", side_effect=boom), \
                mock.patch.object(self.core.upgrades, "propose_upgrade", side_effect=boom), \
                mock.patch.object(self.core.learning, "teach", side_effect=boom), \
                mock.patch.object(self.core.learning, "relate", side_effect=boom), \
                mock.patch.object(self.core.capabilities, "set_enabled", side_effect=boom):
            self.assertEqual(self.grow(data())[1]["status"], "verified")
            self.assertEqual(self.grow(data(kind="CREATE_CAPABILITY"))[1], UNAVAILABLE)


class TestLifecycleAndPurity(ServerCase):
    def test_no_second_runtimecore_per_request(self):
        created = []
        real_init = RuntimeCore.__init__

        def counting(self_, *a, **k):
            created.append(1)
            return real_init(self_, *a, **k)

        with mock.patch.object(RuntimeCore, "__init__", counting), \
                mock.patch.object(Core, "__init__", side_effect=AssertionError("new Core")):
            for _ in range(5):
                self.grow(data())
                self.grow(None)
        self.assertEqual(created, [])

    def test_endpoint_uses_the_handlers_existing_core(self):
        seen = []
        real = RuntimeCore.run_controlled_runtime_growth

        def spy(self_, request_data):
            seen.append(self_)
            return real(self_, request_data)

        with mock.patch.object(RuntimeCore, "run_controlled_runtime_growth", spy):
            self.grow(data())
            self.grow(data())
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(s is self.core for s in seen))

    def test_server_adds_no_direct_growth_imports_or_stage_calls(self):
        with open(SERVER_PATH, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("runtime_growth"), node.module)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name.startswith("runtime_growth"), a.name)
        for stage in ("create_runtime_growth_request", "validate_runtime_growth_request",
                      "analyze_runtime_growth_request", "build_runtime_growth_plan",
                      "build_runtime_growth_proposal", "validate_runtime_growth_proposal",
                      "evaluate_runtime_growth_application_boundary",
                      "build_runtime_growth_application_request",
                      "build_runtime_growth_application_contract",
                      "build_runtime_growth_application_result",
                      "build_runtime_growth_application_transaction",
                      "apply_runtime_growth_transaction", "verify_runtime_growth_application",
                      "run_controlled_runtime_growth_cycle", "runtime_growth_cycle"):
            self.assertNotIn(stage, source, stage)
        self.assertEqual(source.count('getattr(core, "run_controlled_runtime_growth", None)'), 1)
        for banned in ("subprocess", "random", "uuid", "time", "datetime", "sqlite3", "socket",
                       "importlib", "shutil", "pathlib"):
            self.assertNotIn("import " + banned, source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("exec(", source)

    def test_no_filesystem_database_subprocess_eval_exec_random_uuid(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        root = os.path.dirname(PY_ROOT)

        def state():
            out = {}
            for d, ds, fs in os.walk(root):
                ds[:] = sorted(x for x in ds if x != "__pycache__")
                for f in sorted(fs):
                    if not f.endswith(".pyc"):
                        with open(os.path.join(d, f), "rb") as h:
                            out[os.path.join(d, f)] = hashlib.sha256(h.read()).hexdigest()
            return out

        before = state()
        db_path = os.path.join(PY_ROOT, "data", "memory.db")
        with open(db_path, "rb") as h:
            db_before = hashlib.sha256(h.read()).hexdigest()
        # the HTTP server itself legitimately uses the clock and sockets, so only the
        # growth-relevant forbidden operations are trapped while requests are served
        with mock.patch("sqlite3.connect", side_effect=trap), \
                mock.patch("subprocess.Popen", side_effect=trap), \
                mock.patch("os.system", side_effect=trap), \
                mock.patch("os.remove", side_effect=trap), \
                mock.patch("os.rename", side_effect=trap), \
                mock.patch("os.mkdir", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap), \
                mock.patch("uuid.uuid1", side_effect=trap):
            ok = self.grow(data())
            bad = self.grow(data(kind="CREATE_CAPABILITY"))
            malformed = self.grow(raw=b"{bad")
        self.assertEqual(ok[1]["status"], "verified")
        self.assertEqual(bad[1], UNAVAILABLE)
        self.assertEqual(malformed[0], 400)
        self.assertEqual(state(), before)
        with open(db_path, "rb") as h:
            self.assertEqual(hashlib.sha256(h.read()).hexdigest(), db_before)

    def test_growth_path_does_not_read_clock_random_or_uuid(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        core = self.core
        with mock.patch("time.time", side_effect=trap), \
                mock.patch("time.monotonic", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap):
            self.assertEqual(core.run_controlled_runtime_growth(data())["status"], "verified")
            self.assertEqual(core.run_controlled_runtime_growth(None), UNAVAILABLE)

    def test_input_not_mutated_by_handler_path(self):
        d = data()
        before = copy.deepcopy(d)
        self.grow(d)
        self.assertEqual(d, before)


if __name__ == "__main__":
    unittest.main()
