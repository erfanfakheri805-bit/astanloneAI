"""
Tests for Prompt 943 - Runtime Growth Proposal.

Run directly:
    python -m unittest tests.test_runtime_growth_proposal_prompt943 -v
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
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = rgq.build_runtime_growth_proposal
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_proposal.py")
KEYS = ["version", "available", "status", "proposal_type", "request_id", "target", "goal",
        "reason", "plan_steps", "change_scope", "execution_allowed", "descriptive_only"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable",
               "proposal_type": None, "request_id": None, "target": None, "goal": None,
               "reason": None, "plan_steps": [], "change_scope": None,
               "execution_allowed": False, "descriptive_only": True}
EXPECTED = {
    "CREATE_CAPABILITY": ("capability_creation",
                          "capability_definition_and_implementation_design"),
    "IMPROVE_CAPABILITY": ("capability_improvement", "existing_capability_improvement_design"),
    "IMPROVE_RUNTIME": ("runtime_improvement", "bounded_runtime_change_design"),
}


def chain(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    d.update(over)
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    return req, v, a, rgp.build_runtime_growth_plan(req, v, a)


class TestValidProposals(unittest.TestCase):
    def test_all_kinds(self):
        for kind, (ptype, scope) in EXPECTED.items():
            req, v, a, p = chain(kind)
            out = build(req, v, a, p)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "proposed",
                                   "proposal_type": ptype, "request_id": req["request_id"],
                                   "target": req["target"], "goal": req["goal"],
                                   "reason": req["reason"], "plan_steps": p["steps"],
                                   "change_scope": scope, "execution_allowed": False,
                                   "descriptive_only": True})
            self.assertEqual(len(out["plan_steps"]), 4)
            self.assertIs(out["execution_allowed"], False)
            self.assertIs(out["descriptive_only"], True)

    def test_goal_text_does_not_change_type(self):
        out = build(*chain("IMPROVE_RUNTIME", goal="create a new capability"))
        self.assertEqual(out["proposal_type"], "runtime_improvement")

    def test_unavailable_shape(self):
        self.assertEqual(list(build(None, None, None, None)), KEYS)
        self.assertEqual(build(None, None, None, None), UNAVAILABLE)


class TestRejected(unittest.TestCase):
    def test_invalid_request(self):
        req, v, a, p = chain()
        self.assertEqual(build(dict(req, kind="DELETE"), v, a, p), UNAVAILABLE)
        self.assertEqual(build(dict(req, status="x"), v, a, p), UNAVAILABLE)
        self.assertEqual(build(rgr.create_runtime_growth_request({}), v, a, p), UNAVAILABLE)

    def test_forged_request_id(self):
        req, v, a, p = chain()
        forged = dict(req, request_id="growth_req_0000000000000000")
        self.assertEqual(build(forged, v, a, p), UNAVAILABLE)
        self.assertEqual(build(forged, val.validate_runtime_growth_request(forged), a, p),
                         UNAVAILABLE)
        self.assertEqual(build(req, v, a, dict(p, request_id=forged["request_id"])),
                         UNAVAILABLE)

    def test_invalid_validation(self):
        req, v, a, p = chain()
        for bad in (dict(v, valid=False), dict(v, status="invalid"), dict(v, error_count=1),
                    dict(v, errors=["x"]), dict(v, available=False), {}, dict(v, extra=1)):
            self.assertEqual(build(req, bad, a, p), UNAVAILABLE)

    def test_mismatched_validation(self):
        req, v, a, p = chain()
        invalid_req = dict(req, goal="  untrimmed  ")
        self.assertEqual(build(invalid_req, v, a, p), UNAVAILABLE)
        self.assertEqual(build(req, val.validate_runtime_growth_request(invalid_req), a, p),
                         UNAVAILABLE)

    def test_invalid_analysis(self):
        req, v, a, p = chain()
        for bad in (dict(a, status="unavailable"), dict(a, available=False),
                    dict(a, descriptive_only=False), {}, dict(a, extra=1),
                    rga.analyze_runtime_growth_request(None, None)):
            self.assertEqual(build(req, v, bad, p), UNAVAILABLE)

    def test_mismatched_analysis(self):
        req, v, a, p = chain("IMPROVE_CAPABILITY")
        other = chain("CREATE_CAPABILITY")[2]
        self.assertEqual(build(req, v, other, p), UNAVAILABLE)
        self.assertEqual(build(req, v, chain(goal="Different goal")[2], p), UNAVAILABLE)

    def test_invalid_plan(self):
        req, v, a, p = chain()
        for bad in (dict(p, status="unavailable"), dict(p, available=False), {},
                    dict(p, extra=1), dict(p, descriptive_only=False), dict(p, steps=[]),
                    rgp.build_runtime_growth_plan(None, None, None)):
            self.assertEqual(build(req, v, a, bad), UNAVAILABLE)

    def test_mismatched_plan(self):
        req, v, a, p = chain("IMPROVE_CAPABILITY")
        self.assertEqual(build(req, v, a, chain("CREATE_CAPABILITY")[3]), UNAVAILABLE)
        self.assertEqual(build(req, v, a, chain(goal="Different goal")[3]), UNAVAILABLE)
        self.assertEqual(build(req, v, a, dict(p, steps=list(reversed(p["steps"])))),
                         UNAVAILABLE)

    def test_unavailable_inputs(self):
        chain_ = chain()
        for i in range(4):
            for bad in (None, "x", 5, [], ()):
                args = list(chain_)
                args[i] = bad
                self.assertEqual(build(*args), UNAVAILABLE)

    def test_raising_request_never_propagates(self):
        class Boom(dict):
            def __getitem__(self, key):
                raise RuntimeError("boom")

            def get(self, *a):
                raise RuntimeError("boom")

        req, v, a, p = chain()
        self.assertEqual(build(Boom(req), v, a, p), UNAVAILABLE)


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in EXPECTED:
            args = chain(kind)
            first = build(*args)
            for _ in range(5):
                self.assertEqual(build(*args), first)
            self.assertEqual(build(*chain(kind)), first)

    def test_no_input_mutation(self):
        for kind in EXPECTED:
            args = chain(kind)
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)
        bad = ({"kind": "x"}, {"valid": True}, {"status": "analyzed"}, {"steps": ["a"]})
        before = copy.deepcopy(bad)
        build(*bad)
        self.assertEqual(bad, before)

    def test_output_isolation(self):
        args = chain()
        out = build(*args)
        out["plan_steps"].append("tampered")
        out["execution_allowed"] = True
        out["goal"] = "tampered"
        self.assertEqual(args[3]["steps"], rgp.build_runtime_growth_plan(*args[:3])["steps"])
        self.assertEqual(len(args[3]["steps"]), 4)
        again = build(*args)
        self.assertEqual(len(again["plan_steps"]), 4)
        self.assertIs(again["execution_allowed"], False)
        self.assertIsNot(again["plan_steps"], args[3]["steps"])
        u1, u2 = build(None, None, None, None), build(None, None, None, None)
        u1["plan_steps"].append("x")
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
            build(None, None, None, None)
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
