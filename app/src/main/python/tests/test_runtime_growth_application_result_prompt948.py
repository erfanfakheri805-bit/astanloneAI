"""
Tests for Prompt 948 - Runtime Growth Application Result.

Run directly:
    python -m unittest tests.test_runtime_growth_application_result_prompt948 -v
"""

import ast
import copy
import hashlib
import os
import random
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_growth import runtime_growth_analysis as rga
from runtime_growth import runtime_growth_application_boundary as ab
from runtime_growth import runtime_growth_application_contract as ac
from runtime_growth import runtime_growth_application_request as ar
from runtime_growth import runtime_growth_application_result as res
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = res.build_runtime_growth_application_result
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_result.py")
KEYS = ["version", "available", "status", "request_id", "proposal_type", "target",
        "change_scope", "application_mode", "execution_attempted", "applied"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "proposal_type": None, "target": None, "change_scope": None,
               "application_mode": None, "execution_attempted": False, "applied": False}
SCOPES = {"capability_creation": "capability_definition_and_implementation_design",
          "capability_improvement": "existing_capability_improvement_design",
          "runtime_improvement": "bounded_runtime_change_design"}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")


def contract(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    p = rgp.build_runtime_growth_plan(req, v, a)
    prop = rgq.build_runtime_growth_proposal(req, v, a, p)
    pvld = pv.validate_runtime_growth_proposal(prop)
    b = ab.evaluate_runtime_growth_application_boundary(prop, pvld)
    r = ar.build_runtime_growth_application_request(prop, pvld, b)
    out = ac.build_runtime_growth_application_contract(r)
    out.update(over)
    return out


class TestNotApplied(unittest.TestCase):
    def test_all_proposal_types(self):
        seen = set()
        for kind in KINDS:
            c = contract(kind)
            out = build(c)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "not_applied",
                                   "request_id": c["request_id"],
                                   "proposal_type": c["proposal_type"], "target": c["target"],
                                   "change_scope": c["change_scope"],
                                   "application_mode": "controlled",
                                   "execution_attempted": False, "applied": False})
            self.assertEqual(out["change_scope"], SCOPES[out["proposal_type"]])
            self.assertNotIn("goal", out)
            seen.add(out["proposal_type"])
        self.assertEqual(seen, set(SCOPES))

    def test_flags_fixed_false_for_every_valid_input(self):
        for kind in KINDS:
            out = build(contract(kind))
            self.assertIs(out["execution_attempted"], False)
            self.assertIs(out["applied"], False)
            self.assertEqual(out["status"], "not_applied")

    def test_no_permission_or_approval_fields(self):
        out = build(contract())
        for name in ("execution_allowed", "approved", "approval", "authorization", "permission",
                     "code", "descriptive_only"):
            self.assertNotIn(name, out)

    def test_unavailable_has_same_keys(self):
        self.assertEqual(list(build(None)), KEYS)


class TestRejected(unittest.TestCase):
    def rejected(self, c):
        out = build(c)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_invalid_contract(self):
        self.rejected(ac.build_runtime_growth_application_contract(None))
        self.rejected(rgr.create_runtime_growth_request({}))

    def test_a_request_is_not_a_contract(self):
        c = contract()
        self.rejected(dict(c, status="ready"))

    def test_malformed_contract(self):
        c = contract()
        for bad in (list(c.items()), tuple(c), str(c), {"a": 1}, {}):
            self.rejected(bad)

    def test_forged_request_id(self):
        for bad in ("", None, 5, ["x"], b"x"):
            self.rejected(contract(request_id=bad))

    def test_wrong_version(self):
        for bad in ("2", 1, None, ""):
            self.rejected(contract(version=bad))

    def test_wrong_available_flag(self):
        for bad in (False, 1, "True", None):
            self.rejected(contract(available=bad))

    def test_wrong_status(self):
        for bad in ("unavailable", "ready", "not_applied", "", None, 1):
            self.rejected(contract(status=bad))

    def test_invalid_proposal_type(self):
        for bad in ("other", "", None, 5, ["capability_creation"]):
            self.rejected(contract(proposal_type=bad))

    def test_invalid_target_and_goal(self):
        for name in ("target", "goal"):
            for bad in (None, 5, ["x"], {"a": 1}):
                self.rejected(contract(**{name: bad}))

    def test_invalid_change_scope(self):
        for bad in ("other", "", None, 5):
            self.rejected(contract(change_scope=bad))

    def test_mismatched_type_and_scope(self):
        for kind in KINDS:
            ptype = contract(kind)["proposal_type"]
            for other_type, other_scope in SCOPES.items():
                self.assertEqual(build(contract(kind, change_scope=other_scope))["available"],
                                 other_type == ptype)

    def test_wrong_application_mode(self):
        for bad in ("uncontrolled", "", None, 5, "Controlled"):
            self.rejected(contract(application_mode=bad))

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 0, "False", None):
            self.rejected(contract(execution_allowed=bad))

    def test_missing_fields(self):
        for name in ac.FIELDS:
            c = contract()
            del c[name]
            self.rejected(c)
        self.rejected({})

    def test_extra_fields(self):
        self.rejected(dict(contract(), extra=1))
        self.rejected(dict(contract(), applied=False))

    def test_unavailable_input(self):
        for bad in (None, "x", 5, [], (), True, object()):
            self.rejected(bad)

    def test_no_untrusted_data_leaks(self):
        out = build(contract(target="secret", version="2"))
        self.assertEqual(out, UNAVAILABLE)
        self.assertNotIn("secret", repr(out))

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def keys(self):
                raise RuntimeError("boom")

        self.rejected(Boom(contract()))


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in KINDS:
            c = contract(kind)
            first = build(c)
            for _ in range(5):
                self.assertEqual(build(c), first)
            self.assertEqual(build(contract(kind)), first)

    def test_no_input_mutation(self):
        for c in (contract(), contract(version="x"), {"a": 1}):
            before = copy.deepcopy(c)
            build(c)
            self.assertEqual(c, before)

    def test_output_isolation(self):
        c = contract()
        out = build(c)
        out["status"] = "tampered"
        out["applied"] = True
        out["execution_attempted"] = True
        again = build(c)
        self.assertEqual(again["status"], "not_applied")
        self.assertIs(again["applied"], False)
        self.assertIs(again["execution_attempted"], False)
        u1, u2 = build(None), build(None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_application_is_attempted(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        c = contract("CREATE_CAPABILITY")
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
        callable_trap = mock.Mock()
        with mock.patch("sqlite3.connect", side_effect=trap), \
                mock.patch("socket.socket", side_effect=trap), \
                mock.patch("subprocess.Popen", side_effect=trap), \
                mock.patch("os.system", side_effect=trap), \
                mock.patch("os.remove", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap), \
                mock.patch("time.time", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap), \
                mock.patch("builtins.open", side_effect=trap):
            out = build(c)
            build(None)
            build(dict(c, goal=callable_trap))
        callable_trap.assert_not_called()
        self.assertIs(out["execution_attempted"], False)
        self.assertIs(out["applied"], False)
        self.assertEqual(state(), before)

    def test_module_source_is_pure_and_not_wired(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__",
                                                "input", "print", "setattr", "delattr", "getattr"})
        self.assertEqual(imported, {"runtime_growth"})
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
