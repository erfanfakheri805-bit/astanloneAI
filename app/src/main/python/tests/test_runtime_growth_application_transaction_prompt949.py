"""
Tests for Prompt 949 - Runtime Growth Application Transaction.

Run directly:
    python -m unittest tests.test_runtime_growth_application_transaction_prompt949 -v
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
from runtime_growth import runtime_growth_application_transaction as tx
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

build = tx.build_runtime_growth_application_transaction
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_transaction.py")
KEYS = ["version", "available", "status", "request_id", "proposal_type", "target",
        "change_scope", "transaction_mode", "precondition_status", "execution_allowed",
        "applied"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "proposal_type": None, "target": None, "change_scope": None,
               "transaction_mode": None, "precondition_status": "not_satisfied",
               "execution_allowed": False, "applied": False}
SCOPES = {"capability_creation": "capability_definition_and_implementation_design",
          "capability_improvement": "existing_capability_improvement_design",
          "runtime_improvement": "bounded_runtime_change_design"}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")


def pair(kind="IMPROVE_CAPABILITY", **over):
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
    c = ac.build_runtime_growth_application_contract(r)
    c.update(over)
    return c, res.build_runtime_growth_application_result(c)


class TestPrepared(unittest.TestCase):
    def test_all_kinds(self):
        seen = set()
        for kind in KINDS:
            c, r = pair(kind)
            out = build(c, r)
            self.assertEqual(list(out), KEYS)
            self.assertEqual(out, {"version": "1", "available": True, "status": "prepared",
                                   "request_id": c["request_id"],
                                   "proposal_type": c["proposal_type"], "target": c["target"],
                                   "change_scope": c["change_scope"],
                                   "transaction_mode": "controlled",
                                   "precondition_status": "satisfied",
                                   "execution_allowed": False, "applied": False})
            self.assertEqual(out["change_scope"], SCOPES[out["proposal_type"]])
            seen.add(out["proposal_type"])
        self.assertEqual(seen, set(SCOPES))

    def test_transaction_remains_non_executable(self):
        out = build(*pair())
        self.assertIs(out["execution_allowed"], False)
        self.assertIs(out["applied"], False)
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "executed", "execution_attempted", "committed", "commit", "code", "goal"):
            self.assertNotIn(name, out)

    def test_unavailable_has_same_keys(self):
        self.assertEqual(list(build(None, None)), KEYS)


class TestRejected(unittest.TestCase):
    def rejected(self, c, r):
        out = build(c, r)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_malformed_contract(self):
        c, r = pair()
        for bad in (list(c.items()), tuple(c), str(c), {"a": 1}, {}, None, 5):
            self.rejected(bad, r)

    def test_wrong_key_sets(self):
        c, r = pair()
        self.rejected(dict(c, extra=1), r)
        for name in ac.FIELDS:
            bad = dict(c)
            del bad[name]
            self.rejected(bad, r)

    def test_wrong_value_types(self):
        c, r = pair()
        for name, bad in (("version", 1), ("available", 1), ("status", None),
                          ("request_id", 5), ("proposal_type", ["x"]), ("target", None),
                          ("goal", 5), ("change_scope", None), ("application_mode", 5),
                          ("execution_allowed", 0)):
            self.rejected(dict(c, **{name: bad}), r)

    def test_forged_request_id(self):
        c, r = pair()
        for bad in ("", None, 5):
            self.rejected(dict(c, request_id=bad), r)
        # a structurally valid but different id no longer matches the supplied result
        self.rejected(dict(c, request_id="growth_req_forged"), r)
        self.rejected(c, dict(r, request_id="growth_req_forged"))

    def test_wrong_type_scope_combination(self):
        c, r = pair("IMPROVE_CAPABILITY")
        for ptype, scope in SCOPES.items():
            if ptype != c["proposal_type"]:
                bad = dict(c, change_scope=scope)
                self.rejected(bad, res.build_runtime_growth_application_result(bad))
        bad = dict(c, change_scope="other")
        self.rejected(bad, r)

    def test_wrong_application_mode(self):
        c, r = pair()
        for bad in ("uncontrolled", "", None, "Controlled"):
            self.rejected(dict(c, application_mode=bad), r)
            self.rejected(c, dict(r, application_mode=bad))

    def test_execution_allowed_true_rejected(self):
        c, r = pair()
        bad = dict(c, execution_allowed=True)
        self.rejected(bad, r)
        self.rejected(bad, res.build_runtime_growth_application_result(bad))
        self.rejected(bad, dict(r, execution_allowed=True))

    def test_valid_result_accepted(self):
        c, r = pair()
        self.assertTrue(build(c, r)["available"])
        self.assertEqual(r, res.build_runtime_growth_application_result(c))

    def test_forged_result_rejected(self):
        c, r = pair()
        self.rejected(c, {"version": "1", "available": True, "status": "not_applied"})
        self.rejected(c, dict(r, extra=1))
        for bad in (None, "x", 5, [], ()):
            self.rejected(c, bad)

    def test_mismatched_result_rejected(self):
        c, r = pair("IMPROVE_CAPABILITY")
        self.rejected(c, pair("CREATE_CAPABILITY")[1])
        self.rejected(c, pair("IMPROVE_CAPABILITY", target="other")[1])
        self.rejected(c, dict(r, proposal_type="runtime_improvement"))
        self.rejected(c, dict(r, target="other"))
        self.rejected(c, dict(r, change_scope="bounded_runtime_change_design"))
        self.rejected(c, res.build_runtime_growth_application_result(None))

    def test_ready_status_result_rejected(self):
        c, r = pair()
        self.rejected(c, dict(r, status="ready"))
        self.rejected(c, dict(r, status="prepared"))

    def test_execution_attempted_true_rejected(self):
        c, r = pair()
        self.rejected(c, dict(r, execution_attempted=True))

    def test_applied_true_rejected(self):
        c, r = pair()
        self.rejected(c, dict(r, applied=True))
        self.rejected(c, dict(r, applied=True, execution_attempted=True, status="applied"))

    def test_invalid_input_does_not_leak_untrusted_fields(self):
        c, r = pair()
        out = build(dict(c, target="secret-target", version="2"), r)
        self.assertEqual(out, UNAVAILABLE)
        self.assertNotIn("secret", repr(out))
        out = build(c, dict(r, target="secret-target"))
        self.assertEqual(out, UNAVAILABLE)
        self.assertNotIn("secret", repr(out))

    def test_unavailable_inputs(self):
        c, r = pair()
        for bad in (None, "x", 5, [], (), True, object()):
            self.rejected(bad, r)
            self.rejected(c, bad)
        self.rejected(None, None)

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def keys(self):
                raise RuntimeError("boom")

        c, r = pair()
        self.rejected(Boom(c), r)
        self.assertIn(build(c, Boom(r))["status"], ("prepared", "unavailable"))


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        for kind in KINDS:
            c, r = pair(kind)
            first = build(c, r)
            for _ in range(5):
                self.assertEqual(build(c, r), first)
            self.assertEqual(build(*pair(kind)), first)

    def test_no_input_mutation(self):
        for args in (pair(), pair(version="x"), ({"a": 1}, {"b": 2})):
            before = copy.deepcopy(args)
            build(*args)
            self.assertEqual(args, before)

    def test_output_isolation(self):
        c, r = pair()
        out = build(c, r)
        out["status"] = "tampered"
        out["applied"] = True
        out["execution_allowed"] = True
        again = build(c, r)
        self.assertEqual(again["status"], "prepared")
        self.assertIs(again["applied"], False)
        self.assertIs(again["execution_allowed"], False)
        u1, u2 = build(None, None), build(None, None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_filesystem_network_subprocess_or_code_execution(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        c, r = pair("CREATE_CAPABILITY")
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
            out = build(c, r)
            build(None, None)
            build(dict(c, goal=callable_trap), r)
        callable_trap.assert_not_called()
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
