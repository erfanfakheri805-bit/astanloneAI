"""
Tests for Prompt 953 - RuntimeCore Controlled Growth Integration.

Run directly:
    python -m unittest tests.test_runtime_growth_runtimecore_integration_prompt953 -v
"""

import ast
import copy
import hashlib
import os
import random  # noqa: F401 - imported up front so patching never triggers a lazy import
import socket  # noqa: F401
import sqlite3  # noqa: F401
import subprocess  # noqa: F401
import sys
import tempfile
import time  # noqa: F401
import unittest
import uuid  # noqa: F401
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_growth import runtime_growth_application_verification as av
from runtime_growth import runtime_growth_controlled_application as ca
from runtime_growth import runtime_growth_cycle as cy
from runtime_integration.runtime_core import RuntimeCore

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(PY_ROOT, "runtime_integration", "runtime_core.py")
UNAVAILABLE = cy._unavailable_cycle()
VERIFIED_KEYS = ["version", "available", "status", "request_id", "request_status",
                 "plan_status", "proposal_status", "boundary_status",
                 "application_request_status", "contract_status", "transaction_status",
                 "application_status", "verification_status", "application_verified",
                 "persistent", "source_modified"]
TURNS = ("hello", "من عرفان هستم", "What is Python?", "", "TEACH sun IS a star", "ASK sun",
         "create a plan to learn python", "UPGRADE demo IS a demo")


def data(**over):
    d = {"kind": "IMPROVE_RUNTIME", "goal": "Grow the runtime safely",
         "target": "runtime_growth", "reason": "Controlled growth", "source": "runtime"}
    d.update(over)
    return d


class RuntimeCoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def new_core(self, cls=RuntimeCore, name="core"):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return cls(memory_db_path=os.path.join(base, "m.sqlite3"),
                   skill_definitions_dir=os.path.join(base, "skills"))


class TestExposure(RuntimeCoreCase):
    def test_methods_exposed(self):
        self.assertTrue(callable(getattr(RuntimeCore, "run_controlled_runtime_growth", None)))
        self.assertTrue(callable(getattr(RuntimeCore, "get_last_controlled_runtime_growth", None)))
        self.assertFalse(hasattr(Core, "run_controlled_runtime_growth"))
        self.assertFalse(hasattr(Core, "get_last_controlled_runtime_growth"))

    def test_none_before_first_call(self):
        core = self.new_core()
        self.assertIsNone(core.get_last_controlled_runtime_growth())
        core.process_input("hello")
        self.assertIsNone(core.get_last_controlled_runtime_growth())


class TestValidRequest(RuntimeCoreCase):
    def test_reaches_prompt_952_exactly_once(self):
        core = self.new_core()
        real = cy.run_controlled_runtime_growth_cycle
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle",
                               side_effect=real) as spy:
            out = core.run_controlled_runtime_growth(data())
        spy.assert_called_once_with(data())
        self.assertEqual(out, real(data()))

    def test_valid_result_preserved_exactly(self):
        out = self.new_core().run_controlled_runtime_growth(data())
        self.assertEqual(out, cy.run_controlled_runtime_growth_cycle(data()))
        self.assertEqual(list(out), VERIFIED_KEYS)
        self.assertEqual(out["status"], "verified")
        self.assertIs(out["available"], True)
        self.assertIs(out["application_verified"], True)
        self.assertIs(out["persistent"], False)
        self.assertIs(out["source_modified"], False)

    def test_no_permission_claims(self):
        out = self.new_core().run_controlled_runtime_growth(data())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "executed", "committed", "code"):
            self.assertNotIn(name, out)

    def test_accessor_returns_latest(self):
        core = self.new_core()
        first = core.run_controlled_runtime_growth(data())
        self.assertEqual(core.get_last_controlled_runtime_growth(), first)
        second = core.run_controlled_runtime_growth(data(kind="CREATE_CAPABILITY"))
        self.assertEqual(second, UNAVAILABLE)
        self.assertEqual(core.get_last_controlled_runtime_growth(), UNAVAILABLE)
        third = core.run_controlled_runtime_growth(data(goal="Another goal"))
        self.assertEqual(core.get_last_controlled_runtime_growth(), third)
        self.assertNotEqual(third["request_id"], first["request_id"])

    def test_accessor_returns_independent_copy(self):
        core = self.new_core()
        core.run_controlled_runtime_growth(data())
        a, b = core.get_last_controlled_runtime_growth(), core.get_last_controlled_runtime_growth()
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        a["status"] = "tampered"
        a["persistent"] = True
        self.assertEqual(core.get_last_controlled_runtime_growth()["status"], "verified")
        self.assertIs(core.get_last_controlled_runtime_growth()["persistent"], False)

    def test_returned_result_mutation_does_not_alter_stored_or_cycle_result(self):
        core = self.new_core()
        out = core.run_controlled_runtime_growth(data())
        out["status"] = "tampered"
        out["source_modified"] = True
        out["application_verified"] = False
        stored = core.get_last_controlled_runtime_growth()
        self.assertEqual(stored["status"], "verified")
        self.assertIs(stored["source_modified"], False)
        self.assertIs(stored["application_verified"], True)
        # the Prompt 952 function is unaffected: a fresh call is still pristine
        self.assertEqual(cy.run_controlled_runtime_growth_cycle(data()), stored)

    def test_stored_object_is_not_the_cycle_object(self):
        core = self.new_core()
        shared = cy.run_controlled_runtime_growth_cycle(data())
        with mock.patch.object(cy, "run_controlled_runtime_growth_cycle", return_value=shared):
            out = core.run_controlled_runtime_growth(data())
        self.assertIsNot(out, shared)
        shared["status"] = "tampered"  # mutating the cycle's own object
        self.assertEqual(core.get_last_controlled_runtime_growth()["status"], "verified")
        self.assertEqual(out["status"], "verified")

    def test_repeated_valid_calls_deterministic(self):
        core, other = self.new_core(name="a"), self.new_core(name="b")
        first = core.run_controlled_runtime_growth(data())
        for _ in range(5):
            self.assertEqual(core.run_controlled_runtime_growth(data()), first)
        self.assertEqual(other.run_controlled_runtime_growth(data()), first)
        self.assertEqual(core.get_last_controlled_runtime_growth(), first)

    def test_input_not_mutated(self):
        d = data()
        before = copy.deepcopy(d)
        self.new_core().run_controlled_runtime_growth(d)
        self.assertEqual(d, before)


class TestInvalidRequest(RuntimeCoreCase):
    def test_exact_prompt_952_unavailable_result(self):
        core = self.new_core()
        for bad in (None, 5, "x", [], {}, data(kind="CREATE_CAPABILITY"),
                    data(kind="IMPROVE_CAPABILITY"), data(target="other"),
                    dict(data(), request_id="growth_req_forged"), dict(data(), extra=1)):
            out = core.run_controlled_runtime_growth(bad)
            self.assertEqual(out, UNAVAILABLE)
            self.assertEqual(out, cy.run_controlled_runtime_growth_cycle(bad))
            self.assertEqual(list(out), VERIFIED_KEYS)
            self.assertEqual(core.get_last_controlled_runtime_growth(), UNAVAILABLE)

    def test_invalid_request_does_not_reach_application_behavior(self):
        core = self.new_core()
        with mock.patch.object(ca, "apply_runtime_growth_transaction") as apply_mock, \
                mock.patch.object(av, "verify_runtime_growth_application") as verify_mock:
            for bad in (None, {}, {"kind": "NOPE"}, dict(data(), extra=1)):
                self.assertEqual(core.run_controlled_runtime_growth(bad), UNAVAILABLE)
        apply_mock.assert_not_called()
        verify_mock.assert_not_called()

    def test_unavailable_result_is_independent(self):
        core = self.new_core()
        out = core.run_controlled_runtime_growth(None)
        out["status"] = "verified"
        out["application_verified"] = True
        self.assertEqual(core.get_last_controlled_runtime_growth(), UNAVAILABLE)
        self.assertEqual(core.run_controlled_runtime_growth(None), UNAVAILABLE)


class TestSoleOrchestrator(unittest.TestCase):
    def test_runtimecore_references_only_the_prompt_952_cycle(self):
        with open(CORE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        growth_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("runtime_growth"):
                growth_imports.append((node.module, tuple(a.name for a in node.names)))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name.startswith("runtime_growth"), a.name)
        self.assertEqual(growth_imports, [("runtime_growth", ("runtime_growth_cycle",))])

    def test_runtimecore_never_names_individual_stages(self):
        with open(CORE_PATH, encoding="utf-8") as handle:
            source = handle.read()
        for stage in ("create_runtime_growth_request", "validate_runtime_growth_request",
                      "analyze_runtime_growth_request", "build_runtime_growth_plan",
                      "build_runtime_growth_proposal", "validate_runtime_growth_proposal",
                      "evaluate_runtime_growth_application_boundary",
                      "build_runtime_growth_application_request",
                      "build_runtime_growth_application_contract",
                      "build_runtime_growth_application_result",
                      "build_runtime_growth_application_transaction",
                      "apply_runtime_growth_transaction", "verify_runtime_growth_application",
                      "runtime_growth_request", "runtime_growth_analysis",
                      "runtime_growth_plan", "runtime_growth_proposal",
                      "runtime_growth_application", "runtime_growth_controlled"):
            self.assertNotIn(stage, source, stage)
        self.assertEqual(source.count("runtime_growth_cycle.run_controlled_runtime_growth_cycle("), 1)

    def test_stub_cycle_result_is_what_runtimecore_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = RuntimeCore(memory_db_path=os.path.join(tmp, "m.sqlite3"),
                               skill_definitions_dir=os.path.join(tmp, "skills"))
            stub = {"sentinel": [1, 2]}
            with mock.patch.object(cy, "run_controlled_runtime_growth_cycle", return_value=stub):
                out = core.run_controlled_runtime_growth(data())
            self.assertEqual(out, stub)
            self.assertIsNot(out, stub)
            self.assertIsNot(out["sentinel"], stub["sentinel"])
            self.assertEqual(core.get_last_controlled_runtime_growth(), stub)


class TestBackwardCompatible(RuntimeCoreCase):
    def test_replies_unchanged_by_growth_calls(self):
        plain, runtime = self.new_core(Core, "plain"), self.new_core(RuntimeCore, "rt")
        for text in TURNS:
            runtime.run_controlled_runtime_growth(data())
            self.assertEqual(runtime.process_input(text), plain.process_input(text), text)

    def test_existing_runtime_state_unaffected(self):
        a, b = self.new_core(name="a"), self.new_core(name="b")
        getters = ("get_last_runtime_result", "get_last_reasoning_consumption_result",
                   "get_last_reasoning_decision_candidate",
                   "get_last_reasoning_decision_validation",
                   "get_last_reasoning_decision_eligibility",
                   "get_last_controlled_reasoning_checkpoint",
                   "get_last_controlled_reasoning_snapshot",
                   "get_last_controlled_reasoning_runtime_ready",
                   "get_last_final_runtime_integration_checkpoint",
                   "get_last_final_runtime_integration_boundary_validation",
                   "get_last_final_runtime_assessment", "get_last_runtime_observation",
                   "get_last_reasoning_handoff")
        for text in TURNS:
            a.run_controlled_runtime_growth(data())
            a.run_controlled_runtime_growth(None)
            a.process_input(text)
            b.process_input(text)
            for getter in getters:
                self.assertEqual(getattr(a, getter)(), getattr(b, getter)(), (text, getter))
            self.assertEqual(a.last_runtime_result, b.last_runtime_result)
        self.assertEqual(a.get_last_controlled_runtime_growth(), UNAVAILABLE)
        self.assertIsNone(b.get_last_controlled_runtime_growth())

    def test_only_dedicated_field_added(self):
        core = self.new_core()
        core.process_input("hello")
        before = {k: v for k, v in vars(core).items() if k != "_last_controlled_runtime_growth"}
        core.run_controlled_runtime_growth(data())
        core.get_last_controlled_runtime_growth()
        after = {k: v for k, v in vars(core).items() if k != "_last_controlled_runtime_growth"}
        self.assertEqual(set(before), set(after))
        for key in before:  # every other attribute is the very same, untouched object
            self.assertIs(before[key], after[key], key)
        self.assertEqual(set(vars(core)) - set(after), {"_last_controlled_runtime_growth"})
        self.assertEqual(core.get_last_runtime_observation(),
                         {"final_runtime_assessment": core.get_last_final_runtime_assessment()})

    def test_growth_result_not_changed_by_turns(self):
        core = self.new_core()
        out = core.run_controlled_runtime_growth(data())
        for text in TURNS:
            core.process_input(text)
            self.assertEqual(core.get_last_controlled_runtime_growth(), out)

    def test_growth_call_executes_nothing_in_core(self):
        core = self.new_core()
        boom = AssertionError("growth must not run this")
        before = (len(core.upgrades.history(100)), core.capabilities.all(),
                  len(core.context.get_recent_turns()))
        with mock.patch.object(core.ael, "run", side_effect=boom), \
                mock.patch.object(core.upgrades, "propose_upgrade", side_effect=boom), \
                mock.patch.object(core.learning, "teach", side_effect=boom), \
                mock.patch.object(core.learning, "relate", side_effect=boom), \
                mock.patch.object(core.capabilities, "set_enabled", side_effect=boom):
            for _ in range(3):
                core.run_controlled_runtime_growth(data())
                core.run_controlled_runtime_growth(data(kind="CREATE_CAPABILITY"))
        self.assertEqual(before, (len(core.upgrades.history(100)), core.capabilities.all(),
                                  len(core.context.get_recent_turns())))

    def test_core_android_ael_files_do_not_reference_growth(self):
        for rel in ("core/core.py", "runtime_integration/bridge.py", "ael/interpreter.py",
                    "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


class TestPurity(RuntimeCoreCase):
    def test_no_filesystem_database_network_subprocess_or_code_execution(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        core = self.new_core()
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
        with mock.patch("sqlite3.connect", side_effect=trap), \
                mock.patch("socket.socket", side_effect=trap), \
                mock.patch("subprocess.Popen", side_effect=trap), \
                mock.patch("os.system", side_effect=trap), \
                mock.patch("os.remove", side_effect=trap), \
                mock.patch("os.rename", side_effect=trap), \
                mock.patch("os.mkdir", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap), \
                mock.patch("time.time", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap), \
                mock.patch("builtins.open", side_effect=trap):
            out = core.run_controlled_runtime_growth(data())
            core.run_controlled_runtime_growth(None)
            core.get_last_controlled_runtime_growth()
        self.assertEqual(out["status"], "verified")
        self.assertEqual(state(), before)  # whole project tree incl. memory.db
        with open(db_path, "rb") as h:
            self.assertEqual(hashlib.sha256(h.read()).hexdigest(), db_before)

    def test_added_methods_use_no_forbidden_calls(self):
        with open(CORE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        methods = [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body
                   if isinstance(n, ast.FunctionDef)
                   and n.name in ("run_controlled_runtime_growth",
                                  "get_last_controlled_runtime_growth")]
        self.assertEqual(len(methods), 2)
        for method in methods:
            for node in ast.walk(method):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
                    self.assertNotIn(name, {"open", "exec", "eval", "compile", "__import__",
                                            "connect", "Popen", "system", "time", "random",
                                            "uuid4", "write", "remove", "mkdir"})


if __name__ == "__main__":
    unittest.main()
