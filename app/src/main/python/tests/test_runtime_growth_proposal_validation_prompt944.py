"""
Tests for Prompt 944 - Runtime Growth Proposal Validation.

Run directly:
    python -m unittest tests.test_runtime_growth_proposal_validation_prompt944 -v
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
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

validate = pv.validate_runtime_growth_proposal
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_proposal_validation.py")
RESULT_KEYS = ["available", "status", "valid", "error_count", "errors"]
OK = {"available": True, "status": "valid", "valid": True, "error_count": 0, "errors": []}
UNAVAILABLE = {"available": False, "status": "unavailable", "valid": False,
               "error_count": 0, "errors": []}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")


def proposal(kind="IMPROVE_CAPABILITY", **over):
    d = {"kind": kind, "goal": "Answer questions faster", "target": "code_analysis",
         "reason": "Users wait too long", "source": "runtime"}
    req = rgr.create_runtime_growth_request(d)
    v = val.validate_runtime_growth_request(req)
    a = rga.analyze_runtime_growth_request(req, v)
    p = rgp.build_runtime_growth_plan(req, v, a)
    out = rgq.build_runtime_growth_proposal(req, v, a, p)
    out.update(over)
    return out


def errors_of(p):
    r = validate(p)
    assert r["status"] == "invalid" and r["available"] is True and r["valid"] is False, r
    assert r["error_count"] == len(r["errors"])
    return r["errors"]


class TestValid(unittest.TestCase):
    def test_all_kinds_valid(self):
        for kind in KINDS:
            self.assertEqual(validate(proposal(kind)), OK)

    def test_exact_keys_and_status(self):
        r = validate(proposal())
        self.assertEqual(list(r), RESULT_KEYS)
        self.assertEqual((r["available"], r["status"], r["valid"], r["error_count"], r["errors"]),
                         (True, "valid", True, 0, []))

    def test_empty_strings_for_target_goal_reason_are_still_strings(self):
        self.assertEqual(validate(proposal(target="", goal="", reason="")), OK)


class TestInvalid(unittest.TestCase):
    def test_unexpected_key(self):
        self.assertEqual(errors_of(dict(proposal(), extra=1)), ["unexpected_field"])

    def test_missing_keys_in_fixed_order(self):
        p = proposal()
        del p["goal"]
        del p["version"]
        del p["descriptive_only"]
        self.assertEqual(errors_of(p), ["missing_version", "missing_goal",
                                        "missing_descriptive_only"])
        self.assertEqual(len(errors_of({})), 12)

    def test_wrong_version(self):
        for bad in ("2", 1, None, ""):
            self.assertEqual(errors_of(proposal(version=bad)), ["invalid_version"])

    def test_wrong_available(self):
        for bad in (False, 1, "True", None):
            self.assertEqual(errors_of(proposal(available=bad)), ["invalid_available"])

    def test_wrong_status(self):
        for bad in ("unavailable", "planned", "", None, 1):
            self.assertEqual(errors_of(proposal(status=bad)), ["invalid_status"])

    def test_invalid_proposal_type(self):
        for bad in ("other", "", None, 5, ["capability_creation"]):
            self.assertEqual(errors_of(proposal(proposal_type=bad)), ["invalid_proposal_type"])

    def test_invalid_request_id(self):
        for bad in ("", None, 5, ["x"]):
            self.assertEqual(errors_of(proposal(request_id=bad)), ["invalid_request_id"])

    def test_invalid_target_goal_reason(self):
        for name in ("target", "goal", "reason"):
            for bad in (None, 5, ["x"], {"a": 1}):
                self.assertEqual(errors_of(proposal(**{name: bad})), ["invalid_" + name])

    def test_invalid_plan_steps(self):
        for bad in ([], None, "steps", ("a",), ["a", 1], [None], {"a": "b"}):
            self.assertEqual(errors_of(proposal(plan_steps=bad)), ["invalid_plan_steps"])

    def test_invalid_change_scope(self):
        for bad in ("other", "", None, 5):
            self.assertEqual(errors_of(proposal(change_scope=bad)), ["invalid_change_scope"])

    def test_mismatched_type_and_scope(self):
        p = proposal("CREATE_CAPABILITY", change_scope="bounded_runtime_change_design")
        self.assertEqual(errors_of(p), ["change_scope_type_mismatch"])
        for kind in KINDS:
            for other in pv.PROPOSAL_TYPE_SCOPES.values():
                p = proposal(kind, change_scope=other)
                good = other == proposal(kind)["change_scope"]
                self.assertEqual(validate(p)["valid"], good)

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 0, "False", None):
            self.assertEqual(errors_of(proposal(execution_allowed=bad)),
                             ["invalid_execution_allowed"])

    def test_descriptive_only_false_rejected(self):
        for bad in (False, 1, "True", None):
            self.assertEqual(errors_of(proposal(descriptive_only=bad)),
                             ["invalid_descriptive_only"])

    def test_the_prompt943_unavailable_proposal_is_invalid(self):
        self.assertEqual(errors_of(rgq.build_runtime_growth_proposal(None, None, None, None)),
                         ["invalid_available", "invalid_status", "invalid_proposal_type",
                          "invalid_request_id", "invalid_target", "invalid_goal",
                          "invalid_reason", "invalid_plan_steps", "invalid_change_scope"])

    def test_deterministic_error_ordering(self):
        p = proposal(version="9", available=False, status="x", proposal_type="x",
                     request_id="", target=1, goal=1, reason=1, plan_steps=[],
                     change_scope="x", execution_allowed=True, descriptive_only=False)
        p["extra"] = 1
        expected = ["unexpected_field", "invalid_version", "invalid_available", "invalid_status",
                    "invalid_proposal_type", "invalid_request_id", "invalid_target",
                    "invalid_goal", "invalid_reason", "invalid_plan_steps",
                    "invalid_change_scope", "invalid_execution_allowed",
                    "invalid_descriptive_only"]
        for _ in range(3):
            self.assertEqual(errors_of(p), expected)
        self.assertEqual(errors_of(dict(reversed(list(p.items())))), expected)


class TestUnavailable(unittest.TestCase):
    def test_non_dict_input(self):
        for bad in (None, "x", 5, [], (), True, object(), [proposal()]):
            self.assertEqual(validate(bad), UNAVAILABLE)

    def test_reading_raising_is_unavailable(self):
        class Boom(dict):
            def __contains__(self, key):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

        self.assertEqual(validate(Boom(proposal())), UNAVAILABLE)


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for p in (proposal(), proposal(version="x"), None):
            first = validate(p)
            for _ in range(5):
                self.assertEqual(validate(p), first)

    def test_no_input_mutation_or_repair(self):
        for p in (proposal(), proposal(version="x", plan_steps=[], goal=1), {"a": 1}):
            before = copy.deepcopy(p)
            validate(p)
            self.assertEqual(p, before)
        p = proposal(plan_steps=["a"])
        steps = p["plan_steps"]
        validate(p)
        self.assertIs(p["plan_steps"], steps)

    def test_output_isolation(self):
        p = proposal(version="x")
        r = validate(p)
        r["errors"].append("tampered")
        r["valid"] = True
        self.assertEqual(validate(p)["errors"], ["invalid_version"])
        a, b = validate(None), validate(None)
        a["errors"].append("x")
        self.assertEqual(b, UNAVAILABLE)

    def test_no_execution_or_io(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        p = proposal()
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
            validate(p)
            validate(None)
            validate(dict(p, goal=callable_trap, plan_steps=[callable_trap]))
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
