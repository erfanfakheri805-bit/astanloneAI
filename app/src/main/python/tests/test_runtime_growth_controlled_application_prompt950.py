"""
Tests for Prompt 950 - Runtime Growth Controlled Application.

Run directly:
    python -m unittest tests.test_runtime_growth_controlled_application_prompt950 -v
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
import time  # noqa: F401
import unittest
import uuid  # noqa: F401
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_growth import runtime_growth_analysis as rga
from runtime_growth import runtime_growth_application_boundary as ab
from runtime_growth import runtime_growth_application_contract as ac
from runtime_growth import runtime_growth_application_request as ar
from runtime_growth import runtime_growth_application_result as res
from runtime_growth import runtime_growth_application_transaction as tx
from runtime_growth import runtime_growth_controlled_application as ca
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

apply_tx = ca.apply_runtime_growth_transaction
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_controlled_application.py")
KEYS = ["version", "available", "status", "request_id", "proposal_type", "target",
        "change_scope", "application_mode", "transaction_mode", "execution_attempted",
        "applied", "application_state"]
STATE_KEYS = ["state", "request_id", "operation", "persistent", "source_modified"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "proposal_type": None, "target": None, "change_scope": None,
               "application_mode": None, "transaction_mode": None,
               "execution_attempted": False, "applied": False, "application_state": None}
SCOPES = {"capability_creation": "capability_definition_and_implementation_design",
          "capability_improvement": "existing_capability_improvement_design",
          "runtime_improvement": "bounded_runtime_change_design"}
KINDS = ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY", "IMPROVE_RUNTIME")
SUPPORTED_KIND = "IMPROVE_RUNTIME"
SUPPORTED_TARGET = "runtime_growth"


def contract(kind=SUPPORTED_KIND, target=SUPPORTED_TARGET, **over):
    d = {"kind": kind, "goal": "Grow the runtime safely", "target": target,
         "reason": "Controlled growth", "source": "runtime"}
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
    return c


def transaction_for(c):
    return tx.build_runtime_growth_application_transaction(
        c, res.build_runtime_growth_application_result(c))


def pair(kind=SUPPORTED_KIND, target=SUPPORTED_TARGET, **over):
    c = contract(kind, target, **over)
    return transaction_for(c), c


class TestApplied(unittest.TestCase):
    def test_valid_supported_application(self):
        t, c = pair()
        self.assertEqual(t["status"], "prepared")
        out = apply_tx(t, c)
        self.assertEqual(out, {
            "version": "1", "available": True, "status": "applied",
            "request_id": c["request_id"], "proposal_type": "runtime_improvement",
            "target": "runtime_growth", "change_scope": "bounded_runtime_change_design",
            "application_mode": "controlled", "transaction_mode": "controlled",
            "execution_attempted": True, "applied": True,
            "application_state": {"state": "applied_in_memory", "request_id": c["request_id"],
                                  "operation": "controlled_runtime_growth",
                                  "persistent": False, "source_modified": False}})

    def test_exact_output_key_set(self):
        out = apply_tx(*pair())
        self.assertEqual(list(out), KEYS)
        self.assertEqual(set(out), set(ca.FIELDS))
        self.assertEqual(list(apply_tx(None, None)), KEYS)

    def test_exact_application_state_key_set(self):
        state = apply_tx(*pair())["application_state"]
        self.assertEqual(list(state), STATE_KEYS)
        self.assertEqual(len(state), 5)

    def test_deterministic_repeated_calls(self):
        t, c = pair()
        first = apply_tx(t, c)
        for _ in range(5):
            self.assertEqual(apply_tx(t, c), first)
        self.assertEqual(apply_tx(*pair()), first)

    def test_request_id_only_from_trusted_contract(self):
        t, c = pair()
        out = apply_tx(t, c)
        self.assertEqual(out["request_id"], c["request_id"])
        self.assertEqual(out["application_state"]["request_id"], c["request_id"])
        self.assertEqual(apply_tx(dict(t, request_id="growth_req_forged"), c), UNAVAILABLE)

    def test_proposal_type_target_scope_copied(self):
        t, c = pair()
        out = apply_tx(t, c)
        self.assertEqual(out["proposal_type"], c["proposal_type"])
        self.assertEqual(out["target"], c["target"])
        self.assertEqual(out["change_scope"], c["change_scope"])
        self.assertEqual(out["change_scope"], SCOPES[out["proposal_type"]])

    def test_state_values(self):
        state = apply_tx(*pair())["application_state"]
        self.assertEqual(state["state"], "applied_in_memory")
        self.assertIs(state["persistent"], False)
        self.assertIs(state["source_modified"], False)
        self.assertEqual(state["operation"], "controlled_runtime_growth")

    def test_modes_and_flags_only_for_supported_operation(self):
        out = apply_tx(*pair())
        self.assertEqual(out["application_mode"], "controlled")
        self.assertEqual(out["transaction_mode"], "controlled")
        self.assertIs(out["execution_attempted"], True)
        self.assertIs(out["applied"], True)
        for bad in (apply_tx(*pair("CREATE_CAPABILITY")), apply_tx(*pair("IMPROVE_CAPABILITY")),
                    apply_tx(*pair(target="other")), apply_tx(None, None)):
            self.assertIs(bad["execution_attempted"], False)
            self.assertIs(bad["applied"], False)

    def test_no_permission_fields(self):
        out = apply_tx(*pair())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "committed", "commit", "code", "goal"):
            self.assertNotIn(name, out)


class TestRejected(unittest.TestCase):
    def rejected(self, t, c):
        out = apply_tx(t, c)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_malformed_transaction(self):
        t, c = pair()
        for bad in (list(t.items()), tuple(t), str(t), {"a": 1}, {}, None, 5, True, object()):
            self.rejected(bad, c)
        for name in tx.FIELDS:
            bad = dict(t)
            del bad[name]
            self.rejected(bad, c)

    def test_malformed_contract(self):
        t, c = pair()
        for bad in (list(c.items()), tuple(c), str(c), {"a": 1}, {}, None, 5, True, object()):
            self.rejected(t, bad)
        for name in ac.FIELDS:
            bad = dict(c)
            del bad[name]
            self.rejected(t, bad)
        for name, bad in (("version", 1), ("available", 1), ("status", None),
                          ("request_id", 5), ("proposal_type", ["x"]), ("target", None),
                          ("goal", 5), ("change_scope", None), ("application_mode", 5),
                          ("execution_allowed", 0)):
            self.rejected(t, dict(c, **{name: bad}))

    def test_forged_request_id(self):
        t, c = pair()
        for bad in ("", None, 5, "growth_req_forged"):
            self.rejected(dict(t, request_id=bad), c)
        self.rejected(t, dict(c, request_id="growth_req_forged"))
        self.rejected(t, dict(c, request_id=""))

    def test_mismatched_transaction(self):
        t, c = pair()
        self.rejected(pair("CREATE_CAPABILITY")[0], c)
        self.rejected(pair(target="other")[0], c)
        self.rejected(dict(t, proposal_type="capability_creation"), c)
        self.rejected(dict(t, target="other"), c)
        self.rejected(dict(t, change_scope="existing_capability_improvement_design"), c)
        self.rejected(dict(t, precondition_status="not_satisfied"), c)
        self.rejected(tx.build_runtime_growth_application_transaction(None, None), c)

    def test_value_type_forgery_rejected(self):
        t, c = pair()
        self.rejected(dict(t, available=1), c)
        self.rejected(dict(t, applied=0), c)
        self.rejected(dict(t, execution_allowed=0), c)

    def test_wrong_transaction_status(self):
        t, c = pair()
        for bad in ("applied", "ready", "unavailable", "", None, 5):
            self.rejected(dict(t, status=bad), c)

    def test_wrong_transaction_mode(self):
        t, c = pair()
        for bad in ("uncontrolled", "", None, "Controlled", 5):
            self.rejected(dict(t, transaction_mode=bad), c)
        self.rejected(t, dict(c, application_mode="uncontrolled"))

    def test_execution_allowed_true_rejected(self):
        t, c = pair()
        self.rejected(dict(t, execution_allowed=True), c)
        bad = dict(c, execution_allowed=True)
        self.rejected(t, bad)
        self.rejected(transaction_for(bad), bad)

    def test_unsupported_target_rejected(self):
        for target in ("other", "", "Runtime_Growth", "code_analysis"):
            self.rejected(*pair(target=target))
        t, c = pair()
        for target in ("runtime_growth ", " runtime_growth", "RUNTIME_GROWTH", None, 5):
            bad = dict(c, target=target)
            self.rejected(transaction_for(bad), bad)
            self.rejected(dict(t, target=target), c)

    def test_unsupported_change_scope_rejected(self):
        t, c = pair()
        for scope in ("controlled_runtime_growth", "other", "", None, 5):
            bad = dict(c, change_scope=scope)
            self.rejected(transaction_for(bad), bad)
            self.rejected(dict(t, change_scope=scope), c)

    def test_unsupported_target_scope_combination_rejected(self):
        t, c = pair()
        for ptype, scope in SCOPES.items():
            if ptype != "runtime_improvement":
                bad = dict(c, change_scope=scope)
                self.rejected(transaction_for(bad), bad)
                bad = dict(c, proposal_type=ptype)
                self.rejected(transaction_for(bad), bad)
        bad = dict(c, proposal_type="capability_improvement",
                   change_scope="existing_capability_improvement_design")
        self.rejected(transaction_for(bad), bad)

    def test_already_applied_transaction_rejected(self):
        t, c = pair()
        self.rejected(dict(t, applied=True), c)
        self.rejected(dict(t, applied=True, status="applied"), c)
        self.rejected(dict(t, applied=True, status="applied", execution_allowed=True), c)
        self.rejected(apply_tx(t, c), c)  # a prior application output is not a transaction

    def test_extra_transaction_keys_rejected(self):
        t, c = pair()
        self.rejected(dict(t, extra=1), c)
        self.rejected(dict(t, execution_attempted=True), c)
        self.rejected(dict(t, application_state={}), c)

    def test_extra_contract_keys_rejected(self):
        t, c = pair()
        self.rejected(t, dict(c, extra=1))
        self.rejected(t, dict(c, approved=True))

    def test_no_bypass_for_other_proposal_kinds(self):
        # 31. CREATE_CAPABILITY, even with the supported target
        t, c = pair("CREATE_CAPABILITY")
        self.assertEqual(t["status"], "prepared")
        self.rejected(t, c)
        # 32. IMPROVE_CAPABILITY, even with the supported target
        t, c = pair("IMPROVE_CAPABILITY")
        self.assertEqual(t["status"], "prepared")
        self.rejected(t, c)
        # 33. IMPROVE_RUNTIME with another target
        t, c = pair("IMPROVE_RUNTIME", target="code_analysis")
        self.assertEqual(t["status"], "prepared")
        self.rejected(t, c)
        # a transaction from one kind never applies against another kind's contract
        self.rejected(pair("CREATE_CAPABILITY")[0], contract())
        self.rejected(pair("IMPROVE_CAPABILITY")[0], contract())
        self.rejected(pair()[0], contract("CREATE_CAPABILITY"))

    def test_malformed_application_state_cannot_be_produced(self):
        t, c = pair()
        good = ca._build_application_state(c["request_id"])
        self.assertTrue(ca._is_valid_application_state(good, c["request_id"]))
        for bad in (dict(good, persistent=True), dict(good, source_modified=True),
                    dict(good, state="applied"), dict(good, operation="other"),
                    dict(good, extra=1), dict(good, persistent=0), dict(good, request_id="x"),
                    {k: good[k] for k in list(good)[:-1]}, None, [], "x"):
            self.assertFalse(ca._is_valid_application_state(bad, c["request_id"]))
        with mock.patch.object(ca, "_build_application_state",
                               return_value=dict(good, persistent=True)):
            self.rejected(t, c)

    def test_invalid_input_does_not_leak_untrusted_fields(self):
        t, c = pair()
        for args in ((dict(t, target="secret-target"), c),
                     (t, dict(c, target="secret-target", version="2")),
                     (pair(target="secret-target"))):
            out = apply_tx(*args)
            self.assertEqual(out, UNAVAILABLE)
            self.assertNotIn("secret", repr(out))

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def keys(self):
                raise RuntimeError("boom")

        t, c = pair()
        self.rejected(Boom(c), t)
        self.assertIn(apply_tx(Boom(t), c)["status"], ("applied", "unavailable"))


class TestPurity(unittest.TestCase):
    def test_no_input_mutation(self):
        for args in (pair(), pair("CREATE_CAPABILITY"), pair(version="x"), ({"a": 1}, {"b": 2})):
            before = copy.deepcopy(args)
            apply_tx(*args)
            self.assertEqual(args, before)

    def test_output_isolation(self):
        t, c = pair()
        out = apply_tx(t, c)
        out["status"] = "tampered"
        out["application_state"]["persistent"] = True
        out["application_state"]["source_modified"] = True
        again = apply_tx(t, c)
        self.assertEqual(again["status"], "applied")
        self.assertIs(again["application_state"]["persistent"], False)
        self.assertIs(again["application_state"]["source_modified"], False)
        u1, u2 = apply_tx(None, None), apply_tx(None, None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_filesystem_database_network_subprocess_or_code_execution(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        t, c = pair()
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
        callable_trap = mock.Mock()
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
            out = apply_tx(t, c)
            apply_tx(None, None)
            apply_tx(t, dict(c, goal=callable_trap))
        callable_trap.assert_not_called()
        self.assertIs(out["applied"], True)
        self.assertEqual(state(), before)  # no project-tree mutation
        with open(db_path, "rb") as h:
            self.assertEqual(hashlib.sha256(h.read()).hexdigest(), db_before)

    def test_module_source_is_pure_and_not_wired(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
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
        for banned in ("subprocess", "socket", "sqlite3", "random", "uuid", "time", "datetime",
                       "importlib", "os.", "pathlib", "shutil"):
            self.assertNotIn("import " + banned.rstrip("."), source)
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
