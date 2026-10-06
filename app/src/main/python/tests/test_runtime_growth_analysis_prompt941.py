"""
Tests for Prompt 941 - Runtime Growth Analysis.

`analyze_runtime_growth_request(request, validation)` is a pure, deterministic,
descriptive analysis of a request already validated by Prompt 940.

Run directly:
    python -m unittest tests.test_runtime_growth_analysis_prompt941 -v
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
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_growth import runtime_growth_analysis as rga
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

analyze = rga.analyze_runtime_growth_request
create = rgr.create_runtime_growth_request
validate = val.validate_runtime_growth_request
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_analysis.py")
KEYS = ["version", "available", "status", "kind", "target", "goal", "reason", "source",
        "analysis_type", "needs_creation", "needs_improvement", "needs_runtime_change",
        "descriptive_only"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "kind": None,
               "target": None, "goal": None, "reason": None, "source": None,
               "analysis_type": None, "needs_creation": False, "needs_improvement": False,
               "needs_runtime_change": False, "descriptive_only": True}
EXPECTED = {
    "CREATE_CAPABILITY": ("capability_creation", True, False, False),
    "IMPROVE_CAPABILITY": ("capability_improvement", False, True, False),
    "IMPROVE_RUNTIME": ("runtime_improvement", False, False, True),
}


def request(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    d.update(over)
    return create(d)


def pair(kind="IMPROVE_CAPABILITY", **over):
    req = request(kind, **over)
    return req, validate(req)


def tree_state(root):
    out = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return out


class TestValidAnalysis(unittest.TestCase):
    def check(self, kind):
        req, v = pair(kind)
        out = analyze(req, v)
        atype, c, i, r = EXPECTED[kind]
        self.assertEqual(list(out), KEYS)
        self.assertEqual(out, {"version": "1", "available": True, "status": "analyzed",
                               "kind": kind, "target": req["target"], "goal": req["goal"],
                               "reason": req["reason"], "source": req["source"],
                               "analysis_type": atype, "needs_creation": c,
                               "needs_improvement": i, "needs_runtime_change": r,
                               "descriptive_only": True})

    def test_create_capability(self):
        self.check("CREATE_CAPABILITY")

    def test_improve_capability(self):
        self.check("IMPROVE_CAPABILITY")

    def test_improve_runtime(self):
        self.check("IMPROVE_RUNTIME")

    def test_exact_flags_for_every_kind(self):
        for kind, (atype, c, i, r) in EXPECTED.items():
            out = analyze(*pair(kind))
            self.assertEqual((out["analysis_type"], out["needs_creation"],
                              out["needs_improvement"], out["needs_runtime_change"]),
                             (atype, c, i, r))
            self.assertEqual(sum([out["needs_creation"], out["needs_improvement"],
                                  out["needs_runtime_change"]]), 1)

    def test_goal_text_does_not_influence_the_analysis(self):
        for goal in ("create a brand new capability", "improve the runtime", "delete everything"):
            out = analyze(*pair("IMPROVE_CAPABILITY", goal=goal))
            self.assertEqual(out["analysis_type"], "capability_improvement")
            self.assertEqual(out["goal"], goal)


class TestUnusableInput(unittest.TestCase):
    def test_invalid_request(self):
        req = request()
        v = validate(req)
        bad = dict(req, request_id="growth_req_forged")
        self.assertEqual(analyze(bad, v), UNAVAILABLE)
        self.assertEqual(analyze(dict(req, kind="DELETE"), v), UNAVAILABLE)
        self.assertEqual(analyze(rgr.create_runtime_growth_request({}), v), UNAVAILABLE)

    def test_invalid_validation(self):
        req = request()
        for bad in (validate(dict(req, status="x")),
                    dict(validate(req), valid=False),
                    dict(validate(req), status="invalid"),
                    dict(validate(req), error_count=1),
                    dict(validate(req), errors=["x"]),
                    dict(validate(req), available=False)):
            self.assertEqual(analyze(req, bad), UNAVAILABLE)

    def test_unavailable_request(self):
        v = validate(request())
        for bad in (None, "x", 5, [], (), object()):
            self.assertEqual(analyze(bad, v), UNAVAILABLE)

    def test_unavailable_validation(self):
        req = request()
        for bad in (None, "x", 5, [], validate(None), {}):
            self.assertEqual(analyze(req, bad), UNAVAILABLE)

    def test_validation_cannot_vouch_for_an_invalid_request(self):
        req = request()
        forged = dict(req, request_id="growth_req_0000000000000000")
        self.assertEqual(analyze(forged, validate(req)), UNAVAILABLE)

    def test_reading_raising_never_propagates(self):
        class Boom(dict):
            def __getitem__(self, key):
                raise RuntimeError("boom")

            def get(self, *a):
                raise RuntimeError("boom")

        req, v = pair()
        self.assertEqual(analyze(Boom(req), v), UNAVAILABLE)
        self.assertEqual(analyze(req, Boom(v)), UNAVAILABLE)


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in EXPECTED:
            req, v = pair(kind)
            first = analyze(req, v)
            for _ in range(5):
                self.assertEqual(analyze(req, v), first)
            self.assertEqual(analyze(*pair(kind)), first)

    def test_no_input_mutation(self):
        for kind in EXPECTED:
            req, v = pair(kind)
            req0, v0 = copy.deepcopy(req), copy.deepcopy(v)
            analyze(req, v)
            self.assertEqual((req, v), (req0, v0))
        bad = {"kind": "x"}
        bad0 = copy.deepcopy(bad)
        analyze(bad, {"valid": True})
        self.assertEqual(bad, bad0)

    def test_output_isolation(self):
        req, v = pair()
        a = analyze(req, v)
        a["goal"] = "tampered"
        a["needs_creation"] = True
        a["descriptive_only"] = False
        b = analyze(req, v)
        self.assertIsNot(a, b)
        self.assertEqual(b["goal"], req["goal"])
        self.assertFalse(b["needs_creation"])
        self.assertTrue(b["descriptive_only"])
        self.assertEqual(req, request())
        u1, u2 = analyze(None, None), analyze(None, None)
        u1["status"] = "tampered"
        self.assertEqual(u2, UNAVAILABLE)

    def test_descriptive_only_always_true(self):
        for kind in EXPECTED:
            self.assertIs(analyze(*pair(kind))["descriptive_only"], True)
        for args in ((None, None), ({}, {}), (request(), None), ("x", "y")):
            self.assertIs(analyze(*args)["descriptive_only"], True)

    def test_no_execution_fields_or_effects(self):
        out = analyze(*pair())
        for name in ("execute", "executed", "approved", "approval", "code", "generated_code",
                     "modified", "files", "created", "applied"):
            self.assertNotIn(name, out)
        trap = mock.Mock()
        req = dict(request(), goal=trap)
        self.assertEqual(analyze(req, validate(request())), UNAVAILABLE)
        trap.assert_not_called()

    def test_no_filesystem_database_network_or_execution(self):
        req, v = pair("CREATE_CAPABILITY")
        root = os.path.dirname(PY_ROOT)
        before = tree_state(root)
        with tempfile.TemporaryDirectory() as tmp:
            def trap(*a, **k):
                raise AssertionError("forbidden access")

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
                for args in ((req, v), (None, None), (req, None)):
                    analyze(*args)
            self.assertEqual(os.listdir(tmp), [])
        self.assertEqual(tree_state(root), before)

    def test_module_source_is_pure(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"runtime_growth"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__",
                                                "input", "print", "setattr", "delattr", "getattr"})

    def test_not_wired_into_the_runtime(self):
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
