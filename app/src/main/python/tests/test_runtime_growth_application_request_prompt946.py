"""
Tests for Prompt 946 - Runtime Growth Application Request.

Run directly:
    python -m unittest tests.test_runtime_growth_application_request_prompt946 -v
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
from runtime_growth import runtime_growth_application_request as ar
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = ar.build_runtime_growth_application_request
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_request.py")
KEYS = ["version", "available", "status", "request_id", "proposal_type", "target", "goal",
        "change_scope", "application_mode", "execution_allowed"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "proposal_type": None, "target": None, "goal": None, "change_scope": None,
               "application_mode": None, "execution_allowed": False}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")


def chain(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    p = rgp.build_runtime_growth_plan(req, v, a)
    prop = rgq.build_runtime_growth_proposal(req, v, a, p)
    prop.update(over)
    pvld = pv.validate_runtime_growth_proposal(prop)
    return prop, pvld, ab.evaluate_runtime_growth_application_boundary(prop, pvld)


class TestReady(unittest.TestCase):
    def test_all_kinds(self):
        for kind in KINDS:
            prop, v, b = chain(kind)
            out = build(prop, v, b)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "ready",
                                   "request_id": prop["request_id"],
                                   "proposal_type": prop["proposal_type"],
                                   "target": prop["target"], "goal": prop["goal"],
                                   "change_scope": prop["change_scope"],
                                   "application_mode": "controlled",
                                   "execution_allowed": False})

    def test_copied_values_per_kind(self):
        expected = {"CREATE_CAPABILITY": ("capability_creation",
                                          "capability_definition_and_implementation_design"),
                    "IMPROVE_CAPABILITY": ("capability_improvement",
                                           "existing_capability_improvement_design"),
                    "IMPROVE_RUNTIME": ("runtime_improvement", "bounded_runtime_change_design")}
        for kind, (ptype, scope) in expected.items():
            out = build(*chain(kind))
            self.assertEqual((out["proposal_type"], out["change_scope"]), (ptype, scope))
            self.assertEqual((out["target"], out["goal"]), ("code_analysis",
                                                           "Answer questions faster"))
            self.assertTrue(out["request_id"].startswith("growth_req_"))

    def test_ready_is_not_applied_or_permitted(self):
        out = build(*chain())
        self.assertIs(out["execution_allowed"], False)
        for name in ("applied", "approved", "approval", "authorization", "execute", "code",
                     "descriptive_only", "eligible"):
            self.assertNotIn(name, out)

    def test_unavailable_has_same_keys(self):
        self.assertEqual(list(build(None, None, None)), KEYS)


class TestRejected(unittest.TestCase):
    def test_invalid_proposal(self):
        prop, v, b = chain()
        self.assertEqual(build(dict(prop, version="2"), v, b), UNAVAILABLE)
        bad = dict(prop, goal=5)
        bv = pv.validate_runtime_growth_proposal(bad)
        self.assertEqual(build(bad, bv, ab.evaluate_runtime_growth_application_boundary(bad, bv)),
                         UNAVAILABLE)

    def test_forged_proposal_id(self):
        prop, v, b = chain()
        out = build(dict(prop, request_id=""), v, b)
        self.assertEqual(out, UNAVAILABLE)
        # a non-empty forged id is structurally valid but not the boundary's id
        forged = dict(prop, request_id="growth_req_forged")
        self.assertEqual(build(forged, v, b), UNAVAILABLE)

    def test_forged_validation(self):
        prop, v, b = chain()
        for bad in (dict(v, valid=False), dict(v, status="invalid"), dict(v, extra=1),
                    dict(v, error_count=1), {}, None, "x", 5, []):
            self.assertEqual(build(prop, bad, b), UNAVAILABLE)
        bad_prop = dict(prop, descriptive_only=False)
        self.assertEqual(build(bad_prop, dict(v), b), UNAVAILABLE)

    def test_mismatched_validation(self):
        prop, v, b = chain()
        bad_prop = dict(prop, version="9")
        bad_v = pv.validate_runtime_growth_proposal(bad_prop)
        self.assertEqual(build(prop, bad_v, b), UNAVAILABLE)
        self.assertEqual(build(bad_prop, v, b), UNAVAILABLE)
        self.assertEqual(build(bad_prop, bad_v, b), UNAVAILABLE)

    def test_forged_boundary(self):
        prop, v, b = chain()
        for bad in (dict(b, eligible=False), dict(b, status="unavailable"),
                    dict(b, request_id="growth_req_forged"), dict(b, extra=1), {}, None, "x",
                    5, []):
            self.assertEqual(build(prop, v, bad), UNAVAILABLE)

    def test_mismatched_boundary(self):
        prop, v, b = chain("IMPROVE_CAPABILITY")
        other = chain("CREATE_CAPABILITY")[2]
        self.assertEqual(build(prop, v, other), UNAVAILABLE)
        self.assertEqual(build(prop, v, dict(b, proposal_type="runtime_improvement")),
                         UNAVAILABLE)

    def test_ineligible_boundary(self):
        prop, v, b = chain()
        for bad in (UNAVAILABLE_BOUNDARY, dict(b, eligible=False, status="unavailable")):
            self.assertEqual(build(prop, v, bad), UNAVAILABLE)
        bad_prop = dict(prop, proposal_type="other")
        bv = pv.validate_runtime_growth_proposal(bad_prop)
        bb = ab.evaluate_runtime_growth_application_boundary(bad_prop, bv)
        self.assertFalse(bb["eligible"])
        self.assertEqual(build(bad_prop, bv, bb), UNAVAILABLE)

    def test_boundary_execution_allowed_true_rejected(self):
        prop, v, b = chain()
        self.assertEqual(build(prop, v, dict(b, execution_allowed=True)), UNAVAILABLE)
        bad_prop = dict(prop, execution_allowed=True)
        bv = pv.validate_runtime_growth_proposal(bad_prop)
        self.assertEqual(build(bad_prop, bv, dict(b)), UNAVAILABLE)

    def test_boundary_descriptive_only_false_rejected(self):
        prop, v, b = chain()
        self.assertEqual(build(prop, v, dict(b, descriptive_only=False)), UNAVAILABLE)
        bad_prop = dict(prop, descriptive_only=False)
        bv = pv.validate_runtime_growth_proposal(bad_prop)
        self.assertEqual(build(bad_prop, bv, dict(b)), UNAVAILABLE)

    def test_unavailable_inputs(self):
        base = chain()
        for i in range(3):
            for bad in (None, "x", 5, [], ()):
                args = list(base)
                args[i] = bad
                self.assertEqual(build(*args), UNAVAILABLE)

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __contains__(self, key):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

        prop, v, b = chain()
        self.assertEqual(build(Boom(prop), v, b), UNAVAILABLE)


UNAVAILABLE_BOUNDARY = {"version": "1", "available": False, "status": "unavailable",
                        "eligible": False, "request_id": None, "proposal_type": None,
                        "execution_allowed": False, "descriptive_only": True}


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in KINDS:
            args = chain(kind)
            first = build(*args)
            for _ in range(5):
                self.assertEqual(build(*args), first)
            self.assertEqual(build(*chain(kind)), first)

    def test_no_input_mutation(self):
        for args in (chain(), chain(version="x"), ({"a": 1}, {"b": 2}, {"c": 3})):
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)

    def test_output_isolation(self):
        args = chain()
        out = build(*args)
        out["status"] = "tampered"
        out["execution_allowed"] = True
        out["goal"] = "tampered"
        again = build(*args)
        self.assertEqual(again["status"], "ready")
        self.assertIs(again["execution_allowed"], False)
        self.assertEqual(again["goal"], args[0]["goal"])
        u1, u2 = build(None, None, None), build(None, None, None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_execution_or_io(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        args = chain("CREATE_CAPABILITY")
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
            build(*args)
            build(None, None, None)
            build(dict(args[0], goal=callable_trap), args[1], args[2])
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
