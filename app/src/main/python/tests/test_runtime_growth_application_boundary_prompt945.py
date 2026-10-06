"""
Tests for Prompt 945 - Runtime Growth Application Boundary.

Run directly:
    python -m unittest tests.test_runtime_growth_application_boundary_prompt945 -v
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
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

evaluate = ab.evaluate_runtime_growth_application_boundary
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_boundary.py")
KEYS = ["version", "available", "status", "eligible", "request_id", "proposal_type",
        "execution_allowed", "descriptive_only"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "eligible": False,
               "request_id": None, "proposal_type": None, "execution_allowed": False,
               "descriptive_only": True}
TYPES = {"CREATE_CAPABILITY": "capability_creation",
         "IMPROVE_CAPABILITY": "capability_improvement",
         "IMPROVE_RUNTIME": "runtime_improvement"}


def pair(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    p = rgp.build_runtime_growth_plan(req, v, a)
    prop = rgq.build_runtime_growth_proposal(req, v, a, p)
    prop.update(over)
    return prop, pv.validate_runtime_growth_proposal(prop)


class TestEligible(unittest.TestCase):
    def test_all_kinds(self):
        for kind, ptype in TYPES.items():
            prop, v = pair(kind)
            out = evaluate(prop, v)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "eligible",
                                   "eligible": True, "request_id": prop["request_id"],
                                   "proposal_type": ptype, "execution_allowed": False,
                                   "descriptive_only": True})

    def test_eligibility_is_not_execution_permission(self):
        for kind in TYPES:
            out = evaluate(*pair(kind))
            self.assertIs(out["eligible"], True)
            self.assertIs(out["execution_allowed"], False)
            self.assertIs(out["descriptive_only"], True)
            for name in ("approved", "approval", "execute", "permission", "applied", "code"):
                self.assertNotIn(name, out)

    def test_unavailable_has_same_keys(self):
        self.assertEqual(list(evaluate(None, None)), KEYS)


class TestRejected(unittest.TestCase):
    def test_invalid_proposal(self):
        prop, v = pair()
        self.assertEqual(evaluate(dict(prop, version="2"), v), UNAVAILABLE)
        bad = dict(prop, goal=5)
        self.assertEqual(evaluate(bad, pv.validate_runtime_growth_proposal(bad)), UNAVAILABLE)
        bad = dict(prop, extra=1)
        self.assertEqual(evaluate(bad, pv.validate_runtime_growth_proposal(bad)), UNAVAILABLE)

    def test_unavailable_proposal(self):
        _, v = pair()
        for bad in (None, "x", 5, [], ()):
            self.assertEqual(evaluate(bad, v), UNAVAILABLE)
        self.assertEqual(evaluate(rgq.build_runtime_growth_proposal(None, None, None, None), v),
                         UNAVAILABLE)

    def test_forged_request_id_does_not_leak(self):
        prop, v = pair()
        out = evaluate(dict(prop, request_id=""), v)
        self.assertEqual(out, UNAVAILABLE)
        forged = dict(prop, request_id="growth_req_forged")
        out = evaluate(forged, {"available": False, "status": "unavailable", "valid": False,
                                "error_count": 0, "errors": []})
        self.assertEqual(out, UNAVAILABLE)
        self.assertIsNone(out["request_id"])

    def test_forged_validation(self):
        prop, v = pair()
        bad_prop = dict(prop, descriptive_only=False)
        forged = dict(OK := {"available": True, "status": "valid", "valid": True,
                             "error_count": 0, "errors": []})
        self.assertEqual(evaluate(bad_prop, forged), UNAVAILABLE)
        for bad in (dict(v, valid=False), dict(v, status="invalid"), dict(v, extra=1),
                    dict(v, error_count=1), {}, None, "x", 5, []):
            self.assertEqual(evaluate(prop, bad), UNAVAILABLE)

    def test_mismatched_validation(self):
        prop, v = pair()
        bad_prop = dict(prop, version="9")
        bad_v = pv.validate_runtime_growth_proposal(bad_prop)
        self.assertEqual(evaluate(prop, bad_v), UNAVAILABLE)
        self.assertEqual(evaluate(bad_prop, v), UNAVAILABLE)
        self.assertEqual(evaluate(bad_prop, bad_v), UNAVAILABLE)

    def test_invalid_proposal_type(self):
        for bad in ("other", "", None, 5):
            prop, v = pair(proposal_type=bad)
            self.assertEqual(evaluate(prop, v), UNAVAILABLE)

    def test_execution_allowed_true_rejected(self):
        prop, v = pair(execution_allowed=True)
        self.assertEqual(evaluate(prop, v), UNAVAILABLE)
        # even a forged "valid" validation cannot rescue it
        forged = {"available": True, "status": "valid", "valid": True, "error_count": 0,
                  "errors": []}
        self.assertEqual(evaluate(prop, forged), UNAVAILABLE)

    def test_descriptive_only_false_rejected(self):
        prop, v = pair(descriptive_only=False)
        self.assertEqual(evaluate(prop, v), UNAVAILABLE)

    def test_scope_mismatch_rejected(self):
        prop, v = pair("CREATE_CAPABILITY", change_scope="bounded_runtime_change_design")
        self.assertEqual(evaluate(prop, v), UNAVAILABLE)

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __contains__(self, key):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

        prop, v = pair()
        self.assertEqual(evaluate(Boom(prop), v), UNAVAILABLE)


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in TYPES:
            prop, v = pair(kind)
            first = evaluate(prop, v)
            for _ in range(5):
                self.assertEqual(evaluate(prop, v), first)
            self.assertEqual(evaluate(*pair(kind)), first)

    def test_no_input_mutation(self):
        for args in (pair(), pair(version="x"), ({"a": 1}, {"b": 2})):
            before = copy.deepcopy(args)
            evaluate(*args)
            self.assertEqual(args, before)

    def test_output_isolation(self):
        prop, v = pair()
        out = evaluate(prop, v)
        out["eligible"] = False
        out["execution_allowed"] = True
        out["request_id"] = "tampered"
        again = evaluate(prop, v)
        self.assertTrue(again["eligible"])
        self.assertIs(again["execution_allowed"], False)
        self.assertEqual(again["request_id"], prop["request_id"])
        u1, u2 = evaluate(None, None), evaluate(None, None)
        u1["eligible"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_execution_or_io(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        prop, v = pair("CREATE_CAPABILITY")
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
            evaluate(prop, v)
            evaluate(None, None)
            evaluate(dict(prop, goal=callable_trap), v)
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
