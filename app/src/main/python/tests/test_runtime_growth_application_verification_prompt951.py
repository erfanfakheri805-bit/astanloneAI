"""
Tests for Prompt 951 - Runtime Growth Application Verification.

Run directly:
    python -m unittest tests.test_runtime_growth_controlled_application_prompt951 -v
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
from runtime_growth import runtime_growth_application_verification as av
from runtime_growth import runtime_growth_controlled_application as ca
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

apply_tx = ca.apply_runtime_growth_transaction
verify = av.verify_runtime_growth_application
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_application_verification.py")
KEYS = ["version", "available", "status", "valid", "request_id", "verification_type",
        "application_verified", "persistent", "source_modified", "execution_verified"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "valid": False,
               "request_id": None, "verification_type": None, "application_verified": False,
               "persistent": False, "source_modified": False, "execution_verified": False}
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


def triple(kind=SUPPORTED_KIND, target=SUPPORTED_TARGET):
    c = contract(kind, target)
    t = transaction_for(c)
    return c, t, apply_tx(t, c)


class TestVerified(unittest.TestCase):
    def test_valid_application_verifies(self):
        c, t, a = triple()
        self.assertEqual(a["status"], "applied")
        self.assertEqual(verify(c, t, a), {
            "version": "1", "available": True, "status": "verified", "valid": True,
            "request_id": c["request_id"], "verification_type": "controlled_runtime_growth",
            "application_verified": True, "persistent": False, "source_modified": False,
            "execution_verified": True})

    def test_exact_output_key_set(self):
        self.assertEqual(list(verify(*triple())), KEYS)
        self.assertEqual(list(verify(None, None, None)), KEYS)
        self.assertEqual(set(av.FIELDS), set(KEYS))

    def test_deterministic(self):
        args = triple()
        first = verify(*args)
        for _ in range(5):
            self.assertEqual(verify(*args), first)
        self.assertEqual(verify(*triple()), first)

    def test_request_id_and_type(self):
        c, t, a = triple()
        out = verify(c, t, a)
        self.assertEqual(out["request_id"], c["request_id"])
        self.assertEqual(out["verification_type"], "controlled_runtime_growth")

    def test_flags_true_only_for_valid_application(self):
        out = verify(*triple())
        self.assertIs(out["application_verified"], True)
        self.assertIs(out["execution_verified"], True)
        self.assertIs(out["persistent"], False)
        self.assertIs(out["source_modified"], False)
        for args in (triple("CREATE_CAPABILITY"), triple("IMPROVE_CAPABILITY"),
                     triple(target="other"), (None, None, None)):
            bad = verify(*args)
            self.assertIs(bad["application_verified"], False)
            self.assertIs(bad["execution_verified"], False)
            self.assertIs(bad["valid"], False)
            self.assertIs(bad["persistent"], False)
            self.assertIs(bad["source_modified"], False)

    def test_no_permission_fields(self):
        out = verify(*triple())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "applied", "execution_attempted", "goal"):
            self.assertNotIn(name, out)

    def test_scope_mapping_unchanged(self):
        self.assertEqual(dict(pv.PROPOSAL_TYPE_SCOPES), SCOPES)
        self.assertNotIn("controlled_runtime_growth", pv.PROPOSAL_TYPE_SCOPES.values())


class TestRejected(unittest.TestCase):
    def rejected(self, c, t, a):
        out = verify(c, t, a)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_malformed_contract(self):
        c, t, a = triple()
        for bad in (list(c.items()), tuple(c), str(c), {"a": 1}, {}, None, 5, True, object()):
            self.rejected(bad, t, a)

    def test_malformed_transaction(self):
        c, t, a = triple()
        for bad in (list(t.items()), tuple(t), str(t), {"a": 1}, {}, None, 5, True, object()):
            self.rejected(c, bad, a)

    def test_malformed_application_result(self):
        c, t, a = triple()
        for bad in (list(a.items()), tuple(a), str(a), {"a": 1}, {}, None, 5, True, object()):
            self.rejected(c, t, bad)

    def test_forged_request_id(self):
        c, t, a = triple()
        for bad in ("", None, 5, "growth_req_forged"):
            self.rejected(c, dict(t, request_id=bad), a)
            self.rejected(c, t, dict(a, request_id=bad))
        self.rejected(c, t, dict(a, application_state=dict(a["application_state"],
                                                           request_id="growth_req_forged")))
        self.rejected(dict(c, request_id="growth_req_forged"), t, a)

    def test_contract_transaction_mismatch(self):
        c, t, a = triple()
        self.rejected(c, triple("CREATE_CAPABILITY")[1], a)
        self.rejected(c, triple(target="other")[1], a)
        self.rejected(c, dict(t, target="other"), a)

    def test_contract_result_mismatch(self):
        c, t, a = triple()
        c2 = dict(c, goal="a different goal")  # same trusted fields, still valid
        self.assertEqual(verify(c2, t, a)["status"], "verified")
        self.rejected(c, t, triple("CREATE_CAPABILITY")[2])
        self.rejected(c, t, dict(a, target="other"))
        self.rejected(c, t, dict(a, proposal_type="capability_creation"))

    def test_transaction_result_mismatch(self):
        c, t, a = triple()
        self.rejected(c, triple("IMPROVE_CAPABILITY")[1], triple()[2])
        self.rejected(c, t, apply_tx(None, None))
        self.rejected(c, dict(t, precondition_status="not_satisfied"), a)

    def test_wrong_target(self):
        c, t, a = triple()
        for target in ("other", "", "Runtime_Growth", None, 5):
            self.rejected(c, t, dict(a, target=target))
            bad = dict(c, target=target)
            self.rejected(bad, transaction_for(bad), a)

    def test_wrong_proposal_type(self):
        c, t, a = triple()
        for ptype in ("capability_creation", "capability_improvement", "other", None, 5):
            self.rejected(c, t, dict(a, proposal_type=ptype))
            bad = dict(c, proposal_type=ptype)
            self.rejected(bad, transaction_for(bad), a)

    def test_wrong_change_scope(self):
        c, t, a = triple()
        for scope in ("controlled_runtime_growth", "existing_capability_improvement_design",
                      "other", None, 5):
            self.rejected(c, t, dict(a, change_scope=scope))
            bad = dict(c, change_scope=scope)
            self.rejected(bad, transaction_for(bad), a)

    def test_wrong_application_mode(self):
        c, t, a = triple()
        for bad in ("uncontrolled", "", None, "Controlled", 5):
            self.rejected(c, t, dict(a, application_mode=bad))
            self.rejected(dict(c, application_mode=bad), t, a)

    def test_wrong_transaction_mode(self):
        c, t, a = triple()
        for bad in ("uncontrolled", "", None, "Controlled", 5):
            self.rejected(c, dict(t, transaction_mode=bad), a)
            self.rejected(c, t, dict(a, transaction_mode=bad))

    def test_execution_allowed_true_rejected(self):
        c, t, a = triple()
        bad = dict(c, execution_allowed=True)
        self.rejected(bad, t, a)
        self.rejected(bad, dict(t, execution_allowed=True), a)
        self.rejected(c, dict(t, execution_allowed=True), a)
        self.rejected(c, t, dict(a, execution_allowed=True))

    def test_execution_attempted_false_rejected(self):
        c, t, a = triple()
        self.rejected(c, t, dict(a, execution_attempted=False))

    def test_applied_false_rejected(self):
        c, t, a = triple()
        self.rejected(c, t, dict(a, applied=False))
        self.rejected(c, t, dict(a, applied=False, execution_attempted=False))

    def test_wrong_application_state(self):
        c, t, a = triple()
        s = a["application_state"]
        for bad in (None, {}, [], "x", dict(s, state="applied"), dict(s, state=None),
                    dict(s, operation="other"), dict(s, operation="runtime_growth"),
                    {k: s[k] for k in list(s)[:-1]}):
            self.rejected(c, t, dict(a, application_state=bad))

    def test_persistent_true_rejected(self):
        c, t, a = triple()
        s = a["application_state"]
        self.rejected(c, t, dict(a, application_state=dict(s, persistent=True)))
        self.rejected(c, t, dict(a, persistent=True))

    def test_source_modified_true_rejected(self):
        c, t, a = triple()
        s = a["application_state"]
        self.rejected(c, t, dict(a, application_state=dict(s, source_modified=True)))
        self.rejected(c, t, dict(a, source_modified=True))
        self.rejected(c, t, dict(a, application_state=dict(s, persistent=True,
                                                           source_modified=True)))

    def test_extra_and_missing_keys_rejected(self):
        c, t, a = triple()
        self.rejected(dict(c, extra=1), t, a)
        self.rejected(c, dict(t, extra=1), a)
        self.rejected(c, t, dict(a, extra=1))
        self.rejected(c, t, dict(a, application_state=dict(a["application_state"], extra=1)))
        for name in ca.FIELDS:
            bad = dict(a)
            del bad[name]
            self.rejected(c, t, bad)
        for name in tx.FIELDS:
            bad = dict(t)
            del bad[name]
            self.rejected(c, bad, a)

    def test_wrong_value_types_rejected(self):
        c, t, a = triple()
        s = a["application_state"]
        self.rejected(c, t, dict(a, available=1))
        self.rejected(c, t, dict(a, applied=1))
        self.rejected(c, t, dict(a, execution_attempted=1))
        self.rejected(c, t, dict(a, version=1))
        self.rejected(c, t, dict(a, application_state=dict(s, persistent=0)))
        self.rejected(c, t, dict(a, application_state=dict(s, source_modified=0)))
        self.rejected(c, dict(t, available=1), a)
        self.rejected(c, dict(t, execution_allowed=0), a)
        self.rejected(dict(c, execution_allowed=0), t, a)

    def test_not_applied_result_rejected(self):
        c, t, a = triple()
        self.rejected(c, t, dict(a, status="not_applied"))
        self.rejected(c, t, res.build_runtime_growth_application_result(c))
        self.rejected(c, t, dict(a, status="prepared"))
        self.rejected(c, t, dict(a, status="verified"))

    def test_unsupported_improve_runtime_target_rejected(self):
        c, t, a = triple(target="code_analysis")
        self.assertEqual(t["status"], "prepared")
        self.assertEqual(c["proposal_type"], "runtime_improvement")
        self.assertEqual(a, UNAVAILABLE_APPLICATION)
        self.rejected(c, t, a)
        # a forged "applied" result on that contract is refused too
        good = triple()[2]
        self.rejected(c, t, dict(good, target="code_analysis", request_id=c["request_id"],
                                 application_state=dict(good["application_state"],
                                                        request_id=c["request_id"])))

    def test_other_kinds_with_supported_target_rejected(self):
        for kind in ("CREATE_CAPABILITY", "IMPROVE_CAPABILITY"):
            c, t, a = triple(kind)
            self.assertEqual(t["status"], "prepared")
            self.rejected(c, t, a)
            self.rejected(c, t, triple()[2])

    def test_invalid_input_does_not_leak_untrusted_fields(self):
        c, t, a = triple()
        for args in ((dict(c, target="secret-target"), t, a), (c, dict(t, target="secret-target"), a),
                     (c, t, dict(a, target="secret-target", request_id="secret-id"))):
            out = verify(*args)
            self.assertEqual(out, UNAVAILABLE)
            self.assertNotIn("secret", repr(out))

    def test_raising_input_never_propagates(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

            def keys(self):
                raise RuntimeError("boom")

        c, t, a = triple()
        self.rejected(Boom(c), t, a)
        self.rejected(c, Boom(t), a)
        self.rejected(c, t, Boom(a))


UNAVAILABLE_APPLICATION = {
    "version": "1", "available": False, "status": "unavailable", "request_id": None,
    "proposal_type": None, "target": None, "change_scope": None, "application_mode": None,
    "transaction_mode": None, "execution_attempted": False, "applied": False,
    "application_state": None}


class TestPurity(unittest.TestCase):
    def test_no_input_mutation(self):
        for args in (triple(), triple("CREATE_CAPABILITY"), triple(target="other"),
                     ({"a": 1}, {"b": 2}, {"c": 3})):
            before = copy.deepcopy(args)
            verify(*args)
            self.assertEqual(args, before)

    def test_output_isolation(self):
        args = triple()
        out = verify(*args)
        out["status"] = "tampered"
        out["persistent"] = True
        out["execution_verified"] = False
        again = verify(*args)
        self.assertEqual(again["status"], "verified")
        self.assertIs(again["persistent"], False)
        self.assertIs(again["execution_verified"], True)
        u1, u2 = verify(None, None, None), verify(None, None, None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_filesystem_database_network_subprocess_or_code_execution(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

        args = triple()
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
            out = verify(*args)
            verify(None, None, None)
            verify(dict(args[0], goal=callable_trap), args[1], args[2])
        callable_trap.assert_not_called()
        self.assertIs(out["execution_verified"], True)
        self.assertEqual(state(), before)
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
                       "importlib", "os", "pathlib", "shutil"):
            self.assertNotIn("import " + banned, source)
        for rel in ("core/core.py",
                    "runtime_integration/bridge.py", "ael/interpreter.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("runtime_growth", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
