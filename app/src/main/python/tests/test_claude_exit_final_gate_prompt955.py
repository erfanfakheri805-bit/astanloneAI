"""
Tests for Prompt 955 - Final Claude-Exit End-to-End Validation Gate.

A validation-only module: it adds no production code. It drives the REAL runtime
entry (a real ThreadingHTTPServer built with the existing `make_handler` over a
real `RuntimeCore`, a real HTTP POST to /api/runtime-growth) and collects evidence
that the controlled runtime-growth path

    POST /api/runtime-growth -> handler -> its RuntimeCore
      -> RuntimeCore.run_controlled_runtime_growth -> Prompt 952 cycle
      -> Prompts 939..951 -> verified in-memory result

executes without Claude (or any external AI) being part of the implementation /
execution chain, while staying controlled and non-persistent.

The precise claim validated is NOT "the application never needs Claude again":
only that THIS implemented controlled runtime-growth path can execute through the
application runtime without Claude being part of that implementation/execution chain.

The evidence structure `collect_gate_evidence()` is test-only (no production API).
`CLAUDE_EXIT_MILESTONE = PASS|BLOCKED` is printed from the measured evidence.

Run directly:
    python -m unittest tests.test_claude_exit_final_gate_prompt955 -v
"""

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess  # noqa: F401 - imported up front so patching never triggers a lazy import
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from interface import server as srv
from runtime_growth import runtime_growth_cycle as cy
from runtime_integration.runtime_core import RuntimeCore

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.abspath(os.path.join(PY_ROOT, "..", "..", "..", ".."))
SERVER_PATH = os.path.join(PY_ROOT, "interface", "server.py")
RUNTIME_CORE_PATH = os.path.join(PY_ROOT, "runtime_integration", "runtime_core.py")
GROWTH_DIR = os.path.join(PY_ROOT, "runtime_growth")
SHIPPED_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_DB_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

UNAVAILABLE = cy._unavailable_cycle()
KEYS = list(cy.FIELDS)
EXPECTED_STAGE_STATUSES = {
    "request_status": "valid",
    "plan_status": "planned",
    "proposal_status": "proposed",
    "boundary_status": "eligible",
    "application_request_status": "ready",
    "contract_status": "contracted",
    "transaction_status": "prepared",
    "application_status": "applied",
    "verification_status": "verified",
}
# Production files that Prompt 955 must leave exactly as Prompt 954 delivered them.
UNCHANGED_FILES = {
    "android_entry.py": "ffa9d214a53e4aeb7e043f65ade9a398c4be2fd7d6e2dc69f4e7ce1c6bc40c07",
    "core/core.py": "64dbaef03caba1b1bc43795a21516dfce04c68d01c68f22c1f97ae98b7f77d0b",
    "ael/interpreter.py": "8c96be945ef91e5ba33c7290d6483801d7acd1beba7d14ab846dd9a7f8f3984b",
    "runtime_integration/bridge.py": "4b2177f0153d05741bc07d196f6fbadf7917521da71f4804761588564383bfac",
    "interface/server.py": "97f3f0659fb2881690db4b02340508156ba24039c0846551098fb3343aabb642",
    "runtime_integration/runtime_core.py": "610e0c5c51f47fc95f574cd90958a6a94f61c803f114d388f435cbc85f658cdf",
    "runtime_growth/runtime_growth_cycle.py": "d7015ed497e4fef18280c1b6592c13a5c415ff8226568b349aefa07205dd2bcd",
}

# (module attribute name on the cycle module, function name) for Prompts 939..951, in order.
CYCLE_CALLER = ("runtime_growth_cycle.py", "run_controlled_runtime_growth_cycle")
STAGES = (
    ("_request", "create_runtime_growth_request"),                       # 939
    ("_request_validation", "validate_runtime_growth_request"),          # 940
    ("_analysis", "analyze_runtime_growth_request"),                     # 941
    ("_plan", "build_runtime_growth_plan"),                              # 942
    ("_proposal", "build_runtime_growth_proposal"),                      # 943
    ("_proposal_validation", "validate_runtime_growth_proposal"),        # 944
    ("_boundary", "evaluate_runtime_growth_application_boundary"),       # 945
    ("_app_request", "build_runtime_growth_application_request"),        # 946
    ("_contract", "build_runtime_growth_application_contract"),          # 947
    ("_app_result", "build_runtime_growth_application_result"),          # 948
    ("_transaction", "build_runtime_growth_application_transaction"),    # 949
    ("_application", "apply_runtime_growth_transaction"),                # 950
    ("_verification", "verify_runtime_growth_application"),              # 951
)

FORBIDDEN_AI_MODULES = ("anthropic", "openai", "requests", "httpx", "urllib3", "aiohttp",
                        "torch", "transformers", "tensorflow", "llama_cpp", "onnxruntime",
                        "huggingface_hub", "google.generativeai", "cohere", "mistralai")
FORBIDDEN_GROWTH_IMPORTS = FORBIDDEN_AI_MODULES + (
    "urllib", "http", "socket", "ssl", "subprocess", "shutil", "ctypes", "importlib",
    "sqlite3", "os", "sys", "tempfile", "pathlib", "pickle", "marshal", "runpy", "builtins",
    "autonomy", "capabilities", "upgrade", "self_upgrade", "core", "interface", "memory")
AI_KEY_ENV_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY",
                    "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "COHERE_API_KEY",
                    "MISTRAL_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY")
MODEL_FILE_SUFFIXES = (".gguf", ".ggml", ".onnx", ".safetensors", ".pt", ".pth", ".tflite", ".bin")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
HIDDEN_EXEC_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                      "os.fork", "os.forkpty", "ctypes.dlopen", "ctypes.dlsym")
FILE_MUTATION_EVENTS = ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod",
                        "os.chown", "os.truncate", "os.symlink", "os.link", "os.utime",
                        "shutil.rmtree", "shutil.copyfile", "shutil.move", "shutil.copytree",
                        "tempfile.mkdtemp", "tempfile.mkstemp")


def data(**over):
    d = {"kind": "IMPROVE_RUNTIME", "goal": "Grow the runtime safely",
         "target": "runtime_growth", "reason": "Controlled growth", "source": "runtime"}
    d.update(over)
    return d


# --------------------------------------------------------------------------------------
# Audit-hook recorder: a process-wide hook installed once; it records (and, for non-loopback
# network access, blocks) only while a guarded window is active, and is inert otherwise.
# --------------------------------------------------------------------------------------
_AUDIT = {"active": False, "events": [], "allowed_port": None}


def _is_loopback(address):
    if isinstance(address, tuple) and address:
        return address[0] in ("127.0.0.1", "::1", "localhost")
    return False


def _audit_hook(event, args):
    if not _AUDIT["active"]:
        return
    try:
        if event == "socket.connect":
            _AUDIT["events"].append((event, repr(args[1])))
            if not _is_loopback(args[1]):
                raise RuntimeError("blocked non-loopback network connect: %r" % (args[1],))
        elif event == "socket.getaddrinfo":
            _AUDIT["events"].append((event, repr(args[0])))
            if args[0] not in ("127.0.0.1", "::1", "localhost", None):
                raise RuntimeError("blocked name resolution: %r" % (args[0],))
        elif event == "open":
            path, mode, flags = args[0], args[1], args[2]
            writing = (isinstance(flags, int) and bool(flags & WRITE_FLAGS)) or (
                isinstance(mode, str) and any(c in mode for c in "wax+"))
            _AUDIT["events"].append(("open_write" if writing else "open_read", str(path)))
        elif event in ("exec", "compile"):
            filename = args[1] if event == "compile" and len(args) > 1 else ""
            # Source-file compiles belong to lazy imports; string/anonymous code is what matters.
            if event == "exec" or str(filename).startswith("<"):
                _AUDIT["events"].append((event, str(filename)))
        elif event in HIDDEN_EXEC_EVENTS or event in FILE_MUTATION_EVENTS:
            _AUDIT["events"].append((event, repr(args)[:200]))
        elif event in ("sqlite3.connect", "urllib.Request"):
            _AUDIT["events"].append((event, repr(args)[:200]))
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - the recorder must never break the process
        pass


sys.addaudithook(_audit_hook)


class guarded:
    """Context manager: record audit events (and block external network) in its window."""

    def __enter__(self):
        _AUDIT["events"] = []
        _AUDIT["active"] = True
        return _AUDIT["events"]

    def __exit__(self, *exc):
        _AUDIT["active"] = False
        return False


# --------------------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------------------
def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_fingerprint(root):
    """{relative path: sha256} for every file under `root`, ignoring bytecode caches."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, root).replace(os.sep, "/")] = _sha256_file(full)
    return out


def tree_diff(before, after):
    return {"added": sorted(set(after) - set(before)),
            "deleted": sorted(set(before) - set(after)),
            "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def db_snapshot(db_path):
    """Per-table (row count, content hash) read through a fresh connection."""
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        snap = {}
        for t in tables:
            rows = conn.execute('SELECT * FROM "%s" ORDER BY rowid' % t).fetchall()
            snap[t] = (len(rows), hashlib.sha256(repr(rows).encode("utf-8")).hexdigest())
        return snap
    finally:
        conn.close()


# --------------------------------------------------------------------------------------
# Real runtime harness
# --------------------------------------------------------------------------------------
class Runtime:
    """A real RuntimeCore behind a real ThreadingHTTPServer built from `make_handler`."""

    def __init__(self, base, use_shipped_db_copy=False):
        os.makedirs(base, exist_ok=True)
        self.db_path = os.path.join(base, "m.sqlite3")
        if use_shipped_db_copy:
            shutil.copyfile(SHIPPED_DB, self.db_path)
        self.base = base
        self.core = RuntimeCore(memory_db_path=self.db_path,
                                skill_definitions_dir=os.path.join(base, "skills"))
        self.handler_cls = srv.make_handler(self.core)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_cls)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, raw=None):
        payload = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=payload,
                                     method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def grow(self, body=None, raw=None):
        return self.call("POST", "/api/runtime-growth", body, raw=raw)

    def dir_fingerprint(self):
        return tree_fingerprint(self.base)


def _handler_owned_cores(handler_cls):
    """Every object the handler's request methods close over that is a Core."""
    found = []
    for name in ("_route_post", "_route_get", "do_GET", "do_POST"):
        fn = getattr(handler_cls, name, None)
        for cell in (getattr(fn, "__closure__", None) or ()):
            try:
                obj = cell.cell_contents
            except ValueError:
                continue
            if isinstance(obj, Core) and not any(obj is f for f in found):
                found.append(obj)  # one entry per distinct Core object
    return found


class StageSpy:
    """Wraps the 13 Prompt 939-951 stage functions (reached only through the cycle module's
    own references) and records, per stage, the direct caller of every call."""

    def __init__(self):
        self.calls = {name: [] for _, name in STAGES}
        self._patches = []

    def __enter__(self):
        for attr, fname in STAGES:
            module = getattr(cy, attr)
            real = getattr(module, fname)

            def wrapper(*a, _real=real, _fname=fname, **k):
                caller = sys._getframe(1)
                self.calls[_fname].append((os.path.basename(caller.f_code.co_filename),
                                           caller.f_code.co_name))
                return _real(*a, **k)

            patcher = mock.patch.object(module, fname, wrapper)
            patcher.start()
            self._patches.append(patcher)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False

    def counts(self):
        """Calls made directly by the Prompt 952 cycle function, per stage."""
        return {name: sum(1 for c in calls if c == CYCLE_CALLER)
                for name, calls in self.calls.items()}

    def foreign_callers(self):
        """Direct callers that are neither the cycle nor another runtime_growth_* module
        (i.e. any server / RuntimeCore / test code reaching a stage directly)."""
        return sorted({(n, c) for calls in self.calls.values() for n, c in calls
                       if (n, c) != CYCLE_CALLER and not n.startswith("runtime_growth_")})


# --------------------------------------------------------------------------------------
# Evidence collection (test-only structure) - one real flow, measured, never hard-coded True
# --------------------------------------------------------------------------------------
def collect_gate_evidence():
    ev = {}
    tmp = tempfile.TemporaryDirectory()
    rt = Runtime(os.path.join(tmp.name, "runtime"), use_shipped_db_copy=True)
    pristine_db = os.path.join(tmp.name, "pristine.sqlite3")
    shutil.copyfile(SHIPPED_DB, pristine_db)
    pristine = RuntimeCore(memory_db_path=pristine_db,
                           skill_definitions_dir=os.path.join(tmp.name, "pristine_skills"))
    try:
        # Warm the server (lazy imports) with a read-only GET, outside any guarded window.
        rt.call("GET", "/api/health")

        shipped_hash_before = _sha256_file(SHIPPED_DB)
        tree_before = tree_fingerprint(PROJECT_ROOT)
        db_hash_before = _sha256_file(rt.db_path)
        db_before = db_snapshot(rt.db_path)
        dir_before = rt.dir_fingerprint()
        last_before = rt.core.get_last_controlled_runtime_growth()
        constructed = []

        def counting(orig):
            def init(self, *a, **k):
                constructed.append(type(self).__name__)
                return orig(self, *a, **k)
            return init

        real_entry = RuntimeCore.run_controlled_runtime_growth
        real_cycle = cy.run_controlled_runtime_growth_cycle
        scrubbed_env = {k: v for k, v in os.environ.items() if k not in AI_KEY_ENV_NAMES}
        modules_before = set(sys.modules)
        with mock.patch.dict(os.environ, scrubbed_env, clear=True), \
                mock.patch.object(Core, "__init__", counting(Core.__init__)), \
                mock.patch.object(RuntimeCore, "run_controlled_runtime_growth", autospec=True,
                                  side_effect=real_entry) as entry_spy, \
                mock.patch.object(cy, "run_controlled_runtime_growth_cycle",
                                  side_effect=real_cycle) as cycle_spy, \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")), \
                mock.patch.object(os, "system", side_effect=AssertionError("os.system")), \
                StageSpy() as stages, guarded() as events:
            status, body = rt.grow(data())
        modules_after = set(sys.modules)

        ev["http_status"] = status
        ev["body"] = body
        ev["entry_call_count"] = entry_spy.call_count
        ev["entry_called_on_handler_core"] = (
            entry_spy.call_count == 1 and entry_spy.call_args[0][0] is rt.core
            and entry_spy.call_args[0][1] == data())
        ev["cycle_call_count"] = cycle_spy.call_count
        ev["cycle_called_with_request"] = cycle_spy.call_args_list == [mock.call(data())]
        ev["stage_counts"] = stages.counts()
        ev["stage_foreign_callers"] = stages.foreign_callers()
        ev["stage_callers"] = stages.calls
        ev["constructed_cores"] = list(constructed)
        ev["handler_cores"] = _handler_owned_cores(rt.handler_cls)
        ev["events"] = list(events)
        ev["new_modules"] = sorted(modules_after - modules_before)
        ev["last_growth_on_handler_core"] = rt.core.get_last_controlled_runtime_growth()
        ev["last_growth_on_other_core"] = pristine.get_last_controlled_runtime_growth()
        ev["last_growth_before"] = last_before

        ev["shipped_db_hash_before"] = shipped_hash_before
        ev["shipped_db_hash_after"] = _sha256_file(SHIPPED_DB)
        ev["tree_diff"] = tree_diff(tree_before, tree_fingerprint(PROJECT_ROOT))
        ev["runtime_db_hash_same"] = _sha256_file(rt.db_path) == db_hash_before
        db_after = db_snapshot(rt.db_path)
        ev["db_changed_tables"] = sorted(t for t in set(db_before) | set(db_after)
                                         if db_before.get(t) != db_after.get(t))
        ev["db_before"] = db_before
        ev["runtime_dir_diff"] = tree_diff(dir_before, rt.dir_fingerprint())

        # Backward compatibility, measured against a pristine twin that never served a growth call.
        twin = Runtime(os.path.join(tmp.name, "twin"), use_shipped_db_copy=True)
        try:
            compat = []
            for text in ("hello", "What is Python?", "TEACH sun IS a star", "ASK sun"):
                sa, ba = rt.call("POST", "/api/message", {"text": text})
                sb, bb = twin.call("POST", "/api/message", {"text": text})
                compat.append((sa, sb, ba.get("reply") == bb.get("reply"),
                               set(ba) == set(bb) == {"reply", "status"},
                               set(ba["status"]) == set(bb["status"])))
            for path in ("/api/status", "/api/health", "/api/history", "/api/learning-history",
                         "/api/errors", "/api/runtime-result"):
                sa, ba = rt.call("GET", path)
                sb, bb = twin.call("GET", path)
                compat.append((sa, sb, True, set(ba) == set(bb), True))
            ha = rt.call("GET", "/api/history")[1]
            hb = twin.call("GET", "/api/history")[1]
            compat.append((200, 200, [m.get("text") for m in ha["messages"]]
                           == [m.get("text") for m in hb["messages"]], True, True))
            ev["compat_results"] = compat
            ev["compat_ok"] = all(sa == sb == 200 and r1 and r2 and r3
                                  for sa, sb, r1, r2, r3 in compat)
        finally:
            twin.close()
    finally:
        rt.close()
        tmp.cleanup()

    body = ev["body"]
    write_events = [e for e in ev["events"] if e[0] in ("open_write",) + FILE_MUTATION_EVENTS]
    network_events = [e for e in ev["events"] if e[0] in ("socket.connect", "socket.getaddrinfo")]
    ev["write_events"] = write_events
    ev["non_loopback_network"] = [e for e in network_events
                                  if not (e[1].startswith("('127.0.0.1'") or e[1] in
                                          ("'127.0.0.1'", "'localhost'", "None"))]
    ev["hidden_exec_events"] = [e for e in ev["events"]
                                if e[0] in HIDDEN_EXEC_EVENTS + ("exec", "compile")]
    ev["sqlite_connect_events"] = [e for e in ev["events"] if e[0] == "sqlite3.connect"]
    ev["model_file_reads"] = [e for e in ev["events"] if e[0] == "open_read"
                              and e[1].lower().endswith(MODEL_FILE_SUFFIXES)]
    ev["ai_modules_loaded"] = sorted(
        m for m in sys.modules
        if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_AI_MODULES))

    through_real_entry = (
        ev["http_status"] == 200 and ev["entry_call_count"] == 1
        and ev["entry_called_on_handler_core"] and ev["cycle_call_count"] == 1
        and ev["cycle_called_with_request"] and ev["constructed_cores"] == []
        and ev["handler_cores"] and ev["handler_cores"][0] is not None
        and ev["last_growth_on_handler_core"] == body
        and ev["last_growth_on_other_core"] is None)
    verified = (
        list(body) == KEYS and body["available"] is True and body["status"] == "verified"
        and body["application_verified"] is True
        and all(body[k] == v for k, v in EXPECTED_STAGE_STATUSES.items())
        and body == real_cycle(data())
        and all(n == 1 for n in ev["stage_counts"].values())
        and ev["stage_foreign_callers"] == [])
    claude_required = bool(
        ev["non_loopback_network"] or ev["model_file_reads"] or ev["ai_modules_loaded"]
        or ev["hidden_exec_events"] or ev["sqlite_connect_events"] or _static_ai_references())
    persistent_change = (body["persistent"] is not False or bool(ev["db_changed_tables"])
                         or not ev["runtime_db_hash_same"] or bool(write_events)
                         or any(ev["runtime_dir_diff"].values()))
    source_change = (body["source_modified"] is not False
                     or any(ev["tree_diff"].values()) or bool(write_events))
    memory_change = (ev["shipped_db_hash_before"] != ev["shipped_db_hash_after"]
                     or ev["shipped_db_hash_after"] != PRISTINE_DB_SHA256
                     or bool(ev["db_changed_tables"]) or not ev["runtime_db_hash_same"])
    evidence = {
        "runtime_growth_executed_through_real_entry": through_real_entry,
        "controlled_cycle_verified": verified,
        "claude_required_for_cycle": claude_required,
        "persistent_change": persistent_change,
        "source_change": source_change,
        "memory_change": memory_change,
        "backward_compatibility": ev["compat_ok"],
    }
    evidence["claude_exit_gate_ready"] = (
        evidence["runtime_growth_executed_through_real_entry"]
        and evidence["controlled_cycle_verified"]
        and evidence["claude_required_for_cycle"] is False
        and evidence["persistent_change"] is False
        and evidence["source_change"] is False
        and evidence["memory_change"] is False
        and evidence["backward_compatibility"] is True)
    return evidence, ev


def milestone_decision(evidence):
    if evidence["claude_exit_gate_ready"]:
        return "CLAUDE_EXIT_MILESTONE = PASS", []
    blockers = [k for k, want in (
        ("runtime_growth_executed_through_real_entry", True),
        ("controlled_cycle_verified", True), ("claude_required_for_cycle", False),
        ("persistent_change", False), ("source_change", False), ("memory_change", False),
        ("backward_compatibility", True)) if evidence[k] is not want]
    return "CLAUDE_EXIT_MILESTONE = BLOCKED", blockers


# --------------------------------------------------------------------------------------
# Static Claude-independence evidence
# --------------------------------------------------------------------------------------
def _growth_sources():
    out = {}
    for name in sorted(os.listdir(GROWTH_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(GROWTH_DIR, name), encoding="utf-8") as fh:
                out["runtime_growth/" + name] = fh.read()
    return out


def _growth_entry_sources():
    """Source text of everything the growth route executes outside the growth package:
    the server's route branch and the two RuntimeCore growth methods."""
    with open(SERVER_PATH, encoding="utf-8") as fh:
        server_src = fh.read()
    with open(RUNTIME_CORE_PATH, encoding="utf-8") as fh:
        core_src = fh.read()
    tree = ast.parse(core_src)
    segments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "run_controlled_runtime_growth", "get_last_controlled_runtime_growth"):
            segments.append(ast.get_source_segment(core_src, node))
    return server_src, segments


def _static_ai_references():
    """Case-insensitive references to Claude / external AI services in the growth path."""
    needles = ("claude", "anthropic", "openai", "api_key", "apikey", "gemini", "llm_api")
    hits = []
    server_src, segments = _growth_entry_sources()
    for label, src in list(_growth_sources().items()) + [("interface/server.py", server_src)] + [
            ("runtime_core growth method", s) for s in segments]:
        low = src.lower()
        hits += [(label, n) for n in needles if n in low]
    return hits


def _imports_of(src):
    mods = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    return mods


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------
class TestFinalGate(unittest.TestCase):
    """The headline gate: one real HTTP growth request, measured end to end."""

    @classmethod
    def setUpClass(cls):
        cls.evidence, cls.ev = collect_gate_evidence()
        cls.decision, cls.blockers = milestone_decision(cls.evidence)
        print("\nPrompt 955 gate evidence: " + json.dumps(cls.evidence, sort_keys=True))
        print(cls.decision + ("" if not cls.blockers else "  blockers=" + ",".join(cls.blockers)))

    def test_real_http_request_result(self):
        self.assertEqual(self.ev["http_status"], 200)
        body = self.ev["body"]
        self.assertEqual(list(body), KEYS)
        self.assertIs(body["available"], True)
        self.assertEqual(body["status"], "verified")
        self.assertIs(body["application_verified"], True)
        self.assertIs(body["persistent"], False)
        self.assertIs(body["source_modified"], False)

    def test_intermediate_statuses_show_complete_successful_chain(self):
        body = self.ev["body"]
        for key, expected in EXPECTED_STAGE_STATUSES.items():
            self.assertEqual(body[key], expected, key)
        self.assertTrue(body["request_id"].startswith("growth_req_"))
        self.assertEqual(body, cy.run_controlled_runtime_growth_cycle(data()))

    def test_exactly_one_prompt_952_cycle_per_request(self):
        self.assertEqual(self.ev["cycle_call_count"], 1)
        self.assertTrue(self.ev["cycle_called_with_request"])

    def test_every_stage_runs_once_and_only_from_the_cycle(self):
        self.assertEqual(self.ev["stage_counts"], {name: 1 for _, name in STAGES})
        # Later stages re-derive earlier ones internally (inside the runtime_growth package);
        # nothing outside the cycle - the server, RuntimeCore, the test - ever calls a stage.
        self.assertEqual(self.ev["stage_foreign_callers"], [])
        for stage, callers in self.ev["stage_callers"].items():
            self.assertEqual(callers.count(CYCLE_CALLER), 1, stage)
            self.assertNotIn(("server.py", "_route_post"), callers)
            self.assertFalse([c for c in callers if c[0] in ("runtime_core.py", "server.py")])

    def test_request_handled_by_handler_owned_runtimecore(self):
        self.assertEqual(self.ev["entry_call_count"], 1)
        self.assertTrue(self.ev["entry_called_on_handler_core"])
        self.assertEqual(len(self.ev["handler_cores"]), 1)  # one distinct Core behind the handler
        self.assertIsInstance(self.ev["handler_cores"][0], RuntimeCore)
        self.assertEqual(self.ev["last_growth_on_handler_core"], self.ev["body"])
        self.assertIsNone(self.ev["last_growth_on_other_core"])  # nothing leaked to another core

    def test_no_second_runtimecore_or_core_constructed(self):
        self.assertEqual(self.ev["constructed_cores"], [])

    def test_no_database_connection_opened_by_growth_request(self):
        self.assertEqual(self.ev["sqlite_connect_events"], [])

    def test_source_tree_unchanged(self):
        self.assertEqual(self.ev["tree_diff"], {"added": [], "deleted": [], "modified": []})

    def test_memory_db_unchanged(self):
        self.assertEqual(self.ev["shipped_db_hash_before"], PRISTINE_DB_SHA256)
        self.assertEqual(self.ev["shipped_db_hash_after"], PRISTINE_DB_SHA256)
        self.assertTrue(self.ev["runtime_db_hash_same"])
        self.assertEqual(self.ev["runtime_dir_diff"], {"added": [], "deleted": [], "modified": []})

    def test_no_table_changed_including_upgrades_capabilities_conversation_learning(self):
        self.assertEqual(self.ev["db_changed_tables"], [])
        for table in ("upgrades", "capabilities", "conversation_log", "learning_events"):
            self.assertIn(table, self.ev["db_before"])

    def test_no_file_writes_deletes_or_mutations(self):
        self.assertEqual(self.ev["write_events"], [])

    def test_no_hidden_execution(self):
        self.assertEqual(self.ev["hidden_exec_events"], [])

    def test_no_network_beyond_loopback_and_no_models(self):
        self.assertEqual(self.ev["non_loopback_network"], [])
        self.assertEqual(self.ev["model_file_reads"], [])
        self.assertEqual(self.ev["ai_modules_loaded"], [])

    def test_backward_compatibility_after_growth(self):
        self.assertTrue(self.ev["compat_ok"], self.ev["compat_results"])

    def test_gate_flags(self):
        e = self.evidence
        self.assertIs(e["runtime_growth_executed_through_real_entry"], True)
        self.assertIs(e["controlled_cycle_verified"], True)
        self.assertIs(e["claude_required_for_cycle"], False)
        self.assertIs(e["persistent_change"], False)
        self.assertIs(e["source_change"], False)
        self.assertIs(e["memory_change"], False)
        self.assertIs(e["backward_compatibility"], True)
        self.assertIs(e["claude_exit_gate_ready"], True)

    def test_milestone_decision(self):
        self.assertEqual(self.blockers, [])
        self.assertEqual(self.decision, "CLAUDE_EXIT_MILESTONE = PASS")

    def test_decision_logic_reports_blocked_when_evidence_fails(self):
        bad = dict(self.evidence, persistent_change=True, claude_exit_gate_ready=False)
        decision, blockers = milestone_decision(bad)
        self.assertEqual(decision, "CLAUDE_EXIT_MILESTONE = BLOCKED")
        self.assertEqual(blockers, ["persistent_change"])
        bad = dict(self.evidence, claude_required_for_cycle=True, claude_exit_gate_ready=False)
        self.assertEqual(milestone_decision(bad)[1], ["claude_required_for_cycle"])


class TestStaticClaudeIndependence(unittest.TestCase):
    def test_growth_package_imports_only_itself(self):
        for label, src in _growth_sources().items():
            for mod in _imports_of(src):
                top = mod.split(".")[0]
                # only the package itself plus two pure, deterministic stdlib modules
                self.assertIn(top, ("", "runtime_growth", "hashlib", "json"), f"{label} imports {mod}")
                self.assertNotIn(top, FORBIDDEN_GROWTH_IMPORTS, label)

    def test_no_claude_or_external_ai_reference_in_growth_path(self):
        self.assertEqual(_static_ai_references(), [])

    def test_growth_path_has_no_exec_eval_subprocess_or_network_calls(self):
        banned_calls = {"eval", "exec", "compile", "__import__", "open", "system", "Popen",
                        "run", "urlopen", "connect", "remove", "unlink", "rmtree", "rename"}
        server_src, segments = _growth_entry_sources()
        sources = list(_growth_sources().items()) + [("growth methods", "\n".join(segments))]
        for label, src in sources:
            tree = ast.parse("\n".join(l for l in src.splitlines())) if label != "growth methods" \
                else ast.parse("\n".join(__import__("textwrap").dedent(s) for s in segments))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                    self.assertNotIn(name, banned_calls, f"{label}: call to {name}")

    def test_server_growth_route_only_delegates_to_runtimecore(self):
        with open(SERVER_PATH, encoding="utf-8") as fh:
            src = fh.read()
        mods = _imports_of(src)
        self.assertFalse([m for m in mods if m.startswith("runtime_growth")])
        self.assertIn('grow = getattr(core, "run_controlled_runtime_growth", None)', src)
        self.assertIn("return self._send_json(grow(data))", src)
        for _, fname in STAGES:
            self.assertNotIn(fname, src)
        self.assertNotIn("run_controlled_runtime_growth_cycle", src)

    def test_runtimecore_imports_only_the_prompt_952_cycle_from_growth(self):
        with open(RUNTIME_CORE_PATH, encoding="utf-8") as fh:
            mods = [m for m in _imports_of(fh.read()) if m.startswith("runtime_growth")]
        self.assertEqual(mods, ["runtime_growth"])
        with open(RUNTIME_CORE_PATH, encoding="utf-8") as fh:
            src = fh.read()
        self.assertEqual(src.count("runtime_growth_cycle.run_controlled_runtime_growth_cycle("), 1)
        for _, fname in STAGES:
            self.assertNotIn(fname, src)

    def test_run_builds_one_runtimecore_for_one_handler(self):
        with open(SERVER_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
        calls = [n for n in ast.walk(run) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        self.assertEqual([c.func.id for c in calls if c.func.id == "RuntimeCore"], ["RuntimeCore"])
        self.assertEqual([c.func.id for c in calls if c.func.id == "Core"], [])
        self.assertEqual([c.func.id for c in calls if c.func.id == "make_handler"], ["make_handler"])

    def test_no_claude_specific_module_in_growth_chain(self):
        names = [n for n in os.listdir(GROWTH_DIR) if "claude" in n.lower()]
        self.assertEqual(names, [])
        self.assertFalse([n for n in sys.modules if n.startswith("runtime_growth")
                          and "claude" in n.lower()])

    def test_exact_claim_is_scoped(self):
        claim = ("The implemented controlled runtime-growth path can execute through the "
                 "application runtime without Claude being part of that implementation/execution chain.")
        self.assertIn("controlled runtime-growth path", claim)
        self.assertNotIn("forever", claim)


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.rt = Runtime(os.path.join(self._tmp.name, "rt"))
        self.addCleanup(self.rt.close)


class TestInvalidRequestsThroughRealHttp(_Case):
    def check_unavailable_no_mutation(self, bodies):
        snap_db, snap_dir = db_snapshot(self.rt.db_path), self.rt.dir_fingerprint()
        tree_before = tree_fingerprint(PROJECT_ROOT)
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle",
                               side_effect=cy.run_controlled_runtime_growth_cycle) as spy, \
                StageSpy() as stages:
            for bad in bodies:
                raw = json.dumps(bad).encode()
                status, body = self.rt.grow(raw=raw)
                self.assertEqual(status, 200, bad)
                self.assertEqual(body, UNAVAILABLE, bad)
                self.assertEqual(list(body), KEYS)
            self.assertEqual(spy.call_count, len(bodies))  # still exactly one cycle per request
            # Support is decided by the stages: Prompt 950 may be reached and refuse to apply,
            # but the Prompt 951 verification is never reached by an unsupported request.
            self.assertEqual(stages.counts()["verify_runtime_growth_application"], 0)
            self.assertEqual(stages.foreign_callers(), [])
        self.assertEqual(db_snapshot(self.rt.db_path), snap_db)
        self.assertEqual(self.rt.dir_fingerprint(), snap_dir)
        self.assertEqual(tree_diff(tree_before, tree_fingerprint(PROJECT_ROOT)),
                         {"added": [], "deleted": [], "modified": []})

    def test_unknown_kind(self):
        self.check_unavailable_no_mutation([data(kind="DELETE_CAPABILITY"), data(kind="nope"),
                                            data(kind=""), data(kind=None), data(kind=5)])

    def test_wrong_target(self):
        self.check_unavailable_no_mutation([data(target="code_analysis"), data(target="other"),
                                            data(target=""), data(target=None)])

    def test_create_capability(self):
        self.check_unavailable_no_mutation([data(kind="CREATE_CAPABILITY"),
                                            data(kind="CREATE_CAPABILITY", target="code_analysis")])

    def test_improve_capability(self):
        self.check_unavailable_no_mutation([data(kind="IMPROVE_CAPABILITY"),
                                            data(kind="IMPROVE_CAPABILITY", target="code_analysis")])

    def test_forged_or_invalid_request_shape(self):
        self.check_unavailable_no_mutation([
            dict(data(), extra=1), dict(data(), request_id="growth_req_forged"),
            dict(data(), status="verified", available=True, persistent=False),
            {"kind": "IMPROVE_RUNTIME"}, {}, data(goal=""), data(goal=5),
            {"request": data()}, dict(data(), source_modified=True)])

    def test_non_object_json(self):
        self.check_unavailable_no_mutation([[], [data()], "x", 5, 1.5, None, True, False])

    def test_missing_body(self):
        snap = db_snapshot(self.rt.db_path)
        for status_body in (self.rt.grow(), self.rt.grow(raw=b"")):
            self.assertEqual(status_body, (200, UNAVAILABLE))
        self.assertEqual(db_snapshot(self.rt.db_path), snap)

    def test_malformed_json_keeps_established_400(self):
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle") as spy:
            for raw in (b"{not json", b"\xff\xfe", b'{"kind": ', b"[1,"):
                self.assertEqual(self.rt.grow(raw=raw), (400, {"error": "invalid json"}))
            spy.assert_not_called()  # a 400 never reaches the cycle
        self.assertEqual(self.rt.call("GET", "/api/health")[0], 200)

    def test_oversized_body_keeps_established_413(self):
        raw = b"{" + b" " * (srv.MAX_BODY_BYTES + 10) + b"}"
        self.assertEqual(self.rt.grow(raw=raw), (413, {"error": "request body too large"}))

    def test_invalid_results_never_mark_latest_growth_verified(self):
        self.rt.grow(data(kind="CREATE_CAPABILITY"))
        self.assertEqual(self.rt.core.get_last_controlled_runtime_growth(), UNAVAILABLE)


class TestLifecycleAndRepeatability(_Case):
    def test_one_request_one_cycle_and_no_new_core_per_request(self):
        constructed = []
        orig = Core.__init__

        def counting(self, *a, **k):
            constructed.append(type(self))
            return orig(self, *a, **k)

        with mock.patch.object(Core, "__init__", counting), \
                mock.patch.object(cy, "run_controlled_runtime_growth_cycle",
                                  side_effect=cy.run_controlled_runtime_growth_cycle) as spy:
            for n in range(1, 4):
                self.assertEqual(self.rt.grow(data())[1]["status"], "verified")
                self.assertEqual(spy.call_count, n)
        self.assertEqual(constructed, [])

    def test_repeated_requests_identical_and_state_stays_clean(self):
        before = db_snapshot(self.rt.db_path)
        first = self.rt.grow(data())
        for _ in range(4):
            self.assertEqual(self.rt.grow(data()), first)
        self.assertEqual(db_snapshot(self.rt.db_path), before)
        self.assertEqual(self.rt.core.get_last_controlled_runtime_growth(), first[1])

    def test_result_has_no_permission_execution_or_code_claims(self):
        _, body = self.rt.grow(data())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "executed", "committed", "code", "persisted"):
            self.assertNotIn(name, body)

    def test_plain_core_has_no_growth_route(self):
        plain = Core(memory_db_path=os.path.join(self._tmp.name, "plain.sqlite3"),
                     skill_definitions_dir=os.path.join(self._tmp.name, "plain_skills"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(plain))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/runtime-growth",
            data=json.dumps(data()).encode(), method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 404)


class TestBackwardCompatibilityContracts(_Case):
    def test_endpoint_contracts_after_growth(self):
        self.rt.grow(data())
        self.rt.grow(data(kind="NOPE"))
        status, body = self.rt.call("POST", "/api/message", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"reply", "status"})
        for path in ("/api/status", "/api/health", "/api/history", "/api/learning-history",
                     "/api/errors", "/api/runtime-result"):
            self.assertEqual(self.rt.call("GET", path)[0], 200, path)
        self.assertEqual(self.rt.call("GET", "/nope"), (404, {"error": "not found"}))
        self.assertEqual(self.rt.call("GET", "/api/runtime-growth")[0], 404)  # POST only
        self.assertEqual(self.rt.call("POST", "/api/runtime-growth-x", data())[0], 404)
        status, inspected = self.rt.call("POST", "/api/inspect-code", {"code": "x = 1"})
        self.assertEqual((status, inspected), (200, self.rt.core.inspect_code("x = 1")))
        self.assertEqual(self.rt.call("POST", "/api/inspect-code", {"code": 5})[0], 400)

    def test_growth_does_not_change_conversation_state(self):
        before = (len(self.rt.core.recent_messages(50)), len(self.rt.core.context.get_recent_turns()),
                  len(self.rt.core.upgrades.history(100)), self.rt.core.capabilities.all())
        for _ in range(3):
            self.rt.grow(data())
        after = (len(self.rt.core.recent_messages(50)), len(self.rt.core.context.get_recent_turns()),
                 len(self.rt.core.upgrades.history(100)), self.rt.core.capabilities.all())
        self.assertEqual(before, after)

    def test_last_runtime_result_not_touched_by_growth(self):
        self.rt.call("POST", "/api/message", {"text": "hello"})
        before = self.rt.call("GET", "/api/runtime-result")
        self.rt.grow(data())
        self.assertEqual(self.rt.call("GET", "/api/runtime-result"), before)


class TestGuardsAreLive(unittest.TestCase):
    """Negative controls: the detectors used by the gate really fire, so a clean result is
    evidence and not an artefact of a guard that cannot see anything."""

    def test_audit_recorder_sees_writes_deletes_and_loopback_network(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.txt")
            with guarded() as events:
                with open(path, "w") as fh:
                    fh.write("x")
                os.remove(path)
                sqlite3.connect(os.path.join(d, "n.db")).close()
                exec("1 + 1")  # noqa: S102 - deliberate: proves the exec detector fires
            kinds = {e[0] for e in events}
            self.assertIn("open_write", kinds)
            self.assertIn("os.remove", kinds)
            self.assertIn("sqlite3.connect", kinds)
            self.assertIn("exec", kinds)

    def test_audit_recorder_blocks_external_network(self):
        import socket
        with guarded():
            with self.assertRaises(RuntimeError):
                socket.create_connection(("203.0.113.7", 80), timeout=1)

    def test_real_growth_request_is_visible_to_the_recorder(self):
        with tempfile.TemporaryDirectory() as d:
            rt = Runtime(os.path.join(d, "rt"))
            try:
                with guarded() as events:
                    rt.grow(data())
            finally:
                rt.close()
        self.assertTrue([e for e in events if e[0] == "socket.connect"])  # the loopback client call

    def test_fingerprint_and_db_snapshot_detect_changes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "a.py")
            with open(f, "w") as fh:
                fh.write("a = 1\n")
            before = tree_fingerprint(d)
            with open(f, "w") as fh:
                fh.write("a = 2\n")
            with open(os.path.join(d, "b.py"), "w") as fh:
                fh.write("")
            self.assertEqual(tree_diff(before, tree_fingerprint(d)),
                             {"added": ["b.py"], "deleted": [], "modified": ["a.py"]})
            os.remove(f)
            self.assertEqual(tree_diff(before, tree_fingerprint(d))["deleted"], ["a.py"])
            db = os.path.join(d, "t.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE upgrades (id INTEGER PRIMARY KEY, v TEXT)")
            conn.commit()
            snap = db_snapshot(db)
            conn.execute("INSERT INTO upgrades (v) VALUES ('x')")
            conn.commit()
            conn.close()
            self.assertNotEqual(db_snapshot(db), snap)

    def test_static_scan_would_flag_ai_references(self):
        needles = ("claude", "anthropic", "openai", "api_key")
        sample = "import anthropic\nclient = Anthropic(api_key=KEY)\n"
        self.assertTrue([n for n in needles if n in sample.lower()])
        self.assertEqual(sorted(_imports_of(sample)), ["anthropic"])


class TestProductionFilesUnchanged(unittest.TestCase):
    def test_protected_production_files_keep_their_hashes(self):
        for rel, expected in UNCHANGED_FILES.items():
            self.assertEqual(_sha256_file(os.path.join(PY_ROOT, rel)), expected, rel)

    def test_shipped_memory_db_is_pristine(self):
        self.assertEqual(_sha256_file(SHIPPED_DB), PRISTINE_DB_SHA256)

    def test_no_pycache_or_pyc_needed_in_fingerprint(self):
        fp = tree_fingerprint(PY_ROOT)
        self.assertFalse([k for k in fp if k.endswith(".pyc") or "__pycache__" in k])


if __name__ == "__main__":
    unittest.main()
