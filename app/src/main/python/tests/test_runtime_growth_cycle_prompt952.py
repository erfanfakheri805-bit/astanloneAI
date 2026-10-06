"""
Tests for Prompt 952 - Runtime Growth Controlled Cycle.

Run directly:
    python -m unittest tests.test_runtime_growth_cycle_prompt952 -v
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
from runtime_growth import runtime_growth_cycle as cy
from runtime_growth import runtime_growth_plan as rgp
from runtime_growth import runtime_growth_proposal as rgq
from runtime_growth import runtime_growth_proposal_validation as pv
from runtime_growth import runtime_growth_request as rgr
from runtime_growth import runtime_growth_request_validation as val

run = cy.run_controlled_runtime_growth_cycle
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PY_ROOT, "runtime_growth", "runtime_growth_cycle.py")
KEYS = ["version", "available", "status", "request_id", "request_status", "plan_status",
        "proposal_status", "boundary_status", "application_request_status", "contract_status",
        "transaction_status", "application_status", "verification_status",
        "application_verified", "persistent", "source_modified"]
UNAVAILABLE = {"version": "1", "available": False, "status": "unavailable", "request_id": None,
               "request_status": "unavailable", "plan_status": "unavailable",
               "proposal_status": "unavailable", "boundary_status": "unavailable",
               "application_request_status": "unavailable", "contract_status": "unavailable",
               "transaction_status": "unavailable", "application_status": "unavailable",
               "verification_status": "unavailable", "application_verified": False,
               "persistent": False, "source_modified": False}
# (name used in the cycle module, module, function name) in the required order
STAGES = [("create", rgr, "create_runtime_growth_request"),
          ("validate", val, "validate_runtime_growth_request"),
          ("analyze", rga, "analyze_runtime_growth_request"),
          ("plan", rgp, "build_runtime_growth_plan"),
          ("proposal", rgq, "build_runtime_growth_proposal"),
          ("proposal_validation", pv, "validate_runtime_growth_proposal"),
          ("boundary", ab, "evaluate_runtime_growth_application_boundary"),
          ("app_request", ar, "build_runtime_growth_application_request"),
          ("contract", ac, "build_runtime_growth_application_contract"),
          ("result", res, "build_runtime_growth_application_result"),
          ("transaction", tx, "build_runtime_growth_application_transaction"),
          ("apply", ca, "apply_runtime_growth_transaction"),
          ("verify", av, "verify_runtime_growth_application")]


def data(**over):
    d = {"kind": "IMPROVE_RUNTIME", "goal": "Grow the runtime safely",
         "target": "runtime_growth", "reason": "Controlled growth", "source": "runtime"}
    d.update(over)
    return d


def record_calls():
    """Patch every stage with a wrapper that records the call order."""
    calls = []
    patches = []
    depth = [0]  # later stages re-derive earlier ones internally; record top-level calls only
    for name, mod, fn in STAGES:
        real = getattr(mod, fn)

        def wrapper(*a, _real=real, _name=name, **k):
            if depth[0] == 0:
                calls.append(_name)
            depth[0] += 1
            try:
                return _real(*a, **k)
            finally:
                depth[0] -= 1

        patches.append(mock.patch.object(mod, fn, side_effect=wrapper))
    return calls, patches


class TestVerifiedCycle(unittest.TestCase):
    def test_full_cycle_verified(self):
        self.assertEqual(run(data()), {
            "version": "1", "available": True, "status": "verified",
            "request_id": rgr.create_runtime_growth_request(data())["request_id"],
            "request_status": "valid", "plan_status": "planned",
            "proposal_status": "proposed", "boundary_status": "eligible",
            "application_request_status": "ready", "contract_status": "contracted",
            "transaction_status": "prepared", "application_status": "applied",
            "verification_status": "verified", "application_verified": True,
            "persistent": False, "source_modified": False})

    def test_exact_16_keys(self):
        out = run(data())
        self.assertEqual(list(out), KEYS)
        self.assertEqual(len(out), 16)
        self.assertEqual(set(cy.FIELDS), set(KEYS))
        self.assertEqual(list(run(None)), KEYS)

    def test_each_status(self):
        out = run(data())
        for key, value in (("status", "verified"), ("request_status", "valid"),
                           ("plan_status", "planned"), ("proposal_status", "proposed"),
                           ("boundary_status", "eligible"),
                           ("application_request_status", "ready"),
                           ("contract_status", "contracted"),
                           ("transaction_status", "prepared"),
                           ("application_status", "applied"),
                           ("verification_status", "verified")):
            self.assertEqual(out[key], value, key)
        self.assertIs(out["available"], True)
        self.assertIs(out["application_verified"], True)
        self.assertIs(out["persistent"], False)
        self.assertIs(out["source_modified"], False)

    def test_deterministic_and_repeated(self):
        first = run(data())
        for _ in range(5):
            self.assertEqual(run(data()), first)
        self.assertEqual(run(copy.deepcopy(data())), first)

    def test_request_id_only_from_validated_request(self):
        d = data()
        out = run(d)
        self.assertEqual(out["request_id"], rgr.create_runtime_growth_request(d)["request_id"])
        # an id supplied in the input is an unexpected key and is never used
        self.assertEqual(run(dict(d, request_id="growth_req_forged")), UNAVAILABLE)
        # equivalent normalized input gives the same trusted id
        self.assertEqual(run(data(goal="  Grow   the runtime safely "))["request_id"],
                         out["request_id"])

    def test_no_claims_beyond_in_memory_verification(self):
        out = run(data())
        for name in ("approved", "approval", "authorized", "authorization", "permission",
                     "execution_allowed", "executed", "committed", "code", "goal", "target",
                     "change_scope", "persisted"):
            self.assertNotIn(name, out)
        self.assertIs(out["persistent"], False)
        self.assertIs(out["source_modified"], False)

    def test_stages_run_in_exact_order_without_skips(self):
        calls, patches = record_calls()
        for p in patches:
            p.start()
        try:
            out = run(data())
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(out["status"], "verified")
        self.assertEqual(calls, [name for name, _, _ in STAGES])


class TestRejected(unittest.TestCase):
    def rejected(self, d):
        out = run(d)
        self.assertEqual(out, UNAVAILABLE)
        self.assertEqual(list(out), KEYS)

    def test_unsupported_request_kind(self):
        for kind in ("DELETE_CAPABILITY", "improve_runtime", "", None, 5):
            self.rejected(data(kind=kind))

    def test_create_capability_rejected(self):
        self.rejected(data(kind="CREATE_CAPABILITY"))
        self.rejected(data(kind="CREATE_CAPABILITY", target="code_analysis"))

    def test_improve_capability_rejected(self):
        self.rejected(data(kind="IMPROVE_CAPABILITY"))
        self.rejected(data(kind="IMPROVE_CAPABILITY", target="code_analysis"))

    def test_improve_runtime_other_target_rejected(self):
        for target in ("code_analysis", "other", "Runtime_Growth", "runtime"):
            self.rejected(data(target=target))

    def test_malformed_input(self):
        for bad in (None, 5, "x", [], (), True, object(), {}, {"kind": "IMPROVE_RUNTIME"},
                    list(data().items())):
            self.rejected(bad)
        self.rejected(data(goal=""))
        self.rejected(data(goal=5))
        self.rejected(data(target=None))
        self.rejected(data(goal="x" * 501))

    def test_forged_or_invalid_request(self):
        self.rejected(dict(data(), request_id="growth_req_forged"))
        self.rejected(dict(data(), status="requested"))
        self.rejected(dict(data(), execution_allowed=True))
        self.rejected(dict(data(), extra=1))
        self.rejected(rgr.create_runtime_growth_request(data()))  # an already-built request

    def test_no_untrusted_field_leaks(self):
        out = run(data(kind="CREATE_CAPABILITY", goal="secret-goal", target="secret-target"))
        self.assertEqual(out, UNAVAILABLE)
        self.assertNotIn("secret", repr(out))

    def test_invalid_stage_cannot_be_bypassed(self):
        """Each stage returning unavailable stops the cycle; later stages never run."""
        for idx, (name, mod, fn) in enumerate(STAGES):
            calls, patches = record_calls()
            for p in patches:
                p.start()
            try:
                with mock.patch.object(mod, fn, side_effect=lambda *a, _n=name, **k:
                                       (calls.append(_n), {"status": "unavailable"})[1]):
                    out = run(data())
            finally:
                for p in patches:
                    p.stop()
            self.assertEqual(out, UNAVAILABLE, name)
            self.assertEqual(calls[-1], name)
            self.assertEqual(calls, [n for n, _, _ in STAGES[:idx + 1]], name)

    def test_non_dict_stage_output_rejected(self):
        for name, mod, fn in STAGES:
            for bad in (None, "verified", 5, [], {}):
                with mock.patch.object(mod, fn, return_value=bad):
                    self.assertEqual(run(data()), UNAVAILABLE, (name, bad))

    def test_stage_exception_never_propagates(self):
        for name, mod, fn in STAGES:
            with mock.patch.object(mod, fn, side_effect=RuntimeError("boom")):
                self.assertEqual(run(data()), UNAVAILABLE, name)

    def test_application_failure_cannot_verify(self):
        unavailable_app = ca._unavailable_application()
        with mock.patch.object(ca, "apply_runtime_growth_transaction",
                               return_value=unavailable_app):
            self.assertEqual(run(data()), UNAVAILABLE)
        # an application result that was never really applied
        real = ca.apply_runtime_growth_transaction
        with mock.patch.object(ca, "apply_runtime_growth_transaction",
                               side_effect=lambda t, c: dict(real(t, c), status="not_applied")):
            self.assertEqual(run(data()), UNAVAILABLE)

    def test_verification_failure_cannot_verify(self):
        real = ca.apply_runtime_growth_transaction

        def tampered(state_change):
            def apply(t, c):
                out = real(t, c)
                out["application_state"] = dict(out["application_state"], **state_change)
                return out
            return apply

        # Prompt 950 "applied" but Prompt 951 (real verifier) rejects the state
        for change in ({"persistent": True}, {"source_modified": True},
                       {"state": "applied"}, {"operation": "other"},
                       {"request_id": "growth_req_forged"}):
            with mock.patch.object(ca, "apply_runtime_growth_transaction",
                                   side_effect=tampered(change)):
                self.assertEqual(run(data()), UNAVAILABLE, change)
        with mock.patch.object(av, "verify_runtime_growth_application",
                               return_value=av._unavailable_verification()):
            self.assertEqual(run(data()), UNAVAILABLE)
        good = av.verify_runtime_growth_application(
            *self._chain())
        for change in ({"persistent": True}, {"source_modified": True},
                       {"application_verified": False}, {"execution_verified": False},
                       {"valid": False}, {"status": "unavailable"},
                       {"request_id": "growth_req_forged"}, {"request_id": None}):
            with mock.patch.object(av, "verify_runtime_growth_application",
                                   return_value=dict(good, **change)):
                self.assertEqual(run(data()), UNAVAILABLE, change)

    @staticmethod
    def _chain():
        req = rgr.create_runtime_growth_request(data())
        v = val.validate_runtime_growth_request(req)
        a = rga.analyze_runtime_growth_request(req, v)
        p = rgp.build_runtime_growth_plan(req, v, a)
        prop = rgq.build_runtime_growth_proposal(req, v, a, p)
        pvld = pv.validate_runtime_growth_proposal(prop)
        b = ab.evaluate_runtime_growth_application_boundary(prop, pvld)
        r = ar.build_runtime_growth_application_request(prop, pvld, b)
        c = ac.build_runtime_growth_application_contract(r)
        t = tx.build_runtime_growth_application_transaction(
            c, res.build_runtime_growth_application_result(c))
        return c, t, ca.apply_runtime_growth_transaction(t, c)

    def test_request_id_mismatch_between_stages_rejected(self):
        real = rgr.create_runtime_growth_request
        # the id of the Prompt 939 request must be the id every later stage carries
        with mock.patch.object(rgr, "create_runtime_growth_request",
                               side_effect=lambda d: dict(real(d), request_id="growth_req_other")):
            self.assertEqual(run(data()), UNAVAILABLE)


class TestPurity(unittest.TestCase):
    def test_input_not_mutated(self):
        for d in (data(), data(kind="CREATE_CAPABILITY"), data(target="other"), {"a": [1]}):
            before = copy.deepcopy(d)
            run(d)
            self.assertEqual(d, before)

    def test_output_isolation(self):
        out = run(data())
        out["status"] = "tampered"
        out["persistent"] = True
        self.assertEqual(run(data())["status"], "verified")
        self.assertIs(run(data())["persistent"], False)
        u1, u2 = run(None), run(None)
        u1["available"] = True
        self.assertEqual(u2, UNAVAILABLE)

    def test_no_filesystem_database_network_subprocess_or_code_execution(self):
        def trap(*a, **k):
            raise AssertionError("forbidden access")

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
                mock.patch("os.rename", side_effect=trap), \
                mock.patch("os.mkdir", side_effect=trap), \
                mock.patch("builtins.exec", side_effect=trap), \
                mock.patch("builtins.eval", side_effect=trap), \
                mock.patch("time.time", side_effect=trap), \
                mock.patch("random.random", side_effect=trap), \
                mock.patch("uuid.uuid4", side_effect=trap), \
                mock.patch("builtins.open", side_effect=trap):
            out = run(data())
            run(None)
            run(data(kind="CREATE_CAPABILITY"))
        self.assertEqual(out["status"], "verified")
        self.assertEqual(state(), before)  # includes data/memory.db

    def test_module_source_is_pure_and_core_untouched(self):
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
