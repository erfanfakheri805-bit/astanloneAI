"""
Tests for Prompt 947 - Runtime Growth Application Contract.

Run directly:
    python -m unittest tests.test_runtime_growth_application_contract_prompt947 -v
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
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = ac.build_runtime_growth_application_contract
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_contract.py")
KEYS = ["version", "available", "status", "request_id", "proposal_type", "target", "goal",
        "change_scope", "application_mode", "execution_allowed"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "proposal_type": None, "target": None, "goal": None, "change_scope": None,
               "application_mode": None, "execution_allowed": False}
SCOPES = {"capability_creation": "capability_definition_and_implementation_design",
          "capability_improvement": "existing_capability_improvement_design",
          "runtime_improvement": "bounded_runtime_change_design"}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")


def app_request(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    p = rgp.build_runtime_growth_plan(req, v, a)
    prop = rgq.build_runtime_growth_proposal(req, v, a, p)
    pvld = pv.validate_runtime_growth_proposal(prop)
    b = ab.evaluate_runtime_growth_application_boundary(prop, pvld)
    out = ar.build_runtime_growth_application_request(prop, pvld, b)
    out.update(over)
    return out


class TestContracted(unittest.TestCase):
    def test_all_proposal_types(self):
        seen = set()
        for kind in KINDS:
            r = app_request(kind)
            out = build(r)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "contracted",
                                   "request_id": r["request_id"],
                                   "proposal_type": r["proposal_type"], "target": r["target"],
                                   "goal": r["goal"], "change_scope": r["change_scope"],
                                   "application_mode": "controlled",
                                   "execution_allowed": False})
            self.assertEqual(out["change_scope"], SCOPES[out["proposal_type"]])
            seen.add(out["proposal_type"])
        self.assertEqual(seen, set(SCOPES))

    def test_contract_is_not_permission(self):
        out = build(app_request())
        self.assertIs(out["execution_allowed"], False)
        for name in ("approved", "approval", "authorization", "execute", "applied", "code",
                     "permission", "descriptive_only"):
            self.assertNotIn(name, out)

    def test_unavailable_has_same_keys(self):
        self.assertEqual(list(build(None)), KEYS)


class TestRejected(unittest.TestCase):
    def rejected(self, r):
        out = build(r)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_invalid_request(self):
        self.rejected(ar.build_runtime_growth_application_request(None, None, None))
        self.rejected(rgr.create_runtime_growth_request({}))

    def test_malformed_request(self):
        r = app_request()
        for bad in (list(r.items()), tuple(r), str(r), {"a": 1}, {}):
            self.rejected(bad)

    def test_forged_request_id(self):
        for bad in ("", None, 5, ["x"], b"x"):
            self.rejected(app_request(request_id=bad))

    def test_wrong_version(self):
        for bad in ("2", 1, None, ""):
            self.rejected(app_request(version=bad))

    def test_wrong_available_flag(self):
        for bad in (False, 1, "True", None):
            self.rejected(app_request(available=bad))

    def test_wrong_status(self):
        for bad in ("unavailable", "contracted", "", None, 1):
            self.rejected(app_request(status=bad))

    def test_invalid_proposal_type(self):
        for bad in ("other", "", None, 5, ["capability_creation"]):
            self.rejected(app_request(proposal_type=bad))

    def test_invalid_target_and_goal(self):
        for name in ("target", "goal"):
            for bad in (None, 5, ["x"], {"a": 1}):
                self.rejected(app_request(**{name: bad}))

    def test_invalid_change_scope(self):
        for bad in ("other", "", None, 5):
            self.rejected(app_request(change_scope=bad))

    def test_mismatched_type_and_scope(self):
        for kind in KINDS:
            ptype = app_request(kind)["proposal_type"]
            for other_type, other_scope in SCOPES.items():
                r = app_request(kind, change_scope=other_scope)
                self.assertEqual(build(r)["available"], other_type == ptype)

    def test_wrong_application_mode(self):
        for bad in ("uncontrolled", "", None, 5, "Controlled"):
            self.rejected(app_request(application_mode=bad))

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 0, "False", None):
            self.rejected(app_request(execution_allowed=bad))

    def test_extra_fields(self):
        self.rejected(dict(app_request(), extra=1))
        self.rejected(dict(app_request(), descriptive_only=True))

    def test_missing_fields(self):
        for name in KEYS:
            r = app_request()
            del r[name]
            self.rejected(r)
        self.rejected({})

    def test_unavailable_input(self):
        for bad in (None, "x", 5, [], (), True, object()):
            self.rejected(bad)
        self.rejected(ar.build_runtime_growth_application_request(None, None, None))

    def test_no_untrusted_data_leaks(self):
        out = build(app_request(goal="secret", version="2"))
        self.assertEqual(out, UNAVAILABLE)
        self.assertNotIn("secret", repr(out))

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def keys(self):
                raise RuntimeError("boom")

        self.rejected(Boom(app_request()))


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in KINDS:
            r = app_request(kind)
            first = build(r)
            for _ in range(5):
                self.assertEqual(build(r), first)
            self.assertEqual(build(app_request(kind)), first)

    def test_no_input_mutation(self):
        for r in (app_request(), app_request(version="x"), {"a": 1}):
            before = copy.deepcopy(r)
            build(r)
            self.assertEqual(r, before)

    def test_output_isolation(self):
        r = app_request()
        out = build(r)
        out["status"] = "tampered"
        out["execution_allowed"] = True
        out["goal"] = "tampered"
        again = build(r)
        self.assertEqual(again["status"], "contracted")
        self.assertIs(again["execution_allowed"], False)
        self.assertEqual(again["goal"], r["goal"])
        self.assertNotEqual(r["goal"], "tampered")
        u1, u2 = build(None), build(None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_execution_or_io(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        r = app_request("CREATE_CAPABILITY")
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
            build(r)
            build(None)
            build(dict(r, goal=callable_trap))
        callable_trap.assert_not_called()
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
