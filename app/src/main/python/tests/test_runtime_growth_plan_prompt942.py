"""
Tests for Prompt 942 - Runtime Growth Plan.

Run directly:
    python -m unittest tests.test_runtime_growth_plan_prompt942 -v
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
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = rgp.build_runtime_growth_plan
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_plan.py")
KEYS = ["version", "available", "status", "plan_type", "request_id", "target", "goal",
        "reason", "steps", "descriptive_only"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "plan_type": None,
               "request_id": None, "target": None, "goal": None, "reason": None, "steps": [],
               "descriptive_only": True}
EXPECTED = {
    "CREATE_CAPABILITY": ("capability_creation", [
        "define capability", "validate capability definition",
        "design implementation", "verify proposed change"]),
    "IMPROVE_CAPABILITY": ("capability_improvement", [
        "inspect existing capability", "identify improvement target",
        "design improvement", "verify proposed change"]),
    "IMPROVE_RUNTIME": ("runtime_improvement", [
        "inspect runtime target", "identify bounded improvement",
        "design runtime change", "verify proposed change"]),
}


def chain(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    d.update(over)
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    return req, v, rga.analyze_runtime_growth_request(req, v)


class TestValidPlans(unittest.TestCase):
    def test_all_kinds(self):
        for kind, (ptype, steps) in EXPECTED.items():
            req, v, a = chain(kind)
            out = build(req, v, a)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "planned",
                                   "plan_type": ptype, "request_id": req["request_id"],
                                   "target": req["target"], "goal": req["goal"],
                                   "reason": req["reason"], "steps": steps,
                                   "descriptive_only": True})
            self.assertEqual(len(out["steps"]), 4)

    def test_goal_text_does_not_change_plan(self):
        out = build(*chain("IMPROVE_RUNTIME", goal="create a new capability"))
        self.assertEqual(out["plan_type"], "runtime_improvement")

    def test_unavailable_has_same_ten_keys(self):
        self.assertEqual(list(build(None, None, None)), KEYS)
        self.assertEqual(build(None, None, None), UNAVAILABLE)


class TestRejected(unittest.TestCase):
    def test_invalid_request(self):
        req, v, a = chain()
        bad = dict(req, kind="DELETE")
        self.assertEqual(build(bad, v, a), UNAVAILABLE)
        self.assertEqual(build(dict(req, status="x"), v, a), UNAVAILABLE)
        self.assertEqual(build(rgr.create_runtime_growth_request({}), v, a), UNAVAILABLE)

    def test_invalid_validation(self):
        req, v, a = chain()
        for bad in (dict(v, valid=False), dict(v, status="invalid"), dict(v, error_count=1),
                    dict(v, errors=["x"]), dict(v, available=False), {}, dict(v, extra=1)):
            self.assertEqual(build(req, bad, a), UNAVAILABLE)

    def test_mismatched_validation(self):
        req, v, a = chain("IMPROVE_CAPABILITY")
        self.assertEqual(build(req, dict(v, error_count=0, errors=[], valid=True,
                                         status="invalid"), a), UNAVAILABLE)
        invalid_req = dict(req, goal="  untrimmed  ")
        self.assertEqual(build(invalid_req, v, a), UNAVAILABLE)

    def test_invalid_analysis(self):
        req, v, a = chain()
        for bad in (dict(a, status="unavailable"), dict(a, available=False),
                    dict(a, descriptive_only=False), {}, dict(a, extra=1),
                    rga.analyze_runtime_growth_request(None, None)):
            self.assertEqual(build(req, v, bad), UNAVAILABLE)

    def test_mismatched_analysis(self):
        req, v, a = chain("IMPROVE_CAPABILITY")
        _, _, other = chain("CREATE_CAPABILITY")
        self.assertEqual(build(req, v, other), UNAVAILABLE)
        _, _, other2 = chain("IMPROVE_CAPABILITY", goal="Different goal")
        self.assertEqual(build(req, v, other2), UNAVAILABLE)
        self.assertEqual(build(req, v, dict(a, needs_creation=True)), UNAVAILABLE)

    def test_forged_request_id(self):
        req, v, a = chain()
        forged = dict(req, request_id="growth_req_0000000000000000")
        self.assertEqual(build(forged, v, a), UNAVAILABLE)
        self.assertEqual(build(forged, val.validate_runtime_growth_request(forged), a),
                         UNAVAILABLE)

    def test_unavailable_input(self):
        req, v, a = chain()
        for bad in (None, "x", 5, [], ()):
            self.assertEqual(build(bad, v, a), UNAVAILABLE)
            self.assertEqual(build(req, bad, a), UNAVAILABLE)
            self.assertEqual(build(req, v, bad), UNAVAILABLE)

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __getitem__(self, key):
                raise RuntimeError("boom")

            def get(self, *a):
                raise RuntimeError("boom")

            def __eq__(self, other):
                raise RuntimeError("boom")

        req, v, a = chain()
        self.assertEqual(build(Boom(req), v, a), UNAVAILABLE)
        for args in ((req, Boom(v), a), (req, v, Boom(a))):
            self.assertIn(build(*args)["status"], ("planned", "unavailable"))


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in EXPECTED:
            req, v, a = chain(kind)
            first = build(req, v, a)
            for _ in range(5):
                self.assertEqual(build(req, v, a), first)
            self.assertEqual(build(*chain(kind)), first)

    def test_no_input_mutation(self):
        for kind in EXPECTED:
            args = chain(kind)
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)
        bad = ({"kind": "x"}, {"valid": True}, {"status": "analyzed"})
        before = copy.deepcopy(bad)
        build(*bad)
        self.assertEqual(bad, before)

    def test_output_isolation(self):
        req, v, a = chain()
        out = build(req, v, a)
        out["steps"].append("tampered")
        out["goal"] = "tampered"
        out["descriptive_only"] = False
        again = build(req, v, a)
        self.assertEqual(again["steps"], EXPECTED["IMPROVE_CAPABILITY"][1])
        self.assertEqual(again["goal"], req["goal"])
        self.assertTrue(again["descriptive_only"])
        u1, u2 = build(None, None, None), build(None, None, None)
        u1["steps"].append("x")
        self.assertEqual(u2, UNAVAILABLE)

    def test_isolation_from_execution(self):
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
        self.assertEqual(state(), before)
        for name in ("execute", "approved", "code", "applied", "files", "modified"):
            self.assertNotIn(name, build(*args))

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
